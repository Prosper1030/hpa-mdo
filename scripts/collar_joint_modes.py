#!/usr/bin/env python3
"""Collar joint mode class library for rib-to-spar attachment design.

Provides a Strategy-pattern class hierarchy for analysing and comparing
different collar joint concepts at a rib station. Each mode encapsulates
its geometry, material parameters, and margin calculation. A factory
function instantiates any mode from a plain dict (YAML-serialisable),
making it trivial to swap joint concepts in config files.

Literature basis
----------------
- Daedalus/Gossamer/Musculair: foam rib + spar-hole local reinforcement +
  bonded, not clamped. Year-round detachable means going beyond historic HPA.
- Schön (2004): CFRP/CFRP dry COF 0.65–0.74 (worn-in); conservative design
  value 0.15–0.20 for un-tested surfaces.
- NPL MATC65 / Hart-Smith / MIL-HDBK-17: avoid peel, use shear/compression,
  taper ends, fillet all corners, overwrap for peel arrest.
- NASA-STD-5020B: fastener preload variation ≥ ±25–35% without test data.
- HPA CFRP tube manual: no drilling HM spar; use film adhesive / Kevlar lashing.

Recommended baseline (from literature synthesis):
  BondedShearKey (permanent, primary anti-rotation)
  + LoadLineYoke  (rib web close to spar surface; reduces r_eff to ≤ 3–5 mm)
  + FrictionClamp (positioning / secondary retention only; must be torque-tested)

Usage
-----
    from collar_joint_modes import joint_from_config, JointLoad

    load = JointLoad(F_n=47.68, R_m=0.05, L_m=0.085, a_m=0.015, peel_allow=400.0)

    key = BondedShearKey(n_keys=2, saddle_length_m=0.060, key_width_m=0.008,
                         key_height_m=0.004, tau_d_pa=2e6, r_key_offset_m=0.005)
    result = key.margin(load)
    print(result.margin, result.governs)

    # Or from a config dict (e.g., loaded from YAML):
    cfg = {"type": "bonded_shear_key", "n_keys": 2, "saddle_length_m": 0.060, ...}
    mode = joint_from_config(cfg)
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JointLoad:
    """Factored mechanical load at the collar station.

    These come from the upstream geometry freeze sheet and do not depend on
    which joint concept is chosen.
    """
    F_n: float         # factored couple force [N]
    R_m: float         # spar tube outer radius [m]
    L_m: float         # collar contact width (span direction) [m]
    a_m: float         # current (or nominal) bondline width along tube axis [m]
    peel_allow: float  # adhesive peel allowable [N/m]

    @property
    def M_req_nm(self) -> float:
        """Required anti-rotation torque [N·m]."""
        return self.F_n * self.R_m

    @property
    def m_per_width(self) -> float:
        """Moment per unit collar contact width [N·m/m = N]."""
        return self.M_req_nm / self.L_m

    @classmethod
    def from_freeze(cls, freeze: dict[str, Any]) -> JointLoad:
        """Build from a Step-1 geometry freeze JSON dict."""
        lf = freeze["load_factor"]
        return cls(
            F_n=abs(freeze["local_couple_force_n"]) * lf,
            R_m=freeze["spar_tubes"]["main_spar"]["od_m"] / 2.0,
            L_m=freeze["collar"]["collar_contact_width_m"],
            a_m=freeze["bondline"]["bondline_width_m"],
            peel_allow=freeze["bondline"]["adhesive_peel_allowable_n_per_m"],
        )


@dataclass
class JointResult:
    """Margin analysis result for a single joint mode."""
    margin: float          # MS = capacity/demand − 1
    governs: str           # label for the governing failure sub-mode
    passes: bool
    detail: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class CollarJointMode(ABC):
    """Abstract base for collar joint concepts.

    Subclasses implement *margin()* and carry their own geometry/material
    parameters. All modes must support *to_dict()* / *from_dict()* for
    YAML-driven config files.
    """
    mode_id: ClassVar[str]  # must be set in every subclass

    @abstractmethod
    def margin(self, load: JointLoad) -> JointResult:
        """Compute the margin-of-safety for this joint concept."""

    def sweep(
        self,
        load: JointLoad,
        param: str,
        values: list[float],
    ) -> list[dict[str, Any]]:
        """Sweep one scalar parameter and return a list of result dicts."""
        import copy
        rows = []
        for v in values:
            clone = copy.copy(self)
            setattr(clone, param, v)
            r = clone.margin(load)
            row = {param: v, "margin": round(r.margin, 4),
                   "passes": r.passes, "governs": r.governs}
            row.update(r.detail)
            rows.append(row)
        return rows

    def min_viable(
        self,
        load: JointLoad,
        param: str,
        lo: float,
        hi: float,
        n_steps: int = 200,
    ) -> float | None:
        """Binary search for the smallest param value that gives margin > 0.

        For parameters where *larger* is better (e.g. bondline width, N_c).
        Returns None if no viable value found in [lo, hi].
        """
        import copy
        # check hi first
        c = copy.copy(self)
        setattr(c, param, hi)
        if c.margin(load).margin <= 0:
            return None
        # check lo
        setattr(c, param, lo)
        if c.margin(load).margin > 0:
            return lo
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            setattr(c, param, mid)
            if c.margin(load).margin > 0:
                hi = mid
            else:
                lo = mid
        return hi

    def min_viable_inverse(
        self,
        load: JointLoad,
        param: str,
        lo: float,
        hi: float,
    ) -> float | None:
        """Binary search for the largest param value that gives margin > 0.

        For parameters where *smaller* is better (e.g. r_eff eccentricity).
        Returns None if even lo gives margin ≤ 0.
        """
        import copy
        c = copy.copy(self)
        setattr(c, param, lo)
        if c.margin(load).margin <= 0:
            return None
        setattr(c, param, hi)
        if c.margin(load).margin > 0:
            return hi
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            setattr(c, param, mid)
            if c.margin(load).margin > 0:
                lo = mid
            else:
                hi = mid
        return lo

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (YAML-friendly)."""

    @classmethod
    @abstractmethod
    def from_dict(cls, d: dict[str, Any]) -> CollarJointMode:
        """Deserialise from a plain dict."""


# ---------------------------------------------------------------------------
# Mode 1: Peel Bond (current design — baseline for comparison)
# ---------------------------------------------------------------------------

class PeelBond(CollarJointMode):
    """Current design: collar tab bonded directly to spar OD.

    The couple force acts at the spar axis. The bond surface at radius r
    creates a peel moment that the bondline must resist. This is the least
    favourable adhesive load case. Literature (Hart-Smith, NPL MATC65)
    unanimously advises against relying on peel for structural joints.

    c_factor options:
      1.0 = theoretical minimum (best-case resultant couple at bondline ends)
      1.5 = linear distribution tensile-half resultant  [default]
      2.0 = conservative index (Step-2 model)
    """
    mode_id = "peel_bond"

    def __init__(self, *, a_m: float | None = None, c_factor: float = 1.5) -> None:
        self.a_m = a_m        # override bondline width (uses load.a_m if None)
        self.c_factor = c_factor

    def margin(self, load: JointLoad) -> JointResult:
        a = self.a_m if self.a_m is not None else load.a_m
        f_peel = self.c_factor * load.m_per_width / a
        ms = load.peel_allow / f_peel - 1.0
        return JointResult(
            margin=round(ms, 4),
            governs="peel_bond",
            passes=ms > 0,
            detail={
                "bondline_width_mm": round(a * 1000, 2),
                "f_peel_demand_n_per_m": round(f_peel, 2),
                "peel_allow_n_per_m": load.peel_allow,
                "c_factor": self.c_factor,
                "theoretical_min_n_per_m": round(load.m_per_width / a, 2),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.mode_id, "a_m": self.a_m, "c_factor": self.c_factor}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PeelBond:
        return cls(a_m=d.get("a_m"), c_factor=d.get("c_factor", 1.5))


# ---------------------------------------------------------------------------
# Mode 2: Load-Line Yoke (reduce eccentricity via rib clevis/slot)
# ---------------------------------------------------------------------------

class LoadLineYoke(CollarJointMode):
    """Rib web has a U-slot / yoke that engages a feature close to spar OD.

    By routing the rib reaction force through a point near the spar surface,
    the effective eccentricity r_eff << R_spar. Combined with a bonded shear
    key (below), this is the recommended primary load path.

    Literature: rib yoke on bonded key; slot clearance 0.2–0.5 mm; wear
    pads (UHMWPE/PTFE) on slot faces to protect key.
    """
    mode_id = "load_line_yoke"

    def __init__(
        self,
        *,
        r_eff_m: float,
        a_m: float | None = None,
        c_factor: float = 1.5,
    ) -> None:
        self.r_eff_m = r_eff_m    # effective eccentricity [m]; target ≤ 3–5 mm
        self.a_m = a_m             # override bondline width
        self.c_factor = c_factor

    def margin(self, load: JointLoad) -> JointResult:
        a = self.a_m if self.a_m is not None else load.a_m
        m_eff = load.F_n * self.r_eff_m / load.L_m
        f_peel = self.c_factor * m_eff / a
        ms = load.peel_allow / f_peel - 1.0
        return JointResult(
            margin=round(ms, 4),
            governs="residual_peel_at_yoke",
            passes=ms > 0,
            detail={
                "r_eff_mm": round(self.r_eff_m * 1000, 2),
                "r_original_mm": round(load.R_m * 1000, 1),
                "eccentricity_reduction_pct": round((1 - self.r_eff_m / load.R_m) * 100, 1),
                "m_eff_per_width_n": round(m_eff, 4),
                "f_peel_demand_n_per_m": round(f_peel, 2),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.mode_id, "r_eff_m": self.r_eff_m,
                "a_m": self.a_m, "c_factor": self.c_factor}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LoadLineYoke:
        return cls(r_eff_m=d["r_eff_m"], a_m=d.get("a_m"),
                   c_factor=d.get("c_factor", 1.5))


# ---------------------------------------------------------------------------
# Mode 3: Friction Clamp (split clamp — positioning and secondary retention)
# ---------------------------------------------------------------------------

# Friction coefficient reference values from Schön (2004) and literature:
MU_REFERENCE = {
    "dry_cfrp_conservative": 0.15,   # untested, clean HM CFRP / CFRP
    "dry_cfrp_nominal": 0.20,        # nominal for glossy prepreg surface
    "cork_rubber_liner": 0.30,       # conservative with liner, untested
    "PU_liner": 0.25,
    "neoprene_liner": 0.28,
    "worn_in_cfrp": 0.65,            # Schön worn-in; do NOT use for design
}


class FrictionClamp(CollarJointMode):
    """Split clamp (two half-shells with through-bolts) on spar OD.

    Friction provides anti-rotation torque: T = μ × N_c × R.
    Literature position: use as *positioning and secondary retention* only,
    not as the sole primary anti-rotation mechanism, unless torque-to-slip
    tests over the planned reassembly cycle count confirm μ and N_c stability.

    Liner materials and their conservative μ_d (design, not worn-in):
      dry_cfrp_conservative : 0.15  (no liner, no test)
      cork_rubber_liner      : 0.30  (conservative with liner)
      PU_liner               : 0.25
      neoprene_liner         : 0.28
    """
    mode_id = "friction_clamp"

    def __init__(
        self,
        *,
        mu: float,
        N_c_n: float,
        liner: str = "dry_cfrp_conservative",
        contact_arc_rad: float = math.pi,
        p_contact_allow_pa: float = 1.0e6,
        role: str = "secondary",
    ) -> None:
        self.mu = mu
        self.N_c_n = N_c_n
        self.liner = liner
        self.contact_arc_rad = contact_arc_rad
        self.p_contact_allow_pa = p_contact_allow_pa
        self.role = role   # 'primary' or 'secondary' — informational

    def margin(self, load: JointLoad) -> JointResult:
        M_friction = self.mu * self.N_c_n * load.R_m
        m_torque = M_friction / load.M_req_nm - 1.0
        A_c = self.contact_arc_rad * load.R_m * load.L_m
        p_c = self.N_c_n / A_c if A_c > 0 else math.inf
        m_pressure = self.p_contact_allow_pa / p_c - 1.0 if p_c > 0 else math.inf
        ms = min(m_torque, m_pressure)
        governs = "torque" if m_torque <= m_pressure else "contact_pressure"
        return JointResult(
            margin=round(ms, 4),
            governs=governs,
            passes=ms > 0,
            detail={
                "mu": self.mu,
                "N_c_n": self.N_c_n,
                "liner": self.liner,
                "role": self.role,
                "M_friction_nm": round(M_friction, 4),
                "M_req_nm": round(load.M_req_nm, 4),
                "contact_pressure_pa": round(p_c, 0),
                "margin_torque": round(m_torque, 3),
                "margin_pressure": round(m_pressure, 3),
                "note": (
                    "Design μ requires torque-to-slip test + reassembly cycle test. "
                    "Do not use mu_reference['worn_in_cfrp'] for design."
                ),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.mode_id,
            "mu": self.mu,
            "N_c_n": self.N_c_n,
            "liner": self.liner,
            "contact_arc_rad": self.contact_arc_rad,
            "p_contact_allow_pa": self.p_contact_allow_pa,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FrictionClamp:
        return cls(
            mu=d["mu"],
            N_c_n=d["N_c_n"],
            liner=d.get("liner", "dry_cfrp_conservative"),
            contact_arc_rad=d.get("contact_arc_rad", math.pi),
            p_contact_allow_pa=d.get("p_contact_allow_pa", 1.0e6),
            role=d.get("role", "secondary"),
        )


# ---------------------------------------------------------------------------
# Mode 4: Bonded Shear Key (primary anti-rotation — literature recommendation)
# ---------------------------------------------------------------------------

class BondedShearKey(CollarJointMode):
    """Permanent conformal saddle key bonded to spar OD; rib has U-slot.

    The key resists rotation via adhesive *shear* (not peel). The rib yoke
    engages the key; slot clearance 0.2–0.5 mm with UHMWPE/PTFE wear pads.

    Literature-derived geometry guidelines (HPA CFRP tube manual, NPL MATC65):
      - Saddle length 50–70 mm; conformal inner face (R = R_spar)
      - Saddle thickness 0.8–1.5 mm (G10/FR4 or thin CFRP)
      - Key height 3–5 mm, key width 6–10 mm
      - End taper 10:1 to 20:1 (length:height)
      - Fillet radius ≥ 1–2 mm at all corners
      - Overwrap: 1–2 ply ±45° glass/carbon, 20–30 mm past each end of key
      - tau_d = 2 MPa (conservative; 18 MPa nominal × ~0.11 knockdown for peel
        concentration at key ends without overwrap; adjust upward if overwrap
        coupon-tested)

    The governing failure sub-mode is whichever of shear or bearing is smaller.
    """
    mode_id = "bonded_shear_key"

    def __init__(
        self,
        *,
        n_keys: int = 2,
        saddle_length_m: float = 0.060,
        key_width_m: float = 0.008,
        key_height_m: float = 0.004,
        tau_d_pa: float = 2.0e6,
        r_key_offset_m: float = 0.005,
        sigma_b_d_pa: float | None = None,
    ) -> None:
        self.n_keys = n_keys
        self.saddle_length_m = saddle_length_m
        self.key_width_m = key_width_m
        self.key_height_m = key_height_m
        self.tau_d_pa = tau_d_pa
        # R_key = R_spar + key_height/2 + r_key_offset (centroid of shear area)
        self.r_key_offset_m = r_key_offset_m
        self.sigma_b_d_pa = sigma_b_d_pa   # rib-on-key bearing allowable; optional

    def _r_key(self, load: JointLoad) -> float:
        return load.R_m + self.key_height_m / 2.0 + self.r_key_offset_m

    def margin(self, load: JointLoad) -> JointResult:
        r_key = self._r_key(load)
        F_t = load.M_req_nm / r_key
        A_shear_each = self.key_width_m * self.saddle_length_m
        F_shear_cap = self.n_keys * self.tau_d_pa * A_shear_each
        sub_margins: dict[str, float] = {
            "shear": F_shear_cap / F_t - 1.0,
        }
        if self.sigma_b_d_pa is not None:
            A_bearing_each = self.key_height_m * self.key_width_m
            F_bearing_cap = self.n_keys * self.sigma_b_d_pa * A_bearing_each
            sub_margins["bearing"] = F_bearing_cap / F_t - 1.0
        ms = min(sub_margins.values())
        governs = min(sub_margins, key=sub_margins.__getitem__)
        return JointResult(
            margin=round(ms, 4),
            governs=governs,
            passes=ms > 0,
            detail={
                "n_keys": self.n_keys,
                "saddle_length_mm": round(self.saddle_length_m * 1000, 1),
                "key_width_mm": round(self.key_width_m * 1000, 1),
                "key_height_mm": round(self.key_height_m * 1000, 1),
                "A_shear_per_key_mm2": round(A_shear_each * 1e6, 1),
                "A_shear_total_mm2": round(self.n_keys * A_shear_each * 1e6, 1),
                "tau_d_mpa": self.tau_d_pa / 1e6,
                "r_key_m": round(r_key, 5),
                "F_tangential_n": round(F_t, 3),
                "F_shear_cap_n": round(F_shear_cap, 3),
                "sub_margins": {k: round(v, 3) for k, v in sub_margins.items()},
                "literature_notes": (
                    "Permanent on spar; rib slots over key. "
                    "tau_d=2 MPa includes knockdown for end-peel concentration; "
                    "increase to 4–6 MPa if overwrap coupon tested. "
                    "Key ends: 10–20:1 taper, fillet R≥2 mm, ±45° overwrap 25 mm past end."
                ),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.mode_id,
            "n_keys": self.n_keys,
            "saddle_length_m": self.saddle_length_m,
            "key_width_m": self.key_width_m,
            "key_height_m": self.key_height_m,
            "tau_d_pa": self.tau_d_pa,
            "r_key_offset_m": self.r_key_offset_m,
            "sigma_b_d_pa": self.sigma_b_d_pa,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BondedShearKey:
        return cls(
            n_keys=d.get("n_keys", 2),
            saddle_length_m=d.get("saddle_length_m", 0.060),
            key_width_m=d.get("key_width_m", 0.008),
            key_height_m=d.get("key_height_m", 0.004),
            tau_d_pa=d.get("tau_d_pa", 2.0e6),
            r_key_offset_m=d.get("r_key_offset_m", 0.005),
            sigma_b_d_pa=d.get("sigma_b_d_pa"),
        )


# ---------------------------------------------------------------------------
# Mode 5: HybridJoint (combine modes, check independently — conservative)
# ---------------------------------------------------------------------------

class HybridJoint(CollarJointMode):
    """Combination of multiple joint modes checked independently.

    Each sub-mode is evaluated against the full required torque. The
    governing margin is the *minimum* across all sub-modes (conservative;
    no load sharing assumed unless you have test evidence).

    Typical recommended baseline (literature):
      primary   = BondedShearKey (+ LoadLineYoke r_eff ≤ 3 mm on rib side)
      secondary = FrictionClamp  (positioning / secondary retention)

    The FrictionClamp is kept in the joint because it contributes to
    axial slip prevention and provides redundancy, even if its torque margin
    alone is the weakest. If any single mode passes, the joint *may* be
    acceptable — but conservative sign-off requires all modes to pass.
    """
    mode_id = "hybrid"

    def __init__(
        self,
        modes: list[CollarJointMode],
        *,
        description: str = "",
    ) -> None:
        self.modes = modes
        self.description = description

    def margin(self, load: JointLoad) -> JointResult:
        results = [(m.mode_id, m.margin(load)) for m in self.modes]
        governs_id, worst = min(results, key=lambda x: x[1].margin)
        return JointResult(
            margin=worst.margin,
            governs=f"{governs_id}:{worst.governs}",
            passes=all(r.passes for _, r in results),
            detail={
                "description": self.description,
                "sub_results": {
                    mid: {"margin": r.margin, "governs": r.governs, "passes": r.passes}
                    for mid, r in results
                },
                "governing_mode": governs_id,
                "all_pass": all(r.passes for _, r in results),
                "any_pass": any(r.passes for _, r in results),
                "note": "Conservative: no load sharing assumed between sub-modes.",
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.mode_id,
            "description": self.description,
            "modes": [m.to_dict() for m in self.modes],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HybridJoint:
        modes = [joint_from_config(m) for m in d["modes"]]
        return cls(modes, description=d.get("description", ""))


# ---------------------------------------------------------------------------
# Mode 6: SaddleRingYoke (C04 fix — conformal ring + low-profile tangential lugs)
# ---------------------------------------------------------------------------

class SaddleRingYoke(CollarJointMode):
    """Conformal bonded saddle ring with diametrically-opposed tangential lugs.

    Replaces the eccentric collar tab (C04 fix). A GFRP/CFRP ring wraps the
    spar circumferentially; two low-profile lugs project tangentially; the rib
    yoke pushes on the lugs to form a pure couple, eliminating the outward peel
    moment that governs C04 failure.

    Load path (no peel):
        rib yoke arm → lug bearing (tangential)
        → ring adhesive shear (large conformal area)
        → spar OD surface shear

    Literature basis (from search AI synthesis):
      - Average ring shear at 48 N total force ≈ 0.012–0.024 MPa — not the
        critical failure mode.
      - Critical modes: concentrated adhesive shear at lug foot (use k_concentration
        to capture non-uniform distribution) and lug bearing.
      - h_lug must be << R_spar to keep lug-root peel small; ≤ 5–8 mm for 100 mm OD.
      - Ring ends: taper + fillet; optional ±45° overwrap 20–30 mm past edge.
    """
    mode_id = "saddle_ring_yoke"

    def __init__(
        self,
        *,
        arc_angle_rad: float = math.pi,        # contact arc (π=180°, 2π=360°)
        ring_width_m: float = 0.030,           # spanwise width of ring [m]
        lug_height_m: float = 0.005,           # lug height above ring OD — keep ≤ 8 mm
        lug_width_m: float = 0.012,            # lug width (span-direction) [m]
        lug_foot_length_m: float = 0.025,      # adhesive bond length at lug base [m]
        tau_adhesive_pa: float = 10.0e6,       # ring-to-spar adhesive shear allowable [Pa]
        k_concentration: float = 2.0,          # shear concentration factor at lug foot
        sigma_lug_bearing_pa: float = 50.0e6,  # rib yoke on lug bearing allowable [Pa]
    ) -> None:
        self.arc_angle_rad = arc_angle_rad
        self.ring_width_m = ring_width_m
        self.lug_height_m = lug_height_m
        self.lug_width_m = lug_width_m
        self.lug_foot_length_m = lug_foot_length_m
        self.tau_adhesive_pa = tau_adhesive_pa
        self.k_concentration = k_concentration
        self.sigma_lug_bearing_pa = sigma_lug_bearing_pa

    def _r_lug(self, load: JointLoad) -> float:
        return load.R_m + self.lug_height_m / 2.0

    def margin(self, load: JointLoad) -> JointResult:
        r_lug = self._r_lug(load)
        # Diametrically-opposed pair: M = 2 × F_lug × r_lug
        F_lug = load.M_req_nm / (2.0 * r_lug)

        # Mode 1: concentrated adhesive shear at lug foot
        A_lug_foot = self.lug_width_m * self.lug_foot_length_m
        tau_lug_foot = self.k_concentration * F_lug / A_lug_foot
        m_adhesive = self.tau_adhesive_pa / tau_lug_foot - 1.0

        # Mode 2: lug bearing (rib yoke face pushing tangentially on lug)
        A_lug_bearing = self.lug_height_m * self.lug_width_m
        sigma_bearing = F_lug / A_lug_bearing
        m_bearing = self.sigma_lug_bearing_pa / sigma_bearing - 1.0

        # Informational: average ring shear (much lower — large conformal area)
        A_ring_total = self.arc_angle_rad * load.R_m * self.ring_width_m
        tau_ring_avg = (load.M_req_nm / load.R_m) / A_ring_total

        sub = {"adhesive_shear": m_adhesive, "lug_bearing": m_bearing}
        ms = min(sub.values())
        governs = min(sub, key=sub.__getitem__)
        return JointResult(
            margin=round(ms, 4),
            governs=governs,
            passes=ms > 0,
            detail={
                "r_lug_mm": round(r_lug * 1000, 2),
                "F_lug_n": round(F_lug, 3),
                "A_lug_foot_mm2": round(A_lug_foot * 1e6, 2),
                "tau_lug_foot_mpa": round(tau_lug_foot / 1e6, 4),
                "tau_adhesive_allow_mpa": self.tau_adhesive_pa / 1e6,
                "sigma_bearing_mpa": round(sigma_bearing / 1e6, 4),
                "sigma_bearing_allow_mpa": self.sigma_lug_bearing_pa / 1e6,
                "A_ring_total_mm2": round(A_ring_total * 1e6, 1),
                "tau_ring_avg_mpa": round(tau_ring_avg / 1e6, 6),
                "arc_deg": round(math.degrees(self.arc_angle_rad), 1),
                "lug_height_mm": round(self.lug_height_m * 1000, 1),
                "k_concentration": self.k_concentration,
                "sub_margins": {k: round(v, 3) for k, v in sub.items()},
                "note": (
                    "h_lug must be << R_spar to suppress root peel. "
                    "Taper ring ends; optional ±45° overwrap 25 mm past ring edge."
                ),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.mode_id,
            "arc_angle_rad": self.arc_angle_rad,
            "ring_width_m": self.ring_width_m,
            "lug_height_m": self.lug_height_m,
            "lug_width_m": self.lug_width_m,
            "lug_foot_length_m": self.lug_foot_length_m,
            "tau_adhesive_pa": self.tau_adhesive_pa,
            "k_concentration": self.k_concentration,
            "sigma_lug_bearing_pa": self.sigma_lug_bearing_pa,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SaddleRingYoke:
        return cls(
            arc_angle_rad=d.get("arc_angle_rad", math.pi),
            ring_width_m=d.get("ring_width_m", 0.030),
            lug_height_m=d.get("lug_height_m", 0.005),
            lug_width_m=d.get("lug_width_m", 0.012),
            lug_foot_length_m=d.get("lug_foot_length_m", 0.025),
            tau_adhesive_pa=d.get("tau_adhesive_pa", 10.0e6),
            k_concentration=d.get("k_concentration", 2.0),
            sigma_lug_bearing_pa=d.get("sigma_lug_bearing_pa", 50.0e6),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_MODE_REGISTRY: dict[str, type[CollarJointMode]] = {
    PeelBond.mode_id: PeelBond,
    LoadLineYoke.mode_id: LoadLineYoke,
    FrictionClamp.mode_id: FrictionClamp,
    BondedShearKey.mode_id: BondedShearKey,
    HybridJoint.mode_id: HybridJoint,
    SaddleRingYoke.mode_id: SaddleRingYoke,
}


def joint_from_config(cfg: dict[str, Any]) -> CollarJointMode:
    """Instantiate any CollarJointMode from a plain dict.

    The dict must have a "type" key matching one of the registered mode_ids.
    Remaining keys are forwarded to the mode's from_dict() classmethod.
    Compatible with YAML round-trips.

    Example:
        joint_from_config({"type": "bonded_shear_key", "n_keys": 2, "tau_d_pa": 2e6})
    """
    mode_type = cfg.get("type")
    if mode_type not in _MODE_REGISTRY:
        raise ValueError(
            f"Unknown collar joint type '{mode_type}'. "
            f"Valid types: {list(_MODE_REGISTRY)}"
        )
    return _MODE_REGISTRY[mode_type].from_dict(cfg)


def available_modes() -> list[str]:
    return list(_MODE_REGISTRY)


# ---------------------------------------------------------------------------
# Recommended baseline (literature synthesis)
# ---------------------------------------------------------------------------

def recommended_baseline(load: JointLoad) -> HybridJoint:
    """Build the literature-recommended baseline joint for the given load.

    Components:
      - BondedShearKey: permanent on spar, primary anti-rotation.
        Geometry: 2 × (60 mm × 8 mm saddle, 4 mm key), tau_d = 2 MPa.
      - LoadLineYoke: rib web U-slot routes force to ≤ 3 mm from spar surface.
      - FrictionClamp: split clamp, cork-rubber liner, N_c = 600 N; role=secondary.

    All three are checked independently (conservative, no load sharing).
    """
    return HybridJoint(
        modes=[
            BondedShearKey(
                n_keys=2,
                saddle_length_m=0.060,
                key_width_m=0.008,
                key_height_m=0.004,
                tau_d_pa=2.0e6,
                r_key_offset_m=0.005,
            ),
            LoadLineYoke(r_eff_m=0.003, c_factor=2.0),  # conservative C-factor
            FrictionClamp(mu=0.15, N_c_n=600.0, liner="cork_rubber_liner", role="secondary"),
        ],
        description=(
            "Literature baseline: bonded shear key (primary) + "
            "yoke r_eff=3 mm (peel reduction) + "
            "split clamp N_c=600 N μ=0.15 (secondary positioning)"
        ),
    )


def recommended_c04_fix(load: JointLoad) -> HybridJoint:
    """C04-specific fix: saddle ring yoke (primary) + friction clamp (secondary).

    Replaces the eccentric collar tab with a conformal saddle ring + tangential
    lug pair. The rib yoke arms push on two diametrically-opposed low-profile
    lugs, forming a pure couple with no outward peel moment.

    Literature basis (Airglow, Google Patent US20130240671A1, Hart-Smith):
      SaddleRingYoke: 30 mm wide GFRP ring, 180° arc, two 5 mm × 12 mm lugs,
        tau_adhesive = 10 MPa (toughened epoxy), k_concentration = 2.0.
      FrictionClamp: secondary positioning, mu = 0.15, N_c = 600 N.
    """
    return HybridJoint(
        modes=[
            SaddleRingYoke(
                arc_angle_rad=math.pi,
                ring_width_m=0.030,
                lug_height_m=0.005,
                lug_width_m=0.012,
                lug_foot_length_m=0.025,
                tau_adhesive_pa=10.0e6,
                k_concentration=2.0,
                sigma_lug_bearing_pa=50.0e6,
            ),
            FrictionClamp(mu=0.15, N_c_n=600.0, liner="cork_rubber_liner", role="secondary"),
        ],
        description=(
            "C04 fix: saddle ring (conformal, no peel) + "
            "low-profile tangential lug pair + "
            "split clamp N_c=600 N (secondary positioning)"
        ),
    )
