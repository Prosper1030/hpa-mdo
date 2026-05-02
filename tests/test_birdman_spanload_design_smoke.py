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
        "mission_power_proxy": {"power_required_w": 170.0},
    }
    high_ar = {
        "sample_index": 2,
        "geometry": {"aspect_ratio": 42.0},
        "spanload_gate_health": {"max_local_clmax_utilization": 0.70, "max_outer_clmax_utilization": 0.60},
        "mission_power_proxy": {"power_required_w": 180.0},
    }
    low_power = {
        "sample_index": 3,
        "geometry": {"aspect_ratio": 35.0},
        "spanload_gate_health": {"max_local_clmax_utilization": 0.58, "max_outer_clmax_utilization": 0.50},
        "mission_power_proxy": {"power_required_w": 150.0},
    }

    leaderboards = smoke._select_accepted_leaderboards(
        [low_utilization, high_ar, low_power],
        per_board_count=1,
    )

    assert leaderboards["highest_ar_accepted"][0]["sample_index"] == 2
    assert leaderboards["best_mission_power_proxy_accepted"][0]["sample_index"] == 3
    assert leaderboards["lowest_utilization_accepted"][0]["sample_index"] == 1


def test_inverse_twist_mvp_rewrites_station_twist_from_target_spanload() -> None:
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

    inverse_stations, summary = smoke._build_inverse_twist_stations(
        cfg=cfg,
        concept=concept,
        stations=baseline_stations,
        design_speed_mps=6.8,
    )

    assert summary["model"] == "inverse_twist_mvp_lift_curve"
    assert len(inverse_stations) == len(baseline_stations)
    assert inverse_stations[0].twist_deg == pytest.approx(2.0)
    assert any(
        abs(float(inverse.twist_deg) - float(base.twist_deg)) > 0.5
        for inverse, base in zip(inverse_stations[1:-1], baseline_stations[1:-1], strict=True)
    )
