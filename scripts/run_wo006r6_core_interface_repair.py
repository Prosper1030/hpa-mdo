#!/usr/bin/env python3
"""Run WO-006R6 core-interface repair campaign.

WO-006R6 is still a mesh-interface campaign, not a CFD coefficient promotion.
It may only emit ``bl_mesh_handoff.v1.json`` after a real merged BL+core SU2
mesh exists with zero unmatched interface faces, clean quality gates, marker
ownership, and final-mesh SU2 readability.
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
from run_wo006r5_bl_core_merge_writer import (  # noqa: E402
    INTERFACE_CSV_FIELDS,
    build_interface_conformality_rows,
    probe_full_non_wall_boundary_surface,
    _run_preserved_interface_core_probe,
)


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r6_core_interface_repair"
OFFICIAL_FORMAT_SOURCES = {
    "su2_mesh_file": "https://su2code.github.io/docs_v7/Mesh-File/",
    "su2_markers_and_bc": "https://su2code.github.io/docs_v7/Markers-and-BC/",
    "su2_multizone": "https://su2code.github.io/docs_v7/Multizone/",
    "gmsh_texinfo": "https://gmsh.info/doc/texinfo/",
}
REQUIRED_VERDICTS = {
    "wo006r6_bl_core_handoff_ready",
    "wo006r6_core_quality_limitation_proven",
    "wo006r6_interface_topology_limitation_proven",
    "wo006r6_campaign_incomplete",
}
FINAL_ARTIFACT_ROLE = "final_merged_bl_core_su2"


def deep_merge_dict(
    original: Mapping[str, Any],
    patch: Mapping[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(original)
    for key, value in patch.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge_dict(existing, value)
        else:
            merged[key] = value
    return merged


def evaluate_r6_final_handoff_gate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Gate a final merged BL+core SU2 handoff.

    Probe SU2 files can be parser-readable evidence, but they are not final
    handoff artifacts. Promotion requires a non-probe final SU2 mesh, zero
    unmatched BL/core faces, marker ownership pass, no non-positive elements,
    and a successful SU2 parser read.
    """
    artifact_role = str(candidate.get("artifact_role") or "")
    su2_path_value = candidate.get("su2_path")
    su2_path = Path(su2_path_value) if isinstance(su2_path_value, str) and su2_path_value else None
    coupling = candidate.get("bl_block_coupling") or {}
    marker_audit = candidate.get("marker_ownership_audit") or {}
    mesh_gate = candidate.get("mesh_quality_gate") or {}
    quality_metrics = mesh_gate.get("quality_metrics") or candidate.get("quality_metrics") or {}

    blockers: list[str] = []
    if candidate.get("core_status") is not None and candidate.get("core_status") != "meshed":
        blockers.append("core_probe_not_meshed")
    if artifact_role != FINAL_ARTIFACT_ROLE:
        blockers.extend(["probe_su2_not_final", "final_merged_su2_missing"])
    if su2_path is None or not su2_path.exists():
        blockers.append("final_merged_su2_missing")
    elif "probe" in su2_path.name.lower() and artifact_role != FINAL_ARTIFACT_ROLE:
        blockers.append("probe_su2_not_final")

    unmatched_core = _optional_int(coupling.get("unmatched_core_interface_face_count"))
    unmatched_bl = _optional_int(coupling.get("unmatched_bl_boundary_face_count"))
    if unmatched_core is None:
        blockers.append("unmatched_core_interface_faces_unknown")
    elif unmatched_core != 0:
        blockers.append("unmatched_core_interface_faces")
    if unmatched_bl is None:
        blockers.append("unmatched_bl_boundary_faces_unknown")
    elif unmatched_bl != 0:
        blockers.append("unmatched_bl_boundary_faces")
    if coupling.get("can_merge_core_with_bl_block") is not True:
        blockers.append("bl_core_coupling_not_pass")

    if marker_audit.get("status") != "pass":
        blockers.append("marker_ownership_not_pass")
    elif not _has_final_boundary_markers(marker_audit.get("final_mesh_boundary_markers")):
        blockers.append("final_boundary_markers_incomplete")

    non_positive_counts = {
        key: _optional_int(quality_metrics.get(key)) or 0
        for key in (
            "non_positive_min_sicn_count",
            "non_positive_min_sige_count",
            "non_positive_volume_count",
        )
    }
    if mesh_gate.get("status") != "pass":
        blockers.append("mesh_quality_not_pass")
    if any(count > 0 for count in non_positive_counts.values()):
        blockers.append("non_positive_elements_present")

    su2_read = _parse_optional_su2(str(su2_path) if su2_path is not None else None)
    if su2_read.get("status") != "parsed":
        blockers.append("final_su2_readability_not_pass")

    blockers = _dedupe(blockers)
    return {
        "schema_version": "wo006r6_final_handoff_gate.v1",
        "status": "pass" if not blockers else "blocked",
        "can_write_bl_mesh_handoff": not blockers,
        "blockers": blockers,
        "artifact_role": artifact_role,
        "candidate_su2_path": None if su2_path is None else str(su2_path),
        "evidence": {
            "core_status": candidate.get("core_status"),
            "unmatched_core_interface_face_count": unmatched_core,
            "unmatched_bl_boundary_face_count": unmatched_bl,
            "marker_ownership_status": marker_audit.get("status"),
            "mesh_quality_status": mesh_gate.get("status"),
            "non_positive_counts": non_positive_counts,
            "su2_readability_status": su2_read.get("status"),
        },
    }


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

    non_wall_probe = normalize_r6_non_wall_probe(
        probe_full_non_wall_boundary_surface(block)
    )
    _write_json(output_dir / "full_non_wall_boundary_surface_probe.json", non_wall_probe)

    merge_gate = evaluate_boundary_layer_core_merge_gate(
        core_report,
        merged_mesh_path=None,
    )
    _write_json(output_dir / "core_interface_repair_gate.json", merge_gate)

    block_summary = build_owned_bl_block_summary(block, core_interface)
    topology_audit = build_core_interface_topology_audit(
        block_summary=block_summary,
        core_report=core_report,
        non_wall_probe=non_wall_probe,
    )
    _write_json(output_dir / "core_interface_topology_audit.json", topology_audit)

    deviation_report = normalize_r6_surface_geometry_deviation(
        build_surface_geometry_deviation(
            build_current_go_wing_surface(geometry),
            block,
        )
    )
    (output_dir / "geometry_deviation_report.md").write_text(
        render_geometry_deviation_report(deviation_report),
        encoding="utf-8",
    )

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

    marker_audit = build_marker_ownership_audit(
        bl_probe_report=bl_probe_report,
        core_report=core_report,
        merge_gate=merge_gate,
    )
    _write_json(output_dir / "marker_ownership_audit.json", marker_audit)

    su2_readability = build_su2_readability_smoke(
        bl_probe_report=bl_probe_report,
        core_report=core_report,
        merge_gate=merge_gate,
    )
    _write_json(output_dir / "su2_readability_smoke.json", su2_readability)
    final_handoff_gate = evaluate_r6_final_handoff_gate(
        build_final_gate_candidate(
            core_report=core_report,
            marker_audit=marker_audit,
            mesh_quality_gate=mesh_quality_gate,
            bl_probe_report=bl_probe_report,
        )
    )
    _write_json(output_dir / "final_handoff_gate.json", final_handoff_gate)
    _write_json(
        output_dir / "probe_su2_policy.json",
        build_probe_su2_policy(core_report=core_report, final_handoff_gate=final_handoff_gate),
    )

    blockers = build_blocker_rows(
        merge_gate=merge_gate,
        mesh_quality_gate=mesh_quality_gate,
        marker_audit=marker_audit,
        su2_readability=su2_readability,
        topology_audit=topology_audit,
        non_wall_probe=non_wall_probe,
        final_handoff_gate=final_handoff_gate,
    )
    write_csv(output_dir / "blocker_register.csv", blockers)

    decision = build_route_decision(
        geometry=geometry,
        block_summary=block_summary,
        deviation_report=deviation_report,
        merge_gate=merge_gate,
        topology_audit=topology_audit,
        marker_audit=marker_audit,
        mesh_quality_gate=mesh_quality_gate,
        su2_readability=su2_readability,
        non_wall_probe=non_wall_probe,
        blockers=blockers,
    )
    decision["final_handoff_gate"] = final_handoff_gate
    _write_json(output_dir / "route_decision.json", decision)

    if decision["bl_mesh_handoff_written"]:
        raise AssertionError("R6 must not claim a BL handoff without a real merged mesh")

    (output_dir / "core_interface_repair_report.md").write_text(
        render_core_interface_repair_report(
            decision=decision,
            topology_audit=topology_audit,
            mesh_quality_gate=mesh_quality_gate,
            marker_audit=marker_audit,
            su2_readability=su2_readability,
            blockers=blockers,
        ),
        encoding="utf-8",
    )
    (output_dir / "next_goal.md").write_text(render_next_goal(decision), encoding="utf-8")
    return decision


def _skipped_core_probe_report(*, output_dir: Path) -> dict[str, Any]:
    return {
        "status": "not_run",
        "route": "wo006r6_preserved_interface_core_probe",
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


def build_core_interface_topology_audit(
    *,
    block_summary: Mapping[str, Any],
    core_report: Mapping[str, Any],
    non_wall_probe: Mapping[str, Any],
) -> dict[str, Any]:
    coupling = core_report.get("bl_block_coupling") or {}
    unmatched_core = int(coupling.get("unmatched_core_interface_face_count") or 0)
    unmatched_bl = int(coupling.get("unmatched_bl_boundary_face_count") or 0)
    zero_unmatched = (
        coupling.get("can_merge_core_with_bl_block") is True
        and unmatched_core == 0
        and unmatched_bl == 0
    )
    core_counts = block_summary.get("core_interface_marker_counts") or {}
    boundary_counts = block_summary.get("boundary_marker_counts") or {}
    return {
        "schema_version": "wo006r6_core_interface_topology_audit.v1",
        "status": "pass" if zero_unmatched else "fail",
        "zero_unmatched_interface_faces": zero_unmatched,
        "core_interface_marker_counts": core_counts,
        "owned_bl_boundary_marker_counts": boundary_counts,
        "unmatched_core_interface_face_count": unmatched_core,
        "unmatched_core_interface_face_counts_by_marker": coupling.get(
            "unmatched_core_interface_face_counts_by_marker"
        )
        or {},
        "unmatched_bl_boundary_face_count": unmatched_bl,
        "unmatched_bl_boundary_face_counts_by_marker": coupling.get(
            "unmatched_bl_boundary_face_counts_by_marker"
        )
        or {},
        "full_non_wall_boundary_probe_status": non_wall_probe.get("status"),
        "full_non_wall_boundary_can_use_as_core_inner_boundary": non_wall_probe.get(
            "can_use_as_core_inner_boundary"
        )
        is True,
        "engineering_read": (
            "The BL/core handoff is acceptable only if the core inner boundary is "
            "the same face set as the BL block interface. Preserving a smaller "
            "closure envelope is useful evidence, but wake/span-cap unmatched "
            "faces mean the final fluid-volume topology is still not closed."
        ),
    }


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
        "schema_version": "wo006r6_mesh_quality_gate.v1",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "owned_bl_block_quality": block_quality,
        "core_mesh_quality_gate": core_gate,
        "core_quality_metrics": core_metrics,
        "merged_mesh_quality_gate": None,
        "engineering_read": (
            "Positive BL cells are necessary but insufficient. R6 requires the "
            "core and eventual merged mesh to have zero non-positive volume, SICN, "
            "and SIGE elements before any handoff manifest exists."
        ),
    }


def build_marker_ownership_audit(
    *,
    bl_probe_report: Mapping[str, Any],
    core_report: Mapping[str, Any],
    merge_gate: Mapping[str, Any],
) -> dict[str, Any]:
    core_groups = core_report.get("physical_groups") or {}
    marker_summary = bl_probe_report.get("marker_summary") or {}
    blockers: list[str] = []
    if "wing_wall" not in marker_summary:
        blockers.append("wing_wall_marker_missing_from_owned_bl_block")
    if "farfield" not in core_groups:
        blockers.append("farfield_marker_missing_from_core_probe")
    if merge_gate.get("can_write_bl_mesh_handoff") is not True:
        blockers.append("final_merged_marker_ownership_not_proven")
    return {
        "schema_version": "wo006r6_marker_ownership_audit.v1",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "owned_bl_block_markers": marker_summary,
        "core_probe_physical_groups": core_groups,
        "final_mesh_boundary_markers": None,
        "policy": (
            "Final SU2 boundary markers should expose real computational "
            "boundaries such as wing_wall and farfield. A conformal BL/core "
            "interface must be internal connectivity, not a solver boundary marker."
        ),
    }


def build_su2_readability_smoke(
    *,
    bl_probe_report: Mapping[str, Any],
    core_report: Mapping[str, Any],
    merge_gate: Mapping[str, Any],
) -> dict[str, Any]:
    blockers = []
    if merge_gate.get("can_write_bl_mesh_handoff") is not True:
        blockers.append("merged_bl_core_su2_mesh_missing")
    return {
        "schema_version": "wo006r6_su2_readability_smoke.v1",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "final_mesh_path": None,
        "final_solver_run": False,
        "probe_parser_reads": {
            "owned_bl_block_probe": _parse_optional_su2(bl_probe_report.get("mesh_path")),
            "preserved_core_probe": _parse_optional_su2(core_report.get("su2_path")),
        },
        "coefficient_interpretable": False,
        "reason": (
            "No final merged mixed-element BL+core SU2 mesh exists, so probe "
            "readability is not promoted to CFD evidence."
        ),
    }


def build_final_gate_candidate(
    *,
    core_report: Mapping[str, Any],
    marker_audit: Mapping[str, Any],
    mesh_quality_gate: Mapping[str, Any],
    bl_probe_report: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "wo006r6_final_gate_candidate.v1",
        "artifact_role": "probe_su2",
        "core_status": core_report.get("status"),
        "su2_path": core_report.get("su2_path") or bl_probe_report.get("mesh_path"),
        "bl_block_coupling": core_report.get("bl_block_coupling") or {},
        "marker_ownership_audit": marker_audit,
        "mesh_quality_gate": {
            "status": mesh_quality_gate.get("status"),
            "blockers": mesh_quality_gate.get("blockers"),
            "quality_metrics": core_report.get("quality_metrics") or {},
        },
    }


def build_probe_su2_policy(
    *,
    core_report: Mapping[str, Any],
    final_handoff_gate: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "wo006r6_probe_su2_policy.v1",
        "candidate_su2_path": core_report.get("su2_path"),
        "probe_su2_is_final": False,
        "final_handoff_allowed": final_handoff_gate.get("can_write_bl_mesh_handoff") is True,
        "policy": (
            "A core or BL probe SU2 can be parser-readable evidence, but it is not "
            "a final merged BL+core handoff and must not be used for coefficients."
        ),
    }


def build_route_decision(
    *,
    geometry,
    block_summary: Mapping[str, Any],
    deviation_report: Mapping[str, Any],
    merge_gate: Mapping[str, Any],
    topology_audit: Mapping[str, Any],
    marker_audit: Mapping[str, Any],
    mesh_quality_gate: Mapping[str, Any],
    su2_readability: Mapping[str, Any],
    non_wall_probe: Mapping[str, Any],
    blockers: list[Mapping[str, str]],
) -> dict[str, Any]:
    handoff_ready = (
        merge_gate.get("can_write_bl_mesh_handoff") is True
        and topology_audit.get("status") == "pass"
        and marker_audit.get("status") == "pass"
        and mesh_quality_gate.get("status") == "pass"
        and su2_readability.get("status") == "pass"
    )
    verdict = classify_verdict(
        handoff_ready=handoff_ready,
        core_report_status=mesh_quality_gate.get("core_mesh_quality_gate", {}).get("status"),
        topology_status=topology_audit.get("status"),
    )
    return {
        "schema_version": "wo006r6_route_decision.v1",
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
        "interface_topology_audit": topology_audit,
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
        "non_wall_boundary_probe": non_wall_probe,
        "blockers": _unique_values(row["blocker"] for row in blockers),
        "smallest_remaining_limitation": _smallest_limitation(verdict),
        "blocked_claims": [
            "current BL/y+ CFD handoff",
            "CL/CD/CDi/profile-drag interpretation",
            "drag or power truth",
            "Baseline A reopen evidence",
            "RFQ/procurement truth",
            "final aircraft sign-off",
        ],
    }


def classify_verdict(
    *,
    handoff_ready: bool,
    core_report_status: str | None,
    topology_status: str | None,
) -> str:
    if handoff_ready:
        return "wo006r6_bl_core_handoff_ready"
    if core_report_status != "pass":
        return "wo006r6_core_quality_limitation_proven"
    if topology_status != "pass":
        return "wo006r6_interface_topology_limitation_proven"
    return "wo006r6_campaign_incomplete"


def _smallest_limitation(verdict: str) -> str:
    if verdict == "wo006r6_core_quality_limitation_proven":
        return (
            "The preserved core interface route still produces non-positive core "
            "quality metrics before a merged BL+core handoff can be trusted."
        )
    if verdict == "wo006r6_interface_topology_limitation_proven":
        return (
            "Core quality can be separated from the harder blocker: wake/span-cap "
            "BL boundary faces still do not form a zero-unmatched conformal interface."
        )
    if verdict == "wo006r6_bl_core_handoff_ready":
        return "A real merged mixed-element BL+core SU2 handoff exists."
    return "The campaign did not reach a decisive quality or topology verdict."


def build_blocker_rows(
    *,
    merge_gate: Mapping[str, Any],
    mesh_quality_gate: Mapping[str, Any],
    marker_audit: Mapping[str, Any],
    su2_readability: Mapping[str, Any],
    topology_audit: Mapping[str, Any],
    non_wall_probe: Mapping[str, Any],
    final_handoff_gate: Mapping[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for blocker in merge_gate.get("blockers") or []:
        rows.append(_blocker_row("core_interface_repair_gate", blocker, merge_gate))
    for blocker in mesh_quality_gate.get("blockers") or []:
        rows.append(_blocker_row("mesh_quality_gate", blocker, mesh_quality_gate))
    for blocker in marker_audit.get("blockers") or []:
        rows.append(_blocker_row("marker_ownership_audit", blocker, marker_audit))
    for blocker in su2_readability.get("blockers") or []:
        rows.append(_blocker_row("su2_readability_smoke", blocker, su2_readability))
    for blocker in final_handoff_gate.get("blockers") or []:
        rows.append(_blocker_row("final_handoff_gate", blocker, final_handoff_gate))
    if topology_audit.get("zero_unmatched_interface_faces") is not True:
        rows.append(
            _blocker_row(
                "core_interface_topology_audit",
                "zero_unmatched_bl_core_interface_not_proven",
                topology_audit,
            )
        )
    if non_wall_probe.get("can_use_as_core_inner_boundary") is False:
        rows.append(
            _blocker_row(
                "full_non_wall_boundary_surface_probe",
                "full_non_wall_boundary_not_watertight",
                non_wall_probe,
            )
        )
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["stage"], row["blocker"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _blocker_row(stage: str, blocker: object, evidence: Mapping[str, Any]) -> dict[str, str]:
    return {
        "stage": stage,
        "status": "blocked",
        "blocker": str(blocker),
        "evidence": json.dumps(evidence, sort_keys=True),
        "next_fix": _next_fix_for_blocker(str(blocker)),
    }


def _next_fix_for_blocker(blocker: str) -> str:
    if "quality" in blocker or "non_positive" in blocker:
        return "repair preserved-core volume quality without remeshing the BL/core interface"
    if "coupling" in blocker or "interface" in blocker or "watertight" in blocker:
        return "replace the virtual wake/span-cap closure with a true conformal BL/core topology"
    if "marker" in blocker:
        return "prove final merged mesh boundary markers, not only component probe markers"
    if "su2" in blocker or "mesh_missing" in blocker:
        return "write one real merged mixed-element SU2 mesh only after gates pass"
    return "continue WO-006R6 repair before promoting any handoff"


def normalize_r6_surface_geometry_deviation(deviation_report: Mapping[str, Any]) -> dict[str, Any]:
    report = dict(deviation_report)
    report["schema_version"] = "wo006r6_surface_geometry_deviation.v1"
    report["r6_new_adapter_cleanup_applied"] = report.pop(
        "r4_new_adapter_cleanup_applied",
        False,
    )
    report["interpretation"] = (
        "R6 did not change authority geometry. The owned BL wall is generated "
        "from the same current-GO mesh-native station data; any remaining "
        "deviation is adapter/discretization evidence, not a source-shape change."
    )
    return report


def normalize_r6_non_wall_probe(non_wall_probe: Mapping[str, Any]) -> dict[str, Any]:
    report = dict(non_wall_probe)
    report["schema_version"] = "wo006r6_full_non_wall_boundary_surface_probe.v1"
    return report


def _unique_values(values) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def render_geometry_deviation_report(deviation_report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# WO-006R6 Geometry Deviation Report",
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


def render_core_interface_repair_report(
    *,
    decision: Mapping[str, Any],
    topology_audit: Mapping[str, Any],
    mesh_quality_gate: Mapping[str, Any],
    marker_audit: Mapping[str, Any],
    su2_readability: Mapping[str, Any],
    blockers: list[Mapping[str, str]],
) -> str:
    return "\n".join(
        [
            "# WO-006R6 Core Interface Repair Report",
            "",
            f"- Verdict: `{decision.get('verdict')}`",
            f"- BL+core handoff exists: `{decision.get('bl_core_handoff_exists')}`",
            f"- bl_mesh_handoff.v1.json emitted: `{decision.get('bl_mesh_handoff_written')}`",
            f"- Coefficients interpretable: `{decision.get('coefficient_interpretable')}`",
            f"- Zero unmatched interface faces: `{topology_audit.get('zero_unmatched_interface_faces')}`",
            f"- Mesh quality gate: `{mesh_quality_gate.get('status')}`",
            f"- Marker ownership audit: `{marker_audit.get('status')}`",
            f"- SU2 readability smoke: `{su2_readability.get('status')}`",
            "",
            "## Data Authority",
            "",
            "| Topic | Current authority | Blocked stale value |",
            "| --- | --- | --- |",
            "| Design gross mass | 98.5 kg | 106.828608 kg suspect screening aggregate |",
            "| Full span | 34.332286 m | not replaced by local 16.5 m half-span |",
            "| Half span | 17.166143 m | 16.5 m local/splice screening only |",
            "| Coefficients | non-interpretable | no-BL/probe/old smoke coefficients |",
            "",
            "## Format Sources",
            "",
            f"- SU2 mesh file: {OFFICIAL_FORMAT_SOURCES['su2_mesh_file']}",
            f"- SU2 markers and boundary conditions: {OFFICIAL_FORMAT_SOURCES['su2_markers_and_bc']}",
            f"- SU2 multizone: {OFFICIAL_FORMAT_SOURCES['su2_multizone']}",
            f"- Gmsh manual: {OFFICIAL_FORMAT_SOURCES['gmsh_texinfo']}",
            "",
            "## Blockers",
            "",
            *[f"- `{row['stage']}`: `{row['blocker']}`" for row in blockers],
            "",
            "## Engineering Read",
            "",
            str(decision.get("smallest_remaining_limitation") or ""),
            "",
            "This is mesh/interface evidence only. Passing parser checks or writing "
            "component probes does not establish wall shear, y+, convergence, grid-pair "
            "independence, drag truth, Baseline A reopen evidence, procurement truth, "
            "or final aircraft sign-off.",
            "",
        ]
    )


def render_next_goal(decision: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "/goal In /Volumes/Samsung SSD/hpa-mdo, continue after WO-006R6 with the data-authority checker prerequisite preserved by choosing the next BL/core topology route based on the R6 verdict.",
            "",
            f"Previous verdict: `{decision.get('verdict')}`.",
            "",
            "If the verdict is `wo006r6_core_quality_limitation_proven`, first repair "
            "preserved-core volume quality without remeshing the BL/core boundary. If "
            "the verdict is `wo006r6_interface_topology_limitation_proven`, stop "
            "treating wake/span-cap closure as a writer bug and redesign the local "
            "BL/core topology contract before attempting another final SU2 handoff.",
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


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_final_boundary_markers(markers: Any) -> bool:
    if not isinstance(markers, Mapping):
        return False
    return all(
        marker in markers and int((markers.get(marker) or {}).get("element_count") or 0) > 0
        for marker in ("wing_wall", "farfield")
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
    if decision["verdict"] not in REQUIRED_VERDICTS:
        raise RuntimeError(f"Unexpected WO-006R6 verdict: {decision['verdict']}")
    print(json.dumps(decision, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
