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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"Config path (default: {DEFAULT_CONFIG})")
    parser.add_argument("--out", default=None, help="Artifact output directory")
    parser.add_argument("--aoa", nargs="+", type=float, default=DEFAULT_AOA, help="AoA sweep values in deg")
    parser.add_argument("--su2-sweep-dir", default=None, help="Optional SU2 alpha sweep root to ingest")
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
    )

    print(f"Origin aero sweep complete: {bundle['bundle_json']}")
    print(f"VSPAero CSV: {bundle['vspaero']['files']['csv']}")
    if bundle.get("su2"):
        print(f"SU2 CSV: {bundle['su2']['files']['csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
