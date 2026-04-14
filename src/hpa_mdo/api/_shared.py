"""Shared helpers for the FastAPI and MCP servers.

This module is intentionally framework-agnostic — it must NOT import
fastapi or mcp, so both servers can use it without dragging optional
dependencies into the other.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def json_safe(obj):
    """Convert numpy types to JSON-serializable Python types."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {key: json_safe(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(value) for value in obj]
    if isinstance(obj, (np.float32, np.float64)):
        return float(obj)
    if isinstance(obj, (np.int32, np.int64)):
        return int(obj)
    return obj


def run_pipeline(config_yaml_path: str, aoa_deg: Optional[float] = None):
    """Shared pipeline: config -> aircraft -> aero parse -> design loads -> optimizer.

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
    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
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

    trim_loads = mapper.map_loads(
        best_case, ac.wing.y,
        actual_velocity=cfg.flight.velocity,
        actual_density=cfg.flight.air_density,
    )
    aero_loads = trim_loads

    opt = SparOptimizer(cfg, ac, aero_loads, mat_db)
    return cfg, ac, mat_db, aero_loads, opt, best_case


def result_to_dict(result) -> dict:
    """Convert an OptimizationResult to a JSON-safe dict."""
    return {
        "error_code": None,
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
        "buckling_index": round(result.buckling_index, 4),
        "tip_deflection_m": round(result.tip_deflection_m, 4),
        "twist_max_deg": round(result.twist_max_deg, 2),
        "main_t_seg_mm": [round(float(t), 3) for t in result.main_t_seg_mm],
        "rear_t_seg_mm": (
            [round(float(t), 3) for t in result.rear_t_seg_mm]
            if result.rear_t_seg_mm is not None else None
        ),
        "strain_envelope": json_safe(result.strain_envelope),
    }
