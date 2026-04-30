from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from .gmsh_runtime import GmshRuntimeError, load_gmsh


ProfileResampleProbeStatusType = Literal[
    "profile_resample_candidate_materialized_needs_brep_validation",
    "profile_resample_candidate_materialized_but_topology_risk",
    "profile_resample_candidate_materialization_failed",
    "profile_resample_candidate_source_only_ready_for_materialization",
    "blocked",
]


class MainWingStationSeamProfileResampleStrategyProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_profile_resample_strategy_probe.v1"
    ] = "main_wing_station_seam_profile_resample_strategy_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_profile_resample_export_strategy_probe"] = (
        "report_only_profile_resample_export_strategy_probe"
    )
    production_default_changed: bool = False
    probe_status: ProfileResampleProbeStatusType
    export_source_audit_path: str
    rebuild_csm_path: str | None = None
    materialization_requested: bool = False
    source_profile_point_counts: list[int] = Field(default_factory=list)
    target_profile_point_count: int | None = None
    target_station_y_m: list[float] = Field(default_factory=list)
    candidate_report: dict[str, Any] = Field(default_factory=dict)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_export_source_audit_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_export_source_audit"
        / "main_wing_station_seam_export_source_audit.v1.json"
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


def _format_csm_number(value: float) -> str:
    return f"{float(value):.12g}"


def _parse_csm_sections(
    path: Path,
    blockers: list[str],
) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        blockers.append("rebuild_csm_missing")
        return []
    sections: list[dict[str, Any]] = []
    current_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("skbeg "):
            current_lines = [line.rstrip()]
            continue
        if current_lines:
            current_lines.append(line.rstrip())
            if stripped == "skend":
                points: list[tuple[float, float, float]] = []
                for section_line in current_lines:
                    tokens = section_line.strip().split()
                    if not tokens or tokens[0] not in {"skbeg", "linseg", "spline"}:
                        continue
                    if len(tokens) < 4:
                        continue
                    try:
                        points.append(
                            (
                                float(tokens[1]),
                                float(tokens[2]),
                                float(tokens[3]),
                            )
                        )
                    except ValueError:
                        continue
                sections.append(
                    {
                        "csm_section_index": len(sections),
                        "station_y_m": points[0][1] if points else None,
                        "point_count": len(points),
                        "points": points,
                    }
                )
                current_lines = []
    if not sections:
        blockers.append("rebuild_csm_sections_missing")
    return sections


def _closed_polyline_length(points: list[tuple[float, float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(math.dist(lhs, rhs) for lhs, rhs in zip(points, points[1:]))


def _resample_closed_profile(
    points: list[tuple[float, float, float]],
    target_count: int,
) -> list[tuple[float, float, float]]:
    if target_count < 4:
        raise ValueError("target closed profile point count must be at least 4")
    if len(points) < 3:
        raise ValueError("source profile needs at least 3 points")
    open_points = points[:-1] if points[0] == points[-1] else list(points)
    closed = [*open_points, open_points[0]]
    total = _closed_polyline_length(closed)
    if total <= 0.0:
        raise ValueError("source profile has zero perimeter")
    cumulative = [0.0]
    for lhs, rhs in zip(closed, closed[1:]):
        cumulative.append(cumulative[-1] + math.dist(lhs, rhs))
    resampled: list[tuple[float, float, float]] = []
    for index in range(target_count - 1):
        target_distance = total * index / (target_count - 1)
        segment_index = 0
        while (
            segment_index + 1 < len(cumulative)
            and cumulative[segment_index + 1] < target_distance
        ):
            segment_index += 1
        span = cumulative[segment_index + 1] - cumulative[segment_index]
        fraction = (
            0.0
            if span <= 0.0
            else (target_distance - cumulative[segment_index]) / span
        )
        lhs = closed[segment_index]
        rhs = closed[segment_index + 1]
        resampled.append(
            tuple(lhs[axis] * (1.0 - fraction) + rhs[axis] * fraction for axis in range(3))
        )
    resampled.append(resampled[0])
    return resampled


def _station_bounds(sections: list[dict[str, Any]]) -> dict[str, float | None]:
    y_values = [
        float(section["station_y_m"])
        for section in sections
        if isinstance(section.get("station_y_m"), (int, float))
    ]
    return {
        "y_min": min(y_values) if y_values else None,
        "y_max": max(y_values) if y_values else None,
    }


def _span_y_bounds_preserved(
    *,
    topology: dict[str, Any],
    expected_bounds: dict[str, float | None],
    tolerance: float = 1.0e-3,
) -> bool | None:
    bbox = topology.get("bbox")
    expected_min = expected_bounds.get("y_min")
    expected_max = expected_bounds.get("y_max")
    if (
        not isinstance(bbox, list)
        or len(bbox) < 5
        or not isinstance(expected_min, (int, float))
        or not isinstance(expected_max, (int, float))
    ):
        return None
    return (
        abs(float(bbox[1]) - float(expected_min)) <= tolerance
        and abs(float(bbox[4]) - float(expected_max)) <= tolerance
    )


def _build_candidate_csm(
    *,
    sections: list[dict[str, Any]],
    target_profile_point_count: int,
    source_csm_path: Path,
    export_filename: str,
) -> tuple[str, list[int]]:
    candidate_counts: list[int] = []
    lines = [
        "# Auto-generated by hpa_meshing.main_wing_station_seam_profile_resample_strategy_probe",
        "# Report-only candidate; not a production provider default",
        "# Uniformizes section profile point counts while preserving one OpenCSM rule",
        f"# Source rebuild.csm: {source_csm_path}",
        f"SET export_path $\"{export_filename}\"",
        "",
        "mark",
    ]
    for section in sections:
        points = section.get("points", [])
        if not isinstance(points, list):
            raise ValueError("section points missing")
        resampled = _resample_closed_profile(points, target_profile_point_count)
        candidate_counts.append(len(resampled))
        lines.append(
            "skbeg " + " ".join(_format_csm_number(value) for value in resampled[0])
        )
        for point_index, point in enumerate(resampled[1:], start=1):
            opcode = (
                "linseg"
                if point_index == 1 or point_index == len(resampled) - 1
                else "spline"
            )
            lines.append(
                f"   {opcode} "
                + " ".join(_format_csm_number(value) for value in point)
            )
        lines.append("skend")
    lines.extend(
        [
            "rule",
            "ATTRIBUTE _name $main_wing_profile_resample_uniform",
            "ATTRIBUTE capsGroup $main_wing",
            "DUMP !export_path 0 1",
            "END",
            "",
        ]
    )
    return "\n".join(lines), candidate_counts


def _write_command_log(
    *,
    log_path: Path,
    args: list[str],
    returncode: int | str,
    stdout: str,
    stderr: str,
) -> None:
    log_path.write_text(
        "\n".join(
            [
                "command: " + " ".join(args),
                f"returncode: {returncode}",
                "--- stdout ---",
                stdout,
                "--- stderr ---",
                stderr,
                "",
            ]
        ),
        encoding="utf-8",
    )


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
        bbox = [float(value) for value in gmsh.model.getBoundingBox(dim, tag)]
        model_bbox[0] = min(model_bbox[0], bbox[0])
        model_bbox[1] = min(model_bbox[1], bbox[1])
        model_bbox[2] = min(model_bbox[2], bbox[2])
        model_bbox[3] = max(model_bbox[3], bbox[3])
        model_bbox[4] = max(model_bbox[4], bbox[4])
        model_bbox[5] = max(model_bbox[5], bbox[5])
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
        gmsh.model.add(f"main_wing_profile_resample_{int(time.time() * 1000)}")
        imported = gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()
        volumes = gmsh.model.getEntities(3)
        surfaces = gmsh.model.getEntities(2)
        curves = gmsh.model.getEntities(1)
        points = gmsh.model.getEntities(0)
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
            "surfaces": [
                {
                    "tag": tag,
                    "bbox": [
                        float(value)
                        for value in gmsh.model.getBoundingBox(dim, tag)
                    ],
                }
                for dim, tag in surfaces
            ],
        }
    except Exception as exc:
        return {"status": "surface_inventory_failed", "error": str(exc), "step_path": str(step_path)}
    finally:
        if gmsh_initialized:
            gmsh.finalize()


def _materialize_candidate(
    *,
    out_dir: Path,
    csm_text: str,
    timeout_seconds: float,
    surface_inventory_override: dict[str, Any] | None,
) -> dict[str, Any]:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    csm_path = out_dir / "candidate.csm"
    step_path = out_dir / "candidate_raw_dump.stp"
    command_log_path = out_dir / "ocsm.log"
    csm_path.write_text(csm_text, encoding="utf-8")

    if surface_inventory_override is not None:
        return {
            "status": "materialized",
            "csm_path": str(csm_path),
            "step_path": str(step_path),
            "command_log_path": str(command_log_path),
            "topology": surface_inventory_override,
            "materialization_skipped_for_test_override": True,
        }

    batch_binary = shutil.which("serveCSM") or shutil.which("ocsm")
    if batch_binary is None:
        _write_command_log(
            log_path=command_log_path,
            args=[],
            returncode="not_run",
            stdout="",
            stderr="Neither serveCSM nor ocsm was resolvable on PATH.",
        )
        return {
            "status": "not_run_batch_binary_missing",
            "csm_path": str(csm_path),
            "step_path": str(step_path),
            "command_log_path": str(command_log_path),
        }

    args = [batch_binary, "-batch", csm_path.name]
    try:
        completed = subprocess.run(
            args,
            cwd=str(out_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        _write_command_log(
            log_path=command_log_path,
            args=args,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except subprocess.TimeoutExpired as exc:
        _write_command_log(
            log_path=command_log_path,
            args=args,
            returncode="timeout",
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else "",
        )
        return {
            "status": "timeout",
            "csm_path": str(csm_path),
            "step_path": str(step_path),
            "command_log_path": str(command_log_path),
            "timeout_seconds": float(timeout_seconds),
        }

    topology = _probe_step_surface_inventory(step_path) if step_path.exists() else {}
    return {
        "status": (
            "materialized"
            if completed.returncode == 0 and step_path.exists()
            else "failed"
        ),
        "returncode": completed.returncode,
        "csm_path": str(csm_path),
        "step_path": str(step_path),
        "step_exists": step_path.exists(),
        "step_size_bytes": step_path.stat().st_size if step_path.exists() else None,
        "command_log_path": str(command_log_path),
        "stdout_tail": (completed.stdout or "")[-1000:],
        "stderr_tail": (completed.stderr or "")[-1000:],
        "topology": topology,
    }


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
    topology: dict[str, Any],
    target_station_y_m: list[float],
    station_plane_tolerance: float,
) -> list[dict[str, Any]]:
    surfaces = topology.get("surfaces", [])
    if not isinstance(surfaces, list):
        surfaces = []
    groups: list[dict[str, Any]] = []
    for station in target_station_y_m:
        hits = [
            surface
            for surface in surfaces
            if isinstance(surface, dict)
            and _is_station_plane_face(
                surface=surface,
                station_y_m=station,
                tolerance=station_plane_tolerance,
            )
        ]
        groups.append(
            {
                "station_y_m": station,
                "plane_face_count": len(hits),
                "face_tags": [surface.get("tag") for surface in hits],
                "face_bboxes": [surface.get("bbox") for surface in hits],
                "station_cap_faces_present": bool(hits),
                "duplicate_station_cap_faces": len(hits) > 1,
            }
        )
    return groups


def _build_candidate_report(
    *,
    sections: list[dict[str, Any]],
    source_csm_path: Path,
    materialization_requested: bool,
    materialization_root: Path | None,
    timeout_seconds: float,
    target_profile_point_count: int,
    target_station_y_m: list[float],
    station_plane_tolerance: float,
    surface_inventory_override: dict[str, Any] | None,
) -> dict[str, Any]:
    csm_text, candidate_counts = _build_candidate_csm(
        sections=sections,
        target_profile_point_count=target_profile_point_count,
        source_csm_path=source_csm_path,
        export_filename="candidate_raw_dump.stp",
    )
    report: dict[str, Any] = {
        "candidate": "uniform_profile_resample_single_rule",
        "intended_use": "diagnostic_single_rule_profile_count_uniformization_probe",
        "risk": "resampling can perturb airfoil fidelity and still needs BRep/PCurve validation",
        "rule_count": 1,
        "candidate_profile_point_counts": candidate_counts,
        "candidate_csm_text_available": True,
        "materialization": {"status": "not_requested"},
    }
    if materialization_requested and materialization_root is not None:
        report["materialization"] = _materialize_candidate(
            out_dir=materialization_root / "artifacts" / "uniform_profile_resample_single_rule",
            csm_text=csm_text,
            timeout_seconds=timeout_seconds,
            surface_inventory_override=surface_inventory_override,
        )
        topology = report["materialization"].get("topology", {})
        topology = topology if isinstance(topology, dict) else {}
        report.update(
            {
                "materialization_status": report["materialization"].get("status"),
                "body_count": topology.get("body_count"),
                "volume_count": topology.get("volume_count"),
                "surface_count": topology.get("surface_count"),
                "bbox": topology.get("bbox"),
                "span_y_bounds_preserved": _span_y_bounds_preserved(
                    topology=topology,
                    expected_bounds=_station_bounds(sections),
                ),
                "target_station_face_groups": _station_face_groups(
                    topology=topology,
                    target_station_y_m=target_station_y_m,
                    station_plane_tolerance=station_plane_tolerance,
                ),
            }
        )
    return report


def _candidate_clean_enough_for_brep_validation(candidate_report: dict[str, Any]) -> bool:
    return (
        candidate_report.get("materialization_status") == "materialized"
        and candidate_report.get("body_count") == 1
        and candidate_report.get("volume_count") == 1
        and candidate_report.get("span_y_bounds_preserved") is True
        and not any(
            group.get("station_cap_faces_present")
            for group in candidate_report.get("target_station_face_groups", [])
            if isinstance(group, dict)
        )
    )


def _probe_status(
    *,
    blockers: list[str],
    materialization_requested: bool,
    candidate_report: dict[str, Any],
) -> ProfileResampleProbeStatusType:
    if blockers or not candidate_report:
        return "blocked"
    if not materialization_requested:
        return "profile_resample_candidate_source_only_ready_for_materialization"
    if candidate_report.get("materialization_status") != "materialized":
        return "profile_resample_candidate_materialization_failed"
    if _candidate_clean_enough_for_brep_validation(candidate_report):
        return "profile_resample_candidate_materialized_needs_brep_validation"
    return "profile_resample_candidate_materialized_but_topology_risk"


def _engineering_findings(
    *,
    source_counts: list[int],
    candidate_report: dict[str, Any],
) -> list[str]:
    findings = ["station_seam_profile_resample_strategy_probe_captured"]
    if len(set(source_counts)) > 1:
        findings.append("source_profile_point_count_mismatch_observed")
    if len(set(candidate_report.get("candidate_profile_point_counts", []))) == 1:
        findings.append("candidate_profile_point_counts_uniformized")
    if _candidate_clean_enough_for_brep_validation(candidate_report):
        findings.append("uniform_profile_candidate_no_target_cap_faces_detected")
        findings.append("uniform_profile_candidate_single_volume_full_span_observed")
    if candidate_report.get("span_y_bounds_preserved") is False:
        findings.append("uniform_profile_candidate_span_bounds_not_preserved")
    if any(
        group.get("station_cap_faces_present")
        for group in candidate_report.get("target_station_face_groups", [])
        if isinstance(group, dict)
    ):
        findings.append("uniform_profile_candidate_target_cap_faces_present")
    return list(dict.fromkeys(findings))


def _blocking_reasons(
    *,
    status: ProfileResampleProbeStatusType,
    blockers: list[str],
    candidate_report: dict[str, Any],
) -> list[str]:
    reasons = list(blockers)
    if status == "profile_resample_candidate_source_only_ready_for_materialization":
        reasons.append("candidate_materialization_not_run")
    elif status == "profile_resample_candidate_materialization_failed":
        reasons.append("profile_resample_candidate_materialization_failed")
    elif status == "profile_resample_candidate_materialized_needs_brep_validation":
        reasons.append("candidate_needs_station_brep_pcurve_validation_before_mesh_handoff")
    elif status == "profile_resample_candidate_materialized_but_topology_risk":
        reasons.append("profile_resample_candidate_topology_risk")
    if candidate_report.get("span_y_bounds_preserved") is False:
        reasons.append("profile_resample_candidate_does_not_preserve_full_span_bounds")
    if any(
        group.get("station_cap_faces_present")
        for group in candidate_report.get("target_station_face_groups", [])
        if isinstance(group, dict)
    ):
        reasons.append("profile_resample_candidate_target_station_caps_present")
    if candidate_report.get("body_count") not in {None, 1} or candidate_report.get(
        "volume_count"
    ) not in {None, 1}:
        reasons.append("profile_resample_candidate_not_single_volume")
    return list(dict.fromkeys(reasons))


def _next_actions(status: ProfileResampleProbeStatusType) -> list[str]:
    if status == "profile_resample_candidate_materialized_needs_brep_validation":
        return [
            "run_station_seam_brep_hotspot_probe_on_profile_resample_candidate",
            "compare_profile_resample_candidate_mesh_handoff_without_promoting_default",
        ]
    if status == "profile_resample_candidate_materialized_but_topology_risk":
        return ["inspect_profile_resample_candidate_brep_failures"]
    if status == "profile_resample_candidate_source_only_ready_for_materialization":
        return ["materialize_profile_resample_candidate_with_servecsm"]
    if status == "profile_resample_candidate_materialization_failed":
        return ["inspect_profile_resample_servecsm_log"]
    return ["restore_profile_resample_strategy_probe_inputs"]


def build_main_wing_station_seam_profile_resample_strategy_probe_report(
    *,
    export_source_audit_path: Path | None = None,
    materialization_requested: bool = False,
    materialization_root: Path | None = None,
    timeout_seconds: float = 90.0,
    target_profile_point_count: int | None = None,
    station_plane_tolerance: float = 1.0e-4,
    surface_inventory_override: dict[str, Any] | None = None,
) -> MainWingStationSeamProfileResampleStrategyProbeReport:
    blockers: list[str] = []
    audit_path = export_source_audit_path or _default_export_source_audit_path()
    audit_payload = _load_json(
        audit_path,
        blockers,
        "main_wing_station_seam_export_source_audit",
    )
    source_csm_path = (
        _resolve_path(audit_payload.get("rebuild_csm_path"))
        if isinstance(audit_payload, dict)
        else None
    )
    if source_csm_path is None:
        blockers.append("rebuild_csm_path_missing")
        sections: list[dict[str, Any]] = []
    else:
        sections = _parse_csm_sections(source_csm_path, blockers)
    source_counts = [int(section.get("point_count", 0)) for section in sections]
    resolved_target_count = (
        int(target_profile_point_count)
        if target_profile_point_count is not None
        else max(source_counts)
        if source_counts
        else None
    )
    target_stations = _target_station_y_values(audit_payload)
    if not target_stations:
        blockers.append("target_station_y_values_missing")
    if resolved_target_count is None or resolved_target_count < 4:
        blockers.append("target_profile_point_count_invalid")
        candidate_report: dict[str, Any] = {}
    elif not sections:
        candidate_report = {}
    else:
        candidate_report = _build_candidate_report(
            sections=sections,
            source_csm_path=source_csm_path or Path("missing_rebuild.csm"),
            materialization_requested=materialization_requested,
            materialization_root=materialization_root,
            timeout_seconds=timeout_seconds,
            target_profile_point_count=resolved_target_count,
            target_station_y_m=target_stations,
            station_plane_tolerance=station_plane_tolerance,
            surface_inventory_override=surface_inventory_override,
        )
    status = _probe_status(
        blockers=blockers,
        materialization_requested=materialization_requested,
        candidate_report=candidate_report,
    )
    return MainWingStationSeamProfileResampleStrategyProbeReport(
        probe_status=status,
        export_source_audit_path=str(audit_path),
        rebuild_csm_path=str(source_csm_path) if source_csm_path is not None else None,
        materialization_requested=bool(materialization_requested),
        source_profile_point_counts=source_counts,
        target_profile_point_count=resolved_target_count,
        target_station_y_m=target_stations,
        candidate_report=candidate_report,
        engineering_findings=_engineering_findings(
            source_counts=source_counts,
            candidate_report=candidate_report,
        ),
        blocking_reasons=_blocking_reasons(
            status=status,
            blockers=blockers,
            candidate_report=candidate_report,
        ),
        next_actions=_next_actions(status),
        limitations=[
            "This report resamples section profiles in a candidate OpenCSM source only; it does not change the provider default.",
            "A clean single-volume candidate still needs station BRep/PCurve, mesh handoff, SU2, solver, and convergence gates.",
            "Profile resampling can perturb airfoil fidelity and must be evaluated before route promotion.",
        ],
    )


def _render_markdown(
    report: MainWingStationSeamProfileResampleStrategyProbeReport,
) -> str:
    candidate = report.candidate_report
    groups = candidate.get("target_station_face_groups", [])
    face_counts = ", ".join(
        f"{group.get('station_y_m')}:{group.get('plane_face_count')}"
        for group in groups
        if isinstance(group, dict)
    )
    lines = [
        "# Main Wing Station Seam Profile Resample Strategy Probe v1",
        "",
        f"- status: `{report.probe_status}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        f"- materialization_requested: `{report.materialization_requested}`",
        f"- rebuild_csm_path: `{report.rebuild_csm_path}`",
        f"- source_profile_point_counts: `{report.source_profile_point_counts}`",
        f"- target_profile_point_count: `{report.target_profile_point_count}`",
        f"- target_station_y_m: `{report.target_station_y_m}`",
        "",
        "## Candidate",
        "",
        f"- candidate: `{candidate.get('candidate')}`",
        f"- rule_count: `{candidate.get('rule_count')}`",
        f"- materialization_status: `{candidate.get('materialization_status')}`",
        f"- body_count: `{candidate.get('body_count')}`",
        f"- volume_count: `{candidate.get('volume_count')}`",
        f"- surface_count: `{candidate.get('surface_count')}`",
        f"- span_y_bounds_preserved: `{candidate.get('span_y_bounds_preserved')}`",
        f"- target_station_face_counts: `{face_counts}`",
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
    return "\n".join(lines)


def write_main_wing_station_seam_profile_resample_strategy_probe_report(
    out_dir: Path,
    *,
    export_source_audit_path: Path | None = None,
    materialization_requested: bool = False,
    timeout_seconds: float = 90.0,
    target_profile_point_count: int | None = None,
    station_plane_tolerance: float = 1.0e-4,
    report: MainWingStationSeamProfileResampleStrategyProbeReport | None = None,
    surface_inventory_override: dict[str, Any] | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    built_report = report or build_main_wing_station_seam_profile_resample_strategy_probe_report(
        export_source_audit_path=export_source_audit_path,
        materialization_requested=materialization_requested,
        materialization_root=out_dir,
        timeout_seconds=timeout_seconds,
        target_profile_point_count=target_profile_point_count,
        station_plane_tolerance=station_plane_tolerance,
        surface_inventory_override=surface_inventory_override,
    )
    json_path = out_dir / "main_wing_station_seam_profile_resample_strategy_probe.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_profile_resample_strategy_probe.v1.md"
    json_path.write_text(
        json.dumps(built_report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(built_report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
