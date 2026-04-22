from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CandidateConceptResult:
    concept_id: str
    launch_feasible: bool
    turn_feasible: bool
    trim_feasible: bool
    mission_feasible: bool
    safety_margin: float
    mission_objective_mode: str
    mission_score: float
    best_range_m: float
    assembly_penalty: float
    local_stall_feasible: bool = True

    @property
    def safety_feasible(self) -> bool:
        return (
            self.launch_feasible
            and self.turn_feasible
            and self.trim_feasible
            and self.local_stall_feasible
        )


@dataclass(frozen=True)
class RankedConcept:
    concept_id: str
    score: float
    safety_feasible: bool
    selection_status: str
    why_not_higher: tuple[str, ...] = field(default_factory=tuple)


def rank_concepts(results: list[CandidateConceptResult]) -> list[RankedConcept]:
    scored: list[tuple[CandidateConceptResult, float, list[str]]] = []
    for result in results:
        reasons: list[str] = []
        if not result.launch_feasible:
            reasons.append("launch_not_feasible")
        if not result.turn_feasible:
            reasons.append("turn_not_feasible")
        if not result.trim_feasible:
            reasons.append("trim_not_feasible")
        if not result.local_stall_feasible:
            reasons.append("local_stall_not_feasible")
        if not result.mission_feasible:
            reasons.append("target_range_not_met")
        if result.safety_margin < 0.10:
            reasons.append("low_safety_margin")
        if result.assembly_penalty >= 2.5:
            reasons.append("assembly_complexity")

        if result.mission_objective_mode == "max_range":
            mission_component = 0.001 * float(result.mission_score)
        elif result.mission_objective_mode == "min_power":
            mission_component = float(result.mission_score)
        else:
            raise ValueError(
                f"unsupported mission_objective_mode for ranking: {result.mission_objective_mode}"
            )

        score = (
            (0.0 if result.launch_feasible else 1000.0)
            + (0.0 if result.turn_feasible else 1000.0)
            + (0.0 if result.trim_feasible else 1000.0)
            + (0.0 if result.local_stall_feasible else 1000.0)
            + (0.0 if result.mission_feasible else 500.0)
            + mission_component
            - 10.0 * result.safety_margin
            + result.assembly_penalty
        )
        scored.append((result, score, reasons))

    scored.sort(key=lambda item: (0 if item[0].safety_feasible else 1, item[1], item[0].concept_id))
    best_result = None if not scored else scored[0][0]
    first_infeasible_emitted = False
    ranked: list[RankedConcept] = []
    for result, score, reasons in scored:
        augmented_reasons = list(reasons)
        if best_result is not None and result.concept_id != best_result.concept_id and not reasons:
            if result.mission_objective_mode == "max_range" and result.best_range_m < best_result.best_range_m:
                augmented_reasons.append("less_range_than_best")
            elif (
                result.mission_objective_mode == "min_power"
                and result.mission_score > best_result.mission_score
            ):
                augmented_reasons.append("higher_power_than_best")
            elif result.safety_margin < best_result.safety_margin:
                augmented_reasons.append("lower_safety_margin_than_best")
            elif result.assembly_penalty > best_result.assembly_penalty:
                augmented_reasons.append("higher_assembly_penalty_than_best")

        if result.safety_feasible:
            selection_status = "selected"
        elif not first_infeasible_emitted:
            selection_status = "best_infeasible"
            first_infeasible_emitted = True
        else:
            selection_status = "infeasible_runner_up"

        ranked.append(
            RankedConcept(
                concept_id=result.concept_id,
                score=score,
                safety_feasible=result.safety_feasible,
                selection_status=selection_status,
                why_not_higher=tuple(augmented_reasons),
            )
        )
    return ranked
