"""External load mapping component for structural FEM nodes."""
from __future__ import annotations

import numpy as np
import openmdao.api as om

from hpa_mdo.core.constants import G_STANDARD


class ExternalLoadsComp(om.ExplicitComponent):
    """Convert aero lift/torque distributions + spar weight into FEM loads.

    Applies:
        - Aerodynamic lift (Fz) at design load level
        - Aerodynamic pitching moment (Mx torque)
        - Spar self-weight / inertia (negative Fz), scaled by load factor
        - Rear spar gravity torque about the span axis (negative My)
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
        self.options.declare(
            "rear_gravity_torque_per_span",
            default=None,
            allow_none=True,
            desc=(
                "(nn,) distributed torsional moment from rear spar self-weight "
                "[N.m/m] at each spanwise node. Applied at DOF 4 (My, spanwise "
                "torsion). None = disabled (legacy behaviour)."
            ),
        )
        self.options.declare(
            "rear_torque_arm",
            default=None,
            allow_none=True,
            desc=(
                "(ne,) chordwise lever arm from beam axis to rear spar centroid [m]. "
                "When provided, rear_mass_per_length generates rear-spar gravity "
                "torsion using the current structural design."
            ),
        )

    def setup(self):
        nn = self.options["n_nodes"]
        ne = nn - 1
        self.add_input("mass_per_length", shape=(ne,), units="kg/m")
        self.add_input("rear_mass_per_length", shape=(ne,), units="kg/m", val=np.zeros(ne))
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

        rear_torque_arm = self.options["rear_torque_arm"]
        if rear_torque_arm is not None:
            rear_torque_arm_arr = np.asarray(rear_torque_arm, dtype=float)
            if rear_torque_arm_arr.shape != (ne,):
                raise ValueError(
                    "rear_torque_arm must have shape "
                    f"({ne},), got {rear_torque_arm_arr.shape}"
                )

            torque_rows = []
            torque_cols = []
            torque_vals = []
            for e, (length, arm) in enumerate(zip(element_lengths, rear_torque_arm_arr, strict=True)):
                torque_sensitivity = -0.5 * g_scaled * arm * length
                torque_rows.extend([e * 6 + 4, (e + 1) * 6 + 4])
                torque_cols.extend([e, e])
                torque_vals.extend([torque_sensitivity, torque_sensitivity])
            self.declare_partials(
                "loads",
                "rear_mass_per_length",
                rows=torque_rows,
                cols=torque_cols,
                val=torque_vals,
            )

    def compute(self, inputs, outputs):
        nn = self.options["n_nodes"]
        ne = nn - 1
        lift = self.options["lift_per_span"]
        torque = self.options["torque_per_span"]
        ds = self.options["node_spacings"]
        element_lengths = self.options["element_lengths"]
        mpl = inputs["mass_per_length"]
        rear_mpl = inputs["rear_mass_per_length"]
        g = G_STANDARD * self.options["gravity_scale"]

        loads = np.zeros((nn, 6), dtype=mpl.dtype)

        # Lift contribution (integrate over tributary length)
        for i in range(nn):
            loads[i, 2] = lift[i] * ds[i]
            # My = design torque (torsion about span/Y axis)
            # For beam along Y: torsion maps to global DOF 4 (θy)
            loads[i, 4] = torque[i] * ds[i]

        rear_torque_arm = self.options["rear_torque_arm"]
        if rear_torque_arm is not None:
            rear_torque_arm_arr = np.asarray(rear_torque_arm, dtype=rear_mpl.dtype)
            if rear_torque_arm_arr.shape != (ne,):
                raise ValueError(
                    "rear_torque_arm must have shape "
                    f"({ne},), got {rear_torque_arm_arr.shape}"
                )

            for e in range(ne):
                # Rear spar self-weight acts downward aft of the beam axis.
                # In the FEM sign convention that trailing-edge-down torsion maps to -My.
                element_torque = rear_mpl[e] * g * rear_torque_arm_arr[e] * element_lengths[e]
                loads[e, 4] -= element_torque / 2.0
                loads[e + 1, 4] -= element_torque / 2.0

        rgt = self.options["rear_gravity_torque_per_span"]
        if rgt is not None:
            rgt_arr = np.asarray(rgt)
            if rgt_arr.shape != (nn,):
                raise ValueError(
                    "rear_gravity_torque_per_span must have shape "
                    f"({nn},), got {rgt_arr.shape}"
                )
            g_scale = self.options["gravity_scale"]
            for i in range(nn):
                # Positive rear-gravity magnitude corresponds to trailing-edge-down
                # physical torque, which maps to negative My in the FEM sign convention.
                loads[i, 4] -= rgt_arr[i] * ds[i] * g_scale

        # Weight contribution (lumped mass per element, split to endpoints)
        for e in range(ne):
            element_weight = mpl[e] * g * element_lengths[e]
            loads[e, 2] -= element_weight / 2.0
            loads[e + 1, 2] -= element_weight / 2.0

        outputs["loads"] = loads
