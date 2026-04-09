"""Stress, failure, mass, twist, and tip-deflection constraint components."""
from __future__ import annotations

import numpy as np
import openmdao.api as om

from hpa_mdo.structure.fem.elements import _cs_norm, _rotation_matrix
from hpa_mdo.structure.spar_model import tube_area


class VonMisesStressComp(om.ExplicitComponent):
    """Compute von Mises stress in each spar at each element.

    For beam elements, the max stress occurs at the tube surface:
        σ_bending = E * κ * (R + |d_z|)  (dual-spar equivalent-beam recovery)
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
        self.options.declare("z_main", default=None, allow_none=True)
        self.options.declare("z_rear", default=None, allow_none=True)
        self.options.declare("rear_enabled", types=bool, default=True)
        self.options.declare(
            "wire_precompression",
            default=None,
            allow_none=True,
            desc="(ne,) axial pre-compression [N] from lift-wire reaction. None disables pre-stress.",
        )

    def setup(self):
        nn = self.options["n_nodes"]
        ne = nn - 1

        self.add_input("disp", shape=(nn, 6))
        self.add_input("nodes", shape=(nn, 3), units="m")
        self.add_input("R_main_elem", shape=(ne,), units="m")
        self.add_input("main_t_elem", shape=(ne,), units="m")
        self.add_input("I_main", shape=(ne,), units="m**4")
        self.add_input("EI_flap", shape=(ne,), units="N*m**2")
        self.add_input("GJ", shape=(ne,), units="N*m**2")

        self.add_output("vonmises_main", shape=(ne,), units="Pa")

        if self.options["rear_enabled"]:
            self.add_input("R_rear_elem", shape=(ne,), units="m")
            self.add_input("rear_t_elem", shape=(ne,), units="m")
            self.add_input("I_rear", shape=(ne,), units="m**4")
            self.add_output("vonmises_rear", shape=(ne,), units="Pa")

        disp_rows = []
        disp_cols = []
        for e in range(ne):
            for node_idx in (e, e + 1):
                base = node_idx * 6
                for dof in range(6):
                    disp_rows.append(e)
                    disp_cols.append(base + dof)
        self._disp_partial_rows = np.asarray(disp_rows, dtype=int)
        self._disp_partial_cols = np.asarray(disp_cols, dtype=int)

        self.declare_partials(
            "vonmises_main",
            "disp",
            rows=self._disp_partial_rows,
            cols=self._disp_partial_cols,
            method="cs",
        )
        self.declare_partials(
            "vonmises_main",
            ["nodes", "R_main_elem", "main_t_elem", "I_main", "EI_flap", "GJ"],
            method="cs",
        )
        if self.options["rear_enabled"]:
            self.declare_partials(
                "vonmises_rear",
                "disp",
                rows=self._disp_partial_rows,
                cols=self._disp_partial_cols,
                method="cs",
            )
            self.declare_partials(
                "vonmises_rear",
                ["nodes", "R_rear_elem", "rear_t_elem", "I_rear"],
                method="cs",
            )

    def compute(self, inputs, outputs):
        nn = self.options["n_nodes"]
        ne = nn - 1
        E_m = self.options["E_main"]
        G_m = self.options["G_main"]

        disp = inputs["disp"]
        nodes = inputs["nodes"]
        R_m = inputs["R_main_elem"]
        t_m = inputs["main_t_elem"]
        z_m = self.options["z_main"]
        if z_m is None:
            z_m = np.zeros(ne)
        z_m = np.asarray(z_m)
        A_m = tube_area(R_m, t_m)

        wire_precomp_opt = self.options["wire_precompression"]
        if wire_precomp_opt is None:
            wire_precomp = np.zeros(ne, dtype=disp.dtype)
        else:
            wire_precomp = np.asarray(wire_precomp_opt, dtype=disp.dtype)
            if wire_precomp.shape != (ne,):
                raise om.AnalysisError(
                    f"wire_precompression must have shape ({ne},), got {wire_precomp.shape}."
                )

        # Complex-step compatible: use du**2 instead of abs(du)
        sigma_vm_main = np.zeros(ne, dtype=disp.dtype)
        kappa2_elem = np.zeros(ne, dtype=disp.dtype)
        gamma2_elem = np.zeros(ne, dtype=disp.dtype)

        if self.options["rear_enabled"]:
            E_r = self.options["E_rear"]
            R_r = inputs["R_rear_elem"]
            t_r = inputs["rear_t_elem"]
            z_r = self.options["z_rear"]
            if z_r is None:
                z_r = np.zeros(ne)
            z_r = np.asarray(z_r)

            A_r = tube_area(R_r, t_r)
            denom = E_m * A_m + E_r * A_r + 1e-30
            z_na = (E_m * A_m * z_m + E_r * A_r * z_r) / denom
            dz_main_abs = np.sqrt((z_m - z_na) ** 2 + 1e-30)
            dz_rear_abs = np.sqrt((z_r - z_na) ** 2 + 1e-30)
        else:
            R_r = None
            dz_main_abs = np.zeros(ne, dtype=disp.dtype)
            dz_rear_abs = None

        for e in range(ne):
            dx = nodes[e+1] - nodes[e]
            L = _cs_norm(dx)
            if np.real(L) < 1e-10:
                continue

            du = disp[e+1] - disp[e]  # 6-DOF delta
            R3 = _rotation_matrix(nodes[e], nodes[e + 1])
            dtheta_local = R3 @ du[3:6]
            # Local beam formulation:
            #   torsion rate = d(theta_x_local)/dx
            #   bending curvatures use theta_y_local, theta_z_local gradients.
            kappa2 = (dtheta_local[1] / L) ** 2 + (dtheta_local[2] / L) ** 2
            gamma2 = (dtheta_local[0] / L) ** 2
            kappa2_elem[e] = kappa2
            gamma2_elem[e] = gamma2

            # Main spar bending stress with parallel-axis axial component:
            #   σ = E * κ * (R + |d_z|)
            sigma_bend2 = (E_m * (R_m[e] + dz_main_abs[e])) ** 2 * kappa2
            sigma_bend = np.sqrt(sigma_bend2 + 1e-30)
            sigma_axial = wire_precomp[e] / (A_m[e] + 1e-30)

            # Torsion shear stress: τ = G * γ * R
            tau2 = (G_m * R_m[e]) ** 2 * gamma2

            # Von Mises: σ_vm = sqrt((σ_bend + σ_axial)^2 + 3τ²)
            sigma_vm_main[e] = np.sqrt((sigma_bend + sigma_axial) ** 2 + 3.0 * tau2 + 1e-30)

        outputs["vonmises_main"] = sigma_vm_main

        if self.options["rear_enabled"]:
            G_r = self.options["G_rear"]

            sigma_vm_rear = np.zeros(ne, dtype=disp.dtype)
            for e in range(ne):
                kappa2 = kappa2_elem[e]
                gamma2 = gamma2_elem[e]

                sigma_bend2 = (E_r * (R_r[e] + dz_rear_abs[e])) ** 2 * kappa2
                sigma_bend = np.sqrt(sigma_bend2 + 1e-30)
                sigma_axial = wire_precomp[e] / (A_r[e] + 1e-30)
                tau2 = (G_r * R_r[e]) ** 2 * gamma2
                sigma_vm_rear[e] = np.sqrt((sigma_bend + sigma_axial) ** 2 + 3.0 * tau2 + 1e-30)

            outputs["vonmises_rear"] = sigma_vm_rear


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

        half = np.sum(mpl * dL)
        outputs["spar_mass_half"] = half
        outputs["spar_mass_full"] = half * 2.0
        outputs["total_mass_full"] = half * 2.0 + jm * 2.0


class TwistConstraintComp(om.ExplicitComponent):
    """Extract maximum twist angle from beam displacements.

    twist_max = KS smooth max of |θ_y| along span, in degrees.
    Previously only used tip value (assumes monotonic twist),
    but this assumption fails for wings with sign-changing pitching
    moment or complex lift distributions. KS aggregation is more robust.
    """

    def initialize(self):
        self.options.declare("n_nodes", types=int)
        self.options.declare("ks_rho", types=float, default=100.0)

    def setup(self):
        nn = self.options["n_nodes"]
        self.add_input("disp", shape=(nn, 6))
        self.add_input("nodes", shape=(nn, 3), units="m")
        self.add_output("twist_max_deg", val=0.0)
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs):
        disp = inputs["disp"]
        nodes = inputs["nodes"]
        nn = self.options["n_nodes"]

        # Project nodal rotation vectors to each node's local beam axis.
        theta_twist = np.zeros(nn, dtype=disp.dtype)
        for i in range(nn):
            if i < nn - 1:
                R3 = _rotation_matrix(nodes[i], nodes[i + 1])
            else:
                R3 = _rotation_matrix(nodes[i - 1], nodes[i])
            theta_local = R3 @ disp[i, 3:6]
            theta_twist[i] = theta_local[0]

        # KS aggregation for max |θ| across all nodes (CS-safe)
        theta_abs_sq = theta_twist ** 2 + 1e-30  # [nn]
        theta_abs = np.sqrt(theta_abs_sq)  # [nn], strictly positive
        # KS smooth-max (dimensionless scaling avoids node-count-dependent
        # offset when absolute twists are very small).
        rho = self.options["ks_rho"]
        theta_scale = np.real(theta_abs).max() + 1e-12
        theta_nd = theta_abs / theta_scale
        theta_max_ks_nd = (1.0 / rho) * np.log(np.sum(np.exp(rho * theta_nd)))
        theta_max_ks = theta_max_ks_nd * theta_scale
        outputs["twist_max_deg"] = theta_max_ks * 180.0 / np.pi


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
