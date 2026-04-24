"""Report-only area/mass closure helpers for upstream HPA concept sizing."""

from __future__ import annotations

import math
from dataclasses import dataclass


_STANDARD_GRAVITY_MPS2 = 9.80665


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


def close_area_mass(
    *,
    wing_loading_target_Npm2: float,
    pilot_mass_kg: float,
    fixed_non_area_aircraft_mass_kg: float,
    wing_areal_density_kgpm2: float = 0.22,
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
    _require_finite_non_negative(extra_system_margin_kg, "extra_system_margin_kg")
    _require_finite_positive(tolerance_m2, "tolerance_m2")
    _require_finite_positive(float(max_iterations), "max_iterations")
    _require_finite_positive(gravity_mps2, "gravity_mps2")

    fixed_mass_kg = (
        float(pilot_mass_kg)
        + float(fixed_non_area_aircraft_mass_kg)
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
