from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .main_wing_su2_mesh_normal_audit import (
    _default_mesh_path,
    _parse_main_wing_surface_entities,
    _parse_nodes,
    _parse_physical_names,
    _parse_surface_triangles,
)


LocalizationStatusType = Literal["defects_localized", "no_defects", "blocked"]


class MainWingSU2TopologyDefectLocalizationReport(BaseModel):
    schema_version: Literal["main_wing_su2_topology_defect_localization.v1"] = (
        "main_wing_su2_topology_defect_localization.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_mesh"] = (
        "report_only_existing_mesh"
    )
    production_default_changed: bool = False
    localization_status: LocalizationStatusType
    mesh_path: str
    physical_group_name: Literal["main_wing"] = "main_wing"
    physical_group_tag: int | None = None
    defect_summary: Dict[str, Any] = Field(default_factory=dict)
    defect_edges: List[Dict[str, Any]] = Field(default_factory=list)
    station_summary: List[Dict[str, Any]] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    engineering_findings: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _edge_counts(triangles: list[tuple[int, int, int]]) -> Counter[tuple[int, int]]:
    edges: Counter[tuple[int, int]] = Counter()
    for n1, n2, n3 in triangles:
        for first, second in ((n1, n2), (n2, n3), (n3, n1)):
            edges[tuple(sorted((first, second)))] += 1
    return edges


def _bbox(
    nodes: dict[int, tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
) -> dict[str, float] | None:
    used_nodes = {node for triangle in triangles for node in triangle}
    coords = [nodes[node] for node in used_nodes if node in nodes]
    if not coords:
        return None
    xs = [coord[0] for coord in coords]
    ys = [coord[1] for coord in coords]
    zs = [coord[2] for coord in coords]
    return {
        "x_min": min(xs),
        "x_max": max(xs),
        "y_min": min(ys),
        "y_max": max(ys),
        "z_min": min(zs),
        "z_max": max(zs),
    }


def _station_label(semispan_fraction: float | None) -> str:
    if semispan_fraction is None:
        return "unknown"
    if semispan_fraction < 0.25:
        return "root_region"
    if semispan_fraction < 0.75:
        return "midspan_region"
    return "outer_panel_region"


def _defect_edges(
    *,
    nodes: dict[int, tuple[float, float, float]],
    edge_counts: Counter[tuple[int, int]],
    bbox: dict[str, float] | None,
) -> list[dict[str, Any]]:
    max_abs_y = None
    if bbox is not None:
        max_abs_y = max(abs(bbox["y_min"]), abs(bbox["y_max"]))
    defects: list[dict[str, Any]] = []
    for edge, count in edge_counts.items():
        kind = "boundary_edge" if count == 1 else "nonmanifold_edge" if count > 2 else None
        if kind is None:
            continue
        if edge[0] not in nodes or edge[1] not in nodes:
            continue
        p1 = nodes[edge[0]]
        p2 = nodes[edge[1]]
        midpoint = [(p1[index] + p2[index]) / 2.0 for index in range(3)]
        semispan_fraction = (
            abs(midpoint[1]) / max_abs_y
            if max_abs_y is not None and max_abs_y > 0.0
            else None
        )
        defects.append(
            {
                "kind": kind,
                "nodes": list(edge),
                "use_count": count,
                "node_coordinates": [
                    {"node": edge[0], "xyz": [p1[0], p1[1], p1[2]]},
                    {"node": edge[1], "xyz": [p2[0], p2[1], p2[2]]},
                ],
                "midpoint_xyz": midpoint,
                "semispan_fraction": semispan_fraction,
                "span_station_label": _station_label(semispan_fraction),
            }
        )
    return defects


def _station_summary(defects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for defect in defects:
        midpoint = defect.get("midpoint_xyz", [None, None, None])
        y_value = midpoint[1] if isinstance(midpoint, list) and len(midpoint) >= 2 else None
        if isinstance(y_value, (int, float)):
            grouped[round(float(y_value), 6)].append(defect)
    summary: list[dict[str, Any]] = []
    for station_y in sorted(grouped):
        station_defects = grouped[station_y]
        kinds = Counter(str(defect.get("kind")) for defect in station_defects)
        semispan_values = [
            defect.get("semispan_fraction")
            for defect in station_defects
            if isinstance(defect.get("semispan_fraction"), (int, float))
        ]
        summary.append(
            {
                "station_y_m": station_y,
                "defect_count": len(station_defects),
                "defect_kind_counts": dict(kinds),
                "semispan_fraction": (
                    sum(float(value) for value in semispan_values)
                    / len(semispan_values)
                    if semispan_values
                    else None
                ),
                "span_station_label": (
                    station_defects[0].get("span_station_label")
                    if station_defects
                    else "unknown"
                ),
            }
        )
    return summary


def _engineering_findings(defects: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    if not defects:
        return ["no_boundary_or_nonmanifold_edges_observed"]
    kind_counts = Counter(str(defect.get("kind")) for defect in defects)
    if kind_counts.get("boundary_edge", 0) > 0:
        findings.append("boundary_edges_localized")
    if kind_counts.get("nonmanifold_edge", 0) > 0:
        findings.append("nonmanifold_edges_localized")
    station_count = len(_station_summary(defects))
    if station_count <= 3:
        findings.append("topology_defects_clustered_at_few_span_stations")
    return findings


def _next_actions(defects: list[dict[str, Any]]) -> list[str]:
    if not defects:
        return ["continue_with_source_backed_solver_budget_after_geometry_audit"]
    return [
        "inspect_openvsp_export_topology_at_localized_defect_span_stations",
        "trace_defect_edges_to_gmsh_entities_before_backend_changes",
        "decide_if_local_topology_repair_or_closed_thickness_export_is_required",
    ]


def build_main_wing_su2_topology_defect_localization_report(
    *,
    mesh_path: Path | None = None,
) -> MainWingSU2TopologyDefectLocalizationReport:
    path = _default_mesh_path() if mesh_path is None else mesh_path
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    physical = _parse_physical_names(lines)
    physical_tag = next(
        (tag for (dim, tag), name in physical.items() if dim == 2 and name == "main_wing"),
        None,
    )
    surface_entities = _parse_main_wing_surface_entities(
        lines,
        physical_tag=physical_tag,
    )
    nodes = _parse_nodes(lines)
    triangles = _parse_surface_triangles(lines, surface_entities=surface_entities)
    blockers: list[str] = []
    if physical_tag is None:
        blockers.append("main_wing_physical_group_missing")
    if not triangles:
        blockers.append("main_wing_surface_triangles_missing")
    edge_counts = _edge_counts(triangles)
    bbox = _bbox(nodes, triangles)
    defects = _defect_edges(nodes=nodes, edge_counts=edge_counts, bbox=bbox)
    boundary_count = sum(1 for defect in defects if defect["kind"] == "boundary_edge")
    nonmanifold_count = sum(
        1 for defect in defects if defect["kind"] == "nonmanifold_edge"
    )
    status: LocalizationStatusType = (
        "blocked"
        if blockers
        else "defects_localized"
        if defects
        else "no_defects"
    )
    return MainWingSU2TopologyDefectLocalizationReport(
        localization_status=status,
        mesh_path=str(path),
        physical_group_tag=physical_tag,
        defect_summary={
            "surface_triangle_count": len(triangles),
            "unique_edge_count": len(edge_counts),
            "boundary_edge_count": boundary_count,
            "nonmanifold_edge_count": nonmanifold_count,
            "defect_edge_count": len(defects),
            "station_count": len(_station_summary(defects)),
        },
        defect_edges=defects,
        station_summary=_station_summary(defects),
        blocking_reasons=blockers,
        engineering_findings=_engineering_findings(defects),
        next_actions=_next_actions(defects),
        limitations=[
            "This report localizes topology defects only; it does not repair the mesh.",
            "Node IDs are mesh-local and must be traced through Gmsh/OpenVSP artifacts before code changes.",
            "Localized defects are route-risk evidence, not proof of SU2 convergence behavior.",
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


def _render_markdown(
    report: MainWingSU2TopologyDefectLocalizationReport,
) -> str:
    lines = [
        "# Main Wing SU2 Topology Defect Localization v1",
        "",
        "This report reads the existing Gmsh mesh only; it does not repair topology.",
        "",
        f"- localization_status: `{report.localization_status}`",
        f"- mesh_path: `{report.mesh_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Defect Summary",
        "",
    ]
    for key, value in report.defect_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Station Summary", ""])
    for station in report.station_summary:
        lines.append(f"- `{_fmt(station)}`")
    lines.extend(["", "## Defect Edges", ""])
    for defect in report.defect_edges:
        lines.append(f"- `{_fmt(defect)}`")
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


def write_main_wing_su2_topology_defect_localization_report(
    out_dir: Path,
    *,
    report: MainWingSU2TopologyDefectLocalizationReport | None = None,
    mesh_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_su2_topology_defect_localization_report(
            mesh_path=mesh_path,
        )
    json_path = out_dir / "main_wing_su2_topology_defect_localization.v1.json"
    markdown_path = out_dir / "main_wing_su2_topology_defect_localization.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
