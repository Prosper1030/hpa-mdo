#!/usr/bin/env python3
"""Step 2c: Collar joint redesign search for C04 peel fix at y=2.328 m.

The Step 2 analytical margin run identified that the current peel-bond
design (15 mm bondline) fails with margin −0.893 even under the most
conservative model, and margin −0.786 under the theoretical minimum
(geometry-only lower bound). This script implements a multi-mode design
search to find physically sound alternatives.

Four collar joint modes are evaluated:

  peel_bond        — current design; bondline width is the free parameter.
  load_line_yoke   — route the rib force through the tube centerline (yoke /
                     clevis / saddle bracket); effective eccentricity r_eff is
                     the free parameter.
  friction_clamp   — split clamp collar; resist rotation via friction between
                     collar and tube outer surface; clamp force N_c is the free
                     parameter, mu is swept over realistic ranges.
  external_shear_key — two bonded anti-rotation blocks on tube OD; resist
                     rotation via adhesive shear (not peel); total bonded area
                     is the free parameter.

For each mode the search finds the minimum viable geometry (margin = 0
crossing), a recommended design (1.5× minimum for peel/yoke, 2× minimum
for others), and the governing margin at the recommended design point.

All load inputs are read from the Step 1 geometry freeze JSON so this
script stays consistent with the upstream pipeline. If the design changes
(different tube OD, different load), just regenerate the freeze JSON and
rerun this script.

Usage:
    python scripts/current_pathfinder_rib_collar_joint_design_search.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.collar_joint_modes import JointLoad, recommended_c04_fix  # noqa: E402

SCHEMA_VERSION = "rib_collar_joint_design_search_v1"

DEFAULT_FREEZE_JSON = (
    REPO_ROOT / "output" / "current_pathfinder_rib_local_detail_geometry_freeze"
    / "geometry_allowable_freeze.json"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "output" / "current_pathfinder_rib_collar_joint_design_search"
)
DEFAULT_REPORT_JSON = (
    REPO_ROOT / "docs" / "reports"
    / "2026-05-11_current_pathfinder_rib_collar_joint_design_search.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT / "docs" / "reports"
    / "2026-05-11_current_pathfinder_rib_collar_joint_design_search.md"
)

# C-factor for peel stress distribution:
#   1.0 = theoretical minimum (best-case resultant couple at bondline ends)
#   1.5 = linear distribution tensile-half resultant (N+ = 3m/2a)
#   2.0 = conservative index used in Step 2 (f = 2m/a = sigma*a/3)
C_THEORETICAL = 1.0
C_LINEAR = 1.5
C_CONSERVATIVE = 2.0

# Shear key design allowable (conservative; nominal adhesive tau_allow ~ 18 MPa
# but bonded key sees peel at ends; use knockdown to 2 MPa for hand calculation).
TAU_DESIGN_KEY_PA = 2.0e6


# ---------------------------------------------------------------------------
# Margin functions — one per collar joint mode
# ---------------------------------------------------------------------------

def margin_peel_bond(
    m_per_width: float,
    a: float,
    peel_allow: float,
    c_factor: float = C_LINEAR,
) -> tuple[float, dict[str, Any]]:
    """Peel bond: collar tab bonded directly to spar tube OD.

    m_per_width: moment per unit collar contact width [N·m/m = N]
    a          : bondline width along tube axis [m]
    peel_allow : adhesive peel allowable [N/m]
    c_factor   : distribution factor (C_THEORETICAL=1, C_LINEAR=1.5, C_CONSERVATIVE=2)
    """
    f_peel = c_factor * m_per_width / a
    margin = peel_allow / f_peel - 1.0
    return margin, {
        "mode": "peel_bond",
        "bondline_width_m": round(a, 5),
        "bondline_width_mm": round(a * 1000, 2),
        "f_peel_demand_n_per_m": round(f_peel, 2),
        "peel_allow_n_per_m": peel_allow,
        "c_factor": c_factor,
    }


def margin_load_line_yoke(
    F: float,
    r_eff: float,
    L: float,
    a: float,
    peel_allow: float,
    c_factor: float = C_LINEAR,
) -> tuple[float, dict[str, Any]]:
    """Yoke / clevis / saddle: route rib force through tube centerline.

    F     : design couple force [N]
    r_eff : effective eccentricity (distance from force line to bondline) [m]
    L     : collar contact width (span direction) [m]
    a     : bondline width along tube axis [m]
    """
    m_eff = F * r_eff / L
    f_peel = c_factor * m_eff / a
    margin = peel_allow / f_peel - 1.0
    return margin, {
        "mode": "load_line_yoke",
        "r_eff_m": round(r_eff, 5),
        "r_eff_mm": round(r_eff * 1000, 2),
        "m_eff_per_width_n": round(m_eff, 4),
        "f_peel_demand_n_per_m": round(f_peel, 2),
        "peel_allow_n_per_m": peel_allow,
        "c_factor": c_factor,
    }


def margin_friction_clamp(
    M_req: float,
    R_spar: float,
    mu: float,
    N_c: float,
    L: float,
    contact_arc_rad: float = math.pi,
    p_contact_allow_pa: float = 1.0e6,
) -> tuple[float, dict[str, Any]]:
    """Split clamp collar: resist torque via friction on spar OD.

    M_req            : required anti-rotation torque [N·m]
    R_spar           : spar tube outer radius [m]
    mu               : design friction coefficient (conservative)
    N_c              : total clamp force (sum over both collar halves) [N]
    L                : collar contact width (span direction) [m]
    contact_arc_rad  : arc over which contact pressure acts [rad] (default π = half circumference)
    p_contact_allow_pa: tube OD bearing/contact pressure allowable [Pa]
    """
    M_friction = mu * N_c * R_spar
    margin_torque = M_friction / M_req - 1.0
    A_contact = contact_arc_rad * R_spar * L
    p_contact = N_c / A_contact
    margin_pressure = p_contact_allow_pa / p_contact - 1.0
    margin = min(margin_torque, margin_pressure)
    return margin, {
        "mode": "friction_clamp",
        "mu": mu,
        "N_c_n": round(N_c, 2),
        "M_friction_nm": round(M_friction, 4),
        "contact_pressure_pa": round(p_contact, 0),
        "margin_torque": round(margin_torque, 3),
        "margin_pressure": round(margin_pressure, 3),
        "governing": "torque" if margin_torque <= margin_pressure else "pressure",
    }


def margin_external_shear_key(
    M_req: float,
    R_key: float,
    n_key: int,
    A_key_m2: float,
    tau_d: float = TAU_DESIGN_KEY_PA,
    sigma_b_d: float | None = None,
    A_bearing_m2: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """External bonded shear key: anti-rotation blocks bonded to spar OD.

    Keys resist torque via shear at the bond surface (not peel). The force
    line through the key centroid is perpendicular to the radius R_key.

    M_req      : required anti-rotation torque [N·m]
    R_key      : distance from tube axis to shear key bond centroid [m]
                 (approximately R_spar + half key thickness)
    n_key      : number of shear keys (placed symmetrically)
    A_key_m2   : bonded area of each shear key [m²]
    tau_d      : design shear allowable for key bond [Pa] (with knockdown)
    sigma_b_d  : bearing stress allowable on tube OD [Pa] (optional)
    A_bearing_m2: bearing area of each key on tube OD [m²] (optional)
    """
    F_t = M_req / R_key
    F_shear_cap = n_key * tau_d * A_key_m2
    if sigma_b_d is not None and A_bearing_m2 is not None:
        F_bearing_cap = n_key * sigma_b_d * A_bearing_m2
        margin_bearing = F_bearing_cap / F_t - 1.0
        F_cap = min(F_shear_cap, F_bearing_cap)
    else:
        F_bearing_cap = None
        margin_bearing = None
        F_cap = F_shear_cap
    M_cap = F_cap * R_key
    margin = M_cap / M_req - 1.0
    return margin, {
        "mode": "external_shear_key",
        "n_key": n_key,
        "A_key_per_key_mm2": round(A_key_m2 * 1e6, 2),
        "A_key_total_mm2": round(n_key * A_key_m2 * 1e6, 2),
        "tau_design_pa": tau_d,
        "F_tangential_n": round(F_t, 3),
        "F_shear_cap_n": round(F_shear_cap, 3),
        "M_cap_nm": round(M_cap, 4),
        "margin_bearing": round(margin_bearing, 3) if margin_bearing is not None else None,
        "governing": "shear" if (margin_bearing is None or F_shear_cap <= (F_bearing_cap or 1e30)) else "bearing",
    }


# ---------------------------------------------------------------------------
# Sweep helpers — find minimum viable parameter and recommended design
# ---------------------------------------------------------------------------

def _sweep_peel_bond(m_per_width: float, peel_allow: float, c_factor: float) -> dict[str, Any]:
    a_values = [v * 1e-3 for v in range(5, 205, 5)]  # 5 mm to 200 mm step 5 mm
    rows = []
    min_viable_a = None
    for a in a_values:
        margin, detail = margin_peel_bond(m_per_width, a, peel_allow, c_factor)
        detail["margin"] = round(margin, 3)
        detail["passes"] = margin > 0
        rows.append(detail)
        if margin > 0 and min_viable_a is None:
            min_viable_a = a
    recommended_a = min_viable_a * 1.5 if min_viable_a else None
    rec_margin = None
    if recommended_a:
        rec_margin, _ = margin_peel_bond(m_per_width, recommended_a, peel_allow, c_factor)
    return {
        "mode": "peel_bond",
        "current_bondline_mm": 15.0,
        "min_viable_bondline_mm": round(min_viable_a * 1000, 1) if min_viable_a else None,
        "recommended_bondline_mm": round(recommended_a * 1000, 1) if recommended_a else None,
        "recommended_margin": round(rec_margin, 3) if rec_margin is not None else None,
        "sweep": rows,
    }


def _sweep_load_line_yoke(
    F: float, L: float, a: float, peel_allow: float, c_factor: float
) -> dict[str, Any]:
    r_eff_values = [v * 1e-3 for v in range(1, 52, 1)]  # 1 mm to 51 mm step 1 mm
    rows = []
    max_viable_r = None
    for r_eff in r_eff_values:
        margin, detail = margin_load_line_yoke(F, r_eff, L, a, peel_allow, c_factor)
        detail["margin"] = round(margin, 3)
        detail["passes"] = margin > 0
        rows.append(detail)
        if margin > 0:
            max_viable_r = r_eff
    recommended_r = max_viable_r * 0.67 if max_viable_r else None  # smaller r_eff = better
    rec_margin = None
    if recommended_r:
        rec_margin, _ = margin_load_line_yoke(F, recommended_r, L, a, peel_allow, c_factor)
    return {
        "mode": "load_line_yoke",
        "current_r_eff_mm": 50.0,
        "max_viable_r_eff_mm": round(max_viable_r * 1000, 1) if max_viable_r else None,
        "recommended_r_eff_mm": round(recommended_r * 1000, 1) if recommended_r else None,
        "recommended_margin": round(rec_margin, 3) if rec_margin is not None else None,
        "note": "r_eff is the eccentricity of the force line from the tube centreline; smaller is better",
        "sweep": rows,
    }


def _sweep_friction_clamp(
    M_req: float, R_spar: float, L: float, mu_values: list[float]
) -> dict[str, Any]:
    n_c_values = list(range(100, 3100, 100))  # 100 N to 3000 N step 100 N
    all_rows: list[dict[str, Any]] = []
    by_mu: dict[float, dict[str, Any]] = {}
    for mu in mu_values:
        min_viable_nc = None
        for n_c in n_c_values:
            margin, detail = margin_friction_clamp(M_req, R_spar, mu, n_c, L)
            detail["margin"] = round(margin, 3)
            detail["passes"] = margin > 0
            all_rows.append(detail)
            if margin > 0 and min_viable_nc is None:
                min_viable_nc = n_c
        recommended_nc = min_viable_nc * 2.0 if min_viable_nc else None
        rec_margin = None
        if recommended_nc:
            rec_margin, _ = margin_friction_clamp(M_req, R_spar, mu, recommended_nc, L)
        by_mu[mu] = {
            "mu": mu,
            "min_viable_N_c_n": min_viable_nc,
            "recommended_N_c_n": recommended_nc,
            "recommended_margin": round(rec_margin, 3) if rec_margin is not None else None,
        }
    return {
        "mode": "friction_clamp",
        "note": "N_c is total clamp force; mu_d is conservative design friction coefficient",
        "by_mu": by_mu,
        "sweep": all_rows,
    }


def _sweep_external_shear_key(M_req: float, R_key: float) -> dict[str, Any]:
    # Sweep total bonded area (n_key * A_per_key) from 50 mm² to 2000 mm²
    area_values = list(range(50, 2050, 50))  # mm²
    n_key = 2
    rows = []
    min_viable_area = None
    for area_mm2 in area_values:
        A_each = area_mm2 / n_key * 1e-6  # per key in m²
        margin, detail = margin_external_shear_key(
            M_req, R_key, n_key, A_each, TAU_DESIGN_KEY_PA
        )
        detail["total_area_mm2"] = area_mm2
        detail["margin"] = round(margin, 3)
        detail["passes"] = margin > 0
        rows.append(detail)
        if margin > 0 and min_viable_area is None:
            min_viable_area = area_mm2
    recommended_area = min_viable_area * 2.0 if min_viable_area else None
    rec_margin = None
    if recommended_area:
        A_each = recommended_area / n_key * 1e-6
        rec_margin, _ = margin_external_shear_key(M_req, R_key, n_key, A_each, TAU_DESIGN_KEY_PA)
    return {
        "mode": "external_shear_key",
        "tau_design_pa": TAU_DESIGN_KEY_PA,
        "n_keys": n_key,
        "min_viable_total_area_mm2": min_viable_area,
        "recommended_total_area_mm2": recommended_area,
        "recommended_per_key_mm2": round(recommended_area / n_key, 1) if recommended_area else None,
        "recommended_margin": round(rec_margin, 3) if rec_margin is not None else None,
        "note": (
            f"tau_d = {TAU_DESIGN_KEY_PA/1e6:.0f} MPa (conservative knockdown from ~18 MPa); "
            "key bond surface must be in shear, not peel — use tapered ends or carbon tow overwrap"
        ),
        "sweep": rows,
    }


# ---------------------------------------------------------------------------
# Master design search runner
# ---------------------------------------------------------------------------

def run_design_search(freeze: dict[str, Any]) -> dict[str, Any]:
    lf = freeze["load_factor"]
    F_couple = abs(freeze["local_couple_force_n"]) * lf  # factored couple force [N]
    R_spar = freeze["spar_tubes"]["main_spar"]["od_m"] / 2.0  # tube outer radius [m]
    L_contact = freeze["collar"]["collar_contact_width_m"]  # span-wise collar width [m]
    a_current = freeze["bondline"]["bondline_width_m"]  # current bondline width [m]
    peel_allow = freeze["bondline"]["adhesive_peel_allowable_n_per_m"]

    M_req = F_couple * R_spar  # required anti-rotation torque [N·m]
    m_per_width = M_req / L_contact  # moment per unit collar width [N·m/m = N]

    # Baseline: current peel-bond design
    current_margin, current_detail = margin_peel_bond(
        m_per_width, a_current, peel_allow, C_CONSERVATIVE
    )
    theoretical_min, _ = margin_peel_bond(
        m_per_width, a_current, peel_allow, C_THEORETICAL
    )

    # Mode sweeps
    peel_bond_sweep = _sweep_peel_bond(m_per_width, peel_allow, C_LINEAR)
    yoke_sweep = _sweep_load_line_yoke(F_couple, L_contact, a_current, peel_allow, C_LINEAR)
    friction_sweep = _sweep_friction_clamp(
        M_req, R_spar, L_contact, mu_values=[0.10, 0.15, 0.20, 0.25]
    )
    key_sweep = _sweep_external_shear_key(M_req, R_key=R_spar + 0.005)  # key centroid ~5 mm off tube OD

    # Recommended design: saddle ring yoke + secondary friction clamp.
    # This uses the class-based load-path model so the search report and the
    # reusable joint library do not drift into different C04-fix narratives.
    joint_load = JointLoad.from_freeze(freeze)
    recommended_joint = recommended_c04_fix(joint_load)
    recommended_result = recommended_joint.margin(joint_load)
    sub_results = recommended_result.detail.get("sub_results", {})
    modes = {mode.mode_id: mode for mode in recommended_joint.modes}
    saddle_mode = modes["saddle_ring_yoke"]
    clamp_mode = modes["friction_clamp"]
    saddle_result = saddle_mode.margin(joint_load)
    clamp_result = clamp_mode.margin(joint_load)

    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": freeze["candidate_id"],
        "station_id": "R068",
        "load_factor": lf,
        "load_inputs": {
            "F_couple_factored_n": round(F_couple, 4),
            "R_spar_m": round(R_spar, 5),
            "L_contact_m": L_contact,
            "M_req_nm": round(M_req, 5),
            "m_per_width_n": round(m_per_width, 4),
        },
        "allowable_inputs": {
            "peel_allow_n_per_m": peel_allow,
            "tau_design_key_pa": TAU_DESIGN_KEY_PA,
            "current_bondline_m": a_current,
        },
        "baseline_peel_bond": {
            "margin_conservative": round(current_margin, 3),
            "margin_theoretical_min": round(theoretical_min, 3),
            "min_bondline_for_pass_theoretical_mm": round(m_per_width / peel_allow * 1000, 1),
            "verdict": "fail — geometry redesign required",
        },
        "mode_peel_bond": peel_bond_sweep,
        "mode_load_line_yoke": yoke_sweep,
        "mode_friction_clamp": friction_sweep,
        "mode_external_shear_key": key_sweep,
        "recommended_design": {
            "type": "saddle_ring_yoke_plus_secondary_clamp",
            "primary_load_path": "saddle_ring_yoke",
            "description": "conformal saddle ring yoke + secondary friction clamp",
            "components": {
                "saddle_ring_yoke": {
                    "arc_deg": saddle_result.detail["arc_deg"],
                    "ring_width_mm": round(saddle_mode.ring_width_m * 1000.0, 1),
                    "lug_height_mm": saddle_result.detail["lug_height_mm"],
                    "lug_width_mm": round(saddle_mode.lug_width_m * 1000.0, 1),
                    "lug_foot_length_mm": round(saddle_mode.lug_foot_length_m * 1000.0, 1),
                    "tau_adhesive_allow_mpa": saddle_result.detail["tau_adhesive_allow_mpa"],
                    "k_concentration": saddle_result.detail["k_concentration"],
                    "governs": saddle_result.governs,
                },
                "friction_clamp": {
                    "mu": clamp_result.detail["mu"],
                    "N_c_n": clamp_result.detail["N_c_n"],
                    "liner": clamp_result.detail["liner"],
                    "role": clamp_result.detail["role"],
                    "governs": clamp_result.governs,
                },
            },
            "margins": {
                "saddle_ring_yoke": saddle_result.margin,
                "friction_clamp_secondary": clamp_result.margin,
                "sub_results": sub_results,
            },
            "governing_margin": recommended_result.margin,
            "governing_mode": recommended_result.governs,
            "notes": [
                "Primary load path is tangential lug bearing into a conformal saddle ring, not outward adhesive peel.",
                "The friction clamp is secondary positioning/redundancy and is checked independently.",
                "Saddle lug height is kept low to suppress lug-root peel; taper ring ends and add fillet/overwrap.",
                "mu=0.15 remains coupon-owned for the clamp; do not promote worn-in CFRP friction values.",
                "External shear key remains a viable alternate/backup concept but is not the selected P1 fix.",
            ],
        },
        "design_search_summary": {
            "peel_bond_min_viable_bondline_mm": peel_bond_sweep["min_viable_bondline_mm"],
            "yoke_max_viable_r_eff_mm": yoke_sweep["max_viable_r_eff_mm"],
            "friction_clamp_min_N_c_at_mu015": friction_sweep["by_mu"][0.15]["min_viable_N_c_n"],
            "shear_key_min_total_area_mm2": key_sweep["min_viable_total_area_mm2"],
            "recommended_design_type": "saddle_ring_yoke_plus_secondary_clamp",
        },
    }


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------

def _render_report_md(result: dict[str, Any]) -> str:
    li = result["load_inputs"]
    bl = result["baseline_peel_bond"]
    rec = result["recommended_design"]
    ds = result["design_search_summary"]
    pb = result["mode_peel_bond"]
    yk = result["mode_load_line_yoke"]
    fc = result["mode_friction_clamp"]
    sk = result["mode_external_shear_key"]

    lines = [
        "# Current Pathfinder Rib Collar Joint — Design Search (C04 Fix)",
        "",
        "> Date: 2026-05-11",
        f"> Candidate: `{result['candidate_id']}`",
        "> Station: R068 at y = 2.328 m",
        f"> Schema: `{result['schema_version']}`",
        "",
        "## Problem Statement",
        "",
        "The Step 2 analytical margin run showed that the current peel-bond collar design",
        f"(15 mm bondline, peel allowable {result['allowable_inputs']['peel_allow_n_per_m']:.0f} N/m) fails",
        f"with margin {bl['margin_conservative']:.3f} (conservative) and {bl['margin_theoretical_min']:.3f}",
        "(theoretical minimum — geometry-only lower bound, independent of stress distribution).",
        f"Even under the best possible stress distribution, the bondline needs ≥"
        f" {bl['min_bondline_for_pass_theoretical_mm']:.0f} mm.",
        "",
        "**Root cause**: the rib couple force F acts at the spar tube axis. The collar",
        f"bond surface is at radius r = {li['R_spar_m']*1000:.0f} mm. This eccentricity creates",
        f"a peel moment M = F×r = {li['F_couple_factored_n']:.2f}×{li['R_spar_m']*1000:.0f} mm",
        f"= {li['M_req_nm']:.3f} N·m that the 15 mm bondline cannot resist in peel.",
        "",
        "## Load Inputs (from Step 1 freeze sheet)",
        "",
        "| parameter | value |",
        "|---|---:|",
        f"| Factored couple force F | {li['F_couple_factored_n']:.3f} N |",
        f"| Spar OD radius R | {li['R_spar_m']*1000:.0f} mm |",
        f"| Collar contact width L | {li['L_contact_m']*1000:.0f} mm |",
        f"| Required anti-rotation torque M_req | {li['M_req_nm']:.4f} N·m |",
        f"| Moment per unit collar width m | {li['m_per_width_n']:.3f} N |",
        "",
        "## Mode 1: Peel Bond (current design — sweep bondline width)",
        "",
        f"Minimum viable bondline (linear model): **{pb['min_viable_bondline_mm']} mm**.",
        f"Recommended (1.5×): **{pb['recommended_bondline_mm']} mm**, margin {pb['recommended_margin']:.2f}.",
        "Current bondline is 15 mm. Widening to 105 mm requires a major geometry change",
        "and still leaves the bondline working in its weakest mode (peel).",
        "",
        "| bondline mm | peel demand N/m | margin | pass |",
        "|---:|---:|---:|---|",
    ]
    for row in pb["sweep"][::4]:  # every 20 mm
        lines.append(
            f"| {row['bondline_width_mm']:.0f} | {row['f_peel_demand_n_per_m']:.0f}"
            f" | {row['margin']:.2f} | {'✓' if row['passes'] else '✗'} |"
        )

    lines += [
        "",
        "## Mode 2: Load-Line Yoke (reduce eccentricity)",
        "",
        "Route the rib reaction force through a clevis/yoke so it acts close to the",
        "tube centreline. Reducing r_eff from 50 mm to a small value eliminates most",
        "of the peel moment while keeping the bondline in the joint.",
        "",
        f"Maximum viable r_eff (linear model, a=15 mm): **{yk['max_viable_r_eff_mm']} mm**.",
        f"Recommended r_eff (0.67× max): **{yk['recommended_r_eff_mm']} mm**,",
        f"margin {yk['recommended_margin']:.2f}.",
        "",
        "| r_eff mm | m_eff N | peel demand N/m | margin | pass |",
        "|---:|---:|---:|---:|---|",
    ]
    for row in yk["sweep"][::5]:  # every 5 mm
        lines.append(
            f"| {row['r_eff_mm']:.0f} | {row['m_eff_per_width_n']:.3f}"
            f" | {row['f_peel_demand_n_per_m']:.0f}"
            f" | {row['margin']:.2f} | {'✓' if row['passes'] else '✗'} |"
        )

    lines += [
        "",
        "## Mode 3: Friction Clamp (split clamp collar)",
        "",
        "A split clamp (two half-shells with through-bolts) grips the spar OD.",
        "Clamp force N_c generates friction torque M = μ × N_c × R.",
        "Contact pressure on CFRP tube is checked separately.",
        "",
        "| μ | Min N_c [N] | Recommended N_c [N] | Margin at rec. |",
        "|---:|---:|---:|---:|",
    ]
    for mu_val, mu_data in fc["by_mu"].items():
        lines.append(
            f"| {mu_val:.2f} | {mu_data['min_viable_N_c_n'] or 'N/A'}"
            f" | {mu_data['recommended_N_c_n'] or 'N/A'}"
            f" | {mu_data['recommended_margin'] or 'N/A'} |"
        )

    lines += [
        "",
        "> Contact pressure at N_c=600 N over half-circumference contact:",
        f"> p = 600 / (π × {li['R_spar_m']*1000:.0f}mm × {li['L_contact_m']*1000:.0f}mm)",
        f"> = {600 / (math.pi * li['R_spar_m'] * li['L_contact_m']):.0f} Pa — very low, not governing.",
        "",
        "## Mode 4: External Shear Key",
        "",
        "Two bonded anti-rotation blocks on the spar OD transmit the rib torque via",
        f"**adhesive shear** (not peel). Design shear allowable: τ_d = {sk['tau_design_pa']/1e6:.0f} MPa",
        "(conservative knockdown from ~18 MPa to account for peel concentration at key ends;",
        "key edges must be tapered or wrapped with carbon tow).",
        "",
        f"Minimum viable total bonded area: **{sk['min_viable_total_area_mm2']} mm²**.",
        f"Recommended (2× minimum): **{sk['recommended_total_area_mm2']} mm²**",
        f"= **{sk['recommended_per_key_mm2']:.0f} mm²** per key ({sk['n_keys']} keys),",
        f"margin **{sk['recommended_margin']:.1f}**.",
        "",
        "Example: each key = 10 mm × 15 mm = 150 mm², two keys = 300 mm².",
        "",
        "## Recommended Design",
        "",
        f"**{rec['description']}**",
        "",
        "The selected P1 C04 fix is now the same load path used by",
        "`recommended_c04_fix()`: a conformal saddle ring with tangential lugs",
        "that routes the rib reaction as a couple around the spar, plus a secondary",
        "friction clamp for positioning/redundancy. The external shear-key sweep",
        "above remains an alternate concept, not the selected P1 baseline.",
        "",
        "| load path | governing margin | role |",
        "|---|---:|---|",
        f"| Saddle ring yoke ({rec['components']['saddle_ring_yoke']['arc_deg']:.0f} deg arc, "
        f"{rec['components']['saddle_ring_yoke']['lug_height_mm']:.1f} mm lugs) | "
        f"{rec['margins']['saddle_ring_yoke']:.2f} | primary |",
        f"| Friction clamp (μ={rec['components']['friction_clamp']['mu']:.2f}, "
        f"N_c={rec['components']['friction_clamp']['N_c_n']:.0f} N) | "
        f"{rec['margins']['friction_clamp_secondary']:.2f} | secondary |",
        "",
        f"**Governing margin: {rec['governing_margin']:.2f}** ({rec['governing_mode']}).",
        "",
        "Notes:",
    ]
    for note in rec["notes"]:
        lines.append(f"- {note}")

    lines += [
        "",
        "## Design Search Summary",
        "",
        "| mode | minimum viable geometry | current geometry | verdict |",
        "|---|---|---|---|",
        f"| peel bond | {ds['peel_bond_min_viable_bondline_mm']} mm bondline"
        f" | 15 mm | ✗ needs {ds['peel_bond_min_viable_bondline_mm'] / 15:.0f}× increase |",
        f"| yoke | r_eff ≤ {ds['yoke_max_viable_r_eff_mm']} mm"
        f" | r=50 mm | ✓ achievable with clevis/saddle |",
        f"| friction clamp (μ=0.15) | N_c ≥ {ds['friction_clamp_min_N_c_at_mu015']} N"
        f" | none | ✓ achievable with M3–M4 bolts |",
        f"| external shear key | ≥ {ds['shear_key_min_total_area_mm2']} mm² total"
        f" | none | ✓ alternate / backup, not selected P1 baseline |",
        "",
        "## What Needs Physical Verification",
        "",
        "1. **μ coupon**: friction coefficient for CFRP-on-CFRP (or on liner material)",
        "   with realistic clamp pressure and surface finish — do not assume μ=0.15 without test.",
        "2. **Shear key bond coupon**: verify τ_d ≥ 2 MPa for the actual key geometry with",
        "   tapered edges. Check that key-end peel does not drive failure before shear.",
        "3. **Saddle/yoke geometry**: confirm that the rib yoke bears on the",
        "   tangential lug pair without prying the ring edge, and that lug height,",
        "   fillets, taper, and overwrap match the surrogate geometry.",
        "4. **Clamp repeatability**: verify that bolt preload after repeated assembly /",
        "   disassembly maintains the required N_c (use torque wrench, calibrated fastener).",
    ]
    return "\n".join(lines)


def _write_sweep_csv(result: dict[str, Any], path: Path) -> None:
    rows = []
    for mode_key in ("mode_peel_bond", "mode_load_line_yoke",
                      "mode_friction_clamp", "mode_external_shear_key"):
        mode_data = result[mode_key]
        for row in mode_data.get("sweep", []):
            flat = {"mode": mode_data["mode"]}
            flat.update({k: v for k, v in row.items() if not isinstance(v, dict)})
            rows.append(flat)
    if not rows:
        return
    fieldnames = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_design_search_package(
    *,
    freeze_json: Path = DEFAULT_FREEZE_JSON,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
) -> dict[str, Path]:
    freeze = json.loads(freeze_json.read_text(encoding="utf-8"))
    result = run_design_search(freeze)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)

    full_json_path = output_dir / "collar_joint_design_search.json"
    full_json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    sweep_csv_path = output_dir / "collar_joint_design_sweep.csv"
    _write_sweep_csv(result, sweep_csv_path)

    md_text = _render_report_md(result)
    report_md.write_text(md_text, encoding="utf-8")

    # Compact summary for downstream consumers
    summary = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": result["candidate_id"],
        "station_id": result["station_id"],
        "baseline_margin_conservative": result["baseline_peel_bond"]["margin_conservative"],
        "baseline_margin_theoretical_min": result["baseline_peel_bond"]["margin_theoretical_min"],
        "peel_bond_min_viable_bondline_mm": result["design_search_summary"]["peel_bond_min_viable_bondline_mm"],
        "yoke_max_viable_r_eff_mm": result["design_search_summary"]["yoke_max_viable_r_eff_mm"],
        "friction_clamp_min_N_c_at_mu015": result["design_search_summary"]["friction_clamp_min_N_c_at_mu015"],
        "shear_key_min_total_area_mm2": result["design_search_summary"]["shear_key_min_total_area_mm2"],
        "recommended_design_type": result["design_search_summary"]["recommended_design_type"],
        "recommended_governing_margin": result["recommended_design"]["governing_margin"],
        "verdict": "redesign_required_viable_alternatives_identified",
    }
    report_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "full_json": full_json_path,
        "sweep_csv": sweep_csv_path,
        "report_md": report_md,
        "report_json": report_json,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-json", type=Path, default=DEFAULT_FREEZE_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    args = parser.parse_args(argv)

    paths = write_design_search_package(
        freeze_json=args.freeze_json,
        output_dir=args.output_dir,
        report_json=args.report_json,
        report_md=args.report_md,
    )
    print(f"full JSON:  {paths['full_json']}")
    print(f"sweep CSV:  {paths['sweep_csv']}")
    print(f"report MD:  {paths['report_md']}")
    print(f"report JSON:{paths['report_json']}")


if __name__ == "__main__":
    main()
