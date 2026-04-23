from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
from math import comb, cos, pi
from typing import Mapping


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
