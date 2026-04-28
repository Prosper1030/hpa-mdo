import math

import pytest

from hpa_mdo.concept.airfoil_selection import score_zone_candidate
from hpa_mdo.concept.config import AirfoilSelectionScoreConfig


def _zone_points(*, cl_target: float = 0.85, weight: float = 1.0) -> list[dict[str, float]]:
    return [
        {
            "station_y_m": 4.0,
            "cl_target": cl_target,
            "cm_target": -0.10,
            "cm_effective": -0.10,
            "chord_m": 1.0,
            "weight": weight,
            "reynolds": 350000.0,
            "case_label": "reference_avl_case",
            "span_fraction": 0.30,
            "taper_ratio": 0.35,
            "washout_deg": 0.5,
        }
    ]


def test_score_zone_candidate_default_path_matches_legacy_inline_constants():
    """When score_cfg=None, behaviour must match the pre-segment-H formula."""
    legacy = score_zone_candidate(
        zone_points=_zone_points(),
        mean_cd=0.012,
        mean_cm=-0.10,
        usable_clmax=1.20,
        zone_min_tc_ratio=0.14,
        score_cfg=None,
    )
    explicit = score_zone_candidate(
        zone_points=_zone_points(),
        mean_cd=0.012,
        mean_cm=-0.10,
        usable_clmax=1.20,
        zone_min_tc_ratio=0.14,
        score_cfg=AirfoilSelectionScoreConfig(),
    )
    assert legacy == pytest.approx(explicit, rel=1e-12)


def test_score_zone_candidate_drag_weight_increases_score_when_higher():
    cd_high = score_zone_candidate(
        zone_points=_zone_points(),
        mean_cd=0.020,
        mean_cm=-0.10,
        usable_clmax=1.20,
        zone_min_tc_ratio=0.14,
    )
    cd_low = score_zone_candidate(
        zone_points=_zone_points(),
        mean_cd=0.005,
        mean_cm=-0.10,
        usable_clmax=1.20,
        zone_min_tc_ratio=0.14,
    )
    assert cd_high > cd_low


def test_score_zone_candidate_stall_violation_adds_infeasibility_guard():
    margin_ok_score = score_zone_candidate(
        zone_points=_zone_points(cl_target=0.50),
        mean_cd=0.012,
        mean_cm=-0.10,
        usable_clmax=1.40,
        zone_min_tc_ratio=0.14,
    )
    margin_violated_score = score_zone_candidate(
        zone_points=_zone_points(cl_target=1.50),
        mean_cd=0.012,
        mean_cm=-0.10,
        usable_clmax=1.40,
        zone_min_tc_ratio=0.14,
    )
    assert margin_violated_score >= margin_ok_score + 1.0  # at least the 1.4 base bump


def test_score_zone_candidate_enforce_stall_hard_reject_returns_inf():
    cfg = AirfoilSelectionScoreConfig(enforce_stall_as_hard_reject=True)
    score = score_zone_candidate(
        zone_points=_zone_points(cl_target=1.50),
        mean_cd=0.012,
        mean_cm=-0.10,
        usable_clmax=1.40,
        zone_min_tc_ratio=0.14,
        score_cfg=cfg,
    )
    assert math.isinf(score)


def test_score_zone_candidate_overridden_drag_weight_changes_scoring():
    base_cfg = AirfoilSelectionScoreConfig()
    drag_emphasised_cfg = AirfoilSelectionScoreConfig(drag_weight=10.0)
    base = score_zone_candidate(
        zone_points=_zone_points(),
        mean_cd=0.020,
        mean_cm=-0.10,
        usable_clmax=1.20,
        zone_min_tc_ratio=0.14,
        score_cfg=base_cfg,
    )
    emphasised = score_zone_candidate(
        zone_points=_zone_points(),
        mean_cd=0.020,
        mean_cm=-0.10,
        usable_clmax=1.20,
        zone_min_tc_ratio=0.14,
        score_cfg=drag_emphasised_cfg,
    )
    assert emphasised > base


def test_airfoil_selection_score_config_validates_non_negative_weights():
    with pytest.raises(ValueError):
        AirfoilSelectionScoreConfig(drag_weight=-1.0)
