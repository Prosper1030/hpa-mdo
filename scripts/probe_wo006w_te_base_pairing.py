#!/usr/bin/env python3
"""Probe whether remaining TE-base wake-cut faces are stitchable pairs.

WO-006V narrowed the wake receiver blocker to wall-touching TE-base faces.
For a sharp trailing edge, those upper/lower wake-base faces should be
geometrically coincident wake-seam pairs, not physical walls. This probe checks
that geometry explicitly before any stitching or SU2 ladder is allowed.
"""

from __future__ import annotations

import argparse
import csv
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
    build_boundary_layer_core_interface_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import SurfaceMesh, Vertex  # noqa: E402
from probe_wo006v_wake_receiver_topology import (  # noqa: E402
    build_wake_receiver_cells,
    receiver_cell_faces,
    summarize_wake_receiver_topology,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006w_te_base_pairing_probe"
DEFAULT_COORD_TOLERANCE_M = 1.0e-9
DEFAULT_AREA_TOLERANCE_M2 = 1.0e-14


def summarize_te_base_pairing(
    block: WingBoundaryLayerBlock,
    core_interface: SurfaceMesh,
    *,
    coordinate_tolerance_m: float = DEFAULT_COORD_TOLERANCE_M,
    area_tolerance_m2: float = DEFAULT_AREA_TOLERANCE_M2,
) -> dict[str, Any]:
    wake_receiver = summarize_wake_receiver_topology(block, core_interface)
    te_base_faces = [
        tuple(face["nodes"])
        for face in wake_receiver.get("remaining_bl_wake_cut_faces", [])
        if isinstance(face, Mapping)
    ]
    groups = group_faces_by_geometry(
        block.vertices,
        te_base_faces,
        coordinate_tolerance_m=coordinate_tolerance_m,
    )
    paired_face_count = sum((len(group["faces"]) // 2) * 2 for group in groups)
    coincident_pair_count = sum(len(group["faces"]) // 2 for group in groups)
    unpaired_face_count = len(te_base_faces) - paired_face_count

    receiver_base_faces = [
        face.nodes
        for cell in build_wake_receiver_cells(block)
        for face in receiver_cell_faces(cell, block)
        if face.role == "receiver_base"
    ]
    receiver_base_areas = [
        polygon_area_3d(block.vertices, face) for face in receiver_base_faces
    ]
    max_receiver_base_area = max(receiver_base_areas, default=0.0)
    degenerate_base_count = sum(
        1 for area in receiver_base_areas if area <= area_tolerance_m2
    )
    pairing_candidate = (
        bool(te_base_faces)
        and unpaired_face_count == 0
        and max_receiver_base_area <= area_tolerance_m2
    )
    status = (
        "sharp_te_pairing_candidate" if pairing_candidate else "te_base_geometry_open"
    )
    return {
        "schema_version": "wo006w_te_base_pairing.v1",
        "te_base_pairing_status": status,
        "te_base_face_count": len(te_base_faces),
        "coincident_pair_count": coincident_pair_count,
        "paired_te_base_face_count": paired_face_count,
        "unpaired_te_base_face_count": unpaired_face_count,
        "receiver_base_face_count": len(receiver_base_faces),
        "receiver_base_degenerate_face_count": degenerate_base_count,
        "max_receiver_base_area_m2": max_receiver_base_area,
        "coordinate_tolerance_m": coordinate_tolerance_m,
        "area_tolerance_m2": area_tolerance_m2,
        "wake_receiver_status": wake_receiver.get("wake_receiver_status"),
        "wake_receiver_counts": {
            "matched_bl_wake_cut_face_count": wake_receiver.get(
                "matched_bl_wake_cut_face_count"
            ),
            "remaining_bl_wake_cut_face_count": wake_receiver.get(
                "remaining_bl_wake_cut_face_count"
            ),
            "matched_core_wake_cut_face_count": wake_receiver.get(
                "matched_core_wake_cut_face_count"
            ),
            "remaining_receiver_base_face_count": wake_receiver.get(
                "remaining_receiver_base_face_count"
            ),
        },
        "pair_groups": groups,
        "engineering_read": engineering_read(
            pairing_candidate=pairing_candidate,
            unpaired_face_count=unpaired_face_count,
            max_receiver_base_area=max_receiver_base_area,
        ),
    }


def group_faces_by_geometry(
    vertices: Sequence[Vertex],
    faces: Sequence[Sequence[int]],
    *,
    coordinate_tolerance_m: float,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[tuple[int, int, int], ...], list[Sequence[int]]] = {}
    for face in faces:
        signature = geometric_face_signature(
            vertices,
            face,
            coordinate_tolerance_m=coordinate_tolerance_m,
        )
        grouped.setdefault(signature, []).append(tuple(int(node) for node in face))
    rows: list[dict[str, Any]] = []
    for index, (signature, grouped_faces) in enumerate(sorted(grouped.items())):
        rows.append(
            {
                "group_id": index,
                "face_count": len(grouped_faces),
                "pair_count": len(grouped_faces) // 2,
                "unpaired_face_count": len(grouped_faces) % 2,
                "signature": json.dumps(signature),
                "faces": [
                    {"nodes": list(face)}
                    for face in grouped_faces
                ],
            }
        )
    return rows


def geometric_face_signature(
    vertices: Sequence[Vertex],
    face: Sequence[int],
    *,
    coordinate_tolerance_m: float,
) -> tuple[tuple[int, int, int], ...]:
    if coordinate_tolerance_m <= 0.0:
        raise ValueError("coordinate_tolerance_m must be positive")
    quantized = []
    for node in face:
        vertex = vertices[int(node)]
        quantized.append(
            tuple(
                int(round(float(component) / coordinate_tolerance_m))
                for component in vertex
            )
        )
    return tuple(sorted(quantized))


def polygon_area_3d(vertices: Sequence[Vertex], face: Sequence[int]) -> float:
    if len(face) < 3:
        return 0.0
    anchor = vertices[int(face[0])]
    area = 0.0
    for left, right in zip(face[1:-1], face[2:]):
        area += triangle_area_3d(anchor, vertices[int(left)], vertices[int(right)])
    return area


def triangle_area_3d(a: Vertex, b: Vertex, c: Vertex) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return 0.5 * math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)


def build_probe_summary(pairing: Mapping[str, Any]) -> dict[str, Any]:
    candidate = pairing.get("te_base_pairing_status") == "sharp_te_pairing_candidate"
    return {
        "schema_version": "wo006w_te_base_pairing_probe.v1",
        "verdict": (
            "te_base_pairing_candidate_not_handoff"
            if candidate
            else "te_base_pairing_blocked"
        ),
        "te_base_pairing": dict(pairing),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "BL/core handoff readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": pairing.get("engineering_read"),
    }


def engineering_read(
    *,
    pairing_candidate: bool,
    unpaired_face_count: int,
    max_receiver_base_area: float,
) -> str:
    if pairing_candidate:
        return (
            "The remaining TE-base wake-cut faces are coincident sharp-TE wake "
            "seam pairs and the receiver base is degenerate. The next repair can "
            "try explicit seam stitching/removal, but this is not yet a mesh "
            "handoff or CFD ladder."
        )
    return (
        "The remaining TE-base wake-cut faces are not a clean sharp-TE pairing "
        f"candidate: unpaired={unpaired_face_count}, "
        f"max_receiver_base_area_m2={max_receiver_base_area:.6e}. Do not stitch "
        "blindly or promote coefficients."
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
    pairing = summarize_te_base_pairing(block, core_interface)
    summary = build_probe_summary(pairing)
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
    write_csv(output_dir / "te_base_pair_groups.csv", pairing["pair_groups"])
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    pairing = summary["te_base_pairing"]
    lines = [
        "# WO-006W TE-Base Wake Pairing Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- pairing status: `{pairing.get('te_base_pairing_status')}`",
        f"- TE-base faces: `{pairing.get('te_base_face_count')}`",
        f"- coincident pairs: `{pairing.get('coincident_pair_count')}`",
        f"- unpaired TE-base faces: `{pairing.get('unpaired_te_base_face_count')}`",
        f"- receiver base faces: `{pairing.get('receiver_base_face_count')}`",
        f"- max receiver base area (m^2): `{pairing.get('max_receiver_base_area_m2')}`",
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
    pairing = summary["te_base_pairing"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "te_base_pairing_status": pairing["te_base_pairing_status"],
                "te_base_face_count": pairing["te_base_face_count"],
                "coincident_pair_count": pairing["coincident_pair_count"],
                "unpaired_te_base_face_count": pairing["unpaired_te_base_face_count"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
