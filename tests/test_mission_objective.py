from pathlib import Path

import pytest

from hpa_mdo.mission import (
    CsvPowerCurve,
    FakeAnchorCurve,
    MissionEvaluationInputs,
    RiderPowerEnvironment,
    adjust_power_curve_for_environment,
    build_rider_power_curve,
    evaluate_mission_objective,
    load_csv_power_curve,
    simplified_heat_stress_h,
    thermal_power_derate_factor,
)


def _write_power_curve_csv(tmp_path: Path, rows: list[tuple[float, float]]) -> Path:
    csv_path = tmp_path / "power_curve.csv"
    csv_path.write_text(
        "secs,watts\n"
        + "\n".join(f"{secs},{watts}" for secs, watts in rows)
        + "\n",
        encoding="utf-8",
    )
    return csv_path


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


def test_load_csv_power_curve_interpolates_duration_and_power(tmp_path: Path):
    csv_path = _write_power_curve_csv(
        tmp_path,
        [
            (60.0, 400.0),
            (120.0, 350.0),
            (300.0, 300.0),
            (600.0, 250.0),
        ],
    )

    curve = load_csv_power_curve(csv_path)

    assert isinstance(curve, CsvPowerCurve)
    assert curve.power_at_duration_min(5.0) == pytest.approx(300.0)
    assert curve.duration_at_power_w(300.0) == pytest.approx(5.0)
    assert curve.duration_at_power_w(275.0) == pytest.approx(7.5)
    assert curve.duration_at_power_w(450.0) == pytest.approx(1.0)
    assert curve.duration_at_power_w(200.0) == pytest.approx(10.0)


def test_load_csv_power_curve_monotonizes_noisy_measurements(tmp_path: Path):
    csv_path = _write_power_curve_csv(
        tmp_path,
        [
            (60.0, 400.0),
            (120.0, 340.0),
            (180.0, 345.0),
            (300.0, 300.0),
        ],
    )

    curve = load_csv_power_curve(csv_path)

    assert curve.power_at_duration_min(2.0) == pytest.approx(345.0)
    assert curve.duration_at_power_w(345.0) == pytest.approx(3.0)


def test_thermal_power_derate_factor_uses_simplified_heat_stress_index() -> None:
    test_env = RiderPowerEnvironment(temperature_c=26.0, relative_humidity_percent=70.0)
    race_env = RiderPowerEnvironment(temperature_c=33.0, relative_humidity_percent=80.0)

    assert simplified_heat_stress_h(test_env) == pytest.approx(27.900900638173272)
    assert simplified_heat_stress_h(race_env) == pytest.approx(38.40884649010027)
    assert thermal_power_derate_factor(
        test_environment=test_env,
        target_environment=race_env,
        heat_loss_coefficient_per_h_c=0.008,
    ) == pytest.approx(1.0 - 0.008 * (38.40884649010027 - 27.900900638173272))


def test_adjust_power_curve_for_environment_preserves_raw_csv_and_scales_power(
    tmp_path: Path,
) -> None:
    csv_path = _write_power_curve_csv(
        tmp_path,
        [
            (60.0, 400.0),
            (300.0, 300.0),
            (1800.0, 240.0),
        ],
    )
    raw_curve = load_csv_power_curve(csv_path)

    adjusted = adjust_power_curve_for_environment(
        raw_curve,
        test_environment=RiderPowerEnvironment(
            temperature_c=26.0,
            relative_humidity_percent=70.0,
        ),
        target_environment=RiderPowerEnvironment(
            temperature_c=33.0,
            relative_humidity_percent=80.0,
        ),
        heat_loss_coefficient_per_h_c=0.008,
    )

    assert adjusted.source_path == raw_curve.source_path
    assert adjusted.power_at_duration_min(30.0) == pytest.approx(
        raw_curve.power_at_duration_min(30.0) * adjusted.thermal_adjustment["power_factor"]
    )
    assert adjusted.thermal_adjustment["test_environment"]["temperature_c"] == pytest.approx(26.0)
    assert adjusted.thermal_adjustment["target_environment"]["relative_humidity_percent"] == pytest.approx(80.0)


def test_build_rider_power_curve_uses_sidecar_environment_metadata(tmp_path: Path) -> None:
    csv_path = _write_power_curve_csv(
        tmp_path,
        [
            (60.0, 400.0),
            (300.0, 300.0),
            (1800.0, 240.0),
        ],
    )
    metadata_path = tmp_path / "power_curve.metadata.yaml"
    metadata_path.write_text(
        "\n".join(
            [
                "schema_version: rider_power_curve_metadata_v1",
                "measurement_environment:",
                "  temperature_c: 26.0",
                "  relative_humidity_percent: 70.0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    adjusted = build_rider_power_curve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
        rider_power_curve_csv=csv_path,
        rider_power_curve_metadata_yaml=metadata_path,
        thermal_adjustment_enabled=True,
        target_temperature_c=33.0,
        target_relative_humidity_percent=80.0,
        heat_loss_coefficient_per_h_c=0.008,
    )

    assert isinstance(adjusted, CsvPowerCurve)
    assert adjusted.thermal_adjustment is not None
    assert adjusted.thermal_adjustment["metadata_path"].endswith("power_curve.metadata.yaml")
    assert adjusted.anchor_power_w < load_csv_power_curve(csv_path).anchor_power_w


def test_build_rider_power_curve_rejects_metadata_for_different_csv(
    tmp_path: Path,
) -> None:
    csv_path = _write_power_curve_csv(
        tmp_path,
        [
            (60.0, 400.0),
            (300.0, 300.0),
            (1800.0, 240.0),
        ],
    )
    (tmp_path / "other_power_curve.csv").write_text(
        "secs,watts\n60,410\n300,310\n1800,250\n",
        encoding="utf-8",
    )
    metadata_path = tmp_path / "power_curve.metadata.yaml"
    metadata_path.write_text(
        "\n".join(
            [
                "schema_version: rider_power_curve_metadata_v1",
                "source_csv: other_power_curve.csv",
                "measurement_environment:",
                "  temperature_c: 26.0",
                "  relative_humidity_percent: 70.0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source_csv"):
        build_rider_power_curve(
            anchor_power_w=300.0,
            anchor_duration_min=30.0,
            rider_power_curve_csv=csv_path,
            rider_power_curve_metadata_yaml=metadata_path,
            thermal_adjustment_enabled=True,
            target_temperature_c=33.0,
            target_relative_humidity_percent=80.0,
            heat_loss_coefficient_per_h_c=0.008,
        )


def test_evaluate_mission_objective_reports_csv_power_curve_metadata(tmp_path: Path):
    csv_path = _write_power_curve_csv(
        tmp_path,
        [
            (60.0, 400.0),
            (120.0, 350.0),
            (300.0, 300.0),
            (600.0, 250.0),
            (1800.0, 220.0),
        ],
    )
    curve = build_rider_power_curve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
        rider_power_curve_csv=csv_path,
    )
    inputs = MissionEvaluationInputs(
        objective_mode="max_range",
        target_range_km=20.0,
        speed_mps=(10.0, 12.0, 14.0),
        power_required_w=(240.0, 220.0, 260.0),
        rider_curve=curve,
    )

    result = evaluate_mission_objective(inputs)

    assert result.pilot_power_model == "csv_power_curve"
    assert csv_path.name in result.pilot_power_anchor
    assert "30.0min" in result.pilot_power_anchor


@pytest.mark.parametrize("duration_min", [float("nan"), float("inf"), 0.0, -1.0])
def test_power_at_duration_min_rejects_invalid_inputs(duration_min):
    curve = FakeAnchorCurve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
    )

    with pytest.raises(ValueError):
        curve.power_at_duration_min(duration_min)


@pytest.mark.parametrize("power_w", [float("nan"), float("inf"), 0.0, -1.0])
def test_duration_at_power_w_rejects_invalid_inputs(power_w):
    curve = FakeAnchorCurve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
    )

    with pytest.raises(ValueError):
        curve.duration_at_power_w(power_w)


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


def test_evaluate_mission_objective_reports_target_distance_power_margin():
    curve = FakeAnchorCurve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
        exponent=1.0,
    )
    inputs = MissionEvaluationInputs(
        objective_mode="max_range",
        target_range_km=20.0,
        speed_mps=(10.0, 12.0, 14.0),
        power_required_w=(280.0, 315.0, 390.0),
        rider_curve=curve,
    )

    result = evaluate_mission_objective(inputs)
    expected_required_duration_min = tuple(
        inputs.target_range_km * 1000.0 / speed_mps / 60.0
        for speed_mps in inputs.speed_mps
    )
    expected_available_power_w = tuple(
        curve.power_at_duration_min(duration_min)
        for duration_min in expected_required_duration_min
    )
    expected_power_margin_w = tuple(
        available_power_w - required_power_w
        for available_power_w, required_power_w in zip(
            expected_available_power_w,
            inputs.power_required_w,
        )
    )

    assert result.required_duration_min_by_speed == pytest.approx(
        expected_required_duration_min
    )
    assert result.available_power_w_by_speed == pytest.approx(expected_available_power_w)
    assert result.power_margin_w_by_speed == pytest.approx(expected_power_margin_w)
    assert result.best_power_margin_w == pytest.approx(max(expected_power_margin_w))
    assert result.best_power_margin_speed_mps == pytest.approx(12.0)


def test_evaluate_mission_objective_reports_true_best_endurance():
    curve = FakeAnchorCurve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
        exponent=1.0,
    )
    inputs = MissionEvaluationInputs(
        objective_mode="max_range",
        target_range_km=20.0,
        speed_mps=(8.0, 12.0, 16.0),
        power_required_w=(200.0, 180.0, 190.0),
        rider_curve=curve,
    )

    result = evaluate_mission_objective(inputs)
    expected_durations_s = [
        curve.duration_at_power_w(power) * 60.0
        for power in inputs.power_required_w
    ]
    best_range_index = max(
        range(len(inputs.speed_mps)),
        key=lambda index: inputs.speed_mps[index] * expected_durations_s[index],
    )

    assert best_range_index != expected_durations_s.index(max(expected_durations_s))
    assert result.best_range_speed_mps == pytest.approx(inputs.speed_mps[best_range_index])
    assert result.best_endurance_s == pytest.approx(max(expected_durations_s))
    assert result.best_endurance_s != pytest.approx(expected_durations_s[best_range_index])


def test_evaluate_mission_objective_accepts_single_sample_speed():
    curve = FakeAnchorCurve(
        anchor_power_w=300.0,
        anchor_duration_min=30.0,
    )
    inputs = MissionEvaluationInputs(
        objective_mode="max_range",
        target_range_km=5.0,
        speed_mps=(9.0,),
        power_required_w=(220.0,),
        rider_curve=curve,
    )

    result = evaluate_mission_objective(inputs)
    expected_range_m = 9.0 * curve.duration_at_power_w(220.0) * 60.0

    assert result.best_range_m == pytest.approx(expected_range_m)
    assert result.best_range_speed_mps == pytest.approx(9.0)
    assert result.min_power_w == pytest.approx(220.0)
    assert result.min_power_speed_mps == pytest.approx(9.0)
    assert result.speed_sweep_window_mps == (9.0, 9.0)


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


@pytest.mark.parametrize("target_range_km", [0.0, -1.0, float("nan"), float("inf")])
def test_evaluate_mission_objective_rejects_invalid_target_range(target_range_km):
    inputs = MissionEvaluationInputs(
        objective_mode="max_range",
        target_range_km=target_range_km,
        speed_mps=(10.0, 11.0),
        power_required_w=(240.0, 230.0),
        rider_curve=FakeAnchorCurve(
            anchor_power_w=300.0,
            anchor_duration_min=30.0,
        ),
    )

    with pytest.raises(ValueError):
        evaluate_mission_objective(inputs)


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
