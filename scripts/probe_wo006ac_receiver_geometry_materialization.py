#!/usr/bin/env python3
"""Materialize the WO-006 tip receiver geometry candidate.

WO-006AB proves topology accounting is ready as a pre-mesh contract. This probe
turns the virtual tip receiver into explicit coordinates and volume cells so the
next route can build a real merged BL+core mesh instead of inventing a handoff
from accounting alone.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
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
from hpa_meshing.mesh_native.wing_surface import Vertex  # noqa: E402
from probe_wo006aa_tip_receiver_topology import (  # noqa: E402
    TipReceiverCell,
    build_tip_receiver_cells,
    summarize_tip_receiver_topology,
)
from probe_wo006ab_bl_core_topology_accounting_gate import (  # noqa: E402
    evaluate_topology_accounting,
    summarize_outer_interface_accounting,
    summarize_wall_surface,
)
from probe_wo006x_stitched_wake_handoff_gate import (  # noqa: E402
    evaluate_stitched_wake_handoff_gate,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402
from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    build_boundary_layer_core_interface_surface,
    build_boundary_layer_wall_surface,
)


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006ac_receiver_geometry_materialization_probe"


@dataclass(frozen=True)
class MaterializedTipReceiver:
    vertices: list[Vertex]
    cells: list[TipReceiverCell]
    receiver_thickness_m: float
    virtual_node_count: int


def materialize_tip_receiver_geometry(
    block: WingBoundaryLayerBlock,
    *,
    receiver_thickness_m: float | None = None,
) -> MaterializedTipReceiver:
    cells = build_tip_receiver_cells(block)
    if receiver_thickness_m is None:
        receiver_thickness_m = float(block.section_blocks[0].metadata["total_thickness_m"])
    if receiver_thickness_m <= 0.0 or not math.isfinite(receiver_thickness_m):
        raise ValueError("receiver_thickness_m must be positive and finite")

    vertices = list(block.vertices)
    next_virtual_index = len(vertices)
    virtual_to_source: dict[int, int] = {}
    for cell in cells:
        for source_node, virtual_node in zip(cell.nodes[:4], cell.nodes[4:]):
            virtual_to_source.setdefault(int(virtual_node), int(source_node))

    for virtual_node in sorted(virtual_to_source):
        if virtual_node != next_virtual_index:
            raise ValueError("Tip receiver virtual node ids must be contiguous")
        source = virtual_to_source[virtual_node]
        x, y, z = block.vertices[source]
        sign = -1.0 if y < 0.0 else 1.0
        vertices.append((x, y + sign * receiver_thickness_m, z))
        next_virtual_index += 1

    return MaterializedTipReceiver(
        vertices=vertices,
        cells=cells,
        receiver_thickness_m=float(receiver_thickness_m),
        virtual_node_count=len(virtual_to_source),
    )


def summarize_materialized_tip_receiver(
    block: WingBoundaryLayerBlock,
    materialized: MaterializedTipReceiver,
) -> dict[str, Any]:
    tip_topology = summarize_tip_receiver_topology(block)
    volumes = [
        receiver_cell_volume(materialized.vertices, cell.nodes)
        for cell in materialized.cells
    ]
    non_positive = sum(1 for volume in volumes if volume <= 1.0e-14)
    blockers = []
    if tip_topology.get("remaining_bl_span_cap_face_count") != 0:
        blockers.append("tip_receiver_span_cap_accounting_not_pass")
    if non_positive:
        blockers.append("tip_receiver_non_positive_volume")
    blockers.extend(
        [
            "final_merged_mesh_missing",
            "merged_mesh_quality_not_run",
            "su2_marker_readability_not_run",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )
    status = (
        "tip_receiver_geometry_materialized_quality_pass"
        if not any(blocker.endswith("not_pass") or blocker.endswith("volume") for blocker in blockers)
        else "tip_receiver_geometry_materialized_quality_fail"
    )
    return {
        "schema_version": "wo006ac_receiver_geometry_materialization.v1",
        "status": status,
        "tip_receiver_cell_count": len(materialized.cells),
        "virtual_node_count": materialized.virtual_node_count,
        "total_vertex_count": len(materialized.vertices),
        "receiver_thickness_m": materialized.receiver_thickness_m,
        "matched_bl_span_cap_face_count": tip_topology.get("matched_bl_span_cap_face_count"),
        "remaining_bl_span_cap_face_count": tip_topology.get("remaining_bl_span_cap_face_count"),
        "min_receiver_volume_m3": min(volumes) if volumes else 0.0,
        "max_receiver_volume_m3": max(volumes) if volumes else 0.0,
        "non_positive_volume_count": non_positive,
        "external_shape_changed": False,
        "blockers": blockers,
        "engineering_read": (
            "The tip receiver now has explicit coordinates and positive volume "
            "cells, but no final merged BL+core mesh exists yet."
        ),
    }


def update_topology_accounting_after_receiver_materialization(
    topology_accounting: Mapping[str, Any],
    receiver_geometry: Mapping[str, Any],
) -> dict[str, Any]:
    updated = dict(topology_accounting)
    blockers = [
        str(blocker)
        for blocker in updated.get("blockers", [])
        if str(blocker) != "receiver_geometry_not_materialized"
    ]
    if receiver_geometry.get("status") != "tip_receiver_geometry_materialized_quality_pass":
        blockers.insert(0, "receiver_geometry_materialization_not_pass")
        updated["status"] = "topology_receiver_geometry_blocked"
    else:
        updated["status"] = "topology_receiver_geometry_ready_mesh_pending"
    updated["blockers"] = blockers
    updated["receiver_geometry_status"] = receiver_geometry.get("status")
    updated["engineering_read"] = (
        "Topology ownership accounting and tip receiver geometry materialization "
        "are ready as a pre-mesh contract. A real merged mesh, quality gate, SU2 "
        "marker/readability gate, near-wall y+, and solver ladder are still missing."
    )
    return updated


def receiver_cell_volume(vertices: Sequence[Vertex], nodes: Sequence[int]) -> float:
    points = [vertices[int(node)] for node in nodes]
    return _hexa_volume(points)


def _hexa_volume(points: Sequence[Vertex]) -> float:
    a, b, c, d, e, f, g, h = points
    tetrahedra = (
        (a, b, d, e),
        (b, c, d, g),
        (b, d, e, g),
        (b, e, f, g),
        (d, e, g, h),
    )
    return sum(abs(_tetra_volume(*tet)) for tet in tetrahedra)


def _tetra_volume(a: Vertex, b: Vertex, c: Vertex, d: Vertex) -> float:
    ab = _sub3(b, a)
    ac = _sub3(c, a)
    ad = _sub3(d, a)
    cross = (
        ac[1] * ad[2] - ac[2] * ad[1],
        ac[2] * ad[0] - ac[0] * ad[2],
        ac[0] * ad[1] - ac[1] * ad[0],
    )
    return (
        ab[0] * cross[0]
        + ab[1] * cross[1]
        + ab[2] * cross[2]
    ) / 6.0


def _sub3(left: Vertex, right: Vertex) -> Vertex:
    return (
        left[0] - right[0],
        left[1] - right[1],
        left[2] - right[2],
    )


def build_probe_summary(*, receiver_geometry: Mapping[str, Any]) -> dict[str, Any]:
    ready = receiver_geometry.get("status") == "tip_receiver_geometry_materialized_quality_pass"
    return {
        "schema_version": "wo006ac_receiver_geometry_materialization_probe.v1",
        "verdict": (
            "receiver_geometry_materialized_not_handoff"
            if ready
            else "receiver_geometry_materialization_blocked"
        ),
        "receiver_geometry": dict(receiver_geometry),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "full BL/core handoff readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": receiver_geometry.get("engineering_read"),
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
    core_interface = build_boundary_layer_core_interface_surface(block)
    wall_surface = summarize_wall_surface(
        build_boundary_layer_wall_surface(block, include_tip_caps=True)
    )
    wake_gate = evaluate_stitched_wake_handoff_gate(block, core_interface)
    tip_receiver = summarize_tip_receiver_topology(block)
    outer_interface = summarize_outer_interface_accounting(block, core_interface)
    topology_accounting = evaluate_topology_accounting(
        wall_surface=wall_surface,
        wake_gate=wake_gate,
        tip_receiver=tip_receiver,
        outer_interface=outer_interface,
    )
    materialized = materialize_tip_receiver_geometry(block)
    receiver_geometry = summarize_materialized_tip_receiver(block, materialized)
    topology_accounting = update_topology_accounting_after_receiver_materialization(
        topology_accounting,
        receiver_geometry,
    )
    summary = build_probe_summary(receiver_geometry=receiver_geometry)
    summary.update(
        {
            "output_dir": str(output_dir),
            "geometry_source": str(geometry.section_table_path),
            "points_per_side": int(points_per_side),
            "spanwise_subdivisions": int(spanwise_subdivisions),
            "topology_accounting": topology_accounting,
            "tip_receiver": tip_receiver,
            "owned_bl_block": {
                "cell_count": len(block.cells),
                "boundary_marker_counts": block.boundary_marker_counts(),
                "quality": block.quality,
            },
        }
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "receiver_geometry.csv", [receiver_geometry])
    write_csv(
        output_dir / "materialized_tip_receiver_cells.csv",
        [
            {
                "tip": cell.tip,
                "source_face_index": cell.source_face_index,
                "nodes": list(cell.nodes),
                "volume_m3": receiver_cell_volume(materialized.vertices, cell.nodes),
            }
            for cell in materialized.cells
        ],
    )
    (output_dir / "receiver_geometry_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    receiver = summary["receiver_geometry"]
    lines = [
        "# WO-006AC Receiver Geometry Materialization Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- geometry source: `{summary['geometry_source']}`",
        f"- receiver status: `{receiver.get('status')}`",
        f"- receiver cells: `{receiver.get('tip_receiver_cell_count')}`",
        f"- virtual nodes: `{receiver.get('virtual_node_count')}`",
        f"- receiver thickness (m): `{receiver.get('receiver_thickness_m')}`",
        f"- min receiver volume (m^3): `{receiver.get('min_receiver_volume_m3')}`",
        f"- non-positive receiver volumes: `{receiver.get('non_positive_volume_count')}`",
        f"- external shape changed: `{receiver.get('external_shape_changed')}`",
        f"- blockers: `{receiver.get('blockers')}`",
        f"- engineering read: {summary['engineering_read']}",
        "",
        "Blocked claims:",
        "- full BL/core handoff readiness",
        "- medium/fine CFD ladder readiness",
        "- CL/CD/Cm interpretation",
        "- Baseline A drag or power truth",
    ]
    return "\n".join(lines) + "\n"


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
    receiver = summary["receiver_geometry"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "receiver_status": receiver["status"],
                "tip_receiver_cell_count": receiver["tip_receiver_cell_count"],
                "non_positive_volume_count": receiver["non_positive_volume_count"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
