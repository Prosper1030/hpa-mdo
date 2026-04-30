import json
from pathlib import Path

from hpa_meshing.component_family_smoke_matrix import (
    build_component_family_route_smoke_matrix,
    write_component_family_route_smoke_matrix_report,
)


def test_component_family_route_smoke_is_pre_mesh_and_not_root_last3(tmp_path: Path):
    report = build_component_family_route_smoke_matrix(tmp_path / "smoke")

    assert report.schema_version == "component_family_route_smoke_matrix.v1"
    assert report.execution_mode == "pre_mesh_dispatch_smoke"
    assert report.no_gmsh_execution is True
    assert report.no_su2_execution is True
    assert report.scope_policy["root_last3_policy"] == "excluded_not_product_route"
    assert report.scope_policy["bl_runtime_policy"] == "not_executed"


def test_component_family_route_smoke_covers_main_wing_tail_and_fairing(tmp_path: Path):
    report = build_component_family_route_smoke_matrix(tmp_path / "smoke")
    rows = {row.component: row for row in report.rows}

    for component in [
        "main_wing",
        "tail_wing",
        "horizontal_tail",
        "vertical_tail",
        "fairing_solid",
        "fairing_vented",
    ]:
        row = rows[component]
        assert row.smoke_status == "dispatch_smoke_pass"
        assert row.validation_status == "pass"
        assert row.recipe_status == "resolved"
        assert row.mesh_handoff_status == "not_run"
        assert row.su2_handoff_status == "not_run"

    assert rows["main_wing"].meshing_route == "gmsh_thin_sheet_surface"
    assert rows["tail_wing"].meshing_route == "gmsh_thin_sheet_surface"
    assert rows["fairing_solid"].meshing_route == "gmsh_closed_solid_volume"
    assert rows["fairing_vented"].meshing_route == "gmsh_perforated_solid_volume"


def test_component_family_route_smoke_keeps_productization_status_visible(tmp_path: Path):
    report = build_component_family_route_smoke_matrix(tmp_path / "smoke")
    rows = {row.component: row for row in report.rows}

    assert rows["main_wing"].productization_status == "experimental"
    assert rows["main_wing"].promotion_status == "blocked_before_solver_convergence"
    assert "explicit_bl_to_core_handoff_topology_not_owned" in rows["main_wing"].blocking_reasons
    assert "main_wing_component_specific_force_marker_missing" not in rows["main_wing"].blocking_reasons
    assert "main_wing_real_geometry_smoke_missing" not in rows["main_wing"].blocking_reasons
    assert "main_wing_real_geometry_mesh_handoff_not_run" not in rows["main_wing"].blocking_reasons
    assert "main_wing_real_geometry_mesh_handoff_timeout" in rows["main_wing"].blocking_reasons
    assert (
        "main_wing_real_geometry_mesh3d_volume_insertion_timeout"
        in rows["main_wing"].blocking_reasons
    )
    assert rows["fairing_solid"].productization_status == "registered_not_productized"
    assert rows["fairing_solid"].promotion_status == "blocked_before_solver_convergence"
    assert "fairing_su2_handoff_artifact_missing" not in rows["fairing_solid"].blocking_reasons
    assert "fairing_real_geometry_smoke_missing" not in rows["fairing_solid"].blocking_reasons
    assert "fairing_real_geometry_mesh_handoff_not_run" not in rows["fairing_solid"].blocking_reasons
    assert "fairing_real_geometry_su2_handoff_not_run" not in rows["fairing_solid"].blocking_reasons
    assert "fairing_real_reference_policy_mismatch_observed" not in rows["fairing_solid"].blocking_reasons
    assert (
        "fairing_moment_origin_policy_incomplete_for_moment_coefficients"
        in rows["fairing_solid"].blocking_reasons
    )
    assert rows["tail_wing"].promotion_status == "blocked_before_solver_convergence"
    assert "tail_family_backend_not_productized" not in rows["tail_wing"].blocking_reasons
    assert "tail_wing_su2_handoff_not_run" not in rows["tail_wing"].blocking_reasons
    assert "tail_real_geometry_smoke_missing" not in rows["tail_wing"].blocking_reasons
    assert "tail_real_geometry_mesh_handoff_not_run" not in rows["tail_wing"].blocking_reasons
    assert "tail_real_geometry_mesh_handoff_blocked_surface_only" in rows["tail_wing"].blocking_reasons
    assert "tail_naive_gmsh_heal_solidification_no_volume" in rows["tail_wing"].blocking_reasons
    assert (
        "tail_explicit_volume_route_blocked_by_orientation_or_baffle_plc"
        in rows["tail_wing"].blocking_reasons
    )
    assert "tail_surface_only_mesh_not_su2_volume_handoff" in rows["tail_wing"].blocking_reasons
    assert "tail_wing_solver_not_run" in rows["tail_wing"].blocking_reasons


def test_component_family_route_smoke_report_writer_outputs_json_markdown_and_fixtures(tmp_path: Path):
    out_dir = tmp_path / "route-smoke"

    paths = write_component_family_route_smoke_matrix_report(out_dir)

    assert set(paths) == {"json", "markdown"}
    assert paths["json"].name == "component_family_route_smoke_matrix.v1.json"
    assert paths["markdown"].name == "component_family_route_smoke_matrix.v1.md"
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["execution_mode"] == "pre_mesh_dispatch_smoke"
    assert payload["no_gmsh_execution"] is True
    assert len(payload["rows"]) >= 6
    assert "pre-mesh dispatch smoke" in markdown
    assert (out_dir / "artifacts" / "fixtures" / "main_wing.step").exists()
