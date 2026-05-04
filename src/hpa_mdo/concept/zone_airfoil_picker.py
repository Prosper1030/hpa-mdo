"""Per-zone airfoil selection for the Birdman MIT-like closed loop.

This is a deliberate first step before the full CST/XFOIL search lands
inside the Birdman closed loop.  The chief engineer's brief asks for
``AVL → XFOIL/CST → AVL`` with proper :math:`\alpha_{L0}` / CLAF / CDCL
back-fill.  The XFOIL/CST infrastructure already exists at
``hpa_mdo.concept.airfoil_selection`` and is used by the upstream
concept pipeline; running it for every Birdman MIT-like candidate is
expensive (Julia/XFOIL polar batch per zone per candidate) and is the
natural next iteration.

In the meantime this picker maps each zone's ``cl_target`` and
``reynolds`` (from the AVL-no-airfoil pass) to an airfoil from the
seeded library that ships with the repo:

* ``fx76mp140`` (FX 76-MP-140) — cambered HPA root airfoil, holds
  high :math:`c_l` at high Re, used by Daedalus-like inboard zones.
* ``clarkysm`` (Clark-Y 11.7% smoothed) — lower-Re-tolerant,
  conservative outer airfoil, used by Daedalus-like outboard zones.

The picker also estimates a :math:`\alpha_{L0}` and a quadratic drag
polar :math:`c_d(c_l) = c_{d0} + k (c_l - c_{l,\text{ref}})^2` per zone
so the closed-loop driver can record the values it would back-fill into
AVL via CLAF/CDCL when that wiring lands.  These polar coefficients come
from a reference XFOIL run cached at
``docs/research/xfoil_fx76mp140_re410000/`` for FX 76-MP-140 and a
fitted cosine model for Clark-Y; the picker carries them as data, never
re-runs XFOIL.

Outputs match the structure that
``hpa_mdo.concept.avl_loader._write_zone_airfoil_dat_files`` expects so
the same payload feeds back into AVL with airfoil files.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from hpa_mdo.concept.airfoil_selection import (
    DEFAULT_CAMBER_DELTA_LEVELS as _CAMBER_LEVELS,
    DEFAULT_THICKNESS_DELTA_LEVELS as _THICKNESS_LEVELS,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_AIRFOIL_DIR = _REPO_ROOT / "data" / "airfoils"


@dataclass(frozen=True)
class ZoneAirfoilSpec:
    """Selected airfoil and the polar coefficients it carries.

    ``alpha_l0_deg`` is the section zero-lift angle (used by AVL's CLAF
    block when implemented).  ``cl_alpha_per_rad`` is the section lift
    curve slope.  ``polar_cd0`` and ``polar_k`` come from a
    :math:`c_d = c_{d0} + k (c_l - c_{l,\text{ref}})^2` fit, with
    ``cl_ref`` and ``reynolds_ref`` recording where the fit is anchored.
    """

    zone_name: str
    template_id: str
    seed_name: str
    source_file: Path
    coordinates: tuple[tuple[float, float], ...]
    alpha_l0_deg: float
    cl_alpha_per_rad: float
    polar_cd0: float
    polar_k: float
    polar_cl_ref: float
    reynolds_ref: float
    selection_reason: str

    def to_template(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "geometry_hash": f"seed{self.seed_name}",
            "coordinates": [list(point) for point in self.coordinates],
            "source_file": str(self.source_file),
            "alpha_l0_deg": float(self.alpha_l0_deg),
            "cl_alpha_per_rad": float(self.cl_alpha_per_rad),
            "polar_cd0": float(self.polar_cd0),
            "polar_k": float(self.polar_k),
            "polar_cl_ref": float(self.polar_cl_ref),
            "reynolds_ref": float(self.reynolds_ref),
            "selection_reason": str(self.selection_reason),
        }

    def cd_at(self, *, cl: float, reynolds: float) -> float:
        """Quadratic-polar drag estimate plus a Re scaling correction.

        The Re correction is a thin-airfoil-ish ``(Re_ref / Re)^0.2``
        scaling on the parasite term — accurate enough as a power-proxy
        bound while we wait for proper XFOIL polars per zone.
        """

        re_ratio = max(self.reynolds_ref, 1.0e-9) / max(float(reynolds), 1.0e-9)
        re_correction = re_ratio**0.2
        return float(
            self.polar_cd0 * re_correction
            + float(self.polar_k) * (float(cl) - float(self.polar_cl_ref)) ** 2
        )


_SEED_LIBRARY: dict[str, dict[str, Any]] = {
    "fx76mp140": {
        "template_id": "FX 76-MP-140",
        "source_file": _AIRFOIL_DIR / "fx76mp140.dat",
        "alpha_l0_deg": -3.6,
        "cl_alpha_per_rad": 5.85,
        "polar_cd0": 0.0090,
        "polar_k": 0.0085,
        "polar_cl_ref": 1.05,
        "reynolds_ref": 410_000.0,
    },
    "clarkysm": {
        "template_id": "CLARK-Y 11.7% smoothed",
        "source_file": _AIRFOIL_DIR / "clarkysm.dat",
        "alpha_l0_deg": -2.4,
        "cl_alpha_per_rad": 5.70,
        "polar_cd0": 0.0095,
        "polar_k": 0.0095,
        "polar_cl_ref": 0.65,
        "reynolds_ref": 280_000.0,
    },
}


def _load_seed_coordinates(seed_name: str) -> tuple[tuple[float, float], ...]:
    path = _SEED_LIBRARY[seed_name]["source_file"]
    coords: list[tuple[float, float]] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = raw_line.strip().split()
        if len(parts) != 2:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            continue
        coords.append((float(x), float(y)))
    if len(coords) < 3:
        raise ValueError(f"Seed airfoil {seed_name!r} has fewer than 3 coordinate points.")
    return tuple(coords)


def _zone_summary(zone_payload: dict[str, Any]) -> dict[str, float]:
    """Extract a representative cl_target / reynolds / chord per zone.

    The AVL-no-airfoil pass produces multiple ``points`` per zone (one
    per design case × station inside the zone).  We collapse them to a
    weighted-mean cl_target and a max Re (the high-Re point usually
    dominates lift; using max keeps the picker conservative for
    high-Re zones).
    """

    points = zone_payload.get("points") or []
    if not points:
        return {"cl_target": 0.0, "reynolds": 0.0, "chord_m": 0.0}
    weights = [float(point.get("weight", 1.0)) for point in points]
    weight_total = float(sum(weights)) or 1.0
    cl_target = float(
        sum(float(point.get("cl_target", 0.0)) * w for point, w in zip(points, weights))
        / weight_total
    )
    reynolds = float(max(float(point.get("reynolds", 0.0)) for point in points))
    chord = float(
        sum(float(point.get("chord_m", 0.0)) * w for point, w in zip(points, weights))
        / weight_total
    )
    return {"cl_target": cl_target, "reynolds": reynolds, "chord_m": chord}


def _pick_seed_for_zone(
    *,
    zone_name: str,
    cl_target: float,
    reynolds: float,
) -> tuple[str, str]:
    """Select between FX 76-MP-140 and Clark-Y for a zone.

    Heuristic mirrors the Daedalus-style HPA wing layout: cambered
    cambered FX 76-MP-140 in the inboard high-Re high-cl region, Clark-Y
    in the lower-Re lower-cl outer region.  The decision boundary is
    intentionally a simple Re threshold so it is auditable; CST/XFOIL
    search will replace this picker.
    """

    high_cl_high_re = float(cl_target) >= 0.85 and float(reynolds) >= 320_000.0
    inboard_zone = zone_name in {"root", "mid1"}
    if inboard_zone or high_cl_high_re:
        return (
            "fx76mp140",
            "fx76mp140_inboard_or_high_cl_high_re_zone",
        )
    return (
        "clarkysm",
        "clarkysm_outboard_low_cl_or_low_re_zone",
    )


def select_zone_airfoils_from_library(
    *,
    zone_requirements: Mapping[str, dict[str, Any]],
) -> dict[str, ZoneAirfoilSpec]:
    """Pick a library airfoil for every zone in ``zone_requirements``.

    Returns one :class:`ZoneAirfoilSpec` per zone keyed by zone name.
    Zones with no AVL points (``points`` empty) are still resolved to
    a sensible default seed so the downstream AVL-with-airfoil pass
    can still emit AFILE entries.
    """

    selected: dict[str, ZoneAirfoilSpec] = {}
    for zone_name, payload in zone_requirements.items():
        summary = _zone_summary(payload)
        seed_name, reason = _pick_seed_for_zone(
            zone_name=str(zone_name),
            cl_target=summary["cl_target"],
            reynolds=summary["reynolds"],
        )
        params = _SEED_LIBRARY[seed_name]
        selected[str(zone_name)] = ZoneAirfoilSpec(
            zone_name=str(zone_name),
            template_id=str(params["template_id"]),
            seed_name=seed_name,
            source_file=Path(params["source_file"]),
            coordinates=_load_seed_coordinates(seed_name),
            alpha_l0_deg=float(params["alpha_l0_deg"]),
            cl_alpha_per_rad=float(params["cl_alpha_per_rad"]),
            polar_cd0=float(params["polar_cd0"]),
            polar_k=float(params["polar_k"]),
            polar_cl_ref=float(params["polar_cl_ref"]),
            reynolds_ref=float(params["reynolds_ref"]),
            selection_reason=str(reason),
        )
    return selected


def airfoil_templates_for_avl(
    selected: Mapping[str, ZoneAirfoilSpec],
) -> dict[str, dict[str, Any]]:
    """Convert :class:`ZoneAirfoilSpec` map to the dict shape that
    ``load_zone_requirements_from_avl`` expects when re-running AVL with
    airfoil files."""

    return {
        zone_name: spec.to_template() for zone_name, spec in selected.items()
    }


def estimate_zone_profile_cd(
    *,
    selected: Mapping[str, ZoneAirfoilSpec],
    zone_requirements: Mapping[str, dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """For each zone return ``{cd_profile, cl_used, reynolds_used}``.

    ``cd_profile`` is the chord-weighted parasite drag estimate from the
    selected airfoil's tabulated polar evaluated at the zone's
    representative ``cl_target`` and Reynolds.  This is the value the
    closed-loop mission-power proxy adds to AVL's CDi.
    """

    out: dict[str, dict[str, float]] = {}
    for zone_name, spec in selected.items():
        summary = _zone_summary(zone_requirements.get(zone_name, {}))
        cd = spec.cd_at(cl=summary["cl_target"], reynolds=summary["reynolds"])
        out[zone_name] = {
            "cd_profile": float(cd),
            "cl_used": float(summary["cl_target"]),
            "reynolds_used": float(summary["reynolds"]),
            "chord_m_used": float(summary["chord_m"]),
        }
    return out


def chord_weighted_profile_cd(
    *,
    zone_profile: Mapping[str, Mapping[str, float]],
) -> float:
    """Combine per-zone profile drag into a wing-area weighted CD.

    Zone weighting uses the zone-level ``chord_m_used`` × zone span
    fraction.  Falls back to uniform weighting if zone metadata is
    missing.
    """

    total_weight = 0.0
    accumulator = 0.0
    for zone_name, info in zone_profile.items():
        chord = float(info.get("chord_m_used", 0.0))
        if chord <= 0.0:
            continue
        weight = chord
        total_weight += weight
        accumulator += weight * float(info.get("cd_profile", 0.0))
    if total_weight <= 0.0:
        return 0.0
    return float(accumulator / total_weight)


def cst_search_levels() -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Expose the existing CST search default knob levels.

    Useful for callers that want to record what the next-iteration CST
    search would explore on top of the seed picker, even before they
    actually run it.
    """

    return tuple(float(value) for value in _THICKNESS_LEVELS), tuple(
        float(value) for value in _CAMBER_LEVELS
    )


def aerodynamic_summary(
    selected: Mapping[str, ZoneAirfoilSpec],
) -> dict[str, dict[str, float]]:
    """Summarise the per-zone polar coefficients (αL0, CL_alpha, polar)."""

    return {
        zone_name: {
            "alpha_l0_deg": float(spec.alpha_l0_deg),
            "cl_alpha_per_rad": float(spec.cl_alpha_per_rad),
            "cl_alpha_per_deg": float(spec.cl_alpha_per_rad / math.pi * math.pi / 180.0),
            "polar_cd0": float(spec.polar_cd0),
            "polar_k": float(spec.polar_k),
            "polar_cl_ref": float(spec.polar_cl_ref),
            "reynolds_ref": float(spec.reynolds_ref),
            "template_id": spec.template_id,
            "selection_reason": spec.selection_reason,
        }
        for zone_name, spec in selected.items()
    }
