#!/usr/bin/env python3
"""Export a .vsp3 model to CFD-friendly formats (STEP / STL / IGES).

Typical invocation::

    python scripts/vsp_to_cfd.py \\
        --vsp output/blackcat_004/cruise.vsp3 \\
        --out output/blackcat_004/cruise \\
        --formats step stl

Writes ``<out>.step``, ``<out>.stl``, etc.  The default --formats set is
``step stl`` which covers the common CFD meshing paths (Fluent, StarCCM+,
OpenFOAM via snappyHexMesh all accept STEP/STL directly).

For the jig+cruise pair the recommended pattern is::

    python scripts/vsp_to_cfd.py --vsp .../jig.vsp3    --out .../jig
    python scripts/vsp_to_cfd.py --vsp .../cruise.vsp3 --out .../cruise
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


_EXPORT_MAP = {
    "step": ("EXPORT_STEP", ".step"),
    "stp": ("EXPORT_STEP", ".stp"),
    "iges": ("EXPORT_IGES", ".igs"),
    "igs": ("EXPORT_IGES", ".igs"),
    "stl": ("EXPORT_STL", ".stl"),
    "obj": ("EXPORT_OBJ", ".obj"),
    "dxf": ("EXPORT_DXF", ".dxf"),
}


def _export_one(vsp, vsp3: Path, out_stem: Path, fmt: str) -> Path:
    enum_name, suffix = _EXPORT_MAP[fmt]
    enum_val = getattr(vsp, enum_name)
    out_path = out_stem.with_suffix(suffix)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vsp.ClearVSPModel()
    vsp.ReadVSPFile(str(vsp3))
    vsp.Update()
    # SET_ALL = 0 in the OpenVSP API; export the full geometry.
    vsp.ExportFile(str(out_path), getattr(vsp, "SET_ALL", 0), enum_val)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vsp", required=True, help="Input .vsp3 file")
    parser.add_argument("--out", required=True,
                        help="Output stem (suffix added per format)")
    parser.add_argument("--formats", nargs="+", default=["step", "stl"],
                        choices=list(_EXPORT_MAP.keys()))
    args = parser.parse_args(argv)

    vsp3 = Path(args.vsp)
    if not vsp3.is_file():
        print(f"[ERR] input not found: {vsp3}", file=sys.stderr)
        return 2

    try:
        import openvsp as vsp  # type: ignore
    except ImportError:
        print("[ERR] openvsp python bindings required (install from OpenVSP python/).",
              file=sys.stderr)
        return 3

    out_stem = Path(args.out)
    written: list[Path] = []
    for fmt in args.formats:
        try:
            path = _export_one(vsp, vsp3, out_stem, fmt)
            written.append(path)
            print(f"[OK] {fmt:>5}  -> {path}")
        except Exception as exc:  # pragma: no cover — defensive
            print(f"[WARN] {fmt} export failed: {exc}", file=sys.stderr)

    if not written:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
