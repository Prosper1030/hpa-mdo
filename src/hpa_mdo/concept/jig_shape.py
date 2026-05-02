from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hpa_mdo.concept.config import (
        JigShapeGateConfig,
        TubeSystemGeometryConfig,
    )


_GRAVITY_M_PER_S2 = 9.80665


@dataclass(frozen=True)
class TipDeflectionEstimate:
    tip_deflection_m: float
    tip_deflection_ratio: float
    effective_dihedral_deg: float
    unbraced_tip_deflection_m: float
    lift_wire_relief_deflection_m: float
    lift_wire_attach_span_fraction: float
    lift_wire_cruise_lift_fraction_carried: float


def estimate_tip_deflection(
    *,
    gross_mass_kg: float,
    span_m: float,
    tube_geom: "TubeSystemGeometryConfig",
    gate_cfg: "JigShapeGateConfig",
) -> TipDeflectionEstimate:
    """Return a concept-stage wire-relieved cruise tip-deflection estimate.

    This remains a first-order beam proxy, but unlike the older bare
    cantilever ratio it can represent the dominant HPA engineering effect:
    a lift wire reacting part of the cruise lift at an outboard attachment.
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
        return TipDeflectionEstimate(
            tip_deflection_m=float("inf"),
            tip_deflection_ratio=float("inf"),
            effective_dihedral_deg=90.0,
            unbraced_tip_deflection_m=float("inf"),
            lift_wire_relief_deflection_m=0.0,
            lift_wire_attach_span_fraction=float(gate_cfg.lift_wire_attach_span_fraction),
            lift_wire_cruise_lift_fraction_carried=float(
                gate_cfg.lift_wire_cruise_lift_fraction_carried
            ),
        )

    taper_factor = float(gate_cfg.deflection_taper_correction_factor)
    unbraced_tip_deflection_m = (
        distributed_load_n_per_m
        * half_span_m**4
        / (8.0 * bending_stiffness_per_wing_nm2)
        * taper_factor
    )

    lift_wire_relief_deflection_m = 0.0
    lift_wire_fraction = float(gate_cfg.lift_wire_cruise_lift_fraction_carried)
    lift_wire_eta = float(gate_cfg.lift_wire_attach_span_fraction)
    if bool(gate_cfg.lift_wire_relief_enabled) and lift_wire_fraction > 0.0:
        attach_m = lift_wire_eta * half_span_m
        support_reaction_n = lift_wire_fraction * distributed_load_n_per_m * half_span_m
        lift_wire_relief_deflection_m = (
            support_reaction_n
            * attach_m**2
            * (3.0 * half_span_m - attach_m)
            / (6.0 * bending_stiffness_per_wing_nm2)
            * taper_factor
        )

    tip_deflection_m = max(0.0, unbraced_tip_deflection_m - lift_wire_relief_deflection_m)
    tip_deflection_ratio = tip_deflection_m / half_span_m
    effective_dihedral_deg = math.degrees(math.atan2(tip_deflection_m, half_span_m))
    return TipDeflectionEstimate(
        tip_deflection_m=tip_deflection_m,
        tip_deflection_ratio=tip_deflection_ratio,
        effective_dihedral_deg=effective_dihedral_deg,
        unbraced_tip_deflection_m=unbraced_tip_deflection_m,
        lift_wire_relief_deflection_m=lift_wire_relief_deflection_m,
        lift_wire_attach_span_fraction=lift_wire_eta,
        lift_wire_cruise_lift_fraction_carried=lift_wire_fraction,
    )


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
    return estimate_tip_deflection(
        gross_mass_kg=gross_mass_kg,
        span_m=span_m,
        tube_geom=tube_geom,
        gate_cfg=gate_cfg,
    ).tip_deflection_ratio
