#!/usr/bin/env python3
"""Reconcile reference .vsp3 planform with config and baseline AVL.

The project has three independent geometry records:

1. **Reference .vsp3** (path via `config.io.vsp_model`) — the original CAD
   model from the chief designer. Treated as geometric truth.
2. **Config YAML** — `wing.span`, `wing.root_chord`, `wing.tip_chord`, and
   (when present) `wing.sections` defining y/chord schedule.
3. **Baseline AVL** — `data/blackcat_004_full.avl` carrying `Sref`,
   `Bref`, `Cref` for stability analyses.

If these three disagree the stability and load-mapping pipelines end
up running on inconsistent reference areas. This script extracts the
planform from (1), derives Sref/Bref/Cref by trapezoidal integration,
and compares against (2) and (3). Flags anything off by more than
--tolerance-pct. Optionally writes a suggested overlay YAML for manual
merge; never mutates committed files directly.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from hpa_mdo.core.config import load_config, HPAConfig


def _extract_reference_schedule(cfg: HPAConfig) -> list[dict]:
    try:
        import openvsp as vsp  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "openvsp python bindings required. Install from the OpenVSP "
            "distribution's python/ directory."
        ) from exc

    from hpa_mdo.aero.vsp_builder import VSPBuilder

    vsp_model = cfg.io.vsp_model
    if vsp_model is None or not Path(vsp_model).is_file():
        raise SystemExit(
            f"io.vsp_model not found: {vsp_model}. "
            "Set sync_root in configs/local_paths.yaml first."
        )
    builder = VSPBuilder(cfg)
    vsp.ClearVSPModel()
    vsp.ReadVSPFile(str(vsp_model))
    vsp.Update()
    wing_id = builder._find_reference_wing_geom(vsp)
    if wing_id is None:
        raise SystemExit(f"No main wing geom found in {vsp_model}.")
    return builder._extract_reference_wing_schedule(vsp, wing_id)


def _planform_metrics(schedule: list[dict]) -> dict:
    y = np.asarray([float(s["y"]) for s in schedule], dtype=float)
    c = np.asarray([float(s["chord"]) for s in schedule], dtype=float)
    order = np.argsort(y)
    y_s, c_s = y[order], c[order]
    half_area = float(np.trapezoid(c_s, y_s))
    sref = 2.0 * half_area
    bref = 2.0 * float(y_s.max())
    # MAC = ∫c² dy / ∫c dy (integrals on the same half-span cancel the factor of 2).
    cref = float(np.trapezoid(c_s * c_s, y_s)) / half_area if half_area > 0 else 0.0
    taper = float(c_s[-1] / c_s[0]) if c_s[0] > 0 else float("nan")
    return {
        "sref_m2": sref, "bref_m": bref, "cref_m": cref, "taper": taper,
        "n_stations": len(schedule),
        "y_stations_m": y_s.tolist(), "chords_m": c_s.tolist(),
    }


def _read_avl_ref(avl_path: Path) -> dict:
    """Pull #Sref/#Bref/#Cref numeric lines from an AVL file."""
    text = avl_path.read_text(encoding="utf-8").splitlines()
    sref = cref = bref = float("nan")
    for i, line in enumerate(text):
        u = line.strip().upper()
        if u.startswith("#SREF") and i + 1 < len(text):
            parts = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text[i + 1])
            if len(parts) >= 3:
                sref, cref, bref = map(float, parts[:3])
            break
    return {"sref_m2": sref, "cref_m": cref, "bref_m": bref}


def _pct(a: float, b: float) -> float:
    if b == 0.0 or not (np.isfinite(a) and np.isfinite(b)):
        return float("nan")
    return 100.0 * (a - b) / b


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/blackcat_004.yaml")
    parser.add_argument("--avl", default="data/blackcat_004_full.avl",
                        help="Baseline AVL file whose Sref/Bref/Cref to check.")
    parser.add_argument("--tolerance-pct", type=float, default=2.0)
    parser.add_argument("--write", default=None,
                        help="Write a suggested overlay YAML here (manual merge).")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    schedule = _extract_reference_schedule(cfg)
    vsp_m = _planform_metrics(schedule)
    avl_ref = _read_avl_ref(Path(args.avl)) if Path(args.avl).is_file() else None

    cfg_bref = float(cfg.wing.span)
    cfg_root = float(cfg.wing.root_chord)
    cfg_tip = float(cfg.wing.tip_chord)
    vsp_root = float(vsp_m["chords_m"][0])
    vsp_tip = float(vsp_m["chords_m"][-1])
    # Informational: Sref and MAC from a PURE linear root/tip taper.
    # For the real VSP (which carries a flat inboard region etc.) this
    # disagrees by design; do not include in the tolerance check.
    cfg_sref_linear = 0.5 * (cfg_root + cfg_tip) * cfg_bref
    cfg_cref_linear = (
        (cfg_root * cfg_root + cfg_root * cfg_tip + cfg_tip * cfg_tip)
        / (1.5 * (cfg_root + cfg_tip))
    )

    print(f"\nReference VSP : {cfg.io.vsp_model}")
    print(f"Config        : {args.config}")
    print(f"Baseline AVL  : {args.avl}")
    print(f"\nVSP planform: {vsp_m['n_stations']} stations, taper {vsp_m['taper']:.3f}\n")

    # Flagged rows (checked against --tolerance-pct).
    rows: list[tuple[str, float, float]] = [
        ("Bref [m]    (config.wing.span)       ", cfg_bref, vsp_m["bref_m"]),
        ("Root chord  (config.wing.root_chord) ", cfg_root, vsp_root),
        ("Tip chord   (config.wing.tip_chord)  ", cfg_tip, vsp_tip),
    ]
    if avl_ref is not None:
        rows += [
            ("Sref [m^2]  (baseline AVL file)      ", avl_ref["sref_m2"], vsp_m["sref_m2"]),
            ("Bref [m]    (baseline AVL file)      ", avl_ref["bref_m"], vsp_m["bref_m"]),
            ("Cref [m]    (baseline AVL file)      ", avl_ref["cref_m"], vsp_m["cref_m"]),
        ]
    # Informational-only rows (not flagged).
    info_rows: list[tuple[str, float, float]] = [
        ("Sref [m^2]  (config root/tip linear) ", cfg_sref_linear, vsp_m["sref_m2"]),
        ("Cref [m]    (config root/tip linear) ", cfg_cref_linear, vsp_m["cref_m"]),
    ]

    print(f"{'Metric':<40}{'Source':>14}{'VSP truth':>14}{'Diff':>12}")
    print("-" * 80)
    any_flag = False
    for label, src, vv in rows:
        diff = _pct(src, vv)
        flag = " *" if np.isfinite(diff) and abs(diff) > args.tolerance_pct else ""
        if flag:
            any_flag = True
        src_s = f"{src:>14.4f}" if np.isfinite(src) else f"{'n/a':>14}"
        vv_s = f"{vv:>14.4f}"
        diff_s = f"{diff:>+10.2f}%" if np.isfinite(diff) else f"{'n/a':>12}"
        print(f"{label:<40}{src_s}{vv_s}{diff_s}{flag}")

    print("\nInformational (not flagged — VSP has non-linear planform):")
    for label, src, vv in info_rows:
        diff = _pct(src, vv)
        src_s = f"{src:>14.4f}" if np.isfinite(src) else f"{'n/a':>14}"
        vv_s = f"{vv:>14.4f}"
        diff_s = f"{diff:>+10.2f}%" if np.isfinite(diff) else f"{'n/a':>12}"
        print(f"{label:<40}{src_s}{vv_s}{diff_s}")

    print("\n7-station schedule from reference VSP:")
    print(f"{'y [m]':>8}{'chord [m]':>12}")
    for y_val, c_val in zip(vsp_m["y_stations_m"], vsp_m["chords_m"]):
        print(f"{y_val:>8.3f}{c_val:>12.4f}")

    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        overlay = [
            "# Suggested AVL reference update — manual merge after review.",
            f"# Generated from {cfg.io.vsp_model} by vsp_consistency_check.py",
            "#",
            "# Update data/blackcat_004_full.avl header to:",
            "#",
            f"#Sref  Cref  Bref",
            f"{vsp_m['sref_m2']:.9f}  {vsp_m['cref_m']:.9f}  {vsp_m['bref_m']:.9f}",
            "#",
        ]
        out_path.write_text("\n".join(overlay) + "\n", encoding="utf-8")
        print(f"\nWrote AVL header overlay: {out_path}")

    if any_flag:
        print(f"\n[WARN] Metrics marked '*' differ by more than {args.tolerance_pct:.1f}%.")
        print("[WARN] Reference .vsp3 is geometric truth — update config & AVL baseline.")
        return 2
    print("\n[OK] All metrics within tolerance of the reference VSP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
