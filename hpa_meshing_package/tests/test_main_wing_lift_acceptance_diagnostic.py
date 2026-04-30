import json
from pathlib import Path

import pytest

from hpa_meshing.main_wing_lift_acceptance_diagnostic import (
    build_main_wing_lift_acceptance_diagnostic_report,
    write_main_wing_lift_acceptance_diagnostic_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_solver_fixture(
    tmp_path: Path,
    *,
    cl: float = 0.263161913,
    velocity_mps: float = 6.5,
    alpha_deg: float = 0.0,
    convergence_gate_status: str = "warn",
) -> Path:
    report_root = tmp_path / "docs" / "reports"
    handoff_path = tmp_path / "artifacts" / "su2_handoff.json"
    _write_json(
        handoff_path,
        {
            "runtime": {
                "alpha_deg": alpha_deg,
                "velocity_mps": velocity_mps,
                "density_kgpm3": 1.225,
                "flow_conditions": {
                    "velocity_mps": velocity_mps,
                    "density_kgpm3": 1.225,
                    "source_label": "hpa_standard_6p5_mps",
                },
            },
            "reference_geometry": {
                "ref_area": 35.175,
                "ref_length": 1.0425,
            },
        },
    )
    _write_json(
        report_root
        / "main_wing_openvsp_reference_solver_smoke_probe_iter80"
        / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "solver_execution_status": "solver_executed",
            "run_status": "solver_executed_but_not_converged",
            "convergence_gate_status": convergence_gate_status,
            "convergence_comparability_level": "run_only",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": velocity_mps,
            "runtime_max_iterations": 80,
            "final_iteration": 79,
            "final_coefficients": {"cl": cl, "cd": 0.0249, "cm": -0.209},
            "su2_handoff_path": str(handoff_path),
            "solver_log_quality_metrics": {
                "dual_control_volume_quality": {
                    "cv_sub_volume_ratio": {"max": 13256.1},
                    "cv_face_area_aspect_ratio": {"max": 377.9},
                }
            },
        },
    )
    _write_json(
        report_root
        / "main_wing_reference_geometry_gate"
        / "main_wing_reference_geometry_gate.v1.json",
        {
            "checks": {
                "applied_ref_area_vs_openvsp_sref": {
                    "observed": {"relative_error": 0.01492537313432832}
                }
            }
        },
    )
    _write_json(
        report_root
        / "main_wing_vspaero_panel_reference_probe"
        / "main_wing_vspaero_panel_reference_probe.v1.json",
        {
            "panel_reference_status": "panel_reference_available",
            "lift_acceptance_status": "pass",
            "selected_case": {
                "AoA": alpha_deg,
                "CLtot": 1.287645495943,
                "CDtot": 0.045068093845,
            },
            "setup_reference": {"Vinf": velocity_mps},
        },
    )
    return report_root


def test_main_wing_lift_acceptance_diagnostic_reports_low_cl_alpha_zero(
    tmp_path: Path,
):
    report_root = _write_solver_fixture(tmp_path)

    report = build_main_wing_lift_acceptance_diagnostic_report(
        report_root=report_root
    )

    assert report.diagnostic_status == "lift_deficit_observed"
    assert "main_wing_cl_below_expected_lift" in report.engineering_flags
    assert "alpha_zero_operating_lift_not_demonstrated" in report.engineering_flags
    assert "reference_geometry_warn" in report.engineering_flags
    assert "mesh_quality_warning_present" in report.engineering_flags
    assert (
        "reference_area_delta_too_small_to_explain_lift_deficit"
        in report.engineering_flags
    )
    assert report.flow_condition_observed["velocity_mps"] == 6.5
    assert report.flow_condition_observed["alpha_deg"] == 0.0
    assert report.lift_metrics["dynamic_pressure_pa"] == pytest.approx(25.878125)
    assert report.lift_metrics["observed_cl_to_minimum_ratio"] == pytest.approx(
        0.263161913
    )
    assert report.panel_reference_observed["cltot"] == pytest.approx(1.287645495943)
    assert report.lift_gap_diagnostics["panel_vs_su2_status"] == (
        "panel_supports_expected_lift_su2_low"
    )
    assert report.lift_gap_diagnostics["panel_to_su2_cl_ratio"] == pytest.approx(
        4.892978171742504
    )
    assert "vspaero_panel_cl_gt_one_while_su2_low" in report.engineering_flags
    assert report.root_cause_candidates[0]["candidate"] == (
        "su2_route_lift_deficit_not_explained_by_operating_alpha_alone"
    )
    assert report.next_actions[0] == (
        "run_bounded_main_wing_alpha_trim_sanity_probe_without_changing_default"
    )
    assert "audit_su2_force_markers_bc_and_reference_against_vspaero_panel" in (
        report.next_actions
    )


def test_main_wing_lift_acceptance_diagnostic_passes_only_when_cl_above_one_and_gate_passes(
    tmp_path: Path,
):
    report_root = _write_solver_fixture(
        tmp_path,
        cl=1.08,
        convergence_gate_status="pass",
    )

    report = build_main_wing_lift_acceptance_diagnostic_report(
        report_root=report_root
    )

    assert report.diagnostic_status == "lift_acceptance_passed"
    assert "main_wing_cl_below_expected_lift" not in report.engineering_flags
    assert report.lift_metrics["observed_lift_n"] > report.lift_metrics[
        "lift_at_minimum_acceptable_cl_n"
    ]


def test_write_main_wing_lift_acceptance_diagnostic_report(tmp_path: Path):
    report_root = _write_solver_fixture(tmp_path)
    out_dir = tmp_path / "diagnostic"

    written = write_main_wing_lift_acceptance_diagnostic_report(
        out_dir,
        report_root=report_root,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_lift_acceptance_diagnostic.v1"
    assert payload["diagnostic_status"] == "lift_deficit_observed"
    assert payload["lift_gap_diagnostics"]["panel_vs_su2_status"] == (
        "panel_supports_expected_lift_su2_low"
    )
    assert "Main Wing Lift Acceptance Diagnostic v1" in markdown
    assert "Panel Reference" in markdown
    assert "Root Cause Candidates" in markdown
