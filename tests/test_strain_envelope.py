from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest

from hpa_mdo.structure.oas_structural import StrainEnvelopeComp


def test_strain_envelope_recovers_segment_absmax_kinematics() -> None:
    nodes = np.zeros((4, 3))
    nodes[:, 0] = np.linspace(0.0, 3.0, 4)

    disp = np.zeros((4, 6))
    disp[:, 0] = [0.0, 1.0e-3, 3.0e-3, 3.0e-3]
    disp[:, 3] = [0.0, 1.0e-2, 1.0e-2, -1.0e-2]
    disp[:, 4] = [0.0, 0.0, 3.0e-2, 3.0e-2]

    prob = om.Problem()
    indeps = prob.model.add_subsystem("indeps", om.IndepVarComp(), promotes=["*"])
    indeps.add_output("disp", val=disp)
    indeps.add_output("nodes", val=nodes, units="m")
    prob.model.add_subsystem(
        "strain_env",
        StrainEnvelopeComp(
            n_nodes=4,
            segment_boundaries=np.array([0.0, 1.5, 3.0]),
            element_centres=np.array([0.5, 1.5, 2.5]),
        ),
        promotes_inputs=["disp", "nodes"],
    )

    prob.setup()
    prob.run_model()

    np.testing.assert_allclose(
        prob.get_val("strain_env.epsilon_x_absmax"),
        np.array([1.0e-3, 2.0e-3]),
    )
    np.testing.assert_allclose(
        prob.get_val("strain_env.kappa_absmax"),
        np.array([0.0, 3.0e-2]),
        atol=1.0e-12,
    )
    np.testing.assert_allclose(
        prob.get_val("strain_env.torsion_rate_absmax"),
        np.array([1.0e-2, 2.0e-2]),
    )


def test_strain_envelope_requires_segment_boundaries() -> None:
    prob = om.Problem()
    prob.model.add_subsystem(
        "strain_env",
        StrainEnvelopeComp(
            n_nodes=2,
            segment_boundaries=np.array([0.0]),
            element_centres=np.array([0.5]),
        ),
    )

    with pytest.raises(ValueError, match="segment_boundaries"):
        prob.setup()
