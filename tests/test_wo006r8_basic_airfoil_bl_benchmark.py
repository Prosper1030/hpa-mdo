from pathlib import Path

import pytest

from scripts.run_wo006r8_basic_airfoil_bl_benchmark import (
    BasicAirfoilCase,
    build_basic_airfoil_case,
    coefficient_sanity_gate,
    naca4_airfoil_loop,
    parse_su2_history,
    write_basic_airfoil_bl_mesh,
    write_su2_config,
)


def test_naca4412_loop_is_cambered_and_ordered_for_bl_meshing() -> None:
    loop = naca4_airfoil_loop("4412", points_per_side=41)

    assert len(loop) == 81
    assert loop[0][0] > 0.99
    leading_edge = min(loop, key=lambda point: point[0])
    assert leading_edge[0] == pytest.approx(0.0, abs=2.0e-4)
    upper_mid = max(point[1] for point in loop if 0.35 < point[0] < 0.45)
    lower_mid = min(point[1] for point in loop if 0.35 < point[0] < 0.45)
    assert upper_mid > abs(lower_mid)
    assert upper_mid > 0.07


def test_basic_airfoil_case_uses_hpa_re_and_0xx_drag_expectation() -> None:
    case = build_basic_airfoil_case()

    assert case.airfoil == "NACA4412"
    assert case.chord_m == pytest.approx(1.130189765)
    assert case.velocity_mps == pytest.approx(6.5)
    assert case.reynolds_number == pytest.approx(5.03e5, rel=0.02)
    assert 0.45 <= case.expected_cl <= 0.95
    assert case.expected_cd_range[0] < 0.02
    assert case.expected_cd_range[1] <= 0.08
    assert case.absurd_cd_threshold == pytest.approx(0.20)
    assert case.boundary_layer.first_layer_height_m <= 6.0e-5
    assert case.boundary_layer.layer_count >= 24


def test_write_su2_config_uses_viscous_rans_no_slip_airfoil_setup(tmp_path: Path) -> None:
    case = build_basic_airfoil_case(max_iterations=777)
    cfg_path = tmp_path / "su2_runtime.cfg"

    write_su2_config(case, cfg_path)
    cfg = cfg_path.read_text(encoding="utf-8")

    assert "SOLVER= INC_RANS" in cfg
    assert "KIND_TURB_MODEL= SA" in cfg
    assert "INC_NONDIM= INITIAL_VALUES" in cfg
    assert "MU_CONSTANT= 1.789400e-05" in cfg
    assert "INC_VELOCITY_INIT= ( 6." in cfg
    assert "MARKER_HEATFLUX= ( airfoil, 0.0 )" in cfg
    assert "MARKER_FAR= ( farfield )" in cfg
    assert "MARKER_MONITORING= ( airfoil )" in cfg
    assert "REF_AREA= 1.130190" in cfg
    assert "REF_LENGTH= 1.130190" in cfg
    assert "ITER= 777" in cfg
    assert "CONV_NUM_METHOD_FLOW= FDS" in cfg
    assert "CONV_NUM_METHOD_TURB= SCALAR_UPWIND" in cfg


def test_coefficient_sanity_gate_rejects_order_of_magnitude_drag() -> None:
    case = build_basic_airfoil_case()

    gate = coefficient_sanity_gate(
        case,
        {"cl": 0.72, "cd": 0.55, "cmy": -0.03},
        stable_window={"cd_relative_span": 0.005, "cl_relative_span": 0.005},
    )

    assert gate["status"] == "fail"
    assert "cd_absurd_high_for_basic_airfoil" in gate["blockers"]
    assert gate["engineering_read"] == "reject_solver_output"


def test_parse_su2_history_reports_tail_force_stability(tmp_path: Path) -> None:
    history = tmp_path / "history.csv"
    history.write_text(
        "\n".join(
            [
                '"Inner_Iter","CL","CD","CMy","rms[Rho]"',
                "1,0.60,0.030,-0.020,-3.0",
                "2,0.61,0.031,-0.021,-3.2",
                "3,0.605,0.0305,-0.0205,-3.3",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_su2_history(history, tail_window=3)

    assert parsed["row_count"] == 3
    assert parsed["final_iteration"] == 3
    assert parsed["final_coefficients"] == {
        "cl": pytest.approx(0.605),
        "cd": pytest.approx(0.0305),
        "cmy": pytest.approx(-0.0205),
    }
    assert parsed["tail_stability"]["cl_relative_span"] < 0.02
    assert parsed["tail_stability"]["cd_relative_span"] < 0.04


def test_write_basic_airfoil_bl_mesh_materializes_bl_quads_and_markers(tmp_path: Path) -> None:
    pytest.importorskip("gmsh")
    case = BasicAirfoilCase(
        **{
            **build_basic_airfoil_case(points_per_side=25).__dict__,
            "farfield_radius_chord": 8.0,
            "farfield_mesh_size_chord": 1.0,
            "airfoil_mesh_size_chord": 0.04,
        }
    )

    report = write_basic_airfoil_bl_mesh(case, tmp_path)

    assert Path(report["mesh_path"]).exists()
    assert Path(report["su2_mesh_path"]).exists()
    assert report["status"] == "meshed"
    assert report["physical_groups"]["airfoil"]["dimension"] == 1
    assert report["physical_groups"]["farfield"]["dimension"] == 1
    assert report["physical_groups"]["fluid"]["dimension"] == 2
    assert report["cell_type_counts"].get("3", 0) > 0
    assert report["boundary_layer_quad_count"] > 0
    assert report["marker_summary"]["markers"]["airfoil"]["element_count"] > 0
    assert report["marker_summary"]["markers"]["farfield"]["element_count"] > 0
