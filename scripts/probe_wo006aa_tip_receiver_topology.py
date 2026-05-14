#!/usr/bin/env python3
"""Probe a WO-006AA tip receiver topology candidate.

WO-006Y proved the BL span-cap faces do not natively match the core span caps.
This probe builds a virtual tip-receiver accounting layer that matches every
BL span-cap face and classifies the remaining side boundaries. It is topology
evidence only, not a final mesh or CFD coefficient route.
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
    build_boundary_layer_wall_surface,
    build_wing_boundary_layer_block,
)
from probe_wo006v_wake_receiver_topology import (  # noqa: E402
    boundary_edge_marker_map,
    canonical_face,
    canonical_face_counts,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006aa_tip_receiver_topology_probe"


@dataclass(frozen=True)
class TipReceiverCell:
    nodes: tuple[int, int, int, int, int, int, int, int]
    tip: str
    source_face_index: int


@dataclass(frozen=True)
class TipReceiverFace:
    nodes: tuple[int, ...]
    role: str
    tip: str
    source_face_index: int
    source_edge: tuple[int, int] | None = None


def build_tip_receiver_cells(block: WingBoundaryLayerBlock) -> list[TipReceiverCell]:
    section_vertex_count = int(block.metadata["section_vertex_count"])
    section_count = int(block.metadata["station_count"])
    first_tip = 0
    last_tip = section_count - 1
    next_virtual_node = len(block.vertices)
    virtual_nodes: dict[tuple[str, int], int] = {}

    def tip_for_face(nodes: Sequence[int]) -> str | None:
        node_sections = {int(node) // section_vertex_count for node in nodes}
        if node_sections == {first_tip}:
            return "left_tip"
        if node_sections == {last_tip}:
            return "right_tip"
        return None

    def virtual_node(tip: str, node: int) -> int:
        nonlocal next_virtual_node
        key = (tip, int(node))
        if key not in virtual_nodes:
            virtual_nodes[key] = next_virtual_node
            next_virtual_node += 1
        return virtual_nodes[key]

    cells: list[TipReceiverCell] = []
    for face_index, face in enumerate(block.boundary_faces):
        if face.marker != "span_cap":
            continue
        tip = tip_for_face(face.nodes)
        if tip is None:
            continue
        a, b, c, d = tuple(int(node) for node in face.nodes)
        cells.append(
            TipReceiverCell(
                nodes=(
                    a,
                    b,
                    c,
                    d,
                    virtual_node(tip, a),
                    virtual_node(tip, b),
                    virtual_node(tip, c),
                    virtual_node(tip, d),
                ),
                tip=tip,
                source_face_index=face_index,
            )
        )
    return cells


def tip_receiver_cell_faces(cell: TipReceiverCell) -> tuple[TipReceiverFace, ...]:
    a, b, c, d, e, f, g, h = cell.nodes
    return (
        TipReceiverFace((a, b, c, d), "bl_span_cap_match", cell.tip, cell.source_face_index),
        TipReceiverFace(
            (e, f, g, h),
            "core_tip_receiver_outer",
            cell.tip,
            cell.source_face_index,
        ),
        TipReceiverFace(
            (a, e, f, b),
            "receiver_side",
            cell.tip,
            cell.source_face_index,
            source_edge=tuple(sorted((a, b))),
        ),
        TipReceiverFace(
            (b, f, g, c),
            "receiver_side",
            cell.tip,
            cell.source_face_index,
            source_edge=tuple(sorted((b, c))),
        ),
        TipReceiverFace(
            (c, g, h, d),
            "receiver_side",
            cell.tip,
            cell.source_face_index,
            source_edge=tuple(sorted((c, d))),
        ),
        TipReceiverFace(
            (d, h, e, a),
            "receiver_side",
            cell.tip,
            cell.source_face_index,
            source_edge=tuple(sorted((d, a))),
        ),
    )


def summarize_tip_receiver_topology(block: WingBoundaryLayerBlock) -> dict[str, Any]:
    receiver_cells = build_tip_receiver_cells(block)
    receiver_faces = [
        face for cell in receiver_cells for face in tip_receiver_cell_faces(cell)
    ]
    receiver_face_counts = canonical_face_counts(face.nodes for face in receiver_faces)
    receiver_boundary_faces = [
        face
        for face in receiver_faces
        if receiver_face_counts[canonical_face(face.nodes)] == 1
    ]
    bl_span_faces = [
        tuple(face.nodes) for face in block.boundary_faces if face.marker == "span_cap"
    ]
    receiver_boundary_keys = {canonical_face(face.nodes) for face in receiver_boundary_faces}
    matched_bl = [
        nodes for nodes in bl_span_faces if canonical_face(nodes) in receiver_boundary_keys
    ]
    remaining_bl = [
        nodes for nodes in bl_span_faces if canonical_face(nodes) not in receiver_boundary_keys
    ]

    edge_markers = boundary_edge_marker_map(block)
    boundary_role_counts: dict[str, int] = {}
    side_role_counts: dict[str, int] = {}
    boundary_rows: list[dict[str, Any]] = []
    for face in receiver_boundary_faces:
        role = classify_receiver_boundary_role(face, edge_markers)
        boundary_role_counts[role] = boundary_role_counts.get(role, 0) + 1
        if face.role == "receiver_side":
            side_role_counts[role] = side_role_counts.get(role, 0) + 1
        boundary_rows.append(
            {
                "tip": face.tip,
                "source_face_index": face.source_face_index,
                "role": role,
                "nodes": list(face.nodes),
                "source_edge": None
                if face.source_edge is None
                else list(face.source_edge),
                "adjacent_markers": []
                if face.source_edge is None
                else sorted(edge_markers.get(face.source_edge, [])),
            }
        )

    all_span_caps_matched = len(matched_bl) == len(bl_span_faces)
    return {
        "schema_version": "wo006aa_tip_receiver_topology.v1",
        "tip_receiver_status": (
            "span_cap_receiver_accounting_ready"
            if all_span_caps_matched
            else "span_cap_receiver_accounting_blocked"
        ),
        "tip_receiver_cell_count": len(receiver_cells),
        "tip_receiver_boundary_face_count": len(receiver_boundary_faces),
        "receiver_boundary_role_counts": dict(sorted(boundary_role_counts.items())),
        "receiver_side_boundary_role_counts": dict(sorted(side_role_counts.items())),
        "bl_span_cap_face_count": len(bl_span_faces),
        "matched_bl_span_cap_face_count": len(matched_bl),
        "remaining_bl_span_cap_face_count": len(remaining_bl),
        "tip_receiver_cells": [
            {
                "tip": cell.tip,
                "source_face_index": cell.source_face_index,
                "nodes": list(cell.nodes),
            }
            for cell in receiver_cells
        ],
        "tip_receiver_boundary_faces": boundary_rows,
        "remaining_bl_span_cap_faces": [{"nodes": list(nodes)} for nodes in remaining_bl],
        "engineering_read": engineering_read(
            all_span_caps_matched=all_span_caps_matched,
            side_role_counts=side_role_counts,
        ),
    }


def classify_receiver_boundary_role(
    face: TipReceiverFace,
    edge_markers: Mapping[tuple[int, int], Sequence[str]],
) -> str:
    if face.role != "receiver_side" or face.source_edge is None:
        return face.role
    markers = set(edge_markers.get(face.source_edge, []))
    if "wing_wall" in markers:
        return "physical_wall_edge_receiver"
    if "wake_cut" in markers:
        return "wake_edge_receiver"
    if "bl_outer_interface" in markers:
        return "core_outer_edge_receiver"
    return "unclassified_receiver_side"


def build_probe_summary(tip_receiver: Mapping[str, Any]) -> dict[str, Any]:
    ready = tip_receiver.get("tip_receiver_status") == "span_cap_receiver_accounting_ready"
    return {
        "schema_version": "wo006aa_tip_receiver_topology_probe.v1",
        "verdict": (
            "tip_receiver_accounting_ready_not_handoff"
            if ready
            else "tip_receiver_accounting_blocked"
        ),
        "tip_receiver": dict(tip_receiver),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "BL/core handoff readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": tip_receiver.get("engineering_read"),
    }


def engineering_read(
    *,
    all_span_caps_matched: bool,
    side_role_counts: Mapping[str, int],
) -> str:
    if not all_span_caps_matched:
        return (
            "The virtual tip receiver does not yet account for every BL span-cap "
            "face. Do not attempt a merged mesh."
        )
    return (
        "A virtual tip receiver can account for every BL span-cap face, but its "
        "side boundaries still need real geometric implementation and matching "
        "to physical wall, wake receiver, and core outer interfaces before a "
        "final BL/core SU2 handoff. Side boundary counts: "
        f"{dict(sorted(side_role_counts.items()))}."
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
    wall_surface = build_boundary_layer_wall_surface(block, include_tip_caps=True)
    tip_receiver = summarize_tip_receiver_topology(block)
    summary = build_probe_summary(tip_receiver)
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
            "physical_wall_surface": {
                "marker_counts": wall_surface.marker_counts(),
                "metadata": wall_surface.metadata,
            },
        }
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "tip_receiver_cells.csv", tip_receiver["tip_receiver_cells"])
    write_csv(
        output_dir / "tip_receiver_boundary_faces.csv",
        tip_receiver["tip_receiver_boundary_faces"],
    )
    write_csv(
        output_dir / "remaining_bl_span_cap_faces.csv",
        tip_receiver["remaining_bl_span_cap_faces"],
    )
    (output_dir / "tip_receiver_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    receiver = summary["tip_receiver"]
    lines = [
        "# WO-006AA Tip Receiver Topology Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- tip receiver status: `{receiver.get('tip_receiver_status')}`",
        f"- receiver cells: `{receiver.get('tip_receiver_cell_count')}`",
        f"- BL span-cap faces matched: `{receiver.get('matched_bl_span_cap_face_count')}` / `{receiver.get('bl_span_cap_face_count')}`",
        f"- remaining BL span-cap faces: `{receiver.get('remaining_bl_span_cap_face_count')}`",
        f"- receiver boundary role counts: `{receiver.get('receiver_boundary_role_counts')}`",
        f"- receiver side role counts: `{receiver.get('receiver_side_boundary_role_counts')}`",
        f"- engineering read: {summary['engineering_read']}",
        "",
        "Blocked claims:",
        "- BL/core handoff readiness",
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
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "matched_bl_span_cap_face_count": summary["tip_receiver"][
                    "matched_bl_span_cap_face_count"
                ],
                "remaining_bl_span_cap_face_count": summary["tip_receiver"][
                    "remaining_bl_span_cap_face_count"
                ],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
