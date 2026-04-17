#!/usr/bin/env python3
"""One-shot structural high-fidelity validation driver.

This script orchestrates the currently implemented structural pieces:

  summary -> (optional STEP -> mesh) -> CalculiX static -> BUCKLE -> report
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.hifi.structural_check import run_structural_check  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "blackcat_004.yaml",
        help="Project config with hi_fidelity.gmsh / calculix settings.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help=(
            "Reference summary/design report. Defaults to the current-standard "
            "dual-beam production crossval report when available, otherwise "
            "falls back to optimization_summary.txt."
        ),
    )
    parser.add_argument(
        "--step",
        type=Path,
        default=None,
        help=(
            "STEP geometry input. Defaults to jig-oriented STEP artifacts such as "
            "spar_jig_shape.step before falling back to legacy spar/cruise STEP files."
        ),
    )
    parser.add_argument(
        "--mesh",
        type=Path,
        default=None,
        help="Existing CalculiX .inp mesh. If given, meshing is skipped.",
    )
    parser.add_argument(
        "--hifi-dir",
        type=Path,
        default=None,
        help="Output directory for generated hifi artifacts. Defaults to <output_dir>/hifi.",
    )
    parser.add_argument(
        "--material",
        type=str,
        default="carbon_fiber_hm",
        help="Material key in data/materials.yaml used for the standalone solid deck.",
    )
    parser.add_argument(
        "--tip-load-n",
        type=float,
        default=None,
        help="Override the vertical tip load [N]. Default is -0.5 * MTOW * g.",
    )
    parser.add_argument(
        "--no-paraview",
        action="store_true",
        help="Skip pvpython script generation.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_structural_check(
        config_path=args.config,
        summary_path=args.summary,
        step_path=args.step,
        mesh_path=args.mesh,
        hifi_dir=args.hifi_dir,
        material_key=args.material,
        tip_load_n=args.tip_load_n,
        generate_paraview=not args.no_paraview,
    )

    print(f"[hpa-mdo] Structural check: {result.overall_status}")
    print(f"  report   : {result.report_path}")
    if result.mesh_path is not None:
        print(f"  mesh     : {result.mesh_path}")
    if result.paraview_script_path is not None:
        print(f"  pvpython : {result.paraview_script_path}")
    print(f"  static   : {result.static.status} — {result.static.message}")
    print(f"  buckle   : {result.buckle.status} — {result.buckle.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
