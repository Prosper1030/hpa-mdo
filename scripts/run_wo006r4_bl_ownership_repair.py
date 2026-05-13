#!/usr/bin/env python3
"""Run WO-006R4 BL ownership repair / limitation campaign.

The campaign starts from the WO-006R3 high-mesh no-BL handoff and asks whether
the current GO mesh-native adapter can produce a credible BL/y+ capable SU2
handoff without changing Baseline A authority geometry. It is intentionally a
route-decision and evidence generator: if a route is only a topology smoke, it
records that boundary instead of writing a misleading BL handoff.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
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

from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    write_boundary_layer_block_core_tet_mesh,
)
from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    WingBoundaryLayerBlock,
    build_boundary_layer_core_interface_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    SurfaceMesh,
    build_farfield_box_surface,
    validate_surface_mesh,
)
from run_wo006r1_go_baseline_a_cfd_bridge import (  # noqa: E402
    DESIGN_GROSS_MASS_KG,
    PIPELINE_FULL_SPAN_M,
    PIPELINE_HALF_SPAN_M,
    CurrentGoGeometry,
    build_current_go_wing_surface,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    MU_PA_S,
    RHO_KGPM3,
    VELOCITY_MPS,
    build_yplus_nearwall_summary,
    load_campaign_geometry,
)


WO006_ROOT = REPO_ROOT / "output" / "baseline_A_team_release" / "wo006_su2_baseline_validation"
WO006R3_DIR = WO006_ROOT / "wo006r3_surface_topology_repair"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r4_bl_ownership_repair"


def run_campaign(
    *,
    output_dir: Path,
    clean: bool = True,
    run_core_probes: bool = True,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    geometry = load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
    wing = build_current_go_wing_surface(geometry)
    yplus_summary = build_yplus_nearwall_summary(geometry)
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

    old_evidence = build_old_evidence_rows()
    r3_evidence = load_r3_evidence()
    block_summary = build_owned_bl_block_summary(block, core_interface)
    deviation_report = build_surface_geometry_deviation(wing, block)

    attempts = [
        *build_r3_replay_attempts(r3_evidence),
        {
            "attempt_id": "owned_bl_block_current_go_32x2",
            "route": "mesh_native_owned_bl_block_without_core_merge",
            "status": "partial",
            "accepted_for": "wall BL topology construction and first-layer basis",
            "rejected_for": "final SU2 BL handoff",
            "failure_mode": "owned BL block has no conformal core merge or SU2 writer yet",
            "evidence": block_summary,
        },
    ]
    core_probe_reports: list[dict[str, Any]] = []
    if run_core_probes:
        core_probe_reports = run_owned_bl_core_probes(output_dir=output_dir)
    else:
        core_probe_reports = [
            {
                "attempt_id": "owned_bl_core_probe_skipped",
                "status": "not_run",
                "reason": "run_core_probes_false",
            }
        ]
    attempts.extend(core_probe_reports)

    route_decision = build_route_decision(
        geometry=geometry,
        attempts=attempts,
        block_summary=block_summary,
        deviation_report=deviation_report,
    )
    blockers = build_blocker_rows(attempts, route_decision)
    solver_gate = build_solver_evidence_gate(route_decision, r3_evidence)

    write_json(output_dir / "route_decision.json", route_decision)
    write_json(output_dir / "solver_evidence_gate.json", solver_gate)
    write_json(output_dir / "owned_bl_block_summary.json", block_summary)
    write_markdown(output_dir / "old_evidence_map.md", render_old_evidence_map(old_evidence))
    write_markdown(
        output_dir / "surface_geometry_deviation_report.md",
        render_surface_geometry_deviation_report(deviation_report),
    )
    write_markdown(
        output_dir / "yplus_and_boundary_layer_basis.md",
        render_yplus_and_boundary_layer_basis(yplus_summary),
    )
    write_csv(output_dir / "blocker_register.csv", blockers)
    write_markdown(
        output_dir / "cfd_recovery_campaign_report.md",
        render_campaign_report(
            geometry=geometry,
            route_decision=route_decision,
            attempts=attempts,
            blockers=blockers,
            yplus_summary=yplus_summary,
            deviation_report=deviation_report,
        ),
    )
    write_markdown(output_dir / "next_goal.md", render_next_goal(route_decision, blockers))
    return route_decision


def load_r3_evidence(r3_dir: Path = WO006R3_DIR) -> dict[str, Any]:
    final_verdict_path = r3_dir / "final_engineering_verdict.json"
    handoff_path = r3_dir / "mesh_handoff.v1.json"
    repair_summary_path = r3_dir / "repair_attempts_summary.csv"
    plc_path = r3_dir / "plc_intersection_localization.csv"
    final_policy_blockers = r3_dir / "final_policy_campaign" / "blocker_register.csv"
    return {
        "r3_dir": str(r3_dir),
        "final_engineering_verdict": read_json(final_verdict_path),
        "mesh_handoff": read_json(handoff_path),
        "repair_attempts_summary": read_csv_rows(repair_summary_path),
        "plc_intersection_localization": read_csv_rows(plc_path),
        "final_policy_blockers": read_csv_rows(final_policy_blockers),
    }


def build_old_evidence_rows() -> list[dict[str, str]]:
    return [
        {
            "evidence_id": "wo006r2_current_go_adapter_blocker",
            "artifact": str(WO006_ROOT / "wo006r2_cfd_recovery_campaign"),
            "read": "current GO BL and high-mesh attempts blocked in Gmsh HXT PLC recovery",
            "use": "blocker localization",
            "not_use": "coefficient truth",
        },
        {
            "evidence_id": "old_hxt_bl_wing_h_0p20",
            "artifact": (
                "hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/"
                "mesh_native_hxt_thread_profile.v1.md"
            ),
            "read": "1,125,409 cells; 992,352 BL prisms; marker-owned short smoke",
            "use": "serious BL target/template",
            "not_use": "current Baseline A coefficient truth",
        },
        {
            "evidence_id": "old_hxt_bl_wing_h_0p15",
            "artifact": (
                "hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/"
                "mesh_native_hxt_thread_profile.v1.md"
            ),
            "read": "1,515,251 cells; two non-positive BL quality items",
            "use": "finer-mesh BL quality warning boundary",
            "not_use": "solver-ready mesh",
        },
        {
            "evidence_id": "wo006r3_high_mesh_no_bl_handoff",
            "artifact": str(WO006R3_DIR / "mesh_handoff.v1.json"),
            "read": "936,017 no-BL tets; marker audit pass; SU2 reached iteration 75",
            "use": "current GO no-BL readability handoff baseline",
            "not_use": "BL/y+ handoff or drag/power truth",
        },
    ]


def build_owned_bl_block_summary(
    block: WingBoundaryLayerBlock,
    core_interface: SurfaceMesh,
) -> dict[str, Any]:
    return {
        "schema_version": "wo006r4_owned_bl_block_summary.v1",
        "route": "mesh_native_owned_boundary_layer_block",
        "wall_marker": "wing_wall",
        "outer_interface_markers": ["bl_outer_interface", "wake_cut", "span_cap"],
        "block_cells": len(block.cells),
        "block_vertices": len(block.vertices),
        "marker_counts": block.marker_counts(),
        "boundary_marker_counts": block.boundary_marker_counts(),
        "core_interface_marker_counts": core_interface.marker_counts(),
        "quality": block.quality,
        "boundary_layer": {
            "first_height_m": BL_FIRST_HEIGHT_M,
            "growth_ratio": BL_GROWTH_RATIO,
            "layers": BL_LAYERS,
            "total_thickness_m": geometric_total_thickness(
                BL_FIRST_HEIGHT_M,
                BL_GROWTH_RATIO,
                BL_LAYERS,
            ),
        },
        "engineering_read": (
            "The current GO adapter can construct an owned wall BL block with positive "
            "estimated cells, but this is not a complete SU2 handoff until the core "
            "mesh boundary, wake cut, span caps, volume quality, and SU2 element writer "
            "are closed together."
        ),
    }


def run_owned_bl_core_probes(*, output_dir: Path) -> list[dict[str, Any]]:
    geometry = load_campaign_geometry(points_per_side=16, spanwise_subdivisions=2)
    block = build_wing_boundary_layer_block(
        geometry.spec.wing_spec,
        BoundaryLayerBlockSpec(
            first_layer_height_m=BL_FIRST_HEIGHT_M,
            growth_ratio=BL_GROWTH_RATIO,
            layer_count=BL_LAYERS,
        ),
    )
    inner_boundary = build_boundary_layer_core_interface_surface(block)
    farfield = build_farfield_box_surface(
        inner_boundary,
        upstream_factor=2.0,
        downstream_factor=4.0,
        lateral_factor=2.0,
        vertical_factor=2.0,
    )
    probe_specs = [
        {
            "attempt_id": "owned_bl_core_preserve_interface_alg1",
            "preserve_boundary_mesh": True,
            "mesh_algorithm3d": 1,
            "engineering_role": "test whether core can preserve BL outer interface",
        },
        {
            "attempt_id": "owned_bl_core_remesh_hxt",
            "preserve_boundary_mesh": False,
            "mesh_algorithm3d": 10,
            "engineering_role": "test whether remeshed core hides interface issues",
        },
        {
            "attempt_id": "owned_bl_core_remesh_alg1",
            "preserve_boundary_mesh": False,
            "mesh_algorithm3d": 1,
            "engineering_role": "test whether non-HXT remeshed core avoids quality failure",
        },
    ]
    results = []
    for spec in probe_specs:
        case_dir = output_dir / "core_probe_artifacts" / spec["attempt_id"]
        start = time.time()
        try:
            report = write_boundary_layer_block_core_tet_mesh(
                block,
                farfield,
                case_dir / "core.msh",
                su2_path=case_dir / "core.su2",
                mesh_size=1.0,
                farfield_mesh_size=8.0,
                preserve_boundary_mesh=bool(spec["preserve_boundary_mesh"]),
                gmsh_threads=4,
                mesh_algorithm3d=int(spec["mesh_algorithm3d"]),
            )
            result = classify_core_probe_result(
                attempt_id=str(spec["attempt_id"]),
                role=str(spec["engineering_role"]),
                report=report,
                elapsed_seconds=time.time() - start,
            )
            write_json(case_dir / "core_probe_report.json", report)
            write_json(case_dir / "core_probe_summary.json", result)
            results.append(result)
        except Exception as exc:  # pragma: no cover - real Gmsh failure is evidence.
            result = {
                "attempt_id": str(spec["attempt_id"]),
                "route": "mesh_native_owned_bl_block_core_tet_probe",
                "status": "blocked",
                "accepted_for": "failure localization",
                "rejected_for": "BL handoff",
                "failure_mode": exc.__class__.__name__,
                "error": str(exc),
                "elapsed_seconds": time.time() - start,
                "runtime_policy": spec,
            }
            write_json(case_dir / "core_probe_summary.json", result)
            results.append(result)
    return results


def classify_core_probe_result(
    *,
    attempt_id: str,
    role: str,
    report: Mapping[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    mesh_gate = report.get("mesh_quality_gate") or {}
    conformality = report.get("interface_conformality") or {}
    coupling = report.get("bl_block_coupling") or {}
    can_merge = (
        mesh_gate.get("status") == "pass"
        and conformality.get("can_merge_with_owned_bl_block") is True
        and coupling.get("can_merge_core_with_bl_block") is True
    )
    if can_merge:
        status = "candidate_ready"
        failure_mode = None
        rejected_for = ""
    elif conformality.get("can_merge_with_owned_bl_block") is False:
        status = "rejected_workaround"
        failure_mode = "core_interface_remeshed_not_conformal_to_owned_bl_block"
        rejected_for = "final BL handoff because Gmsh changed the BL-core interface mesh"
    elif mesh_gate.get("status") != "pass" and coupling.get("can_merge_core_with_bl_block") is False:
        status = "blocked"
        failure_mode = "core_mesh_quality_failed_and_owned_bl_core_coupling_partial"
        rejected_for = (
            "final BL handoff because preserved core volume quality failed and "
            "wake/span-cap ownership is not yet a conformal merged BL+core topology"
        )
    elif mesh_gate.get("status") != "pass":
        status = "blocked"
        failure_mode = "core_mesh_quality_gate_failed"
        rejected_for = "final BL handoff because preserved core volume quality failed"
    elif coupling.get("can_merge_core_with_bl_block") is False:
        status = "blocked"
        failure_mode = "owned_bl_core_coupling_partial_wake_span_cap_not_conformal"
        rejected_for = (
            "final BL handoff because wake/span-cap ownership is not yet a conformal "
            "merged BL+core topology"
        )
    else:
        status = "blocked"
        failure_mode = "unknown_owned_bl_core_probe_blocker"
        rejected_for = "final BL handoff because probe did not satisfy merge criteria"
    return {
        "attempt_id": attempt_id,
        "route": "mesh_native_owned_bl_block_core_tet_probe",
        "status": status,
        "accepted_for": role,
        "rejected_for": rejected_for,
        "failure_mode": failure_mode,
        "elapsed_seconds": elapsed_seconds,
        "mesh": {
            "volume_element_count": report.get("volume_element_count"),
            "volume_element_type_counts": report.get("volume_element_type_counts"),
            "mesh_quality_gate": mesh_gate,
            "quality_metrics": report.get("quality_metrics"),
        },
        "interface_conformality": conformality,
        "bl_block_coupling": coupling,
        "markers": report.get("physical_groups"),
        "caveats": report.get("caveats"),
    }


def build_r3_replay_attempts(r3_evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    plc_rows = r3_evidence.get("plc_intersection_localization") or []
    attempts = []
    for row in plc_rows:
        stage = str(row.get("evidence_stage") or "")
        if not stage.startswith("wo006r3_final_policy"):
            continue
        attempts.append(
            {
                "attempt_id": stage,
                "route": "gmsh_topological_bl_extrude_boundary_layer",
                "status": "blocked",
                "accepted_for": "exact remaining DAE31-family blocker localization",
                "rejected_for": "BL/y+ handoff",
                "failure_mode": "Gmsh HXT PLC segment/facet intersection",
                "code_path": (
                    "write_faceted_volume_mesh_with_boundary_layer -> "
                    "gmsh.model.geo.extrudeBoundaryLayer -> gmsh.model.mesh.generate(3)"
                ),
                "evidence": dict(row),
            }
        )
    repair_rows = r3_evidence.get("repair_attempts_summary") or []
    for row in repair_rows:
        if str(row.get("attempt")) == "shorter_panel_diagonalization":
            attempts.append(
                {
                    "attempt_id": "r3_shorter_diagonalization_on_bl_exploratory",
                    "route": "blind_shorter_diagonalization_applied_to_bl",
                    "status": "rejected_workaround",
                    "accepted_for": "no-BL high-mesh faceted handoff only",
                    "rejected_for": "BL extrusion",
                    "failure_mode": "Gmsh Unknown curve -1550",
                    "code_path": (
                        "_add_mesh_surfaces/_line_between signed curve ownership "
                        "under BL topology"
                    ),
                    "evidence": dict(row),
                }
            )
    return attempts


def build_surface_geometry_deviation(
    wing: SurfaceMesh,
    block: WingBoundaryLayerBlock,
) -> dict[str, Any]:
    wall_vertices = wall_vertices_from_block(block)
    wing_vertices = list(wing.vertices)
    distances = [nearest_distance(vertex, wing_vertices) for vertex in wall_vertices]
    return {
        "schema_version": "wo006r4_surface_geometry_deviation.v1",
        "external_authority_files_changed": False,
        "r4_new_adapter_cleanup_applied": False,
        "comparison": "owned BL wall layer-0 nodes against current GO mesh-native wing surface",
        "wall_vertex_count": len(wall_vertices),
        "wing_surface_vertex_count": len(wing_vertices),
        "max_nearest_distance_m": max(distances) if distances else None,
        "p95_nearest_distance_m": percentile(distances, 0.95),
        "mean_nearest_distance_m": sum(distances) / len(distances) if distances else None,
        "interpretation": (
            "R4 did not change authority geometry. The owned BL wall is generated "
            "from the same current-GO mesh-native station data; any remaining "
            "deviation here is adapter/discretization evidence, not a source-shape change."
        ),
    }


def build_route_decision(
    *,
    geometry: CurrentGoGeometry,
    attempts: Sequence[Mapping[str, Any]],
    block_summary: Mapping[str, Any],
    deviation_report: Mapping[str, Any],
) -> dict[str, Any]:
    handoff_ready = any(attempt.get("status") == "candidate_ready" for attempt in attempts)
    verdict = (
        "wo006r4_bl_handoff_ready" if handoff_ready else "wo006r4_adapter_limitation_proven"
    )
    return {
        "schema_version": "wo006r4_route_decision.v1",
        "verdict": verdict,
        "bl_mesh_handoff_written": False,
        "bl_mesh_handoff_path": None,
        "coefficient_interpretable": False,
        "baseline_a_reopen_status": "not_evaluated",
        "authority_basis": authority_basis(geometry),
        "external_shape_changed": False,
        "surface_deviation": deviation_report,
        "attempt_count": len(attempts),
        "attempt_status_counts": status_counts(attempts),
        "selected_route": (
            "none"
            if not handoff_ready
            else "mesh_native_owned_bl_block_with_conformal_core_merge"
        ),
        "rejected_routes": [
            "Gmsh topological BL extrusion: still fails DAE31-family PLC points.",
            "Blind shorter diagonalization on BL: produced Unknown curve -1550.",
            "Owned BL block alone: positive wall cells but no conformal core/SU2 merge.",
            "Remeshed core workaround: hides interface ownership by changing the BL-core boundary.",
        ],
        "limitation_proof": {
            "smallest_blocker": (
                "current adapter lacks a conformal owned BL block + core merge/writer; "
                "Gmsh-owned BL extrusion still fails on DAE31-family PLC topology, "
                "while the mesh-native owned-BL core probes either fail preserved "
                "core quality or remesh the interface."
            ),
            "code_paths": [
                "hpa_meshing.mesh_native.gmsh_polyhedral.write_faceted_volume_mesh_with_boundary_layer",
                "hpa_meshing.mesh_native.near_wall_block.build_wing_boundary_layer_block",
                "hpa_meshing.mesh_native.gmsh_polyhedral.write_boundary_layer_block_core_tet_mesh",
            ],
            "next_repair_target": (
                "write a conformal BL+core ownership merge that preserves bl_outer_interface, "
                "wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 "
                "with wing_wall/farfield ownership and quality gates."
            ),
        },
        "owned_bl_block_summary": {
            "block_cells": block_summary["block_cells"],
            "quality": block_summary["quality"],
            "boundary_layer": block_summary["boundary_layer"],
        },
    }


def build_solver_evidence_gate(
    route_decision: Mapping[str, Any],
    r3_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    r3_handoff = r3_evidence.get("mesh_handoff") or {}
    r3_solver = r3_handoff.get("solver_readability_smoke") or {}
    return {
        "schema_version": "wo006r4_solver_evidence_gate.v1",
        "status": "fail",
        "coefficient_interpretable": False,
        "solver_run_this_campaign": False,
        "reasons": [
            "no BL mesh handoff was written",
            "owned BL block is not yet merged with a conformal core SU2 mesh",
            "R3 high-mesh no-BL solver smoke remains readability evidence only",
            "no postprocessed y+ field exists",
            "no convergence/grid-pair evidence exists",
        ],
        "r3_no_bl_readability_context": {
            "run_status": r3_solver.get("run_status"),
            "final_iteration": (r3_solver.get("history") or {}).get("final_iteration"),
            "cfd_evidence_gate": r3_solver.get("cfd_evidence_gate"),
            "coefficient_sanity_gate": r3_solver.get("coefficient_sanity_gate"),
        },
        "allowed_use": "route recovery evidence only",
        "blocked_use": [
            "CL/CD/CDi/profile-drag calibration",
            "drag or power truth",
            "Baseline A reopen evidence",
            "RFQ/procurement truth",
            "final aircraft sign-off",
        ],
        "campaign_verdict": route_decision.get("verdict"),
    }


def build_blocker_rows(
    attempts: Sequence[Mapping[str, Any]],
    route_decision: Mapping[str, Any],
) -> list[dict[str, str]]:
    rows = []
    for attempt in attempts:
        status = str(attempt.get("status"))
        if status in {"candidate_ready"}:
            continue
        rows.append(
            {
                "stage": str(attempt.get("attempt_id")),
                "status": status,
                "route": str(attempt.get("route")),
                "blocker": str(attempt.get("failure_mode") or "not_handoff_ready"),
                "code_path": str(attempt.get("code_path") or "see_attempt_summary"),
                "evidence": compact_json(attempt.get("evidence") or attempt),
                "next_fix": str(
                    route_decision.get("limitation_proof", {}).get("next_repair_target")
                    or "inspect route_decision.json"
                ),
            }
        )
    return rows


def authority_basis(geometry: CurrentGoGeometry) -> dict[str, Any]:
    return {
        "design_gross_mass_kg": DESIGN_GROSS_MASS_KG,
        "pipeline_full_span_m": PIPELINE_FULL_SPAN_M,
        "pipeline_half_span_m": PIPELINE_HALF_SPAN_M,
        "sref_m2": geometry.reference.sref_full,
        "cref_m": geometry.reference.cref,
        "bref_m": geometry.reference.bref_full,
        "moment_origin_m": list(geometry.moment_origin_m),
        "geometry_source": str(geometry.section_table_path),
        "blocked_legacy_mass_kg": "106.828608 kg is not current truth",
        "blocked_legacy_half_span_m": "16.5 m is not current pipeline truth",
    }


def render_old_evidence_map(rows: Sequence[Mapping[str, str]]) -> str:
    lines = [
        "# WO-006R4 Old Evidence Map",
        "",
        "This campaign starts from prior evidence instead of rerunning every old path.",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row['evidence_id']}",
                "",
                f"- Artifact: `{row['artifact']}`",
                f"- Read: {row['read']}",
                f"- Use in R4: {row['use']}",
                f"- Not used for: {row['not_use']}",
                "",
            ]
        )
    return "\n".join(lines)


def render_surface_geometry_deviation_report(report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# WO-006R4 Surface Geometry Deviation Report",
            "",
            f"- External authority files changed: `{report['external_authority_files_changed']}`",
            f"- R4 new adapter cleanup applied: `{report['r4_new_adapter_cleanup_applied']}`",
            f"- Comparison: {report['comparison']}",
            f"- Wall vertex count: `{report['wall_vertex_count']}`",
            f"- Wing surface vertex count: `{report['wing_surface_vertex_count']}`",
            f"- Max nearest distance: `{report['max_nearest_distance_m']:.12g} m`",
            f"- P95 nearest distance: `{report['p95_nearest_distance_m']:.12g} m`",
            f"- Mean nearest distance: `{report['mean_nearest_distance_m']:.12g} m`",
            "",
            report["interpretation"],
            "",
            "Engineering read: no R4 route changes Baseline A external shape. The blocker is "
            "adapter/core ownership, not an intentional shape-relief workaround.",
            "",
        ]
    )


def render_yplus_and_boundary_layer_basis(summary: Mapping[str, Any]) -> str:
    yplus = summary["current_go_first_layer_yplus_estimate"]
    refs = summary["current_go_chord_refs_m"]
    return "\n".join(
        [
            "# WO-006R4 y+ And Boundary-Layer Basis",
            "",
            "## Authority Flow Condition",
            "",
            f"- Velocity: `{VELOCITY_MPS} m/s`",
            f"- Density: `{RHO_KGPM3} kg/m^3`",
            f"- Dynamic viscosity: `{MU_PA_S} Pa*s`",
            f"- Kinematic viscosity: `{MU_PA_S / RHO_KGPM3:.9g} m^2/s`",
            "",
            "## Current GO Chord / Re Basis",
            "",
            f"- Root chord: `{refs['root']:.9f} m`",
            f"- Mean aerodynamic chord / Cref: `{refs['mean_aerodynamic_chord']:.9f} m`",
            f"- Tip chord: `{refs['tip']:.9f} m`",
            (
                "- Re at Cref: "
                f"`{summary['current_go_reynolds_by_chord']['mean_aerodynamic_chord']:.3f}`"
            ),
            "",
            "## BL Policy",
            "",
            f"- First layer: `{BL_FIRST_HEIGHT_M} m`",
            f"- Growth ratio: `{BL_GROWTH_RATIO}`",
            f"- Layers: `{BL_LAYERS}`",
            (
                "- Total geometric BL thickness: "
                f"`{summary['boundary_layer_policy']['recommended_total_thickness_m']:.9f} m`"
            ),
            f"- Estimated y+ for first layer: `{yplus['yplus_for_5e-5m']:.3f}`",
            f"- Estimate model: `{yplus['estimate_model']}`",
            "",
            "This is a first-layer sizing estimate only. It is not a postprocessed SU2 "
            "surface y+ field because no conformal BL SU2 handoff exists in R4.",
            "",
            "Official-source read: SU2 wall-resolved viscous/RANS credibility requires "
            "no-slip wall BCs, a near-wall mesh consistent with the wall model choice, "
            "and solved wall-shear evidence. Gmsh topological BL extrusion remains a "
            "topology gate before solver physics can be interpreted.",
            "",
            "Official sources used:",
            "",
            "- Gmsh manual: https://gmsh.info/doc/texinfo/",
            "- SU2 mesh format: https://su2code.github.io/docs_v7/Mesh-File/",
            "- SU2 markers / boundary conditions: https://su2code.github.io/docs_v7/Markers-and-BC/",
            "- SU2 theory / wall functions: https://su2code.github.io/docs_v7/Theory/",
            "",
        ]
    )


def render_campaign_report(
    *,
    geometry: CurrentGoGeometry,
    route_decision: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    blockers: Sequence[Mapping[str, str]],
    yplus_summary: Mapping[str, Any],
    deviation_report: Mapping[str, Any],
) -> str:
    lines = [
        "# WO-006R4 BL Ownership Repair Campaign Report",
        "",
        f"Verdict: `{route_decision['verdict']}`",
        "",
        "## Authority Basis",
        "",
        f"- Mass authority: `{DESIGN_GROSS_MASS_KG} kg`.",
        f"- Span authority: `{PIPELINE_FULL_SPAN_M} m` full / `{PIPELINE_HALF_SPAN_M} m` half.",
        (
            f"- References: Sref `{geometry.reference.sref_full:.9f} m^2`, "
            f"Cref `{geometry.reference.cref:.9f} m`, "
            f"Bref `{geometry.reference.bref_full:.9f} m`."
        ),
        "- `106.828608 kg` remains suspect screening aggregate, and `16.5 m` remains local/splice screening only; both are not current truth.",
        "- External authority shape changed: `false`.",
        "",
        "## Route Decision",
        "",
        f"- BL/y+ handoff exists: `{route_decision['bl_mesh_handoff_written']}`",
        f"- Coefficient interpretable: `{route_decision['coefficient_interpretable']}`",
        f"- Baseline A reopen status: `{route_decision['baseline_a_reopen_status']}`",
        f"- Selected route: `{route_decision['selected_route']}`",
        "",
        "The campaign rejected a BL handoff because the only successful current-GO "
        "near-wall construction is an owned BL block without a conformal merged core "
        "and SU2 writer. That is not enough to expose `wing_wall` plus `farfield` in "
        "one credible viscous SU2 mesh.",
        "",
        "## Attempts",
        "",
    ]
    for attempt in attempts:
        lines.extend(
            [
                f"### {attempt.get('attempt_id')}",
                "",
                f"- route: `{attempt.get('route')}`",
                f"- status: `{attempt.get('status')}`",
                f"- accepted for: {attempt.get('accepted_for')}",
                f"- rejected for: {attempt.get('rejected_for')}",
                f"- failure mode: `{attempt.get('failure_mode')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Smallest Blocker",
            "",
            route_decision["limitation_proof"]["smallest_blocker"],
            "",
            "Concrete next repair target:",
            "",
            route_decision["limitation_proof"]["next_repair_target"],
            "",
            "## Geometry Deviation",
            "",
            (
                f"Max owned-BL wall-to-current-wing nearest distance: "
                f"`{deviation_report['max_nearest_distance_m']:.12g} m`."
            ),
            "No R4 adapter-level shape cleanup was applied.",
            "",
            "## BL / y+ Basis",
            "",
            (
                f"First layer `{BL_FIRST_HEIGHT_M} m`, layers `{BL_LAYERS}`, growth "
                f"`{BL_GROWTH_RATIO}`, estimated y+ "
                f"`{yplus_summary['current_go_first_layer_yplus_estimate']['yplus_for_5e-5m']:.3f}`."
            ),
            "This is estimated sizing, not postprocessed surface y+.",
            "",
            "## Coefficients",
            "",
            "No coefficient is interpretable. R3 no-BL coefficients, old Black Cat "
            "coefficients, old short BL smoke, and any no-convergence smoke remain "
            "route/readability evidence only.",
            "",
            "## Blockers",
            "",
        ]
    )
    for blocker in blockers:
        lines.append(
            f"- `{blocker['stage']}`: `{blocker['blocker']}`; next `{blocker['next_fix']}`"
        )
    lines.extend(
        [
            "",
            "## Engineering Caveats",
            "",
            "- This is adapter limitation evidence, not a final CFD validation.",
            "- A valid workaround must preserve geometry or report measured deviation; R4 does not change the source shape.",
            "- Low-Re HPA drag remains transition-sensitive; SA/SST/laminar setup cannot be chosen from this mesh route alone.",
            "- A future pass still needs marker audit, no-slip wall BCs, postprocessed y+, convergence, and grid-pair evidence before CL/CD is used.",
            "",
            "## Reviewer Prompt",
            "",
            "```text",
            "Review WO-006R4 as an adversarial aerospace/CFD reviewer. Check route_decision.json, blocker_register.csv, surface_geometry_deviation_report.md, yplus_and_boundary_layer_basis.md, solver_evidence_gate.json, and any core_probe_artifacts. Decide whether the verdict wo006r4_adapter_limitation_proven is supported without hiding topology by coarsening/remeshing, changing Baseline A authority shape, or promoting no-BL/unconverged coefficients.",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def render_next_goal(
    route_decision: Mapping[str, Any],
    blockers: Sequence[Mapping[str, str]],
) -> str:
    first_blocker = blockers[0]["blocker"] if blockers else "no blocker recorded"
    next_target = route_decision["limitation_proof"]["next_repair_target"]
    return f"""/goal In /Volumes/Samsung SSD/hpa-mdo, execute WO-006R5: implement the conformal mesh-native BL+core merge needed after WO-006R4.

Start from:
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r4_bl_ownership_repair/
- route_decision.json
- blocker_register.csv
- owned_bl_block_summary.json
- core_probe_artifacts/
- hpa_meshing_package/src/hpa_meshing/mesh_native/near_wall_block.py
- hpa_meshing_package/src/hpa_meshing/mesh_native/gmsh_polyhedral.py

Current WO-006R4 verdict: `{route_decision['verdict']}`.
First blocker: `{first_blocker}`.

Repair target:
{next_target}

Hard constraints:
- Preserve 98.5 kg, 34.332286 m full span, 17.166143 m half span, Sref/Cref/Bref.
- Do not change Baseline A external shape to make the mesh pass.
- Do not promote no-BL, tiny-smoke, old Black Cat, or unconverged coefficients.
- Only emit bl_mesh_handoff.v1.json after a conformal mixed BL+core SU2 mesh has
  marker audit pass, wall/farfield ownership, BL quality gate, and readability evidence.
"""


def status_counts(attempts: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for attempt in attempts:
        status = str(attempt.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def wall_vertices_from_block(block: WingBoundaryLayerBlock) -> list[tuple[float, float, float]]:
    wall_count = int(block.section_blocks[0].metadata["wall_node_count"])
    section_vertex_count = int(block.metadata["section_vertex_count"])
    section_count = int(block.metadata["station_count"])
    vertices = []
    for section_index in range(section_count):
        section_offset = section_index * section_vertex_count
        vertices.extend(block.vertices[section_offset + index] for index in range(wall_count))
    return vertices


def nearest_distance(
    vertex: tuple[float, float, float],
    candidates: Sequence[tuple[float, float, float]],
) -> float:
    return min(
        math.sqrt(
            (vertex[0] - candidate[0]) ** 2
            + (vertex[1] - candidate[1]) ** 2
            + (vertex[2] - candidate[2]) ** 2
        )
        for candidate in candidates
    )


def percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def geometric_total_thickness(first_height: float, growth_ratio: float, layers: int) -> float:
    return sum(first_height * growth_ratio**index for index in range(layers))


def compact_json(payload: Any, max_chars: int = 900) -> str:
    text = json.dumps(payload, sort_keys=True)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument(
        "--skip-core-probes",
        action="store_true",
        help="Skip Gmsh owned-BL core probes and write report-only artifacts.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_campaign(
        output_dir=args.output_dir,
        clean=not args.no_clean,
        run_core_probes=not args.skip_core_probes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
