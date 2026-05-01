from __future__ import annotations

import math
from typing import Any, Mapping


DEFAULT_BLACKCAT_MAIN_WING_REFERENCE = {
    "velocity_mps": 6.5,
    "density_kgpm3": 1.225,
    "dynamic_viscosity_pas": 1.7894e-5,
    "sref_full_m2": 35.175,
    "sref_half_m2": 17.5875,
    "cref_m": 1.130189765,
    "bref_full_m": 33.0,
    "root_chord_m": 1.30,
    "tip_chord_m": 0.435,
}


DEFAULT_GRID_INDEPENDENCE_RELATIVE_TOLERANCES = {
    "cl": 0.03,
    "cd": 0.05,
    "cmy": 0.05,
}


def reynolds_number(
    *,
    density_kgpm3: float,
    velocity_mps: float,
    length_m: float,
    dynamic_viscosity_pas: float,
) -> float:
    if density_kgpm3 <= 0.0:
        raise ValueError("density_kgpm3 must be positive")
    if velocity_mps <= 0.0:
        raise ValueError("velocity_mps must be positive")
    if length_m <= 0.0:
        raise ValueError("length_m must be positive")
    if dynamic_viscosity_pas <= 0.0:
        raise ValueError("dynamic_viscosity_pas must be positive")
    return float(density_kgpm3 * velocity_mps * length_m / dynamic_viscosity_pas)


def flat_plate_cf_estimates(reynolds_number_value: float) -> dict[str, float]:
    if reynolds_number_value <= 1.0:
        raise ValueError("reynolds_number_value must be larger than 1")
    return {
        "laminar_blasius": float(0.664 / math.sqrt(reynolds_number_value)),
        "turbulent_schlichting": float(0.0592 / reynolds_number_value**0.2),
    }


def first_cell_height_for_yplus(
    *,
    target_yplus: float,
    density_kgpm3: float,
    velocity_mps: float,
    dynamic_viscosity_pas: float,
    reference_length_m: float,
    cf_model: str = "turbulent_schlichting",
) -> dict[str, float]:
    if target_yplus <= 0.0:
        raise ValueError("target_yplus must be positive")
    re_value = reynolds_number(
        density_kgpm3=density_kgpm3,
        velocity_mps=velocity_mps,
        length_m=reference_length_m,
        dynamic_viscosity_pas=dynamic_viscosity_pas,
    )
    cf_estimates = flat_plate_cf_estimates(re_value)
    if cf_model not in cf_estimates:
        raise ValueError(f"unsupported cf_model: {cf_model}")
    wall_shear = 0.5 * density_kgpm3 * velocity_mps**2 * cf_estimates[cf_model]
    friction_velocity = math.sqrt(wall_shear / density_kgpm3)
    height = target_yplus * dynamic_viscosity_pas / (density_kgpm3 * friction_velocity)
    return {
        "target_yplus": float(target_yplus),
        "first_cell_height_m": float(height),
        "reynolds_number": float(re_value),
        "cf": float(cf_estimates[cf_model]),
        "friction_velocity_mps": float(friction_velocity),
        "cf_model": cf_model,
    }


def geometric_boundary_layer_total_thickness(
    *,
    first_layer_height_m: float,
    layers: int,
    growth_ratio: float,
) -> float:
    if first_layer_height_m <= 0.0:
        raise ValueError("first_layer_height_m must be positive")
    if layers <= 0:
        raise ValueError("layers must be positive")
    if growth_ratio <= 1.0:
        raise ValueError("growth_ratio must be greater than 1")
    return float(first_layer_height_m * (growth_ratio**layers - 1.0) / (growth_ratio - 1.0))


def hpa_main_wing_cfd_advisory(
    reference: Mapping[str, float] | None = None,
    *,
    ram_cap_gb: float = 12.0,
) -> dict[str, Any]:
    ref = dict(DEFAULT_BLACKCAT_MAIN_WING_REFERENCE)
    if reference:
        ref.update({key: float(value) for key, value in reference.items()})
    if ram_cap_gb <= 0.0:
        raise ValueError("ram_cap_gb must be positive")

    velocity = float(ref["velocity_mps"])
    density = float(ref["density_kgpm3"])
    mu = float(ref["dynamic_viscosity_pas"])
    chord_refs = {
        "tip": float(ref["tip_chord_m"]),
        "mean_aerodynamic_chord": float(ref["cref_m"]),
        "root": float(ref["root_chord_m"]),
    }
    reynolds = {
        name: reynolds_number(
            density_kgpm3=density,
            velocity_mps=velocity,
            length_m=length,
            dynamic_viscosity_pas=mu,
        )
        for name, length in chord_refs.items()
    }
    yplus_targets = {
        "wall_resolved_yplus_1": first_cell_height_for_yplus(
            target_yplus=1.0,
            density_kgpm3=density,
            velocity_mps=velocity,
            dynamic_viscosity_pas=mu,
            reference_length_m=float(ref["cref_m"]),
        ),
        "wall_resolved_yplus_5": first_cell_height_for_yplus(
            target_yplus=5.0,
            density_kgpm3=density,
            velocity_mps=velocity,
            dynamic_viscosity_pas=mu,
            reference_length_m=float(ref["cref_m"]),
        ),
    }
    baseline_first_layer = 5.0e-5
    baseline_layers = 24
    baseline_growth = 1.24
    return {
        "reference": ref,
        "flow_regime": {
            "mach_estimate": velocity / 340.3,
            "reynolds_by_chord": reynolds,
            "engineering_class": "low_mach_low_reynolds_human_powered_aircraft",
        },
        "boundary_layer_targets": {
            "first_cell_height": yplus_targets,
            "recommended_wall_resolved_first_layer_height_m": baseline_first_layer,
            "recommended_layers": baseline_layers,
            "recommended_growth_ratio": baseline_growth,
            "recommended_total_thickness_m": geometric_boundary_layer_total_thickness(
                first_layer_height_m=baseline_first_layer,
                layers=baseline_layers,
                growth_ratio=baseline_growth,
            ),
            "note": (
                "Use wall-resolved prisms for drag work; no-BL tetra cases are solver and marker "
                "smokes, not viscous-drag evidence."
            ),
        },
        "solver_sequence": [
            {
                "stage": "mesh_readability",
                "solver": "INC_EULER",
                "wall": "MARKER_EULER",
                "purpose": "marker and volume-mesh smoke only",
            },
            {
                "stage": "laminar_debug",
                "solver": "INC_NAVIER_STOKES",
                "wall": "MARKER_HEATFLUX=(wing_wall,0)",
                "purpose": "debug no-slip setup before turbulence variables",
            },
            {
                "stage": "primary_grid_study",
                "solver": "INC_RANS",
                "turbulence_model": "SA",
                "wall": "wall-resolved no-slip, y+ about 1",
                "purpose": "first credible grid-convergence route",
            },
            {
                "stage": "secondary_physics_check",
                "solver": "INC_RANS",
                "turbulence_model": "SST or transition SST",
                "purpose": "low-Re/transition sensitivity after BL mesh is reliable",
            },
        ],
        "half_wing_mesh_ladder_targets": [
            {
                "level": "coarse",
                "target_cells": 900_000,
                "full_wing_equivalent_cells": 1_800_000,
                "role": "first physics run, not final",
            },
            {
                "level": "medium",
                "target_cells": 1_800_000,
                "full_wing_equivalent_cells": 3_600_000,
                "role": "main comparison case",
            },
            {
                "level": "fine",
                "target_cells": 3_000_000,
                "full_wing_equivalent_cells": 6_000_000,
                "role": "RAM-capped check on a 12 GB budget",
            },
        ],
        "grid_independence_policy": {
            "max_iter": 2000,
            "tail_window_iterations": 200,
            "coefficient_relative_tolerances": DEFAULT_GRID_INDEPENDENCE_RELATIVE_TOLERANCES,
            "selection": "choose the cheapest adjacent mesh pair whose CL/CD/Cm changes are inside tolerance",
        },
        "ram_cap_gb": float(ram_cap_gb),
    }
