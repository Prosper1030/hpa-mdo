from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


StageType = Literal[
    "real_geometry",
    "real_mesh_handoff",
    "synthetic_mesh_handoff",
    "synthetic_su2_handoff",
    "real_su2_handoff",
    "openvsp_reference_su2_handoff",
    "openvsp_reference_solver_smoke",
    "openvsp_reference_solver_budget_probe",
    "solver_smoke",
    "solver_budget_probe",
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
    synthetic_su2_runtime_path = (
        root
        / "main_wing_su2_handoff_smoke"
        / "artifacts"
        / "su2"
        / "alpha_0_materialization_smoke"
        / "su2_handoff.json"
    )

    real_geometry = _load_json(real_geometry_path)
    real_mesh = _load_json(real_mesh_path)
    synthetic_mesh = _load_json(synthetic_mesh_path)
    synthetic_su2 = _load_json(synthetic_su2_path)
    real_su2 = _load_json(real_su2_path)
    openvsp_reference_su2 = _load_json(openvsp_reference_su2_path)
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
    convergence_pass = solver_executed and convergence_status == "pass"
    convergence_blocked = solver_executed and convergence_status in {"warn", "fail", "unavailable"}

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
            observed={
                "solver_execution_status": (
                    None
                    if openvsp_reference_solver is None
                    else openvsp_reference_solver.get("solver_execution_status")
                )
                or "not_run",
                "run_status": (
                    None
                    if openvsp_reference_solver is None
                    else openvsp_reference_solver.get("run_status")
                ),
                "convergence_gate_status": (
                    None
                    if openvsp_reference_solver is None
                    else openvsp_reference_solver.get("convergence_gate_status")
                ),
                "convergence_comparability_level": (
                    None
                    if openvsp_reference_solver is None
                    else openvsp_reference_solver.get("convergence_comparability_level")
                ),
                "final_iteration": (
                    None
                    if openvsp_reference_solver is None
                    else openvsp_reference_solver.get("final_iteration")
                ),
                "final_coefficients": (
                    {}
                    if openvsp_reference_solver is None
                    else openvsp_reference_solver.get("final_coefficients", {})
                ),
                "observed_velocity_mps": (
                    None
                    if openvsp_reference_solver is None
                    else openvsp_reference_solver.get("observed_velocity_mps")
                ),
            },
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
                "solver_execution_status": (
                    None if solver_smoke is None else solver_smoke.get("solver_execution_status")
                )
                or "not_run",
                "run_status": None if solver_smoke is None else solver_smoke.get("run_status"),
                "return_code": None if solver_smoke is None else solver_smoke.get("return_code"),
                "history_path": None if solver_smoke is None else solver_smoke.get("history_path"),
                "solver_log_path": (
                    None if solver_smoke is None else solver_smoke.get("solver_log_path")
                ),
                "observed_velocity_mps": (
                    None if solver_smoke is None else solver_smoke.get("observed_velocity_mps")
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
                _blocking_reasons(solver_smoke)
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
