from pathlib import Path

import scripts.birdman_mission_coupled_spanload_search as mission_search
from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.geometry import GeometryConcept


def _concept() -> GeometryConcept:
    return GeometryConcept(
        span_m=34.5,
        wing_area_m2=31.0,
        root_chord_m=1.35,
        tip_chord_m=(2.0 * 31.0 / 34.5) - 1.35,
        twist_root_deg=2.0,
        twist_tip_deg=-2.0,
        twist_control_points=((0.0, 2.0), (1.0, -2.0)),
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(4.3125, 4.3125, 4.3125, 4.3125),
        spanload_a3_over_a1=-0.05,
        spanload_a5_over_a1=0.0,
        design_gross_mass_kg=98.5,
    )


def test_mission_speed_sweep_reports_fastest_completion_speed() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))

    sweep = mission_search.mission_speed_sweep(
        cfg=cfg,
        concept=_concept(),
        avl_e_cdi=1.50,
        speed_grid_mps=(6.4, 6.6, 6.8),
    )

    assert sweep["speed_grid_mps"] == [6.4, 6.6, 6.8]
    assert sweep["best_complete_point"]["speed_mps"] == sweep["v_complete_max_mps"]
    assert sweep["t_complete_min_s"] == sweep["best_complete_point"]["duration_s"]
    assert all("power_margin_w" in point for point in sweep["points"])


def test_mission_ranking_prefers_e88_completion_speed_over_diagnostic_e85() -> None:
    records = [
        {
            "sample_index": 1,
            "physical_acceptance": {"physically_acceptable": True},
            "avl_reference_case": {"avl_e_cdi": 0.86},
            "mission_speed_sweep": {"v_complete_max_mps": 7.0, "best_complete_power_margin_w": 8.0},
            "avl_cdi_power_proxy": {"power_required_w": 210.0},
            "mass_authority": {"proxy_budget_warning": False},
        },
        {
            "sample_index": 2,
            "physical_acceptance": {"physically_acceptable": True},
            "avl_reference_case": {"avl_e_cdi": 0.89},
            "mission_speed_sweep": {"v_complete_max_mps": 6.8, "best_complete_power_margin_w": 4.0},
            "avl_cdi_power_proxy": {"power_required_w": 215.0},
            "mass_authority": {"proxy_budget_warning": False},
        },
    ]

    ranked = mission_search.rank_mission_candidates(records)

    assert ranked[0]["sample_index"] == 2
    assert ranked[0]["mission_ranking_tier"] == "e_cdi_ge_0p88_primary"


def test_design_speed_allocation_keeps_stage1_top_k_total_bounded() -> None:
    allocation = mission_search.allocate_stage1_budget(
        design_speeds_mps=(6.0, 6.2, 6.4, 6.6, 6.8, 7.0),
        stage1_top_k=80,
    )

    assert sum(allocation.values()) == 80
    assert set(allocation) == {6.0, 6.2, 6.4, 6.6, 6.8, 7.0}
    assert min(allocation.values()) >= 13


def test_leaderboards_expose_engineering_and_mission_fields() -> None:
    records = [
        {
            "sample_index": 1,
            "status": "physically_acceptable",
            "geometry": {"span_m": 34.0, "wing_area_m2": 31.0, "aspect_ratio": 37.3},
            "physical_acceptance": {"physically_acceptable": True, "failure_reasons": []},
            "avl_reference_case": {"avl_e_cdi": 0.89},
            "mission_speed_sweep": {"v_complete_max_mps": 6.8, "best_complete_power_margin_w": 4.0},
            "avl_cdi_power_proxy": {"power_required_w": 215.0},
            "outer_loading_diagnostics": {"outer_underloaded": False},
            "mass_authority": {"proxy_budget_warning": False},
        },
        {
            "sample_index": 2,
            "status": "physically_acceptable",
            "geometry": {"span_m": 35.0, "wing_area_m2": 30.5, "aspect_ratio": 40.2},
            "physical_acceptance": {"physically_acceptable": True, "failure_reasons": []},
            "avl_reference_case": {"avl_e_cdi": 0.86},
            "mission_speed_sweep": {"v_complete_max_mps": 7.0, "best_complete_power_margin_w": 8.0},
            "avl_cdi_power_proxy": {"power_required_w": 205.0},
            "outer_loading_diagnostics": {"outer_underloaded": True},
            "mass_authority": {"proxy_budget_warning": False},
        },
        {
            "sample_index": 3,
            "status": "rejected",
            "geometry": {"span_m": 35.0, "wing_area_m2": 29.8, "aspect_ratio": 41.1},
            "physical_acceptance": {"physically_acceptable": False, "failure_reasons": ["twist_physical_gates_failed"]},
            "avl_reference_case": {"avl_e_cdi": 0.87},
            "mission_speed_sweep": {"v_complete_max_mps": None},
            "avl_cdi_power_proxy": {"power_required_w": 210.0},
            "outer_loading_diagnostics": {"outer_underloaded": False},
            "twist_gate_metrics": {"twist_gate_failures": ["max_adjacent_twist_jump"]},
        },
        {
            "sample_index": 4,
            "status": "rejected",
            "geometry": {"span_m": 34.8, "wing_area_m2": 29.5, "aspect_ratio": 41.0},
            "physical_acceptance": {"physically_acceptable": False, "failure_reasons": ["local_cl_utilization_failed"]},
            "avl_reference_case": {"avl_e_cdi": 0.84},
            "mission_speed_sweep": {"v_complete_max_mps": None},
            "avl_cdi_power_proxy": {"power_required_w": 208.0},
            "outer_loading_diagnostics": {
                "outer_underloaded": True,
                "e_cdi_loss_diagnosis": {"drivers": ["local_cl_limited", "tip_re_limited"]},
            },
        },
    ]

    leaderboards = mission_search.build_leaderboards(mission_search.rank_mission_candidates(records), count=3)

    assert leaderboards["best_mission_candidate"][0]["sample_index"] == 1
    assert leaderboards["highest_AR_engineering_candidate"][0]["sample_index"] == 2
    assert leaderboards["best_AVL_CDi_power_proxy_candidate"][0]["sample_index"] == 2
    assert leaderboards["closest_rejected_due_to_twist"][0]["sample_index"] == 3
    assert leaderboards["closest_rejected_due_to_tip_local_cl"][0]["sample_index"] == 4
    assert leaderboards["best_mission_candidate"][0]["aspect_ratio"] == 37.3
    assert leaderboards["best_mission_candidate"][0]["v_complete_max_mps"] == 6.8
