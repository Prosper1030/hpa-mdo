import pytest

from hpa_meshing.mesh_native.cfd_advisory import (
    geometric_boundary_layer_total_thickness,
    hpa_main_wing_cfd_advisory,
    reynolds_number,
)
from hpa_meshing.mesh_native.mesh_stability import select_cheapest_stable_mesh
from hpa_meshing.mesh_native.su2_structured import _smoke_cfg_text
from hpa_meshing.mesh_native.wing_surface import SurfaceMesh


def test_hpa_main_wing_advisory_estimates_blackcat_reynolds_and_bl_targets():
    advisory = hpa_main_wing_cfd_advisory()

    re_values = advisory["flow_regime"]["reynolds_by_chord"]
    assert re_values["mean_aerodynamic_chord"] == pytest.approx(5.03e5, rel=0.01)
    assert re_values["root"] == pytest.approx(5.78e5, rel=0.01)
    assert re_values["tip"] == pytest.approx(1.94e5, rel=0.01)
    bl = advisory["boundary_layer_targets"]
    assert bl["recommended_wall_resolved_first_layer_height_m"] == pytest.approx(5.0e-5)
    assert bl["recommended_total_thickness_m"] == pytest.approx(
        geometric_boundary_layer_total_thickness(
            first_layer_height_m=5.0e-5,
            layers=24,
            growth_ratio=1.24,
        )
    )
    assert advisory["solver_sequence"][2]["solver"] == "INC_RANS"
    assert advisory["grid_independence_policy"]["max_iter"] == 2000


def test_reynolds_number_rejects_nonphysical_inputs():
    with pytest.raises(ValueError, match="velocity_mps"):
        reynolds_number(
            density_kgpm3=1.225,
            velocity_mps=0.0,
            length_m=1.0,
            dynamic_viscosity_pas=1.8e-5,
        )


def test_select_cheapest_stable_mesh_supports_relative_percent_tolerances():
    cases = [
        {
            "case_name": "coarse",
            "volume_element_count": 900_000,
            "history": {"final_coefficients": {"cl": 0.80, "cd": 0.090, "cmy": -0.12}},
        },
        {
            "case_name": "medium",
            "volume_element_count": 1_800_000,
            "history": {"final_coefficients": {"cl": 1.00, "cd": 0.050, "cmy": -0.20}},
        },
        {
            "case_name": "fine",
            "volume_element_count": 3_000_000,
            "history": {"final_coefficients": {"cl": 1.02, "cd": 0.052, "cmy": -0.205}},
        },
    ]

    selection = select_cheapest_stable_mesh(
        cases,
        coefficient_tolerances={"cl": 1.0, "cd": 1.0, "cmy": 1.0},
        coefficient_relative_tolerances={"cl": 0.03, "cd": 0.05, "cmy": 0.05},
    )

    assert selection["status"] == "stable_pair_found"
    assert selection["selected_case"]["case_name"] == "medium"
    assert selection["compared_to_case"]["case_name"] == "fine"
    assert selection["comparison"]["relative_deltas"]["cd"] == pytest.approx(
        abs(0.052 - 0.050) / 0.052
    )


def test_smoke_cfg_text_can_emit_incompressible_rans_wall_function_setup():
    wing = SurfaceMesh(vertices=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.2)], faces=[])

    cfg = _smoke_cfg_text(
        wing,
        solver="INC_RANS",
        turbulence_model="SA",
        transition_model="NONE",
        ref_area=17.5,
        ref_length=1.13,
        velocity_mps=6.5,
        alpha_deg=0.0,
        max_iterations=2000,
        wall_marker="wing_wall",
        farfield_marker="farfield",
        wall_profile="adiabatic_no_slip",
        conv_num_method_flow="FDS",
        wall_function="STANDARD_WALL_FUNCTION",
    )

    assert "SOLVER= INC_RANS" in cfg
    assert "KIND_TURB_MODEL= SA" in cfg
    assert "MARKER_HEATFLUX= ( wing_wall, 0.0 )" in cfg
    assert "MARKER_WALL_FUNCTIONS= ( wing_wall, STANDARD_WALL_FUNCTION )" in cfg
    assert "CONV_NUM_METHOD_TURB= SCALAR_UPWIND" in cfg
    assert "MUSCL_FLOW= YES" in cfg
