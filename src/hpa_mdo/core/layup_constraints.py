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
    ply_material_key = getattr(spar_cfg, "ply_material", None)
    if ply_material_key is None:
        if getattr(spar_cfg, "layup_mode", "isotropic") == "discrete_clt":
            raise ValueError("Spar layup_mode='discrete_clt' requires ply_material.")
        return base_limit

    ply_mat = materials_db.get_ply(str(ply_material_key))
    ply_step_limit = int(getattr(spar_cfg, "max_ply_drop_per_segment", 1))
    return min(base_limit, symmetric_half_layup_step_limit_m(ply_step_limit, ply_mat.t_ply))


def thickness_step_margin_min(thicknesses_m: Sequence[float], max_step_m: float) -> float:
    """Return minimum adjacent thickness-step margin for an optimizer constraint."""
    thicknesses = np.asarray(thicknesses_m, dtype=float)
    if thicknesses.size <= 1:
        return float("inf")
    if not np.all(np.isfinite(thicknesses)):
        return float("-inf")
    return float(max_step_m) - float(np.max(np.abs(np.diff(thicknesses))))


def symmetric_half_layup_step_limit_m(max_half_layup_ply_step: int, t_ply_m: float) -> float:
    """Return wall-thickness step for a symmetric laminate half-layup ply step.

    A one-ply change in the half-layup appears on both sides of the symmetry
    plane, so the physical wall-thickness change is two ply thicknesses.
    """
    return 2.0 * float(max(int(max_half_layup_ply_step), 0)) * float(t_ply_m)


def continuous_ply_count_step_margin_min(
    thicknesses_m: Sequence[float],
    spar_cfg: SparConfig,
    materials_db: MaterialDB,
) -> float:
    """Return adjacent half-layup ply-count margin implied by wall thicknesses."""
    ply_material_key = getattr(spar_cfg, "ply_material", None)
    if ply_material_key is None:
        if getattr(spar_cfg, "layup_mode", "isotropic") == "discrete_clt":
            raise ValueError("Spar layup_mode='discrete_clt' requires ply_material.")
        return float("inf")
    ply_mat = materials_db.get_ply(str(ply_material_key))
    step_unit = 2.0 * float(ply_mat.t_ply)
    if step_unit <= 0.0:
        return float("-inf")
    half_layup_counts = np.asarray(thicknesses_m, dtype=float) / step_unit
    return ply_count_step_margin_min(
        half_layup_counts,
        int(getattr(spar_cfg, "max_ply_drop_per_segment", 1)),
    )


def ply_count_step_margin_min(
    half_layup_ply_counts: Sequence[float],
    max_half_layup_ply_step: int,
) -> float:
    """Return margin for adjacent half-layup ply-count changes."""
    counts = np.asarray(half_layup_ply_counts, dtype=float)
    if counts.size <= 1:
        return float("inf")
    if not np.all(np.isfinite(counts)):
        return float("-inf")
    return float(max(int(max_half_layup_ply_step), 0)) - float(
        np.max(np.abs(np.diff(counts)))
    )


def ply_run_length_margin_min(
    half_layup_ply_counts: Sequence[float],
    segment_lengths_m: Sequence[float],
    min_run_length_m: float,
) -> float:
    """Return minimum constant-ply run-length margin.

    Consecutive segments with the same half-layup ply count form one run.
    The margin is ``run_length - min_run_length_m`` for the shortest run.
    """
    min_run = float(min_run_length_m)
    if min_run <= 0.0:
        return float("inf")
    counts = np.asarray(half_layup_ply_counts, dtype=float)
    lengths = np.asarray(segment_lengths_m, dtype=float)
    if counts.size != lengths.size:
        raise ValueError("half_layup_ply_counts and segment_lengths_m must have the same length.")
    if counts.size == 0:
        return float("inf")
    if not np.all(np.isfinite(counts)) or not np.all(np.isfinite(lengths)):
        return float("-inf")

    min_margin = float("inf")
    run_count = counts[0]
    run_length = 0.0
    for count, length in zip(counts, lengths, strict=True):
        if count != run_count:
            min_margin = min(min_margin, run_length - min_run)
            run_count = count
            run_length = 0.0
        run_length += float(length)
    min_margin = min(min_margin, run_length - min_run)
    return float(min_margin)
