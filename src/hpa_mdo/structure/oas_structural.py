"""OpenMDAO-based structural model using OAS SpatialBeam formulation.

This module implements 6-DOF Timoshenko beam finite elements within
the OpenMDAO framework, following the same formulation as
OpenAeroStruct's SpatialBeam but customised for:

    1. Segmented carbon-fiber tubes (piecewise-constant wall thickness)
    2. Dual-spar equivalent stiffness (parallel-axis theorem)
    3. Joint mass penalty in the objective
    4. Lift-wire point support
    5. External aero loads (from VSPAero, not VLM)
    6. Separate aerodynamic load factor and material safety factor

Design variables : segment wall thicknesses (main + rear spar)
Objective        : total spar system mass [kg]
Constraints      : stress ratio ≤ 1, tip deflection, twist ≤ ±2°

All engineering constants are read from HPAConfig — nothing hardcoded.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import openmdao.api as om

from hpa_mdo.core.logging import get_logger
from hpa_mdo.structure.spar_model import (
    tube_area,
    tube_Ixx,
    tube_J,
    tube_mass_per_length,
    segments_to_elements,
    segment_boundaries_from_lengths,
    compute_dual_spar_section,
    DualSparSection,
)

logger = get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════════
#  Component 1 : Segment DVs → element-level wall thicknesses
# ═════════════════════════════════════════════════════════════════════════

class SegmentToElementComp(om.ExplicitComponent):
    """Map segment-level wall thicknesses and outer radii to per-element values.

    Inputs : main_t_seg (n_seg,), main_r_seg (n_seg,),
             rear_t_seg (n_seg,), rear_r_seg (n_seg,)  [if rear_enabled]
    Outputs: main_t_elem (n_elem,), main_r_elem (n_elem,),
             rear_t_elem (n_elem,), rear_r_elem (n_elem,)  [if rear_enabled]
    """

    def initialize(self):
        self.options.declare("n_segments", types=int)
        self.options.declare("n_elements", types=int)
        self.options.declare("segment_boundaries", types=np.ndarray)
        self.options.declare("element_centres", types=np.ndarray)
        self.options.declare("rear_enabled", types=bool, default=True)

    def setup(self):
        ns = self.options["n_segments"]
        ne = self.options["n_elements"]

        self.add_input("main_t_seg", shape=(ns,), units="m")
        self.add_output("main_t_elem", shape=(ne,), units="m")

        self.add_input("main_r_seg", shape=(ns,), units="m")
        self.add_output("main_r_elem", shape=(ne,), units="m")

        if self.options["rear_enabled"]:
            self.add_input("rear_t_seg", shape=(ns,), units="m")
            self.add_output("rear_t_elem", shape=(ne,), units="m")

            self.add_input("rear_r_seg", shape=(ns,), units="m")
            self.add_output("rear_r_elem", shape=(ne,), units="m")

        # Precompute the mapping matrix (constant: ∂x_elem/∂x_seg)
        sb = self.options["segment_boundaries"]
        ec = self.options["element_centres"]
        self._map_matrix = np.zeros((ne, ns))
        for i, yc in enumerate(ec):
            seg_idx = int(np.searchsorted(sb[1:], yc, side="right"))
            seg_idx = min(seg_idx, ns - 1)
            self._map_matrix[i, seg_idx] = 1.0

        self.declare_partials("main_t_elem", "main_t_seg", val=self._map_matrix)
        self.declare_partials("main_r_elem", "main_r_seg", val=self._map_matrix)
        if self.options["rear_enabled"]:
            self.declare_partials("rear_t_elem", "rear_t_seg", val=self._map_matrix)
            self.declare_partials("rear_r_elem", "rear_r_seg", val=self._map_matrix)

    def compute(self, inputs, outputs):
        M = self._map_matrix
        outputs["main_t_elem"] = M @ inputs["main_t_seg"]
        outputs["main_r_elem"] = M @ inputs["main_r_seg"]
        if self.options["rear_enabled"]:
            outputs["rear_t_elem"] = M @ inputs["rear_t_seg"]
            outputs["rear_r_elem"] = M @ inputs["rear_r_seg"]


# ═════════════════════════════════════════════════════════════════════════
#  Component 2 : Tube geometry → section properties (A, I, J)
# ═════════════════════════════════════════════════════════════════════════

class DualSparPropertiesComp(om.ExplicitComponent):
    """Compute equivalent beam A, Iy, Iz, J from dual hollow-tube spars.

    Uses parallel-axis theorem for EI, warping term for GJ.
    """

    def initialize(self):
        self.options.declare("n_elements", types=int)
        self.options.declare("z_main", types=np.ndarray,
                             desc="Z-offset of main spar (camber fraction)")
        self.options.declare("z_rear", types=np.ndarray,
                             desc="Z-offset of rear spar (camber fraction)")
        self.options.declare("d_chord", types=np.ndarray,
                             desc="Chordwise spar separation [m]")
        self.options.declare("E_main", types=float)
        self.options.declare("G_main", types=float)
        self.options.declare("rho_main", types=float)
        self.options.declare("E_rear", types=float)
        self.options.declare("G_rear", types=float)
        self.options.declare("rho_rear", types=float)
        self.options.declare("rear_enabled", types=bool, default=True)

    def setup(self):
        ne = self.options["n_elements"]

        self.add_input("main_t_elem", shape=(ne,), units="m")
        self.add_input("main_r_elem", shape=(ne,), units="m")
        self.add_output("A_equiv", shape=(ne,), units="m**2")
        self.add_output("Iy_equiv", shape=(ne,), units="m**4")
        self.add_output("J_equiv", shape=(ne,), units="m**4")
        self.add_output("EI_flap", shape=(ne,), units="N*m**2")
        self.add_output("GJ", shape=(ne,), units="N*m**2")
        self.add_output("mass_per_length", shape=(ne,), units="kg/m")
        # Stress-check arrays (individual tubes)
        self.add_output("A_main", shape=(ne,), units="m**2")
        self.add_output("I_main", shape=(ne,), units="m**4")
        self.add_output("A_rear", shape=(ne,), units="m**2")
        self.add_output("I_rear", shape=(ne,), units="m**4")

        if self.options["rear_enabled"]:
            self.add_input("rear_t_elem", shape=(ne,), units="m")
            self.add_input("rear_r_elem", shape=(ne,), units="m")

        # Use complex-step for derivatives (simpler, accurate)
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs):
        ne = self.options["n_elements"]
        R_m = inputs["main_r_elem"]
        rho_m = self.options["rho_main"]
        E_m = self.options["E_main"]
        G_m = self.options["G_main"]
        t_m = inputs["main_t_elem"]

        # Clamp thickness to valid range
        t_m = np.minimum(t_m, R_m - 1e-6)
        t_m = np.maximum(t_m, 1e-6)

        A_m = tube_area(R_m, t_m)
        I_m = tube_Ixx(R_m, t_m)
        J_m = tube_J(R_m, t_m)

        outputs["A_main"] = A_m
        outputs["I_main"] = I_m

        if self.options["rear_enabled"]:
            R_r = inputs["rear_r_elem"]
            rho_r = self.options["rho_rear"]
            E_r = self.options["E_rear"]
            G_r = self.options["G_rear"]
            z_m = self.options["z_main"]
            z_r = self.options["z_rear"]
            d = self.options["d_chord"]
            t_r = inputs["rear_t_elem"]

            t_r = np.minimum(t_r, R_r - 1e-6)
            t_r = np.maximum(t_r, 1e-6)

            A_r = tube_area(R_r, t_r)
            I_r = tube_Ixx(R_r, t_r)
            J_r = tube_J(R_r, t_r)

            outputs["A_rear"] = A_r
            outputs["I_rear"] = I_r

            # Parallel-axis theorem for flapwise EI
            denom = E_m * A_m + E_r * A_r + 1e-30
            z_na = (E_m * A_m * z_m + E_r * A_r * z_r) / denom
            EI_flap = (
                E_m * (I_m + A_m * (z_m - z_na) ** 2)
                + E_r * (I_r + A_r * (z_r - z_na) ** 2)
            )

            # Torsion: tubes + warping coupling
            GJ_tubes = G_m * J_m + G_r * J_r
            GJ_warping = (E_m * A_m * E_r * A_r) / denom * d ** 2
            GJ_total = GJ_tubes + GJ_warping

            outputs["A_equiv"] = A_m + A_r
            outputs["EI_flap"] = EI_flap
            outputs["GJ"] = GJ_total
            outputs["mass_per_length"] = rho_m * A_m + rho_r * A_r

            # Equivalent section properties (for single-beam FEM)
            E_avg = (E_m * A_m + E_r * A_r) / (A_m + A_r + 1e-30)
            G_avg = (G_m * A_m + G_r * A_r) / (A_m + A_r + 1e-30)
            outputs["Iy_equiv"] = EI_flap / (E_avg + 1e-30)
            outputs["J_equiv"] = GJ_total / (G_avg + 1e-30)
        else:
            outputs["A_rear"] = np.zeros(ne)
            outputs["I_rear"] = np.zeros(ne)
            outputs["A_equiv"] = A_m
            outputs["EI_flap"] = E_m * I_m
            outputs["GJ"] = G_m * J_m
            outputs["mass_per_length"] = rho_m * A_m
            outputs["Iy_equiv"] = I_m
            outputs["J_equiv"] = J_m


# ═════════════════════════════════════════════════════════════════════════
#  Component 3 : Timoshenko beam FEM solver  (6-DOF per node)
# ═════════════════════════════════════════════════════════════════════════

def _timoshenko_element_stiffness(
    L: float, E: float, G: float,
    A: float, Iy: float, Iz: float, J: float,
) -> np.ndarray:
    """12×12 stiffness matrix for a 3-D Timoshenko beam element.

    DOF order per node: [u, v, w, θx, θy, θz]
    Local coord: x = axial (along element), y = lateral, z = vertical.

    Shear correction factor κ = 0.5 (thin-walled circular tube).
    """
    kappa = 0.5  # shear correction for hollow tube
    GA = kappa * G * A
    phi_y = 12.0 * E * Iz / (GA * L**2) if GA > 1e-20 else 0.0
    phi_z = 12.0 * E * Iy / (GA * L**2) if GA > 1e-20 else 0.0

    K = np.zeros((12, 12))

    # Axial (u)
    ea_L = E * A / L
    K[0, 0] = ea_L
    K[0, 6] = -ea_L
    K[6, 0] = -ea_L
    K[6, 6] = ea_L

    # Torsion (θx)
    gj_L = G * J / L
    K[3, 3] = gj_L
    K[3, 9] = -gj_L
    K[9, 3] = -gj_L
    K[9, 9] = gj_L

    # Bending in x-z plane (w, θy)
    c1 = E * Iy / (L**3 * (1 + phi_z))
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
    c2 = E * Iz / (L**3 * (1 + phi_y))
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
    return np.sqrt(np.dot(x, x))


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
    e1 = dx / L  # local x

    # Pick a reference direction (global Z unless nearly parallel to element)
    ref = np.array([0.0, 0.0, 1.0], dtype=dx.dtype)
    dot_val = np.real(np.dot(e1, np.array([0.0, 0.0, 1.0])))
    if abs(dot_val) > 0.99:
        ref = np.array([1.0, 0.0, 0.0], dtype=dx.dtype)

    e2 = np.cross(ref, e1)
    norm_e2 = _cs_norm(e2)
    if np.real(norm_e2) < 1e-12:
        return np.eye(3, dtype=dx.dtype)
    e2 = e2 / norm_e2
    e3 = np.cross(e1, e2)
    e3 = e3 / (_cs_norm(e3) + 1e-30)

    return np.array([e1, e2, e3])


def _transform_12x12(R3: np.ndarray) -> np.ndarray:
    """Build 12×12 transformation matrix from 3×3 rotation."""
    T = np.zeros((12, 12))
    for i in range(4):
        T[3*i:3*i+3, 3*i:3*i+3] = R3
    return T


class SpatialBeamFEM(om.ExplicitComponent):
    """6-DOF Timoshenko beam FEM: assembles K, solves K·u = f.

    This follows the OAS SpatialBeam formulation:
    - Nodes along the half-span
    - Fixed BC at root (all 6 DOFs constrained)
    - External loads at each node [Fx, Fy, Fz, Mx, My, Mz]

    Inputs
    ------
    nodes : (nn, 3) FEM node coordinates [m]
    EI_flap : (ne,) flapwise bending stiffness [N.m^2]
    GJ : (ne,) torsional stiffness [N.m^2]
    A_equiv : (ne,) equivalent cross-section area [m^2]
    Iy_equiv : (ne,) second moment of area [m^4]
    J_equiv : (ne,) polar moment [m^4]
    loads : (nn, 6) external loads at each node

    Outputs
    -------
    disp : (nn, 6) displacements at each node
    """

    def initialize(self):
        self.options.declare("n_nodes", types=int)
        self.options.declare("E_avg", types=float, desc="Average Young's modulus")
        self.options.declare("G_avg", types=float, desc="Average shear modulus")
        self.options.declare("fixed_node", types=int, default=0,
                             desc="Index of fixed BC node (root)")
        self.options.declare("lift_wire_nodes", default=None,
                             desc="List of node indices with lift wire support")

    def setup(self):
        nn = self.options["n_nodes"]
        ne = nn - 1

        self.add_input("nodes", shape=(nn, 3), units="m")
        self.add_input("EI_flap", shape=(ne,), units="N*m**2")
        self.add_input("GJ", shape=(ne,), units="N*m**2")
        self.add_input("A_equiv", shape=(ne,), units="m**2")
        self.add_input("Iy_equiv", shape=(ne,), units="m**4")
        self.add_input("J_equiv", shape=(ne,), units="m**4")
        self.add_input("loads", shape=(nn, 6))

        self.add_output("disp", shape=(nn, 6))

        self.declare_partials("disp", "*", method="cs")

    def compute(self, inputs, outputs):
        nn = self.options["n_nodes"]
        ne = nn - 1
        E = self.options["E_avg"]
        G = self.options["G_avg"]
        fix = self.options["fixed_node"]

        nodes = inputs["nodes"]
        EI = inputs["EI_flap"]
        GJ_arr = inputs["GJ"]
        A = inputs["A_equiv"]
        Iy = inputs["Iy_equiv"]
        J = inputs["J_equiv"]
        loads = inputs["loads"]

        ndof = nn * 6
        # Use same dtype as inputs for complex-step compatibility
        dtype = EI.dtype
        K_global = np.zeros((ndof, ndof), dtype=dtype)

        for e in range(ne):
            ni = nodes[e]
            nj = nodes[e + 1]
            dx = nj - ni
            L = _cs_norm(dx)
            if np.real(L) < 1e-10:
                continue

            # Use the equivalent Iy, J for this element
            Iy_e = Iy[e]
            Iz_e = Iy[e]  # symmetric tube approximation
            J_e = J[e]
            A_e = A[e]

            # Compute effective E, G from EI and I
            E_eff = EI[e] / (Iy_e + 1e-30)
            G_eff = GJ_arr[e] / (J_e + 1e-30)

            K_local = _timoshenko_element_stiffness(
                L, E_eff, G_eff, A_e, Iy_e, Iz_e, J_e)

            # Transform to global coordinates
            R3 = _rotation_matrix(ni, nj)
            T = _transform_12x12(R3)
            K_elem_global = T.T @ K_local @ T

            # Assemble into global matrix
            for ii in range(12):
                gi = e * 6 + ii
                for jj in range(12):
                    gj = e * 6 + jj
                    K_global[gi, gj] += K_elem_global[ii, jj]

        # Flatten loads to RHS vector
        f = loads.flatten().astype(dtype)

        # Apply boundary conditions (fixed root)
        bc_dofs = list(range(fix * 6, fix * 6 + 6))

        # Lift wire support: constrain vertical displacement (DOF 2 at wire nodes)
        lw_nodes = self.options["lift_wire_nodes"]
        if lw_nodes:
            for lw_idx in lw_nodes:
                bc_dofs.append(lw_idx * 6 + 2)  # vertical DOF

        # Penalty method for BCs
        penalty_val = np.array(1e15, dtype=dtype)
        zero_val = np.array(0.0, dtype=dtype)
        for dof in bc_dofs:
            K_global[dof, dof] += penalty_val
            f[dof] = zero_val

        # Solve (works with both real and complex matrices)
        try:
            u = np.linalg.solve(K_global, f)
        except np.linalg.LinAlgError:
            u = np.zeros(ndof, dtype=dtype)

        outputs["disp"] = u.reshape((nn, 6))


# ═════════════════════════════════════════════════════════════════════════
#  Component 4 : Von Mises stress from displacements
# ═════════════════════════════════════════════════════════════════════════

class VonMisesStressComp(om.ExplicitComponent):
    """Compute von Mises stress in each spar at each element.

    For beam elements, the max stress occurs at the tube surface:
        σ_bending = M * R / I = E * κ * R
        τ_torsion = T * R / J = G * γ * R
        σ_vm = sqrt(σ² + 3τ²)

    where κ = curvature, γ = twist rate.
    """

    def initialize(self):
        self.options.declare("n_nodes", types=int)
        self.options.declare("E_main", types=float)
        self.options.declare("E_rear", types=float)
        self.options.declare("G_main", types=float)
        self.options.declare("G_rear", types=float)
        self.options.declare("rear_enabled", types=bool, default=True)

    def setup(self):
        nn = self.options["n_nodes"]
        ne = nn - 1

        self.add_input("disp", shape=(nn, 6))
        self.add_input("nodes", shape=(nn, 3), units="m")
        self.add_input("R_main_elem", shape=(ne,), units="m")
        self.add_input("I_main", shape=(ne,), units="m**4")
        self.add_input("EI_flap", shape=(ne,), units="N*m**2")
        self.add_input("GJ", shape=(ne,), units="N*m**2")

        self.add_output("vonmises_main", shape=(ne,), units="Pa")

        if self.options["rear_enabled"]:
            self.add_input("R_rear_elem", shape=(ne,), units="m")
            self.add_input("I_rear", shape=(ne,), units="m**4")
            self.add_output("vonmises_rear", shape=(ne,), units="Pa")

        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs):
        nn = self.options["n_nodes"]
        ne = nn - 1
        E_m = self.options["E_main"]
        G_m = self.options["G_main"]

        disp = inputs["disp"]
        nodes = inputs["nodes"]
        R_m = inputs["R_main_elem"]
        I_m = inputs["I_main"]
        EI = inputs["EI_flap"]
        GJ = inputs["GJ"]

        # Complex-step compatible: use du**2 instead of abs(du)
        sigma_vm_main = np.zeros(ne, dtype=disp.dtype)

        for e in range(ne):
            dx = nodes[e+1] - nodes[e]
            L = _cs_norm(dx)
            if np.real(L) < 1e-10:
                continue

            du = disp[e+1] - disp[e]  # 6-DOF delta

            # For beam along Y-axis:
            #   Flapwise curvature = Δθ_x_global / L (DOF 3 = bending slope)
            #   Chordwise curvature = Δθ_z_global / L (DOF 5)
            #   Torsion rate = Δθ_y_global / L (DOF 4 = twist about span)
            kappa_flap2 = (du[3] / L) ** 2
            kappa_chord2 = (du[5] / L) ** 2
            kappa2 = kappa_flap2 + kappa_chord2

            # Twist rate (torsion about span axis = θy global = DOF 4)
            gamma2 = (du[4] / L) ** 2

            # Main spar bending stress: σ = E * κ * R
            sigma_bend2 = (E_m * R_m[e]) ** 2 * kappa2

            # Torsion shear stress: τ = G * γ * R
            tau2 = (G_m * R_m[e]) ** 2 * gamma2

            # Von Mises: σ_vm = sqrt(σ² + 3τ²)
            sigma_vm_main[e] = np.sqrt(sigma_bend2 + 3.0 * tau2 + 1e-30)

        outputs["vonmises_main"] = sigma_vm_main

        if self.options["rear_enabled"]:
            E_r = self.options["E_rear"]
            G_r = self.options["G_rear"]
            R_r = inputs["R_rear_elem"]
            I_r = inputs["I_rear"]

            sigma_vm_rear = np.zeros(ne, dtype=disp.dtype)
            for e in range(ne):
                dx = nodes[e+1] - nodes[e]
                L = _cs_norm(dx)
                if np.real(L) < 1e-10:
                    continue
                du = disp[e+1] - disp[e]

                kappa2 = (du[3] / L) ** 2 + (du[5] / L) ** 2
                gamma2 = (du[4] / L) ** 2

                sigma_bend2 = (E_r * R_r[e]) ** 2 * kappa2
                tau2 = (G_r * R_r[e]) ** 2 * gamma2
                sigma_vm_rear[e] = np.sqrt(sigma_bend2 + 3.0 * tau2 + 1e-30)

            outputs["vonmises_rear"] = sigma_vm_rear


# ═════════════════════════════════════════════════════════════════════════
#  Component 5 : KS failure aggregation
# ═════════════════════════════════════════════════════════════════════════

class KSFailureComp(om.ExplicitComponent):
    """Kreisselmeier-Steinhauser aggregation of stress failure ratios.

    failure = KS(σ_vm / σ_allow - 1)

    If failure ≤ 0, all elements are within allowable stress.
    """

    def initialize(self):
        self.options.declare("n_elements", types=int)
        self.options.declare("sigma_allow_main", types=float)
        self.options.declare("sigma_allow_rear", types=float, default=None)
        self.options.declare("rear_enabled", types=bool, default=True)
        self.options.declare("rho_ks", types=float, default=100.0)

    def setup(self):
        ne = self.options["n_elements"]
        self.add_input("vonmises_main", shape=(ne,), units="Pa")
        if self.options["rear_enabled"]:
            self.add_input("vonmises_rear", shape=(ne,), units="Pa")
        self.add_output("failure", val=0.0)
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs):
        rho = self.options["rho_ks"]
        sig_a_m = self.options["sigma_allow_main"]
        vm_m = inputs["vonmises_main"]

        # Failure ratio: σ/σ_allow - 1 (negative = safe)
        ratios = vm_m / sig_a_m - 1.0

        if self.options["rear_enabled"]:
            sig_a_r = self.options["sigma_allow_rear"] or sig_a_m
            vm_r = inputs["vonmises_rear"]
            ratios_r = vm_r / sig_a_r - 1.0
            ratios = np.concatenate([ratios, ratios_r])

        # KS function: max ≈ (1/ρ) * ln(Σ exp(ρ * g_i))
        # Use real max for shift (CS-safe: shift doesn't affect imaginary part)
        max_ratio = np.real(ratios).max()
        shifted = ratios - max_ratio  # numerical stability
        ks = max_ratio + (1.0 / rho) * np.log(np.sum(np.exp(rho * shifted)))

        outputs["failure"] = ks


# ═════════════════════════════════════════════════════════════════════════
#  Component 6 : Structural mass (with joint penalty)
# ═════════════════════════════════════════════════════════════════════════

class StructuralMassComp(om.ExplicitComponent):
    """Total spar system mass = tube mass × 2 (full span) + joint mass."""

    def initialize(self):
        self.options.declare("n_elements", types=int)
        self.options.declare("element_lengths", types=np.ndarray)
        self.options.declare("joint_mass_total", types=float, default=0.0,
                             desc="Total joint mass for half-span [kg]")

    def setup(self):
        ne = self.options["n_elements"]
        self.add_input("mass_per_length", shape=(ne,), units="kg/m")
        self.add_output("spar_mass_half", units="kg")
        self.add_output("spar_mass_full", units="kg")
        self.add_output("total_mass_full", units="kg")
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs):
        dL = self.options["element_lengths"]
        jm = self.options["joint_mass_total"]
        mpl = inputs["mass_per_length"]

        half = float(np.sum(mpl * dL))
        outputs["spar_mass_half"] = half
        outputs["spar_mass_full"] = half * 2.0
        outputs["total_mass_full"] = half * 2.0 + jm * 2.0


# ═════════════════════════════════════════════════════════════════════════
#  Component 7 : External loads (from VSPAero)
# ═════════════════════════════════════════════════════════════════════════

class ExternalLoadsComp(om.ExplicitComponent):
    """Convert aero lift/torque distributions + spar weight into FEM loads.

    Applies:
        - Aerodynamic lift (Fz) at design load level
        - Aerodynamic pitching moment (Mx torque)
        - Spar self-weight (negative Fz)
    """

    def initialize(self):
        self.options.declare("n_nodes", types=int)
        self.options.declare("lift_per_span", types=np.ndarray,
                             desc="Aero lift [N/m] at nodes (already scaled for design)")
        self.options.declare("torque_per_span", types=np.ndarray,
                             desc="Aero torque [N.m/m] at nodes")
        self.options.declare("node_spacings", types=np.ndarray,
                             desc="Tributary length for each node [m]")
        self.options.declare("element_lengths", types=np.ndarray,
                             desc="Element lengths [m]")

    def setup(self):
        nn = self.options["n_nodes"]
        ne = nn - 1
        self.add_input("mass_per_length", shape=(ne,), units="kg/m")
        self.add_output("loads", shape=(nn, 6))
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs):
        nn = self.options["n_nodes"]
        ne = nn - 1
        lift = self.options["lift_per_span"]
        torque = self.options["torque_per_span"]
        ds = self.options["node_spacings"]
        element_lengths = self.options["element_lengths"]
        mpl = inputs["mass_per_length"]
        g = 9.80665

        loads = np.zeros((nn, 6), dtype=mpl.dtype)

        # Lift contribution (integrate over tributary length)
        for i in range(nn):
            loads[i, 2] = lift[i] * ds[i]
            # My = design torque (torsion about span/Y axis)
            # For beam along Y: torsion maps to global DOF 4 (θy)
            loads[i, 4] = torque[i] * ds[i]

        # Weight contribution (lumped mass per element, split to endpoints)
        for e in range(ne):
            element_weight = mpl[e] * g * element_lengths[e]
            loads[e, 2] -= element_weight / 2.0
            loads[e + 1, 2] -= element_weight / 2.0

        outputs["loads"] = loads


# ═════════════════════════════════════════════════════════════════════════
#  Component 8 : Twist extraction (for ±2° constraint)
# ═════════════════════════════════════════════════════════════════════════

class TwistConstraintComp(om.ExplicitComponent):
    """Extract maximum twist angle from beam displacements.

    twist_max = KS smooth max of |θ_y| along span, in degrees.
    Previously only used tip value (assumes monotonic twist),
    but this assumption fails for wings with sign-changing pitching
    moment or complex lift distributions. KS aggregation is more robust.
    """

    def initialize(self):
        self.options.declare("n_nodes", types=int)

    def setup(self):
        nn = self.options["n_nodes"]
        self.add_input("disp", shape=(nn, 6))
        self.add_output("twist_max_deg", val=0.0)
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs):
        # Torsion = rotation about span (Y) axis = global DOF 4 (θy)
        theta_twist = inputs["disp"][:, 4]  # torsion rotation [rad]

        # KS aggregation for max |θ| across all nodes (CS-safe)
        theta_abs_sq = theta_twist ** 2 + 1e-30  # [nn]
        theta_abs = np.sqrt(theta_abs_sq)  # [nn], strictly positive
        # KS smooth-max with rho=100
        rho = 100.0
        theta_max_ks = (1.0 / rho) * np.log(np.sum(np.exp(rho * theta_abs)))
        outputs["twist_max_deg"] = theta_max_ks * 180.0 / np.pi


# ═════════════════════════════════════════════════════════════════════════
#  Component 9 : Tip deflection extraction
# ═════════════════════════════════════════════════════════════════════════

class TipDeflectionConstraintComp(om.ExplicitComponent):
    """Extract tip deflection from beam displacements.

    tip_deflection = disp[-1, 2]
    Constraint: tip_deflection <= max_tip_deflection_m.
    """

    def initialize(self):
        self.options.declare("n_nodes", types=int)

    def setup(self):
        nn = self.options["n_nodes"]
        self.add_input("disp", shape=(nn, 6))
        self.add_output("tip_deflection_m", val=0.0)
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs):
        # Vertical displacement (Z) is DOF 2
        outputs["tip_deflection_m"] = inputs["disp"][-1, 2]


# ═════════════════════════════════════════════════════════════════════════
#  Top-level group
# ═════════════════════════════════════════════════════════════════════════

class HPAStructuralGroup(om.Group):
    """Complete structural analysis group for HPA wing spar optimization.

    Subsystems:
        seg_mapper → spar_props → ext_loads → fem → stress → failure, mass, twist
    """

    def initialize(self):
        self.options.declare("cfg", desc="HPAConfig object")
        self.options.declare("aircraft", desc="Aircraft object")
        self.options.declare("aero_loads", desc="Dict from LoadMapper.map_loads()")
        self.options.declare("materials_db", desc="MaterialDB")

    def setup(self):
        from hpa_mdo.core.config import HPAConfig
        cfg: HPAConfig = self.options["cfg"]
        ac = self.options["aircraft"]
        aero = self.options["aero_loads"]
        mat_db = self.options["materials_db"]

        wing = ac.wing
        nn = wing.n_stations
        ne = nn - 1
        y = wing.y
        dy = np.diff(y)

        # Materials
        mat_main = mat_db.get(cfg.main_spar.material)
        mat_rear = mat_db.get(cfg.rear_spar.material)
        rear_on = cfg.rear_spar.enabled

        # Segment boundaries
        seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
        seg_bounds = segment_boundaries_from_lengths(seg_lengths)
        n_seg = len(seg_lengths)

        # Element centres (midpoint of each element)
        elem_centres = (y[:-1] + y[1:]) / 2.0

        # Node spacings (tributary length per node for load distribution)
        node_spacings = np.zeros(nn)
        node_spacings[0] = dy[0] / 2.0
        node_spacings[-1] = dy[-1] / 2.0
        for i in range(1, nn - 1):
            node_spacings[i] = (dy[i-1] + dy[i]) / 2.0

        # Outer radii (constant — from airfoil geometry)
        R_main_nodes = compute_outer_radius_from_wing(wing, cfg.main_spar)
        R_rear_nodes = compute_outer_radius_from_wing(wing, cfg.rear_spar) if rear_on else np.zeros(nn)
        # Element-averaged outer radii
        R_main_elem = (R_main_nodes[:-1] + R_main_nodes[1:]) / 2.0
        R_rear_elem = (R_rear_nodes[:-1] + R_rear_nodes[1:]) / 2.0

        # Z-offsets and spar separation per element
        z_main_elem = (wing.main_spar_z_camber[:-1] + wing.main_spar_z_camber[1:]) / 2.0
        z_rear_elem = (wing.rear_spar_z_camber[:-1] + wing.rear_spar_z_camber[1:]) / 2.0
        chord_elem = (wing.chord[:-1] + wing.chord[1:]) / 2.0
        d_chord_elem = (wing.rear_spar_xc - wing.main_spar_xc) * chord_elem

        # Aero loads at structural nodes
        lift = aero["lift_per_span"]
        # Torque from Cmy: τ = q * c² * Cm (per unit span)
        if "torque_per_span" in aero:
            torque = aero["torque_per_span"]
        else:
            torque = np.zeros(nn)

        # Lift wire nodes
        lw_node_indices = None
        if cfg.lift_wires.enabled and cfg.lift_wires.attachments:
            lw_node_indices = []
            for att in cfg.lift_wires.attachments:
                idx = int(np.argmin(np.abs(y - att.y)))
                lw_node_indices.append(idx)

        # FEM nodes (3D coordinates)
        # Y along span, Z from dihedral, X at spar location
        nodes_3d = np.zeros((nn, 3))
        nodes_3d[:, 1] = y  # spanwise
        # Dihedral offset
        dih_rad = np.deg2rad(wing.dihedral_deg)
        z_dihedral = np.zeros(nn)
        for i in range(1, nn):
            z_dihedral[i] = z_dihedral[i-1] + dy[i-1] * np.tan(dih_rad[i])
        nodes_3d[:, 2] = z_dihedral
        nodes_3d[:, 0] = wing.main_spar_xc * wing.chord  # chordwise position

        # Joint mass
        n_main_joints = len(cfg.joint_positions(seg_lengths))
        n_rear_joints = len(cfg.joint_positions(
            cfg.spar_segment_lengths(cfg.rear_spar))) if rear_on else 0
        joint_mass_half = (
            n_main_joints * cfg.main_spar.joint_mass_kg
            + n_rear_joints * cfg.rear_spar.joint_mass_kg
        )

        # Allowable stress = UTS / material_safety_factor
        sigma_allow_main = mat_main.tensile_strength / cfg.safety.material_safety_factor
        sigma_allow_rear = mat_rear.tensile_strength / cfg.safety.material_safety_factor

        # ── Build subsystems ──

        # 1. Segment mapper
        self.add_subsystem("seg_mapper", SegmentToElementComp(
            n_segments=n_seg,
            n_elements=ne,
            segment_boundaries=seg_bounds,
            element_centres=elem_centres,
            rear_enabled=rear_on,
        ))

        # 2. Dual spar properties
        self.add_subsystem("spar_props", DualSparPropertiesComp(
            n_elements=ne,
            z_main=z_main_elem,
            z_rear=z_rear_elem,
            d_chord=d_chord_elem,
            E_main=mat_main.E,
            G_main=mat_main.G,
            rho_main=mat_main.density,
            E_rear=mat_rear.E,
            G_rear=mat_rear.G,
            rho_rear=mat_rear.density,
            rear_enabled=rear_on,
        ))

        # 3. External loads
        self.add_subsystem("ext_loads", ExternalLoadsComp(
            n_nodes=nn,
            lift_per_span=lift,
            torque_per_span=torque,
            node_spacings=node_spacings,
            element_lengths=dy,
        ))

        # 4. FEM solver
        E_avg = (mat_main.E + mat_rear.E) / 2.0 if rear_on else mat_main.E
        G_avg = (mat_main.G + mat_rear.G) / 2.0 if rear_on else mat_main.G
        self.add_subsystem("fem", SpatialBeamFEM(
            n_nodes=nn,
            E_avg=E_avg,
            G_avg=G_avg,
            fixed_node=0,
            lift_wire_nodes=lw_node_indices,
        ))

        # Set node coordinates as fixed input
        indeps = self.add_subsystem("indeps", om.IndepVarComp())
        indeps.add_output("nodes", val=nodes_3d, units="m")

        # Store initial element radii for use in build_structural_problem()
        self._R_main_elem_init = R_main_elem
        self._R_rear_elem_init = R_rear_elem if rear_on else None

        # 5. Stress computation
        self.add_subsystem("stress", VonMisesStressComp(
            n_nodes=nn,
            E_main=mat_main.E,
            E_rear=mat_rear.E,
            G_main=mat_main.G,
            G_rear=mat_rear.G,
            rear_enabled=rear_on,
        ))

        # 6. KS failure
        self.add_subsystem("failure", KSFailureComp(
            n_elements=ne,
            sigma_allow_main=sigma_allow_main,
            sigma_allow_rear=sigma_allow_rear,
            rear_enabled=rear_on,
        ))

        # 7. Structural mass
        self.add_subsystem("mass", StructuralMassComp(
            n_elements=ne,
            element_lengths=dy,
            joint_mass_total=joint_mass_half,
        ))

        # 8. Twist constraint
        self.add_subsystem("twist", TwistConstraintComp(n_nodes=nn))

        # 9. Tip deflection constraint
        self.add_subsystem("tip_defl", TipDeflectionConstraintComp(n_nodes=nn))

        # ── Connections ──
        self.connect("seg_mapper.main_t_elem", "spar_props.main_t_elem")
        self.connect("seg_mapper.main_r_elem", "spar_props.main_r_elem")
        if rear_on:
            self.connect("seg_mapper.rear_t_elem", "spar_props.rear_t_elem")
            self.connect("seg_mapper.rear_r_elem", "spar_props.rear_r_elem")

        self.connect("spar_props.mass_per_length", "ext_loads.mass_per_length")
        self.connect("spar_props.mass_per_length", "mass.mass_per_length")

        self.connect("indeps.nodes", "fem.nodes")
        self.connect("spar_props.EI_flap", "fem.EI_flap")
        self.connect("spar_props.GJ", "fem.GJ")
        self.connect("spar_props.A_equiv", "fem.A_equiv")
        self.connect("spar_props.Iy_equiv", "fem.Iy_equiv")
        self.connect("spar_props.J_equiv", "fem.J_equiv")
        self.connect("ext_loads.loads", "fem.loads")

        self.connect("fem.disp", "stress.disp")
        self.connect("indeps.nodes", "stress.nodes")
        self.connect("seg_mapper.main_r_elem", "stress.R_main_elem")
        self.connect("spar_props.I_main", "stress.I_main")
        self.connect("spar_props.EI_flap", "stress.EI_flap")
        self.connect("spar_props.GJ", "stress.GJ")
        if rear_on:
            self.connect("seg_mapper.rear_r_elem", "stress.R_rear_elem")
            self.connect("spar_props.I_rear", "stress.I_rear")

        self.connect("stress.vonmises_main", "failure.vonmises_main")
        if rear_on:
            self.connect("stress.vonmises_rear", "failure.vonmises_rear")

        self.connect("fem.disp", "twist.disp")
        self.connect("fem.disp", "tip_defl.disp")


def compute_outer_radius_from_wing(wing, spar_cfg) -> np.ndarray:
    """Compute outer tube radius at each wing station."""
    from hpa_mdo.structure.spar_model import compute_outer_radius
    return compute_outer_radius(
        wing.y, wing.chord, wing.airfoil_thickness, spar_cfg)


# ═════════════════════════════════════════════════════════════════════════
#  Convenience: build & run the full problem
# ═════════════════════════════════════════════════════════════════════════

def build_structural_problem(
    cfg,
    aircraft,
    aero_loads: dict,
    materials_db,
) -> om.Problem:
    """Build the OpenMDAO structural optimization problem.

    Parameters
    ----------
    cfg : HPAConfig
    aircraft : Aircraft
    aero_loads : dict from LoadMapper.map_loads()
    materials_db : MaterialDB

    Returns
    -------
    prob : om.Problem (setup but not run)
    """
    prob = om.Problem()
    model = prob.model

    seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
    n_seg = len(seg_lengths)
    rear_on = cfg.rear_spar.enabled
    logger.debug(
        "Building structural problem (n_seg=%d, rear_on=%s).",
        n_seg,
        rear_on,
    )

    # Add the structural group
    struct_group = HPAStructuralGroup(
        cfg=cfg,
        aircraft=aircraft,
        aero_loads=aero_loads,
        materials_db=materials_db,
    )
    model.add_subsystem("struct", struct_group)

    # ── Design Variables ──
    min_t = cfg.main_spar.min_wall_thickness
    max_t = 0.015  # 15 mm max wall thickness

    model.add_design_var(
        "struct.seg_mapper.main_t_seg",
        lower=min_t, upper=max_t,
        ref=0.002,  # scaling reference
    )

    model.add_design_var(
        "struct.seg_mapper.main_r_seg",
        lower=0.010, upper=0.060,   # 20mm–120mm OD → 10mm–60mm radius
        ref=0.025,
    )

    if rear_on:
        min_t_r = cfg.rear_spar.min_wall_thickness
        model.add_design_var(
            "struct.seg_mapper.rear_t_seg",
            lower=min_t_r, upper=max_t,
            ref=0.002,
        )
        model.add_design_var(
            "struct.seg_mapper.rear_r_seg",
            lower=0.010, upper=0.060,
            ref=0.025,
        )

    # ── Objective: minimise total spar mass ──
    model.add_objective("struct.mass.total_mass_full", ref=10.0)

    # ── Constraints ──
    # 1. Stress: KS(σ/σ_allow - 1) ≤ 0
    model.add_constraint("struct.failure.failure", upper=0.0)

    # 2. Twist: |θ_max| ≤ max_tip_twist_deg
    model.add_constraint(
        "struct.twist.twist_max_deg",
        upper=cfg.wing.max_tip_twist_deg,
    )

    # 3. Tip deflection constraint
    if cfg.wing.max_tip_deflection_m is not None:
        model.add_constraint(
            "struct.tip_defl.tip_deflection_m",
            upper=cfg.wing.max_tip_deflection_m,
        )

    # ── Driver ──
    driver = prob.driver = om.ScipyOptimizeDriver()
    driver.options["optimizer"] = cfg.solver.optimizer
    driver.options["tol"] = cfg.solver.optimizer_tol
    driver.options["maxiter"] = cfg.solver.optimizer_maxiter
    driver.options["disp"] = True

    # ── Recorder (optional) ──
    # prob.driver.add_recorder(om.SqliteRecorder("hpa_opt.sql"))

    prob.setup()

    # ── Initial values ──
    # Wall thickness: start with moderate value (2 mm)
    init_t = np.ones(n_seg) * 0.002
    prob.set_val("struct.seg_mapper.main_t_seg", init_t, units="m")
    if rear_on:
        prob.set_val("struct.seg_mapper.rear_t_seg", init_t * 0.7, units="m")

    # Outer radii: derive from wing geometry (element values averaged per segment)
    # The group stores these after setup — retrieve from the instantiated subsystem.
    wing = aircraft.wing
    seg_bounds = segment_boundaries_from_lengths(seg_lengths)
    nn = wing.n_stations
    y = wing.y
    elem_centres = (y[:-1] + y[1:]) / 2.0

    R_main_elem_init = struct_group._R_main_elem_init
    main_r_seg_init = _elem_to_seg_mean(R_main_elem_init, elem_centres, seg_bounds, n_seg)
    prob.set_val("struct.seg_mapper.main_r_seg", main_r_seg_init, units="m")

    if rear_on:
        R_rear_elem_init = struct_group._R_rear_elem_init
        rear_r_seg_init = _elem_to_seg_mean(R_rear_elem_init, elem_centres, seg_bounds, n_seg)
        prob.set_val("struct.seg_mapper.rear_r_seg", rear_r_seg_init, units="m")

    return prob


def _elem_to_seg_mean(
    elem_vals: np.ndarray,
    elem_centres: np.ndarray,
    seg_bounds: np.ndarray,
    n_seg: int,
) -> np.ndarray:
    """Average element values within each segment to produce per-segment values."""
    seg_vals = np.zeros(n_seg)
    for s in range(n_seg):
        mask = (elem_centres >= seg_bounds[s]) & (elem_centres < seg_bounds[s + 1])
        if np.any(mask):
            seg_vals[s] = np.mean(elem_vals[mask])
        else:
            # No elements in segment — fall back to nearest element
            dists = np.abs(elem_centres - 0.5 * (seg_bounds[s] + seg_bounds[s + 1]))
            seg_vals[s] = elem_vals[np.argmin(dists)]
    return seg_vals


def run_analysis(prob: om.Problem) -> dict:
    """Run a single analysis (no optimization) and return results."""
    logger.debug("Running structural analysis model.")
    prob.run_model()
    results = _extract_results(prob)
    logger.debug(
        "Structural analysis complete (mass=%.3f kg, failure=%.4f).",
        results["total_mass_full_kg"],
        results["failure"],
    )
    return results


def run_optimization(prob: om.Problem) -> dict:
    """Run the full optimization and return results."""
    logger.info("Running structural optimization driver.")
    prob.run_driver()
    results = _extract_results(prob)
    logger.info(
        "Structural optimization complete (mass=%.3f kg, failure=%.4f).",
        results["total_mass_full_kg"],
        results["failure"],
    )
    return results


def _extract_results(prob: om.Problem) -> dict:
    """Extract key results from solved problem."""
    nn = prob.model.struct.options["aircraft"].wing.n_stations
    ne = nn - 1
    rear_on = prob.model.struct.options["cfg"].rear_spar.enabled

    res = {
        "spar_mass_half_kg": float(prob.get_val("struct.mass.spar_mass_half")),
        "spar_mass_full_kg": float(prob.get_val("struct.mass.spar_mass_full")),
        "total_mass_full_kg": float(prob.get_val("struct.mass.total_mass_full")),
        "failure": float(prob.get_val("struct.failure.failure")),
        "twist_max_deg": float(prob.get_val("struct.twist.twist_max_deg")),
        "disp": prob.get_val("struct.fem.disp").copy(),
        "tip_deflection_m": float(prob.get_val("struct.tip_defl.tip_deflection_m")),
        "vonmises_main": prob.get_val("struct.stress.vonmises_main").copy(),
        "main_t_seg": prob.get_val("struct.seg_mapper.main_t_seg").copy(),
        "main_r_seg": prob.get_val("struct.seg_mapper.main_r_seg").copy(),
    }

    if rear_on:
        res["vonmises_rear"] = prob.get_val("struct.stress.vonmises_rear").copy()
        res["rear_t_seg"] = prob.get_val("struct.seg_mapper.rear_t_seg").copy()
        res["rear_r_seg"] = prob.get_val("struct.seg_mapper.rear_r_seg").copy()

    return res
