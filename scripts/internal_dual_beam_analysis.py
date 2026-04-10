#!/usr/bin/env python3
"""Run the internal dual-beam analysis path for Black Cat 004.

This script keeps the existing equivalent-beam optimizer untouched and adds
a separate analysis-only dual-beam route for model-form assessment.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys

# Allow running directly from the repository without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import SparOptimizer
from hpa_mdo.structure.dual_beam_analysis import run_dual_beam_analysis
from scripts.ansys_crossval import _select_cruise_loads


@dataclass
class ComparisonRow:
    metric: str
    internal_value: float
    ansys_value: float
    error_pct: float


def _error_pct(internal_value: float, ansys_value: float) -> float:
    denom = max(abs(ansys_value), 1e-12)
    return abs(internal_value - ansys_value) / denom * 100.0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run internal dual-beam analysis for dual-spar model-form checking."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
        help="Path to YAML configuration file.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/blackcat_004_internal_dual_beam",
        help="Directory for the generated internal dual-beam report.",
    )
    parser.add_argument(
        "--optimizer-method",
        choices=("auto", "openmdao", "scipy"),
        default="auto",
        help="Method for obtaining the baseline optimized design variables.",
    )
    parser.add_argument(
        "--main-r-scale",
        type=float,
        default=1.0,
        help="Scale factor applied to main spar segment radii before dual-beam analysis.",
    )
    parser.add_argument(
        "--rear-r-scale",
        type=float,
        default=1.0,
        help="Scale factor applied to rear spar segment radii before dual-beam analysis.",
    )
    parser.add_argument(
        "--main-t-scale",
        type=float,
        default=1.0,
        help="Scale factor applied to main spar segment thicknesses before dual-beam analysis.",
    )
    parser.add_argument(
        "--rear-t-scale",
        type=float,
        default=1.0,
        help="Scale factor applied to rear spar segment thicknesses before dual-beam analysis.",
    )
    parser.add_argument(
        "--ansys-dir",
        default=None,
        help="Optional ANSYS result directory for immediate first-round comparison.",
    )
    parser.add_argument(
        "--ansys-baseline-report",
        default=None,
        help="Optional ANSYS baseline report path (default: <ansys-dir>/crossval_report.txt).",
    )
    parser.add_argument(
        "--ansys-rst",
        default="file.rst",
        help="Optional RST filename under --ansys-dir.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    cfg_path = Path(args.config).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "dual_beam_internal_report.txt"

    cfg = load_config(cfg_path)
    aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()

    cruise_aoa_deg, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)

    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, mat_db)
    opt_result = optimizer.optimize(method=args.optimizer_method)

    scaled_result = opt_result
    if (
        args.main_r_scale != 1.0
        or args.rear_r_scale != 1.0
        or args.main_t_scale != 1.0
        or args.rear_t_scale != 1.0
    ):
        scaled_result = optimizer.analyze(
            main_t_seg=opt_result.main_t_seg_mm * 1e-3 * args.main_t_scale,
            main_r_seg=opt_result.main_r_seg_mm * 1e-3 * args.main_r_scale,
            rear_t_seg=(
                None
                if opt_result.rear_t_seg_mm is None
                else opt_result.rear_t_seg_mm * 1e-3 * args.rear_t_scale
            ),
            rear_r_seg=(
                None
                if opt_result.rear_r_seg_mm is None
                else opt_result.rear_r_seg_mm * 1e-3 * args.rear_r_scale
            ),
        )

    dual = run_dual_beam_analysis(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=scaled_result,
        export_loads=export_loads,
        materials_db=mat_db,
        bc_penalty=cfg.solver.fem_bc_penalty,
    )

    compare_rows: list[ComparisonRow] = []
    ansys_note = "No ANSYS comparison requested."
    if args.ansys_dir:
        ansys_dir = Path(args.ansys_dir).expanduser().resolve()
        baseline_report = (
            Path(args.ansys_baseline_report).expanduser().resolve()
            if args.ansys_baseline_report
            else ansys_dir / "crossval_report.txt"
        )
        rst_path = ansys_dir / args.ansys_rst
        mac_path = ansys_dir / "spar_model.mac"

        from scripts.ansys_compare_results import (
            extract_ansys_metrics_from_rst,
            parse_baseline_metrics,
        )

        try:
            baseline_metrics = parse_baseline_metrics(baseline_report, mac_path=mac_path)
            ansys_metrics = extract_ansys_metrics_from_rst(rst_path, baseline_metrics, ansys_dir)

            internal_tip_mm = abs(dual.tip_deflection_main_m) * 1000.0
            internal_max_mm = abs(dual.max_vertical_displacement_m) * 1000.0
            internal_reaction_n = abs(dual.support_reaction_fz_n)
            internal_mass_kg = dual.spar_mass_full_kg

            if ansys_metrics.tip_deflection_mm is not None:
                compare_rows.append(
                    ComparisonRow(
                        "Tip deflection main (mm)",
                        internal_tip_mm,
                        ansys_metrics.tip_deflection_mm,
                        _error_pct(internal_tip_mm, ansys_metrics.tip_deflection_mm),
                    )
                )
            if ansys_metrics.max_uz_mm is not None:
                compare_rows.append(
                    ComparisonRow(
                        "Max |UZ| anywhere (mm)",
                        internal_max_mm,
                        ansys_metrics.max_uz_mm,
                        _error_pct(internal_max_mm, ansys_metrics.max_uz_mm),
                    )
                )
            if ansys_metrics.root_reaction_fz_n is not None:
                compare_rows.append(
                    ComparisonRow(
                        "Support reaction Fz all supports (N)",
                        internal_reaction_n,
                        ansys_metrics.root_reaction_fz_n,
                        _error_pct(internal_reaction_n, ansys_metrics.root_reaction_fz_n),
                    )
                )
            if ansys_metrics.total_spar_mass_kg is not None:
                compare_rows.append(
                    ComparisonRow(
                        "Spar mass full-span (kg)",
                        internal_mass_kg,
                        ansys_metrics.total_spar_mass_kg,
                        _error_pct(internal_mass_kg, ansys_metrics.total_spar_mass_kg),
                    )
                )

            ansys_note = f"Compared against ANSYS results in: {ansys_dir}"
        except Exception as exc:  # pragma: no cover - optional dependency/runtime path
            ansys_note = (
                "ANSYS comparison requested but unavailable in this run: "
                f"{exc}"
            )

    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines: list[str] = []
    lines.append("=" * 88)
    lines.append("Internal Dual-Beam Analysis Report")
    lines.append("=" * 88)
    lines.append(f"Generated      : {ts}")
    lines.append(f"Config         : {cfg_path.name}")
    lines.append(f"Cruise AoA     : {cruise_aoa_deg:.2f} deg")
    lines.append("Purpose        : internal analysis-only dual-beam path (non-gating)")
    lines.append("")
    lines.append("Design variable scales:")
    lines.append(f"  main_r_scale : {args.main_r_scale:.4f}")
    lines.append(f"  rear_r_scale : {args.rear_r_scale:.4f}")
    lines.append(f"  main_t_scale : {args.main_t_scale:.4f}")
    lines.append(f"  rear_t_scale : {args.rear_t_scale:.4f}")
    lines.append("")
    lines.append("Internal dual-beam outputs:")
    lines.append(f"  Tip deflection main (mm)         : {abs(dual.tip_deflection_main_m) * 1000.0:.3f}")
    lines.append(f"  Tip deflection rear (mm)         : {abs(dual.tip_deflection_rear_m) * 1000.0:.3f}")
    lines.append(f"  Max |UZ| anywhere (mm)           : {abs(dual.max_vertical_displacement_m) * 1000.0:.3f}")
    lines.append(
        f"  Max |UZ| location                : {dual.max_vertical_spar} node {dual.max_vertical_node}"
    )
    lines.append(f"  Support reaction Fz all supports : {abs(dual.support_reaction_fz_n):.3f} N")
    lines.append(f"  Spar mass full-span              : {dual.spar_mass_full_kg:.3f} kg")
    lines.append(f"  Max VM main                      : {dual.max_vm_main_pa / 1e6:.3f} MPa")
    lines.append(f"  Max VM rear                      : {dual.max_vm_rear_pa / 1e6:.3f} MPa")
    lines.append(f"  Failure index (non-gating here)  : {dual.failure_index:.4f}")
    lines.append("")
    lines.append(ansys_note)

    if compare_rows:
        lines.append("")
        lines.append(
            f"{'Metric':42} {'Internal':>12} {'ANSYS':>12} {'Error %':>10}"
        )
        lines.append("-" * 88)
        for row in compare_rows:
            lines.append(
                f"{row.metric:42} "
                f"{row.internal_value:12.3f} "
                f"{row.ansys_value:12.3f} "
                f"{row.error_pct:10.2f}"
            )

    lines.append("")
    lines.append(
        "Note: This path is for internal dual-beam feasibility/comparison work. "
        "It does not change the equivalent-beam Phase I gate semantics."
    )

    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text, encoding="utf-8")

    print("Internal dual-beam analysis complete.")
    print(f"  Report: {report_path}")
    print(f"  Max |UZ| location: {dual.max_vertical_spar} node {dual.max_vertical_node}")
    if compare_rows:
        print("  ANSYS comparison rows:")
        for row in compare_rows:
            print(
                f"    - {row.metric}: internal={row.internal_value:.3f}, "
                f"ansys={row.ansys_value:.3f}, error={row.error_pct:.2f}%"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
