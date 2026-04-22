from __future__ import annotations

import pytest

from hpa_mdo.concept.propulsion import SimplifiedPropModel
from hpa_mdo.concept.safety import (
    evaluate_launch_gate,
    evaluate_local_stall,
    evaluate_trim_proxy,
    evaluate_turn_gate,
)


def test_simplified_prop_model_efficiency_varies_with_speed_and_power():
    model = SimplifiedPropModel(
        diameter_m=3.0,
        rpm_min=100.0,
        rpm_max=160.0,
        design_efficiency=0.83,
    )

    low_speed = model.efficiency(speed_mps=7.0, shaft_power_w=240.0)
    high_speed = model.efficiency(speed_mps=10.0, shaft_power_w=300.0)

    assert 0.50 <= low_speed <= 0.90
    assert 0.50 <= high_speed <= 0.90
    assert low_speed != pytest.approx(high_speed)
    assert low_speed == pytest.approx(
        max(0.50, min(0.90, 0.83 * max(0.70, 1.0 - 0.015 * abs(7.0 - 8.5)) * max(0.75, 1.0 - 0.0004 * abs(240.0 - 280.0))))
    )


def test_launch_gate_applies_ground_effect_and_can_pass():
    result = evaluate_launch_gate(
        platform_height_m=10.0,
        wing_span_m=32.0,
        speed_mps=8.0,
        cl_required=0.95,
        cl_available=1.10,
        trim_margin_deg=2.0,
        required_trim_margin_deg=2.0,
        use_ground_effect=True,
    )

    assert result.ground_effect_applied is True
    assert result.adjusted_cl_required < 0.95
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
        use_ground_effect=False,
    )

    assert result.ground_effect_applied is False
    assert result.feasible is False
    assert result.reason == "launch_cl_insufficient"


def test_turn_gate_rejects_insufficient_stall_margin():
    result = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        cl_level=0.95,
        cl_max=1.05,
        trim_feasible=True,
        required_stall_margin=0.10,
    )

    assert result.required_cl == pytest.approx(0.95 / 0.9659258262890683, rel=1e-9)
    assert result.stall_margin < 0.10
    assert result.feasible is False
    assert result.reason == "stall_margin_insufficient"


def test_turn_gate_keeps_failure_contract_when_trim_is_not_feasible():
    result = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        cl_level=0.70,
        cl_max=1.20,
        trim_feasible=False,
        required_stall_margin=0.10,
    )

    assert result.required_cl == pytest.approx(0.70 / 0.9659258262890683, rel=1e-9)
    assert result.feasible is False
    assert result.reason == "trim_not_feasible"
    assert hash(result)


def test_launch_gate_respects_required_trim_margin():
    result = evaluate_launch_gate(
        platform_height_m=10.0,
        wing_span_m=32.0,
        speed_mps=8.0,
        cl_required=0.95,
        cl_available=1.10,
        trim_margin_deg=1.5,
        required_trim_margin_deg=2.0,
        use_ground_effect=True,
    )

    assert result.feasible is False
    assert result.reason == "trim_margin_insufficient"


def test_turn_gate_uses_configured_stall_margin_threshold():
    loose = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        cl_level=0.95,
        cl_max=1.12,
        trim_feasible=True,
        required_stall_margin=0.10,
    )
    tight = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        cl_level=0.95,
        cl_max=1.12,
        trim_feasible=True,
        required_stall_margin=0.15,
    )

    assert loose.feasible is True
    assert tight.feasible is False
    assert tight.reason == "stall_margin_insufficient"


def test_trim_proxy_flips_when_required_margin_is_tightened():
    loose = evaluate_trim_proxy(
        representative_cm=-0.10,
        required_margin_deg=1.5,
    )
    tight = evaluate_trim_proxy(
        representative_cm=-0.10,
        required_margin_deg=2.5,
    )

    assert loose.feasible is True
    assert tight.feasible is False
    assert tight.reason == "trim_margin_insufficient"


def test_local_stall_flags_tip_critical_case():
    result = evaluate_local_stall(
        station_points=[
            {"station_y_m": 1.0, "cl_target": 0.70, "cl_max_proxy": 0.92},
            {"station_y_m": 14.0, "cl_target": 0.82, "cl_max_proxy": 0.90},
        ],
        half_span_m=16.0,
        required_stall_margin=0.10,
    )

    assert result.feasible is False
    assert result.tip_critical is True
    assert result.min_margin_station_y_m == pytest.approx(14.0)
    assert result.reason == "stall_margin_insufficient"
