from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


NormalAuditStatusType = Literal["pass", "blocked"]


class MainWingSU2MeshNormalAuditReport(BaseModel):
    schema_version: Literal["main_wing_su2_mesh_normal_audit.v1"] = (
        "main_wing_su2_mesh_normal_audit.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_mesh"] = (
        "report_only_existing_mesh"
    )
    production_default_changed: bool = False
    mesh_path: str
    physical_group_name: Literal["main_wing"] = "main_wing"
    physical_group_dimension: int = 2
    physical_group_tag: int | None = None
    normal_audit_status: NormalAuditStatusType
    main_wing_surface_entity_count: int = 0
    surface_triangle_count: int = 0
    total_surface_area: float | None = None
    normal_orientation: Dict[str, Any] = Field(default_factory=dict)
    engineering_findings: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _default_mesh_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "reports"
        / "main_wing_real_mesh_handoff_probe"
        / "artifacts"
        / "real_mesh_probe"
        / "artifacts"
        / "mesh"
        / "mesh.msh"
    )


def _section(lines: list[str], start: str, end: str) -> list[str]:
    try:
        start_index = lines.index(start) + 1
        end_index = lines.index(end, start_index)
    except ValueError:
        return []
    return lines[start_index:end_index]


def _parse_physical_names(lines: list[str]) -> dict[tuple[int, int], str]:
    section = _section(lines, "$PhysicalNames", "$EndPhysicalNames")
    if not section:
        return {}
    count = int(section[0].strip())
    physical: dict[tuple[int, int], str] = {}
    for line in section[1 : 1 + count]:
        parts = line.split(maxsplit=2)
        if len(parts) != 3:
            continue
        dim = int(parts[0])
        tag = int(parts[1])
        physical[(dim, tag)] = parts[2].strip().strip('"')
    return physical


def _parse_main_wing_surface_entities(
    lines: list[str],
    *,
    physical_tag: int | None,
) -> set[int]:
    if physical_tag is None:
        return set()
    section = _section(lines, "$Entities", "$EndEntities")
    if not section:
        return set()
    counts = [int(value) for value in section[0].split()]
    if len(counts) != 4:
        return set()
    point_count, curve_count, surface_count, _volume_count = counts
    offset = 1 + point_count + curve_count
    surface_lines = section[offset : offset + surface_count]
    entity_tags: set[int] = set()
    for line in surface_lines:
        parts = line.split()
        if len(parts) < 8:
            continue
        tag = int(parts[0])
        physical_count = int(parts[7])
        physical_tags = [int(value) for value in parts[8 : 8 + physical_count]]
        if physical_tag in physical_tags:
            entity_tags.add(tag)
    return entity_tags


def _parse_nodes(lines: list[str]) -> dict[int, tuple[float, float, float]]:
    section = _section(lines, "$Nodes", "$EndNodes")
    if not section:
        return {}
    header = section[0].split()
    if len(header) < 2:
        return {}
    block_count = int(header[0])
    nodes: dict[int, tuple[float, float, float]] = {}
    index = 1
    for _ in range(block_count):
        block_header = section[index].split()
        index += 1
        if len(block_header) != 4:
            return nodes
        _entity_dim, _entity_tag, parametric, node_count = (
            int(block_header[0]),
            int(block_header[1]),
            int(block_header[2]),
            int(block_header[3]),
        )
        node_tags: list[int] = []
        while len(node_tags) < node_count:
            node_tags.extend(int(value) for value in section[index].split())
            index += 1
        for node_tag in node_tags:
            coords = [float(value) for value in section[index].split()]
            index += 1
            if len(coords) < 3:
                continue
            nodes[node_tag] = (coords[0], coords[1], coords[2])
            if parametric:
                # Parametric coordinates follow xyz on the same line in ASCII v4.1.
                # The first three coordinates are still the physical position.
                continue
    return nodes


def _parse_surface_triangles(
    lines: list[str],
    *,
    surface_entities: set[int],
) -> list[tuple[int, int, int]]:
    section = _section(lines, "$Elements", "$EndElements")
    if not section:
        return []
    header = section[0].split()
    if len(header) < 2:
        return []
    block_count = int(header[0])
    triangles: list[tuple[int, int, int]] = []
    index = 1
    for _ in range(block_count):
        block_header = section[index].split()
        index += 1
        if len(block_header) != 4:
            return triangles
        entity_dim = int(block_header[0])
        entity_tag = int(block_header[1])
        element_type = int(block_header[2])
        element_count = int(block_header[3])
        collect = entity_dim == 2 and entity_tag in surface_entities and element_type == 2
        for _element_index in range(element_count):
            parts = section[index].split()
            index += 1
            if collect and len(parts) >= 4:
                triangles.append((int(parts[1]), int(parts[2]), int(parts[3])))
    return triangles


def _subtract(
    lhs: tuple[float, float, float],
    rhs: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (lhs[0] - rhs[0], lhs[1] - rhs[1], lhs[2] - rhs[2])


def _cross(
    lhs: tuple[float, float, float],
    rhs: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        lhs[1] * rhs[2] - lhs[2] * rhs[1],
        lhs[2] * rhs[0] - lhs[0] * rhs[2],
        lhs[0] * rhs[1] - lhs[1] * rhs[0],
    )


def _normal_orientation(
    *,
    nodes: dict[int, tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
) -> tuple[dict[str, Any], list[str]]:
    normals: list[tuple[tuple[float, float, float], float]] = []
    missing_node_triangles = 0
    for n1, n2, n3 in triangles:
        try:
            p1 = nodes[n1]
            p2 = nodes[n2]
            p3 = nodes[n3]
        except KeyError:
            missing_node_triangles += 1
            continue
        cross = _cross(_subtract(p2, p1), _subtract(p3, p1))
        magnitude = math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)
        if magnitude <= 0.0:
            continue
        area = 0.5 * magnitude
        normals.append(((cross[0] / magnitude, cross[1] / magnitude, cross[2] / magnitude), area))

    if not normals:
        return {
            "status": "blocked",
            "valid_triangle_count": 0,
            "missing_node_triangle_count": missing_node_triangles,
        }, ["surface_normals_unavailable"]

    total_area = sum(area for _normal, area in normals)
    total_count = len(normals)
    z_positive = sum(1 for normal, _area in normals if normal[2] > 1.0e-12)
    z_negative = sum(1 for normal, _area in normals if normal[2] < -1.0e-12)
    z_near_zero = total_count - z_positive - z_negative
    x_values = [normal[0] for normal, _area in normals]
    y_values = [normal[1] for normal, _area in normals]
    z_values = [normal[2] for normal, _area in normals]
    mean = [
        sum(normal[axis] * area for normal, area in normals) / total_area
        for axis in range(3)
    ]
    abs_z_mean = sum(abs(normal[2]) * area for normal, area in normals) / total_area
    return {
        "status": "pass",
        "valid_triangle_count": total_count,
        "missing_node_triangle_count": missing_node_triangles,
        "z_positive_fraction": z_positive / total_count,
        "z_negative_fraction": z_negative / total_count,
        "z_near_zero_fraction": z_near_zero / total_count,
        "area_weighted_mean_normal": mean,
        "area_weighted_abs_z_mean": abs_z_mean,
        "min_normal": [min(x_values), min(y_values), min(z_values)],
        "max_normal": [max(x_values), max(y_values), max(z_values)],
        "total_surface_area": total_area,
    }, []


def _engineering_findings(normal_orientation: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    z_positive_fraction = float(normal_orientation.get("z_positive_fraction", 0.0))
    z_negative_fraction = float(normal_orientation.get("z_negative_fraction", 0.0))
    mean = normal_orientation.get("area_weighted_mean_normal", [0.0, 0.0, 0.0])
    abs_z_mean = float(normal_orientation.get("area_weighted_abs_z_mean", 0.0))
    if z_positive_fraction > 0.2 and z_negative_fraction > 0.2:
        findings.append("main_wing_surface_normals_mixed_upper_lower")
    if (
        "main_wing_surface_normals_mixed_upper_lower" in findings
        and isinstance(mean, list)
        and len(mean) == 3
        and abs(float(mean[2])) < 0.1
    ):
        findings.append("single_global_normal_flip_not_supported")
    if abs_z_mean > 0.5:
        findings.append("main_wing_normals_mostly_lift_axis_oriented")
    return findings


def _next_actions(findings: list[str]) -> list[str]:
    actions: list[str] = []
    if "single_global_normal_flip_not_supported" in findings:
        actions.append(
            "compare_openvsp_panel_wake_model_against_su2_thin_sheet_wall_semantics"
        )
        actions.append("inspect_wing_surface_pairing_and_lifting_surface_export")
    if "main_wing_normals_mostly_lift_axis_oriented" in findings:
        actions.append("check_upper_lower_surface_incidence_against_panel_geometry")
    if not actions:
        actions.append("rerun_normal_audit_after_main_wing_mesh_handoff_exists")
    return list(dict.fromkeys(actions))


def build_main_wing_su2_mesh_normal_audit_report(
    *,
    mesh_path: Path | None = None,
) -> MainWingSU2MeshNormalAuditReport:
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
    normal_orientation, blocking_reasons = _normal_orientation(
        nodes=nodes,
        triangles=triangles,
    )
    if physical_tag is None:
        blocking_reasons.append("main_wing_physical_group_missing")
    if not surface_entities:
        blocking_reasons.append("main_wing_surface_entities_missing")
    if not triangles:
        blocking_reasons.append("main_wing_surface_triangles_missing")
    findings = _engineering_findings(normal_orientation)
    status: NormalAuditStatusType = "blocked" if blocking_reasons else "pass"
    return MainWingSU2MeshNormalAuditReport(
        mesh_path=str(path),
        physical_group_tag=physical_tag,
        normal_audit_status=status,
        main_wing_surface_entity_count=len(surface_entities),
        surface_triangle_count=len(triangles),
        total_surface_area=normal_orientation.get("total_surface_area"),
        normal_orientation=normal_orientation,
        engineering_findings=findings,
        blocking_reasons=list(dict.fromkeys(blocking_reasons)),
        next_actions=_next_actions(findings),
        limitations=[
            "This audit reads the existing Gmsh mesh only; it does not repair normals.",
            "Mixed upper/lower normals are expected for a closed or paired thin wing surface.",
            "Normal orientation alone cannot prove SU2 and VSPAERO lifting semantics match.",
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


def _render_markdown(report: MainWingSU2MeshNormalAuditReport) -> str:
    lines = [
        "# Main Wing SU2 Mesh Normal Audit v1",
        "",
        "This report reads the existing Gmsh mesh only; it does not execute SU2.",
        "",
        f"- normal_audit_status: `{report.normal_audit_status}`",
        f"- mesh_path: `{report.mesh_path}`",
        f"- physical_group_tag: `{_fmt(report.physical_group_tag)}`",
        f"- main_wing_surface_entity_count: `{report.main_wing_surface_entity_count}`",
        f"- surface_triangle_count: `{report.surface_triangle_count}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Normal Orientation",
        "",
    ]
    for key, value in report.normal_orientation.items():
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


def write_main_wing_su2_mesh_normal_audit_report(
    out_dir: Path,
    *,
    report: MainWingSU2MeshNormalAuditReport | None = None,
    mesh_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_su2_mesh_normal_audit_report(mesh_path=mesh_path)
    json_path = out_dir / "main_wing_su2_mesh_normal_audit.v1.json"
    markdown_path = out_dir / "main_wing_su2_mesh_normal_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
