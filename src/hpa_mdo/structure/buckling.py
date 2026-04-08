"""Shell local buckling constraint for thin-walled circular CF tubes."""
from __future__ import annotations

import numpy as np
import openmdao.api as om


SHELL_BUCKLING_CLASSICAL_FACTOR = 0.605
SHELL_BUCKLING_COEFFICIENT = 0.512


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
        self.options.declare("rear_enabled", types=bool, default=True)
        self.options.declare("knockdown_factor", types=float, default=0.65)
        self.options.declare("bending_enhancement", types=float, default=1.3)
        self.options.declare("ks_rho", types=float, default=50.0)

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
        gamma = self.options["knockdown_factor"]
        beta = self.options["bending_enhancement"]
        rho = self.options["ks_rho"]

        disp = inputs["disp"]
        nodes = inputs["nodes"]
        R_main = inputs["main_r_elem"]
        t_main = inputs["main_t_elem"]

        kappa_mag = np.zeros(ne, dtype=disp.dtype)
        for e in range(ne):
            dx = nodes[e + 1] - nodes[e]
            L = _cs_norm(dx)
            du = disp[e + 1] - disp[e]
            R3 = _rotation_matrix(nodes[e], nodes[e + 1])
            dtheta_local = R3 @ du[3:6]
            # Include both local bending planes for shell-buckling demand.
            kappa_mag[e] = np.sqrt(
                (dtheta_local[1] / (L + 1e-30)) ** 2
                + (dtheta_local[2] / (L + 1e-30)) ** 2
                + 1e-30
            )

        coef = SHELL_BUCKLING_CLASSICAL_FACTOR * gamma * beta
        abs_kappa = kappa_mag

        sigma_bend_main = E_main * R_main * abs_kappa
        sigma_cr_main = coef * E_main * t_main / (R_main + 1e-30)
        ratio_main = sigma_bend_main / (sigma_cr_main + 1e-30)

        ratios = [ratio_main]

        if self.options["rear_enabled"]:
            E_rear = self.options["E_rear"]
            R_rear = inputs["rear_r_elem"]
            t_rear = inputs["rear_t_elem"]

            sigma_bend_rear = E_rear * R_rear * abs_kappa
            sigma_cr_rear = coef * E_rear * t_rear / (R_rear + 1e-30)
            ratio_rear = sigma_bend_rear / (sigma_cr_rear + 1e-30)
            ratios.append(ratio_rear)

        all_ratios = np.concatenate(ratios)
        margin = all_ratios - 1.0

        max_margin = np.real(margin).max()
        ks_sum = np.sum(np.exp(rho * (margin - max_margin)))
        outputs["buckling_index"] = max_margin + np.log(ks_sum) / rho
