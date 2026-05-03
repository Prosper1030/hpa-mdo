"""Outer-loading low-order interventions.

The Birdman mission-coupled spanload search is bounded by an outer-underloaded
geometry: AVL trim balances total CL by overloading the inner wing, leaving
the eta=0.70-0.95 region with about half the target circulation.  This module
hosts the validated low-order knobs the optimizer pipeline can use against
that failure mode:

* :func:`outer_smooth_bump` - the smooth cosine bump shape that all outer
  authority knobs share (eta range and peak controllable, 1.0 at peak,
  0.0 at the edges).
* :func:`apply_outer_chord_redistribution` - apply the bump to chord while
  scaling inner stations to keep total wing area unchanged.  Returns the
  redistributed stations and a diagnostic describing area error, chord
  bounds, and a smoothness metric.
* :func:`apply_outer_ainc_bump` - adds the bump to the station incidence
  (twist) without touching chord.  Used by the standalone authority sweep.

The implementations were validated against AVL by
``scripts/birdman_outer_loading_authority_sweep.py``: a +0.20 chord bump on
sample 1476 lifts e_CDi from 0.870 to 0.906 with all twist/tip/Fourier
gates remaining green.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from hpa_mdo.concept.geometry import WingStation


OUTER_BUMP_LO_ETA: float = 0.65
OUTER_BUMP_PEAK_ETA: float = 0.85
OUTER_BUMP_HI_ETA: float = 0.98

INNER_AREA_COMPENSATION_END_ETA: float = 0.55
DEFAULT_CHORD_FLOOR_M: float = 0.30


@dataclass(frozen=True)
class ChordRedistributionDiagnostic:
    """Audit trail for a chord-bump redistribution.

    All values are reported even when the redistribution succeeds so the
    caller (or downstream gates) can surface them in candidate metadata.
    """

    amplitude: float
    """Requested outer-chord-bump amplitude (0.0 means passthrough)."""

    inner_compensation_scale: float
    """Multiplier applied to inner stations so total wing area is preserved."""

    original_half_area_m2: float
    new_half_area_m2: float
    half_area_error_m2: float
    """``new_half_area - original_half_area`` after compensation; expected to
    be tiny for a well-behaved bump."""

    relative_area_error: float
    """``half_area_error / original_half_area``."""

    root_chord_m: float
    tip_chord_m: float
    min_chord_m: float

    max_adjacent_chord_ratio: float
    """``max(left, right) / min(left, right)`` over neighbouring stations.

    The Birdman planform-tip-protection gate currently rejects > 1.45.
    """

    max_chord_second_difference_m: float
    """Discrete second-difference proxy for chord curvature; the existing
    Birdman gate rejects > 0.35."""

    succeeded: bool
    """False when the requested redistribution could not be realised within
    the chord floor (the caller should reject the candidate)."""

    failure_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "outer_chord_bump_amp": float(self.amplitude),
            "inner_compensation_scale": float(self.inner_compensation_scale),
            "original_half_area_m2": float(self.original_half_area_m2),
            "new_half_area_m2": float(self.new_half_area_m2),
            "half_area_error_m2": float(self.half_area_error_m2),
            "relative_area_error": float(self.relative_area_error),
            "root_chord_m": float(self.root_chord_m),
            "tip_chord_m": float(self.tip_chord_m),
            "min_chord_m": float(self.min_chord_m),
            "max_adjacent_chord_ratio": float(self.max_adjacent_chord_ratio),
            "max_chord_second_difference_m": float(self.max_chord_second_difference_m),
            "succeeded": bool(self.succeeded),
            "failure_reason": self.failure_reason,
        }


def outer_smooth_bump(
    eta: float,
    *,
    eta_lo: float = OUTER_BUMP_LO_ETA,
    eta_peak: float = OUTER_BUMP_PEAK_ETA,
    eta_hi: float = OUTER_BUMP_HI_ETA,
) -> float:
    """Smooth cosine bump on ``eta in [eta_lo, eta_hi]`` peaking at ``eta_peak``.

    Returns 0 outside ``(eta_lo, eta_hi)`` and 1 at ``eta_peak``.  Both halves
    of the bump are half-cosines so the function is C^1 across the support.
    """

    eta_clamped = float(eta)
    if eta_clamped <= eta_lo or eta_clamped >= eta_hi:
        return 0.0
    if eta_clamped <= eta_peak:
        denom = max(eta_peak - eta_lo, 1.0e-9)
        return 0.5 * (1.0 - math.cos(math.pi * (eta_clamped - eta_lo) / denom))
    denom = max(eta_hi - eta_peak, 1.0e-9)
    return 0.5 * (1.0 + math.cos(math.pi * (eta_clamped - eta_peak) / denom))


def _half_area_from_chords(
    stations: tuple[WingStation, ...],
    chords: Iterable[float],
) -> float:
    chord_list = [float(value) for value in chords]
    half = 0.0
    for left, right, c_left, c_right in zip(
        stations[:-1], stations[1:], chord_list[:-1], chord_list[1:], strict=True
    ):
        dy = float(right.y_m) - float(left.y_m)
        half += 0.5 * dy * (float(c_left) + float(c_right))
    return float(half)


def apply_outer_ainc_bump(
    *,
    stations: tuple[WingStation, ...],
    amplitude_deg: float,
    eta_lo: float = OUTER_BUMP_LO_ETA,
    eta_peak: float = OUTER_BUMP_PEAK_ETA,
    eta_hi: float = OUTER_BUMP_HI_ETA,
) -> tuple[WingStation, ...]:
    """Add an outer Ainc bump (in deg) to ``station.twist_deg``.

    Chord, dihedral and station y are untouched.  The amplitude is the value
    of the additive bump at ``eta_peak``; values at other eta scale with
    :func:`outer_smooth_bump`.
    """

    if not stations:
        return stations
    half_span_m = max(float(stations[-1].y_m), 1.0e-9)
    return tuple(
        WingStation(
            y_m=float(station.y_m),
            chord_m=float(station.chord_m),
            twist_deg=float(station.twist_deg)
            + float(amplitude_deg)
            * outer_smooth_bump(
                float(station.y_m) / half_span_m,
                eta_lo=eta_lo,
                eta_peak=eta_peak,
                eta_hi=eta_hi,
            ),
            dihedral_deg=float(station.dihedral_deg),
        )
        for station in stations
    )


def apply_outer_chord_redistribution(
    *,
    stations: tuple[WingStation, ...],
    amplitude: float,
    inner_compensation_end_eta: float = INNER_AREA_COMPENSATION_END_ETA,
    eta_lo: float = OUTER_BUMP_LO_ETA,
    eta_peak: float = OUTER_BUMP_PEAK_ETA,
    eta_hi: float = OUTER_BUMP_HI_ETA,
    chord_floor_m: float = DEFAULT_CHORD_FLOOR_M,
) -> tuple[tuple[WingStation, ...], ChordRedistributionDiagnostic]:
    """Apply a smooth outer chord bump and compensate inner chord to keep
    total wing area constant.

    The bump scales chord by ``1 + amplitude * outer_smooth_bump(eta)`` for
    stations whose ``eta = y/half_span`` lies above
    ``inner_compensation_end_eta``; inner stations are uniformly scaled by a
    single factor so that the post-bump trapezoidal half area equals the
    pre-bump half area.  The compensation factor is solved analytically (the
    half-area is linear in the compensation scale).

    The returned diagnostic exposes ``half_area_error_m2``,
    ``relative_area_error``, the post-bump root/tip/min chord, and a
    smoothness metric (max adjacent chord ratio + max second-difference) so
    the caller can assert the candidate stays within manufacturing gates.

    If amplitude <= 0, the original stations are returned and the diagnostic
    reports a passthrough.

    The redistribution is rejected (``succeeded=False`` and a non-empty
    ``failure_reason``) when:

    * the inner stations would need to be scaled below 0.5 to absorb the
      area added outboard, or
    * any station chord ends up below ``chord_floor_m``.
    """

    if not stations or len(stations) < 2:
        return stations, ChordRedistributionDiagnostic(
            amplitude=float(amplitude),
            inner_compensation_scale=1.0,
            original_half_area_m2=0.0,
            new_half_area_m2=0.0,
            half_area_error_m2=0.0,
            relative_area_error=0.0,
            root_chord_m=float(stations[0].chord_m) if stations else 0.0,
            tip_chord_m=float(stations[-1].chord_m) if stations else 0.0,
            min_chord_m=float(min(s.chord_m for s in stations)) if stations else 0.0,
            max_adjacent_chord_ratio=1.0,
            max_chord_second_difference_m=0.0,
            succeeded=False,
            failure_reason="not_enough_stations" if not stations else "single_station",
        )

    half_span_m = max(float(stations[-1].y_m), 1.0e-9)
    original_chords = [float(station.chord_m) for station in stations]
    original_half_area = _half_area_from_chords(stations, original_chords)

    if float(amplitude) <= 0.0:
        diag = ChordRedistributionDiagnostic(
            amplitude=float(amplitude),
            inner_compensation_scale=1.0,
            original_half_area_m2=float(original_half_area),
            new_half_area_m2=float(original_half_area),
            half_area_error_m2=0.0,
            relative_area_error=0.0,
            root_chord_m=float(original_chords[0]),
            tip_chord_m=float(original_chords[-1]),
            min_chord_m=float(min(original_chords)),
            max_adjacent_chord_ratio=_max_adjacent_chord_ratio(original_chords),
            max_chord_second_difference_m=_max_chord_second_difference(original_chords),
            succeeded=True,
            failure_reason=None,
        )
        return stations, diag

    inner_flags: list[bool] = []
    bumped_chords: list[float] = []
    for station, chord_orig in zip(stations, original_chords):
        eta = float(station.y_m) / half_span_m
        bump = outer_smooth_bump(eta, eta_lo=eta_lo, eta_peak=eta_peak, eta_hi=eta_hi)
        inner_flags.append(eta <= inner_compensation_end_eta)
        bumped_chords.append(chord_orig * (1.0 + float(amplitude) * bump))

    half_area_outer_only = _half_area_from_chords(
        stations,
        [
            bumped if not inner else 0.0
            for bumped, inner in zip(bumped_chords, inner_flags)
        ],
    )
    half_area_inner_unit = _half_area_from_chords(
        stations,
        [
            chord if inner else 0.0
            for chord, inner in zip(original_chords, inner_flags)
        ],
    )

    if half_area_inner_unit <= 0.0:
        return stations, ChordRedistributionDiagnostic(
            amplitude=float(amplitude),
            inner_compensation_scale=1.0,
            original_half_area_m2=float(original_half_area),
            new_half_area_m2=float(original_half_area),
            half_area_error_m2=0.0,
            relative_area_error=0.0,
            root_chord_m=float(original_chords[0]),
            tip_chord_m=float(original_chords[-1]),
            min_chord_m=float(min(original_chords)),
            max_adjacent_chord_ratio=_max_adjacent_chord_ratio(original_chords),
            max_chord_second_difference_m=_max_chord_second_difference(original_chords),
            succeeded=False,
            failure_reason="no_inner_stations_for_area_compensation",
        )

    raw_scale = (original_half_area - half_area_outer_only) / half_area_inner_unit
    if not math.isfinite(raw_scale):
        return stations, ChordRedistributionDiagnostic(
            amplitude=float(amplitude),
            inner_compensation_scale=1.0,
            original_half_area_m2=float(original_half_area),
            new_half_area_m2=float(original_half_area),
            half_area_error_m2=0.0,
            relative_area_error=0.0,
            root_chord_m=float(original_chords[0]),
            tip_chord_m=float(original_chords[-1]),
            min_chord_m=float(min(original_chords)),
            max_adjacent_chord_ratio=_max_adjacent_chord_ratio(original_chords),
            max_chord_second_difference_m=_max_chord_second_difference(original_chords),
            succeeded=False,
            failure_reason="inner_compensation_scale_not_finite",
        )

    if raw_scale < 0.5:
        return stations, ChordRedistributionDiagnostic(
            amplitude=float(amplitude),
            inner_compensation_scale=float(raw_scale),
            original_half_area_m2=float(original_half_area),
            new_half_area_m2=float(original_half_area),
            half_area_error_m2=0.0,
            relative_area_error=0.0,
            root_chord_m=float(original_chords[0]),
            tip_chord_m=float(original_chords[-1]),
            min_chord_m=float(min(original_chords)),
            max_adjacent_chord_ratio=_max_adjacent_chord_ratio(original_chords),
            max_chord_second_difference_m=_max_chord_second_difference(original_chords),
            succeeded=False,
            failure_reason="inner_compensation_scale_below_floor",
        )
    scale = float(min(1.5, raw_scale))

    new_chords = [
        chord_orig * scale if inner else bumped
        for chord_orig, bumped, inner in zip(original_chords, bumped_chords, inner_flags)
    ]

    if any(chord < float(chord_floor_m) for chord in new_chords):
        return stations, ChordRedistributionDiagnostic(
            amplitude=float(amplitude),
            inner_compensation_scale=float(scale),
            original_half_area_m2=float(original_half_area),
            new_half_area_m2=float(_half_area_from_chords(stations, new_chords)),
            half_area_error_m2=0.0,
            relative_area_error=0.0,
            root_chord_m=float(new_chords[0]),
            tip_chord_m=float(new_chords[-1]),
            min_chord_m=float(min(new_chords)),
            max_adjacent_chord_ratio=_max_adjacent_chord_ratio(new_chords),
            max_chord_second_difference_m=_max_chord_second_difference(new_chords),
            succeeded=False,
            failure_reason="chord_below_floor",
        )

    new_half_area = _half_area_from_chords(stations, new_chords)
    half_area_error = new_half_area - original_half_area
    relative_area_error = half_area_error / max(original_half_area, 1.0e-9)

    redistributed = tuple(
        WingStation(
            y_m=float(station.y_m),
            chord_m=float(chord),
            twist_deg=float(station.twist_deg),
            dihedral_deg=float(station.dihedral_deg),
        )
        for station, chord in zip(stations, new_chords, strict=True)
    )
    return redistributed, ChordRedistributionDiagnostic(
        amplitude=float(amplitude),
        inner_compensation_scale=float(scale),
        original_half_area_m2=float(original_half_area),
        new_half_area_m2=float(new_half_area),
        half_area_error_m2=float(half_area_error),
        relative_area_error=float(relative_area_error),
        root_chord_m=float(new_chords[0]),
        tip_chord_m=float(new_chords[-1]),
        min_chord_m=float(min(new_chords)),
        max_adjacent_chord_ratio=_max_adjacent_chord_ratio(new_chords),
        max_chord_second_difference_m=_max_chord_second_difference(new_chords),
        succeeded=True,
        failure_reason=None,
    )


def _max_adjacent_chord_ratio(chords: list[float]) -> float:
    if len(chords) < 2:
        return 1.0
    ratios = [
        max(left, right) / max(min(left, right), 1.0e-9)
        for left, right in zip(chords[:-1], chords[1:])
    ]
    return float(max(ratios, default=1.0))


def _max_chord_second_difference(chords: list[float]) -> float:
    if len(chords) < 3:
        return 0.0
    differences = [
        abs(right - 2.0 * center + left)
        for left, center, right in zip(chords[:-2], chords[1:-1], chords[2:])
    ]
    return float(max(differences, default=0.0))
