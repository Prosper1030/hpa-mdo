#!/usr/bin/env python3
"""Run a small target-mass feasibility sweep on the refreshed inverse-design line."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
INVERSE_SCRIPT = SCRIPT_DIR / "direct_dual_beam_inverse_design.py"
FEASIBILITY_GATE_PENALTY_KG = 1000.0
TARGET_VIOLATION_WEIGHT_KG = 1000.0
LEGACY_AERO_SOURCE_MODE = "legacy_refresh"
CANDIDATE_RERUN_AERO_SOURCE_MODE = "candidate_rerun_vspaero"
RIB_ZONEWISE_OFF_MODE = "off"
RIB_ZONEWISE_LIMITED_MODE = "limited_zonewise"
DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG = 0.15
DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE = 2
DEFAULT_RIB_PROFILE_COUNT = 3


@dataclass(frozen=True)
class SweepCaseResult:
    target_mass_kg: float
    feasible: bool
    best_feasible_mass_kg: float | None
    best_near_feasible_mass_kg: float | None
    selected_total_mass_kg: float
    objective_value_kg: float
    mass_margin_kg: float | None
    target_violation_score: float
    candidate_score: float
    target_shape_error_max_m: float | None
    ground_clearance_min_m: float | None
    max_jig_prebend_m: float | None
    max_jig_curvature_per_m: float | None
    failure_index: float | None
    buckling_index: float | None
    forward_mismatch_max_m: float | None
    main_blocker: str
    reject_reason: str
    nearest_boundary: str
    summary_json_path: str
    report_path: str
    selection_status: str = "unranked"
    winner_evidence: str | None = None
    aero_source_mode: str | None = None
    baseline_load_source: str | None = None
    refresh_load_source: str | None = None
    load_ownership: str | None = None
    artifact_ownership: str | None = None
    selected_cruise_aoa_deg: float | None = None
    aero_contract_json_path: str | None = None
    rib_design_key: str | None = None
    rib_design_mode: str | None = None
    rib_effective_warping_knockdown: float | None = None
    rib_design_penalty_kg: float | None = None
    rib_unique_family_count: int | None = None
    rib_family_switch_count: int | None = None
    rib_zone_count: int | None = None


def _parse_targets(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Need at least one target mass.")
    return values


def _grid_point_count(text: str) -> int:
    return len(tuple(part.strip() for part in text.split(",") if part.strip()))


def _build_search_budget_summary(args) -> dict[str, object]:
    coarse_axes = {
        "main_plateau_grid_points": _grid_point_count(args.main_plateau_grid),
        "main_taper_fill_grid_points": _grid_point_count(args.main_taper_fill_grid),
        "rear_radius_grid_points": _grid_point_count(args.rear_radius_grid),
        "rear_outboard_grid_points": _grid_point_count(args.rear_outboard_grid),
        "wall_thickness_grid_points": _grid_point_count(args.wall_thickness_grid),
    }
    coarse_grid_points = 1
    for count in coarse_axes.values():
        coarse_grid_points *= max(1, int(count))
    rib_profile_count = (
        1
        if str(args.rib_zonewise_mode) == RIB_ZONEWISE_OFF_MODE
        else DEFAULT_RIB_PROFILE_COUNT
    )
    return {
        "coarse_axes": coarse_axes,
        "coarse_grid_points_per_case": int(coarse_grid_points),
        "coarse_candidate_contracts_per_case": int(coarse_grid_points * rib_profile_count),
        "refresh_steps": int(args.refresh_steps),
        "cobyla_maxiter": int(args.cobyla_maxiter),
        "cobyla_rhobeg": float(args.cobyla_rhobeg),
        "skip_local_refine": bool(args.skip_local_refine),
        "skip_step_export": bool(args.skip_step_export),
        "local_refine_feasible_seeds": int(args.local_refine_feasible_seeds),
        "local_refine_near_feasible_seeds": int(args.local_refine_near_feasible_seeds),
        "local_refine_max_starts": int(args.local_refine_max_starts),
        "local_refine_early_stop_patience": int(args.local_refine_early_stop_patience),
        "local_refine_early_stop_abs_improvement_kg": float(
            args.local_refine_early_stop_abs_improvement_kg
        ),
        "aero_source_mode": str(args.aero_source_mode),
        "rib_zonewise_mode": str(args.rib_zonewise_mode),
        "rib_design_profiles_per_point": int(rib_profile_count),
        "rib_family_switch_penalty_kg": float(args.rib_family_switch_penalty_kg),
        "rib_family_mix_max_unique": int(args.rib_family_mix_max_unique),
    }


def _aero_source_label(source_mode: str | None) -> str:
    if source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE:
        return "candidate rerun-aero"
    if source_mode == LEGACY_AERO_SOURCE_MODE:
        return "legacy refresh"
    if source_mode is None:
        return "unknown"
    return str(source_mode)


def _extract_aero_contract_snapshot(summary: dict[str, object]) -> dict[str, object]:
    contract = summary.get("aero_contract")
    artifacts = summary.get("artifacts")
    if not isinstance(contract, dict):
        return {
            "aero_source_mode": None,
            "baseline_load_source": None,
            "refresh_load_source": None,
            "load_ownership": None,
            "artifact_ownership": None,
            "selected_cruise_aoa_deg": None,
            "aero_contract_json_path": None,
        }
    return {
        "aero_source_mode": (
            None if contract.get("source_mode") is None else str(contract["source_mode"])
        ),
        "baseline_load_source": (
            None
            if contract.get("baseline_load_source") is None
            else str(contract["baseline_load_source"])
        ),
        "refresh_load_source": (
            None
            if contract.get("refresh_load_source") is None
            else str(contract["refresh_load_source"])
        ),
        "load_ownership": (
            None if contract.get("load_ownership") is None else str(contract["load_ownership"])
        ),
        "artifact_ownership": (
            None
            if contract.get("artifact_ownership") is None
            else str(contract["artifact_ownership"])
        ),
        "selected_cruise_aoa_deg": (
            None
            if contract.get("selected_cruise_aoa_deg") is None
            else float(contract["selected_cruise_aoa_deg"])
        ),
        "aero_contract_json_path": (
            None
            if not isinstance(artifacts, dict) or artifacts.get("aero_contract_json") is None
            else str(artifacts["aero_contract_json"])
        ),
    }


def _extract_rib_design_snapshot(selected: dict[str, object]) -> dict[str, object]:
    rib_design = selected.get("rib_design")
    if not isinstance(rib_design, dict):
        return {
            "rib_design_key": None,
            "rib_design_mode": None,
            "rib_effective_warping_knockdown": None,
            "rib_design_penalty_kg": None,
            "rib_unique_family_count": None,
            "rib_family_switch_count": None,
            "rib_zone_count": None,
        }
    return {
        "rib_design_key": None if rib_design.get("design_key") is None else str(rib_design["design_key"]),
        "rib_design_mode": (
            None if rib_design.get("design_mode") is None else str(rib_design["design_mode"])
        ),
        "rib_effective_warping_knockdown": (
            None
            if rib_design.get("effective_warping_knockdown") is None
            else float(rib_design["effective_warping_knockdown"])
        ),
        "rib_design_penalty_kg": (
            None
            if rib_design.get("objective_penalty_kg") is None
            else float(rib_design["objective_penalty_kg"])
        ),
        "rib_unique_family_count": (
            None
            if rib_design.get("unique_family_count") is None
            else int(rib_design["unique_family_count"])
        ),
        "rib_family_switch_count": (
            None
            if rib_design.get("family_switch_count") is None
            else int(rib_design["family_switch_count"])
        ),
        "rib_zone_count": (
            None if rib_design.get("zone_count") is None else int(rib_design["zone_count"])
        ),
    }


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


def _build_winner_evidence(case: SweepCaseResult, *, feasible_pool_exists: bool) -> str:
    mismatch_mm = (
        "n/a"
        if case.target_shape_error_max_m is None
        else f"{case.target_shape_error_max_m * 1000.0:.3f} mm"
    )
    clearance_mm = f"{case.ground_clearance_min_m * 1000.0:.3f} mm"
    prefix = (
        "lowest feasible contract score"
        if feasible_pool_exists
        else "no fully feasible case; lowest penalized contract score"
    )
    return (
        f"{prefix}; score={case.candidate_score:.3f}, "
        f"mass={case.selected_total_mass_kg:.3f} kg, "
        f"mismatch={mismatch_mm}, clearance={clearance_mm}, "
        f"aero source={_aero_source_label(case.aero_source_mode)}, "
        f"rib design={case.rib_design_key or 'n/a'}"
    )


def _annotate_case_selection(cases: list[SweepCaseResult]) -> tuple[list[SweepCaseResult], dict[str, object] | None]:
    if not cases:
        return [], None

    feasible_cases = [case for case in cases if case.feasible]
    winner_pool = feasible_cases if feasible_cases else cases
    winner = min(
        winner_pool,
        key=lambda case: (
            float(case.candidate_score),
            float(case.selected_total_mass_kg),
            float(case.target_shape_error_max_m if case.target_shape_error_max_m is not None else float("inf")),
            -float(case.ground_clearance_min_m),
        ),
    )

    annotated: list[SweepCaseResult] = []
    for case in cases:
        if case == winner:
            selection_status = "winner" if feasible_cases else "nearest_candidate"
            winner_evidence = _build_winner_evidence(case, feasible_pool_exists=bool(feasible_cases))
        elif case.feasible:
            selection_status = "feasible_runner_up"
            winner_evidence = None
        else:
            selection_status = "rejected"
            winner_evidence = None
        annotated.append(
            replace(
                case,
                selection_status=selection_status,
                winner_evidence=winner_evidence,
            )
        )

    winner_summary = {
        "selection_status": "winner" if feasible_cases else "nearest_candidate",
        "requested_knobs": {
            "target_mass_kg": float(winner.target_mass_kg),
        },
        "candidate_score": float(winner.candidate_score),
        "selected_total_mass_kg": float(winner.selected_total_mass_kg),
        "realizable_mismatch_max_m": (
            None
            if winner.target_shape_error_max_m is None
            else float(winner.target_shape_error_max_m)
        ),
        "jig_ground_clearance_min_m": float(winner.ground_clearance_min_m),
        "reject_reason": winner.reject_reason,
        "summary_json_path": winner.summary_json_path,
        "aero_source_mode": winner.aero_source_mode,
        "baseline_load_source": winner.baseline_load_source,
        "refresh_load_source": winner.refresh_load_source,
        "load_ownership": winner.load_ownership,
        "artifact_ownership": winner.artifact_ownership,
        "selected_cruise_aoa_deg": winner.selected_cruise_aoa_deg,
        "aero_contract_json_path": winner.aero_contract_json_path,
        "rib_design": (
            None
            if winner.rib_design_key is None
            else {
                "design_key": winner.rib_design_key,
                "design_mode": winner.rib_design_mode,
                "effective_warping_knockdown": winner.rib_effective_warping_knockdown,
                "objective_penalty_kg": winner.rib_design_penalty_kg,
                "unique_family_count": winner.rib_unique_family_count,
                "family_switch_count": winner.rib_family_switch_count,
                "zone_count": winner.rib_zone_count,
            }
        ),
        "winner_evidence": next(
            item.winner_evidence for item in annotated if item.target_mass_kg == winner.target_mass_kg
        ),
    }
    return annotated, winner_summary


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
        "--aero-source-mode",
        str(args.aero_source_mode),
        "--rib-zonewise-mode",
        str(args.rib_zonewise_mode),
        "--rib-family-switch-penalty-kg",
        str(args.rib_family_switch_penalty_kg),
        "--rib-family-mix-max-unique",
        str(args.rib_family_mix_max_unique),
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
    selected_total_mass_kg = float(selected["total_structural_mass_kg"])
    objective_value_kg = float(selected["objective_value_kg"])
    target_violation_score = float(selected.get("target_violation_score", 0.0))
    candidate_score = float(
        objective_value_kg
        + TARGET_VIOLATION_WEIGHT_KG * target_violation_score
        + (0.0 if feasible else FEASIBILITY_GATE_PENALTY_KG)
    )
    mass_margin_kg = (
        None
        if selected.get("mass_margin_kg") is None
        else float(selected["mass_margin_kg"])
    )
    aero_snapshot = _extract_aero_contract_snapshot(summary)
    rib_snapshot = _extract_rib_design_snapshot(selected)

    return SweepCaseResult(
        target_mass_kg=float(target_mass_kg),
        feasible=feasible,
        best_feasible_mass_kg=(
            None if best_target is None else float(best_target["total_structural_mass_kg"])
        ),
        best_near_feasible_mass_kg=(
            None
            if feasible
            else selected_total_mass_kg
        ),
        selected_total_mass_kg=selected_total_mass_kg,
        objective_value_kg=objective_value_kg,
        mass_margin_kg=mass_margin_kg,
        target_violation_score=target_violation_score,
        candidate_score=candidate_score,
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
        reject_reason="none" if feasible else blocker,
        nearest_boundary=nearest,
        summary_json_path=str(summary_path.resolve()),
        report_path=str(report_path.resolve()),
        **aero_snapshot,
        **rib_snapshot,
    )


def _build_report_text(
    *,
    output_dir: Path,
    cases: list[SweepCaseResult],
    search_budget: dict[str, object],
    winner_summary: dict[str, object] | None,
) -> str:
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "=" * 108,
        "Refreshed Inverse-Design Feasibility Sweep",
        "=" * 108,
        f"Generated                     : {generated}",
        f"Output dir                    : {output_dir}",
        "",
        "Score contract:",
        "  score name                  : target_mass_candidate_score",
        "  direction                   : lower_is_better",
        "  formula                     : objective_value_kg + 1000*target_violation_score + gate penalty",
        f"  rejected gate penalty       : {FEASIBILITY_GATE_PENALTY_KG:.1f} kg",
        f"  target-violation weight     : {TARGET_VIOLATION_WEIGHT_KG:.1f} kg",
        "",
        "Search budget:",
        (
            "  coarse grid points / case   : "
            f"{int(search_budget['coarse_grid_points_per_case'])}"
        ),
        (
            "  rib-aware contracts / case  : "
            f"{int(search_budget['coarse_candidate_contracts_per_case'])}"
        ),
        (
            "  coarse axes                 : "
            f"plateau={search_budget['coarse_axes']['main_plateau_grid_points']}, "
            f"taper={search_budget['coarse_axes']['main_taper_fill_grid_points']}, "
            f"rear_radius={search_budget['coarse_axes']['rear_radius_grid_points']}, "
            f"rear_outboard={search_budget['coarse_axes']['rear_outboard_grid_points']}, "
            f"wall={search_budget['coarse_axes']['wall_thickness_grid_points']}"
        ),
        (
            "  rib contract mode           : "
            f"{search_budget['rib_zonewise_mode']} "
            f"(profiles={search_budget['rib_design_profiles_per_point']}, "
            f"mix_max={search_budget['rib_family_mix_max_unique']}, "
            f"switch_penalty={search_budget['rib_family_switch_penalty_kg']:.3f} kg)"
        ),
        f"  refresh steps               : {search_budget['refresh_steps']}",
        f"  COBYLA maxiter / rhobeg     : {search_budget['cobyla_maxiter']} / {search_budget['cobyla_rhobeg']:.3f}",
        (
            "  local refine                : "
            + (
                "skipped"
                if search_budget["skip_local_refine"]
                else (
                    f"feasible={search_budget['local_refine_feasible_seeds']}, "
                    f"near={search_budget['local_refine_near_feasible_seeds']}, "
                    f"max_starts={search_budget['local_refine_max_starts']}, "
                    f"patience={search_budget['local_refine_early_stop_patience']}, "
                    f"abs_improve={search_budget['local_refine_early_stop_abs_improvement_kg']:.3f} kg"
                )
            )
        ),
        (
            "  aero source mode            : "
            f"{search_budget['aero_source_mode']} ({_aero_source_label(search_budget['aero_source_mode'])})"
        ),
        "",
        "Target Mass Sweep:",
    ]
    for case in cases:
        lines.append(f"  {case.target_mass_kg:5.1f} kg")
    lines.append("")
    if winner_summary is not None:
        lines.append("Selection summary:")
        lines.append(f"  status                       : {winner_summary['selection_status']}")
        lines.append(
            "  requested knobs              : "
            f"target_mass_kg={winner_summary['requested_knobs']['target_mass_kg']:.3f}"
        )
        lines.append(f"  candidate score              : {winner_summary['candidate_score']:.3f}")
        lines.append(
            f"  selected total mass          : {winner_summary['selected_total_mass_kg']:.3f} kg"
        )
        mismatch_m = winner_summary["realizable_mismatch_max_m"]
        lines.append(
            "  realizable mismatch max      : "
            + ("n/a" if mismatch_m is None else f"{float(mismatch_m) * 1000.0:.3f} mm")
        )
        lines.append(
            "  jig ground clearance min     : "
            f"{float(winner_summary['jig_ground_clearance_min_m']) * 1000.0:.3f} mm"
        )
        lines.append(
            "  aero source mode            : "
            + (
                "unknown"
                if winner_summary["aero_source_mode"] is None
                else f"{winner_summary['aero_source_mode']} ({_aero_source_label(winner_summary['aero_source_mode'])})"
            )
        )
        if winner_summary["refresh_load_source"] is not None:
            lines.append(f"  refresh load source         : {winner_summary['refresh_load_source']}")
        if winner_summary["load_ownership"] is not None:
            lines.append(f"  load ownership              : {winner_summary['load_ownership']}")
        lines.append(f"  reject reason                : {winner_summary['reject_reason']}")
        if winner_summary["aero_contract_json_path"] is not None:
            lines.append(
                f"  aero contract JSON          : {winner_summary['aero_contract_json_path']}"
            )
        if winner_summary["rib_design"] is not None:
            rib_design = winner_summary["rib_design"]
            lines.append(f"  rib design                  : {rib_design['design_key']}")
            lines.append(f"  rib mode                    : {rib_design['design_mode']}")
            lines.append(
                f"  rib effective knockdown     : {float(rib_design['effective_warping_knockdown']):.6f}"
            )
            lines.append(
                f"  rib design penalty          : {float(rib_design['objective_penalty_kg']):.3f} kg"
            )
        lines.append(f"  winner evidence              : {winner_summary['winner_evidence']}")
        lines.append("")
    lines.append(
        "target kg | feasible | score | aero source | selected mass kg | mismatch mm | clearance mm | reject reason | selection"
    )
    for case in cases:
        lines.append(
            f"{case.target_mass_kg:9.1f} | "
            f"{str(case.feasible):8s} | "
            f"{case.candidate_score:5.1f} | "
            f"{_aero_source_label(case.aero_source_mode):17s} | "
            f"{case.selected_total_mass_kg:16.3f} | "
            f"{case.target_shape_error_max_m * 1000.0:11.3f} | "
            f"{case.ground_clearance_min_m * 1000.0:11.3f} | "
            f"{case.reject_reason:13s} | "
            f"{case.selection_status}"
        )
    lines.append("")
    for case in cases:
        lines.append(f"Target {case.target_mass_kg:.1f} kg:")
        lines.append(f"  feasible                     : {case.feasible}")
        lines.append(f"  candidate score              : {case.candidate_score:.3f}")
        lines.append(f"  selection status             : {case.selection_status}")
        lines.append(
            "  best feasible mass           : "
            + (f"{case.best_feasible_mass_kg:.3f} kg" if case.best_feasible_mass_kg is not None else "none found")
        )
        lines.append(
            "  best near-feasible mass      : "
            + (f"{case.best_near_feasible_mass_kg:.3f} kg" if case.best_near_feasible_mass_kg is not None else "n/a")
        )
        lines.append(f"  selected total mass          : {case.selected_total_mass_kg:.3f} kg")
        lines.append(f"  objective value              : {case.objective_value_kg:.3f} kg")
        lines.append(f"  target violation score       : {case.target_violation_score:.6f}")
        lines.append(
            "  mass margin                  : "
            + ("n/a" if case.mass_margin_kg is None else f"{case.mass_margin_kg:+.3f} kg")
        )
        lines.append(
            "  aero source mode            : "
            + (
                "unknown"
                if case.aero_source_mode is None
                else f"{case.aero_source_mode} ({_aero_source_label(case.aero_source_mode)})"
            )
        )
        if case.baseline_load_source is not None:
            lines.append(f"  baseline load source         : {case.baseline_load_source}")
        if case.refresh_load_source is not None:
            lines.append(f"  refresh load source          : {case.refresh_load_source}")
        if case.load_ownership is not None:
            lines.append(f"  load ownership               : {case.load_ownership}")
        if case.artifact_ownership is not None:
            lines.append(f"  artifact ownership           : {case.artifact_ownership}")
        if case.selected_cruise_aoa_deg is not None:
            lines.append(f"  selected cruise AoA          : {case.selected_cruise_aoa_deg:.3f} deg")
        lines.append(f"  main blocker                 : {case.main_blocker}")
        lines.append(f"  reject reason                : {case.reject_reason}")
        lines.append(f"  nearest boundary             : {case.nearest_boundary}")
        if case.winner_evidence is not None:
            lines.append(f"  winner evidence              : {case.winner_evidence}")
        if case.rib_design_key is not None:
            lines.append(f"  rib design                   : {case.rib_design_key}")
            lines.append(
                "  rib contract                 : "
                f"mode={case.rib_design_mode}, "
                f"knockdown={float(case.rib_effective_warping_knockdown):.6f}, "
                f"penalty={float(case.rib_design_penalty_kg):.3f} kg, "
                f"families={int(case.rib_unique_family_count)}, "
                f"switches={int(case.rib_family_switch_count)}"
            )
        if case.aero_contract_json_path is not None:
            lines.append(f"  aero contract JSON           : {case.aero_contract_json_path}")
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
    parser.add_argument(
        "--aero-source-mode",
        default=CANDIDATE_RERUN_AERO_SOURCE_MODE,
        choices=(LEGACY_AERO_SOURCE_MODE, CANDIDATE_RERUN_AERO_SOURCE_MODE),
        help=(
            "Choose whether each target-mass case reuses the legacy shared refresh loads "
            "or consumes candidate-owned rerun-aero artifacts from the inverse-design core."
        ),
    )
    parser.add_argument("--refresh-steps", type=int, default=2)
    parser.add_argument("--main-plateau-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--main-taper-fill-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--rear-radius-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--rear-outboard-grid", default="0.0,0.5,1.0")
    parser.add_argument("--wall-thickness-grid", default="0.0,0.35,0.70")
    parser.add_argument("--cobyla-maxiter", type=int, default=160)
    parser.add_argument("--cobyla-rhobeg", type=float, default=0.18)
    parser.add_argument("--skip-local-refine", action="store_true")
    parser.add_argument("--skip-step-export", action="store_true")
    parser.add_argument("--local-refine-feasible-seeds", type=int, default=1)
    parser.add_argument("--local-refine-near-feasible-seeds", type=int, default=2)
    parser.add_argument("--local-refine-max-starts", type=int, default=4)
    parser.add_argument("--local-refine-early-stop-patience", type=int, default=2)
    parser.add_argument("--local-refine-early-stop-abs-improvement-kg", type=float, default=0.05)
    parser.add_argument(
        "--rib-zonewise-mode",
        default=RIB_ZONEWISE_LIMITED_MODE,
        choices=(RIB_ZONEWISE_OFF_MODE, RIB_ZONEWISE_LIMITED_MODE),
    )
    parser.add_argument(
        "--rib-family-switch-penalty-kg",
        type=float,
        default=DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG,
    )
    parser.add_argument(
        "--rib-family-mix-max-unique",
        type=int,
        default=DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE,
    )
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

    search_budget = _build_search_budget_summary(args)
    cases, winner_summary = _annotate_case_selection(cases)

    report_path = output_dir / "direct_dual_beam_inverse_design_feasibility_sweep_report.txt"
    json_path = output_dir / "direct_dual_beam_inverse_design_feasibility_sweep_summary.json"
    report_path.write_text(
        _build_report_text(
            output_dir=output_dir,
            cases=cases,
            search_budget=search_budget,
            winner_summary=winner_summary,
        ),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().astimezone().isoformat(),
                "output_dir": str(output_dir),
                "score_contract": {
                    "score_name": "target_mass_candidate_score",
                    "direction": "lower_is_better",
                    "formula": "objective_value_kg + 1000*target_violation_score + gate penalty",
                    "rejected_gate_penalty_kg": FEASIBILITY_GATE_PENALTY_KG,
                    "target_violation_weight_kg": TARGET_VIOLATION_WEIGHT_KG,
                },
                "search_budget": search_budget,
                "winner": winner_summary,
                "cases": [asdict(case) for case in cases],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Refreshed inverse-design feasibility sweep complete.")
    print(f"  Output dir          : {output_dir}")
    print(
        "  Aero source mode    : "
        f"{args.aero_source_mode} ({_aero_source_label(args.aero_source_mode)})"
    )
    print(
        "  Rib contract mode   : "
        f"{args.rib_zonewise_mode} (profiles={search_budget['rib_design_profiles_per_point']})"
    )
    print(f"  Report              : {report_path}")
    print(f"  Summary JSON        : {json_path}")
    if winner_summary is not None:
        print(
            "  Winner              : "
            f"{winner_summary['selection_status']} at target "
            f"{winner_summary['requested_knobs']['target_mass_kg']:.1f} kg "
            f"(score={winner_summary['candidate_score']:.3f})"
        )
    for case in cases:
        print(
            f"  {case.target_mass_kg:5.1f} kg           : feasible={case.feasible}  "
            f"aero={_aero_source_label(case.aero_source_mode)}  "
            f"score={case.candidate_score:.3f}  "
            f"status={case.selection_status}  "
            f"reject={case.reject_reason}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
