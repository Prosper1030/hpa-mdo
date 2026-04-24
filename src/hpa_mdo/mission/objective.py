"""Mission objective evaluation utilities."""

from __future__ import annotations

from bisect import bisect_left
import csv
import math
from dataclasses import dataclass
from pathlib import Path
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
        _require_finite_positive(duration_min, "duration_min")
        ratio = self.anchor_duration_min / duration_min
        power_w = self.anchor_power_w * ratio ** self.exponent
        return self._clamp_power(power_w)

    def duration_at_power_w(self, power_w: float) -> float:
        _require_finite_positive(power_w, "power_w")
        clamped_power_w = self._clamp_power(power_w)
        ratio = self.anchor_power_w / clamped_power_w
        return self.anchor_duration_min * ratio ** (1.0 / self.exponent)

    def _clamp_power(self, power_w: float) -> float:
        return max(self.min_power_w, min(self.max_power_w, power_w))


@dataclass(frozen=True)
class CsvPowerCurve:
    durations_min: tuple[float, ...]
    powers_w: tuple[float, ...]
    source_path: Path
    reference_duration_min: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", Path(self.source_path).expanduser().resolve())
        object.__setattr__(self, "durations_min", tuple(float(value) for value in self.durations_min))
        object.__setattr__(self, "powers_w", tuple(float(value) for value in self.powers_w))

        if len(self.durations_min) != len(self.powers_w):
            raise ValueError("durations_min and powers_w must have the same length")
        if len(self.durations_min) < 2:
            raise ValueError("CsvPowerCurve requires at least two samples")
        _require_finite_positive(self.reference_duration_min, "reference_duration_min")

        for duration_min in self.durations_min:
            _require_finite_positive(duration_min, "durations_min")
        for power_w in self.powers_w:
            _require_finite_positive(power_w, "powers_w")

        if any(
            later <= earlier
            for earlier, later in zip(self.durations_min, self.durations_min[1:])
        ):
            raise ValueError("durations_min must be strictly increasing")
        if any(
            later > earlier + 1.0e-9
            for earlier, later in zip(self.powers_w, self.powers_w[1:])
        ):
            raise ValueError("powers_w must be monotone non-increasing")

    @property
    def anchor_duration_min(self) -> float:
        return float(self.reference_duration_min)

    @property
    def anchor_power_w(self) -> float:
        return float(self.power_at_duration_min(self.reference_duration_min))

    @property
    def min_power_w(self) -> float:
        return float(self.powers_w[-1])

    @property
    def max_power_w(self) -> float:
        return float(self.powers_w[0])

    def power_at_duration_min(self, duration_min: float) -> float:
        _require_finite_positive(duration_min, "duration_min")
        return float(_interpolate_clamped(duration_min, self.durations_min, self.powers_w))

    def duration_at_power_w(self, power_w: float) -> float:
        _require_finite_positive(power_w, "power_w")
        clamped_power_w = min(max(power_w, self.min_power_w), self.max_power_w)
        ascending_powers_w, durations_min = self._ascending_power_duration_pairs()
        return float(_interpolate_clamped(clamped_power_w, ascending_powers_w, durations_min))

    def _ascending_power_duration_pairs(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        ascending_powers: list[float] = []
        durations_min: list[float] = []
        last_power_w: float | None = None
        for power_w, duration_min in zip(
            reversed(self.powers_w),
            reversed(self.durations_min),
        ):
            if (
                last_power_w is not None
                and math.isclose(power_w, last_power_w, rel_tol=1.0e-12, abs_tol=1.0e-12)
            ):
                continue
            ascending_powers.append(float(power_w))
            durations_min.append(float(duration_min))
            last_power_w = float(power_w)
        return tuple(ascending_powers), tuple(durations_min)


@dataclass(frozen=True)
class MissionEvaluationInputs:
    objective_mode: str
    target_range_km: float
    speed_mps: Sequence[float]
    power_required_w: Sequence[float]
    rider_curve: FakeAnchorCurve | CsvPowerCurve


@dataclass(frozen=True)
class MissionEvaluationResult:
    mission_objective_mode: str
    mission_feasible: bool
    target_range_km: float
    target_range_passed: bool
    target_range_margin_m: float
    best_power_margin_w: float
    best_power_margin_speed_mps: float
    power_margin_w_by_speed: tuple[float, ...]
    required_duration_min_by_speed: tuple[float, ...]
    available_power_w_by_speed: tuple[float, ...]
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


def load_csv_power_curve(
    csv_path: str | Path,
    *,
    duration_column: str = "secs",
    power_column: str = "watts",
    duration_scale_to_min: float = 1.0 / 60.0,
    reference_duration_min: float = 30.0,
) -> CsvPowerCurve:
    _require_finite_positive(duration_scale_to_min, "duration_scale_to_min")
    csv_path = Path(csv_path).expanduser().resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"power curve CSV not found: {csv_path}")

    duration_to_power_w: dict[float, float] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"power curve CSV has no header row: {csv_path}")
        if duration_column not in reader.fieldnames:
            raise ValueError(
                f"power curve CSV missing duration column '{duration_column}': {csv_path}"
            )
        if power_column not in reader.fieldnames:
            raise ValueError(
                f"power curve CSV missing power column '{power_column}': {csv_path}"
            )

        for row_index, row in enumerate(reader, start=2):
            duration_text = row.get(duration_column)
            power_text = row.get(power_column)
            if duration_text is None or power_text is None:
                continue
            if not str(duration_text).strip() and not str(power_text).strip():
                continue
            if not str(duration_text).strip() or not str(power_text).strip():
                raise ValueError(
                    f"power curve CSV row {row_index} must include both {duration_column} and {power_column}"
                )
            duration_value = float(duration_text)
            power_w = float(power_text)
            _require_finite_positive(duration_value, f"{duration_column} row {row_index}")
            _require_finite_positive(power_w, f"{power_column} row {row_index}")
            duration_min = float(duration_value) * float(duration_scale_to_min)
            existing_power_w = duration_to_power_w.get(duration_min)
            if existing_power_w is None or power_w > existing_power_w:
                duration_to_power_w[duration_min] = float(power_w)

    if len(duration_to_power_w) < 2:
        raise ValueError(f"power curve CSV must provide at least two samples: {csv_path}")

    durations_min = tuple(sorted(duration_to_power_w))
    powers_w = [float(duration_to_power_w[duration_min]) for duration_min in durations_min]
    for index in range(len(powers_w) - 2, -1, -1):
        powers_w[index] = max(float(powers_w[index]), float(powers_w[index + 1]))

    return CsvPowerCurve(
        durations_min=durations_min,
        powers_w=tuple(float(value) for value in powers_w),
        source_path=csv_path,
        reference_duration_min=reference_duration_min,
    )


def build_rider_power_curve(
    *,
    anchor_power_w: float,
    anchor_duration_min: float,
    rider_power_curve_csv: str | Path | None = None,
    rider_model: str = "fake_anchor_curve",
    duration_column: str = "secs",
    power_column: str = "watts",
) -> FakeAnchorCurve | CsvPowerCurve:
    if rider_power_curve_csv is not None:
        return load_csv_power_curve(
            rider_power_curve_csv,
            duration_column=duration_column,
            power_column=power_column,
            reference_duration_min=anchor_duration_min,
        )
    if rider_model != "fake_anchor_curve":
        raise ValueError(f"unsupported rider_model without CSV path: {rider_model}")
    return FakeAnchorCurve(
        anchor_power_w=anchor_power_w,
        anchor_duration_min=anchor_duration_min,
    )


def evaluate_mission_objective(
    inputs: MissionEvaluationInputs,
) -> MissionEvaluationResult:
    _validate_inputs(inputs)

    target_range_m = inputs.target_range_km * 1000.0
    ranges_m = []
    endurance_s = []
    required_duration_min_by_speed = []
    available_power_w_by_speed = []
    power_margin_w_by_speed = []
    for speed_mps, power_required_w in zip(inputs.speed_mps, inputs.power_required_w):
        duration_min = inputs.rider_curve.duration_at_power_w(power_required_w)
        duration_s = duration_min * 60.0
        endurance_s.append(duration_s)
        ranges_m.append(speed_mps * duration_s)

        required_duration_min = target_range_m / speed_mps / 60.0
        available_power_w = inputs.rider_curve.power_at_duration_min(required_duration_min)
        required_duration_min_by_speed.append(required_duration_min)
        available_power_w_by_speed.append(available_power_w)
        power_margin_w_by_speed.append(available_power_w - power_required_w)

    best_index = max(range(len(ranges_m)), key=ranges_m.__getitem__)
    best_power_margin_index = max(
        range(len(power_margin_w_by_speed)),
        key=power_margin_w_by_speed.__getitem__,
    )
    min_power_index = min(range(len(inputs.power_required_w)), key=inputs.power_required_w.__getitem__)
    best_range_m = ranges_m[best_index]
    best_endurance_s = max(endurance_s)
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
        best_power_margin_w=float(power_margin_w_by_speed[best_power_margin_index]),
        best_power_margin_speed_mps=float(inputs.speed_mps[best_power_margin_index]),
        power_margin_w_by_speed=tuple(float(value) for value in power_margin_w_by_speed),
        required_duration_min_by_speed=tuple(
            float(value) for value in required_duration_min_by_speed
        ),
        available_power_w_by_speed=tuple(
            float(value) for value in available_power_w_by_speed
        ),
        best_range_m=best_range_m,
        best_range_speed_mps=float(inputs.speed_mps[best_index]),
        best_endurance_s=best_endurance_s,
        min_power_w=min_power_w,
        min_power_speed_mps=float(inputs.speed_mps[min_power_index]),
        mission_score=mission_score,
        mission_score_reason=mission_score_reason,
        pilot_power_model=_pilot_power_model_name(inputs.rider_curve),
        pilot_power_anchor=_pilot_power_anchor_label(inputs.rider_curve),
        speed_sweep_window_mps=(min(inputs.speed_mps), max(inputs.speed_mps)),
    )


def _pilot_power_model_name(curve: FakeAnchorCurve | CsvPowerCurve) -> str:
    if isinstance(curve, CsvPowerCurve):
        return "csv_power_curve"
    return "fake_anchor_curve"


def _pilot_power_anchor_label(curve: FakeAnchorCurve | CsvPowerCurve) -> str:
    if isinstance(curve, CsvPowerCurve):
        return (
            f"{curve.source_path.name}@{curve.anchor_duration_min:.1f}min="
            f"{curve.anchor_power_w:.1f}W"
        )
    return f"{curve.anchor_power_w:.1f}W@{curve.anchor_duration_min:.1f}min"


def _interpolate_clamped(x: float, xp: Sequence[float], fp: Sequence[float]) -> float:
    if len(xp) != len(fp):
        raise ValueError("xp and fp must have the same length")
    if len(xp) < 2:
        raise ValueError("xp and fp must contain at least two points")
    if x <= float(xp[0]):
        return float(fp[0])
    if x >= float(xp[-1]):
        return float(fp[-1])

    upper_index = bisect_left(xp, x)
    if upper_index < len(xp) and math.isclose(float(xp[upper_index]), x, rel_tol=0.0, abs_tol=1.0e-12):
        return float(fp[upper_index])

    lower_index = upper_index - 1
    x0 = float(xp[lower_index])
    x1 = float(xp[upper_index])
    y0 = float(fp[lower_index])
    y1 = float(fp[upper_index])
    if math.isclose(x1, x0, rel_tol=0.0, abs_tol=1.0e-12):
        return y0
    frac = (x - x0) / (x1 - x0)
    return y0 + frac * (y1 - y0)


def _validate_inputs(inputs: MissionEvaluationInputs) -> None:
    _require_finite_positive(inputs.target_range_km, "target_range_km")
    if len(inputs.speed_mps) != len(inputs.power_required_w):
        raise ValueError("speed_mps and power_required_w must have the same length")
    if len(inputs.speed_mps) < 1:
        raise ValueError("at least one sampled speed is required")
    for speed_mps in inputs.speed_mps:
        _require_finite_positive(speed_mps, "speed_mps")
    for power_required_w in inputs.power_required_w:
        _require_finite_positive(power_required_w, "power_required_w")


def _require_finite_positive(value: float, field_name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be finite and > 0")
