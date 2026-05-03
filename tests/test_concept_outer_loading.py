"""Tests for the reusable outer-loading low-order intervention module."""

from __future__ import annotations

import math

import pytest

from hpa_mdo.concept.geometry import WingStation
from hpa_mdo.concept.outer_loading import (
    OUTER_BUMP_HI_ETA,
    OUTER_BUMP_LO_ETA,
    OUTER_BUMP_PEAK_ETA,
    apply_outer_ainc_bump,
    apply_outer_chord_redistribution,
    outer_smooth_bump,
)


def _baseline_stations() -> tuple[WingStation, ...]:
    return tuple(
        WingStation(y_m=float(y), chord_m=float(c), twist_deg=float(t), dihedral_deg=float(d))
        for y, c, t, d in (
            (0.0, 1.45, 2.0, 1.0),
            (2.778, 1.205, 1.088, 1.8),
            (6.077, 1.058, 1.223, 2.75),
            (9.029, 0.997, 1.981, 3.6),
            (12.155, 0.927, 1.981, 4.5),
            (14.239, 0.878, 1.488, 5.1),
            (15.628, 0.823, 0.884, 5.5),
            (16.496, 0.706, 0.507, 5.75),
            (17.364, 0.706, 0.355, 6.0),
        )
    )


def _trapezoidal_half_area(stations: tuple[WingStation, ...]) -> float:
    half = 0.0
    for left, right in zip(stations[:-1], stations[1:], strict=True):
        dy = float(right.y_m) - float(left.y_m)
        half += 0.5 * dy * (float(left.chord_m) + float(right.chord_m))
    return float(half)


def test_outer_smooth_bump_zero_outside_support() -> None:
    assert outer_smooth_bump(0.0) == 0.0
    assert outer_smooth_bump(0.50) == 0.0
    assert outer_smooth_bump(OUTER_BUMP_LO_ETA) == 0.0
    assert outer_smooth_bump(OUTER_BUMP_HI_ETA) == 0.0
    assert outer_smooth_bump(1.0) == 0.0


def test_outer_smooth_bump_peaks_at_one() -> None:
    assert math.isclose(outer_smooth_bump(OUTER_BUMP_PEAK_ETA), 1.0, abs_tol=1.0e-12)


def test_outer_smooth_bump_is_continuous_and_non_negative() -> None:
    grid = [eta / 200.0 for eta in range(201)]
    values = [outer_smooth_bump(eta) for eta in grid]
    assert min(values) >= 0.0
    max_jump = max(abs(b - a) for a, b in zip(values[:-1], values[1:]))
    assert max_jump < 0.10


def test_apply_outer_ainc_bump_changes_only_twist_in_outer_band() -> None:
    stations = _baseline_stations()
    bumped = apply_outer_ainc_bump(stations=stations, amplitude_deg=2.0)
    half_span = stations[-1].y_m
    for original, new in zip(stations, bumped, strict=True):
        eta = original.y_m / half_span
        assert math.isclose(original.chord_m, new.chord_m, rel_tol=1.0e-12)
        assert math.isclose(original.dihedral_deg, new.dihedral_deg, rel_tol=1.0e-12)
        delta = new.twist_deg - original.twist_deg
        if eta <= OUTER_BUMP_LO_ETA + 1.0e-9 or eta >= OUTER_BUMP_HI_ETA - 1.0e-9:
            assert math.isclose(delta, 0.0, abs_tol=1.0e-9)
        else:
            assert delta >= -1.0e-9
            assert delta <= 2.0 + 1.0e-9


@pytest.mark.parametrize("amplitude", [0.05, 0.10, 0.20, 0.30, 0.40])
def test_apply_outer_chord_redistribution_preserves_total_area(amplitude: float) -> None:
    stations = _baseline_stations()
    original_half_area = _trapezoidal_half_area(stations)
    redistributed, diag = apply_outer_chord_redistribution(
        stations=stations, amplitude=amplitude
    )
    assert diag.succeeded
    new_half_area = _trapezoidal_half_area(redistributed)
    assert math.isclose(original_half_area, new_half_area, rel_tol=1.0e-9, abs_tol=1.0e-9)
    assert math.isclose(diag.original_half_area_m2, original_half_area, rel_tol=1.0e-12)
    assert abs(diag.relative_area_error) < 1.0e-9


def test_apply_outer_chord_redistribution_grows_outer_and_shrinks_inner() -> None:
    stations = _baseline_stations()
    redistributed, diag = apply_outer_chord_redistribution(stations=stations, amplitude=0.30)
    assert diag.succeeded
    half_span = stations[-1].y_m
    for original, new in zip(stations, redistributed, strict=True):
        eta = original.y_m / half_span
        if OUTER_BUMP_LO_ETA + 1.0e-3 < eta < OUTER_BUMP_HI_ETA - 1.0e-3:
            assert new.chord_m >= original.chord_m
        elif eta <= 0.50:
            assert new.chord_m <= original.chord_m + 1.0e-9


def test_apply_outer_chord_redistribution_reports_smoothness_metrics() -> None:
    stations = _baseline_stations()
    _, diag = apply_outer_chord_redistribution(stations=stations, amplitude=0.30)
    assert diag.succeeded
    assert diag.max_adjacent_chord_ratio < 1.45
    assert diag.max_chord_second_difference_m < 0.35


def test_apply_outer_chord_redistribution_zero_amplitude_is_passthrough() -> None:
    stations = _baseline_stations()
    redistributed, diag = apply_outer_chord_redistribution(stations=stations, amplitude=0.0)
    assert diag.succeeded
    assert math.isclose(diag.amplitude, 0.0)
    for original, new in zip(stations, redistributed, strict=True):
        assert math.isclose(original.chord_m, new.chord_m, rel_tol=1.0e-12)


def test_apply_outer_chord_redistribution_rejects_when_chord_floor_violated() -> None:
    stations = _baseline_stations()
    redistributed, diag = apply_outer_chord_redistribution(
        stations=stations, amplitude=0.30, chord_floor_m=2.0
    )
    assert not diag.succeeded
    assert diag.failure_reason == "chord_below_floor"
    assert redistributed is stations


def test_apply_outer_chord_redistribution_rejects_when_inner_compensation_below_floor() -> None:
    # Outer chord is so much larger than inner chord that the inner
    # compensation factor would have to be negative to keep the area constant.
    stations = (
        WingStation(y_m=0.0, chord_m=0.50, twist_deg=0.0, dihedral_deg=0.0),
        WingStation(y_m=0.85, chord_m=0.50, twist_deg=0.0, dihedral_deg=0.0),
        WingStation(y_m=1.0, chord_m=0.50, twist_deg=0.0, dihedral_deg=0.0),
    )
    redistributed, diag = apply_outer_chord_redistribution(
        stations=stations, amplitude=1.5
    )
    assert not diag.succeeded
    assert diag.failure_reason == "inner_compensation_scale_below_floor"
    assert redistributed is stations


def test_apply_outer_chord_redistribution_rejects_when_only_inner_stations_present() -> None:
    # When all stations sit inside the inner band there is no outer bump, but
    # if the bump support is forced wide enough that no station counts as
    # inner the helper still rejects with a clear reason.
    stations = (
        WingStation(y_m=0.0, chord_m=0.30, twist_deg=0.0, dihedral_deg=0.0),
        WingStation(y_m=1.0, chord_m=0.30, twist_deg=0.0, dihedral_deg=0.0),
        WingStation(y_m=2.0, chord_m=0.30, twist_deg=0.0, dihedral_deg=0.0),
    )
    redistributed, diag = apply_outer_chord_redistribution(
        stations=stations,
        amplitude=0.40,
        inner_compensation_end_eta=-0.01,
    )
    assert not diag.succeeded
    assert diag.failure_reason == "no_inner_stations_for_area_compensation"
    assert redistributed is stations
