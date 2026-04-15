"""Inertia helpers for the mass-budget package."""

from __future__ import annotations

from typing import Sequence

import numpy as np


def parallel_axis(
    inertia_about_cg: Sequence[Sequence[float]] | np.ndarray,
    mass_kg: float,
    r_from_about_m: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Shift an inertia tensor from an item's CG to another reference point."""

    inertia = np.asarray(inertia_about_cg, dtype=float)
    if inertia.shape != (3, 3):
        raise ValueError(f"inertia_about_cg must be (3, 3), got {inertia.shape}.")
    r = np.asarray(r_from_about_m, dtype=float).reshape(-1)
    if r.shape != (3,):
        raise ValueError(f"r_from_about_m must be length 3, got {r.shape}.")
    rr = float(np.dot(r, r))
    return inertia + float(mass_kg) * (rr * np.eye(3) - np.outer(r, r))


def point_inertia(
    mass_kg: float,
    r_from_cg: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Return the inertia tensor of a point mass about an offset reference point."""

    return parallel_axis(np.zeros((3, 3), dtype=float), mass_kg, r_from_cg)


def tube_inertia(
    mass_kg: float,
    length_m: float,
    r_outer_m: float,
    r_inner_m: float,
    axis: str = "x",
) -> np.ndarray:
    """Principal inertia tensor of a cylindrical tube about its own CG."""

    if mass_kg < 0.0 or length_m < 0.0 or r_outer_m < 0.0 or r_inner_m < 0.0:
        raise ValueError("tube_inertia inputs must be non-negative.")
    if r_inner_m > r_outer_m:
        raise ValueError("tube_inertia requires r_inner_m <= r_outer_m.")

    radius_sum = float(r_outer_m**2 + r_inner_m**2)
    i_axial = 0.5 * float(mass_kg) * radius_sum
    i_transverse = (float(mass_kg) / 12.0) * (3.0 * radius_sum + float(length_m) ** 2)

    axis_token = axis.strip().lower()
    if axis_token == "x":
        return np.diag([i_axial, i_transverse, i_transverse])
    if axis_token == "y":
        return np.diag([i_transverse, i_axial, i_transverse])
    if axis_token == "z":
        return np.diag([i_transverse, i_transverse, i_axial])
    raise ValueError(f"tube_inertia axis must be one of x/y/z, got {axis!r}.")


def _unit_vector(direction_vector: Sequence[float] | np.ndarray) -> np.ndarray:
    vec = np.asarray(direction_vector, dtype=float).reshape(-1)
    if vec.shape != (3,):
        raise ValueError(f"direction_vector must be length 3, got {vec.shape}.")
    norm = float(np.linalg.norm(vec))
    if norm <= 0.0:
        raise ValueError("direction_vector must have non-zero length.")
    return vec / norm


def _basis_from_axis(
    direction_vector: Sequence[float] | np.ndarray,
    axis: str = "x",
) -> np.ndarray:
    primary = _unit_vector(direction_vector)
    trial = np.array([0.0, 0.0, 1.0], dtype=float)
    if abs(float(np.dot(primary, trial))) > 0.95:
        trial = np.array([0.0, 1.0, 0.0], dtype=float)

    secondary = np.cross(trial, primary)
    secondary_norm = float(np.linalg.norm(secondary))
    if secondary_norm <= 0.0:
        raise ValueError("Failed to build an orthonormal basis.")
    secondary /= secondary_norm
    tertiary = np.cross(primary, secondary)

    axis_token = axis.strip().lower()
    if axis_token == "x":
        return np.column_stack((primary, secondary, tertiary))
    if axis_token == "y":
        return np.column_stack((secondary, primary, tertiary))
    if axis_token == "z":
        return np.column_stack((secondary, tertiary, primary))
    raise ValueError(f"axis must be one of x/y/z, got {axis!r}.")


def rotate_inertia_tensor(
    inertia_tensor_kgm2: Sequence[Sequence[float]] | np.ndarray,
    direction_vector: Sequence[float] | np.ndarray,
    *,
    axis: str = "x",
) -> np.ndarray:
    """Rotate a principal-axis inertia tensor onto an arbitrary 3D direction."""

    inertia = np.asarray(inertia_tensor_kgm2, dtype=float)
    if inertia.shape != (3, 3):
        raise ValueError(f"inertia_tensor_kgm2 must be (3, 3), got {inertia.shape}.")
    basis = _basis_from_axis(direction_vector, axis=axis)
    return basis @ inertia @ basis.T


def distributed_lift_mass_from_result(
    result,
    rho_per_segment: Sequence[float] | np.ndarray | float,
):
    """Return one `LineMass` per consecutive result node pair.

    Parameters
    ----------
    result:
        Any result-like object exposing ``nodes`` with shape ``(n, 3)``.
    rho_per_segment:
        Linear mass density in ``kg/m``. Accepts:
        - scalar: same density on every segment
        - length ``n-1``: one density per node pair
        - length ``n``: nodal samples averaged to segments
    """

    from hpa_mdo.mass.components import LineMass

    nodes = np.asarray(getattr(result, "nodes", None), dtype=float)
    if nodes.ndim != 2 or nodes.shape[1] != 3 or nodes.shape[0] < 2:
        raise ValueError("result.nodes must have shape (n>=2, 3).")

    rho = np.asarray(rho_per_segment, dtype=float).reshape(-1)
    n_segments = nodes.shape[0] - 1
    if rho.size == 1:
        rho = np.full(n_segments, float(rho.item()), dtype=float)
    elif rho.size == nodes.shape[0]:
        rho = 0.5 * (rho[:-1] + rho[1:])
    elif rho.size != n_segments:
        raise ValueError(
            f"rho_per_segment must have length 1, {nodes.shape[0]}, or {n_segments}; "
            f"got {rho.size}."
        )
    if np.any(rho < 0.0):
        raise ValueError("rho_per_segment must be >= 0.")

    return [
        LineMass(
            name=f"distributed_seg{index + 1}",
            linear_kg_per_m=float(rho[index]),
            xyz_start_m=tuple(float(value) for value in nodes[index]),
            xyz_end_m=tuple(float(value) for value in nodes[index + 1]),
        )
        for index in range(n_segments)
    ]
