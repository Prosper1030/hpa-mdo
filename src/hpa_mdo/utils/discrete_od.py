"""Discrete outer-diameter post-processing for commercial tube catalogs.

Snaps continuous optimizer OD outputs to nearest available commercial
OD, always rounding up for conservative structural sizing.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List

import numpy as np
import yaml

_FLOAT_TOL = 1e-9


def load_tube_catalog(catalog_path: Path) -> List[float]:
    """Load available ODs from YAML and return sorted values in metres."""
    with open(catalog_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    od_mm = sorted(float(od) for od in data["carbon_tube_od_mm"])
    return [od / 1000.0 for od in od_mm]


def snap_to_catalog(od_continuous_m: float, catalog_m: List[float]) -> float:
    """Return the smallest catalog OD >= od_continuous_m.

    When od_continuous_m is larger than the largest available catalog OD,
    raise ValueError because a conservative snap-up is impossible.
    """
    if not catalog_m:
        raise ValueError("catalog_m must not be empty.")

    for od in catalog_m:
        if od >= od_continuous_m - _FLOAT_TOL:
            return od

    max_od = catalog_m[-1]
    raise ValueError(
        "Requested OD "
        f"{od_continuous_m * 1000.0:.4f} mm exceeds catalog max {max_od * 1000.0:.4f} mm; "
        "conservative snap-up is impossible with the current catalog."
    )


def apply_discrete_od(result, catalog_m: List[float]) -> object:
    """Return a new OptimizationResult-like object with ODs snapped to catalog.

    This function is a post-processing helper and does not re-run structural
    verification. Mass is re-estimated from OD scaling and marked as unverified.
    """
    if not catalog_m:
        raise ValueError("catalog_m must not be empty.")

    main_r_mm_cont = np.asarray(result.main_r_seg_mm, dtype=float)
    main_od_mm_cont = 2.0 * main_r_mm_cont
    main_od_mm_snap = np.asarray(
        [snap_to_catalog(od_mm / 1000.0, catalog_m) * 1000.0 for od_mm in main_od_mm_cont],
        dtype=float,
    )
    main_r_mm_snap = main_od_mm_snap / 2.0

    rear_r_mm_snap = None
    rear_scale = 1.0
    if result.rear_r_seg_mm is not None:
        rear_r_mm_cont = np.asarray(result.rear_r_seg_mm, dtype=float)
        rear_od_mm_cont = 2.0 * rear_r_mm_cont
        rear_od_mm_snap = np.asarray(
            [snap_to_catalog(od_mm / 1000.0, catalog_m) * 1000.0 for od_mm in rear_od_mm_cont],
            dtype=float,
        )
        rear_r_mm_snap = rear_od_mm_snap / 2.0
        rear_scale = float(np.mean(rear_od_mm_snap / (rear_od_mm_cont + 1e-30)))

    main_scale = float(np.mean(main_od_mm_snap / (main_od_mm_cont + 1e-30)))
    combined_scale = 0.6 * main_scale + 0.4 * rear_scale
    estimated_mass = result.total_mass_full_kg * combined_scale

    return replace(
        result,
        main_r_seg_mm=main_r_mm_snap,
        rear_r_seg_mm=rear_r_mm_snap,
        total_mass_full_kg=estimated_mass,
        spar_mass_full_kg=result.spar_mass_full_kg * combined_scale,
        spar_mass_half_kg=result.spar_mass_half_kg * combined_scale,
        success=False,
        message=(
            "[DISCRETE OD APPLIED — re-verify] "
            f"Main OD: {main_od_mm_cont.mean():.1f}mm -> {main_od_mm_snap.mean():.1f}mm avg. "
            f"Mass estimate: {estimated_mass:.2f} kg (proportional, unverified)."
        ),
    )
