from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Callable, Protocol

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    build_lofting_guides,
    generate_cst_coordinates,
    validate_cst_candidate_coordinates,
)
from hpa_mdo.concept.airfoil_selection import (
    SelectedZoneCandidate,
    build_base_cst_template,
    select_zone_airfoil_templates,
)
from hpa_mdo.concept.airfoil_worker import PolarQuery, geometry_hash_from_coordinates
from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    WingStation,
    build_linear_wing_stations,
    enumerate_geometry_concepts,
)
from hpa_mdo.concept.handoff import write_selected_concept_bundle
from hpa_mdo.concept.propulsion import SimplifiedPropModel
from hpa_mdo.concept.ranking import CandidateConceptResult, rank_concepts
from hpa_mdo.concept.safety import (
    evaluate_launch_gate,
    evaluate_local_stall,
    evaluate_trim_proxy,
    evaluate_turn_gate,
)
from hpa_mdo.mission.objective import (
    FakeAnchorCurve,
    MissionEvaluationInputs,
    MissionEvaluationResult,
    evaluate_mission_objective,
)

_ROOT_SEED_AIRFOIL = "fx76mp140"
_TIP_SEED_AIRFOIL = "clarkysm"


class SpanwiseLoadLoader(Protocol):
    def __call__(
        self, concept: GeometryConcept, stations: tuple[WingStation, ...]
    ) -> dict[str, dict[str, Any]]:
        ...


class AirfoilWorker(Protocol):
    def run_queries(self, queries: list[PolarQuery]) -> list[dict[str, object]]:
        ...


AirfoilWorkerFactory = Callable[..., AirfoilWorker]


@dataclass(frozen=True)
class ConceptPipelineResult:
    summary_json_path: Path
    selected_concept_dirs: tuple[Path, ...]
    best_infeasible_concept_dirs: tuple[Path, ...] = ()


@dataclass(frozen=True)
class _EvaluatedConcept:
    evaluation_id: str
    enumeration_index: int
    concept: GeometryConcept
    stations: tuple[WingStation, ...]
    zone_requirements: dict[str, dict[str, Any]]
    airfoil_templates: dict[str, dict[str, Any]]
    worker_results: list[dict[str, object]]
    worker_backend: str
    airfoil_feedback: dict[str, Any]
    launch_summary: dict[str, Any]
    turn_summary: dict[str, Any]
    trim_summary: dict[str, Any]
    local_stall_summary: dict[str, Any]
    mission_summary: dict[str, Any]
    ranking_input: CandidateConceptResult


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _airfoil_data_dir() -> Path:
    return _repo_root() / "data" / "airfoils"


@lru_cache(maxsize=None)
def _load_seed_airfoil_coordinates(seed_name: str) -> tuple[tuple[float, float], ...]:
    dat_path = _airfoil_data_dir() / f"{seed_name}.dat"
    if not dat_path.is_file():
        raise FileNotFoundError(f"Seed airfoil .dat file not found: {dat_path}")

    coordinates: list[tuple[float, float]] = []
    for line in dat_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            coordinates.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if len(coordinates) < 3:
        raise ValueError(f"Seed airfoil file {dat_path} did not contain enough coordinates.")
    return tuple(coordinates)


def _seed_airfoil_name(zone_name: str, zone_index: int, zone_count: int) -> str:
    midpoint_fraction = _zone_midpoint_fraction(zone_name, zone_index, zone_count)
    return _ROOT_SEED_AIRFOIL if midpoint_fraction <= 0.5 else _TIP_SEED_AIRFOIL


def _build_seed_airfoil_templates(
    zone_requirements: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    zone_items = list(zone_requirements.items())
    for zone_index, (zone_name, zone_data) in enumerate(zone_items):
        seed_name = _seed_airfoil_name(zone_name, zone_index, len(zone_items))
        coordinates = _load_seed_airfoil_coordinates(seed_name)
        templates[zone_name] = {
            "template_id": f"{zone_name}-seed",
            "seed_name": seed_name,
            "geometry_hash": geometry_hash_from_coordinates(coordinates),
            "coordinates": [list(point) for point in coordinates],
            "points": zone_data.get("points", []),
            "point_count": len(zone_data.get("points", [])),
        }
    return templates


def _build_selected_cst_airfoil_templates(
    *,
    selected_by_zone: dict[str, SelectedZoneCandidate],
    zone_requirements: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    for zone_name, selected in selected_by_zone.items():
        template = selected.template
        templates[zone_name] = {
            "authority": "cst_candidate",
            "template_id": f"{zone_name}-{template.candidate_role}",
            "zone_name": zone_name,
            "seed_name": template.seed_name,
            "candidate_role": template.candidate_role,
            "upper_coefficients": list(template.upper_coefficients),
            "lower_coefficients": list(template.lower_coefficients),
            "te_thickness_m": float(template.te_thickness_m),
            "geometry_hash": geometry_hash_from_coordinates(selected.coordinates),
            "coordinates": [list(point) for point in selected.coordinates],
            "selected_mean_cd": float(selected.mean_cd),
            "selected_mean_cm": float(selected.mean_cm),
            "selected_usable_clmax": float(selected.usable_clmax),
            "points": zone_requirements[zone_name].get("points", []),
        }
    return templates


def _selection_stubbed_metrics(
    *,
    cl_samples: tuple[float, ...],
    cm_target: float = -0.10,
) -> dict[str, object]:
    target_cl = max(cl_samples, default=0.70)
    return {
        "status": "stubbed_ok",
        "mean_cd": 0.020,
        "mean_cm": cm_target,
        "usable_clmax": target_cl + 0.20,
    }


class _SelectionWorkerAdapter:
    def __init__(self, worker: AirfoilWorker, *, allow_stub_fallback: bool) -> None:
        self._worker = worker
        self._allow_stub_fallback = allow_stub_fallback

    def run_queries(self, queries: list[PolarQuery]) -> list[dict[str, object]]:
        raw_results = self._worker.run_queries(queries)
        if not isinstance(raw_results, list):
            raise RuntimeError("Selection worker adapter expected a list of worker results.")

        raw_by_template_id: dict[str, dict[str, object]] = {}
        for item in raw_results:
            if not isinstance(item, dict):
                raise RuntimeError("Selection worker adapter expected dictionary worker results.")
            template_id = item.get("template_id")
            if isinstance(template_id, str):
                if template_id in raw_by_template_id:
                    raise RuntimeError(
                        f"Selection worker returned duplicate template_id {template_id!r}."
                    )
                raw_by_template_id[template_id] = item

        normalized_results: list[dict[str, object]] = []
        for query in queries:
            raw_result = raw_by_template_id.get(query.template_id)
            if raw_result is None:
                if not self._allow_stub_fallback:
                    raise RuntimeError(
                        f"Selection worker did not return template_id {query.template_id!r}."
                    )
                normalized_results.append(
                    {
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        **_selection_stubbed_metrics(cl_samples=query.cl_samples),
                    }
                )
                continue

            result_geometry_hash = raw_result.get("geometry_hash")
            if result_geometry_hash is not None and result_geometry_hash != query.geometry_hash:
                raise RuntimeError(
                    "Selection worker returned a geometry_hash that did not match the requested CST candidate."
                )

            status = str(raw_result.get("status", "unknown"))
            has_direct_metrics = all(
                key in raw_result for key in ("mean_cd", "mean_cm", "usable_clmax")
            )
            has_polar_points = isinstance(raw_result.get("polar_points"), list) and bool(
                raw_result.get("polar_points")
            )
            if status == "cli_stubbed" or (
                status in {"ok", "stubbed_ok"} and not has_direct_metrics and not has_polar_points
            ):
                if not self._allow_stub_fallback:
                    raise RuntimeError(
                        f"Selection worker returned unusable metrics for template_id {query.template_id!r}."
                    )
                normalized_results.append(
                    {
                        **raw_result,
                        "status": "stubbed_ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        **_selection_stubbed_metrics(cl_samples=query.cl_samples),
                    }
                )
                continue

            normalized_results.append(raw_result)
        return normalized_results


def _build_fallback_selected_zone_candidate(
    *,
    zone_name: str,
    seed_coordinates: tuple[tuple[float, float], ...],
) -> SelectedZoneCandidate:
    seed_name = _ROOT_SEED_AIRFOIL if zone_name in {"root", "mid1"} else _TIP_SEED_AIRFOIL
    base_template = build_base_cst_template(
        zone_name=zone_name,
        seed_name=seed_name,
        seed_coordinates=seed_coordinates,
    )
    coordinates = generate_cst_coordinates(base_template)
    validity = validate_cst_candidate_coordinates(coordinates)
    if not validity.valid:
        raise ValueError(
            f"Base CST candidate for zone {zone_name!r} was invalid during pipeline fallback: {validity.reason}."
        )
    stubbed_metrics = _selection_stubbed_metrics(cl_samples=())
    return SelectedZoneCandidate(
        template=base_template,
        coordinates=coordinates,
        mean_cd=float(stubbed_metrics["mean_cd"]),
        mean_cm=float(stubbed_metrics["mean_cm"]),
        usable_clmax=float(stubbed_metrics["usable_clmax"]),
        candidate_score=0.0,
    )


def _default_spanwise_loader(
    concept: GeometryConcept, stations: tuple[WingStation, ...]
) -> dict[str, dict[str, Any]]:
    zones = ("root", "mid1", "mid2", "tip")
    if not stations:
        return {zone: {"points": []} for zone in zones}

    zone_payload: dict[str, dict[str, Any]] = {zone: {"points": []} for zone in zones}
    for index, station in enumerate(stations):
        zone = zones[min(index * len(zones) // len(stations), len(zones) - 1)]
        zone_payload[zone]["points"].append(
            {
                "reynolds": 250000.0 + 10000.0 * index,
                "chord_m": station.chord_m,
                "cl_target": max(0.5, 0.72 - 0.02 * index),
                "cm_target": -0.10 + 0.01 * index,
                "weight": 1.0,
                "station_y_m": station.y_m,
            }
        )
    return zone_payload


def _air_density_from_environment(cfg: BirdmanConceptConfig) -> float:
    """Approximate humid-air density from the configured environment."""

    temp_c = float(cfg.environment.temperature_c)
    temp_k = temp_c + 273.15
    altitude_m = float(cfg.environment.altitude_m)
    relative_humidity = max(0.0, min(1.0, float(cfg.environment.relative_humidity) / 100.0))
    if altitude_m < -100.0 or altitude_m > 11000.0:
        raise ValueError(
            "environment.altitude_m must be within -100 m to 11000 m for the tropospheric density approximation."
        )

    pressure_pa = 101325.0 * (1.0 - 2.25577e-5 * altitude_m) ** 5.25588
    saturation_vapor_pa = 610.94 * math.exp((17.625 * temp_c) / (temp_c + 243.04))
    vapor_pa = relative_humidity * saturation_vapor_pa
    dry_pa = max(0.0, pressure_pa - vapor_pa)
    return dry_pa / (287.058 * temp_k) + vapor_pa / (461.495 * temp_k)


def _zone_midpoint_fraction(zone_name: str, zone_index: int, zone_count: int) -> float:
    named_defaults = {
        "root": 0.125,
        "mid1": 0.40,
        "mid2": 0.675,
        "tip": 0.90,
    }
    if zone_name in named_defaults:
        return named_defaults[zone_name]
    if zone_count <= 0:
        return 0.5
    return (zone_index + 0.5) / float(zone_count)


def _flatten_zone_points(
    zone_requirements: dict[str, dict[str, Any]],
    stations: tuple[WingStation, ...],
) -> list[dict[str, float]]:
    """Flatten zone targets into station-like safety points.

    The zone loader may or may not provide explicit station locations. When the
    location is omitted we place the point at the center of its zone, using the
    current station layout as the span reference.
    """

    if not zone_requirements:
        raise ValueError("zone_requirements must not be empty.")

    half_span_m = float(stations[-1].y_m) if stations else 0.0
    zone_items = list(zone_requirements.items())
    flattened: list[dict[str, float]] = []

    for zone_index, (zone_name, zone_data) in enumerate(zone_items):
        points = zone_data.get("points", [])
        for point_index, point in enumerate(points):
            if "cl_target" not in point or "cm_target" not in point:
                raise ValueError("zone point entries must include cl_target and cm_target.")
            station_y_m = point.get("station_y_m")
            if station_y_m is None:
                station_y_m = (
                    _zone_midpoint_fraction(zone_name, zone_index, len(zone_items)) * half_span_m
                )
            flattened.append(
                {
                    "zone_name": zone_name,
                    "zone_index": float(zone_index),
                    "point_index": float(point_index),
                    "station_y_m": float(station_y_m),
                    "chord_m": float(point.get("chord_m", 1.0)),
                    "cl_target": float(point["cl_target"]),
                    "cm_target": float(point["cm_target"]),
                    "weight": float(point.get("weight", 1.0)),
                    "reynolds": float(point.get("reynolds", 0.0)),
                    "reference_speed_mps": _numeric_value(zone_data.get("reference_speed_mps")),
                    "reference_gross_mass_kg": _numeric_value(zone_data.get("reference_gross_mass_kg")),
                }
            )

    if flattened:
        return flattened

    if not stations:
        raise ValueError("zone_requirements must contain at least one point or stations must exist.")

    # Honest fallback when the loader does not provide zone targets. The current
    # concept geometry still drives a coarse spanwise load shape instead of a
    # hard-coded stub.
    fallback: list[dict[str, float]] = []
    for station in stations:
        eta = 0.0 if half_span_m <= 0.0 else float(station.y_m) / half_span_m
        fallback.append(
            {
                "zone_name": "fallback",
                "zone_index": 0.0,
                "point_index": float(len(fallback)),
                "station_y_m": float(station.y_m),
                "cl_target": 0.72 - 0.14 * eta + 0.02 * (1.0 - eta),
                "cm_target": -0.09 - 0.03 * eta,
                "weight": 1.0,
                "reynolds": 0.0,
            }
        )
    return fallback


def _attach_cl_max_proxies(
    station_points: list[dict[str, float]],
    *,
    half_span_m: float,
    concept: GeometryConcept,
) -> list[dict[str, float]]:
    enriched: list[dict[str, float]] = []
    span_ratio = 0.0 if concept.span_m <= 0.0 else concept.span_m / max(concept.wing_area_m2, 1.0)
    twist_delta = abs(concept.twist_tip_deg - concept.twist_root_deg)

    for point in station_points:
        eta = 0.0 if half_span_m <= 0.0 else min(max(point["station_y_m"] / half_span_m, 0.0), 1.0)
        cl_headroom = 0.24 - 0.09 * eta - 0.015 * (twist_delta / 5.0) + 0.01 * min(span_ratio, 1.2)
        cl_headroom = min(max(cl_headroom, 0.08), 0.30)
        cl_max_proxy = point["cl_target"] + cl_headroom
        enriched.append(
            {
                **point,
                "cl_max_proxy": cl_max_proxy,
                "cl_max_effective": cl_max_proxy,
                "cl_max_effective_source": "geometry_proxy",
                "cm_effective": float(point["cm_target"]),
                "cm_effective_source": "zone_target_proxy",
                "cd_effective": None,
                "cd_effective_source": "not_available",
                "airfoil_feedback_applied": False,
            }
        )
    return enriched


def _numeric_value(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _cl_limit(point: dict[str, float]) -> float:
    if "cl_max_safe" in point:
        return float(point["cl_max_safe"])
    return float(point.get("cl_max_effective", point["cl_max_proxy"]))


def _safe_clmax_source(raw_source: str) -> str:
    source_map = {
        "airfoil_observed_lower_bound": "airfoil_safe_lower_bound",
        "airfoil_observed": "airfoil_safe_observed",
        "geometry_proxy": "geometry_safe_proxy",
    }
    return source_map.get(raw_source, f"safe_clmax_model_v1:{raw_source}")


def _apply_safe_clmax_model(
    station_points: list[dict[str, float]],
    *,
    safe_scale: float,
    safe_delta: float,
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    safe_points: list[dict[str, float]] = []
    raw_values: list[float] = []
    safe_values: list[float] = []

    for point in station_points:
        raw_clmax = float(point.get("cl_max_effective", point["cl_max_proxy"]))
        raw_source = str(point.get("cl_max_effective_source", "geometry_proxy"))
        safe_clmax = max(0.10, float(safe_scale) * raw_clmax - float(safe_delta))
        raw_values.append(raw_clmax)
        safe_values.append(safe_clmax)
        safe_points.append(
            {
                **point,
                "cl_max_raw": raw_clmax,
                "cl_max_raw_source": raw_source,
                "cl_max_safe": safe_clmax,
                "cl_max_safe_source": _safe_clmax_source(raw_source),
                "cl_max_safe_scale": float(safe_scale),
                "cl_max_safe_delta": float(safe_delta),
            }
        )

    summary = {
        "safe_clmax_applied": True,
        "safe_clmax_scale": float(safe_scale),
        "safe_clmax_delta": float(safe_delta),
        "min_cl_max_raw": min(raw_values) if raw_values else None,
        "min_cl_max_safe": min(safe_values) if safe_values else None,
    }
    return safe_points, summary


def _build_worker_queries_and_refs(
    *,
    zone_requirements: dict[str, dict[str, Any]],
    airfoil_templates: dict[str, dict[str, Any]],
) -> tuple[list[PolarQuery], list[dict[str, Any]]]:
    worker_queries: list[PolarQuery] = []
    worker_point_refs: list[dict[str, Any]] = []

    for zone_index, (zone_name, zone_data) in enumerate(zone_requirements.items()):
        airfoil_template = airfoil_templates[zone_name]
        coordinates = tuple(
            (float(point[0]), float(point[1])) for point in airfoil_template["coordinates"]
        )
        for point_index, point in enumerate(zone_data.get("points", []), start=1):
            template_id = f"{airfoil_template['template_id']}-{point_index:02d}"
            worker_queries.append(
                PolarQuery(
                    template_id=template_id,
                    reynolds=float(point["reynolds"]),
                    cl_samples=(float(point["cl_target"]),),
                    roughness_mode="clean",
                    geometry_hash=str(airfoil_template["geometry_hash"]),
                    coordinates=coordinates,
                )
            )
            worker_point_refs.append(
                {
                    "template_id": template_id,
                    "zone_name": zone_name,
                    "zone_index": zone_index,
                    "point_index": point_index,
                    "station_point_index": len(worker_point_refs),
                }
            )

    return worker_queries, worker_point_refs


def _selected_polar_point(polar_points: list[dict[str, object]]) -> dict[str, object] | None:
    best_point: dict[str, object] | None = None
    best_error = float("inf")
    for point in polar_points:
        if not isinstance(point, dict):
            continue
        cl_value = _numeric_value(point.get("cl"))
        cm_value = _numeric_value(point.get("cm"))
        cd_value = _numeric_value(point.get("cd"))
        if cl_value is None or cm_value is None or cd_value is None:
            continue
        cl_error = _numeric_value(point.get("cl_error"))
        if cl_error is None:
            cl_target = _numeric_value(point.get("cl_target"))
            cl_error = abs(cl_value - cl_target) if cl_target is not None else 0.0
        if cl_error < best_error:
            best_error = cl_error
            best_point = point
    return best_point


def _extract_worker_feedback(result: dict[str, object]) -> dict[str, object] | None:
    if str(result.get("status")) != "ok":
        return None

    polar_points = result.get("polar_points")
    if not isinstance(polar_points, list) or not polar_points:
        return None

    sweep_summary = result.get("sweep_summary")
    if not isinstance(sweep_summary, dict):
        return None

    cl_max_observed = _numeric_value(sweep_summary.get("cl_max_observed"))
    if cl_max_observed is None:
        cl_max_observed = _numeric_value(sweep_summary.get("first_pass_observed_clmax_proxy"))
    if cl_max_observed is None:
        return None

    selected_point = _selected_polar_point(polar_points)
    if selected_point is None:
        return None

    worker_cl = _numeric_value(selected_point.get("cl"))
    worker_cm = _numeric_value(selected_point.get("cm"))
    worker_cd = _numeric_value(selected_point.get("cd"))
    worker_cdp = _numeric_value(selected_point.get("cdp"))
    if worker_cl is None or worker_cm is None or worker_cd is None:
        return None

    return {
        "worker_cl": worker_cl,
        "worker_cm": worker_cm,
        "worker_cd": worker_cd,
        "worker_cdp": worker_cdp,
        "worker_cl_error": _numeric_value(selected_point.get("cl_error")),
        "cl_max_observed": cl_max_observed,
        "alpha_at_cl_max_deg": (
            _numeric_value(sweep_summary.get("alpha_at_cl_max_deg"))
            if _numeric_value(sweep_summary.get("alpha_at_cl_max_deg")) is not None
            else _numeric_value(sweep_summary.get("first_pass_observed_clmax_proxy_alpha_deg"))
        ),
        "last_converged_alpha_deg": _numeric_value(sweep_summary.get("last_converged_alpha_deg")),
        "clmax_is_lower_bound": bool(
            sweep_summary.get("clmax_is_lower_bound")
            if sweep_summary.get("clmax_is_lower_bound") is not None
            else sweep_summary.get("first_pass_observed_clmax_proxy_at_sweep_edge", False)
        ),
        "sweep_point_count": int(_numeric_value(sweep_summary.get("sweep_point_count")) or 0.0),
        "converged_point_count": int(
            _numeric_value(sweep_summary.get("converged_point_count")) or 0.0
        ),
    }


def _apply_worker_airfoil_feedback(
    *,
    station_points: list[dict[str, float]],
    worker_point_refs: list[dict[str, Any]],
    worker_results: list[dict[str, object]],
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    enriched_points = [dict(point) for point in station_points]
    if len(worker_point_refs) != len(worker_results):
        fallback_rows: list[dict[str, Any]] = []
        for ref in worker_point_refs:
            point_index = int(ref["station_point_index"])
            base_point = enriched_points[point_index]
            fallback_rows.append(
                {
                    "template_id": ref["template_id"],
                    "zone_name": ref["zone_name"],
                    "zone_index": ref["zone_index"],
                    "point_index": ref["point_index"],
                    "station_point_index": point_index,
                    "status": "worker_result_count_mismatch",
                    "applied": False,
                    "fallback_reason": "worker_result_count_mismatch",
                    "cl_target": float(base_point["cl_target"]),
                    "cm_target": float(base_point["cm_target"]),
                    "cl_max_proxy": float(base_point["cl_max_proxy"]),
                }
            )
        return (
            [dict(point) for point in station_points],
            {
                "applied": False,
                "mode": "geometry_proxy",
                "worker_result_count": len(worker_results),
                "expected_worker_point_count": len(worker_point_refs),
                "usable_worker_point_count": 0,
                "fallback_worker_point_count": len(worker_point_refs),
                "fallback_reason": "worker_result_count_mismatch",
                "points": fallback_rows,
            },
        )

    feedback_rows: list[dict[str, Any]] = []
    usable_worker_point_count = 0
    observed_cd_values: list[float] = []
    observed_clmax_values: list[float] = []

    for ref, result in zip(worker_point_refs, worker_results):
        point_index = int(ref["station_point_index"])
        base_point = enriched_points[point_index]
        feedback = _extract_worker_feedback(result)
        fallback_row = {
            "template_id": ref["template_id"],
            "zone_name": ref["zone_name"],
            "zone_index": ref["zone_index"],
            "point_index": ref["point_index"],
            "station_point_index": point_index,
            "status": str(result.get("status", "unknown")),
            "applied": False,
            "fallback_reason": "missing_usable_polar_points",
            "cl_target": float(base_point["cl_target"]),
            "cm_target": float(base_point["cm_target"]),
            "cl_max_proxy": float(base_point["cl_max_proxy"]),
        }
        if feedback is None:
            feedback_rows.append(fallback_row)
            continue

        usable_worker_point_count += 1
        observed_cd_values.append(float(feedback["worker_cd"]))
        observed_clmax_values.append(float(feedback["cl_max_observed"]))
        updated_point = {
            **base_point,
            "worker_cl": float(feedback["worker_cl"]),
            "worker_cl_error": feedback["worker_cl_error"],
            "worker_cm": float(feedback["worker_cm"]),
            "worker_cd": float(feedback["worker_cd"]),
            "worker_cdp": feedback["worker_cdp"],
            "cl_max_effective": float(feedback["cl_max_observed"]),
            "cl_max_effective_source": (
                "airfoil_observed_lower_bound"
                if feedback["clmax_is_lower_bound"]
                else "airfoil_observed"
            ),
            "cm_effective": float(feedback["worker_cm"]),
            "cm_effective_source": "airfoil_near_target",
            "cd_effective": float(feedback["worker_cd"]),
            "cd_effective_source": "airfoil_near_target",
            "airfoil_feedback_applied": True,
            "airfoil_feedback_source": "worker_polar_feedback",
            "airfoil_feedback_worker_status": str(result.get("status", "unknown")),
            "airfoil_feedback_template_id": ref["template_id"],
            "airfoil_feedback_zone_name": ref["zone_name"],
            "airfoil_feedback_zone_index": float(ref["zone_index"]),
            "airfoil_feedback_point_index": float(ref["point_index"]),
            "airfoil_feedback_station_point_index": float(point_index),
            "airfoil_feedback_cl_max_observed": float(feedback["cl_max_observed"]),
            "airfoil_feedback_alpha_at_cl_max_deg": feedback["alpha_at_cl_max_deg"],
            "airfoil_feedback_last_converged_alpha_deg": feedback["last_converged_alpha_deg"],
            "airfoil_feedback_clmax_is_lower_bound": bool(feedback["clmax_is_lower_bound"]),
            "airfoil_feedback_sweep_point_count": feedback["sweep_point_count"],
            "airfoil_feedback_converged_point_count": feedback["converged_point_count"],
        }
        enriched_points[point_index] = updated_point
        feedback_rows.append(
            {
                "template_id": ref["template_id"],
                "zone_name": ref["zone_name"],
                "zone_index": ref["zone_index"],
                "point_index": ref["point_index"],
                "station_point_index": point_index,
                "status": str(result.get("status", "unknown")),
                "applied": True,
                "cl_target": float(base_point["cl_target"]),
                "cm_target": float(base_point["cm_target"]),
                "cl_max_proxy": float(base_point["cl_max_proxy"]),
                "worker_cl": float(updated_point["worker_cl"]),
                "worker_cl_error": updated_point["worker_cl_error"],
                "worker_cm": float(updated_point["worker_cm"]),
                "worker_cd": float(updated_point["worker_cd"]),
                "worker_cdp": updated_point["worker_cdp"],
                "cl_max_effective": float(updated_point["cl_max_effective"]),
                "cl_max_effective_source": updated_point["cl_max_effective_source"],
                "cm_effective": float(updated_point["cm_effective"]),
                "cd_effective": float(updated_point["cd_effective"]),
                "cl_max_observed": float(updated_point["airfoil_feedback_cl_max_observed"]),
                "alpha_at_cl_max_deg": updated_point["airfoil_feedback_alpha_at_cl_max_deg"],
                "clmax_is_lower_bound": updated_point["airfoil_feedback_clmax_is_lower_bound"],
            }
        )

    feedback_summary = {
        "applied": usable_worker_point_count > 0,
        "mode": "airfoil_informed" if usable_worker_point_count > 0 else "geometry_proxy",
        "worker_result_count": len(worker_results),
        "usable_worker_point_count": usable_worker_point_count,
        "fallback_worker_point_count": len(worker_results) - usable_worker_point_count,
        "mean_cd_effective": (
            sum(observed_cd_values) / len(observed_cd_values) if observed_cd_values else None
        ),
        "min_cl_max_effective": min(observed_clmax_values) if observed_clmax_values else None,
        "points": feedback_rows,
    }
    if usable_worker_point_count == 0:
        return [dict(point) for point in station_points], feedback_summary
    return enriched_points, feedback_summary


def _summarize_launch(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
    trim_result,
    air_density_kg_per_m3: float,
) -> tuple[dict[str, Any], float, float]:
    q_pa = 0.5 * air_density_kg_per_m3 * float(cfg.launch.release_speed_mps) ** 2
    gross_mass_kg = float(max(cfg.mass.gross_mass_sweep_kg))
    cl_required = (gross_mass_kg * 9.80665) / max(q_pa * concept.wing_area_m2, 1.0e-9)
    limiting_point = min(station_points, key=_cl_limit)
    cl_available = _cl_limit(limiting_point)
    cl_available_source = str(
        limiting_point.get(
            "cl_max_safe_source",
            limiting_point.get("cl_max_effective_source", "geometry_proxy"),
        )
    )

    launch_result = evaluate_launch_gate(
        platform_height_m=cfg.launch.platform_height_m,
        wing_span_m=concept.span_m,
        speed_mps=cfg.launch.release_speed_mps,
        cl_required=cl_required,
        cl_available=cl_available,
        trim_margin_deg=trim_result.margin_deg,
        required_trim_margin_deg=cfg.launch.min_trim_margin_deg,
        stall_utilization_limit=cfg.stall_model.launch_utilization_limit,
        use_ground_effect=cfg.launch.use_ground_effect,
    )
    return (
        {
            "status": launch_result.reason,
            "feasible": launch_result.feasible,
            "ground_effect_applied": launch_result.ground_effect_applied,
            "adjusted_cl_required": launch_result.adjusted_cl_required,
            "cl_required": cl_required,
            "cl_available": cl_available,
            "cl_available_source": cl_available_source,
            "stall_utilization": launch_result.stall_utilization,
            "stall_utilization_limit": launch_result.stall_utilization_limit,
            "trim_margin_deg": trim_result.margin_deg,
            "required_trim_margin_deg": cfg.launch.min_trim_margin_deg,
            "release_speed_mps": cfg.launch.release_speed_mps,
            "air_density_kg_per_m3": air_density_kg_per_m3,
            "gross_mass_kg": gross_mass_kg,
            "dynamic_pressure_pa": q_pa,
        },
        cl_required,
        cl_available,
    )


def _summarize_turn(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
    trim_result,
) -> dict[str, Any]:
    evaluation_speed_mps = float(cfg.launch.release_speed_mps)
    evaluation_gross_mass_kg = float(max(cfg.mass.gross_mass_sweep_kg))

    scaled_station_points: list[dict[str, float]] = []
    cl_scale_factors: list[float] = []
    for point in station_points:
        reference_speed_mps = _numeric_value(point.get("reference_speed_mps"))
        reference_gross_mass_kg = _numeric_value(point.get("reference_gross_mass_kg"))
        cl_scale = 1.0
        if (
            reference_speed_mps is not None
            and reference_speed_mps > 0.0
            and reference_gross_mass_kg is not None
            and reference_gross_mass_kg > 0.0
        ):
            cl_scale = (
                evaluation_gross_mass_kg / reference_gross_mass_kg
            ) * (reference_speed_mps / evaluation_speed_mps) ** 2
        cl_scale_factors.append(cl_scale)
        scaled_station_points.append(
            {
                **point,
                "cl_target": float(point["cl_target"]) * cl_scale,
                "turn_cl_scale_factor": cl_scale,
            }
        )

    turn_result = evaluate_turn_gate(
        bank_angle_deg=cfg.turn.required_bank_angle_deg,
        speed_mps=evaluation_speed_mps,
        station_points=scaled_station_points,
        half_span_m=0.5 * concept.span_m,
        trim_feasible=trim_result.feasible,
        stall_utilization_limit=cfg.stall_model.turn_utilization_limit,
    )
    return {
        "status": turn_result.reason,
        "feasible": turn_result.feasible,
        "bank_angle_deg": cfg.turn.required_bank_angle_deg,
        "speed_mps": cfg.launch.release_speed_mps,
        "load_factor": turn_result.load_factor,
        "cl_level": turn_result.cl_level,
        "required_cl": turn_result.required_cl,
        "cl_max": turn_result.cl_max,
        "cl_max_source": turn_result.cl_max_source,
        "stall_margin": turn_result.stall_margin,
        "stall_utilization": turn_result.stall_utilization,
        "stall_utilization_limit": turn_result.stall_utilization_limit,
        "trim_feasible": trim_result.feasible,
        "limiting_station_y_m": turn_result.limiting_station_y_m,
        "tip_critical": turn_result.tip_critical,
        "evaluation_gross_mass_kg": evaluation_gross_mass_kg,
        "reference_speed_mps": _numeric_value(station_points[0].get("reference_speed_mps")),
        "reference_gross_mass_kg": _numeric_value(station_points[0].get("reference_gross_mass_kg")),
        "cl_scale_factor_min": min(cl_scale_factors) if cl_scale_factors else 1.0,
        "cl_scale_factor_max": max(cl_scale_factors) if cl_scale_factors else 1.0,
    }


def _summarize_trim(
    *,
    cfg: BirdmanConceptConfig,
    station_points: list[dict[str, float]],
) -> tuple[dict[str, Any], Any]:
    effective_points = [
        (
            float(point.get("cm_effective", point["cm_target"])),
            max(float(point.get("weight", 1.0)) * float(point.get("chord_m", 1.0)), 1.0e-9),
            point,
        )
        for point in station_points
    ]
    total_weight = sum(weight for _, weight, _ in effective_points)
    if total_weight <= 0.0:
        total_weight = float(len(effective_points)) or 1.0
    weighted_mean_cm = sum(cm * weight for cm, weight, _ in effective_points) / total_weight
    cm_rms = math.sqrt(
        sum(weight * (cm - weighted_mean_cm) ** 2 for cm, weight, _ in effective_points)
        / total_weight
    )
    dominant_point = max(
        effective_points,
        key=lambda item: abs(item[0]) * item[1],
    )[2]
    representative_cm = float(weighted_mean_cm)
    representative_cm_source = str(
        dominant_point.get("cm_effective_source", "zone_target_proxy")
    )
    trim_result = evaluate_trim_proxy(
        representative_cm=representative_cm,
        required_margin_deg=cfg.launch.min_trim_margin_deg,
        cm_spread=cm_rms,
    )
    return {
        "status": trim_result.reason,
        "feasible": trim_result.feasible,
        "representative_cm": representative_cm,
        "representative_cm_source": representative_cm_source,
        "cm_rms": cm_rms,
        "margin_deg": trim_result.margin_deg,
        "required_margin_deg": trim_result.required_margin_deg,
        "required_trim_margin_deg": cfg.launch.min_trim_margin_deg,
    }, trim_result


def _summarize_local_stall(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
) -> dict[str, Any]:
    local_stall_result = evaluate_local_stall(
        station_points=station_points,
        half_span_m=0.5 * concept.span_m,
        stall_utilization_limit=cfg.stall_model.local_stall_utilization_limit,
    )
    return {
        "status": local_stall_result.reason,
        "feasible": local_stall_result.feasible,
        "required_cl": local_stall_result.required_cl,
        "cl_max": local_stall_result.cl_max,
        "min_margin": local_stall_result.min_margin,
        "stall_utilization": local_stall_result.stall_utilization,
        "stall_utilization_limit": local_stall_result.stall_utilization_limit,
        "min_margin_station_y_m": local_stall_result.min_margin_station_y_m,
        "tip_critical": local_stall_result.tip_critical,
        "margin_source": local_stall_result.cl_max_source,
    }


def _speed_sweep_mps(cfg: BirdmanConceptConfig) -> tuple[float, ...]:
    point_count = int(cfg.mission.speed_sweep_points)
    if point_count < 2:
        raise ValueError("mission.speed_sweep_points must be at least 2.")
    min_speed = float(cfg.mission.speed_sweep_min_mps)
    max_speed = float(cfg.mission.speed_sweep_max_mps)
    step = (max_speed - min_speed) / float(point_count - 1)
    return tuple(min_speed + step * index for index in range(point_count))


def _mean_effective_cd(
    station_points: list[dict[str, float]],
    airfoil_feedback: dict[str, Any],
) -> float:
    weighted_values: list[tuple[float, float]] = []
    for point in station_points:
        cd_value = _numeric_value(point.get("cd_effective"))
        if cd_value is None:
            continue
        weighted_values.append((cd_value, float(point.get("weight", 1.0))))
    if weighted_values:
        total_weight = sum(weight for _, weight in weighted_values)
        if total_weight > 0.0:
            return sum(value * weight for value, weight in weighted_values) / total_weight

    mean_cd = _numeric_value(airfoil_feedback.get("mean_cd_effective"))
    if mean_cd is not None:
        return mean_cd
    return 0.020


def _assembly_penalty(concept: GeometryConcept) -> float:
    joint_count = max(0, len(concept.segment_lengths_m) - 1)
    return 0.5 * float(joint_count)


def _oswald_efficiency_proxy(concept: GeometryConcept) -> float:
    dihedral_delta = max(0.0, float(concept.dihedral_tip_deg) - float(concept.dihedral_root_deg))
    twist_delta = abs(float(concept.twist_tip_deg) - float(concept.twist_root_deg))
    efficiency = 0.88 - 0.012 * dihedral_delta - 0.008 * twist_delta
    return max(0.68, min(0.92, efficiency))


def _shaft_power_required_w(
    *,
    drag_n: float,
    speed_mps: float,
    prop_model: SimplifiedPropModel,
) -> float:
    shaft_power_w = drag_n * speed_mps / max(prop_model.design_efficiency, 1.0e-6)
    for _ in range(3):
        eta_prop = prop_model.efficiency(
            speed_mps=speed_mps,
            shaft_power_w=max(shaft_power_w, 1.0),
        )
        shaft_power_w = drag_n * speed_mps / max(eta_prop, 1.0e-6)
    return shaft_power_w


def _build_concept_mission_summary(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
    airfoil_feedback: dict[str, Any],
    air_density_kg_per_m3: float,
) -> dict[str, Any]:
    speed_sweep_mps = _speed_sweep_mps(cfg)
    profile_cd = _mean_effective_cd(station_points, airfoil_feedback)
    aspect_ratio = concept.span_m**2 / max(concept.wing_area_m2, 1.0e-9)
    oswald_efficiency = _oswald_efficiency_proxy(concept)
    tail_area_ratio = concept.tail_area_m2 / max(concept.wing_area_m2, 1.0e-9)
    misc_cd = 0.0035 + 0.20 * tail_area_ratio * profile_cd
    prop_model = SimplifiedPropModel(
        diameter_m=float(cfg.prop.diameter_m),
        rpm_min=float(cfg.prop.rpm_min),
        rpm_max=float(cfg.prop.rpm_max),
        design_efficiency=0.83,
    )
    rider_curve = FakeAnchorCurve(
        anchor_power_w=float(cfg.mission.anchor_power_w),
        anchor_duration_min=float(cfg.mission.anchor_duration_min),
    )

    mission_results: list[tuple[float, MissionEvaluationResult, tuple[float, ...]]] = []
    for gross_mass_kg in cfg.mass.gross_mass_sweep_kg:
        weight_n = float(gross_mass_kg) * 9.80665
        power_required_w: list[float] = []
        for speed_mps in speed_sweep_mps:
            dynamic_pressure_pa = 0.5 * air_density_kg_per_m3 * speed_mps**2
            cl_required = weight_n / max(dynamic_pressure_pa * concept.wing_area_m2, 1.0e-9)
            induced_cd = cl_required**2 / max(math.pi * aspect_ratio * oswald_efficiency, 1.0e-9)
            total_cd = profile_cd + induced_cd + misc_cd
            drag_n = dynamic_pressure_pa * concept.wing_area_m2 * total_cd
            power_required_w.append(
                _shaft_power_required_w(
                    drag_n=drag_n,
                    speed_mps=speed_mps,
                    prop_model=prop_model,
                )
            )

        mission_result = evaluate_mission_objective(
            MissionEvaluationInputs(
                objective_mode=str(cfg.mission.objective_mode),
                target_range_km=float(cfg.mission.target_distance_km),
                speed_mps=speed_sweep_mps,
                power_required_w=tuple(power_required_w),
                rider_curve=rider_curve,
            )
        )
        mission_results.append((float(gross_mass_kg), mission_result, tuple(power_required_w)))

    worst_case_mass_kg, worst_case_result, worst_case_power_required_w = max(
        mission_results,
        key=lambda item: float(item[1].mission_score),
    )
    return {
        "mission_objective_mode": worst_case_result.mission_objective_mode,
        "mission_feasible": all(result.mission_feasible for _, result, _ in mission_results),
        "target_range_km": worst_case_result.target_range_km,
        "target_range_passed": all(result.target_range_passed for _, result, _ in mission_results),
        "target_range_margin_m": min(
            result.target_range_margin_m for _, result, _ in mission_results
        ),
        "best_range_m": worst_case_result.best_range_m,
        "best_range_speed_mps": worst_case_result.best_range_speed_mps,
        "best_endurance_s": worst_case_result.best_endurance_s,
        "min_power_w": worst_case_result.min_power_w,
        "min_power_speed_mps": worst_case_result.min_power_speed_mps,
        "mission_score": worst_case_result.mission_score,
        "mission_score_reason": worst_case_result.mission_score_reason,
        "pilot_power_model": worst_case_result.pilot_power_model,
        "pilot_power_anchor": worst_case_result.pilot_power_anchor,
        "speed_sweep_window_mps": list(worst_case_result.speed_sweep_window_mps),
        "aggregation_mode": "worst_case_over_gross_mass_sweep",
        "evaluated_gross_mass_kg": worst_case_mass_kg,
        "profile_cd_proxy": profile_cd,
        "misc_cd_proxy": misc_cd,
        "oswald_efficiency_proxy": oswald_efficiency,
        "propulsion_model": "simplified_prop_proxy_v1",
        "mass_cases": [
            {
                "gross_mass_kg": gross_mass_kg,
                "mission_feasible": result.mission_feasible,
                "target_range_passed": result.target_range_passed,
                "target_range_margin_m": result.target_range_margin_m,
                "best_range_m": result.best_range_m,
                "best_range_speed_mps": result.best_range_speed_mps,
                "best_endurance_s": result.best_endurance_s,
                "min_power_w": result.min_power_w,
                "min_power_speed_mps": result.min_power_speed_mps,
                "mission_score": result.mission_score,
                "power_required_w": list(power_required_w),
            }
            for gross_mass_kg, result, power_required_w in mission_results
        ],
        "power_required_w": list(worst_case_power_required_w),
    }


def _concept_safety_margin(
    *,
    launch_summary: dict[str, Any],
    turn_summary: dict[str, Any],
    trim_summary: dict[str, Any],
    local_stall_summary: dict[str, Any],
) -> float:
    launch_margin = float(launch_summary["stall_utilization_limit"]) - float(
        launch_summary["stall_utilization"]
    )
    turn_margin = float(turn_summary["stall_utilization_limit"]) - float(
        turn_summary["stall_utilization"]
    )
    local_margin = float(local_stall_summary["stall_utilization_limit"]) - float(
        local_stall_summary["stall_utilization"]
    )
    trim_margin = (
        float(trim_summary["margin_deg"]) - float(trim_summary["required_trim_margin_deg"])
    ) / 10.0
    return min(launch_margin, turn_margin, local_margin, trim_margin)


def _summarize_spanwise_requirements(
    zone_requirements: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    reference_speeds_mps = sorted(
        {
            float(zone_data["reference_speed_mps"])
            for zone_data in zone_requirements.values()
            if zone_data.get("reference_speed_mps") is not None
        }
    )
    reference_gross_masses_kg = sorted(
        {
            float(zone_data["reference_gross_mass_kg"])
            for zone_data in zone_requirements.values()
            if zone_data.get("reference_gross_mass_kg") is not None
        }
    )
    reference_speed_reasons = sorted(
        {
            str(zone_data["reference_speed_reason"])
            for zone_data in zone_requirements.values()
            if zone_data.get("reference_speed_reason")
        }
    )
    mass_selection_reasons = sorted(
        {
            str(zone_data["mass_selection_reason"])
            for zone_data in zone_requirements.values()
            if zone_data.get("mass_selection_reason")
        }
    )
    sources = sorted(
        {
            str(zone_data.get("source", "unknown"))
            for zone_data in zone_requirements.values()
        }
    )
    fallback_reasons = sorted(
        {
            str(zone_data["fallback_reason"])
            for zone_data in zone_requirements.values()
            if zone_data.get("fallback_reason")
        }
    )
    reference_condition_policies = sorted(
        {
            str(zone_data["reference_condition_policy"])
            for zone_data in zone_requirements.values()
            if zone_data.get("reference_condition_policy")
        }
    )
    return {
        "zone_count": len(zone_requirements),
        "unique_sources": sources,
        "fallback_detected": any(source.startswith("fallback") for source in sources),
        "fallback_reasons": fallback_reasons,
        "reference_condition_policies": reference_condition_policies,
        "reference_speeds_mps": reference_speeds_mps,
        "reference_gross_masses_kg": reference_gross_masses_kg,
        "reference_speed_reasons": reference_speed_reasons,
        "mass_selection_reasons": mass_selection_reasons,
    }


def _default_airfoil_worker_factory(**_: Any) -> AirfoilWorker:
    class _NoopWorker:
        backend_name = "python_stubbed"

        def run_queries(self, queries: list[PolarQuery]) -> list[dict[str, object]]:
            return [
                {
                    "template_id": query.template_id,
                    "reynolds": query.reynolds,
                    "cl_samples": list(query.cl_samples),
                    "roughness_mode": query.roughness_mode,
                    "geometry_hash": query.geometry_hash,
                    "status": "stubbed_ok",
                }
                for query in queries
            ]

    return _NoopWorker()


def _worker_backend(worker: AirfoilWorker) -> str:
    return str(getattr(worker, "backend_name", "python_stubbed"))


def _worker_statuses(worker_results: list[dict[str, object]]) -> tuple[str, ...]:
    statuses: list[str] = []
    for result in worker_results:
        status = result.get("status")
        statuses.append("unknown" if status is None else str(status))
    return tuple(statuses)


def _concept_to_bundle_payload(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    zone_requirements: dict[str, dict[str, Any]],
    airfoil_templates: dict[str, dict[str, Any]],
    worker_results: list[dict[str, object]],
    worker_backend: str,
    concept_index: int,
    enumeration_index: int,
    airfoil_feedback: dict[str, Any],
    launch_summary: dict[str, Any],
    turn_summary: dict[str, Any],
    trim_summary: dict[str, Any],
    local_stall_summary: dict[str, Any],
    mission_summary: dict[str, Any],
    ranking_summary: dict[str, Any],
    spanwise_requirement_summary: dict[str, Any],
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    concept_config = cfg.model_dump(mode="python")
    concept_config["geometry"] = {
        "span_m": concept.span_m,
        "wing_area_m2": concept.wing_area_m2,
        "root_chord_m": concept.root_chord_m,
        "tip_chord_m": concept.tip_chord_m,
        "twist_root_deg": concept.twist_root_deg,
        "twist_tip_deg": concept.twist_tip_deg,
        "dihedral_root_deg": concept.dihedral_root_deg,
        "dihedral_tip_deg": concept.dihedral_tip_deg,
        "dihedral_exponent": concept.dihedral_exponent,
        "tail_area_m2": concept.tail_area_m2,
        "cg_xc": concept.cg_xc,
        "segment_lengths_m": list(concept.segment_lengths_m),
    }

    stations_rows = [
        {
            "y_m": station.y_m,
            "chord_m": station.chord_m,
            "twist_deg": station.twist_deg,
            "dihedral_deg": station.dihedral_deg,
        }
        for station in stations
    ]
    lofting_guides = build_lofting_guides(
        {
            zone_name: CSTAirfoilTemplate(
                zone_name=zone_name,
                upper_coefficients=tuple(payload["upper_coefficients"]),
                lower_coefficients=tuple(payload["lower_coefficients"]),
                te_thickness_m=float(payload["te_thickness_m"]),
                seed_name=payload.get("seed_name"),
                candidate_role=payload.get("candidate_role", "selected"),
            )
            for zone_name, payload in airfoil_templates.items()
        }
    )
    prop_assumption = {
        "blade_count": cfg.prop.blade_count,
        "diameter_m": cfg.prop.diameter_m,
        "rpm_range": [cfg.prop.rpm_min, cfg.prop.rpm_max],
        "position_mode": cfg.prop.position_mode,
        "mode": "simplified",
    }
    worker_statuses = _worker_statuses(worker_results)
    concept_summary = {
        "selected": True,
        "concept_id": f"concept-{concept_index:02d}",
        "enumeration_index": enumeration_index,
        "rank": concept_index,
        "span_m": concept.span_m,
        "wing_area_m2": concept.wing_area_m2,
        "station_count": len(stations),
        "zone_count": len(zone_requirements),
        "worker_result_count": len(worker_results),
        "worker_backend": worker_backend,
        "worker_statuses": list(worker_statuses),
        "airfoil_feedback": airfoil_feedback,
        "launch": launch_summary,
        "turn": turn_summary,
        "trim": trim_summary,
        "local_stall": local_stall_summary,
        "spanwise_requirements": spanwise_requirement_summary,
        "mission": mission_summary,
        "ranking": ranking_summary,
    }
    return (
        concept_config,
        stations_rows,
        airfoil_templates,
        lofting_guides,
        prop_assumption,
        concept_summary,
    )


def run_birdman_concept_pipeline(
    *,
    config_path: Path,
    output_dir: Path,
    airfoil_worker_factory: AirfoilWorkerFactory = _default_airfoil_worker_factory,
    spanwise_loader: SpanwiseLoadLoader = _default_spanwise_loader,
) -> ConceptPipelineResult:
    cfg = load_concept_config(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_concepts = enumerate_geometry_concepts(cfg)
    if len(all_concepts) < 3:
        raise RuntimeError("Birdman concept enumeration must yield at least 3 candidate concepts.")
    concepts = all_concepts[: cfg.pipeline.keep_top_n]

    repo_root = _repo_root()
    worker = airfoil_worker_factory(project_dir=repo_root, cache_dir=output_dir / "polar_db")
    worker_backend = _worker_backend(worker)
    air_density_kg_per_m3 = _air_density_from_environment(cfg)

    evaluated_concepts: list[_EvaluatedConcept] = []
    selected_concept_dirs: list[Path] = []
    best_infeasible_concept_dirs: list[Path] = []
    summary_worker_statuses: list[str] = []

    for enumeration_index, concept in enumerate(concepts, start=1):
        stations = build_linear_wing_stations(
            concept,
            stations_per_half=cfg.pipeline.stations_per_half,
        )
        zone_requirements = spanwise_loader(concept, stations)
        zone_requirements_with_points = {
            zone_name: zone_data
            for zone_name, zone_data in zone_requirements.items()
            if zone_data.get("points")
        }
        zone_requirements_without_points = {
            zone_name: zone_data
            for zone_name, zone_data in zone_requirements.items()
            if not zone_data.get("points")
        }
        selected_by_zone: dict[str, SelectedZoneCandidate] = {}
        if zone_requirements_with_points:
            selection_batch = select_zone_airfoil_templates(
                zone_requirements=zone_requirements_with_points,
                seed_loader=_load_seed_airfoil_coordinates,
                worker=_SelectionWorkerAdapter(
                    worker,
                    allow_stub_fallback=worker_backend
                    in {"test_stub", "cli_stubbed", "python_stubbed"},
                ),
            )
            selected_by_zone.update(selection_batch.selected_by_zone)
        for zone_name in zone_requirements_without_points:
            selected_by_zone[zone_name] = _build_fallback_selected_zone_candidate(
                zone_name=zone_name,
                seed_coordinates=_load_seed_airfoil_coordinates(
                    _ROOT_SEED_AIRFOIL if zone_name in {"root", "mid1"} else _TIP_SEED_AIRFOIL
                ),
            )
        airfoil_templates = _build_selected_cst_airfoil_templates(
            selected_by_zone=selected_by_zone,
            zone_requirements=zone_requirements,
        )
        station_points = _flatten_zone_points(zone_requirements, stations)
        station_points = _attach_cl_max_proxies(
            station_points,
            half_span_m=0.5 * concept.span_m,
            concept=concept,
        )
        worker_queries, worker_point_refs = _build_worker_queries_and_refs(
            zone_requirements=zone_requirements,
            airfoil_templates=airfoil_templates,
        )
        worker_results = worker.run_queries(worker_queries)
        station_points, airfoil_feedback = _apply_worker_airfoil_feedback(
            station_points=station_points,
            worker_point_refs=worker_point_refs,
            worker_results=worker_results,
        )
        station_points, safe_clmax_summary = _apply_safe_clmax_model(
            station_points,
            safe_scale=cfg.stall_model.safe_clmax_scale,
            safe_delta=cfg.stall_model.safe_clmax_delta,
        )
        airfoil_feedback = {
            **airfoil_feedback,
            **safe_clmax_summary,
        }
        trim_summary, trim_result = _summarize_trim(cfg=cfg, station_points=station_points)
        launch_summary, _, _ = _summarize_launch(
            cfg=cfg,
            concept=concept,
            station_points=station_points,
            trim_result=trim_result,
            air_density_kg_per_m3=air_density_kg_per_m3,
        )
        turn_summary = _summarize_turn(
            cfg=cfg,
            concept=concept,
            station_points=station_points,
            trim_result=trim_result,
        )
        local_stall_summary = _summarize_local_stall(
            cfg=cfg,
            concept=concept,
            station_points=station_points,
        )
        mission_summary = _build_concept_mission_summary(
            cfg=cfg,
            concept=concept,
            station_points=station_points,
            airfoil_feedback=airfoil_feedback,
            air_density_kg_per_m3=air_density_kg_per_m3,
        )
        ranking_input = CandidateConceptResult(
            concept_id=f"eval-{enumeration_index:02d}",
            launch_feasible=bool(launch_summary["feasible"]),
            turn_feasible=bool(turn_summary["feasible"]),
            trim_feasible=bool(trim_summary["feasible"]),
            mission_feasible=bool(mission_summary["mission_feasible"]),
            safety_margin=_concept_safety_margin(
                launch_summary=launch_summary,
                turn_summary=turn_summary,
                trim_summary=trim_summary,
                local_stall_summary=local_stall_summary,
            ),
            mission_objective_mode=str(mission_summary["mission_objective_mode"]),
            mission_score=float(mission_summary["mission_score"]),
            best_range_m=float(mission_summary["best_range_m"]),
            assembly_penalty=_assembly_penalty(concept),
            local_stall_feasible=bool(local_stall_summary["feasible"]),
        )
        concept_worker_statuses = _worker_statuses(worker_results)
        summary_worker_statuses.extend(concept_worker_statuses)
        evaluated_concepts.append(
            _EvaluatedConcept(
                evaluation_id=ranking_input.concept_id,
                enumeration_index=enumeration_index,
                concept=concept,
                stations=stations,
                zone_requirements=zone_requirements,
                airfoil_templates=airfoil_templates,
                worker_results=worker_results,
                worker_backend=worker_backend,
                airfoil_feedback=airfoil_feedback,
                launch_summary=launch_summary,
                turn_summary=turn_summary,
                trim_summary=trim_summary,
                local_stall_summary=local_stall_summary,
                mission_summary=mission_summary,
                ranking_input=ranking_input,
            )
        )

    ranked_concepts = rank_concepts([record.ranking_input for record in evaluated_concepts])
    evaluated_by_id = {record.evaluation_id: record for record in evaluated_concepts}
    summary_records: list[dict[str, Any]] = []
    best_infeasible_records: list[dict[str, Any]] = []

    selected_ranked = [ranked for ranked in ranked_concepts if ranked.safety_feasible]
    infeasible_ranked = [ranked for ranked in ranked_concepts if not ranked.safety_feasible]
    best_infeasible_ranked = (
        infeasible_ranked[:1]
        if selected_ranked
        else infeasible_ranked[: int(cfg.pipeline.keep_top_n)]
    )

    for concept_index, ranked in enumerate(selected_ranked, start=1):
        record = evaluated_by_id[ranked.concept_id]
        ranking_summary = {
            "score": ranked.score,
            "selection_status": ranked.selection_status,
            "why_not_higher": list(ranked.why_not_higher),
            "safety_margin": record.ranking_input.safety_margin,
            "assembly_penalty": record.ranking_input.assembly_penalty,
            "ranking_basis": "airfoil_informed_mission_proxy_v1",
            "selection_scope": "ranked_bounded_prefix_pool",
        }
        spanwise_requirement_summary = _summarize_spanwise_requirements(record.zone_requirements)
        (
            concept_config,
            stations_rows,
            airfoil_templates,
            lofting_guides,
            prop_assumption,
            concept_summary,
        ) = _concept_to_bundle_payload(
            cfg=cfg,
            concept=record.concept,
            stations=record.stations,
            zone_requirements=record.zone_requirements,
            airfoil_templates=record.airfoil_templates,
            worker_results=record.worker_results,
            worker_backend=record.worker_backend,
            concept_index=concept_index,
            enumeration_index=record.enumeration_index,
            airfoil_feedback=record.airfoil_feedback,
            launch_summary=record.launch_summary,
            turn_summary=record.turn_summary,
            trim_summary=record.trim_summary,
            local_stall_summary=record.local_stall_summary,
            mission_summary=record.mission_summary,
            ranking_summary=ranking_summary,
            spanwise_requirement_summary=spanwise_requirement_summary,
        )

        bundle_dir: Path | None = None
        if cfg.output.export_candidate_bundle:
            bundle_dir = write_selected_concept_bundle(
                output_dir=output_dir / "selected_concepts",
                concept_id=concept_summary["concept_id"],
                concept_config=concept_config,
                stations_rows=stations_rows,
                airfoil_templates=airfoil_templates,
                lofting_guides=lofting_guides,
                prop_assumption=prop_assumption,
                concept_summary=concept_summary,
                export_vsp=(
                    cfg.output.export_vsp and concept_index <= cfg.output.export_vsp_for_top_n
                ),
            )
            selected_concept_dirs.append(bundle_dir)

        summary_records.append(
            {
                "concept_id": concept_summary["concept_id"],
                "enumeration_index": record.enumeration_index,
                "rank": concept_index,
                "bundle_dir": str(bundle_dir) if bundle_dir is not None else None,
                "span_m": record.concept.span_m,
                "wing_area_m2": record.concept.wing_area_m2,
                "zone_count": len(record.zone_requirements),
                "worker_result_count": len(record.worker_results),
                "worker_backend": record.worker_backend,
                "worker_statuses": list(_worker_statuses(record.worker_results)),
                "airfoil_feedback": record.airfoil_feedback,
                "launch": record.launch_summary,
                "turn": record.turn_summary,
                "trim": record.trim_summary,
                "local_stall": record.local_stall_summary,
                "spanwise_requirements": spanwise_requirement_summary,
                "mission": record.mission_summary,
                "ranking": ranking_summary,
            }
        )

    for infeasible_index, ranked in enumerate(best_infeasible_ranked, start=1):
        record = evaluated_by_id[ranked.concept_id]
        spanwise_requirement_summary = _summarize_spanwise_requirements(record.zone_requirements)
        bundle_dir: Path | None = None
        if cfg.output.export_candidate_bundle:
            (
                concept_config,
                stations_rows,
                airfoil_templates,
                lofting_guides,
                prop_assumption,
                concept_summary,
            ) = _concept_to_bundle_payload(
                cfg=cfg,
                concept=record.concept,
                stations=record.stations,
                zone_requirements=record.zone_requirements,
                airfoil_templates=record.airfoil_templates,
                worker_results=record.worker_results,
                worker_backend=record.worker_backend,
                concept_index=infeasible_index,
                enumeration_index=record.enumeration_index,
                airfoil_feedback=record.airfoil_feedback,
                launch_summary=record.launch_summary,
                turn_summary=record.turn_summary,
                trim_summary=record.trim_summary,
                local_stall_summary=record.local_stall_summary,
                mission_summary=record.mission_summary,
                ranking_summary={
                    "score": ranked.score,
                    "selection_status": ranked.selection_status,
                    "why_not_higher": list(ranked.why_not_higher),
                    "safety_margin": record.ranking_input.safety_margin,
                    "assembly_penalty": record.ranking_input.assembly_penalty,
                    "ranking_basis": "airfoil_informed_mission_proxy_v1",
                    "selection_scope": "ranked_bounded_prefix_pool",
                },
                spanwise_requirement_summary=spanwise_requirement_summary,
            )
            concept_summary["selected"] = False
            concept_summary["concept_id"] = f"infeasible-{record.enumeration_index:02d}"
            concept_summary["rank"] = infeasible_index
            bundle_dir = write_selected_concept_bundle(
                output_dir=output_dir / "best_infeasible_concepts",
                concept_id=concept_summary["concept_id"],
                concept_config=concept_config,
                stations_rows=stations_rows,
                airfoil_templates=airfoil_templates,
                lofting_guides=lofting_guides,
                prop_assumption=prop_assumption,
                concept_summary=concept_summary,
                export_vsp=(
                    cfg.output.export_vsp
                    and not selected_ranked
                    and infeasible_index <= cfg.output.export_vsp_for_top_n
                ),
            )
            best_infeasible_concept_dirs.append(bundle_dir)
        best_infeasible_records.append(
            {
                "concept_id": f"infeasible-{record.enumeration_index:02d}",
                "enumeration_index": record.enumeration_index,
                "overall_rank": next(
                    index for index, item in enumerate(ranked_concepts, start=1) if item.concept_id == ranked.concept_id
                ),
                "bundle_dir": str(bundle_dir) if bundle_dir is not None else None,
                "span_m": record.concept.span_m,
                "wing_area_m2": record.concept.wing_area_m2,
                "zone_count": len(record.zone_requirements),
                "worker_result_count": len(record.worker_results),
                "worker_backend": record.worker_backend,
                "worker_statuses": list(_worker_statuses(record.worker_results)),
                "airfoil_feedback": record.airfoil_feedback,
                "launch": record.launch_summary,
                "turn": record.turn_summary,
                "trim": record.trim_summary,
                "local_stall": record.local_stall_summary,
                "spanwise_requirements": spanwise_requirement_summary,
                "mission": record.mission_summary,
                "ranking": {
                    "score": ranked.score,
                    "selection_status": ranked.selection_status,
                    "why_not_higher": list(ranked.why_not_higher),
                    "safety_margin": record.ranking_input.safety_margin,
                    "assembly_penalty": record.ranking_input.assembly_penalty,
                    "ranking_basis": "airfoil_informed_mission_proxy_v1",
                    "selection_scope": "ranked_bounded_prefix_pool",
                },
            }
        )

    summary_json_path = output_dir / "concept_summary.json"
    summary_json_path.write_text(
        json.dumps(
            {
                "config_path": str(Path(config_path)),
                "worker_backend": worker_backend,
                "worker_statuses": summary_worker_statuses,
                "evaluation_scope": {
                    "selection_scope": "ranked_bounded_prefix_pool",
                    "ranking_basis": "airfoil_informed_mission_proxy_v1",
                    "objective_mode": str(cfg.mission.objective_mode),
                    "enumerated_concept_count": len(all_concepts),
                    "evaluated_concept_count": len(evaluated_concepts),
                    "selected_concept_count": len(summary_records),
                    "best_infeasible_count": len(best_infeasible_records),
                    "speed_sweep_window_mps": [
                        float(cfg.mission.speed_sweep_min_mps),
                        float(cfg.mission.speed_sweep_max_mps),
                    ],
                    "speed_sweep_points": int(cfg.mission.speed_sweep_points),
                },
                "selected_concepts": summary_records,
                "best_infeasible_concepts": best_infeasible_records,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return ConceptPipelineResult(
        summary_json_path=summary_json_path,
        selected_concept_dirs=tuple(selected_concept_dirs),
        best_infeasible_concept_dirs=tuple(best_infeasible_concept_dirs),
    )
