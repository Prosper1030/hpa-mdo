from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .main_wing_su2_mesh_normal_audit import (
    _default_mesh_path,
    _normal_orientation,
    _parse_main_wing_surface_entities,
    _parse_nodes,
    _parse_physical_names,
    _parse_surface_triangles,
)


AuditStatusType = Literal[
    "closed_surface_manifold",
    "closed_surface_with_local_topology_defects",
    "thin_surface_like_closed_topology",
    "thin_surface_like_with_local_topology_defects",
    "open_or_lifting_surface_like",
    "blocked",
]


class MainWingSU2SurfaceTopologyAuditReport(BaseModel):
    schema_version: Literal["main_wing_su2_surface_topology_audit.v1"] = (
        "main_wing_su2_surface_topology_audit.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_mesh"] = (
        "report_only_existing_mesh"
    )
    production_default_changed: bool = False
    audit_status: AuditStatusType
    mesh_path: str
    physical_group_name: Literal["main_wing"] = "main_wing"
    physical_group_tag: int | None = None
    reference_area_m2: float | None = None
    edge_topology_observed: Dict[str, Any] = Field(default_factory=dict)
    area_evidence_observed: Dict[str, Any] = Field(default_factory=dict)
    bbox_observed: Dict[str, Any] = Field(default_factory=dict)
    engineering_findings: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _default_report_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "reports"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _default_reference_area(report_root: Path) -> float | None:
    panel = _load_json(
        report_root
        / "main_wing_vspaero_panel_reference_probe"
        / "main_wing_vspaero_panel_reference_probe.v1.json"
    )
    setup = panel.get("setup_reference", {}) if isinstance(panel, dict) else {}
    if isinstance(setup, dict):
        area = _as_float(setup.get("Sref"))
        if area is not None:
            return area
    lift = _load_json(
        report_root
        / "main_wing_lift_acceptance_diagnostic"
        / "main_wing_lift_acceptance_diagnostic.v1.json"
    )
    reference = lift.get("reference_observed", {}) if isinstance(lift, dict) else {}
    if isinstance(reference, dict):
        return _as_float(reference.get("ref_area_m2"))
    return None


def _edge_topology(triangles: list[tuple[int, int, int]]) -> dict[str, Any]:
    edges: Counter[tuple[int, int]] = Counter()
    for n1, n2, n3 in triangles:
        for first, second in ((n1, n2), (n2, n3), (n3, n1)):
            edges[tuple(sorted((first, second)))] += 1
    boundary_edges = [edge for edge, count in edges.items() if count == 1]
    nonmanifold_edges = [
        {"edge": list(edge), "use_count": count}
        for edge, count in edges.items()
        if count > 2
    ]
    unique_edge_count = len(edges)
    boundary_fraction = (
        len(boundary_edges) / unique_edge_count if unique_edge_count else None
    )
    nonmanifold_fraction = (
        len(nonmanifold_edges) / unique_edge_count if unique_edge_count else None
    )
    return {
        "surface_triangle_count": len(triangles),
        "unique_edge_count": unique_edge_count,
        "boundary_edge_count": len(boundary_edges),
        "nonmanifold_edge_count": len(nonmanifold_edges),
        "boundary_edge_fraction": boundary_fraction,
        "nonmanifold_edge_fraction": nonmanifold_fraction,
        "sample_boundary_edges": [list(edge) for edge in boundary_edges[:12]],
        "sample_nonmanifold_edges": nonmanifold_edges[:12],
    }


def _bbox(
    nodes: dict[int, tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
) -> dict[str, Any]:
    used_nodes = {node for triangle in triangles for node in triangle}
    coords = [nodes[node] for node in used_nodes if node in nodes]
    if not coords:
        return {"status": "unavailable"}
    xs = [coord[0] for coord in coords]
    ys = [coord[1] for coord in coords]
    zs = [coord[2] for coord in coords]
    return {
        "status": "available",
        "x_min": min(xs),
        "x_max": max(xs),
        "y_min": min(ys),
        "y_max": max(ys),
        "z_min": min(zs),
        "z_max": max(zs),
        "x_extent": max(xs) - min(xs),
        "y_extent": max(ys) - min(ys),
        "z_extent": max(zs) - min(zs),
    }


def _area_evidence(
    *,
    normal_orientation: dict[str, Any],
    reference_area_m2: float | None,
) -> dict[str, Any]:
    surface_area = _as_float(normal_orientation.get("total_surface_area"))
    abs_z_mean = _as_float(normal_orientation.get("area_weighted_abs_z_mean"))
    projected_abs_lift_axis_area = (
        surface_area * abs_z_mean
        if surface_area is not None and abs_z_mean is not None
        else None
    )
    surface_ratio = (
        surface_area / reference_area_m2
        if surface_area is not None
        and reference_area_m2 is not None
        and reference_area_m2 > 0.0
        else None
    )
    projected_ratio = (
        projected_abs_lift_axis_area / reference_area_m2
        if projected_abs_lift_axis_area is not None
        and reference_area_m2 is not None
        and reference_area_m2 > 0.0
        else None
    )
    single_sheet_like = (
        surface_ratio is not None
        and projected_ratio is not None
        and surface_ratio <= 1.5
        and projected_ratio <= 1.25
    )
    double_sided_like = (
        surface_ratio is not None and surface_ratio >= 1.6
    ) or (projected_ratio is not None and projected_ratio >= 1.6)
    return {
        "surface_area_m2": surface_area,
        "projected_abs_lift_axis_area_m2": projected_abs_lift_axis_area,
        "reference_area_m2": reference_area_m2,
        "surface_area_to_reference_area_ratio": surface_ratio,
        "projected_abs_area_to_reference_area_ratio": projected_ratio,
        "single_sheet_area_like": single_sheet_like,
        "double_sided_closed_area_like": double_sided_like,
    }


def _audit_status(
    *,
    edge_topology: dict[str, Any],
    area_evidence: dict[str, Any],
) -> AuditStatusType:
    if not edge_topology.get("surface_triangle_count"):
        return "blocked"
    boundary_fraction = edge_topology.get("boundary_edge_fraction")
    local_defects = (
        edge_topology.get("boundary_edge_count", 0) > 0
        or edge_topology.get("nonmanifold_edge_count", 0) > 0
    )
    if isinstance(boundary_fraction, float) and boundary_fraction >= 0.05:
        return "open_or_lifting_surface_like"
    if area_evidence.get("single_sheet_area_like"):
        return (
            "thin_surface_like_with_local_topology_defects"
            if local_defects
            else "thin_surface_like_closed_topology"
        )
    return (
        "closed_surface_with_local_topology_defects"
        if local_defects
        else "closed_surface_manifold"
    )


def _engineering_findings(
    *,
    status: AuditStatusType,
    edge_topology: dict[str, Any],
    area_evidence: dict[str, Any],
) -> list[str]:
    findings: list[str] = []
    boundary_count = int(edge_topology.get("boundary_edge_count", 0))
    nonmanifold_count = int(edge_topology.get("nonmanifold_edge_count", 0))
    boundary_fraction = edge_topology.get("boundary_edge_fraction")
    if boundary_count > 0:
        findings.append("open_boundary_edges_present")
        if isinstance(boundary_fraction, float) and boundary_fraction < 0.01:
            findings.append("open_boundary_edges_localized_low_fraction")
    if nonmanifold_count > 0:
        findings.append("nonmanifold_edges_present")
    if status in {
        "thin_surface_like_closed_topology",
        "thin_surface_like_with_local_topology_defects",
        "open_or_lifting_surface_like",
    }:
        findings.append("thin_or_single_sheet_surface_area_evidence_observed")
    if area_evidence.get("double_sided_closed_area_like"):
        findings.append("closed_double_sided_surface_area_evidence_observed")
    if edge_topology.get("unique_edge_count") and isinstance(boundary_fraction, float):
        if boundary_fraction < 0.01:
            findings.append("main_wing_surface_edges_mostly_manifold")
    if status == "thin_surface_like_with_local_topology_defects":
        findings.append("thin_surface_like_area_with_local_topology_defects")
    return list(dict.fromkeys(findings))


def _next_actions(findings: list[str]) -> list[str]:
    actions: list[str] = []
    if {
        "open_boundary_edges_present",
        "nonmanifold_edges_present",
    }.intersection(findings):
        actions.append("localize_main_wing_open_boundary_and_nonmanifold_edges")
    if "thin_or_single_sheet_surface_area_evidence_observed" in findings:
        actions.append(
            "inspect_openvsp_export_surface_thickness_before_more_solver_iterations"
        )
        actions.append(
            "decide_main_wing_product_route_lifting_surface_vs_closed_thickness_cfd_geometry"
        )
    if not actions:
        actions.append("continue_with_source_backed_solver_budget_after_geometry_audit")
    return list(dict.fromkeys(actions))


def build_main_wing_su2_surface_topology_audit_report(
    *,
    mesh_path: Path | None = None,
    report_root: Path | None = None,
    reference_area_m2: float | None = None,
) -> MainWingSU2SurfaceTopologyAuditReport:
    root = _default_report_root() if report_root is None else report_root
    resolved_reference_area = (
        _default_reference_area(root)
        if reference_area_m2 is None
        else float(reference_area_m2)
    )
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
    normal_orientation, normal_blockers = _normal_orientation(
        nodes=nodes,
        triangles=triangles,
    )
    edge_topology = _edge_topology(triangles)
    area_evidence = _area_evidence(
        normal_orientation=normal_orientation,
        reference_area_m2=resolved_reference_area,
    )
    status = _audit_status(
        edge_topology=edge_topology,
        area_evidence=area_evidence,
    )
    blockers = list(normal_blockers)
    if physical_tag is None:
        blockers.append("main_wing_physical_group_missing")
    if not triangles:
        blockers.append("main_wing_surface_triangles_missing")
    findings = _engineering_findings(
        status=status,
        edge_topology=edge_topology,
        area_evidence=area_evidence,
    )
    return MainWingSU2SurfaceTopologyAuditReport(
        audit_status=status if not blockers else "blocked",
        mesh_path=str(path),
        physical_group_tag=physical_tag,
        reference_area_m2=resolved_reference_area,
        edge_topology_observed=edge_topology,
        area_evidence_observed=area_evidence,
        bbox_observed=_bbox(nodes, triangles),
        engineering_findings=findings,
        blocking_reasons=list(dict.fromkeys(blockers)),
        next_actions=_next_actions(findings),
        limitations=[
            "This audit reads the existing Gmsh mesh only; it does not repair topology.",
            "Area-ratio labels are engineering evidence, not a proof of aerodynamic equivalence.",
            "A thin/single-sheet-like surface remains route risk until OpenVSP export semantics are confirmed.",
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


def _render_markdown(report: MainWingSU2SurfaceTopologyAuditReport) -> str:
    lines = [
        "# Main Wing SU2 Surface Topology Audit v1",
        "",
        "This report reads the existing Gmsh mesh only; it does not execute SU2.",
        "",
        f"- audit_status: `{report.audit_status}`",
        f"- mesh_path: `{report.mesh_path}`",
        f"- reference_area_m2: `{_fmt(report.reference_area_m2)}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Edge Topology",
        "",
    ]
    for key, value in report.edge_topology_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Area Evidence", ""])
    for key, value in report.area_evidence_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Bounding Box", ""])
    for key, value in report.bbox_observed.items():
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


def write_main_wing_su2_surface_topology_audit_report(
    out_dir: Path,
    *,
    report: MainWingSU2SurfaceTopologyAuditReport | None = None,
    mesh_path: Path | None = None,
    report_root: Path | None = None,
    reference_area_m2: float | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_su2_surface_topology_audit_report(
            mesh_path=mesh_path,
            report_root=report_root,
            reference_area_m2=reference_area_m2,
        )
    json_path = out_dir / "main_wing_su2_surface_topology_audit.v1.json"
    markdown_path = out_dir / "main_wing_su2_surface_topology_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
