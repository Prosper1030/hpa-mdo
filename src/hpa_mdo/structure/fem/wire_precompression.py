"""Pre-compression force in spar from inclined lift-wire reaction."""
from __future__ import annotations

import numpy as np


def wire_axial_precompression(
    y_nodes: np.ndarray,
    lift_per_span: np.ndarray,
    node_spacings: np.ndarray,
    wire_attachment_indices: list[int],
    wire_angle_deg: float | list[float] | np.ndarray,
) -> np.ndarray:
    """Return axial pre-compression force [N] at each FEM element.

    For each element between the root (node 0) and a wire attachment node,
    add the horizontal component of wire tension as compressive pre-stress.
    Elements outboard of a wire attachment carry zero extra load from that wire.
    """

    y_nodes_arr = np.asarray(y_nodes, dtype=float)
    lift_arr = np.asarray(lift_per_span, dtype=float)
    spacing_arr = np.asarray(node_spacings, dtype=float)

    if y_nodes_arr.ndim != 1:
        raise ValueError("y_nodes must be a 1D array.")
    nn = y_nodes_arr.size
    if nn < 2:
        raise ValueError("y_nodes must contain at least two nodes.")
    if lift_arr.shape != (nn,):
        raise ValueError("lift_per_span must have shape (n_nodes,).")
    if spacing_arr.shape != (nn,):
        raise ValueError("node_spacings must have shape (n_nodes,).")
    ne = nn - 1
    if np.isscalar(wire_angle_deg):
        angle_values = np.full(len(wire_attachment_indices), float(wire_angle_deg), dtype=float)
    else:
        angle_values = np.asarray(wire_angle_deg, dtype=float).reshape(-1)
        if angle_values.size != len(wire_attachment_indices):
            raise ValueError(
                "wire_angle_deg must be a scalar or match wire_attachment_indices length."
            )

    p_precomp = np.zeros(ne, dtype=float)
    for att_raw, angle_deg in zip(wire_attachment_indices, angle_values, strict=True):
        if angle_deg <= 0.0 or angle_deg >= 90.0:
            raise ValueError("wire_angle_deg must satisfy 0 < wire_angle_deg < 90.")
        theta = np.deg2rad(float(angle_deg))
        tan_theta = np.tan(theta)
        if np.abs(tan_theta) < 1e-30:
            raise ValueError("wire_angle_deg is too close to 0 deg.")
        att_idx = int(att_raw)
        if att_idx < 0 or att_idx >= nn:
            raise ValueError(f"wire attachment index {att_idx} out of bounds for {nn} nodes.")
        if att_idx == 0:
            continue

        outboard_lift = float(np.sum(lift_arr[att_idx:] * spacing_arr[att_idx:]))
        outboard_lift = max(outboard_lift, 0.0)
        p_comp_wire = outboard_lift / tan_theta
        p_precomp[: min(att_idx, ne)] += p_comp_wire

    return p_precomp
