#!/usr/bin/env python
"""ASWING nonlinear aeroelastic cross-validation against the OpenMDAO optimiser.

Usage
-----
# Basic: compare against the latest optimiser result
python scripts/hifi_validate_aswing.py

# Pass explicit MDO values (e.g. from a saved result)
python scripts/hifi_validate_aswing.py \\
    --mdo-tip-defl 2.500 \\
    --mdo-tip-twist-deg -0.501

# Use a different config
python scripts/hifi_validate_aswing.py --config configs/blackcat_004.yaml

Outputs
-------
  output/blackcat_004/hifi/aswing_report.md   — human-readable comparison
  output/blackcat_004/hifi/blackcat_004.asw   — ASWING seed file

Exit codes
----------
  0  — comparison PASS (all differences below warn_threshold_pct)
  1  — ASWING unavailable or run error
  2  — comparison WARN (at least one quantity exceeds warn_threshold_pct)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent


def _load_mdo_result_from_output(output_dir: Path) -> dict:
    """Try to read tip_deflection_m and tip_twist_deg from the optimiser summary."""
    summary = output_dir / "optimization_summary.txt"
    if not summary.exists():
        return {}
    import re
    text = summary.read_text(encoding="utf-8", errors="ignore")
    result = {}
    m = re.search(r"tip_deflection_m\s*[:=]\s*([-\d.eE+]+)", text, re.IGNORECASE)
    if m:
        result["tip_deflection_m"] = float(m.group(1))
    m = re.search(r"tip_twist.*?:\s*([-\d.eE+]+)", text, re.IGNORECASE)
    if m:
        result["tip_twist_deg"] = float(m.group(1))
    return result


def _pct_diff(a: float | None, b: float | None) -> float | None:
    """Return percentage difference 100*(a-b)/b or None if either is absent."""
    if a is None or b is None:
        return None
    if abs(b) < 1e-12:
        return None
    return 100.0 * (a - b) / abs(b)


def _status(diff_pct: float | None, threshold: float) -> str:
    if diff_pct is None:
        return "N/A"
    return "PASS" if abs(diff_pct) <= threshold else "WARN"


def _write_report(
    out_path: Path,
    aswing_result: dict,
    mdo_tip_defl: float | None,
    mdo_tip_twist: float | None,
    warn_threshold: float,
    asw_path: Path,
    vinf: float,
) -> int:
    """Write markdown report; return exit code (0=PASS, 2=WARN)."""
    az_defl = aswing_result.get("tip_deflection_m")
    az_twist = aswing_result.get("tip_twist_deg")
    az_cl = aswing_result.get("CL_trim")
    az_alpha = aswing_result.get("alpha_trim_deg")
    converged = aswing_result.get("converged", False)

    diff_defl = _pct_diff(az_defl, mdo_tip_defl)
    diff_twist = _pct_diff(az_twist, mdo_tip_twist)

    st_defl = _status(diff_defl, warn_threshold)
    st_twist = _status(diff_twist, warn_threshold)

    overall = "PASS" if all(s in ("PASS", "N/A") for s in (st_defl, st_twist)) else "WARN"
    exit_code = 0 if overall == "PASS" else 2

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def _fmt(v: float | None, unit: str = "") -> str:
        if v is None:
            return "—"
        return f"{v:.4g}{unit}"

    def _fmt_pct(v: float | None) -> str:
        if v is None:
            return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.1f}%"

    lines = [
        "# ASWING Cross-Validation Report",
        "",
        f"**Generated:** {timestamp}  ",
        f"**ASWING seed:** `{asw_path}`  ",
        f"**Trim airspeed:** {vinf:.2f} m/s  ",
        f"**Trim converged:** {'✅ Yes' if converged else '⚠️ Not detected'}",
        "",
        "## Trim Solution (ASWING)",
        "",
        f"| Quantity | Value |",
        f"|----------|-------|",
        f"| CL (trim) | {_fmt(az_cl)} |",
        f"| α (trim) | {_fmt(az_alpha, '°')} |",
        f"| Tip deflection | {_fmt(az_defl, ' m')} |",
        f"| Tip twist | {_fmt(az_twist, '°')} |",
        "",
        "## Comparison: ASWING vs OpenMDAO",
        "",
        f"> Warn threshold: ±{warn_threshold:.0f}%",
        "",
        "| Quantity | ASWING | MDO | Δ% | Status |",
        "|----------|--------|-----|----|--------|",
        f"| Tip deflection [m] | {_fmt(az_defl)} | {_fmt(mdo_tip_defl)} "
        f"| {_fmt_pct(diff_defl)} | {st_defl} |",
        f"| Tip twist [°] | {_fmt(az_twist)} | {_fmt(mdo_tip_twist)} "
        f"| {_fmt_pct(diff_twist)} | {st_twist} |",
        "",
        f"## Overall: **{overall}**",
        "",
    ]

    if overall == "WARN":
        lines += [
            "> ⚠️ At least one quantity exceeds the warning threshold.",
            "> Review ASWING seed file for mesh or stiffness discrepancies.",
            "> This does **not** invalidate the MDO result — ASWING uses a",
            "> different aerodynamic model (nonlinear lifting-line vs. VLM).",
            "",
        ]

    if aswing_result.get("error"):
        lines += [
            "## Errors",
            "",
            f"```\n{aswing_result['error']}\n```",
            "",
        ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run ASWING trim and compare with MDO tip deflection / twist."
    )
    parser.add_argument(
        "--config",
        default=str(_PROJECT_ROOT / "configs" / "blackcat_004.yaml"),
        help="Path to project YAML config (default: configs/blackcat_004.yaml).",
    )
    parser.add_argument(
        "--avl",
        default=str(_PROJECT_ROOT / "data" / "blackcat_004_full.avl"),
        help="Path to AVL geometry file (default: data/blackcat_004_full.avl).",
    )
    parser.add_argument(
        "--mdo-tip-defl",
        type=float,
        default=None,
        metavar="M",
        help="MDO tip deflection [m] to compare against (auto-read from summary if absent).",
    )
    parser.add_argument(
        "--mdo-tip-twist-deg",
        type=float,
        default=None,
        metavar="DEG",
        help="MDO tip twist [deg] to compare against (auto-read from summary if absent).",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for .asw and report (default: output/blackcat_004/hifi).",
    )
    parser.add_argument(
        "--aswing-binary",
        default=None,
        metavar="BIN",
        help="Override aswing binary path.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if hi_fidelity.aswing.enabled is false in config.",
    )
    args = parser.parse_args()

    # ── Load config ────────────────────────────────────────────────────────
    from hpa_mdo.core import load_config
    from hpa_mdo.core.materials import MaterialDB

    cfg = load_config(Path(args.config))
    aw_cfg = cfg.hi_fidelity.aswing

    if not aw_cfg.enabled and not args.force:
        print(
            "[hpa-mdo] ASWING runner is disabled (hi_fidelity.aswing.enabled=false).\n"
            "          Set enabled: true in configs/blackcat_004.yaml, or pass --force.",
            file=sys.stderr,
        )
        sys.exit(0)

    # ── Resolve paths ──────────────────────────────────────────────────────
    output_dir = Path(args.out_dir) if args.out_dir else (
        _PROJECT_ROOT / cfg.io.output_dir / "hifi"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    asw_path = output_dir / "blackcat_004.asw"
    report_path = output_dir / "aswing_report.md"

    # ── Export .asw seed ───────────────────────────────────────────────────
    from hpa_mdo.aero.aswing_exporter import export_aswing

    avl_path = Path(args.avl)
    if not avl_path.exists():
        print(f"[hpa-mdo] AVL file not found: {avl_path}", file=sys.stderr)
        sys.exit(1)

    mat_db = MaterialDB(_PROJECT_ROOT / "data" / "materials.yaml")
    print(f"[hpa-mdo] Exporting ASWING seed → {asw_path}")
    export_aswing(avl_path, cfg, asw_path, materials_db=mat_db)

    # ── Run ASWING ─────────────────────────────────────────────────────────
    from hpa_mdo.hifi.aswing_runner import find_aswing, run_aswing

    binary = args.aswing_binary or find_aswing(cfg)
    if binary is None:
        print(
            "[hpa-mdo] ASWING binary not found.  Install ASWING and set\n"
            "          hi_fidelity.aswing.binary in configs/blackcat_004.yaml.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[hpa-mdo] Running ASWING ({binary}) …")
    result = run_aswing(asw_path, cfg, aswing_binary=binary)

    if result["error"]:
        print(f"[hpa-mdo] ASWING error: {result['error']}", file=sys.stderr)

    # ── Resolve MDO reference values ───────────────────────────────────────
    mdo_defl = args.mdo_tip_defl
    mdo_twist = args.mdo_tip_twist_deg

    if mdo_defl is None or mdo_twist is None:
        summary_dir = _PROJECT_ROOT / cfg.io.output_dir
        auto = _load_mdo_result_from_output(summary_dir)
        mdo_defl = mdo_defl if mdo_defl is not None else auto.get("tip_deflection_m")
        mdo_twist = mdo_twist if mdo_twist is not None else auto.get("tip_twist_deg")

    # ── Write report ───────────────────────────────────────────────────────
    vinf = aw_cfg.vinf_mps if aw_cfg.vinf_mps is not None else cfg.flight.velocity
    exit_code = _write_report(
        report_path,
        result,
        mdo_tip_defl=mdo_defl,
        mdo_tip_twist=mdo_twist,
        warn_threshold=aw_cfg.warn_threshold_pct,
        asw_path=asw_path,
        vinf=vinf,
    )

    print(f"[hpa-mdo] Report written → {report_path}")
    print(f"[hpa-mdo] Overall: {'PASS' if exit_code == 0 else 'WARN'}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
