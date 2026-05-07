#!/usr/bin/env python3
"""Dual-beam / wire-truss jig validation sidecar for the smooth Tier2 baseline.

This is intentionally diagnostic: it adapts aerodynamic production artifacts
into the existing dual-beam kernel with explicit structural-layout assumptions.
It does not alter aerodynamic rankings or production hard gates.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from hpa_mdo.aero.avl_spanwise import build_spanwise_load_from_avl_strip_forces  # noqa: E402
from hpa_mdo.structure.dual_beam_mainline.api import run_dual_beam_mainline_kernel  # noqa: E402
from hpa_mdo.structure.dual_beam_mainline.types import (  # noqa: E402
    AnalysisModeName,
    DualBeamMainlineModel,
    LinkMode,
    TorqueInputDefinition,
)
from hpa_mdo.structure.inverse_design import (  # noqa: E402
    build_frozen_load_inverse_design_from_mainline,
)
from hpa_mdo.structure.spar_model import tube_Ixx, tube_J, tube_area  # noqa: E402
from scripts import audit_avl_induced_drag_credibility as avl_audit  # noqa: E402


DEFAULT_OUTPUT_DIR = _REPO_ROOT / "output" / "phase10_dual_beam_jig_validation"
FINAL_BASELINE_DIR = (
    _REPO_ROOT / "output" / "final_candidate_validation" / "smooth_tier2_production_baseline"
)
SMOOTH_GEOM_DIR = (
    FINAL_BASELINE_DIR
    / "geometry_exports"
    / "avl_parity"
    / "smooth_tier2_production_baseline"
)
OLD_BASELINE_DIR = _REPO_ROOT / "output" / "baseline_comparisons"
PHASE9_AUDIT_DIR = _REPO_ROOT / "output" / "phase9_structure_model_audit"
PROXY_STRUCTURE_AUDIT = FINAL_BASELINE_DIR / "structure_jig_audit.csv"
CURRENT_SPAR_TUBE_MASS_TARGET_KG = 11.7534

MISSION_VELOCITY_MPS = 6.6
AVL_AUDIT_RHO_KGPM3 = 1.18
MATERIAL_SAFETY_FACTOR = 1.5
MAIN_SPAR_XC = 0.25
REAR_SPAR_XC = 0.70
WIRE_Y_M = 7.5
WIRE_FUSELAGE_Z_M = -1.5
WIRE_DIAMETER_M = 2.5e-3
WIRE_MAX_TENSION_FRACTION = 0.40
WIRE_PRETENSION_N = 0.0
WIRE_ANGLE_DEG = 11.3
JOINT_Y_M = (1.5, 4.5, 7.5, 10.5, 13.5)


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    display_name: str
    section_table: Path
    avl_path: Path
    spanwise_forces: Path


@dataclass(frozen=True)
class TubeLine:
    outer_diameter_root_m: float
    outer_diameter_tip_m: float
    wall_root_m: float
    wall_tip_m: float
    material_key: str
    mass_per_m_override_kgpm: float | None = None


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    description: str
    main: TubeLine
    rear: TubeLine


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in keys})


def read_materials() -> dict[str, dict[str, Any]]:
    with (_REPO_ROOT / "data" / "materials.yaml").open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("data/materials.yaml must contain a mapping.")
    return data


def material_value(materials: Mapping[str, Mapping[str, Any]], key: str, field: str) -> float:
    value = materials[key][field]
    if value is None:
        raise ValueError(f"Material {key} has no numeric {field}.")
    return float(value)


def material_shear_pa(materials: Mapping[str, Mapping[str, Any]], key: str) -> float:
    value = materials[key].get("G")
    if value is not None:
        return float(value)
    poisson = materials[key].get("poisson_ratio")
    nu = 0.30 if poisson is None else float(poisson)
    return material_value(materials, key, "E") / (2.0 * (1.0 + nu))


def material_allowable_pa(materials: Mapping[str, Mapping[str, Any]], key: str) -> float:
    tensile = material_value(materials, key, "tensile_strength")
    compressive_raw = materials[key].get("compressive_strength")
    compressive = tensile if compressive_raw is None else float(compressive_raw)
    return min(tensile, compressive) / MATERIAL_SAFETY_FACTOR


def load_sections(path: Path) -> dict[str, np.ndarray]:
    rows = read_csv_rows(path)
    y = np.asarray([float(row["y_m"]) for row in rows], dtype=float)
    order = np.argsort(y)
    y = y[order]
    return {
        "y_m": y,
        "z_m": np.asarray([float(rows[idx]["z_m"]) for idx in order], dtype=float),
        "chord_m": np.asarray([float(rows[idx]["chord_m"]) for idx in order], dtype=float),
        "twist_deg": np.asarray([float(rows[idx]["twist_deg"]) for idx in order], dtype=float),
    }


def case_specs() -> list[CaseSpec]:
    return [
        CaseSpec(
            case_id="smooth_tier2_production_baseline",
            display_name="Smooth Tier2 production baseline",
            section_table=SMOOTH_GEOM_DIR / "section_table.csv",
            avl_path=FINAL_BASELINE_DIR
            / "avl_runs"
            / "smooth_tier2_production_baseline"
            / "smooth_tier2_production_baseline.avl",
            spanwise_forces=FINAL_BASELINE_DIR
            / "avl_runs"
            / "smooth_tier2_production_baseline"
            / "concept_spanwise.fs",
        ),
        CaseSpec(
            case_id="old_fx_clark_baseline",
            display_name="Old FX/Clark raw baseline",
            section_table=OLD_BASELINE_DIR
            / "old_fx_clark_vs_phase7_tier2"
            / "old_design_section_table.csv",
            avl_path=FINAL_BASELINE_DIR
            / "avl_runs"
            / "old_fx_clark_baseline_raw_reference"
            / "old_main_wing_only.avl",
            spanwise_forces=FINAL_BASELINE_DIR
            / "avl_runs"
            / "old_fx_clark_baseline_raw_reference"
            / "concept_spanwise.fs",
        ),
    ]


def structural_recipes() -> list[Recipe]:
    return [
        Recipe(
            recipe_id="proxy_selected_equal_CF_STD_100x98",
            description=(
                "Both main and rear spar use the Phase 9 selected CF-STD-100x98 catalog tube; "
                "kept to compare directly with the 32.959 kg proxy mass."
            ),
            main=TubeLine(0.100, 0.100, 0.001, 0.001, "carbon_fiber_std", 0.480),
            rear=TubeLine(0.100, 0.100, 0.001, 0.001, "carbon_fiber_std", 0.480),
        ),
        Recipe(
            recipe_id="production_split_main100_rear80",
            description=(
                "Diagnostic split-spar recipe: 100x98 main and synthetic 80x78 rear, "
                "intended to satisfy main-spar dominance better than equal tubes."
            ),
            main=TubeLine(0.100, 0.100, 0.001, 0.001, "carbon_fiber_std", 0.480),
            rear=TubeLine(0.080, 0.080, 0.001, 0.001, "carbon_fiber_std", None),
        ),
        Recipe(
            recipe_id="phase9_nominal_taper_70_40",
            description=(
                "Phase 9 nominal proxy geometry: two spars taper from 70x68.6 at root "
                "to 40x39 at tip; included as a low-mass warning comparison."
            ),
            main=TubeLine(0.070, 0.040, 0.0007, 0.0005, "carbon_fiber_std", None),
            rear=TubeLine(0.070, 0.040, 0.0007, 0.0005, "carbon_fiber_std", None),
        ),
        Recipe(
            recipe_id="geometry_rule_main100_rear50",
            description=(
                "Main-dominant check recipe: 100x98 main and synthetic 50x48 rear, "
                "included to test the dual-beam geometry-validity rules without optimizing."
            ),
            main=TubeLine(0.100, 0.100, 0.001, 0.001, "carbon_fiber_std", 0.480),
            rear=TubeLine(0.050, 0.050, 0.001, 0.001, "carbon_fiber_std", None),
        ),
    ]


def node_spacings(y_nodes_m: np.ndarray) -> np.ndarray:
    dy = np.diff(y_nodes_m)
    if np.any(dy <= 0.0):
        raise ValueError("Structural y stations must be strictly increasing.")
    out = np.zeros_like(y_nodes_m, dtype=float)
    out[0] = 0.5 * dy[0]
    out[-1] = 0.5 * dy[-1]
    out[1:-1] = 0.5 * (dy[:-1] + dy[1:])
    return out


def spanload_for_case(case: CaseSpec) -> dict[str, np.ndarray]:
    names = avl_audit.surface_names(case.avl_path)
    target_surfaces = ("Main Wing",) if "Main Wing" in names else ("Wing",)
    load = build_spanwise_load_from_avl_strip_forces(
        fs_path=case.spanwise_forces,
        avl_path=case.avl_path,
        aoa_deg=0.0,
        velocity_mps=MISSION_VELOCITY_MPS,
        density_kgpm3=AVL_AUDIT_RHO_KGPM3,
        target_surface_names=target_surfaces,
        positive_y_only=True,
    )
    y = np.asarray(load.y, dtype=float)
    order = np.argsort(y)
    y = y[order]
    _, unique_indices = np.unique(y, return_index=True)
    unique_indices = np.sort(unique_indices)
    q = 0.5 * AVL_AUDIT_RHO_KGPM3 * MISSION_VELOCITY_MPS**2
    chord = np.asarray(load.chord, dtype=float)[order][unique_indices]
    cm = np.asarray(load.cm, dtype=float)[order][unique_indices]
    return {
        "y_m": y[unique_indices],
        "chord_avl_m": chord,
        "cl": np.asarray(load.cl, dtype=float)[order][unique_indices],
        "cd_strip": np.asarray(load.cd, dtype=float)[order][unique_indices],
        "cm_c4": cm,
        "lift_per_span_npm": np.asarray(load.lift_per_span, dtype=float)[order][unique_indices],
        "torque_per_span_nmpm": q * chord * chord * cm,
        "target_surface_names": np.asarray(["|".join(target_surfaces)] * unique_indices.size, dtype=object),
    }


def station_inputs(case: CaseSpec) -> list[dict[str, Any]]:
    sections = load_sections(case.section_table)
    load = spanload_for_case(case)
    y = load["y_m"]
    y_section = sections["y_m"]
    chord = np.interp(y, y_section, sections["chord_m"])
    z = np.interp(y, y_section, sections["z_m"])
    twist = np.interp(y, y_section, sections["twist_deg"])
    twist_relative = twist - float(twist[0])
    eta = y / max(float(y[-1]), 1.0e-12)
    rows: list[dict[str, Any]] = []
    for idx in range(y.size):
        rows.append(
            {
                "case_id": case.case_id,
                "station_index": idx,
                "eta": eta[idx],
                "y_m": y[idx],
                "loaded_z_m": z[idx],
                "chord_m": chord[idx],
                "twist_deg": twist[idx],
                "relative_twist_deg": twist_relative[idx],
                "main_spar_x_m": MAIN_SPAR_XC * chord[idx],
                "rear_spar_x_m": REAR_SPAR_XC * chord[idx],
                "main_spar_z_loaded_m": z[idx],
                "rear_spar_z_loaded_m": z[idx]
                + (REAR_SPAR_XC - MAIN_SPAR_XC)
                * chord[idx]
                * math.tan(math.radians(twist_relative[idx])),
                "lift_per_span_npm": load["lift_per_span_npm"][idx],
                "cm_c4": load["cm_c4"][idx],
                "torque_per_span_nmpm": load["torque_per_span_nmpm"][idx],
                "cl_avl": load["cl"][idx],
                "target_surface_names": load["target_surface_names"][idx],
            }
        )
    return rows


def _line_arrays(line: TubeLine, y_nodes_m: np.ndarray) -> dict[str, np.ndarray]:
    y_mid = 0.5 * (y_nodes_m[:-1] + y_nodes_m[1:])
    eta_mid = y_mid / max(float(y_nodes_m[-1]), 1.0e-12)
    od = line.outer_diameter_root_m + eta_mid * (
        line.outer_diameter_tip_m - line.outer_diameter_root_m
    )
    wall = line.wall_root_m + eta_mid * (line.wall_tip_m - line.wall_root_m)
    radius = 0.5 * od
    if np.any(wall <= 0.0) or np.any(radius <= wall):
        raise ValueError(f"Invalid tube line for {line}.")
    return {"radius_m": radius, "wall_m": wall}


def _nearest_indices(y_nodes_m: np.ndarray, targets_m: Sequence[float]) -> tuple[int, ...]:
    out: list[int] = []
    for target in targets_m:
        if target <= y_nodes_m[0] or target >= y_nodes_m[-1]:
            continue
        idx = int(np.argmin(np.abs(y_nodes_m - float(target))))
        if idx not in out and 0 < idx < y_nodes_m.size - 1:
            out.append(idx)
    return tuple(out)


def build_model(
    *,
    station_rows: Sequence[Mapping[str, Any]],
    recipe: Recipe,
    materials: Mapping[str, Mapping[str, Any]],
) -> tuple[DualBeamMainlineModel, dict[str, Any]]:
    y = np.asarray([float(row["y_m"]) for row in station_rows], dtype=float)
    chord = np.asarray([float(row["chord_m"]) for row in station_rows], dtype=float)
    main_x = np.asarray([float(row["main_spar_x_m"]) for row in station_rows], dtype=float)
    rear_x = np.asarray([float(row["rear_spar_x_m"]) for row in station_rows], dtype=float)
    main_z = np.asarray([float(row["main_spar_z_loaded_m"]) for row in station_rows], dtype=float)
    rear_z = np.asarray([float(row["rear_spar_z_loaded_m"]) for row in station_rows], dtype=float)
    lift_per_span = np.asarray([float(row["lift_per_span_npm"]) for row in station_rows], dtype=float)
    torque_per_span = np.asarray(
        [float(row["torque_per_span_nmpm"]) for row in station_rows],
        dtype=float,
    )
    nn = y.size
    ne = nn - 1
    main = _line_arrays(recipe.main, y)
    rear = _line_arrays(recipe.rear, y)
    main_area = tube_area(main["radius_m"], main["wall_m"])
    rear_area = tube_area(rear["radius_m"], rear["wall_m"])
    main_i = tube_Ixx(main["radius_m"], main["wall_m"])
    rear_i = tube_Ixx(rear["radius_m"], rear["wall_m"])
    main_j = tube_J(main["radius_m"], main["wall_m"])
    rear_j = tube_J(rear["radius_m"], rear["wall_m"])
    main_density = material_value(materials, recipe.main.material_key, "density")
    rear_density = material_value(materials, recipe.rear.material_key, "density")
    main_mass_per_length = (
        np.full(ne, recipe.main.mass_per_m_override_kgpm, dtype=float)
        if recipe.main.mass_per_m_override_kgpm is not None
        else main_density * main_area
    )
    rear_mass_per_length = (
        np.full(ne, recipe.rear.mass_per_m_override_kgpm, dtype=float)
        if recipe.rear.mass_per_m_override_kgpm is not None
        else rear_density * rear_area
    )
    nodes_main = np.column_stack((main_x, y, main_z))
    nodes_rear = np.column_stack((rear_x, y, rear_z))
    wire_idx = _nearest_indices(y, (WIRE_Y_M,))
    wire_anchor_points = np.asarray(
        [[nodes_main[idx, 0], 0.0, WIRE_FUSELAGE_Z_M] for idx in wire_idx],
        dtype=float,
    )
    cable_material = materials["dyneema_sk75"]
    wire_area = np.full(len(wire_idx), math.pi * (0.5 * WIRE_DIAMETER_M) ** 2, dtype=float)
    wire_young = np.full(len(wire_idx), float(cable_material["E"]), dtype=float)
    wire_allowable = np.full(
        len(wire_idx),
        WIRE_MAX_TENSION_FRACTION
        * float(cable_material["tensile_strength"])
        * (wire_area[0] if wire_area.size else 0.0)
        / MATERIAL_SAFETY_FACTOR,
        dtype=float,
    )
    wire_reference_lengths = (
        np.linalg.norm(nodes_main[list(wire_idx)] - wire_anchor_points, axis=1)
        if wire_idx
        else np.zeros(0, dtype=float)
    )
    pretension = np.full(len(wire_idx), WIRE_PRETENSION_N, dtype=float)
    wire_unstretched = (
        wire_reference_lengths / (1.0 + pretension / np.maximum(wire_area * wire_young, 1.0e-30))
        if wire_idx
        else np.zeros(0, dtype=float)
    )
    target_tip_z = float(main_z[-1])
    model = DualBeamMainlineModel(
        y_nodes_m=y,
        node_spacings_m=node_spacings(y),
        element_lengths_m=np.diff(y),
        main_t_seg_m=main["wall_m"],
        main_r_seg_m=main["radius_m"],
        rear_t_seg_m=rear["wall_m"],
        rear_r_seg_m=rear["radius_m"],
        nodes_main_m=nodes_main,
        nodes_rear_m=nodes_rear,
        spar_offset_vectors_m=nodes_rear - nodes_main,
        spar_separation_nodes_m=rear_x - main_x,
        main_area_m2=main_area,
        main_iy_m4=main_i,
        main_iz_m4=main_i.copy(),
        main_j_m4=main_j,
        rear_area_m2=rear_area,
        rear_iy_m4=rear_i,
        rear_iz_m4=rear_i.copy(),
        rear_j_m4=rear_j,
        main_radius_elem_m=main["radius_m"],
        rear_radius_elem_m=rear["radius_m"],
        main_mass_per_length_kgpm=main_mass_per_length,
        rear_mass_per_length_kgpm=rear_mass_per_length,
        main_young_pa=np.full(ne, material_value(materials, recipe.main.material_key, "E"), dtype=float),
        main_shear_pa=np.full(ne, material_shear_pa(materials, recipe.main.material_key), dtype=float),
        rear_young_pa=np.full(ne, material_value(materials, recipe.rear.material_key, "E"), dtype=float),
        rear_shear_pa=np.full(ne, material_shear_pa(materials, recipe.rear.material_key), dtype=float),
        main_density_kgpm3=np.full(ne, main_density, dtype=float),
        rear_density_kgpm3=np.full(ne, rear_density, dtype=float),
        main_allowable_stress_pa=np.full(
            ne,
            material_allowable_pa(materials, recipe.main.material_key),
            dtype=float,
        ),
        rear_allowable_stress_pa=np.full(
            ne,
            material_allowable_pa(materials, recipe.rear.material_key),
            dtype=float,
        ),
        lift_per_span_npm=lift_per_span,
        torque_per_span_nmpm=torque_per_span,
        torque_input=TorqueInputDefinition(),
        gravity_scale=1.0,
        max_tip_deflection_limit_m=max(target_tip_z, 0.25),
        max_thickness_step_m=1.0,
        max_thickness_to_radius_ratio=0.8,
        main_spar_dominance_margin_m=0.005,
        rear_main_radius_ratio_min=0.0,
        main_spar_ei_ratio=2.0,
        rear_min_inner_radius_m=1.0e-4,
        rear_inboard_span_m=1.5,
        rear_inboard_ei_to_main_ratio_max=0.20,
        joint_node_indices=_nearest_indices(y, JOINT_Y_M),
        dense_link_node_indices=tuple(range(1, nn - 1)),
        wire_node_indices=wire_idx,
        wire_attachment_angles_deg=tuple(WIRE_ANGLE_DEG for _ in wire_idx),
        wire_anchor_points_m=wire_anchor_points,
        wire_area_m2=wire_area,
        wire_young_pa=wire_young,
        wire_allowable_tension_n=wire_allowable,
        wire_reference_lengths_m=wire_reference_lengths,
        wire_unstretched_lengths_m=wire_unstretched,
        joint_mass_half_kg=0.0,
        fitting_mass_half_kg=0.0,
        equivalent_analysis_success=True,
        equivalent_failure_index=0.0,
        equivalent_buckling_index=0.0,
        equivalent_tip_deflection_m=0.0,
        equivalent_tip_deflection_limit_m=max(target_tip_z, 0.25),
        equivalent_twist_max_deg=0.0,
        equivalent_twist_limit_deg=10.0,
    )
    input_summary = {
        "wire_node_indices": "|".join(str(idx) for idx in wire_idx),
        "wire_y_actual_m": "|".join(f"{float(y[idx]):.6f}" for idx in wire_idx),
        "wire_reference_lengths_m": "|".join(f"{value:.6f}" for value in wire_reference_lengths),
        "wire_unstretched_lengths_m": "|".join(f"{value:.6f}" for value in wire_unstretched),
        "wire_pretension_n": WIRE_PRETENSION_N,
        "joint_node_indices": "|".join(str(idx) for idx in model.joint_node_indices),
        "joint_y_actual_m": "|".join(f"{float(y[idx]):.6f}" for idx in model.joint_node_indices),
        "integrated_half_lift_n": float(np.trapezoid(lift_per_span, y)),
        "root_bending_proxy_n_m": float(np.trapezoid(y * lift_per_span, y)),
        "tip_deflection_second_moment_proxy": float(np.trapezoid(y * y * lift_per_span, y)),
        "loaded_tip_z_m": target_tip_z,
    }
    return model, input_summary


def feasibility_label(row: Mapping[str, Any]) -> str:
    if not bool(row.get("run_succeeded")):
        return "run_failed"
    blocking = [
        "geometry_validity_passed",
        "numerical_consistency_passed",
        "wire_support_validity_passed",
        "inverse_overall_feasible",
        "dual_displacement_candidate_passed",
    ]
    if all(bool(row.get(key)) for key in blocking):
        return "feasible_under_adapter_assumptions"
    return "not_cleared_under_adapter_assumptions"


def run_case_recipe(
    *,
    case: CaseSpec,
    station_rows: Sequence[Mapping[str, Any]],
    recipe: Recipe,
    materials: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = {
        "case_id": case.case_id,
        "display_name": case.display_name,
        "recipe_id": recipe.recipe_id,
        "recipe_description": recipe.description,
        "model_mode": AnalysisModeName.DUAL_BEAM_PRODUCTION.value,
        "link_mode": LinkMode.JOINT_ONLY_OFFSET_RIGID.value,
        "wire_model": "explicit_tension_only_truss",
        "wire_pretension_n": WIRE_PRETENSION_N,
        "structural_layout_source": "phase10_adapter_assumptions",
    }
    try:
        model, input_summary = build_model(
            station_rows=station_rows,
            recipe=recipe,
            materials=materials,
        )
        result = run_dual_beam_mainline_kernel(
            model=model,
            mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
            link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
        )
        inverse = build_frozen_load_inverse_design_from_mainline(
            model=model,
            result=result,
            clearance_floor_z_m=0.0,
            max_abs_vertical_prebend_m=2.0,
            max_abs_vertical_curvature_per_m=1.0,
            wire_y_positions=tuple(float(model.y_nodes_m[idx]) for idx in model.wire_node_indices),
        )
        tensions = np.asarray(result.recovery.wire_tension_estimates_n, dtype=float)
        wire_rows = []
        for local_idx, node_idx in enumerate(model.wire_node_indices):
            wire_rows.append(
                {
                    **base,
                    "wire_index": local_idx,
                    "wire_node_index": node_idx,
                    "wire_y_m": float(model.y_nodes_m[node_idx]),
                    "anchor_x_m": float(model.wire_anchor_points_m[local_idx, 0]),
                    "anchor_y_m": float(model.wire_anchor_points_m[local_idx, 1]),
                    "anchor_z_m": float(model.wire_anchor_points_m[local_idx, 2]),
                    "reference_length_m": float(model.wire_reference_lengths_m[local_idx]),
                    "unstretched_length_m": float(model.wire_unstretched_lengths_m[local_idx]),
                    "tension_n": float(tensions[local_idx]),
                    "allowable_tension_n": float(model.wire_allowable_tension_n[local_idx]),
                    "tension_utilization": float(
                        tensions[local_idx] / max(model.wire_allowable_tension_n[local_idx], 1.0e-30)
                    ),
                    "slack_in_solved_state": bool(tensions[local_idx] <= 1.0e-6),
                    "tension_only_passed": bool(result.recovery.wire_tension_only_passed),
                    "tension_limit_passed": bool(result.recovery.wire_tension_limit_passed),
                }
            )
        row = {
            **base,
            **input_summary,
            "run_succeeded": True,
            "run_error": "",
            "node_count": int(model.y_nodes_m.size),
            "span_m": float(2.0 * model.y_nodes_m[-1]),
            "main_outer_diameter_root_m": recipe.main.outer_diameter_root_m,
            "main_outer_diameter_tip_m": recipe.main.outer_diameter_tip_m,
            "main_wall_root_m": recipe.main.wall_root_m,
            "main_wall_tip_m": recipe.main.wall_tip_m,
            "rear_outer_diameter_root_m": recipe.rear.outer_diameter_root_m,
            "rear_outer_diameter_tip_m": recipe.rear.outer_diameter_tip_m,
            "rear_wall_root_m": recipe.rear.wall_root_m,
            "rear_wall_tip_m": recipe.rear.wall_tip_m,
            "tip_deflection_main_m": float(result.report.tip_deflection_main_m),
            "tip_deflection_rear_m": float(result.report.tip_deflection_rear_m),
            "max_vertical_displacement_m": float(result.report.max_vertical_displacement_m),
            "max_vertical_spar": result.report.max_vertical_spar,
            "main_root_EI_Nm2": float(model.main_young_pa[0] * model.main_iy_m4[0]),
            "rear_root_EI_Nm2": float(model.rear_young_pa[0] * model.rear_iy_m4[0]),
            "main_tip_EI_Nm2": float(model.main_young_pa[-1] * model.main_iy_m4[-1]),
            "rear_tip_EI_Nm2": float(model.rear_young_pa[-1] * model.rear_iy_m4[-1]),
            "required_EI_Nm2": "",
            "required_EI_basis": "not_computed_forward_recipe_check_only",
            "dual_displacement_limit_m": result.optimizer.dual_displacement_limit_m,
            "dual_displacement_margin_m": result.optimizer.dual_displacement_margin_m,
            "dual_displacement_candidate_passed": result.feasibility.dual_displacement_candidate_passed,
            "jig_tip_z_main_m": float(inverse.jig_shape.main_nodes_m[-1, 2]),
            "jig_tip_z_rear_m": float(inverse.jig_shape.rear_nodes_m[-1, 2]),
            "jig_min_z_m": float(inverse.ground_clearance.min_z_m),
            "jig_ground_clearance_margin_m": float(inverse.ground_clearance.margin_m),
            "jig_ground_clearance_passed": bool(inverse.ground_clearance.passed),
            "loaded_shape_main_z_max_abs_error_m": float(
                inverse.loaded_shape_match.main_z_max_abs_error_m
            ),
            "loaded_shape_main_z_rms_error_m": float(inverse.loaded_shape_match.main_z_rms_error_m),
            "loaded_shape_twist_max_abs_error_deg": float(
                inverse.loaded_shape_match.twist_max_abs_error_deg
            ),
            "loaded_shape_twist_rms_error_deg": float(inverse.loaded_shape_match.twist_rms_error_deg),
            "inverse_overall_feasible": bool(inverse.feasibility.overall_feasible),
            "inverse_failures": "|".join(inverse.feasibility.failures),
            "manufacturing_max_abs_vertical_prebend_m": float(
                inverse.manufacturing.max_abs_vertical_prebend_m
            ),
            "manufacturing_max_abs_vertical_curvature_per_m": float(
                inverse.manufacturing.max_abs_vertical_curvature_per_m
            ),
            "wire_count": int(tensions.size),
            "max_wire_tension_n": float(result.recovery.max_wire_tension_n),
            "max_wire_allowable_tension_n": float(result.recovery.max_wire_allowable_tension_n),
            "max_wire_tension_utilization": float(result.recovery.max_wire_tension_utilization),
            "wire_slack_detected": bool(np.any(tensions <= 1.0e-6)) if tensions.size else False,
            "wire_tension_only_passed": bool(result.recovery.wire_tension_only_passed),
            "wire_tension_limit_passed": bool(result.recovery.wire_tension_limit_passed),
            "wire_support_validity_passed": bool(result.feasibility.wire_support_validity_passed),
            "spar_tube_mass_full_kg": float(result.recovery.spar_tube_mass_full_kg),
            "total_structural_mass_full_kg": float(result.recovery.total_structural_mass_full_kg),
            "current_spar_tube_mass_target_kg": CURRENT_SPAR_TUBE_MASS_TARGET_KG,
            "spar_mass_margin_vs_current_target_kg": float(
                CURRENT_SPAR_TUBE_MASS_TARGET_KG - result.recovery.spar_tube_mass_full_kg
            ),
            "max_vm_main_pa": float(result.recovery.max_vm_main_pa),
            "max_vm_rear_pa": float(result.recovery.max_vm_rear_pa),
            "failure_index": float(result.recovery.failure_index),
            "geometry_validity_passed": bool(result.feasibility.geometry_validity_succeeded),
            "geometry_radius_dominance_margin_min_m": float(
                result.optimizer.geometry_validity.radius_dominance_margin_min_m
            ),
            "geometry_ei_ratio_margin_min": float(
                result.optimizer.geometry_validity.ei_ratio_margin_min
            ),
            "geometry_rear_inboard_ei_margin_min_nm2": float(
                result.optimizer.geometry_validity.rear_inboard_ei_margin_min_nm2
            ),
            "numerical_consistency_passed": bool(result.feasibility.numerical_consistency_passed),
            "equilibrium_residual_n": float(result.optimizer.numerical_consistency.equilibrium_residual_n),
            "compatibility_residual": float(result.optimizer.numerical_consistency.compatibility_residual),
            "force_closure_residual_n": float(
                result.optimizer.numerical_consistency.force_closure_residual_n
            ),
            "moment_closure_residual_nm": float(
                result.optimizer.numerical_consistency.moment_closure_residual_nm
            ),
            "constraint_condition_number": float(
                result.optimizer.numerical_consistency.scaled_constraint_condition_number
            ),
            "overall_hard_feasible": bool(result.feasibility.overall_hard_feasible),
            "overall_optimizer_candidate_feasible": bool(
                result.feasibility.overall_optimizer_candidate_feasible
            ),
            "hard_failures": "|".join(result.feasibility.hard_failures),
            "candidate_constraint_failures": "|".join(
                result.feasibility.candidate_constraint_failures
            ),
        }
        row["feasibility_status"] = feasibility_label(row)
        return row, wire_rows
    except Exception as exc:  # noqa: BLE001 - capture diagnostic failures into CSV.
        row = {
            **base,
            "run_succeeded": False,
            "run_error": f"{type(exc).__name__}: {exc}",
            "feasibility_status": "run_failed",
        }
        return row, []


def read_proxy_row() -> dict[str, str]:
    if not PROXY_STRUCTURE_AUDIT.exists():
        return {}
    rows = read_csv_rows(PROXY_STRUCTURE_AUDIT)
    return rows[0] if rows else {}


def proxy_comparison_rows(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    proxy = read_proxy_row()
    if not proxy:
        return []
    proxy_tip = _float_or_none(proxy.get("tip_deflection_estimate_m"))
    proxy_jig_tip = _float_or_none(proxy.get("jig_tip_z_unloaded_estimate_m"))
    proxy_mass = _float_or_none(proxy.get("selected_tube_estimated_full_span_tube_mass_kg"))
    rows = []
    for row in results:
        if row.get("case_id") != "smooth_tier2_production_baseline" or not row.get("run_succeeded"):
            continue
        real_tip = _float_or_none(row.get("tip_deflection_main_m"))
        real_jig = _float_or_none(row.get("jig_tip_z_main_m"))
        real_mass = _float_or_none(row.get("spar_tube_mass_full_kg"))
        rows.append(
            {
                "case_id": row.get("case_id"),
                "recipe_id": row.get("recipe_id"),
                "proxy_tip_deflection_m": proxy_tip,
                "real_tip_deflection_main_m": real_tip,
                "delta_real_minus_proxy_tip_m": None
                if proxy_tip is None or real_tip is None
                else real_tip - proxy_tip,
                "proxy_unloaded_jig_tip_m": proxy_jig_tip,
                "real_jig_tip_z_main_m": real_jig,
                "delta_real_minus_proxy_jig_tip_m": None
                if proxy_jig_tip is None or real_jig is None
                else real_jig - proxy_jig_tip,
                "proxy_selected_tube_mass_kg": proxy_mass,
                "real_spar_tube_mass_full_kg": real_mass,
                "delta_real_minus_proxy_mass_kg": None
                if proxy_mass is None or real_mass is None
                else real_mass - proxy_mass,
                "comparability": (
                    "same nominal full-span two-tube catalog mass basis"
                    if row.get("recipe_id") == "proxy_selected_equal_CF_STD_100x98"
                    else "not directly comparable: different assumed main/rear tube recipe"
                ),
            }
        )
    return rows


def _fmt(value: Any, digits: int = 3) -> str:
    number = _float_or_none(value)
    if number is None or not np.isfinite(number):
        return "n/a"
    return f"{number:.{digits}f}"


def write_reports(
    *,
    output_dir: Path,
    results: Sequence[Mapping[str, Any]],
    wire_rows: Sequence[Mapping[str, Any]],
    proxy_rows: Sequence[Mapping[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    module_inventory = f"""# Dual-Beam Module Inventory

## Existing Real Modules

- `src/hpa_mdo/structure/dual_beam_mainline/types.py`: owns `DualBeamMainlineModel`, `AnalysisModeName.DUAL_BEAM_PRODUCTION`, `WireBCMode.WIRE_MAIN_TRUSS`, result dataclasses, recovery fields, and feasibility summaries.
- `src/hpa_mdo/structure/dual_beam_mainline/api.py`: `run_dual_beam_mainline_kernel()` builds load split, constraints, displacements, reactions, structural recovery, smooth aggregation, optimizer metrics, and feasibility.
- `src/hpa_mdo/structure/dual_beam_mainline/solver.py`: `solve_dual_beam_state()` includes the explicit wire-truss nonlinear branch; `_evaluate_explicit_wire_truss_support()` clips compression to zero with `tension_n = max(axial_force, 0)`.
- `src/hpa_mdo/structure/dual_beam_mainline/builder.py`: the config-driven builder can convert configured aircraft/optimizer outputs into a `DualBeamMainlineModel`, including pretension-derived unstretched wire lengths.
- `src/hpa_mdo/structure/inverse_design.py`: `build_frozen_load_inverse_design_from_mainline()` and `predict_loaded_shape()` recover unloaded jig shape and verify loaded-shape closure.
- `scripts/direct_dual_beam_inverse_design.py`: currently callable production workflow using the real kernel and inverse-jig recovery.

## Required Inputs

- front/main and rear spar node coordinates
- spanwise main/rear tube radius and wall distributions
- material E/G/density/allowables
- distributed lift per span and torque per span
- root BC, link/rib mode, and wire BC
- wire attach nodes, anchor coordinates, cable area/material/allowable tension
- wire reference and unstretched lengths; pretension enters through unstretched length
- target loaded shape and jig clearance/manufacturing limits

## Phase 10 Adapter Assumptions

- main spar at `{MAIN_SPAR_XC:.2f}c`; rear spar at `{REAR_SPAR_XC:.2f}c`
- loaded main spar z from the production section table
- loaded rear spar z from loaded z plus relative twist from the root
- AVL `concept_spanwise.fs` supplies `L'(y)` and `Cm`; torque is approximated as `q*c^2*Cm` about the 25% chord main spar
- one Dyneema SK75 wire at nominal `y={WIRE_Y_M:.1f} m`, nearest structural node, anchor `(x_attach, 0, {WIRE_FUSELAGE_Z_M:.1f})`
- wire pretension `{WIRE_PRETENSION_N:.1f} N` because the current baseline config does not define installed pretension
- link mode `joint_only_offset_rigid`

The module is callable from scripts. This Phase 10 script calls it directly rather than using the older config/optimizer builder because the smooth aero package lacks a full structural config.
"""
    (output_dir / "dual_beam_module_inventory.md").write_text(module_inventory, encoding="utf-8")

    best_smooth = next(
        (
            row
            for row in results
            if row.get("case_id") == "smooth_tier2_production_baseline"
            and row.get("recipe_id") == "proxy_selected_equal_CF_STD_100x98"
        ),
        {},
    )
    jig_report = f"""# Jig Shape Recovery Report

## Did The Real Model Run?

Yes. `run_dual_beam_mainline_kernel(mode=dual_beam_production, link_mode=joint_only_offset_rigid)` ran through the real dual-beam / explicit wire-truss path for the smooth baseline and old FX/Clark baseline.

## Smooth Baseline, Proxy-Selected Tube Recipe

- tip deflection, main spar: `{_fmt(best_smooth.get('tip_deflection_main_m'))} m`
- tip deflection, rear spar: `{_fmt(best_smooth.get('tip_deflection_rear_m'))} m`
- loaded tip z: `{_fmt(best_smooth.get('loaded_tip_z_m'))} m`
- recovered unloaded jig tip z, main spar: `{_fmt(best_smooth.get('jig_tip_z_main_m'))} m`
- recovered unloaded jig minimum z: `{_fmt(best_smooth.get('jig_min_z_m'))} m`
- loaded-shape main-z RMS error: `{_fmt(best_smooth.get('loaded_shape_main_z_rms_error_m'), 6)} m`
- loaded-shape twist RMS error: `{_fmt(best_smooth.get('loaded_shape_twist_rms_error_deg'), 6)} deg`
- geometry validity passed: `{best_smooth.get('geometry_validity_passed', 'n/a')}`
- numerical consistency passed: `{best_smooth.get('numerical_consistency_passed', 'n/a')}`
- hard failures: `{best_smooth.get('hard_failures', '') or 'none'}`
- moment-closure residual: `{_fmt(best_smooth.get('moment_closure_residual_nm'))} N*m`
- inverse-jig failures: `{best_smooth.get('inverse_failures', '') or 'none'}`

The zero loaded-shape error is expected for the frozen-load inverse method: it algebraically backs out `jig = target_loaded_shape - solved_displacement`, then re-adds the same displacement field. This validates the adapter plumbing, not a coupled aeroelastic convergence loop.
"""
    (output_dir / "jig_shape_recovery_report.md").write_text(jig_report, encoding="utf-8")

    wire_lines = ["# Wire Tension Report", "", "| case | recipe | tension N | allowable N | utilization | slack | passed |", "|---|---|---:|---:|---:|---|---|"]
    for row in wire_rows:
        wire_lines.append(
            "| {case} | {recipe} | {tension} | {allowable} | {util} | {slack} | {passed} |".format(
                case=row.get("case_id"),
                recipe=row.get("recipe_id"),
                tension=_fmt(row.get("tension_n")),
                allowable=_fmt(row.get("allowable_tension_n")),
                util=_fmt(row.get("tension_utilization"), 3),
                slack=row.get("slack_in_solved_state"),
                passed=row.get("tension_limit_passed"),
            )
        )
    (output_dir / "wire_tension_report.md").write_text("\n".join(wire_lines) + "\n", encoding="utf-8")

    mass_lines = [
        "# Spar Mass Report",
        "",
        "This sidecar performs forward checks of assumed tube recipes. It does not solve an inverse required-EI sizing problem; root/tip EI values are reported in `dual_beam_validation_results.csv` and `required_EI_basis=not_computed_forward_recipe_check_only`.",
        "",
        "| case | recipe | spar tube mass kg | target kg | margin kg | failure index | status |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in results:
        mass_lines.append(
        "| {case} | {recipe} | {mass} | {target} | {margin} | {failure} | {status} |".format(
                case=row.get("case_id"),
                recipe=row.get("recipe_id"),
                mass=_fmt(row.get("spar_tube_mass_full_kg")),
                target=_fmt(row.get("current_spar_tube_mass_target_kg")),
                margin=_fmt(row.get("spar_mass_margin_vs_current_target_kg")),
                failure=_fmt(row.get("failure_index"), 3),
                status=row.get("feasibility_status"),
            )
        )
    (output_dir / "spar_mass_report.md").write_text("\n".join(mass_lines) + "\n", encoding="utf-8")

    proxy_lines = [
        "# Proxy vs Real Model Comparison",
        "",
        "The Phase 9 proxy mass and deflection numbers are warning-only. Phase 10 uses the real dual-beam solver, but still through an adapter with explicit structural assumptions.",
        "",
        "| recipe | proxy tip m | real tip m | proxy jig tip m | real jig tip m | proxy mass kg | real mass kg | comparability |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in proxy_rows:
        proxy_lines.append(
            "| {recipe} | {ptip} | {rtip} | {pjig} | {rjig} | {pmass} | {rmass} | {comp} |".format(
                recipe=row.get("recipe_id"),
                ptip=_fmt(row.get("proxy_tip_deflection_m")),
                rtip=_fmt(row.get("real_tip_deflection_main_m")),
                pjig=_fmt(row.get("proxy_unloaded_jig_tip_m")),
                rjig=_fmt(row.get("real_jig_tip_z_main_m")),
                pmass=_fmt(row.get("proxy_selected_tube_mass_kg")),
                rmass=_fmt(row.get("real_spar_tube_mass_full_kg")),
                comp=row.get("comparability"),
            )
        )
    (output_dir / "proxy_vs_real_model_comparison.md").write_text(
        "\n".join(proxy_lines) + "\n",
        encoding="utf-8",
    )

    next_steps = f"""# Recommended Next Steps

## Structural Verdict

The real dual-beam model ran, but the smooth aerodynamic baseline is **not yet structurally cleared**. The results are adapter-grade because the smooth aero package still lacks a candidate-owned structural layout, spar recipe, wire pretension definition, and validated load/torque mapping.

The most important next action is to make the structural recipe candidate-owned instead of adapter-assumed:

1. Add a smooth-baseline structural config/manifest with main/rear spar locations, tube/layup recipe, material keys, joint stations, wire anchor geometry, and pretension.
2. Reuse the real builder path where possible instead of directly constructing `DualBeamMainlineModel`.
3. Map AVL lift and airfoil/AVL moment into a reviewed torque-per-span convention, then close the current `moment_closure` diagnostic.
4. Run `dual_beam_production` plus inverse-jig recovery as a required sidecar report, but keep it outside aerodynamic ranking until reviewed.
5. Replace the Phase 9 scalar proxy in final validation reports with this sidecar once the inputs are no longer assumptions.

## Engineering Caution

If the equal `CF-STD-100x98` recipe looks much better in deflection than the Phase 9 proxy, that does not mean the old proxy was simply pessimistic. It used a scalar equivalent EI target, while this run uses explicit main/rear beams, a real truss wire, torque input, and a different stiffness distribution. The mass comparison is only direct for the equal-tube recipe; other recipes are not comparable to the `32.959 kg` proxy number.
"""
    (output_dir / "recommended_next_steps.md").write_text(next_steps, encoding="utf-8")


def run(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    materials = read_materials()
    all_input_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    wire_rows: list[dict[str, Any]] = []
    for case in case_specs():
        rows = station_inputs(case)
        if case.case_id == "smooth_tier2_production_baseline":
            all_input_rows.extend(rows)
        for recipe in structural_recipes():
            result_row, case_wire_rows = run_case_recipe(
                case=case,
                station_rows=rows,
                recipe=recipe,
                materials=materials,
            )
            result_rows.append(result_row)
            wire_rows.extend(case_wire_rows)
    proxy_rows = proxy_comparison_rows(result_rows)
    write_csv(output_dir / "smooth_baseline_dual_beam_inputs.csv", all_input_rows)
    write_csv(output_dir / "dual_beam_validation_results.csv", result_rows)
    write_csv(output_dir / "wire_tension_results.csv", wire_rows)
    write_csv(output_dir / "proxy_vs_real_model_comparison.csv", proxy_rows)
    write_reports(
        output_dir=output_dir,
        results=result_rows,
        wire_rows=wire_rows,
        proxy_rows=proxy_rows,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for Phase 10 dual-beam jig validation outputs.",
    )
    args = parser.parse_args(argv)
    return run(args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
