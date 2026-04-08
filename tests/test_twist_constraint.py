from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest

from hpa_mdo.structure.oas_structural import TwistConstraintComp


def _run_twist_constraint(disp: np.ndarray) -> float:
    nn = disp.shape[0]
    prob = om.Problem()
    indeps = prob.model.add_subsystem("indeps", om.IndepVarComp(), promotes=["*"])
    indeps.add_output("disp", val=disp)
    prob.model.add_subsystem("twist", TwistConstraintComp(n_nodes=nn), promotes_inputs=["disp"])
    prob.setup()
    prob.run_model()
    return float(np.asarray(prob.get_val("twist.twist_max_deg")).item())


def test_twist_max_uses_all_nodes_not_just_tip():
    disp = np.zeros((5, 6))
    disp[2, 4] = 0.03  # mid-span twist [rad]
    disp[-1, 4] = 0.01  # tip twist [rad]

    twist_max_deg = _run_twist_constraint(disp)
    mid_deg = 0.03 * 180.0 / np.pi
    tip_deg = 0.01 * 180.0 / np.pi

    assert twist_max_deg > tip_deg * 1.3
    assert twist_max_deg == pytest.approx(mid_deg, rel=0.1)
