from __future__ import annotations

import pytest

from hpa_mdo.concept.airfoil_cma_es import (
    CMAESState,
    initialize_cma_es_state,
    sample_cma_es_offspring,
    update_cma_es_state,
)
from hpa_mdo.concept.airfoil_cst import (
    SeedlessCSTCoefficientBounds,
    SeedlessCSTConstraints,
    build_seedless_cst_template,
)


def _bounds() -> SeedlessCSTCoefficientBounds:
    return SeedlessCSTCoefficientBounds(
        upper_min=(0.18, 0.26, 0.25, 0.18, 0.11, 0.05, 0.015),
        upper_max=(0.22, 0.32, 0.30, 0.22, 0.13, 0.07, 0.025),
        lower_min=(-0.14, -0.18, -0.15, -0.11, -0.06, -0.03, -0.010),
        lower_max=(-0.10, -0.14, -0.13, -0.09, -0.04, -0.015, -0.002),
        te_thickness_min=0.0015,
        te_thickness_max=0.0025,
    )


def _seed_parent() -> object:
    return build_seedless_cst_template(
        zone_name="root",
        upper_coefficients=(0.20, 0.29, 0.27, 0.20, 0.12, 0.06, 0.020),
        lower_coefficients=(-0.12, -0.16, -0.14, -0.10, -0.05, -0.022, -0.006),
        te_thickness_m=0.0020,
        candidate_role="cma_parent",
    )


def test_initialize_cma_es_state_uses_parent_design_vector() -> None:
    bounds = _bounds()
    parent = _seed_parent()

    state = initialize_cma_es_state(
        zone_name="root",
        parent=parent,
        bounds=bounds,
        sigma_init=0.07,
        knee_index=2,
    )

    assert isinstance(state, CMAESState)
    assert state.zone_name == "root"
    assert state.coefficient_count == 7
    assert state.iteration == 0
    assert state.knee_index == 2
    assert state.sigma == pytest.approx(0.07)
    assert len(state.mean_vector) == 2 * 7 + 1
    assert state.mean_vector[-1] == pytest.approx(0.0020)


def test_sample_cma_es_offspring_is_deterministic_and_within_bounds() -> None:
    bounds = _bounds()
    state = initialize_cma_es_state(
        zone_name="root",
        parent=_seed_parent(),
        bounds=bounds,
        sigma_init=0.05,
    )

    constraints = SeedlessCSTConstraints(max_thickness_x_max=0.45)
    first = sample_cma_es_offspring(
        state=state,
        bounds=bounds,
        constraints=constraints,
        population_lambda=4,
        random_seed=11,
    )
    second = sample_cma_es_offspring(
        state=state,
        bounds=bounds,
        constraints=constraints,
        population_lambda=4,
        random_seed=11,
    )

    assert len(first) == 4
    assert len(second) == 4
    assert tuple(child.candidate_role for child in first) == tuple(
        child.candidate_role for child in second
    )
    assert all(
        bounds.te_thickness_min <= child.te_thickness_m <= bounds.te_thickness_max
        for child in first
    )
    for child in first:
        for value, low, high in zip(
            child.upper_coefficients, bounds.upper_min, bounds.upper_max
        ):
            assert low <= value <= high
        for value, low, high in zip(
            child.lower_coefficients, bounds.lower_min, bounds.lower_max
        ):
            assert low <= value <= high


def test_update_cma_es_state_shrinks_sigma_when_no_offspring_beat_parent() -> None:
    state = initialize_cma_es_state(
        zone_name="root",
        parent=_seed_parent(),
        bounds=_bounds(),
        sigma_init=0.05,
    )
    children = sample_cma_es_offspring(
        state=state,
        bounds=_bounds(),
        constraints=SeedlessCSTConstraints(max_thickness_x_max=0.45),
        population_lambda=4,
        random_seed=7,
    )
    bad_scores = tuple((child, 1.0) for child in children)

    new_state = update_cma_es_state(
        state=state,
        scored_offspring=bad_scores,
        parent_score=0.0,
    )

    assert new_state.sigma < state.sigma
    assert new_state.iteration == state.iteration + 1


def test_update_cma_es_state_expands_sigma_when_many_offspring_improve() -> None:
    state = initialize_cma_es_state(
        zone_name="root",
        parent=_seed_parent(),
        bounds=_bounds(),
        sigma_init=0.05,
    )
    children = sample_cma_es_offspring(
        state=state,
        bounds=_bounds(),
        constraints=SeedlessCSTConstraints(max_thickness_x_max=0.45),
        population_lambda=4,
        random_seed=7,
    )
    good_scores = tuple((child, -1.0) for child in children)

    new_state = update_cma_es_state(
        state=state,
        scored_offspring=good_scores,
        parent_score=0.0,
    )

    assert new_state.sigma > state.sigma
    assert new_state.iteration == state.iteration + 1
    assert new_state.coefficient_count == state.coefficient_count


def test_sample_cma_es_offspring_zero_population_returns_empty() -> None:
    state = initialize_cma_es_state(
        zone_name="root",
        parent=_seed_parent(),
        bounds=_bounds(),
        sigma_init=0.05,
    )

    children = sample_cma_es_offspring(
        state=state,
        bounds=_bounds(),
        constraints=SeedlessCSTConstraints(max_thickness_x_max=0.45),
        population_lambda=0,
        random_seed=0,
    )

    assert children == ()
