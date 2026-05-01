from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Sequence

from hpa_mdo.concept.atmosphere import LEGACY_DEFAULT_DYNAMIC_VISCOSITY_PA_S

_AIR_VISCOSITY_PA_S = LEGACY_DEFAULT_DYNAMIC_VISCOSITY_PA_S


@dataclass(frozen=True)
class ZoneDefinition:
    name: str
    y0_frac: float
    y1_frac: float


@dataclass(frozen=True)
class ZoneOperatingPoint:
    reynolds: float
    chord_m: float
    cl_target: float
    cm_target: float
    weight: float


@dataclass(frozen=True)
class ZoneRequirement:
    name: str
    min_tc_ratio: float
    points: tuple[ZoneOperatingPoint, ...]


def default_zone_definitions() -> tuple[ZoneDefinition, ...]:
    return (
        ZoneDefinition("root", 0.00, 0.25),
        ZoneDefinition("mid1", 0.25, 0.55),
        ZoneDefinition("mid2", 0.55, 0.80),
        ZoneDefinition("tip", 0.80, 1.00),
    )


def _zone_min_tc_ratio(zone_name: str) -> float:
    return 0.14 if zone_name == "root" else 0.10


def _validate_zone_definitions(zone_definitions: Sequence[ZoneDefinition]) -> tuple[ZoneDefinition, ...]:
    validated = tuple(zone_definitions)
    if not validated:
        raise ValueError("zone_definitions must not be empty.")
    names = [zone.name for zone in validated]
    if len(set(names)) != len(names):
        raise ValueError("zone_definitions names must be unique.")

    previous_end = 0.0
    for index, zone in enumerate(validated):
        if not (0.0 <= zone.y0_frac < zone.y1_frac <= 1.0):
            raise ValueError("zone definition bounds must satisfy 0 <= y0 < y1 <= 1.")
        if index == 0:
            if not isclose(zone.y0_frac, 0.0, abs_tol=1e-9):
                raise ValueError("zone definitions must start at 0.0.")
        elif not isclose(zone.y0_frac, previous_end, abs_tol=1e-9):
            raise ValueError("zone definitions must be contiguous and non-overlapping.")
        previous_end = zone.y1_frac

    if not isclose(previous_end, 1.0, abs_tol=1e-9):
        raise ValueError("zone definitions must cover the full [0, 1] span.")
    return validated


def _station_span_fractions(stations) -> tuple[float, ...]:
    if not stations:
        raise ValueError("stations must not be empty.")

    y_positions = tuple(float(station.y_m) for station in stations)
    if any(later <= earlier for earlier, later in zip(y_positions, y_positions[1:])):
        raise ValueError("stations must be strictly increasing in spanwise position.")

    start_y_m = y_positions[0]
    half_span_m = y_positions[-1] - start_y_m
    if half_span_m <= 0.0:
        raise ValueError("stations must span a positive half-span.")

    return tuple((y_m - start_y_m) / half_span_m for y_m in y_positions)


def _station_coverage_weights(stations) -> tuple[float, ...]:
    y_positions = tuple(float(station.y_m) for station in stations)
    if len(y_positions) == 1:
        return (1.0,)

    start_y_m = y_positions[0]
    end_y_m = y_positions[-1]
    half_span_m = end_y_m - start_y_m
    if half_span_m <= 0.0:
        raise ValueError("stations must span a positive half-span.")

    boundaries = [start_y_m]
    boundaries.extend(0.5 * (left + right) for left, right in zip(y_positions[:-1], y_positions[1:]))
    boundaries.append(end_y_m)

    widths = tuple(max(right - left, 0.0) for left, right in zip(boundaries[:-1], boundaries[1:]))
    total_width = sum(widths)
    if total_width <= 0.0:
        raise ValueError("stations must define a positive coverage interval.")
    return tuple(width / total_width for width in widths)


def build_zone_requirements(
    spanwise_load,
    stations,
    zone_definitions: Sequence[ZoneDefinition],
    *,
    dynamic_viscosity_pa_s: float = _AIR_VISCOSITY_PA_S,
) -> dict[str, ZoneRequirement]:
    validated_zone_definitions = _validate_zone_definitions(zone_definitions)
    span_fractions = _station_span_fractions(stations)
    coverage_weights = _station_coverage_weights(stations)

    station_count = len(stations)
    if len(spanwise_load.y) != station_count:
        raise ValueError("spanwise_load.y must have the same number of entries as stations.")
    if len(spanwise_load.chord) != station_count:
        raise ValueError("spanwise_load.chord must have the same number of entries as stations.")
    if len(spanwise_load.cl) != station_count:
        raise ValueError("spanwise_load.cl must have the same number of entries as stations.")
    if len(spanwise_load.cm) != station_count:
        raise ValueError("spanwise_load.cm must have the same number of entries as stations.")

    velocity_mps = float(spanwise_load.velocity)
    if velocity_mps <= 0.0:
        raise ValueError("spanwise_load.velocity must be positive.")
    dynamic_viscosity = float(dynamic_viscosity_pa_s)
    if dynamic_viscosity <= 0.0:
        raise ValueError("dynamic_viscosity_pa_s must be positive.")

    density_kg_per_m3 = 2.0 * float(spanwise_load.dynamic_pressure) / (velocity_mps**2)
    zone_requirements: dict[str, ZoneRequirement] = {}

    for zone_index, zone in enumerate(validated_zone_definitions):
        zone_points: list[ZoneOperatingPoint] = []
        zone_y0_frac = zone.y0_frac
        zone_y1_frac = zone.y1_frac
        is_last_zone = zone_index == len(validated_zone_definitions) - 1

        for span_frac, chord_m, cl_value, cm_value, weight in zip(
            span_fractions,
            spanwise_load.chord,
            spanwise_load.cl,
            spanwise_load.cm,
            coverage_weights,
        ):
            in_zone = zone_y0_frac <= span_frac < zone_y1_frac
            if is_last_zone and span_frac <= zone_y1_frac:
                in_zone = zone_y0_frac <= span_frac <= zone_y1_frac
            if not in_zone:
                continue

            reynolds = density_kg_per_m3 * velocity_mps * float(chord_m) / dynamic_viscosity
            zone_points.append(
                ZoneOperatingPoint(
                    reynolds=reynolds,
                    chord_m=float(chord_m),
                    cl_target=float(cl_value),
                    cm_target=float(cm_value),
                    weight=float(weight),
                )
            )

        zone_requirements[zone.name] = ZoneRequirement(
            name=zone.name,
            min_tc_ratio=_zone_min_tc_ratio(zone.name),
            points=tuple(zone_points),
        )

    return zone_requirements
