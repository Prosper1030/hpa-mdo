from __future__ import annotations

from dataclasses import dataclass
from itertools import product


@dataclass(frozen=True)
class WingStation:
    y_m: float
    chord_m: float
    twist_deg: float


@dataclass(frozen=True)
class GeometryConcept:
    span_m: float
    wing_area_m2: float
    root_chord_m: float
    tip_chord_m: float
    twist_root_deg: float
    twist_tip_deg: float
    tail_area_m2: float
    cg_xc: float
    segment_lengths_m: tuple[float, ...]


def build_segment_plan(
    *,
    half_span_m: float,
    min_segment_length_m: float,
    max_segment_length_m: float,
) -> tuple[float, ...]:
    if half_span_m <= 0.0:
        raise ValueError("half_span_m must be positive.")
    if min_segment_length_m <= 0.0:
        raise ValueError("min_segment_length_m must be positive.")
    if max_segment_length_m < min_segment_length_m:
        raise ValueError("max_segment_length_m must be >= min_segment_length_m.")

    segment_count = max(1, int(-(-half_span_m // max_segment_length_m)))
    segment_length = half_span_m / float(segment_count)
    if segment_length < min_segment_length_m:
        raise ValueError("half_span_m cannot be segmented within the configured bounds.")

    return tuple(float(segment_length) for _ in range(segment_count))


def build_linear_wing_stations(
    concept: GeometryConcept,
    *,
    stations_per_half: int,
) -> tuple[WingStation, ...]:
    if stations_per_half < 2:
        raise ValueError("stations_per_half must be at least 2.")

    half_span_m = 0.5 * concept.span_m
    stations: list[WingStation] = []
    for index in range(stations_per_half):
        frac = index / float(stations_per_half - 1)
        y_m = half_span_m * frac
        chord_m = concept.root_chord_m + frac * (concept.tip_chord_m - concept.root_chord_m)
        twist_deg = concept.twist_root_deg + frac * (concept.twist_tip_deg - concept.twist_root_deg)
        stations.append(WingStation(y_m=y_m, chord_m=chord_m, twist_deg=twist_deg))
    return tuple(stations)


def enumerate_geometry_concepts(cfg) -> tuple[GeometryConcept, ...]:
    concepts: list[GeometryConcept] = []
    for (
        span_m,
        wing_area_m2,
        taper_ratio,
        twist_tip_deg,
        tail_area_m2,
    ) in product(
        cfg.geometry_family.span_candidates_m,
        cfg.geometry_family.wing_area_candidates_m2,
        cfg.geometry_family.taper_ratio_candidates,
        cfg.geometry_family.twist_tip_candidates_deg,
        cfg.geometry_family.tail_area_candidates_m2,
    ):
        root_chord_m = 2.0 * wing_area_m2 / (span_m * (1.0 + taper_ratio))
        tip_chord_m = root_chord_m * taper_ratio
        concepts.append(
            GeometryConcept(
                span_m=float(span_m),
                wing_area_m2=float(wing_area_m2),
                root_chord_m=float(root_chord_m),
                tip_chord_m=float(tip_chord_m),
                twist_root_deg=2.0,
                twist_tip_deg=float(twist_tip_deg),
                tail_area_m2=float(tail_area_m2),
                cg_xc=0.30,
                segment_lengths_m=build_segment_plan(
                    half_span_m=0.5 * float(span_m),
                    min_segment_length_m=cfg.segmentation.min_segment_length_m,
                    max_segment_length_m=cfg.segmentation.max_segment_length_m,
                ),
            )
        )
    return tuple(concepts)
