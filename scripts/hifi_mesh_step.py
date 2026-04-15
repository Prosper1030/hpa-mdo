#!/usr/bin/env python3
"""Mesh a STEP file to a CalculiX .inp using the optional Gmsh validation stack."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.core import load_config  # noqa: E402
from hpa_mdo.core.config import HPAConfig  # noqa: E402
from hpa_mdo.hifi.gmsh_runner import (  # noqa: E402
    NamedPoint,
    find_gmsh,
    mesh_step_to_inp,
)


def named_points_from_config(cfg: HPAConfig) -> list[NamedPoint]:
    """Derive root / tip / wire-joint NamedPoints from the HPA config.

    Uses the half-span convention baked into ``Aircraft.from_config`` —
    spar is oriented along +Y with the root at ``y = 0`` and the tip at
    ``y = half_span`` — so a mesh produced from ``wing_jig.step`` /
    ``wing_cruise.step`` inherits the same axes.
    """
    half_span = float(cfg.wing.half_span)
    points: list[NamedPoint] = [
        NamedPoint("ROOT", (0.0, 0.0, 0.0)),
        NamedPoint("TIP", (0.0, half_span, 0.0)),
    ]
    if cfg.lift_wires.enabled:
        for idx, attachment in enumerate(cfg.lift_wires.attachments, start=1):
            points.append(
                NamedPoint(f"WIRE_{idx}", (0.0, float(attachment.y), 0.0))
            )
    return points


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
    parser.add_argument(
        "--no-named-points",
        action="store_true",
        default=False,
        help="Disable automatic ROOT / TIP / WIRE_N NSET annotation.",
    )
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

    named_points = None if args.no_named_points else named_points_from_config(cfg)
    result = mesh_step_to_inp(
        args.step, args.out, cfg, order=args.order, named_points=named_points
    )
    if result is None:
        print("INFO: STEP mesh did not produce an output .inp.")
        return 0

    print(f"Wrote {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
