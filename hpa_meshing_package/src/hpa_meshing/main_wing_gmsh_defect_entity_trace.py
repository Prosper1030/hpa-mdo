from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .main_wing_su2_mesh_normal_audit import (
    _default_mesh_path,
    _parse_main_wing_surface_entities,
    _parse_physical_names,
    _section,
)


TraceStatusType = Literal[
    "defect_edges_traced_to_gmsh_entities",
    "defect_edges_partially_traced_to_gmsh_entities",
    "no_defect_edges",
    "blocked",
]


class MainWingGmshDefectEntityTraceReport(BaseModel):
    schema_version: Literal["main_wing_gmsh_defect_entity_trace.v1"] = (
        "main_wing_gmsh_defect_entity_trace.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_mesh_and_geometry_artifacts"] = (
        "report_only_existing_mesh_and_geometry_artifacts"
    )
    production_default_changed: bool = False
    trace_status: TraceStatusType
    mesh_path: str
    defect_localization_path: str
    openvsp_station_audit_path: str
    surface_patch_diagnostics_path: str
    trace_summary: Dict[str, Any] = Field(default_factory=dict)
    edge_traces: List[Dict[str, Any]] = Field(default_factory=list)
    station_traces: List[Dict[str, Any]] = Field(default_factory=list)
    surface_entity_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    engineering_findings: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_defect_localization_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_su2_topology_defect_localization"
        / "main_wing_su2_topology_defect_localization.v1.json"
    )


def _default_openvsp_station_audit_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_openvsp_defect_station_audit"
        / "main_wing_openvsp_defect_station_audit.v1.json"
    )


def _default_surface_patch_diagnostics_path() -> Path:
    return _default_mesh_path().parent / "surface_patch_diagnostics.json"


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


def _parse_surface_triangles_with_entities(
    lines: list[str],
    *,
    surface_entities: set[int],
) -> list[dict[str, Any]]:
    section = _section(lines, "$Elements", "$EndElements")
    if not section:
        return []
    header = section[0].split()
    if len(header) < 2:
        return []
    block_count = int(header[0])
    records: list[dict[str, Any]] = []
    index = 1
    for _ in range(block_count):
        block_header = section[index].split()
        index += 1
        if len(block_header) != 4:
            return records
        entity_dim = int(block_header[0])
        entity_tag = int(block_header[1])
        element_type = int(block_header[2])
        element_count = int(block_header[3])
        collect = entity_dim == 2 and entity_tag in surface_entities and element_type == 2
        for _element_index in range(element_count):
            parts = section[index].split()
            index += 1
            if collect and len(parts) >= 4:
                records.append(
                    {
                        "element_id": int(parts[0]),
                        "entity_tag": entity_tag,
                        "node_ids": [int(parts[1]), int(parts[2]), int(parts[3])],
                    }
                )
    return records


def _edge_adjacency(
    triangles: list[dict[str, Any]],
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    adjacency: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for triangle in triangles:
        nodes = triangle["node_ids"]
        for first, second in (
            (nodes[0], nodes[1]),
            (nodes[1], nodes[2]),
            (nodes[2], nodes[0]),
        ):
            adjacency[tuple(sorted((first, second)))].append(triangle)
    return adjacency


def _defect_edges(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    defects = payload.get("defect_edges", [])
    return [defect for defect in defects if isinstance(defect, dict)]


def _station_mappings(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    mappings = payload.get("station_mappings", [])
    return [mapping for mapping in mappings if isinstance(mapping, dict)]


def _station_y_from_defect(defect: dict[str, Any]) -> float | None:
    midpoint = defect.get("midpoint_xyz")
    if isinstance(midpoint, list) and len(midpoint) >= 2:
        y_value = midpoint[1]
        if isinstance(y_value, (int, float)):
            return float(y_value)
    return None


def _nearest_station_mapping(
    *,
    station_y: float | None,
    station_mappings: list[dict[str, Any]],
) -> dict[str, Any]:
    if station_y is None:
        return {}
    nearest: dict[str, Any] = {}
    nearest_delta: float | None = None
    for mapping in station_mappings:
        raw_y = mapping.get("defect_station_y_m")
        if not isinstance(raw_y, (int, float)):
            continue
        delta = abs(float(raw_y) - station_y)
        if nearest_delta is None or delta < nearest_delta:
            nearest = mapping
            nearest_delta = delta
    return nearest


def _edge_traces(
    *,
    defects: list[dict[str, Any]],
    adjacency: dict[tuple[int, int], list[dict[str, Any]]],
    station_mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for defect in defects:
        nodes = defect.get("nodes", [])
        if not isinstance(nodes, list) or len(nodes) != 2:
            continue
        edge = tuple(sorted((int(nodes[0]), int(nodes[1]))))
        adjacent_elements = adjacency.get(edge, [])
        station_y = _station_y_from_defect(defect)
        station_mapping = _nearest_station_mapping(
            station_y=station_y,
            station_mappings=station_mappings,
        )
        traces.append(
            {
                "kind": defect.get("kind"),
                "nodes": list(edge),
                "mesh_reported_use_count": defect.get("use_count"),
                "adjacent_surface_triangle_count": len(adjacent_elements),
                "adjacent_elements": adjacent_elements,
                "adjacent_entity_tags": [
                    int(element["entity_tag"]) for element in adjacent_elements
                ],
                "unique_adjacent_entity_tags": sorted(
                    {int(element["entity_tag"]) for element in adjacent_elements}
                ),
                "midpoint_xyz": defect.get("midpoint_xyz"),
                "openvsp_station_context": station_mapping,
            }
        )
    return traces


def _surface_records(payload: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    records: dict[int, dict[str, Any]] = {}
    for record in payload.get("surface_records", []):
        if isinstance(record, dict) and isinstance(record.get("tag"), int):
            records[int(record["tag"])] = record
    return records


def _curve_records(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [
        record
        for record in payload.get("curve_records", [])
        if isinstance(record, dict) and isinstance(record.get("tag"), int)
    ]


def _surface_entity_summaries(
    *,
    edge_traces: list[dict[str, Any]],
    surface_records: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    entity_tags = sorted(
        {
            int(tag)
            for trace in edge_traces
            for tag in trace.get("unique_adjacent_entity_tags", [])
            if isinstance(tag, int)
        }
    )
    summaries: list[dict[str, Any]] = []
    for tag in entity_tags:
        record = surface_records.get(tag, {})
        summaries.append(
            {
                "entity_tag": tag,
                "surface_patch_record": record,
                "defect_edge_count": sum(
                    1
                    for trace in edge_traces
                    if tag in trace.get("unique_adjacent_entity_tags", [])
                ),
            }
        )
    return summaries


def _station_traces(
    *,
    edge_traces: list[dict[str, Any]],
    station_mappings: list[dict[str, Any]],
    curves: list[dict[str, Any]],
    station_tolerance_m: float,
) -> list[dict[str, Any]]:
    traces_by_station: list[dict[str, Any]] = []
    for mapping in station_mappings:
        raw_y = mapping.get("defect_station_y_m")
        if not isinstance(raw_y, (int, float)):
            continue
        station_y = float(raw_y)
        station_edge_traces = [
            trace
            for trace in edge_traces
            if (
                _station_y_from_defect({"midpoint_xyz": trace.get("midpoint_xyz")})
                is not None
                and abs(
                    _station_y_from_defect({"midpoint_xyz": trace.get("midpoint_xyz")})
                    - station_y
                )
                <= station_tolerance_m
            )
        ]
        station_entities = sorted(
            {
                int(tag)
                for trace in station_edge_traces
                for tag in trace.get("unique_adjacent_entity_tags", [])
                if isinstance(tag, int)
            }
        )
        candidate_curves = []
        for curve in curves:
            owners = {
                int(tag)
                for tag in curve.get("owner_surface_tags", [])
                if isinstance(tag, int)
            }
            bbox = curve.get("bbox", {})
            y_min = bbox.get("y_min") if isinstance(bbox, dict) else None
            y_max = bbox.get("y_max") if isinstance(bbox, dict) else None
            if not isinstance(y_min, (int, float)) or not isinstance(y_max, (int, float)):
                continue
            if not (float(y_min) - station_tolerance_m <= station_y <= float(y_max) + station_tolerance_m):
                continue
            if len(owners.intersection(station_entities)) >= 2:
                candidate_curves.append(curve)
        traces_by_station.append(
            {
                "defect_station_y_m": station_y,
                "openvsp_station_context": mapping,
                "involved_surface_entity_tags": station_entities,
                "candidate_curve_tags": sorted(int(curve["tag"]) for curve in candidate_curves),
                "candidate_curves": candidate_curves,
            }
        )
    return traces_by_station


def _trace_summary(
    *,
    edge_traces: list[dict[str, Any]],
    station_traces: list[dict[str, Any]],
) -> dict[str, Any]:
    involved_entities = sorted(
        {
            int(tag)
            for trace in edge_traces
            for tag in trace.get("unique_adjacent_entity_tags", [])
            if isinstance(tag, int)
        }
    )
    edge_kind_counts = Counter(str(trace.get("kind")) for trace in edge_traces)
    return {
        "defect_edge_count": len(edge_traces),
        "edge_kind_counts": dict(edge_kind_counts),
        "traced_edge_count": sum(
            1 for trace in edge_traces if trace.get("adjacent_surface_triangle_count", 0) > 0
        ),
        "involved_surface_entity_tags": involved_entities,
        "station_count": len(station_traces),
        "candidate_curve_tags": sorted(
            {
                int(tag)
                for station in station_traces
                for tag in station.get("candidate_curve_tags", [])
                if isinstance(tag, int)
            }
        ),
    }


def _status(
    *,
    blockers: list[str],
    edge_traces: list[dict[str, Any]],
) -> TraceStatusType:
    if blockers:
        return "blocked"
    if not edge_traces:
        return "no_defect_edges"
    if all(trace.get("adjacent_surface_triangle_count", 0) > 0 for trace in edge_traces):
        return "defect_edges_traced_to_gmsh_entities"
    return "defect_edges_partially_traced_to_gmsh_entities"


def _engineering_findings(
    *,
    status: TraceStatusType,
    edge_traces: list[dict[str, Any]],
    station_traces: list[dict[str, Any]],
) -> list[str]:
    if status == "blocked":
        return ["gmsh_defect_entity_trace_blocked"]
    if status == "no_defect_edges":
        return ["no_localized_defect_edges_to_trace"]
    findings = ["defect_edges_traced_to_gmsh_surface_entities"]
    if any(trace.get("kind") == "nonmanifold_edge" for trace in edge_traces):
        findings.append("nonmanifold_edges_span_adjacent_gmsh_entities")
    if any(trace.get("kind") == "boundary_edge" for trace in edge_traces):
        findings.append("boundary_edges_have_single_adjacent_surface_triangle")
    if any(station.get("candidate_curve_tags") for station in station_traces):
        findings.append("station_curve_candidates_found")
    return findings


def _next_actions(status: TraceStatusType, station_traces: list[dict[str, Any]]) -> list[str]:
    if status == "blocked":
        return ["restore_missing_gmsh_defect_trace_inputs"]
    if status == "no_defect_edges":
        return ["continue_with_source_backed_solver_budget_after_geometry_audit"]
    curve_tags = sorted(
        {
            int(tag)
            for station in station_traces
            for tag in station.get("candidate_curve_tags", [])
            if isinstance(tag, int)
        }
    )
    if curve_tags == [36, 50]:
        first = "inspect_gmsh_curve_tags_36_50_against_openvsp_section_rebuild"
    elif curve_tags:
        joined = "_".join(str(tag) for tag in curve_tags)
        first = f"inspect_gmsh_curve_tags_{joined}_against_openvsp_section_rebuild"
    else:
        first = "inspect_gmsh_surface_entities_against_openvsp_section_rebuild"
    return [
        first,
        "build_minimal_openvsp_section_station_topology_fixture",
        "decide_station_seam_repair_before_solver_iteration_budget",
    ]


def build_main_wing_gmsh_defect_entity_trace_report(
    *,
    mesh_path: Path | None = None,
    defect_localization_path: Path | None = None,
    openvsp_station_audit_path: Path | None = None,
    surface_patch_diagnostics_path: Path | None = None,
    station_tolerance_m: float = 1.0e-5,
) -> MainWingGmshDefectEntityTraceReport:
    mesh = _default_mesh_path() if mesh_path is None else mesh_path
    defect_path = (
        _default_defect_localization_path()
        if defect_localization_path is None
        else defect_localization_path
    )
    station_path = (
        _default_openvsp_station_audit_path()
        if openvsp_station_audit_path is None
        else openvsp_station_audit_path
    )
    patch_path = (
        _default_surface_patch_diagnostics_path()
        if surface_patch_diagnostics_path is None
        else surface_patch_diagnostics_path
    )
    blockers: list[str] = []
    try:
        lines = mesh.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        blockers.append("mesh_missing")
        lines = []
    physical = _parse_physical_names(lines)
    physical_tag = next(
        (tag for (dim, tag), name in physical.items() if dim == 2 and name == "main_wing"),
        None,
    )
    if physical_tag is None and lines:
        blockers.append("main_wing_physical_group_missing")
    surface_entities = _parse_main_wing_surface_entities(
        lines,
        physical_tag=physical_tag,
    )
    if lines and not surface_entities:
        blockers.append("main_wing_surface_entities_missing")
    triangles = _parse_surface_triangles_with_entities(
        lines,
        surface_entities=surface_entities,
    )
    defect_localization = _load_json(defect_path, blockers, "defect_localization_report")
    openvsp_station_audit = _load_json(station_path, blockers, "openvsp_station_audit")
    surface_patch_diagnostics = _load_json(
        patch_path,
        blockers,
        "surface_patch_diagnostics",
    )
    defects = _defect_edges(defect_localization)
    station_mappings = _station_mappings(openvsp_station_audit)
    edge_traces = _edge_traces(
        defects=defects,
        adjacency=_edge_adjacency(triangles),
        station_mappings=station_mappings,
    )
    surface_records = _surface_records(surface_patch_diagnostics)
    station_traces = _station_traces(
        edge_traces=edge_traces,
        station_mappings=station_mappings,
        curves=_curve_records(surface_patch_diagnostics),
        station_tolerance_m=station_tolerance_m,
    )
    status = _status(blockers=blockers, edge_traces=edge_traces)
    return MainWingGmshDefectEntityTraceReport(
        trace_status=status,
        mesh_path=str(mesh),
        defect_localization_path=str(defect_path),
        openvsp_station_audit_path=str(station_path),
        surface_patch_diagnostics_path=str(patch_path),
        trace_summary=_trace_summary(
            edge_traces=edge_traces,
            station_traces=station_traces,
        ),
        edge_traces=edge_traces,
        station_traces=station_traces,
        surface_entity_summaries=_surface_entity_summaries(
            edge_traces=edge_traces,
            surface_records=surface_records,
        ),
        blocking_reasons=blockers,
        engineering_findings=_engineering_findings(
            status=status,
            edge_traces=edge_traces,
            station_traces=station_traces,
        ),
        next_actions=_next_actions(status, station_traces),
        limitations=[
            "This trace reads existing mesh and topology diagnostics only; it does not repair Gmsh or OpenVSP output.",
            "Candidate curve tags are inferred from surface_patch_diagnostics ownership and station y, not from exact curve-parametric edge projection.",
            "Gmsh entity tracing is topology provenance; it is not SU2 convergence evidence.",
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


def _render_markdown(report: MainWingGmshDefectEntityTraceReport) -> str:
    lines = [
        "# Main Wing Gmsh Defect Entity Trace v1",
        "",
        "This report reads existing mesh/topology artifacts only; it does not repair Gmsh or OpenVSP output.",
        "",
        f"- trace_status: `{report.trace_status}`",
        f"- mesh_path: `{report.mesh_path}`",
        f"- defect_localization_path: `{report.defect_localization_path}`",
        f"- openvsp_station_audit_path: `{report.openvsp_station_audit_path}`",
        f"- surface_patch_diagnostics_path: `{report.surface_patch_diagnostics_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Trace Summary",
        "",
    ]
    for key, value in report.trace_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Edge Traces", ""])
    for trace in report.edge_traces:
        lines.append(f"- `{_fmt(trace)}`")
    lines.extend(["", "## Station Traces", ""])
    for trace in report.station_traces:
        lines.append(f"- `{_fmt(trace)}`")
    lines.extend(["", "## Surface Entity Summaries", ""])
    for summary in report.surface_entity_summaries:
        lines.append(f"- `{_fmt(summary)}`")
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


def write_main_wing_gmsh_defect_entity_trace_report(
    out_dir: Path,
    *,
    report: MainWingGmshDefectEntityTraceReport | None = None,
    mesh_path: Path | None = None,
    defect_localization_path: Path | None = None,
    openvsp_station_audit_path: Path | None = None,
    surface_patch_diagnostics_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_gmsh_defect_entity_trace_report(
            mesh_path=mesh_path,
            defect_localization_path=defect_localization_path,
            openvsp_station_audit_path=openvsp_station_audit_path,
            surface_patch_diagnostics_path=surface_patch_diagnostics_path,
        )
    json_path = out_dir / "main_wing_gmsh_defect_entity_trace.v1.json"
    markdown_path = out_dir / "main_wing_gmsh_defect_entity_trace.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
