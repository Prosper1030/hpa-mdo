from __future__ import annotations

import pytest

from scripts.audit_seedless_selection_behavior import (
    classify_artifact_suspicion,
    build_reference_zone_requirements,
    historical_airfoil_names_for_zone,
)


def test_reference_zone_requirements_cover_phase4_zones() -> None:
    requirements = build_reference_zone_requirements()

    assert tuple(requirements) == ("root", "mid1", "mid2", "tip")
    assert requirements["root"]["min_tc_ratio"] == pytest.approx(0.14)
    assert requirements["mid1"]["min_tc_ratio"] == pytest.approx(0.10)
    assert requirements["mid2"]["min_tc_ratio"] == pytest.approx(0.10)
    assert requirements["tip"]["min_tc_ratio"] == pytest.approx(0.10)
    assert all(requirements[zone]["points"] for zone in requirements)


def test_historical_airfoil_zone_mapping_matches_phase4_scope() -> None:
    assert historical_airfoil_names_for_zone("root") == (
        "FX 76-MP-140",
        "DAE11",
        "DAE21",
    )
    assert historical_airfoil_names_for_zone("mid1") == (
        "FX 76-MP-140",
        "DAE11",
        "DAE21",
    )
    assert historical_airfoil_names_for_zone("mid2") == ("DAE21", "DAE31", "DAE41")
    assert historical_airfoil_names_for_zone("tip") == ("DAE21", "DAE31", "DAE41")


def test_artifact_suspicion_flags_failed_and_rough_sensitive_candidate() -> None:
    suspicion = classify_artifact_suspicion(
        status="ok",
        robust_pass_rate=1.0,
        mean_cd=0.009,
        mean_cm=-0.04,
        raw_condition_results=[
            {"status": "ok", "roughness_mode": "clean", "mean_cd": 0.007},
            {"status": "ok", "roughness_mode": "rough", "mean_cd": 0.012},
        ],
        max_camber_ratio=0.04,
        thickness_at_1pct_chord=0.018,
        max_cl_target_error=0.01,
    )

    assert suspicion.level == "medium"
    assert any("rough drag sensitivity" in reason for reason in suspicion.reasons)

    failed = classify_artifact_suspicion(
        status="analysis_failed",
        robust_pass_rate=0.0,
        mean_cd=float("inf"),
        mean_cm=0.0,
        raw_condition_results=[],
        max_camber_ratio=0.03,
        thickness_at_1pct_chord=0.02,
        max_cl_target_error=0.0,
    )

    assert failed.level == "high"
    assert any("analysis_failed" in reason for reason in failed.reasons)
