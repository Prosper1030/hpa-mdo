"""MIT-like high-AR Birdman Stage-1 candidate generator.

The previous Stage-1 pipeline maximised AVL e_CDi with an inverse-chord
geometry plus a smooth outer chord bump.  After the closed-loop
sweep showed that bump cannot fully close the outer-underloaded gap
without an airfoil-aware redesign, the chief engineer redirected
Stage-1 to:

* generate "MIT-like" high-AR sensible-taper candidates
  (AR 37-40, tip/root in 0.30-0.40, no chord bump),
* feed each candidate through the existing
  ``hpa_mdo.concept.avl_loader.load_zone_requirements_from_avl`` path
  (AVL no-airfoil → per-zone cl_target + Re),
* run XFOIL/CST per zone and re-run AVL with the selected airfoils,
* keep candidates even if the first-round e_CDi is low; only judge after
  the post-airfoil AVL pass.

This module hosts the candidate generator.  The closed-loop driver
lives in ``scripts/birdman_mit_like_closed_loop_search.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import math
import numpy as np
from scipy.stats import qmc

from hpa_mdo.concept.config import BirdmanConceptConfig
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    build_segment_plan,
)


DEFAULT_AR_RANGE: tuple[float, float] = (37.0, 40.0)
DEFAULT_TAPER_RATIO_RANGE: tuple[float, float] = (0.30, 0.40)
DEFAULT_SPAN_RANGE_M: tuple[float, float] = (32.0, 35.0)
DEFAULT_TIP_CHORD_FLOOR_M: float = 0.42

DEFAULT_TWIST_CONTROL_ETAS: tuple[float, float, float, float] = (0.0, 0.35, 0.70, 1.0)
DEFAULT_TWIST_SCHEDULE_DEG: tuple[float, float, float, float] = (2.0, 0.5, -0.5, -2.0)


@dataclass(frozen=True)
class MITLikeCandidate:
    """Container for a generated high-AR sensible-taper concept."""

    sample_index: int
    span_m: float
    aspect_ratio: float
    taper_ratio: float
    wing_area_m2: float
    root_chord_m: float
    tip_chord_m: float
    twist_control_points: tuple[tuple[float, float], ...]
    concept: GeometryConcept

    def to_summary(self) -> dict[str, Any]:
        return {
            "sample_index": int(self.sample_index),
            "span_m": float(self.span_m),
            "aspect_ratio": float(self.aspect_ratio),
            "taper_ratio": float(self.taper_ratio),
            "wing_area_m2": float(self.wing_area_m2),
            "root_chord_m": float(self.root_chord_m),
            "tip_chord_m": float(self.tip_chord_m),
            "mean_chord_m": float(self.wing_area_m2 / max(self.span_m, 1.0e-9)),
            "twist_control_points": [
                [float(eta), float(twist)] for eta, twist in self.twist_control_points
            ],
            "outer_chord_bump_amp": 0.0,
        }


def generate_mit_like_candidates(
    *,
    cfg: BirdmanConceptConfig,
    sample_count: int,
    ar_range: tuple[float, float] = DEFAULT_AR_RANGE,
    taper_range: tuple[float, float] = DEFAULT_TAPER_RATIO_RANGE,
    span_range_m: tuple[float, float] = DEFAULT_SPAN_RANGE_M,
    twist_control_etas: tuple[float, float, float, float] = DEFAULT_TWIST_CONTROL_ETAS,
    twist_schedule_deg: tuple[float, float, float, float] = DEFAULT_TWIST_SCHEDULE_DEG,
    tip_chord_floor_m: float = DEFAULT_TIP_CHORD_FLOOR_M,
    seed: int = 20260503,
) -> list[MITLikeCandidate]:
    """Generate ``sample_count`` MIT-like candidates as plain trapezoidal
    high-AR planforms.

    The sampler is a 3-dim Sobol over (span, AR, taper).  Each sample
    becomes a :class:`GeometryConcept` with:

    * ``planform_parameterization = "spanload_inverse_chord"`` so the
      ``GeometryConcept`` tolerance check ignores the trapezoidal-area
      identity (we still set ``wing_area_m2`` to ``span * mean_chord``
      explicitly, so AR matches what the sampler asked for).
    * a fixed monotone-washout twist schedule ``twist_schedule_deg``
      anchored at ``twist_control_etas`` (no Stage-0 twist optimization).
    * **no outer chord bump** — the chord profile is exactly trapezoidal.

    Candidates that violate ``cfg.geometry_family.hard_constraints``
    (root chord, tip chord, AR/area envelopes, dynamic taper from
    tip-chord protection) are dropped; the caller receives only
    physically realisable concepts.
    """

    if sample_count <= 0:
        return []
    if ar_range[0] <= 0 or ar_range[1] <= ar_range[0]:
        raise ValueError("ar_range must be a positive ascending pair.")
    if taper_range[0] <= 0 or taper_range[1] <= taper_range[0]:
        raise ValueError("taper_range must be a positive ascending pair.")
    if span_range_m[0] <= 0 or span_range_m[1] <= span_range_m[0]:
        raise ValueError("span_range_m must be a positive ascending pair.")
    if (
        len(twist_control_etas) != 4
        or twist_control_etas[0] != 0.0
        or twist_control_etas[-1] != 1.0
    ):
        raise ValueError("twist_control_etas must be 4 values starting at 0 and ending at 1.")
    if any(
        later[0] <= earlier[0]
        for earlier, later in zip(
            zip(twist_control_etas, twist_schedule_deg, strict=True),
            zip(twist_control_etas[1:], twist_schedule_deg[1:], strict=True),
        )
    ):
        raise ValueError("twist_control_etas must be strictly increasing.")
    if any(
        later > earlier + 1.0e-9
        for earlier, later in zip(twist_schedule_deg[:-1], twist_schedule_deg[1:])
    ):
        raise ValueError(
            "twist_schedule_deg must be monotone (washout) — no wash-in tolerated."
        )

    exponent = max(1, int(math.ceil(math.log2(sample_count))))
    sampler = qmc.Sobol(d=3, seed=int(seed), scramble=True)
    units = sampler.random_base2(m=exponent)[:sample_count]

    constraints = cfg.geometry_family.hard_constraints
    tip_protection = cfg.geometry_family.planform_tip_protection

    candidates: list[MITLikeCandidate] = []
    for index, unit in enumerate(units, start=1):
        span = float(span_range_m[0] + (span_range_m[1] - span_range_m[0]) * float(unit[0]))
        aspect_ratio = float(ar_range[0] + (ar_range[1] - ar_range[0]) * float(unit[1]))
        taper = float(taper_range[0] + (taper_range[1] - taper_range[0]) * float(unit[2]))

        mean_chord = float(span / max(aspect_ratio, 1.0e-9))
        wing_area = float(span * mean_chord)
        root_chord = float(2.0 * mean_chord / max(1.0 + taper, 1.0e-9))
        tip_chord = float(root_chord * taper)

        if root_chord < float(constraints.root_chord_min_m):
            continue
        if tip_chord < float(tip_chord_floor_m):
            continue
        if tip_chord < float(constraints.tip_chord_min_m):
            continue
        if bool(tip_protection.enabled) and tip_chord < float(
            tip_protection.tip_chord_abs_min_m
        ):
            continue
        if wing_area < float(constraints.wing_area_m2_range.min):
            continue
        if wing_area > float(constraints.wing_area_m2_range.max):
            continue

        half_span_m = 0.5 * span
        try:
            segment_lengths_m = build_segment_plan(
                half_span_m=half_span_m,
                min_segment_length_m=float(cfg.segmentation.min_segment_length_m),
                max_segment_length_m=float(cfg.segmentation.max_segment_length_m),
            )
        except ValueError:
            continue

        twist_control_points = tuple(
            (float(eta), float(twist))
            for eta, twist in zip(twist_control_etas, twist_schedule_deg, strict=True)
        )
        try:
            concept = GeometryConcept(
                span_m=float(span),
                wing_area_m2=float(wing_area),
                root_chord_m=float(root_chord),
                tip_chord_m=float(tip_chord),
                twist_root_deg=float(twist_schedule_deg[0]),
                twist_tip_deg=float(twist_schedule_deg[-1]),
                twist_control_points=twist_control_points,
                tail_area_m2=float(cfg.geometry_family.tail_area_candidates_m2[0]),
                cg_xc=float(cfg.geometry_family.cg_xc),
                segment_lengths_m=segment_lengths_m,
                spanload_a3_over_a1=-0.05,
                spanload_a5_over_a1=0.0,
                wing_loading_target_Npm2=float(
                    cfg.design_gross_weight_n / max(wing_area, 1.0e-9)
                ),
                mean_chord_target_m=float(mean_chord),
                wing_area_is_derived=True,
                planform_parameterization="spanload_inverse_chord",
                design_gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
                dihedral_root_deg=0.0,
                dihedral_tip_deg=6.0,
                dihedral_exponent=1.5,
            )
        except ValueError:
            continue

        candidates.append(
            MITLikeCandidate(
                sample_index=int(index),
                span_m=float(span),
                aspect_ratio=float(aspect_ratio),
                taper_ratio=float(taper),
                wing_area_m2=float(wing_area),
                root_chord_m=float(root_chord),
                tip_chord_m=float(tip_chord),
                twist_control_points=twist_control_points,
                concept=concept,
            )
        )
    return candidates


def stations_for_mit_like_candidate(
    *,
    candidate: MITLikeCandidate,
    stations_per_half: int,
) -> tuple:
    """Linear chord + monotone washout stations from a candidate.

    Helper that returns plain trapezoidal stations rather than going
    through the linear ``build_linear_wing_stations`` (which sometimes
    rebuilds the segment plan).  The closed-loop driver uses this so
    the chord profile is exactly what the candidate generator promised.
    """

    from hpa_mdo.concept.geometry import WingStation

    half_span_m = 0.5 * float(candidate.span_m)
    if stations_per_half < 2:
        raise ValueError("stations_per_half must be >= 2.")

    etas = np.linspace(0.0, 1.0, int(stations_per_half))
    chord_root = float(candidate.root_chord_m)
    chord_tip = float(candidate.tip_chord_m)
    twist_etas = np.asarray(
        [eta for eta, _ in candidate.twist_control_points], dtype=float
    )
    twist_values = np.asarray(
        [twist for _, twist in candidate.twist_control_points], dtype=float
    )
    stations = []
    for eta in etas:
        eta_clamped = float(min(max(eta, 0.0), 1.0))
        chord_m = float(chord_root + (chord_tip - chord_root) * eta_clamped)
        twist_deg = float(np.interp(eta_clamped, twist_etas, twist_values))
        dihedral_deg = float(
            candidate.concept.dihedral_root_deg
            + (candidate.concept.dihedral_tip_deg - candidate.concept.dihedral_root_deg)
            * eta_clamped**float(candidate.concept.dihedral_exponent)
        )
        stations.append(
            WingStation(
                y_m=float(eta_clamped * half_span_m),
                chord_m=chord_m,
                twist_deg=twist_deg,
                dihedral_deg=dihedral_deg,
            )
        )
    return tuple(stations)
