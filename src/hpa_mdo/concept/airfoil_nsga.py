from __future__ import annotations

from random import Random

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    SeedlessCSTCoefficientBounds,
    SeedlessCSTConstraints,
    build_seedless_cst_template,
    validate_seedless_cst_template,
)


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


def _make_child_vector(
    *,
    parent_a: tuple[float, ...],
    parent_b: tuple[float, ...],
    lower_bounds: tuple[float, ...],
    upper_bounds: tuple[float, ...],
    rng: Random,
    mutation_scale: float,
) -> tuple[float, ...]:
    values: list[float] = []
    for a_value, b_value, lower, upper in zip(
        parent_a,
        parent_b,
        lower_bounds,
        upper_bounds,
        strict=True,
    ):
        blend_fraction = rng.uniform(-0.15, 1.15)
        blended = float(a_value) + blend_fraction * (float(b_value) - float(a_value))
        span = float(upper) - float(lower)
        mutated = blended + rng.gauss(0.0, max(span, 1.0e-12) * float(mutation_scale))
        values.append(_clamp(mutated, lower, upper))
    return tuple(values)


def generate_seedless_nsga2_offspring(
    *,
    zone_name: str,
    parents: tuple[CSTAirfoilTemplate, ...],
    bounds: SeedlessCSTCoefficientBounds,
    constraints: SeedlessCSTConstraints = SeedlessCSTConstraints(),
    offspring_count: int,
    generation_index: int,
    random_seed: int | None = 0,
    mutation_scale: float = 0.06,
    max_attempts_per_child: int = 50,
) -> tuple[CSTAirfoilTemplate, ...]:
    if offspring_count <= 0:
        return ()
    if len(parents) < 2:
        raise ValueError("at least two parent templates are required for NSGA-II offspring.")
    if max_attempts_per_child < 1:
        raise ValueError("max_attempts_per_child must be at least 1.")

    coefficient_count = _coefficient_count(bounds)
    parent_vectors = tuple(_template_to_design_vector(parent) for parent in parents)
    expected_dimension = 2 * coefficient_count + 1
    if any(len(vector) != expected_dimension for vector in parent_vectors):
        raise ValueError("parent template coefficient lengths must match seedless CST bounds.")

    lower_bounds, upper_bounds = _bounds_vectors(bounds)
    rng = Random(random_seed)
    children: list[CSTAirfoilTemplate] = []
    attempts = 0
    max_attempts = int(offspring_count) * int(max_attempts_per_child)
    while len(children) < offspring_count and attempts < max_attempts:
        attempts += 1
        parent_a, parent_b = rng.sample(parent_vectors, 2)
        child_vector = _make_child_vector(
            parent_a=parent_a,
            parent_b=parent_b,
            lower_bounds=lower_bounds,
            upper_bounds=upper_bounds,
            rng=rng,
            mutation_scale=mutation_scale,
        )
        child_index = len(children)
        candidate = _candidate_from_design_vector(
            zone_name=zone_name,
            vector=child_vector,
            coefficient_count=coefficient_count,
            candidate_role=f"nsga2_g{int(generation_index):02d}_child_{child_index:04d}",
        )
        if not validate_seedless_cst_template(candidate, constraints=constraints).valid:
            continue
        children.append(candidate)

    if len(children) < offspring_count:
        raise ValueError(
            "insufficient feasible NSGA-II offspring after geometry filtering: "
            f"requested {offspring_count}, found {len(children)}"
        )
    return tuple(children)
