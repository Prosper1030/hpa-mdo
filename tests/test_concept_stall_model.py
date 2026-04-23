from __future__ import annotations

import pytest

from hpa_mdo.concept import pipeline as concept_pipeline
from hpa_mdo.concept.config import StallModelConfig
from hpa_mdo.concept.stall_model import compute_safe_local_clmax


def test_compute_safe_local_clmax_penalizes_outer_span_more_than_root() -> None:
    root = compute_safe_local_clmax(
        raw_clmax=1.24,
        raw_source="airfoil_observed",
        span_fraction=0.20,
        taper_ratio=0.30,
        washout_deg=4.0,
        safe_scale=0.90,
        safe_delta=0.05,
        tip_3d_penalty_start_eta=0.55,
        tip_3d_penalty_max=0.04,
        tip_taper_penalty_weight=0.35,
        washout_relief_deg=2.0,
        washout_relief_max=0.02,
    )
    tip = compute_safe_local_clmax(
        raw_clmax=1.24,
        raw_source="airfoil_observed",
        span_fraction=0.90,
        taper_ratio=0.30,
        washout_deg=4.0,
        safe_scale=0.90,
        safe_delta=0.05,
        tip_3d_penalty_start_eta=0.55,
        tip_3d_penalty_max=0.04,
        tip_taper_penalty_weight=0.35,
        washout_relief_deg=2.0,
        washout_relief_max=0.02,
    )

    assert root.tip_3d_penalty == pytest.approx(0.0)
    assert tip.tip_3d_penalty > 0.0
    assert tip.washout_relief > 0.0
    assert tip.safe_clmax < root.safe_clmax


def test_compute_safe_local_clmax_treats_geometry_proxy_as_more_conservative() -> None:
    observed = compute_safe_local_clmax(
        raw_clmax=1.18,
        raw_source="airfoil_observed",
        span_fraction=0.45,
        taper_ratio=0.35,
        washout_deg=0.0,
        safe_scale=0.90,
        safe_delta=0.05,
        tip_3d_penalty_start_eta=0.55,
        tip_3d_penalty_max=0.04,
        tip_taper_penalty_weight=0.35,
        washout_relief_deg=2.0,
        washout_relief_max=0.02,
    )
    proxy = compute_safe_local_clmax(
        raw_clmax=1.18,
        raw_source="geometry_proxy",
        span_fraction=0.45,
        taper_ratio=0.35,
        washout_deg=0.0,
        safe_scale=0.90,
        safe_delta=0.05,
        tip_3d_penalty_start_eta=0.55,
        tip_3d_penalty_max=0.04,
        tip_taper_penalty_weight=0.35,
        washout_relief_deg=2.0,
        washout_relief_max=0.02,
    )

    assert proxy.safe_clmax < observed.safe_clmax
    assert proxy.source_scale < observed.source_scale
    assert proxy.source_delta > observed.source_delta


def test_pipeline_safe_clmax_summary_reports_tip_penalty_breakdown() -> None:
    stall_cfg = StallModelConfig()
    safe_points, summary = concept_pipeline._apply_safe_clmax_model(
        [
            {
                "station_y_m": 2.0,
                "span_fraction": 0.125,
                "taper_ratio": 0.30,
                "washout_deg": 4.0,
                "cl_max_effective": 1.24,
                "cl_max_effective_source": "airfoil_observed",
            },
            {
                "station_y_m": 14.0,
                "span_fraction": 0.875,
                "taper_ratio": 0.30,
                "washout_deg": 4.0,
                "cl_max_effective": 1.24,
                "cl_max_effective_source": "airfoil_observed",
            },
        ],
        safe_scale=stall_cfg.safe_clmax_scale,
        safe_delta=stall_cfg.safe_clmax_delta,
        tip_3d_penalty_start_eta=stall_cfg.tip_3d_penalty_start_eta,
        tip_3d_penalty_max=stall_cfg.tip_3d_penalty_max,
        tip_taper_penalty_weight=stall_cfg.tip_taper_penalty_weight,
        washout_relief_deg=stall_cfg.washout_relief_deg,
        washout_relief_max=stall_cfg.washout_relief_max,
    )

    assert summary["safe_clmax_model"] == "safe_clmax_model_v2"
    assert summary["max_tip_3d_penalty"] > 0.0
    assert safe_points[1]["cl_max_safe"] < safe_points[0]["cl_max_safe"]
    assert safe_points[1]["cl_max_safe_tip_3d_penalty"] > 0.0
    assert safe_points[1]["cl_max_safe_source"] == "airfoil_safe_observed"
