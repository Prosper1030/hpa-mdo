#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from hpa_mdo.aero.avl_spanwise import build_spanwise_load_from_avl_strip_forces
from hpa_mdo.concept.aero_proxies import misc_cd_proxy
from hpa_mdo.concept.atmosphere import air_properties_from_environment
from hpa_mdo.concept.avl_loader import (
    _run_avl_spanwise_case,
    _run_avl_trim_case,
    avl_zone_payload_from_spanwise_load,
    resample_spanwise_load_to_stations,
    write_concept_wing_only_avl,
)
from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    GeometryRejection,
    WingStation,
    _apply_spanload_bias_washout,
    _fourier_spanload_shape,
    _fourier_spanload_ratio_to_ellipse,
    build_linear_wing_stations,
    build_segment_plan,
    enumerate_geometry_concepts,
    get_last_geometry_enumeration_diagnostics,
)
from hpa_mdo.concept.mission_drag import compute_rigging_drag_cda_m2
from hpa_mdo.concept.pipeline import _sizing_diagnostics


G_MPS2 = 9.80665
CASE_LABEL = "spanload_smoke_reference_cruise"
FIXED_AIRFOIL_PROFILE_CD_PROXY = 0.018
INVERSE_TWIST_ZERO_LIFT_ALPHA_DEG = -3.0
INVERSE_TWIST_LIFT_CURVE_SLOPE_PER_RAD = 2.0 * math.pi
INVERSE_TWIST_MAX_AERO_ETA = 0.97
INVERSE_TWIST_MAX_ABS_TWIST_DEG = 14.0
SPANLOAD_DELTA_SUCCESS_LIMIT = 0.15
AVL_E_CDI_SUCCESS_FLOOR = 0.85


def _round(value: Any, digits: int = 6) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, int | float):
        if not math.isfinite(float(value)):
            return str(value)
        return round(float(value), digits)
    if isinstance(value, dict):
        return {str(key): _round(val, digits) for key, val in value.items()}
    if isinstance(value, list | tuple):
        return [_round(item, digits) for item in value]
    return value


def _air_properties(cfg: BirdmanConceptConfig):
    return air_properties_from_environment(
        temperature_c=float(cfg.environment.temperature_c),
        relative_humidity_percent=float(cfg.environment.relative_humidity),
        altitude_m=float(cfg.environment.altitude_m),
    )


def _design_speed_mps(cfg: BirdmanConceptConfig, requested_speed_mps: float | None) -> float:
    if requested_speed_mps is not None:
        return float(requested_speed_mps)
    spanload_cfg = cfg.geometry_family.spanload_design
    if spanload_cfg.design_speed_mps is not None:
        return float(spanload_cfg.design_speed_mps)
    return 0.5 * (float(cfg.mission.speed_sweep_min_mps) + float(cfg.mission.speed_sweep_max_mps))


def _mission_mass_authority(cfg: BirdmanConceptConfig, concept: GeometryConcept) -> dict[str, Any]:
    sizing = _sizing_diagnostics(cfg, concept)
    closure = sizing.get("area_mass_closure") or {}
    return {
        "primary_design_gross_mass_kg": float(cfg.mass.design_gross_mass_kg),
        "concept_design_gross_mass_kg": (
            None
            if concept.design_gross_mass_kg is None
            else float(concept.design_gross_mass_kg)
        ),
        "pilot_mass_cases_kg": [float(value) for value in cfg.mass.pilot_mass_cases_kg],
        "aircraft_empty_mass_cases_kg": [
            float(value) for value in cfg.mass.aircraft_empty_mass_cases_kg
        ],
        "gross_mass_sweep_kg": [float(value) for value in cfg.mass.gross_mass_sweep_kg],
        "mass_authority": "mass.design_gross_mass_kg",
        "proxy_model": closure.get("model"),
        "proxy_model_authority": closure.get("model_authority"),
        "proxy_estimated_gross_mass_kg": closure.get("estimated_gross_mass_kg"),
        "proxy_estimated_empty_mass_kg": closure.get("estimated_aircraft_empty_mass_kg"),
        "proxy_budget_warning": closure.get("budget_warning"),
        "proxy_empty_mass_target_range_kg": closure.get("aircraft_empty_mass_target_range_kg"),
        "proxy_limitations": closure.get("limitations", []),
    }


def _geometry_summary(concept: GeometryConcept) -> dict[str, float]:
    return {
        "span_m": float(concept.span_m),
        "wing_area_m2": float(concept.wing_area_m2),
        "aspect_ratio": float(concept.aspect_ratio),
        "taper_ratio": float(concept.taper_ratio),
        "root_chord_m": float(concept.root_chord_m),
        "tip_chord_m": float(concept.tip_chord_m),
        "mean_chord_m": float(concept.wing_area_m2 / max(concept.span_m, 1.0e-9)),
        "mean_aerodynamic_chord_m": float(concept.mean_aerodynamic_chord_m),
    }


def _fourier_efficiency(a3: float, a5: float) -> dict[str, float]:
    harmonic_penalty = 3.0 * float(a3) ** 2 + 5.0 * float(a5) ** 2
    return {
        "a3_over_a1": float(a3),
        "a5_over_a1": float(a5),
        "target_fourier_e": float(1.0 / max(1.0 + harmonic_penalty, 1.0e-9)),
        "target_fourier_deviation": float(math.sqrt(max(harmonic_penalty, 0.0))),
        "outer_loading_ratio_eta_0p90": _fourier_spanload_ratio_to_ellipse(
            a3_over_a1=float(a3),
            a5_over_a1=float(a5),
            eta=0.90,
        ),
        "outer_loading_ratio_eta_0p95": _fourier_spanload_ratio_to_ellipse(
            a3_over_a1=float(a3),
            a5_over_a1=float(a5),
            eta=0.95,
        ),
    }


def _linear_chord_at_eta(concept: GeometryConcept, eta: float) -> float:
    eta_clamped = min(max(float(eta), 0.0), 1.0)
    return float(
        concept.root_chord_m
        + eta_clamped * (float(concept.tip_chord_m) - float(concept.root_chord_m))
    )


def _target_spanload_solution(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    design_speed_mps: float,
) -> dict[str, Any]:
    spanload_cfg = cfg.geometry_family.spanload_design
    air = _air_properties(cfg)
    half_span_m = 0.5 * float(concept.span_m)
    a3 = float(concept.spanload_a3_over_a1)
    a5 = float(concept.spanload_a5_over_a1)
    q_pa = 0.5 * float(air.density_kg_per_m3) * float(design_speed_mps) ** 2
    design_cl = (
        float(cfg.mass.design_gross_mass_kg)
        * G_MPS2
        / max(q_pa * float(concept.wing_area_m2), 1.0e-9)
    )

    target_etas = {
        float(value)
        for value in np.linspace(0.0, 1.0, int(spanload_cfg.target_station_count))
    }
    integration_records: list[dict[str, float]] = []
    for eta in sorted(target_etas):
        shape = _fourier_spanload_shape(a3_over_a1=a3, a5_over_a1=a5, eta=eta)
        integration_records.append(
            {
                "eta": float(eta),
                "y_m": float(eta * half_span_m),
                "shape": float(shape),
                "chord_m": _linear_chord_at_eta(concept, eta),
            }
        )

    shape_integral_m = 0.0
    for left, right in zip(integration_records, integration_records[1:]):
        dy_m = float(right["y_m"] - left["y_m"])
        shape_integral_m += 0.5 * dy_m * (float(left["shape"]) + float(right["shape"]))
    cl_scale = design_cl * float(concept.wing_area_m2) / max(2.0 * shape_integral_m, 1.0e-9)
    max_shape = max((record["shape"] for record in integration_records), default=1.0)
    return {
        "air_properties": air,
        "design_speed_mps": float(design_speed_mps),
        "design_mass_kg": float(cfg.mass.design_gross_mass_kg),
        "design_cl": float(design_cl),
        "dynamic_pressure_pa": float(q_pa),
        "target_circulation_integral_m": float(shape_integral_m),
        "cl_scale": float(cl_scale),
        "max_shape": float(max_shape),
    }


def _target_local_record_at_eta(
    *,
    concept: GeometryConcept,
    solution: dict[str, Any],
    eta: float,
) -> dict[str, float]:
    eta_clamped = min(max(float(eta), 0.0), 1.0)
    shape = _fourier_spanload_shape(
        a3_over_a1=float(concept.spanload_a3_over_a1),
        a5_over_a1=float(concept.spanload_a5_over_a1),
        eta=eta_clamped,
    )
    chord_m = _linear_chord_at_eta(concept, eta_clamped)
    local_cl = float(solution["cl_scale"]) * float(shape) / max(chord_m, 1.0e-9)
    return {
        "eta": float(eta_clamped),
        "chord_m": float(chord_m),
        "shape": float(shape),
        "target_circulation_norm": float(shape / max(float(solution["max_shape"]), 1.0e-9)),
        "target_local_cl": float(local_cl),
    }


def _target_station_records(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    design_speed_mps: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spanload_cfg = cfg.geometry_family.spanload_design
    half_span_m = 0.5 * float(concept.span_m)
    solution = _target_spanload_solution(
        cfg=cfg,
        concept=concept,
        design_speed_mps=design_speed_mps,
    )
    air = solution["air_properties"]

    target_etas = {
        float(value)
        for value in np.linspace(0.0, 1.0, int(spanload_cfg.target_station_count))
    }
    target_etas.update(
        0.0 if half_span_m <= 0.0 else float(station.y_m) / half_span_m
        for station in stations
    )
    integration_records: list[dict[str, float]] = []
    for eta in sorted(min(max(float(value), 0.0), 1.0) for value in target_etas):
        local = _target_local_record_at_eta(concept=concept, solution=solution, eta=eta)
        integration_records.append(
            {
                "eta": float(eta),
                "y_m": float(eta * half_span_m),
                "shape": float(local["shape"]),
                "chord_m": float(local["chord_m"]),
            }
        )

    safe_clmax = float(spanload_cfg.local_clmax_safe_floor)
    gate_records: list[dict[str, Any]] = []
    worst = {
        "eta": None,
        "y_m": None,
        "chord_m": None,
        "reynolds": None,
        "local_cl": None,
        "clmax_utilization": -1.0,
        "outer_eta": None,
        "outer_y_m": None,
        "outer_chord_m": None,
        "outer_reynolds": None,
        "outer_local_cl": None,
        "outer_clmax_utilization": -1.0,
    }
    for record in integration_records:
        eta = float(record["eta"])
        y_m = float(record["y_m"])
        chord_m = float(record["chord_m"])
        local = _target_local_record_at_eta(concept=concept, solution=solution, eta=eta)
        shape = float(local["shape"])
        local_cl = float(local["target_local_cl"])
        utilization = local_cl / max(safe_clmax, 1.0e-9)
        reynolds = (
            float(air.density_kg_per_m3)
            * float(design_speed_mps)
            * chord_m
            / max(float(air.dynamic_viscosity_pa_s), 1.0e-12)
        )
        gate_record = {
            "eta": float(eta),
            "y_m": float(y_m),
            "chord_m": float(chord_m),
            "reynolds": float(reynolds),
            "target_circulation_shape": float(shape),
            "target_circulation_norm": float(local["target_circulation_norm"]),
            "target_local_cl": float(local_cl),
            "target_clmax_safe_floor": float(safe_clmax),
            "target_clmax_utilization": float(utilization),
        }
        gate_records.append(gate_record)
        if utilization > float(worst["clmax_utilization"]):
            worst.update(
                {
                    "eta": float(eta),
                    "y_m": float(y_m),
                    "chord_m": float(chord_m),
                    "reynolds": float(reynolds),
                    "local_cl": float(local_cl),
                    "clmax_utilization": float(utilization),
                }
            )
        if eta >= float(spanload_cfg.outer_eta_start) and utilization > float(
            worst["outer_clmax_utilization"]
        ):
            worst.update(
                {
                    "outer_eta": float(eta),
                    "outer_y_m": float(y_m),
                    "outer_chord_m": float(chord_m),
                    "outer_reynolds": float(reynolds),
                    "outer_local_cl": float(local_cl),
                    "outer_clmax_utilization": float(utilization),
                }
            )

    station_records: list[dict[str, Any]] = []
    for station in stations:
        eta = 0.0 if half_span_m <= 0.0 else min(max(float(station.y_m) / half_span_m, 0.0), 1.0)
        local = _target_local_record_at_eta(concept=concept, solution=solution, eta=eta)
        shape = float(local["shape"])
        local_cl = float(local["target_local_cl"])
        utilization = local_cl / max(safe_clmax, 1.0e-9)
        reynolds = (
            float(air.density_kg_per_m3)
            * float(design_speed_mps)
            * float(station.chord_m)
            / max(float(air.dynamic_viscosity_pa_s), 1.0e-12)
        )
        station_records.append(
            {
                "eta": float(eta),
                "y_m": float(station.y_m),
                "chord_m": float(station.chord_m),
                "twist_deg": float(station.twist_deg),
                "reynolds": float(reynolds),
                "target_circulation_shape": float(shape),
                "target_circulation_norm": float(local["target_circulation_norm"]),
                "target_local_cl": float(local_cl),
                "target_clmax_safe_floor": float(safe_clmax),
                "target_clmax_utilization": float(utilization),
            }
        )

    summary = {
        "design_speed_mps": float(design_speed_mps),
        "design_mass_kg": float(cfg.mass.design_gross_mass_kg),
        "design_cl": float(solution["design_cl"]),
        "dynamic_pressure_pa": float(solution["dynamic_pressure_pa"]),
        "target_circulation_integral_m": float(solution["target_circulation_integral_m"]),
        "safe_clmax": float(safe_clmax),
        "worst_station": worst,
        "gate_station_table": gate_records,
    }
    return station_records, summary


def _spanload_gate_health(station_summary: dict[str, Any], cfg: BirdmanConceptConfig) -> dict[str, Any]:
    spanload_cfg = cfg.geometry_family.spanload_design
    worst = station_summary["worst_station"]
    local_limit = float(spanload_cfg.local_clmax_utilization_max)
    outer_limit = float(spanload_cfg.outer_cruise_clmax_utilization_max)
    max_util = float(worst["clmax_utilization"])
    outer_util = float(worst["outer_clmax_utilization"])
    return {
        "max_local_clmax_utilization": max_util,
        "max_local_clmax_utilization_limit": local_limit,
        "local_margin_to_limit": float(local_limit - max_util),
        "max_outer_clmax_utilization": outer_util,
        "max_outer_clmax_utilization_limit": outer_limit,
        "outer_margin_to_limit": float(outer_limit - outer_util),
    }


def _mission_power_proxy(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    design_speed_mps: float,
) -> dict[str, float | str]:
    air = _air_properties(cfg)
    q_pa = 0.5 * float(air.density_kg_per_m3) * float(design_speed_mps) ** 2
    design_cl = (
        float(cfg.mass.design_gross_mass_kg)
        * G_MPS2
        / max(q_pa * float(concept.wing_area_m2), 1.0e-9)
    )
    target_e = float(
        _fourier_efficiency(
            float(concept.spanload_a3_over_a1),
            float(concept.spanload_a5_over_a1),
        )["target_fourier_e"]
    )
    induced_cd = design_cl**2 / max(
        math.pi * float(concept.aspect_ratio) * target_e,
        1.0e-9,
    )
    profile_cd = FIXED_AIRFOIL_PROFILE_CD_PROXY
    tail_area_ratio = float(concept.tail_area_m2) / max(float(concept.wing_area_m2), 1.0e-9)
    misc_cd = misc_cd_proxy(
        profile_cd=profile_cd,
        tail_area_ratio=tail_area_ratio,
        proxy_cfg=cfg.aero_proxies.parasite_drag,
    )
    rigging_cd = compute_rigging_drag_cda_m2(cfg.rigging_drag) / max(
        float(concept.wing_area_m2),
        1.0e-9,
    )
    total_cd = induced_cd + profile_cd + misc_cd + rigging_cd
    drag_n = q_pa * float(concept.wing_area_m2) * total_cd
    shaft_power_w = drag_n * float(design_speed_mps) / max(
        float(cfg.prop.efficiency_model.design_efficiency),
        1.0e-9,
    )
    pedal_power_w = shaft_power_w / max(float(cfg.drivetrain.efficiency), 1.0e-9)
    return {
        "model": "fixed_airfoil_target_fourier_drag_proxy_v1",
        "speed_mps": float(design_speed_mps),
        "mass_kg": float(cfg.mass.design_gross_mass_kg),
        "power_required_w": float(pedal_power_w),
        "shaft_power_required_w": float(shaft_power_w),
        "drag_n": float(drag_n),
        "design_cl": float(design_cl),
        "target_fourier_e": float(target_e),
        "induced_cd": float(induced_cd),
        "profile_cd": float(profile_cd),
        "misc_cd": float(misc_cd),
        "rigging_cd": float(rigging_cd),
        "total_cd": float(total_cd),
    }


def _accepted_candidate_metric(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    sample_index: int,
    design_speed_mps: float,
) -> dict[str, Any]:
    stations = build_linear_wing_stations(
        concept,
        stations_per_half=int(cfg.pipeline.stations_per_half),
    )
    _, target_summary = _target_station_records(
        cfg=cfg,
        concept=concept,
        stations=stations,
        design_speed_mps=design_speed_mps,
    )
    return {
        "sample_index": int(sample_index),
        "concept": concept,
        "geometry": _geometry_summary(concept),
        "spanload_gate_health": _spanload_gate_health(target_summary, cfg),
        "mission_power_proxy": _mission_power_proxy(
            cfg=cfg,
            concept=concept,
            design_speed_mps=design_speed_mps,
        ),
    }


def _utilization_sort_key(record: dict[str, Any]) -> tuple[float, float, int]:
    health = record["spanload_gate_health"]
    max_utilization = max(
        float(health["max_local_clmax_utilization"]),
        float(health["max_outer_clmax_utilization"]),
    )
    return (
        max_utilization,
        -float(record["geometry"]["aspect_ratio"]),
        int(record["sample_index"]),
    )


def _select_accepted_leaderboards(
    records: list[dict[str, Any]],
    *,
    per_board_count: int,
) -> dict[str, list[dict[str, Any]]]:
    count = max(0, int(per_board_count))
    return {
        "highest_ar_accepted": sorted(
            records,
            key=lambda record: (
                -float(record["geometry"]["aspect_ratio"]),
                int(record["sample_index"]),
            ),
        )[:count],
        "best_mission_power_proxy_accepted": sorted(
            records,
            key=lambda record: (
                float(record["mission_power_proxy"]["power_required_w"]),
                -float(record["geometry"]["aspect_ratio"]),
                int(record["sample_index"]),
            ),
        )[:count],
        "lowest_utilization_accepted": sorted(records, key=_utilization_sort_key)[:count],
    }


def _selected_samples_from_leaderboards(
    leaderboards: dict[str, list[dict[str, Any]]],
) -> list[int]:
    selected: list[int] = []
    for board_name in (
        "highest_ar_accepted",
        "best_mission_power_proxy_accepted",
        "lowest_utilization_accepted",
    ):
        for record in leaderboards.get(board_name, []):
            sample_index = int(record["sample_index"])
            if sample_index not in selected:
                selected.append(sample_index)
    return selected


def _leaderboard_memberships(
    leaderboards: dict[str, list[dict[str, Any]]],
) -> dict[int, list[str]]:
    memberships: dict[int, list[str]] = {}
    for board_name, records in leaderboards.items():
        for record in records:
            memberships.setdefault(int(record["sample_index"]), []).append(board_name)
    return memberships


def _concept_from_rejection(
    cfg: BirdmanConceptConfig,
    rejection: GeometryRejection,
) -> GeometryConcept | None:
    primary = dict(rejection.primary_values)
    secondary = dict(rejection.secondary_values)
    try:
        span_m = float(primary["span_m"])
        taper_ratio = float(primary["taper_ratio"])
        planform_parameterization = str(cfg.geometry_family.planform_parameterization)
        if planform_parameterization == "mean_chord":
            mean_chord_target_m = float(primary["mean_chord_m"])
            wing_area_m2 = float(span_m * mean_chord_target_m)
            wing_loading_target_Npm2 = float(cfg.design_gross_weight_n / max(wing_area_m2, 1.0e-9))
        else:
            mean_chord_target_m = None
            wing_loading_target_Npm2 = float(primary["wing_loading_target_Npm2"])
            wing_area_m2 = float(cfg.design_gross_weight_n / max(wing_loading_target_Npm2, 1.0e-9))

        root_chord_m = 2.0 * wing_area_m2 / (span_m * (1.0 + taper_ratio))
        tip_chord_m = root_chord_m * taper_ratio
        twist_mid_eta, twist_outer_eta = (
            float(value) for value in cfg.geometry_family.twist_control_etas
        )
        twist_control_points = (
            (0.0, float(cfg.geometry_family.twist_root_deg)),
            (twist_mid_eta, float(primary["twist_mid_deg"])),
            (twist_outer_eta, float(primary["twist_outer_deg"])),
            (1.0, float(primary["tip_twist_deg"])),
        )
        twist_control_points = _apply_spanload_bias_washout(
            twist_control_points=twist_control_points,
            spanload_bias=float(primary["spanload_bias"]),
            washout_gain_deg=float(cfg.geometry_family.spanload_bias_washout_gain_deg),
        )
        tail_sizing_mode = str(cfg.geometry_family.tail_sizing_mode)
        if tail_sizing_mode == "tail_volume":
            tail_volume_coefficient = float(secondary["tail_volume_coefficient"])
            tail_area_m2 = float(
                secondary.get(
                    "tail_area_m2",
                    tail_volume_coefficient
                    * wing_area_m2
                    / float(cfg.tail_model.tail_arm_to_mac),
                )
            )
            tail_area_source = "derived_from_tail_volume_coefficient"
        else:
            tail_volume_coefficient = None
            tail_area_m2 = float(secondary["tail_area_m2"])
            tail_area_source = "fixed_area_candidate"
        segment_lengths_m = build_segment_plan(
            half_span_m=0.5 * span_m,
            min_segment_length_m=float(cfg.segmentation.min_segment_length_m),
            max_segment_length_m=float(cfg.segmentation.max_segment_length_m),
        )
        return GeometryConcept(
            span_m=float(span_m),
            wing_area_m2=float(wing_area_m2),
            root_chord_m=float(root_chord_m),
            tip_chord_m=float(tip_chord_m),
            twist_root_deg=float(cfg.geometry_family.twist_root_deg),
            twist_tip_deg=float(twist_control_points[-1][1]),
            twist_control_points=twist_control_points,
            spanload_bias=float(primary["spanload_bias"]),
            spanload_a3_over_a1=float(cfg.geometry_family.spanload_design.a3_over_a1),
            spanload_a5_over_a1=float(cfg.geometry_family.spanload_design.a5_over_a1),
            dihedral_root_deg=float(secondary["dihedral_root_deg"]),
            dihedral_tip_deg=float(secondary["dihedral_tip_deg"]),
            dihedral_exponent=float(secondary["dihedral_exponent"]),
            tail_area_m2=float(tail_area_m2),
            tail_area_source=tail_area_source,
            tail_volume_coefficient=tail_volume_coefficient,
            cg_xc=float(cfg.geometry_family.cg_xc),
            segment_lengths_m=segment_lengths_m,
            wing_loading_target_Npm2=float(wing_loading_target_Npm2),
            mean_chord_target_m=mean_chord_target_m,
            wing_area_is_derived=True,
            planform_parameterization=planform_parameterization,
            design_gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
        )
    except (KeyError, ValueError) as exc:
        print(f"warning: could not reconstruct rejected sample {rejection.sample_index}: {exc}")
        return None


def _rejection_severity(rejection: GeometryRejection) -> float:
    details = rejection.details
    reason = rejection.reason
    if reason == "spanload_design_local_clmax_utilization_exceeded":
        return float(details["local_clmax_utilization"]) / max(
            float(details["local_clmax_utilization_max"]),
            1.0e-9,
        )
    if reason == "spanload_design_outer_clmax_utilization_exceeded":
        return float(details["outer_clmax_utilization"]) / max(
            float(details["outer_clmax_utilization_max"]),
            1.0e-9,
        )
    if reason == "spanload_design_tip_re_below_min":
        return float(details["tip_re_abs_min"]) / max(float(details["tip_re"]), 1.0e-9)
    if reason == "spanload_design_outer_loading_above_max":
        return float(details["outer_loading_ratio_to_ellipse"]) / max(
            float(details["outer_loading_max_ratio_to_ellipse"]),
            1.0e-9,
        )
    return float("inf")


def _run_reference_avl_case(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    output_dir: Path,
    design_speed_mps: float,
    design_mass_kg: float,
    status_for_ranking: str,
    avl_binary: str | None,
    case_tag: str | None = None,
) -> dict[str, Any]:
    air = _air_properties(cfg)
    case_dir_name = f"{status_for_ranking}_{concept.span_m:.3f}_{concept.taper_ratio:.4f}"
    if case_tag is not None:
        case_dir_name = f"{case_dir_name}_{case_tag}"
    case_dir = output_dir / "avl_cases" / case_dir_name
    avl_path = write_concept_wing_only_avl(
        concept=concept,
        stations=stations,
        output_path=case_dir / "concept_wing.avl",
        zone_airfoil_paths=None,
    )
    dynamic_pressure_pa = 0.5 * float(air.density_kg_per_m3) * float(design_speed_mps) ** 2
    cl_required = (
        float(design_mass_kg) * G_MPS2 / max(dynamic_pressure_pa * float(concept.wing_area_m2), 1.0e-9)
    )
    try:
        trim_totals = _run_avl_trim_case(
            avl_path=avl_path,
            case_dir=case_dir / CASE_LABEL,
            cl_required=float(cl_required),
            velocity_mps=float(design_speed_mps),
            density_kgpm3=float(air.density_kg_per_m3),
            avl_binary=avl_binary,
        )
        fs_path = _run_avl_spanwise_case(
            avl_path=avl_path,
            case_dir=case_dir / CASE_LABEL,
            alpha_deg=float(trim_totals["aoa_trim_deg"]),
            velocity_mps=float(design_speed_mps),
            density_kgpm3=float(air.density_kg_per_m3),
            avl_binary=avl_binary,
        )
        avl_spanwise_load = build_spanwise_load_from_avl_strip_forces(
            fs_path=fs_path,
            avl_path=avl_path,
            aoa_deg=float(trim_totals["aoa_trim_deg"]),
            velocity_mps=float(design_speed_mps),
            density_kgpm3=float(air.density_kg_per_m3),
            target_surface_names=("Wing",),
            positive_y_only=True,
        )
        station_load = resample_spanwise_load_to_stations(
            spanwise_load=avl_spanwise_load,
            stations=stations,
        )
        zone_payload = avl_zone_payload_from_spanwise_load(
            spanwise_load=station_load,
            stations=stations,
            dynamic_viscosity_pa_s=float(air.dynamic_viscosity_pa_s),
            case_label=CASE_LABEL,
            case_weight=1.0,
            evaluation_speed_mps=float(design_speed_mps),
            evaluation_gross_mass_kg=float(design_mass_kg),
            load_factor=1.0,
            case_reason="fixed_airfoil_spanload_design_smoke_reference_cruise",
            trim_totals=trim_totals,
        )
    except Exception as exc:  # noqa: BLE001 - report smoke diagnostics instead of hiding partial output.
        return {
            "status": "failed",
            "error": str(exc),
            "case_label": CASE_LABEL,
            "evaluation_speed_mps": float(design_speed_mps),
            "evaluation_gross_mass_kg": float(design_mass_kg),
            "cl_required": float(cl_required),
            "ranking_authority_status": "invalid_avl_failed",
        }

    flat_points: list[dict[str, Any]] = []
    for zone_payload_record in zone_payload.values():
        flat_points.extend(zone_payload_record.get("points", []))
    flat_points.sort(key=lambda point: float(point.get("station_y_m", 0.0)))
    trim_cl = trim_totals.get("cl_trim")
    cd_induced = trim_totals.get("cd_induced")
    e_cdi = None
    if trim_cl is not None and cd_induced is not None and float(cd_induced) > 0.0:
        e_cdi = float(trim_cl) ** 2 / (
            math.pi * float(concept.aspect_ratio) * float(cd_induced)
        )
    return {
        "status": "ok",
        "case_label": CASE_LABEL,
        "case_reason": "fixed_airfoil_spanload_design_smoke_reference_cruise",
        "evaluation_speed_mps": float(design_speed_mps),
        "evaluation_gross_mass_kg": float(design_mass_kg),
        "load_factor": 1.0,
        "cl_required": float(cl_required),
        "trim_aoa_deg": trim_totals.get("aoa_trim_deg"),
        "trim_cl": trim_totals.get("cl_trim"),
        "trim_cd_induced": trim_totals.get("cd_induced"),
        "avl_e_cdi": e_cdi,
        "avl_reported_e": trim_totals.get("span_efficiency"),
        "ranking_authority_status": status_for_ranking,
        "avl_case_dir": str(case_dir),
        "station_points": flat_points,
    }


def _attach_avl_to_station_table(
    station_records: list[dict[str, Any]],
    avl_record: dict[str, Any],
) -> list[dict[str, Any]]:
    avl_points = avl_record.get("station_points") or []
    if not avl_points:
        return station_records
    max_avl_circulation = max(
        (
            max(float(point.get("cl_target", 0.0)) * float(point.get("chord_m", 0.0)), 0.0)
            for point in avl_points
        ),
        default=1.0,
    )
    attached: list[dict[str, Any]] = []
    for record in station_records:
        y_m = float(record["y_m"])
        nearest = min(
            avl_points,
            key=lambda point: abs(float(point.get("station_y_m", 0.0)) - y_m),
        )
        avl_circulation = float(nearest.get("cl_target", 0.0)) * float(
            nearest.get("chord_m", 0.0)
        )
        avl_norm = avl_circulation / max(max_avl_circulation, 1.0e-9)
        combined = dict(record)
        combined.update(
            {
                "avl_station_y_m": float(nearest.get("station_y_m", y_m)),
                "avl_reynolds": nearest.get("reynolds"),
                "avl_local_cl": nearest.get("cl_target"),
                "avl_circulation_proxy": float(avl_circulation),
                "avl_circulation_norm": float(avl_norm),
                "target_minus_avl_circulation_norm": float(
                    float(record["target_circulation_norm"]) - avl_norm
                ),
            }
        )
        attached.append(combined)
    return attached


def _sin_harmonic_ratio(*, eta: float, harmonic: int) -> float:
    eta_clamped = min(max(float(eta), 0.0), INVERSE_TWIST_MAX_AERO_ETA)
    theta = math.acos(eta_clamped)
    denominator = math.sin(theta)
    if abs(denominator) <= 1.0e-9:
        return 0.0
    return float(math.sin(float(harmonic) * theta) / denominator)


def _target_induced_angle_deg(
    *,
    concept: GeometryConcept,
    design_cl: float,
    eta: float,
) -> float:
    eta_eff = min(max(float(eta), 0.0), INVERSE_TWIST_MAX_AERO_ETA)
    a1 = float(design_cl) / max(math.pi * float(concept.aspect_ratio), 1.0e-9)
    a3 = float(concept.spanload_a3_over_a1)
    a5 = float(concept.spanload_a5_over_a1)
    induced_rad = a1 * (
        1.0
        + 3.0 * a3 * _sin_harmonic_ratio(eta=eta_eff, harmonic=3)
        + 5.0 * a5 * _sin_harmonic_ratio(eta=eta_eff, harmonic=5)
    )
    return math.degrees(float(induced_rad))


def _alpha_2d_from_cl_deg(
    local_cl: float,
    *,
    zero_lift_alpha_deg: float = INVERSE_TWIST_ZERO_LIFT_ALPHA_DEG,
    lift_curve_slope_per_rad: float = INVERSE_TWIST_LIFT_CURVE_SLOPE_PER_RAD,
) -> float:
    return float(zero_lift_alpha_deg) + math.degrees(
        float(local_cl) / max(float(lift_curve_slope_per_rad), 1.0e-9)
    )


def _build_inverse_twist_stations(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    design_speed_mps: float,
) -> tuple[tuple[WingStation, ...], dict[str, Any]]:
    solution = _target_spanload_solution(
        cfg=cfg,
        concept=concept,
        design_speed_mps=design_speed_mps,
    )
    half_span_m = 0.5 * float(concept.span_m)
    target_section_angles: list[float] = []
    station_records: list[dict[str, float]] = []
    for station in stations:
        eta = 0.0 if half_span_m <= 0.0 else min(max(float(station.y_m) / half_span_m, 0.0), 1.0)
        eta_for_twist = min(eta, INVERSE_TWIST_MAX_AERO_ETA)
        target = _target_local_record_at_eta(
            concept=concept,
            solution=solution,
            eta=eta_for_twist,
        )
        alpha_2d_deg = _alpha_2d_from_cl_deg(float(target["target_local_cl"]))
        induced_angle_deg = _target_induced_angle_deg(
            concept=concept,
            design_cl=float(solution["design_cl"]),
            eta=eta_for_twist,
        )
        target_section_angle_deg = alpha_2d_deg + induced_angle_deg
        target_section_angles.append(target_section_angle_deg)
        station_records.append(
            {
                "eta": float(eta),
                "eta_for_twist": float(eta_for_twist),
                "y_m": float(station.y_m),
                "chord_m": float(station.chord_m),
                "target_local_cl": float(target["target_local_cl"]),
                "alpha_2d_deg": float(alpha_2d_deg),
                "induced_angle_deg": float(induced_angle_deg),
                "target_section_angle_deg": float(target_section_angle_deg),
            }
        )

    root_section_angle_deg = target_section_angles[0] if target_section_angles else 0.0
    inverse_stations: list[WingStation] = []
    inverse_records: list[dict[str, float]] = []
    root_twist_deg = float(concept.twist_root_deg)
    for station, record, target_section_angle_deg in zip(
        stations,
        station_records,
        target_section_angles,
        strict=True,
    ):
        twist_deg = root_twist_deg + float(target_section_angle_deg) - root_section_angle_deg
        inverse_stations.append(
            WingStation(
                y_m=float(station.y_m),
                chord_m=float(station.chord_m),
                twist_deg=float(twist_deg),
                dihedral_deg=float(station.dihedral_deg),
            )
        )
        inverse_records.append({**record, "twist_deg": float(twist_deg)})
    return tuple(inverse_stations), {
        "model": "inverse_twist_mvp_lift_curve",
        "zero_lift_alpha_deg": float(INVERSE_TWIST_ZERO_LIFT_ALPHA_DEG),
        "lift_curve_slope_per_rad": float(INVERSE_TWIST_LIFT_CURVE_SLOPE_PER_RAD),
        "induced_angle_model": "fourier_lifting_line_local_downwash",
        "max_aero_eta_for_tip_twist": float(INVERSE_TWIST_MAX_AERO_ETA),
        "root_twist_anchor_deg": root_twist_deg,
        "design_cl": float(solution["design_cl"]),
        "station_records": inverse_records,
    }


def _avl_match_metrics(station_table: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [
        abs(float(row["target_minus_avl_circulation_norm"]))
        for row in station_table
        if row.get("target_minus_avl_circulation_norm") is not None
    ]
    if not deltas:
        return {
            "max_target_avl_circulation_norm_delta": None,
            "max_delta_station": None,
            "target_avl_delta_success": False,
        }
    max_index = max(
        range(len(station_table)),
        key=lambda index: abs(
            float(station_table[index].get("target_minus_avl_circulation_norm") or 0.0)
        ),
    )
    max_delta = max(deltas)
    return {
        "max_target_avl_circulation_norm_delta": float(max_delta),
        "max_delta_station": {
            key: station_table[max_index].get(key)
            for key in (
                "eta",
                "y_m",
                "target_circulation_norm",
                "avl_circulation_norm",
                "target_minus_avl_circulation_norm",
            )
        },
        "target_avl_delta_success": bool(max_delta < SPANLOAD_DELTA_SUCCESS_LIMIT),
    }


def _correct_inverse_twist_stations(
    *,
    stations: tuple[WingStation, ...],
    station_table: list[dict[str, Any]],
    root_twist_deg: float,
    gain_deg: float,
    max_abs_twist_deg: float,
) -> tuple[WingStation, ...]:
    table_by_y = {
        round(float(row.get("y_m", 0.0)), 9): row
        for row in station_table
        if row.get("target_minus_avl_circulation_norm") is not None
    }
    corrected: list[WingStation] = []
    for station in stations:
        row = table_by_y.get(round(float(station.y_m), 9))
        error = 0.0 if row is None else float(row["target_minus_avl_circulation_norm"])
        eta = 0.0 if stations[-1].y_m <= 0.0 else float(station.y_m) / max(float(stations[-1].y_m), 1.0e-9)
        # Avoid chasing the physical tip cap; the aerodynamic target is capped just inboard.
        tip_relief = max(0.0, 1.0 - max(eta - INVERSE_TWIST_MAX_AERO_ETA, 0.0) / 0.03)
        corrected.append(
            WingStation(
                y_m=float(station.y_m),
                chord_m=float(station.chord_m),
                twist_deg=float(station.twist_deg) + float(gain_deg) * error * tip_relief,
                dihedral_deg=float(station.dihedral_deg),
            )
        )
    root_offset = float(corrected[0].twist_deg) - float(root_twist_deg)
    return tuple(
        WingStation(
            y_m=float(station.y_m),
            chord_m=float(station.chord_m),
            twist_deg=max(
                -float(max_abs_twist_deg),
                min(float(max_abs_twist_deg), float(station.twist_deg) - root_offset),
            ),
            dihedral_deg=float(station.dihedral_deg),
        )
        for station in corrected
    )


def _spanload_trust_status(candidate: dict[str, Any]) -> str:
    fourier_e = candidate["spanload_fourier"].get("target_fourier_e")
    avl_e = candidate["avl_reference_case"].get("avl_e_cdi")
    if avl_e is None:
        return "invalid_no_avl_e_cdi"
    max_delta = candidate.get("avl_match_metrics", {}).get(
        "max_target_avl_circulation_norm_delta",
    )
    if max_delta is not None and float(max_delta) < SPANLOAD_DELTA_SUCCESS_LIMIT and float(avl_e) >= AVL_E_CDI_SUCCESS_FLOOR:
        return "spanload_crosscheck_success"
    if fourier_e is not None and float(fourier_e) >= 0.90 and float(avl_e) < AVL_E_CDI_SUCCESS_FLOOR:
        return "spanload_not_trusted_avl_e_low_vs_fourier_high"
    if max_delta is not None and float(max_delta) >= SPANLOAD_DELTA_SUCCESS_LIMIT:
        return "spanload_not_trusted_target_avl_strip_mismatch"
    return "spanload_crosscheck_reasonable"


def _candidate_record(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    status: str,
    sample_index: int | None,
    rejection: GeometryRejection | None,
    output_dir: Path,
    design_speed_mps: float,
    avl_binary: str | None,
    leaderboard_memberships: list[str] | None = None,
    inverse_twist_iterations: int = 3,
    inverse_twist_correction_gain_deg: float = 8.0,
    inverse_twist_max_abs_twist_deg: float = INVERSE_TWIST_MAX_ABS_TWIST_DEG,
) -> dict[str, Any]:
    baseline_stations = build_linear_wing_stations(
        concept,
        stations_per_half=int(cfg.pipeline.stations_per_half),
    )
    inverse_stations, inverse_twist_summary = _build_inverse_twist_stations(
        cfg=cfg,
        concept=concept,
        stations=baseline_stations,
        design_speed_mps=design_speed_mps,
    )
    stations = inverse_stations
    target_table, target_summary = _target_station_records(
        cfg=cfg,
        concept=concept,
        stations=stations,
        design_speed_mps=design_speed_mps,
    )
    health = _spanload_gate_health(target_summary, cfg)
    ranking_authority_status = (
        "valid_design_cruise_same_mass_hard_gates_passed"
        if status == "accepted"
        else "invalid_failed_spanload_gate_diagnostic_only"
    )
    avl = _run_reference_avl_case(
        cfg=cfg,
        concept=concept,
        stations=stations,
        output_dir=output_dir,
        design_speed_mps=design_speed_mps,
        design_mass_kg=float(cfg.mass.design_gross_mass_kg),
        status_for_ranking=ranking_authority_status,
        avl_binary=avl_binary,
        case_tag="inverse_00",
    )
    station_table = _attach_avl_to_station_table(target_table, avl)
    iteration_records = [
        {
            "iteration": 0,
            "avl_status": avl.get("status"),
            "avl_e_cdi": avl.get("avl_e_cdi"),
            "avl_reported_e": avl.get("avl_reported_e"),
            **_avl_match_metrics(station_table),
        }
    ]
    for iteration in range(1, max(0, int(inverse_twist_iterations)) + 1):
        metrics = _avl_match_metrics(station_table)
        if (
            metrics["max_target_avl_circulation_norm_delta"] is not None
            and float(metrics["max_target_avl_circulation_norm_delta"])
            < SPANLOAD_DELTA_SUCCESS_LIMIT
        ):
            break
        stations = _correct_inverse_twist_stations(
            stations=stations,
            station_table=station_table,
            root_twist_deg=float(concept.twist_root_deg),
            gain_deg=float(inverse_twist_correction_gain_deg),
            max_abs_twist_deg=float(inverse_twist_max_abs_twist_deg),
        )
        target_table, target_summary = _target_station_records(
            cfg=cfg,
            concept=concept,
            stations=stations,
            design_speed_mps=design_speed_mps,
        )
        avl = _run_reference_avl_case(
            cfg=cfg,
            concept=concept,
            stations=stations,
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            design_mass_kg=float(cfg.mass.design_gross_mass_kg),
            status_for_ranking=ranking_authority_status,
            avl_binary=avl_binary,
            case_tag=f"inverse_{iteration:02d}",
        )
        station_table = _attach_avl_to_station_table(target_table, avl)
        iteration_records.append(
            {
                "iteration": int(iteration),
                "avl_status": avl.get("status"),
                "avl_e_cdi": avl.get("avl_e_cdi"),
                "avl_reported_e": avl.get("avl_reported_e"),
                **_avl_match_metrics(station_table),
            }
        )
    failing_gate = None
    worst_station = target_summary["worst_station"]
    if rejection is not None:
        failing_gate = {
            "sample_index": int(rejection.sample_index),
            "reason": str(rejection.reason),
            "severity_ratio": _rejection_severity(rejection),
            "details": rejection.details,
        }
    record = {
        "status": status,
        "sample_index": sample_index,
        "selection_rule": (
            "accepted leaderboard union"
            if status == "accepted"
            else "closest rejected spanload gate violation"
        ),
        "leaderboard_memberships": list(leaderboard_memberships or []),
        "mass_authority": _mission_mass_authority(cfg, concept),
        "geometry": _geometry_summary(concept),
        "mission_power_proxy": _mission_power_proxy(
            cfg=cfg,
            concept=concept,
            design_speed_mps=design_speed_mps,
        ),
        "spanload_fourier": _fourier_efficiency(
            float(concept.spanload_a3_over_a1),
            float(concept.spanload_a5_over_a1),
        ),
        "spanload_gate_health": health,
        "inverse_twist": {
            **inverse_twist_summary,
            "correction_gain_deg_per_norm_delta": float(inverse_twist_correction_gain_deg),
            "max_abs_twist_deg": float(inverse_twist_max_abs_twist_deg),
            "requested_correction_iterations": int(inverse_twist_iterations),
            "completed_correction_iterations": max(
                0,
                len(iteration_records) - 1,
            ),
            "iteration_records": iteration_records,
        },
        "avl_reference_case": avl,
        "station_table": station_table,
        "avl_match_metrics": _avl_match_metrics(station_table),
        "gate_station_table": target_summary["gate_station_table"],
        "baseline_twist_distribution": [
            {
                "eta": (
                    0.0
                    if concept.span_m <= 0.0
                    else float(station.y_m) / max(0.5 * float(concept.span_m), 1.0e-9)
                ),
                "y_m": float(station.y_m),
                "twist_deg": float(station.twist_deg),
            }
            for station in baseline_stations
        ],
        "twist_distribution": [
            {
                "eta": float(record["eta"]),
                "y_m": float(record["y_m"]),
                "twist_deg": float(record["twist_deg"]),
            }
            for record in station_table
        ],
        "failing_gate": failing_gate,
        "worst_station": worst_station,
    }
    record["spanload_trust_status"] = _spanload_trust_status(record)
    return record


def _format_float(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return f"{float(value):.{digits}f}"
    return str(value)


def _markdown_candidate(candidate: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    geom = candidate["geometry"]
    mass = candidate["mass_authority"]
    fourier = candidate["spanload_fourier"]
    health = candidate["spanload_gate_health"]
    avl = candidate["avl_reference_case"]
    power = candidate["mission_power_proxy"]
    match = candidate["avl_match_metrics"]
    title = f"{candidate['status'].title()} candidate"
    if candidate.get("sample_index") is not None:
        title += f" sample {candidate['sample_index']}"
    if candidate.get("leaderboard_memberships"):
        title += f" ({', '.join(candidate['leaderboard_memberships'])})"
    lines.append(f"### {title}")
    lines.append("")
    lines.append(
        "- Mass authority: primary "
        f"{_format_float(mass['primary_design_gross_mass_kg'], 2)} kg; "
        f"mission cases {mass['gross_mass_sweep_kg']}; "
        f"proxy gross {_format_float(mass['proxy_estimated_gross_mass_kg'], 2)} kg, "
        f"proxy empty {_format_float(mass['proxy_estimated_empty_mass_kg'], 2)} kg, "
        f"budget warning {mass['proxy_budget_warning']}."
    )
    lines.append(
        "- Geometry: "
        f"span {_format_float(geom['span_m'], 2)} m, "
        f"S {_format_float(geom['wing_area_m2'], 2)} m2, "
        f"AR {_format_float(geom['aspect_ratio'], 2)}, "
        f"taper {_format_float(geom['taper_ratio'], 3)}, "
        f"root/tip chord {_format_float(geom['root_chord_m'], 3)}/"
        f"{_format_float(geom['tip_chord_m'], 3)} m."
    )
    lines.append(
        "- Mission-power proxy: "
        f"{_format_float(power['power_required_w'], 1)} W pedal, "
        f"CDi {_format_float(power['induced_cd'], 5)}, "
        f"CDtotal {_format_float(power['total_cd'], 5)}."
    )
    lines.append(
        "- Fourier: "
        f"a3 {_format_float(fourier['a3_over_a1'], 3)}, "
        f"a5 {_format_float(fourier['a5_over_a1'], 3)}, "
        f"target_fourier_e {_format_float(fourier['target_fourier_e'], 4)}, "
        f"target_fourier_deviation {_format_float(fourier['target_fourier_deviation'], 4)}."
    )
    lines.append(
        "- Gate health: "
        f"local util {_format_float(health['max_local_clmax_utilization'], 3)} / "
        f"{_format_float(health['max_local_clmax_utilization_limit'], 3)}, "
        f"outer util {_format_float(health['max_outer_clmax_utilization'], 3)} / "
        f"{_format_float(health['max_outer_clmax_utilization_limit'], 3)}."
    )
    lines.append(
        "- AVL: "
        f"{avl.get('status')} case {avl.get('case_label')} at "
        f"{_format_float(avl.get('evaluation_speed_mps'), 2)} m/s, "
        f"{_format_float(avl.get('evaluation_gross_mass_kg'), 2)} kg; "
        f"CL {_format_float(avl.get('trim_cl'), 4)}, "
        f"CDi {_format_float(avl.get('trim_cd_induced'), 6)}, "
        f"e_CDi {_format_float(avl.get('avl_e_cdi'), 4)}, "
        f"reported e {_format_float(avl.get('avl_reported_e'), 4)}; "
        f"authority {avl.get('ranking_authority_status')}."
    )
    lines.append(
        "- Target vs AVL: "
        f"max normalized delta {_format_float(match.get('max_target_avl_circulation_norm_delta'), 3)} "
        f"(goal < {SPANLOAD_DELTA_SUCCESS_LIMIT:.2f}); "
        f"AVL e_CDi goal >= {AVL_E_CDI_SUCCESS_FLOOR:.2f}."
    )
    lines.append(f"- Spanload trust: {candidate.get('spanload_trust_status')}.")
    if candidate.get("failing_gate"):
        gate = candidate["failing_gate"]
        lines.append(
            "- Failing gate: "
            f"{gate['reason']} severity {_format_float(gate['severity_ratio'], 3)}."
        )
    worst = candidate["worst_station"]
    lines.append(
        "- Worst gate station: "
        f"eta {_format_float(worst.get('eta'), 3)}, "
        f"y {_format_float(worst.get('y_m'), 2)} m, "
        f"chord {_format_float(worst.get('chord_m'), 3)} m, "
        f"Re {_format_float(worst.get('reynolds'), 0)}, "
        f"cl {_format_float(worst.get('local_cl'), 3)}, "
        f"util {_format_float(worst.get('clmax_utilization'), 3)}."
    )
    lines.append("")
    lines.append("| eta | y m | chord m | Re | target cl | util | twist deg | target circ | AVL cl | AVL circ | d circ |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in candidate["station_table"]:
        lines.append(
            "| "
            f"{_format_float(row.get('eta'), 3)} | "
            f"{_format_float(row.get('y_m'), 2)} | "
            f"{_format_float(row.get('chord_m'), 3)} | "
            f"{_format_float(row.get('reynolds'), 0)} | "
            f"{_format_float(row.get('target_local_cl'), 3)} | "
            f"{_format_float(row.get('target_clmax_utilization'), 3)} | "
            f"{_format_float(row.get('twist_deg'), 2)} | "
            f"{_format_float(row.get('target_circulation_norm'), 3)} | "
            f"{_format_float(row.get('avl_local_cl'), 3)} | "
            f"{_format_float(row.get('avl_circulation_norm'), 3)} | "
            f"{_format_float(row.get('target_minus_avl_circulation_norm'), 3)} |"
        )
    lines.append("")
    return lines


def _leaderboard_candidate_summary(candidate: dict[str, Any]) -> str:
    geometry = candidate["geometry"]
    power = candidate["mission_power_proxy"]
    avl = candidate["avl_reference_case"]
    match = candidate["avl_match_metrics"]
    return (
        f"sample {candidate['sample_index']}: "
        f"AR {_format_float(geometry['aspect_ratio'], 2)}, "
        f"span {_format_float(geometry['span_m'], 2)} m, "
        f"S {_format_float(geometry['wing_area_m2'], 2)} m2, "
        f"power proxy {_format_float(power['power_required_w'], 1)} W, "
        f"AVL e_CDi {_format_float(avl.get('avl_e_cdi'), 4)}, "
        f"target delta {_format_float(match.get('max_target_avl_circulation_norm_delta'), 3)}"
    )


def _write_markdown_report(report: dict[str, Any], path: Path) -> None:
    lines: list[str] = [
        "# Birdman Spanload Design Smoke",
        "",
        "Fixed-airfoil smoke only: no CST, no XFOIL, no Julia worker. AVL uses the current wing-only fixed seed airfoil route for a single design-cruise reference case.",
        "",
        "## Summary",
        "",
        f"- Config: `{report['config_path']}`",
        f"- Output: `{report['output_dir']}`",
        f"- Geometry accepted/rejected: {report['geometry_counts']['accepted']} / {report['geometry_counts']['rejected']}",
        f"- Rejection counts: `{report['geometry_counts']['rejection_reason_counts']}`",
        f"- Design cruise smoke case: {report['design_cruise_case']['speed_mps']} m/s, {report['design_cruise_case']['mass_kg']} kg",
        f"- Candidate selection: {report['candidate_selection_rule']}",
        "",
        "## Engineering Read",
        "",
    ]
    lines.extend(f"- {item}" for item in report["engineering_read"])
    lines.append("")
    lines.append("## Accepted Leaderboards")
    lines.append("")
    for board_name, candidates in report["accepted_leaderboards"].items():
        lines.append(f"### {board_name}")
        lines.append("")
        if not candidates:
            lines.append("- n/a")
        for candidate in candidates:
            lines.append(f"- {_leaderboard_candidate_summary(candidate)}")
        lines.append("")
    lines.append("## Candidates")
    lines.append("")
    for candidate in report["candidates"]:
        lines.extend(_markdown_candidate(candidate))
    path.write_text("\n".join(lines), encoding="utf-8")


def _engineering_read(report: dict[str, Any]) -> list[str]:
    counts = report["geometry_counts"]
    accepted = int(counts["accepted"])
    rejected = int(counts["rejected"])
    read = []
    if accepted > 0 and rejected > 0:
        read.append(
            "The spanload gates are active but not degenerate: they pass some candidates and reject others."
        )
    elif accepted == 0:
        read.append("All candidates were rejected; the gate set is too strict or the sampling box misses the feasible region.")
    else:
        read.append("No candidates were rejected by this smoke; the gate set may be too weak for screening.")
    accepted_candidates = [item for item in report["candidates"] if item["status"] == "accepted"]
    if accepted_candidates:
        worst_outer = max(
            float(item["spanload_gate_health"]["max_outer_clmax_utilization"])
            for item in accepted_candidates
        )
        read.append(
            "Accepted top candidates keep outer-wing local cl/CLmax below "
            f"{worst_outer:.3f} in this proxy target calculation."
        )
    rejected_candidates = [item for item in report["candidates"] if item["status"] == "rejected"]
    if rejected_candidates:
        reasons = sorted({str(item["failing_gate"]["reason"]) for item in rejected_candidates if item.get("failing_gate")})
        read.append(f"Closest rejected candidates fail by {', '.join(reasons)}.")
    avl_ok = [
        item
        for item in report["candidates"]
        if item["avl_reference_case"].get("status") == "ok"
    ]
    if avl_ok:
        max_avl_delta = max(
            abs(float(row.get("target_minus_avl_circulation_norm", 0.0)))
            for item in avl_ok
            for row in item.get("station_table", [])
            if row.get("target_minus_avl_circulation_norm") is not None
        )
        read.append(
            "AVL strip loading is reported as a diagnostic cross-check; the largest normalized target-vs-AVL station delta among reported candidates is "
            f"{max_avl_delta:.3f}."
        )
        low_trust = [
            item
            for item in avl_ok
            if str(item.get("spanload_trust_status", "")).startswith("spanload_not_trusted")
        ]
        if low_trust:
            read.append(
                "Important: AVL e_CDi is much lower than target Fourier e, so the inverse-twist/spanload match is not yet trustworthy even for accepted geometry-gate candidates."
            )
        max_abs_twist = max(
            abs(float(row["twist_deg"]))
            for item in avl_ok
            for row in item.get("twist_distribution", [])
        )
        if max_abs_twist > 8.0:
            read.append(
                "Engineering caution: meeting the strip-loading target in this MVP required more than 8 deg of local flight twist/wash-in on at least one station; treat that as inverse-design evidence, not a buildable twist schedule yet."
            )
    read.append(
        "This smoke validates spanload geometry gates only; fixed seed airfoils and AVL linear trim are not a final low-Re stall or profile-drag authority."
    )
    return read


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/birdman_upstream_concept_baseline.yaml"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/birdman_spanload_design_smoke_20260503_fixed_airfoil"),
    )
    parser.add_argument("--accepted-count", type=int, default=3)
    parser.add_argument("--rejected-count", type=int, default=3)
    parser.add_argument("--design-speed-mps", type=float, default=None)
    parser.add_argument("--inverse-twist-iterations", type=int, default=4)
    parser.add_argument("--inverse-twist-correction-gain-deg", type=float, default=10.0)
    parser.add_argument(
        "--inverse-twist-max-abs-twist-deg",
        type=float,
        default=INVERSE_TWIST_MAX_ABS_TWIST_DEG,
    )
    parser.add_argument("--avl-binary", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_concept_config(args.config)
    design_speed_mps = _design_speed_mps(cfg, args.design_speed_mps)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    accepted = list(enumerate_geometry_concepts(cfg))
    diagnostics = get_last_geometry_enumeration_diagnostics()
    if diagnostics is None:
        raise RuntimeError("Geometry diagnostics were not populated.")

    accepted_metrics: list[dict[str, Any]] = []
    for index, concept in enumerate(accepted, start=1):
        accepted_metrics.append(
            _accepted_candidate_metric(
                cfg=cfg,
                concept=concept,
                sample_index=index,
                design_speed_mps=design_speed_mps,
            )
        )
    accepted_leaderboards = _select_accepted_leaderboards(
        accepted_metrics,
        per_board_count=int(args.accepted_count),
    )
    selected_accepted_samples = _selected_samples_from_leaderboards(accepted_leaderboards)
    accepted_by_sample = {int(record["sample_index"]): record for record in accepted_metrics}
    accepted_memberships = _leaderboard_memberships(accepted_leaderboards)

    spanload_rejections = [
        rejection
        for rejection in diagnostics.rejected_concepts
        if str(rejection.reason).startswith("spanload_design_")
    ]
    spanload_rejections.sort(key=lambda rejection: (_rejection_severity(rejection), rejection.sample_index))
    selected_rejected = spanload_rejections[: max(0, int(args.rejected_count))]

    records: list[dict[str, Any]] = []
    records_by_sample: dict[int, dict[str, Any]] = {}
    for index in selected_accepted_samples:
        metric = accepted_by_sample[index]
        records.append(
            _candidate_record(
                cfg=cfg,
                concept=metric["concept"],
                status="accepted",
                sample_index=index,
                rejection=None,
                output_dir=output_dir,
                design_speed_mps=design_speed_mps,
                avl_binary=args.avl_binary,
                leaderboard_memberships=accepted_memberships.get(index, []),
                inverse_twist_iterations=int(args.inverse_twist_iterations),
                inverse_twist_correction_gain_deg=float(
                    args.inverse_twist_correction_gain_deg
                ),
                inverse_twist_max_abs_twist_deg=float(
                    args.inverse_twist_max_abs_twist_deg
                ),
            )
        )
        records_by_sample[index] = records[-1]
    for rejection in selected_rejected:
        concept = _concept_from_rejection(cfg, rejection)
        if concept is None:
            continue
        records.append(
            _candidate_record(
                cfg=cfg,
                concept=concept,
                status="rejected",
                sample_index=int(rejection.sample_index),
                rejection=rejection,
                output_dir=output_dir,
                design_speed_mps=design_speed_mps,
                avl_binary=args.avl_binary,
                inverse_twist_iterations=int(args.inverse_twist_iterations),
                inverse_twist_correction_gain_deg=float(
                    args.inverse_twist_correction_gain_deg
                ),
                inverse_twist_max_abs_twist_deg=float(
                    args.inverse_twist_max_abs_twist_deg
                ),
            )
        )

    accepted_leaderboard_records = {
        board_name: [
            records_by_sample[int(metric["sample_index"])]
            for metric in metrics
            if int(metric["sample_index"]) in records_by_sample
        ]
        for board_name, metrics in accepted_leaderboards.items()
    }

    report: dict[str, Any] = {
        "schema_version": "birdman_spanload_design_smoke_v1",
        "config_path": str(args.config),
        "output_dir": str(output_dir),
        "route": "fixed_airfoil_inverse_twist_no_cst_no_xfoil",
        "fixed_airfoil_note": "AVL wing-only route uses the repo default fixed seed airfoils; no CST/XFOIL worker is invoked.",
        "candidate_selection_rule": (
            "accepted candidates are reported in three leaderboards: highest AR, "
            "best mission-power proxy, and lowest spanload utilization; "
            "rejected candidates are sorted by closest spanload gate violation"
        ),
        "success_criteria": {
            "max_target_avl_circulation_norm_delta_lt": SPANLOAD_DELTA_SUCCESS_LIMIT,
            "avl_e_cdi_ge": AVL_E_CDI_SUCCESS_FLOOR,
        },
        "design_cruise_case": {
            "case_label": CASE_LABEL,
            "speed_mps": float(design_speed_mps),
            "mass_kg": float(cfg.mass.design_gross_mass_kg),
            "mass_authority": "mass.design_gross_mass_kg",
            "speed_window_mps": [
                float(cfg.mission.speed_sweep_min_mps),
                float(cfg.mission.speed_sweep_max_mps),
            ],
        },
        "geometry_counts": {
            "requested": int(diagnostics.requested_sample_count),
            "accepted": int(diagnostics.accepted_concept_count),
            "rejected": int(diagnostics.rejected_concept_count),
            "rejection_reason_counts": dict(diagnostics.rejection_reason_counts),
        },
        "accepted_leaderboards": accepted_leaderboard_records,
        "candidates": records,
    }
    report["engineering_read"] = _engineering_read(report)

    json_path = output_dir / "spanload_design_smoke_report.json"
    md_path = output_dir / "spanload_design_smoke_report.md"
    json_path.write_text(json.dumps(_round(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_markdown_report(_round(report), md_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
