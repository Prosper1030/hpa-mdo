from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
from math import comb, cos, pi
from random import Random
from typing import Mapping, Sequence


_CANONICAL_ZONE_ORDER = ("root", "mid1", "mid2", "tip")
DEFAULT_THICKNESS_DELTA_LEVELS = (-0.018, -0.010, -0.006, 0.0, 0.006, 0.010, 0.018)
DEFAULT_CAMBER_DELTA_LEVELS = (-0.012, -0.008, 0.0, 0.008, 0.012)
_THICKNESS_UPPER_BASIS = (0.0, 1.0, 1.0, 0.0, 0.0)
_THICKNESS_LOWER_BASIS = (0.0, -1.0, -1.0, 0.0, 0.0)
_CAMBER_UPPER_BASIS = (0.0, 1.0, 0.5, 0.0, 0.0)
_CAMBER_LOWER_BASIS = (0.0, -0.75, -0.375, 0.0, 0.0)


@dataclass(frozen=True)
class CSTAirfoilTemplate:
    zone_name: str
    upper_coefficients: tuple[float, ...]
    lower_coefficients: tuple[float, ...]
    te_thickness_m: float
    seed_name: str | None = None
    candidate_role: str = "selected"
    thickness_delta: float = 0.0
    camber_delta: float = 0.0
    thickness_index: int | None = None
    camber_index: int | None = None


@dataclass(frozen=True)
class CSTValidationResult:
    valid: bool
    reason: str


@dataclass(frozen=True)
class CSTGeometryMetrics:
    max_thickness_ratio: float
    max_thickness_x: float
    spar_depth_ratio_25_35: float
    te_thickness_ratio: float
    curvature_reversal_count: int
    thickness_at_1pct_chord: float
    max_camber_ratio: float


@dataclass(frozen=True)
class SeedlessCSTCoefficientBounds:
    upper_min: tuple[float, ...]
    upper_max: tuple[float, ...]
    lower_min: tuple[float, ...]
    lower_max: tuple[float, ...]
    te_thickness_min: float
    te_thickness_max: float


@dataclass(frozen=True)
class SeedlessCSTConstraints:
    min_thickness_ratio: float = 0.10
    max_thickness_ratio: float = 0.16
    max_thickness_x_min: float = 0.25
    max_thickness_x_max: float = 0.40
    min_spar_depth_ratio_25_35: float = 0.09
    te_thickness_min: float = 0.001
    te_thickness_max: float = 0.004
    max_curvature_reversal_count: int = 8
    min_thickness_at_1pct_chord: float = 0.015
    max_camber_ratio: float = 0.10


def _bernstein(n: int, i: int, x: float) -> float:
    return comb(n, i) * (x**i) * ((1.0 - x) ** (n - i))


def _cst_surface(
    x: float,
    coefficients: tuple[float, ...],
    *,
    n1: float = 0.5,
    n2: float = 1.0,
) -> float:
    if not coefficients:
        raise ValueError("coefficients must not be empty.")
    x = min(max(float(x), 0.0), 1.0)
    class_term = (x**n1) * ((1.0 - x) ** n2)
    shape_term = sum(
        coefficient * _bernstein(len(coefficients) - 1, index, x)
        for index, coefficient in enumerate(coefficients)
    )
    return class_term * shape_term


def _generate_x_coordinates(point_count: int) -> tuple[float, ...]:
    if point_count < 2:
        raise ValueError("point_count must be at least 2.")
    return tuple(
        0.5 * (1.0 - cos(pi * index / float(point_count - 1)))
        for index in range(point_count)
    )


def generate_cst_coordinates(
    template: CSTAirfoilTemplate,
    *,
    point_count: int = 81,
) -> tuple[tuple[float, float], ...]:
    x_coords = _generate_x_coordinates(point_count)
    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []

    for x in x_coords:
        upper.append(
            (
                float(x),
                _cst_surface(x, template.upper_coefficients)
                + 0.5 * float(template.te_thickness_m) * float(x),
            )
        )
        lower.append(
            (
                float(x),
                _cst_surface(x, template.lower_coefficients)
                - 0.5 * float(template.te_thickness_m) * float(x),
            )
        )

    return tuple(reversed(upper)) + tuple(lower[1:])


def _sorted_surface(surface: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    return tuple(sorted(surface, key=lambda point: float(point[0])))


def _interp_surface_y(surface: tuple[tuple[float, float], ...], x: float) -> float:
    if len(surface) == 1:
        return float(surface[0][1])

    xs = [float(point[0]) for point in surface]
    ys = [float(point[1]) for point in surface]
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]

    right_index = bisect_left(xs, x)
    left_index = max(0, right_index - 1)
    x0 = xs[left_index]
    x1 = xs[right_index]
    y0 = ys[left_index]
    y1 = ys[right_index]
    if x1 == x0:
        return y0
    fraction = (x - x0) / (x1 - x0)
    return y0 + fraction * (y1 - y0)


def validate_cst_candidate_coordinates(
    coordinates: tuple[tuple[float, float], ...],
) -> CSTValidationResult:
    if len(coordinates) < 5:
        return CSTValidationResult(valid=False, reason="too_few_points")

    leading_edge_index = min(range(len(coordinates)), key=lambda index: float(coordinates[index][0]))
    if leading_edge_index == 0 or leading_edge_index == len(coordinates) - 1:
        return CSTValidationResult(valid=False, reason="missing_leading_edge_turn")

    upper_surface = _sorted_surface(tuple(coordinates[: leading_edge_index + 1]))
    lower_surface = _sorted_surface(tuple(coordinates[leading_edge_index:]))

    sample_xs = tuple(0.02 + 0.96 * index / 79.0 for index in range(80))
    for x in sample_xs:
        upper_y = _interp_surface_y(upper_surface, x)
        lower_y = _interp_surface_y(lower_surface, x)
        if upper_y - lower_y <= 0.0:
            return CSTValidationResult(valid=False, reason="non_positive_thickness")

    return CSTValidationResult(valid=True, reason="ok")


def build_seedless_cst_template(
    *,
    zone_name: str,
    upper_coefficients: tuple[float, ...],
    lower_coefficients: tuple[float, ...],
    te_thickness_m: float,
    candidate_role: str = "seedless",
) -> CSTAirfoilTemplate:
    if len(upper_coefficients) != len(lower_coefficients):
        raise ValueError("upper_coefficients and lower_coefficients must have the same length.")
    coefficient_count = len(upper_coefficients)
    if coefficient_count < 6 or coefficient_count > 9:
        raise ValueError("seedless CST v1 expects order 5..8, i.e. 6..9 coefficients.")
    if te_thickness_m <= 0.0:
        raise ValueError("te_thickness_m must be positive.")
    return CSTAirfoilTemplate(
        zone_name=str(zone_name),
        upper_coefficients=tuple(float(value) for value in upper_coefficients),
        lower_coefficients=tuple(float(value) for value in lower_coefficients),
        te_thickness_m=float(te_thickness_m),
        seed_name=None,
        candidate_role=str(candidate_role),
    )


def _surface_pair_from_coordinates(
    coordinates: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], ...], tuple[tuple[float, float], ...]]:
    leading_edge_index = min(range(len(coordinates)), key=lambda index: float(coordinates[index][0]))
    upper_surface = _sorted_surface(tuple(coordinates[: leading_edge_index + 1]))
    lower_surface = _sorted_surface(tuple(coordinates[leading_edge_index:]))
    return upper_surface, lower_surface


def _count_curvature_reversals(values: tuple[float, ...]) -> int:
    if len(values) < 5:
        return 0
    second_differences = tuple(
        values[index + 1] - 2.0 * values[index] + values[index - 1]
        for index in range(1, len(values) - 1)
    )
    signs: list[int] = []
    for value in second_differences:
        if abs(value) <= 1.0e-6:
            continue
        signs.append(1 if value > 0.0 else -1)
    return sum(1 for left, right in zip(signs[:-1], signs[1:]) if left != right)


def analyze_cst_geometry(
    template: CSTAirfoilTemplate,
    *,
    point_count: int = 161,
) -> CSTGeometryMetrics:
    coordinates = generate_cst_coordinates(template, point_count=point_count)
    validation = validate_cst_candidate_coordinates(coordinates)
    if not validation.valid:
        raise ValueError(f"cannot analyze invalid CST coordinates: {validation.reason}")

    upper_surface, lower_surface = _surface_pair_from_coordinates(coordinates)
    sample_xs = tuple(0.02 + 0.96 * index / 159.0 for index in range(160))
    thickness_by_x = tuple(
        (
            x,
            _interp_surface_y(upper_surface, x) - _interp_surface_y(lower_surface, x),
        )
        for x in sample_xs
    )
    max_thickness_x, max_thickness_ratio = max(thickness_by_x, key=lambda item: item[1])
    spar_zone_depths = tuple(
        thickness
        for x, thickness in thickness_by_x
        if 0.25 <= x <= 0.35
    )
    camber_values = tuple(
        0.5 * (_interp_surface_y(upper_surface, x) + _interp_surface_y(lower_surface, x))
        for x in sample_xs
    )
    thickness_at_1pct = float(
        _interp_surface_y(upper_surface, 0.01) - _interp_surface_y(lower_surface, 0.01)
    )
    max_camber_ratio = max((abs(value) for value in camber_values), default=0.0)
    return CSTGeometryMetrics(
        max_thickness_ratio=float(max_thickness_ratio),
        max_thickness_x=float(max_thickness_x),
        spar_depth_ratio_25_35=float(min(spar_zone_depths)) if spar_zone_depths else 0.0,
        te_thickness_ratio=float(template.te_thickness_m),
        curvature_reversal_count=_count_curvature_reversals(camber_values),
        thickness_at_1pct_chord=float(thickness_at_1pct),
        max_camber_ratio=float(max_camber_ratio),
    )


def validate_seedless_cst_template(
    template: CSTAirfoilTemplate,
    *,
    constraints: SeedlessCSTConstraints = SeedlessCSTConstraints(),
) -> CSTValidationResult:
    if template.seed_name is not None:
        return CSTValidationResult(valid=False, reason="seed_airfoil_identity_present")
    coordinates = generate_cst_coordinates(template)
    coordinate_validation = validate_cst_candidate_coordinates(coordinates)
    if not coordinate_validation.valid:
        return coordinate_validation
    metrics = analyze_cst_geometry(template)
    if metrics.max_thickness_ratio < constraints.min_thickness_ratio:
        return CSTValidationResult(valid=False, reason="max_thickness_below_min")
    if metrics.max_thickness_ratio > constraints.max_thickness_ratio:
        return CSTValidationResult(valid=False, reason="max_thickness_above_max")
    if not (
        constraints.max_thickness_x_min
        <= metrics.max_thickness_x
        <= constraints.max_thickness_x_max
    ):
        return CSTValidationResult(valid=False, reason="max_thickness_location_out_of_range")
    if metrics.spar_depth_ratio_25_35 < constraints.min_spar_depth_ratio_25_35:
        return CSTValidationResult(valid=False, reason="spar_depth_below_min")
    if metrics.te_thickness_ratio < constraints.te_thickness_min:
        return CSTValidationResult(valid=False, reason="te_thickness_below_min")
    if metrics.te_thickness_ratio > constraints.te_thickness_max:
        return CSTValidationResult(valid=False, reason="te_thickness_above_max")
    if metrics.curvature_reversal_count > constraints.max_curvature_reversal_count:
        return CSTValidationResult(valid=False, reason="curvature_reversal_count_exceeded")
    if metrics.thickness_at_1pct_chord < constraints.min_thickness_at_1pct_chord:
        return CSTValidationResult(valid=False, reason="leading_edge_too_sharp")
    if metrics.max_camber_ratio > constraints.max_camber_ratio:
        return CSTValidationResult(valid=False, reason="max_camber_above_max")
    return CSTValidationResult(valid=True, reason="ok")


def _validate_seedless_bounds(bounds: SeedlessCSTCoefficientBounds) -> int:
    coefficient_count = len(bounds.upper_min)
    if coefficient_count < 6 or coefficient_count > 9:
        raise ValueError("seedless CST bounds expect order 5..8, i.e. 6..9 coefficients.")
    if not (
        len(bounds.upper_max)
        == len(bounds.lower_min)
        == len(bounds.lower_max)
        == coefficient_count
    ):
        raise ValueError("seedless CST coefficient bounds must have matching lengths.")
    for lower, upper in zip(bounds.upper_min, bounds.upper_max, strict=True):
        if float(upper) < float(lower):
            raise ValueError("upper coefficient max must be >= min.")
    for lower, upper in zip(bounds.lower_min, bounds.lower_max, strict=True):
        if float(upper) < float(lower):
            raise ValueError("lower coefficient max must be >= min.")
    if bounds.te_thickness_max < bounds.te_thickness_min:
        raise ValueError("te_thickness_max must be >= te_thickness_min.")
    return coefficient_count


def _latin_hypercube_columns(
    *,
    sample_count: int,
    dimension_count: int,
    rng: Random,
) -> list[list[float]]:
    columns: list[list[float]] = []
    for _ in range(dimension_count):
        values = [
            (float(index) + rng.random()) / float(sample_count)
            for index in range(sample_count)
        ]
        rng.shuffle(values)
        columns.append(values)
    return columns


def _lerp(lower: float, upper: float, fraction: float) -> float:
    return float(lower) + (float(upper) - float(lower)) * float(fraction)


def _build_seedless_template_from_unit_sample(
    *,
    zone_name: str,
    unit_sample: Sequence[float],
    bounds: SeedlessCSTCoefficientBounds,
    coefficient_count: int,
    candidate_role: str,
) -> CSTAirfoilTemplate:
    if len(unit_sample) != 2 * coefficient_count + 1:
        raise ValueError("unit sample dimension does not match seedless CST bounds.")
    upper_coefficients = tuple(
        _lerp(bounds.upper_min[index], bounds.upper_max[index], unit_sample[index])
        for index in range(coefficient_count)
    )
    lower_coefficients = tuple(
        _lerp(
            bounds.lower_min[index],
            bounds.lower_max[index],
            unit_sample[coefficient_count + index],
        )
        for index in range(coefficient_count)
    )
    te_fraction = unit_sample[-1]
    return build_seedless_cst_template(
        zone_name=zone_name,
        upper_coefficients=upper_coefficients,
        lower_coefficients=lower_coefficients,
        te_thickness_m=_lerp(
            bounds.te_thickness_min,
            bounds.te_thickness_max,
            te_fraction,
        ),
        candidate_role=candidate_role,
    )


def sample_seedless_cst_latin_hypercube(
    *,
    zone_name: str,
    sample_count: int,
    bounds: SeedlessCSTCoefficientBounds,
    random_seed: int | None = 0,
) -> tuple[CSTAirfoilTemplate, ...]:
    if sample_count <= 0:
        raise ValueError("sample_count must be positive.")
    coefficient_count = _validate_seedless_bounds(bounds)
    dimension_count = 2 * coefficient_count + 1
    rng = Random(random_seed)
    columns = _latin_hypercube_columns(
        sample_count=sample_count,
        dimension_count=dimension_count,
        rng=rng,
    )

    candidates: list[CSTAirfoilTemplate] = []
    for sample_index in range(sample_count):
        unit_sample = tuple(column[sample_index] for column in columns)
        candidates.append(
            _build_seedless_template_from_unit_sample(
                zone_name=zone_name,
                unit_sample=unit_sample,
                bounds=bounds,
                coefficient_count=coefficient_count,
                candidate_role=f"seedless_lhs_{sample_index:04d}",
            )
        )
    return tuple(candidates)


def _sobol_base2_exponent(sample_count: int) -> int:
    sample_power = 1
    exponent = 0
    while sample_power < sample_count:
        sample_power *= 2
        exponent += 1
    return exponent


def sample_seedless_cst_sobol(
    *,
    zone_name: str,
    sample_count: int,
    bounds: SeedlessCSTCoefficientBounds,
    random_seed: int | None = 0,
) -> tuple[CSTAirfoilTemplate, ...]:
    if sample_count <= 0:
        raise ValueError("sample_count must be positive.")
    coefficient_count = _validate_seedless_bounds(bounds)
    dimension_count = 2 * coefficient_count + 1

    from scipy.stats import qmc

    sampler = qmc.Sobol(
        d=dimension_count,
        scramble=True,
        seed=random_seed,
    )
    unit_samples = sampler.random_base2(m=_sobol_base2_exponent(sample_count))

    candidates: list[CSTAirfoilTemplate] = []
    for sample_index, unit_sample in enumerate(unit_samples[:sample_count]):
        candidates.append(
            _build_seedless_template_from_unit_sample(
                zone_name=zone_name,
                unit_sample=tuple(float(value) for value in unit_sample),
                bounds=bounds,
                coefficient_count=coefficient_count,
                candidate_role=f"seedless_sobol_{sample_index:04d}",
            )
        )
    return tuple(candidates)


def sample_feasible_seedless_cst_sobol(
    *,
    zone_name: str,
    sample_count: int,
    bounds: SeedlessCSTCoefficientBounds,
    constraints: SeedlessCSTConstraints = SeedlessCSTConstraints(),
    random_seed: int | None = 0,
    max_oversample_factor: int = 8,
) -> tuple[CSTAirfoilTemplate, ...]:
    if sample_count <= 0:
        raise ValueError("sample_count must be positive.")
    if max_oversample_factor < 1:
        raise ValueError("max_oversample_factor must be at least 1.")

    raw_candidates = sample_seedless_cst_sobol(
        zone_name=zone_name,
        sample_count=sample_count * max_oversample_factor,
        bounds=bounds,
        random_seed=random_seed,
    )
    feasible = tuple(
        candidate
        for candidate in raw_candidates
        if validate_seedless_cst_template(candidate, constraints=constraints).valid
    )
    if len(feasible) < sample_count:
        raise ValueError(
            "insufficient feasible seedless CST candidates after geometry filtering: "
            f"requested {sample_count}, found {len(feasible)}"
        )
    return feasible[:sample_count]


def build_bounded_candidate_family(
    template: CSTAirfoilTemplate,
    *,
    thickness_delta_levels: tuple[float, ...] = DEFAULT_THICKNESS_DELTA_LEVELS,
    camber_delta_levels: tuple[float, ...] = DEFAULT_CAMBER_DELTA_LEVELS,
) -> tuple[CSTAirfoilTemplate, ...]:
    if len(template.upper_coefficients) != len(template.lower_coefficients):
        raise ValueError("upper_coefficients and lower_coefficients must have the same length.")

    def normalize_levels(levels: tuple[float, ...], *, name: str) -> tuple[float, ...]:
        normalized = tuple(float(level) for level in levels)
        if not normalized:
            raise ValueError(f"{name} must not be empty.")
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"{name} entries must be unique.")
        if 0.0 not in normalized:
            raise ValueError(f"{name} must include 0.0.")
        return normalized

    thickness_delta_levels = normalize_levels(
        thickness_delta_levels,
        name="thickness_delta_levels",
    )
    camber_delta_levels = normalize_levels(
        camber_delta_levels,
        name="camber_delta_levels",
    )

    coefficient_count = len(template.upper_coefficients)

    def scaled_basis(basis: tuple[float, ...], scale: float) -> tuple[float, ...]:
        values = [0.0] * coefficient_count
        for index in range(min(coefficient_count, len(basis))):
            values[index] = float(basis[index]) * float(scale)
        return tuple(values)

    def offset(values: tuple[float, ...], deltas: tuple[float, ...]) -> tuple[float, ...]:
        if len(values) != len(deltas):
            raise ValueError("offset delta must match coefficient count.")
        return tuple(value + delta for value, delta in zip(values, deltas, strict=True))

    def candidate_role(
        thickness_delta: float,
        camber_delta: float,
        *,
        thickness_index: int,
        camber_index: int,
    ) -> str:
        def is_close(left: float, right: float) -> bool:
            return abs(left - right) <= 1.0e-9

        if is_close(thickness_delta, 0.0) and is_close(camber_delta, 0.0):
            return "base"
        if is_close(thickness_delta, 0.010) and is_close(camber_delta, 0.0):
            return "thickness_up"
        if is_close(thickness_delta, -0.010) and is_close(camber_delta, 0.0):
            return "thickness_down"
        if is_close(thickness_delta, 0.0) and is_close(camber_delta, 0.008):
            return "camber_up"
        if is_close(thickness_delta, 0.0) and is_close(camber_delta, -0.008):
            return "camber_down"

        return f"t{thickness_index:02d}_c{camber_index:02d}"

    candidates: list[CSTAirfoilTemplate] = []
    for thickness_index, thickness_delta in enumerate(thickness_delta_levels):
        for camber_index, camber_delta in enumerate(camber_delta_levels):
            upper_delta = tuple(
                thickness_change + camber_change
                for thickness_change, camber_change in zip(
                    scaled_basis(_THICKNESS_UPPER_BASIS, thickness_delta),
                    scaled_basis(_CAMBER_UPPER_BASIS, camber_delta),
                    strict=True,
                )
            )
            lower_delta = tuple(
                thickness_change + camber_change
                for thickness_change, camber_change in zip(
                    scaled_basis(_THICKNESS_LOWER_BASIS, thickness_delta),
                    scaled_basis(_CAMBER_LOWER_BASIS, camber_delta),
                    strict=True,
                )
            )
            candidates.append(
                CSTAirfoilTemplate(
                    zone_name=template.zone_name,
                    upper_coefficients=offset(template.upper_coefficients, upper_delta),
                    lower_coefficients=offset(template.lower_coefficients, lower_delta),
                    te_thickness_m=template.te_thickness_m,
                    seed_name=template.seed_name,
                    candidate_role=candidate_role(
                        thickness_delta,
                        camber_delta,
                        thickness_index=thickness_index,
                        camber_index=camber_index,
                    ),
                    thickness_delta=float(thickness_delta),
                    camber_delta=float(camber_delta),
                    thickness_index=thickness_index,
                    camber_index=camber_index,
                )
            )

    base_index = next(
        index for index, candidate in enumerate(candidates) if candidate.candidate_role == "base"
    )
    base_candidate = candidates.pop(base_index)
    all_roles = {base_candidate.candidate_role, *(candidate.candidate_role for candidate in candidates)}
    if len(all_roles) != len(candidates) + 1:
        raise ValueError("bounded CST candidate roles must be unique.")
    return (base_candidate, *candidates)


def build_lofting_guides(templates: Mapping[str, CSTAirfoilTemplate]) -> dict[str, object]:
    if not templates:
        raise ValueError("templates must not be empty.")

    for key, template in templates.items():
        if key != template.zone_name:
            raise ValueError("template mapping keys must match template.zone_name.")

    unknown_names = set(templates) - set(_CANONICAL_ZONE_ORDER)
    if unknown_names:
        raise ValueError("templates contain unsupported zone names.")

    zone_names = [zone_name for zone_name in _CANONICAL_ZONE_ORDER if zone_name in templates]

    for left_name, right_name in zip(zone_names[:-1], zone_names[1:]):
        left_template = templates[left_name]
        right_template = templates[right_name]
        if len(left_template.upper_coefficients) != len(right_template.upper_coefficients):
            raise ValueError("adjacent templates must have the same upper coefficient count.")
        if len(left_template.lower_coefficients) != len(right_template.lower_coefficients):
            raise ValueError("adjacent templates must have the same lower coefficient count.")

    blend_pairs = list(zip(zone_names[:-1], zone_names[1:]))
    return {
        "authority": "cst_coefficients",
        "zones": zone_names,
        "blend_pairs": blend_pairs,
        "interpolation_rule": "linear_in_coeff_space",
    }
