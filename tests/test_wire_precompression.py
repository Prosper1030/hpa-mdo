from __future__ import annotations

import numpy as np

from hpa_mdo.structure.fem.wire_precompression import wire_axial_precompression


def test_wire_precompression_applies_only_inboard_of_attachment():
    y = np.linspace(0.0, 5.0, 6)
    lift = np.full_like(y, 10.0)
    ds = np.ones_like(y)

    p = wire_axial_precompression(
        y_nodes=y,
        lift_per_span=lift,
        node_spacings=ds,
        wire_attachment_indices=[3],
        wire_angle_deg=45.0,
    )

    np.testing.assert_allclose(p[:3], np.full(3, 30.0), rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(p[3:], np.zeros(2), rtol=1e-12, atol=1e-12)


def test_wire_precompression_accumulates_multiple_wires():
    y = np.linspace(0.0, 5.0, 6)
    lift = np.full_like(y, 10.0)
    ds = np.ones_like(y)

    p = wire_axial_precompression(
        y_nodes=y,
        lift_per_span=lift,
        node_spacings=ds,
        wire_attachment_indices=[2, 4],
        wire_angle_deg=45.0,
    )

    np.testing.assert_allclose(p, np.array([60.0, 60.0, 20.0, 20.0, 0.0]), rtol=1e-12, atol=1e-12)


def test_wire_precompression_clips_negative_outboard_lift():
    y = np.linspace(0.0, 5.0, 6)
    lift = np.full_like(y, -10.0)
    ds = np.ones_like(y)

    p = wire_axial_precompression(
        y_nodes=y,
        lift_per_span=lift,
        node_spacings=ds,
        wire_attachment_indices=[3],
        wire_angle_deg=45.0,
    )

    np.testing.assert_allclose(p, np.zeros(5), rtol=1e-12, atol=1e-12)
