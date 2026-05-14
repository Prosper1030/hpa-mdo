#!/usr/bin/env python3
"""Localize the remaining WO-006R17 BL/core handoff residuals.

R17 reduced the Baseline A near-wall/core interface mismatch to a small, sharp
set of residuals: unowned core-wall loop-cap triangles plus a few owned tip/wake
triangles that no local hybrid tet/prism split can reproduce.  R18 turns that
count into repair-ready geometry evidence.  It is still a topology diagnostic;
it does not write a merged SU2 mesh, postprocess y+, or run CFD coefficients.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence


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
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r18_handoff_residual_localization_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r18_handoff_residual_localization_probe"
LOOP_CAP_MARKER = "core_wall_loop_cap"


def summarize_handoff_residuals(
    *,
    vertices: Sequence[tuple[float, float, float]],
    core_triangle_rows: Sequence[Mapping[str, Any]],
    cell_choice_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    residual_triangle_rows = _residual_triangle_rows(vertices, core_triangle_rows)
    unowned_rows = [
        row for row in residual_triangle_rows
        if row["residual_class"] == "unowned_core_triangle"
    ]
    incompatible_rows = [
        row for row in residual_triangle_rows
        if row["residual_class"] == "candidate_owned_split_incompatible"
    ]
    incompatible_cells = _incompatible_cells(cell_choice_rows)
    loop_cap_fans = _loop_cap_fans(unowned_rows)

    unowned_by_marker = _count_markers(row["marker"] for row in unowned_rows)
    incompatible_by_marker = _count_markers(row["marker"] for row in incompatible_rows)
    recommended_next_repair = _recommended_next_repair(
        unowned_by_marker=unowned_by_marker,
        incompatible_cells=incompatible_cells,
    )
    status = "pass" if not residual_triangle_rows else "blocked"
    return {
        "schema_version": "wo006r18_handoff_residuals.v1",
        "status": status,
        "residual_triangle_count": len(residual_triangle_rows),
        "unowned_residual_count": len(unowned_rows),
        "incompatible_owned_residual_count": len(incompatible_rows),
        "unowned_residuals_by_marker": dict(sorted(unowned_by_marker.items())),
        "incompatible_owned_residuals_by_marker": dict(
            sorted(incompatible_by_marker.items())
        ),
        "loop_cap_fans": loop_cap_fans,
        "incompatible_cells": incompatible_cells,
        "recommended_next_repair": recommended_next_repair,
        "residual_triangle_rows": residual_triangle_rows,
        "engineering_read": (
            "The latest handoff residuals are localized enough for a bounded "
            "geometry/topology repair; do not run a medium/fine SU2 ladder until "
            "these residuals are cleared and the merged mesh/y+ gates exist."
            if status == "blocked"
            else "No R17-style residual triangles remain, but merged mesh, y+, and "
            "solver-ladder gates are still required before CFD interpretation."
        ),
    }


def build_probe_summary(
    *,
    residuals: Mapping[str, Any],
    output_dir: Path,
    geometry_source: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    if residuals.get("status") != "pass":
        blockers.append("handoff_residuals_require_repair")
    if (residuals.get("unowned_residuals_by_marker") or {}).get(LOOP_CAP_MARKER):
        blockers.append("core_wall_loop_cap_owner_cells_missing")
    if int((residuals.get("incompatible_cells") or {}).get("count") or 0) > 0:
        blockers.append("tip_wake_receiver_shared_tessellation_incompatible")
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
            "handoff_residuals_clear_handoff_still_missing"
            if residuals.get("status") == "pass"
            else "handoff_residuals_localized_repair_required"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "geometry_source": geometry_source,
        "output_dir": str(output_dir),
        "residuals": dict(residuals),
        "blockers": sorted(set(blockers)),
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
    boundary_rows = core_facing_rows(merged_boundary_face_rows(block, candidate))
    cap_surface = build_loop_cap_surface(block, candidate)
    repaired_surface, repair = repair_loop_cap_geometric_seams(cap_surface)
    audit = audit_hybrid_tet_prism_split_compatibility(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=boundary_rows,
        core_interface=repaired_surface,
    )
    residuals = summarize_handoff_residuals(
        vertices=repaired_surface.vertices,
        core_triangle_rows=audit["core_triangle_rows"],
        cell_choice_rows=audit["cell_choice_rows"],
    )
    summary = build_probe_summary(
        residuals=residuals,
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
    summary["hybrid_split_basis"] = {
        "status": audit.get("status"),
        "matched_core_triangle_count": audit.get("matched_core_triangle_count"),
        "core_triangle_count": audit.get("core_triangle_count"),
        "candidate_owned_core_triangle_count": audit.get(
            "candidate_owned_core_triangle_count"
        ),
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
        output_dir / "handoff_residual_triangles.csv",
        residuals["residual_triangle_rows"],
    )
    write_csv(
        output_dir / "handoff_incompatible_cells.csv",
        (residuals["incompatible_cells"] or {}).get("cells", []),
    )
    write_csv(output_dir / "loop_cap_fans.csv", (residuals["loop_cap_fans"] or {}).get("fans", []))
    (output_dir / "handoff_residual_localization_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    residuals = summary["residuals"]
    loop_cap = residuals.get("loop_cap_fans") or {}
    incompatible = residuals.get("incompatible_cells") or {}
    return "\n".join(
        [
            "# WO-006R18 Handoff Residual Localization Probe",
            "",
            "This is repair-localization evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- residual status: `{residuals['status']}`",
            f"- residual triangles: `{residuals['residual_triangle_count']}`",
            f"- unowned residuals by marker: `{residuals['unowned_residuals_by_marker']}`",
            f"- incompatible owned residuals by marker: `{residuals['incompatible_owned_residuals_by_marker']}`",
            f"- loop-cap fan count: `{loop_cap.get('fan_count')}`",
            f"- incompatible cell count: `{incompatible.get('count')}`",
            f"- recommended next repair: `{residuals['recommended_next_repair']}`",
            f"- blockers: `{summary['blockers']}`",
            "",
            f"Engineering read: {residuals['engineering_read']}",
            "",
        ]
    )


def _residual_triangle_rows(
    vertices: Sequence[tuple[float, float, float]],
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    residuals: list[dict[str, Any]] = []
    for row in rows:
        candidate_owned = _as_bool(row.get("candidate_owned"))
        matched = _as_bool(row.get("matched_by_best_hybrid_split"))
        if candidate_owned and matched:
            continue
        nodes = _parse_nodes(row.get("triangle_nodes"))
        points = [vertices[int(node)] for node in nodes]
        residual_class = (
            "unowned_core_triangle"
            if not candidate_owned
            else "candidate_owned_split_incompatible"
        )
        residuals.append(
            {
                "core_face_index": int(row.get("core_face_index", -1)),
                "marker": str(row.get("marker") or ""),
                "triangle_nodes": list(nodes),
                "candidate_owned": candidate_owned,
                "matched_by_best_hybrid_split": matched,
                "residual_class": residual_class,
                **_bounds(points),
            }
        )
    return residuals


def _loop_cap_fans(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cap_rows = [row for row in rows if row.get("marker") == LOOP_CAP_MARKER]
    if not cap_rows:
        return {
            "status": "pass",
            "fan_count": 0,
            "triangle_count": 0,
            "fans": [],
        }

    node_to_rows: dict[int, set[int]] = {}
    for row_index, row in enumerate(cap_rows):
        for node in _parse_nodes(row.get("triangle_nodes")):
            node_to_rows.setdefault(int(node), set()).add(row_index)

    visited: set[int] = set()
    fans: list[dict[str, Any]] = []
    for start in range(len(cap_rows)):
        if start in visited:
            continue
        stack = [start]
        component_indices: set[int] = set()
        while stack:
            index = stack.pop()
            if index in visited:
                continue
            visited.add(index)
            component_indices.add(index)
            for node in _parse_nodes(cap_rows[index].get("triangle_nodes")):
                for neighbor in node_to_rows.get(int(node), set()):
                    if neighbor not in visited:
                        stack.append(neighbor)

        component_rows = [cap_rows[index] for index in sorted(component_indices)]
        node_counts: dict[int, int] = {}
        for row in component_rows:
            for node in _parse_nodes(row.get("triangle_nodes")):
                node_counts[int(node)] = node_counts.get(int(node), 0) + 1
        center_node = max(node_counts, key=lambda node: (node_counts[node], -node))
        fans.append(
            {
                "fan_index": len(fans),
                "center_node": center_node,
                "center_node_incidence": node_counts[center_node],
                "triangle_count": len(component_rows),
                "node_count": len(node_counts),
                **_merge_bounds(component_rows),
            }
        )
    fans.sort(key=lambda row: (row["y_min"], row["x_min"], row["z_min"]))
    for index, row in enumerate(fans):
        row["fan_index"] = index
    return {
        "status": "owner_cells_missing",
        "fan_count": len(fans),
        "triangle_count": len(cap_rows),
        "fans": fans,
        "engineering_read": (
            "These cap fans close the core inner surface, but no near-wall volume "
            "cell currently owns the matching side of those triangles."
        ),
    }


def _incompatible_cells(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cells = []
    for row in rows:
        unmatched = int(row.get("unmatched_triangle_count") or 0)
        if unmatched <= 0:
            continue
        cells.append(
            {
                "cell_index": int(row.get("cell_index", -1)),
                "source": str(row.get("source") or ""),
                "role": str(row.get("role") or ""),
                "boundary_face_count": int(row.get("boundary_face_count") or 0),
                "target_core_triangle_count": int(
                    row.get("target_core_triangle_count") or 0
                ),
                "selected_pattern": str(row.get("selected_pattern") or ""),
                "matched_triangle_count": int(row.get("matched_triangle_count") or 0),
                "unmatched_triangle_count": unmatched,
            }
        )
    return {
        "status": "pass" if not cells else "split_incompatible",
        "count": len(cells),
        "by_source": dict(sorted(_count_markers(row["source"] for row in cells).items())),
        "by_role": dict(sorted(_count_markers(row["role"] for row in cells).items())),
        "by_selected_pattern": dict(
            sorted(_count_markers(row["selected_pattern"] for row in cells).items())
        ),
        "cells": cells,
    }


def _recommended_next_repair(
    *,
    unowned_by_marker: Mapping[str, int],
    incompatible_cells: Mapping[str, Any],
) -> str:
    has_loop_cap = int(unowned_by_marker.get(LOOP_CAP_MARKER) or 0) > 0
    has_incompatible = int(incompatible_cells.get("count") or 0) > 0
    if has_loop_cap and has_incompatible:
        return "materialize_core_wall_loop_cap_owner_cells_then_repair_left_tip_receiver_split"
    if has_loop_cap:
        return "materialize_core_wall_loop_cap_owner_cells"
    if has_incompatible:
        return "repair_left_tip_receiver_shared_tessellation"
    return "write_marker_quality_gated_mixed_bl_core_su2_handoff_and_yplus_probe"


def _bounds(points: Sequence[tuple[float, float, float]]) -> dict[str, float]:
    return {
        "x_min": min(point[0] for point in points),
        "x_max": max(point[0] for point in points),
        "y_min": min(point[1] for point in points),
        "y_max": max(point[1] for point in points),
        "z_min": min(point[2] for point in points),
        "z_max": max(point[2] for point in points),
    }


def _merge_bounds(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    return {
        "x_min": min(float(row["x_min"]) for row in rows),
        "x_max": max(float(row["x_max"]) for row in rows),
        "y_min": min(float(row["y_min"]) for row in rows),
        "y_max": max(float(row["y_max"]) for row in rows),
        "z_min": min(float(row["z_min"]) for row in rows),
        "z_max": max(float(row["z_max"]) for row in rows),
    }


def _parse_nodes(raw: Any) -> tuple[int, ...]:
    if isinstance(raw, str):
        return tuple(int(part.strip()) for part in raw.strip("[]").split(",") if part.strip())
    return tuple(int(node) for node in raw)


def _as_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.lower() == "true"
    return bool(raw)


def _count_markers(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        marker = str(value)
        counts[marker] = counts.get(marker, 0) + 1
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
    residuals = summary["residuals"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "residual_triangle_count": residuals["residual_triangle_count"],
                "unowned_residuals_by_marker": residuals["unowned_residuals_by_marker"],
                "incompatible_owned_residuals_by_marker": residuals[
                    "incompatible_owned_residuals_by_marker"
                ],
                "recommended_next_repair": residuals["recommended_next_repair"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
