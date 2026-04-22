from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
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
) -> float:
    zone_stats = _weighted_zone_point_values(zone_points)
    effective_weights = list(zone_stats["effective_weights"]) or [1.0 for _ in zone_points]
    total_effective_weight = sum(effective_weights)
    if total_effective_weight <= 0.0:
        total_effective_weight = float(len(effective_weights)) or 1.0

    normalized_polar_points = _normalize_polar_points(polar_points)
    matched_polar_points = _matched_worker_polar_points(zone_points, normalized_polar_points)

    if matched_polar_points:
        matched_cd = sum(
            weight * float(point["cd"])
            for point, weight in zip(matched_polar_points, effective_weights, strict=True)
        ) / total_effective_weight
        matched_cm = sum(
            weight * float(point["cm"])
            for point, weight in zip(matched_polar_points, effective_weights, strict=True)
        ) / total_effective_weight
        matched_cl = sum(
            weight * float(point["cl"])
            for point, weight in zip(matched_polar_points, effective_weights, strict=True)
        ) / total_effective_weight
        matched_cl_spread = math.sqrt(
            sum(
                weight * (float(point["cl"]) - matched_cl) ** 2
                for point, weight in zip(matched_polar_points, effective_weights, strict=True)
            )
            / total_effective_weight
        )
        matched_cm_spread = math.sqrt(
            sum(
                weight * (float(point["cm"]) - matched_cm) ** 2
                for point, weight in zip(matched_polar_points, effective_weights, strict=True)
            )
            / total_effective_weight
        )
        weighted_cm_target = float(zone_stats["weighted_cm_target"])
        safe_cl_proxy = (
            matched_cl
            + 0.35 * matched_cl_spread
            + 0.20 * max(0.0, float(zone_stats["max_cl_target"]) - matched_cl)
            + 0.03
        )
        trim_proxy = (
            0.65 * matched_cm_spread
            + 0.35 * abs(matched_cm - weighted_cm_target)
        )
        drag_proxy = matched_cd * float(zone_stats["weighted_chord_factor"])
    else:
        safe_cl_proxy = (
            float(zone_stats["weighted_cl_target"])
            + 0.40 * float(zone_stats["cl_spread"])
            + 0.30 * max(
                0.0,
                float(zone_stats["max_cl_target"]) - float(zone_stats["weighted_cl_target"]),
            )
            + 0.03
        )
        trim_proxy = (
            0.70 * float(zone_stats["cm_rms"])
            + 0.30 * abs(float(mean_cm) - float(zone_stats["weighted_cm_target"]))
        )
        drag_proxy = float(mean_cd) * float(zone_stats["weighted_chord_factor"])

    cl_deficit = max(0.0, safe_cl_proxy - float(usable_clmax))
    cl_penalty = _bounded_penalty(cl_deficit, 0.16)
    trim_penalty = _bounded_penalty(trim_proxy, 0.05)

    candidate_thickness_ratio = (
        _candidate_thickness_ratio(coordinates)
        if coordinates is not None
        else max(zone_min_tc_ratio, 0.12)
    )
    if candidate_thickness_ratio <= 0.0:
        thickness_penalty = 1.0
        usable_thickness = 0.0
    else:
        thickness_deficit = max(0.0, float(zone_min_tc_ratio) - candidate_thickness_ratio)
        thickness_penalty = _bounded_penalty(
            thickness_deficit,
            max(0.01, 0.20 * float(zone_min_tc_ratio)),
        )
        usable_thickness = candidate_thickness_ratio

    drag_penalty = _bounded_penalty(drag_proxy, 0.02)

    infeasible_guard = 0.0
    if cl_deficit > 0.0 or usable_thickness + 1.0e-9 < float(zone_min_tc_ratio):
        infeasible_guard = 0.60 + 0.60 * cl_penalty + 0.80 * thickness_penalty

    return (
        1.65 * drag_penalty
        + 3.00 * cl_penalty
        + 1.35 * trim_penalty
        + 4.25 * thickness_penalty
        + infeasible_guard
    )


def select_best_zone_candidate(
    candidates: tuple[CSTAirfoilTemplate, ...],
    zone_points: list[dict[str, float]],
    candidate_results: Mapping[str, Mapping[str, object]],
    *,
    zone_min_tc_ratio: float = 0.10,
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
        if status not in {"ok", "stubbed_ok"}:
            continue

        mean_cd = float(result["mean_cd"])
        mean_cm = float(result["mean_cm"])
        usable_clmax = float(result["usable_clmax"])
        polar_points = result.get("polar_points")
        candidate_score = score_zone_candidate(
            zone_points=zone_points,
            mean_cd=mean_cd,
            mean_cm=mean_cm,
            usable_clmax=usable_clmax,
            zone_min_tc_ratio=zone_min_tc_ratio,
            coordinates=coordinates,
            polar_points=polar_points if isinstance(polar_points, list) else None,
        )
        thickness_ratio = _candidate_thickness_ratio(coordinates)
        feasible = (
            usable_clmax >= 0.0
            and thickness_ratio >= float(zone_min_tc_ratio)
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
                    candidate_score=candidate_score,
                ),
            )
        )

    if not scored:
        raise ValueError("No valid CST zone candidates were available for selection.")

    return min(scored, key=lambda item: (item[0], item[1].candidate_score, item[1].usable_clmax))[1]


def _default_seed_name(zone_name: str) -> str:
    return "fx76mp140" if zone_name in {"root", "mid1"} else "clarkysm"


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
    if status not in {"ok", "stubbed_ok"}:
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
) -> ZoneSelectionBatch:
    selected_by_zone: dict[str, SelectedZoneCandidate] = {}
    worker_results: list[dict[str, object]] = []

    for zone_name, zone_data in zone_requirements.items():
        zone_points = list(zone_data.get("points", []))
        seed_name = _default_seed_name(zone_name)
        base_template = build_base_cst_template(
            zone_name=zone_name,
            seed_name=seed_name,
            seed_coordinates=seed_loader(seed_name),
        )
        candidates = build_bounded_candidate_family(base_template)

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
                )
            )
            query_roles.append(candidate.candidate_role)

        if not queries:
            raise ValueError(f"Zone {zone_name!r} did not produce any valid CST candidates.")

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
        candidate_results: dict[str, dict[str, object]] = {}
        seen_template_ids: set[str] = set()
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
            worker_results.append(
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

        selected_by_zone[zone_name] = select_best_zone_candidate(
            candidates=candidates,
            zone_points=zone_points,
            candidate_results=candidate_results,
            zone_min_tc_ratio=float(zone_data.get("min_tc_ratio", 0.10)),
        )

    return ZoneSelectionBatch(selected_by_zone=selected_by_zone, worker_results=worker_results)
