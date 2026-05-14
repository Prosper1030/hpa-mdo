#!/usr/bin/env python3
"""Localize the remaining WO-006R25 mixed-SU2 boundary marker leaks.

R25 proved that the culled global-star mixed handoff can be written with
positive-volume tets, but the final volume-boundary marker audit still found
68 exterior faces without a SU2 marker.  This probe rebuilds the same R25
handoff in memory, keeps element-source provenance, and classifies each
remaining exterior face against loop-cap, candidate, and core-surface geometry.

It is a marker ownership localization/repair-plan probe only.  It does not
apply the marker repair to the SU2 mesh, does not run SU2, and does not provide
Baseline A CL/CD/Cm evidence.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import probe_wo006r25_culled_mixed_su2_handoff as r25  # noqa: E402
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r26_remaining_boundary_leak_localization_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r26_remaining_boundary_leak_localization_probe"
DEFAULT_R25_OUTPUT_DIR = WO006_ROOT / "wo006r25_culled_mixed_su2_handoff_probe"

SU2_TRIANGLE = r25.SU2_TRIANGLE
SU2_TETRA = r25.SU2_TETRA

REPAIR_READY_CLASSIFICATIONS = {
    "loop_cap_owner_pyramid_exterior",
    "loop_cap_physical_wall_edge_closure",
    "candidate_wake_edge_receiver_boundary",
    "core_wake_edge_receiver_boundary",
}


def collect_remaining_boundary_leak_records(
    *,
    nodes: Sequence[tuple[float, float, float]],
    elements: Sequence[Mapping[str, Any]],
    markers: Mapping[str, Sequence[Mapping[str, Any]]],
    classifier_index: Mapping[
        tuple[tuple[float, float, float], ...],
        Sequence[Mapping[str, Any]],
    ],
    digits: int = 10,
) -> list[dict[str, Any]]:
    face_entries: dict[tuple[int, ...], list[dict[str, Any]]] = defaultdict(list)
    for element_index, element in enumerate(elements):
        element_type = int(element["element_type"])
        for face in r25._volume_element_faces(element_type, r25._parse_nodes(element["nodes"])):
            face_entries[r25._face_node_key(face)].append(
                {
                    "element_index": element_index,
                    "source": str(element.get("source") or ""),
                }
            )

    marker_keys = {
        r25._face_node_key(r25._parse_nodes(face["nodes"]))
        for faces in markers.values()
        for face in faces
    }
    records: list[dict[str, Any]] = []
    for face_key, adjacent in sorted(face_entries.items()):
        if len(adjacent) != 1 or face_key in marker_keys:
            continue
        points = [nodes[int(node)] for node in face_key]
        polygon_key = point_polygon_key(points, digits=digits)
        matches = [dict(match) for match in classifier_index.get(polygon_key, [])]
        classification = classify_boundary_leak(
            matches=matches,
            adjacent_source=str(adjacent[0]["source"]),
        )
        records.append(
            {
                "face_nodes": list(face_key),
                "element_type": SU2_TRIANGLE if len(face_key) == 3 else len(face_key),
                "adjacent_element_index": adjacent[0]["element_index"],
                "adjacent_source": str(adjacent[0]["source"]),
                "classification": classification,
                "recommended_marker": recommended_marker_for_classification(classification),
                "surface_owner": surface_owner_for_classification(classification),
                "area_m2": r25._surface_face_area(nodes, face_key),
                "centroid": _centroid(points),
                "point_bounds": _point_bounds(points),
                "points": [list(point) for point in points],
                "matches": matches,
            }
        )
    return records


def classify_boundary_leak(
    *,
    matches: Sequence[Mapping[str, Any]],
    adjacent_source: str,
) -> str:
    families = {str(match.get("family") or "") for match in matches}
    if "core_wake_edge_receiver_boundary" in families:
        return "core_wake_edge_receiver_boundary"
    if "candidate_wake_edge_receiver_boundary" in families:
        return "candidate_wake_edge_receiver_boundary"
    if (
        "loop_cap_owner_pyramid_exterior" in families
        and "candidate_physical_wall_edge_receiver" in families
    ):
        return "loop_cap_physical_wall_edge_closure"
    if "loop_cap_owner_pyramid_exterior" in families:
        return "loop_cap_owner_pyramid_exterior"
    if "candidate_physical_wall_edge_receiver" in families:
        return "loop_cap_physical_wall_edge_closure"
    if adjacent_source == "loop_cap_owner_pyramid_tet_split" and matches:
        return "loop_cap_owner_pyramid_exterior"
    return "unclassified_boundary_leak"


def recommended_marker_for_classification(classification: str) -> str:
    if classification in REPAIR_READY_CLASSIFICATIONS:
        return "wing_wall"
    return ""


def surface_owner_for_classification(classification: str) -> str:
    owners = {
        "loop_cap_owner_pyramid_exterior": (
            "loop-cap owner pyramid exterior tip-wall closure"
        ),
        "loop_cap_physical_wall_edge_closure": (
            "physical-wall-edge receiver / loop-cap closure"
        ),
        "candidate_wake_edge_receiver_boundary": (
            "candidate wake-edge receiver solid closure"
        ),
        "core_wake_edge_receiver_boundary": "core wake-edge receiver solid closure",
    }
    return owners.get(classification, "unknown")


def summarize_remaining_boundary_leaks(
    *,
    records: Sequence[Mapping[str, Any]],
    output_dir: Path,
    geometry_source: str | None = None,
    upstream_r25_output_dir: Path | None = None,
    elapsed_s: float | None = None,
) -> dict[str, Any]:
    leak_count = len(records)
    unclassified_count = sum(
        1 for record in records if record.get("classification") == "unclassified_boundary_leak"
    )
    marker_counts = Counter(str(record.get("recommended_marker") or "") for record in records)
    marker_counts.pop("", None)
    repair_ready = leak_count > 0 and unclassified_count == 0 and bool(marker_counts)
    blockers = []
    if unclassified_count:
        blockers.append("unclassified_boundary_leaks")
    if leak_count and not repair_ready:
        blockers.append("boundary_marker_repair_policy_not_proven")
    blockers.extend(
        [
            "boundary_marker_repair_not_applied_to_mixed_su2_handoff",
            "solver_postprocessed_surface_yplus_missing",
            "su2_solver_ladder_not_run",
        ]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "remaining_boundary_leaks_localized_repair_plan_ready"
            if repair_ready
            else "remaining_boundary_leaks_localized_repair_blocked"
            if leak_count
            else "no_remaining_boundary_leaks_found"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "geometry_source": geometry_source,
        "output_dir": str(output_dir),
        "upstream_r25_output_dir": (
            str(upstream_r25_output_dir) if upstream_r25_output_dir is not None else None
        ),
        "leak_count": leak_count,
        "total_unmarked_area_m2": sum(float(record.get("area_m2") or 0.0) for record in records),
        "leak_counts_by_adjacent_source": _count_values(
            record.get("adjacent_source") for record in records
        ),
        "leak_counts_by_classification": _count_values(
            record.get("classification") for record in records
        ),
        "recommended_marker_counts": dict(sorted(marker_counts.items())),
        "bounds_m": _combined_bounds(records),
        "boundary_marker_repair_plan": {
            "status": "repair_plan_ready" if repair_ready else "blocked",
            "target_marker": "wing_wall" if repair_ready else "",
            "face_count": leak_count if repair_ready else 0,
            "area_m2": (
                sum(float(record.get("area_m2") or 0.0) for record in records)
                if repair_ready
                else 0.0
            ),
            "policy": (
                "Promote only the localized loop-cap / physical-wall-edge / "
                "wake-edge solid-closure exterior faces to the SU2 wing_wall marker."
                if repair_ready
                else "Do not apply a marker repair until every exterior face is classified."
            ),
        },
        "blockers": sorted(set(blockers)),
        "blocked_claims": [
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "grid convergence",
            "Baseline A drag or power truth",
        ],
        "elapsed_s": elapsed_s,
        "sample_records": [dict(record) for record in records[:50]],
        "engineering_read": (
            "The remaining R25 exterior faces are localized to solid tip/wake "
            "closure ownership classes. The next bounded repair can apply those "
            "faces to wing_wall in the writer, then rerun the mixed handoff marker "
            "audit. This is still not CFD evidence."
            if repair_ready
            else "At least one exterior face remains unclassified, so assigning a "
            "wall marker would be a boundary-condition guess rather than an "
            "engineering repair."
        ),
    }


def run_probe(
    *,
    output_dir: Path,
    r25_output_dir: Path = DEFAULT_R25_OUTPUT_DIR,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
    merge_digits: int = 10,
) -> dict[str, Any]:
    start = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    state = build_r25_state_with_provenance(
        r25_output_dir=r25_output_dir,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
        merge_digits=merge_digits,
    )
    classifier_index = build_classifier_index(
        candidate_vertices=state["candidate_vertices"],
        candidate_boundary_rows=state["candidate_boundary_rows"],
        candidate_face_records=state["candidate_face_records"],
        core_vertices=state["core_vertices"],
        core_triangle_rows=state["core_triangle_rows"],
        loop_cap_elements=state["loop_cap_elements"],
        writer_nodes=state["nodes"],
        digits=merge_digits,
    )
    records = collect_remaining_boundary_leak_records(
        nodes=state["nodes"],
        elements=state["elements"],
        markers=state["markers"],
        classifier_index=classifier_index,
        digits=merge_digits,
    )
    summary = summarize_remaining_boundary_leaks(
        records=records,
        output_dir=output_dir,
        geometry_source=str(state["geometry_source"]),
        upstream_r25_output_dir=r25_output_dir,
        elapsed_s=time.monotonic() - start,
    )
    summary["baseline_a_authority"] = {
        "source": "current GO Baseline A geometry via load_campaign_geometry",
        "points_per_side": int(points_per_side),
        "spanwise_subdivisions": int(spanwise_subdivisions),
        "bl_first_height_m": r25.BL_FIRST_HEIGHT_M,
        "bl_growth_ratio": r25.BL_GROWTH_RATIO,
        "bl_layers": r25.BL_LAYERS,
        "coordinate_merge_digits": int(merge_digits),
    }
    summary["r25_handoff_context"] = {
        "node_count": len(state["nodes"]),
        "volume_element_count": len(state["elements"]),
        "marker_counts": {marker: len(faces) for marker, faces in state["markers"].items()},
        "pre_r26_boundary_audit": state["boundary_audit"],
        "wall_marker_recovery": state["wall_marker_recovery"],
    }
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "boundary_marker_repair_plan.json", summary["boundary_marker_repair_plan"])
    write_csv(output_dir / "remaining_boundary_leak_records.csv", records)
    (output_dir / "remaining_boundary_leak_localization_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def build_r25_state_with_provenance(
    *,
    r25_output_dir: Path,
    points_per_side: int,
    spanwise_subdivisions: int,
    merge_digits: int,
) -> dict[str, Any]:
    geometry = r25.load_campaign_geometry(
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    block = r25.build_wing_boundary_layer_block(
        geometry.spec.wing_spec,
        r25.BoundaryLayerBlockSpec(
            first_layer_height_m=r25.BL_FIRST_HEIGHT_M,
            growth_ratio=r25.BL_GROWTH_RATIO,
            layer_count=r25.BL_LAYERS,
        ),
    )
    candidate = r25.build_near_wall_merged_volume_candidate(block)
    boundary_rows = r25.merged_boundary_face_rows(block, candidate)
    core_boundary_rows = r25.core_facing_rows(boundary_rows)
    cap_surface = r25.build_loop_cap_surface(block, candidate)
    repaired_surface, _repair = r25.repair_loop_cap_geometric_seams(cap_surface)
    hybrid_audit = r25.audit_hybrid_tet_prism_split_compatibility(
        vertices=candidate.vertices,
        candidate_cells=r25.volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_interface=repaired_surface,
    )
    target_rows = r25.global_star_target_triangle_rows(
        candidate_vertices=candidate.vertices,
        candidate_cells=r25.volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_vertices=repaired_surface.vertices,
        core_triangle_rows=hybrid_audit["core_triangle_rows"],
    )
    loop_cap_audit = r25.audit_loop_cap_owner_pyramids(
        candidate_vertices=candidate.vertices,
        core_vertices=repaired_surface.vertices,
        physical_wall_edge_rows=[
            row
            for row in boundary_rows
            if str(row.get("role") or "") == r25.PHYSICAL_WALL_EDGE_RECEIVER
        ],
        core_triangle_rows=hybrid_audit["core_triangle_rows"],
    )

    writer = r25.MixedMeshBuilder(digits=merge_digits)
    star_split = r25.build_culled_global_star_near_wall_elements(
        vertices=candidate.vertices,
        candidate_cells=r25.volume_cell_rows(candidate),
        target_triangle_rows=target_rows,
        external_boundary_rows=boundary_rows,
        writer=writer,
    )
    loop_cap = r25.build_loop_cap_owner_pyramid_elements(
        candidate_vertices=candidate.vertices,
        core_vertices=repaired_surface.vertices,
        owner_pyramid_rows=loop_cap_audit.get("owner_pyramid_rows") or [],
        writer=writer,
    )
    elements = [*star_split["elements"], *loop_cap["elements"]]
    markers = {
        "wing_wall": list((star_split.get("boundary_marker_faces") or {}).get("wing_wall") or []),
        "farfield": [],
    }
    core_su2 = r25_output_dir / "core_probe_artifacts" / "r25_repaired_loop_cap_core_probe.su2"
    if not core_su2.exists():
        raise FileNotFoundError(
            f"R26 requires the R25 core SU2 artifact to preserve exact handoff context: {core_su2}"
        )
    core_mesh = r25.parse_su2_mesh(core_su2)
    core_merge = r25.add_core_mesh_to_mixed_builder(core_mesh=core_mesh, writer=writer)
    elements.extend(core_merge["elements"])
    markers["farfield"] = core_merge["farfield_marker_faces"]
    wall_marker_recovery = r25.recover_wall_closure_marker_faces(
        nodes=writer.nodes,
        elements=elements,
        markers=markers,
        candidate_vertices=candidate.vertices,
        candidate_face_records=r25._face_records(block, candidate),
        digits=merge_digits,
    )
    if wall_marker_recovery["recovered_face_count"]:
        markers["wing_wall"].extend(wall_marker_recovery["faces"])
    boundary_audit = r25.audit_volume_boundary_markers(
        elements=elements,
        markers=markers,
        nodes=writer.nodes,
    )
    return {
        "geometry_source": geometry.section_table_path,
        "nodes": writer.nodes,
        "elements": elements,
        "markers": markers,
        "candidate_vertices": candidate.vertices,
        "candidate_boundary_rows": boundary_rows,
        "candidate_face_records": r25._face_records(block, candidate),
        "core_vertices": repaired_surface.vertices,
        "core_triangle_rows": hybrid_audit["core_triangle_rows"],
        "loop_cap_elements": loop_cap["elements"],
        "wall_marker_recovery": r25._drop_heavy_elements(wall_marker_recovery),
        "boundary_audit": r25._drop_heavy_elements(boundary_audit),
    }


def build_classifier_index(
    *,
    candidate_vertices: Sequence[tuple[float, float, float]],
    candidate_boundary_rows: Sequence[Mapping[str, Any]],
    candidate_face_records: Sequence[Mapping[str, Any]],
    core_vertices: Sequence[tuple[float, float, float]],
    core_triangle_rows: Sequence[Mapping[str, Any]],
    loop_cap_elements: Sequence[Mapping[str, Any]],
    writer_nodes: Sequence[tuple[float, float, float]],
    digits: int,
) -> dict[tuple[tuple[float, float, float], ...], list[dict[str, Any]]]:
    index: dict[tuple[tuple[float, float, float], ...], list[dict[str, Any]]] = defaultdict(list)

    for row in candidate_boundary_rows:
        role = str(row.get("role") or "")
        family = _candidate_role_family(role)
        if not family:
            continue
        for triangle in r25._deterministic_quad_triangulation(r25._parse_nodes(row.get("nodes"))):
            _append_match(
                index,
                [candidate_vertices[int(node)] for node in triangle],
                digits=digits,
                family=family,
                marker_role="wing_wall",
                surface_owner=f"candidate_boundary:{role}",
                source=str(row.get("source") or ""),
            )

    for row in candidate_face_records:
        role = str(row.get("role") or "")
        family = _candidate_role_family(role)
        if not family:
            continue
        for triangle in r25._deterministic_quad_triangulation(r25._parse_nodes(row.get("nodes"))):
            _append_match(
                index,
                [candidate_vertices[int(node)] for node in triangle],
                digits=digits,
                family=family,
                marker_role="wing_wall",
                surface_owner=f"candidate_face_record:{role}",
                source=str(row.get("source") or ""),
            )

    for row in core_triangle_rows:
        marker = str(row.get("marker") or "")
        family = _core_marker_family(marker)
        if not family:
            continue
        triangle = r25._parse_nodes(row.get("triangle_nodes"))
        _append_match(
            index,
            [core_vertices[int(node)] for node in triangle],
            digits=digits,
            family=family,
            marker_role="wing_wall",
            surface_owner=f"core_triangle:{marker}",
            source=str(row.get("source") or ""),
        )

    for element in loop_cap_elements:
        for face in r25._volume_element_faces(
            int(element["element_type"]),
            r25._parse_nodes(element["nodes"]),
        ):
            _append_match(
                index,
                [writer_nodes[int(node)] for node in face],
                digits=digits,
                family="loop_cap_owner_pyramid_exterior",
                marker_role="wing_wall",
                surface_owner="loop_cap_owner_pyramid_tet_split",
                source=str(element.get("source") or ""),
            )

    return {key: value for key, value in index.items()}


def point_polygon_key(
    points: Sequence[tuple[float, float, float]],
    *,
    digits: int,
) -> tuple[tuple[float, float, float], ...]:
    return r25._point_polygon_key(points, digits=digits)


def render_report(summary: Mapping[str, Any]) -> str:
    plan = summary.get("boundary_marker_repair_plan") or {}
    return "\n".join(
        [
            "# WO-006R26 Remaining Boundary Leak Localization Probe",
            "",
            "This is marker-ownership repair evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary.get('goal_status')}`",
            f"CFD_STATUS: `{summary.get('cfd_status')}`",
            f"- verdict: `{summary.get('verdict')}`",
            f"- remaining leak faces: `{summary.get('leak_count')}`",
            f"- total unmarked area m^2: `{summary.get('total_unmarked_area_m2')}`",
            f"- by adjacent source: `{summary.get('leak_counts_by_adjacent_source')}`",
            f"- by classification: `{summary.get('leak_counts_by_classification')}`",
            f"- repair plan status: `{plan.get('status')}`",
            f"- repair target marker: `{plan.get('target_marker')}`",
            f"- blockers: `{summary.get('blockers')}`",
            "",
            f"Engineering read: {summary.get('engineering_read')}",
            "",
        ]
    )


def _candidate_role_family(role: str) -> str:
    if role == r25.PHYSICAL_WALL_EDGE_RECEIVER:
        return "candidate_physical_wall_edge_receiver"
    if role == "wake_edge_receiver":
        return "candidate_wake_edge_receiver_boundary"
    if role == "wing_wall":
        return "candidate_physical_wall_edge_receiver"
    return ""


def _core_marker_family(marker: str) -> str:
    if marker == "wake_edge_receiver":
        return "core_wake_edge_receiver_boundary"
    return ""


def _append_match(
    index: dict[tuple[tuple[float, float, float], ...], list[dict[str, Any]]],
    points: Sequence[tuple[float, float, float]],
    *,
    digits: int,
    family: str,
    marker_role: str,
    surface_owner: str,
    source: str,
) -> None:
    index[point_polygon_key(points, digits=digits)].append(
        {
            "family": family,
            "marker_role": marker_role,
            "surface_owner": surface_owner,
            "source": source,
        }
    )


def _centroid(points: Sequence[tuple[float, float, float]]) -> list[float]:
    count = float(len(points))
    return [
        sum(point[axis] for point in points) / count
        for axis in range(3)
    ]


def _point_bounds(points: Sequence[tuple[float, float, float]]) -> dict[str, list[float]]:
    return {
        axis: [min(point[index] for point in points), max(point[index] for point in points)]
        for index, axis in enumerate(("x", "y", "z"))
    }


def _combined_bounds(records: Sequence[Mapping[str, Any]]) -> dict[str, list[float] | None]:
    if not records:
        return {"x": None, "y": None, "z": None}
    points = [
        tuple(float(value) for value in point)
        for record in records
        for point in record.get("points", [])
    ]
    if not points:
        return {"x": None, "y": None, "z": None}
    return _point_bounds(points)


def _count_values(values: Sequence[Any] | Any) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values if str(value)).items()))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list, tuple))
                    else value
                    for key, value in row.items()
                }
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--r25-output-dir", type=Path, default=DEFAULT_R25_OUTPUT_DIR)
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    parser.add_argument("--merge-digits", type=int, default=10)
    args = parser.parse_args(argv)
    summary = run_probe(
        output_dir=args.output_dir,
        r25_output_dir=args.r25_output_dir,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        merge_digits=args.merge_digits,
    )
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "leak_count": summary["leak_count"],
                "leak_counts_by_adjacent_source": summary[
                    "leak_counts_by_adjacent_source"
                ],
                "leak_counts_by_classification": summary[
                    "leak_counts_by_classification"
                ],
                "repair_plan": summary["boundary_marker_repair_plan"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
