from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest

from hpa_mdo.core.constants import G_STANDARD
from hpa_mdo.structure.components.loads import ExternalLoadsComp


def _run_external_loads(
    *,
    lift_per_span: np.ndarray,
    torque_per_span: np.ndarray,
    node_spacings: np.ndarray,
    element_lengths: np.ndarray,
    mass_per_length: np.ndarray,
    rear_mass_per_length: np.ndarray | None = None,
    gravity_scale: float = 1.0,
    rear_gravity_torque_per_span: np.ndarray | None = None,
    rear_torque_arm: np.ndarray | None = None,
) -> np.ndarray:
    nn = int(lift_per_span.size)
    ne = nn - 1
    prob = om.Problem()
    prob.model.add_subsystem(
        "ext_loads",
        ExternalLoadsComp(
            n_nodes=nn,
            lift_per_span=lift_per_span,
            torque_per_span=torque_per_span,
            node_spacings=node_spacings,
            element_lengths=element_lengths,
            gravity_scale=gravity_scale,
            rear_gravity_torque_per_span=rear_gravity_torque_per_span,
            rear_torque_arm=rear_torque_arm,
        ),
        promotes=["*"],
    )
    prob.setup()
    prob.set_val("mass_per_length", mass_per_length, units="kg/m")
    if rear_mass_per_length is not None:
        prob.set_val("rear_mass_per_length", rear_mass_per_length, units="kg/m")
    else:
        prob.set_val("rear_mass_per_length", np.zeros(ne), units="kg/m")
    prob.run_model()
    return np.asarray(prob.get_val("loads"))


def test_external_loads_adds_rear_gravity_torque_to_torsion_dof():
    node_spacings = np.array([0.5, 1.0, 1.0, 0.5])
    loads = _run_external_loads(
        lift_per_span=np.zeros(4),
        torque_per_span=np.array([4.0, 3.0, 2.0, 1.0]),
        node_spacings=node_spacings,
        element_lengths=np.ones(3),
        mass_per_length=np.zeros(3),
        gravity_scale=1.5,
        rear_gravity_torque_per_span=np.array([1.0, 2.0, 3.0, 4.0]),
    )

    expected_my = (np.array([4.0, 3.0, 2.0, 1.0]) - 1.5 * np.array([1.0, 2.0, 3.0, 4.0])) * node_spacings
    np.testing.assert_allclose(loads[:, 4], expected_my)
    np.testing.assert_allclose(loads[:, 2], 0.0)


def test_external_loads_rear_gravity_torque_tracks_rear_mass_distribution():
    element_lengths = np.array([1.0, 2.0, 1.5])
    rear_mass_per_length = np.array([1.0, 2.0, 3.0])
    rear_torque_arm = np.array([0.4, 0.3, 0.2])
    gravity_scale = 1.25

    loads = _run_external_loads(
        lift_per_span=np.zeros(4),
        torque_per_span=np.zeros(4),
        node_spacings=np.array([0.5, 1.5, 1.75, 0.75]),
        element_lengths=element_lengths,
        mass_per_length=np.zeros(3),
        rear_mass_per_length=rear_mass_per_length,
        gravity_scale=gravity_scale,
        rear_torque_arm=rear_torque_arm,
    )

    elem_torque = rear_mass_per_length * G_STANDARD * gravity_scale * rear_torque_arm * element_lengths
    expected_my = np.array(
        [
            -0.5 * elem_torque[0],
            -0.5 * (elem_torque[0] + elem_torque[1]),
            -0.5 * (elem_torque[1] + elem_torque[2]),
            -0.5 * elem_torque[2],
        ]
    )
    np.testing.assert_allclose(loads[:, 4], expected_my)
    np.testing.assert_allclose(loads[:, 2], 0.0)


def test_external_loads_legacy_weight_path_unchanged_when_rear_torque_disabled():
    node_spacings = np.array([0.5, 1.0, 1.0, 0.5])
    element_lengths = np.ones(3)
    lift = np.array([10.0, 20.0, 30.0, 40.0])
    mpl = np.array([3.0, 5.0, 7.0])
    gravity_scale = 2.0
    g = G_STANDARD * gravity_scale

    loads = _run_external_loads(
        lift_per_span=lift,
        torque_per_span=np.zeros(4),
        node_spacings=node_spacings,
        element_lengths=element_lengths,
        mass_per_length=mpl,
        gravity_scale=gravity_scale,
        rear_gravity_torque_per_span=None,
    )

    expected_fz = lift * node_spacings
    expected_fz[0] -= 0.5 * mpl[0] * g * element_lengths[0]
    expected_fz[1] -= 0.5 * mpl[0] * g * element_lengths[0] + 0.5 * mpl[1] * g * element_lengths[1]
    expected_fz[2] -= 0.5 * mpl[1] * g * element_lengths[1] + 0.5 * mpl[2] * g * element_lengths[2]
    expected_fz[3] -= 0.5 * mpl[2] * g * element_lengths[2]

    np.testing.assert_allclose(loads[:, 2], expected_fz)
    np.testing.assert_allclose(loads[:, 4], 0.0)


def test_external_loads_validates_rear_gravity_torque_shape():
    with pytest.raises(ValueError, match="rear_gravity_torque_per_span must have shape"):
        _run_external_loads(
            lift_per_span=np.zeros(4),
            torque_per_span=np.zeros(4),
            node_spacings=np.array([0.5, 1.0, 1.0, 0.5]),
            element_lengths=np.ones(3),
            mass_per_length=np.zeros(3),
            rear_gravity_torque_per_span=np.ones(3),
        )
