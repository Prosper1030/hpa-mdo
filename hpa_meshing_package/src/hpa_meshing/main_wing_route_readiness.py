from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


StageType = Literal[
    "real_geometry",
    "geometry_provenance",
    "vspaero_panel_reference",
    "real_mesh_handoff",
    "synthetic_mesh_handoff",
    "synthetic_su2_handoff",
    "real_su2_handoff",
    "openvsp_reference_su2_handoff",
    "su2_force_marker_audit",
    "surface_force_output_audit",
    "panel_su2_lift_gap_debug",
    "mesh_quality_hotspot_audit",
    "su2_mesh_normal_audit",
    "panel_wake_semantics_audit",
    "su2_surface_topology_audit",
    "su2_topology_defect_localization",
    "openvsp_defect_station_audit",
    "gmsh_defect_entity_trace",
    "gmsh_curve_station_rebuild_audit",
    "openvsp_section_station_topology_fixture",
    "station_seam_repair_decision",
    "station_seam_brep_hotspot_probe",
    "station_seam_same_parameter_feasibility",
    "station_seam_shape_fix_feasibility",
    "station_seam_export_source_audit",
    "station_seam_export_strategy_probe",
    "station_seam_internal_cap_probe",
    "station_seam_profile_resample_strategy_probe",
    "station_seam_profile_resample_brep_validation_probe",
    "station_seam_profile_resample_repair_feasibility_probe",
    "station_seam_profile_parametrization_audit",
    "station_seam_side_aware_parametrization_probe",
    "station_seam_side_aware_brep_validation_probe",
    "station_seam_side_aware_pcurve_residual_diagnostic",
    "station_seam_side_aware_metadata_repair_probe",
    "station_seam_side_aware_pcurve_metadata_builder_probe",
    "station_seam_side_aware_projected_pcurve_builder_probe",
    "station_seam_side_aware_export_opcode_variant_probe",
    "station_seam_export_metadata_source_audit",
    "openvsp_reference_geometry_gate",
    "openvsp_reference_solver_smoke",
    "openvsp_reference_solver_budget_probe",
    "solver_smoke",
    "solver_budget_probe",
    "lift_acceptance_diagnostic",
    "convergence_gate",
]
StageStatusType = Literal["pass", "blocked", "materialized_synthetic_only", "not_run"]
EvidenceKindType = Literal["real", "synthetic", "absent"]
OverallStatusType = Literal[
    "blocked_at_real_geometry",
    "blocked_at_real_mesh_handoff",
    "blocked_at_real_su2_handoff",
    "solver_not_run",
    "convergence_not_run",
    "solver_smoke_blocked",
    "solver_executed_not_converged",
    "convergence_gate_passed",
]
HPAFlowStatusType = Literal[
    "hpa_standard_6p5_observed",
    "legacy_or_nonstandard_velocity_observed",
    "unavailable",
]
MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 = 1.0


class MainWingRouteStageEvidence(BaseModel):
    stage: StageType
    status: StageStatusType
    evidence_kind: EvidenceKindType
    artifact_path: str | None = None
    observed: Dict[str, Any] = Field(default_factory=dict)
    blockers: List[str] = Field(default_factory=list)


class MainWingRouteReadinessReport(BaseModel):
    schema_version: Literal["main_wing_route_readiness.v1"] = (
        "main_wing_route_readiness.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    target_route: Literal["real_main_wing_vsp_or_esp_to_gmsh_to_su2"] = (
        "real_main_wing_vsp_or_esp_to_gmsh_to_su2"
    )
    overall_status: OverallStatusType
    hpa_standard_velocity_mps: float = 6.5
    observed_velocity_mps: float | None = None
    hpa_standard_flow_status: HPAFlowStatusType
    stages: List[MainWingRouteStageEvidence]
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


def _default_report_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "reports"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _budget_from_report_path(path: Path, directory_prefix: str) -> int | None:
    suffix = path.parent.name.removeprefix(directory_prefix)
    return int(suffix) if suffix.isdigit() else None


def _load_latest_solver_budget_probe(
    root: Path,
    *,
    directory_prefix: str,
) -> tuple[Path | None, dict[str, Any] | None]:
    selected_budget: int | None = None
    selected_path: Path | None = None
    selected_payload: dict[str, Any] | None = None
    for report_path in sorted(
        root.glob(f"{directory_prefix}*/main_wing_real_solver_smoke_probe.v1.json")
    ):
        payload = _load_json(report_path)
        if not isinstance(payload, dict):
            continue
        budget = _int_or_none(payload.get("runtime_max_iterations"))
        if budget is None:
            budget = _budget_from_report_path(report_path, directory_prefix)
        if budget is None:
            continue
        if selected_budget is None or budget > selected_budget:
            selected_budget = budget
            selected_path = report_path
            selected_payload = payload
    return selected_path, selected_payload


def _blocking_reasons(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    reasons = payload.get("blocking_reasons", [])
    return [str(reason) for reason in reasons] if isinstance(reasons, list) else []


def _engineering_flags(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    flags = payload.get("engineering_flags", [])
    return [str(flag) for flag in flags] if isinstance(flags, list) else []


def _real_su2_stage_blockers(payload: dict[str, Any] | None) -> list[str]:
    solver_stage_blockers = {"main_wing_solver_not_run", "convergence_gate_not_run"}
    return [
        reason
        for reason in _blocking_reasons(payload)
        if reason not in solver_stage_blockers
    ]


def _stage(
    *,
    stage: StageType,
    status: StageStatusType,
    evidence_kind: EvidenceKindType,
    artifact_path: Path | None,
    observed: dict[str, Any],
    blockers: list[str],
) -> MainWingRouteStageEvidence:
    return MainWingRouteStageEvidence(
        stage=stage,
        status=status,
        evidence_kind=evidence_kind,
        artifact_path=None if artifact_path is None else str(artifact_path),
        observed=observed,
        blockers=blockers,
    )


def _flow_status(su2_runtime_handoff: dict[str, Any] | None) -> tuple[HPAFlowStatusType, float | None]:
    runtime = su2_runtime_handoff.get("runtime", {}) if isinstance(su2_runtime_handoff, dict) else {}
    velocity = runtime.get("velocity_mps") if isinstance(runtime, dict) else None
    if not isinstance(velocity, (int, float)):
        return "unavailable", None
    observed = float(velocity)
    if abs(observed - 6.5) <= 1.0e-9:
        return "hpa_standard_6p5_observed", observed
    return "legacy_or_nonstandard_velocity_observed", observed


def _solver_probe_executed(payload: dict[str, Any] | None) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("solver_execution_status") == "solver_executed"
    )


def _solver_probe_blocked(payload: dict[str, Any] | None) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("solver_execution_status")
        in {"solver_failed", "solver_timeout", "solver_unavailable", "blocked_before_solver"}
    )


def _solver_probe_lift_acceptance_status(
    payload: dict[str, Any] | None,
) -> str:
    if not isinstance(payload, dict):
        return "not_evaluated"
    reported_status = payload.get("main_wing_lift_acceptance_status")
    if reported_status in {"pass", "fail", "not_evaluated"}:
        return str(reported_status)
    velocity = payload.get("observed_velocity_mps")
    coefficients = payload.get("final_coefficients", {})
    cl = coefficients.get("cl") if isinstance(coefficients, dict) else None
    if not isinstance(velocity, (int, float)) or abs(float(velocity) - 6.5) > 1.0e-9:
        return "not_evaluated"
    if not isinstance(cl, (int, float)):
        return "not_evaluated"
    return "pass" if float(cl) > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 else "fail"


def _solver_probe_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "solver_execution_status": (
            None if payload is None else payload.get("solver_execution_status")
        )
        or "not_run",
        "run_status": None if payload is None else payload.get("run_status"),
        "convergence_gate_status": (
            None if payload is None else payload.get("convergence_gate_status")
        ),
        "convergence_comparability_level": (
            None if payload is None else payload.get("convergence_comparability_level")
        ),
        "final_iteration": None if payload is None else payload.get("final_iteration"),
        "runtime_max_iterations": (
            None if payload is None else payload.get("runtime_max_iterations")
        ),
        "final_coefficients": (
            {} if payload is None else payload.get("final_coefficients", {})
        ),
        "observed_velocity_mps": (
            None if payload is None else payload.get("observed_velocity_mps")
        ),
        "reference_geometry_status": (
            None if payload is None else payload.get("reference_geometry_status")
        ),
        "solver_log_quality_metrics": (
            {} if payload is None else payload.get("solver_log_quality_metrics", {})
        ),
        "main_wing_lift_acceptance_status": _solver_probe_lift_acceptance_status(
            payload
        ),
        "minimum_acceptable_cl": (
            MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
            if _solver_probe_lift_acceptance_status(payload) != "not_evaluated"
            else None
        ),
    }


def _geometry_provenance_status(payload: dict[str, Any] | None) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("geometry_provenance_status") == "provenance_available"
        else "blocked"
    )


def _geometry_provenance_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "geometry_provenance_status": (
            None if payload is None else payload.get("geometry_provenance_status")
        ),
        "selected_geom_id": None if payload is None else payload.get("selected_geom_id"),
        "selected_geom_name": (
            None if payload is None else payload.get("selected_geom_name")
        ),
        "installation_incidence_deg": (
            None if payload is None else payload.get("installation_incidence_deg")
        ),
        "section_count": None if payload is None else payload.get("section_count"),
        "twist_summary": {} if payload is None else payload.get("twist_summary", {}),
        "airfoil_summary": {} if payload is None else payload.get("airfoil_summary", {}),
        "alpha_zero_interpretation": (
            None if payload is None else payload.get("alpha_zero_interpretation")
        ),
    }


def _geometry_provenance_blockers(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    if payload.get("geometry_provenance_status") == "provenance_available":
        return []
    error = payload.get("error")
    if isinstance(error, str) and error:
        return [f"main_wing_geometry_provenance_missing: {error}"]
    return ["main_wing_geometry_provenance_missing"]


def _reference_gate_status(payload: dict[str, Any] | None) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return "pass" if payload.get("reference_gate_status") == "pass" else "blocked"


def _reference_gate_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"reference_gate_status": None}
    applied_reference = payload.get("applied_reference", {})
    openvsp_reference = payload.get("openvsp_reference", {})
    return {
        "reference_gate_status": payload.get("reference_gate_status"),
        "observed_velocity_mps": payload.get("observed_velocity_mps"),
        "applied_ref_area_m2": (
            applied_reference.get("ref_area")
            if isinstance(applied_reference, dict)
            else None
        ),
        "applied_ref_length_m": (
            applied_reference.get("ref_length")
            if isinstance(applied_reference, dict)
            else None
        ),
        "openvsp_sref_m2": (
            openvsp_reference.get("ref_area")
            if isinstance(openvsp_reference, dict)
            else None
        ),
        "openvsp_cref_m": (
            openvsp_reference.get("ref_length")
            if isinstance(openvsp_reference, dict)
            else None
        ),
        "derived_full_span_m": payload.get("derived_full_span_m"),
        "derived_full_span_method": payload.get("derived_full_span_method"),
    }


def _su2_force_marker_audit_status(payload: dict[str, Any] | None) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return "pass" if payload.get("audit_status") in {"pass", "warn"} else "blocked"


def _su2_force_marker_audit_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "audit_status": None if payload is None else payload.get("audit_status"),
        "marker_contract": {} if payload is None else payload.get("marker_contract", {}),
        "cfg_markers": {} if payload is None else payload.get("cfg_markers", {}),
        "flow_reference_observed": (
            {} if payload is None else payload.get("flow_reference_observed", {})
        ),
        "engineering_flags": (
            [] if payload is None else payload.get("engineering_flags", [])
        ),
    }


def _surface_force_output_audit_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return "pass" if payload.get("audit_status") in {"pass", "warn"} else "blocked"


def _surface_force_output_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "audit_status": None if payload is None else payload.get("audit_status"),
        "solver_execution_observed": (
            {} if payload is None else payload.get("solver_execution_observed", {})
        ),
        "expected_outputs_from_log": (
            {} if payload is None else payload.get("expected_outputs_from_log", {})
        ),
        "artifact_retention_observed": (
            {} if payload is None else payload.get("artifact_retention_observed", {})
        ),
        "force_breakdown_observed": (
            {} if payload is None else payload.get("force_breakdown_observed", {})
        ),
        "panel_reference_observed": (
            {} if payload is None else payload.get("panel_reference_observed", {})
        ),
        "engineering_flags": (
            [] if payload is None else payload.get("engineering_flags", [])
        ),
    }


def _vspaero_panel_reference_status(payload: dict[str, Any] | None) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("panel_reference_status") == "panel_reference_available"
        else "blocked"
    )


def _vspaero_panel_reference_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
    selected_case = payload.get("selected_case", {}) if isinstance(payload, dict) else {}
    setup_reference = (
        payload.get("setup_reference", {}) if isinstance(payload, dict) else {}
    )
    return {
        "panel_reference_status": (
            None if payload is None else payload.get("panel_reference_status")
        ),
        "hpa_standard_flow_status": (
            None if payload is None else payload.get("hpa_standard_flow_status")
        ),
        "lift_acceptance_status": (
            None if payload is None else payload.get("lift_acceptance_status")
        ),
        "minimum_acceptable_cl": (
            None if payload is None else payload.get("minimum_acceptable_cl")
        ),
        "alpha_deg": (
            selected_case.get("AoA") if isinstance(selected_case, dict) else None
        ),
        "cltot": (
            selected_case.get("CLtot") if isinstance(selected_case, dict) else None
        ),
        "cdtot": (
            selected_case.get("CDtot") if isinstance(selected_case, dict) else None
        ),
        "velocity_mps": (
            setup_reference.get("Vinf") if isinstance(setup_reference, dict) else None
        ),
        "su2_smoke_comparison": (
            {} if payload is None else payload.get("su2_smoke_comparison", {})
        ),
        "engineering_flags": (
            [] if payload is None else payload.get("engineering_flags", [])
        ),
    }


def _vspaero_panel_reference_blockers(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    if payload.get("panel_reference_status") == "panel_reference_available":
        return []
    flags = [
        str(flag)
        for flag in payload.get("engineering_flags", [])
        if isinstance(flag, str) and flag
    ]
    status = payload.get("panel_reference_status")
    if isinstance(status, str) and status:
        return list(dict.fromkeys([status, *flags]))
    return list(dict.fromkeys(["vspaero_panel_reference_missing", *flags]))


def _lift_acceptance_stage_status(payload: dict[str, Any] | None) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("diagnostic_status") == "lift_acceptance_passed"
        else "blocked"
    )


def _lift_acceptance_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "diagnostic_status": None if payload is None else payload.get("diagnostic_status"),
        "minimum_acceptable_cl": (
            None if payload is None else payload.get("minimum_acceptable_cl")
        ),
        "selected_solver_report": (
            {} if payload is None else payload.get("selected_solver_report", {})
        ),
        "panel_reference_observed": (
            {} if payload is None else payload.get("panel_reference_observed", {})
        ),
        "flow_condition_observed": (
            {} if payload is None else payload.get("flow_condition_observed", {})
        ),
        "reference_observed": (
            {} if payload is None else payload.get("reference_observed", {})
        ),
        "lift_metrics": {} if payload is None else payload.get("lift_metrics", {}),
        "lift_gap_diagnostics": (
            {} if payload is None else payload.get("lift_gap_diagnostics", {})
        ),
        "root_cause_candidates": (
            [] if payload is None else payload.get("root_cause_candidates", [])
        ),
        "engineering_flags": (
            [] if payload is None else payload.get("engineering_flags", [])
        ),
    }


def _lift_acceptance_blockers(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    status = payload.get("diagnostic_status")
    flags = [
        str(flag)
        for flag in payload.get("engineering_flags", [])
        if isinstance(flag, str) and flag
    ]
    if status == "lift_acceptance_passed":
        return []
    if status == "lift_margin_observed_without_convergence":
        return list(
            dict.fromkeys(
                ["main_wing_lift_margin_observed_without_convergence", *flags]
            )
        )
    if status == "lift_deficit_observed":
        return list(dict.fromkeys(["main_wing_cl_below_expected_lift", *flags]))
    if status == "nonstandard_flow_observed":
        return list(dict.fromkeys(["nonstandard_flow_condition", *flags]))
    if status == "insufficient_solver_evidence":
        return list(
            dict.fromkeys(
                ["main_wing_lift_acceptance_insufficient_solver_evidence", *flags]
            )
        )
    return list(dict.fromkeys([f"main_wing_lift_acceptance_{status}", *flags]))


def _panel_su2_lift_gap_debug_status(payload: dict[str, Any] | None) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "blocked"
        if payload.get("debug_status") == "insufficient_evidence"
        else "pass"
    )


def _panel_su2_lift_gap_debug_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "debug_status": None if payload is None else payload.get("debug_status"),
        "flow_reference_alignment": (
            {} if payload is None else payload.get("flow_reference_alignment", {})
        ),
        "panel_reference_decomposition": (
            {} if payload is None else payload.get("panel_reference_decomposition", {})
        ),
        "su2_force_breakdown": (
            {} if payload is None else payload.get("su2_force_breakdown", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "primary_hypotheses": (
            [] if payload is None else payload.get("primary_hypotheses", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _panel_su2_lift_gap_debug_blockers(
    payload: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(payload, dict):
        return []
    if payload.get("debug_status") == "insufficient_evidence":
        return ["panel_su2_lift_gap_debug_insufficient_evidence"]
    return []


def _su2_mesh_normal_audit_status(payload: dict[str, Any] | None) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return "pass" if payload.get("normal_audit_status") == "pass" else "blocked"


def _su2_mesh_normal_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "normal_audit_status": (
            None if payload is None else payload.get("normal_audit_status")
        ),
        "main_wing_surface_entity_count": (
            None if payload is None else payload.get("main_wing_surface_entity_count")
        ),
        "surface_triangle_count": (
            None if payload is None else payload.get("surface_triangle_count")
        ),
        "normal_orientation": (
            {} if payload is None else payload.get("normal_orientation", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _panel_wake_semantics_audit_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "blocked"
        if payload.get("audit_status") == "insufficient_evidence"
        else "pass"
    )


def _panel_wake_semantics_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "audit_status": None if payload is None else payload.get("audit_status"),
        "panel_wake_observed": (
            {} if payload is None else payload.get("panel_wake_observed", {})
        ),
        "su2_semantics_observed": (
            {} if payload is None else payload.get("su2_semantics_observed", {})
        ),
        "normal_audit_observed": (
            {} if payload is None else payload.get("normal_audit_observed", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _mesh_quality_hotspot_audit_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return "blocked" if payload.get("hotspot_status") == "blocked" else "pass"


def _mesh_quality_hotspot_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "hotspot_status": None if payload is None else payload.get("hotspot_status"),
        "quality_summary": (
            {} if payload is None else payload.get("quality_summary", {})
        ),
        "worst_tet_sample_partition": (
            {} if payload is None else payload.get("worst_tet_sample_partition", {})
        ),
        "station_seam_overlap_observed": (
            {}
            if payload is None
            else payload.get("station_seam_overlap_observed", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _su2_surface_topology_audit_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return "blocked" if payload.get("audit_status") == "blocked" else "pass"


def _su2_surface_topology_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "audit_status": None if payload is None else payload.get("audit_status"),
        "edge_topology_observed": (
            {} if payload is None else payload.get("edge_topology_observed", {})
        ),
        "area_evidence_observed": (
            {} if payload is None else payload.get("area_evidence_observed", {})
        ),
        "bbox_observed": {} if payload is None else payload.get("bbox_observed", {}),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _su2_topology_defect_localization_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "blocked"
        if payload.get("localization_status") == "blocked"
        else "pass"
    )


def _su2_topology_defect_localization_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "localization_status": (
            None if payload is None else payload.get("localization_status")
        ),
        "defect_summary": (
            {} if payload is None else payload.get("defect_summary", {})
        ),
        "station_summary": (
            [] if payload is None else payload.get("station_summary", [])
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _openvsp_defect_station_audit_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "blocked"
        if payload.get("station_alignment_status") == "blocked"
        else "pass"
    )


def _openvsp_defect_station_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "station_alignment_status": (
            None if payload is None else payload.get("station_alignment_status")
        ),
        "alignment_summary": (
            {} if payload is None else payload.get("alignment_summary", {})
        ),
        "station_mappings": (
            [] if payload is None else payload.get("station_mappings", [])
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _gmsh_defect_entity_trace_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return "blocked" if payload.get("trace_status") == "blocked" else "pass"


def _gmsh_defect_entity_trace_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "trace_status": None if payload is None else payload.get("trace_status"),
        "trace_summary": (
            {} if payload is None else payload.get("trace_summary", {})
        ),
        "edge_traces": [] if payload is None else payload.get("edge_traces", []),
        "station_traces": (
            [] if payload is None else payload.get("station_traces", [])
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _gmsh_curve_station_rebuild_audit_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "blocked"
        if payload.get("curve_station_rebuild_status") == "blocked"
        else "pass"
    )


def _gmsh_curve_station_rebuild_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "curve_station_rebuild_status": (
            None if payload is None else payload.get("curve_station_rebuild_status")
        ),
        "match_summary": (
            {} if payload is None else payload.get("match_summary", {})
        ),
        "curve_matches": (
            [] if payload is None else payload.get("curve_matches", [])
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _openvsp_section_station_topology_fixture_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return "blocked" if payload.get("topology_fixture_status") == "blocked" else "pass"


def _openvsp_section_station_topology_fixture_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "topology_fixture_status": (
            None if payload is None else payload.get("topology_fixture_status")
        ),
        "fixture_summary": (
            {} if payload is None else payload.get("fixture_summary", {})
        ),
        "station_fixture_cases": (
            [] if payload is None else payload.get("station_fixture_cases", [])
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_repair_decision_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("repair_decision_status") == "no_station_seam_repair_required"
        else "blocked"
    )


def _station_seam_repair_decision_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "repair_decision_status": (
            None if payload is None else payload.get("repair_decision_status")
        ),
        "topology_fixture_observed": (
            {} if payload is None else payload.get("topology_fixture_observed", {})
        ),
        "solver_context_observed": (
            {} if payload is None else payload.get("solver_context_observed", {})
        ),
        "decision_rationale": (
            [] if payload is None else payload.get("decision_rationale", [])
        ),
        "repair_candidate_requirements": (
            [] if payload is None else payload.get("repair_candidate_requirements", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_brep_hotspot_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("probe_status") == "brep_hotspot_captured_station_edges_valid"
        else "blocked"
    )


def _station_seam_brep_hotspot_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "probe_status": None if payload is None else payload.get("probe_status"),
        "requested_curve_tags": (
            [] if payload is None else payload.get("requested_curve_tags", [])
        ),
        "requested_surface_tags": (
            [] if payload is None else payload.get("requested_surface_tags", [])
        ),
        "brep_hotspot_summary": (
            {} if payload is None else payload.get("brep_hotspot_summary", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_same_parameter_feasibility_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("feasibility_status") == "same_parameter_repair_recovered"
        else "blocked"
    )


def _station_seam_same_parameter_feasibility_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "feasibility_status": (
            None if payload is None else payload.get("feasibility_status")
        ),
        "baseline_summary": (
            {} if payload is None else payload.get("baseline_summary", {})
        ),
        "attempt_summary": (
            {} if payload is None else payload.get("attempt_summary", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_shape_fix_feasibility_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("feasibility_status") == "shape_fix_repair_recovered"
        else "blocked"
    )


def _station_seam_shape_fix_feasibility_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "feasibility_status": (
            None if payload is None else payload.get("feasibility_status")
        ),
        "baseline_summary": (
            {} if payload is None else payload.get("baseline_summary", {})
        ),
        "attempt_summary": (
            {} if payload is None else payload.get("attempt_summary", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_export_source_audit_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "blocked"
        if payload.get("audit_status")
        == "single_rule_internal_station_export_source_confirmed"
        else "pass"
        if payload.get("audit_status") == "export_source_audit_captured"
        else "blocked"
    )


def _station_seam_export_source_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "audit_status": None if payload is None else payload.get("audit_status"),
        "csm_summary": {} if payload is None else payload.get("csm_summary", {}),
        "target_station_mappings": (
            [] if payload is None else payload.get("target_station_mappings", [])
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_export_strategy_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("probe_status")
        == "export_strategy_candidate_materialized_needs_brep_validation"
        else "blocked"
    )


def _station_seam_export_strategy_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate_summaries: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for candidate in payload.get("candidate_reports", []):
            if not isinstance(candidate, dict):
                continue
            materialization = candidate.get("materialization", {})
            topology = materialization.get("topology", {}) if isinstance(materialization, dict) else {}
            candidate_summaries.append(
                {
                    "candidate": candidate.get("candidate"),
                    "apply_union": candidate.get("apply_union"),
                    "all_targets_exported_as_rule_boundaries": candidate.get(
                        "all_targets_exported_as_rule_boundaries"
                    ),
                    "target_boundary_duplication_count": candidate.get(
                        "target_boundary_duplication_count"
                    ),
                    "span_y_bounds_preserved": candidate.get(
                        "span_y_bounds_preserved"
                    ),
                    "materialization_status": materialization.get("status")
                    if isinstance(materialization, dict)
                    else None,
                    "body_count": topology.get("body_count")
                    if isinstance(topology, dict)
                    else None,
                    "volume_count": topology.get("volume_count")
                    if isinstance(topology, dict)
                    else None,
                    "surface_count": topology.get("surface_count")
                    if isinstance(topology, dict)
                    else None,
                    "bbox": topology.get("bbox") if isinstance(topology, dict) else None,
                }
            )
    return {
        "probe_status": None if payload is None else payload.get("probe_status"),
        "materialization_requested": (
            None if payload is None else payload.get("materialization_requested")
        ),
        "target_rule_section_indices": (
            [] if payload is None else payload.get("target_rule_section_indices", [])
        ),
        "candidate_summaries": candidate_summaries,
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_internal_cap_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("probe_status")
        == "split_candidate_no_internal_caps_detected_needs_mesh_handoff_probe"
        else "blocked"
    )


def _station_seam_internal_cap_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate_summaries: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for inspection in payload.get("candidate_inspections", []):
            if not isinstance(inspection, dict):
                continue
            candidate_summaries.append(
                {
                    "candidate": inspection.get("candidate"),
                    "candidate_mesh_handoff_ready": inspection.get(
                        "candidate_mesh_handoff_ready"
                    ),
                    "body_count": inspection.get("body_count"),
                    "volume_count": inspection.get("volume_count"),
                    "surface_count": inspection.get("surface_count"),
                    "span_y_bounds_preserved": inspection.get(
                        "span_y_bounds_preserved"
                    ),
                    "target_station_face_groups": inspection.get(
                        "target_station_face_groups", []
                    ),
                }
            )
    return {
        "probe_status": None if payload is None else payload.get("probe_status"),
        "target_station_y_m": (
            [] if payload is None else payload.get("target_station_y_m", [])
        ),
        "station_plane_tolerance": (
            None if payload is None else payload.get("station_plane_tolerance")
        ),
        "candidate_summaries": candidate_summaries,
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_profile_resample_strategy_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("probe_status")
        == "profile_resample_candidate_materialized_needs_brep_validation"
        else "blocked"
    )


def _station_seam_profile_resample_strategy_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate = (
        payload.get("candidate_report", {}) if isinstance(payload, dict) else {}
    )
    return {
        "probe_status": None if payload is None else payload.get("probe_status"),
        "source_profile_point_counts": (
            [] if payload is None else payload.get("source_profile_point_counts", [])
        ),
        "target_profile_point_count": (
            None if payload is None else payload.get("target_profile_point_count")
        ),
        "target_station_y_m": (
            [] if payload is None else payload.get("target_station_y_m", [])
        ),
        "candidate_summary": {
            "candidate": candidate.get("candidate") if isinstance(candidate, dict) else None,
            "materialization_status": (
                candidate.get("materialization_status")
                if isinstance(candidate, dict)
                else None
            ),
            "body_count": candidate.get("body_count") if isinstance(candidate, dict) else None,
            "volume_count": (
                candidate.get("volume_count") if isinstance(candidate, dict) else None
            ),
            "surface_count": (
                candidate.get("surface_count") if isinstance(candidate, dict) else None
            ),
            "span_y_bounds_preserved": (
                candidate.get("span_y_bounds_preserved")
                if isinstance(candidate, dict)
                else None
            ),
            "target_station_face_groups": (
                candidate.get("target_station_face_groups", [])
                if isinstance(candidate, dict)
                else []
            ),
        },
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_profile_resample_brep_validation_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("probe_status")
        == "profile_resample_candidate_station_brep_edges_valid"
        else "blocked"
    )


def _station_seam_profile_resample_brep_validation_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    target_selection = (
        payload.get("target_selection", {}) if isinstance(payload, dict) else {}
    )
    target_selection = target_selection if isinstance(target_selection, dict) else {}
    hotspot_summary = (
        payload.get("hotspot_summary", {}) if isinstance(payload, dict) else {}
    )
    hotspot_summary = hotspot_summary if isinstance(hotspot_summary, dict) else {}
    return {
        "probe_status": None if payload is None else payload.get("probe_status"),
        "candidate_step_path": (
            None if payload is None else payload.get("candidate_step_path")
        ),
        "target_station_y_m": (
            [] if payload is None else payload.get("target_station_y_m", [])
        ),
        "selection_mode": target_selection.get("selection_mode"),
        "source_fixture_tags_replayed": target_selection.get(
            "source_fixture_tags_replayed"
        ),
        "selected_curve_tags": target_selection.get("selected_curve_tags", []),
        "selected_surface_tags": target_selection.get("selected_surface_tags", []),
        "station_edge_check_count": hotspot_summary.get("station_edge_check_count"),
        "shape_valid_exact": hotspot_summary.get("shape_valid_exact"),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_profile_resample_repair_feasibility_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("feasibility_status")
        == "profile_resample_station_shape_fix_repair_recovered"
        else "blocked"
    )


def _station_seam_profile_resample_repair_feasibility_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    baseline_summary = (
        payload.get("baseline_summary", {}) if isinstance(payload, dict) else {}
    )
    baseline_summary = baseline_summary if isinstance(baseline_summary, dict) else {}
    attempt_summary = (
        payload.get("attempt_summary", {}) if isinstance(payload, dict) else {}
    )
    attempt_summary = attempt_summary if isinstance(attempt_summary, dict) else {}
    return {
        "feasibility_status": (
            None if payload is None else payload.get("feasibility_status")
        ),
        "candidate_step_path": (
            None if payload is None else payload.get("candidate_step_path")
        ),
        "target_edge_count": baseline_summary.get("target_edge_count"),
        "all_station_checks_pass": baseline_summary.get("all_station_checks_pass"),
        "attempt_count": attempt_summary.get("attempt_count"),
        "recovered_attempt_count": attempt_summary.get("recovered_attempt_count"),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_profile_parametrization_audit_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return "blocked" if payload.get("audit_status") == "blocked" else "pass"


def _station_seam_profile_parametrization_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "audit_status": None if payload is None else payload.get("audit_status"),
        "target_station_y_m": (
            [] if payload is None else payload.get("target_station_y_m", [])
        ),
        "source_profile_point_counts": (
            [] if payload is None else payload.get("source_profile_point_counts", [])
        ),
        "candidate_profile_point_counts": (
            [] if payload is None else payload.get("candidate_profile_point_counts", [])
        ),
        "station_fragment_summary": (
            {} if payload is None else payload.get("station_fragment_summary", {})
        ),
        "edge_failure_summary": (
            {} if payload is None else payload.get("edge_failure_summary", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_side_aware_parametrization_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("probe_status")
        == "side_aware_parametrization_candidate_materialized_needs_brep_validation"
        else "blocked"
    )


def _station_seam_side_aware_parametrization_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate = payload.get("candidate_report", {}) if isinstance(payload, dict) else {}
    candidate = candidate if isinstance(candidate, dict) else {}
    return {
        "probe_status": None if payload is None else payload.get("probe_status"),
        "source_profile_point_counts": (
            [] if payload is None else payload.get("source_profile_point_counts", [])
        ),
        "candidate_profile_point_counts": (
            [] if payload is None else payload.get("candidate_profile_point_counts", [])
        ),
        "target_station_y_m": (
            [] if payload is None else payload.get("target_station_y_m", [])
        ),
        "side_parametrization_summary": (
            {} if payload is None else payload.get("side_parametrization_summary", {})
        ),
        "candidate_summary": {
            "candidate": candidate.get("candidate"),
            "materialization_status": candidate.get("materialization_status"),
            "body_count": candidate.get("body_count"),
            "volume_count": candidate.get("volume_count"),
            "surface_count": candidate.get("surface_count"),
            "span_y_bounds_preserved": candidate.get("span_y_bounds_preserved"),
            "target_station_face_groups": candidate.get("target_station_face_groups", []),
        },
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_side_aware_brep_validation_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("probe_status")
        == "side_aware_candidate_station_brep_edges_valid"
        else "blocked"
    )


def _station_seam_side_aware_brep_validation_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    hotspot_summary = (
        payload.get("hotspot_summary", {}) if isinstance(payload, dict) else {}
    )
    hotspot_summary = hotspot_summary if isinstance(hotspot_summary, dict) else {}
    target_selection = (
        payload.get("target_selection", {}) if isinstance(payload, dict) else {}
    )
    target_selection = target_selection if isinstance(target_selection, dict) else {}
    edge_checks = (
        payload.get("station_edge_checks", []) if isinstance(payload, dict) else []
    )
    edge_checks = [item for item in edge_checks if isinstance(item, dict)]
    return {
        "probe_status": None if payload is None else payload.get("probe_status"),
        "candidate_step_path": (
            None if payload is None else payload.get("candidate_step_path")
        ),
        "target_station_y_m": (
            [] if payload is None else payload.get("target_station_y_m", [])
        ),
        "selection_mode": target_selection.get("selection_mode"),
        "source_fixture_tags_replayed": target_selection.get(
            "source_fixture_tags_replayed"
        ),
        "selected_curve_tags": target_selection.get("selected_curve_tags", []),
        "selected_surface_tags": target_selection.get("selected_surface_tags", []),
        "station_edge_check_count": hotspot_summary.get("station_edge_check_count"),
        "face_check_count": hotspot_summary.get("face_check_count"),
        "shape_valid_exact": hotspot_summary.get("shape_valid_exact"),
        "pcurve_inconsistent_edge_count": sum(
            1 for item in edge_checks if item.get("pcurve_checks_complete") is not True
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_side_aware_pcurve_residual_diagnostic_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("diagnostic_status")
        == "side_aware_station_pcurve_residuals_sampled_clean"
        else "blocked"
    )


def _station_seam_side_aware_pcurve_residual_diagnostic_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    target_selection = (
        payload.get("target_selection", {}) if isinstance(payload, dict) else {}
    )
    target_selection = target_selection if isinstance(target_selection, dict) else {}
    return {
        "diagnostic_status": (
            None if payload is None else payload.get("diagnostic_status")
        ),
        "candidate_step_path": (
            None if payload is None else payload.get("candidate_step_path")
        ),
        "target_station_y_m": (
            [] if payload is None else payload.get("target_station_y_m", [])
        ),
        "selection_mode": target_selection.get("selection_mode"),
        "source_fixture_tags_replayed": target_selection.get(
            "source_fixture_tags_replayed"
        ),
        "sample_count": None if payload is None else payload.get("sample_count"),
        "residual_summary": (
            {} if payload is None else payload.get("residual_summary", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_side_aware_metadata_repair_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("metadata_repair_status")
        == "side_aware_station_metadata_repair_recovered"
        else "blocked"
    )


def _station_seam_side_aware_metadata_repair_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    target_edges = payload.get("target_edges", []) if isinstance(payload, dict) else []
    target_edges = [item for item in target_edges if isinstance(item, dict)]
    return {
        "metadata_repair_status": (
            None if payload is None else payload.get("metadata_repair_status")
        ),
        "candidate_step_path": (
            None if payload is None else payload.get("candidate_step_path")
        ),
        "target_edge_count": len(target_edges),
        "residual_context_summary": (
            {} if payload is None else payload.get("residual_context_summary", {})
        ),
        "same_parameter_attempt_summary": (
            {} if payload is None else payload.get("same_parameter_attempt_summary", {})
        ),
        "shape_fix_attempt_summary": (
            {} if payload is None else payload.get("shape_fix_attempt_summary", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_side_aware_pcurve_metadata_builder_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("metadata_builder_status")
        == "side_aware_station_pcurve_metadata_builder_recovered"
        else "blocked"
    )


def _station_seam_side_aware_pcurve_metadata_builder_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    target_edges = payload.get("target_edges", []) if isinstance(payload, dict) else []
    target_edges = [item for item in target_edges if isinstance(item, dict)]
    return {
        "metadata_builder_status": (
            None if payload is None else payload.get("metadata_builder_status")
        ),
        "candidate_step_path": (
            None if payload is None else payload.get("candidate_step_path")
        ),
        "target_edge_count": len(target_edges),
        "baseline_summary": (
            {} if payload is None else payload.get("baseline_summary", {})
        ),
        "strategy_attempt_summary": (
            {} if payload is None else payload.get("strategy_attempt_summary", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_side_aware_projected_pcurve_builder_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("projected_builder_status")
        == "side_aware_station_projected_pcurve_builder_recovered"
        else "blocked"
    )


def _station_seam_side_aware_projected_pcurve_builder_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    target_edges = payload.get("target_edges", []) if isinstance(payload, dict) else []
    target_edges = [item for item in target_edges if isinstance(item, dict)]
    return {
        "projected_builder_status": (
            None if payload is None else payload.get("projected_builder_status")
        ),
        "candidate_step_path": (
            None if payload is None else payload.get("candidate_step_path")
        ),
        "target_edge_count": len(target_edges),
        "strategy_attempt_summary": (
            {} if payload is None else payload.get("strategy_attempt_summary", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_side_aware_export_opcode_variant_probe_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "pass"
        if payload.get("opcode_variant_status")
        == "side_aware_export_opcode_variant_recovered"
        else "blocked"
    )


def _station_seam_side_aware_export_opcode_variant_probe_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "opcode_variant_status": (
            None if payload is None else payload.get("opcode_variant_status")
        ),
        "source_csm_path": None if payload is None else payload.get("source_csm_path"),
        "variants": [] if payload is None else payload.get("variants", []),
        "variant_summary": (
            {} if payload is None else payload.get("variant_summary", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def _station_seam_export_metadata_source_audit_status(
    payload: dict[str, Any] | None,
) -> StageStatusType:
    if not isinstance(payload, dict):
        return "not_run"
    return (
        "blocked"
        if payload.get("audit_status")
        in {
            "export_metadata_generation_source_boundary_captured",
            "export_metadata_generation_source_boundary_incomplete",
            "blocked",
        }
        else "not_run"
    )


def _station_seam_export_metadata_source_audit_observed(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "audit_status": None if payload is None else payload.get("audit_status"),
        "source_boundary": (
            {} if payload is None else payload.get("source_boundary", {})
        ),
        "current_negative_controls": (
            {} if payload is None else payload.get("current_negative_controls", {})
        ),
        "external_source_inventory": (
            {} if payload is None else payload.get("external_source_inventory", {})
        ),
        "engineering_findings": (
            [] if payload is None else payload.get("engineering_findings", [])
        ),
        "next_actions": [] if payload is None else payload.get("next_actions", []),
    }


def build_main_wing_route_readiness_report(
    *,
    report_root: Path | None = None,
) -> MainWingRouteReadinessReport:
    root = _default_report_root() if report_root is None else report_root
    real_geometry_path = (
        root
        / "main_wing_esp_rebuilt_geometry_smoke"
        / "main_wing_esp_rebuilt_geometry_smoke.v1.json"
    )
    geometry_provenance_path = (
        root
        / "main_wing_geometry_provenance_probe"
        / "main_wing_geometry_provenance_probe.v1.json"
    )
    vspaero_panel_reference_path = (
        root
        / "main_wing_vspaero_panel_reference_probe"
        / "main_wing_vspaero_panel_reference_probe.v1.json"
    )
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    synthetic_mesh_path = (
        root / "main_wing_mesh_handoff_smoke" / "main_wing_mesh_handoff_smoke.v1.json"
    )
    synthetic_su2_path = (
        root / "main_wing_su2_handoff_smoke" / "main_wing_su2_handoff_smoke.v1.json"
    )
    real_su2_path = (
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json"
    )
    openvsp_reference_su2_path = (
        root
        / "main_wing_openvsp_reference_su2_handoff_probe"
        / "main_wing_openvsp_reference_su2_handoff_probe.v1.json"
    )
    su2_force_marker_audit_path = (
        root
        / "main_wing_su2_force_marker_audit"
        / "main_wing_su2_force_marker_audit.v1.json"
    )
    surface_force_output_audit_path = (
        root
        / "main_wing_surface_force_output_audit"
        / "main_wing_surface_force_output_audit.v1.json"
    )
    openvsp_reference_geometry_gate_path = (
        root
        / "main_wing_openvsp_reference_geometry_gate"
        / "main_wing_reference_geometry_gate.v1.json"
    )
    openvsp_reference_solver_path = (
        root
        / "main_wing_openvsp_reference_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json"
    )
    reference_gate_path = (
        root
        / "main_wing_reference_geometry_gate"
        / "main_wing_reference_geometry_gate.v1.json"
    )
    solver_smoke_path = (
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json"
    )
    lift_acceptance_path = (
        root
        / "main_wing_lift_acceptance_diagnostic"
        / "main_wing_lift_acceptance_diagnostic.v1.json"
    )
    panel_su2_lift_gap_debug_path = (
        root
        / "main_wing_panel_su2_lift_gap_debug"
        / "main_wing_panel_su2_lift_gap_debug.v1.json"
    )
    su2_mesh_normal_audit_path = (
        root
        / "main_wing_su2_mesh_normal_audit"
        / "main_wing_su2_mesh_normal_audit.v1.json"
    )
    mesh_quality_hotspot_audit_path = (
        root
        / "main_wing_mesh_quality_hotspot_audit"
        / "main_wing_mesh_quality_hotspot_audit.v1.json"
    )
    panel_wake_semantics_audit_path = (
        root
        / "main_wing_panel_wake_semantics_audit"
        / "main_wing_panel_wake_semantics_audit.v1.json"
    )
    su2_surface_topology_audit_path = (
        root
        / "main_wing_su2_surface_topology_audit"
        / "main_wing_su2_surface_topology_audit.v1.json"
    )
    su2_topology_defect_localization_path = (
        root
        / "main_wing_su2_topology_defect_localization"
        / "main_wing_su2_topology_defect_localization.v1.json"
    )
    openvsp_defect_station_audit_path = (
        root
        / "main_wing_openvsp_defect_station_audit"
        / "main_wing_openvsp_defect_station_audit.v1.json"
    )
    gmsh_defect_entity_trace_path = (
        root
        / "main_wing_gmsh_defect_entity_trace"
        / "main_wing_gmsh_defect_entity_trace.v1.json"
    )
    gmsh_curve_station_rebuild_audit_path = (
        root
        / "main_wing_gmsh_curve_station_rebuild_audit"
        / "main_wing_gmsh_curve_station_rebuild_audit.v1.json"
    )
    openvsp_section_station_topology_fixture_path = (
        root
        / "main_wing_openvsp_section_station_topology_fixture"
        / "main_wing_openvsp_section_station_topology_fixture.v1.json"
    )
    station_seam_repair_decision_path = (
        root
        / "main_wing_station_seam_repair_decision"
        / "main_wing_station_seam_repair_decision.v1.json"
    )
    station_seam_brep_hotspot_probe_path = (
        root
        / "main_wing_station_seam_brep_hotspot_probe"
        / "main_wing_station_seam_brep_hotspot_probe.v1.json"
    )
    station_seam_same_parameter_feasibility_path = (
        root
        / "main_wing_station_seam_same_parameter_feasibility"
        / "main_wing_station_seam_same_parameter_feasibility.v1.json"
    )
    station_seam_shape_fix_feasibility_path = (
        root
        / "main_wing_station_seam_shape_fix_feasibility"
        / "main_wing_station_seam_shape_fix_feasibility.v1.json"
    )
    station_seam_export_source_audit_path = (
        root
        / "main_wing_station_seam_export_source_audit"
        / "main_wing_station_seam_export_source_audit.v1.json"
    )
    station_seam_export_strategy_probe_path = (
        root
        / "main_wing_station_seam_export_strategy_probe"
        / "main_wing_station_seam_export_strategy_probe.v1.json"
    )
    station_seam_internal_cap_probe_path = (
        root
        / "main_wing_station_seam_internal_cap_probe"
        / "main_wing_station_seam_internal_cap_probe.v1.json"
    )
    station_seam_profile_resample_strategy_probe_path = (
        root
        / "main_wing_station_seam_profile_resample_strategy_probe"
        / "main_wing_station_seam_profile_resample_strategy_probe.v1.json"
    )
    station_seam_profile_resample_brep_validation_probe_path = (
        root
        / "main_wing_station_seam_profile_resample_brep_validation_probe"
        / "main_wing_station_seam_profile_resample_brep_validation_probe.v1.json"
    )
    station_seam_profile_resample_repair_feasibility_probe_path = (
        root
        / "main_wing_station_seam_profile_resample_repair_feasibility_probe"
        / "main_wing_station_seam_profile_resample_repair_feasibility_probe.v1.json"
    )
    station_seam_profile_parametrization_audit_path = (
        root
        / "main_wing_station_seam_profile_parametrization_audit"
        / "main_wing_station_seam_profile_parametrization_audit.v1.json"
    )
    station_seam_side_aware_parametrization_probe_path = (
        root
        / "main_wing_station_seam_side_aware_parametrization_probe"
        / "main_wing_station_seam_side_aware_parametrization_probe.v1.json"
    )
    station_seam_side_aware_brep_validation_probe_path = (
        root
        / "main_wing_station_seam_side_aware_brep_validation_probe"
        / "main_wing_station_seam_side_aware_brep_validation_probe.v1.json"
    )
    station_seam_side_aware_pcurve_residual_diagnostic_path = (
        root
        / "main_wing_station_seam_side_aware_pcurve_residual_diagnostic"
        / "main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1.json"
    )
    station_seam_side_aware_metadata_repair_probe_path = (
        root
        / "main_wing_station_seam_side_aware_metadata_repair_probe"
        / "main_wing_station_seam_side_aware_metadata_repair_probe.v1.json"
    )
    station_seam_side_aware_pcurve_metadata_builder_probe_path = (
        root
        / "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe"
        / "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1.json"
    )
    station_seam_side_aware_projected_pcurve_builder_probe_path = (
        root
        / "main_wing_station_seam_side_aware_projected_pcurve_builder_probe"
        / "main_wing_station_seam_side_aware_projected_pcurve_builder_probe.v1.json"
    )
    station_seam_side_aware_export_opcode_variant_probe_path = (
        root
        / "main_wing_station_seam_side_aware_export_opcode_variant_probe"
        / "main_wing_station_seam_side_aware_export_opcode_variant_probe.v1.json"
    )
    station_seam_export_metadata_source_audit_path = (
        root
        / "main_wing_station_seam_export_metadata_source_audit"
        / "main_wing_station_seam_export_metadata_source_audit.v1.json"
    )
    synthetic_su2_runtime_path = (
        root
        / "main_wing_su2_handoff_smoke"
        / "artifacts"
        / "su2"
        / "alpha_0_materialization_smoke"
        / "su2_handoff.json"
    )

    real_geometry = _load_json(real_geometry_path)
    geometry_provenance = _load_json(geometry_provenance_path)
    vspaero_panel_reference = _load_json(vspaero_panel_reference_path)
    real_mesh = _load_json(real_mesh_path)
    synthetic_mesh = _load_json(synthetic_mesh_path)
    synthetic_su2 = _load_json(synthetic_su2_path)
    real_su2 = _load_json(real_su2_path)
    openvsp_reference_su2 = _load_json(openvsp_reference_su2_path)
    su2_force_marker_audit = _load_json(su2_force_marker_audit_path)
    surface_force_output_audit = _load_json(surface_force_output_audit_path)
    openvsp_reference_geometry_gate = _load_json(openvsp_reference_geometry_gate_path)
    openvsp_reference_solver = _load_json(openvsp_reference_solver_path)
    (
        openvsp_reference_solver_budget_path,
        openvsp_reference_solver_budget,
    ) = _load_latest_solver_budget_probe(
        root,
        directory_prefix="main_wing_openvsp_reference_solver_smoke_probe_iter",
    )
    reference_gate = _load_json(reference_gate_path)
    solver_smoke = _load_json(solver_smoke_path)
    lift_acceptance = _load_json(lift_acceptance_path)
    panel_su2_lift_gap_debug = _load_json(panel_su2_lift_gap_debug_path)
    su2_mesh_normal_audit = _load_json(su2_mesh_normal_audit_path)
    mesh_quality_hotspot_audit = _load_json(mesh_quality_hotspot_audit_path)
    panel_wake_semantics_audit = _load_json(panel_wake_semantics_audit_path)
    su2_surface_topology_audit = _load_json(su2_surface_topology_audit_path)
    su2_topology_defect_localization = _load_json(
        su2_topology_defect_localization_path
    )
    openvsp_defect_station_audit = _load_json(openvsp_defect_station_audit_path)
    gmsh_defect_entity_trace = _load_json(gmsh_defect_entity_trace_path)
    gmsh_curve_station_rebuild_audit = _load_json(
        gmsh_curve_station_rebuild_audit_path
    )
    openvsp_section_station_topology_fixture = _load_json(
        openvsp_section_station_topology_fixture_path
    )
    station_seam_repair_decision = _load_json(station_seam_repair_decision_path)
    station_seam_brep_hotspot_probe = _load_json(
        station_seam_brep_hotspot_probe_path
    )
    station_seam_same_parameter_feasibility = _load_json(
        station_seam_same_parameter_feasibility_path
    )
    station_seam_shape_fix_feasibility = _load_json(
        station_seam_shape_fix_feasibility_path
    )
    station_seam_export_source_audit = _load_json(
        station_seam_export_source_audit_path
    )
    station_seam_export_strategy_probe = _load_json(
        station_seam_export_strategy_probe_path
    )
    station_seam_internal_cap_probe = _load_json(station_seam_internal_cap_probe_path)
    station_seam_profile_resample_strategy_probe = _load_json(
        station_seam_profile_resample_strategy_probe_path
    )
    station_seam_profile_resample_brep_validation_probe = _load_json(
        station_seam_profile_resample_brep_validation_probe_path
    )
    station_seam_profile_resample_repair_feasibility_probe = _load_json(
        station_seam_profile_resample_repair_feasibility_probe_path
    )
    station_seam_profile_parametrization_audit = _load_json(
        station_seam_profile_parametrization_audit_path
    )
    station_seam_side_aware_parametrization_probe = _load_json(
        station_seam_side_aware_parametrization_probe_path
    )
    station_seam_side_aware_brep_validation_probe = _load_json(
        station_seam_side_aware_brep_validation_probe_path
    )
    station_seam_side_aware_pcurve_residual_diagnostic = _load_json(
        station_seam_side_aware_pcurve_residual_diagnostic_path
    )
    station_seam_side_aware_metadata_repair_probe = _load_json(
        station_seam_side_aware_metadata_repair_probe_path
    )
    station_seam_side_aware_pcurve_metadata_builder_probe = _load_json(
        station_seam_side_aware_pcurve_metadata_builder_probe_path
    )
    station_seam_side_aware_projected_pcurve_builder_probe = _load_json(
        station_seam_side_aware_projected_pcurve_builder_probe_path
    )
    station_seam_side_aware_export_opcode_variant_probe = _load_json(
        station_seam_side_aware_export_opcode_variant_probe_path
    )
    station_seam_export_metadata_source_audit = _load_json(
        station_seam_export_metadata_source_audit_path
    )
    solver_budget_path, solver_budget = _load_latest_solver_budget_probe(
        root,
        directory_prefix="main_wing_real_solver_smoke_probe_iter",
    )
    synthetic_su2_runtime = _load_json(synthetic_su2_runtime_path)
    hpa_flow_status, observed_velocity = _flow_status(synthetic_su2_runtime)

    real_geometry_pass = (
        isinstance(real_geometry, dict)
        and real_geometry.get("geometry_smoke_status") == "geometry_smoke_pass"
        and real_geometry.get("provider_status") == "materialized"
    )
    real_mesh_pass = (
        isinstance(real_mesh, dict)
        and real_mesh.get("probe_status") == "mesh_handoff_pass"
        and real_mesh.get("mesh_handoff_status") == "written"
    )
    real_mesh_quality_flags = (
        real_mesh.get("mesh_quality_advisory_flags", [])
        if isinstance(real_mesh, dict)
        else []
    )
    real_mesh_quality_warn = bool(real_mesh_quality_flags)
    synthetic_mesh_pass = (
        isinstance(synthetic_mesh, dict)
        and synthetic_mesh.get("smoke_status") == "mesh_handoff_pass"
        and synthetic_mesh.get("mesh_handoff_status") == "written"
    )
    synthetic_su2_materialized = (
        isinstance(synthetic_su2, dict)
        and synthetic_su2.get("materialization_status") == "su2_handoff_written"
    )
    real_su2_materialized = (
        isinstance(real_su2, dict)
        and real_su2.get("materialization_status") == "su2_handoff_written"
    )
    openvsp_reference_su2_materialized = (
        isinstance(openvsp_reference_su2, dict)
        and openvsp_reference_su2.get("materialization_status") == "su2_handoff_written"
    )
    openvsp_reference_solver_executed = (
        isinstance(openvsp_reference_solver, dict)
        and openvsp_reference_solver.get("solver_execution_status") == "solver_executed"
    )
    openvsp_reference_solver_blocked = (
        isinstance(openvsp_reference_solver, dict)
        and openvsp_reference_solver.get("solver_execution_status")
        in {"solver_failed", "solver_timeout", "solver_unavailable", "blocked_before_solver"}
    )
    reference_gate_status = (
        reference_gate.get("reference_gate_status")
        if isinstance(reference_gate, dict)
        else None
    )
    solver_executed = (
        isinstance(solver_smoke, dict)
        and solver_smoke.get("solver_execution_status") == "solver_executed"
    )
    solver_blocked = (
        isinstance(solver_smoke, dict)
        and solver_smoke.get("solver_execution_status")
        in {"solver_failed", "solver_timeout", "solver_unavailable", "blocked_before_solver"}
    )
    convergence_status = (
        solver_smoke.get("convergence_gate_status")
        if isinstance(solver_smoke, dict)
        else None
    )
    solver_lift_acceptance_failed = any(
        _solver_probe_lift_acceptance_status(candidate) == "fail"
        for candidate in (
            solver_smoke,
            solver_budget,
            openvsp_reference_solver,
            openvsp_reference_solver_budget,
        )
    )
    solver_lift_acceptance_blockers = (
        ["main_wing_cl_below_expected_lift"]
        if solver_lift_acceptance_failed
        else []
    )
    surface_force_output_blockers = set(_blocking_reasons(surface_force_output_audit))
    surface_force_output_blocked = any(
        reason
        in {
            "surface_force_output_pruned_or_missing",
            "forces_breakdown_output_missing",
            "panel_force_comparison_not_ready",
        }
        for reason in surface_force_output_blockers
    )
    convergence_pass = (
        solver_executed
        and convergence_status == "pass"
        and not solver_lift_acceptance_failed
    )
    convergence_blocked = solver_executed and (
        convergence_status in {"warn", "fail", "unavailable"}
        or (convergence_status == "pass" and solver_lift_acceptance_failed)
    )

    stages = [
        _stage(
            stage="real_geometry",
            status="pass" if real_geometry_pass else "blocked",
            evidence_kind="real",
            artifact_path=real_geometry_path,
            observed={
                "geometry_smoke_status": None if real_geometry is None else real_geometry.get("geometry_smoke_status"),
                "provider_status": None if real_geometry is None else real_geometry.get("provider_status"),
                "surface_count": None if real_geometry is None else real_geometry.get("surface_count"),
                "volume_count": None if real_geometry is None else real_geometry.get("volume_count"),
            },
            blockers=[] if real_geometry_pass else _blocking_reasons(real_geometry),
        ),
        _stage(
            stage="geometry_provenance",
            status=_geometry_provenance_status(geometry_provenance),
            evidence_kind="real" if isinstance(geometry_provenance, dict) else "absent",
            artifact_path=(
                geometry_provenance_path
                if isinstance(geometry_provenance, dict)
                else None
            ),
            observed=_geometry_provenance_observed(geometry_provenance),
            blockers=_geometry_provenance_blockers(geometry_provenance),
        ),
        _stage(
            stage="vspaero_panel_reference",
            status=_vspaero_panel_reference_status(vspaero_panel_reference),
            evidence_kind=(
                "real" if isinstance(vspaero_panel_reference, dict) else "absent"
            ),
            artifact_path=(
                vspaero_panel_reference_path
                if isinstance(vspaero_panel_reference, dict)
                else None
            ),
            observed=_vspaero_panel_reference_observed(vspaero_panel_reference),
            blockers=_vspaero_panel_reference_blockers(vspaero_panel_reference),
        ),
        _stage(
            stage="real_mesh_handoff",
            status="pass" if real_mesh_pass else "blocked",
            evidence_kind="real",
            artifact_path=real_mesh_path,
            observed={
                "probe_status": None if real_mesh is None else real_mesh.get("probe_status"),
                "mesh_handoff_status": None if real_mesh is None else real_mesh.get("mesh_handoff_status"),
                "mesh2d_watchdog_status": None if real_mesh is None else real_mesh.get("mesh2d_watchdog_status"),
                "mesh3d_timeout_phase_classification": (
                    None if real_mesh is None else real_mesh.get("mesh3d_timeout_phase_classification")
                ),
                "mesh_failure_classification": (
                    None if real_mesh is None else real_mesh.get("mesh_failure_classification")
                ),
                "mesh3d_nodes_created_per_boundary_node": (
                    None if real_mesh is None else real_mesh.get("mesh3d_nodes_created_per_boundary_node")
                ),
                "mesh_quality_status": (
                    None if real_mesh is None else real_mesh.get("mesh_quality_status")
                ),
                "mesh_quality_advisory_flags": (
                    [] if real_mesh is None else real_mesh.get("mesh_quality_advisory_flags", [])
                ),
                "mesh_quality_metrics": (
                    {} if real_mesh is None else real_mesh.get("mesh_quality_metrics", {})
                ),
            },
            blockers=[] if real_mesh_pass else _blocking_reasons(real_mesh),
        ),
        _stage(
            stage="synthetic_mesh_handoff",
            status="materialized_synthetic_only" if synthetic_mesh_pass else "blocked",
            evidence_kind="synthetic",
            artifact_path=synthetic_mesh_path,
            observed={
                "smoke_status": None if synthetic_mesh is None else synthetic_mesh.get("smoke_status"),
                "mesh_handoff_status": None if synthetic_mesh is None else synthetic_mesh.get("mesh_handoff_status"),
                "marker_summary_status": None if synthetic_mesh is None else synthetic_mesh.get("marker_summary_status"),
                "volume_element_count": None if synthetic_mesh is None else synthetic_mesh.get("volume_element_count"),
            },
            blockers=_blocking_reasons(synthetic_mesh),
        ),
        _stage(
            stage="synthetic_su2_handoff",
            status="materialized_synthetic_only" if synthetic_su2_materialized else "blocked",
            evidence_kind="synthetic",
            artifact_path=synthetic_su2_path,
            observed={
                "materialization_status": None if synthetic_su2 is None else synthetic_su2.get("materialization_status"),
                "solver_execution_status": None if synthetic_su2 is None else synthetic_su2.get("solver_execution_status"),
                "convergence_gate_status": None if synthetic_su2 is None else synthetic_su2.get("convergence_gate_status"),
                "component_force_ownership_status": (
                    None if synthetic_su2 is None else synthetic_su2.get("component_force_ownership_status")
                ),
                "observed_velocity_mps": observed_velocity,
            },
            blockers=_blocking_reasons(synthetic_su2),
        ),
        _stage(
            stage="real_su2_handoff",
            status="pass" if real_su2_materialized else "blocked",
            evidence_kind="real" if real_su2_materialized else "absent",
            artifact_path=real_su2_path if real_su2_materialized else None,
            observed={
                "materialization_status": (
                    None if real_su2 is None else real_su2.get("materialization_status")
                ),
                "su2_contract": None if real_su2 is None else real_su2.get("su2_contract"),
                "input_mesh_contract": (
                    None if real_su2 is None else real_su2.get("input_mesh_contract")
                ),
                "component_force_ownership_status": (
                    None
                    if real_su2 is None
                    else real_su2.get("component_force_ownership_status")
                ),
                "reference_geometry_status": (
                    None if real_su2 is None else real_su2.get("reference_geometry_status")
                ),
                "reference_gate_status": reference_gate_status,
                "reference_gate_path": (
                    str(reference_gate_path) if isinstance(reference_gate, dict) else None
                ),
                "observed_velocity_mps": (
                    None if real_su2 is None else real_su2.get("observed_velocity_mps")
                ),
                "reason": None if real_su2_materialized else (
                    "real_su2_handoff_artifact_missing_after_mesh_handoff"
                    if real_mesh_pass
                    else "real_mesh_handoff_required_first"
                ),
            },
            blockers=(
                [
                    *(
                        _real_su2_stage_blockers(real_su2)
                    ),
                    *(
                        _blocking_reasons(reference_gate)
                        if isinstance(reference_gate, dict)
                        else []
                    ),
                ]
                if real_su2_materialized
                else (
                    ["real_main_wing_su2_handoff_not_materialized"]
                    if real_mesh_pass
                    else ["blocked_until_real_main_wing_mesh_handoff_v1_exists"]
                )
            ),
        ),
        _stage(
            stage="openvsp_reference_su2_handoff",
            status="pass"
            if openvsp_reference_su2_materialized
            else "blocked"
            if isinstance(openvsp_reference_su2, dict)
            else "not_run",
            evidence_kind="real" if isinstance(openvsp_reference_su2, dict) else "absent",
            artifact_path=openvsp_reference_su2_path
            if isinstance(openvsp_reference_su2, dict)
            else None,
            observed={
                "materialization_status": (
                    None
                    if openvsp_reference_su2 is None
                    else openvsp_reference_su2.get("materialization_status")
                ),
                "reference_policy": (
                    None
                    if openvsp_reference_su2 is None
                    else openvsp_reference_su2.get("reference_policy")
                ),
                "su2_contract": (
                    None if openvsp_reference_su2 is None else openvsp_reference_su2.get("su2_contract")
                ),
                "component_force_ownership_status": (
                    None
                    if openvsp_reference_su2 is None
                    else openvsp_reference_su2.get("component_force_ownership_status")
                ),
                "reference_geometry_status": (
                    None
                    if openvsp_reference_su2 is None
                    else openvsp_reference_su2.get("reference_geometry_status")
                ),
                "observed_velocity_mps": (
                    None
                    if openvsp_reference_su2 is None
                    else openvsp_reference_su2.get("observed_velocity_mps")
                ),
            },
            blockers=(
                _real_su2_stage_blockers(openvsp_reference_su2)
                if openvsp_reference_su2_materialized
                else _blocking_reasons(openvsp_reference_su2)
                if isinstance(openvsp_reference_su2, dict)
                else []
            ),
        ),
        _stage(
            stage="su2_force_marker_audit",
            status=_su2_force_marker_audit_status(su2_force_marker_audit),
            evidence_kind=(
                "real" if isinstance(su2_force_marker_audit, dict) else "absent"
            ),
            artifact_path=su2_force_marker_audit_path
            if isinstance(su2_force_marker_audit, dict)
            else None,
            observed=_su2_force_marker_audit_observed(su2_force_marker_audit),
            blockers=_blocking_reasons(su2_force_marker_audit),
        ),
        _stage(
            stage="surface_force_output_audit",
            status=_surface_force_output_audit_status(surface_force_output_audit),
            evidence_kind=(
                "real" if isinstance(surface_force_output_audit, dict) else "absent"
            ),
            artifact_path=surface_force_output_audit_path
            if isinstance(surface_force_output_audit, dict)
            else None,
            observed=_surface_force_output_audit_observed(surface_force_output_audit),
            blockers=_blocking_reasons(surface_force_output_audit),
        ),
        _stage(
            stage="openvsp_reference_geometry_gate",
            status=_reference_gate_status(openvsp_reference_geometry_gate),
            evidence_kind=(
                "real" if isinstance(openvsp_reference_geometry_gate, dict) else "absent"
            ),
            artifact_path=openvsp_reference_geometry_gate_path
            if isinstance(openvsp_reference_geometry_gate, dict)
            else None,
            observed=_reference_gate_observed(openvsp_reference_geometry_gate),
            blockers=_blocking_reasons(openvsp_reference_geometry_gate),
        ),
        _stage(
            stage="openvsp_reference_solver_smoke",
            status="pass"
            if openvsp_reference_solver_executed
            else "blocked"
            if openvsp_reference_solver_blocked
            else "not_run",
            evidence_kind="real" if isinstance(openvsp_reference_solver, dict) else "absent",
            artifact_path=openvsp_reference_solver_path
            if isinstance(openvsp_reference_solver, dict)
            else None,
            observed=_solver_probe_observed(openvsp_reference_solver),
            blockers=(
                _blocking_reasons(openvsp_reference_solver)
                if isinstance(openvsp_reference_solver, dict)
                else []
            ),
        ),
        _stage(
            stage="openvsp_reference_solver_budget_probe",
            status=(
                "pass"
                if _solver_probe_executed(openvsp_reference_solver_budget)
                else "blocked"
                if _solver_probe_blocked(openvsp_reference_solver_budget)
                else "not_run"
            ),
            evidence_kind=(
                "real" if isinstance(openvsp_reference_solver_budget, dict) else "absent"
            ),
            artifact_path=(
                openvsp_reference_solver_budget_path
                if isinstance(openvsp_reference_solver_budget, dict)
                else None
            ),
            observed=_solver_probe_observed(openvsp_reference_solver_budget),
            blockers=(
                _blocking_reasons(openvsp_reference_solver_budget)
                if isinstance(openvsp_reference_solver_budget, dict)
                else []
            ),
        ),
        _stage(
            stage="solver_smoke",
            status="pass" if solver_executed else "blocked" if solver_blocked else "not_run",
            evidence_kind="real" if isinstance(solver_smoke, dict) else "absent",
            artifact_path=solver_smoke_path if isinstance(solver_smoke, dict) else None,
            observed={
                **_solver_probe_observed(solver_smoke),
                "return_code": None if solver_smoke is None else solver_smoke.get("return_code"),
                "history_path": None if solver_smoke is None else solver_smoke.get("history_path"),
                "solver_log_path": (
                    None if solver_smoke is None else solver_smoke.get("solver_log_path")
                ),
            },
            blockers=(
                _blocking_reasons(solver_smoke)
                if solver_blocked
                else []
                if solver_executed
                else ["main_wing_solver_not_run"]
            ),
        ),
        _stage(
            stage="solver_budget_probe",
            status=(
                "pass"
                if _solver_probe_executed(solver_budget)
                else "blocked"
                if _solver_probe_blocked(solver_budget)
                else "not_run"
            ),
            evidence_kind="real" if isinstance(solver_budget, dict) else "absent",
            artifact_path=solver_budget_path if isinstance(solver_budget, dict) else None,
            observed=_solver_probe_observed(solver_budget),
            blockers=(
                _blocking_reasons(solver_budget)
                if isinstance(solver_budget, dict)
                else []
            ),
        ),
        _stage(
            stage="lift_acceptance_diagnostic",
            status=_lift_acceptance_stage_status(lift_acceptance),
            evidence_kind="real" if isinstance(lift_acceptance, dict) else "absent",
            artifact_path=(
                lift_acceptance_path if isinstance(lift_acceptance, dict) else None
            ),
            observed=_lift_acceptance_observed(lift_acceptance),
            blockers=_lift_acceptance_blockers(lift_acceptance),
        ),
        _stage(
            stage="panel_su2_lift_gap_debug",
            status=_panel_su2_lift_gap_debug_status(panel_su2_lift_gap_debug),
            evidence_kind=(
                "real" if isinstance(panel_su2_lift_gap_debug, dict) else "absent"
            ),
            artifact_path=(
                panel_su2_lift_gap_debug_path
                if isinstance(panel_su2_lift_gap_debug, dict)
                else None
            ),
            observed=_panel_su2_lift_gap_debug_observed(panel_su2_lift_gap_debug),
            blockers=_panel_su2_lift_gap_debug_blockers(panel_su2_lift_gap_debug),
        ),
        _stage(
            stage="mesh_quality_hotspot_audit",
            status=_mesh_quality_hotspot_audit_status(mesh_quality_hotspot_audit),
            evidence_kind=(
                "real" if isinstance(mesh_quality_hotspot_audit, dict) else "absent"
            ),
            artifact_path=(
                mesh_quality_hotspot_audit_path
                if isinstance(mesh_quality_hotspot_audit, dict)
                else None
            ),
            observed=_mesh_quality_hotspot_audit_observed(mesh_quality_hotspot_audit),
            blockers=_blocking_reasons(mesh_quality_hotspot_audit),
        ),
        _stage(
            stage="su2_mesh_normal_audit",
            status=_su2_mesh_normal_audit_status(su2_mesh_normal_audit),
            evidence_kind="real" if isinstance(su2_mesh_normal_audit, dict) else "absent",
            artifact_path=(
                su2_mesh_normal_audit_path
                if isinstance(su2_mesh_normal_audit, dict)
                else None
            ),
            observed=_su2_mesh_normal_audit_observed(su2_mesh_normal_audit),
            blockers=_blocking_reasons(su2_mesh_normal_audit),
        ),
        _stage(
            stage="panel_wake_semantics_audit",
            status=_panel_wake_semantics_audit_status(panel_wake_semantics_audit),
            evidence_kind=(
                "real" if isinstance(panel_wake_semantics_audit, dict) else "absent"
            ),
            artifact_path=(
                panel_wake_semantics_audit_path
                if isinstance(panel_wake_semantics_audit, dict)
                else None
            ),
            observed=_panel_wake_semantics_audit_observed(panel_wake_semantics_audit),
            blockers=_blocking_reasons(panel_wake_semantics_audit),
        ),
        _stage(
            stage="su2_surface_topology_audit",
            status=_su2_surface_topology_audit_status(su2_surface_topology_audit),
            evidence_kind=(
                "real" if isinstance(su2_surface_topology_audit, dict) else "absent"
            ),
            artifact_path=(
                su2_surface_topology_audit_path
                if isinstance(su2_surface_topology_audit, dict)
                else None
            ),
            observed=_su2_surface_topology_audit_observed(su2_surface_topology_audit),
            blockers=_blocking_reasons(su2_surface_topology_audit),
        ),
        _stage(
            stage="su2_topology_defect_localization",
            status=_su2_topology_defect_localization_status(
                su2_topology_defect_localization
            ),
            evidence_kind=(
                "real"
                if isinstance(su2_topology_defect_localization, dict)
                else "absent"
            ),
            artifact_path=(
                su2_topology_defect_localization_path
                if isinstance(su2_topology_defect_localization, dict)
                else None
            ),
            observed=_su2_topology_defect_localization_observed(
                su2_topology_defect_localization
            ),
            blockers=_blocking_reasons(su2_topology_defect_localization),
        ),
        _stage(
            stage="openvsp_defect_station_audit",
            status=_openvsp_defect_station_audit_status(
                openvsp_defect_station_audit
            ),
            evidence_kind=(
                "real" if isinstance(openvsp_defect_station_audit, dict) else "absent"
            ),
            artifact_path=(
                openvsp_defect_station_audit_path
                if isinstance(openvsp_defect_station_audit, dict)
                else None
            ),
            observed=_openvsp_defect_station_audit_observed(
                openvsp_defect_station_audit
            ),
            blockers=_blocking_reasons(openvsp_defect_station_audit),
        ),
        _stage(
            stage="gmsh_defect_entity_trace",
            status=_gmsh_defect_entity_trace_status(gmsh_defect_entity_trace),
            evidence_kind=(
                "real" if isinstance(gmsh_defect_entity_trace, dict) else "absent"
            ),
            artifact_path=(
                gmsh_defect_entity_trace_path
                if isinstance(gmsh_defect_entity_trace, dict)
                else None
            ),
            observed=_gmsh_defect_entity_trace_observed(gmsh_defect_entity_trace),
            blockers=_blocking_reasons(gmsh_defect_entity_trace),
        ),
        _stage(
            stage="gmsh_curve_station_rebuild_audit",
            status=_gmsh_curve_station_rebuild_audit_status(
                gmsh_curve_station_rebuild_audit
            ),
            evidence_kind=(
                "real"
                if isinstance(gmsh_curve_station_rebuild_audit, dict)
                else "absent"
            ),
            artifact_path=(
                gmsh_curve_station_rebuild_audit_path
                if isinstance(gmsh_curve_station_rebuild_audit, dict)
                else None
            ),
            observed=_gmsh_curve_station_rebuild_audit_observed(
                gmsh_curve_station_rebuild_audit
            ),
            blockers=_blocking_reasons(gmsh_curve_station_rebuild_audit),
        ),
        _stage(
            stage="openvsp_section_station_topology_fixture",
            status=_openvsp_section_station_topology_fixture_status(
                openvsp_section_station_topology_fixture
            ),
            evidence_kind=(
                "real"
                if isinstance(openvsp_section_station_topology_fixture, dict)
                else "absent"
            ),
            artifact_path=(
                openvsp_section_station_topology_fixture_path
                if isinstance(openvsp_section_station_topology_fixture, dict)
                else None
            ),
            observed=_openvsp_section_station_topology_fixture_observed(
                openvsp_section_station_topology_fixture
            ),
            blockers=_blocking_reasons(openvsp_section_station_topology_fixture),
        ),
        _stage(
            stage="station_seam_repair_decision",
            status=_station_seam_repair_decision_status(
                station_seam_repair_decision
            ),
            evidence_kind=(
                "real" if isinstance(station_seam_repair_decision, dict) else "absent"
            ),
            artifact_path=(
                station_seam_repair_decision_path
                if isinstance(station_seam_repair_decision, dict)
                else None
            ),
            observed=_station_seam_repair_decision_observed(
                station_seam_repair_decision
            ),
            blockers=_blocking_reasons(station_seam_repair_decision),
        ),
        _stage(
            stage="station_seam_brep_hotspot_probe",
            status=_station_seam_brep_hotspot_probe_status(
                station_seam_brep_hotspot_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_brep_hotspot_probe, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_brep_hotspot_probe_path
                if isinstance(station_seam_brep_hotspot_probe, dict)
                else None
            ),
            observed=_station_seam_brep_hotspot_probe_observed(
                station_seam_brep_hotspot_probe
            ),
            blockers=_blocking_reasons(station_seam_brep_hotspot_probe),
        ),
        _stage(
            stage="station_seam_same_parameter_feasibility",
            status=_station_seam_same_parameter_feasibility_status(
                station_seam_same_parameter_feasibility
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_same_parameter_feasibility, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_same_parameter_feasibility_path
                if isinstance(station_seam_same_parameter_feasibility, dict)
                else None
            ),
            observed=_station_seam_same_parameter_feasibility_observed(
                station_seam_same_parameter_feasibility
            ),
            blockers=_blocking_reasons(station_seam_same_parameter_feasibility),
        ),
        _stage(
            stage="station_seam_shape_fix_feasibility",
            status=_station_seam_shape_fix_feasibility_status(
                station_seam_shape_fix_feasibility
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_shape_fix_feasibility, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_shape_fix_feasibility_path
                if isinstance(station_seam_shape_fix_feasibility, dict)
                else None
            ),
            observed=_station_seam_shape_fix_feasibility_observed(
                station_seam_shape_fix_feasibility
            ),
            blockers=_blocking_reasons(station_seam_shape_fix_feasibility),
        ),
        _stage(
            stage="station_seam_export_source_audit",
            status=_station_seam_export_source_audit_status(
                station_seam_export_source_audit
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_export_source_audit, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_export_source_audit_path
                if isinstance(station_seam_export_source_audit, dict)
                else None
            ),
            observed=_station_seam_export_source_audit_observed(
                station_seam_export_source_audit
            ),
            blockers=_blocking_reasons(station_seam_export_source_audit),
        ),
        _stage(
            stage="station_seam_export_strategy_probe",
            status=_station_seam_export_strategy_probe_status(
                station_seam_export_strategy_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_export_strategy_probe, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_export_strategy_probe_path
                if isinstance(station_seam_export_strategy_probe, dict)
                else None
            ),
            observed=_station_seam_export_strategy_probe_observed(
                station_seam_export_strategy_probe
            ),
            blockers=_blocking_reasons(station_seam_export_strategy_probe),
        ),
        _stage(
            stage="station_seam_internal_cap_probe",
            status=_station_seam_internal_cap_probe_status(
                station_seam_internal_cap_probe
            ),
            evidence_kind=(
                "real" if isinstance(station_seam_internal_cap_probe, dict) else "absent"
            ),
            artifact_path=(
                station_seam_internal_cap_probe_path
                if isinstance(station_seam_internal_cap_probe, dict)
                else None
            ),
            observed=_station_seam_internal_cap_probe_observed(
                station_seam_internal_cap_probe
            ),
            blockers=_blocking_reasons(station_seam_internal_cap_probe),
        ),
        _stage(
            stage="station_seam_profile_resample_strategy_probe",
            status=_station_seam_profile_resample_strategy_probe_status(
                station_seam_profile_resample_strategy_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_profile_resample_strategy_probe, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_profile_resample_strategy_probe_path
                if isinstance(station_seam_profile_resample_strategy_probe, dict)
                else None
            ),
            observed=_station_seam_profile_resample_strategy_probe_observed(
                station_seam_profile_resample_strategy_probe
            ),
            blockers=_blocking_reasons(station_seam_profile_resample_strategy_probe),
        ),
        _stage(
            stage="station_seam_profile_resample_brep_validation_probe",
            status=_station_seam_profile_resample_brep_validation_probe_status(
                station_seam_profile_resample_brep_validation_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(
                    station_seam_profile_resample_brep_validation_probe,
                    dict,
                )
                else "absent"
            ),
            artifact_path=(
                station_seam_profile_resample_brep_validation_probe_path
                if isinstance(
                    station_seam_profile_resample_brep_validation_probe,
                    dict,
                )
                else None
            ),
            observed=_station_seam_profile_resample_brep_validation_probe_observed(
                station_seam_profile_resample_brep_validation_probe
            ),
            blockers=_blocking_reasons(
                station_seam_profile_resample_brep_validation_probe
            ),
        ),
        _stage(
            stage="station_seam_profile_resample_repair_feasibility_probe",
            status=_station_seam_profile_resample_repair_feasibility_probe_status(
                station_seam_profile_resample_repair_feasibility_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(
                    station_seam_profile_resample_repair_feasibility_probe,
                    dict,
                )
                else "absent"
            ),
            artifact_path=(
                station_seam_profile_resample_repair_feasibility_probe_path
                if isinstance(
                    station_seam_profile_resample_repair_feasibility_probe,
                    dict,
                )
                else None
            ),
            observed=_station_seam_profile_resample_repair_feasibility_probe_observed(
                station_seam_profile_resample_repair_feasibility_probe
            ),
            blockers=_blocking_reasons(
                station_seam_profile_resample_repair_feasibility_probe
            ),
        ),
        _stage(
            stage="station_seam_profile_parametrization_audit",
            status=_station_seam_profile_parametrization_audit_status(
                station_seam_profile_parametrization_audit
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_profile_parametrization_audit, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_profile_parametrization_audit_path
                if isinstance(station_seam_profile_parametrization_audit, dict)
                else None
            ),
            observed=_station_seam_profile_parametrization_audit_observed(
                station_seam_profile_parametrization_audit
            ),
            blockers=_blocking_reasons(station_seam_profile_parametrization_audit),
        ),
        _stage(
            stage="station_seam_side_aware_parametrization_probe",
            status=_station_seam_side_aware_parametrization_probe_status(
                station_seam_side_aware_parametrization_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_side_aware_parametrization_probe, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_side_aware_parametrization_probe_path
                if isinstance(station_seam_side_aware_parametrization_probe, dict)
                else None
            ),
            observed=_station_seam_side_aware_parametrization_probe_observed(
                station_seam_side_aware_parametrization_probe
            ),
            blockers=_blocking_reasons(station_seam_side_aware_parametrization_probe),
        ),
        _stage(
            stage="station_seam_side_aware_brep_validation_probe",
            status=_station_seam_side_aware_brep_validation_probe_status(
                station_seam_side_aware_brep_validation_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_side_aware_brep_validation_probe, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_side_aware_brep_validation_probe_path
                if isinstance(station_seam_side_aware_brep_validation_probe, dict)
                else None
            ),
            observed=_station_seam_side_aware_brep_validation_probe_observed(
                station_seam_side_aware_brep_validation_probe
            ),
            blockers=_blocking_reasons(station_seam_side_aware_brep_validation_probe),
        ),
        _stage(
            stage="station_seam_side_aware_pcurve_residual_diagnostic",
            status=_station_seam_side_aware_pcurve_residual_diagnostic_status(
                station_seam_side_aware_pcurve_residual_diagnostic
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_side_aware_pcurve_residual_diagnostic, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_side_aware_pcurve_residual_diagnostic_path
                if isinstance(station_seam_side_aware_pcurve_residual_diagnostic, dict)
                else None
            ),
            observed=_station_seam_side_aware_pcurve_residual_diagnostic_observed(
                station_seam_side_aware_pcurve_residual_diagnostic
            ),
            blockers=_blocking_reasons(
                station_seam_side_aware_pcurve_residual_diagnostic
            ),
        ),
        _stage(
            stage="station_seam_side_aware_metadata_repair_probe",
            status=_station_seam_side_aware_metadata_repair_probe_status(
                station_seam_side_aware_metadata_repair_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_side_aware_metadata_repair_probe, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_side_aware_metadata_repair_probe_path
                if isinstance(station_seam_side_aware_metadata_repair_probe, dict)
                else None
            ),
            observed=_station_seam_side_aware_metadata_repair_probe_observed(
                station_seam_side_aware_metadata_repair_probe
            ),
            blockers=_blocking_reasons(station_seam_side_aware_metadata_repair_probe),
        ),
        _stage(
            stage="station_seam_side_aware_pcurve_metadata_builder_probe",
            status=_station_seam_side_aware_pcurve_metadata_builder_probe_status(
                station_seam_side_aware_pcurve_metadata_builder_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(
                    station_seam_side_aware_pcurve_metadata_builder_probe,
                    dict,
                )
                else "absent"
            ),
            artifact_path=(
                station_seam_side_aware_pcurve_metadata_builder_probe_path
                if isinstance(
                    station_seam_side_aware_pcurve_metadata_builder_probe,
                    dict,
                )
                else None
            ),
            observed=_station_seam_side_aware_pcurve_metadata_builder_probe_observed(
                station_seam_side_aware_pcurve_metadata_builder_probe
            ),
            blockers=_blocking_reasons(
                station_seam_side_aware_pcurve_metadata_builder_probe
            ),
        ),
        _stage(
            stage="station_seam_side_aware_projected_pcurve_builder_probe",
            status=_station_seam_side_aware_projected_pcurve_builder_probe_status(
                station_seam_side_aware_projected_pcurve_builder_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(
                    station_seam_side_aware_projected_pcurve_builder_probe,
                    dict,
                )
                else "absent"
            ),
            artifact_path=(
                station_seam_side_aware_projected_pcurve_builder_probe_path
                if isinstance(
                    station_seam_side_aware_projected_pcurve_builder_probe,
                    dict,
                )
                else None
            ),
            observed=_station_seam_side_aware_projected_pcurve_builder_probe_observed(
                station_seam_side_aware_projected_pcurve_builder_probe
            ),
            blockers=_blocking_reasons(
                station_seam_side_aware_projected_pcurve_builder_probe
            ),
        ),
        _stage(
            stage="station_seam_side_aware_export_opcode_variant_probe",
            status=_station_seam_side_aware_export_opcode_variant_probe_status(
                station_seam_side_aware_export_opcode_variant_probe
            ),
            evidence_kind=(
                "real"
                if isinstance(
                    station_seam_side_aware_export_opcode_variant_probe,
                    dict,
                )
                else "absent"
            ),
            artifact_path=(
                station_seam_side_aware_export_opcode_variant_probe_path
                if isinstance(
                    station_seam_side_aware_export_opcode_variant_probe,
                    dict,
                )
                else None
            ),
            observed=_station_seam_side_aware_export_opcode_variant_probe_observed(
                station_seam_side_aware_export_opcode_variant_probe
            ),
            blockers=_blocking_reasons(
                station_seam_side_aware_export_opcode_variant_probe
            ),
        ),
        _stage(
            stage="station_seam_export_metadata_source_audit",
            status=_station_seam_export_metadata_source_audit_status(
                station_seam_export_metadata_source_audit
            ),
            evidence_kind=(
                "real"
                if isinstance(station_seam_export_metadata_source_audit, dict)
                else "absent"
            ),
            artifact_path=(
                station_seam_export_metadata_source_audit_path
                if isinstance(station_seam_export_metadata_source_audit, dict)
                else None
            ),
            observed=_station_seam_export_metadata_source_audit_observed(
                station_seam_export_metadata_source_audit
            ),
            blockers=_blocking_reasons(station_seam_export_metadata_source_audit),
        ),
        _stage(
            stage="convergence_gate",
            status="pass" if convergence_pass else "blocked" if convergence_blocked else "not_run",
            evidence_kind="real" if solver_executed else "absent",
            artifact_path=solver_smoke_path if solver_executed else None,
            observed={
                "convergence_gate_status": convergence_status or "not_run",
                "run_status": None if solver_smoke is None else solver_smoke.get("run_status"),
                "convergence_gate_path": (
                    None
                    if solver_smoke is None
                    else solver_smoke.get("convergence_gate_path")
                ),
                "convergence_comparability_level": (
                    None
                    if solver_smoke is None
                    else solver_smoke.get("convergence_comparability_level")
                ),
                "final_iteration": (
                    None if solver_smoke is None else solver_smoke.get("final_iteration")
                ),
            },
            blockers=(
                [
                    *(
                        _blocking_reasons(solver_smoke)
                        if isinstance(solver_smoke, dict)
                        else []
                    ),
                    *solver_lift_acceptance_blockers,
                ]
                if convergence_blocked
                else []
                if convergence_pass
                else ["convergence_gate_not_run"]
            ),
        ),
    ]

    if not real_geometry_pass:
        overall_status: OverallStatusType = "blocked_at_real_geometry"
    elif not real_mesh_pass:
        overall_status = "blocked_at_real_mesh_handoff"
    elif not real_su2_materialized:
        overall_status = "blocked_at_real_su2_handoff"
    elif solver_blocked:
        overall_status = "solver_smoke_blocked"
    elif not solver_executed:
        overall_status = "solver_not_run"
    elif convergence_pass:
        overall_status = "convergence_gate_passed"
    elif convergence_blocked:
        overall_status = "solver_executed_not_converged"
    else:
        overall_status = "convergence_not_run"

    blocking_reasons = []
    for stage in stages:
        if stage.status == "materialized_synthetic_only":
            continue
        for reason in stage.blockers:
            if reason not in blocking_reasons:
                blocking_reasons.append(reason)
    for reason in solver_lift_acceptance_blockers:
        if reason not in blocking_reasons:
            blocking_reasons.append(reason)

    secondary_next_action = (
        "run_bounded_main_wing_iteration_sweep_after_reference_gate_is_clean"
        if convergence_blocked
        else "inspect_main_wing_solver_log_and_runtime_cfg"
        if solver_blocked
        else "promote_real_solver_artifacts_into_readiness_contract"
        if convergence_pass
        else "run_solver_smoke_then_convergence_gate_after_real_su2_handoff"
    )
    next_actions = [
        (
            "diagnose_main_wing_solver_nonconvergence_before_cfd_claims"
            if convergence_blocked
            else "repair_main_wing_solver_smoke_blocker"
            if solver_blocked
            else "run_main_wing_solver_smoke_from_real_su2_handoff"
            if real_su2_materialized and not solver_executed
            else "harden_main_wing_reference_geometry_and_mesh_independence_before_product_cfd"
            if convergence_pass
            else
            "materialize_real_main_wing_su2_handoff_from_real_mesh_handoff_v1"
            if real_mesh_pass
            else "repair_real_main_wing_mesh3d_volume_insertion_policy"
        ),
        secondary_next_action,
        "preserve_synthetic_su2_as_wiring_evidence_only",
    ]
    if "main_wing_real_geometry_invalid_boundary_mesh_overlapping_facets" in blocking_reasons:
        next_actions[0] = "repair_real_main_wing_boundary_overlap_before_volume_meshing"
    if "main_wing_real_geometry_boundary_parametrization_topology_failed" in blocking_reasons:
        next_actions[0] = "repair_real_main_wing_boundary_topology_before_volume_meshing"
    if convergence_blocked and real_mesh_quality_warn:
        next_actions[0] = "inspect_main_wing_mesh_quality_before_more_solver_budget"
    if convergence_blocked and solver_lift_acceptance_failed:
        next_actions[0] = "resolve_main_wing_cl_below_expected_lift_before_convergence_claims"
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and surface_force_output_blocked
    ):
        if "surface_force_output_pruned_or_missing" in surface_force_output_blockers:
            next_actions[0] = (
                "preserve_main_wing_surface_force_outputs_before_panel_delta_debug"
            )
        elif "forces_breakdown_output_missing" in surface_force_output_blockers:
            next_actions[0] = (
                "resolve_main_wing_forces_breakdown_output_before_panel_delta_debug"
            )
    surface_force_output_flags = set(_engineering_flags(surface_force_output_audit))
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and not surface_force_output_blocked
        and "forces_breakdown_cl_below_panel_reference" in surface_force_output_flags
    ):
        next_actions[0] = "debug_panel_su2_lift_gap_from_retained_force_breakdown"
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(panel_su2_lift_gap_debug, dict)
        and panel_su2_lift_gap_debug.get("debug_status") == "gap_confirmed_debug_ready"
    ):
        debug_next_actions = panel_su2_lift_gap_debug.get("next_actions", [])
        if isinstance(debug_next_actions, list) and debug_next_actions:
            next_actions[0] = str(debug_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(su2_mesh_normal_audit, dict)
        and su2_mesh_normal_audit.get("normal_audit_status") == "pass"
        and "single_global_normal_flip_not_supported"
        in su2_mesh_normal_audit.get("engineering_findings", [])
    ):
        normal_next_actions = su2_mesh_normal_audit.get("next_actions", [])
        if isinstance(normal_next_actions, list) and normal_next_actions:
            next_actions[0] = str(normal_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(panel_wake_semantics_audit, dict)
        and panel_wake_semantics_audit.get("audit_status")
        == "semantics_gap_observed"
    ):
        semantics_next_actions = panel_wake_semantics_audit.get("next_actions", [])
        if isinstance(semantics_next_actions, list) and semantics_next_actions:
            next_actions[0] = str(semantics_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(su2_surface_topology_audit, dict)
        and su2_surface_topology_audit.get("audit_status")
        in {
            "thin_surface_like_with_local_topology_defects",
            "open_or_lifting_surface_like",
            "closed_surface_with_local_topology_defects",
        }
    ):
        topology_next_actions = su2_surface_topology_audit.get("next_actions", [])
        if isinstance(topology_next_actions, list) and topology_next_actions:
            next_actions[0] = str(topology_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(su2_topology_defect_localization, dict)
        and su2_topology_defect_localization.get("localization_status")
        == "defects_localized"
    ):
        localization_next_actions = su2_topology_defect_localization.get(
            "next_actions", []
        )
        if isinstance(localization_next_actions, list) and localization_next_actions:
            next_actions[0] = str(localization_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(openvsp_defect_station_audit, dict)
        and openvsp_defect_station_audit.get("station_alignment_status")
        == "defect_stations_aligned_to_openvsp_rule_sections"
    ):
        station_next_actions = openvsp_defect_station_audit.get("next_actions", [])
        if isinstance(station_next_actions, list) and station_next_actions:
            next_actions[0] = str(station_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(gmsh_defect_entity_trace, dict)
        and gmsh_defect_entity_trace.get("trace_status")
        == "defect_edges_traced_to_gmsh_entities"
    ):
        trace_next_actions = gmsh_defect_entity_trace.get("next_actions", [])
        if isinstance(trace_next_actions, list) and trace_next_actions:
            next_actions[0] = str(trace_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(gmsh_curve_station_rebuild_audit, dict)
        and gmsh_curve_station_rebuild_audit.get("curve_station_rebuild_status")
        == "curve_tags_match_vsp3_section_profile_scale"
    ):
        curve_next_actions = gmsh_curve_station_rebuild_audit.get("next_actions", [])
        if isinstance(curve_next_actions, list) and curve_next_actions:
            next_actions[0] = str(curve_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(openvsp_section_station_topology_fixture, dict)
        and openvsp_section_station_topology_fixture.get("topology_fixture_status")
        == "real_defect_station_fixture_materialized"
    ):
        fixture_next_actions = openvsp_section_station_topology_fixture.get(
            "next_actions",
            [],
        )
        if isinstance(fixture_next_actions, list) and fixture_next_actions:
            next_actions[0] = str(fixture_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_repair_decision, dict)
        and station_seam_repair_decision.get("repair_decision_status")
        == "station_seam_repair_required_before_solver_budget"
    ):
        decision_next_actions = station_seam_repair_decision.get("next_actions", [])
        if isinstance(decision_next_actions, list) and decision_next_actions:
            next_actions[0] = str(decision_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_brep_hotspot_probe, dict)
        and station_seam_brep_hotspot_probe.get("probe_status")
        in {
            "brep_hotspot_captured_station_edges_valid",
            "brep_hotspot_captured_station_edges_suspect",
            "unavailable",
            "blocked",
        }
    ):
        brep_next_actions = station_seam_brep_hotspot_probe.get("next_actions", [])
        if isinstance(brep_next_actions, list) and brep_next_actions:
            next_actions[0] = str(brep_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_same_parameter_feasibility, dict)
        and station_seam_same_parameter_feasibility.get("feasibility_status")
        in {
            "same_parameter_repair_recovered",
            "same_parameter_repair_not_recovered",
            "unavailable",
            "blocked",
        }
    ):
        same_parameter_next_actions = station_seam_same_parameter_feasibility.get(
            "next_actions",
            [],
        )
        if (
            isinstance(same_parameter_next_actions, list)
            and same_parameter_next_actions
        ):
            next_actions[0] = str(same_parameter_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_shape_fix_feasibility, dict)
        and station_seam_shape_fix_feasibility.get("feasibility_status")
        in {
            "shape_fix_repair_recovered",
            "shape_fix_repair_not_recovered",
            "unavailable",
            "blocked",
        }
    ):
        shape_fix_next_actions = station_seam_shape_fix_feasibility.get(
            "next_actions",
            [],
        )
        if isinstance(shape_fix_next_actions, list) and shape_fix_next_actions:
            next_actions[0] = str(shape_fix_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_export_source_audit, dict)
        and station_seam_export_source_audit.get("audit_status")
        in {
            "single_rule_internal_station_export_source_confirmed",
            "export_source_audit_captured",
            "blocked",
        }
    ):
        export_source_next_actions = station_seam_export_source_audit.get(
            "next_actions",
            [],
        )
        if (
            isinstance(export_source_next_actions, list)
            and export_source_next_actions
        ):
            next_actions[0] = str(export_source_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_export_strategy_probe, dict)
        and station_seam_export_strategy_probe.get("probe_status")
        in {
            "export_strategy_candidate_materialized_needs_brep_validation",
            "export_strategy_candidate_materialized_but_topology_risk",
            "export_strategy_candidate_materialization_failed",
            "export_strategy_candidate_source_only_ready_for_materialization",
            "blocked",
        }
    ):
        export_strategy_next_actions = station_seam_export_strategy_probe.get(
            "next_actions",
            [],
        )
        if (
            isinstance(export_strategy_next_actions, list)
            and export_strategy_next_actions
        ):
            next_actions[0] = str(export_strategy_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_internal_cap_probe, dict)
        and station_seam_internal_cap_probe.get("probe_status")
        in {
            "split_candidate_internal_cap_risk_confirmed",
            "split_candidate_no_internal_caps_detected_needs_mesh_handoff_probe",
            "blocked",
        }
    ):
        internal_cap_next_actions = station_seam_internal_cap_probe.get(
            "next_actions",
            [],
        )
        if (
            isinstance(internal_cap_next_actions, list)
            and internal_cap_next_actions
        ):
            next_actions[0] = str(internal_cap_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_profile_resample_strategy_probe, dict)
        and station_seam_profile_resample_strategy_probe.get("probe_status")
        in {
            "profile_resample_candidate_materialized_needs_brep_validation",
            "profile_resample_candidate_materialized_but_topology_risk",
            "profile_resample_candidate_materialization_failed",
            "profile_resample_candidate_source_only_ready_for_materialization",
            "blocked",
        }
    ):
        profile_next_actions = station_seam_profile_resample_strategy_probe.get(
            "next_actions",
            [],
        )
        if isinstance(profile_next_actions, list) and profile_next_actions:
            next_actions[0] = str(profile_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_profile_resample_brep_validation_probe, dict)
        and station_seam_profile_resample_brep_validation_probe.get("probe_status")
        in {
            "profile_resample_candidate_station_brep_edges_valid",
            "profile_resample_candidate_station_brep_edges_suspect",
            "profile_resample_candidate_station_brep_validation_unavailable",
            "blocked",
        }
    ):
        profile_brep_next_actions = (
            station_seam_profile_resample_brep_validation_probe.get(
                "next_actions",
                [],
            )
        )
        if isinstance(profile_brep_next_actions, list) and profile_brep_next_actions:
            next_actions[0] = str(profile_brep_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_profile_resample_repair_feasibility_probe, dict)
        and station_seam_profile_resample_repair_feasibility_probe.get(
            "feasibility_status"
        )
        in {
            "profile_resample_station_shape_fix_repair_recovered",
            "profile_resample_station_shape_fix_repair_not_recovered",
            "unavailable",
            "blocked",
        }
    ):
        profile_repair_next_actions = (
            station_seam_profile_resample_repair_feasibility_probe.get(
                "next_actions",
                [],
            )
        )
        if (
            isinstance(profile_repair_next_actions, list)
            and profile_repair_next_actions
        ):
            next_actions[0] = str(profile_repair_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_profile_parametrization_audit, dict)
        and station_seam_profile_parametrization_audit.get("audit_status")
        in {
            "profile_parametrization_seam_fragment_correlation_observed",
            "profile_parametrization_audit_captured",
            "blocked",
        }
    ):
        profile_parametrization_next_actions = (
            station_seam_profile_parametrization_audit.get("next_actions", [])
        )
        if (
            isinstance(profile_parametrization_next_actions, list)
            and profile_parametrization_next_actions
        ):
            next_actions[0] = str(profile_parametrization_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_side_aware_parametrization_probe, dict)
        and station_seam_side_aware_parametrization_probe.get("probe_status")
        in {
            "side_aware_parametrization_candidate_materialized_needs_brep_validation",
            "side_aware_parametrization_candidate_topology_risk",
            "side_aware_parametrization_candidate_materialization_failed",
            "side_aware_parametrization_source_only_ready_for_materialization",
            "blocked",
        }
    ):
        side_aware_next_actions = station_seam_side_aware_parametrization_probe.get(
            "next_actions",
            [],
        )
        if isinstance(side_aware_next_actions, list) and side_aware_next_actions:
            next_actions[0] = str(side_aware_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_side_aware_brep_validation_probe, dict)
        and station_seam_side_aware_brep_validation_probe.get("probe_status")
        in {
            "side_aware_candidate_station_brep_edges_valid",
            "side_aware_candidate_station_brep_edges_suspect",
            "side_aware_candidate_station_brep_validation_unavailable",
            "blocked",
        }
    ):
        side_aware_brep_next_actions = (
            station_seam_side_aware_brep_validation_probe.get("next_actions", [])
        )
        if (
            isinstance(side_aware_brep_next_actions, list)
            and side_aware_brep_next_actions
        ):
            next_actions[0] = str(side_aware_brep_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_side_aware_pcurve_residual_diagnostic, dict)
        and station_seam_side_aware_pcurve_residual_diagnostic.get("diagnostic_status")
        in {
            "side_aware_station_pcurve_residuals_sampled_clean",
            "side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail",
            "side_aware_station_pcurve_sampled_residuals_exceed_tolerance",
            "side_aware_station_pcurve_residual_diagnostic_unavailable",
            "blocked",
        }
    ):
        side_aware_pcurve_next_actions = (
            station_seam_side_aware_pcurve_residual_diagnostic.get("next_actions", [])
        )
        if (
            isinstance(side_aware_pcurve_next_actions, list)
            and side_aware_pcurve_next_actions
        ):
            next_actions[0] = str(side_aware_pcurve_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_side_aware_metadata_repair_probe, dict)
        and station_seam_side_aware_metadata_repair_probe.get("metadata_repair_status")
        in {
            "side_aware_station_metadata_repair_recovered",
            "side_aware_station_metadata_repair_not_recovered",
            "side_aware_station_metadata_repair_unavailable",
            "blocked",
        }
    ):
        metadata_next_actions = station_seam_side_aware_metadata_repair_probe.get(
            "next_actions",
            [],
        )
        if isinstance(metadata_next_actions, list) and metadata_next_actions:
            next_actions[0] = str(metadata_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_side_aware_pcurve_metadata_builder_probe, dict)
        and station_seam_side_aware_pcurve_metadata_builder_probe.get(
            "metadata_builder_status"
        )
        in {
            "side_aware_station_pcurve_metadata_builder_recovered",
            "side_aware_station_pcurve_metadata_builder_partial",
            "side_aware_station_pcurve_metadata_builder_not_recovered",
            "side_aware_station_pcurve_metadata_builder_unavailable",
            "blocked",
        }
    ):
        builder_next_actions = (
            station_seam_side_aware_pcurve_metadata_builder_probe.get(
                "next_actions",
                [],
            )
        )
        if isinstance(builder_next_actions, list) and builder_next_actions:
            next_actions[0] = str(builder_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_side_aware_projected_pcurve_builder_probe, dict)
        and station_seam_side_aware_projected_pcurve_builder_probe.get(
            "projected_builder_status"
        )
        in {
            "side_aware_station_projected_pcurve_builder_recovered",
            "side_aware_station_projected_pcurve_builder_partial",
            "side_aware_station_projected_pcurve_builder_not_recovered",
            "side_aware_station_projected_pcurve_builder_unavailable",
            "blocked",
        }
    ):
        projected_builder_next_actions = (
            station_seam_side_aware_projected_pcurve_builder_probe.get(
                "next_actions",
                [],
            )
        )
        if (
            isinstance(projected_builder_next_actions, list)
            and projected_builder_next_actions
        ):
            next_actions[0] = str(projected_builder_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_side_aware_export_opcode_variant_probe, dict)
        and station_seam_side_aware_export_opcode_variant_probe.get(
            "opcode_variant_status"
        )
        in {
            "side_aware_export_opcode_variant_recovered",
            "side_aware_export_opcode_variant_not_recovered",
            "side_aware_export_opcode_variant_source_only_ready_for_materialization",
            "side_aware_export_opcode_variant_materialization_failed",
            "blocked",
        }
    ):
        opcode_variant_next_actions = (
            station_seam_side_aware_export_opcode_variant_probe.get(
                "next_actions",
                [],
            )
        )
        if (
            isinstance(opcode_variant_next_actions, list)
            and opcode_variant_next_actions
        ):
            next_actions[0] = str(opcode_variant_next_actions[0])
    if (
        convergence_blocked
        and solver_lift_acceptance_failed
        and isinstance(station_seam_export_metadata_source_audit, dict)
        and station_seam_export_metadata_source_audit.get("audit_status")
        in {
            "export_metadata_generation_source_boundary_captured",
            "export_metadata_generation_source_boundary_incomplete",
            "blocked",
        }
    ):
        metadata_source_next_actions = (
            station_seam_export_metadata_source_audit.get("next_actions", [])
        )
        if (
            isinstance(metadata_source_next_actions, list)
            and metadata_source_next_actions
        ):
            next_actions[0] = str(metadata_source_next_actions[0])

    return MainWingRouteReadinessReport(
        overall_status=overall_status,
        observed_velocity_mps=observed_velocity,
        hpa_standard_flow_status=hpa_flow_status,
        stages=stages,
        blocking_reasons=blocking_reasons,
        next_actions=next_actions,
        notes=[
            "Synthetic mesh/SU2 stages prove route wiring only; they are not real aircraft CFD evidence.",
            "A materialized SU2 handoff is not a solver run, and a solver run is not convergence.",
            "Lift acceptance is a report-only gate here; main-wing convergence acceptance at V=6.5 m/s still requires CL > 1.0.",
            "VSPAERO panel reference evidence is a lower-order sanity baseline only; it is not high-fidelity CFD.",
            "Surface-force output retention is required before panel/SU2 force breakdown can be used to debug the CL gap.",
            "HPA standard flow is V=6.5 m/s; V=10 artifacts are legacy mismatch evidence only.",
        ],
    )


def _render_markdown(report: MainWingRouteReadinessReport) -> str:
    lines = [
        "# main_wing route readiness v1",
        "",
        f"- overall_status: `{report.overall_status}`",
        f"- hpa_standard_flow_status: `{report.hpa_standard_flow_status}`",
        f"- observed_velocity_mps: `{report.observed_velocity_mps}`",
        "",
        "## Stages",
        "",
        "| stage | status | evidence | artifact |",
        "|---|---|---|---|",
    ]
    for stage in report.stages:
        artifact = "" if stage.artifact_path is None else stage.artifact_path
        lines.append(
            f"| `{stage.stage}` | `{stage.status}` | `{stage.evidence_kind}` | `{artifact}` |"
        )
    lines.extend(["", "## Blocking Reasons", ""])
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in report.notes)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_route_readiness_report(
    out_dir: Path,
    report: MainWingRouteReadinessReport | None = None,
    *,
    report_root: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_main_wing_route_readiness_report(report_root=report_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "main_wing_route_readiness.v1.json"
    markdown_path = out_dir / "main_wing_route_readiness.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
