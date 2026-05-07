from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from hpa_mdo.structure.calculix_beam_export import BeamMaterial
from hpa_mdo.structure.spar_model import tube_J
from scripts.phase14_maclocal_fem_package import (
    B2ComparisonInputs,
    Phase14ExpectedValue,
    TubeShellMeshSpec,
    classify_b2_shell_agreement,
    tip_torque_loads_for_ring,
    tube_torsion_theta,
    write_apdl_windows_package,
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
