from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


ReferencePolicyType = Literal[
    "declared_blackcat_full_span",
    "openvsp_geometry_derived",
    "unknown",
]
ReportRoleType = Literal["baseline_smoke", "budget_probe"]
ReportStatusType = Literal[
    "no_solver_smokes",
    "solver_smokes_observed",
    "solver_budget_nonconverged",
    "solver_budget_gate_passed",
]
HPAFlowStatusType = Literal[
    "hpa_standard_6p5_observed",
    "mixed_or_nonstandard_velocity_observed",
    "unavailable",
]
MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 = 1.0


class MainWingSolverBudgetComparisonRow(BaseModel):
    reference_policy: ReferencePolicyType
    report_role: ReportRoleType
    report_path: str
    convergence_gate_path: str | None = None
    runtime_max_iterations: int | None = None
    final_iteration: int | None = None
    solver_execution_status: str
    run_status: str | None = None
    convergence_gate_status: str | None = None
    convergence_comparability_level: str | None = None
    reference_geometry_status: str | None = None
    observed_velocity_mps: float | None = None
    final_coefficients: Dict[str, Any] = Field(default_factory=dict)
    main_wing_lift_acceptance_status: str = "not_evaluated"
    minimum_acceptable_cl: float | None = None
    residual_median_log_drop: float | None = None
    coefficient_stability_status: str | None = None
    coefficient_stability_by_axis: Dict[str, str] = Field(default_factory=dict)
    solver_log_quality_metrics: Dict[str, Any] = Field(default_factory=dict)
    advisory_flags: List[str] = Field(default_factory=list)


class MainWingSolverBudgetComparisonReport(BaseModel):
    schema_version: Literal["main_wing_solver_budget_comparison.v1"] = (
        "main_wing_solver_budget_comparison.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_solver_smokes"] = (
        "report_only_existing_solver_smokes"
    )
    hpa_standard_velocity_mps: float = 6.5
    hpa_standard_flow_status: HPAFlowStatusType
    report_status: ReportStatusType
    current_route_row: Dict[str, Any] = Field(default_factory=dict)
    rows: List[MainWingSolverBudgetComparisonRow]
    engineering_assessment: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _default_report_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "reports"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _iter_from_dir(path: Path) -> int | None:
    suffix = path.parent.name.rsplit("_iter", maxsplit=1)[-1]
    return int(suffix) if suffix.isdigit() else None


def _repo_root_from_report_root(report_root: Path) -> Path | None:
    try:
        return report_root.resolve().parents[2]
    except IndexError:
        return None


def _resolve_path(raw_path: Any, *, report_root: Path, report_path: Path) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path)
    candidates = [path]
    repo_root = _repo_root_from_report_root(report_root)
    if not path.is_absolute() and repo_root is not None:
        candidates.append(repo_root / path)
    if not path.is_absolute():
        candidates.append(report_path.parent / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _discover_report_paths(report_root: Path) -> list[Path]:
    paths = [
        report_root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        report_root
        / "main_wing_openvsp_reference_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
    ]
    paths.extend(
        sorted(
            report_root.glob(
                "main_wing_real_solver_smoke_probe_iter*/"
                "main_wing_real_solver_smoke_probe.v1.json"
            )
        )
    )
    paths.extend(
        sorted(
            report_root.glob(
                "main_wing_openvsp_reference_solver_smoke_probe_iter*/"
                "main_wing_real_solver_smoke_probe.v1.json"
            )
        )
    )
    seen: set[Path] = set()
    discovered: list[Path] = []
    for path in paths:
        if path in seen or not path.exists():
            continue
        discovered.append(path)
        seen.add(path)
    return discovered


def _infer_reference_policy(path: Path, payload: dict[str, Any]) -> ReferencePolicyType:
    joined = " ".join(
        str(payload.get(key, ""))
        for key in ("source_su2_probe_path", "case_dir", "runtime_cfg_path")
    )
    if (
        path.parent.name.startswith("main_wing_openvsp_reference")
        or "openvsp_reference" in joined
    ):
        return "openvsp_geometry_derived"
    if (
        path.parent.name.startswith("main_wing_real_solver")
        or "declared_blackcat" in joined
    ):
        return "declared_blackcat_full_span"
    return "unknown"


def _report_role(path: Path) -> ReportRoleType:
    return "budget_probe" if "_iter" in path.parent.name else "baseline_smoke"


def _residual_median_log_drop(gate: dict[str, Any] | None) -> float | None:
    if not isinstance(gate, dict):
        return None
    checks = (
        gate.get("iterative_gate", {})
        .get("checks", {})
        .get("residual_trend", {})
    )
    observed = checks.get("observed", {}) if isinstance(checks, dict) else {}
    return _as_float(observed.get("median_log_drop"))


def _coefficient_stability(gate: dict[str, Any] | None) -> tuple[str | None, dict[str, str]]:
    if not isinstance(gate, dict):
        return None, {}
    check = (
        gate.get("iterative_gate", {})
        .get("checks", {})
        .get("coefficient_stability", {})
    )
    status = check.get("status") if isinstance(check, dict) else None
    observed = check.get("observed", {}) if isinstance(check, dict) else {}
    by_axis: dict[str, str] = {}
    if isinstance(observed, dict):
        for axis in ("cl", "cd", "cm"):
            axis_payload = observed.get(axis, {})
            axis_status = (
                axis_payload.get("status")
                if isinstance(axis_payload, dict)
                else None
            )
            if isinstance(axis_status, str):
                by_axis[axis] = axis_status
    return status if isinstance(status, str) else None, by_axis


def _quality_metric(payload: dict[str, Any], path: tuple[str, ...]) -> float | None:
    current: Any = payload
    for key in path:
        current = current.get(key) if isinstance(current, dict) else None
    return _as_float(current)


def _main_wing_lift_acceptance_status(payload: dict[str, Any]) -> str:
    reported_status = payload.get("main_wing_lift_acceptance_status")
    if reported_status in {"pass", "fail", "not_evaluated"}:
        return str(reported_status)
    velocity = _as_float(payload.get("observed_velocity_mps"))
    coefficients = payload.get("final_coefficients", {})
    cl = coefficients.get("cl") if isinstance(coefficients, dict) else None
    if velocity is None or abs(velocity - 6.5) > 1.0e-9:
        return "not_evaluated"
    if not isinstance(cl, (int, float)):
        return "not_evaluated"
    return "pass" if float(cl) > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 else "fail"


def _advisory_flags(
    *,
    payload: dict[str, Any],
    gate: dict[str, Any] | None,
    residual_drop: float | None,
    coefficient_status: str | None,
) -> list[str]:
    flags: list[str] = []
    if payload.get("solver_execution_status") != "solver_executed":
        flags.append("solver_not_executed")
    if payload.get("convergence_gate_status") != "pass":
        flags.append("convergence_gate_not_passed")
    if residual_drop is not None and residual_drop < 0.5:
        flags.append("residual_drop_below_threshold")
    if coefficient_status not in {None, "pass"}:
        flags.append("coefficient_tail_not_stable")
    if payload.get("reference_geometry_status") in {"warn", "fail"}:
        flags.append(f"reference_geometry_{payload['reference_geometry_status']}")
    if _main_wing_lift_acceptance_status(payload) == "fail":
        flags.append("main_wing_cl_below_expected_lift")

    quality = payload.get("solver_log_quality_metrics", {})
    if isinstance(quality, dict):
        cv_ratio = _quality_metric(
            quality,
            ("dual_control_volume_quality", "cv_sub_volume_ratio", "max"),
        )
        face_ar = _quality_metric(
            quality,
            ("dual_control_volume_quality", "cv_face_area_aspect_ratio", "max"),
        )
        if cv_ratio is not None and cv_ratio >= 1000.0:
            flags.append("mesh_quality_cv_sub_volume_ratio_high")
        if face_ar is not None and face_ar >= 100.0:
            flags.append("mesh_quality_cv_face_area_aspect_ratio_high")

    if isinstance(gate, dict):
        overall = gate.get("overall_convergence_gate", {})
        warnings = overall.get("warnings", []) if isinstance(overall, dict) else []
        if isinstance(warnings, list):
            flags.extend(
                f"overall_gate_warning:{warning}"
                for warning in warnings
                if isinstance(warning, str)
            )
    return list(dict.fromkeys(flags))


def _row_from_report_path(
    path: Path,
    *,
    report_root: Path,
) -> MainWingSolverBudgetComparisonRow | None:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return None
    gate_path = _resolve_path(
        payload.get("convergence_gate_path"),
        report_root=report_root,
        report_path=path,
    )
    gate = _load_json(gate_path) if gate_path is not None else None
    residual_drop = _residual_median_log_drop(gate)
    coefficient_status, coefficient_by_axis = _coefficient_stability(gate)
    runtime_max_iterations = _as_int(payload.get("runtime_max_iterations"))
    if runtime_max_iterations is None:
        runtime_max_iterations = _iter_from_dir(path)
    lift_acceptance_status = _main_wing_lift_acceptance_status(payload)
    return MainWingSolverBudgetComparisonRow(
        reference_policy=_infer_reference_policy(path, payload),
        report_role=_report_role(path),
        report_path=str(path),
        convergence_gate_path=None if gate_path is None else str(gate_path),
        runtime_max_iterations=runtime_max_iterations,
        final_iteration=_as_int(payload.get("final_iteration")),
        solver_execution_status=str(payload.get("solver_execution_status", "unknown")),
        run_status=payload.get("run_status"),
        convergence_gate_status=payload.get("convergence_gate_status"),
        convergence_comparability_level=payload.get("convergence_comparability_level"),
        reference_geometry_status=payload.get("reference_geometry_status"),
        observed_velocity_mps=_as_float(payload.get("observed_velocity_mps")),
        final_coefficients=payload.get("final_coefficients", {}),
        main_wing_lift_acceptance_status=lift_acceptance_status,
        minimum_acceptable_cl=(
            MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
            if lift_acceptance_status != "not_evaluated"
            else None
        ),
        residual_median_log_drop=residual_drop,
        coefficient_stability_status=coefficient_status,
        coefficient_stability_by_axis=coefficient_by_axis,
        solver_log_quality_metrics=payload.get("solver_log_quality_metrics", {}),
        advisory_flags=_advisory_flags(
            payload=payload,
            gate=gate,
            residual_drop=residual_drop,
            coefficient_status=coefficient_status,
        ),
    )


def _row_sort_key(row: MainWingSolverBudgetComparisonRow) -> tuple[int, int, int]:
    policy_order = {
        "declared_blackcat_full_span": 0,
        "openvsp_geometry_derived": 1,
        "unknown": 2,
    }
    role_order = {"baseline_smoke": 0, "budget_probe": 1}
    return (
        policy_order[row.reference_policy],
        role_order[row.report_role],
        row.runtime_max_iterations or -1,
    )


def _flow_status(rows: list[MainWingSolverBudgetComparisonRow]) -> HPAFlowStatusType:
    velocities = [
        row.observed_velocity_mps
        for row in rows
        if isinstance(row.observed_velocity_mps, (int, float))
    ]
    if not velocities:
        return "unavailable"
    if all(abs(float(value) - 6.5) <= 1.0e-9 for value in velocities):
        return "hpa_standard_6p5_observed"
    return "mixed_or_nonstandard_velocity_observed"


def _current_route_row(rows: list[MainWingSolverBudgetComparisonRow]) -> dict[str, Any]:
    openvsp_rows = [
        row for row in rows if row.reference_policy == "openvsp_geometry_derived"
    ]
    candidates = openvsp_rows or rows
    if not candidates:
        return {}
    selected = max(candidates, key=lambda row: row.runtime_max_iterations or -1)
    return {
        "reference_policy": selected.reference_policy,
        "runtime_max_iterations": selected.runtime_max_iterations,
        "report_path": selected.report_path,
        "convergence_gate_status": selected.convergence_gate_status,
        "convergence_comparability_level": selected.convergence_comparability_level,
        "residual_median_log_drop": selected.residual_median_log_drop,
        "coefficient_stability_status": selected.coefficient_stability_status,
        "final_coefficients": selected.final_coefficients,
        "main_wing_lift_acceptance_status": selected.main_wing_lift_acceptance_status,
        "minimum_acceptable_cl": selected.minimum_acceptable_cl,
        "advisory_flags": selected.advisory_flags,
    }


def _report_status(rows: list[MainWingSolverBudgetComparisonRow]) -> ReportStatusType:
    if not rows:
        return "no_solver_smokes"
    if any(row.convergence_gate_status == "pass" for row in rows):
        return "solver_budget_gate_passed"
    if any(row.solver_execution_status == "solver_executed" for row in rows):
        return "solver_budget_nonconverged"
    return "solver_smokes_observed"


def _engineering_assessment(rows: list[MainWingSolverBudgetComparisonRow]) -> list[str]:
    if not rows:
        return ["No committed main-wing solver smoke report was found."]
    current = _current_route_row(rows)
    assessment = [
        "This comparison is report-only and does not execute SU2.",
        "Solver execution is treated separately from convergence; only a pass gate can be called converged.",
    ]
    if current.get("convergence_gate_status") != "pass":
        assessment.append(
            "The highest available current-route budget remains non-converged or warn-only."
        )
    if current.get("coefficient_stability_status") == "pass":
        assessment.append(
            "Current-route coefficient tails are stable, but residual and reference gates still limit comparability."
        )
    if "main_wing_cl_below_expected_lift" in current.get("advisory_flags", []):
        assessment.append(
            "Current-route CL is below 1 at HPA 6.5 m/s, so it cannot be accepted as converged main-wing evidence."
        )
    current_flags = current.get("advisory_flags", [])
    if any(str(flag).startswith("mesh_quality_") for flag in current_flags):
        assessment.append(
            "SU2 mesh-quality diagnostics now point at local mesh quality as a better next suspect than simply adding iterations."
        )
    if any("reference_geometry_warn" == flag for flag in current_flags):
        assessment.append(
            "Reference geometry remains warn-level, so moments and force comparability are not final engineering evidence."
        )
    return assessment


def _next_actions(rows: list[MainWingSolverBudgetComparisonRow]) -> list[str]:
    if not rows:
        return ["run_main_wing_real_solver_smoke_probe"]
    current = _current_route_row(rows)
    flags = set(current.get("advisory_flags", []))
    actions: list[str] = []
    if "main_wing_cl_below_expected_lift" in flags:
        actions.append("resolve_main_wing_cl_below_expected_lift_before_convergence_claims")
    if any(flag.startswith("mesh_quality_") for flag in flags):
        actions.append("inspect_main_wing_mesh_quality_before_more_iterations")
    if "residual_drop_below_threshold" in flags:
        actions.append(
            "compare_solver_numerics_and_mesh_local_sizing_before_larger_budget"
        )
    if "reference_geometry_warn" in flags:
        actions.append("resolve_main_wing_reference_area_and_moment_origin_policy")
    if not actions:
        actions.append("rerun_solver_budget_after_next_route_change")
    return actions


def build_main_wing_solver_budget_comparison_report(
    *,
    report_root: Path | None = None,
) -> MainWingSolverBudgetComparisonReport:
    root = _default_report_root() if report_root is None else report_root
    rows = [
        row
        for path in _discover_report_paths(root)
        if (row := _row_from_report_path(path, report_root=root)) is not None
    ]
    rows = sorted(rows, key=_row_sort_key)
    return MainWingSolverBudgetComparisonReport(
        hpa_standard_flow_status=_flow_status(rows),
        report_status=_report_status(rows),
        current_route_row=_current_route_row(rows),
        rows=rows,
        engineering_assessment=_engineering_assessment(rows),
        next_actions=_next_actions(rows),
        limitations=[
            "This report reads existing solver-smoke and convergence-gate artifacts only.",
            "A stable coefficient tail is not a convergence claim when residual or reference gates warn.",
            "Mesh-quality advisory flags are triage signals, not replacement convergence gates.",
            "The current upstream mesh remains a coarse bounded non-BL probe.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_markdown(report: MainWingSolverBudgetComparisonReport) -> str:
    lines = [
        "# Main Wing Solver Budget Comparison v1",
        "",
        "This report compares existing solver-smoke artifacts only; it does not execute SU2.",
        "",
        f"- report_status: `{report.report_status}`",
        f"- hpa_standard_velocity_mps: `{report.hpa_standard_velocity_mps}`",
        f"- hpa_standard_flow_status: `{report.hpa_standard_flow_status}`",
        "",
        "## Current Route Row",
        "",
    ]
    for key, value in report.current_route_row.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(
        [
            "",
            "## Rows",
            "",
            "| reference_policy | role | max_iter | final_iter | gate | residual_drop | CL | CD | CM | flags |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in report.rows:
        coeffs = row.final_coefficients
        flags = ", ".join(row.advisory_flags) if row.advisory_flags else "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row.reference_policy}`",
                    f"`{row.report_role}`",
                    f"`{_fmt(row.runtime_max_iterations)}`",
                    f"`{_fmt(row.final_iteration)}`",
                    f"`{_fmt(row.convergence_gate_status)}`",
                    f"`{_fmt(row.residual_median_log_drop)}`",
                    f"`{_fmt(coeffs.get('cl'))}`",
                    f"`{_fmt(coeffs.get('cd'))}`",
                    f"`{_fmt(coeffs.get('cm'))}`",
                    flags,
                ]
            )
            + " |"
        )
    lines.extend(["", "## Engineering Assessment", ""])
    lines.extend(f"- {item}" for item in report.engineering_assessment)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{item}`" for item in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_solver_budget_comparison_report(
    out_dir: Path,
    *,
    report: MainWingSolverBudgetComparisonReport | None = None,
    report_root: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_solver_budget_comparison_report(report_root=report_root)

    json_path = out_dir / "main_wing_solver_budget_comparison.v1.json"
    markdown_path = out_dir / "main_wing_solver_budget_comparison.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
