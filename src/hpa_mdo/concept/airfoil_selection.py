from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    DEFAULT_CAMBER_DELTA_LEVELS,
    DEFAULT_THICKNESS_DELTA_LEVELS,
    build_bounded_candidate_family,
    generate_cst_coordinates,
    validate_cst_candidate_coordinates,
)
from hpa_mdo.concept.airfoil_worker import PolarQuery, geometry_hash_from_coordinates


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
) -> dict[str, float]:
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
    safe_clmax = _safe_clmax(
        usable_clmax,
        safe_scale=safe_clmax_scale,
        safe_delta=safe_clmax_delta,
    )
    stall_utilization = max(
        float(point["cl_target"]) / max(safe_clmax, 1.0e-9)
        for point in zone_points
    ) if zone_points else 0.0

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
) -> float:
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
    )

    drag_penalty = _bounded_penalty(float(metrics["profile_power_proxy"]), 0.022)
    trim_penalty = _bounded_penalty(float(metrics["trim_moment_proxy"]), 0.11)
    stall_violation = max(0.0, float(metrics["stall_utilization"]) - float(stall_utilization_limit))
    stall_penalty = _bounded_penalty(stall_violation, 0.10)

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
        infeasible_guard += 1.2 + 2.0 * stall_penalty
    if thickness_deficit > 0.0 or spar_depth_deficit > 0.0:
        infeasible_guard += 0.8 + 1.5 * max(thickness_penalty, spar_penalty)

    return (
        1.75 * drag_penalty
        + 3.50 * stall_penalty
        + 1.50 * trim_penalty
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
) -> SelectedZoneCandidate:
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
        )
        thickness_ratio = float(metrics["candidate_thickness_ratio"])
        spar_depth_ratio = float(metrics["spar_depth_ratio"])
        required_spar_depth_ratio = float(metrics["required_spar_depth_ratio"])
        safe_clmax = float(metrics["safe_clmax"])
        stall_utilization = float(metrics["stall_utilization"])
        feasible = (
            safe_clmax >= 0.0
            and stall_utilization <= float(stall_utilization_limit)
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
        )
        thickness_ratio = float(metrics["candidate_thickness_ratio"])
        spar_depth_ratio = float(metrics["spar_depth_ratio"])
        required_spar_depth_ratio = float(metrics["required_spar_depth_ratio"])
        safe_clmax = float(metrics["safe_clmax"])
        stall_utilization = float(metrics["stall_utilization"])
        feasible = (
            safe_clmax >= 0.0
            and stall_utilization <= float(stall_utilization_limit)
            and thickness_ratio >= float(zone_min_tc_ratio)
            and spar_depth_ratio >= required_spar_depth_ratio
        )
        scored.append((0 if feasible else 1, candidate_score, -usable_clmax, candidate))
    return sorted(scored, key=lambda item: (item[0], item[1], item[2], item[3].candidate_role))


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


def _zone_queries_for_candidates(
    *,
    zone_name: str,
    candidates: tuple[CSTAirfoilTemplate, ...],
    zone_points: list[dict[str, float]],
) -> tuple[list[PolarQuery], list[str]]:
    queries: list[PolarQuery] = []
    query_roles: list[str] = []
    for candidate in candidates:
        coordinates = generate_cst_coordinates(candidate)
        validity = validate_cst_candidate_coordinates(coordinates)
        if not validity.valid:
            continue
        queries.append(
            PolarQuery(
                template_id=f"{zone_name}-{candidate.candidate_role}",
                reynolds=_representative_reynolds(zone_points),
                cl_samples=_representative_cl_samples(zone_points),
                roughness_mode="clean",
                geometry_hash=geometry_hash_from_coordinates(coordinates),
                coordinates=coordinates,
                analysis_mode="screening_target_cl",
                analysis_stage="screening",
            )
        )
        query_roles.append(candidate.candidate_role)
    return queries, query_roles


def _run_zone_candidate_queries(
    *,
    zone_name: str,
    candidates: tuple[CSTAirfoilTemplate, ...],
    zone_points: list[dict[str, float]],
    worker: Any,
    existing_results: Mapping[str, dict[str, object]] | None = None,
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    candidate_results = dict(existing_results or {})
    candidates_to_run = tuple(
        candidate for candidate in candidates if candidate.candidate_role not in candidate_results
    )
    queries, query_roles = _zone_queries_for_candidates(
        zone_name=zone_name,
        candidates=candidates_to_run,
        zone_points=zone_points,
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
            candidate_results[candidate_role] = metrics
    if seen_template_ids != set(query_identity_by_template_id):
        missing = sorted(set(query_identity_by_template_id) - seen_template_ids)
        raise RuntimeError(
            f"Airfoil worker did not return results for all CST queries in zone {zone_name!r}: missing {missing!r}."
        )
    return candidate_results, normalized_worker_results


def _run_batched_zone_candidate_queries(
    *,
    zone_candidates: Mapping[str, tuple[CSTAirfoilTemplate, ...]],
    zone_points_by_name: Mapping[str, list[dict[str, float]]],
    worker: Any,
    existing_results_by_zone: Mapping[str, Mapping[str, dict[str, object]]] | None = None,
) -> tuple[dict[str, dict[str, dict[str, object]]], list[dict[str, object]]]:
    aggregated_results: dict[str, dict[str, dict[str, object]]] = {
        zone_name: dict((existing_results_by_zone or {}).get(zone_name, {}))
        for zone_name in zone_candidates
    }
    batch_queries: list[PolarQuery] = []
    query_identity_by_template_id: dict[str, dict[str, str]] = {}

    for zone_name, candidates in zone_candidates.items():
        existing_zone_results = aggregated_results.setdefault(zone_name, {})
        candidates_to_run = tuple(
            candidate for candidate in candidates if candidate.candidate_role not in existing_zone_results
        )
        queries, query_roles = _zone_queries_for_candidates(
            zone_name=zone_name,
            candidates=candidates_to_run,
            zone_points=zone_points_by_name[zone_name],
        )
        for query, candidate_role in zip(queries, query_roles, strict=True):
            batch_queries.append(query)
            query_identity_by_template_id[query.template_id] = {
                "zone_name": zone_name,
                "candidate_role": candidate_role,
                "geometry_hash": query.geometry_hash,
            }

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
            aggregated_results.setdefault(zone_name, {})[candidate_role] = metrics

    if seen_template_ids != set(query_identity_by_template_id):
        missing = sorted(set(query_identity_by_template_id) - seen_template_ids)
        raise RuntimeError(
            "Airfoil worker did not return results for all batched CST queries: "
            f"missing {missing!r}."
        )
    return aggregated_results, normalized_worker_results


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
    thickness_delta_levels: tuple[float, ...] = DEFAULT_THICKNESS_DELTA_LEVELS,
    camber_delta_levels: tuple[float, ...] = DEFAULT_CAMBER_DELTA_LEVELS,
    coarse_to_fine_enabled: bool = True,
    coarse_thickness_stride: int = 2,
    coarse_camber_stride: int = 2,
    coarse_keep_top_k: int = 2,
    refine_neighbor_radius: int = 1,
    safe_clmax_scale: float = 0.90,
    safe_clmax_delta: float = 0.05,
    stall_utilization_limit: float = 0.80,
) -> ZoneSelectionBatch:
    selected_by_zone: dict[str, SelectedZoneCandidate] = {}
    worker_results: list[dict[str, object]] = []
    zone_points_by_name: dict[str, list[dict[str, float]]] = {}
    zone_min_tc_by_name: dict[str, float] = {}
    candidates_by_zone: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
    coarse_candidates_by_zone: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}

    for zone_name, zone_data in zone_requirements.items():
        zone_points = list(zone_data.get("points", []))
        zone_min_tc_ratio = float(zone_data.get("min_tc_ratio", 0.10))
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

    candidate_results_by_zone, coarse_worker_results = _run_batched_zone_candidate_queries(
        zone_candidates=coarse_candidates_by_zone,
        zone_points_by_name=zone_points_by_name,
        worker=worker,
    )
    worker_results.extend(coarse_worker_results)

    refinement_candidates_by_zone: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
    if coarse_to_fine_enabled:
        for zone_name, candidates in candidates_by_zone.items():
            zone_points = zone_points_by_name[zone_name]
            zone_min_tc_ratio = zone_min_tc_by_name[zone_name]
            candidate_results = candidate_results_by_zone.get(zone_name, {})
            coarse_candidates = coarse_candidates_by_zone[zone_name]
            coarse_scored = _score_available_zone_candidates(
                coarse_candidates,
                zone_points=zone_points,
                candidate_results=candidate_results,
                zone_min_tc_ratio=zone_min_tc_ratio,
                safe_clmax_scale=safe_clmax_scale,
                safe_clmax_delta=safe_clmax_delta,
                stall_utilization_limit=stall_utilization_limit,
            )
            coarse_seed_count = min(max(1, int(coarse_keep_top_k)), len(coarse_scored))
            coarse_beam = tuple(item[3] for item in coarse_scored[:coarse_seed_count])
            refinement_candidates_by_zone[zone_name] = _refinement_candidates(
                candidates,
                seed_candidates=coarse_beam,
                neighbor_radius=refine_neighbor_radius,
            )
            if not refinement_candidates_by_zone[zone_name]:
                refinement_candidates_by_zone[zone_name] = candidates

        candidate_results_by_zone, refinement_worker_results = _run_batched_zone_candidate_queries(
            zone_candidates=refinement_candidates_by_zone,
            zone_points_by_name=zone_points_by_name,
            worker=worker,
            existing_results_by_zone=candidate_results_by_zone,
        )
        worker_results.extend(refinement_worker_results)

    for zone_name, candidates in candidates_by_zone.items():
        selected_by_zone[zone_name] = select_best_zone_candidate(
            candidates=candidates,
            zone_points=zone_points_by_name[zone_name],
            candidate_results=candidate_results_by_zone.get(zone_name, {}),
            zone_min_tc_ratio=zone_min_tc_by_name[zone_name],
            safe_clmax_scale=safe_clmax_scale,
            safe_clmax_delta=safe_clmax_delta,
            stall_utilization_limit=stall_utilization_limit,
        )

    return ZoneSelectionBatch(selected_by_zone=selected_by_zone, worker_results=worker_results)
