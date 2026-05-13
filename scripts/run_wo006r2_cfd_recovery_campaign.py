#!/usr/bin/env python3
"""Run the WO-006R2 GO/Baseline A CFD recovery campaign.

This campaign is intentionally a route-recovery controller, not a new geometry
design tool. It reuses the WO-006R1 current-GO section-table adapter and then
tries to replay the old serious mesh-native BL/SU2 path on the current fixed
GO/Baseline A wing.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from dataclasses import dataclass
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.convergence import evaluate_iterative_gate  # noqa: E402
from hpa_meshing.mesh_native.cfd_advisory import (  # noqa: E402
    first_cell_height_for_yplus,
    geometric_boundary_layer_total_thickness,
    reynolds_number,
)
from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    _cfd_evidence_gate,
    _coefficient_sanity_gate,
    build_wing_feature_refinement_boxes,
    write_faceted_boundary_layer_su2_case,
    write_faceted_volume_su2_case,
)
from hpa_meshing.mesh_native.su2_structured import (  # noqa: E402
    _parse_smoke_history,
    audit_su2_case_markers,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    SurfaceMesh,
    build_farfield_box_surface,
)
from run_wo006r1_go_baseline_a_cfd_bridge import (  # noqa: E402
    CANDIDATE_ID,
    DEFAULT_OUTPUT_DIR as WO006R1_OUTPUT_DIR,
    DESIGN_GROSS_MASS_KG,
    PIPELINE_FULL_SPAN_M,
    PIPELINE_HALF_SPAN_M,
    CurrentGoGeometry,
    _authority_reference_payload,
    _patch_runtime_reference_origin,
    _read_csv_dicts,
    build_current_go_wing_surface,
    load_current_go_geometry,
)


DEFAULT_OUTPUT_DIR = WO006R1_OUTPUT_DIR.parent / "wo006r2_cfd_recovery_campaign"
AVL_PARITY_GEOMETRY_DIR = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "avl_parity"
    / CANDIDATE_ID
)
SU2_COMMAND = "/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD"
RHO_KGPM3 = 1.225
MU_PA_S = 1.7894e-5
VELOCITY_MPS = 6.5
BL_FIRST_HEIGHT_M = 5.0e-5
BL_GROWTH_RATIO = 1.24
BL_LAYERS = 24
PLC_POINT_RE = re.compile(
    r"PLC Error:.*?point\s*\("
    r"(?P<x>[-+0-9.eE]+)\s*,\s*"
    r"(?P<y>[-+0-9.eE]+)\s*,\s*"
    r"(?P<z>[-+0-9.eE]+)\s*\)"
)


@dataclass(frozen=True)
class AttemptSpec:
    attempt_id: str
    route: str
    mesh_kind: str
    points_per_side: int
    spanwise_subdivisions: int
    base_mesh_size: float
    wing_mesh_size: float
    farfield_mesh_size: float
    wing_refinement_radius: float
    feature_refinement_size: float | None
    solver: str
    turbulence_model: str
    transition_model: str | None
    wall_profile: str
    conv_num_method_flow: str
    cfl_number: float
    linear_solver_iter: int
    max_iterations: int
    run_solver: bool
    purpose: str


def load_campaign_geometry(
    geometry_dir: Path | str = AVL_PARITY_GEOMETRY_DIR,
    *,
    points_per_side: int = 32,
    spanwise_subdivisions: int = 2,
) -> CurrentGoGeometry:
    return load_current_go_geometry(
        geometry_dir,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )


def build_yplus_nearwall_summary(geometry: CurrentGoGeometry) -> dict[str, Any]:
    rows = _read_csv_dicts(geometry.section_table_path)
    root_chord = float(rows[0]["chord_m"])
    tip_chord = float(rows[-1]["chord_m"])
    cref = float(geometry.reference.cref)
    reynolds = {
        "root": reynolds_number(
            density_kgpm3=RHO_KGPM3,
            velocity_mps=VELOCITY_MPS,
            length_m=root_chord,
            dynamic_viscosity_pas=MU_PA_S,
        ),
        "mean_aerodynamic_chord": reynolds_number(
            density_kgpm3=RHO_KGPM3,
            velocity_mps=VELOCITY_MPS,
            length_m=cref,
            dynamic_viscosity_pas=MU_PA_S,
        ),
        "tip": reynolds_number(
            density_kgpm3=RHO_KGPM3,
            velocity_mps=VELOCITY_MPS,
            length_m=tip_chord,
            dynamic_viscosity_pas=MU_PA_S,
        ),
    }
    yplus1 = first_cell_height_for_yplus(
        target_yplus=1.0,
        density_kgpm3=RHO_KGPM3,
        velocity_mps=VELOCITY_MPS,
        dynamic_viscosity_pas=MU_PA_S,
        reference_length_m=cref,
    )
    yplus5 = first_cell_height_for_yplus(
        target_yplus=5.0,
        density_kgpm3=RHO_KGPM3,
        velocity_mps=VELOCITY_MPS,
        dynamic_viscosity_pas=MU_PA_S,
        reference_length_m=cref,
    )
    total_thickness = geometric_boundary_layer_total_thickness(
        first_layer_height_m=BL_FIRST_HEIGHT_M,
        layers=BL_LAYERS,
        growth_ratio=BL_GROWTH_RATIO,
    )
    return {
        "schema_version": "wo006r2_yplus_nearwall_summary.v1",
        "flow_condition": {
            "velocity_mps": VELOCITY_MPS,
            "density_kgpm3": RHO_KGPM3,
            "dynamic_viscosity_pa_s": MU_PA_S,
        },
        "current_go_chord_refs_m": {
            "root": root_chord,
            "mean_aerodynamic_chord": cref,
            "tip": tip_chord,
        },
        "current_go_reynolds_by_chord": reynolds,
        "first_cell_height_estimates_m": {
            "target_yplus_1": yplus1,
            "target_yplus_5": yplus5,
        },
        "current_go_first_layer_yplus_estimate": {
            "first_layer_height_m": BL_FIRST_HEIGHT_M,
            "yplus_for_5e-5m": BL_FIRST_HEIGHT_M / float(yplus1["first_cell_height_m"]),
            "estimate_model": yplus1["cf_model"],
        },
        "boundary_layer_policy": {
            "recommended_first_layer_height_m": BL_FIRST_HEIGHT_M,
            "recommended_layers": BL_LAYERS,
            "recommended_growth_ratio": BL_GROWTH_RATIO,
            "recommended_total_thickness_m": total_thickness,
            "wall_resolved_target": "prefer_yplus_0p5_to_1p5_and_under_5_without_wall_model",
        },
        "engineering_read": (
            "The first-layer estimate keeps the old 5e-5 m BL policy in the "
            "right wall-resolved order for the current GO mean chord; this is "
            "an estimate, not postprocessed surface y+ from SU2."
        ),
    }


def build_route_decision_matrix_rows() -> list[dict[str, str]]:
    return [
        {
            "route_id": "old_mesh_native_wing_h_0p20_bl",
            "source": "mesh_native_cfd_line_freeze + mesh_native_hxt_thread_profile",
            "old_volume_elements": "1125409",
            "bl_or_nearwall": "24_layer_prism_bl",
            "solver_evidence": "10_iteration_su2_readability_smoke",
            "current_go_use": "template_for_attempt_01",
            "decision": "reuse_as_primary_template",
            "reason": "strongest old BL mesh with pass marker and quality gate",
        },
        {
            "route_id": "old_mesh_native_wing_h_0p15_bl",
            "source": "mesh_native_hxt_thread_profile",
            "old_volume_elements": "1515251",
            "bl_or_nearwall": "24_layer_prism_bl_with_two_nonpositive_quality_items",
            "solver_evidence": "not_run",
            "current_go_use": "do_not_use_until_local_bl_defect_is_fixed",
            "decision": "hold_as_failure_boundary",
            "reason": "finer mesh shows likely terminal BL topology failure",
        },
        {
            "route_id": "old_no_bl_iter1000",
            "source": "mesh_native_blackcat_vsp_su2_iter1000",
            "old_volume_elements": "717901",
            "bl_or_nearwall": "none",
            "solver_evidence": "999_final_row_inc_navier_stokes_cd_positive",
            "current_go_use": "fallback_solver_reference_only",
            "decision": "reuse_only_if_bl_route_blocked",
            "reason": "good solver stability evidence but not drag credible",
        },
        {
            "route_id": "wo006r1_current_go_coarse_no_bl",
            "source": "wo006r1_go_cfd_bridge",
            "old_volume_elements": "2902",
            "bl_or_nearwall": "none",
            "solver_evidence": "3_iteration_inc_euler_negative_cd",
            "current_go_use": "geometry_bridge_and_marker_smoke",
            "decision": "bridge_only_not_target",
            "reason": "proves adapter, not CFD evidence",
        },
        {
            "route_id": "old_step_brep_esp_route",
            "source": "wo006 first attempt + package-native route reports",
            "old_volume_elements": "0_or_timeout_on_current_go",
            "bl_or_nearwall": "not_reached",
            "solver_evidence": "not_reached",
            "current_go_use": "reference_blocker_only",
            "decision": "reject_as_primary",
            "reason": "current GO VSP3/STEP path blocks before usable mesh handoff",
        },
    ]


def build_force_reference_audit(geometry: CurrentGoGeometry) -> dict[str, Any]:
    return {
        "schema_version": "wo006r2_force_reference_audit.v1",
        "current_authority": {
            "design_gross_mass_kg": DESIGN_GROSS_MASS_KG,
            "full_span_m": PIPELINE_FULL_SPAN_M,
            "half_span_m": PIPELINE_HALF_SPAN_M,
            "sref_m2": geometry.reference.sref_full,
            "cref_m": geometry.reference.cref,
            "bref_m": geometry.reference.bref_full,
            "moment_origin_m": list(geometry.moment_origin_m),
            "geometry_source": str(geometry.section_table_path),
        },
        "blocked_legacy_values": {
            "legacy_screening_mass_status": "blocked_not_current_truth",
            "legacy_local_splice_half_span_status": "blocked_not_current_truth",
            "use_status": "do_not_promote_to_current_truth",
        },
        "force_marker_contract": {
            "wall_marker": "wing_wall",
            "farfield_marker": "farfield",
            "monitoring_marker": "wing_wall",
            "plotting_marker": "wing_wall",
            "symmetry_marker": None,
            "symmetry_status": "not_used_full_wing_current_mesh_native_adapter",
        },
        "coefficient_acceptance": {
            "negative_cd_status": "reject",
            "minimum_iteration_gate": 1000,
            "requires_mesh_quality_gate_pass": True,
            "requires_marker_audit_pass": True,
            "requires_iterative_gate_pass": True,
            "comparison_to_avl_vspaero": "only_after_cfd_case_is_interpretable",
        },
    }


def build_old_evidence_rows() -> list[dict[str, str]]:
    return [
        {
            "evidence_id": "old_bl_wing_h_0p20_hxt",
            "artifact": (
                "hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/"
                "mesh_native_hxt_thread_profile.v1.md"
            ),
            "commit": "310c7db4",
            "mesh_nodes": "531054",
            "volume_elements": "1125409",
            "bl_prisms": "992352",
            "core_tets": "133057",
            "solver_status": "10_iteration_su2_smoke_pass",
            "why_reusable": "best old marker-owned BL/HXT route",
            "why_not_final": "low BL p01 quality and no long converged run",
        },
        {
            "evidence_id": "old_bl_wing_h_0p15_hxt_failed_quality",
            "artifact": (
                "hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/"
                "mesh_native_hxt_thread_profile.v1.md"
            ),
            "commit": "310c7db4",
            "mesh_nodes": "695550",
            "volume_elements": "1515251",
            "bl_prisms": "1281312",
            "core_tets": "233939",
            "solver_status": "not_run_quality_fail",
            "why_reusable": "failure boundary for terminal BL quality",
            "why_not_final": "two non-positive BL minSICN/minSIGE items",
        },
        {
            "evidence_id": "old_no_bl_iter1000",
            "artifact": (
                "hpa_meshing_package/docs/reports/mesh_native_blackcat_vsp_su2_iter1000/"
                "mesh_native_blackcat_vsp_su2_iter1000.v1.md"
            ),
            "commit": "205f5382",
            "mesh_nodes": "258378",
            "volume_elements": "717901",
            "bl_prisms": "0",
            "core_tets": "717901",
            "solver_status": "inc_navier_stokes_999_final_row_cd_positive",
            "why_reusable": "solver/reference sign sanity fallback",
            "why_not_final": "no prism BL or wall-normal yplus evidence",
        },
        {
            "evidence_id": "wo006r1_current_go_bridge",
            "artifact": (
                "output/baseline_A_team_release/wo006_su2_baseline_validation/"
                "wo006r1_go_cfd_bridge/wo006r1_go_cfd_bridge_report.md"
            ),
            "commit": "8daea0bd",
            "mesh_nodes": "1081",
            "volume_elements": "2902",
            "bl_prisms": "0",
            "core_tets": "2902",
            "solver_status": "3_iteration_inc_euler_readability_negative_cd",
            "why_reusable": "current GO geometry adapter and marker bridge",
            "why_not_final": "coarse no-BL smoke only",
        },
    ]


def default_attempt_specs(max_iterations: int, run_solver: bool) -> list[AttemptSpec]:
    return [
        AttemptSpec(
            attempt_id="attempt_00_avl_parity_coarse_bridge_control",
            route="current_go_avl_parity_coarse_no_bl_bridge_control",
            mesh_kind="no_bl",
            points_per_side=8,
            spanwise_subdivisions=3,
            base_mesh_size=8.0,
            wing_mesh_size=2.0,
            farfield_mesh_size=12.0,
            wing_refinement_radius=12.0,
            feature_refinement_size=None,
            solver="INC_EULER",
            turbulence_model="NONE",
            transition_model=None,
            wall_profile="euler_slip",
            conv_num_method_flow="FDS",
            cfl_number=1.0,
            linear_solver_iter=10,
            max_iterations=3,
            run_solver=False,
            purpose="Prove the no-touch avl_parity adapter can still make a coarse bridge mesh.",
        ),
        AttemptSpec(
            attempt_id="attempt_01_replay_old_mesh_native_bl_template",
            route="current_go_faceted_hxt_bl_old_wing_h_0p20_template",
            mesh_kind="bl",
            points_per_side=32,
            spanwise_subdivisions=2,
            base_mesh_size=4.0,
            wing_mesh_size=0.20,
            farfield_mesh_size=8.0,
            wing_refinement_radius=6.0,
            feature_refinement_size=0.32,
            solver="INC_NAVIER_STOKES",
            turbulence_model="NONE",
            transition_model=None,
            wall_profile="adiabatic_no_slip",
            conv_num_method_flow="JST",
            cfl_number=0.05,
            linear_solver_iter=20,
            max_iterations=max_iterations,
            run_solver=run_solver,
            purpose="Replay old 1.125M-cell BL route on fixed current GO geometry.",
        ),
        AttemptSpec(
            attempt_id="attempt_02_current_go_bl_coarser_quality_probe",
            route="current_go_faceted_hxt_bl_wing_h_0p25_quality_probe",
            mesh_kind="bl",
            points_per_side=32,
            spanwise_subdivisions=2,
            base_mesh_size=4.0,
            wing_mesh_size=0.25,
            farfield_mesh_size=8.0,
            wing_refinement_radius=6.0,
            feature_refinement_size=0.40,
            solver="INC_NAVIER_STOKES",
            turbulence_model="NONE",
            transition_model=None,
            wall_profile="adiabatic_no_slip",
            conv_num_method_flow="JST",
            cfl_number=0.05,
            linear_solver_iter=20,
            max_iterations=max_iterations,
            run_solver=False,
            purpose="If the old density fails, isolate whether coarser BL quality survives.",
        ),
        AttemptSpec(
            attempt_id="attempt_03_current_go_high_mesh_no_bl_solver_control",
            route="current_go_faceted_hxt_no_bl_high_mesh_solver_control",
            mesh_kind="no_bl",
            points_per_side=32,
            spanwise_subdivisions=2,
            base_mesh_size=4.0,
            wing_mesh_size=0.25,
            farfield_mesh_size=8.0,
            wing_refinement_radius=6.0,
            feature_refinement_size=0.40,
            solver="INC_NAVIER_STOKES",
            turbulence_model="NONE",
            transition_model=None,
            wall_profile="adiabatic_no_slip",
            conv_num_method_flow="JST",
            cfl_number=0.05,
            linear_solver_iter=20,
            max_iterations=max_iterations,
            run_solver=run_solver,
            purpose="Solver/reference control only if BL route cannot produce interpretable CFD.",
        ),
    ]


def run_campaign(
    *,
    output_dir: Path,
    max_iterations: int,
    run_solver: bool,
    mesh_timeout_seconds: float,
    solver_timeout_seconds: float,
    clean: bool,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    geometry = load_campaign_geometry()
    _write_static_artifacts(output_dir, geometry)

    attempts = []
    driver_log_path = output_dir / "campaign_driver_terminal.log"
    with _redirect_process_output(driver_log_path):
        for spec in default_attempt_specs(max_iterations=max_iterations, run_solver=run_solver):
            result = _run_attempt_with_timeout(
                spec=spec,
                output_dir=output_dir,
                mesh_timeout_seconds=mesh_timeout_seconds,
                solver_timeout_seconds=solver_timeout_seconds,
            )
            attempts.append(result)
            if _attempt_has_interpretable_cfd(result):
                break
            if (
                _attempt_has_bl_mesh_ready(result)
                and result.get("solver", {}).get("run_status") == "timeout"
            ):
                break

    attempts = _attach_driver_log_context(attempts, driver_log_path)
    for attempt in attempts:
        attempt_id = str(attempt.get("attempt_id"))
        summary_path = output_dir / attempt_id / "attempt_summary.json"
        if summary_path.exists():
            _write_json(summary_path, attempt)
    blockers = []
    for attempt in attempts:
        blockers.extend(_blockers_from_attempt(attempt))

    verdict = _final_verdict(attempts)
    final_payload = {
        "schema_version": "wo006r2_final_engineering_verdict.v1",
        "verdict": verdict,
        "baseline_a_reopen_status": (
            "not_evaluated"
            if verdict != "wo006r2_cfd_evidence_gate_ready"
            else "not_evaluated_pending_aero_delta_review"
        ),
        "current_geometry_changed": False,
        "attempt_count": len(attempts),
        "best_attempt": _best_attempt_summary(attempts),
        "coefficient_interpretable": any(_attempt_has_interpretable_cfd(item) for item in attempts),
        "engineering_caveats": [
            "A passing code path is not final aircraft sign-off.",
            "No old Black Cat coefficient is promoted to current Baseline A truth.",
            "Negative CD or no-BL drag is rejected as calibration evidence.",
            "Surface y+ here is estimated unless a solver surface postprocess is present.",
        ],
    }
    _write_json(output_dir / "final_engineering_verdict.json", final_payload)
    _write_attempt_csvs(output_dir, attempts, blockers)
    _write_report(output_dir, geometry, attempts, final_payload, blockers)
    _write_next_goal(output_dir, final_payload, blockers)
    return final_payload


def _write_static_artifacts(output_dir: Path, geometry: CurrentGoGeometry) -> None:
    _write_csv(output_dir / "old_evidence_map.csv", build_old_evidence_rows())
    _write_commit_history_evidence(output_dir / "commit_history_evidence.md")
    (output_dir / "manual_research_notes.md").write_text(
        _manual_research_notes_text(),
        encoding="utf-8",
    )
    _write_csv(output_dir / "route_decision_matrix.csv", build_route_decision_matrix_rows())
    _write_csv(
        output_dir / "current_go_geometry_reconciliation.csv",
        _current_go_geometry_reconciliation_rows(geometry),
    )
    _write_json(output_dir / "yplus_nearwall_summary.json", build_yplus_nearwall_summary(geometry))
    _write_json(output_dir / "force_reference_audit.json", build_force_reference_audit(geometry))


def _run_attempt_with_timeout(
    *,
    spec: AttemptSpec,
    output_dir: Path,
    mesh_timeout_seconds: float,
    solver_timeout_seconds: float,
) -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue: mp.Queue = context.Queue()
    case_dir = output_dir / spec.attempt_id
    process = context.Process(
        target=_attempt_worker_entry,
        kwargs={
            "queue": queue,
            "spec_payload": spec.__dict__,
            "case_dir": str(case_dir),
            "solver_timeout_seconds": solver_timeout_seconds,
        },
    )
    start = time.time()
    process.start()
    process.join(mesh_timeout_seconds + solver_timeout_seconds + 30.0)
    if process.is_alive():
        process.terminate()
        process.join(5.0)
        return {
            "attempt_id": spec.attempt_id,
            "route": spec.route,
            "status": "timeout",
            "failure_code": "attempt_timeout",
            "elapsed_seconds": time.time() - start,
            "mesh_timeout_seconds": mesh_timeout_seconds,
            "solver_timeout_seconds": solver_timeout_seconds,
        }
    if queue.empty():
        return {
            "attempt_id": spec.attempt_id,
            "route": spec.route,
            "status": "failed",
            "failure_code": "attempt_worker_no_payload",
            "elapsed_seconds": time.time() - start,
            "process_exitcode": process.exitcode,
        }
    payload = queue.get()
    payload["elapsed_seconds"] = time.time() - start
    _write_json(case_dir / "attempt_summary.json", payload)
    return payload


def _attempt_worker_entry(
    queue: Any,
    *,
    spec_payload: Mapping[str, Any],
    case_dir: str,
    solver_timeout_seconds: float,
) -> None:
    try:
        spec = AttemptSpec(**dict(spec_payload))
        case_path = Path(case_dir)
        case_path.mkdir(parents=True, exist_ok=True)
        geometry = load_campaign_geometry(
            points_per_side=spec.points_per_side,
            spanwise_subdivisions=spec.spanwise_subdivisions,
        )
        wing = build_current_go_wing_surface(geometry)
        farfield = build_farfield_box_surface(
            wing,
            upstream_factor=2.0,
            downstream_factor=4.0,
            lateral_factor=2.0,
            vertical_factor=2.0,
        )
        attempt_log_path = case_path / "attempt_runtime.log"
        with _redirect_process_output(attempt_log_path):
            report = _materialize_case(spec, geometry, wing, farfield, case_path)
            solver_payload = {"run_status": "not_run", "reason": "disabled_or_mesh_not_eligible"}
            mesh_gate = report.get("mesh_report", {}).get("mesh_quality_gate", {}).get("status")
            marker_gate = report.get("marker_audit", {}).get("status")
            if spec.run_solver and mesh_gate == "pass" and marker_gate == "pass":
                solver_payload = _run_solver_for_case(
                    case_path=case_path,
                    spec=spec,
                    timeout_seconds=solver_timeout_seconds,
                )
        payload = {
            "attempt_id": spec.attempt_id,
            "route": spec.route,
            "purpose": spec.purpose,
            "status": "completed",
            "mesh_kind": spec.mesh_kind,
            "attempt_log_path": str(attempt_log_path),
            "attempt_log_tail": _tail_text(attempt_log_path),
            "geometry": _geometry_attempt_payload(geometry),
            "runtime_policy": _attempt_runtime_payload(spec),
            "case_report": report,
            "mesh": _mesh_attempt_payload(report),
            "solver": solver_payload,
            "engineering_read": _attempt_engineering_read(report, solver_payload),
        }
        queue.put(payload)
    except Exception as exc:  # pragma: no cover - real Gmsh/SU2 failures are payload evidence.
        attempt_id = str(spec_payload.get("attempt_id", "unknown"))
        route = str(spec_payload.get("route", "unknown"))
        mesh_kind = str(spec_payload.get("mesh_kind", "unknown"))
        log_path = Path(case_dir) / "attempt_runtime.log"
        log_tail = _tail_text(log_path)
        queue.put(
            {
                "attempt_id": attempt_id,
                "route": route,
                "purpose": str(spec_payload.get("purpose", "")),
                "status": "failed",
                "mesh_kind": mesh_kind,
                "attempt_log_path": str(log_path),
                "attempt_log_tail": log_tail,
                "plc_intersection_context": _plc_intersection_context(log_tail),
                "failure_code": exc.__class__.__name__,
                "error": str(exc),
                "runtime_policy": dict(spec_payload),
            }
        )


def _materialize_case(
    spec: AttemptSpec,
    geometry: CurrentGoGeometry,
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    case_path: Path,
) -> dict[str, Any]:
    refinement_boxes = (
        None
        if spec.feature_refinement_size is None
        else build_wing_feature_refinement_boxes(wing, mesh_size=spec.feature_refinement_size)
    )
    common = {
        "ref_area": geometry.reference.sref_full,
        "ref_length": geometry.reference.cref,
        "mesh_size": spec.base_mesh_size,
        "wing_mesh_size": spec.wing_mesh_size,
        "farfield_mesh_size": spec.farfield_mesh_size,
        "wing_refinement_radius": spec.wing_refinement_radius,
        "refinement_boxes": refinement_boxes,
        "velocity_mps": VELOCITY_MPS,
        "alpha_deg": 0.0,
        "max_iterations": spec.max_iterations,
        "solver": spec.solver,
        "turbulence_model": spec.turbulence_model,
        "transition_model": spec.transition_model,
        "wall_profile": spec.wall_profile,
        "conv_num_method_flow": spec.conv_num_method_flow,
        "cfl_number": spec.cfl_number,
        "linear_solver_iter": spec.linear_solver_iter,
        "freestream_turbulence_intensity": 0.01,
        "freestream_turb2lam_visc_ratio": 3.0,
        "conv_cauchy_elems": 100,
        "conv_cauchy_eps": "1e-4",
        "output_files": ("RESTART_ASCII", "SURFACE_CSV"),
        "gmsh_threads": 4,
        "mesh_algorithm3d": 10,
    }
    if spec.mesh_kind == "bl":
        report = write_faceted_boundary_layer_su2_case(
            wing,
            farfield,
            case_path,
            boundary_layer_first_height=BL_FIRST_HEIGHT_M,
            boundary_layer_growth_ratio=BL_GROWTH_RATIO,
            boundary_layer_layers=BL_LAYERS,
            **common,
        )
    elif spec.mesh_kind == "no_bl":
        report = write_faceted_volume_su2_case(wing, farfield, case_path, **common)
    else:
        raise ValueError(f"Unsupported mesh_kind: {spec.mesh_kind}")

    runtime_cfg_path = Path(report["runtime_cfg_path"])
    _patch_runtime_reference_origin(runtime_cfg_path, geometry.moment_origin_m)
    marker_audit = audit_su2_case_markers(report["mesh_path"], runtime_cfg_path)
    updated = {
        **report,
        "marker_audit": marker_audit,
        "current_authority_reference": _authority_reference_payload(geometry),
    }
    Path(report["report_path"]).write_text(json.dumps(updated, indent=2), encoding="utf-8")
    return updated


def _run_solver_for_case(
    *,
    case_path: Path,
    spec: AttemptSpec,
    timeout_seconds: float,
) -> dict[str, Any]:
    solver_path = _resolve_solver_command(SU2_COMMAND)
    solver_log = case_path / "solver.log"
    history_path = case_path / "history.csv"
    command = [solver_path, "-t", "4", "su2_runtime.cfg"]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "4"
    try:
        with solver_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                cwd=case_path,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=timeout_seconds,
                env=env,
            )
    except subprocess.TimeoutExpired:
        history = _parse_smoke_history(history_path) if history_path.exists() else None
        return {
            "run_status": "timeout",
            "failure_code": "solver_timeout",
            "solver_log_path": str(solver_log),
            "history_path": str(history_path) if history_path.exists() else None,
            "history": history,
            "coefficient_sanity_gate": _coefficient_sanity_gate(history),
            "cfd_evidence_gate": _cfd_evidence_gate(
                max_iterations=spec.max_iterations,
                min_iterations=1000,
                iterative_gate_status=None,
                history=history,
            ),
        }
    history = _parse_smoke_history(history_path) if history_path.exists() else None
    iterative_gate = None
    iterative_gate_status = None
    if history_path.exists():
        iterative_gate = evaluate_iterative_gate(history_path).model_dump(mode="json")
        iterative_gate_status = str(iterative_gate.get("status"))
    coefficient_gate = _coefficient_sanity_gate(history)
    cfd_gate = _cfd_evidence_gate(
        max_iterations=spec.max_iterations,
        min_iterations=1000,
        iterative_gate_status=iterative_gate_status,
        history=history,
    )
    run_status = "completed" if completed.returncode == 0 and history is not None else "failed"
    return {
        "run_status": run_status,
        "failure_code": None if run_status == "completed" else "solver_failed_or_history_missing",
        "returncode": completed.returncode,
        "solver_command": command,
        "solver_log_path": str(solver_log),
        "history_path": str(history_path) if history_path.exists() else None,
        "history": history,
        "iterative_gate": iterative_gate,
        "iterative_gate_status": iterative_gate_status,
        "coefficient_sanity_gate": coefficient_gate,
        "cfd_evidence_gate": cfd_gate,
        "aero_coefficients_interpretable": (
            run_status == "completed"
            and iterative_gate_status == "pass"
            and coefficient_gate["status"] == "pass"
            and cfd_gate["status"] == "pass"
        ),
    }


def _resolve_solver_command(command: str) -> str:
    path = Path(command)
    if path.is_file():
        return str(path)
    resolved = shutil.which(command)
    if resolved:
        return resolved
    raise FileNotFoundError(f"Could not find SU2 solver command: {command}")


@contextmanager
def _redirect_process_output(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    sys.stderr.flush()
    old_stdout = os.dup(1)
    old_stderr = os.dup(2)
    try:
        with path.open("ab") as handle:
            os.dup2(handle.fileno(), 1)
            os.dup2(handle.fileno(), 2)
            yield
            sys.stdout.flush()
            sys.stderr.flush()
    finally:
        os.dup2(old_stdout, 1)
        os.dup2(old_stderr, 2)
        os.close(old_stdout)
        os.close(old_stderr)


def _tail_text(path: Path, max_lines: int = 20) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def extract_plc_points(text: str) -> list[dict[str, float]]:
    points = []
    for match in PLC_POINT_RE.finditer(text):
        points.append(
            {
                "x_m": float(match.group("x")),
                "y_m": float(match.group("y")),
                "z_m": float(match.group("z")),
            }
        )
    return points


def _plc_intersection_context(
    text: str,
    *,
    geometry_dir: Path = AVL_PARITY_GEOMETRY_DIR,
) -> list[dict[str, Any]]:
    points = extract_plc_points(text)
    if not points:
        return []
    rows = _read_csv_dicts(geometry_dir / "section_table.csv")
    sections = sorted(rows, key=lambda item: float(item["y_m"]))
    context = []
    for point in points:
        y_abs = abs(point["y_m"])
        nearest = min(sections, key=lambda item: abs(float(item["y_m"]) - y_abs))
        lower = sections[0]
        upper = sections[-1]
        for left, right in zip(sections, sections[1:]):
            if float(left["y_m"]) <= y_abs <= float(right["y_m"]):
                lower = left
                upper = right
                break
        context.append(
            {
                **point,
                "abs_y_m": y_abs,
                "nearest_section_index": int(nearest["section_index"]),
                "nearest_section_y_m": float(nearest["y_m"]),
                "nearest_airfoil_id": nearest.get("airfoil_id"),
                "bracket_lower_section_index": int(lower["section_index"]),
                "bracket_lower_y_m": float(lower["y_m"]),
                "bracket_lower_airfoil_id": lower.get("airfoil_id"),
                "bracket_upper_section_index": int(upper["section_index"]),
                "bracket_upper_y_m": float(upper["y_m"]),
                "bracket_upper_airfoil_id": upper.get("airfoil_id"),
                "bracket_crosses_airfoil_family": lower.get("airfoil_id") != upper.get(
                    "airfoil_id"
                ),
            }
        )
    return context


def _mesh_attempt_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    mesh_report = report.get("mesh_report", {})
    bl = mesh_report.get("boundary_layer") or {}
    return {
        "status": mesh_report.get("status"),
        "mesh_path": report.get("mesh_path"),
        "runtime_cfg_path": report.get("runtime_cfg_path"),
        "volume_element_count": mesh_report.get("volume_element_count"),
        "node_count": mesh_report.get("node_count"),
        "mesh_quality_gate": mesh_report.get("mesh_quality_gate"),
        "marker_audit": report.get("marker_audit"),
        "boundary_layer": {
            "present": bool(bl),
            "volume_element_type_counts": bl.get("volume_element_type_counts"),
            "quality_metrics": bl.get("quality_metrics"),
            "layers": bl.get("layers"),
            "first_height_m": bl.get("first_height_m"),
            "total_thickness_m": bl.get("total_thickness_m"),
        },
    }


def _geometry_attempt_payload(geometry: CurrentGoGeometry) -> dict[str, Any]:
    return {
        "case_name": geometry.case_name,
        "section_table_path": str(geometry.section_table_path),
        "geometry_manifest_path": str(geometry.geometry_manifest_path),
        "full_span_m": geometry.full_span_m,
        "half_span_m": geometry.half_span_m,
        "sref_m2": geometry.reference.sref_full,
        "cref_m": geometry.reference.cref,
        "bref_m": geometry.reference.bref_full,
        "moment_origin_m": list(geometry.moment_origin_m),
    }


def _attempt_runtime_payload(spec: AttemptSpec) -> dict[str, Any]:
    return {
        "points_per_side": spec.points_per_side,
        "spanwise_subdivisions": spec.spanwise_subdivisions,
        "base_mesh_size": spec.base_mesh_size,
        "wing_mesh_size": spec.wing_mesh_size,
        "farfield_mesh_size": spec.farfield_mesh_size,
        "feature_refinement_size": spec.feature_refinement_size,
        "solver": spec.solver,
        "turbulence_model": spec.turbulence_model,
        "wall_profile": spec.wall_profile,
        "max_iterations": spec.max_iterations,
        "run_solver": spec.run_solver,
    }


def _attempt_engineering_read(
    report: Mapping[str, Any],
    solver_payload: Mapping[str, Any],
) -> dict[str, Any]:
    mesh = _mesh_attempt_payload(report)
    mesh_gate = (mesh.get("mesh_quality_gate") or {}).get("status")
    marker_gate = (mesh.get("marker_audit") or {}).get("status")
    coeff_gate = (solver_payload.get("coefficient_sanity_gate") or {}).get("status")
    return {
        "mesh_quality": mesh_gate,
        "marker_ownership": marker_gate,
        "solver_status": solver_payload.get("run_status"),
        "coefficient_sanity": coeff_gate,
        "aero_coefficients_interpretable": solver_payload.get(
            "aero_coefficients_interpretable",
            False,
        ),
    }


def _attempt_has_interpretable_cfd(attempt: Mapping[str, Any]) -> bool:
    return bool(attempt.get("solver", {}).get("aero_coefficients_interpretable"))


def _attempt_has_bl_mesh_ready(attempt: Mapping[str, Any]) -> bool:
    mesh = attempt.get("mesh", {})
    return (
        bool(mesh.get("boundary_layer", {}).get("present"))
        and (mesh.get("mesh_quality_gate") or {}).get("status") == "pass"
        and (mesh.get("marker_audit") or {}).get("status") == "pass"
    )


def _final_verdict(attempts: Sequence[Mapping[str, Any]]) -> str:
    if any(_attempt_has_interpretable_cfd(attempt) for attempt in attempts):
        return "wo006r2_cfd_evidence_gate_ready"
    solver_attempts = [item for item in attempts if item.get("solver", {}).get("run_status")]
    if any(
        (item.get("solver", {}).get("coefficient_sanity_gate") or {}).get("status") == "fail"
        for item in solver_attempts
    ):
        return "wo006r2_solver_force_reference_blocker_isolated"
    if any(_attempt_has_bl_mesh_ready(attempt) for attempt in attempts):
        return "wo006r2_nearwall_bl_route_ready"
    has_failed_bl = any(
        item.get("mesh_kind") == "bl"
        and item.get("status") in {"failed", "timeout"}
        for item in attempts
    )
    has_failed_serious_no_bl = any(
        item.get("mesh_kind") == "no_bl"
        and item.get("status") in {"failed", "timeout"}
        and str(item.get("attempt_id")) != "attempt_00_avl_parity_coarse_bridge_control"
        for item in attempts
    )
    if has_failed_bl and has_failed_serious_no_bl:
        return "wo006r2_current_geometry_adapter_blocker_isolated"
    if has_failed_bl:
        return "wo006r2_bl_topology_blocker_isolated"
    if any(
        int((item.get("mesh") or {}).get("volume_element_count") or 0) >= 500_000
        for item in attempts
    ):
        return "wo006r2_high_mesh_current_go_route_ready"
    if attempts:
        return "wo006r2_current_geometry_adapter_blocker_isolated"
    return "wo006r2_campaign_incomplete_needs_more_runtime"


def _best_attempt_summary(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not attempts:
        return None
    sorted_attempts = sorted(
        attempts,
        key=lambda item: int((item.get("mesh") or {}).get("volume_element_count") or 0),
        reverse=True,
    )
    best = sorted_attempts[0]
    return {
        "attempt_id": best.get("attempt_id"),
        "route": best.get("route"),
        "mesh_kind": best.get("mesh_kind"),
        "volume_element_count": (best.get("mesh") or {}).get("volume_element_count"),
        "mesh_quality_gate": ((best.get("mesh") or {}).get("mesh_quality_gate") or {}).get(
            "status"
        ),
        "solver_status": (best.get("solver") or {}).get("run_status"),
    }


def _blockers_from_attempt(attempt: Mapping[str, Any]) -> list[dict[str, str]]:
    if attempt.get("status") != "completed":
        evidence_text = str(
            attempt.get("attempt_log_tail")
            or attempt.get("error")
            or attempt.get("status")
        )
        plc_context = (
            attempt.get("plc_intersection_context")
            or attempt.get("campaign_driver_plc_intersection_context")
            or _plc_intersection_context(evidence_text)
        )
        campaign_driver_tail = str(attempt.get("campaign_driver_log_tail") or "")
        next_fix = "inspect_attempt_summary_and_route_specific_logs"
        if plc_context:
            next_fix = (
                "localize_current_go_surface_panel_topology_near_plc_station_bracket_"
                "without_changing_external_shape"
            )
        return [
            {
                "stage": str(attempt.get("attempt_id")),
                "status": "blocked",
                "blocker": str(attempt.get("failure_code") or "attempt_failed"),
                "evidence": json.dumps(
                    {
                        "tail": evidence_text,
                        "campaign_driver_tail": campaign_driver_tail,
                        "plc_intersection_context": plc_context,
                    },
                    sort_keys=True,
                ),
                "next_fix": next_fix,
            }
        ]
    blockers = []
    mesh = attempt.get("mesh") or {}
    if (mesh.get("mesh_quality_gate") or {}).get("status") != "pass":
        blockers.append(
            {
                "stage": str(attempt.get("attempt_id")),
                "status": "blocked",
                "blocker": "mesh_quality_gate_not_passed",
                "evidence": json.dumps(mesh.get("mesh_quality_gate"), sort_keys=True),
                "next_fix": "localize_bl_or_tet_quality_hotspot_before_solver",
            }
        )
    solver = attempt.get("solver") or {}
    if solver.get("run_status") in {"failed", "timeout"}:
        blockers.append(
            {
                "stage": str(attempt.get("attempt_id")),
                "status": "blocked",
                "blocker": str(solver.get("failure_code") or solver.get("run_status")),
                "evidence": str(solver.get("solver_log_path") or solver.get("history_path")),
                "next_fix": "inspect_solver_log_and_history_tail",
            }
        )
    if (solver.get("coefficient_sanity_gate") or {}).get("status") == "fail":
        blockers.append(
            {
                "stage": str(attempt.get("attempt_id")),
                "status": "blocked",
                "blocker": "coefficient_sanity_failed",
                "evidence": json.dumps(solver.get("coefficient_sanity_gate"), sort_keys=True),
                "next_fix": "audit_force_markers_reference_axes_and_viscous_wall_setup",
            }
        )
    return blockers


def _attach_driver_log_context(
    attempts: Sequence[Mapping[str, Any]],
    driver_log_path: Path,
) -> list[dict[str, Any]]:
    driver_log_tail = _tail_text(driver_log_path, max_lines=80)
    driver_context = _plc_intersection_context(driver_log_tail)
    enriched = []
    context_cursor = 0
    for attempt in attempts:
        payload = dict(attempt)
        if attempt.get("status") == "failed" and not attempt.get("plc_intersection_context"):
            if context_cursor < len(driver_context):
                payload["campaign_driver_plc_intersection_context"] = [
                    driver_context[context_cursor]
                ]
                context_cursor += 1
            elif driver_context:
                payload["campaign_driver_plc_intersection_context"] = driver_context
            if driver_log_tail:
                payload["campaign_driver_log_tail"] = driver_log_tail
                payload["campaign_driver_log_path"] = str(driver_log_path)
        enriched.append(payload)
    return enriched


def _write_attempt_csvs(
    output_dir: Path,
    attempts: Sequence[Mapping[str, Any]],
    blockers: Sequence[Mapping[str, str]],
) -> None:
    mesh_rows = []
    solver_rows = []
    for attempt in attempts:
        mesh = attempt.get("mesh") or {}
        solver = attempt.get("solver") or {}
        mesh_rows.append(
            {
                "attempt_id": attempt.get("attempt_id"),
                "route": attempt.get("route"),
                "mesh_kind": attempt.get("mesh_kind"),
                "status": attempt.get("status"),
                "purpose": attempt.get("purpose"),
                "volume_element_count": mesh.get("volume_element_count"),
                "node_count": mesh.get("node_count"),
                "bl_present": mesh.get("boundary_layer", {}).get("present"),
                "bl_layers": mesh.get("boundary_layer", {}).get("layers"),
                "mesh_quality_gate": (mesh.get("mesh_quality_gate") or {}).get("status"),
                "marker_audit": (mesh.get("marker_audit") or {}).get("status"),
                "elapsed_seconds": f"{float(attempt.get('elapsed_seconds') or 0.0):.3f}",
                "attempt_log_path": attempt.get("attempt_log_path"),
            }
        )
        history = solver.get("history") or {}
        coeff_gate = solver.get("coefficient_sanity_gate") or {}
        solver_rows.append(
            {
                "attempt_id": attempt.get("attempt_id"),
                "run_status": solver.get("run_status"),
                "failure_code": solver.get("failure_code"),
                "iterations_configured": attempt.get("runtime_policy", {}).get(
                    "max_iterations"
                ),
                "final_iteration": history.get("final_iteration"),
                "final_cl": history.get("final_cl"),
                "final_cd": history.get("final_cd"),
                "coefficient_sanity": coeff_gate.get("status"),
                "cfd_evidence_gate": (solver.get("cfd_evidence_gate") or {}).get("status"),
                "iterative_gate": solver.get("iterative_gate_status"),
                "history_path": solver.get("history_path"),
            }
        )
    _write_csv(output_dir / "mesh_attempts_summary.csv", mesh_rows)
    _write_csv(output_dir / "solver_attempts_summary.csv", solver_rows)
    _write_csv(output_dir / "blocker_register.csv", blockers)


def _current_go_geometry_reconciliation_rows(
    geometry: CurrentGoGeometry,
) -> list[dict[str, str]]:
    return [
        {
            "item": "design_gross_mass",
            "value": f"{geometry.design_gross_mass_kg:.6f}",
            "unit": "kg",
            "source": "user_authority",
            "classification": "current_authority",
            "use_in_wo006r2": "use",
        },
        {
            "item": "full_span",
            "value": f"{geometry.full_span_m:.6f}",
            "unit": "m",
            "source": str(geometry.section_table_path),
            "classification": "current_pipeline_truth",
            "use_in_wo006r2": "use",
        },
        {
            "item": "half_span",
            "value": f"{geometry.half_span_m:.6f}",
            "unit": "m",
            "source": str(geometry.section_table_path),
            "classification": "current_pipeline_truth",
            "use_in_wo006r2": "use",
        },
        {
            "item": "sref",
            "value": f"{geometry.reference.sref_full:.9f}",
            "unit": "m^2",
            "source": str(geometry.geometry_manifest_path),
            "classification": "current_pipeline_truth",
            "use_in_wo006r2": "use",
        },
        {
            "item": "cref",
            "value": f"{geometry.reference.cref:.9f}",
            "unit": "m",
            "source": str(geometry.geometry_manifest_path),
            "classification": "current_pipeline_truth",
            "use_in_wo006r2": "use",
        },
        {
            "item": "bref",
            "value": f"{geometry.reference.bref_full:.9f}",
            "unit": "m",
            "source": str(geometry.geometry_manifest_path),
            "classification": "current_pipeline_truth",
            "use_in_wo006r2": "use",
        },
        {
            "item": "legacy_screening_mass",
            "value": "blocked_not_current_truth",
            "unit": "",
            "source": "legacy_screening_aggregate",
            "classification": "legacy_or_experiment",
            "use_in_wo006r2": "blocked",
        },
        {
            "item": "legacy_local_splice_half_span",
            "value": "blocked_not_current_truth",
            "unit": "",
            "source": "local_splice_screening",
            "classification": "legacy_or_experiment",
            "use_in_wo006r2": "blocked",
        },
    ]


def _manual_research_notes_text() -> str:
    return """# WO-006R2 Manual Research Notes

## Official / Primary Sources Checked

- SU2 Physical Definition: https://su2code.github.io/docs_v7/Physical-Definition/
  - Supports incompressible initialization with `INC_DENSITY_INIT`,
    `INC_VELOCITY_INIT`, `INC_TEMPERATURE_INIT`, and farfield state ownership.
- SU2 Theory: https://su2code.github.io/docs_v7/Theory/
  - Separates `INC_EULER`, viscous solvers, RANS, and wall-function expectations.
  - Wall-resolved runs without wall functions need fine near-wall mesh; docs state
    `y+ < 5` when no wall model is active.
- SU2 Markers and Boundary Conditions:
  https://su2code.github.io/docs_v7/Markers-and-BC/
  - Solid viscous walls should be no-slip heatflux walls, not `MARKER_EULER`.
- SU2 Convective Schemes: https://su2code.github.io/docs_v7/Convective-Schemes/
  - Incompressible solver supports central and FDS low-speed schemes.
- SU2 Custom Output: https://su2code.github.io/docs_v7/Custom-Output/
  - `MARKER_PLOTTING` controls surface outputs; coefficient histories can expose
    force and moment sanity.
- SU2 Incompressible Turbulent NACA0012:
  https://su2code.github.io/tutorials/Inc_Turbulent_NACA0012/
  - Official external incompressible RANS + SA example with farfield and no-slip
    wall, TMR mesh, and `y+ < 1` near-wall spacing.
- SU2 Turbulent Flat Plate:
  https://su2code.github.io/tutorials/Turbulent_Flat_Plate/
  - SA is a common robust first model for external aerodynamic RANS.
- SU2 Transitional Flat Plate:
  https://su2code.github.io/tutorials/Transitional_Flat_Plate_T3A/
  - Transition modeling depends on turbulence assumptions and should be treated as
    a second-stage physics sensitivity here.
- Gmsh manual: https://gmsh.info/doc/texinfo/
  - Topological BL extrusion is available with the built-in kernel, but it is a
    simple extrusion with no fan or special reentrant-corner treatment; the
    `BoundaryLayer` field is 2D only.
- OpenVSP CFD Mesh API:
  https://openvsp.org/api_docs/3.42.2/group___c_f_d_mesh.html
  - OpenVSP exposes CFD mesh/source/wake controls, but this campaign does not
    treat OpenVSP as proof of solver-ready 3D prism BL quality.

## Engineering Interpretation

Euler/no-BL cases are instrumentation only. WO-006R2 needs no-slip viscous or
RANS ownership, explicit force/reference conventions, BL or a justified near-wall
alternative, and coefficient sanity before any AVL/VSPAERO/proxy comparison.
"""


def _write_commit_history_evidence(path: Path) -> None:
    commits = [
        "0f89edb3",
        "310c7db4",
        "2bc35e1",
        "7d5f572",
        "cd6f5b96",
        "3cd6c5e",
        "205f5382",
        "8daea0bd",
    ]
    chunks = ["# WO-006R2 Commit History Evidence\n"]
    for commit in commits:
        completed = subprocess.run(
            ["git", "show", "--stat", "--oneline", "--no-renames", commit],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        chunks.append(f"## {commit}\n")
        chunks.append("```text\n")
        chunks.append(completed.stdout.strip())
        chunks.append("\n```\n")
    path.write_text("\n".join(chunks), encoding="utf-8")


def _write_report(
    output_dir: Path,
    geometry: CurrentGoGeometry,
    attempts: Sequence[Mapping[str, Any]],
    final_payload: Mapping[str, Any],
    blockers: Sequence[Mapping[str, str]],
) -> None:
    lines = [
        "# WO-006R2 CFD Recovery Campaign Report",
        "",
        f"Verdict: `{final_payload['verdict']}`",
        "",
        "## Authority And Geometry",
        "",
        f"- Geometry: `{geometry.case_name}` from `{geometry.section_table_path}`.",
        f"- Mass authority: `{DESIGN_GROSS_MASS_KG} kg`.",
        f"- Span authority: `{PIPELINE_FULL_SPAN_M} m` full / `{PIPELINE_HALF_SPAN_M} m` half.",
        (
            f"- References: Sref `{geometry.reference.sref_full:.9f} m^2`, "
            f"Cref `{geometry.reference.cref:.9f} m`, "
            f"Bref `{geometry.reference.bref_full:.9f} m`."
        ),
        "- External Baseline A shape changed: `false`.",
        "",
        "## Old Evidence Reused",
        "",
        "- Reused the old mesh-native route definition, not old Black Cat coefficients.",
        "- Primary template: old `wing_h=0.20 m` HXT BL mesh with 1,125,409 cells.",
        "- Failure boundary: old `wing_h=0.15 m` BL mesh with 1,515,251 cells and two non-positive BL quality items.",
        "- Solver control: old 717,901-cell no-BL `INC_NAVIER_STOKES` 1000-iteration run, but only as non-drag-credible sign/reference evidence.",
        "",
        "## Manual Research",
        "",
        "See `manual_research_notes.md`. Key result: official SU2/Gmsh docs support the campaign policy that Euler/slip and no-BL tetra runs are not drag evidence; no-slip viscous/RANS cases need explicit wall markers and near-wall evidence.",
        "",
        "## Attempts",
        "",
    ]
    for attempt in attempts:
        mesh = attempt.get("mesh") or {}
        solver = attempt.get("solver") or {}
        lines.extend(
            [
                f"### {attempt.get('attempt_id')}",
                "",
                f"- route: `{attempt.get('route')}`",
                f"- mesh kind: `{attempt.get('mesh_kind')}`",
                f"- volume elements: `{mesh.get('volume_element_count')}`",
                f"- mesh gate: `{(mesh.get('mesh_quality_gate') or {}).get('status')}`",
                f"- marker audit: `{(mesh.get('marker_audit') or {}).get('status')}`",
                f"- solver status: `{solver.get('run_status')}`",
                f"- coefficient sanity: `{(solver.get('coefficient_sanity_gate') or {}).get('status')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## BL / y+ Status",
            "",
            "`yplus_nearwall_summary.json` records the first-layer estimate. This is not a solver-derived surface y+ field unless a later SU2 postprocess provides it.",
            "",
            "## Solver And Coefficients",
            "",
            "Coefficients are accepted only if mesh quality, marker ownership, 1000+ iteration evidence, iterative gate, and non-negative coefficient sanity all pass. Otherwise Baseline A reopen remains `not_evaluated`.",
            "",
            "## Blockers",
            "",
        ]
    )
    if blockers:
        for blocker in blockers:
            lines.append(
                f"- `{blocker.get('stage')}`: `{blocker.get('blocker')}`; "
                f"evidence `{_short_blocker_evidence(blocker)}`; "
                f"next `{blocker.get('next_fix')}`"
            )
    else:
        lines.append("- none recorded")
    lines.extend(
        [
            "",
            "## Engineering Caveats",
            "",
            "- This is bounded CFD route recovery, not final aircraft sign-off.",
            "- A passing SU2 run would still need mesh-pair/grid sensitivity before performance claims.",
            "- Low-Re HPA drag remains transition-sensitive; SA/SST/LM assumptions need explicit turbulence/roughness evidence.",
            "",
            "## Reviewer Prompt",
            "",
            "```text",
            "Review output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r2_cfd_recovery_campaign/. Check old_evidence_map.csv, route_decision_matrix.csv, yplus_nearwall_summary.json, mesh_attempts_summary.csv, solver_attempts_summary.csv, force_reference_audit.json, blocker_register.csv, and final_engineering_verdict.json. Judge whether the verdict is supported without promoting old Black Cat coefficients, blocked legacy mass/span values, no-BL drag, or negative CD into current Baseline A truth.",
            "```",
            "",
            "## Next Recommended Action",
            "",
            "Use `next_goal.md` if the verdict is not `wo006r2_cfd_evidence_gate_ready`.",
            "",
        ]
    )
    (output_dir / "cfd_recovery_campaign_report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _short_blocker_evidence(blocker: Mapping[str, str]) -> str:
    try:
        payload = json.loads(blocker.get("evidence", "{}"))
    except json.JSONDecodeError:
        return str(blocker.get("evidence", ""))[:200]
    contexts = payload.get("plc_intersection_context") or []
    if not contexts:
        return str(payload.get("tail") or blocker.get("evidence", ""))[:200]
    item = contexts[0]
    lower = item.get("bracket_lower_section_index")
    upper = item.get("bracket_upper_section_index")
    lower_airfoil = item.get("bracket_lower_airfoil_id")
    upper_airfoil = item.get("bracket_upper_airfoil_id")
    return (
        f"PLC point x={item.get('x_m')} y={item.get('y_m')} z={item.get('z_m')}; "
        f"section bracket {lower}-{upper} ({lower_airfoil}->{upper_airfoil}); "
        f"crosses_airfoil_family={item.get('bracket_crosses_airfoil_family')}"
    )


def _write_next_goal(
    output_dir: Path,
    final_payload: Mapping[str, Any],
    blockers: Sequence[Mapping[str, str]],
) -> None:
    blocker_text = "no blocker recorded"
    if blockers:
        blocker_text = f"{blockers[0].get('blocker')} at {blockers[0].get('stage')}"
    text = f"""/goal In /Volumes/Samsung SSD/hpa-mdo, continue WO-006R2 from {output_dir}: resolve the current CFD recovery blocker `{blocker_text}` without changing external GO/Baseline A shape, mass/CG authority, or spar/procurement truth. Treat data authority checker pass as a prerequisite and keep `scripts/check_baseline_a_data_authority.py --check-only` green. Start from cfd_recovery_campaign_report.md, mesh_attempts_summary.csv, solver_attempts_summary.csv, yplus_nearwall_summary.json, force_reference_audit.json, and blocker_register.csv. Preserve 98.5 kg, 34.332286 m / 17.166143 m, Sref=33.420059598 m^2, Cref=1.003721543 m, Bref=34.332286 m unless a newer promoted authority is found. Do not accept negative CD, no-BL drag, or old Black Cat coefficients as current Baseline A CFD evidence. Produce the next scoped artifact bundle, run targeted tests/checks, and commit only relevant files.

Current WO006R2 verdict: `{final_payload['verdict']}`.
"""
    (output_dir / "next_goal.md").write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
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
    parser.add_argument("--max-iterations", type=int, default=1000)
    parser.add_argument("--mesh-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--solver-timeout-seconds", type=float, default=7200.0)
    parser.add_argument("--skip-solver", action="store_true")
    parser.add_argument("--no-clean", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_campaign(
        output_dir=args.output_dir,
        max_iterations=args.max_iterations,
        run_solver=not args.skip_solver,
        mesh_timeout_seconds=args.mesh_timeout_seconds,
        solver_timeout_seconds=args.solver_timeout_seconds,
        clean=not args.no_clean,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
