#!/usr/bin/env python3
"""Test whether a simple two-prism BL cell split can conform to R13 core triangles.

WO-006R14 showed that the R13 repaired core interface is mostly aligned with
the near-wall boundary polygons, but the actual core triangles are not
conformal with the current hexa/quad near-wall representation.  This probe
checks a tempting low-cost repair: split each near-wall hexa cell into two
triangular prisms, choosing one of the two common face diagonals per cell.

If this cannot cover the core interface triangles, the next repair has to make
the near-wall and core route share the interface tessellation; merely changing a
local prism diagonal is not a CFD-ready handoff.
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
from hpa_meshing.mesh_native.wing_surface import SurfaceMesh  # noqa: E402
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
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r15_prism_split_handoff_compatibility_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r15_prism_split_handoff_compatibility_probe"

PRISM_SPLIT_PATTERNS: tuple[tuple[tuple[int, int, int, int, int, int], ...], ...] = (
    (
        (0, 1, 2, 4, 5, 6),
        (0, 2, 3, 4, 6, 7),
    ),
    (
        (0, 1, 3, 4, 5, 7),
        (1, 2, 3, 5, 6, 7),
    ),
)
PRISM_FACE_LOCAL_NODES: tuple[tuple[int, ...], ...] = (
    (0, 1, 2),
    (3, 4, 5),
    (0, 3, 4, 1),
    (1, 4, 5, 2),
    (2, 5, 3, 0),
)


def audit_prism_split_handoff_compatibility(
    *,
    vertices: Sequence[tuple[float, float, float]],
    candidate_cells: Sequence[Mapping[str, Any]],
    candidate_boundary_faces: Sequence[Mapping[str, Any]],
    core_interface: SurfaceMesh,
    digits: int = 10,
) -> dict[str, Any]:
    core_entries = _core_triangle_entries(core_interface, digits=digits)
    core_triangle_keys = {entry["key"] for entry in core_entries}
    core_marker_by_key = {entry["key"]: entry["marker"] for entry in core_entries}
    boundary_rows = _normalized_boundary_rows(candidate_boundary_faces)
    matched_core_triangle_keys: set[tuple[tuple[float, float, float], ...]] = set()
    cell_choice_rows: list[dict[str, Any]] = []

    for raw_cell_index, cell in enumerate(candidate_cells):
        nodes = tuple(int(node) for node in cell.get("nodes", []))
        if len(nodes) != 8:
            continue
        cell_boundary_rows = [
            row
            for row in boundary_rows
            if set(row["nodes"]).issubset(set(nodes))
        ]
        if not cell_boundary_rows:
            continue

        target_keys = _core_triangle_keys_touching_boundary_rows(
            core_entries,
            vertices,
            cell_boundary_rows,
            digits=digits,
        )
        choices = []
        for pattern_index in range(len(PRISM_SPLIT_PATTERNS)):
            split_keys = _split_boundary_triangle_keys_for_cell(
                vertices,
                nodes,
                pattern_index=pattern_index,
                candidate_boundary_rows=cell_boundary_rows,
                digits=digits,
            )
            matched_keys = split_keys & core_triangle_keys
            choices.append((pattern_index, matched_keys))

        best_pattern, best_matched_keys = max(
            choices,
            key=lambda choice: (len(choice[1]), -choice[0]),
        )
        matched_core_triangle_keys.update(best_matched_keys)
        source = str(cell.get("source") or "")
        role = str(cell.get("role") or "")
        cell_choice_rows.append(
            {
                "cell_index": int(cell.get("cell_index", raw_cell_index)),
                "source": source,
                "role": role,
                "boundary_face_count": len(cell_boundary_rows),
                "target_core_triangle_count": len(target_keys),
                "selected_pattern": f"pattern_{best_pattern}",
                "matched_triangle_count": len(best_matched_keys),
                "unmatched_triangle_count": len(target_keys - best_matched_keys),
            }
        )

    unmatched_keys = core_triangle_keys - matched_core_triangle_keys
    matched_by_marker = _count_markers(
        core_marker_by_key[key] for key in matched_core_triangle_keys
    )
    unmatched_by_marker = _count_markers(core_marker_by_key[key] for key in unmatched_keys)
    best_pattern_counts = _count_markers(row["selected_pattern"] for row in cell_choice_rows)
    status = "pass" if not unmatched_keys else "blocked_by_incompatible_prism_split"
    if not cell_choice_rows and core_triangle_keys:
        status = "blocked_by_no_candidate_core_facing_cells"

    blockers: list[str] = []
    if status != "pass":
        blockers.append("simple_two_prism_split_does_not_match_core_interface")
    if unmatched_by_marker:
        blockers.append("shared_interface_tessellation_missing")

    return {
        "schema_version": "wo006r15_prism_split_handoff_compatibility.v1",
        "status": status,
        "blockers": blockers,
        "candidate_cell_count": len(candidate_cells),
        "candidate_core_facing_cell_count": len(cell_choice_rows),
        "candidate_boundary_face_count": len(boundary_rows),
        "core_triangle_count": len(core_triangle_keys),
        "matched_core_triangle_count": len(matched_core_triangle_keys),
        "unmatched_core_triangle_count": len(unmatched_keys),
        "matched_core_triangles_by_marker": dict(sorted(matched_by_marker.items())),
        "unmatched_core_triangles_by_marker": dict(sorted(unmatched_by_marker.items())),
        "best_pattern_counts": dict(sorted(best_pattern_counts.items())),
        "cell_choice_rows": cell_choice_rows,
        "core_triangle_rows": [
            {
                "core_face_index": entry["core_face_index"],
                "marker": entry["marker"],
                "triangle_nodes": entry["triangle_nodes"],
                "matched_by_best_prism_split": entry["key"] in matched_core_triangle_keys,
            }
            for entry in core_entries
        ],
        "engineering_read": (
            "A per-cell two-prism split can reproduce the current core interface "
            "triangles, but this is still only a topology probe until the mixed "
            "BL+core SU2 handoff and y+ evidence exist."
            if status == "pass"
            else "A simple per-cell two-prism split cannot reproduce the current "
            "R13 core interface triangles. The handoff needs a shared interface "
            "tessellation or boundary-driven near-wall remesh before medium/fine SU2."
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
        blockers.append("prism_split_handoff_compatibility_blocked")
    blockers.extend(str(item) for item in audit.get("blockers", []))
    if audit.get("unmatched_core_triangles_by_marker"):
        blockers.append("shared_interface_tessellation_missing")
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
            "prism_split_handoff_compatibility_pass_handoff_still_missing"
            if audit.get("status") == "pass"
            else "prism_split_handoff_compatibility_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "merged_handoff_status": audit.get("status"),
        "coefficient_interpretable": False,
        "geometry_source": geometry_source,
        "output_dir": str(output_dir),
        "prism_split_compatibility": dict(audit),
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
    audit = audit_prism_split_handoff_compatibility(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=boundary_rows,
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
    write_csv(output_dir / "cell_prism_split_choices.csv", audit["cell_choice_rows"])
    write_csv(output_dir / "core_triangle_prism_split_match.csv", audit["core_triangle_rows"])
    (output_dir / "prism_split_handoff_compatibility_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    audit = summary["prism_split_compatibility"]
    return "\n".join(
        [
            "# WO-006R15 Prism Split Handoff Compatibility Probe",
            "",
            "This is a pre-handoff topology audit, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- merged handoff status: `{summary['merged_handoff_status']}`",
            f"- candidate cells: `{audit['candidate_cell_count']}`",
            f"- core-facing candidate cells: `{audit['candidate_core_facing_cell_count']}`",
            f"- candidate core-facing boundary faces: `{audit['candidate_boundary_face_count']}`",
            f"- matched core triangles: `{audit['matched_core_triangle_count']}` / `{audit['core_triangle_count']}`",
            f"- unmatched core triangles by marker: `{audit['unmatched_core_triangles_by_marker']}`",
            f"- selected pattern counts: `{audit['best_pattern_counts']}`",
            f"- blockers: `{summary['blockers']}`",
            "",
            f"Engineering read: {audit['engineering_read']}",
            "",
        ]
    )


def _core_triangle_entries(
    core_interface: SurfaceMesh,
    *,
    digits: int,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for face_index, face in enumerate(core_interface.faces):
        for triangle in _triangulate(face.nodes):
            entries.append(
                {
                    "core_face_index": face_index,
                    "marker": face.marker,
                    "triangle_nodes": list(triangle),
                    "key": _polygon_key(core_interface.vertices, triangle, digits=digits),
                }
            )
    return entries


def _normalized_boundary_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(rows):
        nodes = tuple(int(node) for node in row.get("nodes", []))
        if len(nodes) < 3:
            continue
        normalized.append(
            {
                "boundary_face_index": int(row.get("boundary_face_index", index)),
                "source": str(row.get("source") or ""),
                "role": str(row.get("role") or ""),
                "nodes": nodes,
            }
        )
    return normalized


def _core_triangle_keys_touching_boundary_rows(
    core_entries: Sequence[Mapping[str, Any]],
    vertices: Sequence[tuple[float, float, float]],
    boundary_rows: Sequence[Mapping[str, Any]],
    *,
    digits: int,
) -> set[tuple[tuple[float, float, float], ...]]:
    boundary_point_sets = [
        set(_polygon_key(vertices, row["nodes"], digits=digits))
        for row in boundary_rows
    ]
    target_keys: set[tuple[tuple[float, float, float], ...]] = set()
    for entry in core_entries:
        triangle_points = set(entry["key"])
        if any(triangle_points.issubset(points) for points in boundary_point_sets):
            target_keys.add(entry["key"])
    return target_keys


def _split_boundary_triangle_keys_for_cell(
    vertices: Sequence[tuple[float, float, float]],
    hex_nodes: Sequence[int],
    *,
    pattern_index: int,
    candidate_boundary_rows: Sequence[Mapping[str, Any]],
    digits: int,
) -> set[tuple[tuple[float, float, float], ...]]:
    boundary_node_sets = [
        set(int(node) for node in row["nodes"])
        for row in candidate_boundary_rows
    ]
    keys: set[tuple[tuple[float, float, float], ...]] = set()
    for face in _split_exterior_faces(hex_nodes, pattern_index=pattern_index):
        if len(face) != 3:
            continue
        face_nodes = set(face)
        if not any(face_nodes.issubset(boundary_nodes) for boundary_nodes in boundary_node_sets):
            continue
        keys.add(_polygon_key(vertices, face, digits=digits))
    return keys


def _split_exterior_faces(
    hex_nodes: Sequence[int],
    *,
    pattern_index: int,
) -> list[tuple[int, ...]]:
    pattern = PRISM_SPLIT_PATTERNS[int(pattern_index)]
    raw_faces: list[tuple[int, ...]] = []
    face_counts: dict[tuple[int, ...], int] = {}
    for prism in pattern:
        prism_nodes = tuple(int(hex_nodes[local]) for local in prism)
        for local_face in PRISM_FACE_LOCAL_NODES:
            face = tuple(prism_nodes[index] for index in local_face)
            raw_faces.append(face)
            key = tuple(sorted(face))
            face_counts[key] = face_counts.get(key, 0) + 1
    return [
        face
        for face in raw_faces
        if face_counts[tuple(sorted(face))] == 1
    ]


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
    audit = summary["prism_split_compatibility"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "merged_handoff_status": summary["merged_handoff_status"],
                "matched_core_triangle_count": audit["matched_core_triangle_count"],
                "core_triangle_count": audit["core_triangle_count"],
                "unmatched_core_triangles_by_marker": audit[
                    "unmatched_core_triangles_by_marker"
                ],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
