from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


RepairDecisionStatusType = Literal[
    "station_seam_repair_required_before_solver_budget",
    "no_station_seam_repair_required",
    "blocked",
]

MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 = 1.0


class MainWingStationSeamRepairDecisionReport(BaseModel):
    schema_version: Literal["main_wing_station_seam_repair_decision.v1"] = (
        "main_wing_station_seam_repair_decision.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["decision_from_station_topology_fixture"] = (
        "decision_from_station_topology_fixture"
    )
    production_default_changed: bool = False
    repair_decision_status: RepairDecisionStatusType
    topology_fixture_path: str
    solver_report_path: str
    topology_fixture_observed: Dict[str, Any] = Field(default_factory=dict)
    solver_context_observed: Dict[str, Any] = Field(default_factory=dict)
    decision_rationale: List[str] = Field(default_factory=list)
    repair_candidate_requirements: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_topology_fixture_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_openvsp_section_station_topology_fixture"
        / "main_wing_openvsp_section_station_topology_fixture.v1.json"
    )


def _default_solver_report_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_openvsp_reference_solver_smoke_probe_iter80"
        / "main_wing_real_solver_smoke_probe.v1.json"
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


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _as_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    return sorted(int(value) for value in values if isinstance(value, int))


def _topology_fixture_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"topology_fixture_status": None}
    summary = payload.get("fixture_summary", {})
    summary = summary if isinstance(summary, dict) else {}
    return {
        "topology_fixture_status": payload.get("topology_fixture_status"),
        "station_fixture_count": summary.get("station_fixture_count"),
        "total_boundary_edge_count": summary.get("total_boundary_edge_count"),
        "total_nonmanifold_edge_count": summary.get("total_nonmanifold_edge_count"),
        "candidate_curve_tags": _as_int_list(summary.get("candidate_curve_tags")),
        "source_section_indices": _as_int_list(summary.get("source_section_indices")),
        "all_cases_violate_canonical_station_topology_contract": summary.get(
            "all_cases_violate_canonical_station_topology_contract"
        ),
    }


def _lift_acceptance_status(payload: dict[str, Any]) -> str:
    reported = payload.get("main_wing_lift_acceptance_status")
    if reported in {"pass", "fail", "not_evaluated"}:
        return str(reported)
    velocity = _as_float(payload.get("observed_velocity_mps"))
    coefficients = payload.get("final_coefficients", {})
    cl = _as_float(coefficients.get("cl")) if isinstance(coefficients, dict) else None
    if velocity is None or abs(velocity - 6.5) > 1.0e-9 or cl is None:
        return "not_evaluated"
    return "pass" if cl > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 else "fail"


def _solver_context_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"solver_execution_status": None}
    coefficients = payload.get("final_coefficients", {})
    cl = _as_float(coefficients.get("cl")) if isinstance(coefficients, dict) else None
    return {
        "solver_execution_status": payload.get("solver_execution_status"),
        "convergence_gate_status": payload.get("convergence_gate_status"),
        "run_status": payload.get("run_status"),
        "observed_velocity_mps": _as_float(payload.get("observed_velocity_mps")),
        "main_wing_lift_acceptance_status": _lift_acceptance_status(payload),
        "minimum_acceptable_cl": payload.get(
            "minimum_acceptable_cl",
            MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5,
        ),
        "final_cl": cl,
        "final_coefficients": coefficients if isinstance(coefficients, dict) else {},
    }


def _fixture_violates_contract(observed: dict[str, Any]) -> bool:
    boundary_count = observed.get("total_boundary_edge_count")
    nonmanifold_count = observed.get("total_nonmanifold_edge_count")
    return (
        observed.get("topology_fixture_status")
        == "real_defect_station_fixture_materialized"
        and (
            (isinstance(boundary_count, int) and boundary_count > 0)
            or (isinstance(nonmanifold_count, int) and nonmanifold_count > 0)
            or observed.get(
                "all_cases_violate_canonical_station_topology_contract"
            )
            is True
        )
    )


def _status(
    blockers: list[str],
    topology_observed: dict[str, Any],
) -> RepairDecisionStatusType:
    if blockers:
        return "blocked"
    if _fixture_violates_contract(topology_observed):
        return "station_seam_repair_required_before_solver_budget"
    return "no_station_seam_repair_required"


def _decision_rationale(
    status: RepairDecisionStatusType,
    solver_observed: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["station_seam_repair_decision_inputs_missing"]
    if status == "no_station_seam_repair_required":
        return ["station_topology_fixture_does_not_require_repair"]
    rationale = [
        "station_topology_contract_violated_by_real_fixture",
        "boundary_or_nonmanifold_station_edges_are_geometry_route_risk",
    ]
    if (
        solver_observed.get("observed_velocity_mps") == 6.5
        and solver_observed.get("main_wing_lift_acceptance_status") == "fail"
    ):
        rationale.append(
            "solver_budget_is_not_primary_next_gate_while_station_fixture_fails"
        )
    if solver_observed.get("convergence_gate_status") in {"fail", "warn", "unavailable"}:
        rationale.append("solver_execution_is_not_convergence_evidence")
    return rationale


def _curve_tag_suffix(curve_tags: list[int]) -> str:
    return "_".join(str(tag) for tag in curve_tags) if curve_tags else "unknown"


def _repair_candidate_requirements(
    status: RepairDecisionStatusType,
    topology_observed: dict[str, Any],
) -> list[str]:
    if status != "station_seam_repair_required_before_solver_budget":
        return []
    curve_tags = _as_int_list(topology_observed.get("candidate_curve_tags"))
    suffix = _curve_tag_suffix(curve_tags)
    return [
        f"eliminate_boundary_and_nonmanifold_edges_at_station_curve_tags_{suffix}",
        "preserve_main_wing_force_marker_ownership",
        f"preserve_openvsp_section_profile_scale_for_curve_tags_{suffix}",
        "rerun_station_fixture_and_gmsh_defect_trace_before_solver_budget_claims",
        "do_not_use_surface_id_patch_as_route_repair",
    ]


def _blocking_reasons(status: RepairDecisionStatusType) -> list[str]:
    if status == "station_seam_repair_required_before_solver_budget":
        return ["station_seam_repair_required_before_solver_budget"]
    if status == "blocked":
        return ["station_seam_repair_decision_blocked"]
    return []


def _next_actions(status: RepairDecisionStatusType) -> list[str]:
    if status == "blocked":
        return ["restore_station_seam_repair_decision_inputs"]
    if status == "no_station_seam_repair_required":
        return ["continue_with_source_backed_solver_budget_after_geometry_audit"]
    return [
        "prototype_station_seam_repair_against_minimal_fixture",
        "run_main_wing_gmsh_defect_entity_trace_on_repair_candidate",
        "keep_solver_budget_source_backed_after_geometry_topology_gate",
    ]


def build_main_wing_station_seam_repair_decision_report(
    *,
    topology_fixture_path: Path | None = None,
    solver_report_path: Path | None = None,
) -> MainWingStationSeamRepairDecisionReport:
    fixture_path = (
        _default_topology_fixture_path()
        if topology_fixture_path is None
        else topology_fixture_path
    )
    solver_path = _default_solver_report_path() if solver_report_path is None else solver_report_path
    blockers: list[str] = []
    fixture_payload = _load_json(fixture_path, blockers, "topology_fixture")
    solver_payload = _load_json(solver_path, blockers, "solver_report")
    topology_observed = _topology_fixture_observed(fixture_payload)
    solver_observed = _solver_context_observed(solver_payload)
    status = _status(blockers, topology_observed)
    return MainWingStationSeamRepairDecisionReport(
        repair_decision_status=status,
        topology_fixture_path=str(fixture_path),
        solver_report_path=str(solver_path),
        topology_fixture_observed=topology_observed,
        solver_context_observed=solver_observed,
        decision_rationale=_decision_rationale(status, solver_observed),
        repair_candidate_requirements=_repair_candidate_requirements(
            status,
            topology_observed,
        ),
        blocking_reasons=[*blockers, *_blocking_reasons(status)],
        next_actions=_next_actions(status),
        limitations=[
            "This is a decision gate only; it does not modify Gmsh, OpenVSP, or SU2 inputs.",
            "A required repair decision is a route blocker, not evidence that the geometry has been repaired.",
            "Solver execution remains non-convergence evidence unless the convergence and CL gates pass under source-backed settings.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(report: MainWingStationSeamRepairDecisionReport) -> str:
    lines = [
        "# Main Wing Station Seam Repair Decision v1",
        "",
        "This decision gate decides whether station topology repair must precede more solver budget.",
        "",
        f"- repair_decision_status: `{report.repair_decision_status}`",
        f"- topology_fixture_path: `{report.topology_fixture_path}`",
        f"- solver_report_path: `{report.solver_report_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Topology Fixture Observed",
        "",
    ]
    for key, value in report.topology_fixture_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Solver Context Observed", ""])
    for key, value in report.solver_context_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Decision Rationale", ""])
    lines.extend(f"- `{reason}`" for reason in report.decision_rationale)
    lines.extend(["", "## Repair Candidate Requirements", ""])
    if report.repair_candidate_requirements:
        lines.extend(f"- `{item}`" for item in report.repair_candidate_requirements)
    else:
        lines.append("- none")
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


def write_main_wing_station_seam_repair_decision_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamRepairDecisionReport | None = None,
    topology_fixture_path: Path | None = None,
    solver_report_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_repair_decision_report(
            topology_fixture_path=topology_fixture_path,
            solver_report_path=solver_report_path,
        )
    json_path = out_dir / "main_wing_station_seam_repair_decision.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_repair_decision.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
