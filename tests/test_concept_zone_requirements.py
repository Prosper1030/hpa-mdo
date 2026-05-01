from __future__ import annotations

import math

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.concept.airfoil_cst import CSTAirfoilTemplate, build_lofting_guides
from hpa_mdo.concept.atmosphere import interpolate_sea_level_air_properties
from hpa_mdo.concept.geometry import GeometryConcept, build_linear_wing_stations
from hpa_mdo.concept.zone_requirements import ZoneDefinition
from hpa_mdo.concept.zone_requirements import build_zone_requirements, default_zone_definitions


def _sample_load() -> SpanwiseLoad:
    return SpanwiseLoad(
        y=np.array([0.0, 2.0, 4.0, 6.0, 8.0]),
        chord=np.array([1.30, 1.10, 0.90, 0.70, 0.50]),
        cl=np.array([0.90, 0.88, 0.82, 0.75, 0.68]),
        cd=np.array([0.020, 0.019, 0.018, 0.017, 0.016]),
        cm=np.array([-0.12, -0.11, -0.10, -0.09, -0.08]),
        lift_per_span=np.array([120.0, 110.0, 100.0, 85.0, 60.0]),
        drag_per_span=np.array([2.4, 2.1, 1.8, 1.5, 1.1]),
        aoa_deg=6.0,
        velocity=8.0,
        dynamic_pressure=36.8,
    )


def test_build_zone_requirements_uses_station_geometry_for_zone_assignment() -> None:
    concept = GeometryConcept(
        span_m=16.0,
        wing_area_m2=14.4,
        root_chord_m=1.30,
        tip_chord_m=0.50,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.0, 1.0, 4.0, 2.0),
    )
    stations = build_linear_wing_stations(concept, stations_per_half=5)

    load = SpanwiseLoad(
        y=np.array([0.0, 0.2, 0.4, 1.0, 0.6]),
        chord=np.array([1.30, 1.15, 1.00, 0.80, 0.50]),
        cl=np.array([0.90, 0.89, 0.84, 0.78, 0.70]),
        cd=np.array([0.020, 0.019, 0.018, 0.017, 0.016]),
        cm=np.array([-0.12, -0.11, -0.10, -0.09, -0.08]),
        lift_per_span=np.array([120.0, 112.0, 101.0, 86.0, 62.0]),
        drag_per_span=np.array([2.4, 2.1, 1.8, 1.5, 1.1]),
        aoa_deg=6.0,
        velocity=8.0,
        dynamic_pressure=36.8,
    )

    zone_requirements = build_zone_requirements(
        load,
        stations,
        default_zone_definitions(),
    )

    assert set(zone_requirements) == {"root", "mid1", "mid2", "tip"}
    assert len(zone_requirements["root"].points) == 2
    assert len(zone_requirements["mid1"].points) == 1
    assert len(zone_requirements["mid2"].points) == 1
    assert len(zone_requirements["tip"].points) == 1
    assert zone_requirements["root"].min_tc_ratio == 0.14
    assert zone_requirements["tip"].min_tc_ratio == 0.10

    expected_density = 2.0 * load.dynamic_pressure / (load.velocity**2)
    expected_reynolds = expected_density * load.velocity * 1.30 / 1.8e-5
    assert math.isclose(zone_requirements["root"].points[0].reynolds, expected_reynolds, rel_tol=1e-12)
    assert zone_requirements["root"].points[0].chord_m == pytest.approx(1.30)
    assert zone_requirements["root"].points[0].cl_target == 0.90
    assert zone_requirements["root"].points[0].cm_target == -0.12
    weights = [point.weight for requirement in zone_requirements.values() for point in requirement.points]
    assert all(weight > 0.0 for weight in weights)
    assert len({round(weight, 12) for weight in weights}) > 1


def test_build_zone_requirements_accepts_temperature_table_viscosity_for_reynolds() -> None:
    concept = GeometryConcept(
        span_m=16.0,
        wing_area_m2=14.4,
        root_chord_m=1.30,
        tip_chord_m=0.50,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.0, 1.0, 4.0, 2.0),
    )
    stations = build_linear_wing_stations(concept, stations_per_half=5)
    air_props = interpolate_sea_level_air_properties(33.5)

    zone_requirements = build_zone_requirements(
        _sample_load(),
        stations,
        default_zone_definitions(),
        dynamic_viscosity_pa_s=air_props.dynamic_viscosity_pa_s,
    )

    expected_density = 2.0 * _sample_load().dynamic_pressure / (_sample_load().velocity**2)
    expected_reynolds = (
        expected_density
        * _sample_load().velocity
        * 1.30
        / air_props.dynamic_viscosity_pa_s
    )
    assert zone_requirements["root"].points[0].reynolds == pytest.approx(expected_reynolds)


@pytest.mark.parametrize(
    "zone_definitions",
    [
        (
            ZoneDefinition("root", 0.00, 0.30),
            ZoneDefinition("mid1", 0.25, 0.55),
            ZoneDefinition("mid2", 0.55, 0.80),
            ZoneDefinition("tip", 0.80, 1.00),
        ),
        (
            ZoneDefinition("root", 0.00, 0.25),
            ZoneDefinition("mid1", 0.25, 0.50),
            ZoneDefinition("mid2", 0.60, 0.80),
            ZoneDefinition("tip", 0.80, 1.00),
        ),
    ],
)
def test_build_zone_requirements_rejects_invalid_zone_definitions(zone_definitions) -> None:
    concept = GeometryConcept(
        span_m=16.0,
        wing_area_m2=14.4,
        root_chord_m=1.30,
        tip_chord_m=0.50,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.0, 1.0, 4.0, 2.0),
    )
    stations = build_linear_wing_stations(concept, stations_per_half=5)

    with pytest.raises(ValueError):
        build_zone_requirements(_sample_load(), stations, zone_definitions)


def test_build_zone_requirements_rejects_duplicate_zone_names() -> None:
    concept = GeometryConcept(
        span_m=16.0,
        wing_area_m2=14.4,
        root_chord_m=1.30,
        tip_chord_m=0.50,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.0, 1.0, 4.0, 2.0),
    )
    stations = build_linear_wing_stations(concept, stations_per_half=5)

    duplicate_zones = (
        ZoneDefinition("root", 0.00, 0.25),
        ZoneDefinition("root", 0.25, 0.55),
        ZoneDefinition("mid2", 0.55, 0.80),
        ZoneDefinition("tip", 0.80, 1.00),
    )

    with pytest.raises(ValueError):
        build_zone_requirements(_sample_load(), stations, duplicate_zones)


def test_build_zone_requirements_rejects_mismatched_spanwise_load_lengths() -> None:
    concept = GeometryConcept(
        span_m=16.0,
        wing_area_m2=14.4,
        root_chord_m=1.30,
        tip_chord_m=0.50,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.0, 1.0, 4.0, 2.0),
    )
    stations = build_linear_wing_stations(concept, stations_per_half=5)
    load = SpanwiseLoad(
        y=np.array([0.0, 2.0, 4.0, 6.0, 8.0]),
        chord=np.array([1.30, 1.10, 0.90, 0.70]),
        cl=np.array([0.90, 0.88, 0.82, 0.75, 0.68]),
        cd=np.array([0.020, 0.019, 0.018, 0.017, 0.016]),
        cm=np.array([-0.12, -0.11, -0.10, -0.09, -0.08]),
        lift_per_span=np.array([120.0, 110.0, 100.0, 85.0, 60.0]),
        drag_per_span=np.array([2.4, 2.1, 1.8, 1.5, 1.1]),
        aoa_deg=6.0,
        velocity=8.0,
        dynamic_pressure=36.8,
    )

    with pytest.raises(ValueError):
        build_zone_requirements(load, stations, default_zone_definitions())


def test_build_lofting_guides_uses_cst_templates_as_authority() -> None:
    templates = {
        "root": CSTAirfoilTemplate("root", (0.2, 0.3, 0.1), (-0.1, -0.2, -0.05), 0.0015),
        "tip": CSTAirfoilTemplate("tip", (0.1, 0.2, 0.05), (-0.08, -0.15, -0.03), 0.0010),
    }

    guides = build_lofting_guides(templates)

    assert guides["authority"] == "cst_coefficients"
    assert guides["zones"] == ["root", "tip"]
    assert guides["blend_pairs"] == [("root", "tip")]
    assert guides["interpolation_rule"] == "linear_in_coeff_space"


def test_build_lofting_guides_canonicalizes_known_zone_order() -> None:
    templates = {
        "tip": CSTAirfoilTemplate("tip", (0.1, 0.2), (-0.08, -0.15), 0.0010),
        "mid2": CSTAirfoilTemplate("mid2", (0.12, 0.22), (-0.09, -0.16), 0.0011),
        "mid1": CSTAirfoilTemplate("mid1", (0.15, 0.25), (-0.10, -0.18), 0.0012),
        "root": CSTAirfoilTemplate("root", (0.2, 0.3), (-0.1, -0.2), 0.0015),
    }

    guides = build_lofting_guides(templates)

    assert guides["zones"] == ["root", "mid1", "mid2", "tip"]
    assert guides["blend_pairs"] == [("root", "mid1"), ("mid1", "mid2"), ("mid2", "tip")]


def test_build_lofting_guides_rejects_empty_or_incompatible_templates() -> None:
    with pytest.raises(ValueError):
        build_lofting_guides({})

    with pytest.raises(ValueError):
        build_lofting_guides(
            {
                "root": CSTAirfoilTemplate("root", (0.2, 0.3), (-0.1, -0.2), 0.0015),
                "tip": CSTAirfoilTemplate("tip", (0.1,), (-0.08,), 0.0010),
            }
        )

    with pytest.raises(ValueError):
        build_lofting_guides(
            {
                "root": CSTAirfoilTemplate("root-zone", (0.2, 0.3), (-0.1, -0.2), 0.0015),
                "tip": CSTAirfoilTemplate("tip", (0.2, 0.3), (-0.1, -0.2), 0.0010),
            }
        )
