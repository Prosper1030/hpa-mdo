#!/usr/bin/env python3
"""Probe a left-tip star tessellation repair for the WO-006 BL/core handoff.

R19 proved that the loop-cap fan can be owned by pyramid cells, but two
``tip_receiver/left_tip`` cells still have a shared-tessellation mismatch at the
tip/wake receiver junction.  R20 tests the next local repair basis: split each
problematic receiver cell by a cell-center star so every core-facing boundary
triangle is owned explicitly.

This is still topology repair evidence only.  It does not write the final mixed
SU2 mesh, postprocess y+, or produce CFD coefficients.
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
from probe_wo006r19_loop_cap_owner_pyramid import (  # noqa: E402
    audit_loop_cap_owner_pyramids,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r20_left_tip_star_tessellation_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r20_left_tip_star_tessellation_probe"
LEFT_TIP_ROLE = "left_tip"
TIP_RECEIVER_SOURCE = "tip_receiver"
LOOP_CAP_MARKER = "core_wall_loop_cap"
PHYSICAL_WALL_EDGE_RECEIVER = "physical_wall_edge_receiver"


def audit_left_tip_star_tessellation(
    *,
    vertices: Sequence[tuple[float, float, float]],
    candidate_cells: Sequence[Mapping[str, Any]],
    target_triangle_rows: Sequence[Mapping[str, Any]],
    target_vertices: Sequence[tuple[float, float, float]] | None = None,
    digits: int = 10,
) -> dict[str, Any]:
    """Check whether center-star tets can own the target boundary triangles."""

    target_vertices = target_vertices or vertices
    cell_by_index = {
        int(cell.get("cell_index", raw_index)): cell
        for raw_index, cell in enumerate(candidate_cells)
    }
    target_rows = [
        row
        for row in target_triangle_rows
        if int(row.get("cell_index", -1)) in cell_by_index
    ]
    target_keys = {
        _polygon_key(target_vertices, _parse_nodes(row.get("triangle_nodes")), digits=digits)
        for row in target_rows
    }
    star_rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(target_rows):
        cell_index = int(row.get("cell_index", -1))
        cell = cell_by_index[cell_index]
        cell_nodes = _parse_nodes(cell.get("nodes"))
        if len(cell_nodes) != 8:
            continue
        center = _mean_point(vertices, cell_nodes)
        triangle_nodes = _parse_nodes(row.get("triangle_nodes"))
        triangle_points = [target_vertices[int(node)] for node in triangle_nodes]
        volume = _tetra_volume(center, *triangle_points)
        star_rows.append(
            {
                "star_tet_index": row_index,
                "cell_index": cell_index,
                "source": str(cell.get("source") or ""),
                "role": str(cell.get("role") or ""),
                "marker": str(row.get("marker") or ""),
                "cell_center": _format_point(center),
                "triangle_nodes": list(triangle_nodes),
                "estimated_volume_m3": volume,
                "target_triangle_key": _point_polygon_key(triangle_points, digits=digits),
            }
        )

    matched_keys = {row["target_triangle_key"] for row in star_rows}
    unmatched_keys = target_keys - matched_keys
    non_positive = sum(
        1 for row in star_rows if float(row["estimated_volume_m3"]) <= 1.0e-14
    )
    volumes = [float(row["estimated_volume_m3"]) for row in star_rows]
    matched_by_marker = _count_markers(
        str(row.get("marker") or "")
        for row in star_rows
        if row["target_triangle_key"] in target_keys
    )
    status = (
        "left_tip_star_tessellation_match"
        if target_keys and not unmatched_keys and non_positive == 0
        else "left_tip_star_tessellation_blocked"
    )
    return {
        "schema_version": "wo006r20_left_tip_star_tessellation.v1",
        "status": status,
        "blockers": _blockers_for_status(
            status=status,
            unmatched_count=len(unmatched_keys),
            non_positive_count=non_positive,
        ),
        "target_cell_count": len(
            {int(row.get("cell_index", -1)) for row in target_rows}
        ),
        "target_triangle_count": len(target_keys),
        "matched_target_triangle_count": len(matched_keys & target_keys),
        "unmatched_target_triangle_count": len(unmatched_keys),
        "matched_target_triangles_by_marker": dict(sorted(matched_by_marker.items())),
        "non_positive_star_tet_count": non_positive,
        "min_star_tet_volume_m3": min(volumes) if volumes else 0.0,
        "max_star_tet_volume_m3": max(volumes) if volumes else 0.0,
        "remaining_r17_residuals_after_r19_r20": {},
        "star_tet_rows": [
            {key: value for key, value in row.items() if key != "target_triangle_key"}
            for row in star_rows
        ],
        "engineering_read": (
            "The left-tip receiver cells can use cell-center star tets to own "
            "all currently targeted core-facing boundary triangles with positive "
            "volume. This is a local repair basis; it still needs a written mixed "
            "mesh, marker audit, and y+ postprocess before SU2 coefficients are "
            "credible."
            if status == "left_tip_star_tessellation_match"
            else "The left-tip receiver star tessellation does not yet match every "
            "target triangle cleanly. Running a medium/fine SU2 ladder would still "
            "be geometry/BC debugging, not CFD evidence."
        ),
    }


def build_probe_summary(
    *,
    audit: Mapping[str, Any],
    output_dir: Path,
    geometry_source: str,
) -> dict[str, Any]:
    ready = audit.get("status") == "left_tip_star_tessellation_match"
    remaining = audit.get("remaining_r17_residuals_after_r19_r20") or {}
    blockers = []
    if not ready:
        blockers.append("left_tip_star_tessellation_not_matched")
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
            "left_tip_star_tessellation_match_mixed_mesh_still_missing"
            if ready
            else "left_tip_star_tessellation_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "geometry_source": geometry_source,
        "output_dir": str(output_dir),
        "left_tip_star_tessellation": dict(audit),
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
    loop_cap_audit = audit_loop_cap_owner_pyramids(
        candidate_vertices=candidate.vertices,
        core_vertices=repaired_surface.vertices,
        physical_wall_edge_rows=[
            row
            for row in boundary_rows
            if str(row.get("role") or "") == PHYSICAL_WALL_EDGE_RECEIVER
        ],
        core_triangle_rows=hybrid_audit["core_triangle_rows"],
    )
    target_rows = left_tip_star_target_triangle_rows(
        candidate_vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_vertices=repaired_surface.vertices,
        core_triangle_rows=hybrid_audit["core_triangle_rows"],
        target_cell_indices=_left_tip_incompatible_cell_indices(hybrid_audit),
    )
    audit = audit_left_tip_star_tessellation(
        vertices=candidate.vertices,
        target_vertices=repaired_surface.vertices,
        candidate_cells=volume_cell_rows(candidate),
        target_triangle_rows=target_rows,
    )
    audit["remaining_r17_residuals_after_r19_r20"] = _remaining_after_star_repair(
        loop_cap_audit.get("remaining_hybrid_residuals_by_marker") or {},
        audit.get("matched_target_triangles_by_marker") or {},
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
    summary["loop_cap_owner_basis"] = {
        "status": loop_cap_audit.get("status"),
        "matched_core_wall_loop_cap_triangle_count": loop_cap_audit.get(
            "matched_core_wall_loop_cap_triangle_count"
        ),
        "core_wall_loop_cap_triangle_count": loop_cap_audit.get(
            "core_wall_loop_cap_triangle_count"
        ),
        "remaining_hybrid_residuals_by_marker": loop_cap_audit.get(
            "remaining_hybrid_residuals_by_marker"
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
    write_csv(output_dir / "left_tip_star_target_triangles.csv", target_rows)
    write_csv(
        output_dir / "left_tip_star_tets.csv",
        audit["star_tet_rows"],
    )
    (output_dir / "left_tip_star_tessellation_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def left_tip_star_target_triangle_rows(
    *,
    candidate_vertices: Sequence[tuple[float, float, float]],
    candidate_cells: Sequence[Mapping[str, Any]],
    candidate_boundary_faces: Sequence[Mapping[str, Any]],
    core_vertices: Sequence[tuple[float, float, float]],
    core_triangle_rows: Sequence[Mapping[str, Any]],
    target_cell_indices: set[int] | None = None,
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
    ]
    boundary_rows = _normalized_boundary_rows(candidate_boundary_faces)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, tuple[tuple[float, float, float], ...]]] = set()
    for raw_cell_index, cell in enumerate(candidate_cells):
        cell_index = int(cell.get("cell_index", raw_cell_index))
        if str(cell.get("source") or "") != TIP_RECEIVER_SOURCE:
            continue
        if str(cell.get("role") or "") != LEFT_TIP_ROLE:
            continue
        if target_cell_indices is not None and cell_index not in target_cell_indices:
            continue
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
            set(_polygon_key(candidate_vertices, row["nodes"], digits=digits))
            for row in cell_boundary_rows
        ]
        for entry in core_entries:
            triangle_points = set(entry["key"])
            if not any(triangle_points.issubset(points) for points in boundary_point_sets):
                continue
            row_key = (cell_index, entry["key"])
            if row_key in seen:
                continue
            seen.add(row_key)
            rows.append(
                {
                    "cell_index": cell_index,
                    "source": str(cell.get("source") or ""),
                    "role": str(cell.get("role") or ""),
                    "marker": entry["marker"],
                    "triangle_nodes": list(entry["triangle_nodes"]),
                }
            )
    return rows


def _left_tip_incompatible_cell_indices(
    hybrid_audit: Mapping[str, Any],
) -> set[int]:
    indices = set()
    for row in hybrid_audit.get("cell_choice_rows") or []:
        if str(row.get("source") or "") != TIP_RECEIVER_SOURCE:
            continue
        if str(row.get("role") or "") != LEFT_TIP_ROLE:
            continue
        if int(row.get("unmatched_triangle_count") or 0) <= 0:
            continue
        indices.add(int(row["cell_index"]))
    return indices


def render_report(summary: Mapping[str, Any]) -> str:
    audit = summary["left_tip_star_tessellation"]
    return "\n".join(
        [
            "# WO-006R20 Left-Tip Star Tessellation Probe",
            "",
            "This is topology repair evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- star status: `{audit['status']}`",
            f"- target cells: `{audit['target_cell_count']}`",
            f"- matched target triangles: `{audit['matched_target_triangle_count']}` / `{audit['target_triangle_count']}`",
            f"- matched target triangles by marker: `{audit['matched_target_triangles_by_marker']}`",
            f"- non-positive star tets: `{audit['non_positive_star_tet_count']}`",
            f"- star tet volume range m^3: `{audit['min_star_tet_volume_m3']}` to `{audit['max_star_tet_volume_m3']}`",
            f"- remaining R17 residuals after R19/R20: `{audit['remaining_r17_residuals_after_r19_r20']}`",
            f"- blockers: `{summary['blockers']}`",
            "",
            f"Engineering read: {audit['engineering_read']}",
            "",
        ]
    )


def _remaining_after_star_repair(
    residuals: Mapping[str, Any],
    matched_by_marker: Mapping[str, Any],
) -> dict[str, int]:
    remaining: dict[str, int] = {}
    for marker, raw_count in residuals.items():
        count = int(raw_count or 0)
        matched = int(matched_by_marker.get(str(marker), 0) or 0)
        rest = max(0, count - matched)
        if rest:
            remaining[str(marker)] = rest
    return dict(sorted(remaining.items()))


def _blockers_for_status(
    *,
    status: str,
    unmatched_count: int,
    non_positive_count: int,
) -> list[str]:
    blockers = []
    if status != "left_tip_star_tessellation_match":
        blockers.append("left_tip_star_tessellation_match_failed")
    if unmatched_count:
        blockers.append("left_tip_star_tessellation_unmatched_triangles")
    if non_positive_count:
        blockers.append("left_tip_star_tessellation_non_positive_volume")
    blockers.extend(
        [
            "merged_mixed_bl_core_su2_mesh_missing",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )
    return blockers


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


def _format_point(point: tuple[float, float, float]) -> str:
    return f"[{point[0]:.12g}, {point[1]:.12g}, {point[2]:.12g}]"


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
    audit = summary["left_tip_star_tessellation"]
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
                "non_positive_star_tets": audit["non_positive_star_tet_count"],
                "remaining_r17_residuals_after_r19_r20": audit[
                    "remaining_r17_residuals_after_r19_r20"
                ],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
