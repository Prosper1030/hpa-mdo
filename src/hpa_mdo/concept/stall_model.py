from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SafeLocalClmax:
    raw_clmax: float
    raw_source: str
    safe_clmax: float
    source_scale: float
    source_delta: float
    span_fraction: float
    tip_3d_penalty: float
    tip_taper_penalty: float
    washout_relief: float


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _smoothstep01(value: float) -> float:
    x = _clamp(value, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def safe_clmax_source_label(raw_source: str) -> str:
    source_map = {
        "airfoil_observed_lower_bound": "airfoil_safe_lower_bound",
        "airfoil_observed": "airfoil_safe_observed",
        "geometry_proxy": "geometry_safe_proxy",
    }
    return source_map.get(str(raw_source), f"safe_clmax_model_v2:{raw_source}")


def _resolved_source_adjustment(
    *,
    raw_source: str,
    safe_scale: float,
    safe_delta: float,
) -> tuple[float, float]:
    raw_source = str(raw_source)
    if raw_source == "geometry_proxy":
        return max(0.0, float(safe_scale) - 0.02), float(safe_delta) + 0.02
    if raw_source == "airfoil_observed":
        return min(1.0, float(safe_scale) + 0.02), max(0.0, float(safe_delta) - 0.01)
    return float(safe_scale), float(safe_delta)


def compute_safe_local_clmax(
    *,
    raw_clmax: float,
    raw_source: str,
    span_fraction: float,
    taper_ratio: float,
    washout_deg: float,
    safe_scale: float,
    safe_delta: float,
    tip_3d_penalty_start_eta: float,
    tip_3d_penalty_max: float,
    tip_taper_penalty_weight: float,
    washout_relief_deg: float,
    washout_relief_max: float,
    safe_clmax_floor: float = 0.10,
) -> SafeLocalClmax:
    span_fraction = _clamp(float(span_fraction), 0.0, 1.0)
    taper_ratio = max(float(taper_ratio), 1.0e-6)
    washout_deg = max(float(washout_deg), 0.0)
    safe_scale, safe_delta = _resolved_source_adjustment(
        raw_source=str(raw_source),
        safe_scale=float(safe_scale),
        safe_delta=float(safe_delta),
    )

    tip_3d_penalty = 0.0
    tip_taper_penalty = 0.0
    washout_relief = 0.0
    if span_fraction > float(tip_3d_penalty_start_eta) and float(tip_3d_penalty_max) > 0.0:
        start_eta = _clamp(float(tip_3d_penalty_start_eta), 0.0, 0.999)
        span_progress = _smoothstep01((span_fraction - start_eta) / max(1.0 - start_eta, 1.0e-9))
        taper_severity = _clamp((0.40 - taper_ratio) / 0.20, 0.0, 1.0)
        tip_taper_penalty = (
            span_progress
            * float(tip_3d_penalty_max)
            * float(tip_taper_penalty_weight)
            * taper_severity
        )
        washout_relief = (
            span_progress
            * float(washout_relief_max)
            * _clamp(washout_deg / max(float(washout_relief_deg), 1.0e-9), 0.0, 1.0)
        )
        tip_3d_penalty = max(
            0.0,
            span_progress * float(tip_3d_penalty_max) + tip_taper_penalty - washout_relief,
        )

    safe_clmax = max(
        float(safe_clmax_floor),
        safe_scale * float(raw_clmax) - safe_delta - tip_3d_penalty,
    )
    return SafeLocalClmax(
        raw_clmax=float(raw_clmax),
        raw_source=str(raw_source),
        safe_clmax=safe_clmax,
        source_scale=float(safe_scale),
        source_delta=float(safe_delta),
        span_fraction=span_fraction,
        tip_3d_penalty=float(tip_3d_penalty),
        tip_taper_penalty=float(tip_taper_penalty),
        washout_relief=float(washout_relief),
    )


def apply_safe_local_clmax_model(
    station_points: list[dict[str, float]],
    *,
    safe_scale: float,
    safe_delta: float,
    tip_3d_penalty_start_eta: float,
    tip_3d_penalty_max: float,
    tip_taper_penalty_weight: float,
    washout_relief_deg: float,
    washout_relief_max: float,
    safe_clmax_floor: float = 0.10,
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    safe_points: list[dict[str, float]] = []
    raw_values: list[float] = []
    safe_values: list[float] = []
    tip_penalties: list[float] = []

    for point in station_points:
        if "cl_max_effective" in point:
            raw_clmax = float(point["cl_max_effective"])
            raw_source = str(point.get("cl_max_effective_source", "geometry_proxy"))
        else:
            raw_clmax = float(point["cl_max_proxy"])
            raw_source = "geometry_proxy"
        result = compute_safe_local_clmax(
            raw_clmax=raw_clmax,
            raw_source=raw_source,
            span_fraction=float(point.get("span_fraction", 0.5)),
            taper_ratio=float(point.get("taper_ratio", 0.35)),
            washout_deg=float(point.get("washout_deg", 0.0)),
            safe_scale=float(safe_scale),
            safe_delta=float(safe_delta),
            tip_3d_penalty_start_eta=float(tip_3d_penalty_start_eta),
            tip_3d_penalty_max=float(tip_3d_penalty_max),
            tip_taper_penalty_weight=float(tip_taper_penalty_weight),
            washout_relief_deg=float(washout_relief_deg),
            washout_relief_max=float(washout_relief_max),
            safe_clmax_floor=float(safe_clmax_floor),
        )
        raw_values.append(result.raw_clmax)
        safe_values.append(result.safe_clmax)
        tip_penalties.append(result.tip_3d_penalty)
        safe_points.append(
            {
                **point,
                "cl_max_raw": result.raw_clmax,
                "cl_max_raw_source": result.raw_source,
                "cl_max_safe": result.safe_clmax,
                "cl_max_safe_source": safe_clmax_source_label(result.raw_source),
                "cl_max_safe_scale": result.source_scale,
                "cl_max_safe_delta": result.source_delta,
                "cl_max_safe_model": "safe_clmax_model_v2",
                "cl_max_safe_span_fraction": result.span_fraction,
                "cl_max_safe_tip_3d_penalty": result.tip_3d_penalty,
                "cl_max_safe_tip_taper_penalty": result.tip_taper_penalty,
                "cl_max_safe_washout_relief": result.washout_relief,
            }
        )

    summary = {
        "safe_clmax_applied": True,
        "safe_clmax_model": "safe_clmax_model_v2",
        "safe_clmax_scale": float(safe_scale),
        "safe_clmax_delta": float(safe_delta),
        "tip_3d_penalty_start_eta": float(tip_3d_penalty_start_eta),
        "tip_3d_penalty_max": float(tip_3d_penalty_max),
        "tip_taper_penalty_weight": float(tip_taper_penalty_weight),
        "washout_relief_deg": float(washout_relief_deg),
        "washout_relief_max": float(washout_relief_max),
        "min_cl_max_raw": min(raw_values) if raw_values else None,
        "min_cl_max_safe": min(safe_values) if safe_values else None,
        "max_tip_3d_penalty": max(tip_penalties) if tip_penalties else 0.0,
    }
    return safe_points, summary


__all__ = [
    "SafeLocalClmax",
    "apply_safe_local_clmax_model",
    "compute_safe_local_clmax",
    "safe_clmax_source_label",
]
