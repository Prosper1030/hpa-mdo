from pathlib import Path
import shutil

import pytest

from hpa_meshing.mesh_native.gmsh_polyhedral import (
    _cfd_evidence_gate,
    _boundary_layer_mesh_quality_gate,
    _coefficient_sanity_gate,
    _mesh_quality_gate,
    build_wing_feature_refinement_boxes,
    infer_wing_feature_extents,
    run_faceted_volume_refinement_ladder,
    run_faceted_volume_su2_smoke,
    write_boundary_layer_block_core_tet_mesh,
    write_faceted_volume_mesh,
    write_faceted_volume_mesh_with_boundary_layer,
    write_faceted_volume_su2_case,
)
from hpa_meshing.mesh_native.near_wall_block import (
    BoundaryLayerBlockSpec,
    build_boundary_layer_block_boundary_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.su2_structured import parse_su2_marker_summary
from hpa_meshing.mesh_native.wing_surface import (
    Reference,
    Station,
    WingSpec,
    build_farfield_box_surface,
    build_wing_surface,
)


def _rect_loop():
    return [
        (1.0, 0.05),
        (0.0, 0.05),
        (0.0, -0.05),
        (1.0, -0.05),
    ]


def _wing_and_close_farfield():
    wing = build_wing_surface(
        WingSpec(
            stations=[
                Station(y=0.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
                Station(y=1.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
                Station(y=2.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
            ],
            side="full",
            te_rule="finite_thickness",
            tip_rule="planar_cap",
            root_rule="wall_cap",
            reference=Reference(sref_full=2.0, cref=1.0, bref_full=2.0),
        )
    )
    farfield = build_farfield_box_surface(
        wing,
        upstream_factor=1.5,
        downstream_factor=2.0,
        lateral_factor=1.5,
        vertical_factor=1.5,
    )
    return wing, farfield


def _simple_wing_spec() -> WingSpec:
    return WingSpec(
        stations=[
            Station(y=0.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
            Station(y=1.0, airfoil_xz=_rect_loop(), chord=0.8, twist_deg=2.0),
            Station(y=2.0, airfoil_xz=_rect_loop(), chord=0.6, twist_deg=4.0),
        ],
        side="full",
        te_rule="finite_thickness",
        tip_rule="planar_cap",
        root_rule="wall_cap",
        reference=Reference(sref_full=1.6, cref=0.8, bref_full=2.0),
    )


def test_write_faceted_volume_mesh_preserves_su2_boundary_markers(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()
    msh_path = tmp_path / "faceted_wing_volume.msh"
    su2_path = tmp_path / "faceted_wing_volume.su2"

    report = write_faceted_volume_mesh(
        wing,
        farfield,
        msh_path,
        su2_path=su2_path,
        mesh_size=2.0,
    )

    assert report["status"] == "meshed"
    assert report["volume_count"] == 1
    assert report["volume_element_count"] > 0
    assert report["node_count"] > 0
    assert report["surface_triangle_count"] == 36
    assert report["quality_metrics"]["tetra_element_count"] == report["volume_element_count"]
    assert report["quality_metrics"]["non_positive_min_sicn_count"] == 0
    assert report["quality_metrics"]["non_positive_volume_count"] == 0
    assert report["quality_metrics"]["min_gamma"] > 0.0
    assert report["production_scale_gate"]["target_volume_elements"] == 1_000_000
    assert report["production_scale_gate"]["status"] == "underresolved"
    assert report["physical_groups"]["wing_wall"]["dimension"] == 2
    assert report["physical_groups"]["farfield"]["dimension"] == 2
    assert report["physical_groups"]["fluid"]["dimension"] == 3
    assert report["physical_groups"]["wing_wall"]["entity_count"] == 24
    assert report["physical_groups"]["farfield"]["entity_count"] == 12
    assert msh_path.exists()
    assert su2_path.exists()

    su2_summary = parse_su2_marker_summary(su2_path)
    assert su2_summary["ndime"] == 3
    assert su2_summary["nelem"] == report["volume_element_count"]
    assert su2_summary["nmark"] == 2
    assert set(su2_summary["markers"]) == {"wing_wall", "farfield"}
    assert su2_summary["markers"]["wing_wall"]["element_count"] > 0
    assert su2_summary["markers"]["farfield"]["element_count"] > 0


def test_write_boundary_layer_block_core_tet_mesh_uses_owned_bl_block_boundary(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")
    block = build_wing_boundary_layer_block(
        _simple_wing_spec(),
        BoundaryLayerBlockSpec(
            first_layer_height_m=0.01,
            growth_ratio=1.2,
            layer_count=2,
        ),
    )
    boundary = build_boundary_layer_block_boundary_surface(block)
    farfield = build_farfield_box_surface(
        boundary,
        upstream_factor=1.5,
        downstream_factor=2.0,
        lateral_factor=1.5,
        vertical_factor=1.5,
    )

    report = write_boundary_layer_block_core_tet_mesh(
        block,
        farfield,
        tmp_path / "core.msh",
        su2_path=tmp_path / "core.su2",
        mesh_size=0.8,
        farfield_mesh_size=1.5,
    )

    assert report["status"] == "meshed"
    assert report["route"] == "mesh_native_bl_block_core_tet_smoke"
    assert report["volume_element_count"] > 0
    assert report["volume_element_type_counts"].get("4", 0) == report["volume_element_count"]
    assert report["mesh_quality_gate"]["status"] == "pass"
    assert report["inner_boundary"]["marker_counts"] == {
        "bl_outer_interface": 10,
        "wake_cut": 2,
        "span_cap": 8,
    }
    assert report["inner_boundary"]["generated_mesh_element_counts"][
        "bl_outer_interface"
    ]["element_count"] > report["inner_boundary"]["input_mesh_element_counts"][
        "bl_outer_interface"
    ][
        "triangulated_face_count"
    ]
    assert report["interface_conformality"]["status"] == "remeshed"
    assert report["interface_conformality"]["can_merge_with_owned_bl_block"] is False
    assert "bl_outer_interface" in report["interface_conformality"]["remeshed_markers"]
    assert "wing_wall" not in report["physical_groups"]
    assert report["physical_groups"]["bl_outer_interface"]["entity_count"] > 0
    assert report["physical_groups"]["wake_cut"]["entity_count"] > 0
    assert report["physical_groups"]["span_cap"]["entity_count"] > 0
    assert report["physical_groups"]["farfield"]["entity_count"] == 12
    assert "not a final conformal BL+core merge" in report["caveats"][0]

    su2_summary = parse_su2_marker_summary(tmp_path / "core.su2")
    assert set(su2_summary["markers"]) == {
        "bl_outer_interface",
        "wake_cut",
        "span_cap",
        "farfield",
    }


def test_write_boundary_layer_block_core_tet_mesh_can_preserve_input_interface(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")
    block = build_wing_boundary_layer_block(
        _simple_wing_spec(),
        BoundaryLayerBlockSpec(
            first_layer_height_m=0.01,
            growth_ratio=1.2,
            layer_count=2,
        ),
    )
    boundary = build_boundary_layer_block_boundary_surface(block)
    farfield = build_farfield_box_surface(
        boundary,
        upstream_factor=1.5,
        downstream_factor=2.0,
        lateral_factor=1.5,
        vertical_factor=1.5,
    )

    report = write_boundary_layer_block_core_tet_mesh(
        block,
        farfield,
        tmp_path / "core_preserved.msh",
        su2_path=tmp_path / "core_preserved.su2",
        mesh_size=10.0,
        farfield_mesh_size=10.0,
        preserve_boundary_mesh=True,
    )

    assert report["status"] == "meshed"
    assert report["volume_element_type_counts"].get("7", 0) > 0
    assert report["quality_metrics"]["pyramid_element_count"] == report[
        "volume_element_type_counts"
    ]["7"]
    assert report["quality_metrics"]["volume_element_count"] == report[
        "volume_element_count"
    ]
    assert report["interface_conformality"]["status"] == "preserved"
    assert report["interface_conformality"]["can_merge_with_owned_bl_block"] is True
    assert report["interface_conformality"]["expected_boundary_representation"] == "native"
    assert report["interface_conformality"]["remeshed_markers"] == []
    assert report["inner_boundary"]["generated_mesh_element_counts"][
        "bl_outer_interface"
    ]["element_type_counts"] == {"3": 10}
    assert report["bl_block_coupling"]["can_merge_core_with_bl_block"] is False
    assert report["bl_block_coupling"]["unmatched_core_interface_face_count"] > 0
    assert report["mesh_sizing"]["preserve_boundary_mesh"] is True


def test_write_faceted_volume_mesh_with_boundary_layer_writes_mixed_su2_mesh(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()
    msh_path = tmp_path / "faceted_wing_bl_volume.msh"
    su2_path = tmp_path / "faceted_wing_bl_volume.su2"

    report = write_faceted_volume_mesh_with_boundary_layer(
        wing,
        farfield,
        msh_path,
        su2_path=su2_path,
        mesh_size=2.0,
        boundary_layer_first_height=0.005,
        boundary_layer_growth_ratio=1.3,
        boundary_layer_layers=3,
    )

    assert report["status"] == "meshed"
    assert report["route"] == "mesh_native_faceted_gmsh_boundary_layer_volume"
    assert report["volume_element_count"] > 0
    assert report["boundary_layer"]["layers"] == 3
    assert report["boundary_layer"]["total_thickness_m"] == pytest.approx(
        0.005 + 0.005 * 1.3 + 0.005 * 1.3**2
    )
    assert report["boundary_layer"]["volume_element_type_counts"]
    assert report["boundary_layer"]["quality_metrics"]["element_count"] > 0
    assert report["core_volume"]["volume_element_type_counts"]
    assert report["physical_groups"]["wing_wall"]["entity_count"] == 24
    assert report["physical_groups"]["farfield"]["entity_count"] == 12
    assert report["mesh_quality_gate"]["status"] == "pass"

    su2_summary = parse_su2_marker_summary(su2_path)
    assert su2_summary["ndime"] == 3
    assert su2_summary["nelem"] == report["volume_element_count"]
    assert set(su2_summary["markers"]) == {"wing_wall", "farfield"}
    assert su2_summary["markers"]["wing_wall"]["element_count"] > 0
    assert su2_summary["markers"]["farfield"]["element_count"] > 0


def test_write_faceted_volume_mesh_supports_wing_local_sizing(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    coarse = write_faceted_volume_mesh(
        wing,
        farfield,
        tmp_path / "coarse.msh",
        mesh_size=3.0,
    )
    locally_refined = write_faceted_volume_mesh(
        wing,
        farfield,
        tmp_path / "wing_local.msh",
        mesh_size=3.0,
        wing_mesh_size=1.0,
        farfield_mesh_size=3.0,
    )

    assert locally_refined["mesh_sizing"]["default_mesh_size"] == 3.0
    assert locally_refined["mesh_sizing"]["wing_mesh_size"] == 1.0
    assert locally_refined["mesh_sizing"]["farfield_mesh_size"] == 3.0
    assert locally_refined["mesh_sizing"]["wing_refinement_radius"] == 3.0
    assert locally_refined["mesh_sizing"]["background_field"]["type"] == "DistanceThreshold"
    assert locally_refined["volume_element_count"] > coarse["volume_element_count"]
    assert locally_refined["mesh_quality_gate"]["status"] == "pass"


def test_build_wing_feature_refinement_boxes_materializes_te_tip_wake_regions():
    wing, _farfield = _wing_and_close_farfield()

    boxes = build_wing_feature_refinement_boxes(wing, mesh_size=0.5)

    assert [box["name"] for box in boxes] == [
        "trailing_edge_refinement_region",
        "tip_left_refinement_region",
        "tip_right_refinement_region",
        "wake_refinement_region",
    ]
    assert all(box["size"] == 0.5 for box in boxes)
    assert boxes[0]["x_min"] < wing.bounds()["x_max"] < boxes[0]["x_max"]
    assert boxes[1]["y_min"] == pytest.approx(wing.bounds()["y_min"])
    assert boxes[2]["y_max"] == pytest.approx(wing.bounds()["y_max"])
    assert boxes[3]["x_min"] == pytest.approx(wing.bounds()["x_max"])
    assert boxes[3]["x_max"] > boxes[3]["x_min"]


def test_infer_wing_feature_extents_reports_chord_span_tips_and_edges():
    wing, _farfield = _wing_and_close_farfield()

    extents = infer_wing_feature_extents(wing)

    assert extents["leading_edge_x"] == pytest.approx(0.0)
    assert extents["trailing_edge_x"] == pytest.approx(1.0)
    assert extents["tip_left_y"] == pytest.approx(0.0)
    assert extents["tip_right_y"] == pytest.approx(2.0)
    assert extents["chord_extent_m"] == pytest.approx(1.0)
    assert extents["span_m"] == pytest.approx(2.0)
    assert extents["z_min"] == pytest.approx(-0.05)
    assert extents["z_max"] == pytest.approx(0.05)


def test_write_faceted_volume_mesh_supports_box_refinement_fields(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()
    boxes = build_wing_feature_refinement_boxes(wing, mesh_size=0.75)

    coarse = write_faceted_volume_mesh(
        wing,
        farfield,
        tmp_path / "coarse_feature_baseline.msh",
        mesh_size=3.0,
        wing_mesh_size=2.0,
        farfield_mesh_size=3.0,
    )
    report = write_faceted_volume_mesh(
        wing,
        farfield,
        tmp_path / "feature_boxes.msh",
        mesh_size=3.0,
        wing_mesh_size=2.0,
        farfield_mesh_size=3.0,
        refinement_boxes=boxes,
    )

    background = report["mesh_sizing"]["background_field"]
    assert background["type"] == "Min"
    assert [field["type"] for field in background["fields"]] == [
        "DistanceThreshold",
        "Box",
        "Box",
        "Box",
        "Box",
    ]
    assert report["mesh_sizing"]["refinement_boxes"][0]["name"] == (
        "trailing_edge_refinement_region"
    )
    assert report["volume_element_count"] > coarse["volume_element_count"]
    assert report["mesh_quality_gate"]["status"] == "pass"


def test_mesh_quality_gate_warns_on_near_zero_positive_tets():
    gate = _mesh_quality_gate(
        {
            "tetra_element_count": 1,
            "non_positive_min_sicn_count": 0,
            "non_positive_min_sige_count": 0,
            "non_positive_volume_count": 0,
            "min_gamma": 1.0e-7,
            "min_sicn": 5.0e-5,
            "gamma_percentiles": {"p01": 0.005, "p05": 0.02, "p50": 0.3},
        }
    )

    assert gate["status"] == "pass"
    assert "very_low_min_gamma" in gate["warnings"]
    assert "very_low_min_sicn" in gate["warnings"]
    assert "low_p01_gamma" in gate["warnings"]


def test_boundary_layer_mesh_quality_gate_blocks_bad_prisms():
    gate = _boundary_layer_mesh_quality_gate(
        core_quality_metrics={
            "tetra_element_count": 10,
            "non_positive_min_sicn_count": 0,
            "non_positive_min_sige_count": 0,
            "non_positive_volume_count": 0,
            "min_gamma": 0.2,
            "min_sicn": 0.2,
            "gamma_percentiles": {"p01": 0.2},
        },
        boundary_layer_quality_metrics={
            "element_count": 100,
            "non_positive_min_sicn_count": 1,
            "non_positive_min_sige_count": 1,
            "non_positive_volume_count": 0,
            "min_sicn_percentiles": {"p01": 0.001},
        },
    )

    assert gate["status"] == "fail"
    assert "boundary_layer_non_positive_min_sicn" in gate["blockers"]
    assert "boundary_layer_non_positive_min_sige" in gate["blockers"]
    assert "boundary_layer_low_p01_min_sicn" in gate["warnings"]


def test_cfd_evidence_gate_rejects_short_iteration_budget():
    gate = _cfd_evidence_gate(
        max_iterations=100,
        min_iterations=1000,
        iterative_gate_status="pass",
        history={"final_iteration": 70},
    )

    assert gate["status"] == "fail"
    assert gate["minimum_iterations"] == 1000
    assert gate["configured_max_iterations"] == 100
    assert gate["observed_final_iteration"] == 70
    assert gate["reasons"] == ["iteration_budget_below_cfd_evidence_minimum"]


def test_cfd_evidence_gate_accepts_long_budget_with_iterative_pass():
    gate = _cfd_evidence_gate(
        max_iterations=1200,
        min_iterations=1000,
        iterative_gate_status="pass",
        history={"final_iteration": 780},
    )

    assert gate["status"] == "pass"
    assert gate["reasons"] == []


def test_coefficient_sanity_gate_rejects_negative_drag():
    gate = _coefficient_sanity_gate(
        {
            "final_coefficients": {
                "cl": 0.696,
                "cd": -0.148,
                "cmy": 0.137,
            }
        }
    )

    assert gate["status"] == "fail"
    assert gate["reasons"] == ["negative_cd"]


def test_run_faceted_volume_refinement_ladder_increases_mesh_density(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    report = run_faceted_volume_refinement_ladder(
        wing,
        farfield,
        tmp_path / "ladder",
        mesh_sizes=(3.0, 2.0, 1.0),
        target_volume_elements=1_000,
        max_volume_elements=5_000,
    )

    counts = [case["volume_element_count"] for case in report["cases"]]
    assert counts == sorted(counts)
    assert counts[-1] >= 1_000
    assert report["status"] == "target_reached"
    assert report["selected_case"]["mesh_size"] == 1.0
    assert report["selected_case"]["production_scale_gate"]["status"] == "meets_target"


def test_run_faceted_volume_refinement_ladder_respects_cell_budget(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    report = run_faceted_volume_refinement_ladder(
        wing,
        farfield,
        tmp_path / "budget_ladder",
        mesh_sizes=(3.0, 2.0, 1.0),
        target_volume_elements=1_000_000,
        max_volume_elements=500,
    )

    assert report["status"] == "blocked_by_volume_element_guard"
    assert report["selected_case"] is None
    assert report["cases"][-1]["volume_element_count"] > 500


def test_write_faceted_volume_su2_case_materializes_marker_audit(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    report = write_faceted_volume_su2_case(
        wing,
        farfield,
        tmp_path / "faceted_case",
        ref_area=2.0,
        ref_length=1.0,
        mesh_size=2.0,
        max_iterations=3,
    )

    assert report["route"] == "mesh_native_faceted_gmsh_volume_su2_smoke_case"
    assert report["mesh_report"]["status"] == "meshed"
    assert report["mesh_report"]["volume_element_count"] > 0
    assert report["marker_audit"]["status"] == "pass"
    assert Path(report["mesh_path"]).exists()
    assert Path(report["runtime_cfg_path"]).exists()
    assert Path(report["report_path"]).exists()


def test_write_faceted_volume_su2_case_accepts_su2_numerics_profile(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    report = write_faceted_volume_su2_case(
        wing,
        farfield,
        tmp_path / "faceted_jst_case",
        ref_area=2.0,
        ref_length=1.0,
        mesh_size=2.0,
        max_iterations=300,
        conv_num_method_flow="JST",
        cfl_number=100.0,
        linear_solver_error="1e-12",
        linear_solver_iter=25,
        jst_sensor_coeff=(0.0, 0.02),
        conv_cauchy_elems=50,
        conv_cauchy_eps="1E-6",
        output_files=("RESTART_ASCII",),
    )

    cfg_text = Path(report["runtime_cfg_path"]).read_text(encoding="utf-8")
    assert "CONV_NUM_METHOD_FLOW= JST" in cfg_text
    assert "JST_SENSOR_COEFF= ( 0, 0.02 )" in cfg_text
    assert "CFL_NUMBER= 100" in cfg_text
    assert "LINEAR_SOLVER_ERROR= 1e-12" in cfg_text
    assert "LINEAR_SOLVER_ITER= 25" in cfg_text
    assert "CONV_CAUCHY_ELEMS= 50" in cfg_text
    assert "CONV_CAUCHY_EPS= 1E-6" in cfg_text
    assert "OUTPUT_FILES= (RESTART_ASCII)" in cfg_text
    assert report["runtime"]["conv_num_method_flow"] == "JST"
    assert report["runtime"]["cfl_number"] == 100.0
    assert report["runtime"]["output_files"] == ["RESTART_ASCII"]


def test_write_faceted_volume_su2_case_supports_adiabatic_no_slip_wall_profile(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    report = write_faceted_volume_su2_case(
        wing,
        farfield,
        tmp_path / "faceted_ns_case",
        ref_area=2.0,
        ref_length=1.0,
        mesh_size=2.0,
        solver="INC_NAVIER_STOKES",
        wall_profile="adiabatic_no_slip",
    )

    cfg_text = Path(report["runtime_cfg_path"]).read_text(encoding="utf-8")
    assert "SOLVER= INC_NAVIER_STOKES" in cfg_text
    assert "MARKER_HEATFLUX= ( wing_wall, 0.0 )" in cfg_text
    assert "MARKER_EULER= ( wing_wall )" not in cfg_text
    assert report["marker_audit"]["status"] == "pass"
    assert report["runtime"]["wall_profile"] == "adiabatic_no_slip"


def test_run_faceted_volume_su2_smoke_runs_when_su2_is_available(tmp_path: Path):
    pytest.importorskip("gmsh")
    solver = shutil.which("SU2_CFD")
    if solver is None:
        pytest.skip("SU2_CFD not available")

    wing, farfield = _wing_and_close_farfield()
    report = run_faceted_volume_su2_smoke(
        wing,
        farfield,
        tmp_path / "faceted_solver_case",
        ref_area=2.0,
        ref_length=1.0,
        mesh_size=2.0,
        max_iterations=3,
        solver_command=solver,
        threads=1,
    )

    assert report["run_status"] == "completed"
    assert report["returncode"] == 0
    assert report["marker_audit"]["status"] == "pass"
    assert report["mesh_report"]["volume_element_count"] > 0
    assert Path(report["history_path"]).exists()
    assert Path(report["solver_log_path"]).exists()
    assert report["history"]["final_iteration"] == 2
    assert report["history"]["final_coefficients"]["cl"] is not None
    assert report["history"]["final_coefficients"]["cd"] is not None
    assert report["iterative_gate_status"] == "fail"
    assert report["iterative_gate"]["status"] == "fail"
    assert report["engineering_assessment"] == {
        "solver_readability": "pass",
        "marker_ownership": "pass",
        "iterative_convergence": "fail",
        "cfd_evidence": "fail",
        "coefficient_sanity": "fail",
        "aero_coefficients_interpretable": False,
        "reason": "case_level_cfd_gate_not_passed",
    }
