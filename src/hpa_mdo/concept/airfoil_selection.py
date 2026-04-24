from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Literal, Mapping

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    DEFAULT_CAMBER_DELTA_LEVELS,
    DEFAULT_THICKNESS_DELTA_LEVELS,
    SeedlessCSTCoefficientBounds,
    SeedlessCSTConstraints,
    build_bounded_candidate_family,
    generate_cst_coordinates,
    sample_feasible_seedless_cst_sobol,
    validate_cst_candidate_coordinates,
)
from hpa_mdo.concept.airfoil_nsga import generate_seedless_nsga2_offspring
from hpa_mdo.concept.airfoil_pareto import AirfoilParetoCandidate, select_nsga2_survivors
from hpa_mdo.concept.airfoil_worker import PolarQuery, geometry_hash_from_coordinates
from hpa_mdo.concept.stall_model import compute_safe_local_clmax


_BASE_TEMPLATE_LIBRARY: dict[str, dict[str, object]] = {
    "fx76mp140": {
        "upper_coefficients": (0.22, 0.28, 0.18, 0.10, 0.04),
        "lower_coefficients": (-0.18, -0.14, -0.08, -0.03, -0.01),
        "default_te_thickness_m": 0.0015,
    },
    "clarkysm": {
        "upper_coefficients": (0.18, 0.20, 0.12, 0.05, 0.02),
        "lower_coefficients": (-0.12, -0.10, -0.05, -0.02, -0.005),
        "default_te_thickness_m": 0.0010,
    },
}

_ROOT_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(
    upper_min=(0.18, 0.26, 0.25, 0.18, 0.11, 0.05, 0.015),
    upper_max=(0.22, 0.32, 0.30, 0.22, 0.13, 0.07, 0.025),
    lower_min=(-0.14, -0.18, -0.15, -0.11, -0.06, -0.03, -0.010),
    lower_max=(-0.10, -0.14, -0.13, -0.09, -0.04, -0.015, -0.002),
    te_thickness_min=0.0015,
    te_thickness_max=0.0025,
)

_OUTBOARD_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(
    upper_min=(0.14, 0.20, 0.18, 0.13, 0.08, 0.04, 0.012),
    upper_max=(0.20, 0.30, 0.27, 0.20, 0.12, 0.07, 0.024),
    lower_min=(-0.13, -0.16, -0.14, -0.10, -0.05, -0.025, -0.009),
    lower_max=(-0.08, -0.11, -0.09, -0.06, -0.025, -0.010, -0.002),
    te_thickness_min=0.0012,
    te_thickness_max=0.0025,
)


@dataclass(frozen=True)
class SelectedZoneCandidate:
    template: CSTAirfoilTemplate
    coordinates: tuple[tuple[float, float], ...]
    mean_cd: float
    mean_cm: float
    usable_clmax: float
    safe_clmax: float
    candidate_score: float


@dataclass(frozen=True)
class ZoneSelectionBatch:
    selected_by_zone: dict[str, SelectedZoneCandidate]
    worker_results: list[dict[str, object]]


def _concept_zone_batch_key(*, concept_id: str, zone_name: str) -> str:
    return f"{concept_id}__{zone_name}"


def _split_concept_zone_batch_key(batch_key: str) -> tuple[str, str]:
    concept_id, zone_name = batch_key.split("__", 1)
    return concept_id, zone_name


def _bounded_penalty(deficit: float, scale: float) -> float:
    if deficit <= 0.0:
        return 0.0
    scale = max(float(scale), 1.0e-9)
    return min(deficit / scale, 1.0)


def _numeric_value(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _surface_y(surface: tuple[tuple[float, float], ...], x: float) -> float:
    if len(surface) == 1:
        return float(surface[0][1])

    xs = [float(point[0]) for point in surface]
    ys = [float(point[1]) for point in surface]
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]

    for index in range(1, len(xs)):
        if xs[index] >= x:
            x0 = xs[index - 1]
            x1 = xs[index]
            y0 = ys[index - 1]
            y1 = ys[index]
            if x1 == x0:
                return y0
            fraction = (x - x0) / (x1 - x0)
            return y0 + fraction * (y1 - y0)
    return ys[-1]


def _candidate_thickness_ratio(coordinates: tuple[tuple[float, float], ...]) -> float:
    if len(coordinates) < 5:
        return 0.0

    leading_edge_index = min(range(len(coordinates)), key=lambda index: float(coordinates[index][0]))
    if leading_edge_index <= 0 or leading_edge_index >= len(coordinates) - 1:
        return 0.0

    upper_surface = tuple(sorted(coordinates[: leading_edge_index + 1], key=lambda point: float(point[0])))
    lower_surface = tuple(sorted(coordinates[leading_edge_index:], key=lambda point: float(point[0])))

    thickness_ratio = 0.0
    for index in range(80):
        x = 0.02 + 0.96 * index / 79.0
        thickness_ratio = max(
            thickness_ratio,
            _surface_y(upper_surface, x) - _surface_y(lower_surface, x),
        )
    return thickness_ratio


def _candidate_depth_ratio_at_x(
    coordinates: tuple[tuple[float, float], ...],
    *,
    x_ratio: float,
) -> float:
    if len(coordinates) < 5:
        return 0.0

    leading_edge_index = min(range(len(coordinates)), key=lambda index: float(coordinates[index][0]))
    if leading_edge_index <= 0 or leading_edge_index >= len(coordinates) - 1:
        return 0.0

    upper_surface = tuple(sorted(coordinates[: leading_edge_index + 1], key=lambda point: float(point[0])))
    lower_surface = tuple(sorted(coordinates[leading_edge_index:], key=lambda point: float(point[0])))
    x_ratio = min(max(float(x_ratio), 0.0), 1.0)
    return max(0.0, _surface_y(upper_surface, x_ratio) - _surface_y(lower_surface, x_ratio))


def _safe_clmax(
    usable_clmax: float,
    *,
    safe_scale: float,
    safe_delta: float,
) -> float:
    return max(0.10, float(safe_scale) * float(usable_clmax) - float(safe_delta))


def _case_stall_utilization_limit(
    case_label: str,
    *,
    launch_stall_utilization_limit: float,
    turn_stall_utilization_limit: float,
    local_stall_utilization_limit: float,
) -> float:
    if case_label == "launch_release_case":
        return float(launch_stall_utilization_limit)
    if case_label == "turn_avl_case":
        return float(turn_stall_utilization_limit)
    return float(local_stall_utilization_limit)


def _zone_candidate_metrics(
    *,
    zone_points: list[dict[str, float]],
    mean_cd: float,
    mean_cm: float,
    usable_clmax: float,
    zone_min_tc_ratio: float,
    coordinates: tuple[tuple[float, float], ...] | None,
    polar_points: list[dict[str, float]] | None,
    safe_clmax_scale: float,
    safe_clmax_delta: float,
    tip_3d_penalty_start_eta: float,
    tip_3d_penalty_max: float,
    tip_taper_penalty_weight: float,
    washout_relief_deg: float,
    washout_relief_max: float,
    launch_stall_utilization_limit: float,
    turn_stall_utilization_limit: float,
    local_stall_utilization_limit: float,
) -> dict[str, float | str]:
    zone_stats = _weighted_zone_point_values(zone_points)
    weights = list(zone_stats["weights"]) or [1.0 for _ in zone_points]
    chords = list(zone_stats["chords"]) or [1.0 for _ in zone_points]
    weight_sum = max(float(zone_stats["weight_sum"]) or 0.0, 1.0e-9)
    chord_reference = max(float(zone_stats["chord_reference"]) or 0.0, 1.0e-9)

    normalized_polar_points = _normalize_polar_points(polar_points)
    matched_polar_points = _matched_worker_polar_points(zone_points, normalized_polar_points)

    if matched_polar_points:
        profile_drag_area = sum(
            weight * chord * float(point["cd"])
            for point, weight, chord in zip(matched_polar_points, weights, chords, strict=True)
        ) / weight_sum
        trim_moment_proxy = sum(
            weight * chord**2 * abs(float(point["cm"]))
            for point, weight, chord in zip(matched_polar_points, weights, chords, strict=True)
        ) / max(sum(weight * chord**2 for weight, chord in zip(weights, chords, strict=True)), 1.0e-9)
    else:
        profile_drag_area = sum(weight * chord for weight, chord in zip(weights, chords, strict=True)) / weight_sum
        profile_drag_area *= float(mean_cd)
        trim_moment_proxy = abs(float(mean_cm))

    profile_power_proxy = profile_drag_area / chord_reference
    point_safe_clmax_values: list[float] = []
    point_stall_utilizations: list[float] = []
    weighted_stall_violation = 0.0
    worst_case_margin = float("inf")
    worst_case_label = "reference_avl_case"
    worst_case_limit = float(local_stall_utilization_limit)
    worst_case_stall_utilization = 0.0
    for point, weight in zip(zone_points, weights, strict=True):
        case_label = str(point.get("case_label", "reference_avl_case"))
        case_limit = _case_stall_utilization_limit(
            case_label,
            launch_stall_utilization_limit=launch_stall_utilization_limit,
            turn_stall_utilization_limit=turn_stall_utilization_limit,
            local_stall_utilization_limit=local_stall_utilization_limit,
        )
        safe_result = compute_safe_local_clmax(
            raw_clmax=float(usable_clmax),
            raw_source="airfoil_observed",
            span_fraction=float(point.get("span_fraction", 0.5)),
            taper_ratio=float(point.get("taper_ratio", 0.35)),
            washout_deg=float(point.get("washout_deg", 0.0)),
            safe_scale=float(safe_clmax_scale),
            safe_delta=float(safe_clmax_delta),
            tip_3d_penalty_start_eta=float(tip_3d_penalty_start_eta),
            tip_3d_penalty_max=float(tip_3d_penalty_max),
            tip_taper_penalty_weight=float(tip_taper_penalty_weight),
            washout_relief_deg=float(washout_relief_deg),
            washout_relief_max=float(washout_relief_max),
        )
        safe_clmax_point = float(safe_result.safe_clmax)
        stall_utilization_point = float(point["cl_target"]) / max(safe_clmax_point, 1.0e-9)
        point_safe_clmax_values.append(safe_clmax_point)
        point_stall_utilizations.append(stall_utilization_point)
        weighted_stall_violation += float(weight) * max(0.0, stall_utilization_point - case_limit)
        case_margin = case_limit - stall_utilization_point
        if case_margin < worst_case_margin:
            worst_case_margin = case_margin
            worst_case_label = case_label
            worst_case_limit = case_limit
            worst_case_stall_utilization = stall_utilization_point

    safe_clmax = min(point_safe_clmax_values) if point_safe_clmax_values else _safe_clmax(
        usable_clmax,
        safe_scale=safe_clmax_scale,
        safe_delta=safe_clmax_delta,
    )
    stall_utilization = max(point_stall_utilizations) if point_stall_utilizations else 0.0
    weighted_stall_violation = weighted_stall_violation / weight_sum

    candidate_thickness_ratio = (
        _candidate_thickness_ratio(coordinates)
        if coordinates is not None
        else max(zone_min_tc_ratio, 0.12)
    )
    spar_depth_ratio = (
        _candidate_depth_ratio_at_x(coordinates, x_ratio=0.30)
        if coordinates is not None
        else max(0.75 * zone_min_tc_ratio, 0.08)
    )
    required_spar_depth_ratio = max(0.06, 0.75 * float(zone_min_tc_ratio))

    return {
        "profile_power_proxy": profile_power_proxy,
        "trim_moment_proxy": trim_moment_proxy,
        "safe_clmax": safe_clmax,
        "stall_utilization": stall_utilization,
        "weighted_stall_violation": weighted_stall_violation,
        "worst_case_margin": worst_case_margin,
        "worst_case_label": worst_case_label,
        "worst_case_limit": worst_case_limit,
        "worst_case_stall_utilization": worst_case_stall_utilization,
        "candidate_thickness_ratio": candidate_thickness_ratio,
        "spar_depth_ratio": spar_depth_ratio,
        "required_spar_depth_ratio": required_spar_depth_ratio,
    }


def _weighted_zone_point_values(
    zone_points: list[dict[str, float]],
) -> dict[str, object]:
    if not zone_points:
        return {
            "weight_sum": 0.0,
            "chord_reference": 1.0,
            "weighted_chord_factor": 1.0,
            "weighted_cl_target": 0.0,
            "weighted_cm_target": 0.0,
            "cl_spread": 0.0,
            "cm_rms": 0.0,
            "max_cl_target": 0.0,
            "weights": (),
            "chords": (),
            "chord_factors": (),
            "effective_weights": (),
        }

    weights = [max(float(point.get("weight", 1.0)), 0.0) for point in zone_points]
    chords = [max(float(point.get("chord_m", 1.0)), 1.0e-9) for point in zone_points]
    weight_sum = sum(weights)
    if weight_sum <= 0.0:
        weights = [1.0 for _ in zone_points]
        weight_sum = float(len(zone_points))

    chord_reference = max(max(chords), sum(weight * chord for weight, chord in zip(weights, chords, strict=True)) / weight_sum)
    chord_factors = [chord / chord_reference for chord in chords]
    effective_weights = [weight * chord_factor for weight, chord_factor in zip(weights, chord_factors, strict=True)]
    effective_weight_sum = sum(effective_weights)
    if effective_weight_sum <= 0.0:
        effective_weights = [1.0 for _ in zone_points]
        effective_weight_sum = float(len(zone_points))

    weighted_cl_target = sum(
        weight * float(point["cl_target"])
        for point, weight in zip(zone_points, effective_weights, strict=True)
    ) / effective_weight_sum
    weighted_cm_target = sum(
        weight * float(point["cm_target"])
        for point, weight in zip(zone_points, effective_weights, strict=True)
    ) / effective_weight_sum
    cl_spread = math.sqrt(
        sum(
            weight * (float(point["cl_target"]) - weighted_cl_target) ** 2
            for point, weight in zip(zone_points, effective_weights, strict=True)
        )
        / effective_weight_sum
    )
    cm_rms = math.sqrt(
        sum(
            weight * (float(point["cm_target"]) - weighted_cm_target) ** 2
            for point, weight in zip(zone_points, effective_weights, strict=True)
        )
        / effective_weight_sum
    )
    weighted_chord_factor = sum(
        weight * chord_factor
        for weight, chord_factor in zip(weights, chord_factors, strict=True)
    ) / weight_sum
    max_cl_target = max(float(point["cl_target"]) for point in zone_points)
    return {
        "weight_sum": weight_sum,
        "chord_reference": chord_reference,
        "weighted_chord_factor": weighted_chord_factor,
        "weighted_cl_target": weighted_cl_target,
        "weighted_cm_target": weighted_cm_target,
        "cl_spread": cl_spread,
        "cm_rms": cm_rms,
        "max_cl_target": max_cl_target,
        "weights": tuple(weights),
        "chords": tuple(chords),
        "chord_factors": tuple(chord_factors),
        "effective_weights": tuple(effective_weights),
    }


def _normalize_polar_points(
    polar_points: object,
) -> list[dict[str, float]]:
    if not isinstance(polar_points, list):
        return []

    normalized: list[dict[str, float]] = []
    for point in polar_points:
        if not isinstance(point, Mapping):
            continue
        cl_value = _numeric_value(point.get("cl"))
        cd_value = _numeric_value(point.get("cd"))
        cm_value = _numeric_value(point.get("cm"))
        if cl_value is None or cd_value is None or cm_value is None:
            continue
        normalized.append(
            {
                "cl": float(cl_value),
                "cd": float(cd_value),
                "cm": float(cm_value),
                "cl_target": float(_numeric_value(point.get("cl_target")) or cl_value),
            }
        )
    return normalized


def _matched_worker_polar_points(
    zone_points: list[dict[str, float]],
    polar_points: list[dict[str, float]],
) -> list[dict[str, float]]:
    if not zone_points or not polar_points:
        return []

    matched_points: list[dict[str, float]] = []
    for zone_point in zone_points:
        cl_target = float(zone_point["cl_target"])
        matched_point = min(
            polar_points,
            key=lambda point: abs(float(point.get("cl_target", point["cl"])) - cl_target),
        )
        matched_points.append(matched_point)
    return matched_points


def build_base_cst_template(
    *,
    zone_name: str,
    seed_name: str,
    seed_coordinates: tuple[tuple[float, float], ...],
) -> CSTAirfoilTemplate:
    base_template = _BASE_TEMPLATE_LIBRARY.get(seed_name)
    if base_template is None:
        raise ValueError(f"Unsupported seed airfoil for Phase 1 CST template: {seed_name!r}")
    if len(seed_coordinates) < 3:
        raise ValueError("seed_coordinates must contain at least three points.")

    trailing_edge_gap = abs(float(seed_coordinates[0][1]) - float(seed_coordinates[-1][1]))
    te_thickness_m = max(
        float(base_template["default_te_thickness_m"]),
        trailing_edge_gap,
    )

    return CSTAirfoilTemplate(
        zone_name=zone_name,
        upper_coefficients=tuple(base_template["upper_coefficients"]),
        lower_coefficients=tuple(base_template["lower_coefficients"]),
        te_thickness_m=te_thickness_m,
        seed_name=seed_name,
        candidate_role="base",
    )


def score_zone_candidate(
    *,
    zone_points: list[dict[str, float]],
    mean_cd: float,
    mean_cm: float,
    usable_clmax: float,
    zone_min_tc_ratio: float = 0.10,
    coordinates: tuple[tuple[float, float], ...] | None = None,
    polar_points: list[dict[str, float]] | None = None,
    safe_clmax_scale: float = 0.90,
    safe_clmax_delta: float = 0.05,
    stall_utilization_limit: float = 0.80,
    tip_3d_penalty_start_eta: float = 0.55,
    tip_3d_penalty_max: float = 0.04,
    tip_taper_penalty_weight: float = 0.35,
    washout_relief_deg: float = 2.0,
    washout_relief_max: float = 0.02,
    launch_stall_utilization_limit: float | None = None,
    turn_stall_utilization_limit: float | None = None,
    local_stall_utilization_limit: float | None = None,
) -> float:
    local_stall_utilization_limit = (
        float(stall_utilization_limit)
        if local_stall_utilization_limit is None
        else float(local_stall_utilization_limit)
    )
    launch_stall_utilization_limit = (
        local_stall_utilization_limit
        if launch_stall_utilization_limit is None
        else float(launch_stall_utilization_limit)
    )
    turn_stall_utilization_limit = (
        local_stall_utilization_limit
        if turn_stall_utilization_limit is None
        else float(turn_stall_utilization_limit)
    )
    metrics = _zone_candidate_metrics(
        zone_points=zone_points,
        mean_cd=mean_cd,
        mean_cm=mean_cm,
        usable_clmax=usable_clmax,
        zone_min_tc_ratio=zone_min_tc_ratio,
        coordinates=coordinates,
        polar_points=polar_points,
        safe_clmax_scale=safe_clmax_scale,
        safe_clmax_delta=safe_clmax_delta,
        tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
        tip_3d_penalty_max=tip_3d_penalty_max,
        tip_taper_penalty_weight=tip_taper_penalty_weight,
        washout_relief_deg=washout_relief_deg,
        washout_relief_max=washout_relief_max,
        launch_stall_utilization_limit=launch_stall_utilization_limit,
        turn_stall_utilization_limit=turn_stall_utilization_limit,
        local_stall_utilization_limit=local_stall_utilization_limit,
    )

    drag_penalty = _bounded_penalty(float(metrics["profile_power_proxy"]), 0.022)
    trim_penalty = _bounded_penalty(float(metrics["trim_moment_proxy"]), 0.11)
    stall_violation = max(0.0, -float(metrics["worst_case_margin"]))
    weighted_stall_violation = max(0.0, float(metrics["weighted_stall_violation"]))
    stall_penalty = _bounded_penalty(max(stall_violation, weighted_stall_violation), 0.08)
    margin_deficit = max(0.0, 0.08 - float(metrics["worst_case_margin"]))
    margin_penalty = _bounded_penalty(margin_deficit, 0.06)

    thickness_deficit = max(
        0.0,
        float(zone_min_tc_ratio) - float(metrics["candidate_thickness_ratio"]),
    )
    thickness_penalty = _bounded_penalty(
        thickness_deficit,
        max(0.01, 0.20 * float(zone_min_tc_ratio)),
    )

    spar_depth_deficit = max(
        0.0,
        float(metrics["required_spar_depth_ratio"]) - float(metrics["spar_depth_ratio"]),
    )
    spar_penalty = _bounded_penalty(
        spar_depth_deficit,
        max(0.008, 0.15 * float(metrics["required_spar_depth_ratio"])),
    )

    infeasible_guard = 0.0
    if stall_violation > 0.0:
        infeasible_guard += 1.4 + 2.5 * stall_penalty
    if thickness_deficit > 0.0 or spar_depth_deficit > 0.0:
        infeasible_guard += 0.8 + 1.5 * max(thickness_penalty, spar_penalty)

    return (
        1.50 * drag_penalty
        + 4.25 * stall_penalty
        + 2.25 * margin_penalty
        + 1.25 * trim_penalty
        + 3.00 * spar_penalty
        + 2.50 * thickness_penalty
        + infeasible_guard
    )


def select_best_zone_candidate(
    candidates: tuple[CSTAirfoilTemplate, ...],
    zone_points: list[dict[str, float]],
    candidate_results: Mapping[str, Mapping[str, object]],
    *,
    zone_min_tc_ratio: float = 0.10,
    safe_clmax_scale: float = 0.90,
    safe_clmax_delta: float = 0.05,
    stall_utilization_limit: float = 0.80,
    tip_3d_penalty_start_eta: float = 0.55,
    tip_3d_penalty_max: float = 0.04,
    tip_taper_penalty_weight: float = 0.35,
    washout_relief_deg: float = 2.0,
    washout_relief_max: float = 0.02,
    launch_stall_utilization_limit: float | None = None,
    turn_stall_utilization_limit: float | None = None,
    local_stall_utilization_limit: float | None = None,
) -> SelectedZoneCandidate:
    local_stall_utilization_limit = (
        float(stall_utilization_limit)
        if local_stall_utilization_limit is None
        else float(local_stall_utilization_limit)
    )
    launch_stall_utilization_limit = (
        local_stall_utilization_limit
        if launch_stall_utilization_limit is None
        else float(launch_stall_utilization_limit)
    )
    turn_stall_utilization_limit = (
        local_stall_utilization_limit
        if turn_stall_utilization_limit is None
        else float(turn_stall_utilization_limit)
    )
    scored: list[tuple[int, SelectedZoneCandidate]] = []
    for candidate in candidates:
        coordinates = generate_cst_coordinates(candidate)
        validity = validate_cst_candidate_coordinates(coordinates)
        if not validity.valid:
            continue

        result = candidate_results.get(candidate.candidate_role)
        if result is None:
            continue
        status = str(result.get("status", "unknown"))
        if status not in {"ok", "stubbed_ok", "mini_sweep_fallback"}:
            continue

        mean_cd = float(result["mean_cd"])
        mean_cm = float(result["mean_cm"])
        usable_clmax = float(result["usable_clmax"])
        polar_points = result.get("polar_points")
        metrics = _zone_candidate_metrics(
            zone_points=zone_points,
            mean_cd=mean_cd,
            mean_cm=mean_cm,
            usable_clmax=usable_clmax,
            zone_min_tc_ratio=zone_min_tc_ratio,
            coordinates=coordinates,
            polar_points=polar_points if isinstance(polar_points, list) else None,
            safe_clmax_scale=safe_clmax_scale,
            safe_clmax_delta=safe_clmax_delta,
            tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
            tip_3d_penalty_max=tip_3d_penalty_max,
            tip_taper_penalty_weight=tip_taper_penalty_weight,
            washout_relief_deg=washout_relief_deg,
            washout_relief_max=washout_relief_max,
            launch_stall_utilization_limit=launch_stall_utilization_limit,
            turn_stall_utilization_limit=turn_stall_utilization_limit,
            local_stall_utilization_limit=local_stall_utilization_limit,
        )
        candidate_score = score_zone_candidate(
            zone_points=zone_points,
            mean_cd=mean_cd,
            mean_cm=mean_cm,
            usable_clmax=usable_clmax,
            zone_min_tc_ratio=zone_min_tc_ratio,
            coordinates=coordinates,
            polar_points=polar_points if isinstance(polar_points, list) else None,
            safe_clmax_scale=safe_clmax_scale,
            safe_clmax_delta=safe_clmax_delta,
            stall_utilization_limit=stall_utilization_limit,
            tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
            tip_3d_penalty_max=tip_3d_penalty_max,
            tip_taper_penalty_weight=tip_taper_penalty_weight,
            washout_relief_deg=washout_relief_deg,
            washout_relief_max=washout_relief_max,
            launch_stall_utilization_limit=launch_stall_utilization_limit,
            turn_stall_utilization_limit=turn_stall_utilization_limit,
            local_stall_utilization_limit=local_stall_utilization_limit,
        )
        thickness_ratio = float(metrics["candidate_thickness_ratio"])
        spar_depth_ratio = float(metrics["spar_depth_ratio"])
        required_spar_depth_ratio = float(metrics["required_spar_depth_ratio"])
        safe_clmax = float(metrics["safe_clmax"])
        worst_case_margin = float(metrics["worst_case_margin"])
        feasible = (
            safe_clmax >= 0.0
            and worst_case_margin >= 0.0
            and thickness_ratio >= float(zone_min_tc_ratio)
            and spar_depth_ratio >= required_spar_depth_ratio
        )
        scored.append(
            (
                0 if feasible else 1,
                SelectedZoneCandidate(
                    template=candidate,
                    coordinates=coordinates,
                    mean_cd=mean_cd,
                    mean_cm=mean_cm,
                    usable_clmax=usable_clmax,
                    safe_clmax=safe_clmax,
                    candidate_score=candidate_score,
                ),
            )
        )

    if not scored:
        raise ValueError("No valid CST zone candidates were available for selection.")

    return min(scored, key=lambda item: (item[0], item[1].candidate_score, item[1].usable_clmax))[1]


def _default_seed_name(zone_name: str) -> str:
    return "fx76mp140" if zone_name in {"root", "mid1"} else "clarkysm"


def _default_seedless_cst_bounds(zone_name: str) -> SeedlessCSTCoefficientBounds:
    return _ROOT_SEEDLESS_CST_BOUNDS if zone_name in {"root", "mid1"} else _OUTBOARD_SEEDLESS_CST_BOUNDS


def _seedless_constraints_for_zone(zone_min_tc_ratio: float) -> SeedlessCSTConstraints:
    min_tc_ratio = float(zone_min_tc_ratio)
    return SeedlessCSTConstraints(
        min_thickness_ratio=min_tc_ratio,
        max_thickness_ratio=max(0.16, min_tc_ratio + 0.02),
        max_thickness_x_min=0.25,
        max_thickness_x_max=0.45,
        min_spar_depth_ratio_25_35=max(0.09, 0.75 * min_tc_ratio),
    )


def _seedless_zone_candidates(
    *,
    zone_name: str,
    zone_min_tc_ratio: float,
    sample_count: int,
    random_seed: int | None,
    max_oversample_factor: int,
) -> tuple[CSTAirfoilTemplate, ...]:
    return sample_feasible_seedless_cst_sobol(
        zone_name=zone_name,
        sample_count=sample_count,
        bounds=_default_seedless_cst_bounds(zone_name),
        constraints=_seedless_constraints_for_zone(zone_min_tc_ratio),
        random_seed=random_seed,
        max_oversample_factor=max_oversample_factor,
    )


def _prepare_zone_selection_inputs(
    *,
    zone_requirements: Mapping[str, dict[str, object]],
    seed_loader: Callable[[str], tuple[tuple[float, float], ...]],
    thickness_delta_levels: tuple[float, ...],
    camber_delta_levels: tuple[float, ...],
    coarse_to_fine_enabled: bool,
    coarse_thickness_stride: int,
    coarse_camber_stride: int,
    search_mode: Literal["seed_neighborhood", "seedless_sobol"],
    seedless_sample_count: int,
    seedless_random_seed: int | None,
    seedless_max_oversample_factor: int,
) -> tuple[
    dict[str, list[dict[str, float]]],
    dict[str, float],
    dict[str, tuple[CSTAirfoilTemplate, ...]],
    dict[str, tuple[CSTAirfoilTemplate, ...]],
]:
    zone_points_by_name: dict[str, list[dict[str, float]]] = {}
    zone_min_tc_by_name: dict[str, float] = {}
    candidates_by_zone: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
    coarse_candidates_by_zone: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}

    for zone_name, zone_data in zone_requirements.items():
        zone_points = list(zone_data.get("points", []))
        zone_min_tc_ratio = float(zone_data.get("min_tc_ratio", 0.10))
        if search_mode == "seed_neighborhood":
            seed_name = _default_seed_name(zone_name)
            base_template = build_base_cst_template(
                zone_name=zone_name,
                seed_name=seed_name,
                seed_coordinates=seed_loader(seed_name),
            )
            candidates = build_bounded_candidate_family(
                base_template,
                thickness_delta_levels=thickness_delta_levels,
                camber_delta_levels=camber_delta_levels,
            )
        elif search_mode == "seedless_sobol":
            candidates = _seedless_zone_candidates(
                zone_name=zone_name,
                zone_min_tc_ratio=zone_min_tc_ratio,
                sample_count=seedless_sample_count,
                random_seed=seedless_random_seed,
                max_oversample_factor=seedless_max_oversample_factor,
            )
        else:
            raise ValueError(f"Unsupported CST search mode: {search_mode!r}")
        candidates = _prescreen_zone_candidates(
            candidates,
            zone_points=zone_points,
            zone_min_tc_ratio=zone_min_tc_ratio,
        )
        if not candidates:
            raise ValueError(f"Zone {zone_name!r} did not produce any valid CST candidates.")

        zone_points_by_name[zone_name] = zone_points
        zone_min_tc_by_name[zone_name] = zone_min_tc_ratio
        candidates_by_zone[zone_name] = candidates
        coarse_candidates_by_zone[zone_name] = (
            _coarse_seed_candidates(
                candidates,
                thickness_stride=coarse_thickness_stride,
                camber_stride=coarse_camber_stride,
            )
            if coarse_to_fine_enabled
            else candidates
        )
    return (
        zone_points_by_name,
        zone_min_tc_by_name,
        candidates_by_zone,
        coarse_candidates_by_zone,
    )


def _prescreen_zone_candidates(
    candidates: tuple[CSTAirfoilTemplate, ...],
    *,
    zone_points: list[dict[str, float]],
    zone_min_tc_ratio: float,
) -> tuple[CSTAirfoilTemplate, ...]:
    if not candidates:
        return ()

    required_spar_depth_ratio = max(0.06, 0.75 * float(zone_min_tc_ratio))
    prescreened: list[CSTAirfoilTemplate] = []
    valid_fallback: list[CSTAirfoilTemplate] = []

    for candidate in candidates:
        coordinates = generate_cst_coordinates(candidate)
        validity = validate_cst_candidate_coordinates(coordinates)
        if not validity.valid:
            continue
        valid_fallback.append(candidate)

        thickness_ratio = _candidate_thickness_ratio(coordinates)
        spar_depth_ratio = _candidate_depth_ratio_at_x(coordinates, x_ratio=0.30)
        if thickness_ratio < float(zone_min_tc_ratio):
            continue
        if spar_depth_ratio < required_spar_depth_ratio:
            continue
        prescreened.append(candidate)

    if prescreened:
        return tuple(prescreened)
    return tuple(valid_fallback)


def _is_anchor_candidate(candidate: CSTAirfoilTemplate) -> bool:
    return candidate.candidate_role in {
        "base",
        "thickness_up",
        "thickness_down",
        "camber_up",
        "camber_down",
    }


def _coarse_seed_candidates(
    candidates: tuple[CSTAirfoilTemplate, ...],
    *,
    thickness_stride: int,
    camber_stride: int,
) -> tuple[CSTAirfoilTemplate, ...]:
    if not candidates:
        return ()

    selected: list[CSTAirfoilTemplate] = []
    seen_roles: set[str] = set()
    for candidate in candidates:
        include = False
        if _is_anchor_candidate(candidate):
            include = True
        elif candidate.thickness_index is not None and candidate.camber_index is not None:
            include = (
                candidate.thickness_index % max(1, int(thickness_stride)) == 0
                and candidate.camber_index % max(1, int(camber_stride)) == 0
            )
        if include and candidate.candidate_role not in seen_roles:
            selected.append(candidate)
            seen_roles.add(candidate.candidate_role)
    return tuple(selected) if selected else candidates


def _score_available_zone_candidates(
    candidates: tuple[CSTAirfoilTemplate, ...],
    *,
    zone_points: list[dict[str, float]],
    candidate_results: Mapping[str, Mapping[str, object]],
    zone_min_tc_ratio: float,
    safe_clmax_scale: float,
    safe_clmax_delta: float,
    stall_utilization_limit: float,
    tip_3d_penalty_start_eta: float,
    tip_3d_penalty_max: float,
    tip_taper_penalty_weight: float,
    washout_relief_deg: float,
    washout_relief_max: float,
    launch_stall_utilization_limit: float,
    turn_stall_utilization_limit: float,
    local_stall_utilization_limit: float,
) -> list[tuple[int, float, float, CSTAirfoilTemplate]]:
    scored: list[tuple[int, float, float, CSTAirfoilTemplate]] = []
    for candidate in candidates:
        result = candidate_results.get(candidate.candidate_role)
        if result is None:
            continue
        status = str(result.get("status", "unknown"))
        if status not in {"ok", "stubbed_ok", "mini_sweep_fallback"}:
            continue

        coordinates = generate_cst_coordinates(candidate)
        validity = validate_cst_candidate_coordinates(coordinates)
        if not validity.valid:
            continue

        mean_cd = float(result["mean_cd"])
        mean_cm = float(result["mean_cm"])
        usable_clmax = float(result["usable_clmax"])
        polar_points = result.get("polar_points")
        metrics = _zone_candidate_metrics(
            zone_points=zone_points,
            mean_cd=mean_cd,
            mean_cm=mean_cm,
            usable_clmax=usable_clmax,
            zone_min_tc_ratio=zone_min_tc_ratio,
            coordinates=coordinates,
            polar_points=polar_points if isinstance(polar_points, list) else None,
            safe_clmax_scale=safe_clmax_scale,
            safe_clmax_delta=safe_clmax_delta,
            tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
            tip_3d_penalty_max=tip_3d_penalty_max,
            tip_taper_penalty_weight=tip_taper_penalty_weight,
            washout_relief_deg=washout_relief_deg,
            washout_relief_max=washout_relief_max,
            launch_stall_utilization_limit=launch_stall_utilization_limit,
            turn_stall_utilization_limit=turn_stall_utilization_limit,
            local_stall_utilization_limit=local_stall_utilization_limit,
        )
        candidate_score = score_zone_candidate(
            zone_points=zone_points,
            mean_cd=mean_cd,
            mean_cm=mean_cm,
            usable_clmax=usable_clmax,
            zone_min_tc_ratio=zone_min_tc_ratio,
            coordinates=coordinates,
            polar_points=polar_points if isinstance(polar_points, list) else None,
            safe_clmax_scale=safe_clmax_scale,
            safe_clmax_delta=safe_clmax_delta,
            stall_utilization_limit=stall_utilization_limit,
            tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
            tip_3d_penalty_max=tip_3d_penalty_max,
            tip_taper_penalty_weight=tip_taper_penalty_weight,
            washout_relief_deg=washout_relief_deg,
            washout_relief_max=washout_relief_max,
            launch_stall_utilization_limit=launch_stall_utilization_limit,
            turn_stall_utilization_limit=turn_stall_utilization_limit,
            local_stall_utilization_limit=local_stall_utilization_limit,
        )
        thickness_ratio = float(metrics["candidate_thickness_ratio"])
        spar_depth_ratio = float(metrics["spar_depth_ratio"])
        required_spar_depth_ratio = float(metrics["required_spar_depth_ratio"])
        safe_clmax = float(metrics["safe_clmax"])
        worst_case_margin = float(metrics["worst_case_margin"])
        feasible = (
            safe_clmax >= 0.0
            and worst_case_margin >= 0.0
            and thickness_ratio >= float(zone_min_tc_ratio)
            and spar_depth_ratio >= required_spar_depth_ratio
        )
        scored.append((0 if feasible else 1, candidate_score, -usable_clmax, candidate))
    return sorted(scored, key=lambda item: (item[0], item[1], item[2], item[3].candidate_role))


def _select_scored_candidate_beam(
    scored: list[tuple[int, float, float, CSTAirfoilTemplate]]
    | tuple[tuple[int, float, float, CSTAirfoilTemplate], ...],
    *,
    beam_count: int,
    selection_strategy: Literal["scalar_score", "constrained_pareto"] = "scalar_score",
) -> tuple[CSTAirfoilTemplate, ...]:
    count = max(0, int(beam_count))
    if count <= 0 or not scored:
        return ()
    if selection_strategy == "scalar_score":
        return tuple(item[3] for item in scored[:count])
    if selection_strategy != "constrained_pareto":
        raise ValueError(f"Unsupported airfoil selection strategy: {selection_strategy!r}")

    candidate_by_role = {item[3].candidate_role: item[3] for item in scored}
    pareto_candidates = tuple(
        AirfoilParetoCandidate(
            candidate_role=item[3].candidate_role,
            objectives={
                "candidate_score": float(item[1]),
                "negative_usable_clmax": float(item[2]),
            },
            constraint_violations={"hard_gate": float(item[0])},
        )
        for item in scored
    )
    return tuple(
        candidate_by_role[survivor.candidate_role]
        for survivor in select_nsga2_survivors(pareto_candidates, survivor_count=count)
    )


def _seed_for_generation(
    *,
    base_seed: int | None,
    generation_index: int,
) -> int | None:
    if base_seed is None:
        return None
    return int(base_seed) + 1009 * int(generation_index)


def _refinement_candidates(
    candidates: tuple[CSTAirfoilTemplate, ...],
    *,
    seed_candidates: tuple[CSTAirfoilTemplate, ...],
    neighbor_radius: int,
) -> tuple[CSTAirfoilTemplate, ...]:
    if not candidates or not seed_candidates:
        return candidates

    radius = max(0, int(neighbor_radius))
    selected: list[CSTAirfoilTemplate] = []
    seen_roles: set[str] = set()
    seed_index_pairs = {
        (candidate.thickness_index, candidate.camber_index)
        for candidate in seed_candidates
        if candidate.thickness_index is not None and candidate.camber_index is not None
    }

    for candidate in candidates:
        include = _is_anchor_candidate(candidate)
        if not include and candidate.thickness_index is not None and candidate.camber_index is not None:
            for thickness_index, camber_index in seed_index_pairs:
                if thickness_index is None or camber_index is None:
                    continue
                if (
                    abs(candidate.thickness_index - thickness_index) <= radius
                    and abs(candidate.camber_index - camber_index) <= radius
                ):
                    include = True
                    break
        if include and candidate.candidate_role not in seen_roles:
            selected.append(candidate)
            seen_roles.add(candidate.candidate_role)

    return tuple(selected) if selected else candidates


def _normalize_robust_reynolds_factors(
    reynolds_factors: tuple[float, ...],
) -> tuple[float, ...]:
    normalized = tuple(float(value) for value in reynolds_factors)
    if not normalized:
        raise ValueError("robust_reynolds_factors must not be empty.")
    if any(value <= 0.0 for value in normalized):
        raise ValueError("robust_reynolds_factors entries must be positive.")
    return normalized


def _normalize_robust_roughness_modes(
    roughness_modes: tuple[str, ...],
) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in roughness_modes)
    if not normalized or any(not value for value in normalized):
        raise ValueError("robust_roughness_modes must contain non-empty entries.")
    return normalized


def _robust_condition_suffix(
    *,
    reynolds_factor: float,
    roughness_mode: str,
) -> str:
    reynolds_token = f"{float(reynolds_factor):.3f}".rstrip("0").rstrip(".").replace(".", "p")
    roughness_token = str(roughness_mode).replace("-", "_")
    return f"__robust_re{reynolds_token}_{roughness_token}"


def _zone_queries_for_candidates(
    *,
    zone_name: str,
    candidates: tuple[CSTAirfoilTemplate, ...],
    zone_points: list[dict[str, float]],
    robust_evaluation_enabled: bool = False,
    robust_reynolds_factors: tuple[float, ...] = (1.0,),
    robust_roughness_modes: tuple[str, ...] = ("clean",),
) -> tuple[list[PolarQuery], list[str]]:
    queries: list[PolarQuery] = []
    query_roles: list[str] = []
    reynolds_factors = (
        _normalize_robust_reynolds_factors(robust_reynolds_factors)
        if robust_evaluation_enabled
        else (1.0,)
    )
    roughness_modes = (
        _normalize_robust_roughness_modes(robust_roughness_modes)
        if robust_evaluation_enabled
        else ("clean",)
    )
    base_reynolds = _representative_reynolds(zone_points)
    cl_samples = _representative_cl_samples(zone_points)
    for candidate in candidates:
        coordinates = generate_cst_coordinates(candidate)
        validity = validate_cst_candidate_coordinates(coordinates)
        if not validity.valid:
            continue
        for reynolds_factor in reynolds_factors:
            for roughness_mode in roughness_modes:
                template_id = f"{zone_name}-{candidate.candidate_role}"
                if robust_evaluation_enabled:
                    template_id = (
                        template_id
                        + _robust_condition_suffix(
                            reynolds_factor=reynolds_factor,
                            roughness_mode=roughness_mode,
                        )
                    )
                queries.append(
                    PolarQuery(
                        template_id=template_id,
                        reynolds=base_reynolds * float(reynolds_factor),
                        cl_samples=cl_samples,
                        roughness_mode=roughness_mode,
                        geometry_hash=geometry_hash_from_coordinates(coordinates),
                        coordinates=coordinates,
                        analysis_mode=(
                            "full_alpha_sweep"
                            if robust_evaluation_enabled
                            else "screening_target_cl"
                        ),
                        analysis_stage=(
                            "robust_screening"
                            if robust_evaluation_enabled
                            else "screening"
                        ),
                    )
                )
                query_roles.append(candidate.candidate_role)
    return queries, query_roles


def _aggregate_worker_condition_metrics(
    metrics: list[dict[str, object]],
    *,
    condition_count: int,
    min_pass_rate: float,
) -> dict[str, object] | None:
    if condition_count <= 0:
        return None
    if not metrics:
        return {
            "status": "analysis_failed",
            "mean_cd": float("inf"),
            "mean_cm": 0.0,
            "usable_clmax": 0.0,
            "polar_points": [],
            "robust_condition_count": condition_count,
            "robust_success_count": 0,
            "robust_pass_rate": 0.0,
        }

    success_count = len(metrics)
    pass_rate = float(success_count) / float(condition_count)
    mean_cd = max(float(item["mean_cd"]) for item in metrics)
    mean_cm = max((float(item["mean_cm"]) for item in metrics), key=abs)
    usable_clmax = min(float(item["usable_clmax"]) for item in metrics)
    polar_points = [
        point
        for item in metrics
        for point in item.get("polar_points", [])
        if isinstance(point, Mapping)
    ]

    return {
        "status": "ok" if pass_rate >= float(min_pass_rate) else "analysis_failed",
        "mean_cd": mean_cd,
        "mean_cm": mean_cm,
        "usable_clmax": usable_clmax,
        "polar_points": polar_points,
        "robust_condition_count": condition_count,
        "robust_success_count": success_count,
        "robust_pass_rate": pass_rate,
        "robust_min_usable_clmax": usable_clmax,
        "robust_max_mean_cd": mean_cd,
        "robust_worst_abs_cm": mean_cm,
    }


def _run_zone_candidate_queries(
    *,
    zone_name: str,
    candidates: tuple[CSTAirfoilTemplate, ...],
    zone_points: list[dict[str, float]],
    worker: Any,
    existing_results: Mapping[str, dict[str, object]] | None = None,
    robust_evaluation_enabled: bool = False,
    robust_reynolds_factors: tuple[float, ...] = (1.0,),
    robust_roughness_modes: tuple[str, ...] = ("clean",),
    robust_min_pass_rate: float = 0.75,
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    candidate_results = dict(existing_results or {})
    candidates_to_run = tuple(
        candidate for candidate in candidates if candidate.candidate_role not in candidate_results
    )
    queries, query_roles = _zone_queries_for_candidates(
        zone_name=zone_name,
        candidates=candidates_to_run,
        zone_points=zone_points,
        robust_evaluation_enabled=robust_evaluation_enabled,
        robust_reynolds_factors=robust_reynolds_factors,
        robust_roughness_modes=robust_roughness_modes,
    )
    if not queries:
        return candidate_results, []

    zone_results = worker.run_queries(queries)
    if len(zone_results) != len(queries):
        raise RuntimeError(
            f"Worker returned {len(zone_results)} results for {len(queries)} CST queries in zone {zone_name!r}."
        )

    query_identity_by_template_id = {
        query.template_id: {
            "candidate_role": candidate_role,
            "geometry_hash": query.geometry_hash,
        }
        for query, candidate_role in zip(queries, query_roles, strict=True)
    }
    seen_template_ids: set[str] = set()
    normalized_worker_results: list[dict[str, object]] = []
    metrics_by_candidate_role: dict[str, list[dict[str, object]]] = {}
    condition_count_by_candidate_role: dict[str, int] = {}
    for candidate_role in query_roles:
        condition_count_by_candidate_role[candidate_role] = (
            condition_count_by_candidate_role.get(candidate_role, 0) + 1
        )
    for raw_result in zone_results:
        if not isinstance(raw_result, dict):
            raise RuntimeError("Airfoil worker results must be dictionaries.")
        template_id = raw_result.get("template_id")
        if not isinstance(template_id, str):
            raise RuntimeError("Airfoil worker results must include a template_id.")
        query_identity = query_identity_by_template_id.get(template_id)
        if query_identity is None:
            raise RuntimeError(
                f"Airfoil worker returned an unexpected template_id {template_id!r} in zone {zone_name!r}."
            )
        candidate_role = str(query_identity["candidate_role"])
        geometry_hash = raw_result.get("geometry_hash")
        if geometry_hash is not None and geometry_hash != query_identity["geometry_hash"]:
            raise RuntimeError(
                f"Airfoil worker geometry_hash mismatch for template_id {template_id!r} in zone {zone_name!r}."
            )
        seen_template_ids.add(template_id)
        normalized_worker_results.append(
            {
                **raw_result,
                "zone_name": zone_name,
                "candidate_role": candidate_role,
            }
        )
        metrics = _metrics_from_worker_result(raw_result)
        if metrics is not None:
            metrics_by_candidate_role.setdefault(candidate_role, []).append(metrics)
    if seen_template_ids != set(query_identity_by_template_id):
        missing = sorted(set(query_identity_by_template_id) - seen_template_ids)
        raise RuntimeError(
            f"Airfoil worker did not return results for all CST queries in zone {zone_name!r}: missing {missing!r}."
        )
    for candidate_role, condition_count in condition_count_by_candidate_role.items():
        aggregated_metrics = _aggregate_worker_condition_metrics(
            metrics_by_candidate_role.get(candidate_role, []),
            condition_count=condition_count,
            min_pass_rate=robust_min_pass_rate,
        )
        if aggregated_metrics is not None:
            candidate_results[candidate_role] = aggregated_metrics
    return candidate_results, normalized_worker_results


def _run_batched_zone_candidate_queries(
    *,
    zone_candidates: Mapping[str, tuple[CSTAirfoilTemplate, ...]],
    zone_points_by_name: Mapping[str, list[dict[str, float]]],
    worker: Any,
    existing_results_by_zone: Mapping[str, Mapping[str, dict[str, object]]] | None = None,
    robust_evaluation_enabled: bool = False,
    robust_reynolds_factors: tuple[float, ...] = (1.0,),
    robust_roughness_modes: tuple[str, ...] = ("clean",),
    robust_min_pass_rate: float = 0.75,
) -> tuple[dict[str, dict[str, dict[str, object]]], list[dict[str, object]]]:
    aggregated_results: dict[str, dict[str, dict[str, object]]] = {
        zone_name: dict((existing_results_by_zone or {}).get(zone_name, {}))
        for zone_name in zone_candidates
    }
    batch_queries: list[PolarQuery] = []
    query_identity_by_template_id: dict[str, dict[str, str]] = {}
    condition_count_by_zone_role: dict[tuple[str, str], int] = {}

    for zone_name, candidates in zone_candidates.items():
        existing_zone_results = aggregated_results.setdefault(zone_name, {})
        candidates_to_run = tuple(
            candidate for candidate in candidates if candidate.candidate_role not in existing_zone_results
        )
        queries, query_roles = _zone_queries_for_candidates(
            zone_name=zone_name,
            candidates=candidates_to_run,
            zone_points=zone_points_by_name[zone_name],
            robust_evaluation_enabled=robust_evaluation_enabled,
            robust_reynolds_factors=robust_reynolds_factors,
            robust_roughness_modes=robust_roughness_modes,
        )
        for query, candidate_role in zip(queries, query_roles, strict=True):
            batch_queries.append(query)
            query_identity_by_template_id[query.template_id] = {
                "zone_name": zone_name,
                "candidate_role": candidate_role,
                "geometry_hash": query.geometry_hash,
            }
            role_key = (zone_name, candidate_role)
            condition_count_by_zone_role[role_key] = (
                condition_count_by_zone_role.get(role_key, 0) + 1
            )

    if not batch_queries:
        return aggregated_results, []

    batch_results = worker.run_queries(batch_queries)
    if len(batch_results) != len(batch_queries):
        raise RuntimeError(
            "Worker returned "
            f"{len(batch_results)} results for {len(batch_queries)} batched CST queries."
        )

    seen_template_ids: set[str] = set()
    normalized_worker_results: list[dict[str, object]] = []
    metrics_by_zone_role: dict[tuple[str, str], list[dict[str, object]]] = {}
    for raw_result in batch_results:
        if not isinstance(raw_result, dict):
            raise RuntimeError("Airfoil worker results must be dictionaries.")
        template_id = raw_result.get("template_id")
        if not isinstance(template_id, str):
            raise RuntimeError("Airfoil worker results must include a template_id.")
        query_identity = query_identity_by_template_id.get(template_id)
        if query_identity is None:
            raise RuntimeError(
                f"Airfoil worker returned an unexpected template_id {template_id!r}."
            )
        geometry_hash = raw_result.get("geometry_hash")
        if geometry_hash is not None and geometry_hash != query_identity["geometry_hash"]:
            raise RuntimeError(
                f"Airfoil worker geometry_hash mismatch for template_id {template_id!r}."
            )
        seen_template_ids.add(template_id)
        zone_name = str(query_identity["zone_name"])
        candidate_role = str(query_identity["candidate_role"])
        normalized_worker_results.append(
            {
                **raw_result,
                "zone_name": zone_name,
                "candidate_role": candidate_role,
            }
        )
        metrics = _metrics_from_worker_result(raw_result)
        if metrics is not None:
            metrics_by_zone_role.setdefault((zone_name, candidate_role), []).append(metrics)

    if seen_template_ids != set(query_identity_by_template_id):
        missing = sorted(set(query_identity_by_template_id) - seen_template_ids)
        raise RuntimeError(
            "Airfoil worker did not return results for all batched CST queries: "
            f"missing {missing!r}."
        )
    for (zone_name, candidate_role), condition_count in condition_count_by_zone_role.items():
        aggregated_metrics = _aggregate_worker_condition_metrics(
            metrics_by_zone_role.get((zone_name, candidate_role), []),
            condition_count=condition_count,
            min_pass_rate=robust_min_pass_rate,
        )
        if aggregated_metrics is not None:
            aggregated_results.setdefault(zone_name, {})[candidate_role] = aggregated_metrics
    return aggregated_results, normalized_worker_results


def _successive_halving_radius(
    *,
    round_index: int,
    total_rounds: int,
    base_radius: int,
) -> int:
    return max(0, int(base_radius) + max(int(total_rounds) - int(round_index) - 1, 0))


def _representative_reynolds(zone_points: list[dict[str, float]]) -> float:
    if not zone_points:
        return 250000.0
    total_weight = sum(float(point.get("weight", 1.0)) for point in zone_points)
    if total_weight <= 0.0:
        total_weight = float(len(zone_points))
    weighted_sum = sum(
        float(point["reynolds"]) * float(point.get("weight", 1.0)) for point in zone_points
    )
    return weighted_sum / total_weight


def _representative_cl_samples(zone_points: list[dict[str, float]]) -> tuple[float, ...]:
    if not zone_points:
        return (0.70,)
    return tuple(
        sorted({float(point["cl_target"]) for point in zone_points})
    )


def _metrics_from_worker_result(result: Mapping[str, object]) -> dict[str, object] | None:
    status = str(result.get("status", "unknown"))
    if status not in {"ok", "stubbed_ok", "mini_sweep_fallback"}:
        return None

    polar_points = _normalize_polar_points(result.get("polar_points"))
    mean_cd: float | None = None
    mean_cm: float | None = None
    usable_clmax: float | None = None

    if polar_points:
        mean_cd = sum(float(point["cd"]) for point in polar_points) / len(polar_points)
        mean_cm = sum(float(point["cm"]) for point in polar_points) / len(polar_points)
        usable_clmax = max(float(point["cl"]) for point in polar_points)
    elif all(key in result for key in ("mean_cd", "mean_cm", "usable_clmax")):
        mean_cd = float(result["mean_cd"])
        mean_cm = float(result["mean_cm"])
        usable_clmax = float(result["usable_clmax"])
    else:
        return None

    sweep_summary = result.get("sweep_summary")
    if isinstance(sweep_summary, Mapping):
        observed_clmax = sweep_summary.get("cl_max_observed")
        if isinstance(observed_clmax, int | float):
            usable_clmax = float(observed_clmax)
        elif isinstance(sweep_summary.get("first_pass_observed_clmax_proxy"), int | float):
            usable_clmax = float(sweep_summary["first_pass_observed_clmax_proxy"])

    return {
        "status": status,
        "mean_cd": mean_cd,
        "mean_cm": mean_cm,
        "usable_clmax": usable_clmax,
        "polar_points": polar_points,
    }


def select_zone_airfoil_templates(
    *,
    zone_requirements: dict[str, dict[str, object]],
    seed_loader: Callable[[str], tuple[tuple[float, float], ...]],
    worker: Any,
    search_mode: Literal["seed_neighborhood", "seedless_sobol"] = "seed_neighborhood",
    selection_strategy: Literal["scalar_score", "constrained_pareto"] = "scalar_score",
    thickness_delta_levels: tuple[float, ...] = DEFAULT_THICKNESS_DELTA_LEVELS,
    camber_delta_levels: tuple[float, ...] = DEFAULT_CAMBER_DELTA_LEVELS,
    seedless_sample_count: int = 32,
    seedless_random_seed: int | None = 0,
    seedless_max_oversample_factor: int = 8,
    robust_evaluation_enabled: bool = False,
    robust_reynolds_factors: tuple[float, ...] = (1.0,),
    robust_roughness_modes: tuple[str, ...] = ("clean",),
    robust_min_pass_rate: float = 0.75,
    nsga_generation_count: int = 0,
    nsga_offspring_count: int = 0,
    nsga_parent_count: int = 8,
    nsga_random_seed: int | None = 0,
    nsga_mutation_scale: float = 0.06,
    coarse_to_fine_enabled: bool = True,
    coarse_thickness_stride: int = 2,
    coarse_camber_stride: int = 2,
    coarse_keep_top_k: int = 2,
    refine_neighbor_radius: int = 1,
    successive_halving_enabled: bool = True,
    successive_halving_rounds: int = 2,
    successive_halving_beam_width: int = 6,
    safe_clmax_scale: float = 0.90,
    safe_clmax_delta: float = 0.05,
    stall_utilization_limit: float = 0.80,
    tip_3d_penalty_start_eta: float = 0.55,
    tip_3d_penalty_max: float = 0.04,
    tip_taper_penalty_weight: float = 0.35,
    washout_relief_deg: float = 2.0,
    washout_relief_max: float = 0.02,
    launch_stall_utilization_limit: float | None = None,
    turn_stall_utilization_limit: float | None = None,
    local_stall_utilization_limit: float | None = None,
) -> ZoneSelectionBatch:
    concept_batches = select_zone_airfoil_templates_for_concepts(
        concept_zone_requirements={"single": zone_requirements},
        seed_loader=seed_loader,
        worker=worker,
        search_mode=search_mode,
        selection_strategy=selection_strategy,
        thickness_delta_levels=thickness_delta_levels,
        camber_delta_levels=camber_delta_levels,
        seedless_sample_count=seedless_sample_count,
        seedless_random_seed=seedless_random_seed,
        seedless_max_oversample_factor=seedless_max_oversample_factor,
        robust_evaluation_enabled=robust_evaluation_enabled,
        robust_reynolds_factors=robust_reynolds_factors,
        robust_roughness_modes=robust_roughness_modes,
        robust_min_pass_rate=robust_min_pass_rate,
        nsga_generation_count=nsga_generation_count,
        nsga_offspring_count=nsga_offspring_count,
        nsga_parent_count=nsga_parent_count,
        nsga_random_seed=nsga_random_seed,
        nsga_mutation_scale=nsga_mutation_scale,
        coarse_to_fine_enabled=coarse_to_fine_enabled,
        coarse_thickness_stride=coarse_thickness_stride,
        coarse_camber_stride=coarse_camber_stride,
        coarse_keep_top_k=coarse_keep_top_k,
        refine_neighbor_radius=refine_neighbor_radius,
        successive_halving_enabled=successive_halving_enabled,
        successive_halving_rounds=successive_halving_rounds,
        successive_halving_beam_width=successive_halving_beam_width,
        safe_clmax_scale=safe_clmax_scale,
        safe_clmax_delta=safe_clmax_delta,
        stall_utilization_limit=stall_utilization_limit,
        tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
        tip_3d_penalty_max=tip_3d_penalty_max,
        tip_taper_penalty_weight=tip_taper_penalty_weight,
        washout_relief_deg=washout_relief_deg,
        washout_relief_max=washout_relief_max,
        launch_stall_utilization_limit=launch_stall_utilization_limit,
        turn_stall_utilization_limit=turn_stall_utilization_limit,
        local_stall_utilization_limit=local_stall_utilization_limit,
    )
    batch = concept_batches["single"]
    return ZoneSelectionBatch(
        selected_by_zone=batch.selected_by_zone,
        worker_results=[
            {key: value for key, value in result.items() if key != "concept_id"}
            for result in batch.worker_results
        ],
    )


def select_zone_airfoil_templates_for_concepts(
    *,
    concept_zone_requirements: Mapping[str, Mapping[str, dict[str, object]]],
    seed_loader: Callable[[str], tuple[tuple[float, float], ...]],
    worker: Any,
    search_mode: Literal["seed_neighborhood", "seedless_sobol"] = "seed_neighborhood",
    selection_strategy: Literal["scalar_score", "constrained_pareto"] = "scalar_score",
    thickness_delta_levels: tuple[float, ...] = DEFAULT_THICKNESS_DELTA_LEVELS,
    camber_delta_levels: tuple[float, ...] = DEFAULT_CAMBER_DELTA_LEVELS,
    seedless_sample_count: int = 32,
    seedless_random_seed: int | None = 0,
    seedless_max_oversample_factor: int = 8,
    robust_evaluation_enabled: bool = False,
    robust_reynolds_factors: tuple[float, ...] = (1.0,),
    robust_roughness_modes: tuple[str, ...] = ("clean",),
    robust_min_pass_rate: float = 0.75,
    nsga_generation_count: int = 0,
    nsga_offspring_count: int = 0,
    nsga_parent_count: int = 8,
    nsga_random_seed: int | None = 0,
    nsga_mutation_scale: float = 0.06,
    coarse_to_fine_enabled: bool = True,
    coarse_thickness_stride: int = 2,
    coarse_camber_stride: int = 2,
    coarse_keep_top_k: int = 2,
    refine_neighbor_radius: int = 1,
    successive_halving_enabled: bool = True,
    successive_halving_rounds: int = 2,
    successive_halving_beam_width: int = 6,
    safe_clmax_scale: float = 0.90,
    safe_clmax_delta: float = 0.05,
    stall_utilization_limit: float = 0.80,
    tip_3d_penalty_start_eta: float = 0.55,
    tip_3d_penalty_max: float = 0.04,
    tip_taper_penalty_weight: float = 0.35,
    washout_relief_deg: float = 2.0,
    washout_relief_max: float = 0.02,
    launch_stall_utilization_limit: float | None = None,
    turn_stall_utilization_limit: float | None = None,
    local_stall_utilization_limit: float | None = None,
) -> dict[str, ZoneSelectionBatch]:
    if not concept_zone_requirements:
        return {}

    local_stall_utilization_limit = (
        float(stall_utilization_limit)
        if local_stall_utilization_limit is None
        else float(local_stall_utilization_limit)
    )
    launch_stall_utilization_limit = (
        local_stall_utilization_limit
        if launch_stall_utilization_limit is None
        else float(launch_stall_utilization_limit)
    )
    turn_stall_utilization_limit = (
        local_stall_utilization_limit
        if turn_stall_utilization_limit is None
        else float(turn_stall_utilization_limit)
    )

    zone_points_by_key: dict[str, list[dict[str, float]]] = {}
    zone_min_tc_by_key: dict[str, float] = {}
    candidates_by_key: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
    coarse_candidates_by_key: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}

    for concept_id, zone_requirements in concept_zone_requirements.items():
        (
            zone_points_by_name,
            zone_min_tc_by_name,
            candidates_by_zone,
            coarse_candidates_by_zone,
        ) = _prepare_zone_selection_inputs(
            zone_requirements=zone_requirements,
            seed_loader=seed_loader,
            thickness_delta_levels=thickness_delta_levels,
            camber_delta_levels=camber_delta_levels,
            coarse_to_fine_enabled=coarse_to_fine_enabled,
            coarse_thickness_stride=coarse_thickness_stride,
            coarse_camber_stride=coarse_camber_stride,
            search_mode=search_mode,
            seedless_sample_count=seedless_sample_count,
            seedless_random_seed=seedless_random_seed,
            seedless_max_oversample_factor=seedless_max_oversample_factor,
        )
        for zone_name in zone_requirements:
            batch_key = _concept_zone_batch_key(concept_id=concept_id, zone_name=zone_name)
            zone_points_by_key[batch_key] = zone_points_by_name[zone_name]
            zone_min_tc_by_key[batch_key] = zone_min_tc_by_name[zone_name]
            candidates_by_key[batch_key] = candidates_by_zone[zone_name]
            coarse_candidates_by_key[batch_key] = coarse_candidates_by_zone[zone_name]

    candidate_results_by_key, coarse_worker_results = _run_batched_zone_candidate_queries(
        zone_candidates=coarse_candidates_by_key,
        zone_points_by_name=zone_points_by_key,
        worker=worker,
        robust_evaluation_enabled=robust_evaluation_enabled,
        robust_reynolds_factors=robust_reynolds_factors,
        robust_roughness_modes=robust_roughness_modes,
        robust_min_pass_rate=robust_min_pass_rate,
    )
    worker_results_by_concept: dict[str, list[dict[str, object]]] = {
        concept_id: [] for concept_id in concept_zone_requirements
    }
    for result in coarse_worker_results:
        concept_id, zone_name = _split_concept_zone_batch_key(str(result["zone_name"]))
        worker_results_by_concept.setdefault(concept_id, []).append(
            {
                **result,
                "zone_name": zone_name,
                "concept_id": concept_id,
            }
        )

    if (
        search_mode == "seedless_sobol"
        and int(nsga_generation_count) > 0
        and int(nsga_offspring_count) > 0
    ):
        for generation_index in range(1, int(nsga_generation_count) + 1):
            offspring_by_key: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
            for batch_key, candidates in candidates_by_key.items():
                zone_points = zone_points_by_key[batch_key]
                zone_min_tc_ratio = zone_min_tc_by_key[batch_key]
                scored = _score_available_zone_candidates(
                    candidates,
                    zone_points=zone_points,
                    candidate_results=candidate_results_by_key.get(batch_key, {}),
                    zone_min_tc_ratio=zone_min_tc_ratio,
                    safe_clmax_scale=safe_clmax_scale,
                    safe_clmax_delta=safe_clmax_delta,
                    stall_utilization_limit=stall_utilization_limit,
                    tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
                    tip_3d_penalty_max=tip_3d_penalty_max,
                    tip_taper_penalty_weight=tip_taper_penalty_weight,
                    washout_relief_deg=washout_relief_deg,
                    washout_relief_max=washout_relief_max,
                    launch_stall_utilization_limit=launch_stall_utilization_limit,
                    turn_stall_utilization_limit=turn_stall_utilization_limit,
                    local_stall_utilization_limit=local_stall_utilization_limit,
                )
                parent_count = min(max(2, int(nsga_parent_count)), len(scored))
                if parent_count < 2:
                    continue
                _, zone_name = _split_concept_zone_batch_key(batch_key)
                parents = _select_scored_candidate_beam(
                    scored,
                    beam_count=parent_count,
                    selection_strategy=selection_strategy,
                )
                offspring = generate_seedless_nsga2_offspring(
                    zone_name=zone_name,
                    parents=parents,
                    bounds=_default_seedless_cst_bounds(zone_name),
                    constraints=_seedless_constraints_for_zone(zone_min_tc_ratio),
                    offspring_count=int(nsga_offspring_count),
                    generation_index=generation_index,
                    random_seed=_seed_for_generation(
                        base_seed=nsga_random_seed,
                        generation_index=generation_index,
                    ),
                    mutation_scale=nsga_mutation_scale,
                )
                offspring_by_key[batch_key] = offspring
                candidates_by_key[batch_key] = (*candidates_by_key[batch_key], *offspring)

            if not offspring_by_key:
                continue
            candidate_results_by_key, nsga_worker_results = _run_batched_zone_candidate_queries(
                zone_candidates=offspring_by_key,
                zone_points_by_name=zone_points_by_key,
                worker=worker,
                existing_results_by_zone=candidate_results_by_key,
                robust_evaluation_enabled=robust_evaluation_enabled,
                robust_reynolds_factors=robust_reynolds_factors,
                robust_roughness_modes=robust_roughness_modes,
                robust_min_pass_rate=robust_min_pass_rate,
            )
            for result in nsga_worker_results:
                concept_id, zone_name = _split_concept_zone_batch_key(str(result["zone_name"]))
                worker_results_by_concept.setdefault(concept_id, []).append(
                    {
                        **result,
                        "zone_name": zone_name,
                        "concept_id": concept_id,
                    }
                )

    if coarse_to_fine_enabled:
        coarse_beam_by_key: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
        for batch_key, candidates in candidates_by_key.items():
            zone_points = zone_points_by_key[batch_key]
            zone_min_tc_ratio = zone_min_tc_by_key[batch_key]
            candidate_results = candidate_results_by_key.get(batch_key, {})
            coarse_candidates = coarse_candidates_by_key[batch_key]
            coarse_scored = _score_available_zone_candidates(
                coarse_candidates,
                zone_points=zone_points,
                candidate_results=candidate_results,
                zone_min_tc_ratio=zone_min_tc_ratio,
                safe_clmax_scale=safe_clmax_scale,
                safe_clmax_delta=safe_clmax_delta,
                stall_utilization_limit=stall_utilization_limit,
                tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
                tip_3d_penalty_max=tip_3d_penalty_max,
                tip_taper_penalty_weight=tip_taper_penalty_weight,
                washout_relief_deg=washout_relief_deg,
                washout_relief_max=washout_relief_max,
                launch_stall_utilization_limit=launch_stall_utilization_limit,
                turn_stall_utilization_limit=turn_stall_utilization_limit,
                local_stall_utilization_limit=local_stall_utilization_limit,
            )
            coarse_seed_count = min(max(1, int(coarse_keep_top_k)), len(coarse_scored))
            coarse_beam_by_key[batch_key] = _select_scored_candidate_beam(
                coarse_scored,
                beam_count=coarse_seed_count,
                selection_strategy=selection_strategy,
            )

        current_beam_by_key = coarse_beam_by_key
        if successive_halving_enabled:
            total_rounds = max(1, int(successive_halving_rounds))
            for round_index in range(total_rounds):
                stage_candidates_by_key: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
                radius = _successive_halving_radius(
                    round_index=round_index,
                    total_rounds=total_rounds,
                    base_radius=refine_neighbor_radius,
                )
                for batch_key, candidates in candidates_by_key.items():
                    stage_candidates = _refinement_candidates(
                        candidates,
                        seed_candidates=current_beam_by_key[batch_key],
                        neighbor_radius=radius,
                    )
                    stage_candidates_by_key[batch_key] = stage_candidates or candidates

                candidate_results_by_key, stage_worker_results = _run_batched_zone_candidate_queries(
                    zone_candidates=stage_candidates_by_key,
                    zone_points_by_name=zone_points_by_key,
                    worker=worker,
                    existing_results_by_zone=candidate_results_by_key,
                    robust_evaluation_enabled=robust_evaluation_enabled,
                    robust_reynolds_factors=robust_reynolds_factors,
                    robust_roughness_modes=robust_roughness_modes,
                    robust_min_pass_rate=robust_min_pass_rate,
                )
                for result in stage_worker_results:
                    concept_id, zone_name = _split_concept_zone_batch_key(str(result["zone_name"]))
                    worker_results_by_concept.setdefault(concept_id, []).append(
                        {
                            **result,
                            "zone_name": zone_name,
                            "concept_id": concept_id,
                        }
                    )

                next_beam_by_key: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
                for batch_key, stage_candidates in stage_candidates_by_key.items():
                    zone_points = zone_points_by_key[batch_key]
                    zone_min_tc_ratio = zone_min_tc_by_key[batch_key]
                    stage_scored = _score_available_zone_candidates(
                        stage_candidates,
                        zone_points=zone_points,
                        candidate_results=candidate_results_by_key.get(batch_key, {}),
                        zone_min_tc_ratio=zone_min_tc_ratio,
                        safe_clmax_scale=safe_clmax_scale,
                        safe_clmax_delta=safe_clmax_delta,
                        stall_utilization_limit=stall_utilization_limit,
                        tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
                        tip_3d_penalty_max=tip_3d_penalty_max,
                        tip_taper_penalty_weight=tip_taper_penalty_weight,
                        washout_relief_deg=washout_relief_deg,
                        washout_relief_max=washout_relief_max,
                        launch_stall_utilization_limit=launch_stall_utilization_limit,
                        turn_stall_utilization_limit=turn_stall_utilization_limit,
                        local_stall_utilization_limit=local_stall_utilization_limit,
                    )
                    beam_count = min(max(1, int(successive_halving_beam_width)), len(stage_scored))
                    next_beam_by_key[batch_key] = _select_scored_candidate_beam(
                        stage_scored,
                        beam_count=beam_count,
                        selection_strategy=selection_strategy,
                    )
                current_beam_by_key = next_beam_by_key
        else:
            refinement_candidates_by_key: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
            for batch_key, candidates in candidates_by_key.items():
                refinement_candidates_by_key[batch_key] = _refinement_candidates(
                    candidates,
                    seed_candidates=current_beam_by_key[batch_key],
                    neighbor_radius=refine_neighbor_radius,
                )
                if not refinement_candidates_by_key[batch_key]:
                    refinement_candidates_by_key[batch_key] = candidates

            candidate_results_by_key, refinement_worker_results = _run_batched_zone_candidate_queries(
                zone_candidates=refinement_candidates_by_key,
                zone_points_by_name=zone_points_by_key,
                worker=worker,
                existing_results_by_zone=candidate_results_by_key,
                robust_evaluation_enabled=robust_evaluation_enabled,
                robust_reynolds_factors=robust_reynolds_factors,
                robust_roughness_modes=robust_roughness_modes,
                robust_min_pass_rate=robust_min_pass_rate,
            )
            for result in refinement_worker_results:
                concept_id, zone_name = _split_concept_zone_batch_key(str(result["zone_name"]))
                worker_results_by_concept.setdefault(concept_id, []).append(
                    {
                        **result,
                        "zone_name": zone_name,
                        "concept_id": concept_id,
                    }
                )

    selected_by_concept: dict[str, dict[str, SelectedZoneCandidate]] = {
        concept_id: {} for concept_id in concept_zone_requirements
    }
    for concept_id, zone_requirements in concept_zone_requirements.items():
        for zone_name in zone_requirements:
            batch_key = _concept_zone_batch_key(concept_id=concept_id, zone_name=zone_name)
            selected_by_concept[concept_id][zone_name] = select_best_zone_candidate(
                candidates=candidates_by_key[batch_key],
                zone_points=zone_points_by_key[batch_key],
                candidate_results=candidate_results_by_key.get(batch_key, {}),
                zone_min_tc_ratio=zone_min_tc_by_key[batch_key],
                safe_clmax_scale=safe_clmax_scale,
                safe_clmax_delta=safe_clmax_delta,
                stall_utilization_limit=stall_utilization_limit,
                tip_3d_penalty_start_eta=tip_3d_penalty_start_eta,
                tip_3d_penalty_max=tip_3d_penalty_max,
                tip_taper_penalty_weight=tip_taper_penalty_weight,
                washout_relief_deg=washout_relief_deg,
                washout_relief_max=washout_relief_max,
                launch_stall_utilization_limit=launch_stall_utilization_limit,
                turn_stall_utilization_limit=turn_stall_utilization_limit,
                local_stall_utilization_limit=local_stall_utilization_limit,
            )

    return {
        concept_id: ZoneSelectionBatch(
            selected_by_zone=selected_by_concept[concept_id],
            worker_results=worker_results_by_concept.get(concept_id, []),
        )
        for concept_id in concept_zone_requirements
    }
