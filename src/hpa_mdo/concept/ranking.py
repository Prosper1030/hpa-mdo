from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CandidateConceptResult:
    concept_id: str
    launch_feasible: bool
    turn_feasible: bool
    trim_feasible: bool
    safety_margin: float
    best_range_m: float
    assembly_penalty: float


@dataclass(frozen=True)
class RankedConcept:
    concept_id: str
    score: float
    why_not_higher: tuple[str, ...] = field(default_factory=tuple)


def rank_concepts(results: list[CandidateConceptResult]) -> list[RankedConcept]:
    ranked: list[RankedConcept] = []
    for result in results:
        score = (
            (0.0 if result.launch_feasible else 1000.0)
            + (0.0 if result.turn_feasible else 1000.0)
            + (0.0 if result.trim_feasible else 1000.0)
            - 0.001 * result.best_range_m
            - 10.0 * result.safety_margin
            + result.assembly_penalty
        )
        ranked.append(
            RankedConcept(
                concept_id=result.concept_id,
                score=score,
            )
        )
    return sorted(ranked, key=lambda item: (item.score, item.concept_id))
