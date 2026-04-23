from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LaunchGateResult:
    feasible: bool
    ground_effect_applied: bool
    adjusted_cl_required: float
    stall_utilization: float
    stall_utilization_limit: float
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
    cl_level: float
    cl_max: float
    required_cl: float
    stall_margin: float
    stall_utilization: float
    stall_utilization_limit: float
    load_factor: float
    limiting_station_y_m: float
    tip_critical: bool
    cl_max_source: str
    reason: str


@dataclass(frozen=True)
class LocalStallResult:
    feasible: bool
    required_cl: float
    cl_max: float
    min_margin: float
    stall_utilization: float
    stall_utilization_limit: float
    min_margin_station_y_m: float
    tip_critical: bool
    cl_max_source: str
    reason: str


def _cl_limit(point: dict[str, float]) -> float:
    if "cl_max_safe" in point:
        return float(point["cl_max_safe"])
    return float(point.get("cl_max_effective", point["cl_max_proxy"]))


def _weighted_required_cl(point: dict[str, float], *, load_factor: float) -> float:
    return float(point["cl_target"]) * float(load_factor)


def _cl_limit_source(point: dict[str, float]) -> str:
    if "cl_max_safe_source" in point:
        return str(point["cl_max_safe_source"])
    if "cl_max_safe" in point:
        return "geometry_safe_proxy"
    return str(point.get("cl_max_effective_source", "geometry_proxy"))


def _evaluate_stationwise_margin(
    *,
    station_points: list[dict[str, float]],
    half_span_m: float,
    load_factor: float,
) -> dict[str, float | bool | str]:
    if not station_points:
        raise ValueError("station_points must not be empty.")
    if half_span_m <= 0.0:
        raise ValueError("half_span_m must be positive.")
    if load_factor <= 0.0:
        raise ValueError("load_factor must be positive.")

    min_point = min(
        station_points,
        key=lambda item: _cl_limit(item) - _weighted_required_cl(item, load_factor=load_factor),
    )
    cl_level = float(min_point["cl_target"])
    cl_max = _cl_limit(min_point)
    required_cl = _weighted_required_cl(min_point, load_factor=load_factor)
    min_margin = cl_max - required_cl
    stall_utilization = required_cl / max(cl_max, 1.0e-9)
    y_m = float(min_point["station_y_m"])
    return {
        "cl_level": cl_level,
        "cl_max": cl_max,
        "required_cl": required_cl,
        "min_margin": min_margin,
        "stall_utilization": stall_utilization,
        "min_margin_station_y_m": y_m,
        "tip_critical": y_m >= 0.75 * float(half_span_m),
        "cl_max_source": _cl_limit_source(min_point),
    }


def evaluate_launch_gate(
    *,
    platform_height_m: float,
    wing_span_m: float,
    speed_mps: float,
    cl_required: float,
    cl_available: float,
    trim_margin_deg: float,
    required_trim_margin_deg: float,
    stall_utilization_limit: float,
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
    if stall_utilization_limit <= 0.0 or stall_utilization_limit >= 1.0:
        raise ValueError("stall_utilization_limit must be in the interval (0, 1).")

    # The current launch gate works on CL terms that were already computed from a
    # chosen speed upstream. We keep speed_mps in the contract for later envelope
    # models even though Task 5 does not use it directly here.
    ground_effect_applied = bool(use_ground_effect and platform_height_m > 0.0)
    adjusted_cl_required = float(cl_required)
    if ground_effect_applied:
        height_ratio = max(float(platform_height_m) / float(wing_span_m), 1.0e-3)
        drag_factor = max(0.82, 1.0 - 0.6 * math.exp(-8.0 * height_ratio))
        adjusted_cl_required *= drag_factor
    stall_utilization = adjusted_cl_required / max(float(cl_available), 1.0e-9)

    if float(cl_available) < adjusted_cl_required:
        return LaunchGateResult(
            feasible=False,
            ground_effect_applied=ground_effect_applied,
            adjusted_cl_required=adjusted_cl_required,
            stall_utilization=stall_utilization,
            stall_utilization_limit=float(stall_utilization_limit),
            reason="launch_cl_insufficient",
        )
    if stall_utilization > float(stall_utilization_limit):
        return LaunchGateResult(
            feasible=False,
            ground_effect_applied=ground_effect_applied,
            adjusted_cl_required=adjusted_cl_required,
            stall_utilization=stall_utilization,
            stall_utilization_limit=float(stall_utilization_limit),
            reason="launch_stall_utilization_exceeded",
        )
    if float(trim_margin_deg) < float(required_trim_margin_deg):
        return LaunchGateResult(
            feasible=False,
            ground_effect_applied=ground_effect_applied,
            adjusted_cl_required=adjusted_cl_required,
            stall_utilization=stall_utilization,
            stall_utilization_limit=float(stall_utilization_limit),
            reason="trim_margin_insufficient",
        )
    return LaunchGateResult(
        feasible=True,
        ground_effect_applied=ground_effect_applied,
        adjusted_cl_required=adjusted_cl_required,
        stall_utilization=stall_utilization,
        stall_utilization_limit=float(stall_utilization_limit),
        reason="ok",
    )


def evaluate_turn_gate(
    *,
    bank_angle_deg: float,
    speed_mps: float,
    station_points: list[dict[str, float]],
    half_span_m: float,
    trim_feasible: bool,
    stall_utilization_limit: float,
) -> TurnGateResult:
    if bank_angle_deg <= 0.0 or bank_angle_deg >= 85.0:
        raise ValueError("bank_angle_deg must be in the interval (0, 85).")
    if speed_mps <= 0.0:
        raise ValueError("speed_mps must be positive.")
    # Like the launch gate, this MVP consumes an upstream CL state. The speed is
    # retained on the API surface so later turn-envelope refinements can use it
    # without changing the pipeline contract.
    load_factor = 1.0 / math.cos(math.radians(float(bank_angle_deg)))
    stationwise = _evaluate_stationwise_margin(
        station_points=station_points,
        half_span_m=half_span_m,
        load_factor=load_factor,
    )
    cl_level = float(stationwise["cl_level"])
    cl_max = float(stationwise["cl_max"])
    required_cl = float(stationwise["required_cl"])
    stall_margin = float(stationwise["min_margin"])
    stall_utilization = float(stationwise["stall_utilization"])
    limiting_station_y_m = float(stationwise["min_margin_station_y_m"])
    tip_critical = bool(stationwise["tip_critical"])
    cl_max_source = str(stationwise["cl_max_source"])

    if not trim_feasible:
        return TurnGateResult(
            feasible=False,
            cl_level=cl_level,
            cl_max=cl_max,
            required_cl=required_cl,
            stall_margin=stall_margin,
            stall_utilization=stall_utilization,
            stall_utilization_limit=float(stall_utilization_limit),
            load_factor=load_factor,
            limiting_station_y_m=limiting_station_y_m,
            tip_critical=tip_critical,
            cl_max_source=cl_max_source,
            reason="trim_not_feasible",
        )
    if stall_utilization > float(stall_utilization_limit):
        return TurnGateResult(
            feasible=False,
            cl_level=cl_level,
            cl_max=cl_max,
            required_cl=required_cl,
            stall_margin=stall_margin,
            stall_utilization=stall_utilization,
            stall_utilization_limit=float(stall_utilization_limit),
            load_factor=load_factor,
            limiting_station_y_m=limiting_station_y_m,
            tip_critical=tip_critical,
            cl_max_source=cl_max_source,
            reason="stall_utilization_exceeded",
        )
    return TurnGateResult(
        feasible=True,
        cl_level=cl_level,
        cl_max=cl_max,
        required_cl=required_cl,
        stall_margin=stall_margin,
        stall_utilization=stall_utilization,
        stall_utilization_limit=float(stall_utilization_limit),
        load_factor=load_factor,
        limiting_station_y_m=limiting_station_y_m,
        tip_critical=tip_critical,
        cl_max_source=cl_max_source,
        reason="ok",
    )


def evaluate_trim_proxy(
    *,
    representative_cm: float,
    required_margin_deg: float,
    cm_limit_abs: float = 0.15,
    cm_spread: float = 0.0,
    spread_factor: float = 0.5,
) -> TrimGateResult:
    if required_margin_deg <= 0.0:
        raise ValueError("required_margin_deg must be positive.")
    if cm_limit_abs <= 0.0:
        raise ValueError("cm_limit_abs must be positive.")
    if cm_spread < 0.0:
        raise ValueError("cm_spread must not be negative.")
    if spread_factor < 0.0:
        raise ValueError("spread_factor must not be negative.")

    effective_abs_cm = abs(float(representative_cm)) + float(spread_factor) * float(cm_spread)
    margin_deg = max(
        0.0,
        6.0 * (float(cm_limit_abs) - effective_abs_cm) / float(cm_limit_abs),
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
    stall_utilization_limit: float,
) -> LocalStallResult:
    if not station_points:
        raise ValueError("station_points must not be empty.")
    if half_span_m <= 0.0:
        raise ValueError("half_span_m must be positive.")
    if stall_utilization_limit <= 0.0 or stall_utilization_limit >= 1.0:
        raise ValueError("stall_utilization_limit must be in the interval (0, 1).")

    stationwise = _evaluate_stationwise_margin(
        station_points=station_points,
        half_span_m=half_span_m,
        load_factor=1.0,
    )
    min_margin = float(stationwise["min_margin"])
    stall_utilization = float(stationwise["stall_utilization"])
    y_m = float(stationwise["min_margin_station_y_m"])
    tip_critical = bool(stationwise["tip_critical"])
    feasible = stall_utilization <= float(stall_utilization_limit)
    return LocalStallResult(
        feasible=feasible,
        required_cl=float(stationwise["required_cl"]),
        cl_max=float(stationwise["cl_max"]),
        min_margin=min_margin,
        stall_utilization=stall_utilization,
        stall_utilization_limit=float(stall_utilization_limit),
        min_margin_station_y_m=y_m,
        tip_critical=tip_critical,
        cl_max_source=str(stationwise["cl_max_source"]),
        reason="ok" if feasible else "stall_utilization_exceeded",
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
