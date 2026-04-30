import json
from pathlib import Path

import pytest

from hpa_meshing.main_wing_route_readiness import (
    build_main_wing_route_readiness_report,
    write_main_wing_route_readiness_report,
)


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _fixture_report_root(tmp_path: Path) -> Path:
    root = tmp_path / "reports"
    _write_json(
        root
        / "main_wing_esp_rebuilt_geometry_smoke"
        / "main_wing_esp_rebuilt_geometry_smoke.v1.json",
        {
            "geometry_smoke_status": "geometry_smoke_pass",
            "provider_status": "materialized",
            "surface_count": 32,
            "volume_count": 1,
            "blocking_reasons": ["main_wing_real_geometry_mesh_handoff_not_run"],
        },
    )
    _write_json(
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json",
        {
            "probe_status": "mesh_handoff_timeout",
            "mesh_handoff_status": "missing",
            "mesh2d_watchdog_status": "completed_without_timeout",
            "mesh3d_timeout_phase_classification": "volume_insertion",
            "mesh3d_nodes_created_per_boundary_node": 13.49,
            "blocking_reasons": [
                "main_wing_real_geometry_mesh_handoff_timeout",
                "main_wing_real_geometry_mesh3d_volume_insertion_timeout",
            ],
        },
    )
    _write_json(
        root / "main_wing_mesh_handoff_smoke" / "main_wing_mesh_handoff_smoke.v1.json",
        {
            "smoke_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "marker_summary_status": "component_wall_and_farfield_present",
            "volume_element_count": 865,
            "blocking_reasons": [
                "synthetic_fixture_not_real_aerodynamic_wing_geometry",
            ],
        },
    )
    su2_dir = root / "main_wing_su2_handoff_smoke"
    _write_json(
        su2_dir / "main_wing_su2_handoff_smoke.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "solver_execution_status": "not_run",
            "convergence_gate_status": "not_run",
            "component_force_ownership_status": "owned",
            "blocking_reasons": [
                "su2_solver_not_run",
                "convergence_gate_not_run",
                "synthetic_fixture_not_real_aerodynamic_wing_geometry",
                "real_main_wing_geometry_not_used",
            ],
        },
    )
    _write_json(
        su2_dir
        / "artifacts"
        / "su2"
        / "alpha_0_materialization_smoke"
        / "su2_handoff.json",
        {"runtime": {"velocity_mps": 6.5}},
    )
    return root


def test_main_wing_route_readiness_summarizes_stage_truth(tmp_path: Path):
    report = build_main_wing_route_readiness_report(
        report_root=_fixture_report_root(tmp_path)
    )

    stages = {stage.stage: stage for stage in report.stages}

    assert report.schema_version == "main_wing_route_readiness.v1"
    assert report.overall_status == "blocked_at_real_mesh_handoff"
    assert report.hpa_standard_flow_status == "hpa_standard_6p5_observed"
    assert report.observed_velocity_mps == 6.5
    assert stages["real_geometry"].status == "pass"
    assert stages["real_geometry"].evidence_kind == "real"
    assert stages["real_mesh_handoff"].status == "blocked"
    assert stages["real_mesh_handoff"].evidence_kind == "real"
    assert stages["synthetic_su2_handoff"].status == "materialized_synthetic_only"
    assert stages["synthetic_su2_handoff"].evidence_kind == "synthetic"
    assert stages["real_su2_handoff"].status == "blocked"
    assert stages["solver_smoke"].status == "not_run"
    assert stages["convergence_gate"].status == "not_run"
    assert "main_wing_real_geometry_mesh3d_volume_insertion_timeout" in report.blocking_reasons
    assert "repair_real_main_wing_mesh3d_volume_insertion_policy" in report.next_actions


def test_main_wing_route_readiness_moves_to_real_su2_after_real_mesh_pass(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "mesh3d_timeout_phase_classification": "optimization",
            "mesh3d_nodes_created_per_boundary_node": 23.9,
            "blocking_reasons": ["main_wing_solver_not_run", "convergence_gate_not_run"],
        }
    )
    _write_json(real_mesh_path, real_mesh)

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    assert report.overall_status == "blocked_at_real_su2_handoff"
    assert stages["real_mesh_handoff"].status == "pass"
    assert stages["real_su2_handoff"].observed["reason"] == (
        "real_su2_handoff_artifact_missing_after_mesh_handoff"
    )
    assert "real_main_wing_su2_handoff_not_materialized" in report.blocking_reasons
    assert "real_main_wing_geometry_not_used" not in report.blocking_reasons
    assert report.next_actions[0] == (
        "materialize_real_main_wing_su2_handoff_from_real_mesh_handoff_v1"
    )


def test_main_wing_route_readiness_moves_to_solver_after_real_su2_handoff(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": ["main_wing_solver_not_run", "convergence_gate_not_run"],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "su2_contract": "su2_handoff.v1",
            "input_mesh_contract": "mesh_handoff.v1",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": [
                "main_wing_solver_not_run",
                "convergence_gate_not_run",
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    assert report.overall_status == "solver_not_run"
    assert stages["real_su2_handoff"].status == "pass"
    assert stages["real_su2_handoff"].evidence_kind == "real"
    assert stages["real_su2_handoff"].observed["observed_velocity_mps"] == 6.5
    assert "real_main_wing_su2_handoff_not_materialized" not in report.blocking_reasons
    assert "main_wing_real_reference_geometry_warn" in report.blocking_reasons
    assert "main_wing_solver_not_run" in report.blocking_reasons
    assert report.next_actions[0] == "run_main_wing_solver_smoke_from_real_su2_handoff"


def test_main_wing_route_readiness_records_solver_nonconvergence_artifact(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": ["main_wing_solver_not_run", "convergence_gate_not_run"],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "su2_contract": "su2_handoff.v1",
            "input_mesh_contract": "mesh_handoff.v1",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": [
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "fail",
            "run_status": "solver_executed_but_not_converged",
            "history_path": "solver/history.csv",
            "convergence_gate_path": "solver/convergence_gate.v1.json",
            "final_iteration": 12,
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.30, "cd": 0.02, "cm": -0.1},
            "solver_log_quality_metrics": {
                "dual_control_volume_quality": {
                    "cv_sub_volume_ratio": {"min": 1.0, "max": 13256.1}
                }
            },
            "blocking_reasons": [
                "solver_executed_but_not_converged",
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )
    _write_json(
        root
        / "main_wing_reference_geometry_gate"
        / "main_wing_reference_geometry_gate.v1.json",
        {
            "reference_gate_status": "warn",
            "blocking_reasons": [
                "main_wing_reference_geometry_incomplete",
                "main_wing_reference_chord_not_independently_certified",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    assert report.overall_status == "solver_executed_not_converged"
    assert stages["solver_smoke"].status == "pass"
    assert stages["solver_smoke"].evidence_kind == "real"
    assert stages["solver_smoke"].observed["solver_execution_status"] == "solver_executed"
    assert stages["solver_smoke"].observed["main_wing_lift_acceptance_status"] == "fail"
    assert stages["solver_smoke"].observed["minimum_acceptable_cl"] == 1.0
    assert stages["real_su2_handoff"].observed["reference_gate_status"] == "warn"
    assert stages["convergence_gate"].status == "blocked"
    assert stages["convergence_gate"].observed["convergence_gate_status"] == "fail"
    assert "solver_executed_but_not_converged" in report.blocking_reasons
    assert "main_wing_reference_geometry_incomplete" in report.blocking_reasons
    assert "main_wing_solver_not_run" not in report.blocking_reasons
    assert report.next_actions[0] == (
        "resolve_main_wing_cl_below_expected_lift_before_convergence_claims"
    )
    assert "run_bounded_main_wing_iteration_sweep_after_reference_gate_is_clean" in report.next_actions


def test_main_wing_route_readiness_blocks_convergence_pass_when_cl_is_too_low(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": [],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "su2_contract": "su2_handoff.v1",
            "input_mesh_contract": "mesh_handoff.v1",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "pass",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": [],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "pass",
            "run_status": "solver_executed",
            "final_iteration": 200,
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.72, "cd": 0.02, "cm": -0.1},
            "blocking_reasons": [],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    assert report.overall_status == "solver_executed_not_converged"
    assert stages["solver_smoke"].observed["main_wing_lift_acceptance_status"] == "fail"
    assert stages["convergence_gate"].status == "blocked"
    assert "main_wing_cl_below_expected_lift" in report.blocking_reasons
    assert report.next_actions[0] == (
        "resolve_main_wing_cl_below_expected_lift_before_convergence_claims"
    )


def test_main_wing_route_readiness_records_geometry_and_lift_diagnostic_stages(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    _write_json(
        root
        / "main_wing_geometry_provenance_probe"
        / "main_wing_geometry_provenance_probe.v1.json",
        {
            "geometry_provenance_status": "provenance_available",
            "selected_geom_id": "IPAWXFWPQF",
            "selected_geom_name": "Main Wing",
            "installation_incidence_deg": 3.0,
            "section_count": 6,
            "twist_summary": {"all_sections_zero_twist": True},
            "airfoil_summary": {
                "cambered_airfoil_coordinates_observed": True,
                "max_abs_camber_over_chord": 0.071,
            },
            "alpha_zero_interpretation": (
                "alpha_zero_expected_positive_lift_but_not_acceptance_lift"
            ),
        },
    )
    _write_json(
        root
        / "main_wing_lift_acceptance_diagnostic"
        / "main_wing_lift_acceptance_diagnostic.v1.json",
        {
            "diagnostic_status": "lift_deficit_observed",
            "minimum_acceptable_cl": 1.0,
            "selected_solver_report": {"runtime_max_iterations": 80},
            "panel_reference_observed": {"cltot": 1.287645495943},
            "flow_condition_observed": {"velocity_mps": 6.5, "alpha_deg": 0.0},
            "reference_observed": {"ref_area_m2": 35.175},
            "lift_metrics": {"cl": 0.263, "observed_cl_to_minimum_ratio": 0.263},
            "lift_gap_diagnostics": {
                "panel_vs_su2_status": "panel_supports_expected_lift_su2_low",
                "panel_to_su2_cl_ratio": 4.89,
            },
            "root_cause_candidates": [
                {
                    "candidate": "su2_route_lift_deficit_not_explained_by_operating_alpha_alone",
                    "priority": "high",
                }
            ],
            "engineering_flags": [
                "main_wing_cl_below_expected_lift",
                "alpha_zero_operating_lift_not_demonstrated",
                "vspaero_panel_cl_gt_one_while_su2_low",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    geometry_stage = stages["geometry_provenance"]
    lift_stage = stages["lift_acceptance_diagnostic"]
    assert geometry_stage.status == "pass"
    assert geometry_stage.observed["installation_incidence_deg"] == 3.0
    assert geometry_stage.observed["airfoil_summary"][
        "cambered_airfoil_coordinates_observed"
    ]
    assert lift_stage.status == "blocked"
    assert lift_stage.observed["minimum_acceptable_cl"] == 1.0
    assert lift_stage.observed["panel_reference_observed"]["cltot"] == pytest.approx(
        1.287645495943
    )
    assert lift_stage.observed["lift_gap_diagnostics"][
        "panel_vs_su2_status"
    ] == "panel_supports_expected_lift_su2_low"
    assert lift_stage.observed["root_cause_candidates"][0]["priority"] == "high"
    assert "main_wing_cl_below_expected_lift" in lift_stage.blockers
    assert "alpha_zero_operating_lift_not_demonstrated" in report.blocking_reasons


def test_main_wing_route_readiness_records_vspaero_panel_reference_stage(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    _write_json(
        root
        / "main_wing_vspaero_panel_reference_probe"
        / "main_wing_vspaero_panel_reference_probe.v1.json",
        {
            "panel_reference_status": "panel_reference_available",
            "hpa_standard_flow_status": "hpa_standard_6p5_observed",
            "lift_acceptance_status": "pass",
            "minimum_acceptable_cl": 1.0,
            "selected_case": {"AoA": 0.0, "CLtot": 1.287645495943, "CDtot": 0.045},
            "setup_reference": {"Vinf": 6.5, "Sref": 35.175},
            "su2_smoke_comparison": {
                "status": "available",
                "panel_reference_cl": 1.287645495943,
                "selected_su2_smoke_cl": 0.263161913,
                "panel_to_su2_cl_ratio": 4.892978171742504,
            },
            "engineering_flags": [
                "vspaero_panel_reference_cl_gt_one",
                "su2_smoke_below_vspaero_panel_reference",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    panel_stage = stages["vspaero_panel_reference"]
    assert panel_stage.status == "pass"
    assert panel_stage.evidence_kind == "real"
    assert panel_stage.observed["cltot"] == pytest.approx(1.287645495943)
    assert panel_stage.observed["velocity_mps"] == 6.5
    assert panel_stage.observed["su2_smoke_comparison"][
        "panel_to_su2_cl_ratio"
    ] == pytest.approx(4.892978171742504)
    assert "su2_smoke_below_vspaero_panel_reference" in panel_stage.observed[
        "engineering_flags"
    ]
    assert "su2_smoke_below_vspaero_panel_reference" not in report.blocking_reasons


def test_main_wing_route_readiness_records_panel_su2_lift_gap_debug_stage(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": [],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "su2_contract": "su2_handoff.v1",
            "input_mesh_contract": "mesh_handoff.v1",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": ["main_wing_real_reference_geometry_warn"],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "fail",
            "run_status": "solver_executed_but_not_converged",
            "final_iteration": 80,
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.263, "cd": 0.02, "cm": -0.2},
            "blocking_reasons": ["solver_executed_but_not_converged"],
        },
    )
    _write_json(
        root
        / "main_wing_panel_su2_lift_gap_debug"
        / "main_wing_panel_su2_lift_gap_debug.v1.json",
        {
            "debug_status": "gap_confirmed_debug_ready",
            "flow_reference_alignment": {
                "status": "pass",
                "ref_area_relative_delta": 0.0,
            },
            "panel_reference_decomposition": {
                "cltot": 1.287645495943,
                "induced_lift_fraction_of_cltot": 1.0021338531262347,
            },
            "su2_force_breakdown": {
                "forces_breakdown_cl": 0.263162,
                "force_breakdown_marker_owned": True,
                "force_breakdown_matches_history_cl": True,
            },
            "engineering_findings": [
                "panel_su2_lift_gap_confirmed",
                "reference_normalization_not_primary_cause",
                "panel_lift_dominated_by_wake_induced_terms",
                "su2_wall_bc_is_euler_smoke",
            ],
            "primary_hypotheses": [
                {
                    "hypothesis": "panel_su2_lifting_surface_semantics_or_geometry_mismatch",
                    "priority": "high",
                }
            ],
            "next_actions": [
                "compare_openvsp_panel_geometry_against_su2_mesh_normals_incidence_and_wake_semantics"
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    debug_stage = stages["panel_su2_lift_gap_debug"]
    assert debug_stage.status == "pass"
    assert debug_stage.evidence_kind == "real"
    assert debug_stage.observed["debug_status"] == "gap_confirmed_debug_ready"
    assert debug_stage.observed["primary_hypotheses"][0]["priority"] == "high"
    assert report.next_actions[0] == (
        "compare_openvsp_panel_geometry_against_su2_mesh_normals_incidence_and_wake_semantics"
    )


def test_main_wing_route_readiness_records_su2_mesh_normal_audit_stage(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": [],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": ["main_wing_real_reference_geometry_warn"],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "fail",
            "run_status": "solver_executed_but_not_converged",
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.263161913, "cd": 0.025},
            "blocking_reasons": ["solver_executed_but_not_converged"],
        },
    )
    _write_json(
        root
        / "main_wing_panel_su2_lift_gap_debug"
        / "main_wing_panel_su2_lift_gap_debug.v1.json",
        {
            "debug_status": "gap_confirmed_debug_ready",
            "next_actions": [
                "compare_openvsp_panel_geometry_against_su2_mesh_normals_incidence_and_wake_semantics"
            ],
        },
    )
    _write_json(
        root
        / "main_wing_su2_mesh_normal_audit"
        / "main_wing_su2_mesh_normal_audit.v1.json",
        {
            "normal_audit_status": "pass",
            "main_wing_surface_entity_count": 32,
            "surface_triangle_count": 2424,
            "normal_orientation": {
                "z_positive_fraction": 0.511963696369637,
                "z_negative_fraction": 0.4839108910891089,
                "area_weighted_mean_normal": [
                    1.0143938927015298e-18,
                    -0.0008604344522536509,
                    -1.261221222764421e-17,
                ],
            },
            "engineering_findings": [
                "main_wing_surface_normals_mixed_upper_lower",
                "single_global_normal_flip_not_supported",
            ],
            "next_actions": [
                "compare_openvsp_panel_wake_model_against_su2_thin_sheet_wall_semantics"
            ],
            "blocking_reasons": [],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    normal_stage = stages["su2_mesh_normal_audit"]
    assert normal_stage.status == "pass"
    assert normal_stage.evidence_kind == "real"
    assert normal_stage.observed["surface_triangle_count"] == 2424
    assert "single_global_normal_flip_not_supported" in normal_stage.observed[
        "engineering_findings"
    ]
    assert report.next_actions[0] == (
        "compare_openvsp_panel_wake_model_against_su2_thin_sheet_wall_semantics"
    )


def test_main_wing_route_readiness_records_panel_wake_semantics_audit_stage(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": [],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": ["main_wing_real_reference_geometry_warn"],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "fail",
            "run_status": "solver_executed_but_not_converged",
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.263161913, "cd": 0.025},
            "blocking_reasons": ["solver_executed_but_not_converged"],
        },
    )
    _write_json(
        root
        / "main_wing_panel_wake_semantics_audit"
        / "main_wing_panel_wake_semantics_audit.v1.json",
        {
            "audit_status": "semantics_gap_observed",
            "panel_wake_observed": {
                "induced_lift_fraction_of_cltot": 1.0021338531262347,
                "cltot": 1.287645495943,
            },
            "su2_semantics_observed": {
                "wall_boundary_condition": "euler",
                "forces_breakdown_cl": 0.263162,
            },
            "engineering_findings": [
                "panel_su2_semantics_gap_observed",
                "thin_sheet_wall_not_yet_bridged_to_panel_wake_semantics",
            ],
            "next_actions": [
                "audit_su2_thin_surface_geometry_closed_vs_lifting_surface_export"
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    semantics_stage = stages["panel_wake_semantics_audit"]
    assert semantics_stage.status == "pass"
    assert semantics_stage.evidence_kind == "real"
    assert semantics_stage.observed["audit_status"] == "semantics_gap_observed"
    assert "thin_sheet_wall_not_yet_bridged_to_panel_wake_semantics" in (
        semantics_stage.observed["engineering_findings"]
    )
    assert report.next_actions[0] == (
        "audit_su2_thin_surface_geometry_closed_vs_lifting_surface_export"
    )


def test_main_wing_route_readiness_records_su2_surface_topology_audit_stage(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": [],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": ["main_wing_real_reference_geometry_warn"],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "fail",
            "run_status": "solver_executed_but_not_converged",
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.263161913, "cd": 0.025},
            "blocking_reasons": ["solver_executed_but_not_converged"],
        },
    )
    _write_json(
        root
        / "main_wing_su2_surface_topology_audit"
        / "main_wing_su2_surface_topology_audit.v1.json",
        {
            "audit_status": "thin_surface_like_with_local_topology_defects",
            "edge_topology_observed": {
                "boundary_edge_count": 4,
                "nonmanifold_edge_count": 2,
                "boundary_edge_fraction": 0.0011,
            },
            "area_evidence_observed": {
                "surface_area_to_reference_area_ratio": 1.2063,
                "projected_abs_area_to_reference_area_ratio": 1.076,
                "single_sheet_area_like": True,
            },
            "engineering_findings": [
                "open_boundary_edges_localized_low_fraction",
                "nonmanifold_edges_present",
                "thin_surface_like_area_with_local_topology_defects",
            ],
            "next_actions": [
                "localize_main_wing_open_boundary_and_nonmanifold_edges"
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    topology_stage = stages["su2_surface_topology_audit"]
    assert topology_stage.status == "pass"
    assert topology_stage.evidence_kind == "real"
    assert topology_stage.observed["audit_status"] == (
        "thin_surface_like_with_local_topology_defects"
    )
    assert topology_stage.observed["edge_topology_observed"][
        "boundary_edge_count"
    ] == 4
    assert report.next_actions[0] == (
        "localize_main_wing_open_boundary_and_nonmanifold_edges"
    )


def test_main_wing_route_readiness_surfaces_real_mesh_quality_advisories(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "mesh_quality_status": "warn",
            "mesh_quality_metrics": {
                "ill_shaped_tet_count": 78,
                "min_gamma": 8.13e-7,
                "gamma_percentiles": {"p01": 0.133},
            },
            "mesh_quality_advisory_flags": [
                "gmsh_ill_shaped_tets_present",
                "gmsh_min_gamma_below_1e_minus_4",
            ],
            "blocking_reasons": ["main_wing_solver_not_run", "convergence_gate_not_run"],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "su2_contract": "su2_handoff.v1",
            "input_mesh_contract": "mesh_handoff.v1",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": ["main_wing_real_reference_geometry_warn"],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "warn",
            "run_status": "solver_executed_but_not_converged",
            "final_iteration": 40,
            "observed_velocity_mps": 6.5,
            "blocking_reasons": [
                "solver_executed_but_not_converged",
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    real_mesh_stage = stages["real_mesh_handoff"]
    assert real_mesh_stage.status == "pass"
    assert real_mesh_stage.observed["mesh_quality_status"] == "warn"
    assert real_mesh_stage.observed["mesh_quality_metrics"]["ill_shaped_tet_count"] == 78
    assert "gmsh_min_gamma_below_1e_minus_4" in real_mesh_stage.observed[
        "mesh_quality_advisory_flags"
    ]
    assert report.next_actions[0] == (
        "inspect_main_wing_mesh_quality_before_more_solver_budget"
    )


def test_main_wing_route_readiness_records_openvsp_reference_probe_stages(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    _write_json(
        root
        / "main_wing_openvsp_reference_su2_handoff_probe"
        / "main_wing_openvsp_reference_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "reference_policy": "openvsp_geometry_derived",
            "su2_contract": "su2_handoff.v1",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": [
                "main_wing_solver_not_run",
                "convergence_gate_not_run",
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )
    _write_json(
        root
        / "main_wing_openvsp_reference_geometry_gate"
        / "main_wing_reference_geometry_gate.v1.json",
        {
            "reference_gate_status": "warn",
            "observed_velocity_mps": 6.5,
            "applied_reference": {"ref_area": 35.175, "ref_length": 1.0425},
            "openvsp_reference": {"ref_area": 35.175, "ref_length": 1.0425},
            "derived_full_span_m": 33.0,
            "derived_full_span_method": "area_provenance.details.wing_quantities.bref",
            "blocking_reasons": [
                "main_wing_reference_geometry_incomplete",
                "main_wing_moment_origin_not_certified",
            ],
        },
    )
    _write_json(
        root
        / "main_wing_su2_force_marker_audit"
        / "main_wing_su2_force_marker_audit.v1.json",
        {
            "audit_status": "warn",
            "marker_contract": {
                "wall_marker": "main_wing",
                "farfield_marker": "farfield",
                "force_surface_gate_status": "pass",
            },
            "cfg_markers": {
                "MARKER_EULER": ["main_wing"],
                "MARKER_MONITORING": ["main_wing"],
                "MARKER_PLOTTING": ["main_wing"],
                "MARKER_FAR": ["farfield"],
            },
            "flow_reference_observed": {"velocity_mps": 6.5},
            "engineering_flags": [
                "main_wing_solver_wall_bc_is_euler_smoke_not_viscous"
            ],
            "blocking_reasons": [],
        },
    )
    _write_json(
        root
        / "main_wing_openvsp_reference_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "fail",
            "run_status": "solver_executed_but_not_converged",
            "convergence_comparability_level": "not_comparable",
            "final_iteration": 11,
            "final_coefficients": {
                "cl": 0.2602573982,
                "cd": 0.01858625024,
                "cm": -0.2032569615,
                "cm_axis": "CMy",
            },
            "observed_velocity_mps": 6.5,
            "solver_log_quality_metrics": {
                "dual_control_volume_quality": {
                    "cv_sub_volume_ratio": {"min": 1.0, "max": 13256.1}
                }
            },
            "blocking_reasons": [
                "solver_executed_but_not_converged",
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    handoff_stage = stages["openvsp_reference_su2_handoff"]
    marker_audit_stage = stages["su2_force_marker_audit"]
    reference_gate_stage = stages["openvsp_reference_geometry_gate"]
    solver_stage = stages["openvsp_reference_solver_smoke"]
    assert handoff_stage.status == "pass"
    assert handoff_stage.observed["reference_policy"] == "openvsp_geometry_derived"
    assert marker_audit_stage.status == "pass"
    assert marker_audit_stage.observed["audit_status"] == "warn"
    assert marker_audit_stage.observed["marker_contract"]["wall_marker"] == "main_wing"
    assert not marker_audit_stage.blockers
    assert reference_gate_stage.status == "blocked"
    assert reference_gate_stage.evidence_kind == "real"
    assert reference_gate_stage.observed["derived_full_span_method"] == (
        "area_provenance.details.wing_quantities.bref"
    )
    assert "main_wing_moment_origin_not_certified" in reference_gate_stage.blockers
    assert solver_stage.status == "pass"
    assert solver_stage.observed["run_status"] == "solver_executed_but_not_converged"
    assert solver_stage.observed["final_coefficients"]["cm_axis"] == "CMy"
    assert "solver_executed_but_not_converged" in report.blocking_reasons


def test_main_wing_route_readiness_records_surface_force_output_audit_stage(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    _write_json(
        root
        / "main_wing_surface_force_output_audit"
        / "main_wing_surface_force_output_audit.v1.json",
        {
            "audit_status": "blocked",
            "solver_execution_observed": {
                "solver_execution_status": "solver_executed",
                "run_status": "solver_executed_but_not_converged",
                "main_wing_lift_acceptance_status": "fail",
                "observed_velocity_mps": 6.5,
                "final_coefficients": {"cl": 0.263161913},
            },
            "expected_outputs_from_log": {
                "surface_csv": "surface.csv",
                "forces_breakdown": "forces_breakdown.dat",
            },
            "artifact_retention_observed": {
                "surface_csv_candidates": [],
                "forces_breakdown_candidates": [],
                "pruned_surface_outputs": ["case/surface.csv"],
            },
            "force_breakdown_observed": {
                "status": "available",
                "surface_names": ["main_wing"],
                "total_coefficients": {"cl": 0.263162},
                "history_cl_delta_abs": 8.7e-8,
                "panel_to_force_breakdown_cl_ratio": 4.892976554149155,
            },
            "panel_reference_observed": {
                "status": "available",
                "panel_reference_cl": 1.287645495943,
                "selected_su2_smoke_cl": 0.263161913,
                "panel_to_su2_cl_ratio": 4.892978171742504,
            },
            "engineering_flags": [
                "solver_executed_but_not_converged",
                "main_wing_lift_acceptance_failed_cl_below_one",
            ],
            "blocking_reasons": [
                "surface_force_output_pruned_or_missing",
                "forces_breakdown_output_missing",
                "panel_force_comparison_not_ready",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    surface_force_stage = stages["surface_force_output_audit"]
    assert surface_force_stage.status == "blocked"
    assert surface_force_stage.evidence_kind == "real"
    assert surface_force_stage.observed["audit_status"] == "blocked"
    assert surface_force_stage.observed["expected_outputs_from_log"][
        "surface_csv"
    ] == "surface.csv"
    assert surface_force_stage.observed["panel_reference_observed"][
        "panel_reference_cl"
    ] == pytest.approx(1.287645495943)
    assert surface_force_stage.observed["force_breakdown_observed"][
        "surface_names"
    ] == ["main_wing"]
    assert surface_force_stage.observed["force_breakdown_observed"][
        "panel_to_force_breakdown_cl_ratio"
    ] == pytest.approx(4.892976554149155)
    assert "surface_force_output_pruned_or_missing" in surface_force_stage.blockers
    assert "panel_force_comparison_not_ready" in report.blocking_reasons


def test_main_wing_route_readiness_prioritizes_surface_force_retention_for_cl_gap(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": [],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "su2_contract": "su2_handoff.v1",
            "input_mesh_contract": "mesh_handoff.v1",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "pass",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": [],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "warn",
            "run_status": "solver_executed_but_not_converged",
            "final_iteration": 80,
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.263161913, "cd": 0.025},
            "blocking_reasons": ["solver_executed_but_not_converged"],
        },
    )
    _write_json(
        root
        / "main_wing_surface_force_output_audit"
        / "main_wing_surface_force_output_audit.v1.json",
        {
            "audit_status": "blocked",
            "blocking_reasons": [
                "surface_force_output_pruned_or_missing",
                "forces_breakdown_output_missing",
                "panel_force_comparison_not_ready",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    assert report.overall_status == "solver_executed_not_converged"
    assert "main_wing_cl_below_expected_lift" in report.blocking_reasons
    assert "surface_force_output_pruned_or_missing" in report.blocking_reasons
    assert report.next_actions[0] == (
        "preserve_main_wing_surface_force_outputs_before_panel_delta_debug"
    )


def test_main_wing_route_readiness_prioritizes_force_breakdown_when_surface_exists(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": [],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "pass",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": [],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "warn",
            "run_status": "solver_executed_but_not_converged",
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.263161913},
            "blocking_reasons": ["solver_executed_but_not_converged"],
        },
    )
    _write_json(
        root
        / "main_wing_surface_force_output_audit"
        / "main_wing_surface_force_output_audit.v1.json",
        {
            "audit_status": "blocked",
            "blocking_reasons": [
                "forces_breakdown_output_missing",
                "panel_force_comparison_not_ready",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    assert "surface_force_output_pruned_or_missing" not in report.blocking_reasons
    assert "forces_breakdown_output_missing" in report.blocking_reasons
    assert report.next_actions[0] == (
        "resolve_main_wing_forces_breakdown_output_before_panel_delta_debug"
    )


def test_main_wing_route_readiness_prioritizes_retained_force_breakdown_lift_gap(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh.update(
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "blocking_reasons": [],
        }
    )
    _write_json(real_mesh_path, real_mesh)
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "pass",
            "observed_velocity_mps": 6.5,
            "blocking_reasons": [],
        },
    )
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "warn",
            "run_status": "solver_executed_but_not_converged",
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.263161913},
            "blocking_reasons": ["solver_executed_but_not_converged"],
        },
    )
    _write_json(
        root
        / "main_wing_surface_force_output_audit"
        / "main_wing_surface_force_output_audit.v1.json",
        {
            "audit_status": "warn",
            "engineering_flags": [
                "forces_breakdown_cl_below_panel_reference",
            ],
            "blocking_reasons": [],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    assert report.next_actions[0] == (
        "debug_panel_su2_lift_gap_from_retained_force_breakdown"
    )


def test_main_wing_route_readiness_records_solver_budget_probe_stages(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    _write_json(
        root
        / "main_wing_real_solver_smoke_probe_iter40"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "warn",
            "run_status": "solver_executed_but_not_converged",
            "convergence_comparability_level": "run_only",
            "final_iteration": 39,
            "runtime_max_iterations": 40,
            "final_coefficients": {
                "cl": 0.2719146364,
                "cd": 0.02596997971,
                "cm": -0.1467861013,
                "cm_axis": "CMy",
            },
            "observed_velocity_mps": 6.5,
            "solver_log_quality_metrics": {
                "dual_control_volume_quality": {
                    "cv_sub_volume_ratio": {"min": 1.0, "max": 13256.1}
                }
            },
            "blocking_reasons": [
                "solver_executed_but_not_converged",
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )
    _write_json(
        root
        / "main_wing_openvsp_reference_solver_smoke_probe_iter40"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "warn",
            "run_status": "solver_executed_but_not_converged",
            "convergence_comparability_level": "run_only",
            "final_iteration": 39,
            "runtime_max_iterations": 40,
            "final_coefficients": {
                "cl": 0.267856209,
                "cd": 0.02558236807,
                "cm": -0.2130813257,
                "cm_axis": "CMy",
            },
            "observed_velocity_mps": 6.5,
            "blocking_reasons": [
                "solver_executed_but_not_converged",
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    solver_budget = stages["solver_budget_probe"]
    openvsp_solver_budget = stages["openvsp_reference_solver_budget_probe"]
    assert solver_budget.status == "pass"
    assert solver_budget.observed["runtime_max_iterations"] == 40
    assert solver_budget.observed["convergence_comparability_level"] == "run_only"
    assert solver_budget.observed["final_coefficients"]["cm_axis"] == "CMy"
    assert (
        solver_budget.observed["solver_log_quality_metrics"][
            "dual_control_volume_quality"
        ]["cv_sub_volume_ratio"]["max"]
        == 13256.1
    )
    assert openvsp_solver_budget.status == "pass"
    assert openvsp_solver_budget.observed["runtime_max_iterations"] == 40
    assert openvsp_solver_budget.observed["final_coefficients"]["cm"] == -0.2130813257
    assert report.overall_status == "blocked_at_real_mesh_handoff"
    assert "solver_executed_but_not_converged" in report.blocking_reasons


def test_main_wing_route_readiness_selects_highest_solver_budget_probe(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    for iterations, cl in [(20, 0.25), (80, 0.28)]:
        _write_json(
            root
            / f"main_wing_real_solver_smoke_probe_iter{iterations}"
            / "main_wing_real_solver_smoke_probe.v1.json",
            {
                "solver_execution_status": "solver_executed",
                "convergence_gate_status": "warn",
                "run_status": "solver_executed_but_not_converged",
                "convergence_comparability_level": "run_only",
                "final_iteration": iterations - 1,
                "runtime_max_iterations": iterations,
                "final_coefficients": {
                    "cl": cl,
                    "cd": 0.02,
                    "cm": -0.15,
                    "cm_axis": "CMy",
                },
                "observed_velocity_mps": 6.5,
                "blocking_reasons": ["solver_executed_but_not_converged"],
            },
        )
    for iterations, cm in [(40, -0.21), (80, -0.22)]:
        _write_json(
            root
            / f"main_wing_openvsp_reference_solver_smoke_probe_iter{iterations}"
            / "main_wing_real_solver_smoke_probe.v1.json",
            {
                "solver_execution_status": "solver_executed",
                "convergence_gate_status": "warn",
                "run_status": "solver_executed_but_not_converged",
                "convergence_comparability_level": "run_only",
                "final_iteration": iterations - 1,
                "runtime_max_iterations": iterations,
                "final_coefficients": {
                    "cl": 0.27,
                    "cd": 0.026,
                    "cm": cm,
                    "cm_axis": "CMy",
                },
                "observed_velocity_mps": 6.5,
                "blocking_reasons": ["solver_executed_but_not_converged"],
            },
        )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    solver_budget = stages["solver_budget_probe"]
    openvsp_solver_budget = stages["openvsp_reference_solver_budget_probe"]
    assert "main_wing_real_solver_smoke_probe_iter80" in solver_budget.artifact_path
    assert solver_budget.observed["runtime_max_iterations"] == 80
    assert solver_budget.observed["final_coefficients"]["cl"] == 0.28
    assert (
        "main_wing_openvsp_reference_solver_smoke_probe_iter80"
        in openvsp_solver_budget.artifact_path
    )
    assert openvsp_solver_budget.observed["runtime_max_iterations"] == 80
    assert openvsp_solver_budget.observed["final_coefficients"]["cm"] == -0.22


def test_main_wing_route_readiness_prioritizes_invalid_boundary_mesh_action(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh["failure_code"] = "gmsh_invalid_boundary_mesh"
    real_mesh["mesh_failure_classification"] = "invalid_boundary_mesh_overlapping_facets"
    real_mesh["blocking_reasons"] = [
        "main_wing_real_geometry_mesh_handoff_blocked",
        "main_wing_real_geometry_invalid_boundary_mesh_overlapping_facets",
    ]
    _write_json(real_mesh_path, real_mesh)

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    assert stages["real_mesh_handoff"].observed["mesh_failure_classification"] == (
        "invalid_boundary_mesh_overlapping_facets"
    )
    assert report.next_actions[0] == (
        "repair_real_main_wing_boundary_overlap_before_volume_meshing"
    )
    assert (
        "main_wing_real_geometry_invalid_boundary_mesh_overlapping_facets"
        in report.blocking_reasons
    )


def test_main_wing_route_readiness_prioritizes_boundary_topology_action(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    real_mesh_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    real_mesh = json.loads(real_mesh_path.read_text(encoding="utf-8"))
    real_mesh["failure_code"] = "gmsh_boundary_parametrization_topology"
    real_mesh["mesh_failure_classification"] = "boundary_parametrization_topology_failed"
    real_mesh["blocking_reasons"] = [
        "main_wing_real_geometry_mesh_handoff_blocked",
        "main_wing_real_geometry_boundary_parametrization_topology_failed",
    ]
    _write_json(real_mesh_path, real_mesh)

    report = build_main_wing_route_readiness_report(report_root=root)

    assert report.next_actions[0] == (
        "repair_real_main_wing_boundary_topology_before_volume_meshing"
    )
    assert (
        "main_wing_real_geometry_boundary_parametrization_topology_failed"
        in report.blocking_reasons
    )


def test_main_wing_route_readiness_writer_outputs_json_and_markdown(tmp_path: Path):
    paths = write_main_wing_route_readiness_report(
        tmp_path / "out",
        report=build_main_wing_route_readiness_report(
            report_root=_fixture_report_root(tmp_path)
        ),
    )

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["overall_status"] == "blocked_at_real_mesh_handoff"
    assert "real_mesh_handoff" in markdown
    assert "blocked_at_real_mesh_handoff" in markdown
