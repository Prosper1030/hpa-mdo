from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


_AIR_VISCOSITY_PA_S = 1.8e-5


@dataclass(frozen=True)
class ZoneDefinition:
    name: str
    y0_frac: float
    y1_frac: float


@dataclass(frozen=True)
class ZoneOperatingPoint:
    reynolds: float
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


def build_zone_requirements(
    spanwise_load,
    stations,
    zone_definitions: Sequence[ZoneDefinition],
) -> dict[str, ZoneRequirement]:
    if len(spanwise_load.y) != len(stations):
        raise ValueError("spanwise_load and stations must have the same number of entries.")
    if not zone_definitions:
        raise ValueError("zone_definitions must not be empty.")

    half_span_m = float(max(spanwise_load.y))
    velocity_mps = float(spanwise_load.velocity)
    if velocity_mps <= 0.0:
        raise ValueError("spanwise_load.velocity must be positive.")

    density_kg_per_m3 = 2.0 * float(spanwise_load.dynamic_pressure) / (velocity_mps**2)
    zone_requirements: dict[str, ZoneRequirement] = {}

    for zone_index, zone in enumerate(zone_definitions):
        zone_points: list[ZoneOperatingPoint] = []
        zone_y0_frac = zone.y0_frac
        zone_y1_frac = zone.y1_frac
        is_last_zone = zone_index == len(zone_definitions) - 1

        for y_m, chord_m, cl_value, cm_value in zip(
            spanwise_load.y,
            spanwise_load.chord,
            spanwise_load.cl,
            spanwise_load.cm,
        ):
            span_frac = 0.0 if half_span_m <= 0.0 else float(y_m) / half_span_m
            in_zone = zone_y0_frac <= span_frac < zone_y1_frac
            if is_last_zone and span_frac <= zone_y1_frac:
                in_zone = zone_y0_frac <= span_frac <= zone_y1_frac
            if not in_zone:
                continue

            reynolds = density_kg_per_m3 * velocity_mps * float(chord_m) / _AIR_VISCOSITY_PA_S
            zone_points.append(
                ZoneOperatingPoint(
                    reynolds=reynolds,
                    cl_target=float(cl_value),
                    cm_target=float(cm_value),
                    weight=1.0,
                )
            )

        zone_requirements[zone.name] = ZoneRequirement(
            name=zone.name,
            min_tc_ratio=_zone_min_tc_ratio(zone.name),
            points=tuple(zone_points),
        )

    return zone_requirements
