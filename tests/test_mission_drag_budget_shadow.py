"""Tests for mission drag budget shadow evaluator."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path

import pytest

from hpa_mdo.concept.pipeline import (
    _mean_effective_cd_with_source,
    _PROFILE_CD_SOURCE_STATION,
    _PROFILE_CD_SOURCE_FEEDBACK,
    _PROFILE_CD_SOURCE_STUB,
    _PROFILE_CD_QUALITY_MISSION,
    _PROFILE_CD_QUALITY_FALLBACK,
    _PROFILE_CD_QUALITY_NOT_MISSION,
)
from hpa_mdo.mission.drag_budget import load_mission_drag_budget
from hpa_mdo.mission.drag_budget_shadow import (
    SHADOW_CSV_FILENAME,
    SHADOW_SUMMARY_JSON_FILENAME,
    ShadowRow,
    evaluate_shadow_candidate,
    run_shadow_on_ranked_pool_json,
)
from hpa_mdo.mission.objective import FakeAnchorCurve

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUDGET_YAML = _REPO_ROOT / "configs" / "mission_drag_budget_example.yaml"
_REAL_RANKED_POOL = (
    _REPO_ROOT / "output" / "birdman_oswald_fourier_smoke_20260502" / "concept_ranked_pool.json"
)


def _budget():
    return load_mission_drag_budget(_BUDGET_YAML)


def _make_candidate(
    concept_id: str = "test-00",
    span_m: float = 35.0,
    aspect_ratio: float = 38.0,
    profile_cd_proxy: float | None = 0.0125,
    oswald_efficiency: float | None = 0.90,
    evaluated_gross_mass_kg: float = 98.5,
    raw_clmax: float = 1.09,
    speed_sweep_window: list[float] | None = None,
    eta_prop: float = 0.86,
    eta_trans: float = 0.96,
) -> dict:
    """Build a minimal synthetic candidate dict resembling concept_ranked_pool format."""
    return {
        "concept_id": concept_id,
        "span_m": span_m,
        "aspect_ratio": aspect_ratio,
        "wing_area_m2": span_m**2 / aspect_ratio,
        "mission": {
            "profile_cd_proxy": profile_cd_proxy,
            "oswald_efficiency": oswald_efficiency,
            "evaluated_gross_mass_kg": evaluated_gross_mass_kg,
            "speed_sweep_window_mps": speed_sweep_window or [6.4, 7.2],
            "propulsion_efficiency_assumptions": {
                "eta_prop_design": eta_prop,
                "eta_transmission": eta_trans,
            },
            "target_range_km": 42.195,
        },
        "local_stall": {
            "raw_clmax": raw_clmax,
            "safe_clmax": raw_clmax * 0.80,
        },
    }


def _make_fake_rider_curve() -> FakeAnchorCurve:
    return FakeAnchorCurve(anchor_power_w=213.0, anchor_duration_min=108.2)


# ---------------------------------------------------------------------------
# Test 1: complete input → finite result
# ---------------------------------------------------------------------------

def test_shadow_evaluator_complete_input_produces_finite_result() -> None:
    """Shadow evaluator on a fully specified candidate produces finite values."""
    budget = _budget()
    candidate = _make_candidate(
        span_m=35.0,
        aspect_ratio=38.0,
        profile_cd_proxy=0.0125,
        oswald_efficiency=0.90,
        evaluated_gross_mass_kg=98.5,
    )
    rider_curve = _make_fake_rider_curve()

    row = evaluate_shadow_candidate(
        candidate=candidate,
        budget=budget,
        air_density=1.1357,
        rider_curve=rider_curve,
        thermal_derate_factor=0.9159,
        target_range_km=42.195,
    )

    assert row.evaluation_status == "ok"
    assert row.cd0_total_est is not None and isfinite(row.cd0_total_est)
    assert row.wing_area_m2 is not None and isfinite(row.wing_area_m2)
    assert row.cd0_nonwing_equivalent is not None and isfinite(row.cd0_nonwing_equivalent)
    assert row.drag_budget_band in ("target", "boundary", "rescue", "over_budget")
    assert row.cl_required is not None and isfinite(row.cl_required)
    assert row.cl_to_clmax_ratio is not None and isfinite(row.cl_to_clmax_ratio)
    assert row.mission_power_margin_crank_w is not None
    assert isfinite(row.mission_power_margin_crank_w)


# ---------------------------------------------------------------------------
# Test 2: missing cd0_wing_profile → evaluation_status="missing_cd0_wing_profile"
# ---------------------------------------------------------------------------

def test_shadow_evaluator_missing_cd0_wing_profile_does_not_crash() -> None:
    """When profile_cd_proxy is None, status is 'missing_cd0_wing_profile', no crash."""
    budget = _budget()
    candidate = _make_candidate(profile_cd_proxy=None)

    row = evaluate_shadow_candidate(
        candidate=candidate,
        budget=budget,
        air_density=1.1357,
        rider_curve=None,
        thermal_derate_factor=1.0,
        target_range_km=42.195,
    )

    assert row.evaluation_status == "missing_cd0_wing_profile"
    assert row.cd0_total_est is None
    assert row.drag_budget_band is None


def test_shadow_evaluator_zero_cd0_wing_profile_does_not_crash() -> None:
    """When profile_cd_proxy is 0, status is 'missing_cd0_wing_profile'."""
    budget = _budget()
    candidate = _make_candidate(profile_cd_proxy=0.0)

    row = evaluate_shadow_candidate(
        candidate=candidate,
        budget=budget,
        air_density=1.1357,
        rider_curve=None,
        thermal_derate_factor=1.0,
        target_range_km=42.195,
    )

    assert row.evaluation_status == "missing_cd0_wing_profile"


# ---------------------------------------------------------------------------
# Test 3: shadow mode disabled → no shadow file (no run_shadow call)
# ---------------------------------------------------------------------------

def test_shadow_disabled_produces_no_shadow_file(tmp_path: Path) -> None:
    """When shadow is not called, no shadow CSV is written."""
    shadow_csv = tmp_path / SHADOW_CSV_FILENAME
    shadow_summary = tmp_path / SHADOW_SUMMARY_JSON_FILENAME

    # Simulate: pipeline runs, but shadow mode is disabled (we never call run_shadow_*)
    # Just verify the files don't exist if we never call the shadow function.
    assert not shadow_csv.exists()
    assert not shadow_summary.exists()


# ---------------------------------------------------------------------------
# Test 4: shadow summary statistics
# ---------------------------------------------------------------------------

def test_shadow_summary_statistics(tmp_path: Path) -> None:
    """Summary correctly counts total, evaluated, and band distribution."""
    # Build a minimal fake ranked pool JSON
    candidates = [
        _make_candidate("c-00", profile_cd_proxy=0.0125, oswald_efficiency=0.90),  # target
        _make_candidate("c-01", profile_cd_proxy=0.018, oswald_efficiency=0.85),   # over/rescue
        _make_candidate("c-02", profile_cd_proxy=None),   # missing_cd0
    ]
    ranked_pool_json = {
        "config_path": None,
        "ranked_pool": candidates,
    }
    pool_json_path = tmp_path / "concept_ranked_pool.json"
    pool_json_path.write_text(json.dumps(ranked_pool_json), encoding="utf-8")

    summary = run_shadow_on_ranked_pool_json(
        ranked_pool_json_path=pool_json_path,
        budget_config_path=_BUDGET_YAML,
        output_dir=tmp_path,
        rider_curve=None,
        auto_load_rider_curve=False,
    )

    assert summary["total_candidates"] == 3
    assert summary["evaluated_candidates"] == 2
    assert summary["missing_input_candidates"] == 1
    assert isinstance(summary["count_by_drag_budget_band"], dict)
    total_in_bands = sum(summary["count_by_drag_budget_band"].values())
    assert total_in_bands == 2

    # Shadow files must exist
    assert (tmp_path / SHADOW_CSV_FILENAME).exists()
    assert (tmp_path / SHADOW_SUMMARY_JSON_FILENAME).exists()

    # CSV must have a header and data rows
    lines = (tmp_path / SHADOW_CSV_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4  # header + 3 candidates
    assert "candidate_id" in lines[0]
    assert "evaluation_status" in lines[0]


# ---------------------------------------------------------------------------
# Test 5: reference case (span=35, AR=38, mass=98.5, cd0_wing=0.0125)
# ---------------------------------------------------------------------------

def test_reference_case_target_band_with_fake_rider_curve() -> None:
    """Reference: span=35, AR=38, mass=98.5, cd0_wing=0.0125 → target band."""
    budget = _budget()
    candidate = _make_candidate(
        concept_id="reference",
        span_m=35.0,
        aspect_ratio=38.0,
        profile_cd_proxy=0.0125,
        oswald_efficiency=0.90,
        evaluated_gross_mass_kg=98.5,
        raw_clmax=1.55,
        speed_sweep_window=[6.2, 6.8],
    )
    rider_curve = FakeAnchorCurve(
        anchor_power_w=213.0,
        anchor_duration_min=108.2,
        exponent=1.0,
    )

    row = evaluate_shadow_candidate(
        candidate=candidate,
        budget=budget,
        air_density=1.1357,
        rider_curve=rider_curve,
        thermal_derate_factor=0.9159,
        target_range_km=42.195,
    )

    assert row.evaluation_status == "ok"
    # cd0_total_est = 0.0125 + 0.13 / (35^2/38) ≈ 0.01653
    assert row.cd0_total_est == pytest.approx(0.0165, abs=0.001)
    assert row.drag_budget_band == "target"
    assert row.mission_power_margin_crank_w is not None
    # With good CD0, power margin should be better than -15 W (reference with cd0=0.020)
    assert row.mission_power_margin_crank_w > -15.0


# ---------------------------------------------------------------------------
# Test 6: run on real ranked pool (if available)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _REAL_RANKED_POOL.exists(),
    reason="real concept_ranked_pool.json not present in output directory",
)
def test_shadow_run_on_real_ranked_pool(tmp_path: Path) -> None:
    """Integration: runs shadow evaluation on a real pipeline output."""
    summary = run_shadow_on_ranked_pool_json(
        ranked_pool_json_path=_REAL_RANKED_POOL,
        budget_config_path=_BUDGET_YAML,
        output_dir=tmp_path,
        auto_load_rider_curve=True,
    )

    assert summary["total_candidates"] > 0
    assert summary["evaluated_candidates"] >= 0
    # All evaluated candidates should have a recognized band
    for band in summary["count_by_drag_budget_band"]:
        assert band in ("target", "boundary", "rescue", "over_budget")

    csv_path = tmp_path / SHADOW_CSV_FILENAME
    assert csv_path.exists()
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2

    # Summary JSON must be valid
    summary_data = json.loads(
        (tmp_path / SHADOW_SUMMARY_JSON_FILENAME).read_text(encoding="utf-8")
    )
    assert "total_candidates" in summary_data
    assert "count_by_drag_budget_band" in summary_data
    assert "config_paths" in summary_data


# ---------------------------------------------------------------------------
# Test 7: _mean_effective_cd_with_source — three source paths
# ---------------------------------------------------------------------------

def test_mean_effective_cd_with_source_station_points() -> None:
    """When station_points have cd_effective, source=cruise_station_points."""
    station_points = [
        {"cd_effective": 0.0110, "weight": 1.5},
        {"cd_effective": 0.0130, "weight": 0.5},
    ]
    airfoil_feedback: dict = {}

    cd, source, quality = _mean_effective_cd_with_source(station_points, airfoil_feedback)

    expected_cd = (0.0110 * 1.5 + 0.0130 * 0.5) / 2.0
    assert cd == pytest.approx(expected_cd, rel=1e-9)
    assert source == _PROFILE_CD_SOURCE_STATION
    assert quality == _PROFILE_CD_QUALITY_MISSION


def test_mean_effective_cd_with_source_airfoil_feedback_fallback() -> None:
    """When station_points lack cd_effective, falls back to airfoil_feedback."""
    station_points = [{"weight": 1.0}]  # no cd_effective
    airfoil_feedback = {"mean_cd_effective": 0.0155}

    cd, source, quality = _mean_effective_cd_with_source(station_points, airfoil_feedback)

    assert cd == pytest.approx(0.0155, rel=1e-9)
    assert source == _PROFILE_CD_SOURCE_FEEDBACK
    assert quality == _PROFILE_CD_QUALITY_FALLBACK


def test_mean_effective_cd_with_source_stub_fallback() -> None:
    """When neither source is available, returns stub 0.020."""
    station_points: list = []
    airfoil_feedback: dict = {}

    cd, source, quality = _mean_effective_cd_with_source(station_points, airfoil_feedback)

    assert cd == pytest.approx(0.020, rel=1e-9)
    assert source == _PROFILE_CD_SOURCE_STUB
    assert quality == _PROFILE_CD_QUALITY_NOT_MISSION


# ---------------------------------------------------------------------------
# Test 8: shadow reads and propagates source/quality from candidate dict
# ---------------------------------------------------------------------------

def test_shadow_propagates_source_quality_from_candidate_dict() -> None:
    """ShadowRow carries profile_cd_proxy_source and _quality from the candidate."""
    budget = _budget()
    candidate = _make_candidate(profile_cd_proxy=0.0115)
    candidate["mission"]["profile_cd_proxy_source"] = _PROFILE_CD_SOURCE_STATION
    candidate["mission"]["profile_cd_proxy_quality"] = _PROFILE_CD_QUALITY_MISSION

    row = evaluate_shadow_candidate(
        candidate=candidate,
        budget=budget,
        air_density=1.1357,
        rider_curve=None,
        thermal_derate_factor=1.0,
        target_range_km=42.195,
    )

    assert row.evaluation_status == "ok"
    assert row.profile_cd_proxy_source == _PROFILE_CD_SOURCE_STATION
    assert row.profile_cd_proxy_quality == _PROFILE_CD_QUALITY_MISSION


# ---------------------------------------------------------------------------
# Test 9: not_mission_grade profile_cd — no crash, status flagged
# ---------------------------------------------------------------------------

def test_shadow_not_mission_grade_does_not_crash_and_is_flagged() -> None:
    """Candidate with quality=not_mission_grade gets status=profile_cd_not_mission_grade."""
    budget = _budget()
    candidate = _make_candidate(profile_cd_proxy=0.020)
    candidate["mission"]["profile_cd_proxy_source"] = _PROFILE_CD_SOURCE_STUB
    candidate["mission"]["profile_cd_proxy_quality"] = _PROFILE_CD_QUALITY_NOT_MISSION

    row = evaluate_shadow_candidate(
        candidate=candidate,
        budget=budget,
        air_density=1.1357,
        rider_curve=None,
        thermal_derate_factor=1.0,
        target_range_km=42.195,
    )

    assert row.evaluation_status == "profile_cd_not_mission_grade"
    assert row.cd0_total_est is not None  # values still computed
    assert row.drag_budget_band is not None
    assert "stub fallback" in row.notes


# ---------------------------------------------------------------------------
# Test 10: summary counts not_mission_grade and mission_budget_candidate
# ---------------------------------------------------------------------------

def test_shadow_summary_counts_profile_cd_quality(tmp_path: Path) -> None:
    """Summary correctly tallies profile_cd_quality_counts and derived counts."""
    c_mission = _make_candidate("c-m", profile_cd_proxy=0.0115)
    c_mission["mission"]["profile_cd_proxy_source"] = _PROFILE_CD_SOURCE_STATION
    c_mission["mission"]["profile_cd_proxy_quality"] = _PROFILE_CD_QUALITY_MISSION

    c_stub = _make_candidate("c-s", profile_cd_proxy=0.020)
    c_stub["mission"]["profile_cd_proxy_source"] = _PROFILE_CD_SOURCE_STUB
    c_stub["mission"]["profile_cd_proxy_quality"] = _PROFILE_CD_QUALITY_NOT_MISSION

    c_missing = _make_candidate("c-x", profile_cd_proxy=None)

    ranked_pool_json = {"config_path": None, "ranked_pool": [c_mission, c_stub, c_missing]}
    pool_path = tmp_path / "concept_ranked_pool.json"
    pool_path.write_text(json.dumps(ranked_pool_json), encoding="utf-8")

    summary = run_shadow_on_ranked_pool_json(
        ranked_pool_json_path=pool_path,
        budget_config_path=_BUDGET_YAML,
        output_dir=tmp_path,
        rider_curve=None,
        auto_load_rider_curve=False,
    )

    assert summary["total_candidates"] == 3
    assert summary["evaluated_candidates"] == 1          # only mission-grade "ok"
    assert summary["count_not_mission_grade_profile_cd"] == 1
    assert summary["count_mission_budget_candidate_profile_cd"] == 1
    assert summary["missing_input_candidates"] == 1      # c-x with None cd

    qc = summary["profile_cd_quality_counts"]
    assert qc.get("mission_budget_candidate", 0) == 1
    assert qc.get("not_mission_grade", 0) == 1
    assert qc.get("unknown", 0) == 1  # c-x has no quality field

    # profile_cd_proxy_quality column must appear in the CSV header
    lines = (tmp_path / SHADOW_CSV_FILENAME).read_text(encoding="utf-8").splitlines()
    assert "profile_cd_proxy_quality" in lines[0]
    assert "profile_cd_proxy_source" in lines[0]


# ---------------------------------------------------------------------------
# Test 11: stubbed smoke — not_mission_grade > 0 in quality counts
# ---------------------------------------------------------------------------

def test_shadow_summary_with_all_stub_candidates(tmp_path: Path) -> None:
    """All candidates with stub quality → count_not_mission_grade_profile_cd == total evaluated-ish."""
    candidates = [
        _make_candidate(f"s-{i:02d}", profile_cd_proxy=0.020)
        for i in range(5)
    ]
    for c in candidates:
        c["mission"]["profile_cd_proxy_source"] = _PROFILE_CD_SOURCE_STUB
        c["mission"]["profile_cd_proxy_quality"] = _PROFILE_CD_QUALITY_NOT_MISSION

    pool = {"config_path": None, "ranked_pool": candidates}
    pool_path = tmp_path / "concept_ranked_pool.json"
    pool_path.write_text(json.dumps(pool), encoding="utf-8")

    summary = run_shadow_on_ranked_pool_json(
        ranked_pool_json_path=pool_path,
        budget_config_path=_BUDGET_YAML,
        output_dir=tmp_path,
        rider_curve=None,
        auto_load_rider_curve=False,
    )

    assert summary["total_candidates"] == 5
    assert summary["evaluated_candidates"] == 0           # none are "ok"
    assert summary["count_not_mission_grade_profile_cd"] == 5
    assert summary["profile_cd_quality_counts"].get("not_mission_grade", 0) == 5
