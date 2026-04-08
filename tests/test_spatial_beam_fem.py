from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest

from hpa_mdo.structure.oas_structural import SpatialBeamFEM


def test_spatial_beam_fem_raises_analysis_error_on_invalid_section_properties():
    nn = 4
    ne = nn - 1
    prob = om.Problem()
    prob.model.add_subsystem(
        "fem",
        SpatialBeamFEM(
            n_nodes=nn,
            E_avg=1.0,
            G_avg=1.0,
            fixed_node=0,
            lift_wire_nodes=None,
        ),
        promotes=["*"],
    )
    prob.setup()

    nodes = np.zeros((nn, 3))
    nodes[:, 1] = np.linspace(0.0, 3.0, nn)
    prob.set_val("nodes", nodes)
    prob.set_val("EI_flap", np.zeros(ne))
    prob.set_val("GJ", np.zeros(ne))
    prob.set_val("A_equiv", np.zeros(ne))
    prob.set_val("Iy_equiv", np.zeros(ne))
    prob.set_val("J_equiv", np.zeros(ne))
    loads = np.zeros((nn, 6))
    loads[:, 2] = 100.0
    prob.set_val("loads", loads)

    with pytest.raises(om.AnalysisError):
        prob.run_model()
