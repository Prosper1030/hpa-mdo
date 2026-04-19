"""Mission objective evaluation utilities."""

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class FakeAnchorCurve:
    anchor_power_w: float
    anchor_duration_min: float
    exponent: float = 0.15
    min_power_w: float = 180.0
    max_power_w: float = 450.0

    def __post_init__(self) -> None:
        _require_finite_positive(self.anchor_power_w, "anchor_power_w")
        _require_finite_positive(self.anchor_duration_min, "anchor_duration_min")
        _require_finite_positive(self.exponent, "exponent")
        _require_finite_positive(self.min_power_w, "min_power_w")
        _require_finite_positive(self.max_power_w, "max_power_w")
        if self.max_power_w <= self.min_power_w:
            raise ValueError("max_power_w must be greater than min_power_w")
        if not (self.min_power_w <= self.anchor_power_w <= self.max_power_w):
            raise ValueError("anchor_power_w must lie within min_power_w and max_power_w")

    def power_at_duration_min(self, duration_min: float) -> float:
        if duration_min <= 0:
            raise ValueError("duration_min must be positive")
        ratio = self.anchor_duration_min / duration_min
        power_w = self.anchor_power_w * ratio ** self.exponent
        return self._clamp_power(power_w)

    def duration_at_power_w(self, power_w: float) -> float:
        if power_w <= 0:
            raise ValueError("power_w must be positive")
        clamped_power_w = self._clamp_power(power_w)
        ratio = self.anchor_power_w / clamped_power_w
        return self.anchor_duration_min * ratio ** (1.0 / self.exponent)

    def _clamp_power(self, power_w: float) -> float:
        return max(self.min_power_w, min(self.max_power_w, power_w))


@dataclass(frozen=True)
class MissionEvaluationInputs:
    objective_mode: str
    target_range_km: float
    speed_mps: Sequence[float]
    power_required_w: Sequence[float]
    rider_curve: FakeAnchorCurve


@dataclass(frozen=True)
class MissionEvaluationResult:
    mission_objective_mode: str
    mission_feasible: bool
    target_range_km: float
    target_range_passed: bool
    target_range_margin_m: float
    best_range_m: float
    best_range_speed_mps: float
    best_endurance_s: float
    min_power_w: float
    min_power_speed_mps: float
    mission_score: float
    mission_score_reason: str
    pilot_power_model: str
    pilot_power_anchor: str
    speed_sweep_window_mps: tuple[float, float]


def evaluate_mission_objective(
    inputs: MissionEvaluationInputs,
) -> MissionEvaluationResult:
    _validate_inputs(inputs)

    ranges_m = []
    endurance_s = []
    for speed_mps, power_required_w in zip(inputs.speed_mps, inputs.power_required_w):
        duration_min = inputs.rider_curve.duration_at_power_w(power_required_w)
        duration_s = duration_min * 60.0
        endurance_s.append(duration_s)
        ranges_m.append(speed_mps * duration_s)

    best_index = max(range(len(ranges_m)), key=ranges_m.__getitem__)
    min_power_index = min(range(len(inputs.power_required_w)), key=inputs.power_required_w.__getitem__)
    best_range_m = ranges_m[best_index]
    target_range_m = inputs.target_range_km * 1000.0
    min_power_w = inputs.power_required_w[min_power_index]

    if inputs.objective_mode == "max_range":
        mission_score = -best_range_m
        mission_score_reason = "maximize_range"
    elif inputs.objective_mode == "min_power":
        mission_score = float(min_power_w)
        mission_score_reason = "minimize_power"
    else:
        raise ValueError(f"unsupported objective_mode: {inputs.objective_mode}")

    return MissionEvaluationResult(
        mission_objective_mode=inputs.objective_mode,
        mission_feasible=best_range_m >= target_range_m,
        target_range_km=inputs.target_range_km,
        target_range_passed=best_range_m >= target_range_m,
        target_range_margin_m=best_range_m - target_range_m,
        best_range_m=best_range_m,
        best_range_speed_mps=inputs.speed_mps[best_index],
        best_endurance_s=endurance_s[best_index],
        min_power_w=min_power_w,
        min_power_speed_mps=inputs.speed_mps[min_power_index],
        mission_score=mission_score,
        mission_score_reason=mission_score_reason,
        pilot_power_model="fake_anchor_curve",
        pilot_power_anchor=(
            f"{inputs.rider_curve.anchor_power_w:.1f}W@"
            f"{inputs.rider_curve.anchor_duration_min:.1f}min"
        ),
        speed_sweep_window_mps=(min(inputs.speed_mps), max(inputs.speed_mps)),
    )


def _validate_inputs(inputs: MissionEvaluationInputs) -> None:
    if len(inputs.speed_mps) != len(inputs.power_required_w):
        raise ValueError("speed_mps and power_required_w must have the same length")
    if len(inputs.speed_mps) < 2:
        raise ValueError("at least two sampled speeds are required")
    for speed_mps in inputs.speed_mps:
        _require_finite_positive(speed_mps, "speed_mps")
    for power_required_w in inputs.power_required_w:
        _require_finite_positive(power_required_w, "power_required_w")


def _require_finite_positive(value: float, field_name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be finite and > 0")
