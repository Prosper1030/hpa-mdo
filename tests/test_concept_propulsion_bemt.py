import math

import pytest

from hpa_mdo.concept.propulsion import SimplifiedPropModel


def _build_bemt_model(
    *,
    diameter_m: float = 3.0,
    blade_count: int = 2,
    bemt_design_rpm: float = 140.0,
    bemt_v_tip_max_mps: float = 60.0,
) -> SimplifiedPropModel:
    return SimplifiedPropModel(
        diameter_m=diameter_m,
        rpm_min=100.0,
        rpm_max=160.0,
        blade_count=blade_count,
        air_density_kg_per_m3=1.18,
        design_efficiency=0.83,
        peak_speed_mps=8.5,
        peak_shaft_power_w=280.0,
        speed_falloff_per_mps=0.015,
        power_falloff_per_w=0.0004,
        speed_term_floor=0.70,
        power_term_floor=0.75,
        efficiency_floor=0.50,
        efficiency_ceiling=0.90,
        use_bemt_proxy=True,
        bemt_blade_loss_constant=0.174,
        bemt_profile_loss=0.07,
        bemt_peak_advance_ratio=1.10,
        bemt_advance_ratio_falloff=0.10,
        bemt_advance_ratio_floor=0.50,
        bemt_design_rpm=bemt_design_rpm,
        bemt_v_tip_max_mps=bemt_v_tip_max_mps,
        bemt_v_tip_penalty_slope=0.5,
    )


def test_bemt_efficiency_at_reference_point_matches_design_anchor_within_tolerance():
    """At V=8.5, P=280, D=3, B=2, RPM=140 the BEMT proxy should yield ≈0.83."""
    model = _build_bemt_model()
    eta = model.efficiency(speed_mps=8.5, shaft_power_w=280.0)
    assert eta == pytest.approx(0.83, abs=0.02)


def test_bemt_efficiency_increases_with_diameter_at_fixed_thrust_band():
    """Bigger disk → lower disk loading → higher Froude ideal η."""
    small = _build_bemt_model(diameter_m=2.5)
    big = _build_bemt_model(diameter_m=3.5)
    eta_small = small.efficiency(speed_mps=8.5, shaft_power_w=280.0)
    eta_big = big.efficiency(speed_mps=8.5, shaft_power_w=280.0)
    assert eta_big > eta_small


def test_bemt_efficiency_increases_with_blade_count():
    """More blades → smaller finite-blade knockdown → higher η."""
    two = _build_bemt_model(blade_count=2)
    three = _build_bemt_model(blade_count=3)
    four = _build_bemt_model(blade_count=4)
    eta_two = two.efficiency(speed_mps=8.5, shaft_power_w=280.0)
    eta_three = three.efficiency(speed_mps=8.5, shaft_power_w=280.0)
    eta_four = four.efficiency(speed_mps=8.5, shaft_power_w=280.0)
    assert eta_two < eta_three < eta_four


def test_bemt_efficiency_drops_when_v_tip_exceeds_limit():
    """A high-RPM small-diameter combo will breach V_tip and pay a penalty."""
    nominal = _build_bemt_model(bemt_design_rpm=140.0, bemt_v_tip_max_mps=60.0)
    fast_tip = _build_bemt_model(bemt_design_rpm=400.0, bemt_v_tip_max_mps=60.0)
    eta_nominal = nominal.efficiency(speed_mps=8.5, shaft_power_w=280.0)
    eta_fast_tip = fast_tip.efficiency(speed_mps=8.5, shaft_power_w=280.0)
    # V_tip = π·D·n: at D=3, RPM=400 → 62.8 m/s, slightly past 60 m/s ceiling.
    assert eta_fast_tip < eta_nominal


def test_bemt_efficiency_drops_off_design_advance_ratio():
    """At V far from peak J·n·D, the advance-ratio term penalises η."""
    model = _build_bemt_model()
    eta_at_peak = model.efficiency(speed_mps=7.7, shaft_power_w=280.0)  # J ≈ 1.10
    eta_off_peak = model.efficiency(speed_mps=14.0, shaft_power_w=280.0)  # J ≈ 2.0
    assert eta_off_peak < eta_at_peak


def test_bemt_efficiency_falls_back_to_op_point_when_use_bemt_proxy_false():
    """Disabling the BEMT path should preserve original op-point behavior."""
    op_point = SimplifiedPropModel(
        diameter_m=3.0,
        rpm_min=100.0,
        rpm_max=160.0,
        blade_count=2,
        air_density_kg_per_m3=1.18,
        design_efficiency=0.83,
        peak_speed_mps=8.5,
        peak_shaft_power_w=280.0,
        speed_falloff_per_mps=0.015,
        power_falloff_per_w=0.0004,
        speed_term_floor=0.70,
        power_term_floor=0.75,
        efficiency_floor=0.50,
        efficiency_ceiling=0.90,
        use_bemt_proxy=False,
        bemt_blade_loss_constant=0.174,
        bemt_profile_loss=0.07,
        bemt_peak_advance_ratio=1.10,
        bemt_advance_ratio_falloff=0.10,
        bemt_advance_ratio_floor=0.50,
        bemt_design_rpm=140.0,
        bemt_v_tip_max_mps=60.0,
        bemt_v_tip_penalty_slope=0.5,
    )
    expected = max(
        0.50,
        min(
            0.90,
            0.83
            * max(0.70, 1.0 - 0.015 * abs(7.0 - 8.5))
            * max(0.75, 1.0 - 0.0004 * abs(240.0 - 280.0)),
        ),
    )
    assert op_point.efficiency(
        speed_mps=7.0, shaft_power_w=240.0
    ) == pytest.approx(expected)


def test_bemt_efficiency_thrust_solution_satisfies_momentum_balance_at_reference():
    """Cross-check: η_ideal from the converged thrust matches Froude formula."""
    model = _build_bemt_model()
    eta = model.efficiency(speed_mps=8.5, shaft_power_w=280.0)
    thrust_n = eta * 280.0 / 8.5
    disk_area = math.pi * 3.0**2 / 4.0
    eta_ideal = 2.0 / (
        1.0
        + math.sqrt(1.0 + 2.0 * thrust_n / (1.18 * 8.5**2 * disk_area))
    )
    # η must be at most η_ideal × (other multiplicative knockdowns ≤ 1).
    assert eta <= eta_ideal + 1.0e-9
