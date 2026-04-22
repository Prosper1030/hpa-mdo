from __future__ import annotations

import math

import numpy as np

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.concept.airfoil_cst import CSTAirfoilTemplate, build_lofting_guides
from hpa_mdo.concept.geometry import GeometryConcept, build_linear_wing_stations
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


def test_build_zone_requirements_groups_operating_points_by_zone() -> None:
    concept = GeometryConcept(
        span_m=16.0,
        wing_area_m2=14.4,
        root_chord_m=1.30,
        tip_chord_m=0.50,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(2.5, 2.5, 3.0),
    )
    stations = build_linear_wing_stations(concept, stations_per_half=5)

    zone_requirements = build_zone_requirements(
        spanwise_load=_sample_load(),
        stations=stations,
        zone_definitions=default_zone_definitions(),
    )

    assert set(zone_requirements) == {"root", "mid1", "mid2", "tip"}
    assert len(zone_requirements["root"].points) == 1
    assert len(zone_requirements["mid1"].points) == 2
    assert len(zone_requirements["mid2"].points) == 1
    assert len(zone_requirements["tip"].points) == 1
    assert zone_requirements["root"].min_tc_ratio == 0.14
    assert zone_requirements["tip"].min_tc_ratio == 0.10

    expected_density = 2.0 * _sample_load().dynamic_pressure / (_sample_load().velocity**2)
    expected_reynolds = expected_density * _sample_load().velocity * 1.30 / 1.8e-5
    assert math.isclose(
        zone_requirements["root"].points[0].reynolds,
        expected_reynolds,
        rel_tol=1e-12,
    )
    assert zone_requirements["root"].points[0].cl_target == 0.90
    assert zone_requirements["root"].points[0].cm_target == -0.12
    assert zone_requirements["root"].points[0].weight == 1.0


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
