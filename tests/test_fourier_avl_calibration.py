from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from hpa_mdo.aero.fourier_avl_calibration import (
    FourierAvlCalibrationCase,
    fit_case_to_fourier_bridge,
    write_fourier_avl_calibration_artifacts,
)


def _synthetic_rows(
    *,
    span_m: float,
    speed_mps: float,
    a1: float,
    r3: float,
    r5: float,
    r7: float,
    avl_scale_outer: float = 1.0,
) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for index in range(81):
        eta = index / 80.0
        theta = math.acos(eta)
        target_gamma = 2.0 * span_m * speed_mps * a1 * (
            math.sin(theta)
            + r3 * math.sin(3.0 * theta)
            + r5 * math.sin(5.0 * theta)
            + r7 * math.sin(7.0 * theta)
        )
        avl_gamma = target_gamma * (avl_scale_outer if eta >= 0.72 else 1.0)
        rows.append(
            {
                "eta": eta,
                "y_m": 0.5 * span_m * eta,
                "chord_m": 1.1 - 0.35 * eta,
                "target_circulation": target_gamma,
                "Gamma_avl_m2ps": avl_gamma,
            }
        )
    return rows


def test_fit_case_recovers_low_order_fourier_coefficients() -> None:
    case = FourierAvlCalibrationCase(
        case_id="synthetic_match",
        station_rows=_synthetic_rows(
            span_m=34.0,
            speed_mps=6.5,
            a1=0.012,
            r3=-0.06,
            r5=0.018,
            r7=-0.007,
        ),
        span_m=34.0,
        speed_mps=6.5,
        e_avl_cdi=0.91,
    )

    result = fit_case_to_fourier_bridge(case)

    assert result.fit_row["A1"] == pytest.approx(0.012, rel=1.0e-8)
    assert result.fit_row["r3"] == pytest.approx(-0.06, rel=1.0e-8)
    assert result.fit_row["r5"] == pytest.approx(0.018, rel=1.0e-8)
    assert result.fit_row["r7"] == pytest.approx(-0.007, rel=1.0e-8)
    assert result.bridge_row["bridge_status"] == "calibrated"
    assert result.bridge_row["target_vs_avl_rms"] == pytest.approx(0.0, abs=1.0e-10)


def test_fit_case_is_independent_of_station_row_order() -> None:
    case = FourierAvlCalibrationCase(
        case_id="synthetic_reversed_rows",
        station_rows=list(
            reversed(
                _synthetic_rows(
                    span_m=34.0,
                    speed_mps=6.5,
                    a1=0.012,
                    r3=-0.06,
                    r5=0.018,
                    r7=-0.007,
                )
            )
        ),
        span_m=34.0,
        speed_mps=6.5,
        e_avl_cdi=0.91,
    )

    result = fit_case_to_fourier_bridge(case)

    assert result.fit_row["r3"] == pytest.approx(-0.06, rel=1.0e-8)
    assert result.fit_row["r5"] == pytest.approx(0.018, rel=1.0e-8)
    assert result.fit_row["r7"] == pytest.approx(-0.007, rel=1.0e-8)


def test_fit_case_classifies_outer_loading_authority_mismatch() -> None:
    case = FourierAvlCalibrationCase(
        case_id="synthetic_outer_underloaded",
        station_rows=_synthetic_rows(
            span_m=34.0,
            speed_mps=6.5,
            a1=0.012,
            r3=-0.04,
            r5=0.01,
            r7=0.0,
            avl_scale_outer=0.62,
        ),
        span_m=34.0,
        speed_mps=6.5,
        e_avl_cdi=0.83,
    )

    result = fit_case_to_fourier_bridge(case)

    assert result.bridge_row["bridge_status"] == "outer_underloaded_authority_limited"
    assert result.bridge_row["target_vs_avl_outer_delta"] > 0.1
    assert result.bridge_row["outer_lift_fraction_avl"] < result.bridge_row["outer_lift_fraction_command"]


def test_fit_case_converts_legacy_avl_cl_times_chord_export_to_gamma() -> None:
    speed_mps = 6.5
    rows = _synthetic_rows(
        span_m=34.0,
        speed_mps=speed_mps,
        a1=0.012,
        r3=-0.06,
        r5=0.018,
        r7=-0.007,
    )
    for row in rows:
        row["avl_circulation"] = 2.0 * row.pop("Gamma_avl_m2ps") / speed_mps
    case = FourierAvlCalibrationCase(
        case_id="legacy_station_export",
        station_rows=rows,
        span_m=34.0,
        speed_mps=speed_mps,
    )

    result = fit_case_to_fourier_bridge(case)

    assert result.fit_row["A1"] == pytest.approx(0.012, rel=1.0e-8)
    assert result.fit_row["loading_source"] == "legacy_avl_cl_times_chord_converted_to_gamma"
    assert result.fit_row["coefficient_basis"].startswith("Gamma_m2ps")


def test_fit_case_classifies_outer_overloading_separately() -> None:
    case = FourierAvlCalibrationCase(
        case_id="synthetic_outer_overloaded",
        station_rows=_synthetic_rows(
            span_m=34.0,
            speed_mps=6.5,
            a1=0.012,
            r3=-0.04,
            r5=0.01,
            r7=0.0,
            avl_scale_outer=1.45,
        ),
        span_m=34.0,
        speed_mps=6.5,
        e_avl_cdi=0.83,
    )

    result = fit_case_to_fourier_bridge(case)

    assert result.bridge_row["bridge_status"] == "outer_overloaded_realization_mismatch"
    assert result.bridge_row["outer_lift_fraction_avl"] > result.bridge_row["outer_lift_fraction_command"]


def test_artifact_writer_emits_mvp_contract_files(tmp_path: Path) -> None:
    case = FourierAvlCalibrationCase(
        case_id="synthetic_artifact",
        station_rows=_synthetic_rows(
            span_m=34.0,
            speed_mps=6.5,
            a1=0.012,
            r3=-0.05,
            r5=0.02,
            r7=0.0,
        ),
        span_m=34.0,
        speed_mps=6.5,
        e_avl_cdi=0.89,
        source_artifact="unit-test",
        notes="source_report=unit-test-report.json",
    )

    output = write_fourier_avl_calibration_artifacts([case], tmp_path)

    expected_names = {
        "spanload_definition.md",
        "avl_to_fourier_fit.csv",
        "fourier_command_to_avl_realized.csv",
        "fourier_avl_calibration_report.md",
        "recommended_fourier_bridge.md",
    }
    assert expected_names <= {path.name for path in output.values()}
    assert (tmp_path / "spanload_definition.md").read_text(encoding="utf-8").startswith(
        "# Spanload Definition"
    )
    with (tmp_path / "avl_to_fourier_fit.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["case_id"] == "synthetic_artifact"
    assert rows[0]["source_artifact"] == "unit-test"
    assert rows[0]["source_report"] == "unit-test-report.json"
