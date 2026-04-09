"""Segment mapping and dual-spar section property components."""
from __future__ import annotations

import numpy as np
import openmdao.api as om

from hpa_mdo.structure.spar_model import tube_area, tube_Ixx, tube_J


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


class DualSparPropertiesComp(om.ExplicitComponent):
    """Compute equivalent beam A, Iy, Iz, J from dual hollow-tube spars.

    Uses parallel-axis theorem for EI, with an optional knockdown on the
    rigid-rib torsional warping term in GJ.
    """

    # Class-level call counters for benchmarking (not thread-safe).
    _n_compute = 0
    _n_compute_partials = 0

    @classmethod
    def reset_counters(cls) -> None:
        cls._n_compute = 0
        cls._n_compute_partials = 0

    def initialize(self):
        self.options.declare("n_elements", types=int)
        self.options.declare("z_main", types=np.ndarray,
                             desc="Z-offset of main spar centroid [m]")
        self.options.declare("z_rear", types=np.ndarray,
                             desc="Z-offset of rear spar centroid [m]")
        self.options.declare("d_chord", types=np.ndarray,
                             desc="Chordwise spar separation [m]")
        self.options.declare("E_main", types=float)
        self.options.declare("G_main", types=float)
        self.options.declare("rho_main", types=float)
        self.options.declare("E_rear", types=float)
        self.options.declare("G_rear", types=float)
        self.options.declare("rho_rear", types=float)
        self.options.declare("rear_enabled", types=bool, default=True)
        self.options.declare("warping_knockdown", types=float, default=1.0)

    def setup(self):
        ne = self.options["n_elements"]

        self.add_input("main_t_elem", shape=(ne,), units="m")
        self.add_input("main_r_elem", shape=(ne,), units="m")
        self.add_output("A_equiv", shape=(ne,), units="m**2")
        self.add_output("Iy_equiv", shape=(ne,), units="m**4")
        self.add_output("Iz_equiv", shape=(ne,), units="m**4")
        self.add_output("J_equiv", shape=(ne,), units="m**4")
        self.add_output("EI_flap", shape=(ne,), units="N*m**2")
        self.add_output("EI_main", shape=(ne,), units="N*m**2")
        self.add_output("GJ", shape=(ne,), units="N*m**2")
        self.add_output("mass_per_length", shape=(ne,), units="kg/m")
        self.add_output("rear_mass_per_length", shape=(ne,), units="kg/m")
        # Stress-check arrays (individual tubes)
        self.add_output("A_main", shape=(ne,), units="m**2")
        self.add_output("I_main", shape=(ne,), units="m**4")
        self.add_output("A_rear", shape=(ne,), units="m**2")
        self.add_output("I_rear", shape=(ne,), units="m**4")

        if self.options["rear_enabled"]:
            self.add_input("rear_t_elem", shape=(ne,), units="m")
            self.add_input("rear_r_elem", shape=(ne,), units="m")
            self.add_output("EI_rear", shape=(ne,), units="N*m**2")

        row_col = np.arange(ne)
        rear_on = self.options["rear_enabled"]
        outputs_always = [
            "A_main",
            "I_main",
            "EI_main",
            "A_equiv",
            "EI_flap",
            "GJ",
            "mass_per_length",
            "Iy_equiv",
            "Iz_equiv",
            "J_equiv",
        ]
        outputs_with_rear = [
            "A_rear",
            "I_rear",
            "EI_rear",
            "rear_mass_per_length",
            "A_equiv",
            "EI_flap",
            "GJ",
            "mass_per_length",
            "Iy_equiv",
            "Iz_equiv",
            "J_equiv",
        ]
        inputs_main = ["main_t_elem", "main_r_elem"]
        inputs_rear = ["rear_t_elem", "rear_r_elem"]

        for out in outputs_always:
            for inp in inputs_main:
                self.declare_partials(out, inp, rows=row_col, cols=row_col)

        if rear_on:
            for out in outputs_with_rear:
                for inp in inputs_rear:
                    self.declare_partials(out, inp, rows=row_col, cols=row_col)

    def compute(self, inputs, outputs):
        type(self)._n_compute += 1
        ne = self.options["n_elements"]
        R_m = inputs["main_r_elem"]
        rho_m = self.options["rho_main"]
        E_m = self.options["E_main"]
        G_m = self.options["G_main"]
        t_m = inputs["main_t_elem"]

        A_m = tube_area(R_m, t_m)
        I_m = tube_Ixx(R_m, t_m)
        J_m = tube_J(R_m, t_m)

        outputs["A_main"] = A_m
        outputs["I_main"] = I_m
        outputs["EI_main"] = E_m * I_m

        if self.options["rear_enabled"]:
            R_r = inputs["rear_r_elem"]
            rho_r = self.options["rho_rear"]
            E_r = self.options["E_rear"]
            G_r = self.options["G_rear"]
            z_m = self.options["z_main"]
            z_r = self.options["z_rear"]
            d = self.options["d_chord"]
            warping_knockdown = self.options["warping_knockdown"]
            t_r = inputs["rear_t_elem"]

            A_r = tube_area(R_r, t_r)
            I_r = tube_Ixx(R_r, t_r)
            J_r = tube_J(R_r, t_r)

            outputs["A_rear"] = A_r
            outputs["I_rear"] = I_r
            outputs["EI_rear"] = E_r * I_r

            # Parallel-axis theorem for flapwise EI
            denom = E_m * A_m + E_r * A_r + 1e-30
            z_na = (E_m * A_m * z_m + E_r * A_r * z_r) / denom
            EI_flap = (
                E_m * (I_m + A_m * (z_m - z_na) ** 2)
                + E_r * (I_r + A_r * (z_r - z_na) ** 2)
            )
            # Chordwise EI (about span axis) from spar chordwise separation.
            x_na = E_r * A_r * d / denom
            EI_chord = (
                E_m * (I_m + A_m * x_na**2)
                + E_r * (I_r + A_r * (d - x_na) ** 2)
            )

            # Torsion: tubes + warping coupling
            GJ_tubes = G_m * J_m + G_r * J_r
            GJ_warping = warping_knockdown * (E_m * A_m * E_r * A_r) / denom * d ** 2
            GJ_total = GJ_tubes + GJ_warping

            outputs["A_equiv"] = A_m + A_r
            outputs["EI_flap"] = EI_flap
            outputs["GJ"] = GJ_total
            outputs["mass_per_length"] = rho_m * A_m + rho_r * A_r
            outputs["rear_mass_per_length"] = rho_r * A_r

            # Equivalent section properties (for single-beam FEM)
            E_avg = (E_m * A_m + E_r * A_r) / (A_m + A_r + 1e-30)
            G_avg = (G_m * A_m + G_r * A_r) / (A_m + A_r + 1e-30)
            outputs["Iy_equiv"] = EI_flap / (E_avg + 1e-30)
            outputs["Iz_equiv"] = EI_chord / (E_avg + 1e-30)
            outputs["J_equiv"] = GJ_total / (G_avg + 1e-30)
        else:
            outputs["A_rear"] = np.zeros(ne)
            outputs["I_rear"] = np.zeros(ne)
            outputs["A_equiv"] = A_m
            outputs["EI_flap"] = E_m * I_m
            outputs["GJ"] = G_m * J_m
            outputs["mass_per_length"] = rho_m * A_m
            outputs["rear_mass_per_length"] = np.zeros(ne)
            outputs["Iy_equiv"] = I_m
            outputs["Iz_equiv"] = I_m
            outputs["J_equiv"] = J_m

    def compute_partials(self, inputs, partials):
        type(self)._n_compute_partials += 1
        """Analytic partials for the exact guarded `compute()` equations.

        With r = R - t:
            A = pi * (2 * R * t - t**2),  dA/dt = 2 * pi * r,  dA/dR = 2 * pi * t
            I = pi / 4 * (R**4 - r**4),   dI/dt = pi * r**3,   dI/dR = pi * (R**3 - r**3)
            J = 2 * I,                    dJ/dt = 2 * pi * r**3,
                                          dJ/dR = 2 * pi * (R**3 - r**3)

        Equivalent-section derivatives are chained from the same `compute()`
        intermediates, including the 1e-30 denominator guards.
        """
        eps = 1e-30
        rear_on = self.options["rear_enabled"]

        E_m = self.options["E_main"]
        G_m = self.options["G_main"]
        rho_m = self.options["rho_main"]
        R_m = inputs["main_r_elem"]
        t_m = inputs["main_t_elem"]
        r_m = R_m - t_m
        A_m = np.pi * (R_m**2 - r_m**2)
        I_m = np.pi / 4.0 * (R_m**4 - r_m**4)
        J_m = 2.0 * I_m

        dA_m_dt = 2.0 * np.pi * r_m
        dA_m_dR = 2.0 * np.pi * t_m
        dI_m_dt = np.pi * r_m**3
        dI_m_dR = np.pi * (R_m**3 - r_m**3)
        dJ_m_dt = 2.0 * np.pi * r_m**3
        dJ_m_dR = 2.0 * np.pi * (R_m**3 - r_m**3)

        partials["A_main", "main_t_elem"] = dA_m_dt
        partials["A_main", "main_r_elem"] = dA_m_dR
        partials["I_main", "main_t_elem"] = dI_m_dt
        partials["I_main", "main_r_elem"] = dI_m_dR
        partials["EI_main", "main_t_elem"] = E_m * dI_m_dt
        partials["EI_main", "main_r_elem"] = E_m * dI_m_dR

        if rear_on:
            E_r = self.options["E_rear"]
            G_r = self.options["G_rear"]
            rho_r = self.options["rho_rear"]
            z_m = self.options["z_main"]
            z_r = self.options["z_rear"]
            d = self.options["d_chord"]
            warping_knockdown = self.options["warping_knockdown"]

            R_r = inputs["rear_r_elem"]
            t_r = inputs["rear_t_elem"]
            r_r = R_r - t_r
            A_r = np.pi * (R_r**2 - r_r**2)
            I_r = np.pi / 4.0 * (R_r**4 - r_r**4)
            J_r = 2.0 * I_r

            dA_r_dt = 2.0 * np.pi * r_r
            dA_r_dR = 2.0 * np.pi * t_r
            dI_r_dt = np.pi * r_r**3
            dI_r_dR = np.pi * (R_r**3 - r_r**3)
            dJ_r_dt = 2.0 * np.pi * r_r**3
            dJ_r_dR = 2.0 * np.pi * (R_r**3 - r_r**3)

            partials["A_rear", "rear_t_elem"] = dA_r_dt
            partials["A_rear", "rear_r_elem"] = dA_r_dR
            partials["I_rear", "rear_t_elem"] = dI_r_dt
            partials["I_rear", "rear_r_elem"] = dI_r_dR
            partials["EI_rear", "rear_t_elem"] = E_r * dI_r_dt
            partials["EI_rear", "rear_r_elem"] = E_r * dI_r_dR
            partials["rear_mass_per_length", "rear_t_elem"] = rho_r * dA_r_dt
            partials["rear_mass_per_length", "rear_r_elem"] = rho_r * dA_r_dR

            p = E_m * A_m
            q = E_r * A_r
            denom_e = p + q + eps
            numer_z = p * z_m + q * z_r
            z_na = numer_z / denom_e
            dz_m = z_m - z_na
            dz_r = z_r - z_na
            dz_na_dAm = E_m * dz_m / denom_e
            dz_na_dAr = E_r * dz_r / denom_e

            EI_flap = (
                E_m * (I_m + A_m * dz_m**2)
                + E_r * (I_r + A_r * dz_r**2)
            )
            x_na = q * d / denom_e
            dx_na_dAm = -E_m * q * d / denom_e**2
            dx_na_dAr = E_r * (p + eps) * d / denom_e**2
            x_off_m = -x_na
            x_off_r = d - x_na
            dx_off_m_dAm = -dx_na_dAm
            dx_off_r_dAm = -dx_na_dAm
            dx_off_m_dAr = -dx_na_dAr
            dx_off_r_dAr = -dx_na_dAr
            EI_chord = (
                E_m * (I_m + A_m * x_off_m**2)
                + E_r * (I_r + A_r * x_off_r**2)
            )
            dEI_dAm = E_m * dz_m**2 - 2.0 * eps * z_na * dz_na_dAm
            dEI_dAr = E_r * dz_r**2 - 2.0 * eps * z_na * dz_na_dAr
            dEI_chord_dAm = (
                E_m * x_off_m**2
                + 2.0 * E_m * A_m * x_off_m * dx_off_m_dAm
                + 2.0 * E_r * A_r * x_off_r * dx_off_r_dAm
            )
            dEI_chord_dAr = (
                E_r * x_off_r**2
                + 2.0 * E_m * A_m * x_off_m * dx_off_m_dAr
                + 2.0 * E_r * A_r * x_off_r * dx_off_r_dAr
            )

            GJ_val = G_m * J_m + G_r * J_r + warping_knockdown * (p * q / denom_e) * d**2
            dGJ_dAm = warping_knockdown * E_m * q * (q + eps) * d**2 / denom_e**2
            dGJ_dAr = warping_knockdown * E_r * p * (p + eps) * d**2 / denom_e**2

            A_sum = A_m + A_r
            a_sum_guard = A_sum + eps

            partials["A_equiv", "main_t_elem"] = dA_m_dt
            partials["A_equiv", "main_r_elem"] = dA_m_dR
            partials["A_equiv", "rear_t_elem"] = dA_r_dt
            partials["A_equiv", "rear_r_elem"] = dA_r_dR

            partials["mass_per_length", "main_t_elem"] = rho_m * dA_m_dt
            partials["mass_per_length", "main_r_elem"] = rho_m * dA_m_dR
            partials["mass_per_length", "rear_t_elem"] = rho_r * dA_r_dt
            partials["mass_per_length", "rear_r_elem"] = rho_r * dA_r_dR

            partials["EI_flap", "main_t_elem"] = dEI_dAm * dA_m_dt + E_m * dI_m_dt
            partials["EI_flap", "main_r_elem"] = dEI_dAm * dA_m_dR + E_m * dI_m_dR
            partials["EI_flap", "rear_t_elem"] = dEI_dAr * dA_r_dt + E_r * dI_r_dt
            partials["EI_flap", "rear_r_elem"] = dEI_dAr * dA_r_dR + E_r * dI_r_dR

            partials["GJ", "main_t_elem"] = dGJ_dAm * dA_m_dt + G_m * dJ_m_dt
            partials["GJ", "main_r_elem"] = dGJ_dAm * dA_m_dR + G_m * dJ_m_dR
            partials["GJ", "rear_t_elem"] = dGJ_dAr * dA_r_dt + G_r * dJ_r_dt
            partials["GJ", "rear_r_elem"] = dGJ_dAr * dA_r_dR + G_r * dJ_r_dR

            E_avg = (p + q) / a_sum_guard
            iy_denom = E_avg + eps
            dEavg_dAm = ((E_m - E_r) * A_r + E_m * eps) / a_sum_guard**2
            dEavg_dAr = ((E_r - E_m) * A_m + E_r * eps) / a_sum_guard**2
            dIyeq_dAm = dEI_dAm / iy_denom - EI_flap * dEavg_dAm / iy_denom**2
            dIyeq_dAr = dEI_dAr / iy_denom - EI_flap * dEavg_dAr / iy_denom**2
            dIyeq_dIm = E_m / iy_denom
            dIyeq_dIr = E_r / iy_denom
            dIzeq_dAm = dEI_chord_dAm / iy_denom - EI_chord * dEavg_dAm / iy_denom**2
            dIzeq_dAr = dEI_chord_dAr / iy_denom - EI_chord * dEavg_dAr / iy_denom**2
            dIzeq_dIm = E_m / iy_denom
            dIzeq_dIr = E_r / iy_denom

            partials["Iy_equiv", "main_t_elem"] = dIyeq_dAm * dA_m_dt + dIyeq_dIm * dI_m_dt
            partials["Iy_equiv", "main_r_elem"] = dIyeq_dAm * dA_m_dR + dIyeq_dIm * dI_m_dR
            partials["Iy_equiv", "rear_t_elem"] = dIyeq_dAr * dA_r_dt + dIyeq_dIr * dI_r_dt
            partials["Iy_equiv", "rear_r_elem"] = dIyeq_dAr * dA_r_dR + dIyeq_dIr * dI_r_dR
            partials["Iz_equiv", "main_t_elem"] = dIzeq_dAm * dA_m_dt + dIzeq_dIm * dI_m_dt
            partials["Iz_equiv", "main_r_elem"] = dIzeq_dAm * dA_m_dR + dIzeq_dIm * dI_m_dR
            partials["Iz_equiv", "rear_t_elem"] = dIzeq_dAr * dA_r_dt + dIzeq_dIr * dI_r_dt
            partials["Iz_equiv", "rear_r_elem"] = dIzeq_dAr * dA_r_dR + dIzeq_dIr * dI_r_dR

            G_avg = (G_m * A_m + G_r * A_r) / a_sum_guard
            j_denom = G_avg + eps
            dGavg_dAm = ((G_m - G_r) * A_r + G_m * eps) / a_sum_guard**2
            dGavg_dAr = ((G_r - G_m) * A_m + G_r * eps) / a_sum_guard**2
            dJeq_dAm = dGJ_dAm / j_denom - GJ_val * dGavg_dAm / j_denom**2
            dJeq_dAr = dGJ_dAr / j_denom - GJ_val * dGavg_dAr / j_denom**2
            dJeq_dJm = G_m / j_denom
            dJeq_dJr = G_r / j_denom

            partials["J_equiv", "main_t_elem"] = dJeq_dAm * dA_m_dt + dJeq_dJm * dJ_m_dt
            partials["J_equiv", "main_r_elem"] = dJeq_dAm * dA_m_dR + dJeq_dJm * dJ_m_dR
            partials["J_equiv", "rear_t_elem"] = dJeq_dAr * dA_r_dt + dJeq_dJr * dJ_r_dt
            partials["J_equiv", "rear_r_elem"] = dJeq_dAr * dA_r_dR + dJeq_dJr * dJ_r_dR
        else:
            partials["A_equiv", "main_t_elem"] = dA_m_dt
            partials["A_equiv", "main_r_elem"] = dA_m_dR
            partials["EI_flap", "main_t_elem"] = E_m * dI_m_dt
            partials["EI_flap", "main_r_elem"] = E_m * dI_m_dR
            partials["GJ", "main_t_elem"] = G_m * dJ_m_dt
            partials["GJ", "main_r_elem"] = G_m * dJ_m_dR
            partials["mass_per_length", "main_t_elem"] = rho_m * dA_m_dt
            partials["mass_per_length", "main_r_elem"] = rho_m * dA_m_dR
            partials["Iy_equiv", "main_t_elem"] = dI_m_dt
            partials["Iy_equiv", "main_r_elem"] = dI_m_dR
            partials["Iz_equiv", "main_t_elem"] = dI_m_dt
            partials["Iz_equiv", "main_r_elem"] = dI_m_dR
            partials["J_equiv", "main_t_elem"] = dJ_m_dt
            partials["J_equiv", "main_r_elem"] = dJ_m_dR
