#!/usr/bin/env python3
"""Step 2: P1 local detail margin run for y=2.328 m rib / collar zone.

Reads the Step 1 geometry and allowable freeze sheet and produces refined
analytical margins for the seven local failure modes. Improvements over the
Step 1 preliminary screen:

  C02/C03: shear stress concentration factor (Goland-Reissner simplified) at
    bond ends; step-1 used uniform shear only.
  C04: eccentric moment model (M = F × r_spar) replacing the 0.20 fraction proxy.
  C05: Hertz curvature correction for curved-surface collar bearing.
  C06: full thin-wall Lamé hoop stress with pressure computed from distributed
    collar contact (same result as step-1 but with cleaner derivation chain).
  C07: parametric pre-strain sweep from 0.005 % to 0.10 %, finds minimum viable
    pre-strain for the sag criterion, and identifies the process specification
    target.

This is an analytical pre-margin run, not final FEM sign-off. The refined
margins update Step 1 preliminary values and identify which modes require
physical coupon or full FEM verification before claim.
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


SCHEMA_VERSION = "rib_local_detail_margin_run_v2"
CLAIM_BOUNDARY = (
    "Step 2 analytical margin run. Improvements over step-1 preliminary: SCF "
    "for bond shear ends, eccentric-moment peel model, Hertz bearing curvature "
    "correction, Lame tube-wall, and parametric skin-sag sweep. "
    "This is still analytical, not physical coupon or full FEM sign-off."
)

DEFAULT_FREEZE_JSON = (
    REPO_ROOT / "output" / "current_pathfinder_rib_local_detail_geometry_freeze"
    / "geometry_allowable_freeze.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_rib_local_detail_margin_run"
DEFAULT_REPORT_JSON = (
    REPO_ROOT / "docs" / "reports"
    / "2026-05-11_current_pathfinder_rib_local_detail_margin_run.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT / "docs" / "reports"
    / "2026-05-11_current_pathfinder_rib_local_detail_margin_run.md"
)

PRESTRAIN_SWEEP_VALUES = [
    0.00005, 0.0001, 0.0002, 0.0003, 0.0005,
    0.0007, 0.001, 0.0015, 0.002,
]


def _solve_membrane_nonlinear(p: float, E: float, t: float, L: float, eps0: float) -> float:
    """Solve geometric-nonlinear membrane sag by bisection.

    Governing equation (parabolic arc, fixed ends, uniform pressure):
        p = (8Et/L²) * s * [eps0 + (8/3)*(s/L)²]

    The geometric strain (8/3)*(s/L)² increases membrane tension as sag grows,
    making the nonlinear sag smaller than the constant-tension linear estimate.
    """
    A = 8.0 * E * t * eps0 / L**2
    B = 64.0 * E * t / (3.0 * L**4)
    # Linear solution p = A*s gives the upper bound; 0 is the lower bound.
    s_lo, s_hi = 0.0, p / max(A, 1e-30)
    for _ in range(60):
        s_mid = 0.5 * (s_lo + s_hi)
        if A * s_mid + B * s_mid**3 > p:
            s_hi = s_mid
        else:
            s_lo = s_mid
    return 0.5 * (s_lo + s_hi)


def _fval(v: Any, default: float) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _compute_c02_c03_bond_shear_refined(
    freeze: dict[str, Any],
    load_factor: float,
) -> dict[str, Any]:
    main = freeze["spar_tubes"]["main_spar"]
    rear = freeze["spar_tubes"]["rear_spar"]
    collar = freeze["collar"]
    bond = freeze["bondline"]

    local_couple_force_n = abs(freeze["local_couple_force_n"])
    design_force = local_couple_force_n * load_factor

    main_od = main["od_m"]
    rear_od = rear["od_m"]
    contact_width = collar["collar_contact_width_m"]
    bond_width = bond["bondline_width_m"]
    bond_thickness = bond["bondline_thickness_m"]
    allow = bond["adhesive_shear_allowable_pa"]

    # Average bond shear (same as step-1 half-circumference model).
    bond_area_main = math.pi * main_od * contact_width / 2.0
    bond_area_rear = math.pi * rear_od * contact_width / 2.0
    avg_shear_main = design_force / bond_area_main
    avg_shear_rear = design_force / bond_area_rear

    # Shear stress concentration at bond ends (Goland-Reissner simplified).
    # For a lap joint of length a with adhesive shear modulus G_adh, thickness t_adh,
    # adherend modulus E_sub, thickness t_sub:
    #   lambda = sqrt(G_adh / (t_adh * E_sub * t_sub))
    #   SCF ≈ 1 + lambda * a (for lambda*a >> 1: peak ≈ avg * lambda*a / 2)
    # Use collar_contact_width as lap length, bond_width as adherend "thickness".
    G_adh = _fval(bond.get("adhesive_shear_modulus_pa"), 1.5e9)
    E_sub = 45.0e9
    t_sub = bond_width
    t_adh = bond_thickness
    lam = math.sqrt(G_adh / max(t_adh * E_sub * t_sub, 1e-20))
    la = lam * contact_width
    if la > 0.1:
        scf = la / math.tanh(la)
    else:
        scf = 1.0
    scf = min(scf, 3.0)

    peak_shear_main = avg_shear_main * scf
    peak_shear_rear = avg_shear_rear * scf
    margin_main = allow / peak_shear_main - 1.0
    margin_rear = allow / peak_shear_rear - 1.0

    return {
        "model": "goland_reissner_simplified_scf",
        "design_couple_force_n": round(design_force, 4),
        "bond_area_main_m2": round(bond_area_main, 8),
        "bond_area_rear_m2": round(bond_area_rear, 8),
        "scf_lambda_a": round(la, 4),
        "scf_applied": round(scf, 4),
        "avg_shear_main_pa": round(avg_shear_main, 1),
        "avg_shear_rear_pa": round(avg_shear_rear, 1),
        "C02_peak_shear_main_pa": round(peak_shear_main, 1),
        "C02_margin": round(margin_main, 3),
        "C02_status": "pass" if margin_main > 0 else "concern",
        "C03_peak_shear_rear_pa": round(peak_shear_rear, 1),
        "C03_margin": round(margin_rear, 3),
        "C03_status": "pass" if margin_rear > 0 else "concern",
        "allowable_pa": allow,
        "step1_scf": 1.0,
        "step2_improvement": "SCF at bond ends replaces uniform shear assumption",
    }


def _compute_c04_peel_refined(
    freeze: dict[str, Any],
    load_factor: float,
) -> dict[str, Any]:
    main = freeze["spar_tubes"]["main_spar"]
    collar = freeze["collar"]
    bond = freeze["bondline"]

    local_couple_force_n = abs(freeze["local_couple_force_n"])
    design_force = local_couple_force_n * load_factor

    r_spar = main["od_m"] / 2.0
    contact_width = collar["collar_contact_width_m"]
    bond_width = bond["bondline_width_m"]
    peel_allow_n_per_m = bond["adhesive_peel_allowable_n_per_m"]

    # Eccentric moment model.
    # The couple force F acts at the spar tube axis. The collar tab bond surface
    # is at radius r_spar from the axis. The moment per unit span-width:
    #   m = F * r_spar / contact_width  [N·m / m]
    # For a bonded tab of lap length a = bond_width, using rigid-adherend peel:
    #   peak peel stress σ = 6 * m / a²  [Pa]
    # Equivalent peel force per unit width (to compare with G_c allowable):
    #   F_peel_per_width = σ * a / 3  [N/m]  (triangular distribution resultant)
    m_per_width = design_force * r_spar / contact_width
    a = bond_width
    peak_peel_stress_pa = 6.0 * m_per_width / a**2
    f_peel_per_width = peak_peel_stress_pa * a / 3.0

    margin = peel_allow_n_per_m / f_peel_per_width - 1.0

    # Theoretical minimum: any peel distribution balancing the moment couple
    # requires N+ >= m_per_width / a (best-case N+/N- couple at bondline ends).
    # This lower bound is geometry-only and cannot be improved by material choice.
    theoretical_min_peel = m_per_width / a
    theoretical_min_margin = peel_allow_n_per_m / theoretical_min_peel - 1.0
    # Minimum bondline width needed for theoretical lower bound to just pass.
    min_bondline_for_pass_m = m_per_width / peel_allow_n_per_m

    return {
        "model": "eccentric_moment_rigid_adherend",
        "design_force_n": round(design_force, 4),
        "r_spar_m": round(r_spar, 6),
        "moment_per_width_n": round(m_per_width, 4),
        "lap_length_m": a,
        "peak_peel_stress_pa": round(peak_peel_stress_pa, 1),
        "f_peel_per_width_n_per_m": round(f_peel_per_width, 4),
        "peel_allowable_n_per_m": peel_allow_n_per_m,
        "C04_margin": round(margin, 3),
        "C04_status": "pass" if margin > 0 else "concern",
        "c04_theoretical_min_peel_n_per_m": round(theoretical_min_peel, 4),
        "c04_theoretical_min_margin": round(theoretical_min_margin, 3),
        "c04_min_bondline_for_pass_m": round(min_bondline_for_pass_m, 5),
        "c04_min_bondline_for_pass_mm": round(min_bondline_for_pass_m * 1000, 1),
        "step1_model": "peel_fraction_0.20_of_shear",
        "step1_margin": 2.57,
        "step2_improvement": "eccentric moment M=F*r_spar replaces empirical peel fraction",
    }


def _compute_c05_bearing_refined(
    freeze: dict[str, Any],
    load_factor: float,
) -> dict[str, Any]:
    collar = freeze["collar"]

    local_couple_force_n = abs(freeze["local_couple_force_n"])
    design_force = local_couple_force_n * load_factor

    t_collar = collar["collar_thickness_m"]
    contact_width = collar["collar_contact_width_m"]
    allow = collar["collar_bearing_allowable_pa"]

    # Hertz-like curvature correction for contact of a flat strip (collar)
    # pressed against a convex cylinder (spar tube outer surface).
    # For cylinder-on-flat (collar wrapping outer surface): the projected bearing
    # area is multiplied by pi/4 to account for actual contact pressure distribution.
    # This gives a HIGHER effective area → LOWER stress → step-2 is less conservative.
    proj_area = contact_width * t_collar
    hertz_area = proj_area * math.pi / 4.0
    bearing_stress = design_force / hertz_area
    margin = allow / bearing_stress - 1.0

    return {
        "model": "hertz_curvature_correction_flat_on_cylinder",
        "design_force_n": round(design_force, 4),
        "proj_bearing_area_m2": round(proj_area, 8),
        "hertz_bearing_area_m2": round(hertz_area, 8),
        "curvature_factor": round(math.pi / 4.0, 4),
        "bearing_stress_pa": round(bearing_stress, 1),
        "C05_bearing_allowable_pa": allow,
        "C05_margin": round(margin, 3),
        "C05_status": "pass" if margin > 0 else "concern",
        "step1_margin": 355.55,
        "step2_improvement": "pi/4 curvature factor increases effective area vs projected area",
    }


def _compute_c06_tube_crush_refined(
    freeze: dict[str, Any],
    load_factor: float,
) -> dict[str, Any]:
    main = freeze["spar_tubes"]["main_spar"]
    rear = freeze["spar_tubes"]["rear_spar"]
    collar = freeze["collar"]
    crush_allow = (
        freeze["materials_summary"].get("carbon_fiber_hm", {}).get("compressive_strength", 1500e6) * 0.25
    )

    local_couple_force_n = abs(freeze["local_couple_force_n"])
    design_force = local_couple_force_n * load_factor
    contact_width = collar["collar_contact_width_m"]

    def _lame_hoop(od_m: float, wall_m: float, f_n: float, l_m: float) -> dict[str, Any]:
        r_o = od_m / 2.0
        r_i = r_o - wall_m
        contact_perimeter = math.pi * od_m
        pressure_pa = f_n / (l_m * contact_perimeter)
        sigma_hoop_inner = pressure_pa * r_o**2 * (r_o**2 + r_i**2) / (r_i * (r_o**2 - r_i**2))
        sigma_hoop_outer = 2.0 * pressure_pa * r_o**2 / (r_o**2 - r_i**2)
        sigma_peak = max(sigma_hoop_inner, sigma_hoop_outer)
        return {
            "r_o_m": round(r_o, 6),
            "r_i_m": round(r_i, 6),
            "contact_pressure_pa": round(pressure_pa, 1),
            "sigma_hoop_inner_pa": round(sigma_hoop_inner, 1),
            "sigma_hoop_outer_pa": round(sigma_hoop_outer, 1),
            "sigma_peak_pa": round(sigma_peak, 1),
            "margin": round(crush_allow / sigma_peak - 1.0, 3),
        }

    main_res = _lame_hoop(main["od_m"], main["wall_m"], design_force, contact_width)
    rear_res = _lame_hoop(rear["od_m"], rear["wall_m"], design_force, contact_width)

    return {
        "model": "lame_thick_wall_cylinder",
        "crush_allowable_pa": crush_allow,
        "C06_main": main_res,
        "C06_rear": rear_res,
        "C06_main_margin": main_res["margin"],
        "C06_main_status": "pass" if main_res["margin"] > 0 else "concern",
        "C06_rear_margin": rear_res["margin"],
        "C06_rear_status": "pass" if rear_res["margin"] > 0 else "concern",
        "step2_improvement": "Lame hoop at inner and outer wall; contact pressure from full circumference",
    }


def _compute_c07_skin_sag_sweep(
    freeze: dict[str, Any],
) -> dict[str, Any]:
    skin = freeze["skin"]
    q_cruise_pa = 0.5 * 1.225 * 6.5**2
    chord_m = freeze["chord_m"]
    bay_length_m = 0.291048
    p_normal_per_span = q_cruise_pa * chord_m
    sag_allow_m = skin["sag_allowable_fraction_chord"] * chord_m
    E_skin = skin["skin_E_pa"]
    t_skin = skin["skin_thickness_m"]

    sweep_results = []
    min_viable_prestrain = None
    min_viable_prestrain_nl = None
    for prestrain in PRESTRAIN_SWEEP_VALUES:
        T = E_skin * t_skin * prestrain
        if T <= 0:
            continue
        sag_m = p_normal_per_span * bay_length_m**2 / (8.0 * T)
        sag_nl_m = _solve_membrane_nonlinear(
            p_normal_per_span, E_skin, t_skin, bay_length_m, prestrain
        )
        sag_fraction = sag_m / chord_m
        sag_nl_fraction = sag_nl_m / chord_m
        margin = sag_allow_m / sag_m - 1.0
        margin_nl = sag_allow_m / sag_nl_m - 1.0
        passes = margin > 0
        passes_nl = margin_nl > 0
        if passes and min_viable_prestrain is None:
            min_viable_prestrain = prestrain
        if passes_nl and min_viable_prestrain_nl is None:
            min_viable_prestrain_nl = prestrain
        sweep_results.append({
            "prestrain_pct": round(prestrain * 100, 4),
            "T_membrane_n_per_m": round(T, 4),
            "sag_m": round(sag_m, 6),
            "sag_pct_chord": round(sag_fraction * 100, 4),
            "margin": round(margin, 4),
            "passes": passes,
            "sag_nonlinear_m": round(sag_nl_m, 6),
            "sag_nonlinear_pct_chord": round(sag_nl_fraction * 100, 4),
            "margin_nonlinear": round(margin_nl, 4),
            "passes_nonlinear": passes_nl,
        })

    nominal = next(r for r in sweep_results if abs(r["prestrain_pct"] - 0.05) < 0.001)

    return {
        "model": "membrane_tension_sag_parametric_sweep",
        "q_cruise_pa": round(q_cruise_pa, 2),
        "chord_m": chord_m,
        "bay_length_m": bay_length_m,
        "sag_allowable_m": round(sag_allow_m, 6),
        "sag_allowable_pct_chord": round(skin["sag_allowable_fraction_chord"] * 100, 3),
        "skin_E_pa": E_skin,
        "skin_thickness_m": t_skin,
        "nominal_prestrain_pct": 0.05,
        "nominal_sag_m": nominal["sag_m"],
        "nominal_sag_pct_chord": nominal["sag_pct_chord"],
        "nominal_margin": nominal["margin"],
        "nominal_sag_nonlinear_m": nominal["sag_nonlinear_m"],
        "nominal_sag_nonlinear_pct_chord": nominal["sag_nonlinear_pct_chord"],
        "nominal_margin_nonlinear": nominal["margin_nonlinear"],
        "min_viable_prestrain_pct": (
            round(min_viable_prestrain * 100, 4) if min_viable_prestrain else None
        ),
        "process_target_prestrain_pct": (
            round(min_viable_prestrain * 100 * 2.0, 4)
            if min_viable_prestrain else None
        ),
        "min_viable_prestrain_nonlinear_pct": (
            round(min_viable_prestrain_nl * 100, 4) if min_viable_prestrain_nl else None
        ),
        "sweep": sweep_results,
        "C07_margin": nominal["margin"],
        "C07_status": "pass" if nominal["margin"] > 0 else "concern",
        "step2_improvement": (
            "parametric sweep with linear and geometric-nonlinear membrane models; "
            "min viable pre-strain and 2x process target derived"
        ),
    }


def _run_all_margins(freeze: dict[str, Any]) -> dict[str, Any]:
    lf = freeze["load_factor"]
    step1 = freeze["preliminary_margins"]

    c02c03 = _compute_c02_c03_bond_shear_refined(freeze, lf)
    c04 = _compute_c04_peel_refined(freeze, lf)
    c05 = _compute_c05_bearing_refined(freeze, lf)
    c06 = _compute_c06_tube_crush_refined(freeze, lf)
    c07 = _compute_c07_skin_sag_sweep(freeze)

    c01_margin = step1["C01_cap_shear_transfer"]["margin"]

    all_margins = {
        "C01": c01_margin,
        "C02": c02c03["C02_margin"],
        "C03": c02c03["C03_margin"],
        "C04": c04["C04_margin"],
        "C05": c05["C05_margin"],
        "C06_main": c06["C06_main_margin"],
        "C06_rear": c06["C06_rear_margin"],
        "C07": c07["C07_margin"],
    }
    worst_margin = min(all_margins.values())
    worst_coupon = min(all_margins, key=all_margins.__getitem__)
    all_pass = all(v > 0 for v in all_margins.values())

    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": freeze["candidate_id"],
        "station_id": "R068",
        "load_factor": lf,
        "C01_cap_shear": {
            "margin": c01_margin,
            "model": "step1_unchanged",
            "status": "pass" if c01_margin > 0 else "concern",
        },
        "C02_C03_bond_shear": c02c03,
        "C04_bond_peel": c04,
        "C05_collar_bearing": c05,
        "C06_tube_crush": c06,
        "C07_skin_sag": c07,
        "summary": {
            "all_margins": all_margins,
            "worst_margin": round(worst_margin, 4),
            "worst_coupon": worst_coupon,
            "all_pass": all_pass,
            "verdict": (
                "step2_analytical_margins_pass" if all_pass
                else "step2_analytical_concern_review_needed"
            ),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _render_report_md(result: dict[str, Any], freeze: dict[str, Any]) -> str:
    s = result["summary"]
    c02c03 = result["C02_C03_bond_shear"]
    c04 = result["C04_bond_peel"]
    c05 = result["C05_collar_bearing"]
    c06 = result["C06_tube_crush"]
    c07 = result["C07_skin_sag"]
    step1 = freeze["preliminary_margins"]

    def _pf(m: float) -> str:
        return "pass" if m > 0 else "**CONCERN**"

    lines = [
        "# Current Pathfinder Rib / Local Detail Margin Run (Step 2)",
        "",
        "> Date: 2026-05-11",
        f"> Candidate: `{result['candidate_id']}`",
        "> Station: R068 at y = 2.328 m",
        f"> Schema: `{result['schema_version']}`",
        "",
        "## Purpose",
        "",
        "Step 2 of the FEM/Coupon Plan. Reads the Step 1 geometry freeze sheet and",
        "applies refined analytical mechanics models for each failure mode.",
        "Key improvements: SCF for bond shear end concentration, eccentric-moment",
        "peel model, Hertz curvature correction for collar bearing, Lamé thick-wall",
        "tube stress, and parametric skin-sag sweep to find the minimum viable",
        "covering pre-strain.",
        "",
        "## Step 1 → Step 2 Margin Comparison",
        "",
        "| coupon | failure mode | step 1 margin | step 2 margin | delta | model change |",
        "|---|---|---:|---:|---:|---|",
        f"| C01 | cap shear transfer | {step1['C01_cap_shear_transfer']['margin']:.2f} | {result['C01_cap_shear']['margin']:.2f} | 0.00 | unchanged |",
        f"| C02 | main bond shear | {step1['C02_main_spar_bond_shear']['margin']:.1f} | {c02c03['C02_margin']:.1f} | {c02c03['C02_margin'] - step1['C02_main_spar_bond_shear']['margin']:.1f} | SCF={c02c03['scf_applied']:.2f} added |",
        f"| C03 | rear bond shear | {step1['C03_rear_spar_bond_shear']['margin']:.1f} | {c02c03['C03_margin']:.1f} | {c02c03['C03_margin'] - step1['C03_rear_spar_bond_shear']['margin']:.1f} | SCF={c02c03['scf_applied']:.2f} added |",
        f"| C04 | bond peel | {step1['C04_bond_peel_main']['margin']:.2f} | {c04['C04_margin']:.2f} | {c04['C04_margin'] - step1['C04_bond_peel_main']['margin']:.2f} | eccentric moment replaces 0.20 fraction |",
        f"| C05 | collar bearing | {step1['C05_collar_bearing']['margin']:.1f} | {c05['C05_margin']:.1f} | {c05['C05_margin'] - step1['C05_collar_bearing']['margin']:.1f} | π/4 Hertz correction |",
        f"| C06-M | tube crush (main) | {step1['C06_tube_crush_main']['margin']:.1f} | {c06['C06_main_margin']:.1f} | {c06['C06_main_margin'] - step1['C06_tube_crush_main']['margin']:.1f} | Lamé hoop (inner wall) |",
        f"| C06-R | tube crush (rear) | {step1['C06_tube_crush_rear']['margin']:.1f} | {c06['C06_rear_margin']:.1f} | {c06['C06_rear_margin'] - step1['C06_tube_crush_rear']['margin']:.1f} | Lamé hoop (inner wall) |",
        f"| C07 | skin sag (nominal) | {step1['C07_skin_sag']['margin']:.3f} | {c07['C07_margin']:.3f} | {c07['C07_margin'] - step1['C07_skin_sag']['margin']:.3f} | same nominal; see sweep below |",
        "",
        f"**Worst step-2 margin: {s['worst_margin']:.3f}** ({s['worst_coupon']}). All pass: **{s['all_pass']}**.",
        "",
        "## C04 Bond Peel — Eccentric Moment Model",
        "",
        "The torque-couple force F acts at the spar tube axis. The collar bond surface is",
        f"at radius r_spar = {freeze['spar_tubes']['main_spar']['od_m']/2*1000:.0f} mm.",
        "The eccentricity creates a peel moment M = F × r_spar per unit collar width.",
        "",
        "| item | value |",
        "|---|---:|",
        f"| design force (factored) | {c04['design_force_n']:.3f} N |",
        f"| r_spar | {c04['r_spar_m']*1000:.0f} mm |",
        f"| moment per width | {c04['moment_per_width_n']:.4f} N·m/m |",
        f"| lap length (bondline width) | {c04['lap_length_m']*1000:.0f} mm |",
        f"| peak peel stress | {c04['peak_peel_stress_pa']:.0f} Pa = {c04['peak_peel_stress_pa']/1e6:.4f} MPa |",
        f"| peel force per width | {c04['f_peel_per_width_n_per_m']:.4f} N/m |",
        f"| peel allowable | {c04['peel_allowable_n_per_m']:.0f} N/m |",
        f"| **C04 margin (rigid)** | **{c04['C04_margin']:.3f}** ({_pf(c04['C04_margin'])}) |",
        f"| Theoretical min peel (any distribution) | {c04['c04_theoretical_min_peel_n_per_m']:.0f} N/m |",
        f"| **Theoretical min margin** | **{c04['c04_theoretical_min_margin']:.3f}** ({_pf(c04['c04_theoretical_min_margin'])}) |",
        f"| Min bondline needed to pass (theoretical) | {c04['c04_min_bondline_for_pass_mm']:.0f} mm (current: 15 mm) |",
        "",
        f"> Step 1 margin was 2.57 (peel_fraction=0.20). Step 2 eccentric moment gives {c04['C04_margin']:.3f}.",
        "> The theoretical minimum bound (independent of stress distribution) gives"
        f" margin = {c04['c04_theoretical_min_margin']:.3f}: the 15 mm bondline is geometrically",
        f"> insufficient. The bondline must be ≥ {c04['c04_min_bondline_for_pass_mm']:.0f} mm, or the peel moment",
        "> must be redirected to a different load path (mechanical wrap, pin, bearing contact).",
        "",
        "## C07 Skin Sag — Process Sensitivity Sweep",
        "",
        "The sag is inversely proportional to the covering pre-strain. This sweep shows the",
        f"sensitivity over the realistic manufacturing range ({PRESTRAIN_SWEEP_VALUES[0]*100:.3f}–{PRESTRAIN_SWEEP_VALUES[-1]*100:.2f}% pre-strain).",
        "",
        "| pre-strain % | T N/m | sag linear mm | sag NL mm | margin linear | margin NL | pass (NL) |",
        "|---:|---:|---:|---:|---:|---:|---|",
    ]

    for row in c07["sweep"]:
        lines.append(
            f"| {row['prestrain_pct']:.4f} | {row['T_membrane_n_per_m']:.2f} | "
            f"{row['sag_m']*1000:.2f} | {row['sag_nonlinear_m']*1000:.2f} | "
            f"{row['margin']:.3f} | {row['margin_nonlinear']:.3f} | "
            f"{'pass' if row['passes_nonlinear'] else '**FAIL**'} |"
        )

    lines += [
        "",
        f"Linear model: minimum viable pre-strain **{c07['min_viable_prestrain_pct']} %**"
        f" (nonlinear: **{c07['min_viable_prestrain_nonlinear_pct']} %**).",
        f"Recommended process target (2× linear minimum): **{c07['process_target_prestrain_pct']} %**.",
        f"Nonlinear nominal margin (0.05% pre-strain): **{c07['nominal_margin_nonlinear']:.3f}**"
        f" (linear: {c07['nominal_margin']:.3f}). Linear is conservative by"
        f" ~{(1 - c07['nominal_sag_nonlinear_m']/c07['nominal_sag_m'])*100:.0f}%.",
        "",
        "> The process target pre-strain must be verified through a covering specification",
        "> (heat-shrink temperature / tension protocol) and panel test on a representative",
        "> 0.30 m bay before this failure mode is considered closed.",
        "",
        "## C02/C03 Bond Shear — SCF at Lap Ends",
        "",
        "Goland-Reissner simplified: λ = sqrt(G_adh / (t_adh E_sub t_sub)), SCF = λa / tanh(λa).",
        f"Applied SCF = **{c02c03['scf_applied']:.2f}** (λa = {c02c03['scf_lambda_a']:.4f}).",
        "",
        f"- Average bond shear (main): {c02c03['avg_shear_main_pa']:.0f} Pa",
        f"- Peak bond shear with SCF (main): {c02c03['C02_peak_shear_main_pa']:.0f} Pa",
        f"- Allowable: {c02c03['allowable_pa']:.0e} Pa → margin main {c02c03['C02_margin']:.0f}, rear {c02c03['C03_margin']:.0f}",
        "",
        "> The simplified Goland-Reissner index is capped at SCF=3.0 for this screening",
        "> run. Even with that cap applied, margins remain very large (>100). Bond shear",
        "> is not the governing failure mode at these load levels.",
        "",
        "## C05 Collar Bearing — Hertz Curvature Correction",
        "",
        f"Projected area: {c05['proj_bearing_area_m2']*1e6:.2f} mm².",
        f"Hertz effective area (π/4 factor): {c05['hertz_bearing_area_m2']*1e6:.2f} mm².",
        f"Peak bearing stress: {c05['bearing_stress_pa']:.0f} Pa = {c05['bearing_stress_pa']/1e6:.4f} MPa.",
        f"Bearing allowable: {c05['C05_bearing_allowable_pa']:.0e} Pa → margin **{c05['C05_margin']:.0f}**.",
        "",
        "## C06 Tube Wall Crush — Lamé Result",
        "",
        "| spar | OD | wall | contact pressure | σ_hoop inner | σ_hoop outer | margin |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| main | {freeze['spar_tubes']['main_spar']['od_m']*1000:.0f} mm | {freeze['spar_tubes']['main_spar']['wall_m']*1000:.1f} mm | {c06['C06_main']['contact_pressure_pa']:.1f} Pa | {c06['C06_main']['sigma_hoop_inner_pa']:.1f} Pa | {c06['C06_main']['sigma_hoop_outer_pa']:.1f} Pa | {c06['C06_main_margin']:.0f} |",
        f"| rear | {freeze['spar_tubes']['rear_spar']['od_m']*1000:.0f} mm | {freeze['spar_tubes']['rear_spar']['wall_m']*1000:.1f} mm | {c06['C06_rear']['contact_pressure_pa']:.1f} Pa | {c06['C06_rear']['sigma_hoop_inner_pa']:.1f} Pa | {c06['C06_rear']['sigma_hoop_outer_pa']:.1f} Pa | {c06['C06_rear_margin']:.0f} |",
        "",
        "## Engineering Interpretation",
        "",
        (
            "The Step 2 analytical run does **not** close the local load path: "
            "C04 bond peel is a critical blocker in the current eccentric collar-tab geometry."
            if not s["all_pass"]
            else "All Step 2 analytical failure modes pass for the current geometry."
        ),
        "",
        "The rank ordering is:",
        "",
        f"1. **C04 bond peel** (margin {c04['C04_margin']:.3f}) — critical load-path blocker.",
        "   The current geometry puts the adhesive in peel; this needs a different load path, not a stronger peel allowable.",
        f"2. **C07 skin sag** (margin {c07['C07_margin']:.3f} at nominal pre-strain) — process-governed.",
        f"   Minimum viable pre-strain = {c07['min_viable_prestrain_pct']}%; process target = {c07['process_target_prestrain_pct']}%.",
        "3. **C01 cap shear** (margin unchanged) — comfortable; balsa cap shear is not governing.",
        "4. C02/C03/C05/C06 — very large margins (>100); load levels are very small for HPA.",
        "",
        "The large margins on bond shear, collar bearing, and tube crush confirm that at",
        "HPA cruise load levels, the rib-spar joint is strength-governed by skin sag",
        "(serviceability) and peel eccentricity, not by gross shear or bearing failure.",
        "",
        "**What still needs physical evidence before Step 4 margin report:**",
        "",
        "- C07: covering process specification (heat-shrink protocol, target pre-strain,",
        "  inspection method, panel test on 0.30 m representative bay).",
        "- C04: replace the eccentric collar-tab peel path with the saddle-ring / yoke /",
        "  clamp load path, then validate that geometry with coupon and local FEM.",
        "- Adhesive allowables: supplier datasheet to replace 18 MPa / 400 N/m estimates.",
        "- Spar tube OD: structural optimizer confirmation that max-OD assumption holds.",
        "",
        "## Claim Boundary",
        "",
        f"> {result['claim_boundary']}",
    ]
    return "\n".join(lines)


def _write_margin_csv(result: dict[str, Any], path: Path) -> None:
    step1_margins = {
        "C01": result["C01_cap_shear"]["margin"],
        "C02": result["C02_C03_bond_shear"]["C02_margin"],
        "C03": result["C02_C03_bond_shear"]["C03_margin"],
        "C04": result["C04_bond_peel"]["C04_margin"],
        "C05": result["C05_collar_bearing"]["C05_margin"],
        "C06_main": result["C06_tube_crush"]["C06_main_margin"],
        "C06_rear": result["C06_tube_crush"]["C06_rear_margin"],
        "C07": result["C07_skin_sag"]["C07_margin"],
    }
    rows = [
        {"coupon": k, "step2_margin": round(v, 4), "pass": "pass" if v > 0 else "concern"}
        for k, v in step1_margins.items()
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["coupon", "step2_margin", "pass"])
        writer.writeheader()
        writer.writerows(rows)


def _write_sag_sweep_csv(result: dict[str, Any], path: Path) -> None:
    sweep = result["C07_skin_sag"]["sweep"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "prestrain_pct", "T_membrane_n_per_m",
                "sag_m", "sag_pct_chord", "margin", "passes",
                "sag_nonlinear_m", "sag_nonlinear_pct_chord",
                "margin_nonlinear", "passes_nonlinear",
            ],
        )
        writer.writeheader()
        writer.writerows(sweep)


def write_margin_run_package(
    *,
    freeze_json: Path = DEFAULT_FREEZE_JSON,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
) -> dict[str, Path]:
    freeze = json.loads(freeze_json.read_text(encoding="utf-8"))
    result = _run_all_margins(freeze)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)

    run_json_path = output_dir / "local_detail_margin_run.json"
    run_json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    margins_csv_path = output_dir / "local_detail_margins.csv"
    _write_margin_csv(result, margins_csv_path)

    sag_csv_path = output_dir / "skin_sag_prestrain_sweep.csv"
    _write_sag_sweep_csv(result, sag_csv_path)

    md_text = _render_report_md(result, freeze)
    report_md.write_text(md_text, encoding="utf-8")

    report_json_payload = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": result["candidate_id"],
        "station_id": result["station_id"],
        "all_margins": result["summary"]["all_margins"],
        "worst_margin": result["summary"]["worst_margin"],
        "worst_coupon": result["summary"]["worst_coupon"],
        "all_pass": result["summary"]["all_pass"],
        "verdict": result["summary"]["verdict"],
        "c07_min_viable_prestrain_pct": result["C07_skin_sag"].get("min_viable_prestrain_pct"),
        "c07_process_target_prestrain_pct": result["C07_skin_sag"].get("process_target_prestrain_pct"),
        "c04_eccentric_moment_margin": result["C04_bond_peel"]["C04_margin"],
        "c04_theoretical_min_margin": result["C04_bond_peel"]["c04_theoretical_min_margin"],
        "c04_min_bondline_for_pass_mm": result["C04_bond_peel"]["c04_min_bondline_for_pass_mm"],
        "c07_nominal_margin_nonlinear": result["C07_skin_sag"]["nominal_margin_nonlinear"],
        "c07_nominal_sag_nonlinear_mm": round(
            result["C07_skin_sag"]["nominal_sag_nonlinear_m"] * 1000, 3
        ),
        "claim_boundary": CLAIM_BOUNDARY,
        "output_run_json": str(run_json_path),
        "output_margins_csv": str(margins_csv_path),
        "output_sag_sweep_csv": str(sag_csv_path),
        "output_report_md": str(report_md),
    }
    report_json.write_text(json.dumps(report_json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "run_json": run_json_path,
        "margins_csv": margins_csv_path,
        "sag_sweep_csv": sag_csv_path,
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

    paths = write_margin_run_package(
        freeze_json=args.freeze_json,
        output_dir=args.output_dir,
        report_json=args.report_json,
        report_md=args.report_md,
    )
    print(f"run JSON:      {paths['run_json']}")
    print(f"margins CSV:   {paths['margins_csv']}")
    print(f"sag sweep CSV: {paths['sag_sweep_csv']}")
    print(f"report MD:     {paths['report_md']}")
    print(f"report JSON:   {paths['report_json']}")


if __name__ == "__main__":
    main()
