from __future__ import annotations

from pathlib import Path
import sys


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


def test_true_airfoil_cgrid_keeps_te_open_and_adds_wake_patches() -> None:
    authority = load_baseline_authority(n_perim=48)
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
    assert mesh.boundary_face_counts["wake_upper"] > 0
    assert mesh.boundary_face_counts["wake_lower"] > 0
    assert mesh.boundary_face_counts["farfield"] > 0
    assert mesh.boundary_face_counts["outlet"] > 0
    assert mesh.boundary_face_counts["tip_left"] > 0
    assert mesh.boundary_face_counts["tip_right"] > 0


def test_cgrid_section_meshes_have_positive_hexa_for_true_airfoils() -> None:
    authority = load_baseline_authority(n_perim=48)
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
    authority = load_baseline_authority(n_perim=48)
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
    assert mesh.boundary_face_counts["farfield"] > 0
