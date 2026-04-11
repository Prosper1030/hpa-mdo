"""Geometry and section-property builders for the dual-beam mainline kernel."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hpa_mdo.core.config import HPAConfig
from hpa_mdo.structure.spar_model import compute_outer_radius, tube_Ixx, tube_J, tube_area

from hpa_mdo.structure.dual_beam_mainline.types import (
    DualBeamMainlineModel,
    TorqueInputDefinition,
)

if TYPE_CHECKING:
    from hpa_mdo.structure.optimizer import OptimizationResult


def _segment_values_to_stations(
    seg_values: np.ndarray,
    seg_lengths: list[float],
    stations_m: np.ndarray,
    *,
    scale: float,
) -> np.ndarray:
    """Map piecewise-constant segment values to arbitrary spanwise stations."""

    seg_values = np.asarray(seg_values, dtype=float).reshape(-1)
    if seg_values.size != len(seg_lengths):
        raise ValueError(
            f"Expected {len(seg_lengths)} segment values, got {seg_values.size}."
        )

    boundaries = np.concatenate(([0.0], np.cumsum(np.asarray(seg_lengths, dtype=float))))
    out = np.empty(stations_m.size, dtype=float)
    values_si = seg_values * scale
    for i, station in enumerate(stations_m):
        idx = int(np.searchsorted(boundaries[1:], station, side="right"))
        out[i] = values_si[min(idx, values_si.size - 1)]
    return out


def _dihedral_z(y_nodes_m: np.ndarray, dihedral_deg: np.ndarray) -> np.ndarray:
    """Integrate dihedral to nodal Z offset using the existing export convention."""

    z_nodes = np.zeros_like(y_nodes_m, dtype=float)
    for i in range(1, y_nodes_m.size):
        dy = y_nodes_m[i] - y_nodes_m[i - 1]
        avg_dihedral = 0.5 * (dihedral_deg[i - 1] + dihedral_deg[i])
        z_nodes[i] = z_nodes[i - 1] + dy * np.tan(np.radians(avg_dihedral))
    return z_nodes


def _node_spacings(y_nodes_m: np.ndarray) -> np.ndarray:
    """Return tributary span length for each node."""

    dy = np.diff(y_nodes_m)
    out = np.zeros_like(y_nodes_m, dtype=float)
    out[0] = 0.5 * dy[0]
    out[-1] = 0.5 * dy[-1]
    for i in range(1, y_nodes_m.size - 1):
        out[i] = 0.5 * (dy[i - 1] + dy[i])
    return out


def _nearest_node_indices(y_nodes_m: np.ndarray, locations_m: list[float]) -> tuple[int, ...]:
    """Map spanwise locations to nearest structural node indices."""

    return tuple(int(np.argmin(np.abs(y_nodes_m - yy))) for yy in locations_m)


def build_dual_beam_mainline_model(
    *,
    cfg: HPAConfig,
    aircraft,
    opt_result: OptimizationResult,
    export_loads: dict,
    materials_db,
    torque_input: TorqueInputDefinition | None = None,
) -> DualBeamMainlineModel:
    """Build the explicit dual-beam analysis model from config + optimized design."""

    if not cfg.rear_spar.enabled:
        raise ValueError("dual-beam mainline analysis requires cfg.rear_spar.enabled=True.")

    wing = aircraft.wing
    y_nodes_m = np.asarray(wing.y, dtype=float)
    nn = y_nodes_m.size
    if nn < 2:
        raise ValueError("Need at least two structural nodes per spar.")

    element_lengths_m = np.diff(y_nodes_m)
    element_centres_m = 0.5 * (y_nodes_m[:-1] + y_nodes_m[1:])
    node_spacings_m = _node_spacings(y_nodes_m)

    main_seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
    rear_seg_lengths = cfg.spar_segment_lengths(cfg.rear_spar)

    main_t_elem_m = _segment_values_to_stations(
        opt_result.main_t_seg_mm, main_seg_lengths, element_centres_m, scale=1.0e-3
    )
    if opt_result.rear_t_seg_mm is None:
        rear_t_elem_m = np.full(nn - 1, cfg.rear_spar.min_wall_thickness, dtype=float)
    else:
        rear_t_elem_m = _segment_values_to_stations(
            opt_result.rear_t_seg_mm, rear_seg_lengths, element_centres_m, scale=1.0e-3
        )

    default_main_radius_nodes_m = compute_outer_radius(
        y_nodes_m,
        np.asarray(wing.chord, dtype=float),
        np.asarray(wing.airfoil_thickness, dtype=float),
        cfg.main_spar,
    )
    default_rear_radius_nodes_m = compute_outer_radius(
        y_nodes_m,
        np.asarray(wing.chord, dtype=float),
        np.asarray(wing.airfoil_thickness, dtype=float),
        cfg.rear_spar,
    )
    default_main_radius_elem_m = 0.5 * (
        default_main_radius_nodes_m[:-1] + default_main_radius_nodes_m[1:]
    )
    default_rear_radius_elem_m = 0.5 * (
        default_rear_radius_nodes_m[:-1] + default_rear_radius_nodes_m[1:]
    )

    if opt_result.main_r_seg_mm is None:
        main_radius_elem_m = default_main_radius_elem_m
    else:
        main_radius_elem_m = _segment_values_to_stations(
            opt_result.main_r_seg_mm, main_seg_lengths, element_centres_m, scale=1.0e-3
        )

    if opt_result.rear_r_seg_mm is None:
        rear_radius_elem_m = default_rear_radius_elem_m
    else:
        rear_radius_elem_m = _segment_values_to_stations(
            opt_result.rear_r_seg_mm, rear_seg_lengths, element_centres_m, scale=1.0e-3
        )

    z_dihedral_m = _dihedral_z(y_nodes_m, np.asarray(wing.dihedral_deg, dtype=float))
    nodes_main_m = np.column_stack(
        (
            wing.main_spar_xc * np.asarray(wing.chord, dtype=float),
            y_nodes_m,
            z_dihedral_m + np.asarray(wing.main_spar_z_camber, dtype=float),
        )
    )
    nodes_rear_m = np.column_stack(
        (
            wing.rear_spar_xc * np.asarray(wing.chord, dtype=float),
            y_nodes_m,
            z_dihedral_m + np.asarray(wing.rear_spar_z_camber, dtype=float),
        )
    )
    spar_offset_vectors_m = nodes_rear_m - nodes_main_m
    spar_separation_nodes_m = spar_offset_vectors_m[:, 0]

    main_area_m2 = tube_area(main_radius_elem_m, main_t_elem_m)
    rear_area_m2 = tube_area(rear_radius_elem_m, rear_t_elem_m)
    main_iy_m4 = tube_Ixx(main_radius_elem_m, main_t_elem_m)
    rear_iy_m4 = tube_Ixx(rear_radius_elem_m, rear_t_elem_m)
    main_j_m4 = tube_J(main_radius_elem_m, main_t_elem_m)
    rear_j_m4 = tube_J(rear_radius_elem_m, rear_t_elem_m)
    main_mass_per_length_kgpm = materials_db.get(cfg.main_spar.material).density * main_area_m2
    rear_mass_per_length_kgpm = materials_db.get(cfg.rear_spar.material).density * rear_area_m2

    main_joint_positions_m = HPAConfig.joint_positions(main_seg_lengths)
    rear_joint_positions_m = HPAConfig.joint_positions(rear_seg_lengths)
    joint_node_indices = _nearest_node_indices(
        y_nodes_m, sorted(set(main_joint_positions_m + rear_joint_positions_m))
    )

    wire_locations_m = [att.y for att in cfg.lift_wires.attachments] if cfg.lift_wires.enabled else []
    wire_node_indices = _nearest_node_indices(y_nodes_m, wire_locations_m)

    dense_link_node_indices = tuple(range(1, nn - 1))
    joint_mass_half_kg = (
        len(main_joint_positions_m) * cfg.main_spar.joint_mass_kg
        + len(rear_joint_positions_m) * cfg.rear_spar.joint_mass_kg
    )

    lift_per_span_npm = np.asarray(export_loads.get("lift_per_span", np.zeros(nn)), dtype=float)
    torque_per_span_nmpm = np.asarray(
        export_loads.get("torque_per_span", np.zeros(nn)), dtype=float
    )
    if lift_per_span_npm.shape != (nn,):
        raise ValueError(
            f"lift_per_span must have shape {(nn,)}, got {lift_per_span_npm.shape}."
        )
    if torque_per_span_nmpm.shape != (nn,):
        raise ValueError(
            f"torque_per_span must have shape {(nn,)}, got {torque_per_span_nmpm.shape}."
        )

    load_case = cfg.structural_load_cases()[0]
    mat_main = materials_db.get(cfg.main_spar.material)
    mat_rear = materials_db.get(cfg.rear_spar.material)
    main_allowable_stress_pa = min(
        mat_main.tensile_strength,
        mat_main.compressive_strength or mat_main.tensile_strength,
    ) / cfg.safety.material_safety_factor
    rear_allowable_stress_pa = min(
        mat_rear.tensile_strength,
        mat_rear.compressive_strength or mat_rear.tensile_strength,
    ) / cfg.safety.material_safety_factor

    return DualBeamMainlineModel(
        y_nodes_m=y_nodes_m,
        node_spacings_m=node_spacings_m,
        element_lengths_m=element_lengths_m,
        nodes_main_m=nodes_main_m,
        nodes_rear_m=nodes_rear_m,
        spar_offset_vectors_m=spar_offset_vectors_m,
        spar_separation_nodes_m=spar_separation_nodes_m,
        main_area_m2=main_area_m2,
        main_iy_m4=main_iy_m4,
        main_iz_m4=main_iy_m4.copy(),
        main_j_m4=main_j_m4,
        rear_area_m2=rear_area_m2,
        rear_iy_m4=rear_iy_m4,
        rear_iz_m4=rear_iy_m4.copy(),
        rear_j_m4=rear_j_m4,
        main_radius_elem_m=main_radius_elem_m,
        rear_radius_elem_m=rear_radius_elem_m,
        main_mass_per_length_kgpm=main_mass_per_length_kgpm,
        rear_mass_per_length_kgpm=rear_mass_per_length_kgpm,
        main_young_pa=float(mat_main.E),
        main_shear_pa=float(mat_main.G),
        rear_young_pa=float(mat_rear.E),
        rear_shear_pa=float(mat_rear.G),
        main_density_kgpm3=float(mat_main.density),
        rear_density_kgpm3=float(mat_rear.density),
        main_allowable_stress_pa=float(main_allowable_stress_pa),
        rear_allowable_stress_pa=float(rear_allowable_stress_pa),
        lift_per_span_npm=lift_per_span_npm,
        torque_per_span_nmpm=torque_per_span_nmpm,
        torque_input=torque_input or TorqueInputDefinition(),
        gravity_scale=float(load_case.gravity_scale),
        max_tip_deflection_limit_m=load_case.max_tip_deflection_m,
        joint_node_indices=joint_node_indices,
        dense_link_node_indices=dense_link_node_indices,
        wire_node_indices=wire_node_indices,
        joint_mass_half_kg=float(joint_mass_half_kg),
        fitting_mass_half_kg=0.0,
    )
