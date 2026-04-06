"""FastAPI REST server for HPA-MDO.

Exposes the full MDO pipeline as HTTP endpoints, enabling:
    - Web dashboards
    - Remote batch jobs
    - AI agent orchestration (autoresearch, etc.)
    - Cross-platform team collaboration (any OS with a browser)

Launch:
    uvicorn hpa_mdo.api.server:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    from fastapi import FastAPI, HTTPException, UploadFile, File
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel as PydanticModel
except ImportError:
    raise ImportError("FastAPI not installed. Run: pip install 'hpa-mdo[api]'")

from hpa_mdo.core.config import HPAConfig, FlightConditionConfig, WeightConfig, WingConfig
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.aero.vsp_aero import VSPAeroParser
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.structure.beam_model import EulerBernoulliBeam
from hpa_mdo.structure.spar import TubularSpar
from hpa_mdo.structure.optimizer import SparOptimizer
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.fsi.coupling import FSICoupling


app = FastAPI(
    title="HPA-MDO API",
    description="Human-Powered Aircraft Multidisciplinary Design Optimization",
    version="0.1.0",
)

# Global state
_material_db = MaterialDB()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class OptimizeRequest(PydanticModel):
    """Request body for the optimize endpoint."""
    config: dict[str, Any]
    lod_file_path: Optional[str] = None
    aoa_deg: float = 3.0


class OptimizeResponse(PydanticModel):
    success: bool
    message: str
    spar_mass_full_kg: Optional[float] = None
    max_stress_MPa: Optional[float] = None
    allowable_stress_MPa: Optional[float] = None
    tip_deflection_m: Optional[float] = None
    d_i_root_mm: Optional[float] = None
    d_i_tip_mm: Optional[float] = None


class MaterialResponse(PydanticModel):
    name: str
    E_GPa: float
    density_kg_m3: float
    tensile_strength_MPa: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/materials")
async def list_materials():
    """List all available materials."""
    result = {}
    for key in _material_db.list_materials():
        m = _material_db.get(key)
        result[key] = {
            "name": m.name,
            "E_GPa": m.E / 1e9,
            "density_kg_m3": m.density,
            "tensile_strength_MPa": m.tensile_strength / 1e6,
        }
    return result


@app.get("/materials/{key}")
async def get_material(key: str):
    try:
        m = _material_db.get(key)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "name": m.name,
        "E_GPa": m.E / 1e9,
        "density_kg_m3": m.density,
        "tensile_strength_MPa": m.tensile_strength / 1e6,
    }


@app.post("/optimize", response_model=OptimizeResponse)
async def run_optimization(req: OptimizeRequest):
    """Run a full spar optimization from config + aero data."""
    try:
        cfg = HPAConfig(**req.config)
        aircraft = Aircraft.from_config(cfg)
        material = _material_db.get(cfg.spar.material)

        # Parse aero data
        if req.lod_file_path:
            parser = VSPAeroParser(req.lod_file_path)
            parser.parse()
            aero_load = parser.get_load_at_aoa(req.aoa_deg)
        else:
            raise HTTPException(400, "lod_file_path is required")

        # Build spar and mapper
        spar = TubularSpar.from_wing_geometry(aircraft.wing, cfg.spar, material)
        mapper = LoadMapper()
        mapped = mapper.map_loads(aero_load, spar.y, scale_factor=cfg.flight.load_factor)

        # Optimize
        beam = EulerBernoulliBeam()
        half_span = aircraft.wing.half_span
        target_defl = half_span * np.tan(np.radians(cfg.wing.dihedral_tip_deg))

        opt = SparOptimizer(
            spar=spar,
            beam_solver=beam,
            f_ext=mapped["lift_per_span"],
            safety_factor=cfg.spar.safety_factor,
            max_tip_deflection=target_defl,
        )
        result = opt.optimize(method=cfg.solver.optimizer_method)

        return OptimizeResponse(
            success=result.success,
            message=result.message,
            spar_mass_full_kg=result.spar_mass_full_kg,
            max_stress_MPa=result.max_stress_Pa / 1e6,
            allowable_stress_MPa=result.allowable_stress_Pa / 1e6,
            tip_deflection_m=result.tip_deflection_m,
            d_i_root_mm=result.d_i_root * 1000,
            d_i_tip_mm=result.d_i_tip * 1000,
        )

    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.post("/export/ansys-apdl")
async def export_ansys_apdl(req: OptimizeRequest):
    """Run optimization and return ANSYS APDL .mac file."""
    try:
        cfg = HPAConfig(**req.config)
        aircraft = Aircraft.from_config(cfg)
        material = _material_db.get(cfg.spar.material)

        parser = VSPAeroParser(req.lod_file_path)
        parser.parse()
        aero_load = parser.get_load_at_aoa(req.aoa_deg)

        spar = TubularSpar.from_wing_geometry(aircraft.wing, cfg.spar, material)
        mapper = LoadMapper()
        mapped = mapper.map_loads(aero_load, spar.y, scale_factor=cfg.flight.load_factor)

        beam = EulerBernoulliBeam()
        half_span = aircraft.wing.half_span
        target_defl = half_span * np.tan(np.radians(cfg.wing.dihedral_tip_deg))

        opt = SparOptimizer(
            spar=spar, beam_solver=beam, f_ext=mapped["lift_per_span"],
            safety_factor=cfg.spar.safety_factor, max_tip_deflection=target_defl,
        )
        result = opt.optimize()

        exporter = ANSYSExporter(spar, result.spar_props, result.beam_result, material)
        tmp = Path(tempfile.mkdtemp()) / "spar_model.mac"
        exporter.write_apdl(tmp)

        return FileResponse(tmp, media_type="text/plain", filename="spar_model.mac")

    except Exception as e:
        raise HTTPException(500, detail=str(e))


def main():
    """Entry point for `hpa-mdo` CLI command."""
    import uvicorn
    uvicorn.run("hpa_mdo.api.server:app", host="0.0.0.0", port=8000, reload=True)
