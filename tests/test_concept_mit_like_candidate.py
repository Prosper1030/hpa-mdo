"""Tests for the MIT-like high-AR Birdman candidate generator."""

from __future__ import annotations

from pathlib import Path

import math

from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.mit_like_candidate import (
    DEFAULT_AR_RANGE,
    DEFAULT_TAPER_RATIO_RANGE,
    generate_mit_like_candidates,
    stations_for_mit_like_candidate,
)


CONFIG_PATH = Path("configs/birdman_upstream_concept_baseline.yaml")


def test_generate_mit_like_candidates_lands_in_requested_envelope() -> None:
    cfg = load_concept_config(CONFIG_PATH)
    candidates = generate_mit_like_candidates(
        cfg=cfg,
        sample_count=16,
        seed=20260601,
    )
    assert candidates, "should produce at least one candidate from a 16-sample Sobol"
    for candidate in candidates:
        assert DEFAULT_AR_RANGE[0] - 1.0e-6 <= candidate.aspect_ratio <= DEFAULT_AR_RANGE[1] + 1.0e-6
        assert (
            DEFAULT_TAPER_RATIO_RANGE[0] - 1.0e-6
            <= candidate.taper_ratio
            <= DEFAULT_TAPER_RATIO_RANGE[1] + 1.0e-6
        )
        assert candidate.tip_chord_m >= 0.42 - 1.0e-9
        assert candidate.root_chord_m >= 1.05 - 1.0e-9
        # Wing area is the trapezoidal area for a linear chord planform.
        expected_area = (
            0.5 * (candidate.root_chord_m + candidate.tip_chord_m) * candidate.span_m
        )
        assert math.isclose(candidate.wing_area_m2, expected_area, rel_tol=1.0e-9)


def test_generate_mit_like_candidates_deterministic_for_seed() -> None:
    cfg = load_concept_config(CONFIG_PATH)
    a = generate_mit_like_candidates(cfg=cfg, sample_count=8, seed=20260601)
    b = generate_mit_like_candidates(cfg=cfg, sample_count=8, seed=20260601)
    assert len(a) == len(b)
    for left, right in zip(a, b, strict=True):
        assert math.isclose(left.aspect_ratio, right.aspect_ratio, rel_tol=1.0e-12)
        assert math.isclose(left.taper_ratio, right.taper_ratio, rel_tol=1.0e-12)
        assert math.isclose(left.span_m, right.span_m, rel_tol=1.0e-12)


def test_generate_mit_like_candidates_does_not_emit_chord_bump() -> None:
    cfg = load_concept_config(CONFIG_PATH)
    candidates = generate_mit_like_candidates(cfg=cfg, sample_count=8, seed=20260601)
    for candidate in candidates:
        summary = candidate.to_summary()
        assert summary["outer_chord_bump_amp"] == 0.0


def test_stations_for_mit_like_candidate_are_trapezoidal_and_monotone() -> None:
    cfg = load_concept_config(CONFIG_PATH)
    candidates = generate_mit_like_candidates(cfg=cfg, sample_count=4, seed=20260601)
    assert candidates
    candidate = candidates[0]
    stations = stations_for_mit_like_candidate(candidate=candidate, stations_per_half=9)
    assert len(stations) == 9
    half_span = stations[-1].y_m
    assert math.isclose(half_span, 0.5 * candidate.span_m, rel_tol=1.0e-12)
    # Chord linearly interpolates root → tip.
    for station in stations:
        eta = station.y_m / max(half_span, 1.0e-9)
        expected_chord = candidate.root_chord_m + (
            candidate.tip_chord_m - candidate.root_chord_m
        ) * eta
        assert math.isclose(station.chord_m, expected_chord, rel_tol=1.0e-9)
    # Twist must be monotone washout.
    twists = [s.twist_deg for s in stations]
    for left, right in zip(twists[:-1], twists[1:]):
        assert right <= left + 1.0e-9
