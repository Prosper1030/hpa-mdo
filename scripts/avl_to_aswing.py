#!/usr/bin/env python3
"""Generate an ASWING .asw seed file from AVL geometry and HPA-MDO config."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.aero.aswing_exporter import export_aswing  # noqa: E402
from hpa_mdo.core import MaterialDB, load_config  # noqa: E402


DEFAULT_AVL = REPO_ROOT / "data" / "blackcat_004_full.avl"
DEFAULT_CONFIG = REPO_ROOT / "configs" / "blackcat_004.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "output" / "aswing" / "blackcat_004_full.asw"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--avl",
        type=Path,
        default=DEFAULT_AVL,
        help="Input AVL geometry file.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="HPA-MDO YAML config with load cases and structural seed data.",
    )
    parser.add_argument(
        "--materials",
        type=Path,
        default=REPO_ROOT / "data" / "materials.yaml",
        help="Material database YAML.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output ASWING .asw path.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cfg = load_config(args.config)
    materials_db = MaterialDB(args.materials)
    output = export_aswing(
        args.avl,
        cfg,
        args.output,
        materials_db=materials_db,
    )
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
