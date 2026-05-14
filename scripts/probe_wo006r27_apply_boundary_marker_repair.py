#!/usr/bin/env python3
"""Apply the WO-006R26 boundary marker repair to the mixed SU2 handoff.

R26 classified every remaining R25 unmarked exterior face and produced a
bounded policy: promote those localized solid-closure faces to ``wing_wall``.
This probe applies that policy to a fresh R25-style in-memory handoff, writes a
repaired SU2 mesh, and reruns the final volume-boundary marker audit.

This is still a mesh-handoff gate.  It does not run SU2 and does not provide a
coarse/medium/fine CL/CD/Cm grid-convergence ladder.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
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
import probe_wo006r26_remaining_boundary_leak_localization as r26  # noqa: E402
from run_wo006r2_cfd_recovery_campaign import build_yplus_nearwall_summary  # noqa: E402
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r27_apply_boundary_marker_repair_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r27_apply_boundary_marker_repair_probe"
DEFAULT_R25_OUTPUT_DIR = WO006_ROOT / "wo006r25_culled_mixed_su2_handoff_probe"

SU2_TRIANGLE = r25.SU2_TRIANGLE
SU2_QUAD = r25.SU2_QUAD
SU2_TETRA = r25.SU2_TETRA


def apply_boundary_marker_repair(
    *,
    markers: Mapping[str, Sequence[Mapping[str, Any]]],
    leak_records: Sequence[Mapping[str, Any]],
    target_marker: str = "wing_wall",
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    repaired = {marker: [dict(face) for face in faces] for marker, faces in markers.items()}
    repaired.setdefault(target_marker, [])
    existing = {
        (marker, r25._face_node_key(r25._parse_nodes(face["nodes"])))
        for marker, faces in repaired.items()
        for face in faces
    }
    applied_by_classification: dict[str, int] = {}
    skipped = 0
    duplicate = 0
    for record in leak_records:
        if str(record.get("recommended_marker") or "") != target_marker:
            skipped += 1
            continue
        face_nodes = tuple(int(node) for node in r25._parse_nodes(record.get("face_nodes")))
        marker_key = (target_marker, r25._face_node_key(face_nodes))
        if marker_key in existing:
            duplicate += 1
            continue
        if len(face_nodes) == 3:
            element_type = SU2_TRIANGLE
        elif len(face_nodes) == 4:
            element_type = SU2_QUAD
        else:
            skipped += 1
            continue
        repaired[target_marker].append({"element_type": element_type, "nodes": face_nodes})
        existing.add(marker_key)
        classification = str(record.get("classification") or "unknown")
        applied_by_classification[classification] = (
            applied_by_classification.get(classification, 0) + 1
        )
    applied_count = sum(applied_by_classification.values())
    return repaired, {
        "schema_version": "wo006r27_boundary_marker_repair.v1",
        "status": "applied" if applied_count > 0 and skipped == 0 else "partial_or_blocked",
        "target_marker": target_marker,
        "applied_face_count": applied_count,
        "skipped_face_count": skipped,
        "duplicate_face_count": duplicate,
        "applied_by_classification": dict(sorted(applied_by_classification.items())),
        "policy": (
            "Only R26 leak records whose recommended marker is wing_wall are added "
            "to the final mixed SU2 boundary marker set."
        ),
    }


def build_probe_summary(
    *,
    output_dir: Path,
    geometry_source: str,
    handoff: Mapping[str, Any],
    boundary_audit: Mapping[str, Any],
    quality: Mapping[str, Any],
    marker_repair: Mapping[str, Any],
    yplus: Mapping[str, Any],
) -> dict[str, Any]:
    handoff_pass = (
        handoff.get("status") == "mixed_su2_handoff_written"
        and boundary_audit.get("status") == "pass"
        and quality.get("status") == "pass"
        and int(marker_repair.get("applied_face_count") or 0) > 0
    )
    blockers = []
    if handoff.get("status") != "mixed_su2_handoff_written":
        blockers.append("mixed_su2_handoff_not_written")
    blockers.extend(str(item) for item in boundary_audit.get("blockers") or [])
    blockers.extend(str(item) for item in quality.get("blockers") or [])
    if marker_repair.get("status") != "applied":
        blockers.append("boundary_marker_repair_not_fully_applied")
    blockers.extend(
        [
            "solver_postprocessed_surface_yplus_missing",
            "su2_solver_ladder_not_run",
        ]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "mixed_su2_handoff_marker_quality_pass_solver_ladder_pending"
            if handoff_pass
            else "mixed_su2_handoff_marker_repair_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "output_dir": str(output_dir),
        "geometry_source": geometry_source,
        "mixed_su2_handoff": dict(handoff),
        "boundary_marker_repair": dict(marker_repair),
        "volume_boundary_marker_audit": dict(boundary_audit),
        "mixed_mesh_quality": dict(quality),
        "near_wall_yplus": dict(yplus),
        "blockers": sorted(set(blockers)),
        "blocked_claims": [
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "grid convergence",
            "Baseline A drag or power truth",
        ],
        "engineering_read": (
            "The R26 boundary marker repair is applied and the mixed SU2 handoff "
            "passes marker and positive-volume quality gates. This is ready for "
            "a bounded solver route-smoke, not for CFD completion or grid "
            "convergence claims."
            if handoff_pass
            else "The marker repair did not clear the mixed SU2 handoff gate. "
            "Do not run SU2 until the marker/quality audit is clear."
        ),
    }


def run_probe(
    *,
    output_dir: Path,
    clean: bool = True,
    r25_output_dir: Path = DEFAULT_R25_OUTPUT_DIR,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
    merge_digits: int = 10,
) -> dict[str, Any]:
    start = time.monotonic()
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    state = r26.build_r25_state_with_provenance(
        r25_output_dir=r25_output_dir,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
        merge_digits=merge_digits,
    )
    classifier_index = r26.build_classifier_index(
        candidate_vertices=state["candidate_vertices"],
        candidate_boundary_rows=state["candidate_boundary_rows"],
        candidate_face_records=state["candidate_face_records"],
        core_vertices=state["core_vertices"],
        core_triangle_rows=state["core_triangle_rows"],
        loop_cap_elements=state["loop_cap_elements"],
        writer_nodes=state["nodes"],
        digits=merge_digits,
    )
    leak_records = r26.collect_remaining_boundary_leak_records(
        nodes=state["nodes"],
        elements=state["elements"],
        markers=state["markers"],
        classifier_index=classifier_index,
        digits=merge_digits,
    )
    repaired_markers, marker_repair = apply_boundary_marker_repair(
        markers=state["markers"],
        leak_records=leak_records,
    )
    boundary_audit = r25.audit_volume_boundary_markers(
        elements=state["elements"],
        markers=repaired_markers,
        nodes=state["nodes"],
    )
    quality = r25.evaluate_mixed_mesh_quality(
        nodes=state["nodes"],
        elements=state["elements"],
    )
    mesh_path = output_dir / "culled_global_star_mixed_handoff_r27_repaired.su2"
    r25.write_su2_mesh(
        path=mesh_path,
        nodes=state["nodes"],
        elements=state["elements"],
        markers=repaired_markers,
    )
    volume_type_counts: dict[str, int] = {}
    for element in state["elements"]:
        element_type = str(element["element_type"])
        volume_type_counts[element_type] = volume_type_counts.get(element_type, 0) + 1
    handoff = {
        "schema_version": "wo006r27_mixed_su2_handoff.v1",
        "status": "mixed_su2_handoff_written",
        "mesh_path": str(mesh_path),
        "node_count": len(state["nodes"]),
        "volume_element_count": len(state["elements"]),
        "volume_element_type_counts": dict(sorted(volume_type_counts.items())),
        "marker_counts": {
            marker: len(faces) for marker, faces in sorted(repaired_markers.items())
        },
        "surface_ownership": {
            "wing_wall": (
                "physical Baseline A wall plus R26-localized tip/wake solid "
                "closure exterior faces"
            ),
            "farfield": "R13/R25 repaired-loop-cap core-mesh farfield box",
            "bl/core interface": "internalized by the R25 coordinate-merged mixed handoff",
        },
    }
    geometry = r25.load_campaign_geometry(
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    summary = build_probe_summary(
        output_dir=output_dir,
        geometry_source=str(state["geometry_source"]),
        handoff=handoff,
        boundary_audit=boundary_audit,
        quality=quality,
        marker_repair=marker_repair,
        yplus={
            **build_yplus_nearwall_summary(geometry),
            "status": "estimate_ready_not_solver_postprocessed",
        },
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
    summary["upstream_r26_leak_localization"] = {
        "leak_count": len(leak_records),
        "leak_counts_by_classification": r26._count_values(
            record.get("classification") for record in leak_records
        ),
        "leak_counts_by_adjacent_source": r26._count_values(
            record.get("adjacent_source") for record in leak_records
        ),
        "total_unmarked_area_m2": sum(
            float(record.get("area_m2") or 0.0) for record in leak_records
        ),
    }
    summary["elapsed_s"] = time.monotonic() - start
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "boundary_marker_repair_report.json", marker_repair)
    write_json(output_dir / "mixed_su2_handoff_report.json", handoff)
    (output_dir / "boundary_marker_repair_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    handoff = summary.get("mixed_su2_handoff") or {}
    audit = summary.get("volume_boundary_marker_audit") or {}
    repair = summary.get("boundary_marker_repair") or {}
    return "\n".join(
        [
            "# WO-006R27 Apply Boundary Marker Repair Probe",
            "",
            "This is marker/mesh handoff evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary.get('goal_status')}`",
            f"CFD_STATUS: `{summary.get('cfd_status')}`",
            f"- verdict: `{summary.get('verdict')}`",
            f"- mesh: `{handoff.get('mesh_path')}`",
            f"- nodes / volume elements: `{handoff.get('node_count')}` / `{handoff.get('volume_element_count')}`",
            f"- marker counts: `{handoff.get('marker_counts')}`",
            f"- applied marker faces: `{repair.get('applied_face_count')}`",
            f"- boundary marker audit: `{audit.get('status')}`",
            f"- unmarked / extra marker faces: `{audit.get('unmarked_boundary_face_count')}` / `{audit.get('extra_marker_face_count')}`",
            f"- blockers: `{summary.get('blockers')}`",
            "",
            f"Engineering read: {summary.get('engineering_read')}",
            "",
        ]
    )


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--r25-output-dir", type=Path, default=DEFAULT_R25_OUTPUT_DIR)
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    parser.add_argument("--merge-digits", type=int, default=10)
    args = parser.parse_args(argv)
    summary = run_probe(
        output_dir=args.output_dir,
        clean=not args.no_clean,
        r25_output_dir=args.r25_output_dir,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        merge_digits=args.merge_digits,
    )
    handoff = summary["mixed_su2_handoff"]
    audit = summary["volume_boundary_marker_audit"]
    repair = summary["boundary_marker_repair"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "mesh_path": handoff["mesh_path"],
                "node_count": handoff["node_count"],
                "volume_element_count": handoff["volume_element_count"],
                "marker_counts": handoff["marker_counts"],
                "applied_marker_faces": repair["applied_face_count"],
                "boundary_marker_status": audit["status"],
                "unmarked_boundary_faces": audit["unmarked_boundary_face_count"],
                "extra_marker_faces": audit["extra_marker_face_count"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
