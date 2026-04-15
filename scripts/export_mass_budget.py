#!/usr/bin/env python3
"""Export mass budget YAML, Markdown report, and AVL `.mass` file."""

from __future__ import annotations

import argparse
import pickle
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.aero import LoadMapper, VSPAeroParser  # noqa: E402
from hpa_mdo.core import Aircraft, MaterialDB, load_config  # noqa: E402
from hpa_mdo.mass import build_mass_budget_from_config  # noqa: E402
from hpa_mdo.structure import SparOptimizer  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "blackcat_004.yaml",
        help="Path to the HPA-MDO config YAML.",
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=None,
        help="Optional pickle path for a cached OptimizationResult.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: cfg.io.output_dir).",
    )
    parser.add_argument(
        "--skip-optimize",
        action="store_true",
        default=False,
        help="Do not rerun the structural optimizer when no cached result is available.",
    )
    parser.add_argument(
        "--rho",
        type=float,
        default=None,
        help="Air density written into the AVL .mass header.",
    )
    return parser.parse_args()


def _load_pickled_result(path: Path):
    with path.open("rb") as handle:
        return pickle.load(handle)


def _run_optimizer(cfg, aircraft, materials_db):
    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
    cases = parser.parse()
    mapper = LoadMapper()

    best_residual = float("inf")
    best_loads = None
    for case in cases:
        loads = mapper.map_loads(
            case,
            aircraft.wing.y,
            actual_velocity=cfg.flight.velocity,
            actual_density=cfg.flight.air_density,
        )
        residual = abs(2.0 * loads["total_lift"] - aircraft.weight_N)
        if residual < best_residual:
            best_residual = residual
            best_loads = loads

    if best_loads is None:
        raise RuntimeError("Failed to map a valid load case for optimization.")

    optimizer = SparOptimizer(cfg, aircraft, best_loads, materials_db)
    return optimizer.optimize(method="auto")


def _resolve_result(args, cfg, aircraft, materials_db, out_dir: Path):
    candidate = args.result
    if candidate is None:
        default_candidate = Path(cfg.io.output_dir) / "result.pkl"
        if default_candidate.exists():
            candidate = default_candidate

    if candidate is not None and candidate.exists():
        try:
            result = _load_pickled_result(candidate)
            print(f"Using cached result: {candidate}")
            return result
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: failed to load cached result {candidate}: {exc}")

    if args.skip_optimize:
        print("WARN: no cached result available and --skip-optimize was requested.")
        return None

    print("No cached result found; rerunning spar optimization...")
    result = _run_optimizer(cfg, aircraft, materials_db)
    cache_path = out_dir / "result.pkl"
    try:
        with cache_path.open("wb") as handle:
            pickle.dump(result, handle)
        print(f"Cached result: {cache_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: failed to cache result.pkl: {exc}")
    return result


def main() -> int:
    args = _parse_args()
    cfg = load_config(args.config)
    out_dir = Path(args.out) if args.out is not None else Path(cfg.io.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    try:
        result = _resolve_result(args, cfg, aircraft, materials_db, out_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: optimization replay failed ({exc}); exporting config-only budget.")
        result = None

    budget = build_mass_budget_from_config(
        cfg,
        result,
        aircraft=aircraft,
        materials_db=materials_db,
    )

    yaml_path = budget.to_yaml(out_dir / "mass_budget.yaml")
    report_path = budget.write_report(out_dir / "mass_budget_report.md")
    rho = float(args.rho) if args.rho is not None else float(cfg.flight.air_density)
    avl_path = budget.to_avl_mass(out_dir / "avl_mass.mass", rho=rho)

    for warning in budget.warnings:
        print(warning)

    sanity = budget.sanity_check()
    cg = budget.center_of_gravity()
    print(f"Wrote: {yaml_path}")
    print(f"Wrote: {report_path}")
    print(f"Wrote: {avl_path}")
    print(
        f"Total mass: {budget.total_mass():.3f} kg, "
        f"CG: [{cg[0]:+.3f}, {cg[1]:+.3f}, {cg[2]:+.3f}] m, "
        f"sanity: {'PASS' if sanity['passed'] else 'WARN'}"
    )
    if sanity["target_total_mass_kg"] is not None and not sanity["passed"]:
        print(
            "WARN: mass budget differs from config operating mass by "
            f"{float(sanity['delta_kg']):+.3f} kg "
            f"({100.0 * float(sanity['delta_fraction']):+.2f}%)."
        )
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
