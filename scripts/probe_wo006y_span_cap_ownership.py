#!/usr/bin/env python3
"""Probe span-cap ownership after wake accounting passes.

WO-006X accounts for wake-cut faces, but the owned BL block still has endpoint
span caps that are not a final solver boundary contract. This probe classifies
those faces against neighboring markers and the core-interface span caps before
any merged mesh or CFD coefficient is promoted.
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
    build_boundary_layer_core_interface_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import SurfaceMesh  # noqa: E402
from probe_wo006v_wake_receiver_topology import (  # noqa: E402
    boundary_edge_marker_map,
    canonical_face,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006y_span_cap_ownership_probe"


def summarize_span_cap_ownership(
    block: WingBoundaryLayerBlock,
    core_interface: SurfaceMesh,
) -> dict[str, Any]:
    bl_span_faces = [
        tuple(face.nodes) for face in block.boundary_faces if face.marker == "span_cap"
    ]
    core_span_faces = [
        tuple(face.nodes) for face in core_interface.faces if face.marker == "span_cap"
    ]
    core_span_keys = {canonical_face(face) for face in core_span_faces}
    edge_markers = boundary_edge_marker_map(block)

    rows: list[dict[str, Any]] = []
    for index, face in enumerate(bl_span_faces):
        adjacent_markers = markers_touching_face(face, edge_markers)
        rows.append(
            {
                "face_index": index,
                "nodes": list(face),
                "native_matches_core_span_cap": canonical_face(face) in core_span_keys,
                "touches_wing_wall": "wing_wall" in adjacent_markers,
                "touches_bl_outer_interface": "bl_outer_interface" in adjacent_markers,
                "touches_wake_cut": "wake_cut" in adjacent_markers,
                "adjacent_markers": sorted(adjacent_markers),
            }
        )

    native_matched = sum(1 for row in rows if row["native_matches_core_span_cap"])
    wall_touching = sum(1 for row in rows if row["touches_wing_wall"])
    outer_touching = sum(1 for row in rows if row["touches_bl_outer_interface"])
    wake_touching = sum(1 for row in rows if row["touches_wake_cut"])
    blocked = native_matched != len(bl_span_faces)
    return {
        "schema_version": "wo006y_span_cap_ownership.v1",
        "span_cap_status": (
            "span_cap_ownership_blocked" if blocked else "span_cap_native_match"
        ),
        "bl_span_cap_face_count": len(bl_span_faces),
        "core_span_cap_face_count": len(core_span_faces),
        "native_matched_span_cap_face_count": native_matched,
        "unmatched_bl_span_cap_face_count": len(bl_span_faces) - native_matched,
        "wall_touching_span_cap_face_count": wall_touching,
        "outer_interface_touching_span_cap_face_count": outer_touching,
        "wake_touching_span_cap_face_count": wake_touching,
        "coefficient_interpretable": False,
        "span_cap_rows": rows,
        "engineering_read": engineering_read(
            bl_span_count=len(bl_span_faces),
            core_span_count=len(core_span_faces),
            native_matched=native_matched,
            wall_touching=wall_touching,
        ),
    }


def markers_touching_face(
    face: Sequence[int],
    edge_markers: Mapping[tuple[int, int], Sequence[str]],
) -> set[str]:
    node_list = [int(node) for node in face]
    markers: set[str] = set()
    for left, right in zip(node_list, [*node_list[1:], node_list[0]]):
        markers.update(edge_markers.get(tuple(sorted((left, right))), ()))
    markers.discard("span_cap")
    return markers


def build_probe_summary(span_cap: Mapping[str, Any]) -> dict[str, Any]:
    native_match = span_cap.get("span_cap_status") == "span_cap_native_match"
    return {
        "schema_version": "wo006y_span_cap_ownership_probe.v1",
        "verdict": (
            "span_cap_native_match_not_handoff"
            if native_match
            else "span_cap_ownership_blocked"
        ),
        "span_cap_ownership": dict(span_cap),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "full BL/core handoff readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": span_cap.get("engineering_read"),
    }


def engineering_read(
    *,
    bl_span_count: int,
    core_span_count: int,
    native_matched: int,
    wall_touching: int,
) -> str:
    if native_matched == bl_span_count:
        return (
            "BL span-cap faces natively match the core span-cap faces. This still "
            "needs final marker/quality/readability gates before CFD."
        )
    return (
        "BL span-cap faces do not natively match the triangulated core span caps "
        f"({native_matched}/{bl_span_count} matched, core_span={core_span_count}). "
        f"{wall_touching} BL span-cap faces touch wing_wall, so this needs an "
        "explicit tip/span-cap ownership policy rather than a blind SU2 boundary."
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
    span_cap = summarize_span_cap_ownership(block, core_interface)
    summary = build_probe_summary(span_cap)
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
    write_csv(output_dir / "span_cap_faces.csv", span_cap["span_cap_rows"])
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    span_cap = summary["span_cap_ownership"]
    lines = [
        "# WO-006Y Span-Cap Ownership Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- span-cap status: `{span_cap.get('span_cap_status')}`",
        f"- BL span-cap faces: `{span_cap.get('bl_span_cap_face_count')}`",
        f"- core span-cap faces: `{span_cap.get('core_span_cap_face_count')}`",
        f"- native matched BL span-cap faces: `{span_cap.get('native_matched_span_cap_face_count')}`",
        f"- wall-touching BL span-cap faces: `{span_cap.get('wall_touching_span_cap_face_count')}`",
        f"- outer-interface-touching BL span-cap faces: `{span_cap.get('outer_interface_touching_span_cap_face_count')}`",
        f"- wake-touching BL span-cap faces: `{span_cap.get('wake_touching_span_cap_face_count')}`",
        f"- engineering read: {summary['engineering_read']}",
        "",
        "Blocked claims:",
        "- full BL/core handoff readiness",
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
    span_cap = summary["span_cap_ownership"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "span_cap_status": span_cap["span_cap_status"],
                "bl_span_cap_face_count": span_cap["bl_span_cap_face_count"],
                "native_matched_span_cap_face_count": span_cap[
                    "native_matched_span_cap_face_count"
                ],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
