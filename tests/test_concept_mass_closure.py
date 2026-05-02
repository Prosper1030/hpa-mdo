import math

import pytest

from hpa_mdo.concept.mass_closure import (
    close_area_mass,
    estimate_fixed_planform_mass,
    estimate_tube_system_mass_kg,
)


def test_close_area_mass_penalizes_large_area_low_wing_loading():
    low_loading = close_area_mass(
        wing_loading_target_Npm2=21.187,
        pilot_mass_kg=60.0,
        fixed_non_area_aircraft_mass_kg=39.0,
        wing_areal_density_kgpm2=0.22,
    )
    high_loading = close_area_mass(
        wing_loading_target_Npm2=34.0,
        pilot_mass_kg=60.0,
        fixed_non_area_aircraft_mass_kg=39.0,
        wing_areal_density_kgpm2=0.22,
    )

    assert low_loading.converged is True
    assert high_loading.converged is True
    assert low_loading.closed_wing_area_m2 == pytest.approx(
        low_loading.closed_gross_mass_kg * 9.80665 / 21.187
    )
    assert low_loading.closed_wing_area_m2 > 50.0
    assert high_loading.closed_wing_area_m2 < 32.0
    assert low_loading.closed_gross_mass_kg > high_loading.closed_gross_mass_kg + 4.0
    assert low_loading.mass_breakdown_kg["wing_area_dependent_kg"] == pytest.approx(
        low_loading.closed_wing_area_m2 * 0.22
    )


def test_close_area_mass_matches_gpt_pro_baseline_components():
    result = close_area_mass(
        wing_loading_target_Npm2=34.0,
        pilot_mass_kg=60.0,
        fixed_non_area_aircraft_mass_kg=24.0,
        tube_system_mass_kg=10.5,
        wing_areal_density_kgpm2=0.20,
        wing_fittings_base_kg=1.5,
        wire_terminal_mass_kg=0.6,
        extra_system_margin_kg=2.0,
        initial_wing_area_m2=105.0 * 9.80665 / 34.0,
    )

    assert result.converged is True
    assert result.closed_wing_area_m2 == pytest.approx(30.17, abs=0.02)
    assert result.closed_gross_mass_kg == pytest.approx(104.63, abs=0.03)
    assert result.mass_breakdown_kg["tube_system_kg"] == pytest.approx(10.5)


def test_estimate_fixed_planform_mass_keeps_area_independent_of_mass_proxy():
    result = estimate_fixed_planform_mass(
        wing_area_m2=31.5,
        pilot_mass_kg=64.0,
        fixed_non_area_aircraft_mass_kg=22.0,
        wing_areal_density_kgpm2=0.20,
        tube_system_mass_kg=10.0,
        wing_fittings_base_kg=1.5,
        wire_terminal_mass_kg=0.6,
        extra_system_margin_kg=2.0,
    )

    assert result.wing_area_m2 == pytest.approx(31.5)
    assert result.wing_area_dependent_mass_kg == pytest.approx(6.3)
    assert result.aircraft_empty_mass_kg == pytest.approx(42.4)
    assert result.gross_mass_kg == pytest.approx(106.4)
    assert result.mass_breakdown_kg["pilot_kg"] == pytest.approx(64.0)


def test_estimate_tube_system_mass_uniform_tube_matches_thin_wall_formula():
    span_m = 32.0
    diameter_m = 0.06
    wall_m = 0.0008
    density = 1600.0
    num_spars = 2
    num_wings = 2
    mass = estimate_tube_system_mass_kg(
        span_m=span_m,
        root_outer_diameter_m=diameter_m,
        tip_outer_diameter_m=diameter_m,
        root_wall_thickness_m=wall_m,
        tip_wall_thickness_m=wall_m,
        density_kg_per_m3=density,
        num_spars_per_wing=num_spars,
        num_wings=num_wings,
    )
    expected = (
        density
        * math.pi
        * diameter_m
        * wall_m
        * (span_m / 2.0)
        * num_spars
        * num_wings
    )
    assert mass == pytest.approx(expected, rel=1e-12)


def test_estimate_tube_system_mass_scales_linearly_with_span():
    base_kwargs = dict(
        root_outer_diameter_m=0.07,
        tip_outer_diameter_m=0.035,
        root_wall_thickness_m=0.0007,
        tip_wall_thickness_m=0.0004,
    )
    short = estimate_tube_system_mass_kg(span_m=30.0, **base_kwargs)
    long = estimate_tube_system_mass_kg(span_m=36.0, **base_kwargs)
    assert long == pytest.approx(short * 36.0 / 30.0, rel=1e-12)


def test_estimate_tube_system_mass_rejects_non_positive_dimensions():
    with pytest.raises(ValueError, match="root_outer_diameter_m"):
        estimate_tube_system_mass_kg(
            span_m=32.0,
            root_outer_diameter_m=0.0,
            tip_outer_diameter_m=0.05,
            root_wall_thickness_m=0.001,
            tip_wall_thickness_m=0.0005,
        )
