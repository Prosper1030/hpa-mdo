from __future__ import annotations

import pytest

from hpa_mdo.concept.frontier import build_frontier_summary


def _record(
    concept_id: str,
    *,
    overall_rank: int,
    wing_loading_target_Npm2: float,
    wing_area_m2: float,
    aspect_ratio: float,
    span_m: float,
    launch_feasible: bool,
    turn_feasible: bool,
    trim_feasible: bool,
    local_stall_feasible: bool,
    mission_feasible: bool,
    combined_feasibility_margin: float,
    mission_margin_m: float,
    local_stall_required_area_m2: float,
    local_stall_delta_area_m2: float,
    limiter: str,
) -> dict[str, object]:
    return {
        "concept_id": concept_id,
        "overall_rank": overall_rank,
        "span_m": span_m,
        "wing_loading_target_Npm2": wing_loading_target_Npm2,
        "wing_area_m2": wing_area_m2,
        "aspect_ratio": aspect_ratio,
        "launch": {
            "feasible": launch_feasible,
            "status": "ok" if launch_feasible else "launch_cl_insufficient",
            "stall_utilization": 0.70 if launch_feasible else 1.15,
        },
        "turn": {
            "feasible": turn_feasible,
            "status": "ok" if turn_feasible else "stall_utilization_exceeded",
        },
        "trim": {
            "feasible": trim_feasible,
            "status": "ok" if trim_feasible else "trim_margin_insufficient",
        },
        "local_stall": {
            "feasible": local_stall_feasible,
            "status": "ok" if local_stall_feasible else "stall_utilization_exceeded",
            "required_wing_area_for_limit_m2": local_stall_required_area_m2,
            "delta_wing_area_for_limit_m2": local_stall_delta_area_m2,
            "stall_utilization": 0.75 if local_stall_feasible else 1.08,
        },
        "mission": {
            "mission_feasible": mission_feasible,
            "status": "ok" if mission_feasible else "no_feasible_speed_samples",
            "target_range_margin_m": mission_margin_m,
            "best_range_m": max(0.0, 42195.0 + mission_margin_m),
            "limiter_audit": {
                "dominant_limiter": limiter,
            },
        },
        "ranking": {
            "fully_feasible": all(
                [
                    launch_feasible,
                    turn_feasible,
                    trim_feasible,
                    local_stall_feasible,
                    mission_feasible,
                ]
            ),
            "safety_feasible": all(
                [
                    launch_feasible,
                    turn_feasible,
                    trim_feasible,
                    local_stall_feasible,
                ]
            ),
            "combined_feasibility_margin": combined_feasibility_margin,
            "mission_margin_m": mission_margin_m,
        },
    }


def test_build_frontier_summary_tracks_failure_modes_and_geometry_trends():
    records = [
        _record(
            "concept-01",
            overall_rank=1,
            wing_loading_target_Npm2=21.2,
            wing_area_m2=48.5,
            aspect_ratio=24.8,
            span_m=34.7,
            launch_feasible=False,
            turn_feasible=False,
            trim_feasible=True,
            local_stall_feasible=False,
            mission_feasible=False,
            combined_feasibility_margin=-41.0,
            mission_margin_m=-18000.0,
            local_stall_required_area_m2=52.0,
            local_stall_delta_area_m2=3.5,
            limiter="stall_operating_point_unavailable",
        ),
        _record(
            "concept-02",
            overall_rank=2,
            wing_loading_target_Npm2=22.4,
            wing_area_m2=46.0,
            aspect_ratio=25.9,
            span_m=34.5,
            launch_feasible=False,
            turn_feasible=True,
            trim_feasible=True,
            local_stall_feasible=False,
            mission_feasible=False,
            combined_feasibility_margin=-28.0,
            mission_margin_m=-9000.0,
            local_stall_required_area_m2=49.0,
            local_stall_delta_area_m2=3.0,
            limiter="stall_operating_point_unavailable",
        ),
        _record(
            "concept-03",
            overall_rank=3,
            wing_loading_target_Npm2=24.5,
            wing_area_m2=42.1,
            aspect_ratio=27.4,
            span_m=34.0,
            launch_feasible=True,
            turn_feasible=True,
            trim_feasible=True,
            local_stall_feasible=True,
            mission_feasible=False,
            combined_feasibility_margin=-6.0,
            mission_margin_m=-2500.0,
            local_stall_required_area_m2=42.1,
            local_stall_delta_area_m2=0.0,
            limiter="pilot_power_limit",
        ),
        _record(
            "concept-04",
            overall_rank=4,
            wing_loading_target_Npm2=25.1,
            wing_area_m2=41.0,
            aspect_ratio=28.2,
            span_m=34.0,
            launch_feasible=True,
            turn_feasible=True,
            trim_feasible=True,
            local_stall_feasible=True,
            mission_feasible=True,
            combined_feasibility_margin=0.8,
            mission_margin_m=1500.0,
            local_stall_required_area_m2=40.2,
            local_stall_delta_area_m2=-0.8,
            limiter="power_available",
        ),
    ]

    summary = build_frontier_summary(records, top_n=3)

    assert summary["counts"]["evaluated_count"] == 4
    assert summary["counts"]["fully_feasible_count"] == 1
    assert summary["counts"]["safety_feasible_count"] == 2
    assert summary["counts"]["mission_feasible_count"] == 1
    assert summary["failure_gate_counts"]["overall"]["launch"] == 2
    assert summary["failure_gate_counts"]["overall"]["local_stall"] == 2
    assert summary["failure_gate_counts"]["top_ranked"]["mission"] == 3
    top_ranked_signatures = {
        item["signature"] for item in summary["dominant_failure_signatures"]["top_ranked"]
    }
    assert "launch+turn+local_stall+mission" in top_ranked_signatures
    assert "launch+local_stall+mission" in top_ranked_signatures
    assert summary["mission_dominant_limiters"]["top_ranked"][0]["limiter"] == (
        "stall_operating_point_unavailable"
    )
    assert summary["geometry_subsets"]["top_ranked"]["wing_loading_target_Npm2"]["min"] == pytest.approx(21.2)
    assert summary["geometry_subsets"]["top_ranked"]["wing_loading_target_Npm2"]["max"] == pytest.approx(24.5)
    assert summary["geometry_subsets"]["top_ranked"]["wing_area_m2"]["max"] == pytest.approx(48.5)
    assert summary["margin_subsets"]["top_ranked"]["required_wing_area_for_local_stall_limit_m2"]["max"] == pytest.approx(
        52.0
    )
    assert summary["margin_subsets"]["top_ranked"]["delta_wing_area_for_local_stall_limit_m2"]["median"] == pytest.approx(
        3.0
    )
