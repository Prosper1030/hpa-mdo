"""Exact-constraint assembly for dual-beam root, wire, and link modes."""

from __future__ import annotations

import numpy as np

from hpa_mdo.structure.dual_beam_mainline.types import (
    ConstraintAssemblyResult,
    DualBeamConstraintMode,
    DualBeamMainlineModel,
    LinkMode,
    RootBCMode,
    WireBCMode,
)


def _main_dof(node_index: int, local_dof: int) -> int:
    return node_index * 6 + local_dof


def _rear_dof(nn: int, node_index: int, local_dof: int) -> int:
    return (nn + node_index) * 6 + local_dof


def _skew_matrix(offset_m: np.ndarray) -> np.ndarray:
    dx, dy, dz = np.asarray(offset_m, dtype=float)
    return np.array(
        [
            [0.0, -dz, dy],
            [dz, 0.0, -dx],
            [-dy, dx, 0.0],
        ],
        dtype=float,
    )


def _select_link_nodes(model: DualBeamMainlineModel, link_mode: LinkMode) -> tuple[int, ...]:
    if link_mode in (
        LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY,
        LinkMode.JOINT_ONLY_OFFSET_RIGID,
    ):
        return model.joint_node_indices
    if link_mode == LinkMode.DENSE_OFFSET_RIGID:
        return model.dense_link_node_indices
    if link_mode == LinkMode.DENSE_FINITE_RIB:
        raise NotImplementedError(
            "dense_finite_rib is reserved for robustness/future mode and is not yet implemented."
        )
    raise ValueError(f"Unsupported link mode: {link_mode}.")


def _append_fixed_node_rows(
    rows: list[np.ndarray],
    ndof: int,
    *,
    nn: int,
    node_index: int,
    use_rear: bool,
) -> None:
    for dof in range(6):
        row = np.zeros(ndof, dtype=float)
        if use_rear:
            row[_rear_dof(nn, node_index, dof)] = 1.0
        else:
            row[_main_dof(node_index, dof)] = 1.0
        rows.append(row)


def _append_equal_dof_rows(
    rows: list[np.ndarray],
    ndof: int,
    *,
    nn: int,
    node_index: int,
) -> None:
    for dof in range(6):
        row = np.zeros(ndof, dtype=float)
        row[_rear_dof(nn, node_index, dof)] = 1.0
        row[_main_dof(node_index, dof)] = -1.0
        rows.append(row)


def _append_offset_rigid_rows(
    rows: list[np.ndarray],
    ndof: int,
    *,
    nn: int,
    node_index: int,
    offset_vector_m: np.ndarray,
) -> None:
    skew = _skew_matrix(offset_vector_m)

    for axis in range(3):
        row = np.zeros(ndof, dtype=float)
        row[_main_dof(node_index, axis)] = -1.0
        row[_rear_dof(nn, node_index, axis)] = 1.0
        for rot_axis in range(3):
            coeff = 0.5 * skew[axis, rot_axis]
            row[_main_dof(node_index, 3 + rot_axis)] = coeff
            row[_rear_dof(nn, node_index, 3 + rot_axis)] = coeff
        rows.append(row)

    for axis in range(3):
        row = np.zeros(ndof, dtype=float)
        row[_rear_dof(nn, node_index, 3 + axis)] = 1.0
        row[_main_dof(node_index, 3 + axis)] = -1.0
        rows.append(row)


def build_constraint_assembly(
    *,
    model: DualBeamMainlineModel,
    constraint_mode: DualBeamConstraintMode,
) -> ConstraintAssemblyResult:
    """Build the exact constraint matrix for the selected root/wire/link configuration."""

    nn = model.y_nodes_m.size
    ndof = 2 * nn * 6
    rows: list[np.ndarray] = []

    root_main_start = len(rows)
    _append_fixed_node_rows(rows, ndof, nn=nn, node_index=0, use_rear=False)
    root_main_stop = len(rows)

    if constraint_mode.root_bc == RootBCMode.ROOT_FIXED_BOTH:
        root_rear_start = len(rows)
        _append_fixed_node_rows(rows, ndof, nn=nn, node_index=0, use_rear=True)
        root_rear_stop = len(rows)
    elif constraint_mode.root_bc == RootBCMode.ROOT_MAIN_FIXED_REAR_LINKED:
        root_rear_start = len(rows)
        _append_offset_rigid_rows(
            rows,
            ndof,
            nn=nn,
            node_index=0,
            offset_vector_m=model.spar_offset_vectors_m[0],
        )
        root_rear_stop = len(rows)
    else:
        raise ValueError(f"Unsupported root BC mode: {constraint_mode.root_bc}.")

    wire_start = len(rows)
    if constraint_mode.wire_bc == WireBCMode.WIRE_MAIN_VERTICAL:
        for node_index in model.wire_node_indices:
            row = np.zeros(ndof, dtype=float)
            row[_main_dof(node_index, 2)] = 1.0
            rows.append(row)
    elif constraint_mode.wire_bc == WireBCMode.WIRE_MAIN_AXIAL:
        raise NotImplementedError("wire_main_axial is reserved for a future validated wire model.")
    elif constraint_mode.wire_bc is not None:
        raise ValueError(f"Unsupported wire BC mode: {constraint_mode.wire_bc}.")
    wire_stop = len(rows)

    link_row_slices: list[slice] = []
    link_node_indices = _select_link_nodes(model, constraint_mode.link_mode)
    for node_index in link_node_indices:
        start = len(rows)
        if constraint_mode.link_mode == LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY:
            _append_equal_dof_rows(rows, ndof, nn=nn, node_index=node_index)
        elif constraint_mode.link_mode in (
            LinkMode.JOINT_ONLY_OFFSET_RIGID,
            LinkMode.DENSE_OFFSET_RIGID,
        ):
            _append_offset_rigid_rows(
                rows,
                ndof,
                nn=nn,
                node_index=node_index,
                offset_vector_m=model.spar_offset_vectors_m[node_index],
            )
        else:
            raise ValueError(f"Unsupported link mode: {constraint_mode.link_mode}.")
        stop = len(rows)
        link_row_slices.append(slice(start, stop))

    if not rows:
        raise ValueError("Dual-beam mainline analysis requires at least one constraint row.")

    matrix = np.vstack(rows)
    rhs = np.zeros(matrix.shape[0], dtype=float)
    return ConstraintAssemblyResult(
        matrix=matrix,
        rhs=rhs,
        root_main_slice=slice(root_main_start, root_main_stop),
        root_rear_slice=slice(root_rear_start, root_rear_stop),
        wire_slice=slice(wire_start, wire_stop),
        link_row_slices=tuple(link_row_slices),
        link_node_indices=link_node_indices,
        wire_node_indices=model.wire_node_indices,
        constraint_mode=constraint_mode,
    )
