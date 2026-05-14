#!/usr/bin/env python3
"""Audit WO-006R13 core interface against the near-wall volume handoff.

R13 proves the repaired loop-cap surface can be used as a marker-owned core
mesh probe. That is still not the same as a merged mixed BL+core SU2 handoff:
the core interface must also be conformal with the owned near-wall volume
boundary, including the actual surface tessellation consumed by the core mesh.
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
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import Face, SurfaceMesh  # noqa: E402
from probe_wo006ad_near_wall_merged_volume_candidate import (  # noqa: E402
    build_near_wall_merged_volume_candidate,
    merged_boundary_face_rows,
)
from probe_wo006r11_core_facing_loop_closure import core_facing_rows  # noqa: E402
from probe_wo006r13_loop_cap_geometric_seam_repair import (  # noqa: E402
    build_loop_cap_surface,
    repair_loop_cap_geometric_seams,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r14_mixed_handoff_conformality_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r14_mixed_handoff_conformality_probe"


def audit_mixed_handoff_conformality(
    *,
    near_wall_interface: SurfaceMesh,
    core_interface: SurfaceMesh,
    digits: int = 10,
) -> dict[str, Any]:
    near_polygons = {
        _polygon_key(near_wall_interface.vertices, face.nodes, digits=digits): face.marker
        for face in near_wall_interface.faces
    }
    near_triangles = {
        _polygon_key(near_wall_interface.vertices, triangle, digits=digits): face.marker
        for face in near_wall_interface.faces
        for triangle in _triangulate(face.nodes)
    }
    core_polygon_rows: list[dict[str, Any]] = []
    core_triangle_rows: list[dict[str, Any]] = []

    polygon_matched_core_face_count = 0
    polygon_matched_but_triangle_unmatched_count = 0
    missing_polygon_by_marker: dict[str, int] = {}
    unmatched_core_triangles_by_marker: dict[str, int] = {}
    triangle_matched_core_face_count = 0
    for face_index, face in enumerate(core_interface.faces):
        polygon_key = _polygon_key(core_interface.vertices, face.nodes, digits=digits)
        polygon_matched = polygon_key in near_polygons
        if polygon_matched:
            polygon_matched_core_face_count += 1
        else:
            missing_polygon_by_marker[face.marker] = (
                missing_polygon_by_marker.get(face.marker, 0) + 1
            )

        face_triangle_match_count = 0
        face_triangle_count = 0
        for triangle in _triangulate(face.nodes):
            face_triangle_count += 1
            triangle_key = _polygon_key(core_interface.vertices, triangle, digits=digits)
            triangle_matched = triangle_key in near_triangles
            if triangle_matched:
                face_triangle_match_count += 1
                triangle_matched_core_face_count += 1
            else:
                unmatched_core_triangles_by_marker[face.marker] = (
                    unmatched_core_triangles_by_marker.get(face.marker, 0) + 1
                )
            core_triangle_rows.append(
                {
                    "core_face_index": face_index,
                    "marker": face.marker,
                    "triangle_nodes": list(triangle),
                    "polygon_matched": polygon_matched,
                    "triangle_matched": triangle_matched,
                }
            )
        if polygon_matched and face_triangle_match_count != face_triangle_count:
            polygon_matched_but_triangle_unmatched_count += 1
        core_polygon_rows.append(
            {
                "core_face_index": face_index,
                "marker": face.marker,
                "node_count": len(face.nodes),
                "polygon_matched": polygon_matched,
                "matched_triangle_count": face_triangle_match_count,
                "triangle_count": face_triangle_count,
            }
        )

    blockers: list[str] = []
    if polygon_matched_but_triangle_unmatched_count:
        blockers.append("core_nearwall_polygon_match_but_triangle_mismatch")
    if missing_polygon_by_marker:
        blockers.append("core_interface_polygon_without_nearwall_owner")

    status = "pass"
    if "core_nearwall_polygon_match_but_triangle_mismatch" in blockers:
        status = "blocked_by_interface_triangulation_mismatch"
    elif blockers:
        status = "blocked_by_interface_geometry_gap"

    core_triangle_count = len(core_triangle_rows)
    return {
        "schema_version": "wo006r14_mixed_handoff_conformality.v1",
        "status": status,
        "blockers": blockers,
        "near_wall_face_count": len(near_wall_interface.faces),
        "core_face_count": len(core_interface.faces),
        "near_wall_triangle_count": len(near_triangles),
        "core_triangle_count": core_triangle_count,
        "polygon_matched_core_face_count": polygon_matched_core_face_count,
        "triangle_matched_core_face_count": triangle_matched_core_face_count,
        "polygon_matched_but_triangle_unmatched_count": (
            polygon_matched_but_triangle_unmatched_count
        ),
        "missing_polygon_core_faces_by_marker": dict(sorted(missing_polygon_by_marker.items())),
        "unmatched_core_triangles_by_marker": dict(
            sorted(unmatched_core_triangles_by_marker.items())
        ),
        "core_polygon_rows": core_polygon_rows,
        "core_triangle_rows": core_triangle_rows,
        "engineering_read": (
            "The R13 repaired core surface is geometrically aligned with most "
            "near-wall boundary polygons, but the triangulated core boundary is "
            "not conformal with the current near-wall volume representation. A "
            "solver mesh would need a shared interface tessellation, not just "
            "matching coordinates."
            if status != "pass"
            else "The core interface triangles are conformal with the near-wall boundary."
        ),
    }


def build_probe_summary(
    *,
    audit: Mapping[str, Any],
    output_dir: Path,
    geometry_source: str,
) -> dict[str, Any]:
    blockers = []
    if audit.get("status") != "pass":
        blockers.append("mixed_handoff_interface_not_conformal")
    blockers.extend(
        [
            "merged_mixed_bl_core_su2_mesh_missing",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "mixed_handoff_conformality_pass_handoff_still_missing"
            if audit.get("status") == "pass"
            else "mixed_handoff_conformality_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "merged_handoff_status": audit.get("status"),
        "coefficient_interpretable": False,
        "geometry_source": geometry_source,
        "output_dir": str(output_dir),
        "conformality_audit": dict(audit),
        "blockers": blockers,
        "blocked_claims": [
            "merged BL+core SU2 handoff",
            "postprocessed near-wall y+",
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
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
    near_wall_interface = SurfaceMesh(
        vertices=list(candidate.vertices),
        faces=[
            Face(nodes=tuple(int(node) for node in row["nodes"]), marker=str(row["role"]))
            for row in core_facing_rows(merged_boundary_face_rows(block, candidate))
        ],
        metadata={"surface_role": "wo006r14_near_wall_core_facing_boundary"},
    )
    cap_surface = build_loop_cap_surface(block, candidate)
    repaired_surface, repair = repair_loop_cap_geometric_seams(cap_surface)
    audit = audit_mixed_handoff_conformality(
        near_wall_interface=near_wall_interface,
        core_interface=repaired_surface,
    )
    summary = build_probe_summary(
        audit=audit,
        output_dir=output_dir,
        geometry_source=str(geometry.section_table_path),
    )
    summary["baseline_a_authority"] = {
        "source": "current GO Baseline A geometry via load_campaign_geometry",
        "points_per_side": int(points_per_side),
        "spanwise_subdivisions": int(spanwise_subdivisions),
        "bl_first_height_m": BL_FIRST_HEIGHT_M,
        "bl_growth_ratio": BL_GROWTH_RATIO,
        "bl_layers": BL_LAYERS,
    }
    summary["repair_basis"] = {
        "status": repair.get("status"),
        "dropped_duplicate_face_count": repair.get("dropped_duplicate_face_count"),
        "post_repair_bad_edge_count": (
            (repair.get("post_repair_audit") or {})
            .get("welded_topology", {})
            .get("bad_edge_count")
        ),
    }
    write_json(output_dir / "summary.json", summary)
    write_csv(
        output_dir / "core_polygon_conformality.csv",
        audit["core_polygon_rows"],
    )
    write_csv(
        output_dir / "core_triangle_conformality.csv",
        audit["core_triangle_rows"],
    )
    (output_dir / "mixed_handoff_conformality_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    audit = summary["conformality_audit"]
    return "\n".join(
        [
            "# WO-006R14 Mixed Handoff Conformality Probe",
            "",
            "This is a pre-handoff topology audit, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- merged handoff status: `{summary['merged_handoff_status']}`",
            f"- core faces: `{audit['core_face_count']}`",
            f"- near-wall interface faces: `{audit['near_wall_face_count']}`",
            f"- polygon-matched core faces: `{audit['polygon_matched_core_face_count']}`",
            f"- triangle-matched core triangles: `{audit['triangle_matched_core_face_count']}` / `{audit['core_triangle_count']}`",
            f"- polygon-matched but triangle-unmatched faces: `{audit['polygon_matched_but_triangle_unmatched_count']}`",
            f"- missing core polygons by marker: `{audit['missing_polygon_core_faces_by_marker']}`",
            f"- unmatched core triangles by marker: `{audit['unmatched_core_triangles_by_marker']}`",
            f"- blockers: `{summary['blockers']}`",
            "",
            f"Engineering read: {audit['engineering_read']}",
            "",
        ]
    )


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


def _triangulate(nodes: Sequence[int]) -> list[tuple[int, ...]]:
    node_tuple = tuple(int(node) for node in nodes)
    if len(node_tuple) == 3:
        return [node_tuple]
    if len(node_tuple) == 4:
        return [
            (node_tuple[0], node_tuple[1], node_tuple[2]),
            (node_tuple[0], node_tuple[2], node_tuple[3]),
        ]
    raise ValueError("Only triangle and quad interface faces are supported")


def _polygon_key(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
    *,
    digits: int,
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        sorted(
            tuple(round(float(value), digits) for value in vertices[int(node)])
            for node in nodes
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
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
    audit = summary["conformality_audit"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "merged_handoff_status": summary["merged_handoff_status"],
                "polygon_matched_core_face_count": audit[
                    "polygon_matched_core_face_count"
                ],
                "triangle_matched_core_face_count": audit[
                    "triangle_matched_core_face_count"
                ],
                "core_triangle_count": audit["core_triangle_count"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
