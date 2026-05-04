"""Tests for the per-zone airfoil picker used by the MIT-like loop."""

from __future__ import annotations

import math

from hpa_mdo.concept.zone_airfoil_picker import (
    ZoneAirfoilSpec,
    aerodynamic_summary,
    airfoil_templates_for_avl,
    chord_weighted_profile_cd,
    estimate_zone_profile_cd,
    select_zone_airfoils_from_library,
)


def _stub_zones() -> dict[str, dict[str, list[dict[str, float]]]]:
    return {
        "root": {
            "points": [
                {"cl_target": 1.05, "reynolds": 460000.0, "chord_m": 1.30, "weight": 1.0}
            ]
        },
        "mid1": {
            "points": [
                {"cl_target": 1.00, "reynolds": 380000.0, "chord_m": 1.05, "weight": 1.0}
            ]
        },
        "mid2": {
            "points": [
                {"cl_target": 0.85, "reynolds": 310000.0, "chord_m": 0.85, "weight": 1.0}
            ]
        },
        "tip": {
            "points": [
                {"cl_target": 0.55, "reynolds": 220000.0, "chord_m": 0.50, "weight": 1.0}
            ]
        },
    }


def test_picker_routes_inboard_to_fx76_outboard_to_clarky() -> None:
    selected = select_zone_airfoils_from_library(zone_requirements=_stub_zones())
    assert selected["root"].seed_name == "fx76mp140"
    assert selected["mid1"].seed_name == "fx76mp140"
    assert selected["mid2"].seed_name == "clarkysm"
    assert selected["tip"].seed_name == "clarkysm"


def test_picker_carries_alpha_l0_and_polar_for_each_zone() -> None:
    selected = select_zone_airfoils_from_library(zone_requirements=_stub_zones())
    for spec in selected.values():
        assert isinstance(spec, ZoneAirfoilSpec)
        assert spec.alpha_l0_deg < 0.0
        assert spec.cl_alpha_per_rad > 4.0
        assert spec.polar_cd0 > 0.0
        assert spec.polar_k > 0.0


def test_airfoil_templates_payload_is_avl_compatible() -> None:
    selected = select_zone_airfoils_from_library(zone_requirements=_stub_zones())
    templates = airfoil_templates_for_avl(selected)
    for zone_name, template in templates.items():
        assert "coordinates" in template
        coords = template["coordinates"]
        assert len(coords) >= 3
        for point in coords:
            assert len(point) == 2
            assert all(isinstance(value, float) for value in point)
        assert "geometry_hash" in template
        assert "template_id" in template
        assert template["selection_reason"]


def test_estimate_zone_profile_cd_uses_polar_at_cl_and_re() -> None:
    selected = select_zone_airfoils_from_library(zone_requirements=_stub_zones())
    per_zone = estimate_zone_profile_cd(
        selected=selected, zone_requirements=_stub_zones()
    )
    assert set(per_zone) == {"root", "mid1", "mid2", "tip"}
    for zone, info in per_zone.items():
        assert info["cd_profile"] > 0.0
        assert info["cd_profile"] < 0.05
        assert info["cl_used"] > 0.0
        assert info["reynolds_used"] > 0.0


def test_chord_weighted_profile_cd_falls_back_to_zero_when_no_chord() -> None:
    cd = chord_weighted_profile_cd(zone_profile={})
    assert cd == 0.0
    cd = chord_weighted_profile_cd(
        zone_profile={"root": {"chord_m_used": 0.0, "cd_profile": 0.01}}
    )
    assert cd == 0.0


def test_chord_weighted_profile_cd_matches_manual_average() -> None:
    zone_profile = {
        "root": {"chord_m_used": 1.30, "cd_profile": 0.0090},
        "mid1": {"chord_m_used": 1.05, "cd_profile": 0.0095},
        "mid2": {"chord_m_used": 0.85, "cd_profile": 0.0100},
        "tip": {"chord_m_used": 0.50, "cd_profile": 0.0110},
    }
    expected = sum(
        info["chord_m_used"] * info["cd_profile"] for info in zone_profile.values()
    ) / sum(info["chord_m_used"] for info in zone_profile.values())
    actual = chord_weighted_profile_cd(zone_profile=zone_profile)
    assert math.isclose(actual, expected, rel_tol=1.0e-12)


def test_aerodynamic_summary_records_template_id_and_polar() -> None:
    selected = select_zone_airfoils_from_library(zone_requirements=_stub_zones())
    summary = aerodynamic_summary(selected)
    for zone_name, info in summary.items():
        assert info["template_id"] in {"FX 76-MP-140", "CLARK-Y 11.7% smoothed"}
        assert info["polar_cd0"] > 0.0
        assert info["polar_k"] > 0.0
        assert info["selection_reason"]


def test_zone_airfoil_spec_cd_reduces_with_higher_re() -> None:
    selected = select_zone_airfoils_from_library(zone_requirements=_stub_zones())
    spec = selected["root"]
    cd_lower = spec.cd_at(cl=spec.polar_cl_ref, reynolds=200_000.0)
    cd_higher = spec.cd_at(cl=spec.polar_cl_ref, reynolds=500_000.0)
    assert cd_lower > cd_higher
