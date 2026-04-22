from __future__ import annotations

from dataclasses import dataclass
from math import exp, pi


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class SimplifiedPropModel:
    diameter_m: float
    rpm_min: float
    rpm_max: float
    design_efficiency: float

    def __post_init__(self) -> None:
        if self.diameter_m <= 0.0:
            raise ValueError("diameter_m must be positive.")
        if self.rpm_min <= 0.0:
            raise ValueError("rpm_min must be positive.")
        if self.rpm_max <= self.rpm_min:
            raise ValueError("rpm_max must be greater than rpm_min.")
        if not 0.0 < self.design_efficiency <= 1.0:
            raise ValueError("design_efficiency must be in the interval (0, 1].")

    @property
    def _mean_rpm(self) -> float:
        return 0.5 * (float(self.rpm_min) + float(self.rpm_max))

    @property
    def _design_speed_mps(self) -> float:
        tip_speed_mps = pi * float(self.diameter_m) * self._mean_rpm / 60.0
        return max(1.0e-6, 0.08 * tip_speed_mps)

    @property
    def _design_shaft_power_w(self) -> float:
        return max(1.0e-6, 0.12 * float(self.diameter_m) * self._mean_rpm)

    def efficiency(self, speed_mps: float, shaft_power_w: float) -> float:
        if speed_mps < 0.0:
            raise ValueError("speed_mps must be non-negative.")
        if shaft_power_w <= 0.0:
            raise ValueError("shaft_power_w must be positive.")

        speed_ratio = float(speed_mps) / self._design_speed_mps
        power_ratio = float(shaft_power_w) / self._design_shaft_power_w

        speed_term = exp(-((speed_ratio - 1.0) / 0.55) ** 2)
        power_term = 0.78 + 0.22 * exp(-((power_ratio - 1.0) / 0.75) ** 2)
        efficiency = float(self.design_efficiency) * speed_term * power_term
        return _clamp(efficiency, 0.05, float(self.design_efficiency))


__all__ = ["SimplifiedPropModel"]
