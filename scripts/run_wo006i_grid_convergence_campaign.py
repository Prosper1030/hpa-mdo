#!/usr/bin/env python3
"""Run a Baseline A current-GO main-wing CFD grid-convergence campaign.

This runner is intentionally stricter than the older WO-006 route-completion
case. It now blocks the current no-BL route by default: a same-geometry ladder
without a conformal BL/core handoff, postprocessed near-wall evidence, and a
source-backed no-slip wall setup is still diagnostic evidence, not CFD
completion. Use ``--allow-no-bl-diagnostic`` only when deliberately reproducing
the known-bad route for debugging.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import signal
import subprocess
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

from run_wo006_current_go_cfd_completion import (  # noqa: E402
    REQUIRED_MARKERS,
    authority_payload as completion_authority_payload,
    geometry_recovery_payload,
    parse_history_detail,
    run_completion_case,
)
from run_wo006r1_go_baseline_a_cfd_bridge import (  # noqa: E402
    CANDIDATE_ID,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    MU_PA_S,
    RHO_KGPM3,
    SU2_COMMAND,
    VELOCITY_MPS,
    load_campaign_geometry,
)


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006i_grid_convergence_campaign"
DIRECT_STAGEBACK_PROBE_PATHS = (
    WO006_ROOT / "wo006m_face_coherent_stageback_mesh_probe" / "summary.json",
    WO006_ROOT / "wo006m_narrow_stageback_mesh_probe" / "summary.json",
)
CORE_CLOSURE_PROBE_PATHS = (
    WO006_ROOT / "wo006r20_left_tip_star_tessellation_probe" / "summary.json",
    WO006_ROOT / "wo006r19_loop_cap_owner_pyramid_probe" / "summary.json",
    WO006_ROOT / "wo006r18_handoff_residual_localization_probe" / "summary.json",
    WO006_ROOT / "wo006r17_hybrid_tet_prism_split_probe" / "summary.json",
    WO006_ROOT / "wo006r16_axis_agnostic_prism_split_probe" / "summary.json",
    WO006_ROOT / "wo006r15_prism_split_handoff_compatibility_probe" / "summary.json",
    WO006_ROOT / "wo006r14_mixed_handoff_conformality_probe" / "summary.json",
    WO006_ROOT / "wo006r13_loop_cap_geometric_seam_repair_probe" / "summary.json",
    WO006_ROOT / "wo006r12_loop_cap_core_mesh_probe" / "summary.json",
    WO006_ROOT / "wo006r11_core_facing_loop_closure_probe" / "summary.json",
    WO006_ROOT / "wo006r10_near_wall_core_closure_probe" / "summary.json",
)
CFD_SETUP_POLICY_ID = "baseline_a_wall_resolved_bl_preflight_gate_v1"
PHYSICS_SETUP_ID = "baseline_a_current_go_no_bl_rans_sa_alpha5"
PHYSICS_SETUP = {
    "physics_setup_id": PHYSICS_SETUP_ID,
    "solver": "INC_RANS",
    "turbulence_model": "SA",
    "wall_profile": "adiabatic_no_slip",
    "wall_bc": "MARKER_HEATFLUX",
    "farfield_bc": "MARKER_FAR",
    "boundary_layer": "not_used_no_bl_route",
    "near_wall_yplus_status": "missing",
    "conformal_bl_core_handoff_status": "missing",
    "intended_use": "diagnostic_only_invalid_for_cfd_completion",
    "alpha_deg": 5.0,
    "velocity_mps": VELOCITY_MPS,
    "density_kgpm3": RHO_KGPM3,
    "dynamic_viscosity_pa_s": MU_PA_S,
    "inc_nondim": "INITIAL_VALUES",
    "conv_num_method_flow": "JST",
    "cfl_number": 0.15,
    "linear_solver_error": "1e-5",
    "linear_solver_iter": 12,
}
COEFFICIENT_RELATIVE_TOL = 0.02
CM_ABSOLUTE_TOL = 0.005
FORCE_STABILITY_WINDOW_ROWS = 100
FORCE_WINDOW_RELATIVE_TOL = 0.01
RESIDUAL_WINDOW_ABS_SLOPE_TOL = 0.05
MINIMUM_LADDER_ITERATIONS = 100
HPA_MAIN_WING_CD_PLAUSIBILITY_MAX = 0.15
SU2_REFERENCE_REQUIREMENTS = {
    "source": "SU2 incompressible turbulent NACA0012 tutorial and Markers/BC docs",
    "url": "https://su2code.github.io/tutorials/Inc_Turbulent_NACA0012/",
    "marker_bc_url": "https://su2code.github.io/docs_v7/Markers-and-BC/",
    "required_setup": [
        "INC_RANS / SA or otherwise justified viscous setup",
        "solid wall uses a no-slip wall BC such as MARKER_HEATFLUX with heatflux 0.0",
        "farfield marker is explicit and matches the mesh marker tag",
        "incompressible coefficient normalization uses INC_NONDIM=INITIAL_VALUES or an equivalent rho/V reference, not DIMENSIONAL=1 Pa",
        "near-wall spacing or wall-function choice is justified; wall-resolved target is y+ < 1",
        "convergence uses residual and coefficient history windows, not a short smoke budget; "
        "local force stability requires a 100-iteration CL/CD window within 1 percent",
    ],
}


@dataclass(frozen=True)
class RungSpec:
    rung_id: str
    wing_h: float
    target_cells: int
    role: str
    run_solver: bool = True


DEFAULT_RUNG_SPECS = (
    RungSpec("route_smoke", 0.15, 500_000, "route_smoke", True),
    RungSpec("coarse", 0.10, 1_000_000, "coarse", True),
    RungSpec("medium", 0.08, 3_000_000, "medium", True),
    RungSpec("fine", 0.06, 10_000_000, "fine_closest_local", True),
    RungSpec("ten_m_probe", 0.04, 10_000_000, "ten_m_mesh_probe", True),
)


def evaluate_grid_convergence(
    rungs: Sequence[Mapping[str, Any]],
    *,
    require_wall_resolved: bool = True,
    setup_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    successful = []
    plausibility_failures: list[dict[str, Any]] = []
    force_window_failures: list[dict[str, Any]] = []

    if setup_gate is not None and setup_gate.get("status") != "pass":
        blockers.extend(f"setup_{item}" for item in setup_gate.get("blockers", []))

    for rung in rungs:
        rung_id = str(rung.get("rung_id") or "unknown")
        status = str(rung.get("status") or "")
        if status not in {"success", "completed"}:
            blockers.append(f"{rung_id}_not_successful")
            continue

        mesh = rung.get("mesh") or {}
        su2 = rung.get("su2") or {}
        coefficients = su2.get("coefficients") or {}
        if mesh.get("marker_status") != "pass" or mesh.get("config_marker_match_status") == "fail":
            blockers.append(f"{rung_id}_marker_or_config_mismatch")
        if mesh.get("quality_status") != "pass":
            blockers.append(f"{rung_id}_mesh_quality_fail")
        if su2.get("run_status") != "completed":
            blockers.append(f"{rung_id}_su2_not_completed")
        if int(su2.get("iterations") or 0) < MINIMUM_LADDER_ITERATIONS:
            blockers.append(f"{rung_id}_iterations_below_minimum")
        for coeff_name in ("cl", "cd", "cm"):
            if not _is_finite(coefficients.get(coeff_name)):
                blockers.append(f"{rung_id}_missing_finite_{coeff_name}")
        cd_value = _optional_float(coefficients.get("cd"))
        if (
            cd_value is not None
            and math.isfinite(cd_value)
            and cd_value > HPA_MAIN_WING_CD_PLAUSIBILITY_MAX
        ):
            blockers.append(f"{rung_id}_cd_implausibly_high_for_hpa_main_wing")
            plausibility_failures.append(
                {
                    "rung_id": rung_id,
                    "cd": cd_value,
                    "limit": HPA_MAIN_WING_CD_PLAUSIBILITY_MAX,
                    "reason": "stable_force_history_at_order-of-magnitude_high_drag_is_not_cfd_completion",
                }
            )
        force_stability = su2.get("force_stability") or {}
        if force_stability.get("status") != "pass" or _force_stability_value_fails(force_stability):
            blockers.append(f"{rung_id}_force_stability_fail")
        if _force_stability_window_fails(force_stability):
            blockers.append(f"{rung_id}_force_stability_window_too_short")
            force_window_failures.append(
                {
                    "rung_id": rung_id,
                    "observed_window_rows": force_stability.get("window_rows"),
                    "minimum_window_rows": FORCE_STABILITY_WINDOW_ROWS,
                }
            )
        residual_stability = su2.get("residual_stability") or {}
        if residual_stability.get("status") != "pass" or _residual_stability_value_fails(residual_stability):
            blockers.append(f"{rung_id}_residual_stability_fail")
        if require_wall_resolved and rung.get("boundary_layer_status") != "pass":
            blockers.append(f"{rung_id}_boundary_layer_not_pass")
        if require_wall_resolved and rung.get("wall_resolution_status") != "pass":
            blockers.append(f"{rung_id}_wall_resolution_not_pass")
        if require_wall_resolved and rung.get("near_wall_yplus_status") != "pass":
            blockers.append(f"{rung_id}_near_wall_yplus_not_pass")

        if not any(item.startswith(f"{rung_id}_") for item in blockers):
            successful.append(rung)

    physics_ids = {str(rung.get("physics_setup_id") or "") for rung in successful}
    geometry_sources = {str(rung.get("geometry_source") or "") for rung in successful}
    if len(physics_ids) > 1:
        blockers.append("successful_rungs_do_not_share_physics_setup")
    if len(geometry_sources) > 1:
        blockers.append("successful_rungs_do_not_share_geometry_source")

    successful = sorted(
        successful,
        key=lambda rung: int((rung.get("mesh") or {}).get("volume_element_count") or 0),
    )
    finite_completed = _finite_completed_rungs(rungs)
    trend = _grid_trend(successful)
    finite_completed_trend = _grid_trend(finite_completed)
    if trend["status"] == "insufficient_successful_rungs" and len(finite_completed) >= 3:
        trend = {
            **finite_completed_trend,
            "trend_basis": "finite_completed_rungs_before_force_stability_gate",
            "force_stability_gate": "fail",
        }
    if len(successful) < 3:
        blockers.append("fewer_than_three_successful_rungs")
    elif trend["status"] not in {
        "stable_enough_for_low_confidence",
        "stable_and_wall_resolved",
    }:
        blockers.append("grid_trend_not_stable")

    blockers = _dedupe(blockers)
    attempted_ladder = len(rungs) >= 3
    setup_blocked = setup_gate is not None and setup_gate.get("status") != "pass"
    if setup_blocked:
        cfd_status = "mesh_ladder_incomplete"
    elif not successful and rungs and not attempted_ladder:
        cfd_status = "route_smoke"
    elif len(successful) < 2 and not attempted_ladder:
        cfd_status = "route_smoke"
    elif blockers:
        cfd_status = "mesh_ladder_incomplete"
    elif require_wall_resolved:
        cfd_status = "grid_convergence_ready"
    else:
        cfd_status = "low_confidence_cfd"

    return {
        "schema_version": "wo006i_grid_convergence_gate.v1",
        "goal_status": "COMPLETE"
        if cfd_status in {"low_confidence_cfd", "grid_convergence_ready"}
        else "INCOMPLETE",
        "cfd_status": cfd_status,
        "blockers": blockers,
        "successful_rung_count": len(successful),
        "successful_rungs": [str(rung.get("rung_id")) for rung in successful],
        "grid_trend": trend,
        "finite_completed_rung_count": len(finite_completed),
        "finite_completed_rungs": [str(rung.get("rung_id")) for rung in finite_completed],
        "require_wall_resolved": bool(require_wall_resolved),
        "minimum_iterations": MINIMUM_LADDER_ITERATIONS,
        "setup_gate_status": None if setup_gate is None else setup_gate.get("status"),
        "engineering_plausibility_gate": {
            "status": "pass" if not plausibility_failures else "fail",
            "cd_max_for_hpa_main_wing": HPA_MAIN_WING_CD_PLAUSIBILITY_MAX,
            "failures": plausibility_failures,
            "engineering_basis": (
                "Baseline A main-wing CD should be O(0.0XX) in this low-speed setup; "
                "CD above the conservative plausibility limit indicates setup/domain/"
                "geometry/solver trouble even when the force history is numerically stable."
            ),
        },
        "force_stability_gate": {
            "status": "pass" if not force_window_failures else "fail",
            "minimum_window_rows": FORCE_STABILITY_WINDOW_ROWS,
            "cl_cd_relative_spread_max": FORCE_WINDOW_RELATIVE_TOL,
            "cm_absolute_spread_max": CM_ABSOLUTE_TOL,
            "failures": force_window_failures,
            "engineering_basis": (
                "A short tail of apparently steady coefficients is route smoke, not "
                "CFD convergence evidence; CL/CD/Cm must stay within tolerance across "
                "the configured 100-iteration window."
            ),
        },
        "engineering_trust_boundary": _trust_boundary(cfd_status),
    }


def evaluate_cfd_setup_gate(
    *,
    physics_setup: Mapping[str, Any] = PHYSICS_SETUP,
    allow_no_bl_diagnostic: bool = False,
    direct_stageback_artifacts: Sequence[Mapping[str, Any]] | None = None,
    core_closure_artifacts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []

    setup_id = str(physics_setup.get("physics_setup_id") or "")
    boundary_layer = str(physics_setup.get("boundary_layer") or "")
    if "no_bl" in setup_id:
        blockers.append("physics_setup_is_no_bl_diagnostic")
    if not boundary_layer or boundary_layer.startswith("not_used"):
        blockers.append("boundary_layer_mesh_missing")
    if physics_setup.get("conformal_bl_core_handoff_status") != "pass":
        blockers.append("conformal_bl_core_handoff_missing")
    if physics_setup.get("near_wall_yplus_status") != "pass":
        blockers.append("postprocessed_near_wall_yplus_missing")
    if physics_setup.get("wall_profile") != "adiabatic_no_slip":
        blockers.append("solid_wall_not_no_slip_adiabatic")
    if physics_setup.get("wall_bc") not in {"MARKER_HEATFLUX", "MARKER_ISOTHERMAL"}:
        blockers.append("solid_wall_bc_not_viscous_no_slip")
    if physics_setup.get("farfield_bc") != "MARKER_FAR":
        blockers.append("farfield_bc_not_explicit_marker_far")
    if str(physics_setup.get("inc_nondim") or "").strip().upper() != "INITIAL_VALUES":
        blockers.append("coefficient_normalization_not_initial_values")

    core_closure_topology = _core_closure_topology_summary(core_closure_artifacts or ())
    stageback_topology = _stageback_topology_summary(direct_stageback_artifacts or ())
    if _core_route_supersedes_direct_stageback(
        core_closure_topology=core_closure_topology,
        stageback_topology=stageback_topology,
    ):
        stageback_topology = {
            **stageback_topology,
            "status": "superseded_by_core_mesh_route",
            "superseded_blocker": "direct_stageback_topology_plc_segment_facet",
            "active_blocker": False,
            "engineering_read": (
                "The direct stageback PLC failure remains historical diagnostic "
                "evidence, but the active route has moved to the loop-cap core "
                "mesh path; do not keep the stale direct-stageback blocker once "
                "a newer core-mesh route artifact exists."
            ),
        }
    elif stageback_topology["status"] == "blocked":
        blockers.append("direct_stageback_topology_plc_segment_facet")

    if core_closure_topology["status"] == "core_mesh_blocked":
        blockers.append(
            str(core_closure_topology.get("blocker") or "near_wall_core_mesh_probe_blocked")
        )
    if core_closure_topology["status"] == "handoff_hybrid_split_blocked":
        blockers.append("near_wall_hybrid_tet_prism_handoff_not_compatible")
    if core_closure_topology["status"] == "handoff_prism_split_blocked":
        blockers.append("near_wall_prism_split_handoff_not_compatible")
    if core_closure_topology["status"] == "handoff_conformality_blocked":
        blockers.append("near_wall_mixed_handoff_interface_not_conformal")
    if core_closure_topology["status"] == "blocked":
        blockers.append("near_wall_core_interface_closure_blocked")
    if core_closure_topology["status"] == "surface_ready_core_mesh_pending":
        blockers.append("near_wall_core_mesh_probe_missing")
    if core_closure_topology["status"] == "core_mesh_ready_handoff_pending":
        blockers.append("near_wall_merged_mesh_handoff_missing")
    if core_closure_topology["status"] == "handoff_repair_basis_ready_mixed_mesh_pending":
        blockers.append("near_wall_merged_mesh_handoff_missing")
    if core_closure_topology["status"] == "blocked" and core_closure_topology.get(
        "wall_edge_gap_status"
    ) == ("blocked_by_physical_wall_edge_dependency"):
        blockers.append("near_wall_core_wall_edge_gap_dependency")
    if (
        core_closure_topology["status"] == "blocked"
        and core_closure_topology.get("full_shell_policy_status") == "forbidden"
    ):
        blockers.append("near_wall_full_shell_physical_wall_misownership")

    if blockers and allow_no_bl_diagnostic:
        warnings.append("no_bl_route_allowed_for_diagnostics_only")

    return {
        "schema_version": "wo006i_cfd_setup_gate.v1",
        "policy_id": CFD_SETUP_POLICY_ID,
        "status": "pass" if not blockers else ("diagnostic_allowed" if allow_no_bl_diagnostic else "blocked"),
        "allow_no_bl_diagnostic": bool(allow_no_bl_diagnostic),
        "blockers": _dedupe(blockers),
        "warnings": warnings,
        "physics_setup_id": setup_id,
        "stageback_topology": stageback_topology,
        "core_closure_topology": core_closure_topology,
        "reference_requirements": SU2_REFERENCE_REQUIREMENTS,
        "engineering_read": (
            "The setup is CFD-grade enough to attempt a wall-resolved mesh ladder."
            if not blockers
            else "Do not run or report this setup as CFD completion; repair BL/BC/near-wall handoff first."
        ),
    }


def _core_route_supersedes_direct_stageback(
    *,
    core_closure_topology: Mapping[str, Any],
    stageback_topology: Mapping[str, Any],
) -> bool:
    return (
        stageback_topology.get("status") == "blocked"
        and core_closure_topology.get("status")
        in {
            "handoff_hybrid_split_blocked",
            "handoff_conformality_blocked",
            "handoff_prism_split_blocked",
            "core_mesh_ready_handoff_pending",
            "handoff_repair_basis_ready_mixed_mesh_pending",
            "pass",
        }
    )


def run_campaign(
    *,
    output_dir: Path,
    rung_specs: Sequence[RungSpec] = DEFAULT_RUNG_SPECS,
    clean: bool = True,
    iterations: int = 180,
    minimum_iterations: int = MINIMUM_LADDER_ITERATIONS,
    solver_command: str = SU2_COMMAND,
    solver_threads: int = 4,
    solver_timeout_seconds: float = 3600.0,
    rung_timeout_seconds: float = 5400.0,
    stop_after_first_hard_failure: bool = False,
    allow_no_bl_diagnostic: bool = False,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    geometry = load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
    authority = completion_authority_payload(geometry)
    authority.update(
        {
            "candidate_id": CANDIDATE_ID,
            "geometry_manifest_path": str(geometry.geometry_manifest_path),
            "source_avl_path": str(geometry.source_avl_path),
            "surface_ownership": {
                "wing_wall": "mesh-native current-GO indexed wing surface from section_table.csv and airfoil DAT loops",
                "farfield": "mesh-native farfield box surface generated around the same wing",
                "fluid": "Gmsh physical volume group for external-flow tet volume",
            },
            "physical_group_policy": {
                "required_surface_markers": list(REQUIRED_MARKERS),
                "required_volume_marker": "fluid",
                "config_mesh_marker_match_required": True,
            },
            "geometry_recovery": geometry_recovery_payload(geometry),
        }
    )
    write_json(output_dir / "authority_and_geometry.json", authority)

    direct_stageback_artifacts = load_direct_stageback_artifacts()
    setup_gate = evaluate_cfd_setup_gate(
        allow_no_bl_diagnostic=allow_no_bl_diagnostic,
        direct_stageback_artifacts=direct_stageback_artifacts,
        core_closure_artifacts=load_core_closure_artifacts(),
    )
    if setup_gate["status"] == "blocked":
        summary = build_preflight_blocked_summary(
            authority=authority,
            rung_specs=rung_specs,
            setup_gate=setup_gate,
        )
        write_campaign_outputs(output_dir, summary)
        return summary

    rung_summaries: list[dict[str, Any]] = []
    for spec in rung_specs:
        case_dir = output_dir / "cases" / spec.rung_id
        summary = run_rung_with_timeout(
            spec=spec,
            case_dir=case_dir,
            iterations=iterations,
            minimum_iterations=minimum_iterations,
            solver_command=solver_command,
            solver_threads=solver_threads,
            solver_timeout_seconds=solver_timeout_seconds,
            rung_timeout_seconds=rung_timeout_seconds,
        )
        rung_summaries.append(summary)
        write_json(case_dir / "attempt_summary.json", summary)
        if (
            stop_after_first_hard_failure
            and summary.get("status") not in {"success", "completed"}
            and spec.role != "route_smoke"
        ):
            break

    gate = evaluate_grid_convergence(
        rung_summaries,
        require_wall_resolved=True,
        setup_gate=setup_gate,
    )
    summary = {
        "schema_version": "wo006i_grid_convergence_campaign.v1",
        "authority": authority,
        "physics_setup": PHYSICS_SETUP,
        "setup_gate": setup_gate,
        "rung_specs": [spec.__dict__ for spec in rung_specs],
        "rungs": rung_summaries,
        "grid_convergence_gate": gate,
        "blocked_claims": _blocked_claims(gate["cfd_status"]),
    }
    write_campaign_outputs(output_dir, summary)
    return summary


def summarize_existing_campaign(
    *,
    output_dir: Path,
    rung_specs: Sequence[RungSpec] = DEFAULT_RUNG_SPECS,
) -> dict[str, Any]:
    authority_path = output_dir / "authority_and_geometry.json"
    if authority_path.exists():
        authority = load_json(authority_path)
    else:
        geometry = load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
        authority = completion_authority_payload(geometry)
        authority.update(
            {
                "candidate_id": CANDIDATE_ID,
                "geometry_manifest_path": str(geometry.geometry_manifest_path),
                "source_avl_path": str(geometry.source_avl_path),
                "geometry_recovery": geometry_recovery_payload(geometry),
            }
        )
    rung_summaries: list[dict[str, Any]] = []
    for spec in rung_specs:
        path = output_dir / "cases" / spec.rung_id / "attempt_summary.json"
        if path.exists():
            rung_summaries.append(load_json(path))
        else:
            rung_summaries.append(
                {
                    "rung_id": spec.rung_id,
                    "role": spec.role,
                    "wing_h": spec.wing_h,
                    "target_cells": spec.target_cells,
                    "status": "missing",
                    "failure_code": "attempt_summary_missing",
                    "physics_setup_id": PHYSICS_SETUP_ID,
                    "geometry_source": CANDIDATE_ID,
                }
            )
    setup_gate = evaluate_cfd_setup_gate(
        allow_no_bl_diagnostic=True,
        direct_stageback_artifacts=load_direct_stageback_artifacts(),
        core_closure_artifacts=load_core_closure_artifacts(),
    )
    gate = evaluate_grid_convergence(
        rung_summaries,
        require_wall_resolved=True,
        setup_gate=setup_gate,
    )
    summary = {
        "schema_version": "wo006i_grid_convergence_campaign.v1",
        "authority": authority,
        "physics_setup": PHYSICS_SETUP,
        "setup_gate": setup_gate,
        "rung_specs": [spec.__dict__ for spec in rung_specs],
        "rungs": rung_summaries,
        "grid_convergence_gate": gate,
        "blocked_claims": _blocked_claims(gate["cfd_status"]),
    }
    write_campaign_outputs(output_dir, summary)
    return summary


def build_preflight_blocked_summary(
    *,
    authority: Mapping[str, Any],
    rung_specs: Sequence[RungSpec],
    setup_gate: Mapping[str, Any],
) -> dict[str, Any]:
    gate = evaluate_grid_convergence(
        [],
        require_wall_resolved=True,
        setup_gate=setup_gate,
    )
    return {
        "schema_version": "wo006i_grid_convergence_campaign.v1",
        "authority": authority,
        "physics_setup": PHYSICS_SETUP,
        "setup_gate": setup_gate,
        "rung_specs": [spec.__dict__ for spec in rung_specs],
        "rungs": [],
        "grid_convergence_gate": gate,
        "blocked_claims": _blocked_claims(gate["cfd_status"]),
        "preflight_decision": {
            "status": "blocked_before_solver",
            "reason": "current setup cannot produce CFD completion evidence before BL/core/yplus gates pass",
        },
    }


def write_campaign_outputs(output_dir: Path, summary: Mapping[str, Any]) -> None:
    write_json(output_dir / "grid_convergence_summary.json", summary)
    write_csv(output_dir / "mesh_ladder_table.csv", [_mesh_ladder_row(r) for r in summary["rungs"]])
    write_csv(output_dir / "su2_iteration_table.csv", [_su2_iteration_row(r) for r in summary["rungs"]])
    (output_dir / "grid_convergence_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    (output_dir / "reviewer_prompt.md").write_text(render_reviewer_prompt(summary), encoding="utf-8")


def run_rung_with_timeout(
    *,
    spec: RungSpec,
    case_dir: Path,
    iterations: int,
    minimum_iterations: int,
    solver_command: str,
    solver_threads: int,
    solver_timeout_seconds: float,
    rung_timeout_seconds: float,
) -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue: mp.Queue = context.Queue()
    payload = {
        "spec": spec.__dict__,
        "case_dir": str(case_dir),
        "iterations": iterations,
        "minimum_iterations": minimum_iterations,
        "solver_command": solver_command,
        "solver_threads": solver_threads,
        "solver_timeout_seconds": solver_timeout_seconds,
    }
    process = context.Process(target=_rung_worker, kwargs={"queue": queue, "payload": payload})
    start = time.time()
    rss_samples: list[dict[str, float | int]] = []
    process.start()
    while process.is_alive() and time.time() - start < rung_timeout_seconds:
        time.sleep(5.0)
        rss_kb = _process_tree_rss_kb(process.pid)
        if rss_kb is not None:
            rss_samples.append(
                {
                    "elapsed_seconds": time.time() - start,
                    "rss_kb": rss_kb,
                }
            )

    if process.is_alive():
        _terminate_process_tree(process.pid)
        process.join(10.0)
        if process.is_alive():
            process.kill()
            process.join(5.0)
        return {
            "rung_id": spec.rung_id,
            "status": "timeout",
            "failure_code": "rung_timeout",
            "timeout_seconds": rung_timeout_seconds,
            "elapsed_seconds": time.time() - start,
            "process_exitcode": process.exitcode,
            "rss_samples": rss_samples,
            "peak_sampled_rss_kb": _peak_rss(rss_samples),
            "case_dir": str(case_dir),
            "physics_setup_id": PHYSICS_SETUP_ID,
            "geometry_source": CANDIDATE_ID,
        }

    process.join()
    if queue.empty():
        return {
            "rung_id": spec.rung_id,
            "status": "terminated",
            "failure_code": "worker_no_payload",
            "elapsed_seconds": time.time() - start,
            "process_exitcode": process.exitcode,
            "rss_samples": rss_samples,
            "peak_sampled_rss_kb": _peak_rss(rss_samples),
            "case_dir": str(case_dir),
            "physics_setup_id": PHYSICS_SETUP_ID,
            "geometry_source": CANDIDATE_ID,
        }
    summary = dict(queue.get())
    summary["process_exitcode"] = process.exitcode
    summary["rss_samples"] = rss_samples
    summary["peak_sampled_rss_kb"] = _peak_rss(rss_samples)
    summary["case_dir"] = str(case_dir)
    return summary


def _rung_worker(queue: Any, *, payload: Mapping[str, Any]) -> None:
    spec_payload = payload["spec"]
    spec = RungSpec(**spec_payload)
    case_dir = Path(str(payload["case_dir"]))
    start = time.time()
    try:
        report = run_completion_case(
            output_dir=case_dir,
            clean=True,
            wing_h=spec.wing_h,
            alpha_deg=PHYSICS_SETUP["alpha_deg"],
            iterations=int(payload["iterations"]) if spec.run_solver else 1,
            minimum_iterations=int(payload["minimum_iterations"]),
            solver_command=str(payload["solver_command"]),
            solver_threads=int(payload["solver_threads"]),
            solver_timeout_seconds=float(payload["solver_timeout_seconds"]),
        )
        summary = summarize_run_report(
            spec=spec,
            report=report,
            elapsed_seconds=time.time() - start,
        )
    except Exception as exc:  # pragma: no cover - real Gmsh/SU2 failures are data.
        case_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "rung_id": spec.rung_id,
            "role": spec.role,
            "wing_h": spec.wing_h,
            "target_cells": spec.target_cells,
            "status": "failed",
            "failure_code": exc.__class__.__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "elapsed_seconds": time.time() - start,
            "physics_setup_id": PHYSICS_SETUP_ID,
            "geometry_source": CANDIDATE_ID,
            "wall_resolution_status": "not_wall_resolved_no_bl_route",
            "boundary_layer_status": "not_used_no_bl_route",
            "near_wall_yplus_status": "missing",
        }
    queue.put(summary)


def summarize_run_report(
    *,
    spec: RungSpec,
    report: Mapping[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    mesh_report = report.get("mesh_report") or {}
    quality = mesh_report.get("quality_metrics") or {}
    marker_audit = report.get("marker_audit") or {}
    mesh_summary = marker_audit.get("mesh_summary") or {}
    history_path = report.get("history_path")
    history_detail = parse_history_detail(Path(history_path)) if history_path else None
    stability = (
        summarize_history_stability(Path(history_path))
        if history_path and Path(history_path).exists()
        else {
            "force_stability": {"status": "fail", "reason": "history_missing"},
            "residual_stability": {"status": "fail", "reason": "history_missing"},
        }
    )
    coefficients = ((history_detail or {}).get("final_coefficients") or {})
    cm = _first_finite(coefficients.get("cmy"), coefficients.get("cmz"), coefficients.get("cmx"))
    run_status = report.get("run_status")
    completion_gate = report.get("completion_gate") or {}
    status = "success" if completion_gate.get("status") == "pass" else "failed"
    physical_groups = mesh_report.get("physical_groups") or {}
    markers = mesh_summary.get("markers") or {}
    return {
        "rung_id": spec.rung_id,
        "role": spec.role,
        "wing_h": spec.wing_h,
        "target_cells": spec.target_cells,
        "status": status,
        "failure_code": report.get("failure_code"),
        "elapsed_seconds": elapsed_seconds,
        "physics_setup_id": PHYSICS_SETUP_ID,
        "geometry_source": CANDIDATE_ID,
        "geometry_source_path": (report.get("authority_basis") or {}).get("geometry_source"),
        "surface_ownership": {
            "wing_wall": "current-GO mesh-native wing faces",
            "farfield": "mesh-native farfield box",
            "fluid": "Gmsh external-flow volume",
        },
        "wall_resolution_status": "not_wall_resolved_no_bl_route",
        "boundary_layer_status": "not_used_no_bl_route",
        "near_wall_yplus_status": "missing",
        "mesh": {
            "mesh_path": report.get("mesh_path"),
            "gmsh_mesh_path": report.get("gmsh_mesh_path"),
            "node_count": mesh_report.get("node_count"),
            "volume_element_count": mesh_report.get("volume_element_count"),
            "volume_element_type_counts": mesh_report.get("volume_element_type_counts"),
            "marker_status": marker_audit.get("status"),
            "config_marker_match_status": marker_audit.get("status"),
            "markers": markers,
            "quality_status": (mesh_report.get("mesh_quality_gate") or {}).get("status"),
            "quality_blockers": (mesh_report.get("mesh_quality_gate") or {}).get("blockers"),
            "quality": {
                "min_gamma": quality.get("min_gamma"),
                "min_sicn": quality.get("min_sicn"),
                "min_sige": quality.get("min_sige"),
                "non_positive_volume_count": quality.get("non_positive_volume_count"),
                "non_positive_min_sicn_count": quality.get("non_positive_min_sicn_count"),
                "non_positive_min_sige_count": quality.get("non_positive_min_sige_count"),
                "ill_shaped_volume_element_count": quality.get("ill_shaped_volume_element_count"),
            },
            "physical_groups": physical_groups,
            "mesh_sizing": mesh_report.get("mesh_sizing"),
        },
        "su2": {
            "run_status": run_status,
            "returncode": report.get("returncode"),
            "config_path": report.get("runtime_cfg_path"),
            "solver_log_path": report.get("solver_log_path"),
            "history_path": history_path,
            "iterations": (history_detail or {}).get("final_iteration"),
            "coefficients": {
                "cl": coefficients.get("cl"),
                "cd": coefficients.get("cd"),
                "cm": cm,
                "cmx": coefficients.get("cmx"),
                "cmy": coefficients.get("cmy"),
                "cmz": coefficients.get("cmz"),
            },
            "residuals": (history_detail or {}).get("final_residuals") or {},
            "force_stability": stability["force_stability"],
            "residual_stability": stability["residual_stability"],
            "iterative_gate": report.get("iterative_gate"),
        },
        "completion_gate": completion_gate,
        "engineering_read": (
            "Same-geometry no-BL RANS/SA rung. It is eligible for mesh-sensitivity "
            "trend checks only; it is not BL/y+ viscous drag truth."
        ),
    }


def summarize_history_stability(
    path: Path,
    *,
    window_rows: int = FORCE_STABILITY_WINDOW_ROWS,
) -> dict[str, Any]:
    rows = _read_history_rows(path)
    if not rows:
        return {
            "force_stability": {"status": "fail", "reason": "history_empty"},
            "residual_stability": {"status": "fail", "reason": "history_empty"},
        }
    window = rows[-min(window_rows, len(rows)) :]
    force_columns = {"cl": "CL", "cd": "CD", "cm": "CMy"}
    force_spreads: dict[str, float | None] = {}
    force_reasons: list[str] = []
    for out_key, column in force_columns.items():
        values = [_optional_float(row.get(column)) for row in window]
        values = [value for value in values if value is not None and math.isfinite(value)]
        if len(values) < 2:
            force_reasons.append(f"{out_key}_window_missing")
            force_spreads[out_key] = None
            continue
        if out_key == "cm":
            spread = max(values) - min(values)
            force_spreads[out_key] = spread
            if spread > CM_ABSOLUTE_TOL:
                force_reasons.append(f"{out_key}_window_spread_high")
        else:
            scale = max(abs(values[-1]), 1.0e-12)
            spread = (max(values) - min(values)) / scale
            force_spreads[out_key] = spread
            if spread > FORCE_WINDOW_RELATIVE_TOL:
                force_reasons.append(f"{out_key}_window_spread_high")

    residual_columns = [key for key in rows[-1] if key.lower().startswith("rms[")]
    residual_slopes: dict[str, float | None] = {}
    residual_reasons: list[str] = []
    for column in residual_columns:
        values = [_optional_float(row.get(column)) for row in window]
        values = [value for value in values if value is not None and math.isfinite(value)]
        if len(values) < 2:
            residual_slopes[column] = None
            residual_reasons.append(f"{column}_window_missing")
            continue
        slope = (values[-1] - values[0]) / max(1, len(values) - 1)
        residual_slopes[column] = slope
        if slope > RESIDUAL_WINDOW_ABS_SLOPE_TOL:
            residual_reasons.append(f"{column}_worsening")

    return {
        "force_stability": {
            "status": "pass" if not force_reasons else "fail",
            "window_rows": len(window),
            "max_relative_spread": max(
                [float(v) for key, v in force_spreads.items() if key != "cm" and v is not None],
                default=None,
            ),
            "cm_absolute_spread": force_spreads.get("cm"),
            "spreads": force_spreads,
            "reasons": force_reasons,
        },
        "residual_stability": {
            "status": "pass" if residual_columns and not residual_reasons else "fail",
            "window_rows": len(window),
            "max_abs_slope_per_iter": max(
                [abs(float(value)) for value in residual_slopes.values() if value is not None],
                default=None,
            ),
            "trend": "not_worsening" if residual_columns and not residual_reasons else "unstable",
            "slopes": residual_slopes,
            "reasons": residual_reasons,
        },
    }


def render_report(summary: Mapping[str, Any]) -> str:
    gate = summary["grid_convergence_gate"]
    authority = summary["authority"]
    setup_gate = summary.get("setup_gate") or {}
    stageback_topology = setup_gate.get("stageback_topology") or {}
    core_closure_topology = setup_gate.get("core_closure_topology") or {}
    residual_localization = (
        core_closure_topology.get("handoff_residual_localization") or {}
    )
    loop_cap_owner_pyramid = (
        core_closure_topology.get("loop_cap_owner_pyramid") or {}
    )
    left_tip_star_tessellation = (
        core_closure_topology.get("left_tip_star_tessellation") or {}
    )
    lines = [
        "# WO-006I Baseline A Main-Wing CFD Grid-Convergence Campaign",
        "",
        f"GOAL_STATUS: `{gate['goal_status']}`",
        f"CFD_STATUS: `{gate['cfd_status']}`",
        "",
        "## Authority And Geometry",
        "",
        f"- candidate: `{authority['candidate_id']}`",
        f"- design mass: `{authority['design_gross_mass_kg']} kg`",
        f"- full span: `{authority['full_span_m']} m`",
        f"- half span: `{authority['half_span_m']} m`",
        f"- geometry source: `{authority['geometry_source']}`",
        f"- geometry manifest: `{authority['geometry_manifest_path']}`",
        f"- external shape changed: `{authority['geometry_recovery']['external_shape_changed']}`",
        "",
        "## CFD Setup Gate",
        "",
        f"- setup gate: `{setup_gate.get('status')}`",
        f"- policy: `{setup_gate.get('policy_id')}`",
        f"- stageback topology: `{stageback_topology.get('status')}`",
        f"- core closure topology: `{core_closure_topology.get('status')}`",
        f"- core closure blocker: `{core_closure_topology.get('blocker')}`",
        f"- recommended repair: `{core_closure_topology.get('recommended_repair')}`",
        f"- R18 residual triangles: `{residual_localization.get('residual_triangle_count')}`",
        f"- R18 loop-cap fans / incompatible cells: `{residual_localization.get('loop_cap_fan_count')}` / `{residual_localization.get('incompatible_cell_count')}`",
        f"- R19 loop-cap owner pyramids: `{loop_cap_owner_pyramid.get('matched_core_wall_loop_cap_triangle_count')}` / `{loop_cap_owner_pyramid.get('core_wall_loop_cap_triangle_count')}`",
        f"- R20 left-tip star target triangles: `{left_tip_star_tessellation.get('matched_target_triangle_count')}` / `{left_tip_star_tessellation.get('target_triangle_count')}`",
        f"- R20 non-positive star tets: `{left_tip_star_tessellation.get('non_positive_star_tet_count')}`",
        f"- engineering read: `{setup_gate.get('engineering_read')}`",
        "",
        "## Physics Setup",
        "",
        f"- setup id: `{summary['physics_setup']['physics_setup_id']}`",
        "- solver: `INC_RANS` / turbulence: `SA` / wall: `adiabatic_no_slip`",
        "- boundary layer: `not_used_no_bl_route`",
        "- alpha: `5 deg`; velocity: `6.5 m/s`",
        "",
        "## Mesh Ladder",
        "",
        "| rung | status | h | nodes | cells | markers | quality | iterations | CL | CD | Cm | force | residual |",
        "|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|---|---|",
    ]
    for rung in summary["rungs"]:
        lines.append(_rung_markdown_row(rung))
    lines.extend(
        [
            "",
            "## Grid Trend",
            "",
            f"- status: `{gate['grid_trend']['status']}`",
            f"- medium->fine CL relative change: `{gate['grid_trend'].get('cl_relative_change_medium_to_fine')}`",
            f"- medium->fine CD relative change: `{gate['grid_trend'].get('cd_relative_change_medium_to_fine')}`",
            f"- medium->fine Cm absolute change: `{gate['grid_trend'].get('cm_absolute_change_medium_to_fine')}`",
            "",
            "## Engineering Read",
            "",
            str(gate["engineering_trust_boundary"]),
            "",
            "Blocked claims:",
            "",
            *[f"- {claim}" for claim in summary["blocked_claims"]],
            "",
            "## Blockers",
            "",
            *([f"- `{blocker}`" for blocker in gate["blockers"]] or ["- none"]),
            "",
        ]
    )
    return "\n".join(lines)


def render_reviewer_prompt(summary: Mapping[str, Any]) -> str:
    output_dir = Path(str(summary["rungs"][0].get("case_dir", ""))).parents[1] if summary["rungs"] else DEFAULT_OUTPUT_DIR
    return "\n".join(
        [
            "Review WO-006I Baseline A main-wing CFD grid-convergence campaign.",
            "",
            f"Artifact directory: `{output_dir}`",
            "Check `grid_convergence_summary.json`, `mesh_ladder_table.csv`, per-rung `attempt_summary.json`, SU2 configs, mesh markers, and histories.",
            "Verify the same current-GO geometry source, marker/config match, mesh quality, CL/CD/Cm finiteness, force/residual stability, grid trend, and especially the setup gate.",
            "Reject any no-BL / missing-y+ / non-conformal BL-core result as CFD completion even if its force history is finite.",
            "",
        ]
    )


def _grid_trend(successful: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(successful) < 3:
        return {"status": "insufficient_successful_rungs"}
    coarse, medium, fine = successful[-3], successful[-2], successful[-1]
    coarse_coeffs = (coarse.get("su2") or {}).get("coefficients") or {}
    medium_coeffs = (medium.get("su2") or {}).get("coefficients") or {}
    fine_coeffs = (fine.get("su2") or {}).get("coefficients") or {}
    cl_cm = _relative_change(coarse_coeffs.get("cl"), medium_coeffs.get("cl"))
    cl_mf = _relative_change(medium_coeffs.get("cl"), fine_coeffs.get("cl"))
    cd_cm = _relative_change(coarse_coeffs.get("cd"), medium_coeffs.get("cd"))
    cd_mf = _relative_change(medium_coeffs.get("cd"), fine_coeffs.get("cd"))
    cm_cm = _absolute_change(coarse_coeffs.get("cm"), medium_coeffs.get("cm"))
    cm_mf = _absolute_change(medium_coeffs.get("cm"), fine_coeffs.get("cm"))
    stable = (
        cl_mf is not None
        and cl_mf <= COEFFICIENT_RELATIVE_TOL
        and cd_mf is not None
        and cd_mf <= COEFFICIENT_RELATIVE_TOL
        and cm_mf is not None
        and cm_mf <= CM_ABSOLUTE_TOL
    )
    return {
        "status": "stable_enough_for_low_confidence" if stable else "not_stable",
        "coarse_rung": coarse.get("rung_id"),
        "medium_rung": medium.get("rung_id"),
        "fine_rung": fine.get("rung_id"),
        "cl_relative_change_coarse_to_medium": cl_cm,
        "cl_relative_change_medium_to_fine": cl_mf,
        "cd_relative_change_coarse_to_medium": cd_cm,
        "cd_relative_change_medium_to_fine": cd_mf,
        "cm_absolute_change_coarse_to_medium": cm_cm,
        "cm_absolute_change_medium_to_fine": cm_mf,
        "tolerances": {
            "cl_cd_relative": COEFFICIENT_RELATIVE_TOL,
            "cm_absolute": CM_ABSOLUTE_TOL,
        },
    }


def _finite_completed_rungs(rungs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    finite = []
    for rung in rungs:
        if str(rung.get("status") or "") not in {"success", "completed"}:
            continue
        su2 = rung.get("su2") or {}
        mesh = rung.get("mesh") or {}
        coeffs = su2.get("coefficients") or {}
        if su2.get("run_status") != "completed":
            continue
        if mesh.get("marker_status") != "pass" or mesh.get("quality_status") != "pass":
            continue
        if not all(_is_finite(coeffs.get(name)) for name in ("cl", "cd", "cm")):
            continue
        finite.append(rung)
    return sorted(
        finite,
        key=lambda rung: int((rung.get("mesh") or {}).get("volume_element_count") or 0),
    )


def _trust_boundary(cfd_status: str) -> str:
    if cfd_status == "grid_convergence_ready":
        return (
            "Grid trend and wall-resolution gates pass inside the current setup. "
            "This is CFD V&V evidence for the setup, still not final aircraft sign-off."
        )
    if cfd_status == "low_confidence_cfd":
        return (
            "Same-physics CL/CD/Cm trend is stable enough to treat as low-confidence "
            "CFD evidence only when the setup gate allows that interpretation. It is "
            "not final Baseline A aero calibration."
        )
    if cfd_status == "route_smoke":
        return "Only route smoke exists. A single finite force history is not CFD completion."
    return (
        "Mesh ladder evidence is incomplete or unstable. Do not use these coefficients "
        "for engineering decisions beyond debugging mesh/SU2 wiring."
    )


def _force_stability_value_fails(payload: Mapping[str, Any]) -> bool:
    relative = _optional_float(payload.get("max_relative_spread"))
    cm_spread = _optional_float(payload.get("cm_absolute_spread"))
    if relative is not None and relative > FORCE_WINDOW_RELATIVE_TOL:
        return True
    if cm_spread is not None and cm_spread > CM_ABSOLUTE_TOL:
        return True
    return False


def _force_stability_window_fails(payload: Mapping[str, Any]) -> bool:
    observed = _optional_float(payload.get("window_rows"))
    return observed is None or observed < FORCE_STABILITY_WINDOW_ROWS


def _residual_stability_value_fails(payload: Mapping[str, Any]) -> bool:
    slope = _optional_float(payload.get("max_abs_slope_per_iter"))
    return slope is not None and slope > RESIDUAL_WINDOW_ABS_SLOPE_TOL


def _blocked_claims(cfd_status: str) -> list[str]:
    claims = [
        "CFD completion from no-BL or missing-y+ setup",
        "BL/y+ viscous drag calibration",
        "drag or power truth",
        "Baseline A reopen evidence",
        "RFQ/procurement truth",
        "final aircraft sign-off",
    ]
    if cfd_status != "grid_convergence_ready":
        claims.insert(0, "grid-converged engineering CFD")
    return claims


def load_direct_stageback_artifacts(
    paths: Sequence[Path] = DIRECT_STAGEBACK_PROBE_PATHS,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            artifact = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            artifacts.append(
                {
                    "path": str(path),
                    "status": "unreadable",
                    "error": str(exc),
                }
            )
            continue
        artifact["path"] = str(path)
        artifacts.append(artifact)
    return artifacts


def load_core_closure_artifacts(
    paths: Sequence[Path] = CORE_CLOSURE_PROBE_PATHS,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            artifact = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            artifacts.append(
                {
                    "path": str(path),
                    "status": "unreadable",
                    "error": str(exc),
                }
            )
            continue
        artifact["path"] = str(path)
        artifacts.append(artifact)
    return artifacts


def _stageback_topology_summary(
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    plc_failure_observed = False
    for artifact in artifacts:
        diagnostic_family = _stageback_artifact_diagnostic_family(artifact)
        if diagnostic_family == "stageback_plc_segment_facet_intersection":
            plc_failure_observed = True
        records.append(
            {
                "path": artifact.get("path"),
                "schema_version": artifact.get("schema_version"),
                "status": artifact.get("status"),
                "failure_code": artifact.get("failure_code"),
                "diagnostic_family": diagnostic_family,
            }
        )
    status = "blocked" if plc_failure_observed else ("not_evaluated" if not records else "pass")
    result: dict[str, Any] = {
        "status": status,
        "artifacts": records,
    }
    if plc_failure_observed:
        result.update(
            {
                "blocker": "direct_stageback_topology_plc_segment_facet",
                "recommended_repair": "receiver_sleeve_staged_transition_required",
                "engineering_read": (
                    "Direct no-BL-hole stageback is producing a Gmsh PLC segment/facet "
                    "intersection, so the BL/core transition topology is not solver-ready."
                ),
            }
        )
    return result


def _core_closure_topology_summary(
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    r12_core_mesh_ready = False
    r12_core_mesh_blocked = False
    r12_blocker = None
    r12_volume_element_count = None
    core_mesh_artifact_seen = False
    r11_surface_ready = False
    r11_mesh_pending = False
    r10_blocked = False
    wall_edge_gap_status = None
    full_shell_policy_status = None
    bad_edge_count = 0
    unexplained_bad_edge_count = 0
    physical_wall_edge_dependency_count = 0
    post_cap_status = None
    left_tip_star_record: dict[str, Any] | None = None
    left_tip_star_ready = False
    loop_cap_owner_pyramid_record: dict[str, Any] | None = None
    loop_cap_owner_ready = False
    handoff_residual_record: dict[str, Any] | None = None
    hybrid_split_artifact_seen = False
    hybrid_split_blocked = False
    hybrid_split_record: dict[str, Any] | None = None
    prism_split_artifact_seen = False
    prism_split_blocked = False
    prism_split_record: dict[str, Any] | None = None
    handoff_conformality_blocked = False
    handoff_conformality_record: dict[str, Any] | None = None
    for artifact in artifacts:
        left_tip_star = artifact.get("left_tip_star_tessellation") or {}
        if left_tip_star:
            remaining_after_star = (
                left_tip_star.get("remaining_r17_residuals_after_r19_r20") or {}
            )
            left_tip_star_ready = (
                left_tip_star.get("status") == "left_tip_star_tessellation_match"
                and int(left_tip_star.get("non_positive_star_tet_count") or 0) == 0
                and not remaining_after_star
            )
            left_tip_star_record = {
                "path": artifact.get("path"),
                "schema_version": artifact.get("schema_version"),
                "verdict": artifact.get("verdict"),
                "closure_status": left_tip_star.get("status"),
                "target_cell_count": left_tip_star.get("target_cell_count"),
                "target_triangle_count": left_tip_star.get("target_triangle_count"),
                "matched_target_triangle_count": left_tip_star.get(
                    "matched_target_triangle_count"
                ),
                "non_positive_star_tet_count": left_tip_star.get(
                    "non_positive_star_tet_count"
                ),
                "remaining_r17_residuals_after_r19_r20": remaining_after_star,
                "pending_blockers": artifact.get("blockers"),
            }
            records.append(left_tip_star_record)
            continue

        loop_cap_owner_pyramid = artifact.get("loop_cap_owner_pyramid") or {}
        if loop_cap_owner_pyramid:
            loop_cap_owner_ready = (
                loop_cap_owner_pyramid.get("status") == "loop_cap_owner_pyramids_match"
                and int(
                    loop_cap_owner_pyramid.get(
                        "non_positive_owner_pyramid_volume_count"
                    )
                    or 0
                )
                == 0
            )
            loop_cap_owner_pyramid_record = {
                "path": artifact.get("path"),
                "schema_version": artifact.get("schema_version"),
                "verdict": artifact.get("verdict"),
                "closure_status": loop_cap_owner_pyramid.get("status"),
                "owner_pyramid_cell_count": loop_cap_owner_pyramid.get(
                    "owner_pyramid_cell_count"
                ),
                "physical_wall_edge_receiver_face_count": (
                    loop_cap_owner_pyramid.get(
                        "physical_wall_edge_receiver_face_count"
                    )
                ),
                "matched_core_wall_loop_cap_triangle_count": (
                    loop_cap_owner_pyramid.get(
                        "matched_core_wall_loop_cap_triangle_count"
                    )
                ),
                "core_wall_loop_cap_triangle_count": loop_cap_owner_pyramid.get(
                    "core_wall_loop_cap_triangle_count"
                ),
                "non_positive_owner_pyramid_volume_count": (
                    loop_cap_owner_pyramid.get(
                        "non_positive_owner_pyramid_volume_count"
                    )
                ),
                "remaining_hybrid_residuals_by_marker": (
                    loop_cap_owner_pyramid.get("remaining_hybrid_residuals_by_marker")
                ),
                "pending_blockers": artifact.get("blockers"),
            }
            records.append(loop_cap_owner_pyramid_record)
            continue

        handoff_residuals = artifact.get("residuals") or {}
        if handoff_residuals:
            loop_cap_fans = handoff_residuals.get("loop_cap_fans") or {}
            incompatible_cells = handoff_residuals.get("incompatible_cells") or {}
            handoff_residual_record = {
                "path": artifact.get("path"),
                "schema_version": artifact.get("schema_version"),
                "verdict": artifact.get("verdict"),
                "closure_status": handoff_residuals.get("status"),
                "residual_triangle_count": handoff_residuals.get(
                    "residual_triangle_count"
                ),
                "unowned_residuals_by_marker": handoff_residuals.get(
                    "unowned_residuals_by_marker"
                ),
                "incompatible_owned_residuals_by_marker": handoff_residuals.get(
                    "incompatible_owned_residuals_by_marker"
                ),
                "loop_cap_fan_count": loop_cap_fans.get("fan_count"),
                "loop_cap_triangle_count": loop_cap_fans.get("triangle_count"),
                "incompatible_cell_count": incompatible_cells.get("count"),
                "incompatible_cells_by_role": incompatible_cells.get("by_role"),
                "recommended_next_repair": handoff_residuals.get(
                    "recommended_next_repair"
                ),
                "pending_blockers": artifact.get("blockers"),
            }
            records.append(handoff_residual_record)
            continue

        hybrid_split_compatibility = artifact.get("hybrid_split_compatibility") or {}
        if hybrid_split_compatibility:
            hybrid_split_artifact_seen = True
            merged_handoff_status = str(
                artifact.get("merged_handoff_status")
                or hybrid_split_compatibility.get("status")
                or artifact.get("verdict")
                or ""
            )
            hybrid_split_blocked = merged_handoff_status != "pass"
            hybrid_split_record = {
                "path": artifact.get("path"),
                "schema_version": artifact.get("schema_version"),
                "verdict": artifact.get("verdict"),
                "closure_status": merged_handoff_status,
                "candidate_cell_count": hybrid_split_compatibility.get(
                    "candidate_cell_count"
                ),
                "candidate_core_facing_cell_count": hybrid_split_compatibility.get(
                    "candidate_core_facing_cell_count"
                ),
                "matched_core_triangle_count": hybrid_split_compatibility.get(
                    "matched_core_triangle_count"
                ),
                "core_triangle_count": hybrid_split_compatibility.get("core_triangle_count"),
                "candidate_owned_core_triangle_count": hybrid_split_compatibility.get(
                    "candidate_owned_core_triangle_count"
                ),
                "unowned_core_triangles_by_marker": hybrid_split_compatibility.get(
                    "unowned_core_triangles_by_marker"
                ),
                "incompatible_owned_core_triangles_by_marker": (
                    hybrid_split_compatibility.get(
                        "incompatible_owned_core_triangles_by_marker"
                    )
                ),
                "best_pattern_counts": hybrid_split_compatibility.get(
                    "best_pattern_counts"
                ),
                "pending_blockers": artifact.get("blockers"),
            }
            records.append(hybrid_split_record)
            continue

        prism_split_compatibility = artifact.get("prism_split_compatibility") or {}
        if prism_split_compatibility:
            if hybrid_split_artifact_seen:
                records.append(
                    {
                        "path": artifact.get("path"),
                        "schema_version": artifact.get("schema_version"),
                        "verdict": artifact.get("verdict"),
                        "closure_status": (
                            artifact.get("merged_handoff_status")
                            or prism_split_compatibility.get("status")
                        ),
                        "status": "superseded_by_hybrid_split_probe",
                        "matched_core_triangle_count": prism_split_compatibility.get(
                            "matched_core_triangle_count"
                        ),
                        "core_triangle_count": prism_split_compatibility.get(
                            "core_triangle_count"
                        ),
                        "unmatched_core_triangles_by_marker": (
                            prism_split_compatibility.get(
                                "unmatched_core_triangles_by_marker"
                            )
                        ),
                    }
                )
                continue
            if prism_split_artifact_seen:
                records.append(
                    {
                        "path": artifact.get("path"),
                        "schema_version": artifact.get("schema_version"),
                        "verdict": artifact.get("verdict"),
                        "closure_status": (
                            artifact.get("merged_handoff_status")
                            or prism_split_compatibility.get("status")
                        ),
                        "status": "superseded_by_newer_prism_split_probe",
                        "matched_core_triangle_count": prism_split_compatibility.get(
                            "matched_core_triangle_count"
                        ),
                        "core_triangle_count": prism_split_compatibility.get(
                            "core_triangle_count"
                        ),
                        "unmatched_core_triangles_by_marker": (
                            prism_split_compatibility.get(
                                "unmatched_core_triangles_by_marker"
                            )
                        ),
                    }
                )
                continue
            prism_split_artifact_seen = True
            merged_handoff_status = str(
                artifact.get("merged_handoff_status")
                or prism_split_compatibility.get("status")
                or artifact.get("verdict")
                or ""
            )
            prism_split_blocked = merged_handoff_status != "pass"
            prism_split_record = {
                "path": artifact.get("path"),
                "schema_version": artifact.get("schema_version"),
                "verdict": artifact.get("verdict"),
                "closure_status": merged_handoff_status,
                "candidate_cell_count": prism_split_compatibility.get(
                    "candidate_cell_count"
                ),
                "candidate_core_facing_cell_count": prism_split_compatibility.get(
                    "candidate_core_facing_cell_count"
                ),
                "matched_core_triangle_count": prism_split_compatibility.get(
                    "matched_core_triangle_count"
                ),
                "core_triangle_count": prism_split_compatibility.get("core_triangle_count"),
                "unmatched_core_triangles_by_marker": prism_split_compatibility.get(
                    "unmatched_core_triangles_by_marker"
                ),
                "best_pattern_counts": prism_split_compatibility.get(
                    "best_pattern_counts"
                ),
                "pending_blockers": artifact.get("blockers"),
            }
            records.append(prism_split_record)
            continue

        conformality_audit = artifact.get("conformality_audit") or {}
        if conformality_audit:
            merged_handoff_status = str(
                artifact.get("merged_handoff_status")
                or conformality_audit.get("status")
                or artifact.get("verdict")
                or ""
            )
            handoff_conformality_record = {
                "path": artifact.get("path"),
                "schema_version": artifact.get("schema_version"),
                "verdict": artifact.get("verdict"),
                "closure_status": merged_handoff_status,
                "status": (
                    "superseded_by_hybrid_split_probe"
                    if hybrid_split_artifact_seen
                    else "superseded_by_prism_split_probe"
                    if prism_split_artifact_seen
                    else "active"
                ),
                "polygon_matched_core_face_count": conformality_audit.get(
                    "polygon_matched_core_face_count"
                ),
                "triangle_matched_core_face_count": conformality_audit.get(
                    "triangle_matched_core_face_count"
                ),
                "core_triangle_count": conformality_audit.get("core_triangle_count"),
                "polygon_matched_but_triangle_unmatched_count": conformality_audit.get(
                    "polygon_matched_but_triangle_unmatched_count"
                ),
                "missing_polygon_core_faces_by_marker": conformality_audit.get(
                    "missing_polygon_core_faces_by_marker"
                ),
                "unmatched_core_triangles_by_marker": conformality_audit.get(
                    "unmatched_core_triangles_by_marker"
                ),
                "pending_blockers": artifact.get("blockers"),
            }
            if not hybrid_split_artifact_seen and not prism_split_artifact_seen:
                handoff_conformality_blocked = merged_handoff_status != "pass"
            records.append(handoff_conformality_record)
            continue

        loop_cap_core_mesh = artifact.get("loop_cap_core_mesh") or {}
        loop_closure = artifact.get("loop_closure") or {}
        closure = artifact.get("core_closure") or {}
        if loop_cap_core_mesh:
            mesh_status = str(loop_cap_core_mesh.get("status") or artifact.get("verdict") or "")
            hard_blockers = list(loop_cap_core_mesh.get("hard_blockers") or [])
            if not core_mesh_artifact_seen:
                core_mesh_artifact_seen = True
                r12_volume_element_count = loop_cap_core_mesh.get("volume_element_count")
                r12_core_mesh_ready = (
                    mesh_status == "core_mesh_probe_pass_merged_handoff_pending"
                    and not hard_blockers
                )
                r12_core_mesh_blocked = not r12_core_mesh_ready
                if r12_core_mesh_blocked:
                    r12_blocker = (
                        "near_wall_core_mesh_geometry_blocked"
                        if "core_inner_surface_geometric_duplicate_nonmanifold"
                        in hard_blockers
                        else "near_wall_core_mesh_probe_blocked"
                    )
            records.append(
                {
                    "path": artifact.get("path"),
                    "schema_version": artifact.get("schema_version"),
                    "verdict": artifact.get("verdict"),
                    "closure_status": loop_cap_core_mesh.get("status"),
                    "core_facing_status": loop_cap_core_mesh.get("loop_cap_status"),
                    "post_cap_status": loop_cap_core_mesh.get("loop_cap_status"),
                    "core_mesh_quality_status": loop_cap_core_mesh.get(
                        "core_mesh_quality_status"
                    ),
                    "core_mesh_marker_status": loop_cap_core_mesh.get(
                        "core_mesh_marker_status"
                    ),
                    "node_count": loop_cap_core_mesh.get("node_count"),
                    "volume_element_count": r12_volume_element_count,
                    "inner_marker_counts": loop_cap_core_mesh.get("inner_marker_counts"),
                    "pending_blockers": loop_cap_core_mesh.get("pending_blockers"),
                    "hard_blockers": hard_blockers,
                }
            )
            continue

        if loop_closure:
            pre_cap = loop_closure.get("pre_cap_topology") or {}
            post_cap = loop_closure.get("post_cap_topology") or {}
            loop_status = str(loop_closure.get("status") or artifact.get("verdict") or "")
            post_cap_status = str(post_cap.get("status") or "")
            r11_surface_ready = (
                loop_status == "core_facing_loop_cap_surface_ready_core_mesh_pending"
                and post_cap_status == "watertight"
            )
            r11_mesh_pending = r11_surface_ready and bool(loop_closure.get("blockers"))
            bad_edge_count += int(pre_cap.get("bad_edge_count") or 0)
            records.append(
                {
                    "path": artifact.get("path"),
                    "schema_version": artifact.get("schema_version"),
                    "verdict": artifact.get("verdict"),
                    "closure_status": loop_closure.get("status"),
                    "core_facing_status": pre_cap.get("status"),
                    "bad_edge_count": pre_cap.get("bad_edge_count"),
                    "post_cap_status": post_cap.get("status"),
                    "post_cap_bad_edge_count": post_cap.get("bad_edge_count"),
                    "loop_count": loop_closure.get("loop_count"),
                    "cap_face_count": loop_closure.get("cap_face_count"),
                    "pending_blockers": loop_closure.get("blockers"),
                }
            )
            continue

        core_topology = closure.get("core_facing_topology") or {}
        gap_audit = closure.get("core_wall_edge_gap_audit") or {}
        shell_policy = closure.get("full_shell_core_interface_policy") or {}
        closure_status = str(closure.get("status") or artifact.get("verdict") or "")
        artifact_blocked = (
            "blocked" in closure_status
            or core_topology.get("status") == "not_watertight"
            or shell_policy.get("status") == "forbidden"
        )
        r10_blocked = r10_blocked or artifact_blocked
        if gap_audit.get("status") is not None:
            wall_edge_gap_status = str(gap_audit.get("status"))
        if shell_policy.get("status") is not None:
            full_shell_policy_status = str(shell_policy.get("status"))
        bad_edge_count += int(core_topology.get("bad_edge_count") or 0)
        unexplained_bad_edge_count += int(gap_audit.get("unexplained_bad_edge_count") or 0)
        physical_wall_edge_dependency_count += int(
            gap_audit.get("physical_wall_edge_dependency_count") or 0
        )
        records.append(
            {
                "path": artifact.get("path"),
                "schema_version": artifact.get("schema_version"),
                "verdict": artifact.get("verdict"),
                "closure_status": closure.get("status"),
                "core_facing_status": core_topology.get("status"),
                "bad_edge_count": core_topology.get("bad_edge_count"),
                "wall_edge_gap_status": gap_audit.get("status"),
                "unexplained_bad_edge_count": gap_audit.get("unexplained_bad_edge_count"),
                "full_shell_policy_status": shell_policy.get("status"),
                "physical_roles_present": shell_policy.get("physical_roles_present"),
            }
        )

    handoff_repair_basis_ready = (
        left_tip_star_ready
        and loop_cap_owner_ready
        and hybrid_split_artifact_seen
        and hybrid_split_blocked
    )
    if handoff_repair_basis_ready:
        status = "handoff_repair_basis_ready_mixed_mesh_pending"
    elif hybrid_split_blocked:
        status = "handoff_hybrid_split_blocked"
    elif prism_split_blocked:
        status = "handoff_prism_split_blocked"
    elif handoff_conformality_blocked:
        status = "handoff_conformality_blocked"
    elif r12_core_mesh_ready:
        status = "core_mesh_ready_handoff_pending"
    elif r12_core_mesh_blocked:
        status = "core_mesh_blocked"
    elif r11_mesh_pending:
        status = "surface_ready_core_mesh_pending"
    elif r11_surface_ready:
        status = "pass"
    elif r10_blocked:
        status = "blocked"
    else:
        status = "not_evaluated" if not records else "pass"
    result: dict[str, Any] = {
        "status": status,
        "artifacts": records,
        "bad_edge_count": bad_edge_count,
        "post_cap_status": post_cap_status,
        "volume_element_count": r12_volume_element_count,
        "wall_edge_gap_status": wall_edge_gap_status,
        "physical_wall_edge_dependency_count": physical_wall_edge_dependency_count,
        "unexplained_bad_edge_count": unexplained_bad_edge_count,
        "full_shell_policy_status": full_shell_policy_status,
    }
    if status == "handoff_hybrid_split_blocked":
        recommended_repair = "materialize_remaining_loop_cap_and_wake_tip_interface_ownership"
        if handoff_residual_record and handoff_residual_record.get(
            "recommended_next_repair"
        ):
            recommended_repair = str(
                handoff_residual_record["recommended_next_repair"]
            )
        if (
            loop_cap_owner_pyramid_record
            and loop_cap_owner_pyramid_record.get("closure_status")
            == "loop_cap_owner_pyramids_match"
        ):
            recommended_repair = (
                "repair_left_tip_receiver_shared_tessellation_then_write_"
                "loop_cap_owner_pyramid_mixed_mesh"
            )
        result.update(
            {
                "blocker": "near_wall_hybrid_tet_prism_handoff_not_compatible",
                "hybrid_split_compatibility": hybrid_split_record,
                "handoff_residual_localization": handoff_residual_record,
                "loop_cap_owner_pyramid": loop_cap_owner_pyramid_record,
                "recommended_repair": recommended_repair,
                "engineering_read": (
                    "The latest hybrid tet/prism split probe shows most of the "
                    "R13 core interface can now be reproduced by local mixed-cell "
                    "decomposition, but remaining loop-cap and small wake/tip "
                    "interface triangles still lack ownership or compatible "
                    "tessellation. Do not run medium/fine SU2 until those final "
                    "handoff gaps are materialized and y+ is postprocessed."
                ),
            }
        )
    elif status == "handoff_repair_basis_ready_mixed_mesh_pending":
        result.update(
            {
                "blocker": "near_wall_merged_mesh_handoff_missing",
                "hybrid_split_compatibility": hybrid_split_record,
                "handoff_residual_localization": handoff_residual_record,
                "loop_cap_owner_pyramid": loop_cap_owner_pyramid_record,
                "left_tip_star_tessellation": left_tip_star_record,
                "recommended_repair": (
                    "write_marker_quality_gated_mixed_bl_core_su2_handoff_and_yplus_probe"
                ),
                "engineering_read": (
                    "The loop-cap owner pyramids and left-tip star tessellation "
                    "provide a positive-volume local repair basis for the last "
                    "known R17 handoff residuals. This is still not a CFD-ready "
                    "setup until a marker/quality-gated mixed BL+core SU2 mesh is "
                    "written and near-wall y+ is postprocessed."
                ),
            }
        )
    elif status == "handoff_prism_split_blocked":
        result.update(
            {
                "blocker": "near_wall_prism_split_handoff_not_compatible",
                "prism_split_compatibility": prism_split_record,
                "recommended_repair": (
                    "make_near_wall_and_core_share_interface_tessellation_before_prismization"
                ),
                "engineering_read": (
                    "The latest prism-split compatibility probe shows that simply "
                    "splitting each near-wall hexa into two prisms cannot reproduce "
                    "the active R13 core interface triangles. Medium/fine SU2 must "
                    "wait for a shared interface tessellation or boundary-driven "
                    "near-wall remesh, not just a local diagonal choice."
                ),
            }
        )
    elif status == "handoff_conformality_blocked":
        result.update(
            {
                "blocker": "near_wall_mixed_handoff_interface_not_conformal",
                "handoff_conformality": handoff_conformality_record,
                "recommended_repair": (
                    "make_near_wall_and_core_share_the_same_interface_tessellation"
                ),
                "engineering_read": (
                    "The latest mixed-handoff audit shows the R13 core interface "
                    "is geometrically close to the near-wall boundary, but the "
                    "active triangulated core boundary is not conformal with the "
                    "near-wall volume interface. Do not write or run a mixed SU2 "
                    "mesh until the shared interface tessellation is repaired."
                ),
            }
        )
    elif status == "core_mesh_ready_handoff_pending":
        result.update(
            {
                "blocker": "near_wall_merged_mesh_handoff_missing",
                "recommended_repair": "write_marker_quality_gated_mixed_bl_core_su2_handoff_and_yplus_probe",
                "engineering_read": (
                    "The latest loop-cap artifact closes the core-facing surface and "
                    "a core/farfield mesh probe exists with preserved markers. The "
                    "setup still needs a merged mixed BL+core SU2 handoff, y+, and "
                    "solver ladder before CFD."
                ),
            }
        )
    elif status == "core_mesh_blocked":
        result.update(
            {
                "blocker": r12_blocker or "near_wall_core_mesh_probe_blocked",
                "recommended_repair": "repair_loop_cap_tip_wake_geometric_self_intersection",
                "engineering_read": (
                    "The latest loop-cap core mesh probe supersedes older R10 "
                    "wall-edge blockers. It shows the core-facing surface is not "
                    "PLC-valid for Gmsh because the tip/wake loop-cap seam still "
                    "has geometric duplicate/non-manifold behavior."
                ),
            }
        )
    elif status == "surface_ready_core_mesh_pending":
        result.update(
            {
                "blocker": "near_wall_core_mesh_probe_missing",
                "recommended_repair": "generate_marker_quality_gated_core_farfield_mesh_from_loop_cap_surface",
                "engineering_read": (
                    "The latest loop-cap artifact closes the core-facing surface "
                    "topology. The setup still needs a marker/quality-gated core "
                    "mesh, merged SU2 readability, y+, and solver ladder before CFD."
                ),
            }
        )
    elif status == "blocked":
        result.update(
            {
                "blocker": "near_wall_core_interface_closure_blocked",
                "recommended_repair": "materialize_true_core_facing_closure",
                "engineering_read": (
                    "The latest near-wall closure artifact shows the repaired full shell "
                    "is watertight, but the core-facing subset is not. Medium/fine SU2 "
                    "must wait until the wall-edge ownership gap is materialized without "
                    "borrowing physical wall faces as core interface."
                ),
            }
        )
    return result


def _stageback_artifact_diagnostic_family(artifact: Mapping[str, Any]) -> str | None:
    diagnostic = artifact.get("diagnostic")
    if isinstance(diagnostic, Mapping):
        family = diagnostic.get("diagnostic_family")
        if family:
            return str(family)
        raw_error = str(diagnostic.get("raw_error") or "")
        if _raw_stageback_plc_segment_facet(raw_error):
            return "stageback_plc_segment_facet_intersection"

    error = str(artifact.get("error") or "")
    marker = "diagnostic="
    if marker in error:
        diagnostic_text = error.split(marker, 1)[1].strip()
        try:
            parsed = json.loads(diagnostic_text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Mapping):
            family = parsed.get("diagnostic_family")
            raw_error = str(parsed.get("raw_error") or "")
            if _raw_stageback_plc_segment_facet(raw_error):
                return "stageback_plc_segment_facet_intersection"
            if family:
                return str(family)
    if _raw_stageback_plc_segment_facet(error):
        return "stageback_plc_segment_facet_intersection"
    return None


def _raw_stageback_plc_segment_facet(raw_error: str) -> bool:
    text = raw_error.lower()
    return "plc error" in text and "segment" in text and "facet" in text


def _rung_markdown_row(rung: Mapping[str, Any]) -> str:
    mesh = rung.get("mesh") or {}
    su2 = rung.get("su2") or {}
    coeffs = su2.get("coefficients") or {}
    force = su2.get("force_stability") or {}
    residual = su2.get("residual_stability") or {}
    return (
        f"| `{rung.get('rung_id')}` | `{rung.get('status')}` | {rung.get('wing_h')} | "
        f"{mesh.get('node_count')} | {mesh.get('volume_element_count')} | "
        f"`{mesh.get('marker_status')}` | `{mesh.get('quality_status')}` | "
        f"{su2.get('iterations')} | {coeffs.get('cl')} | {coeffs.get('cd')} | "
        f"{coeffs.get('cm')} | `{force.get('status')}` | `{residual.get('status')}` |"
    )


def _mesh_ladder_row(rung: Mapping[str, Any]) -> dict[str, Any]:
    mesh = rung.get("mesh") or {}
    quality = mesh.get("quality") or {}
    return {
        "rung_id": rung.get("rung_id"),
        "status": rung.get("status"),
        "role": rung.get("role"),
        "wing_h": rung.get("wing_h"),
        "target_cells": rung.get("target_cells"),
        "node_count": mesh.get("node_count"),
        "volume_element_count": mesh.get("volume_element_count"),
        "marker_status": mesh.get("marker_status"),
        "quality_status": mesh.get("quality_status"),
        "min_gamma": quality.get("min_gamma"),
        "min_sicn": quality.get("min_sicn"),
        "min_sige": quality.get("min_sige"),
        "non_positive_volume_count": quality.get("non_positive_volume_count"),
        "elapsed_seconds": rung.get("elapsed_seconds"),
        "peak_sampled_rss_kb": rung.get("peak_sampled_rss_kb"),
        "failure_code": rung.get("failure_code"),
        "error": rung.get("error"),
    }


def _su2_iteration_row(rung: Mapping[str, Any]) -> dict[str, Any]:
    su2 = rung.get("su2") or {}
    coeffs = su2.get("coefficients") or {}
    force = su2.get("force_stability") or {}
    residual = su2.get("residual_stability") or {}
    return {
        "rung_id": rung.get("rung_id"),
        "run_status": su2.get("run_status"),
        "iterations": su2.get("iterations"),
        "cl": coeffs.get("cl"),
        "cd": coeffs.get("cd"),
        "cm": coeffs.get("cm"),
        "force_stability_status": force.get("status"),
        "force_max_relative_spread": force.get("max_relative_spread"),
        "force_cm_absolute_spread": force.get("cm_absolute_spread"),
        "residual_stability_status": residual.get("status"),
        "residual_max_abs_slope_per_iter": residual.get("max_abs_slope_per_iter"),
        "history_path": su2.get("history_path"),
        "config_path": su2.get("config_path"),
    }


def _read_history_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {str(key).strip().strip('"'): value for key, value in row.items()}
        for row in rows
    ]


def _parse_rung_specs(values: Sequence[str]) -> tuple[RungSpec, ...]:
    specs: list[RungSpec] = []
    for value in values:
        parts = value.split(":")
        if len(parts) not in {3, 4, 5}:
            raise ValueError(
                "rung specs must look like rung_id:wing_h:target_cells[:role[:run_solver]]"
            )
        rung_id = parts[0]
        wing_h = float(parts[1])
        target_cells = int(float(parts[2]))
        role = parts[3] if len(parts) >= 4 else rung_id
        run_solver = True if len(parts) < 5 else parts[4].lower() not in {"0", "false", "no"}
        specs.append(RungSpec(rung_id, wing_h, target_cells, role, run_solver))
    return tuple(specs)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _process_tree_rss_kb(pid: int | None) -> int | None:
    if pid is None:
        return None
    pids = [pid, *_child_pids(pid)]
    total = 0
    observed = False
    for item in pids:
        try:
            output = subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(item)],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            continue
        if not output:
            continue
        try:
            total += int(output.splitlines()[-1].strip())
            observed = True
        except ValueError:
            continue
    return total if observed else None


def _child_pids(pid: int) -> list[int]:
    try:
        output = subprocess.check_output(
            ["pgrep", "-P", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    children = []
    for line in output.splitlines():
        try:
            children.append(int(line.strip()))
        except ValueError:
            continue
    return children


def _terminate_process_tree(pid: int | None) -> None:
    if pid is None:
        return
    for child in _child_pids(pid):
        _terminate_process_tree(child)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        time.sleep(1.0)


def _peak_rss(samples: Sequence[Mapping[str, Any]]) -> int | None:
    values = [int(sample["rss_kb"]) for sample in samples if sample.get("rss_kb") is not None]
    return max(values) if values else None


def _relative_change(a: Any, b: Any) -> float | None:
    av = _optional_float(a)
    bv = _optional_float(b)
    if av is None or bv is None or not math.isfinite(av) or not math.isfinite(bv):
        return None
    return abs(bv - av) / max(abs(bv), 1.0e-12)


def _absolute_change(a: Any, b: Any) -> float | None:
    av = _optional_float(a)
    bv = _optional_float(b)
    if av is None or bv is None or not math.isfinite(av) or not math.isfinite(bv):
        return None
    return abs(bv - av)


def _first_finite(*values: Any) -> float | None:
    for value in values:
        converted = _optional_float(value)
        if converted is not None and math.isfinite(converted):
            return converted
    return None


def _is_finite(value: Any) -> bool:
    converted = _optional_float(value)
    return converted is not None and math.isfinite(converted)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument(
        "--rung",
        dest="rungs",
        action="append",
        help="rung_id:wing_h:target_cells[:role[:run_solver]]. Repeat for custom ladder.",
    )
    parser.add_argument("--iterations", type=int, default=180)
    parser.add_argument("--solver-command", type=str, default=SU2_COMMAND)
    parser.add_argument("--solver-threads", type=int, default=4)
    parser.add_argument("--solver-timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--rung-timeout-seconds", type=float, default=5400.0)
    parser.add_argument("--stop-after-first-hard-failure", action="store_true")
    parser.add_argument(
        "--allow-no-bl-diagnostic",
        action="store_true",
        help="Run the known no-BL route as diagnostic evidence only; it cannot complete the CFD goal.",
    )
    parser.add_argument(
        "--summarize-existing",
        action="store_true",
        help="Regenerate campaign summary/report from existing per-rung attempt summaries.",
    )
    args = parser.parse_args(argv)

    rung_specs = DEFAULT_RUNG_SPECS if not args.rungs else _parse_rung_specs(args.rungs)
    summary = (
        summarize_existing_campaign(output_dir=args.output_dir, rung_specs=rung_specs)
        if args.summarize_existing
        else run_campaign(
            output_dir=args.output_dir,
            rung_specs=rung_specs,
            clean=not args.no_clean,
            iterations=args.iterations,
            solver_command=args.solver_command,
            solver_threads=args.solver_threads,
            solver_timeout_seconds=args.solver_timeout_seconds,
            rung_timeout_seconds=args.rung_timeout_seconds,
            stop_after_first_hard_failure=args.stop_after_first_hard_failure,
            allow_no_bl_diagnostic=args.allow_no_bl_diagnostic,
        )
    )
    gate = summary["grid_convergence_gate"]
    print(
        json.dumps(
            {
                "GOAL_STATUS": gate["goal_status"],
                "CFD_STATUS": gate["cfd_status"],
                "output_dir": str(args.output_dir),
                "successful_rungs": gate["successful_rungs"],
                "blockers": gate["blockers"],
                "setup_gate": gate.get("setup_gate_status"),
            },
            indent=2,
        )
    )
    return 0 if gate["goal_status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
