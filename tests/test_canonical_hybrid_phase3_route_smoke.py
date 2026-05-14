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
