#!/usr/bin/env python3
"""Gate stitched wake ownership before any BL/core CFD handoff.

WO-006V showed that the wake receiver can internalize most BL wake-cut faces.
WO-006W showed that the remaining TE-base faces are sharp-TE coincident seam
pairs on Baseline A. This probe combines those facts into a strict accounting
gate: every BL wake-cut face must be either matched by the receiver or explicitly
stitched as a sharp-TE seam. It still leaves span-cap ownership pending and does
not promote any coefficient evidence.
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
from probe_wo006v_wake_receiver_topology import summarize_wake_receiver_topology  # noqa: E402
from probe_wo006w_te_base_pairing import summarize_te_base_pairing  # noqa: E402
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006x_stitched_wake_handoff_gate"


def evaluate_stitched_wake_handoff_gate(
    block: WingBoundaryLayerBlock,
    core_interface: SurfaceMesh,
) -> dict[str, Any]:
    wake = summarize_wake_receiver_topology(block, core_interface)
    pairing = summarize_te_base_pairing(block, core_interface)

    bl_wake_count = int(wake.get("bl_wake_cut_boundary_face_count") or 0)
    receiver_matched_bl = int(wake.get("matched_bl_wake_cut_face_count") or 0)
    core_wake_count = int(wake.get("core_wake_cut_face_count") or 0)
    receiver_matched_core = int(wake.get("matched_core_wake_cut_face_count") or 0)
    pairable = pairing.get("te_base_pairing_status") == "sharp_te_pairing_candidate"
    te_base_count = int(pairing.get("te_base_face_count") or 0)
    te_base_stitched = int(pairing.get("paired_te_base_face_count") or 0) if pairable else 0
    remaining_bl = max(0, bl_wake_count - receiver_matched_bl - te_base_stitched)
    remaining_core = max(0, core_wake_count - receiver_matched_core)

    blockers: list[str] = []
    if not pairable and te_base_count:
        blockers.append("te_base_not_pairable")
    if remaining_bl:
        blockers.append("unowned_bl_wake_cut_faces")
    if remaining_core:
        blockers.append("unmatched_core_wake_cut_faces")

    wake_accounting_pass = not blockers
    status = (
        "wake_stitch_accounting_pass_span_caps_pending"
        if wake_accounting_pass
        else "wake_stitch_accounting_blocked"
    )
    return {
        "schema_version": "wo006x_stitched_wake_handoff_gate.v1",
        "status": status,
        "wake_accounting_pass": wake_accounting_pass,
        "blockers": blockers,
        "bl_wake_cut_face_count": bl_wake_count,
        "receiver_matched_bl_wake_cut_face_count": receiver_matched_bl,
        "te_base_face_count": te_base_count,
        "te_base_stitched_face_count": te_base_stitched,
        "remaining_unowned_bl_wake_cut_face_count": remaining_bl,
        "core_wake_cut_face_count": core_wake_count,
        "receiver_matched_core_wake_cut_face_count": receiver_matched_core,
        "remaining_unmatched_core_wake_cut_face_count": remaining_core,
        "span_cap_status": "pending",
        "coefficient_interpretable": False,
        "wake_receiver_status": wake.get("wake_receiver_status"),
        "te_base_pairing_status": pairing.get("te_base_pairing_status"),
        "engineering_read": engineering_read(
            wake_accounting_pass=wake_accounting_pass,
            remaining_bl=remaining_bl,
            remaining_core=remaining_core,
            pairable=pairable,
        ),
    }


def build_probe_summary(gate: Mapping[str, Any]) -> dict[str, Any]:
    pass_wake = gate.get("wake_accounting_pass") is True
    return {
        "schema_version": "wo006x_stitched_wake_handoff_probe.v1",
        "verdict": (
            "stitched_wake_accounting_ready_span_caps_pending"
            if pass_wake
            else "stitched_wake_accounting_blocked"
        ),
        "stitched_wake_gate": dict(gate),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "full BL/core handoff readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": gate.get("engineering_read"),
    }


def engineering_read(
    *,
    wake_accounting_pass: bool,
    remaining_bl: int,
    remaining_core: int,
    pairable: bool,
) -> str:
    if wake_accounting_pass:
        return (
            "Wake ownership can be fully accounted for by receiver matching plus "
            "explicit sharp-TE seam stitching. This is not a final handoff because "
            "span-cap ownership and merged mesh quality still need separate gates."
        )
    return (
        "Wake ownership is still blocked: "
        f"remaining_bl={remaining_bl}, remaining_core={remaining_core}, "
        f"te_base_pairable={pairable}. Do not build CFD coefficients from this route."
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
    gate = evaluate_stitched_wake_handoff_gate(block, core_interface)
    summary = build_probe_summary(gate)
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
    write_csv(output_dir / "gate_accounting.csv", [gate])
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    gate = summary["stitched_wake_gate"]
    lines = [
        "# WO-006X Stitched Wake Handoff Gate",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- wake gate status: `{gate.get('status')}`",
        f"- BL wake-cut faces: `{gate.get('bl_wake_cut_face_count')}`",
        f"- receiver-matched BL wake-cut faces: `{gate.get('receiver_matched_bl_wake_cut_face_count')}`",
        f"- TE-base stitched faces: `{gate.get('te_base_stitched_face_count')}`",
        f"- remaining unowned BL wake-cut faces: `{gate.get('remaining_unowned_bl_wake_cut_face_count')}`",
        f"- receiver-matched core wake-cut faces: `{gate.get('receiver_matched_core_wake_cut_face_count')}` / `{gate.get('core_wake_cut_face_count')}`",
        f"- span-cap status: `{gate.get('span_cap_status')}`",
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
    gate = summary["stitched_wake_gate"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "wake_gate_status": gate["status"],
                "remaining_unowned_bl_wake_cut_face_count": gate[
                    "remaining_unowned_bl_wake_cut_face_count"
                ],
                "span_cap_status": gate["span_cap_status"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
