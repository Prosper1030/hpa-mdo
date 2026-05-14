#!/usr/bin/env python3
"""Probe a globally conformal center-star split basis for WO-006.

R21 showed that R17's per-cell best tet/prism choices do not assemble into a
conformal near-wall volume.  R22 tests a stricter global alternative: split each
near-wall hexa by a cell-center star, use deterministic diagonals on internal
quad faces, and use the repaired core-interface target triangles on core-facing
boundary faces.

This is topology basis evidence only.  It does not write the final mixed SU2
mesh, postprocess y+, or run CFD coefficients.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    build_wing_boundary_layer_block,
)
from probe_wo006ad_near_wall_merged_volume_candidate import (  # noqa: E402
    build_near_wall_merged_volume_candidate,
    merged_boundary_face_rows,
    volume_cell_rows,
)
from probe_wo006r11_core_facing_loop_closure import core_facing_rows  # noqa: E402
from probe_wo006r13_loop_cap_geometric_seam_repair import (  # noqa: E402
    build_loop_cap_surface,
    repair_loop_cap_geometric_seams,
)
from probe_wo006r17_hybrid_tet_prism_split import (  # noqa: E402
    audit_hybrid_tet_prism_split_compatibility,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r22_global_star_split_basis_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r22_global_star_split_basis_probe"
LOOP_CAP_MARKER = "core_wall_loop_cap"
HEX_FACE_LOCAL_NODES = (
    (0, 1, 2, 3),
    (4, 7, 6, 5),
    (0, 4, 5, 1),
    (1, 5, 6, 2),
    (2, 6, 7, 3),
    (3, 7, 4, 0),
)


def audit_global_star_split_basis(
    *,
    vertices: Sequence[tuple[float, float, float]],
    candidate_cells: Sequence[Mapping[str, Any]],
    external_boundary_rows: Sequence[Mapping[str, Any]],
    target_triangle_rows: Sequence[Mapping[str, Any]],
    digits: int = 10,
) -> dict[str, Any]:
    boundary_point_sets = [
        set(_polygon_key(vertices, _parse_nodes(row.get("nodes")), digits=digits))
        for row in external_boundary_rows
    ]
    target_groups: dict[tuple[int, tuple[int, ...]], list[Mapping[str, Any]]] = {}
    target_keys: set[tuple[tuple[float, float, float], ...]] = set()
    target_marker_by_key: dict[tuple[tuple[float, float, float], ...], str] = {}
    for row in target_triangle_rows:
        cell_index = int(row.get("cell_index", -1))
        face_key = _face_node_key(_parse_nodes(row.get("face_nodes")))
        target_groups.setdefault((cell_index, face_key), []).append(row)
        triangle_key = _polygon_key(
            vertices,
            _parse_nodes(row.get("triangle_nodes")),
            digits=digits,
        )
        target_keys.add(triangle_key)
        target_marker_by_key[triangle_key] = str(row.get("marker") or "")

    face_counts: dict[tuple[tuple[float, float, float], ...], int] = {}
    boundary_face_keys: set[tuple[tuple[float, float, float], ...]] = set()
    volume_element_count = 0
    non_positive_tet_count = 0
    degenerate_star_triangle_count = 0
    min_volume = None
    max_volume = None
    leak_samples: list[dict[str, Any]] = []

    generated_boundary_by_marker: dict[str, int] = {}
    for raw_cell_index, cell in enumerate(candidate_cells):
        cell_index = int(cell.get("cell_index", raw_cell_index))
        cell_nodes = _parse_nodes(cell.get("nodes"))
        if len(cell_nodes) != 8:
            continue
        center = _mean_point(vertices, cell_nodes)
        for local_face in HEX_FACE_LOCAL_NODES:
            face_nodes = tuple(cell_nodes[index] for index in local_face)
            face_key = _face_node_key(face_nodes)
            target_rows = target_groups.get((cell_index, face_key))
            triangles = (
                [_parse_nodes(row.get("triangle_nodes")) for row in target_rows]
                if target_rows
                else _deterministic_quad_triangulation(face_nodes)
            )
            marker = str(target_rows[0].get("marker") or "") if target_rows else ""
            for triangle in triangles:
                triangle_points = [vertices[int(node)] for node in triangle]
                if _triangle_area(*triangle_points) <= 1.0e-14:
                    degenerate_star_triangle_count += 1
                    continue
                volume = _tetra_volume(
                    center,
                    triangle_points[0],
                    triangle_points[1],
                    triangle_points[2],
                )
                min_volume = volume if min_volume is None else min(min_volume, volume)
                max_volume = volume if max_volume is None else max(max_volume, volume)
                if volume <= 1.0e-14:
                    non_positive_tet_count += 1
                volume_element_count += 1
                boundary_key = _polygon_key(vertices, triangle, digits=digits)
                boundary_face_keys.add(boundary_key)
                if marker:
                    generated_boundary_by_marker[marker] = (
                        generated_boundary_by_marker.get(marker, 0) + 1
                    )
                for tet_face_key in _star_tet_face_keys(
                    center,
                    triangle_points,
                    digits=digits,
                ):
                    face_counts[tet_face_key] = face_counts.get(tet_face_key, 0) + 1

    matched_target_keys = boundary_face_keys & target_keys
    unmatched_target_keys = target_keys - matched_target_keys
    matched_markers = _count_markers(
        target_marker_by_key[key] for key in matched_target_keys
    )
    nonmanifold_keys = {key for key, count in face_counts.items() if count > 2}
    internal_leak_count = 0
    exterior_count = 0
    external_boundary_count = 0
    for key, count in face_counts.items():
        if count != 1:
            continue
        exterior_count += 1
        is_external_boundary = any(set(key).issubset(points) for points in boundary_point_sets)
        if is_external_boundary:
            external_boundary_count += 1
            continue
        internal_leak_count += 1
        if len(leak_samples) < 25:
            leak_samples.append({"face_key": list(key)})

    ready = (
        internal_leak_count == 0
        and not nonmanifold_keys
        and not unmatched_target_keys
        and non_positive_tet_count == 0
        and degenerate_star_triangle_count == 0
    )
    if ready:
        status = "global_star_split_basis_ready"
    elif (
        degenerate_star_triangle_count
        and internal_leak_count == 0
        and not nonmanifold_keys
        and not unmatched_target_keys
        and non_positive_tet_count == 0
    ):
        status = "global_star_split_basis_degenerate_reduction_required"
    else:
        status = "global_star_split_basis_blocked"
    return {
        "schema_version": "wo006r22_global_star_split_basis.v1",
        "status": status,
        "blockers": _blockers_for_status(
            ready=ready,
            internal_leak_count=internal_leak_count,
            nonmanifold_count=len(nonmanifold_keys),
            unmatched_target_count=len(unmatched_target_keys),
            non_positive_tet_count=non_positive_tet_count,
            degenerate_star_triangle_count=degenerate_star_triangle_count,
        ),
        "candidate_cell_count": len(candidate_cells),
        "volume_element_count": volume_element_count,
        "target_triangle_count": len(target_keys),
        "matched_target_triangle_count": len(matched_target_keys),
        "unmatched_target_triangle_count": len(unmatched_target_keys),
        "matched_target_triangles_by_marker": dict(sorted(matched_markers.items())),
        "generated_target_boundary_triangles_by_marker": dict(
            sorted(generated_boundary_by_marker.items())
        ),
        "exterior_split_face_count": exterior_count,
        "external_boundary_face_count": external_boundary_count,
        "internal_split_leak_face_count": internal_leak_count,
        "nonmanifold_split_face_count": len(nonmanifold_keys),
        "non_positive_tet_count": non_positive_tet_count,
        "degenerate_star_triangle_count": degenerate_star_triangle_count,
        "min_star_tet_volume_m3": 0.0 if min_volume is None else min_volume,
        "max_star_tet_volume_m3": 0.0 if max_volume is None else max_volume,
        "internal_split_leak_samples": leak_samples,
        "engineering_read": (
            "A deterministic global center-star split can assemble the near-wall "
            "candidate without internal split leaks while matching the current "
            "candidate-owned core-interface triangles. This is a topology basis; "
            "the all-tet near-wall layer still needs mesh-quality, y+, and solver "
            "credibility checks before CFD use."
            if ready
            else "The global center-star split is conformal after ignoring "
            "zero-area star triangles, but degenerate sharp-edge cells still need "
            "cell-type reduction before writing a valid SU2 mesh."
            if status == "global_star_split_basis_degenerate_reduction_required"
            else "The global center-star split basis still fails topology or target "
            "triangle checks; do not write a mixed SU2 mesh from it."
        ),
    }


def global_star_target_triangle_rows(
    *,
    candidate_vertices: Sequence[tuple[float, float, float]],
    candidate_cells: Sequence[Mapping[str, Any]],
    candidate_boundary_faces: Sequence[Mapping[str, Any]],
    core_vertices: Sequence[tuple[float, float, float]],
    core_triangle_rows: Sequence[Mapping[str, Any]],
    digits: int = 10,
) -> list[dict[str, Any]]:
    core_entries = [
        {
            "marker": str(row.get("marker") or ""),
            "triangle_nodes": _parse_nodes(row.get("triangle_nodes")),
            "key": _polygon_key(
                core_vertices,
                _parse_nodes(row.get("triangle_nodes")),
                digits=digits,
            ),
        }
        for row in core_triangle_rows
        if str(row.get("marker") or "") != LOOP_CAP_MARKER
        and _as_bool(row.get("candidate_owned", True))
    ]
    boundary_rows = _normalized_boundary_rows(candidate_boundary_faces)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, tuple[tuple[float, float, float], ...]]] = set()
    for raw_cell_index, cell in enumerate(candidate_cells):
        cell_index = int(cell.get("cell_index", raw_cell_index))
        cell_nodes = _parse_nodes(cell.get("nodes"))
        if len(cell_nodes) != 8:
            continue
        cell_node_set = set(cell_nodes)
        cell_boundary_rows = [
            row
            for row in boundary_rows
            if set(row["nodes"]).issubset(cell_node_set)
        ]
        boundary_point_sets = [
            (
                row,
                set(_polygon_key(candidate_vertices, row["nodes"], digits=digits)),
            )
            for row in cell_boundary_rows
        ]
        for entry in core_entries:
            triangle_points = set(entry["key"])
            matched_boundary_row = None
            for row, point_set in boundary_point_sets:
                if triangle_points.issubset(point_set):
                    matched_boundary_row = row
                    break
            if matched_boundary_row is None:
                continue
            row_key = (cell_index, entry["key"])
            if row_key in seen:
                continue
            triangle_nodes = _candidate_nodes_for_core_triangle(
                candidate_vertices,
                matched_boundary_row["nodes"],
                core_vertices,
                entry["triangle_nodes"],
                digits=digits,
            )
            seen.add(row_key)
            rows.append(
                {
                    "cell_index": cell_index,
                    "source": str(cell.get("source") or ""),
                    "role": str(cell.get("role") or ""),
                    "marker": entry["marker"],
                    "face_nodes": list(matched_boundary_row["nodes"]),
                    "triangle_nodes": list(triangle_nodes),
                }
            )
    return rows


def build_probe_summary(
    *,
    audit: Mapping[str, Any],
    output_dir: Path,
    geometry_source: str,
) -> dict[str, Any]:
    audit_status = str(audit.get("status") or "")
    ready = audit_status == "global_star_split_basis_ready"
    degenerate_reduction_required = (
        audit_status == "global_star_split_basis_degenerate_reduction_required"
    )
    blockers = []
    if degenerate_reduction_required:
        blockers.append("degenerate_star_triangles_require_cell_type_reduction")
    elif not ready:
        blockers.append("global_star_split_basis_not_ready")
    blockers.extend(
        [
            "merged_mixed_bl_core_su2_mesh_missing",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "global_star_split_basis_ready_mixed_mesh_pending"
            if ready
            else "global_star_split_degenerate_reduction_required"
            if degenerate_reduction_required
            else "global_star_split_basis_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "geometry_source": geometry_source,
        "output_dir": str(output_dir),
        "global_star_split_basis": dict(audit),
        "blockers": sorted(set(blockers)),
        "blocked_claims": [
            "merged BL+core SU2 handoff",
            "postprocessed near-wall y+",
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
    }


def run_probe(
    *,
    output_dir: Path,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    geometry = load_campaign_geometry(
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    block = build_wing_boundary_layer_block(
        geometry.spec.wing_spec,
        BoundaryLayerBlockSpec(
            first_layer_height_m=BL_FIRST_HEIGHT_M,
            growth_ratio=BL_GROWTH_RATIO,
            layer_count=BL_LAYERS,
        ),
    )
    candidate = build_near_wall_merged_volume_candidate(block)
    boundary_rows = merged_boundary_face_rows(block, candidate)
    core_boundary_rows = core_facing_rows(boundary_rows)
    cap_surface = build_loop_cap_surface(block, candidate)
    repaired_surface, repair = repair_loop_cap_geometric_seams(cap_surface)
    hybrid_audit = audit_hybrid_tet_prism_split_compatibility(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_interface=repaired_surface,
    )
    target_rows = global_star_target_triangle_rows(
        candidate_vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_vertices=repaired_surface.vertices,
        core_triangle_rows=hybrid_audit["core_triangle_rows"],
    )
    audit = audit_global_star_split_basis(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        external_boundary_rows=boundary_rows,
        target_triangle_rows=target_rows,
    )
    summary = build_probe_summary(
        audit=audit,
        output_dir=output_dir,
        geometry_source=str(geometry.section_table_path),
    )
    summary["baseline_a_authority"] = {
        "source": "current GO Baseline A geometry via load_campaign_geometry",
        "points_per_side": int(points_per_side),
        "spanwise_subdivisions": int(spanwise_subdivisions),
        "bl_first_height_m": BL_FIRST_HEIGHT_M,
        "bl_growth_ratio": BL_GROWTH_RATIO,
        "bl_layers": BL_LAYERS,
    }
    summary["hybrid_split_basis"] = {
        "status": hybrid_audit.get("status"),
        "matched_core_triangle_count": hybrid_audit.get("matched_core_triangle_count"),
        "core_triangle_count": hybrid_audit.get("core_triangle_count"),
        "candidate_owned_core_triangle_count": hybrid_audit.get(
            "candidate_owned_core_triangle_count"
        ),
    }
    summary["repair_basis"] = {
        "status": repair.get("status"),
        "dropped_duplicate_face_count": repair.get("dropped_duplicate_face_count"),
        "post_repair_bad_edge_count": (
            (repair.get("post_repair_audit") or {})
            .get("welded_topology", {})
            .get("bad_edge_count")
        ),
    }
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "global_star_target_triangles.csv", target_rows)
    write_csv(
        output_dir / "internal_split_leak_samples.csv",
        audit["internal_split_leak_samples"],
    )
    (output_dir / "global_star_split_basis_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    audit = summary["global_star_split_basis"]
    return "\n".join(
        [
            "# WO-006R22 Global Star Split Basis Probe",
            "",
            "This is topology basis evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- global star status: `{audit['status']}`",
            f"- candidate cells: `{audit['candidate_cell_count']}`",
            f"- star tet elements: `{audit['volume_element_count']}`",
            f"- target triangles matched: `{audit['matched_target_triangle_count']}` / `{audit['target_triangle_count']}`",
            f"- internal split leaks: `{audit['internal_split_leak_face_count']}`",
            f"- non-manifold split faces: `{audit['nonmanifold_split_face_count']}`",
            f"- non-positive star tets: `{audit['non_positive_tet_count']}`",
            f"- degenerate star triangles: `{audit.get('degenerate_star_triangle_count')}`",
            f"- blockers: `{summary['blockers']}`",
            "",
            f"Engineering read: {audit['engineering_read']}",
            "",
        ]
    )


def _blockers_for_status(
    *,
    ready: bool,
    internal_leak_count: int,
    nonmanifold_count: int,
    unmatched_target_count: int,
    non_positive_tet_count: int,
    degenerate_star_triangle_count: int,
) -> list[str]:
    blockers = []
    if not ready:
        blockers.append("global_star_split_basis_not_ready")
    if internal_leak_count:
        blockers.append("internal_split_faces_without_neighbor_match")
    if nonmanifold_count:
        blockers.append("nonmanifold_split_faces")
    if unmatched_target_count:
        blockers.append("core_target_triangles_not_matched")
    if non_positive_tet_count:
        blockers.append("non_positive_global_star_tets")
    if degenerate_star_triangle_count:
        blockers.append("degenerate_star_triangles_require_cell_type_reduction")
    blockers.extend(
        [
            "merged_mixed_bl_core_su2_mesh_missing",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )
    return blockers


def _star_tet_face_keys(
    center: tuple[float, float, float],
    triangle_points: Sequence[tuple[float, float, float]],
    *,
    digits: int,
) -> list[tuple[tuple[float, float, float], ...]]:
    a, b, c = triangle_points
    return [
        _point_polygon_key((a, b, c), digits=digits),
        _point_polygon_key((center, a, b), digits=digits),
        _point_polygon_key((center, b, c), digits=digits),
        _point_polygon_key((center, c, a), digits=digits),
    ]


def _deterministic_quad_triangulation(nodes: Sequence[int]) -> list[tuple[int, ...]]:
    node_tuple = tuple(int(node) for node in nodes)
    if len(node_tuple) == 3:
        return [node_tuple]
    if len(node_tuple) != 4:
        raise ValueError("Only triangle or quad faces can be star-triangulated")
    diagonals = [
        tuple(sorted((node_tuple[0], node_tuple[2]))),
        tuple(sorted((node_tuple[1], node_tuple[3]))),
    ]
    selected = min(diagonals)
    if selected == tuple(sorted((node_tuple[0], node_tuple[2]))):
        return [(node_tuple[0], node_tuple[1], node_tuple[2]), (node_tuple[0], node_tuple[2], node_tuple[3])]
    return [(node_tuple[1], node_tuple[2], node_tuple[3]), (node_tuple[1], node_tuple[3], node_tuple[0])]


def _candidate_nodes_for_core_triangle(
    candidate_vertices: Sequence[tuple[float, float, float]],
    candidate_face_nodes: Sequence[int],
    core_vertices: Sequence[tuple[float, float, float]],
    core_triangle_nodes: Sequence[int],
    *,
    digits: int,
) -> tuple[int, ...]:
    candidate_by_point = {
        _point_key(candidate_vertices[int(node)], digits=digits): int(node)
        for node in candidate_face_nodes
    }
    return tuple(
        candidate_by_point[_point_key(core_vertices[int(node)], digits=digits)]
        for node in core_triangle_nodes
    )


def _normalized_boundary_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(rows):
        nodes = _parse_nodes(row.get("nodes"))
        if len(nodes) < 3:
            continue
        normalized.append(
            {
                "boundary_face_index": int(row.get("boundary_face_index", index)),
                "source": str(row.get("source") or ""),
                "role": str(row.get("role") or ""),
                "nodes": nodes,
            }
        )
    return normalized


def _mean_point(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
) -> tuple[float, float, float]:
    count = float(len(nodes))
    return (
        sum(vertices[int(node)][0] for node in nodes) / count,
        sum(vertices[int(node)][1] for node in nodes) / count,
        sum(vertices[int(node)][2] for node in nodes) / count,
    )


def _tetra_volume(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    d: tuple[float, float, float],
) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    ad = (d[0] - a[0], d[1] - a[1], d[2] - a[2])
    cross = (
        ac[1] * ad[2] - ac[2] * ad[1],
        ac[2] * ad[0] - ac[0] * ad[2],
        ac[0] * ad[1] - ac[1] * ad[0],
    )
    return abs(ab[0] * cross[0] + ab[1] * cross[1] + ab[2] * cross[2]) / 6.0


def _triangle_area(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return 0.5 * (cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2) ** 0.5


def _polygon_key(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
    *,
    digits: int,
) -> tuple[tuple[float, float, float], ...]:
    return _point_polygon_key([vertices[int(node)] for node in nodes], digits=digits)


def _point_polygon_key(
    points: Sequence[tuple[float, float, float]],
    *,
    digits: int,
) -> tuple[tuple[float, float, float], ...]:
    return tuple(sorted(_point_key(point, digits=digits) for point in points))


def _point_key(
    point: tuple[float, float, float],
    *,
    digits: int,
) -> tuple[float, float, float]:
    return tuple(round(float(value), digits) for value in point)


def _face_node_key(nodes: Sequence[int]) -> tuple[int, ...]:
    return tuple(sorted(int(node) for node in nodes))


def _parse_nodes(raw: Any) -> tuple[int, ...]:
    if isinstance(raw, str):
        return tuple(int(part.strip()) for part in raw.strip("[]").split(",") if part.strip())
    return tuple(int(node) for node in raw)


def _as_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.lower() == "true"
    return bool(raw)


def _count_markers(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        marker = str(value)
        counts[marker] = counts.get(marker, 0) + 1
    return counts


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    args = parser.parse_args(argv)
    summary = run_probe(
        output_dir=args.output_dir,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
    )
    audit = summary["global_star_split_basis"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "star_status": audit["status"],
                "matched_target_triangles": (
                    f"{audit['matched_target_triangle_count']}/"
                    f"{audit['target_triangle_count']}"
                ),
                "internal_split_leaks": audit["internal_split_leak_face_count"],
                "nonmanifold_split_faces": audit["nonmanifold_split_face_count"],
                "non_positive_tets": audit["non_positive_tet_count"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
