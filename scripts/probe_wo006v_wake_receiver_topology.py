#!/usr/bin/env python3
"""Probe an owned TE/wake receiver before more BL/core CFD attempts.

WO-006U proved that sending every non-wall BL boundary face directly to the
core mesh is not watertight because wake/span-cap edges still touch the wing
wall. This probe builds the smallest topological wake receiver candidate:
cells that fill the gap between upper/lower wake connector sides, match the
layer-wise BL wake-cut faces, and expose only the outer wake face to the core
interface. It is still not CFD completion evidence.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
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
    build_boundary_layer_core_interface_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import SurfaceMesh  # noqa: E402
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006v_wake_receiver_topology_probe"


@dataclass(frozen=True)
class ReceiverCell:
    nodes: tuple[int, int, int, int, int, int, int, int]
    layer: int
    span_interval: int


@dataclass(frozen=True)
class ReceiverFace:
    nodes: tuple[int, int, int, int]
    role: str
    layer: int
    span_interval: int


def build_wake_receiver_cells(block: WingBoundaryLayerBlock) -> list[ReceiverCell]:
    """Build candidate cells filling the TE wake gap between upper/lower sides."""
    layer_count = int(block.metadata["layer_count"])
    section_count = int(block.metadata["station_count"])

    cells: list[ReceiverCell] = []
    for span_interval in range(section_count - 1):
        for layer in range(layer_count):
            cells.append(
                ReceiverCell(
                    nodes=(
                        wake_node(block, span_interval + 1, layer, 0),
                        wake_node(block, span_interval + 1, layer + 1, 0),
                        wake_node(block, span_interval + 1, layer + 1, 1),
                        wake_node(block, span_interval + 1, layer, 1),
                        wake_node(block, span_interval, layer, 0),
                        wake_node(block, span_interval, layer + 1, 0),
                        wake_node(block, span_interval, layer + 1, 1),
                        wake_node(block, span_interval, layer, 1),
                    ),
                    layer=layer,
                    span_interval=span_interval,
                )
            )
    return cells


def wake_node(
    block: WingBoundaryLayerBlock,
    section: int,
    layer: int,
    side: int,
) -> int:
    wall_count = int(block.section_blocks[0].metadata["wall_node_count"])
    layer_count = int(block.metadata["layer_count"])
    section_vertex_count = int(block.metadata["section_vertex_count"])
    wake_start = (layer_count + 1) * wall_count
    return section * section_vertex_count + wake_start + 2 * layer + side


def summarize_wake_receiver_topology(
    block: WingBoundaryLayerBlock,
    core_interface: SurfaceMesh,
) -> dict[str, Any]:
    receiver_cells = build_wake_receiver_cells(block)
    receiver_faces = [
        face for cell in receiver_cells for face in receiver_cell_faces(cell, block)
    ]
    receiver_face_counts = canonical_face_counts(face.nodes for face in receiver_faces)
    receiver_boundary_faces = [
        face for face in receiver_faces if receiver_face_counts[canonical_face(face.nodes)] == 1
    ]

    bl_wake_faces = [
        tuple(face.nodes) for face in block.boundary_faces if face.marker == "wake_cut"
    ]
    core_wake_faces = [
        tuple(face.nodes) for face in core_interface.faces if face.marker == "wake_cut"
    ]
    receiver_boundary_keys = {canonical_face(face.nodes) for face in receiver_boundary_faces}
    matched_bl = [
        nodes for nodes in bl_wake_faces if canonical_face(nodes) in receiver_boundary_keys
    ]
    remaining_bl = [
        nodes for nodes in bl_wake_faces if canonical_face(nodes) not in receiver_boundary_keys
    ]
    matched_core = [
        nodes for nodes in core_wake_faces if canonical_face(nodes) in receiver_boundary_keys
    ]
    remaining_core = [
        nodes for nodes in core_wake_faces if canonical_face(nodes) not in receiver_boundary_keys
    ]
    role_counts: dict[str, int] = {}
    for face in receiver_boundary_faces:
        role_counts[face.role] = role_counts.get(face.role, 0) + 1

    wall_touching_remaining = [
        nodes
        for nodes in remaining_bl
        if face_touches_marker(
            nodes,
            all_boundary_edge_markers=boundary_edge_marker_map(block),
            marker="wing_wall",
        )
    ]
    remaining_base = int(role_counts.get("receiver_base", 0))
    complete = not remaining_bl and not remaining_core and remaining_base == 0
    status = "complete" if complete else "partial_te_base_blocked"
    return {
        "schema_version": "wo006v_wake_receiver_topology.v1",
        "wake_receiver_status": status,
        "receiver_cell_count": len(receiver_cells),
        "receiver_boundary_face_count": len(receiver_boundary_faces),
        "receiver_boundary_role_counts": dict(sorted(role_counts.items())),
        "bl_wake_cut_boundary_face_count": len(bl_wake_faces),
        "matched_bl_wake_cut_face_count": len(matched_bl),
        "remaining_bl_wake_cut_face_count": len(remaining_bl),
        "remaining_bl_wake_cut_wall_touching_face_count": len(wall_touching_remaining),
        "core_wake_cut_face_count": len(core_wake_faces),
        "matched_core_wake_cut_face_count": len(matched_core),
        "remaining_core_wake_cut_face_count": len(remaining_core),
        "remaining_receiver_base_face_count": remaining_base,
        "receiver_cells": [
            {
                "span_interval": cell.span_interval,
                "layer": cell.layer,
                "nodes": list(cell.nodes),
            }
            for cell in receiver_cells
        ],
        "remaining_bl_wake_cut_faces": [
            {"nodes": list(nodes)} for nodes in remaining_bl
        ],
        "engineering_read": engineering_read(
            remaining_bl_count=len(remaining_bl),
            wall_touching_remaining_count=len(wall_touching_remaining),
            receiver_base_count=remaining_base,
        ),
    }


def receiver_cell_faces(
    cell: ReceiverCell,
    block: WingBoundaryLayerBlock,
) -> tuple[ReceiverFace, ...]:
    a, b, c, d, e, f, g, h = cell.nodes
    layer_count = int(block.metadata["layer_count"])
    return (
        ReceiverFace((a, b, c, d), "span_cap_receiver", cell.layer, cell.span_interval),
        ReceiverFace((e, f, g, h), "span_cap_receiver", cell.layer, cell.span_interval),
        ReceiverFace((a, e, f, b), "bl_wake_upper_match", cell.layer, cell.span_interval),
        ReceiverFace(
            (b, f, g, c),
            "core_wake_outer_match"
            if cell.layer + 1 == layer_count
            else "receiver_internal_layer",
            cell.layer,
            cell.span_interval,
        ),
        ReceiverFace((c, g, h, d), "bl_wake_lower_match", cell.layer, cell.span_interval),
        ReceiverFace(
            (d, h, e, a),
            "receiver_base" if cell.layer == 0 else "receiver_internal_layer",
            cell.layer,
            cell.span_interval,
        ),
    )


def build_probe_summary(wake_receiver: Mapping[str, Any]) -> dict[str, Any]:
    complete = wake_receiver.get("wake_receiver_status") == "complete"
    verdict = (
        "wake_receiver_topology_complete"
        if complete
        else "wake_receiver_partial_te_base_blocked"
    )
    return {
        "schema_version": "wo006v_wake_receiver_topology_probe.v1",
        "verdict": verdict,
        "wake_receiver": dict(wake_receiver),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "BL/core handoff readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": wake_receiver.get("engineering_read"),
    }


def engineering_read(
    *,
    remaining_bl_count: int,
    wall_touching_remaining_count: int,
    receiver_base_count: int,
) -> str:
    if remaining_bl_count == 0 and receiver_base_count == 0:
        return (
            "The wake receiver matches the BL wake-cut faces and does not leave "
            "a TE base closure. It still needs span-tip ownership, meshing, and "
            "SU2 readability gates."
        )
    if wall_touching_remaining_count > 0 or receiver_base_count > 0:
        return (
            "The wake receiver can internalize the layer-wise wake-cut side faces, "
            "but wall-touching TE-base faces remain. The next repair must define "
            "that TE-base ownership before any medium/fine SU2 ladder."
        )
    return (
        "The wake receiver is still partial. Continue topology repair before "
        "using any coefficient history."
    )


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
    wake_receiver = summarize_wake_receiver_topology(block, core_interface)
    summary = build_probe_summary(wake_receiver)
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
            "core_interface_marker_counts": core_interface.marker_counts(),
        }
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(
        output_dir / "wake_receiver_cells.csv",
        summary["wake_receiver"]["receiver_cells"],
    )
    write_csv(
        output_dir / "remaining_bl_wake_cut_faces.csv",
        summary["wake_receiver"]["remaining_bl_wake_cut_faces"],
    )
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def canonical_face(nodes: Sequence[int]) -> tuple[int, ...]:
    return tuple(sorted(int(node) for node in nodes))


def canonical_face_counts(faces: Sequence[Sequence[int]]) -> dict[tuple[int, ...], int]:
    counts: dict[tuple[int, ...], int] = {}
    for face in faces:
        key = canonical_face(face)
        counts[key] = counts.get(key, 0) + 1
    return counts


def face_touches_marker(
    nodes: Sequence[int],
    *,
    all_boundary_edge_markers: Mapping[tuple[int, int], Sequence[str]],
    marker: str,
) -> bool:
    node_list = [int(node) for node in nodes]
    for left, right in zip(node_list, [*node_list[1:], node_list[0]]):
        edge = tuple(sorted((left, right)))
        if marker in set(all_boundary_edge_markers.get(edge, [])):
            return True
    return False


def boundary_edge_marker_map(block: WingBoundaryLayerBlock) -> dict[tuple[int, int], list[str]]:
    edge_map: dict[tuple[int, int], list[str]] = {}
    for face in block.boundary_faces:
        nodes = [int(node) for node in face.nodes]
        for left, right in zip(nodes, [*nodes[1:], nodes[0]]):
            edge = tuple(sorted((left, right)))
            edge_map.setdefault(edge, []).append(str(face.marker))
    return edge_map


def render_report(summary: Mapping[str, Any]) -> str:
    receiver = summary["wake_receiver"]
    lines = [
        "# WO-006V Wake Receiver Topology Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- wake receiver status: `{receiver.get('wake_receiver_status')}`",
        f"- receiver cells: `{receiver.get('receiver_cell_count')}`",
        f"- BL wake-cut faces matched: `{receiver.get('matched_bl_wake_cut_face_count')}` / `{receiver.get('bl_wake_cut_boundary_face_count')}`",
        f"- remaining BL wake-cut faces: `{receiver.get('remaining_bl_wake_cut_face_count')}`",
        f"- remaining wall-touching BL wake-cut faces: `{receiver.get('remaining_bl_wake_cut_wall_touching_face_count')}`",
        f"- core wake-cut faces matched: `{receiver.get('matched_core_wake_cut_face_count')}` / `{receiver.get('core_wake_cut_face_count')}`",
        f"- receiver base faces: `{receiver.get('remaining_receiver_base_face_count')}`",
        f"- engineering read: {summary['engineering_read']}",
        "",
        "Blocked claims:",
        "- BL/core handoff readiness",
        "- medium/fine CFD ladder readiness",
        "- CL/CD/Cm interpretation",
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
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "matched_bl_wake_cut_face_count": summary["wake_receiver"][
                    "matched_bl_wake_cut_face_count"
                ],
                "remaining_bl_wake_cut_face_count": summary["wake_receiver"][
                    "remaining_bl_wake_cut_face_count"
                ],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
