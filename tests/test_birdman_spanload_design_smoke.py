from pathlib import Path

import pytest

import scripts.birdman_spanload_design_smoke as smoke
from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.geometry import GeometryConcept, build_linear_wing_stations


def test_fourier_summary_labels_target_not_actual_or_ranking_e() -> None:
    summary = smoke._fourier_efficiency(-0.05, 0.0)

    assert summary["target_fourier_e"] == pytest.approx(1.0 / (1.0 + 3.0 * 0.05**2))
    assert summary["target_fourier_deviation"] == pytest.approx((3.0 * 0.05**2) ** 0.5)
    assert "fourier_e" not in summary
    assert "ranking_e" not in summary


def test_accepted_leaderboards_keep_high_ar_visible() -> None:
    low_utilization = {
        "sample_index": 1,
        "geometry": {"aspect_ratio": 31.0},
        "spanload_gate_health": {"max_local_clmax_utilization": 0.55, "max_outer_clmax_utilization": 0.42},
        "target_fourier_power_proxy": {"power_required_w": 140.0},
        "avl_cdi_power_proxy": {"power_required_w": 170.0, "power_margin_w": 10.0},
    }
    high_ar = {
        "sample_index": 2,
        "geometry": {"aspect_ratio": 42.0},
        "spanload_gate_health": {"max_local_clmax_utilization": 0.70, "max_outer_clmax_utilization": 0.60},
        "target_fourier_power_proxy": {"power_required_w": 130.0},
        "avl_cdi_power_proxy": {"power_required_w": 180.0, "power_margin_w": 1.0},
    }
    low_power = {
        "sample_index": 3,
        "geometry": {"aspect_ratio": 35.0},
        "spanload_gate_health": {"max_local_clmax_utilization": 0.58, "max_outer_clmax_utilization": 0.50},
        "target_fourier_power_proxy": {"power_required_w": 200.0},
        "avl_cdi_power_proxy": {"power_required_w": 150.0, "power_margin_w": 30.0},
    }

    leaderboards = smoke._select_accepted_leaderboards(
        [low_utilization, high_ar, low_power],
        per_board_count=1,
    )

    assert leaderboards["highest_AR_physical_accepted"][0]["sample_index"] == 2
    assert leaderboards["best_avl_cdi_power_proxy_accepted"][0]["sample_index"] == 3
    assert leaderboards["best_power_margin_accepted"][0]["sample_index"] == 3
    assert leaderboards["lowest_utilization_accepted"][0]["sample_index"] == 1


def test_twist_physical_gates_reject_outer_washin_bump() -> None:
    stations = (
        smoke.WingStation(y_m=0.0, chord_m=1.2, twist_deg=2.0, dihedral_deg=0.0),
        smoke.WingStation(y_m=4.0, chord_m=1.0, twist_deg=1.0, dihedral_deg=0.0),
        smoke.WingStation(y_m=10.0, chord_m=0.8, twist_deg=4.6, dihedral_deg=0.0),
        smoke.WingStation(y_m=12.0, chord_m=0.7, twist_deg=3.8, dihedral_deg=0.0),
        smoke.WingStation(y_m=16.0, chord_m=0.5, twist_deg=-2.0, dihedral_deg=0.0),
    )

    metrics = smoke._twist_gate_metrics(stations)

    assert metrics["twist_physical_gates_pass"] is False
    assert metrics["max_outer_washin_bump_deg"] > 2.0
    assert "outer_washin_bump_exceeded" in metrics["twist_gate_failures"]


def test_regularized_twist_initial_guess_stays_within_physical_bounds() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = GeometryConcept(
        span_m=34.0,
        wing_area_m2=32.0,
        root_chord_m=1.34,
        tip_chord_m=0.5423529411764706,
        twist_root_deg=2.0,
        twist_tip_deg=-2.0,
        twist_control_points=((0.0, 2.0), (0.35, 0.5), (0.70, -1.2), (1.0, -2.0)),
        spanload_a3_over_a1=-0.05,
        spanload_a5_over_a1=0.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(2.5, 2.5, 3.0, 3.0, 3.0, 3.0),
        design_gross_mass_kg=98.5,
    )
    baseline_stations = build_linear_wing_stations(concept, stations_per_half=7)

    inverse_stations, summary = smoke._build_regularized_twist_initial_stations(
        cfg=cfg,
        concept=concept,
        stations=baseline_stations,
        design_speed_mps=6.8,
    )

    assert summary["model"] == "regularized_inverse_twist_initial_lift_curve"
    assert len(inverse_stations) == len(baseline_stations)
    assert inverse_stations[0].twist_deg == pytest.approx(2.0)
    metrics = smoke._twist_gate_metrics(inverse_stations)
    assert metrics["twist_range_deg"] <= 7.0
    assert metrics["max_adjacent_twist_jump_deg"] <= 2.0


def test_candidate_physical_status_requires_e_load_twist_and_power() -> None:
    base = {
        "avl_reference_case": {"avl_e_cdi": 0.90},
        "avl_match_metrics": {"max_target_avl_circulation_norm_delta": 0.10, "rms_target_avl_circulation_norm_delta": 0.05},
        "twist_gate_metrics": {"twist_physical_gates_pass": True},
        "spanload_gate_health": {
            "local_margin_to_limit": 0.1,
            "outer_margin_to_limit": 0.1,
        },
        "tip_gate_summary": {"tip_gates_pass": True},
        "avl_cdi_power_proxy": {"power_margin_w": -20.0},
    }
    assert smoke._physical_acceptance_status(base)["status"] == "physically_acceptable"

    bad_twist = {
        **base,
        "twist_gate_metrics": {
            "twist_physical_gates_pass": False,
            "twist_gate_failures": ["twist_range_exceeded"],
        },
    }
    assert smoke._physical_acceptance_status(bad_twist)["status"] == "spanload_matched_but_twist_unphysical"
