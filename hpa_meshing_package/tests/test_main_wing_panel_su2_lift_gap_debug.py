import json
from pathlib import Path

import pytest

from hpa_meshing.main_wing_panel_su2_lift_gap_debug import (
    build_main_wing_panel_su2_lift_gap_debug_report,
    write_main_wing_panel_su2_lift_gap_debug_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _fixture_report_root(tmp_path: Path) -> Path:
    root = tmp_path / "docs" / "reports"
    _write_json(
        root
        / "main_wing_vspaero_panel_reference_probe"
        / "main_wing_vspaero_panel_reference_probe.v1.json",
        {
            "panel_reference_status": "panel_reference_available",
            "selected_case": {
                "AoA": 0.0,
                "CLo": -0.002747646367,
                "CLi": 1.29039314231,
                "CLtot": 1.287645495943,
                "CDo": 0.024039646573,
                "CDi": 0.021028447271,
                "CDtot": 0.045068093845,
                "CFztot": 1.287645495943,
                "CLwtot": 1.289971668181,
            },
            "setup_reference": {
                "Sref": 35.175,
                "Cref": 1.0425,
                "Bref": 33.0,
                "Vinf": 6.5,
                "Rho": 1.225,
            },
        },
    )
    _write_json(
        root
        / "main_wing_lift_acceptance_diagnostic"
        / "main_wing_lift_acceptance_diagnostic.v1.json",
        {
            "diagnostic_status": "lift_deficit_observed",
            "minimum_acceptable_cl": 1.0,
            "selected_solver_report": {
                "runtime_max_iterations": 80,
                "convergence_gate_status": "fail",
                "convergence_comparability_level": "not_comparable",
                "final_coefficients": {"cl": 0.263161913},
                "su2_handoff_path_source": "retained_solver_report_su2_handoff_path",
            },
            "flow_condition_observed": {
                "velocity_mps": 6.5,
                "density_kgpm3": 1.225,
                "alpha_deg": 0.0,
            },
            "reference_observed": {
                "ref_area_m2": 35.175,
                "ref_length_m": 1.0425,
                "declared_vs_openvsp_area_relative_error": 0.0,
            },
            "lift_gap_diagnostics": {
                "selected_su2_cl": 0.263161913,
                "vspaero_panel_cl": 1.287645495943,
                "forces_breakdown_cl": 0.263162,
                "force_breakdown_marker_owned": True,
                "force_breakdown_matches_history_cl": True,
                "panel_to_force_breakdown_cl_ratio": 4.892976554149155,
                "force_breakdown_vs_panel_status": (
                    "panel_supports_expected_lift_force_breakdown_low"
                ),
            },
        },
    )
    _write_json(
        root
        / "main_wing_surface_force_output_audit"
        / "main_wing_surface_force_output_audit.v1.json",
        {
            "audit_status": "warn",
            "force_breakdown_observed": {
                "status": "available",
                "surface_names": ["main_wing"],
                "total_coefficients": {"cl": 0.263162, "cd": 0.024969},
                "surface_coefficients": {
                    "main_wing": {"cl": 0.263162, "cd": 0.024969}
                },
                "history_cl_delta_abs": 8.7e-8,
                "panel_to_force_breakdown_cl_ratio": 4.892976554149155,
            },
            "checks": {
                "forces_breakdown_marker_owned": {"status": "pass"},
                "forces_breakdown_matches_history_cl": {"status": "pass"},
            },
        },
    )
    _write_json(
        root
        / "main_wing_su2_force_marker_audit"
        / "main_wing_su2_force_marker_audit.v1.json",
        {
            "audit_status": "warn",
            "checks": {
                "flow_reference_consistency": {
                    "status": "pass",
                    "observed": {
                        "velocity_mps": 6.5,
                        "ref_area_m2": 35.175,
                        "ref_length_m": 1.0425,
                        "wall_boundary_condition": "euler",
                        "solver": "INC_NAVIER_STOKES",
                    },
                }
            },
            "engineering_flags": ["main_wing_solver_wall_bc_is_euler_smoke_not_viscous"],
        },
    )
    _write_json(
        root
        / "main_wing_openvsp_reference_solver_smoke_probe_iter80"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "run_status": "solver_executed_but_not_converged",
            "convergence_gate_status": "fail",
            "convergence_comparability_level": "not_comparable",
            "runtime_max_iterations": 80,
            "final_iteration": 79,
            "observed_velocity_mps": 6.5,
            "final_coefficients": {"cl": 0.263161913, "cd": 0.02496911575},
            "solver_log_quality_metrics": {
                "dual_control_volume_quality": {
                    "cv_face_area_aspect_ratio": {"max": 377.909},
                    "cv_sub_volume_ratio": {"max": 13256.1},
                }
            },
        },
    )
    return root


def test_main_wing_panel_su2_lift_gap_debug_ranks_engineering_hypotheses(
    tmp_path: Path,
):
    report = build_main_wing_panel_su2_lift_gap_debug_report(
        report_root=_fixture_report_root(tmp_path)
    )

    assert report.debug_status == "gap_confirmed_debug_ready"
    assert report.flow_reference_alignment["status"] == "pass"
    assert report.flow_reference_alignment["panel_sref_m2"] == pytest.approx(35.175)
    assert report.flow_reference_alignment["su2_ref_area_m2"] == pytest.approx(35.175)
    assert report.panel_reference_decomposition["cltot"] == pytest.approx(
        1.287645495943
    )
    assert report.panel_reference_decomposition[
        "induced_lift_fraction_of_cltot"
    ] == pytest.approx(1.002133)
    assert report.su2_force_breakdown["force_breakdown_marker_owned"] is True
    assert report.su2_force_breakdown["force_breakdown_matches_history_cl"] is True
    assert "reference_normalization_not_primary_cause" in report.engineering_findings
    assert "panel_lift_dominated_by_wake_induced_terms" in report.engineering_findings
    assert "su2_force_breakdown_confirms_main_wing_low_cl" in report.engineering_findings
    assert "su2_wall_bc_is_euler_smoke" in report.engineering_findings
    assert "mesh_quality_pathology_present" in report.engineering_findings
    assert "solver_not_converged" in report.engineering_findings
    assert report.primary_hypotheses[0]["hypothesis"] == (
        "panel_su2_lifting_surface_semantics_or_geometry_mismatch"
    )
    assert report.next_actions[0] == (
        "compare_openvsp_panel_geometry_against_su2_mesh_normals_incidence_and_wake_semantics"
    )


def test_write_main_wing_panel_su2_lift_gap_debug_report(tmp_path: Path):
    out_dir = tmp_path / "debug"

    written = write_main_wing_panel_su2_lift_gap_debug_report(
        out_dir,
        report_root=_fixture_report_root(tmp_path),
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_panel_su2_lift_gap_debug.v1"
    assert payload["debug_status"] == "gap_confirmed_debug_ready"
    assert "Main Wing Panel/SU2 Lift Gap Debug v1" in markdown
