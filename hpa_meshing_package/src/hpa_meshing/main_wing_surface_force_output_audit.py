from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


AuditStatusType = Literal["pass", "warn", "blocked", "unavailable"]


class MainWingSurfaceForceOutputAuditReport(BaseModel):
    schema_version: Literal["main_wing_surface_force_output_audit.v1"] = (
        "main_wing_surface_force_output_audit.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_solver_artifacts"] = (
        "report_only_existing_solver_artifacts"
    )
    production_default_changed: bool = False
    audit_status: AuditStatusType
    selected_solver_report_path: str | None = None
    solver_report_dir: str | None = None
    solver_log_path: str | None = None
    panel_reference_report_path: str | None = None
    solver_execution_observed: Dict[str, Any] = Field(default_factory=dict)
    expected_outputs_from_log: Dict[str, str | None] = Field(default_factory=dict)
    artifact_retention_observed: Dict[str, Any] = Field(default_factory=dict)
    panel_reference_observed: Dict[str, Any] = Field(default_factory=dict)
    checks: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    engineering_flags: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _default_report_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "reports"


def _default_solver_report_path(report_root: Path) -> Path:
    return (
        report_root
        / "main_wing_openvsp_reference_solver_smoke_probe_iter80"
        / "main_wing_real_solver_smoke_probe.v1.json"
    )


def _default_panel_reference_path(report_root: Path) -> Path:
    return (
        report_root
        / "main_wing_vspaero_panel_reference_probe"
        / "main_wing_vspaero_panel_reference_probe.v1.json"
    )


def _repo_root_from_report_root(report_root: Path) -> Path | None:
    try:
        return report_root.resolve().parents[2]
    except IndexError:
        return None


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_existing_path(
    raw_path: Any,
    *,
    report_root: Path,
    anchor_path: Path | None = None,
) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path)
    candidates = [path]
    repo_root = _repo_root_from_report_root(report_root)
    if not path.is_absolute() and repo_root is not None:
        candidates.append(repo_root / path)
    if not path.is_absolute() and anchor_path is not None:
        candidates.append(anchor_path.parent / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _selected_solver_log_path(
    solver_report: dict[str, Any] | None,
    *,
    report_root: Path,
    solver_report_path: Path,
) -> Path | None:
    committed = solver_report_path.parent / "artifacts" / "raw_solver" / "solver.log"
    if committed.exists():
        return committed.resolve()
    return _resolve_existing_path(
        solver_report.get("solver_log_path") if isinstance(solver_report, dict) else None,
        report_root=report_root,
        anchor_path=solver_report_path,
    )


def _parse_expected_outputs_from_log(path: Path | None) -> dict[str, str | None]:
    expected: dict[str, str | None] = {
        "surface_csv": None,
        "forces_breakdown": None,
    }
    if path is None or not path.exists():
        return expected
    text = path.read_text(encoding="utf-8", errors="replace")
    force_match = re.search(r"Forces breakdown file name:\s*([^.\s]+(?:\.[^.\s]+)?)\.", text)
    if force_match:
        expected["forces_breakdown"] = force_match.group(1).strip()
    csv_match = re.search(r"\|\s*CSV file\s*\|\s*(surface\.csv)\s*\|", text)
    if csv_match:
        expected["surface_csv"] = csv_match.group(1).strip()
    elif re.search(r"Surface file name:\s*surface\b", text):
        expected["surface_csv"] = "surface.csv"
    return expected


def _raw_solver_dir(solver_report_path: Path) -> Path:
    return solver_report_path.parent / "artifacts" / "raw_solver"


def _existing_named_outputs(
    *,
    raw_solver_dir: Path,
    solver_report: dict[str, Any] | None,
    report_root: Path,
    solver_report_path: Path,
    name: str | None,
) -> list[str]:
    if not name:
        return []
    candidates: list[Path] = [raw_solver_dir / name, solver_report_path.parent / name]
    case_dir = (
        solver_report.get("case_dir") if isinstance(solver_report, dict) else None
    )
    resolved_case_dir = _resolve_existing_path(
        case_dir,
        report_root=report_root,
        anchor_path=solver_report_path,
    )
    if resolved_case_dir is not None:
        candidates.append(resolved_case_dir / name)
    return [str(path.resolve()) for path in candidates if path.exists()]


def _pruned_outputs_matching(
    solver_report: dict[str, Any] | None,
    output_name: str | None,
) -> list[str]:
    if not output_name or not isinstance(solver_report, dict):
        return []
    pruned = solver_report.get("pruned_output_paths", [])
    if not isinstance(pruned, list):
        return []
    return [
        str(path)
        for path in pruned
        if isinstance(path, str) and Path(path).name == output_name
    ]


def _panel_reference_observed(panel: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(panel, dict):
        return {"status": "unavailable"}
    reference = panel.get("panel_reference", {})
    comparison = panel.get("comparison", {})
    selected_case = panel.get("selected_case", {})
    setup_reference = panel.get("setup_reference", {})
    su2_comparison = panel.get("su2_smoke_comparison", {})
    comparison_payload = (
        su2_comparison
        if isinstance(su2_comparison, dict) and su2_comparison
        else comparison
        if isinstance(comparison, dict)
        else {}
    )
    return {
        "status": comparison_payload.get("status")
        or panel.get("panel_reference_status")
        or "available",
        "panel_reference_cl": (
            comparison_payload.get("panel_reference_cl")
            if isinstance(comparison_payload, dict)
            else None
        )
        or (
            reference.get("cltot")
            if isinstance(reference, dict)
            else None
        )
        or (
            selected_case.get("CLtot") if isinstance(selected_case, dict) else None
        ),
        "selected_su2_smoke_cl": (
            comparison_payload.get("selected_su2_smoke_cl")
            if isinstance(comparison_payload, dict)
            else None
        ),
        "panel_to_su2_cl_ratio": (
            comparison_payload.get("panel_to_su2_cl_ratio")
            if isinstance(comparison_payload, dict)
            else None
        ),
        "velocity_mps": (
            reference.get("velocity_mps") if isinstance(reference, dict) else None
        )
        or (
            setup_reference.get("Vinf")
            if isinstance(setup_reference, dict)
            else None
        ),
        "alpha_deg": (
            reference.get("alpha_deg") if isinstance(reference, dict) else None
        )
        or (selected_case.get("AoA") if isinstance(selected_case, dict) else None),
    }


def _check(status: str, observed: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return {"status": status, "observed": observed, "expected": expected}


def _main_wing_lift_acceptance_status(
    solver_report: dict[str, Any] | None,
) -> str | None:
    if not isinstance(solver_report, dict):
        return None
    reported = solver_report.get("main_wing_lift_acceptance_status")
    if isinstance(reported, str):
        return reported
    observed_velocity = solver_report.get("observed_velocity_mps")
    coefficients = solver_report.get("final_coefficients", {})
    cl = coefficients.get("cl") if isinstance(coefficients, dict) else None
    if not isinstance(observed_velocity, (int, float)):
        return None
    if abs(float(observed_velocity) - 6.5) > 1.0e-9:
        return None
    if not isinstance(cl, (int, float)):
        return None
    return "pass" if float(cl) > 1.0 else "fail"


def build_main_wing_surface_force_output_audit_report(
    *,
    report_root: Path | None = None,
    solver_report_path: Path | None = None,
    panel_reference_report_path: Path | None = None,
) -> MainWingSurfaceForceOutputAuditReport:
    root = _default_report_root() if report_root is None else report_root
    selected_solver_report_path = (
        _default_solver_report_path(root)
        if solver_report_path is None
        else solver_report_path
    )
    selected_panel_reference_path = (
        _default_panel_reference_path(root)
        if panel_reference_report_path is None
        else panel_reference_report_path
    )
    solver_report = _load_json(selected_solver_report_path)
    panel_report = _load_json(selected_panel_reference_path)
    solver_log_path = _selected_solver_log_path(
        solver_report,
        report_root=root,
        solver_report_path=selected_solver_report_path,
    )
    expected_outputs = _parse_expected_outputs_from_log(solver_log_path)
    raw_dir = _raw_solver_dir(selected_solver_report_path)
    surface_outputs = _existing_named_outputs(
        raw_solver_dir=raw_dir,
        solver_report=solver_report,
        report_root=root,
        solver_report_path=selected_solver_report_path,
        name=expected_outputs["surface_csv"],
    )
    force_outputs = _existing_named_outputs(
        raw_solver_dir=raw_dir,
        solver_report=solver_report,
        report_root=root,
        solver_report_path=selected_solver_report_path,
        name=expected_outputs["forces_breakdown"],
    )
    pruned_surface_outputs = _pruned_outputs_matching(
        solver_report,
        expected_outputs["surface_csv"],
    )
    pruned_force_outputs = _pruned_outputs_matching(
        solver_report,
        expected_outputs["forces_breakdown"],
    )

    solver_execution_observed = {
        "solver_execution_status": (
            solver_report.get("solver_execution_status")
            if isinstance(solver_report, dict)
            else None
        ),
        "run_status": solver_report.get("run_status") if isinstance(solver_report, dict) else None,
        "convergence_gate_status": (
            solver_report.get("convergence_gate_status")
            if isinstance(solver_report, dict)
            else None
        ),
        "main_wing_lift_acceptance_status": _main_wing_lift_acceptance_status(
            solver_report
        ),
        "observed_velocity_mps": (
            solver_report.get("observed_velocity_mps")
            if isinstance(solver_report, dict)
            else None
        ),
        "runtime_max_iterations": (
            solver_report.get("runtime_max_iterations")
            if isinstance(solver_report, dict)
            else None
        ),
        "final_iteration": (
            solver_report.get("final_iteration") if isinstance(solver_report, dict) else None
        ),
        "final_coefficients": (
            solver_report.get("final_coefficients", {})
            if isinstance(solver_report, dict)
            else {}
        ),
    }
    panel_observed = _panel_reference_observed(panel_report)
    raw_files = sorted(str(path.resolve()) for path in raw_dir.glob("*") if path.is_file())
    artifact_retention_observed = {
        "raw_solver_dir": str(raw_dir),
        "committed_raw_solver_files": raw_files,
        "surface_csv_candidates": surface_outputs,
        "forces_breakdown_candidates": force_outputs,
        "pruned_surface_outputs": pruned_surface_outputs,
        "pruned_force_breakdown_outputs": pruned_force_outputs,
        "declared_pruned_output_paths": (
            solver_report.get("pruned_output_paths", [])
            if isinstance(solver_report, dict)
            else []
        ),
    }

    checks: dict[str, dict[str, Any]] = {}
    checks["solver_report_available"] = _check(
        "pass" if solver_report is not None else "blocked",
        {"path": str(selected_solver_report_path), "loaded": solver_report is not None},
        {"loaded": True},
    )
    checks["solver_executed"] = _check(
        "pass"
        if solver_execution_observed["solver_execution_status"] == "solver_executed"
        else "blocked",
        solver_execution_observed,
        {"solver_execution_status": "solver_executed"},
    )
    expected_surface = expected_outputs["surface_csv"] is not None
    checks["surface_csv_retained"] = _check(
        "pass" if surface_outputs else "blocked" if expected_surface else "unavailable",
        {
            "expected_from_solver_log": expected_outputs["surface_csv"],
            "retained_candidates": surface_outputs,
            "pruned_candidates": pruned_surface_outputs,
        },
        {"retained_candidates": ">= 1 committed or existing runtime surface.csv"},
    )
    expected_force_breakdown = expected_outputs["forces_breakdown"] is not None
    checks["forces_breakdown_retained"] = _check(
        "pass"
        if force_outputs
        else "blocked"
        if expected_force_breakdown
        else "unavailable",
        {
            "expected_from_solver_log": expected_outputs["forces_breakdown"],
            "retained_candidates": force_outputs,
            "pruned_candidates": pruned_force_outputs,
        },
        {"retained_candidates": ">= 1 committed or existing forces_breakdown.dat"},
    )
    panel_available = panel_observed.get("status") == "available"
    comparison_ready = bool(surface_outputs and force_outputs and panel_available)
    checks["panel_force_comparison_ready"] = _check(
        "pass" if comparison_ready else "blocked" if panel_available else "unavailable",
        {
            "panel_reference_status": panel_observed.get("status"),
            "surface_csv_retained": bool(surface_outputs),
            "forces_breakdown_retained": bool(force_outputs),
        },
        {
            "panel_reference_status": "available",
            "surface_csv_retained": True,
            "forces_breakdown_retained": True,
        },
    )

    blocking_reasons: list[str] = []
    if checks["solver_report_available"]["status"] == "blocked":
        blocking_reasons.append("solver_report_missing")
    if checks["solver_executed"]["status"] == "blocked":
        blocking_reasons.append("solver_execution_missing")
    if checks["surface_csv_retained"]["status"] == "blocked":
        blocking_reasons.append("surface_force_output_pruned_or_missing")
    if checks["forces_breakdown_retained"]["status"] == "blocked":
        blocking_reasons.append("forces_breakdown_output_missing")
    if checks["panel_force_comparison_ready"]["status"] == "blocked":
        blocking_reasons.append("panel_force_comparison_not_ready")

    engineering_flags: list[str] = []
    if solver_execution_observed["run_status"] == "solver_executed_but_not_converged":
        engineering_flags.append("solver_executed_but_not_converged")
    if solver_execution_observed["main_wing_lift_acceptance_status"] == "fail":
        engineering_flags.append("main_wing_lift_acceptance_failed_cl_below_one")
    if solver_execution_observed["observed_velocity_mps"] == 6.5:
        engineering_flags.append("hpa_standard_flow_conditions_6p5_mps_observed")

    if blocking_reasons:
        audit_status: AuditStatusType = "blocked"
    elif engineering_flags:
        audit_status = "warn"
    else:
        audit_status = "pass"

    next_actions: list[str] = []
    if "surface_force_output_pruned_or_missing" in blocking_reasons:
        next_actions.append("preserve_surface_csv_in_solver_smoke_artifacts")
    if "forces_breakdown_output_missing" in blocking_reasons:
        next_actions.append("preserve_forces_breakdown_dat_in_solver_smoke_artifacts")
    if "panel_force_comparison_not_ready" in blocking_reasons:
        next_actions.append("rerun_surface_force_output_audit_before_panel_delta_debug")
    if not blocking_reasons:
        next_actions.append("surface_force_outputs_available_for_panel_delta_debug")

    return MainWingSurfaceForceOutputAuditReport(
        audit_status=audit_status,
        selected_solver_report_path=str(selected_solver_report_path),
        solver_report_dir=str(selected_solver_report_path.parent),
        solver_log_path=None if solver_log_path is None else str(solver_log_path),
        panel_reference_report_path=str(selected_panel_reference_path),
        solver_execution_observed=solver_execution_observed,
        expected_outputs_from_log=expected_outputs,
        artifact_retention_observed=artifact_retention_observed,
        panel_reference_observed=panel_observed,
        checks=checks,
        engineering_flags=list(dict.fromkeys(engineering_flags)),
        blocking_reasons=list(dict.fromkeys(blocking_reasons)),
        next_actions=list(dict.fromkeys(next_actions)),
        limitations=[
            "This audit reads existing solver artifacts only and does not execute SU2.",
            "Solver execution is not convergence; convergence remains governed by the convergence gate.",
            "Surface-force output retention is required before using panel/SU2 force deltas to debug the CL gap.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(report: MainWingSurfaceForceOutputAuditReport) -> str:
    lines = [
        "# Main Wing Surface Force Output Audit v1",
        "",
        "This report reads existing solver artifacts only; it does not execute SU2.",
        "",
        f"- audit_status: `{report.audit_status}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        f"- selected_solver_report_path: `{report.selected_solver_report_path}`",
        f"- solver_log_path: `{report.solver_log_path}`",
        f"- panel_reference_report_path: `{report.panel_reference_report_path}`",
        "",
        "## Solver Execution Observed",
        "",
    ]
    for key, value in report.solver_execution_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Expected Outputs From Log", ""])
    for key, value in report.expected_outputs_from_log.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Checks", "", "| check | status |", "|---|---|"])
    for name, check in report.checks.items():
        lines.append(f"| `{name}` | `{check.get('status')}` |")
    lines.extend(["", "## Panel Reference Observed", ""])
    for key, value in report.panel_reference_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Blocking Reasons", ""])
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Engineering Flags", ""])
    lines.extend(f"- `{flag}`" for flag in report.engineering_flags)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_surface_force_output_audit_report(
    out_dir: Path,
    *,
    report: MainWingSurfaceForceOutputAuditReport | None = None,
    report_root: Path | None = None,
    solver_report_path: Path | None = None,
    panel_reference_report_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_surface_force_output_audit_report(
            report_root=report_root,
            solver_report_path=solver_report_path,
            panel_reference_report_path=panel_reference_report_path,
        )
    json_path = out_dir / "main_wing_surface_force_output_audit.v1.json"
    markdown_path = out_dir / "main_wing_surface_force_output_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
