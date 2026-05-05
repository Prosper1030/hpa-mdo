#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import fields, replace
import json
import math
from pathlib import Path
import shutil
from typing import Any

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import minimize
from scipy.stats import qmc
import yaml

from hpa_mdo.aero.avl_spanwise import build_spanwise_load_from_avl_strip_forces
from hpa_mdo.aero.fourier_target import (
    FourierTarget,
    build_fourier_target,
    compare_fourier_target_to_avl,
)
from hpa_mdo.airfoils.database import (
    ProfileDragIntegrationResult,
    ZoneAirfoilAssignment,
    default_airfoil_database,
    fixed_seed_zone_airfoil_assignments,
    integrate_profile_drag_from_avl,
)
from hpa_mdo.airfoils.sidecar import (
    assignment_label,
    assignment_to_dicts,
    build_zone_envelopes,
    generate_airfoil_sidecar_combinations,
    query_zone_airfoil_topk,
    zone_envelopes_to_rows,
)
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
    WingStation,
    _fourier_spanload_shape,
    _fourier_spanload_ratio_to_ellipse,
    _lambda_min_from_tip_chord,
    build_linear_wing_stations,
    build_segment_plan,
)
from hpa_mdo.concept.jig_shape import estimate_tip_deflection
from hpa_mdo.concept.loaded_shape import (
    LoadedWingShape,
    build_loaded_wing_shape,
    build_loaded_wing_shape_from_stations,
)
from hpa_mdo.concept.mission_drag import compute_rigging_drag_cda_m2
from hpa_mdo.concept.outer_loading import (
    apply_outer_chord_redistribution,
)
from hpa_mdo.concept.pipeline import _sizing_diagnostics
from hpa_mdo.concept.vsp_export import write_concept_openvsp_handoff
from hpa_mdo.mission.contract import (
    MISSION_CONTRACT_SHADOW_FIELDS,
    MissionContract,
    build_mission_contract,
)
from hpa_mdo.mission.objective import build_rider_power_curve


G_MPS2 = 9.80665
CASE_LABEL = "spanload_smoke_reference_cruise"
FIXED_AIRFOIL_PROFILE_CD_PROXY = 0.018
INVERSE_TWIST_ZERO_LIFT_ALPHA_DEG = -3.0
INVERSE_TWIST_LIFT_CURVE_SLOPE_PER_RAD = 2.0 * math.pi
INVERSE_TWIST_MAX_AERO_ETA = 0.97
TWIST_CONTROL_ETAS = (0.0, 0.25, 0.45, 0.65, 0.82, 0.97)
TWIST_ROOT_ANCHOR_DEG = 2.0
TWIST_BOUNDS_DEG = (-4.5, 5.0)
TWIST_RANGE_LIMIT_DEG = 7.0
TWIST_ADJACENT_JUMP_LIMIT_DEG = 2.0
OUTER_WASHOUT_START_ETA = 0.45
OUTER_WASHIN_BUMP_START_ETA = 0.60
OUTER_WASHIN_BUMP_END_ETA = 0.85
OUTER_WASHIN_BUMP_LIMIT_ABOVE_ROOT_DEG = 2.0
TIP_MINUS_ETA70_WASHOUT_MIN_DEG = -0.8
SPANLOAD_DELTA_SUCCESS_LIMIT = 0.15
SPANLOAD_RMS_SUCCESS_LIMIT = 0.08
AVL_E_CDI_SUCCESS_FLOOR = 0.85
AVL_E_CDI_STRETCH_FLOOR = 0.90
SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE = "inverse_chord_then_inverse_twist"
SPANLOAD_TO_GEOMETRY_LINEAR_MODE = "linear_taper_then_inverse_twist"
STAGE0_SPAN_RANGE_M = (31.0, 35.0)
STAGE0_MEAN_CHORD_RANGE_M = (0.78, 1.05)
STAGE0_TAPER_SAMPLE_RANGE = (0.24, 0.42)
STAGE0_TAPER_UPPER_LIMIT = 0.42
STAGE0_TAIL_VOLUME_RANGE = (0.30, 0.55)
STAGE0_A3_RANGE = (-0.10, 0.0)
STAGE0_A5_RANGE = (-0.04, 0.04)
STAGE0_WING_AREA_RANGE_M2 = (26.0, 36.0)
STAGE0_AR_RANGE = (32.0, 45.0)
STAGE0_ROOT_CHORD_MIN_M = 1.05
INVERSE_CHORD_CL_CONTROL_ETAS = (0.0, 0.35, 0.70, 0.95)
INVERSE_CHORD_CL_CONTROL_BOUNDS = (
    (1.05, 1.25),
    (1.15, 1.40),
    (0.85, 1.15),
    (0.35, 0.85),
)
INVERSE_CHORD_STATION_ETAS = (0.0, 0.16, 0.35, 0.52, 0.70, 0.82, 0.90, 0.95, 1.0)
INVERSE_CHORD_PHYSICAL_TIP_CHORD_MIN_M = 0.43
INVERSE_CHORD_ROOT_CHORD_RANGE_M = (1.15, 1.45)
RESIDUAL_TWIST_MAX_ABS_DEG = 6.0

OUTER_CHORD_BUMP_AMP_RANGE = (0.0, 0.30)
"""Bounds for the stage-0 outer chord redistribution amplitude.

The standalone authority sweep showed +0.40 starts pressing the
``max_chord_second_difference`` gate (0.35 m) on sample 1476, so the
production Stage-1 search caps the variable at +0.30 to keep all chord
manufacturing gates in their existing thresholds.
"""

STAGE0_SAMPLE_DIMENSIONS = 9
DEFAULT_MISSION_SCREENER_SUMMARY_PATH = Path("output/mission_design_space/summary.json")
DEFAULT_MISSION_OPTIMIZER_HANDOFF_PATH = Path("output/mission_design_space/optimizer_handoff.json")
DEFAULT_MISSION_DRAG_BUDGET_CONFIG_PATH = Path("configs/mission_drag_budget_example.yaml")
MISSION_FOURIER_TARGET_ETA_GRID = tuple(float(value) for value in np.linspace(0.0, 1.0, 81))
MISSION_FOURIER_SHADOW_FIELDS = (
    "mission_fourier_e_target",
    "mission_fourier_r3",
    "mission_fourier_r5",
    "mission_fourier_cl_max",
    "mission_fourier_outer_lift_ratio",
    "mission_fourier_root_bending_proxy",
    "target_vs_avl_rms_delta",
    "target_vs_avl_max_delta",
    "target_vs_avl_outer_delta",
)
AIRFOIL_PROFILE_DRAG_SHADOW_FIELDS = (
    "profile_cd_airfoil_db",
    "profile_cd_airfoil_db_source_quality",
    "cd0_total_est_airfoil_db",
    "mission_drag_budget_band_airfoil_db",
    "profile_drag_station_warning_count",
    "min_stall_margin_airfoil_db",
    "max_station_cl_utilization_airfoil_db",
    "profile_drag_cl_source_shape_mode",
    "profile_drag_cl_source_loaded_shape",
    "profile_drag_cl_source_warning_count",
)
AIRFOIL_SIDECAR_SHADOW_FIELDS = (
    "sidecar_best_airfoil_assignment",
    "sidecar_best_e_CDi",
    "sidecar_best_target_vs_avl_rms",
    "sidecar_best_target_vs_avl_outer_delta",
    "sidecar_best_profile_cd",
    "sidecar_best_cd0_total_est",
    "sidecar_best_min_stall_margin",
    "sidecar_best_source_quality",
    "sidecar_improved_vs_baseline",
    "sidecar_improvement_notes",
)
LOADED_SHAPE_JIG_SHADOW_FIELDS = (
    "loaded_shape_mode",
    "loaded_tip_dihedral_deg",
    "loaded_tip_z_m",
    "loaded_shape_source",
    "jig_feasible_shadow",
    "jig_feasibility_band",
    "jig_tip_deflection_m",
    "jig_tip_deflection_ratio",
    "jig_effective_dihedral_deg",
    "jig_tip_deflection_preferred_status",
    "jig_warning_count",
)


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


def _numeric_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    return None


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


def _geometry_summary(concept: GeometryConcept) -> dict[str, Any]:
    return {
        "span_m": float(concept.span_m),
        "wing_area_m2": float(concept.wing_area_m2),
        "aspect_ratio": float(concept.aspect_ratio),
        "taper_ratio": float(concept.taper_ratio),
        "root_chord_m": float(concept.root_chord_m),
        "tip_chord_m": float(concept.tip_chord_m),
        "mean_chord_m": float(concept.wing_area_m2 / max(concept.span_m, 1.0e-9)),
        "mean_aerodynamic_chord_m": float(concept.mean_aerodynamic_chord_m),
        "dihedral_root_deg": float(concept.dihedral_root_deg),
        "dihedral_tip_deg": float(concept.dihedral_tip_deg),
        "dihedral_exponent": float(concept.dihedral_exponent),
        "design_gross_mass_kg": concept.design_gross_mass_kg,
        "tip_deflection_m_at_design_mass": concept.tip_deflection_m_at_design_mass,
        "tip_deflection_ratio_at_design_mass": concept.tip_deflection_ratio_at_design_mass,
        "effective_dihedral_deg_at_design_mass": (
            concept.effective_dihedral_deg_at_design_mass
        ),
        "unbraced_tip_deflection_m_at_design_mass": (
            concept.unbraced_tip_deflection_m_at_design_mass
        ),
        "lift_wire_relief_deflection_m_at_design_mass": (
            concept.lift_wire_relief_deflection_m_at_design_mass
        ),
        "tip_deflection_preferred_status": concept.tip_deflection_preferred_status,
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


def _chord_at_eta_from_stations(
    stations: tuple[WingStation, ...] | None,
    concept: GeometryConcept,
    eta: float,
) -> float:
    if not stations:
        return _linear_chord_at_eta(concept, eta)
    etas = _station_etas(stations)
    chords = [float(station.chord_m) for station in stations]
    return _linear_interp(tuple(etas), tuple(chords), float(eta))


def _tip_required_chord_m_for_speed(
    cfg: BirdmanConceptConfig,
    *,
    design_speed_mps: float,
) -> float:
    constraints = cfg.geometry_family.hard_constraints
    tip_protection = cfg.geometry_family.planform_tip_protection
    if not bool(tip_protection.enabled):
        return float(constraints.tip_chord_min_m)
    air = _air_properties(cfg)
    re_based_min_m = (
        float(tip_protection.tip_re_abs_min)
        * float(air.dynamic_viscosity_pa_s)
        / max(float(air.density_kg_per_m3) * float(design_speed_mps), 1.0e-9)
    )
    spar_based_min_m = float(tip_protection.tip_spar_depth_min_m) / max(
        float(tip_protection.tip_structural_tc_ratio),
        1.0e-9,
    )
    return max(
        float(constraints.tip_chord_min_m),
        float(tip_protection.tip_chord_abs_min_m),
        float(re_based_min_m),
        float(spar_based_min_m),
    )


def _tip_preferred_chord_m_for_speed(
    cfg: BirdmanConceptConfig,
    *,
    design_speed_mps: float,
) -> float:
    tip_protection = cfg.geometry_family.planform_tip_protection
    if not bool(tip_protection.enabled):
        return _tip_required_chord_m_for_speed(cfg, design_speed_mps=design_speed_mps)
    air = _air_properties(cfg)
    preferred_re_min_m = (
        float(tip_protection.tip_re_preferred_min)
        * float(air.dynamic_viscosity_pa_s)
        / max(float(air.density_kg_per_m3) * float(design_speed_mps), 1.0e-9)
    )
    return max(
        float(tip_protection.tip_chord_preferred_min_m),
        float(preferred_re_min_m),
        _tip_required_chord_m_for_speed(cfg, design_speed_mps=design_speed_mps),
    )


def _tip_gate_summary(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    design_speed_mps: float,
    stations: tuple[WingStation, ...] | None = None,
) -> dict[str, Any]:
    tip_protection = cfg.geometry_family.planform_tip_protection
    air = _air_properties(cfg)
    eta = float(tip_protection.aerodynamic_tip_station_eta)
    chord_eta_m = _chord_at_eta_from_stations(stations, concept, eta)
    tip_re = (
        float(air.density_kg_per_m3)
        * float(design_speed_mps)
        * float(chord_eta_m)
        / max(float(air.dynamic_viscosity_pa_s), 1.0e-12)
    )
    tip_spar_depth_m = float(concept.tip_chord_m) * float(
        tip_protection.tip_structural_tc_ratio
    )
    required_chord_m = _tip_required_chord_m_for_speed(
        cfg,
        design_speed_mps=design_speed_mps,
    )
    preferred_chord_m = _tip_preferred_chord_m_for_speed(
        cfg,
        design_speed_mps=design_speed_mps,
    )
    failures: list[str] = []
    warnings: list[str] = []
    if float(concept.tip_chord_m) + 1.0e-9 < required_chord_m:
        failures.append("tip_chord_below_required")
    if chord_eta_m + 1.0e-9 < float(tip_protection.require_chord_at_eta_0p95_min_m):
        failures.append("aerodynamic_tip_chord_below_required")
    if tip_re < float(tip_protection.tip_re_abs_min):
        failures.append("tip_re_below_abs_min")
    if tip_spar_depth_m + 1.0e-9 < float(tip_protection.tip_spar_depth_min_m):
        failures.append("tip_spar_depth_below_min")
    if float(concept.tip_chord_m) < preferred_chord_m:
        warnings.append("tip_chord_below_preferred")
    if tip_re < float(tip_protection.tip_re_preferred_min):
        warnings.append("tip_re_below_preferred")
    return {
        "tip_gates_pass": not failures,
        "tip_gate_failures": failures,
        "tip_gate_warnings": warnings,
        "tip_chord_m": float(concept.tip_chord_m),
        "tip_required_chord_m": float(required_chord_m),
        "tip_preferred_chord_m": float(preferred_chord_m),
        "aerodynamic_tip_station_eta": float(eta),
        "chord_at_aerodynamic_tip_eta_m": float(chord_eta_m),
        "chord_at_aerodynamic_tip_eta_min_m": float(
            tip_protection.require_chord_at_eta_0p95_min_m
        ),
        "tip_re": float(tip_re),
        "tip_re_abs_min": float(tip_protection.tip_re_abs_min),
        "tip_re_preferred_min": float(tip_protection.tip_re_preferred_min),
        "tip_spar_depth_m": float(tip_spar_depth_m),
        "tip_spar_depth_min_m": float(tip_protection.tip_spar_depth_min_m),
        "tip_structural_tc_ratio": float(tip_protection.tip_structural_tc_ratio),
    }


def _linear_interp(xs: list[float] | tuple[float, ...], ys: list[float] | tuple[float, ...], x: float) -> float:
    x_clamped = min(max(float(x), float(xs[0])), float(xs[-1]))
    for left_i, right_i in zip(range(len(xs) - 1), range(1, len(xs)), strict=True):
        x_left = float(xs[left_i])
        x_right = float(xs[right_i])
        if x_left <= x_clamped <= x_right:
            span = max(x_right - x_left, 1.0e-9)
            frac = (x_clamped - x_left) / span
            return float(ys[left_i]) + frac * (float(ys[right_i]) - float(ys[left_i]))
    return float(ys[-1])


def _stations_from_twist_controls(
    *,
    base_stations: tuple[WingStation, ...],
    control_twists_deg: tuple[float, ...] | list[float],
) -> tuple[WingStation, ...]:
    if len(control_twists_deg) != len(TWIST_CONTROL_ETAS):
        raise ValueError("control_twists_deg must match TWIST_CONTROL_ETAS.")
    half_span_m = max(float(base_stations[-1].y_m), 1.0e-9)
    stations: list[WingStation] = []
    for station in base_stations:
        eta = min(max(float(station.y_m) / half_span_m, 0.0), 1.0)
        twist_deg = _linear_interp(TWIST_CONTROL_ETAS, tuple(control_twists_deg), min(eta, TWIST_CONTROL_ETAS[-1]))
        stations.append(
            WingStation(
                y_m=float(station.y_m),
                chord_m=float(station.chord_m),
                twist_deg=float(twist_deg),
                dihedral_deg=float(station.dihedral_deg),
            )
        )
    return tuple(stations)


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
    chord_m: float | None = None,
) -> dict[str, float]:
    eta_clamped = min(max(float(eta), 0.0), 1.0)
    shape = _fourier_spanload_shape(
        a3_over_a1=float(concept.spanload_a3_over_a1),
        a5_over_a1=float(concept.spanload_a5_over_a1),
        eta=eta_clamped,
    )
    local_chord_m = (
        _linear_chord_at_eta(concept, eta_clamped)
        if chord_m is None
        else float(chord_m)
    )
    local_cl = float(solution["cl_scale"]) * float(shape) / max(local_chord_m, 1.0e-9)
    target_circulation_proxy = 0.5 * float(solution["design_speed_mps"]) * local_chord_m * local_cl
    return {
        "eta": float(eta_clamped),
        "chord_m": float(local_chord_m),
        "shape": float(shape),
        "target_circulation_norm": float(shape / max(float(solution["max_shape"]), 1.0e-9)),
        "target_circulation_proxy": float(target_circulation_proxy),
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
        chord_m = _chord_at_eta_from_stations(stations, concept, eta)
        local = _target_local_record_at_eta(
            concept=concept,
            solution=solution,
            eta=eta,
            chord_m=chord_m,
        )
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
        local = _target_local_record_at_eta(
            concept=concept,
            solution=solution,
            eta=eta,
            chord_m=chord_m,
        )
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
            "target_circulation_proxy": float(local["target_circulation_proxy"]),
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
        local = _target_local_record_at_eta(
            concept=concept,
            solution=solution,
            eta=eta,
            chord_m=float(station.chord_m),
        )
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
                "target_circulation_proxy": float(local["target_circulation_proxy"]),
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
    solution = _target_spanload_solution(
        cfg=cfg,
        concept=concept,
        design_speed_mps=design_speed_mps,
    )
    design_cl = float(solution["design_cl"])
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
    proxy = _power_proxy_from_cdi(
        cfg=cfg,
        concept=concept,
        design_speed_mps=design_speed_mps,
        induced_cd=float(induced_cd),
        model="fixed_airfoil_target_fourier_drag_proxy_v1",
    )
    return {
        **proxy,
        "design_cl": float(design_cl),
        "target_fourier_e": float(target_e),
    }


def _pilot_available_power_w(cfg: BirdmanConceptConfig, *, duration_s: float) -> float:
    curve = build_rider_power_curve(
        anchor_power_w=float(cfg.mission.anchor_power_w),
        anchor_duration_min=float(cfg.mission.anchor_duration_min),
        rider_power_curve_csv=cfg.mission.rider_power_curve_csv,
        rider_power_curve_metadata_yaml=cfg.mission.rider_power_curve_metadata_yaml,
        rider_model=str(cfg.mission.rider_model),
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
    return float(curve.power_at_duration_min(float(duration_s) / 60.0))


def _power_proxy_from_cdi(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    design_speed_mps: float,
    induced_cd: float,
    model: str,
) -> dict[str, float | str | bool]:
    air = _air_properties(cfg)
    q_pa = 0.5 * float(air.density_kg_per_m3) * float(design_speed_mps) ** 2
    design_cl = (
        float(cfg.mass.design_gross_mass_kg)
        * G_MPS2
        / max(q_pa * float(concept.wing_area_m2), 1.0e-9)
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
    total_cd = float(induced_cd) + profile_cd + misc_cd + rigging_cd
    drag_n = q_pa * float(concept.wing_area_m2) * total_cd
    shaft_power_w = drag_n * float(design_speed_mps) / max(
        float(cfg.prop.efficiency_model.design_efficiency),
        1.0e-9,
    )
    pedal_power_w = shaft_power_w / max(float(cfg.drivetrain.efficiency), 1.0e-9)
    duration_s = float(cfg.mission.target_distance_km) * 1000.0 / max(
        float(design_speed_mps),
        1.0e-9,
    )
    available_power_w = _pilot_available_power_w(cfg, duration_s=duration_s)
    return {
        "model": str(model),
        "profile_drag_note": "fixed_airfoil_no_xfoil_not_final_profile_drag",
        "speed_mps": float(design_speed_mps),
        "mass_kg": float(cfg.mass.design_gross_mass_kg),
        "duration_s": float(duration_s),
        "duration_min": float(duration_s / 60.0),
        "available_power_w": float(available_power_w),
        "power_required_w": float(pedal_power_w),
        "shaft_power_required_w": float(shaft_power_w),
        "power_margin_w": float(available_power_w - pedal_power_w),
        "non_catastrophic_power_margin_report": bool(math.isfinite(available_power_w - pedal_power_w)),
        "drag_n": float(drag_n),
        "design_cl": float(design_cl),
        "induced_cd": float(induced_cd),
        "profile_cd": float(profile_cd),
        "misc_cd": float(misc_cd),
        "rigging_cd": float(rigging_cd),
        "total_cd": float(total_cd),
    }


def _merge_context(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_context(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _read_mapping_file(path: Path) -> dict[str, Any] | None:
    if path is None or not Path(path).is_file():
        return None
    try:
        if Path(path).suffix.lower() in {".yaml", ".yml"}:
            loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        else:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def _mission_contract_shadow_context(
    *,
    cfg: BirdmanConceptConfig,
    summary_path: Path | None,
    optimizer_handoff_path: Path | None,
    drag_budget_config_path: Path | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "mission_context": {
            "target_range_km": float(cfg.mission.target_distance_km),
            "target_environment": {
                "temperature_c": float(cfg.environment.temperature_c),
                "relative_humidity_percent": float(cfg.environment.relative_humidity),
            },
        },
        "mission_gate": {
            "robust_power_margin_crank_w_min": 5.0,
        },
        "propulsion_budget": {
            "eta_prop_target": float(cfg.prop.efficiency_model.design_efficiency),
            "eta_trans": float(cfg.drivetrain.efficiency),
        },
    }
    source_parts = ["concept_config"]
    path_records: dict[str, str] = {}
    for source_name, path in (
        ("summary_json", summary_path),
        ("optimizer_handoff_json", optimizer_handoff_path),
        ("mission_drag_budget_yaml", drag_budget_config_path),
    ):
        if path is None:
            continue
        loaded = _read_mapping_file(Path(path))
        if loaded is None:
            continue
        context = _merge_context(context, loaded)
        source_parts.append(source_name)
        path_records[source_name] = str(path)
    context["mission_contract_source"] = "+".join(source_parts)
    context["mission_contract_source_paths"] = path_records
    return context


def _mission_contract_seed_row(
    *,
    record: dict[str, Any],
    cfg: BirdmanConceptConfig,
    design_speed_mps: float,
) -> dict[str, Any]:
    geometry = record.get("geometry", {})
    power = record.get("avl_cdi_power_proxy") or record.get("target_fourier_power_proxy") or {}
    air = _air_properties(cfg)
    spanload_cfg = cfg.geometry_family.spanload_design
    return {
        "speed_mps": power.get("speed_mps", design_speed_mps),
        "span_m": geometry.get("span_m"),
        "aspect_ratio": geometry.get("aspect_ratio"),
        "mass_kg": power.get("mass_kg", cfg.mass.design_gross_mass_kg),
        "rho": float(air.density_kg_per_m3),
        "eta_prop": float(cfg.prop.efficiency_model.design_efficiency),
        "eta_trans": float(cfg.drivetrain.efficiency),
        "pilot_power_hot_w": power.get("available_power_w"),
        "CLmax_effective_assumption": float(spanload_cfg.local_clmax_safe_floor),
    }


def _attach_mission_contract_shadow_fields(
    records: list[dict[str, Any]],
    *,
    cfg: BirdmanConceptConfig,
    design_speed_mps: float,
    context: dict[str, Any],
) -> None:
    for record in records:
        try:
            contract = build_mission_contract(
                _mission_contract_seed_row(
                    record=record,
                    cfg=cfg,
                    design_speed_mps=design_speed_mps,
                ),
                context,
            )
        except Exception as exc:  # noqa: BLE001 - keep smoke route non-gating.
            record["mission_contract"] = {
                "source_mode": "shadow_no_ranking_gate",
                "mission_contract_source": str(
                    context.get("mission_contract_source", "unknown")
                ),
                "error": f"{type(exc).__name__}: {exc}",
            }
            for field in MISSION_CONTRACT_SHADOW_FIELDS:
                record[field] = (
                    record["mission_contract"]["mission_contract_source"]
                    if field == "mission_contract_source"
                    else None
                )
            continue
        record["mission_contract"] = contract.to_dict()
        record.update(contract.to_shadow_fields())


def _station_etas_from_record(record: dict[str, Any]) -> tuple[float, ...]:
    station_table = record.get("station_table") or []
    eta_values: list[float] = []
    for row in station_table:
        if not isinstance(row, dict):
            continue
        eta_value = _numeric_value(row.get("eta"))
        if eta_value is not None:
            eta_values.append(min(max(float(eta_value), 0.0), 1.0))
    if eta_values:
        return tuple(eta_values)
    return (0.0, 1.0)


def _loaded_shape_from_record(record: dict[str, Any]) -> LoadedWingShape:
    geometry = record.get("geometry") or {}
    span_m = _numeric_value(geometry.get("span_m"))
    if span_m is None or span_m <= 0.0:
        raise ValueError("geometry.span_m is unavailable")
    station_table = record.get("station_table") or []
    station_shape_inputs: list[WingStation] = []
    for row in station_table:
        if not isinstance(row, dict):
            continue
        y_m = _numeric_value(row.get("y_m"))
        dihedral_deg = _numeric_value(row.get("dihedral_deg"))
        if y_m is None or dihedral_deg is None:
            continue
        station_shape_inputs.append(
            WingStation(
                y_m=float(y_m),
                chord_m=float(_numeric_value(row.get("chord_m")) or 1.0),
                twist_deg=float(
                    _numeric_value(row.get("twist_deg"))
                    or _numeric_value(row.get("ainc_deg"))
                    or 0.0
                ),
                dihedral_deg=float(dihedral_deg),
            )
        )
    if len(station_shape_inputs) >= 2:
        return build_loaded_wing_shape_from_stations(
            span_m=float(span_m),
            stations=tuple(station_shape_inputs),
            source="station_table_dihedral_fields_shadow",
        )

    tip_dihedral_deg = _numeric_value(geometry.get("dihedral_tip_deg"))
    if tip_dihedral_deg is None:
        tip_dihedral_deg = 0.0
    dihedral_exponent = _numeric_value(geometry.get("dihedral_exponent"))
    mode = (
        "flat"
        if abs(float(tip_dihedral_deg)) <= 1.0e-9
        else "concept_dihedral_fields"
    )
    return build_loaded_wing_shape(
        span_m=float(span_m),
        eta=_station_etas_from_record(record),
        loaded_tip_dihedral_deg=float(tip_dihedral_deg),
        dihedral_exponent=dihedral_exponent or 1.0,
        loaded_shape_mode=mode,
        source="candidate_geometry_dihedral_fields_shadow",
    )


def _tip_deflection_preferred_status(
    *,
    tip_deflection_m: float | None,
    cfg: BirdmanConceptConfig | None,
    fallback_status: object = None,
) -> str | None:
    if isinstance(fallback_status, str) and fallback_status:
        return fallback_status
    if tip_deflection_m is None or cfg is None:
        return None
    lower = float(cfg.jig_shape_gate.preferred_tip_deflection_m_min)
    upper = float(cfg.jig_shape_gate.preferred_tip_deflection_m_max)
    if tip_deflection_m < lower:
        return "below_preferred"
    if tip_deflection_m > upper:
        return "above_preferred"
    return "within_preferred"


def _jig_feasibility_band(
    *,
    feasible: bool | None,
    preferred_status: str | None,
    ratio: float | None,
    cfg: BirdmanConceptConfig | None,
) -> str:
    if feasible is None or ratio is None:
        return "unknown_placeholder"
    if feasible is False:
        return "above_limit"
    if preferred_status == "within_preferred":
        return "preferred_window"
    if preferred_status == "below_preferred":
        return "feasible_below_preferred"
    if preferred_status == "above_preferred":
        return "feasible_above_preferred"
    if cfg is not None and ratio <= float(cfg.jig_shape_gate.max_tip_deflection_to_halfspan_ratio):
        return "feasible"
    return "unknown"


def _jig_shadow_from_record(
    record: dict[str, Any],
    *,
    cfg: BirdmanConceptConfig | None,
) -> dict[str, Any]:
    geometry = record.get("geometry") or {}
    span_m = _numeric_value(geometry.get("span_m"))
    mass_kg = _numeric_value(geometry.get("design_gross_mass_kg"))
    warnings: list[str] = []

    estimate = None
    if cfg is not None and span_m is not None and span_m > 0.0:
        try:
            estimate = estimate_tip_deflection(
                gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
                span_m=float(span_m),
                tube_geom=cfg.mass_closure.tube_system,
                gate_cfg=cfg.jig_shape_gate,
            )
            mass_kg = float(cfg.mass.design_gross_mass_kg)
        except Exception as exc:  # noqa: BLE001 - shadow-only structural provenance.
            warnings.append(f"estimate_tip_deflection_failed:{type(exc).__name__}")

    if estimate is not None:
        tip_deflection_m = float(estimate.tip_deflection_m)
        ratio = float(estimate.tip_deflection_ratio)
        effective_dihedral_deg = float(estimate.effective_dihedral_deg)
        unbraced_tip_deflection_m = float(estimate.unbraced_tip_deflection_m)
        lift_wire_relief_deflection_m = float(estimate.lift_wire_relief_deflection_m)
        source_quality = "concept_jig_shape_estimate_tip_deflection_shadow"
    else:
        tip_deflection_m = _numeric_value(
            geometry.get("tip_deflection_m_at_design_mass")
        )
        ratio = _numeric_value(geometry.get("tip_deflection_ratio_at_design_mass"))
        effective_dihedral_deg = _numeric_value(
            geometry.get("effective_dihedral_deg_at_design_mass")
        )
        unbraced_tip_deflection_m = _numeric_value(
            geometry.get("unbraced_tip_deflection_m_at_design_mass")
        )
        lift_wire_relief_deflection_m = _numeric_value(
            geometry.get("lift_wire_relief_deflection_m_at_design_mass")
        )
        source_quality = (
            "concept_jig_shape_estimate_tip_deflection_shadow"
            if ratio is not None
            else "placeholder_not_structure_grade"
        )
        if ratio is None:
            warnings.append("jig_shape_estimate_unavailable")

    feasible: bool | None
    if ratio is None:
        feasible = None
    elif cfg is None:
        feasible = None
        warnings.append("jig_shape_gate_config_unavailable")
    else:
        feasible = bool(
            ratio <= float(cfg.jig_shape_gate.max_tip_deflection_to_halfspan_ratio)
        )
    preferred_status = _tip_deflection_preferred_status(
        tip_deflection_m=tip_deflection_m,
        cfg=cfg,
        fallback_status=geometry.get("tip_deflection_preferred_status"),
    )
    band = _jig_feasibility_band(
        feasible=feasible,
        preferred_status=preferred_status,
        ratio=ratio,
        cfg=cfg,
    )
    return {
        "source": "jig_feasibility_shadow_v1",
        "source_mode": "shadow_no_ranking_gate",
        "jig_source_quality": source_quality,
        "design_mass_kg": mass_kg,
        "tip_deflection_m_at_design_mass": tip_deflection_m,
        "tip_deflection_ratio_at_design_mass": ratio,
        "effective_dihedral_deg_at_design_mass": effective_dihedral_deg,
        "unbraced_tip_deflection_m_at_design_mass": unbraced_tip_deflection_m,
        "lift_wire_relief_deflection_m_at_design_mass": lift_wire_relief_deflection_m,
        "tip_deflection_preferred_status": preferred_status,
        "jig_feasible_shadow": feasible,
        "jig_feasibility_band": band,
        "warnings": warnings,
        "warning_count": len(warnings),
    }


def _attach_loaded_shape_jig_shadow_fields(
    records: list[dict[str, Any]],
    *,
    cfg: BirdmanConceptConfig | None = None,
) -> None:
    for record in records:
        try:
            loaded_shape = _loaded_shape_from_record(record)
            record["loaded_wing_shape"] = loaded_shape.to_dict()
            loaded_shape_fields = {
                "loaded_shape_mode": loaded_shape.loaded_shape_mode,
                "loaded_tip_dihedral_deg": float(loaded_shape.loaded_tip_dihedral_deg),
                "loaded_tip_z_m": float(loaded_shape.loaded_tip_z_m),
                "loaded_shape_source": loaded_shape.source,
            }
        except Exception as exc:  # noqa: BLE001 - loaded shape is shadow-only here.
            record["loaded_wing_shape"] = {
                "source": "loaded_wing_shape_shadow_v1",
                "source_mode": "shadow_no_ranking_gate",
                "error": f"{type(exc).__name__}: {exc}",
                "warnings": ["loaded_shape_unavailable"],
            }
            loaded_shape_fields = {
                "loaded_shape_mode": None,
                "loaded_tip_dihedral_deg": None,
                "loaded_tip_z_m": None,
                "loaded_shape_source": "loaded_wing_shape_unavailable",
            }

        jig = _jig_shadow_from_record(record, cfg=cfg)
        record["jig_feasibility"] = jig
        record.update(
            {
                **loaded_shape_fields,
                "jig_feasible_shadow": jig.get("jig_feasible_shadow"),
                "jig_feasibility_band": jig.get("jig_feasibility_band"),
                "jig_tip_deflection_m": jig.get("tip_deflection_m_at_design_mass"),
                "jig_tip_deflection_ratio": jig.get(
                    "tip_deflection_ratio_at_design_mass"
                ),
                "jig_effective_dihedral_deg": jig.get(
                    "effective_dihedral_deg_at_design_mass"
                ),
                "jig_tip_deflection_preferred_status": jig.get(
                    "tip_deflection_preferred_status"
                ),
                "jig_warning_count": int(jig.get("warning_count", 0)),
                "jig_source_quality": jig.get("jig_source_quality"),
            }
        )


def _attach_mission_fourier_shadow_fields(records: list[dict[str, Any]]) -> None:
    for record in records:
        try:
            contract = _mission_contract_from_record(record)
            if contract is None:
                raise ValueError("mission_contract is unavailable")
            r3 = float(record.get("spanload_fourier", {}).get("a3_over_a1", 0.0))
            r5 = float(record.get("spanload_fourier", {}).get("a5_over_a1", 0.0))
            target = build_fourier_target(
                contract,
                _mission_fourier_chord_ref(record, MISSION_FOURIER_TARGET_ETA_GRID),
                MISSION_FOURIER_TARGET_ETA_GRID,
                r3=r3,
                r5=r5,
            )
            comparison = compare_fourier_target_to_avl(target, record.get("station_table") or [])
        except Exception as exc:  # noqa: BLE001 - shadow diagnostics must not gate the route.
            record["mission_fourier_target"] = {
                "source": "mission_contract_fourier_target_v2_shadow_no_ranking_gate",
                "source_mode": "shadow_no_ranking_gate",
                "error": f"{type(exc).__name__}: {exc}",
            }
            record["mission_fourier_comparison"] = {
                "target_vs_avl_compare_success": False,
                "target_vs_avl_compare_reason": "mission_fourier_target_failed",
                "target_vs_avl_error": f"{type(exc).__name__}: {exc}",
            }
            for field in MISSION_FOURIER_SHADOW_FIELDS:
                record[field] = None
            continue

        record["mission_fourier_target"] = target.to_dict()
        record["mission_fourier_comparison"] = comparison
        record.update(
            {
                "mission_fourier_e_target": float(target.e_theory),
                "mission_fourier_r3": float(target.r3),
                "mission_fourier_r5": float(target.r5),
                "mission_fourier_cl_max": float(target.cl_max),
                "mission_fourier_outer_lift_ratio": float(
                    target.outer_lift_ratio_vs_ellipse
                ),
                "mission_fourier_root_bending_proxy": float(target.root_bending_proxy),
                "target_vs_avl_rms_delta": comparison.get("target_vs_avl_rms_delta"),
                "target_vs_avl_max_delta": comparison.get("target_vs_avl_max_delta"),
                "target_vs_avl_outer_delta": comparison.get("target_vs_avl_outer_delta"),
            }
        )


def _attach_airfoil_profile_drag_shadow_fields(records: list[dict[str, Any]]) -> None:
    database = default_airfoil_database()
    assignments = fixed_seed_zone_airfoil_assignments()
    for record in records:
        avl_reference = record.get("avl_reference_case") or {}
        cl_source_shape_mode = str(
            avl_reference.get(
                "profile_drag_cl_source_shape_mode",
                "flat_or_unverified_loaded_shape",
            )
        )
        cl_source_loaded_shape = bool(
            avl_reference.get(
                "profile_drag_cl_source_loaded_shape",
                cl_source_shape_mode == "loaded_dihedral_avl",
            )
        )
        cl_source_warning_count = int(
            avl_reference.get(
                "profile_drag_cl_source_warning_count",
                0 if cl_source_loaded_shape else 1,
            )
        )
        if not cl_source_loaded_shape and cl_source_warning_count == 0:
            cl_source_warning_count = 1
        try:
            contract = _mission_contract_from_record(record)
            if contract is None:
                raise ValueError("mission_contract is unavailable")
            result = integrate_profile_drag_from_avl(
                contract,
                record.get("station_table") or [],
                record.get("station_table") or [],
                assignments,
                database,
                cl_source_shape_mode=cl_source_shape_mode,
                cl_source_loaded_shape=cl_source_loaded_shape,
                cl_source_warning_count=cl_source_warning_count,
            )
        except Exception as exc:  # noqa: BLE001 - profile drag database is shadow-only.
            record["airfoil_profile_drag"] = {
                "source": "airfoil_database_profile_drag_shadow_v1",
                "source_mode": "shadow_no_ranking_gate",
                "error": f"{type(exc).__name__}: {exc}",
                "profile_drag_cl_source_shape_mode": cl_source_shape_mode,
                "profile_drag_cl_source_loaded_shape": bool(cl_source_loaded_shape),
                "profile_drag_cl_source_warning_count": int(cl_source_warning_count),
                "zone_airfoil_assignment": [
                    assignment.to_dict() for assignment in assignments
                ],
            }
            for field in AIRFOIL_PROFILE_DRAG_SHADOW_FIELDS:
                record[field] = None
            record["profile_drag_cl_source_shape_mode"] = cl_source_shape_mode
            record["profile_drag_cl_source_loaded_shape"] = bool(cl_source_loaded_shape)
            record["profile_drag_cl_source_warning_count"] = int(cl_source_warning_count)
            continue

        record["airfoil_profile_drag"] = result.to_dict()
        record.update(
            {
                "profile_cd_airfoil_db": float(result.CD_profile),
                "profile_cd_airfoil_db_source_quality": result.source_quality,
                "cd0_total_est_airfoil_db": float(result.cd0_total_est),
                "mission_drag_budget_band_airfoil_db": result.drag_budget_band,
                "profile_drag_station_warning_count": int(result.station_warning_count),
                "min_stall_margin_airfoil_db": result.min_stall_margin_deg,
                "max_station_cl_utilization_airfoil_db": (
                    None
                    if result.max_station_cl_utilization is None
                    else float(result.max_station_cl_utilization)
                ),
                "profile_drag_cl_source_shape_mode": (
                    result.profile_drag_cl_source_shape_mode
                ),
                "profile_drag_cl_source_loaded_shape": bool(
                    result.profile_drag_cl_source_loaded_shape
                ),
                "profile_drag_cl_source_warning_count": int(
                    result.profile_drag_cl_source_warning_count
                ),
            }
        )


def _airfoil_geometry_path(airfoil_id: str) -> Path | None:
    mapping = {
        "fx76mp140": Path("data/airfoils/fx76mp140.dat"),
        "clarkysm": Path("data/airfoils/clarkysm.dat"),
        "dae11": Path("docs/research/historical_airfoil_cst_coverage/airfoils/dae11.dat"),
        "dae21": Path("docs/research/historical_airfoil_cst_coverage/airfoils/dae21.dat"),
        "dae31": Path("docs/research/historical_airfoil_cst_coverage/airfoils/dae31.dat"),
        "dae41": Path("docs/research/historical_airfoil_cst_coverage/airfoils/dae41.dat"),
    }
    path = mapping.get(str(airfoil_id))
    if path is None:
        return None
    resolved = path.resolve()
    return resolved if resolved.is_file() else None


def _zone_airfoil_paths_from_assignment(
    assignments: tuple[ZoneAirfoilAssignment, ...],
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for assignment in assignments:
        path = _airfoil_geometry_path(assignment.airfoil_id)
        if path is None:
            raise FileNotFoundError(f"Missing airfoil geometry for {assignment.airfoil_id}")
        paths[str(assignment.zone_name)] = path
    return paths


def _sidecar_available_airfoil_ids() -> tuple[str, ...]:
    return tuple(
        airfoil_id
        for airfoil_id in ("fx76mp140", "clarkysm", "dae11", "dae21", "dae31", "dae41")
        if _airfoil_geometry_path(airfoil_id) is not None
    )


def _sidecar_stations_from_record(record: dict[str, Any]) -> tuple[WingStation, ...]:
    rows = [
        row for row in record.get("station_table") or [] if isinstance(row, dict)
    ]
    rows.sort(key=lambda row: float(row.get("y_m", row.get("y", 0.0)) or 0.0))
    stations: list[WingStation] = []
    for row in rows:
        y_m = _float_or_none(row.get("y_m", row.get("y")))
        chord_m = _float_or_none(row.get("chord_m", row.get("chord")))
        if y_m is None or chord_m is None or chord_m <= 0.0:
            continue
        twist_deg = _float_or_none(row.get("ainc_deg"))
        if twist_deg is None:
            twist_deg = _float_or_none(row.get("twist_deg"))
        if twist_deg is None:
            twist_deg = 0.0
        dihedral_deg = _float_or_none(row.get("dihedral_deg"))
        if dihedral_deg is None:
            dihedral_deg = _station_dihedral_from_geometry(
                record.get("geometry") or {},
                eta=_float_or_none(row.get("eta")) or 0.0,
            )
        stations.append(
            WingStation(
                y_m=float(y_m),
                chord_m=float(chord_m),
                twist_deg=float(twist_deg),
                dihedral_deg=float(dihedral_deg),
            )
        )
    if len(stations) < 2:
        raise ValueError("At least two station_table rows are required for sidecar AVL.")
    return tuple(stations)


def _station_dihedral_from_geometry(geometry: dict[str, Any], *, eta: float) -> float:
    root = _float_or_none(geometry.get("dihedral_root_deg"))
    tip = _float_or_none(geometry.get("dihedral_tip_deg"))
    exponent = _float_or_none(geometry.get("dihedral_exponent"))
    if root is None and tip is None:
        return 0.0
    root = 0.0 if root is None else root
    tip = root if tip is None else tip
    exponent = 1.0 if exponent is None or exponent <= 0.0 else exponent
    eta_shaped = min(max(float(eta), 0.0), 1.0) ** float(exponent)
    return float(root + (tip - root) * eta_shaped)


def _sidecar_concept_from_record(
    *,
    cfg: BirdmanConceptConfig,
    record: dict[str, Any],
    stations: tuple[WingStation, ...],
) -> GeometryConcept:
    geometry = record.get("geometry") or {}
    span_m = _float_or_none(geometry.get("span_m"))
    if span_m is None:
        span_m = 2.0 * max(float(station.y_m) for station in stations)
    wing_area_m2 = _float_or_none(geometry.get("wing_area_m2"))
    if wing_area_m2 is None:
        wing_area_m2 = _integrate_station_chords(stations)
    root_chord_m = _float_or_none(geometry.get("root_chord_m")) or float(stations[0].chord_m)
    tip_chord_m = _float_or_none(geometry.get("tip_chord_m")) or float(stations[-1].chord_m)
    segment_lengths = tuple(
        float(right.y_m - left.y_m)
        for left, right in zip(stations[:-1], stations[1:], strict=True)
    )
    tail_volume = _float_or_none((record.get("spanload_to_geometry") or {}).get("tail_volume_coefficient"))
    if tail_volume is None:
        tail_volume = _float_or_none(geometry.get("tail_volume_coefficient"))
    tail_area_m2 = _float_or_none(geometry.get("tail_area_m2"))
    if tail_area_m2 is None:
        tail_area_m2 = (
            float(tail_volume or 0.4)
            * float(wing_area_m2)
            / max(float(cfg.tail_model.tail_arm_to_mac), 1.0e-9)
        )
    return GeometryConcept(
        span_m=float(span_m),
        wing_area_m2=float(wing_area_m2),
        root_chord_m=float(root_chord_m),
        tip_chord_m=float(tip_chord_m),
        twist_root_deg=float(stations[0].twist_deg),
        twist_tip_deg=float(stations[-1].twist_deg),
        tail_area_m2=float(tail_area_m2),
        tail_area_source="airfoil_sidecar_reconstructed_from_stage1_record",
        tail_volume_coefficient=tail_volume,
        cg_xc=float(_float_or_none(geometry.get("cg_xc")) or cfg.geometry_family.cg_xc),
        segment_lengths_m=segment_lengths,
        twist_control_points=tuple(
            (
                0.0
                if span_m <= 0.0
                else min(max(float(station.y_m) / (0.5 * float(span_m)), 0.0), 1.0),
                float(station.twist_deg),
            )
            for station in stations
        ),
        spanload_a3_over_a1=float(record.get("spanload_fourier", {}).get("a3_over_a1", 0.0)),
        spanload_a5_over_a1=float(record.get("spanload_fourier", {}).get("a5_over_a1", 0.0)),
        wing_loading_target_Npm2=float(cfg.design_gross_weight_n / max(float(wing_area_m2), 1.0e-9)),
        mean_chord_target_m=float(float(wing_area_m2) / max(float(span_m), 1.0e-9)),
        wing_area_is_derived=True,
        planform_parameterization="spanload_inverse_chord",
        design_gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
        dihedral_root_deg=float(_float_or_none(geometry.get("dihedral_root_deg")) or 0.0),
        dihedral_tip_deg=float(_float_or_none(geometry.get("dihedral_tip_deg")) or 0.0),
        dihedral_exponent=float(_float_or_none(geometry.get("dihedral_exponent")) or 1.0),
    )


def _fourier_target_from_record(record: dict[str, Any]) -> FourierTarget | None:
    target = record.get("mission_fourier_target")
    if isinstance(target, FourierTarget):
        return target
    if not isinstance(target, dict) or target.get("error") is not None:
        return None
    field_names = {field.name for field in fields(FourierTarget)}
    payload = {key: value for key, value in target.items() if key in field_names}
    if field_names - set(payload):
        return None
    tuple_fields = {
        "y",
        "eta",
        "theta",
        "chord_ref",
        "gamma_target",
        "lprime_target",
        "cl_target",
        "validation_warnings",
    }
    for field_name in tuple_fields:
        payload[field_name] = tuple(payload[field_name])
    return FourierTarget(**payload)


def _sidecar_source_quality(source_quality: str | None) -> str:
    text = str(source_quality or "")
    if "mission_grade" in text and "not_mission_grade" not in text:
        return "mission_grade_sidecar"
    return "not_mission_grade_sidecar"


def _evaluate_airfoil_sidecar_combination(
    *,
    cfg: BirdmanConceptConfig,
    record: dict[str, Any],
    combination: tuple[ZoneAirfoilAssignment, ...],
    combination_index: int,
    output_dir: Path,
    design_speed_mps: float,
    avl_binary: str | None,
    database: Any,
    is_baseline: bool,
) -> dict[str, Any]:
    assignment_dicts = assignment_to_dicts(combination)
    base_payload: dict[str, Any] = {
        "combination_index": int(combination_index),
        "is_baseline": bool(is_baseline),
        "assignment_label": assignment_label(combination),
        "airfoil_assignment": assignment_dicts,
        "source": "zone_airfoil_sidecar_avl_rerun_shadow_v1",
        "source_mode": "shadow_no_ranking_gate",
    }
    try:
        contract = _mission_contract_from_record(record)
        if contract is None:
            raise ValueError("mission_contract is unavailable")
        stations = _sidecar_stations_from_record(record)
        concept = _sidecar_concept_from_record(cfg=cfg, record=record, stations=stations)
        avl = _run_reference_avl_case(
            cfg=cfg,
            concept=concept,
            stations=stations,
            output_dir=output_dir,
            design_speed_mps=float(design_speed_mps),
            design_mass_kg=float(cfg.mass.design_gross_mass_kg),
            status_for_ranking="airfoil_sidecar_shadow",
            avl_binary=avl_binary,
            case_tag=f"sample_{int(record.get('sample_index') or 0):04d}_combo_{combination_index:02d}",
            zone_airfoil_paths=_zone_airfoil_paths_from_assignment(combination),
        )
        if avl.get("status") != "ok":
            raise RuntimeError(str(avl.get("error", "sidecar AVL rerun failed")))
        rerun_station_table = _attach_avl_to_station_table(
            [dict(row) for row in record.get("station_table") or []],
            avl,
        )
        profile = integrate_profile_drag_from_avl(
            contract,
            rerun_station_table,
            rerun_station_table,
            combination,
            database,
            cl_source_shape_mode=str(
                avl.get(
                    "profile_drag_cl_source_shape_mode",
                    "flat_or_unverified_loaded_shape",
                )
            ),
            cl_source_loaded_shape=bool(
                avl.get("profile_drag_cl_source_loaded_shape", False)
            ),
            cl_source_warning_count=int(
                avl.get("profile_drag_cl_source_warning_count", 1)
            ),
        )
        target = _fourier_target_from_record(record)
        comparison = (
            compare_fourier_target_to_avl(target, rerun_station_table)
            if target is not None
            else {
                "target_vs_avl_compare_success": False,
                "target_vs_avl_compare_reason": "mission_fourier_target_unavailable",
                "target_vs_avl_rms_delta": None,
                "target_vs_avl_max_delta": None,
                "target_vs_avl_outer_delta": None,
            }
        )
        source_quality = _sidecar_source_quality(profile.source_quality)
        return {
            **base_payload,
            "status": "ok",
            "CL": avl.get("trim_cl"),
            "CDi": avl.get("trim_cd_induced"),
            "e_CDi": avl.get("avl_e_cdi"),
            "target_vs_avl_rms": comparison.get("target_vs_avl_rms_delta"),
            "target_vs_avl_max": comparison.get("target_vs_avl_max_delta"),
            "target_vs_avl_outer_delta": comparison.get("target_vs_avl_outer_delta"),
            "profile_cd_airfoil_db": float(profile.CD_profile),
            "cd0_total_est_airfoil_db": float(profile.cd0_total_est),
            "mission_drag_budget_band": profile.drag_budget_band,
            "min_stall_margin_airfoil_db": profile.min_stall_margin_deg,
            "max_station_cl_utilization_airfoil_db": profile.max_station_cl_utilization,
            "source_quality": source_quality,
            "profile_drag_station_warning_count": int(profile.station_warning_count),
            "profile_drag_cl_source_shape_mode": profile.profile_drag_cl_source_shape_mode,
            "profile_drag_cl_source_loaded_shape": bool(
                profile.profile_drag_cl_source_loaded_shape
            ),
            "profile_drag_cl_source_warning_count": int(
                profile.profile_drag_cl_source_warning_count
            ),
            "avl_reference_case": avl,
            "target_vs_avl_comparison": comparison,
            "airfoil_profile_drag": profile.to_dict(),
        }
    except Exception as exc:  # noqa: BLE001 - sidecar must never gate the route.
        return {
            **base_payload,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "source_quality": "not_mission_grade_sidecar",
        }


def _sidecar_best_score(row: dict[str, Any]) -> tuple[float, float, float, int]:
    return (
        float(row.get("profile_cd_airfoil_db") or float("inf")),
        float(row.get("target_vs_avl_rms") or float("inf")),
        -float(row.get("e_CDi") or -float("inf")),
        int(row.get("combination_index") or 0),
    )


def _sidecar_improvement_notes(
    *,
    baseline: dict[str, Any] | None,
    best: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    if baseline is None or best is None:
        return False, ["baseline_or_best_sidecar_result_unavailable"]
    if best.get("combination_index") == baseline.get("combination_index"):
        return False, ["baseline_assignment_remains_best_sidecar"]
    notes: list[str] = []
    improved = False
    best_profile = _float_or_none(best.get("profile_cd_airfoil_db"))
    base_profile = _float_or_none(baseline.get("profile_cd_airfoil_db"))
    if best_profile is not None and base_profile is not None and best_profile < base_profile - 1.0e-6:
        improved = True
        notes.append("profile_cd_lower_than_baseline")
    best_e = _float_or_none(best.get("e_CDi"))
    base_e = _float_or_none(baseline.get("e_CDi"))
    if best_e is not None and base_e is not None and best_e > base_e + 1.0e-4:
        improved = True
        notes.append("e_CDi_higher_than_baseline")
    best_rms = _float_or_none(best.get("target_vs_avl_rms"))
    base_rms = _float_or_none(baseline.get("target_vs_avl_rms"))
    if best_rms is not None and base_rms is not None and best_rms < base_rms - 1.0e-4:
        improved = True
        notes.append("target_vs_avl_rms_lower_than_baseline")
    if not notes:
        notes.append("no_material_sidecar_improvement_vs_baseline")
    return improved, notes


def _attach_airfoil_sidecar_shadow_fields(
    records: list[dict[str, Any]],
    *,
    cfg: BirdmanConceptConfig,
    output_dir: Path,
    design_speed_mps: float,
    avl_binary: str | None,
    max_airfoil_combinations: int = 8,
) -> None:
    database = default_airfoil_database()
    baseline = fixed_seed_zone_airfoil_assignments()
    available_airfoils = _sidecar_available_airfoil_ids()
    for record in records:
        for field in AIRFOIL_SIDECAR_SHADOW_FIELDS:
            record.setdefault(field, None)
        try:
            contract = _mission_contract_from_record(record)
            if contract is None:
                raise ValueError("mission_contract is unavailable")
            profile_rows = _airfoil_profile_drag_rows_for_export(record)
            envelopes = build_zone_envelopes(
                loaded_avl_spanwise_result=record.get("station_table") or [],
                chord_distribution=record.get("station_table") or [],
                mission_contract=contract,
                fourier_target=record.get("mission_fourier_target"),
                zone_definitions=baseline,
                current_profile_drag_rows=profile_rows,
            )
            topk = query_zone_airfoil_topk(envelopes, database, top_k=2)
            combinations = generate_airfoil_sidecar_combinations(
                baseline,
                topk,
                available_airfoil_ids=available_airfoils,
                max_airfoil_combinations=int(max_airfoil_combinations),
            )
            results = [
                _evaluate_airfoil_sidecar_combination(
                    cfg=cfg,
                    record=record,
                    combination=combination,
                    combination_index=index,
                    output_dir=output_dir,
                    design_speed_mps=design_speed_mps,
                    avl_binary=avl_binary,
                    database=database,
                    is_baseline=index == 0,
                )
                for index, combination in enumerate(combinations)
            ]
            successful = [row for row in results if row.get("status") == "ok"]
            baseline_result = next(
                (row for row in successful if bool(row.get("is_baseline"))),
                None,
            )
            best = min(successful, key=_sidecar_best_score) if successful else None
            improved, notes = _sidecar_improvement_notes(
                baseline=baseline_result,
                best=best,
            )
            record["zone_envelope"] = zone_envelopes_to_rows(envelopes)
            record["zone_airfoil_topk"] = {
                str(zone_name): [dict(item) for item in candidates]
                for zone_name, candidates in topk.items()
            }
            record["airfoil_sidecar"] = {
                "source": "zone_airfoil_sidecar_avl_rerun_shadow_v1",
                "source_mode": "shadow_no_ranking_gate",
                "ranking_behavior": "unchanged_no_rejection_no_sort_key",
                "max_airfoil_combinations": int(max_airfoil_combinations),
                "available_airfoil_ids": list(available_airfoils),
                "combination_count": len(results),
            }
            record["airfoil_sidecar_combinations"] = results
            record["airfoil_sidecar_best"] = best or {
                "status": "unavailable",
                "source_quality": "not_mission_grade_sidecar",
                "notes": notes,
            }
            if best is not None:
                record.update(
                    {
                        "sidecar_best_airfoil_assignment": best.get("assignment_label"),
                        "sidecar_best_e_CDi": best.get("e_CDi"),
                        "sidecar_best_target_vs_avl_rms": best.get(
                            "target_vs_avl_rms"
                        ),
                        "sidecar_best_target_vs_avl_outer_delta": best.get(
                            "target_vs_avl_outer_delta"
                        ),
                        "sidecar_best_profile_cd": best.get("profile_cd_airfoil_db"),
                        "sidecar_best_cd0_total_est": best.get(
                            "cd0_total_est_airfoil_db"
                        ),
                        "sidecar_best_min_stall_margin": best.get(
                            "min_stall_margin_airfoil_db"
                        ),
                        "sidecar_best_source_quality": best.get("source_quality"),
                        "sidecar_improved_vs_baseline": bool(improved),
                        "sidecar_improvement_notes": notes,
                    }
                )
            else:
                record["sidecar_improved_vs_baseline"] = False
                record["sidecar_improvement_notes"] = notes
                record["sidecar_best_source_quality"] = "not_mission_grade_sidecar"
        except Exception as exc:  # noqa: BLE001 - Phase 4 sidecar is shadow-only.
            record["zone_envelope"] = []
            record["zone_airfoil_topk"] = {}
            record["airfoil_sidecar"] = {
                "source": "zone_airfoil_sidecar_avl_rerun_shadow_v1",
                "source_mode": "shadow_no_ranking_gate",
                "ranking_behavior": "unchanged_no_rejection_no_sort_key",
                "error": f"{type(exc).__name__}: {exc}",
            }
            record["airfoil_sidecar_combinations"] = []
            record["airfoil_sidecar_best"] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "source_quality": "not_mission_grade_sidecar",
            }
            record["sidecar_improved_vs_baseline"] = False
            record["sidecar_improvement_notes"] = ["sidecar_failed_shadow_only"]
            record["sidecar_best_source_quality"] = "not_mission_grade_sidecar"


def _mission_contract_from_record(record: dict[str, Any]) -> MissionContract | None:
    payload = record.get("mission_contract")
    if not isinstance(payload, dict) or payload.get("error") is not None:
        return None
    contract_field_names = {field.name for field in fields(MissionContract)}
    contract_payload = {
        key: value for key, value in payload.items() if key in contract_field_names
    }
    return MissionContract(**contract_payload)


def _mission_fourier_chord_ref(
    record: dict[str, Any],
    eta_grid: tuple[float, ...],
) -> tuple[float, ...]:
    station_points: list[tuple[float, float]] = []
    for row in record.get("station_table") or []:
        eta = _float_or_none(row.get("eta"))
        chord = _float_or_none(row.get("chord_m"))
        if eta is None or chord is None or chord <= 0.0:
            continue
        station_points.append((min(max(float(eta), 0.0), 1.0), float(chord)))
    if len(station_points) >= 2:
        station_points.sort(key=lambda point: point[0])
        unique_points: dict[float, float] = {}
        for eta, chord in station_points:
            unique_points[eta] = chord
        station_eta = np.asarray(tuple(unique_points.keys()), dtype=float)
        station_chord = np.asarray(tuple(unique_points.values()), dtype=float)
        chord_ref = np.interp(np.asarray(eta_grid, dtype=float), station_eta, station_chord)
        return tuple(float(max(chord, 1.0e-6)) for chord in chord_ref)

    geometry = record.get("geometry", {})
    root_chord = _float_or_none(geometry.get("root_chord_m"))
    tip_chord = _float_or_none(geometry.get("tip_chord_m"))
    if root_chord is None or tip_chord is None or root_chord <= 0.0 or tip_chord <= 0.0:
        raise ValueError("station_table or geometry root/tip chord is required")
    return tuple(
        float((1.0 - float(eta)) * root_chord + float(eta) * tip_chord)
        for eta in eta_grid
    )


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _scale_range(bounds: tuple[float, float], unit_value: float) -> float:
    low, high = bounds
    return float(low + float(unit_value) * (high - low))


def _sample_stage0_units(*, sample_count: int, seed: int, dimensions: int = 6) -> np.ndarray:
    # Sobol prefers powers of two. random() works for arbitrary N but emits a scipy
    # warning; random_base2 keeps the sequence balanced and we trim to the requested N.
    count = max(1, int(sample_count))
    exponent = int(math.ceil(math.log2(count)))
    sampler = qmc.Sobol(d=int(dimensions), seed=int(seed), scramble=True)
    return sampler.random_base2(m=exponent)[:count]


def _median_candidate(values: tuple[float, ...] | list[float], default: float) -> float:
    if not values:
        return float(default)
    sorted_values = sorted(float(value) for value in values)
    return float(sorted_values[len(sorted_values) // 2])


def _cl_schedule_values(
    cl_controls: tuple[float, float, float, float] | list[float],
    etas: tuple[float, ...] | list[float],
) -> list[float]:
    if len(cl_controls) != len(INVERSE_CHORD_CL_CONTROL_ETAS):
        raise ValueError("cl_controls must match INVERSE_CHORD_CL_CONTROL_ETAS.")
    interpolator = PchipInterpolator(
        np.asarray(INVERSE_CHORD_CL_CONTROL_ETAS, dtype=float),
        np.asarray(tuple(float(value) for value in cl_controls), dtype=float),
        extrapolate=True,
    )
    values = interpolator(np.asarray(tuple(float(eta) for eta in etas), dtype=float))
    return [float(max(0.05, value)) for value in values]


def _integrate_station_chords(stations: tuple[WingStation, ...]) -> float:
    if len(stations) < 2:
        return 0.0
    half_area = 0.0
    for left, right in zip(stations[:-1], stations[1:]):
        dy_m = float(right.y_m) - float(left.y_m)
        half_area += 0.5 * dy_m * (float(left.chord_m) + float(right.chord_m))
    return float(2.0 * half_area)


def _inverse_chord_target_solution(
    *,
    cfg: BirdmanConceptConfig,
    span_m: float,
    a3: float,
    a5: float,
    design_speed_mps: float,
) -> dict[str, Any]:
    air = _air_properties(cfg)
    half_span_m = 0.5 * float(span_m)
    integration_etas = np.linspace(0.0, 1.0, 401)
    shapes = [
        max(0.0, _fourier_spanload_shape(a3_over_a1=float(a3), a5_over_a1=float(a5), eta=float(eta)))
        for eta in integration_etas
    ]
    shape_integral_m = float(
        np.trapezoid(
            np.asarray(shapes, dtype=float),
            x=np.asarray(integration_etas, dtype=float) * half_span_m,
        )
    )
    design_weight_n = float(cfg.mass.design_gross_mass_kg) * G_MPS2
    gamma_scale = design_weight_n / max(
        2.0 * float(air.density_kg_per_m3) * float(design_speed_mps) * shape_integral_m,
        1.0e-9,
    )
    cl_scale = 2.0 * gamma_scale / max(float(design_speed_mps), 1.0e-9)
    return {
        "air_properties": air,
        "span_m": float(span_m),
        "half_span_m": float(half_span_m),
        "design_speed_mps": float(design_speed_mps),
        "design_mass_kg": float(cfg.mass.design_gross_mass_kg),
        "design_weight_n": float(design_weight_n),
        "shape_integral_m": float(shape_integral_m),
        "gamma_scale_m2ps": float(gamma_scale),
        "cl_scale": float(cl_scale),
        "max_shape": float(max(shapes, default=1.0)),
    }


def _inverse_chord_build_stations(
    *,
    cfg: BirdmanConceptConfig,
    span_m: float,
    a3: float,
    a5: float,
    cl_controls: tuple[float, float, float, float] | list[float],
    design_speed_mps: float,
) -> tuple[tuple[WingStation, ...], dict[str, Any]]:
    half_span_m = 0.5 * float(span_m)
    etas = tuple(float(value) for value in INVERSE_CHORD_STATION_ETAS)
    cl_values = _cl_schedule_values(cl_controls, etas)
    target = _inverse_chord_target_solution(
        cfg=cfg,
        span_m=span_m,
        a3=a3,
        a5=a5,
        design_speed_mps=design_speed_mps,
    )
    tip_required_m = max(
        INVERSE_CHORD_PHYSICAL_TIP_CHORD_MIN_M,
        _tip_required_chord_m_for_speed(cfg, design_speed_mps=design_speed_mps),
    )
    tip_eta_chord_min_m = max(
        float(cfg.geometry_family.planform_tip_protection.require_chord_at_eta_0p95_min_m),
        _tip_required_chord_m_for_speed(cfg, design_speed_mps=design_speed_mps),
    )
    raw_chords: list[float] = []
    for eta, local_cl in zip(etas, cl_values, strict=True):
        eta_for_lift = min(float(eta), float(cfg.geometry_family.planform_tip_protection.aerodynamic_tip_station_eta))
        shape = max(
            0.0,
            _fourier_spanload_shape(a3_over_a1=float(a3), a5_over_a1=float(a5), eta=eta_for_lift),
        )
        chord_m = float(target["cl_scale"]) * shape / max(float(local_cl), 1.0e-9)
        if math.isclose(eta, 0.95, abs_tol=1.0e-9):
            chord_m = max(chord_m, tip_eta_chord_min_m)
        if math.isclose(eta, 1.0, abs_tol=1.0e-9):
            chord_m = max(tip_required_m, raw_chords[-1] if raw_chords else tip_required_m)
        raw_chords.append(float(chord_m))

    fitted_chords = list(raw_chords)
    root_low, root_high = INVERSE_CHORD_ROOT_CHORD_RANGE_M
    root_scale = 1.0
    if fitted_chords[0] < root_low:
        root_scale = float(root_low / max(fitted_chords[0], 1.0e-9))
    elif fitted_chords[0] > root_high:
        root_scale = float(root_high / max(fitted_chords[0], 1.0e-9))
    if not math.isclose(root_scale, 1.0):
        fitted_chords = [max(tip_required_m, chord * root_scale) for chord in fitted_chords]
    fitted_chords[-2] = max(fitted_chords[-2], tip_eta_chord_min_m)
    fitted_chords[-1] = max(fitted_chords[-1], tip_required_m, 0.95 * fitted_chords[-2])

    stations = tuple(
        WingStation(
            y_m=float(eta * half_span_m),
            chord_m=float(chord_m),
            twist_deg=float(TWIST_ROOT_ANCHOR_DEG),
            dihedral_deg=_linear_interp(
                (0.0, 1.0),
                (
                    _median_candidate(cfg.geometry_family.dihedral_root_deg_candidates, 0.0),
                    _median_candidate(cfg.geometry_family.dihedral_tip_deg_candidates, 6.0),
                ),
                float(eta),
            ),
        )
        for eta, chord_m in zip(etas, fitted_chords, strict=True)
    )
    adjacent_ratios = [
        max(left, right) / max(min(left, right), 1.0e-9)
        for left, right in zip(fitted_chords[:-1], fitted_chords[1:])
    ]
    slope_changes = [
        abs(right - 2.0 * center + left)
        for left, center, right in zip(fitted_chords[:-2], fitted_chords[1:-1], fitted_chords[2:])
    ]
    return stations, {
        "mode": SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE,
        "stage_a_fourier_target": _fourier_efficiency(a3, a5),
        "local_cl_schedule": {
            "model": "pchip_b_spline_control_schedule",
            "control_etas": [float(value) for value in INVERSE_CHORD_CL_CONTROL_ETAS],
            "control_bounds": [
                [float(low), float(high)] for low, high in INVERSE_CHORD_CL_CONTROL_BOUNDS
            ],
            "control_values": [float(value) for value in cl_controls],
            "station_values": [
                {"eta": float(eta), "target_cl": float(cl)}
                for eta, cl in zip(etas, cl_values, strict=True)
            ],
        },
        "inverse_chord": {
            "formula": "c_y_eq_2_gamma_target_over_v_cl_design",
            "station_etas": [float(value) for value in etas],
            "raw_chords_m": [float(value) for value in raw_chords],
            "fitted_chords_m": [float(value) for value in fitted_chords],
            "root_scale_applied": float(root_scale),
            "max_adjacent_chord_ratio": float(max(adjacent_ratios, default=1.0)),
            "max_chord_second_difference_m": float(max(slope_changes, default=0.0)),
            "physical_tip_not_primary_lifting_station": True,
            "chord_eta_0p95_min_m": float(tip_eta_chord_min_m),
            "physical_tip_chord_min_m": float(tip_required_m),
        },
        "target_solution": {
            key: value
            for key, value in target.items()
            if key != "air_properties"
        },
    }


def _inverse_chord_gate_failures(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    spanload_to_geometry: dict[str, Any],
    design_speed_mps: float,
) -> list[str]:
    failures: list[str] = []
    root_low, root_high = INVERSE_CHORD_ROOT_CHORD_RANGE_M
    if concept.root_chord_m < root_low or concept.root_chord_m > root_high:
        failures.append("inverse_chord_root_chord_outside_hpa_range")
    if concept.wing_area_m2 < STAGE0_WING_AREA_RANGE_M2[0]:
        failures.append("wing_area_below_optimizer_min")
    if concept.wing_area_m2 > STAGE0_WING_AREA_RANGE_M2[1]:
        failures.append("wing_area_above_optimizer_max")
    if concept.aspect_ratio < STAGE0_AR_RANGE[0]:
        failures.append("aspect_ratio_below_optimizer_min")
    if concept.aspect_ratio > STAGE0_AR_RANGE[1]:
        failures.append("aspect_ratio_above_optimizer_max")
    if concept.tip_chord_m < INVERSE_CHORD_PHYSICAL_TIP_CHORD_MIN_M:
        failures.append("inverse_chord_physical_tip_chord_below_min")
    chord_eta_0p95 = _chord_at_eta_from_stations(stations, concept, 0.95)
    if chord_eta_0p95 < float(cfg.geometry_family.planform_tip_protection.require_chord_at_eta_0p95_min_m):
        failures.append("inverse_chord_eta_0p95_chord_below_min")
    inverse_chord = spanload_to_geometry.get("inverse_chord", {})
    chord_bump = spanload_to_geometry.get("outer_chord_bump") or {}
    bump_succeeded = bool(chord_bump.get("succeeded", True))
    bump_active = float(chord_bump.get("outer_chord_bump_amp", 0.0)) > 0.0 and bump_succeeded
    max_adjacent_ratio = (
        float(chord_bump.get("max_adjacent_chord_ratio", 1.0))
        if bump_active
        else float(inverse_chord.get("max_adjacent_chord_ratio", 1.0))
    )
    max_second_difference = (
        float(chord_bump.get("max_chord_second_difference_m", 0.0))
        if bump_active
        else float(inverse_chord.get("max_chord_second_difference_m", 0.0))
    )
    if max_adjacent_ratio > 1.45:
        failures.append("sharp_chord_kink_ratio_without_joint")
    if max_second_difference > 0.35:
        failures.append("sharp_chord_kink_curvature_without_joint")
    air = _air_properties(cfg)
    tip_re = (
        float(air.density_kg_per_m3)
        * float(design_speed_mps)
        * float(concept.tip_chord_m)
        / max(float(air.dynamic_viscosity_pa_s), 1.0e-12)
    )
    if tip_re < float(cfg.geometry_family.planform_tip_protection.tip_re_abs_min):
        failures.append("inverse_chord_physical_tip_re_below_abs_min")
    return failures


def _make_inverse_chord_concept(
    *,
    cfg: BirdmanConceptConfig,
    span_m: float,
    tail_volume_coefficient: float,
    a3: float,
    a5: float,
    stations: tuple[WingStation, ...],
) -> GeometryConcept:
    wing_area_m2 = _integrate_station_chords(stations)
    root_chord_m = float(stations[0].chord_m)
    tip_chord_m = float(stations[-1].chord_m)
    tail_area_m2 = (
        float(tail_volume_coefficient)
        * wing_area_m2
        / max(float(cfg.tail_model.tail_arm_to_mac), 1.0e-9)
    )
    twist_control_points = (
        (0.0, float(TWIST_ROOT_ANCHOR_DEG)),
        (0.35, 0.7),
        (0.70, -0.6),
        (1.0, -1.8),
    )
    segment_lengths_m = tuple(
        float(right.y_m - left.y_m)
        for left, right in zip(stations[:-1], stations[1:])
    )
    return GeometryConcept(
        span_m=float(span_m),
        wing_area_m2=float(wing_area_m2),
        root_chord_m=float(root_chord_m),
        tip_chord_m=float(tip_chord_m),
        twist_root_deg=float(TWIST_ROOT_ANCHOR_DEG),
        twist_tip_deg=float(twist_control_points[-1][1]),
        twist_control_points=twist_control_points,
        spanload_bias=0.0,
        spanload_a3_over_a1=float(a3),
        spanload_a5_over_a1=float(a5),
        dihedral_root_deg=_median_candidate(cfg.geometry_family.dihedral_root_deg_candidates, 0.0),
        dihedral_tip_deg=_median_candidate(cfg.geometry_family.dihedral_tip_deg_candidates, 6.0),
        dihedral_exponent=_median_candidate(cfg.geometry_family.dihedral_exponent_candidates, 1.5),
        tail_area_m2=float(tail_area_m2),
        tail_area_source="derived_from_tail_volume_coefficient",
        tail_volume_coefficient=float(tail_volume_coefficient),
        cg_xc=float(cfg.geometry_family.cg_xc),
        segment_lengths_m=segment_lengths_m,
        wing_loading_target_Npm2=float(cfg.design_gross_weight_n / max(wing_area_m2, 1.0e-9)),
        mean_chord_target_m=float(wing_area_m2 / max(float(span_m), 1.0e-9)),
        wing_area_is_derived=True,
        planform_parameterization="spanload_inverse_chord",
        design_gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
    )


def _build_inverse_chord_stage0_metric(
    *,
    cfg: BirdmanConceptConfig,
    sample_index: int,
    span_m: float,
    tail_volume_coefficient: float,
    a3: float,
    a5: float,
    cl_controls: tuple[float, float, float, float] | list[float],
    design_speed_mps: float,
    outer_chord_bump_amp: float = 0.0,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    base_stations, spanload_to_geometry = _inverse_chord_build_stations(
        cfg=cfg,
        span_m=float(span_m),
        a3=float(a3),
        a5=float(a5),
        cl_controls=cl_controls,
        design_speed_mps=float(design_speed_mps),
    )
    bump_amp = max(0.0, float(outer_chord_bump_amp))
    stations, chord_bump_diag = apply_outer_chord_redistribution(
        stations=base_stations,
        amplitude=bump_amp,
        chord_floor_m=float(INVERSE_CHORD_PHYSICAL_TIP_CHORD_MIN_M),
    )
    spanload_to_geometry = {
        **spanload_to_geometry,
        "outer_chord_bump": chord_bump_diag.to_dict(),
    }
    if bump_amp > 0.0 and not chord_bump_diag.succeeded:
        rejection = {
            "sample_index": int(sample_index),
            "reason": (
                f"outer_chord_bump_redistribution_failed:"
                f"{chord_bump_diag.failure_reason or 'unknown'}"
            ),
            "details": {
                "outer_chord_bump_amp": float(bump_amp),
                "chord_redistribution": chord_bump_diag.to_dict(),
                "spanload_to_geometry": spanload_to_geometry,
            },
            "geometry": {
                "span_m": float(span_m),
                "wing_area_m2": _integrate_station_chords(base_stations),
            },
            "metric": None,
            "severity_ratio": _stage0_rejection_severity(
                {
                    "reason": "outer_chord_bump_redistribution_failed",
                    "details": {"gate_failures": 1},
                }
            ),
        }
        return None, rejection
    concept = _make_inverse_chord_concept(
        cfg=cfg,
        span_m=float(span_m),
        tail_volume_coefficient=float(tail_volume_coefficient),
        a3=float(a3),
        a5=float(a5),
        stations=stations,
    )
    station_table, target_summary = _target_station_records(
        cfg=cfg,
        concept=concept,
        stations=stations,
        design_speed_mps=design_speed_mps,
    )
    health = _spanload_gate_health(target_summary, cfg)
    fourier = _fourier_efficiency(float(a3), float(a5))
    tip_summary = _tip_gate_summary(
        cfg=cfg,
        concept=concept,
        stations=stations,
        design_speed_mps=design_speed_mps,
    )
    spanload_cfg = cfg.geometry_family.spanload_design
    gate_failures = _inverse_chord_gate_failures(
        cfg=cfg,
        concept=concept,
        stations=stations,
        spanload_to_geometry=spanload_to_geometry,
        design_speed_mps=design_speed_mps,
    )
    if fourier["outer_loading_ratio_eta_0p90"] > float(
        spanload_cfg.outer_loading_eta_0p90_max_ratio_to_ellipse
    ) or fourier["outer_loading_ratio_eta_0p95"] > float(
        spanload_cfg.outer_loading_eta_0p95_max_ratio_to_ellipse
    ):
        gate_failures.append("outer_loading_ratio_above_max")
    if not bool(tip_summary["tip_gates_pass"]):
        gate_failures.append("tip_geometry_gates_failed")
    if float(health["local_margin_to_limit"]) < 0.0 or float(health["outer_margin_to_limit"]) < 0.0:
        gate_failures.append("spanload_local_or_outer_utilization_failed")
    target_power_proxy = _mission_power_proxy(
        cfg=cfg,
        concept=concept,
        design_speed_mps=design_speed_mps,
    )
    metric = {
        "sample_index": int(sample_index),
        "concept": concept,
        "stations": stations,
        "geometry": _geometry_summary(concept),
        "spanload_to_geometry": spanload_to_geometry,
        "spanload_fourier": fourier,
        "spanload_gate_health": health,
        "tip_gate_summary": tip_summary,
        "target_fourier_power_proxy": target_power_proxy,
        "avl_cdi_power_proxy": {
            **target_power_proxy,
            "model": "stage0_placeholder_uses_target_fourier_cdi_until_avl",
        },
        "station_table": station_table,
        "gate_station_table": target_summary["gate_station_table"],
        "worst_station": target_summary["worst_station"],
        "stage0_prefilter_status": "accepted" if not gate_failures else "rejected",
        "outer_chord_bump_amp": float(bump_amp),
        "outer_chord_redistribution": chord_bump_diag.to_dict(),
    }
    if not gate_failures:
        return metric, None
    reason = str(gate_failures[0])
    rejection = {
        "sample_index": int(sample_index),
        "reason": reason,
        "details": {
            "gate_failures": sorted(set(gate_failures)),
            "spanload_gate_health": health,
            "tip_gate_summary": tip_summary,
            "spanload_to_geometry": spanload_to_geometry,
        },
        "geometry": metric["geometry"],
        "metric": metric,
        "severity_ratio": _stage0_rejection_severity(
            {"reason": reason, "details": {"gate_failures": len(gate_failures)}}
        ),
    }
    return None, rejection


def _make_stage0_concept(
    *,
    cfg: BirdmanConceptConfig,
    sample_index: int,
    unit_row: np.ndarray,
    design_speed_mps: float,
) -> tuple[GeometryConcept | None, dict[str, Any] | None]:
    span_m = _scale_range(STAGE0_SPAN_RANGE_M, float(unit_row[0]))
    mean_chord_m = _scale_range(STAGE0_MEAN_CHORD_RANGE_M, float(unit_row[1]))
    sampled_taper = _scale_range(STAGE0_TAPER_SAMPLE_RANGE, float(unit_row[2]))
    tail_volume = _scale_range(STAGE0_TAIL_VOLUME_RANGE, float(unit_row[3]))
    a3 = _scale_range(STAGE0_A3_RANGE, float(unit_row[4]))
    a5 = _scale_range(STAGE0_A5_RANGE, float(unit_row[5]))

    wing_area_m2 = span_m * mean_chord_m
    required_tip_chord_m = _tip_required_chord_m_for_speed(
        cfg,
        design_speed_mps=design_speed_mps,
    )
    lambda_min_dyn = _lambda_min_from_tip_chord(
        c_bar_m=mean_chord_m,
        c_tip_min_m=required_tip_chord_m,
    )
    if not math.isfinite(lambda_min_dyn):
        return None, {
            "sample_index": int(sample_index),
            "reason": "tip_dynamic_lambda_infeasible",
            "details": {
                "mean_chord_m": float(mean_chord_m),
                "tip_required_chord_m": float(required_tip_chord_m),
            },
            "geometry": {
                "span_m": float(span_m),
                "wing_area_m2": float(wing_area_m2),
                "aspect_ratio": float(span_m / max(mean_chord_m, 1.0e-9)),
            },
        }
    taper_ratio = max(float(sampled_taper), float(lambda_min_dyn))
    if taper_ratio > STAGE0_TAPER_UPPER_LIMIT:
        return None, {
            "sample_index": int(sample_index),
            "reason": "dynamic_taper_exceeds_upper_limit",
            "details": {
                "sampled_taper_ratio": float(sampled_taper),
                "dynamic_lambda_min_from_tip_chord": float(lambda_min_dyn),
                "taper_upper_limit": float(STAGE0_TAPER_UPPER_LIMIT),
                "tip_required_chord_m": float(required_tip_chord_m),
            },
            "geometry": {
                "span_m": float(span_m),
                "wing_area_m2": float(wing_area_m2),
                "aspect_ratio": float(span_m / max(mean_chord_m, 1.0e-9)),
            },
        }

    root_chord_m = 2.0 * mean_chord_m / max(1.0 + taper_ratio, 1.0e-9)
    tip_chord_m = root_chord_m * taper_ratio
    aspect_ratio = span_m / max(mean_chord_m, 1.0e-9)
    primary_values = {
        "span_m": float(span_m),
        "mean_chord_m": float(mean_chord_m),
        "sampled_taper_ratio": float(sampled_taper),
        "taper_ratio": float(taper_ratio),
        "dynamic_lambda_min_from_tip_chord": float(lambda_min_dyn),
        "spanload_a3_over_a1": float(a3),
        "spanload_a5_over_a1": float(a5),
    }
    secondary_values = {
        "tail_volume_coefficient": float(tail_volume),
        "dihedral_root_deg": _median_candidate(
            cfg.geometry_family.dihedral_root_deg_candidates,
            0.0,
        ),
        "dihedral_tip_deg": _median_candidate(
            cfg.geometry_family.dihedral_tip_deg_candidates,
            6.0,
        ),
        "dihedral_exponent": _median_candidate(
            cfg.geometry_family.dihedral_exponent_candidates,
            1.5,
        ),
    }

    def _stage0_reject(reason: str, **details: float | str) -> tuple[None, dict[str, Any]]:
        return None, {
            "sample_index": int(sample_index),
            "reason": reason,
            "primary_values": dict(primary_values),
            "secondary_values": dict(secondary_values),
            "details": details,
            "geometry": {
                "span_m": float(span_m),
                "wing_area_m2": float(wing_area_m2),
                "aspect_ratio": float(aspect_ratio),
                "taper_ratio": float(taper_ratio),
                "root_chord_m": float(root_chord_m),
                "tip_chord_m": float(tip_chord_m),
                "mean_chord_m": float(mean_chord_m),
            },
        }

    if wing_area_m2 < STAGE0_WING_AREA_RANGE_M2[0]:
        return _stage0_reject("wing_area_below_optimizer_min", wing_area_m2=wing_area_m2)
    if wing_area_m2 > STAGE0_WING_AREA_RANGE_M2[1]:
        return _stage0_reject("wing_area_above_optimizer_max", wing_area_m2=wing_area_m2)
    if aspect_ratio < STAGE0_AR_RANGE[0]:
        return _stage0_reject("aspect_ratio_below_optimizer_min", aspect_ratio=aspect_ratio)
    if aspect_ratio > STAGE0_AR_RANGE[1]:
        return _stage0_reject("aspect_ratio_above_optimizer_max", aspect_ratio=aspect_ratio)
    if root_chord_m < STAGE0_ROOT_CHORD_MIN_M:
        return _stage0_reject("root_chord_below_optimizer_min", root_chord_m=root_chord_m)

    try:
        segment_lengths_m = build_segment_plan(
            half_span_m=0.5 * span_m,
            min_segment_length_m=float(cfg.segmentation.min_segment_length_m),
            max_segment_length_m=float(cfg.segmentation.max_segment_length_m),
        )
    except ValueError as exc:
        return _stage0_reject("segment_plan_infeasible", error=str(exc))

    tail_area_m2 = tail_volume * wing_area_m2 / max(float(cfg.tail_model.tail_arm_to_mac), 1.0e-9)
    twist_control_points = (
        (0.0, float(TWIST_ROOT_ANCHOR_DEG)),
        (0.35, 0.5),
        (0.70, -1.0),
        (1.0, -2.4),
    )
    concept = GeometryConcept(
        span_m=float(span_m),
        wing_area_m2=float(wing_area_m2),
        root_chord_m=float(root_chord_m),
        tip_chord_m=float(tip_chord_m),
        twist_root_deg=float(TWIST_ROOT_ANCHOR_DEG),
        twist_tip_deg=float(twist_control_points[-1][1]),
        twist_control_points=twist_control_points,
        spanload_bias=0.0,
        spanload_a3_over_a1=float(a3),
        spanload_a5_over_a1=float(a5),
        dihedral_root_deg=float(secondary_values["dihedral_root_deg"]),
        dihedral_tip_deg=float(secondary_values["dihedral_tip_deg"]),
        dihedral_exponent=float(secondary_values["dihedral_exponent"]),
        tail_area_m2=float(tail_area_m2),
        tail_area_source="derived_from_tail_volume_coefficient",
        tail_volume_coefficient=float(tail_volume),
        cg_xc=float(cfg.geometry_family.cg_xc),
        segment_lengths_m=segment_lengths_m,
        wing_loading_target_Npm2=float(cfg.design_gross_weight_n / max(wing_area_m2, 1.0e-9)),
        mean_chord_target_m=float(mean_chord_m),
        wing_area_is_derived=True,
        planform_parameterization="mean_chord",
        design_gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
    )
    return concept, None


def _stage0_rejection_severity(rejection: dict[str, Any]) -> float:
    details = rejection.get("details", {})
    reason = str(rejection.get("reason", ""))
    if reason.endswith("below_optimizer_min"):
        value = next((float(value) for value in details.values() if isinstance(value, int | float)), 0.0)
        limit = {
            "wing_area_below_optimizer_min": STAGE0_WING_AREA_RANGE_M2[0],
            "aspect_ratio_below_optimizer_min": STAGE0_AR_RANGE[0],
            "root_chord_below_optimizer_min": STAGE0_ROOT_CHORD_MIN_M,
        }.get(reason, 1.0)
        return abs(float(limit) - value) / max(abs(float(limit)), 1.0e-9)
    if reason.endswith("above_optimizer_max"):
        value = next((float(value) for value in details.values() if isinstance(value, int | float)), 0.0)
        limit = {
            "wing_area_above_optimizer_max": STAGE0_WING_AREA_RANGE_M2[1],
            "aspect_ratio_above_optimizer_max": STAGE0_AR_RANGE[1],
        }.get(reason, 1.0)
        return abs(value - float(limit)) / max(abs(float(limit)), 1.0e-9)
    if reason == "dynamic_taper_exceeds_upper_limit":
        return float(details.get("dynamic_lambda_min_from_tip_chord", 1.0)) / max(
            float(details.get("taper_upper_limit", 1.0)),
            1.0e-9,
        )
    if reason == "tip_geometry_gates_failed":
        return 1.1
    if reason == "spanload_local_or_outer_utilization_failed":
        return max(
            float(details.get("max_local_clmax_utilization", 0.0))
            / max(float(details.get("local_limit", 1.0)), 1.0e-9),
            float(details.get("max_outer_clmax_utilization", 0.0))
            / max(float(details.get("outer_limit", 1.0)), 1.0e-9),
        )
    if reason == "outer_loading_ratio_above_max":
        return max(
            float(details.get("outer_loading_ratio_eta_0p90", 0.0))
            / max(float(details.get("outer_loading_eta_0p90_max", 1.0)), 1.0e-9),
            float(details.get("outer_loading_ratio_eta_0p95", 0.0))
            / max(float(details.get("outer_loading_eta_0p95_max", 1.0)), 1.0e-9),
        )
    return float("inf")


def _stage0_metric_from_concept(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    sample_index: int,
    design_speed_mps: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
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
    health = _spanload_gate_health(target_summary, cfg)
    fourier = _fourier_efficiency(
        float(concept.spanload_a3_over_a1),
        float(concept.spanload_a5_over_a1),
    )
    tip_summary = _tip_gate_summary(
        cfg=cfg,
        concept=concept,
        design_speed_mps=design_speed_mps,
    )
    spanload_cfg = cfg.geometry_family.spanload_design
    rejection_details: dict[str, Any] | None = None
    if fourier["outer_loading_ratio_eta_0p90"] > float(
        spanload_cfg.outer_loading_eta_0p90_max_ratio_to_ellipse
    ) or fourier["outer_loading_ratio_eta_0p95"] > float(
        spanload_cfg.outer_loading_eta_0p95_max_ratio_to_ellipse
    ):
        rejection_details = {
            "reason": "outer_loading_ratio_above_max",
            "details": {
                "outer_loading_ratio_eta_0p90": float(fourier["outer_loading_ratio_eta_0p90"]),
                "outer_loading_eta_0p90_max": float(
                    spanload_cfg.outer_loading_eta_0p90_max_ratio_to_ellipse
                ),
                "outer_loading_ratio_eta_0p95": float(fourier["outer_loading_ratio_eta_0p95"]),
                "outer_loading_eta_0p95_max": float(
                    spanload_cfg.outer_loading_eta_0p95_max_ratio_to_ellipse
                ),
            },
        }
    if rejection_details is None and not bool(tip_summary["tip_gates_pass"]):
        rejection_details = {
            "reason": "tip_geometry_gates_failed",
            "details": tip_summary,
        }
    if rejection_details is None and (
        float(health["local_margin_to_limit"]) < 0.0
        or float(health["outer_margin_to_limit"]) < 0.0
    ):
        rejection_details = {
            "reason": "spanload_local_or_outer_utilization_failed",
            "details": {
                **health,
                "local_limit": float(health["max_local_clmax_utilization_limit"]),
                "outer_limit": float(health["max_outer_clmax_utilization_limit"]),
            },
        }

    target_power_proxy = _mission_power_proxy(
        cfg=cfg,
        concept=concept,
        design_speed_mps=design_speed_mps,
    )
    metric = {
        "sample_index": int(sample_index),
        "concept": concept,
        "geometry": _geometry_summary(concept),
        "spanload_fourier": fourier,
        "spanload_gate_health": health,
        "tip_gate_summary": tip_summary,
        "target_fourier_power_proxy": target_power_proxy,
        "avl_cdi_power_proxy": {
            **target_power_proxy,
            "model": "stage0_placeholder_uses_target_fourier_cdi_until_avl",
        },
        "gate_station_table": target_summary["gate_station_table"],
        "worst_station": target_summary["worst_station"],
        "stage0_prefilter_status": "accepted" if rejection_details is None else "rejected",
    }
    if rejection_details is None:
        return metric, None
    rejection = {
        "sample_index": int(sample_index),
        "reason": str(rejection_details["reason"]),
        "details": rejection_details["details"],
        "geometry": metric["geometry"],
        "metric": metric,
        "severity_ratio": _stage0_rejection_severity(
            {
                "reason": rejection_details["reason"],
                "details": rejection_details["details"],
            }
        ),
    }
    return None, rejection


def _stage0_sobol_prefilter(
    *,
    cfg: BirdmanConceptConfig,
    sample_count: int,
    design_speed_mps: float,
    seed: int,
) -> dict[str, Any]:
    units = _sample_stage0_units(sample_count=sample_count, seed=seed)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for sample_index, unit_row in enumerate(units, start=1):
        concept, build_rejection = _make_stage0_concept(
            cfg=cfg,
            sample_index=sample_index,
            unit_row=unit_row,
            design_speed_mps=design_speed_mps,
        )
        if concept is None:
            assert build_rejection is not None
            build_rejection["severity_ratio"] = _stage0_rejection_severity(build_rejection)
            rejected.append(build_rejection)
            continue
        metric, gate_rejection = _stage0_metric_from_concept(
            cfg=cfg,
            concept=concept,
            sample_index=sample_index,
            design_speed_mps=design_speed_mps,
        )
        if metric is not None:
            accepted.append(metric)
        elif gate_rejection is not None:
            rejected.append(gate_rejection)
    return {
        "accepted": accepted,
        "rejected": rejected,
        "counts": {
            "requested": int(sample_count),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "rejection_reason_counts": dict(
                Counter(str(item["reason"]) for item in rejected)
            ),
        },
    }


def _stage0_inverse_chord_sobol_prefilter(
    *,
    cfg: BirdmanConceptConfig,
    sample_count: int,
    design_speed_mps: float,
    seed: int,
    enable_outer_chord_bump: bool = True,
    outer_chord_bump_amp_range: tuple[float, float] = OUTER_CHORD_BUMP_AMP_RANGE,
) -> dict[str, Any]:
    units = _sample_stage0_units(
        sample_count=sample_count,
        seed=seed,
        dimensions=STAGE0_SAMPLE_DIMENSIONS,
    )
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for sample_index, unit_row in enumerate(units, start=1):
        span_m = _scale_range(STAGE0_SPAN_RANGE_M, float(unit_row[0]))
        tail_volume = _scale_range(STAGE0_TAIL_VOLUME_RANGE, float(unit_row[1]))
        a3 = _scale_range(STAGE0_A3_RANGE, float(unit_row[2]))
        a5 = _scale_range(STAGE0_A5_RANGE, float(unit_row[3]))
        cl_controls = tuple(
            _scale_range(bounds, float(unit_row[index]))
            for index, bounds in enumerate(INVERSE_CHORD_CL_CONTROL_BOUNDS, start=4)
        )
        if enable_outer_chord_bump:
            outer_chord_bump_amp = _scale_range(
                tuple(float(value) for value in outer_chord_bump_amp_range),
                float(unit_row[8]),
            )
        else:
            outer_chord_bump_amp = 0.0
        metric, rejection = _build_inverse_chord_stage0_metric(
            cfg=cfg,
            sample_index=sample_index,
            span_m=span_m,
            tail_volume_coefficient=tail_volume,
            a3=a3,
            a5=a5,
            cl_controls=cl_controls,
            design_speed_mps=design_speed_mps,
            outer_chord_bump_amp=outer_chord_bump_amp,
        )
        if metric is not None:
            accepted.append(metric)
        elif rejection is not None:
            rejected.append(rejection)
    return {
        "accepted": accepted,
        "rejected": rejected,
        "counts": {
            "requested": int(sample_count),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "rejection_reason_counts": dict(
                Counter(str(item["reason"]) for item in rejected)
            ),
        },
    }


def _select_stage1_inputs(
    accepted_metrics: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    count = max(0, int(top_k))
    if count == 0:
        return []
    selected: dict[int, dict[str, Any]] = {}

    def _add(records: list[dict[str, Any]]) -> None:
        for record in records:
            if len(selected) >= count:
                return
            selected.setdefault(int(record["sample_index"]), record)

    per_lane = max(1, count // 4)
    _add(
        sorted(
            accepted_metrics,
            key=lambda record: (
                -float(record["geometry"]["aspect_ratio"]),
                int(record["sample_index"]),
            ),
        )[:per_lane]
    )
    _add(
        sorted(
            accepted_metrics,
            key=lambda record: (
                float(record["target_fourier_power_proxy"]["power_required_w"]),
                -float(record["geometry"]["aspect_ratio"]),
            ),
        )[:per_lane]
    )
    _add(
        sorted(
            accepted_metrics,
            key=lambda record: (
                -float(record["target_fourier_power_proxy"]["power_margin_w"]),
                float(record["target_fourier_power_proxy"]["power_required_w"]),
            ),
        )[:per_lane]
    )
    _add(sorted(accepted_metrics, key=_utilization_sort_key)[:per_lane])
    _add(
        sorted(
            accepted_metrics,
            key=lambda record: (
                float(record["target_fourier_power_proxy"]["power_required_w"]),
                -float(record["geometry"]["aspect_ratio"]),
                int(record["sample_index"]),
            ),
        )
    )
    return list(selected.values())[:count]


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
        "highest_AR_physical_accepted": sorted(
            records,
            key=lambda record: (
                -float(record["geometry"]["aspect_ratio"]),
                int(record["sample_index"]),
            ),
        )[:count],
        "best_avl_cdi_power_proxy_accepted": sorted(
            records,
            key=lambda record: (
                float(record["avl_cdi_power_proxy"]["power_required_w"]),
                -float(record["geometry"]["aspect_ratio"]),
                int(record["sample_index"]),
            ),
        )[:count],
        "best_power_margin_accepted": sorted(
            records,
            key=lambda record: (
                -float(record["avl_cdi_power_proxy"]["power_margin_w"]),
                float(record["avl_cdi_power_proxy"]["power_required_w"]),
                int(record["sample_index"]),
            ),
        )[:count],
        "lowest_utilization_accepted": sorted(records, key=_utilization_sort_key)[:count],
    }


def _record_is_engineering_candidate(record: dict[str, Any]) -> bool:
    physical = record.get("physical_acceptance", {})
    if bool(physical.get("physically_acceptable", False)):
        return True
    return str(record.get("status")) == "physically_acceptable"


def _select_engineering_leaderboards(
    records: list[dict[str, Any]],
    *,
    per_board_count: int,
) -> dict[str, list[dict[str, Any]]]:
    count = max(0, int(per_board_count))
    accepted = [record for record in records if _record_is_engineering_candidate(record)]
    rejected = [record for record in records if not _record_is_engineering_candidate(record)]

    def _failure_text(record: dict[str, Any]) -> str:
        reasons = record.get("physical_acceptance", {}).get("failure_reasons", [])
        twist_failures = record.get("twist_gate_metrics", {}).get("twist_gate_failures", [])
        return " ".join(str(item) for item in [*reasons, *twist_failures])

    twist_rejected = [
        record
        for record in rejected
        if "twist" in _failure_text(record) or not bool(
            record.get("twist_gate_metrics", {}).get("twist_physical_gates_pass", True)
        )
    ]
    tip_local_rejected = [
        record
        for record in rejected
        if any(
            token in _failure_text(record)
            for token in ("tip", "local_cl", "outer_cl", "utilization", "chord")
        )
        or not bool(record.get("tip_gate_summary", {}).get("tip_gates_pass", True))
    ]
    return {
        "highest_AR_engineering_candidate": sorted(
            accepted,
            key=lambda record: (
                -float(record["geometry"]["aspect_ratio"]),
                int(record["sample_index"]),
            ),
        )[:count],
        "best_AVL_e_CDi_candidate": sorted(
            accepted,
            key=lambda record: (
                -float(record.get("avl_reference_case", {}).get("avl_e_cdi") or -1.0),
                float(record.get("avl_cdi_power_proxy", {}).get("power_required_w") or float("inf")),
                int(record["sample_index"]),
            ),
        )[:count],
        "best_AVL_CDi_power_proxy_candidate": sorted(
            accepted,
            key=lambda record: (
                float(record.get("avl_cdi_power_proxy", {}).get("power_required_w") or float("inf")),
                -float(record.get("avl_reference_case", {}).get("avl_e_cdi") or -1.0),
                int(record["sample_index"]),
            ),
        )[:count],
        "closest_rejected_due_to_twist": sorted(
            twist_rejected,
            key=lambda record: (
                float(record.get("objective_value", float("inf"))),
                -float(record.get("geometry", {}).get("aspect_ratio", 0.0)),
                int(record.get("sample_index") or 0),
            ),
        )[:count],
        "closest_rejected_due_to_tip_or_local_cl": sorted(
            tip_local_rejected,
            key=lambda record: (
                float(record.get("objective_value", float("inf"))),
                -float(record.get("geometry", {}).get("aspect_ratio", 0.0)),
                int(record.get("sample_index") or 0),
            ),
        )[:count],
    }


def _leaderboard_memberships(
    leaderboards: dict[str, list[dict[str, Any]]],
) -> dict[int, list[str]]:
    memberships: dict[int, list[str]] = {}
    for board_name, records in leaderboards.items():
        for record in records:
            memberships.setdefault(int(record["sample_index"]), []).append(board_name)
    return memberships


def _stage1_compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_index": record.get("sample_index"),
        "status": record.get("status"),
        "physical_acceptance_status": record.get("physical_acceptance_status"),
        "failure_reasons": record.get("physical_acceptance", {}).get("failure_reasons", []),
        "geometry": record.get("geometry", {}),
        "a3_over_a1": record.get("spanload_fourier", {}).get("a3_over_a1"),
        "a5_over_a1": record.get("spanload_fourier", {}).get("a5_over_a1"),
        "target_fourier_e": record.get("spanload_fourier", {}).get("target_fourier_e"),
        "target_fourier_deviation": record.get("spanload_fourier", {}).get(
            "target_fourier_deviation"
        ),
        "avl_e_cdi": record.get("avl_reference_case", {}).get("avl_e_cdi"),
        "avl_reported_e": record.get("avl_reference_case", {}).get("avl_reported_e"),
        "trim_cd_induced": record.get("avl_reference_case", {}).get("trim_cd_induced"),
        "max_target_avl_circulation_norm_delta": record.get("avl_match_metrics", {}).get(
            "max_target_avl_circulation_norm_delta"
        ),
        "rms_target_avl_circulation_norm_delta": record.get("avl_match_metrics", {}).get(
            "rms_target_avl_circulation_norm_delta"
        ),
        "twist_gate_metrics": record.get("twist_gate_metrics", {}),
        "spanload_gate_health": record.get("spanload_gate_health", {}),
        "tip_gate_summary": record.get("tip_gate_summary", {}),
        "target_fourier_power_required_w": record.get("target_fourier_power_proxy", {}).get(
            "power_required_w"
        ),
        "avl_cdi_power_required_w": record.get("avl_cdi_power_proxy", {}).get(
            "power_required_w"
        ),
        "avl_cdi_power_margin_w": record.get("avl_cdi_power_proxy", {}).get("power_margin_w"),
        "mission_CL_req": record.get("mission_CL_req"),
        "mission_CD_wing_profile_target": record.get("mission_CD_wing_profile_target"),
        "mission_CD_wing_profile_boundary": record.get("mission_CD_wing_profile_boundary"),
        "mission_CDA_nonwing_target_m2": record.get("mission_CDA_nonwing_target_m2"),
        "mission_CDA_nonwing_boundary_m2": record.get("mission_CDA_nonwing_boundary_m2"),
        "mission_power_margin_required_w": record.get("mission_power_margin_required_w"),
        "mission_contract_source": record.get("mission_contract_source"),
        "mission_fourier_e_target": record.get("mission_fourier_e_target"),
        "mission_fourier_r3": record.get("mission_fourier_r3"),
        "mission_fourier_r5": record.get("mission_fourier_r5"),
        "mission_fourier_cl_max": record.get("mission_fourier_cl_max"),
        "mission_fourier_outer_lift_ratio": record.get("mission_fourier_outer_lift_ratio"),
        "mission_fourier_root_bending_proxy": record.get(
            "mission_fourier_root_bending_proxy"
        ),
        "target_vs_avl_rms_delta": record.get("target_vs_avl_rms_delta"),
        "target_vs_avl_max_delta": record.get("target_vs_avl_max_delta"),
        "target_vs_avl_outer_delta": record.get("target_vs_avl_outer_delta"),
        "loaded_shape_mode": record.get("loaded_shape_mode"),
        "loaded_tip_dihedral_deg": record.get("loaded_tip_dihedral_deg"),
        "loaded_tip_z_m": record.get("loaded_tip_z_m"),
        "loaded_shape_source": record.get("loaded_shape_source"),
        "jig_feasible_shadow": record.get("jig_feasible_shadow"),
        "jig_feasibility_band": record.get("jig_feasibility_band"),
        "jig_tip_deflection_m": record.get("jig_tip_deflection_m"),
        "jig_tip_deflection_ratio": record.get("jig_tip_deflection_ratio"),
        "jig_effective_dihedral_deg": record.get("jig_effective_dihedral_deg"),
        "jig_tip_deflection_preferred_status": record.get(
            "jig_tip_deflection_preferred_status"
        ),
        "jig_warning_count": record.get("jig_warning_count"),
        "jig_source_quality": record.get("jig_source_quality"),
        "profile_cd_airfoil_db": record.get("profile_cd_airfoil_db"),
        "profile_cd_airfoil_db_source_quality": record.get(
            "profile_cd_airfoil_db_source_quality"
        ),
        "cd0_total_est_airfoil_db": record.get("cd0_total_est_airfoil_db"),
        "mission_drag_budget_band_airfoil_db": record.get(
            "mission_drag_budget_band_airfoil_db"
        ),
        "profile_drag_station_warning_count": record.get(
            "profile_drag_station_warning_count"
        ),
        "min_stall_margin_airfoil_db": record.get("min_stall_margin_airfoil_db"),
        "max_station_cl_utilization_airfoil_db": record.get(
            "max_station_cl_utilization_airfoil_db"
        ),
        "profile_drag_cl_source_shape_mode": record.get(
            "profile_drag_cl_source_shape_mode"
        ),
        "profile_drag_cl_source_loaded_shape": record.get(
            "profile_drag_cl_source_loaded_shape"
        ),
        "profile_drag_cl_source_warning_count": record.get(
            "profile_drag_cl_source_warning_count"
        ),
        "sidecar_best_airfoil_assignment": record.get("sidecar_best_airfoil_assignment"),
        "sidecar_best_e_CDi": record.get("sidecar_best_e_CDi"),
        "sidecar_best_target_vs_avl_rms": record.get("sidecar_best_target_vs_avl_rms"),
        "sidecar_best_target_vs_avl_outer_delta": record.get(
            "sidecar_best_target_vs_avl_outer_delta"
        ),
        "sidecar_best_profile_cd": record.get("sidecar_best_profile_cd"),
        "sidecar_best_cd0_total_est": record.get("sidecar_best_cd0_total_est"),
        "sidecar_best_min_stall_margin": record.get("sidecar_best_min_stall_margin"),
        "sidecar_best_source_quality": record.get("sidecar_best_source_quality"),
        "sidecar_improved_vs_baseline": record.get("sidecar_improved_vs_baseline"),
        "sidecar_improvement_notes": record.get("sidecar_improvement_notes"),
        "outer_loading_diagnostics": record.get("outer_loading_diagnostics", {}),
        "objective_value": record.get("objective_value"),
    }


def _read_airfoil_dat_coordinates(path: Path) -> tuple[str, list[list[float]]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    title = Path(path).stem
    coordinates: list[list[float]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) < 2:
            title = stripped
            continue
        try:
            coordinates.append([float(parts[0]), float(parts[1])])
        except ValueError:
            title = stripped
    if len(coordinates) < 3:
        raise ValueError(f"Airfoil dat file has too few coordinates: {path}")
    return title, coordinates


def _seed_airfoil_templates() -> dict[str, Any]:
    fx_title, fx_coordinates = _read_airfoil_dat_coordinates(Path("data/airfoils/fx76mp140.dat"))
    clark_title, clark_coordinates = _read_airfoil_dat_coordinates(Path("data/airfoils/clarkysm.dat"))
    return {
        "root": {
            "template_id": fx_title,
            "source_file": "data/airfoils/fx76mp140.dat",
            "geometry_hash": "seedfx76mp140",
            "coordinates": fx_coordinates,
        },
        "mid1": {
            "template_id": fx_title,
            "source_file": "data/airfoils/fx76mp140.dat",
            "geometry_hash": "seedfx76mp140",
            "coordinates": fx_coordinates,
        },
        "mid2": {
            "template_id": clark_title,
            "source_file": "data/airfoils/clarkysm.dat",
            "geometry_hash": "seedclarkysm",
            "coordinates": clark_coordinates,
        },
        "tip": {
            "template_id": clark_title,
            "source_file": "data/airfoils/clarkysm.dat",
            "geometry_hash": "seedclarkysm",
            "coordinates": clark_coordinates,
        },
    }


def _seed_zone_airfoil_paths() -> dict[str, Path]:
    return {
        "root": Path("data/airfoils/fx76mp140.dat").resolve(),
        "mid1": Path("data/airfoils/fx76mp140.dat").resolve(),
        "mid2": Path("data/airfoils/clarkysm.dat").resolve(),
        "tip": Path("data/airfoils/clarkysm.dat").resolve(),
    }


def _station_rows_for_export(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = record.get("station_table") or []
    if not rows:
        return []
    export_rows: list[dict[str, Any]] = []
    for row in rows:
        export_rows.append(
            {
                "eta": float(row.get("eta", 0.0)),
                "y_m": float(row["y_m"]),
                "chord_m": float(row["chord_m"]),
                "twist_deg": float(row.get("twist_deg", row.get("ainc_deg", 0.0))),
                "ainc_deg": float(row.get("ainc_deg", row.get("twist_deg", 0.0))),
                "dihedral_deg": float(row.get("dihedral_deg", 0.0)),
                "reynolds": row.get("reynolds"),
                "target_cl": row.get("target_local_cl"),
                "avl_cl": row.get("avl_local_cl"),
                "target_circulation": row.get("target_circulation_proxy"),
                "avl_circulation": row.get("avl_circulation_proxy"),
                "target_avl_delta": row.get("target_minus_avl_circulation_norm"),
            }
        )
    return export_rows


def _fourier_target_rows_for_export(record: dict[str, Any]) -> list[dict[str, Any]]:
    target = record.get("mission_fourier_target") or {}
    if isinstance(target, FourierTarget):
        return target.to_rows()
    if not isinstance(target, dict):
        return []
    required = ("eta", "y", "chord_ref", "gamma_target", "lprime_target", "cl_target")
    arrays = [target.get(key) for key in required]
    if not all(isinstance(values, list | tuple) for values in arrays):
        return []
    row_count = min(len(values) for values in arrays)
    rows: list[dict[str, Any]] = []
    for index in range(row_count):
        rows.append({key: target[key][index] for key in required})
    return rows


def _airfoil_profile_drag_rows_for_export(record: dict[str, Any]) -> list[dict[str, Any]]:
    result = record.get("airfoil_profile_drag") or {}
    if isinstance(result, ProfileDragIntegrationResult):
        return [dict(row) for row in result.station_rows]
    if not isinstance(result, dict):
        return []
    rows = result.get("station_rows") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _zone_envelope_rows_for_export(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = record.get("zone_envelope") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _airfoil_sidecar_combination_rows_for_export(
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in record.get("airfoil_sidecar_combinations") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "combination_index": item.get("combination_index"),
                "status": item.get("status"),
                "is_baseline": item.get("is_baseline"),
                "assignment_label": item.get("assignment_label"),
                "CL": item.get("CL"),
                "CDi": item.get("CDi"),
                "e_CDi": item.get("e_CDi"),
                "target_vs_avl_rms": item.get("target_vs_avl_rms"),
                "target_vs_avl_max": item.get("target_vs_avl_max"),
                "target_vs_avl_outer_delta": item.get("target_vs_avl_outer_delta"),
                "profile_cd_airfoil_db": item.get("profile_cd_airfoil_db"),
                "cd0_total_est_airfoil_db": item.get("cd0_total_est_airfoil_db"),
                "mission_drag_budget_band": item.get("mission_drag_budget_band"),
                "min_stall_margin_airfoil_db": item.get(
                    "min_stall_margin_airfoil_db"
                ),
                "max_station_cl_utilization_airfoil_db": item.get(
                    "max_station_cl_utilization_airfoil_db"
                ),
                "source_quality": item.get("source_quality"),
                "profile_drag_cl_source_shape_mode": item.get(
                    "profile_drag_cl_source_shape_mode"
                ),
                "profile_drag_cl_source_loaded_shape": item.get(
                    "profile_drag_cl_source_loaded_shape"
                ),
                "profile_drag_cl_source_warning_count": item.get(
                    "profile_drag_cl_source_warning_count"
                ),
                "sidecar_summary_json_path": item.get("sidecar_summary_json_path"),
                "sidecar_profile_drag_csv_path": item.get(
                    "sidecar_profile_drag_csv_path"
                ),
                "error": item.get("error"),
            }
        )
    return rows


def _export_top_candidate_artifacts(
    *,
    cfg: BirdmanConceptConfig,
    record: dict[str, Any],
    output_dir: Path,
    rank: int,
) -> dict[str, str]:
    sample_index = int(record.get("sample_index") or rank)
    bundle_dir = Path(output_dir) / "top_candidate_exports" / f"rank_{int(rank):02d}_sample_{sample_index:04d}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    avl_record = record.get("avl_reference_case", {})
    avl_source = avl_record.get("avl_file_path")
    if avl_source is None and avl_record.get("avl_case_dir") is not None:
        avl_source = str(Path(str(avl_record["avl_case_dir"])) / "concept_wing.avl")
    avl_target = bundle_dir / "concept_wing.avl"
    if avl_source is not None and Path(str(avl_source)).is_file():
        shutil.copyfile(Path(str(avl_source)), avl_target)

    station_rows = _station_rows_for_export(record)
    station_table_path = bundle_dir / "station_table.json"
    station_table_path.write_text(json.dumps(_round(station_rows), indent=2) + "\n", encoding="utf-8")
    station_table_csv_path = bundle_dir / "station_table.csv"
    with station_table_csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(station_rows[0].keys()) if station_rows else [
            "eta",
            "y_m",
            "chord_m",
            "twist_deg",
            "ainc_deg",
            "dihedral_deg",
            "reynolds",
            "target_cl",
            "avl_cl",
            "target_circulation",
            "avl_circulation",
            "target_avl_delta",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_round(station_rows))
    mission_contract_payload = {
        **{field: record.get(field) for field in MISSION_CONTRACT_SHADOW_FIELDS},
        "mission_contract": record.get("mission_contract", {}),
    }
    mission_contract_json_path = bundle_dir / "mission_contract.json"
    mission_contract_json_path.write_text(
        json.dumps(_round(mission_contract_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    mission_contract_csv_path = bundle_dir / "mission_contract.csv"
    with mission_contract_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MISSION_CONTRACT_SHADOW_FIELDS))
        writer.writeheader()
        writer.writerow(
            {
                field: "" if record.get(field) is None else _round(record.get(field))
                for field in MISSION_CONTRACT_SHADOW_FIELDS
            }
        )
    fourier_target_payload = {
        **{field: record.get(field) for field in MISSION_FOURIER_SHADOW_FIELDS},
        "mission_fourier_target": record.get("mission_fourier_target", {}),
        "mission_fourier_comparison": record.get("mission_fourier_comparison", {}),
    }
    fourier_target_json_path = bundle_dir / "fourier_target.json"
    fourier_target_json_path.write_text(
        json.dumps(_round(fourier_target_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fourier_rows = _fourier_target_rows_for_export(record)
    fourier_target_csv_path = bundle_dir / "fourier_target.csv"
    with fourier_target_csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(fourier_rows[0].keys()) if fourier_rows else [
            "eta",
            "y",
            "chord_ref",
            "gamma_target",
            "lprime_target",
            "cl_target",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_round(fourier_rows))
    airfoil_profile_drag_payload = {
        **{field: record.get(field) for field in AIRFOIL_PROFILE_DRAG_SHADOW_FIELDS},
        "airfoil_profile_drag": record.get("airfoil_profile_drag", {}),
    }
    airfoil_profile_drag_json_path = bundle_dir / "airfoil_profile_drag.json"
    airfoil_profile_drag_json_path.write_text(
        json.dumps(_round(airfoil_profile_drag_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    airfoil_rows = _airfoil_profile_drag_rows_for_export(record)
    airfoil_profile_drag_csv_path = bundle_dir / "airfoil_profile_drag.csv"
    with airfoil_profile_drag_csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(airfoil_rows[0].keys()) if airfoil_rows else [
            "eta",
            "y",
            "chord",
            "Re",
            "cl_actual_avl",
            "airfoil_id",
            "cd_profile",
            "cm",
            "stall_margin_deg",
            "source_quality",
            "warning_flags",
            "profile_drag_cl_source_shape_mode",
            "profile_drag_cl_source_loaded_shape",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_round(airfoil_rows))
    zone_envelope_payload = {
        "source": "loaded_dihedral_avl_zone_envelope_shadow_v1",
        "source_mode": "shadow_no_ranking_gate",
        "zone_envelope": record.get("zone_envelope", []),
        "zone_airfoil_topk": record.get("zone_airfoil_topk", {}),
    }
    zone_envelope_json_path = bundle_dir / "zone_envelope.json"
    zone_envelope_json_path.write_text(
        json.dumps(_round(zone_envelope_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    zone_rows = _zone_envelope_rows_for_export(record)
    zone_envelope_csv_path = bundle_dir / "zone_envelope.csv"
    with zone_envelope_csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(zone_rows[0].keys()) if zone_rows else [
            "zone_name",
            "eta_min",
            "eta_max",
            "re_min",
            "re_max",
            "re_p50",
            "cl_min",
            "cl_max",
            "cl_p50",
            "cl_p90",
            "max_avl_actual_cl",
            "max_fourier_target_cl",
            "target_vs_actual_cl_delta",
            "current_airfoil_id",
            "current_stall_margin",
            "current_profile_cd_estimate",
            "source",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_round(zone_rows))
    sidecar_dir = bundle_dir / "airfoil_sidecar"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    for item in record.get("airfoil_sidecar_combinations") or []:
        if not isinstance(item, dict):
            continue
        combo_index = int(item.get("combination_index") or 0)
        summary_path = sidecar_dir / f"combination_{combo_index:02d}_summary.json"
        summary_path.write_text(
            json.dumps(_round(item), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        profile_rows = []
        profile_payload = item.get("airfoil_profile_drag") or {}
        if isinstance(profile_payload, dict):
            profile_rows = [
                dict(row)
                for row in profile_payload.get("station_rows", [])
                if isinstance(row, dict)
            ]
        profile_path = sidecar_dir / f"combination_{combo_index:02d}_profile_drag.csv"
        with profile_path.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = list(profile_rows[0].keys()) if profile_rows else [
                "eta",
                "y",
                "chord",
                "Re",
                "cl_actual_avl",
                "airfoil_id",
                "cd_profile",
                "cm",
                "stall_margin_deg",
                "source_quality",
                "warning_flags",
                "profile_drag_cl_source_shape_mode",
                "profile_drag_cl_source_loaded_shape",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(_round(profile_rows))
        item["sidecar_summary_json_path"] = str(summary_path)
        item["sidecar_profile_drag_csv_path"] = str(profile_path)
    sidecar_combinations_payload = {
        "airfoil_sidecar": record.get("airfoil_sidecar", {}),
        "airfoil_sidecar_combinations": record.get("airfoil_sidecar_combinations", []),
    }
    airfoil_sidecar_combinations_json_path = (
        bundle_dir / "airfoil_sidecar_combinations.json"
    )
    airfoil_sidecar_combinations_json_path.write_text(
        json.dumps(_round(sidecar_combinations_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sidecar_rows = _airfoil_sidecar_combination_rows_for_export(record)
    airfoil_sidecar_combinations_csv_path = (
        bundle_dir / "airfoil_sidecar_combinations.csv"
    )
    with airfoil_sidecar_combinations_csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(sidecar_rows[0].keys()) if sidecar_rows else [
            "combination_index",
            "status",
            "is_baseline",
            "assignment_label",
            "CL",
            "CDi",
            "e_CDi",
            "target_vs_avl_rms",
            "target_vs_avl_max",
            "target_vs_avl_outer_delta",
            "profile_cd_airfoil_db",
            "cd0_total_est_airfoil_db",
            "mission_drag_budget_band",
            "min_stall_margin_airfoil_db",
            "max_station_cl_utilization_airfoil_db",
            "source_quality",
            "profile_drag_cl_source_shape_mode",
            "profile_drag_cl_source_loaded_shape",
            "profile_drag_cl_source_warning_count",
            "sidecar_summary_json_path",
            "sidecar_profile_drag_csv_path",
            "error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_round(sidecar_rows))
    sidecar_best_payload = {
        **{field: record.get(field) for field in AIRFOIL_SIDECAR_SHADOW_FIELDS},
        "airfoil_sidecar_best": record.get("airfoil_sidecar_best", {}),
    }
    airfoil_sidecar_best_json_path = bundle_dir / "airfoil_sidecar_best.json"
    airfoil_sidecar_best_json_path.write_text(
        json.dumps(_round(sidecar_best_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    concept_id = f"birdman_inverse_chord_sample_{sample_index:04d}"
    script_path, metadata_path = write_concept_openvsp_handoff(
        bundle_dir=bundle_dir,
        concept_id=concept_id,
        concept_config={
            "name": concept_id,
            "geometry": record.get("geometry", {}),
            "tail_model": {
                "tail_arm_to_mac": float(cfg.tail_model.tail_arm_to_mac),
                "tail_aspect_ratio": float(cfg.tail_model.tail_aspect_ratio),
            },
        },
        stations_rows=station_rows,
        airfoil_templates=_seed_airfoil_templates(),
        lofting_guides={
            "source": SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE,
            "note": "actual_station_chord_and_residual_ainc_export_no_naca0012_main_wing_fallback",
        },
        prop_assumption={},
        concept_summary={
            "sample_index": sample_index,
            "leaderboard_memberships": record.get("leaderboard_memberships", []),
            "avl_reference_case": record.get("avl_reference_case", {}),
            "spanload_fourier": record.get("spanload_fourier", {}),
            "outer_chord_bump_amp": record.get("outer_chord_bump_amp"),
            "outer_chord_redistribution": record.get("outer_chord_redistribution"),
            "outer_loading_diagnostics": record.get("outer_loading_diagnostics"),
            "mission_contract": record.get("mission_contract", {}),
            **{field: record.get(field) for field in MISSION_CONTRACT_SHADOW_FIELDS},
            "mission_fourier_target_summary": {
                field: record.get(field) for field in MISSION_FOURIER_SHADOW_FIELDS
            },
            "mission_fourier_comparison": record.get("mission_fourier_comparison", {}),
            "loaded_shape_jig_summary": {
                field: record.get(field) for field in LOADED_SHAPE_JIG_SHADOW_FIELDS
            },
            "loaded_wing_shape": record.get("loaded_wing_shape", {}),
            "jig_feasibility": record.get("jig_feasibility", {}),
            "airfoil_profile_drag_summary": {
                field: record.get(field) for field in AIRFOIL_PROFILE_DRAG_SHADOW_FIELDS
            },
            "airfoil_profile_drag": record.get("airfoil_profile_drag", {}),
            "zone_envelope": record.get("zone_envelope", []),
            "zone_airfoil_topk": record.get("zone_airfoil_topk", {}),
            "airfoil_sidecar_summary": {
                field: record.get(field) for field in AIRFOIL_SIDECAR_SHADOW_FIELDS
            },
            "airfoil_sidecar_best": record.get("airfoil_sidecar_best", {}),
        },
    )
    return {
        "bundle_dir": str(bundle_dir),
        "avl_file_path": str(avl_target),
        "vsp_script_path": str(script_path),
        "vsp_metadata_path": str(metadata_path),
        "station_table_path": str(station_table_path),
        "station_table_csv_path": str(station_table_csv_path),
        "mission_contract_json_path": str(mission_contract_json_path),
        "mission_contract_csv_path": str(mission_contract_csv_path),
        "fourier_target_json_path": str(fourier_target_json_path),
        "fourier_target_csv_path": str(fourier_target_csv_path),
        "airfoil_profile_drag_json_path": str(airfoil_profile_drag_json_path),
        "airfoil_profile_drag_csv_path": str(airfoil_profile_drag_csv_path),
        "zone_envelope_json_path": str(zone_envelope_json_path),
        "zone_envelope_csv_path": str(zone_envelope_csv_path),
        "airfoil_sidecar_combinations_json_path": str(
            airfoil_sidecar_combinations_json_path
        ),
        "airfoil_sidecar_combinations_csv_path": str(
            airfoil_sidecar_combinations_csv_path
        ),
        "airfoil_sidecar_best_json_path": str(airfoil_sidecar_best_json_path),
    }


def _export_top_candidates(
    *,
    cfg: BirdmanConceptConfig,
    records: list[dict[str, Any]],
    output_dir: Path,
    count: int,
) -> list[dict[str, Any]]:
    unique_records: list[dict[str, Any]] = []
    seen: set[int] = set()
    for record in records:
        sample_index = int(record.get("sample_index") or -1)
        if sample_index in seen:
            continue
        seen.add(sample_index)
        unique_records.append(record)
    artifacts: list[dict[str, Any]] = []
    for rank, record in enumerate(unique_records[: max(0, int(count))], start=1):
        try:
            paths = _export_top_candidate_artifacts(
                cfg=cfg,
                record=record,
                output_dir=output_dir,
                rank=rank,
            )
            record["export_artifacts"] = paths
            artifacts.append({"sample_index": record.get("sample_index"), **paths})
        except Exception as exc:  # noqa: BLE001 - preserve smoke report even when VSP export fails.
            artifacts.append(
                {
                    "sample_index": record.get("sample_index"),
                    "rank": rank,
                    "status": "export_failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return artifacts


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
    zone_airfoil_paths: dict[str, Path] | None = None,
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
        zone_airfoil_paths=(
            _seed_zone_airfoil_paths() if zone_airfoil_paths is None else zone_airfoil_paths
        ),
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
            "avl_file_path": str(avl_path),
            "avl_case_dir": str(case_dir),
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
    loaded_shape = build_loaded_wing_shape_from_stations(
        span_m=float(concept.span_m),
        stations=stations,
        source="avl_section_z_from_wing_station_dihedral",
    )
    cl_source_shape_mode = (
        "loaded_dihedral_avl"
        if abs(float(loaded_shape.loaded_tip_z_m)) > 1.0e-9
        else "flat_or_unverified_loaded_shape"
    )
    cl_source_warning_count = int(loaded_shape.warning_count)
    if cl_source_shape_mode != "loaded_dihedral_avl":
        cl_source_warning_count += 1
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
        "avl_file_path": str(avl_path),
        "avl_case_dir": str(case_dir),
        "station_points": flat_points,
        "loaded_shape_mode": loaded_shape.loaded_shape_mode,
        "loaded_tip_dihedral_deg": float(loaded_shape.loaded_tip_dihedral_deg),
        "loaded_tip_z_m": float(loaded_shape.loaded_tip_z_m),
        "loaded_shape_source": loaded_shape.source,
        "loaded_shape_warning_count": int(loaded_shape.warning_count),
        "profile_drag_cl_source_shape_mode": cl_source_shape_mode,
        "profile_drag_cl_source_loaded_shape": cl_source_shape_mode == "loaded_dihedral_avl",
        "profile_drag_cl_source_warning_count": int(cl_source_warning_count),
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


def _station_etas(stations: tuple[WingStation, ...]) -> list[float]:
    if not stations:
        return []
    half_span_m = max(float(stations[-1].y_m), 1.0e-9)
    return [min(max(float(station.y_m) / half_span_m, 0.0), 1.0) for station in stations]


def _twist_gate_metrics(stations: tuple[WingStation, ...]) -> dict[str, Any]:
    if not stations:
        return {
            "twist_range_deg": None,
            "max_abs_flight_twist_deg": None,
            "max_adjacent_twist_jump_deg": None,
            "outer_monotonic_washout": False,
            "max_outer_wash_in_step_deg": None,
            "max_outer_washin_bump_deg": None,
            "tip_minus_eta70_twist_deg": None,
            "twist_physical_gates_pass": False,
            "twist_gate_failures": ["missing_stations"],
        }
    etas = _station_etas(stations)
    twists = [float(station.twist_deg) for station in stations]
    twist_range = max(twists) - min(twists)
    max_abs_twist = max(abs(value) for value in twists)
    adjacent_jumps = [
        abs(right - left)
        for left, right in zip(twists[:-1], twists[1:])
    ]
    max_adjacent_jump = max(adjacent_jumps, default=0.0)
    outer_pairs = [
        (eta, twist)
        for eta, twist in zip(etas, twists, strict=True)
        if eta >= OUTER_WASHOUT_START_ETA
    ]
    outer_wash_in_steps = [
        right_twist - left_twist
        for (_, left_twist), (_, right_twist) in zip(outer_pairs[:-1], outer_pairs[1:])
        if right_twist > left_twist
    ]
    max_outer_wash_in_step = max(outer_wash_in_steps, default=0.0)
    outer_monotonic = all(
        right_twist <= left_twist + 1.0e-6
        for (_, left_twist), (_, right_twist) in zip(outer_pairs[:-1], outer_pairs[1:])
    )
    root_twist = twists[0]
    bump_candidates = [
        twist - root_twist
        for eta, twist in zip(etas, twists, strict=True)
        if OUTER_WASHIN_BUMP_START_ETA <= eta <= OUTER_WASHIN_BUMP_END_ETA
    ]
    max_outer_washin_bump = max(bump_candidates, default=-float("inf"))
    eta70_twist = _linear_interp(etas, twists, 0.70)
    tip_minus_eta70 = twists[-1] - eta70_twist
    failures: list[str] = []
    if max_abs_twist > RESIDUAL_TWIST_MAX_ABS_DEG:
        failures.append("max_abs_flight_twist_exceeded")
    if twist_range > TWIST_RANGE_LIMIT_DEG:
        failures.append("twist_range_exceeded")
    if max_adjacent_jump > TWIST_ADJACENT_JUMP_LIMIT_DEG:
        failures.append("adjacent_twist_jump_exceeded")
    if not outer_monotonic and max_outer_wash_in_step > 0.60:
        failures.append("outer_monotonic_washout_failed")
    if max_outer_washin_bump > OUTER_WASHIN_BUMP_LIMIT_ABOVE_ROOT_DEG:
        failures.append("outer_washin_bump_exceeded")
    if tip_minus_eta70 > TIP_MINUS_ETA70_WASHOUT_MIN_DEG:
        failures.append("tip_minus_eta70_washout_failed")
    return {
        "twist_range_deg": float(twist_range),
        "twist_range_limit_deg": float(TWIST_RANGE_LIMIT_DEG),
        "max_abs_flight_twist_deg": float(max_abs_twist),
        "max_abs_flight_twist_limit_deg": float(RESIDUAL_TWIST_MAX_ABS_DEG),
        "max_adjacent_twist_jump_deg": float(max_adjacent_jump),
        "max_adjacent_twist_jump_limit_deg": float(TWIST_ADJACENT_JUMP_LIMIT_DEG),
        "outer_monotonic_washout": bool(outer_monotonic),
        "max_outer_wash_in_step_deg": float(max_outer_wash_in_step),
        "max_outer_wash_in_step_limit_deg": 0.60,
        "max_outer_washin_bump_deg": float(max(max_outer_washin_bump, 0.0)),
        "outer_washin_bump_limit_above_root_deg": float(
            OUTER_WASHIN_BUMP_LIMIT_ABOVE_ROOT_DEG
        ),
        "tip_minus_eta70_twist_deg": float(tip_minus_eta70),
        "tip_minus_eta70_washout_required_deg": float(TIP_MINUS_ETA70_WASHOUT_MIN_DEG),
        "twist_physical_gates_pass": not failures,
        "twist_gate_failures": failures,
    }


def _twist_smoothness_penalty(stations: tuple[WingStation, ...]) -> float:
    twists = [float(station.twist_deg) for station in stations]
    if len(twists) < 3:
        return 0.0
    return float(
        sum(
            (right - 2.0 * center + left) ** 2
            for left, center, right in zip(twists[:-2], twists[1:-1], twists[2:])
        )
    )


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


def _build_regularized_twist_initial_stations(
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
    target_section_angles: list[float] = []
    control_records: list[dict[str, float]] = []
    for eta in TWIST_CONTROL_ETAS:
        eta_for_twist = min(float(eta), INVERSE_TWIST_MAX_AERO_ETA)
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
        control_records.append(
            {
                "eta": float(eta),
                "eta_for_twist": float(eta_for_twist),
                "target_local_cl": float(target["target_local_cl"]),
                "alpha_2d_deg": float(alpha_2d_deg),
                "induced_angle_deg": float(induced_angle_deg),
                "target_section_angle_deg": float(target_section_angle_deg),
            }
        )

    root_section_angle_deg = target_section_angles[0] if target_section_angles else 0.0
    raw_controls = [
        float(concept.twist_root_deg) + float(angle) - root_section_angle_deg
        for angle in target_section_angles
    ]
    lower, upper = TWIST_BOUNDS_DEG
    controls = [float(TWIST_ROOT_ANCHOR_DEG)]
    for eta, raw_twist in zip(TWIST_CONTROL_ETAS[1:], raw_controls[1:], strict=True):
        clipped = max(float(lower), min(float(upper), float(raw_twist)))
        if eta >= OUTER_WASHOUT_START_ETA:
            clipped = min(clipped, controls[-1])
        clipped = max(controls[-1] - TWIST_ADJACENT_JUMP_LIMIT_DEG, clipped)
        clipped = min(controls[-1] + TWIST_ADJACENT_JUMP_LIMIT_DEG, clipped)
        clipped = max(controls[0] - TWIST_RANGE_LIMIT_DEG, min(controls[0], clipped))
        controls.append(float(clipped))
    eta70_twist = _linear_interp(TWIST_CONTROL_ETAS, tuple(controls), 0.70)
    controls[-1] = min(controls[-1], eta70_twist + TIP_MINUS_ETA70_WASHOUT_MIN_DEG)
    controls[-1] = max(controls[-2] - TWIST_ADJACENT_JUMP_LIMIT_DEG, controls[-1])
    inverse_stations = _stations_from_twist_controls(
        base_stations=stations,
        control_twists_deg=tuple(controls),
    )
    inverse_records = [
        {**record, "raw_twist_deg": float(raw), "twist_deg": float(twist)}
        for record, raw, twist in zip(control_records, raw_controls, controls, strict=True)
    ]
    return tuple(inverse_stations), {
        "model": "regularized_inverse_twist_initial_lift_curve",
        "zero_lift_alpha_deg": float(INVERSE_TWIST_ZERO_LIFT_ALPHA_DEG),
        "lift_curve_slope_per_rad": float(INVERSE_TWIST_LIFT_CURVE_SLOPE_PER_RAD),
        "induced_angle_model": "fourier_lifting_line_local_downwash",
        "max_aero_eta_for_tip_twist": float(INVERSE_TWIST_MAX_AERO_ETA),
        "root_twist_anchor_deg": float(TWIST_ROOT_ANCHOR_DEG),
        "control_etas": list(TWIST_CONTROL_ETAS),
        "control_twists_deg": [float(value) for value in controls],
        "twist_gate_metrics": _twist_gate_metrics(inverse_stations),
        "design_cl": float(solution["design_cl"]),
        "station_records": inverse_records,
    }


def _build_residual_twist_initial_stations(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    design_speed_mps: float,
) -> tuple[tuple[WingStation, ...], dict[str, Any]]:
    target_table, target_summary = _target_station_records(
        cfg=cfg,
        concept=concept,
        stations=stations,
        design_speed_mps=design_speed_mps,
    )
    raw_section_angles: list[float] = []
    control_records: list[dict[str, float]] = []
    for eta in TWIST_CONTROL_ETAS:
        eta_for_twist = min(float(eta), INVERSE_TWIST_MAX_AERO_ETA)
        nearest = min(
            target_table,
            key=lambda row: abs(float(row["eta"]) - eta_for_twist),
        )
        alpha_2d_deg = _alpha_2d_from_cl_deg(float(nearest["target_local_cl"]))
        induced_angle_deg = _target_induced_angle_deg(
            concept=concept,
            design_cl=float(target_summary["design_cl"]),
            eta=eta_for_twist,
        )
        section_angle = alpha_2d_deg + induced_angle_deg
        raw_section_angles.append(section_angle)
        control_records.append(
            {
                "eta": float(eta),
                "eta_for_twist": float(eta_for_twist),
                "target_local_cl": float(nearest["target_local_cl"]),
                "alpha_2d_deg": float(alpha_2d_deg),
                "induced_angle_deg": float(induced_angle_deg),
                "raw_section_angle_deg": float(section_angle),
            }
        )

    root_section_angle = raw_section_angles[0] if raw_section_angles else 0.0
    raw_residuals = [
        float(TWIST_ROOT_ANCHOR_DEG) + 0.35 * (float(angle) - root_section_angle)
        for angle in raw_section_angles
    ]
    lower, upper = TWIST_BOUNDS_DEG
    controls = [float(TWIST_ROOT_ANCHOR_DEG)]
    for eta, raw_twist in zip(TWIST_CONTROL_ETAS[1:], raw_residuals[1:], strict=True):
        clipped = max(float(lower), min(float(upper), float(raw_twist)))
        if eta >= 0.55:
            clipped = min(clipped, controls[-1] - 0.15)
        clipped = max(controls[-1] - TWIST_ADJACENT_JUMP_LIMIT_DEG, clipped)
        clipped = min(controls[-1] + TWIST_ADJACENT_JUMP_LIMIT_DEG, clipped)
        clipped = max(-RESIDUAL_TWIST_MAX_ABS_DEG, min(RESIDUAL_TWIST_MAX_ABS_DEG, clipped))
        controls.append(float(clipped))
    eta70_twist = _linear_interp(TWIST_CONTROL_ETAS, tuple(controls), 0.70)
    controls[-1] = min(controls[-1], eta70_twist + TIP_MINUS_ETA70_WASHOUT_MIN_DEG)
    controls[-1] = max(controls[-2] - TWIST_ADJACENT_JUMP_LIMIT_DEG, controls[-1])
    controls[-1] = max(-RESIDUAL_TWIST_MAX_ABS_DEG, controls[-1])
    inverse_stations = _stations_from_twist_controls(
        base_stations=stations,
        control_twists_deg=tuple(controls),
    )
    inverse_records = [
        {
            **record,
            "raw_residual_twist_deg": float(raw),
            "twist_deg": float(twist),
        }
        for record, raw, twist in zip(control_records, raw_residuals, controls, strict=True)
    ]
    return tuple(inverse_stations), {
        "model": "inverse_chord_residual_twist_initial_lift_curve",
        "zero_lift_alpha_deg": float(INVERSE_TWIST_ZERO_LIFT_ALPHA_DEG),
        "lift_curve_slope_per_rad": float(INVERSE_TWIST_LIFT_CURVE_SLOPE_PER_RAD),
        "induced_angle_model": "fourier_lifting_line_local_downwash",
        "residual_twist_fraction_of_raw_inverse": 0.35,
        "max_aero_eta_for_tip_twist": float(INVERSE_TWIST_MAX_AERO_ETA),
        "root_twist_anchor_deg": float(TWIST_ROOT_ANCHOR_DEG),
        "control_etas": list(TWIST_CONTROL_ETAS),
        "control_twists_deg": [float(value) for value in controls],
        "twist_gate_metrics": _twist_gate_metrics(inverse_stations),
        "design_cl": float(target_summary["design_cl"]),
        "station_records": inverse_records,
    }


def _build_inverse_twist_stations(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    design_speed_mps: float,
) -> tuple[tuple[WingStation, ...], dict[str, Any]]:
    return _build_regularized_twist_initial_stations(
        cfg=cfg,
        concept=concept,
        stations=stations,
        design_speed_mps=design_speed_mps,
    )


def _avl_match_metrics(station_table: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [
        abs(float(row["target_minus_avl_circulation_norm"]))
        for row in station_table
        if row.get("target_minus_avl_circulation_norm") is not None
        and float(row.get("eta", 0.0)) <= INVERSE_TWIST_MAX_AERO_ETA
    ]
    if not deltas:
        return {
            "max_target_avl_circulation_norm_delta": None,
            "rms_target_avl_circulation_norm_delta": None,
            "max_delta_station": None,
            "target_avl_delta_success": False,
        }
    max_index = max(
        range(len(station_table)),
        key=lambda index: abs(
            float(station_table[index].get("target_minus_avl_circulation_norm") or 0.0)
            if float(station_table[index].get("eta", 0.0)) <= INVERSE_TWIST_MAX_AERO_ETA
            else -1.0
        ),
    )
    max_delta = max(deltas)
    rms_delta = math.sqrt(float(sum(delta**2 for delta in deltas)) / max(len(deltas), 1))
    return {
        "max_target_avl_circulation_norm_delta": float(max_delta),
        "rms_target_avl_circulation_norm_delta": float(rms_delta),
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
        "target_avl_rms_delta_preferred": bool(rms_delta < SPANLOAD_RMS_SUCCESS_LIMIT),
    }


def _ratio_or_none(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator is None:
        return None
    denominator_float = float(denominator)
    if abs(denominator_float) <= 1.0e-9:
        return None
    return float(numerator) / denominator_float


def _outer_loading_diagnostics(
    *,
    station_table: list[dict[str, Any]],
    spanload_gate_health: dict[str, Any],
    tip_gate_summary: dict[str, Any],
    twist_gate_metrics: dict[str, Any],
) -> dict[str, Any]:
    eta_samples: dict[str, dict[str, Any]] = {}
    for eta in (0.70, 0.82, 0.90, 0.95):
        if not station_table:
            continue
        nearest = min(
            station_table,
            key=lambda row: abs(float(row.get("eta", 0.0)) - eta),
        )
        circ_ratio = _ratio_or_none(
            nearest.get("avl_circulation_norm"),
            nearest.get("target_circulation_norm"),
        )
        cl_ratio = _ratio_or_none(
            nearest.get("avl_local_cl"),
            nearest.get("target_local_cl"),
        )
        eta_samples[f"{eta:.2f}"] = {
            "requested_eta": float(eta),
            "station_eta": nearest.get("eta"),
            "y_m": nearest.get("y_m"),
            "chord_m": nearest.get("chord_m"),
            "reynolds": nearest.get("reynolds"),
            "target_circulation_norm": nearest.get("target_circulation_norm"),
            "avl_circulation_norm": nearest.get("avl_circulation_norm"),
            "avl_to_target_circulation_ratio": circ_ratio,
            "target_local_cl": nearest.get("target_local_cl"),
            "avl_local_cl": nearest.get("avl_local_cl"),
            "avl_cl_to_target_cl_ratio": cl_ratio,
            "target_clmax_utilization": nearest.get("target_clmax_utilization"),
            "ainc_deg": nearest.get("ainc_deg", nearest.get("twist_deg")),
        }

    outer_ratios = [
        float(sample["avl_to_target_circulation_ratio"])
        for key, sample in eta_samples.items()
        if float(key) >= 0.82
        and sample.get("avl_to_target_circulation_ratio") is not None
    ]
    inner_ratios = [
        _ratio_or_none(row.get("avl_circulation_norm"), row.get("target_circulation_norm"))
        for row in station_table
        if float(row.get("eta", 0.0)) <= 0.45
    ]
    inner_ratios = [float(value) for value in inner_ratios if value is not None]
    outer_underloaded = bool(outer_ratios and min(outer_ratios) < 0.85)
    inner_overloaded = bool(inner_ratios and max(inner_ratios) > 1.15)
    twist_limited = (
        not bool(twist_gate_metrics.get("twist_physical_gates_pass", False))
        or float(twist_gate_metrics.get("max_abs_flight_twist_deg") or 0.0)
        > 0.85 * RESIDUAL_TWIST_MAX_ABS_DEG
    )
    local_cl_limited = float(spanload_gate_health.get("local_margin_to_limit", 0.0)) < 0.05
    outer_cl_limited = float(spanload_gate_health.get("outer_margin_to_limit", 0.0)) < 0.05
    tip_chord_limited = float(tip_gate_summary.get("tip_chord_m") or 0.0) <= float(
        tip_gate_summary.get("tip_required_chord_m") or 0.0
    ) + 0.02
    tip_re_limited = float(tip_gate_summary.get("tip_re") or 0.0) <= float(
        tip_gate_summary.get("tip_re_preferred_min") or 0.0
    ) + 5000.0
    drivers: list[str] = []
    if outer_underloaded:
        drivers.append("outer_underloaded")
    if inner_overloaded:
        drivers.append("inner_overloaded")
    if twist_limited:
        drivers.append("twist_limited")
    if local_cl_limited:
        drivers.append("local_cl_limited")
    if outer_cl_limited:
        drivers.append("outer_cl_limited")
    if tip_chord_limited:
        drivers.append("tip_chord_limited")
    if tip_re_limited:
        drivers.append("tip_re_limited")
    return {
        "eta_samples": eta_samples,
        "outer_underloaded": outer_underloaded,
        "inner_overloaded": inner_overloaded,
        "min_outer_avl_to_target_circulation_ratio": min(outer_ratios) if outer_ratios else None,
        "max_inner_avl_to_target_circulation_ratio": max(inner_ratios) if inner_ratios else None,
        "tip_re": tip_gate_summary.get("tip_re"),
        "tip_chord_m": tip_gate_summary.get("tip_chord_m"),
        "ainc_distribution": [
            {
                "eta": row.get("eta"),
                "y_m": row.get("y_m"),
                "ainc_deg": row.get("ainc_deg", row.get("twist_deg")),
            }
            for row in station_table
        ],
        "e_cdi_loss_diagnosis": {
            "drivers": drivers,
            "primary_driver": drivers[0] if drivers else "no_clear_loss_driver",
            "notes": (
                "outer/mixed-airfoil incidence diagnosis; target_fourier_e is not ranking authority"
            ),
        },
    }


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


def _physical_acceptance_status(
    candidate: dict[str, Any],
    *,
    target_delta_is_hard_gate: bool = True,
) -> dict[str, Any]:
    reasons: list[str] = []
    avl_e_cdi = candidate.get("avl_reference_case", {}).get("avl_e_cdi")
    match = candidate.get("avl_match_metrics", {})
    max_delta = match.get("max_target_avl_circulation_norm_delta")
    twist = candidate.get("twist_gate_metrics", {})
    health = candidate.get("spanload_gate_health", {})
    tip = candidate.get("tip_gate_summary", {})
    power = candidate.get("avl_cdi_power_proxy", {})

    if avl_e_cdi is None or float(avl_e_cdi) < AVL_E_CDI_SUCCESS_FLOOR:
        reasons.append("avl_e_cdi_below_min")
    if target_delta_is_hard_gate and (
        max_delta is None or float(max_delta) >= SPANLOAD_DELTA_SUCCESS_LIMIT
    ):
        reasons.append("target_avl_max_delta_exceeded")
    if not bool(twist.get("twist_physical_gates_pass", False)):
        reasons.extend(str(reason) for reason in twist.get("twist_gate_failures", []))
        reasons.append("twist_physical_gates_failed")
    if float(health.get("local_margin_to_limit", -1.0)) < 0.0:
        reasons.append("local_cl_utilization_failed")
    if float(health.get("outer_margin_to_limit", -1.0)) < 0.0:
        reasons.append("outer_cl_utilization_failed")
    if not bool(tip.get("tip_gates_pass", False)):
        reasons.append("tip_geometry_gates_failed")
    power_margin = power.get("power_margin_w")
    power_report_ok = bool(power.get("non_catastrophic_power_margin_report", False)) or (
        isinstance(power_margin, int | float) and math.isfinite(float(power_margin))
    )
    if not power_report_ok:
        reasons.append("power_margin_report_missing")

    if (
        avl_e_cdi is not None
        and float(avl_e_cdi) >= AVL_E_CDI_SUCCESS_FLOOR
        and max_delta is not None
        and (
            float(max_delta) < SPANLOAD_DELTA_SUCCESS_LIMIT
            or not bool(target_delta_is_hard_gate)
        )
        and "twist_physical_gates_failed" in reasons
    ):
        status = "spanload_matched_but_twist_unphysical"
    elif reasons:
        status = "rejected"
    else:
        status = "physically_acceptable"
    return {
        "status": status,
        "physically_acceptable": status == "physically_acceptable",
        "failure_reasons": sorted(set(reasons)),
        "e_stretch_goal_passed": (
            False if avl_e_cdi is None else float(avl_e_cdi) >= AVL_E_CDI_STRETCH_FLOOR
        ),
    }


def _twist_objective_components(candidate: dict[str, Any]) -> dict[str, float]:
    match = candidate.get("avl_match_metrics", {})
    twist = candidate.get("twist_gate_metrics", {})
    health = candidate.get("spanload_gate_health", {})
    avl = candidate.get("avl_reference_case", {})
    power = candidate.get("avl_cdi_power_proxy", {})

    rms_delta = match.get("rms_target_avl_circulation_norm_delta")
    max_delta = match.get("max_target_avl_circulation_norm_delta")
    avl_e = avl.get("avl_e_cdi")
    range_excess = max(
        0.0,
        float(twist.get("twist_range_deg") or 0.0) - TWIST_RANGE_LIMIT_DEG,
    )
    abs_twist_excess = max(
        0.0,
        float(twist.get("max_abs_flight_twist_deg") or 0.0) - RESIDUAL_TWIST_MAX_ABS_DEG,
    )
    jump_excess = max(
        0.0,
        float(twist.get("max_adjacent_twist_jump_deg") or 0.0)
        - TWIST_ADJACENT_JUMP_LIMIT_DEG,
    )
    tip_washout_excess = max(
        0.0,
        float(twist.get("tip_minus_eta70_twist_deg") or 0.0)
        - TIP_MINUS_ETA70_WASHOUT_MIN_DEG,
    )
    outer_bump_excess = max(
        0.0,
        float(twist.get("max_outer_washin_bump_deg") or 0.0)
        - OUTER_WASHIN_BUMP_LIMIT_ABOVE_ROOT_DEG,
    )
    local_util_excess = max(0.0, -float(health.get("local_margin_to_limit", 0.0)))
    outer_util_excess = max(0.0, -float(health.get("outer_margin_to_limit", 0.0)))
    smoothness = float(candidate.get("inverse_twist", {}).get("smoothness_penalty", 0.0))
    induced_cd = float(avl.get("trim_cd_induced") or power.get("induced_cd") or 1.0)
    return {
        "load_rms": 1.0 if rms_delta is None else float(rms_delta),
        "load_max_excess": max(
            0.0,
            (1.0 if max_delta is None else float(max_delta)) - SPANLOAD_DELTA_SUCCESS_LIMIT,
        ),
        "e_shortfall": max(
            0.0,
            AVL_E_CDI_SUCCESS_FLOOR - (0.0 if avl_e is None else float(avl_e)),
        ),
        "smoothness": float(smoothness),
        "range_excess": float(range_excess),
        "abs_twist_excess": float(abs_twist_excess),
        "jump_excess": float(jump_excess),
        "tip_washout_excess": float(tip_washout_excess),
        "outer_bump_excess": float(outer_bump_excess),
        "outer_monotonic_violation": 0.0
        if bool(twist.get("outer_monotonic_washout", False))
        else 1.0,
        "local_util_excess": float(local_util_excess),
        "outer_util_excess": float(outer_util_excess),
        "induced_cd": float(induced_cd),
    }


def _twist_objective_value(candidate: dict[str, Any]) -> float:
    c = _twist_objective_components(candidate)
    return float(
        24.0 * c["load_rms"] ** 2
        + 12.0 * c["load_max_excess"] ** 2
        + 220.0 * c["e_shortfall"] ** 2
        + 0.08 * c["smoothness"]
        + 80.0 * c["range_excess"] ** 2
        + 80.0 * c["abs_twist_excess"] ** 2
        + 100.0 * c["jump_excess"] ** 2
        + 90.0 * c["tip_washout_excess"] ** 2
        + 90.0 * c["outer_bump_excess"] ** 2
        + 25.0 * c["outer_monotonic_violation"]
        + 70.0 * c["local_util_excess"] ** 2
        + 90.0 * c["outer_util_excess"] ** 2
        + 1400.0 * c["induced_cd"]
    )


def _evaluation_cache_key(
    *,
    sample_index: int,
    control_twists_deg: tuple[float, ...],
    a3: float,
    a5: float,
) -> tuple[Any, ...]:
    return (
        int(sample_index),
        *(round(float(value), 3) for value in control_twists_deg),
        round(float(a3), 4),
        round(float(a5), 4),
    )


def _evaluate_twist_design(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    sample_index: int,
    base_stations: tuple[WingStation, ...],
    stage0_metric: dict[str, Any] | None = None,
    control_twists_deg: tuple[float, ...],
    output_dir: Path,
    design_speed_mps: float,
    avl_binary: str | None,
    cache: dict[tuple[Any, ...], dict[str, Any]],
    evaluation_counter: list[int],
    status_for_ranking: str,
    target_delta_is_hard_gate: bool = True,
    a3: float | None = None,
    a5: float | None = None,
) -> dict[str, Any]:
    a3_value = float(concept.spanload_a3_over_a1 if a3 is None else a3)
    a5_value = float(concept.spanload_a5_over_a1 if a5 is None else a5)
    key = _evaluation_cache_key(
        sample_index=sample_index,
        control_twists_deg=control_twists_deg,
        a3=a3_value,
        a5=a5_value,
    )
    if key in cache:
        return cache[key]

    evaluation_counter[0] += 1
    optimized_concept = replace(
        concept,
        twist_root_deg=float(control_twists_deg[0]),
        twist_tip_deg=float(control_twists_deg[-1]),
        twist_control_points=(
            tuple(
                (float(eta), float(twist))
                for eta, twist in zip(TWIST_CONTROL_ETAS, control_twists_deg, strict=True)
            )
            + ((1.0, float(control_twists_deg[-1])),)
        ),
        spanload_a3_over_a1=a3_value,
        spanload_a5_over_a1=a5_value,
    )
    stations = _stations_from_twist_controls(
        base_stations=base_stations,
        control_twists_deg=control_twists_deg,
    )
    target_table, target_summary = _target_station_records(
        cfg=cfg,
        concept=optimized_concept,
        stations=stations,
        design_speed_mps=design_speed_mps,
    )
    avl = _run_reference_avl_case(
        cfg=cfg,
        concept=optimized_concept,
        stations=stations,
        output_dir=output_dir,
        design_speed_mps=design_speed_mps,
        design_mass_kg=float(cfg.mass.design_gross_mass_kg),
        status_for_ranking=status_for_ranking,
        avl_binary=avl_binary,
        case_tag=f"opt_{int(sample_index):04d}_{evaluation_counter[0]:04d}",
    )
    station_table = _attach_avl_to_station_table(target_table, avl)
    enriched_station_table: list[dict[str, Any]] = []
    for row in station_table:
        nearest_station = min(
            stations,
            key=lambda station: abs(float(station.y_m) - float(row["y_m"])),
        )
        enriched_station_table.append(
            {
                **row,
                "ainc_deg": float(row.get("twist_deg", nearest_station.twist_deg)),
                "dihedral_deg": float(nearest_station.dihedral_deg),
            }
        )
    station_table = enriched_station_table
    avl_induced_cd = avl.get("trim_cd_induced")
    if avl_induced_cd is None:
        avl_induced_cd = _mission_power_proxy(
            cfg=cfg,
            concept=optimized_concept,
            design_speed_mps=design_speed_mps,
        )["induced_cd"]
    target_power_proxy = _mission_power_proxy(
        cfg=cfg,
        concept=optimized_concept,
        design_speed_mps=design_speed_mps,
    )
    avl_power_proxy = _power_proxy_from_cdi(
        cfg=cfg,
        concept=optimized_concept,
        design_speed_mps=design_speed_mps,
        induced_cd=float(avl_induced_cd),
        model="fixed_airfoil_avl_cdi_drag_proxy_v1",
    )
    twist_gate_metrics = _twist_gate_metrics(stations)
    record = {
        "status": "stage1_evaluated",
        "sample_index": int(sample_index),
        "mass_authority": _mission_mass_authority(cfg, optimized_concept),
        "geometry": _geometry_summary(optimized_concept),
        "spanload_fourier": _fourier_efficiency(a3_value, a5_value),
        "spanload_gate_health": _spanload_gate_health(target_summary, cfg),
        "tip_gate_summary": _tip_gate_summary(
            cfg=cfg,
            concept=optimized_concept,
            stations=stations,
            design_speed_mps=design_speed_mps,
        ),
        "target_fourier_power_proxy": target_power_proxy,
        "avl_cdi_power_proxy": avl_power_proxy,
        "mission_power_proxy": target_power_proxy,
        "inverse_twist": {
            "model": "regularized_avl_twist_optimizer_v1",
            "architecture": (
                SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE
                if stage0_metric and stage0_metric.get("spanload_to_geometry")
                else SPANLOAD_TO_GEOMETRY_LINEAR_MODE
            ),
            "control_etas": list(TWIST_CONTROL_ETAS),
            "control_twists_deg": [float(value) for value in control_twists_deg],
            "smoothness_penalty": _twist_smoothness_penalty(stations),
            "twist_bounds_deg": list(TWIST_BOUNDS_DEG),
            "root_twist_anchor_deg": float(TWIST_ROOT_ANCHOR_DEG),
        },
        "twist_gate_metrics": twist_gate_metrics,
        "avl_reference_case": avl,
        "station_table": station_table,
        "avl_match_metrics": _avl_match_metrics(station_table),
        "gate_station_table": target_summary["gate_station_table"],
        "twist_distribution": [
            {
                "eta": float(row["eta"]),
                "y_m": float(row["y_m"]),
                "twist_deg": float(row["twist_deg"]),
            }
            for row in station_table
        ],
        "worst_station": target_summary["worst_station"],
    }
    if stage0_metric and stage0_metric.get("spanload_to_geometry") is not None:
        record["spanload_to_geometry"] = stage0_metric["spanload_to_geometry"]
    if stage0_metric is not None:
        record["outer_chord_bump_amp"] = float(
            stage0_metric.get("outer_chord_bump_amp", 0.0)
        )
        record["outer_chord_redistribution"] = stage0_metric.get(
            "outer_chord_redistribution"
        )
    record["outer_loading_diagnostics"] = _outer_loading_diagnostics(
        station_table=station_table,
        spanload_gate_health=record["spanload_gate_health"],
        tip_gate_summary=record["tip_gate_summary"],
        twist_gate_metrics=twist_gate_metrics,
    )
    record["objective_components"] = _twist_objective_components(record)
    record["objective_value"] = _twist_objective_value(record)
    record["physical_acceptance"] = _physical_acceptance_status(
        record,
        target_delta_is_hard_gate=target_delta_is_hard_gate,
    )
    record["physical_acceptance_status"] = record["physical_acceptance"]["status"]
    record["status"] = record["physical_acceptance_status"]
    record["spanload_trust_status"] = _spanload_trust_status(record)
    cache[key] = record
    return record


def _controls_from_optimizer_vector(
    vector: np.ndarray,
    *,
    optimize_spanload: bool,
    concept: GeometryConcept,
) -> tuple[tuple[float, ...], float, float]:
    lower, upper = TWIST_BOUNDS_DEG
    controls = [float(TWIST_ROOT_ANCHOR_DEG)]
    controls.extend(float(max(lower, min(upper, value))) for value in vector[:5])
    if optimize_spanload:
        a3 = float(max(STAGE0_A3_RANGE[0], min(STAGE0_A3_RANGE[1], vector[5])))
        a5 = float(max(STAGE0_A5_RANGE[0], min(STAGE0_A5_RANGE[1], vector[6])))
    else:
        a3 = float(concept.spanload_a3_over_a1)
        a5 = float(concept.spanload_a5_over_a1)
    return tuple(controls), a3, a5


def _optimize_regularized_twist_candidate(
    *,
    cfg: BirdmanConceptConfig,
    stage0_metric: dict[str, Any],
    output_dir: Path,
    design_speed_mps: float,
    avl_binary: str | None,
    optimizer_maxfev: int,
    optimizer_maxiter: int,
    optimize_spanload_coefficients: bool,
) -> dict[str, Any]:
    concept = stage0_metric["concept"]
    sample_index = int(stage0_metric["sample_index"])
    inverse_chord_mode = bool(stage0_metric.get("spanload_to_geometry"))
    base_stations = tuple(stage0_metric.get("stations") or ()) or build_linear_wing_stations(
        concept,
        stations_per_half=int(cfg.pipeline.stations_per_half),
    )
    if inverse_chord_mode:
        initial_stations, initial_summary = _build_residual_twist_initial_stations(
            cfg=cfg,
            concept=concept,
            stations=base_stations,
            design_speed_mps=design_speed_mps,
        )
    else:
        initial_stations, initial_summary = _build_regularized_twist_initial_stations(
            cfg=cfg,
            concept=concept,
            stations=base_stations,
            design_speed_mps=design_speed_mps,
        )
    initial_controls = tuple(float(value) for value in initial_summary["control_twists_deg"])
    cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    evaluation_counter = [0]
    status_for_ranking = "valid_design_cruise_same_mass_hard_gates_passed"
    best_record = _evaluate_twist_design(
        cfg=cfg,
        concept=concept,
        sample_index=sample_index,
        base_stations=base_stations,
        stage0_metric=stage0_metric,
        control_twists_deg=initial_controls,
        output_dir=output_dir,
        design_speed_mps=design_speed_mps,
        avl_binary=avl_binary,
        cache=cache,
        evaluation_counter=evaluation_counter,
        status_for_ranking=status_for_ranking,
        target_delta_is_hard_gate=not inverse_chord_mode,
    )
    if inverse_chord_mode:
        seed_controls = [
            initial_controls,
            (2.0, 1.4, 0.8, 0.0, -0.8, -1.7),
            (2.0, 1.2, 0.4, -0.4, -1.0, -1.9),
            (2.0, 1.7, 0.9, 0.1, -0.7, -1.8),
        ]
    else:
        seed_controls = [
            initial_controls,
            (2.0, 1.5, 1.2, 1.2, 1.0, 0.15),
            (2.0, 2.0, 2.0, 2.0, 1.8, 0.95),
            (2.0, 3.0, 3.0, 3.0, 3.0, 2.15),
            (2.0, 4.0, 4.0, 4.0, 4.0, 3.15),
        ]
    seen_seed_controls: set[tuple[float, ...]] = set()
    for seed_control in seed_controls:
        rounded_seed = tuple(round(float(value), 3) for value in seed_control)
        if rounded_seed in seen_seed_controls:
            continue
        seen_seed_controls.add(rounded_seed)
        seed_record = _evaluate_twist_design(
            cfg=cfg,
            concept=concept,
            sample_index=sample_index,
            base_stations=base_stations,
            stage0_metric=stage0_metric,
            control_twists_deg=tuple(float(value) for value in seed_control),
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            avl_binary=avl_binary,
            cache=cache,
            evaluation_counter=evaluation_counter,
            status_for_ranking=status_for_ranking,
            target_delta_is_hard_gate=not inverse_chord_mode,
        )
        if float(seed_record["objective_value"]) < float(best_record["objective_value"]):
            best_record = seed_record
    best_controls = tuple(float(value) for value in best_record["inverse_twist"]["control_twists_deg"])
    x0_values = list(best_controls[1:])
    bounds = [TWIST_BOUNDS_DEG for _ in range(5)]
    if optimize_spanload_coefficients:
        x0_values.extend(
            [
                float(concept.spanload_a3_over_a1),
                float(concept.spanload_a5_over_a1),
            ]
        )
        bounds.extend([STAGE0_A3_RANGE, STAGE0_A5_RANGE])
    x0 = np.asarray(x0_values, dtype=float)

    iteration_records: list[dict[str, Any]] = [
        {
            "optimizer_evaluation": 0,
            "source": "best_of_regularized_initial_seed_bank",
            "objective_value": float(best_record["objective_value"]),
            "avl_e_cdi": best_record["avl_reference_case"].get("avl_e_cdi"),
            **best_record["avl_match_metrics"],
            **best_record["twist_gate_metrics"],
        }
    ]

    def objective(vector: np.ndarray) -> float:
        nonlocal best_record
        controls, a3, a5 = _controls_from_optimizer_vector(
            np.asarray(vector, dtype=float),
            optimize_spanload=optimize_spanload_coefficients,
            concept=concept,
        )
        record = _evaluate_twist_design(
            cfg=cfg,
            concept=concept,
            sample_index=sample_index,
            base_stations=base_stations,
            stage0_metric=stage0_metric,
            control_twists_deg=controls,
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            avl_binary=avl_binary,
            cache=cache,
            evaluation_counter=evaluation_counter,
            status_for_ranking=status_for_ranking,
            target_delta_is_hard_gate=not inverse_chord_mode,
            a3=a3,
            a5=a5,
        )
        if float(record["objective_value"]) < float(best_record["objective_value"]):
            best_record = record
        return float(record["objective_value"])

    optimizer_result: dict[str, Any]
    if int(optimizer_maxfev) > 0 and len(x0) > 0:
        result = minimize(
            objective,
            x0,
            method="Powell",
            bounds=bounds,
            options={
                "maxfev": int(optimizer_maxfev),
                "maxiter": int(optimizer_maxiter),
                "xtol": 0.05,
                "ftol": 1.0e-3,
                "disp": False,
            },
        )
        final_controls, final_a3, final_a5 = _controls_from_optimizer_vector(
            np.asarray(result.x, dtype=float),
            optimize_spanload=optimize_spanload_coefficients,
            concept=concept,
        )
        final_record = _evaluate_twist_design(
            cfg=cfg,
            concept=concept,
            sample_index=sample_index,
            base_stations=base_stations,
            stage0_metric=stage0_metric,
            control_twists_deg=final_controls,
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            avl_binary=avl_binary,
            cache=cache,
            evaluation_counter=evaluation_counter,
            status_for_ranking=status_for_ranking,
            target_delta_is_hard_gate=not inverse_chord_mode,
            a3=final_a3,
            a5=final_a5,
        )
        if float(final_record["objective_value"]) < float(best_record["objective_value"]):
            best_record = final_record
        optimizer_result = {
            "method": "scipy.optimize.minimize_powell",
            "success": bool(result.success),
            "message": str(result.message),
            "nfev": int(getattr(result, "nfev", evaluation_counter[0])),
            "nit": int(getattr(result, "nit", 0)),
            "fun": float(result.fun),
            "requested_maxfev": int(optimizer_maxfev),
            "requested_maxiter": int(optimizer_maxiter),
            "optimize_spanload_coefficients": bool(optimize_spanload_coefficients),
        }
    else:
        optimizer_result = {
            "method": "regularized_initial_guess_only",
            "success": True,
            "message": "optimizer disabled by maxfev <= 0",
            "nfev": int(evaluation_counter[0]),
            "nit": 0,
            "fun": float(best_record["objective_value"]),
            "requested_maxfev": int(optimizer_maxfev),
            "requested_maxiter": int(optimizer_maxiter),
            "optimize_spanload_coefficients": bool(optimize_spanload_coefficients),
        }

    iteration_records.append(
        {
            "optimizer_evaluation": int(evaluation_counter[0]),
            "source": "best_regularized_optimizer_record",
            "objective_value": float(best_record["objective_value"]),
            "avl_e_cdi": best_record["avl_reference_case"].get("avl_e_cdi"),
            **best_record["avl_match_metrics"],
            **best_record["twist_gate_metrics"],
        }
    )
    best_record["inverse_twist"] = {
        **best_record["inverse_twist"],
        "initial_lift_curve_summary": initial_summary,
        "initial_twist_gate_metrics": _twist_gate_metrics(initial_stations),
        "optimizer_result": optimizer_result,
        "evaluation_count": int(evaluation_counter[0]),
        "iteration_records": iteration_records,
        "objective_weights": {
            "objective_authority": "primary_avl_cdi_and_avl_e_cdi_secondary_target_avl_spanload_match",
            "load_rms": 24.0,
            "load_max_excess": 12.0,
            "e_shortfall": 220.0,
            "smoothness": 0.08,
            "range_excess": 80.0,
            "abs_twist_excess": 80.0,
            "jump_excess": 100.0,
            "tip_washout_excess": 90.0,
            "outer_bump_excess": 90.0,
            "outer_monotonic_violation": 25.0,
            "local_util_excess": 70.0,
            "outer_util_excess": 90.0,
            "induced_cd": 1400.0,
        },
    }
    best_record["stage0_prefilter"] = {
        "status": stage0_metric.get("stage0_prefilter_status", "accepted"),
        "target_fourier_power_proxy": stage0_metric.get("target_fourier_power_proxy"),
        "spanload_gate_health": stage0_metric.get("spanload_gate_health"),
        "tip_gate_summary": stage0_metric.get("tip_gate_summary"),
        "spanload_to_geometry": stage0_metric.get("spanload_to_geometry"),
    }
    return best_record


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
    target_power = candidate["target_fourier_power_proxy"]
    avl_power = candidate["avl_cdi_power_proxy"]
    match = candidate["avl_match_metrics"]
    twist = candidate.get("twist_gate_metrics", {})
    outer_diag = candidate.get("outer_loading_diagnostics", {})
    physical = candidate.get("physical_acceptance", {})
    title = f"{str(candidate['status']).title()} candidate"
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
        "- Power proxies: "
        f"target_fourier {_format_float(target_power['power_required_w'], 1)} W "
        f"(CDi {_format_float(target_power['induced_cd'], 5)}); "
        f"AVL-CDi {_format_float(avl_power['power_required_w'], 1)} W "
        f"(CDi {_format_float(avl_power['induced_cd'], 5)}, "
        f"CDtotal {_format_float(avl_power['total_cd'], 5)}, "
        f"margin {_format_float(avl_power['power_margin_w'], 1)} W). "
        f"{avl_power.get('profile_drag_note')}."
    )
    if candidate.get("mission_contract") is not None:
        lines.append(
            "- Mission contract shadow: "
            f"CL_req {_format_float(candidate.get('mission_CL_req'), 3)}, "
            f"wing profile CD target/boundary "
            f"{_format_float(candidate.get('mission_CD_wing_profile_target'), 5)}/"
            f"{_format_float(candidate.get('mission_CD_wing_profile_boundary'), 5)}, "
            f"non-wing CDA target/boundary "
            f"{_format_float(candidate.get('mission_CDA_nonwing_target_m2'), 3)}/"
            f"{_format_float(candidate.get('mission_CDA_nonwing_boundary_m2'), 3)} m2; "
            "shadow only, no ranking gate."
        )
    lines.append(
        "- Fourier: "
        f"a3 {_format_float(fourier['a3_over_a1'], 3)}, "
        f"a5 {_format_float(fourier['a5_over_a1'], 3)}, "
        f"target_fourier_e {_format_float(fourier['target_fourier_e'], 4)}, "
        f"target_fourier_deviation {_format_float(fourier['target_fourier_deviation'], 4)}."
    )
    if candidate.get("mission_fourier_target") is not None:
        lines.append(
            "- Mission FourierTarget v2 shadow: "
            f"e {_format_float(candidate.get('mission_fourier_e_target'), 4)}, "
            f"r3/r5 {_format_float(candidate.get('mission_fourier_r3'), 3)}/"
            f"{_format_float(candidate.get('mission_fourier_r5'), 3)}, "
            f"cl_max {_format_float(candidate.get('mission_fourier_cl_max'), 3)}, "
            f"outer ratio {_format_float(candidate.get('mission_fourier_outer_lift_ratio'), 3)}, "
            f"root bending proxy "
            f"{_format_float(candidate.get('mission_fourier_root_bending_proxy'), 1)}; "
            "shadow only, no ranking gate."
        )
    if candidate.get("loaded_wing_shape") is not None or candidate.get("jig_feasibility") is not None:
        lines.append(
            "- Loaded shape / jig shadow: "
            f"mode {candidate.get('loaded_shape_mode')}, "
            f"tip dihedral {_format_float(candidate.get('loaded_tip_dihedral_deg'), 2)} deg, "
            f"tip z {_format_float(candidate.get('loaded_tip_z_m'), 3)} m, "
            f"jig band {candidate.get('jig_feasibility_band')}, "
            f"tip deflection {_format_float(candidate.get('jig_tip_deflection_m'), 3)} m, "
            f"effective dihedral {_format_float(candidate.get('jig_effective_dihedral_deg'), 2)} deg, "
            f"warnings {candidate.get('jig_warning_count')}; "
            "shadow only, no ranking gate."
        )
    if candidate.get("airfoil_profile_drag") is not None:
        lines.append(
            "- Airfoil DB profile drag shadow: "
            f"CD_profile {_format_float(candidate.get('profile_cd_airfoil_db'), 5)}, "
            f"CD0_total {_format_float(candidate.get('cd0_total_est_airfoil_db'), 5)}, "
            f"band {candidate.get('mission_drag_budget_band_airfoil_db')}, "
            f"min stall margin {_format_float(candidate.get('min_stall_margin_airfoil_db'), 2)} deg, "
            f"max cl util {_format_float(candidate.get('max_station_cl_utilization_airfoil_db'), 3)}, "
            f"warnings {candidate.get('profile_drag_station_warning_count')}; "
            f"Cl source {candidate.get('profile_drag_cl_source_shape_mode')}, "
            f"quality {candidate.get('profile_cd_airfoil_db_source_quality')}. "
            "shadow only, no ranking gate."
        )
    if candidate.get("airfoil_sidecar") is not None:
        lines.append(
            "- Airfoil sidecar shadow: "
            f"best {candidate.get('sidecar_best_airfoil_assignment')}, "
            f"e_CDi {_format_float(candidate.get('sidecar_best_e_CDi'), 4)}, "
            f"profile CD {_format_float(candidate.get('sidecar_best_profile_cd'), 5)}, "
            f"CD0_total {_format_float(candidate.get('sidecar_best_cd0_total_est'), 5)}, "
            f"target RMS/outer "
            f"{_format_float(candidate.get('sidecar_best_target_vs_avl_rms'), 3)}/"
            f"{_format_float(candidate.get('sidecar_best_target_vs_avl_outer_delta'), 3)}, "
            f"min stall margin {_format_float(candidate.get('sidecar_best_min_stall_margin'), 2)} deg, "
            f"quality {candidate.get('sidecar_best_source_quality')}, "
            f"improved vs baseline {candidate.get('sidecar_improved_vs_baseline')}; "
            "shadow only, no ranking gate."
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
        f"RMS {_format_float(match.get('rms_target_avl_circulation_norm_delta'), 3)} "
        f"(goal < {SPANLOAD_DELTA_SUCCESS_LIMIT:.2f}); "
        f"mission FourierTarget RMS/max/outer "
        f"{_format_float(candidate.get('target_vs_avl_rms_delta'), 3)}/"
        f"{_format_float(candidate.get('target_vs_avl_max_delta'), 3)}/"
        f"{_format_float(candidate.get('target_vs_avl_outer_delta'), 3)}; "
        f"AVL e_CDi goal >= {AVL_E_CDI_SUCCESS_FLOOR:.2f}."
    )
    eta_samples = outer_diag.get("eta_samples", {})
    if eta_samples:
        ratio_summary = ", ".join(
            f"eta {eta}: circ {_format_float(sample.get('avl_to_target_circulation_ratio'), 2)}, "
            f"cl {_format_float(sample.get('avl_cl_to_target_cl_ratio'), 2)}"
            for eta, sample in eta_samples.items()
        )
        lines.append(
            "- Outer loading diagnostics: "
            f"outer_underloaded {outer_diag.get('outer_underloaded')}; "
            f"{ratio_summary}; "
            f"drivers {outer_diag.get('e_cdi_loss_diagnosis', {}).get('drivers', [])}."
        )
    lines.append(
        "- Twist gates: "
        f"range {_format_float(twist.get('twist_range_deg'), 2)} deg, "
        f"max adjacent jump {_format_float(twist.get('max_adjacent_twist_jump_deg'), 2)} deg, "
        f"outer monotonic {twist.get('outer_monotonic_washout')}, "
        f"outer wash-in bump {_format_float(twist.get('max_outer_washin_bump_deg'), 2)} deg, "
        f"tip-eta70 {_format_float(twist.get('tip_minus_eta70_twist_deg'), 2)} deg; "
        f"pass {twist.get('twist_physical_gates_pass')}."
    )
    lines.append(
        "- Physical acceptance: "
        f"{physical.get('status', candidate.get('physical_acceptance_status'))}; "
        f"failures {physical.get('failure_reasons', [])}."
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
    lines.append("| eta | y m | chord m | Re | target cl | util | Ainc deg | target circ | AVL cl | AVL circ | AVL/target | d circ |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in candidate.get("station_table", []):
        avl_target_ratio = _ratio_or_none(
            row.get("avl_circulation_norm"),
            row.get("target_circulation_norm"),
        )
        lines.append(
            "| "
            f"{_format_float(row.get('eta'), 3)} | "
            f"{_format_float(row.get('y_m'), 2)} | "
            f"{_format_float(row.get('chord_m'), 3)} | "
            f"{_format_float(row.get('reynolds'), 0)} | "
            f"{_format_float(row.get('target_local_cl'), 3)} | "
            f"{_format_float(row.get('target_clmax_utilization'), 3)} | "
            f"{_format_float(row.get('ainc_deg', row.get('twist_deg')), 2)} | "
            f"{_format_float(row.get('target_circulation_norm'), 3)} | "
            f"{_format_float(row.get('avl_local_cl'), 3)} | "
            f"{_format_float(row.get('avl_circulation_norm'), 3)} | "
            f"{_format_float(avl_target_ratio, 3)} | "
            f"{_format_float(row.get('target_minus_avl_circulation_norm'), 3)} |"
        )
    lines.append("")
    return lines


def _leaderboard_candidate_summary(candidate: dict[str, Any]) -> str:
    geometry = candidate["geometry"]
    power = candidate["avl_cdi_power_proxy"]
    avl = candidate["avl_reference_case"]
    match = candidate["avl_match_metrics"]
    twist = candidate.get("twist_gate_metrics", {})
    outer_diag = candidate.get("outer_loading_diagnostics", {})
    return (
        f"sample {candidate['sample_index']}: "
        f"AR {_format_float(geometry['aspect_ratio'], 2)}, "
        f"span {_format_float(geometry['span_m'], 2)} m, "
        f"S {_format_float(geometry['wing_area_m2'], 2)} m2, "
        f"AVL-CDi power {_format_float(power['power_required_w'], 1)} W, "
        f"margin {_format_float(power.get('power_margin_w'), 1)} W, "
        f"AVL e_CDi {_format_float(avl.get('avl_e_cdi'), 4)}, "
        f"target max/RMS delta {_format_float(match.get('max_target_avl_circulation_norm_delta'), 3)}/"
        f"{_format_float(match.get('rms_target_avl_circulation_norm_delta'), 3)}, "
        f"mission Fourier RMS/max {_format_float(candidate.get('target_vs_avl_rms_delta'), 3)}/"
        f"{_format_float(candidate.get('target_vs_avl_max_delta'), 3)}, "
        f"airfoil-db CDp {_format_float(candidate.get('profile_cd_airfoil_db'), 5)}, "
        f"twist pass {twist.get('twist_physical_gates_pass')}, "
        f"outer_underloaded {outer_diag.get('outer_underloaded')}"
    )


def _write_markdown_report(report: dict[str, Any], path: Path) -> None:
    lines: list[str] = [
        "# Birdman Spanload / Twist Optimizer Smoke",
        "",
        "Fixed-airfoil optimizer smoke only: no CST, no XFOIL robust, no Julia worker. AVL uses the current wing-only fixed seed airfoil route for a single design-cruise reference case.",
        "",
        "## Summary",
        "",
        f"- Config: `{report['config_path']}`",
        f"- Output: `{report['output_dir']}`",
        f"- Stage 0 accepted/rejected: {report['stage0_counts']['accepted']} / {report['stage0_counts']['rejected']}",
        f"- Stage 0 rejection counts: `{report['stage0_counts']['rejection_reason_counts']}`",
        f"- Stage 1 evaluated / physically accepted: {report['stage1_counts']['evaluated']} / {report['stage1_counts']['physically_accepted']}",
        f"- Stage 1 status counts: `{report['stage1_counts']['status_counts']}`",
        f"- Design cruise smoke case: {report['design_cruise_case']['speed_mps']} m/s, {report['design_cruise_case']['mass_kg']} kg",
        f"- Candidate selection: {report['candidate_selection_rule']}",
        f"- Profile drag note: {report['profile_drag_note']}",
        f"- Mission contract shadow: {report.get('mission_contract_shadow', {}).get('mission_contract_source', 'unknown')} "
        f"({report.get('mission_contract_shadow', {}).get('ranking_behavior', 'unchanged')})",
        f"- FourierTarget v2 shadow: {report.get('mission_fourier_target_shadow', {}).get('source', 'unknown')} "
        f"({report.get('mission_fourier_target_shadow', {}).get('ranking_behavior', 'unchanged')})",
        f"- Loaded shape / jig shadow: {report.get('loaded_shape_jig_shadow', {}).get('source', 'unknown')} "
        f"({report.get('loaded_shape_jig_shadow', {}).get('ranking_behavior', 'unchanged')})",
        f"- Airfoil DB profile drag shadow: {report.get('airfoil_profile_drag_shadow', {}).get('database', 'unknown')} "
        f"({report.get('airfoil_profile_drag_shadow', {}).get('ranking_behavior', 'unchanged')})",
        f"- Airfoil zone/top-k sidecar shadow: {report.get('airfoil_sidecar_shadow', {}).get('source', 'unknown')} "
        f"({report.get('airfoil_sidecar_shadow', {}).get('ranking_behavior', 'unchanged')})",
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
    lines.append("## Stage 1 Compact Ranking")
    lines.append("")
    lines.append("| sample | status | AR | e_CDi | max delta | RMS delta | twist pass | AVL-CDi W | margin W | failures |")
    lines.append("|---:|---|---:|---:|---:|---:|---|---:|---:|---|")
    compact_records = sorted(
        report.get("stage1_records_compact", []),
        key=lambda record: (
            0 if record.get("physical_acceptance_status") == "physically_acceptable" else 1,
            -float(record.get("geometry", {}).get("aspect_ratio") or 0.0),
            float(record.get("objective_value") or float("inf")),
        ),
    )
    for record in compact_records[: max(20, len(report.get("accepted_leaderboards", {}).get("closest_rejected_high_AR", [])))]:
        geometry = record.get("geometry", {})
        twist = record.get("twist_gate_metrics", {})
        failures = ", ".join(str(reason) for reason in record.get("failure_reasons", []))
        lines.append(
            "| "
            f"{record.get('sample_index')} | "
            f"{record.get('physical_acceptance_status', record.get('status'))} | "
            f"{_format_float(geometry.get('aspect_ratio'), 2)} | "
            f"{_format_float(record.get('avl_e_cdi'), 4)} | "
            f"{_format_float(record.get('max_target_avl_circulation_norm_delta'), 3)} | "
            f"{_format_float(record.get('rms_target_avl_circulation_norm_delta'), 3)} | "
            f"{twist.get('twist_physical_gates_pass')} | "
            f"{_format_float(record.get('avl_cdi_power_required_w'), 1)} | "
            f"{_format_float(record.get('avl_cdi_power_margin_w'), 1)} | "
            f"{failures} |"
        )
    lines.append("")
    lines.append("## Candidates")
    lines.append("")
    for candidate in report["candidates"]:
        lines.extend(_markdown_candidate(candidate))
    path.write_text("\n".join(lines), encoding="utf-8")


def _engineering_read(report: dict[str, Any]) -> list[str]:
    counts = report["stage0_counts"]
    stage1_counts = report["stage1_counts"]
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
    read.append(
        "Stage 1 physical acceptance count is "
        f"{stage1_counts['physically_accepted']} / {stage1_counts['evaluated']}; "
        "AVL e alone is not treated as success."
    )
    compact = report.get("stage1_records_compact", [])
    if compact:
        best_e_record = max(
            compact,
            key=lambda item: float(item.get("avl_e_cdi") or -1.0),
        )
        best_delta_record = min(
            compact,
            key=lambda item: float(
                item.get("max_target_avl_circulation_norm_delta")
                if item.get("max_target_avl_circulation_norm_delta") is not None
                else float("inf")
            ),
        )
        read.append(
            "Best Stage 1 AVL e_CDi is "
            f"{float(best_e_record.get('avl_e_cdi') or 0.0):.3f} "
            f"(sample {best_e_record.get('sample_index')}); best max strip delta is "
            f"{float(best_delta_record.get('max_target_avl_circulation_norm_delta') or 0.0):.3f} "
            f"(sample {best_delta_record.get('sample_index')})."
        )
        if int(stage1_counts["physically_accepted"]) == 0:
            read.append(
                "No physically acceptable candidate was found inside this bounded run; this is a geometry/spanload/twist result, not an AVL-e success."
            )
    accepted_candidates = [
        item
        for item in report["candidates"]
        if bool(item.get("physical_acceptance", {}).get("physically_acceptable", False))
    ]
    if accepted_candidates:
        worst_outer = max(
            float(item["spanload_gate_health"]["max_outer_clmax_utilization"])
            for item in accepted_candidates
        )
        read.append(
            "Accepted top candidates keep outer-wing local cl/CLmax below "
            f"{worst_outer:.3f} in this proxy target calculation."
        )
    rejected_candidates = [
        item
        for item in report["candidates"]
        if not bool(item.get("physical_acceptance", {}).get("physically_acceptable", False))
    ]
    if rejected_candidates:
        reasons = sorted(
            {
                str(reason)
                for item in rejected_candidates
                for reason in item.get("physical_acceptance", {}).get("failure_reasons", [])
            }
        )
        if reasons:
            read.append(f"Closest rejected candidates fail by {', '.join(reasons)}.")
    avl_ok = [
        item
        for item in report["candidates"]
        if item["avl_reference_case"].get("status") == "ok"
    ]
    if avl_ok:
        outer_underloaded_count = sum(
            1
            for item in avl_ok
            if bool(item.get("outer_loading_diagnostics", {}).get("outer_underloaded", False))
        )
        if outer_underloaded_count:
            read.append(
                f"{outer_underloaded_count} reported AVL candidates are outer-underloaded; inspect eta 0.82/0.90/0.95 AVL-to-target circulation ratios before trusting e_CDi."
            )
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
                "Engineering caution: at least one reported candidate still required more than 8 deg of local flight twist/wash-in, so it must stay rejected even if e looks attractive."
            )
        unphysical = [
            item
            for item in avl_ok
            if item.get("physical_acceptance_status") == "spanload_matched_but_twist_unphysical"
        ]
        if unphysical:
            read.append(
                "Some candidates matched e/load but failed the twist physical contract; these are explicitly labeled spanload_matched_but_twist_unphysical."
            )
    read.append(
        "This optimizer is still fixed-airfoil/no-XFOIL: profile drag is a report-only proxy and cannot be used as a final 42.195 km completion verdict."
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
        default=Path("output/birdman_spanload_twist_optimizer_20260503_fixed_airfoil"),
    )
    parser.add_argument("--stage0-samples", type=int, default=1024)
    parser.add_argument("--stage1-top-k", type=int, default=100)
    parser.add_argument("--optimizer-maxfev", type=int, default=12)
    parser.add_argument("--optimizer-maxiter", type=int, default=4)
    parser.add_argument("--accepted-count", type=int, default=5)
    parser.add_argument("--rejected-count", type=int, default=5)
    parser.add_argument("--design-speed-mps", type=float, default=None)
    parser.add_argument("--stage0-seed", type=int, default=20260503)
    parser.add_argument(
        "--optimize-spanload-coefficients",
        action="store_true",
        help="Also let Powell adjust a3/a5 inside the bounded Fourier spanload box.",
    )
    parser.add_argument(
        "--spanload-to-geometry-mode",
        choices=(SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE, SPANLOAD_TO_GEOMETRY_LINEAR_MODE),
        default=SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE,
    )
    parser.add_argument(
        "--mission-screener-summary",
        type=Path,
        default=DEFAULT_MISSION_SCREENER_SUMMARY_PATH,
        help="Stage-0 mission screener summary.json for shadow MissionContract fields.",
    )
    parser.add_argument(
        "--mission-optimizer-handoff",
        type=Path,
        default=DEFAULT_MISSION_OPTIMIZER_HANDOFF_PATH,
        help="Stage-0 optimizer_handoff.json for shadow MissionContract fields.",
    )
    parser.add_argument(
        "--mission-drag-budget-config",
        type=Path,
        default=DEFAULT_MISSION_DRAG_BUDGET_CONFIG_PATH,
        help="Mission drag budget YAML used by the shadow MissionContract adapter.",
    )
    parser.add_argument(
        "--max-airfoil-sidecar-combinations",
        type=int,
        default=8,
        help="Maximum zone-level airfoil assignment combinations to rerun in the Phase 4 sidecar.",
    )
    parser.add_argument("--avl-binary", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_concept_config(args.config)
    design_speed_mps = _design_speed_mps(cfg, args.design_speed_mps)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.spanload_to_geometry_mode == SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE:
        stage0 = _stage0_inverse_chord_sobol_prefilter(
            cfg=cfg,
            sample_count=int(args.stage0_samples),
            design_speed_mps=design_speed_mps,
            seed=int(args.stage0_seed),
        )
    else:
        stage0 = _stage0_sobol_prefilter(
            cfg=cfg,
            sample_count=int(args.stage0_samples),
            design_speed_mps=design_speed_mps,
            seed=int(args.stage0_seed),
        )
    stage1_inputs = _select_stage1_inputs(
        list(stage0["accepted"]),
        top_k=int(args.stage1_top_k),
    )
    records: list[dict[str, Any]] = []
    for metric in stage1_inputs:
        try:
            record = _optimize_regularized_twist_candidate(
                cfg=cfg,
                output_dir=output_dir,
                design_speed_mps=design_speed_mps,
                avl_binary=args.avl_binary,
                stage0_metric=metric,
                optimizer_maxfev=int(args.optimizer_maxfev),
                optimizer_maxiter=int(args.optimizer_maxiter),
                optimize_spanload_coefficients=bool(args.optimize_spanload_coefficients),
            )
        except Exception as exc:  # noqa: BLE001 - keep smoke artifacts explicit.
            record = {
                "status": "stage1_optimizer_failed",
                "physical_acceptance_status": "rejected",
                "physical_acceptance": {
                    "status": "rejected",
                    "physically_acceptable": False,
                    "failure_reasons": ["stage1_optimizer_failed"],
                },
                "sample_index": int(metric["sample_index"]),
                "geometry": metric["geometry"],
                "spanload_fourier": metric["spanload_fourier"],
                "spanload_gate_health": metric["spanload_gate_health"],
                "tip_gate_summary": metric["tip_gate_summary"],
                "spanload_to_geometry": metric.get("spanload_to_geometry"),
                "target_fourier_power_proxy": metric["target_fourier_power_proxy"],
                "avl_cdi_power_proxy": metric["avl_cdi_power_proxy"],
                "mission_power_proxy": metric["target_fourier_power_proxy"],
                "mass_authority": _mission_mass_authority(cfg, metric["concept"]),
                "avl_reference_case": {"status": "failed", "error": str(exc)},
                "avl_match_metrics": {
                    "max_target_avl_circulation_norm_delta": None,
                    "rms_target_avl_circulation_norm_delta": None,
                },
                "twist_gate_metrics": {
                    "twist_physical_gates_pass": False,
                    "twist_gate_failures": ["stage1_optimizer_failed"],
                },
                "station_table": [],
                "gate_station_table": metric["gate_station_table"],
                "twist_distribution": [],
                "worst_station": metric["worst_station"],
                "optimizer_error": str(exc),
            }
        records.append(record)

    mission_contract_context = _mission_contract_shadow_context(
        cfg=cfg,
        summary_path=args.mission_screener_summary,
        optimizer_handoff_path=args.mission_optimizer_handoff,
        drag_budget_config_path=args.mission_drag_budget_config,
    )
    _attach_mission_contract_shadow_fields(
        records,
        cfg=cfg,
        design_speed_mps=design_speed_mps,
        context=mission_contract_context,
    )
    _attach_mission_fourier_shadow_fields(records)
    _attach_loaded_shape_jig_shadow_fields(records, cfg=cfg)
    _attach_airfoil_profile_drag_shadow_fields(records)

    physically_accepted = [
        record
        for record in records
        if bool(record.get("physical_acceptance", {}).get("physically_acceptable", False))
    ]
    rejected_records = [
        record
        for record in records
        if not bool(record.get("physical_acceptance", {}).get("physically_acceptable", False))
    ]
    if args.spanload_to_geometry_mode == SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE:
        accepted_leaderboards = _select_engineering_leaderboards(
            records,
            per_board_count=int(args.accepted_count),
        )
    else:
        accepted_leaderboards = _select_accepted_leaderboards(
            physically_accepted,
            per_board_count=int(args.accepted_count),
        )
        closest_rejected = sorted(
            rejected_records,
            key=lambda record: (
                -float(record.get("geometry", {}).get("aspect_ratio", 0.0)),
                float(record.get("objective_value", float("inf"))),
                int(record.get("sample_index") or 0),
            ),
        )[: max(0, int(args.rejected_count))]
        accepted_leaderboards["closest_rejected_high_AR"] = closest_rejected
    memberships = _leaderboard_memberships(accepted_leaderboards)
    selected_sample_ids = {
        int(record["sample_index"])
        for records_for_board in accepted_leaderboards.values()
        for record in records_for_board
        if record.get("sample_index") is not None
    }
    if not selected_sample_ids:
        fallback_records = sorted(
            records,
            key=lambda record: (
                float(record.get("objective_value", float("inf"))),
                -float(record.get("geometry", {}).get("aspect_ratio", 0.0)),
                int(record.get("sample_index") or 0),
            ),
        )[:10]
        selected_sample_ids.update(
            int(record["sample_index"])
            for record in fallback_records
            if record.get("sample_index") is not None
        )
    reported_records = [
        record for record in records if int(record.get("sample_index") or -1) in selected_sample_ids
    ]
    for record in reported_records:
        sample_index = int(record.get("sample_index") or -1)
        record["leaderboard_memberships"] = memberships.get(sample_index, [])
    _attach_airfoil_sidecar_shadow_fields(
        reported_records,
        cfg=cfg,
        output_dir=output_dir,
        design_speed_mps=design_speed_mps,
        avl_binary=args.avl_binary,
        max_airfoil_combinations=int(args.max_airfoil_sidecar_combinations),
    )
    export_artifacts = _export_top_candidates(
        cfg=cfg,
        records=reported_records,
        output_dir=output_dir,
        count=10,
    )

    report: dict[str, Any] = {
        "schema_version": "birdman_spanload_inverse_chord_residual_twist_smoke_v1",
        "config_path": str(args.config),
        "output_dir": str(output_dir),
        "route": (
            "inverse_chord_then_residual_twist_no_cst_no_xfoil"
            if args.spanload_to_geometry_mode == SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE
            else "geometry_spanload_regularized_twist_optimizer_no_cst_no_xfoil"
        ),
        "spanload_to_geometry_mode": str(args.spanload_to_geometry_mode),
        "fixed_airfoil_note": "AVL wing-only route uses the repo default fixed seed airfoils; no CST/XFOIL worker is invoked.",
        "profile_drag_note": "fixed_airfoil_no_xfoil_not_final_profile_drag",
        "search_box": {
            "span_m": list(STAGE0_SPAN_RANGE_M),
            "mean_chord_m": list(STAGE0_MEAN_CHORD_RANGE_M),
            "taper_ratio": [
                float(STAGE0_TAPER_SAMPLE_RANGE[0]),
                float(STAGE0_TAPER_UPPER_LIMIT),
            ],
            "tail_volume_coefficient": list(STAGE0_TAIL_VOLUME_RANGE),
            "a3_over_a1": list(STAGE0_A3_RANGE),
            "a5_over_a1": list(STAGE0_A5_RANGE),
            "cl_control_etas": list(INVERSE_CHORD_CL_CONTROL_ETAS),
            "cl_control_bounds": [
                [float(low), float(high)] for low, high in INVERSE_CHORD_CL_CONTROL_BOUNDS
            ],
            "wing_area_m2": list(STAGE0_WING_AREA_RANGE_M2),
            "aspect_ratio": list(STAGE0_AR_RANGE),
        },
        "candidate_selection_rule": (
            "Stage 0 Sobol prefilters Fourier target plus local-cl inverse-chord "
            "geometry gates; Stage 1 runs low-order residual AVL Ainc/twist "
            "optimization on the selected top K. Engineering leaderboards use "
            "AVL e_CDi, AVL CDi power proxy, local/outer utilization, twist gates, "
            "and tip gates; target_fourier_power_proxy is report-only."
        ),
        "success_criteria": {
            "max_target_avl_circulation_norm_delta_lt": SPANLOAD_DELTA_SUCCESS_LIMIT,
            "preferred_rms_target_avl_circulation_norm_delta_lt": SPANLOAD_RMS_SUCCESS_LIMIT,
            "avl_e_cdi_ge": AVL_E_CDI_SUCCESS_FLOOR,
            "avl_e_cdi_stretch_ge": AVL_E_CDI_STRETCH_FLOOR,
            "twist_physical_gates_pass": True,
            "tip_geometry_gates_pass": True,
            "local_and_outer_cl_utilization_pass": True,
            "target_avl_delta_is_diagnostic_not_hard_gate_for_inverse_chord_mode": (
                args.spanload_to_geometry_mode == SPANLOAD_TO_GEOMETRY_INVERSE_CHORD_MODE
            ),
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
        "mission_contract_shadow": {
            "source_mode": "shadow_no_ranking_gate",
            "mission_contract_source": str(
                mission_contract_context.get("mission_contract_source", "unknown")
            ),
            "source_paths": mission_contract_context.get("mission_contract_source_paths", {}),
            "export_fields": list(MISSION_CONTRACT_SHADOW_FIELDS),
            "ranking_behavior": "unchanged_no_rejection_no_sort_key",
        },
        "mission_fourier_target_shadow": {
            "source_mode": "shadow_no_ranking_gate",
            "source": "mission_contract_fourier_target_v2_shadow_no_ranking_gate",
            "eta_grid_count": len(MISSION_FOURIER_TARGET_ETA_GRID),
            "export_fields": list(MISSION_FOURIER_SHADOW_FIELDS),
            "ranking_behavior": "unchanged_no_rejection_no_sort_key",
            "comparison": "normalized_half_span_loading_shape_vs_avl_actual",
        },
        "loaded_shape_jig_shadow": {
            "source_mode": "shadow_no_ranking_gate",
            "source": "loaded_wing_shape_plus_jig_feasibility_shadow_v1",
            "export_fields": list(LOADED_SHAPE_JIG_SHADOW_FIELDS),
            "ranking_behavior": "unchanged_no_rejection_no_sort_key",
            "profile_drag_contract": (
                "profile drag must label whether AVL local Cl came from flat_or_unverified_loaded_shape "
                "or loaded_dihedral_avl"
            ),
        },
        "airfoil_profile_drag_shadow": {
            "source_mode": "shadow_no_ranking_gate",
            "source": "airfoil_database_profile_drag_shadow_v1",
            "database": "manual_fixtures_not_mission_grade",
            "zone_assignment": [
                assignment.to_dict() for assignment in fixed_seed_zone_airfoil_assignments()
            ],
            "export_fields": list(AIRFOIL_PROFILE_DRAG_SHADOW_FIELDS),
            "ranking_behavior": "unchanged_no_rejection_no_sort_key",
            "cl_source": "AVL actual local Cl with flat_or_loaded_shape provenance",
        },
        "airfoil_sidecar_shadow": {
            "source_mode": "shadow_no_ranking_gate",
            "source": "zone_airfoil_sidecar_avl_rerun_shadow_v1",
            "database": "manual_fixtures_not_mission_grade_sidecar",
            "zone_assignment_baseline": [
                assignment.to_dict() for assignment in fixed_seed_zone_airfoil_assignments()
            ],
            "max_airfoil_combinations": int(args.max_airfoil_sidecar_combinations),
            "export_fields": list(AIRFOIL_SIDECAR_SHADOW_FIELDS),
            "ranking_behavior": "unchanged_no_rejection_no_sort_key",
            "cl_source": "rerun AVL actual local Cl with loaded-shape provenance",
            "selection_rule": "zone-level top-k/Pareto sidecar combinations; no station-by-station greedy min-cd selection",
        },
        "stage0_counts": stage0["counts"],
        "stage1_counts": {
            "requested_top_k": int(args.stage1_top_k),
            "evaluated": len(records),
            "physically_accepted": len(physically_accepted),
            "rejected_or_unphysical": len(rejected_records),
            "status_counts": dict(Counter(str(record.get("status")) for record in records)),
        },
        "stage1_records_compact": [_stage1_compact_record(record) for record in records],
        "geometry_counts": {
            **stage0["counts"],
            "stage1_evaluated": len(records),
            "stage1_physically_accepted": len(physically_accepted),
        },
        "accepted_leaderboards": accepted_leaderboards,
        "export_artifacts": export_artifacts,
        "candidates": reported_records,
    }
    report["engineering_read"] = _engineering_read(report)

    json_path = output_dir / "spanload_design_smoke_report.json"
    md_path = output_dir / "spanload_design_smoke_report.md"
    json_path.write_text(json.dumps(_round(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_markdown_report(_round(report), md_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
