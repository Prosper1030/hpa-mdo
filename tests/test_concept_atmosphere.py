from __future__ import annotations

import pytest

from hpa_mdo.concept.atmosphere import (
    air_properties_from_environment,
    interpolate_sea_level_air_properties,
)


def test_sea_level_air_table_interpolates_density_and_viscosity() -> None:
    props_33 = interpolate_sea_level_air_properties(33.0)
    props_34 = interpolate_sea_level_air_properties(34.0)
    props_33_5 = interpolate_sea_level_air_properties(33.5)

    assert props_33.density_kg_per_m3 == pytest.approx(1.152956)
    assert props_33.dynamic_viscosity_pa_s == pytest.approx(1.875104437e-5)
    assert props_33_5.density_kg_per_m3 == pytest.approx(
        0.5 * (props_33.density_kg_per_m3 + props_34.density_kg_per_m3)
    )
    assert props_33_5.dynamic_viscosity_pa_s == pytest.approx(
        0.5 * (props_33.dynamic_viscosity_pa_s + props_34.dynamic_viscosity_pa_s)
    )
    assert props_33_5.kinematic_viscosity_m2_per_s == pytest.approx(
        props_33_5.dynamic_viscosity_pa_s / props_33_5.density_kg_per_m3
    )
    assert props_33_5.source == "sea_level_dry_air_table_linear_interpolation"


def test_air_properties_from_environment_applies_humidity_to_density() -> None:
    dry_props = air_properties_from_environment(
        temperature_c=33.0,
        relative_humidity_percent=0.0,
        altitude_m=0.0,
    )
    dry_table_props = interpolate_sea_level_air_properties(33.0)
    assert dry_props.density_kg_per_m3 == pytest.approx(dry_table_props.density_kg_per_m3)

    props = air_properties_from_environment(
        temperature_c=33.0,
        relative_humidity_percent=80.0,
        altitude_m=0.0,
    )

    assert props.density_kg_per_m3 == pytest.approx(1.1356685441577505)
    assert props.dynamic_viscosity_pa_s == pytest.approx(1.875104437e-5)
    assert props.kinematic_viscosity_m2_per_s == pytest.approx(
        props.dynamic_viscosity_pa_s / props.density_kg_per_m3
    )
    assert props.source == "sea_level_air_table_with_humidity_density_correction"
