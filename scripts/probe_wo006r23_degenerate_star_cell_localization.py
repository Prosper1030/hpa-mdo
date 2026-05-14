#!/usr/bin/env python3
"""Localize WO-006R22 degenerate global-star split triangles.

R22 reduced the active mixed-handoff blocker to zero-area star triangles.  This
probe turns that count into cell/face/coordinate evidence for the next local
cell-type-reduction repair.  It does not write a mixed SU2 mesh or run CFD.
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
from probe_wo006ad_near_wall_merged_volume_candidate import (  # noqa: E402
    build_near_wall_merged_volume_candidate,
    merged_boundary_face_rows,
    volume_cell_rows,
)
from probe_wo006r11_core_facing_loop_closure import core_facing_rows  # noqa: E402
from probe_wo006r13_loop_cap_geometric_seam_repair import (  # noqa: E402
    build_loop_cap_surface,
    repair_loop_cap_geometric_seams,
)
from probe_wo006r17_hybrid_tet_prism_split import (  # noqa: E402
    audit_hybrid_tet_prism_split_compatibility,
)
from probe_wo006r22_global_star_split_basis import (  # noqa: E402
    HEX_FACE_LOCAL_NODES,
    _deterministic_quad_triangulation,
    _face_node_key,
    _parse_nodes,
    _point_key,
    _triangle_area,
    global_star_target_triangle_rows,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r23_degenerate_star_cell_localization_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r23_degenerate_star_cell_localization_probe"


def collect_degenerate_star_triangle_records(
    *,
    vertices: Sequence[tuple[float, float, float]],
    candidate_cells: Sequence[Mapping[str, Any]],
    target_triangle_rows: Sequence[Mapping[str, Any]],
    digits: int = 10,
) -> list[dict[str, Any]]:
    target_groups: dict[tuple[int, tuple[int, ...]], list[Mapping[str, Any]]] = {}
    for row in target_triangle_rows:
        cell_index = int(row.get("cell_index", -1))
        face_key = _face_node_key(_parse_nodes(row.get("face_nodes")))
        target_groups.setdefault((cell_index, face_key), []).append(row)

    records: list[dict[str, Any]] = []
    for raw_cell_index, cell in enumerate(candidate_cells):
        cell_index = int(cell.get("cell_index", raw_cell_index))
        cell_nodes = _parse_nodes(cell.get("nodes"))
        if len(cell_nodes) != 8:
            continue
        for local_face_index, local_face in enumerate(HEX_FACE_LOCAL_NODES):
            face_nodes = tuple(cell_nodes[index] for index in local_face)
            face_key = _face_node_key(face_nodes)
            target_rows = target_groups.get((cell_index, face_key))
            triangles = (
                [_parse_nodes(row.get("triangle_nodes")) for row in target_rows]
                if target_rows
                else _deterministic_quad_triangulation(face_nodes)
            )
            markers = [str(row.get("marker") or "") for row in target_rows or []]
            for triangle_index, triangle in enumerate(triangles):
                points = [vertices[int(node)] for node in triangle]
                if _triangle_area(*points) > 1.0e-14:
                    continue
                repeated = _repeated_point_keys(points, digits=digits)
                records.append(
                    {
                        "cell_index": cell_index,
                        "source": str(cell.get("source") or ""),
                        "role": str(cell.get("role") or ""),
                        "local_face_index": local_face_index,
                        "face_nodes": list(face_nodes),
                        "triangle_index_on_face": triangle_index,
                        "triangle_nodes": list(triangle),
                        "marker": markers[triangle_index] if triangle_index < len(markers) else "",
                        "unique_point_count": len(
                            {_point_key(point, digits=digits) for point in points}
                        ),
                        "repeated_point_keys": repeated,
                        "point_bounds": _point_bounds(points),
                        "points": [list(point) for point in points],
                    }
                )
    return records


def build_localization_summary(
    *,
    records: Sequence[Mapping[str, Any]],
    output_dir: Path,
    geometry_source: str,
) -> dict[str, Any]:
    bounds = _combined_bounds(records)
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "degenerate_star_cells_localized_repair_required"
            if records
            else "no_degenerate_star_cells_found_mixed_mesh_still_missing"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "geometry_source": geometry_source,
        "output_dir": str(output_dir),
        "degenerate_star_triangle_count": len(records),
        "degenerate_cell_count": len({int(row["cell_index"]) for row in records}),
        "records_by_source": _count_values(row.get("source") for row in records),
        "records_by_role": _count_values(row.get("role") for row in records),
        "records_by_marker": _count_values(row.get("marker") for row in records),
        "bounds_m": bounds,
        "blockers": [
            "degenerate_star_triangles_require_cell_type_reduction",
            "merged_mixed_bl_core_su2_mesh_missing",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ],
        "blocked_claims": [
            "merged BL+core SU2 handoff",
            "postprocessed near-wall y+",
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "sample_records": [dict(row) for row in records[:50]],
        "engineering_read": (
            "The remaining global-star blocker is localized to degenerate "
            "zero-area star triangles. The next repair should reduce or special-case "
            "those local cells before any mixed SU2 writer or solver ladder."
            if records
            else "No degenerate star triangles were found, but this probe still does "
            "not provide a mixed SU2 mesh, y+, or solver ladder."
        ),
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
    boundary_rows = merged_boundary_face_rows(block, candidate)
    core_boundary_rows = core_facing_rows(boundary_rows)
    cap_surface = build_loop_cap_surface(block, candidate)
    repaired_surface, _repair = repair_loop_cap_geometric_seams(cap_surface)
    hybrid_audit = audit_hybrid_tet_prism_split_compatibility(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_interface=repaired_surface,
    )
    target_rows = global_star_target_triangle_rows(
        candidate_vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_vertices=repaired_surface.vertices,
        core_triangle_rows=hybrid_audit["core_triangle_rows"],
    )
    records = collect_degenerate_star_triangle_records(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        target_triangle_rows=target_rows,
    )
    summary = build_localization_summary(
        records=records,
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
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "degenerate_star_triangle_records.csv", records)
    (output_dir / "degenerate_star_cell_localization_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# WO-006R23 Degenerate Star Cell Localization Probe",
            "",
            "This is local repair evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- degenerate star triangles: `{summary['degenerate_star_triangle_count']}`",
            f"- degenerate cells: `{summary['degenerate_cell_count']}`",
            f"- records by role: `{summary['records_by_role']}`",
            f"- records by marker: `{summary['records_by_marker']}`",
            f"- bounds m: `{summary['bounds_m']}`",
            f"- blockers: `{summary['blockers']}`",
            "",
            f"Engineering read: {summary['engineering_read']}",
            "",
        ]
    )


def _repeated_point_keys(
    points: Sequence[tuple[float, float, float]],
    *,
    digits: int,
) -> list[tuple[float, float, float]]:
    counts: dict[tuple[float, float, float], int] = {}
    for point in points:
        key = _point_key(point, digits=digits)
        counts[key] = counts.get(key, 0) + 1
    return [key for key, count in sorted(counts.items()) if count > 1]


def _point_bounds(points: Sequence[tuple[float, float, float]]) -> dict[str, float]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    zs = [float(point[2]) for point in points]
    return {
        "x_min": min(xs),
        "x_max": max(xs),
        "y_min": min(ys),
        "y_max": max(ys),
        "z_min": min(zs),
        "z_max": max(zs),
    }


def _combined_bounds(records: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    if not records:
        return {
            "x_min": None,
            "x_max": None,
            "y_min": None,
            "y_max": None,
            "z_min": None,
            "z_max": None,
        }
    bounds = [row["point_bounds"] for row in records]
    return {
        "x_min": min(float(row["x_min"]) for row in bounds),
        "x_max": max(float(row["x_max"]) for row in bounds),
        "y_min": min(float(row["y_min"]) for row in bounds),
        "y_max": max(float(row["y_max"]) for row in bounds),
        "z_min": min(float(row["z_min"]) for row in bounds),
        "z_max": max(float(row["z_max"]) for row in bounds),
    }


def _count_values(values: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


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
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "degenerate_star_triangles": summary["degenerate_star_triangle_count"],
                "degenerate_cells": summary["degenerate_cell_count"],
                "records_by_role": summary["records_by_role"],
                "records_by_marker": summary["records_by_marker"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
