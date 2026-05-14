#!/usr/bin/env python3
"""Repair the R12 loop-cap geometric seam and rerun the core mesh probe.

R12 proved the R11 core-facing surface is closed by index topology but not
PLC-valid: exact duplicate coordinates at the sharp-TE tip/wake loop-cap seam
collapse into non-manifold edges inside Gmsh. R13 applies the minimal geometric
repair observed in the probe: weld exact duplicate coordinates and remove every
face group that becomes an exact same-marker duplicate after that weld.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys
import time
import traceback
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    write_core_tet_mesh_from_inner_surface,
)
from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    WingBoundaryLayerBlock,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    Face,
    SurfaceMesh,
    build_farfield_box_surface,
    orient_surface_mesh_outward,
    validate_surface_mesh,
)
from probe_wo006ad_near_wall_merged_volume_candidate import (  # noqa: E402
    MergedVolumeCandidate,
    build_near_wall_merged_volume_candidate,
    merged_boundary_face_rows,
)
from probe_wo006r11_core_facing_loop_closure import (  # noqa: E402
    build_core_facing_loop_cap_surface,
    core_facing_rows,
    open_edge_loops,
    summarize_core_facing_loop_closure,
)
from probe_wo006r12_loop_cap_core_mesh_probe import (  # noqa: E402
    audit_inner_surface_geometry,
    marker_count_rows,
    summarize_loop_cap_core_mesh_probe,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r13_loop_cap_geometric_seam_repair_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r13_loop_cap_geometric_seam_repair_probe"


def build_loop_cap_surface(
    block: WingBoundaryLayerBlock,
    candidate: MergedVolumeCandidate,
) -> SurfaceMesh:
    boundary_rows = merged_boundary_face_rows(block, candidate)
    core_rows = core_facing_rows(boundary_rows)
    loops = open_edge_loops(core_rows)
    return build_core_facing_loop_cap_surface(candidate, core_rows, loops)


def repair_loop_cap_geometric_seams(
    surface: SurfaceMesh,
    *,
    digits: int = 12,
) -> tuple[SurfaceMesh, dict[str, Any]]:
    pre_audit = audit_inner_surface_geometry(surface)
    key_to_new: dict[tuple[float, float, float], int] = {}
    remap: dict[int, int] = {}
    welded_vertices: list[tuple[float, float, float]] = []
    for index, point in enumerate(surface.vertices):
        key = tuple(round(value, digits) for value in point)
        if key not in key_to_new:
            key_to_new[key] = len(welded_vertices)
            welded_vertices.append(point)
        remap[index] = key_to_new[key]

    welded_nodes_by_face: list[tuple[int, ...]] = []
    duplicate_groups: dict[tuple[str, tuple[int, ...]], list[int]] = {}
    for face_index, face in enumerate(surface.faces):
        welded_nodes = tuple(remap[int(node)] for node in face.nodes)
        welded_nodes_by_face.append(welded_nodes)
        duplicate_groups.setdefault((face.marker, tuple(sorted(welded_nodes))), []).append(
            face_index
        )

    duplicate_face_indices = {
        face_index
        for indices in duplicate_groups.values()
        if len(indices) > 1
        for face_index in indices
    }
    degenerate_face_indices: set[int] = set()
    repaired_faces: list[Face] = []
    dropped_duplicate_faces: list[dict[str, Any]] = []
    for face_index, face in enumerate(surface.faces):
        welded_nodes = welded_nodes_by_face[face_index]
        if len(set(welded_nodes)) != len(welded_nodes):
            degenerate_face_indices.add(face_index)
            continue
        if face_index in duplicate_face_indices:
            dropped_duplicate_faces.append(
                {
                    "face_index": face_index,
                    "marker": face.marker,
                    "original_nodes": list(face.nodes),
                    "welded_nodes": list(welded_nodes),
                }
            )
            continue
        repaired_faces.append(Face(nodes=welded_nodes, marker=face.marker))

    repaired = orient_surface_mesh_outward(
        SurfaceMesh(
            vertices=welded_vertices,
            faces=repaired_faces,
            metadata={
                **surface.metadata,
                "surface_role": "wo006r13_repaired_loop_cap_core_surface",
                "repair": "weld_exact_duplicate_coordinates_drop_duplicate_faces",
            },
        )
    )
    validate_surface_mesh(
        repaired,
        allowed_markers=frozenset(repaired.marker_counts()),
        required_markers=(),
    )
    post_audit = audit_inner_surface_geometry(repaired)
    status = "pass" if post_audit["welded_topology"]["bad_edge_count"] == 0 else "blocked"
    return repaired, {
        "schema_version": "wo006r13_loop_cap_geometric_seam_repair.v1",
        "status": status,
        "pre_repair_audit": pre_audit,
        "post_repair_audit": post_audit,
        "original_vertex_count": len(surface.vertices),
        "repaired_vertex_count": len(repaired.vertices),
        "original_face_count": len(surface.faces),
        "repaired_face_count": len(repaired.faces),
        "dropped_duplicate_face_count": len(dropped_duplicate_faces),
        "dropped_duplicate_faces": dropped_duplicate_faces,
        "degenerate_face_count": len(degenerate_face_indices),
        "marker_counts": repaired.marker_counts(),
        "engineering_read": (
            "Exact-coordinate welding plus duplicate seam-face removal makes the "
            "loop-cap surface watertight in geometric PLC terms."
            if status == "pass"
            else "The duplicate seam repair did not fully clear geometric topology."
        ),
    }


def run_repaired_loop_cap_core_mesh_probe(
    *,
    block: WingBoundaryLayerBlock,
    candidate: MergedVolumeCandidate,
    output_dir: Path,
    mesh_size: float,
    farfield_mesh_size: float,
    gmsh_threads: int = 4,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    cap_surface = build_loop_cap_surface(block, candidate)
    repaired_surface, repair = repair_loop_cap_geometric_seams(cap_surface)
    loop_closure = summarize_core_facing_loop_closure(block, candidate)
    farfield = build_farfield_box_surface(
        repaired_surface,
        upstream_factor=2.0,
        downstream_factor=4.0,
        lateral_factor=2.0,
        vertical_factor=2.0,
    )
    probe_dir = output_dir / "core_probe_artifacts"
    probe_dir.mkdir(parents=True, exist_ok=True)
    try:
        core_report = write_core_tet_mesh_from_inner_surface(
            repaired_surface,
            farfield,
            probe_dir / "repaired_loop_cap_core_probe.msh",
            su2_path=probe_dir / "repaired_loop_cap_core_probe.su2",
            mesh_size=mesh_size,
            farfield_mesh_size=farfield_mesh_size,
            preserve_boundary_mesh=True,
            preserved_boundary_representation="triangulated",
            gmsh_threads=gmsh_threads,
            mesh_algorithm3d=10,
            owned_bl_block=block,
        )
    except Exception as exc:  # pragma: no cover - reserved for real Gmsh failures.
        core_report = {
            "status": "failed",
            "route": "mesh_native_inner_surface_core_tet_probe",
            "failure_code": "repaired_loop_cap_core_mesh_generation_failed",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "mesh_quality_gate": {
                "status": "fail",
                "blockers": ["core_mesh_generation_exception"],
            },
            "su2_boundary_ownership": None,
            "interface_conformality": {"status": "not_run"},
            "inner_boundary": {"marker_counts": repaired_surface.marker_counts()},
            "physical_groups": {},
        }
    write_json(probe_dir / "repaired_loop_cap_core_probe_report.json", core_report)

    inner_surface_audit = repair["post_repair_audit"]
    core_mesh = summarize_loop_cap_core_mesh_probe(
        loop_closure=loop_closure,
        core_report=core_report,
        inner_surface_audit=inner_surface_audit,
    )
    ready = core_mesh["status"] == "core_mesh_probe_pass_merged_handoff_pending"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "loop_cap_geometric_seam_repair_core_mesh_pass_not_handoff"
            if ready
            else "loop_cap_geometric_seam_repair_core_mesh_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "repair": repair,
        "loop_closure": dict(loop_closure),
        "loop_cap_core_mesh": core_mesh,
        "output_dir": str(output_dir),
        "elapsed_s": time.monotonic() - start,
        "blocked_claims": [
            "merged BL+core SU2 handoff",
            "postprocessed near-wall y+",
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
    }
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "loop_cap_geometric_seam_repair_summary.json", summary)
    write_csv(
        output_dir / "repaired_surface_marker_counts.csv",
        marker_count_rows(repair["marker_counts"]),
    )
    (output_dir / "loop_cap_geometric_seam_repair_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def run_campaign(
    *,
    output_dir: Path,
    clean: bool = True,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
    mesh_size: float = 1.0,
    farfield_mesh_size: float = 8.0,
    gmsh_threads: int = 4,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
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
    summary = run_repaired_loop_cap_core_mesh_probe(
        block=block,
        candidate=candidate,
        output_dir=output_dir,
        mesh_size=mesh_size,
        farfield_mesh_size=farfield_mesh_size,
        gmsh_threads=gmsh_threads,
    )
    summary["baseline_a_authority"] = {
        "source": "current GO Baseline A geometry via load_campaign_geometry",
        "geometry_source": str(geometry.section_table_path),
        "points_per_side": int(points_per_side),
        "spanwise_subdivisions": int(spanwise_subdivisions),
        "bl_first_height_m": BL_FIRST_HEIGHT_M,
        "bl_growth_ratio": BL_GROWTH_RATIO,
        "bl_layers": BL_LAYERS,
    }
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "loop_cap_geometric_seam_repair_summary.json", summary)
    (output_dir / "loop_cap_geometric_seam_repair_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    repair = summary.get("repair") or {}
    core = summary.get("loop_cap_core_mesh") or {}
    quality = core.get("quality_metrics") or {}
    return "\n".join(
        [
            "# WO-006R13 Loop-Cap Geometric Seam Repair",
            "",
            "This is mesh handoff progress only, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary.get('goal_status')}`",
            f"CFD_STATUS: `{summary.get('cfd_status')}`",
            f"- verdict: `{summary.get('verdict')}`",
            f"- repair status: `{repair.get('status')}`",
            f"- dropped duplicate faces: `{repair.get('dropped_duplicate_face_count')}`",
            f"- repaired markers: `{repair.get('marker_counts')}`",
            f"- core mesh status: `{core.get('status')}`",
            f"- nodes: `{core.get('node_count')}`",
            f"- volume elements: `{core.get('volume_element_count')}`",
            f"- mesh quality: `{core.get('core_mesh_quality_status')}`",
            f"- SU2 boundary ownership: `{core.get('core_mesh_marker_status')}`",
            f"- non-positive SICN/SIGE/volume: `{quality.get('non_positive_min_sicn_count')}` / `{quality.get('non_positive_min_sige_count')}` / `{quality.get('non_positive_volume_count')}`",
            f"- blockers: `{core.get('blockers')}`",
            "",
            "Blocked claims:",
            "- merged BL+core SU2 handoff",
            "- postprocessed near-wall y+",
            "- SU2 coarse/medium/fine ladder",
            "- CL/CD/Cm interpretation",
        ]
    ) + "\n"


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
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    parser.add_argument("--mesh-size", type=float, default=1.0)
    parser.add_argument("--farfield-mesh-size", type=float, default=8.0)
    parser.add_argument("--gmsh-threads", type=int, default=4)
    args = parser.parse_args(argv)
    summary = run_campaign(
        output_dir=args.output_dir,
        clean=not args.no_clean,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        mesh_size=args.mesh_size,
        farfield_mesh_size=args.farfield_mesh_size,
        gmsh_threads=args.gmsh_threads,
    )
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "core_mesh_status": summary["loop_cap_core_mesh"]["status"],
                "volume_element_count": summary["loop_cap_core_mesh"].get(
                    "volume_element_count"
                ),
                "quality_status": summary["loop_cap_core_mesh"].get(
                    "core_mesh_quality_status"
                ),
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
