"""Tests for the cruise-aware twist oracle (pure helpers, no AVL)."""

from __future__ import annotations

import math

from hpa_mdo.concept.cruise_twist_oracle import (
    OUTER_RATIO_TARGET_FLOOR,
    TWIST_BOUNDS_DEG,
    TwistVector,
    apply_twist_to_stations,
    twist_at_eta,
    _outer_ratio_metrics,
    _target_match_norm_delta,
    _twist_distribution,
    _twist_physical_gate_failures,
    _twist_smoothness_penalty,
)
from hpa_mdo.concept.geometry import WingStation


def _fake_stations() -> tuple[WingStation, ...]:
    return tuple(
        WingStation(
            y_m=float(eta * 17.0),
            chord_m=1.20 - 0.55 * eta,
            twist_deg=0.0,
            dihedral_deg=0.0,
        )
        for eta in (0.0, 0.125, 0.25, 0.5, 0.7, 0.85, 0.95, 1.0)
    )


def test_twist_at_eta_evaluates_each_dof_correctly() -> None:
    twist = TwistVector(
        root_incidence_deg=2.0,
        linear_washout_deg=-3.0,
        outer_bump_amp_deg=0.0,
        tip_correction_deg=0.0,
    )
    assert math.isclose(twist_at_eta(twist, 0.0), 2.0)
    assert math.isclose(twist_at_eta(twist, 1.0), -1.0)
    assert math.isclose(twist_at_eta(twist, 0.5), 0.5)


def test_twist_at_eta_includes_outer_bump_only_in_support() -> None:
    twist = TwistVector(0.0, 0.0, 1.0, 0.0)
    assert math.isclose(twist_at_eta(twist, 0.50), 0.0)
    assert twist_at_eta(twist, 0.85) > 0.99
    assert twist_at_eta(twist, 1.0) == 0.0


def test_apply_twist_to_stations_preserves_chord_and_dihedral() -> None:
    stations = _fake_stations()
    twist = TwistVector(2.0, -3.0, 0.5, -0.5)
    new_stations = apply_twist_to_stations(stations, twist)
    for orig, new in zip(stations, new_stations, strict=True):
        assert math.isclose(orig.chord_m, new.chord_m)
        assert math.isclose(orig.dihedral_deg, new.dihedral_deg)
        assert orig.y_m == new.y_m


def test_twist_distribution_records_range_and_jump() -> None:
    stations = _fake_stations()
    twist = TwistVector(2.0, -3.0, 0.5, -0.5)
    new = apply_twist_to_stations(stations, twist)
    distribution = _twist_distribution(stations=new, twist=twist)
    twists = distribution["stations_twist_deg"]
    assert distribution["twist_range_deg"] == max(twists) - min(twists)
    assert distribution["max_abs_twist_deg"] == max(abs(value) for value in twists)


def test_twist_physical_gate_failures_flags_oversized_amplitude() -> None:
    failures = _twist_physical_gate_failures(
        {
            "twist_range_deg": 9.0,
            "max_abs_twist_deg": 7.0,
            "max_adjacent_jump_deg": 3.0,
            "max_outer_wash_in_step_deg": 1.0,
        }
    )
    assert "twist_max_abs_exceeded" in failures
    assert "twist_range_exceeded" in failures
    assert "twist_adjacent_jump_exceeded" in failures
    assert "outer_monotonic_washout_failed" in failures


def test_smoothness_penalty_grows_with_amplitude() -> None:
    small = _twist_smoothness_penalty(TwistVector(2.0, -3.0, 0.5, -0.5))
    large = _twist_smoothness_penalty(TwistVector(4.5, -6.0, 2.5, -2.0))
    assert large > small


def test_outer_ratio_metrics_handles_eta_window_tolerance() -> None:
    table = [
        {"eta": 0.5, "avl_to_target_circulation_ratio": 0.95},
        {"eta": 0.79999, "avl_to_target_circulation_ratio": 0.6},
        {"eta": 0.85, "avl_to_target_circulation_ratio": 0.5},
        {"eta": 0.92001, "avl_to_target_circulation_ratio": 0.55},
        {"eta": 0.95, "avl_to_target_circulation_ratio": 0.7},
    ]
    rmin, rmean = _outer_ratio_metrics(table, (0.80, 0.92))
    assert rmin is not None and rmin == 0.5
    assert rmean is not None
    assert math.isclose(rmean, sum([0.6, 0.5, 0.55]) / 3.0, rel_tol=1.0e-9)


def test_target_match_norm_delta_reports_rms_and_max() -> None:
    table = [
        {"target_circulation_norm": 1.0, "avl_circulation_norm": 0.9},
        {"target_circulation_norm": 0.5, "avl_circulation_norm": 0.5},
        {"target_circulation_norm": 0.3, "avl_circulation_norm": 0.0},
    ]
    rms, max_delta = _target_match_norm_delta(table)
    assert math.isclose(max_delta, 0.3, rel_tol=1.0e-9)
    assert math.isclose(rms, math.sqrt((0.1**2 + 0.0**2 + 0.3**2) / 3.0), rel_tol=1.0e-9)


def test_outer_ratio_target_floor_is_85_percent_of_target() -> None:
    assert math.isclose(OUTER_RATIO_TARGET_FLOOR, 0.85)


def test_twist_bounds_deg_define_all_four_dof() -> None:
    assert set(TWIST_BOUNDS_DEG.keys()) == {
        "root_incidence_deg",
        "linear_washout_deg",
        "outer_bump_amp_deg",
        "tip_correction_deg",
    }
    for low, high in TWIST_BOUNDS_DEG.values():
        assert low < high
