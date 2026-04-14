#!/usr/bin/env python3
"""Convert an OpenVSP .vsp3 geometry file into an AVL .avl model file."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Allow direct execution from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero.avl_exporter import export_avl
from hpa_mdo.aero.vsp_geometry_parser import VSPGeometryParser


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse VSP3 XML geometry and export an AVL model file."
    )
    parser.add_argument("--vsp3", required=True, help="Path to source .vsp3 file.")
    parser.add_argument("--output", required=True, help="Path to output .avl file.")
    parser.add_argument("--sref", type=float, default=None)
    parser.add_argument("--cref", type=float, default=None)
    parser.add_argument("--bref", type=float, default=None)
    parser.add_argument("--xref", type=float, default=0.0)
    parser.add_argument("--yref", type=float, default=0.0)
    parser.add_argument("--zref", type=float, default=0.0)
    parser.add_argument("--mach", type=float, default=0.0)
    parser.add_argument(
        "--airfoil-dir",
        default=None,
        help="Directory to search for .dat airfoil coordinate files "
        "(emits AVL AFILE directive for non-NACA airfoils).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    vsp3_path = Path(args.vsp3).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    parser = VSPGeometryParser(vsp3_path)
    geometry = parser.parse()
    avl_path = export_avl(
        geometry=geometry,
        output_path=output_path,
        sref=args.sref,
        cref=args.cref,
        bref=args.bref,
        xref=args.xref,
        yref=args.yref,
        zref=args.zref,
        mach=args.mach,
        airfoil_dir=args.airfoil_dir,
    )

    print(f"Wrote AVL model: {avl_path}")
    for surface in geometry.surfaces:
        print(
            f"  {surface.name}: type={surface.surface_type}, "
            f"sym={surface.symmetry}, sections={len(surface.sections)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
