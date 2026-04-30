from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from .main_wing_station_seam_shape_fix_feasibility import (
    DEFAULT_SHAPE_FIX_OPERATIONS,
    DEFAULT_SHAPE_FIX_TOLERANCES,
    _attempt_summary,
    _run_shape_fix_feasibility,
    _summary,
)


ProfileResampleRepairFeasibilityStatusType = Literal[
    "profile_resample_station_shape_fix_repair_recovered",
    "profile_resample_station_shape_fix_repair_not_recovered",
    "unavailable",
    "blocked",
]

ProfileResampleRepairRunner = Callable[..., Dict[str, Any]]


class MainWingStationSeamProfileResampleRepairFeasibilityProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_profile_resample_repair_feasibility_probe.v1"
    ] = "main_wing_station_seam_profile_resample_repair_feasibility_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_profile_resample_station_repair_feasibility"
    ] = "report_only_profile_resample_station_repair_feasibility"
    production_default_changed: bool = False
    feasibility_status: ProfileResampleRepairFeasibilityStatusType
    brep_validation_probe_path: str
    candidate_step_path: str | None = None
    target_edges: list[dict[str, Any]] = Field(default_factory=list)
    tolerances: list[float] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    baseline_checks: list[dict[str, Any]] = Field(default_factory=list)
    repair_attempts: list[dict[str, Any]] = Field(default_factory=list)
    baseline_summary: dict[str, Any] = Field(default_factory=dict)
    attempt_summary: dict[str, Any] = Field(default_factory=dict)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_brep_validation_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_profile_resample_brep_validation_probe"
        / "main_wing_station_seam_profile_resample_brep_validation_probe.v1.json"
    )


def _load_json(path: Path, blockers: list[str], label: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        blockers.append(f"{label}_missing")
        return None
    except json.JSONDecodeError as exc:
        blockers.append(f"{label}_invalid_json:{exc}")
        return None
    return payload if isinstance(payload, dict) else {}


def _resolve_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    path = Path(str(value))
    return path if path.is_absolute() else _repo_root() / path


def _as_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    result: set[int] = set()
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            result.add(int(value))
    return sorted(result)


def _target_edges_from_validation(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    target_edges: list[dict[str, Any]] = []
    seen: set[tuple[int, int, tuple[int, ...]]] = set()
    for check in payload.get("station_edge_checks", []):
        if not isinstance(check, dict):
            continue
        curve_id = check.get("candidate_step_curve_tag")
        edge_index = check.get("candidate_step_edge_index")
        if not isinstance(curve_id, int) or not isinstance(edge_index, int):
            continue
        face_ids = _as_int_list(check.get("ancestor_face_ids"))
        key = (int(curve_id), int(edge_index), tuple(face_ids))
        if key in seen:
            continue
        seen.add(key)
        target_edges.append(
            {
                "curve_id": int(curve_id),
                "edge_index": int(edge_index),
                "face_ids": face_ids,
            }
        )
    return target_edges


def _attempt_recovered(attempt: dict[str, Any]) -> bool:
    if attempt.get("recovered") is True:
        return True
    checks = attempt.get("checks", [])
    return isinstance(checks, list) and _summary(checks).get(
        "all_station_checks_pass"
    ) is True


def _status(
    *,
    blockers: list[str],
    runner_payload: dict[str, Any],
    repair_attempts: list[dict[str, Any]],
) -> ProfileResampleRepairFeasibilityStatusType:
    if blockers:
        return "blocked"
    if runner_payload.get("runtime_status") == "unavailable":
        return "unavailable"
    if any(_attempt_recovered(attempt) for attempt in repair_attempts):
        return "profile_resample_station_shape_fix_repair_recovered"
    return "profile_resample_station_shape_fix_repair_not_recovered"


def _engineering_findings(
    status: ProfileResampleRepairFeasibilityStatusType,
    baseline_summary: dict[str, Any],
    attempt_summary: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["profile_resample_station_repair_feasibility_blocked"]
    if status == "unavailable":
        return ["profile_resample_station_repair_runtime_unavailable"]
    findings = ["profile_resample_station_repair_feasibility_evaluated"]
    if baseline_summary.get("all_target_pcurves_present") is True:
        findings.append("profile_resample_station_target_pcurves_are_present")
    if status == "profile_resample_station_shape_fix_repair_recovered":
        findings.append("profile_resample_station_shape_fix_recovered_candidate_checks")
    else:
        findings.append(
            "profile_resample_station_shape_fix_did_not_recover_candidate_checks"
        )
    if int(attempt_summary.get("recovered_attempt_count") or 0) == 0:
        findings.append("profile_resample_station_export_repair_needed")
    return findings


def _blocking_reasons(
    status: ProfileResampleRepairFeasibilityStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "unavailable":
        reasons.append("profile_resample_station_repair_runtime_unavailable")
    if status == "profile_resample_station_shape_fix_repair_not_recovered":
        reasons.append("profile_resample_station_shape_fix_repair_not_recovered")
    if status == "blocked" and not reasons:
        reasons.append("profile_resample_station_repair_feasibility_blocked")
    return reasons


def _next_actions(status: ProfileResampleRepairFeasibilityStatusType) -> list[str]:
    if status == "profile_resample_station_shape_fix_repair_recovered":
        return [
            "materialize_profile_resample_repaired_step_before_mesh_handoff",
            "rerun_profile_resample_brep_validation_on_repaired_candidate",
        ]
    if status == "profile_resample_station_shape_fix_repair_not_recovered":
        return [
            "change_profile_resample_export_pcurve_generation_or_section_parametrization",
            "avoid_direct_mesh_handoff_from_current_profile_resample_candidate",
        ]
    if status == "unavailable":
        return ["restore_ocp_runtime_before_profile_resample_repair_claims"]
    return ["restore_profile_resample_repair_feasibility_inputs"]


def build_main_wing_station_seam_profile_resample_repair_feasibility_probe_report(
    *,
    brep_validation_probe_path: Path | None = None,
    tolerances: list[float] | None = None,
    operations: list[str] | None = None,
    feasibility_runner: ProfileResampleRepairRunner | None = None,
) -> MainWingStationSeamProfileResampleRepairFeasibilityProbeReport:
    source_path = (
        _default_brep_validation_probe_path()
        if brep_validation_probe_path is None
        else brep_validation_probe_path
    )
    blockers: list[str] = []
    source_payload = _load_json(source_path, blockers, "brep_validation_probe")
    step_path = _resolve_path(
        source_payload.get("candidate_step_path")
        if isinstance(source_payload, dict)
        else None
    )
    if step_path is None:
        blockers.append("profile_resample_candidate_step_path_missing")
    elif not step_path.exists():
        blockers.append("profile_resample_candidate_step_missing")
    target_edges = _target_edges_from_validation(source_payload)
    if not target_edges:
        blockers.append("profile_resample_repair_target_edges_missing")
    tolerance_values = (
        list(DEFAULT_SHAPE_FIX_TOLERANCES)
        if tolerances is None
        else [float(value) for value in tolerances]
    )
    operation_values = (
        list(DEFAULT_SHAPE_FIX_OPERATIONS)
        if operations is None
        else [str(value) for value in operations]
    )
    runner_payload: dict[str, Any] = {}
    if not blockers and step_path is not None:
        runner = feasibility_runner or _run_shape_fix_feasibility
        runner_payload = runner(
            step_path=step_path,
            target_edges=target_edges,
            tolerances=tolerance_values,
            operations=operation_values,
        )
    baseline_checks = [
        check
        for check in runner_payload.get("baseline_checks", [])
        if isinstance(check, dict)
    ]
    repair_attempts = [
        attempt
        for attempt in runner_payload.get("repair_attempts", [])
        if isinstance(attempt, dict)
    ]
    baseline_summary = _summary(baseline_checks)
    attempt_summary = _attempt_summary(repair_attempts)
    status = _status(
        blockers=blockers,
        runner_payload=runner_payload,
        repair_attempts=repair_attempts,
    )
    return MainWingStationSeamProfileResampleRepairFeasibilityProbeReport(
        feasibility_status=status,
        brep_validation_probe_path=str(source_path),
        candidate_step_path=str(step_path) if step_path is not None else None,
        target_edges=target_edges,
        tolerances=tolerance_values,
        operations=operation_values,
        baseline_checks=baseline_checks,
        repair_attempts=repair_attempts,
        baseline_summary=baseline_summary,
        attempt_summary=attempt_summary,
        engineering_findings=_engineering_findings(
            status,
            baseline_summary,
            attempt_summary,
        ),
        blocking_reasons=_blocking_reasons(status, blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This probe evaluates bounded in-memory OCCT repair only and writes no repaired STEP.",
            "It does not change production defaults or promote the profile-resample candidate.",
            "It does not run Gmsh volume mesh generation, SU2_CFD, CL acceptance, or convergence checks.",
            "Recovery is defined by post-operation PCurve, same-parameter, curve-3D-with-PCurve, and vertex-tolerance checks.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingStationSeamProfileResampleRepairFeasibilityProbeReport,
) -> str:
    lines = [
        "# Main Wing Station Seam Profile Resample Repair Feasibility Probe v1",
        "",
        "This report tests bounded in-memory OCCT repair against profile-resample candidate station-edge checks without writing repaired geometry.",
        "",
        f"- feasibility_status: `{report.feasibility_status}`",
        f"- brep_validation_probe_path: `{report.brep_validation_probe_path}`",
        f"- candidate_step_path: `{report.candidate_step_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Baseline Summary",
        "",
    ]
    for key, value in report.baseline_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Attempt Summary", ""])
    for key, value in report.attempt_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Target Edges", ""])
    if report.target_edges:
        lines.extend(f"- `{_fmt(item)}`" for item in report.target_edges)
    else:
        lines.append("- none")
    lines.extend(["", "## Repair Attempts", ""])
    if report.repair_attempts:
        lines.extend(f"- `{_fmt(item)}`" for item in report.repair_attempts)
    else:
        lines.append("- none")
    lines.extend(["", "## Engineering Findings", ""])
    lines.extend(f"- `{finding}`" for finding in report.engineering_findings)
    lines.extend(["", "## Blocking Reasons", ""])
    if report.blocking_reasons:
        lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    else:
        lines.append("- none")
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_station_seam_profile_resample_repair_feasibility_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamProfileResampleRepairFeasibilityProbeReport
    | None = None,
    brep_validation_probe_path: Path | None = None,
    tolerances: list[float] | None = None,
    operations: list[str] | None = None,
    feasibility_runner: ProfileResampleRepairRunner | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_profile_resample_repair_feasibility_probe_report(
            brep_validation_probe_path=brep_validation_probe_path,
            tolerances=tolerances,
            operations=operations,
            feasibility_runner=feasibility_runner,
        )
    json_path = (
        out_dir / "main_wing_station_seam_profile_resample_repair_feasibility_probe.v1.json"
    )
    markdown_path = (
        out_dir / "main_wing_station_seam_profile_resample_repair_feasibility_probe.v1.md"
    )
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
