from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hpa_mdo.concept.config import (
        JigShapeGateConfig,
        TubeSystemGeometryConfig,
    )


_GRAVITY_M_PER_S2 = 9.80665


def estimate_tip_deflection_ratio(
    *,
    gross_mass_kg: float,
    span_m: float,
    tube_geom: "TubeSystemGeometryConfig",
    gate_cfg: "JigShapeGateConfig",
) -> float:
    """Return tip deflection / half-span at 1g uniform spanwise loading.

    Treats each wing as a uniform-load cantilever of length b/2 carrying
    half the gross weight. Bending stiffness EI is taken at the root
    section using a thin-wall tube model with optional parallel-axis
    contribution from a vertical spar separation. A configurable
    multiplicative correction approximates the deflection penalty from
    the OD/wall taper toward the tip.
    """
    half_span_m = 0.5 * float(span_m)
    if half_span_m <= 0.0:
        raise ValueError("span_m must be positive.")

    weight_n = float(gross_mass_kg) * _GRAVITY_M_PER_S2
    num_wings = max(1, int(tube_geom.num_wings))
    num_spars_per_wing = max(1, int(tube_geom.num_spars_per_wing))
    distributed_load_n_per_m = weight_n / (num_wings * half_span_m)

    diameter_root_m = float(tube_geom.root_outer_diameter_m)
    wall_root_m = float(tube_geom.root_wall_thickness_m)
    inertia_per_tube_m4 = math.pi * diameter_root_m**3 * wall_root_m / 8.0
    area_per_tube_m2 = math.pi * diameter_root_m * wall_root_m

    separation_m = float(gate_cfg.spar_vertical_separation_m)
    if num_spars_per_wing >= 2 and separation_m > 0.0:
        offset_m = 0.5 * separation_m
        parallel_axis_term_m4 = num_spars_per_wing * area_per_tube_m2 * offset_m**2
    else:
        parallel_axis_term_m4 = 0.0
    inertia_per_wing_m4 = num_spars_per_wing * inertia_per_tube_m4 + parallel_axis_term_m4

    youngs_pa = float(gate_cfg.spar_youngs_modulus_pa)
    bending_stiffness_per_wing_nm2 = youngs_pa * inertia_per_wing_m4
    if bending_stiffness_per_wing_nm2 <= 0.0:
        return float("inf")

    deflection_uniform_m = (
        distributed_load_n_per_m
        * half_span_m**4
        / (8.0 * bending_stiffness_per_wing_nm2)
    )
    deflection_with_taper_m = deflection_uniform_m * float(
        gate_cfg.deflection_taper_correction_factor
    )
    return deflection_with_taper_m / half_span_m
