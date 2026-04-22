from __future__ import annotations

from dataclasses import dataclass
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
_SUCCESSFUL_SELECTION_STATUSES = {"ok", "stubbed_ok", "cli_stubbed"}


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
) -> float:
    target_cl = max((float(point["cl_target"]) for point in zone_points), default=0.0)
    cl_margin_penalty = max(0.0, target_cl + 0.10 - usable_clmax) ** 2
    cm_penalty = max(0.0, abs(mean_cm) - 0.15) ** 2
    return float(mean_cd) + 5.0 * cl_margin_penalty + 2.0 * cm_penalty


def select_best_zone_candidate(
    candidates: tuple[CSTAirfoilTemplate, ...],
    zone_points: list[dict[str, float]],
    candidate_results: Mapping[str, Mapping[str, float | str]],
) -> SelectedZoneCandidate:
    scored: list[SelectedZoneCandidate] = []
    for candidate in candidates:
        coordinates = generate_cst_coordinates(candidate)
        validity = validate_cst_candidate_coordinates(coordinates)
        if not validity.valid:
            continue

        result = candidate_results.get(candidate.candidate_role)
        if result is None:
            continue
        status = str(result.get("status", "unknown"))
        if status not in _SUCCESSFUL_SELECTION_STATUSES:
            continue

        mean_cd = float(result["mean_cd"])
        mean_cm = float(result["mean_cm"])
        usable_clmax = float(result["usable_clmax"])
        candidate_score = score_zone_candidate(
            zone_points=zone_points,
            mean_cd=mean_cd,
            mean_cm=mean_cm,
            usable_clmax=usable_clmax,
        )
        scored.append(
            SelectedZoneCandidate(
                template=candidate,
                coordinates=coordinates,
                mean_cd=mean_cd,
                mean_cm=mean_cm,
                usable_clmax=usable_clmax,
                candidate_score=candidate_score,
            )
        )

    if not scored:
        raise ValueError("No valid CST zone candidates were available for selection.")

    return min(scored, key=lambda item: item.candidate_score)


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


def _metrics_from_worker_result(result: Mapping[str, object]) -> dict[str, float | str] | None:
    status = str(result.get("status", "unknown"))
    if status not in _SUCCESSFUL_SELECTION_STATUSES:
        return None

    direct_keys = ("mean_cd", "mean_cm", "usable_clmax")
    if all(key in result for key in direct_keys):
        return {
            "status": status,
            "mean_cd": float(result["mean_cd"]),
            "mean_cm": float(result["mean_cm"]),
            "usable_clmax": float(result["usable_clmax"]),
        }

    polar_points = result.get("polar_points")
    if not isinstance(polar_points, list) or not polar_points:
        return None

    valid_points = [
        point
        for point in polar_points
        if isinstance(point, Mapping)
        and isinstance(point.get("cd"), int | float)
        and isinstance(point.get("cm"), int | float)
        and isinstance(point.get("cl"), int | float)
    ]
    if not valid_points:
        return None

    mean_cd = sum(float(point["cd"]) for point in valid_points) / len(valid_points)
    mean_cm = sum(float(point["cm"]) for point in valid_points) / len(valid_points)
    usable_clmax = max(float(point["cl"]) for point in valid_points)

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
    }


def _stubbed_metrics_from_zone_points(zone_points: list[dict[str, float]]) -> dict[str, float | str]:
    target_cl = max((float(point["cl_target"]) for point in zone_points), default=0.70)
    if zone_points:
        mean_cm = sum(float(point["cm_target"]) for point in zone_points) / len(zone_points)
    else:
        mean_cm = -0.10
    return {
        "status": "stubbed_ok",
        "mean_cd": 0.020,
        "mean_cm": mean_cm,
        "usable_clmax": target_cl + 0.20,
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
        if not zone_points:
            base_coordinates = generate_cst_coordinates(base_template)
            validity = validate_cst_candidate_coordinates(base_coordinates)
            if not validity.valid:
                raise ValueError(
                    f"Base CST candidate for zone {zone_name!r} was invalid: {validity.reason}."
                )
            fallback_metrics = _stubbed_metrics_from_zone_points(zone_points)
            selected_by_zone[zone_name] = SelectedZoneCandidate(
                template=base_template,
                coordinates=base_coordinates,
                mean_cd=float(fallback_metrics["mean_cd"]),
                mean_cm=float(fallback_metrics["mean_cm"]),
                usable_clmax=float(fallback_metrics["usable_clmax"]),
                candidate_score=score_zone_candidate(
                    zone_points=zone_points,
                    mean_cd=float(fallback_metrics["mean_cd"]),
                    mean_cm=float(fallback_metrics["mean_cm"]),
                    usable_clmax=float(fallback_metrics["usable_clmax"]),
                ),
            )
            continue
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
        candidate_results: dict[str, dict[str, float | str]] = {}
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
            if metrics is None and str(raw_result.get("status", "unknown")) in _SUCCESSFUL_SELECTION_STATUSES:
                metrics = _stubbed_metrics_from_zone_points(zone_points)
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
        )

    return ZoneSelectionBatch(selected_by_zone=selected_by_zone, worker_results=worker_results)
