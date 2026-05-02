"""Report-only area/mass closure helpers for upstream HPA concept sizing."""

from __future__ import annotations

import math
from dataclasses import dataclass


_STANDARD_GRAVITY_MPS2 = 9.80665


def estimate_tube_system_mass_kg(
    *,
    span_m: float,
    root_outer_diameter_m: float,
    tip_outer_diameter_m: float,
    root_wall_thickness_m: float,
    tip_wall_thickness_m: float,
    density_kg_per_m3: float = 1600.0,
    num_spars_per_wing: int = 2,
    num_wings: int = 2,
) -> float:
    """Mass of a thin-wall circular CFRP tube spar system from geometry.

    Each spar runs from root to tip on one wing-half (length = span / 2).
    Outer diameter and wall thickness taper linearly along the spar; the
    integral ∫ π D(x) t(x) dx is evaluated by Simpson's rule, which is exact
    for the resulting quadratic D(x) t(x). Caller multiplies by spar count
    (default 2 spars per wing × 2 wings = 4 tubes).
    """

    _require_finite_positive(span_m, "span_m")
    _require_finite_positive(root_outer_diameter_m, "root_outer_diameter_m")
    _require_finite_positive(tip_outer_diameter_m, "tip_outer_diameter_m")
    _require_finite_positive(root_wall_thickness_m, "root_wall_thickness_m")
    _require_finite_positive(tip_wall_thickness_m, "tip_wall_thickness_m")
    _require_finite_positive(density_kg_per_m3, "density_kg_per_m3")
    if int(num_spars_per_wing) <= 0:
        raise ValueError("num_spars_per_wing must be a positive integer")
    if int(num_wings) <= 0:
        raise ValueError("num_wings must be a positive integer")

    half_span_m = 0.5 * float(span_m)
    d_root = float(root_outer_diameter_m)
    d_tip = float(tip_outer_diameter_m)
    t_root = float(root_wall_thickness_m)
    t_tip = float(tip_wall_thickness_m)
    d_mid = 0.5 * (d_root + d_tip)
    t_mid = 0.5 * (t_root + t_tip)
    integrand_avg = (d_root * t_root + 4.0 * d_mid * t_mid + d_tip * t_tip) / 6.0
    mass_per_tube_kg = float(density_kg_per_m3) * math.pi * integrand_avg * half_span_m
    total_tube_count = int(num_spars_per_wing) * int(num_wings)
    return float(mass_per_tube_kg * total_tube_count)


@dataclass(frozen=True)
class AreaMassClosureResult:
    wing_loading_target_Npm2: float
    closed_wing_area_m2: float
    closed_gross_mass_kg: float
    fixed_mass_kg: float
    wing_area_dependent_mass_kg: float
    mass_breakdown_kg: dict[str, float]
    area_residual_m2: float
    iterations: int
    converged: bool


@dataclass(frozen=True)
class FixedPlanformMassResult:
    wing_area_m2: float
    gross_mass_kg: float
    aircraft_empty_mass_kg: float
    fixed_mass_kg: float
    wing_area_dependent_mass_kg: float
    mass_breakdown_kg: dict[str, float]


def estimate_fixed_planform_mass(
    *,
    wing_area_m2: float,
    pilot_mass_kg: float,
    fixed_non_area_aircraft_mass_kg: float,
    wing_areal_density_kgpm2: float = 0.22,
    tube_system_mass_kg: float = 0.0,
    wing_fittings_base_kg: float = 0.0,
    wire_terminal_mass_kg: float = 0.0,
    extra_system_margin_kg: float = 0.0,
) -> FixedPlanformMassResult:
    """Estimate mass for a planform whose wing area is already chosen.

    Unlike ``close_area_mass``, this helper does not resize the wing area to
    hit a wing-loading target. It is therefore the right report-only mass
    proxy for mean-chord planform sampling, where ``S = b * c_bar`` is a
    design input and wing loading is a derived consequence.
    """

    _require_finite_positive(wing_area_m2, "wing_area_m2")
    _require_finite_positive(pilot_mass_kg, "pilot_mass_kg")
    _require_finite_positive(
        fixed_non_area_aircraft_mass_kg,
        "fixed_non_area_aircraft_mass_kg",
    )
    _require_finite_non_negative(wing_areal_density_kgpm2, "wing_areal_density_kgpm2")
    _require_finite_non_negative(tube_system_mass_kg, "tube_system_mass_kg")
    _require_finite_non_negative(wing_fittings_base_kg, "wing_fittings_base_kg")
    _require_finite_non_negative(wire_terminal_mass_kg, "wire_terminal_mass_kg")
    _require_finite_non_negative(extra_system_margin_kg, "extra_system_margin_kg")

    wing_area_dependent_mass_kg = float(wing_areal_density_kgpm2) * float(wing_area_m2)
    aircraft_empty_mass_kg = (
        float(fixed_non_area_aircraft_mass_kg)
        + float(tube_system_mass_kg)
        + float(wing_fittings_base_kg)
        + float(wire_terminal_mass_kg)
        + float(extra_system_margin_kg)
        + wing_area_dependent_mass_kg
    )
    gross_mass_kg = float(pilot_mass_kg) + aircraft_empty_mass_kg
    fixed_mass_kg = gross_mass_kg - wing_area_dependent_mass_kg
    return FixedPlanformMassResult(
        wing_area_m2=float(wing_area_m2),
        gross_mass_kg=float(gross_mass_kg),
        aircraft_empty_mass_kg=float(aircraft_empty_mass_kg),
        fixed_mass_kg=float(fixed_mass_kg),
        wing_area_dependent_mass_kg=float(wing_area_dependent_mass_kg),
        mass_breakdown_kg={
            "pilot_kg": float(pilot_mass_kg),
            "fixed_non_area_aircraft_kg": float(fixed_non_area_aircraft_mass_kg),
            "tube_system_kg": float(tube_system_mass_kg),
            "wing_fittings_base_kg": float(wing_fittings_base_kg),
            "wire_terminal_kg": float(wire_terminal_mass_kg),
            "extra_system_margin_kg": float(extra_system_margin_kg),
            "wing_area_dependent_kg": float(wing_area_dependent_mass_kg),
        },
    )


def close_area_mass(
    *,
    wing_loading_target_Npm2: float,
    pilot_mass_kg: float,
    fixed_non_area_aircraft_mass_kg: float,
    wing_areal_density_kgpm2: float = 0.22,
    tube_system_mass_kg: float = 0.0,
    wing_fittings_base_kg: float = 0.0,
    wire_terminal_mass_kg: float = 0.0,
    extra_system_margin_kg: float = 0.0,
    initial_wing_area_m2: float | None = None,
    tolerance_m2: float = 1.0e-6,
    max_iterations: int = 50,
    gravity_mps2: float = _STANDARD_GRAVITY_MPS2,
) -> AreaMassClosureResult:
    """Close wing area against a first-order area-dependent mass model.

    This is intentionally lightweight and report-only: it catches cases where
    low wing loading creates more wing area, which then adds enough structure
    mass to push the required area upward again.
    """

    _require_finite_positive(wing_loading_target_Npm2, "wing_loading_target_Npm2")
    _require_finite_positive(pilot_mass_kg, "pilot_mass_kg")
    _require_finite_positive(
        fixed_non_area_aircraft_mass_kg,
        "fixed_non_area_aircraft_mass_kg",
    )
    _require_finite_non_negative(wing_areal_density_kgpm2, "wing_areal_density_kgpm2")
    _require_finite_non_negative(tube_system_mass_kg, "tube_system_mass_kg")
    _require_finite_non_negative(wing_fittings_base_kg, "wing_fittings_base_kg")
    _require_finite_non_negative(wire_terminal_mass_kg, "wire_terminal_mass_kg")
    _require_finite_non_negative(extra_system_margin_kg, "extra_system_margin_kg")
    _require_finite_positive(tolerance_m2, "tolerance_m2")
    _require_finite_positive(float(max_iterations), "max_iterations")
    _require_finite_positive(gravity_mps2, "gravity_mps2")

    fixed_mass_kg = (
        float(pilot_mass_kg)
        + float(fixed_non_area_aircraft_mass_kg)
        + float(tube_system_mass_kg)
        + float(wing_fittings_base_kg)
        + float(wire_terminal_mass_kg)
        + float(extra_system_margin_kg)
    )
    denominator = float(wing_loading_target_Npm2) - float(wing_areal_density_kgpm2) * float(
        gravity_mps2
    )
    if denominator <= 0.0:
        raise ValueError(
            "wing_loading_target_Npm2 must exceed wing_areal_density_kgpm2 * gravity_mps2"
        )

    wing_area_m2 = (
        fixed_mass_kg * float(gravity_mps2) / float(wing_loading_target_Npm2)
        if initial_wing_area_m2 is None
        else float(initial_wing_area_m2)
    )
    _require_finite_positive(wing_area_m2, "initial_wing_area_m2")

    converged = False
    iteration = 0
    next_area_m2 = wing_area_m2
    for iteration in range(1, int(max_iterations) + 1):
        wing_area_dependent_mass_kg = float(wing_areal_density_kgpm2) * wing_area_m2
        gross_mass_kg = fixed_mass_kg + wing_area_dependent_mass_kg
        next_area_m2 = gross_mass_kg * float(gravity_mps2) / float(wing_loading_target_Npm2)
        if abs(next_area_m2 - wing_area_m2) <= float(tolerance_m2):
            converged = True
            wing_area_m2 = next_area_m2
            break
        wing_area_m2 = next_area_m2

    wing_area_dependent_mass_kg = float(wing_areal_density_kgpm2) * wing_area_m2
    gross_mass_kg = fixed_mass_kg + wing_area_dependent_mass_kg
    closed_wing_area_m2 = gross_mass_kg * float(gravity_mps2) / float(
        wing_loading_target_Npm2
    )
    residual_m2 = closed_wing_area_m2 - wing_area_m2

    return AreaMassClosureResult(
        wing_loading_target_Npm2=float(wing_loading_target_Npm2),
        closed_wing_area_m2=float(closed_wing_area_m2),
        closed_gross_mass_kg=float(gross_mass_kg),
        fixed_mass_kg=float(fixed_mass_kg),
        wing_area_dependent_mass_kg=float(wing_area_dependent_mass_kg),
        mass_breakdown_kg={
            "pilot_kg": float(pilot_mass_kg),
            "fixed_non_area_aircraft_kg": float(fixed_non_area_aircraft_mass_kg),
            "tube_system_kg": float(tube_system_mass_kg),
            "wing_fittings_base_kg": float(wing_fittings_base_kg),
            "wire_terminal_kg": float(wire_terminal_mass_kg),
            "extra_system_margin_kg": float(extra_system_margin_kg),
            "wing_area_dependent_kg": float(wing_area_dependent_mass_kg),
        },
        area_residual_m2=float(residual_m2),
        iterations=int(iteration),
        converged=bool(converged and abs(residual_m2) <= float(tolerance_m2)),
    )


def _require_finite_positive(value: float, field_name: str) -> None:
    if not math.isfinite(float(value)) or float(value) <= 0.0:
        raise ValueError(f"{field_name} must be finite and > 0")


def _require_finite_non_negative(value: float, field_name: str) -> None:
    if not math.isfinite(float(value)) or float(value) < 0.0:
        raise ValueError(f"{field_name} must be finite and >= 0")
