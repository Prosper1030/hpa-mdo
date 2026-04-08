from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest

from hpa_mdo.structure.oas_structural import TwistConstraintComp


def _run_twist_constraint(disp: np.ndarray, nodes: np.ndarray) -> float:
    nn = disp.shape[0]
    prob = om.Problem()
    indeps = prob.model.add_subsystem("indeps", om.IndepVarComp(), promotes=["*"])
    indeps.add_output("disp", val=disp)
    indeps.add_output("nodes", val=nodes, units="m")
    prob.model.add_subsystem(
        "twist",
        TwistConstraintComp(n_nodes=nn),
        promotes_inputs=["disp", "nodes"],
    )
    prob.setup()
    prob.run_model()
    return float(np.asarray(prob.get_val("twist.twist_max_deg")).item())


def test_twist_max_uses_all_nodes_not_just_tip():
    disp = np.zeros((5, 6))
    disp[2, 4] = 0.03  # mid-span twist [rad]
    disp[-1, 4] = 0.01  # tip twist [rad]
    nodes = np.zeros((5, 3))
    nodes[:, 1] = np.linspace(0.0, 4.0, 5)

    twist_max_deg = _run_twist_constraint(disp, nodes)
    mid_deg = 0.03 * 180.0 / np.pi
    tip_deg = 0.01 * 180.0 / np.pi

    assert twist_max_deg > tip_deg * 1.3
    assert twist_max_deg == pytest.approx(mid_deg, rel=0.1)


def test_twist_uses_local_axis_projection():
    """Twist should follow rotation about local beam axis, not a fixed global axis."""
    disp = np.zeros((4, 6))
    # Beam aligned with global X -> local twist is DOF 3 (global θx).
    disp[-1, 3] = 0.02
    nodes = np.zeros((4, 3))
    nodes[:, 0] = np.linspace(0.0, 3.0, 4)

    twist_max_deg = _run_twist_constraint(disp, nodes)
    expected_deg = 0.02 * 180.0 / np.pi
    assert twist_max_deg == pytest.approx(expected_deg, rel=0.1)
