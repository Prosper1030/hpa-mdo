"""Mesh-study verdict helpers for origin SU2 comparison readiness."""

from __future__ import annotations

from typing import Any, Sequence

from hpa_mdo.aero.aero_sweep import AeroSweepPoint

CD_SPREAD_LIMIT = 0.002
CL_SPREAD_LIMIT = 0.03
CM_SPREAD_LIMIT = 0.03


def _spread(values: Sequence[float | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return max(numeric) - min(numeric)


def _max_metric_spread(
    points_by_preset: dict[str, Sequence[AeroSweepPoint]],
    metric_name: str,
) -> tuple[float, list[float]]:
    alpha_to_values: dict[float, list[float | None]] = {}
    for points in points_by_preset.values():
        for point in points:
            alpha_to_values.setdefault(float(point.alpha_deg), []).append(getattr(point, metric_name))

    compared_alpha_deg: list[float] = []
    max_spread = 0.0
    for alpha_deg in sorted(alpha_to_values):
        values = alpha_to_values[alpha_deg]
        spread = _spread(values)
        if spread is None:
            continue
        compared_alpha_deg.append(alpha_deg)
        max_spread = max(max_spread, spread)
    return max_spread, compared_alpha_deg


def assess_origin_mesh_study(
    *,
    points_by_preset: dict[str, Sequence[AeroSweepPoint]],
) -> dict[str, Any]:
    if not points_by_preset:
        raise ValueError("points_by_preset must not be empty")

    cd_spread_abs, compared_alpha_deg = _max_metric_spread(points_by_preset, "cd")
    cl_spread_abs, _ = _max_metric_spread(points_by_preset, "cl")
    cm_spread_abs, _ = _max_metric_spread(points_by_preset, "cm")

    thresholds = {
        "cd_spread_abs_max": CD_SPREAD_LIMIT,
        "cl_spread_abs_max": CL_SPREAD_LIMIT,
        "cm_spread_abs_max": CM_SPREAD_LIMIT,
    }
    verdict = (
        "usable_for_comparison"
        if (
            cd_spread_abs <= CD_SPREAD_LIMIT
            and cl_spread_abs <= CL_SPREAD_LIMIT
            and cm_spread_abs <= CM_SPREAD_LIMIT
        )
        else "still_baseline_only"
    )

    return {
        "verdict": verdict,
        "preset_count": len(points_by_preset),
        "compared_alpha_deg": compared_alpha_deg,
        "cd_spread_abs": cd_spread_abs,
        "cl_spread_abs": cl_spread_abs,
        "cm_spread_abs": cm_spread_abs,
        "thresholds": thresholds,
        "points_per_preset": {
            preset: len(points)
            for preset, points in sorted(points_by_preset.items())
        },
    }
