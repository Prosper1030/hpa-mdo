from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_wo006_hpa_cfd_verification_workflow as module  # noqa: E402


def test_current_openfoam_basis_is_locked_from_recent_successful_route() -> None:
    basis = module.current_openfoam_operating_basis()

    assert basis["basis_id"] == "recent_successful_openfoam_fullwing_mirror"
    assert basis["source_commit"] == "fe73939a"
    assert basis["rho_kg_m3"] == 1.225
    assert basis["velocity_mps"] == 6.5
    assert basis["kinematic_viscosity_m2_s"] == 1.4607e-5
    assert round(basis["dynamic_viscosity_pa_s"], 10) == round(1.225 * 1.4607e-5, 10)
    assert basis["aoa_deg"] == 0.18
    assert basis["sref_m2"] == 33.420059598
    assert basis["cref_m"] == 1.003721543
    assert basis["cl_design_target"] == 1.16853
    assert round(basis["chord_min_m"], 6) == 0.645004
    assert round(basis["chord_max_m"], 6) == 1.256773
    assert round(basis["reynolds_min"]) == 287022
    assert round(basis["reynolds_max"]) == 559254
    assert basis["turbulence_model"] == "SpalartAllmaras"
    assert basis["do_not_revert_to_original_screening_basis"] is True


def test_original_design_estimate_is_kept_as_historical_comparison_not_hard_stop() -> None:
    comparison = module.original_screening_basis_comparison()

    assert comparison["basis_id"] == "historical_avl_tier2_screening_comparison"
    assert comparison["rho_kg_m3"] == 1.18
    assert comparison["velocity_mps"] == 6.6
    assert comparison["role"] == "comparison_only_not_cfd_verification_basis"
    assert comparison["must_not_block_recent_openfoam_route"] is True


def test_refinement_zone_table_covers_hpa_specific_physics() -> None:
    rows = module.local_refinement_zone_rows()
    zone_ids = [row["zone_id"] for row in rows]

    assert zone_ids == [
        "leading_edge",
        "boundary_layer",
        "trailing_edge",
        "near_wake",
        "downstream_wake",
        "wing_tip_vortex_region",
        "farfield",
    ]
    assert rows[1]["growth_rate_target"] == "<=1.20"
    assert rows[5]["why_hpa_specific"].startswith("Tip vortex")
    assert all(row["coarse_to_medium_ratio"] == "4/3 linear" for row in rows)
    assert all(row["medium_to_fine_ratio"] == "5/4 linear" for row in rows)


def test_grid_verdict_preserves_successful_route_but_rejects_grid_independence() -> None:
    verdict = module.build_grid_independence_verdict(
        stable_route={
            "accepted_stable_route_smoke": True,
            "CD_primary": 0.03276165,
            "CL_primary": 1.133291,
            "yplus_mean": 0.5678595352296987,
            "yplus_p95": 1.0904245,
            "yplus_max": 2.65697,
        },
        grid_gate={
            "study_status": "grid_independence_not_demonstrated",
            "blocking_items": [
                "coarse:solver_not_completed",
                "medium:solver_not_completed",
                "fine:checkMesh_not_solver_smoke_acceptable",
            ],
            "max_abs_cd_percent_change": 50.73972140084425,
        },
    )

    assert verdict["latest_route_smoke_success"] is True
    assert verdict["grid_independence_demonstrated"] is False
    assert verdict["can_trust_cd_approx_0p0315"] is False
    assert verdict["can_update_design_power_from_174w"] is False
    assert "fine:checkMesh_not_solver_smoke_acceptable" in verdict["exact_blockers"]


def test_workflow_writes_phase_reports_without_returning_to_old_basis(tmp_path: Path) -> None:
    module.write_hpa_verification_scaffold(
        tmp_path,
        stable_route={
            "accepted_stable_route_smoke": True,
            "CD_primary": 0.03276165,
            "CL_primary": 1.133291,
            "CmPitch": -0.1239779,
            "yplus_mean": 0.5678595352296987,
            "yplus_p95": 1.0904245,
            "yplus_p99": 1.8354890999999969,
            "yplus_max": 2.65697,
            "wall_yplus_by_patch": {
                "airfoil_upper": {
                    "mean": 0.5913392806089747,
                    "p90": 0.9731635000000001,
                    "p95": 1.1975625,
                    "p99": 1.7804425,
                    "max": 2.65697,
                    "count": 14976,
                },
                "airfoil_lower": {
                    "mean": 0.5443797898504277,
                    "p90": 0.673433,
                    "p95": 0.7880510000000001,
                    "p99": 1.90195,
                    "max": 2.25937,
                    "count": 14976,
                },
            },
            "cell_count": 1996800,
            "max_non_ortho": 89.193,
            "max_skew": 3.45663,
            "failed_checks": 2,
            "force_window_stable": True,
        },
        grid_gate={
            "study_status": "grid_independence_not_demonstrated",
            "blocking_items": [
                "coarse:solver_not_completed",
                "medium:solver_not_completed",
                "fine:checkMesh_not_solver_smoke_acceptable",
            ],
            "max_abs_cd_percent_change": 50.73972140084425,
        },
    )

    expected_files = {
        "hpa_operating_condition_lock.md",
        "current_mesh_quality_audit.md",
        "current_mesh_quality_table.csv",
        "hpa_mesh_strategy.md",
        "local_refinement_zone_table.csv",
        "mesh_generator_fix_report.md",
        "final_hpa_grid_independence_verdict.md",
    }
    assert expected_files.issubset({path.name for path in tmp_path.iterdir()})

    lock = (tmp_path / "hpa_operating_condition_lock.md").read_text(encoding="utf-8")
    assert "Verdict: `current_openfoam_basis_locked_for_hpa_verification`" in lock
    assert "Re range along span" in lock
    assert "CL_design target" in lock
    assert "historical comparison only" in lock
    assert "Do not return to" in lock

    audit = (tmp_path / "current_mesh_quality_audit.md").read_text(encoding="utf-8")
    assert "`airfoil_upper` y+ mean" in audit
    assert "`airfoil_lower` y+ mean" in audit

    generator_report = (tmp_path / "mesh_generator_fix_report.md").read_text(encoding="utf-8")
    assert "Verdict: `lower_te_blocker_removed_but_family_gate_not_passed`" in generator_report
    assert "wrong-oriented face pyramids: `0`" in generator_report
    assert "strict checkMesh clean: `False`" in generator_report
    assert "family-level checkMesh gating" in generator_report

    final = (tmp_path / "final_hpa_grid_independence_verdict.md").read_text(encoding="utf-8")
    assert "latest route-smoke is successful" in final
    assert "grid independence is not demonstrated" in final
    assert "Do not update design power" in final
