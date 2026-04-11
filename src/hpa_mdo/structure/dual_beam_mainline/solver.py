"""Stiffness assembly and exact-constraint solve for the dual-beam mainline kernel."""

from __future__ import annotations

import numpy as np

from hpa_mdo.structure.fem.elements import (
    _cs_norm,
    _rotation_matrix,
    _timoshenko_element_stiffness,
    _transform_12x12,
)

from hpa_mdo.structure.dual_beam_mainline.types import ConstraintAssemblyResult, DualBeamMainlineModel


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


def solve_dual_beam_state(
    *,
    model: DualBeamMainlineModel,
    main_loads_n: np.ndarray,
    rear_loads_n: np.ndarray,
    constraints: ConstraintAssemblyResult,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Solve the exact-constraint saddle-point system and return state + multipliers."""

    nn = model.y_nodes_m.size
    ndof = 2 * nn * 6
    stiffness = assemble_dual_beam_stiffness(model)

    load_vector = np.zeros(ndof, dtype=float)
    load_vector[: nn * 6] = np.asarray(main_loads_n, dtype=float).reshape(nn * 6)
    load_vector[nn * 6 :] = np.asarray(rear_loads_n, dtype=float).reshape(nn * 6)

    n_constraints = constraints.matrix.shape[0]
    saddle_matrix = np.zeros((ndof + n_constraints, ndof + n_constraints), dtype=float)
    saddle_matrix[:ndof, :ndof] = stiffness
    saddle_matrix[:ndof, ndof:] = constraints.matrix.T
    saddle_matrix[ndof:, :ndof] = constraints.matrix

    rhs = np.zeros(ndof + n_constraints, dtype=float)
    rhs[:ndof] = load_vector
    rhs[ndof:] = constraints.rhs

    try:
        solution = np.linalg.solve(saddle_matrix, rhs)
    except np.linalg.LinAlgError as exc:
        raise RuntimeError("Dual-beam mainline saddle-point system is singular.") from exc

    state = solution[:ndof]
    multipliers = solution[ndof:]
    if not np.all(np.isfinite(state)) or not np.all(np.isfinite(multipliers)):
        raise RuntimeError("Dual-beam mainline solve produced non-finite state values.")

    disp_main = state[: nn * 6].reshape((nn, 6))
    disp_rear = state[nn * 6 :].reshape((nn, 6))
    return disp_main, disp_rear, multipliers, stiffness
