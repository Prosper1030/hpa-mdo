from __future__ import annotations

from dataclasses import dataclass
from math import floor, isclose
from itertools import product


@dataclass(frozen=True)
class WingStation:
    y_m: float
    chord_m: float
    twist_deg: float
    dihedral_deg: float


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
    dihedral_root_deg: float = 0.0
    dihedral_tip_deg: float = 0.0
    dihedral_exponent: float = 1.0

    def __post_init__(self) -> None:
        segment_lengths_m = tuple(float(length) for length in self.segment_lengths_m)
        object.__setattr__(self, "segment_lengths_m", segment_lengths_m)

        if self.span_m <= 0.0:
            raise ValueError("span_m must be positive.")
        if self.wing_area_m2 <= 0.0:
            raise ValueError("wing_area_m2 must be positive.")
        if self.root_chord_m <= 0.0:
            raise ValueError("root_chord_m must be positive.")
        if self.tip_chord_m <= 0.0:
            raise ValueError("tip_chord_m must be positive.")
        if self.dihedral_exponent <= 0.0:
            raise ValueError("dihedral_exponent must be positive.")
        if self.tail_area_m2 <= 0.0:
            raise ValueError("tail_area_m2 must be positive.")
        if not 0.0 <= self.cg_xc <= 1.0:
            raise ValueError("cg_xc must be in [0, 1].")
        if self.dihedral_root_deg < -10.0 or self.dihedral_root_deg > 10.0:
            raise ValueError("dihedral_root_deg must be in [-10, 10].")
        if self.dihedral_tip_deg < -10.0 or self.dihedral_tip_deg > 10.0:
            raise ValueError("dihedral_tip_deg must be in [-10, 10].")
        if self.dihedral_tip_deg < self.dihedral_root_deg:
            raise ValueError("dihedral_tip_deg must be >= dihedral_root_deg.")
        if not self.segment_lengths_m:
            raise ValueError("segment_lengths_m must not be empty.")
        if any(length <= 0.0 for length in self.segment_lengths_m):
            raise ValueError("segment_lengths_m entries must all be positive.")

        half_span_m = 0.5 * self.span_m
        if not isclose(sum(self.segment_lengths_m), half_span_m, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("segment_lengths_m must sum to half-span within tolerance.")

        expected_area_m2 = self.span_m * (self.root_chord_m + self.tip_chord_m) / 2.0
        if not isclose(self.wing_area_m2, expected_area_m2, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("trapezoidal wing area is inconsistent with span/root/tip chord.")


def _progressive_schedule_value(
    start_value: float,
    end_value: float,
    frac: float,
    exponent: float,
) -> float:
    return start_value + (frac**exponent) * (end_value - start_value)


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
    segment_count = len(concept.segment_lengths_m)
    boundary_count = segment_count + 1
    if stations_per_half < boundary_count:
        raise ValueError(
            "stations_per_half must be at least len(concept.segment_lengths_m) + 1."
        )

    half_span_m = 0.5 * concept.span_m
    boundaries = [0.0]
    for segment_length in concept.segment_lengths_m:
        boundaries.append(boundaries[-1] + float(segment_length))

    if stations_per_half == boundary_count:
        y_locations = tuple(boundaries)
    else:
        extra_points = stations_per_half - boundary_count
        total_length = sum(concept.segment_lengths_m)
        ideal_shares = [
            extra_points * (segment_length / total_length)
            for segment_length in concept.segment_lengths_m
        ]
        per_segment_interior_points = [int(floor(share)) for share in ideal_shares]
        remaining_points = extra_points - sum(per_segment_interior_points)
        fractional_order = sorted(
            range(segment_count),
            key=lambda index: (
                -(ideal_shares[index] - per_segment_interior_points[index]),
                -concept.segment_lengths_m[index],
                index,
            ),
        )
        for index in fractional_order[:remaining_points]:
            per_segment_interior_points[index] += 1

        y_locations: list[float] = [boundaries[0]]
        for segment_index, (start_y_m, end_y_m) in enumerate(zip(boundaries, boundaries[1:])):
            interior_count = per_segment_interior_points[segment_index]
            segment_length_m = end_y_m - start_y_m
            for interior_index in range(1, interior_count + 1):
                frac = interior_index / float(interior_count + 1)
                y_locations.append(start_y_m + frac * segment_length_m)
            y_locations.append(end_y_m)
        y_locations = tuple(y_locations)

    stations: list[WingStation] = []
    for y_m in y_locations:
        frac = 0.0 if half_span_m == 0.0 else y_m / half_span_m
        chord_m = concept.root_chord_m + frac * (concept.tip_chord_m - concept.root_chord_m)
        twist_deg = concept.twist_root_deg + frac * (concept.twist_tip_deg - concept.twist_root_deg)
        dihedral_deg = _progressive_schedule_value(
            concept.dihedral_root_deg,
            concept.dihedral_tip_deg,
            frac,
            concept.dihedral_exponent,
        )
        stations.append(
            WingStation(y_m=y_m, chord_m=chord_m, twist_deg=twist_deg, dihedral_deg=dihedral_deg)
        )
    return tuple(stations)


def enumerate_geometry_concepts(cfg) -> tuple[GeometryConcept, ...]:
    concepts: list[GeometryConcept] = []
    for (
        span_m,
        wing_area_m2,
        taper_ratio,
        twist_tip_deg,
        tail_area_m2,
        dihedral_root_deg,
        dihedral_tip_deg,
        dihedral_exponent,
    ) in product(
        cfg.geometry_family.span_candidates_m,
        cfg.geometry_family.wing_area_candidates_m2,
        cfg.geometry_family.taper_ratio_candidates,
        cfg.geometry_family.twist_tip_candidates_deg,
        cfg.geometry_family.tail_area_candidates_m2,
        cfg.geometry_family.dihedral_root_deg_candidates,
        cfg.geometry_family.dihedral_tip_deg_candidates,
        cfg.geometry_family.dihedral_exponent_candidates,
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
                dihedral_root_deg=float(dihedral_root_deg),
                dihedral_tip_deg=float(dihedral_tip_deg),
                dihedral_exponent=float(dihedral_exponent),
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
