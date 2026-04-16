#!/usr/bin/env python
"""One-click ParaView launcher for HPA high-fidelity validation results.

Usage
-----
# Auto-discover results from the default output directory:
python scripts/hifi_open_paraview.py

# Specify a custom hifi output directory:
python scripts/hifi_open_paraview.py --hifi-dir output/blackcat_004/hifi

# Specify individual FRD files directly:
python scripts/hifi_open_paraview.py \\
    --static output/blackcat_004/hifi/static.frd \\
    --buckle output/blackcat_004/hifi/buckle_mode01.frd \\
             output/blackcat_004/hifi/buckle_mode02.frd

# Just generate the script without launching:
python scripts/hifi_open_paraview.py --no-launch
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Resolve project root relative to this script
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent


def _find_paraview_binary(config_binary: str | None) -> str | None:
    """Return a usable pvpython path or None."""
    candidates = []
    if config_binary:
        candidates.append(config_binary)
    # Common install locations
    candidates += [
        "/Applications/ParaView.app/Contents/bin/pvpython",
        "/usr/local/bin/pvpython",
        "/usr/bin/pvpython",
        "/opt/homebrew/bin/pvpython",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


def _load_config_binary() -> str | None:
    """Try to read the ParaView binary path from the project config."""
    try:
        import yaml  # noqa: PLC0415
        cfg_path = _PROJECT_ROOT / "configs" / "blackcat_004.yaml"
        if not cfg_path.exists():
            return None
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        return (cfg.get("hi_fidelity", {}) or {}).get("paraview", {}).get("binary")
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a pvpython visualisation script and optionally launch ParaView."
    )
    parser.add_argument(
        "--hifi-dir",
        default=None,
        help="Directory containing CalculiX .frd outputs (default: output/blackcat_004/hifi).",
    )
    parser.add_argument(
        "--static",
        default=None,
        metavar="FRD",
        help="Static analysis .frd file (overrides auto-discovery).",
    )
    parser.add_argument(
        "--buckle",
        nargs="*",
        default=None,
        metavar="FRD",
        help="Buckling mode .frd file(s) (overrides auto-discovery).",
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="PY",
        help="Output pvpython script path (default: hifi_dir/visualise.py).",
    )
    parser.add_argument(
        "--warp-scale",
        type=float,
        default=10.0,
        help="Deformation magnification factor (default: 10).",
    )
    parser.add_argument(
        "--show-modes",
        type=int,
        default=6,
        help="Maximum number of buckling modes to display (default: 6).",
    )
    parser.add_argument(
        "--span",
        type=float,
        default=16.5,
        help="Half-span [m] for camera positioning (default: 16.5 m).",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Generate the script but do not launch ParaView.",
    )
    parser.add_argument(
        "--pvpython",
        default=None,
        metavar="BIN",
        help="Path to pvpython binary (auto-detected if omitted).",
    )
    args = parser.parse_args()

    # ── Resolve FRD files ──────────────────────────────────────────────────
    from hpa_mdo.hifi.paraview_state import discover_frd_files, make_pvpython_script

    if args.static or args.buckle:
        static_frd = Path(args.static).resolve() if args.static else None
        buckle_frds = [Path(b).resolve() for b in (args.buckle or [])]
    else:
        hifi_dir = Path(args.hifi_dir) if args.hifi_dir else (
            _PROJECT_ROOT / "output" / "blackcat_004" / "hifi"
        )
        static_frd, buckle_frds = discover_frd_files(hifi_dir)
        if static_frd is None and not buckle_frds:
            print(
                f"[hpa-mdo] No .frd files found in {hifi_dir}.\n"
                "Run the CalculiX high-fidelity analysis first:\n"
                "  python scripts/run_hifi.py",
                file=sys.stderr,
            )
            sys.exit(1)

    all_frds = [p for p in [static_frd] + buckle_frds if p is not None]
    print(f"[hpa-mdo] Found {len(all_frds)} FRD file(s):")
    for p in all_frds:
        print(f"          {p}")

    # ── Generate script ────────────────────────────────────────────────────
    if args.out:
        out_py = Path(args.out).resolve()
    else:
        base_dir = static_frd.parent if static_frd else (buckle_frds[0].parent if buckle_frds else Path.cwd())
        out_py = base_dir / "visualise.py"

    script_path = make_pvpython_script(
        all_frds,
        out_py,
        warp_scale=args.warp_scale,
        show_modes=args.show_modes,
        span_m=args.span,
    )
    print(f"[hpa-mdo] Script written → {script_path}")

    # ── Launch ParaView ────────────────────────────────────────────────────
    if args.no_launch:
        print("[hpa-mdo] --no-launch: skipping ParaView launch.")
        return

    pvpython = args.pvpython or _find_paraview_binary(_load_config_binary())
    if pvpython is None:
        print(
            "[hpa-mdo] pvpython not found.  Set hi_fidelity.paraview.binary in\n"
            "          configs/blackcat_004.yaml or pass --pvpython <path>.\n"
            f"          Script is ready at: {script_path}",
            file=sys.stderr,
        )
        sys.exit(0)  # not an error — script is usable

    print(f"[hpa-mdo] Launching: {pvpython} {script_path}")
    try:
        subprocess.run([pvpython, str(script_path)], check=True)
    except subprocess.CalledProcessError as exc:
        print(f"[hpa-mdo] pvpython exited with code {exc.returncode}.", file=sys.stderr)
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
