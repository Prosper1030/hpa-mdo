"""Mesh-study verdict helpers for origin SU2 comparison readiness."""

from __future__ import annotations

from typing import Any, Sequence

from hpa_mdo.aero.aero_sweep import AeroSweepPoint

CD_SPREAD_LIMIT = 0.002
CL_SPREAD_LIMIT = 0.03
CM_SPREAD_LIMIT = 0.03


def _spread(values: Sequence[float | None]) -> float | None:
    if any(value is None for value in values):
        return None
    numeric = [float(value) for value in values]
    if not numeric:
        return None
    return max(numeric) - min(numeric)


def _alpha_values(points: Sequence[AeroSweepPoint]) -> set[float]:
    return {float(point.alpha_deg) for point in points}


def _max_metric_spread(
    points_by_preset: dict[str, Sequence[AeroSweepPoint]],
    metric_name: str,
) -> tuple[float | None, list[float]]:
    common_alpha_deg: set[float] | None = None
    for points in points_by_preset.values():
        point_alphas = _alpha_values(points)
        common_alpha_deg = point_alphas if common_alpha_deg is None else common_alpha_deg & point_alphas

    if not common_alpha_deg:
        return None, []

    alpha_to_values: dict[float, list[float | None]] = {}
    for points in points_by_preset.values():
        for point in points:
            alpha_deg = float(point.alpha_deg)
            if alpha_deg not in common_alpha_deg:
                continue
            alpha_to_values.setdefault(alpha_deg, []).append(getattr(point, metric_name))

    compared_alpha_deg: list[float] = []
    max_spread: float | None = None
    for alpha_deg in sorted(common_alpha_deg):
        values = alpha_to_values[alpha_deg]
        spread = _spread(values)
        if spread is None:
            continue
        compared_alpha_deg.append(alpha_deg)
        max_spread = spread if max_spread is None else max(max_spread, spread)
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
    alpha_coverage_by_preset = {
        preset: sorted(_alpha_values(points))
        for preset, points in sorted(points_by_preset.items())
    }
    coverage_complete = len({tuple(values) for values in alpha_coverage_by_preset.values()}) == 1

    thresholds = {
        "cd_spread_abs_max": CD_SPREAD_LIMIT,
        "cl_spread_abs_max": CL_SPREAD_LIMIT,
        "cm_spread_abs_max": CM_SPREAD_LIMIT,
    }
    verdict = (
        "usable_for_comparison"
        if (
            len(points_by_preset) >= 2
            and
            bool(compared_alpha_deg)
            and coverage_complete
            and cd_spread_abs is not None
            and cl_spread_abs is not None
            and cm_spread_abs is not None
            and cd_spread_abs <= CD_SPREAD_LIMIT
            and cl_spread_abs <= CL_SPREAD_LIMIT
            and cm_spread_abs <= CM_SPREAD_LIMIT
        )
        else "still_baseline_only"
    )

    return {
        "verdict": verdict,
        "preset_count": len(points_by_preset),
        "compared_alpha_deg": compared_alpha_deg,
        "coverage_complete": coverage_complete,
        "cd_spread_abs": cd_spread_abs,
        "cl_spread_abs": cl_spread_abs,
        "cm_spread_abs": cm_spread_abs,
        "thresholds": thresholds,
        "alpha_coverage_by_preset": alpha_coverage_by_preset,
        "points_per_preset": {
            preset: len(points)
            for preset, points in sorted(points_by_preset.items())
        },
    }
