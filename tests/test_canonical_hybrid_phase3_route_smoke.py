from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_canonical_hybrid_phase3_route_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_canonical_hybrid_phase3_route_smoke",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _passing_report(module):
    return {
        "mesh": {
            "status": "meshed",
            "marker_audit": {"status": "pass"},
            "mesh_quality_gate": {"status": "pass"},
            "required_markers_present": True,
            "volume_element_type_counts": {
                module.GMSH_TETRA: 400,
                module.GMSH_PRISM: 240,
            },
            "volume_element_count": 640,
            "boundary_layer_cell_count": 240,
            "max_farfield_vertex_incident_volume_cells": 4,
        },
        "solver": {
            "run_status": "completed",
            "dual_control_volume_quality": {
                "status": "available",
                "min_orthogonality_deg": 8.0,
                "max_cv_face_area_aspect_ratio": 2.5e5,
                "max_cv_sub_volume_ratio": 4.0e6,
            },
            "history": {
                "row_count": 220,
                "tail_stability": {
                    "cl_relative_span": 0.01,
                    "cd_relative_span": 0.01,
                },
            },
        },
        "forces_breakdown": {"status": "available"},
        "primary_force_coefficients": {
            "cl": 0.45,
            "cd": 0.035,
            "pressure_cd": 0.018,
            "viscous_cd": 0.017,
        },
        "diagnostic_force_coefficients": {
            "tip_wall": {"cd": 0.004},
            "te_wall": {"cd": 0.002},
            "closure_wall": {"cd": 0.001},
        },
    }


def test_route_smoke_surface_preserves_marker_split_and_hybrid_policy_metadata() -> None:
    module = _load_module()

    surface = module.build_phase3_route_smoke_surface(
        module.DEFAULT_SECTION_TABLE_PATH,
        points_per_side=6,
        spanwise_subdivisions=1,
    )
    counts = surface.marker_counts()

    assert counts["wing_upper"] > 0
    assert counts["wing_lower"] > 0
    assert counts["tip_wall"] > 0
    assert counts["te_wall"] > 0
    assert counts["closure_wall"] > 0
    assert surface.metadata["phase_gate"] == "ROUTE_SMOKE_PASS"
    assert "prism/hexa BL" in surface.metadata["mesh_recipe"]
    assert surface.metadata["primary_force_markers"] == ["wing_upper", "wing_lower"]


def test_route_smoke_config_uses_rans_sa_no_slip_and_split_force_markers() -> None:
    module = _load_module()

    cfg = module.route_smoke_cfg_text(
        ref_area=16.710029799,
        ref_length=1.003721543,
        ref_origin=(0.246276512, 0.0, 0.0),
        velocity_mps=6.5,
        alpha_deg=0.0,
        max_iterations=100,
    )

    assert "SOLVER= INC_RANS" in cfg
    assert "KIND_TURB_MODEL= SA" in cfg
    assert (
        "MARKER_HEATFLUX= ( wing_upper, 0.0, wing_lower, 0.0, tip_wall, 0.0, "
        "te_wall, 0.0, closure_wall, 0.0 )"
    ) in cfg
    assert "MARKER_SYM= ( root_symmetry )" in cfg
    assert "MARKER_FAR= ( farfield )" in cfg
    assert "MARKER_MONITORING= ( wing_upper, wing_lower, tip_wall, te_wall, closure_wall )" in cfg
    assert "AOA= 0.000000" in cfg
    assert "WRT_FORCES_BREAKDOWN= YES" in cfg


def test_route_smoke_gate_requires_hybrid_bl_cells_and_core_tets() -> None:
    module = _load_module()
    passing = module.evaluate_phase3_route_smoke_gate(_passing_report(module))
    all_tet = _passing_report(module)
    all_tet["mesh"]["volume_element_type_counts"] = {
        module.GMSH_TETRA: 640,
    }
    all_tet["mesh"]["boundary_layer_cell_count"] = 0
    failing = module.evaluate_phase3_route_smoke_gate(all_tet)

    assert passing["status"] == "pass"
    assert passing["release_status"] == "ROUTE_SMOKE_PASS"
    assert failing["status"] == "fail"
    assert "route_smoke_hybrid_bl_cells_missing" in failing["blockers"]
    assert "route_smoke_boundary_layer_cells_missing" in failing["blockers"]
    assert "route_smoke_all_tet_mesh_forbidden" in failing["blockers"]


def test_route_smoke_gate_rejects_r28_scale_dual_pathology() -> None:
    module = _load_module()
    report = _passing_report(module)
    report["solver"]["dual_control_volume_quality"] = {
        "status": "available",
        "min_orthogonality_deg": 0.00108069,
        "max_cv_face_area_aspect_ratio": 5.15199e8,
        "max_cv_sub_volume_ratio": 2.07841e11,
    }

    gate = module.evaluate_phase3_route_smoke_gate(report)

    assert gate["status"] == "fail"
    assert "route_smoke_su2_dual_min_orthogonality_pathological" in gate["blockers"]
    assert "route_smoke_su2_dual_face_area_aspect_ratio_pathological" in gate["blockers"]
    assert "route_smoke_su2_dual_sub_volume_ratio_pathological" in gate["blockers"]


def test_route_smoke_gate_rejects_failed_gmsh_extruded_dual_subvolume_scale() -> None:
    module = _load_module()
    report = _passing_report(module)
    report["solver"]["dual_control_volume_quality"] = {
        "status": "available",
        "min_orthogonality_deg": 22.1539,
        "max_cv_face_area_aspect_ratio": 51630.3,
        "max_cv_sub_volume_ratio": 1.81024e8,
    }

    gate = module.evaluate_phase3_route_smoke_gate(report)

    assert gate["status"] == "fail"
    assert "route_smoke_su2_dual_sub_volume_ratio_pathological" in gate["blockers"]


def test_route_smoke_gate_rejects_closure_drag_dominance() -> None:
    module = _load_module()
    report = _passing_report(module)
    report["diagnostic_force_coefficients"]["closure_wall"]["cd"] = 0.08

    gate = module.evaluate_phase3_route_smoke_gate(report)

    assert gate["status"] == "fail"
    assert "route_smoke_closure_cd_dominates" in gate["blockers"]


def test_route_smoke_manifest_update_records_report_path(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "passed_gate_statuses:",
                "- TOOLCHAIN_PASS",
                "- PRESSURE_SANITY_PASS",
                "next_required_gate_status: ROUTE_SMOKE_PASS",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = {
        "report_path": "output/cfd_release_v0/route_smoke/route_smoke_report.json",
        "case_dir": "output/cfd_release_v0/route_smoke",
        "surface": {"metadata": {"mesh_recipe": "hybrid BL + tetra core"}},
    }

    module.mark_manifest_route_smoke_pass(manifest_path, summary)

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["passed_gate_statuses"] == [
        "TOOLCHAIN_PASS",
        "PRESSURE_SANITY_PASS",
        "ROUTE_SMOKE_PASS",
    ]
    assert manifest["next_required_gate_status"] == "GRID_LADDER_PASS"
    assert manifest["phase3_route_smoke"]["status"] == "ROUTE_SMOKE_PASS"
    assert manifest["phase3_route_smoke"]["report_path"] == summary["report_path"]


def test_owned_bl_prism_handoff_writes_prisms_and_split_boundary_markers(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_owned_bl_prism_handoff_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "owned_bl_prism_handoff.su2",
        points_per_side=6,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
    )

    assert report["route"] == "canonical_hybrid_halfwing_owned_bl_prism_handoff"
    assert report["volume_element_type_counts"] == {str(module.SU2_PRISM): 3072}
    assert report["forbidden_route_checks"] == {
        "all_tet_global_star_bl_handoff": False,
        "boundary_layer_split_to_tetra": False,
        "owner_pyramid_as_active_method": False,
    }
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["marker_summary"]["wing_upper"]["element_count"] > 0
    assert report["marker_summary"]["wing_lower"]["element_count"] > 0
    assert report["marker_summary"]["te_wall"]["element_count"] > 0
    assert report["marker_summary"]["closure_wall"]["element_count"] > 0
    assert report["marker_summary"]["tip_wall"]["element_count"] > 0
    assert report["marker_summary"]["root_symmetry"]["element_count"] > 0
    assert report["marker_summary"]["bl_outer_interface"]["element_count"] > 0


def test_direct_surface_prism_handoff_has_triangular_core_interface(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_direct_surface_prism_handoff_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "direct_surface_prism_handoff.su2",
        points_per_side=6,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
    )

    assert report["route"] == "canonical_hybrid_halfwing_direct_surface_prism_handoff"
    assert report["volume_element_type_counts"] == {str(module.SU2_PRISM): 2600}
    assert report["core_tetra_interface"]["status"] == "ready_for_tet_core_boundary"
    assert report["marker_summary"]["bl_outer_interface"]["element_type_counts"] == {
        str(module.SU2_TRIANGLE): 650,
    }
    assert report["marker_area_vectors"]["wing_upper"]["area_vector"][2] > 0.0
    assert report["marker_area_vectors"]["wing_lower"]["area_vector"][2] < 0.0
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["forbidden_route_checks"] == {
        "all_tet_global_star_bl_handoff": False,
        "boundary_layer_split_to_tetra": False,
        "owner_pyramid_as_active_method": False,
    }


def test_direct_surface_prism_handoff_blocks_root_symmetry_sidewall_distortion(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_direct_surface_prism_handoff_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "direct_surface_prism_handoff.su2",
        points_per_side=6,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
    )

    quality = report["direct_prism_quality"]
    gate = report["direct_prism_quality_gate"]

    assert gate["status"] == "fail"
    assert "root_symmetry_sidewall_quad_aspect_ratio_exceeds_1000" in gate["blockers"]
    assert quality["root_symmetry_quad_aspect"]["max"] > 7000.0
    assert quality["root_symmetry_quad_aspect"]["count_over_1000"] > 0
    assert quality["worst_root_symmetry_quad"]["marker"] == "root_symmetry"
    assert min(quality["worst_root_symmetry_quad"]["edge_lengths_m"]) <= 5.1e-5


def test_direct_surface_prism_core_hybrid_writer_merges_interface_without_marker(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_direct_surface_prism_core_hybrid_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "direct_surface_prism_core_hybrid.su2",
        points_per_side=6,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    assert report["route"] == "canonical_hybrid_halfwing_direct_surface_prism_core_hybrid"
    assert report["volume_element_type_counts"][str(module.SU2_PRISM)] == 2600
    assert int(report["volume_element_type_counts"][str(module.SU2_TETRAHEDRON)]) > 0
    assert report["core_report"]["node_tag_integrity"]["status"] == "pass"
    assert report["core_report"]["mesh_sizing"]["gmsh_algorithm3d"] == 1
    assert report["core_report"]["outer_interface_node_count"] > 0
    assert report["marker_area_vectors"]["wing_upper"]["area_vector"][2] > 0.0
    assert report["marker_area_vectors"]["wing_lower"]["area_vector"][2] < 0.0
    assert abs(report["marker_area_vectors"]["farfield"]["area_vector"][2]) < 1.0e-6
    assert report["direct_prism_quality_gate"]["status"] == "fail"
    assert (
        "root_symmetry_sidewall_quad_aspect_ratio_exceeds_1000"
        in report["direct_prism_quality_gate"]["blockers"]
    )
    assert "bl_outer_interface" not in report["marker_summary"]
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["required_markers_present"] is True
    assert report["forbidden_route_checks"] == {
        "all_tet_global_star_bl_handoff": False,
        "boundary_layer_split_to_tetra": False,
        "owner_pyramid_as_active_method": False,
        "closure_faces_merged_into_wing_wall": False,
    }


def test_closed_wall_wrapper_l16_clears_dual_proxy_but_not_root_aspect(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_direct_surface_prism_core_hybrid_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "closed_wall_l16" / "mesh.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=16,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    assert report["dual_subvolume_proxy"]["status"] == "pass"
    assert report["dual_subvolume_proxy"]["max_cv_sub_volume_ratio"] == 0.0
    assert report["direct_prism_quality"]["prism_signed_volume"]["non_positive_count"] == 0
    assert report["direct_prism_quality_gate"]["status"] == "fail"
    assert (
        "root_symmetry_sidewall_quad_aspect_ratio_exceeds_1000"
        in report["direct_prism_quality_gate"]["blockers"]
    )
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_closed_wall_wrapper_pps42_l16_fixes_root_aspect_but_inverts_cap_prisms() -> None:
    module = _load_module()
    surface = module.build_phase3_route_smoke_surface(
        module.DEFAULT_SECTION_TABLE_PATH,
        points_per_side=42,
        spanwise_subdivisions=4,
    )
    volume = module._direct_surface_prism_volume(
        surface.vertices,
        module._triangulated_wall_triangles(surface),
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=16,
    )

    quality = module._direct_prism_quality_metrics(volume)

    assert quality["root_symmetry_quad_aspect"]["max"] < 1000.0
    assert quality["prism_signed_volume"]["non_positive_count"] > 0
    assert quality["prism_signed_volume_by_marker"]["wing_upper"]["non_positive_count"] == 124
    assert quality["prism_signed_volume_by_marker"]["te_wall"]["non_positive_count"] == 121
    assert quality["non_positive_prism_by_layer"]["10"] == 30
    assert quality["non_positive_prism_hotspots"][0]["marker"] in {
        "wing_upper",
        "te_wall",
    }


def test_closed_wall_wrapper_layer_window_probe_records_no_viable_pps42_window(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.run_phase3_closed_wall_wrapper_layer_window_probe(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "closed_wall_layer_window",
        points_per_side=42,
        spanwise_subdivisions=4,
        layer_counts=(6, 7, 16),
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        run_dual_proxy=False,
    )

    by_layer = {row["layers"]: row for row in report["rows"]}

    assert report["status"] == "closed_wall_wrapper_no_simple_layer_window"
    assert by_layer[6]["direct_prism_quality_gate"]["status"] == "pass"
    assert by_layer[6]["dual_subvolume_proxy"]["status"] == "not_run"
    assert by_layer[7]["direct_prism_quality_gate"]["status"] == "fail"
    assert by_layer[7]["direct_prism_quality"]["prism_signed_volume"]["non_positive_count"] == 10
    assert by_layer[16]["direct_prism_quality"]["prism_signed_volume_by_marker"]["wing_upper"]["non_positive_count"] == 124
    assert by_layer[16]["direct_prism_quality"]["prism_signed_volume_by_marker"]["te_wall"]["non_positive_count"] == 121
    assert report["engineering_assessment"]["route_smoke_ready"] is False
    assert Path(report["report_path"]).exists()


def test_closed_wall_te_stageback_probe_reduces_aft_prism_inversion(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.run_phase3_closed_wall_te_stageback_layer_probe(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "closed_wall_te_stageback",
        points_per_side=42,
        spanwise_subdivisions=4,
        full_wall_layers=16,
        cap_layers=6,
        stageback_segments=(0, 6),
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
    )

    by_stageback = {row["stageback_segments"]: row for row in report["rows"]}

    assert report["status"] == "closed_wall_te_stageback_probe_completed"
    assert by_stageback[0]["direct_prism_quality"]["prism_signed_volume"]["non_positive_count"] > 0
    assert (
        by_stageback[6]["direct_prism_quality"]["prism_signed_volume"]["non_positive_count"]
        < by_stageback[0]["direct_prism_quality"]["prism_signed_volume"]["non_positive_count"]
    )
    assert by_stageback[6]["direct_prism_quality_gate"]["status"] == "pass"
    assert by_stageback[6]["direct_prism_quality"]["prism_signed_volume"]["non_positive_count"] == 0
    assert by_stageback[6]["stageback_primary_triangle_count"] > 0
    assert by_stageback[6]["termination_interface_quad_count"] > 0
    assert report["engineering_assessment"]["route_smoke_ready"] is False
    assert Path(report["report_path"]).exists()


def test_closed_wall_te_stageback_core_hybrid_writer_hides_internal_interfaces(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_closed_wall_te_stageback_core_hybrid_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "closed_wall_te_stageback_core.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        full_wall_layers=8,
        cap_layers=3,
        stageback_segments=2,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    assert report["status"] == "closed_wall_te_stageback_core_hybrid_written"
    assert report["direct_prism_quality"]["prism_signed_volume"]["non_positive_count"] == 0
    assert report["direct_prism_quality_gate"]["blockers"] == [
        "root_symmetry_sidewall_quad_aspect_ratio_exceeds_1000",
    ]
    assert report["termination_interface_quad_count"] > 0
    assert "bl_outer_interface" not in report["marker_summary"]
    assert "bl_termination_interface" not in report["marker_summary"]
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_closed_wall_te_stageback_buffered_core_hybrid_adds_non_wall_transition(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_closed_wall_te_stageback_buffered_core_hybrid_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "closed_wall_te_stageback_buffered_core.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        full_wall_layers=8,
        cap_layers=3,
        stageback_segments=2,
        transition_buffer_layers=2,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    assert report["status"] == "closed_wall_te_stageback_buffered_core_hybrid_blocked"
    assert report["transition_buffer_prism_count"] > 0
    assert report["core_report"]["status"] == "blocked_before_core_tet_fill"
    assert "overlapping facets" in report["core_report"]["error"]
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_partial_wing_prism_handoff_passes_prism_quality_but_requires_caps(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_partial_wing_prism_handoff_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "partial_wing_prism_handoff.su2",
        points_per_side=42,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=24,
    )

    assert report["route"] == "canonical_hybrid_halfwing_partial_wing_prism_handoff"
    assert report["status"] == "partial_wing_prism_ready_caps_pending"
    assert report["volume_element_type_counts"] == {str(module.SU2_PRISM): 124416}
    assert report["direct_prism_quality_gate"]["status"] == "pass"
    assert report["direct_prism_quality"]["prism_signed_volume"]["non_positive_count"] == 0
    assert report["direct_prism_quality"]["root_symmetry_quad_aspect"]["max"] < 1000.0
    assert report["cap_closure_topology"]["required_cap_markers"] == [
        "tip_wall",
        "te_wall",
        "closure_wall",
    ]
    assert report["cap_closure_topology"]["status"] == "blocked_cap_faces_missing"
    assert report["core_tetra_interface"]["status"] == "blocked_until_caps_materialized"
    assert report["marker_summary"]["tip_wall"]["element_type_counts"] == {
        str(module.SU2_QUAD): 1944,
    }
    assert report["marker_summary"]["te_wall"]["element_type_counts"] == {
        str(module.SU2_QUAD): 1344,
    }
    assert report["marker_summary"]["closure_wall"]["element_type_counts"] == {
        str(module.SU2_QUAD): 192,
    }


def test_partial_wing_cap_core_probe_tet_fills_materialized_caps(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.run_phase3_partial_wing_cap_core_probe(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "partial_wing_cap_core_probe",
        points_per_side=12,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    assert report["route"] == "canonical_hybrid_halfwing_partial_wing_cap_core_probe"
    assert report["status"] == "partial_wing_cap_core_probe_meshed"
    assert report["core_report"]["volume_element_type_counts"] == {module.GMSH_TETRA: 7295}
    assert report["core_report"]["forbidden_element_type_counts"] == {}
    assert report["inner_boundary_topology"]["bad_edge_count"] == 30
    assert report["inner_boundary_topology"]["bad_edge_count_by_role"] == {
        "bl_outer_interface": 21,
        "te_wall": 9,
    }
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_minimal_transition_unit_requires_pyramid_collar_between_prism_and_tet(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_minimal_transition_unit_su2(
        tmp_path / "minimal_transition_unit.su2"
    )

    assert report["route"] == "canonical_hybrid_halfwing_minimal_transition_unit"
    assert report["status"] == "transition_topology_unit_pass"
    assert report["volume_element_type_counts"] == {
        str(module.SU2_PRISM): 2,
        str(module.SU2_PYRAMID): 4,
        str(module.SU2_TETRAHEDRON): 18,
    }
    assert report["topology"]["tet_to_prism_quad_contact"] == 0
    assert report["topology"]["prism_quad_to_pyramid_base_contact"] == 4
    assert report["topology"]["pyramid_triangle_to_tet_contact"] == 16
    assert report["topology"]["tet_to_prism_triangle_contact"] == 2
    assert report["topology"]["non_root_exposed_prism_quad_count"] == 0
    assert report["topology"]["pyramid_boundary_face_count"] == 0
    assert report["topology"]["boundary_faces_unmarked"] == 0
    assert report["topology"]["duplicate_marker_faces"] == 0
    assert report["element_quality_gate"]["status"] == "pass"
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["marker_summary"]["wing_upper"]["element_count"] == 1
    assert report["marker_summary"]["wing_lower"]["element_count"] == 1
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_collar_scale_transition_unit_limits_hotspot_edge_jump(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_segmented_collar_scale_transition_unit_su2(
        tmp_path / "segmented_collar_scale_transition_unit.su2"
    )

    assert report["route"] == "canonical_hybrid_halfwing_segmented_collar_scale_transition_unit"
    assert report["status"] == "segmented_collar_scale_transition_unit_pass"
    assert report["segmented_collar"]["segment_count"] == 16
    assert report["segmented_collar"]["rim_quad_max_edge_ratio"] < 1000.0
    assert report["topology"]["tet_to_prism_quad_contact"] == 0
    assert report["topology"]["non_root_exposed_prism_quad_count"] == 0
    assert report["element_quality_gate"]["status"] == "pass"
    assert report["dual_subvolume_proxy"]["status"] == "pass"
    assert report["dual_subvolume_proxy"]["max_incident_edge_length_ratio"] < 1000.0
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_structured_transition_patch_unit_stages_core_growth_away_from_bl_vertices(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_structured_transition_patch_unit_su2(
        tmp_path / "structured_transition_patch_unit.su2"
    )

    assert report["route"] == "canonical_hybrid_halfwing_structured_transition_patch_unit"
    assert report["status"] == "structured_transition_patch_unit_pass"
    assert report["structured_transition"]["row_count"] == 2
    assert report["structured_transition"]["first_row_height_m"] <= 0.03
    assert report["structured_transition"]["max_row_growth_ratio"] <= 4.0
    assert report["structured_transition"]["sidewall_closure_pyramid_count"] > 0
    assert report["structured_transition"]["sidewall_closure_tetra_count"] > 0
    assert report["structured_transition"]["sidewall_quad_status"] == "pass"
    assert report["structured_transition"]["core_interface_sidewall_quad_count"] == 0
    assert report["topology"]["tet_to_prism_quad_contact"] == 0
    assert report["topology"]["non_root_exposed_prism_quad_count"] == 0
    assert report["topology"]["pyramid_boundary_face_count"] == 0
    assert report["element_quality_gate"]["status"] == "pass"
    assert report["dual_subvolume_proxy"]["status"] == "pass"
    assert report["dual_subvolume_proxy"]["max_incident_edge_length_ratio"] < 1000.0
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["gate"]["status"] == "pass"
    assert report["gate"]["blockers"] == []
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_partial_wing_transition_collar_handoff_converts_rim_quads_to_triangles(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_partial_wing_transition_collar_handoff_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "partial_wing_transition_collar_handoff.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        collar_height_m=5.0e-4,
    )

    assert report["route"] == "canonical_hybrid_halfwing_partial_wing_transition_collar_handoff"
    assert report["status"] == "partial_wing_transition_collar_ready_caps_pending"
    assert report["volume_element_type_counts"][str(module.SU2_PRISM)] > 0
    assert report["volume_element_type_counts"][str(module.SU2_PYRAMID)] > 0
    converted = report["transition_collar"]["converted_prism_rim_quads_by_marker"]
    assert converted["tip_wall"] > 0
    assert converted["te_wall"] > 0
    assert converted["closure_wall"] > 0
    segmentation = report["transition_collar"]["segmented_collar_requirement"]
    assert segmentation["threshold_max_edge_ratio"] == 1000.0
    assert segmentation["max_required_segments_per_quad"] > 1
    assert segmentation["total_required_rim_segments"] > sum(converted.values())
    assert segmentation["max_single_pyramid_base_edge_ratio"] > 1000.0
    assert segmentation["plan_record_count"] == sum(converted.values())
    assert segmentation["max_planned_segment_base_edge_ratio"] <= 1000.0
    assert segmentation["split_policy"] == "split_longest_prism_rim_edge_pair"
    source_edges = segmentation["source_edge_split_requirement"]
    assert source_edges["source_edge_count"] < segmentation["plan_record_count"]
    assert (
        source_edges["total_required_source_edge_segments"]
        < segmentation["total_required_rim_segments"]
    )
    assert source_edges["max_planned_source_edge_base_ratio"] <= 1000.0
    sample = segmentation["plan_samples"][0]
    assert sample["required_segments"] > 1
    assert sample["planned_segment_base_edge_ratio"] <= 1000.0
    assert sample["marker"] in module.DIAGNOSTIC_FORCE_MARKERS
    assert report["transition_collar"]["force_wall_rim_marker_leak_count"] == 0
    assert report["transition_collar"]["pyramid_signed_volume"]["non_positive_count"] == 0
    assert report["core_tetra_interface"]["status"] == "triangular_transition_interface_ready_caps_pending"
    assert report["core_tetra_interface"]["element_type_counts"] == {
        str(module.SU2_TRIANGLE): report["core_tetra_interface"]["element_count"],
    }
    assert report["marker_summary"]["transition_collar_interface"]["element_type_counts"] == {
        str(module.SU2_TRIANGLE): report["transition_collar"]["interface_triangle_count"],
    }
    for diagnostic_marker in module.DIAGNOSTIC_FORCE_MARKERS:
        assert diagnostic_marker not in report["marker_summary"]
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_partial_wing_transition_collar_handoff_splits_source_edges(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_segmented_partial_wing_transition_collar_handoff_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "segmented_partial_wing_transition_collar_handoff.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        collar_height_m=5.0e-4,
    )

    assert (
        report["route"]
        == "canonical_hybrid_halfwing_segmented_partial_wing_transition_collar_handoff"
    )
    assert report["status"] == "segmented_partial_wing_transition_collar_ready_caps_pending"
    source_plan = report["source_rim_edge_split_plan"]
    assert source_plan["source_edge_count"] > 0
    assert source_plan["total_required_source_edge_segments"] > source_plan["source_edge_count"]
    assert source_plan["max_planned_source_edge_base_ratio"] <= 1000.0
    assert report["segmented_surface"]["added_source_vertices"] > 0

    collar_requirement = report["transition_collar"]["segmented_collar_requirement"]
    assert collar_requirement["max_single_pyramid_base_edge_ratio"] <= 1000.0
    assert collar_requirement["max_required_segments_per_quad"] == 1
    assert (
        collar_requirement["source_edge_split_requirement"][
            "total_required_source_edge_segments"
        ]
        == collar_requirement["source_edge_split_requirement"]["source_edge_count"]
    )
    assert report["transition_collar"]["force_wall_rim_marker_leak_count"] == 0
    assert report["transition_collar"]["pyramid_signed_volume"]["non_positive_count"] == 0
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_partial_wing_transition_collar_core_hybrid_writes_merged_mesh(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_segmented_partial_wing_transition_collar_core_hybrid_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "segmented_partial_wing_transition_collar_core_hybrid.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        collar_height_m=5.0e-4,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    assert (
        report["route"]
        == "canonical_hybrid_halfwing_segmented_partial_wing_transition_collar_core_hybrid"
    )
    assert report["status"] == "segmented_partial_wing_transition_collar_core_hybrid_written"
    assert report["required_markers_present"] is True
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["volume_element_type_counts"][str(module.SU2_PRISM)] > 0
    assert report["volume_element_type_counts"][str(module.SU2_PYRAMID)] > 0
    assert report["volume_element_type_counts"][str(module.SU2_TETRAHEDRON)] > 0
    assert "bl_outer_interface" not in report["marker_summary"]
    assert "transition_collar_interface" not in report["marker_summary"]
    collar_requirement = report["transition_collar"]["segmented_collar_requirement"]
    assert collar_requirement["max_single_pyramid_base_edge_ratio"] <= 1000.0
    assert collar_requirement["max_required_segments_per_quad"] == 1
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_partial_wing_structured_transition_handoff_closes_sidewalls(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_segmented_partial_wing_structured_transition_handoff_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "segmented_partial_wing_structured_transition_handoff.su2",
        points_per_side=4,
        spanwise_subdivisions=1,
        first_layer_height_m=1.0e-3,
        growth_ratio=1.2,
        bl_layers=1,
        collar_height_m=5.0e-4,
        transition_row_heights_m=(0.03, 0.09),
    )

    assert (
        report["route"]
        == "canonical_hybrid_halfwing_segmented_partial_wing_structured_transition_handoff"
    )
    assert report["status"] == "segmented_partial_wing_structured_transition_ready_caps_pending"
    assert report["structured_transition"]["input_interface_triangle_count"] > 0
    assert report["structured_transition"]["sidewall_closure_pyramid_count"] > 0
    assert report["topology"]["tet_to_prism_quad_contact"] == 0
    assert report["topology"]["non_root_exposed_prism_quad_count"] == 0
    assert report["topology"]["pyramid_boundary_face_count"] == 0
    assert report["dual_subvolume_proxy"]["status"] == "pass"
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert "transition_collar_interface" not in report["marker_summary"]
    assert "transition_collar_outer_interface" in report["marker_summary"]
    for diagnostic_marker in module.DIAGNOSTIC_FORCE_MARKERS:
        assert diagnostic_marker not in report["marker_summary"]
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_structured_transition_projection_blocks_element_explosion() -> None:
    module = _load_module()

    report = module.plan_phase3_segmented_partial_wing_structured_transition_handoff(
        module.DEFAULT_SECTION_TABLE_PATH,
        points_per_side=4,
        spanwise_subdivisions=1,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=2,
        collar_height_m=5.0e-4,
        transition_row_heights_m=(0.03, 0.09),
        max_projected_volume_elements=150_000,
    )

    assert (
        report["route"]
        == "canonical_hybrid_halfwing_segmented_partial_wing_structured_transition_projection"
    )
    assert report["status"] == "segmented_partial_wing_structured_transition_projection_blocked"
    projected = report["projected_counts"]
    assert projected["input_interface_triangle_count"] > 0
    assert projected["transition_prism_count"] == projected["input_interface_triangle_count"] * 2
    assert (
        projected["sidewall_closure_pyramid_count"]
        == projected["input_interface_triangle_count"] * 6
    )
    assert (
        projected["sidewall_closure_tetra_count"]
        == projected["sidewall_closure_pyramid_count"] * 4
    )
    assert projected["projected_volume_element_count"] > 150_000
    assert "projected_volume_element_count_exceeds_gate" in report["gate"]["blockers"]
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_structured_transition_projection_stitched_sidewalls_scales() -> None:
    module = _load_module()

    report = module.plan_phase3_segmented_partial_wing_structured_transition_handoff(
        module.DEFAULT_SECTION_TABLE_PATH,
        points_per_side=4,
        spanwise_subdivisions=1,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=2,
        collar_height_m=5.0e-4,
        transition_row_heights_m=(0.01, 0.03),
        sidewall_closure_policy="stitched_sheet",
        max_projected_volume_elements=150_000,
    )

    assert report["status"] == "segmented_partial_wing_structured_transition_projection_ready"
    projected = report["projected_counts"]
    assert projected["interface_boundary_edge_count"] > 0
    assert projected["interface_nonmanifold_edge_count"] == 0
    assert projected["sidewall_closure_policy"] == "stitched_sheet"
    assert (
        projected["sidewall_closure_pyramid_count"]
        == projected["interface_boundary_edge_count"] * 2
    )
    assert (
        projected["sidewall_closure_tetra_count"]
        == projected["sidewall_closure_pyramid_count"] * 4
    )
    assert projected["projected_volume_element_count"] < 150_000
    assert report["gate"]["status"] == "pass"
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_partial_wing_stitched_transition_handoff_pairs_sidewalls(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_segmented_partial_wing_structured_transition_handoff_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "segmented_partial_wing_stitched_transition_handoff.su2",
        points_per_side=4,
        spanwise_subdivisions=1,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=2,
        collar_height_m=5.0e-4,
        transition_row_heights_m=(0.01, 0.03),
        sidewall_closure_policy="stitched_sheet",
        max_projected_volume_elements=150_000,
    )

    assert report["status"] == "segmented_partial_wing_structured_transition_ready_caps_pending"
    assert report["structured_transition"]["sidewall_closure_policy"] == "stitched_sheet"
    assert report["structured_transition"]["sidewall_closure_pyramid_count"] < (
        report["structured_transition"]["input_interface_triangle_count"] * 2 * 3
    )
    assert report["volume_element_count"] < 150_000
    assert report["topology"]["tet_to_prism_quad_contact"] == 0
    assert report["topology"]["non_root_exposed_prism_quad_count"] == 0
    assert report["topology"]["pyramid_boundary_face_count"] == 0
    assert report["dual_subvolume_proxy"]["status"] == "pass"
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_partial_wing_stitched_transition_handoff_pps42_l3_passes_dual_gate(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_segmented_partial_wing_structured_transition_handoff_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "segmented_partial_wing_stitched_transition_handoff_pps42_l3.su2",
        points_per_side=42,
        spanwise_subdivisions=module.DEFAULT_SPANWISE_SUBDIVISIONS,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=3,
        collar_height_m=5.0e-4,
        transition_row_heights_m=(0.01, 0.03),
        sidewall_closure_policy="stitched_sheet",
        max_projected_volume_elements=250_000,
    )

    assert report["status"] == "segmented_partial_wing_structured_transition_ready_caps_pending"
    assert report["volume_element_count"] < 250_000
    assert report["structured_transition"]["input_interface_triangle_count"] == 9708
    assert report["structured_transition"]["sidewall_closure_policy"] == "stitched_sheet"
    assert report["structured_transition"]["sidewall_closure_pyramid_count"] < (
        report["structured_transition"]["input_interface_triangle_count"] * 2 * 3
    )
    assert report["topology"]["tet_to_prism_quad_contact"] == 0
    assert report["topology"]["non_root_exposed_prism_quad_count"] == 0
    assert report["topology"]["pyramid_boundary_face_count"] == 0
    assert report["element_quality_gate"]["status"] == "pass"
    assert report["dual_subvolume_proxy"]["status"] == "pass"
    assert report["su2_boundary_ownership"]["status"] == "pass"
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_partial_wing_stitched_core_shell_blocks_nonmanifold_inner_boundary(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.run_phase3_segmented_partial_wing_structured_transition_core_shell_probe(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "segmented_partial_wing_structured_transition_core_shell_probe",
        points_per_side=4,
        spanwise_subdivisions=1,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=2,
        collar_height_m=5.0e-4,
        transition_row_heights_m=(0.01, 0.03),
        sidewall_closure_policy="stitched_sheet",
        max_projected_volume_elements=150_000,
    )

    assert (
        report["route"]
        == "canonical_hybrid_halfwing_segmented_partial_wing_structured_transition_core_shell_probe"
    )
    assert report["status"] == "segmented_partial_wing_structured_transition_core_shell_blocked"
    assert report["handoff_gate"]["status"] == "pass"
    assert report["inner_boundary_topology"]["bad_edge_count"] > 0
    assert report["inner_boundary_topology"]["nonmanifold_edge_count"] > 0
    assert report["inner_boundary_topology"]["bad_edge_kind_counts"]["nonmanifold"] > 0
    assert (
        report["inner_boundary_topology"]["bad_edge_marker_combo_counts"][
            "transition_collar_outer_interface"
        ]
        > 0
    )
    assert (
        report["inner_boundary_topology"]["bad_edge_marker_combo_counts_by_kind"][
            "nonmanifold"
        ]["transition_collar_outer_interface"]
        > 0
    )
    bad_edge_sample = report["inner_boundary_topology"]["bad_edge_samples"][0]
    assert bad_edge_sample["count"] != 2
    assert bad_edge_sample["markers"]
    assert len(bad_edge_sample["midpoint"]) == 3
    assert bad_edge_sample["length_m"] > 0.0
    nonmanifold_sample = report["inner_boundary_topology"]["bad_edge_samples_by_kind"][
        "nonmanifold"
    ][0]
    assert nonmanifold_sample["kind"] == "nonmanifold"
    assert nonmanifold_sample["markers"] == ["transition_collar_outer_interface"]
    assert (
        report["inner_boundary_topology"]["bad_edge_midpoint_bounds_by_kind"][
            "nonmanifold"
        ]["y_min"]
        > 10.0
    )
    assert report["inner_boundary_topology"]["bad_edge_midpoint_bounds"]["x_min"] <= (
        report["inner_boundary_topology"]["bad_edge_midpoint_bounds"]["x_max"]
    )
    assert "core_inner_boundary_nonmanifold_edges" in report["gate"]["blockers"]
    assert report["core_report"]["status"] == "blocked_before_gmsh_core_fill"
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_segmented_partial_wing_stitched_core_shell_rejects_shared_tip_apex_shortcut(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.run_phase3_segmented_partial_wing_structured_transition_core_shell_probe(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "segmented_partial_wing_structured_transition_core_shell_probe",
        points_per_side=4,
        spanwise_subdivisions=1,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=2,
        collar_height_m=5.0e-4,
        transition_row_heights_m=(0.01, 0.03),
        sidewall_closure_policy="stitched_sheet",
        terminal_tip_closure_policy="shared_apex",
        terminal_tip_band_m=0.05,
        max_projected_volume_elements=150_000,
    )

    assert report["handoff_gate"]["status"] == "blocked"
    assert "mixed_dual_subvolume_ratio_exceeds_route_gate" in report["handoff_gate"]["blockers"]
    assert "structured_handoff_nonmanifold_face_count" in report["handoff_gate"]["blockers"]
    assert report["structured_transition"]["terminal_tip_closure_policy"] == "shared_apex"
    assert report["structured_transition"]["terminal_tip_shared_apex_count"] > 0
    assert report["structured_transition"]["terminal_tip_shared_pyramid_count"] > 0
    assert report["handoff_dual_subvolume_proxy"]["max_cv_sub_volume_ratio"] > 1.0e12
    assert report["inner_boundary_topology"]["nonmanifold_edge_count"] > 0
    assert "core_inner_boundary_nonmanifold_edges" in report["gate"]["blockers"]
    assert "structured_transition_handoff_gate_not_pass" in report["gate"]["blockers"]
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_core_boundary_point_size_targets_selected_interface_markers() -> None:
    module = _load_module()
    surface = module.SurfaceMesh(
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        faces=[
            module.Face(nodes=(0, 1, 2), marker="transition_collar_interface"),
            module.Face(nodes=(1, 3, 2), marker="bl_outer_interface"),
        ],
        metadata={},
    )

    entities, report = module._core_boundary_point_size_targets(
        surface,
        point_tag_offset=100,
        mesh_size=0.05,
        markers=("transition_collar_interface",),
    )

    assert entities == [(0, 100), (0, 101), (0, 102)]
    assert report == {
        "status": "enabled",
        "markers": ["transition_collar_interface"],
        "mesh_size": 0.05,
        "point_count": 3,
        "point_tag_samples": [100, 101, 102],
    }


def test_partial_wing_transition_collar_core_probe_tet_fills_caps(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.run_phase3_partial_wing_transition_collar_core_probe(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "partial_wing_transition_collar_core_probe",
        points_per_side=12,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        collar_height_m=5.0e-4,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    assert report["route"] == "canonical_hybrid_halfwing_partial_wing_transition_collar_core_probe"
    assert report["status"] == "partial_wing_transition_collar_core_probe_meshed"
    assert report["transition_collar"]["converted_prism_rim_quads_by_marker"] == {
        "tip_wall": 84,
        "te_wall": 224,
        "closure_wall": 32,
    }
    assert report["inner_boundary_topology"]["bad_edge_count"] == 30
    assert report["inner_boundary_topology"]["bad_edge_count_by_role"] == {
        "bl_outer_interface": 21,
        "te_wall": 1,
        "transition_collar_interface": 8,
    }
    assert report["core_report"]["volume_element_type_counts"] == {module.GMSH_TETRA: 9088}
    assert report["core_report"]["forbidden_element_type_counts"] == {}
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_partial_wing_transition_collar_core_probe_scales_to_pps24_with_thin_collar(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.run_phase3_partial_wing_transition_collar_core_probe(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "partial_wing_transition_collar_core_probe_pps24",
        points_per_side=24,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        collar_height_m=1.0e-4,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    assert report["status"] == "partial_wing_transition_collar_core_probe_meshed"
    assert report["transition_collar"]["pyramid_signed_volume"]["non_positive_count"] == 0
    assert report["core_report"]["volume_element_type_counts"] == {module.GMSH_TETRA: 12028}
    assert report["core_report"]["forbidden_element_type_counts"] == {}


def test_partial_wing_transition_collar_core_hybrid_writer_merges_without_interface_markers(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_partial_wing_transition_collar_core_hybrid_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "partial_wing_transition_collar_core_hybrid.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        collar_height_m=1.0e-4,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    assert report["route"] == "canonical_hybrid_halfwing_partial_wing_transition_collar_core_hybrid"
    assert report["status"] == "partial_wing_transition_collar_core_hybrid_written"
    assert report["volume_element_type_counts"][str(module.SU2_PRISM)] > 0
    assert report["volume_element_type_counts"][str(module.SU2_PYRAMID)] > 0
    assert report["volume_element_type_counts"][str(module.SU2_TETRAHEDRON)] == 8690
    assert report["node_compaction"]["removed_unused_node_count"] == 4
    assert "bl_outer_interface" not in report["marker_summary"]
    assert "transition_collar_interface" not in report["marker_summary"]
    for marker in module.REQUIRED_MARKERS:
        assert marker in report["marker_summary"]
    assert report["core_report"]["node_tag_integrity"]["status"] == "pass"
    assert report["su2_boundary_ownership"]["status"] == "pass"
    dual_proxy = report["dual_subvolume_proxy"]
    assert dual_proxy["status"] == "fail"
    assert (
        "mixed_dual_subvolume_ratio_exceeds_route_gate"
        in dual_proxy["blockers"]
    )
    assert dual_proxy["max_cv_sub_volume_ratio"] > 4.0e11
    assert dual_proxy["worst_source_pair"] == "tetra_core|tetra_core"
    worst = dual_proxy["top_hotspots"][0]
    assert worst["incident_element_source_counts"]["tetra_core"] > 0
    assert worst["incident_element_source_counts"]["transition_collar_pyramid"] > 0
    assert report["engineering_assessment"]["route_smoke_ready"] is False


def test_partial_wing_collar_core_dual_hotspot_reports_incident_geometry(
    tmp_path: Path,
) -> None:
    module = _load_module()

    report = module.write_phase3_partial_wing_transition_collar_core_hybrid_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "partial_wing_transition_collar_core_hybrid.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        bl_layers=4,
        collar_height_m=1.0e-4,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    worst = report["dual_subvolume_proxy"]["top_hotspots"][0]
    by_source = worst["incident_element_geometry_by_source"]

    assert report["dual_subvolume_proxy"]["max_incident_edge_length_ratio"] > 1000.0
    assert (
        "mixed_dual_hotspot_incident_edge_ratio_exceeds_route_gate"
        in report["dual_subvolume_proxy"]["blockers"]
    )
    assert by_source["transition_collar_pyramid"]["count"] > 0
    assert by_source["transition_collar_pyramid"]["max_edge_length_ratio"] > 1.0
    assert by_source["tetra_core"]["count"] > 0
    assert by_source["tetra_core"]["min_abs_volume_m3"] > 0.0
    assert by_source["tetra_core"]["max_edge_length_m"] > 0.0
    assert worst["min_subvolume"]["element_geometry"]["source"] in by_source
    assert worst["max_subvolume"]["element_geometry"]["source"] in by_source


def test_partial_wing_transition_collar_height_sweep_reduces_but_does_not_clear_dual_proxy(
    tmp_path: Path,
) -> None:
    module = _load_module()

    thin = module.write_phase3_partial_wing_transition_collar_core_hybrid_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "thin_collar" / "mesh.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        collar_height_m=1.0e-4,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )
    taller = module.write_phase3_partial_wing_transition_collar_core_hybrid_su2(
        module.DEFAULT_SECTION_TABLE_PATH,
        tmp_path / "taller_collar" / "mesh.su2",
        points_per_side=12,
        spanwise_subdivisions=4,
        first_layer_height_m=5.0e-5,
        growth_ratio=1.2,
        bl_layers=4,
        collar_height_m=2.0e-3,
        core_mesh_size=0.35,
        farfield_mesh_size=8.0,
    )

    thin_ratio = thin["dual_subvolume_proxy"]["max_cv_sub_volume_ratio"]
    taller_ratio = taller["dual_subvolume_proxy"]["max_cv_sub_volume_ratio"]

    assert thin_ratio > 4.0e11
    assert 1.0e9 < taller_ratio < 1.0e10
    assert taller_ratio < thin_ratio / 40.0
    assert taller["dual_subvolume_proxy"]["status"] == "fail"
    assert taller["transition_collar"]["pyramid_signed_volume"]["non_positive_count"] == 0
    assert taller["engineering_assessment"]["route_smoke_ready"] is False
