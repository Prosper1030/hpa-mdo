"""Rib-link row builders for dual-beam mainline compare modes."""

from __future__ import annotations

import numpy as np

from hpa_mdo.structure.dual_beam_mainline.types import DualBeamMainlineModel, LinkMode


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


def select_link_nodes(model: DualBeamMainlineModel, link_mode: LinkMode) -> tuple[int, ...]:
    """Return the node stations owned by the selected rib-link mode."""

    if link_mode in (
        LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY,
        LinkMode.JOINT_ONLY_OFFSET_RIGID,
    ):
        return model.joint_node_indices
    if link_mode in (
        LinkMode.DENSE_OFFSET_RIGID,
        LinkMode.DENSE_FINITE_RIB,
    ):
        return model.dense_link_node_indices
    raise ValueError(f"Unsupported link mode: {link_mode}.")


def _build_equal_dof_rows(
    *,
    ndof: int,
    nn: int,
    node_index: int,
) -> tuple[np.ndarray, ...]:
    rows: list[np.ndarray] = []
    for dof in range(6):
        row = np.zeros(ndof, dtype=float)
        row[_rear_dof(nn, node_index, dof)] = 1.0
        row[_main_dof(node_index, dof)] = -1.0
        rows.append(row)
    return tuple(rows)


def _build_offset_translation_rows(
    *,
    ndof: int,
    nn: int,
    node_index: int,
    offset_vector_m: np.ndarray,
) -> tuple[np.ndarray, ...]:
    rows: list[np.ndarray] = []
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
    return tuple(rows)


def _build_equal_rotation_rows(
    *,
    ndof: int,
    nn: int,
    node_index: int,
) -> tuple[np.ndarray, ...]:
    rows: list[np.ndarray] = []
    for axis in range(3):
        row = np.zeros(ndof, dtype=float)
        row[_rear_dof(nn, node_index, 3 + axis)] = 1.0
        row[_main_dof(node_index, 3 + axis)] = -1.0
        rows.append(row)
    return tuple(rows)


def build_link_rows(
    *,
    ndof: int,
    nn: int,
    node_index: int,
    link_mode: LinkMode,
    offset_vector_m: np.ndarray,
) -> tuple[np.ndarray, ...]:
    """Build exact-constraint rows for one rib-link station.

    `dense_finite_rib` is intentionally a surrogate compare mode for the exact-constraint
    kernel: it preserves the offset-aware translational closure across the rib bay while
    allowing relative spar rotations, so robustness studies can probe sensitivity without
    presenting the mode as final finite-stiffness truth.
    """

    if link_mode == LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY:
        return _build_equal_dof_rows(
            ndof=ndof,
            nn=nn,
            node_index=node_index,
        )
    if link_mode in (
        LinkMode.JOINT_ONLY_OFFSET_RIGID,
        LinkMode.DENSE_OFFSET_RIGID,
    ):
        return _build_offset_translation_rows(
            ndof=ndof,
            nn=nn,
            node_index=node_index,
            offset_vector_m=offset_vector_m,
        ) + _build_equal_rotation_rows(
            ndof=ndof,
            nn=nn,
            node_index=node_index,
        )
    if link_mode == LinkMode.DENSE_FINITE_RIB:
        return _build_offset_translation_rows(
            ndof=ndof,
            nn=nn,
            node_index=node_index,
            offset_vector_m=offset_vector_m,
        )
    raise ValueError(f"Unsupported link mode: {link_mode}.")
