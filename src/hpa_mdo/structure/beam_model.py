"""1-D Euler–Bernoulli beam finite-difference solver.

Solves for shear, bending moment, slope, and deflection of a cantilevered
beam under arbitrary distributed loading.  The beam is fixed at the root
(y=0) and free at the tip (y=b/2).

Governing equations (finite-difference form, node j → j+1):
    V_{j+1}  = V_j  + f_j * Δy
    M_{j+1}  = M_j  + ½(V_{j+1} + V_j) * Δy
    θ_{j+1}  = θ_j  + ½((M/EI)_{j+1} + (M/EI)_j) * Δy
    u_{j+1}  = u_j  + ½(θ_{j+1} + θ_j) * Δy

Boundary conditions:
    Root (j=0): u=0, θ=0   (fixed)
    Tip  (j=N): V=0, M=0   (free)

Integration proceeds from tip to root for V and M, then root to tip
for θ and u.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class BeamResult:
    """Full solution of the beam problem."""
    y: np.ndarray            # node positions [m]
    shear: np.ndarray        # shear force [N]
    moment: np.ndarray       # bending moment [N·m]
    slope: np.ndarray        # deflection angle [rad]
    deflection: np.ndarray   # transverse deflection [m]
    stress: np.ndarray       # max bending stress at each node [Pa]
    EI: np.ndarray           # bending stiffness distribution [N·m²]
    f_ext: np.ndarray        # applied external force per unit span [N/m]

    @property
    def tip_deflection(self) -> float:
        return float(self.deflection[-1])

    @property
    def max_stress(self) -> float:
        return float(np.max(np.abs(self.stress)))

    @property
    def max_deflection(self) -> float:
        return float(np.max(np.abs(self.deflection)))


class EulerBernoulliBeam:
    """Cantilevered Euler–Bernoulli beam solver (finite-difference method).

    The beam is discretised along y from root (0) to tip (b/2).
    """

    def solve(
        self,
        y: np.ndarray,
        EI: np.ndarray,
        f_ext: np.ndarray,
        outer_radius: np.ndarray,
        point_loads: dict[int, float] | None = None,
    ) -> BeamResult:
        """
        Parameters
        ----------
        y : (N,) array
            Node coordinates along the half-span [m].
        EI : (N,) array
            Flexural rigidity at each node [N·m²].
        f_ext : (N,) array
            External distributed force per unit span [N/m].
            Positive = upward (lift direction).
        outer_radius : (N,) array
            Outer radius of the spar at each node [m] (for stress calc).
        point_loads : dict[int, float] | None
            Optional point loads: {node_index: force_N}. Positive = up.

        Returns
        -------
        BeamResult
        """
        n = len(y)
        dy = np.diff(y)

        # ---- Integrate shear and moment from TIP to ROOT ----
        V = np.zeros(n)   # shear force
        M = np.zeros(n)   # bending moment

        # BC at tip: V[-1] = 0, M[-1] = 0 (free end)
        for j in range(n - 2, -1, -1):
            # Trapezoidal integration of distributed load
            V[j] = V[j + 1] + 0.5 * (f_ext[j] + f_ext[j + 1]) * dy[j]
            # Add point load at node j+1 (if any)
            if point_loads and (j + 1) in point_loads:
                V[j] += point_loads[j + 1]

        # Add point load at root
        if point_loads and 0 in point_loads:
            V[0] += point_loads[0]

        for j in range(n - 2, -1, -1):
            M[j] = M[j + 1] + 0.5 * (V[j] + V[j + 1]) * dy[j]

        # ---- Integrate slope and deflection from ROOT to TIP ----
        theta = np.zeros(n)  # slope [rad]
        u = np.zeros(n)      # deflection [m]

        # BC at root: theta[0] = 0, u[0] = 0 (fixed end)
        M_over_EI = M / EI

        for j in range(n - 1):
            theta[j + 1] = theta[j] + 0.5 * (M_over_EI[j] + M_over_EI[j + 1]) * dy[j]
            u[j + 1] = u[j] + 0.5 * (theta[j] + theta[j + 1]) * dy[j]

        # ---- Bending stress: σ = M * c / I  where c = outer_radius ----
        # EI = E * I, so I = EI / E ... but we need E separately.
        # Instead, σ = M * r / I = M * r * E / (EI)
        # But that requires E.  We store stress as |M * r_outer / I|.
        # Since EI = E * I and we know r_outer, we express:
        #   σ = M * r_outer / I
        # We'll pass E separately through the spar model; here we compute
        # the "stress-like" quantity M * r / (EI/E) which requires E.
        # For now, return M * r_outer / I where I is back-computed.
        # Actually, the cleaner approach: the caller (Spar) knows E and I
        # separately, but let's compute σ = M * r / I directly.
        # We'll store M and r and let the spar compute stress.  But for
        # convenience, we accept that EI was given and assume the caller
        # will also give us I (or r and OD/ID to compute I).
        # Simplest: return |M| * outer_radius and let caller divide by I.
        # Let's just do M*c/I using EI = E*I → I = EI/E, σ = M*c*E/EI
        # The caller knows E, so we store the intermediate M*c/EI
        # and the caller multiplies by E.
        #
        # Decision: store sigma_over_E = |M| * outer_radius / EI
        # The actual stress = sigma_over_E * E
        stress_over_E = np.abs(M) * outer_radius / EI

        return BeamResult(
            y=y,
            shear=V,
            moment=M,
            slope=theta,
            deflection=u,
            stress=stress_over_E,  # caller must multiply by E for actual stress
            EI=EI,
            f_ext=f_ext,
        )
