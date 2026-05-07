from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "phase9_smooth_geometry_combo_reoptimization.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "phase9_smooth_geometry_combo_reoptimization",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_select_zone_pool_candidates_unions_rank_buckets_and_previous_assignments() -> None:
    module = _load_script_module()
    candidates = [
        {
            "airfoil_id": f"af{i}",
            "balanced_score": float(i),
            "mean_cd": float(20 - i),
            "cd_p90": float(i % 7),
            "actual_query_pass": i in {12, 13, 14, 15, 16, 17},
            "archive_pass": i in {3, 4, 5, 6, 7, 8},
        }
        for i in range(20)
    ]

    pool = module.select_zone_pool_candidates(
        zone_name="root",
        scored_candidates=candidates,
        seed_reference_ids={"fx76mp140"},
        previous_assignment_ids={"raw_keep", "conservative_keep"},
        records_by_id={
            "fx76mp140": {"airfoil_id": "fx76mp140"},
            "raw_keep": {"airfoil_id": "raw_keep"},
            "conservative_keep": {"airfoil_id": "conservative_keep"},
        },
    )

    by_id = {row["airfoil_id"]: row for row in pool}
    assert "af0" in by_id
    assert "af19" in by_id
    assert "af12" in by_id
    assert "af3" in by_id
    assert "fx76mp140" in by_id
    assert "raw_keep" in by_id
    assert "conservative_keep" in by_id
    assert "top10_balanced_score" in by_id["af0"]["pool_reasons"]
    assert "top5_mean_cd" in by_id["af19"]["pool_reasons"]
    assert "top5_actual_query_pass" in by_id["af12"]["pool_reasons"]
    assert "top5_archive_pass" in by_id["af3"]["pool_reasons"]
    assert "previous_raw_or_conservative_best_airfoil" in by_id["raw_keep"]["pool_reasons"]


def test_shortlist_combinations_keeps_known_assignments_inside_cap() -> None:
    module = _load_script_module()
    predicted = [
        {
            "assignment": f"root:r{i}|mid1:m{i}|mid2:o{i}|tip:t{i}",
            "predicted_profile_cd_proxy": float(i),
            "predicted_balanced_score": float(i),
            "predicted_actual_query_pass": i % 2 == 0,
            "predicted_archive_pass": i % 3 == 0,
            "known_policy_tags": "",
        }
        for i in range(10)
    ]
    predicted[-1]["assignment"] = "root:known|mid1:known|mid2:known|tip:known"
    predicted[-1]["known_policy_tags"] = "previous_conservative_best"

    shortlist = module.shortlist_combinations(predicted, max_count=5)

    assignments = [row["assignment"] for row in shortlist]
    assert len(assignments) == 5
    assert "root:known|mid1:known|mid2:known|tip:known" in assignments
    assert assignments[0] == "root:r0|mid1:m0|mid2:o0|tip:t0"


def test_penalty_recovery_summary_splits_smoothing_penalty_and_recovered_power() -> None:
    module = _load_script_module()

    summary = module.penalty_recovery_summary(
        raw_faceted_power_w=166.99,
        raw_smoothed_without_reselect_power_w=180.49,
        best_reoptimized_smooth_power_w=171.20,
        old_fx_clark_power_w=187.98,
    )

    assert summary["smoothing_penalty_w"] == pytest.approx(13.50)
    assert summary["recovered_by_reoptimization_w"] == pytest.approx(9.29)
    assert summary["remaining_penalty_after_reoptimization_w"] == pytest.approx(4.21)
    assert summary["best_smooth_beats_old_fx_clark"] is True
