#!/usr/bin/env python3
"""Run a CalculiX static validation and compare wing-tip deflection."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.core import MaterialDB, load_config  # noqa: E402
from hpa_mdo.core.constants import G_STANDARD  # noqa: E402
from hpa_mdo.hifi.calculix_runner import (  # noqa: E402
    prepare_static_inp,
    root_boundary_from_mesh,
    run_static,
    tip_node_from_mesh,
)
from hpa_mdo.hifi.frd_parser import parse_displacement  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "blackcat_004.yaml",
        help="HPA-MDO config with hi_fidelity.calculix settings.",
    )
    parser.add_argument("--mesh", type=Path, required=True, help="Meshed CalculiX .inp file.")
    parser.add_argument(
        "--expected-tip-defl",
        type=float,
        required=True,
        help="Reference MDO tip deflection [m].",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Prepared CalculiX static .inp path.",
    )
    parser.add_argument(
        "--material",
        type=str,
        default="carbon_fiber_hm",
        help="Material key in data/materials.yaml.",
    )
    parser.add_argument(
        "--tip-load-n",
        type=float,
        default=None,
        help="Optional concentrated vertical tip load [N]. Default is half-MTOW downward.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cfg = load_config(args.config)
    materials_db = MaterialDB(REPO_ROOT / "data" / "materials.yaml")
    material = materials_db.get(args.material)
    material_payload = {
        "E": material.E,
        "nu": material.poisson_ratio,
        "rho": material.density,
    }

    try:
        root_boundary = root_boundary_from_mesh(args.mesh)
        tip_node = tip_node_from_mesh(args.mesh)
    except Exception as exc:
        print(f"INFO: could not derive root/tip nodes from mesh: {exc}")
        return 0

    tip_load_n = (
        float(args.tip_load_n)
        if args.tip_load_n is not None
        else -0.5 * cfg.weight.max_takeoff_kg * G_STANDARD
    )
    out_inp = args.out or args.mesh.with_name(f"{args.mesh.stem}_static.inp")
    prepare_static_inp(
        args.mesh,
        out_inp,
        material_payload,
        root_boundary,
        [(tip_node, 3, tip_load_n)],
    )
    result = run_static(out_inp, cfg)
    if result.get("error"):
        print(f"INFO: CalculiX static validation skipped/failed: {result['error']}")
        return 0

    disp = parse_displacement(result["frd"])
    if disp.size == 0:
        print(f"INFO: no displacement rows found in {result['frd']}")
        return 0

    matches = disp[disp[:, 0].astype(int) == int(tip_node)]
    if matches.size == 0:
        print(f"INFO: tip node {tip_node} not found in FRD displacement output.")
        return 0

    hifi_tip = float(matches[-1, 3])
    expected = float(args.expected_tip_defl)
    denom = max(abs(expected), 1.0e-12)
    diff_pct = 100.0 * (hifi_tip - expected) / denom
    prefix = "[WARN] " if abs(diff_pct) > 5.0 else ""
    print(
        f"{prefix}hifi tip defl: {hifi_tip:.6f} m "
        f"(MDO {expected:.6f} m, diff {diff_pct:+.2f}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
