from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hpa_mdo.concept.config import RiggingDragConfig


def compute_rigging_drag_cda_m2(rigging_cfg: "RiggingDragConfig") -> float:
    """Return parasite drag area (CdA, m^2) from external rigging wires.

    Cylinder model: CdA = Cd * d * L, where d is wire diameter, L is the total
    exposed wire length (sum across all wires), and Cd is the cylinder drag
    coefficient at the wire Reynolds number (typically ~1.0-1.2 below Re ~ 1e4).
    Returns 0.0 when the rigging block is disabled or the exposed length is 0.
    A non-None cda_override_m2 short-circuits the geometric formula so the user
    can supply a hand-tuned CdA.
    """
    if not bool(rigging_cfg.enabled):
        return 0.0
    if rigging_cfg.cda_override_m2 is not None:
        return float(rigging_cfg.cda_override_m2)
    diameter_m = float(rigging_cfg.wire_diameter_m)
    length_m = float(rigging_cfg.total_exposed_length_m)
    drag_coefficient = float(rigging_cfg.drag_coefficient)
    if diameter_m <= 0.0 or length_m <= 0.0 or drag_coefficient <= 0.0:
        return 0.0
    return drag_coefficient * diameter_m * length_m
