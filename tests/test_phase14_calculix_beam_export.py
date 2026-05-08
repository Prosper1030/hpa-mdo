from __future__ import annotations

from pathlib import Path

import numpy as np

from hpa_mdo.hifi.frd_parser import parse_total_force_from_dat
from hpa_mdo.structure.calculix_beam_export import (
    BeamMaterial,
    build_dual_pipe_benchmark_spec,
    build_single_pipe_cantilever_spec,
    cantilever_tip_deflection_point_load,
    cantilever_tip_deflection_uniform_load,
    write_calculix_beam_inp,
)


def test_write_single_pipe_cantilever_includes_pipe_sections_boundary_and_loads(
    tmp_path: Path,
) -> None:
    material = BeamMaterial(
        name="MAIN",
        young_pa=135.0e9,
        poisson_ratio=0.3,
        density_kgpm3=1600.0,
    )
    y_nodes_m = np.linspace(0.0, 6.0, 7)
    outer_radius_m = np.full(y_nodes_m.size - 1, 0.05)
    thickness_m = np.full(y_nodes_m.size - 1, 0.002)
    nodal_loads_n = np.zeros(y_nodes_m.size)
    nodal_loads_n[-1] = -100.0

    spec = build_single_pipe_cantilever_spec(
        name="b1_tip_load",
        y_nodes_m=y_nodes_m,
        outer_radius_m=outer_radius_m,
        thickness_m=thickness_m,
        material=material,
        nodal_fz_n=nodal_loads_n,
    )
    deck = write_calculix_beam_inp(spec, tmp_path / "b1_tip_load.inp")
    text = deck.inp_path.read_text(encoding="utf-8")

    assert "*ELEMENT, TYPE=B32R" in text
    assert "*MATERIAL, NAME=MAIN" in text
    assert "*BEAM SECTION,ELSET=MAIN_E1,MATERIAL=MAIN,SECTION=PIPE" in text
    assert "*BOUNDARY" in text
    assert "1, 1, 6" in text
    assert "*CLOAD" in text
    assert f"{deck.node_sets['TIP_MAIN'][0]}, 3, -100" in text
    assert "*NODE PRINT, NSET=HPA_SUPPORT_ALL, TOTALS=ONLY" in text
    assert deck.node_sets["ROOT_MAIN"] == (1,)
    assert deck.node_sets["TIP_MAIN"] == (2 * len(y_nodes_m) - 1,)


def test_write_dual_pipe_deck_includes_link_equations_and_wire_vertical_support(
    tmp_path: Path,
) -> None:
    material_main = BeamMaterial(
        name="MAIN",
        young_pa=135.0e9,
        poisson_ratio=0.3,
        density_kgpm3=1600.0,
    )
    material_rear = BeamMaterial(
        name="REAR",
        young_pa=90.0e9,
        poisson_ratio=0.3,
        density_kgpm3=1550.0,
    )
    y_nodes_m = np.linspace(0.0, 6.0, 7)
    main_outer_radius_m = np.full(y_nodes_m.size - 1, 0.045)
    main_thickness_m = np.full(y_nodes_m.size - 1, 0.0022)
    rear_outer_radius_m = np.full(y_nodes_m.size - 1, 0.032)
    rear_thickness_m = np.full(y_nodes_m.size - 1, 0.0018)
    main_nodal_fz_n = np.zeros(y_nodes_m.size)
    main_nodal_fz_n[1:-1] = -20.0
    rear_nodal_fz_n = np.zeros(y_nodes_m.size)

    spec = build_dual_pipe_benchmark_spec(
        name="b4_vertical_wire",
        y_nodes_m=y_nodes_m,
        main_x_m=np.zeros_like(y_nodes_m),
        rear_x_m=np.full_like(y_nodes_m, 0.35),
        main_z_m=np.zeros_like(y_nodes_m),
        rear_z_m=np.zeros_like(y_nodes_m),
        main_outer_radius_m=main_outer_radius_m,
        main_thickness_m=main_thickness_m,
        rear_outer_radius_m=rear_outer_radius_m,
        rear_thickness_m=rear_thickness_m,
        material_main=material_main,
        material_rear=material_rear,
        main_nodal_fz_n=main_nodal_fz_n,
        rear_nodal_fz_n=rear_nodal_fz_n,
        joint_node_indices=(2, 4, 6),
        wire_node_indices=(4,),
    )
    deck = write_calculix_beam_inp(spec, tmp_path / "b4_vertical_wire.inp")
    text = deck.inp_path.read_text(encoding="utf-8")

    assert "*ELEMENT, TYPE=B32R" in text
    assert "*BEAM SECTION,ELSET=MAIN_E1,MATERIAL=MAIN,SECTION=PIPE" in text
    assert "*BEAM SECTION,ELSET=REAR_E1,MATERIAL=REAR,SECTION=PIPE" in text
    assert "*EQUATION" in text
    assert "*NODE PRINT, NSET=HPA_SUPPORT_ROOT, TOTALS=ONLY" in text
    assert "*NODE PRINT, NSET=HPA_SUPPORT_WIRE, TOTALS=ONLY" in text
    wire_node = deck.node_sets["WIRE_MAIN"][0]
    assert f"{wire_node}, 3, 3, 0.0" in text
    rear_wire_node = deck.node_sets["ROOT_REAR"][0] + 2 * 4
    assert f"{rear_wire_node}, 3, 1.0, {wire_node}, 3, -1.0" in text
    assert deck.node_sets["WIRE_REAR_LINK"] == (rear_wire_node,)
    assert deck.node_sets["HPA_SUPPORT_WIRE"] == (wire_node, rear_wire_node)
    assert "HPA_SUPPORT_ALL" in deck.node_sets
    assert rear_wire_node in deck.node_sets["HPA_SUPPORT_ALL"]
    assert deck.node_sets["ROOT_MAIN"] == (1,)
    assert deck.node_sets["ROOT_REAR"] == (2 * len(y_nodes_m),)


def test_write_dual_pipe_deck_can_export_offset_rigid_link_equations(
    tmp_path: Path,
) -> None:
    material = BeamMaterial(
        name="CARBON",
        young_pa=135.0e9,
        poisson_ratio=0.3,
        density_kgpm3=1600.0,
    )
    y_nodes_m = np.array([0.0, 1.0, 2.0])

    spec = build_dual_pipe_benchmark_spec(
        name="offset_rigid_joint",
        y_nodes_m=y_nodes_m,
        main_x_m=np.zeros_like(y_nodes_m),
        rear_x_m=np.full_like(y_nodes_m, 0.4),
        main_z_m=np.zeros_like(y_nodes_m),
        rear_z_m=np.full_like(y_nodes_m, 0.2),
        main_outer_radius_m=np.full(2, 0.04),
        main_thickness_m=np.full(2, 0.002),
        rear_outer_radius_m=np.full(2, 0.03),
        rear_thickness_m=np.full(2, 0.0015),
        material_main=material,
        material_rear=material,
        main_nodal_fz_n=np.zeros(3),
        rear_nodal_fz_n=np.zeros(3),
        joint_node_indices=(1,),
        joint_link_mode="offset_rigid",
    )
    deck = write_calculix_beam_inp(spec, tmp_path / "offset_rigid_joint.inp")
    text = deck.inp_path.read_text(encoding="utf-8")

    main_node = 3
    rear_node = 8
    assert "joint_link_mode=offset_rigid" in text
    assert f"{rear_node}, 1, 1.0, {main_node}, 1, -1.0" in text
    assert f"{main_node}, 5, -0.1" in text
    assert f"{rear_node}, 5, -0.1" in text
    assert f"{main_node}, 4, 0.1" in text
    assert f"{rear_node}, 4, 0.1" in text
    assert f"{main_node}, 6, -0.2" in text
    assert f"{rear_node}, 6, -0.2" in text
    assert f"{rear_node}, 4, 1.0, {main_node}, 4, -1.0" in text


def test_write_dual_pipe_deck_can_export_buckle_reference_step(
    tmp_path: Path,
) -> None:
    material = BeamMaterial(
        name="CARBON",
        young_pa=135.0e9,
        poisson_ratio=0.3,
        density_kgpm3=1600.0,
    )
    y_nodes_m = np.array([0.0, 1.0, 2.0])
    main_nodal_fz_n = np.array([0.0, -10.0, -5.0])

    spec = build_dual_pipe_benchmark_spec(
        name="braced_subassembly_buckle",
        y_nodes_m=y_nodes_m,
        main_x_m=np.zeros_like(y_nodes_m),
        rear_x_m=np.full_like(y_nodes_m, 0.4),
        main_z_m=np.zeros_like(y_nodes_m),
        rear_z_m=np.zeros_like(y_nodes_m),
        main_outer_radius_m=np.full(2, 0.04),
        main_thickness_m=np.full(2, 0.002),
        rear_outer_radius_m=np.full(2, 0.03),
        rear_thickness_m=np.full(2, 0.0015),
        material_main=material,
        material_rear=material,
        main_nodal_fz_n=main_nodal_fz_n,
        rear_nodal_fz_n=np.zeros_like(y_nodes_m),
        joint_node_indices=(1,),
        joint_link_mode="offset_rigid",
    )
    deck = write_calculix_beam_inp(
        spec,
        tmp_path / "braced_subassembly_buckle.inp",
        analysis_kind="buckle",
        n_buckle_modes=3,
    )
    text = deck.inp_path.read_text(encoding="utf-8")

    assert "*STEP, NAME=reference_static" in text
    assert "*CLOAD" in text
    assert f"{deck.node_sets['TIP_MAIN'][0]}, 3, -5" in text
    assert "*STEP, NAME=buckle\n*BUCKLE\n3" in text
    assert text.count("*END STEP") == 2


def test_parse_total_force_from_dat_reads_named_set_totals(tmp_path: Path) -> None:
    dat_path = tmp_path / "case.dat"
    dat_path.write_text(
        "\n".join(
            [
                " total force (fx,fy,fz) for set HPA_SUPPORT_ALL and time  0.1000000E+01",
                "  0.0000000E+00  0.0000000E+00  1.2345000E+02",
                " total force (fx,fy,fz) for set HPA_SUPPORT_WIRE and time  0.1000000E+01",
                "  0.0000000E+00  0.0000000E+00  2.5000000E+01",
            ]
        ),
        encoding="utf-8",
    )

    assert parse_total_force_from_dat(dat_path, "HPA_SUPPORT_ALL") == (0.0, 0.0, 123.45)
    assert parse_total_force_from_dat(dat_path, "HPA_SUPPORT_WIRE") == (0.0, 0.0, 25.0)
    assert parse_total_force_from_dat(dat_path, "HPA_SUPPORT_ROOT") is None


def test_cantilever_closed_form_helpers_match_hand_formulas() -> None:
    young_pa = 135.0e9
    second_moment_m4 = 4.5e-6
    span_m = 6.0
    point_load_n = 100.0
    uniform_load_npm = 25.0

    expected_tip_load = point_load_n * span_m**3 / (3.0 * young_pa * second_moment_m4)
    expected_uniform = uniform_load_npm * span_m**4 / (8.0 * young_pa * second_moment_m4)

    assert cantilever_tip_deflection_point_load(
        point_load_n=point_load_n,
        span_m=span_m,
        young_pa=young_pa,
        second_moment_m4=second_moment_m4,
    ) == expected_tip_load
    assert cantilever_tip_deflection_uniform_load(
        uniform_load_npm=uniform_load_npm,
        span_m=span_m,
        young_pa=young_pa,
        second_moment_m4=second_moment_m4,
    ) == expected_uniform
