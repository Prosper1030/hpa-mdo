from pathlib import Path

import pytest

from hpa_meshing.mesh_native.blackcat import load_blackcat_main_wing_spec_from_avl
from hpa_meshing.mesh_native.wing_surface import build_wing_surface


REPO_ROOT = Path(__file__).resolve().parents[2]
AVL_PATH = REPO_ROOT / "data" / "blackcat_004_full.avl"


def test_load_blackcat_main_wing_spec_from_avl_builds_full_span_mesh_native_spec():
    spec = load_blackcat_main_wing_spec_from_avl(AVL_PATH, points_per_side=8)

    assert spec.side == "full"
    assert spec.reference.sref_full == pytest.approx(35.175)
    assert spec.reference.cref == pytest.approx(1.130189765)
    assert spec.reference.bref_full == pytest.approx(33.0)
    assert [station.y for station in spec.stations] == pytest.approx(
        [-16.5, -13.5, -10.5, -7.5, -4.5, 0.0, 4.5, 7.5, 10.5, 13.5, 16.5]
    )
    assert spec.stations[0].chord == pytest.approx(0.435)
    assert spec.stations[5].chord == pytest.approx(1.3)
    assert spec.stations[-1].chord == pytest.approx(0.435)
    assert all(station.twist_deg == pytest.approx(3.0) for station in spec.stations)
    assert all(len(station.airfoil_xz) == 14 for station in spec.stations)
    assert spec.stations[0].airfoil_xz[0] == pytest.approx((1.0, 0.0))


def test_blackcat_main_wing_spec_builds_watertight_mesh_native_surface():
    spec = load_blackcat_main_wing_spec_from_avl(AVL_PATH, points_per_side=8)

    surface = build_wing_surface(spec)

    assert surface.metadata["station_count"] == 11
    assert surface.metadata["points_per_station"] == 14
    assert surface.metadata["span_m"] == pytest.approx(33.0)
    assert surface.metadata["planform_area_m2"] == pytest.approx(35.175)
    assert surface.marker_counts() == {"wing_wall": 168}
    bounds = surface.bounds()
    assert bounds["y_min"] == pytest.approx(-16.5)
    assert bounds["y_max"] == pytest.approx(16.5)
