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
from pathlib import Path
from typing import List, Optional

import numpy as np

try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel as PydanticModel, Field
except ImportError:
    raise ImportError("FastAPI not installed. Run: pip install 'hpa-mdo[api]'")

from hpa_mdo.core.errors import ErrorCode
from hpa_mdo.api._shared import json_safe as _json_safe
from hpa_mdo.api._shared import run_pipeline as _run_pipeline
from hpa_mdo.api._shared import result_to_dict as _result_to_dict


app = FastAPI(
    title="HPA-MDO API",
    description="Human-Powered Aircraft Multidisciplinary Design Optimization v2",
    version="2.0.0",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _success_json(payload: dict) -> dict:
    """Append success error_code to endpoint payloads."""
    return {"error_code": None, **payload}


def _error_json(
    e: Exception,
    code: ErrorCode = ErrorCode.SOLVER_DIVERGED,
    *,
    include_val_weight: bool = False,
) -> dict:
    """Standard error dict for any endpoint failure."""
    out = {"error": str(e), "error_code": code.value}
    if include_val_weight:
        # Top-level endpoint failure sentinel only.
        # Internal optimizer failures use separate normalized penalties.
        out["val_weight"] = 99999
    return out


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
    return _success_json({"status": "ok", "version": "2.0.0", "framework": "hpa-mdo"})


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
        return _success_json({"materials": result})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_error_json(e, ErrorCode.CONFIG_INVALID),
        )


@app.post("/parse-vspaero")
async def parse_vspaero(req: ParseVSPAeroRequest):
    """Parse a VSPAero .lod file and return load distribution at a given AoA."""
    try:
        from hpa_mdo.aero.vsp_aero import VSPAeroParser
        parser = VSPAeroParser(req.lod_path)
        cases = parser.parse()
        best = min(cases, key=lambda c: abs(c.aoa_deg - req.aoa_deg))
        return _success_json({
            "aoa_deg": best.aoa_deg,
            "n_stations": best.n_stations,
            "n_cases_parsed": len(cases),
            "available_aoa": [c.aoa_deg for c in cases],
            "total_lift_N": round(float(np.trapezoid(best.lift_per_span, best.y)), 3),
            "y_range_m": [round(float(best.y[0]), 3), round(float(best.y[-1]), 3)],
            "cl_range": [round(float(best.cl.min()), 4), round(float(best.cl.max()), 4)],
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_error_json(e, ErrorCode.AERO_PARSE_FAIL),
        )


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
        return JSONResponse(
            status_code=500,
            content=_error_json(
                e,
                ErrorCode.SOLVER_DIVERGED,
                include_val_weight=True,
            ),
        )


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
        return JSONResponse(
            status_code=500,
            content=_error_json(
                e,
                ErrorCode.SOLVER_DIVERGED,
                include_val_weight=True,
            ),
        )


@app.post("/export")
async def export_ansys(req: ExportRequest):
    """Run optimization and export results to ANSYS-compatible formats."""
    try:
        from hpa_mdo.structure.ansys_export import ANSYSExporter

        cfg, ac, mat_db, aero_loads, opt, best_case = _run_pipeline(
            req.config_yaml_path, req.aoa_deg)
        result = opt.optimize(method="scipy")

        exporter = ANSYSExporter(cfg, ac, result, aero_loads, mat_db)

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
        return JSONResponse(
            status_code=500,
            content=_error_json(e, ErrorCode.EXPORT_FAIL),
        )


@app.get("/config")
async def get_config(config_yaml_path: str):
    """Return parsed HPA-MDO configuration as JSON.

    Pass the path as a query parameter: /config?config_yaml_path=...
    """
    try:
        from hpa_mdo.core.config import load_config
        cfg = load_config(config_yaml_path)
        return _success_json({"config": json.loads(cfg.model_dump_json())})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_error_json(e, ErrorCode.CONFIG_INVALID),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Entry point for `hpa-mdo serve` CLI command."""
    import uvicorn
    uvicorn.run("hpa_mdo.api.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
