from __future__ import annotations

import pytest

from hpa_mdo.concept.propulsion import SimplifiedPropModel
from hpa_mdo.concept.safety import (
    evaluate_launch_gate,
    evaluate_local_stall,
    evaluate_trim_balance,
    evaluate_trim_proxy,
    evaluate_turn_gate,
)


def _build_default_prop_model(*, use_bemt_proxy: bool = False) -> SimplifiedPropModel:
    return SimplifiedPropModel(
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
        use_bemt_proxy=use_bemt_proxy,
        bemt_blade_loss_constant=0.174,
        bemt_profile_loss=0.07,
        bemt_peak_advance_ratio=1.10,
        bemt_advance_ratio_falloff=0.10,
        bemt_advance_ratio_floor=0.50,
        bemt_design_rpm=140.0,
        bemt_v_tip_max_mps=60.0,
        bemt_v_tip_penalty_slope=0.5,
    )


def test_simplified_prop_model_efficiency_varies_with_speed_and_power():
    model = _build_default_prop_model()

    low_speed = model.efficiency(speed_mps=7.0, shaft_power_w=240.0)
    high_speed = model.efficiency(speed_mps=10.0, shaft_power_w=300.0)

    assert 0.50 <= low_speed <= 0.90
    assert 0.50 <= high_speed <= 0.90
    assert low_speed != pytest.approx(high_speed)
    assert low_speed == pytest.approx(
        max(0.50, min(0.90, 0.83 * max(0.70, 1.0 - 0.015 * abs(7.0 - 8.5)) * max(0.75, 1.0 - 0.0004 * abs(240.0 - 280.0))))
    )


def test_simplified_prop_model_efficiency_respects_configured_peak_and_falloff():
    model = SimplifiedPropModel(
        diameter_m=3.0,
        rpm_min=100.0,
        rpm_max=160.0,
        blade_count=2,
        air_density_kg_per_m3=1.18,
        design_efficiency=0.85,
        peak_speed_mps=9.0,
        peak_shaft_power_w=320.0,
        speed_falloff_per_mps=0.020,
        power_falloff_per_w=0.0006,
        speed_term_floor=0.72,
        power_term_floor=0.78,
        efficiency_floor=0.55,
        efficiency_ceiling=0.92,
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
    # At the configured peak the operating-point correction collapses to 1.0.
    assert model.efficiency(speed_mps=9.0, shaft_power_w=320.0) == pytest.approx(0.85)
    # Off-peak the efficiency must drop and stay within configured clamps.
    off_peak = model.efficiency(speed_mps=7.0, shaft_power_w=200.0)
    assert 0.55 <= off_peak <= 0.92
    assert off_peak < 0.85


def test_launch_gate_applies_ground_effect_and_can_pass():
    result = evaluate_launch_gate(
        platform_height_m=10.0,
        wing_span_m=32.0,
        speed_mps=8.0,
        cl_required=0.95,
        cl_available=1.10,
        trim_margin_deg=2.0,
        required_trim_margin_deg=2.0,
        stall_utilization_limit=0.90,
        use_ground_effect=True,
    )

    assert result.ground_effect_applied is True
    assert result.adjusted_cl_required < 0.95
    assert result.stall_utilization < 0.90
    assert result.feasible is True
    assert result.reason == "ok"


def test_launch_gate_reports_generic_failure_reason():
    result = evaluate_launch_gate(
        platform_height_m=10.0,
        wing_span_m=32.0,
        speed_mps=8.0,
        cl_required=1.05,
        cl_available=0.95,
        trim_margin_deg=2.0,
        required_trim_margin_deg=2.0,
        stall_utilization_limit=0.90,
        use_ground_effect=False,
    )

    assert result.ground_effect_applied is False
    assert result.feasible is False
    assert result.reason == "launch_cl_insufficient"


def test_turn_gate_rejects_insufficient_stall_margin():
    result = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        station_points=[
            {"station_y_m": 2.0, "cl_target": 0.95, "cl_max_safe": 1.05},
            {"station_y_m": 14.0, "cl_target": 0.80, "cl_max_safe": 1.10},
        ],
        half_span_m=16.0,
        trim_feasible=True,
        stall_utilization_limit=0.80,
    )

    assert result.required_cl == pytest.approx(0.95 / 0.9659258262890683, rel=1e-9)
    assert result.cl_level == pytest.approx(0.95)
    assert result.cl_max == pytest.approx(1.05)
    assert result.load_factor == pytest.approx(1.0 / 0.9659258262890683, rel=1e-9)
    assert result.limiting_station_y_m == pytest.approx(2.0)
    assert result.tip_critical is False
    assert result.stall_utilization > 0.80
    assert result.feasible is False
    assert result.reason == "stall_utilization_exceeded"


def test_turn_gate_keeps_failure_contract_when_trim_is_not_feasible():
    result = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        station_points=[
            {"station_y_m": 1.0, "cl_target": 0.70, "cl_max_safe": 1.20},
            {"station_y_m": 14.0, "cl_target": 0.60, "cl_max_safe": 1.10},
        ],
        half_span_m=16.0,
        trim_feasible=False,
        stall_utilization_limit=0.85,
    )

    assert result.required_cl == pytest.approx(0.70 / 0.9659258262890683, rel=1e-9)
    assert result.feasible is False
    assert result.reason == "trim_not_feasible"
    assert hash(result)


def test_turn_gate_supports_pre_scaled_turn_case_points() -> None:
    load_factor = 1.0 / 0.9659258262890683
    result = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        station_points=[
            {
                "station_y_m": 2.0,
                "cl_target": 0.98,
                "cl_max_safe": 1.20,
            }
        ],
        half_span_m=16.0,
        trim_feasible=True,
        stall_utilization_limit=0.90,
        load_factor_override=load_factor,
        pre_scaled_cl=True,
    )

    assert result.required_cl == pytest.approx(0.98)
    assert result.load_factor == pytest.approx(load_factor)
    assert result.stall_utilization == pytest.approx(0.98 / 1.20)


def test_launch_gate_respects_required_trim_margin():
    result = evaluate_launch_gate(
        platform_height_m=10.0,
        wing_span_m=32.0,
        speed_mps=8.0,
        cl_required=0.95,
        cl_available=1.10,
        trim_margin_deg=1.5,
        required_trim_margin_deg=2.0,
        stall_utilization_limit=0.90,
        use_ground_effect=True,
    )

    assert result.feasible is False
    assert result.reason == "trim_margin_insufficient"


@pytest.mark.parametrize("required_trim_margin_deg", [0.0, -0.5])
def test_launch_gate_rejects_nonpositive_required_trim_margin(required_trim_margin_deg: float):
    with pytest.raises(ValueError, match="required_trim_margin_deg must be positive"):
        evaluate_launch_gate(
            platform_height_m=10.0,
            wing_span_m=32.0,
            speed_mps=8.0,
            cl_required=0.95,
            cl_available=1.10,
            trim_margin_deg=2.0,
            required_trim_margin_deg=required_trim_margin_deg,
            stall_utilization_limit=0.90,
            use_ground_effect=True,
        )


def test_turn_gate_uses_configured_stall_margin_threshold():
    loose = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        station_points=[{"station_y_m": 2.0, "cl_target": 0.95, "cl_max_safe": 1.20}],
        half_span_m=16.0,
        trim_feasible=True,
        stall_utilization_limit=0.85,
    )
    tight = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        station_points=[{"station_y_m": 2.0, "cl_target": 0.95, "cl_max_safe": 1.20}],
        half_span_m=16.0,
        trim_feasible=True,
        stall_utilization_limit=0.80,
    )

    assert loose.feasible is True
    assert tight.feasible is False
    assert tight.reason == "stall_utilization_exceeded"


def test_trim_proxy_flips_when_required_margin_is_tightened():
    loose = evaluate_trim_proxy(
        representative_cm=-0.10,
        required_margin_deg=1.5,
        cm_spread=0.0,
    )
    tight = evaluate_trim_proxy(
        representative_cm=-0.10,
        required_margin_deg=2.5,
        cm_spread=0.0,
    )

    assert loose.feasible is True
    assert tight.feasible is False
    assert tight.reason == "trim_margin_insufficient"


def test_trim_proxy_treats_threshold_equality_as_feasible():
    result = evaluate_trim_proxy(
        representative_cm=-0.10,
        required_margin_deg=2.0,
        cm_spread=0.0,
    )

    assert result.margin_deg == pytest.approx(2.0)
    assert result.feasible is True
    assert result.reason == "ok"


def test_trim_proxy_penalizes_cm_spread():
    narrow = evaluate_trim_proxy(
        representative_cm=-0.08,
        required_margin_deg=2.0,
        cm_spread=0.00,
    )
    wide = evaluate_trim_proxy(
        representative_cm=-0.08,
        required_margin_deg=2.0,
        cm_spread=0.05,
    )

    assert narrow.margin_deg > wide.margin_deg
    assert wide.feasible is False


def test_trim_balance_rewards_larger_tail_volume() -> None:
    small_tail = evaluate_trim_balance(
        wing_cl=0.80,
        wing_cm_airfoil=-0.10,
        cg_xc=0.30,
        wing_ac_xc=0.25,
        tail_area_ratio=0.12,
        tail_arm_to_mac=4.0,
        tail_dynamic_pressure_ratio=0.90,
        tail_efficiency=0.90,
        tail_cl_limit_abs=0.80,
        required_margin_deg=2.0,
    )
    large_tail = evaluate_trim_balance(
        wing_cl=0.80,
        wing_cm_airfoil=-0.10,
        cg_xc=0.30,
        wing_ac_xc=0.25,
        tail_area_ratio=0.18,
        tail_arm_to_mac=4.0,
        tail_dynamic_pressure_ratio=0.90,
        tail_efficiency=0.90,
        tail_cl_limit_abs=0.80,
        required_margin_deg=2.0,
    )

    assert large_tail.tail_volume_coefficient > small_tail.tail_volume_coefficient
    assert abs(large_tail.tail_cl_required) < abs(small_tail.tail_cl_required)
    assert large_tail.tail_utilization < small_tail.tail_utilization
    assert large_tail.margin_deg > small_tail.margin_deg


def test_trim_balance_penalizes_aft_cg() -> None:
    forward_cg = evaluate_trim_balance(
        wing_cl=0.75,
        wing_cm_airfoil=-0.08,
        cg_xc=0.28,
        wing_ac_xc=0.25,
        tail_area_ratio=0.15,
        tail_arm_to_mac=4.0,
        tail_dynamic_pressure_ratio=0.90,
        tail_efficiency=0.90,
        tail_cl_limit_abs=0.80,
        required_margin_deg=2.0,
    )
    aft_cg = evaluate_trim_balance(
        wing_cl=0.75,
        wing_cm_airfoil=-0.08,
        cg_xc=0.33,
        wing_ac_xc=0.25,
        tail_area_ratio=0.15,
        tail_arm_to_mac=4.0,
        tail_dynamic_pressure_ratio=0.90,
        tail_efficiency=0.90,
        tail_cl_limit_abs=0.80,
        required_margin_deg=2.0,
    )

    assert aft_cg.wing_cm_total < forward_cg.wing_cm_total
    assert abs(aft_cg.tail_cl_required) > abs(forward_cg.tail_cl_required)
    assert aft_cg.tail_utilization > forward_cg.tail_utilization
    assert aft_cg.margin_deg < forward_cg.margin_deg


def test_local_stall_flags_tip_critical_case():
    result = evaluate_local_stall(
        station_points=[
            {"station_y_m": 1.0, "cl_target": 0.70, "cl_max_safe": 0.92},
            {"station_y_m": 14.0, "cl_target": 0.82, "cl_max_safe": 0.90},
        ],
        half_span_m=16.0,
        stall_utilization_limit=0.80,
    )

    assert result.feasible is False
    assert result.required_cl == pytest.approx(0.82)
    assert result.cl_max == pytest.approx(0.90)
    assert result.cl_max_source == "geometry_safe_proxy"
    assert result.tip_critical is True
    assert result.min_margin_station_y_m == pytest.approx(14.0)
    assert result.stall_utilization == pytest.approx(0.82 / 0.90)
    assert result.reason == "stall_utilization_exceeded"


def test_local_stall_prefers_airfoil_derived_limit_when_present():
    result = evaluate_local_stall(
        station_points=[
            {
                "station_y_m": 1.0,
                "cl_target": 0.70,
                "cl_max_proxy": 0.92,
                "cl_max_safe": 1.05,
                "cl_max_safe_source": "airfoil_safe_observed",
            },
            {
                "station_y_m": 14.0,
                "cl_target": 0.82,
                "cl_max_proxy": 1.02,
                "cl_max_safe": 0.90,
                "cl_max_safe_source": "airfoil_safe_lower_bound",
            },
        ],
        half_span_m=16.0,
        stall_utilization_limit=0.80,
    )

    assert result.min_margin == pytest.approx(0.08)
    assert result.cl_max == pytest.approx(0.90)
    assert result.cl_max_source == "airfoil_safe_lower_bound"
    assert result.min_margin_station_y_m == pytest.approx(14.0)
    assert result.tip_critical is True
    assert result.feasible is False


def test_local_stall_uses_the_limiting_station_even_if_other_points_look_safer():
    result = evaluate_local_stall(
        station_points=[
            {"station_y_m": 2.0, "cl_target": 0.66, "cl_max_safe": 0.98},
            {"station_y_m": 14.0, "cl_target": 0.82, "cl_max_safe": 0.90},
        ],
        half_span_m=16.0,
        stall_utilization_limit=0.80,
    )

    assert result.feasible is False
    assert result.min_margin == pytest.approx(0.08)
    assert result.required_cl == pytest.approx(0.82)
    assert result.min_margin_station_y_m == pytest.approx(14.0)
    assert result.tip_critical is True
    assert result.reason == "stall_utilization_exceeded"


def test_local_stall_uses_ratio_limiter_not_smallest_absolute_margin() -> None:
    result = evaluate_local_stall(
        station_points=[
            {"station_y_m": 2.0, "cl_target": 1.80, "cl_max_safe": 2.00},
            {"station_y_m": 14.0, "cl_target": 0.10, "cl_max_safe": 0.20},
        ],
        half_span_m=16.0,
        stall_utilization_limit=0.85,
    )

    assert result.feasible is False
    assert result.required_cl == pytest.approx(1.80)
    assert result.cl_max == pytest.approx(2.00)
    assert result.stall_utilization == pytest.approx(0.90)
    assert result.safe_clmax_ratio == pytest.approx(0.90)
    assert result.min_margin_station_y_m == pytest.approx(2.0)
    assert result.reason == "stall_utilization_exceeded"


def test_local_stall_reports_raw_and_safe_clmax_ratio_statuses() -> None:
    result = evaluate_local_stall(
        station_points=[
            {
                "station_y_m": 4.0,
                "cl_target": 0.92,
                "cl_max_raw": 1.00,
                "cl_max_raw_source": "airfoil_observed",
                "cl_max_safe": 1.15,
                "cl_max_safe_source": "airfoil_safe_observed",
            }
        ],
        half_span_m=16.0,
        stall_utilization_limit=0.85,
    )

    assert result.feasible is True
    assert result.raw_clmax == pytest.approx(1.00)
    assert result.safe_clmax == pytest.approx(1.15)
    assert result.raw_clmax_ratio == pytest.approx(0.92)
    assert result.safe_clmax_ratio == pytest.approx(0.92 / 1.15)
    assert result.raw_clmax_status == "near_raw_amber"
    assert result.safe_clmax_status == "case_limit_pass"
    assert result.safe_stall_speed_margin_ratio == pytest.approx((1.15 / 0.92) ** 0.5)


def test_local_stall_treats_beyond_raw_clmax_as_physics_hard_fail() -> None:
    result = evaluate_local_stall(
        station_points=[
            {
                "station_y_m": 4.0,
                "cl_target": 1.05,
                "cl_max_raw": 1.00,
                "cl_max_raw_source": "airfoil_observed",
                "cl_max_safe": 1.40,
                "cl_max_safe_source": "airfoil_safe_observed",
            }
        ],
        half_span_m=16.0,
        stall_utilization_limit=0.85,
    )

    assert result.feasible is False
    assert result.raw_clmax_ratio == pytest.approx(1.05)
    assert result.raw_clmax_status == "beyond_raw_clmax"
    assert result.reason == "beyond_raw_clmax"
