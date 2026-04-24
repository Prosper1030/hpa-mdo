import pytest

from hpa_mdo.concept.mass_closure import close_area_mass


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
