from __future__ import annotations

from dataclasses import dataclass
import math


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
    *,
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
    adjusted_cl_required = float(cl_required)
    if ground_effect_applied:
        height_ratio = max(float(platform_height_m) / float(wing_span_m), 1.0e-3)
        drag_factor = max(0.82, 1.0 - 0.6 * math.exp(-8.0 * height_ratio))
        adjusted_cl_required *= drag_factor

    feasible = float(cl_available) >= adjusted_cl_required and float(trim_margin_deg) > 0.0
    if not feasible:
        return LaunchGateResult(
            feasible=False,
            ground_effect_applied=ground_effect_applied,
            adjusted_cl_required=adjusted_cl_required,
            reason="launch_cl_or_trim_insufficient",
        )
    return LaunchGateResult(
        feasible=True,
        ground_effect_applied=ground_effect_applied,
        adjusted_cl_required=adjusted_cl_required,
        reason="ok",
    )


def evaluate_turn_gate(
    *,
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

    load_factor = 1.0 / math.cos(math.radians(float(bank_angle_deg)))
    required_cl = float(cl_level) * load_factor
    stall_margin = float(cl_max) - required_cl

    feasible = bool(trim_feasible and stall_margin > 0.10)
    if not feasible:
        return TurnGateResult(
            feasible=False,
            required_cl=required_cl,
            stall_margin=stall_margin,
            reason="stall_margin_insufficient",
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
