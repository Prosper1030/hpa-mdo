from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class LaunchGateResult:
    feasible: bool
    ground_effect_applied: bool
    adjusted_cl_required: float
    reason: str


@dataclass(frozen=True)
class TurnGateResult:
    feasible: bool
    required_cl: float
    stall_margin: float
    reason: str


def evaluate_launch_gate(
    platform_height_m: float,
    wing_span_m: float,
    speed_mps: float,
    cl_required: float,
    cl_available: float,
    trim_margin_deg: float,
    use_ground_effect: bool,
) -> LaunchGateResult:
    if platform_height_m <= 0.0:
        raise ValueError("platform_height_m must be positive.")
    if wing_span_m <= 0.0:
        raise ValueError("wing_span_m must be positive.")
    if speed_mps <= 0.0:
        raise ValueError("speed_mps must be positive.")
    if cl_required <= 0.0:
        raise ValueError("cl_required must be positive.")
    if cl_available <= 0.0:
        raise ValueError("cl_available must be positive.")

    ground_effect_applied = bool(use_ground_effect and platform_height_m > 0.0)
    ground_effect_strength = 0.0
    if ground_effect_applied:
        ground_effect_strength = _clamp(
            float(wing_span_m) / (float(wing_span_m) + 4.0 * float(platform_height_m)),
            0.0,
            1.0,
        )

    adjusted_cl_required = float(cl_required) * (1.0 - 0.12 * ground_effect_strength)
    adjusted_cl_required = max(0.0, adjusted_cl_required)

    if float(trim_margin_deg) < 1.0:
        return LaunchGateResult(
            feasible=False,
            ground_effect_applied=ground_effect_applied,
            adjusted_cl_required=adjusted_cl_required,
            reason="insufficient_trim_margin",
        )
    if adjusted_cl_required > float(cl_available):
        return LaunchGateResult(
            feasible=False,
            ground_effect_applied=ground_effect_applied,
            adjusted_cl_required=adjusted_cl_required,
            reason="cl_required_exceeds_available",
        )
    return LaunchGateResult(
        feasible=True,
        ground_effect_applied=ground_effect_applied,
        adjusted_cl_required=adjusted_cl_required,
        reason="ok",
    )


def evaluate_turn_gate(
    bank_angle_deg: float,
    speed_mps: float,
    cl_level: float,
    cl_max: float,
    trim_feasible: bool,
) -> TurnGateResult:
    if bank_angle_deg <= 0.0 or bank_angle_deg >= 85.0:
        raise ValueError("bank_angle_deg must be in the interval (0, 85).")
    if speed_mps <= 0.0:
        raise ValueError("speed_mps must be positive.")
    if cl_max <= 0.0:
        raise ValueError("cl_max must be positive.")

    load_factor = 1.0 / cos(radians(float(bank_angle_deg)))
    required_cl = float(cl_level) * load_factor
    stall_margin = float(cl_max) - required_cl

    if not trim_feasible:
        return TurnGateResult(
            feasible=False,
            required_cl=required_cl,
            stall_margin=stall_margin,
            reason="trim_infeasible",
        )
    if stall_margin < 0.08:
        return TurnGateResult(
            feasible=False,
            required_cl=required_cl,
            stall_margin=stall_margin,
            reason="insufficient_stall_margin",
        )
    return TurnGateResult(
        feasible=True,
        required_cl=required_cl,
        stall_margin=stall_margin,
        reason="ok",
    )


__all__ = [
    "LaunchGateResult",
    "TurnGateResult",
    "evaluate_launch_gate",
    "evaluate_turn_gate",
]
