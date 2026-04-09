"""Per-load-case structural group wiring shared components."""
from __future__ import annotations

import numpy as np
import openmdao.api as om

from hpa_mdo.structure.buckling import BucklingComp
from hpa_mdo.structure.components.constraints import (
    KSFailureComp,
    TipDeflectionConstraintComp,
    TwistConstraintComp,
    VonMisesStressComp,
)
from hpa_mdo.structure.components.loads import ExternalLoadsComp
from hpa_mdo.structure.fem.assembly import SpatialBeamFEM


class StructuralLoadCaseGroup(om.Group):
    """One structural load case branch sharing geometry and spar properties."""

    def initialize(self):
        self.options.declare("load_case", desc="LoadCaseConfig object")
        self.options.declare("n_nodes", types=int)
        self.options.declare("lift_per_span", types=np.ndarray)
        self.options.declare("torque_per_span", types=np.ndarray)
        self.options.declare(
            "rear_gravity_torque_per_span",
            default=None,
            allow_none=True,
            desc="(nn,) rear spar gravity torque distribution [N.m/m]. None = disabled.",
        )
        self.options.declare(
            "rear_torque_arm",
            default=None,
            allow_none=True,
            desc="(ne,) chordwise lever arm [m] for rear-spar gravity torque.",
        )
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
        self.options.declare(
            "wire_precompression",
            default=None,
            allow_none=True,
            desc="(ne,) axial pre-compression [N] from lift-wire reaction.",
        )
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
        lift = np.asarray(self.options["lift_per_span"], dtype=float)
        torque = np.asarray(self.options["torque_per_span"], dtype=float)

        self.add_subsystem(
            "ext_loads",
            ExternalLoadsComp(
                n_nodes=nn,
                lift_per_span=lift,
                torque_per_span=torque,
                node_spacings=self.options["node_spacings"],
                element_lengths=self.options["element_lengths"],
                gravity_scale=load_case.gravity_scale,
                rear_gravity_torque_per_span=self.options["rear_gravity_torque_per_span"],
                rear_torque_arm=self.options["rear_torque_arm"],
            ),
            promotes_inputs=["mass_per_length", "rear_mass_per_length"],
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
            promotes_inputs=["nodes", "EI_flap", "GJ", "A_equiv", "Iy_equiv", "Iz_equiv", "J_equiv"],
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
                wire_precompression=self.options["wire_precompression"],
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
                wire_precompression=self.options["wire_precompression"],
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
