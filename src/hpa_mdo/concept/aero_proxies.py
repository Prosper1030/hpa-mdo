from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

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
    shape_penalty = min(
        float(proxy_cfg.spanload_shape_penalty_max),
        float(proxy_cfg.spanload_shape_penalty_slope) * rms_error,
    )
    geometry_knockdown = max(0.0, float(proxy_cfg.base_efficiency) - float(geometry_efficiency))
    efficiency = (
        float(proxy_cfg.efficiency_ceiling)
        - shape_penalty
        - float(proxy_cfg.spanload_geometry_knockdown_weight) * geometry_knockdown
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


def spanload_fourier_efficiency_records(
    *,
    concept: "GeometryConcept",
    station_points: list[dict[str, object]],
    harmonic_count: int = 8,
) -> list[dict[str, object]]:
    """Fit a lifting-line sine series to station loads and estimate span efficiency.

    The input load shape is the section lift proxy ``cl_target * chord``. For a
    symmetric wing, the positive-half stations are mirrored into ``theta`` space
    and fit to ``sum(A_n sin(n theta))``. The induced-drag shape factor follows
    the classic lifting-line relation ``1 / e = 1 + sum(n * (A_n/A_1)^2)``.
    """

    half_span_m = 0.5 * float(concept.span_m)
    if half_span_m <= 0.0 or harmonic_count < 1:
        return []

    grouped: dict[str, list[tuple[float, float]]] = {}
    for point in station_points:
        y_m = _numeric(point.get("station_y_m"))
        chord_m = _numeric(point.get("chord_m"))
        cl_target = _numeric(point.get("cl_target"))
        if y_m is None or chord_m is None or cl_target is None:
            continue
        if chord_m <= 0.0:
            continue
        eta = min(max(abs(y_m) / half_span_m, 0.0), 1.0)
        lift_shape = max(chord_m * cl_target, 0.0)
        case_label = str(point.get("case_label", "reference_avl_case"))
        grouped.setdefault(case_label, []).append((eta, lift_shape))

    records: list[dict[str, object]] = []
    for case_label, samples in grouped.items():
        unique_samples = sorted({(round(eta, 10), load) for eta, load in samples})
        if len(unique_samples) < 4:
            continue

        theta_values: list[float] = []
        load_values: list[float] = []
        for eta, lift_shape in unique_samples:
            theta = math.acos(min(max(eta, 0.0), 1.0))
            theta_values.append(theta)
            load_values.append(lift_shape)
            mirrored_theta = math.pi - theta
            if abs(mirrored_theta - theta) > 1.0e-9:
                theta_values.append(mirrored_theta)
                load_values.append(lift_shape)

        if max(load_values, default=0.0) <= 0.0:
            continue

        fit_harmonics = min(int(harmonic_count), max(1, len(theta_values) - 1))
        basis = np.asarray(
            [
                [math.sin(float(n) * theta) for n in range(1, fit_harmonics + 1)]
                for theta in theta_values
            ],
            dtype=float,
        )
        loads = np.asarray(load_values, dtype=float)
        try:
            coefficients, *_ = np.linalg.lstsq(basis, loads, rcond=None)
        except np.linalg.LinAlgError:
            continue

        first = float(coefficients[0])
        if abs(first) <= 1.0e-12 or not math.isfinite(first):
            continue
        drag_factor = 0.0
        normalized_coefficients = [1.0]
        for harmonic_index, coefficient in enumerate(coefficients[1:], start=2):
            ratio = float(coefficient) / first
            normalized_coefficients.append(float(ratio))
            drag_factor += float(harmonic_index) * ratio**2
        efficiency = 1.0 / max(1.0 + drag_factor, 1.0e-12)
        if not math.isfinite(efficiency) or efficiency <= 0.0:
            continue
        records.append(
            {
                "case_label": case_label,
                "source": "spanload_fourier_series_v1",
                "efficiency": float(min(efficiency, 1.0)),
                "spanload_fourier_deviation": float(math.sqrt(max(drag_factor, 0.0))),
                "fourier_drag_factor": float(drag_factor),
                "harmonic_count": int(fit_harmonics),
                "point_count": int(len(unique_samples)),
                "normalized_coefficients": normalized_coefficients,
            }
        )

    records.sort(
        key=lambda record: (
            0 if record["case_label"] == "reference_avl_case" else 1,
            str(record["case_label"]),
        )
    )
    return records


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


__all__ = [
    "oswald_efficiency_proxy",
    "spanload_efficiency_proxy",
    "spanload_fourier_efficiency_records",
    "misc_cd_proxy",
]
