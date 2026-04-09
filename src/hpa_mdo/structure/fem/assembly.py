"""Finite-element assembly and solve for the structural beam model."""
from __future__ import annotations

import numpy as np
import openmdao.api as om

from hpa_mdo.core.logging import get_logger
from hpa_mdo.structure.fem.elements import (
    _cs_norm,
    _has_only_finite_values,
    _rotation_matrix,
    _timoshenko_element_stiffness,
    _transform_12x12,
)

logger = get_logger(__name__)


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
    Iz_equiv : (ne,) second moment of area in chordwise plane [m^4]
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
        self.add_input("Iz_equiv", shape=(ne,), units="m**4")
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
        for name in ("EI_flap", "GJ", "A_equiv", "Iy_equiv", "Iz_equiv", "J_equiv"):
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
        self._zero_jacobian_fallback_count = 0

    def _record_zero_jacobian_fallback(self, reason: str) -> None:
        """Track and log Jacobian fallback-to-zero events for visibility."""
        self._zero_jacobian_fallback_count = int(
            getattr(self, "_zero_jacobian_fallback_count", 0)
        ) + 1
        logger.warning(
            "SpatialBeamFEM.compute_partials fallback to zero Jacobian (%s). count=%d",
            reason,
            self._zero_jacobian_fallback_count,
        )

    def compute(self, inputs, outputs):
        nn = self.options["n_nodes"]
        ne = nn - 1
        fix = self.options["fixed_node"]

        nodes = inputs["nodes"]
        EI = inputs["EI_flap"]
        GJ_arr = inputs["GJ"]
        A = inputs["A_equiv"]
        Iy = inputs["Iy_equiv"]
        Iz = inputs["Iz_equiv"]
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
            Iz_e = Iz[e]
            J_e = J[e]
            A_e = A[e]
            if (
                not _has_only_finite_values(np.array([A_e, Iy_e, Iz_e, J_e, EI[e], GJ_arr[e]]))
                or np.real(A_e) <= 1e-20
                or np.real(Iy_e) <= 1e-20
                or np.real(Iz_e) <= 1e-20
                or np.real(J_e) <= 1e-20
            ):
                raise om.AnalysisError(
                    f"Invalid section properties at element {e} "
                    f"(A={A_e}, Iy={Iy_e}, Iz={Iz_e}, J={J_e})."
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
            self._record_zero_jacobian_fallback("missing_cached_linear_system")
            partials["disp", "loads"] = np.zeros((ndof, ndof))
            return

        try:
            load_jac = np.linalg.solve(k_global, load_selector)
        except np.linalg.LinAlgError:
            self._record_zero_jacobian_fallback("singular_k_global")
            load_jac = np.zeros((ndof, ndof), dtype=k_global.dtype)

        if (
            not _has_only_finite_values(load_jac)
            or float(np.max(np.abs(load_jac))) > max_disp_entry
        ):
            self._record_zero_jacobian_fallback("non_finite_or_overflow_jacobian")
            load_jac = np.zeros((ndof, ndof), dtype=k_global.dtype)

        partials["disp", "loads"] = np.real(load_jac).ravel()
