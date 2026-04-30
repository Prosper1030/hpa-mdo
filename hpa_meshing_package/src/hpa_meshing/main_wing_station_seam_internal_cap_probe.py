from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from .gmsh_runtime import GmshRuntimeError, load_gmsh


InternalCapProbeStatusType = Literal[
    "split_candidate_internal_cap_risk_confirmed",
    "split_candidate_no_internal_caps_detected_needs_mesh_handoff_probe",
    "blocked",
]


class MainWingStationSeamInternalCapProbeReport(BaseModel):
    schema_version: Literal["main_wing_station_seam_internal_cap_probe.v1"] = (
        "main_wing_station_seam_internal_cap_probe.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_split_candidate_internal_cap_probe"] = (
        "report_only_split_candidate_internal_cap_probe"
    )
    production_default_changed: bool = False
    probe_status: InternalCapProbeStatusType
    export_strategy_probe_path: str
    export_source_audit_path: str | None = None
    station_plane_tolerance: float = 1.0e-4
    target_station_y_m: list[float] = Field(default_factory=list)
    candidate_inspections: list[dict[str, Any]] = Field(default_factory=list)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_export_strategy_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_export_strategy_probe"
        / "main_wing_station_seam_export_strategy_probe.v1.json"
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


def _target_station_y_values(
    export_source_audit: dict[str, Any] | None,
) -> list[float]:
    if not isinstance(export_source_audit, dict):
        return []
    values: list[float] = []
    for mapping in export_source_audit.get("target_station_mappings", []):
        if not isinstance(mapping, dict):
            continue
        value = _as_float(mapping.get("defect_station_y_m"))
        if value is not None and value not in values:
            values.append(value)
    return sorted(values)


def _candidate_materialization(candidate: dict[str, Any]) -> dict[str, Any]:
    materialization = candidate.get("materialization", {})
    return materialization if isinstance(materialization, dict) else {}


def _round_signature(value: Any, decimals: int = 6) -> float | None:
    numeric = _as_float(value)
    return None if numeric is None else round(numeric, decimals)


def _surface_bbox_signature(surface: dict[str, Any]) -> tuple[float | None, ...]:
    bbox = surface.get("bbox", [])
    if not isinstance(bbox, list):
        return tuple()
    return tuple(_round_signature(value) for value in bbox[:6])


def _model_bbox_from_volumes(gmsh: Any, volumes: list[tuple[int, int]]) -> list[float] | None:
    if not volumes:
        return None
    model_bbox = [
        float("inf"),
        float("inf"),
        float("inf"),
        float("-inf"),
        float("-inf"),
        float("-inf"),
    ]
    for dim, tag in volumes:
        current = [float(value) for value in gmsh.model.getBoundingBox(dim, tag)]
        model_bbox[0] = min(model_bbox[0], current[0])
        model_bbox[1] = min(model_bbox[1], current[1])
        model_bbox[2] = min(model_bbox[2], current[2])
        model_bbox[3] = max(model_bbox[3], current[3])
        model_bbox[4] = max(model_bbox[4], current[4])
        model_bbox[5] = max(model_bbox[5], current[5])
    return model_bbox


def _probe_step_surface_inventory(step_path: Path) -> dict[str, Any]:
    if not step_path.exists():
        return {"status": "step_missing", "step_path": str(step_path)}
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        return {"status": "gmsh_unavailable", "error": str(exc), "step_path": str(step_path)}

    gmsh_initialized = False
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"main_wing_internal_cap_probe_{int(time.time() * 1000)}")
        imported = gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()
        volumes = gmsh.model.getEntities(3)
        surfaces = gmsh.model.getEntities(2)
        curves = gmsh.model.getEntities(1)
        points = gmsh.model.getEntities(0)
        surface_inventory = []
        for dim, tag in surfaces:
            surface_inventory.append(
                {
                    "tag": tag,
                    "bbox": [float(value) for value in gmsh.model.getBoundingBox(dim, tag)],
                }
            )
        return {
            "status": "topology_counted",
            "step_path": str(step_path),
            "imported_entity_count": len(imported),
            "body_count": len(volumes),
            "volume_count": len(volumes),
            "surface_count": len(surfaces),
            "curve_count": len(curves),
            "point_count": len(points),
            "bbox": _model_bbox_from_volumes(gmsh, volumes),
            "surfaces": surface_inventory,
        }
    except Exception as exc:
        return {"status": "surface_inventory_failed", "error": str(exc), "step_path": str(step_path)}
    finally:
        if gmsh_initialized:
            gmsh.finalize()


def _is_station_plane_face(
    *,
    surface: dict[str, Any],
    station_y_m: float,
    tolerance: float,
) -> bool:
    bbox = surface.get("bbox", [])
    if not isinstance(bbox, list) or len(bbox) < 5:
        return False
    y_min = _as_float(bbox[1])
    y_max = _as_float(bbox[4])
    return (
        y_min is not None
        and y_max is not None
        and abs(y_min - station_y_m) <= tolerance
        and abs(y_max - station_y_m) <= tolerance
    )


def _station_face_groups(
    *,
    surfaces: list[dict[str, Any]],
    target_station_y_m: list[float],
    station_plane_tolerance: float,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for station in target_station_y_m:
        hits = [
            surface
            for surface in surfaces
            if _is_station_plane_face(
                surface=surface,
                station_y_m=station,
                tolerance=station_plane_tolerance,
            )
        ]
        signatures = [_surface_bbox_signature(surface) for surface in hits]
        unique_signatures = list(dict.fromkeys(signatures))
        groups.append(
            {
                "station_y_m": station,
                "plane_face_count": len(hits),
                "face_tags": [surface.get("tag") for surface in hits],
                "face_bboxes": [surface.get("bbox") for surface in hits],
                "duplicate_station_cap_faces": len(hits) > 1,
                "station_cap_faces_present": bool(hits),
                "unique_bbox_signature_count": len(unique_signatures),
                "bbox_signatures": [list(signature) for signature in unique_signatures],
            }
        )
    return groups


def _candidate_mesh_handoff_ready(
    *,
    materialization: dict[str, Any],
    inventory: dict[str, Any],
    candidate: dict[str, Any],
    station_face_groups: list[dict[str, Any]],
) -> bool:
    return (
        materialization.get("status") == "materialized"
        and inventory.get("status") == "topology_counted"
        and inventory.get("body_count") == 1
        and inventory.get("volume_count") == 1
        and candidate.get("span_y_bounds_preserved") is True
        and not any(group.get("station_cap_faces_present") for group in station_face_groups)
    )


def _inspect_candidates(
    *,
    export_strategy_probe: dict[str, Any] | None,
    target_station_y_m: list[float],
    station_plane_tolerance: float,
    surface_inventory_by_candidate: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not isinstance(export_strategy_probe, dict):
        return []
    inspections: list[dict[str, Any]] = []
    overrides = surface_inventory_by_candidate or {}
    for candidate in export_strategy_probe.get("candidate_reports", []):
        if not isinstance(candidate, dict):
            continue
        name = str(candidate.get("candidate") or "unnamed_candidate")
        materialization = _candidate_materialization(candidate)
        step_path = _resolve_path(materialization.get("step_path"))
        inventory = overrides.get(name)
        if inventory is None:
            inventory = (
                {"status": "step_path_missing"}
                if step_path is None
                else _probe_step_surface_inventory(step_path)
            )
        surfaces = inventory.get("surfaces", []) if isinstance(inventory, dict) else []
        if not isinstance(surfaces, list):
            surfaces = []
        station_face_groups = _station_face_groups(
            surfaces=[
                surface for surface in surfaces if isinstance(surface, dict)
            ],
            target_station_y_m=target_station_y_m,
            station_plane_tolerance=station_plane_tolerance,
        )
        topology = materialization.get("topology", {})
        if not isinstance(topology, dict):
            topology = {}
        inspections.append(
            {
                "candidate": name,
                "apply_union": candidate.get("apply_union"),
                "materialization_status": materialization.get("status"),
                "step_path": str(step_path) if step_path is not None else None,
                "inventory_status": inventory.get("status")
                if isinstance(inventory, dict)
                else "invalid_inventory",
                "body_count": inventory.get("body_count", topology.get("body_count"))
                if isinstance(inventory, dict)
                else topology.get("body_count"),
                "volume_count": inventory.get("volume_count", topology.get("volume_count"))
                if isinstance(inventory, dict)
                else topology.get("volume_count"),
                "surface_count": inventory.get("surface_count", topology.get("surface_count"))
                if isinstance(inventory, dict)
                else topology.get("surface_count"),
                "bbox": inventory.get("bbox", topology.get("bbox"))
                if isinstance(inventory, dict)
                else topology.get("bbox"),
                "span_y_bounds_preserved": candidate.get("span_y_bounds_preserved"),
                "target_boundary_duplication_count": candidate.get(
                    "target_boundary_duplication_count"
                ),
                "target_station_face_groups": station_face_groups,
                "candidate_mesh_handoff_ready": _candidate_mesh_handoff_ready(
                    materialization=materialization,
                    inventory=inventory if isinstance(inventory, dict) else {},
                    candidate=candidate,
                    station_face_groups=station_face_groups,
                ),
            }
        )
    return inspections


def _probe_status(
    *,
    blockers: list[str],
    inspections: list[dict[str, Any]],
) -> InternalCapProbeStatusType:
    if blockers or not inspections:
        return "blocked"
    if any(inspection.get("candidate_mesh_handoff_ready") for inspection in inspections):
        return "split_candidate_no_internal_caps_detected_needs_mesh_handoff_probe"
    return "split_candidate_internal_cap_risk_confirmed"


def _any_station_caps(inspections: list[dict[str, Any]]) -> bool:
    return any(
        group.get("station_cap_faces_present")
        for inspection in inspections
        for group in inspection.get("target_station_face_groups", [])
        if isinstance(group, dict)
    )


def _any_duplicate_caps(inspections: list[dict[str, Any]]) -> bool:
    return any(
        group.get("duplicate_station_cap_faces")
        for inspection in inspections
        for group in inspection.get("target_station_face_groups", [])
        if isinstance(group, dict)
    )


def _engineering_findings(inspections: list[dict[str, Any]]) -> list[str]:
    findings = ["station_seam_internal_cap_probe_captured"]
    for inspection in inspections:
        name = inspection.get("candidate")
        if any(
            group.get("duplicate_station_cap_faces")
            for group in inspection.get("target_station_face_groups", [])
            if isinstance(group, dict)
        ):
            findings.append(f"{name}_duplicate_station_cap_faces_confirmed")
        elif any(
            group.get("station_cap_faces_present")
            for group in inspection.get("target_station_face_groups", [])
            if isinstance(group, dict)
        ):
            findings.append(f"{name}_station_cap_faces_confirmed")
        if inspection.get("span_y_bounds_preserved") is False:
            findings.append(f"{name}_span_truncation_reconfirmed")
        if inspection.get("body_count") != 1 or inspection.get("volume_count") != 1:
            findings.append(f"{name}_multi_volume_topology_reconfirmed")
        if inspection.get("candidate_mesh_handoff_ready") is True:
            findings.append(f"{name}_no_internal_caps_detected")
    return list(dict.fromkeys(findings))


def _blocking_reasons(
    *,
    blockers: list[str],
    inspections: list[dict[str, Any]],
) -> list[str]:
    reasons = list(blockers)
    if _any_station_caps(inspections):
        reasons.append("internal_station_cap_faces_present")
    if _any_duplicate_caps(inspections):
        reasons.append("duplicate_station_cap_faces_present")
    if any(inspection.get("span_y_bounds_preserved") is False for inspection in inspections):
        reasons.append("split_candidate_span_truncation_confirmed")
    if any(
        inspection.get("body_count") != 1 or inspection.get("volume_count") != 1
        for inspection in inspections
    ):
        reasons.append("split_candidate_multi_volume_topology_confirmed")
    if not any(inspection.get("candidate_mesh_handoff_ready") for inspection in inspections):
        reasons.append("split_candidate_not_mesh_handoff_ready")
    if any(
        inspection.get("inventory_status") not in {"topology_counted"}
        for inspection in inspections
    ):
        reasons.append("candidate_surface_inventory_incomplete")
    return list(dict.fromkeys(reasons))


def _next_actions(status: InternalCapProbeStatusType) -> list[str]:
    if status == "split_candidate_no_internal_caps_detected_needs_mesh_handoff_probe":
        return [
            "run_split_candidate_mesh_handoff_probe_without_promoting_default",
            "compare_split_candidate_surface_topology_against_original_route",
        ]
    if status == "split_candidate_internal_cap_risk_confirmed":
        return [
            "try_pcurve_rebuild_strategy_without_split_caps",
            "keep_split_bay_strategy_as_negative_evidence_not_product_route",
        ]
    return ["restore_station_seam_internal_cap_probe_inputs"]


def build_main_wing_station_seam_internal_cap_probe_report(
    *,
    export_strategy_probe_path: Path | None = None,
    station_plane_tolerance: float = 1.0e-4,
    surface_inventory_by_candidate: dict[str, dict[str, Any]] | None = None,
) -> MainWingStationSeamInternalCapProbeReport:
    blockers: list[str] = []
    strategy_path = export_strategy_probe_path or _default_export_strategy_probe_path()
    strategy_payload = _load_json(
        strategy_path,
        blockers,
        "main_wing_station_seam_export_strategy_probe",
    )
    export_source_audit_path = (
        _resolve_path(strategy_payload.get("export_source_audit_path"))
        if isinstance(strategy_payload, dict)
        else None
    )
    export_source_audit = (
        _load_json(export_source_audit_path, blockers, "main_wing_station_seam_export_source_audit")
        if export_source_audit_path is not None
        else None
    )
    target_stations = _target_station_y_values(export_source_audit)
    if not target_stations:
        blockers.append("target_station_y_values_missing")
    inspections = _inspect_candidates(
        export_strategy_probe=strategy_payload,
        target_station_y_m=target_stations,
        station_plane_tolerance=station_plane_tolerance,
        surface_inventory_by_candidate=surface_inventory_by_candidate,
    )
    status = _probe_status(blockers=blockers, inspections=inspections)
    return MainWingStationSeamInternalCapProbeReport(
        probe_status=status,
        export_strategy_probe_path=str(strategy_path),
        export_source_audit_path=(
            str(export_source_audit_path) if export_source_audit_path is not None else None
        ),
        station_plane_tolerance=float(station_plane_tolerance),
        target_station_y_m=target_stations,
        candidate_inspections=inspections,
        engineering_findings=_engineering_findings(inspections),
        blocking_reasons=_blocking_reasons(blockers=blockers, inspections=inspections),
        next_actions=_next_actions(status),
        limitations=[
            "This report classifies station-plane cap faces from OCC/Gmsh surface bounding boxes; it does not mesh or run SU2.",
            "A clean result here would only authorize a bounded mesh-handoff probe, not production-route promotion.",
        ],
    )


def _render_markdown(report: MainWingStationSeamInternalCapProbeReport) -> str:
    lines = [
        "# Main Wing Station Seam Internal Cap Probe v1",
        "",
        f"- status: `{report.probe_status}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        f"- export_strategy_probe_path: `{report.export_strategy_probe_path}`",
        f"- station_plane_tolerance: `{report.station_plane_tolerance}`",
        f"- target_station_y_m: `{report.target_station_y_m}`",
        "",
        "## Candidate Inspections",
        "",
        "| candidate | mesh ready | bodies | volumes | span preserved | target face counts |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for inspection in report.candidate_inspections:
        groups = inspection.get("target_station_face_groups", [])
        target_face_counts = ", ".join(
            f"{group.get('station_y_m')}:{group.get('plane_face_count')}"
            for group in groups
            if isinstance(group, dict)
        )
        lines.append(
            "| "
            f"`{inspection.get('candidate')}` | "
            f"`{inspection.get('candidate_mesh_handoff_ready')}` | "
            f"`{inspection.get('body_count')}` | "
            f"`{inspection.get('volume_count')}` | "
            f"`{inspection.get('span_y_bounds_preserved')}` | "
            f"`{target_face_counts}` |"
        )
    lines.extend(
        [
            "",
            "## Engineering Findings",
            "",
            *[f"- `{finding}`" for finding in report.engineering_findings],
            "",
            "## Blocking Reasons",
            "",
            *[f"- `{reason}`" for reason in report.blocking_reasons],
            "",
            "## Next Actions",
            "",
            *[f"- `{action}`" for action in report.next_actions],
            "",
            "## Limitations",
            "",
            *[f"- {limitation}" for limitation in report.limitations],
            "",
        ]
    )
    return "\n".join(lines)


def write_main_wing_station_seam_internal_cap_probe_report(
    out_dir: Path,
    *,
    export_strategy_probe_path: Path | None = None,
    station_plane_tolerance: float = 1.0e-4,
    report: MainWingStationSeamInternalCapProbeReport | None = None,
    surface_inventory_by_candidate: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    built_report = report or build_main_wing_station_seam_internal_cap_probe_report(
        export_strategy_probe_path=export_strategy_probe_path,
        station_plane_tolerance=station_plane_tolerance,
        surface_inventory_by_candidate=surface_inventory_by_candidate,
    )
    json_path = out_dir / "main_wing_station_seam_internal_cap_probe.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_internal_cap_probe.v1.md"
    json_path.write_text(
        json.dumps(built_report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(built_report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
