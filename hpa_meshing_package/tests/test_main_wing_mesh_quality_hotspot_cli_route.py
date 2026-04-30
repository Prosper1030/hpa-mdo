import json
from pathlib import Path

from hpa_meshing.cli import build_parser
from hpa_meshing.main_wing_route_readiness import build_main_wing_route_readiness_report


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _fixture_report_root(tmp_path: Path) -> Path:
    root = tmp_path / "reports"
    _write_json(
        root
        / "main_wing_esp_rebuilt_geometry_smoke"
        / "main_wing_esp_rebuilt_geometry_smoke.v1.json",
        {"geometry_status": "pass", "blocking_reasons": []},
    )
    _write_json(
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json",
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "mesh_quality_status": "warn",
            "mesh_quality_metrics": {"ill_shaped_tet_count": 3, "min_gamma": 1.0e-6},
            "mesh_quality_advisory_flags": ["gmsh_ill_shaped_tets_present"],
            "blocking_reasons": [],
        },
    )
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
    return root


def test_parser_supports_main_wing_mesh_quality_hotspot_audit_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-mesh-quality-hotspot-audit",
            "--out",
            "artifacts/main_wing_mesh_quality_hotspot_audit",
            "--mesh-handoff-report",
            "artifacts/main_wing/mesh_handoff.json",
            "--mesh-metadata",
            "artifacts/main_wing/mesh_metadata.json",
            "--hotspot-patch-report",
            "artifacts/main_wing/hotspot_patch_report.json",
            "--surface-patch-diagnostics",
            "artifacts/main_wing/surface_patch_diagnostics.json",
            "--gmsh-defect-entity-trace",
            "artifacts/main_wing/entity_trace.json",
        ]
    )

    assert args.command == "main-wing-mesh-quality-hotspot-audit"
    assert args.out == "artifacts/main_wing_mesh_quality_hotspot_audit"
    assert args.mesh_handoff_report == "artifacts/main_wing/mesh_handoff.json"
    assert args.mesh_metadata == "artifacts/main_wing/mesh_metadata.json"
    assert args.hotspot_patch_report == "artifacts/main_wing/hotspot_patch_report.json"
    assert args.surface_patch_diagnostics == (
        "artifacts/main_wing/surface_patch_diagnostics.json"
    )
    assert args.gmsh_defect_entity_trace == "artifacts/main_wing/entity_trace.json"


def test_main_wing_route_readiness_records_mesh_quality_hotspot_stage(
    tmp_path: Path,
):
    root = _fixture_report_root(tmp_path)
    _write_json(
        root
        / "main_wing_mesh_quality_hotspot_audit"
        / "main_wing_mesh_quality_hotspot_audit.v1.json",
        {
            "hotspot_status": "mesh_quality_hotspots_localized",
            "quality_summary": {"ill_shaped_tet_count": 3, "min_gamma": 1.0e-6},
            "worst_tet_sample_partition": {
                "by_nearest_physical_name": {"farfield": 1, "main_wing": 2},
            },
            "station_seam_overlap_observed": {"overlap_surface_tags": [19]},
            "engineering_findings": [
                "main_wing_near_surface_quality_hotspots_present",
                "main_wing_quality_hotspot_overlaps_station_seam_trace",
            ],
            "next_actions": [
                "repair_station_seam_export_before_solver_iteration_budget"
            ],
            "blocking_reasons": [],
        },
    )

    report = build_main_wing_route_readiness_report(report_root=root)

    stages = {stage.stage: stage for stage in report.stages}
    quality_stage = stages["mesh_quality_hotspot_audit"]
    assert quality_stage.status == "pass"
    assert quality_stage.evidence_kind == "real"
    assert quality_stage.observed["quality_summary"]["ill_shaped_tet_count"] == 3
    assert quality_stage.observed["station_seam_overlap_observed"][
        "overlap_surface_tags"
    ] == [19]
