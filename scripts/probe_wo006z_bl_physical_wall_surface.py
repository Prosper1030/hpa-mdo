#!/usr/bin/env python3
"""Probe WO-006Z BL physical wall ownership before BL/core handoff.

This is surface-ownership evidence, not CFD completion. It proves that the
owned BL block has a distinct physical ``wing_wall`` basis before any wake,
span-cap, or core-interface faces are promoted into SU2 boundary markers.
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
    build_boundary_layer_wall_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import SurfaceMesh, validate_surface_mesh  # noqa: E402
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006z_bl_physical_wall_surface_probe"


def summarize_physical_wall_surface(
    block: WingBoundaryLayerBlock,
    wall_surface: SurfaceMesh,
) -> dict[str, Any]:
    try:
        validate_surface_mesh(wall_surface, required_markers=("wing_wall",))
    except ValueError as exc:
        status = "invalid"
        validation_error = str(exc)
    else:
        status = "watertight"
        validation_error = None

    boundary_counts = block.boundary_marker_counts()
    return {
        "schema_version": "wo006z_physical_wall_surface.v1",
        "status": status,
        "validation_error": validation_error,
        "marker_counts": wall_surface.marker_counts(),
        "source_wing_wall_face_count": int(
            wall_surface.metadata.get("source_wing_wall_face_count") or 0
        ),
        "tip_cap_face_count": int(wall_surface.metadata.get("tip_cap_face_count") or 0),
        "te_base_face_count": int(wall_surface.metadata.get("te_base_face_count") or 0),
        "sharp_te_seam_pair_count": int(
            wall_surface.metadata.get("sharp_te_seam_pair_count") or 0
        ),
        "surface_role": wall_surface.metadata.get("surface_role"),
        "solver_wall_marker_candidate": "wing_wall",
        "not_solver_boundary_markers_yet": [
            "bl_outer_interface",
            "wake_cut",
            "span_cap",
        ],
        "owned_bl_boundary_marker_counts": boundary_counts,
        "engineering_read": (
            "The layer-0 BL wall can be represented as an explicit watertight "
            "physical wall surface. BL outer, wake, and span-cap faces remain "
            "internal ownership surfaces until conformal BL/core merge is proven."
            if status == "watertight"
            else "The physical wall basis is not valid; do not proceed to BL/core handoff."
        ),
    }


def build_probe_summary(*, wall_surface: Mapping[str, Any]) -> dict[str, Any]:
    ready = wall_surface.get("status") == "watertight"
    return {
        "schema_version": "wo006z_bl_physical_wall_surface_probe.v1",
        "verdict": (
            "bl_physical_wall_basis_ready_not_handoff"
            if ready
            else "bl_physical_wall_basis_blocked"
        ),
        "physical_wall_surface": dict(wall_surface),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "full BL/core handoff readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": wall_surface.get("engineering_read"),
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
    wall_surface = build_boundary_layer_wall_surface(block, include_tip_caps=True)
    wall_summary = summarize_physical_wall_surface(block, wall_surface)
    summary = build_probe_summary(wall_surface=wall_summary)
    summary.update(
        {
            "output_dir": str(output_dir),
            "geometry_source": str(geometry.section_table_path),
            "points_per_side": int(points_per_side),
            "spanwise_subdivisions": int(spanwise_subdivisions),
            "bl_setup": {
                "first_layer_height_m": BL_FIRST_HEIGHT_M,
                "growth_ratio": BL_GROWTH_RATIO,
                "layer_count": BL_LAYERS,
            },
            "owned_bl_block": {
                "cell_count": len(block.cells),
                "boundary_marker_counts": block.boundary_marker_counts(),
                "quality": block.quality,
            },
        }
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "surface_ownership.csv", surface_ownership_rows(summary))
    (output_dir / "surface_ownership_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def surface_ownership_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    wall = summary["physical_wall_surface"]
    boundary_counts = wall.get("owned_bl_boundary_marker_counts") or {}
    return [
        {
            "surface_role": "solver_physical_wall_candidate",
            "marker": "wing_wall",
            "face_count": (wall.get("marker_counts") or {}).get("wing_wall"),
            "solver_boundary_status": "physical_wall_candidate_not_final_handoff",
            "notes": wall.get("engineering_read"),
        },
        {
            "surface_role": "source_spanwise_wall",
            "marker": "wing_wall",
            "face_count": wall.get("source_wing_wall_face_count"),
            "solver_boundary_status": "included_in_physical_wall_basis",
            "notes": "",
        },
        {
            "surface_role": "terminal_tip_wall_caps",
            "marker": "wing_wall",
            "face_count": wall.get("tip_cap_face_count"),
            "solver_boundary_status": "included_in_physical_wall_basis",
            "notes": "",
        },
        {
            "surface_role": "finite_te_base_wall",
            "marker": "wing_wall",
            "face_count": wall.get("te_base_face_count"),
            "solver_boundary_status": "included_only_when_non_degenerate",
            "notes": f"sharp_te_seam_pairs={wall.get('sharp_te_seam_pair_count')}",
        },
        *[
            {
                "surface_role": "internal_bl_core_ownership_surface",
                "marker": marker,
                "face_count": boundary_counts.get(marker),
                "solver_boundary_status": "not_solver_boundary_until_conformal_merge",
                "notes": "Must be internalized or matched before SU2 CFD.",
            }
            for marker in ("bl_outer_interface", "wake_cut", "span_cap")
        ],
    ]


def render_report(summary: Mapping[str, Any]) -> str:
    wall = summary["physical_wall_surface"]
    lines = [
        "# WO-006Z BL Physical Wall Surface Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- geometry source: `{summary['geometry_source']}`",
        f"- points per side: `{summary['points_per_side']}`",
        f"- spanwise subdivisions: `{summary['spanwise_subdivisions']}`",
        f"- wall surface status: `{wall.get('status')}`",
        f"- wall marker counts: `{wall.get('marker_counts')}`",
        f"- source spanwise wall faces: `{wall.get('source_wing_wall_face_count')}`",
        f"- tip-cap wall triangles: `{wall.get('tip_cap_face_count')}`",
        f"- finite TE-base wall faces: `{wall.get('te_base_face_count')}`",
        f"- sharp-TE seam pairs: `{wall.get('sharp_te_seam_pair_count')}`",
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
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "wall_status": summary["physical_wall_surface"]["status"],
                "wall_marker_counts": summary["physical_wall_surface"]["marker_counts"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
