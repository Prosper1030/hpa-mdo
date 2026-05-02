from __future__ import annotations

from dataclasses import dataclass, field

_MIN_SOLVED_WING_E = 0.90


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
    mission_margin_m: float | None = None
    span_efficiency: float | None = None
    spanload_deviation: float | None = None
    best_power_margin_w: float | None = None

    @property
    def span_efficiency_feasible(self) -> bool:
        if self.span_efficiency is None:
            return True
        return float(self.span_efficiency) >= _MIN_SOLVED_WING_E

    @property
    def safety_feasible(self) -> bool:
        return (
            self.launch_feasible
            and self.turn_feasible
            and self.trim_feasible
            and self.local_stall_feasible
            and self.span_efficiency_feasible
        )

    @property
    def fully_feasible(self) -> bool:
        return self.safety_feasible and self.mission_feasible

    @property
    def failed_gate_count(self) -> int:
        return sum(
            0 if feasible else 1
            for feasible in (
                self.launch_feasible,
                self.turn_feasible,
                self.trim_feasible,
                self.local_stall_feasible,
                self.span_efficiency_feasible,
                self.mission_feasible,
            )
        )


@dataclass(frozen=True)
class RankedConcept:
    concept_id: str
    score: float
    safety_feasible: bool
    fully_feasible: bool
    selection_status: str
    failed_gate_count: int = 0
    combined_feasibility_margin: float = 0.0
    why_not_higher: tuple[str, ...] = field(default_factory=tuple)


def _mission_component(result: CandidateConceptResult) -> float:
    if result.mission_objective_mode == "max_range":
        return 0.001 * float(result.mission_score)
    if result.mission_objective_mode == "min_power":
        return float(result.mission_score)
    if result.mission_objective_mode == "fixed_range_best_time":
        return float(result.mission_score)
    raise ValueError(
        f"unsupported mission_objective_mode for ranking: {result.mission_objective_mode}"
    )


def _combined_feasibility_margin(result: CandidateConceptResult) -> float:
    if result.mission_margin_m is None:
        return float(result.safety_margin)
    mission_margin_km = float(result.mission_margin_m) / 1000.0
    return min(float(result.safety_margin), mission_margin_km)


def _span_efficiency_component(result: CandidateConceptResult) -> float:
    if result.span_efficiency is None:
        return 0.0
    return float(result.span_efficiency)


def _spanload_deviation_component(result: CandidateConceptResult) -> float:
    if result.spanload_deviation is None:
        return 1.0e9
    return float(result.spanload_deviation)


def _power_margin_component(result: CandidateConceptResult) -> float:
    if result.best_power_margin_w is None:
        return float("-inf")
    return float(result.best_power_margin_w)


def _ranking_sort_key(
    item: tuple[CandidateConceptResult, float, float, list[str]],
) -> tuple[object, ...]:
    result, _, combined_feasibility_margin, _ = item
    if result.fully_feasible:
        return (
            0,
            _mission_component(result),
            -_power_margin_component(result),
            -_span_efficiency_component(result),
            _spanload_deviation_component(result),
            result.assembly_penalty,
            result.concept_id,
        )
    return (
        1,
        float(result.failed_gate_count),
        -combined_feasibility_margin,
        _mission_component(result),
        -_power_margin_component(result),
        -_span_efficiency_component(result),
        _spanload_deviation_component(result),
        result.assembly_penalty,
        result.concept_id,
    )


def rank_concepts(results: list[CandidateConceptResult]) -> list[RankedConcept]:
    scored: list[tuple[CandidateConceptResult, float, float, list[str]]] = []
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
        if not result.span_efficiency_feasible:
            reasons.append("wing_e_below_minimum")
        if not result.mission_feasible:
            reasons.append("target_range_not_met")
        combined_feasibility_margin = _combined_feasibility_margin(result)
        if result.assembly_penalty >= 2.5:
            reasons.append("assembly_complexity")

        mission_component = _mission_component(result)

        score = (
            1000.0 * float(result.failed_gate_count)
            + mission_component
            - 100.0 * combined_feasibility_margin
            + (
                0.0
                if result.spanload_deviation is None
                else 50.0 * float(result.spanload_deviation)
            )
            + result.assembly_penalty
        )
        scored.append((result, score, combined_feasibility_margin, reasons))

    scored.sort(key=_ranking_sort_key)
    best_result = None if not scored else scored[0][0]
    best_margin = float("-inf") if not scored else scored[0][2]
    first_infeasible_emitted = False
    ranked: list[RankedConcept] = []
    for result, score, combined_feasibility_margin, reasons in scored:
        augmented_reasons = list(reasons)
        if best_result is not None and result.concept_id != best_result.concept_id and not reasons:
            if combined_feasibility_margin < best_margin:
                augmented_reasons.append("lower_feasibility_margin_than_best")
            elif (
                result.mission_objective_mode == "max_range"
                and result.best_range_m < best_result.best_range_m
            ):
                augmented_reasons.append("less_range_than_best")
            elif (
                result.mission_objective_mode == "min_power"
                and result.mission_score > best_result.mission_score
            ):
                augmented_reasons.append("higher_power_than_best")
            elif (
                result.mission_objective_mode == "fixed_range_best_time"
                and result.mission_score > best_result.mission_score
            ):
                augmented_reasons.append("slower_time_than_best")
            elif _power_margin_component(result) < _power_margin_component(best_result):
                augmented_reasons.append("lower_power_margin_than_best")
            elif _span_efficiency_component(result) < _span_efficiency_component(
                best_result
            ):
                augmented_reasons.append("lower_span_efficiency_than_best")
            elif (
                best_result.spanload_deviation is not None
                and result.spanload_deviation is not None
                and _spanload_deviation_component(result)
                > _spanload_deviation_component(best_result)
            ):
                augmented_reasons.append("higher_spanload_deviation_than_best")
            elif result.safety_margin < best_result.safety_margin:
                augmented_reasons.append("lower_safety_margin_than_best")
            elif result.assembly_penalty > best_result.assembly_penalty:
                augmented_reasons.append("higher_assembly_penalty_than_best")

        if result.fully_feasible:
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
                fully_feasible=result.fully_feasible,
                selection_status=selection_status,
                failed_gate_count=result.failed_gate_count,
                combined_feasibility_margin=combined_feasibility_margin,
                why_not_higher=tuple(augmented_reasons),
            )
        )
    return ranked
