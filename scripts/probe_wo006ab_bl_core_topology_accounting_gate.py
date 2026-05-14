#!/usr/bin/env python3
"""Combine WO-006 wall, wake, span-cap, and outer-interface topology accounting.

This gate aggregates the current topology evidence into one prompt-to-artifact
checkpoint. It may say the topology accounting is ready, but it still blocks
CFD because no real merged BL+core mesh, quality gate, SU2 marker/readability
gate, y+ postprocess, or solver ladder exists.
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
    build_boundary_layer_wall_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import SurfaceMesh, validate_surface_mesh  # noqa: E402
from probe_wo006aa_tip_receiver_topology import summarize_tip_receiver_topology  # noqa: E402
from probe_wo006v_wake_receiver_topology import canonical_face  # noqa: E402
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


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006ab_bl_core_topology_accounting_gate"


def summarize_wall_surface(wall_surface: SurfaceMesh) -> dict[str, Any]:
    try:
        validate_surface_mesh(wall_surface, required_markers=("wing_wall",))
    except ValueError as exc:
        return {
            "status": "invalid",
            "marker_counts": wall_surface.marker_counts(),
            "metadata": wall_surface.metadata,
            "error": str(exc),
        }
    return {
        "status": "watertight",
        "marker_counts": wall_surface.marker_counts(),
        "metadata": wall_surface.metadata,
        "error": None,
    }


def summarize_outer_interface_accounting(
    block: WingBoundaryLayerBlock,
    core_interface: SurfaceMesh,
) -> dict[str, Any]:
    bl_outer_faces = [
        tuple(face.nodes) for face in block.boundary_faces if face.marker == "bl_outer_interface"
    ]
    core_outer_faces = [
        tuple(face.nodes) for face in core_interface.faces if face.marker == "bl_outer_interface"
    ]
    bl_outer_keys = {canonical_face(face) for face in bl_outer_faces}
    core_outer_keys = {canonical_face(face) for face in core_outer_faces}
    matched_bl = [face for face in bl_outer_faces if canonical_face(face) in core_outer_keys]
    matched_core = [face for face in core_outer_faces if canonical_face(face) in bl_outer_keys]
    remaining_bl = len(bl_outer_faces) - len(matched_bl)
    remaining_core = len(core_outer_faces) - len(matched_core)
    return {
        "schema_version": "wo006ab_outer_interface_accounting.v1",
        "status": "pass" if remaining_bl == 0 and remaining_core == 0 else "fail",
        "bl_outer_interface_face_count": len(bl_outer_faces),
        "core_outer_interface_face_count": len(core_outer_faces),
        "matched_bl_outer_interface_face_count": len(matched_bl),
        "matched_core_outer_interface_face_count": len(matched_core),
        "remaining_bl_outer_interface_face_count": remaining_bl,
        "remaining_core_outer_interface_face_count": remaining_core,
    }


def evaluate_topology_accounting(
    *,
    wall_surface: Mapping[str, Any],
    wake_gate: Mapping[str, Any],
    tip_receiver: Mapping[str, Any],
    outer_interface: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    wall_status = str(wall_surface.get("status") or "")
    wake_pass = wake_gate.get("wake_accounting_pass") is True
    tip_pass = tip_receiver.get("tip_receiver_status") == "span_cap_receiver_accounting_ready"
    outer_pass = outer_interface.get("status") == "pass"
    if wall_status != "watertight":
        blockers.append("physical_wall_surface_not_watertight")
    if not wake_pass:
        blockers.append("wake_accounting_not_pass")
    if not tip_pass:
        blockers.append("tip_receiver_accounting_not_pass")
    if not outer_pass:
        blockers.append("outer_interface_accounting_not_pass")

    accounting_ready = not blockers
    post_accounting_blockers = [
        "receiver_geometry_not_materialized",
        "final_merged_mesh_missing",
        "merged_mesh_quality_not_run",
        "su2_marker_readability_not_run",
        "near_wall_yplus_not_postprocessed",
        "solver_ladder_not_run",
    ]
    return {
        "schema_version": "wo006ab_bl_core_topology_accounting.v1",
        "status": (
            "topology_accounting_ready_geometry_mesh_pending"
            if accounting_ready
            else "topology_accounting_blocked"
        ),
        "wall_surface_status": wall_status,
        "wake_accounting_pass": wake_pass,
        "tip_receiver_accounting_pass": tip_pass,
        "outer_interface_accounting_pass": outer_pass,
        "blockers": [*blockers, *post_accounting_blockers],
        "accounted_boundary_sets": {
            "physical_wall": wall_surface.get("marker_counts"),
            "wake_gate": {
                "bl_wake_cut_face_count": wake_gate.get("bl_wake_cut_face_count"),
                "remaining_unowned_bl_wake_cut_face_count": wake_gate.get(
                    "remaining_unowned_bl_wake_cut_face_count"
                ),
            },
            "tip_receiver": {
                "bl_span_cap_face_count": tip_receiver.get("bl_span_cap_face_count"),
                "remaining_bl_span_cap_face_count": tip_receiver.get(
                    "remaining_bl_span_cap_face_count"
                ),
            },
            "outer_interface": outer_interface,
        },
        "engineering_read": (
            "Topology ownership accounting is ready, but only as a pre-mesh contract. "
            "The receiver geometry must be materialized and a real merged BL+core SU2 "
            "mesh must pass quality, marker/readability, y+, and solver-ladder gates."
            if accounting_ready
            else "Topology ownership accounting is still blocked; do not attempt CFD."
        ),
    }


def build_probe_summary(*, topology_accounting: Mapping[str, Any]) -> dict[str, Any]:
    ready = (
        topology_accounting.get("status")
        == "topology_accounting_ready_geometry_mesh_pending"
    )
    return {
        "schema_version": "wo006ab_bl_core_topology_accounting_probe.v1",
        "verdict": (
            "topology_accounting_ready_not_handoff"
            if ready
            else "topology_accounting_blocked"
        ),
        "topology_accounting": dict(topology_accounting),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "full BL/core handoff readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": topology_accounting.get("engineering_read"),
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
    summary = build_probe_summary(topology_accounting=topology_accounting)
    summary.update(
        {
            "output_dir": str(output_dir),
            "geometry_source": str(geometry.section_table_path),
            "points_per_side": int(points_per_side),
            "spanwise_subdivisions": int(spanwise_subdivisions),
            "wall_surface": wall_surface,
            "stitched_wake_gate": wake_gate,
            "tip_receiver": tip_receiver,
            "outer_interface": outer_interface,
            "owned_bl_block": {
                "cell_count": len(block.cells),
                "boundary_marker_counts": block.boundary_marker_counts(),
                "quality": block.quality,
            },
            "core_interface_marker_counts": core_interface.marker_counts(),
        }
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "topology_accounting.csv", topology_accounting_rows(summary))
    (output_dir / "topology_accounting_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def topology_accounting_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    accounting = summary["topology_accounting"]
    wake = summary["stitched_wake_gate"]
    tip = summary["tip_receiver"]
    outer = summary["outer_interface"]
    return [
        {
            "surface_set": "physical_wall",
            "status": accounting.get("wall_surface_status"),
            "input_faces": "",
            "matched_faces": "",
            "remaining_faces": "",
            "handoff_status": "not_handoff",
        },
        {
            "surface_set": "wake_cut",
            "status": "pass" if accounting.get("wake_accounting_pass") else "fail",
            "input_faces": wake.get("bl_wake_cut_face_count"),
            "matched_faces": int(wake.get("receiver_matched_bl_wake_cut_face_count") or 0)
            + int(wake.get("te_base_stitched_face_count") or 0),
            "remaining_faces": wake.get("remaining_unowned_bl_wake_cut_face_count"),
            "handoff_status": "not_handoff",
        },
        {
            "surface_set": "span_cap_tip_receiver",
            "status": "pass" if accounting.get("tip_receiver_accounting_pass") else "fail",
            "input_faces": tip.get("bl_span_cap_face_count"),
            "matched_faces": tip.get("matched_bl_span_cap_face_count"),
            "remaining_faces": tip.get("remaining_bl_span_cap_face_count"),
            "handoff_status": "not_handoff",
        },
        {
            "surface_set": "bl_outer_interface",
            "status": outer.get("status"),
            "input_faces": outer.get("bl_outer_interface_face_count"),
            "matched_faces": outer.get("matched_bl_outer_interface_face_count"),
            "remaining_faces": outer.get("remaining_bl_outer_interface_face_count"),
            "handoff_status": "not_handoff",
        },
    ]


def render_report(summary: Mapping[str, Any]) -> str:
    accounting = summary["topology_accounting"]
    lines = [
        "# WO-006AB BL/Core Topology Accounting Gate",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- accounting status: `{accounting.get('status')}`",
        f"- wall surface status: `{accounting.get('wall_surface_status')}`",
        f"- wake accounting pass: `{accounting.get('wake_accounting_pass')}`",
        f"- tip receiver accounting pass: `{accounting.get('tip_receiver_accounting_pass')}`",
        f"- outer interface accounting pass: `{accounting.get('outer_interface_accounting_pass')}`",
        f"- blockers: `{accounting.get('blockers')}`",
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
    accounting = summary["topology_accounting"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "accounting_status": accounting["status"],
                "blockers": accounting["blockers"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
