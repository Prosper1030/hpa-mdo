#!/usr/bin/env python3
"""Export and compare ANSYS checks for the new dual-beam production kernel."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import sys

import numpy as np

# Allow running directly from the repository without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.structure.dual_beam_mainline import (
    AnalysisModeName,
    LinkMode,
    run_dual_beam_mainline_analysis,
)
from hpa_mdo.structure.optimizer import OptimizationResult
from scripts.ansys_compare_results import (
    build_report_text,
    extract_ansys_metrics_from_rst,
    parse_baseline_metrics,
)
from scripts.ansys_crossval import _select_cruise_loads


@dataclass(frozen=True)
class ModeSnapshot:
    label: str
    mode: str
    link_mode: str
    main_tip_mm: float
    rear_tip_mm: float
    max_uz_mm: float
    max_uz_location: str
    spar_mass_full_kg: float
    root_main_fz_n: float
    root_rear_fz_n: float
    wire_fz_n: float
    support_total_abs_fz_n: float
    link_force_max_n: float
    reaction_balance_residual_n: float
    hottest_link_nodes: tuple[int, ...]


def _extract_float(pattern: str, text: str, field_name: str) -> float:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"Could not parse {field_name} from {pattern!r}.")
    return float(match.group(1))


def _extract_design_block(text: str, heading: str) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    in_block = False
    for line in text.splitlines():
        if re.match(rf"^{heading}:\s*$", line):
            in_block = True
            continue
        if not in_block:
            continue
        match = re.match(
            r"^\s*Seg\s+\d+:\s+OD=([+-]?\d+(?:\.\d+)?)mm,\s+t=([+-]?\d+(?:\.\d+)?)mm\s*$",
            line,
        )
        if match:
            rows.append((float(match.group(1)), float(match.group(2))))
            continue
        if rows:
            break
    if not rows:
        raise ValueError(f"No segment rows found under {heading}.")
    return rows


def build_specimen_result_from_crossval_report(report_path: Path) -> OptimizationResult:
    """Rebuild an OptimizationResult-like specimen from a saved design report."""

    text = report_path.read_text(encoding="utf-8")
    main_rows = _extract_design_block(text, r"\s*Main spar")
    rear_rows = _extract_design_block(text, r"\s*Rear spar")
    if len(main_rows) != len(rear_rows):
        raise ValueError("Main and rear spar design blocks must have the same segment count.")

    spar_mass_full_kg = _extract_float(
        r"Spar tube mass \(full-span\)\s+([+-]?\d+(?:\.\d+)?)\s+kg",
        text,
        "spar_mass_full_kg",
    )
    total_mass_full_kg = _extract_float(
        r"Total optimized mass \(full\)\s+([+-]?\d+(?:\.\d+)?)\s+kg",
        text,
        "total_mass_full_kg",
    )
    tip_deflection_m = (
        _extract_float(
            r"Tip deflection \(uz, y=[^)]+\)\s+([+-]?\d+(?:\.\d+)?)\s+mm",
            text,
            "tip_deflection_mm",
        )
        * 1.0e-3
    )
    max_tip_deflection_m = None
    max_stress_main_pa = (
        _extract_float(
            r"Max Von Mises \(main spar\)\s+([+-]?\d+(?:\.\d+)?)\s+MPa",
            text,
            "max_vm_main_mpa",
        )
        * 1.0e6
    )
    max_stress_rear_pa = (
        _extract_float(
            r"Max Von Mises \(rear spar\)\s+([+-]?\d+(?:\.\d+)?)\s+MPa",
            text,
            "max_vm_rear_mpa",
        )
        * 1.0e6
    )
    twist_max_deg = _extract_float(
        r"Max twist angle\s+([+-]?\d+(?:\.\d+)?)\s+deg",
        text,
        "max_twist_deg",
    )

    main_od_mm = np.array([row[0] for row in main_rows], dtype=float)
    main_t_mm = np.array([row[1] for row in main_rows], dtype=float)
    rear_od_mm = np.array([row[0] for row in rear_rows], dtype=float)
    rear_t_mm = np.array([row[1] for row in rear_rows], dtype=float)

    return OptimizationResult(
        success=True,
        message=f"reconstructed from {report_path.name}",
        spar_mass_half_kg=0.5 * spar_mass_full_kg,
        spar_mass_full_kg=spar_mass_full_kg,
        total_mass_full_kg=total_mass_full_kg,
        max_stress_main_Pa=max_stress_main_pa,
        max_stress_rear_Pa=max_stress_rear_pa,
        allowable_stress_main_Pa=max_stress_main_pa,
        allowable_stress_rear_Pa=max_stress_rear_pa,
        failure_index=0.0,
        buckling_index=0.0,
        tip_deflection_m=tip_deflection_m,
        max_tip_deflection_m=max_tip_deflection_m,
        twist_max_deg=twist_max_deg,
        main_t_seg_mm=main_t_mm,
        main_r_seg_mm=0.5 * main_od_mm,
        rear_t_seg_mm=rear_t_mm,
        rear_r_seg_mm=0.5 * rear_od_mm,
        disp=None,
        vonmises_main=None,
        vonmises_rear=None,
    )


def _snapshot(label: str, result) -> ModeSnapshot:
    link_norms = (
        np.linalg.norm(result.reactions.link_resultants_n, axis=1)
        if result.reactions.link_resultants_n.size
        else np.zeros(0, dtype=float)
    )
    hottest_order = (
        np.argsort(link_norms)[::-1][:3]
        if link_norms.size
        else np.array([], dtype=int)
    )
    hottest_link_nodes = tuple(
        int(result.reactions.link_node_indices[idx]) + 1 for idx in hottest_order
    )
    root_main_fz_n = float(result.report.root_reaction_main_n[2])
    root_rear_fz_n = float(result.report.root_reaction_rear_n[2])
    wire_fz_n = float(result.report.wire_reaction_total_n)
    support_total_fz_n = root_main_fz_n + root_rear_fz_n + wire_fz_n
    return ModeSnapshot(
        label=label,
        mode=result.mode_definition.mode.value,
        link_mode=result.constraint_mode.link_mode.value,
        main_tip_mm=abs(float(result.report.tip_deflection_main_m) * 1000.0),
        rear_tip_mm=abs(float(result.report.tip_deflection_rear_m) * 1000.0),
        max_uz_mm=abs(float(result.report.max_vertical_displacement_m) * 1000.0),
        max_uz_location=f"{result.report.max_vertical_spar} node {result.report.max_vertical_node}",
        spar_mass_full_kg=float(result.recovery.spar_tube_mass_full_kg),
        root_main_fz_n=root_main_fz_n,
        root_rear_fz_n=root_rear_fz_n,
        wire_fz_n=wire_fz_n,
        support_total_abs_fz_n=abs(support_total_fz_n),
        link_force_max_n=float(result.report.link_force_max_n),
        reaction_balance_residual_n=abs(support_total_fz_n + float(result.load_split.total_applied_fz_n)),
        hottest_link_nodes=hottest_link_nodes,
    )


def run_production_kernel_bundle(*, cfg, aircraft, opt_result, export_loads, materials_db) -> dict[str, object]:
    parity = run_dual_beam_mainline_analysis(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=opt_result,
        export_loads=export_loads,
        materials_db=materials_db,
        mode=AnalysisModeName.DUAL_SPAR_ANSYS_PARITY,
    )
    production = run_dual_beam_mainline_analysis(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=opt_result,
        export_loads=export_loads,
        materials_db=materials_db,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
    )
    production_parity_links = run_dual_beam_mainline_analysis(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=opt_result,
        export_loads=export_loads,
        materials_db=materials_db,
        mode=AnalysisModeName.DUAL_BEAM_ROBUSTNESS,
        link_mode=LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY,
    )
    return {
        "parity": parity,
        "production": production,
        "production_parity_links": production_parity_links,
    }


def build_production_crossval_report(
    *,
    config_path: Path,
    cruise_aoa_deg: float,
    export_loads: dict,
    opt_result: OptimizationResult,
    production_result,
) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    load_split = production_result.load_split
    report = production_result.report
    recovery = production_result.recovery
    lift_per_span = np.asarray(export_loads["lift_per_span"], dtype=float)
    torque_per_span = np.asarray(export_loads["torque_per_span"], dtype=float)
    nodes_per_spar = int(load_split.main_loads_n.shape[0])

    main_root_fz = float(report.root_reaction_main_n[2])
    rear_root_fz = float(report.root_reaction_rear_n[2])
    wire_fz = float(report.wire_reaction_total_n)
    support_total_abs_fz = abs(main_root_fz + rear_root_fz + wire_fz)

    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("  HPA-MDO Dual-Beam Production ANSYS Cross-Check Report")
    lines.append(f"  Generated: {timestamp}")
    lines.append(f"  Config: {config_path.name}")
    lines.append("  Export mode: dual_beam_production")
    lines.append("=" * 64)
    lines.append("")
    lines.append("--- VALIDATION MODE ---")
    lines.append("  dual-beam production analysis mode")
    lines.append("  Phase I gate: NO")
    lines.append(
        "  This export uses the new physics-first dual_beam_production load ownership, "
        "root/wire BCs, and joint_only_offset_rigid link topology."
    )
    lines.append("")
    lines.append("--- DESIGN ---")
    lines.append("  Main spar:")
    for idx, (radius_mm, thickness_mm) in enumerate(
        zip(opt_result.main_r_seg_mm, opt_result.main_t_seg_mm, strict=True),
        start=1,
    ):
        lines.append(f"    Seg {idx}: OD={2.0 * radius_mm:.2f}mm, t={thickness_mm:.2f}mm")
    lines.append("  Rear spar:")
    for idx, (radius_mm, thickness_mm) in enumerate(
        zip(opt_result.rear_r_seg_mm, opt_result.rear_t_seg_mm, strict=True),
        start=1,
    ):
        lines.append(f"    Seg {idx}: OD={2.0 * radius_mm:.2f}mm, t={thickness_mm:.2f}mm")
    lines.append("")
    lines.append("--- APPLIED LOADS / OWNERSHIP ---")
    lines.append(f"  Cruise AoA: {cruise_aoa_deg:.3f} deg")
    lines.append(f"  Total half-span lift: {float(export_loads['total_lift']):.3f} N")
    lines.append(
        f"  Max lift per span: {float(np.max(lift_per_span)):.3f} N/m"
    )
    lines.append(
        f"  Max torque per span: {float(np.max(np.abs(torque_per_span))):.3f} N*m/m"
    )
    lines.append(
        f"  Total applied Fz after production load split: {float(load_split.total_applied_fz_n):.3f} N"
    )
    lines.append("  Load ownership:")
    lines.append("    - lift -> main beam line")
    lines.append("    - aerodynamic torque -> main/rear vertical couple about main spar")
    lines.append("    - main tube self-weight -> main beam line")
    lines.append("    - rear tube self-weight -> rear beam line")
    lines.append("    - equivalent rear-gravity torque -> disabled in this mode")
    lines.append("")
    lines.append("--- EXPECTED RESULTS (Internal Mainline) ---")
    lines.append("  Metric                         Value          ANSYS Target / Role")
    lines.append("  -----------------------------  -------------  -----------------------------")
    lines.append(
        f"  Main tip deflection (uz, y=tip) {abs(report.tip_deflection_main_m) * 1000.0:11.3f} mm   "
        "inspection / compare directly"
    )
    lines.append(
        f"  Rear tip deflection (uz, y=tip) {abs(report.tip_deflection_rear_m) * 1000.0:11.3f} mm   "
        "inspection / compare directly"
    )
    lines.append(
        f"  Max uz anywhere                {abs(report.max_vertical_displacement_m) * 1000.0:11.3f} mm   "
        "inspection / compare directly"
    )
    lines.append(
        f"  Root main reaction Fz          {main_root_fz:11.3f} N    inspection / signed partition"
    )
    lines.append(
        f"  Root rear reaction Fz          {rear_root_fz:11.3f} N    inspection / signed partition"
    )
    lines.append(
        f"  Wire reaction Fz total         {wire_fz:11.3f} N    inspection / signed partition"
    )
    lines.append(
        f"  Support reaction Fz all supports {support_total_abs_fz:9.3f} N    compare abs(total constrained)"
    )
    lines.append(
        f"  Max link resultant             {float(report.link_force_max_n):11.3f} N    informative / non-gating"
    )
    lines.append(
        f"  Max twist angle                {0.0:11.3f} deg  informative / non-gating"
    )
    lines.append(
        f"  Spar tube mass (half-span)     {float(recovery.spar_tube_mass_half_kg):11.3f} kg   "
        "(compare with APDL element mass)"
    )
    lines.append(
        f"  Spar tube mass (full-span)     {float(recovery.spar_tube_mass_full_kg):11.3f} kg   "
        "inspection / compare directly"
    )
    lines.append(
        f"  Total optimized mass (full)    {float(recovery.total_structural_mass_full_kg):11.3f} kg   "
        "(includes tube + joint + fitting report terms)"
    )
    lines.append("")
    lines.append("--- APDL POST-PROCESSING COMMANDS ---")
    lines.append("  /POST1")
    lines.append("  SET,LAST")
    lines.append(f"  *GET,TIP_UZ,NODE,{nodes_per_spar},U,Z")
    lines.append(f"  *GET,TIP_REAR_UZ,NODE,{2 * nodes_per_spar},U,Z")
    lines.append("  PRRSOL,FZ")
    lines.append("=" * 64)
    return "\n".join(lines) + "\n"


def build_robustness_report(*, snapshots: list[ModeSnapshot]) -> str:
    base = snapshots[0]
    lines = []
    lines.append("=" * 96)
    lines.append("Dual-Beam Production Robustness Summary")
    lines.append("=" * 96)
    lines.append(
        f"{'Case':28} {'Main tip':>10} {'Rear tip':>10} {'Max|UZ|':>10} "
        f"{'Tube kg':>9} {'Root M':>10} {'Root R':>10} {'Wire':>10} {'Link max':>10}"
    )
    lines.append("-" * 96)
    for snap in snapshots:
        lines.append(
            f"{snap.label:28} "
            f"{snap.main_tip_mm:10.3f} "
            f"{snap.rear_tip_mm:10.3f} "
            f"{snap.max_uz_mm:10.3f} "
            f"{snap.spar_mass_full_kg:9.3f} "
            f"{snap.root_main_fz_n:10.3f} "
            f"{snap.root_rear_fz_n:10.3f} "
            f"{snap.wire_fz_n:10.3f} "
            f"{snap.link_force_max_n:10.3f}"
        )
        lines.append(
            f"  link mode={snap.link_mode}, max|UZ| location={snap.max_uz_location}, "
            f"reaction residual={snap.reaction_balance_residual_n:.3e} N, "
            f"hottest link nodes={snap.hottest_link_nodes or ()}"
        )

    lines.append("-" * 96)
    for snap in snapshots[1:]:
        lines.append(
            f"Delta vs {base.label} -> {snap.label}: "
            f"main tip {snap.main_tip_mm - base.main_tip_mm:+.3f} mm, "
            f"rear tip {snap.rear_tip_mm - base.rear_tip_mm:+.3f} mm, "
            f"max|UZ| {snap.max_uz_mm - base.max_uz_mm:+.3f} mm, "
            f"wire {snap.wire_fz_n - base.wire_fz_n:+.3f} N, "
            f"link max {snap.link_force_max_n - base.link_force_max_n:+.3f} N"
        )
    return "\n".join(lines) + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export and compare ANSYS checks for the dual-beam production mainline."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser(
        "export",
        help="Rebuild the specimen from a saved design report, run the new kernel, and export an ANSYS package.",
    )
    export_parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
        help="Path to YAML configuration file.",
    )
    export_parser.add_argument(
        "--design-report",
        default=str(Path(__file__).resolve().parent.parent / "output" / "blackcat_004" / "ansys" / "crossval_report.txt"),
        help="Existing crossval_report.txt used only to reconstruct the baseline segment design.",
    )
    export_parser.add_argument(
        "--output-dir",
        default="output/blackcat_004_dual_beam_production_check",
        help="Output root; ANSYS files are written under <output-dir>/ansys.",
    )
    export_parser.set_defaults(func=export_production_package)

    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare manually-run ANSYS production results against the generated production baseline report.",
    )
    compare_parser.add_argument("--ansys-dir", required=True)
    compare_parser.add_argument("--baseline-report", required=True)
    compare_parser.add_argument("--rst", default="file.rst")
    compare_parser.add_argument("--output", default=None)
    compare_parser.set_defaults(func=compare_production_results)
    return parser


def export_production_package(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    design_report = Path(args.design_report).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    ansys_dir = output_dir / "ansys"
    ansys_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(config_path)
    specimen_baseline = parse_baseline_metrics(design_report)
    cfg.solver.n_beam_nodes = int(specimen_baseline.nodes_per_spar)
    aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    opt_result = build_specimen_result_from_crossval_report(design_report)

    cruise_aoa_deg, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)

    analyses = run_production_kernel_bundle(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=opt_result,
        export_loads=export_loads,
        materials_db=mat_db,
    )
    parity = analyses["parity"]
    production = analyses["production"]
    production_parity_links = analyses["production_parity_links"]

    exporter = ANSYSExporter(
        cfg,
        aircraft,
        opt_result,
        export_loads,
        mat_db,
        mode="dual_beam_production",
    )
    apdl_path = exporter.write_apdl(ansys_dir / "spar_model.mac")
    bdf_path = exporter.write_nastran_bdf(ansys_dir / "spar_model.bdf")
    csv_path = exporter.write_workbench_csv(ansys_dir / "spar_data.csv")

    crossval_report = build_production_crossval_report(
        config_path=config_path,
        cruise_aoa_deg=cruise_aoa_deg,
        export_loads=export_loads,
        opt_result=opt_result,
        production_result=production,
    )
    crossval_report_path = ansys_dir / "crossval_report.txt"
    crossval_report_path.write_text(crossval_report, encoding="utf-8")

    robustness_report = build_robustness_report(
        snapshots=[
            _snapshot("parity", parity),
            _snapshot("production_default", production),
            _snapshot("production_parity_links", production_parity_links),
        ]
    )
    robustness_path = output_dir / "robustness_report.txt"
    robustness_path.write_text(robustness_report, encoding="utf-8")

    print("Dual-beam production ANSYS package generated.")
    print(f"  Config             : {config_path}")
    print(f"  Design report      : {design_report}")
    print(f"  Cruise AoA         : {cruise_aoa_deg:.3f} deg")
    print(f"  Output dir         : {output_dir}")
    print(f"  APDL macro         : {apdl_path.name}")
    print(f"  NASTRAN BDF        : {bdf_path.name}")
    print(f"  Workbench CSV      : {csv_path.name}")
    print(f"  Baseline report    : {crossval_report_path.name}")
    print(f"  Robustness report  : {robustness_path.name}")
    print(
        f"  Production main/rear/max|UZ| : "
        f"{abs(production.report.tip_deflection_main_m) * 1000.0:.3f} / "
        f"{abs(production.report.tip_deflection_rear_m) * 1000.0:.3f} / "
        f"{abs(production.report.max_vertical_displacement_m) * 1000.0:.3f} mm"
    )
    print(
        f"  Production reactions (root main / root rear / wire) : "
        f"{production.report.root_reaction_main_n[2]:.3f} / "
        f"{production.report.root_reaction_rear_n[2]:.3f} / "
        f"{production.report.wire_reaction_total_n:.3f} N"
    )
    return 0


def compare_production_results(args: argparse.Namespace) -> int:
    ansys_dir = Path(args.ansys_dir).expanduser().resolve()
    baseline_report = Path(args.baseline_report).expanduser().resolve()
    rst_path = ansys_dir / args.rst
    mac_path = ansys_dir / "spar_model.mac"

    baseline = parse_baseline_metrics(baseline_report, mac_path=mac_path)
    ansys = extract_ansys_metrics_from_rst(rst_path, baseline, ansys_dir)
    report = build_report_text(
        baseline,
        ansys,
        threshold_pct=5.0,
        ansys_dir=ansys_dir,
        rst_path=rst_path,
    )
    print(report)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
