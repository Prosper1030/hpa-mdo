from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Protocol

from hpa_mdo.concept.aero_proxies import (
    misc_cd_proxy,
    spanload_efficiency_proxy,
)
from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    build_lofting_guides,
    generate_cst_coordinates,
    validate_cst_candidate_coordinates,
)
from hpa_mdo.concept.airfoil_selection import (
    SelectedZoneCandidate,
    build_base_cst_template,
    select_zone_airfoil_templates_for_concepts,
)
from hpa_mdo.concept.atmosphere import AirProperties
from hpa_mdo.concept.atmosphere import air_properties_from_environment
from hpa_mdo.concept.avl_loader import load_zone_requirements_from_avl
from hpa_mdo.concept.airfoil_worker import PolarQuery, geometry_hash_from_coordinates
from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    WingStation,
    _resolve_tube_system_mass_kg,
    _tube_mass_source_tag,
    build_linear_wing_stations,
    enumerate_geometry_concepts,
    get_last_geometry_enumeration_diagnostics,
)
from hpa_mdo.concept.frontier import build_frontier_summary, sizing_archetype
from hpa_mdo.concept.handoff import write_selected_concept_bundle
from hpa_mdo.concept.mass_closure import close_area_mass, estimate_fixed_planform_mass
from hpa_mdo.concept.mission_drag import compute_rigging_drag_cda_m2
from hpa_mdo.concept.propulsion import SimplifiedPropModel
from hpa_mdo.concept.ranking import CandidateConceptResult, rank_concepts
from hpa_mdo.concept.safety import (
    evaluate_launch_gate,
    evaluate_local_stall,
    evaluate_trim_balance,
    evaluate_turn_gate,
)
from hpa_mdo.concept.stall_model import apply_safe_local_clmax_model
from hpa_mdo.mission.objective import (
    CsvPowerCurve,
    FakeAnchorCurve,
    MissionEvaluationInputs,
    build_rider_power_curve,
    evaluate_mission_objective,
    fixed_range_infeasible_score,
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
    selected_by_zone: dict[str, SelectedZoneCandidate]
    airfoil_templates: dict[str, dict[str, Any]]
    screening_worker_results: list[dict[str, object]]
    worker_results: list[dict[str, object]]
    worker_backend: str
    screening_airfoil_feedback: dict[str, Any]
    airfoil_feedback: dict[str, Any]
    launch_summary: dict[str, Any]
    turn_summary: dict[str, Any]
    trim_summary: dict[str, Any]
    local_stall_summary: dict[str, Any]
    mission_summary: dict[str, Any]
    ranking_input: CandidateConceptResult


@dataclass(frozen=True)
class _PreparedConcept:
    evaluation_id: str
    enumeration_index: int
    concept: GeometryConcept
    stations: tuple[WingStation, ...]
    zone_requirements: dict[str, dict[str, Any]]


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
    safe_clmax_scale: float,
    safe_clmax_delta: float,
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
        safe_clmax=max(
            0.10,
            float(safe_clmax_scale) * float(stubbed_metrics["usable_clmax"])
            - float(safe_clmax_delta),
        ),
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
    """Resolve air density from the configured environment and table."""

    return _air_properties_from_environment(cfg).density_kg_per_m3


def _air_properties_from_environment(cfg: BirdmanConceptConfig) -> AirProperties:
    return air_properties_from_environment(
        temperature_c=float(cfg.environment.temperature_c),
        relative_humidity_percent=float(cfg.environment.relative_humidity),
        altitude_m=float(cfg.environment.altitude_m),
    )


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
                    "span_fraction": float(
                        point.get(
                            "span_fraction",
                            0.0
                            if half_span_m <= 0.0
                            else min(max(float(station_y_m) / half_span_m, 0.0), 1.0),
                        )
                    ),
                    "taper_ratio": float(
                        point.get("taper_ratio", zone_data.get("taper_ratio", 0.35))
                    ),
                    "washout_deg": float(
                        point.get("washout_deg", zone_data.get("washout_deg", 0.0))
                    ),
                    "case_label": str(point.get("case_label", "reference_avl_case")),
                    "case_weight": float(point.get("case_weight", 1.0)),
                    "evaluation_speed_mps": _numeric_value(point.get("evaluation_speed_mps")),
                    "evaluation_gross_mass_kg": _numeric_value(
                        point.get("evaluation_gross_mass_kg")
                    ),
                    "load_factor": _numeric_value(point.get("load_factor")) or 1.0,
                    "case_reason": point.get("case_reason"),
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


def _station_points_for_case_label(
    station_points: list[dict[str, float]],
    case_label: str,
) -> list[dict[str, float]]:
    selected = [
        dict(point)
        for point in station_points
        if str(point.get("case_label", "reference_avl_case")) == case_label
    ]
    return selected


def _group_station_points_by_case_label(
    station_points: list[dict[str, float]],
) -> dict[str, list[dict[str, float]]]:
    grouped: dict[str, list[dict[str, float]]] = {}
    for point in station_points:
        case_label = str(point.get("case_label", "reference_avl_case"))
        grouped.setdefault(case_label, []).append(dict(point))
    return grouped


def _attach_cl_max_proxies(
    station_points: list[dict[str, float]],
    *,
    half_span_m: float,
    concept: GeometryConcept,
    proxy_cfg: Any,
) -> list[dict[str, float]]:
    enriched: list[dict[str, float]] = []
    span_ratio = 0.0 if concept.span_m <= 0.0 else concept.span_m / max(concept.wing_area_m2, 1.0)
    twist_delta = abs(concept.twist_tip_deg - concept.twist_root_deg)

    for point in station_points:
        eta = 0.0 if half_span_m <= 0.0 else min(max(point["station_y_m"] / half_span_m, 0.0), 1.0)
        cl_headroom = (
            float(proxy_cfg.cl_headroom_base)
            - float(proxy_cfg.cl_headroom_eta_slope) * eta
            - float(proxy_cfg.cl_headroom_twist_slope) * (twist_delta / 5.0)
            + float(proxy_cfg.cl_headroom_span_ratio_slope) * min(span_ratio, 1.2)
        )
        cl_headroom = min(
            max(cl_headroom, float(proxy_cfg.cl_headroom_floor)),
            float(proxy_cfg.cl_headroom_ceiling),
        )
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


def _annotate_zone_requirements_with_concept_geometry(
    *,
    zone_requirements: dict[str, dict[str, Any]],
    concept: GeometryConcept,
) -> dict[str, dict[str, Any]]:
    half_span_m = 0.5 * float(concept.span_m)
    washout_deg = max(0.0, float(concept.twist_root_deg) - float(concept.twist_tip_deg))
    taper_ratio = float(concept.taper_ratio)
    zone_items = list(zone_requirements.items())
    annotated: dict[str, dict[str, Any]] = {}
    for zone_index, (zone_name, zone_data) in enumerate(zone_items):
        points: list[dict[str, Any]] = []
        for point in zone_data.get("points", []):
            station_y_m = _numeric_value(point.get("station_y_m"))
            if station_y_m is None:
                station_y_m = _zone_midpoint_fraction(zone_name, zone_index, len(zone_items)) * half_span_m
            span_fraction = (
                0.0
                if half_span_m <= 0.0
                else min(max(float(station_y_m) / half_span_m, 0.0), 1.0)
            )
            points.append(
                {
                    **point,
                    "station_y_m": float(station_y_m),
                    "span_fraction": float(point.get("span_fraction", span_fraction)),
                    "taper_ratio": float(point.get("taper_ratio", taper_ratio)),
                    "washout_deg": float(point.get("washout_deg", washout_deg)),
                    "wing_loading_target_Npm2": (
                        None
                        if concept.wing_loading_target_Npm2 is None
                        else float(concept.wing_loading_target_Npm2)
                    ),
                    "wing_area_source": str(concept.wing_area_source),
                }
            )
        annotated[zone_name] = {
            **zone_data,
            "points": points,
            "taper_ratio": float(zone_data.get("taper_ratio", taper_ratio)),
            "washout_deg": float(zone_data.get("washout_deg", washout_deg)),
            "wing_loading_target_Npm2": (
                None
                if concept.wing_loading_target_Npm2 is None
                else float(concept.wing_loading_target_Npm2)
            ),
            "wing_area_source": str(concept.wing_area_source),
        }
    return annotated


def _spanwise_loader_avl_rerun_context(
    spanwise_loader: SpanwiseLoadLoader,
) -> dict[str, Any] | None:
    context = getattr(spanwise_loader, "_birdman_avl_rerun_context", None)
    if not isinstance(context, dict):
        return None

    cfg = context.get("cfg")
    working_root = context.get("working_root")
    if not isinstance(cfg, BirdmanConceptConfig) or working_root is None:
        return None
    return {
        "cfg": cfg,
        "working_root": Path(working_root),
        "avl_binary": context.get("avl_binary"),
    }


def _post_airfoil_reference_condition_override(
    *,
    mission_summary: dict[str, Any],
) -> dict[str, Any] | None:
    reference_speed_mps = _numeric_value(mission_summary.get("best_range_speed_mps"))
    reference_speed_reason = "post_airfoil_best_range_feasible_speed_mps"
    if reference_speed_mps is None:
        reference_speed_mps = _numeric_value(mission_summary.get("estimated_first_feasible_speed_mps"))
        reference_speed_reason = "post_airfoil_estimated_first_feasible_speed_mps"
    reference_gross_mass_kg = _numeric_value(mission_summary.get("evaluated_gross_mass_kg"))
    if reference_speed_mps is None or reference_gross_mass_kg is None:
        return None

    selected_mass_case = next(
        (
            dict(case)
            for case in mission_summary.get("mass_cases", [])
            if math.isclose(
                float(case.get("gross_mass_kg", -1.0)),
                float(reference_gross_mass_kg),
                rel_tol=0.0,
                abs_tol=1.0e-9,
            )
        ),
        {"gross_mass_kg": float(reference_gross_mass_kg)},
    )
    return {
        "reference_speed_mps": float(reference_speed_mps),
        "reference_gross_mass_kg": float(reference_gross_mass_kg),
        "reference_speed_reason": reference_speed_reason,
        "mass_selection_reason": "post_airfoil_worst_case_gross_mass",
        "reference_condition_policy": "post_airfoil_feasible_reference_avl_rerun_v1",
        "case_reason": "post_airfoil_finalist_reference_case",
        "selected_mass_case": selected_mass_case,
    }


def _should_iterate_post_airfoil_avl_reference(
    *,
    consistency_audit: dict[str, Any],
    rerun_iteration_count: int,
    max_rerun_iterations: int = 2,
) -> bool:
    if int(rerun_iteration_count) >= int(max_rerun_iterations):
        return False
    if not bool(consistency_audit.get("rerun_recommended")):
        return False

    rerun_reasons = {str(reason) for reason in consistency_audit.get("rerun_reasons", [])}
    return bool(
        rerun_reasons
        & {
            "reference_speed_outside_post_airfoil_feasible_set",
            "reference_speed_delta_exceeds_1mps",
        }
    )


def _rerun_finalist_zone_requirements_from_post_airfoil_avl(
    *,
    spanwise_loader: SpanwiseLoadLoader,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    airfoil_templates: dict[str, dict[str, Any]],
    mission_summary: dict[str, Any],
    rerun_iteration_index: int,
) -> dict[str, dict[str, Any]] | None:
    avl_context = _spanwise_loader_avl_rerun_context(spanwise_loader)
    if avl_context is None:
        return None

    reference_condition_override = _post_airfoil_reference_condition_override(
        mission_summary=mission_summary,
    )
    if reference_condition_override is None:
        return None

    rerun_zone_requirements = load_zone_requirements_from_avl(
        cfg=avl_context["cfg"],
        concept=concept,
        stations=stations,
        working_root=Path(avl_context["working_root"]),
        avl_binary=avl_context.get("avl_binary"),
        airfoil_templates=airfoil_templates,
        reference_condition_override=reference_condition_override,
        case_tag=f"finalist_post_airfoil_avl_rerun_iter{int(rerun_iteration_index):02d}",
    )
    return _annotate_zone_requirements_with_concept_geometry(
        zone_requirements=rerun_zone_requirements,
        concept=concept,
    )


def _apply_safe_clmax_model(
    station_points: list[dict[str, float]],
    *,
    safe_scale: float,
    safe_delta: float,
    tip_3d_penalty_start_eta: float = 0.55,
    tip_3d_penalty_max: float = 0.04,
    tip_taper_penalty_weight: float = 0.35,
    washout_relief_deg: float = 2.0,
    washout_relief_max: float = 0.02,
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    return apply_safe_local_clmax_model(
        station_points,
        safe_scale=float(safe_scale),
        safe_delta=float(safe_delta),
        tip_3d_penalty_start_eta=float(tip_3d_penalty_start_eta),
        tip_3d_penalty_max=float(tip_3d_penalty_max),
        tip_taper_penalty_weight=float(tip_taper_penalty_weight),
        washout_relief_deg=float(washout_relief_deg),
        washout_relief_max=float(washout_relief_max),
    )


def _build_worker_queries_and_refs(
    *,
    zone_requirements: dict[str, dict[str, Any]],
    airfoil_templates: dict[str, dict[str, Any]],
    analysis_mode: str,
    analysis_stage: str,
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
                    analysis_mode=analysis_mode,
                    analysis_stage=analysis_stage,
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


def _update_selected_by_zone_from_station_points(
    *,
    selected_by_zone: dict[str, SelectedZoneCandidate],
    station_points: list[dict[str, float]],
    safe_scale: float,
    safe_delta: float,
) -> dict[str, SelectedZoneCandidate]:
    updated: dict[str, SelectedZoneCandidate] = {}
    for zone_name, selected in selected_by_zone.items():
        zone_station_points = [
            point
            for point in station_points
            if str(point.get("zone_name")) == zone_name
            and bool(point.get("airfoil_feedback_applied"))
        ]
        if not zone_station_points:
            updated[zone_name] = selected
            continue

        mean_cd = sum(float(point["cd_effective"]) for point in zone_station_points) / len(
            zone_station_points
        )
        mean_cm = sum(float(point["cm_effective"]) for point in zone_station_points) / len(
            zone_station_points
        )
        usable_clmax = max(float(point["cl_max_effective"]) for point in zone_station_points)
        safe_clmax = min(
            float(point.get("cl_max_safe", max(0.10, float(safe_scale) * usable_clmax - float(safe_delta))))
            for point in zone_station_points
        )
        updated[zone_name] = SelectedZoneCandidate(
            template=selected.template,
            coordinates=selected.coordinates,
            mean_cd=mean_cd,
            mean_cm=mean_cm,
            usable_clmax=usable_clmax,
            safe_clmax=safe_clmax,
            candidate_score=selected.candidate_score,
        )

    return updated


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
    gross_mass_kg = _concept_design_gross_mass_kg(cfg, concept)
    cl_required = (gross_mass_kg * 9.80665) / max(q_pa * concept.wing_area_m2, 1.0e-9)
    launch_station_points = _station_points_for_case_label(station_points, "launch_release_case")
    limiting_point = min(launch_station_points or station_points, key=_cl_limit)
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
        use_ground_effect=False,
    )
    ground_effect_sensitivity_result = (
        evaluate_launch_gate(
            platform_height_m=cfg.launch.platform_height_m,
            wing_span_m=concept.span_m,
            speed_mps=cfg.launch.release_speed_mps,
            cl_required=cl_required,
            cl_available=cl_available,
            trim_margin_deg=trim_result.margin_deg,
            required_trim_margin_deg=cfg.launch.min_trim_margin_deg,
            stall_utilization_limit=cfg.stall_model.launch_utilization_limit,
            use_ground_effect=True,
        )
        if cfg.launch.use_ground_effect
        else None
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
            "model": "vstall_margin_primary_with_ground_effect_sensitivity",
            "ground_effect_primary_gate": False,
            "ground_effect_sensitivity_enabled": ground_effect_sensitivity_result is not None,
            "ground_effect_sensitivity_adjusted_cl_required": (
                None
                if ground_effect_sensitivity_result is None
                else ground_effect_sensitivity_result.adjusted_cl_required
            ),
            "ground_effect_sensitivity_stall_utilization": (
                None
                if ground_effect_sensitivity_result is None
                else ground_effect_sensitivity_result.stall_utilization
            ),
            "ground_effect_sensitivity_status": (
                None
                if ground_effect_sensitivity_result is None
                else ground_effect_sensitivity_result.reason
            ),
            "ground_effect_sensitivity_feasible": (
                None
                if ground_effect_sensitivity_result is None
                else ground_effect_sensitivity_result.feasible
            ),
            "evaluation_case": (
                "launch_release_case" if launch_station_points else "all_station_points_fallback"
            ),
        },
        cl_required,
        cl_available,
    )


def _scale_station_points_to_condition(
    *,
    station_points: list[dict[str, float]],
    evaluation_speed_mps: float,
    evaluation_gross_mass_kg: float,
    scale_field_name: str,
) -> tuple[list[dict[str, float]], list[float]]:
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
                scale_field_name: cl_scale,
            }
        )
    return scaled_station_points, cl_scale_factors


def _local_stall_evaluation_cases(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
    mission_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    if not station_points:
        raise ValueError("station_points must not be empty.")

    explicit_case_payload = any(
        "case_label" in point or "evaluation_speed_mps" in point
        for point in station_points
    )
    grouped_case_points = _group_station_points_by_case_label(station_points)
    if explicit_case_payload and grouped_case_points:
        case_labels = (
            "reference_avl_case",
            "slow_avl_case",
            "launch_release_case",
            "turn_avl_case",
        )
        multipoint_cases: list[dict[str, Any]] = []
        for case_label in case_labels:
            case_points = grouped_case_points.get(case_label)
            if not case_points:
                continue
            first_point = case_points[0]
            multipoint_cases.append(
                {
                    "case_label": case_label,
                    "reference_speed_mps": _numeric_value(first_point.get("reference_speed_mps")),
                    "reference_gross_mass_kg": _numeric_value(
                        first_point.get("reference_gross_mass_kg")
                    ),
                    "evaluation_speed_mps": _numeric_value(first_point.get("evaluation_speed_mps")),
                    "evaluation_gross_mass_kg": _numeric_value(
                        first_point.get("evaluation_gross_mass_kg")
                    ),
                    "cl_scale_factor_min": 1.0,
                    "cl_scale_factor_max": 1.0,
                    "station_points": case_points,
                }
            )
        if multipoint_cases:
            return multipoint_cases

    first_point = station_points[0]
    reference_speed_mps = _numeric_value(first_point.get("reference_speed_mps"))
    reference_gross_mass_kg = _numeric_value(first_point.get("reference_gross_mass_kg"))
    if reference_speed_mps is None:
        reference_speed_mps = _numeric_value(mission_summary.get("best_range_speed_mps"))
    if reference_gross_mass_kg is None:
        reference_gross_mass_kg = _numeric_value(mission_summary.get("evaluated_gross_mass_kg"))
    if reference_speed_mps is None:
        reference_speed_mps = float(cfg.launch.release_speed_mps)
    if reference_gross_mass_kg is None:
        reference_gross_mass_kg = _concept_design_gross_mass_kg(cfg, concept)

    cases: list[dict[str, Any]] = [
        {
            "case_label": "reference_avl_case",
            "reference_speed_mps": reference_speed_mps,
            "reference_gross_mass_kg": reference_gross_mass_kg,
            "evaluation_speed_mps": reference_speed_mps,
            "evaluation_gross_mass_kg": reference_gross_mass_kg,
            "station_points": [dict(point) for point in station_points],
            "cl_scale_factor_min": 1.0,
            "cl_scale_factor_max": 1.0,
        }
    ]

    candidate_cases = [
        (
            "mission_worst_case",
            _numeric_value(mission_summary.get("best_range_speed_mps")),
            _numeric_value(mission_summary.get("evaluated_gross_mass_kg")),
        ),
        (
            "launch_release_case",
            float(cfg.launch.release_speed_mps),
            _concept_design_gross_mass_kg(cfg, concept),
        ),
    ]
    seen_conditions = {(reference_speed_mps, reference_gross_mass_kg)}
    for case_label, evaluation_speed_mps, evaluation_gross_mass_kg in candidate_cases:
        if evaluation_speed_mps is None or evaluation_gross_mass_kg is None:
            continue
        condition_key = (float(evaluation_speed_mps), float(evaluation_gross_mass_kg))
        if condition_key in seen_conditions:
            continue
        scaled_station_points, cl_scale_factors = _scale_station_points_to_condition(
            station_points=station_points,
            evaluation_speed_mps=float(evaluation_speed_mps),
            evaluation_gross_mass_kg=float(evaluation_gross_mass_kg),
            scale_field_name="local_stall_cl_scale_factor",
        )
        cases.append(
            {
                "case_label": case_label,
                "reference_speed_mps": reference_speed_mps,
                "reference_gross_mass_kg": reference_gross_mass_kg,
                "evaluation_speed_mps": float(evaluation_speed_mps),
                "evaluation_gross_mass_kg": float(evaluation_gross_mass_kg),
                "station_points": scaled_station_points,
                "cl_scale_factor_min": min(cl_scale_factors) if cl_scale_factors else 1.0,
                "cl_scale_factor_max": max(cl_scale_factors) if cl_scale_factors else 1.0,
            }
        )
        seen_conditions.add(condition_key)
    return cases


def _local_stall_case_role(case_label: str) -> str:
    case_label = str(case_label)
    if case_label == "slow_avl_case":
        return "slow_speed_sensitivity"
    if case_label == "launch_release_case":
        return "launch_transient"
    if case_label == "turn_avl_case":
        return "planned_turn"
    if case_label == "mission_worst_case":
        return "sustained_mission_speed"
    if case_label == "reference_avl_case":
        return "reference_cruise"
    return "local_stall_screening"


def _local_stall_case_limit(*, cfg: BirdmanConceptConfig, case_label: str) -> float:
    role = _local_stall_case_role(case_label)
    if role == "slow_speed_sensitivity":
        return float(cfg.stall_model.slow_speed_report_utilization_limit)
    if role == "launch_transient":
        return float(cfg.stall_model.launch_utilization_limit)
    if role == "planned_turn":
        return float(cfg.stall_model.turn_utilization_limit)
    return float(cfg.stall_model.local_stall_utilization_limit)


def _local_stall_case_gate_enforced(case_label: str) -> bool:
    return _local_stall_case_role(case_label) != "slow_speed_sensitivity"


def _stall_case_status(result) -> str:
    if result.reason == "beyond_raw_clmax":
        return "beyond_raw_clmax"
    if result.safe_clmax_status == "beyond_safe_clmax":
        return "beyond_safe_clmax"
    return str(result.reason)


def _summarize_turn(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
    trim_result,
) -> dict[str, Any]:
    turn_station_points = _station_points_for_case_label(station_points, "turn_avl_case")
    if turn_station_points:
        evaluation_speed_mps = float(
            _numeric_value(turn_station_points[0].get("evaluation_speed_mps"))
            or cfg.launch.release_speed_mps
        )
        evaluation_gross_mass_kg = float(
            _numeric_value(turn_station_points[0].get("evaluation_gross_mass_kg"))
            or _concept_design_gross_mass_kg(cfg, concept)
        )
        load_factor_override = float(
            _numeric_value(turn_station_points[0].get("load_factor"))
            or (1.0 / math.cos(math.radians(float(cfg.turn.required_bank_angle_deg))))
        )
        scaled_station_points = turn_station_points
        cl_scale_factors = [1.0 for _ in turn_station_points]
        pre_scaled_cl = True
        evaluation_case = "turn_avl_case"
    else:
        evaluation_speed_mps = float(cfg.launch.release_speed_mps)
        evaluation_gross_mass_kg = _concept_design_gross_mass_kg(cfg, concept)
        scaled_station_points, cl_scale_factors = _scale_station_points_to_condition(
            station_points=station_points,
            evaluation_speed_mps=evaluation_speed_mps,
            evaluation_gross_mass_kg=evaluation_gross_mass_kg,
            scale_field_name="turn_cl_scale_factor",
        )
        load_factor_override = None
        pre_scaled_cl = False
        evaluation_case = "scaled_reference_fallback"
    turn_result = evaluate_turn_gate(
        bank_angle_deg=cfg.turn.required_bank_angle_deg,
        speed_mps=evaluation_speed_mps,
        station_points=scaled_station_points,
        half_span_m=0.5 * concept.span_m,
        trim_feasible=trim_result.feasible,
        stall_utilization_limit=cfg.stall_model.turn_utilization_limit,
        load_factor_override=load_factor_override,
        pre_scaled_cl=pre_scaled_cl,
    )
    return {
        "status": turn_result.reason,
        "feasible": turn_result.feasible,
        "gate_role": "screening_only",
        "gate_model": "fixed_bank_screening",
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
        "raw_clmax": turn_result.raw_clmax,
        "safe_clmax": turn_result.safe_clmax,
        "raw_clmax_ratio": turn_result.raw_clmax_ratio,
        "safe_clmax_ratio": turn_result.safe_clmax_ratio,
        "raw_clmax_status": turn_result.raw_clmax_status,
        "safe_clmax_status": turn_result.safe_clmax_status,
        "raw_stall_speed_margin_ratio": turn_result.raw_stall_speed_margin_ratio,
        "safe_stall_speed_margin_ratio": turn_result.safe_stall_speed_margin_ratio,
        "tip_excluded_safe_clmax_ratio": turn_result.tip_excluded_safe_clmax_ratio,
        "outboard_region_safe_clmax_ratio": turn_result.outboard_region_safe_clmax_ratio,
        "contiguous_overlimit_span_fraction": turn_result.contiguous_overlimit_span_fraction,
        "tip_exclusion_eta": turn_result.tip_exclusion_eta,
        "outboard_region_eta_min": turn_result.outboard_region_eta_min,
        "outboard_region_eta_max": turn_result.outboard_region_eta_max,
        "trim_feasible": trim_result.feasible,
        "limiting_station_y_m": turn_result.limiting_station_y_m,
        "tip_critical": turn_result.tip_critical,
        "evaluation_gross_mass_kg": evaluation_gross_mass_kg,
        "reference_speed_mps": _numeric_value(station_points[0].get("reference_speed_mps")),
        "reference_gross_mass_kg": _numeric_value(station_points[0].get("reference_gross_mass_kg")),
        "cl_scale_factor_min": min(cl_scale_factors) if cl_scale_factors else 1.0,
        "cl_scale_factor_max": max(cl_scale_factors) if cl_scale_factors else 1.0,
        "evaluation_case": evaluation_case,
    }


def _summarize_trim(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
) -> tuple[dict[str, Any], Any]:
    trim_station_points = _station_points_for_case_label(station_points, "reference_avl_case")
    effective_station_points = trim_station_points or station_points
    cm_points = [
        (
            float(point.get("cm_effective", point["cm_target"])),
            max(float(point.get("weight", 1.0)) * float(point.get("chord_m", 1.0)) ** 2, 1.0e-9),
            point,
        )
        for point in effective_station_points
    ]
    cl_points = [
        (
            float(point["cl_target"]),
            max(float(point.get("weight", 1.0)) * float(point.get("chord_m", 1.0)), 1.0e-9),
        )
        for point in effective_station_points
    ]
    total_cm_weight = sum(weight for _, weight, _ in cm_points)
    if total_cm_weight <= 0.0:
        total_cm_weight = float(len(cm_points)) or 1.0
    total_cl_weight = sum(weight for _, weight in cl_points)
    if total_cl_weight <= 0.0:
        total_cl_weight = float(len(cl_points)) or 1.0

    weighted_mean_cm = sum(cm * weight for cm, weight, _ in cm_points) / total_cm_weight
    weighted_mean_cl = sum(cl * weight for cl, weight in cl_points) / total_cl_weight
    cm_rms = math.sqrt(
        sum(weight * (cm - weighted_mean_cm) ** 2 for cm, weight, _ in cm_points)
        / total_cm_weight
    )
    dominant_point = max(
        cm_points,
        key=lambda item: abs(item[0]) * item[1],
    )[2]
    representative_cm = float(weighted_mean_cm)
    representative_cm_source = str(
        dominant_point.get("cm_effective_source", "zone_target_proxy")
    )
    tail_area_ratio = concept.tail_area_m2 / max(concept.wing_area_m2, 1.0e-9)
    trim_result = evaluate_trim_balance(
        wing_cl=weighted_mean_cl,
        wing_cm_airfoil=representative_cm,
        cg_xc=concept.cg_xc,
        wing_ac_xc=cfg.tail_model.wing_ac_xc,
        tail_area_ratio=tail_area_ratio,
        tail_arm_to_mac=cfg.tail_model.tail_arm_to_mac,
        tail_dynamic_pressure_ratio=cfg.tail_model.tail_dynamic_pressure_ratio,
        tail_efficiency=cfg.tail_model.tail_efficiency,
        tail_cl_limit_abs=cfg.tail_model.tail_cl_limit_abs,
        required_margin_deg=cfg.launch.min_trim_margin_deg,
        body_cm_offset=cfg.tail_model.body_cm_offset,
        cm_spread=cm_rms,
        spread_factor=cfg.tail_model.cm_spread_factor,
    )
    tail_arm_m = cfg.tail_model.tail_arm_to_mac * concept.mean_aerodynamic_chord_m
    return {
        "status": trim_result.reason,
        "feasible": trim_result.feasible,
        "representative_cm": representative_cm,
        "representative_cm_source": representative_cm_source,
        "wing_cl_reference": weighted_mean_cl,
        "wing_ac_xc": cfg.tail_model.wing_ac_xc,
        "cg_xc": concept.cg_xc,
        "wing_cm_total": trim_result.wing_cm_total,
        "cm_rms": cm_rms,
        "tail_area_ratio": tail_area_ratio,
        "tail_arm_to_mac": cfg.tail_model.tail_arm_to_mac,
        "tail_arm_m": tail_arm_m,
        "tail_dynamic_pressure_ratio": cfg.tail_model.tail_dynamic_pressure_ratio,
        "tail_efficiency": cfg.tail_model.tail_efficiency,
        "tail_volume_coefficient": trim_result.tail_volume_coefficient,
        "tail_cl_required": trim_result.tail_cl_required,
        "tail_cl_limit_abs": cfg.tail_model.tail_cl_limit_abs,
        "tail_utilization": trim_result.tail_utilization,
        "body_cm_offset": cfg.tail_model.body_cm_offset,
        "margin_deg": trim_result.margin_deg,
        "required_margin_deg": trim_result.required_margin_deg,
        "required_trim_margin_deg": cfg.launch.min_trim_margin_deg,
        "model": "tail_volume_balance",
        "evaluation_case": (
            "reference_avl_case" if trim_station_points else "all_station_points_fallback"
        ),
    }, trim_result


def _summarize_local_stall(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
    mission_summary: dict[str, Any],
) -> dict[str, Any]:
    evaluation_cases = _local_stall_evaluation_cases(
        cfg=cfg,
        concept=concept,
        station_points=station_points,
        mission_summary=mission_summary,
    )
    case_results: list[dict[str, Any]] = []
    for case in evaluation_cases:
        case_label = str(case["case_label"])
        case_role = _local_stall_case_role(case_label)
        gate_enforced = _local_stall_case_gate_enforced(case_label)
        stall_utilization_limit = _local_stall_case_limit(cfg=cfg, case_label=case_label)
        result = evaluate_local_stall(
            station_points=list(case["station_points"]),
            half_span_m=0.5 * concept.span_m,
            stall_utilization_limit=stall_utilization_limit,
        )
        status = _stall_case_status(result)
        case_results.append(
            {
                "case_label": case_label,
                "case_role": case_role,
                "gate_enforced": gate_enforced,
                "report_only": not gate_enforced,
                "reference_speed_mps": case["reference_speed_mps"],
                "reference_gross_mass_kg": case["reference_gross_mass_kg"],
                "evaluation_speed_mps": case["evaluation_speed_mps"],
                "evaluation_gross_mass_kg": case["evaluation_gross_mass_kg"],
                "cl_scale_factor_min": case["cl_scale_factor_min"],
                "cl_scale_factor_max": case["cl_scale_factor_max"],
                "status": status,
                "feasible": result.feasible,
                "hard_gate_feasible": (bool(result.feasible) if gate_enforced else True),
                "required_cl": result.required_cl,
                "cl_max": result.cl_max,
                "min_margin": result.min_margin,
                "stall_utilization": result.stall_utilization,
                "stall_utilization_limit": result.stall_utilization_limit,
                "raw_clmax": result.raw_clmax,
                "safe_clmax": result.safe_clmax,
                "raw_clmax_ratio": result.raw_clmax_ratio,
                "safe_clmax_ratio": result.safe_clmax_ratio,
                "raw_clmax_status": result.raw_clmax_status,
                "safe_clmax_status": result.safe_clmax_status,
                "raw_stall_speed_margin_ratio": result.raw_stall_speed_margin_ratio,
                "safe_stall_speed_margin_ratio": result.safe_stall_speed_margin_ratio,
                "tip_excluded_safe_clmax_ratio": result.tip_excluded_safe_clmax_ratio,
                "outboard_region_safe_clmax_ratio": result.outboard_region_safe_clmax_ratio,
                "contiguous_overlimit_span_fraction": result.contiguous_overlimit_span_fraction,
                "tip_exclusion_eta": result.tip_exclusion_eta,
                "outboard_region_eta_min": result.outboard_region_eta_min,
                "outboard_region_eta_max": result.outboard_region_eta_max,
                "min_margin_station_y_m": result.min_margin_station_y_m,
                "tip_critical": result.tip_critical,
                "margin_source": result.cl_max_source,
            }
        )
    hard_gate_cases = [case for case in case_results if bool(case["gate_enforced"])]
    hard_gate_selection_pool = hard_gate_cases or case_results
    worst_case = max(
        hard_gate_selection_pool,
        key=lambda case: (
            float(case["stall_utilization"]) / max(float(case["stall_utilization_limit"]), 1.0e-9),
            float(case["required_cl"]),
        ),
    )
    worst_report_case = max(
        case_results,
        key=lambda case: (
            float(case["stall_utilization"]) / max(float(case["stall_utilization_limit"]), 1.0e-9),
            float(case["required_cl"]),
        ),
    )
    resolved_evaluation_speed_mps = (
        _numeric_value(worst_case.get("evaluation_speed_mps"))
        or _numeric_value(worst_case.get("reference_speed_mps"))
        or _numeric_value(mission_summary.get("best_range_speed_mps"))
        or float(cfg.launch.release_speed_mps)
    )
    resolved_evaluation_gross_mass_kg = (
        _numeric_value(worst_case.get("evaluation_gross_mass_kg"))
        or _numeric_value(worst_case.get("reference_gross_mass_kg"))
        or _numeric_value(mission_summary.get("evaluated_gross_mass_kg"))
        or _concept_design_gross_mass_kg(cfg, concept)
    )
    stall_utilization = float(worst_case["stall_utilization"])
    stall_utilization_limit = max(float(worst_case["stall_utilization_limit"]), 1.0e-9)
    speed_scale_to_limit = math.sqrt(max(stall_utilization / stall_utilization_limit, 0.0))
    required_speed_for_limit_mps = resolved_evaluation_speed_mps * speed_scale_to_limit
    required_wing_area_for_limit_m2 = float(concept.wing_area_m2) * (stall_utilization / stall_utilization_limit)
    required_gross_mass_for_limit_kg = resolved_evaluation_gross_mass_kg * (
        stall_utilization_limit / max(stall_utilization, 1.0e-9)
    )
    hard_gate_feasible = all(bool(case["hard_gate_feasible"]) for case in case_results)
    return {
        "status": "ok" if hard_gate_feasible else str(worst_case["status"]),
        "feasible": hard_gate_feasible,
        "required_cl": float(worst_case["required_cl"]),
        "cl_max": float(worst_case["cl_max"]),
        "min_margin": float(worst_case["min_margin"]),
        "stall_utilization": stall_utilization,
        "stall_utilization_limit": stall_utilization_limit,
        "raw_clmax": float(worst_case["raw_clmax"]),
        "safe_clmax": float(worst_case["safe_clmax"]),
        "raw_clmax_ratio": float(worst_case["raw_clmax_ratio"]),
        "safe_clmax_ratio": float(worst_case["safe_clmax_ratio"]),
        "raw_clmax_status": str(worst_case["raw_clmax_status"]),
        "safe_clmax_status": str(worst_case["safe_clmax_status"]),
        "raw_stall_speed_margin_ratio": float(worst_case["raw_stall_speed_margin_ratio"]),
        "safe_stall_speed_margin_ratio": float(worst_case["safe_stall_speed_margin_ratio"]),
        "tip_excluded_safe_clmax_ratio": float(worst_case["tip_excluded_safe_clmax_ratio"]),
        "outboard_region_safe_clmax_ratio": float(
            worst_case["outboard_region_safe_clmax_ratio"]
        ),
        "contiguous_overlimit_span_fraction": float(
            worst_case["contiguous_overlimit_span_fraction"]
        ),
        "tip_exclusion_eta": float(worst_case["tip_exclusion_eta"]),
        "outboard_region_eta_min": float(worst_case["outboard_region_eta_min"]),
        "outboard_region_eta_max": float(worst_case["outboard_region_eta_max"]),
        "min_margin_station_y_m": float(worst_case["min_margin_station_y_m"]),
        "tip_critical": bool(worst_case["tip_critical"]),
        "margin_source": str(worst_case["margin_source"]),
        "evaluation_case": str(worst_case["case_label"]),
        "case_role": str(worst_case["case_role"]),
        "worst_hard_gate_case": str(worst_case["case_label"]),
        "worst_report_case": str(worst_report_case["case_label"]),
        "worst_report_case_status": str(worst_report_case["status"]),
        "report_only_case_count": sum(1 for case in case_results if bool(case["report_only"])),
        "reference_speed_mps": worst_case["reference_speed_mps"],
        "reference_gross_mass_kg": worst_case["reference_gross_mass_kg"],
        "evaluation_speed_mps": resolved_evaluation_speed_mps,
        "evaluation_gross_mass_kg": resolved_evaluation_gross_mass_kg,
        "required_speed_for_limit_mps": required_speed_for_limit_mps,
        "delta_speed_for_limit_mps": (required_speed_for_limit_mps - resolved_evaluation_speed_mps),
        "required_wing_area_for_limit_m2": required_wing_area_for_limit_m2,
        "delta_wing_area_for_limit_m2": (required_wing_area_for_limit_m2 - float(concept.wing_area_m2)),
        "required_gross_mass_for_limit_kg": required_gross_mass_for_limit_kg,
        "delta_gross_mass_for_limit_kg": (
            required_gross_mass_for_limit_kg - resolved_evaluation_gross_mass_kg
        ),
        "cl_scale_factor_min": worst_case["cl_scale_factor_min"],
        "cl_scale_factor_max": worst_case["cl_scale_factor_max"],
        "case_results": case_results,
    }


def _speed_sweep_mps(cfg: BirdmanConceptConfig) -> tuple[float, ...]:
    point_count = int(cfg.mission.speed_sweep_points)
    if point_count < 2:
        raise ValueError("mission.speed_sweep_points must be at least 2.")
    min_speed = float(cfg.mission.speed_sweep_min_mps)
    max_speed = float(cfg.mission.speed_sweep_max_mps)
    step = (max_speed - min_speed) / float(point_count - 1)
    return tuple(min_speed + step * index for index in range(point_count))


def _estimate_trim_drag_per_cm_squared(cfg: BirdmanConceptConfig) -> float:
    wing_area_range = cfg.geometry_family.hard_constraints.wing_area_m2_range
    median_wing_area_m2 = 0.5 * (float(wing_area_range.min) + float(wing_area_range.max))
    tail_areas = tuple(float(area) for area in cfg.geometry_family.tail_area_candidates_m2)
    median_tail_area_m2 = float(sorted(tail_areas)[len(tail_areas) // 2]) if tail_areas else 4.0
    if median_tail_area_m2 <= 0.0 or median_wing_area_m2 <= 0.0:
        return 0.0
    tail_arm_to_mac = float(cfg.tail_model.tail_arm_to_mac)
    q_ratio_tail = float(cfg.tail_model.tail_dynamic_pressure_ratio)
    aspect_tail = float(cfg.tail_model.tail_aspect_ratio)
    oswald_tail = float(cfg.tail_model.tail_oswald_efficiency)
    denominator = (
        tail_arm_to_mac * tail_arm_to_mac
        * max(q_ratio_tail, 1.0e-6)
        * math.pi
        * max(aspect_tail, 1.0e-6)
        * max(oswald_tail, 1.0e-6)
    )
    if denominator <= 0.0:
        return 0.0
    return (median_wing_area_m2 / median_tail_area_m2) / denominator


def _concept_design_gross_mass_kg(
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
) -> float:
    if bool(cfg.mass.use_gross_mass_sweep_for_mission_cases):
        return float(max(cfg.mass.gross_mass_sweep_kg))
    if bool(cfg.mass_closure.enabled) and concept.design_gross_mass_kg is not None:
        return float(concept.design_gross_mass_kg)
    return float(max(cfg.mass.gross_mass_sweep_kg))


def _concept_gross_mass_cases(
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
) -> tuple[float, ...]:
    if bool(cfg.mass.use_gross_mass_sweep_for_mission_cases):
        return tuple(float(value) for value in cfg.mass.gross_mass_sweep_kg)
    if bool(cfg.mass_closure.enabled) and concept.design_gross_mass_kg is not None:
        return (float(concept.design_gross_mass_kg),)
    return tuple(float(value) for value in cfg.mass.gross_mass_sweep_kg)


def _mission_speed_feasibility_records(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
    gross_mass_kg: float,
    speed_sweep_mps: tuple[float, ...],
) -> list[dict[str, Any]]:
    if not station_points:
        return [
            {
                "speed_mps": float(speed_mps),
                "feasible": True,
                "status": "no_station_points_available",
                "required_cl": 0.0,
                "cl_max": 0.0,
                "min_margin": 0.0,
                "stall_utilization": 0.0,
                "stall_utilization_limit": float(cfg.stall_model.local_stall_utilization_limit),
                "raw_clmax": 0.0,
                "safe_clmax": 0.0,
                "raw_clmax_ratio": 0.0,
                "safe_clmax_ratio": 0.0,
                "raw_clmax_status": "not_available",
                "safe_clmax_status": "not_available",
                "raw_stall_speed_margin_ratio": None,
                "safe_stall_speed_margin_ratio": None,
                "min_margin_station_y_m": None,
                "tip_critical": False,
                "margin_source": "not_available",
                "cl_scale_factor_min": 1.0,
                "cl_scale_factor_max": 1.0,
            }
            for speed_mps in speed_sweep_mps
        ]

    reference_station_points = _station_points_for_case_label(station_points, "reference_avl_case")
    base_station_points = reference_station_points or [dict(point) for point in station_points]
    first_point = base_station_points[0]
    reference_speed_mps = (
        _numeric_value(first_point.get("evaluation_speed_mps"))
        or _numeric_value(first_point.get("reference_speed_mps"))
        or float(cfg.launch.release_speed_mps)
    )
    reference_gross_mass_kg = (
        _numeric_value(first_point.get("evaluation_gross_mass_kg"))
        or _numeric_value(first_point.get("reference_gross_mass_kg"))
        or _concept_design_gross_mass_kg(cfg, concept)
    )

    normalized_base_station_points = [dict(point) for point in base_station_points]
    if any(
        "cl_max_safe" not in point
        and "cl_max_effective" not in point
        and "cl_max_proxy" not in point
        for point in normalized_base_station_points
    ):
        normalized_base_station_points = _attach_cl_max_proxies(
            normalized_base_station_points,
            half_span_m=0.5 * concept.span_m,
            concept=concept,
            proxy_cfg=cfg.aero_proxies.coarse_spanload,
        )
    normalized_base_station_points = [
        {
            **point,
            "reference_speed_mps": _numeric_value(point.get("reference_speed_mps"))
            or float(reference_speed_mps),
            "reference_gross_mass_kg": _numeric_value(point.get("reference_gross_mass_kg"))
            or float(reference_gross_mass_kg),
        }
        for point in normalized_base_station_points
    ]

    records: list[dict[str, Any]] = []
    for speed_mps in speed_sweep_mps:
        scaled_station_points, cl_scale_factors = _scale_station_points_to_condition(
            station_points=normalized_base_station_points,
            evaluation_speed_mps=float(speed_mps),
            evaluation_gross_mass_kg=float(gross_mass_kg),
            scale_field_name="mission_operating_point_cl_scale_factor",
        )
        result = evaluate_local_stall(
            station_points=scaled_station_points,
            half_span_m=0.5 * concept.span_m,
            stall_utilization_limit=cfg.stall_model.local_stall_utilization_limit,
        )
        records.append(
            {
                "speed_mps": float(speed_mps),
                "feasible": bool(result.feasible),
                "status": str(result.reason),
                "required_cl": float(result.required_cl),
                "cl_max": float(result.cl_max),
                "min_margin": float(result.min_margin),
                "stall_utilization": float(result.stall_utilization),
                "stall_utilization_limit": float(result.stall_utilization_limit),
                "raw_clmax": float(result.raw_clmax),
                "safe_clmax": float(result.safe_clmax),
                "raw_clmax_ratio": float(result.raw_clmax_ratio),
                "safe_clmax_ratio": float(result.safe_clmax_ratio),
                "raw_clmax_status": str(result.raw_clmax_status),
                "safe_clmax_status": str(result.safe_clmax_status),
                "raw_stall_speed_margin_ratio": float(result.raw_stall_speed_margin_ratio),
                "safe_stall_speed_margin_ratio": float(result.safe_stall_speed_margin_ratio),
                "min_margin_station_y_m": float(result.min_margin_station_y_m),
                "tip_critical": bool(result.tip_critical),
                "margin_source": str(result.cl_max_source),
                "cl_scale_factor_min": min(cl_scale_factors) if cl_scale_factors else 1.0,
                "cl_scale_factor_max": max(cl_scale_factors) if cl_scale_factors else 1.0,
            }
        )
    return records


def _estimated_first_feasible_speed_mps(
    speed_feasibility_records: list[dict[str, Any]],
) -> float | None:
    if not speed_feasibility_records:
        return None
    closest_record = min(
        speed_feasibility_records,
        key=lambda record: float(record["stall_utilization"]),
    )
    stall_utilization = float(closest_record["stall_utilization"])
    stall_limit = max(float(closest_record["stall_utilization_limit"]), 1.0e-9)
    return float(closest_record["speed_mps"]) * math.sqrt(stall_utilization / stall_limit)


def _mission_limiter_audit(
    *,
    target_range_m: float,
    speed_sweep_mps: tuple[float, ...],
    rider_curve: FakeAnchorCurve | CsvPowerCurve,
    mass_case_summary: dict[str, Any],
) -> dict[str, Any]:
    feasible_speed_set_mps = [float(speed) for speed in mass_case_summary["feasible_speed_set_mps"]]
    if not feasible_speed_set_mps:
        return {
            "dominant_limiter": "stall_operating_point_unavailable",
            "feasible_speed_count": 0,
            "best_feasible_speed_mps": None,
            "estimated_first_feasible_speed_mps": mass_case_summary["estimated_first_feasible_speed_mps"],
            "delta_v_to_first_feasible_mps": mass_case_summary["delta_v_to_first_feasible_mps"],
            "power_required_at_best_feasible_w": None,
            "available_duration_min_at_best_feasible": None,
            "target_duration_min_at_best_feasible": None,
            "duration_margin_min": None,
            "pilot_power_anchor_w": float(rider_curve.anchor_power_w),
            "pilot_power_max_w": float(rider_curve.max_power_w),
        }

    best_feasible_speed_mps = float(mass_case_summary["best_range_speed_mps"])
    power_by_speed = {
        float(speed_mps): float(power_required_w)
        for speed_mps, power_required_w in zip(
            speed_sweep_mps,
            mass_case_summary["power_required_w"],
            strict=True,
        )
    }
    lookup_speed_mps = min(power_by_speed, key=lambda speed_mps: abs(speed_mps - best_feasible_speed_mps))
    power_required_at_best_feasible_w = float(power_by_speed[lookup_speed_mps])
    available_duration_min = float(rider_curve.duration_at_power_w(power_required_at_best_feasible_w))
    target_duration_min = float(target_range_m) / max(best_feasible_speed_mps, 1.0e-9) / 60.0
    duration_margin_min = available_duration_min - target_duration_min

    if power_required_at_best_feasible_w > float(rider_curve.max_power_w):
        dominant_limiter = "rider_power_ceiling_at_best_feasible_speed"
    elif duration_margin_min < 0.0:
        dominant_limiter = "endurance_shortfall_at_best_feasible_speed"
    else:
        dominant_limiter = "target_range_met"

    return {
        "dominant_limiter": dominant_limiter,
        "feasible_speed_count": len(feasible_speed_set_mps),
        "best_feasible_speed_mps": best_feasible_speed_mps,
        "estimated_first_feasible_speed_mps": mass_case_summary["estimated_first_feasible_speed_mps"],
        "delta_v_to_first_feasible_mps": mass_case_summary["delta_v_to_first_feasible_mps"],
        "power_required_at_best_feasible_w": power_required_at_best_feasible_w,
        "available_duration_min_at_best_feasible": available_duration_min,
        "target_duration_min_at_best_feasible": target_duration_min,
        "duration_margin_min": duration_margin_min,
        "pilot_power_anchor_w": float(rider_curve.anchor_power_w),
        "pilot_power_max_w": float(rider_curve.max_power_w),
    }


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


def _build_slow_speed_report(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    air_density_kg_per_m3: float,
    aspect_ratio: float,
    oswald_efficiency: float,
    profile_cd: float,
    misc_cd: float,
    tail_trim_drag_cd: float,
    rigging_cd: float,
    prop_model: SimplifiedPropModel,
    rider_curve: Any,
    worst_case_result: dict[str, Any],
    drivetrain_efficiency: float,
) -> dict[str, Any]:
    """Build a per-slow-speed report block for `mission_summary`.

    For each speed in ``cfg.mission.slow_report_speeds_mps`` (defaults to an
    empty tuple), evaluate the same drag/power model used by the cruise
    sweep at the worst-case gross mass and return CL_required, total CD,
    drag, shaft power required, available rider power for the corresponding
    duration, and the delta vs the cruise best-range operating point.

    The block is informational only — these speeds are explicitly not part
    of the cruise feasibility filter, so a station-level CL excursion at,
    for example, 6 m/s is reported but does not gate the concept.
    """
    slow_speeds_mps = tuple(float(speed) for speed in cfg.mission.slow_report_speeds_mps)
    raw_best_range_speed = worst_case_result.get("best_range_speed_mps")
    if raw_best_range_speed is None:
        raw_best_range_speed = worst_case_result.get("best_range_unconstrained_speed_mps")
    best_range_speed_mps = (
        None if raw_best_range_speed is None else float(raw_best_range_speed)
    )
    if not slow_speeds_mps:
        return {
            "model": "slow_speed_drag_power_proxy_v1_report_only",
            "evaluation_gross_mass_kg": float(worst_case_result["gross_mass_kg"]),
            "best_range_speed_mps": best_range_speed_mps,
            "speeds": [],
        }

    gross_mass_kg = float(worst_case_result["gross_mass_kg"])
    weight_n = gross_mass_kg * 9.80665
    target_range_m = float(cfg.mission.target_distance_km) * 1000.0
    speeds_payload: list[dict[str, Any]] = []
    for slow_speed_mps in slow_speeds_mps:
        dynamic_pressure_pa = 0.5 * float(air_density_kg_per_m3) * slow_speed_mps**2
        cl_required = weight_n / max(dynamic_pressure_pa * concept.wing_area_m2, 1.0e-9)
        induced_cd = cl_required**2 / max(math.pi * aspect_ratio * oswald_efficiency, 1.0e-9)
        total_cd = profile_cd + induced_cd + misc_cd + tail_trim_drag_cd + rigging_cd
        drag_n = dynamic_pressure_pa * concept.wing_area_m2 * total_cd
        shaft_power_w = _shaft_power_required_w(
            drag_n=drag_n,
            speed_mps=slow_speed_mps,
            prop_model=prop_model,
        )
        pedal_power_w = shaft_power_w / max(drivetrain_efficiency, 1.0e-9)
        required_duration_min = target_range_m / max(slow_speed_mps, 1.0e-9) / 60.0
        available_power_w = float(rider_curve.power_at_duration_min(required_duration_min))
        speeds_payload.append(
            {
                "speed_mps": float(slow_speed_mps),
                "cl_required": float(cl_required),
                "induced_cd": float(induced_cd),
                "total_cd": float(total_cd),
                "drag_n": float(drag_n),
                "shaft_power_required_w": float(shaft_power_w),
                "pedal_power_required_w": float(pedal_power_w),
                "rider_available_power_w_at_required_duration": available_power_w,
                "power_margin_w": float(available_power_w - pedal_power_w),
                "required_duration_min_to_target_range": float(required_duration_min),
                "delta_v_from_best_range_mps": (
                    None
                    if best_range_speed_mps is None
                    else float(slow_speed_mps - best_range_speed_mps)
                ),
            }
        )
    return {
        "model": "slow_speed_drag_power_proxy_v1_report_only",
        "evaluation_gross_mass_kg": gross_mass_kg,
        "best_range_speed_mps": best_range_speed_mps,
        "drivetrain_efficiency": float(drivetrain_efficiency),
        "speeds": speeds_payload,
    }


def _rider_power_thermal_adjustment_summary(
    rider_curve: FakeAnchorCurve | CsvPowerCurve,
) -> dict[str, Any]:
    if isinstance(rider_curve, CsvPowerCurve) and rider_curve.thermal_adjustment:
        return dict(rider_curve.thermal_adjustment)
    return {"enabled": False}


def _propulsion_efficiency_assumptions(cfg: BirdmanConceptConfig) -> dict[str, Any]:
    eta_prop_design = float(cfg.prop.efficiency_model.design_efficiency)
    eta_transmission = float(cfg.drivetrain.efficiency)
    return {
        "profile": "hpa_initial_sizing_suggested_cruise_v1",
        "eta_prop_design": eta_prop_design,
        "eta_transmission": eta_transmission,
        "eta_total_design": eta_prop_design * eta_transmission,
        "prop_efficiency_model": (
            "bemt_proxy_v1"
            if bool(cfg.prop.efficiency_model.use_bemt_proxy)
            else "operating_point_proxy_v1"
        ),
        "prop_design_space": {
            "blade_count": int(cfg.prop.blade_count),
            "diameter_m": float(cfg.prop.diameter_m),
            "rpm_min": float(cfg.prop.rpm_min),
            "rpm_max": float(cfg.prop.rpm_max),
            "use_bemt_proxy": bool(cfg.prop.efficiency_model.use_bemt_proxy),
            "bemt_design_rpm": float(cfg.prop.efficiency_model.bemt_design_rpm),
        },
        "static_propulsive_efficiency_note": (
            "eta_prop = T*V/P_shaft is a forward-flight design-point value; "
            "it is zero by definition at V=0."
        ),
    }


def _build_concept_mission_summary(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    station_points: list[dict[str, float]],
    airfoil_feedback: dict[str, Any],
    trim_summary: dict[str, Any],
    air_density_kg_per_m3: float,
) -> dict[str, Any]:
    speed_sweep_mps = _speed_sweep_mps(cfg)
    cruise_station_points = _station_points_for_case_label(
        station_points,
        "reference_avl_case",
    )
    profile_cd = _mean_effective_cd(
        cruise_station_points or station_points,
        airfoil_feedback,
    )
    aspect_ratio = concept.span_m**2 / max(concept.wing_area_m2, 1.0e-9)
    oswald_efficiency_summary = spanload_efficiency_proxy(
        concept=concept,
        station_points=cruise_station_points or station_points,
        proxy_cfg=cfg.aero_proxies.oswald_efficiency,
    )
    oswald_efficiency = float(oswald_efficiency_summary["efficiency"])
    tail_area_ratio = concept.tail_area_m2 / max(concept.wing_area_m2, 1.0e-9)
    tail_cl_required = abs(float(trim_summary.get("tail_cl_required", 0.0)))
    tail_trim_drag_cd = (
        float(cfg.tail_model.tail_dynamic_pressure_ratio)
        * tail_area_ratio
        * tail_cl_required**2
        / max(
            math.pi
            * float(cfg.tail_model.tail_aspect_ratio)
            * float(cfg.tail_model.tail_oswald_efficiency),
            1.0e-9,
        )
    )
    misc_cd = misc_cd_proxy(
        profile_cd=profile_cd,
        tail_area_ratio=tail_area_ratio,
        proxy_cfg=cfg.aero_proxies.parasite_drag,
    )
    rigging_cda_m2 = compute_rigging_drag_cda_m2(cfg.rigging_drag)
    rigging_cd = rigging_cda_m2 / max(concept.wing_area_m2, 1.0e-9)
    prop_model = SimplifiedPropModel.from_config(
        diameter_m=float(cfg.prop.diameter_m),
        rpm_min=float(cfg.prop.rpm_min),
        rpm_max=float(cfg.prop.rpm_max),
        blade_count=int(cfg.prop.blade_count),
        air_density_kg_per_m3=float(air_density_kg_per_m3),
        efficiency_cfg=cfg.prop.efficiency_model,
    )
    rider_curve = build_rider_power_curve(
        rider_model=str(cfg.mission.rider_model),
        anchor_power_w=float(cfg.mission.anchor_power_w),
        anchor_duration_min=float(cfg.mission.anchor_duration_min),
        rider_power_curve_csv=cfg.mission.rider_power_curve_csv,
        rider_power_curve_metadata_yaml=cfg.mission.rider_power_curve_metadata_yaml,
        duration_column=str(cfg.mission.rider_power_curve_duration_column),
        power_column=str(cfg.mission.rider_power_curve_power_column),
        thermal_adjustment_enabled=bool(
            cfg.mission.rider_power_curve_thermal_adjustment_enabled
        ),
        target_temperature_c=float(cfg.environment.temperature_c),
        target_relative_humidity_percent=float(cfg.environment.relative_humidity),
        heat_loss_coefficient_per_h_c=float(
            cfg.mission.rider_power_curve_heat_loss_coefficient_per_h_c
        ),
    )
    rider_power_thermal_adjustment = _rider_power_thermal_adjustment_summary(rider_curve)

    target_range_m = float(cfg.mission.target_distance_km) * 1000.0
    drivetrain_efficiency = float(cfg.drivetrain.efficiency)
    propulsion_efficiency_assumptions = _propulsion_efficiency_assumptions(cfg)
    mission_results: list[dict[str, Any]] = []
    for gross_mass_kg in _concept_gross_mass_cases(cfg, concept):
        weight_n = float(gross_mass_kg) * 9.80665
        shaft_power_required_w: list[float] = []
        for speed_mps in speed_sweep_mps:
            dynamic_pressure_pa = 0.5 * air_density_kg_per_m3 * speed_mps**2
            cl_required = weight_n / max(dynamic_pressure_pa * concept.wing_area_m2, 1.0e-9)
            induced_cd = cl_required**2 / max(math.pi * aspect_ratio * oswald_efficiency, 1.0e-9)
            total_cd = profile_cd + induced_cd + misc_cd + tail_trim_drag_cd + rigging_cd
            drag_n = dynamic_pressure_pa * concept.wing_area_m2 * total_cd
            shaft_power_required_w.append(
                _shaft_power_required_w(
                    drag_n=drag_n,
                    speed_mps=speed_mps,
                    prop_model=prop_model,
                )
            )
        # Convert shaft power → pedal power via the drivetrain efficiency
        # so the rider's W-tau curve sees the actual effort at the pedal.
        # The legacy ``power_required_w`` field now carries pedal power.
        power_required_w = [
            shaft_w / max(drivetrain_efficiency, 1.0e-9)
            for shaft_w in shaft_power_required_w
        ]

        unconstrained_result = evaluate_mission_objective(
            MissionEvaluationInputs(
                objective_mode=str(cfg.mission.objective_mode),
                target_range_km=float(cfg.mission.target_distance_km),
                speed_mps=speed_sweep_mps,
                power_required_w=tuple(power_required_w),
                rider_curve=rider_curve,
            )
        )
        speed_feasibility_records = _mission_speed_feasibility_records(
            cfg=cfg,
            concept=concept,
            station_points=cruise_station_points or station_points,
            gross_mass_kg=float(gross_mass_kg),
            speed_sweep_mps=speed_sweep_mps,
        )
        feasible_indices = [
            index
            for index, record in enumerate(speed_feasibility_records)
            if bool(record["feasible"])
        ]
        feasible_speed_set_mps = [float(speed_sweep_mps[index]) for index in feasible_indices]
        first_feasible_speed_mps = (
            None if not feasible_speed_set_mps else float(feasible_speed_set_mps[0])
        )
        estimated_first_feasible_speed_mps = (
            None
            if feasible_speed_set_mps
            else _estimated_first_feasible_speed_mps(speed_feasibility_records)
        )
        delta_v_to_first_feasible_mps = (
            None
            if (
                first_feasible_speed_mps is None
                and estimated_first_feasible_speed_mps is None
            )
            else max(
                0.0,
                float(
                    first_feasible_speed_mps
                    if first_feasible_speed_mps is not None
                    else estimated_first_feasible_speed_mps
                )
                - float(unconstrained_result.best_range_speed_mps),
            )
        )
        feasible_result = None
        if feasible_indices:
            feasible_result = evaluate_mission_objective(
                MissionEvaluationInputs(
                    objective_mode=str(cfg.mission.objective_mode),
                    target_range_km=float(cfg.mission.target_distance_km),
                    speed_mps=tuple(speed_sweep_mps[index] for index in feasible_indices),
                    power_required_w=tuple(power_required_w[index] for index in feasible_indices),
                    rider_curve=rider_curve,
                )
            )

        if feasible_result is None:
            mission_feasible = False
            target_range_passed = False
            target_range_margin_m = -target_range_m
            best_range_m = 0.0
            best_range_speed_mps = None
            best_endurance_s = 0.0
            best_power_margin_w = None
            best_power_margin_speed_mps = None
            best_time_s = None
            best_time_speed_mps = None
            fixed_range_feasible_speed_set_mps: tuple[float, ...] = ()
            mission_objective_mode = str(cfg.mission.objective_mode)
            if mission_objective_mode == "max_range":
                mission_score = 0.0
                mission_score_reason = "maximize_range_feasible_only"
            elif mission_objective_mode == "fixed_range_best_time":
                mission_score = fixed_range_infeasible_score(
                    target_range_m=float(target_range_m),
                    best_range_m=0.0,
                    min_speed_mps=float(min(speed_sweep_mps)),
                    slowest_completion_time_s=float(
                        max(unconstrained_result.target_completion_time_s_by_speed)
                    ),
                )
                mission_score_reason = "fixed_range_no_feasible_speed_samples"
            else:
                mission_score = float(unconstrained_result.min_power_w) + 1_000_000.0
                mission_score_reason = "minimize_power_feasible_only"
            operating_point_status = "no_feasible_speed_samples"
        else:
            mission_feasible = bool(feasible_result.mission_feasible)
            target_range_passed = bool(feasible_result.target_range_passed)
            target_range_margin_m = float(feasible_result.target_range_margin_m)
            best_range_m = float(feasible_result.best_range_m)
            best_range_speed_mps = float(feasible_result.best_range_speed_mps)
            best_endurance_s = float(feasible_result.best_endurance_s)
            best_power_margin_w = float(feasible_result.best_power_margin_w)
            best_power_margin_speed_mps = float(feasible_result.best_power_margin_speed_mps)
            best_time_s = feasible_result.best_time_s
            best_time_speed_mps = feasible_result.best_time_speed_mps
            fixed_range_feasible_speed_set_mps = tuple(
                feasible_result.fixed_range_feasible_speed_set_mps
            )
            mission_score = float(feasible_result.mission_score)
            mission_score_reason = str(feasible_result.mission_score_reason)
            operating_point_status = (
                "all_speed_samples_feasible"
                if len(feasible_indices) == len(speed_sweep_mps)
                else "filtered_to_feasible_speeds"
            )

        mission_results.append(
            {
                "gross_mass_kg": float(gross_mass_kg),
                "mission_feasible": mission_feasible,
                "target_range_passed": target_range_passed,
                "target_range_margin_m": target_range_margin_m,
                "best_range_m": best_range_m,
                "best_range_speed_mps": best_range_speed_mps,
                "best_endurance_s": best_endurance_s,
                "best_power_margin_w": best_power_margin_w,
                "best_power_margin_speed_mps": best_power_margin_speed_mps,
                "best_time_s": best_time_s,
                "best_time_speed_mps": best_time_speed_mps,
                "best_time_unconstrained_s": unconstrained_result.best_time_s,
                "best_time_unconstrained_speed_mps": (
                    unconstrained_result.best_time_speed_mps
                ),
                "target_completion_time_s_by_speed": tuple(
                    unconstrained_result.target_completion_time_s_by_speed
                ),
                "fixed_range_feasible_speed_set_mps": tuple(
                    fixed_range_feasible_speed_set_mps
                ),
                "fixed_range_feasible_speed_set_unconstrained_mps": tuple(
                    unconstrained_result.fixed_range_feasible_speed_set_mps
                ),
                "best_power_margin_unconstrained_w": float(
                    unconstrained_result.best_power_margin_w
                ),
                "best_power_margin_unconstrained_speed_mps": float(
                    unconstrained_result.best_power_margin_speed_mps
                ),
                "power_margin_w_by_speed": tuple(unconstrained_result.power_margin_w_by_speed),
                "required_duration_min_by_speed": tuple(
                    unconstrained_result.required_duration_min_by_speed
                ),
                "available_power_w_by_speed": tuple(
                    unconstrained_result.available_power_w_by_speed
                ),
                "min_power_w": float(unconstrained_result.min_power_w),
                "min_power_speed_mps": float(unconstrained_result.min_power_speed_mps),
                "mission_score": mission_score,
                "mission_score_reason": mission_score_reason,
                "pilot_power_model": str(unconstrained_result.pilot_power_model),
                "pilot_power_anchor": str(unconstrained_result.pilot_power_anchor),
                "pilot_power_thermal_adjustment": dict(
                    rider_power_thermal_adjustment
                ),
                "power_required_w": tuple(power_required_w),
                "shaft_power_required_w_by_speed": tuple(shaft_power_required_w),
                "pedal_power_required_w_by_speed": tuple(power_required_w),
                "best_range_unconstrained_m": float(unconstrained_result.best_range_m),
                "best_range_unconstrained_speed_mps": float(
                    unconstrained_result.best_range_speed_mps
                ),
                "best_endurance_unconstrained_s": float(unconstrained_result.best_endurance_s),
                "feasible_speed_set_mps": feasible_speed_set_mps,
                "first_feasible_speed_mps": first_feasible_speed_mps,
                "estimated_first_feasible_speed_mps": estimated_first_feasible_speed_mps,
                "delta_v_to_first_feasible_mps": delta_v_to_first_feasible_mps,
                "operating_point_status": operating_point_status,
                "operating_point_feasible": bool(feasible_indices),
                "speed_feasibility_records": speed_feasibility_records,
            }
        )
        mission_results[-1]["limiter_audit"] = _mission_limiter_audit(
            target_range_m=target_range_m,
            speed_sweep_mps=speed_sweep_mps,
            rider_curve=rider_curve,
            mass_case_summary=mission_results[-1],
        )

    worst_case_result = max(
        mission_results,
        key=lambda item: (
            float(item["mission_score"]),
            -float(item["best_power_margin_unconstrained_w"]),
            float(item["gross_mass_kg"]),
        ),
    )

    slow_speed_report = _build_slow_speed_report(
        cfg=cfg,
        concept=concept,
        air_density_kg_per_m3=air_density_kg_per_m3,
        aspect_ratio=aspect_ratio,
        oswald_efficiency=oswald_efficiency,
        profile_cd=profile_cd,
        misc_cd=misc_cd,
        tail_trim_drag_cd=tail_trim_drag_cd,
        rigging_cd=rigging_cd,
        prop_model=prop_model,
        rider_curve=rider_curve,
        worst_case_result=worst_case_result,
        drivetrain_efficiency=drivetrain_efficiency,
    )

    best_range_speed_mps_for_loss = worst_case_result.get("best_range_speed_mps")
    if best_range_speed_mps_for_loss is None:
        best_range_speed_mps_for_loss = worst_case_result.get(
            "best_range_unconstrained_speed_mps"
        )
    if best_range_speed_mps_for_loss is None:
        drivetrain_loss_w_at_best_range = None
    else:
        speeds = list(worst_case_result["power_required_w"])
        sweep_speeds = list(speed_sweep_mps)
        # Find pedal power at best range speed (exact match in the sweep grid)
        pedal_power_at_best = None
        for sweep_v, pedal_w in zip(sweep_speeds, speeds):
            if abs(float(sweep_v) - float(best_range_speed_mps_for_loss)) < 1.0e-9:
                pedal_power_at_best = float(pedal_w)
                break
        drivetrain_loss_w_at_best_range = (
            None
            if pedal_power_at_best is None
            else pedal_power_at_best * (1.0 - drivetrain_efficiency)
        )

    return {
        "mission_objective_mode": str(cfg.mission.objective_mode),
        "mission_feasible": all(bool(result["mission_feasible"]) for result in mission_results),
        "target_range_km": float(cfg.mission.target_distance_km),
        "target_range_passed": all(bool(result["target_range_passed"]) for result in mission_results),
        "target_range_margin_m": min(
            float(result["target_range_margin_m"]) for result in mission_results
        ),
        "best_range_m": float(worst_case_result["best_range_m"]),
        "best_range_speed_mps": worst_case_result["best_range_speed_mps"],
        "best_range_unconstrained_m": float(worst_case_result["best_range_unconstrained_m"]),
        "best_range_unconstrained_speed_mps": float(
            worst_case_result["best_range_unconstrained_speed_mps"]
        ),
        "best_endurance_s": float(worst_case_result["best_endurance_s"]),
        "best_endurance_unconstrained_s": float(
            worst_case_result["best_endurance_unconstrained_s"]
        ),
        "best_time_s": worst_case_result["best_time_s"],
        "best_time_speed_mps": worst_case_result["best_time_speed_mps"],
        "best_time_unconstrained_s": worst_case_result["best_time_unconstrained_s"],
        "best_time_unconstrained_speed_mps": worst_case_result[
            "best_time_unconstrained_speed_mps"
        ],
        "target_completion_time_s_by_speed": list(
            worst_case_result["target_completion_time_s_by_speed"]
        ),
        "fixed_range_feasible_speed_set_mps": list(
            worst_case_result["fixed_range_feasible_speed_set_mps"]
        ),
        "fixed_range_feasible_speed_set_unconstrained_mps": list(
            worst_case_result["fixed_range_feasible_speed_set_unconstrained_mps"]
        ),
        "best_power_margin_w": worst_case_result["best_power_margin_w"],
        "best_power_margin_speed_mps": worst_case_result["best_power_margin_speed_mps"],
        "best_power_margin_unconstrained_w": float(
            worst_case_result["best_power_margin_unconstrained_w"]
        ),
        "best_power_margin_unconstrained_speed_mps": float(
            worst_case_result["best_power_margin_unconstrained_speed_mps"]
        ),
        "power_margin_w_by_speed": list(worst_case_result["power_margin_w_by_speed"]),
        "required_duration_min_by_speed": list(
            worst_case_result["required_duration_min_by_speed"]
        ),
        "available_power_w_by_speed": list(
            worst_case_result["available_power_w_by_speed"]
        ),
        "min_power_w": float(worst_case_result["min_power_w"]),
        "min_power_speed_mps": float(worst_case_result["min_power_speed_mps"]),
        "mission_score": float(worst_case_result["mission_score"]),
        "mission_score_reason": str(worst_case_result["mission_score_reason"]),
        "pilot_power_model": str(worst_case_result["pilot_power_model"]),
        "pilot_power_anchor": str(worst_case_result["pilot_power_anchor"]),
        "pilot_power_thermal_adjustment": dict(rider_power_thermal_adjustment),
        "speed_sweep_window_mps": [float(min(speed_sweep_mps)), float(max(speed_sweep_mps))],
        "aggregation_mode": "worst_case_over_gross_mass_sweep",
        "evaluated_gross_mass_kg": float(worst_case_result["gross_mass_kg"]),
        "profile_cd_proxy": profile_cd,
        "misc_cd_proxy": misc_cd,
        "trim_drag_cd_proxy": tail_trim_drag_cd,
        "rigging_cda_m2": float(rigging_cda_m2),
        "rigging_cd_proxy": float(rigging_cd),
        "drivetrain_efficiency": drivetrain_efficiency,
        "propulsion_efficiency_assumptions": dict(propulsion_efficiency_assumptions),
        "drivetrain_loss_w_at_best_range": drivetrain_loss_w_at_best_range,
        "slow_speed_report": slow_speed_report,
        "tail_cl_required_for_trim": tail_cl_required,
        "oswald_efficiency_proxy": oswald_efficiency,
        "oswald_efficiency_source": str(oswald_efficiency_summary["source"]),
        "geometry_oswald_efficiency_proxy": float(
            oswald_efficiency_summary["geometry_efficiency_proxy"]
        ),
        "spanload_rms_error": oswald_efficiency_summary["spanload_rms_error"],
        "propulsion_model": "simplified_prop_proxy_v1",
        "mission_speed_filter_model": "reference_case_local_stall_feasible_speed_v1",
        "operating_point_status": str(worst_case_result["operating_point_status"]),
        "operating_point_feasible": bool(worst_case_result["operating_point_feasible"]),
        "feasible_speed_set_mps": list(worst_case_result["feasible_speed_set_mps"]),
        "first_feasible_speed_mps": worst_case_result["first_feasible_speed_mps"],
        "estimated_first_feasible_speed_mps": worst_case_result[
            "estimated_first_feasible_speed_mps"
        ],
        "delta_v_to_first_feasible_mps": worst_case_result["delta_v_to_first_feasible_mps"],
        "speed_feasibility_records": list(worst_case_result["speed_feasibility_records"]),
        "limiter_audit": dict(worst_case_result["limiter_audit"]),
        "mission_case_source": "reference_avl_case"
        if cruise_station_points
        else "all_station_points_fallback",
        "mass_cases": [
            {
                "gross_mass_kg": float(result["gross_mass_kg"]),
                "mission_feasible": bool(result["mission_feasible"]),
                "target_range_passed": bool(result["target_range_passed"]),
                "target_range_margin_m": float(result["target_range_margin_m"]),
                "best_range_m": float(result["best_range_m"]),
                "best_range_speed_mps": result["best_range_speed_mps"],
                "best_range_unconstrained_m": float(result["best_range_unconstrained_m"]),
                "best_range_unconstrained_speed_mps": float(
                    result["best_range_unconstrained_speed_mps"]
                ),
                "best_endurance_s": float(result["best_endurance_s"]),
                "best_endurance_unconstrained_s": float(
                    result["best_endurance_unconstrained_s"]
                ),
                "best_time_s": result["best_time_s"],
                "best_time_speed_mps": result["best_time_speed_mps"],
                "best_time_unconstrained_s": result["best_time_unconstrained_s"],
                "best_time_unconstrained_speed_mps": result[
                    "best_time_unconstrained_speed_mps"
                ],
                "target_completion_time_s_by_speed": list(
                    result["target_completion_time_s_by_speed"]
                ),
                "fixed_range_feasible_speed_set_mps": list(
                    result["fixed_range_feasible_speed_set_mps"]
                ),
                "fixed_range_feasible_speed_set_unconstrained_mps": list(
                    result["fixed_range_feasible_speed_set_unconstrained_mps"]
                ),
                "best_power_margin_w": result["best_power_margin_w"],
                "best_power_margin_speed_mps": result["best_power_margin_speed_mps"],
                "best_power_margin_unconstrained_w": float(
                    result["best_power_margin_unconstrained_w"]
                ),
                "best_power_margin_unconstrained_speed_mps": float(
                    result["best_power_margin_unconstrained_speed_mps"]
                ),
                "power_margin_w_by_speed": list(result["power_margin_w_by_speed"]),
                "required_duration_min_by_speed": list(
                    result["required_duration_min_by_speed"]
                ),
                "available_power_w_by_speed": list(
                    result["available_power_w_by_speed"]
                ),
                "min_power_w": float(result["min_power_w"]),
                "min_power_speed_mps": float(result["min_power_speed_mps"]),
                "mission_score": float(result["mission_score"]),
                "mission_score_reason": str(result["mission_score_reason"]),
                "pilot_power_model": str(result["pilot_power_model"]),
                "pilot_power_anchor": str(result["pilot_power_anchor"]),
                "pilot_power_thermal_adjustment": dict(
                    result["pilot_power_thermal_adjustment"]
                ),
                "feasible_speed_set_mps": list(result["feasible_speed_set_mps"]),
                "first_feasible_speed_mps": result["first_feasible_speed_mps"],
                "estimated_first_feasible_speed_mps": result[
                    "estimated_first_feasible_speed_mps"
                ],
                "delta_v_to_first_feasible_mps": result["delta_v_to_first_feasible_mps"],
                "operating_point_status": str(result["operating_point_status"]),
                "operating_point_feasible": bool(result["operating_point_feasible"]),
                "speed_feasibility_records": list(result["speed_feasibility_records"]),
                "limiter_audit": dict(result["limiter_audit"]),
                "power_required_w": list(result["power_required_w"]),
                "shaft_power_required_w_by_speed": list(
                    result["shaft_power_required_w_by_speed"]
                ),
                "pedal_power_required_w_by_speed": list(
                    result["pedal_power_required_w_by_speed"]
                ),
            }
            for result in mission_results
        ],
        "power_required_w": list(worst_case_result["power_required_w"]),
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


def _reference_condition_consistency_audit(
    *,
    zone_requirements: dict[str, dict[str, Any]],
    mission_summary: dict[str, Any],
) -> dict[str, Any]:
    reference_speeds_mps = sorted(
        {
            float(zone_data["reference_speed_mps"])
            for zone_data in zone_requirements.values()
            if zone_data.get("reference_speed_mps") is not None
        }
    )
    reference_speed_filter_models = sorted(
        {
            str(zone_data["reference_speed_filter_model"])
            for zone_data in zone_requirements.values()
            if zone_data.get("reference_speed_filter_model")
        }
    )
    pre_avl_best_ranges_m = sorted(
        {
            float(zone_data["pre_avl_best_range_m"])
            for zone_data in zone_requirements.values()
            if zone_data.get("pre_avl_best_range_m") is not None
        }
    )
    pre_avl_best_feasible_ranges_m = sorted(
        {
            float(zone_data["pre_avl_best_range_feasible_m"])
            for zone_data in zone_requirements.values()
            if zone_data.get("pre_avl_best_range_feasible_m") is not None
        }
    )

    pre_avl_reference_speed_mps = (
        None if len(reference_speeds_mps) != 1 else float(reference_speeds_mps[0])
    )
    pre_avl_best_range_m = None if len(pre_avl_best_ranges_m) != 1 else float(pre_avl_best_ranges_m[0])
    pre_avl_best_feasible_range_m = (
        None
        if len(pre_avl_best_feasible_ranges_m) != 1
        else float(pre_avl_best_feasible_ranges_m[0])
    )

    post_airfoil_best_feasible_speed_mps = _numeric_value(mission_summary.get("best_range_speed_mps"))
    post_airfoil_first_feasible_speed_mps = _numeric_value(
        mission_summary.get("first_feasible_speed_mps")
    )
    post_airfoil_best_unconstrained_speed_mps = _numeric_value(
        mission_summary.get("best_range_unconstrained_speed_mps")
    )
    post_airfoil_best_range_m = _numeric_value(mission_summary.get("best_range_m"))
    post_airfoil_best_unconstrained_range_m = _numeric_value(
        mission_summary.get("best_range_unconstrained_m")
    )
    post_airfoil_feasible_speed_set_mps = sorted(
        float(speed_mps) for speed_mps in mission_summary.get("feasible_speed_set_mps", [])
    )

    reference_speed_in_post_airfoil_feasible_set = None
    if pre_avl_reference_speed_mps is not None and post_airfoil_feasible_speed_set_mps:
        reference_speed_in_post_airfoil_feasible_set = any(
            math.isclose(pre_avl_reference_speed_mps, speed_mps, rel_tol=0.0, abs_tol=1.0e-9)
            for speed_mps in post_airfoil_feasible_speed_set_mps
        )

    delta_reference_to_post_airfoil_best_feasible_mps = (
        None
        if pre_avl_reference_speed_mps is None or post_airfoil_best_feasible_speed_mps is None
        else float(pre_avl_reference_speed_mps - post_airfoil_best_feasible_speed_mps)
    )
    delta_reference_to_post_airfoil_first_feasible_mps = (
        None
        if pre_avl_reference_speed_mps is None or post_airfoil_first_feasible_speed_mps is None
        else float(pre_avl_reference_speed_mps - post_airfoil_first_feasible_speed_mps)
    )
    pre_avl_to_post_airfoil_unconstrained_range_ratio = (
        None
        if pre_avl_best_range_m is None
        or post_airfoil_best_unconstrained_range_m is None
        or post_airfoil_best_unconstrained_range_m <= 0.0
        else float(pre_avl_best_range_m / post_airfoil_best_unconstrained_range_m)
    )
    pre_avl_to_post_airfoil_feasible_range_ratio = (
        None
        if pre_avl_best_feasible_range_m is None
        or post_airfoil_best_range_m is None
        or post_airfoil_best_range_m <= 0.0
        else float(pre_avl_best_feasible_range_m / post_airfoil_best_range_m)
    )

    rerun_reasons: list[str] = []
    if reference_speed_in_post_airfoil_feasible_set is False:
        rerun_reasons.append("reference_speed_outside_post_airfoil_feasible_set")
    if (
        delta_reference_to_post_airfoil_first_feasible_mps is not None
        and abs(delta_reference_to_post_airfoil_first_feasible_mps) >= 1.0
    ):
        rerun_reasons.append("reference_speed_delta_exceeds_1mps")
    if (
        pre_avl_to_post_airfoil_unconstrained_range_ratio is not None
        and (
            pre_avl_to_post_airfoil_unconstrained_range_ratio > 1.5
            or pre_avl_to_post_airfoil_unconstrained_range_ratio < (2.0 / 3.0)
        )
    ):
        rerun_reasons.append("pre_avl_unconstrained_range_ratio_out_of_family")
    if (
        pre_avl_to_post_airfoil_feasible_range_ratio is not None
        and (
            pre_avl_to_post_airfoil_feasible_range_ratio > 1.5
            or pre_avl_to_post_airfoil_feasible_range_ratio < (2.0 / 3.0)
        )
    ):
        rerun_reasons.append("pre_avl_feasible_range_ratio_out_of_family")

    return {
        "pre_avl_reference_speed_mps": pre_avl_reference_speed_mps,
        "post_airfoil_best_feasible_speed_mps": post_airfoil_best_feasible_speed_mps,
        "post_airfoil_first_feasible_speed_mps": post_airfoil_first_feasible_speed_mps,
        "post_airfoil_best_unconstrained_speed_mps": post_airfoil_best_unconstrained_speed_mps,
        "post_airfoil_feasible_speed_set_mps": post_airfoil_feasible_speed_set_mps,
        "reference_speed_in_post_airfoil_feasible_set": reference_speed_in_post_airfoil_feasible_set,
        "delta_reference_to_post_airfoil_best_feasible_mps": (
            delta_reference_to_post_airfoil_best_feasible_mps
        ),
        "delta_reference_to_post_airfoil_first_feasible_mps": (
            delta_reference_to_post_airfoil_first_feasible_mps
        ),
        "pre_avl_best_range_m": pre_avl_best_range_m,
        "post_airfoil_best_range_m": post_airfoil_best_range_m,
        "pre_avl_best_unconstrained_range_m": pre_avl_best_range_m,
        "post_airfoil_best_unconstrained_range_m": post_airfoil_best_unconstrained_range_m,
        "pre_avl_best_feasible_range_m": pre_avl_best_feasible_range_m,
        "pre_avl_to_post_airfoil_unconstrained_range_ratio": (
            pre_avl_to_post_airfoil_unconstrained_range_ratio
        ),
        "pre_avl_to_post_airfoil_feasible_range_ratio": (
            pre_avl_to_post_airfoil_feasible_range_ratio
        ),
        "reference_speed_filter_models": reference_speed_filter_models,
        "rerun_recommended": bool(rerun_reasons),
        "rerun_reasons": rerun_reasons,
    }


def _summarize_spanwise_requirements(
    zone_requirements: dict[str, dict[str, Any]],
    mission_summary: dict[str, Any] | None = None,
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
    reference_speed_filter_models = sorted(
        {
            str(zone_data["reference_speed_filter_model"])
            for zone_data in zone_requirements.values()
            if zone_data.get("reference_speed_filter_model")
        }
    )
    design_case_labels = sorted(
        {
            str(case["case_label"])
            for zone_data in zone_requirements.values()
            for case in zone_data.get("design_cases", [])
            if isinstance(case, dict) and case.get("case_label")
        }
    )
    consistency_audit = (
        None
        if mission_summary is None
        else _reference_condition_consistency_audit(
            zone_requirements=zone_requirements,
            mission_summary=mission_summary,
        )
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
        "reference_speed_filter_models": reference_speed_filter_models,
        "mass_selection_reasons": mass_selection_reasons,
        "design_case_labels": design_case_labels,
        "design_case_count": len(design_case_labels),
        "reference_condition_consistency_audit": consistency_audit,
    }


def _evaluate_selected_airfoils_for_concept(
    *,
    concept_id: str,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    zone_requirements: dict[str, dict[str, Any]],
    selected_by_zone: dict[str, SelectedZoneCandidate],
    worker: AirfoilWorker,
    analysis_mode: str,
    analysis_stage: str,
    air_density_kg_per_m3: float,
) -> tuple[
    dict[str, SelectedZoneCandidate],
    dict[str, dict[str, Any]],
    list[dict[str, object]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    CandidateConceptResult,
]:
    airfoil_templates = _build_selected_cst_airfoil_templates(
        selected_by_zone=selected_by_zone,
        zone_requirements=zone_requirements,
    )
    station_points = _flatten_zone_points(zone_requirements, stations)
    station_points = _attach_cl_max_proxies(
        station_points,
        half_span_m=0.5 * concept.span_m,
        concept=concept,
        proxy_cfg=cfg.aero_proxies.coarse_spanload,
    )
    worker_queries, worker_point_refs = _build_worker_queries_and_refs(
        zone_requirements=zone_requirements,
        airfoil_templates=airfoil_templates,
        analysis_mode=analysis_mode,
        analysis_stage=analysis_stage,
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
        tip_3d_penalty_start_eta=cfg.stall_model.tip_3d_penalty_start_eta,
        tip_3d_penalty_max=cfg.stall_model.tip_3d_penalty_max,
        tip_taper_penalty_weight=cfg.stall_model.tip_taper_penalty_weight,
        washout_relief_deg=cfg.stall_model.washout_relief_deg,
        washout_relief_max=cfg.stall_model.washout_relief_max,
    )
    airfoil_feedback = {
        **airfoil_feedback,
        **safe_clmax_summary,
    }
    updated_selected_by_zone = _update_selected_by_zone_from_station_points(
        selected_by_zone=selected_by_zone,
        station_points=station_points,
        safe_scale=cfg.stall_model.safe_clmax_scale,
        safe_delta=cfg.stall_model.safe_clmax_delta,
    )
    airfoil_templates = _build_selected_cst_airfoil_templates(
        selected_by_zone=updated_selected_by_zone,
        zone_requirements=zone_requirements,
    )
    trim_summary, trim_result = _summarize_trim(
        cfg=cfg,
        concept=concept,
        station_points=station_points,
    )
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
    mission_summary = _build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=station_points,
        airfoil_feedback=airfoil_feedback,
        trim_summary=trim_summary,
        air_density_kg_per_m3=air_density_kg_per_m3,
    )
    local_stall_summary = _summarize_local_stall(
        cfg=cfg,
        concept=concept,
        station_points=station_points,
        mission_summary=mission_summary,
    )
    ranking_input = CandidateConceptResult(
        concept_id=concept_id,
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
        mission_margin_m=float(mission_summary["target_range_margin_m"]),
    )
    return (
        updated_selected_by_zone,
        airfoil_templates,
        worker_results,
        airfoil_feedback,
        launch_summary,
        turn_summary,
        trim_summary,
        local_stall_summary,
        mission_summary,
        ranking_input,
    )


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


def _collect_worker_cache_statistics(worker: AirfoilWorker) -> dict[str, int] | None:
    statistics = getattr(worker, "cache_statistics", None)
    if not isinstance(statistics, dict):
        return None
    cache_hits = statistics.get("cache_hits")
    cache_misses = statistics.get("cache_misses")
    if not isinstance(cache_hits, int) or not isinstance(cache_misses, int):
        return None
    return {"cache_hits": int(cache_hits), "cache_misses": int(cache_misses)}


def _close_worker_if_supported(worker: AirfoilWorker) -> None:
    close = getattr(worker, "close", None)
    if callable(close):
        close()


def _worker_statuses(worker_results: list[dict[str, object]]) -> tuple[str, ...]:
    statuses: list[str] = []
    for result in worker_results:
        status = result.get("status")
        statuses.append("unknown" if status is None else str(status))
    return tuple(statuses)


def _worker_analysis_modes(worker_results: list[dict[str, object]]) -> tuple[str, ...]:
    modes: list[str] = []
    for result in worker_results:
        mode = result.get("analysis_mode")
        modes.append("unknown" if mode is None else str(mode))
    return tuple(modes)


def _worker_analysis_stages(worker_results: list[dict[str, object]]) -> tuple[str, ...]:
    stages: list[str] = []
    for result in worker_results:
        stage = result.get("analysis_stage")
        stages.append("unknown" if stage is None else str(stage))
    return tuple(stages)


def _worker_fidelity_summary(worker_results: list[dict[str, object]]) -> dict[str, Any]:
    return {
        "worker_result_count": len(worker_results),
        "worker_statuses": list(_worker_statuses(worker_results)),
        "worker_analysis_modes": list(_worker_analysis_modes(worker_results)),
        "worker_analysis_stages": list(_worker_analysis_stages(worker_results)),
    }


def _count_strings(values: list[str] | tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _config_sha256(config_path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(config_path).read_bytes()).hexdigest()
    except OSError:
        return None


def _worker_backend_is_stub(worker_backend: str) -> bool:
    return worker_backend in {"test_stub", "cli_stubbed", "python_stubbed"}


def _feedback_has_fallback_reason(feedback: dict[str, Any], reason: str) -> bool:
    if str(feedback.get("fallback_reason", "")) == reason:
        return True
    return any(
        isinstance(point, dict) and str(point.get("fallback_reason", "")) == reason
        for point in feedback.get("points", [])
    )


def _concept_spanwise_fallback_reasons(
    zone_requirements: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    reasons = sorted(
        {
            str(zone_data["fallback_reason"])
            for zone_data in zone_requirements.values()
            if zone_data.get("fallback_reason")
        }
    )
    return tuple(reasons)


def _concept_spanwise_sources(
    zone_requirements: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    sources = sorted(
        {
            str(zone_data.get("source", "unknown"))
            for zone_data in zone_requirements.values()
        }
    )
    return tuple(sources)


def _concept_artifact_trust(
    *,
    cfg: BirdmanConceptConfig,
    worker_backend: str,
    worker_results: list[dict[str, object]],
    screening_worker_results: list[dict[str, object]],
    zone_requirements: dict[str, dict[str, Any]],
    airfoil_feedback: dict[str, Any],
    screening_airfoil_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    all_worker_results = list(screening_worker_results)
    if any(stage == "finalist" for stage in _worker_analysis_stages(worker_results)):
        all_worker_results.extend(worker_results)
    elif not all_worker_results:
        all_worker_results.extend(worker_results)
    statuses = _worker_statuses(all_worker_results)
    status_set = set(statuses)
    spanwise_sources = _concept_spanwise_sources(zone_requirements)
    spanwise_fallback_reasons = _concept_spanwise_fallback_reasons(zone_requirements)
    feedbacks = [airfoil_feedback]
    if screening_airfoil_feedback is not None and screening_airfoil_feedback is not airfoil_feedback:
        feedbacks.append(screening_airfoil_feedback)

    hard_flags = {
        "route_not_decision_validated": True,
        "stub_worker_detected": _worker_backend_is_stub(worker_backend)
        or "stubbed_ok" in status_set,
        "worker_fallback_detected": any(status != "ok" for status in statuses),
        "mini_sweep_fallback_detected": "mini_sweep_fallback" in status_set,
        "worker_result_count_mismatch_detected": any(
            _feedback_has_fallback_reason(feedback, "worker_result_count_mismatch")
            for feedback in feedbacks
        ),
        "missing_polar_data_detected": any(
            int(feedback.get("fallback_worker_point_count", 0) or 0) > 0
            or _feedback_has_fallback_reason(feedback, "missing_usable_polar_points")
            for feedback in feedbacks
        ),
        "spanwise_fallback_detected": any(
            source.startswith("fallback") for source in spanwise_sources
        ),
        "simplified_prop_proxy": not bool(cfg.prop.efficiency_model.use_bemt_proxy),
        "openvsp_export_disabled": not bool(cfg.output.export_vsp),
    }
    reasons = [key for key, detected in hard_flags.items() if detected]
    return {
        "schema_version": "artifact_trust_v1",
        "decision_grade": False,
        "decision_grade_status": "diagnostic_only",
        "not_decision_grade_reasons": reasons,
        "hard_flags": hard_flags,
        "worker_backend": worker_backend,
        "worker_status_counts": _count_strings(statuses),
        "spanwise_sources": list(spanwise_sources),
        "spanwise_fallback_reasons": list(spanwise_fallback_reasons),
    }


def _run_artifact_trust(
    *,
    cfg: BirdmanConceptConfig,
    config_path: Path,
    worker_backend: str,
    summary_worker_statuses: list[str],
    evaluated_concepts: list[_EvaluatedConcept],
) -> dict[str, Any]:
    concept_trust_blocks = [
        _concept_artifact_trust(
            cfg=cfg,
            worker_backend=record.worker_backend,
            worker_results=record.worker_results,
            screening_worker_results=record.screening_worker_results,
            zone_requirements=record.zone_requirements,
            airfoil_feedback=record.airfoil_feedback,
            screening_airfoil_feedback=record.screening_airfoil_feedback,
        )
        for record in evaluated_concepts
    ]
    hard_flags = {
        "route_not_decision_validated": True,
        "stub_worker_detected": _worker_backend_is_stub(worker_backend)
        or any(block["hard_flags"]["stub_worker_detected"] for block in concept_trust_blocks),
        "worker_fallback_detected": any(status != "ok" for status in summary_worker_statuses)
        or any(block["hard_flags"]["worker_fallback_detected"] for block in concept_trust_blocks),
        "mini_sweep_fallback_detected": "mini_sweep_fallback" in set(summary_worker_statuses)
        or any(block["hard_flags"]["mini_sweep_fallback_detected"] for block in concept_trust_blocks),
        "worker_result_count_mismatch_detected": any(
            block["hard_flags"]["worker_result_count_mismatch_detected"]
            for block in concept_trust_blocks
        ),
        "missing_polar_data_detected": any(
            block["hard_flags"]["missing_polar_data_detected"]
            for block in concept_trust_blocks
        ),
        "spanwise_fallback_detected": any(
            block["hard_flags"]["spanwise_fallback_detected"]
            for block in concept_trust_blocks
        ),
        "simplified_prop_proxy": not bool(cfg.prop.efficiency_model.use_bemt_proxy),
        "openvsp_export_disabled": not bool(cfg.output.export_vsp),
    }
    reasons = [key for key, detected in hard_flags.items() if detected]
    spanwise_sources = sorted(
        {
            source
            for block in concept_trust_blocks
            for source in block["spanwise_sources"]
        }
    )
    spanwise_fallback_reasons = sorted(
        {
            reason
            for block in concept_trust_blocks
            for reason in block["spanwise_fallback_reasons"]
        }
    )
    return {
        "schema_version": "artifact_trust_v1",
        "decision_grade": False,
        "decision_grade_status": "diagnostic_only",
        "not_decision_grade_reasons": reasons,
        "hard_flags": hard_flags,
        "config_path": str(Path(config_path)),
        "config_sha256": _config_sha256(config_path),
        "worker_backend": worker_backend,
        "worker_status_counts": _count_strings(tuple(summary_worker_statuses)),
        "spanwise_sources": spanwise_sources,
        "spanwise_fallback_reasons": spanwise_fallback_reasons,
    }


def _concept_geometry_summary(concept: GeometryConcept) -> dict[str, Any]:
    return {
        "primary_variables": {
            "planform_parameterization": str(concept.planform_parameterization),
            "span_m": float(concept.span_m),
            "mean_chord_m": (
                None
                if concept.mean_chord_target_m is None
                else float(concept.mean_chord_target_m)
            ),
            "wing_loading_target_Npm2": (
                None
                if concept.wing_loading_target_Npm2 is None
                else float(concept.wing_loading_target_Npm2)
            ),
            "taper_ratio": float(concept.taper_ratio),
            "twist_mid_deg": (
                None
                if len(concept.twist_control_points) < 3
                else float(concept.twist_control_points[1][1])
            ),
            "twist_outer_deg": (
                None
                if len(concept.twist_control_points) < 4
                else float(concept.twist_control_points[2][1])
            ),
            "tip_twist_deg": float(concept.twist_tip_deg),
            "spanload_bias": float(concept.spanload_bias),
        },
        "derived_geometry": {
            "wing_area_m2": float(concept.wing_area_m2),
            "root_chord_m": float(concept.root_chord_m),
            "tip_chord_m": float(concept.tip_chord_m),
            "mean_aerodynamic_chord_m": float(concept.mean_aerodynamic_chord_m),
            "aspect_ratio": float(concept.aspect_ratio),
            "wing_area_source": str(concept.wing_area_source),
            "tail_area_m2": float(concept.tail_area_m2),
            "tail_area_source": str(concept.tail_area_source),
            "tail_volume_coefficient": (
                None
                if concept.tail_volume_coefficient is None
                else float(concept.tail_volume_coefficient)
            ),
            "twist_control_points": [
                {"eta": float(eta), "twist_deg": float(twist_deg)}
                for eta, twist_deg in concept.twist_control_points
            ],
            "design_gross_mass_kg": (
                None
                if concept.design_gross_mass_kg is None
                else float(concept.design_gross_mass_kg)
            ),
            "tip_deflection_ratio_at_design_mass": (
                None
                if concept.tip_deflection_ratio_at_design_mass is None
                else float(concept.tip_deflection_ratio_at_design_mass)
            ),
            "tip_deflection_m_at_design_mass": (
                None
                if concept.tip_deflection_m_at_design_mass is None
                else float(concept.tip_deflection_m_at_design_mass)
            ),
            "effective_dihedral_deg_at_design_mass": (
                None
                if concept.effective_dihedral_deg_at_design_mass is None
                else float(concept.effective_dihedral_deg_at_design_mass)
            ),
            "unbraced_tip_deflection_m_at_design_mass": (
                None
                if concept.unbraced_tip_deflection_m_at_design_mass is None
                else float(concept.unbraced_tip_deflection_m_at_design_mass)
            ),
            "lift_wire_relief_deflection_m_at_design_mass": (
                None
                if concept.lift_wire_relief_deflection_m_at_design_mass is None
                else float(concept.lift_wire_relief_deflection_m_at_design_mass)
            ),
            "tip_deflection_preferred_status": concept.tip_deflection_preferred_status,
            "lift_wire_tension_at_limit_n": (
                None
                if concept.lift_wire_tension_at_limit_n is None
                else float(concept.lift_wire_tension_at_limit_n)
            ),
        },
    }


def _mass_proxy_limitations() -> list[str]:
    return [
        "not_a_structural_sizing_authority",
        "spar_not_bending_or_buckling_sized",
        "wire_geometry_and_joint_mass_not_solved",
        "fixed_nonwing_mass_is_user_budget_not_measured_bom",
    ]


def _sizing_diagnostics(
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
) -> dict[str, Any]:
    archetype = sizing_archetype(
        {
            "wing_area_m2": concept.wing_area_m2,
            "wing_loading_target_Npm2": concept.wing_loading_target_Npm2,
            "aspect_ratio": concept.aspect_ratio,
        }
    )
    closure_summary = None
    if concept.wing_loading_target_Npm2 is not None:
        tube_mass_kg = _resolve_tube_system_mass_kg(
            cfg.mass_closure, span_m=float(concept.span_m)
        )
        try:
            if concept.planform_parameterization == "mean_chord":
                fixed_mass = estimate_fixed_planform_mass(
                    wing_area_m2=float(concept.wing_area_m2),
                    pilot_mass_kg=float(cfg.mass.design_pilot_mass_kg),
                    fixed_non_area_aircraft_mass_kg=float(
                        cfg.mass_closure.fixed_nonwing_aircraft_mass_kg
                    ),
                    wing_areal_density_kgpm2=float(
                        cfg.mass_closure.rib_skin_areal_density_kgpm2
                    ),
                    tube_system_mass_kg=tube_mass_kg,
                    wing_fittings_base_kg=float(cfg.mass_closure.wing_fittings_base_kg),
                    wire_terminal_mass_kg=float(cfg.mass_closure.wire_terminal_mass_kg),
                    extra_system_margin_kg=float(cfg.mass_closure.system_margin_kg),
                )
                closure = None
                closed_wing_area_m2 = float(fixed_mass.wing_area_m2)
                closed_gross_mass_kg = float(fixed_mass.gross_mass_kg)
                mass_breakdown_kg = dict(fixed_mass.mass_breakdown_kg)
                area_residual_m2 = 0.0
                iterations = 0
                model_name = "fixed_planform_mass_proxy_v1_report_only"
                status = "ok"
            else:
                closure = close_area_mass(
                    wing_loading_target_Npm2=float(concept.wing_loading_target_Npm2),
                    pilot_mass_kg=float(cfg.mass.design_pilot_mass_kg),
                    fixed_non_area_aircraft_mass_kg=float(
                        cfg.mass_closure.fixed_nonwing_aircraft_mass_kg
                    ),
                    wing_areal_density_kgpm2=float(
                        cfg.mass_closure.rib_skin_areal_density_kgpm2
                    ),
                    tube_system_mass_kg=tube_mass_kg,
                    wing_fittings_base_kg=float(cfg.mass_closure.wing_fittings_base_kg),
                    wire_terminal_mass_kg=float(cfg.mass_closure.wire_terminal_mass_kg),
                    extra_system_margin_kg=float(cfg.mass_closure.system_margin_kg),
                    initial_wing_area_m2=float(concept.wing_area_m2),
                    tolerance_m2=float(cfg.mass_closure.area_tolerance_m2),
                    max_iterations=int(cfg.mass_closure.max_iterations),
                )
                closed_wing_area_m2 = float(closure.closed_wing_area_m2)
                closed_gross_mass_kg = float(closure.closed_gross_mass_kg)
                mass_breakdown_kg = dict(closure.mass_breakdown_kg)
                area_residual_m2 = float(closure.area_residual_m2)
                iterations = int(closure.iterations)
                model_name = "area_mass_closure_v1_report_only"
                status = "ok" if closure.converged else "not_converged"
            design_gross_mass_kg = (
                None
                if concept.design_gross_mass_kg is None
                else float(concept.design_gross_mass_kg)
            )
            closure_pilot_mass_kg = float(cfg.mass.design_pilot_mass_kg)
            closed_aircraft_empty_mass_kg = float(closed_gross_mass_kg - closure_pilot_mass_kg)
            aircraft_empty_mass_target_min_kg = float(
                min(cfg.mass.aircraft_empty_mass_cases_kg)
            )
            aircraft_empty_mass_target_max_kg = float(
                max(cfg.mass.aircraft_empty_mass_cases_kg)
            )
            closure_summary = {
                "model": model_name,
                "model_authority": "unvalidated_first_order_accounting_proxy",
                "limitations": _mass_proxy_limitations(),
                "status": status,
                "closed_wing_area_m2": float(closed_wing_area_m2),
                "current_wing_area_m2": float(concept.wing_area_m2),
                "closed_area_delta_m2": float(closed_wing_area_m2 - concept.wing_area_m2),
                "closed_area_ratio_to_current": float(
                    closed_wing_area_m2 / max(concept.wing_area_m2, 1.0e-9)
                ),
                "closed_gross_mass_kg": float(closed_gross_mass_kg),
                "design_gross_mass_kg": design_gross_mass_kg,
                "closed_gross_mass_delta_vs_design_kg": (
                    None
                    if design_gross_mass_kg is None
                    else float(closed_gross_mass_kg - design_gross_mass_kg)
                ),
                "closed_aircraft_empty_mass_kg": closed_aircraft_empty_mass_kg,
                "aircraft_empty_mass_target_range_kg": [
                    aircraft_empty_mass_target_min_kg,
                    aircraft_empty_mass_target_max_kg,
                ],
                "aircraft_empty_mass_excess_vs_target_max_kg": float(
                    closed_aircraft_empty_mass_kg - aircraft_empty_mass_target_max_kg
                ),
                "aircraft_empty_mass_within_target_range": bool(
                    aircraft_empty_mass_target_min_kg
                    <= closed_aircraft_empty_mass_kg
                    <= aircraft_empty_mass_target_max_kg
                ),
                "mass_breakdown_kg": mass_breakdown_kg,
                "area_residual_m2": area_residual_m2,
                "iterations": iterations,
                "assumptions": {
                    "pilot_mass_kg": closure_pilot_mass_kg,
                    "fixed_non_area_aircraft_mass_kg": float(
                        cfg.mass_closure.fixed_nonwing_aircraft_mass_kg
                    ),
                    "fixed_mass_source": "mass_closure.fixed_nonwing_aircraft_mass_kg",
                    "tube_system_mass_kg": float(tube_mass_kg),
                    "tube_system_mass_source": _tube_mass_source_tag(cfg.mass_closure),
                    "wing_fittings_base_kg": float(
                        cfg.mass_closure.wing_fittings_base_kg
                    ),
                    "wire_terminal_mass_kg": float(cfg.mass_closure.wire_terminal_mass_kg),
                    "wing_areal_density_kgpm2": float(
                        cfg.mass_closure.rib_skin_areal_density_kgpm2
                    ),
                },
            }
        except ValueError as exc:
            closure_summary = {
                "model": "area_mass_closure_v1_report_only",
                "status": "invalid_assumptions",
                "error": str(exc),
            }

    return {
        "model": "upstream_sizing_diagnostics_v1_report_only",
        "sizing_archetype": archetype,
        "area_mass_closure": closure_summary,
    }


def _build_ranked_concept_record(
    *,
    cfg: BirdmanConceptConfig,
    record: _EvaluatedConcept,
    ranked: Any,
    rank: int,
    overall_rank: int,
    bundle_dir: Path | None,
) -> dict[str, Any]:
    sizing_diagnostics = _sizing_diagnostics(cfg, record.concept)
    return {
        "concept_id": record.evaluation_id,
        "enumeration_index": record.enumeration_index,
        "rank": rank,
        "overall_rank": overall_rank,
        "bundle_dir": str(bundle_dir) if bundle_dir is not None else None,
        "openvsp_handoff": _openvsp_handoff_summary(bundle_dir),
        "span_m": record.concept.span_m,
        "planform_parameterization": str(record.concept.planform_parameterization),
        "mean_chord_target_m": (
            None
            if record.concept.mean_chord_target_m is None
            else float(record.concept.mean_chord_target_m)
        ),
        "wing_area_m2": record.concept.wing_area_m2,
        "wing_loading_target_Npm2": (
            None
            if record.concept.wing_loading_target_Npm2 is None
            else float(record.concept.wing_loading_target_Npm2)
        ),
        "wing_area_source": str(record.concept.wing_area_source),
        "mean_aerodynamic_chord_m": float(record.concept.mean_aerodynamic_chord_m),
        "aspect_ratio": float(record.concept.aspect_ratio),
        "tail_area_m2": float(record.concept.tail_area_m2),
        "tail_area_source": str(record.concept.tail_area_source),
        "tail_volume_coefficient": (
            None
            if record.concept.tail_volume_coefficient is None
            else float(record.concept.tail_volume_coefficient)
        ),
        "spanload_bias": float(record.concept.spanload_bias),
        "sizing_archetype": str(sizing_diagnostics["sizing_archetype"]),
        "sizing_diagnostics": sizing_diagnostics,
        "zone_count": len(record.zone_requirements),
        "worker_result_count": len(record.worker_results),
        "worker_backend": record.worker_backend,
        "worker_statuses": list(_worker_statuses(record.worker_results)),
        "worker_analysis_modes": list(_worker_analysis_modes(record.worker_results)),
        "worker_analysis_stages": list(_worker_analysis_stages(record.worker_results)),
        "worker_fidelity": {
            "screening": _worker_fidelity_summary(record.screening_worker_results),
            "finalist": (
                _worker_fidelity_summary(record.worker_results)
                if any(stage == "finalist" for stage in _worker_analysis_stages(record.worker_results))
                else None
            ),
        },
        "artifact_trust": _concept_artifact_trust(
            cfg=cfg,
            worker_backend=record.worker_backend,
            worker_results=record.worker_results,
            screening_worker_results=record.screening_worker_results,
            zone_requirements=record.zone_requirements,
            airfoil_feedback=record.airfoil_feedback,
            screening_airfoil_feedback=record.screening_airfoil_feedback,
        ),
        "airfoil_feedback": record.airfoil_feedback,
        "launch": record.launch_summary,
        "turn": record.turn_summary,
        "trim": record.trim_summary,
        "local_stall": record.local_stall_summary,
        "spanwise_requirements": _summarize_spanwise_requirements(
            record.zone_requirements,
            record.mission_summary,
        ),
        "mission": record.mission_summary,
        "ranking": {
            "score": ranked.score,
            "selection_status": ranked.selection_status,
            "why_not_higher": list(ranked.why_not_higher),
            "safety_margin": record.ranking_input.safety_margin,
            "mission_margin_m": record.ranking_input.mission_margin_m,
            "failed_gate_count": ranked.failed_gate_count,
            "combined_feasibility_margin": ranked.combined_feasibility_margin,
            "safety_feasible": ranked.safety_feasible,
            "fully_feasible": ranked.fully_feasible,
            "assembly_penalty": record.ranking_input.assembly_penalty,
            "ranking_basis": "feasibility_first_contract_aligned_v2",
            "selection_scope": "ranked_sampled_pool",
        },
        **_concept_geometry_summary(record.concept),
    }


def _openvsp_handoff_summary(bundle_dir: Path | None) -> dict[str, Any] | None:
    if bundle_dir is None:
        return None
    bundle_dir = Path(bundle_dir)
    script_path = bundle_dir / "concept_openvsp.vspscript"
    metadata_path = bundle_dir / "concept_openvsp_metadata.json"
    if not script_path.exists() and not metadata_path.exists():
        return None
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}
    vsp3_build = metadata.get("vsp3_build") if isinstance(metadata, dict) else None
    if not isinstance(vsp3_build, dict):
        vsp3_build = {}
    vsp3_path_value = vsp3_build.get("path") or vsp3_build.get("target_path")
    return {
        "script_path": str(script_path) if script_path.exists() else None,
        "metadata_path": str(metadata_path) if metadata_path.exists() else None,
        "vsp3_path": None if vsp3_path_value is None else str(vsp3_path_value),
        "vsp3_build_status": str(vsp3_build.get("status", "unknown")),
    }


def _concept_to_bundle_payload(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    zone_requirements: dict[str, dict[str, Any]],
    airfoil_templates: dict[str, dict[str, Any]],
    worker_results: list[dict[str, object]],
    screening_worker_results: list[dict[str, object]],
    worker_backend: str,
    concept_index: int,
    enumeration_index: int,
    airfoil_feedback: dict[str, Any],
    screening_airfoil_feedback: dict[str, Any],
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
    concept_config.setdefault("mission", {})
    concept_config["mission"]["resolved_rider_model"] = str(cfg.mission.resolved_rider_model)
    geometry_summary = _concept_geometry_summary(concept)
    sizing_diagnostics = _sizing_diagnostics(cfg, concept)
    concept_config["geometry"] = {
        "span_m": float(concept.span_m),
        "planform_parameterization": str(concept.planform_parameterization),
        "mean_chord_target_m": (
            None
            if concept.mean_chord_target_m is None
            else float(concept.mean_chord_target_m)
        ),
        "wing_loading_target_Npm2": (
            None
            if concept.wing_loading_target_Npm2 is None
            else float(concept.wing_loading_target_Npm2)
        ),
        "wing_area_m2": float(concept.wing_area_m2),
        "wing_area_source": str(concept.wing_area_source),
        "root_chord_m": float(concept.root_chord_m),
        "tip_chord_m": float(concept.tip_chord_m),
        "mean_aerodynamic_chord_m": float(concept.mean_aerodynamic_chord_m),
        "aspect_ratio": float(concept.aspect_ratio),
        "twist_root_deg": float(concept.twist_root_deg),
        "twist_control_points": [
            {"eta": float(eta), "twist_deg": float(twist_deg)}
            for eta, twist_deg in concept.twist_control_points
        ],
        "twist_tip_deg": float(concept.twist_tip_deg),
        "spanload_bias": float(concept.spanload_bias),
        "dihedral_root_deg": float(concept.dihedral_root_deg),
        "dihedral_tip_deg": float(concept.dihedral_tip_deg),
        "dihedral_exponent": float(concept.dihedral_exponent),
        "tail_area_m2": float(concept.tail_area_m2),
        "tail_area_source": str(concept.tail_area_source),
        "tail_volume_coefficient": (
            None
            if concept.tail_volume_coefficient is None
            else float(concept.tail_volume_coefficient)
        ),
        "cg_xc": float(concept.cg_xc),
        "segment_lengths_m": list(concept.segment_lengths_m),
        "design_gross_mass_kg": (
            None
            if concept.design_gross_mass_kg is None
            else float(concept.design_gross_mass_kg)
        ),
        "tip_deflection_m_at_design_mass": (
            None
            if concept.tip_deflection_m_at_design_mass is None
            else float(concept.tip_deflection_m_at_design_mass)
        ),
        "effective_dihedral_deg_at_design_mass": (
            None
            if concept.effective_dihedral_deg_at_design_mass is None
            else float(concept.effective_dihedral_deg_at_design_mass)
        ),
        "tip_deflection_preferred_status": concept.tip_deflection_preferred_status,
        "sizing_archetype": str(sizing_diagnostics["sizing_archetype"]),
        "sizing_diagnostics": sizing_diagnostics,
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
    raw_zone_templates = {
        zone_name: (
            tuple(payload["upper_coefficients"]),
            tuple(payload["lower_coefficients"]),
            float(payload["te_thickness_m"]),
            payload.get("seed_name"),
            payload.get("candidate_role", "selected"),
        )
        for zone_name, payload in airfoil_templates.items()
    }
    if raw_zone_templates:
        max_upper_count = max(len(values[0]) for values in raw_zone_templates.values())
        max_lower_count = max(len(values[1]) for values in raw_zone_templates.values())
    else:
        max_upper_count = 0
        max_lower_count = 0

    def _pad_to(values: tuple[float, ...], target_count: int) -> tuple[float, ...]:
        if len(values) >= target_count:
            return values
        return values + tuple(0.0 for _ in range(target_count - len(values)))

    lofting_guides = build_lofting_guides(
        {
            zone_name: CSTAirfoilTemplate(
                zone_name=zone_name,
                upper_coefficients=_pad_to(values[0], max_upper_count),
                lower_coefficients=_pad_to(values[1], max_lower_count),
                te_thickness_m=values[2],
                seed_name=values[3],
                candidate_role=values[4],
            )
            for zone_name, values in raw_zone_templates.items()
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
    finalist_worker_results = (
        worker_results
        if any(stage == "finalist" for stage in _worker_analysis_stages(worker_results))
        else []
    )
    concept_summary = {
        "selected": True,
        "concept_id": f"concept-{concept_index:02d}",
        "enumeration_index": enumeration_index,
        "rank": concept_index,
        "span_m": float(concept.span_m),
        "wing_area_m2": float(concept.wing_area_m2),
        "wing_loading_target_Npm2": (
            None
            if concept.wing_loading_target_Npm2 is None
            else float(concept.wing_loading_target_Npm2)
        ),
        "wing_area_source": str(concept.wing_area_source),
        "mean_aerodynamic_chord_m": float(concept.mean_aerodynamic_chord_m),
        "aspect_ratio": float(concept.aspect_ratio),
        "sizing_archetype": str(sizing_diagnostics["sizing_archetype"]),
        "sizing_diagnostics": sizing_diagnostics,
        "station_count": len(stations),
        "zone_count": len(zone_requirements),
        "worker_result_count": len(worker_results),
        "worker_backend": worker_backend,
        "worker_statuses": list(worker_statuses),
        "worker_analysis_modes": list(_worker_analysis_modes(worker_results)),
        "worker_analysis_stages": list(_worker_analysis_stages(worker_results)),
        "worker_fidelity": {
            "screening": _worker_fidelity_summary(screening_worker_results),
            "finalist": (
                _worker_fidelity_summary(finalist_worker_results)
                if finalist_worker_results
                else None
            ),
        },
        "artifact_trust": _concept_artifact_trust(
            cfg=cfg,
            worker_backend=worker_backend,
            worker_results=worker_results,
            screening_worker_results=screening_worker_results,
            zone_requirements=zone_requirements,
            airfoil_feedback=airfoil_feedback,
            screening_airfoil_feedback=screening_airfoil_feedback,
        ),
        "airfoil_feedback": airfoil_feedback,
        "launch": launch_summary,
        "turn": turn_summary,
        "trim": trim_summary,
        "local_stall": local_stall_summary,
        "spanwise_requirements": spanwise_requirement_summary,
        "mission": mission_summary,
        "ranking": ranking_summary,
        **geometry_summary,
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
    geometry_diagnostics = get_last_geometry_enumeration_diagnostics()
    if len(all_concepts) < 3:
        raise RuntimeError("Birdman concept enumeration must yield at least 3 candidate concepts.")
    concepts = all_concepts

    repo_root = _repo_root()
    worker = airfoil_worker_factory(
        project_dir=repo_root,
        cache_dir=output_dir / "polar_db",
        persistent_worker_count=cfg.polar_worker.persistent_worker_count,
        xfoil_max_iter=cfg.polar_worker.xfoil_max_iter,
        xfoil_panel_count=cfg.polar_worker.xfoil_panel_count,
    )
    worker_backend = _worker_backend(worker)
    air_properties = _air_properties_from_environment(cfg)
    air_density_kg_per_m3 = air_properties.density_kg_per_m3

    evaluated_concepts: list[_EvaluatedConcept] = []
    selected_concept_dirs: list[Path] = []
    best_infeasible_concept_dirs: list[Path] = []
    summary_worker_statuses: list[str] = []

    prepared_concepts: list[_PreparedConcept] = []
    zone_requirements_with_points_by_concept: dict[str, dict[str, dict[str, Any]]] = {}
    for enumeration_index, concept in enumerate(concepts, start=1):
        concept_id = f"eval-{enumeration_index:02d}"
        stations = build_linear_wing_stations(
            concept,
            stations_per_half=cfg.pipeline.stations_per_half,
        )
        zone_requirements = spanwise_loader(concept, stations)
        zone_requirements = _annotate_zone_requirements_with_concept_geometry(
            zone_requirements=zone_requirements,
            concept=concept,
        )
        prepared_concepts.append(
            _PreparedConcept(
                evaluation_id=concept_id,
                enumeration_index=enumeration_index,
                concept=concept,
                stations=stations,
                zone_requirements=zone_requirements,
            )
        )
        zone_requirements_with_points = {
            zone_name: zone_data
            for zone_name, zone_data in zone_requirements.items()
            if zone_data.get("points")
        }
        if zone_requirements_with_points:
            zone_requirements_with_points_by_concept[concept_id] = zone_requirements_with_points

    try:
        selection_batches_by_concept = (
            select_zone_airfoil_templates_for_concepts(
                concept_zone_requirements=zone_requirements_with_points_by_concept,
                seed_loader=_load_seed_airfoil_coordinates,
                worker=_SelectionWorkerAdapter(
                    worker,
                    allow_stub_fallback=worker_backend
                    in {"test_stub", "cli_stubbed", "python_stubbed"},
                ),
                search_mode=cfg.cst_search.search_mode,
                selection_strategy=cfg.cst_search.selection_strategy,
                thickness_delta_levels=cfg.cst_search.thickness_delta_levels,
                camber_delta_levels=cfg.cst_search.camber_delta_levels,
                seedless_sample_count=cfg.cst_search.seedless_sample_count,
                seedless_random_seed=cfg.cst_search.seedless_random_seed,
                seedless_max_oversample_factor=cfg.cst_search.seedless_max_oversample_factor,
                robust_evaluation_enabled=cfg.cst_search.robust_evaluation_enabled,
                robust_reynolds_factors=cfg.cst_search.robust_reynolds_factors,
                robust_roughness_modes=cfg.cst_search.robust_roughness_modes,
                robust_min_pass_rate=cfg.cst_search.robust_min_pass_rate,
                nsga_generation_count=cfg.cst_search.nsga_generation_count,
                nsga_offspring_count=cfg.cst_search.nsga_offspring_count,
                nsga_parent_count=cfg.cst_search.nsga_parent_count,
                nsga_random_seed=cfg.cst_search.nsga_random_seed,
                nsga_mutation_scale=cfg.cst_search.nsga_mutation_scale,
                coarse_to_fine_enabled=cfg.cst_search.coarse_to_fine_enabled,
                coarse_thickness_stride=cfg.cst_search.coarse_thickness_stride,
                coarse_camber_stride=cfg.cst_search.coarse_camber_stride,
                coarse_keep_top_k=cfg.cst_search.coarse_keep_top_k,
                refine_neighbor_radius=cfg.cst_search.refine_neighbor_radius,
                successive_halving_enabled=cfg.cst_search.successive_halving_enabled,
                successive_halving_rounds=cfg.cst_search.successive_halving_rounds,
                successive_halving_beam_width=cfg.cst_search.successive_halving_beam_width,
                cm_hard_lower_bound=cfg.cst_search.cm_hard_lower_bound,
                cm_penalty_threshold=cfg.cst_search.cm_penalty_threshold,
                pareto_knee_count=cfg.cst_search.pareto_knee_count,
                cma_es_enabled=cfg.cst_search.cma_es_enabled,
                cma_es_knee_count=cfg.cst_search.cma_es_knee_count,
                cma_es_iterations=cfg.cst_search.cma_es_iterations,
                cma_es_population_lambda=cfg.cst_search.cma_es_population_lambda,
                cma_es_sigma_init=cfg.cst_search.cma_es_sigma_init,
                cma_es_random_seed=cfg.cst_search.cma_es_random_seed,
                trim_drag_per_cm_squared=_estimate_trim_drag_per_cm_squared(cfg),
                safe_clmax_scale=cfg.stall_model.safe_clmax_scale,
                safe_clmax_delta=cfg.stall_model.safe_clmax_delta,
                stall_utilization_limit=cfg.stall_model.local_stall_utilization_limit,
                tip_3d_penalty_start_eta=cfg.stall_model.tip_3d_penalty_start_eta,
                tip_3d_penalty_max=cfg.stall_model.tip_3d_penalty_max,
                tip_taper_penalty_weight=cfg.stall_model.tip_taper_penalty_weight,
                washout_relief_deg=cfg.stall_model.washout_relief_deg,
                washout_relief_max=cfg.stall_model.washout_relief_max,
                launch_stall_utilization_limit=cfg.stall_model.launch_utilization_limit,
                turn_stall_utilization_limit=cfg.stall_model.turn_utilization_limit,
                local_stall_utilization_limit=cfg.stall_model.local_stall_utilization_limit,
                score_cfg=cfg.airfoil_selection_score,
            )
            if zone_requirements_with_points_by_concept
            else {}
        )

        for prepared in prepared_concepts:
            concept_id = prepared.evaluation_id
            concept = prepared.concept
            stations = prepared.stations
            zone_requirements = prepared.zone_requirements
            zone_requirements_without_points = {
                zone_name: zone_data
                for zone_name, zone_data in zone_requirements.items()
                if not zone_data.get("points")
            }
            selected_by_zone: dict[str, SelectedZoneCandidate] = {}
            selection_batch = selection_batches_by_concept.get(concept_id)
            if selection_batch is not None:
                selected_by_zone.update(selection_batch.selected_by_zone)
            for zone_name in zone_requirements_without_points:
                selected_by_zone[zone_name] = _build_fallback_selected_zone_candidate(
                    zone_name=zone_name,
                    seed_coordinates=_load_seed_airfoil_coordinates(
                        _ROOT_SEED_AIRFOIL if zone_name in {"root", "mid1"} else _TIP_SEED_AIRFOIL
                    ),
                    safe_clmax_scale=cfg.stall_model.safe_clmax_scale,
                    safe_clmax_delta=cfg.stall_model.safe_clmax_delta,
                )
            airfoil_templates = _build_selected_cst_airfoil_templates(
                selected_by_zone=selected_by_zone,
                zone_requirements=zone_requirements,
            )
            (
                selected_by_zone,
                airfoil_templates,
                worker_results,
                airfoil_feedback,
                launch_summary,
                turn_summary,
                trim_summary,
                local_stall_summary,
                mission_summary,
                ranking_input,
            ) = _evaluate_selected_airfoils_for_concept(
                concept_id=concept_id,
                cfg=cfg,
                concept=concept,
                stations=stations,
                zone_requirements=zone_requirements,
                selected_by_zone=selected_by_zone,
                worker=worker,
                analysis_mode="screening_target_cl",
                analysis_stage="screening",
                air_density_kg_per_m3=air_density_kg_per_m3,
            )
            concept_worker_statuses = _worker_statuses(worker_results)
            summary_worker_statuses.extend(concept_worker_statuses)
            evaluated_concepts.append(
                _EvaluatedConcept(
                    evaluation_id=ranking_input.concept_id,
                    enumeration_index=prepared.enumeration_index,
                    concept=concept,
                    stations=stations,
                    zone_requirements=zone_requirements,
                    selected_by_zone=selected_by_zone,
                    airfoil_templates=airfoil_templates,
                    screening_worker_results=list(worker_results),
                    worker_results=worker_results,
                    worker_backend=worker_backend,
                    screening_airfoil_feedback=airfoil_feedback,
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
        finalist_ranked = ranked_concepts[
            : min(len(ranked_concepts), int(cfg.pipeline.finalist_full_sweep_top_l))
        ]
        finalist_ids = {ranked.concept_id for ranked in finalist_ranked}
        if finalist_ids:
            reevaluated: list[_EvaluatedConcept] = []
            for record in evaluated_concepts:
                if record.evaluation_id not in finalist_ids:
                    reevaluated.append(record)
                    continue

                avl_rerun_context = _spanwise_loader_avl_rerun_context(spanwise_loader)
                current_zone_requirements = record.zone_requirements
                current_selected_by_zone = record.selected_by_zone
                current_airfoil_templates = record.airfoil_templates
                current_worker_results: list[dict[str, object]]
                current_airfoil_feedback: dict[str, Any]
                current_launch_summary: dict[str, Any]
                current_turn_summary: dict[str, Any]
                current_trim_summary: dict[str, Any]
                current_local_stall_summary: dict[str, Any]
                current_mission_summary: dict[str, Any]
                current_ranking_input: CandidateConceptResult
                finalist_evaluation_completed = False

                if avl_rerun_context is None:
                    (
                        current_selected_by_zone,
                        current_airfoil_templates,
                        current_worker_results,
                        current_airfoil_feedback,
                        current_launch_summary,
                        current_turn_summary,
                        current_trim_summary,
                        current_local_stall_summary,
                        current_mission_summary,
                        current_ranking_input,
                    ) = _evaluate_selected_airfoils_for_concept(
                        concept_id=record.evaluation_id,
                        cfg=cfg,
                        concept=record.concept,
                        stations=record.stations,
                        zone_requirements=current_zone_requirements,
                        selected_by_zone=current_selected_by_zone,
                        worker=worker,
                        analysis_mode="full_alpha_sweep",
                        analysis_stage="finalist",
                        air_density_kg_per_m3=air_density_kg_per_m3,
                    )
                    summary_worker_statuses.extend(_worker_statuses(current_worker_results))
                    finalist_evaluation_completed = True
                else:
                    current_mission_summary = record.mission_summary
                    for rerun_iteration_index in range(1, 3):
                        rerun_zone_requirements = _rerun_finalist_zone_requirements_from_post_airfoil_avl(
                            spanwise_loader=spanwise_loader,
                            concept=record.concept,
                            stations=record.stations,
                            airfoil_templates=current_airfoil_templates,
                            mission_summary=current_mission_summary,
                            rerun_iteration_index=rerun_iteration_index,
                        )
                        if rerun_zone_requirements is None:
                            break
                        current_zone_requirements = rerun_zone_requirements
                        (
                            current_selected_by_zone,
                            current_airfoil_templates,
                            current_worker_results,
                            current_airfoil_feedback,
                            current_launch_summary,
                            current_turn_summary,
                            current_trim_summary,
                            current_local_stall_summary,
                            current_mission_summary,
                            current_ranking_input,
                        ) = _evaluate_selected_airfoils_for_concept(
                            concept_id=record.evaluation_id,
                            cfg=cfg,
                            concept=record.concept,
                            stations=record.stations,
                            zone_requirements=current_zone_requirements,
                            selected_by_zone=current_selected_by_zone,
                            worker=worker,
                            analysis_mode="full_alpha_sweep",
                            analysis_stage="finalist",
                            air_density_kg_per_m3=air_density_kg_per_m3,
                        )
                        summary_worker_statuses.extend(_worker_statuses(current_worker_results))
                        finalist_evaluation_completed = True
                        consistency_audit = _reference_condition_consistency_audit(
                            zone_requirements=current_zone_requirements,
                            mission_summary=current_mission_summary,
                        )
                        if not _should_iterate_post_airfoil_avl_reference(
                            consistency_audit=consistency_audit,
                            rerun_iteration_count=rerun_iteration_index,
                        ):
                            break

                if not finalist_evaluation_completed:
                    (
                        current_selected_by_zone,
                        current_airfoil_templates,
                        current_worker_results,
                        current_airfoil_feedback,
                        current_launch_summary,
                        current_turn_summary,
                        current_trim_summary,
                        current_local_stall_summary,
                        current_mission_summary,
                        current_ranking_input,
                    ) = _evaluate_selected_airfoils_for_concept(
                        concept_id=record.evaluation_id,
                        cfg=cfg,
                        concept=record.concept,
                        stations=record.stations,
                        zone_requirements=current_zone_requirements,
                        selected_by_zone=current_selected_by_zone,
                        worker=worker,
                        analysis_mode="full_alpha_sweep",
                        analysis_stage="finalist",
                        air_density_kg_per_m3=air_density_kg_per_m3,
                    )
                    summary_worker_statuses.extend(_worker_statuses(current_worker_results))
                reevaluated.append(
                    _EvaluatedConcept(
                        evaluation_id=record.evaluation_id,
                        enumeration_index=record.enumeration_index,
                        concept=record.concept,
                        stations=record.stations,
                        zone_requirements=current_zone_requirements,
                        selected_by_zone=current_selected_by_zone,
                        airfoil_templates=current_airfoil_templates,
                        screening_worker_results=record.screening_worker_results,
                        worker_results=current_worker_results,
                        worker_backend=record.worker_backend,
                        screening_airfoil_feedback=record.screening_airfoil_feedback,
                        airfoil_feedback=current_airfoil_feedback,
                        launch_summary=current_launch_summary,
                        turn_summary=current_turn_summary,
                        trim_summary=current_trim_summary,
                        local_stall_summary=current_local_stall_summary,
                        mission_summary=current_mission_summary,
                        ranking_input=current_ranking_input,
                    )
                )
            evaluated_concepts = reevaluated
            ranked_concepts = rank_concepts([record.ranking_input for record in evaluated_concepts])
    finally:
        _close_worker_if_supported(worker)
    evaluated_by_id = {record.evaluation_id: record for record in evaluated_concepts}
    summary_records: list[dict[str, Any]] = []
    best_infeasible_records: list[dict[str, Any]] = []

    selected_ranked = [ranked for ranked in ranked_concepts if ranked.fully_feasible]
    selected_output_ranked = selected_ranked[: int(cfg.pipeline.keep_top_n)]
    infeasible_ranked = [ranked for ranked in ranked_concepts if not ranked.fully_feasible]
    best_infeasible_ranked = (
        infeasible_ranked[:1]
        if selected_output_ranked
        else infeasible_ranked[: int(cfg.pipeline.keep_top_n)]
    )
    overall_rank_by_id = {
        item.concept_id: index for index, item in enumerate(ranked_concepts, start=1)
    }
    ranked_pool_records = [
        _build_ranked_concept_record(
            cfg=cfg,
            record=evaluated_by_id[ranked.concept_id],
            ranked=ranked,
            rank=overall_rank_by_id[ranked.concept_id],
            overall_rank=overall_rank_by_id[ranked.concept_id],
            bundle_dir=None,
        )
        for ranked in ranked_concepts
    ]

    for concept_index, ranked in enumerate(selected_output_ranked, start=1):
        record = evaluated_by_id[ranked.concept_id]
        ranking_summary = {
            "score": ranked.score,
            "selection_status": ranked.selection_status,
            "why_not_higher": list(ranked.why_not_higher),
            "safety_margin": record.ranking_input.safety_margin,
            "mission_margin_m": record.ranking_input.mission_margin_m,
            "failed_gate_count": ranked.failed_gate_count,
            "combined_feasibility_margin": ranked.combined_feasibility_margin,
            "safety_feasible": ranked.safety_feasible,
            "fully_feasible": ranked.fully_feasible,
            "assembly_penalty": record.ranking_input.assembly_penalty,
            "ranking_basis": "feasibility_first_contract_aligned_v2",
            "selection_scope": "ranked_sampled_pool",
        }
        spanwise_requirement_summary = _summarize_spanwise_requirements(
            record.zone_requirements,
            record.mission_summary,
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
            concept=record.concept,
            stations=record.stations,
            zone_requirements=record.zone_requirements,
            airfoil_templates=record.airfoil_templates,
            worker_results=record.worker_results,
            screening_worker_results=record.screening_worker_results,
            worker_backend=record.worker_backend,
            concept_index=concept_index,
            enumeration_index=record.enumeration_index,
            airfoil_feedback=record.airfoil_feedback,
            screening_airfoil_feedback=record.screening_airfoil_feedback,
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

        summary_record = _build_ranked_concept_record(
            cfg=cfg,
            record=record,
            ranked=ranked,
            rank=concept_index,
            overall_rank=overall_rank_by_id[ranked.concept_id],
            bundle_dir=bundle_dir,
        )
        summary_record["concept_id"] = concept_summary["concept_id"]
        summary_records.append(summary_record)

    for infeasible_index, ranked in enumerate(best_infeasible_ranked, start=1):
        record = evaluated_by_id[ranked.concept_id]
        spanwise_requirement_summary = _summarize_spanwise_requirements(
            record.zone_requirements,
            record.mission_summary,
        )
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
                screening_worker_results=record.screening_worker_results,
                worker_backend=record.worker_backend,
                concept_index=infeasible_index,
                enumeration_index=record.enumeration_index,
                airfoil_feedback=record.airfoil_feedback,
                screening_airfoil_feedback=record.screening_airfoil_feedback,
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
                    "mission_margin_m": record.ranking_input.mission_margin_m,
                    "failed_gate_count": ranked.failed_gate_count,
                    "combined_feasibility_margin": ranked.combined_feasibility_margin,
                    "safety_feasible": ranked.safety_feasible,
                    "fully_feasible": ranked.fully_feasible,
                    "assembly_penalty": record.ranking_input.assembly_penalty,
                    "ranking_basis": "feasibility_first_contract_aligned_v2",
                    "selection_scope": "ranked_sampled_pool",
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
        best_infeasible_record = _build_ranked_concept_record(
            cfg=cfg,
            record=record,
            ranked=ranked,
            rank=infeasible_index,
            overall_rank=overall_rank_by_id[ranked.concept_id],
            bundle_dir=bundle_dir,
        )
        best_infeasible_record["concept_id"] = f"infeasible-{record.enumeration_index:02d}"
        best_infeasible_records.append(best_infeasible_record)

    geometry_sampling_summary = {
        "sampling_mode": (
            None
            if geometry_diagnostics is None
            else str(geometry_diagnostics.sampling_mode)
        ),
        "requested_sample_count": (
            len(all_concepts)
            if geometry_diagnostics is None
            else int(geometry_diagnostics.requested_sample_count)
        ),
        "accepted_concept_count": (
            len(all_concepts)
            if geometry_diagnostics is None
            else int(geometry_diagnostics.accepted_concept_count)
        ),
        "rejected_concept_count": (
            0
            if geometry_diagnostics is None
            else int(geometry_diagnostics.rejected_concept_count)
        ),
        "rejection_reason_counts": (
            {}
            if geometry_diagnostics is None
            else dict(geometry_diagnostics.rejection_reason_counts)
        ),
        "design_gross_mass_kg": (
            float(cfg.mass.design_gross_mass_kg)
            if geometry_diagnostics is None
            else float(geometry_diagnostics.design_gross_mass_kg)
        ),
        "wing_area_is_derived": True,
    }

    artifact_trust = _run_artifact_trust(
        cfg=cfg,
        config_path=config_path,
        worker_backend=worker_backend,
        summary_worker_statuses=summary_worker_statuses,
        evaluated_concepts=evaluated_concepts,
    )

    ranked_pool_json_path = output_dir / "concept_ranked_pool.json"
    ranked_pool_json_path.write_text(
        json.dumps(
            {
                "config_path": str(Path(config_path)),
                "artifact_trust": artifact_trust,
                "ranked_pool": ranked_pool_records,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    frontier_summary_json_path = output_dir / "frontier_summary.json"
    frontier_summary = build_frontier_summary(ranked_pool_records)
    frontier_summary["artifact_trust"] = artifact_trust
    frontier_summary_json_path.write_text(
        json.dumps(
            frontier_summary,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cache_statistics = _collect_worker_cache_statistics(worker)
    if cfg.polar_worker.log_cache_statistics and cache_statistics is not None:
        total_queries = cache_statistics["cache_hits"] + cache_statistics["cache_misses"]
        hit_rate = (
            cache_statistics["cache_hits"] / total_queries if total_queries > 0 else 0.0
        )
        print(
            f"[polar_worker] cache hits={cache_statistics['cache_hits']} "
            f"misses={cache_statistics['cache_misses']} "
            f"hit_rate={hit_rate:.3f} "
            f"workers={cfg.polar_worker.persistent_worker_count}"
        )

    summary_json_path = output_dir / "concept_summary.json"
    summary_json_path.write_text(
        json.dumps(
            {
                "config_path": str(Path(config_path)),
                "analysis_artifacts": {
                    "ranked_pool_json_path": str(ranked_pool_json_path),
                    "frontier_summary_json_path": str(frontier_summary_json_path),
                },
                "worker_backend": worker_backend,
                "worker_statuses": summary_worker_statuses,
                "environment_air_properties": air_properties.to_dict(),
                "artifact_trust": artifact_trust,
                "polar_worker": {
                    "persistent_worker_count": int(cfg.polar_worker.persistent_worker_count),
                    "cache_statistics": cache_statistics,
                },
                "evaluation_scope": {
                    "selection_scope": "ranked_sampled_pool",
                    "ranking_basis": "feasibility_first_contract_aligned_v2",
                    "objective_mode": str(cfg.mission.objective_mode),
                    "pilot_mass_cases_kg": [
                        float(value) for value in cfg.mass.pilot_mass_cases_kg
                    ],
                    "aircraft_empty_mass_cases_kg": [
                        float(value) for value in cfg.mass.aircraft_empty_mass_cases_kg
                    ],
                    "gross_mass_sweep_kg": [
                        float(value) for value in cfg.mass.gross_mass_sweep_kg
                    ],
                    "mass_case_policy": (
                        "configured_gross_mass_sweep"
                        if bool(cfg.mass.use_gross_mass_sweep_for_mission_cases)
                        else "area_mass_closure_design_mass_when_available"
                    ),
                    "enumerated_concept_count": len(all_concepts),
                    "evaluated_concept_count": len(evaluated_concepts),
                    "selected_concept_count": len(summary_records),
                    "best_infeasible_count": len(best_infeasible_records),
                    "geometry_primary_variables": [
                        "span_m",
                        (
                            "mean_chord_m"
                            if str(cfg.geometry_family.planform_parameterization)
                            == "mean_chord"
                            else "wing_loading_target_Npm2"
                        ),
                        "taper_ratio",
                        "twist_mid_deg",
                        "twist_outer_deg",
                        "tip_twist_deg",
                        "spanload_bias",
                    ],
                    "geometry_sampling": geometry_sampling_summary,
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
