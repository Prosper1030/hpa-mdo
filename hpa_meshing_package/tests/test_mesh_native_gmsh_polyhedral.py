from pathlib import Path
import shutil

import pytest

from hpa_meshing.mesh_native.gmsh_polyhedral import (
    _mesh_quality_gate,
    run_faceted_volume_refinement_ladder,
    run_faceted_volume_su2_smoke,
    write_faceted_volume_mesh,
    write_faceted_volume_su2_case,
)
from hpa_meshing.mesh_native.su2_structured import parse_su2_marker_summary
from hpa_meshing.mesh_native.wing_surface import (
    Reference,
    Station,
    WingSpec,
    build_farfield_box_surface,
    build_wing_surface,
)


def _rect_loop():
    return [
        (1.0, 0.05),
        (0.0, 0.05),
        (0.0, -0.05),
        (1.0, -0.05),
    ]


def _wing_and_close_farfield():
    wing = build_wing_surface(
        WingSpec(
            stations=[
                Station(y=0.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
                Station(y=1.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
                Station(y=2.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
            ],
            side="full",
            te_rule="finite_thickness",
            tip_rule="planar_cap",
            root_rule="wall_cap",
            reference=Reference(sref_full=2.0, cref=1.0, bref_full=2.0),
        )
    )
    farfield = build_farfield_box_surface(
        wing,
        upstream_factor=1.5,
        downstream_factor=2.0,
        lateral_factor=1.5,
        vertical_factor=1.5,
    )
    return wing, farfield


def test_write_faceted_volume_mesh_preserves_su2_boundary_markers(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()
    msh_path = tmp_path / "faceted_wing_volume.msh"
    su2_path = tmp_path / "faceted_wing_volume.su2"

    report = write_faceted_volume_mesh(
        wing,
        farfield,
        msh_path,
        su2_path=su2_path,
        mesh_size=2.0,
    )

    assert report["status"] == "meshed"
    assert report["volume_count"] == 1
    assert report["volume_element_count"] > 0
    assert report["node_count"] > 0
    assert report["surface_triangle_count"] == 36
    assert report["quality_metrics"]["tetra_element_count"] == report["volume_element_count"]
    assert report["quality_metrics"]["non_positive_min_sicn_count"] == 0
    assert report["quality_metrics"]["non_positive_volume_count"] == 0
    assert report["quality_metrics"]["min_gamma"] > 0.0
    assert report["production_scale_gate"]["target_volume_elements"] == 1_000_000
    assert report["production_scale_gate"]["status"] == "underresolved"
    assert report["physical_groups"]["wing_wall"]["dimension"] == 2
    assert report["physical_groups"]["farfield"]["dimension"] == 2
    assert report["physical_groups"]["fluid"]["dimension"] == 3
    assert report["physical_groups"]["wing_wall"]["entity_count"] == 24
    assert report["physical_groups"]["farfield"]["entity_count"] == 12
    assert msh_path.exists()
    assert su2_path.exists()

    su2_summary = parse_su2_marker_summary(su2_path)
    assert su2_summary["ndime"] == 3
    assert su2_summary["nelem"] == report["volume_element_count"]
    assert su2_summary["nmark"] == 2
    assert set(su2_summary["markers"]) == {"wing_wall", "farfield"}
    assert su2_summary["markers"]["wing_wall"]["element_count"] > 0
    assert su2_summary["markers"]["farfield"]["element_count"] > 0


def test_write_faceted_volume_mesh_supports_wing_local_sizing(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    coarse = write_faceted_volume_mesh(
        wing,
        farfield,
        tmp_path / "coarse.msh",
        mesh_size=3.0,
    )
    locally_refined = write_faceted_volume_mesh(
        wing,
        farfield,
        tmp_path / "wing_local.msh",
        mesh_size=3.0,
        wing_mesh_size=1.0,
        farfield_mesh_size=3.0,
    )

    assert locally_refined["mesh_sizing"]["default_mesh_size"] == 3.0
    assert locally_refined["mesh_sizing"]["wing_mesh_size"] == 1.0
    assert locally_refined["mesh_sizing"]["farfield_mesh_size"] == 3.0
    assert locally_refined["mesh_sizing"]["wing_refinement_radius"] == 3.0
    assert locally_refined["mesh_sizing"]["background_field"]["type"] == "DistanceThreshold"
    assert locally_refined["volume_element_count"] > coarse["volume_element_count"]
    assert locally_refined["mesh_quality_gate"]["status"] == "pass"


def test_mesh_quality_gate_warns_on_near_zero_positive_tets():
    gate = _mesh_quality_gate(
        {
            "tetra_element_count": 1,
            "non_positive_min_sicn_count": 0,
            "non_positive_min_sige_count": 0,
            "non_positive_volume_count": 0,
            "min_gamma": 1.0e-7,
            "min_sicn": 5.0e-5,
            "gamma_percentiles": {"p01": 0.005, "p05": 0.02, "p50": 0.3},
        }
    )

    assert gate["status"] == "pass"
    assert "very_low_min_gamma" in gate["warnings"]
    assert "very_low_min_sicn" in gate["warnings"]
    assert "low_p01_gamma" in gate["warnings"]


def test_run_faceted_volume_refinement_ladder_increases_mesh_density(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    report = run_faceted_volume_refinement_ladder(
        wing,
        farfield,
        tmp_path / "ladder",
        mesh_sizes=(3.0, 2.0, 1.0),
        target_volume_elements=1_000,
        max_volume_elements=5_000,
    )

    counts = [case["volume_element_count"] for case in report["cases"]]
    assert counts == sorted(counts)
    assert counts[-1] >= 1_000
    assert report["status"] == "target_reached"
    assert report["selected_case"]["mesh_size"] == 1.0
    assert report["selected_case"]["production_scale_gate"]["status"] == "meets_target"


def test_run_faceted_volume_refinement_ladder_respects_cell_budget(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    report = run_faceted_volume_refinement_ladder(
        wing,
        farfield,
        tmp_path / "budget_ladder",
        mesh_sizes=(3.0, 2.0, 1.0),
        target_volume_elements=1_000_000,
        max_volume_elements=500,
    )

    assert report["status"] == "blocked_by_volume_element_guard"
    assert report["selected_case"] is None
    assert report["cases"][-1]["volume_element_count"] > 500


def test_write_faceted_volume_su2_case_materializes_marker_audit(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()

    report = write_faceted_volume_su2_case(
        wing,
        farfield,
        tmp_path / "faceted_case",
        ref_area=2.0,
        ref_length=1.0,
        mesh_size=2.0,
        max_iterations=3,
    )

    assert report["route"] == "mesh_native_faceted_gmsh_volume_su2_smoke_case"
    assert report["mesh_report"]["status"] == "meshed"
    assert report["mesh_report"]["volume_element_count"] > 0
    assert report["marker_audit"]["status"] == "pass"
    assert Path(report["mesh_path"]).exists()
    assert Path(report["runtime_cfg_path"]).exists()
    assert Path(report["report_path"]).exists()


def test_run_faceted_volume_su2_smoke_runs_when_su2_is_available(tmp_path: Path):
    pytest.importorskip("gmsh")
    solver = shutil.which("SU2_CFD")
    if solver is None:
        pytest.skip("SU2_CFD not available")

    wing, farfield = _wing_and_close_farfield()
    report = run_faceted_volume_su2_smoke(
        wing,
        farfield,
        tmp_path / "faceted_solver_case",
        ref_area=2.0,
        ref_length=1.0,
        mesh_size=2.0,
        max_iterations=3,
        solver_command=solver,
        threads=1,
    )

    assert report["run_status"] == "completed"
    assert report["returncode"] == 0
    assert report["marker_audit"]["status"] == "pass"
    assert report["mesh_report"]["volume_element_count"] > 0
    assert Path(report["history_path"]).exists()
    assert Path(report["solver_log_path"]).exists()
    assert report["history"]["final_iteration"] == 2
    assert report["history"]["final_coefficients"]["cl"] is not None
    assert report["history"]["final_coefficients"]["cd"] is not None
    assert report["engineering_assessment"] == {
        "solver_readability": "pass",
        "marker_ownership": "pass",
        "aero_coefficients_interpretable": False,
        "reason": "faceted_wing_tet_smoke_not_converged",
    }
