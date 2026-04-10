from __future__ import annotations

import numpy as np

from hpa_mdo.structure.dual_beam_analysis import solve_dual_beam_system


def _simple_beam_nodes(n_nodes: int, x: float) -> np.ndarray:
    nodes = np.zeros((n_nodes, 3))
    nodes[:, 0] = x
    nodes[:, 1] = np.linspace(0.0, 3.0, n_nodes)
    return nodes


def _simple_props(n_elem: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    area = np.full(n_elem, 1.0e-3)
    i_val = np.full(n_elem, 8.0e-7)
    j_val = np.full(n_elem, 1.6e-6)
    return area, i_val, i_val.copy(), j_val


def test_dual_beam_links_reduce_main_tip_deflection_and_share_motion() -> None:
    nn = 4
    ne = nn - 1
    nodes_main = _simple_beam_nodes(nn, x=0.0)
    nodes_rear = _simple_beam_nodes(nn, x=1.0)

    area_m, iy_m, iz_m, j_m = _simple_props(ne)
    area_r, iy_r, iz_r, j_r = _simple_props(ne)

    loads_main = np.zeros(nn)
    loads_rear = np.zeros(nn)
    loads_main[-1] = 100.0

    disp_main_free, disp_rear_free, total_fz_free = solve_dual_beam_system(
        nodes_main=nodes_main,
        nodes_rear=nodes_rear,
        area_main=area_m,
        iy_main=iy_m,
        iz_main=iz_m,
        j_main=j_m,
        area_rear=area_r,
        iy_rear=iy_r,
        iz_rear=iz_r,
        j_rear=j_r,
        young_main=70.0e6,
        shear_main=27.0e6,
        young_rear=70.0e6,
        shear_rear=27.0e6,
        loads_main_fz_n=loads_main,
        loads_rear_fz_n=loads_rear,
        joint_node_indices=[],
        wire_node_indices=[],
        bc_penalty=1.0e8,
        link_penalty=1.0e8,
    )

    disp_main_linked, disp_rear_linked, total_fz_linked = solve_dual_beam_system(
        nodes_main=nodes_main,
        nodes_rear=nodes_rear,
        area_main=area_m,
        iy_main=iy_m,
        iz_main=iz_m,
        j_main=j_m,
        area_rear=area_r,
        iy_rear=iy_r,
        iz_rear=iz_r,
        j_rear=j_r,
        young_main=70.0e6,
        shear_main=27.0e6,
        young_rear=70.0e6,
        shear_rear=27.0e6,
        loads_main_fz_n=loads_main,
        loads_rear_fz_n=loads_rear,
        joint_node_indices=list(range(nn)),
        wire_node_indices=[],
        bc_penalty=1.0e8,
        link_penalty=1.0e8,
    )

    assert total_fz_free == total_fz_linked == 100.0
    assert abs(disp_rear_free[-1, 2]) < 1e-10
    assert abs(disp_main_linked[-1, 2]) < abs(disp_main_free[-1, 2])
    assert np.allclose(disp_main_linked[:, 2], disp_rear_linked[:, 2], rtol=0.0, atol=1e-6)


def test_dual_beam_wire_constraint_clamps_main_uz_at_wire_node() -> None:
    nn = 4
    ne = nn - 1
    nodes_main = _simple_beam_nodes(nn, x=0.0)
    nodes_rear = _simple_beam_nodes(nn, x=1.0)

    area_m, iy_m, iz_m, j_m = _simple_props(ne)
    area_r, iy_r, iz_r, j_r = _simple_props(ne)

    loads_main = np.zeros(nn)
    loads_rear = np.zeros(nn)
    loads_main[-1] = 100.0
    wire_node = 2

    disp_main, _, _ = solve_dual_beam_system(
        nodes_main=nodes_main,
        nodes_rear=nodes_rear,
        area_main=area_m,
        iy_main=iy_m,
        iz_main=iz_m,
        j_main=j_m,
        area_rear=area_r,
        iy_rear=iy_r,
        iz_rear=iz_r,
        j_rear=j_r,
        young_main=70.0e6,
        shear_main=27.0e6,
        young_rear=70.0e6,
        shear_rear=27.0e6,
        loads_main_fz_n=loads_main,
        loads_rear_fz_n=loads_rear,
        joint_node_indices=[],
        wire_node_indices=[wire_node],
        bc_penalty=1.0e8,
        link_penalty=1.0e8,
    )

    assert abs(disp_main[wire_node, 2]) < 1e-5
