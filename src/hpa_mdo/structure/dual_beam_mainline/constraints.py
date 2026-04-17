"""Exact-constraint assembly for dual-beam root, wire, and link modes."""

from __future__ import annotations

import numpy as np
from scipy.linalg import qr

from hpa_mdo.structure.dual_beam_mainline.types import (
    ConstraintAuditResult,
    ConstraintAssemblyResult,
    DualBeamConstraintMode,
    DualBeamMainlineModel,
    LinkMode,
    RootBCMode,
    WireBCMode,
)

_CONSTRAINT_NORM_TOL = 1.0e-12
_CONSTRAINT_RANK_TOL = 1.0e-10


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


def _append_wire_axial_row(
    rows: list[np.ndarray],
    ndof: int,
    *,
    node_index: int,
    anchor_point_m: np.ndarray,
    attachment_point_m: np.ndarray,
) -> None:
    axis = np.asarray(attachment_point_m, dtype=float) - np.asarray(anchor_point_m, dtype=float)
    axis_norm = np.linalg.norm(axis)
    if axis_norm <= _CONSTRAINT_NORM_TOL:
        raise ValueError("Wire anchor point must not coincide with the attachment point.")
    axis_unit = axis / axis_norm

    row = np.zeros(ndof, dtype=float)
    for dof, coeff in enumerate(axis_unit):
        row[_main_dof(node_index, dof)] = coeff
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


def _constraint_row_basis(
    *,
    matrix: np.ndarray,
    rhs: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, ConstraintAuditResult]:
    """Return a safely scaled, full-row-rank constraint basis."""

    raw_matrix = np.asarray(matrix, dtype=float)
    raw_rhs = np.asarray(rhs, dtype=float).reshape(-1)
    if raw_matrix.ndim != 2:
        raise ValueError("constraint matrix must be 2D.")
    if raw_matrix.shape[0] != raw_rhs.size:
        raise ValueError("constraint matrix row count must match rhs size.")

    raw_row_count = int(raw_matrix.shape[0])
    if raw_row_count == 0:
        raise ValueError("Dual-beam mainline analysis requires at least one constraint row.")

    row_norms = np.linalg.norm(raw_matrix, axis=1)
    candidate_indices = np.flatnonzero(row_norms > _CONSTRAINT_NORM_TOL)
    if candidate_indices.size == 0:
        raise ValueError("constraint matrix contains only zero-norm rows.")

    scaled_candidates = raw_matrix[candidate_indices] / row_norms[candidate_indices, None]
    _, r_factor, pivot = qr(scaled_candidates.T, pivoting=True, mode="economic")
    diag = np.abs(np.diag(r_factor))
    rank = int(np.sum(diag > _CONSTRAINT_RANK_TOL)) if diag.size else 0
    independent_local = np.sort(np.asarray(pivot[:rank], dtype=int))
    keep_indices = candidate_indices[independent_local]
    removed_indices = np.setdiff1d(
        np.arange(raw_row_count, dtype=int),
        keep_indices,
        assume_unique=False,
    )

    active_matrix = raw_matrix[keep_indices]
    active_rhs = raw_rhs[keep_indices]
    active_row_norms = np.linalg.norm(active_matrix, axis=1)
    row_scale_factors = np.where(
        active_row_norms > _CONSTRAINT_NORM_TOL,
        1.0 / active_row_norms,
        1.0,
    )
    scaled_matrix = active_matrix * row_scale_factors[:, None]
    scaled_rhs = active_rhs * row_scale_factors

    if scaled_matrix.size:
        singular_values = np.linalg.svd(scaled_matrix, compute_uv=False)
        cond = (
            float(singular_values[0] / singular_values[-1])
            if singular_values[-1] > _CONSTRAINT_RANK_TOL
            else float("inf")
        )
        active_rank = int(np.sum(singular_values > _CONSTRAINT_RANK_TOL))
    else:
        cond = 1.0
        active_rank = 0

    audit = ConstraintAuditResult(
        raw_row_count=raw_row_count,
        active_row_count=int(active_matrix.shape[0]),
        removed_row_count=int(removed_indices.size),
        raw_rank=rank,
        active_rank=active_rank,
        scaled_condition_number=cond,
        full_row_rank=bool(active_rank == active_matrix.shape[0]),
        kept_row_indices=tuple(int(value) for value in keep_indices),
        removed_row_indices=tuple(int(value) for value in removed_indices),
    )
    return active_matrix, scaled_matrix, row_scale_factors, audit


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
    elif constraint_mode.wire_bc == WireBCMode.WIRE_MAIN_TRUSS:
        pass
    elif constraint_mode.wire_bc == WireBCMode.WIRE_MAIN_AXIAL:
        if model.wire_anchor_points_m.shape != (len(model.wire_node_indices), 3):
            raise ValueError(
                "wire_anchor_points_m must have shape (n_wires, 3) when wire_main_axial is used."
            )
        for node_index, anchor_point_m in zip(
            model.wire_node_indices,
            model.wire_anchor_points_m,
            strict=True,
        ):
            _append_wire_axial_row(
                rows,
                ndof,
                node_index=node_index,
                anchor_point_m=anchor_point_m,
                attachment_point_m=model.nodes_main_m[node_index],
            )
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

    raw_matrix = np.vstack(rows)
    raw_rhs = np.zeros(raw_matrix.shape[0], dtype=float)
    matrix, scaled_matrix, row_scale_factors, audit = _constraint_row_basis(
        matrix=raw_matrix,
        rhs=raw_rhs,
    )
    rhs = raw_rhs[np.asarray(audit.kept_row_indices, dtype=int)]

    kept_set = set(audit.kept_row_indices)

    def _group_slice(start: int, stop: int, cursor: int) -> tuple[slice, int]:
        count = sum(1 for idx in range(start, stop) if idx in kept_set)
        return slice(cursor, cursor + count), cursor + count

    cursor = 0
    root_main_slice, cursor = _group_slice(root_main_start, root_main_stop, cursor)
    root_rear_slice, cursor = _group_slice(root_rear_start, root_rear_stop, cursor)
    wire_slice, cursor = _group_slice(wire_start, wire_stop, cursor)
    active_link_row_slices: list[slice] = []
    for row_slice in link_row_slices:
        active_slice, cursor = _group_slice(row_slice.start, row_slice.stop, cursor)
        active_link_row_slices.append(active_slice)

    return ConstraintAssemblyResult(
        matrix=matrix,
        rhs=rhs,
        scaled_matrix=scaled_matrix,
        scaled_rhs=rhs * row_scale_factors,
        row_scale_factors=row_scale_factors,
        root_main_slice=root_main_slice,
        root_rear_slice=root_rear_slice,
        wire_slice=wire_slice,
        link_row_slices=tuple(active_link_row_slices),
        link_node_indices=link_node_indices,
        wire_node_indices=model.wire_node_indices,
        constraint_mode=constraint_mode,
        audit=audit,
    )
