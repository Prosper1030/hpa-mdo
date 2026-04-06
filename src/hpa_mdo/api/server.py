"""FastAPI REST server for HPA-MDO v2.

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
import traceback
from pathlib import Path
from typing import Any, Optional, List

import numpy as np

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel as PydanticModel, Field
except ImportError:
    raise ImportError("FastAPI not installed. Run: pip install 'hpa-mdo[api]'")


app = FastAPI(
    title="HPA-MDO API",
    description="Human-Powered Aircraft Multidisciplinary Design Optimization v2",
    version="2.0.0",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_safe(obj):
    """Convert numpy types to JSON-serializable Python types."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.float32, np.float64)):
        return float(obj)
    if isinstance(obj, (np.int32, np.int64)):
        return int(obj)
    return obj


def _result_to_dict(result) -> dict:
    """Convert an OptimizationResult to a JSON-safe dict."""
    return {
        "success": result.success,
        "message": result.message,
        "spar_mass_half_kg": round(result.spar_mass_half_kg, 4),
        "spar_mass_full_kg": round(result.spar_mass_full_kg, 4),
        "total_mass_full_kg": round(result.total_mass_full_kg, 4),
        "max_stress_main_MPa": round(result.max_stress_main_Pa / 1e6, 2),
        "max_stress_rear_MPa": round(result.max_stress_rear_Pa / 1e6, 2),
        "allowable_stress_main_MPa": round(result.allowable_stress_main_Pa / 1e6, 2),
        "allowable_stress_rear_MPa": round(result.allowable_stress_rear_Pa / 1e6, 2),
        "failure_index": round(result.failure_index, 4),
        "tip_deflection_m": round(result.tip_deflection_m, 4),
        "twist_max_deg": round(result.twist_max_deg, 2),
        "main_t_seg_mm": [round(float(t), 3) for t in result.main_t_seg_mm],
        "rear_t_seg_mm": (
            [round(float(t), 3) for t in result.rear_t_seg_mm]
            if result.rear_t_seg_mm is not None else None
        ),
    }


def _run_pipeline(config_yaml_path: str, aoa_deg: Optional[float] = None):
    """Shared pipeline: config -> aircraft -> aero parse -> load map -> optimizer.

    Returns (cfg, ac, mat_db, aero_loads, opt, best_case).
    """
    from hpa_mdo.core.config import load_config
    from hpa_mdo.core.aircraft import Aircraft
    from hpa_mdo.core.materials import MaterialDB
    from hpa_mdo.aero.vsp_aero import VSPAeroParser
    from hpa_mdo.aero.load_mapper import LoadMapper
    from hpa_mdo.structure.optimizer import SparOptimizer

    cfg = load_config(config_yaml_path)
    ac = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    parser = VSPAeroParser(cfg.io.vsp_lod)
    cases = parser.parse()
    mapper = LoadMapper()

    if aoa_deg is not None:
        best_case = min(cases, key=lambda c: abs(c.aoa_deg - aoa_deg))
    else:
        best_case = min(cases, key=lambda c: abs(
            mapper.map_loads(c, ac.wing.y,
                             actual_velocity=cfg.flight.velocity,
                             actual_density=cfg.flight.air_density)["total_lift"]
            - ac.weight_N / 2))

    aero_loads = mapper.map_loads(
        best_case, ac.wing.y,
        actual_velocity=cfg.flight.velocity,
        actual_density=cfg.flight.air_density,
    )

    opt = SparOptimizer(cfg, ac, aero_loads, mat_db)
    return cfg, ac, mat_db, aero_loads, opt, best_case


def _error_json(e: Exception) -> dict:
    """Standard error dict for any endpoint failure."""
    return {"error": str(e), "val_weight": 99999}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ParseVSPAeroRequest(PydanticModel):
    lod_path: str = Field(..., description="Path to VSPAero .lod file")
    aoa_deg: float = Field(3.0, description="Angle of attack [degrees]")


class OptimizeRequest(PydanticModel):
    config_yaml_path: str = Field(..., description="Path to HPA-MDO YAML config")
    aoa_deg: float = Field(3.0, description="Angle of attack [degrees]")


class AnalyzeRequest(PydanticModel):
    config_yaml_path: str = Field(..., description="Path to HPA-MDO YAML config")
    main_t_mm: List[float] = Field(..., description="Main spar segment thicknesses [mm]")
    rear_t_mm: Optional[List[float]] = Field(None, description="Rear spar segment thicknesses [mm]")
    aoa_deg: float = Field(3.0, description="Angle of attack [degrees]")


class ExportRequest(PydanticModel):
    config_yaml_path: str = Field(..., description="Path to HPA-MDO YAML config")
    output_dir: str = Field(..., description="Directory for exported files")
    aoa_deg: float = Field(3.0, description="Angle of attack [degrees]")
    formats: List[str] = Field(
        default=["apdl", "csv", "nastran"],
        description="Export formats: apdl, csv, nastran",
    )


class ConfigRequest(PydanticModel):
    config_yaml_path: str = Field(..., description="Path to HPA-MDO YAML config")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "2.0.0", "framework": "hpa-mdo"}


@app.get("/materials")
async def list_materials():
    """List all available structural materials from data/materials.yaml."""
    try:
        from hpa_mdo.core.materials import MaterialDB
        db = MaterialDB()
        result = {}
        for key in db.list_materials():
            m = db.get(key)
            result[key] = {
                "name": m.name,
                "E_GPa": round(m.E / 1e9, 1),
                "G_GPa": round(m.G / 1e9, 1),
                "density_kg_m3": m.density,
                "tensile_strength_MPa": round(m.tensile_strength / 1e6, 0),
                "poisson_ratio": m.poisson_ratio,
            }
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content=_error_json(e))


@app.post("/parse-vspaero")
async def parse_vspaero(req: ParseVSPAeroRequest):
    """Parse a VSPAero .lod file and return load distribution at a given AoA."""
    try:
        from hpa_mdo.aero.vsp_aero import VSPAeroParser
        parser = VSPAeroParser(req.lod_path)
        cases = parser.parse()
        best = min(cases, key=lambda c: abs(c.aoa_deg - req.aoa_deg))
        return {
            "aoa_deg": best.aoa_deg,
            "n_stations": best.n_stations,
            "n_cases_parsed": len(cases),
            "available_aoa": [c.aoa_deg for c in cases],
            "total_lift_N": round(float(np.trapz(best.lift_per_span, best.y)), 3),
            "y_range_m": [round(float(best.y[0]), 3), round(float(best.y[-1]), 3)],
            "cl_range": [round(float(best.cl.min()), 4), round(float(best.cl.max()), 4)],
        }
    except Exception as e:
        return JSONResponse(status_code=500, content=_error_json(e))


@app.post("/optimize")
async def optimize(req: OptimizeRequest):
    """Run full spar structural optimization from a YAML config."""
    try:
        cfg, ac, mat_db, aero_loads, opt, best_case = _run_pipeline(
            req.config_yaml_path, req.aoa_deg)
        result = opt.optimize(method="scipy")
        out = _result_to_dict(result)
        out["aoa_used_deg"] = best_case.aoa_deg
        return out
    except Exception as e:
        return JSONResponse(status_code=500, content=_error_json(e))


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Evaluate a specific spar design (given segment thicknesses) without optimization."""
    try:
        cfg, ac, mat_db, aero_loads, opt, best_case = _run_pipeline(
            req.config_yaml_path, req.aoa_deg)

        main_t_seg = np.array(req.main_t_mm) * 1e-3
        rear_t_seg = None
        if req.rear_t_mm is not None:
            rear_t_seg = np.array(req.rear_t_mm) * 1e-3

        result = opt.analyze(main_t_seg=main_t_seg, rear_t_seg=rear_t_seg)
        out = _result_to_dict(result)
        out["aoa_used_deg"] = best_case.aoa_deg
        return out
    except Exception as e:
        return JSONResponse(status_code=500, content=_error_json(e))


@app.post("/export")
async def export_ansys(req: ExportRequest):
    """Run optimization and export results to ANSYS-compatible formats."""
    try:
        from hpa_mdo.structure.ansys_export import ANSYSExporter

        cfg, ac, mat_db, aero_loads, opt, best_case = _run_pipeline(
            req.config_yaml_path, req.aoa_deg)
        result = opt.optimize(method="scipy")

        main_mat = mat_db.get(cfg.main_spar.material)
        exporter = ANSYSExporter(
            spar=opt._prob.model.struct if hasattr(opt._prob, "model") else None,
            spar_props={"inner_diameter": result.disp} if result.disp is not None else {},
            beam_result=result,
            material=main_mat,
        )

        out_path = Path(req.output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        files = []
        fmt_list = [f.strip().lower() for f in req.formats]
        if "apdl" in fmt_list:
            p = exporter.write_apdl(out_path / "spar_model.mac")
            files.append(str(p))
        if "csv" in fmt_list:
            p = exporter.write_workbench_csv(out_path / "spar_data.csv")
            files.append(str(p))
        if "nastran" in fmt_list:
            p = exporter.write_nastran_bdf(out_path / "spar_model.bdf")
            files.append(str(p))

        out_dict = _result_to_dict(result)
        out_dict["exported_files"] = files
        out_dict["aoa_used_deg"] = best_case.aoa_deg
        return out_dict
    except Exception as e:
        return JSONResponse(status_code=500, content=_error_json(e))


@app.get("/config")
async def get_config(config_yaml_path: str):
    """Return parsed HPA-MDO configuration as JSON.

    Pass the path as a query parameter: /config?config_yaml_path=...
    """
    try:
        from hpa_mdo.core.config import load_config
        cfg = load_config(config_yaml_path)
        return json.loads(cfg.model_dump_json())
    except Exception as e:
        return JSONResponse(status_code=500, content=_error_json(e))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Entry point for `hpa-mdo serve` CLI command."""
    import uvicorn
    uvicorn.run("hpa_mdo.api.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
