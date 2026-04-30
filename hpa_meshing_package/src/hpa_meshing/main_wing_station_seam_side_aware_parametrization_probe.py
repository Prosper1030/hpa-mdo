from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from .main_wing_station_seam_profile_resample_strategy_probe import (
    _format_csm_number,
    _materialize_candidate,
    _parse_csm_sections,
    _span_y_bounds_preserved,
    _station_bounds,
    _station_face_groups,
)


SideAwareParametrizationProbeStatusType = Literal[
    "side_aware_parametrization_candidate_materialized_needs_brep_validation",
    "side_aware_parametrization_candidate_topology_risk",
    "side_aware_parametrization_candidate_materialization_failed",
    "side_aware_parametrization_source_only_ready_for_materialization",
    "blocked",
]


class MainWingStationSeamSideAwareParametrizationProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_side_aware_parametrization_probe.v1"
    ] = "main_wing_station_seam_side_aware_parametrization_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_side_aware_profile_parametrization_probe"
    ] = "report_only_side_aware_profile_parametrization_probe"
    production_default_changed: bool = False
    probe_status: SideAwareParametrizationProbeStatusType
    profile_parametrization_audit_path: str
    rebuild_csm_path: str | None = None
    materialization_requested: bool = False
    source_profile_point_counts: list[int] = Field(default_factory=list)
    candidate_profile_point_counts: list[int] = Field(default_factory=list)
    target_station_y_m: list[float] = Field(default_factory=list)
    side_parametrization_summary: dict[str, Any] = Field(default_factory=dict)
    candidate_report: dict[str, Any] = Field(default_factory=dict)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_profile_parametrization_audit_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_profile_parametrization_audit"
        / "main_wing_station_seam_profile_parametrization_audit.v1.json"
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
    result: list[float] = []
    for value in values:
        converted = _as_float(value)
        if converted is not None and converted not in result:
            result.append(converted)
    return result


def _closed_profile_points(
    points: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    if len(points) < 2:
        return list(points)
    if all(abs(lhs - rhs) <= 1.0e-9 for lhs, rhs in zip(points[0], points[-1])):
        return list(points)
    return [*points, points[0]]


def _leading_edge_index(points: list[tuple[float, float, float]]) -> int:
    open_count = max(1, len(points) - 1)
    return min(range(open_count), key=lambda index: points[index][0])


def _split_profile_sides(
    points: list[tuple[float, float, float]],
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    closed = _closed_profile_points(points)
    if len(closed) < 4:
        return closed, closed
    le_index = _leading_edge_index(closed)
    upper = closed[: le_index + 1]
    lower = closed[le_index:]
    return upper, lower


def _polyline_length(points: list[tuple[float, float, float]]) -> float:
    return sum(math.dist(lhs, rhs) for lhs, rhs in zip(points, points[1:]))


def _resample_polyline(
    points: list[tuple[float, float, float]],
    target_count: int,
) -> list[tuple[float, float, float]]:
    if target_count < 2:
        raise ValueError("side-aware resample target count must be at least 2")
    if len(points) < 2:
        raise ValueError("side-aware resample source side needs at least 2 points")
    if target_count == len(points):
        return list(points)
    total = _polyline_length(points)
    if total <= 0.0:
        raise ValueError("side-aware resample source side has zero length")
    cumulative = [0.0]
    for lhs, rhs in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + math.dist(lhs, rhs))
    resampled: list[tuple[float, float, float]] = []
    for index in range(target_count):
        if index == 0:
            resampled.append(points[0])
            continue
        if index == target_count - 1:
            resampled.append(points[-1])
            continue
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
        lhs = points[segment_index]
        rhs = points[segment_index + 1]
        resampled.append(
            tuple(lhs[axis] * (1.0 - fraction) + rhs[axis] * fraction for axis in range(3))
        )
    return resampled


def _target_side_counts(
    sections: list[dict[str, Any]],
    *,
    target_upper_side_point_count: int | None,
    target_lower_side_point_count: int | None,
) -> tuple[int, int]:
    upper_counts: list[int] = []
    lower_counts: list[int] = []
    for section in sections:
        points = section.get("points", [])
        if not isinstance(points, list):
            continue
        upper, lower = _split_profile_sides(points)
        upper_counts.append(len(upper))
        lower_counts.append(len(lower))
    upper_target = (
        int(target_upper_side_point_count)
        if target_upper_side_point_count is not None
        else max(upper_counts or [0])
    )
    lower_target = (
        int(target_lower_side_point_count)
        if target_lower_side_point_count is not None
        else max(lower_counts or [0])
    )
    return upper_target, lower_target


def _side_parametrized_sections(
    sections: list[dict[str, Any]],
    *,
    upper_target_count: int,
    lower_target_count: int,
) -> tuple[list[dict[str, Any]], list[int], dict[str, Any]]:
    candidate_sections: list[dict[str, Any]] = []
    candidate_counts: list[int] = []
    section_summaries: list[dict[str, Any]] = []
    for section in sections:
        points = section.get("points", [])
        if not isinstance(points, list):
            raise ValueError("section points missing")
        upper, lower = _split_profile_sides(points)
        upper_resampled = _resample_polyline(upper, upper_target_count)
        lower_resampled = _resample_polyline(lower, lower_target_count)
        candidate_points = [*upper_resampled, *lower_resampled[1:]]
        candidate_sections.append(
            {
                **section,
                "points": candidate_points,
            }
        )
        candidate_counts.append(len(candidate_points))
        source_le = upper[-1]
        candidate_le = upper_resampled[-1]
        section_summaries.append(
            {
                "csm_section_index": section.get("csm_section_index"),
                "station_y_m": section.get("station_y_m"),
                "source_point_count": len(points),
                "source_upper_side_point_count": len(upper),
                "source_lower_side_point_count": len(lower),
                "candidate_point_count": len(candidate_points),
                "candidate_upper_side_point_count": len(upper_resampled),
                "candidate_lower_side_point_count": len(lower_resampled),
                "leading_edge_anchor_delta_m": math.dist(source_le, candidate_le),
                "trailing_edge_anchor_delta_m": math.dist(points[0], candidate_points[0]),
            }
        )
    max_le_delta = max(
        (
            float(item["leading_edge_anchor_delta_m"])
            for item in section_summaries
            if isinstance(item.get("leading_edge_anchor_delta_m"), (int, float))
        ),
        default=None,
    )
    max_te_delta = max(
        (
            float(item["trailing_edge_anchor_delta_m"])
            for item in section_summaries
            if isinstance(item.get("trailing_edge_anchor_delta_m"), (int, float))
        ),
        default=None,
    )
    summary = {
        "target_upper_side_point_count": upper_target_count,
        "target_lower_side_point_count": lower_target_count,
        "candidate_profile_point_count": (
            upper_target_count + lower_target_count - 1
        ),
        "max_le_anchor_delta_m": max_le_delta,
        "max_te_anchor_delta_m": max_te_delta,
        "section_summaries": section_summaries,
    }
    return candidate_sections, candidate_counts, summary


def _build_candidate_csm(
    *,
    sections: list[dict[str, Any]],
    source_csm_path: Path,
    export_filename: str,
) -> str:
    lines = [
        "# Auto-generated by hpa_meshing.main_wing_station_seam_side_aware_parametrization_probe",
        "# Report-only candidate; not a production provider default",
        "# Resamples upper and lower profile sides independently while preserving TE/LE anchors",
        f"# Source rebuild.csm: {source_csm_path}",
        f"SET export_path $\"{export_filename}\"",
        "",
        "mark",
    ]
    for section in sections:
        points = section.get("points", [])
        if not isinstance(points, list) or len(points) < 4:
            raise ValueError("candidate section points missing")
        lines.append(
            "skbeg " + " ".join(_format_csm_number(value) for value in points[0])
        )
        for point_index, point in enumerate(points[1:], start=1):
            opcode = "linseg" if point_index == 1 or point_index == len(points) - 1 else "spline"
            lines.append(
                f"   {opcode} "
                + " ".join(_format_csm_number(value) for value in point)
            )
        lines.append("skend")
    lines.extend(
        [
            "rule",
            "ATTRIBUTE _name $main_wing_side_aware_profile_parametrization",
            "ATTRIBUTE capsGroup $main_wing",
            "DUMP !export_path 0 1",
            "END",
            "",
        ]
    )
    return "\n".join(lines)


def _candidate_report(
    *,
    materialization: dict[str, Any] | None,
    materialization_requested: bool,
    expected_bounds: dict[str, float | None],
    target_station_y_m: list[float],
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "candidate": "side_aware_profile_parametrization_single_rule",
        "intended_use": "report_only_candidate_for_station_brep_validation",
        "risk": "candidate_not_mesh_ready_until_brep_validation_passes",
    }
    if not materialization_requested:
        return {
            **base,
            "candidate_csm_text_available": True,
            "materialization_status": "not_requested",
        }
    materialization = materialization or {}
    topology = materialization.get("topology", {})
    topology = topology if isinstance(topology, dict) else {}
    span_preserved = _span_y_bounds_preserved(
        topology=topology,
        expected_bounds=expected_bounds,
    )
    target_face_groups = _station_face_groups(
        topology=topology,
        target_station_y_m=target_station_y_m,
        station_plane_tolerance=1.0e-4,
    )
    return {
        **base,
        "candidate_csm_text_available": True,
        "materialization": materialization,
        "materialization_status": materialization.get("status"),
        "body_count": topology.get("body_count"),
        "volume_count": topology.get("volume_count"),
        "surface_count": topology.get("surface_count"),
        "bbox": topology.get("bbox"),
        "span_y_bounds_preserved": span_preserved,
        "target_station_face_groups": target_face_groups,
    }


def _candidate_is_clean_materialized(candidate: dict[str, Any]) -> bool:
    target_groups = [
        group
        for group in candidate.get("target_station_face_groups", [])
        if isinstance(group, dict)
    ]
    return (
        candidate.get("materialization_status") == "materialized"
        and candidate.get("body_count") == 1
        and candidate.get("volume_count") == 1
        and candidate.get("span_y_bounds_preserved") is True
        and all(int(group.get("plane_face_count") or 0) == 0 for group in target_groups)
    )


def _status(
    *,
    blockers: list[str],
    candidate: dict[str, Any],
    materialization_requested: bool,
) -> SideAwareParametrizationProbeStatusType:
    if blockers:
        return "blocked"
    if not materialization_requested:
        return "side_aware_parametrization_source_only_ready_for_materialization"
    if candidate.get("materialization_status") != "materialized":
        return "side_aware_parametrization_candidate_materialization_failed"
    if _candidate_is_clean_materialized(candidate):
        return "side_aware_parametrization_candidate_materialized_needs_brep_validation"
    return "side_aware_parametrization_candidate_topology_risk"


def _engineering_findings(
    *,
    status: SideAwareParametrizationProbeStatusType,
    side_summary: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["side_aware_parametrization_probe_blocked"]
    findings = ["side_aware_parametrization_probe_captured"]
    findings.append("side_aware_profile_sections_uniformized_by_upper_lower_correspondence")
    if side_summary.get("max_le_anchor_delta_m") == 0.0:
        findings.append("leading_edge_anchors_preserved")
    if side_summary.get("max_te_anchor_delta_m") == 0.0:
        findings.append("trailing_edge_anchors_preserved")
    if _candidate_is_clean_materialized(candidate):
        findings.append("side_aware_candidate_single_volume_full_span_observed")
        findings.append("side_aware_candidate_no_target_cap_faces_detected")
    elif status == "side_aware_parametrization_candidate_topology_risk":
        findings.append("side_aware_candidate_topology_risk_observed")
    return findings


def _blocking_reasons(
    *,
    status: SideAwareParametrizationProbeStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "side_aware_parametrization_source_only_ready_for_materialization":
        reasons.append("side_aware_candidate_materialization_not_run")
    if status == "side_aware_parametrization_candidate_materialization_failed":
        reasons.append("side_aware_candidate_materialization_failed")
    if status == "side_aware_parametrization_candidate_topology_risk":
        reasons.append("side_aware_candidate_topology_risk")
    if status == "side_aware_parametrization_candidate_materialized_needs_brep_validation":
        reasons.append(
            "side_aware_candidate_needs_station_brep_validation_before_mesh_handoff"
        )
    if status == "blocked" and not reasons:
        reasons.append("side_aware_parametrization_probe_blocked")
    return reasons


def _next_actions(status: SideAwareParametrizationProbeStatusType) -> list[str]:
    if status == "side_aware_parametrization_source_only_ready_for_materialization":
        return ["materialize_side_aware_profile_parametrization_candidate"]
    if status == "side_aware_parametrization_candidate_materialized_needs_brep_validation":
        return [
            "run_profile_resample_brep_validation_on_side_aware_candidate",
            "compare_side_aware_candidate_against_uniform_profile_resample",
            "keep_side_aware_candidate_behind_report_only_gate",
        ]
    if status == "side_aware_parametrization_candidate_topology_risk":
        return ["inspect_side_aware_candidate_topology_before_brep_validation"]
    if status == "side_aware_parametrization_candidate_materialization_failed":
        return ["inspect_side_aware_candidate_ocsm_log"]
    return ["restore_side_aware_parametrization_probe_inputs"]


def build_main_wing_station_seam_side_aware_parametrization_probe_report(
    *,
    profile_parametrization_audit_path: Path | None = None,
    materialization_requested: bool = False,
    materialization_root: Path | None = None,
    timeout_seconds: float = 90.0,
    target_upper_side_point_count: int | None = None,
    target_lower_side_point_count: int | None = None,
    surface_inventory_override: dict[str, Any] | None = None,
) -> MainWingStationSeamSideAwareParametrizationProbeReport:
    audit_path = (
        _default_profile_parametrization_audit_path()
        if profile_parametrization_audit_path is None
        else profile_parametrization_audit_path
    )
    blockers: list[str] = []
    audit_payload = _load_json(audit_path, blockers, "profile_parametrization_audit")
    rebuild_csm_path = _resolve_path(
        audit_payload.get("source_csm_path") if isinstance(audit_payload, dict) else None
    )
    if rebuild_csm_path is None:
        blockers.append("side_aware_rebuild_csm_path_missing")
    elif not rebuild_csm_path.exists():
        blockers.append("side_aware_rebuild_csm_missing")
    target_station_y_m = _float_list(
        audit_payload.get("target_station_y_m")
        if isinstance(audit_payload, dict)
        else []
    )
    if not target_station_y_m:
        blockers.append("side_aware_target_station_y_missing")

    sections: list[dict[str, Any]] = []
    if rebuild_csm_path is not None and rebuild_csm_path.exists():
        sections = _parse_csm_sections(rebuild_csm_path, blockers)
    source_counts = [
        int(section.get("point_count") or 0)
        for section in sections
        if isinstance(section, dict)
    ]

    candidate_counts: list[int] = []
    side_summary: dict[str, Any] = {}
    csm_text = ""
    materialization: dict[str, Any] | None = None
    if not blockers and rebuild_csm_path is not None:
        upper_target, lower_target = _target_side_counts(
            sections,
            target_upper_side_point_count=target_upper_side_point_count,
            target_lower_side_point_count=target_lower_side_point_count,
        )
        candidate_sections, candidate_counts, side_summary = _side_parametrized_sections(
            sections,
            upper_target_count=upper_target,
            lower_target_count=lower_target,
        )
        csm_text = _build_candidate_csm(
            sections=candidate_sections,
            source_csm_path=rebuild_csm_path,
            export_filename="candidate_raw_dump.stp",
        )
        if materialization_requested:
            root = (
                _default_report_root()
                / "main_wing_station_seam_side_aware_parametrization_probe"
                / "artifacts"
                / "side_aware_profile_parametrization_single_rule"
                if materialization_root is None
                else materialization_root / "side_aware_profile_parametrization_single_rule"
            )
            materialization = _materialize_candidate(
                out_dir=root,
                csm_text=csm_text,
                timeout_seconds=timeout_seconds,
                surface_inventory_override=surface_inventory_override,
            )
    expected_bounds = _station_bounds(sections)
    candidate = _candidate_report(
        materialization=materialization,
        materialization_requested=materialization_requested,
        expected_bounds=expected_bounds,
        target_station_y_m=target_station_y_m,
    )
    if not materialization_requested and csm_text:
        candidate["candidate_csm_text_preview"] = csm_text[:2000]
    status = _status(
        blockers=blockers,
        candidate=candidate,
        materialization_requested=materialization_requested,
    )
    return MainWingStationSeamSideAwareParametrizationProbeReport(
        probe_status=status,
        profile_parametrization_audit_path=str(audit_path),
        rebuild_csm_path=str(rebuild_csm_path) if rebuild_csm_path is not None else None,
        materialization_requested=materialization_requested,
        source_profile_point_counts=source_counts,
        candidate_profile_point_counts=candidate_counts,
        target_station_y_m=target_station_y_m,
        side_parametrization_summary=side_summary,
        candidate_report=candidate,
        engineering_findings=_engineering_findings(
            status=status,
            side_summary=side_summary,
            candidate=candidate,
        ),
        blocking_reasons=_blocking_reasons(status=status, blockers=blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This probe emits a report-only candidate and does not change production defaults.",
            "Side-aware resampling preserves TE/LE anchors and upper/lower correspondence, but does not by itself prove PCurve consistency.",
            "A materialized side-aware STEP still needs candidate station BRep/PCurve validation before mesh handoff.",
            "It does not run Gmsh volume meshing, SU2_CFD, CL acceptance, or convergence checks.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingStationSeamSideAwareParametrizationProbeReport,
) -> str:
    lines = [
        "# Main Wing Station Seam Side-Aware Parametrization Probe v1",
        "",
        "This report builds a side-aware profile parametrization candidate without changing provider defaults.",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- profile_parametrization_audit_path: `{report.profile_parametrization_audit_path}`",
        f"- rebuild_csm_path: `{report.rebuild_csm_path}`",
        f"- materialization_requested: `{report.materialization_requested}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Side Parametrization Summary",
        "",
    ]
    for key, value in report.side_parametrization_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Candidate Report", ""])
    for key, value in report.candidate_report.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
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


def write_main_wing_station_seam_side_aware_parametrization_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamSideAwareParametrizationProbeReport | None = None,
    profile_parametrization_audit_path: Path | None = None,
    materialization_requested: bool = False,
    timeout_seconds: float = 90.0,
    target_upper_side_point_count: int | None = None,
    target_lower_side_point_count: int | None = None,
    surface_inventory_override: dict[str, Any] | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_side_aware_parametrization_probe_report(
            profile_parametrization_audit_path=profile_parametrization_audit_path,
            materialization_requested=materialization_requested,
            materialization_root=out_dir,
            timeout_seconds=timeout_seconds,
            target_upper_side_point_count=target_upper_side_point_count,
            target_lower_side_point_count=target_lower_side_point_count,
            surface_inventory_override=surface_inventory_override,
        )
    json_path = out_dir / "main_wing_station_seam_side_aware_parametrization_probe.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_side_aware_parametrization_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
