from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hpa_mdo.mass import DistributedMass, LineMass, MassBudget, PointMass, tube_inertia


def test_two_point_masses_place_cg_at_midpoint_and_build_expected_izz() -> None:
    budget = MassBudget(reference_point_m=(0.0, 0.0, 0.0))
    budget.add(PointMass(name="left", m_kg=1.0, xyz_m=(0.0, 0.0, 0.0)))
    budget.add(PointMass(name="right", m_kg=1.0, xyz_m=(2.0, 0.0, 0.0)))

    cg = budget.center_of_gravity()
    inertia = budget.inertia_tensor(about="cg")

    np.testing.assert_allclose(cg, np.array([1.0, 0.0, 0.0]))
    assert inertia[2, 2] == pytest.approx(2.0)
    assert inertia[0, 0] == pytest.approx(0.0)
    assert inertia[0, 1] == pytest.approx(0.0)


def test_tube_inertia_matches_closed_form_about_local_x_axis() -> None:
    inertia = tube_inertia(
        mass_kg=2.0,
        length_m=3.0,
        r_outer_m=0.2,
        r_inner_m=0.1,
        axis="x",
    )

    expected_i_xx = 0.5 * 2.0 * (0.2**2 + 0.1**2)
    expected_i_yy = (2.0 / 12.0) * (3.0 * (0.2**2 + 0.1**2) + 3.0**2)

    np.testing.assert_allclose(
        inertia,
        np.diag([expected_i_xx, expected_i_yy, expected_i_yy]),
    )


def test_yaml_round_trip_preserves_distributed_mass(tmp_path: Path) -> None:
    budget = MassBudget(reference_point_m=(0.0, 0.0, 0.0), target_total_mass_kg=4.0)
    budget.add(PointMass(name="pilot", m_kg=2.0, xyz_m=(1.0, 0.0, 0.0), sigma_kg=0.2))
    budget.add(
        DistributedMass.from_samples(
            name="main_spar_right",
            nodes_m=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [2.0, 0.0, 0.0],
                ]
            ),
            linear_kg_per_m=np.array([1.0, 1.0]),
            sigma_kg=0.1,
            segment_r_outer_m=np.array([0.02, 0.02]),
            segment_r_inner_m=np.array([0.018, 0.018]),
        )
    )

    path = tmp_path / "mass_budget.yaml"
    budget.to_yaml(path)
    restored = MassBudget.from_yaml(path)

    assert restored.total_mass() == pytest.approx(4.0)
    assert restored.target_total_mass_kg == pytest.approx(4.0)
    np.testing.assert_allclose(restored.center_of_gravity(), np.array([1.0, 0.0, 0.0]))
    assert isinstance(restored.components[0], PointMass)
    assert isinstance(restored.components[1], DistributedMass)


def test_avl_mass_text_matches_golden_string() -> None:
    budget = MassBudget(reference_point_m=(0.0, 0.0, 0.0))
    budget.add(PointMass(name="pilot", m_kg=2.0, xyz_m=(1.0, 0.0, 0.0)))
    budget.add(
        LineMass(
            name="boom",
            linear_kg_per_m=1.0,
            xyz_start_m=(0.0, 0.0, 0.0),
            xyz_end_m=(2.0, 0.0, 0.0),
        )
    )

    expected = "\n".join(
        [
            "# HPA-MDO AVL .mass file",
            "# Data rows: mass x y z Ixx Iyy Izz Ixy Ixz Iyz",
            "Lunit = 1.0 m",
            "Munit = 1.0 kg",
            "Tunit = 1.0 s",
            "g = 9.810000",
            "rho = 1.225000",
            "#",
            "# mass x y z Ixx Iyy Izz Ixy Ixz Iyz",
            "*   1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0 1.0",
            "+   0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0",
            "    2.000000     1.000000     0.000000     0.000000     0.000000     0.000000     0.000000     0.000000     0.000000     0.000000 ! pilot",
            "    2.000000     1.000000     0.000000     0.000000     0.000000     0.666667     0.666667     0.000000     0.000000     0.000000 ! boom",
            "",
            "! Mbody 4.000000 0.000000 0.666667 0.666667 0.000000 0.000000 0.000000 1.000000 0.000000 0.000000",
            "",
        ]
    )

    assert budget.avl_mass_text() == expected
