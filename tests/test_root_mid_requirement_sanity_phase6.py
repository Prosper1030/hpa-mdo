from __future__ import annotations

import pytest

from scripts.audit_seedless_selection_behavior import build_reference_zone_requirements
from scripts.audit_root_mid_requirement_sanity_phase6 import (
    count_stall_passes_by_zone,
    scale_zone_points_for_speed_weight,
    summarize_design_points,
)


def test_phase6_design_point_summary_preserves_root_mid_targets() -> None:
    summary = summarize_design_points(build_reference_zone_requirements())
    by_zone = {row["zone"]: row for row in summary}

    assert by_zone["root"]["cl_min"] == pytest.approx(1.155754)
    assert by_zone["root"]["cl_max"] == pytest.approx(1.369815)
    assert by_zone["mid1"]["cl_max"] == pytest.approx(1.465726)
    assert by_zone["mid1"]["cl_mean"] > by_zone["root"]["cl_mean"]
    assert by_zone["tip"]["cl_max"] < by_zone["root"]["cl_min"]


def test_phase6_speed_weight_scaling_uses_w_over_v_squared() -> None:
    points = (
        {
            "reynolds": 400000.0,
            "chord_m": 1.0,
            "cl_target": 1.2,
            "weight": 1.0,
        },
    )

    faster = scale_zone_points_for_speed_weight(points, speed_factor=1.10, weight_factor=1.0)
    heavier = scale_zone_points_for_speed_weight(points, speed_factor=1.0, weight_factor=1.05)
    combined = scale_zone_points_for_speed_weight(points, speed_factor=1.05, weight_factor=0.95)

    assert faster[0]["cl_target"] == pytest.approx(1.2 / (1.10**2))
    assert faster[0]["reynolds"] == pytest.approx(440000.0)
    assert heavier[0]["cl_target"] == pytest.approx(1.2 * 1.05)
    assert combined[0]["cl_target"] == pytest.approx(1.2 * 0.95 / (1.05**2))


def test_phase6_stall_pass_count_groups_all_zone_points() -> None:
    rows = (
        {"zone": "root", "airfoil": "A", "utilization": 0.72, "status": "ok"},
        {"zone": "root", "airfoil": "A", "utilization": 0.74, "status": "ok"},
        {"zone": "root", "airfoil": "B", "utilization": 0.72, "status": "ok"},
        {"zone": "root", "airfoil": "B", "utilization": 0.82, "status": "ok"},
        {"zone": "mid1", "airfoil": "A", "utilization": 0.78, "status": "ok"},
        {"zone": "mid1", "airfoil": "B", "utilization": 0.70, "status": "analysis_failed"},
    )

    assert count_stall_passes_by_zone(rows, utilization_limit=0.75) == {
        "root": 1,
        "mid1": 0,
    }
    assert count_stall_passes_by_zone(rows, utilization_limit=0.85) == {
        "root": 2,
        "mid1": 1,
    }
