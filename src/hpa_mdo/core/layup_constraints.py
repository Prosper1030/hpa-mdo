"""Low-level layup manufacturability constraints shared across optimizers."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from hpa_mdo.core.config import SparConfig
from hpa_mdo.core.materials import MaterialDB


def effective_layup_thickness_step_limit(
    spar_cfg: SparConfig,
    solver_max_step_m: float,
    materials_db: MaterialDB,
) -> float:
    """Return the optimizer thickness-step cap after optional ply-drop tightening."""
    base_limit = float(solver_max_step_m)
    if getattr(spar_cfg, "layup_mode", "isotropic") != "discrete_clt":
        return base_limit
    ply_material_key = getattr(spar_cfg, "ply_material", None)
    if ply_material_key is None:
        raise ValueError("Spar layup_mode='discrete_clt' requires ply_material.")

    ply_mat = materials_db.get_ply(str(ply_material_key))
    ply_drop_limit = int(getattr(spar_cfg, "max_ply_drop_per_segment", 2))
    return min(base_limit, ply_drop_limit * float(ply_mat.t_ply))


def thickness_step_margin_min(thicknesses_m: Sequence[float], max_step_m: float) -> float:
    """Return minimum adjacent thickness-step margin for an optimizer constraint."""
    thicknesses = np.asarray(thicknesses_m, dtype=float)
    if thicknesses.size <= 1:
        return float("inf")
    if not np.all(np.isfinite(thicknesses)):
        return float("-inf")
    return float(max_step_m) - float(np.max(np.abs(np.diff(thicknesses))))
