from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


TopologyFixtureStatusType = Literal[
    "real_defect_station_fixture_materialized",
    "no_real_defect_station_edges",
    "blocked",
]


class MainWingOpenVspSectionStationTopologyFixtureReport(BaseModel):
    schema_version: Literal[
        "main_wing_openvsp_section_station_topology_fixture.v1"
    ] = "main_wing_openvsp_section_station_topology_fixture.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["fixture_from_existing_real_defect_station_reports"] = (
        "fixture_from_existing_real_defect_station_reports"
    )
    production_default_changed: bool = False
    topology_fixture_status: TopologyFixtureStatusType
    gmsh_defect_entity_trace_path: str
    gmsh_curve_station_rebuild_audit_path: str
    fixture_summary: Dict[str, Any] = Field(default_factory=dict)
    station_fixture_cases: List[Dict[str, Any]] = Field(default_factory=list)
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


def _default_gmsh_curve_station_rebuild_audit_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_gmsh_curve_station_rebuild_audit"
        / "main_wing_gmsh_curve_station_rebuild_audit.v1.json"
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


def _station_key(value: Any) -> str | None:
    station_y = _as_float(value)
    if station_y is None:
        return None
    return f"{station_y:.9f}"


def _station_y_from_context(context: dict[str, Any]) -> float | None:
    value = _as_float(context.get("defect_station_y_m"))
    if value is not None:
        return value
    nearest = context.get("nearest_rule_section", {})
    if isinstance(nearest, dict):
        return _as_float(nearest.get("section_y_m"))
    return None


def _edge_station_y(edge_trace: dict[str, Any]) -> float | None:
    context = edge_trace.get("openvsp_station_context", {})
    if isinstance(context, dict):
        station_y = _station_y_from_context(context)
        if station_y is not None:
            return station_y
    midpoint = edge_trace.get("midpoint_xyz")
    if isinstance(midpoint, list) and len(midpoint) >= 2:
        return _as_float(midpoint[1])
    return None


def _station_traces(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [
        trace
        for trace in payload.get("station_traces", [])
        if isinstance(trace, dict)
    ]


def _edge_traces(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [
        trace
        for trace in payload.get("edge_traces", [])
        if isinstance(trace, dict)
    ]


def _curve_matches(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [
        match
        for match in payload.get("curve_matches", [])
        if isinstance(match, dict)
    ]


def _curve_matches_by_station(
    matches: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        key = _station_key(match.get("defect_station_y_m"))
        if key is None:
            continue
        grouped.setdefault(key, []).append(match)
    return grouped


def _edge_traces_by_station(
    traces: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trace in traces:
        key = _station_key(_edge_station_y(trace))
        if key is None:
            continue
        grouped.setdefault(key, []).append(trace)
    return grouped


def _source_section_index(
    station_trace: dict[str, Any],
    station_matches: list[dict[str, Any]],
) -> int | None:
    for match in station_matches:
        value = match.get("source_section_index")
        if isinstance(value, int):
            return value
    context = station_trace.get("openvsp_station_context", {})
    nearest = context.get("nearest_rule_section", {}) if isinstance(context, dict) else {}
    value = nearest.get("source_section_index") if isinstance(nearest, dict) else None
    return int(value) if isinstance(value, int) else None


def _station_chord(
    station_trace: dict[str, Any],
    station_matches: list[dict[str, Any]],
) -> float | None:
    for match in station_matches:
        chord = _as_float(match.get("station_chord_m"))
        if chord is not None:
            return chord
    context = station_trace.get("openvsp_station_context", {})
    nearest = context.get("nearest_rule_section", {}) if isinstance(context, dict) else {}
    return _as_float(nearest.get("chord")) if isinstance(nearest, dict) else None


def _candidate_curve_tags(
    station_trace: dict[str, Any],
    station_matches: list[dict[str, Any]],
) -> list[int]:
    tags: set[int] = set()
    for value in station_trace.get("candidate_curve_tags", []):
        if isinstance(value, int):
            tags.add(value)
    for curve in station_trace.get("candidate_curves", []):
        if isinstance(curve, dict) and isinstance(curve.get("tag"), int):
            tags.add(int(curve["tag"]))
    for match in station_matches:
        if isinstance(match.get("curve_tag"), int):
            tags.add(int(match["curve_tag"]))
    return sorted(tags)


def _owner_surface_tags(
    station_trace: dict[str, Any],
    station_matches: list[dict[str, Any]],
    station_edge_traces: list[dict[str, Any]],
) -> list[int]:
    tags: set[int] = set()
    for curve in station_trace.get("candidate_curves", []):
        if isinstance(curve, dict):
            tags.update(
                int(tag)
                for tag in curve.get("owner_surface_tags", [])
                if isinstance(tag, int)
            )
    for match in station_matches:
        curve = match.get("candidate_curve", {})
        if isinstance(curve, dict):
            tags.update(
                int(tag)
                for tag in curve.get("owner_surface_tags", [])
                if isinstance(tag, int)
            )
    for trace in station_edge_traces:
        tags.update(
            int(tag)
            for tag in trace.get("unique_adjacent_entity_tags", [])
            if isinstance(tag, int)
        )
    return sorted(tags)


def _compact_edge_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": _normalized_edge_kind(trace.get("kind")),
        "source_kind": trace.get("kind"),
        "nodes": trace.get("nodes", []),
        "mesh_reported_use_count": trace.get("mesh_reported_use_count"),
        "adjacent_surface_triangle_count": trace.get(
            "adjacent_surface_triangle_count"
        ),
        "unique_adjacent_entity_tags": trace.get("unique_adjacent_entity_tags", []),
    }


def _normalized_edge_kind(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value in {"boundary", "boundary_edge"}:
        return "boundary"
    if value in {"nonmanifold", "nonmanifold_edge"}:
        return "nonmanifold"
    return value


def _observed_defect_signature(
    station_edge_traces: list[dict[str, Any]],
) -> dict[str, Any]:
    kind_counts = Counter(
        kind
        for trace in station_edge_traces
        for kind in (_normalized_edge_kind(trace.get("kind")),)
        if kind is not None
    )
    use_counts = [
        int(value)
        for trace in station_edge_traces
        for value in (trace.get("mesh_reported_use_count"),)
        if isinstance(value, int)
    ]
    surface_tags = sorted(
        {
            int(tag)
            for trace in station_edge_traces
            for tag in trace.get("unique_adjacent_entity_tags", [])
            if isinstance(tag, int)
        }
    )
    return {
        "edge_count": len(station_edge_traces),
        "edge_kind_counts": dict(sorted(kind_counts.items())),
        "max_reported_use_count": max(use_counts) if use_counts else None,
        "unique_adjacent_surface_entity_tags": surface_tags,
        "compact_edges": [
            _compact_edge_trace(trace) for trace in station_edge_traces
        ],
    }


def _canonical_station_topology_contract(signature: dict[str, Any]) -> dict[str, Any]:
    kind_counts = signature.get("edge_kind_counts", {})
    boundary_count = int(kind_counts.get("boundary", 0)) if isinstance(kind_counts, dict) else 0
    nonmanifold_count = (
        int(kind_counts.get("nonmanifold", 0)) if isinstance(kind_counts, dict) else 0
    )
    return {
        "contract_name": "station_airfoil_loop_edges_are_internal_to_surface_ownership",
        "expected_boundary_edge_count": 0,
        "expected_nonmanifold_edge_count": 0,
        "expected_max_edge_use_count": 2,
        "current_boundary_edge_count": boundary_count,
        "current_nonmanifold_edge_count": nonmanifold_count,
        "current_signature_violates_contract": (
            boundary_count > 0 or nonmanifold_count > 0
        ),
    }


def _station_fixture_cases(
    *,
    station_traces: list[dict[str, Any]],
    edge_traces_by_station: dict[str, list[dict[str, Any]]],
    curve_matches_by_station: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for station_trace in station_traces:
        station_y = _as_float(station_trace.get("defect_station_y_m"))
        key = _station_key(station_y)
        if key is None:
            continue
        station_edge_traces = edge_traces_by_station.get(key, [])
        if not station_edge_traces:
            continue
        station_matches = curve_matches_by_station.get(key, [])
        signature = _observed_defect_signature(station_edge_traces)
        cases.append(
            {
                "fixture_role": "localized_openvsp_section_station_topology",
                "defect_station_y_m": station_y,
                "source_section_index": _source_section_index(
                    station_trace,
                    station_matches,
                ),
                "station_chord_m": _station_chord(station_trace, station_matches),
                "candidate_curve_tags": _candidate_curve_tags(
                    station_trace,
                    station_matches,
                ),
                "owner_surface_entity_tags": _owner_surface_tags(
                    station_trace,
                    station_matches,
                    station_edge_traces,
                ),
                "curve_match_evidence": station_matches,
                "observed_defect_signature": signature,
                "canonical_station_topology_contract": (
                    _canonical_station_topology_contract(signature)
                ),
            }
        )
    return cases


def _fixture_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    boundary_count = 0
    nonmanifold_count = 0
    curve_tags: set[int] = set()
    surface_tags: set[int] = set()
    source_sections: set[int] = set()
    for case in cases:
        signature = case.get("observed_defect_signature", {})
        kind_counts = signature.get("edge_kind_counts", {}) if isinstance(signature, dict) else {}
        if isinstance(kind_counts, dict):
            boundary_count += int(kind_counts.get("boundary", 0))
            nonmanifold_count += int(kind_counts.get("nonmanifold", 0))
        curve_tags.update(
            int(tag)
            for tag in case.get("candidate_curve_tags", [])
            if isinstance(tag, int)
        )
        surface_tags.update(
            int(tag)
            for tag in case.get("owner_surface_entity_tags", [])
            if isinstance(tag, int)
        )
        if isinstance(case.get("source_section_index"), int):
            source_sections.add(int(case["source_section_index"]))
    return {
        "station_fixture_count": len(cases),
        "total_boundary_edge_count": boundary_count,
        "total_nonmanifold_edge_count": nonmanifold_count,
        "candidate_curve_tags": sorted(curve_tags),
        "owner_surface_entity_tags": sorted(surface_tags),
        "source_section_indices": sorted(source_sections),
        "all_cases_violate_canonical_station_topology_contract": bool(cases)
        and all(
            case.get("canonical_station_topology_contract", {}).get(
                "current_signature_violates_contract"
            )
            is True
            for case in cases
        ),
    }


def _status(
    blockers: list[str],
    cases: list[dict[str, Any]],
) -> TopologyFixtureStatusType:
    if blockers:
        return "blocked"
    if not cases:
        return "no_real_defect_station_edges"
    return "real_defect_station_fixture_materialized"


def _engineering_findings(
    status: TopologyFixtureStatusType,
    summary: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["openvsp_section_station_topology_fixture_blocked"]
    if status == "no_real_defect_station_edges":
        return ["no_real_station_defect_edges_available_for_fixture"]
    findings = ["real_defect_station_topology_fixture_materialized"]
    if summary.get("total_boundary_edge_count", 0) > 0:
        findings.append("station_fixture_contains_boundary_edges")
    if summary.get("total_nonmanifold_edge_count", 0) > 0:
        findings.append("station_fixture_contains_nonmanifold_edges")
    if summary.get("all_cases_violate_canonical_station_topology_contract"):
        findings.append("station_fixture_violates_canonical_topology_contract")
    return findings


def _next_actions(status: TopologyFixtureStatusType) -> list[str]:
    if status == "blocked":
        return ["restore_missing_openvsp_section_station_fixture_inputs"]
    if status == "no_real_defect_station_edges":
        return ["continue_with_source_backed_solver_budget_after_geometry_audit"]
    return [
        "decide_station_seam_repair_before_solver_iteration_budget",
        "prototype_station_seam_repair_against_minimal_fixture",
        "rerun_main_wing_gmsh_defect_entity_trace_after_repair_candidate",
    ]


def build_main_wing_openvsp_section_station_topology_fixture_report(
    *,
    gmsh_defect_entity_trace_path: Path | None = None,
    gmsh_curve_station_rebuild_audit_path: Path | None = None,
) -> MainWingOpenVspSectionStationTopologyFixtureReport:
    trace_path = (
        _default_gmsh_defect_entity_trace_path()
        if gmsh_defect_entity_trace_path is None
        else gmsh_defect_entity_trace_path
    )
    curve_path = (
        _default_gmsh_curve_station_rebuild_audit_path()
        if gmsh_curve_station_rebuild_audit_path is None
        else gmsh_curve_station_rebuild_audit_path
    )
    blockers: list[str] = []
    trace_payload = _load_json(trace_path, blockers, "gmsh_defect_entity_trace")
    curve_payload = _load_json(curve_path, blockers, "gmsh_curve_station_rebuild_audit")
    cases = _station_fixture_cases(
        station_traces=_station_traces(trace_payload),
        edge_traces_by_station=_edge_traces_by_station(_edge_traces(trace_payload)),
        curve_matches_by_station=_curve_matches_by_station(
            _curve_matches(curve_payload)
        ),
    )
    summary = _fixture_summary(cases)
    status = _status(blockers, cases)
    return MainWingOpenVspSectionStationTopologyFixtureReport(
        topology_fixture_status=status,
        gmsh_defect_entity_trace_path=str(trace_path),
        gmsh_curve_station_rebuild_audit_path=str(curve_path),
        fixture_summary=summary,
        station_fixture_cases=cases,
        blocking_reasons=blockers,
        engineering_findings=_engineering_findings(status, summary),
        next_actions=_next_actions(status),
        limitations=[
            "This is a minimal topology fixture derived from existing real-route reports; it does not run OpenVSP, Gmsh, or SU2.",
            "The fixture captures station-edge ownership defects and canonical topology expectations, not a production repair.",
            "No solver convergence or CL acceptance is inferred from this report.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingOpenVspSectionStationTopologyFixtureReport,
) -> str:
    lines = [
        "# Main Wing OpenVSP Section Station Topology Fixture v1",
        "",
        "This fixture records localized station-edge topology defects from real route reports.",
        "",
        f"- topology_fixture_status: `{report.topology_fixture_status}`",
        f"- gmsh_defect_entity_trace_path: `{report.gmsh_defect_entity_trace_path}`",
        f"- gmsh_curve_station_rebuild_audit_path: `{report.gmsh_curve_station_rebuild_audit_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Fixture Summary",
        "",
    ]
    for key, value in report.fixture_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Station Fixture Cases", ""])
    for case in report.station_fixture_cases:
        lines.append(f"- `{_fmt(case)}`")
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


def write_main_wing_openvsp_section_station_topology_fixture_report(
    out_dir: Path,
    *,
    report: MainWingOpenVspSectionStationTopologyFixtureReport | None = None,
    gmsh_defect_entity_trace_path: Path | None = None,
    gmsh_curve_station_rebuild_audit_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_openvsp_section_station_topology_fixture_report(
            gmsh_defect_entity_trace_path=gmsh_defect_entity_trace_path,
            gmsh_curve_station_rebuild_audit_path=(
                gmsh_curve_station_rebuild_audit_path
            ),
        )
    json_path = out_dir / "main_wing_openvsp_section_station_topology_fixture.v1.json"
    markdown_path = out_dir / "main_wing_openvsp_section_station_topology_fixture.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
