from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.laminate import (
    PlyStack,
    compute_ABD,
    ply_Q_matrix,
    rotated_Q,
    tube_equivalent_from_layup,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "materials.yaml"


@pytest.fixture(scope="module")
def ply_material():
    return MaterialDB(DB_PATH).get_ply("cfrp_ply_hm")


def test_ply_stack_half_sequence_and_validation() -> None:
    stack = PlyStack(n_0=1, n_45=1, n_90=1)

    assert stack.total_half_plies() == 4
    assert stack.total_plies() == 8
    assert stack.angle_sequence_half() == (90.0, 0.0, 45.0, -45.0)
    assert stack.validate() == []


def test_ply_q_matrix_matches_reference_values(ply_material) -> None:
    Q = ply_Q_matrix(
        E1=ply_material.E1,
        E2=ply_material.E2,
        G12=ply_material.G12,
        nu12=ply_material.nu12,
    )

    assert Q[0, 0] == pytest.approx(230.58468255158297e9)
    assert Q[1, 1] == pytest.approx(8.020336784402886e9)
    assert Q[0, 1] == pytest.approx(2.165490931788779e9)
    assert Q[2, 2] == pytest.approx(5.0e9)


def test_rotated_q_matches_zero_and_ninety_degree_limits(ply_material) -> None:
    Q = ply_Q_matrix(
        E1=ply_material.E1,
        E2=ply_material.E2,
        G12=ply_material.G12,
        nu12=ply_material.nu12,
    )

    np.testing.assert_allclose(rotated_Q(Q, 0.0), Q)

    Q_90 = rotated_Q(Q, 90.0)
    assert Q_90[0, 0] == pytest.approx(Q[1, 1], rel=1e-9)
    assert Q_90[1, 1] == pytest.approx(Q[0, 0], rel=1e-9)


def test_compute_abd_zeroes_b_matrix_for_symmetric_stack(ply_material) -> None:
    Q = ply_Q_matrix(
        E1=ply_material.E1,
        E2=ply_material.E2,
        G12=ply_material.G12,
        nu12=ply_material.nu12,
    )
    stack = PlyStack(n_0=2, n_45=1, n_90=0)

    _, B, _ = compute_ABD(
        ply_angles_deg=stack.angle_sequence_half(),
        t_ply=ply_material.t_ply,
        Q=Q,
        symmetric=True,
    )

    np.testing.assert_allclose(B, np.zeros((3, 3)), atol=1e-10)


def test_tube_equivalent_for_mixed_stack_has_intermediate_axial_modulus(ply_material) -> None:
    stack = PlyStack(n_0=2, n_45=1, n_90=0)
    props = tube_equivalent_from_layup(stack, ply_material, R_outer=0.03)

    assert props.wall_thickness == pytest.approx(1.0e-3)
    assert 100.0e9 <= props.E_axial <= 160.0e9
    assert props.EI_bending > 0.0
    assert props.GJ_torsion > 0.0


def test_tube_equivalent_for_zero_degree_stack_approaches_fiber_modulus(ply_material) -> None:
    stack = PlyStack(n_0=1, n_45=0, n_90=0)
    props = tube_equivalent_from_layup(stack, ply_material, R_outer=0.03)

    assert props.E_axial == pytest.approx(ply_material.E1, rel=0.01)
