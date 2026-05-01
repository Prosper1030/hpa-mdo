from pathlib import Path
import shutil

import pytest

from hpa_meshing.mesh_native.blackcat import (
    build_blackcat_main_wing_surfaces_from_avl,
    build_blackcat_main_wing_surfaces_from_vsp,
    load_blackcat_main_wing_spec_from_avl,
    load_blackcat_main_wing_spec_from_vsp,
    run_blackcat_main_wing_coupled_refinement_ladder,
    run_blackcat_main_wing_faceted_refinement_ladder,
    run_blackcat_main_wing_faceted_su2_smoke,
    run_blackcat_main_wing_su2_stability_ladder,
)
from hpa_meshing.mesh_native.wing_surface import build_wing_surface


REPO_ROOT = Path(__file__).resolve().parents[2]
AVL_PATH = REPO_ROOT / "data" / "blackcat_004_full.avl"
VSP_PATH = REPO_ROOT / "data" / "blackcat_004_origin.vsp3"


def test_load_blackcat_main_wing_spec_from_avl_builds_full_span_mesh_native_spec():
    spec = load_blackcat_main_wing_spec_from_avl(AVL_PATH, points_per_side=8)

    assert spec.side == "full"
    assert spec.reference.sref_full == pytest.approx(35.175)
    assert spec.reference.cref == pytest.approx(1.130189765)
    assert spec.reference.bref_full == pytest.approx(33.0)
    assert [station.y for station in spec.stations] == pytest.approx(
        [-16.5, -13.5, -10.5, -7.5, -4.5, 0.0, 4.5, 7.5, 10.5, 13.5, 16.5]
    )
    assert spec.stations[0].chord == pytest.approx(0.435)
    assert spec.stations[5].chord == pytest.approx(1.3)
    assert spec.stations[-1].chord == pytest.approx(0.435)
    assert all(station.twist_deg == pytest.approx(3.0) for station in spec.stations)
    assert all(len(station.airfoil_xz) == 14 for station in spec.stations)
    assert spec.stations[0].airfoil_xz[0] == pytest.approx((1.0, 0.0))


def test_load_blackcat_main_wing_spec_from_vsp_preserves_openvsp_le_placement():
    pytest.importorskip("openvsp")

    spec = load_blackcat_main_wing_spec_from_vsp(
        VSP_PATH,
        reference_avl_path=AVL_PATH,
        points_per_side=8,
    )

    positive = [station for station in spec.stations if station.y >= -1.0e-9]
    assert spec.twist_axis_x == pytest.approx(0.0)
    assert spec.reference.sref_full == pytest.approx(35.175)
    assert [station.chord for station in positive] == pytest.approx(
        [1.3, 1.3, 1.175, 1.04, 0.83, 0.435]
    )
    assert [station.y for station in positive] == pytest.approx(
        [
            0.0,
            4.499314628,
            7.497487109,
            10.493375714,
            13.486067864,
            16.474651959,
        ],
        abs=1.0e-9,
    )
    assert positive[3].x_le == pytest.approx(0.057493738, abs=1.0e-9)
    assert positive[-1].x_le == pytest.approx(0.231214587, abs=1.0e-9)
    assert positive[-1].z_le == pytest.approx(0.799974338, abs=1.0e-9)
    assert all(station.twist_deg == pytest.approx(3.0) for station in positive)
    assert all(len(station.airfoil_xz) == 14 for station in positive)


def test_load_blackcat_main_wing_spec_can_subdivide_spanwise_stations():
    coarse = load_blackcat_main_wing_spec_from_avl(
        AVL_PATH,
        points_per_side=8,
    )
    refined = load_blackcat_main_wing_spec_from_avl(
        AVL_PATH,
        points_per_side=8,
        spanwise_subdivisions=2,
    )

    assert len(refined.stations) == 21
    assert refined.stations[0].y == pytest.approx(-16.5)
    assert refined.stations[1].y == pytest.approx(-15.0)
    assert refined.stations[2].y == pytest.approx(-13.5)
    assert refined.stations[1].chord == pytest.approx(
        0.5 * (coarse.stations[0].chord + coarse.stations[1].chord)
    )

    surface = build_wing_surface(refined)
    assert surface.metadata["station_count"] == 21
    assert surface.metadata["span_m"] == pytest.approx(33.0)
    assert surface.metadata["planform_area_m2"] == pytest.approx(35.175)
    assert surface.marker_counts() == {"wing_wall": 308}


def test_blackcat_main_wing_spec_builds_watertight_mesh_native_surface():
    spec = load_blackcat_main_wing_spec_from_avl(AVL_PATH, points_per_side=8)

    surface = build_wing_surface(spec)

    assert surface.metadata["station_count"] == 11
    assert surface.metadata["points_per_station"] == 14
    assert surface.metadata["span_m"] == pytest.approx(33.0)
    assert surface.metadata["planform_area_m2"] == pytest.approx(35.175)
    assert surface.marker_counts() == {"wing_wall": 168}
    bounds = surface.bounds()
    assert bounds["y_min"] == pytest.approx(-16.5)
    assert bounds["y_max"] == pytest.approx(16.5)


def test_build_blackcat_main_wing_surfaces_from_avl_materializes_farfield():
    spec, wing, farfield = build_blackcat_main_wing_surfaces_from_avl(
        AVL_PATH,
        points_per_side=8,
        farfield_upstream_factor=1.5,
        farfield_downstream_factor=2.0,
        farfield_lateral_factor=1.2,
        farfield_vertical_factor=1.2,
    )

    assert spec.reference.sref_full == pytest.approx(35.175)
    assert wing.marker_counts() == {"wing_wall": 168}
    assert farfield.marker_counts() == {"farfield": 6}
    assert farfield.bounds()["y_min"] < wing.bounds()["y_min"]
    assert farfield.bounds()["y_max"] > wing.bounds()["y_max"]


def test_build_blackcat_main_wing_surfaces_from_vsp_uses_vsp_projected_bounds():
    pytest.importorskip("openvsp")

    spec, wing, farfield = build_blackcat_main_wing_surfaces_from_vsp(
        VSP_PATH,
        reference_avl_path=AVL_PATH,
        points_per_side=8,
        farfield_upstream_factor=1.5,
        farfield_downstream_factor=2.0,
        farfield_lateral_factor=1.2,
        farfield_vertical_factor=1.2,
    )

    assert spec.reference.bref_full == pytest.approx(33.0)
    assert wing.marker_counts() == {"wing_wall": 168}
    assert wing.metadata["span_m"] == pytest.approx(32.949303917)
    assert wing.bounds()["y_max"] == pytest.approx(16.474651959)
    assert farfield.marker_counts() == {"farfield": 6}


def test_run_blackcat_main_wing_faceted_su2_smoke_runs_when_su2_is_available(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")
    solver = shutil.which("SU2_CFD")
    if solver is None:
        pytest.skip("SU2_CFD not available")

    report = run_blackcat_main_wing_faceted_su2_smoke(
        AVL_PATH,
        tmp_path / "blackcat_faceted_solver_case",
        points_per_side=6,
        mesh_size=10.0,
        max_iterations=3,
        solver_command=solver,
        threads=1,
    )

    assert report["route"] == "blackcat_main_wing_mesh_native_faceted_su2_smoke"
    assert report["run_status"] == "completed"
    assert report["returncode"] == 0
    assert report["marker_audit"]["status"] == "pass"
    assert report["blackcat_source"]["station_count"] == 11
    assert report["mesh_report"]["volume_element_count"] > 0
    assert report["history"]["final_iteration"] == 2
    assert report["history"]["final_coefficients"]["cl"] is not None


def test_run_blackcat_main_wing_faceted_refinement_ladder_reports_scale_gap(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")

    report = run_blackcat_main_wing_faceted_refinement_ladder(
        AVL_PATH,
        tmp_path / "blackcat_refinement_ladder",
        points_per_side=6,
        mesh_sizes=(14.0, 10.0, 8.0, 6.0),
        target_volume_elements=850,
        max_volume_elements=20_000,
        farfield_mesh_size=18.0,
        wing_refinement_radius=12.0,
        write_su2=False,
    )

    assert report["route"] == "blackcat_main_wing_mesh_native_faceted_refinement_ladder"
    assert report["status"] == "target_reached"
    assert report["blackcat_source"]["station_count"] == 11
    assert [case["volume_element_count"] for case in report["cases"]] == sorted(
        case["volume_element_count"] for case in report["cases"]
    )
    assert report["selected_case"]["mesh_size"] == 6.0
    assert report["selected_case"]["mesh_sizing"]["farfield_mesh_size"] == 18.0
    assert report["selected_case"]["mesh_sizing"]["wing_refinement_radius"] == 12.0
    assert report["selected_case"]["mesh_quality_gate"]["status"] == "pass"
    assert report["engineering_assessment"]["aero_coefficients_interpretable"] is False


def test_run_blackcat_main_wing_coupled_refinement_ladder_varies_surface_density(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")

    report = run_blackcat_main_wing_coupled_refinement_ladder(
        AVL_PATH,
        tmp_path / "blackcat_coupled_ladder",
        points_per_side_values=(4, 8),
        mesh_sizes=(6.0,),
        target_volume_elements=10_000,
        max_volume_elements=50_000,
        farfield_mesh_size=18.0,
        wing_refinement_radius=12.0,
        write_su2=False,
    )

    assert report["route"] == "blackcat_main_wing_mesh_native_coupled_refinement_ladder"
    assert report["status"] == "target_not_reached"
    assert [case["points_per_side"] for case in report["cases"]] == [4, 8]
    assert report["cases"][1]["surface_triangle_count"] > report["cases"][0]["surface_triangle_count"]
    assert report["cases"][1]["volume_element_count"] > report["cases"][0]["volume_element_count"]
    assert report["cases"][1]["mesh_quality_gate"]["status"] == "pass"
    assert report["engineering_assessment"]["surface_and_volume_refinement_coupled"] is True


def test_run_blackcat_main_wing_coupled_refinement_ladder_varies_spanwise_density(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")

    report = run_blackcat_main_wing_coupled_refinement_ladder(
        AVL_PATH,
        tmp_path / "blackcat_spanwise_coupled_ladder",
        points_per_side_values=(4,),
        spanwise_subdivision_values=(1, 2),
        mesh_sizes=(6.0,),
        target_volume_elements=10_000,
        max_volume_elements=50_000,
        farfield_mesh_size=18.0,
        wing_refinement_radius=12.0,
        write_su2=False,
    )

    assert [case["spanwise_subdivisions"] for case in report["cases"]] == [1, 2]
    assert report["cases"][1]["surface_metadata"]["station_count"] > report["cases"][0][
        "surface_metadata"
    ]["station_count"]
    assert report["cases"][1]["surface_triangle_count"] > report["cases"][0][
        "surface_triangle_count"
    ]
    assert report["cases"][1]["volume_element_count"] > report["cases"][0][
        "volume_element_count"
    ]


def test_run_blackcat_main_wing_coupled_refinement_ladder_summarizes_quality_warnings(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")

    report = run_blackcat_main_wing_coupled_refinement_ladder(
        AVL_PATH,
        tmp_path / "blackcat_coupled_warning_ladder",
        points_per_side_values=(16,),
        spanwise_subdivision_values=(1,),
        mesh_sizes=(6.0,),
        target_volume_elements=10_000,
        max_volume_elements=50_000,
        farfield_mesh_size=18.0,
        wing_refinement_radius=12.0,
        write_su2=False,
    )

    assert report["engineering_assessment"]["quality_warnings_present"] is True
    assert len(report["quality_warning_cases"]) == 1
    warning_case = report["quality_warning_cases"][0]
    assert warning_case["case_index"] == 0
    assert warning_case["spanwise_subdivisions"] == 1
    assert warning_case["points_per_side"] == 16
    assert warning_case["mesh_size"] == 6.0
    assert "low_p01_gamma" in warning_case["warnings"]
    assert warning_case["min_gamma"] == pytest.approx(
        report["cases"][0]["quality_metrics"]["min_gamma"]
    )


def test_run_blackcat_main_wing_coupled_refinement_ladder_can_add_feature_boxes(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")

    report = run_blackcat_main_wing_coupled_refinement_ladder(
        AVL_PATH,
        tmp_path / "blackcat_coupled_feature_box_ladder",
        points_per_side_values=(4,),
        spanwise_subdivision_values=(1,),
        mesh_sizes=(6.0,),
        target_volume_elements=10_000,
        max_volume_elements=50_000,
        farfield_mesh_size=18.0,
        wing_refinement_radius=12.0,
        feature_refinement_size=3.0,
        write_su2=False,
    )

    case = report["cases"][0]
    assert report["feature_refinement_size"] == 3.0
    assert case["feature_refinement_box_count"] == 4
    assert case["mesh_sizing"]["refinement_boxes"][0]["name"] == (
        "trailing_edge_refinement_region"
    )
    assert case["mesh_sizing"]["background_field"]["type"] == "Min"


def test_run_blackcat_main_wing_coupled_refinement_ladder_can_use_vsp_native_geometry(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")
    pytest.importorskip("openvsp")

    report = run_blackcat_main_wing_coupled_refinement_ladder(
        AVL_PATH,
        tmp_path / "blackcat_vsp_coupled_ladder",
        points_per_side_values=(4,),
        spanwise_subdivision_values=(1,),
        mesh_sizes=(8.0,),
        target_volume_elements=1_000,
        max_volume_elements=50_000,
        farfield_mesh_size=18.0,
        wing_refinement_radius=12.0,
        write_su2=False,
        vsp_path=VSP_PATH,
    )

    assert report["blackcat_source"]["geometry_source"] == {
        "type": "openvsp_mesh_native",
        "path": str(VSP_PATH),
        "reference_avl_path": str(AVL_PATH),
    }
    assert report["blackcat_source"]["reference"] == {
        "sref_full": pytest.approx(35.175),
        "cref": pytest.approx(1.130189765),
        "bref_full": pytest.approx(33.0),
    }
    assert report["cases"][0]["surface_metadata"]["span_m"] == pytest.approx(
        32.949303917,
        abs=1.0e-9,
    )
    assert report["cases"][0]["volume_element_count"] > 0
    assert "source sections" in report["caveats"][0]


def test_run_blackcat_main_wing_coupled_refinement_ladder_sweeps_feature_box_size(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")

    report = run_blackcat_main_wing_coupled_refinement_ladder(
        AVL_PATH,
        tmp_path / "blackcat_coupled_feature_box_size_ladder",
        points_per_side_values=(4,),
        spanwise_subdivision_values=(1,),
        mesh_sizes=(6.0,),
        feature_refinement_size_values=(None, 3.0, 1.0),
        target_volume_elements=10_000,
        max_volume_elements=50_000,
        farfield_mesh_size=18.0,
        wing_refinement_radius=12.0,
        write_su2=False,
    )

    assert report["feature_refinement_size"] is None
    assert report["feature_refinement_size_values"] == [None, 3.0, 1.0]
    assert [case["feature_refinement_size"] for case in report["cases"]] == [
        None,
        3.0,
        1.0,
    ]
    assert report["cases"][1]["volume_element_count"] > report["cases"][0][
        "volume_element_count"
    ]
    assert report["cases"][2]["volume_element_count"] > report["cases"][1][
        "volume_element_count"
    ]


def test_run_blackcat_main_wing_coupled_refinement_ladder_selects_best_quality_candidate(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")

    report = run_blackcat_main_wing_coupled_refinement_ladder(
        AVL_PATH,
        tmp_path / "blackcat_coupled_quality_selection_ladder",
        points_per_side_values=(8,),
        spanwise_subdivision_values=(1,),
        mesh_sizes=(6.0,),
        feature_refinement_size_values=(None, 3.0, 1.0),
        target_volume_elements=10_000,
        max_volume_elements=50_000,
        farfield_mesh_size=18.0,
        wing_refinement_radius=12.0,
        write_su2=False,
    )

    candidate = report["recommended_quality_candidate"]
    assert candidate["feature_refinement_size"] == 3.0
    assert candidate["volume_element_count"] > report["cases"][0]["volume_element_count"]
    assert candidate["excluded_warnings"] == ["very_low_min_gamma", "very_low_min_sicn"]
    assert candidate["mesh_quality_gate"]["status"] == "pass"


def test_run_blackcat_main_wing_su2_stability_ladder_selects_cheapest_stable_mesh(
    tmp_path: Path,
):
    calls = []

    def fake_case_runner(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        case_dir = Path(args[2])
        mesh_size = kwargs["mesh_size"]
        volume_count = {0.14: 60_000, 0.09: 110_000, 0.06: 180_000}[mesh_size]
        coefficients = {
            0.14: {"cl": 0.30, "cd": 0.070, "cmy": -0.10},
            0.09: {"cl": 0.42, "cd": 0.052, "cmy": -0.18},
            0.06: {"cl": 0.425, "cd": 0.053, "cmy": -0.181},
        }[mesh_size]
        return {
            "case_dir": str(case_dir),
            "run_status": "completed",
            "returncode": 0,
            "mesh_report": {
                "volume_element_count": volume_count,
                "node_count": volume_count // 3,
                "mesh_quality_gate": {"status": "pass", "warnings": []},
            },
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "pass",
            "cfd_evidence_gate": {"status": "pass", "reasons": []},
            "history": {
                "final_iteration": 70,
                "final_coefficients": coefficients,
            },
        }

    report = run_blackcat_main_wing_su2_stability_ladder(
        AVL_PATH,
        tmp_path / "su2_stability_ladder",
        points_per_side=8,
        spanwise_subdivisions=1,
        mesh_sizes=(0.14, 0.09, 0.06),
        feature_refinement_size=3.0,
        max_iterations=1200,
        wall_profile="adiabatic_no_slip",
        turbulence_model="SA",
        transition_model="NONE",
        wall_function="STANDARD_WALL_FUNCTION",
        conv_num_method_flow="JST",
        cfl_number=100.0,
        linear_solver_error="1e-12",
        linear_solver_iter=25,
        jst_sensor_coeff=(0.0, 0.02),
        conv_cauchy_elems=50,
        conv_cauchy_eps="1E-6",
        output_files=("RESTART_ASCII",),
        coefficient_tolerances={"cl": 0.01, "cd": 0.002, "cmy": 0.005},
        coefficient_relative_tolerances={"cl": 0.03, "cd": 0.05, "cmy": 0.05},
        case_runner=fake_case_runner,
    )

    assert len(calls) == 3
    assert calls[0]["kwargs"]["turbulence_model"] == "SA"
    assert calls[0]["kwargs"]["transition_model"] == "NONE"
    assert calls[0]["kwargs"]["wall_function"] == "STANDARD_WALL_FUNCTION"
    assert calls[0]["kwargs"]["conv_num_method_flow"] == "JST"
    assert calls[0]["kwargs"]["cfl_number"] == 100.0
    assert calls[0]["kwargs"]["linear_solver_error"] == "1e-12"
    assert calls[0]["kwargs"]["linear_solver_iter"] == 25
    assert calls[0]["kwargs"]["jst_sensor_coeff"] == (0.0, 0.02)
    assert calls[0]["kwargs"]["conv_cauchy_elems"] == 50
    assert calls[0]["kwargs"]["conv_cauchy_eps"] == "1E-6"
    assert calls[0]["kwargs"]["output_files"] == ("RESTART_ASCII",)
    assert calls[0]["kwargs"]["cfd_evidence_min_iterations"] == 1000
    assert calls[0]["kwargs"]["wall_profile"] == "adiabatic_no_slip"
    assert report["route"] == "blackcat_main_wing_mesh_native_su2_stability_ladder"
    assert report["status"] == "stable_mesh_selected"
    assert report["runtime"]["conv_num_method_flow"] == "JST"
    assert report["runtime"]["wall_profile"] == "adiabatic_no_slip"
    assert report["runtime"]["turbulence_model"] == "SA"
    assert report["runtime"]["wall_function"] == "STANDARD_WALL_FUNCTION"
    assert report["runtime"]["coefficient_relative_tolerances"] == {
        "cl": 0.03,
        "cd": 0.05,
        "cmy": 0.05,
    }
    assert report["runtime"]["cfl_number"] == 100.0
    assert report["runtime"]["output_files"] == ["RESTART_ASCII"]
    assert report["feature_extents"]["span_m"] == pytest.approx(33.0)
    assert report["stability_selection"]["selected_case"]["mesh_size"] == 0.09
    assert report["stability_selection"]["ineligible_cases"] == []
    assert report["stability_selection"]["compared_to_case"]["mesh_size"] == 0.06
    assert report["cases"][1]["volume_element_count"] == 110_000
    assert report["engineering_assessment"] == {
        "solver_stability_evidence": True,
        "aero_coefficients_interpretable": False,
        "interpretation_level": "solver_stability_only_no_boundary_layer_prisms",
        "reason": "adjacent_converged_mesh_coefficients_within_tolerance_but_no_bl_prism_mesh",
    }
    assert Path(report["report_path"]).exists()
