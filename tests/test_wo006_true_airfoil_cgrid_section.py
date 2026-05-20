from __future__ import annotations

from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cfd_rescue.baseline_geometry import interpolate_station, load_baseline_authority  # noqa: E402
from cfd_rescue.section_cgrid import build_section_cgrid  # noqa: E402
from cfd_rescue.swept_cgrid import (  # noqa: E402
    build_extruded_section_cgrid_mesh,
    build_swept_cgrid_mesh,
)
from cfd_rescue.swept_hexa import mesh_quality_summary  # noqa: E402
from run_wo006_true_airfoil_cgrid_section_rescue import (  # noqa: E402
    _strict_checkmesh_log_status,
)


def test_true_airfoil_cgrid_keeps_te_open_and_adds_wake_patches() -> None:
    authority = load_baseline_authority(n_perim=48, airfoil_loop_mode="open_te_cgrid")
    root = authority.half_stations[0]

    grid = build_section_cgrid(
        root,
        first_layer_height_m=5.0e-5,
        n_radial=12,
        farfield_chords=8.0,
        wake_length_chords=10.0,
    )
    mesh = build_extruded_section_cgrid_mesh(
        root,
        n_radial=12,
        first_layer_height_m=5.0e-5,
        farfield_chords=8.0,
        wake_length_chords=10.0,
        case_id="unit_root_cgrid",
    )

    assert grid.metadata["topology"] == "wake_cgrid_open_te"
    assert grid.metadata["source_airfoil"] == "true_baseline_authority"
    assert not grid.metadata["closed_single_loop_ogrid"]
    assert abs(grid.first_layer_stats["min_m"] - grid.first_layer_stats["max_m"]) < 1.0e-14
    assert abs(grid.first_layer_stats["min_m"] - 5.0e-5) < 1.0e-9
    assert mesh.boundary_face_counts["airfoil_upper"] > 0
    assert mesh.boundary_face_counts["airfoil_lower"] > 0
    assert "wake_upper" not in mesh.boundary_face_counts
    assert "wake_lower" not in mesh.boundary_face_counts
    assert mesh.boundary_face_counts["te_wall"] > 0
    assert mesh.boundary_face_counts["farfield"] > 0
    assert mesh.boundary_face_counts["outlet"] > 0
    assert mesh.boundary_face_counts["tip_left"] > 0
    assert mesh.boundary_face_counts["tip_right"] > 0
    assert mesh.metadata["wake_block"]["status"] == "internal_fluid_block"
    assert mesh.metadata["boundary_patch_types"]["tip_left"] == "empty"
    assert mesh.metadata["boundary_patch_types"]["tip_right"] == "empty"


def test_cgrid_authority_restores_lower_te_endpoint_and_reports_bounded_bluntness() -> None:
    authority = load_baseline_authority(n_perim=48, airfoil_loop_mode="open_te_cgrid")
    root = authority.half_stations[0]
    tip = authority.half_stations[-1]

    assert len(root.airfoil_xz) == 49
    assert root.airfoil_xz[0][0] == pytest.approx(1.0)
    assert root.airfoil_xz[-1][0] == pytest.approx(1.0)
    root_gap = abs(root.airfoil_xz[0][1] - root.airfoil_xz[-1][1])
    assert 0.0 < root_gap <= 5.0e-4
    assert authority.airfoil_geometry_reports["dae31"]["te_perturbation"]["introduced"]
    assert authority.airfoil_geometry_reports["dae31"]["te_perturbation"]["gap_over_chord"] == pytest.approx(root_gap)

    assert tip.airfoil_xz[0][0] == pytest.approx(1.0)
    assert tip.airfoil_xz[-1][0] == pytest.approx(1.0)
    assert tip.airfoil_xz[0][1] > tip.airfoil_xz[-1][1]
    tip_report = authority.airfoil_geometry_reports["cst_tip_nsga2_g05_child_0032_70ef8136"]
    assert not tip_report["te_perturbation"]["introduced"]


def test_cgrid_authority_supports_bounded_zero_te_gap_variants() -> None:
    sharp = load_baseline_authority(
        n_perim=48,
        airfoil_loop_mode="open_te_cgrid",
        target_zero_te_gap_over_chord=0.0,
    )
    small_gap = load_baseline_authority(
        n_perim=48,
        airfoil_loop_mode="open_te_cgrid",
        target_zero_te_gap_over_chord=2.0e-4,
    )

    sharp_root = sharp.half_stations[0]
    small_root = small_gap.half_stations[0]
    sharp_gap = abs(sharp_root.airfoil_xz[0][1] - sharp_root.airfoil_xz[-1][1])
    small_actual_gap = abs(small_root.airfoil_xz[0][1] - small_root.airfoil_xz[-1][1])

    assert sharp_gap == pytest.approx(0.0)
    assert not sharp.airfoil_geometry_reports["dae31"]["te_perturbation"]["introduced"]
    assert small_actual_gap == pytest.approx(2.0e-4)
    assert small_gap.airfoil_geometry_reports["dae31"]["te_perturbation"]["introduced"]
    assert small_gap.airfoil_geometry_reports["dae31"]["max_te_regularization_displacement_over_chord"] == pytest.approx(1.0e-4)


def test_cgrid_te_wake_cut_first_layer_points_downstream() -> None:
    authority = load_baseline_authority(n_perim=192, airfoil_loop_mode="open_te_cgrid")
    root = authority.half_stations[0]

    grid = build_section_cgrid(
        root,
        first_layer_height_m=5.0e-5,
        n_radial=12,
        farfield_chords=8.0,
        wake_length_chords=10.0,
    )

    assert grid.points[1][0][0] > grid.points[0][0][0]
    assert grid.points[1][1][0] > grid.points[0][1][0]
    assert grid.points[1][-1][0] > grid.points[0][-1][0]
    assert grid.points[1][-2][0] > grid.points[0][-2][0]
    assert grid.metadata["te_normal_blend_points"] == 1


def test_cgrid_lower_le_shoulder_near_wall_stack_stays_wall_normal() -> None:
    authority = load_baseline_authority(n_perim=192, airfoil_loop_mode="open_te_cgrid")
    root = authority.half_stations[0]

    grid = build_section_cgrid(
        root,
        first_layer_height_m=5.0e-5,
        n_radial=12,
        farfield_chords=8.0,
        wake_length_chords=8.0,
    )
    assert grid.metadata["normal_stack_layers"] >= 8
    le_index = grid.metadata["le_index"] + 11
    first_vector = (
        grid.points[1][le_index][0] - grid.points[0][le_index][0],
        grid.points[1][le_index][1] - grid.points[0][le_index][1],
    )
    second_vector = (
        grid.points[2][le_index][0] - grid.points[1][le_index][0],
        grid.points[2][le_index][1] - grid.points[1][le_index][1],
    )
    dot = first_vector[0] * second_vector[0] + first_vector[1] * second_vector[1]
    first_norm = (first_vector[0] ** 2 + first_vector[1] ** 2) ** 0.5
    second_norm = (second_vector[0] ** 2 + second_vector[1] ** 2) ** 0.5

    assert dot / (first_norm * second_norm) > 0.99


def test_cgrid_section_meshes_have_positive_hexa_for_true_airfoils() -> None:
    authority = load_baseline_authority(n_perim=48, airfoil_loop_mode="open_te_cgrid")
    stations = [
        authority.half_stations[0],
        authority.half_stations[-1],
        interpolate_station(authority.half_stations[4], authority.half_stations[5], 0.5),
    ]

    for station in stations:
        mesh = build_extruded_section_cgrid_mesh(
            station,
            n_radial=10,
            first_layer_height_m=5.0e-5,
            farfield_chords=8.0,
            wake_length_chords=10.0,
            case_id="unit_true_airfoil_cgrid",
        )
        quality = mesh_quality_summary(mesh)

        assert quality["status"] == "pass"
        assert quality["non_positive_volume_count"] == 0
        assert quality["nonmanifold_face_count"] == 0
        assert quality["unmarked_boundary_face_count"] == 0


def test_cgrid_root_bay_sweeps_to_positive_hexa() -> None:
    authority = load_baseline_authority(n_perim=48, airfoil_loop_mode="open_te_cgrid")
    left = authority.half_stations[0]
    right = authority.half_stations[1]
    stations = [left] + [
        interpolate_station(left, right, step / 6) for step in range(1, 6)
    ] + [right]

    mesh = build_swept_cgrid_mesh(
        stations,
        n_radial=12,
        first_layer_height_m=5.0e-5,
        farfield_chords=6.0,
        wake_length_chords=6.0,
        case_id="unit_cgrid_root_bay",
    )
    quality = mesh_quality_summary(mesh)

    assert quality["status"] == "pass"
    assert quality["non_positive_volume_count"] == 0
    assert quality["nonmanifold_face_count"] == 0
    assert quality["unmarked_boundary_face_count"] == 0
    assert mesh.boundary_face_counts["airfoil_upper"] > 0
    assert mesh.boundary_face_counts["airfoil_lower"] > 0
    assert mesh.boundary_face_counts["te_wall"] > 0
    assert mesh.boundary_face_counts["farfield"] > 0


def test_high_resolution_cgrid_te_bay_reports_no_open_cells() -> None:
    authority = load_baseline_authority(n_perim=240, airfoil_loop_mode="open_te_cgrid")
    left = authority.half_stations[3]
    right = authority.half_stations[4]
    span_subdivisions = 8
    stations = [left] + [
        interpolate_station(left, right, step / span_subdivisions)
        for step in range(1, span_subdivisions)
    ] + [right]

    mesh = build_swept_cgrid_mesh(
        stations,
        n_radial=80,
        first_layer_height_m=5.0e-5,
        farfield_chords=10.0,
        wake_length_chords=8.0,
        wake_cross_cells=8,
        case_id="unit_high_resolution_te_bay",
    )
    quality = mesh_quality_summary(mesh)

    assert quality["status"] == "pass"
    assert quality["cell_openness"]["open_cell_count"] == 0
    assert quality["cell_openness"]["max"] < 1.0e-8


def test_strict_section_gate_rejects_failed_all_geometry_log(tmp_path: Path) -> None:
    failed_log = tmp_path / "log.checkMesh_allGeometry"
    failed_log.write_text(
        """
Mesh non-orthogonality Max: 74.0 average: 20.0
Max skewness = 3.0 OK.
Failed 1 mesh checks.
""",
        encoding="utf-8",
    )

    status = _strict_checkmesh_log_status(failed_log, max_non_ortho_target=75.0)

    assert status["status"] == "fail"
    assert status["mesh_ok"] is False
    assert status["failed_check_count"] == 1


def test_strict_section_gate_reports_all_geometry_determinant_blocker(tmp_path: Path) -> None:
    failed_log = tmp_path / "log.checkMesh_allGeometry"
    failed_log.write_text(
        """
Mesh non-orthogonality Max: 68.0 average: 20.0
Max skewness = 2.0 OK.
*Edges too small, min/max edge length = 3.0e-05 3.0, number too small: 14
Cell determinant (wellposedness) : minimum: 4.0e-05 average: 0.12
***Cells with small determinant (< 0.001) found, number of cells: 1846
Failed 1 mesh checks.
""",
        encoding="utf-8",
    )

    status = _strict_checkmesh_log_status(failed_log, max_non_ortho_target=75.0)

    assert status["status"] == "fail"
    assert status["short_edge_count"] == 14
    assert status["min_cell_determinant"] == pytest.approx(4.0e-05)
    assert status["underdetermined_cell_count"] == 1846
