#!/usr/bin/env python3
"""Analyze any .vsp3 by auto-extracting geometry + running the MDO pipeline.

Usage
-----
Most common — point at a .vsp3 file and let the tool infer the rest::

    python scripts/analyze_vsp.py --vsp path/to/any.vsp3

Override engineering parameters (safety factors, spar design, materials)
by providing a template config; only wing / tail / io.vsp_model get
replaced from the VSP::

    python scripts/analyze_vsp.py \\
        --vsp path/to/any.vsp3 \\
        --template configs/blackcat_004.yaml

Output lands in ``output/<vsp_stem>/`` so multiple aircraft can be
analysed without clobbering each other.

Convention
----------
See ``src/hpa_mdo/aero/vsp_introspect.py`` for the geometry auto-detect
heuristic.  Briefly: the main wing is the largest XZ-symmetric WING
geom; the horizontal tail is the second-largest symmetric WING geom;
the vertical fin is a non-symmetric WING geom with ~90° X rotation or
name matching ``fin``/``vtail``/``rudder``.

Files NOT written by this CLI:
    * Reference .vsp3 itself (input only)
    * configs/local_paths.yaml (machine-specific, hand-edited)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


DEFAULT_TEMPLATE = "configs/blackcat_004.yaml"


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _write_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vsp", required=True,
                        help="Absolute or sync-root-relative path to a .vsp3 file.")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE,
                        help=f"YAML config supplying engineering defaults "
                             f"(safety, spar design, solver). Default: {DEFAULT_TEMPLATE}")
    parser.add_argument("--output-root", default="output",
                        help="Parent dir for <vsp_stem>/ output folder.")
    parser.add_argument("--no-run", action="store_true",
                        help="Resolve + dump merged config only; skip running the optimizer.")
    parser.add_argument("--dump-summary", default=None,
                        help="Optional path to dump the raw VSP summary as JSON.")
    args = parser.parse_args(argv)

    vsp_path = Path(args.vsp).expanduser()
    if not vsp_path.is_absolute():
        # Try sync_root resolution via local_paths.yaml.
        local_paths = Path("configs/local_paths.yaml")
        if local_paths.is_file():
            local = _load_yaml(local_paths)
            sync_root = (local.get("io") or {}).get("sync_root")
            if sync_root:
                candidate = Path(sync_root) / args.vsp
                if candidate.is_file():
                    vsp_path = candidate
    if not vsp_path.is_file():
        print(f"[ERR] VSP file not found: {args.vsp}", file=sys.stderr)
        return 2

    print(f"[1/4] Reading {vsp_path}")
    from hpa_mdo.aero.vsp_introspect import (
        summarize_vsp_surfaces, merge_into_config_dict
    )
    try:
        summary = summarize_vsp_surfaces(vsp_path)
    except Exception as exc:
        print(f"[ERR] Introspection failed: {exc}", file=sys.stderr)
        return 3

    if args.dump_summary:
        import json
        Path(args.dump_summary).parent.mkdir(parents=True, exist_ok=True)
        with open(args.dump_summary, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)
        print(f"        Dumped summary → {args.dump_summary}")

    print(f"[2/4] Loading template: {args.template}")
    template = _load_yaml(Path(args.template))
    merged = merge_into_config_dict(template, summary)

    # Per-VSP output dir.
    stem = vsp_path.stem
    out_dir = (Path(args.output_root) / stem).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    merged.setdefault("io", {})
    merged["io"]["output_dir"] = str(out_dir)
    # Keep sync_root=null so paths aren't tied to a user machine.
    merged["io"]["sync_root"] = None

    # Resolve sibling VSPAero artifacts next to the .vsp3.  Convention:
    # <stem>_VSPGeom.lod / <stem>_VSPGeom.polar in the same directory.
    # Fall back to any *.lod / *.polar in the same dir if the exact name
    # is missing (so users can drop a VSPAero run output alongside).
    vsp_dir = vsp_path.parent
    lod_candidate = vsp_dir / f"{vsp_path.stem}_VSPGeom.lod"
    polar_candidate = vsp_dir / f"{vsp_path.stem}_VSPGeom.polar"
    if not lod_candidate.is_file():
        lods = sorted(vsp_dir.glob("*.lod"))
        if lods:
            lod_candidate = lods[0]
    if not polar_candidate.is_file():
        polars = sorted(vsp_dir.glob("*.polar"))
        if polars:
            polar_candidate = polars[0]
    if lod_candidate.is_file():
        merged["io"]["vsp_lod"] = str(lod_candidate)
    if polar_candidate.is_file():
        merged["io"]["vsp_polar"] = str(polar_candidate)

    resolved_cfg_path = out_dir / "resolved_config.yaml"
    _write_yaml(merged, resolved_cfg_path)
    print(f"        Wrote merged config → {resolved_cfg_path}")

    # Sanity: validate via Pydantic before running anything heavy.
    print("[3/4] Validating merged config via HPAConfig …")
    from hpa_mdo.core.config import HPAConfig
    HPAConfig(**merged)  # raises on failure
    print("        OK")

    if args.no_run:
        print("[4/4] --no-run specified; skipping optimizer. Re-run with:")
        print(f"        python examples/blackcat_004_optimize.py --config {resolved_cfg_path}")
        return 0

    print(f"[4/4] Running optimizer with resolved config …")
    cmd = [sys.executable, "examples/blackcat_004_optimize.py",
           "--config", str(resolved_cfg_path)]
    # Stream child process output; preserve its exit code so val_weight
    # sentinel propagates to any upstream agent loop.
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
