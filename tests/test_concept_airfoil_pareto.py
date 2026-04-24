from __future__ import annotations

import pytest

from hpa_mdo.concept.airfoil_pareto import (
    AirfoilParetoCandidate,
    rank_constrained_pareto_candidates,
    select_nsga2_survivors,
)


def test_rank_constrained_pareto_candidates_prefers_feasible_over_infeasible() -> None:
    infeasible_fast = AirfoilParetoCandidate(
        candidate_role="infeasible_fast",
        objectives={"cd": 0.015, "negative_clmax": -1.40},
        constraint_violations={"spar_depth": 0.02},
    )
    feasible_balanced = AirfoilParetoCandidate(
        candidate_role="feasible_balanced",
        objectives={"cd": 0.020, "negative_clmax": -1.25},
    )
    feasible_dominated = AirfoilParetoCandidate(
        candidate_role="feasible_dominated",
        objectives={"cd": 0.024, "negative_clmax": -1.20},
    )

    ranked = rank_constrained_pareto_candidates(
        (infeasible_fast, feasible_dominated, feasible_balanced)
    )

    assert [(entry.candidate.candidate_role, entry.rank) for entry in ranked] == [
        ("feasible_balanced", 0),
        ("feasible_dominated", 1),
        ("infeasible_fast", 2),
    ]
    assert ranked[2].total_constraint_violation == pytest.approx(0.02)


def test_select_nsga2_survivors_keeps_front_extremes_by_crowding_distance() -> None:
    candidates = tuple(
        AirfoilParetoCandidate(
            candidate_role=f"front_{index}",
            objectives={
                "cd": 0.018 + 0.001 * index,
                "negative_clmax": -(1.20 + 0.02 * index),
            },
        )
        for index in range(5)
    )

    survivors = select_nsga2_survivors(candidates, survivor_count=3)

    assert len(survivors) == 3
    assert survivors[0].candidate_role == "front_0"
    assert survivors[1].candidate_role == "front_4"
    assert "front_0" in {candidate.candidate_role for candidate in survivors}
    assert "front_4" in {candidate.candidate_role for candidate in survivors}
