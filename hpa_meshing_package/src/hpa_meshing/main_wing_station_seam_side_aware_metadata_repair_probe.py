from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from .main_wing_station_seam_profile_resample_repair_feasibility_probe import (
    _target_edges_from_validation,
)
from .main_wing_station_seam_same_parameter_feasibility import (
    _run_same_parameter_feasibility,
)
from .main_wing_station_seam_shape_fix_feasibility import (
    DEFAULT_SHAPE_FIX_OPERATIONS,
    DEFAULT_SHAPE_FIX_TOLERANCES,
    _run_shape_fix_feasibility,
    _summary as _station_check_summary,
)


SideAwareMetadataRepairStatusType = Literal[
    "side_aware_station_metadata_repair_recovered",
    "side_aware_station_metadata_repair_not_recovered",
    "side_aware_station_metadata_repair_unavailable",
    "blocked",
]

MetadataRepairRunner = Callable[..., Dict[str, Any]]


class MainWingStationSeamSideAwareMetadataRepairProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_side_aware_metadata_repair_probe.v1"
    ] = "main_wing_station_seam_side_aware_metadata_repair_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_side_aware_station_metadata_repair"
    ] = "report_only_side_aware_station_metadata_repair"
    production_default_changed: bool = False
    metadata_repair_status: SideAwareMetadataRepairStatusType
    side_aware_brep_validation_probe_path: str
    pcurve_residual_diagnostic_path: str
    candidate_step_path: str | None = None
    target_edges: list[dict[str, Any]] = Field(default_factory=list)
    tolerances: list[float] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    residual_context_summary: dict[str, Any] = Field(default_factory=dict)
    same_parameter_baseline_checks: list[dict[str, Any]] = Field(default_factory=list)
    same_parameter_repair_attempts: list[dict[str, Any]] = Field(default_factory=list)
    same_parameter_baseline_summary: dict[str, Any] = Field(default_factory=dict)
    same_parameter_attempt_summary: dict[str, Any] = Field(default_factory=dict)
    shape_fix_baseline_checks: list[dict[str, Any]] = Field(default_factory=list)
    shape_fix_repair_attempts: list[dict[str, Any]] = Field(default_factory=list)
    shape_fix_baseline_summary: dict[str, Any] = Field(default_factory=dict)
    shape_fix_attempt_summary: dict[str, Any] = Field(default_factory=dict)
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
        / "main_wing_station_seam_side_aware_brep_validation_probe"
        / "main_wing_station_seam_side_aware_brep_validation_probe.v1.json"
    )


def _default_pcurve_residual_diagnostic_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_side_aware_pcurve_residual_diagnostic"
        / "main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1.json"
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
    if path.is_absolute():
        return path
    repo_path = _repo_root() / path
    if repo_path.exists():
        return repo_path
    package_path = _repo_root() / "hpa_meshing_package" / path
    if package_path.exists():
        return package_path
    return repo_path


def _dict_list(values: Any) -> list[dict[str, Any]]:
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _target_checks(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return _dict_list(payload.get(key, []))


def _station_attempt_recovered(attempt: dict[str, Any]) -> bool:
    checks = _target_checks(attempt, "checks")
    if checks:
        return _station_check_summary(checks).get("all_station_checks_pass") is True
    return attempt.get("recovered") is True


def _metadata_attempt_summary(attempts: list[dict[str, Any]], *, include_operations: bool) -> dict[str, Any]:
    recovered = [attempt for attempt in attempts if _station_attempt_recovered(attempt)]
    summary: dict[str, Any] = {
        "attempt_count": len(attempts),
        "tolerances_evaluated": sorted(
            {
                float(attempt.get("tolerance"))
                for attempt in attempts
                if isinstance(attempt.get("tolerance"), (int, float))
                and not isinstance(attempt.get("tolerance"), bool)
            }
        ),
        "recovered_attempt_count": len(recovered),
        "first_recovered_tolerance": (
            recovered[0].get("tolerance") if recovered else None
        ),
    }
    if include_operations:
        summary["operations_evaluated"] = sorted(
            {
                str(attempt.get("operation"))
                for attempt in attempts
                if attempt.get("operation") is not None
            }
        )
        summary["first_recovered_operation"] = (
            recovered[0].get("operation") if recovered else None
        )
    return summary


def _residual_context(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    residual_summary = payload.get("residual_summary", {})
    residual_summary = residual_summary if isinstance(residual_summary, dict) else {}
    keys = [
        "edge_face_residual_count",
        "sampled_edge_face_count",
        "max_sample_distance_m",
        "max_sample_distance_over_edge_tolerance",
        "shape_analysis_flag_failure_count",
        "residual_exceeds_edge_tolerance_count",
        "unbounded_pcurve_domain_count",
        "pcurve_missing_count",
    ]
    return {
        "diagnostic_status": payload.get("diagnostic_status"),
        **{key: residual_summary.get(key) for key in keys if key in residual_summary},
    }


def _status(
    *,
    blockers: list[str],
    same_parameter_payload: dict[str, Any],
    shape_fix_payload: dict[str, Any],
    same_parameter_attempt_summary: dict[str, Any],
    shape_fix_attempt_summary: dict[str, Any],
) -> SideAwareMetadataRepairStatusType:
    if blockers:
        return "blocked"
    if (
        same_parameter_payload.get("runtime_status") == "unavailable"
        or shape_fix_payload.get("runtime_status") == "unavailable"
    ):
        return "side_aware_station_metadata_repair_unavailable"
    if (
        int(same_parameter_attempt_summary.get("recovered_attempt_count") or 0) > 0
        or int(shape_fix_attempt_summary.get("recovered_attempt_count") or 0) > 0
    ):
        return "side_aware_station_metadata_repair_recovered"
    return "side_aware_station_metadata_repair_not_recovered"


def _engineering_findings(
    *,
    status: SideAwareMetadataRepairStatusType,
    residual_context_summary: dict[str, Any],
    same_parameter_baseline_summary: dict[str, Any],
    same_parameter_attempt_summary: dict[str, Any],
    shape_fix_attempt_summary: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["side_aware_station_metadata_repair_blocked"]
    if status == "side_aware_station_metadata_repair_unavailable":
        return ["side_aware_station_metadata_repair_runtime_unavailable"]
    findings = ["side_aware_station_metadata_repair_evaluated"]
    if same_parameter_baseline_summary.get("all_target_pcurves_present") is True:
        findings.append("side_aware_station_target_pcurves_are_present")
    same_parameter_recovered = (
        int(same_parameter_attempt_summary.get("recovered_attempt_count") or 0) > 0
    )
    shape_fix_recovered = (
        int(shape_fix_attempt_summary.get("recovered_attempt_count") or 0) > 0
    )
    if same_parameter_recovered:
        findings.append("side_aware_breplib_same_parameter_recovered_metadata_gate")
    else:
        findings.append("side_aware_breplib_same_parameter_not_recovered")
    if shape_fix_recovered:
        findings.append("side_aware_shape_fix_recovered_metadata_gate")
    else:
        findings.append("side_aware_shape_fix_not_recovered")
    if (
        residual_context_summary.get("max_sample_distance_m") == 0.0
        and status == "side_aware_station_metadata_repair_not_recovered"
    ):
        findings.append(
            "side_aware_sampled_residual_zero_but_metadata_repair_not_recovered"
        )
    if status == "side_aware_station_metadata_repair_not_recovered":
        findings.append("side_aware_export_pcurve_rebuild_needed")
    return findings


def _blocking_reasons(
    status: SideAwareMetadataRepairStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "side_aware_station_metadata_repair_unavailable":
        reasons.append("side_aware_station_metadata_repair_runtime_unavailable")
    if status == "side_aware_station_metadata_repair_not_recovered":
        reasons.append("side_aware_station_metadata_repair_not_recovered")
        reasons.append("side_aware_candidate_mesh_handoff_not_run")
    if status == "blocked" and not reasons:
        reasons.append("side_aware_station_metadata_repair_blocked")
    return list(dict.fromkeys(reasons))


def _next_actions(status: SideAwareMetadataRepairStatusType) -> list[str]:
    if status == "side_aware_station_metadata_repair_recovered":
        return [
            "materialize_side_aware_metadata_repaired_step_before_mesh_handoff",
            "rerun_side_aware_brep_validation_on_metadata_repaired_candidate",
            "run_bounded_main_wing_mesh_handoff_from_repaired_candidate",
        ]
    if status == "side_aware_station_metadata_repair_not_recovered":
        return [
            "prototype_side_aware_station_pcurve_rewrite_or_export_metadata_builder",
            "avoid_more_generic_same_parameter_shape_fix_sweeps",
            "do_not_advance_to_solver_budget_until_station_metadata_gate_changes",
        ]
    if status == "side_aware_station_metadata_repair_unavailable":
        return ["restore_ocp_runtime_before_side_aware_metadata_repair_claims"]
    return ["restore_side_aware_metadata_repair_inputs"]


def build_main_wing_station_seam_side_aware_metadata_repair_probe_report(
    *,
    side_aware_brep_validation_probe_path: Path | None = None,
    pcurve_residual_diagnostic_path: Path | None = None,
    tolerances: list[float] | None = None,
    operations: list[str] | None = None,
    same_parameter_runner: MetadataRepairRunner | None = None,
    shape_fix_runner: MetadataRepairRunner | None = None,
) -> MainWingStationSeamSideAwareMetadataRepairProbeReport:
    brep_path = (
        _default_brep_validation_probe_path()
        if side_aware_brep_validation_probe_path is None
        else side_aware_brep_validation_probe_path
    )
    residual_path = (
        _default_pcurve_residual_diagnostic_path()
        if pcurve_residual_diagnostic_path is None
        else pcurve_residual_diagnostic_path
    )
    blockers: list[str] = []
    brep_payload = _load_json(brep_path, blockers, "side_aware_brep_validation_probe")
    residual_payload = _load_json(
        residual_path,
        blockers,
        "side_aware_pcurve_residual_diagnostic",
    )
    step_path = _resolve_path(
        brep_payload.get("candidate_step_path") if isinstance(brep_payload, dict) else None
    )
    if step_path is None:
        blockers.append("side_aware_candidate_step_path_missing")
    elif not step_path.exists():
        blockers.append("side_aware_candidate_step_missing")
    target_edges = _target_edges_from_validation(brep_payload)
    if not target_edges:
        blockers.append("side_aware_metadata_repair_target_edges_missing")
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

    same_parameter_payload: dict[str, Any] = {}
    shape_fix_payload: dict[str, Any] = {}
    if not blockers and step_path is not None:
        same_runner = same_parameter_runner or _run_same_parameter_feasibility
        shape_runner = shape_fix_runner or _run_shape_fix_feasibility
        same_parameter_payload = same_runner(
            step_path=step_path,
            target_edges=target_edges,
            tolerances=tolerance_values,
        )
        shape_fix_payload = shape_runner(
            step_path=step_path,
            target_edges=target_edges,
            tolerances=tolerance_values,
            operations=operation_values,
        )

    same_parameter_baseline_checks = _target_checks(
        same_parameter_payload,
        "baseline_checks",
    )
    same_parameter_attempts = _target_checks(
        same_parameter_payload,
        "repair_attempts",
    )
    shape_fix_baseline_checks = _target_checks(shape_fix_payload, "baseline_checks")
    shape_fix_attempts = _target_checks(shape_fix_payload, "repair_attempts")
    same_parameter_baseline_summary = _station_check_summary(
        same_parameter_baseline_checks
    )
    shape_fix_baseline_summary = _station_check_summary(shape_fix_baseline_checks)
    same_parameter_attempt_summary = _metadata_attempt_summary(
        same_parameter_attempts,
        include_operations=False,
    )
    shape_fix_attempt_summary = _metadata_attempt_summary(
        shape_fix_attempts,
        include_operations=True,
    )
    residual_context_summary = _residual_context(residual_payload)
    metadata_status = _status(
        blockers=blockers,
        same_parameter_payload=same_parameter_payload,
        shape_fix_payload=shape_fix_payload,
        same_parameter_attempt_summary=same_parameter_attempt_summary,
        shape_fix_attempt_summary=shape_fix_attempt_summary,
    )

    return MainWingStationSeamSideAwareMetadataRepairProbeReport(
        metadata_repair_status=metadata_status,
        side_aware_brep_validation_probe_path=str(brep_path),
        pcurve_residual_diagnostic_path=str(residual_path),
        candidate_step_path=str(step_path) if step_path is not None else None,
        target_edges=target_edges,
        tolerances=tolerance_values,
        operations=operation_values,
        residual_context_summary=residual_context_summary,
        same_parameter_baseline_checks=same_parameter_baseline_checks,
        same_parameter_repair_attempts=same_parameter_attempts,
        same_parameter_baseline_summary=same_parameter_baseline_summary,
        same_parameter_attempt_summary=same_parameter_attempt_summary,
        shape_fix_baseline_checks=shape_fix_baseline_checks,
        shape_fix_repair_attempts=shape_fix_attempts,
        shape_fix_baseline_summary=shape_fix_baseline_summary,
        shape_fix_attempt_summary=shape_fix_attempt_summary,
        engineering_findings=_engineering_findings(
            status=metadata_status,
            residual_context_summary=residual_context_summary,
            same_parameter_baseline_summary=same_parameter_baseline_summary,
            same_parameter_attempt_summary=same_parameter_attempt_summary,
            shape_fix_attempt_summary=shape_fix_attempt_summary,
        ),
        blocking_reasons=_blocking_reasons(metadata_status, blockers),
        next_actions=_next_actions(metadata_status),
        limitations=[
            "This probe evaluates bounded in-memory OCCT metadata repair only and writes no repaired STEP.",
            "It does not change production defaults or promote the side-aware candidate to mesh handoff.",
            "It does not run Gmsh volume mesh generation, SU2_CFD, CL acceptance, or convergence checks.",
            "Recovery requires target station-edge PCurve, same-parameter, curve-3D-with-PCurve, and vertex-tolerance checks to pass.",
            "A low sampled PCurve residual is recorded as context only; it is not a mesh-readiness pass.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingStationSeamSideAwareMetadataRepairProbeReport,
) -> str:
    lines = [
        "# Main Wing Station-Seam Side-Aware Metadata Repair Probe v1",
        "",
        "This report tests bounded in-memory OCCT metadata repair against the side-aware station-seam candidate without writing repaired geometry.",
        "",
        f"- metadata_repair_status: `{report.metadata_repair_status}`",
        f"- side_aware_brep_validation_probe_path: `{report.side_aware_brep_validation_probe_path}`",
        f"- pcurve_residual_diagnostic_path: `{report.pcurve_residual_diagnostic_path}`",
        f"- candidate_step_path: `{report.candidate_step_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Residual Context",
        "",
    ]
    for key, value in report.residual_context_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## SameParameter Attempt Summary", ""])
    for key, value in report.same_parameter_attempt_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## ShapeFix Attempt Summary", ""])
    for key, value in report.shape_fix_attempt_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Target Edges", ""])
    if report.target_edges:
        lines.extend(f"- `{_fmt(item)}`" for item in report.target_edges)
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


def write_main_wing_station_seam_side_aware_metadata_repair_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamSideAwareMetadataRepairProbeReport | None = None,
    side_aware_brep_validation_probe_path: Path | None = None,
    pcurve_residual_diagnostic_path: Path | None = None,
    tolerances: list[float] | None = None,
    operations: list[str] | None = None,
    same_parameter_runner: MetadataRepairRunner | None = None,
    shape_fix_runner: MetadataRepairRunner | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_side_aware_metadata_repair_probe_report(
            side_aware_brep_validation_probe_path=side_aware_brep_validation_probe_path,
            pcurve_residual_diagnostic_path=pcurve_residual_diagnostic_path,
            tolerances=tolerances,
            operations=operations,
            same_parameter_runner=same_parameter_runner,
            shape_fix_runner=shape_fix_runner,
        )
    json_path = (
        out_dir / "main_wing_station_seam_side_aware_metadata_repair_probe.v1.json"
    )
    markdown_path = (
        out_dir / "main_wing_station_seam_side_aware_metadata_repair_probe.v1.md"
    )
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
