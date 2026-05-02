from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hpa_mdo.concept.config import (
        OswaldEfficiencyProxyConfig,
        ParasiteDragProxyConfig,
    )
    from hpa_mdo.concept.geometry import GeometryConcept


def oswald_efficiency_proxy(
    *,
    concept: "GeometryConcept",
    proxy_cfg: "OswaldEfficiencyProxyConfig",
) -> float:
    """Return Oswald-efficiency proxy for the concept.

    Linear knockdown around ``proxy_cfg.base_efficiency`` driven by:
    - dihedral spread (tip - root, only positive part)
    - twist spread (|tip - root|)
    Clamped to ``[efficiency_floor, efficiency_ceiling]``.
    """
    dihedral_delta = max(
        0.0, float(concept.dihedral_tip_deg) - float(concept.dihedral_root_deg)
    )
    twist_delta = abs(float(concept.twist_tip_deg) - float(concept.twist_root_deg))
    efficiency = (
        float(proxy_cfg.base_efficiency)
        - float(proxy_cfg.dihedral_delta_slope_per_deg) * dihedral_delta
        - float(proxy_cfg.twist_delta_slope_per_deg) * twist_delta
    )
    return max(
        float(proxy_cfg.efficiency_floor),
        min(float(proxy_cfg.efficiency_ceiling), efficiency),
    )


def _numeric(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _spanwise_width_weights(y_values: list[float], *, half_span_m: float) -> list[float]:
    if len(y_values) == 1:
        return [1.0]
    boundaries = [0.0]
    boundaries.extend(0.5 * (left + right) for left, right in zip(y_values[:-1], y_values[1:]))
    boundaries.append(float(half_span_m))
    widths = [max(right - left, 0.0) for left, right in zip(boundaries[:-1], boundaries[1:])]
    total_width = sum(widths)
    if total_width <= 0.0:
        return [1.0 / float(len(y_values)) for _ in y_values]
    return [width / total_width for width in widths]


def spanload_efficiency_proxy(
    *,
    concept: "GeometryConcept",
    station_points: list[dict[str, object]],
    proxy_cfg: "OswaldEfficiencyProxyConfig",
) -> dict[str, float | str | None]:
    """Estimate an Oswald-like efficiency from the station lift shape.

    This is still a concept-stage proxy, not an AVL Trefftz-plane result. It
    does, however, make the mission drag model respond to the spanwise
    distribution carried by AVL/fallback station points instead of using only
    global geometry knobs. The proxy compares the normalized section lift
    shape, ``cl * chord``, against an elliptic target and penalizes RMS shape
    error while retaining a smaller knockdown for twist/dihedral complexity.
    """

    geometry_efficiency = oswald_efficiency_proxy(concept=concept, proxy_cfg=proxy_cfg)
    valid_points: list[tuple[float, float, float]] = []
    half_span_m = 0.5 * float(concept.span_m)
    for point in station_points:
        y_m = _numeric(point.get("station_y_m"))
        chord_m = _numeric(point.get("chord_m"))
        cl_target = _numeric(point.get("cl_target"))
        if y_m is None or chord_m is None or cl_target is None:
            continue
        if chord_m <= 0.0:
            continue
        valid_points.append((max(0.0, y_m), chord_m, max(0.0, cl_target)))

    if len(valid_points) < 3 or half_span_m <= 0.0:
        return {
            "efficiency": float(geometry_efficiency),
            "source": "concept_geometry_proxy_v1",
            "spanload_rms_error": None,
            "geometry_efficiency_proxy": float(geometry_efficiency),
        }

    valid_points.sort(key=lambda item: item[0])
    y_values = [min(y_m, half_span_m) for y_m, _, _ in valid_points]
    weights = _spanwise_width_weights(y_values, half_span_m=half_span_m)
    lift_shape = [max(chord_m * cl_target, 1.0e-9) for _, chord_m, cl_target in valid_points]
    elliptic_shape = [
        max(math.sqrt(max(1.0 - (min(y_m / half_span_m, 1.0)) ** 2, 0.0)), 1.0e-6)
        for y_m in y_values
    ]

    mean_lift = sum(weight * value for weight, value in zip(weights, lift_shape, strict=True))
    mean_elliptic = sum(
        weight * value for weight, value in zip(weights, elliptic_shape, strict=True)
    )
    if mean_lift <= 0.0 or mean_elliptic <= 0.0:
        return {
            "efficiency": float(geometry_efficiency),
            "source": "concept_geometry_proxy_v1",
            "spanload_rms_error": None,
            "geometry_efficiency_proxy": float(geometry_efficiency),
        }

    rms_error = math.sqrt(
        sum(
            weight * ((lift / mean_lift) - (elliptic / mean_elliptic)) ** 2
            for weight, lift, elliptic in zip(weights, lift_shape, elliptic_shape, strict=True)
        )
    )
    shape_penalty = min(0.18, 0.22 * rms_error)
    geometry_knockdown = max(0.0, float(proxy_cfg.base_efficiency) - float(geometry_efficiency))
    efficiency = (
        float(proxy_cfg.efficiency_ceiling)
        - shape_penalty
        - 0.50 * geometry_knockdown
    )
    efficiency = max(
        float(proxy_cfg.efficiency_floor),
        min(float(proxy_cfg.efficiency_ceiling), efficiency),
    )
    return {
        "efficiency": float(efficiency),
        "source": "spanload_shape_proxy_v1",
        "spanload_rms_error": float(rms_error),
        "geometry_efficiency_proxy": float(geometry_efficiency),
    }


def misc_cd_proxy(
    *,
    profile_cd: float,
    tail_area_ratio: float,
    proxy_cfg: "ParasiteDragProxyConfig",
) -> float:
    """Return the lumped fuselage + tail-coupling parasite drag coefficient.

    misc_cd = fuselage_misc_cd + tail_profile_coupling_factor
              * tail_area_ratio * profile_cd
    """
    return (
        float(proxy_cfg.fuselage_misc_cd)
        + float(proxy_cfg.tail_profile_coupling_factor)
        * float(tail_area_ratio)
        * float(profile_cd)
    )


__all__ = ["oswald_efficiency_proxy", "spanload_efficiency_proxy", "misc_cd_proxy"]
