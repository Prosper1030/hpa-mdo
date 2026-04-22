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
class TrimGateResult:
    feasible: bool
    margin_deg: float
    required_margin_deg: float
    reason: str


@dataclass(frozen=True)
class TurnGateResult:
    feasible: bool
    required_cl: float
    stall_margin: float
    reason: str


@dataclass(frozen=True)
class LocalStallResult:
    feasible: bool
    min_margin: float
    min_margin_station_y_m: float
    tip_critical: bool
    reason: str


def evaluate_launch_gate(
    *,
    platform_height_m: float,
    wing_span_m: float,
    speed_mps: float,
    cl_required: float,
    cl_available: float,
    trim_margin_deg: float,
    required_trim_margin_deg: float,
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
    if required_trim_margin_deg <= 0.0:
        raise ValueError("required_trim_margin_deg must be positive.")

    # The current launch gate works on CL terms that were already computed from a
    # chosen speed upstream. We keep speed_mps in the contract for later envelope
    # models even though Task 5 does not use it directly here.
    ground_effect_applied = bool(use_ground_effect and platform_height_m > 0.0)
    adjusted_cl_required = float(cl_required)
    if ground_effect_applied:
        height_ratio = max(float(platform_height_m) / float(wing_span_m), 1.0e-3)
        drag_factor = max(0.82, 1.0 - 0.6 * math.exp(-8.0 * height_ratio))
        adjusted_cl_required *= drag_factor

    if float(cl_available) < adjusted_cl_required:
        return LaunchGateResult(
            feasible=False,
            ground_effect_applied=ground_effect_applied,
            adjusted_cl_required=adjusted_cl_required,
            reason="launch_cl_insufficient",
        )
    if float(trim_margin_deg) < float(required_trim_margin_deg):
        return LaunchGateResult(
            feasible=False,
            ground_effect_applied=ground_effect_applied,
            adjusted_cl_required=adjusted_cl_required,
            reason="trim_margin_insufficient",
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
    required_stall_margin: float,
) -> TurnGateResult:
    if bank_angle_deg <= 0.0 or bank_angle_deg >= 85.0:
        raise ValueError("bank_angle_deg must be in the interval (0, 85).")
    if speed_mps <= 0.0:
        raise ValueError("speed_mps must be positive.")
    if cl_max <= 0.0:
        raise ValueError("cl_max must be positive.")

    # Like the launch gate, this MVP consumes an upstream CL state. The speed is
    # retained on the API surface so later turn-envelope refinements can use it
    # without changing the pipeline contract.
    load_factor = 1.0 / math.cos(math.radians(float(bank_angle_deg)))
    required_cl = float(cl_level) * load_factor
    stall_margin = float(cl_max) - required_cl

    if not trim_feasible:
        return TurnGateResult(
            feasible=False,
            required_cl=required_cl,
            stall_margin=stall_margin,
            reason="trim_not_feasible",
        )
    if stall_margin < float(required_stall_margin):
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


def evaluate_trim_proxy(
    *,
    representative_cm: float,
    required_margin_deg: float,
    cm_limit_abs: float = 0.15,
) -> TrimGateResult:
    if required_margin_deg <= 0.0:
        raise ValueError("required_margin_deg must be positive.")
    if cm_limit_abs <= 0.0:
        raise ValueError("cm_limit_abs must be positive.")

    margin_deg = max(
        0.0,
        6.0 * (float(cm_limit_abs) - abs(float(representative_cm))) / float(cm_limit_abs),
    )
    required_margin_deg = float(required_margin_deg)
    feasible = margin_deg > required_margin_deg or math.isclose(
        margin_deg,
        required_margin_deg,
        rel_tol=0.0,
        abs_tol=1.0e-9,
    )
    return TrimGateResult(
        feasible=feasible,
        margin_deg=margin_deg,
        required_margin_deg=required_margin_deg,
        reason="ok" if feasible else "trim_margin_insufficient",
    )


def evaluate_local_stall(
    *,
    station_points: list[dict[str, float]],
    half_span_m: float,
    required_stall_margin: float,
) -> LocalStallResult:
    if not station_points:
        raise ValueError("station_points must not be empty.")
    if half_span_m <= 0.0:
        raise ValueError("half_span_m must be positive.")
    if required_stall_margin <= 0.0:
        raise ValueError("required_stall_margin must be positive.")

    def _cl_limit(point: dict[str, float]) -> float:
        return float(point.get("cl_max_effective", point["cl_max_proxy"]))

    min_point = min(
        station_points,
        key=lambda item: _cl_limit(item) - float(item["cl_target"]),
    )
    min_margin = _cl_limit(min_point) - float(min_point["cl_target"])
    y_m = float(min_point["station_y_m"])
    tip_critical = y_m >= 0.75 * float(half_span_m)
    feasible = min_margin >= float(required_stall_margin)
    return LocalStallResult(
        feasible=feasible,
        min_margin=min_margin,
        min_margin_station_y_m=y_m,
        tip_critical=tip_critical,
        reason="ok" if feasible else "stall_margin_insufficient",
    )


__all__ = [
    "LaunchGateResult",
    "LocalStallResult",
    "TrimGateResult",
    "TurnGateResult",
    "evaluate_launch_gate",
    "evaluate_local_stall",
    "evaluate_trim_proxy",
    "evaluate_turn_gate",
]
