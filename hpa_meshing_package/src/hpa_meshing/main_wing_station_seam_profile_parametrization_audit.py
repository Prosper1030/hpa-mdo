from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field


ProfileParametrizationAuditStatusType = Literal[
    "profile_parametrization_seam_fragment_correlation_observed",
    "profile_parametrization_audit_captured",
    "blocked",
]


class MainWingStationSeamProfileParametrizationAuditReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_profile_parametrization_audit.v1"
    ] = "main_wing_station_seam_profile_parametrization_audit.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_profile_parametrization_audit"
    ] = "report_only_profile_parametrization_audit"
    production_default_changed: bool = False
    audit_status: ProfileParametrizationAuditStatusType
    profile_resample_probe_path: str
    brep_validation_probe_path: str
    source_csm_path: str | None = None
    candidate_csm_path: str | None = None
    target_station_y_m: list[float] = Field(default_factory=list)
    source_profile_point_counts: list[int] = Field(default_factory=list)
    candidate_profile_point_counts: list[int] = Field(default_factory=list)
    source_section_summary: dict[str, Any] = Field(default_factory=dict)
    candidate_section_summary: dict[str, Any] = Field(default_factory=dict)
    station_fragment_summary: dict[str, Any] = Field(default_factory=dict)
    target_station_correlations: list[dict[str, Any]] = Field(default_factory=list)
    edge_failure_summary: dict[str, Any] = Field(default_factory=dict)
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


def _default_brep_validation_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_profile_resample_brep_validation_probe"
        / "main_wing_station_seam_profile_resample_brep_validation_probe.v1.json"
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


def _int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    result: list[int] = []
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            result.append(int(value))
    return result


def _candidate_csm_path(profile_payload: dict[str, Any] | None) -> Path | None:
    if not isinstance(profile_payload, dict):
        return None
    candidate = profile_payload.get("candidate_report", {})
    candidate = candidate if isinstance(candidate, dict) else {}
    materialization = candidate.get("materialization", {})
    materialization = materialization if isinstance(materialization, dict) else {}
    return _resolve_path(materialization.get("csm_path") or candidate.get("csm_path"))


def _source_csm_path(profile_payload: dict[str, Any] | None) -> Path | None:
    if not isinstance(profile_payload, dict):
        return None
    return _resolve_path(profile_payload.get("rebuild_csm_path"))


def _point_from_tokens(tokens: list[str]) -> tuple[float, float, float] | None:
    if len(tokens) < 4:
        return None
    try:
        return (float(tokens[1]), float(tokens[2]), float(tokens[3]))
    except ValueError:
        return None


def _parse_csm_sections(
    path: Path,
    blockers: list[str],
    label: str,
) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        blockers.append(f"{label}_csm_missing")
        return []

    sections: list[dict[str, Any]] = []
    current_points: list[tuple[float, float, float]] = []
    current_opcodes: list[str] = []
    for line in lines:
        tokens = line.strip().split()
        if not tokens:
            continue
        opcode = tokens[0]
        if opcode == "skbeg":
            point = _point_from_tokens(tokens)
            current_points = [] if point is None else [point]
            current_opcodes = [] if point is None else ["skbeg"]
            continue
        if opcode in {"linseg", "spline"} and current_points:
            point = _point_from_tokens(tokens)
            if point is not None:
                current_points.append(point)
                current_opcodes.append(opcode)
            continue
        if opcode == "skend" and current_points:
            segments: list[dict[str, Any]] = []
            for index, (start, end) in enumerate(
                zip(current_points, current_points[1:])
            ):
                segments.append(
                    {
                        "segment_index": index,
                        "opcode": current_opcodes[index + 1],
                        "length_m": math.dist(start, end),
                    }
                )
            sections.append(
                {
                    "csm_section_index": len(sections),
                    "station_y_m": current_points[0][1],
                    "point_count": len(current_points),
                    "segment_count": len(segments),
                    "segments": segments,
                }
            )
            current_points = []
            current_opcodes = []
    if not sections:
        blockers.append(f"{label}_csm_sections_missing")
    return sections


def _section_summary(sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "section_count": len(sections),
        "profile_point_counts": [
            int(section.get("point_count") or 0) for section in sections
        ],
        "station_y_m": [
            section.get("station_y_m")
            for section in sections
            if section.get("station_y_m") is not None
        ],
    }


def _section_for_station(
    sections: list[dict[str, Any]],
    station_y_m: float,
    tolerance: float,
) -> dict[str, Any] | None:
    candidates = [
        section
        for section in sections
        if _as_float(section.get("station_y_m")) is not None
        and abs(float(section["station_y_m"]) - station_y_m) <= tolerance
    ]
    if candidates:
        return min(
            candidates,
            key=lambda section: abs(float(section["station_y_m"]) - station_y_m),
        )
    return None


def _segment_summary(section: dict[str, Any] | None) -> dict[str, Any]:
    if section is None:
        return {}
    segments = [
        segment
        for segment in section.get("segments", [])
        if isinstance(segment, dict)
    ]
    if len(segments) < 2:
        return {
            "csm_section_index": section.get("csm_section_index"),
            "point_count": section.get("point_count"),
            "segment_count": len(segments),
        }
    first = segments[0]
    closing = segments[-1]
    interior = segments[1:-1]
    first_length = _as_float(first.get("length_m")) or 0.0
    closing_length = _as_float(closing.get("length_m")) or 0.0
    rest_length = sum(
        _as_float(segment.get("length_m")) or 0.0 for segment in interior
    )
    return {
        "csm_section_index": section.get("csm_section_index"),
        "station_y_m": section.get("station_y_m"),
        "point_count": section.get("point_count"),
        "segment_count": len(segments),
        "first_segment_opcode": first.get("opcode"),
        "first_segment_length_m": first_length,
        "closing_segment_opcode": closing.get("opcode"),
        "closing_segment_length_m": closing_length,
        "rest_arc_length_m": rest_length,
        "perimeter_length_m": first_length + rest_length + closing_length,
        "interior_opcodes": sorted(
            {
                str(segment.get("opcode"))
                for segment in interior
                if segment.get("opcode") is not None
            }
        ),
    }


def _relative_match(length: float, target: Any, tolerance: float) -> bool:
    target_float = _as_float(target)
    if target_float is None:
        return False
    scale = max(abs(length), abs(target_float), 1.0e-12)
    return abs(length - target_float) / scale <= tolerance


def _pcurve_check_failed(check: dict[str, Any]) -> bool:
    if check.get("pcurve_checks_complete") is False:
        return True
    return any(
        check.get(key) is False
        for key in (
            "curve3d_with_pcurve_consistent",
            "same_parameter_by_face_ok",
            "vertex_tolerance_by_face_ok",
            "pcurve_range_matches_edge_range",
        )
    )


def _curve_correlations(
    edge_checks: list[dict[str, Any]],
    segment: dict[str, Any],
    match_tolerance: float,
) -> list[dict[str, Any]]:
    correlations: list[dict[str, Any]] = []
    for check in edge_checks:
        length = _as_float(
            check.get("gmsh_length_3d_m")
            if check.get("gmsh_length_3d_m") is not None
            else check.get("edge_length_3d_m")
        )
        matched_segments: list[str] = []
        if length is not None:
            if _relative_match(
                length,
                segment.get("first_segment_length_m"),
                match_tolerance,
            ):
                matched_segments.append("first_segment")
            if _relative_match(
                length,
                segment.get("closing_segment_length_m"),
                match_tolerance,
            ):
                matched_segments.append("closing_segment")
            if _relative_match(
                length,
                segment.get("rest_arc_length_m"),
                match_tolerance,
            ):
                matched_segments.append("rest_arc")
            if _relative_match(
                length,
                segment.get("perimeter_length_m"),
                match_tolerance,
            ):
                matched_segments.append("perimeter")
        classification = (
            "terminal_linseg_segment"
            if any(item in matched_segments for item in ("first_segment", "closing_segment"))
            and "rest_arc" not in matched_segments
            else "rest_arc"
            if "rest_arc" in matched_segments
            else "perimeter"
            if "perimeter" in matched_segments
            else "unmatched"
        )
        correlations.append(
            {
                "candidate_step_curve_tag": check.get("candidate_step_curve_tag"),
                "curve_length_m": length,
                "classification": classification,
                "matched_segment_keys": matched_segments,
                "pcurve_check_failed": _pcurve_check_failed(check),
                "owner_surface_tags": check.get("owner_surface_tags", []),
            }
        )
    return correlations


def _edge_checks_by_station(
    edge_checks: list[dict[str, Any]],
    station_y_m: float,
    tolerance: float,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for check in edge_checks:
        station = _as_float(check.get("station_y_m"))
        if station is not None and abs(station - station_y_m) <= tolerance:
            matches.append(check)
    return sorted(
        matches,
        key=lambda check: -float(
            _as_float(
                check.get("gmsh_length_3d_m")
                if check.get("gmsh_length_3d_m") is not None
                else check.get("edge_length_3d_m")
            )
            or 0.0
        ),
    )


def _build_station_correlations(
    *,
    target_station_y_m: list[float],
    candidate_sections: list[dict[str, Any]],
    source_sections: list[dict[str, Any]],
    edge_checks: list[dict[str, Any]],
    station_tolerance_m: float,
    match_tolerance: float,
) -> list[dict[str, Any]]:
    correlations: list[dict[str, Any]] = []
    for station in target_station_y_m:
        candidate_section = _section_for_station(
            candidate_sections,
            station,
            station_tolerance_m,
        )
        source_section = _section_for_station(
            source_sections,
            station,
            station_tolerance_m,
        )
        candidate_segment = _segment_summary(candidate_section)
        source_segment = _segment_summary(source_section)
        station_checks = _edge_checks_by_station(
            edge_checks,
            station,
            station_tolerance_m,
        )
        curve_matches = _curve_correlations(
            station_checks,
            candidate_segment,
            match_tolerance,
        )
        terminal_count = sum(
            match.get("classification") == "terminal_linseg_segment"
            for match in curve_matches
        )
        rest_count = sum(match.get("classification") == "rest_arc" for match in curve_matches)
        failed_count = sum(
            match.get("pcurve_check_failed") is True for match in curve_matches
        )
        correlations.append(
            {
                "station_y_m": station,
                "candidate_section_index": (
                    None
                    if candidate_section is None
                    else candidate_section.get("csm_section_index")
                ),
                "source_section_index": (
                    None
                    if source_section is None
                    else source_section.get("csm_section_index")
                ),
                "segment_summary": candidate_segment,
                "source_segment_summary": source_segment,
                "curve_correlations": curve_matches,
                "station_edge_check_count": len(station_checks),
                "terminal_linseg_match_count": terminal_count,
                "rest_arc_match_count": rest_count,
                "failed_pcurve_check_count": failed_count,
                "all_station_edge_pcurve_checks_failed": bool(station_checks)
                and failed_count == len(station_checks),
            }
        )
    return correlations


def _station_fragment_summary(
    correlations: list[dict[str, Any]],
) -> dict[str, Any]:
    station_edge_total = sum(
        int(item.get("station_edge_check_count") or 0) for item in correlations
    )
    failed_total = sum(
        int(item.get("failed_pcurve_check_count") or 0) for item in correlations
    )
    terminal_total = sum(
        int(item.get("terminal_linseg_match_count") or 0) for item in correlations
    )
    rest_total = sum(int(item.get("rest_arc_match_count") or 0) for item in correlations)
    return {
        "station_count": len(correlations),
        "station_edge_check_count_total": station_edge_total,
        "failed_pcurve_check_count_total": failed_total,
        "terminal_linseg_match_count_total": terminal_total,
        "rest_arc_match_count_total": rest_total,
        "stations_with_terminal_linseg_matches": sum(
            int(item.get("terminal_linseg_match_count") or 0) > 0
            for item in correlations
        ),
        "stations_with_rest_arc_matches": sum(
            int(item.get("rest_arc_match_count") or 0) > 0
            for item in correlations
        ),
        "all_station_edge_pcurve_checks_failed": station_edge_total > 0
        and failed_total == station_edge_total,
    }


def _edge_failure_summary(edge_checks: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(edge_checks)
    failed = sum(_pcurve_check_failed(check) for check in edge_checks)
    return {
        "station_edge_check_count": total,
        "failed_pcurve_check_count": failed,
        "pcurve_presence_complete_count": sum(
            check.get("pcurve_presence_complete") is True for check in edge_checks
        ),
        "curve3d_with_pcurve_consistent_count": sum(
            check.get("curve3d_with_pcurve_consistent") is True
            for check in edge_checks
        ),
        "same_parameter_by_face_ok_count": sum(
            check.get("same_parameter_by_face_ok") is True for check in edge_checks
        ),
        "vertex_tolerance_by_face_ok_count": sum(
            check.get("vertex_tolerance_by_face_ok") is True for check in edge_checks
        ),
        "all_station_edge_pcurve_checks_failed": total > 0 and failed == total,
    }


def _status(
    blockers: list[str],
    station_summary: dict[str, Any],
) -> ProfileParametrizationAuditStatusType:
    if blockers:
        return "blocked"
    if (
        int(station_summary.get("terminal_linseg_match_count_total") or 0) > 0
        and int(station_summary.get("rest_arc_match_count_total") or 0) > 0
        and station_summary.get("all_station_edge_pcurve_checks_failed") is True
    ):
        return "profile_parametrization_seam_fragment_correlation_observed"
    return "profile_parametrization_audit_captured"


def _engineering_findings(
    *,
    status: ProfileParametrizationAuditStatusType,
    source_profile_point_counts: list[int],
    station_summary: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["profile_parametrization_audit_blocked"]
    findings = ["profile_parametrization_audit_captured"]
    if len(set(source_profile_point_counts)) > 1:
        findings.append("source_profile_point_count_mismatch_observed")
    if int(station_summary.get("terminal_linseg_match_count_total") or 0) > 0:
        findings.append("station_short_curves_match_profile_terminal_linseg_segments")
    if int(station_summary.get("rest_arc_match_count_total") or 0) > 0:
        findings.append("station_long_curves_match_profile_spline_rest_arc")
    if station_summary.get("all_station_edge_pcurve_checks_failed") is True:
        findings.append(
            "profile_resample_candidate_parameter_consistency_fails_on_all_station_fragments"
        )
    findings.append("profile_parametrization_export_change_needed")
    return findings


def _blocking_reasons(
    *,
    status: ProfileParametrizationAuditStatusType,
    blockers: list[str],
    brep_payload: dict[str, Any] | None,
    station_summary: dict[str, Any],
) -> list[str]:
    reasons = list(blockers)
    if isinstance(brep_payload, dict):
        brep_reasons = brep_payload.get("blocking_reasons", [])
        if isinstance(brep_reasons, list):
            reasons.extend(str(reason) for reason in brep_reasons)
    if (
        status != "blocked"
        and station_summary.get("all_station_edge_pcurve_checks_failed") is True
    ):
        reasons.append("profile_parametrization_export_change_needed_before_mesh_handoff")
    if status == "blocked" and not reasons:
        reasons.append("profile_parametrization_audit_blocked")
    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def _next_actions(status: ProfileParametrizationAuditStatusType) -> list[str]:
    if status == "profile_parametrization_seam_fragment_correlation_observed":
        return [
            "prototype_side_aware_profile_parametrization_candidate",
            "rerun_profile_resample_brep_validation_on_side_aware_candidate",
            "avoid_solver_iteration_budget_until_station_parametrization_gate_is_clean",
        ]
    if status == "profile_parametrization_audit_captured":
        return [
            "add_station_edge_residual_diagnostics_before_export_change",
            "compare_csm_opcode_candidate_against_current_profile_resample",
        ]
    return ["restore_profile_parametrization_audit_inputs"]


def build_main_wing_station_seam_profile_parametrization_audit_report(
    *,
    profile_resample_probe_path: Path | None = None,
    brep_validation_probe_path: Path | None = None,
    station_tolerance_m: float = 1.0e-4,
    match_tolerance: float = 0.03,
) -> MainWingStationSeamProfileParametrizationAuditReport:
    profile_path = (
        _default_profile_resample_probe_path()
        if profile_resample_probe_path is None
        else profile_resample_probe_path
    )
    brep_path = (
        _default_brep_validation_probe_path()
        if brep_validation_probe_path is None
        else brep_validation_probe_path
    )
    blockers: list[str] = []
    profile_payload = _load_json(profile_path, blockers, "profile_resample_probe")
    brep_payload = _load_json(brep_path, blockers, "brep_validation_probe")

    candidate_csm_path = _candidate_csm_path(profile_payload)
    source_csm_path = _source_csm_path(profile_payload)
    if candidate_csm_path is None:
        blockers.append("profile_resample_candidate_csm_path_missing")
    elif not candidate_csm_path.exists():
        blockers.append("profile_resample_candidate_csm_missing")

    target_station_y_m = _float_list(
        profile_payload.get("target_station_y_m")
        if isinstance(profile_payload, dict)
        else []
    )
    if not target_station_y_m:
        target_station_y_m = _float_list(
            brep_payload.get("target_station_y_m")
            if isinstance(brep_payload, dict)
            else []
        )
    if not target_station_y_m:
        blockers.append("profile_parametrization_target_station_y_missing")

    candidate_sections: list[dict[str, Any]] = []
    source_sections: list[dict[str, Any]] = []
    if candidate_csm_path is not None and candidate_csm_path.exists():
        candidate_sections = _parse_csm_sections(
            candidate_csm_path,
            blockers,
            "candidate",
        )
    if source_csm_path is not None and source_csm_path.exists():
        source_sections = _parse_csm_sections(source_csm_path, blockers, "source")

    edge_checks = [
        check
        for check in (
            brep_payload.get("station_edge_checks", [])
            if isinstance(brep_payload, dict)
            else []
        )
        if isinstance(check, dict)
    ]
    if not edge_checks:
        blockers.append("profile_parametrization_station_edge_checks_missing")

    source_profile_point_counts = _int_list(
        profile_payload.get("source_profile_point_counts")
        if isinstance(profile_payload, dict)
        else []
    )
    candidate_report = (
        profile_payload.get("candidate_report", {})
        if isinstance(profile_payload, dict)
        else {}
    )
    candidate_report = candidate_report if isinstance(candidate_report, dict) else {}
    candidate_profile_point_counts = _int_list(
        candidate_report.get("candidate_profile_point_counts")
    )

    target_station_correlations: list[dict[str, Any]] = []
    if not blockers:
        target_station_correlations = _build_station_correlations(
            target_station_y_m=target_station_y_m,
            candidate_sections=candidate_sections,
            source_sections=source_sections,
            edge_checks=edge_checks,
            station_tolerance_m=station_tolerance_m,
            match_tolerance=match_tolerance,
        )
    station_summary = _station_fragment_summary(target_station_correlations)
    edge_summary = _edge_failure_summary(edge_checks)
    status = _status(blockers, station_summary)
    return MainWingStationSeamProfileParametrizationAuditReport(
        audit_status=status,
        profile_resample_probe_path=str(profile_path),
        brep_validation_probe_path=str(brep_path),
        source_csm_path=str(source_csm_path) if source_csm_path is not None else None,
        candidate_csm_path=(
            str(candidate_csm_path) if candidate_csm_path is not None else None
        ),
        target_station_y_m=target_station_y_m,
        source_profile_point_counts=source_profile_point_counts,
        candidate_profile_point_counts=candidate_profile_point_counts,
        source_section_summary=_section_summary(source_sections),
        candidate_section_summary=_section_summary(candidate_sections),
        station_fragment_summary=station_summary,
        target_station_correlations=target_station_correlations,
        edge_failure_summary=edge_summary,
        engineering_findings=_engineering_findings(
            status=status,
            source_profile_point_counts=source_profile_point_counts,
            station_summary=station_summary,
        ),
        blocking_reasons=_blocking_reasons(
            status=status,
            blockers=blockers,
            brep_payload=brep_payload,
            station_summary=station_summary,
        ),
        next_actions=_next_actions(status),
        limitations=[
            "This is a report-only audit and does not change provider defaults.",
            "Curve-to-segment correlation is length-based evidence, not a direct CAD identity map.",
            "It does not materialize a new CSM candidate, generate a Gmsh mesh, run SU2_CFD, or judge convergence.",
            "Engineering acceptance still requires a repaired geometry/mesh gate and CL >= 1 under the HPA 6.5 m/s flow condition.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingStationSeamProfileParametrizationAuditReport,
) -> str:
    lines = [
        "# Main Wing Station Seam Profile Parametrization Audit v1",
        "",
        "This report correlates profile-resample station-edge failures with CSM section segment parametrization without changing production defaults.",
        "",
        f"- audit_status: `{report.audit_status}`",
        f"- profile_resample_probe_path: `{report.profile_resample_probe_path}`",
        f"- brep_validation_probe_path: `{report.brep_validation_probe_path}`",
        f"- candidate_csm_path: `{report.candidate_csm_path}`",
        f"- source_csm_path: `{report.source_csm_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Station Fragment Summary",
        "",
    ]
    for key, value in report.station_fragment_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Edge Failure Summary", ""])
    for key, value in report.edge_failure_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Target Station Correlations", ""])
    if report.target_station_correlations:
        lines.extend(f"- `{_fmt(item)}`" for item in report.target_station_correlations)
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


def write_main_wing_station_seam_profile_parametrization_audit_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamProfileParametrizationAuditReport | None = None,
    profile_resample_probe_path: Path | None = None,
    brep_validation_probe_path: Path | None = None,
    station_tolerance_m: float = 1.0e-4,
    match_tolerance: float = 0.03,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_profile_parametrization_audit_report(
            profile_resample_probe_path=profile_resample_probe_path,
            brep_validation_probe_path=brep_validation_probe_path,
            station_tolerance_m=station_tolerance_m,
            match_tolerance=match_tolerance,
        )
    json_path = out_dir / "main_wing_station_seam_profile_parametrization_audit.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_profile_parametrization_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
