"""Classical lamination theory helpers for discrete symmetric tube layups."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from hpa_mdo.core.materials import PlyMaterial


@dataclass(frozen=True)
class PlyStack:
    """Discrete ply schedule defined on the half-layup."""

    n_0: int
    n_45: int
    n_90: int

    def total_half_plies(self) -> int:
        return self.n_0 + 2 * self.n_45 + self.n_90

    def total_plies(self) -> int:
        return 2 * self.total_half_plies()

    def wall_thickness(self, t_ply: float) -> float:
        return self.total_plies() * float(t_ply)

    def angle_sequence_half(self) -> tuple[float, ...]:
        return (
            (90.0,) * self.n_90
            + (0.0,) * self.n_0
            + (45.0, -45.0) * self.n_45
        )

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.n_0 < 1:
            issues.append("n_0 must be at least 1 for bending stiffness.")
        if self.n_45 < 1:
            issues.append("n_45 must be at least 1 for torsional stiffness.")
        if self.n_90 < 0:
            issues.append("n_90 must be non-negative.")
        if min(self.n_0, self.n_45, self.n_90) < 0:
            issues.append("Ply counts must be non-negative.")
        if self.total_plies() < 4:
            issues.append("total_plies must be at least 4.")
        if self.n_90 > 0 and self.total_half_plies() == self.n_90:
            issues.append("90-degree plies cannot occupy the outermost position.")
        return issues


@dataclass(frozen=True)
class TubeEquivalentProperties:
    """Equivalent tube properties derived from a laminate A-matrix."""

    E_axial: float
    G_shear: float
    wall_thickness: float
    density: float
    A11: float
    A66: float
    outer_radius: float
    EA_axial: float
    EI_bending: float
    GJ_torsion: float


def ply_Q_matrix(E1: float, E2: float, G12: float, nu12: float) -> np.ndarray:
    """Return the on-axis reduced stiffness matrix for a UD ply."""
    nu21 = float(nu12) * float(E2) / float(E1)
    denom = 1.0 - float(nu12) * nu21
    if denom <= 0.0:
        raise ValueError("Invalid orthotropic constants: 1 - nu12 * nu21 must be positive.")

    Q11 = float(E1) / denom
    Q22 = float(E2) / denom
    Q12 = float(nu12) * float(E2) / denom
    Q66 = float(G12)
    return np.array(
        [[Q11, Q12, 0.0], [Q12, Q22, 0.0], [0.0, 0.0, Q66]],
        dtype=float,
    )


def rotated_Q(Q: np.ndarray, theta_deg: float) -> np.ndarray:
    """Rotate the reduced stiffness matrix into the ply material axes."""
    theta_rad = np.deg2rad(float(theta_deg))
    c = float(np.cos(theta_rad))
    s = float(np.sin(theta_rad))
    c2 = c * c
    s2 = s * s
    c4 = c2 * c2
    s4 = s2 * s2
    c3s = c2 * c * s
    cs3 = c * s2 * s
    s2c2 = s2 * c2

    Q11 = float(Q[0, 0])
    Q22 = float(Q[1, 1])
    Q12 = float(Q[0, 1])
    Q66 = float(Q[2, 2])

    q11_bar = Q11 * c4 + 2.0 * (Q12 + 2.0 * Q66) * s2c2 + Q22 * s4
    q22_bar = Q11 * s4 + 2.0 * (Q12 + 2.0 * Q66) * s2c2 + Q22 * c4
    q12_bar = (Q11 + Q22 - 4.0 * Q66) * s2c2 + Q12 * (s4 + c4)
    q16_bar = (Q11 - Q12 - 2.0 * Q66) * c3s - (Q22 - Q12 - 2.0 * Q66) * cs3
    q26_bar = (Q11 - Q12 - 2.0 * Q66) * cs3 - (Q22 - Q12 - 2.0 * Q66) * c3s
    q66_bar = (Q11 + Q22 - 2.0 * Q12 - 2.0 * Q66) * s2c2 + Q66 * (s4 + c4)

    return np.array(
        [
            [q11_bar, q12_bar, q16_bar],
            [q12_bar, q22_bar, q26_bar],
            [q16_bar, q26_bar, q66_bar],
        ],
        dtype=float,
    )


def compute_ABD(
    ply_angles_deg: Sequence[float],
    t_ply: float,
    Q: np.ndarray,
    symmetric: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute laminate ABD matrices.

    When ``symmetric`` is True, ``ply_angles_deg`` is interpreted as the
    half-layup sequence from laminate core to the outer surface.
    """
    if not ply_angles_deg:
        raise ValueError("ply_angles_deg must not be empty.")
    if t_ply <= 0.0:
        raise ValueError("t_ply must be positive.")

    half_angles = tuple(float(angle) for angle in ply_angles_deg)
    full_angles = tuple(reversed(half_angles)) + half_angles if symmetric else half_angles
    total_thickness = len(full_angles) * float(t_ply)
    z_bot = -0.5 * total_thickness

    A = np.zeros((3, 3), dtype=float)
    B = np.zeros((3, 3), dtype=float)
    D = np.zeros((3, 3), dtype=float)

    for angle in full_angles:
        z_top = z_bot + float(t_ply)
        Q_bar = rotated_Q(Q, angle)
        A += Q_bar * (z_top - z_bot)
        B += 0.5 * Q_bar * (z_top**2 - z_bot**2)
        D += (1.0 / 3.0) * Q_bar * (z_top**3 - z_bot**3)
        z_bot = z_top

    if symmetric:
        atol = max(float(np.max(np.abs(A))), 1.0) * 1e-10
        if not np.allclose(B, 0.0, atol=atol, rtol=1e-10):
            raise AssertionError("Symmetric laminate should produce a near-zero B matrix.")

    return A, B, D


def tube_equivalent_from_layup(
    stack: PlyStack,
    ply_mat: PlyMaterial,
    R_outer: float,
) -> TubeEquivalentProperties:
    """Compute equivalent tube properties from a symmetric ply stack."""
    if R_outer <= 0.0:
        raise ValueError("R_outer must be positive.")

    Q = ply_Q_matrix(
        E1=ply_mat.E1,
        E2=ply_mat.E2,
        G12=ply_mat.G12,
        nu12=ply_mat.nu12,
    )
    A, _, _ = compute_ABD(
        ply_angles_deg=stack.angle_sequence_half(),
        t_ply=ply_mat.t_ply,
        Q=Q,
        symmetric=True,
    )
    wall_thickness = stack.wall_thickness(ply_mat.t_ply)
    E_axial = float(A[0, 0]) / wall_thickness
    G_shear = float(A[2, 2]) / wall_thickness
    outer_radius = float(R_outer)

    return TubeEquivalentProperties(
        E_axial=E_axial,
        G_shear=G_shear,
        wall_thickness=wall_thickness,
        density=ply_mat.density,
        A11=float(A[0, 0]),
        A66=float(A[2, 2]),
        outer_radius=outer_radius,
        EA_axial=2.0 * np.pi * outer_radius * float(A[0, 0]),
        EI_bending=np.pi * outer_radius**3 * float(A[0, 0]),
        GJ_torsion=4.0 * np.pi * outer_radius**3 * float(A[2, 2]),
    )
