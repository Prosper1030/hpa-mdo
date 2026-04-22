from __future__ import annotations

import pytest

from hpa_mdo.concept.propulsion import SimplifiedPropModel
from hpa_mdo.concept.safety import evaluate_launch_gate, evaluate_turn_gate


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
        use_ground_effect=True,
    )

    assert result.ground_effect_applied is True
    assert result.adjusted_cl_required < 0.95
    assert result.feasible is True
    assert result.reason == "ok"


def test_turn_gate_rejects_insufficient_stall_margin():
    result = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        cl_level=0.95,
        cl_max=1.05,
        trim_feasible=True,
    )

    assert result.required_cl == pytest.approx(0.95 / 0.9659258262890683, rel=1e-9)
    assert result.stall_margin < 0.10
    assert result.feasible is False
    assert result.reason == "stall_margin_insufficient"
