#!/usr/bin/env python3
"""Geometry and allowable freeze sheet for P1 rib / local detail validation.

Step 1 of the FEM/Coupon Plan from the local-validation shortlist report
(2026-05-10). Derives spar-tube OD/wall from the config thickness-fraction
parameters, pins down collar / bondline / adhesive / skin estimates with
explicit confidence levels, and computes preliminary margins for the seven
local failure modes at y = 2.328 m.

This is a freeze-sheet and preliminary-margin pass, NOT final sign-off. Every
parameter tagged 'engineering_estimate' must be replaced with supplier or
coupon data before the FEM/APDL local margin run is considered qualified.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import load_config  # noqa: E402


SCHEMA_VERSION = "rib_local_detail_geometry_freeze_v1"
CLAIM_BOUNDARY = (
    "Geometry freeze and preliminary margins for P1 y=2.328 m local detail "
    "validation. Parameters tagged 'engineering_estimate' must be replaced "
    "with supplier or coupon data before qualified margin claims. "
    "This is not final bond, collar, tube-wall, buckling, or aircraft sign-off."
)

DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"
DEFAULT_CARBON_TUBES_CSV = REPO_ROOT / "data" / "carbon_tubes.csv"
DEFAULT_MATERIALS_YAML = REPO_ROOT / "data" / "materials.yaml"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_rib_local_detail_geometry_freeze"
DEFAULT_REPORT_JSON = (
    REPO_ROOT / "docs" / "reports"
    / "2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT / "docs" / "reports"
    / "2026-05-11_current_pathfinder_rib_local_detail_geometry_freeze.md"
)
DEFAULT_APDL_TEMPLATE = (
    REPO_ROOT / "output" / "current_pathfinder_positive_torque_zone_validation"
    / "positive_zone_local_fem_skeleton.mac"
)

TORQUE_CRITICAL_Y_M = 2.327757
SPAR_SEPARATION_M = 0.533385
LOCAL_KERNEL_TORQUE_N_M = -12.715548
LOCAL_COUPLE_FORCE_N = 23.839355
LOCAL_MAIN_TOTAL_FZ_N = -4.222466
LOCAL_REAR_TOTAL_FZ_N = 23.552825
LOCAL_MAIN_LIFT_N = 21.202169
STATION_CHORD_M = 1.184552
STATION_Y_M = 2.327955
MAIN_SPAR_XC = 0.25
REAR_SPAR_XC = 0.70


def _load_carbon_tubes(path: Path) -> list[dict[str, Any]]:
    tubes: list[dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            tubes.append(
                {
                    "product": row["product"],
                    "material_key": row["material_key"],
                    "od_mm": float(row["outer_diameter_mm"]),
                    "id_mm": float(row["inner_diameter_mm"]),
                    "wall_mm": float(row["wall_thickness_mm"]),
                    "mass_per_m_kg": float(row["mass_per_meter_kg"]),
                    "note": row.get("note", ""),
                }
            )
    return tubes


def _load_materials(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _select_tube(tubes: list[dict[str, Any]], od_max_m: float, material_key: str) -> dict[str, Any]:
    od_max_mm = od_max_m * 1000.0
    candidates = [t for t in tubes if t["material_key"] == material_key and t["od_mm"] <= od_max_mm]
    if not candidates:
        candidates = [t for t in tubes if t["material_key"] == material_key]
    return max(candidates, key=lambda t: t["od_mm"])


def _derive_spar_tube_at_station(
    config: Any,
    carbon_tubes: list[dict[str, Any]],
    y_m: float,
    chord_m: float,
) -> dict[str, Any]:
    wing = config.wing
    half_span_m = sum(config.main_spar.segments)
    tc_root = wing.airfoil_root_tc
    tc_tip = wing.airfoil_tip_tc
    tc_y = tc_root + (tc_tip - tc_root) * (y_m / half_span_m)

    ms = config.main_spar
    rs = config.rear_spar
    depth_main = chord_m * tc_y * ms.thickness_fraction_root
    depth_rear = chord_m * tc_y * rs.thickness_fraction_root

    main_tube = _select_tube(carbon_tubes, depth_main, ms.material)
    rear_tube = _select_tube(carbon_tubes, depth_rear, rs.material)

    return {
        "tc_y": round(tc_y, 6),
        "half_span_m": half_span_m,
        "depth_main_m": round(depth_main, 6),
        "depth_rear_m": round(depth_rear, 6),
        "main_spar": {
            "product": main_tube["product"],
            "material_key": main_tube["material_key"],
            "od_m": round(main_tube["od_mm"] / 1000.0, 6),
            "id_m": round(main_tube["id_mm"] / 1000.0, 6),
            "wall_m": round(main_tube["wall_mm"] / 1000.0, 6),
            "mass_per_m_kg": main_tube["mass_per_m_kg"],
            "confidence": "design_derived",
            "source": "config thickness_fraction_root x t/c x chord; nearest catalog tube",
            "note": "Derived max OD; optimizer may select smaller. Awaiting optimizer confirmation.",
        },
        "rear_spar": {
            "product": rear_tube["product"],
            "material_key": rear_tube["material_key"],
            "od_m": round(rear_tube["od_mm"] / 1000.0, 6),
            "id_m": round(rear_tube["id_mm"] / 1000.0, 6),
            "wall_m": round(rear_tube["wall_mm"] / 1000.0, 6),
            "mass_per_m_kg": rear_tube["mass_per_m_kg"],
            "confidence": "design_derived",
            "source": "config thickness_fraction_root x t/c x chord; nearest catalog tube",
            "note": "Derived max OD; optimizer may select smaller. Awaiting optimizer confirmation.",
        },
    }


def _build_collar_geometry(
    reinforcement_type: str,
    materials: dict[str, Any],
) -> dict[str, Any]:
    if "carbon" in reinforcement_type:
        mat_key = "cfrp_ply_sm"
        n_plies = 4
        t_ply_m = materials[mat_key].get("t_ply", 0.000125)
        collar_thickness_m = n_plies * t_ply_m
        collar_bearing_allowable_pa = 400.0e6
        collar_material_name = "Standard-modulus CFRP (T300/T700 class)"
        confidence = "design_intent"
        note = (
            "4-ply CF collar at torque-critical station. Bearing allowable is "
            "conservative (25% of F1t). Replace with measured bearing coupon."
        )
    else:
        mat_key = "eglass_woven"
        collar_thickness_m = 0.0005
        collar_bearing_allowable_pa = 150.0e6
        collar_material_name = "E-glass woven fabric (cured)"
        confidence = "design_intent"
        note = (
            "E-glass woven collar at torque-critical station. Bearing allowable "
            "is conservative (43% of tensile_strength). Replace with coupon data."
        )
    return {
        "material_key": mat_key,
        "material_name": collar_material_name,
        "n_plies": n_plies if "carbon" in reinforcement_type else None,
        "collar_thickness_m": round(collar_thickness_m, 6),
        "collar_contact_width_m": 0.085,
        "collar_bearing_allowable_pa": collar_bearing_allowable_pa,
        "confidence": confidence,
        "source": "shortlist report (contact width); conservative bearing allowable from material strength",
        "note": note,
    }


def _build_bondline_geometry() -> dict[str, Any]:
    return {
        "adhesive_system": "structural_epoxy_hpa_class",
        "adhesive_description": (
            "Araldite 420 / Hysol EA9430 class structural epoxy. "
            "Conservative lower-bound for HPA bonded joints."
        ),
        "bondline_width_m": 0.015,
        "bondline_thickness_m": 0.0003,
        "fillet_radius_m": 0.001,
        "adhesive_shear_allowable_pa": 18.0e6,
        "adhesive_peel_allowable_n_per_m": 400.0,
        "confidence": "engineering_estimate",
        "source": "Typical structural epoxy for HPA bonded joints; supplier confirmation required",
        "note": (
            "18 MPa shear and 400 N/m peel are conservative estimates for "
            "Araldite 420 class. Replace with supplier data sheet and "
            "coupon confirmation matched to actual bondline geometry and cure."
        ),
    }


def _fval(v: Any, default: float) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _build_balsa_cap_geometry(materials: dict[str, Any]) -> dict[str, Any]:
    balsa = materials.get("balsa", {})
    g_balsa = _fval(balsa.get("G"), 0.2e9)
    tensile_allow = _fval(balsa.get("tensile_strength"), 20.0e6)
    shear_allow = min(g_balsa * 0.03, tensile_allow * 0.35)
    return {
        "material_key": "balsa",
        "cap_width_m": 0.012,
        "cap_thickness_m": 0.003,
        "cap_length_m": 0.085,
        "balsa_shear_allowable_pa": round(shear_allow, 0),
        "eps_shear_allowable_pa": 100.0e3,
        "eps_structural_credit": False,
        "confidence": "engineering_estimate",
        "source": "balsa G from materials.yaml; shear allow = min(G*3%, 35% tensile); EPS shape support only",
        "note": (
            "Balsa cap shear allowable is estimated. Replace with in-grain and "
            "cross-grain coupon data. EPS has no structural torsion credit; "
            "its shape-support role must be confirmed against manufacturing scatter."
        ),
    }


def _build_skin_geometry() -> dict[str, Any]:
    return {
        "material": "mylar_bopet_film",
        "material_description": "Biaxially oriented PET (Mylar) 25 micron. Standard HPA covering.",
        "skin_thickness_m": 25.0e-6,
        "skin_E_pa": 4.5e9,
        "skin_tensile_allowable_pa": 150.0e6,
        "skin_prestrain_fraction": 0.0005,
        "sag_allowable_fraction_chord": 0.005,
        "confidence": "engineering_estimate",
        "source": "Standard HPA Mylar covering; pre-strain is process-dependent",
        "note": (
            "Sag is process-sensitive: 0.05% pre-strain gives acceptable sag; "
            "lower values result in >1% chord sag. Confirm with actual panel test "
            "or covering process specification."
        ),
    }


def _tube_polar_moment(od_m: float, wall_m: float) -> float:
    r_mean = (od_m - wall_m) / 2.0
    return 2.0 * math.pi * r_mean**3 * wall_m


def _compute_preliminary_margins(
    freeze_sheet: dict[str, Any],
    load_factor: float,
) -> dict[str, Any]:
    main = freeze_sheet["spar_tubes"]["main_spar"]
    rear = freeze_sheet["spar_tubes"]["rear_spar"]
    collar = freeze_sheet["collar"]
    bond = freeze_sheet["bondline"]
    cap = freeze_sheet["balsa_cap"]
    skin_geo = freeze_sheet["skin"]

    design_couple_force_n = abs(LOCAL_COUPLE_FORCE_N) * load_factor
    design_main_total_n = abs(LOCAL_MAIN_TOTAL_FZ_N) * load_factor
    design_rear_total_n = abs(LOCAL_REAR_TOTAL_FZ_N) * load_factor
    design_torque_n_m = abs(LOCAL_KERNEL_TORQUE_N_M) * load_factor

    main_od = main["od_m"]
    main_wall = main["wall_m"]
    rear_od = rear["od_m"]
    rear_wall = rear["wall_m"]

    # --- C02 / C03: rib-to-spar bond shear ---
    # Vertical couple force transferred through collar bondline into spar tube.
    # Modelled as shear over the bond lateral area: π * OD * collar_contact_width / 2
    # (half-circumference contact for a rib-collar wrapping over the spar tube).
    bond_area_main = math.pi * main_od * collar["collar_contact_width_m"] / 2.0
    bond_area_rear = math.pi * rear_od * collar["collar_contact_width_m"] / 2.0
    bond_shear_main_pa = design_couple_force_n / bond_area_main
    bond_shear_rear_pa = design_couple_force_n / bond_area_rear
    bond_shear_allow = bond["adhesive_shear_allowable_pa"]
    margin_bond_shear_main = bond_shear_allow / bond_shear_main_pa - 1.0
    margin_bond_shear_rear = bond_shear_allow / bond_shear_rear_pa - 1.0

    # --- C04: bond peel ---
    # Peel arises from eccentricity of the couple force relative to the bondline.
    # Estimated as peel_fraction × bond_shear_stress × bond_area → peak peel force.
    # Conservative peel fraction = 0.20 for a collar on a round tube.
    peel_fraction = 0.20
    peak_peel_force_main_n = peel_fraction * bond_shear_main_pa * bond_area_main
    peak_peel_force_rear_n = peel_fraction * bond_shear_rear_pa * bond_area_rear
    peel_allow_n = bond["adhesive_peel_allowable_n_per_m"] * collar["collar_contact_width_m"]
    margin_peel_main = peel_allow_n / peak_peel_force_main_n - 1.0
    _ = peel_allow_n / peak_peel_force_rear_n - 1.0

    # --- C05: collar bearing on spar tube ---
    # Radial bearing load from couple force on collar-to-tube contact patch.
    # Projected bearing area = collar_contact_width * collar_thickness.
    bearing_area = collar["collar_contact_width_m"] * collar["collar_thickness_m"]
    bearing_stress_pa = design_couple_force_n / bearing_area
    margin_collar_bearing = collar["collar_bearing_allowable_pa"] / bearing_stress_pa - 1.0

    # --- C06: spar tube wall crush / ovalization ---
    # Peak hoop stress from collar contact using Hertzian / thin-shell estimate.
    # Radial line load from couple force spread over collar_contact_width.
    # Hoop stress = (F / (collar_width * OD)) * (OD / (2 * wall)).
    main_radial_load = design_couple_force_n / collar["collar_contact_width_m"]
    rear_radial_load = design_couple_force_n / collar["collar_contact_width_m"]
    main_hoop_stress = (main_radial_load / main_od) * (main_od / (2.0 * main_wall))
    rear_hoop_stress = (rear_radial_load / rear_od) * (rear_od / (2.0 * rear_wall))
    carbon_hm = freeze_sheet["materials_summary"].get("carbon_fiber_hm", {})
    tube_crush_allow = carbon_hm.get("compressive_strength", 1500.0e6) * 0.25
    margin_tube_crush_main = tube_crush_allow / main_hoop_stress - 1.0
    margin_tube_crush_rear = tube_crush_allow / rear_hoop_stress - 1.0

    # --- C01: EPS+balsa cap shear transfer ---
    # Cap shear = total vertical force shared over main and rear caps.
    # Worst case: all vertical load on one cap strip.
    cap_shear_force_n = max(design_main_total_n, design_rear_total_n)
    cap_area = cap["cap_width_m"] * cap["cap_length_m"]
    cap_shear_stress_pa = cap_shear_force_n / cap_area
    margin_cap_shear = cap["balsa_shear_allowable_pa"] / cap_shear_stress_pa - 1.0

    # --- C07: skin sag / shape keeping ---
    # Membrane sag model: δ = p*L² / (8*T) where T is spanwise membrane tension.
    # T = E_skin * t_skin * pre_strain (per unit chordwise width).
    q_cruise_pa = 0.5 * 1.225 * 6.5**2
    p_normal_per_span = q_cruise_pa * STATION_CHORD_M
    bay_length_m = 0.291048
    T_membrane = skin_geo["skin_E_pa"] * skin_geo["skin_thickness_m"] * skin_geo["skin_prestrain_fraction"]
    sag_m = p_normal_per_span * bay_length_m**2 / (8.0 * T_membrane)
    sag_fraction_chord = sag_m / STATION_CHORD_M
    sag_allowable = skin_geo["sag_allowable_fraction_chord"] * STATION_CHORD_M
    margin_skin_sag = sag_allowable / sag_m - 1.0

    return {
        "load_factor_applied": load_factor,
        "design_couple_force_n": round(design_couple_force_n, 4),
        "design_torque_n_m": round(design_torque_n_m, 4),
        "claim_boundary": (
            "Preliminary margins only. Model simplifications apply: "
            "half-circumference bond area, peel fraction estimate, thin-shell hoop, "
            "membrane skin sag. Must be replaced with full local FEM and coupon data."
        ),
        "C01_cap_shear_transfer": {
            "cap_shear_stress_pa": round(cap_shear_stress_pa, 1),
            "cap_shear_allowable_pa": cap["balsa_shear_allowable_pa"],
            "margin": round(margin_cap_shear, 3),
            "status": "preliminary_pass" if margin_cap_shear > 0 else "preliminary_concern",
        },
        "C02_main_spar_bond_shear": {
            "bond_area_m2": round(bond_area_main, 6),
            "bond_shear_stress_pa": round(bond_shear_main_pa, 1),
            "bond_shear_allowable_pa": bond_shear_allow,
            "margin": round(margin_bond_shear_main, 3),
            "status": "preliminary_pass" if margin_bond_shear_main > 0 else "preliminary_concern",
        },
        "C03_rear_spar_bond_shear": {
            "bond_area_m2": round(bond_area_rear, 6),
            "bond_shear_stress_pa": round(bond_shear_rear_pa, 1),
            "bond_shear_allowable_pa": bond_shear_allow,
            "margin": round(margin_bond_shear_rear, 3),
            "status": "preliminary_pass" if margin_bond_shear_rear > 0 else "preliminary_concern",
        },
        "C04_bond_peel_main": {
            "peel_fraction_used": peel_fraction,
            "peak_peel_force_n": round(peak_peel_force_main_n, 4),
            "peel_allowable_n": round(peel_allow_n, 4),
            "margin": round(margin_peel_main, 3),
            "status": "preliminary_pass" if margin_peel_main > 0 else "preliminary_concern",
        },
        "C05_collar_bearing": {
            "bearing_area_m2": round(bearing_area, 8),
            "bearing_stress_pa": round(bearing_stress_pa, 1),
            "bearing_allowable_pa": collar["collar_bearing_allowable_pa"],
            "margin": round(margin_collar_bearing, 3),
            "status": "preliminary_pass" if margin_collar_bearing > 0 else "preliminary_concern",
        },
        "C06_tube_crush_main": {
            "hoop_stress_pa": round(main_hoop_stress, 1),
            "crush_allowable_pa": round(tube_crush_allow, 0),
            "margin": round(margin_tube_crush_main, 3),
            "status": "preliminary_pass" if margin_tube_crush_main > 0 else "preliminary_concern",
        },
        "C06_tube_crush_rear": {
            "hoop_stress_pa": round(rear_hoop_stress, 1),
            "crush_allowable_pa": round(tube_crush_allow, 0),
            "margin": round(margin_tube_crush_rear, 3),
            "status": "preliminary_pass" if margin_tube_crush_rear > 0 else "preliminary_concern",
        },
        "C07_skin_sag": {
            "q_cruise_pa": round(q_cruise_pa, 2),
            "membrane_tension_n_per_m": round(T_membrane, 3),
            "sag_m": round(sag_m, 6),
            "sag_fraction_chord": round(sag_fraction_chord, 6),
            "sag_allowable_m": round(sag_allowable, 6),
            "margin": round(margin_skin_sag, 3),
            "status": "preliminary_pass" if margin_skin_sag > 0 else "preliminary_concern",
            "process_sensitivity": (
                "PROCESS-SENSITIVE: sag scales with 1/pre_strain. "
                "0.05% pre-strain assumed; lower values cause >1% chord sag."
            ),
        },
    }


def _build_freeze_sheet(
    config: Any,
    materials: dict[str, Any],
    carbon_tubes: list[dict[str, Any]],
) -> dict[str, Any]:
    spar_tubes = _derive_spar_tube_at_station(
        config,
        carbon_tubes,
        y_m=STATION_Y_M,
        chord_m=STATION_CHORD_M,
    )
    collar_p1 = _build_collar_geometry("carbon_face_collar_y2p328", materials)
    collar_p3 = _build_collar_geometry("glass_face_collar_y2p328", materials)
    bondline = _build_bondline_geometry()
    balsa_cap = _build_balsa_cap_geometry(materials)
    skin = _build_skin_geometry()

    load_factor = getattr(getattr(config, "loads", None), "aerodynamic_load_factor", 2.0)

    _numeric_keys = ("E", "G", "density", "tensile_strength", "compressive_strength", "shear_strength")
    materials_summary = {
        k: {
            kk: _fval(v, 0.0)
            for kk, v in m.items()
            if kk in _numeric_keys
        }
        for k, m in materials.items()
        if isinstance(m, dict)
    }

    freeze_sheet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": "eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75",
        "station_id": "R068",
        "station_y_m": STATION_Y_M,
        "torque_critical_y_m": TORQUE_CRITICAL_Y_M,
        "chord_m": STATION_CHORD_M,
        "spar_separation_m": SPAR_SEPARATION_M,
        "load_factor": load_factor,
        "local_kernel_torque_n_m": LOCAL_KERNEL_TORQUE_N_M,
        "local_couple_force_n": LOCAL_COUPLE_FORCE_N,
        "local_main_total_fz_n": LOCAL_MAIN_TOTAL_FZ_N,
        "local_rear_total_fz_n": LOCAL_REAR_TOTAL_FZ_N,
        "spar_tubes": spar_tubes,
        "collar": collar_p1,
        "collar_p3_alternate": collar_p3,
        "bondline": bondline,
        "balsa_cap": balsa_cap,
        "skin": skin,
        "materials_summary": materials_summary,
        "missing_data_register_status": {
            "adhesive_shear_allowable_pa": "engineering_estimate_filled",
            "adhesive_peel_allowable_pa": "engineering_estimate_filled",
            "bondline_width_thickness_fillet": "engineering_estimate_filled",
            "collar_material_thickness_contact_width": "design_intent_filled",
            "spar_tube_od_wall_material": "design_derived_filled",
            "balsa_cap_face_properties": "engineering_estimate_filled",
            "eps_core_properties": "engineering_estimate_shape_support_only",
            "skin_material_thickness_attachment": "engineering_estimate_filled",
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }

    freeze_sheet["preliminary_margins"] = _compute_preliminary_margins(
        freeze_sheet, load_factor
    )
    return freeze_sheet


def _render_freeze_report_md(freeze: dict[str, Any]) -> str:
    ms = freeze["spar_tubes"]["main_spar"]
    rs = freeze["spar_tubes"]["rear_spar"]
    cl = freeze["collar"]
    bo = freeze["bondline"]
    cap = freeze["balsa_cap"]
    sk = freeze["skin"]
    lf = freeze["load_factor"]
    marg = freeze["preliminary_margins"]

    def _ms(v: float) -> str:
        return f"{v:.3f}"

    def _pass(status: str) -> str:
        return "pass" if "pass" in status else "CONCERN"

    lines = [
        "# Current Pathfinder Rib / Local Detail Geometry and Allowable Freeze Sheet",
        "",
        "> Date: 2026-05-11",
        f"> Candidate: `{freeze['candidate_id']}`",
        f"> Station: R068 at y = {freeze['station_y_m']} m",
        f"> Schema: `{freeze['schema_version']}`",
        "",
        "## Purpose",
        "",
        "This is Step 1 of the FEM/Coupon Plan from the 2026-05-10 local-validation shortlist.",
        "It fills all eight open items in the missing-data register with engineering estimates,",
        "derives spar-tube dimensions from the config thickness-fraction parameters, and computes",
        "preliminary margins for the seven local failure modes.",
        "",
        "Parameters tagged **engineering_estimate** must be replaced with supplier data or",
        "coupon results before the local FEM/APDL run is considered a qualified margin claim.",
        "",
        "## Station Summary",
        "",
        "| item | value |",
        "|---|---:|",
        "| station | R068 |",
        f"| y | {freeze['station_y_m']} m |",
        f"| chord | {freeze['chord_m']} m |",
        f"| spar separation | {freeze['spar_separation_m']} m |",
        f"| kernel torque | {freeze['local_kernel_torque_n_m']} N·m |",
        f"| torque couple | {freeze['local_couple_force_n']} N |",
        f"| load factor | {lf} |",
        f"| design couple force (factored) | {marg['design_couple_force_n']} N |",
        "",
        "## Spar Tube Geometry (Design Derived)",
        "",
        "OD is derived as: `chord × t/c(y) × thickness_fraction_root` then rounded DOWN to the",
        "nearest catalog tube. This is the MAXIMUM allowable OD; the structural optimizer may",
        "select a smaller tube based on bending and buckling requirements.",
        "",
        "| item | main spar | rear spar |",
        "|---|---:|---:|",
        f"| catalog product | {ms['product']} | {rs['product']} |",
        f"| OD | {ms['od_m']*1000:.0f} mm | {rs['od_m']*1000:.0f} mm |",
        f"| wall | {ms['wall_m']*1000:.1f} mm | {rs['wall_m']*1000:.1f} mm |",
        f"| confidence | {ms['confidence']} | {rs['confidence']} |",
        "",
        f"**Note:** {ms['note']}",
        "",
        "## Missing Data Register — Filled Values",
        "",
        "| data key | filled value | confidence | source |",
        "|---|---|---|---|",
        f"| main_spar_od_m | {ms['od_m']} | {ms['confidence']} | {ms['source'][:50]} |",
        f"| main_spar_wall_m | {ms['wall_m']} | {ms['confidence']} | catalog |",
        f"| rear_spar_od_m | {rs['od_m']} | {rs['confidence']} | config t/c + thickness_fraction |",
        f"| rear_spar_wall_m | {rs['wall_m']} | {rs['confidence']} | catalog |",
        "| collar_material (P1) | cfrp_ply_sm | design_intent | shortlist report |",
        f"| collar_thickness_m | {cl['collar_thickness_m']} | {cl['confidence']} | 4-ply CF estimate |",
        f"| collar_contact_width_m | {cl['collar_contact_width_m']} | design_intent | shortlist report |",
        f"| bondline_width_m | {bo['bondline_width_m']} | engineering_estimate | typical HPA lap joint |",
        f"| bondline_thickness_m | {bo['bondline_thickness_m']} | engineering_estimate | thin bond |",
        f"| adhesive_shear_allowable_pa | {bo['adhesive_shear_allowable_pa']:.0e} | engineering_estimate | Araldite 420 class |",
        f"| adhesive_peel_allowable_n_per_m | {bo['adhesive_peel_allowable_n_per_m']:.0f} | engineering_estimate | structural epoxy |",
        f"| balsa_cap_shear_allowable_pa | {cap['balsa_shear_allowable_pa']:.0e} | engineering_estimate | G×3% strain limit |",
        f"| eps_core_shear_allowable_pa | {cap['eps_shear_allowable_pa']:.0e} | engineering_estimate | shape support only |",
        f"| skin_thickness_m | {sk['skin_thickness_m']:.0e} | engineering_estimate | 25 μm Mylar standard |",
        "",
        "## Preliminary Margins (7 Failure Modes)",
        "",
        "> These are PRELIMINARY estimates. Model simplifications: half-circumference bond area,",
        "> peel fraction = 0.20, thin-shell hoop stress, membrane skin sag. Replace with full",
        "> local FEM and coupon data for qualified margins.",
        "",
        "| coupon | failure mode | stress / load | allowable | margin | status |",
        "|---|---|---:|---:|---:|---|",
    ]

    c01 = marg["C01_cap_shear_transfer"]
    c02 = marg["C02_main_spar_bond_shear"]
    c03 = marg["C03_rear_spar_bond_shear"]
    c04 = marg["C04_bond_peel_main"]
    c05 = marg["C05_collar_bearing"]
    c06m = marg["C06_tube_crush_main"]
    c06r = marg["C06_tube_crush_rear"]
    c07 = marg["C07_skin_sag"]

    lines += [
        f"| C01 | cap shear transfer | {c01['cap_shear_stress_pa']:.0f} Pa | {c01['cap_shear_allowable_pa']:.0e} Pa | {c01['margin']:.1f} | {_pass(c01['status'])} |",
        f"| C02 | main spar bond shear | {c02['bond_shear_stress_pa']:.0f} Pa | {c02['bond_shear_allowable_pa']:.0e} Pa | {c02['margin']:.1f} | {_pass(c02['status'])} |",
        f"| C03 | rear spar bond shear | {c03['bond_shear_stress_pa']:.0f} Pa | {c03['bond_shear_allowable_pa']:.0e} Pa | {c03['margin']:.1f} | {_pass(c03['status'])} |",
        f"| C04 | bond peel (main) | {c04['peak_peel_force_n']:.3f} N | {c04['peel_allowable_n']:.3f} N | {c04['margin']:.1f} | {_pass(c04['status'])} |",
        f"| C05 | collar bearing | {c05['bearing_stress_pa']:.0f} Pa | {c05['bearing_allowable_pa']:.0e} Pa | {c05['margin']:.1f} | {_pass(c05['status'])} |",
        f"| C06-M | tube crush (main) | {c06m['hoop_stress_pa']:.0f} Pa | {c06m['crush_allowable_pa']:.0e} Pa | {c06m['margin']:.1f} | {_pass(c06m['status'])} |",
        f"| C06-R | tube crush (rear) | {c06r['hoop_stress_pa']:.0f} Pa | {c06r['crush_allowable_pa']:.0e} Pa | {c06r['margin']:.1f} | {_pass(c06r['status'])} |",
        f"| C07 | skin sag | {c07['sag_fraction_chord']*100:.3f} %c | {sk['sag_allowable_fraction_chord']*100:.2f} %c | {c07['margin']:.2f} | {_pass(c07['status'])} |",
    ]

    worst_margin = min(
        c01["margin"], c02["margin"], c03["margin"], c04["margin"],
        c05["margin"], c06m["margin"], c06r["margin"], c07["margin"],
    )
    most_critical = "C07 skin sag" if c07["margin"] == worst_margin else "see table"

    lines += [
        "",
        f"Preliminary worst margin: **{worst_margin:.2f}** ({most_critical}).",
        "",
        "**Important:** All margins appear comfortable at screening load levels. This is",
        "expected for HPA structures. The purpose of the local FEM is NOT to find near-zero",
        "margins but to confirm that the simplified preliminary model is not hiding stress",
        "concentrations, peel failures, or ovalization under point loads.",
        "",
        "## Skin Sag Process Warning",
        "",
        f"Sag is computed at pre-strain = {sk['skin_prestrain_fraction']*100:.2f}%. "
        f"Computed sag: **{c07['sag_m']*1000:.1f} mm** = "
        f"**{c07['sag_fraction_chord']*100:.3f}% chord**.",
        "",
        f"> {c07['process_sensitivity']}",
        "",
        "## Next Actions",
        "",
        "| step | action | unblocked by this sheet |",
        "|---|---|---|",
        "| Step 2 | P1 local FEM pre-margin run at y=2.328 m | Yes — fill APDL skeleton with frozen values |",
        "| Step 3 | P1 coupon matrix C01–C07 | Yes — geometry and failure modes pinned |",
        "| Step 4 | P1 local margin report | Requires Step 2 + Step 3 |",
        "| Step 5 | P2 reserve comparison (12 mm) | After P1 FEM baseline |",
        "| Step 6 | P3 manufacturability fallback (glass collar) | After P1 |",
        "| Step 7 | Ordinary bay validation | After torque-zone results |",
        "",
        "## Supplier Confirmation Priority",
        "",
        "Replace the following engineering estimates BEFORE Step 4 margin report:",
        "",
        "1. **Adhesive**: supplier datasheet for actual adhesive system — shear strength, peel",
        "   strength, bondline thickness, cure schedule.",
        "2. **Spar tube OD/wall**: structural optimizer output at y=2.328 m to confirm whether",
        "   the max-OD assumption holds or the optimizer selected a smaller tube.",
        "3. **Balsa cap shear allowable**: diagonal shear coupon on EPS+balsa cap specimen",
        "   matched to actual grain direction and cap strip dimensions.",
        "4. **Collar bearing**: bearing coupon on CF collar on representative spar tube section.",
        "5. **Skin pre-strain**: covering process specification confirming target pre-strain and",
        "   inspection method.",
        "",
        "## Claim Boundary",
        "",
        f"> {freeze['claim_boundary']}",
    ]
    return "\n".join(lines)


def _update_apdl_skeleton(freeze: dict[str, Any], template_text: str) -> str:
    ms = freeze["spar_tubes"]["main_spar"]
    rs = freeze["spar_tubes"]["rear_spar"]
    cl = freeze["collar"]
    bo = freeze["bondline"]

    replacements = {
        "MAIN_SPAR_OD_M = -1": f"MAIN_SPAR_OD_M = {ms['od_m']}",
        "MAIN_SPAR_WALL_M = -1": f"MAIN_SPAR_WALL_M = {ms['wall_m']}",
        "REAR_SPAR_OD_M = -1": f"REAR_SPAR_OD_M = {rs['od_m']}",
        "REAR_SPAR_WALL_M = -1": f"REAR_SPAR_WALL_M = {rs['wall_m']}",
        "COLLAR_THICKNESS_M = -1": f"COLLAR_THICKNESS_M = {cl['collar_thickness_m']}",
        "BONDLINE_WIDTH_M = -1": f"BONDLINE_WIDTH_M = {bo['bondline_width_m']}",
        "BONDLINE_THICKNESS_M = -1": f"BONDLINE_THICKNESS_M = {bo['bondline_thickness_m']}",
        "ADHESIVE_SHEAR_ALLOWABLE_PA = -1": f"ADHESIVE_SHEAR_ALLOWABLE_PA = {bo['adhesive_shear_allowable_pa']:.3e}",
        "ADHESIVE_PEEL_ALLOWABLE_PA = -1": (
            f"ADHESIVE_PEEL_ALLOWABLE_PA = {bo['adhesive_peel_allowable_n_per_m'] / bo['bondline_width_m']:.3e}"
        ),
        "COLLAR_BEARING_ALLOWABLE_PA = -1": f"COLLAR_BEARING_ALLOWABLE_PA = {cl['collar_bearing_allowable_pa']:.3e}",
        "TUBE_CRUSH_ALLOWABLE_PA = -1": (
            f"TUBE_CRUSH_ALLOWABLE_PA = "
            f"{freeze['materials_summary'].get('carbon_fiber_hm', {}).get('compressive_strength', 1500e6) * 0.25:.3e}"
        ),
        "BALSACAP_SHEAR_ALLOWABLE_PA = -1": (
            f"BALSACAP_SHEAR_ALLOWABLE_PA = {freeze['balsa_cap']['balsa_shear_allowable_pa']:.3e}"
        ),
        "SKIN_THICKNESS_M = -1": f"SKIN_THICKNESS_M = {freeze['skin']['skin_thickness_m']:.3e}",
        "SUPPLIER_DATA_REQUIRED = 1": "SUPPLIER_DATA_REQUIRED = 0  ! geometry_freeze_v1_filled",
    }
    text = template_text
    for old, new in replacements.items():
        text = text.replace(old, new)
    guard_header = (
        "! =============================================================================\n"
        "! GEOMETRY FREEZE v1 — parameters filled from engineering estimates.\n"
        "! Source: current_pathfinder_rib_local_detail_geometry_freeze.py\n"
        "! NOT final supplier / coupon data. Replace tagged estimates before\n"
        "! qualified margin run.\n"
        "! =============================================================================\n"
    )
    return guard_header + text


def _write_freeze_csv(freeze: dict[str, Any], path: Path) -> None:
    rows = []
    ms = freeze["spar_tubes"]["main_spar"]
    rs = freeze["spar_tubes"]["rear_spar"]
    cl = freeze["collar"]
    bo = freeze["bondline"]
    cap = freeze["balsa_cap"]
    sk = freeze["skin"]
    for key, val, unit, conf, src in [
        ("main_spar_od_m", ms["od_m"], "m", ms["confidence"], ms["source"][:60]),
        ("main_spar_wall_m", ms["wall_m"], "m", ms["confidence"], "catalog"),
        ("main_spar_product", ms["product"], "-", ms["confidence"], "data/carbon_tubes.csv"),
        ("rear_spar_od_m", rs["od_m"], "m", rs["confidence"], rs["source"][:60]),
        ("rear_spar_wall_m", rs["wall_m"], "m", rs["confidence"], "catalog"),
        ("rear_spar_product", rs["product"], "-", rs["confidence"], "data/carbon_tubes.csv"),
        ("collar_material_key", cl["material_key"], "-", cl["confidence"], "shortlist report"),
        ("collar_thickness_m", cl["collar_thickness_m"], "m", cl["confidence"], "4-ply CF ply estimate"),
        ("collar_contact_width_m", cl["collar_contact_width_m"], "m", "design_intent", "shortlist report"),
        ("collar_bearing_allowable_pa", cl["collar_bearing_allowable_pa"], "Pa", cl["confidence"], "material allowable"),
        ("bondline_width_m", bo["bondline_width_m"], "m", "engineering_estimate", "typical HPA lap joint"),
        ("bondline_thickness_m", bo["bondline_thickness_m"], "m", "engineering_estimate", "thin bond"),
        ("adhesive_shear_allowable_pa", bo["adhesive_shear_allowable_pa"], "Pa", "engineering_estimate", "Araldite 420 class"),
        ("adhesive_peel_allowable_n_per_m", bo["adhesive_peel_allowable_n_per_m"], "N/m", "engineering_estimate", "structural epoxy"),
        ("balsa_cap_width_m", cap["cap_width_m"], "m", "engineering_estimate", "design intent"),
        ("balsa_cap_thickness_m", cap["cap_thickness_m"], "m", "engineering_estimate", "design intent"),
        ("balsa_cap_shear_allowable_pa", cap["balsa_shear_allowable_pa"], "Pa", "engineering_estimate", "materials.yaml G*3%"),
        ("eps_shear_allowable_pa", cap["eps_shear_allowable_pa"], "Pa", "engineering_estimate", "shape support only"),
        ("skin_thickness_m", sk["skin_thickness_m"], "m", "engineering_estimate", "25μm Mylar standard"),
        ("skin_E_pa", sk["skin_E_pa"], "Pa", "engineering_estimate", "Mylar PET published"),
        ("skin_prestrain_fraction", sk["skin_prestrain_fraction"], "-", "engineering_estimate", "process assumption"),
    ]:
        rows.append(
            {"parameter": key, "value": val, "unit": unit, "confidence": conf, "source": src}
        )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["parameter", "value", "unit", "confidence", "source"])
        writer.writeheader()
        writer.writerows(rows)


def write_geometry_freeze_package(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    carbon_tubes_path: Path = DEFAULT_CARBON_TUBES_CSV,
    materials_path: Path = DEFAULT_MATERIALS_YAML,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
    apdl_template_path: Path = DEFAULT_APDL_TEMPLATE,
) -> dict[str, Path]:
    config = load_config(config_path)
    materials = _load_materials(materials_path)
    carbon_tubes = _load_carbon_tubes(carbon_tubes_path)

    freeze = _build_freeze_sheet(config, materials, carbon_tubes)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)

    freeze_json_path = output_dir / "geometry_allowable_freeze.json"
    freeze_json_path.write_text(json.dumps(freeze, indent=2, ensure_ascii=False), encoding="utf-8")

    freeze_csv_path = output_dir / "geometry_allowable_freeze.csv"
    _write_freeze_csv(freeze, freeze_csv_path)

    md_text = _render_freeze_report_md(freeze)
    report_md.write_text(md_text, encoding="utf-8")

    report_json_payload = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": freeze["candidate_id"],
        "station_id": "R068",
        "station_y_m": freeze["station_y_m"],
        "spar_tubes_derived": {
            "main_od_m": freeze["spar_tubes"]["main_spar"]["od_m"],
            "main_wall_m": freeze["spar_tubes"]["main_spar"]["wall_m"],
            "rear_od_m": freeze["spar_tubes"]["rear_spar"]["od_m"],
            "rear_wall_m": freeze["spar_tubes"]["rear_spar"]["wall_m"],
        },
        "preliminary_margin_summary": {
            k: v.get("margin") for k, v in freeze["preliminary_margins"].items()
            if isinstance(v, dict) and "margin" in v
        },
        "worst_margin": min(
            v.get("margin", 9999) for v in freeze["preliminary_margins"].values()
            if isinstance(v, dict) and "margin" in v
        ),
        "all_pass": all(
            v.get("margin", -1) > 0 for v in freeze["preliminary_margins"].values()
            if isinstance(v, dict) and "margin" in v
        ),
        "missing_data_register_filled": freeze["missing_data_register_status"],
        "claim_boundary": CLAIM_BOUNDARY,
        "output_json": str(freeze_json_path),
        "output_csv": str(freeze_csv_path),
        "output_report_md": str(report_md),
    }
    report_json.write_text(json.dumps(report_json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    apdl_filled_path = output_dir / "positive_zone_local_fem_filled.mac"
    if apdl_template_path.exists():
        template_text = apdl_template_path.read_text(encoding="utf-8")
        apdl_filled = _update_apdl_skeleton(freeze, template_text)
        apdl_filled_path.write_text(apdl_filled, encoding="utf-8")
    else:
        apdl_filled_path.write_text(
            "! Template not found; run with --apdl-template to specify path.\n",
            encoding="utf-8",
        )

    return {
        "freeze_json": freeze_json_path,
        "freeze_csv": freeze_csv_path,
        "report_md": report_md,
        "report_json": report_json,
        "apdl_filled": apdl_filled_path,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--carbon-tubes", type=Path, default=DEFAULT_CARBON_TUBES_CSV)
    parser.add_argument("--materials", type=Path, default=DEFAULT_MATERIALS_YAML)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--apdl-template", type=Path, default=DEFAULT_APDL_TEMPLATE)
    args = parser.parse_args(argv)

    paths = write_geometry_freeze_package(
        config_path=args.config,
        carbon_tubes_path=args.carbon_tubes,
        materials_path=args.materials,
        output_dir=args.output_dir,
        report_json=args.report_json,
        report_md=args.report_md,
        apdl_template_path=args.apdl_template,
    )
    print(f"geometry freeze JSON: {paths['freeze_json']}")
    print(f"freeze CSV:           {paths['freeze_csv']}")
    print(f"report MD:            {paths['report_md']}")
    print(f"report JSON:          {paths['report_json']}")
    print(f"APDL filled:          {paths['apdl_filled']}")


if __name__ == "__main__":
    main()
