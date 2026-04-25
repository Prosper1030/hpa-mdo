from __future__ import annotations

import math
from dataclasses import dataclass
from random import Random

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    SeedlessCSTCoefficientBounds,
    SeedlessCSTConstraints,
    build_seedless_cst_template,
    validate_seedless_cst_template,
)


@dataclass(frozen=True)
class CMAESState:
    zone_name: str
    coefficient_count: int
    mean_vector: tuple[float, ...]
    sigma: float
    iteration: int = 0
    knee_index: int = 0


def _coefficient_count(bounds: SeedlessCSTCoefficientBounds) -> int:
    coefficient_count = len(bounds.upper_min)
    if not (
        len(bounds.upper_max)
        == len(bounds.lower_min)
        == len(bounds.lower_max)
        == coefficient_count
    ):
        raise ValueError("seedless CST bounds must have matching coefficient lengths.")
    return coefficient_count


def _template_to_design_vector(template: CSTAirfoilTemplate) -> tuple[float, ...]:
    return (
        *tuple(float(value) for value in template.upper_coefficients),
        *tuple(float(value) for value in template.lower_coefficients),
        float(template.te_thickness_m),
    )


def _bounds_vectors(
    bounds: SeedlessCSTCoefficientBounds,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    lower = (
        *tuple(float(value) for value in bounds.upper_min),
        *tuple(float(value) for value in bounds.lower_min),
        float(bounds.te_thickness_min),
    )
    upper = (
        *tuple(float(value) for value in bounds.upper_max),
        *tuple(float(value) for value in bounds.lower_max),
        float(bounds.te_thickness_max),
    )
    return lower, upper


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(float(value), float(lower)), float(upper))


def _candidate_from_design_vector(
    *,
    zone_name: str,
    vector: tuple[float, ...],
    coefficient_count: int,
    candidate_role: str,
) -> CSTAirfoilTemplate:
    return build_seedless_cst_template(
        zone_name=zone_name,
        upper_coefficients=tuple(vector[:coefficient_count]),
        lower_coefficients=tuple(vector[coefficient_count : 2 * coefficient_count]),
        te_thickness_m=float(vector[-1]),
        candidate_role=candidate_role,
    )


def initialize_cma_es_state(
    *,
    zone_name: str,
    parent: CSTAirfoilTemplate,
    bounds: SeedlessCSTCoefficientBounds,
    sigma_init: float = 0.05,
    knee_index: int = 0,
) -> CMAESState:
    coefficient_count = _coefficient_count(bounds)
    parent_vector = _template_to_design_vector(parent)
    expected_dimension = 2 * coefficient_count + 1
    if len(parent_vector) != expected_dimension:
        raise ValueError("parent template coefficient lengths must match seedless CST bounds.")
    if sigma_init <= 0.0:
        raise ValueError("sigma_init must be positive.")
    return CMAESState(
        zone_name=zone_name,
        coefficient_count=coefficient_count,
        mean_vector=parent_vector,
        sigma=float(sigma_init),
        iteration=0,
        knee_index=int(knee_index),
    )


def sample_cma_es_offspring(
    *,
    state: CMAESState,
    bounds: SeedlessCSTCoefficientBounds,
    constraints: SeedlessCSTConstraints = SeedlessCSTConstraints(),
    population_lambda: int,
    random_seed: int | None = 0,
    max_attempts_per_child: int = 50,
) -> tuple[CSTAirfoilTemplate, ...]:
    if population_lambda <= 0:
        return ()
    if max_attempts_per_child < 1:
        raise ValueError("max_attempts_per_child must be at least 1.")

    coefficient_count = _coefficient_count(bounds)
    if state.coefficient_count != coefficient_count:
        raise ValueError("CMA-ES state coefficient count must match bounds.")

    lower_bounds, upper_bounds = _bounds_vectors(bounds)
    span = tuple(
        max(float(upper_bounds[i]) - float(lower_bounds[i]), 1.0e-12)
        for i in range(len(lower_bounds))
    )

    rng = Random(random_seed)
    children: list[CSTAirfoilTemplate] = []
    attempts = 0
    max_attempts = int(population_lambda) * int(max_attempts_per_child)
    while len(children) < population_lambda and attempts < max_attempts:
        attempts += 1
        vector = tuple(
            _clamp(
                state.mean_vector[index] + rng.gauss(0.0, state.sigma * span[index]),
                lower_bounds[index],
                upper_bounds[index],
            )
            for index in range(len(state.mean_vector))
        )
        candidate_role = (
            f"cma_k{int(state.knee_index):02d}_t{int(state.iteration):02d}"
            f"_c{len(children):04d}"
        )
        candidate = _candidate_from_design_vector(
            zone_name=state.zone_name,
            vector=vector,
            coefficient_count=coefficient_count,
            candidate_role=candidate_role,
        )
        if not validate_seedless_cst_template(candidate, constraints=constraints).valid:
            continue
        children.append(candidate)

    if len(children) < population_lambda:
        raise ValueError(
            "insufficient feasible CMA-ES offspring after geometry filtering: "
            f"requested {population_lambda}, found {len(children)}"
        )
    return tuple(children)


def update_cma_es_state(
    *,
    state: CMAESState,
    scored_offspring: tuple[tuple[CSTAirfoilTemplate, float], ...],
    parent_score: float,
    selection_count: int | None = None,
    sigma_shrink_factor: float = 0.85,
    sigma_expand_factor: float = 1.10,
    success_target_rate: float = 0.20,
) -> CMAESState:
    if not scored_offspring:
        return state
    sorted_by_score = sorted(scored_offspring, key=lambda entry: entry[1])
    population_size = len(sorted_by_score)
    mu = (
        max(1, population_size // 2)
        if selection_count is None
        else max(1, min(int(selection_count), population_size))
    )
    selected = sorted_by_score[:mu]

    raw_weights = [math.log(mu + 1.0) - math.log(index + 1.0) for index in range(mu)]
    weight_sum = float(sum(raw_weights))
    if weight_sum <= 0.0:
        weights = [1.0 / mu] * mu
    else:
        weights = [value / weight_sum for value in raw_weights]

    new_mean = tuple(
        float(
            sum(
                weights[i] * _template_to_design_vector(selected[i][0])[index]
                for i in range(mu)
            )
        )
        for index in range(len(state.mean_vector))
    )

    success_count = sum(
        1 for _, score in scored_offspring if float(score) < float(parent_score)
    )
    success_rate = success_count / float(population_size)
    if success_rate > success_target_rate:
        new_sigma = float(state.sigma) * float(sigma_expand_factor)
    else:
        new_sigma = float(state.sigma) * float(sigma_shrink_factor)

    return CMAESState(
        zone_name=state.zone_name,
        coefficient_count=state.coefficient_count,
        mean_vector=new_mean,
        sigma=new_sigma,
        iteration=int(state.iteration) + 1,
        knee_index=int(state.knee_index),
    )
