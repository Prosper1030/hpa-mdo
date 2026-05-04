"""Pure unit tests for the Birdman MIT-like closed-loop search helpers.

Full AVL-driven closed-loop runs require the AVL binary and live in the
output/ directory; the tests in this file exercise the parts that do
not depend on AVL (summary helpers, mission-power proxy).
"""

from __future__ import annotations

import math
from pathlib import Path

from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.mit_like_candidate import (
    generate_mit_like_candidates,
)

import scripts.birdman_mit_like_closed_loop_search as runner


CONFIG_PATH = Path("configs/birdman_upstream_concept_baseline.yaml")


def test_summarise_zone_avl_picks_cruise_case_closest_to_design_speed() -> None:
    payload = {
        "root": {
            "design_cases": [
                {
                    "case_label": "reference_avl_case",
                    "evaluation_speed_mps": 9.5,
                    "load_factor": 1.0,
                    "trim_aoa_deg": -3.0,
                    "trim_cl": 0.6,
                    "trim_cd_induced": 0.009,
                },
                {
                    "case_label": "slow_avl_case",
                    "evaluation_speed_mps": 6.0,
                    "load_factor": 1.0,
                    "trim_aoa_deg": 5.0,
                    "trim_cl": 1.5,
                    "trim_cd_induced": 0.025,
                },
                {
                    "case_label": "turn_avl_case",
                    "evaluation_speed_mps": 8.0,
                    "load_factor": 1.04,
                    "trim_aoa_deg": -1.0,
                    "trim_cl": 0.95,
                    "trim_cd_induced": 0.012,
                },
            ],
            "points": [],
        },
    }
    summary = runner._summarise_zone_avl(zone_payload=payload, cruise_speed_mps=6.6)
    assert summary["cruise_case_label"] == "slow_avl_case"
    assert math.isclose(float(summary["representative_trim_cl"]), 1.5)


def test_summarise_zone_avl_skips_high_load_factor_for_cruise() -> None:
    payload = {
        "root": {
            "design_cases": [
                {
                    "case_label": "turn_avl_case",
                    "evaluation_speed_mps": 6.5,
                    "load_factor": 1.20,
                    "trim_aoa_deg": 5.0,
                    "trim_cl": 1.4,
                    "trim_cd_induced": 0.03,
                },
                {
                    "case_label": "reference_avl_case",
                    "evaluation_speed_mps": 8.0,
                    "load_factor": 1.0,
                    "trim_aoa_deg": -1.0,
                    "trim_cl": 0.85,
                    "trim_cd_induced": 0.011,
                },
            ],
            "points": [],
        },
    }
    summary = runner._summarise_zone_avl(zone_payload=payload, cruise_speed_mps=6.6)
    # turn_avl_case is closer in speed but has a non-1g load factor; the
    # picker should fall back to the 1g reference case.
    assert summary["cruise_case_label"] == "reference_avl_case"


def test_outer_ratio_metrics_handles_zero_baseline() -> None:
    with_payload = {
        "root": {
            "points": [
                {"cl_target": 0.5, "station_y_m": 0.0},
                {"cl_target": 0.6, "station_y_m": 5.0},
            ]
        }
    }
    no_payload = {
        "root": {
            "points": [
                {"cl_target": 0.5, "station_y_m": 0.0},
                {"cl_target": 0.0, "station_y_m": 5.0},
            ]
        }
    }
    metrics = runner._outer_ratio_metrics(
        zone_payload=with_payload, target_zone_payload=no_payload
    )
    ratios = [sample["ratio"] for sample in metrics["samples"]]
    assert ratios[0] == 1.0
    assert ratios[1] is None  # divide-by-zero guarded
    assert metrics["ratio_mean"] == 1.0


def test_mission_power_proxy_computes_cl_from_weight() -> None:
    cfg = load_concept_config(CONFIG_PATH)
    candidate = generate_mit_like_candidates(
        cfg=cfg, sample_count=4, seed=20260601
    )[0]
    power = runner._mission_power_proxy(
        cfg=cfg,
        candidate=candidate,
        e_cdi=0.85,
        cd_profile=0.012,
        design_speed_mps=6.6,
    )
    assert power["cl_cruise"] > 1.0
    assert power["cd_induced_cruise"] is not None and power["cd_induced_cruise"] > 0.0
    assert power["cd_total"] > power["cd_induced_cruise"]
    assert power["power_required_w"] > 0.0


def test_mission_power_proxy_propagates_zero_e() -> None:
    cfg = load_concept_config(CONFIG_PATH)
    candidate = generate_mit_like_candidates(
        cfg=cfg, sample_count=4, seed=20260601
    )[0]
    power = runner._mission_power_proxy(
        cfg=cfg,
        candidate=candidate,
        e_cdi=0.0,
        cd_profile=0.012,
        design_speed_mps=6.6,
    )
    assert power["cd_induced_cruise"] is None
    assert power["cd_total"] is None
    assert power["power_required_w"] is None


def test_no_airfoil_e_cdi_back_calculation_uses_aspect_ratio() -> None:
    record = {
        "candidate": {"aspect_ratio": 38.0},
        "no_airfoil_avl": {
            "representative_trim_cl": 1.5,
            "representative_trim_cd_induced": 0.025,
        },
    }
    e = runner._no_airfoil_e_cdi(record)
    assert e is not None
    assert math.isclose(e, 1.5**2 / (math.pi * 38.0 * 0.025), rel_tol=1.0e-12)
