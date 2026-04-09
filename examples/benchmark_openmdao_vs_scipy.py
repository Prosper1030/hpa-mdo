#!/usr/bin/env python3
"""Benchmark OpenMDAO driver vs SciPy black-box optimization.

Read-only comparison from the same configuration and a fresh optimizer for
each method. Reports wall time, final design metrics, and call counts for
DualSparPropertiesComp.compute() / compute_partials() so we can verify when
analytic partials are actually being used.

Usage:
    .venv/bin/python examples/benchmark_openmdao_vs_scipy.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from time import perf_counter

os.environ.setdefault("OPENMDAO_REPORTS", "0")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.aero import LoadMapper, VSPAeroParser  # noqa: E402
from hpa_mdo.core import Aircraft, MaterialDB, load_config  # noqa: E402
from hpa_mdo.structure import SparOptimizer  # noqa: E402
from hpa_mdo.structure.oas_structural import DualSparPropertiesComp  # noqa: E402


def _build_optimizer() -> SparOptimizer:
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path)
    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
    cases = parser.parse()
    mapper = LoadMapper()

    target_weight = aircraft.weight_N
    best_residual = float("inf")
    best_loads = None
    for case in cases:
        loads = mapper.map_loads(
            case,
            aircraft.wing.y,
            actual_velocity=cfg.flight.velocity,
            actual_density=cfg.flight.air_density,
        )
        residual = abs(2.0 * loads["total_lift"] - target_weight)
        if residual < best_residual:
            best_residual = residual
            best_loads = loads

    if best_loads is None:
        raise RuntimeError("No valid AoA case found in VSPAero data")

    design_loads = LoadMapper.apply_load_factor(
        best_loads, cfg.safety.aerodynamic_load_factor
    )
    return SparOptimizer(cfg, aircraft, design_loads, materials_db)


def _result_to_dict(method: str, elapsed: float, result) -> dict:
    return {
        "method": method,
        "success": bool(result.success),
        "message": result.message,
        "total_mass_full_kg": float(result.total_mass_full_kg),
        "failure_index": float(result.failure_index),
        "buckling_index": float(result.buckling_index),
        "twist_max_deg": float(result.twist_max_deg),
        "tip_deflection_m": float(result.tip_deflection_m),
        "wall_time_s": float(elapsed),
        "timing_s": dict(result.timing_s),
        "n_compute": int(DualSparPropertiesComp._n_compute),
        "n_compute_partials": int(DualSparPropertiesComp._n_compute_partials),
    }


def _run_one(method: str) -> dict:
    DualSparPropertiesComp.reset_counters()
    optimizer = _build_optimizer()
    t0 = perf_counter()
    result = optimizer.optimize(method=method)
    elapsed = perf_counter() - t0
    return _result_to_dict(method, elapsed, result)


def main() -> None:
    rows = []
    for method in ("openmdao", "scipy"):
        print(f"\n=== Running method={method} ===", flush=True)
        t0 = perf_counter()
        try:
            rows.append(_run_one(method))
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "method": method,
                    "success": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "wall_time_s": float(perf_counter() - t0),
                    "timing_s": {},
                    "traceback": traceback.format_exc(),
                    "n_compute": int(DualSparPropertiesComp._n_compute),
                    "n_compute_partials": int(DualSparPropertiesComp._n_compute_partials),
                }
            )

    out_path = REPO_ROOT / "docs" / "openmdao_vs_scipy_benchmark.json"
    out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nWrote raw results to {out_path}")

    print("\n=== Comparison ===")
    for row in rows:
        print(json.dumps(row, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
