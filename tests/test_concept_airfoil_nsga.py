from __future__ import annotations

from hpa_mdo.concept.airfoil_cst import (
    SeedlessCSTCoefficientBounds,
    SeedlessCSTConstraints,
    build_seedless_cst_template,
    validate_seedless_cst_template,
)
from hpa_mdo.concept.airfoil_nsga import generate_seedless_nsga2_offspring


def _bounds() -> SeedlessCSTCoefficientBounds:
    return SeedlessCSTCoefficientBounds(
        upper_min=(0.18, 0.26, 0.25, 0.18, 0.11, 0.05, 0.015),
        upper_max=(0.22, 0.32, 0.30, 0.22, 0.13, 0.07, 0.025),
        lower_min=(-0.14, -0.18, -0.15, -0.11, -0.06, -0.03, -0.010),
        lower_max=(-0.10, -0.14, -0.13, -0.09, -0.04, -0.015, -0.002),
        te_thickness_min=0.0015,
        te_thickness_max=0.0025,
    )


def test_generate_seedless_nsga2_offspring_is_deterministic_and_seed_free() -> None:
    bounds = _bounds()
    parents = (
        build_seedless_cst_template(
            zone_name="root",
            upper_coefficients=(0.18, 0.26, 0.25, 0.18, 0.11, 0.05, 0.015),
            lower_coefficients=(-0.14, -0.18, -0.15, -0.11, -0.06, -0.03, -0.010),
            te_thickness_m=0.0015,
            candidate_role="parent_a",
        ),
        build_seedless_cst_template(
            zone_name="root",
            upper_coefficients=(0.22, 0.32, 0.30, 0.22, 0.13, 0.07, 0.025),
            lower_coefficients=(-0.10, -0.14, -0.13, -0.09, -0.04, -0.015, -0.002),
            te_thickness_m=0.0025,
            candidate_role="parent_b",
        ),
    )

    first = generate_seedless_nsga2_offspring(
        zone_name="root",
        parents=parents,
        bounds=bounds,
        constraints=SeedlessCSTConstraints(max_thickness_x_max=0.45),
        offspring_count=4,
        generation_index=1,
        random_seed=13,
    )
    second = generate_seedless_nsga2_offspring(
        zone_name="root",
        parents=parents,
        bounds=bounds,
        constraints=SeedlessCSTConstraints(max_thickness_x_max=0.45),
        offspring_count=4,
        generation_index=1,
        random_seed=13,
    )

    assert first == second
    assert len(first) == 4
    assert all(candidate.seed_name is None for candidate in first)
    assert {candidate.candidate_role for candidate in first} == {
        f"nsga2_g01_child_{index:04d}" for index in range(4)
    }
    assert all(
        validate_seedless_cst_template(
            candidate,
            constraints=SeedlessCSTConstraints(max_thickness_x_max=0.45),
        ).valid
        for candidate in first
    )
