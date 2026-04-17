#!/usr/bin/env python3
"""Export a drawing-ready baseline package from an output directory."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hpa_mdo.utils.drawing_ready_package import export_drawing_ready_package


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export drawing-ready baseline package")
    parser.add_argument(
        "--output-dir",
        default="output/blackcat_004",
        help="Solved output directory to package (default: output/blackcat_004).",
    )
    parser.add_argument(
        "--package-name",
        default="drawing_ready_package",
        help="Name of the package directory created under --output-dir.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    package_dir = export_drawing_ready_package(
        args.output_dir,
        package_dir_name=args.package_name,
    )
    print(f"Drawing-ready package exported: {package_dir}")
    print(f"  README   : {package_dir / 'README.md'}")
    print(f"  Manifest : {package_dir / 'drawing_ready_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
