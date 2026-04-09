"""Shell local buckling constraint for thin-walled circular CF tubes."""
from __future__ import annotations

import numpy as np
import openmdao.api as om


SHELL_BUCKLING_CLASSICAL_FACTOR = 0.605
SHELL_BUCKLING_COEFFICIENT = 0.512
SHELL_TORSION_SHEAR_BUCKLING_COEFFICIENT = 0.272


def _cs_norm(x: np.ndarray) -> np.ndarray:
    """Complex-step compatible vector norm."""
    return np.sqrt(np.dot(x, x) + 1e-30)


def _rotation_matrix(node_i: np.ndarray, node_j: np.ndarray) -> np.ndarray:
    """3x3 local-to-global rotation matrix with local x aligned to element axis."""
    dx = node_j - node_i
    L = _cs_norm(dx)
    if np.real(L) < 1e-12:
        return np.eye(3, dtype=dx.dtype)

    e1 = dx / (L + 1e-30)
    ref = np.array([0.0, 0.0, 1.0], dtype=dx.dtype)
    if abs(np.real(np.dot(e1, ref))) > 0.99:
        ref = np.array([1.0, 0.0, 0.0], dtype=dx.dtype)

    e2 = np.cross(ref, e1)
    e2 = e2 / (_cs_norm(e2) + 1e-30)
    e3 = np.cross(e1, e2)
    e3 = e3 / (_cs_norm(e3) + 1e-30)
    return np.array([e1, e2, e3], dtype=dx.dtype)


def _tube_area(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Thin-walled circular tube area (outer radius R, wall thickness t)."""
    r = R - t
    return np.pi * (R**2 - r**2)


class BucklingComp(om.ExplicitComponent):
    """Shell local buckling constraint for thin-walled circular CF tubes.

    Uses classical shell theory (Timoshenko-Gere) with NASA SP-8007
    knockdown factor for imperfection sensitivity, plus bending
    enhancement factor.

    Critical stress per element:
        sigma_cr = (gamma * enhancement) * 0.605 * E * t / R

    where gamma is the knockdown factor (~0.65 for CF tubes).
    """

    def initialize(self):
        self.options.declare("n_nodes", types=int)
        self.options.declare("E_main", types=float)
        self.options.declare("E_rear", types=float)
        self.options.declare("G_main", types=float)
        self.options.declare("G_rear", default=None, allow_none=True)
        self.options.declare("rear_enabled", types=bool, default=True)
        self.options.declare("z_main", default=None, allow_none=True)
        self.options.declare("z_rear", default=None, allow_none=True)
        self.options.declare("knockdown_factor", types=float, default=0.65)
        self.options.declare("bending_enhancement", types=float, default=1.3)
        self.options.declare("ks_rho", types=float, default=50.0)
        self.options.declare(
            "wire_precompression",
            default=None,
            allow_none=True,
            desc="(ne,) axial pre-compression [N] from lift-wire reaction.",
        )

    def setup(self):
        nn = self.options["n_nodes"]
        ne = nn - 1

        self.add_input("disp", shape=(nn, 6))
        self.add_input("nodes", shape=(nn, 3), units="m")
        self.add_input("main_r_elem", shape=(ne,), units="m")
        self.add_input("main_t_elem", shape=(ne,), units="m")

        if self.options["rear_enabled"]:
            self.add_input("rear_r_elem", shape=(ne,), units="m")
            self.add_input("rear_t_elem", shape=(ne,), units="m")

        self.add_output("buckling_index", val=0.0)

        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs):
        nn = self.options["n_nodes"]
        ne = nn - 1

        E_main = self.options["E_main"]
        G_main = self.options["G_main"]
        gamma = self.options["knockdown_factor"]
        beta = self.options["bending_enhancement"]
        rho = self.options["ks_rho"]

        disp = inputs["disp"]
        nodes = inputs["nodes"]
        R_main = inputs["main_r_elem"]
        t_main = inputs["main_t_elem"]
        z_main = self.options["z_main"]
        if z_main is None:
            z_main = np.zeros(ne)
        z_main = np.asarray(z_main)
        A_main = _tube_area(R_main, t_main)

        wire_precomp_opt = self.options["wire_precompression"]
        if wire_precomp_opt is None:
            wire_precomp = np.zeros(ne, dtype=disp.dtype)
        else:
            wire_precomp = np.asarray(wire_precomp_opt, dtype=disp.dtype)
            if wire_precomp.shape != (ne,):
                raise om.AnalysisError(
                    f"wire_precompression must have shape ({ne},), got {wire_precomp.shape}."
                )

        kappa_mag = np.zeros(ne, dtype=disp.dtype)
        gamma_mag = np.zeros(ne, dtype=disp.dtype)
        for e in range(ne):
            dx = nodes[e + 1] - nodes[e]
            L = _cs_norm(dx)
            du = disp[e + 1] - disp[e]
            R3 = _rotation_matrix(nodes[e], nodes[e + 1])
            dtheta_local = R3 @ du[3:6]
            gamma_mag[e] = np.sqrt((dtheta_local[0] / (L + 1e-30)) ** 2 + 1e-30)
            # Include both local bending planes for shell-buckling demand.
            kappa_mag[e] = np.sqrt(
                (dtheta_local[1] / (L + 1e-30)) ** 2
                + (dtheta_local[2] / (L + 1e-30)) ** 2
                + 1e-30
            )

        coef = SHELL_BUCKLING_CLASSICAL_FACTOR * gamma * beta
        abs_kappa = kappa_mag

        if self.options["rear_enabled"]:
            E_rear = self.options["E_rear"]
            G_rear = self.options["G_rear"]
            if G_rear is None:
                raise om.AnalysisError("G_rear must be provided when rear_enabled=True.")
            R_rear = inputs["rear_r_elem"]
            t_rear = inputs["rear_t_elem"]
            z_rear = self.options["z_rear"]
            if z_rear is None:
                z_rear = np.zeros(ne)
            z_rear = np.asarray(z_rear)

            A_rear = _tube_area(R_rear, t_rear)
            denom = E_main * A_main + E_rear * A_rear + 1e-30
            z_na = (E_main * A_main * z_main + E_rear * A_rear * z_rear) / denom
            dz_main = z_main - z_na
            dz_rear = z_rear - z_na
            dz_main_abs = np.sqrt(dz_main**2 + 1e-30)
            dz_rear_abs = np.sqrt(dz_rear**2 + 1e-30)
        else:
            R_rear = None
            t_rear = None
            dz_main_abs = np.zeros(ne, dtype=disp.dtype)
            dz_rear_abs = None

        sigma_bend_main = E_main * (R_main + dz_main_abs) * abs_kappa
        sigma_axial_main = wire_precomp / (A_main + 1e-30)
        sigma_cr_main = coef * E_main * t_main / (R_main + 1e-30)
        tau_main = G_main * R_main * gamma_mag
        tau_cr_main = (
            SHELL_TORSION_SHEAR_BUCKLING_COEFFICIENT
            * gamma
            * E_main
            * (t_main / (R_main + 1e-30)) ** 1.25
        )
        ratio_main_normal = (sigma_bend_main + sigma_axial_main) / (sigma_cr_main + 1e-30)
        ratio_main_shear = tau_main / (tau_cr_main + 1e-30)
        ratio_main = np.sqrt(ratio_main_normal**2 + ratio_main_shear**2 + 1e-30)

        ratios = [ratio_main]

        if self.options["rear_enabled"]:
            sigma_bend_rear = E_rear * (R_rear + dz_rear_abs) * abs_kappa
            sigma_axial_rear = wire_precomp / (A_rear + 1e-30)
            sigma_cr_rear = coef * E_rear * t_rear / (R_rear + 1e-30)
            tau_rear = G_rear * R_rear * gamma_mag
            tau_cr_rear = (
                SHELL_TORSION_SHEAR_BUCKLING_COEFFICIENT
                * gamma
                * E_rear
                * (t_rear / (R_rear + 1e-30)) ** 1.25
            )
            ratio_rear_normal = (sigma_bend_rear + sigma_axial_rear) / (sigma_cr_rear + 1e-30)
            ratio_rear_shear = tau_rear / (tau_cr_rear + 1e-30)
            ratio_rear = np.sqrt(ratio_rear_normal**2 + ratio_rear_shear**2 + 1e-30)
            ratios.append(ratio_rear)

        all_ratios = np.concatenate(ratios)
        margin = all_ratios - 1.0

        max_margin = np.real(margin).max()
        ks_sum = np.sum(np.exp(rho * (margin - max_margin)))
        outputs["buckling_index"] = max_margin + np.log(ks_sum) / rho
