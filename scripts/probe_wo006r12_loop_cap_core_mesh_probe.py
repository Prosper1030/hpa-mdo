#!/usr/bin/env python3
"""Generate a WO-006R12 core/farfield mesh probe from the R11 loop-cap surface.

R11 closed the core-facing open loops as explicit ``core_wall_loop_cap`` faces.
R12 is the next bounded check: ask Gmsh to tet-fill the core around that exact
materialized inner surface, preserve the inner markers, write SU2 marker
ownership evidence, and stop before claiming a merged BL/core handoff or CFD
coefficients.
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
    build_farfield_box_surface,
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
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r12_loop_cap_core_mesh_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r12_loop_cap_core_mesh_probe"


def summarize_loop_cap_core_mesh_probe(
    *,
    loop_closure: Mapping[str, Any],
    core_report: Mapping[str, Any],
    inner_surface_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    quality_gate = core_report.get("mesh_quality_gate") or {}
    ownership = core_report.get("su2_boundary_ownership") or {}
    conformality = core_report.get("interface_conformality") or {}
    inner_boundary = core_report.get("inner_boundary") or {}
    physical_groups = core_report.get("physical_groups") or {}
    loop_status = str(loop_closure.get("status") or "")

    hard_blockers: list[str] = []
    if loop_status != "core_facing_loop_cap_surface_ready_core_mesh_pending":
        hard_blockers.append("loop_cap_surface_not_ready")
    if core_report.get("status") != "meshed":
        hard_blockers.append("core_probe_not_meshed")
    if quality_gate.get("status") != "pass":
        hard_blockers.append("core_mesh_quality_not_pass")
    if ownership.get("status") not in {"pass", None}:
        hard_blockers.append("core_su2_boundary_ownership_not_pass")
    if conformality.get("status") == "remeshed":
        hard_blockers.append("core_inner_boundary_not_preserved")
    if "core_wall_loop_cap" not in (inner_boundary.get("marker_counts") or {}):
        hard_blockers.append("core_wall_loop_cap_marker_missing_from_core_mesh")
    if "fluid_core" not in physical_groups:
        hard_blockers.append("fluid_core_physical_group_missing")
    if (
        inner_surface_audit is not None
        and int(
            (inner_surface_audit.get("welded_topology") or {}).get("bad_edge_count")
            or 0
        )
        > 0
    ):
        hard_blockers.append("core_inner_surface_geometric_duplicate_nonmanifold")

    pending_blockers = [
        "merged_mixed_bl_core_su2_mesh_missing",
        "near_wall_yplus_not_postprocessed",
        "solver_ladder_not_run",
    ]
    status = (
        "core_mesh_probe_pass_merged_handoff_pending"
        if not hard_blockers
        else "core_mesh_probe_blocked"
    )
    return {
        "schema_version": "wo006r12_loop_cap_core_mesh.v1",
        "status": status,
        "loop_cap_status": (loop_closure.get("post_cap_topology") or {}).get("status"),
        "core_mesh_quality_status": quality_gate.get("status"),
        "core_mesh_marker_status": ownership.get("status"),
        "core_inner_conformality_status": conformality.get("status"),
        "mesh_path": core_report.get("mesh_path"),
        "su2_path": core_report.get("su2_path"),
        "node_count": core_report.get("node_count"),
        "volume_element_count": core_report.get("volume_element_count"),
        "volume_element_type_counts": core_report.get("volume_element_type_counts"),
        "inner_marker_counts": inner_boundary.get("marker_counts"),
        "farfield_marker_counts": (core_report.get("farfield") or {}).get("marker_counts"),
        "physical_group_names": sorted(physical_groups),
        "mesh_quality_gate": quality_gate,
        "quality_metrics": {
            "tetra_element_count": (core_report.get("quality_metrics") or {}).get(
                "tetra_element_count"
            ),
            "pyramid_element_count": (core_report.get("quality_metrics") or {}).get(
                "pyramid_element_count"
            ),
            "non_positive_min_sicn_count": (core_report.get("quality_metrics") or {}).get(
                "non_positive_min_sicn_count"
            ),
            "non_positive_min_sige_count": (core_report.get("quality_metrics") or {}).get(
                "non_positive_min_sige_count"
            ),
            "non_positive_volume_count": (core_report.get("quality_metrics") or {}).get(
                "non_positive_volume_count"
            ),
            "min_sicn": (core_report.get("quality_metrics") or {}).get("min_sicn"),
            "min_sige": (core_report.get("quality_metrics") or {}).get("min_sige"),
            "min_volume": (core_report.get("quality_metrics") or {}).get("min_volume"),
        },
        "su2_boundary_ownership": ownership,
        "interface_conformality": conformality,
        "bl_block_coupling": core_report.get("bl_block_coupling"),
        "inner_surface_audit": None
        if inner_surface_audit is None
        else dict(inner_surface_audit),
        "blockers": [*hard_blockers, *pending_blockers],
        "hard_blockers": hard_blockers,
        "pending_blockers": pending_blockers,
        "coefficient_interpretable": False,
        "engineering_read": (
            "The R11 loop-cap surface can be tet-filled with preserved markers; "
            "the next blocker is writing a merged mixed BL+core SU2 handoff plus y+."
            if not hard_blockers
            else "The loop-cap core mesh probe is still blocked; do not run SU2."
        ),
    }


def build_probe_summary(
    *,
    loop_closure: Mapping[str, Any],
    core_report: Mapping[str, Any],
    inner_surface_audit: Mapping[str, Any] | None,
    output_dir: Path,
    elapsed_s: float,
) -> dict[str, Any]:
    core_mesh = summarize_loop_cap_core_mesh_probe(
        loop_closure=loop_closure,
        core_report=core_report,
        inner_surface_audit=inner_surface_audit,
    )
    ready = core_mesh["status"] == "core_mesh_probe_pass_merged_handoff_pending"
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "loop_cap_core_mesh_probe_pass_not_handoff"
            if ready
            else "loop_cap_core_mesh_probe_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "loop_closure": dict(loop_closure),
        "loop_cap_core_mesh": core_mesh,
        "core_report_path": str(output_dir / "core_probe_artifacts" / "loop_cap_core_probe_report.json"),
        "output_dir": str(output_dir),
        "elapsed_s": elapsed_s,
        "blocked_claims": [
            "merged BL+core SU2 handoff",
            "postprocessed near-wall y+",
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": core_mesh["engineering_read"],
    }


def run_loop_cap_core_mesh_probe(
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
    boundary_rows = merged_boundary_face_rows(block, candidate)
    core_rows = core_facing_rows(boundary_rows)
    loops = open_edge_loops(core_rows)
    cap_surface = build_core_facing_loop_cap_surface(candidate, core_rows, loops)
    validate_surface_mesh(
        cap_surface,
        allowed_markers=frozenset(cap_surface.marker_counts()),
        required_markers=(),
    )
    inner_surface_audit = audit_inner_surface_geometry(cap_surface)
    loop_closure = summarize_core_facing_loop_closure(block, candidate)
    farfield = build_farfield_box_surface(
        cap_surface,
        upstream_factor=2.0,
        downstream_factor=4.0,
        lateral_factor=2.0,
        vertical_factor=2.0,
    )
    probe_dir = output_dir / "core_probe_artifacts"
    probe_dir.mkdir(parents=True, exist_ok=True)
    try:
        core_report = write_core_tet_mesh_from_inner_surface(
            cap_surface,
            farfield,
            probe_dir / "loop_cap_core_probe.msh",
            su2_path=probe_dir / "loop_cap_core_probe.su2",
            mesh_size=mesh_size,
            farfield_mesh_size=farfield_mesh_size,
            preserve_boundary_mesh=True,
            preserved_boundary_representation="triangulated",
            gmsh_threads=gmsh_threads,
            mesh_algorithm3d=10,
            owned_bl_block=block,
        )
    except Exception as exc:  # pragma: no cover - exercised by real Gmsh failures.
        core_report = {
            "status": "failed",
            "route": "mesh_native_inner_surface_core_tet_probe",
            "failure_code": "loop_cap_core_mesh_generation_failed",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "mesh_quality_gate": {
                "status": "fail",
                "blockers": ["core_mesh_generation_exception"],
            },
            "su2_boundary_ownership": None,
            "interface_conformality": {"status": "not_run"},
            "inner_boundary": {"marker_counts": cap_surface.marker_counts()},
            "inner_surface_audit": inner_surface_audit,
            "farfield": {"marker_counts": farfield.marker_counts()},
            "physical_groups": {},
        }
    write_json(probe_dir / "loop_cap_core_probe_report.json", core_report)
    summary = build_probe_summary(
        loop_closure=loop_closure,
        core_report=core_report,
        inner_surface_audit=inner_surface_audit,
        output_dir=output_dir,
        elapsed_s=time.monotonic() - start,
    )
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "loop_cap_core_mesh_probe_summary.json", summary)
    write_csv(
        output_dir / "core_mesh_marker_counts.csv",
        marker_count_rows(summary["loop_cap_core_mesh"].get("inner_marker_counts") or {}),
    )
    (output_dir / "loop_cap_core_mesh_probe_report.md").write_text(
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
    summary = run_loop_cap_core_mesh_probe(
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
    write_json(output_dir / "loop_cap_core_mesh_probe_summary.json", summary)
    (output_dir / "loop_cap_core_mesh_probe_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def marker_count_rows(marker_counts: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"marker": marker, "face_count": count}
        for marker, count in sorted(marker_counts.items())
    ]


def audit_inner_surface_geometry(surface) -> dict[str, Any]:
    duplicate_groups = _duplicate_coordinate_groups(surface)
    welded = _welded_topology_audit(surface)
    return {
        "schema_version": "wo006r12_inner_surface_geometry_audit.v1",
        "vertex_count": len(surface.vertices),
        "face_count": len(surface.faces),
        "exact_duplicate_group_count": len(duplicate_groups),
        "exact_duplicate_vertex_count": sum(len(group["indices"]) - 1 for group in duplicate_groups),
        "duplicate_samples": duplicate_groups[:20],
        "welded_topology": welded,
        "engineering_read": (
            "The core-facing surface is geometrically safe for PLC meshing."
            if not duplicate_groups and welded["bad_edge_count"] == 0
            else "The core-facing surface is topologically closed by index, but exact "
            "duplicate coordinates create non-manifold geometry after welding; this "
            "can trigger Gmsh self-intersecting facet failures."
        ),
    }


def _duplicate_coordinate_groups(surface, *, digits: int = 12) -> list[dict[str, Any]]:
    groups: dict[tuple[float, float, float], list[int]] = {}
    for index, point in enumerate(surface.vertices):
        key = tuple(round(value, digits) for value in point)
        groups.setdefault(key, []).append(index)
    return [
        {
            "coordinate": list(key),
            "indices": indices,
        }
        for key, indices in sorted(groups.items())
        if len(indices) > 1
    ]


def _welded_topology_audit(surface, *, digits: int = 12) -> dict[str, Any]:
    key_to_new: dict[tuple[float, float, float], int] = {}
    remap: dict[int, int] = {}
    welded_vertices: list[tuple[float, float, float]] = []
    for index, point in enumerate(surface.vertices):
        key = tuple(round(value, digits) for value in point)
        if key not in key_to_new:
            key_to_new[key] = len(welded_vertices)
            welded_vertices.append(point)
        remap[index] = key_to_new[key]

    edge_counts: dict[tuple[int, int], int] = {}
    edge_faces: dict[tuple[int, int], list[dict[str, Any]]] = {}
    degenerate_face_count = 0
    for face_index, face in enumerate(surface.faces):
        welded_nodes = tuple(remap[int(node)] for node in face.nodes)
        if len(set(welded_nodes)) != len(welded_nodes):
            degenerate_face_count += 1
            continue
        for left, right in zip(welded_nodes, [*welded_nodes[1:], welded_nodes[0]]):
            edge = tuple(sorted((left, right)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
            edge_faces.setdefault(edge, []).append(
                {
                    "face_index": face_index,
                    "marker": face.marker,
                    "original_nodes": list(face.nodes),
                    "welded_nodes": list(welded_nodes),
                }
            )
    bad_edges = [
        {
            "edge": list(edge),
            "count": count,
            "coordinates": [list(welded_vertices[node]) for node in edge],
            "faces": edge_faces[edge],
        }
        for edge, count in sorted(edge_counts.items())
        if count != 2
    ]
    return {
        "welded_vertex_count": len(welded_vertices),
        "degenerate_face_count_after_weld": degenerate_face_count,
        "bad_edge_count": len(bad_edges),
        "open_edge_count": sum(1 for item in bad_edges if item["count"] == 1),
        "nonmanifold_edge_count": sum(1 for item in bad_edges if item["count"] > 2),
        "bad_edge_samples": bad_edges[:20],
    }


def render_report(summary: Mapping[str, Any]) -> str:
    core = summary.get("loop_cap_core_mesh") or {}
    quality = core.get("quality_metrics") or {}
    audit = core.get("inner_surface_audit") or {}
    welded = audit.get("welded_topology") or {}
    return "\n".join(
        [
            "# WO-006R12 Loop-Cap Core Mesh Probe",
            "",
            "This is core mesh evidence only, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary.get('goal_status')}`",
            f"CFD_STATUS: `{summary.get('cfd_status')}`",
            f"- verdict: `{summary.get('verdict')}`",
            f"- status: `{core.get('status')}`",
            f"- nodes: `{core.get('node_count')}`",
            f"- volume elements: `{core.get('volume_element_count')}`",
            f"- quality status: `{core.get('core_mesh_quality_status')}`",
            f"- SU2 boundary ownership: `{core.get('core_mesh_marker_status')}`",
            f"- inner markers: `{core.get('inner_marker_counts')}`",
            f"- exact duplicate coordinate groups: `{audit.get('exact_duplicate_group_count')}`",
            f"- welded bad edges: `{welded.get('bad_edge_count')}`",
            f"- physical groups: `{core.get('physical_group_names')}`",
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
