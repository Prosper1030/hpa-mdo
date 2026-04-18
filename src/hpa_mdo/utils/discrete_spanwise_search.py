"""Spanwise dynamic-programming search for discrete laminate schedules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from hpa_mdo.core.materials import PlyMaterial
from hpa_mdo.structure.laminate import PlyStack

@dataclass(frozen=True)
class SpanwiseSearchObjective:
    """Lexicographic objective for the spanwise discrete search."""

    total_shortfall_m: float
    total_overshoot_m: float
    total_discrete_mass_full_wing_kg: float
    total_transition_half_ply_delta: int

    def as_tuple(self) -> tuple[float, float, float, int]:
        return (
            float(self.total_shortfall_m),
            float(self.total_overshoot_m),
            float(self.total_discrete_mass_full_wing_kg),
            int(self.total_transition_half_ply_delta),
        )


@dataclass(frozen=True)
class SpanwiseDiscreteSearchResult:
    """Best spanwise discrete layup schedule under the DP objective."""

    selected_stacks: tuple[PlyStack, ...]
    objective: SpanwiseSearchObjective


@dataclass(frozen=True)
class _SegmentCandidate:
    stack: PlyStack
    half_ply_count: int
    shortfall_m: float
    overshoot_m: float
    discrete_mass_full_wing_kg: float


def search_spanwise_discrete_stacks(
    *,
    continuous_thicknesses_m: Sequence[float],
    outer_radii_m: Sequence[float],
    stacks: Sequence[PlyStack],
    ply_mat: PlyMaterial,
    ply_drop_limit: int = 1,
    segment_lengths_m: Sequence[float] | None = None,
) -> SpanwiseDiscreteSearchResult:
    """Search a globally consistent spanwise stack schedule with DP.

    The objective is intentionally conservative: first minimize thickness
    shortfall against the continuous target profile, then minimize excess
    thickness, then minimize discrete mass, and finally prefer smaller
    transition jumps.
    """
    n_segments = len(continuous_thicknesses_m)
    if n_segments == 0:
        raise ValueError("continuous_thicknesses_m must not be empty.")
    if len(outer_radii_m) != n_segments:
        raise ValueError("outer_radii_m must match continuous_thicknesses_m in length.")
    if segment_lengths_m is not None and len(segment_lengths_m) != n_segments:
        raise ValueError("segment_lengths_m must match continuous_thicknesses_m in length.")
    if not stacks:
        raise ValueError("stacks must not be empty.")
    if ply_drop_limit < 0:
        raise ValueError("ply_drop_limit must be non-negative.")

    segment_lengths = (
        tuple(float(length) for length in segment_lengths_m)
        if segment_lengths_m is not None
        else tuple(1.0 for _ in range(n_segments))
    )
    ordered_stacks = tuple(
        sorted(
            stacks,
            key=lambda stack: (stack.wall_thickness(ply_mat.t_ply), _stack_sort_key(stack)),
        )
    )
    candidates = tuple(
        _segment_candidates(
            target_thickness_m=float(target_thickness_m),
            outer_radius_m=float(outer_radius_m),
            segment_length_m=float(segment_length_m),
            stacks=ordered_stacks,
            ply_mat=ply_mat,
        )
        for target_thickness_m, outer_radius_m, segment_length_m in zip(
            continuous_thicknesses_m,
            outer_radii_m,
            segment_lengths,
            strict=True,
        )
    )

    prev_objectives = [
        SpanwiseSearchObjective(
            total_shortfall_m=candidate.shortfall_m,
            total_overshoot_m=candidate.overshoot_m,
            total_discrete_mass_full_wing_kg=candidate.discrete_mass_full_wing_kg,
            total_transition_half_ply_delta=0,
        )
        for candidate in candidates[0]
    ]
    backpointers: list[list[int]] = [[-1] * len(ordered_stacks) for _ in range(n_segments)]

    for segment_idx in range(1, n_segments):
        current_objectives: list[SpanwiseSearchObjective] = []
        for candidate_idx, candidate in enumerate(candidates[segment_idx]):
            best_previous = -1
            best_objective: SpanwiseSearchObjective | None = None
            for previous_idx, previous_candidate in enumerate(candidates[segment_idx - 1]):
                transition_delta = abs(
                    previous_candidate.half_ply_count - candidate.half_ply_count
                )
                if transition_delta > int(ply_drop_limit):
                    continue
                objective = SpanwiseSearchObjective(
                    total_shortfall_m=prev_objectives[previous_idx].total_shortfall_m
                    + candidate.shortfall_m,
                    total_overshoot_m=prev_objectives[previous_idx].total_overshoot_m
                    + candidate.overshoot_m,
                    total_discrete_mass_full_wing_kg=prev_objectives[
                        previous_idx
                    ].total_discrete_mass_full_wing_kg
                    + candidate.discrete_mass_full_wing_kg,
                    total_transition_half_ply_delta=prev_objectives[
                        previous_idx
                    ].total_transition_half_ply_delta
                    + transition_delta,
                )
                if best_objective is None or objective.as_tuple() < best_objective.as_tuple():
                    best_objective = objective
                    best_previous = previous_idx
            if best_objective is None:
                raise ValueError(
                    "No feasible spanwise discrete layup path satisfies the ply-drop limit."
                )
            current_objectives.append(best_objective)
            backpointers[segment_idx][candidate_idx] = best_previous
        prev_objectives = current_objectives

    final_index = min(range(len(prev_objectives)), key=lambda idx: prev_objectives[idx].as_tuple())
    selected: list[PlyStack] = []
    current_index = final_index
    for segment_idx in range(n_segments - 1, -1, -1):
        selected.append(candidates[segment_idx][current_index].stack)
        current_index = backpointers[segment_idx][current_index]
        if segment_idx > 0 and current_index < 0:
            raise RuntimeError("DP backpointer chain is broken.")  # pragma: no cover

    selected.reverse()
    return SpanwiseDiscreteSearchResult(
        selected_stacks=tuple(selected),
        objective=prev_objectives[final_index],
    )


def _segment_candidates(
    *,
    target_thickness_m: float,
    outer_radius_m: float,
    segment_length_m: float,
    stacks: Sequence[PlyStack],
    ply_mat: PlyMaterial,
) -> tuple[_SegmentCandidate, ...]:
    candidates: list[_SegmentCandidate] = []
    for stack in stacks:
        wall_thickness_m = float(stack.wall_thickness(ply_mat.t_ply))
        shortfall_m = max(float(target_thickness_m) - wall_thickness_m, 0.0)
        overshoot_m = max(wall_thickness_m - float(target_thickness_m), 0.0)
        candidates.append(
            _SegmentCandidate(
                stack=stack,
                half_ply_count=int(stack.total_plies() // 2),
                shortfall_m=float(shortfall_m),
                overshoot_m=float(overshoot_m),
                discrete_mass_full_wing_kg=_segment_full_wing_mass(
                    segment_length_m=float(segment_length_m),
                    outer_radius_m=float(outer_radius_m),
                    wall_thickness_m=wall_thickness_m,
                    density_kgpm3=ply_mat.density,
                ),
            )
        )
    return tuple(candidates)


def _segment_full_wing_mass(
    *,
    segment_length_m: float,
    outer_radius_m: float,
    wall_thickness_m: float,
    density_kgpm3: float,
) -> float:
    inner_radius_m = max(float(outer_radius_m) - float(wall_thickness_m), 0.0)
    area_m2 = 3.141592653589793 * (float(outer_radius_m) ** 2 - inner_radius_m**2)
    return 2.0 * float(segment_length_m) * float(density_kgpm3) * area_m2


def _stack_sort_key(stack: PlyStack) -> tuple[int, int, int, int]:
    return (stack.total_plies(), stack.n_90, stack.n_45, stack.n_0)


__all__ = [
    "SpanwiseDiscreteSearchResult",
    "SpanwiseSearchObjective",
    "search_spanwise_discrete_stacks",
]
