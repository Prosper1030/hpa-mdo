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
