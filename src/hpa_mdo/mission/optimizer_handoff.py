"""Mission optimizer handoff helpers for stage-0 mission design-space scanning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .quick_screen import MissionQuickScreenInputs, RiderCurve, evaluate_quick_screen


# Constants shared with mission_gate usage.
_MIN_POWER_MARGIN_CRANK_W = 5.0
_MAX_CL_TO_CLMAX_RATIO = 0.90
_ALLOWED_CL_BANDS = ("normal",)
_ALLOWED_STALL_BANDS = ("healthy", "caution")


@dataclass(frozen=True)
class MissionGateInput:
    speed_mps: float
    span_m: float
    aspect_ratio: float
    mass_kg: float
    cd0_total: float
    cl_max_effective: float
    oswald_e: float
    air_density_kg_m3: float
    eta_prop: float
    eta_trans: float
    target_range_km: float
    rider_curve: RiderCurve
    thermal_derate_factor: float


def assign_optimizer_seed_tier(
    *,
    robust_fraction: float,
    power_passed_scenarios: int,
    p10_power_margin_crank_w: float | None,
    max_cl_to_clmax_ratio: float | None,
) -> str:
    """Return seed tier from optimizer pre-filter policy."""

    if power_passed_scenarios <= 0:
        return "reject"

    if (
        robust_fraction >= 0.50
        and p10_power_margin_crank_w is not None
        and p10_power_margin_crank_w >= 10.0
        and max_cl_to_clmax_ratio is not None
        and max_cl_to_clmax_ratio <= 0.85
    ):
        return "high_confidence"

    if (
        robust_fraction >= 0.25
        and p10_power_margin_crank_w is not None
        and p10_power_margin_crank_w >= 5.0
        and max_cl_to_clmax_ratio is not None
        and max_cl_to_clmax_ratio <= 0.90
    ):
        return "primary"

    return "boundary"


def assign_optimizer_exploration_tier(
    *,
    robust_scenarios: int,
    power_passed_scenarios: int,
    median_power_margin_crank_w: float | None,
    max_cl_to_clmax_ratio: float | None,
) -> str:
    """Return seed tier for optimizer exploration.

    This tier is intentionally separate from the conservative strict tier and is tuned for
    discovery-oriented seed sampling.
    """

    if power_passed_scenarios == 0:
        return "exploration_reject"

    if (
        robust_scenarios > 0
        and median_power_margin_crank_w is not None
        and median_power_margin_crank_w >= 5.0
        and max_cl_to_clmax_ratio is not None
        and max_cl_to_clmax_ratio <= 0.95
    ):
        return "exploration_primary"

    if (
        robust_scenarios > 0
        and median_power_margin_crank_w is not None
        and median_power_margin_crank_w >= 0.0
        and max_cl_to_clmax_ratio is not None
        and max_cl_to_clmax_ratio <= 1.00
    ):
        return "exploration_promising"

    return "exploration_boundary"


def evaluate_optimizer_mission_gate(input: MissionGateInput) -> dict[str, Any]:
    """Evaluate one seed candidate for optimizer pre-gate."""

    result = evaluate_quick_screen(
        MissionQuickScreenInputs(
            speed_mps=input.speed_mps,
            span_m=input.span_m,
            aspect_ratio=input.aspect_ratio,
            mass_kg=input.mass_kg,
            cd0_total=input.cd0_total,
            oswald_e=input.oswald_e,
            air_density_kg_m3=input.air_density_kg_m3,
            eta_prop=input.eta_prop,
            eta_trans=input.eta_trans,
            target_range_km=input.target_range_km,
            rider_curve=input.rider_curve,
            thermal_derate_factor=input.thermal_derate_factor,
            cl_max_effective=input.cl_max_effective,
        )
    )

    robust_passed = bool(
        result.power_passed
        and result.power_margin_crank_w is not None
        and result.power_margin_crank_w >= _MIN_POWER_MARGIN_CRANK_W
        and result.cl_band in _ALLOWED_CL_BANDS
        and result.stall_band in _ALLOWED_STALL_BANDS
        and result.cl_to_clmax_ratio <= _MAX_CL_TO_CLMAX_RATIO
    )

    power_passed = bool(result.power_passed)
    power_margin_crank_w = result.power_margin_crank_w
    cl_required = result.cl_required
    cl_to_clmax_ratio = result.cl_to_clmax_ratio
    stall_band = result.stall_band
    cl_band = result.cl_band
    required_time_min = result.required_time_min

    penalty = 0.0
    if power_margin_crank_w is not None and power_margin_crank_w < 0:
        penalty += abs(power_margin_crank_w) * 100.0

    if cl_to_clmax_ratio > _MAX_CL_TO_CLMAX_RATIO:
        penalty += (cl_to_clmax_ratio - _MAX_CL_TO_CLMAX_RATIO) * 1000.0

    if stall_band == "over_clmax":
        penalty += 10000.0
    elif stall_band == "thin_margin":
        penalty += 1000.0

    if cl_band == "too_high":
        penalty += 5000.0

    if robust_passed:
        penalty = 0.0

    return {
        "power_passed": power_passed,
        "robust_passed": robust_passed,
        "power_margin_crank_w": power_margin_crank_w,
        "cl_required": cl_required,
        "cl_to_clmax_ratio": cl_to_clmax_ratio,
        "stall_band": stall_band,
        "cl_band": cl_band,
        "required_time_min": required_time_min,
        "penalty": penalty,
    }
