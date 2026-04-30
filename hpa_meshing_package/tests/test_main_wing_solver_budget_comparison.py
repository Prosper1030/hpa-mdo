import json
from pathlib import Path

from hpa_meshing.main_wing_solver_budget_comparison import (
    build_main_wing_solver_budget_comparison_report,
    write_main_wing_solver_budget_comparison_report,
)


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_solver_fixture(
    root: Path,
    directory: str,
    *,
    iterations: int,
    reference_path_token: str,
    convergence_gate_status: str = "warn",
    residual_drop: float = 0.36,
    coefficient_status: str = "pass",
    velocity_mps: float = 6.5,
    include_quality: bool = False,
):
    report_path = root / directory / "main_wing_real_solver_smoke_probe.v1.json"
    gate_path = root / directory / "artifacts" / "convergence_gate.v1.json"
    _write_json(
        gate_path,
        {
            "iterative_gate": {
                "checks": {
                    "residual_trend": {
                        "status": "warn",
                        "observed": {"median_log_drop": residual_drop},
                    },
                    "coefficient_stability": {
                        "status": coefficient_status,
                        "observed": {
                            "cl": {"status": "pass"},
                            "cd": {"status": "pass"},
                            "cm": {"status": "pass"},
                        },
                    },
                }
            },
            "overall_convergence_gate": {
                "warnings": ["iterative_gate=warn", "reference_gate=warn"],
            },
        },
    )
    payload = {
        "source_su2_probe_path": reference_path_token,
        "solver_execution_status": "solver_executed",
        "run_status": "solver_executed_but_not_converged",
        "convergence_gate_status": convergence_gate_status,
        "convergence_comparability_level": "run_only",
        "reference_geometry_status": "warn",
        "observed_velocity_mps": velocity_mps,
        "runtime_max_iterations": iterations,
        "final_iteration": iterations - 1,
        "final_coefficients": {
            "cl": 0.26 + iterations * 1.0e-5,
            "cd": 0.025,
            "cm": -0.21,
            "cm_axis": "CMy",
        },
        "convergence_gate_path": str(gate_path),
    }
    if include_quality:
        payload["solver_log_quality_metrics"] = {
            "dual_control_volume_quality": {
                "cv_face_area_aspect_ratio": {"max": 377.909},
                "cv_sub_volume_ratio": {"max": 13256.1},
            }
        }
    _write_json(report_path, payload)


def test_solver_budget_comparison_summarizes_openvsp_current_route(tmp_path: Path):
    root = tmp_path / "reports"
    _write_solver_fixture(
        root,
        "main_wing_real_solver_smoke_probe",
        iterations=12,
        reference_path_token="declared_blackcat_full_span",
    )
    _write_solver_fixture(
        root,
        "main_wing_openvsp_reference_solver_smoke_probe",
        iterations=12,
        reference_path_token="main_wing_openvsp_reference_su2_handoff_probe",
    )
    _write_solver_fixture(
        root,
        "main_wing_openvsp_reference_solver_smoke_probe_iter80",
        iterations=80,
        reference_path_token="main_wing_openvsp_reference_su2_handoff_probe_iter80",
        include_quality=True,
    )

    report = build_main_wing_solver_budget_comparison_report(report_root=root)

    assert report.schema_version == "main_wing_solver_budget_comparison.v1"
    assert report.report_status == "solver_budget_nonconverged"
    assert report.hpa_standard_flow_status == "hpa_standard_6p5_observed"
    assert len(report.rows) == 3
    assert report.current_route_row["reference_policy"] == "openvsp_geometry_derived"
    assert report.current_route_row["runtime_max_iterations"] == 80
    assert report.current_route_row["residual_median_log_drop"] == 0.36
    assert "residual_drop_below_threshold" in report.current_route_row["advisory_flags"]
    assert (
        "mesh_quality_cv_sub_volume_ratio_high"
        in report.current_route_row["advisory_flags"]
    )
    assert (
        "inspect_main_wing_mesh_quality_before_more_iterations"
        in report.next_actions
    )


def test_solver_budget_comparison_detects_nonstandard_flow(tmp_path: Path):
    root = tmp_path / "reports"
    _write_solver_fixture(
        root,
        "main_wing_real_solver_smoke_probe",
        iterations=12,
        reference_path_token="declared_blackcat_full_span",
        velocity_mps=10.0,
    )

    report = build_main_wing_solver_budget_comparison_report(report_root=root)

    assert report.hpa_standard_flow_status == "mixed_or_nonstandard_velocity_observed"
    assert report.rows[0].observed_velocity_mps == 10.0


def test_solver_budget_comparison_writer_outputs_json_and_markdown(tmp_path: Path):
    root = tmp_path / "reports"
    out_dir = tmp_path / "out"
    _write_solver_fixture(
        root,
        "main_wing_openvsp_reference_solver_smoke_probe_iter80",
        iterations=80,
        reference_path_token="main_wing_openvsp_reference_su2_handoff_probe_iter80",
        include_quality=True,
    )

    paths = write_main_wing_solver_budget_comparison_report(
        out_dir,
        report=build_main_wing_solver_budget_comparison_report(report_root=root),
    )

    assert paths["json"].name == "main_wing_solver_budget_comparison.v1.json"
    assert paths["markdown"].name == "main_wing_solver_budget_comparison.v1.md"
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["current_route_row"]["runtime_max_iterations"] == 80
    assert "main_wing_openvsp_reference_solver_smoke_probe_iter80" in paths[
        "markdown"
    ].read_text(
        encoding="utf-8"
    )
