"""Stiffness assembly and exact-constraint solve for the dual-beam mainline kernel."""

from __future__ import annotations

import numpy as np

from hpa_mdo.structure.fem.elements import (
    _cs_norm,
    _rotation_matrix,
    _timoshenko_element_stiffness,
    _transform_12x12,
)

from hpa_mdo.structure.dual_beam_mainline.types import (
    ConstraintAssemblyResult,
    DualBeamMainlineModel,
    ExplicitWireSupportResult,
    WireBCMode,
)

_WIRE_ACTIVE_TOL_N = 1.0e-9
_WIRE_ACTIVE_SET_MAX_ITERS = 8


def _elementwise_property_array(values: np.ndarray | float, ne: int, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 0:
        return np.full(ne, float(arr), dtype=float)
    if arr.shape != (ne,):
        raise ValueError(f"{name} must be scalar or have shape ({ne},), got {arr.shape}.")
    return arr


def _assemble_chain_beam(
    *,
    stiffness_matrix: np.ndarray,
    nodes_m: np.ndarray,
    start_node: int,
    area_m2: np.ndarray,
    iy_m4: np.ndarray,
    iz_m4: np.ndarray,
    j_m4: np.ndarray,
    young_pa: float,
    shear_pa: float,
) -> None:
    """Assemble one 6-DOF/node Timoshenko beam chain into the global stiffness matrix."""

    ne = nodes_m.shape[0] - 1
    young_elem_pa = _elementwise_property_array(young_pa, ne, "young_pa")
    shear_elem_pa = _elementwise_property_array(shear_pa, ne, "shear_pa")
    for element_index in range(ne):
        node_i = nodes_m[element_index]
        node_j = nodes_m[element_index + 1]
        length_m = _cs_norm(node_j - node_i)
        if np.real(length_m) < 1.0e-12:
            raise ValueError(f"Degenerate beam element length at element {element_index}.")

        if min(
            np.real(area_m2[element_index]),
            np.real(iy_m4[element_index]),
            np.real(iz_m4[element_index]),
            np.real(j_m4[element_index]),
        ) <= 0.0:
            raise ValueError(f"Non-positive section property at element {element_index}.")

        k_local = _timoshenko_element_stiffness(
            length_m,
            young_elem_pa[element_index],
            shear_elem_pa[element_index],
            area_m2[element_index],
            iy_m4[element_index],
            iz_m4[element_index],
            j_m4[element_index],
        )
        rotation = _rotation_matrix(node_i, node_j)
        transform = _transform_12x12(rotation)
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            k_element = transform.T @ k_local @ transform

        dof_start = (start_node + element_index) * 6
        dof_next = (start_node + element_index + 1) * 6
        dofs = np.concatenate(
            (np.arange(dof_start, dof_start + 6), np.arange(dof_next, dof_next + 6))
        )
        for local_i in range(12):
            global_i = int(dofs[local_i])
            for local_j in range(12):
                global_j = int(dofs[local_j])
                stiffness_matrix[global_i, global_j] += k_element[local_i, local_j]


def assemble_dual_beam_stiffness(model: DualBeamMainlineModel) -> np.ndarray:
    """Assemble the uncoupled main+rear beam stiffness matrix."""

    nn = model.y_nodes_m.size
    ndof = 2 * nn * 6
    stiffness = np.zeros((ndof, ndof), dtype=float)
    _assemble_chain_beam(
        stiffness_matrix=stiffness,
        nodes_m=model.nodes_main_m,
        start_node=0,
        area_m2=model.main_area_m2,
        iy_m4=model.main_iy_m4,
        iz_m4=model.main_iz_m4,
        j_m4=model.main_j_m4,
        young_pa=model.main_young_pa,
        shear_pa=model.main_shear_pa,
    )
    _assemble_chain_beam(
        stiffness_matrix=stiffness,
        nodes_m=model.nodes_rear_m,
        start_node=nn,
        area_m2=model.rear_area_m2,
        iy_m4=model.rear_iy_m4,
        iz_m4=model.rear_iz_m4,
        j_m4=model.rear_j_m4,
        young_pa=model.rear_young_pa,
        shear_pa=model.rear_shear_pa,
    )
    return stiffness


def _assemble_explicit_wire_truss_support(
    *,
    model: DualBeamMainlineModel,
    active_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Assemble linearized wire-truss support stiffness and prestrain offset."""

    nn = model.y_nodes_m.size
    ndof = 2 * nn * 6
    stiffness = np.zeros((ndof, ndof), dtype=float)
    offset_vector = np.zeros(ndof, dtype=float)
    if len(model.wire_node_indices) == 0:
        return stiffness, offset_vector

    active = np.asarray(active_mask, dtype=bool).reshape(-1)
    if active.shape != (len(model.wire_node_indices),):
        raise ValueError("active_mask must align with wire_node_indices.")
    if model.wire_anchor_points_m.shape != (len(model.wire_node_indices), 3):
        raise ValueError("wire_anchor_points_m must have shape (n_wires, 3) for truss support.")

    for wire_index, (node_index, anchor_point_m, area_m2, young_pa, ref_length_m, unstretched_m) in enumerate(
        zip(
            model.wire_node_indices,
            np.asarray(model.wire_anchor_points_m, dtype=float),
            np.asarray(model.wire_area_m2, dtype=float),
            np.asarray(model.wire_young_pa, dtype=float),
            np.asarray(model.wire_reference_lengths_m, dtype=float),
            np.asarray(model.wire_unstretched_lengths_m, dtype=float),
            strict=True,
        )
    ):
        if not active[wire_index]:
            continue
        axis = np.asarray(model.nodes_main_m[node_index], dtype=float) - np.asarray(anchor_point_m, dtype=float)
        axis_norm = np.linalg.norm(axis)
        if axis_norm <= 1.0e-12:
            raise ValueError("Wire anchor point must not coincide with the attachment point.")
        if ref_length_m <= 1.0e-12 or unstretched_m <= 1.0e-12:
            raise ValueError("Wire truss lengths must stay positive.")
        axis_unit = axis / axis_norm
        axial_stiffness_npm = float(young_pa) * float(area_m2) / float(unstretched_m)
        node_slice = slice(node_index * 6, node_index * 6 + 3)
        stiffness[node_slice, node_slice] += axial_stiffness_npm * np.outer(axis_unit, axis_unit)
        initial_extension_m = float(ref_length_m) - float(unstretched_m)
        if abs(initial_extension_m) > 0.0:
            offset_vector[node_slice] += axial_stiffness_npm * initial_extension_m * axis_unit

    return stiffness, offset_vector


def _evaluate_explicit_wire_truss_support(
    *,
    model: DualBeamMainlineModel,
    disp_main_m: np.ndarray,
) -> ExplicitWireSupportResult:
    """Recover explicit wire-support reactions from the solved main-beam displacements."""

    nn = model.y_nodes_m.size
    ndof = 2 * nn * 6
    support_reaction_vector_n = np.zeros(ndof, dtype=float)
    n_wires = len(model.wire_node_indices)
    wire_reaction_vectors_n = np.zeros((n_wires, 3), dtype=float)
    wire_resultants_n = np.zeros(n_wires, dtype=float)
    active_mask = np.zeros(n_wires, dtype=bool)

    for wire_index, (node_index, anchor_point_m, area_m2, young_pa, ref_length_m, unstretched_m) in enumerate(
        zip(
            model.wire_node_indices,
            np.asarray(model.wire_anchor_points_m, dtype=float),
            np.asarray(model.wire_area_m2, dtype=float),
            np.asarray(model.wire_young_pa, dtype=float),
            np.asarray(model.wire_reference_lengths_m, dtype=float),
            np.asarray(model.wire_unstretched_lengths_m, dtype=float),
            strict=True,
        )
    ):
        axis = np.asarray(model.nodes_main_m[node_index], dtype=float) - np.asarray(anchor_point_m, dtype=float)
        axis_norm = np.linalg.norm(axis)
        if axis_norm <= 1.0e-12:
            raise ValueError("Wire anchor point must not coincide with the attachment point.")
        if ref_length_m <= 1.0e-12 or unstretched_m <= 1.0e-12:
            raise ValueError("Wire truss lengths must stay positive.")
        axis_unit = axis / axis_norm
        axial_stiffness_npm = float(young_pa) * float(area_m2) / float(unstretched_m)
        projected_extension_m = float(np.dot(np.asarray(disp_main_m[node_index, :3], dtype=float), axis_unit))
        initial_extension_m = float(ref_length_m) - float(unstretched_m)
        axial_force_n = axial_stiffness_npm * (projected_extension_m + initial_extension_m)
        tension_n = max(axial_force_n, 0.0)
        if tension_n > _WIRE_ACTIVE_TOL_N:
            active_mask[wire_index] = True
        reaction_vector_n = -tension_n * axis_unit
        wire_reaction_vectors_n[wire_index] = reaction_vector_n
        wire_resultants_n[wire_index] = tension_n
        node_slice = slice(node_index * 6, node_index * 6 + 3)
        support_reaction_vector_n[node_slice] += reaction_vector_n

    return ExplicitWireSupportResult(
        active_mask=active_mask,
        support_reaction_vector_n=support_reaction_vector_n,
        wire_reaction_vectors_n=wire_reaction_vectors_n,
        wire_resultants_n=wire_resultants_n,
    )


def _solve_saddle_point(
    *,
    stiffness: np.ndarray,
    load_vector: np.ndarray,
    constraints: ConstraintAssemblyResult,
) -> tuple[np.ndarray, np.ndarray]:
    """Solve one exact-constraint saddle-point system."""

    ndof = stiffness.shape[0]
    constraint_matrix = np.asarray(constraints.scaled_matrix, dtype=float)
    constraint_rhs = np.asarray(constraints.scaled_rhs, dtype=float)
    n_constraints = constraint_matrix.shape[0]
    saddle_matrix = np.zeros((ndof + n_constraints, ndof + n_constraints), dtype=float)
    saddle_matrix[:ndof, :ndof] = stiffness
    saddle_matrix[:ndof, ndof:] = constraint_matrix.T
    saddle_matrix[ndof:, :ndof] = constraint_matrix

    rhs = np.zeros(ndof + n_constraints, dtype=float)
    rhs[:ndof] = load_vector
    rhs[ndof:] = constraint_rhs

    try:
        solution = np.linalg.solve(saddle_matrix, rhs)
    except np.linalg.LinAlgError as exc:
        raise RuntimeError("Dual-beam mainline saddle-point system is singular.") from exc

    return solution[:ndof], solution[ndof:]


def solve_dual_beam_state(
    *,
    model: DualBeamMainlineModel,
    main_loads_n: np.ndarray,
    rear_loads_n: np.ndarray,
    constraints: ConstraintAssemblyResult,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, ExplicitWireSupportResult | None]:
    """Solve the exact-constraint saddle-point system and return state + multipliers."""

    nn = model.y_nodes_m.size
    ndof = 2 * nn * 6
    beam_stiffness = assemble_dual_beam_stiffness(model)

    load_vector = np.zeros(ndof, dtype=float)
    load_vector[: nn * 6] = np.asarray(main_loads_n, dtype=float).reshape(nn * 6)
    load_vector[nn * 6 :] = np.asarray(rear_loads_n, dtype=float).reshape(nn * 6)

    explicit_wire_support: ExplicitWireSupportResult | None = None

    if constraints.constraint_mode.wire_bc == WireBCMode.WIRE_MAIN_TRUSS and len(model.wire_node_indices) > 0:
        active_mask = np.asarray(
            np.asarray(model.wire_reference_lengths_m, dtype=float)
            > np.asarray(model.wire_unstretched_lengths_m, dtype=float) + 1.0e-12,
            dtype=bool,
        )
        state = np.zeros(ndof, dtype=float)
        multipliers_scaled = np.zeros(constraints.scaled_matrix.shape[0], dtype=float)
        stiffness = beam_stiffness
        for _ in range(_WIRE_ACTIVE_SET_MAX_ITERS):
            wire_stiffness, wire_offset_vector = _assemble_explicit_wire_truss_support(
                model=model,
                active_mask=active_mask,
            )
            stiffness = beam_stiffness + wire_stiffness
            state, multipliers_scaled = _solve_saddle_point(
                stiffness=stiffness,
                load_vector=load_vector - wire_offset_vector,
                constraints=constraints,
            )
            disp_main_trial = state[: nn * 6].reshape((nn, 6))
            explicit_wire_support = _evaluate_explicit_wire_truss_support(
                model=model,
                disp_main_m=disp_main_trial,
            )
            if np.array_equal(explicit_wire_support.active_mask, active_mask):
                break
            active_mask = explicit_wire_support.active_mask.copy()
        else:
            raise RuntimeError("Explicit wire truss active-set solve did not converge.")
    else:
        stiffness = beam_stiffness
        state, multipliers_scaled = _solve_saddle_point(
            stiffness=stiffness,
            load_vector=load_vector,
            constraints=constraints,
        )

    multipliers = np.asarray(constraints.row_scale_factors, dtype=float) * multipliers_scaled
    if not np.all(np.isfinite(state)) or not np.all(np.isfinite(multipliers)):
        raise RuntimeError("Dual-beam mainline solve produced non-finite state values.")

    disp_main = state[: nn * 6].reshape((nn, 6))
    disp_rear = state[nn * 6 :].reshape((nn, 6))
    if constraints.constraint_mode.wire_bc == WireBCMode.WIRE_MAIN_TRUSS and len(model.wire_node_indices) > 0:
        explicit_wire_support = _evaluate_explicit_wire_truss_support(
            model=model,
            disp_main_m=disp_main,
        )
    return disp_main, disp_rear, multipliers, stiffness, explicit_wire_support
