from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hpa_mdo.concept.config import LiftWireGateConfig, TubeSystemGeometryConfig


_GRAVITY_M_PER_S2 = 9.80665


def estimate_lift_wire_tension_n(
    *,
    gross_mass_kg: float,
    tube_geom: "TubeSystemGeometryConfig",
    gate_cfg: "LiftWireGateConfig",
) -> float:
    """Return estimated lift-wire tension at limit load, in newtons.

    Coarse single-wire-per-wing model:

        T = (m·g / N_wings) × load_factor × wing_lift_fraction_carried

    The fraction parameter folds in the inboard moment-arm geometry,
    reasonable wire-angle inefficiency, and the share of wing lift the
    upper wire reacts in steady level flight. For HPA piano-wire /
    Dyneema rigging, default 0.75 with limit_load_factor=1.75 puts a
    typical 105 kg / 2-wing aircraft around 680 N — comfortably below
    a 5 kN allowable.
    """
    num_wings = max(1, int(tube_geom.num_wings))
    weight_per_wing_n = float(gross_mass_kg) * _GRAVITY_M_PER_S2 / float(num_wings)
    return (
        weight_per_wing_n
        * float(gate_cfg.limit_load_factor)
        * float(gate_cfg.wing_lift_fraction_carried)
    )


__all__ = ["estimate_lift_wire_tension_n"]
