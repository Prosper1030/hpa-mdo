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
    wing_cl: float = 0.0
    wing_cm_airfoil: float = 0.0
    wing_cm_total: float = 0.0
    tail_cl_required: float = 0.0
    tail_cl_limit_abs: float = 0.0
    tail_utilization: float = 0.0
    tail_volume_coefficient: float = 0.0


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
    raw_clmax: float = 0.0
    safe_clmax: float = 0.0
    raw_clmax_ratio: float = 0.0
    safe_clmax_ratio: float = 0.0
    raw_clmax_status: str = "not_evaluated"
    safe_clmax_status: str = "not_evaluated"
    raw_stall_speed_margin_ratio: float = float("inf")
    safe_stall_speed_margin_ratio: float = float("inf")
    tip_excluded_safe_clmax_ratio: float = 0.0
    outboard_region_safe_clmax_ratio: float = 0.0
    contiguous_overlimit_span_fraction: float = 0.0
    tip_exclusion_eta: float = 0.97
    outboard_region_eta_min: float = 0.70
    outboard_region_eta_max: float = 0.95


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
    raw_clmax: float
    safe_clmax: float
    raw_clmax_ratio: float
    safe_clmax_ratio: float
    raw_clmax_status: str
    safe_clmax_status: str
    raw_stall_speed_margin_ratio: float
    safe_stall_speed_margin_ratio: float
    tip_excluded_safe_clmax_ratio: float = 0.0
    outboard_region_safe_clmax_ratio: float = 0.0
    contiguous_overlimit_span_fraction: float = 0.0
    tip_exclusion_eta: float = 0.97
    outboard_region_eta_min: float = 0.70
    outboard_region_eta_max: float = 0.95


def _cl_limit(point: dict[str, float]) -> float:
    if "cl_max_safe" in point:
        return float(point["cl_max_safe"])
    return float(point.get("cl_max_effective", point["cl_max_proxy"]))


def _cl_raw_limit(point: dict[str, float]) -> float:
    if "cl_max_raw" in point:
        return float(point["cl_max_raw"])
    if "cl_max_effective" in point:
        return float(point["cl_max_effective"])
    if "cl_max_proxy" in point:
        return float(point["cl_max_proxy"])
    return float(point["cl_max_safe"])


def _weighted_required_cl(point: dict[str, float], *, load_factor: float) -> float:
    return float(point["cl_target"]) * float(load_factor)


def _resolved_required_cl(
    point: dict[str, float],
    *,
    load_factor: float,
    pre_scaled_cl: bool,
) -> float:
    if pre_scaled_cl:
        return float(point["cl_target"])
    return _weighted_required_cl(point, load_factor=load_factor)


def _cl_limit_source(point: dict[str, float]) -> str:
    if "cl_max_safe_source" in point:
        return str(point["cl_max_safe_source"])
    if "cl_max_safe" in point:
        return "geometry_safe_proxy"
    return str(point.get("cl_max_effective_source", "geometry_proxy"))


def _cl_raw_limit_source(point: dict[str, float]) -> str:
    if "cl_max_raw_source" in point:
        return str(point["cl_max_raw_source"])
    if "cl_max_effective_source" in point:
        return str(point["cl_max_effective_source"])
    if "cl_max_proxy" in point:
        return "geometry_proxy"
    return "raw_unavailable_uses_safe_clmax"


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator) / max(float(denominator), 1.0e-9)


def _stall_speed_margin_ratio(clmax_ratio: float) -> float:
    if clmax_ratio <= 0.0:
        return float("inf")
    return 1.0 / math.sqrt(float(clmax_ratio))


def _raw_clmax_status(raw_clmax_ratio: float) -> str:
    ratio = float(raw_clmax_ratio)
    if ratio > 1.0:
        return "beyond_raw_clmax"
    if ratio >= 0.95:
        return "near_raw_red"
    if ratio >= 0.90:
        return "near_raw_amber"
    if ratio >= 0.85:
        return "raw_caution"
    return "normal"


def _safe_clmax_status(safe_clmax_ratio: float, *, case_limit: float) -> str:
    ratio = float(safe_clmax_ratio)
    if ratio > 1.0:
        return "beyond_safe_clmax"
    if ratio > float(case_limit):
        return "exceeds_case_limit"
    if ratio <= 0.70:
        return "target"
    return "case_limit_pass"


_DEFAULT_TIP_EXCLUSION_ETA = 0.97
_DEFAULT_OUTBOARD_REGION_ETA_MIN = 0.70
_DEFAULT_OUTBOARD_REGION_ETA_MAX = 0.95


def _spanwise_indicators(
    *,
    station_points: list[dict[str, float]],
    half_span_m: float,
    load_factor: float,
    pre_scaled_cl: bool,
    warning_threshold: float,
    tip_exclusion_eta: float = _DEFAULT_TIP_EXCLUSION_ETA,
    outboard_region_eta_min: float = _DEFAULT_OUTBOARD_REGION_ETA_MIN,
    outboard_region_eta_max: float = _DEFAULT_OUTBOARD_REGION_ETA_MAX,
) -> dict[str, float]:
    if outboard_region_eta_max <= outboard_region_eta_min:
        raise ValueError("outboard_region_eta_max must be > outboard_region_eta_min.")
    if tip_exclusion_eta <= 0.0 or tip_exclusion_eta > 1.0:
        raise ValueError("tip_exclusion_eta must be in the interval (0, 1].")

    sorted_points = sorted(station_points, key=lambda item: float(item.get("station_y_m", 0.0)))
    safe_span_entries: list[tuple[float, float]] = []
    for point in sorted_points:
        y_abs = abs(float(point.get("station_y_m", 0.0)))
        eta = min(1.0, y_abs / max(float(half_span_m), 1.0e-9))
        required_cl = _resolved_required_cl(
            point,
            load_factor=load_factor,
            pre_scaled_cl=pre_scaled_cl,
        )
        safe_ratio = _ratio(required_cl, _cl_limit(point))
        safe_span_entries.append((eta, safe_ratio))

    if not safe_span_entries:
        return {
            "tip_excluded_safe_clmax_ratio": 0.0,
            "outboard_region_safe_clmax_ratio": 0.0,
            "contiguous_overlimit_span_fraction": 0.0,
        }

    tip_excluded_ratios = [ratio for eta, ratio in safe_span_entries if eta <= tip_exclusion_eta]
    outboard_ratios = [
        ratio
        for eta, ratio in safe_span_entries
        if outboard_region_eta_min <= eta <= outboard_region_eta_max
    ]
    tip_excluded_max = max(tip_excluded_ratios) if tip_excluded_ratios else 0.0
    outboard_max = max(outboard_ratios) if outboard_ratios else 0.0

    contiguous_fraction = 0.0
    current_start: float | None = None
    previous_eta: float | None = None
    segments: list[tuple[float, float]] = []
    for eta, ratio in safe_span_entries:
        if ratio > float(warning_threshold):
            if current_start is None:
                current_start = eta
            previous_eta = eta
        else:
            if current_start is not None and previous_eta is not None:
                segments.append((current_start, previous_eta))
            current_start = None
            previous_eta = None
    if current_start is not None and previous_eta is not None:
        segments.append((current_start, previous_eta))
    if segments:
        contiguous_fraction = max(end - start for start, end in segments)

    return {
        "tip_excluded_safe_clmax_ratio": float(tip_excluded_max),
        "outboard_region_safe_clmax_ratio": float(outboard_max),
        "contiguous_overlimit_span_fraction": float(contiguous_fraction),
    }


def _evaluate_stationwise_margin(
    *,
    station_points: list[dict[str, float]],
    half_span_m: float,
    load_factor: float,
    pre_scaled_cl: bool = False,
    warning_threshold: float | None = None,
    tip_exclusion_eta: float = _DEFAULT_TIP_EXCLUSION_ETA,
    outboard_region_eta_min: float = _DEFAULT_OUTBOARD_REGION_ETA_MIN,
    outboard_region_eta_max: float = _DEFAULT_OUTBOARD_REGION_ETA_MAX,
) -> dict[str, float | bool | str]:
    if not station_points:
        raise ValueError("station_points must not be empty.")
    if half_span_m <= 0.0:
        raise ValueError("half_span_m must be positive.")
    if load_factor <= 0.0:
        raise ValueError("load_factor must be positive.")

    limiting_point = max(
        station_points,
        key=lambda item: _ratio(
            _resolved_required_cl(
                item,
                load_factor=load_factor,
                pre_scaled_cl=pre_scaled_cl,
            ),
            _cl_limit(item),
        ),
    )
    raw_limiting_point = max(
        station_points,
        key=lambda item: _ratio(
            _resolved_required_cl(
                item,
                load_factor=load_factor,
                pre_scaled_cl=pre_scaled_cl,
            ),
            _cl_raw_limit(item),
        ),
    )
    cl_level = float(limiting_point["cl_target"])
    cl_max = _cl_limit(limiting_point)
    required_cl = _resolved_required_cl(
        limiting_point,
        load_factor=load_factor,
        pre_scaled_cl=pre_scaled_cl,
    )
    raw_required_cl = _resolved_required_cl(
        raw_limiting_point,
        load_factor=load_factor,
        pre_scaled_cl=pre_scaled_cl,
    )
    min_margin = cl_max - required_cl
    stall_utilization = _ratio(required_cl, cl_max)
    raw_clmax = _cl_raw_limit(raw_limiting_point)
    raw_clmax_ratio = _ratio(raw_required_cl, raw_clmax)
    y_m = float(limiting_point["station_y_m"])
    raw_y_m = float(raw_limiting_point.get("station_y_m", y_m))
    warning_threshold_value = (
        float(stall_utilization) if warning_threshold is None else float(warning_threshold)
    )
    spanwise = _spanwise_indicators(
        station_points=station_points,
        half_span_m=half_span_m,
        load_factor=load_factor,
        pre_scaled_cl=pre_scaled_cl,
        warning_threshold=warning_threshold_value,
        tip_exclusion_eta=tip_exclusion_eta,
        outboard_region_eta_min=outboard_region_eta_min,
        outboard_region_eta_max=outboard_region_eta_max,
    )
    return {
        "cl_level": cl_level,
        "cl_max": cl_max,
        "required_cl": required_cl,
        "min_margin": min_margin,
        "stall_utilization": stall_utilization,
        "min_margin_station_y_m": y_m,
        "tip_critical": y_m >= 0.75 * float(half_span_m),
        "cl_max_source": _cl_limit_source(limiting_point),
        "raw_clmax": raw_clmax,
        "raw_clmax_source": _cl_raw_limit_source(raw_limiting_point),
        "raw_clmax_ratio": raw_clmax_ratio,
        "raw_ratio_station_y_m": raw_y_m,
        "raw_clmax_status": _raw_clmax_status(raw_clmax_ratio),
        "raw_stall_speed_margin_ratio": _stall_speed_margin_ratio(raw_clmax_ratio),
        "safe_clmax": cl_max,
        "safe_clmax_ratio": stall_utilization,
        "safe_stall_speed_margin_ratio": _stall_speed_margin_ratio(stall_utilization),
        "warning_threshold": warning_threshold_value,
        "tip_exclusion_eta": float(tip_exclusion_eta),
        "outboard_region_eta_min": float(outboard_region_eta_min),
        "outboard_region_eta_max": float(outboard_region_eta_max),
        **spanwise,
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
    load_factor_override: float | None = None,
    pre_scaled_cl: bool = False,
) -> TurnGateResult:
    if bank_angle_deg <= 0.0 or bank_angle_deg >= 85.0:
        raise ValueError("bank_angle_deg must be in the interval (0, 85).")
    if speed_mps <= 0.0:
        raise ValueError("speed_mps must be positive.")
    # Like the launch gate, this MVP consumes an upstream CL state. The speed is
    # retained on the API surface so later turn-envelope refinements can use it
    # without changing the pipeline contract.
    load_factor = (
        float(load_factor_override)
        if load_factor_override is not None
        else 1.0 / math.cos(math.radians(float(bank_angle_deg)))
    )
    stationwise = _evaluate_stationwise_margin(
        station_points=station_points,
        half_span_m=half_span_m,
        load_factor=load_factor,
        pre_scaled_cl=pre_scaled_cl,
        warning_threshold=float(stall_utilization_limit),
    )
    cl_level = float(stationwise["cl_level"])
    cl_max = float(stationwise["cl_max"])
    required_cl = float(stationwise["required_cl"])
    stall_margin = float(stationwise["min_margin"])
    stall_utilization = float(stationwise["stall_utilization"])
    limiting_station_y_m = float(stationwise["min_margin_station_y_m"])
    tip_critical = bool(stationwise["tip_critical"])
    cl_max_source = str(stationwise["cl_max_source"])
    raw_clmax_status = str(stationwise["raw_clmax_status"])
    safe_clmax_status = _safe_clmax_status(
        stall_utilization,
        case_limit=float(stall_utilization_limit),
    )
    ratio_fields = {
        "raw_clmax": float(stationwise["raw_clmax"]),
        "safe_clmax": float(stationwise["safe_clmax"]),
        "raw_clmax_ratio": float(stationwise["raw_clmax_ratio"]),
        "safe_clmax_ratio": float(stationwise["safe_clmax_ratio"]),
        "raw_clmax_status": raw_clmax_status,
        "safe_clmax_status": safe_clmax_status,
        "raw_stall_speed_margin_ratio": float(stationwise["raw_stall_speed_margin_ratio"]),
        "safe_stall_speed_margin_ratio": float(stationwise["safe_stall_speed_margin_ratio"]),
        "tip_excluded_safe_clmax_ratio": float(stationwise["tip_excluded_safe_clmax_ratio"]),
        "outboard_region_safe_clmax_ratio": float(
            stationwise["outboard_region_safe_clmax_ratio"]
        ),
        "contiguous_overlimit_span_fraction": float(
            stationwise["contiguous_overlimit_span_fraction"]
        ),
        "tip_exclusion_eta": float(stationwise["tip_exclusion_eta"]),
        "outboard_region_eta_min": float(stationwise["outboard_region_eta_min"]),
        "outboard_region_eta_max": float(stationwise["outboard_region_eta_max"]),
    }

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
            **ratio_fields,
        )
    if raw_clmax_status == "beyond_raw_clmax":
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
            reason="beyond_raw_clmax",
            **ratio_fields,
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
            **ratio_fields,
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
        **ratio_fields,
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


def evaluate_trim_balance(
    *,
    wing_cl: float,
    wing_cm_airfoil: float,
    cg_xc: float,
    wing_ac_xc: float,
    tail_area_ratio: float,
    tail_arm_to_mac: float,
    tail_dynamic_pressure_ratio: float,
    tail_efficiency: float,
    tail_cl_limit_abs: float,
    required_margin_deg: float,
    body_cm_offset: float = 0.0,
    cm_spread: float = 0.0,
    spread_factor: float = 0.5,
) -> TrimGateResult:
    if required_margin_deg <= 0.0:
        raise ValueError("required_margin_deg must be positive.")
    if tail_area_ratio <= 0.0:
        raise ValueError("tail_area_ratio must be positive.")
    if tail_arm_to_mac <= 0.0:
        raise ValueError("tail_arm_to_mac must be positive.")
    if tail_dynamic_pressure_ratio <= 0.0:
        raise ValueError("tail_dynamic_pressure_ratio must be positive.")
    if tail_efficiency <= 0.0:
        raise ValueError("tail_efficiency must be positive.")
    if tail_cl_limit_abs <= 0.0:
        raise ValueError("tail_cl_limit_abs must be positive.")
    if cm_spread < 0.0:
        raise ValueError("cm_spread must not be negative.")
    if spread_factor < 0.0:
        raise ValueError("spread_factor must not be negative.")

    wing_cm_total = (
        float(wing_cm_airfoil)
        + float(wing_cl) * (float(wing_ac_xc) - float(cg_xc))
        + float(body_cm_offset)
    )
    tail_volume_coefficient = (
        float(tail_area_ratio)
        * float(tail_arm_to_mac)
        * float(tail_dynamic_pressure_ratio)
        * float(tail_efficiency)
    )
    tail_cl_required = -wing_cm_total / max(tail_volume_coefficient, 1.0e-9)
    spread_tail_cl = float(spread_factor) * float(cm_spread) / max(tail_volume_coefficient, 1.0e-9)
    effective_tail_cl_required = abs(float(tail_cl_required)) + abs(spread_tail_cl)
    tail_utilization = effective_tail_cl_required / max(float(tail_cl_limit_abs), 1.0e-9)
    margin_deg = max(
        0.0,
        6.0 * (float(tail_cl_limit_abs) - effective_tail_cl_required) / float(tail_cl_limit_abs),
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
        wing_cl=float(wing_cl),
        wing_cm_airfoil=float(wing_cm_airfoil),
        wing_cm_total=float(wing_cm_total),
        tail_cl_required=float(tail_cl_required),
        tail_cl_limit_abs=float(tail_cl_limit_abs),
        tail_utilization=float(tail_utilization),
        tail_volume_coefficient=float(tail_volume_coefficient),
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
        warning_threshold=float(stall_utilization_limit),
    )
    min_margin = float(stationwise["min_margin"])
    stall_utilization = float(stationwise["stall_utilization"])
    y_m = float(stationwise["min_margin_station_y_m"])
    tip_critical = bool(stationwise["tip_critical"])
    raw_clmax_status = str(stationwise["raw_clmax_status"])
    safe_clmax_status = _safe_clmax_status(
        stall_utilization,
        case_limit=float(stall_utilization_limit),
    )
    feasible = (
        raw_clmax_status != "beyond_raw_clmax"
        and stall_utilization <= float(stall_utilization_limit)
    )
    reason = "ok"
    if raw_clmax_status == "beyond_raw_clmax":
        reason = "beyond_raw_clmax"
    elif not feasible:
        reason = "stall_utilization_exceeded"
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
        reason=reason,
        raw_clmax=float(stationwise["raw_clmax"]),
        safe_clmax=float(stationwise["safe_clmax"]),
        raw_clmax_ratio=float(stationwise["raw_clmax_ratio"]),
        safe_clmax_ratio=float(stationwise["safe_clmax_ratio"]),
        raw_clmax_status=raw_clmax_status,
        safe_clmax_status=safe_clmax_status,
        raw_stall_speed_margin_ratio=float(stationwise["raw_stall_speed_margin_ratio"]),
        safe_stall_speed_margin_ratio=float(stationwise["safe_stall_speed_margin_ratio"]),
        tip_excluded_safe_clmax_ratio=float(stationwise["tip_excluded_safe_clmax_ratio"]),
        outboard_region_safe_clmax_ratio=float(
            stationwise["outboard_region_safe_clmax_ratio"]
        ),
        contiguous_overlimit_span_fraction=float(
            stationwise["contiguous_overlimit_span_fraction"]
        ),
        tip_exclusion_eta=float(stationwise["tip_exclusion_eta"]),
        outboard_region_eta_min=float(stationwise["outboard_region_eta_min"]),
        outboard_region_eta_max=float(stationwise["outboard_region_eta_max"]),
    )


__all__ = [
    "LaunchGateResult",
    "LocalStallResult",
    "TrimGateResult",
    "TurnGateResult",
    "evaluate_launch_gate",
    "evaluate_local_stall",
    "evaluate_trim_balance",
    "evaluate_trim_proxy",
    "evaluate_turn_gate",
]
