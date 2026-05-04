"""Reusable mission quick-screen utilities for preliminary feasibility checks."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import isfinite, pi, sqrt
from typing import Literal, Sequence

from .objective import CsvPowerCurve, FakeAnchorCurve


RiderCurve = FakeAnchorCurve | CsvPowerCurve

ClBand = Literal["normal", "high_but_possible", "too_high", "low"]
StallBand = Literal["healthy", "caution", "thin_margin", "over_clmax"]


@dataclass(frozen=True)
class MissionQuickScreenInputs:
    speed_mps: float
    span_m: float
    aspect_ratio: float
    mass_kg: float
    cd0_total: float

    oswald_e: float = 0.90
    air_density_kg_m3: float = 1.1357
    gravity_m_s2: float = 9.80665

    eta_prop: float = 0.86
    eta_trans: float = 0.96

    target_range_km: float = 42.195

    rider_curve: RiderCurve | None = None
    thermal_derate_factor: float = 1.0
    cl_max_effective: float = 1.55


@dataclass(frozen=True)
class MissionQuickScreenResult:
    speed_mps: float
    span_m: float
    aspect_ratio: float
    mass_kg: float
    oswald_e: float
    air_density_kg_m3: float
    eta_prop: float
    eta_trans: float
    wing_area_m2: float
    cd0_total: float
    required_time_min: float

    cl_required: float
    cd_induced: float
    induced_power_air_w: float
    parasite_power_air_w: float
    total_power_air_w: float
    required_crank_power_w: float

    cl_max_effective: float
    cl_to_clmax_ratio: float
    cl_margin_to_clmax: float
    stall_speed_mps: float
    stall_margin_speed_ratio: float
    stall_band: StallBand

    pilot_power_test_w: float | None
    pilot_power_hot_w: float | None
    power_margin_crank_w: float | None

    critical_drag_n: float | None
    cd0_max: float | None
    power_passed: bool | None

    cl_band: ClBand


def evaluate_quick_screen(inputs: MissionQuickScreenInputs) -> MissionQuickScreenResult:
    _validate_inputs(inputs)

    wing_area_m2 = inputs.span_m**2 / inputs.aspect_ratio
    weight_newton = inputs.mass_kg * inputs.gravity_m_s2
    dynamic_pressure_pa = 0.5 * inputs.air_density_kg_m3 * inputs.speed_mps**2

    cl_required = weight_newton / (dynamic_pressure_pa * wing_area_m2)
    cd_induced = cl_required**2 / (pi * inputs.oswald_e * inputs.aspect_ratio)
    induced_power_air_w = (
        2.0 * weight_newton**2
        / (
            inputs.air_density_kg_m3
            * pi
            * inputs.oswald_e
            * inputs.span_m**2
            * inputs.speed_mps
        )
    )
    parasite_power_air_w = (
        0.5 * inputs.air_density_kg_m3 * wing_area_m2 * inputs.cd0_total * inputs.speed_mps**3
    )
    total_power_air_w = induced_power_air_w + parasite_power_air_w
    required_crank_power_w = total_power_air_w / (inputs.eta_prop * inputs.eta_trans)
    required_time_min = (
        inputs.target_range_km * 1000.0 / inputs.speed_mps / 60.0
    )

    cl_to_clmax_ratio = cl_required / inputs.cl_max_effective
    cl_margin_to_clmax = inputs.cl_max_effective - cl_required
    stall_speed_mps = sqrt(
        2.0 * weight_newton
        / (inputs.air_density_kg_m3 * wing_area_m2 * inputs.cl_max_effective)
    )
    stall_margin_speed_ratio = inputs.speed_mps / stall_speed_mps

    if inputs.rider_curve is None:
        pilot_power_test_w = None
        pilot_power_hot_w = None
        power_margin_crank_w = None
        critical_drag_n = None
        cd0_max = None
        power_passed = None
    else:
        pilot_power_test_w = inputs.rider_curve.power_at_duration_min(required_time_min)
        pilot_power_hot_w = pilot_power_test_w * inputs.thermal_derate_factor
        power_margin_crank_w = pilot_power_hot_w - required_crank_power_w
        power_avail_crank_w = pilot_power_hot_w * inputs.eta_prop * inputs.eta_trans
        critical_drag_n = power_avail_crank_w / inputs.speed_mps
        cd0_max = (
            power_avail_crank_w - induced_power_air_w
        ) / (0.5 * inputs.air_density_kg_m3 * wing_area_m2 * inputs.speed_mps**3)
        power_passed = power_margin_crank_w >= 0

    cl_band = _classify_cl_band(cl_required)
    stall_band = _classify_stall_band(cl_to_clmax_ratio)

    return MissionQuickScreenResult(
        speed_mps=float(inputs.speed_mps),
        span_m=float(inputs.span_m),
        aspect_ratio=float(inputs.aspect_ratio),
        mass_kg=float(inputs.mass_kg),
        oswald_e=float(inputs.oswald_e),
        air_density_kg_m3=float(inputs.air_density_kg_m3),
        eta_prop=float(inputs.eta_prop),
        eta_trans=float(inputs.eta_trans),
        wing_area_m2=float(wing_area_m2),
        cd0_total=float(inputs.cd0_total),
        required_time_min=float(required_time_min),
        cl_required=float(cl_required),
        cd_induced=float(cd_induced),
        induced_power_air_w=float(induced_power_air_w),
        parasite_power_air_w=float(parasite_power_air_w),
        total_power_air_w=float(total_power_air_w),
        required_crank_power_w=float(required_crank_power_w),
        cl_max_effective=float(inputs.cl_max_effective),
        cl_to_clmax_ratio=float(cl_to_clmax_ratio),
        cl_margin_to_clmax=float(cl_margin_to_clmax),
        stall_speed_mps=float(stall_speed_mps),
        stall_margin_speed_ratio=float(stall_margin_speed_ratio),
        stall_band=stall_band,
        pilot_power_test_w=None if pilot_power_test_w is None else float(pilot_power_test_w),
        pilot_power_hot_w=None if pilot_power_hot_w is None else float(pilot_power_hot_w),
        power_margin_crank_w=None
        if power_margin_crank_w is None
        else float(power_margin_crank_w),
        critical_drag_n=None if critical_drag_n is None else float(critical_drag_n),
        cd0_max=None if cd0_max is None else float(cd0_max),
        power_passed=None if power_passed is None else bool(power_passed),
        cl_band=cl_band,
    )


def sweep_quick_screen_grid(
    speeds_mps: Sequence[float],
    spans_m: Sequence[float],
    aspect_ratios: Sequence[float],
    cd0_totals: Sequence[float],
    mass_kg: float,
    oswald_e: float = 0.90,
    air_density_kg_m3: float = 1.1357,
    gravity_m_s2: float = 9.80665,
    eta_prop: float = 0.86,
    eta_trans: float = 0.96,
    target_range_km: float = 42.195,
    cl_max_effectives: Sequence[float] | None = None,
    rider_curve: RiderCurve | None = None,
    thermal_derate_factor: float = 1.0,
) -> list[MissionQuickScreenResult]:
    cl_max_values: tuple[float, ...]
    if cl_max_effectives is None:
        cl_max_values = (1.55,)
    else:
        cl_max_values = tuple(float(value) for value in cl_max_effectives)
        if len(cl_max_values) == 0:
            raise ValueError("cl_max_effectives must include at least one value.")
    results: list[MissionQuickScreenResult] = []
    for speed_mps, span_m, aspect_ratio, cd0_total, cl_max_effective in product(
        speeds_mps,
        spans_m,
        aspect_ratios,
        cd0_totals,
        cl_max_values,
    ):
        inputs = MissionQuickScreenInputs(
            speed_mps=float(speed_mps),
            span_m=float(span_m),
            aspect_ratio=float(aspect_ratio),
            mass_kg=float(mass_kg),
            cd0_total=float(cd0_total),
            oswald_e=oswald_e,
            air_density_kg_m3=air_density_kg_m3,
            gravity_m_s2=gravity_m_s2,
            eta_prop=eta_prop,
            eta_trans=eta_trans,
            target_range_km=target_range_km,
            cl_max_effective=cl_max_effective,
            rider_curve=rider_curve,
            thermal_derate_factor=thermal_derate_factor,
        )
        results.append(evaluate_quick_screen(inputs))
    return results


def _classify_cl_band(cl_required: float) -> ClBand:
    if 1.10 <= cl_required <= 1.35:
        return "normal"
    if 1.35 < cl_required <= 1.50:
        return "high_but_possible"
    if cl_required > 1.50:
        return "too_high"
    return "low"


def _classify_stall_band(cl_to_clmax_ratio: float) -> StallBand:
    if cl_to_clmax_ratio <= 0.80:
        return "healthy"
    if cl_to_clmax_ratio <= 0.90:
        return "caution"
    if cl_to_clmax_ratio <= 1.00:
        return "thin_margin"
    return "over_clmax"


def _validate_inputs(inputs: MissionQuickScreenInputs) -> None:
    _require_finite_positive(inputs.speed_mps, "speed_mps")
    _require_finite_positive(inputs.span_m, "span_m")
    _require_finite_positive(inputs.aspect_ratio, "aspect_ratio")
    _require_finite_positive(inputs.mass_kg, "mass_kg")
    _require_finite_non_negative(inputs.cd0_total, "cd0_total")
    if not (0.0 < float(inputs.oswald_e) <= 1.2):
        raise ValueError("oswald_e must be finite and in (0, 1.2].")
    _require_finite_positive(inputs.air_density_kg_m3, "air_density_kg_m3")
    _require_finite_positive(inputs.gravity_m_s2, "gravity_m_s2")
    if not (0.0 < float(inputs.eta_prop) <= 1.0):
        raise ValueError("eta_prop must be finite and in (0, 1.0].")
    if not (0.0 < float(inputs.eta_trans) <= 1.0):
        raise ValueError("eta_trans must be finite and in (0, 1.0].")
    _require_finite_positive(inputs.target_range_km, "target_range_km")
    if not (0.0 < float(inputs.cl_max_effective) <= 3.0):
        raise ValueError("cl_max_effective must be finite and in (0, 3.0].")
    _require_finite_non_negative(
        inputs.thermal_derate_factor,
        "thermal_derate_factor",
    )


def _require_finite_positive(value: float, field_name: str) -> None:
    if not isfinite(float(value)) or float(value) <= 0.0:
        raise ValueError(f"{field_name} must be finite and > 0.")


def _require_finite_non_negative(value: float, field_name: str) -> None:
    if not isfinite(float(value)) or float(value) < 0.0:
        raise ValueError(f"{field_name} must be finite and >= 0.")
