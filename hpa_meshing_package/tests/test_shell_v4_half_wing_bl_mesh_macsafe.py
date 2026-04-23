from __future__ import annotations

from pathlib import Path

import pytest

from hpa_meshing.gmsh_runtime import load_gmsh
from hpa_meshing.shell_v4_half_wing_bl_mesh_macsafe import (
    _analyze_real_wing_tip_bl_interference,
    _augment_real_wing_sections_for_tip_truncation,
    _build_real_main_wing_occ_shell,
    _build_real_wing_bl_protection_field,
    _collect_extbl_surfaces_in_y_band,
    _build_real_wing_root_closure_plan,
    _build_real_wing_root_closure_surfaces,
    _build_su2_cfg,
    _derive_wall_diagnostics_from_surface_vtk,
    _global_section_profile_points,
    _layer_cumulative_heights,
    _resolve_real_main_wing_geometry,
    _select_tip_truncation_connector_band_surface_tags,
    _set_shell_transfinite_controls,
    _solver_command,
    _solver_env,
    build_shell_v4_half_wing_bl_macsafe_spec,
    estimate_first_cell_yplus_range,
    run_shell_v4_half_wing_bl_mesh_macsafe,
)


def test_build_shell_v4_spec_uses_half_wing_reference_values():
    spec = build_shell_v4_half_wing_bl_macsafe_spec()

    assert spec["route_name"] == "shell_v4_half_wing_bl_mesh_macsafe"
    assert spec["study_level"] == "BL_macsafe_baseline"
    assert spec["geometry"]["shape_mode"] == "surrogate_naca0012"
    assert spec["geometry"]["chord_m"] == pytest.approx(1.05)
    assert spec["geometry"]["half_span_m"] == pytest.approx(16.5)
    assert spec["reference_values"]["ref_length"] == pytest.approx(1.05)
    assert spec["reference_values"]["ref_area"] == pytest.approx(17.325)
    assert spec["reference_values"]["alternate_full_wing_ref_area"] == pytest.approx(34.65)
    assert spec["boundary_layer"]["layers"] == 24
    assert spec["boundary_layer"]["first_layer_height_m"] == pytest.approx(5.0e-5)
    assert 0.035 <= spec["boundary_layer"]["target_total_thickness_m"] <= 0.05


def test_build_shell_v4_baseline_spec_uses_macsafe_off_wall_redesign():
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")

    assert spec["wake_refinement"]["wake_length_chords"] == pytest.approx(5.0)
    assert spec["wake_refinement"]["wake_height_chords"] == pytest.approx(0.7)
    assert spec["wake_refinement"]["near_wake_cell_size_chords"] == pytest.approx(0.10)
    assert spec["tip_refinement"]["spanwise_length_chords"] == pytest.approx(0.4)
    assert spec["tip_refinement"]["cell_size_chords"] == pytest.approx(0.16)
    assert spec["farfield"]["upstream_chords"] == pytest.approx(5.0)
    assert spec["farfield"]["downstream_chords"] == pytest.approx(8.0)
    assert spec["farfield"]["normal_chords"] == pytest.approx(5.0)
    assert spec["farfield"]["outer_cell_size_chords"] == pytest.approx(2.4)
    assert spec["cell_budget"]["target_total_cells_min"] == 1_500_000
    assert spec["cell_budget"]["target_total_cells_max"] == 2_200_000
    assert spec["cell_budget"]["hard_fail_total_cells"] == 3_000_000
    assert spec["off_wall_growth"]["enabled"] is True
    assert spec["off_wall_growth"]["support_cell_size_chords"] == pytest.approx(0.20)
    assert spec["off_wall_growth"]["support_dist_min_chords"] == pytest.approx(0.15)
    assert spec["off_wall_growth"]["support_dist_max_chords"] == pytest.approx(0.60)
    assert spec["off_wall_growth"]["stop_at_dist_max"] is True


def test_build_shell_v4_baseline_spec_defaults_to_four_rank_mpi():
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")

    assert spec["solver"]["parallel_mode"] == "mpi"
    assert spec["solver"]["mpi_ranks"] == 4
    assert spec["solver"]["cpu_threads"] == 4
    assert spec["solver"]["omp_threads_per_rank"] == 1
    assert spec["solver"]["mpi_launcher"] == "mpirun"


def test_shell_v4_solver_command_uses_four_rank_mpi_with_one_thread_per_rank():
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")

    command = _solver_command(spec, "su2_runtime.cfg")
    env = _solver_env(spec)

    assert command == ["mpirun", "-np", "4", "SU2_CFD", "-t", "1", "su2_runtime.cfg"]
    assert env["OMP_NUM_THREADS"] == "1"


def test_build_su2_cfg_includes_surface_paraview_ascii_for_wall_diagnostics():
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")

    cfg = _build_su2_cfg(spec=spec, mesh_filename="mesh.su2")

    assert "OUTPUT_FILES= (RESTART_ASCII, PARAVIEW_ASCII, SURFACE_CSV, SURFACE_PARAVIEW_ASCII)" in cfg


def test_derive_wall_diagnostics_from_surface_vtk_computes_yplus_summary(tmp_path: Path):
    surface_vtk = tmp_path / "surface.vtk"
    surface_vtk.write_text(
        """# vtk DataFile Version 3.0
vtk output
ASCII
DATASET POLYDATA
POINTS 2 double
0.0 0.0 0.0
1.0 0.0 0.0
POLYGONS 0 0
POINT_DATA 2
SCALARS Pressure_Coefficient double 1
LOOKUP_TABLE default
-0.5 -0.25
VECTORS Skin_Friction_Coefficient double
0.002 0.0 0.0
0.008 0.0 0.0
""",
        encoding="utf-8",
    )

    diagnostics = _derive_wall_diagnostics_from_surface_vtk(
        surface_vtk,
        {
            (0.0, 0.0, 0.0): 5.0e-5,
            (1.0, 0.0, 0.0): 5.0e-5,
        },
        {
            "density_kgpm3": 1.225,
            "velocity_mps": 6.5,
            "dynamic_viscosity_pas": 1.789e-5,
        },
    )

    assert diagnostics is not None
    assert diagnostics["point_count"] == 2
    assert diagnostics["y_plus"]["source"] == "derived_from_surface_vtk_skin_friction_and_mesh_first_layer_height"
    assert diagnostics["y_plus"]["max"] > diagnostics["y_plus"]["min"] > 0.0
    assert diagnostics["pressure_coefficient"]["min"] == pytest.approx(-0.5)
    assert diagnostics["pressure_coefficient"]["max"] == pytest.approx(-0.25)
    assert diagnostics["skin_friction_coefficient_magnitude"]["max"] == pytest.approx(0.008)


def test_derive_wall_diagnostics_from_surface_vtk_prefers_native_yplus_field(tmp_path: Path):
    surface_vtk = tmp_path / "surface.vtk"
    surface_vtk.write_text(
        """# vtk DataFile Version 3.0
vtk output
ASCII
DATASET POLYDATA
POINTS 2 double
1.036585 0.0 0.001933869 1.023165 0.0 0.003836836
POLYGONS 0 0
POINT_DATA 2
SCALARS Pressure_Coefficient double 1
LOOKUP_TABLE default
-0.4 -0.2
VECTORS Skin_Friction_Coefficient double
0.002 0.0 0.0 0.004 0.0 0.0
SCALARS Y_Plus double 1
LOOKUP_TABLE default
0.62 0.95
""",
        encoding="utf-8",
    )

    diagnostics = _derive_wall_diagnostics_from_surface_vtk(
        surface_vtk,
        {},
        {
            "density_kgpm3": 1.225,
            "velocity_mps": 6.5,
            "dynamic_viscosity_pas": 1.789e-5,
        },
    )

    assert diagnostics is not None
    assert diagnostics["point_count"] == 2
    assert diagnostics["y_plus_field"] == "Y_Plus"
    assert diagnostics["y_plus"]["source"] == "native_surface_vtk_y_plus"
    assert diagnostics["y_plus"]["min"] == pytest.approx(0.62)
    assert diagnostics["y_plus"]["max"] == pytest.approx(0.95)


def test_derive_wall_diagnostics_from_surface_vtk_matches_truncated_surface_coordinates(tmp_path: Path):
    surface_vtk = tmp_path / "surface.vtk"
    surface_vtk.write_text(
        """# vtk DataFile Version 3.0
vtk output
ASCII
DATASET POLYDATA
POINTS 1 double
1.036585 0.0 0.001933869
POLYGONS 0 0
POINT_DATA 1
VECTORS Skin_Friction_Coefficient double
0.002 0.0 0.0
""",
        encoding="utf-8",
    )

    diagnostics = _derive_wall_diagnostics_from_surface_vtk(
        surface_vtk,
        {
            (1.036584705781, 0.0, 0.001933869329): 5.0e-5,
        },
        {
            "density_kgpm3": 1.225,
            "velocity_mps": 6.5,
            "dynamic_viscosity_pas": 1.789e-5,
        },
    )

    assert diagnostics is not None
    assert diagnostics["point_count"] == 1
    assert diagnostics["y_plus"]["source"] == "derived_from_surface_vtk_skin_friction_and_mesh_first_layer_height"
    assert diagnostics["y_plus"]["min"] > 0.0


def test_estimate_first_cell_yplus_range_returns_positive_laminar_to_turbulent_band():
    result = estimate_first_cell_yplus_range(
        velocity_mps=6.5,
        density_kgpm3=1.225,
        dynamic_viscosity_pas=1.789e-5,
        ref_length_m=1.05,
        first_layer_height_m=5.0e-5,
    )

    assert result["reynolds_number"] > 1.0e5
    assert result["y_plus_min"] > 0.0
    assert result["y_plus_max"] > result["y_plus_min"]


def test_run_shell_v4_half_wing_route_smoke_creates_required_groups_and_bl_cells(tmp_path: Path):
    out_dir = tmp_path / "shell_v4_smoke"

    result = run_shell_v4_half_wing_bl_mesh_macsafe(
        out_dir=out_dir,
        run_su2=False,
        allow_swap_risk=False,
        overrides={
            "study_level": "BL_macsafe_baseline",
            "geometry": {
                "airfoil_loop_points": 24,
                "half_span_stations": 8,
            },
            "boundary_layer": {
                "first_layer_height_m": 2.0e-3,
                "layers": 9,
                "growth_ratio": 1.20,
            },
            "wake_refinement": {
                "wake_length_chords": 2.5,
                "near_wake_cell_size_chords": 0.18,
            },
            "farfield": {
                "upstream_chords": 2.0,
                "downstream_chords": 3.0,
                "normal_chords": 2.0,
                "outer_cell_size_chords": 2.2,
            },
            "tip_refinement": {
                "spanwise_length_chords": 0.45,
                "cell_size_chords": 0.20,
            },
        },
    )

    assert result["status"] == "success"
    assert result["solver"]["status"] == "not_run"
    assert result["solver"]["parallel_mode"] == "mpi"
    assert result["solver"]["mpi_ranks"] == 4
    assert result["solver"]["omp_threads_per_rank"] == 1
    assert result["solver"]["solver_command"] == "mpirun -np 4 SU2_CFD -t 1 su2_runtime.cfg"
    assert result["solver"]["launch_environment"]["OMP_NUM_THREADS"] == "1"
    assert result["case_summary"]["parallel_mode"] == "mpi"
    assert result["case_summary"]["mpi_ranks"] == 4
    assert result["case_summary"]["omp_threads_per_rank"] == 1
    assert result["mesh"]["physical_groups"]["wing_wall"]["exists"] is True
    assert result["mesh"]["physical_groups"]["symmetry"]["exists"] is True
    assert result["mesh"]["physical_groups"]["farfield"]["exists"] is True
    assert result["mesh"]["physical_groups"]["wake_refinement_region"]["exists"] is True
    assert result["mesh"]["physical_groups"]["wake_refinement_region"]["virtual"] is True
    assert result["mesh"]["physical_groups"]["tip_refinement_region"]["exists"] is True
    assert result["mesh"]["physical_groups"]["tip_refinement_region"]["virtual"] is True
    assert result["boundary_layer"]["requested_layers"] == 9
    assert result["boundary_layer"]["achieved_layers"] >= 1
    assert result["boundary_layer"]["boundary_layer_cell_count"] > 0
    assert result["reference_values"]["ref_area"] == pytest.approx(17.325)
    assert result["mesh"]["total_cells"] > 0
    assert result["mesh"]["total_nodes"] > 0
    volume_types = result["mesh"]["volume_element_type_counts"]
    assert any(int(key) in {5, 6} and int(value) > 0 for key, value in volume_types.items())
    assert (out_dir / "artifacts" / "mesh" / "mesh.msh").exists()
    assert (out_dir / "report.json").exists()


def test_resolve_real_main_wing_geometry_uses_provider_sections(monkeypatch, tmp_path: Path):
    source_path = tmp_path / "model.vsp3"
    source_path.write_text("<vsp3/>", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.shell_v4_half_wing_bl_mesh_macsafe.extract_native_lifting_surface_sections",
        lambda **_: {
            "source_path": str(source_path),
            "component": "main_wing",
            "surface_count": 1,
            "notes": [],
            "surfaces": [
                {
                    "component": "main_wing",
                    "geom_id": "main",
                    "name": "Main Wing",
                    "caps_group": "main_wing",
                    "symmetric_xz": True,
                    "rotation_deg": [0.0, 0.0, 0.0],
                    "sections": [
                        {
                            "x_le": 0.0,
                            "y_le": 0.0,
                            "z_le": 0.0,
                            "chord": 1.3,
                            "twist_deg": 0.0,
                            "airfoil_name": "test-root",
                            "airfoil_source": "inline_coordinates",
                            "thickness_tc": 0.12,
                            "camber": 0.02,
                            "camber_loc": 0.4,
                            "airfoil_coordinates": [
                                [1.0, 0.0],
                                [0.7, 0.05],
                                [0.0, 0.0],
                                [0.3, -0.03],
                                [1.0, 0.0],
                            ],
                        },
                        {
                            "x_le": 0.2,
                            "y_le": 16.5,
                            "z_le": 0.8,
                            "chord": 0.45,
                            "twist_deg": 0.0,
                            "airfoil_name": "test-tip",
                            "airfoil_source": "inline_coordinates",
                            "thickness_tc": 0.12,
                            "camber": 0.02,
                            "camber_loc": 0.4,
                            "airfoil_coordinates": [
                                [1.0, 0.0],
                                [0.7, 0.04],
                                [0.0, 0.0],
                                [0.3, -0.025],
                                [1.0, 0.0],
                            ],
                        },
                    ],
                }
            ],
        },
    )

    result = _resolve_real_main_wing_geometry(
        geometry={
            "shape_mode": "esp_rebuilt_main_wing",
            "source_path": str(source_path),
        },
        artifact_dir=tmp_path / "artifacts",
    )

    assert result["shape_mode"] == "esp_rebuilt_main_wing"
    assert result["surface_name"] == "Main Wing"
    assert len(result["sections"]) == 2
    assert result["overall_bounds"]["y_max"] == pytest.approx(16.5)
    assert Path(result["artifact_path"]).exists()


def test_real_main_wing_occ_shell_sews_duplicate_tip_edges_before_bl_boundary_extraction(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_path = repo_root / "data" / "blackcat_004_origin.vsp3"
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")
    real_geometry = _resolve_real_main_wing_geometry(
        geometry={
            **spec["geometry"],
            "shape_mode": "esp_rebuilt_main_wing",
            "source_path": str(source_path),
            "component": "main_wing",
        },
        artifact_dir=tmp_path / "artifacts",
    )
    gmsh = load_gmsh()
    gmsh.initialize()
    try:
        gmsh.model.add("real_main_wing_bl_boundary")
        wall_surface_tags, _, _ = _build_real_main_wing_occ_shell(
            gmsh=gmsh,
            section_profiles=real_geometry["section_profiles"],
        )
        _set_shell_transfinite_controls(
            gmsh,
            chord_m=float(spec["geometry"]["chord_m"]),
            half_span_m=float(spec["geometry"]["half_span_m"]),
            airfoil_loop_points=int(spec["geometry"]["airfoil_loop_points"]),
            half_span_stations=int(spec["geometry"]["half_span_stations"]),
        )
        bl_top_surface_tags: list[int] = []
        extbl = gmsh.model.geo.extrudeBoundaryLayer(
            [(2, tag) for tag in wall_surface_tags],
            [1] * int(spec["boundary_layer"]["layers"]),
            _layer_cumulative_heights(
                float(spec["boundary_layer"]["first_layer_height_m"]),
                float(spec["boundary_layer"]["growth_ratio"]),
                int(spec["boundary_layer"]["layers"]),
            ),
            True,
        )
        for index in range(1, len(extbl)):
            if extbl[index][0] == 3:
                bl_top_surface_tags.append(int(extbl[index - 1][1]))
        gmsh.model.geo.synchronize()
        hole_boundary = gmsh.model.getBoundary(
            [(2, tag) for tag in bl_top_surface_tags],
            combined=True,
            oriented=False,
            recursive=False,
        )
        hole_curves = [int(tag) for dim, tag in hole_boundary if dim == 1]
    finally:
        gmsh.finalize()

    assert len(hole_curves) == 3


def test_real_main_wing_root_closure_plan_avoids_duplicate_loops_and_self_intersections(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_path = repo_root / "data" / "blackcat_004_origin.vsp3"
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")
    real_geometry = _resolve_real_main_wing_geometry(
        geometry={
            **spec["geometry"],
            "shape_mode": "esp_rebuilt_main_wing",
            "source_path": str(source_path),
            "component": "main_wing",
        },
        artifact_dir=tmp_path / "artifacts",
    )
    gmsh = load_gmsh()
    gmsh.initialize()
    try:
        gmsh.model.add("real_main_wing_root_closure_plan")
        wall_surface_tags, _, _ = _build_real_main_wing_occ_shell(
            gmsh=gmsh,
            section_profiles=real_geometry["section_profiles"],
        )
        _set_shell_transfinite_controls(
            gmsh,
            chord_m=float(spec["geometry"]["chord_m"]),
            half_span_m=float(spec["geometry"]["half_span_m"]),
            airfoil_loop_points=int(spec["geometry"]["airfoil_loop_points"]),
            half_span_stations=int(spec["geometry"]["half_span_stations"]),
        )
        bl_top_surface_tags: list[int] = []
        extbl = gmsh.model.geo.extrudeBoundaryLayer(
            [(2, tag) for tag in wall_surface_tags],
            [1] * int(spec["boundary_layer"]["layers"]),
            _layer_cumulative_heights(
                float(spec["boundary_layer"]["first_layer_height_m"]),
                float(spec["boundary_layer"]["growth_ratio"]),
                int(spec["boundary_layer"]["layers"]),
            ),
            True,
        )
        for index in range(1, len(extbl)):
            if extbl[index][0] == 3:
                bl_top_surface_tags.append(int(extbl[index - 1][1]))
        gmsh.model.geo.synchronize()
        plan = _build_real_wing_root_closure_plan(
            gmsh=gmsh,
            extbl=extbl,
            bl_top_surface_tags=bl_top_surface_tags,
            chord_m=float(spec["geometry"]["chord_m"]),
            bl_total_thickness_m=float(spec["boundary_layer"]["target_total_thickness_m"]),
            x_min=-5.0 * float(spec["geometry"]["chord_m"]),
            x_max=10.0 * float(spec["geometry"]["chord_m"]),
            z_min=-5.0 * float(spec["geometry"]["chord_m"]),
            z_max=5.0 * float(spec["geometry"]["chord_m"]),
        )
    finally:
        gmsh.finalize()

    assert plan["mode"] == "use_bl_generated_faces"
    assert plan["holed_symmetry_face_used"] is False
    assert plan["duplicate_curve_tags"] == []
    assert len(plan["ordered_root_curve_tags"]) == 3
    assert len(plan["root_side_surface_tags"]) == 3
    assert all(not payload["self_intersections"] for payload in plan["patch_loop_checks"].values())


def test_real_main_wing_root_closure_2d_meshing_stage_completes_cleanly(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_path = repo_root / "data" / "blackcat_004_origin.vsp3"
    gmsh = load_gmsh()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Geometry.ExtrudeReturnLateralEntities", 1)
        gmsh.model.add("real_main_wing_root_closure_2d")
        real_geometry = _resolve_real_main_wing_geometry(
            geometry={
                "shape_mode": "esp_rebuilt_main_wing",
                "source_path": str(source_path),
                "component": "main_wing",
                "chord_m": 1.05,
                "half_span_m": 16.5,
                "airfoil_loop_points": 48,
                "half_span_stations": 18,
            },
            artifact_dir=tmp_path / "artifacts",
        )
        wall_surface_tags, _, _ = _build_real_main_wing_occ_shell(
            gmsh=gmsh,
            section_profiles=real_geometry["section_profiles"],
        )
        _set_shell_transfinite_controls(
            gmsh,
            chord_m=1.05,
            half_span_m=float(real_geometry["overall_bounds"]["y_max"]),
            airfoil_loop_points=48,
            half_span_stations=18,
        )
        cumulative_heights = _layer_cumulative_heights(1.0e-3, 1.20, 8)
        extbl = gmsh.model.geo.extrudeBoundaryLayer(
            [(2, tag) for tag in wall_surface_tags],
            [1] * 8,
            cumulative_heights,
            True,
        )
        bl_top_surface_tags: list[int] = []
        bl_volume_tags: list[int] = []
        for index in range(1, len(extbl)):
            if extbl[index][0] == 3:
                bl_volume_tags.append(int(extbl[index][1]))
                bl_top_surface_tags.append(int(extbl[index - 1][1]))
        gmsh.model.geo.synchronize()
        chord_m = 1.05
        geometry_bounds = real_geometry["overall_bounds"]
        x_min = float(geometry_bounds["x_min"]) - 2.0 * chord_m
        x_max = float(geometry_bounds["x_max"]) + 3.0 * chord_m
        y_max = float(geometry_bounds["y_max"]) + 2.0 * chord_m
        z_min = float(geometry_bounds["z_min"]) - 2.0 * chord_m
        z_max = float(geometry_bounds["z_max"]) + 2.0 * chord_m
        p1 = gmsh.model.geo.addPoint(x_min, 0.0, z_min, chord_m)
        p2 = gmsh.model.geo.addPoint(x_max, 0.0, z_min, chord_m)
        p3 = gmsh.model.geo.addPoint(x_max, y_max, z_min, chord_m)
        p4 = gmsh.model.geo.addPoint(x_min, y_max, z_min, chord_m)
        p5 = gmsh.model.geo.addPoint(x_min, 0.0, z_max, chord_m)
        p6 = gmsh.model.geo.addPoint(x_max, 0.0, z_max, chord_m)
        p7 = gmsh.model.geo.addPoint(x_max, y_max, z_max, chord_m)
        p8 = gmsh.model.geo.addPoint(x_min, y_max, z_max, chord_m)
        l1 = gmsh.model.geo.addLine(p1, p2)
        l2 = gmsh.model.geo.addLine(p2, p3)
        l3 = gmsh.model.geo.addLine(p3, p4)
        l4 = gmsh.model.geo.addLine(p4, p1)
        l5 = gmsh.model.geo.addLine(p5, p6)
        l6 = gmsh.model.geo.addLine(p6, p7)
        l7 = gmsh.model.geo.addLine(p7, p8)
        l8 = gmsh.model.geo.addLine(p8, p5)
        l9 = gmsh.model.geo.addLine(p1, p5)
        l10 = gmsh.model.geo.addLine(p2, p6)
        l11 = gmsh.model.geo.addLine(p3, p7)
        l12 = gmsh.model.geo.addLine(p4, p8)
        plan = _build_real_wing_root_closure_plan(
            gmsh=gmsh,
            extbl=extbl,
            bl_top_surface_tags=bl_top_surface_tags,
            chord_m=chord_m,
            bl_total_thickness_m=float(cumulative_heights[-1]),
            x_min=x_min,
            x_max=x_max,
            z_min=z_min,
            z_max=z_max,
        )
        symmetry_surface_tags, plan = _build_real_wing_root_closure_surfaces(
            gmsh=gmsh,
            plan=plan,
            p1_tag=p1,
            p2_tag=p2,
            p5_tag=p5,
            p6_tag=p6,
            l1_tag=l1,
            l5_tag=l5,
            l9_tag=l9,
            l10_tag=l10,
        )
        farfield_surface_tags = [
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l2, l11, -l6, -l10])]),
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l3, l12, -l7, -l11])]),
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l4, l9, -l8, -l12])]),
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l1, l2, l3, l4])]),
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l5, l6, l7, l8])]),
        ]
        gmsh.model.geo.addVolume(
            [gmsh.model.geo.addSurfaceLoop(bl_top_surface_tags + symmetry_surface_tags + farfield_surface_tags)]
        )
        gmsh.model.geo.synchronize()
        gmsh.model.mesh.generate(2)
    finally:
        gmsh.finalize()

    assert plan["mode"] == "use_bl_generated_faces"
    assert plan["holed_symmetry_face_used"] is False
    assert plan["duplicate_curve_tags"] == []
    assert len(plan["surface_tags"]["root_side"]) == 3


def test_real_main_wing_bl_protection_only_triggers_in_outboard_local_chord_zone(tmp_path: Path):
    class _FakeMesh:
        def __init__(self, nodes_by_surface: dict[int, list[tuple[int, tuple[float, float, float]]]]) -> None:
            self._nodes_by_surface = nodes_by_surface

        def getNodes(
            self,
            dim: int,
            tag: int,
            includeBoundary: bool = True,
            returnParametricCoord: bool = False,
        ) -> tuple[list[int], list[float], list[float]]:
            assert dim == 2
            payload = self._nodes_by_surface[int(tag)]
            node_tags = [node_tag for node_tag, _ in payload]
            coordinates = [coordinate for _, xyz in payload for coordinate in xyz]
            return node_tags, coordinates, []

    class _FakeModel:
        def __init__(self, nodes_by_surface: dict[int, list[tuple[int, tuple[float, float, float]]]]) -> None:
            self.mesh = _FakeMesh(nodes_by_surface)

        def getCurrent(self) -> str:
            return "fake_model"

    class _FakeView:
        def __init__(self) -> None:
            self._next_tag = 1

        def add(self, _name: str) -> int:
            tag = self._next_tag
            self._next_tag += 1
            return tag

        def addModelData(
            self,
            view_tag: int,
            step: int,
            model_name: str,
            data_type: str,
            node_tags: list[int],
            values: list[list[float]],
            *,
            numComponents: int,
        ) -> None:
            assert view_tag == 1
            assert step == 0
            assert model_name == "fake_model"
            assert data_type == "NodeData"
            assert numComponents == 1
            assert len(node_tags) == len(values)

        def getIndex(self, view_tag: int) -> int:
            return int(view_tag - 1)

    class _FakeGmsh:
        def __init__(self, nodes_by_surface: dict[int, list[tuple[int, tuple[float, float, float]]]]) -> None:
            self.model = _FakeModel(nodes_by_surface)
            self.view = _FakeView()

    def _pick_section_surface_point(
        section: dict[str, object],
        profile: list[tuple[float, float, float]],
        *,
        target_x_rel: float,
    ) -> tuple[float, float, float]:
        x_le = float(section["x_le"])
        chord = float(section["chord"])
        candidates = sorted(
            profile,
            key=lambda point: abs(((float(point[0]) - x_le) / chord) - target_x_rel),
        )[:8]
        return max(candidates, key=lambda point: float(point[2]))

    repo_root = Path(__file__).resolve().parents[2]
    source_path = repo_root / "data" / "blackcat_004_origin.vsp3"
    real_geometry = _resolve_real_main_wing_geometry(
        geometry={
            "shape_mode": "esp_rebuilt_main_wing",
            "source_path": str(source_path),
            "component": "main_wing",
        },
        artifact_dir=tmp_path,
    )
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")
    sections = list(real_geometry["sections"])
    profiles = list(real_geometry["section_profiles"])
    nodes_by_surface = {
        1: [
            (101, _pick_section_surface_point(sections[0], profiles[0], target_x_rel=0.85)),
            (102, _pick_section_surface_point(sections[4], profiles[4], target_x_rel=0.85)),
            (103, _pick_section_surface_point(sections[-1], profiles[-1], target_x_rel=0.85)),
        ]
    }

    summary = _build_real_wing_bl_protection_field(
        gmsh=_FakeGmsh(nodes_by_surface),
        wall_surface_tags=[1],
        sections=sections,
        protection=dict(spec["real_wing_bl_protection"]),
        base_total_thickness_m=0.0164990848,
        ref_chord_m=float(spec["geometry"]["chord_m"]),
        half_span_m=float(spec["geometry"]["half_span_m"]),
    )

    assert summary is not None
    assert summary["node_count"] == 3
    assert summary["outboard_activated_node_count"] == 1
    assert summary["triggered_node_count"] == 1
    assert summary["thickness_limit_active_node_count"] == 1
    assert summary["triggered_span_y_range_m"]["min"] > 15.0
    assert summary["triggered_local_chord_range_m"]["max"] < 0.6
    assert summary["scale_min"] < 1.0


def test_real_main_wing_tip_bl_interference_analysis_requests_local_tip_truncation(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_path = repo_root / "data" / "blackcat_004_origin.vsp3"
    real_geometry = _resolve_real_main_wing_geometry(
        geometry={
            "shape_mode": "esp_rebuilt_main_wing",
            "source_path": str(source_path),
            "component": "main_wing",
        },
        artifact_dir=tmp_path / "artifacts",
    )
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")

    analysis = _analyze_real_wing_tip_bl_interference(
        sections=list(real_geometry["sections"]),
        protection=dict(spec["real_wing_bl_protection"]),
        base_total_thickness_m=0.0164990848,
        half_span_m=float(real_geometry["overall_bounds"]["y_max"]),
    )

    assert analysis["enabled"] is True
    assert analysis["intervention_mode"] == "scaling_and_truncation"
    assert analysis["risk_sample_count"] > 0
    assert analysis["min_predicted_bl_top_clearance_m"] < analysis["required_min_bl_top_clearance_m"]
    assert analysis["tip_truncation"]["enabled"] is True
    assert analysis["tip_truncation"]["start_y_m"] > 15.0
    assert analysis["triggered_span_y_range_m"]["min"] > 15.0


def test_real_main_wing_tip_bl_interference_analysis_reports_suppressed_risk_after_truncation(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_path = repo_root / "data" / "blackcat_004_origin.vsp3"
    real_geometry = _resolve_real_main_wing_geometry(
        geometry={
            "shape_mode": "esp_rebuilt_main_wing",
            "source_path": str(source_path),
            "component": "main_wing",
        },
        artifact_dir=tmp_path / "artifacts",
    )
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")

    analysis = _analyze_real_wing_tip_bl_interference(
        sections=list(real_geometry["sections"]),
        protection=dict(spec["real_wing_bl_protection"]),
        base_total_thickness_m=0.0164990848,
        half_span_m=float(real_geometry["overall_bounds"]["y_max"]),
        truncation_start_y_m=14.0,
    )

    assert analysis["tip_truncation"]["enabled"] is True
    assert analysis["tip_truncation"]["start_y_m"] == pytest.approx(14.0)
    assert analysis["risk_sample_count"] == 0
    assert analysis["suppressed_risk_sample_count"] > 0
    assert analysis["full_sample_count"] > analysis["retained_sample_count"] > 0
    assert analysis["full_min_predicted_bl_top_clearance_m"] < analysis["required_min_bl_top_clearance_m"]
    assert analysis["intervention_mode"] == "scaling_and_truncation"


def test_collect_extbl_surfaces_in_y_band_includes_tip_truncation_neighborhood():
    class _FakeModel:
        def __init__(self, bboxes: dict[int, tuple[float, float, float, float, float, float]]) -> None:
            self._bboxes = bboxes

        def getEntities(self, dim: int) -> list[tuple[int, int]]:
            assert dim == 2
            return [(2, tag) for tag in self._bboxes]

        def getBoundingBox(self, dim: int, tag: int) -> tuple[float, float, float, float, float, float]:
            assert dim == 2
            return self._bboxes[int(tag)]

    class _FakeGmsh:
        def __init__(self, bboxes: dict[int, tuple[float, float, float, float, float, float]]) -> None:
            self.model = _FakeModel(bboxes)

    gmsh = _FakeGmsh(
        {
            339: (0.13, 13.997, 0.58, 0.89, 14.000, 0.68),
            348: (0.11, 13.498, 0.54, 0.94, 14.000, 0.68),
            369: (0.88, 13.998, 0.57, 0.91, 14.002, 0.59),
            436: (0.89, 13.498, 0.54, 0.94, 13.871, 0.58),
            520: (0.50, 12.700, 0.40, 0.70, 13.100, 0.52),
        }
    )

    matching = _collect_extbl_surfaces_in_y_band(
        gmsh,
        [(2, 339), (2, 348), (2, 369), (2, 436), (2, 520)],
        y_min=13.5,
        y_max=14.0,
    )

    assert matching == [339, 348, 369, 436]


def test_select_tip_truncation_connector_band_surface_tags_targets_local_strip():
    class _FakeModel:
        def __init__(self, bboxes: dict[int, tuple[float, float, float, float, float, float]]) -> None:
            self._bboxes = bboxes

        def getBoundingBox(self, dim: int, tag: int) -> tuple[float, float, float, float, float, float]:
            assert dim == 2
            return self._bboxes[int(tag)]

    class _FakeGmsh:
        def __init__(self, bboxes: dict[int, tuple[float, float, float, float, float, float]]) -> None:
            self.model = _FakeModel(bboxes)

    gmsh = _FakeGmsh(
        {
            19: (0.23, 14.910196, 0.79, 0.66, 16.5, 0.84),
            120: (0.12, 14.904074, 0.54, 0.95, 14.910196, 0.74),
            121: (0.80, 14.904074, 0.54, 0.94, 14.910196, 0.67),
            130: (0.12, 13.5, 0.54, 0.95, 14.910196, 0.74),
            140: (0.12, 14.910196, 0.54, 0.95, 16.5, 0.74),
        }
    )

    matching = _select_tip_truncation_connector_band_surface_tags(
        gmsh=gmsh,
        wall_surface_tags=[19, 120, 121, 130, 140],
        band_start_y_m=14.904074064233518,
        start_y_m=14.91019607843137,
        tip_surface_tag=19,
    )

    assert matching == [120, 121]


def test_real_main_wing_tip_truncation_inserts_connector_band_strip(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_path = repo_root / "data" / "blackcat_004_origin.vsp3"
    start_y = 14.91019607843137
    spec = build_shell_v4_half_wing_bl_macsafe_spec(
        "BL_macsafe_baseline",
        overrides={
            "geometry": {
                "shape_mode": "esp_rebuilt_main_wing",
                "source_path": str(source_path),
                "component": "main_wing",
                "airfoil_loop_points": 48,
                "half_span_stations": 18,
            }
        },
    )
    real_geometry = _resolve_real_main_wing_geometry(
        geometry=spec["geometry"],
        artifact_dir=tmp_path / "artifacts",
    )
    augmented_sections, truncation_geometry = _augment_real_wing_sections_for_tip_truncation(
        sections=list(real_geometry["sections"]),
        start_y_m=start_y,
        protection=spec["real_wing_bl_protection"],
    )

    assert truncation_geometry["connector_band_start_y_m"] is not None
    assert truncation_geometry["inserted_connector_band_section"] is True
    assert len(augmented_sections) == len(real_geometry["sections"]) + 2

    gmsh = load_gmsh()
    gmsh.initialize()
    try:
        gmsh.model.add("real_main_wing_tip_connector_strip")
        wall_surface_tags, _, geometry = _build_real_main_wing_occ_shell(
            gmsh=gmsh,
            section_profiles=[_global_section_profile_points(section) for section in augmented_sections],
        )
        connector_tags = _select_tip_truncation_connector_band_surface_tags(
            gmsh=gmsh,
            wall_surface_tags=wall_surface_tags,
            band_start_y_m=truncation_geometry["connector_band_start_y_m"],
            start_y_m=start_y,
            tip_surface_tag=int(geometry["tip_surface_tag"]),
        )
        assert connector_tags
        for surface_tag in connector_tags:
            _x_min, y_min, _z_min, _x_max, y_max, _z_max = gmsh.model.getBoundingBox(2, int(surface_tag))
            assert y_min >= truncation_geometry["connector_band_start_y_m"] - 1.0e-6
            assert y_max >= start_y - 1.0e-6
            assert y_max <= start_y + 1.0e-6
    finally:
        gmsh.finalize()


def test_run_shell_v4_real_main_wing_prelaunch_smoke_reaches_prelaunch_clean_with_tip_truncation(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    source_path = repo_root / "data" / "blackcat_004_origin.vsp3"
    out_dir = tmp_path / "real_main_wing_smoke"

    result = run_shell_v4_half_wing_bl_mesh_macsafe(
        out_dir=out_dir,
        run_su2=False,
        allow_swap_risk=False,
        overrides={
            "geometry": {
                "shape_mode": "esp_rebuilt_main_wing",
                "source_path": str(source_path),
                "component": "main_wing",
                "airfoil_loop_points": 48,
                "half_span_stations": 18,
            },
            "boundary_layer": {
                "first_layer_height_m": 1.0e-3,
                "layers": 8,
                "growth_ratio": 1.20,
            },
            "wake_refinement": {
                "wake_length_chords": 2.0,
                "wake_height_chords": 0.4,
                "near_wake_cell_size_chords": 0.18,
            },
            "farfield": {
                "upstream_chords": 2.0,
                "downstream_chords": 3.0,
                "normal_chords": 2.0,
                "outer_cell_size_chords": 2.2,
            },
            "tip_refinement": {
                "spanwise_length_chords": 0.25,
                "cell_size_chords": 0.20,
            },
            "cell_budget": {
                "target_total_cells_min": 10_000,
                "target_total_cells_max": 500_000,
                "hard_fail_total_cells": 1_000_000,
                "min_volume_to_wall_ratio": 5.0,
                "max_bl_collapse_rate": 0.2,
            },
        },
    )

    assert result["status"] == "success"
    assert result["geometry"]["shape_mode"] == "esp_rebuilt_main_wing"
    assert result["case_summary"]["root_closure_mode"] == "use_bl_generated_faces"
    assert result["case_summary"]["mesh_algorithm3d"] == 1
    assert result.get("error") is None
    assert result["topology_checks"]["root_closure"]["duplicate_curve_tags"] == []
    assert result["topology_checks"]["root_closure"]["holed_symmetry_face_used"] is False
    assert len(result["topology_checks"]["root_closure"]["surface_tags"]["root_side"]) == 3
    assert (
        result["topology_checks"]["root_closure"]["surface_mesh_cleanup"]["removed_degenerate_element_count"]
        > 0
    )
    assert all(
        not payload["self_intersections"]
        for payload in result["topology_checks"]["root_closure"]["patch_loop_checks"].values()
    )
    assert result["case_summary"]["bl_local_protection"]["triggered_span_y_range_m"]["min"] > 15.0
    assert result["case_summary"]["bl_local_protection"]["intervention_mode"] == "scaling_and_truncation"
    assert result["case_summary"]["bl_local_protection"]["tip_truncation"]["enabled"] is True
    assert result["case_summary"]["bl_local_protection"]["tip_truncation"]["connector_band_start_y_m"] is not None
    assert len(result["case_summary"]["bl_local_protection"]["tip_truncation_connector_band_surface_tags"]) > 0
    assert result["case_summary"]["pre_3d_bl_clearance"]["risk_sample_count"] == 0
    assert (
        result["case_summary"]["pre_3d_bl_clearance"]["min_predicted_bl_top_clearance_m"]
        >= result["case_summary"]["pre_3d_bl_clearance"]["required_min_bl_top_clearance_m"] - 1.0e-9
    )
