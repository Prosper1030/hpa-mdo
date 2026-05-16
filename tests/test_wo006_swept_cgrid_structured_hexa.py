from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cfd_rescue.baseline_geometry import (  # noqa: E402
    build_adaptive_full_span_stations,
    load_baseline_authority,
)
from cfd_rescue.section_ogrid import (  # noqa: E402
    build_section_ogrid,
    interpolate_station,
    section_grid_quality,
)
from cfd_rescue.swept_hexa import (  # noqa: E402
    build_swept_ogrid_mesh,
    mesh_quality_summary,
)


def test_true_airfoil_section_ogrids_have_wall_markers_and_positive_cells() -> None:
    authority = load_baseline_authority(n_perim=48)
    root = authority.half_stations[0]
    tip = authority.half_stations[-1]
    morph = interpolate_station(authority.half_stations[4], authority.half_stations[5], 0.5)

    for station in (root, tip, morph):
        grid = build_section_ogrid(
            station,
            first_layer_height_m=5.0e-5,
            n_radial=12,
            farfield_chords=8.0,
        )
        quality = section_grid_quality(grid)

        assert quality["status"] == "pass"
        assert quality["negative_or_collapsed_cell_count"] == 0
        assert abs(quality["first_layer_min_m"] - 5.0e-5) < 1.0e-9
        assert abs(quality["first_layer_max_m"] - 5.0e-5) < 1.0e-9
        assert grid.segment_markers.count("wing_upper") > 0
        assert grid.segment_markers.count("wing_lower") > 0
        assert grid.segment_markers.count("te_wall") == 1


def test_adaptive_full_span_stations_stay_practical_and_bound_geometry_change() -> None:
    authority = load_baseline_authority(n_perim=48)
    stations, report = build_adaptive_full_span_stations(
        authority,
        twist_target_deg=0.25,
        chord_ratio_target=0.03,
        z_step_target_m=0.08,
        morph_step_target=0.08,
    )

    span_cells = len(stations) - 1
    dy_values = [round(stations[i + 1].y - stations[i].y, 6) for i in range(span_cells)]

    assert 64 <= span_cells <= 192
    assert span_cells < 5200
    assert len(set(dy_values)) > 4
    assert report["max_abs_twist_delta_deg"] <= 0.2500001
    assert report["max_chord_ratio_delta"] <= 0.0300001
    assert report["max_airfoil_morph_step"] <= 0.0800001


def test_single_morph_bay_sweeps_to_positive_hexa_with_split_patches() -> None:
    authority = load_baseline_authority(n_perim=48)
    left = authority.half_stations[4]
    right = authority.half_stations[5]
    stations = [left] + [
        interpolate_station(left, right, step / 8) for step in range(1, 8)
    ] + [right]

    mesh = build_swept_ogrid_mesh(
        stations,
        n_radial=10,
        first_layer_height_m=5.0e-5,
        farfield_chords=12.0,
        case_id="unit_morph_bay",
    )
    quality = mesh_quality_summary(mesh)

    assert quality["status"] == "pass"
    assert quality["non_positive_volume_count"] == 0
    assert quality["nonmanifold_face_count"] == 0
    assert mesh.boundary_face_counts["wing_upper"] > 0
    assert mesh.boundary_face_counts["wing_lower"] > 0
    assert mesh.boundary_face_counts["te_wall"] > 0
    assert mesh.boundary_face_counts["farfield"] > 0
    assert mesh.boundary_face_counts["tip_left"] > 0
    assert mesh.boundary_face_counts["tip_right"] > 0
