from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Callable, Protocol

from hpa_mdo.concept.airfoil_worker import PolarQuery, geometry_hash_from_coordinates
from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    WingStation,
    build_linear_wing_stations,
    enumerate_geometry_concepts,
)
from hpa_mdo.concept.handoff import write_selected_concept_bundle
from hpa_mdo.concept.safety import (
    evaluate_launch_gate,
    evaluate_local_stall,
    evaluate_trim_proxy,
    evaluate_turn_gate,
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
                    "zone_index": float(zone_index),
                    "point_index": float(point_index),
                    "station_y_m": float(station_y_m),
                    "cl_target": float(point["cl_target"]),
                    "cm_target": float(point["cm_target"]),
                    "weight": float(point.get("weight", 1.0)),
                    "reynolds": float(point.get("reynolds", 0.0)),
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
        enriched.append({**point, "cl_max_proxy": point["cl_target"] + cl_headroom})
    return enriched


def _numeric_value(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


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

    first_pass_clmax_proxy = _numeric_value(
        sweep_summary.get("first_pass_observed_clmax_proxy")
    )
    if first_pass_clmax_proxy is None:
        first_pass_clmax_proxy = _numeric_value(sweep_summary.get("observed_clmax_proxy"))
    if first_pass_clmax_proxy is None:
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
        "observed_clmax_proxy": first_pass_clmax_proxy,
        "observed_clmax_proxy_alpha_deg": _numeric_value(
            sweep_summary.get("first_pass_observed_clmax_proxy_alpha_deg")
        ),
        "observed_clmax_proxy_cd": _numeric_value(
            sweep_summary.get("first_pass_observed_clmax_proxy_cd")
        ),
        "observed_clmax_proxy_cdp": _numeric_value(
            sweep_summary.get("first_pass_observed_clmax_proxy_cdp")
        ),
        "observed_clmax_proxy_cm": _numeric_value(
            sweep_summary.get("first_pass_observed_clmax_proxy_cm")
        ),
        "observed_clmax_proxy_index": sweep_summary.get("first_pass_observed_clmax_proxy_index"),
        "observed_clmax_proxy_at_sweep_edge": sweep_summary.get(
            "first_pass_observed_clmax_proxy_at_sweep_edge"
        ),
        "sweep_point_count": sweep_summary.get("sweep_point_count"),
        "converged_point_count": sweep_summary.get("converged_point_count"),
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
        cl_max_proxy = min(float(base_point["cl_max_proxy"]), float(feedback["observed_clmax_proxy"]))
        updated_point = {
            **base_point,
            "cl_target": float(feedback["worker_cl"]),
            "cm_target": float(feedback["worker_cm"]),
            "cd_target": float(feedback["worker_cd"]),
            "cl_max_proxy": cl_max_proxy,
            "worker_cl": float(feedback["worker_cl"]),
            "worker_cm": float(feedback["worker_cm"]),
            "worker_cd": float(feedback["worker_cd"]),
            "worker_cdp": feedback["worker_cdp"],
            "airfoil_feedback_applied": True,
            "airfoil_feedback_source": "first_pass_observed_clmax_proxy",
            "airfoil_feedback_worker_status": str(result.get("status", "unknown")),
            "airfoil_feedback_template_id": ref["template_id"],
            "airfoil_feedback_zone_name": ref["zone_name"],
            "airfoil_feedback_zone_index": float(ref["zone_index"]),
            "airfoil_feedback_point_index": float(ref["point_index"]),
            "airfoil_feedback_station_point_index": float(point_index),
            "airfoil_feedback_observed_clmax_proxy": float(feedback["observed_clmax_proxy"]),
            "airfoil_feedback_observed_clmax_proxy_alpha_deg": feedback[
                "observed_clmax_proxy_alpha_deg"
            ],
            "airfoil_feedback_observed_clmax_proxy_cd": feedback["observed_clmax_proxy_cd"],
            "airfoil_feedback_observed_clmax_proxy_cdp": feedback["observed_clmax_proxy_cdp"],
            "airfoil_feedback_observed_clmax_proxy_cm": feedback["observed_clmax_proxy_cm"],
            "airfoil_feedback_observed_clmax_proxy_index": feedback["observed_clmax_proxy_index"],
            "airfoil_feedback_observed_clmax_proxy_at_sweep_edge": feedback[
                "observed_clmax_proxy_at_sweep_edge"
            ],
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
                "cl_target": float(updated_point["cl_target"]),
                "cm_target": float(updated_point["cm_target"]),
                "cd_target": float(updated_point["cd_target"]),
                "cl_max_proxy": float(updated_point["cl_max_proxy"]),
                "worker_cl": float(updated_point["worker_cl"]),
                "worker_cm": float(updated_point["worker_cm"]),
                "worker_cd": float(updated_point["worker_cd"]),
                "worker_cdp": updated_point["worker_cdp"],
                "first_pass_observed_clmax_proxy": float(
                    updated_point["airfoil_feedback_observed_clmax_proxy"]
                ),
                "first_pass_observed_clmax_proxy_alpha_deg": updated_point[
                    "airfoil_feedback_observed_clmax_proxy_alpha_deg"
                ],
                "first_pass_observed_clmax_proxy_cd": updated_point[
                    "airfoil_feedback_observed_clmax_proxy_cd"
                ],
                "first_pass_observed_clmax_proxy_cdp": updated_point[
                    "airfoil_feedback_observed_clmax_proxy_cdp"
                ],
                "first_pass_observed_clmax_proxy_cm": updated_point[
                    "airfoil_feedback_observed_clmax_proxy_cm"
                ],
            }
        )

    feedback_summary = {
        "applied": usable_worker_point_count > 0,
        "mode": "worker_polar_points" if usable_worker_point_count > 0 else "geometry_proxy",
        "worker_result_count": len(worker_results),
        "usable_worker_point_count": usable_worker_point_count,
        "fallback_worker_point_count": len(worker_results) - usable_worker_point_count,
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
    cl_available = min(point["cl_max_proxy"] for point in station_points)

    launch_result = evaluate_launch_gate(
        platform_height_m=cfg.launch.platform_height_m,
        wing_span_m=concept.span_m,
        speed_mps=cfg.launch.release_speed_mps,
        cl_required=cl_required,
        cl_available=cl_available,
        trim_margin_deg=trim_result.margin_deg,
        required_trim_margin_deg=cfg.launch.min_trim_margin_deg,
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
    station_points: list[dict[str, float]],
    trim_result,
) -> dict[str, Any]:
    representative_cl = max(point["cl_target"] for point in station_points)
    cl_max = min(point["cl_max_proxy"] for point in station_points)

    turn_result = evaluate_turn_gate(
        bank_angle_deg=cfg.turn.required_bank_angle_deg,
        speed_mps=cfg.launch.release_speed_mps,
        cl_level=representative_cl,
        cl_max=cl_max,
        trim_feasible=trim_result.feasible,
        required_stall_margin=cfg.launch.min_stall_margin,
    )
    return {
        "status": turn_result.reason,
        "feasible": turn_result.feasible,
        "bank_angle_deg": cfg.turn.required_bank_angle_deg,
        "speed_mps": cfg.launch.release_speed_mps,
        "cl_level": representative_cl,
        "required_cl": turn_result.required_cl,
        "cl_max": cl_max,
        "stall_margin": turn_result.stall_margin,
        "required_stall_margin": cfg.launch.min_stall_margin,
        "trim_feasible": trim_result.feasible,
    }


def _summarize_trim(
    *,
    cfg: BirdmanConceptConfig,
    station_points: list[dict[str, float]],
) -> tuple[dict[str, Any], Any]:
    representative_cm = -max(abs(point["cm_target"]) for point in station_points)
    trim_result = evaluate_trim_proxy(
        representative_cm=representative_cm,
        required_margin_deg=cfg.launch.min_trim_margin_deg,
    )
    return {
        "status": trim_result.reason,
        "feasible": trim_result.feasible,
        "representative_cm": representative_cm,
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
        required_stall_margin=cfg.launch.min_stall_margin,
    )
    return {
        "status": local_stall_result.reason,
        "feasible": local_stall_result.feasible,
        "min_margin": local_stall_result.min_margin,
        "min_margin_station_y_m": local_stall_result.min_margin_station_y_m,
        "tip_critical": local_stall_result.tip_critical,
        "required_stall_margin": cfg.launch.min_stall_margin,
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
    airfoil_feedback: dict[str, Any],
    launch_summary: dict[str, Any],
    turn_summary: dict[str, Any],
    trim_summary: dict[str, Any],
    local_stall_summary: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
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
    lofting_guides = {
        "authority": "cst_coefficients",
        "stations_per_half": len(stations),
        "zone_names": list(zone_requirements.keys()),
        "interpolation_rule": "linear_in_coeff_space",
    }
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

    concepts = enumerate_geometry_concepts(cfg)[: cfg.pipeline.keep_top_n]
    if len(concepts) < 3:
        raise RuntimeError("Birdman concept enumeration must yield at least 3 candidate concepts.")

    repo_root = _repo_root()
    worker = airfoil_worker_factory(project_dir=repo_root, cache_dir=output_dir / "polar_db")
    worker_backend = _worker_backend(worker)

    selected_concept_dirs: list[Path] = []
    summary_records: list[dict[str, Any]] = []
    summary_worker_statuses: list[str] = []

    for concept_index, concept in enumerate(concepts, start=1):
        stations = build_linear_wing_stations(
            concept,
            stations_per_half=cfg.pipeline.stations_per_half,
        )
        zone_requirements = spanwise_loader(concept, stations)
        airfoil_templates = _build_seed_airfoil_templates(zone_requirements)
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
        trim_summary, trim_result = _summarize_trim(cfg=cfg, station_points=station_points)
        launch_summary, _, _ = _summarize_launch(
            cfg=cfg,
            concept=concept,
            station_points=station_points,
            trim_result=trim_result,
            air_density_kg_per_m3=_air_density_from_environment(cfg),
        )
        turn_summary = _summarize_turn(
            cfg=cfg,
            station_points=station_points,
            trim_result=trim_result,
        )
        local_stall_summary = _summarize_local_stall(
            cfg=cfg,
            concept=concept,
            station_points=station_points,
        )
        (
            concept_config,
            stations_rows,
            airfoil_templates,
            lofting_guides,
            prop_assumption,
            concept_summary,
        ) = _concept_to_bundle_payload(
            cfg=cfg,
            concept=concept,
            stations=stations,
            zone_requirements=zone_requirements,
            airfoil_templates=airfoil_templates,
            worker_results=worker_results,
            worker_backend=worker_backend,
            concept_index=concept_index,
            airfoil_feedback=airfoil_feedback,
            launch_summary=launch_summary,
            turn_summary=turn_summary,
            trim_summary=trim_summary,
            local_stall_summary=local_stall_summary,
        )
        concept_worker_statuses = list(concept_summary["worker_statuses"])
        summary_worker_statuses.extend(concept_worker_statuses)

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
                "bundle_dir": str(bundle_dir) if bundle_dir is not None else None,
                "span_m": concept.span_m,
                "wing_area_m2": concept.wing_area_m2,
                "zone_count": len(zone_requirements),
                "worker_result_count": len(worker_results),
                "worker_backend": worker_backend,
                "worker_statuses": concept_worker_statuses,
                "airfoil_feedback": airfoil_feedback,
                "launch": launch_summary,
                "turn": turn_summary,
                "trim": trim_summary,
                "local_stall": local_stall_summary,
            }
        )

    summary_json_path = output_dir / "concept_summary.json"
    summary_json_path.write_text(
        json.dumps(
            {
                "config_path": str(Path(config_path)),
                "worker_backend": worker_backend,
                "worker_statuses": summary_worker_statuses,
                "selected_concepts": summary_records,
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
    )
