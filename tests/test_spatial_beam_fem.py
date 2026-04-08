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
    prob.set_val("Iz_equiv", np.zeros(ne))
    prob.set_val("J_equiv", np.zeros(ne))
    loads = np.zeros((nn, 6))
    loads[:, 2] = 100.0
    prob.set_val("loads", loads)

    with pytest.raises(om.AnalysisError):
        prob.run_model()


def _run_tip_lateral_deflection(iz_val: float) -> float:
    nn = 3
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
    nodes[:, 0] = np.linspace(0.0, 2.0, nn)
    prob.set_val("nodes", nodes)
    prob.set_val("EI_flap", np.full(ne, 1.0e5))
    prob.set_val("GJ", np.full(ne, 1.0e8))
    prob.set_val("A_equiv", np.full(ne, 10.0))
    prob.set_val("Iy_equiv", np.full(ne, 0.01))
    prob.set_val("Iz_equiv", np.full(ne, iz_val))
    prob.set_val("J_equiv", np.full(ne, 0.01))

    loads = np.zeros((nn, 6))
    loads[-1, 1] = 10.0
    prob.set_val("loads", loads)
    prob.run_model()
    return float(np.asarray(prob.get_val("disp")[-1, 1]).item())


def test_spatial_beam_fem_uses_independent_iz_for_lateral_bending():
    """Larger Iz should reduce tip-lateral displacement under Fy loading."""
    disp_small_iz = abs(_run_tip_lateral_deflection(iz_val=0.002))
    disp_large_iz = abs(_run_tip_lateral_deflection(iz_val=0.02))
    assert disp_large_iz < disp_small_iz * 0.6
