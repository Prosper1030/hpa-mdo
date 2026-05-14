from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006i_grid_convergence_campaign.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006i_grid_convergence", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["wo006i_grid_convergence"] = module
    spec.loader.exec_module(module)
    return module


def _rung(
    rung_id: str,
    *,
    cells: int,
    cl: float,
    cd: float,
    cm: float,
    force_spread: float = 0.004,
    residual_slope: float = -0.02,
    status: str = "success",
    wall_status: str = "pass",
    boundary_layer_status: str = "pass",
    yplus_status: str = "pass",
    setup_id: str = "baseline_a_current_go_wall_resolved_rans_sa_alpha5",
    force_window_rows: int = 100,
):
    return {
        "rung_id": rung_id,
        "status": status,
        "mesh": {
            "node_count": max(1, cells // 5),
            "volume_element_count": cells,
            "marker_status": "pass",
            "quality_status": "pass",
            "markers": {"wing_wall": {"element_count": 100}, "farfield": {"element_count": 60}},
            "physical_groups": {
                "wing_wall": {"dimension": 2},
                "farfield": {"dimension": 2},
                "fluid": {"dimension": 3},
            },
        },
        "su2": {
            "run_status": "completed",
            "iterations": 180,
            "coefficients": {"cl": cl, "cd": cd, "cm": cm},
            "residuals": {"rms[P]": -2.0, "rms[U]": -1.2},
            "force_stability": {
                "status": "pass",
                "max_relative_spread": force_spread,
                "window_rows": force_window_rows,
            },
            "residual_stability": {
                "status": "pass",
                "max_abs_slope_per_iter": abs(residual_slope),
                "trend": "improving",
            },
        },
        "physics_setup_id": setup_id,
        "geometry_source": "current_avl_compromise_conservative_closed",
        "wall_resolution_status": wall_status,
        "boundary_layer_status": boundary_layer_status,
        "near_wall_yplus_status": yplus_status,
    }


def _good_setup_gate(module):
    return module.evaluate_cfd_setup_gate(
        physics_setup={
            "physics_setup_id": "baseline_a_current_go_wall_resolved_rans_sa_alpha5",
            "solver": "INC_RANS",
            "turbulence_model": "SA",
            "wall_profile": "adiabatic_no_slip",
            "wall_bc": "MARKER_HEATFLUX",
            "farfield_bc": "MARKER_FAR",
            "boundary_layer": "owned_conformal_bl_core_handoff",
            "near_wall_yplus_status": "pass",
            "conformal_bl_core_handoff_status": "pass",
            "inc_nondim": "INITIAL_VALUES",
        }
    )


def test_grid_trend_promotes_three_stable_wall_resolved_rungs_to_grid_ready() -> None:
    module = _load_module()

    setup_gate = _good_setup_gate(module)
    result = module.evaluate_grid_convergence(
        [
            _rung("coarse", cells=1_100_000, cl=1.20, cd=0.0350, cm=-0.03),
            _rung("medium", cells=3_000_000, cl=1.18, cd=0.0348, cm=-0.031),
            _rung("fine", cells=9_000_000, cl=1.17, cd=0.0347, cm=-0.0315),
        ],
        require_wall_resolved=True,
        setup_gate=setup_gate,
    )

    assert setup_gate["status"] == "pass"
    assert result["cfd_status"] == "grid_convergence_ready"
    assert result["goal_status"] == "COMPLETE"
    assert result["successful_rung_count"] == 3
    assert result["grid_trend"]["status"] == "stable_enough_for_low_confidence"
    assert result["grid_trend"]["cl_relative_change_medium_to_fine"] < 0.02
    assert result["grid_trend"]["cd_relative_change_medium_to_fine"] < 0.02
    assert result["grid_trend"]["cm_absolute_change_medium_to_fine"] < 0.005


def test_grid_trend_rejects_single_smoke_or_missing_cm_as_incomplete() -> None:
    module = _load_module()
    setup_gate = _good_setup_gate(module)

    single = module.evaluate_grid_convergence(
        [_rung("route_smoke", cells=490_000, cl=1.1, cd=0.036, cm=-0.03)],
        require_wall_resolved=True,
        setup_gate=setup_gate,
    )
    missing_cm_rung = _rung("fine", cells=3_000_000, cl=1.2, cd=0.036, cm=-0.03)
    missing_cm_rung["su2"]["coefficients"]["cm"] = None
    missing = module.evaluate_grid_convergence(
        [
            _rung("coarse", cells=1_000_000, cl=1.2, cd=0.036, cm=-0.03),
            _rung("medium", cells=2_000_000, cl=1.19, cd=0.035, cm=-0.031),
            missing_cm_rung,
        ],
        require_wall_resolved=True,
        setup_gate=setup_gate,
    )

    assert single["cfd_status"] == "route_smoke"
    assert single["goal_status"] == "INCOMPLETE"
    assert "fewer_than_three_successful_rungs" in single["blockers"]
    assert missing["cfd_status"] == "mesh_ladder_incomplete"
    assert missing["goal_status"] == "INCOMPLETE"
    assert "fine_missing_finite_cm" in missing["blockers"]


def test_grid_trend_rejects_marker_mismatch_or_unstable_forces() -> None:
    module = _load_module()
    setup_gate = _good_setup_gate(module)
    bad_marker = _rung("medium", cells=3_000_000, cl=1.18, cd=0.035, cm=-0.031)
    bad_marker["mesh"]["marker_status"] = "fail"
    unstable = _rung(
        "fine",
        cells=9_000_000,
        cl=1.35,
        cd=0.038,
        cm=-0.06,
        force_spread=0.08,
    )

    result = module.evaluate_grid_convergence(
        [
            _rung("coarse", cells=1_100_000, cl=1.2, cd=0.036, cm=-0.03),
            bad_marker,
            unstable,
        ],
        require_wall_resolved=True,
        setup_gate=setup_gate,
    )

    assert result["goal_status"] == "INCOMPLETE"
    assert result["cfd_status"] == "mesh_ladder_incomplete"
    assert "medium_marker_or_config_mismatch" in result["blockers"]
    assert "fine_force_stability_fail" in result["blockers"]


def test_grid_trend_rejects_short_force_stability_window_even_when_spread_is_small() -> None:
    module = _load_module()
    setup_gate = _good_setup_gate(module)

    result = module.evaluate_grid_convergence(
        [
            _rung("coarse", cells=1_100_000, cl=1.20, cd=0.0350, cm=-0.03),
            _rung("medium", cells=3_000_000, cl=1.18, cd=0.0348, cm=-0.031),
            _rung(
                "fine",
                cells=9_000_000,
                cl=1.17,
                cd=0.0347,
                cm=-0.0315,
                force_window_rows=25,
            ),
        ],
        require_wall_resolved=True,
        setup_gate=setup_gate,
    )

    assert result["goal_status"] == "INCOMPLETE"
    assert result["cfd_status"] == "mesh_ladder_incomplete"
    assert result["force_stability_gate"]["minimum_window_rows"] == 100
    assert "fine_force_stability_window_too_short" in result["blockers"]


def test_grid_trend_rejects_order_of_magnitude_high_cd_even_when_stable() -> None:
    module = _load_module()
    setup_gate = _good_setup_gate(module)

    result = module.evaluate_grid_convergence(
        [
            _rung("coarse", cells=1_100_000, cl=0.72, cd=0.610, cm=-0.085),
            _rung("medium", cells=3_000_000, cl=0.721, cd=0.615, cm=-0.084),
            _rung("fine", cells=9_000_000, cl=0.720, cd=0.614, cm=-0.0845),
        ],
        require_wall_resolved=True,
        setup_gate=setup_gate,
    )

    assert result["goal_status"] == "INCOMPLETE"
    assert result["cfd_status"] == "mesh_ladder_incomplete"
    assert result["engineering_plausibility_gate"]["status"] == "fail"
    assert result["engineering_plausibility_gate"]["cd_max_for_hpa_main_wing"] == 0.15
    assert "coarse_cd_implausibly_high_for_hpa_main_wing" in result["blockers"]
    assert "medium_cd_implausibly_high_for_hpa_main_wing" in result["blockers"]
    assert "fine_cd_implausibly_high_for_hpa_main_wing" in result["blockers"]


def test_no_bl_setup_is_blocked_even_if_coefficients_are_stable() -> None:
    module = _load_module()
    setup_gate = module.evaluate_cfd_setup_gate()

    result = module.evaluate_grid_convergence(
        [
            _rung(
                "coarse",
                cells=1_100_000,
                cl=1.20,
                cd=0.036,
                cm=-0.03,
                wall_status="not_wall_resolved_no_bl_route",
                boundary_layer_status="not_used_no_bl_route",
                yplus_status="missing",
                setup_id="baseline_a_current_go_no_bl_rans_sa_alpha5",
            ),
            _rung(
                "medium",
                cells=3_000_000,
                cl=1.18,
                cd=0.035,
                cm=-0.031,
                wall_status="not_wall_resolved_no_bl_route",
                boundary_layer_status="not_used_no_bl_route",
                yplus_status="missing",
                setup_id="baseline_a_current_go_no_bl_rans_sa_alpha5",
            ),
            _rung(
                "fine",
                cells=9_000_000,
                cl=1.17,
                cd=0.0348,
                cm=-0.0315,
                wall_status="not_wall_resolved_no_bl_route",
                boundary_layer_status="not_used_no_bl_route",
                yplus_status="missing",
                setup_id="baseline_a_current_go_no_bl_rans_sa_alpha5",
            ),
        ],
        setup_gate=setup_gate,
    )

    assert setup_gate["status"] == "blocked"
    assert result["goal_status"] == "INCOMPLETE"
    assert result["cfd_status"] == "mesh_ladder_incomplete"
    assert "setup_boundary_layer_mesh_missing" in result["blockers"]
    assert "coarse_wall_resolution_not_pass" in result["blockers"]
    assert result["finite_completed_rung_count"] == 3


def test_setup_gate_rejects_dimensional_nondim_for_aero_coefficients() -> None:
    module = _load_module()
    bad_setup = {
        "physics_setup_id": "baseline_a_current_go_wall_resolved_rans_sa_alpha5",
        "solver": "INC_RANS",
        "turbulence_model": "SA",
        "wall_profile": "adiabatic_no_slip",
        "wall_bc": "MARKER_HEATFLUX",
        "farfield_bc": "MARKER_FAR",
        "boundary_layer": "owned_conformal_bl_core_handoff",
        "near_wall_yplus_status": "pass",
        "conformal_bl_core_handoff_status": "pass",
        "inc_nondim": "DIMENSIONAL",
    }

    result = module.evaluate_cfd_setup_gate(physics_setup=bad_setup)

    assert result["status"] == "blocked"
    assert "coefficient_normalization_not_initial_values" in result["blockers"]


def test_setup_gate_rejects_direct_stageback_plc_failure_artifact() -> None:
    module = _load_module()
    otherwise_ready_setup = {
        "physics_setup_id": "baseline_a_current_go_wall_resolved_rans_sa_alpha5",
        "solver": "INC_RANS",
        "turbulence_model": "SA",
        "wall_profile": "adiabatic_no_slip",
        "wall_bc": "MARKER_HEATFLUX",
        "farfield_bc": "MARKER_FAR",
        "boundary_layer": "owned_conformal_bl_core_handoff",
        "near_wall_yplus_status": "pass",
        "conformal_bl_core_handoff_status": "pass",
        "inc_nondim": "INITIAL_VALUES",
    }

    result = module.evaluate_cfd_setup_gate(
        physics_setup=otherwise_ready_setup,
        direct_stageback_artifacts=[
            {
                "schema_version": "wo006m_narrow_stageback_mesh_probe.v1",
                "status": "failed",
                "error": (
                    "Gmsh stageback BL/core mesh generation failed; diagnostic="
                    '{"diagnostic_family":"stageback_plc_segment_facet_intersection"}'
                ),
            }
        ],
    )

    assert result["status"] == "blocked"
    assert "direct_stageback_topology_plc_segment_facet" in result["blockers"]
    assert result["stageback_topology"]["status"] == "blocked"
    assert result["stageback_topology"]["recommended_repair"] == (
        "receiver_sleeve_staged_transition_required"
    )


def test_setup_gate_consumes_r10_core_closure_artifact_before_solver() -> None:
    module = _load_module()
    otherwise_ready_setup = {
        "physics_setup_id": "baseline_a_current_go_wall_resolved_rans_sa_alpha5",
        "solver": "INC_RANS",
        "turbulence_model": "SA",
        "wall_profile": "adiabatic_no_slip",
        "wall_bc": "MARKER_HEATFLUX",
        "farfield_bc": "MARKER_FAR",
        "boundary_layer": "owned_conformal_bl_core_handoff",
        "near_wall_yplus_status": "pass",
        "conformal_bl_core_handoff_status": "pass",
        "inc_nondim": "INITIAL_VALUES",
    }

    result = module.evaluate_cfd_setup_gate(
        physics_setup=otherwise_ready_setup,
        core_closure_artifacts=[
            {
                "schema_version": "wo006r10_near_wall_core_closure_probe.v1",
                "verdict": "near_wall_core_interface_closure_blocked",
                "core_closure": {
                    "status": "core_interface_closure_blocked",
                    "core_facing_topology": {
                        "status": "not_watertight",
                        "bad_edge_count": 64,
                    },
                    "core_wall_edge_gap_audit": {
                        "status": "blocked_by_physical_wall_edge_dependency",
                        "bad_edge_count": 64,
                        "physical_wall_edge_dependency_count": 64,
                        "unexplained_bad_edge_count": 0,
                    },
                    "full_shell_core_interface_policy": {
                        "status": "forbidden",
                        "physical_roles_present": {
                            "wing_wall": 960,
                            "physical_wall_edge_receiver": 60,
                        },
                    },
                },
            }
        ],
    )

    assert result["status"] == "blocked"
    assert "near_wall_core_interface_closure_blocked" in result["blockers"]
    assert "near_wall_core_wall_edge_gap_dependency" in result["blockers"]
    assert "near_wall_full_shell_physical_wall_misownership" in result["blockers"]
    assert result["core_closure_topology"]["status"] == "blocked"
    assert result["core_closure_topology"]["bad_edge_count"] == 64
    assert result["core_closure_topology"]["unexplained_bad_edge_count"] == 0


def test_setup_gate_consumes_r11_loop_cap_artifact_as_mesh_pending() -> None:
    module = _load_module()
    otherwise_ready_setup = {
        "physics_setup_id": "baseline_a_current_go_wall_resolved_rans_sa_alpha5",
        "solver": "INC_RANS",
        "turbulence_model": "SA",
        "wall_profile": "adiabatic_no_slip",
        "wall_bc": "MARKER_HEATFLUX",
        "farfield_bc": "MARKER_FAR",
        "boundary_layer": "owned_conformal_bl_core_handoff",
        "near_wall_yplus_status": "pass",
        "conformal_bl_core_handoff_status": "pass",
        "inc_nondim": "INITIAL_VALUES",
    }

    result = module.evaluate_cfd_setup_gate(
        physics_setup=otherwise_ready_setup,
        core_closure_artifacts=[
            {
                "schema_version": "wo006r11_core_facing_loop_closure_probe.v1",
                "verdict": "core_facing_loop_cap_surface_ready_not_handoff",
                "loop_closure": {
                    "status": "core_facing_loop_cap_surface_ready_core_mesh_pending",
                    "can_generate_core_mesh_probe": True,
                    "pre_cap_topology": {
                        "status": "not_watertight",
                        "bad_edge_count": 64,
                    },
                    "post_cap_topology": {
                        "status": "watertight",
                        "bad_edge_count": 0,
                    },
                    "blockers": [
                        "core_farfield_mesh_not_generated",
                        "merged_mesh_quality_not_run",
                    ],
                },
            }
        ],
    )

    assert result["status"] == "blocked"
    assert "near_wall_core_interface_closure_blocked" not in result["blockers"]
    assert "near_wall_core_wall_edge_gap_dependency" not in result["blockers"]
    assert "near_wall_core_mesh_probe_missing" in result["blockers"]
    assert result["core_closure_topology"]["status"] == "surface_ready_core_mesh_pending"
    assert result["core_closure_topology"]["post_cap_status"] == "watertight"


def test_setup_gate_consumes_r12_core_mesh_artifact_as_handoff_pending() -> None:
    module = _load_module()
    otherwise_ready_setup = {
        "physics_setup_id": "baseline_a_current_go_wall_resolved_rans_sa_alpha5",
        "solver": "INC_RANS",
        "turbulence_model": "SA",
        "wall_profile": "adiabatic_no_slip",
        "wall_bc": "MARKER_HEATFLUX",
        "farfield_bc": "MARKER_FAR",
        "boundary_layer": "owned_conformal_bl_core_handoff",
        "near_wall_yplus_status": "pass",
        "conformal_bl_core_handoff_status": "pass",
        "inc_nondim": "INITIAL_VALUES",
    }

    result = module.evaluate_cfd_setup_gate(
        physics_setup=otherwise_ready_setup,
        core_closure_artifacts=[
            {
                "schema_version": "wo006r12_loop_cap_core_mesh_probe.v1",
                "verdict": "loop_cap_core_mesh_probe_pass_not_handoff",
                "loop_cap_core_mesh": {
                    "status": "core_mesh_probe_pass_merged_handoff_pending",
                    "loop_cap_status": "watertight",
                    "core_mesh_quality_status": "pass",
                    "core_mesh_marker_status": "pass",
                    "node_count": 1234,
                    "volume_element_count": 4567,
                    "blockers": [
                        "merged_mixed_bl_core_su2_mesh_missing",
                        "near_wall_yplus_not_postprocessed",
                        "solver_ladder_not_run",
                    ],
                },
            }
        ],
    )

    assert result["status"] == "blocked"
    assert "near_wall_core_mesh_probe_missing" not in result["blockers"]
    assert "near_wall_core_interface_closure_blocked" not in result["blockers"]
    assert "near_wall_merged_mesh_handoff_missing" in result["blockers"]
    assert result["core_closure_topology"]["status"] == "core_mesh_ready_handoff_pending"
    assert result["core_closure_topology"]["volume_element_count"] == 4567


def test_setup_gate_r12_blocker_supersedes_older_r10_wall_edge_blockers() -> None:
    module = _load_module()
    otherwise_ready_setup = {
        "physics_setup_id": "baseline_a_current_go_wall_resolved_rans_sa_alpha5",
        "solver": "INC_RANS",
        "turbulence_model": "SA",
        "wall_profile": "adiabatic_no_slip",
        "wall_bc": "MARKER_HEATFLUX",
        "farfield_bc": "MARKER_FAR",
        "boundary_layer": "owned_conformal_bl_core_handoff",
        "near_wall_yplus_status": "pass",
        "conformal_bl_core_handoff_status": "pass",
        "inc_nondim": "INITIAL_VALUES",
    }

    result = module.evaluate_cfd_setup_gate(
        physics_setup=otherwise_ready_setup,
        core_closure_artifacts=[
            {
                "schema_version": "wo006r12_loop_cap_core_mesh_probe.v1",
                "verdict": "loop_cap_core_mesh_probe_blocked",
                "loop_cap_core_mesh": {
                    "status": "core_mesh_probe_blocked",
                    "hard_blockers": [
                        "core_inner_surface_geometric_duplicate_nonmanifold"
                    ],
                    "volume_element_count": None,
                    "blockers": [
                        "core_inner_surface_geometric_duplicate_nonmanifold",
                    ],
                },
            },
            {
                "schema_version": "wo006r10_near_wall_core_closure_probe.v1",
                "core_closure": {
                    "status": "core_closure_blocked",
                    "core_facing_topology": {
                        "status": "not_watertight",
                        "bad_edge_count": 64,
                    },
                    "core_wall_edge_gap_audit": {
                        "status": "blocked_by_physical_wall_edge_dependency",
                        "unexplained_bad_edge_count": 0,
                        "physical_wall_edge_dependency_count": 64,
                    },
                    "full_shell_core_interface_policy": {"status": "forbidden"},
                },
            },
        ],
    )

    assert result["status"] == "blocked"
    assert "near_wall_core_mesh_geometry_blocked" in result["blockers"]
    assert "near_wall_core_wall_edge_gap_dependency" not in result["blockers"]
    assert "near_wall_full_shell_physical_wall_misownership" not in result["blockers"]
    assert result["core_closure_topology"]["blocker"] == "near_wall_core_mesh_geometry_blocked"


def test_setup_gate_newest_core_mesh_artifact_wins_over_older_r12_blocker() -> None:
    module = _load_module()
    otherwise_ready_setup = {
        "physics_setup_id": "baseline_a_current_go_wall_resolved_rans_sa_alpha5",
        "solver": "INC_RANS",
        "turbulence_model": "SA",
        "wall_profile": "adiabatic_no_slip",
        "wall_bc": "MARKER_HEATFLUX",
        "farfield_bc": "MARKER_FAR",
        "boundary_layer": "owned_conformal_bl_core_handoff",
        "near_wall_yplus_status": "pass",
        "conformal_bl_core_handoff_status": "pass",
        "inc_nondim": "INITIAL_VALUES",
    }

    result = module.evaluate_cfd_setup_gate(
        physics_setup=otherwise_ready_setup,
        core_closure_artifacts=[
            {
                "schema_version": "wo006r13_loop_cap_geometric_seam_repair_probe.v1",
                "verdict": "loop_cap_geometric_seam_repair_core_mesh_pass_not_handoff",
                "loop_cap_core_mesh": {
                    "status": "core_mesh_probe_pass_merged_handoff_pending",
                    "hard_blockers": [],
                    "volume_element_count": 9677,
                    "blockers": ["merged_mixed_bl_core_su2_mesh_missing"],
                },
            },
            {
                "schema_version": "wo006r12_loop_cap_core_mesh_probe.v1",
                "verdict": "loop_cap_core_mesh_probe_blocked",
                "loop_cap_core_mesh": {
                    "status": "core_mesh_probe_blocked",
                    "hard_blockers": [
                        "core_inner_surface_geometric_duplicate_nonmanifold"
                    ],
                    "volume_element_count": None,
                    "blockers": [
                        "core_inner_surface_geometric_duplicate_nonmanifold",
                    ],
                },
            },
        ],
    )

    assert result["status"] == "blocked"
    assert "near_wall_merged_mesh_handoff_missing" in result["blockers"]
    assert "near_wall_core_mesh_geometry_blocked" not in result["blockers"]
    assert result["core_closure_topology"]["status"] == "core_mesh_ready_handoff_pending"
    assert result["core_closure_topology"]["volume_element_count"] == 9677


def test_history_stability_uses_100_iteration_force_window(tmp_path: Path) -> None:
    module = _load_module()
    history_path = tmp_path / "history.csv"
    rows = ["Inner_Iter,CL,CD,CMy,RMS[P]\n"]
    for index in range(120):
        cl = 1.0
        cd = 0.035
        if index == 20:
            cl = 1.02
            cd = 0.0357
        rows.append(f"{index},{cl},{cd},-0.030,-2.0\n")
    history_path.write_text("".join(rows), encoding="utf-8")

    result = module.summarize_history_stability(history_path)

    assert result["force_stability"]["window_rows"] == 100
    assert result["force_stability"]["status"] == "fail"
    assert result["force_stability"]["max_relative_spread"] > 0.01
    assert "cl_window_spread_high" in result["force_stability"]["reasons"]


def test_run_campaign_blocks_no_bl_route_before_solver_by_default(tmp_path: Path) -> None:
    module = _load_module()

    summary = module.run_campaign(
        output_dir=tmp_path / "blocked_campaign",
        rung_specs=(module.RungSpec("medium", 0.08, 3_000_000, "medium"),),
    )

    assert summary["setup_gate"]["status"] == "blocked"
    assert summary["preflight_decision"]["status"] == "blocked_before_solver"
    assert summary["rungs"] == []
    assert summary["grid_convergence_gate"]["goal_status"] == "INCOMPLETE"
    assert summary["grid_convergence_gate"]["cfd_status"] == "mesh_ladder_incomplete"
    assert (tmp_path / "blocked_campaign" / "grid_convergence_report.md").exists()
