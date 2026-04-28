from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SimplifiedPropModel:
    """Concept-stage prop efficiency proxy.

    Two modes selectable via ``use_bemt_proxy``:

    - Operating-point proxy (default): η = design_efficiency × speed_term ×
      power_term, clamped. Independent of diameter / RPM / blade count;
      kept for backwards compatibility with existing tuning.

    - BEMT-flavored proxy: physics-anchored, uses momentum-theory ideal
      efficiency (function of disk loading T/A → diameter and forward
      speed), finite-blade knockdown (1 - k/B), profile-drag knockdown,
      off-design parabolic penalty in advance ratio J = V/(n·D), and a
      soft V_tip ceiling. Defaults tuned so the reference operating point
      (V=8.5, P=280, D=3, B=2, RPM=140) gives η ≈ 0.83.

    All physical parameters source from ``cfg.prop.*`` and
    ``cfg.prop.efficiency_model.*`` per CLAUDE.md ironclad rule #1; no
    propulsion physics is hard-coded in this module.
    """

    diameter_m: float
    rpm_min: float
    rpm_max: float
    blade_count: int
    air_density_kg_per_m3: float
    design_efficiency: float
    peak_speed_mps: float
    peak_shaft_power_w: float
    speed_falloff_per_mps: float
    power_falloff_per_w: float
    speed_term_floor: float
    power_term_floor: float
    efficiency_floor: float
    efficiency_ceiling: float
    use_bemt_proxy: bool
    bemt_blade_loss_constant: float
    bemt_profile_loss: float
    bemt_peak_advance_ratio: float
    bemt_advance_ratio_falloff: float
    bemt_advance_ratio_floor: float
    bemt_design_rpm: float
    bemt_v_tip_max_mps: float
    bemt_v_tip_penalty_slope: float

    def __post_init__(self) -> None:
        if self.diameter_m <= 0.0:
            raise ValueError("diameter_m must be positive.")
        if self.rpm_min <= 0.0:
            raise ValueError("rpm_min must be positive.")
        if self.rpm_max <= self.rpm_min:
            raise ValueError("rpm_max must be greater than rpm_min.")
        if self.blade_count < 1:
            raise ValueError("blade_count must be >= 1.")
        if self.air_density_kg_per_m3 <= 0.0:
            raise ValueError("air_density_kg_per_m3 must be positive.")
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
        if self.bemt_blade_loss_constant < 0.0:
            raise ValueError("bemt_blade_loss_constant must be non-negative.")
        if not 0.0 <= self.bemt_profile_loss < 1.0:
            raise ValueError("bemt_profile_loss must be in [0, 1).")
        if self.bemt_peak_advance_ratio <= 0.0:
            raise ValueError("bemt_peak_advance_ratio must be positive.")
        if self.bemt_advance_ratio_falloff < 0.0:
            raise ValueError("bemt_advance_ratio_falloff must be non-negative.")
        if not 0.0 < self.bemt_advance_ratio_floor <= 1.0:
            raise ValueError("bemt_advance_ratio_floor must be in (0, 1].")
        if self.bemt_design_rpm <= 0.0:
            raise ValueError("bemt_design_rpm must be positive.")
        if self.bemt_v_tip_max_mps <= 0.0:
            raise ValueError("bemt_v_tip_max_mps must be positive.")
        if self.bemt_v_tip_penalty_slope < 0.0:
            raise ValueError("bemt_v_tip_penalty_slope must be non-negative.")

    @classmethod
    def from_config(
        cls,
        *,
        diameter_m: float,
        rpm_min: float,
        rpm_max: float,
        blade_count: int,
        air_density_kg_per_m3: float,
        efficiency_cfg,
    ) -> "SimplifiedPropModel":
        return cls(
            diameter_m=float(diameter_m),
            rpm_min=float(rpm_min),
            rpm_max=float(rpm_max),
            blade_count=int(blade_count),
            air_density_kg_per_m3=float(air_density_kg_per_m3),
            design_efficiency=float(efficiency_cfg.design_efficiency),
            peak_speed_mps=float(efficiency_cfg.peak_speed_mps),
            peak_shaft_power_w=float(efficiency_cfg.peak_shaft_power_w),
            speed_falloff_per_mps=float(efficiency_cfg.speed_falloff_per_mps),
            power_falloff_per_w=float(efficiency_cfg.power_falloff_per_w),
            speed_term_floor=float(efficiency_cfg.speed_term_floor),
            power_term_floor=float(efficiency_cfg.power_term_floor),
            efficiency_floor=float(efficiency_cfg.efficiency_floor),
            efficiency_ceiling=float(efficiency_cfg.efficiency_ceiling),
            use_bemt_proxy=bool(efficiency_cfg.use_bemt_proxy),
            bemt_blade_loss_constant=float(efficiency_cfg.bemt_blade_loss_constant),
            bemt_profile_loss=float(efficiency_cfg.bemt_profile_loss),
            bemt_peak_advance_ratio=float(efficiency_cfg.bemt_peak_advance_ratio),
            bemt_advance_ratio_falloff=float(efficiency_cfg.bemt_advance_ratio_falloff),
            bemt_advance_ratio_floor=float(efficiency_cfg.bemt_advance_ratio_floor),
            bemt_design_rpm=float(efficiency_cfg.bemt_design_rpm),
            bemt_v_tip_max_mps=float(efficiency_cfg.bemt_v_tip_max_mps),
            bemt_v_tip_penalty_slope=float(efficiency_cfg.bemt_v_tip_penalty_slope),
        )

    def efficiency(self, *, speed_mps: float, shaft_power_w: float) -> float:
        if speed_mps < 0.0:
            raise ValueError("speed_mps must be non-negative.")
        if shaft_power_w <= 0.0:
            raise ValueError("shaft_power_w must be positive.")
        if self.use_bemt_proxy:
            return self._efficiency_bemt(
                speed_mps=speed_mps,
                shaft_power_w=shaft_power_w,
            )
        return self._efficiency_op_point(
            speed_mps=speed_mps,
            shaft_power_w=shaft_power_w,
        )

    def _efficiency_op_point(self, *, speed_mps: float, shaft_power_w: float) -> float:
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

    def _efficiency_bemt(self, *, speed_mps: float, shaft_power_w: float) -> float:
        # Fixed-point iteration: η depends on T (via momentum theory),
        # T = η · P_shaft / V depends on η. Converges fast since η_ideal
        # is weakly nonlinear in T at typical HPA disk loadings.
        disk_area_m2 = math.pi * self.diameter_m**2 / 4.0
        n_rev_per_s = self.bemt_design_rpm / 60.0
        v_tip_mps = math.pi * self.diameter_m * n_rev_per_s
        if v_tip_mps > self.bemt_v_tip_max_mps:
            v_tip_penalty = max(
                0.0,
                1.0
                - self.bemt_v_tip_penalty_slope
                * (v_tip_mps / self.bemt_v_tip_max_mps - 1.0),
            )
        else:
            v_tip_penalty = 1.0
        advance_ratio = float(speed_mps) / max(n_rev_per_s * self.diameter_m, 1.0e-9)
        advance_ratio_term = max(
            self.bemt_advance_ratio_floor,
            1.0
            - self.bemt_advance_ratio_falloff
            * (advance_ratio - self.bemt_peak_advance_ratio) ** 2,
        )
        eta_blade = max(
            0.0,
            1.0 - self.bemt_blade_loss_constant / max(float(self.blade_count), 1.0e-9),
        )
        eta_profile = max(0.0, 1.0 - self.bemt_profile_loss)

        eta = float(self.design_efficiency)
        for _ in range(5):
            thrust_n = eta * float(shaft_power_w) / max(float(speed_mps), 1.0e-6)
            ram_pressure_per_area_n = (
                self.air_density_kg_per_m3 * float(speed_mps) ** 2
            )
            disk_loading_factor = (
                2.0 * thrust_n
                / max(disk_area_m2 * ram_pressure_per_area_n, 1.0e-9)
            )
            eta_ideal = 2.0 / (1.0 + math.sqrt(1.0 + disk_loading_factor))
            eta_new = (
                eta_ideal
                * eta_blade
                * eta_profile
                * advance_ratio_term
                * v_tip_penalty
            )
            eta_new = max(self.efficiency_floor, min(self.efficiency_ceiling, eta_new))
            if abs(eta_new - eta) < 1.0e-4:
                eta = eta_new
                break
            eta = eta_new
        return eta


__all__ = ["SimplifiedPropModel"]
