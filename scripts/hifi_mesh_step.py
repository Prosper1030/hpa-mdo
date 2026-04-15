#!/usr/bin/env python3
"""Mesh a STEP file to a CalculiX .inp using the optional Gmsh validation stack."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.core import load_config  # noqa: E402
from hpa_mdo.hifi.gmsh_runner import find_gmsh, mesh_step_to_inp  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "blackcat_004.yaml",
        help="HPA-MDO config with hi_fidelity.gmsh settings.",
    )
    parser.add_argument(
        "--step",
        type=Path,
        default=REPO_ROOT / "output" / "blackcat_004" / "wing_cruise.step",
        help="Input STEP file.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "output" / "blackcat_004" / "hifi" / "wing_cruise.inp",
        help="Output CalculiX .inp mesh.",
    )
    parser.add_argument("--order", type=int, default=1, help="Gmsh element order.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cfg = load_config(args.config)

    if not cfg.hi_fidelity.gmsh.enabled:
        print("INFO: hi_fidelity.gmsh.enabled is false; skipping mesh.")
        return 0

    if find_gmsh(cfg) is None:
        print("INFO: Gmsh binary not found; skipping mesh.")
        return 0

    result = mesh_step_to_inp(args.step, args.out, cfg, order=args.order)
    if result is None:
        print("INFO: STEP mesh did not produce an output .inp.")
        return 0

    print(f"Wrote {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
