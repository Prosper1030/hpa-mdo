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
