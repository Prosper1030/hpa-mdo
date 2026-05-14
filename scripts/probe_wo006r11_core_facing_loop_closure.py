#!/usr/bin/env python3
"""Materialize WO-006R11 core-facing loop caps after the R10 gap audit.

R10 proved the repaired near-wall shell is watertight only if physical wall-edge
receiver faces are borrowed. R11 takes the next bounded step: extract the two
core-facing open loops and add explicit loop-cap faces so the core-facing inner
surface is topologically closed without marking the physical wall itself as a
core interface.

This is still topology evidence only. The loop-cap surface must be followed by a
real core/farfield mesh, marker/readability gate, near-wall/y+ postprocessing,
and SU2 ladder before coefficients can be interpreted.
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
    WingBoundaryLayerBlock,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    Face,
    SurfaceMesh,
    validate_surface_mesh,
)
from probe_wo006ad_near_wall_merged_volume_candidate import (  # noqa: E402
    MergedVolumeCandidate,
    build_near_wall_merged_volume_candidate,
    merged_boundary_face_rows,
)
from probe_wo006r10_near_wall_core_closure import (  # noqa: E402
    CORE_EXCLUDED_PHYSICAL_ROLES,
    boundary_topology,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r11_core_facing_loop_closure_probe"
LOOP_CAP_MARKER = "core_wall_loop_cap"


def summarize_core_facing_loop_closure(
    block: WingBoundaryLayerBlock,
    candidate: MergedVolumeCandidate,
) -> dict[str, Any]:
    boundary_rows = merged_boundary_face_rows(block, candidate)
    core_rows = core_facing_rows(boundary_rows)
    pre_cap_topology = boundary_topology(core_rows)
    loops = open_edge_loops(core_rows)
    cap_surface = build_core_facing_loop_cap_surface(candidate, core_rows, loops)
    post_cap_topology = boundary_topology(surface_face_rows(cap_surface))
    cap_quality = loop_cap_quality(cap_surface, loops)

    blockers: list[str] = []
    if pre_cap_topology.get("status") != "not_watertight":
        blockers.append("r10_open_loop_precondition_not_observed")
    if not loops:
        blockers.append("core_facing_open_loops_missing")
    if post_cap_topology.get("status") != "watertight":
        blockers.append("core_facing_loop_cap_surface_not_watertight")
    if int(cap_quality.get("non_positive_cap_area_count") or 0) > 0:
        blockers.append("core_wall_loop_cap_non_positive_area")

    ready_as_surface = not blockers
    blockers.extend(
        [
            "core_farfield_mesh_not_generated",
            "merged_mesh_quality_not_run",
            "su2_marker_readability_not_run",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )
    return {
        "schema_version": "wo006r11_core_facing_loop_closure.v1",
        "status": (
            "core_facing_loop_cap_surface_ready_core_mesh_pending"
            if ready_as_surface
            else "core_facing_loop_cap_surface_blocked"
        ),
        "can_generate_core_mesh_probe": ready_as_surface,
        "core_facing_boundary_face_count_before_caps": len(core_rows),
        "core_facing_boundary_face_count_after_caps": len(cap_surface.faces),
        "loop_count": len(loops),
        "loop_node_counts": [len(loop) for loop in loops],
        "cap_face_count": cap_quality["cap_face_count"],
        "cap_marker": LOOP_CAP_MARKER,
        "pre_cap_topology": pre_cap_topology,
        "post_cap_topology": post_cap_topology,
        "cap_quality": cap_quality,
        "surface_marker_counts": cap_surface.marker_counts(),
        "blockers": blockers,
        "engineering_read": (
            "The R10 wall-edge gaps form closed loops that can be materialized as "
            "explicit core-facing loop caps. This repairs core-facing surface "
            "topology, but it is not yet a merged BL/core SU2 handoff."
            if ready_as_surface
            else "The R10 wall-edge gaps could not be materialized into a clean core-facing cap surface."
        ),
    }


def core_facing_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("role")) not in CORE_EXCLUDED_PHYSICAL_ROLES
    ]


def open_edge_loops(rows: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    edge_counts: dict[tuple[int, int], int] = {}
    for row in rows:
        nodes = [int(node) for node in row.get("nodes", [])]
        for left, right in zip(nodes, [*nodes[1:], nodes[0]]):
            if left == right:
                continue
            edge = tuple(sorted((left, right)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1

    bad_edges = [edge for edge, count in edge_counts.items() if count != 2]
    adjacency: dict[int, list[int]] = {}
    for left, right in bad_edges:
        adjacency.setdefault(left, []).append(right)
        adjacency.setdefault(right, []).append(left)

    loops: list[list[int]] = []
    seen: set[int] = set()
    for start in sorted(adjacency):
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        previous = None
        current = start
        while True:
            next_nodes = [node for node in sorted(adjacency[current]) if node != previous]
            if not next_nodes:
                break
            next_node = next_nodes[0]
            if next_node == start:
                break
            if next_node in seen:
                break
            loop.append(next_node)
            seen.add(next_node)
            previous, current = current, next_node
        loops.append(loop)
    return loops


def build_core_facing_loop_cap_surface(
    candidate: MergedVolumeCandidate,
    core_rows: Sequence[Mapping[str, Any]],
    loops: Sequence[Sequence[int]],
) -> SurfaceMesh:
    vertices = list(candidate.vertices)
    faces = [
        Face(nodes=tuple(int(node) for node in row["nodes"]), marker=str(row["role"]))
        for row in core_rows
    ]
    for loop in loops:
        if len(loop) < 3:
            continue
        center_index = len(vertices)
        vertices.append(_centroid([vertices[int(node)] for node in loop]))
        for left, right in zip(loop, [*loop[1:], loop[0]]):
            faces.append(
                Face(
                    nodes=(center_index, int(left), int(right)),
                    marker=LOOP_CAP_MARKER,
                )
            )
    return SurfaceMesh(
        vertices=vertices,
        faces=faces,
        metadata={
            "surface_role": "wo006r11_core_facing_loop_cap_surface",
            "loop_count": len(loops),
            "cap_marker": LOOP_CAP_MARKER,
        },
    )


def surface_face_rows(surface: SurfaceMesh) -> list[dict[str, Any]]:
    return [
        {
            "source": "core_facing_loop_cap_surface",
            "role": face.marker,
            "nodes": list(face.nodes),
        }
        for face in surface.faces
    ]


def loop_cap_quality(surface: SurfaceMesh, loops: Sequence[Sequence[int]]) -> dict[str, Any]:
    cap_faces = [face for face in surface.faces if face.marker == LOOP_CAP_MARKER]
    areas = [_face_area([surface.vertices[node] for node in face.nodes]) for face in cap_faces]
    loop_bounds = []
    for loop in loops:
        points = [surface.vertices[int(node)] for node in loop]
        loop_bounds.append(
            {
                "node_count": len(loop),
                "x_min": min(point[0] for point in points),
                "x_max": max(point[0] for point in points),
                "y_min": min(point[1] for point in points),
                "y_max": max(point[1] for point in points),
                "z_min": min(point[2] for point in points),
                "z_max": max(point[2] for point in points),
            }
        )
    return {
        "cap_face_count": len(cap_faces),
        "min_cap_area_m2": min(areas) if areas else 0.0,
        "max_cap_area_m2": max(areas) if areas else 0.0,
        "non_positive_cap_area_count": sum(1 for area in areas if area <= 1.0e-14),
        "loop_bounds": loop_bounds,
    }


def build_probe_summary(*, loop_closure: Mapping[str, Any]) -> dict[str, Any]:
    ready = (
        loop_closure.get("status")
        == "core_facing_loop_cap_surface_ready_core_mesh_pending"
    )
    return {
        "schema_version": "wo006r11_core_facing_loop_closure_probe.v1",
        "verdict": (
            "core_facing_loop_cap_surface_ready_not_handoff"
            if ready
            else "core_facing_loop_cap_surface_blocked"
        ),
        "loop_closure": dict(loop_closure),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "full BL/core/farfield Gmsh mesh readiness",
            "SU2 marker/readability readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": loop_closure.get("engineering_read"),
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
    core_rows = core_facing_rows(boundary_rows)
    loops = open_edge_loops(core_rows)
    cap_surface = build_core_facing_loop_cap_surface(candidate, core_rows, loops)
    validate_surface_mesh(
        cap_surface,
        allowed_markers=frozenset(cap_surface.marker_counts()),
        required_markers=(),
    )
    loop_closure = summarize_core_facing_loop_closure(block, candidate)
    summary = build_probe_summary(loop_closure=loop_closure)
    summary.update(
        {
            "output_dir": str(output_dir),
            "geometry_source": str(geometry.section_table_path),
            "points_per_side": int(points_per_side),
            "spanwise_subdivisions": int(spanwise_subdivisions),
            "owned_bl_block": {
                "cell_count": len(block.cells),
                "boundary_marker_counts": block.boundary_marker_counts(),
                "quality": block.quality,
            },
        }
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "loop_table.csv", loop_rows(cap_surface, loops))
    write_csv(output_dir / "surface_marker_counts.csv", marker_count_rows(cap_surface))
    (output_dir / "core_facing_loop_closure_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def loop_rows(surface: SurfaceMesh, loops: Sequence[Sequence[int]]) -> list[dict[str, Any]]:
    quality = loop_cap_quality(surface, loops)
    return [
        {
            "loop_index": index,
            **bounds,
        }
        for index, bounds in enumerate(quality["loop_bounds"])
    ]


def marker_count_rows(surface: SurfaceMesh) -> list[dict[str, Any]]:
    return [
        {"marker": marker, "face_count": count}
        for marker, count in sorted(surface.marker_counts().items())
    ]


def render_report(summary: Mapping[str, Any]) -> str:
    closure = summary["loop_closure"]
    return "\n".join(
        [
            "# WO-006R11 Core-Facing Loop Closure Probe",
            "",
            "This is topology evidence only, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- geometry source: `{summary['geometry_source']}`",
            f"- points per side: `{summary['points_per_side']}`",
            f"- spanwise subdivisions: `{summary['spanwise_subdivisions']}`",
            f"- pre-cap topology: `{(closure.get('pre_cap_topology') or {}).get('status')}`",
            f"- post-cap topology: `{(closure.get('post_cap_topology') or {}).get('status')}`",
            f"- loop count: `{closure.get('loop_count')}`",
            f"- loop node counts: `{closure.get('loop_node_counts')}`",
            f"- cap face count: `{closure.get('cap_face_count')}`",
            f"- can generate core mesh probe: `{closure.get('can_generate_core_mesh_probe')}`",
            f"- blockers: `{closure.get('blockers')}`",
            f"- engineering read: {summary['engineering_read']}",
            "",
            "Blocked claims:",
            "- full BL/core/farfield Gmsh mesh readiness",
            "- SU2 marker/readability readiness",
            "- medium/fine CFD ladder readiness",
            "- CL/CD/Cm interpretation",
            "- Baseline A drag or power truth",
        ]
    ) + "\n"


def _centroid(points: Sequence[tuple[float, float, float]]) -> tuple[float, float, float]:
    scale = 1.0 / len(points)
    return (
        sum(point[0] for point in points) * scale,
        sum(point[1] for point in points) * scale,
        sum(point[2] for point in points) * scale,
    )


def _face_area(points: Sequence[tuple[float, float, float]]) -> float:
    if len(points) != 3:
        raise ValueError("R11 loop cap quality expects triangular cap faces")
    a, b, c = points
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return 0.5 * (
        cross[0] * cross[0]
        + cross[1] * cross[1]
        + cross[2] * cross[2]
    ) ** 0.5


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


def main(argv: list[str] | None = None) -> int:
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
    closure = summary["loop_closure"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "pre_cap_status": closure["pre_cap_topology"]["status"],
                "post_cap_status": closure["post_cap_topology"]["status"],
                "loop_count": closure["loop_count"],
                "can_generate_core_mesh_probe": closure["can_generate_core_mesh_probe"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
