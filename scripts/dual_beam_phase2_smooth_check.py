#!/usr/bin/env python3
"""Baseline smoke check for the dual-beam Phase-2 smooth evaluator path."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure.dual_beam_mainline import (
    AnalysisModeName,
    run_dual_beam_mainline_analysis,
)
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_crossval import _select_cruise_loads
from scripts.ansys_dual_beam_production_check import (
    build_specimen_result_from_crossval_report,
)


def _status(flag: bool) -> str:
    return "PASS" if flag else "FAIL"


def _mm(value_m: float) -> float:
    return abs(float(value_m) * 1000.0)


def build_phase2_report(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    production_result,
    parity_result,
) -> str:
    """Build a human-readable Phase-2 baseline report."""

    optimizer = production_result.optimizer
    eq = optimizer.equivalent_gates
    feasibility = production_result.feasibility
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "Dual-Beam Production Phase-2 Smooth Evaluator Baseline",
        "=" * 60,
        f"Timestamp                     {timestamp}",
        f"Config                        {config_path}",
        f"Design report                 {design_report}",
        f"Cruise AoA                    {cruise_aoa_deg:11.3f} deg",
        "",
        "Production baseline:",
        f"  Raw main tip                 {_mm(production_result.report.tip_deflection_main_m):11.3f} mm",
        f"  Raw rear tip                 {_mm(production_result.report.tip_deflection_rear_m):11.3f} mm",
        f"  Raw max |UZ|                 {_mm(production_result.report.max_vertical_displacement_m):11.3f} mm",
        f"  Raw max |UZ| location        {production_result.report.max_vertical_spar} node {production_result.report.max_vertical_node}",
        f"  psi_u_all                    {_mm(optimizer.psi_u_all_m):11.3f} mm",
        f"  psi_u_rear                   {_mm(optimizer.psi_u_rear_m):11.3f} mm",
        f"  psi_u_rear_outboard          {_mm(optimizer.psi_u_rear_outboard_m):11.3f} mm",
        f"  Dual displacement limit      {_mm(optimizer.dual_displacement_limit_m):11.3f} mm"
        if optimizer.dual_displacement_limit_m is not None
        else "  Dual displacement limit      none",
        f"  Spar tube mass               {production_result.recovery.spar_tube_mass_full_kg:11.3f} kg",
        "",
        "Equivalent validated gates (legacy retained):",
        f"  Analysis success             {_status(eq.analysis_success)}",
        f"  Failure gate                 {_status(eq.failure_passed)}  value={eq.failure_index:8.4f}  margin={eq.failure_margin:8.4f}",
        f"  Buckling gate                {_status(eq.buckling_passed)}  value={eq.buckling_index:8.4f}  margin={eq.buckling_margin:8.4f}",
        f"  Tip-deflection gate          {_status(eq.tip_passed)}  value={_mm(eq.tip_deflection_m):8.3f} mm  margin={_mm(eq.tip_margin_m):8.3f} mm"
        if eq.tip_limit_m is not None
        else f"  Tip-deflection gate          {_status(eq.tip_passed)}  value={_mm(eq.tip_deflection_m):8.3f} mm  margin=inf",
        f"  Twist gate                   {_status(eq.twist_passed)}  value={eq.twist_max_deg:8.3f} deg  margin={eq.twist_margin_deg:8.3f} deg"
        if eq.twist_limit_deg is not None
        else f"  Twist gate                   {_status(eq.twist_passed)}  value={eq.twist_max_deg:8.3f} deg  margin=inf",
        "",
        "Feasibility summary:",
        f"  Dual analysis success        {_status(feasibility.analysis_succeeded)}",
        f"  Geometry validity            {_status(feasibility.geometry_validity_succeeded)}",
        f"  Dual displacement candidate  {_status(feasibility.dual_displacement_candidate_passed)}",
        f"  Overall hard feasible        {_status(feasibility.overall_hard_feasible)}",
        f"  Overall optimizer candidate  {_status(feasibility.overall_optimizer_candidate_feasible)}",
        f"  Hard failures                {', '.join(feasibility.hard_failures) if feasibility.hard_failures else 'none'}",
        f"  Candidate-only failures      {', '.join(feasibility.candidate_constraint_failures) if feasibility.candidate_constraint_failures else 'none'}",
        f"  Report-only channels         {', '.join(feasibility.report_only_channels)}",
        "",
        "Parity sanity:",
        f"  Parity raw main/rear/max     {_mm(parity_result.report.tip_deflection_main_m):11.3f} / {_mm(parity_result.report.tip_deflection_rear_m):11.3f} / {_mm(parity_result.report.max_vertical_displacement_m):11.3f} mm",
        f"  Parity psi_u_all/rear/out    {_mm(parity_result.optimizer.psi_u_all_m):11.3f} / {_mm(parity_result.optimizer.psi_u_rear_m):11.3f} / {_mm(parity_result.optimizer.psi_u_rear_outboard_m):11.3f} mm",
        f"  Production-parity delta psi_u_all   {_mm(production_result.optimizer.psi_u_all_m - parity_result.optimizer.psi_u_all_m):11.3f} mm",
        f"  Production-parity delta psi_u_rear  {_mm(production_result.optimizer.psi_u_rear_m - parity_result.optimizer.psi_u_rear_m):11.3f} mm",
        "",
        "Optimizer-facing outputs:",
        "  psi_u_all, psi_u_rear, psi_u_rear_outboard, geometry_validity, equivalent_gates, feasibility summary",
        "Report-only outputs:",
        "  raw max |UZ|, argmax location, raw rear/main tip ratio, root reaction partition, link hotspots, dual stress/buckling",
    ]
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
    )
    parser.add_argument(
        "--design-report",
        default=str(
            Path(__file__).resolve().parent.parent
            / "output"
            / "blackcat_004"
            / "ansys"
            / "crossval_report.txt"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(
            Path(__file__).resolve().parent.parent
            / "output"
            / "blackcat_004_phase2_smooth_check"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    design_report = Path(args.design_report).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(config_path)
    specimen_baseline = parse_baseline_metrics(design_report)
    cfg.solver.n_beam_nodes = int(specimen_baseline.nodes_per_spar)
    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    opt_result = build_specimen_result_from_crossval_report(design_report)

    cruise_aoa_deg, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)

    production = run_dual_beam_mainline_analysis(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=opt_result,
        export_loads=export_loads,
        materials_db=materials_db,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
    )
    parity = run_dual_beam_mainline_analysis(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=opt_result,
        export_loads=export_loads,
        materials_db=materials_db,
        mode=AnalysisModeName.DUAL_SPAR_ANSYS_PARITY,
    )

    report_text = build_phase2_report(
        config_path=config_path,
        design_report=design_report,
        cruise_aoa_deg=cruise_aoa_deg,
        production_result=production,
        parity_result=parity,
    )
    report_path = output_dir / "phase2_smooth_report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    print("Dual-beam Phase-2 smooth evaluator baseline generated.")
    print(f"  Config              : {config_path}")
    print(f"  Design report       : {design_report}")
    print(f"  Cruise AoA          : {cruise_aoa_deg:.3f} deg")
    print(f"  Report              : {report_path}")
    print(
        f"  Production raw/smooth max|UZ| : "
        f"{_mm(production.report.max_vertical_displacement_m):.3f} / "
        f"{_mm(production.optimizer.psi_u_all_m):.3f} mm"
    )
    print(
        f"  Feasible (hard / candidate)   : "
        f"{production.feasibility.overall_hard_feasible} / "
        f"{production.feasibility.overall_optimizer_candidate_feasible}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
