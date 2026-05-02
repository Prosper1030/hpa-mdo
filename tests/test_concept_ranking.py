from __future__ import annotations

from hpa_mdo.concept.ranking import CandidateConceptResult, rank_concepts


def _fixed_range_candidate(
    *,
    concept_id: str,
    completion_time_s: float,
    safety_margin: float,
    mission_margin_m: float,
    span_efficiency: float | None = None,
    spanload_deviation: float | None = None,
) -> CandidateConceptResult:
    return CandidateConceptResult(
        concept_id=concept_id,
        launch_feasible=True,
        turn_feasible=True,
        trim_feasible=True,
        local_stall_feasible=True,
        mission_feasible=True,
        safety_margin=safety_margin,
        mission_objective_mode="fixed_range_best_time",
        mission_score=completion_time_s,
        best_range_m=42_195.0 + mission_margin_m,
        mission_margin_m=mission_margin_m,
        assembly_penalty=0.0,
        span_efficiency=span_efficiency,
        spanload_deviation=spanload_deviation,
    )


def test_fixed_range_best_time_ranking_keeps_margin_ahead_of_thin_speed() -> None:
    safer_slow = _fixed_range_candidate(
        concept_id="safer_slow",
        completion_time_s=6_400.0,
        safety_margin=0.18,
        mission_margin_m=2_000.0,
    )
    faster_thin = _fixed_range_candidate(
        concept_id="faster_thin",
        completion_time_s=5_900.0,
        safety_margin=0.04,
        mission_margin_m=350.0,
    )

    ranked = rank_concepts([faster_thin, safer_slow])

    assert ranked[0].concept_id == "safer_slow"
    assert ranked[1].concept_id == "faster_thin"
    assert "lower_feasibility_margin_than_best" in ranked[1].why_not_higher


def test_fixed_range_best_time_breaks_margin_ties_by_completion_time() -> None:
    slow = _fixed_range_candidate(
        concept_id="slow",
        completion_time_s=6_400.0,
        safety_margin=0.12,
        mission_margin_m=900.0,
    )
    fast = _fixed_range_candidate(
        concept_id="fast",
        completion_time_s=5_900.0,
        safety_margin=0.12,
        mission_margin_m=900.0,
    )

    ranked = rank_concepts([slow, fast])

    assert ranked[0].concept_id == "fast"
    assert ranked[1].concept_id == "slow"
    assert "slower_time_than_best" in ranked[1].why_not_higher


def test_fixed_range_best_time_breaks_time_ties_by_span_efficiency() -> None:
    low_e = _fixed_range_candidate(
        concept_id="low_e",
        completion_time_s=6_100.0,
        safety_margin=0.12,
        mission_margin_m=900.0,
        span_efficiency=0.72,
    )
    high_e = _fixed_range_candidate(
        concept_id="high_e",
        completion_time_s=6_100.0,
        safety_margin=0.12,
        mission_margin_m=900.0,
        span_efficiency=0.90,
    )

    ranked = rank_concepts([low_e, high_e])

    assert ranked[0].concept_id == "high_e"
    assert ranked[1].concept_id == "low_e"
    assert "lower_span_efficiency_than_best" in ranked[1].why_not_higher


def test_fixed_range_best_time_breaks_efficiency_ties_by_spanload_deviation() -> None:
    wavy_load = _fixed_range_candidate(
        concept_id="wavy_load",
        completion_time_s=6_100.0,
        safety_margin=0.12,
        mission_margin_m=900.0,
        span_efficiency=0.86,
        spanload_deviation=0.30,
    )
    cleaner_load = _fixed_range_candidate(
        concept_id="cleaner_load",
        completion_time_s=6_100.0,
        safety_margin=0.12,
        mission_margin_m=900.0,
        span_efficiency=0.86,
        spanload_deviation=0.05,
    )

    ranked = rank_concepts([wavy_load, cleaner_load])

    assert ranked[0].concept_id == "cleaner_load"
    assert ranked[1].concept_id == "wavy_load"
    assert "higher_spanload_deviation_than_best" in ranked[1].why_not_higher
