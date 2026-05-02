import pytest

from hpa_mdo.concept.aero_proxies import (
    misc_cd_proxy,
    oswald_efficiency_proxy,
    spanload_fourier_efficiency_records,
    spanload_efficiency_proxy,
)
from hpa_mdo.concept.config import (
    OswaldEfficiencyProxyConfig,
    ParasiteDragProxyConfig,
)
from hpa_mdo.concept.geometry import GeometryConcept


def _build_concept(
    *,
    twist_root_deg: float = 2.0,
    twist_tip_deg: float = -1.0,
    dihedral_root_deg: float = 0.0,
    dihedral_tip_deg: float = 4.0,
) -> GeometryConcept:
    return GeometryConcept(
        span_m=32.0,
        wing_area_m2=32.0,
        root_chord_m=1.0,
        tip_chord_m=1.0,
        twist_root_deg=twist_root_deg,
        twist_tip_deg=twist_tip_deg,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(8.0, 8.0),
        dihedral_root_deg=dihedral_root_deg,
        dihedral_tip_deg=dihedral_tip_deg,
    )


def test_oswald_efficiency_proxy_matches_legacy_inline_formula_at_defaults():
    concept = _build_concept()
    cfg = OswaldEfficiencyProxyConfig()
    expected = max(0.68, min(0.92, 0.88 - 0.012 * 4.0 - 0.008 * 3.0))
    assert oswald_efficiency_proxy(concept=concept, proxy_cfg=cfg) == pytest.approx(expected)


def test_oswald_efficiency_proxy_clamps_to_floor_when_knockdown_is_large():
    cfg = OswaldEfficiencyProxyConfig(
        base_efficiency=0.88,
        dihedral_delta_slope_per_deg=0.05,
        twist_delta_slope_per_deg=0.05,
        efficiency_floor=0.70,
        efficiency_ceiling=0.92,
    )
    concept = _build_concept(dihedral_tip_deg=10.0, twist_tip_deg=-9.0)
    eff = oswald_efficiency_proxy(concept=concept, proxy_cfg=cfg)
    assert eff == pytest.approx(0.70)


def test_oswald_efficiency_proxy_drops_with_more_dihedral_spread():
    cfg = OswaldEfficiencyProxyConfig()
    flat = _build_concept(dihedral_root_deg=0.0, dihedral_tip_deg=0.0)
    spread = _build_concept(dihedral_root_deg=0.0, dihedral_tip_deg=8.0)
    eff_flat = oswald_efficiency_proxy(concept=flat, proxy_cfg=cfg)
    eff_spread = oswald_efficiency_proxy(concept=spread, proxy_cfg=cfg)
    assert eff_spread < eff_flat


def test_spanload_efficiency_proxy_uses_station_lift_shape_when_available():
    cfg = OswaldEfficiencyProxyConfig(efficiency_ceiling=0.93)
    concept = _build_concept(dihedral_tip_deg=6.0, twist_tip_deg=-1.5)
    half_span = 0.5 * concept.span_m
    good_points = [
        {
            "station_y_m": eta * half_span,
            "chord_m": 1.0,
            "cl_target": max((1.0 - eta**2) ** 0.5, 0.02),
        }
        for eta in (0.0, 0.25, 0.50, 0.75, 0.95)
    ]
    tip_loaded_points = [
        {**point, "cl_target": 0.65 + 0.65 * point["station_y_m"] / half_span}
        for point in good_points
    ]

    good = spanload_efficiency_proxy(
        concept=concept,
        station_points=good_points,
        proxy_cfg=cfg,
    )
    tip_loaded = spanload_efficiency_proxy(
        concept=concept,
        station_points=tip_loaded_points,
        proxy_cfg=cfg,
    )

    assert good["source"] == "spanload_shape_proxy_v1"
    assert good["efficiency"] > oswald_efficiency_proxy(concept=concept, proxy_cfg=cfg)
    assert good["efficiency"] > tip_loaded["efficiency"]
    assert good["spanload_rms_error"] < tip_loaded["spanload_rms_error"]


def test_spanload_efficiency_proxy_responds_to_configured_shape_penalty():
    concept = _build_concept(dihedral_tip_deg=6.0, twist_tip_deg=-1.5)
    half_span = 0.5 * concept.span_m
    tip_loaded_points = [
        {
            "station_y_m": eta * half_span,
            "chord_m": 1.0,
            "cl_target": 0.65 + 0.65 * eta,
        }
        for eta in (0.0, 0.25, 0.50, 0.75, 0.95)
    ]

    baseline = spanload_efficiency_proxy(
        concept=concept,
        station_points=tip_loaded_points,
        proxy_cfg=OswaldEfficiencyProxyConfig(efficiency_ceiling=0.93),
    )
    harsher = spanload_efficiency_proxy(
        concept=concept,
        station_points=tip_loaded_points,
        proxy_cfg=OswaldEfficiencyProxyConfig(
            efficiency_ceiling=0.93,
            spanload_shape_penalty_slope=0.44,
            spanload_shape_penalty_max=0.36,
        ),
    )

    assert harsher["efficiency"] < baseline["efficiency"]


def test_spanload_fourier_efficiency_rewards_elliptic_distribution():
    concept = _build_concept(dihedral_tip_deg=0.0, twist_tip_deg=0.0)
    half_span = 0.5 * concept.span_m
    elliptic_points = [
        {
            "case_label": "reference_avl_case",
            "station_y_m": eta * half_span,
            "chord_m": 1.0,
            "cl_target": max((1.0 - eta**2) ** 0.5, 0.0),
        }
        for eta in (0.0, 0.20, 0.40, 0.60, 0.80, 0.95, 1.0)
    ]
    tip_loaded_points = [
        {**point, "cl_target": 0.55 + 0.75 * point["station_y_m"] / half_span}
        for point in elliptic_points
    ]

    elliptic = spanload_fourier_efficiency_records(
        concept=concept,
        station_points=elliptic_points,
    )[0]
    tip_loaded = spanload_fourier_efficiency_records(
        concept=concept,
        station_points=tip_loaded_points,
    )[0]

    assert elliptic["source"] == "spanload_fourier_series_v1"
    assert elliptic["efficiency"] > 0.98
    assert elliptic["spanload_fourier_deviation"] < tip_loaded["spanload_fourier_deviation"]
    assert tip_loaded["efficiency"] < elliptic["efficiency"]


def test_misc_cd_proxy_matches_legacy_inline_formula():
    cfg = ParasiteDragProxyConfig()
    cd = misc_cd_proxy(profile_cd=0.020, tail_area_ratio=0.10, proxy_cfg=cfg)
    assert cd == pytest.approx(0.0035 + 0.20 * 0.10 * 0.020)


def test_misc_cd_proxy_responds_to_overridden_constants():
    cfg = ParasiteDragProxyConfig(
        fuselage_misc_cd=0.0050,
        tail_profile_coupling_factor=0.30,
    )
    cd = misc_cd_proxy(profile_cd=0.025, tail_area_ratio=0.12, proxy_cfg=cfg)
    assert cd == pytest.approx(0.0050 + 0.30 * 0.12 * 0.025)


def test_oswald_efficiency_proxy_config_rejects_inverted_floor_ceiling():
    with pytest.raises(ValueError):
        OswaldEfficiencyProxyConfig(efficiency_floor=0.95, efficiency_ceiling=0.90)


def test_oswald_efficiency_proxy_config_rejects_base_outside_clamp_band():
    with pytest.raises(ValueError):
        OswaldEfficiencyProxyConfig(
            base_efficiency=0.50,
            efficiency_floor=0.68,
            efficiency_ceiling=0.92,
        )
