from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


ProbeStatusType = Literal[
    "brep_hotspot_captured_station_edges_valid",
    "brep_hotspot_captured_station_edges_suspect",
    "unavailable",
    "blocked",
]

HotspotReportCollector = Callable[..., Dict[str, Any]]


class MainWingStationSeamBRepHotspotProbeReport(BaseModel):
    schema_version: Literal["main_wing_station_seam_brep_hotspot_probe.v1"] = (
        "main_wing_station_seam_brep_hotspot_probe.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_station_seam_brep_hotspot_probe"] = (
        "report_only_station_seam_brep_hotspot_probe"
    )
    production_default_changed: bool = False
    probe_status: ProbeStatusType
    topology_fixture_path: str
    real_mesh_probe_report_path: str
    normalized_step_path: str | None = None
    surface_patch_diagnostics_path: str | None = None
    requested_curve_tags: List[int] = Field(default_factory=list)
    requested_surface_tags: List[int] = Field(default_factory=list)
    station_fixture_observed: Dict[str, Any] = Field(default_factory=dict)
    brep_hotspot_summary: Dict[str, Any] = Field(default_factory=dict)
    curve_checks: List[Dict[str, Any]] = Field(default_factory=list)
    face_checks: List[Dict[str, Any]] = Field(default_factory=list)
    prototype_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    engineering_findings: List[str] = Field(default_factory=list)
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


def _default_real_mesh_probe_report_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )


def _default_normalized_step_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_real_mesh_handoff_probe"
        / "artifacts"
        / "real_mesh_probe"
        / "artifacts"
        / "providers"
        / "esp_rebuilt"
        / "esp_runtime"
        / "normalized.stp"
    )


def _default_surface_patch_diagnostics_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_real_mesh_handoff_probe"
        / "artifacts"
        / "real_mesh_probe"
        / "artifacts"
        / "mesh"
        / "surface_patch_diagnostics.json"
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


def _resolve_path(value: Any, fallback: Path) -> Path:
    if value is None or value == "":
        return fallback
    path = Path(str(value))
    return path if path.is_absolute() else _repo_root() / path


def _as_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    tags: set[int] = set()
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            tags.add(int(value))
    return sorted(tags)


def _station_fixture_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
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
        "owner_surface_entity_tags": _as_int_list(
            summary.get("owner_surface_entity_tags")
        ),
        "source_section_indices": _as_int_list(summary.get("source_section_indices")),
    }


def _candidate_surface_groups(payload: dict[str, Any] | None) -> list[list[int]]:
    if not isinstance(payload, dict):
        return []
    groups: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    for case in payload.get("station_fixture_cases", []):
        if not isinstance(case, dict):
            continue
        group = _as_int_list(case.get("owner_surface_entity_tags"))
        if len(group) < 2:
            continue
        key = tuple(group)
        if key not in seen:
            groups.append(group)
            seen.add(key)
    return groups


def _all_mapping_values_true(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _relative_delta(lhs: Any, rhs: Any) -> float | None:
    if isinstance(lhs, bool) or isinstance(rhs, bool):
        return None
    try:
        lhs_float = float(lhs)
        rhs_float = float(rhs)
    except (TypeError, ValueError):
        return None
    scale = max(abs(lhs_float), abs(rhs_float), 1.0e-12)
    return abs(lhs_float - rhs_float) / scale


def _curve_check(curve_report: dict[str, Any]) -> dict[str, Any]:
    pcurve_presence_complete = _all_mapping_values_true(
        curve_report.get("pcurve_presence_by_face")
    )
    curve3d_with_pcurve_consistent = _all_mapping_values_true(
        curve_report.get("check_curve3d_with_pcurve_by_face")
    )
    same_parameter_by_face_ok = _all_mapping_values_true(
        curve_report.get("check_same_parameter_by_face")
    )
    vertex_tolerance_by_face_ok = _all_mapping_values_true(
        curve_report.get("check_vertex_tolerance_by_face")
    )
    pcurve_range_matches_edge_range = _all_mapping_values_true(
        curve_report.get("pcurve_range_matches_edge_range_by_face")
    )
    pcurve_checks_complete = (
        pcurve_presence_complete
        and curve3d_with_pcurve_consistent
        and same_parameter_by_face_ok
        and vertex_tolerance_by_face_ok
        and pcurve_range_matches_edge_range
    )
    brepcheck = curve_report.get("brepcheck", {})
    brepcheck = brepcheck if isinstance(brepcheck, dict) else {}
    length_delta = _relative_delta(
        curve_report.get("gmsh_length_3d"),
        curve_report.get("edge_length_3d"),
    )
    return {
        "curve_id": curve_report.get("curve_id"),
        "owner_surface_tags": _as_int_list(curve_report.get("owner_surface_tags")),
        "gmsh_length_3d_m": curve_report.get("gmsh_length_3d"),
        "edge_length_3d_m": curve_report.get("edge_length_3d"),
        "length_relative_delta": length_delta,
        "match_score": curve_report.get("match_score"),
        "mapped_edge_index": curve_report.get("mapped_edge_index"),
        "ancestor_face_ids": _as_int_list(curve_report.get("ancestor_face_ids")),
        "pcurve_presence_complete": pcurve_presence_complete,
        "curve3d_with_pcurve_consistent": curve3d_with_pcurve_consistent,
        "same_parameter_by_face_ok": same_parameter_by_face_ok,
        "vertex_tolerance_by_face_ok": vertex_tolerance_by_face_ok,
        "pcurve_range_matches_edge_range": pcurve_range_matches_edge_range,
        "pcurve_checks_complete": pcurve_checks_complete,
        "same_parameter_flag": curve_report.get("same_parameter_flag"),
        "same_range_flag": curve_report.get("same_range_flag"),
        "brep_valid_default": brepcheck.get("valid_default"),
        "brep_valid_exact": brepcheck.get("valid_exact"),
    }


def _face_check(face_report: dict[str, Any]) -> dict[str, Any]:
    brepcheck = face_report.get("brepcheck", {})
    brepcheck = brepcheck if isinstance(brepcheck, dict) else {}
    wires = [
        wire
        for wire in face_report.get("wire_reports", [])
        if isinstance(wire, dict)
    ]
    return {
        "surface_id": face_report.get("surface_id"),
        "brep_valid_default": brepcheck.get("valid_default"),
        "brep_valid_exact": brepcheck.get("valid_exact"),
        "wire_count": len(wires),
        "wire_order_all_ok": bool(wires)
        and all(wire.get("wire_order_ok") is True for wire in wires),
        "wires_connected": bool(wires)
        and all(wire.get("wire_connected") is True for wire in wires),
        "wires_closed": bool(wires)
        and all(wire.get("wire_closed") is True for wire in wires),
        "wire_self_intersection_detected": any(
            wire.get("wire_self_intersection") is True for wire in wires
        ),
        "small_face_analysis": face_report.get("small_face_analysis", {}),
    }


def _curves_are_valid(curve_checks: list[dict[str, Any]]) -> bool:
    if not curve_checks:
        return False
    for check in curve_checks:
        if check.get("mapped_edge_index") is None:
            return False
        if check.get("pcurve_checks_complete") is not True:
            return False
        if check.get("same_parameter_flag") is not True:
            return False
        if check.get("same_range_flag") is not True:
            return False
        if check.get("brep_valid_default") is not True:
            return False
        if check.get("brep_valid_exact") is not True:
            return False
        length_delta = check.get("length_relative_delta")
        if isinstance(length_delta, float) and length_delta > 1.0e-5:
            return False
    return True


def _curves_map_to_edges(curve_checks: list[dict[str, Any]]) -> bool:
    if not curve_checks:
        return False
    for check in curve_checks:
        if check.get("mapped_edge_index") is None:
            return False
        if check.get("brep_valid_default") is not True:
            return False
        if check.get("brep_valid_exact") is not True:
            return False
        length_delta = check.get("length_relative_delta")
        if isinstance(length_delta, float) and length_delta > 1.0e-5:
            return False
    return True


def _curve_pcurves_present(curve_checks: list[dict[str, Any]]) -> bool:
    return bool(curve_checks) and all(
        check.get("pcurve_presence_complete") is True for check in curve_checks
    )


def _faces_are_valid(face_checks: list[dict[str, Any]]) -> bool:
    if not face_checks:
        return False
    for check in face_checks:
        if check.get("brep_valid_default") is not True:
            return False
        if check.get("brep_valid_exact") is not True:
            return False
        if check.get("wire_order_all_ok") is not True:
            return False
        if check.get("wires_connected") is not True:
            return False
        if check.get("wires_closed") is not True:
            return False
        if check.get("wire_self_intersection_detected") is True:
            return False
    return True


def _probe_status(
    *,
    blockers: list[str],
    hotspot_report: dict[str, Any],
    curve_checks: list[dict[str, Any]],
    face_checks: list[dict[str, Any]],
) -> ProbeStatusType:
    if blockers:
        return "blocked"
    hotspot_status = hotspot_report.get("status")
    if hotspot_status == "unavailable":
        return "unavailable"
    if hotspot_status != "captured":
        return "blocked"
    if (
        hotspot_report.get("shape_valid_default") is True
        and hotspot_report.get("shape_valid_exact") is True
        and _curves_are_valid(curve_checks)
        and _faces_are_valid(face_checks)
    ):
        return "brep_hotspot_captured_station_edges_valid"
    return "brep_hotspot_captured_station_edges_suspect"


def _prototype_candidates(surface_groups: list[list[int]]) -> list[dict[str, Any]]:
    if not surface_groups:
        return []
    return [
        {
            "candidate_name": "station_owner_surface_compound_meshing_policy_v0",
            "prototype_status": "prototype_not_applied",
            "candidate_scope": "localized_station_owner_surface_meshing_probe",
            "config_metadata": {
                "mesh_compound_enabled": True,
                "mesh_compound_policy_name": "main_wing_station_owner_surface_compound_v0",
                "mesh_compound_surface_groups": surface_groups,
                "mesh_compound_curve_groups": [],
                "mesh_compound_classify": 1,
            },
            "validation_gate": {
                "rerun": [
                    "main-wing-real-mesh-handoff-probe",
                    "main-wing-gmsh-defect-entity-trace",
                    "main-wing-openvsp-section-station-topology-fixture",
                ],
                "required_observation": (
                    "station fixture boundary/nonmanifold edge counts drop to zero "
                    "without losing main_wing wall marker ownership"
                ),
            },
            "notes": [
                "This is a meshing-policy experiment proposal, not a production default.",
                "Curve compound groups are intentionally omitted because each station target is a single closed loop tag in this evidence packet.",
            ],
        }
    ]


def _engineering_findings(
    status: ProbeStatusType,
    curve_checks: list[dict[str, Any]],
    face_checks: list[dict[str, Any]],
) -> list[str]:
    if status == "blocked":
        return ["station_seam_brep_hotspot_probe_blocked"]
    if status == "unavailable":
        return ["station_seam_brep_hotspot_runtime_unavailable"]
    findings = ["station_seam_brep_hotspot_report_captured"]
    if _curves_map_to_edges(curve_checks):
        findings.append("station_curve_brep_edges_map_to_gmsh_curves_after_mm_to_m_scale")
    if _curve_pcurves_present(curve_checks):
        findings.append("station_curve_pcurves_are_present")
    if _curves_are_valid(curve_checks):
        findings.append("station_curve_brep_edges_are_valid_and_pcurve_consistent")
        findings.append("station_fixture_failure_not_explained_by_missing_brep_pcurves")
    else:
        if _curve_pcurves_present(curve_checks):
            findings.append("station_curve_pcurve_consistency_checks_are_suspect")
            findings.append(
                "station_fixture_failure_not_explained_by_missing_brep_pcurves"
            )
        else:
            findings.append("station_curve_pcurves_missing_or_unmapped")
    if _faces_are_valid(face_checks):
        findings.append("owner_surface_wires_are_closed_connected_and_ordered")
    else:
        findings.append("owner_surface_wire_or_face_checks_are_suspect")
    findings.append(
        "repair_should_target_gmsh_meshing_or_station_surface_connectivity_before_solver_budget"
    )
    return findings


def _blocking_reasons(status: ProbeStatusType, blockers: list[str]) -> list[str]:
    reasons = list(blockers)
    if status == "blocked" and not reasons:
        reasons.append("station_seam_brep_hotspot_probe_blocked")
    if status == "unavailable":
        reasons.append("station_seam_brep_hotspot_runtime_unavailable")
    if status == "brep_hotspot_captured_station_edges_suspect":
        reasons.append("station_seam_brep_hotspot_suspect")
    return reasons


def _next_actions(status: ProbeStatusType) -> list[str]:
    if status == "brep_hotspot_captured_station_edges_valid":
        return [
            "prototype_station_owner_surface_compound_meshing_policy_against_fixture",
            "rerun_main_wing_gmsh_defect_entity_trace_on_repair_candidate",
            "keep_solver_budget_source_backed_after_geometry_topology_gate",
        ]
    if status == "brep_hotspot_captured_station_edges_suspect":
        return [
            "inspect_station_curve_pcurve_consistency_before_meshing_policy",
            "rerun_brep_hotspot_probe_after_geometry_export_repair",
        ]
    if status == "unavailable":
        return ["restore_ocp_runtime_before_brep_hotspot_claims"]
    return ["restore_station_seam_brep_hotspot_probe_inputs"]


def _default_hotspot_report_collector() -> HotspotReportCollector:
    from .adapters.gmsh_backend import _collect_brep_hotspot_report

    return _collect_brep_hotspot_report


def build_main_wing_station_seam_brep_hotspot_probe_report(
    *,
    topology_fixture_path: Path | None = None,
    real_mesh_probe_report_path: Path | None = None,
    normalized_step_path: Path | None = None,
    surface_patch_diagnostics_path: Path | None = None,
    requested_curve_tags: list[int] | None = None,
    requested_surface_tags: list[int] | None = None,
    scale_to_output_units: float = 0.001,
    hotspot_report_collector: HotspotReportCollector | None = None,
) -> MainWingStationSeamBRepHotspotProbeReport:
    fixture_path = (
        _default_topology_fixture_path()
        if topology_fixture_path is None
        else topology_fixture_path
    )
    real_mesh_path = (
        _default_real_mesh_probe_report_path()
        if real_mesh_probe_report_path is None
        else real_mesh_probe_report_path
    )
    blockers: list[str] = []
    fixture_payload = _load_json(fixture_path, blockers, "topology_fixture")
    real_mesh_payload = _load_json(real_mesh_path, blockers, "real_mesh_probe_report")
    station_observed = _station_fixture_observed(fixture_payload)
    curve_tags = (
        sorted(int(tag) for tag in requested_curve_tags)
        if requested_curve_tags is not None
        else _as_int_list(station_observed.get("candidate_curve_tags"))
    )
    surface_tags = (
        sorted(int(tag) for tag in requested_surface_tags)
        if requested_surface_tags is not None
        else _as_int_list(station_observed.get("owner_surface_entity_tags"))
    )

    mesh_payload = real_mesh_payload if isinstance(real_mesh_payload, dict) else {}
    step_path = (
        normalized_step_path
        if normalized_step_path is not None
        else _resolve_path(
            mesh_payload.get("normalized_geometry_path"),
            _default_normalized_step_path(),
        )
    )
    diagnostics_path = (
        surface_patch_diagnostics_path
        if surface_patch_diagnostics_path is not None
        else _resolve_path(
            mesh_payload.get("surface_patch_diagnostics_path"),
            _default_surface_patch_diagnostics_path(),
        )
    )
    if not step_path.exists():
        blockers.append("normalized_step_missing")
    surface_patch_diagnostics = _load_json(
        diagnostics_path,
        blockers,
        "surface_patch_diagnostics",
    )

    hotspot_report: dict[str, Any] = {}
    if not blockers:
        collector = hotspot_report_collector or _default_hotspot_report_collector()
        hotspot_report = collector(
            step_path=step_path,
            surface_patch_diagnostics=surface_patch_diagnostics,
            requested_surface_tags=surface_tags,
            requested_curve_tags=curve_tags,
            scale_to_output_units=scale_to_output_units,
            output_units="m",
        )
    curve_checks = [
        _curve_check(curve_report)
        for curve_report in hotspot_report.get("curve_reports", [])
        if isinstance(curve_report, dict)
    ]
    face_checks = [
        _face_check(face_report)
        for face_report in hotspot_report.get("face_reports", [])
        if isinstance(face_report, dict)
    ]
    status = _probe_status(
        blockers=blockers,
        hotspot_report=hotspot_report,
        curve_checks=curve_checks,
        face_checks=face_checks,
    )
    return MainWingStationSeamBRepHotspotProbeReport(
        probe_status=status,
        topology_fixture_path=str(fixture_path),
        real_mesh_probe_report_path=str(real_mesh_path),
        normalized_step_path=str(step_path) if step_path is not None else None,
        surface_patch_diagnostics_path=(
            str(diagnostics_path) if diagnostics_path is not None else None
        ),
        requested_curve_tags=curve_tags,
        requested_surface_tags=surface_tags,
        station_fixture_observed=station_observed,
        brep_hotspot_summary={
            "hotspot_status": hotspot_report.get("status"),
            "shape_valid_default": hotspot_report.get("shape_valid_default"),
            "shape_valid_exact": hotspot_report.get("shape_valid_exact"),
            "scale_to_output_units": hotspot_report.get(
                "scale_to_output_units",
                scale_to_output_units,
            ),
            "selected_curve_tags": hotspot_report.get("selected_curve_tags", []),
            "selected_surface_tags": hotspot_report.get("selected_surface_tags", []),
            "curve_report_count": len(curve_checks),
            "face_report_count": len(face_checks),
        },
        curve_checks=curve_checks,
        face_checks=face_checks,
        prototype_candidates=_prototype_candidates(_candidate_surface_groups(fixture_payload)),
        engineering_findings=_engineering_findings(status, curve_checks, face_checks),
        blocking_reasons=_blocking_reasons(status, blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This probe reads existing real-route STEP and Gmsh diagnostic artifacts only.",
            "It does not run Gmsh, does not run SU2_CFD, and does not evaluate CL or convergence.",
            "A valid station BRep hotspot report does not prove the real mesh topology has been repaired.",
            "Prototype candidates are not applied and do not change production defaults.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(report: MainWingStationSeamBRepHotspotProbeReport) -> str:
    lines = [
        "# Main Wing Station Seam BRep Hotspot Probe v1",
        "",
        "This report localizes the station seam blocker at the STEP/BRep hotspot layer without changing meshing defaults.",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- topology_fixture_path: `{report.topology_fixture_path}`",
        f"- real_mesh_probe_report_path: `{report.real_mesh_probe_report_path}`",
        f"- normalized_step_path: `{report.normalized_step_path}`",
        f"- surface_patch_diagnostics_path: `{report.surface_patch_diagnostics_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Station Fixture Observed",
        "",
    ]
    for key, value in report.station_fixture_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## BRep Hotspot Summary", ""])
    for key, value in report.brep_hotspot_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Curve Checks", ""])
    if report.curve_checks:
        lines.extend(f"- `{_fmt(item)}`" for item in report.curve_checks)
    else:
        lines.append("- none")
    lines.extend(["", "## Face Checks", ""])
    if report.face_checks:
        lines.extend(f"- `{_fmt(item)}`" for item in report.face_checks)
    else:
        lines.append("- none")
    lines.extend(["", "## Prototype Candidates", ""])
    if report.prototype_candidates:
        lines.extend(f"- `{_fmt(item)}`" for item in report.prototype_candidates)
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


def write_main_wing_station_seam_brep_hotspot_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamBRepHotspotProbeReport | None = None,
    topology_fixture_path: Path | None = None,
    real_mesh_probe_report_path: Path | None = None,
    normalized_step_path: Path | None = None,
    surface_patch_diagnostics_path: Path | None = None,
    requested_curve_tags: list[int] | None = None,
    requested_surface_tags: list[int] | None = None,
    scale_to_output_units: float = 0.001,
    hotspot_report_collector: HotspotReportCollector | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_brep_hotspot_probe_report(
            topology_fixture_path=topology_fixture_path,
            real_mesh_probe_report_path=real_mesh_probe_report_path,
            normalized_step_path=normalized_step_path,
            surface_patch_diagnostics_path=surface_patch_diagnostics_path,
            requested_curve_tags=requested_curve_tags,
            requested_surface_tags=requested_surface_tags,
            scale_to_output_units=scale_to_output_units,
            hotspot_report_collector=hotspot_report_collector,
        )
    json_path = out_dir / "main_wing_station_seam_brep_hotspot_probe.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_brep_hotspot_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
