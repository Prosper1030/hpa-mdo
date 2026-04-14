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
        return (90.0,) * self.n_90 + (0.0,) * self.n_0 + (45.0, -45.0) * self.n_45

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


@dataclass(frozen=True)
class PlyFailureResult:
    """Tsai-Wu failure result for one ply at its mid-surface."""

    ply_index: int
    theta_deg: float
    z_mid: float
    stress_xy: tuple[float, float, float]
    stress_12: tuple[float, float, float]
    failure_index: float
    strength_ratio: float


@dataclass(frozen=True)
class TsaiWuCoefficients:
    """Plane-stress Tsai-Wu coefficients for a lamina."""

    F1: float
    F2: float
    F11: float
    F22: float
    F66: float
    F12: float


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


def _full_layup_angles(ply_angles_deg: Sequence[float], symmetric: bool) -> tuple[float, ...]:
    half_angles = tuple(float(angle) for angle in ply_angles_deg)
    return tuple(reversed(half_angles)) + half_angles if symmetric else half_angles


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

    full_angles = _full_layup_angles(ply_angles_deg, symmetric)
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


def tsai_wu_coefficients(
    ply_mat: PlyMaterial,
    interaction_coefficient: float = -0.5,
) -> TsaiWuCoefficients:
    """Return Tsai-Wu coefficients using the common estimated F12 interaction."""
    strengths = (ply_mat.F1t, ply_mat.F1c, ply_mat.F2t, ply_mat.F2c, ply_mat.F6)
    if any(float(value) <= 0.0 for value in strengths):
        raise ValueError("Tsai-Wu strengths must all be positive.")

    F11 = 1.0 / (float(ply_mat.F1t) * float(ply_mat.F1c))
    F22 = 1.0 / (float(ply_mat.F2t) * float(ply_mat.F2c))
    return TsaiWuCoefficients(
        F1=1.0 / float(ply_mat.F1t) - 1.0 / float(ply_mat.F1c),
        F2=1.0 / float(ply_mat.F2t) - 1.0 / float(ply_mat.F2c),
        F11=F11,
        F22=F22,
        F66=1.0 / float(ply_mat.F6) ** 2,
        F12=float(interaction_coefficient) * float(np.sqrt(F11 * F22)),
    )


def transform_global_stress_to_ply(
    stress_xy: Sequence[float],
    theta_deg: float,
) -> tuple[float, float, float]:
    """Transform laminate x-y stress components to local 1-2 ply axes."""
    if len(stress_xy) != 3:
        raise ValueError("stress_xy must contain sigma_x, sigma_y, tau_xy.")

    sigma_x, sigma_y, tau_xy = (float(value) for value in stress_xy)
    theta_rad = np.deg2rad(float(theta_deg))
    c = float(np.cos(theta_rad))
    s = float(np.sin(theta_rad))
    c2 = c * c
    s2 = s * s
    cs = c * s

    sigma_1 = c2 * sigma_x + s2 * sigma_y + 2.0 * cs * tau_xy
    sigma_2 = s2 * sigma_x + c2 * sigma_y - 2.0 * cs * tau_xy
    tau_12 = -cs * sigma_x + cs * sigma_y + (c2 - s2) * tau_xy
    return float(sigma_1), float(sigma_2), float(tau_12)


def tsai_wu_failure_index(
    stress_12: Sequence[float],
    ply_mat: PlyMaterial,
    interaction_coefficient: float = -0.5,
) -> float:
    """Evaluate Tsai-Wu failure index from local ply stresses."""
    if len(stress_12) != 3:
        raise ValueError("stress_12 must contain sigma_1, sigma_2, tau_12.")

    sigma_1, sigma_2, tau_12 = (float(value) for value in stress_12)
    coeffs = tsai_wu_coefficients(ply_mat, interaction_coefficient)
    return float(
        coeffs.F1 * sigma_1
        + coeffs.F2 * sigma_2
        + coeffs.F11 * sigma_1**2
        + coeffs.F22 * sigma_2**2
        + coeffs.F66 * tau_12**2
        + 2.0 * coeffs.F12 * sigma_1 * sigma_2
    )


def tsai_wu_strength_ratio(
    stress_12: Sequence[float],
    ply_mat: PlyMaterial,
    interaction_coefficient: float = -0.5,
) -> float:
    """Return the positive load multiplier that drives Tsai-Wu index to 1."""
    if len(stress_12) != 3:
        raise ValueError("stress_12 must contain sigma_1, sigma_2, tau_12.")

    sigma_1, sigma_2, tau_12 = (float(value) for value in stress_12)
    if max(abs(sigma_1), abs(sigma_2), abs(tau_12)) <= 0.0:
        return float("inf")

    coeffs = tsai_wu_coefficients(ply_mat, interaction_coefficient)
    linear = coeffs.F1 * sigma_1 + coeffs.F2 * sigma_2
    quadratic = (
        coeffs.F11 * sigma_1**2
        + coeffs.F22 * sigma_2**2
        + coeffs.F66 * tau_12**2
        + 2.0 * coeffs.F12 * sigma_1 * sigma_2
    )

    if abs(quadratic) <= 1.0e-18:
        return float("inf") if linear <= 0.0 else float(1.0 / linear)

    discriminant = linear**2 + 4.0 * quadratic
    if discriminant < 0.0:
        return float("inf")

    sqrt_discriminant = float(np.sqrt(discriminant))
    roots = (
        (-linear + sqrt_discriminant) / (2.0 * quadratic),
        (-linear - sqrt_discriminant) / (2.0 * quadratic),
    )
    positive_roots = [root for root in roots if root > 0.0]
    return float(min(positive_roots)) if positive_roots else float("inf")


def evaluate_laminate_tsai_wu(
    ply_angles_deg: Sequence[float],
    t_ply: float,
    ply_mat: PlyMaterial,
    midplane_strain: Sequence[float],
    curvature: Sequence[float] = (0.0, 0.0, 0.0),
    symmetric: bool = True,
    interaction_coefficient: float = -0.5,
) -> tuple[PlyFailureResult, ...]:
    """Evaluate per-ply Tsai-Wu indices from CLT midplane strain and curvature."""
    if not ply_angles_deg:
        raise ValueError("ply_angles_deg must not be empty.")
    if t_ply <= 0.0:
        raise ValueError("t_ply must be positive.")
    if len(midplane_strain) != 3:
        raise ValueError("midplane_strain must contain epsilon_x, epsilon_y, gamma_xy.")
    if len(curvature) != 3:
        raise ValueError("curvature must contain kappa_x, kappa_y, kappa_xy.")

    full_angles = _full_layup_angles(ply_angles_deg, symmetric)
    total_thickness = len(full_angles) * float(t_ply)
    z_bot = -0.5 * total_thickness
    eps0 = np.asarray(midplane_strain, dtype=float)
    kappa = np.asarray(curvature, dtype=float)
    Q = ply_Q_matrix(ply_mat.E1, ply_mat.E2, ply_mat.G12, ply_mat.nu12)

    results: list[PlyFailureResult] = []
    for ply_index, angle in enumerate(full_angles, start=1):
        z_top = z_bot + float(t_ply)
        z_mid = 0.5 * (z_bot + z_top)
        strain_xy = eps0 + z_mid * kappa
        stress_xy_array = rotated_Q(Q, angle) @ strain_xy
        stress_xy = tuple(float(value) for value in stress_xy_array)
        stress_12 = transform_global_stress_to_ply(stress_xy, angle)
        results.append(
            PlyFailureResult(
                ply_index=ply_index,
                theta_deg=float(angle),
                z_mid=float(z_mid),
                stress_xy=stress_xy,
                stress_12=stress_12,
                failure_index=tsai_wu_failure_index(
                    stress_12,
                    ply_mat,
                    interaction_coefficient=interaction_coefficient,
                ),
                strength_ratio=tsai_wu_strength_ratio(
                    stress_12,
                    ply_mat,
                    interaction_coefficient=interaction_coefficient,
                ),
            )
        )
        z_bot = z_top

    return tuple(results)


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
