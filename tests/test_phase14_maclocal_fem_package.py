from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from hpa_mdo.structure.calculix_beam_export import BeamMaterial
from hpa_mdo.structure.spar_model import tube_J
from scripts.phase14_maclocal_fem_package import (
    B2ComparisonInputs,
    ConstantTubeVerificationRow,
    Phase14ExpectedValue,
    TubeShellMeshSpec,
    _build_parser,
    build_structured_tube_shell_mesh,
    classify_b2_shell_agreement,
    classify_constant_tube_status,
    estimate_ring_twist_rad,
    tube_bending_tip_load_delta,
    tube_bending_uniform_load_delta,
    tip_torque_loads_for_ring,
    tube_torsion_theta,
    write_apdl_windows_package,
    write_constant_tube_markdown,
    write_constant_tube_verification_csv,
    write_tube_shell_geo,
)


def test_tube_torsion_theta_matches_closed_form() -> None:
    theta = tube_torsion_theta(
        torque_n_m=100.0,
        span_m=10.0,
        young_pa=135.0e9,
        poisson_ratio=0.3,
        outer_radius_m=0.03,
        thickness_m=0.0015,
    )

    expected = 100.0 * 10.0 / (
        (135.0e9 / (2.0 * 1.3))
        * float(tube_J(np.asarray([0.03]), np.asarray([0.0015]))[0])
    )
    assert theta == expected


def test_tube_bending_helpers_match_closed_form() -> None:
    tip = tube_bending_tip_load_delta(
        force_n=-80.0,
        span_m=10.0,
        young_pa=135.0e9,
        outer_radius_m=0.03,
        thickness_m=0.0015,
    )
    uniform = tube_bending_uniform_load_delta(
        q_n_per_m=-8.0,
        span_m=10.0,
        young_pa=135.0e9,
        outer_radius_m=0.03,
        thickness_m=0.0015,
    )
    second_moment = np.pi / 4.0 * (0.03**4 - (0.03 - 0.0015) ** 4)

    assert tip == -80.0 * 10.0**3 / (3.0 * 135.0e9 * second_moment)
    assert uniform == -8.0 * 10.0**4 / (8.0 * 135.0e9 * second_moment)


def test_build_structured_tube_shell_mesh_builds_quad_shell_elements() -> None:
    spec = TubeShellMeshSpec(
        name="constant_quad",
        span_m=2.0,
        root_outer_radius_m=0.03,
        tip_outer_radius_m=0.03,
        n_span=3,
        n_circumference=8,
        mesh_size_m=0.2,
    )

    nodes, elements = build_structured_tube_shell_mesh(spec)

    assert nodes.shape == (32, 4)
    assert len(elements) == 24
    assert {element.element_type for element in elements} == {"S4"}
    assert elements[0].node_ids == (1, 9, 10, 2)
    assert elements[-1].node_ids == (24, 32, 25, 17)


def test_constant_tube_verification_row_has_required_schema() -> None:
    fields = set(ConstantTubeVerificationRow.__dataclass_fields__)

    assert {
        "case_id",
        "mesh_id",
        "n_span",
        "n_circumference",
        "element_count",
        "load_or_torque",
        "theory_value",
        "fem_value",
        "error_pct",
        "reaction_or_moment_residual",
        "mesh_delta_vs_previous_pct",
        "mesh_delta_vs_finest_pct",
        "max_von_mises_pa",
        "status",
        "engineering_note",
    }.issubset(fields)


def test_build_parser_accepts_hardening_task() -> None:
    args = _build_parser().parse_args(["--task", "hardening"])

    assert args.task == "hardening"


def test_write_constant_tube_artifacts_include_required_columns(tmp_path: Path) -> None:
    rows = [
        ConstantTubeVerificationRow(
            case_id="A1_constant_tube_tip_load",
            mesh_id="coarse",
            n_span=32,
            n_circumference=32,
            element_count=1024,
            load_or_torque=-80.0,
            theory_value=-0.1,
            fem_value=-0.102,
            error_pct=2.0,
            reaction_or_moment_residual=0.0,
            mesh_delta_vs_previous_pct=None,
            mesh_delta_vs_finest_pct=1.0,
            max_von_mises_pa=1000.0,
            status="PASS",
            engineering_note="closed form agreement",
        )
    ]

    csv_path = tmp_path / "constant_tube_bending.csv"
    md_path = tmp_path / "constant_tube_bending.md"
    write_constant_tube_verification_csv(csv_path, rows)
    write_constant_tube_markdown(
        md_path,
        title="Constant Tube Bending",
        rows=rows,
        engineering_summary="Daily gate candidate.",
    )

    csv_rows = list(csv.DictReader(csv_path.read_text().splitlines()))
    assert csv_rows[0]["case_id"] == "A1_constant_tube_tip_load"
    assert csv_rows[0]["mesh_delta_vs_finest_pct"] == "1.0"
    md_text = md_path.read_text(encoding="utf-8")
    assert "# Constant Tube Bending" in md_text
    assert "reaction_or_moment_residual" in md_text
    assert "Daily gate candidate." in md_text


def test_classify_constant_tube_status_uses_error_convergence_and_equilibrium() -> None:
    assert classify_constant_tube_status(
        theory_value=1.0,
        fem_value=1.03,
        error_pct=3.0,
        mesh_delta_vs_finest_pct=4.0,
        reaction_or_moment_residual=1.0e-5,
        load_or_torque=100.0,
    ) == "PASS"
    assert classify_constant_tube_status(
        theory_value=1.0,
        fem_value=1.08,
        error_pct=8.0,
        mesh_delta_vs_finest_pct=12.0,
        reaction_or_moment_residual=1.0e-5,
        load_or_torque=100.0,
    ) == "WARN"
    assert classify_constant_tube_status(
        theory_value=1.0,
        fem_value=-0.2,
        error_pct=120.0,
        mesh_delta_vs_finest_pct=50.0,
        reaction_or_moment_residual=20.0,
        load_or_torque=100.0,
    ) == "FAIL"


def test_tip_torque_loads_for_ring_are_self_equilibrated() -> None:
    theta = np.linspace(0.0, 2.0 * np.pi, 16, endpoint=False)
    nodes = np.column_stack(
        (
            np.arange(1, theta.size + 1, dtype=float),
            0.03 * np.cos(theta),
            np.full(theta.size, 10.0),
            0.03 * np.sin(theta),
        )
    )

    loads = tip_torque_loads_for_ring(nodes, torque_n_m=42.0)

    assert abs(sum(load.force_x_n for load in loads)) < 1.0e-12
    assert abs(sum(load.force_z_n for load in loads)) < 1.0e-12
    torque = sum(load.z_m * load.force_x_n - load.x_m * load.force_z_n for load in loads)
    assert abs(torque - 42.0) < 1.0e-10


def test_estimate_ring_twist_rad_recovers_known_rotation() -> None:
    angles = np.linspace(0.0, 2.0 * np.pi, 32, endpoint=False)
    radius = 0.03
    theta = 0.017
    nodes = np.column_stack(
        (
            np.arange(1, angles.size + 1, dtype=float),
            radius * np.cos(angles),
            np.full(angles.size, 10.0),
            radius * np.sin(angles),
        )
    )
    deformed_x = nodes[:, 1] * np.cos(theta) + nodes[:, 3] * np.sin(theta)
    deformed_z = -nodes[:, 1] * np.sin(theta) + nodes[:, 3] * np.cos(theta)
    displacements = np.column_stack(
        (
            nodes[:, 0],
            deformed_x - nodes[:, 1],
            np.zeros(angles.size),
            deformed_z - nodes[:, 3],
        )
    )

    assert abs(estimate_ring_twist_rad(nodes=nodes, displacements=displacements) - theta) < 1.0e-8


def test_estimate_ring_twist_rad_ignores_pure_translation() -> None:
    angles = np.linspace(0.0, 2.0 * np.pi, 24, endpoint=False)
    nodes = np.column_stack(
        (
            np.arange(1, angles.size + 1, dtype=float),
            0.03 * np.cos(angles),
            np.full(angles.size, 10.0),
            0.03 * np.sin(angles),
        )
    )
    displacements = np.column_stack(
        (
            nodes[:, 0],
            np.full(angles.size, 0.002),
            np.full(angles.size, -0.001),
            np.full(angles.size, -0.003),
        )
    )

    assert abs(estimate_ring_twist_rad(nodes=nodes, displacements=displacements)) < 1.0e-10


def test_estimate_ring_twist_rad_is_stable_with_small_noise() -> None:
    rng = np.random.default_rng(14)
    angles = np.linspace(0.0, 2.0 * np.pi, 64, endpoint=False)
    radius = 0.03
    theta = 0.012
    nodes = np.column_stack(
        (
            np.arange(1, angles.size + 1, dtype=float),
            radius * np.cos(angles),
            np.full(angles.size, 10.0),
            radius * np.sin(angles),
        )
    )
    deformed_x = nodes[:, 1] * np.cos(theta) + nodes[:, 3] * np.sin(theta)
    deformed_z = -nodes[:, 1] * np.sin(theta) + nodes[:, 3] * np.cos(theta)
    displacements = np.column_stack(
        (
            nodes[:, 0],
            deformed_x - nodes[:, 1] + rng.normal(0.0, 2.0e-6, angles.size),
            rng.normal(0.0, 2.0e-6, angles.size),
            deformed_z - nodes[:, 3] + rng.normal(0.0, 2.0e-6, angles.size),
        )
    )

    assert abs(estimate_ring_twist_rad(nodes=nodes, displacements=displacements) - theta) < 2.5e-4


def test_classify_b2_shell_agreement_chooses_nearest_reference() -> None:
    assert (
        classify_b2_shell_agreement(
            B2ComparisonInputs(
                internal_tip_uz_m=-0.102,
                calculix_pipe_tip_uz_m=-0.086,
                shell_tip_uz_m=-0.099,
            )
        ).closer_to
        == "internal_beam"
    )
    assert (
        classify_b2_shell_agreement(
            B2ComparisonInputs(
                internal_tip_uz_m=-0.102,
                calculix_pipe_tip_uz_m=-0.086,
                shell_tip_uz_m=-0.088,
            )
        ).closer_to
        == "calculix_b32r_pipe"
    )


def test_write_tube_shell_geo_builds_closed_gmsh_surface(tmp_path: Path) -> None:
    spec = TubeShellMeshSpec(
        name="tiny_taper",
        span_m=2.0,
        root_outer_radius_m=0.04,
        tip_outer_radius_m=0.03,
        n_span=2,
        n_circumference=6,
        mesh_size_m=0.2,
    )

    geo_path = write_tube_shell_geo(spec, tmp_path / "tiny_taper.geo")
    text = geo_path.read_text(encoding="utf-8")

    assert text.count("Point(") == 18
    assert text.count("Plane Surface(") == 24
    assert 'Physical Surface("TUBE_SHELL")' in text
    assert "0.04, 0, 0" in text
    assert "0.03, 2, 0" in text


def test_write_apdl_windows_package_creates_nonexpert_runner(tmp_path: Path) -> None:
    material = BeamMaterial(
        name="MAIN",
        young_pa=135.0e9,
        poisson_ratio=0.3,
        density_kgpm3=1600.0,
    )
    expected_values = [
        Phase14ExpectedValue(
            case_id="B2_TAPERED_TUBE",
            metric="tip_uz_m",
            value=-0.1,
            source="mac_internal_beam",
            tolerance_pct=10.0,
            note="Regression reference for APDL handoff.",
        ),
        Phase14ExpectedValue(
            case_id="B5_SINGLE_TORSION",
            metric="theta_rad",
            value=0.01,
            source="theta_equals_tl_over_gj",
            tolerance_pct=10.0,
            note="Closed-form torsion reference.",
        ),
    ]

    package = write_apdl_windows_package(
        output_dir=tmp_path / "apdl_windows_package",
        material=material,
        expected_values=expected_values,
    )

    required = {
        "run_all_phase14.mac",
        "phase14_b2_tapered_tube.mac",
        "phase14_b5_single_torsion.mac",
        "phase14_b5_dual_direct_my.mac",
        "phase14_b5_dual_force_couple.mac",
        "README_windows_run.md",
        "expected_values.csv",
    }
    assert required.issubset({path.name for path in package.files})

    runner = (package.directory / "run_all_phase14.mac").read_text(encoding="utf-8")
    assert "phase14_apdl_results,csv" in runner
    assert "/INPUT,phase14_b2_tapered_tube,mac" in runner
    assert "/INPUT,phase14_b5_single_torsion,mac" in runner
    assert "/INPUT,phase14_b5_dual_direct_my,mac" in runner
    assert "/INPUT,phase14_b5_dual_force_couple,mac" in runner

    b2_deck = (package.directory / "phase14_b2_tapered_tube.mac").read_text(encoding="utf-8")
    b5_deck = (package.directory / "phase14_b5_single_torsion.mac").read_text(encoding="utf-8")
    assert "BEAM188" in b2_deck
    assert "CTUBE" in b2_deck
    assert "*CFOPEN,phase14_apdl_results,csv,,APPEND" in b2_deck
    assert "B5_SINGLE_TORSION" in b5_deck
    assert "MY" in b5_deck

    readme = (package.directory / "README_windows_run.md").read_text(encoding="utf-8")
    assert "set working directory" in readme.lower()
    assert "run_all_phase14.mac" in readme
    assert "phase14_apdl_results.csv" in readme

    rows = list(csv.DictReader((package.directory / "expected_values.csv").read_text().splitlines()))
    assert {row["case_id"] for row in rows} == {"B2_TAPERED_TUBE", "B5_SINGLE_TORSION"}
