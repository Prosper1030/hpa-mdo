from __future__ import annotations

from hpa_mdo.aero.aero_sweep import AeroSweepPoint
from hpa_mdo.aero.origin_quality_gate import assess_origin_mesh_study


def _points(
    *,
    solver: str,
    alpha_deg: float,
    cl: float,
    cd: float,
    cm: float,
) -> AeroSweepPoint:
    return AeroSweepPoint(
        solver=solver,
        alpha_deg=alpha_deg,
        cl=cl,
        cd=cd,
        cm=cm,
        lift_n=None,
        drag_n=None,
        source_path=f"/tmp/{solver}_{alpha_deg:+.1f}.csv",
    )


def test_assess_origin_mesh_study_marks_tight_spreads_usable_for_comparison() -> None:
    assessment = assess_origin_mesh_study(
        points_by_preset={
            "study_coarse": [_points(solver="su2", alpha_deg=0.0, cl=1.00, cd=0.0310, cm=-0.021)],
            "study_medium": [_points(solver="su2", alpha_deg=0.0, cl=1.01, cd=0.0318, cm=-0.019)],
            "study_fine": [_points(solver="su2", alpha_deg=0.0, cl=1.02, cd=0.0326, cm=-0.018)],
        }
    )

    assert assessment["verdict"] == "usable_for_comparison"
    assert assessment["preset_count"] == 3
    assert assessment["cd_spread_abs"] < 0.002
    assert assessment["cl_spread_abs"] < 0.03
    assert assessment["cm_spread_abs"] < 0.03


def test_assess_origin_mesh_study_marks_large_spreads_baseline_only() -> None:
    assessment = assess_origin_mesh_study(
        points_by_preset={
            "study_coarse": [_points(solver="su2", alpha_deg=0.0, cl=0.94, cd=0.0290, cm=-0.040)],
            "study_medium": [_points(solver="su2", alpha_deg=0.0, cl=1.00, cd=0.0325, cm=-0.010)],
            "study_fine": [_points(solver="su2", alpha_deg=0.0, cl=1.05, cd=0.0355, cm=0.004)],
        }
    )

    assert assessment["verdict"] == "still_baseline_only"
    assert assessment["preset_count"] == 3
    assert assessment["cd_spread_abs"] > 0.002
    assert assessment["cl_spread_abs"] > 0.03
    assert assessment["cm_spread_abs"] > 0.03


def test_assess_origin_mesh_study_does_not_mark_partial_alpha_coverage_usable() -> None:
    assessment = assess_origin_mesh_study(
        points_by_preset={
            "study_coarse": [
                _points(solver="su2", alpha_deg=0.0, cl=1.00, cd=0.0310, cm=-0.021),
                _points(solver="su2", alpha_deg=2.0, cl=1.18, cd=0.0340, cm=-0.018),
            ],
            "study_medium": [
                _points(solver="su2", alpha_deg=0.0, cl=1.01, cd=0.0317, cm=-0.020),
            ],
            "study_fine": [
                _points(solver="su2", alpha_deg=0.0, cl=1.02, cd=0.0324, cm=-0.019),
                _points(solver="su2", alpha_deg=2.0, cl=1.20, cd=0.0350, cm=-0.017),
            ],
        }
    )

    assert assessment["compared_alpha_deg"] == [0.0]
    assert assessment["verdict"] == "still_baseline_only"


def test_assess_origin_mesh_study_marks_no_common_alpha_coverage_baseline_only() -> None:
    assessment = assess_origin_mesh_study(
        points_by_preset={
            "study_coarse": [_points(solver="su2", alpha_deg=-2.0, cl=0.84, cd=0.0300, cm=-0.022)],
            "study_medium": [_points(solver="su2", alpha_deg=0.0, cl=1.01, cd=0.0317, cm=-0.020)],
            "study_fine": [_points(solver="su2", alpha_deg=2.0, cl=1.20, cd=0.0350, cm=-0.017)],
        }
    )

    assert assessment["compared_alpha_deg"] == []
    assert assessment["verdict"] == "still_baseline_only"
