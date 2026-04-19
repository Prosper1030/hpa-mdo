import pytest

from hpa_mdo.mission import (
    FakeAnchorCurve,
    MissionEvaluationInputs,
    evaluate_mission_objective,
)


def test_fake_anchor_curve_matches_anchor_point():
    curve = FakeAnchorCurve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
    )

    assert curve.power_at_duration_min(30.0) == pytest.approx(300.0)
    assert curve.duration_at_power_w(300.0) == pytest.approx(30.0)


def test_duration_at_power_w_decreases_when_required_power_increases():
    curve = FakeAnchorCurve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
    )

    lower_power_duration = curve.duration_at_power_w(250.0)
    higher_power_duration = curve.duration_at_power_w(350.0)

    assert higher_power_duration < lower_power_duration


def test_evaluate_mission_objective_max_range_reports_best_range_and_margin():
    curve = FakeAnchorCurve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
    )
    inputs = MissionEvaluationInputs(
        objective_mode="max_range",
        target_range_km=20.0,
        speed_mps=(10.0, 12.0, 14.0),
        power_required_w=(240.0, 220.0, 260.0),
        rider_curve=curve,
    )

    result = evaluate_mission_objective(inputs)
    expected_ranges = [
        speed * curve.duration_at_power_w(power) * 60.0
        for speed, power in zip(inputs.speed_mps, inputs.power_required_w)
    ]
    expected_best_range = max(expected_ranges)

    assert result.mission_objective_mode == "max_range"
    assert result.best_range_m == pytest.approx(expected_best_range)
    assert result.target_range_margin_m == pytest.approx(expected_best_range - 20000.0)
    assert result.mission_score == pytest.approx(-result.best_range_m)
    assert result.mission_score_reason == "maximize_range"
    assert result.pilot_power_model == "fake_anchor_curve"
    assert result.pilot_power_anchor == "300.0W@30.0min"
    assert result.speed_sweep_window_mps == (10.0, 14.0)


def test_evaluate_mission_objective_min_power_reports_min_power_metrics():
    curve = FakeAnchorCurve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
    )
    inputs = MissionEvaluationInputs(
        objective_mode="min_power",
        target_range_km=15.0,
        speed_mps=(9.0, 11.0, 13.0),
        power_required_w=(235.0, 215.0, 225.0),
        rider_curve=curve,
    )

    result = evaluate_mission_objective(inputs)
    expected_ranges = [
        speed * curve.duration_at_power_w(power) * 60.0
        for speed, power in zip(inputs.speed_mps, inputs.power_required_w)
    ]

    assert result.mission_objective_mode == "min_power"
    assert result.min_power_w == pytest.approx(215.0)
    assert result.min_power_speed_mps == pytest.approx(11.0)
    assert result.mission_score == pytest.approx(215.0)
    assert result.mission_score_reason == "minimize_power"
    assert result.target_range_passed is (max(expected_ranges) >= 15000.0)


def test_evaluate_mission_objective_target_miss_is_infeasible():
    inputs = MissionEvaluationInputs(
        objective_mode="max_range",
        target_range_km=1000000.0,
        speed_mps=(10.0, 11.0, 12.0),
        power_required_w=(240.0, 230.0, 220.0),
        rider_curve=FakeAnchorCurve(
            anchor_power_w=300.0,
            anchor_duration_min=30.0,
        ),
    )

    result = evaluate_mission_objective(inputs)

    assert result.target_range_passed is False
    assert result.mission_feasible is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"anchor_power_w": 0.0, "anchor_duration_min": 30.0},
        {"anchor_power_w": 300.0, "anchor_duration_min": float("nan")},
        {"anchor_power_w": 300.0, "anchor_duration_min": -1.0},
        {"anchor_power_w": 300.0, "anchor_duration_min": 30.0, "exponent": 0.0},
        {"anchor_power_w": 300.0, "anchor_duration_min": 30.0, "min_power_w": 0.0},
        {"anchor_power_w": 300.0, "anchor_duration_min": 30.0, "max_power_w": 180.0},
        {
            "anchor_power_w": 500.0,
            "anchor_duration_min": 30.0,
            "max_power_w": 450.0,
        },
    ],
)
def test_fake_anchor_curve_rejects_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        FakeAnchorCurve(**kwargs)


@pytest.mark.parametrize(
    "speed_mps,power_required_w",
    [
        ((10.0, float("nan")), (240.0, 230.0)),
        ((10.0, 11.0), (240.0, 0.0)),
        ((10.0, -1.0), (240.0, 230.0)),
        ((10.0, 11.0), (240.0, float("inf"))),
    ],
)
def test_evaluate_mission_objective_rejects_non_finite_or_non_positive_samples(
    speed_mps, power_required_w
):
    inputs = MissionEvaluationInputs(
        objective_mode="max_range",
        target_range_km=10.0,
        speed_mps=speed_mps,
        power_required_w=power_required_w,
        rider_curve=FakeAnchorCurve(
            anchor_power_w=300.0,
            anchor_duration_min=30.0,
        ),
    )

    with pytest.raises(ValueError):
        evaluate_mission_objective(inputs)


def test_evaluate_mission_objective_rejects_unsupported_mode():
    inputs = MissionEvaluationInputs(
        objective_mode="other",
        target_range_km=10.0,
        speed_mps=(10.0, 11.0),
        power_required_w=(250.0, 240.0),
        rider_curve=FakeAnchorCurve(
            anchor_power_w=300.0,
            anchor_duration_min=30.0,
        ),
    )

    with pytest.raises(ValueError, match="unsupported objective_mode"):
        evaluate_mission_objective(inputs)
