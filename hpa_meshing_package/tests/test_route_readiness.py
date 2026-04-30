import json
from pathlib import Path

from hpa_meshing.route_readiness import (
    build_component_family_route_readiness,
    write_component_family_route_readiness_report,
)


def test_route_readiness_promotes_component_family_architecture_over_root_last3():
    report = build_component_family_route_readiness()

    assert report.target_pipeline == "vsp_or_esp_to_gmsh_to_su2_for_hpa_main_wing_tail_fairing"
    assert report.primary_decision == "switch_to_component_family_route_architecture"
    assert report.shell_v4_policy["role"] == "diagnostic_regression_branch"
    assert report.shell_v4_policy["root_last3_policy"] == "not_a_product_route"
    assert report.gmsh_source_policy["primary_use"] == "forensics_and_instrumentation"
    assert report.gmsh_source_policy["do_not_use_as"] == "primary_product_repair_path"


def test_route_readiness_marks_only_formal_package_line_as_productized():
    report = build_component_family_route_readiness()
    rows = {row.component: row for row in report.components}

    assert rows["aircraft_assembly"].productization_status == "formal_v1"
    assert rows["aircraft_assembly"].route_role == "current_product_line"
    assert rows["aircraft_assembly"].su2_status == "baseline_productized"

    for component in [
        "main_wing",
        "tail_wing",
        "horizontal_tail",
        "vertical_tail",
        "fairing_solid",
        "fairing_vented",
    ]:
        assert rows[component].productization_status != "formal_v1"
        assert rows[component].su2_status != "baseline_productized"


def test_route_readiness_keeps_shell_v4_bl_as_promotion_only():
    report = build_component_family_route_readiness()
    main_wing = {row.component: row for row in report.components}["main_wing"]

    assert main_wing.geometry_family == "thin_sheet_lifting_surface"
    assert main_wing.default_route == "gmsh_thin_sheet_surface"
    assert main_wing.route_role == "experimental_and_diagnostic"
    assert main_wing.su2_status == "handoff_materialized_force_marker_owned_solver_not_run"
    assert main_wing.bl_contract_policy == "promotion_only_when_hpa_mdo_owns_handoff_topology"
    assert main_wing.gmsh_boundary_recovery_policy == "not_allowed_as_owned_boundary_handoff"
    assert "shell_v4_root_last3_is_not_product_route" in main_wing.blocking_reasons
    assert "explicit_bl_to_core_handoff_topology_not_owned" in main_wing.blocking_reasons
    assert "main_wing_component_specific_force_marker_missing" not in main_wing.blocking_reasons
    assert "main_wing_real_geometry_smoke_missing" in main_wing.blocking_reasons
    assert "main_wing_solver_not_run" in main_wing.blocking_reasons
    assert "main_wing_mesh_handoff_smoke_available_non_bl_synthetic" in main_wing.notes
    assert "main_wing_su2_handoff_materialization_smoke_available" in main_wing.notes
    assert "main_wing_component_specific_force_marker_available" in main_wing.notes


def test_route_readiness_marks_fairing_solid_mesh_handoff_smoke_as_available_not_productized():
    report = build_component_family_route_readiness()
    fairing_solid = {row.component: row for row in report.components}["fairing_solid"]

    assert fairing_solid.productization_status == "registered_not_productized"
    assert fairing_solid.su2_status == "handoff_materialized_force_marker_owned_solver_not_run"
    assert fairing_solid.default_route == "gmsh_closed_solid_volume"
    assert "fairing_solid_mesh_handoff_smoke_available" in fairing_solid.notes
    assert "fairing_component_specific_force_marker_available_in_mesh_handoff_smoke" in fairing_solid.notes
    assert "su2_backend_materializes_fairing_solid_marker_without_running_su2" in fairing_solid.notes
    assert "fairing_solid_su2_handoff_materialization_smoke_available" in fairing_solid.notes
    assert "fairing_su2_handoff_artifact_missing" not in fairing_solid.blocking_reasons
    assert "fairing_real_geometry_smoke_missing" in fairing_solid.blocking_reasons
    assert "fairing_solver_not_run" in fairing_solid.blocking_reasons
    assert "convergence_gate_not_run" in fairing_solid.blocking_reasons


def test_route_readiness_marks_tail_wing_mesh_handoff_smoke_as_available_not_productized():
    report = build_component_family_route_readiness()
    tail_wing = {row.component: row for row in report.components}["tail_wing"]

    assert tail_wing.productization_status == "registered_not_productized"
    assert tail_wing.su2_status == "blocked_until_su2_handoff"
    assert tail_wing.default_route == "gmsh_thin_sheet_surface"
    assert "tail_wing_mesh_handoff_smoke_available_non_bl_synthetic" in tail_wing.notes
    assert "tail_wing_specific_force_marker_available" in tail_wing.notes
    assert "tail_family_backend_not_productized" not in tail_wing.blocking_reasons
    assert "tail_real_geometry_smoke_missing" in tail_wing.blocking_reasons
    assert "tail_wing_su2_handoff_not_run" in tail_wing.blocking_reasons
    assert "convergence_gate_not_run" in tail_wing.blocking_reasons


def test_route_readiness_report_writer_outputs_json_and_markdown(tmp_path: Path):
    out_dir = tmp_path / "readiness"

    paths = write_component_family_route_readiness_report(out_dir)

    assert set(paths) == {"json", "markdown"}
    assert paths["json"].name == "component_family_route_readiness.v1.json"
    assert paths["markdown"].name == "component_family_route_readiness.v1.md"
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["primary_decision"] == "switch_to_component_family_route_architecture"
    assert "main_wing" in markdown
    assert "shell_v4" in markdown
    assert "Gmsh" in markdown
