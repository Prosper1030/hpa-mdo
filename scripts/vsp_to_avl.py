#!/usr/bin/env python3
"""Convert aircraft geometry into an AVL ``.avl`` model file.

Prefers a reference ``.vsp3`` when available; otherwise falls back to
geometry declared in a YAML config.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Allow direct execution from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero.avl_exporter import export_avl
from hpa_mdo.aero.vsp_geometry_parser import (
    VSPGeometryParser,
    attach_surface_metadata_from_summary,
    geometry_model_from_config,
)
from hpa_mdo.aero.vsp_introspect import summarize_vsp_surfaces
from hpa_mdo.core.config import load_config


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export an AVL model from a reference .vsp3 when available, "
            "otherwise from YAML geometry."
        )
    )
    parser.add_argument(
        "--vsp3",
        default=None,
        help="Path to source .vsp3 file. Overrides config io.vsp_model when provided.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Optional YAML config. If --vsp3 is omitted, the script will try "
            "config.io.vsp_model first, then fall back to YAML geometry."
        ),
    )
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
    parser.add_argument(
        "--no-inline-airfoils-from-vsp",
        action="store_true",
        help=(
            "Disable direct OpenVSP airfoil-coordinate extraction and keep the "
            "older AFILE/NACA export path."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    output_path = Path(args.output).expanduser().resolve()
    cfg = load_config(args.config) if args.config is not None else None

    explicit_vsp = None
    if args.vsp3 is not None:
        explicit_vsp = Path(args.vsp3).expanduser().resolve()
        if not explicit_vsp.is_file():
            raise FileNotFoundError(f"VSP3 file not found: {explicit_vsp}")

    config_vsp = None
    if cfg is not None and cfg.io.vsp_model is not None:
        candidate = Path(cfg.io.vsp_model).expanduser()
        if candidate.is_file():
            config_vsp = candidate.resolve()

    source_vsp = explicit_vsp or config_vsp
    if source_vsp is not None:
        geometry = VSPGeometryParser(source_vsp).parse()
        try:
            summary = summarize_vsp_surfaces(
                source_vsp,
                airfoil_dir=(cfg.io.airfoil_dir if cfg is not None else None),
                include_airfoil_coordinates=not bool(args.no_inline_airfoils_from_vsp),
            )
        except Exception as exc:
            print(f"WARN: control-surface introspection skipped ({exc})")
        else:
            summary_source = Path(summary.get("source_path", source_vsp)).expanduser().resolve()
            if summary_source != source_vsp:
                raise RuntimeError(
                    "VSP summary source drifted away from the requested .vsp3: "
                    f"{summary_source} != {source_vsp}"
                )
            if geometry.source_path is not None:
                geometry_source = Path(geometry.source_path).expanduser().resolve()
                if geometry_source != source_vsp:
                    raise RuntimeError(
                        "Parsed geometry source drifted away from the requested .vsp3: "
                        f"{geometry_source} != {source_vsp}"
                    )
            geometry = attach_surface_metadata_from_summary(geometry, summary)
        source_label = str(source_vsp)
    elif cfg is not None:
        geometry = geometry_model_from_config(cfg)
        source_label = f"config:{Path(args.config).expanduser().resolve()}"
    else:
        raise ValueError("Provide --vsp3 or --config so geometry can be resolved.")

    airfoil_dir = args.airfoil_dir
    if airfoil_dir is None and cfg is not None and cfg.io.airfoil_dir is not None:
        airfoil_dir = str(cfg.io.airfoil_dir)

    avl_path = export_avl(
        geometry=geometry,
        output_path=output_path,
        title=cfg.project_name if cfg is not None else None,
        sref=args.sref,
        cref=args.cref,
        bref=args.bref,
        xref=args.xref,
        yref=args.yref,
        zref=args.zref,
        mach=args.mach,
        airfoil_dir=airfoil_dir,
    )

    print(f"Wrote AVL model: {avl_path}")
    print(f"Geometry source: {source_label}")
    for surface in geometry.surfaces:
        print(
            f"  {surface.name}: type={surface.surface_type}, "
            f"sym={surface.symmetry}, sections={len(surface.sections)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
