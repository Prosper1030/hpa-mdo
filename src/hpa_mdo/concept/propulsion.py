from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimplifiedPropModel:
    """Concept-stage prop efficiency proxy.

    The efficiency formula is a coarse linear-falloff correction around a
    peak operating point ``(peak_speed_mps, peak_shaft_power_w)``. All
    coefficients are sourced from ``cfg.prop.efficiency_model`` (see
    ``PropEfficiencyConfig``) so that no propulsion physics is hard-coded
    in this module (CLAUDE.md ironclad rule #1).

    ``diameter_m``, ``rpm_min``, ``rpm_max`` are preserved on the artifact
    surface so later tasks can hand them off to richer prop models; the
    current proxy does not yet consume them in the efficiency calc.
    """

    diameter_m: float
    rpm_min: float
    rpm_max: float
    design_efficiency: float
    peak_speed_mps: float
    peak_shaft_power_w: float
    speed_falloff_per_mps: float
    power_falloff_per_w: float
    speed_term_floor: float
    power_term_floor: float
    efficiency_floor: float
    efficiency_ceiling: float

    def __post_init__(self) -> None:
        if self.diameter_m <= 0.0:
            raise ValueError("diameter_m must be positive.")
        if self.rpm_min <= 0.0:
            raise ValueError("rpm_min must be positive.")
        if self.rpm_max <= self.rpm_min:
            raise ValueError("rpm_max must be greater than rpm_min.")
        if not 0.0 < self.design_efficiency <= 1.0:
            raise ValueError("design_efficiency must be in the interval (0, 1].")
        if self.peak_speed_mps <= 0.0:
            raise ValueError("peak_speed_mps must be positive.")
        if self.peak_shaft_power_w <= 0.0:
            raise ValueError("peak_shaft_power_w must be positive.")
        if self.speed_falloff_per_mps < 0.0:
            raise ValueError("speed_falloff_per_mps must be non-negative.")
        if self.power_falloff_per_w < 0.0:
            raise ValueError("power_falloff_per_w must be non-negative.")
        if not 0.0 < self.speed_term_floor <= 1.0:
            raise ValueError("speed_term_floor must be in the interval (0, 1].")
        if not 0.0 < self.power_term_floor <= 1.0:
            raise ValueError("power_term_floor must be in the interval (0, 1].")
        if not 0.0 < self.efficiency_floor < self.efficiency_ceiling <= 1.0:
            raise ValueError(
                "efficiency_floor must be < efficiency_ceiling and both in (0, 1]."
            )
        if not (
            self.efficiency_floor <= self.design_efficiency <= self.efficiency_ceiling
        ):
            raise ValueError(
                "design_efficiency must lie within [efficiency_floor, efficiency_ceiling]."
            )

    @classmethod
    def from_config(
        cls,
        *,
        diameter_m: float,
        rpm_min: float,
        rpm_max: float,
        efficiency_cfg,
    ) -> "SimplifiedPropModel":
        return cls(
            diameter_m=float(diameter_m),
            rpm_min=float(rpm_min),
            rpm_max=float(rpm_max),
            design_efficiency=float(efficiency_cfg.design_efficiency),
            peak_speed_mps=float(efficiency_cfg.peak_speed_mps),
            peak_shaft_power_w=float(efficiency_cfg.peak_shaft_power_w),
            speed_falloff_per_mps=float(efficiency_cfg.speed_falloff_per_mps),
            power_falloff_per_w=float(efficiency_cfg.power_falloff_per_w),
            speed_term_floor=float(efficiency_cfg.speed_term_floor),
            power_term_floor=float(efficiency_cfg.power_term_floor),
            efficiency_floor=float(efficiency_cfg.efficiency_floor),
            efficiency_ceiling=float(efficiency_cfg.efficiency_ceiling),
        )

    def efficiency(self, *, speed_mps: float, shaft_power_w: float) -> float:
        if speed_mps < 0.0:
            raise ValueError("speed_mps must be non-negative.")
        if shaft_power_w <= 0.0:
            raise ValueError("shaft_power_w must be positive.")

        speed_term = max(
            self.speed_term_floor,
            1.0 - self.speed_falloff_per_mps * abs(float(speed_mps) - self.peak_speed_mps),
        )
        power_term = max(
            self.power_term_floor,
            1.0
            - self.power_falloff_per_w
            * abs(float(shaft_power_w) - self.peak_shaft_power_w),
        )
        efficiency = float(self.design_efficiency) * speed_term * power_term
        return max(self.efficiency_floor, min(self.efficiency_ceiling, efficiency))


__all__ = ["SimplifiedPropModel"]
