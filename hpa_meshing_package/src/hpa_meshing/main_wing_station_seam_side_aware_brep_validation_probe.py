from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from .main_wing_station_seam_profile_resample_brep_validation_probe import (
    StationBRepCollector,
    build_main_wing_station_seam_profile_resample_brep_validation_probe_report,
)


SideAwareBRepValidationStatusType = Literal[
    "side_aware_candidate_station_brep_edges_valid",
    "side_aware_candidate_station_brep_edges_suspect",
    "side_aware_candidate_station_brep_validation_unavailable",
    "blocked",
]


class MainWingStationSeamSideAwareBRepValidationProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_side_aware_brep_validation_probe.v1"
    ] = "main_wing_station_seam_side_aware_brep_validation_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_side_aware_candidate_brep_validation"
    ] = "report_only_side_aware_candidate_brep_validation"
    production_default_changed: bool = False
    probe_status: SideAwareBRepValidationStatusType
    side_aware_parametrization_probe_path: str
    candidate_step_path: str | None = None
    target_station_y_m: list[float] = Field(default_factory=list)
    station_tolerance_m: float = 1.0e-4
    target_selection: dict[str, Any] = Field(default_factory=dict)
    hotspot_summary: dict[str, Any] = Field(default_factory=dict)
    station_edge_checks: list[dict[str, Any]] = Field(default_factory=list)
    face_checks: list[dict[str, Any]] = Field(default_factory=list)
    upstream_validation_schema: str | None = None
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_side_aware_parametrization_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_side_aware_parametrization_probe"
        / "main_wing_station_seam_side_aware_parametrization_probe.v1.json"
    )


def _status_from_profile_status(status: str) -> SideAwareBRepValidationStatusType:
    if status == "profile_resample_candidate_station_brep_edges_valid":
        return "side_aware_candidate_station_brep_edges_valid"
    if status == "profile_resample_candidate_station_brep_edges_suspect":
        return "side_aware_candidate_station_brep_edges_suspect"
    if status == "profile_resample_candidate_station_brep_validation_unavailable":
        return "side_aware_candidate_station_brep_validation_unavailable"
    return "blocked"


def _edge_pcurves_present(edge_checks: list[dict[str, Any]]) -> bool:
    return bool(edge_checks) and all(
        check.get("pcurve_presence_complete") is True for check in edge_checks
    )


def _edges_pcurve_consistent(edge_checks: list[dict[str, Any]]) -> bool:
    return bool(edge_checks) and all(
        check.get("pcurve_checks_complete") is True for check in edge_checks
    )


def _faces_closed_connected(face_checks: list[dict[str, Any]]) -> bool:
    return bool(face_checks) and all(
        check.get("wire_order_all_ok") is True
        and check.get("wires_connected") is True
        and check.get("wires_closed") is True
        and check.get("wire_self_intersection_detected") is not True
        for check in face_checks
    )


def _engineering_findings(
    *,
    status: SideAwareBRepValidationStatusType,
    target_selection: dict[str, Any],
    edge_checks: list[dict[str, Any]],
    face_checks: list[dict[str, Any]],
) -> list[str]:
    if status == "blocked":
        return ["side_aware_candidate_brep_validation_blocked"]
    if status == "side_aware_candidate_station_brep_validation_unavailable":
        return ["side_aware_candidate_brep_validation_runtime_unavailable"]
    findings = ["side_aware_candidate_brep_validation_report_captured"]
    if target_selection.get("source_fixture_tags_replayed") is False:
        findings.append("side_aware_station_edges_geometrically_selected")
        findings.append("source_fixture_curve_surface_tags_not_replayed")
    if _edge_pcurves_present(edge_checks):
        findings.append("side_aware_station_edge_pcurves_are_present")
    if _edges_pcurve_consistent(edge_checks):
        findings.append("side_aware_station_edges_are_valid_and_pcurve_consistent")
    else:
        findings.append("side_aware_station_edge_pcurve_consistency_checks_are_suspect")
    if _faces_closed_connected(face_checks):
        findings.append("side_aware_owner_faces_wires_are_closed_connected_and_ordered")
    else:
        findings.append("side_aware_owner_face_or_wire_checks_are_suspect")
    findings.append("side_aware_candidate_still_not_mesh_ready")
    return findings


def _blocking_reasons(
    status: SideAwareBRepValidationStatusType,
) -> list[str]:
    reasons: list[str] = []
    if status == "side_aware_candidate_station_brep_edges_suspect":
        reasons.append("side_aware_candidate_station_brep_pcurve_checks_suspect")
    if status == "side_aware_candidate_station_brep_validation_unavailable":
        reasons.append("side_aware_candidate_brep_validation_runtime_unavailable")
    if status == "blocked":
        reasons.append("side_aware_candidate_brep_validation_blocked")
    reasons.append("side_aware_candidate_mesh_handoff_not_run")
    return reasons


def _next_actions(status: SideAwareBRepValidationStatusType) -> list[str]:
    if status == "side_aware_candidate_station_brep_edges_valid":
        return [
            "compare_side_aware_candidate_mesh_handoff_without_promoting_default",
            "run_station_fixture_topology_trace_on_side_aware_candidate",
            "keep_side_aware_candidate_behind_report_only_gate",
        ]
    if status == "side_aware_candidate_station_brep_edges_suspect":
        return [
            "repair_side_aware_candidate_pcurve_export_before_mesh_handoff",
            "inspect_side_aware_station_y_candidate_edges_in_occt",
        ]
    if status == "side_aware_candidate_station_brep_validation_unavailable":
        return ["restore_ocp_or_gmsh_runtime_before_side_aware_brep_claims"]
    return ["restore_side_aware_candidate_brep_validation_inputs"]


def build_main_wing_station_seam_side_aware_brep_validation_probe_report(
    *,
    side_aware_parametrization_probe_path: Path | None = None,
    candidate_step_path: Path | None = None,
    station_y_targets: list[float] | None = None,
    station_tolerance_m: float = 1.0e-4,
    scale_to_output_units: float = 1.0,
    station_brep_collector: StationBRepCollector | None = None,
) -> MainWingStationSeamSideAwareBRepValidationProbeReport:
    side_aware_path = (
        _default_side_aware_parametrization_probe_path()
        if side_aware_parametrization_probe_path is None
        else side_aware_parametrization_probe_path
    )
    shared_report = (
        build_main_wing_station_seam_profile_resample_brep_validation_probe_report(
            profile_resample_probe_path=side_aware_path,
            candidate_step_path=candidate_step_path,
            station_y_targets=station_y_targets,
            station_tolerance_m=station_tolerance_m,
            scale_to_output_units=scale_to_output_units,
            station_brep_collector=station_brep_collector,
        )
    )
    status = _status_from_profile_status(shared_report.probe_status)
    return MainWingStationSeamSideAwareBRepValidationProbeReport(
        probe_status=status,
        side_aware_parametrization_probe_path=str(side_aware_path),
        candidate_step_path=shared_report.candidate_step_path,
        target_station_y_m=shared_report.target_station_y_m,
        station_tolerance_m=shared_report.station_tolerance_m,
        target_selection=shared_report.target_selection,
        hotspot_summary=shared_report.hotspot_summary,
        station_edge_checks=shared_report.station_edge_checks,
        face_checks=shared_report.face_checks,
        upstream_validation_schema=shared_report.schema_version,
        engineering_findings=_engineering_findings(
            status=status,
            target_selection=shared_report.target_selection,
            edge_checks=shared_report.station_edge_checks,
            face_checks=shared_report.face_checks,
        ),
        blocking_reasons=_blocking_reasons(status),
        next_actions=_next_actions(status),
        limitations=[
            "This probe validates the side-aware parametrization candidate STEP only; it does not change production defaults.",
            "Station targets are selected geometrically from candidate topology, not replayed from old fixture curve or surface tags.",
            "It reuses the shared station-y BRep collector; the side-aware schema prevents the artifact from being confused with the earlier uniform profile-resample candidate.",
            "It does not run Gmsh volume mesh generation, SU2_CFD, CL acceptance, or convergence checks.",
            "A side-aware candidate with valid gross topology is still not mesh-ready unless station-edge PCurve consistency passes.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingStationSeamSideAwareBRepValidationProbeReport,
) -> str:
    lines = [
        "# Main Wing Station Seam Side-Aware BRep Validation Probe v1",
        "",
        "This report validates station-y BRep/PCurve checks on the side-aware candidate STEP without replaying old curve or surface tags.",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- side_aware_parametrization_probe_path: `{report.side_aware_parametrization_probe_path}`",
        f"- candidate_step_path: `{report.candidate_step_path}`",
        f"- target_station_y_m: `{_fmt(report.target_station_y_m)}`",
        f"- station_tolerance_m: `{report.station_tolerance_m}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        f"- upstream_validation_schema: `{report.upstream_validation_schema}`",
        "",
        "## Target Selection",
        "",
        f"- `{_fmt(report.target_selection)}`",
        "",
        "## Hotspot Summary",
        "",
    ]
    for key, value in report.hotspot_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Station Edge Checks", ""])
    if report.station_edge_checks:
        lines.extend(f"- `{_fmt(item)}`" for item in report.station_edge_checks)
    else:
        lines.append("- none")
    lines.extend(["", "## Face Checks", ""])
    if report.face_checks:
        lines.extend(f"- `{_fmt(item)}`" for item in report.face_checks)
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


def write_main_wing_station_seam_side_aware_brep_validation_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamSideAwareBRepValidationProbeReport | None = None,
    side_aware_parametrization_probe_path: Path | None = None,
    candidate_step_path: Path | None = None,
    station_y_targets: list[float] | None = None,
    station_tolerance_m: float = 1.0e-4,
    scale_to_output_units: float = 1.0,
    station_brep_collector: StationBRepCollector | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_side_aware_brep_validation_probe_report(
            side_aware_parametrization_probe_path=side_aware_parametrization_probe_path,
            candidate_step_path=candidate_step_path,
            station_y_targets=station_y_targets,
            station_tolerance_m=station_tolerance_m,
            scale_to_output_units=scale_to_output_units,
            station_brep_collector=station_brep_collector,
        )
    json_path = out_dir / "main_wing_station_seam_side_aware_brep_validation_probe.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_side_aware_brep_validation_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
