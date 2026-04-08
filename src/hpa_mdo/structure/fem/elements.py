"""Low-level beam element kinematics and stiffness primitives.

These helpers are used by SpatialBeamFEM and are pure functions of
geometry / material - no state, no OpenMDAO. Kept module-private to
discourage downstream coupling outside the structure package.
"""
from __future__ import annotations

import numpy as np


def _timoshenko_element_stiffness(
    L: float, E: float, G: float,
    A: float, Iy: float, Iz: float, J: float,
) -> np.ndarray:
    """12×12 stiffness matrix for a 3-D Timoshenko beam element.

    DOF order per node: [u, v, w, θx, θy, θz]
    Local coord: x = axial (along element), y = lateral, z = vertical.

    Shear correction factor κ = 0.5 (thin-walled circular tube).
    """
    eps = 1e-30
    kappa = 0.5  # shear correction for hollow tube
    GA = kappa * G * A
    dtype = np.result_type(L, E, G, A, Iy, Iz, J, float)
    L_safe = L + np.array(eps, dtype=dtype)
    ga_l2 = GA * L**2
    ga_guard = np.array(eps, dtype=dtype)
    if np.real(np.abs(ga_l2)) > 1e-20:
        ga_guard = ga_l2 + np.array(eps, dtype=dtype)
    phi_y = 12.0 * E * Iz / ga_guard
    phi_z = 12.0 * E * Iy / ga_guard

    K = np.zeros((12, 12), dtype=dtype)

    # Axial (u)
    ea_L = E * A / L_safe
    K[0, 0] = ea_L
    K[0, 6] = -ea_L
    K[6, 0] = -ea_L
    K[6, 6] = ea_L

    # Torsion (θx)
    gj_L = G * J / L_safe
    K[3, 3] = gj_L
    K[3, 9] = -gj_L
    K[9, 3] = -gj_L
    K[9, 9] = gj_L

    # Bending in x-z plane (w, θy)
    c1 = E * Iy / ((L**3 + np.array(eps, dtype=dtype)) * (1 + phi_z))
    K[2, 2] = 12.0 * c1
    K[2, 4] = 6.0 * L * c1
    K[2, 8] = -12.0 * c1
    K[2, 10] = 6.0 * L * c1
    K[4, 2] = 6.0 * L * c1
    K[4, 4] = (4.0 + phi_z) * L**2 * c1
    K[4, 8] = -6.0 * L * c1
    K[4, 10] = (2.0 - phi_z) * L**2 * c1
    K[8, 2] = -12.0 * c1
    K[8, 4] = -6.0 * L * c1
    K[8, 8] = 12.0 * c1
    K[8, 10] = -6.0 * L * c1
    K[10, 2] = 6.0 * L * c1
    K[10, 4] = (2.0 - phi_z) * L**2 * c1
    K[10, 8] = -6.0 * L * c1
    K[10, 10] = (4.0 + phi_z) * L**2 * c1

    # Bending in x-y plane (v, θz)
    c2 = E * Iz / ((L**3 + np.array(eps, dtype=dtype)) * (1 + phi_y))
    K[1, 1] = 12.0 * c2
    K[1, 5] = -6.0 * L * c2
    K[1, 7] = -12.0 * c2
    K[1, 11] = -6.0 * L * c2
    K[5, 1] = -6.0 * L * c2
    K[5, 5] = (4.0 + phi_y) * L**2 * c2
    K[5, 7] = 6.0 * L * c2
    K[5, 11] = (2.0 - phi_y) * L**2 * c2
    K[7, 1] = -12.0 * c2
    K[7, 5] = 6.0 * L * c2
    K[7, 7] = 12.0 * c2
    K[7, 11] = 6.0 * L * c2
    K[11, 1] = -6.0 * L * c2
    K[11, 5] = (2.0 - phi_y) * L**2 * c2
    K[11, 7] = -6.0 * L * c2
    K[11, 11] = (4.0 + phi_y) * L**2 * c2

    return K


def _cs_norm(x):
    """Complex-step compatible vector norm: sqrt(dot(x,x))."""
    return np.sqrt(np.dot(x, x) + 1e-30)


def _has_only_finite_values(x: np.ndarray | float | complex) -> bool:
    """Return True when both real and imaginary parts are finite."""
    arr = np.asarray(x)
    return bool(np.all(np.isfinite(arr.real)) and np.all(np.isfinite(arr.imag)))


def _rotation_matrix(node_i: np.ndarray, node_j: np.ndarray) -> np.ndarray:
    """3×3 rotation from local to global coords for a beam element.

    Local x-axis is along the element.
    Local z-axis defaults to global Z unless element is vertical.
    Returns identity if nodes are coincident.
    Uses complex-step compatible operations.
    """
    dx = node_j - node_i
    L = _cs_norm(dx)
    if np.real(L) < 1e-12:
        return np.eye(3, dtype=dx.dtype)
    e1 = dx / (L + 1e-30)  # local x
    if not _has_only_finite_values(e1):
        return np.eye(3, dtype=dx.dtype)

    # Pick a reference direction (global Z unless nearly parallel to element)
    ref = np.array([0.0, 0.0, 1.0], dtype=dx.dtype)
    dot_val = np.real(np.dot(e1, np.array([0.0, 0.0, 1.0])))
    if abs(dot_val) > 0.99:
        ref = np.array([1.0, 0.0, 0.0], dtype=dx.dtype)

    e2 = np.cross(ref, e1)
    norm_e2 = _cs_norm(e2)
    if np.real(norm_e2) < 1e-12:
        return np.eye(3, dtype=dx.dtype)
    e2 = e2 / (norm_e2 + 1e-30)
    if not _has_only_finite_values(e2):
        return np.eye(3, dtype=dx.dtype)
    e3 = np.cross(e1, e2)
    e3 = e3 / (_cs_norm(e3) + 1e-30)
    if not _has_only_finite_values(e3):
        return np.eye(3, dtype=dx.dtype)

    return np.array([e1, e2, e3])


def _transform_12x12(R3: np.ndarray) -> np.ndarray:
    """Build 12×12 transformation matrix from 3×3 rotation."""
    T = np.zeros((12, 12), dtype=R3.dtype)
    for i in range(4):
        T[3*i:3*i+3, 3*i:3*i+3] = R3
    return T
