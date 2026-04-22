from __future__ import annotations

import pytest

from hpa_mdo.concept.propulsion import SimplifiedPropModel
from hpa_mdo.concept.safety import evaluate_launch_gate, evaluate_turn_gate


def test_simplified_prop_model_efficiency_varies_with_speed_and_power():
    model = SimplifiedPropModel(
        diameter_m=1.4,
        rpm_min=1100.0,
        rpm_max=1800.0,
        design_efficiency=0.82,
    )

    low_speed_low_power = model.efficiency(speed_mps=6.0, shaft_power_w=180.0)
    design_speed_high_power = model.efficiency(speed_mps=9.0, shaft_power_w=260.0)
    fast_speed_low_power = model.efficiency(speed_mps=12.0, shaft_power_w=180.0)

    assert 0.0 <= low_speed_low_power <= 1.0
    assert 0.0 <= design_speed_high_power <= 1.0
    assert 0.0 <= fast_speed_low_power <= 1.0
    assert low_speed_low_power != pytest.approx(design_speed_high_power)
    assert design_speed_high_power != pytest.approx(fast_speed_low_power)


def test_launch_gate_applies_ground_effect_and_can_pass():
    result = evaluate_launch_gate(
        platform_height_m=10.0,
        wing_span_m=30.0,
        speed_mps=8.0,
        cl_required=1.20,
        cl_available=1.15,
        trim_margin_deg=2.0,
        use_ground_effect=True,
    )

    assert result.ground_effect_applied is True
    assert result.adjusted_cl_required < 1.20
    assert result.feasible is True
    assert result.reason == "ok"


def test_turn_gate_rejects_insufficient_stall_margin():
    result = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=9.0,
        cl_level=0.98,
        cl_max=1.05,
        trim_feasible=True,
    )

    assert result.required_cl == pytest.approx(0.98 / 0.9659258262890683, rel=1e-9)
    assert result.stall_margin < 0.1
    assert result.feasible is False
    assert result.reason == "insufficient_stall_margin"
