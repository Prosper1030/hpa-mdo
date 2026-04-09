"""Segmented dual-spar cross-section model.

Computes equivalent beam section properties (A, Iy, Iz, J) for a
dual-spar wing with piecewise-constant wall thickness segments.

The main spar (at 0.25c) and rear spar (at 0.70c) are modelled as
hollow circular tubes connected by ribs. The combined section is
reduced to a single equivalent beam for FEM analysis using the
parallel-axis theorem, with an optional knockdown on the rigid-rib
torsional coupling term.

All units are SI: metres, Pascals, kg.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np



# ── Tube cross-section helpers ────────────────────────────────────────────

def tube_area(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Cross-section area of a hollow tube.  A = pi*(R^2 - (R-t)^2)."""
    r = R - t
    return np.pi * (R**2 - r**2)


def tube_Ixx(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Second moment of area (bending). I = pi/4 * (R^4 - r^4)."""
    r = R - t
    return np.pi / 4.0 * (R**4 - r**4)


def tube_J(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Polar moment of area (torsion). J = pi/2 * (R^4 - r^4) = 2*I."""
    r = R - t
    return np.pi / 2.0 * (R**4 - r**4)


def tube_mass_per_length(R: np.ndarray, t: np.ndarray, rho: float) -> np.ndarray:
    """Linear mass density [kg/m]."""
    return rho * tube_area(R, t)


# ── Segment mapping ──────────────────────────────────────────────────────

def segments_to_elements(
    segment_thicknesses: np.ndarray,
    segment_boundaries: np.ndarray,
    element_centres: np.ndarray,
) -> np.ndarray:
    """Map piecewise-constant segment wall thicknesses to element centres.

    Parameters
    ----------
    segment_thicknesses : (n_seg,)
        Wall thickness for each segment [m].
    segment_boundaries : (n_seg + 1,)
        Spanwise boundaries of each segment [m], e.g. [0, 1.5, 4.5, ...].
    element_centres : (n_elem,)
        Y-coordinate of each element centre [m].

    Returns
    -------
    thickness_per_element : (n_elem,)
    """
    n_elem = len(element_centres)
    out = np.empty(n_elem)
    for i, yc in enumerate(element_centres):
        # Find which segment this element belongs to
        seg_idx = np.searchsorted(segment_boundaries[1:], yc, side="right")
        seg_idx = min(seg_idx, len(segment_thicknesses) - 1)
        out[i] = segment_thicknesses[seg_idx]
    return out


def segment_boundaries_from_lengths(segment_lengths: List[float]) -> np.ndarray:
    """Convert segment lengths [1.5, 3.0, 3.0, ...] to boundaries [0, 1.5, 4.5, ...]."""
    return np.concatenate([[0.0], np.cumsum(segment_lengths)])


# ── Outer-diameter computation from airfoil ──────────────────────────────

def compute_outer_radius(
    y: np.ndarray,
    chord: np.ndarray,
    airfoil_tc: np.ndarray,
    spar_cfg,
) -> np.ndarray:
    """Compute outer tube radius at each station.

    If spar_cfg specifies explicit OD, use linear interpolation.
    Otherwise, use airfoil thickness × fraction.
    """
    n = len(y)
    eta = (y - y[0]) / (y[-1] - y[0]) if y[-1] > y[0] else np.zeros(n)

    if spar_cfg.outer_diameter_root is not None:
        d_o_root = spar_cfg.outer_diameter_root
        d_o_tip = spar_cfg.outer_diameter_tip or d_o_root * 0.5
        outer_d = d_o_root + eta * (d_o_tip - d_o_root)
    else:
        frac_root = spar_cfg.thickness_fraction_root
        frac_tip = spar_cfg.thickness_fraction_tip
        frac = frac_root + eta * (frac_tip - frac_root)
        airfoil_thickness_m = airfoil_tc * chord
        outer_d = frac * airfoil_thickness_m

    return outer_d / 2.0  # radius


# ── Dual-spar equivalent section ─────────────────────────────────────────

@dataclass
class DualSparSection:
    """Equivalent beam section properties from main + rear spar.

    All arrays are sized (n_elem,) — one value per beam element.
    """
    A_equiv: np.ndarray       # equivalent area [m^2]
    Iy_equiv: np.ndarray      # flapwise bending stiffness / E [m^4]
    Iz_equiv: np.ndarray      # chordwise bending stiffness / E [m^4]
    J_equiv: np.ndarray       # torsional stiffness / G [m^4]
    EI_flap: np.ndarray       # flapwise EI [N.m^2]
    EI_chord: np.ndarray      # chordwise EI [N.m^2]
    GJ: np.ndarray            # torsional stiffness [N.m^2]
    mass_per_length: np.ndarray  # [kg/m]

    # Individual spar arrays (for stress checking)
    A_main: np.ndarray
    A_rear: np.ndarray
    R_main: np.ndarray
    R_rear: np.ndarray
    t_main: np.ndarray
    t_rear: np.ndarray
    I_main: np.ndarray
    I_rear: np.ndarray


def compute_dual_spar_section(
    R_main: np.ndarray,
    t_main: np.ndarray,
    R_rear: np.ndarray,
    t_rear: np.ndarray,
    z_main: np.ndarray,
    z_rear: np.ndarray,
    d_chord: np.ndarray,
    E_main: float,
    G_main: float,
    rho_main: float,
    E_rear: float,
    G_rear: float,
    rho_rear: float,
    warping_knockdown: float = 1.0,
) -> DualSparSection:
    """Compute equivalent beam section for dual-spar wing.

    Parameters
    ----------
    R_main, R_rear : outer radii of main/rear spar [m]
    t_main, t_rear : wall thicknesses [m]
    z_main, z_rear : vertical (Z) position of each spar centroid
                     on the airfoil camber line (fraction of chord)
    d_chord : chordwise separation between spars [m]
    E_main, E_rear : Young's modulus [Pa]
    G_main, G_rear : shear modulus [Pa]
    rho_main, rho_rear : density [kg/m^3]
    """
    # Individual tube properties
    A_m = tube_area(R_main, t_main)
    A_r = tube_area(R_rear, t_rear)
    I_m = tube_Ixx(R_main, t_main)
    I_r = tube_Ixx(R_rear, t_rear)
    J_m = tube_J(R_main, t_main)
    J_r = tube_J(R_rear, t_rear)

    # ── Flapwise bending (vertical plane, about chordline) ──
    # Parallel-axis theorem: both spars are offset from the combined NA
    # For same E: z_na = (A_m*z_m + A_r*z_r) / (A_m + A_r)
    # EI_flap = E*(I_m + A_m*(z_m-z_na)^2 + I_r + A_r*(z_r-z_na)^2)
    # For different E:
    z_na = (E_main * A_m * z_main + E_rear * A_r * z_rear) / (
        E_main * A_m + E_rear * A_r + 1e-30
    )
    EI_flap = (
        E_main * (I_m + A_m * (z_main - z_na) ** 2)
        + E_rear * (I_r + A_r * (z_rear - z_na) ** 2)
    )

    # ── Chordwise bending (horizontal plane, about spar axis) ──
    # x_main ≈ 0 (reference), x_rear = d_chord
    x_main = np.zeros_like(d_chord)
    x_rear = d_chord
    x_na = (E_main * A_m * x_main + E_rear * A_r * d_chord) / (
        E_main * A_m + E_rear * A_r + 1e-30
    )
    EI_chord = (
        E_main * (I_m + A_m * (x_main - x_na) ** 2)
        + E_rear * (I_r + A_r * (x_rear - x_na) ** 2)
    )

    # ── Torsion ──
    # Individual tube torsion + coupling from spar separation.
    # The warping term assumes rigid ribs; `warping_knockdown` lets the
    # caller reduce that idealised coupling for flexible rib bays.
    GJ_tubes = G_main * J_m + G_rear * J_r
    GJ_warping = warping_knockdown * (E_main * A_m * E_rear * A_r) / (
        E_main * A_m + E_rear * A_r + 1e-30
    ) * d_chord ** 2
    GJ_total = GJ_tubes + GJ_warping

    # ── Mass ──
    m_per_L = rho_main * A_m + rho_rear * A_r

    # ── Equivalent section (for OAS-like solver) ──
    A_equiv = A_m + A_r
    E_avg = (E_main * A_m + E_rear * A_r) / (A_equiv + 1e-30)
    G_avg = (G_main * A_m + G_rear * A_r) / (A_equiv + 1e-30)
    Iy_equiv = EI_flap / (E_avg + 1e-30)
    Iz_equiv = EI_chord / (E_avg + 1e-30)
    J_equiv = GJ_total / (G_avg + 1e-30)

    return DualSparSection(
        A_equiv=A_equiv,
        Iy_equiv=Iy_equiv,
        Iz_equiv=Iz_equiv,
        J_equiv=J_equiv,
        EI_flap=EI_flap,
        EI_chord=EI_chord,
        GJ=GJ_total,
        mass_per_length=m_per_L,
        A_main=A_m,
        A_rear=A_r,
        R_main=R_main,
        R_rear=R_rear,
        t_main=t_main,
        t_rear=t_rear,
        I_main=I_m,
        I_rear=I_r,
    )


# ── Joint / segment utilities ────────────────────────────────────────────

def joint_y_positions(segment_lengths: List[float]) -> List[float]:
    """Return Y-positions of splice joints (cumsum minus tip)."""
    cs = np.cumsum(segment_lengths).tolist()
    return cs[:-1]  # last entry is the tip, not a joint


def joint_mass_total(n_joints: int, mass_per_joint: float) -> float:
    """Total joint mass for half-span (main spar only).

    Full span doubles the inner joints; the centre joint is shared.
    """
    return n_joints * mass_per_joint


def compute_spar_mass(
    y_nodes: np.ndarray,
    section: DualSparSection,
    main_spar_cfg,
    rear_spar_cfg,
) -> dict:
    """Compute total spar system mass including joint penalty.

    Returns dict with mass breakdown.
    """
    n_elem = len(section.mass_per_length)
    dy = np.diff(y_nodes)
    assert len(dy) == n_elem

    # Tube mass per half-span
    spar_mass_half = float(np.sum(section.mass_per_length * dy))

    # Joint masses
    main_joints = joint_y_positions(main_spar_cfg.segments or [y_nodes[-1]])
    rear_joints = joint_y_positions(rear_spar_cfg.segments or [y_nodes[-1]])
    n_main_joints = len(main_joints)
    n_rear_joints = len(rear_joints) if rear_spar_cfg.enabled else 0
    joint_mass = (
        n_main_joints * main_spar_cfg.joint_mass_kg
        + n_rear_joints * rear_spar_cfg.joint_mass_kg
    )

    return {
        "spar_tube_mass_half": spar_mass_half,
        "spar_tube_mass_full": spar_mass_half * 2.0,
        "joint_mass_half": joint_mass,
        "joint_mass_full": joint_mass * 2.0,
        "total_mass_half": spar_mass_half + joint_mass,
        "total_mass_full": (spar_mass_half + joint_mass) * 2.0,
        "n_main_joints": n_main_joints,
        "n_rear_joints": n_rear_joints,
    }
