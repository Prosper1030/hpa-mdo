from __future__ import annotations

from pathlib import Path

import pytest

from hpa_meshing.shell_v4_half_wing_bl_mesh_macsafe import (
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
