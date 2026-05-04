import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from hpa_mdo.mission import (
    CsvPowerCurve,
    FakeAnchorCurve,
    MissionQuickScreenInputs,
    RiderPowerEnvironment,
    evaluate_quick_screen,
    load_csv_power_curve,
    simplified_heat_stress_h,
    thermal_power_derate_factor,
)
from hpa_mdo.mission import sweep_quick_screen_grid


def _write_power_curve_csv(tmp_path: Path, rows: list[tuple[float, float]]) -> Path:
    csv_path = tmp_path / "power_curve.csv"
    csv_path.write_text(
        "secs,watts\n"
        + "\n".join(f"{secs},{watts}" for secs, watts in rows)
        + "\n",
        encoding="utf-8",
    )
    return csv_path


def _reference_inputs(
    *,
    rider_curve: FakeAnchorCurve | CsvPowerCurve | None,
    cl_max_effective: float = 1.55,
    cd0_total: float = 0.020,
) -> MissionQuickScreenInputs:
    return MissionQuickScreenInputs(
        speed_mps=6.5,
        span_m=35.0,
        aspect_ratio=38.0,
        mass_kg=98.5,
        cd0_total=cd0_total,
        oswald_e=0.9,
        air_density_kg_m3=1.1357,
        eta_prop=0.86,
        eta_trans=0.96,
        target_range_km=42.195,
        rider_curve=rider_curve,
        thermal_derate_factor=0.9159364331845841,
        cl_max_effective=cl_max_effective,
    )


def test_quick_screen_reuses_existing_thermal_functions():
    test_env = RiderPowerEnvironment(temperature_c=26.0, relative_humidity_percent=70.0)
    race_env = RiderPowerEnvironment(temperature_c=33.0, relative_humidity_percent=80.0)

    assert simplified_heat_stress_h(test_env) == pytest.approx(
        27.900900638173272
    )
    assert simplified_heat_stress_h(race_env) == pytest.approx(
        38.40884649010027
    )
    assert thermal_power_derate_factor(
        test_environment=test_env,
        target_environment=race_env,
        heat_loss_coefficient_per_h_c=0.008,
    ) == pytest.approx(0.9159364331845841)
    assert thermal_power_derate_factor(
        test_environment=test_env,
        target_environment=race_env,
        heat_loss_coefficient_per_h_c=0.01,
    ) == pytest.approx(0.8949205414807301)


def test_evaluate_quick_screen_uses_rider_curve_with_required_time_lookup(tmp_path: Path):
    csv_path = _write_power_curve_csv(
        tmp_path,
        [
            (6000.0, 213.0),
            (6600.0, 212.0),
            (7200.0, 211.0),
        ],
    )
    rider_curve = load_csv_power_curve(csv_path)
    inputs = _reference_inputs(rider_curve=rider_curve)

    result = evaluate_quick_screen(inputs)

    assert result.required_time_min == pytest.approx(108.1923076923, rel=1e-9)
    assert result.pilot_power_test_w == pytest.approx(212.18076923077, abs=1.0e-9)
    assert result.pilot_power_test_w != 213.0
    assert result.pilot_power_hot_w == pytest.approx(
        212.18076923077 * 0.9159364331845841,
        abs=1.0e-9,
    )


def test_evaluate_quick_screen_reference_case_matches_expected_numbers():
    rider_curve = FakeAnchorCurve(
        anchor_power_w=213.0,
        anchor_duration_min=108.1923076923077,
        exponent=1.0,
    )
    result = evaluate_quick_screen(_reference_inputs(rider_curve=rider_curve))

    assert result.wing_area_m2 == pytest.approx(32.23684210526316)
    assert result.required_time_min == pytest.approx(108.1923)
    assert result.cl_required == pytest.approx(1.24895, abs=1e-3)
    assert result.cd_induced == pytest.approx(0.01452, abs=1e-4)
    assert result.induced_power_air_w == pytest.approx(72.99, abs=1e-2)
    assert result.parasite_power_air_w == pytest.approx(100.54, abs=1e-2)
    assert result.total_power_air_w == pytest.approx(173.53, abs=1e-2)
    assert result.required_crank_power_w == pytest.approx(210.19, abs=1e-2)
    assert result.pilot_power_hot_w == pytest.approx(195.09, abs=1e-2)
    assert result.power_margin_crank_w == pytest.approx(-15.09, abs=1e-2)
    assert result.cd0_max == pytest.approx(0.01752, abs=1e-4)
    assert result.power_passed is False
    assert result.cl_band == "normal"


def test_evaluate_quick_screen_stall_metrics_reference_case():
    result = evaluate_quick_screen(_reference_inputs(rider_curve=None))

    assert result.cl_required == pytest.approx(1.24895, abs=1e-3)
    assert result.cl_to_clmax_ratio == pytest.approx(0.8058, abs=1e-3)
    assert result.stall_speed_mps == pytest.approx(5.835, rel=1e-3)
    assert result.stall_margin_speed_ratio == pytest.approx(1.114, rel=1e-2)
    assert result.stall_band == "caution"


@pytest.mark.parametrize(
    ("cl_max_effective", "expected_band"),
    [
        (2.5, "healthy"),
        (1.45, "caution"),
        (1.30, "thin_margin"),
        (1.20, "over_clmax"),
    ],
)
def test_stall_band_classification_uses_ratio(cl_max_effective: float, expected_band: str) -> None:
    result = evaluate_quick_screen(_reference_inputs(rider_curve=None, cl_max_effective=cl_max_effective))
    assert result.stall_band == expected_band


def test_evaluate_quick_screen_no_rider_curve_marks_power_fields_none():
    result = evaluate_quick_screen(
        _reference_inputs(rider_curve=None),
    )

    assert result.pilot_power_test_w is None
    assert result.pilot_power_hot_w is None
    assert result.power_margin_crank_w is None
    assert result.critical_drag_n is None
    assert result.cd0_max is None
    assert result.power_passed is None


def test_evaluate_quick_screen_reuses_aspect_ratio_and_cd0_inputs():
    rider_curve = FakeAnchorCurve(anchor_power_w=213.0, anchor_duration_min=108.1923076923077)
    ar_38 = evaluate_quick_screen(_reference_inputs(rider_curve=rider_curve))
    ar_40 = evaluate_quick_screen(
        replace(_reference_inputs(rider_curve=rider_curve), aspect_ratio=40.0)
    )

    assert ar_40.wing_area_m2 == pytest.approx(35.0**2 / 40.0)
    assert ar_40.wing_area_m2 != pytest.approx(ar_38.wing_area_m2)
    assert ar_40.cl_required != pytest.approx(ar_38.cl_required)
    assert ar_40.required_time_min == pytest.approx(ar_38.required_time_min)


def test_sweep_quick_screen_grid_returns_full_combinational_results(tmp_path: Path):
    csv_path = _write_power_curve_csv(
        tmp_path,
        [
            (6000.0, 213.0),
            (6600.0, 212.0),
            (7200.0, 211.0),
        ],
    )
    rider_curve = load_csv_power_curve(csv_path)
    results = sweep_quick_screen_grid(
        speeds_mps=[6.0, 6.5],
        spans_m=[34.0, 35.0],
        aspect_ratios=[38.0, 40.0],
        cd0_totals=[0.018, 0.020],
        mass_kg=98.5,
        oswald_e=0.9,
        air_density_kg_m3=1.1357,
        eta_prop=0.86,
        eta_trans=0.96,
        target_range_km=42.195,
        rider_curve=rider_curve,
        thermal_derate_factor=0.9159364331845841,
    )

    assert len(results) == 16
    assert any(result.aspect_ratio == 40.0 for result in results)
    assert any(result.cd0_total == 0.018 for result in results)


def test_sweep_quick_screen_grid_supports_clmax_list(tmp_path: Path):
    csv_path = _write_power_curve_csv(
        tmp_path,
        [
            (6000.0, 213.0),
            (6600.0, 212.0),
            (7200.0, 211.0),
        ],
    )
    rider_curve = load_csv_power_curve(csv_path)
    results = sweep_quick_screen_grid(
        speeds_mps=[6.0, 6.5],
        spans_m=[35.0],
        aspect_ratios=[38.0],
        cd0_totals=[0.017, 0.020],
        mass_kg=98.5,
        oswald_e=0.9,
        air_density_kg_m3=1.1357,
        eta_prop=0.86,
        eta_trans=0.96,
        target_range_km=42.195,
        cl_max_effectives=[1.45, 1.55, 1.65],
        rider_curve=rider_curve,
        thermal_derate_factor=0.9159364331845841,
    )

    assert len(results) == 12
    assert any(result.cl_max_effective == 1.45 for result in results)
    assert any(result.cl_max_effective == 1.55 for result in results)
    assert any(result.cl_max_effective == 1.65 for result in results)


def test_mission_quick_screen_sweep_cli_smoke(tmp_path: Path) -> None:
    power_csv = tmp_path / "pilot_power_curve.csv"
    power_csv.write_text(
        "secs,watts\n6000,213\n6600,212\n7200,211\n",
        encoding="utf-8",
    )
    metadata_yaml = tmp_path / "metadata.yaml"
    metadata_yaml.write_text(
        """\
schema_version: rider_power_curve_metadata_v1
source_csv: pilot_power_curve.csv
measurement_environment:
  temperature_c: 26.0
  relative_humidity_percent: 70.0
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "quick_screen_sweep"
    repo_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "scripts/mission_quick_screen_sweep.py",
            "--power-csv",
            str(power_csv),
            "--metadata-yaml",
            str(metadata_yaml),
            "--speed-min",
            "6.0",
            "--speed-max",
            "6.5",
            "--speed-step",
            "0.5",
            "--span-list",
            "34",
            "--ar-list",
            "38",
            "--cd0-list",
            "0.018",
            "--clmax-list",
            "1.45,1.55",
            "--mass-kg",
            "98.5",
            "--output-dir",
            str(output_dir),
            "--target-temp-c",
            "33",
            "--target-rh",
            "80",
            "--heat-k",
            "0.008",
        ],
        check=True,
        cwd=repo_root,
    )

    assert (output_dir / "results.csv").exists()
    assert (output_dir / "report.md").exists()
    lines = (output_dir / "results.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) > 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("speed_mps", 0.0),
        ("speed_mps", float("nan")),
        ("span_m", 0.0),
        ("aspect_ratio", 0.0),
        ("mass_kg", -1.0),
        ("cd0_total", -1e-3),
        ("oswald_e", 0.0),
        ("oswald_e", 1.3),
        ("air_density_kg_m3", -1.0),
        ("gravity_m_s2", 0.0),
        ("eta_prop", 0.0),
        ("eta_prop", 1.1),
        ("eta_trans", 0.0),
        ("target_range_km", 0.0),
        ("thermal_derate_factor", -0.1),
        ("cl_max_effective", 0.0),
        ("cl_max_effective", 3.01),
    ],
)
def test_evaluate_quick_screen_invalid_inputs_raise_value_error(
    field: str,
    value: float,
) -> None:
    base = _reference_inputs(rider_curve=None)
    with pytest.raises(ValueError):
        evaluate_quick_screen(replace(base, **{field: value}))
