from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Literal
import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field

from .main_wing_geometry_provenance_probe import _find_main_wing, _point_values


CurveStationRebuildStatusType = Literal[
    "curve_tags_match_vsp3_section_profile_scale",
    "curve_tags_deviate_from_vsp3_section_profile_scale",
    "no_candidate_curves",
    "blocked",
]


class MainWingGmshCurveStationRebuildAuditReport(BaseModel):
    schema_version: Literal["main_wing_gmsh_curve_station_rebuild_audit.v1"] = (
        "main_wing_gmsh_curve_station_rebuild_audit.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_curve_and_vsp3_artifacts"] = (
        "report_only_existing_curve_and_vsp3_artifacts"
    )
    production_default_changed: bool = False
    curve_station_rebuild_status: CurveStationRebuildStatusType
    gmsh_defect_entity_trace_path: str
    source_vsp3_path: str
    relative_length_tolerance: float
    curve_matches: List[Dict[str, Any]] = Field(default_factory=list)
    match_summary: Dict[str, Any] = Field(default_factory=dict)
    blocking_reasons: List[str] = Field(default_factory=list)
    engineering_findings: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_gmsh_defect_entity_trace_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_gmsh_defect_entity_trace"
        / "main_wing_gmsh_defect_entity_trace.v1.json"
    )


def _default_source_vsp3_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_real_mesh_handoff_probe"
        / "artifacts"
        / "real_mesh_probe"
        / "artifacts"
        / "providers"
        / "esp_rebuilt"
        / "esp_runtime"
        / "main_wing.vsp3"
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


def _polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(
        math.hypot(
            points[index + 1][0] - points[index][0],
            points[index + 1][1] - points[index][1],
        )
        for index in range(len(points) - 1)
    )


def _closed_profile_perimeter_ratio(
    upper: list[tuple[float, float]],
    lower: list[tuple[float, float]],
) -> float | None:
    if not upper or not lower:
        return None
    profile = upper + list(reversed(lower))
    if len(profile) < 2:
        return None
    return _polyline_length(profile) + math.hypot(
        profile[0][0] - profile[-1][0],
        profile[0][1] - profile[-1][1],
    )


def _vsp3_profile_sections(path: Path, blockers: list[str]) -> dict[int, dict[str, Any]]:
    try:
        root = ET.parse(path).getroot()
    except FileNotFoundError:
        blockers.append("source_vsp3_missing")
        return {}
    except ET.ParseError as exc:
        blockers.append(f"source_vsp3_parse_failed:{exc}")
        return {}
    geom = _find_main_wing(root)
    if geom is None:
        blockers.append("source_vsp3_main_wing_missing")
        return {}
    xsec_surf = geom.find(".//XSecSurf")
    xsecs = xsec_surf.findall("./XSec") if xsec_surf is not None else []
    sections: dict[int, dict[str, Any]] = {}
    for index, xsec in enumerate(xsecs):
        file_airfoil = xsec.find(".//FileAirfoil")
        if file_airfoil is None:
            continue
        upper = _point_values(file_airfoil.findtext("UpperPnts"))
        lower = _point_values(file_airfoil.findtext("LowerPnts"))
        perimeter_ratio = _closed_profile_perimeter_ratio(upper, lower)
        sections[index] = {
            "source_section_index": index,
            "upper_point_count": len(upper),
            "lower_point_count": len(lower),
            "normalized_profile_perimeter": perimeter_ratio,
        }
    if not sections:
        blockers.append("source_vsp3_airfoil_profiles_missing")
    return sections


def _station_traces(trace_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(trace_payload, dict):
        return []
    traces = trace_payload.get("station_traces", [])
    return [trace for trace in traces if isinstance(trace, dict)]


def _source_section_index(context: dict[str, Any]) -> int | None:
    nearest = context.get("nearest_rule_section", {})
    if isinstance(nearest, dict) and isinstance(nearest.get("source_section_index"), int):
        return int(nearest["source_section_index"])
    source = context.get("source_section", {})
    if isinstance(source, dict) and isinstance(source.get("source_section_index"), int):
        return int(source["source_section_index"])
    return None


def _station_chord(context: dict[str, Any]) -> float | None:
    nearest = context.get("nearest_rule_section", {})
    if isinstance(nearest, dict) and isinstance(nearest.get("chord"), (int, float)):
        return float(nearest["chord"])
    source = context.get("source_section", {})
    if isinstance(source, dict):
        for key in ("tip_chord_m", "root_chord_m"):
            value = source.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    return None


def _curve_matches(
    *,
    station_traces: list[dict[str, Any]],
    vsp3_profiles: dict[int, dict[str, Any]],
    tolerance: float,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for station_trace in station_traces:
        context = station_trace.get("openvsp_station_context", {})
        if not isinstance(context, dict):
            context = {}
        source_index = _source_section_index(context)
        chord = _station_chord(context)
        profile = vsp3_profiles.get(source_index) if source_index is not None else None
        normalized_perimeter = (
            profile.get("normalized_profile_perimeter")
            if isinstance(profile, dict)
            else None
        )
        for curve in station_trace.get("candidate_curves", []):
            if not isinstance(curve, dict) or not isinstance(curve.get("tag"), int):
                continue
            observed_length = curve.get("length")
            expected_length = (
                float(normalized_perimeter) * chord
                if isinstance(normalized_perimeter, (int, float))
                and isinstance(chord, (int, float))
                else None
            )
            relative_delta = (
                (float(observed_length) - expected_length) / expected_length
                if isinstance(observed_length, (int, float))
                and expected_length is not None
                and expected_length > 0.0
                else None
            )
            matches.append(
                {
                    "curve_tag": int(curve["tag"]),
                    "defect_station_y_m": station_trace.get("defect_station_y_m"),
                    "source_section_index": source_index,
                    "station_chord_m": chord,
                    "observed_curve_length_m": observed_length,
                    "vsp3_normalized_profile_perimeter": normalized_perimeter,
                    "expected_curve_length_m": expected_length,
                    "relative_length_delta": relative_delta,
                    "within_tolerance": (
                        relative_delta is not None and abs(relative_delta) <= tolerance
                    ),
                    "candidate_curve": curve,
                    "vsp3_profile": profile or {},
                }
            )
    return matches


def _status(
    *,
    blockers: list[str],
    matches: list[dict[str, Any]],
) -> CurveStationRebuildStatusType:
    if blockers:
        return "blocked"
    if not matches:
        return "no_candidate_curves"
    if all(match.get("within_tolerance") is True for match in matches):
        return "curve_tags_match_vsp3_section_profile_scale"
    return "curve_tags_deviate_from_vsp3_section_profile_scale"


def _match_summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    relative_deltas = [
        abs(float(match["relative_length_delta"]))
        for match in matches
        if isinstance(match.get("relative_length_delta"), (int, float))
    ]
    return {
        "curve_match_count": len(matches),
        "matched_curve_tags": sorted(
            int(match["curve_tag"]) for match in matches if isinstance(match.get("curve_tag"), int)
        ),
        "all_within_tolerance": bool(matches)
        and all(match.get("within_tolerance") is True for match in matches),
        "max_abs_relative_length_delta": max(relative_deltas) if relative_deltas else None,
    }


def _engineering_findings(
    status: CurveStationRebuildStatusType,
    matches: list[dict[str, Any]],
) -> list[str]:
    if status == "blocked":
        return ["gmsh_curve_station_rebuild_audit_blocked"]
    if status == "no_candidate_curves":
        return ["no_gmsh_curve_candidates_to_compare"]
    if status == "curve_tags_match_vsp3_section_profile_scale":
        return [
            "curve_tags_match_vsp3_section_profile_scale",
            "curve_tags_are_station_airfoil_loop_candidates",
        ]
    curve_tags = [
        str(match.get("curve_tag"))
        for match in matches
        if match.get("within_tolerance") is not True
    ]
    return [f"curve_tags_deviate_from_vsp3_profile_scale:{','.join(curve_tags)}"]


def _next_actions(status: CurveStationRebuildStatusType) -> list[str]:
    if status == "blocked":
        return ["restore_missing_curve_station_rebuild_inputs"]
    if status == "no_candidate_curves":
        return ["continue_with_source_backed_solver_budget_after_geometry_audit"]
    return [
        "build_minimal_openvsp_section_station_topology_fixture",
        "decide_station_seam_repair_before_solver_iteration_budget",
        "preserve_curve_36_50_as_real_route_blocker_evidence",
    ]


def build_main_wing_gmsh_curve_station_rebuild_audit_report(
    *,
    gmsh_defect_entity_trace_path: Path | None = None,
    source_vsp3_path: Path | None = None,
    relative_length_tolerance: float = 0.05,
) -> MainWingGmshCurveStationRebuildAuditReport:
    trace_path = (
        _default_gmsh_defect_entity_trace_path()
        if gmsh_defect_entity_trace_path is None
        else gmsh_defect_entity_trace_path
    )
    vsp3_path = _default_source_vsp3_path() if source_vsp3_path is None else source_vsp3_path
    blockers: list[str] = []
    trace_payload = _load_json(trace_path, blockers, "gmsh_defect_entity_trace")
    profiles = _vsp3_profile_sections(vsp3_path, blockers)
    matches = _curve_matches(
        station_traces=_station_traces(trace_payload),
        vsp3_profiles=profiles,
        tolerance=relative_length_tolerance,
    )
    status = _status(blockers=blockers, matches=matches)
    return MainWingGmshCurveStationRebuildAuditReport(
        curve_station_rebuild_status=status,
        gmsh_defect_entity_trace_path=str(trace_path),
        source_vsp3_path=str(vsp3_path),
        relative_length_tolerance=relative_length_tolerance,
        curve_matches=matches,
        match_summary=_match_summary(matches),
        blocking_reasons=blockers,
        engineering_findings=_engineering_findings(status, matches),
        next_actions=_next_actions(status),
        limitations=[
            "This audit compares Gmsh curve length to VSP3 airfoil-profile scale only; it does not project mesh nodes back to OpenVSP parameters.",
            "A profile-scale match supports station-loop provenance, but it is still route-risk evidence rather than a geometry repair.",
            "No SU2 solver execution or convergence assessment is performed by this report.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_markdown(report: MainWingGmshCurveStationRebuildAuditReport) -> str:
    lines = [
        "# Main Wing Gmsh Curve Station Rebuild Audit v1",
        "",
        "This report compares Gmsh candidate curve length against VSP3 section profile scale only.",
        "",
        f"- curve_station_rebuild_status: `{report.curve_station_rebuild_status}`",
        f"- gmsh_defect_entity_trace_path: `{report.gmsh_defect_entity_trace_path}`",
        f"- source_vsp3_path: `{report.source_vsp3_path}`",
        f"- relative_length_tolerance: `{report.relative_length_tolerance}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Match Summary",
        "",
    ]
    for key, value in report.match_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Curve Matches", ""])
    for match in report.curve_matches:
        lines.append(f"- `{_fmt(match)}`")
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


def write_main_wing_gmsh_curve_station_rebuild_audit_report(
    out_dir: Path,
    *,
    report: MainWingGmshCurveStationRebuildAuditReport | None = None,
    gmsh_defect_entity_trace_path: Path | None = None,
    source_vsp3_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_gmsh_curve_station_rebuild_audit_report(
            gmsh_defect_entity_trace_path=gmsh_defect_entity_trace_path,
            source_vsp3_path=source_vsp3_path,
        )
    json_path = out_dir / "main_wing_gmsh_curve_station_rebuild_audit.v1.json"
    markdown_path = out_dir / "main_wing_gmsh_curve_station_rebuild_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
