from pathlib import Path
import shutil

import pytest

from hpa_meshing.mesh_native.blackcat import (
    build_blackcat_main_wing_surfaces_from_avl,
    load_blackcat_main_wing_spec_from_avl,
    run_blackcat_main_wing_faceted_refinement_ladder,
    run_blackcat_main_wing_faceted_su2_smoke,
)
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


def test_build_blackcat_main_wing_surfaces_from_avl_materializes_farfield():
    spec, wing, farfield = build_blackcat_main_wing_surfaces_from_avl(
        AVL_PATH,
        points_per_side=8,
        farfield_upstream_factor=1.5,
        farfield_downstream_factor=2.0,
        farfield_lateral_factor=1.2,
        farfield_vertical_factor=1.2,
    )

    assert spec.reference.sref_full == pytest.approx(35.175)
    assert wing.marker_counts() == {"wing_wall": 168}
    assert farfield.marker_counts() == {"farfield": 6}
    assert farfield.bounds()["y_min"] < wing.bounds()["y_min"]
    assert farfield.bounds()["y_max"] > wing.bounds()["y_max"]


def test_run_blackcat_main_wing_faceted_su2_smoke_runs_when_su2_is_available(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")
    solver = shutil.which("SU2_CFD")
    if solver is None:
        pytest.skip("SU2_CFD not available")

    report = run_blackcat_main_wing_faceted_su2_smoke(
        AVL_PATH,
        tmp_path / "blackcat_faceted_solver_case",
        points_per_side=6,
        mesh_size=10.0,
        max_iterations=3,
        solver_command=solver,
        threads=1,
    )

    assert report["route"] == "blackcat_main_wing_mesh_native_faceted_su2_smoke"
    assert report["run_status"] == "completed"
    assert report["returncode"] == 0
    assert report["marker_audit"]["status"] == "pass"
    assert report["blackcat_source"]["station_count"] == 11
    assert report["mesh_report"]["volume_element_count"] > 0
    assert report["history"]["final_iteration"] == 2
    assert report["history"]["final_coefficients"]["cl"] is not None


def test_run_blackcat_main_wing_faceted_refinement_ladder_reports_scale_gap(
    tmp_path: Path,
):
    pytest.importorskip("gmsh")

    report = run_blackcat_main_wing_faceted_refinement_ladder(
        AVL_PATH,
        tmp_path / "blackcat_refinement_ladder",
        points_per_side=6,
        mesh_sizes=(14.0, 10.0, 8.0, 6.0),
        target_volume_elements=850,
        max_volume_elements=20_000,
        farfield_mesh_size=18.0,
        wing_refinement_radius=12.0,
        write_su2=False,
    )

    assert report["route"] == "blackcat_main_wing_mesh_native_faceted_refinement_ladder"
    assert report["status"] == "target_reached"
    assert report["blackcat_source"]["station_count"] == 11
    assert [case["volume_element_count"] for case in report["cases"]] == sorted(
        case["volume_element_count"] for case in report["cases"]
    )
    assert report["selected_case"]["mesh_size"] == 6.0
    assert report["selected_case"]["mesh_sizing"]["farfield_mesh_size"] == 18.0
    assert report["selected_case"]["mesh_sizing"]["wing_refinement_radius"] == 12.0
    assert report["selected_case"]["mesh_quality_gate"]["status"] == "pass"
    assert report["engineering_assessment"]["aero_coefficients_interpretable"] is False
