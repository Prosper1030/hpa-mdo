#!/usr/bin/env python3
"""Build a WO-006 near-wall merged-volume candidate.

WO-006AC materialized the virtual tip receiver, but it still stopped before a
single near-wall volume accounting object existed. This probe combines the owned
BL block, wake receiver, explicit sharp-TE stitch accounting, and materialized
tip receiver into one pre-core volume candidate. It is still not a Gmsh/SU2
handoff: the core/farfield mesh, quality gate, SU2 marker/readability gate, y+,
and solver ladder remain downstream blockers.
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
from hpa_meshing.mesh_native.wing_surface import Vertex  # noqa: E402
from probe_wo006aa_tip_receiver_topology import (  # noqa: E402
    classify_receiver_boundary_role,
    tip_receiver_cell_faces,
)
from probe_wo006ac_receiver_geometry_materialization import (  # noqa: E402
    MaterializedTipReceiver,
    materialize_tip_receiver_geometry,
    receiver_cell_volume,
    summarize_materialized_tip_receiver,
)
from probe_wo006v_wake_receiver_topology import (  # noqa: E402
    ReceiverCell,
    boundary_edge_marker_map,
    build_wake_receiver_cells,
    canonical_face,
    receiver_cell_faces,
)
from probe_wo006w_te_base_pairing import summarize_te_base_pairing  # noqa: E402
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006ad_near_wall_merged_volume_candidate_probe"


@dataclass(frozen=True)
class MergedVolumeCell:
    nodes: tuple[int, int, int, int, int, int, int, int]
    source: str
    role: str


@dataclass(frozen=True)
class MergedVolumeCandidate:
    vertices: list[Vertex]
    cells: list[MergedVolumeCell]
    materialized_tip_receiver: MaterializedTipReceiver
    wake_receiver_cells: list[ReceiverCell]
    stitched_te_base_face_keys: set[tuple[int, ...]]
    removed_receiver_base_face_keys: set[tuple[int, ...]]


def build_near_wall_merged_volume_candidate(
    block: WingBoundaryLayerBlock,
) -> MergedVolumeCandidate:
    materialized = materialize_tip_receiver_geometry(block)
    wake_cells = build_wake_receiver_cells(block)
    stitched_te_base_face_keys = _stitched_te_base_face_keys(block)
    removed_receiver_base_face_keys = _removed_degenerate_receiver_base_face_keys(
        block,
        wake_cells,
    )
    cells = [
        *[
            MergedVolumeCell(
                nodes=tuple(int(node) for node in cell.nodes),
                source="owned_bl_block",
                role=str(cell.marker),
            )
            for cell in block.cells
        ],
        *[
            MergedVolumeCell(
                nodes=tuple(int(node) for node in cell.nodes),
                source="wake_receiver",
                role="wake_receiver",
            )
            for cell in wake_cells
        ],
        *[
            MergedVolumeCell(
                nodes=tuple(int(node) for node in cell.nodes),
                source="tip_receiver",
                role=cell.tip,
            )
            for cell in materialized.cells
        ],
    ]
    return MergedVolumeCandidate(
        vertices=materialized.vertices,
        cells=cells,
        materialized_tip_receiver=materialized,
        wake_receiver_cells=wake_cells,
        stitched_te_base_face_keys=stitched_te_base_face_keys,
        removed_receiver_base_face_keys=removed_receiver_base_face_keys,
    )


def summarize_near_wall_merged_volume_candidate(
    block: WingBoundaryLayerBlock,
    candidate: MergedVolumeCandidate,
) -> dict[str, Any]:
    receiver_geometry = summarize_materialized_tip_receiver(
        block,
        candidate.materialized_tip_receiver,
    )
    face_rows = merged_boundary_face_rows(block, candidate)
    exposed_span_caps = [
        row for row in face_rows
        if row["source"] == "owned_bl_block" and row["role"] == "span_cap"
    ]
    exposed_wake_cut = [
        row for row in face_rows
        if row["source"] == "owned_bl_block" and row["role"] == "wake_cut"
    ]
    source_counts = _counts(row["source"] for row in face_rows)
    role_counts = _counts(row["role"] for row in face_rows)
    volume_quality = _volume_quality(block, candidate)
    external_boundary_topology = _external_boundary_topology(face_rows)
    blockers: list[str] = []
    if receiver_geometry.get("status") != "tip_receiver_geometry_materialized_quality_pass":
        blockers.append("tip_receiver_geometry_not_pass")
    if volume_quality["non_positive_volume_count"] != 0:
        blockers.append("near_wall_candidate_non_positive_volume")
    if exposed_span_caps:
        blockers.append("original_bl_span_cap_still_exposed")
    if exposed_wake_cut:
        blockers.append("original_bl_wake_cut_still_exposed")
    if external_boundary_topology["bad_edge_count"] != 0:
        blockers.append("near_wall_external_boundary_not_watertight")

    ready_as_candidate = not blockers
    blockers.extend(
        [
            "core_farfield_mesh_not_generated",
            "merged_mesh_quality_not_run",
            "su2_marker_readability_not_run",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )
    wall_surface = build_boundary_layer_wall_surface(block, include_tip_caps=True)
    return {
        "schema_version": "wo006ad_near_wall_merged_volume_candidate.v1",
        "status": (
            "near_wall_volume_candidate_ready_core_mesh_pending"
            if ready_as_candidate
            else "near_wall_volume_candidate_core_boundary_blocked"
        ),
        "node_count": len(candidate.vertices),
        "volume_cell_count": len(candidate.cells),
        "owned_bl_cell_count": len(block.cells),
        "wake_receiver_cell_count": len(candidate.wake_receiver_cells),
        "tip_receiver_cell_count": len(candidate.materialized_tip_receiver.cells),
        "te_base_stitched_face_count": len(candidate.stitched_te_base_face_keys),
        "degenerate_receiver_base_removed_face_count": len(
            candidate.removed_receiver_base_face_keys
        ),
        "boundary_face_count": len(face_rows),
        "boundary_face_source_counts": dict(sorted(source_counts.items())),
        "boundary_face_role_counts": dict(sorted(role_counts.items())),
        "remaining_exposed_original_span_cap_face_count": len(exposed_span_caps),
        "remaining_exposed_original_wake_cut_face_count": len(exposed_wake_cut),
        "physical_wall_face_count": (wall_surface.marker_counts()).get("wing_wall", 0),
        "receiver_geometry_status": receiver_geometry.get("status"),
        "volume_quality": volume_quality,
        "external_boundary_topology": external_boundary_topology,
        "blockers": blockers,
        "surface_ownership": {
            "wing_wall": "owned BL layer-0 physical wall surface",
            "bl_outer_interface": "near-wall outer boundary awaiting core/farfield mesh",
            "core_wake_outer_match": "wake receiver outer boundary awaiting core mesh",
            "core_tip_receiver_outer": "tip receiver outer boundary awaiting core mesh",
            "stitched_te_base": "sharp trailing-edge coincident wake seam removed from solver boundary accounting",
        },
        "engineering_read": (
            "The original BL span-cap and wake-cut faces are no longer exposed as "
            "standalone solver boundaries in the near-wall candidate. This clears "
            "the local ownership accounting blocker, but the core/farfield mesh "
            "and all SU2/y+ gates are still missing."
            if ready_as_candidate
            else "The near-wall merged volume candidate still needs boundary repair before core meshing."
        ),
    }


def merged_boundary_face_rows(
    block: WingBoundaryLayerBlock,
    candidate: MergedVolumeCandidate,
) -> list[dict[str, Any]]:
    records = _face_records(block, candidate)
    face_counts = _counts(record["key"] for record in records)
    rows = []
    for record in records:
        key = record["key"]
        if face_counts[key] != 1:
            continue
        if key in candidate.stitched_te_base_face_keys:
            continue
        if key in candidate.removed_receiver_base_face_keys:
            continue
        rows.append(
            {
                "source": record["source"],
                "role": record["role"],
                "nodes": list(record["nodes"]),
            }
        )
    return rows


def build_probe_summary(*, merged_volume: Mapping[str, Any]) -> dict[str, Any]:
    ready = merged_volume.get("status") == "near_wall_volume_candidate_ready_core_mesh_pending"
    return {
        "schema_version": "wo006ad_near_wall_merged_volume_candidate_probe.v1",
        "verdict": (
            "near_wall_volume_candidate_ready_not_su2_handoff"
            if ready
            else "near_wall_volume_candidate_core_boundary_blocked"
        ),
        "merged_volume": dict(merged_volume),
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
        "engineering_read": merged_volume.get("engineering_read"),
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
    merged_volume = summarize_near_wall_merged_volume_candidate(block, candidate)
    summary = build_probe_summary(merged_volume=merged_volume)
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
    write_csv(output_dir / "near_wall_volume_cells.csv", volume_cell_rows(candidate))
    write_csv(
        output_dir / "near_wall_boundary_faces.csv",
        merged_boundary_face_rows(block, candidate),
    )
    (output_dir / "near_wall_merged_volume_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def volume_cell_rows(candidate: MergedVolumeCandidate) -> list[dict[str, Any]]:
    return [
        {
            "cell_index": index,
            "source": cell.source,
            "role": cell.role,
            "nodes": list(cell.nodes),
        }
        for index, cell in enumerate(candidate.cells)
    ]


def render_report(summary: Mapping[str, Any]) -> str:
    merged = summary["merged_volume"]
    lines = [
        "# WO-006AD Near-Wall Merged Volume Candidate Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- geometry source: `{summary['geometry_source']}`",
        f"- merged volume status: `{merged.get('status')}`",
        f"- nodes: `{merged.get('node_count')}`",
        f"- cells: `{merged.get('volume_cell_count')}`",
        f"- owned BL cells: `{merged.get('owned_bl_cell_count')}`",
        f"- wake receiver cells: `{merged.get('wake_receiver_cell_count')}`",
        f"- tip receiver cells: `{merged.get('tip_receiver_cell_count')}`",
        f"- stitched TE-base faces: `{merged.get('te_base_stitched_face_count')}`",
        f"- exposed original span-cap faces: `{merged.get('remaining_exposed_original_span_cap_face_count')}`",
        f"- exposed original wake-cut faces: `{merged.get('remaining_exposed_original_wake_cut_face_count')}`",
        f"- non-positive candidate volumes: `{(merged.get('volume_quality') or {}).get('non_positive_volume_count')}`",
        f"- blockers: `{merged.get('blockers')}`",
        f"- engineering read: {summary['engineering_read']}",
        "",
        "Blocked claims:",
        "- full BL/core/farfield Gmsh mesh readiness",
        "- SU2 marker/readability readiness",
        "- medium/fine CFD ladder readiness",
        "- CL/CD/Cm interpretation",
        "- Baseline A drag or power truth",
    ]
    return "\n".join(lines) + "\n"


def _face_records(
    block: WingBoundaryLayerBlock,
    candidate: MergedVolumeCandidate,
) -> list[dict[str, Any]]:
    original_boundary_roles = {
        canonical_face(face.nodes): str(face.marker)
        for face in block.boundary_faces
    }
    edge_markers = boundary_edge_marker_map(block)
    records: list[dict[str, Any]] = []
    for cell in block.cells:
        for face in _hex_faces(cell.nodes):
            key = canonical_face(face)
            records.append(
                {
                    "key": key,
                    "nodes": tuple(face),
                    "source": "owned_bl_block",
                    "role": original_boundary_roles.get(key, "owned_bl_internal"),
                }
            )
    for cell in candidate.wake_receiver_cells:
        for face in receiver_cell_faces(cell, block):
            records.append(
                {
                    "key": canonical_face(face.nodes),
                    "nodes": tuple(face.nodes),
                    "source": "wake_receiver",
                    "role": face.role,
                }
            )
    for cell in candidate.materialized_tip_receiver.cells:
        for face in tip_receiver_cell_faces(cell):
            records.append(
                {
                    "key": canonical_face(face.nodes),
                    "nodes": tuple(face.nodes),
                    "source": "tip_receiver",
                    "role": classify_receiver_boundary_role(face, edge_markers),
                }
            )
    return records


def _stitched_te_base_face_keys(block: WingBoundaryLayerBlock) -> set[tuple[int, ...]]:
    from hpa_meshing.mesh_native.near_wall_block import (  # noqa: PLC0415
        build_boundary_layer_core_interface_surface,
    )

    pairing = summarize_te_base_pairing(
        block,
        build_boundary_layer_core_interface_surface(block),
    )
    if pairing.get("te_base_pairing_status") != "sharp_te_pairing_candidate":
        return set()
    keys: set[tuple[int, ...]] = set()
    for group in pairing.get("pair_groups", []):
        if not isinstance(group, Mapping):
            continue
        for face in group.get("faces", []):
            if isinstance(face, Mapping) and isinstance(face.get("nodes"), list):
                keys.add(canonical_face(face["nodes"]))
    return keys


def _removed_degenerate_receiver_base_face_keys(
    block: WingBoundaryLayerBlock,
    wake_cells: Sequence[ReceiverCell],
) -> set[tuple[int, ...]]:
    from hpa_meshing.mesh_native.near_wall_block import (  # noqa: PLC0415
        build_boundary_layer_core_interface_surface,
    )

    pairing = summarize_te_base_pairing(
        block,
        build_boundary_layer_core_interface_surface(block),
    )
    if pairing.get("te_base_pairing_status") != "sharp_te_pairing_candidate":
        return set()
    return {
        canonical_face(face.nodes)
        for cell in wake_cells
        for face in receiver_cell_faces(cell, block)
        if face.role == "receiver_base"
    }


def _volume_quality(
    block: WingBoundaryLayerBlock,
    candidate: MergedVolumeCandidate,
) -> dict[str, Any]:
    wake_volumes = [
        receiver_cell_volume(candidate.vertices, cell.nodes)
        for cell in candidate.wake_receiver_cells
    ]
    tip_volumes = [
        receiver_cell_volume(candidate.vertices, cell.nodes)
        for cell in candidate.materialized_tip_receiver.cells
    ]
    receiver_volumes = [*wake_volumes, *tip_volumes]
    non_positive_receiver = sum(1 for volume in receiver_volumes if volume <= 1.0e-14)
    return {
        "owned_bl_non_positive_estimated_volume_count": int(
            block.quality.get("non_positive_volume_count") or 0
        ),
        "receiver_non_positive_volume_count": non_positive_receiver,
        "non_positive_volume_count": int(
            block.quality.get("non_positive_volume_count") or 0
        )
        + non_positive_receiver,
        "min_receiver_volume_m3": min(receiver_volumes) if receiver_volumes else 0.0,
        "max_receiver_volume_m3": max(receiver_volumes) if receiver_volumes else 0.0,
    }


def _external_boundary_topology(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    edge_counts: dict[tuple[int, int], int] = {}
    role_counts: dict[str, int] = {}
    for row in rows:
        nodes = [int(node) for node in row.get("nodes", [])]
        for left, right in zip(nodes, [*nodes[1:], nodes[0]]):
            edge = tuple(sorted((left, right)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    bad_edges = {
        edge: count
        for edge, count in edge_counts.items()
        if count != 2
    }
    for row in rows:
        nodes = [int(node) for node in row.get("nodes", [])]
        role = str(row.get("role") or "unknown")
        for left, right in zip(nodes, [*nodes[1:], nodes[0]]):
            edge = tuple(sorted((left, right)))
            if edge in bad_edges:
                role_counts[role] = role_counts.get(role, 0) + 1
    return {
        "status": "watertight" if not bad_edges else "not_watertight",
        "edge_count": len(edge_counts),
        "bad_edge_count": len(bad_edges),
        "bad_edge_incidence_counts": dict(sorted(_counts(bad_edges.values()).items())),
        "bad_edge_role_touch_counts": dict(sorted(role_counts.items())),
    }


def _hex_faces(nodes: Sequence[int]) -> tuple[tuple[int, int, int, int], ...]:
    a, b, c, d, e, f, g, h = tuple(int(node) for node in nodes)
    return (
        (a, b, c, d),
        (e, f, g, h),
        (a, e, f, b),
        (b, f, g, c),
        (c, g, h, d),
        (d, h, e, a),
    )


def _counts(values: Sequence[Any]) -> dict[Any, int]:
    counts: dict[Any, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
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
    merged = summary["merged_volume"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "merged_volume_status": merged["status"],
                "volume_cell_count": merged["volume_cell_count"],
                "remaining_exposed_original_span_cap_face_count": merged[
                    "remaining_exposed_original_span_cap_face_count"
                ],
                "remaining_exposed_original_wake_cut_face_count": merged[
                    "remaining_exposed_original_wake_cut_face_count"
                ],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
