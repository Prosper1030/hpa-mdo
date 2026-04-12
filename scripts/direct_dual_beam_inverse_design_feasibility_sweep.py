#!/usr/bin/env python3
"""Run a small target-mass feasibility sweep on the refreshed inverse-design line."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
INVERSE_SCRIPT = SCRIPT_DIR / "direct_dual_beam_inverse_design.py"


@dataclass(frozen=True)
class SweepCaseResult:
    target_mass_kg: float
    feasible: bool
    best_feasible_mass_kg: float | None
    best_near_feasible_mass_kg: float | None
    target_shape_error_max_m: float | None
    ground_clearance_min_m: float | None
    max_jig_prebend_m: float | None
    max_jig_curvature_per_m: float | None
    failure_index: float | None
    buckling_index: float | None
    forward_mismatch_max_m: float | None
    main_blocker: str
    nearest_boundary: str
    summary_json_path: str
    report_path: str


def _parse_targets(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Need at least one target mass.")
    return values


def _blocker_category(margin_name: str) -> str:
    if margin_name == "ground_clearance_margin_m":
        return "ground clearance"
    if margin_name in {"loaded_shape_main_z_margin_m", "loaded_shape_twist_margin_deg"}:
        return "loaded-shape closure"
    if margin_name == "equivalent_failure_margin":
        return "failure"
    if margin_name == "equivalent_buckling_margin":
        return "buckling"
    if margin_name in {"jig_prebend_margin_m", "jig_curvature_margin_per_m"}:
        return "manufacturing prebend / curvature"
    return "geometry / discrete boundary"


def _infer_blocker(*, selected: dict, feasible: bool) -> tuple[str, str]:
    hard_margins = selected["hard_margins"]
    tightest_name, tightest_value = min(hard_margins.items(), key=lambda item: float(item[1]))
    nearest_boundary = _blocker_category(str(tightest_name))
    if feasible:
        return "none", nearest_boundary
    if not bool(selected.get("target_mass_passed", True)) and bool(selected.get("overall_feasible", False)):
        return "mass target; nearest wall is " + nearest_boundary, nearest_boundary
    if float(tightest_value) < 0.0:
        return _blocker_category(str(tightest_name)), nearest_boundary
    if not bool(selected.get("target_mass_passed", True)):
        return "mass target; nearest wall is " + nearest_boundary, nearest_boundary
    return nearest_boundary, nearest_boundary


def _run_one_case(args, *, target_mass_kg: float, case_dir: Path) -> SweepCaseResult:
    case_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(INVERSE_SCRIPT),
        "--config",
        str(Path(args.config).expanduser().resolve()),
        "--design-report",
        str(Path(args.design_report).expanduser().resolve()),
        "--output-dir",
        str(case_dir),
        "--refresh-steps",
        str(args.refresh_steps),
        "--main-plateau-grid",
        args.main_plateau_grid,
        "--main-taper-fill-grid",
        args.main_taper_fill_grid,
        "--rear-radius-grid",
        args.rear_radius_grid,
        "--rear-outboard-grid",
        args.rear_outboard_grid,
        "--wall-thickness-grid",
        args.wall_thickness_grid,
        "--cobyla-maxiter",
        str(args.cobyla_maxiter),
        "--cobyla-rhobeg",
        str(args.cobyla_rhobeg),
        "--local-refine-feasible-seeds",
        str(args.local_refine_feasible_seeds),
        "--local-refine-near-feasible-seeds",
        str(args.local_refine_near_feasible_seeds),
        "--local-refine-max-starts",
        str(args.local_refine_max_starts),
        "--local-refine-early-stop-patience",
        str(args.local_refine_early_stop_patience),
        "--local-refine-early-stop-abs-improvement-kg",
        str(args.local_refine_early_stop_abs_improvement_kg),
        "--target-mass-kg",
        str(target_mass_kg),
    ]
    if args.skip_step_export:
        cmd.append("--skip-step-export")
    if args.skip_local_refine:
        cmd.append("--skip-local-refine")

    subprocess.run(cmd, check=True)

    summary_path = case_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
    report_path = case_dir / "direct_dual_beam_inverse_design_refresh_report.txt"
    summary = json.loads(summary_path.read_text())
    final = summary["iterations"][-1]
    selected = final["selected"]
    best_target = final["search_diagnostics"]["best_target_feasible"]
    best_overall = final["search_diagnostics"]["best_overall_feasible"]
    feasible = bool(final["run_metrics"]["feasible"])
    blocker, nearest = _infer_blocker(selected=selected, feasible=feasible)
    forward = final["forward_check"] or {}

    return SweepCaseResult(
        target_mass_kg=float(target_mass_kg),
        feasible=feasible,
        best_feasible_mass_kg=(
            None if best_target is None else float(best_target["total_structural_mass_kg"])
        ),
        best_near_feasible_mass_kg=(
            None
            if feasible
            else float(selected["total_structural_mass_kg"])
        ),
        target_shape_error_max_m=float(selected["target_shape_error_max_m"]),
        ground_clearance_min_m=float(selected["jig_ground_clearance_min_m"]),
        max_jig_prebend_m=float(selected["max_jig_vertical_prebend_m"]),
        max_jig_curvature_per_m=float(selected["max_jig_vertical_curvature_per_m"]),
        failure_index=float(selected["equivalent_failure_index"]),
        buckling_index=float(selected["equivalent_buckling_index"]),
        forward_mismatch_max_m=(
            None if not forward else float(forward["target_shape_error_max_m"])
        ),
        main_blocker=blocker,
        nearest_boundary=nearest,
        summary_json_path=str(summary_path.resolve()),
        report_path=str(report_path.resolve()),
    )


def _build_report_text(*, output_dir: Path, cases: list[SweepCaseResult]) -> str:
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "=" * 108,
        "Refreshed Inverse-Design Feasibility Sweep",
        "=" * 108,
        f"Generated                     : {generated}",
        f"Output dir                    : {output_dir}",
        "",
        "Target Mass Sweep:",
    ]
    for case in cases:
        lines.append(f"  {case.target_mass_kg:5.1f} kg")
    lines.append("")
    lines.append(
        "target kg | feasible | best feasible kg | best near-feasible kg | clearance mm | prebend mm | curvature 1/m | failure | buckling | forward mismatch mm | blocker"
    )
    for case in cases:
        lines.append(
            f"{case.target_mass_kg:9.1f} | "
            f"{str(case.feasible):8s} | "
            f"{(f'{case.best_feasible_mass_kg:.3f}' if case.best_feasible_mass_kg is not None else 'n/a'):16s} | "
            f"{(f'{case.best_near_feasible_mass_kg:.3f}' if case.best_near_feasible_mass_kg is not None else 'n/a'):20s} | "
            f"{case.ground_clearance_min_m * 1000.0:11.3f} | "
            f"{case.max_jig_prebend_m * 1000.0:10.3f} | "
            f"{case.max_jig_curvature_per_m:13.6f} | "
            f"{case.failure_index:7.4f} | "
            f"{case.buckling_index:8.4f} | "
            f"{((case.forward_mismatch_max_m or 0.0) * 1000.0):19.6f} | "
            f"{case.main_blocker}"
        )
    lines.append("")
    for case in cases:
        lines.append(f"Target {case.target_mass_kg:.1f} kg:")
        lines.append(f"  feasible                     : {case.feasible}")
        lines.append(
            "  best feasible mass           : "
            + (f"{case.best_feasible_mass_kg:.3f} kg" if case.best_feasible_mass_kg is not None else "none found")
        )
        lines.append(
            "  best near-feasible mass      : "
            + (f"{case.best_near_feasible_mass_kg:.3f} kg" if case.best_near_feasible_mass_kg is not None else "n/a")
        )
        lines.append(f"  main blocker                 : {case.main_blocker}")
        lines.append(f"  nearest boundary             : {case.nearest_boundary}")
        lines.append(f"  summary JSON                 : {case.summary_json_path}")
        lines.append(f"  detailed report              : {case.report_path}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a small target-mass feasibility sweep on the refreshed inverse-design line."
    )
    parser.add_argument(
        "--config",
        default=str(SCRIPT_DIR.parent / "configs" / "blackcat_004.yaml"),
    )
    parser.add_argument(
        "--design-report",
        default=str(
            SCRIPT_DIR.parent
            / "output"
            / "blackcat_004_dual_beam_production_check"
            / "ansys"
            / "crossval_report.txt"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(SCRIPT_DIR.parent / "output" / "direct_dual_beam_inverse_design_feasibility_sweep"),
    )
    parser.add_argument("--target-masses-kg", default="22,20,18,16,15")
    parser.add_argument("--refresh-steps", type=int, default=2)
    parser.add_argument("--main-plateau-grid", default="0.0,1.0")
    parser.add_argument("--main-taper-fill-grid", default="0.0,1.0")
    parser.add_argument("--rear-radius-grid", default="0.0,1.0")
    parser.add_argument("--rear-outboard-grid", default="0.0,1.0")
    parser.add_argument("--wall-thickness-grid", default="0.0,1.0")
    parser.add_argument("--cobyla-maxiter", type=int, default=160)
    parser.add_argument("--cobyla-rhobeg", type=float, default=0.18)
    parser.add_argument("--skip-local-refine", action="store_true")
    parser.add_argument("--skip-step-export", action="store_true")
    parser.add_argument("--local-refine-feasible-seeds", type=int, default=1)
    parser.add_argument("--local-refine-near-feasible-seeds", type=int, default=2)
    parser.add_argument("--local-refine-max-starts", type=int, default=4)
    parser.add_argument("--local-refine-early-stop-patience", type=int, default=2)
    parser.add_argument("--local-refine-early-stop-abs-improvement-kg", type=float, default=0.05)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    targets = _parse_targets(args.target_masses_kg)
    cases: list[SweepCaseResult] = []
    for target_mass_kg in targets:
        case_dir = output_dir / f"target_{target_mass_kg:0.1f}kg"
        cases.append(_run_one_case(args, target_mass_kg=target_mass_kg, case_dir=case_dir))

    report_path = output_dir / "direct_dual_beam_inverse_design_feasibility_sweep_report.txt"
    json_path = output_dir / "direct_dual_beam_inverse_design_feasibility_sweep_summary.json"
    report_path.write_text(_build_report_text(output_dir=output_dir, cases=cases), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().astimezone().isoformat(),
                "output_dir": str(output_dir),
                "cases": [asdict(case) for case in cases],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Refreshed inverse-design feasibility sweep complete.")
    print(f"  Output dir          : {output_dir}")
    print(f"  Report              : {report_path}")
    print(f"  Summary JSON        : {json_path}")
    for case in cases:
        print(
            f"  {case.target_mass_kg:5.1f} kg           : feasible={case.feasible}  "
            f"best_feasible={case.best_feasible_mass_kg if case.best_feasible_mass_kg is not None else 'n/a'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
