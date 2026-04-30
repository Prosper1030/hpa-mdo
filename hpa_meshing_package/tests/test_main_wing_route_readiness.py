import json
from pathlib import Path

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
            "blocking_reasons": [
                "solver_executed_but_not_converged",
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    assert report.overall_status == "solver_executed_not_converged"
    assert stages["solver_smoke"].status == "pass"
    assert stages["solver_smoke"].evidence_kind == "real"
    assert stages["solver_smoke"].observed["solver_execution_status"] == "solver_executed"
    assert stages["convergence_gate"].status == "blocked"
    assert stages["convergence_gate"].observed["convergence_gate_status"] == "fail"
    assert "solver_executed_but_not_converged" in report.blocking_reasons
    assert "main_wing_solver_not_run" not in report.blocking_reasons
    assert report.next_actions[0] == "diagnose_main_wing_solver_nonconvergence_before_cfd_claims"
    assert "run_bounded_main_wing_iteration_sweep_after_reference_gate_is_clean" in report.next_actions


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
