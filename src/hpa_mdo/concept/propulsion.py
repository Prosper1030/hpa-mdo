from __future__ import annotations

from dataclasses import dataclass
import math


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

    def efficiency(self, *, speed_mps: float, shaft_power_w: float) -> float:
        if speed_mps < 0.0:
            raise ValueError("speed_mps must be non-negative.")
        if shaft_power_w <= 0.0:
            raise ValueError("shaft_power_w must be positive.")

        speed_term = max(0.70, 1.0 - 0.015 * abs(float(speed_mps) - 8.5))
        power_term = max(0.75, 1.0 - 0.0004 * abs(float(shaft_power_w) - 280.0))
        efficiency = float(self.design_efficiency) * speed_term * power_term
        return max(0.50, min(0.90, efficiency))


__all__ = ["SimplifiedPropModel"]
