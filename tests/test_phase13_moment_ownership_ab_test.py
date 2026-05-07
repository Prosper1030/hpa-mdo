import numpy as np

from scripts.phase13_moment_ownership_ab_test import (
    MOMENT_AXES,
    OWNERSHIP_MODE_IDS,
    component_residual_by_axis,
)


def test_ownership_modes_cover_requested_diagnostics() -> None:
    assert OWNERSHIP_MODE_IDS == (
        "main_beam_my_about_main_spar",
        "front_rear_vertical_couple",
        "cm_off_baseline",
        "current_legacy_mode",
    )


def test_component_residual_by_axis_sums_named_moment_sources() -> None:
    components = {
        "applied_aero_force": np.array([1.0, 2.0, 3.0]),
        "applied_cm_torsion": np.array([0.0, -5.0, 0.0]),
        "root_reaction": np.array([-1.0, 0.5, 0.0]),
        "wire_reaction": np.array([0.0, 0.0, -2.0]),
        "link_front_rear_couple": np.array([0.0, 0.5, 1.0]),
    }

    residual = component_residual_by_axis(components)

    assert MOMENT_AXES == ("mx", "my", "mz")
    assert residual["mx_residual_nm"] == 0.0
    assert residual["my_residual_nm"] == -2.0
    assert residual["mz_residual_nm"] == 2.0
    assert residual["total_moment_residual_nm"] == np.sqrt(8.0)
