#!/usr/bin/env python3
"""Run the repo-owned origin VSPAero sweep and optionally compare against SU2."""

from __future__ import annotations

import argparse
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hpa_mdo.aero.origin_aero import run_origin_aero_sweep
from hpa_mdo.core.config import load_config


DEFAULT_CONFIG = "configs/blackcat_004.yaml"
DEFAULT_AOA = [-2.0, 0.0, 2.0]
DEFAULT_MESH_PRESET = "baseline"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"Config path (default: {DEFAULT_CONFIG})")
    parser.add_argument("--out", default=None, help="Artifact output directory")
    parser.add_argument("--aoa", nargs="+", type=float, default=DEFAULT_AOA, help="AoA sweep values in deg")
    parser.add_argument("--su2-sweep-dir", default=None, help="Optional SU2 alpha sweep root to ingest")
    parser.add_argument("--prepare-su2", action="store_true", help="Prepare origin-based SU2 alpha cases")
    parser.add_argument("--su2-mesh", default=None, help="Optional .su2 mesh copied into each prepared case")
    parser.add_argument(
        "--su2-mesh-preset",
        default=DEFAULT_MESH_PRESET,
        choices=["baseline", "study_coarse", "study_medium", "study_fine"],
        help="Preset mesh sizing contract used when auto-generating the SU2 mesh",
    )
    parser.add_argument("--auto-mesh-su2", action="store_true", help="Auto-generate an external-flow SU2 mesh from origin_surface.stl")
    parser.add_argument("--run-su2", action="store_true", help="Run prepared SU2 cases after writing configs")
    parser.add_argument("--dry-run-su2", action="store_true", help="Preview prepared SU2 commands without executing")
    parser.add_argument("--su2-ranks", type=int, default=None, help="Optional MPI ranks when --run-su2 is used")
    parser.add_argument("--su2-binary", default=None, help="Override SU2_CFD binary path when running cases")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    output_dir = (
        Path(args.out).expanduser().resolve()
        if args.out
        else (Path(cfg.io.output_dir).expanduser().resolve() / "origin_aero")
    )

    bundle = run_origin_aero_sweep(
        config_path=args.config,
        output_dir=output_dir,
        aoa_list=args.aoa,
        su2_sweep_dir=args.su2_sweep_dir,
        prepare_su2=args.prepare_su2,
        su2_mesh_path=args.su2_mesh,
        auto_mesh_su2=args.auto_mesh_su2,
        su2_mesh_preset=args.su2_mesh_preset,
        run_su2_cases=args.run_su2,
        dry_run_su2_cases=args.dry_run_su2,
        su2_binary=args.su2_binary,
        su2_mpi_ranks=args.su2_ranks,
    )

    print(f"Origin aero sweep complete: {bundle['bundle_json']}")
    print(f"VSPAero CSV: {bundle['vspaero']['files']['csv']}")
    if bundle.get("su2"):
        print(f"SU2 CSV: {bundle['su2']['files']['csv']}")
    if bundle["metadata"].get("su2_preparation"):
        print(f"SU2 sweep dir: {bundle['metadata']['su2_preparation']['sweep_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
