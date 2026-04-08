from __future__ import annotations

import numpy as np
import openmdao.api as om

from hpa_mdo.structure.oas_structural import VonMisesStressComp


def _build_prob(z_main: np.ndarray, z_rear: np.ndarray) -> om.Problem:
    nn = len(z_main) + 1
    prob = om.Problem()
    prob.model.add_subsystem(
        "stress",
        VonMisesStressComp(
            n_nodes=nn,
            E_main=240e9,
            E_rear=240e9,
            G_main=90e9,
            G_rear=90e9,
            z_main=z_main,
            z_rear=z_rear,
            rear_enabled=True,
        ),
        promotes=["*"],
    )
    prob.setup(force_alloc_complex=True)
    return prob


def test_parallel_axis_offset_scales_vonmises_stress():
    """With equal spars, adding Z offset doubles stress when |d_z| == R."""
    nn = 5
    ne = nn - 1
    z0 = np.zeros(ne)
    z_off = np.full(ne, 0.04)

    prob_no_offset = _build_prob(z_main=z0, z_rear=z0)
    prob_with_offset = _build_prob(z_main=z_off, z_rear=z0)

    for prob in (prob_no_offset, prob_with_offset):
        prob["disp"] = np.zeros((nn, 6))
        # Beam axis along global Y; varying global Rx creates local bending curvature.
        prob["disp"][:, 3] = np.linspace(0.0, 0.02, nn)
        prob["nodes"] = np.column_stack(
            [np.zeros(nn), np.linspace(0.0, 4.0, nn), np.zeros(nn)]
        )
        prob["R_main_elem"] = np.full(ne, 0.02)
        prob["main_t_elem"] = np.full(ne, 0.001)
        prob["R_rear_elem"] = np.full(ne, 0.02)
        prob["rear_t_elem"] = np.full(ne, 0.001)
        # Inputs kept for interface compatibility; not used in current stress recovery.
        prob["I_main"] = np.full(ne, 1.0e-6)
        prob["I_rear"] = np.full(ne, 1.0e-6)
        prob["EI_flap"] = np.full(ne, 1.0e5)
        prob["GJ"] = np.full(ne, 1.0e5)
        prob.run_model()

    vm_main_0 = prob_no_offset.get_val("vonmises_main")
    vm_main_1 = prob_with_offset.get_val("vonmises_main")
    vm_rear_0 = prob_no_offset.get_val("vonmises_rear")
    vm_rear_1 = prob_with_offset.get_val("vonmises_rear")

    np.testing.assert_allclose(vm_main_1 / vm_main_0, np.full(ne, 2.0), rtol=1e-7)
    np.testing.assert_allclose(vm_rear_1 / vm_rear_0, np.full(ne, 2.0), rtol=1e-7)
