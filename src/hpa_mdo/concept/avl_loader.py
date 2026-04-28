from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Sequence

import numpy as np

from hpa_mdo.aero.avl_exporter import stage_avl_airfoil_files
from hpa_mdo.aero.avl_spanwise import build_spanwise_load_from_avl_strip_forces
from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.concept.aero_proxies import misc_cd_proxy, oswald_efficiency_proxy
from hpa_mdo.concept.config import BirdmanConceptConfig
from hpa_mdo.concept.geometry import GeometryConcept, WingStation, build_linear_wing_stations
from hpa_mdo.concept.mission_drag import compute_rigging_drag_cda_m2
from hpa_mdo.concept.propulsion import SimplifiedPropModel
from hpa_mdo.concept.safety import evaluate_local_stall
from hpa_mdo.concept.stall_model import apply_safe_local_clmax_model
from hpa_mdo.concept.zone_requirements import build_zone_requirements, default_zone_definitions
from hpa_mdo.mission.objective import (
    MissionEvaluationInputs,
    build_rider_power_curve,
    evaluate_mission_objective,
)

_FLOAT_TOKEN = r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[Ee][-+]?\d+)?"
_ROOT_SEED_AIRFOIL = "fx76mp140"
_TIP_SEED_AIRFOIL = "clarkysm"


def _air_density_from_environment(cfg: BirdmanConceptConfig) -> float:
    temp_c = float(cfg.environment.temperature_c)
    temp_k = temp_c + 273.15
    altitude_m = float(cfg.environment.altitude_m)
    relative_humidity = max(0.0, min(1.0, float(cfg.environment.relative_humidity) / 100.0))

    pressure_pa = 101325.0 * (1.0 - 2.25577e-5 * altitude_m) ** 5.25588
    saturation_vapor_pa = 610.94 * math.exp((17.625 * temp_c) / (temp_c + 243.04))
    vapor_pa = relative_humidity * saturation_vapor_pa
    dry_pa = max(0.0, pressure_pa - vapor_pa)
    return dry_pa / (287.058 * temp_k) + vapor_pa / (461.495 * temp_k)


def _speed_sweep_mps(cfg: BirdmanConceptConfig) -> tuple[float, ...]:
    point_count = int(cfg.mission.speed_sweep_points)
    if point_count < 2:
        raise ValueError("mission.speed_sweep_points must be at least 2.")
    min_speed = float(cfg.mission.speed_sweep_min_mps)
    max_speed = float(cfg.mission.speed_sweep_max_mps)
    step = (max_speed - min_speed) / float(point_count - 1)
    return tuple(min_speed + step * index for index in range(point_count))


def _concept_design_gross_mass_kg(
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
) -> float:
    if bool(cfg.mass_closure.enabled) and concept.design_gross_mass_kg is not None:
        return float(concept.design_gross_mass_kg)
    return float(max(cfg.mass.gross_mass_sweep_kg))


def _concept_gross_mass_cases(
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
) -> tuple[float, ...]:
    if bool(cfg.mass_closure.enabled) and concept.design_gross_mass_kg is not None:
        return (float(concept.design_gross_mass_kg),)
    return tuple(float(value) for value in cfg.mass.gross_mass_sweep_kg)


def _oswald_efficiency_proxy(
    concept: GeometryConcept,
    cfg: BirdmanConceptConfig,
) -> float:
    return oswald_efficiency_proxy(
        concept=concept,
        proxy_cfg=cfg.aero_proxies.oswald_efficiency,
    )


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


def _numeric_value(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _station_area_weights(stations: tuple[WingStation, ...]) -> tuple[float, ...]:
    if not stations:
        return ()
    if len(stations) == 1:
        return (1.0,)

    y_positions = [float(station.y_m) for station in stations]
    boundaries = [y_positions[0]]
    boundaries.extend(0.5 * (left + right) for left, right in zip(y_positions[:-1], y_positions[1:]))
    boundaries.append(y_positions[-1])
    strip_widths = [
        max(right - left, 0.0)
        for left, right in zip(boundaries[:-1], boundaries[1:])
    ]
    area_weights = [
        strip_width * max(float(station.chord_m), 1.0e-9)
        for strip_width, station in zip(strip_widths, stations, strict=True)
    ]
    total_area_weight = sum(area_weights)
    if total_area_weight <= 0.0:
        return tuple(1.0 / float(len(stations)) for _ in stations)
    return tuple(weight / total_area_weight for weight in area_weights)


def _coarse_pre_avl_reference_station_points(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    air_density_kg_per_m3: float,
    speed_sweep_mps: tuple[float, ...],
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    stations = build_linear_wing_stations(
        concept,
        stations_per_half=int(cfg.pipeline.stations_per_half),
    )
    if not stations:
        return [], {"reference_speed_filter_model": "pre_avl_local_stall_feasible_speed_proxy_v1"}

    half_span_m = 0.5 * float(concept.span_m)
    reference_speed_mps = max(float(cfg.launch.release_speed_mps), float(min(speed_sweep_mps)))
    reference_gross_mass_kg = _concept_design_gross_mass_kg(cfg, concept)
    dynamic_pressure_pa = 0.5 * float(air_density_kg_per_m3) * reference_speed_mps**2
    wing_cl_required = (reference_gross_mass_kg * 9.80665) / max(
        dynamic_pressure_pa * float(concept.wing_area_m2),
        1.0e-9,
    )
    area_weights = _station_area_weights(stations)
    total_washout_deg = max(float(concept.twist_root_deg) - float(concept.twist_tip_deg), 0.0)
    span_ratio = (
        0.0 if concept.span_m <= 0.0 else float(concept.span_m) / max(float(concept.wing_area_m2), 1.0)
    )
    twist_delta = abs(float(concept.twist_tip_deg) - float(concept.twist_root_deg))

    raw_shape: list[float] = []
    for station in stations:
        eta = 0.0 if half_span_m <= 0.0 else min(max(float(station.y_m) / half_span_m, 0.0), 1.0)
        elliptic_loading = math.sqrt(max(1.0 - eta**2, 1.0e-9))
        chord_ratio = float(station.chord_m) / max(float(concept.root_chord_m), 1.0e-9)
        local_washout_deg = max(float(concept.twist_root_deg) - float(station.twist_deg), 0.0)
        washout_relief_factor = 1.0 - 0.10 * (
            0.0
            if total_washout_deg <= 0.0
            else min(local_washout_deg / total_washout_deg, 1.0)
        )
        raw_shape.append(
            max(
                0.35,
                (elliptic_loading / max(chord_ratio, 1.0e-6)) * washout_relief_factor,
            )
        )

    normalized_denominator = sum(
        shape * weight for shape, weight in zip(raw_shape, area_weights, strict=True)
    )
    normalized_denominator = max(normalized_denominator, 1.0e-9)

    coarse_points: list[dict[str, float]] = []
    for station, area_weight, shape in zip(stations, area_weights, raw_shape, strict=True):
        eta = 0.0 if half_span_m <= 0.0 else min(max(float(station.y_m) / half_span_m, 0.0), 1.0)
        cl_target = float(wing_cl_required) * (shape / normalized_denominator)
        cl_headroom = (
            0.24
            - 0.09 * eta
            - 0.015 * (twist_delta / 5.0)
            + 0.01 * min(span_ratio, 1.2)
        )
        cl_headroom = min(max(cl_headroom, 0.08), 0.30)
        coarse_points.append(
            {
                "station_y_m": float(station.y_m),
                "chord_m": float(station.chord_m),
                "weight": float(area_weight),
                "cl_target": float(cl_target),
                "cm_target": -0.10 + 0.01 * (1.0 - eta),
                "span_fraction": float(eta),
                "taper_ratio": float(concept.taper_ratio),
                "washout_deg": float(total_washout_deg),
                "reference_speed_mps": float(reference_speed_mps),
                "reference_gross_mass_kg": float(reference_gross_mass_kg),
                "cl_max_proxy": float(cl_target + cl_headroom),
                "cl_max_effective": float(cl_target + cl_headroom),
                "cl_max_effective_source": "geometry_proxy",
                "cm_effective": -0.10 + 0.01 * (1.0 - eta),
                "cm_effective_source": "zone_target_proxy",
            }
        )

    safe_points, safe_summary = apply_safe_local_clmax_model(
        coarse_points,
        safe_scale=float(cfg.stall_model.safe_clmax_scale),
        safe_delta=float(cfg.stall_model.safe_clmax_delta),
        tip_3d_penalty_start_eta=float(cfg.stall_model.tip_3d_penalty_start_eta),
        tip_3d_penalty_max=float(cfg.stall_model.tip_3d_penalty_max),
        tip_taper_penalty_weight=float(cfg.stall_model.tip_taper_penalty_weight),
        washout_relief_deg=float(cfg.stall_model.washout_relief_deg),
        washout_relief_max=float(cfg.stall_model.washout_relief_max),
    )
    return safe_points, {
        **safe_summary,
        "reference_speed_filter_model": "pre_avl_local_stall_feasible_speed_proxy_v1",
        "reference_speed_mps": float(reference_speed_mps),
        "reference_gross_mass_kg": float(reference_gross_mass_kg),
        "section_cl_distribution_model": "elliptic_over_local_chord_with_washout_relief",
    }


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
                float(evaluation_gross_mass_kg) / float(reference_gross_mass_kg)
            ) * (float(reference_speed_mps) / float(evaluation_speed_mps)) ** 2
        cl_scale_factors.append(cl_scale)
        scaled_station_points.append(
            {
                **point,
                "cl_target": float(point["cl_target"]) * cl_scale,
                scale_field_name: cl_scale,
            }
        )
    return scaled_station_points, cl_scale_factors


def _mission_speed_feasibility_records_for_avl(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    reference_station_points: list[dict[str, float]],
    gross_mass_kg: float,
    speed_sweep_mps: tuple[float, ...],
) -> list[dict[str, Any]]:
    if not reference_station_points:
        return []

    records: list[dict[str, Any]] = []
    for speed_mps in speed_sweep_mps:
        scaled_station_points, cl_scale_factors = _scale_station_points_to_condition(
            station_points=reference_station_points,
            evaluation_speed_mps=float(speed_mps),
            evaluation_gross_mass_kg=float(gross_mass_kg),
            scale_field_name="pre_avl_reference_case_cl_scale_factor",
        )
        result = evaluate_local_stall(
            station_points=scaled_station_points,
            half_span_m=0.5 * float(concept.span_m),
            stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
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


def _select_reference_speed_for_mass_case(
    *,
    objective_mode: str,
    selected_mass_case: dict[str, Any],
) -> tuple[float, str]:
    if objective_mode == "max_range":
        feasible_speed_mps = _numeric_value(selected_mass_case.get("best_range_feasible_speed_mps"))
        if feasible_speed_mps is not None:
            return float(feasible_speed_mps), "best_range_feasible_speed_mps"
        estimated_speed_mps = _numeric_value(
            selected_mass_case.get("estimated_first_feasible_speed_mps")
        )
        if estimated_speed_mps is not None:
            return float(estimated_speed_mps), "estimated_first_feasible_speed_mps"
        return float(selected_mass_case["best_range_speed_mps"]), "best_range_speed_mps_unconstrained_fallback"

    feasible_speed_mps = _numeric_value(selected_mass_case.get("min_power_feasible_speed_mps"))
    if feasible_speed_mps is not None:
        return float(feasible_speed_mps), "min_power_feasible_speed_mps"
    estimated_speed_mps = _numeric_value(selected_mass_case.get("estimated_first_feasible_speed_mps"))
    if estimated_speed_mps is not None:
        return float(estimated_speed_mps), "estimated_first_feasible_speed_mps"
    return float(selected_mass_case["min_power_speed_mps"]), "min_power_speed_mps_unconstrained_fallback"


def _mission_mass_cases_for_avl(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    air_density_kg_per_m3: float,
    profile_cd_proxy: float = 0.020,
) -> list[dict[str, Any]]:
    speed_sweep_mps = _speed_sweep_mps(cfg)
    aspect_ratio = float(concept.span_m**2 / max(concept.wing_area_m2, 1.0e-9))
    oswald_efficiency = _oswald_efficiency_proxy(concept, cfg)
    tail_area_ratio = float(concept.tail_area_m2 / max(concept.wing_area_m2, 1.0e-9))
    misc_cd = float(
        misc_cd_proxy(
            profile_cd=profile_cd_proxy,
            tail_area_ratio=tail_area_ratio,
            proxy_cfg=cfg.aero_proxies.parasite_drag,
        )
    )
    rigging_cda_m2 = compute_rigging_drag_cda_m2(cfg.rigging_drag)
    rigging_cd = rigging_cda_m2 / max(concept.wing_area_m2, 1.0e-9)
    prop_model = SimplifiedPropModel.from_config(
        diameter_m=float(cfg.prop.diameter_m),
        rpm_min=float(cfg.prop.rpm_min),
        rpm_max=float(cfg.prop.rpm_max),
        efficiency_cfg=cfg.prop.efficiency_model,
    )
    rider_curve = build_rider_power_curve(
        rider_model=str(cfg.mission.rider_model),
        anchor_power_w=float(cfg.mission.anchor_power_w),
        anchor_duration_min=float(cfg.mission.anchor_duration_min),
        rider_power_curve_csv=cfg.mission.rider_power_curve_csv,
        duration_column=str(cfg.mission.rider_power_curve_duration_column),
        power_column=str(cfg.mission.rider_power_curve_power_column),
    )
    reference_station_points, reference_speed_filter_summary = _coarse_pre_avl_reference_station_points(
        cfg=cfg,
        concept=concept,
        air_density_kg_per_m3=air_density_kg_per_m3,
        speed_sweep_mps=speed_sweep_mps,
    )

    mass_cases: list[dict[str, Any]] = []
    for gross_mass_kg in _concept_gross_mass_cases(cfg, concept):
        weight_n = float(gross_mass_kg) * 9.80665
        power_required_w: list[float] = []
        for speed_mps in speed_sweep_mps:
            dynamic_pressure_pa = 0.5 * air_density_kg_per_m3 * speed_mps**2
            cl_required = weight_n / max(dynamic_pressure_pa * concept.wing_area_m2, 1.0e-9)
            induced_cd = cl_required**2 / max(math.pi * aspect_ratio * oswald_efficiency, 1.0e-9)
            total_cd = float(profile_cd_proxy) + induced_cd + misc_cd + rigging_cd
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
        speed_feasibility_records = _mission_speed_feasibility_records_for_avl(
            cfg=cfg,
            concept=concept,
            reference_station_points=reference_station_points,
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
                - float(mission_result.best_range_speed_mps),
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
        mass_cases.append(
            {
                "gross_mass_kg": float(gross_mass_kg),
                "best_range_m": float(mission_result.best_range_m),
                "best_range_speed_mps": float(mission_result.best_range_speed_mps),
                "best_range_feasible_m": (
                    None if feasible_result is None else float(feasible_result.best_range_m)
                ),
                "best_range_feasible_speed_mps": (
                    None
                    if feasible_result is None
                    else float(feasible_result.best_range_speed_mps)
                ),
                "best_power_margin_w": float(mission_result.best_power_margin_w),
                "best_power_margin_speed_mps": float(
                    mission_result.best_power_margin_speed_mps
                ),
                "power_margin_w_by_speed": tuple(mission_result.power_margin_w_by_speed),
                "required_duration_min_by_speed": tuple(
                    mission_result.required_duration_min_by_speed
                ),
                "available_power_w_by_speed": tuple(
                    mission_result.available_power_w_by_speed
                ),
                "best_power_margin_feasible_w": (
                    None if feasible_result is None else float(feasible_result.best_power_margin_w)
                ),
                "best_power_margin_feasible_speed_mps": (
                    None
                    if feasible_result is None
                    else float(feasible_result.best_power_margin_speed_mps)
                ),
                "min_power_w": float(mission_result.min_power_w),
                "min_power_speed_mps": float(mission_result.min_power_speed_mps),
                "min_power_feasible_w": (
                    None if feasible_result is None else float(feasible_result.min_power_w)
                ),
                "min_power_feasible_speed_mps": (
                    None
                    if feasible_result is None
                    else float(feasible_result.min_power_speed_mps)
                ),
                "mission_feasible": bool(mission_result.mission_feasible),
                "target_range_passed": bool(mission_result.target_range_passed),
                "mission_score": float(mission_result.mission_score),
                "feasible_speed_set_mps": tuple(feasible_speed_set_mps),
                "first_feasible_speed_mps": first_feasible_speed_mps,
                "estimated_first_feasible_speed_mps": estimated_first_feasible_speed_mps,
                "delta_v_to_first_feasible_mps": delta_v_to_first_feasible_mps,
                "speed_feasibility_records": speed_feasibility_records,
                "reference_speed_filter_model": str(
                    reference_speed_filter_summary["reference_speed_filter_model"]
                ),
                "reference_speed_filter_summary": dict(reference_speed_filter_summary),
            }
        )

    return mass_cases


def select_avl_design_cases(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    air_density_kg_per_m3: float,
    profile_cd_proxy: float = 0.020,
) -> dict[str, Any]:
    reference_case_weight = 0.35
    slow_case_weight = 1.75
    launch_case_weight = 2.00
    turn_case_weight = 2.25
    mass_cases = _mission_mass_cases_for_avl(
        cfg=cfg,
        concept=concept,
        air_density_kg_per_m3=air_density_kg_per_m3,
        profile_cd_proxy=profile_cd_proxy,
    )
    objective_mode = str(cfg.mission.objective_mode)
    if objective_mode == "max_range":
        selected_mass_case = min(
            mass_cases,
            key=lambda case: (
                float(_numeric_value(case.get("best_range_feasible_m")) or 0.0),
                -float(case["gross_mass_kg"]),
            ),
        )
        mass_selection_reason = "min_best_range_feasible_m"
    elif objective_mode == "min_power":
        selected_mass_case = max(
            mass_cases,
            key=lambda case: (
                _numeric_value(case.get("min_power_feasible_w")) is not None,
                float(_numeric_value(case.get("min_power_feasible_w")) or -1.0),
                float(case["gross_mass_kg"]),
            ),
        )
        mass_selection_reason = "max_min_power_feasible_w"
    else:
        raise ValueError(f"Unsupported mission objective mode: {objective_mode}")
    reference_speed_mps, reference_speed_reason = _select_reference_speed_for_mass_case(
        objective_mode=objective_mode,
        selected_mass_case=selected_mass_case,
    )

    max_gross_mass_kg = _concept_design_gross_mass_kg(cfg, concept)
    slow_report_speeds_mps = tuple(cfg.mission.slow_report_speeds_mps)
    if slow_report_speeds_mps:
        slow_case_speed_mps = float(min(slow_report_speeds_mps))
        slow_case_speed_reason = "slow_report_speeds_mps_min"
    else:
        slow_case_speed_mps = float(min(_speed_sweep_mps(cfg)))
        slow_case_speed_reason = "speed_sweep_min_mps"
    launch_speed_mps = float(cfg.launch.release_speed_mps)
    turn_load_factor = 1.0 / math.cos(math.radians(float(cfg.turn.required_bank_angle_deg)))
    design_cases = [
        {
            "case_label": "reference_avl_case",
            "evaluation_speed_mps": float(reference_speed_mps),
            "evaluation_gross_mass_kg": float(selected_mass_case["gross_mass_kg"]),
            "load_factor": 1.0,
            "case_weight": reference_case_weight,
            "speed_reason": reference_speed_reason,
            "mass_reason": mass_selection_reason,
            "case_reason": "secondary_cruise_objective_case",
        },
        {
            "case_label": "slow_avl_case",
            "evaluation_speed_mps": float(slow_case_speed_mps),
            "evaluation_gross_mass_kg": float(max_gross_mass_kg),
            "load_factor": 1.0,
            "case_weight": slow_case_weight,
            "speed_reason": slow_case_speed_reason,
            "mass_reason": "max_gross_mass",
            "case_reason": "primary_low_speed_heavy_mass_case",
        },
        {
            "case_label": "launch_release_case",
            "evaluation_speed_mps": float(launch_speed_mps),
            "evaluation_gross_mass_kg": float(max_gross_mass_kg),
            "load_factor": 1.0,
            "case_weight": launch_case_weight,
            "speed_reason": "launch.release_speed_mps",
            "mass_reason": "max_gross_mass",
            "case_reason": "primary_launch_release_heavy_mass_case",
        },
        {
            "case_label": "turn_avl_case",
            "evaluation_speed_mps": float(launch_speed_mps),
            "evaluation_gross_mass_kg": float(max_gross_mass_kg),
            "load_factor": float(turn_load_factor),
            "case_weight": turn_case_weight,
            "speed_reason": "launch.release_speed_mps",
            "mass_reason": "max_gross_mass",
            "case_reason": "primary_banked_turn_heavy_mass_case",
        },
    ]
    return {
        "objective_mode": objective_mode,
        "reference_speed_mps": float(reference_speed_mps),
        "reference_gross_mass_kg": float(selected_mass_case["gross_mass_kg"]),
        "reference_speed_reason": reference_speed_reason,
        "mass_selection_reason": mass_selection_reason,
        "reference_condition_policy": "low_speed_primary_multipoint_design_cases_v4_feasible_reference_proxy",
        "primary_case_labels": [
            "slow_avl_case",
            "launch_release_case",
            "turn_avl_case",
        ],
        "secondary_case_labels": ["reference_avl_case"],
        "selected_mass_case": selected_mass_case,
        "mass_cases": mass_cases,
        "design_cases": design_cases,
    }


def select_avl_reference_condition(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    air_density_kg_per_m3: float,
    profile_cd_proxy: float = 0.020,
) -> dict[str, Any]:
    return select_avl_design_cases(
        cfg=cfg,
        concept=concept,
        air_density_kg_per_m3=air_density_kg_per_m3,
        profile_cd_proxy=profile_cd_proxy,
    )


def _concept_case_slug(concept: GeometryConcept) -> str:
    payload = {
        "span_m": concept.span_m,
        "wing_area_m2": concept.wing_area_m2,
        "wing_loading_target_Npm2": concept.wing_loading_target_Npm2,
        "wing_area_source": concept.wing_area_source,
        "root_chord_m": concept.root_chord_m,
        "tip_chord_m": concept.tip_chord_m,
        "mean_aerodynamic_chord_m": concept.mean_aerodynamic_chord_m,
        "twist_root_deg": concept.twist_root_deg,
        "twist_tip_deg": concept.twist_tip_deg,
        "dihedral_root_deg": concept.dihedral_root_deg,
        "dihedral_tip_deg": concept.dihedral_tip_deg,
        "dihedral_exponent": concept.dihedral_exponent,
        "tail_area_m2": concept.tail_area_m2,
        "cg_xc": concept.cg_xc,
        "design_gross_mass_kg": concept.design_gross_mass_kg,
        "segment_lengths_m": list(concept.segment_lengths_m),
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"concept_{digest}"


def _station_z_positions(stations: tuple[WingStation, ...]) -> tuple[float, ...]:
    if not stations:
        return ()
    z_positions = [0.0]
    for left, right in zip(stations[:-1], stations[1:]):
        dy_m = float(right.y_m) - float(left.y_m)
        mean_dihedral_rad = math.radians(0.5 * (float(left.dihedral_deg) + float(right.dihedral_deg)))
        z_positions.append(z_positions[-1] + dy_m * math.tan(mean_dihedral_rad))
    return tuple(z_positions)


def _station_airfoil_name(station: WingStation, half_span_m: float) -> str:
    eta = 0.0 if half_span_m <= 0.0 else float(station.y_m) / half_span_m
    return _ROOT_SEED_AIRFOIL if eta <= 0.55 else _TIP_SEED_AIRFOIL


def _zone_name_for_span_fraction(span_fraction: float) -> str:
    clamped_fraction = min(max(float(span_fraction), 0.0), 1.0)
    zone_definitions = default_zone_definitions()
    for zone_index, zone in enumerate(zone_definitions):
        is_last_zone = zone_index == len(zone_definitions) - 1
        in_zone = zone.y0_frac <= clamped_fraction < zone.y1_frac
        if is_last_zone and clamped_fraction <= zone.y1_frac:
            in_zone = zone.y0_frac <= clamped_fraction <= zone.y1_frac
        if in_zone:
            return str(zone.name)
    return str(zone_definitions[-1].name)


def _station_airfoil_target(
    *,
    station: WingStation,
    half_span_m: float,
    zone_airfoil_paths: dict[str, str] | None,
) -> str:
    if zone_airfoil_paths:
        eta = 0.0 if half_span_m <= 0.0 else float(station.y_m) / half_span_m
        zone_name = _zone_name_for_span_fraction(eta)
        zone_airfoil_path = zone_airfoil_paths.get(zone_name)
        if zone_airfoil_path is not None:
            return str(zone_airfoil_path)
    return _station_airfoil_name(station, half_span_m)


def write_concept_wing_only_avl(
    *,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    output_path: Path,
    zone_airfoil_paths: dict[str, Path | str] | None = None,
) -> Path:
    if not stations:
        raise ValueError("stations must not be empty.")

    z_positions = _station_z_positions(stations)
    half_span_m = 0.5 * float(concept.span_m)
    c_ref_m = float(concept.mean_aerodynamic_chord_m)
    # AVL needs appreciably more spanwise vortices than section breaks once
    # multiple section airfoils are present, otherwise it aborts before trim
    # with "Insufficient number of spanwise vortices to work with."
    span_panels = max(24, 4 * max(len(stations) - 1, 1))

    lines = [
        "Birdman concept wing-only AVL",
        "#Mach",
        "0.000000",
        "#IYsym  iZsym  Zsym",
        "1  0  0.000000",
        "#Sref  Cref  Bref",
        f"{float(concept.wing_area_m2):.9f}  {c_ref_m:.9f}  {float(concept.span_m):.9f}",
        "#Xref  Yref  Zref",
        f"{0.25 * c_ref_m:.9f}  0.000000000  0.000000000",
        "#CDp",
        "0.000000",
        "#",
        "SURFACE",
        "Wing",
        f"16  1.0  {span_panels}  1.0",
        "#",
    ]
    resolved_zone_airfoil_paths = (
        None
        if zone_airfoil_paths is None
        else {
            str(zone_name): str(Path(airfoil_path).expanduser().resolve())
            for zone_name, airfoil_path in zone_airfoil_paths.items()
        }
    )
    for station, z_le_m in zip(stations, z_positions):
        lines.extend(
            [
                "SECTION",
                (
                    f"0.000000000  {float(station.y_m):.9f}  {float(z_le_m):.9f}  "
                    f"{float(station.chord_m):.9f}  {float(station.twist_deg):.9f}"
                ),
                "AFILE",
                _station_airfoil_target(
                    station=station,
                    half_span_m=half_span_m,
                    zone_airfoil_paths=resolved_zone_airfoil_paths,
                ),
                "#",
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _parse_avl_scalar(text: str, label: str) -> float | None:
    pattern = re.compile(
        rf"\b{re.escape(label)}\s*=\s*(?P<value>{_FLOAT_TOKEN}|\*{{3,}})",
    )
    match = pattern.search(text)
    if match is None:
        return None
    value_text = match.group("value")
    if "*" in value_text:
        return None
    return float(value_text)


def _parse_avl_force_totals(path: Path) -> dict[str, float] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    alpha_deg = _parse_avl_scalar(text, "Alpha")
    cl_trim = _parse_avl_scalar(text, "CLtot")
    if alpha_deg is None and cl_trim is None:
        return None
    payload: dict[str, float] = {}
    if alpha_deg is not None:
        payload["aoa_trim_deg"] = float(alpha_deg)
    if cl_trim is not None:
        payload["cl_trim"] = float(cl_trim)
    return payload


def _resolve_avl_binary(avl_binary: str | Path | None) -> Path:
    if avl_binary is not None:
        as_path = Path(avl_binary).expanduser()
        if as_path.is_absolute() and as_path.exists():
            return as_path.resolve()
        which_hit = shutil.which(str(as_path))
        if which_hit:
            return Path(which_hit)
    which_hit = shutil.which("avl")
    if which_hit is None:
        raise FileNotFoundError("AVL binary not found on PATH.")
    return Path(which_hit)


def _stage_avl_case(avl_path: Path, case_dir: Path) -> Path:
    case_dir.mkdir(parents=True, exist_ok=True)
    staged_avl = case_dir / avl_path.name
    if staged_avl.resolve() != avl_path.resolve():
        staged_avl.write_bytes(avl_path.read_bytes())
    stage_avl_airfoil_files(staged_avl)
    return staged_avl


def _run_avl_trim_case(
    *,
    avl_path: Path,
    case_dir: Path,
    cl_required: float,
    velocity_mps: float,
    density_kgpm3: float,
    avl_binary: str | Path | None = None,
) -> dict[str, float]:
    avl_bin = _resolve_avl_binary(avl_binary)
    staged_avl = _stage_avl_case(avl_path, case_dir)
    trim_file = case_dir / "concept_trim.ft"
    stdout_log = case_dir / "concept_trim_stdout.log"
    if trim_file.exists():
        trim_file.unlink()
    command_text = "\n".join(
        [
            "plop",
            "g",
            "",
            f"load {staged_avl.name}",
            "oper",
            "m",
            f"v {float(velocity_mps):.9f}",
            f"d {float(density_kgpm3):.9f}",
            "",
            "c1",
            f"c {float(cl_required):.9f}",
            "",
            "x",
            "ft",
            trim_file.name,
            "",
            "",
            "quit",
            "",
        ]
    )
    proc = subprocess.run(
        [str(avl_bin)],
        input=command_text,
        text=True,
        capture_output=True,
        cwd=case_dir,
        check=False,
    )
    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(f"AVL trim run failed with return code {proc.returncode}.")
    if "Cannot trim." in stdout_text:
        raise RuntimeError("AVL trim did not converge for the requested CL.")

    parsed = _parse_avl_force_totals(trim_file)
    if parsed is None or "aoa_trim_deg" not in parsed or "cl_trim" not in parsed:
        raise RuntimeError("AVL trim output missing Alpha/CLtot.")
    return parsed


def _run_avl_spanwise_case(
    *,
    avl_path: Path,
    case_dir: Path,
    alpha_deg: float,
    velocity_mps: float,
    density_kgpm3: float,
    avl_binary: str | Path | None = None,
) -> Path:
    avl_bin = _resolve_avl_binary(avl_binary)
    staged_avl = _stage_avl_case(avl_path, case_dir)
    fs_path = case_dir / "concept_spanwise.fs"
    stdout_log = case_dir / "concept_spanwise_stdout.log"
    if fs_path.exists():
        fs_path.unlink()
    command_text = "\n".join(
        [
            "plop",
            "g",
            "",
            f"load {staged_avl.name}",
            "oper",
            "m",
            f"v {float(velocity_mps):.9f}",
            f"d {float(density_kgpm3):.9f}",
            "",
            "a",
            "a",
            f"{float(alpha_deg):.9f}",
            "x",
            "fs",
            fs_path.name,
            "",
            "",
            "quit",
            "",
        ]
    )
    proc = subprocess.run(
        [str(avl_bin)],
        input=command_text,
        text=True,
        capture_output=True,
        cwd=case_dir,
        check=False,
    )
    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"AVL spanwise run failed with return code {proc.returncode}.")
    if not fs_path.exists():
        raise RuntimeError("AVL spanwise run did not emit an .fs file.")
    return fs_path


def resample_spanwise_load_to_stations(
    *,
    spanwise_load: SpanwiseLoad,
    stations: tuple[WingStation, ...],
) -> SpanwiseLoad:
    if not stations:
        raise ValueError("stations must not be empty.")
    station_y = np.asarray([float(station.y_m) for station in stations], dtype=float)
    if station_y[0] < float(np.min(spanwise_load.y)) - 1.0e-6:
        raise ValueError("station root lies outside spanwise load coverage.")
    if station_y[-1] > float(np.max(spanwise_load.y)) + 1.0e-6:
        raise ValueError("station tip lies outside spanwise load coverage.")

    def interp(values: np.ndarray) -> np.ndarray:
        return np.interp(station_y, np.asarray(spanwise_load.y, dtype=float), values)

    return SpanwiseLoad(
        y=station_y,
        chord=interp(np.asarray(spanwise_load.chord, dtype=float)),
        cl=interp(np.asarray(spanwise_load.cl, dtype=float)),
        cd=interp(np.asarray(spanwise_load.cd, dtype=float)),
        cm=interp(np.asarray(spanwise_load.cm, dtype=float)),
        lift_per_span=interp(np.asarray(spanwise_load.lift_per_span, dtype=float)),
        drag_per_span=interp(np.asarray(spanwise_load.drag_per_span, dtype=float)),
        aoa_deg=float(spanwise_load.aoa_deg),
        velocity=float(spanwise_load.velocity),
        dynamic_pressure=float(spanwise_load.dynamic_pressure),
    )


def _station_span_fractions(stations: tuple[WingStation, ...]) -> tuple[float, ...]:
    if not stations:
        raise ValueError("stations must not be empty.")
    start_y_m = float(stations[0].y_m)
    end_y_m = float(stations[-1].y_m)
    half_span_m = end_y_m - start_y_m
    if half_span_m <= 0.0:
        raise ValueError("stations must span a positive half-span.")
    return tuple((float(station.y_m) - start_y_m) / half_span_m for station in stations)


def _zone_station_positions(
    *,
    stations: tuple[WingStation, ...],
    zone_names: Sequence[str],
) -> dict[str, list[float]]:
    zone_definitions = default_zone_definitions()
    span_fractions = _station_span_fractions(stations)
    zone_positions = {zone.name: [] for zone in zone_definitions}

    for station, span_frac in zip(stations, span_fractions):
        for zone_index, zone in enumerate(zone_definitions):
            is_last_zone = zone_index == len(zone_definitions) - 1
            in_zone = zone.y0_frac <= span_frac < zone.y1_frac
            if is_last_zone and span_frac <= zone.y1_frac:
                in_zone = zone.y0_frac <= span_frac <= zone.y1_frac
            if in_zone:
                zone_positions[zone.name].append(float(station.y_m))
                break

    missing = set(zone_names) - set(zone_positions)
    if missing:
        raise ValueError(f"Unknown zone names in payload conversion: {sorted(missing)}")
    return zone_positions


def avl_zone_payload_from_spanwise_load(
    *,
    spanwise_load: SpanwiseLoad,
    stations: tuple[WingStation, ...],
    case_label: str = "reference_avl_case",
    case_weight: float = 1.0,
    evaluation_speed_mps: float | None = None,
    evaluation_gross_mass_kg: float | None = None,
    load_factor: float = 1.0,
    case_reason: str | None = None,
) -> dict[str, dict[str, Any]]:
    zone_requirements = build_zone_requirements(
        spanwise_load=spanwise_load,
        stations=stations,
        zone_definitions=default_zone_definitions(),
    )
    zone_positions = _zone_station_positions(
        stations=stations,
        zone_names=tuple(zone_requirements.keys()),
    )

    payload: dict[str, dict[str, Any]] = {}
    for zone_name, zone_requirement in zone_requirements.items():
        station_positions = zone_positions[zone_name]
        if len(station_positions) != len(zone_requirement.points):
            raise ValueError(
                f"Zone '{zone_name}' has {len(zone_requirement.points)} operating points but "
                f"{len(station_positions)} station positions."
            )
        payload[zone_name] = {
            "source": "avl_strip_forces",
            "min_tc_ratio": float(zone_requirement.min_tc_ratio),
            "design_cases": [
                {
                    "case_label": str(case_label),
                    "evaluation_speed_mps": (
                        None if evaluation_speed_mps is None else float(evaluation_speed_mps)
                    ),
                    "evaluation_gross_mass_kg": (
                        None
                        if evaluation_gross_mass_kg is None
                        else float(evaluation_gross_mass_kg)
                    ),
                    "load_factor": float(load_factor),
                    "case_weight": float(case_weight),
                    "case_reason": None if case_reason is None else str(case_reason),
                }
            ],
            "points": [
                {
                    "reynolds": float(point.reynolds),
                    "chord_m": float(point.chord_m),
                    "cl_target": float(point.cl_target),
                    "cm_target": float(point.cm_target),
                    "weight": float(point.weight) * float(case_weight),
                    "station_y_m": float(station_y_m),
                    "case_label": str(case_label),
                    "case_weight": float(case_weight),
                    "evaluation_speed_mps": (
                        None if evaluation_speed_mps is None else float(evaluation_speed_mps)
                    ),
                    "evaluation_gross_mass_kg": (
                        None
                        if evaluation_gross_mass_kg is None
                        else float(evaluation_gross_mass_kg)
                    ),
                    "load_factor": float(load_factor),
                    "case_reason": None if case_reason is None else str(case_reason),
                }
                for point, station_y_m in zip(
                    zone_requirement.points,
                    station_positions,
                    strict=True,
                )
            ],
        }
    return payload


def load_zone_requirements_from_avl(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    working_root: Path,
    avl_binary: str | Path | None = None,
    airfoil_templates: dict[str, dict[str, Any]] | None = None,
    reference_condition_override: dict[str, Any] | None = None,
    case_tag: str | None = None,
) -> dict[str, dict[str, Any]]:
    if not stations:
        raise ValueError("stations must not be empty.")

    working_root = Path(working_root)
    case_dir = working_root / _concept_case_slug(concept)
    if case_tag is not None:
        case_dir = case_dir / str(case_tag)
    avl_path = case_dir / "concept_wing.avl"
    zone_airfoil_paths = (
        None
        if airfoil_templates is None
        else _write_zone_airfoil_dat_files(
            case_dir=case_dir,
            airfoil_templates=airfoil_templates,
        )
    )
    write_concept_wing_only_avl(
        concept=concept,
        stations=stations,
        output_path=avl_path,
        zone_airfoil_paths=zone_airfoil_paths,
    )

    air_density_kgpm3 = _air_density_from_environment(cfg)
    reference_condition = select_avl_design_cases(
        cfg=cfg,
        concept=concept,
        air_density_kg_per_m3=air_density_kgpm3,
    )
    if reference_condition_override is not None:
        reference_condition = _apply_reference_condition_override(
            reference_condition=reference_condition,
            reference_condition_override=reference_condition_override,
        )
    aggregated_payload: dict[str, dict[str, Any]] = {}
    design_case_summaries: list[dict[str, Any]] = []

    for case_spec in reference_condition["design_cases"]:
        case_label = str(case_spec["case_label"])
        evaluation_speed_mps = float(case_spec["evaluation_speed_mps"])
        evaluation_gross_mass_kg = float(case_spec["evaluation_gross_mass_kg"])
        load_factor = float(case_spec["load_factor"])
        dynamic_pressure_pa = 0.5 * air_density_kgpm3 * evaluation_speed_mps**2
        cl_required = (evaluation_gross_mass_kg * 9.80665 * load_factor) / max(
            dynamic_pressure_pa * float(concept.wing_area_m2),
            1.0e-9,
        )

        case_case_dir = case_dir / case_label
        trim_totals = _run_avl_trim_case(
            avl_path=avl_path,
            case_dir=case_case_dir,
            cl_required=cl_required,
            velocity_mps=evaluation_speed_mps,
            density_kgpm3=air_density_kgpm3,
            avl_binary=avl_binary,
        )
        fs_path = _run_avl_spanwise_case(
            avl_path=avl_path,
            case_dir=case_case_dir,
            alpha_deg=float(trim_totals["aoa_trim_deg"]),
            velocity_mps=evaluation_speed_mps,
            density_kgpm3=air_density_kgpm3,
            avl_binary=avl_binary,
        )

        avl_spanwise_load = build_spanwise_load_from_avl_strip_forces(
            fs_path=fs_path,
            avl_path=avl_path,
            aoa_deg=float(trim_totals["aoa_trim_deg"]),
            velocity_mps=evaluation_speed_mps,
            density_kgpm3=air_density_kgpm3,
            target_surface_names=("Wing",),
            positive_y_only=True,
        )
        station_load = resample_spanwise_load_to_stations(
            spanwise_load=avl_spanwise_load,
            stations=stations,
        )
        case_payload = avl_zone_payload_from_spanwise_load(
            spanwise_load=station_load,
            stations=stations,
            case_label=case_label,
            case_weight=float(case_spec.get("case_weight", 1.0)),
            evaluation_speed_mps=evaluation_speed_mps,
            evaluation_gross_mass_kg=evaluation_gross_mass_kg,
            load_factor=load_factor,
            case_reason=str(case_spec.get("case_reason", case_label)),
        )
        design_case_summaries.append(
            {
                "case_label": case_label,
                "evaluation_speed_mps": evaluation_speed_mps,
                "evaluation_gross_mass_kg": evaluation_gross_mass_kg,
                "load_factor": load_factor,
                "case_weight": float(case_spec.get("case_weight", 1.0)),
                "speed_reason": str(case_spec.get("speed_reason", "unknown")),
                "mass_reason": str(case_spec.get("mass_reason", "unknown")),
                "case_reason": str(case_spec.get("case_reason", case_label)),
                "trim_aoa_deg": float(trim_totals["aoa_trim_deg"]),
                "trim_cl": float(trim_totals["cl_trim"]),
                "cl_required": float(cl_required),
            }
        )
        for zone_name, zone_payload in case_payload.items():
            aggregate = aggregated_payload.setdefault(
                zone_name,
                {
                    "source": "avl_strip_forces",
                    "min_tc_ratio": float(zone_payload["min_tc_ratio"]),
                    "points": [],
                    "design_cases": [],
                },
            )
            aggregate["points"].extend(zone_payload["points"])
            aggregate["design_cases"].extend(zone_payload.get("design_cases", []))

    reference_speed_mps = float(reference_condition["reference_speed_mps"])
    reference_gross_mass_kg = float(reference_condition["reference_gross_mass_kg"])
    selected_mass_case = dict(reference_condition["selected_mass_case"])
    for zone_payload in aggregated_payload.values():
        zone_payload["reference_speed_mps"] = reference_speed_mps
        zone_payload["reference_gross_mass_kg"] = reference_gross_mass_kg
        zone_payload["reference_speed_reason"] = str(reference_condition["reference_speed_reason"])
        zone_payload["mass_selection_reason"] = str(reference_condition["mass_selection_reason"])
        zone_payload["reference_condition_policy"] = str(
            reference_condition["reference_condition_policy"]
        )
        zone_payload["reference_speed_filter_model"] = str(
            selected_mass_case.get("reference_speed_filter_model", "not_available")
        )
        zone_payload["pre_avl_best_range_m"] = _numeric_value(selected_mass_case.get("best_range_m"))
        zone_payload["pre_avl_best_range_feasible_m"] = _numeric_value(
            selected_mass_case.get("best_range_feasible_m")
        )
        zone_payload["pre_avl_best_range_speed_mps"] = _numeric_value(
            selected_mass_case.get("best_range_speed_mps")
        )
        zone_payload["pre_avl_best_range_feasible_speed_mps"] = _numeric_value(
            selected_mass_case.get("best_range_feasible_speed_mps")
        )
        zone_payload["pre_avl_feasible_speed_set_mps"] = list(
            selected_mass_case.get("feasible_speed_set_mps", ())
        )
        if design_case_summaries:
            zone_payload["reference_cl_required"] = float(design_case_summaries[0]["cl_required"])
            zone_payload["trim_aoa_deg"] = float(design_case_summaries[0]["trim_aoa_deg"])
            zone_payload["trim_cl"] = float(design_case_summaries[0]["trim_cl"])
        zone_payload["design_case_count"] = len(zone_payload.get("design_cases", []))
        zone_payload["design_cases"] = design_case_summaries
    return aggregated_payload


def _annotate_fallback_payload(
    zone_payload: dict[str, dict[str, Any]],
    *,
    fallback_reason: str,
) -> dict[str, dict[str, Any]]:
    annotated: dict[str, dict[str, Any]] = {}
    for zone_name, zone_data in zone_payload.items():
        annotated[zone_name] = {
            **zone_data,
            "source": "fallback_coarse_loader",
            "fallback_reason": str(zone_data.get("fallback_reason", fallback_reason)),
            "reference_condition_policy": str(
                zone_data.get("reference_condition_policy", "fallback_coarse_loader")
            ),
        }
    return annotated


def _normalize_airfoil_coordinates(
    coordinates: object,
) -> tuple[tuple[float, float], ...]:
    if not isinstance(coordinates, list | tuple):
        raise ValueError("Airfoil coordinates must be provided as an array of [x, y] pairs.")

    normalized: list[tuple[float, float]] = []
    for point in coordinates:
        if not isinstance(point, list | tuple) or len(point) < 2:
            raise ValueError("Airfoil coordinate entries must be [x, y] pairs.")
        normalized.append((float(point[0]), float(point[1])))

    if len(normalized) < 3:
        raise ValueError("Airfoil coordinates must contain at least three points.")
    return tuple(normalized)


def _write_zone_airfoil_dat_files(
    *,
    case_dir: Path,
    airfoil_templates: dict[str, dict[str, Any]],
) -> dict[str, Path]:
    airfoil_dir = case_dir / "selected_airfoils"
    airfoil_dir.mkdir(parents=True, exist_ok=True)

    written_paths: dict[str, Path] = {}
    for zone_name, template in airfoil_templates.items():
        coordinates = _normalize_airfoil_coordinates(template.get("coordinates"))
        geometry_hash = str(template.get("geometry_hash", zone_name))[:12]
        dat_path = airfoil_dir / f"{zone_name}-{geometry_hash}.dat"
        lines = [str(template.get("template_id", f"{zone_name}-selected"))]
        lines.extend(f"{float(x):.8f} {float(y):.8f}" for x, y in coordinates)
        dat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written_paths[str(zone_name)] = dat_path.resolve()
    return written_paths


def _apply_reference_condition_override(
    *,
    reference_condition: dict[str, Any],
    reference_condition_override: dict[str, Any],
) -> dict[str, Any]:
    if not reference_condition_override:
        return reference_condition

    overridden = {
        **reference_condition,
        "selected_mass_case": dict(reference_condition.get("selected_mass_case", {})),
        "design_cases": [dict(case) for case in reference_condition.get("design_cases", [])],
    }
    reference_speed_mps = float(
        reference_condition_override.get(
            "reference_speed_mps",
            reference_condition["reference_speed_mps"],
        )
    )
    reference_gross_mass_kg = float(
        reference_condition_override.get(
            "reference_gross_mass_kg",
            reference_condition["reference_gross_mass_kg"],
        )
    )
    reference_speed_reason = str(
        reference_condition_override.get(
            "reference_speed_reason",
            reference_condition["reference_speed_reason"],
        )
    )
    mass_selection_reason = str(
        reference_condition_override.get(
            "mass_selection_reason",
            reference_condition["mass_selection_reason"],
        )
    )
    reference_condition_policy = str(
        reference_condition_override.get(
            "reference_condition_policy",
            reference_condition["reference_condition_policy"],
        )
    )

    overridden["reference_speed_mps"] = reference_speed_mps
    overridden["reference_gross_mass_kg"] = reference_gross_mass_kg
    overridden["reference_speed_reason"] = reference_speed_reason
    overridden["mass_selection_reason"] = mass_selection_reason
    overridden["reference_condition_policy"] = reference_condition_policy

    selected_mass_case = overridden["selected_mass_case"]
    selected_mass_case.update(reference_condition_override.get("selected_mass_case", {}))
    selected_mass_case["gross_mass_kg"] = reference_gross_mass_kg

    for case in overridden["design_cases"]:
        if str(case.get("case_label")) != "reference_avl_case":
            continue
        case["evaluation_speed_mps"] = reference_speed_mps
        case["evaluation_gross_mass_kg"] = reference_gross_mass_kg
        case["speed_reason"] = reference_speed_reason
        case["mass_reason"] = mass_selection_reason
        case["case_reason"] = str(
            reference_condition_override.get(
                "case_reason",
                "post_airfoil_finalist_reference_case",
            )
        )
        break

    return overridden


def build_avl_backed_spanwise_loader(
    *,
    cfg: BirdmanConceptConfig,
    working_root: Path,
    fallback_loader: Callable[[GeometryConcept, tuple[WingStation, ...]], dict[str, dict[str, Any]]],
    avl_binary: str | Path | None = None,
) -> Callable[[GeometryConcept, tuple[WingStation, ...]], dict[str, dict[str, Any]]]:
    def _loader(
        concept: GeometryConcept,
        stations: tuple[WingStation, ...],
    ) -> dict[str, dict[str, Any]]:
        try:
            return load_zone_requirements_from_avl(
                cfg=cfg,
                concept=concept,
                stations=stations,
                working_root=working_root,
                avl_binary=avl_binary,
            )
        except Exception as exc:  # pragma: no cover - exercised via fallback behavior
            print(
                (
                    "[birdman-concept] AVL-backed spanwise loader failed; "
                    f"falling back to coarse loader: {exc}"
                ),
                file=sys.stderr,
            )
            return _annotate_fallback_payload(
                fallback_loader(concept, stations),
                fallback_reason=str(exc),
            )

    setattr(
        _loader,
        "_birdman_avl_rerun_context",
        {
            "cfg": cfg,
            "working_root": Path(working_root),
            "avl_binary": avl_binary,
        },
    )
    return _loader
