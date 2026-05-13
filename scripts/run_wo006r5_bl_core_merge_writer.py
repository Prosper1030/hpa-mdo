#!/usr/bin/env python3
"""Run WO-006R5 BL+core merge campaign.

This is a mesh ownership campaign, not a CFD-result promotion. It writes
near-wall BL and preserved-core probe artifacts, audits the BL/core interface,
and refuses ``bl_mesh_handoff.v1.json`` unless a conformal mixed BL+core SU2
mesh actually exists.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    evaluate_boundary_layer_core_merge_gate,
    write_boundary_layer_block_core_tet_mesh,
)
from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    build_boundary_layer_core_interface_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.su2_structured import (  # noqa: E402
    parse_su2_marker_summary,
    write_wing_boundary_layer_block_su2,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    Face,
    SurfaceMesh,
    build_farfield_box_surface,
    validate_surface_mesh,
)
from run_wo006r1_go_baseline_a_cfd_bridge import (  # noqa: E402
    DESIGN_GROSS_MASS_KG,
    PIPELINE_FULL_SPAN_M,
    PIPELINE_HALF_SPAN_M,
    build_current_go_wing_surface,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import (  # noqa: E402
    WO006_ROOT,
    build_owned_bl_block_summary,
    build_surface_geometry_deviation,
)


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r5_bl_core_merge"
OFFICIAL_FORMAT_SOURCES = {
    "su2_mesh_file": "https://su2code.github.io/docs_v7/Mesh-File/",
    "su2_markers_and_bc": "https://su2code.github.io/docs_v7/Markers-and-BC/",
    "gmsh_texinfo": "https://gmsh.info/doc/texinfo/",
}
INTERFACE_CSV_FIELDS = (
    "audit_scope",
    "marker",
    "expected_element_count",
    "observed_element_count",
    "preserved",
    "unmatched_bl_boundary_faces",
    "unmatched_core_interface_faces",
    "can_merge",
    "notes",
)


def run_campaign(
    *,
    output_dir: Path,
    clean: bool = True,
    run_core_probe: bool = True,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
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
    core_interface = build_boundary_layer_core_interface_surface(block)
    validate_surface_mesh(
        core_interface,
        allowed_markers=frozenset({"bl_outer_interface", "wake_cut", "span_cap"}),
        required_markers=("bl_outer_interface", "wake_cut", "span_cap"),
    )

    bl_probe_report = write_wing_boundary_layer_block_su2(
        block,
        output_dir / "owned_bl_block_probe.su2",
    )
    _write_json(output_dir / "owned_bl_block_writer_probe.json", bl_probe_report)

    core_report = (
        _run_preserved_interface_core_probe(block, core_interface, output_dir=output_dir)
        if run_core_probe
        else _skipped_core_probe_report(output_dir=output_dir)
    )
    _write_json(output_dir / "core_probe_summary.json", core_report)

    non_wall_probe = probe_full_non_wall_boundary_surface(block)
    _write_json(output_dir / "full_non_wall_boundary_surface_probe.json", non_wall_probe)

    merge_gate = evaluate_boundary_layer_core_merge_gate(
        core_report,
        merged_mesh_path=None,
    )
    _write_json(output_dir / "bl_core_merge_gate.json", merge_gate)

    deviation_report = build_surface_geometry_deviation(
        build_current_go_wing_surface(geometry),
        block,
    )
    geometry_deviation_report = render_geometry_deviation_report(deviation_report)
    (output_dir / "geometry_deviation_report.md").write_text(
        geometry_deviation_report,
        encoding="utf-8",
    )

    block_summary = build_owned_bl_block_summary(block, core_interface)
    marker_audit = build_marker_ownership_audit(
        bl_probe_report=bl_probe_report,
        core_report=core_report,
        merge_gate=merge_gate,
    )
    _write_json(output_dir / "marker_ownership_audit.json", marker_audit)

    interface_rows = build_interface_conformality_rows(
        core_report=core_report,
        non_wall_probe=non_wall_probe,
    )
    write_csv(output_dir / "interface_conformality_audit.csv", interface_rows)

    mesh_quality_gate = build_mesh_quality_gate(
        block_summary=block_summary,
        core_report=core_report,
        merge_gate=merge_gate,
    )
    _write_json(output_dir / "mesh_quality_gate.json", mesh_quality_gate)

    su2_readability = build_su2_readability_smoke(
        bl_probe_report=bl_probe_report,
        core_report=core_report,
        merge_gate=merge_gate,
    )
    _write_json(output_dir / "su2_readability_smoke.json", su2_readability)

    limitation = build_limitation_evidence(
        core_report=core_report,
        merge_gate=merge_gate,
        bl_probe_report=bl_probe_report,
        non_wall_probe=non_wall_probe,
    )
    _write_json(output_dir / "merge_limitation_evidence.json", limitation)

    blockers = build_blocker_rows(
        core_report=core_report,
        merge_gate=merge_gate,
        non_wall_probe=non_wall_probe,
        mesh_quality_gate=mesh_quality_gate,
        su2_readability=su2_readability,
    )
    write_csv(output_dir / "blocker_register.csv", blockers)

    decision = build_route_decision(
        geometry=geometry,
        block_summary=block_summary,
        deviation_report=deviation_report,
        merge_gate=merge_gate,
        limitation=limitation,
        marker_audit=marker_audit,
        mesh_quality_gate=mesh_quality_gate,
        su2_readability=su2_readability,
        non_wall_probe=non_wall_probe,
    )
    _write_json(output_dir / "route_decision.json", decision)
    (output_dir / "bl_core_merge_report.md").write_text(
        render_bl_core_merge_report(
            decision=decision,
            marker_audit=marker_audit,
            mesh_quality_gate=mesh_quality_gate,
            su2_readability=su2_readability,
            blockers=blockers,
        ),
        encoding="utf-8",
    )
    (output_dir / "next_goal.md").write_text(render_next_goal(decision), encoding="utf-8")
    return decision


def _run_preserved_interface_core_probe(
    block,
    core_interface,
    *,
    output_dir: Path,
) -> dict[str, Any]:
    probe_dir = output_dir / "core_probe_artifacts" / "preserved_interface_probe"
    farfield = build_farfield_box_surface(
        core_interface,
        upstream_factor=2.0,
        downstream_factor=4.0,
        lateral_factor=2.0,
        vertical_factor=2.0,
    )
    report = write_boundary_layer_block_core_tet_mesh(
        block,
        farfield,
        probe_dir / "core_preserved_interface_probe.msh",
        su2_path=probe_dir / "core_preserved_interface_probe.su2",
        mesh_size=1.0,
        farfield_mesh_size=8.0,
        preserve_boundary_mesh=True,
        gmsh_threads=4,
        mesh_algorithm3d=1,
    )
    _write_json(probe_dir / "core_preserved_interface_probe_report.json", report)
    return report


def _skipped_core_probe_report(*, output_dir: Path) -> dict[str, Any]:
    return {
        "status": "not_run",
        "route": "wo006r5_preserved_interface_core_probe",
        "mesh_path": None,
        "su2_path": None,
        "output_dir": str(output_dir),
        "reason": "run_core_probe_false",
        "mesh_quality_gate": {"status": "not_run", "blockers": ["core_probe_not_run"]},
        "interface_conformality": {
            "status": "not_run",
            "can_merge_with_owned_bl_block": False,
            "remeshed_markers": [],
        },
        "bl_block_coupling": {
            "status": "not_run",
            "can_merge_core_with_bl_block": False,
            "unmatched_core_interface_face_count": None,
            "unmatched_bl_boundary_face_count": None,
        },
    }


def probe_full_non_wall_boundary_surface(block) -> dict[str, Any]:
    """Test the tempting but invalid 'all non-wall BL boundary is core interface' route."""
    surface = SurfaceMesh(
        vertices=list(block.vertices),
        faces=[
            Face(nodes=tuple(face.nodes), marker=face.marker)
            for face in block.boundary_faces
            if face.marker != "wing_wall"
        ],
        metadata={
            "surface_role": "boundary_layer_full_non_wall_boundary_probe",
            "engineering_role": (
                "Check whether all non-wall BL boundary faces can be used directly "
                "as a closed core inner boundary."
            ),
        },
    )
    try:
        validate_surface_mesh(
            surface,
            allowed_markers=frozenset({"bl_outer_interface", "wake_cut", "span_cap"}),
            required_markers=("bl_outer_interface", "wake_cut", "span_cap"),
        )
    except ValueError as exc:
        return {
            "schema_version": "wo006r5_full_non_wall_boundary_surface_probe.v1",
            "status": "not_watertight",
            "can_use_as_core_inner_boundary": False,
            "marker_counts": surface.marker_counts(),
            "error": str(exc),
            "engineering_read": (
                "The full non-wall BL boundary is not a closed core inner surface. "
                "It cannot be sent directly to Gmsh as the conformal core boundary."
            ),
        }
    return {
        "schema_version": "wo006r5_full_non_wall_boundary_surface_probe.v1",
        "status": "watertight",
        "can_use_as_core_inner_boundary": True,
        "marker_counts": surface.marker_counts(),
        "engineering_read": "Full non-wall BL boundary passed the closed-surface preflight.",
    }


def build_limitation_evidence(
    *,
    core_report: Mapping[str, Any],
    merge_gate: Mapping[str, Any],
    bl_probe_report: Mapping[str, Any],
    non_wall_probe: Mapping[str, Any],
) -> dict[str, Any]:
    coupling = core_report.get("bl_block_coupling") or {}
    conformality = core_report.get("interface_conformality") or {}
    return {
        "schema_version": "wo006r5_merge_limitation_evidence.v1",
        "route": "mesh_native_owned_bl_block_plus_preserved_core_probe",
        "verdict": "blocked" if merge_gate.get("status") != "pass" else "handoff_ready",
        "external_shape_changed": False,
        "final_handoff_written": False,
        "blockers": list(merge_gate.get("blockers") or []),
        "owned_bl_block_probe": {
            "mesh_path": bl_probe_report.get("mesh_path"),
            "node_count": bl_probe_report.get("node_count"),
            "volume_element_count": bl_probe_report.get("volume_element_count"),
            "marker_summary": bl_probe_report.get("marker_summary"),
            "caveats": bl_probe_report.get("caveats"),
        },
        "core_probe": {
            "mesh_path": core_report.get("mesh_path"),
            "su2_path": core_report.get("su2_path"),
            "status": core_report.get("status"),
            "interface_conformality": conformality,
            "bl_block_coupling": coupling,
            "mesh_quality_gate": core_report.get("mesh_quality_gate"),
        },
        "full_non_wall_boundary_probe": non_wall_probe,
        "smallest_current_limitation": (
            "The current preserved-core route can be used as evidence only. The "
            "core interface envelope is preserved, but the preserved core still "
            "fails quality/coupling gates and the full non-wall BL boundary is not "
            "a watertight core inner surface."
        ),
        "engineering_read": (
            "A no-slip BL mesh is not credible merely because the wall hex block exists. "
            "The wake and span-cap load paths between near-wall cells and the outer core "
            "must be conformal, or SU2 would see artificial gaps/internal boundaries."
        ),
    }


def build_route_decision(
    *,
    geometry,
    block_summary: Mapping[str, Any],
    deviation_report: Mapping[str, Any],
    merge_gate: Mapping[str, Any],
    limitation: Mapping[str, Any],
    marker_audit: Mapping[str, Any],
    mesh_quality_gate: Mapping[str, Any],
    su2_readability: Mapping[str, Any],
    non_wall_probe: Mapping[str, Any],
) -> dict[str, Any]:
    handoff_ready = (
        merge_gate.get("can_write_bl_mesh_handoff") is True
        and marker_audit.get("status") == "pass"
        and mesh_quality_gate.get("status") == "pass"
        and su2_readability.get("status") == "pass"
    )
    verdict = classify_verdict(
        handoff_ready=handoff_ready,
        merge_gate=merge_gate,
        mesh_quality_gate=mesh_quality_gate,
        su2_readability=su2_readability,
        non_wall_probe=non_wall_probe,
    )
    return {
        "schema_version": "wo006r5_route_decision.v1",
        "verdict": verdict,
        "bl_mesh_handoff_written": False,
        "bl_mesh_handoff_path": None,
        "bl_core_handoff_exists": False,
        "coefficient_interpretable": False,
        "baseline_a_reopen_status": "not_evaluated",
        "external_shape_changed": False,
        "format_authority_sources": OFFICIAL_FORMAT_SOURCES,
        "authority_basis": {
            "design_gross_mass_kg": DESIGN_GROSS_MASS_KG,
            "pipeline_full_span_m": PIPELINE_FULL_SPAN_M,
            "pipeline_half_span_m": PIPELINE_HALF_SPAN_M,
            "sref_m2": geometry.reference.sref_full,
            "cref_m": geometry.reference.cref,
            "bref_m": geometry.reference.bref_full,
            "geometry_source": str(geometry.section_table_path),
            "blocked_legacy_mass_kg": "106.828608 kg is not current truth",
            "blocked_legacy_half_span_m": "16.5 m is not current pipeline truth",
        },
        "surface_deviation": deviation_report,
        "owned_bl_block_summary": {
            "block_cells": block_summary["block_cells"],
            "quality": block_summary["quality"],
            "boundary_layer": block_summary["boundary_layer"],
        },
        "merge_gate": merge_gate,
        "marker_ownership_audit": {
            "status": marker_audit.get("status"),
            "blockers": marker_audit.get("blockers"),
        },
        "mesh_quality_gate": {
            "status": mesh_quality_gate.get("status"),
            "blockers": mesh_quality_gate.get("blockers"),
        },
        "su2_readability_smoke": {
            "status": su2_readability.get("status"),
            "blockers": su2_readability.get("blockers"),
        },
        "limitation": limitation,
        "smallest_remaining_limitation": limitation["smallest_current_limitation"],
        "next_repair_target": (
            "Repair the conformal core interface route so the preserved core quality "
            "and BL/core coupling gates pass; only then write the mixed-element SU2 "
            "merge and emit bl_mesh_handoff.v1.json from the actual merged mesh."
        ),
        "blocked_claims": [
            "current BL/y+ CFD handoff",
            "drag or power truth",
            "Baseline A reopen evidence",
            "final aircraft sign-off",
        ],
    }


def classify_verdict(
    *,
    handoff_ready: bool,
    merge_gate: Mapping[str, Any],
    mesh_quality_gate: Mapping[str, Any],
    su2_readability: Mapping[str, Any],
    non_wall_probe: Mapping[str, Any],
) -> str:
    if handoff_ready:
        return "wo006r5_bl_core_handoff_ready"
    core_blockers = {
        "core_probe_not_meshed",
        "core_mesh_quality_gate_not_pass",
        "core_interface_not_preserved",
        "owned_bl_core_coupling_incomplete",
    }
    blockers = set(merge_gate.get("blockers") or [])
    quality_blockers = set(mesh_quality_gate.get("blockers") or [])
    if blockers & core_blockers or quality_blockers or (
        non_wall_probe.get("can_use_as_core_inner_boundary") is False
    ):
        return "wo006r5_core_merge_limitation_proven"
    if "merged_mixed_su2_mesh_missing" in blockers or su2_readability.get("status") != "pass":
        return "wo006r5_writer_limitation_proven"
    return "wo006r5_campaign_incomplete"


def build_marker_ownership_audit(
    *,
    bl_probe_report: Mapping[str, Any],
    core_report: Mapping[str, Any],
    merge_gate: Mapping[str, Any],
) -> dict[str, Any]:
    core_groups = core_report.get("physical_groups") or {}
    core_interface = core_report.get("interface_conformality") or {}
    marker_summary = bl_probe_report.get("marker_summary") or {}
    blockers: list[str] = []
    if "wing_wall" not in marker_summary:
        blockers.append("wing_wall_marker_missing_from_owned_bl_block")
    if "farfield" not in core_groups:
        blockers.append("farfield_marker_missing_from_core_probe")
    if merge_gate.get("can_write_bl_mesh_handoff") is not True:
        blockers.append("final_merged_marker_ownership_not_proven")
    return {
        "schema_version": "wo006r5_marker_ownership_audit.v1",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "final_mesh_boundary_markers": None,
        "owned_bl_block_markers": marker_summary,
        "core_probe_physical_groups": core_groups,
        "core_probe_interface_conformality": core_interface,
        "policy": (
            "The final SU2 mesh may expose wall/farfield boundary markers, but BL/core "
            "interface ownership must be proven as internal conformality evidence, not "
            "promoted as an aerodynamic boundary condition."
        ),
    }


def build_interface_conformality_rows(
    *,
    core_report: Mapping[str, Any],
    non_wall_probe: Mapping[str, Any],
) -> list[dict[str, str]]:
    conformality = core_report.get("interface_conformality") or {}
    coupling = core_report.get("bl_block_coupling") or {}
    markers = conformality.get("markers") if isinstance(conformality.get("markers"), dict) else {}
    unmatched_bl = coupling.get("unmatched_bl_boundary_face_counts_by_marker") or {}
    unmatched_core = coupling.get("unmatched_core_interface_face_counts_by_marker") or {}
    rows: list[dict[str, str]] = []
    for marker in ("bl_outer_interface", "wake_cut", "span_cap"):
        marker_info = markers.get(marker, {}) if isinstance(markers, dict) else {}
        rows.append(
            {
                "audit_scope": "preserved_core_interface_envelope",
                "marker": marker,
                "expected_element_count": _str_or_empty(
                    marker_info.get("input_expected_element_count")
                ),
                "observed_element_count": _str_or_empty(
                    marker_info.get("generated_element_count")
                ),
                "preserved": str(bool(marker_info.get("preserved"))).lower(),
                "unmatched_bl_boundary_faces": _str_or_empty(unmatched_bl.get(marker)),
                "unmatched_core_interface_faces": _str_or_empty(unmatched_core.get(marker)),
                "can_merge": str(conformality.get("can_merge_with_owned_bl_block") is True).lower(),
                "notes": str(conformality.get("interpretation") or ""),
            }
        )
    rows.append(
        {
            "audit_scope": "full_non_wall_boundary_direct_core_probe",
            "marker": "all_non_wall",
            "expected_element_count": "",
            "observed_element_count": "",
            "preserved": "false",
            "unmatched_bl_boundary_faces": "",
            "unmatched_core_interface_faces": "",
            "can_merge": str(non_wall_probe.get("can_use_as_core_inner_boundary") is True).lower(),
            "notes": str(non_wall_probe.get("error") or non_wall_probe.get("engineering_read") or ""),
        }
    )
    return rows


def build_mesh_quality_gate(
    *,
    block_summary: Mapping[str, Any],
    core_report: Mapping[str, Any],
    merge_gate: Mapping[str, Any],
) -> dict[str, Any]:
    block_quality = block_summary.get("quality") or {}
    core_gate = core_report.get("mesh_quality_gate") or {}
    core_metrics = core_report.get("quality_metrics") or {}
    blockers: list[str] = []
    if int(block_quality.get("non_positive_volume_count") or 0) > 0:
        blockers.append("owned_bl_block_non_positive_volume")
    if int(block_quality.get("unowned_boundary_face_count") or 0) > 0:
        blockers.append("owned_bl_block_unowned_boundary_faces")
    if core_gate.get("status") != "pass":
        blockers.append("core_mesh_quality_gate_not_pass")
    if merge_gate.get("can_write_bl_mesh_handoff") is not True:
        blockers.append("merged_bl_core_quality_not_proven")
    return {
        "schema_version": "wo006r5_mesh_quality_gate.v1",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "owned_bl_block_quality": block_quality,
        "core_mesh_quality_gate": core_gate,
        "core_quality_metrics": core_metrics,
        "engineering_read": (
            "The owned BL block has positive estimated cell volumes, but the preserved "
            "core probe must also pass volume/SICN/SIGE quality before any handoff."
        ),
    }


def build_su2_readability_smoke(
    *,
    bl_probe_report: Mapping[str, Any],
    core_report: Mapping[str, Any],
    merge_gate: Mapping[str, Any],
) -> dict[str, Any]:
    probe_reads = {
        "owned_bl_block_probe": _parse_optional_su2(bl_probe_report.get("mesh_path")),
        "preserved_core_probe": _parse_optional_su2(core_report.get("su2_path")),
    }
    blockers = []
    if merge_gate.get("can_write_bl_mesh_handoff") is not True:
        blockers.append("merged_bl_core_su2_mesh_missing")
    return {
        "schema_version": "wo006r5_su2_readability_smoke.v1",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "final_mesh_path": None,
        "final_solver_run": False,
        "probe_parser_reads": probe_reads,
        "coefficient_interpretable": False,
        "reason": (
            "No final merged BL+core SU2 mesh exists, so only probe parser readability "
            "can be recorded. No solver coefficient is interpretable."
        ),
    }


def build_blocker_rows(
    *,
    core_report: Mapping[str, Any],
    merge_gate: Mapping[str, Any],
    non_wall_probe: Mapping[str, Any],
    mesh_quality_gate: Mapping[str, Any],
    su2_readability: Mapping[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for blocker in merge_gate.get("blockers") or []:
        rows.append(
            {
                "stage": "bl_core_merge_gate",
                "status": "blocked",
                "blocker": str(blocker),
                "evidence": json.dumps(merge_gate.get("evidence") or {}, sort_keys=True),
                "next_fix": "repair core interface quality/coupling before writing final handoff",
            }
        )
    for blocker in mesh_quality_gate.get("blockers") or []:
        rows.append(
            {
                "stage": "mesh_quality_gate",
                "status": "blocked",
                "blocker": str(blocker),
                "evidence": json.dumps(core_report.get("quality_metrics") or {}, sort_keys=True),
                "next_fix": "remove non-positive/invalid core elements without changing Baseline A shape",
            }
        )
    for blocker in su2_readability.get("blockers") or []:
        rows.append(
            {
                "stage": "su2_readability_smoke",
                "status": "blocked",
                "blocker": str(blocker),
                "evidence": json.dumps(su2_readability.get("probe_parser_reads") or {}, sort_keys=True),
                "next_fix": "emit one merged mixed-element SU2 mesh only after merge gates pass",
            }
        )
    if non_wall_probe.get("can_use_as_core_inner_boundary") is False:
        rows.append(
            {
                "stage": "full_non_wall_boundary_surface_probe",
                "status": "blocked",
                "blocker": "full_non_wall_boundary_not_watertight",
                "evidence": str(non_wall_probe.get("error") or ""),
                "next_fix": "define a closed core envelope/interface split instead of using all non-wall BL faces directly",
            }
        )
    return rows


def render_geometry_deviation_report(deviation_report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# WO-006R5 Geometry Deviation Report",
            "",
            f"- External authority files changed: `{deviation_report.get('external_authority_files_changed')}`",
            f"- Comparison: {deviation_report.get('comparison')}",
            f"- Wall vertex count: `{deviation_report.get('wall_vertex_count')}`",
            f"- Wing surface vertex count: `{deviation_report.get('wing_surface_vertex_count')}`",
            f"- Max nearest distance (m): `{deviation_report.get('max_nearest_distance_m')}`",
            f"- P95 nearest distance (m): `{deviation_report.get('p95_nearest_distance_m')}`",
            f"- Mean nearest distance (m): `{deviation_report.get('mean_nearest_distance_m')}`",
            "",
            str(deviation_report.get("interpretation") or ""),
            "",
        ]
    )


def render_bl_core_merge_report(
    *,
    decision: Mapping[str, Any],
    marker_audit: Mapping[str, Any],
    mesh_quality_gate: Mapping[str, Any],
    su2_readability: Mapping[str, Any],
    blockers: list[Mapping[str, str]],
) -> str:
    return "\n".join(
        [
            "# WO-006R5 BL+Core Merge Report",
            "",
            f"- Verdict: `{decision.get('verdict')}`",
            f"- BL+core handoff exists: `{decision.get('bl_core_handoff_exists')}`",
            f"- bl_mesh_handoff.v1.json emitted: `{decision.get('bl_mesh_handoff_written')}`",
            f"- Coefficients interpretable: `{decision.get('coefficient_interpretable')}`",
            f"- Marker ownership audit: `{marker_audit.get('status')}`",
            f"- Mesh quality gate: `{mesh_quality_gate.get('status')}`",
            f"- SU2 readability smoke: `{su2_readability.get('status')}`",
            "",
            "## Data Authority",
            "",
            "| Topic | Current authority | Blocked stale value |",
            "| --- | --- | --- |",
            "| Design gross mass | 98.5 kg | blocked suspect P1 screening aggregate |",
            "| Full span | 34.332286 m | 16.5 m half-span is not current truth |",
            "| Half span | 17.166143 m | 16.5 m |",
            "| Coefficients | non-interpretable | no-BL/probe/old smoke coefficients |",
            "",
            "## Format Sources",
            "",
            f"- SU2 mesh file: {OFFICIAL_FORMAT_SOURCES['su2_mesh_file']}",
            f"- SU2 markers and boundary conditions: {OFFICIAL_FORMAT_SOURCES['su2_markers_and_bc']}",
            f"- Gmsh manual: {OFFICIAL_FORMAT_SOURCES['gmsh_texinfo']}",
            "",
            "## Blockers",
            "",
            *[
                f"- `{row['stage']}`: `{row['blocker']}`"
                for row in blockers
            ],
            "",
            "## Engineering Caveat",
            "",
            "This campaign is mesh/ownership evidence only. Passing software tests or writing "
            "probe SU2 files does not establish wall shear, y+, convergence, grid-pair "
            "independence, drag truth, Baseline A reopen evidence, procurement truth, or "
            "final aircraft sign-off.",
            "",
        ]
    )


def render_next_goal(decision: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "/goal In /Volumes/Samsung SSD/hpa-mdo, execute WO-006R6: repair the current-GO conformal BL/core interface and mixed-element SU2 writer after WO-006R5.",
            "",
            "Start from `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r5_bl_core_merge/`.",
            "First resolve the preserved-core quality/coupling blockers without changing Baseline A external shape.",
            "Only emit `bl_mesh_handoff.v1.json` after one merged mixed-element SU2 mesh exists, marker ownership passes, interface unmatched counts are zero, SU2 readability passes, and coefficient interpretation remains explicitly blocked until y+/wall shear, convergence, and grid-pair evidence exist.",
            "",
            f"Previous verdict: `{decision.get('verdict')}`.",
            "",
        ]
    )


def write_csv(path: Path, rows: list[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = INTERFACE_CSV_FIELDS if path.name == "interface_conformality_audit.csv" else (
        "stage",
        "status",
        "blocker",
        "evidence",
        "next_fix",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _parse_optional_su2(path: Any) -> dict[str, Any]:
    if not isinstance(path, str) or not path:
        return {"status": "missing", "path": path}
    try:
        return {
            "status": "parsed",
            "path": path,
            "summary": parse_su2_marker_summary(path),
        }
    except Exception as exc:
        return {"status": "parse_failed", "path": path, "error": str(exc)}


def _str_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--skip-core-probe", action="store_true")
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    args = parser.parse_args(argv)

    decision = run_campaign(
        output_dir=args.output_dir,
        clean=not args.no_clean,
        run_core_probe=not args.skip_core_probe,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
    )
    print(json.dumps(decision, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
