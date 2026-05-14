#!/usr/bin/env python3
"""Audit whether the WO-006 split choices assemble into a conformal volume.

R17 selected a best local tet/prism split per core-facing near-wall cell. R19
and R20 proved local repair bases for the remaining loop-cap and left-tip
interface residuals.  Before writing a mixed BL+core SU2 mesh, those local
choices still need a whole-volume assembly check: adjacent near-wall cells must
not create unmatched internal split faces.

This probe is deliberately pre-writer evidence.  It does not write the final
mixed SU2 mesh, postprocess y+, or run CFD coefficients.
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
    hybrid_split_patterns,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r21_split_assembly_conformality_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r21_split_assembly_conformality_probe"
DEFAULT_SPLIT_PATTERN = "tet_06"


def audit_split_assembly_conformality(
    *,
    vertices: Sequence[tuple[float, float, float]],
    candidate_cells: Sequence[Mapping[str, Any]],
    selected_patterns_by_cell: Mapping[int, str],
    external_boundary_rows: Sequence[Mapping[str, Any]],
    default_pattern: str = DEFAULT_SPLIT_PATTERN,
    digits: int = 10,
) -> dict[str, Any]:
    pattern_lookup = {
        name: (tuple(tuple(int(index) for index in element) for element in elements), faces)
        for name, elements, faces in hybrid_split_patterns()
    }
    if default_pattern not in pattern_lookup:
        raise ValueError(f"Unknown default split pattern: {default_pattern}")
    unknown_patterns = sorted(
        {
            pattern
            for pattern in selected_patterns_by_cell.values()
            if pattern not in pattern_lookup
        }
    )
    if unknown_patterns:
        raise ValueError(f"Unknown selected split patterns: {unknown_patterns}")

    boundary_point_sets = [
        set(_polygon_key(vertices, _parse_nodes(row.get("nodes")), digits=digits))
        for row in external_boundary_rows
    ]
    face_rows: list[dict[str, Any]] = []
    face_counts: dict[tuple[tuple[float, float, float], ...], int] = {}
    pattern_counts: dict[str, int] = {}
    volume_element_count = 0

    for raw_cell_index, cell in enumerate(candidate_cells):
        cell_index = int(cell.get("cell_index", raw_cell_index))
        cell_nodes = _parse_nodes(cell.get("nodes"))
        if len(cell_nodes) != 8:
            continue
        pattern_name = str(selected_patterns_by_cell.get(cell_index) or default_pattern)
        split_elements, face_local_nodes = pattern_lookup[pattern_name]
        pattern_counts[pattern_name] = pattern_counts.get(pattern_name, 0) + 1
        for local_element_index, local_element in enumerate(split_elements):
            element_nodes = tuple(cell_nodes[index] for index in local_element)
            volume_element_count += 1
            for face in _split_element_faces(
                element_nodes,
                face_local_nodes=face_local_nodes,
            ):
                key = _polygon_key(vertices, face, digits=digits)
                face_counts[key] = face_counts.get(key, 0) + 1
                face_rows.append(
                    {
                        "cell_index": cell_index,
                        "source": str(cell.get("source") or ""),
                        "role": str(cell.get("role") or ""),
                        "pattern": pattern_name,
                        "local_element_index": local_element_index,
                        "face_nodes": list(face),
                        "face_key": key,
                    }
                )

    exterior_rows = []
    internal_leak_rows = []
    nonmanifold_keys = {
        key for key, count in face_counts.items()
        if count > 2
    }
    for row in face_rows:
        key = row["face_key"]
        count = face_counts[key]
        if count != 1:
            continue
        is_external_boundary = any(set(key).issubset(points) for points in boundary_point_sets)
        exterior_rows.append({**_csv_safe_row(row), "is_external_boundary": is_external_boundary})
        if not is_external_boundary:
            internal_leak_rows.append(_csv_safe_row(row))

    status = (
        "split_assembly_conformal"
        if not internal_leak_rows and not nonmanifold_keys
        else "split_assembly_internal_nonconformal"
    )
    return {
        "schema_version": "wo006r21_split_assembly_conformality.v1",
        "status": status,
        "blockers": _blockers_for_status(
            status=status,
            internal_leak_count=len(internal_leak_rows),
            nonmanifold_count=len(nonmanifold_keys),
        ),
        "candidate_cell_count": len(candidate_cells),
        "volume_element_count": volume_element_count,
        "selected_cell_count": len(selected_patterns_by_cell),
        "default_pattern": default_pattern,
        "selected_pattern_counts": dict(sorted(pattern_counts.items())),
        "split_face_count": len(face_rows),
        "exterior_split_face_count": len(exterior_rows),
        "external_boundary_face_count": len(exterior_rows) - len(internal_leak_rows),
        "internal_split_leak_face_count": len(internal_leak_rows),
        "nonmanifold_split_face_count": len(nonmanifold_keys),
        "internal_split_leak_samples": internal_leak_rows[:25],
        "engineering_read": (
            "The current split choices assemble without unmatched internal split "
            "faces. A mixed mesh writer can proceed to marker ownership and y+ gates."
            if status == "split_assembly_conformal"
            else "The current local split choices create unmatched internal split "
            "faces between near-wall cells. A mixed BL+core SU2 writer must use a "
            "globally conformal split assignment, not just per-cell core-face matching."
        ),
    }


def build_probe_summary(
    *,
    audit: Mapping[str, Any],
    output_dir: Path,
    geometry_source: str,
) -> dict[str, Any]:
    conformal = audit.get("status") == "split_assembly_conformal"
    blockers = []
    if not conformal:
        blockers.append("near_wall_split_assembly_internal_nonconformal")
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
            "split_assembly_conformal_mixed_mesh_pending"
            if conformal
            else "split_assembly_internal_nonconformal"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "geometry_source": geometry_source,
        "output_dir": str(output_dir),
        "split_assembly_conformality": dict(audit),
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
    boundary_rows = merged_boundary_face_rows(block, candidate)
    core_boundary_rows = core_facing_rows(boundary_rows)
    cap_surface = build_loop_cap_surface(block, candidate)
    repaired_surface, repair = repair_loop_cap_geometric_seams(cap_surface)
    hybrid_audit = audit_hybrid_tet_prism_split_compatibility(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_interface=repaired_surface,
    )
    selected_patterns = {
        int(row["cell_index"]): str(row["selected_pattern"])
        for row in hybrid_audit.get("cell_choice_rows") or []
    }
    audit = audit_split_assembly_conformality(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        selected_patterns_by_cell=selected_patterns,
        external_boundary_rows=boundary_rows,
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
    summary["hybrid_split_basis"] = {
        "status": hybrid_audit.get("status"),
        "matched_core_triangle_count": hybrid_audit.get("matched_core_triangle_count"),
        "core_triangle_count": hybrid_audit.get("core_triangle_count"),
        "selected_core_facing_cell_count": len(selected_patterns),
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
        output_dir / "internal_split_leak_samples.csv",
        audit["internal_split_leak_samples"],
    )
    (output_dir / "split_assembly_conformality_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    audit = summary["split_assembly_conformality"]
    return "\n".join(
        [
            "# WO-006R21 Split Assembly Conformality Probe",
            "",
            "This is mixed-mesh writer preflight evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- split assembly status: `{audit['status']}`",
            f"- candidate cells: `{audit['candidate_cell_count']}`",
            f"- split volume elements: `{audit['volume_element_count']}`",
            f"- selected core-facing cells: `{audit['selected_cell_count']}`",
            f"- internal split leaks: `{audit['internal_split_leak_face_count']}`",
            f"- non-manifold split faces: `{audit['nonmanifold_split_face_count']}`",
            f"- selected pattern counts: `{audit['selected_pattern_counts']}`",
            f"- blockers: `{summary['blockers']}`",
            "",
            f"Engineering read: {audit['engineering_read']}",
            "",
        ]
    )


def _blockers_for_status(
    *,
    status: str,
    internal_leak_count: int,
    nonmanifold_count: int,
) -> list[str]:
    blockers = []
    if status != "split_assembly_conformal":
        blockers.append("split_assembly_not_conformal")
    if internal_leak_count:
        blockers.append("internal_split_faces_without_neighbor_match")
    if nonmanifold_count:
        blockers.append("nonmanifold_split_faces")
    blockers.extend(
        [
            "merged_mixed_bl_core_su2_mesh_missing",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )
    return blockers


def _split_element_faces(
    element_nodes: Sequence[int],
    *,
    face_local_nodes: Sequence[Sequence[int]],
) -> list[tuple[int, ...]]:
    return [
        tuple(int(element_nodes[index]) for index in face)
        for face in face_local_nodes
    ]


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


def _parse_nodes(raw: Any) -> tuple[int, ...]:
    if isinstance(raw, str):
        return tuple(int(part.strip()) for part in raw.strip("[]").split(",") if part.strip())
    return tuple(int(node) for node in raw)


def _csv_safe_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value if key != "face_key" else list(value)
        for key, value in row.items()
    }


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
    audit = summary["split_assembly_conformality"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "split_status": audit["status"],
                "internal_split_leaks": audit["internal_split_leak_face_count"],
                "nonmanifold_split_faces": audit["nonmanifold_split_face_count"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
