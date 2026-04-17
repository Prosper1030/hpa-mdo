"""Reaction recovery, element recovery, and raw report metrics."""

from __future__ import annotations

import numpy as np

from hpa_mdo.structure.fem.elements import _cs_norm, _rotation_matrix

from hpa_mdo.structure.dual_beam_mainline.types import (
    ConstraintAssemblyResult,
    DualBeamMainlineModel,
    ReactionRecoveryResult,
    RecoveryResult,
    ReportMetrics,
)


def _elementwise_property_array(values: np.ndarray | float, ne: int, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 0:
        return np.full(ne, float(arr), dtype=float)
    if arr.shape != (ne,):
        raise ValueError(f"{name} must be scalar or have shape ({ne},), got {arr.shape}.")
    return arr


def _beam_von_mises(
    *,
    nodes_m: np.ndarray,
    disp_m: np.ndarray,
    radius_elem_m: np.ndarray,
    young_pa: float,
    shear_pa: float,
) -> np.ndarray:
    """Simple beam-fiber von Mises estimate per element."""

    ne = nodes_m.shape[0] - 1
    vm = np.zeros(ne, dtype=float)
    young_elem_pa = _elementwise_property_array(young_pa, ne, "young_pa")
    shear_elem_pa = _elementwise_property_array(shear_pa, ne, "shear_pa")
    for element_index in range(ne):
        length_m = _cs_norm(nodes_m[element_index + 1] - nodes_m[element_index])
        if np.real(length_m) < 1.0e-12:
            continue
        du = disp_m[element_index + 1] - disp_m[element_index]
        rotation = _rotation_matrix(nodes_m[element_index], nodes_m[element_index + 1])
        dtheta_local = rotation @ du[3:6]
        curvature = np.sqrt(
            (dtheta_local[1] / length_m) ** 2 + (dtheta_local[2] / length_m) ** 2
        )
        torsion = dtheta_local[0] / length_m
        sigma_bending = young_elem_pa[element_index] * radius_elem_m[element_index] * curvature
        tau_torsion = shear_elem_pa[element_index] * radius_elem_m[element_index] * torsion
        vm[element_index] = float(np.sqrt(sigma_bending**2 + 3.0 * tau_torsion**2))
    return vm


def recover_reactions(
    *,
    constraints: ConstraintAssemblyResult,
    multipliers: np.ndarray,
    nn: int,
) -> ReactionRecoveryResult:
    """Recover root, wire, and link resultants from the multiplier solution."""

    def _pad_rows(rows: list[np.ndarray]) -> np.ndarray:
        if not rows:
            return np.zeros((0, 0), dtype=float)
        width = max(int(row.size) for row in rows)
        out = np.zeros((len(rows), width), dtype=float)
        for idx, row in enumerate(rows):
            out[idx, : row.size] = np.asarray(row, dtype=float)
        return out

    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        total_constraint_reaction_vector_n = -(constraints.matrix.T @ multipliers)

    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        root_main_vector = -(
            constraints.matrix[constraints.root_main_slice].T @ multipliers[constraints.root_main_slice]
        )
        root_rear_vector = -(
            constraints.matrix[constraints.root_rear_slice].T @ multipliers[constraints.root_rear_slice]
        )
        wire_vector = -(
            constraints.matrix[constraints.wire_slice].T @ multipliers[constraints.wire_slice]
            if constraints.wire_slice.stop > constraints.wire_slice.start
            else np.zeros_like(total_constraint_reaction_vector_n)
        )

    root_main_reaction_n = root_main_vector[:6].copy()
    root_rear_start = nn * 6
    root_rear_reaction_n = root_rear_vector[root_rear_start : root_rear_start + 6].copy()

    wire_reactions_n = np.array(
        [wire_vector[node_index * 6 + 2] for node_index in constraints.wire_node_indices],
        dtype=float,
    )

    link_resultants = []
    link_reaction_on_main = []
    link_reaction_on_rear = []
    for row_slice, node_index in zip(constraints.link_row_slices, constraints.link_node_indices, strict=True):
        lambda_i = -multipliers[row_slice]
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            reaction_i = -(constraints.matrix[row_slice].T @ multipliers[row_slice])
        link_resultants.append(np.asarray(lambda_i, dtype=float))
        link_reaction_on_main.append(reaction_i[node_index * 6 : node_index * 6 + 6])
        rear_base = (nn + node_index) * 6
        link_reaction_on_rear.append(reaction_i[rear_base : rear_base + 6])

    return ReactionRecoveryResult(
        multipliers=np.asarray(multipliers, dtype=float),
        total_constraint_reaction_vector_n=np.asarray(total_constraint_reaction_vector_n, dtype=float),
        root_main_reaction_n=np.asarray(root_main_reaction_n, dtype=float),
        root_rear_reaction_n=np.asarray(root_rear_reaction_n, dtype=float),
        wire_reactions_n=wire_reactions_n,
        wire_node_indices=constraints.wire_node_indices,
        link_resultants_n=_pad_rows(link_resultants),
        link_reaction_on_main_n=(
            np.vstack(link_reaction_on_main) if link_reaction_on_main else np.zeros((0, 6), dtype=float)
        ),
        link_reaction_on_rear_n=(
            np.vstack(link_reaction_on_rear) if link_reaction_on_rear else np.zeros((0, 6), dtype=float)
        ),
        link_node_indices=constraints.link_node_indices,
    )


def recover_structural_response(
    *,
    model: DualBeamMainlineModel,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
) -> RecoveryResult:
    """Recover provisional stress metrics and report mass breakdowns."""

    vm_main_pa = _beam_von_mises(
        nodes_m=model.nodes_main_m,
        disp_m=disp_main_m,
        radius_elem_m=model.main_radius_elem_m,
        young_pa=model.main_young_pa,
        shear_pa=model.main_shear_pa,
    )
    vm_rear_pa = _beam_von_mises(
        nodes_m=model.nodes_rear_m,
        disp_m=disp_rear_m,
        radius_elem_m=model.rear_radius_elem_m,
        young_pa=model.rear_young_pa,
        shear_pa=model.rear_shear_pa,
    )
    max_vm_main_pa = float(np.max(vm_main_pa)) if vm_main_pa.size else 0.0
    max_vm_rear_pa = float(np.max(vm_rear_pa)) if vm_rear_pa.size else 0.0
    main_allowable_pa = _elementwise_property_array(
        model.main_allowable_stress_pa,
        vm_main_pa.size,
        "main_allowable_stress_pa",
    )
    rear_allowable_pa = _elementwise_property_array(
        model.rear_allowable_stress_pa,
        vm_rear_pa.size,
        "rear_allowable_stress_pa",
    )
    failure_index = max(
        float(np.max(vm_main_pa / np.maximum(main_allowable_pa, 1.0e-30))) if vm_main_pa.size else 0.0,
        float(np.max(vm_rear_pa / np.maximum(rear_allowable_pa, 1.0e-30))) if vm_rear_pa.size else 0.0,
    ) - 1.0

    spar_tube_mass_half_kg = float(
        np.sum(
            (model.main_mass_per_length_kgpm + model.rear_mass_per_length_kgpm)
            * model.element_lengths_m
        )
    )
    joint_mass_half_kg = float(model.joint_mass_half_kg)
    fitting_mass_half_kg = float(model.fitting_mass_half_kg)
    total_structural_mass_half_kg = spar_tube_mass_half_kg + joint_mass_half_kg + fitting_mass_half_kg

    return RecoveryResult(
        vm_main_pa=vm_main_pa,
        vm_rear_pa=vm_rear_pa,
        max_vm_main_pa=max_vm_main_pa,
        max_vm_rear_pa=max_vm_rear_pa,
        failure_index=float(failure_index),
        spar_tube_mass_half_kg=spar_tube_mass_half_kg,
        spar_tube_mass_full_kg=2.0 * spar_tube_mass_half_kg,
        joint_mass_half_kg=joint_mass_half_kg,
        joint_mass_full_kg=2.0 * joint_mass_half_kg,
        fitting_mass_half_kg=fitting_mass_half_kg,
        fitting_mass_full_kg=2.0 * fitting_mass_half_kg,
        total_structural_mass_full_kg=2.0 * total_structural_mass_half_kg,
    )


def build_report_metrics(
    *,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
    reactions: ReactionRecoveryResult,
) -> ReportMetrics:
    """Build the raw engineering report metrics for one run."""

    tip_deflection_main_m = float(disp_main_m[-1, 2])
    tip_deflection_rear_m = float(disp_rear_m[-1, 2])
    rear_main_tip_ratio = abs(tip_deflection_rear_m) / max(abs(tip_deflection_main_m), 1.0e-12)

    main_abs = np.abs(disp_main_m[:, 2])
    rear_abs = np.abs(disp_rear_m[:, 2])
    main_max_index = int(np.argmax(main_abs))
    rear_max_index = int(np.argmax(rear_abs))
    main_max = float(main_abs[main_max_index])
    rear_max = float(rear_abs[rear_max_index])
    if rear_max >= main_max:
        max_vertical_displacement_m = rear_max
        max_vertical_spar = "rear"
        max_vertical_node = rear_max_index + 1
    else:
        max_vertical_displacement_m = main_max
        max_vertical_spar = "main"
        max_vertical_node = main_max_index + 1

    if reactions.link_resultants_n.size:
        link_norms = np.linalg.norm(reactions.link_resultants_n, axis=1)
        hotspot_index = int(np.argmax(link_norms))
        link_force_max_n = float(link_norms[hotspot_index])
        link_force_hotspot_node = int(reactions.link_node_indices[hotspot_index]) + 1
    else:
        link_force_max_n = 0.0
        link_force_hotspot_node = None

    return ReportMetrics(
        tip_deflection_main_m=tip_deflection_main_m,
        tip_deflection_rear_m=tip_deflection_rear_m,
        rear_main_tip_ratio=float(rear_main_tip_ratio),
        max_vertical_displacement_m=max_vertical_displacement_m,
        max_vertical_spar=max_vertical_spar,
        max_vertical_node=max_vertical_node,
        root_reaction_main_n=np.asarray(reactions.root_main_reaction_n, dtype=float),
        root_reaction_rear_n=np.asarray(reactions.root_rear_reaction_n, dtype=float),
        wire_reaction_total_n=float(np.sum(reactions.wire_reactions_n)),
        link_force_max_n=link_force_max_n,
        link_force_hotspot_node=link_force_hotspot_node,
    )
