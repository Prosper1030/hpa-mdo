#!/usr/bin/env python3
"""Probe WO-006 owned-BL/core envelope topology before more meshing.

This is a topology diagnostic, not CFD completion evidence. It inspects the
owned boundary-layer block boundary and identifies why the tempting "all
non-wall BL boundary is the core inner surface" route is not watertight.
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
    build_boundary_layer_core_interface_surface,
    build_wing_boundary_layer_block,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006u_bl_core_envelope_topology_probe"


@dataclass(frozen=True)
class SimpleFace:
    nodes: tuple[int, ...]
    marker: str


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
    boundary_faces = [
        SimpleFace(tuple(face.nodes), str(face.marker))
        for face in block.boundary_faces
    ]
    full_non_wall = summarize_candidate_surface_topology(
        candidate_faces=[face for face in boundary_faces if face.marker != "wing_wall"],
        all_boundary_faces=boundary_faces,
        candidate_id="full_non_wall_boundary",
    )
    core_interface = build_boundary_layer_core_interface_surface(block)
    core_interface_summary = summarize_candidate_surface_topology(
        candidate_faces=[
            SimpleFace(tuple(face.nodes), str(face.marker))
            for face in core_interface.faces
        ],
        all_boundary_faces=boundary_faces,
        candidate_id="current_core_interface_surface",
    )
    summary = build_probe_summary(
        full_non_wall,
        core_interface_summary=core_interface_summary,
    )
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
    write_csv(output_dir / "bad_edges_full_non_wall.csv", full_non_wall["bad_edges"])
    write_csv(output_dir / "bad_edges_core_interface.csv", core_interface_summary["bad_edges"])
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def summarize_candidate_surface_topology(
    *,
    candidate_faces: Sequence[SimpleFace],
    all_boundary_faces: Sequence[SimpleFace],
    candidate_id: str = "candidate",
) -> dict[str, Any]:
    candidate_edge_markers = edge_marker_map(candidate_faces)
    all_edge_markers = edge_marker_map(all_boundary_faces)
    bad_edges: list[dict[str, Any]] = []
    for edge, candidate_markers in sorted(candidate_edge_markers.items()):
        if len(candidate_markers) == 2:
            continue
        all_markers = all_edge_markers.get(edge, [])
        classification = classify_candidate_edge_gap(
            candidate_markers=candidate_markers,
            all_boundary_markers=all_markers,
        )
        bad_edges.append(
            {
                "edge_nodes": list(edge),
                "candidate_markers": list(candidate_markers),
                "all_boundary_markers": list(all_markers),
                "marker_combo": marker_combo(candidate_markers),
                "classification": classification,
            }
        )
    class_counts: dict[str, int] = {}
    marker_counts: dict[str, int] = {}
    for row in bad_edges:
        class_counts[str(row["classification"])] = class_counts.get(str(row["classification"]), 0) + 1
        marker_counts[str(row["marker_combo"])] = marker_counts.get(str(row["marker_combo"]), 0) + 1
    return {
        "candidate_id": candidate_id,
        "status": "watertight" if not bad_edges else "not_watertight",
        "face_count": len(candidate_faces),
        "edge_count": len(candidate_edge_markers),
        "bad_edge_count": len(bad_edges),
        "bad_edge_class_counts": dict(sorted(class_counts.items())),
        "bad_edge_marker_combo_counts": dict(sorted(marker_counts.items())),
        "bad_edges": bad_edges,
    }


def classify_candidate_edge_gap(
    *,
    candidate_markers: Sequence[str],
    all_boundary_markers: Sequence[str],
) -> str:
    if len(candidate_markers) > 2:
        return "candidate_nonmanifold_edge"
    if len(candidate_markers) == 2:
        return "candidate_edge_paired"
    if "wing_wall" in set(all_boundary_markers):
        return "candidate_open_edge_touches_wing_wall"
    if not candidate_markers:
        return "candidate_edge_missing"
    return "candidate_open_edge_without_wall_contact"


def edge_marker_map(faces: Sequence[SimpleFace]) -> dict[tuple[int, int], list[str]]:
    edge_map: dict[tuple[int, int], list[str]] = {}
    for face in faces:
        nodes = list(face.nodes)
        for left, right in zip(nodes, [*nodes[1:], nodes[0]]):
            edge = tuple(sorted((int(left), int(right))))
            edge_map.setdefault(edge, []).append(str(face.marker))
    return edge_map


def marker_combo(markers: Sequence[str]) -> str:
    return "+".join(sorted(str(marker) for marker in markers)) or "none"


def build_probe_summary(
    full_non_wall_summary: Mapping[str, Any],
    *,
    core_interface_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_pass = full_non_wall_summary.get("status") == "watertight"
    verdict = (
        "bl_core_envelope_candidate_watertight"
        if candidate_pass
        else "bl_core_envelope_topology_blocked"
    )
    return {
        "schema_version": "wo006u_bl_core_envelope_topology_probe.v1",
        "verdict": verdict,
        "candidate_case_ids": (
            [str(full_non_wall_summary.get("candidate_id"))] if candidate_pass else []
        ),
        "full_non_wall_boundary": full_non_wall_summary,
        "current_core_interface_surface": core_interface_summary,
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "engineering_read": engineering_read(full_non_wall_summary),
    }


def engineering_read(full_non_wall_summary: Mapping[str, Any]) -> str:
    if full_non_wall_summary.get("status") == "watertight":
        return (
            "The full non-wall BL boundary is watertight as a topology candidate. "
            "It still needs Gmsh/SU2 quality and readability gates before CFD."
        )
    class_counts = full_non_wall_summary.get("bad_edge_class_counts") or {}
    if int(class_counts.get("candidate_open_edge_touches_wing_wall") or 0) > 0:
        return (
            "The full non-wall BL boundary opens along edges that still touch the "
            "physical wing wall. The next repair should create an owned TE/wake "
            "receiver/envelope instead of sending wall-touching wake connector faces "
            "directly to the core mesh."
        )
    return (
        "The BL/core envelope candidate is not watertight. Repair the candidate "
        "surface topology before any medium/fine SU2 ladder."
    )


def render_report(summary: Mapping[str, Any]) -> str:
    full = summary["full_non_wall_boundary"]
    current = summary.get("current_core_interface_surface") or {}
    lines = [
        "# WO-006U BL/Core Envelope Topology Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- full non-wall status: `{full.get('status')}`",
        f"- full non-wall bad edges: `{full.get('bad_edge_count')}`",
        f"- current core-interface status: `{current.get('status')}`",
        f"- current core-interface bad edges: `{current.get('bad_edge_count')}`",
        f"- engineering read: {summary['engineering_read']}",
        "",
        "## Full Non-Wall Candidate",
        "",
        f"- bad edge class counts: `{full.get('bad_edge_class_counts')}`",
        f"- bad edge marker combo counts: `{full.get('bad_edge_marker_combo_counts')}`",
        "",
        "Blocked claims:",
        "- BL/y+ viscous drag calibration",
        "- medium/fine CFD ladder readiness",
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
                "full_non_wall_bad_edge_count": summary["full_non_wall_boundary"]["bad_edge_count"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
