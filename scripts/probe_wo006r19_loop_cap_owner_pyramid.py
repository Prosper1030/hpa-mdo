#!/usr/bin/env python3
"""Probe owner pyramids for the WO-006R18 core-wall loop-cap residual.

R18 localized the largest remaining BL/core handoff gap to two
``core_wall_loop_cap`` triangle fans.  Those cap triangles close the core mesh,
but the near-wall side does not yet own matching faces.  R19 tests a bounded
repair pattern: use the existing physical-wall-edge receiver quads as pyramid
bases and the loop-cap fan centers as pyramid apices.  The resulting pyramid
side faces should exactly own the core-wall loop-cap triangles without changing
the Baseline A external wall coordinates.

This is still topology repair evidence only.  It does not write the final mixed
SU2 mesh, does not postprocess y+, and does not run CFD coefficients.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence


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


SCHEMA_VERSION = "wo006r19_loop_cap_owner_pyramid_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r19_loop_cap_owner_pyramid_probe"
LOOP_CAP_MARKER = "core_wall_loop_cap"
PHYSICAL_WALL_EDGE_RECEIVER = "physical_wall_edge_receiver"


def audit_loop_cap_owner_pyramids(
    *,
    candidate_vertices: Sequence[tuple[float, float, float]],
    core_vertices: Sequence[tuple[float, float, float]],
    physical_wall_edge_rows: Sequence[Mapping[str, Any]],
    core_triangle_rows: Sequence[Mapping[str, Any]],
    digits: int = 10,
) -> dict[str, Any]:
    loop_cap_rows = [
        row
        for row in core_triangle_rows
        if str(row.get("marker") or "") == LOOP_CAP_MARKER
    ]
    core_cap_keys = {
        _polygon_key(core_vertices, _parse_nodes(row.get("triangle_nodes")), digits=digits)
        for row in loop_cap_rows
    }
    fan_centers = _loop_cap_fan_centers(core_vertices, loop_cap_rows)
    owner_rows = _loop_cap_owner_pyramid_rows(
        candidate_vertices=candidate_vertices,
        core_vertices=core_vertices,
        physical_wall_edge_rows=physical_wall_edge_rows,
        fan_centers=fan_centers,
        digits=digits,
    )
    owner_keys = {row["owned_cap_triangle_key"] for row in owner_rows}
    matched_keys = core_cap_keys & owner_keys
    unmatched_keys = core_cap_keys - owner_keys
    volumes = [float(row["estimated_volume_m3"]) for row in owner_rows]
    non_positive = sum(1 for volume in volumes if volume <= 1.0e-14)
    fully_matched = bool(core_cap_keys) and len(matched_keys) == len(core_cap_keys)
    status = (
        "loop_cap_owner_pyramids_match"
        if fully_matched and non_positive == 0
        else "loop_cap_owner_pyramids_blocked"
    )
    remaining_hybrid = _remaining_non_loop_cap_residuals(core_triangle_rows)
    return {
        "schema_version": "wo006r19_loop_cap_owner_pyramid.v1",
        "status": status,
        "blockers": _blockers_for_status(
            status=status,
            unmatched_count=len(unmatched_keys),
            non_positive_count=non_positive,
            remaining_hybrid_residuals=remaining_hybrid,
        ),
        "physical_wall_edge_receiver_face_count": len(physical_wall_edge_rows),
        "owner_pyramid_cell_count": len(owner_rows),
        "loop_cap_fan_count": len(fan_centers),
        "core_wall_loop_cap_triangle_count": len(core_cap_keys),
        "matched_core_wall_loop_cap_triangle_count": len(matched_keys),
        "unmatched_core_wall_loop_cap_triangle_count": len(unmatched_keys),
        "non_positive_owner_pyramid_volume_count": non_positive,
        "min_owner_pyramid_volume_m3": min(volumes) if volumes else 0.0,
        "max_owner_pyramid_volume_m3": max(volumes) if volumes else 0.0,
        "remaining_hybrid_residuals_by_marker": remaining_hybrid,
        "owner_pyramid_rows": [
            {
                key: value
                for key, value in row.items()
                if key != "owned_cap_triangle_key"
            }
            for row in owner_rows
        ],
        "engineering_read": (
            "The physical-wall-edge receiver quads can be capped by loop-center "
            "pyramids that exactly own the core_wall_loop_cap fan triangles. "
            "This is a repair basis, not a final mixed SU2 mesh."
            if status == "loop_cap_owner_pyramids_match"
            else "The loop-cap owner pyramid pattern does not yet own every cap "
            "triangle cleanly, so a merged BL/core mesh would still be invalid."
        ),
    }


def build_probe_summary(
    *,
    audit: Mapping[str, Any],
    output_dir: Path,
    geometry_source: str,
) -> dict[str, Any]:
    remaining = audit.get("remaining_hybrid_residuals_by_marker") or {}
    loop_cap_ready = audit.get("status") == "loop_cap_owner_pyramids_match"
    blockers = []
    if not loop_cap_ready:
        blockers.append("core_wall_loop_cap_owner_pyramids_not_matched")
    if remaining:
        blockers.append("tip_wake_receiver_shared_tessellation_incompatible")
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
            "loop_cap_owner_pyramids_match_tip_split_still_blocked"
            if loop_cap_ready and remaining
            else "loop_cap_owner_pyramids_match_handoff_still_missing"
            if loop_cap_ready
            else "loop_cap_owner_pyramids_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "geometry_source": geometry_source,
        "output_dir": str(output_dir),
        "loop_cap_owner_pyramid": dict(audit),
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
    audit = audit_loop_cap_owner_pyramids(
        candidate_vertices=candidate.vertices,
        core_vertices=repaired_surface.vertices,
        physical_wall_edge_rows=[
            row
            for row in boundary_rows
            if str(row.get("role") or "") == PHYSICAL_WALL_EDGE_RECEIVER
        ],
        core_triangle_rows=hybrid_audit["core_triangle_rows"],
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
        "unowned_core_triangles_by_marker": hybrid_audit.get(
            "unowned_core_triangles_by_marker"
        ),
        "incompatible_owned_core_triangles_by_marker": hybrid_audit.get(
            "incompatible_owned_core_triangles_by_marker"
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
    write_csv(
        output_dir / "loop_cap_owner_pyramids.csv",
        audit["owner_pyramid_rows"],
    )
    (output_dir / "loop_cap_owner_pyramid_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    audit = summary["loop_cap_owner_pyramid"]
    return "\n".join(
        [
            "# WO-006R19 Loop-Cap Owner Pyramid Probe",
            "",
            "This is topology repair evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- owner status: `{audit['status']}`",
            f"- physical-wall-edge receiver faces: `{audit['physical_wall_edge_receiver_face_count']}`",
            f"- owner pyramid cells: `{audit['owner_pyramid_cell_count']}`",
            f"- loop-cap fan count: `{audit['loop_cap_fan_count']}`",
            f"- matched loop-cap triangles: `{audit['matched_core_wall_loop_cap_triangle_count']}` / `{audit['core_wall_loop_cap_triangle_count']}`",
            f"- non-positive owner volumes: `{audit['non_positive_owner_pyramid_volume_count']}`",
            f"- remaining hybrid residuals by marker: `{audit['remaining_hybrid_residuals_by_marker']}`",
            f"- blockers: `{summary['blockers']}`",
            "",
            f"Engineering read: {audit['engineering_read']}",
            "",
        ]
    )


def _loop_cap_owner_pyramid_rows(
    *,
    candidate_vertices: Sequence[tuple[float, float, float]],
    core_vertices: Sequence[tuple[float, float, float]],
    physical_wall_edge_rows: Sequence[Mapping[str, Any]],
    fan_centers: Sequence[Mapping[str, Any]],
    digits: int,
) -> list[dict[str, Any]]:
    rows = []
    for index, row in enumerate(physical_wall_edge_rows):
        nodes = _parse_nodes(row.get("nodes"))
        center = _center_for_receiver_row(candidate_vertices, core_vertices, nodes, fan_centers)
        outer_edge = _outer_span_edge(candidate_vertices, nodes)
        cap_points = [
            candidate_vertices[int(outer_edge[0])],
            candidate_vertices[int(outer_edge[1])],
            core_vertices[int(center["center_node"])],
        ]
        rows.append(
            {
                "owner_cell_index": index,
                "source": str(row.get("source") or ""),
                "role": PHYSICAL_WALL_EDGE_RECEIVER,
                "base_nodes": list(nodes),
                "outer_edge_nodes": list(outer_edge),
                "fan_index": int(center["fan_index"]),
                "center_node": int(center["center_node"]),
                "estimated_volume_m3": _pyramid_volume(
                    candidate_vertices,
                    nodes,
                    core_vertices[int(center["center_node"])],
                ),
                "owned_cap_triangle_key": _point_polygon_key(cap_points, digits=digits),
            }
        )
    return rows


def _loop_cap_fan_centers(
    vertices: Sequence[tuple[float, float, float]],
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cap_rows = [
        row for row in rows
        if str(row.get("marker") or "") == LOOP_CAP_MARKER
    ]
    node_to_rows: dict[int, set[int]] = {}
    for row_index, row in enumerate(cap_rows):
        for node in _parse_nodes(row.get("triangle_nodes")):
            node_to_rows.setdefault(int(node), set()).add(row_index)

    visited: set[int] = set()
    fans: list[dict[str, Any]] = []
    for start in range(len(cap_rows)):
        if start in visited:
            continue
        stack = [start]
        component_indices: set[int] = set()
        while stack:
            index = stack.pop()
            if index in visited:
                continue
            visited.add(index)
            component_indices.add(index)
            for node in _parse_nodes(cap_rows[index].get("triangle_nodes")):
                for neighbor in node_to_rows.get(int(node), set()):
                    if neighbor not in visited:
                        stack.append(neighbor)
        node_counts: dict[int, int] = {}
        for index in component_indices:
            for node in _parse_nodes(cap_rows[index].get("triangle_nodes")):
                node_counts[int(node)] = node_counts.get(int(node), 0) + 1
        center_node = max(node_counts, key=lambda node: (node_counts[node], -node))
        center_point = vertices[int(center_node)]
        fans.append(
            {
                "fan_index": len(fans),
                "center_node": center_node,
                "center_y": center_point[1],
                "triangle_count": len(component_indices),
            }
        )
    fans.sort(key=lambda item: item["center_y"])
    for index, fan in enumerate(fans):
        fan["fan_index"] = index
    return fans


def _center_for_receiver_row(
    candidate_vertices: Sequence[tuple[float, float, float]],
    core_vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
    fan_centers: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if not fan_centers:
        raise ValueError("At least one loop-cap fan center is required")
    mean_y = sum(candidate_vertices[int(node)][1] for node in nodes) / len(nodes)
    sign = -1.0 if mean_y < 0.0 else 1.0
    return max(
        fan_centers,
        key=lambda center: sign * core_vertices[int(center["center_node"])][1],
    )


def _outer_span_edge(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
) -> tuple[int, int]:
    node_tuple = tuple(int(node) for node in nodes)
    edges = tuple(zip(node_tuple, (*node_tuple[1:], node_tuple[0])))
    return max(
        edges,
        key=lambda edge: abs((vertices[edge[0]][1] + vertices[edge[1]][1]) * 0.5),
    )


def _remaining_non_loop_cap_residuals(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    residuals = []
    for row in rows:
        marker = str(row.get("marker") or "")
        if marker == LOOP_CAP_MARKER:
            continue
        if _as_bool(row.get("candidate_owned")) and _as_bool(
            row.get("matched_by_best_hybrid_split")
        ):
            continue
        residuals.append(marker)
    return dict(sorted(_count_markers(residuals).items()))


def _blockers_for_status(
    *,
    status: str,
    unmatched_count: int,
    non_positive_count: int,
    remaining_hybrid_residuals: Mapping[str, int],
) -> list[str]:
    blockers = []
    if status != "loop_cap_owner_pyramids_match":
        blockers.append("loop_cap_owner_pyramid_match_failed")
    if unmatched_count:
        blockers.append("loop_cap_owner_pyramid_unmatched_triangles")
    if non_positive_count:
        blockers.append("loop_cap_owner_pyramid_non_positive_volume")
    if remaining_hybrid_residuals:
        blockers.append("tip_wake_receiver_shared_tessellation_incompatible")
    blockers.extend(
        [
            "merged_mixed_bl_core_su2_mesh_missing",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )
    return blockers


def _pyramid_volume(
    vertices: Sequence[tuple[float, float, float]],
    base_nodes: Sequence[int],
    apex: tuple[float, float, float],
) -> float:
    a, b, c, d = [vertices[int(node)] for node in base_nodes]
    return _tetra_volume(apex, a, b, c) + _tetra_volume(apex, a, c, d)


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
    return tuple(
        sorted(
            tuple(round(float(value), digits) for value in point)
            for point in points
        )
    )


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


def _count_markers(values: Iterable[str]) -> dict[str, int]:
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
    audit = summary["loop_cap_owner_pyramid"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "owner_status": audit["status"],
                "matched_loop_cap_triangles": (
                    f"{audit['matched_core_wall_loop_cap_triangle_count']}/"
                    f"{audit['core_wall_loop_cap_triangle_count']}"
                ),
                "remaining_hybrid_residuals_by_marker": audit[
                    "remaining_hybrid_residuals_by_marker"
                ],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
