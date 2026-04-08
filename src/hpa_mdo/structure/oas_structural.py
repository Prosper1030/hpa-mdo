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

from hpa_mdo.core.constants import G_STANDARD
from hpa_mdo.core.logging import get_logger
from hpa_mdo.structure.buckling import BucklingComp
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


def _is_single_mapped_load(aero_loads: dict) -> bool:
    """Return True when ``aero_loads`` looks like a single mapped load dict."""
    return isinstance(aero_loads, dict) and "lift_per_span" in aero_loads


def _normalise_load_case_inputs(cfg, aero_loads: dict) -> dict[str, tuple[object, dict]]:
    """Return ``{case_name: (load_case_cfg, mapped_loads)}`` with backward compatibility."""
    from hpa_mdo.core.config import LoadCaseConfig

    if _is_single_mapped_load(aero_loads):
        if len(cfg.flight.cases) > 1:
            raise ValueError(
                "cfg.flight.cases declares multiple load cases, but aero_loads contains only one case."
            )
        default_case = cfg.structural_load_cases()[0]
        return {default_case.name: (default_case, aero_loads)}

    if not isinstance(aero_loads, dict):
        raise TypeError("aero_loads must be a mapped-load dict or {case_name: mapped_loads}.")

    explicit_cases = {case.name: case for case in cfg.flight.cases}
    case_entries: dict[str, tuple[object, dict]] = {}

    for case_name, case_loads in aero_loads.items():
        if not _is_single_mapped_load(case_loads):
            raise ValueError(
                f"aero_loads['{case_name}'] must be a mapped load dict with 'lift_per_span'."
            )

        load_case = explicit_cases.get(case_name)
        if load_case is None:
            load_case = LoadCaseConfig(
                name=case_name,
                velocity=cfg.flight.velocity,
                air_density=cfg.flight.air_density,
            )

        case_entries[case_name] = (load_case, case_loads)

    if explicit_cases:
        missing = sorted(set(explicit_cases) - set(case_entries))
        extra = sorted(set(case_entries) - set(explicit_cases))
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing load cases: {', '.join(missing)}")
            if extra:
                details.append(f"unexpected load cases: {', '.join(extra)}")
            raise ValueError("; ".join(details))

    return case_entries


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
        self.options.declare("warping_knockdown", types=float, default=1.0)

    def setup(self):
        ne = self.options["n_elements"]

        self.add_input("main_t_elem", shape=(ne,), units="m")
        self.add_input("main_r_elem", shape=(ne,), units="m")
        self.add_output("A_equiv", shape=(ne,), units="m**2")
        self.add_output("Iy_equiv", shape=(ne,), units="m**4")
        self.add_output("J_equiv", shape=(ne,), units="m**4")
        self.add_output("EI_flap", shape=(ne,), units="N*m**2")
        self.add_output("EI_main", shape=(ne,), units="N*m**2")
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
            "J_equiv",
        ]
        outputs_with_rear = [
            "A_rear",
            "I_rear",
            "EI_rear",
            "A_equiv",
            "EI_flap",
            "GJ",
            "mass_per_length",
            "Iy_equiv",
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

            # Torsion: tubes + warping coupling
            GJ_tubes = G_m * J_m + G_r * J_r
            GJ_warping = warping_knockdown * (E_m * A_m * E_r * A_r) / denom * d ** 2
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
            dEI_dAm = E_m * dz_m**2 - 2.0 * eps * z_na * dz_na_dAm
            dEI_dAr = E_r * dz_r**2 - 2.0 * eps * z_na * dz_na_dAr

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

            partials["Iy_equiv", "main_t_elem"] = dIyeq_dAm * dA_m_dt + dIyeq_dIm * dI_m_dt
            partials["Iy_equiv", "main_r_elem"] = dIyeq_dAm * dA_m_dR + dIyeq_dIm * dI_m_dR
            partials["Iy_equiv", "rear_t_elem"] = dIyeq_dAr * dA_r_dt + dIyeq_dIr * dI_r_dt
            partials["Iy_equiv", "rear_r_elem"] = dIyeq_dAr * dA_r_dR + dIyeq_dIr * dI_r_dR

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
            partials["J_equiv", "main_t_elem"] = dJ_m_dt
            partials["J_equiv", "main_r_elem"] = dJ_m_dR


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
        self.options.declare(
            "max_matrix_entry",
            types=float,
            default=1e12,
            desc="Numerical guard on local element stiffness entries",
        )
        self.options.declare(
            "max_disp_entry",
            types=float,
            default=1e2,
            desc="Numerical guard on solved displacements / load Jacobian entries",
        )
        self.options.declare(
            "bc_penalty",
            types=float,
            default=1e15,
            desc="Penalty stiffness added to constrained DOFs",
        )

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

        ndof = nn * 6
        node_size = nn * 3
        elem_size = ne
        dense_rows_nodes, dense_cols_nodes = np.indices((ndof, node_size))
        dense_rows_elem, dense_cols_elem = np.indices((ndof, elem_size))
        rows, cols = np.indices((ndof, ndof))
        self._load_partial_rows = rows.ravel()
        self._load_partial_cols = cols.ravel()

        self.declare_partials(
            "disp",
            "nodes",
            rows=dense_rows_nodes.ravel(),
            cols=dense_cols_nodes.ravel(),
            method="cs",
        )
        for name in ("EI_flap", "GJ", "A_equiv", "Iy_equiv", "J_equiv"):
            self.declare_partials(
                "disp",
                name,
                rows=dense_rows_elem.ravel(),
                cols=dense_cols_elem.ravel(),
                method="cs",
            )
        self.declare_partials(
            "disp",
            "loads",
            rows=self._load_partial_rows,
            cols=self._load_partial_cols,
        )

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
        max_matrix_entry = self.options["max_matrix_entry"]
        max_disp_entry = self.options["max_disp_entry"]
        load_selector = np.eye(ndof, dtype=dtype)

        for e in range(ne):
            ni = nodes[e]
            nj = nodes[e + 1]
            dx = nj - ni
            L = _cs_norm(dx)
            if np.real(L) < 1e-10:
                raise om.AnalysisError(f"Degenerate beam element length at element {e}.")

            # Use the equivalent Iy, J for this element
            Iy_e = Iy[e]
            Iz_e = Iy[e]  # symmetric tube approximation
            J_e = J[e]
            A_e = A[e]
            if (
                not _has_only_finite_values(np.array([A_e, Iy_e, J_e, EI[e], GJ_arr[e]]))
                or np.real(A_e) <= 1e-20
                or np.real(Iy_e) <= 1e-20
                or np.real(J_e) <= 1e-20
            ):
                raise om.AnalysisError(
                    f"Invalid section properties at element {e} "
                    f"(A={A_e}, Iy={Iy_e}, J={J_e})."
                )

            # Compute effective E, G from EI and I
            E_eff = EI[e] / (Iy_e + 1e-30)
            G_eff = GJ_arr[e] / (J_e + 1e-30)
            if not _has_only_finite_values(np.array([E_eff, G_eff])):
                raise om.AnalysisError(
                    f"Invalid effective material properties at element {e} "
                    f"(E_eff={E_eff}, G_eff={G_eff})."
                )

            K_local = _timoshenko_element_stiffness(
                L, E_eff, G_eff, A_e, Iy_e, Iz_e, J_e)
            if (
                not _has_only_finite_values(K_local)
                or float(np.max(np.abs(K_local))) > max_matrix_entry
            ):
                raise om.AnalysisError(
                    f"Local stiffness matrix overflow/non-finite at element {e}."
                )

            # Transform to global coordinates
            R3 = _rotation_matrix(ni, nj)
            T = _transform_12x12(R3)
            if not _has_only_finite_values(T):
                raise om.AnalysisError(f"Invalid element rotation transform at element {e}.")
            with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
                K_elem_global = T.T @ K_local @ T
            if not _has_only_finite_values(K_elem_global):
                raise om.AnalysisError(
                    f"Global element stiffness matrix became non-finite at element {e}."
                )

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
        penalty_val = np.array(self.options["bc_penalty"], dtype=dtype)
        zero_val = np.array(0.0, dtype=dtype)
        for dof in bc_dofs:
            K_global[dof, dof] += penalty_val
            f[dof] = zero_val
            load_selector[dof, dof] = zero_val

        # Solve (works with both real and complex matrices)
        try:
            u = np.linalg.solve(K_global, f)
        except np.linalg.LinAlgError as exc:
            raise om.AnalysisError("Global stiffness matrix is singular.") from exc
        if (
            not _has_only_finite_values(u)
            or float(np.max(np.abs(u))) > max_disp_entry
        ):
            raise om.AnalysisError(
                "FEM displacement solve diverged or produced non-finite values."
            )

        self._last_k_global = K_global.copy()
        self._last_load_selector = load_selector
        self._max_disp_entry = max_disp_entry
        outputs["disp"] = u.reshape((nn, 6))

    def compute_partials(self, inputs, partials):
        """Exact Jacobian for ``disp`` with respect to nodal loads."""
        k_global = getattr(self, "_last_k_global", None)
        load_selector = getattr(self, "_last_load_selector", None)
        max_disp_entry = getattr(self, "_max_disp_entry", 1e2)
        nn = self.options["n_nodes"]
        ndof = nn * 6

        if k_global is None or load_selector is None:
            partials["disp", "loads"] = np.zeros((ndof, ndof))
            return

        try:
            load_jac = np.linalg.solve(k_global, load_selector)
        except np.linalg.LinAlgError:
            load_jac = np.zeros((ndof, ndof), dtype=k_global.dtype)

        if (
            not _has_only_finite_values(load_jac)
            or float(np.max(np.abs(load_jac))) > max_disp_entry
        ):
            load_jac = np.zeros((ndof, ndof), dtype=k_global.dtype)

        partials["disp", "loads"] = np.real(load_jac).ravel()


# ═════════════════════════════════════════════════════════════════════════
#  Component 4 : Von Mises stress from displacements
# ═════════════════════════════════════════════════════════════════════════

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

            A_m = tube_area(R_m, t_m)
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

            # Torsion shear stress: τ = G * γ * R
            tau2 = (G_m * R_m[e]) ** 2 * gamma2

            # Von Mises: σ_vm = sqrt(σ² + 3τ²)
            sigma_vm_main[e] = np.sqrt(sigma_bend2 + 3.0 * tau2 + 1e-30)

        outputs["vonmises_main"] = sigma_vm_main

        if self.options["rear_enabled"]:
            G_r = self.options["G_rear"]

            sigma_vm_rear = np.zeros(ne, dtype=disp.dtype)
            for e in range(ne):
                kappa2 = kappa2_elem[e]
                gamma2 = gamma2_elem[e]

                sigma_bend2 = (E_r * (R_r[e] + dz_rear_abs[e])) ** 2 * kappa2
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

        half = np.sum(mpl * dL)
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
        - Spar self-weight / inertia (negative Fz), scaled by load factor
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
        self.options.declare(
            "gravity_scale",
            types=float,
            default=1.0,
            desc="Scale factor on gravity/inertial loads (e.g. maneuver nz)",
        )

    def setup(self):
        nn = self.options["n_nodes"]
        ne = nn - 1
        self.add_input("mass_per_length", shape=(ne,), units="kg/m")
        self.add_output("loads", shape=(nn, 6))
        g = G_STANDARD
        g_scaled = g * self.options["gravity_scale"]
        element_lengths = self.options["element_lengths"]
        rows = []
        cols = []
        vals = []
        for e, length in enumerate(element_lengths):
            weight_sensitivity = -0.5 * g_scaled * length
            rows.extend([e * 6 + 2, (e + 1) * 6 + 2])
            cols.extend([e, e])
            vals.extend([weight_sensitivity, weight_sensitivity])
        self.declare_partials("loads", "mass_per_length", rows=rows, cols=cols, val=vals)

    def compute(self, inputs, outputs):
        nn = self.options["n_nodes"]
        ne = nn - 1
        lift = self.options["lift_per_span"]
        torque = self.options["torque_per_span"]
        ds = self.options["node_spacings"]
        element_lengths = self.options["element_lengths"]
        mpl = inputs["mass_per_length"]
        g = G_STANDARD * self.options["gravity_scale"]

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
#  Per-case group
# ═════════════════════════════════════════════════════════════════════════

class StructuralLoadCaseGroup(om.Group):
    """One structural load case branch sharing geometry and spar properties."""

    def initialize(self):
        self.options.declare("load_case", desc="LoadCaseConfig object")
        self.options.declare("n_nodes", types=int)
        self.options.declare("lift_per_span", types=np.ndarray)
        self.options.declare("torque_per_span", types=np.ndarray)
        self.options.declare("node_spacings", types=np.ndarray)
        self.options.declare("element_lengths", types=np.ndarray)
        self.options.declare("E_avg", types=float)
        self.options.declare("G_avg", types=float)
        self.options.declare("E_main", types=float)
        self.options.declare("E_rear", types=float)
        self.options.declare("G_main", types=float)
        self.options.declare("G_rear", types=float)
        self.options.declare("z_main", types=np.ndarray)
        self.options.declare("z_rear", types=np.ndarray)
        self.options.declare("sigma_allow_main", types=float)
        self.options.declare("sigma_allow_rear", types=float)
        self.options.declare("rear_enabled", types=bool, default=True)
        self.options.declare("fixed_node", types=int, default=0)
        self.options.declare("lift_wire_nodes", default=None)
        self.options.declare("shell_buckling_knockdown", types=float)
        self.options.declare("shell_buckling_bending_enhancement", types=float)
        self.options.declare("ks_rho_stress", types=float)
        self.options.declare("ks_rho_buckling", types=float)
        self.options.declare("ks_rho_twist", types=float)
        self.options.declare("fem_max_matrix_entry", types=float)
        self.options.declare("fem_max_disp_entry", types=float)
        self.options.declare("fem_bc_penalty", types=float)

    def setup(self):
        load_case = self.options["load_case"]
        nn = self.options["n_nodes"]
        rear_on = self.options["rear_enabled"]
        aero_scale = load_case.aero_scale
        lift = np.asarray(self.options["lift_per_span"]) * aero_scale
        torque = np.asarray(self.options["torque_per_span"]) * aero_scale

        self.add_subsystem(
            "ext_loads",
            ExternalLoadsComp(
                n_nodes=nn,
                lift_per_span=lift,
                torque_per_span=torque,
                node_spacings=self.options["node_spacings"],
                element_lengths=self.options["element_lengths"],
                gravity_scale=load_case.gravity_scale,
            ),
            promotes_inputs=["mass_per_length"],
            promotes_outputs=["loads"],
        )

        self.add_subsystem(
            "fem",
            SpatialBeamFEM(
                n_nodes=nn,
                E_avg=self.options["E_avg"],
                G_avg=self.options["G_avg"],
                fixed_node=self.options["fixed_node"],
                lift_wire_nodes=self.options["lift_wire_nodes"],
                max_matrix_entry=self.options["fem_max_matrix_entry"],
                max_disp_entry=self.options["fem_max_disp_entry"],
                bc_penalty=self.options["fem_bc_penalty"],
            ),
            promotes_inputs=["nodes", "EI_flap", "GJ", "A_equiv", "Iy_equiv", "J_equiv"],
            promotes_outputs=["disp"],
        )
        self.connect("loads", "fem.loads")

        stress_inputs = ["disp", "nodes", "R_main_elem", "main_t_elem", "I_main", "EI_flap", "GJ"]
        if rear_on:
            stress_inputs.extend(["R_rear_elem", "rear_t_elem", "I_rear"])

        stress_outputs = ["vonmises_main"]
        if rear_on:
            stress_outputs.append("vonmises_rear")

        self.add_subsystem(
            "stress",
            VonMisesStressComp(
                n_nodes=nn,
                E_main=self.options["E_main"],
                E_rear=self.options["E_rear"],
                G_main=self.options["G_main"],
                G_rear=self.options["G_rear"],
                z_main=self.options["z_main"],
                z_rear=self.options["z_rear"],
                rear_enabled=rear_on,
            ),
            promotes_inputs=stress_inputs,
            promotes_outputs=stress_outputs,
        )

        buckling_inputs = ["disp", "nodes", "main_r_elem", "main_t_elem"]
        if rear_on:
            buckling_inputs.extend(["rear_r_elem", "rear_t_elem"])

        self.add_subsystem(
            "buckling",
            BucklingComp(
                n_nodes=nn,
                E_main=self.options["E_main"],
                E_rear=self.options["E_rear"] if rear_on else 0.0,
                z_main=self.options["z_main"],
                z_rear=self.options["z_rear"],
                rear_enabled=rear_on,
                knockdown_factor=self.options["shell_buckling_knockdown"],
                bending_enhancement=self.options["shell_buckling_bending_enhancement"],
                ks_rho=self.options["ks_rho_buckling"],
            ),
            promotes_inputs=buckling_inputs,
            promotes_outputs=["buckling_index"],
        )

        failure_inputs = ["vonmises_main"]
        if rear_on:
            failure_inputs.append("vonmises_rear")

        self.add_subsystem(
            "failure_comp",
            KSFailureComp(
                n_elements=nn - 1,
                sigma_allow_main=self.options["sigma_allow_main"],
                sigma_allow_rear=self.options["sigma_allow_rear"],
                rear_enabled=rear_on,
                rho_ks=self.options["ks_rho_stress"],
            ),
            promotes_inputs=failure_inputs,
            promotes_outputs=[("failure", "failure")],
        )

        self.add_subsystem(
            "twist",
            TwistConstraintComp(n_nodes=nn, ks_rho=self.options["ks_rho_twist"]),
            promotes_inputs=["disp", "nodes"],
            promotes_outputs=["twist_max_deg"],
        )

        self.add_subsystem(
            "tip_defl",
            TipDeflectionConstraintComp(n_nodes=nn),
            promotes_inputs=["disp"],
            promotes_outputs=["tip_deflection_m"],
        )


# ═════════════════════════════════════════════════════════════════════════
#  Top-level group
# ═════════════════════════════════════════════════════════════════════════

class HPAStructuralGroup(om.Group):
    """Complete structural analysis group for HPA wing spar optimization.

    Subsystems:
        seg_mapper → spar_props → ext_loads → fem → stress → buckling
        → failure, mass, twist
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

        case_entries = _normalise_load_case_inputs(cfg, aero)
        self._case_names = tuple(case_entries)
        self._multi_case = len(case_entries) > 1

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

        # Allowable stress uses the controlling material limit in bending:
        # min(tensile, compressive) / material_safety_factor.
        sigma_allow_main = min(mat_main.tensile_strength, mat_main.sigma_c) / cfg.safety.material_safety_factor
        sigma_allow_rear = min(mat_rear.tensile_strength, mat_rear.sigma_c) / cfg.safety.material_safety_factor

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
            warping_knockdown=cfg.safety.dual_spar_warping_knockdown,
        ))

        E_avg = (mat_main.E + mat_rear.E) / 2.0 if rear_on else mat_main.E
        G_avg = (mat_main.G + mat_rear.G) / 2.0 if rear_on else mat_main.G

        # Set node coordinates as fixed input
        indeps = self.add_subsystem("indeps", om.IndepVarComp())
        indeps.add_output("nodes", val=nodes_3d, units="m")

        # Store initial element radii for use in build_structural_problem()
        self._R_main_elem_init = R_main_elem
        self._R_rear_elem_init = R_rear_elem if rear_on else None

        # 8. Structural mass
        self.add_subsystem("mass", StructuralMassComp(
            n_elements=ne,
            element_lengths=dy,
            joint_mass_total=joint_mass_half,
        ))

        if len(case_entries) == 1:
            load_case, case_loads = next(iter(case_entries.values()))
            aero_scale = load_case.aero_scale
            lift = np.asarray(case_loads["lift_per_span"]) * aero_scale
            torque = np.asarray(case_loads.get("torque_per_span", np.zeros(nn))) * aero_scale

            # 3. External loads
            self.add_subsystem("ext_loads", ExternalLoadsComp(
                n_nodes=nn,
                lift_per_span=lift,
                torque_per_span=torque,
                node_spacings=node_spacings,
                element_lengths=dy,
                gravity_scale=load_case.gravity_scale,
            ))

            # 4. FEM solver
            self.add_subsystem("fem", SpatialBeamFEM(
                n_nodes=nn,
                E_avg=E_avg,
                G_avg=G_avg,
                fixed_node=0,
                lift_wire_nodes=lw_node_indices,
                max_matrix_entry=cfg.solver.fem_max_matrix_entry,
                max_disp_entry=cfg.solver.fem_max_disp_entry,
                bc_penalty=cfg.solver.fem_bc_penalty,
            ))

            # 5. Stress computation
            self.add_subsystem("stress", VonMisesStressComp(
                n_nodes=nn,
                E_main=mat_main.E,
                E_rear=mat_rear.E,
                G_main=mat_main.G,
                G_rear=mat_rear.G,
                z_main=z_main_elem,
                z_rear=z_rear_elem,
                rear_enabled=rear_on,
            ))

            # 6. Shell buckling
            self.add_subsystem("buckling", BucklingComp(
                n_nodes=nn,
                E_main=mat_main.E,
                E_rear=mat_rear.E if rear_on else 0.0,
                z_main=z_main_elem,
                z_rear=z_rear_elem,
                rear_enabled=rear_on,
                knockdown_factor=cfg.safety.shell_buckling_knockdown,
                bending_enhancement=cfg.safety.shell_buckling_bending_enhancement,
                ks_rho=cfg.safety.ks_rho_buckling,
            ))

            # 7. KS failure
            self.add_subsystem("failure", KSFailureComp(
                n_elements=ne,
                sigma_allow_main=sigma_allow_main,
                sigma_allow_rear=sigma_allow_rear,
                rear_enabled=rear_on,
                rho_ks=cfg.safety.ks_rho_stress,
            ))

            # 9. Twist constraint
            self.add_subsystem(
                "twist",
                TwistConstraintComp(n_nodes=nn, ks_rho=cfg.safety.ks_rho_twist),
            )

            # 10. Tip deflection constraint
            self.add_subsystem("tip_defl", TipDeflectionConstraintComp(n_nodes=nn))
        else:
            for case_name, (load_case, case_loads) in case_entries.items():
                lift = case_loads["lift_per_span"]
                torque = case_loads.get("torque_per_span", np.zeros(nn))
                case_group_name = f"case_{case_name}"

                self.add_subsystem(
                    case_group_name,
                    StructuralLoadCaseGroup(
                        load_case=load_case,
                        n_nodes=nn,
                        lift_per_span=lift,
                        torque_per_span=torque,
                        node_spacings=node_spacings,
                        element_lengths=dy,
                        E_avg=E_avg,
                        G_avg=G_avg,
                        E_main=mat_main.E,
                        E_rear=mat_rear.E,
                        G_main=mat_main.G,
                        G_rear=mat_rear.G,
                        z_main=z_main_elem,
                        z_rear=z_rear_elem,
                        sigma_allow_main=sigma_allow_main,
                        sigma_allow_rear=sigma_allow_rear,
                        rear_enabled=rear_on,
                        fixed_node=0,
                        lift_wire_nodes=lw_node_indices,
                        shell_buckling_knockdown=cfg.safety.shell_buckling_knockdown,
                        shell_buckling_bending_enhancement=cfg.safety.shell_buckling_bending_enhancement,
                        ks_rho_stress=cfg.safety.ks_rho_stress,
                        ks_rho_buckling=cfg.safety.ks_rho_buckling,
                        ks_rho_twist=cfg.safety.ks_rho_twist,
                        fem_max_matrix_entry=cfg.solver.fem_max_matrix_entry,
                        fem_max_disp_entry=cfg.solver.fem_max_disp_entry,
                        fem_bc_penalty=cfg.solver.fem_bc_penalty,
                    ),
                )

        # ── Connections ──
        self.connect("seg_mapper.main_t_elem", "spar_props.main_t_elem")
        self.connect("seg_mapper.main_r_elem", "spar_props.main_r_elem")
        if rear_on:
            self.connect("seg_mapper.rear_t_elem", "spar_props.rear_t_elem")
            self.connect("seg_mapper.rear_r_elem", "spar_props.rear_r_elem")

        self.connect("spar_props.mass_per_length", "mass.mass_per_length")
        if len(case_entries) == 1:
            self.connect("spar_props.mass_per_length", "ext_loads.mass_per_length")

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
            self.connect("seg_mapper.main_t_elem", "stress.main_t_elem")
            self.connect("spar_props.I_main", "stress.I_main")
            self.connect("spar_props.EI_flap", "stress.EI_flap")
            self.connect("spar_props.GJ", "stress.GJ")
            if rear_on:
                self.connect("seg_mapper.rear_r_elem", "stress.R_rear_elem")
                self.connect("seg_mapper.rear_t_elem", "stress.rear_t_elem")
                self.connect("spar_props.I_rear", "stress.I_rear")

            self.connect("fem.disp", "buckling.disp")
            self.connect("indeps.nodes", "buckling.nodes")
            self.connect("seg_mapper.main_r_elem", "buckling.main_r_elem")
            self.connect("seg_mapper.main_t_elem", "buckling.main_t_elem")
            if rear_on:
                self.connect("seg_mapper.rear_r_elem", "buckling.rear_r_elem")
                self.connect("seg_mapper.rear_t_elem", "buckling.rear_t_elem")

            self.connect("stress.vonmises_main", "failure.vonmises_main")
            if rear_on:
                self.connect("stress.vonmises_rear", "failure.vonmises_rear")

            self.connect("fem.disp", "twist.disp")
            self.connect("indeps.nodes", "twist.nodes")
            self.connect("fem.disp", "tip_defl.disp")
        else:
            for case_name in case_entries:
                case_group_name = f"case_{case_name}"
                self.connect("spar_props.mass_per_length", f"{case_group_name}.mass_per_length")
                self.connect("indeps.nodes", f"{case_group_name}.nodes")
                self.connect("spar_props.EI_flap", f"{case_group_name}.EI_flap")
                self.connect("spar_props.GJ", f"{case_group_name}.GJ")
                self.connect("spar_props.A_equiv", f"{case_group_name}.A_equiv")
                self.connect("spar_props.Iy_equiv", f"{case_group_name}.Iy_equiv")
                self.connect("spar_props.J_equiv", f"{case_group_name}.J_equiv")
                self.connect("seg_mapper.main_r_elem", f"{case_group_name}.R_main_elem")
                self.connect("seg_mapper.main_t_elem", f"{case_group_name}.main_t_elem")
                self.connect("spar_props.I_main", f"{case_group_name}.I_main")
                if rear_on:
                    self.connect("seg_mapper.rear_r_elem", f"{case_group_name}.R_rear_elem")
                    self.connect("seg_mapper.rear_t_elem", f"{case_group_name}.rear_t_elem")
                    self.connect("spar_props.I_rear", f"{case_group_name}.I_rear")


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
    force_alloc_complex: bool = False,
) -> om.Problem:
    """Build the OpenMDAO structural optimization problem.

    Parameters
    ----------
    cfg : HPAConfig
    aircraft : Aircraft
    aero_loads : dict from LoadMapper.map_loads()
    materials_db : MaterialDB
    force_alloc_complex : bool, optional
        Forwarded to ``Problem.setup()`` so tests can run complex-step total
        derivative checks through the assembled structural model.

    Returns
    -------
    prob : om.Problem (setup but not run)
    """
    case_entries = _normalise_load_case_inputs(cfg, aero_loads)
    prob = om.Problem()
    model = prob.model

    seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
    n_seg = len(seg_lengths)
    n_elem = aircraft.wing.n_stations - 1
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
    solver_cfg = cfg.solver
    min_t = cfg.main_spar.min_wall_thickness
    max_t = solver_cfg.max_wall_thickness_m

    model.add_design_var(
        "struct.seg_mapper.main_t_seg",
        lower=min_t, upper=max_t,
        ref=0.002,  # scaling reference
    )

    model.add_design_var(
        "struct.seg_mapper.main_r_seg",
        lower=solver_cfg.min_radius_m, upper=solver_cfg.max_radius_m,
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
            lower=solver_cfg.min_radius_m, upper=solver_cfg.max_radius_m,
            ref=0.025,
        )

    # Thickness-to-radius geometric feasibility: t <= eta * R.
    ratio_limit = solver_cfg.max_thickness_to_radius_ratio
    model.add_subsystem(
        "main_thickness_ratio",
        om.ExecComp(
            "margin = eta * radius - thickness",
            margin={"shape": (n_seg,), "units": "m"},
            radius={"shape": (n_seg,), "units": "m"},
            thickness={"shape": (n_seg,), "units": "m"},
            eta=ratio_limit,
        ),
    )
    model.connect("struct.seg_mapper.main_r_seg", "main_thickness_ratio.radius")
    model.connect("struct.seg_mapper.main_t_seg", "main_thickness_ratio.thickness")
    model.add_constraint("main_thickness_ratio.margin", lower=0.0)

    if rear_on:
        model.add_subsystem(
            "rear_thickness_ratio",
            om.ExecComp(
                "margin = eta * radius - thickness",
                margin={"shape": (n_seg,), "units": "m"},
                radius={"shape": (n_seg,), "units": "m"},
                thickness={"shape": (n_seg,), "units": "m"},
                eta=ratio_limit,
            ),
        )
        model.connect("struct.seg_mapper.rear_r_seg", "rear_thickness_ratio.radius")
        model.connect("struct.seg_mapper.rear_t_seg", "rear_thickness_ratio.thickness")
        model.add_constraint("rear_thickness_ratio.margin", lower=0.0)

        # Main spar dominance constraints:
        #   1) radius margin per segment
        #   2) EI margin per element
        dominance_margin = solver_cfg.main_spar_dominance_margin_m
        ei_ratio = solver_cfg.main_spar_ei_ratio

        model.add_subsystem(
            "main_rear_radius_dominance",
            om.ExecComp(
                "margin = main_r - rear_r",
                margin={"shape": (n_seg,), "units": "m"},
                main_r={"shape": (n_seg,), "units": "m"},
                rear_r={"shape": (n_seg,), "units": "m"},
                has_diag_partials=True,
            ),
        )
        model.connect("struct.seg_mapper.main_r_seg", "main_rear_radius_dominance.main_r")
        model.connect("struct.seg_mapper.rear_r_seg", "main_rear_radius_dominance.rear_r")
        model.add_constraint(
            "main_rear_radius_dominance.margin",
            lower=dominance_margin,
        )

        model.add_subsystem(
            "main_rear_ei_dominance",
            om.ExecComp(
                "margin = ei_main - ratio * ei_rear",
                margin={"shape": (n_elem,), "units": "N*m**2"},
                ei_main={"shape": (n_elem,), "units": "N*m**2"},
                ei_rear={"shape": (n_elem,), "units": "N*m**2"},
                ratio=ei_ratio,
                has_diag_partials=True,
            ),
        )
        model.connect("struct.spar_props.EI_main", "main_rear_ei_dominance.ei_main")
        model.connect("struct.spar_props.EI_rear", "main_rear_ei_dominance.ei_rear")
        model.add_constraint("main_rear_ei_dominance.margin", lower=0.0)

    # ── Objective: minimise total spar mass ──
    model.add_objective("struct.mass.total_mass_full", ref=10.0)

    # ── Constraints ──
    if len(case_entries) == 1:
        load_case, _ = next(iter(case_entries.values()))
        twist_limit = (
            load_case.max_twist_deg
            if load_case.max_twist_deg is not None
            else cfg.wing.max_tip_twist_deg
        )
        deflection_limit = (
            load_case.max_tip_deflection_m
            if load_case.max_tip_deflection_m is not None
            else cfg.wing.max_tip_deflection_m
        )

        # 1. Stress: KS(σ/σ_allow - 1) ≤ 0
        model.add_constraint("struct.failure.failure", upper=0.0)

        # 2. Shell buckling: KS(buckling_ratio - 1) ≤ 0
        model.add_constraint("struct.buckling.buckling_index", upper=0.0)

        # 3. Twist: |θ_max| ≤ max_tip_twist_deg
        model.add_constraint("struct.twist.twist_max_deg", upper=twist_limit)

        # 4. Tip deflection constraint
        if deflection_limit is not None:
            model.add_constraint(
                "struct.tip_defl.tip_deflection_m",
                upper=deflection_limit,
            )
    else:
        for case_name, (load_case, _) in case_entries.items():
            twist_limit = (
                load_case.max_twist_deg
                if load_case.max_twist_deg is not None
                else cfg.wing.max_tip_twist_deg
            )
            deflection_limit = (
                load_case.max_tip_deflection_m
                if load_case.max_tip_deflection_m is not None
                else cfg.wing.max_tip_deflection_m
            )
            case_path = f"struct.case_{case_name}"
            model.add_constraint(f"{case_path}.failure", upper=0.0)
            model.add_constraint(f"{case_path}.buckling_index", upper=0.0)
            model.add_constraint(f"{case_path}.twist_max_deg", upper=twist_limit)
            if deflection_limit is not None:
                model.add_constraint(
                    f"{case_path}.tip_deflection_m",
                    upper=deflection_limit,
                )

    # ── Driver ──
    driver = prob.driver = om.ScipyOptimizeDriver()
    driver.options["optimizer"] = cfg.solver.optimizer
    driver.options["tol"] = cfg.solver.optimizer_tol
    driver.options["maxiter"] = cfg.solver.optimizer_maxiter
    driver.options["disp"] = True

    # ── Recorder (optional) ──
    # prob.driver.add_recorder(om.SqliteRecorder("hpa_opt.sql"))

    prob.setup(force_alloc_complex=force_alloc_complex)

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
    def _get_scalar(name: str) -> float:
        return float(np.asarray(prob.get_val(name)).item())

    struct_group = prob.model.struct
    nn = struct_group.options["aircraft"].wing.n_stations
    rear_on = struct_group.options["cfg"].rear_spar.enabled
    case_names = tuple(getattr(struct_group, "_case_names", ("default",)))
    multi_case = bool(getattr(struct_group, "_multi_case", False))

    res = {
        "spar_mass_half_kg": _get_scalar("struct.mass.spar_mass_half"),
        "spar_mass_full_kg": _get_scalar("struct.mass.spar_mass_full"),
        "total_mass_full_kg": _get_scalar("struct.mass.total_mass_full"),
        "case_names": case_names,
        "main_t_seg": prob.get_val("struct.seg_mapper.main_t_seg").copy(),
        "main_r_seg": prob.get_val("struct.seg_mapper.main_r_seg").copy(),
        "EI_main_elem": prob.get_val("struct.spar_props.EI_main").copy(),
    }

    if multi_case:
        case_results = {}
        for case_name in case_names:
            case_path = f"struct.case_{case_name}"
            case_res = {
                "failure": _get_scalar(f"{case_path}.failure"),
                "buckling_index": _get_scalar(f"{case_path}.buckling_index"),
                "twist_max_deg": _get_scalar(f"{case_path}.twist_max_deg"),
                "tip_deflection_m": _get_scalar(f"{case_path}.tip_deflection_m"),
                "disp": prob.get_val(f"{case_path}.disp").copy(),
                "vonmises_main": prob.get_val(f"{case_path}.vonmises_main").copy(),
            }
            if rear_on:
                case_res["vonmises_rear"] = prob.get_val(f"{case_path}.vonmises_rear").copy()
            case_results[case_name] = case_res

        res["cases"] = case_results
        res["failure"] = max(case["failure"] for case in case_results.values())
        res["buckling_index"] = max(case["buckling_index"] for case in case_results.values())
        res["twist_max_deg"] = max(case["twist_max_deg"] for case in case_results.values())
        res["tip_deflection_m"] = max(case["tip_deflection_m"] for case in case_results.values())
        res["disp"] = None
        res["vonmises_main"] = None
        if rear_on:
            res["vonmises_rear"] = None
    else:
        res["failure"] = _get_scalar("struct.failure.failure")
        res["buckling_index"] = _get_scalar("struct.buckling.buckling_index")
        res["twist_max_deg"] = _get_scalar("struct.twist.twist_max_deg")
        res["disp"] = prob.get_val("struct.fem.disp").copy()
        res["tip_deflection_m"] = _get_scalar("struct.tip_defl.tip_deflection_m")
        res["vonmises_main"] = prob.get_val("struct.stress.vonmises_main").copy()
        if rear_on:
            res["vonmises_rear"] = prob.get_val("struct.stress.vonmises_rear").copy()

    if rear_on:
        res["rear_t_seg"] = prob.get_val("struct.seg_mapper.rear_t_seg").copy()
        res["rear_r_seg"] = prob.get_val("struct.seg_mapper.rear_r_seg").copy()
        res["EI_rear_elem"] = prob.get_val("struct.spar_props.EI_rear").copy()

    return res
