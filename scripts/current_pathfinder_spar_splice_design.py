#!/usr/bin/env python3
"""Spar splice joint design for 3 m wing panel segmentation.

The pathfinder wing (half-span 17.3 m) is divided into ≤ 3 m panels for
transport. Each panel boundary requires a spar splice joint. This script
designs the splice at every 3 m station, checks structural margins, and
estimates the total weight penalty.

Architecture (Airglow-informed):
  Internal spigot sleeve: resists bending moment and shear
    - CFRP tube inserted inside spar, overlap each side = 4 × D_spar
    - Transfers moment via contact couple at sleeve ends
    - Anti-ovalization ring required at each sleeve end
  External ferrule + shear dog: resists torsion and axial compression
    - Permanent CFRP ring bonded to spar end face
    - Keyed shear dog prevents rotation and axial slip
    - Removable pin through ferrule only (never through CFRP spar)

References:
  - Airglow HPA: plug-together joints, small tube into large tube, 4D overlap,
    bonded aluminium fittings for torsion/compression (studylib.net)
  - NPL MATC65: avoid peel, taper adhesive ends, fillet corners
  - NASA-STD-5020B: fastener preload variation for pin sizing

Load basis: phase12_spanload_structure_diagnosis/current_spanload_bending.csv
  Loads are unfactored aerodynamic. Applied load_factor from geometry freeze.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "spar_splice_design_v1"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SPANLOAD_CSV = (
    _REPO_ROOT / "output" / "phase12_spanload_structure_diagnosis"
    / "current_spanload_bending.csv"
)
_FREEZE_JSON = (
    _REPO_ROOT / "output" / "current_pathfinder_rib_local_detail_geometry_freeze"
    / "geometry_allowable_freeze.json"
)
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "output" / "current_pathfinder_spar_splice_design"

# ---------------------------------------------------------------------------
# Material / geometry constants
# ---------------------------------------------------------------------------

CFRP_DENSITY_KG_M3 = 1580.0       # typical CFRP tube density
CFRP_SIGMA_BEND_PA = 600.0e6       # bending allowable (HM CFRP, 0° ply dominant)
CFRP_SIGMA_BEARING_PA = 200.0e6    # bearing allowable for CFRP tube wall
CFRP_TAU_SHEAR_PA = 40.0e6         # shear allowable for CFRP tube wall

SPIGOT_OVERLAP_D_RATIO = 4.0       # L_overlap per side = ratio × D_spar (Airglow)
SPIGOT_WALL_M = 0.0008             # spigot wall thickness [m] — 0.8 mm CFRP
ANTI_OVAL_RING_MASS_G = 3.0        # anti-ovalization ring mass [g] (per ring, 2 per joint)

FERRULE_WIDTH_M = 0.025            # ferrule axial width [m]
FERRULE_OD_RATIO = 1.25            # ferrule OD / spar OD
FERRULE_WALL_M = 0.0015            # ferrule wall [m]
SHEAR_DOG_MASS_G = 2.5             # single shear dog mass [g]
N_SHEAR_DOGS = 2                   # per joint

END_RIB_MASS_G = 20.0              # hard end rib (birch ply / Rohacell sandwich) [g]
PIN_MASS_G = 3.0                   # removable alignment pin [g]


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def _load_spanwise_csv(path: Path) -> list[dict[str, float]]:
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({k: float(v) for k, v in r.items()})
    return rows


def _interpolate_at(rows: list[dict[str, float]], y_target: float,
                    key: str) -> float:
    """Linear interpolation of *key* at y_target [m]."""
    ys = [r["y_m"] for r in rows]
    vs = [r[key] for r in rows]
    if y_target <= ys[0]:
        return vs[0]
    if y_target >= ys[-1]:
        return vs[-1]
    for i in range(len(ys) - 1):
        if ys[i] <= y_target <= ys[i + 1]:
            t = (y_target - ys[i]) / (ys[i + 1] - ys[i])
            return vs[i] + t * (vs[i + 1] - vs[i])
    return 0.0


# ---------------------------------------------------------------------------
# Splice station load container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpliceLoad:
    y_m: float          # splice location [m]
    M_nm: float         # factored bending moment [N·m]
    V_n: float          # factored shear force [N]
    T_nm: float         # factored torsion [N·m] (estimated from station data)


def _build_splice_loads(
    rows: list[dict[str, float]],
    splice_ys: list[float],
    load_factor: float,
    torque_per_chord_nm_m: float,
) -> list[SpliceLoad]:
    """Build factored loads at each splice location.

    Torsion at each y is estimated by scaling the known kernel torque linearly
    with local chord (chord decreases toward tip → torque decreases).
    """
    loads = []
    for y in splice_ys:
        M_raw = _interpolate_at(rows, y, "bending_moment_nm")
        V_raw = _interpolate_at(rows, y, "shear_force_n")
        chord = _interpolate_at(rows, y, "chord_m")
        T_est = torque_per_chord_nm_m * chord
        loads.append(SpliceLoad(
            y_m=y,
            M_nm=M_raw * load_factor,
            V_n=V_raw * load_factor,
            T_nm=T_est * load_factor,
        ))
    return loads


# ---------------------------------------------------------------------------
# Spigot design
# ---------------------------------------------------------------------------

@dataclass
class SpigotDesign:
    y_m: float
    spar_od_m: float
    spigot_od_m: float
    spigot_wall_m: float
    overlap_each_side_m: float
    total_length_m: float
    mass_g: float
    margin_bending: float
    margin_shear: float
    margin_bearing_outer: float
    governs: str
    passes: bool
    detail: dict[str, Any] = field(default_factory=dict)


def _min_spigot_wall(load: SpliceLoad, spar_od_m: float,
                     spar_wall_m: float) -> float:
    """Binary search for minimum spigot wall that satisfies bending margin."""
    D = spar_od_m
    t_spar = spar_wall_m
    D_spigot = D - 2.0 * t_spar - 0.0002
    R_spigot = D_spigot / 2.0
    # Need I ≥ M × R / σ_allow
    I_min = load.M_nm * R_spigot / CFRP_SIGMA_BEND_PA
    # π/4 × (R^4 - (R-t)^4) = I_min  → solve for t
    # Binary search on t in [0.0005, R_spigot/2]
    t_lo, t_hi = 0.0005, R_spigot / 2.0
    for _ in range(60):
        t_mid = 0.5 * (t_lo + t_hi)
        moi = math.pi / 4.0 * (R_spigot**4 - (R_spigot - t_mid)**4)
        if moi >= I_min:
            t_hi = t_mid
        else:
            t_lo = t_mid
    return t_hi


def _design_spigot(load: SpliceLoad, spar_od_m: float,
                   spar_wall_m: float) -> SpigotDesign:
    D = spar_od_m
    t_spar = spar_wall_m
    D_spigot = D - 2.0 * t_spar - 0.0002  # 0.2 mm diametral clearance
    # Auto-size wall: use minimum of design constant or bending requirement
    t_spigot = max(SPIGOT_WALL_M, _min_spigot_wall(load, spar_od_m, spar_wall_m))
    L_overlap = SPIGOT_OVERLAP_D_RATIO * D  # per side
    L_total = 2.0 * L_overlap

    R_spigot = D_spigot / 2.0
    # Second moment of area of spigot tube
    I_spigot = math.pi / 4.0 * (R_spigot**4 - (R_spigot - t_spigot)**4)

    # --- Bending margin ---
    # Spigot carries bending via contact couple at overlap ends.
    # Conservative: treat spigot as the sole bending element.
    sigma_bend_spigot = load.M_nm * R_spigot / I_spigot
    m_bending = CFRP_SIGMA_BEND_PA / sigma_bend_spigot - 1.0

    # --- Shear margin (spigot wall) ---
    # Average shear stress in spigot wall: V / (2 × A_wall)
    A_wall_spigot = math.pi * D_spigot * t_spigot
    tau_shear = load.V_n / A_wall_spigot
    m_shear = CFRP_TAU_SHEAR_PA / tau_shear - 1.0

    # --- Bearing on spar inner wall (contact force at overlap end) ---
    # F_contact ≈ M / L_overlap (two-point contact model)
    F_contact = load.M_nm / L_overlap
    # Contact area: D × (L_overlap / 4) — Hertzian line contact approximation
    A_bearing_spar = D * (L_overlap / 4.0)
    sigma_bearing = F_contact / A_bearing_spar
    m_bearing = CFRP_SIGMA_BEARING_PA / sigma_bearing - 1.0

    # Mass: spigot tube + 2 anti-ovalization rings
    rho = CFRP_DENSITY_KG_M3
    m_spigot_kg = math.pi * D_spigot * t_spigot * L_total * rho
    m_rings_kg = 2 * ANTI_OVAL_RING_MASS_G / 1000.0
    mass_g = (m_spigot_kg + m_rings_kg) * 1000.0

    sub = {"bending": m_bending, "shear": m_shear, "bearing_outer": m_bearing}
    ms = min(sub.values())
    governs = min(sub, key=sub.__getitem__)

    return SpigotDesign(
        y_m=load.y_m,
        spar_od_m=D,
        spigot_od_m=D_spigot,
        spigot_wall_m=t_spigot,
        overlap_each_side_m=L_overlap,
        total_length_m=L_total,
        mass_g=round(mass_g, 1),
        margin_bending=round(m_bending, 3),
        margin_shear=round(m_shear, 3),
        margin_bearing_outer=round(m_bearing, 3),
        governs=governs,
        passes=ms > 0,
        detail={
            "D_spigot_mm": round(D_spigot * 1000, 2),
            "spigot_wall_mm": round(t_spigot * 1000, 2),
            "L_overlap_mm": round(L_overlap * 1000, 1),
            "sigma_bend_mpa": round(sigma_bend_spigot / 1e6, 1),
            "tau_shear_mpa": round(tau_shear / 1e6, 3),
            "F_contact_n": round(F_contact, 1),
            "sigma_bearing_mpa": round(sigma_bearing / 1e6, 2),
            "sub_margins": {k: round(v, 3) for k, v in sub.items()},
        },
    )


# ---------------------------------------------------------------------------
# Ferrule + shear dog design
# ---------------------------------------------------------------------------

@dataclass
class FerruleDesign:
    y_m: float
    ferrule_od_m: float
    ferrule_width_m: float
    mass_g: float
    margin_torsion: float
    governs: str
    passes: bool
    detail: dict[str, Any] = field(default_factory=dict)


def _design_ferrule(load: SpliceLoad, spar_od_m: float) -> FerruleDesign:
    D_ferrule = spar_od_m * FERRULE_OD_RATIO
    t_ferrule = FERRULE_WALL_M
    w = FERRULE_WIDTH_M

    # Shear dog resists torsion via bearing: T = n_dogs × F_dog × r_dog
    # r_dog ≈ D_ferrule/2 (dog at ferrule OD)
    r_dog = D_ferrule / 2.0
    F_dog_each = load.T_nm / (N_SHEAR_DOGS * r_dog)

    # Dog bearing area: dog height × dog width (estimated)
    dog_height_m = 0.006
    dog_width_m = 0.010
    A_dog = dog_height_m * dog_width_m
    sigma_dog_bearing = F_dog_each / A_dog
    m_torsion = CFRP_SIGMA_BEARING_PA / sigma_dog_bearing - 1.0

    # Mass: ferrule tube ring + shear dogs + pin
    rho = CFRP_DENSITY_KG_M3
    m_ferrule_kg = math.pi * D_ferrule * t_ferrule * w * rho
    m_dogs_kg = N_SHEAR_DOGS * SHEAR_DOG_MASS_G / 1000.0
    m_pin_kg = PIN_MASS_G / 1000.0
    m_end_rib_kg = END_RIB_MASS_G / 1000.0
    mass_g = (m_ferrule_kg + m_dogs_kg + m_pin_kg + m_end_rib_kg) * 1000.0

    return FerruleDesign(
        y_m=load.y_m,
        ferrule_od_m=D_ferrule,
        ferrule_width_m=w,
        mass_g=round(mass_g, 1),
        margin_torsion=round(m_torsion, 3),
        governs="torsion_shear_dog",
        passes=m_torsion > 0,
        detail={
            "D_ferrule_mm": round(D_ferrule * 1000, 1),
            "r_dog_mm": round(r_dog * 1000, 1),
            "F_dog_n": round(F_dog_each, 3),
            "sigma_dog_bearing_mpa": round(sigma_dog_bearing / 1e6, 4),
            "n_shear_dogs": N_SHEAR_DOGS,
        },
    )


# ---------------------------------------------------------------------------
# Joint assembly
# ---------------------------------------------------------------------------

@dataclass
class SpliceJoint:
    y_m: float
    load: SpliceLoad
    spigot: SpigotDesign
    ferrule: FerruleDesign
    total_mass_g: float
    passes: bool
    governing_margin: float
    governs: str


def _assemble_joint(load: SpliceLoad, spar_od_m: float,
                    spar_wall_m: float) -> SpliceJoint:
    spigot = _design_spigot(load, spar_od_m, spar_wall_m)
    ferrule = _design_ferrule(load, spar_od_m)
    total_mass_g = spigot.mass_g + ferrule.mass_g
    margins = {
        f"spigot:{spigot.governs}": min(
            spigot.margin_bending, spigot.margin_shear, spigot.margin_bearing_outer
        ),
        f"ferrule:{ferrule.governs}": ferrule.margin_torsion,
    }
    gm = min(margins.values())
    gk = min(margins, key=margins.__getitem__)
    return SpliceJoint(
        y_m=load.y_m,
        load=load,
        spigot=spigot,
        ferrule=ferrule,
        total_mass_g=round(total_mass_g, 1),
        passes=spigot.passes and ferrule.passes,
        governing_margin=round(gm, 3),
        governs=gk,
    )


# ---------------------------------------------------------------------------
# Full design sweep
# ---------------------------------------------------------------------------

def run_splice_design(
    freeze: dict[str, Any],
    spanload_rows: list[dict[str, float]],
) -> dict[str, Any]:
    """Run splice joint design for all 3 m stations on the pathfinder half-wing."""
    load_factor = float(freeze["load_factor"])
    spar_od_m = float(freeze["spar_tubes"]["main_spar"]["od_m"])
    spar_wall_m = float(freeze["spar_tubes"]["main_spar"]["wall_m"])
    half_span_m = float(freeze["spar_tubes"]["half_span_m"])

    # Torsion at the freeze station → torque per unit chord
    T_kernel = abs(float(freeze["local_kernel_torque_n_m"]))
    chord_station = float(freeze["chord_m"])
    torque_per_chord = T_kernel / chord_station  # [N·m / m]

    # Splice locations at every 3 m up to half span
    panel_length = 3.0
    n_panels = math.ceil(half_span_m / panel_length)
    splice_ys = [panel_length * i for i in range(1, n_panels)]
    splice_ys = [y for y in splice_ys if y < half_span_m]

    loads = _build_splice_loads(spanload_rows, splice_ys, load_factor,
                                torque_per_chord)
    joints = [_assemble_joint(ld, spar_od_m, spar_wall_m) for ld in loads]

    # Weight budget
    total_half_wing_g = sum(j.total_mass_g for j in joints)
    total_full_wing_g = 2.0 * total_half_wing_g  # symmetric

    all_pass = all(j.passes for j in joints)
    worst_joint = min(joints, key=lambda j: j.governing_margin)

    return {
        "schema_version": SCHEMA_VERSION,
        "half_span_m": half_span_m,
        "panel_length_m": panel_length,
        "n_panels_per_half": n_panels,
        "n_splice_joints_per_half": len(joints),
        "n_splice_joints_full_wing": 2 * len(joints),
        "load_factor": load_factor,
        "spar_od_mm": round(spar_od_m * 1000, 1),
        "spar_wall_mm": round(spar_wall_m * 1000, 1),
        "all_pass": all_pass,
        "worst_joint_y_m": worst_joint.y_m,
        "worst_joint_margin": worst_joint.governing_margin,
        "worst_joint_governs": worst_joint.governs,
        "total_splice_mass_half_wing_g": round(total_half_wing_g, 1),
        "total_splice_mass_full_wing_g": round(total_full_wing_g, 1),
        "total_splice_mass_full_wing_kg": round(total_full_wing_g / 1000.0, 3),
        "joints": [
            {
                "y_m": j.y_m,
                "M_nm": round(j.load.M_nm, 1),
                "V_n": round(j.load.V_n, 1),
                "T_nm": round(j.load.T_nm, 3),
                "spigot_wall_mm": j.spigot.detail.get("spigot_wall_mm"),
                "spigot_mass_g": j.spigot.mass_g,
                "ferrule_mass_g": j.ferrule.mass_g,
                "total_mass_g": j.total_mass_g,
                "spigot_overlap_mm": round(j.spigot.overlap_each_side_m * 1000, 1),
                "margin_bending": j.spigot.margin_bending,
                "margin_shear": j.spigot.margin_shear,
                "margin_bearing": j.spigot.margin_bearing_outer,
                "margin_torsion": j.ferrule.margin_torsion,
                "governing_margin": j.governing_margin,
                "governs": j.governs,
                "passes": j.passes,
            }
            for j in joints
        ],
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _write_csv(joints: list[dict], path: Path) -> None:
    if not joints:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(joints[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(joints)


def _write_md(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Spar Splice Design — 3 m Panel Segmentation",
        "",
        f"Schema: `{result['schema_version']}` · Load factor: {result['load_factor']}",
        "",
        "## Summary",
        "",
        f"- Half-span: **{result['half_span_m']} m** → "
        f"{result['n_panels_per_half']} panels × ≤3 m",
        f"- Splice joints per half-wing: **{result['n_splice_joints_per_half']}** "
        f"(full wing: {result['n_splice_joints_full_wing']})",
        f"- All joints pass: **{result['all_pass']}**",
        f"- Worst margin: **{result['worst_joint_margin']:.3f}** "
        f"at y={result['worst_joint_y_m']:.1f} m ({result['worst_joint_governs']})",
        "",
        "## Weight Budget",
        "",
        "| Half-wing splices | Full-wing splices |",
        "|:-----------------:|:-----------------:|",
        f"| **{result['total_splice_mass_half_wing_g']:.0f} g** "
        f"| **{result['total_splice_mass_full_wing_g']:.0f} g "
        f"({result['total_splice_mass_full_wing_kg']:.2f} kg)** |",
        "",
        "## Joint-by-Joint Results",
        "",
        "| y [m] | M [N·m] | V [N] | T [N·m] | Mass [g] | Bend MS | Shear MS"
        " | Bear MS | Tors MS | Governs | Pass |",
        "|------:|--------:|------:|--------:|---------:|--------:|---------:"
        "|--------:|--------:|---------|------|",
    ]
    for j in result["joints"]:
        lines.append(
            f"| {j['y_m']:.1f} | {j['M_nm']:.0f} | {j['V_n']:.0f}"
            f" | {j['T_nm']:.2f} | {j['total_mass_g']:.0f}"
            f" | {j['margin_bending']:.2f} | {j['margin_shear']:.2f}"
            f" | {j['margin_bearing']:.2f} | {j['margin_torsion']:.2f}"
            f" | {j['governs']} | {'✓' if j['passes'] else '✗'} |"
        )
    lines += [
        "",
        "## Architecture Notes",
        "",
        "- **Spigot**: CFRP tube, OD ≈ spar ID − 0.2 mm clearance, wall 0.8 mm, "
        "overlap 4 × D each side. Carries bending + shear.",
        "- **Ferrule**: CFRP ring bonded to spar end, OD = 1.25 × spar OD, width 25 mm. "
        "Carries torsion via shear dogs. Removable pin (never through CFRP spar).",
        "- **Anti-ovalization ring**: CFRP bulkhead at each spigot end; prevents "
        "1 mm wall tube collapse under contact forces.",
        "- **End rib**: hard birch ply / Rohacell sandwich; transmits assembly loads "
        "and covering tension.",
        "",
        "> Loads from `phase12_spanload_structure_diagnosis/current_spanload_bending.csv` "
        "(factored). Torsion estimated from kernel torque per chord at R068 station.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def write_splice_design_package(
    output_dir: Path | None = None,
    report_json: Path | None = None,
    report_md: Path | None = None,
    joints_csv: Path | None = None,
) -> dict[str, Path]:
    out = output_dir or _DEFAULT_OUTPUT_DIR
    rj = report_json or out / "splice_design_report.json"
    rm = report_md or out / "splice_design_report.md"
    rc = joints_csv or out / "splice_joints.csv"

    freeze = json.loads(_FREEZE_JSON.read_text())
    spanload_rows = _load_spanwise_csv(_SPANLOAD_CSV)
    result = run_splice_design(freeze, spanload_rows)

    out.mkdir(parents=True, exist_ok=True)
    rj.write_text(json.dumps(result, indent=2), encoding="utf-8")
    _write_csv(result["joints"], rc)
    _write_md(result, rm)

    return {"report_json": rj, "report_md": rm, "joints_csv": rc}


if __name__ == "__main__":
    paths = write_splice_design_package()
    result = json.loads(paths["report_json"].read_text())
    print(f"Joints per half-wing: {result['n_splice_joints_per_half']}")
    print(f"Total splice mass (full wing): {result['total_splice_mass_full_wing_kg']:.2f} kg")
    print(f"All pass: {result['all_pass']}")
    print(f"Worst margin: {result['worst_joint_margin']:.3f} @ y={result['worst_joint_y_m']:.1f} m"
          f" ({result['worst_joint_governs']})")
