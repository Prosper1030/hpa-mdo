import json
from pathlib import Path

import pytest

from hpa_meshing.main_wing_surface_force_output_audit import (
    build_main_wing_surface_force_output_audit_report,
    write_main_wing_surface_force_output_audit_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_solver_fixture(tmp_path: Path, *, retain_surface_outputs: bool = False) -> Path:
    report_root = tmp_path / "docs" / "reports"
    solver_dir = report_root / "main_wing_openvsp_reference_solver_smoke_probe_iter80"
    raw_dir = solver_dir / "artifacts" / "raw_solver"
    raw_dir.mkdir(parents=True, exist_ok=True)
    if retain_surface_outputs:
        (raw_dir / "surface.csv").write_text("PointID,Pressure\n1,0.0\n", encoding="utf-8")
        (raw_dir / "forces_breakdown.dat").write_text(
            "\n".join(
                [
                    "Forces breakdown:",
                    "Total CL:       0.263162 | Pressure (   99%):    0.263162",
                    "Total CD:       0.024969 | Pressure (   99%):    0.024969",
                    "Total CMy:     -0.209680 | Pressure (  100%):   -0.209680",
                    "",
                    "Surface name: main_wing",
                    "",
                    "Total CL    (   99%):    0.263162 | Pressure (   99%):    0.263162",
                    "Total CD    (   99%):    0.024969 | Pressure (   99%):    0.024969",
                    "Total CMy   (  100%):   -0.209680 | Pressure (  100%):   -0.209680",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    solver_log = raw_dir / "solver.log"
    solver_log.write_text(
        "\n".join(
            [
                "Forces breakdown file name: forces_breakdown.dat.",
                "Surface file name: surface.",
                "|CSV file                           |surface.csv                        |",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_json(
        solver_dir / "main_wing_real_solver_smoke_probe.v1.json",
        {
            "schema_version": "main_wing_real_solver_smoke_probe.v1",
            "solver_execution_status": "solver_executed",
            "run_status": "solver_executed_but_not_converged",
            "convergence_gate_status": "warn",
            "observed_velocity_mps": 6.5,
            "runtime_max_iterations": 80,
            "final_iteration": 79,
            "final_coefficients": {"cl": 0.263161913, "cd": 0.02496911575},
            "solver_log_path": str(tmp_path / "runtime" / "solver.log"),
            "pruned_output_paths": [
                str(tmp_path / "runtime" / "restart.csv"),
                str(tmp_path / "runtime" / "surface.csv"),
                str(tmp_path / "runtime" / "vol_solution.vtk"),
            ],
        },
    )
    _write_json(
        report_root
        / "main_wing_vspaero_panel_reference_probe"
        / "main_wing_vspaero_panel_reference_probe.v1.json",
        {
            "schema_version": "main_wing_vspaero_panel_reference_probe.v1",
            "panel_reference_status": "panel_reference_available",
            "selected_case": {
                "CLtot": 1.287645495943,
                "CDtot": 0.045068093845,
                "AoA": 0.0,
            },
            "setup_reference": {
                "Vinf": 6.5,
                "Sref": 35.175,
                "Cref": 1.0425,
            },
            "su2_smoke_comparison": {
                "status": "available",
                "panel_reference_cl": 1.287645495943,
                "selected_su2_smoke_cl": 0.263161913,
                "panel_to_su2_cl_ratio": 4.892978171742504,
            },
        },
    )
    return report_root


def test_surface_force_output_audit_blocks_when_expected_outputs_were_pruned(
    tmp_path: Path,
):
    report_root = _write_solver_fixture(tmp_path)

    report = build_main_wing_surface_force_output_audit_report(report_root=report_root)

    assert report.audit_status == "blocked"
    assert report.expected_outputs_from_log["surface_csv"] == "surface.csv"
    assert report.expected_outputs_from_log["forces_breakdown"] == "forces_breakdown.dat"
    assert report.checks["surface_csv_retained"]["status"] == "blocked"
    assert report.checks["forces_breakdown_retained"]["status"] == "blocked"
    assert report.checks["panel_force_comparison_ready"]["status"] == "blocked"
    assert "surface_force_output_pruned_or_missing" in report.blocking_reasons
    assert "forces_breakdown_output_missing" in report.blocking_reasons
    assert "panel_force_comparison_not_ready" in report.blocking_reasons
    assert report.panel_reference_observed["panel_reference_cl"] == 1.287645495943
    assert report.solver_execution_observed["observed_velocity_mps"] == 6.5
    assert report.solver_execution_observed["main_wing_lift_acceptance_status"] == "fail"


def test_surface_force_output_audit_passes_when_committed_surface_outputs_exist(
    tmp_path: Path,
):
    report_root = _write_solver_fixture(tmp_path, retain_surface_outputs=True)

    report = build_main_wing_surface_force_output_audit_report(report_root=report_root)

    assert report.audit_status == "warn"
    assert report.checks["surface_csv_retained"]["status"] == "pass"
    assert report.checks["forces_breakdown_retained"]["status"] == "pass"
    assert report.checks["panel_force_comparison_ready"]["status"] == "pass"
    assert report.checks["forces_breakdown_marker_owned"]["status"] == "pass"
    assert report.checks["forces_breakdown_matches_history_cl"]["status"] == "pass"
    assert report.force_breakdown_observed["surface_names"] == ["main_wing"]
    assert report.force_breakdown_observed["total_coefficients"]["cl"] == pytest.approx(
        0.263162
    )
    assert report.force_breakdown_observed["surface_coefficients"]["main_wing"][
        "cl"
    ] == pytest.approx(0.263162)
    assert report.force_breakdown_observed["history_cl_delta_abs"] < 1e-6
    assert report.force_breakdown_observed[
        "panel_to_force_breakdown_cl_ratio"
    ] == pytest.approx(4.892976554733587)
    assert "forces_breakdown_cl_below_panel_reference" in report.engineering_flags
    assert not report.blocking_reasons
    assert "debug_panel_su2_lift_gap_from_retained_force_breakdown" in report.next_actions


def test_write_main_wing_surface_force_output_audit_report(tmp_path: Path):
    report_root = _write_solver_fixture(tmp_path)
    out_dir = tmp_path / "audit"

    written = write_main_wing_surface_force_output_audit_report(
        out_dir,
        report_root=report_root,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_surface_force_output_audit.v1"
    assert payload["audit_status"] == "blocked"
    assert "Main Wing Surface Force Output Audit v1" in markdown
