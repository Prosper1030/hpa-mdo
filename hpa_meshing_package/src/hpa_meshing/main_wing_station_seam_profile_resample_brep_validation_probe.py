from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import time
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from .gmsh_runtime import GmshRuntimeError, load_gmsh


ProfileResampleBRepValidationStatusType = Literal[
    "profile_resample_candidate_station_brep_edges_valid",
    "profile_resample_candidate_station_brep_edges_suspect",
    "profile_resample_candidate_station_brep_validation_unavailable",
    "blocked",
]

StationBRepCollector = Callable[..., dict[str, Any]]


class MainWingStationSeamProfileResampleBRepValidationProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_profile_resample_brep_validation_probe.v1"
    ] = "main_wing_station_seam_profile_resample_brep_validation_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_profile_resample_candidate_brep_validation"
    ] = "report_only_profile_resample_candidate_brep_validation"
    production_default_changed: bool = False
    probe_status: ProfileResampleBRepValidationStatusType
    profile_resample_probe_path: str
    candidate_step_path: str | None = None
    target_station_y_m: list[float] = Field(default_factory=list)
    station_tolerance_m: float = 1.0e-4
    target_selection: dict[str, Any] = Field(default_factory=dict)
    hotspot_summary: dict[str, Any] = Field(default_factory=dict)
    station_edge_checks: list[dict[str, Any]] = Field(default_factory=list)
    face_checks: list[dict[str, Any]] = Field(default_factory=list)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_profile_resample_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_profile_resample_strategy_probe"
        / "main_wing_station_seam_profile_resample_strategy_probe.v1.json"
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


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _float_list(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    floats: list[float] = []
    for value in values:
        converted = _as_float(value)
        if converted is not None and converted not in floats:
            floats.append(converted)
    return floats


def _candidate_step_path_from_profile(payload: dict[str, Any] | None) -> Path | None:
    if not isinstance(payload, dict):
        return None
    candidate = payload.get("candidate_report", {})
    candidate = candidate if isinstance(candidate, dict) else {}
    materialization = candidate.get("materialization", {})
    materialization = materialization if isinstance(materialization, dict) else {}
    return _resolve_path(
        materialization.get("step_path")
        or candidate.get("step_path")
        or candidate.get("candidate_step_path")
    )


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


def _station_by_candidate_curve(
    target_selection: dict[str, Any],
) -> dict[int, float]:
    mapping: dict[int, float] = {}
    for group in target_selection.get("station_edge_groups", []):
        if not isinstance(group, dict):
            continue
        station = _as_float(group.get("station_y_m"))
        if station is None:
            continue
        for curve_tag in group.get("candidate_curve_tags", []):
            if isinstance(curve_tag, bool):
                continue
            if isinstance(curve_tag, int):
                mapping[int(curve_tag)] = station
    return mapping


def _station_edge_check(
    curve_report: dict[str, Any],
    *,
    station_by_curve: dict[int, float],
) -> dict[str, Any]:
    curve_tag = curve_report.get("curve_id")
    curve_id = int(curve_tag) if isinstance(curve_tag, int) else None
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
    brepcheck = curve_report.get("brepcheck", {})
    brepcheck = brepcheck if isinstance(brepcheck, dict) else {}
    return {
        "station_y_m": station_by_curve.get(curve_id) if curve_id is not None else None,
        "candidate_step_curve_tag": curve_id,
        "candidate_step_edge_index": curve_report.get("mapped_edge_index"),
        "owner_surface_tags": curve_report.get("owner_surface_tags", []),
        "ancestor_face_ids": curve_report.get("ancestor_face_ids", []),
        "gmsh_length_3d_m": curve_report.get("gmsh_length_3d"),
        "edge_length_3d_m": curve_report.get("edge_length_3d"),
        "length_relative_delta": _relative_delta(
            curve_report.get("gmsh_length_3d"),
            curve_report.get("edge_length_3d"),
        ),
        "match_score": curve_report.get("match_score"),
        "pcurve_presence_complete": pcurve_presence_complete,
        "curve3d_with_pcurve_consistent": curve3d_with_pcurve_consistent,
        "same_parameter_by_face_ok": same_parameter_by_face_ok,
        "vertex_tolerance_by_face_ok": vertex_tolerance_by_face_ok,
        "pcurve_range_matches_edge_range": pcurve_range_matches_edge_range,
        "pcurve_checks_complete": (
            pcurve_presence_complete
            and curve3d_with_pcurve_consistent
            and same_parameter_by_face_ok
            and vertex_tolerance_by_face_ok
            and pcurve_range_matches_edge_range
        ),
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
        "candidate_step_face_tag": face_report.get("surface_id"),
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
    }


def _station_edges_are_valid(edge_checks: list[dict[str, Any]]) -> bool:
    if not edge_checks:
        return False
    for check in edge_checks:
        if check.get("candidate_step_edge_index") is None:
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


def _station_groups_cover_targets(
    *,
    target_selection: dict[str, Any],
    target_station_y_m: list[float],
    station_tolerance_m: float,
) -> bool:
    groups = [
        group
        for group in target_selection.get("station_edge_groups", [])
        if isinstance(group, dict)
    ]
    if not groups or not target_station_y_m:
        return False
    for target in target_station_y_m:
        matching = [
            group
            for group in groups
            if (
                _as_float(group.get("station_y_m")) is not None
                and abs(float(group["station_y_m"]) - target) <= station_tolerance_m
                and group.get("candidate_curve_tags")
            )
        ]
        if not matching:
            return False
    return True


def _probe_status(
    *,
    blockers: list[str],
    collector_payload: dict[str, Any],
    target_station_y_m: list[float],
    station_tolerance_m: float,
    edge_checks: list[dict[str, Any]],
    face_checks: list[dict[str, Any]],
) -> ProfileResampleBRepValidationStatusType:
    if blockers:
        return "blocked"
    if collector_payload.get("status") == "unavailable":
        return "profile_resample_candidate_station_brep_validation_unavailable"
    if collector_payload.get("status") != "captured":
        return "blocked"
    hotspot = collector_payload.get("hotspot_report", {})
    hotspot = hotspot if isinstance(hotspot, dict) else {}
    target_selection = collector_payload.get("target_selection", {})
    target_selection = target_selection if isinstance(target_selection, dict) else {}
    if (
        hotspot.get("status") == "captured"
        and hotspot.get("shape_valid_default") is True
        and hotspot.get("shape_valid_exact") is True
        and _station_groups_cover_targets(
            target_selection=target_selection,
            target_station_y_m=target_station_y_m,
            station_tolerance_m=station_tolerance_m,
        )
        and _station_edges_are_valid(edge_checks)
        and _faces_are_valid(face_checks)
    ):
        return "profile_resample_candidate_station_brep_edges_valid"
    return "profile_resample_candidate_station_brep_edges_suspect"


def _engineering_findings(
    *,
    status: ProfileResampleBRepValidationStatusType,
    target_selection: dict[str, Any],
    edge_checks: list[dict[str, Any]],
    face_checks: list[dict[str, Any]],
) -> list[str]:
    if status == "blocked":
        return ["profile_resample_candidate_brep_validation_blocked"]
    if status == "profile_resample_candidate_station_brep_validation_unavailable":
        return ["profile_resample_candidate_brep_validation_runtime_unavailable"]
    findings = ["profile_resample_candidate_brep_validation_report_captured"]
    if target_selection.get("source_fixture_tags_replayed") is False:
        findings.append("candidate_station_edges_geometrically_selected")
        findings.append("source_fixture_curve_surface_tags_not_replayed")
    if edge_checks and all(
        check.get("pcurve_presence_complete") is True for check in edge_checks
    ):
        findings.append("candidate_station_edge_pcurves_are_present")
    if _station_edges_are_valid(edge_checks):
        findings.append("candidate_station_edges_are_valid_and_pcurve_consistent")
    else:
        findings.append("candidate_station_edge_pcurve_consistency_checks_are_suspect")
    if _faces_are_valid(face_checks):
        findings.append("candidate_owner_faces_wires_are_closed_connected_and_ordered")
    else:
        findings.append("candidate_owner_face_or_wire_checks_are_suspect")
    findings.append("profile_resample_candidate_still_not_mesh_ready")
    return findings


def _blocking_reasons(
    status: ProfileResampleBRepValidationStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "profile_resample_candidate_station_brep_edges_suspect":
        reasons.append("profile_resample_candidate_station_brep_pcurve_checks_suspect")
    if status == "profile_resample_candidate_station_brep_validation_unavailable":
        reasons.append("profile_resample_candidate_brep_validation_runtime_unavailable")
    if status == "blocked" and not reasons:
        reasons.append("profile_resample_candidate_brep_validation_blocked")
    reasons.append("profile_resample_candidate_mesh_handoff_not_run")
    return reasons


def _next_actions(status: ProfileResampleBRepValidationStatusType) -> list[str]:
    if status == "profile_resample_candidate_station_brep_edges_valid":
        return [
            "compare_profile_resample_candidate_mesh_handoff_without_promoting_default",
            "run_station_fixture_topology_trace_on_profile_resample_candidate",
            "keep_profile_resample_candidate_behind_report_only_gate",
        ]
    if status == "profile_resample_candidate_station_brep_edges_suspect":
        return [
            "repair_profile_resample_candidate_pcurve_export_before_mesh_handoff",
            "inspect_station_y_candidate_edges_in_occt",
        ]
    if status == "profile_resample_candidate_station_brep_validation_unavailable":
        return ["restore_ocp_or_gmsh_runtime_before_candidate_brep_claims"]
    return ["restore_profile_resample_candidate_brep_validation_inputs"]


def _default_station_brep_collector() -> StationBRepCollector:
    return collect_profile_resample_candidate_station_brep_report


def _entity_bbox_from_list(values: list[float]) -> dict[str, float]:
    return {
        "x_min": float(values[0]),
        "y_min": float(values[1]),
        "z_min": float(values[2]),
        "x_max": float(values[3]),
        "y_max": float(values[4]),
        "z_max": float(values[5]),
    }


def _model_bbox(gmsh: Any, volumes: list[tuple[int, int]]) -> list[float] | None:
    if not volumes:
        return None
    bbox = [
        float("inf"),
        float("inf"),
        float("inf"),
        float("-inf"),
        float("-inf"),
        float("-inf"),
    ]
    for dim, tag in volumes:
        current = [float(value) for value in gmsh.model.getBoundingBox(dim, tag)]
        bbox[0] = min(bbox[0], current[0])
        bbox[1] = min(bbox[1], current[1])
        bbox[2] = min(bbox[2], current[2])
        bbox[3] = max(bbox[3], current[3])
        bbox[4] = max(bbox[4], current[4])
        bbox[5] = max(bbox[5], current[5])
    return bbox


def _station_curve_groups_from_diagnostics(
    *,
    surface_patch_diagnostics: dict[str, Any],
    station_y_targets: list[float],
    station_tolerance_m: float,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    curve_records = [
        record
        for record in surface_patch_diagnostics.get("curve_records", [])
        if isinstance(record, dict)
    ]
    for station in station_y_targets:
        station_records: list[dict[str, Any]] = []
        for record in curve_records:
            bbox = record.get("bbox", {})
            bbox = bbox if isinstance(bbox, dict) else {}
            y_min = _as_float(bbox.get("y_min"))
            y_max = _as_float(bbox.get("y_max"))
            owner_surfaces = [
                int(tag)
                for tag in record.get("owner_surface_tags", [])
                if isinstance(tag, int) and not isinstance(tag, bool)
            ]
            if (
                y_min is None
                or y_max is None
                or abs(y_min - station) > station_tolerance_m
                or abs(y_max - station) > station_tolerance_m
                or len(owner_surfaces) < 2
            ):
                continue
            station_records.append(record)
        station_records.sort(
            key=lambda item: (
                -float(item.get("length") or 0.0),
                int(item.get("tag") or 0),
            )
        )
        groups.append(
            {
                "station_y_m": float(station),
                "candidate_curve_tags": [
                    int(record["tag"])
                    for record in station_records
                    if isinstance(record.get("tag"), int)
                ],
                "owner_surface_tags": sorted(
                    {
                        int(surface_tag)
                        for record in station_records
                        for surface_tag in record.get("owner_surface_tags", [])
                        if isinstance(surface_tag, int)
                    }
                ),
                "curve_count": len(station_records),
                "curve_records": [
                    {
                        "candidate_curve_tag": int(record["tag"]),
                        "length_3d_m": record.get("length"),
                        "owner_surface_tags": record.get("owner_surface_tags", []),
                        "bbox": record.get("bbox"),
                    }
                    for record in station_records
                    if isinstance(record.get("tag"), int)
                ],
            }
        )
    return groups


def collect_profile_resample_candidate_station_brep_report(
    *,
    step_path: Path,
    station_y_targets: list[float],
    station_tolerance_m: float = 1.0e-4,
    scale_to_output_units: float = 1.0,
    output_units: str = "m",
) -> dict[str, Any]:
    try:
        from .adapters.gmsh_backend import (
            _collect_brep_hotspot_report,
            _collect_surface_patch_diagnostics,
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason": "gmsh_backend_brep_helpers_unavailable",
            "error": str(exc),
        }
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        return {
            "status": "unavailable",
            "reason": "gmsh_runtime_unavailable",
            "error": str(exc),
        }

    gmsh_initialized = False
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"profile_resample_brep_validation_{int(time.time() * 1000)}")
        imported = gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()
        volumes = gmsh.model.getEntities(3)
        surfaces = gmsh.model.getEntities(2)
        bbox = _model_bbox(gmsh, volumes)
        reference_length = (
            max(
                float(bbox[3]) - float(bbox[0]),
                float(bbox[4]) - float(bbox[1]),
                float(bbox[5]) - float(bbox[2]),
            )
            if bbox is not None
            else 1.0
        )
        surface_tags = [int(tag) for _, tag in surfaces]
        surface_patch_diagnostics = _collect_surface_patch_diagnostics(
            gmsh,
            surface_tags=surface_tags,
            reference_length=reference_length,
            near_body_size=max(reference_length / 66.0, 1.0e-3),
        )
        station_edge_groups = _station_curve_groups_from_diagnostics(
            surface_patch_diagnostics=surface_patch_diagnostics,
            station_y_targets=station_y_targets,
            station_tolerance_m=station_tolerance_m,
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason": "candidate_step_station_selection_failed",
            "error": str(exc),
            "step_path": str(step_path),
        }
    finally:
        if gmsh_initialized:
            gmsh.finalize()

    selected_curve_tags = sorted(
        {
            int(curve_tag)
            for group in station_edge_groups
            for curve_tag in group.get("candidate_curve_tags", [])
        }
    )
    selected_surface_tags = sorted(
        {
            int(surface_tag)
            for group in station_edge_groups
            for surface_tag in group.get("owner_surface_tags", [])
        }
    )
    target_selection = {
        "selection_mode": "station_y_geometry_on_candidate_step",
        "source_fixture_tags_replayed": False,
        "station_tolerance_m": float(station_tolerance_m),
        "target_station_y_m": station_y_targets,
        "imported_entity_count": len(imported),
        "volume_count": len(volumes),
        "surface_count": len(surfaces),
        "model_bbox": None if bbox is None else [float(value) for value in bbox],
        "selected_curve_tags": selected_curve_tags,
        "selected_surface_tags": selected_surface_tags,
        "station_edge_groups": station_edge_groups,
    }
    hotspot_report = _collect_brep_hotspot_report(
        step_path=step_path,
        surface_patch_diagnostics=surface_patch_diagnostics,
        requested_surface_tags=selected_surface_tags,
        requested_curve_tags=selected_curve_tags,
        scale_to_output_units=scale_to_output_units,
        output_units=output_units,
    )
    return {
        "status": "captured",
        "target_selection": target_selection,
        "surface_patch_diagnostics_summary": {
            "surface_count": surface_patch_diagnostics.get("surface_count"),
            "curve_count": surface_patch_diagnostics.get("curve_count"),
            "family_hint_counts": surface_patch_diagnostics.get("family_hint_counts", {}),
        },
        "hotspot_report": hotspot_report,
    }


def build_main_wing_station_seam_profile_resample_brep_validation_probe_report(
    *,
    profile_resample_probe_path: Path | None = None,
    candidate_step_path: Path | None = None,
    station_y_targets: list[float] | None = None,
    station_tolerance_m: float = 1.0e-4,
    scale_to_output_units: float = 1.0,
    station_brep_collector: StationBRepCollector | None = None,
) -> MainWingStationSeamProfileResampleBRepValidationProbeReport:
    profile_path = (
        _default_profile_resample_probe_path()
        if profile_resample_probe_path is None
        else profile_resample_probe_path
    )
    blockers: list[str] = []
    profile_payload = _load_json(profile_path, blockers, "profile_resample_probe")
    step_path = candidate_step_path or _candidate_step_path_from_profile(profile_payload)
    targets = (
        list(station_y_targets)
        if station_y_targets is not None
        else _float_list(
            profile_payload.get("target_station_y_m")
            if isinstance(profile_payload, dict)
            else []
        )
    )
    if step_path is None:
        blockers.append("profile_resample_candidate_step_path_missing")
    elif not step_path.exists():
        blockers.append("profile_resample_candidate_step_missing")
    if not targets:
        blockers.append("profile_resample_target_station_y_missing")

    collector_payload: dict[str, Any] = {}
    if not blockers and step_path is not None:
        collector = station_brep_collector or _default_station_brep_collector()
        collector_payload = collector(
            step_path=step_path,
            station_y_targets=targets,
            station_tolerance_m=station_tolerance_m,
            scale_to_output_units=scale_to_output_units,
            output_units="m",
        )

    target_selection = collector_payload.get("target_selection", {})
    target_selection = target_selection if isinstance(target_selection, dict) else {}
    hotspot_report = collector_payload.get("hotspot_report", {})
    hotspot_report = hotspot_report if isinstance(hotspot_report, dict) else {}
    station_by_curve = _station_by_candidate_curve(target_selection)
    edge_checks = [
        _station_edge_check(curve_report, station_by_curve=station_by_curve)
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
        collector_payload=collector_payload,
        target_station_y_m=targets,
        station_tolerance_m=station_tolerance_m,
        edge_checks=edge_checks,
        face_checks=face_checks,
    )
    return MainWingStationSeamProfileResampleBRepValidationProbeReport(
        probe_status=status,
        profile_resample_probe_path=str(profile_path),
        candidate_step_path=str(step_path) if step_path is not None else None,
        target_station_y_m=targets,
        station_tolerance_m=float(station_tolerance_m),
        target_selection=target_selection,
        hotspot_summary={
            "collector_status": collector_payload.get("status"),
            "hotspot_status": hotspot_report.get("status"),
            "shape_valid_default": hotspot_report.get("shape_valid_default"),
            "shape_valid_exact": hotspot_report.get("shape_valid_exact"),
            "scale_to_output_units": hotspot_report.get(
                "scale_to_output_units",
                scale_to_output_units,
            ),
            "selected_curve_tags": hotspot_report.get("selected_curve_tags", []),
            "selected_surface_tags": hotspot_report.get("selected_surface_tags", []),
            "station_edge_check_count": len(edge_checks),
            "face_check_count": len(face_checks),
        },
        station_edge_checks=edge_checks,
        face_checks=face_checks,
        engineering_findings=_engineering_findings(
            status=status,
            target_selection=target_selection,
            edge_checks=edge_checks,
            face_checks=face_checks,
        ),
        blocking_reasons=_blocking_reasons(status, blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This probe validates the profile-resample candidate STEP only; it does not change production defaults.",
            "Station targets are selected geometrically from candidate topology, not replayed from the old station fixture tags.",
            "It does not run Gmsh volume mesh generation, SU2_CFD, CL acceptance, or convergence checks.",
            "Profile resampling may perturb airfoil fidelity and still needs a geometry-deviation gate before promotion.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingStationSeamProfileResampleBRepValidationProbeReport,
) -> str:
    lines = [
        "# Main Wing Station Seam Profile Resample BRep Validation Probe v1",
        "",
        "This report validates station-y BRep/PCurve checks on the profile-resample candidate STEP without replaying old curve or surface tags.",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- profile_resample_probe_path: `{report.profile_resample_probe_path}`",
        f"- candidate_step_path: `{report.candidate_step_path}`",
        f"- target_station_y_m: `{_fmt(report.target_station_y_m)}`",
        f"- station_tolerance_m: `{report.station_tolerance_m}`",
        f"- production_default_changed: `{report.production_default_changed}`",
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


def write_main_wing_station_seam_profile_resample_brep_validation_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamProfileResampleBRepValidationProbeReport | None = None,
    profile_resample_probe_path: Path | None = None,
    candidate_step_path: Path | None = None,
    station_y_targets: list[float] | None = None,
    station_tolerance_m: float = 1.0e-4,
    scale_to_output_units: float = 1.0,
    station_brep_collector: StationBRepCollector | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_profile_resample_brep_validation_probe_report(
            profile_resample_probe_path=profile_resample_probe_path,
            candidate_step_path=candidate_step_path,
            station_y_targets=station_y_targets,
            station_tolerance_m=station_tolerance_m,
            scale_to_output_units=scale_to_output_units,
            station_brep_collector=station_brep_collector,
        )
    json_path = (
        out_dir / "main_wing_station_seam_profile_resample_brep_validation_probe.v1.json"
    )
    markdown_path = (
        out_dir / "main_wing_station_seam_profile_resample_brep_validation_probe.v1.md"
    )
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
