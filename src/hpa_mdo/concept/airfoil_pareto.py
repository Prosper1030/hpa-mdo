from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping


@dataclass(frozen=True)
class AirfoilParetoCandidate:
    candidate_role: str
    objectives: Mapping[str, float]
    constraint_violations: Mapping[str, float] | None = None


@dataclass(frozen=True)
class AirfoilParetoEntry:
    candidate: AirfoilParetoCandidate
    rank: int
    crowding_distance: float
    total_constraint_violation: float


def _objective_names(candidates: tuple[AirfoilParetoCandidate, ...]) -> tuple[str, ...]:
    names: set[str] = set()
    for candidate in candidates:
        names.update(str(name) for name in candidate.objectives)
    return tuple(sorted(names))


def _objective_value(candidate: AirfoilParetoCandidate, name: str) -> float:
    value = float(candidate.objectives.get(name, float("inf")))
    return value if isfinite(value) else float("inf")


def _total_constraint_violation(candidate: AirfoilParetoCandidate) -> float:
    violations = candidate.constraint_violations or {}
    return sum(max(0.0, float(value)) for value in violations.values())


def _constrained_dominates(
    left: AirfoilParetoCandidate,
    right: AirfoilParetoCandidate,
    *,
    objective_names: tuple[str, ...],
) -> bool:
    left_violation = _total_constraint_violation(left)
    right_violation = _total_constraint_violation(right)
    if left_violation <= 0.0 and right_violation > 0.0:
        return True
    if left_violation > 0.0 and right_violation <= 0.0:
        return False
    if left_violation > 0.0 or right_violation > 0.0:
        return left_violation < right_violation

    left_values = tuple(_objective_value(left, name) for name in objective_names)
    right_values = tuple(_objective_value(right, name) for name in objective_names)
    return all(left <= right for left, right in zip(left_values, right_values, strict=True)) and any(
        left < right for left, right in zip(left_values, right_values, strict=True)
    )


def _non_dominated_fronts(
    candidates: tuple[AirfoilParetoCandidate, ...],
    *,
    objective_names: tuple[str, ...],
) -> list[list[int]]:
    dominates: list[set[int]] = [set() for _ in candidates]
    dominated_count = [0 for _ in candidates]
    fronts: list[list[int]] = [[]]

    for left_index, left in enumerate(candidates):
        for right_index, right in enumerate(candidates):
            if left_index == right_index:
                continue
            if _constrained_dominates(left, right, objective_names=objective_names):
                dominates[left_index].add(right_index)
            elif _constrained_dominates(right, left, objective_names=objective_names):
                dominated_count[left_index] += 1
        if dominated_count[left_index] == 0:
            fronts[0].append(left_index)

    front_index = 0
    while front_index < len(fronts) and fronts[front_index]:
        next_front: list[int] = []
        for candidate_index in fronts[front_index]:
            for dominated_index in dominates[candidate_index]:
                dominated_count[dominated_index] -= 1
                if dominated_count[dominated_index] == 0:
                    next_front.append(dominated_index)
        if next_front:
            fronts.append(next_front)
        front_index += 1

    return fronts


def _crowding_distances(
    candidates: tuple[AirfoilParetoCandidate, ...],
    front: list[int],
    *,
    objective_names: tuple[str, ...],
) -> dict[int, float]:
    if not front:
        return {}
    if len(front) <= 2:
        return {index: float("inf") for index in front}

    distances = {index: 0.0 for index in front}
    for objective_name in objective_names:
        ordered = sorted(front, key=lambda index: _objective_value(candidates[index], objective_name))
        min_value = _objective_value(candidates[ordered[0]], objective_name)
        max_value = _objective_value(candidates[ordered[-1]], objective_name)
        distances[ordered[0]] = float("inf")
        distances[ordered[-1]] = float("inf")
        if max_value == min_value:
            continue
        for position in range(1, len(ordered) - 1):
            if distances[ordered[position]] == float("inf"):
                continue
            previous_value = _objective_value(candidates[ordered[position - 1]], objective_name)
            next_value = _objective_value(candidates[ordered[position + 1]], objective_name)
            distances[ordered[position]] += (next_value - previous_value) / (max_value - min_value)
    return distances


def rank_constrained_pareto_candidates(
    candidates: tuple[AirfoilParetoCandidate, ...],
) -> tuple[AirfoilParetoEntry, ...]:
    if not candidates:
        return ()
    objective_names = _objective_names(candidates)
    fronts = _non_dominated_fronts(candidates, objective_names=objective_names)
    entries: list[AirfoilParetoEntry] = []
    for rank, front in enumerate(fronts):
        crowding = _crowding_distances(candidates, front, objective_names=objective_names)
        for index in front:
            entries.append(
                AirfoilParetoEntry(
                    candidate=candidates[index],
                    rank=rank,
                    crowding_distance=crowding[index],
                    total_constraint_violation=_total_constraint_violation(candidates[index]),
                )
            )
    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.rank,
                -entry.crowding_distance,
                entry.total_constraint_violation,
                entry.candidate.candidate_role,
            ),
        )
    )


def select_nsga2_survivors(
    candidates: tuple[AirfoilParetoCandidate, ...],
    *,
    survivor_count: int,
) -> tuple[AirfoilParetoCandidate, ...]:
    if survivor_count <= 0:
        return ()
    ranked = rank_constrained_pareto_candidates(candidates)
    return tuple(entry.candidate for entry in ranked[:survivor_count])
