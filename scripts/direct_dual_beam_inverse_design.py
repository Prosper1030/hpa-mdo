#!/usr/bin/env python3
"""Inverse-design load-refresh refinement for the direct dual-beam V2 path."""

from __future__ import annotations

import argparse
import csv
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from itertools import product
import json
import math
from pathlib import Path
import sys
from time import perf_counter
from typing import Iterable

import numpy as np
from scipy.optimize import minimize

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper, VSPBuilder, VSPAeroParser
from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import (
    AnalysisModeName,
    INVERSE_MARGIN_NAMES,
    SparOptimizer,
    build_frozen_load_inverse_design_from_mainline,
    build_inverse_design_margins,
    shape_to_dict,
    write_shape_csv_from_template,
)
from hpa_mdo.structure.inverse_design import predict_loaded_shape
from hpa_mdo.structure.rib_surrogate import (
    RibBaySurrogateSummary,
    build_rib_bay_surrogate_summary,
)
from hpa_mdo.structure.rib_properties import (
    build_default_rib_catalog,
    derive_warping_knockdown,
)
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.structure.dual_beam_mainline import (
    build_dual_beam_mainline_model,
    run_dual_beam_mainline_kernel,
)
from hpa_mdo.structure.optimizer import OptimizationResult
from hpa_mdo.structure.fem.elements import _rotation_matrix
from hpa_mdo.utils.cad_export import export_step_from_csv
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report
from scripts.direct_dual_beam_v2 import (
    HARD_MARGIN_NAMES,
    BaselineDesign,
    ReducedMapConfig,
    SCALE_NAMES,
    build_candidate_hard_margins,
    build_reduced_map_config,
    decode_reduced_variables,
    design_from_reduced_variables,
    hard_violation_score_from_margins,
)


FAILED_MASS_KG = 1.0e12
FAILED_MARGIN = -1.0e3
ALL_MARGIN_NAMES = HARD_MARGIN_NAMES + INVERSE_MARGIN_NAMES
CLEARANCE_RISK_WALL_NAMES = (
    "rear_thickness_step_margin_min_m",
    "main_radius_taper_margin_min_m",
    "rear_radius_taper_margin_min_m",
)
CLEARANCE_RISK_BUFFER_BY_MARGIN_NAME = {
    "rear_thickness_step_margin_min_m": 0.25e-3,
    "main_radius_taper_margin_min_m": 0.50e-3,
    "rear_radius_taper_margin_min_m": 0.50e-3,
}
LEGACY_AERO_SOURCE_MODE = "legacy_refresh"
CANDIDATE_RERUN_AERO_SOURCE_MODE = "candidate_rerun_vspaero"
DEFAULT_CANDIDATE_AOA_SWEEP_DEG = (-2.0, 0.0, 2.0, 4.0, 6.0, 8.0)
RIB_ZONEWISE_OFF_MODE = "off"
RIB_ZONEWISE_LIMITED_MODE = "limited_zonewise"
DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE = 2
DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG = 0.15
RIB_MIX_FAMILY_EXCESS_PENALTY_KG = 100.0
DEFAULT_ZONEWISE_RIB_PROFILE_KEYS = (
    "baseline_uniform",
    "inboard_reinforced_mix",
    "outboard_relaxed_mix",
)


@dataclass(frozen=True)
class MandatoryRibStation:
    y_m: float
    labels: tuple[str, ...]


@dataclass(frozen=True)
class ZoneWiseRibZone:
    zone_index: int
    zone_key: str
    y_start_m: float
    y_end_m: float
    y_center_m: float
    span_m: float
    start_labels: tuple[str, ...]
    end_labels: tuple[str, ...]
    family_key: str
    family_label: str
    target_pitch_m: float
    realized_pitch_m: float
    optional_rib_count: int
    bay_count: int
    derived_warping_knockdown: float


@dataclass(frozen=True)
class ZoneWiseRibDesignSummary:
    enabled: bool
    design_key: str
    design_label: str
    design_mode: str
    mix_mode: str
    max_unique_families: int
    within_unique_family_limit: bool
    unique_family_count: int
    unique_family_keys: tuple[str, ...]
    family_switch_count: int
    family_switch_penalty_kg: float
    family_mix_cap_penalty_kg: float
    objective_penalty_kg: float
    mandatory_station_count: int
    mandatory_stations_m: tuple[float, ...]
    effective_warping_knockdown: float
    representative_family_key: str | None
    representative_spacing_m: float | None
    zone_count: int
    zones: tuple[ZoneWiseRibZone, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class InverseCandidate:
    z: np.ndarray
    source: str
    message: str
    eval_wall_time_s: float
    main_plateau_scale: float
    main_taper_fill: float
    rear_radius_scale: float
    rear_outboard_fraction: float
    wall_thickness_fraction: float
    main_t_seg_m: np.ndarray
    main_r_seg_m: np.ndarray
    rear_t_seg_m: np.ndarray
    rear_r_seg_m: np.ndarray
    tube_mass_kg: float
    total_structural_mass_kg: float
    equivalent_failure_index: float
    equivalent_buckling_index: float
    equivalent_tip_deflection_m: float
    equivalent_twist_max_deg: float
    analysis_succeeded: bool
    geometry_validity_succeeded: bool
    loaded_shape_main_z_error_max_m: float
    loaded_shape_main_z_error_rms_m: float
    loaded_shape_twist_error_max_deg: float
    loaded_shape_twist_error_rms_deg: float
    loaded_shape_normalized_error: float
    loaded_shape_penalty_kg: float
    clearance_risk_score: float
    clearance_hotspot_count: int
    clearance_hotspot_mean_m: float
    clearance_penalty_kg: float
    active_wall_risk_score: float
    active_wall_tight_count: int
    active_wall_penalty_kg: float
    technically_clearance_fragile: bool
    objective_value_kg: float
    target_shape_error_max_m: float
    target_shape_error_rms_m: float
    jig_ground_clearance_min_m: float
    jig_ground_clearance_margin_m: float
    max_jig_vertical_prebend_m: float
    max_jig_vertical_curvature_per_m: float
    safety_passed: bool
    manufacturing_passed: bool
    overall_feasible: bool
    mass_margin_kg: float
    target_mass_passed: bool
    overall_target_feasible: bool
    failures: tuple[str, ...]
    hard_margins: dict[str, float]
    hard_violation_score: float
    target_violation_score: float
    rib_bay_surrogate: RibBaySurrogateSummary | None = field(default=None, repr=False)
    rib_design: ZoneWiseRibDesignSummary | None = field(default=None, repr=False)
    inverse_result: object | None = field(default=None, repr=False)
    equivalent_result: OptimizationResult | None = field(default=None, repr=False)
    mainline_model: object | None = field(default=None, repr=False)
    production_result: object | None = field(default=None, repr=False)


@dataclass
class CandidateArchive:
    target_mass_kg: float | None = None
    candidates: list[InverseCandidate] = field(default_factory=list)
    best_feasible: InverseCandidate | None = None
    best_violation: InverseCandidate | None = None
    best_target_feasible: InverseCandidate | None = None
    best_target_violation: InverseCandidate | None = None

    def add(self, cand: InverseCandidate) -> None:
        self.candidates.append(cand)
        if cand.overall_feasible:
            if self.best_feasible is None or _feasible_key(cand) < _feasible_key(self.best_feasible):
                self.best_feasible = cand
        if self.best_violation is None or _violation_key(cand) < _violation_key(self.best_violation):
            self.best_violation = cand
        if self.target_mass_kg is not None:
            if cand.overall_target_feasible:
                if (
                    self.best_target_feasible is None
                    or _feasible_key(cand) < _feasible_key(self.best_target_feasible)
                ):
                    self.best_target_feasible = cand
            if (
                self.best_target_violation is None
                or _target_violation_key(cand) < _target_violation_key(self.best_target_violation)
            ):
                self.best_target_violation = cand

    @property
    def selected(self) -> InverseCandidate | None:
        if self.target_mass_kg is not None:
            return self.best_target_feasible or self.best_target_violation or self.best_feasible or self.best_violation
        return self.best_feasible or self.best_violation

    @property
    def feasible_count(self) -> int:
        return sum(1 for cand in self.candidates if cand.overall_feasible)

    @property
    def target_feasible_count(self) -> int:
        if self.target_mass_kg is None:
            return self.feasible_count
        return sum(1 for cand in self.candidates if cand.overall_target_feasible)

    def ranked_feasible(self) -> list[InverseCandidate]:
        return sorted(
            (cand for cand in self.candidates if cand.overall_feasible),
            key=_feasible_key,
        )

    def ranked_target_feasible(self) -> list[InverseCandidate]:
        return sorted(
            (cand for cand in self.candidates if cand.overall_target_feasible),
            key=_feasible_key,
        )

    def ranked_by_violation(self) -> list[InverseCandidate]:
        if self.target_mass_kg is not None:
            return sorted(self.candidates, key=_target_violation_key)
        return sorted(self.candidates, key=_violation_key)

    def local_refine_starts(
        self,
        *,
        feasible_limit: int,
        near_feasible_limit: int,
        max_starts: int | None = None,
        baseline: InverseCandidate | None = None,
    ) -> tuple[InverseCandidate, ...]:
        ranked: list[InverseCandidate] = []
        seen: set[tuple[float, ...]] = set()

        def _add(candidate: InverseCandidate | None) -> None:
            if candidate is None:
                return
            key = (
                tuple(np.round(np.asarray(candidate.z, dtype=float).reshape(-1), 10)),
                None if candidate.rib_design is None else candidate.rib_design.design_key,
            )
            if key in seen:
                return
            seen.add(key)
            ranked.append(candidate)

        feasible_pool = (
            self.ranked_target_feasible()
            if self.target_mass_kg is not None and self.ranked_target_feasible()
            else self.ranked_feasible()
        )
        for candidate in feasible_pool[: max(0, int(feasible_limit))]:
            _add(candidate)

        near_feasible = [
            cand
            for cand in self.ranked_by_violation()
            if (
                not (
                    cand.overall_target_feasible if self.target_mass_kg is not None else cand.overall_feasible
                )
            )
            and cand.analysis_succeeded
            and np.isfinite(cand.total_structural_mass_kg)
        ]
        for candidate in near_feasible[: max(0, int(near_feasible_limit))]:
            _add(candidate)

        _add(self.selected)
        _add(baseline)
        if max_starts is not None:
            ranked = ranked[: max(0, int(max_starts))]
        return tuple(ranked)


@dataclass(frozen=True)
class LocalRefineAttempt:
    seed_source: str
    seed_mass_kg: float
    seed_overall_feasible: bool
    seed_hard_violation_score: float
    end_source: str
    end_mass_kg: float
    end_overall_feasible: bool
    success: bool
    message: str
    nfev: int
    nit: int


@dataclass(frozen=True)
class LocalRefineSummary:
    coarse_selected_source: str
    coarse_selected_mass_kg: float
    coarse_candidate_count: int
    coarse_feasible_count: int
    coarse_target_feasible_count: int
    seed_count: int
    start_source: str
    start_mass_kg: float
    end_mass_kg: float
    success: bool
    message: str
    nfev: int
    nit: int
    early_stop_triggered: bool = False
    early_stop_reason: str | None = None
    attempts: tuple[LocalRefineAttempt, ...] = ()


@dataclass(frozen=True)
class ArtifactBundle:
    target_shape_csv: str | None = None
    jig_shape_csv: str | None = None
    loaded_shape_csv: str | None = None
    deflection_csv: str | None = None
    jig_step_path: str | None = None
    loaded_step_path: str | None = None
    step_engine: str | None = None
    step_error: str | None = None
    loaded_step_error: str | None = None
    diagnostics_json: str | None = None
    validity_summary_json: str | None = None
    wire_rigging_json: str | None = None
    aero_contract_json: str | None = None


@dataclass(frozen=True)
class ClearanceHotspot:
    rank: int
    spar: str
    side: str
    node_index: int
    y_m: float
    z_m: float
    clearance_m: float


@dataclass(frozen=True)
class ClearanceRiskMetrics:
    threshold_m: float
    top_k: int
    minimum_clearance_m: float
    hotspot_mean_clearance_m: float
    hotspot_count_below_threshold: int
    risk_score: float
    fragile: bool
    hotspots: tuple[ClearanceHotspot, ...]


@dataclass(frozen=True)
class ActiveWallEntry:
    name: str
    category: str
    margin: float
    buffer: float
    risk_score: float
    location: str
    boundary_state: str
    detail: str


@dataclass(frozen=True)
class ActiveWallDiagnostics:
    principal_bottleneck: str
    primary_driver: str
    active_wall_risk_score: float
    tight_wall_count: int
    geometry_walls: tuple[ActiveWallEntry, ...]
    reduced_variable_bounds: tuple[ActiveWallEntry, ...]
    lighten_probes: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class LiftWireRiggingRecord:
    identifier: str
    side: str
    attach_node_index: int
    attach_y_m: float
    attach_point_loaded_m: tuple[float, float, float]
    anchor_point_m: tuple[float, float, float]
    L_flight_m: float
    delta_L_m: float
    L_cut_m: float
    tension_force_n: float
    vertical_reaction_n: float
    allowable_tension_n: float | None
    tension_margin_n: float | None
    attach_label: str


@dataclass(frozen=True)
class InverseOutcome:
    success: bool
    feasible: bool
    target_mass_kg: float | None
    message: str
    total_wall_time_s: float
    baseline_eval_wall_time_s: float
    nfev: int
    nit: int
    equivalent_analysis_calls: int
    production_analysis_calls: int
    unique_evaluations: int
    cache_hits: int
    feasible_count: int
    target_feasible_count: int
    baseline: InverseCandidate
    best_overall_feasible: InverseCandidate | None
    best_target_feasible: InverseCandidate | None
    coarse_selected: InverseCandidate
    coarse_candidate_count: int
    coarse_feasible_count: int
    coarse_target_feasible_count: int
    selected: InverseCandidate
    local_refine: LocalRefineSummary | None
    active_wall_diagnostics: ActiveWallDiagnostics | None
    manufacturing_limit_source: str
    max_jig_vertical_prebend_limit_m: float | None
    max_jig_vertical_curvature_limit_per_m: float | None
    artifacts: ArtifactBundle | None = None


@dataclass(frozen=True)
class RefreshLoadMetrics:
    total_lift_half_n: float
    total_drag_half_n: float
    total_abs_torque_half_nm: float
    max_lift_per_span_npm: float
    max_abs_torque_per_span_nmpm: float
    twist_abs_max_deg: float
    aoa_eff_min_deg: float
    aoa_eff_max_deg: float
    aoa_clip_fraction: float


@dataclass(frozen=True)
class ForwardRefreshCheck:
    previous_iteration_index: int
    target_shape_error_max_m: float
    target_shape_error_rms_m: float
    equivalent_tip_deflection_m: float
    equivalent_twist_max_deg: float


@dataclass
class RefreshIterationResult:
    iteration_index: int
    load_source: str
    outcome: InverseOutcome
    load_metrics: RefreshLoadMetrics
    mapped_loads: dict = field(repr=False)
    map_config_summary: dict[str, float] = field(default_factory=dict)
    dynamic_design_space_applied: bool = False
    forward_check: ForwardRefreshCheck | None = None
    lift_rms_delta_npm: float | None = None
    lift_max_abs_delta_npm: float | None = None
    torque_rms_delta_nmpm: float | None = None
    torque_max_abs_delta_nmpm: float | None = None
    mass_delta_kg: float | None = None
    inverse_target_error_delta_m: float | None = None
    ground_clearance_delta_m: float | None = None
    prebend_delta_m: float | None = None
    curvature_delta_per_m: float | None = None
    failure_delta: float | None = None
    buckling_delta: float | None = None
    tip_deflection_delta_m: float | None = None
    twist_delta_deg: float | None = None


@dataclass(frozen=True)
class RefreshRefinementOutcome:
    refresh_steps_requested: int
    refresh_steps_completed: int
    dynamic_design_space_enabled: bool
    dynamic_design_space_rebuilds: int
    converged: bool
    convergence_reason: str | None
    manufacturing_limit_source: str
    max_jig_vertical_prebend_limit_m: float | None
    max_jig_vertical_curvature_limit_per_m: float | None
    iterations: tuple[RefreshIterationResult, ...]
    artifacts: ArtifactBundle | None = None
    aero_contract: "CandidateAeroContract | None" = None

    @property
    def final_iteration(self) -> RefreshIterationResult:
        if not self.iterations:
            raise RuntimeError("Refresh refinement outcome has no iterations.")
        return self.iterations[-1]


@dataclass(frozen=True)
class CandidateAeroContract:
    source_mode: str
    baseline_load_source: str
    refresh_load_source: str
    load_ownership: str
    artifact_ownership: str
    requested_knobs: dict[str, float]
    aoa_sweep_deg: tuple[float, ...]
    selected_cruise_aoa_deg: float
    geometry_artifacts: dict[str, str | None]
    notes: tuple[str, ...] = ()


def _parse_grid(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Grid specification must contain at least one float.")
    for value in values:
        if value < -1.0e-12 or value > 1.0 + 1.0e-12:
            raise ValueError("Grid fractions must stay within [0, 1].")
    return values


def _parse_control_fractions(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Control-station specification must contain at least one float.")
    for value in values:
        if value < -1.0e-12 or value > 1.0 + 1.0e-12:
            raise ValueError("Control-station fractions must stay within [0, 1].")
    return values


def _mm(value_m: float | None) -> float:
    if value_m is None:
        return float("nan")
    return float(value_m) * 1000.0


def _status(flag: bool) -> str:
    return "PASS" if flag else "FAIL"


def _fmt_array_mm(values_m: np.ndarray) -> str:
    values_mm = np.asarray(values_m, dtype=float) * 1000.0
    return "[" + ", ".join(f"{value:.3f}" for value in values_mm) + "]"


def _resolve_optional_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return str(Path(text).expanduser().resolve())


def _half_span_m(aircraft) -> float:
    wing = getattr(aircraft, "wing", None)
    y_values = None if wing is None else getattr(wing, "y", None)
    if y_values is not None:
        y_arr = np.asarray(y_values, dtype=float).reshape(-1)
        if y_arr.size:
            return float(np.max(y_arr))
    raise ValueError("Aircraft wing geometry must expose spanwise y stations for rib integration.")


def _collect_mandatory_rib_stations(cfg, aircraft) -> tuple[MandatoryRibStation, ...]:
    half_span_m = _half_span_m(aircraft)
    labels_by_station: dict[float, list[str]] = {}

    def _add_station(y_m: float, label: str) -> None:
        y_value = round(float(y_m), 9)
        labels = labels_by_station.setdefault(y_value, [])
        if label not in labels:
            labels.append(label)

    _add_station(0.0, "root")
    _add_station(half_span_m, "tip_boundary")

    cumulative = 0.0
    for idx, segment_length_m in enumerate(getattr(cfg.main_spar, "segments", ()) or (), start=1):
        cumulative += float(segment_length_m)
        if 1.0e-9 < cumulative < half_span_m - 1.0e-9:
            _add_station(cumulative, f"joint_{idx}")

    lift_wires = getattr(cfg, "lift_wires", None)
    if lift_wires is not None and bool(getattr(lift_wires, "enabled", False)):
        for idx, attachment in enumerate(getattr(lift_wires, "attachments", ()) or (), start=1):
            label = getattr(attachment, "label", None) or f"wire_attach_{idx}"
            _add_station(float(getattr(attachment, "y")), str(label))

    stations = [
        MandatoryRibStation(y_m=float(y_m), labels=tuple(labels))
        for y_m, labels in sorted(labels_by_station.items(), key=lambda item: float(item[0]))
    ]
    if len(stations) < 2:
        raise ValueError("Zone-wise rib contract needs at least two mandatory rib stations.")
    return tuple(stations)


def _clamp_rib_pitch_m(family, pitch_m: float) -> float:
    return float(
        min(
            float(family.spacing_guidance.max_m),
            max(float(family.spacing_guidance.min_m), float(pitch_m)),
        )
    )


def _realized_zone_pitch_m(span_m: float, target_pitch_m: float) -> tuple[int, int, float]:
    bay_count = max(1, int(math.ceil(float(span_m) / max(float(target_pitch_m), 1.0e-9) - 1.0e-9)))
    optional_rib_count = max(0, bay_count - 1)
    realized_pitch_m = float(span_m) / float(bay_count)
    return optional_rib_count, bay_count, realized_pitch_m


def _resolve_zonewise_rib_designs(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    zonewise_mode: str,
    family_switch_penalty_kg: float,
    family_mix_max_unique: int,
) -> tuple[ZoneWiseRibDesignSummary, ...]:
    rib_cfg = getattr(cfg, "rib", None)
    if rib_cfg is None or not bool(getattr(rib_cfg, "enabled", True)):
        effective_knockdown = float(
            getattr(getattr(cfg, "safety", None), "dual_spar_warping_knockdown", 1.0)
        )
        return (
            ZoneWiseRibDesignSummary(
                enabled=False,
                design_key="rib_disabled",
                design_label="Rib contract disabled",
                design_mode="disabled",
                mix_mode="disabled",
                max_unique_families=0,
                within_unique_family_limit=True,
                unique_family_count=0,
                unique_family_keys=(),
                family_switch_count=0,
                family_switch_penalty_kg=0.0,
                family_mix_cap_penalty_kg=0.0,
                objective_penalty_kg=0.0,
                mandatory_station_count=0,
                mandatory_stations_m=(),
                effective_warping_knockdown=effective_knockdown,
                representative_family_key=None,
                representative_spacing_m=None,
                zone_count=0,
                zones=(),
                notes=("cfg.rib.enabled=false; zone-wise rib search is disabled.",),
            ),
        )

    catalog = build_default_rib_catalog(getattr(rib_cfg, "catalog_path", None))
    baseline_family_key = str(getattr(rib_cfg, "family", None) or catalog.default_family)
    baseline_family = catalog.family(baseline_family_key)
    baseline_pitch_m = float(
        getattr(rib_cfg, "spacing_m", None) or baseline_family.spacing_guidance.nominal_m
    )
    reinforced_family = catalog.families.get("capped_balsa_box_4mm", baseline_family)
    light_family = catalog.families.get("foam_core_glass_cap_5mm", baseline_family)
    stations = _collect_mandatory_rib_stations(cfg, aircraft)
    half_span_m = _half_span_m(aircraft)
    wire_attach_y_m = [
        float(getattr(attachment, "y"))
        for attachment in (getattr(getattr(cfg, "lift_wires", None), "attachments", ()) or ())
    ]
    inboard_reinforced_limit_m = max(wire_attach_y_m) if wire_attach_y_m else 0.45 * half_span_m
    outboard_light_limit_m = 0.68 * half_span_m

    if zonewise_mode == RIB_ZONEWISE_OFF_MODE:
        profile_keys = ("legacy_uniform",)
    else:
        profile_keys = DEFAULT_ZONEWISE_RIB_PROFILE_KEYS

    def _zone_family_and_pitch(
        *,
        profile_key: str,
        y_center_m: float,
        zone_index: int,
    ) -> tuple[object, float, str]:
        if profile_key in {"legacy_uniform", "baseline_uniform"}:
            return baseline_family, baseline_pitch_m, "single_family_uniform"
        if profile_key == "inboard_reinforced_mix":
            if y_center_m <= inboard_reinforced_limit_m + 1.0e-9:
                return (
                    reinforced_family,
                    0.90 * float(reinforced_family.spacing_guidance.nominal_m),
                    "limited_zonewise_mix",
                )
            return baseline_family, baseline_pitch_m, "limited_zonewise_mix"
        if profile_key == "outboard_relaxed_mix":
            if y_center_m >= outboard_light_limit_m - 1.0e-9:
                return (
                    light_family,
                    min(
                        float(light_family.spacing_guidance.max_m),
                        1.05 * float(light_family.spacing_guidance.nominal_m),
                    ),
                    "limited_zonewise_mix",
                )
            return baseline_family, baseline_pitch_m, "limited_zonewise_mix"
        raise ValueError(f"Unknown zone-wise rib design profile '{profile_key}' at zone {zone_index}.")

    profile_labels = {
        "legacy_uniform": "Legacy single-contract baseline",
        "baseline_uniform": "Uniform baseline rib family",
        "inboard_reinforced_mix": "Inboard reinforced two-family mix",
        "outboard_relaxed_mix": "Outboard relaxed two-family mix",
    }

    summaries: list[ZoneWiseRibDesignSummary] = []
    seen_signatures: set[tuple[tuple[str, float], ...]] = set()
    for profile_key in profile_keys:
        zones: list[ZoneWiseRibZone] = []
        span_by_family: dict[str, float] = {}
        pitch_span_sum = 0.0
        knockdown_span_sum = 0.0
        mix_mode = "single_family_uniform"

        for zone_index, (start_station, end_station) in enumerate(
            zip(stations[:-1], stations[1:], strict=True),
            start=1,
        ):
            y_start_m = float(start_station.y_m)
            y_end_m = float(end_station.y_m)
            span_m = max(y_end_m - y_start_m, 1.0e-9)
            y_center_m = 0.5 * (y_start_m + y_end_m)
            family, target_pitch_m, mix_mode = _zone_family_and_pitch(
                profile_key=profile_key,
                y_center_m=y_center_m,
                zone_index=zone_index,
            )
            target_pitch_m = _clamp_rib_pitch_m(family, target_pitch_m)
            optional_rib_count, bay_count, realized_pitch_m = _realized_zone_pitch_m(
                span_m=span_m,
                target_pitch_m=target_pitch_m,
            )
            knockdown = derive_warping_knockdown(
                family.key,
                realized_pitch_m,
                catalog=catalog,
                material_db=materials_db,
            )
            span_by_family[family.key] = span_by_family.get(family.key, 0.0) + span_m
            pitch_span_sum += realized_pitch_m * span_m
            knockdown_span_sum += knockdown * span_m
            zones.append(
                ZoneWiseRibZone(
                    zone_index=int(zone_index),
                    zone_key=f"zone_{zone_index:02d}",
                    y_start_m=y_start_m,
                    y_end_m=y_end_m,
                    y_center_m=y_center_m,
                    span_m=span_m,
                    start_labels=tuple(start_station.labels),
                    end_labels=tuple(end_station.labels),
                    family_key=family.key,
                    family_label=family.label,
                    target_pitch_m=target_pitch_m,
                    realized_pitch_m=realized_pitch_m,
                    optional_rib_count=int(optional_rib_count),
                    bay_count=int(bay_count),
                    derived_warping_knockdown=float(knockdown),
                )
            )

        signature = tuple(
            (zone.family_key, round(zone.realized_pitch_m, 6))
            for zone in zones
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        unique_family_keys = tuple(sorted({zone.family_key for zone in zones}))
        family_switch_count = sum(
            1
            for previous, current in zip(zones[:-1], zones[1:], strict=True)
            if previous.family_key != current.family_key
        )
        within_limit = len(unique_family_keys) <= int(family_mix_max_unique)
        family_mix_cap_penalty_kg = 0.0
        if not within_limit:
            excess = len(unique_family_keys) - int(family_mix_max_unique)
            family_mix_cap_penalty_kg = float(RIB_MIX_FAMILY_EXCESS_PENALTY_KG * excess * excess)
        family_switch_penalty = (
            float(family_switch_penalty_kg) * float(family_switch_count)
            if len(unique_family_keys) > 1
            else 0.0
        )
        representative_family_key = max(
            span_by_family.items(),
            key=lambda item: (item[1], item[0]),
        )[0]
        summaries.append(
            ZoneWiseRibDesignSummary(
                enabled=True,
                design_key=profile_key,
                design_label=profile_labels.get(profile_key, profile_key.replace("_", " ")),
                design_mode=(
                    "legacy_single_contract"
                    if profile_key == "legacy_uniform"
                    else RIB_ZONEWISE_LIMITED_MODE
                ),
                mix_mode=mix_mode,
                max_unique_families=int(family_mix_max_unique),
                within_unique_family_limit=bool(within_limit),
                unique_family_count=len(unique_family_keys),
                unique_family_keys=unique_family_keys,
                family_switch_count=int(family_switch_count),
                family_switch_penalty_kg=float(family_switch_penalty),
                family_mix_cap_penalty_kg=float(family_mix_cap_penalty_kg),
                objective_penalty_kg=float(family_switch_penalty + family_mix_cap_penalty_kg),
                mandatory_station_count=len(stations),
                mandatory_stations_m=tuple(float(station.y_m) for station in stations),
                effective_warping_knockdown=float(knockdown_span_sum / max(half_span_m, 1.0e-9)),
                representative_family_key=representative_family_key,
                representative_spacing_m=float(pitch_span_sum / max(half_span_m, 1.0e-9)),
                zone_count=len(zones),
                zones=tuple(zones),
                notes=(
                    "Mandatory ribs are fixed at root, detected spar joints, lift-wire attachments, and the tip boundary.",
                    "Explicit control/geometry breakpoints are not yet surfaced in the config contract, so this pass uses the currently detectable mandatory stations only.",
                    "rib_bay_surrogate remains a representative single-spacing summary for backward-compatible reporting.",
                ),
            )
        )

    if not summaries:
        raise RuntimeError("Failed to build any zone-wise rib design profiles.")
    return tuple(summaries)


def _baseline_design_from_result(baseline_result) -> BaselineDesign:
    return BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )


def _baseline_design_from_candidate(candidate) -> BaselineDesign:
    return BaselineDesign(
        main_t_seg_m=np.asarray(candidate.main_t_seg_m, dtype=float),
        main_r_seg_m=np.asarray(candidate.main_r_seg_m, dtype=float),
        rear_t_seg_m=np.asarray(candidate.rear_t_seg_m, dtype=float),
        rear_r_seg_m=np.asarray(candidate.rear_r_seg_m, dtype=float),
    )


def _map_config_to_dict(map_config: ReducedMapConfig) -> dict[str, float]:
    return {
        "main_plateau_scale_upper": float(map_config.main_plateau_scale_upper),
        "main_taper_fill_upper": float(map_config.main_taper_fill_upper),
        "rear_radius_scale_upper": float(map_config.rear_radius_scale_upper),
        "delta_t_global_max_m": float(map_config.delta_t_global_max_m),
        "delta_t_rear_outboard_max_m": float(map_config.delta_t_rear_outboard_max_m),
    }


def _rebuild_dynamic_map_config(
    *,
    selected_candidate,
    cfg,
    previous_map_config: ReducedMapConfig,
) -> tuple[BaselineDesign, ReducedMapConfig]:
    baseline = _baseline_design_from_candidate(selected_candidate)
    rebuilt = build_reduced_map_config(
        baseline=baseline,
        cfg=cfg,
        main_plateau_scale_upper=float(previous_map_config.main_plateau_scale_upper),
        main_taper_fill_upper=float(previous_map_config.main_taper_fill_upper),
        rear_radius_scale_upper=float(previous_map_config.rear_radius_scale_upper),
    )
    return baseline, rebuilt


def _refresh_iteration_converged(
    iteration: RefreshIterationResult,
    *,
    mass_tol_kg: float,
    lift_rms_tol_npm: float,
    torque_rms_tol_nmpm: float,
) -> bool:
    if iteration.mass_delta_kg is None:
        return False
    if iteration.lift_rms_delta_npm is None or iteration.torque_rms_delta_nmpm is None:
        return False
    return bool(
        abs(float(iteration.mass_delta_kg)) <= float(mass_tol_kg)
        and abs(float(iteration.lift_rms_delta_npm)) <= float(lift_rms_tol_npm)
        and abs(float(iteration.torque_rms_delta_nmpm)) <= float(torque_rms_tol_nmpm)
    )


def _clearance_hotspots(
    *,
    inverse_result,
    clearance_floor_z_m: float,
    top_k: int,
) -> tuple[ClearanceHotspot, ...]:
    jig_shape = inverse_result.jig_shape
    rows: list[tuple[str, int, float, float, float]] = []
    for spar, nodes in (("main", jig_shape.main_nodes_m), ("rear", jig_shape.rear_nodes_m)):
        for idx, node in enumerate(np.asarray(nodes, dtype=float)):
            rows.append(
                (
                    spar,
                    int(idx),
                    float(node[1]),
                    float(node[2]),
                    float(node[2] - clearance_floor_z_m),
                )
            )
    rows.sort(key=lambda item: (item[4], item[2], item[0], item[1]))
    return tuple(
        ClearanceHotspot(
            rank=rank,
            spar=spar,
            side="positive_half_span",
            node_index=node_index,
            y_m=y_m,
            z_m=z_m,
            clearance_m=clearance_m,
        )
        for rank, (spar, node_index, y_m, z_m, clearance_m) in enumerate(rows[: max(1, int(top_k))], start=1)
    )


def _clearance_risk_metrics(
    *,
    inverse_result,
    clearance_floor_z_m: float,
    threshold_m: float,
    top_k: int,
) -> ClearanceRiskMetrics:
    hotspots = _clearance_hotspots(
        inverse_result=inverse_result,
        clearance_floor_z_m=clearance_floor_z_m,
        top_k=top_k,
    )
    clearances = np.asarray([hotspot.clearance_m for hotspot in hotspots], dtype=float)
    if clearances.size == 0:
        clearances = np.zeros(1, dtype=float)
    threshold = max(float(threshold_m), 1.0e-9)
    deficits = np.maximum(threshold - clearances, 0.0) / threshold
    risk_score = float(np.mean(np.square(deficits)))
    hotspot_count = int(np.sum(clearances <= threshold + 1.0e-12))
    minimum_clearance_m = float(np.min(clearances))
    hotspot_mean_clearance_m = float(np.mean(clearances))
    fragile = bool(minimum_clearance_m <= 1.0e-3 or risk_score >= 0.25)
    return ClearanceRiskMetrics(
        threshold_m=threshold,
        top_k=max(1, int(top_k)),
        minimum_clearance_m=minimum_clearance_m,
        hotspot_mean_clearance_m=hotspot_mean_clearance_m,
        hotspot_count_below_threshold=hotspot_count,
        risk_score=risk_score,
        fragile=fragile,
        hotspots=hotspots,
    )


def _active_wall_risk_score(hard_margins: dict[str, float]) -> tuple[float, int]:
    risks: list[float] = []
    tight_count = 0
    for name in CLEARANCE_RISK_WALL_NAMES:
        buffer = float(CLEARANCE_RISK_BUFFER_BY_MARGIN_NAME[name])
        margin = float(hard_margins.get(name, float("inf")))
        deficit = max(buffer - margin, 0.0) / max(buffer, 1.0e-12)
        risk = float(deficit * deficit)
        risks.append(risk)
        if margin <= buffer + 1.0e-12:
            tight_count += 1
    if not risks:
        return 0.0, 0
    return float(np.mean(risks)), int(tight_count)


def _risk_level(boundary_margin: float, buffer: float) -> str:
    if boundary_margin < -1.0e-12:
        return "violated"
    if boundary_margin <= buffer + 1.0e-12:
        return "active"
    return "inactive"


def _segment_ranges_m(segments: list[float] | tuple[float, ...]) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    start = 0.0
    for length in segments:
        end = start + float(length)
        ranges.append((start, end))
        start = end
    return ranges


def _geometry_wall_entries(candidate: InverseCandidate, cfg) -> tuple[ActiveWallEntry, ...]:
    entries: list[ActiveWallEntry] = []
    main_ranges = _segment_ranges_m(list(cfg.main_spar.segments or []))
    rear_ranges = _segment_ranges_m(list(cfg.rear_spar.segments or []))

    def _append_step(values: np.ndarray, *, name: str, label: str, ranges: list[tuple[float, float]]) -> None:
        arr = np.asarray(values, dtype=float).reshape(-1)
        if arr.size < 2:
            return
        steps = np.abs(np.diff(arr))
        margins = float(cfg.solver.max_thickness_step_m) - steps
        idx = int(np.argmin(margins))
        y_loc = ranges[idx][1] if idx < len(ranges) else float(idx + 1)
        entries.append(
            ActiveWallEntry(
                name=name,
                category="geometry / discrete boundary",
                margin=float(margins[idx]),
                buffer=float(CLEARANCE_RISK_BUFFER_BY_MARGIN_NAME.get(name, 0.25e-3)),
                risk_score=float(
                    (max(CLEARANCE_RISK_BUFFER_BY_MARGIN_NAME.get(name, 0.25e-3) - float(margins[idx]), 0.0)
                    / max(CLEARANCE_RISK_BUFFER_BY_MARGIN_NAME.get(name, 0.25e-3), 1.0e-12)) ** 2
                ),
                location=f"interface {idx + 1}->{idx + 2} @ y={y_loc:.3f} m",
                boundary_state="upper_bound",
                detail=(
                    f"{label} |Δ|={steps[idx] * 1000.0:.3f} mm "
                    f"(limit={float(cfg.solver.max_thickness_step_m) * 1000.0:.3f} mm)"
                ),
            )
        )

    def _append_taper(values: np.ndarray, *, name: str, label: str, ranges: list[tuple[float, float]]) -> None:
        arr = np.asarray(values, dtype=float).reshape(-1)
        if arr.size < 2:
            return
        diffs = arr[:-1] - arr[1:]
        idx = int(np.argmin(diffs))
        y_loc = ranges[idx][1] if idx < len(ranges) else float(idx + 1)
        buffer = float(CLEARANCE_RISK_BUFFER_BY_MARGIN_NAME.get(name, 0.50e-3))
        entries.append(
            ActiveWallEntry(
                name=name,
                category="geometry / discrete boundary",
                margin=float(diffs[idx]),
                buffer=buffer,
                risk_score=float((max(buffer - float(diffs[idx]), 0.0) / max(buffer, 1.0e-12)) ** 2),
                location=f"interface {idx + 1}->{idx + 2} @ y={y_loc:.3f} m",
                boundary_state="equality_wall",
                detail=f"{label} inboard={arr[idx] * 1000.0:.3f} mm outboard={arr[idx + 1] * 1000.0:.3f} mm",
            )
        )

    def _append_segment_margin(values: np.ndarray, *, name: str, label: str, ranges: list[tuple[float, float]], buffer: float, detail_fn) -> None:
        arr = np.asarray(values, dtype=float).reshape(-1)
        idx = int(np.argmin(arr))
        y0, y1 = ranges[idx] if idx < len(ranges) else (float(idx), float(idx + 1))
        entries.append(
            ActiveWallEntry(
                name=name,
                category="geometry / discrete boundary",
                margin=float(arr[idx]),
                buffer=float(buffer),
                risk_score=float((max(float(buffer) - float(arr[idx]), 0.0) / max(float(buffer), 1.0e-12)) ** 2),
                location=f"segment {idx + 1} @ y={y0:.3f}..{y1:.3f} m",
                boundary_state="lower_bound",
                detail=str(detail_fn(idx)),
            )
        )

    _append_taper(candidate.main_r_seg_m, name="main_radius_taper_margin_min_m", label="main radius taper", ranges=main_ranges)
    _append_taper(candidate.rear_r_seg_m, name="rear_radius_taper_margin_min_m", label="rear radius taper", ranges=rear_ranges)
    _append_step(candidate.main_t_seg_m, name="main_thickness_step_margin_min_m", label="main thickness step", ranges=main_ranges)
    _append_step(candidate.rear_t_seg_m, name="rear_thickness_step_margin_min_m", label="rear thickness step", ranges=rear_ranges)

    dominance_margin = (
        np.asarray(candidate.main_r_seg_m, dtype=float)
        - np.asarray(candidate.rear_r_seg_m, dtype=float)
        - float(cfg.solver.main_spar_dominance_margin_m)
    )
    _append_segment_margin(
        dominance_margin,
        name="radius_dominance_margin_min_m",
        label="main vs rear radius dominance",
        ranges=main_ranges,
        buffer=1.0e-3,
        detail_fn=lambda idx: (
            f"main_r={candidate.main_r_seg_m[idx] * 1000.0:.3f} mm rear_r={candidate.rear_r_seg_m[idx] * 1000.0:.3f} mm "
            f"(required gap={float(cfg.solver.main_spar_dominance_margin_m) * 1000.0:.3f} mm)"
        ),
    )
    if float(cfg.solver.rear_main_radius_ratio_min) > 0.0:
        ratio_margin = (
            np.asarray(candidate.rear_r_seg_m, dtype=float)
            - float(cfg.solver.rear_main_radius_ratio_min) * np.asarray(candidate.main_r_seg_m, dtype=float)
        )
        _append_segment_margin(
            ratio_margin,
            name="rear_main_radius_ratio_margin_min_m",
            label="rear/main radius ratio",
            ranges=rear_ranges,
            buffer=0.5e-3,
            detail_fn=lambda idx: (
                f"rear_r={candidate.rear_r_seg_m[idx] * 1000.0:.3f} mm "
                f"ratio*main={float(cfg.solver.rear_main_radius_ratio_min) * candidate.main_r_seg_m[idx] * 1000.0:.3f} mm"
            ),
        )
    return tuple(sorted(entries, key=lambda entry: (entry.margin, entry.risk_score)))


def _reduced_variable_bound_entries(candidate: InverseCandidate) -> tuple[ActiveWallEntry, ...]:
    entries: list[ActiveWallEntry] = []
    z_arr = np.asarray(candidate.z, dtype=float).reshape(-1)
    for idx, (name, value) in enumerate(zip(SCALE_NAMES, z_arr, strict=True)):
        lower_margin = float(value)
        upper_margin = float(1.0 - value)
        if lower_margin <= upper_margin:
            margin = lower_margin
            boundary_state = "lower_bound"
        else:
            margin = upper_margin
            boundary_state = "upper_bound"
        buffer = 0.05
        entries.append(
            ActiveWallEntry(
                name=name,
                category="reduced variable bound",
                margin=margin,
                buffer=buffer,
                risk_score=float((max(buffer - margin, 0.0) / buffer) ** 2),
                location=f"z[{idx}]",
                boundary_state=boundary_state,
                detail=f"value={value:.6f}  lower_margin={lower_margin:.6f}  upper_margin={upper_margin:.6f}",
            )
        )
    return tuple(sorted(entries, key=lambda entry: (entry.margin, entry.risk_score)))


def _dominant_blocker_name(candidate: InverseCandidate) -> str:
    if candidate.failures:
        return str(candidate.failures[0])
    if not candidate.hard_margins:
        return "none"
    return str(min(candidate.hard_margins.items(), key=lambda item: float(item[1]))[0])


def _feasible_key(candidate: InverseCandidate) -> tuple[float, float, float, float, float]:
    return (
        float(candidate.objective_value_kg),
        float(candidate.total_structural_mass_kg),
        float(candidate.clearance_risk_score),
        float(candidate.active_wall_risk_score),
        float(candidate.max_jig_vertical_prebend_m),
    )


def _violation_key(candidate: InverseCandidate) -> tuple[float, float, float, float, float]:
    return (
        float(candidate.hard_violation_score),
        float(candidate.objective_value_kg),
        float(candidate.total_structural_mass_kg),
        float(candidate.clearance_risk_score),
        float(candidate.active_wall_risk_score),
        float(candidate.max_jig_vertical_prebend_m),
    )


def _target_violation_key(candidate: InverseCandidate) -> tuple[float, float, float, float, float]:
    overshoot_kg = max(-float(candidate.mass_margin_kg), 0.0)
    return (
        float(candidate.target_violation_score),
        float(overshoot_kg),
        float(candidate.objective_value_kg),
        float(candidate.clearance_risk_score),
        float(candidate.active_wall_risk_score),
    )


def _target_violation_score(*, hard_violation_score: float, total_mass_kg: float, target_mass_kg: float | None) -> float:
    if target_mass_kg is None:
        return float(hard_violation_score)
    if not np.isfinite(total_mass_kg) or not np.isfinite(hard_violation_score):
        return float("inf")
    overshoot_kg = max(float(total_mass_kg) - float(target_mass_kg), 0.0)
    mass_scale_kg = max(abs(float(target_mass_kg)), 1.0)
    return float(hard_violation_score + (overshoot_kg / mass_scale_kg) ** 2)


def _extract_abs_twist_profile_deg(result: OptimizationResult) -> np.ndarray:
    nodes = getattr(result, "nodes", None)
    disp = getattr(result, "disp", None)
    if nodes is None or disp is None:
        return np.zeros(0, dtype=float)

    nodes_arr = np.asarray(nodes, dtype=float)
    disp_arr = np.asarray(disp, dtype=float)
    if nodes_arr.ndim != 2 or nodes_arr.shape[1] != 3:
        return np.zeros(0, dtype=float)
    if disp_arr.ndim != 2 or disp_arr.shape[0] != nodes_arr.shape[0] or disp_arr.shape[1] < 6:
        return np.zeros(0, dtype=float)

    nn = nodes_arr.shape[0]
    theta_twist = np.zeros(nn, dtype=float)
    for i in range(nn):
        if i < nn - 1:
            r3 = _rotation_matrix(nodes_arr[i], nodes_arr[i + 1])
        else:
            r3 = _rotation_matrix(nodes_arr[i - 1], nodes_arr[i])
        theta_local = r3 @ disp_arr[i, 3:6]
        theta_twist[i] = abs(float(theta_local[0])) * 180.0 / np.pi
    return theta_twist


def _load_metrics_from_mapped_loads(
    mapped_loads: dict,
    *,
    twist_abs_max_deg: float,
    aoa_eff_min_deg: float,
    aoa_eff_max_deg: float,
    aoa_clip_fraction: float,
) -> RefreshLoadMetrics:
    y = np.asarray(mapped_loads["y"], dtype=float)
    lift = np.asarray(mapped_loads["lift_per_span"], dtype=float)
    drag = np.asarray(mapped_loads["drag_per_span"], dtype=float)
    torque = np.asarray(mapped_loads["torque_per_span"], dtype=float)
    return RefreshLoadMetrics(
        total_lift_half_n=float(np.trapezoid(lift, y)),
        total_drag_half_n=float(np.trapezoid(drag, y)),
        total_abs_torque_half_nm=float(np.trapezoid(np.abs(torque), y)),
        max_lift_per_span_npm=float(np.max(lift)),
        max_abs_torque_per_span_nmpm=float(np.max(np.abs(torque))),
        twist_abs_max_deg=float(twist_abs_max_deg),
        aoa_eff_min_deg=float(aoa_eff_min_deg),
        aoa_eff_max_deg=float(aoa_eff_max_deg),
        aoa_clip_fraction=float(aoa_clip_fraction),
    )


def _candidate_aoa_sweep_deg(
    aero_cases: Iterable[SpanwiseLoad] | None,
) -> tuple[float, ...]:
    if aero_cases is None:
        return DEFAULT_CANDIDATE_AOA_SWEEP_DEG

    values: list[float] = []
    seen: set[float] = set()
    for case in aero_cases:
        value = round(float(case.aoa_deg), 9)
        if value in seen:
            continue
        seen.add(value)
        values.append(float(case.aoa_deg))
    if values:
        return tuple(values)
    return DEFAULT_CANDIDATE_AOA_SWEEP_DEG


def _resolve_outer_loop_candidate_aero(
    *,
    cfg,
    aircraft,
    output_dir: Path,
    target_shape_z_scale: float,
    dihedral_exponent: float,
    aero_source_mode: str,
    legacy_aero_cases: list[SpanwiseLoad] | None = None,
    candidate_aero_output_dir: Path | None = None,
) -> tuple[list[SpanwiseLoad], SpanwiseLoad, dict, CandidateAeroContract]:
    mode = str(aero_source_mode)
    if mode not in {LEGACY_AERO_SOURCE_MODE, CANDIDATE_RERUN_AERO_SOURCE_MODE}:
        raise ValueError(f"Unsupported aero source mode: {mode}")

    if mode == LEGACY_AERO_SOURCE_MODE:
        cases = legacy_aero_cases
        if cases is None:
            cases = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar).parse()
        if not cases:
            raise RuntimeError("No aerodynamic cases found in legacy cfg.io VSPAero data.")
        cruise_case, mapped_loads = _select_cruise_case_and_mapped_loads(
            cfg,
            aircraft,
            list(cases),
        )
        contract = CandidateAeroContract(
            source_mode=LEGACY_AERO_SOURCE_MODE,
            baseline_load_source="legacy_cfg_vspaero_sweep",
            refresh_load_source="legacy_twist_refresh_from_cfg_sweep",
            load_ownership=(
                "Loads come from the shared cfg.io.vsp_lod / cfg.io.vsp_polar artifacts; "
                "this candidate does not own a rebuilt-geometry aero solve."
            ),
            artifact_ownership=(
                "No candidate-owned OpenVSP / VSPAero artifacts are produced in legacy_refresh mode."
            ),
            requested_knobs={
                "target_shape_z_scale": float(target_shape_z_scale),
                "dihedral_multiplier": float(target_shape_z_scale),
                "dihedral_exponent": float(dihedral_exponent),
            },
            aoa_sweep_deg=_candidate_aoa_sweep_deg(cases),
            selected_cruise_aoa_deg=float(cruise_case.aoa_deg),
            geometry_artifacts={
                "candidate_output_dir": None,
                "vsp3_path": _resolve_optional_path(cfg.io.vsp_model),
                "vspscript_path": None,
                "lod_path": _resolve_optional_path(cfg.io.vsp_lod),
                "polar_path": _resolve_optional_path(cfg.io.vsp_polar),
            },
            notes=(
                "target_shape_z_scale still modifies the inverse-design target shape, "
                "but aerodynamic ownership remains on the legacy shared sweep.",
            ),
        )
        return list(cases), cruise_case, mapped_loads, contract

    aoa_sweep = list(_candidate_aoa_sweep_deg(legacy_aero_cases))
    rerun_output_dir = (
        candidate_aero_output_dir
        if candidate_aero_output_dir is not None
        else output_dir / "candidate_aero"
    ).resolve()
    builder = VSPBuilder(
        cfg,
        dihedral_multiplier=float(target_shape_z_scale),
        dihedral_exponent=float(dihedral_exponent),
    )
    build_result = builder.build_and_run(str(rerun_output_dir), aoa_list=aoa_sweep)
    if not bool(build_result.get("success")):
        error = build_result.get("error") or "unknown VSPBuilder failure"
        raise RuntimeError(f"Candidate rerun-aero failed: {error}")
    if build_result.get("lod_path") is None:
        vspscript_path = build_result.get("vspscript_path")
        manual_hint = (
            f" Only a VSPScript fallback was generated at {vspscript_path}."
            if vspscript_path
            else ""
        )
        raise RuntimeError(
            "Candidate rerun-aero did not produce a VSPAero .lod artifact."
            + manual_hint
        )

    cases = VSPAeroParser(
        build_result["lod_path"],
        build_result.get("polar_path"),
    ).parse()
    if not cases:
        raise RuntimeError("Candidate rerun-aero produced no parseable VSPAero cases.")
    cruise_case, mapped_loads = _select_cruise_case_and_mapped_loads(
        cfg,
        aircraft,
        list(cases),
    )
    contract = CandidateAeroContract(
        source_mode=CANDIDATE_RERUN_AERO_SOURCE_MODE,
        baseline_load_source="candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun",
        refresh_load_source="candidate_owned_twist_refresh_from_rerun_sweep",
        load_ownership=(
            "Loads come from a candidate-owned OpenVSP geometry rebuild and VSPAero rerun "
            "tied to the current low-dimensional outer-loop geometry knobs."
        ),
        artifact_ownership=(
            f"Candidate-owned geometry and aero artifacts live under {rerun_output_dir}."
        ),
        requested_knobs={
            "target_shape_z_scale": float(target_shape_z_scale),
            "dihedral_multiplier": float(target_shape_z_scale),
            "dihedral_exponent": float(dihedral_exponent),
        },
        aoa_sweep_deg=tuple(float(value) for value in aoa_sweep),
        selected_cruise_aoa_deg=float(cruise_case.aoa_deg),
        geometry_artifacts={
            "candidate_output_dir": str(rerun_output_dir),
            "vsp3_path": _resolve_optional_path(build_result.get("vsp3_path")),
            "vspscript_path": _resolve_optional_path(build_result.get("vspscript_path")),
            "lod_path": _resolve_optional_path(build_result.get("lod_path")),
            "polar_path": _resolve_optional_path(build_result.get("polar_path")),
        },
        notes=(
            "target_shape_z_scale is mapped onto VSPBuilder.dihedral_multiplier so the "
            "geometry-rerun contract uses the same low-dimensional shape knob as inverse design.",
        ),
    )
    return list(cases), cruise_case, mapped_loads, contract


def _refresh_method_text(contract: CandidateAeroContract | None) -> str:
    if contract is not None and contract.source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE:
        return (
            "candidate-level geometry rebuild + VSPAero rerun for the baseline load owner; "
            "later refresh steps interpolate within the candidate-owned AoA sweep"
        )
    return "reuse existing VSPAero AoA sweep and reduce local effective AoA by structural twist"


def _refresh_physics_assumptions(
    *,
    contract: CandidateAeroContract | None,
    low_dim_loaded_shape_matching: bool,
) -> list[str]:
    assumptions = [
        "Each stage is still a one-way structural solve on the existing beam-line target shape.",
        "The beam-line target shape remains fixed across refresh iterations.",
    ]
    if contract is not None and contract.source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE:
        assumptions.append(
            "The initial baseline loads come from a candidate-owned OpenVSP geometry rebuild and VSPAero rerun."
        )
        assumptions.append(
            "Later refresh steps reuse that candidate-owned AoA sweep; OpenVSP is not rerun after each structural update."
        )
    else:
        assumptions.append(
            "Refreshed loads are interpolated from existing VSPAero AoA cases; OpenVSP is not rerun."
        )
    assumptions.append(
        "Structural twist is treated as local washout with a simple scalar scale factor."
    )
    assumptions.append(
        "The forward refresh check estimates frozen-load bias by applying refreshed displacement to the previous jig."
    )
    if low_dim_loaded_shape_matching:
        assumptions.append(
            "Loaded-shape matching is constrained only on main-beam Z and twist at a few control stations."
        )
    return assumptions


def _refresh_difference_from_full_coupling(
    *,
    contract: CandidateAeroContract | None,
    converged: bool,
    dynamic_design_space_enabled: bool,
) -> list[str]:
    lines = [
        (
            "lightweight outer loop converges on load/mass deltas, not full aeroelastic residuals"
            if converged
            else "capped outer refresh count instead of iterating to convergence"
        )
    ]
    if contract is not None and contract.source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE:
        lines.append(
            "baseline candidate loads are rebuilt once, but there is still no per-refresh geometry rebuild or aero rerun"
        )
    else:
        lines.append("no geometry rebuild / CFD rerun between stages")
    lines.append(
        "no trim solve; dynamic design space only rebuilds the reduced V2 map"
        if dynamic_design_space_enabled
        else "no trim solve or dynamic design-space update"
    )
    return lines


class LightweightLoadRefreshModel:
    """Twist-based local-AoA refresh using the existing VSPAero AoA sweep."""

    def __init__(
        self,
        *,
        aero_cases: list[SpanwiseLoad],
        baseline_case: SpanwiseLoad,
        cfg,
        aircraft,
        washout_scale: float = 1.0,
    ):
        if not aero_cases:
            raise ValueError("Need at least one aerodynamic case for load refresh.")

        self.cfg = cfg
        self.aircraft = aircraft
        self.mapper = LoadMapper()
        self.washout_scale = float(washout_scale)

        self._cases = tuple(sorted(aero_cases, key=lambda case: float(case.aoa_deg)))
        self._aoa_deg = np.asarray([float(case.aoa_deg) for case in self._cases], dtype=float)
        self._baseline_case = min(
            self._cases,
            key=lambda case: abs(float(case.aoa_deg) - float(baseline_case.aoa_deg)),
        )
        self._y_aero = np.asarray(self._baseline_case.y, dtype=float)
        self._chord = np.asarray(self._baseline_case.chord, dtype=float)
        self._cl_table = np.vstack([np.asarray(case.cl, dtype=float) for case in self._cases])
        self._cd_table = np.vstack([np.asarray(case.cd, dtype=float) for case in self._cases])
        self._cm_table = np.vstack([np.asarray(case.cm, dtype=float) for case in self._cases])
        self._validate_case_tables()

    def _validate_case_tables(self) -> None:
        ref_n = self._y_aero.size
        if ref_n < 2:
            raise ValueError("Aerodynamic refresh requires at least two spanwise stations.")
        for case in self._cases:
            if np.asarray(case.y, dtype=float).shape != (ref_n,):
                raise ValueError("All aerodynamic cases must share the same spanwise grid.")
        if self._aoa_deg.size < 2:
            raise ValueError("Lightweight load refresh needs at least two AoA cases.")

    def baseline_metrics(self, mapped_loads: dict) -> RefreshLoadMetrics:
        aoa = float(self._baseline_case.aoa_deg)
        return _load_metrics_from_mapped_loads(
            mapped_loads,
            twist_abs_max_deg=0.0,
            aoa_eff_min_deg=aoa,
            aoa_eff_max_deg=aoa,
            aoa_clip_fraction=0.0,
        )

    def _interp_table(self, table: np.ndarray, aoa_profile_deg: np.ndarray) -> np.ndarray:
        out = np.zeros_like(aoa_profile_deg, dtype=float)
        for idx in range(table.shape[1]):
            out[idx] = float(np.interp(aoa_profile_deg[idx], self._aoa_deg, table[:, idx]))
        return out

    def refresh_mapped_loads(
        self,
        *,
        equivalent_result: OptimizationResult,
    ) -> tuple[dict, RefreshLoadMetrics]:
        twist_deg_nodes = _extract_abs_twist_profile_deg(equivalent_result)
        nodes = getattr(equivalent_result, "nodes", None)
        if nodes is None or twist_deg_nodes.size == 0:
            struct_y = np.asarray(self.aircraft.wing.y, dtype=float)
            twist_deg_nodes = np.zeros_like(struct_y)
        else:
            struct_y = np.asarray(nodes, dtype=float)[:, 1]

        twist_deg_aero = np.interp(
            self._y_aero,
            struct_y,
            twist_deg_nodes,
            left=float(twist_deg_nodes[0]),
            right=float(twist_deg_nodes[-1]),
        )
        aoa_raw_deg = float(self._baseline_case.aoa_deg) - self.washout_scale * twist_deg_aero
        aoa_eff_deg = np.clip(aoa_raw_deg, float(self._aoa_deg[0]), float(self._aoa_deg[-1]))

        cl = self._interp_table(self._cl_table, aoa_eff_deg)
        cd = self._interp_table(self._cd_table, aoa_eff_deg)
        cm = self._interp_table(self._cm_table, aoa_eff_deg)
        q = float(self._baseline_case.dynamic_pressure)
        refreshed_case = SpanwiseLoad(
            y=self._y_aero.copy(),
            chord=self._chord.copy(),
            cl=cl,
            cd=cd,
            cm=cm,
            lift_per_span=q * self._chord * cl,
            drag_per_span=q * self._chord * cd,
            aoa_deg=float(self._baseline_case.aoa_deg),
            velocity=float(self._baseline_case.velocity),
            dynamic_pressure=q,
        )
        mapped = self.mapper.map_loads(
            refreshed_case,
            np.asarray(self.aircraft.wing.y, dtype=float),
            actual_velocity=self.cfg.flight.velocity,
            actual_density=self.cfg.flight.air_density,
        )
        metrics = _load_metrics_from_mapped_loads(
            mapped,
            twist_abs_max_deg=float(np.max(twist_deg_nodes)) if twist_deg_nodes.size else 0.0,
            aoa_eff_min_deg=float(np.min(aoa_eff_deg)),
            aoa_eff_max_deg=float(np.max(aoa_eff_deg)),
            aoa_clip_fraction=float(
                np.mean(np.abs(aoa_eff_deg - aoa_raw_deg) > 1.0e-12)
            ),
        )
        return mapped, metrics


def _select_cruise_case_and_mapped_loads(
    cfg,
    aircraft,
    aero_cases: list[SpanwiseLoad] | None = None,
) -> tuple[SpanwiseLoad, dict]:
    cases = aero_cases
    if cases is None:
        parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
        cases = parser.parse()
    if not cases:
        raise RuntimeError("No aerodynamic cases found in VSPAero data.")

    mapper = LoadMapper()
    target_weight = aircraft.weight_N
    best_case = None
    best_residual = float("inf")
    best_mapped = None

    for case in cases:
        mapped = mapper.map_loads(
            case,
            aircraft.wing.y,
            actual_velocity=cfg.flight.velocity,
            actual_density=cfg.flight.air_density,
        )
        full_lift = 2.0 * float(mapped["total_lift"])
        residual = abs(full_lift - target_weight)
        if residual < best_residual:
            best_case = case
            best_mapped = mapped
            best_residual = residual

    if best_case is None or best_mapped is None:
        raise RuntimeError("Failed to determine cruise aerodynamic case from VSPAero data.")
    return best_case, best_mapped


class InverseDesignEvaluator:
    """Cached frozen-load inverse-design evaluator over the reduced V2 map."""

    def __init__(
        self,
        *,
        cfg,
        aircraft,
        materials_db: MaterialDB,
        optimizer: SparOptimizer,
        export_loads: dict,
        baseline: BaselineDesign,
        map_config: ReducedMapConfig,
        clearance_floor_z_m: float,
        target_shape_error_tol_m: float,
        max_jig_vertical_prebend_m: float | None,
        max_jig_vertical_curvature_per_m: float | None,
        loaded_shape_mode: str,
        loaded_shape_control_station_fractions: tuple[float, ...],
        loaded_shape_main_z_tol_m: float,
        loaded_shape_twist_tol_deg: float,
        loaded_shape_penalty_weight_kg: float,
        target_shape_z_scale: float,
        dihedral_exponent: float,
        clearance_risk_threshold_m: float,
        clearance_risk_top_k: int,
        clearance_penalty_weight_kg: float,
        active_wall_penalty_weight_kg: float,
        target_mass_kg: float | None = None,
        rib_zonewise_mode: str = RIB_ZONEWISE_LIMITED_MODE,
        rib_family_switch_penalty_kg: float = DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG,
        rib_family_mix_max_unique: int = DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE,
    ):
        self.cfg = cfg
        self.aircraft = aircraft
        self.materials_db = materials_db
        self.base_aero_loads = getattr(optimizer, "aero_loads")
        self.export_loads = export_loads
        self.baseline = baseline
        self.map_config = map_config
        self.clearance_floor_z_m = float(clearance_floor_z_m)
        self.target_shape_error_tol_m = float(target_shape_error_tol_m)
        self.max_jig_vertical_prebend_m = max_jig_vertical_prebend_m
        self.max_jig_vertical_curvature_per_m = max_jig_vertical_curvature_per_m
        self.loaded_shape_mode = str(loaded_shape_mode)
        self.loaded_shape_control_station_fractions = tuple(
            float(value) for value in loaded_shape_control_station_fractions
        )
        self.loaded_shape_main_z_tol_m = float(loaded_shape_main_z_tol_m)
        self.loaded_shape_twist_tol_deg = float(loaded_shape_twist_tol_deg)
        self.loaded_shape_penalty_weight_kg = float(loaded_shape_penalty_weight_kg)
        self.target_shape_z_scale = float(target_shape_z_scale)
        self.dihedral_exponent = float(dihedral_exponent)
        self.clearance_risk_threshold_m = float(clearance_risk_threshold_m)
        self.clearance_risk_top_k = int(clearance_risk_top_k)
        self.clearance_penalty_weight_kg = float(clearance_penalty_weight_kg)
        self.active_wall_penalty_weight_kg = float(active_wall_penalty_weight_kg)
        self.target_mass_kg = None if target_mass_kg is None else float(target_mass_kg)
        self.rib_zonewise_mode = str(rib_zonewise_mode)
        self.rib_family_switch_penalty_kg = float(rib_family_switch_penalty_kg)
        self.rib_family_mix_max_unique = int(rib_family_mix_max_unique)
        self.rib_design_profiles = _resolve_zonewise_rib_designs(
            cfg=self.cfg,
            aircraft=self.aircraft,
            materials_db=self.materials_db,
            zonewise_mode=self.rib_zonewise_mode,
            family_switch_penalty_kg=self.rib_family_switch_penalty_kg,
            family_mix_max_unique=self.rib_family_mix_max_unique,
        )
        self.default_rib_design_key = self.rib_design_profiles[0].design_key
        self._rib_design_by_key = {design.design_key: design for design in self.rib_design_profiles}
        self._cfg_by_rib_design_key: dict[str, object] = {}
        self._optimizer_by_rib_design_key: dict[str, SparOptimizer] = {}
        self.archive = CandidateArchive(target_mass_kg=self.target_mass_kg)
        self._cache: dict[tuple[object, ...], InverseCandidate] = {}
        self.unique_evaluations = 0
        self.cache_hits = 0
        self.equivalent_analysis_calls = 0
        self.production_analysis_calls = 0

    def _key(self, z: np.ndarray, *, rib_design_key: str) -> tuple[object, ...]:
        return (str(rib_design_key), *tuple(np.round(np.asarray(z, dtype=float).reshape(5), 10)))

    def _candidate_cfg(self, rib_design_key: str):
        cached = self._cfg_by_rib_design_key.get(rib_design_key)
        if cached is not None:
            return cached

        rib_design = self._rib_design_by_key[rib_design_key]
        cfg = deepcopy(self.cfg)
        if rib_design.enabled:
            cfg.safety.dual_spar_warping_knockdown = float(rib_design.effective_warping_knockdown)
            if getattr(cfg, "rib", None) is not None:
                cfg.rib.enabled = True
                cfg.rib.family = rib_design.representative_family_key
                cfg.rib.spacing_m = rib_design.representative_spacing_m
        self._cfg_by_rib_design_key[rib_design_key] = cfg
        return cfg

    def _optimizer_for_rib_design(self, rib_design_key: str) -> SparOptimizer:
        cached = self._optimizer_by_rib_design_key.get(rib_design_key)
        if cached is not None:
            return cached

        cfg = self._candidate_cfg(rib_design_key)
        optimizer = SparOptimizer(
            cfg=cfg,
            aircraft=self.aircraft,
            aero_loads=self.base_aero_loads,
            materials_db=self.materials_db,
        )
        self._optimizer_by_rib_design_key[rib_design_key] = optimizer
        return optimizer

    def evaluate(self, z: np.ndarray, *, source: str, rib_design_key: str | None = None) -> InverseCandidate:
        z_arr = np.asarray(z, dtype=float).reshape(5)
        resolved_rib_design_key = (
            self.default_rib_design_key if rib_design_key is None else str(rib_design_key)
        )
        key = self._key(z_arr, rib_design_key=resolved_rib_design_key)
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        z_bounded = np.clip(z_arr, 0.0, 1.0)
        bounds_violated = bool(np.max(np.abs(z_bounded - z_arr)) > 1.0e-12)
        rib_design = self._rib_design_by_key[resolved_rib_design_key]
        candidate_cfg = self._candidate_cfg(resolved_rib_design_key)
        candidate_optimizer = self._optimizer_for_rib_design(resolved_rib_design_key)
        vars_physical = decode_reduced_variables(z=z_bounded, map_config=self.map_config)
        main_t, main_r, rear_t, rear_r = design_from_reduced_variables(
            baseline=self.baseline,
            z=z_bounded,
            map_config=self.map_config,
        )

        t0 = perf_counter()
        try:
            if bounds_violated:
                raise ValueError("Reduced variables must stay within [0, 1].")

            eq_result = candidate_optimizer.analyze(
                main_t_seg=main_t,
                main_r_seg=main_r,
                rear_t_seg=rear_t,
                rear_r_seg=rear_r,
            )
            self.equivalent_analysis_calls += 1

            model = build_dual_beam_mainline_model(
                cfg=candidate_cfg,
                aircraft=self.aircraft,
                opt_result=eq_result,
                export_loads=self.export_loads,
                materials_db=self.materials_db,
            )
            production = run_dual_beam_mainline_kernel(
                model=model,
                mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
            )
            self.production_analysis_calls += 1

            inverse = build_frozen_load_inverse_design_from_mainline(
                model=model,
                result=production,
                clearance_floor_z_m=self.clearance_floor_z_m,
                target_shape_error_tol_m=self.target_shape_error_tol_m,
                max_abs_vertical_prebend_m=self.max_jig_vertical_prebend_m,
                max_abs_vertical_curvature_per_m=self.max_jig_vertical_curvature_per_m,
                loaded_shape_mode=self.loaded_shape_mode,
                loaded_shape_control_station_fractions=self.loaded_shape_control_station_fractions,
                loaded_shape_main_z_tol_m=self.loaded_shape_main_z_tol_m,
                loaded_shape_twist_tol_deg=self.loaded_shape_twist_tol_deg,
                target_loaded_shape_z_scale=self.target_shape_z_scale,
                target_loaded_shape_dihedral_exponent=self.dihedral_exponent,
                wire_y_positions=(
                    tuple(float(att.y) for att in candidate_cfg.lift_wires.attachments)
                    if candidate_cfg.lift_wires.enabled
                    else ()
                ),
            )
            hard_margins = {
                **build_candidate_hard_margins(production),
                **build_inverse_design_margins(inverse),
            }
            hard_violation_score = hard_violation_score_from_margins(
                hard_margins,
                analysis_succeeded=bool(production.feasibility.analysis_succeeded),
            )
            mass_margin_kg = (
                float("inf")
                if self.target_mass_kg is None
                else float(self.target_mass_kg - float(production.recovery.total_structural_mass_full_kg))
            )
            target_mass_passed = bool(mass_margin_kg >= -1.0e-12)
            target_violation_score = _target_violation_score(
                hard_violation_score=float(hard_violation_score),
                total_mass_kg=float(production.recovery.total_structural_mass_full_kg),
                target_mass_kg=self.target_mass_kg,
            )
            overall_target_feasible = bool(inverse.feasibility.overall_feasible and target_mass_passed)
            clearance_risk = _clearance_risk_metrics(
                inverse_result=inverse,
                clearance_floor_z_m=self.clearance_floor_z_m,
                threshold_m=self.clearance_risk_threshold_m,
                top_k=self.clearance_risk_top_k,
            )
            active_wall_risk_score, active_wall_tight_count = _active_wall_risk_score(hard_margins)
            loaded_shape_penalty_kg = float(
                self.loaded_shape_penalty_weight_kg * inverse.loaded_shape_match.normalized_rms_error
            )
            clearance_penalty_kg = float(self.clearance_penalty_weight_kg * clearance_risk.risk_score)
            active_wall_penalty_kg = float(
                self.active_wall_penalty_weight_kg * active_wall_risk_score
            )
            rib_design_penalty_kg = float(rib_design.objective_penalty_kg)
            objective_value_kg = float(
                production.recovery.total_structural_mass_full_kg
                + loaded_shape_penalty_kg
                + clearance_penalty_kg
                + active_wall_penalty_kg
                + rib_design_penalty_kg
            )
            rib_bay_surrogate = build_rib_bay_surrogate_summary(
                cfg=candidate_cfg,
                aircraft=self.aircraft,
                loaded_shape=inverse.predicted_loaded_shape,
                source_shape="predicted_loaded_shape",
            )

            finite_scalars = [
                float(production.recovery.spar_tube_mass_full_kg),
                float(production.recovery.total_structural_mass_full_kg),
                float(production.optimizer.equivalent_gates.failure_index),
                float(production.optimizer.equivalent_gates.buckling_index),
                float(production.optimizer.equivalent_gates.tip_deflection_m),
                float(production.optimizer.equivalent_gates.twist_max_deg),
                float(inverse.loaded_shape_match.main_z_max_abs_error_m),
                float(inverse.loaded_shape_match.main_z_rms_error_m),
                float(inverse.loaded_shape_match.twist_max_abs_error_deg),
                float(inverse.loaded_shape_match.twist_rms_error_deg),
                float(inverse.loaded_shape_match.normalized_rms_error),
                float(loaded_shape_penalty_kg),
                float(clearance_risk.risk_score),
                float(clearance_risk.hotspot_mean_clearance_m),
                float(clearance_penalty_kg),
                float(active_wall_risk_score),
                float(active_wall_penalty_kg),
                float(rib_design_penalty_kg),
                float(objective_value_kg),
                float(inverse.target_shape_error.max_abs_error_m),
                float(inverse.target_shape_error.rms_error_m),
                float(inverse.ground_clearance.min_z_m),
                float(inverse.ground_clearance.margin_m),
                float(inverse.manufacturing.max_abs_vertical_prebend_m),
                float(inverse.manufacturing.max_abs_vertical_curvature_per_m),
                *[float(value) for value in hard_margins.values()],
            ]
            if not np.all(np.isfinite(np.asarray(finite_scalars, dtype=float))):
                raise ValueError("Non-finite inverse-design metrics encountered.")

            candidate = InverseCandidate(
                z=z_bounded.copy(),
                source=source,
                message="analysis complete",
                eval_wall_time_s=float(perf_counter() - t0),
                main_plateau_scale=float(vars_physical["main_plateau_scale"]),
                main_taper_fill=float(vars_physical["main_taper_fill"]),
                rear_radius_scale=float(vars_physical["rear_radius_scale"]),
                rear_outboard_fraction=float(vars_physical["rear_outboard_fraction"]),
                wall_thickness_fraction=float(vars_physical["wall_thickness_fraction"]),
                main_t_seg_m=main_t.copy(),
                main_r_seg_m=main_r.copy(),
                rear_t_seg_m=rear_t.copy(),
                rear_r_seg_m=rear_r.copy(),
                tube_mass_kg=float(production.recovery.spar_tube_mass_full_kg),
                total_structural_mass_kg=float(production.recovery.total_structural_mass_full_kg),
                equivalent_failure_index=float(production.optimizer.equivalent_gates.failure_index),
                equivalent_buckling_index=float(production.optimizer.equivalent_gates.buckling_index),
                equivalent_tip_deflection_m=float(production.optimizer.equivalent_gates.tip_deflection_m),
                equivalent_twist_max_deg=float(production.optimizer.equivalent_gates.twist_max_deg),
                analysis_succeeded=bool(production.feasibility.analysis_succeeded),
                geometry_validity_succeeded=bool(production.feasibility.geometry_validity_succeeded),
                loaded_shape_main_z_error_max_m=float(inverse.loaded_shape_match.main_z_max_abs_error_m),
                loaded_shape_main_z_error_rms_m=float(inverse.loaded_shape_match.main_z_rms_error_m),
                loaded_shape_twist_error_max_deg=float(inverse.loaded_shape_match.twist_max_abs_error_deg),
                loaded_shape_twist_error_rms_deg=float(inverse.loaded_shape_match.twist_rms_error_deg),
                loaded_shape_normalized_error=float(inverse.loaded_shape_match.normalized_rms_error),
                loaded_shape_penalty_kg=float(loaded_shape_penalty_kg),
                clearance_risk_score=float(clearance_risk.risk_score),
                clearance_hotspot_count=int(clearance_risk.hotspot_count_below_threshold),
                clearance_hotspot_mean_m=float(clearance_risk.hotspot_mean_clearance_m),
                clearance_penalty_kg=float(clearance_penalty_kg),
                active_wall_risk_score=float(active_wall_risk_score),
                active_wall_tight_count=int(active_wall_tight_count),
                active_wall_penalty_kg=float(active_wall_penalty_kg),
                technically_clearance_fragile=bool(clearance_risk.fragile),
                objective_value_kg=float(objective_value_kg),
                target_shape_error_max_m=float(inverse.target_shape_error.max_abs_error_m),
                target_shape_error_rms_m=float(inverse.target_shape_error.rms_error_m),
                jig_ground_clearance_min_m=float(inverse.ground_clearance.min_z_m),
                jig_ground_clearance_margin_m=float(inverse.ground_clearance.margin_m),
                max_jig_vertical_prebend_m=float(inverse.manufacturing.max_abs_vertical_prebend_m),
                max_jig_vertical_curvature_per_m=float(inverse.manufacturing.max_abs_vertical_curvature_per_m),
                safety_passed=bool(inverse.feasibility.safety_passed),
                manufacturing_passed=bool(inverse.feasibility.manufacturing_passed),
                overall_feasible=bool(inverse.feasibility.overall_feasible),
                mass_margin_kg=float(mass_margin_kg),
                target_mass_passed=bool(target_mass_passed),
                overall_target_feasible=bool(overall_target_feasible),
                failures=tuple(inverse.feasibility.failures),
                hard_margins=hard_margins,
                hard_violation_score=float(hard_violation_score),
                target_violation_score=float(target_violation_score),
                rib_bay_surrogate=rib_bay_surrogate,
                rib_design=rib_design,
                inverse_result=inverse,
                equivalent_result=eq_result,
                mainline_model=model,
                production_result=production,
            )
        except Exception as exc:  # pragma: no cover - runtime failure guard
            hard_margins = {name: FAILED_MARGIN for name in ALL_MARGIN_NAMES}
            failed_mass_margin_kg = (
                float("inf")
                if self.target_mass_kg is None
                else float(self.target_mass_kg - FAILED_MASS_KG)
            )
            candidate = InverseCandidate(
                z=z_bounded.copy(),
                source=source,
                message=f"{type(exc).__name__}: {exc}",
                eval_wall_time_s=float(perf_counter() - t0),
                main_plateau_scale=float(vars_physical["main_plateau_scale"]),
                main_taper_fill=float(vars_physical["main_taper_fill"]),
                rear_radius_scale=float(vars_physical["rear_radius_scale"]),
                rear_outboard_fraction=float(vars_physical["rear_outboard_fraction"]),
                wall_thickness_fraction=float(vars_physical["wall_thickness_fraction"]),
                main_t_seg_m=main_t.copy(),
                main_r_seg_m=main_r.copy(),
                rear_t_seg_m=rear_t.copy(),
                rear_r_seg_m=rear_r.copy(),
                tube_mass_kg=FAILED_MASS_KG,
                total_structural_mass_kg=FAILED_MASS_KG,
                equivalent_failure_index=float("inf"),
                equivalent_buckling_index=float("inf"),
                equivalent_tip_deflection_m=float("inf"),
                equivalent_twist_max_deg=float("inf"),
                analysis_succeeded=False,
                geometry_validity_succeeded=False,
                loaded_shape_main_z_error_max_m=float("inf"),
                loaded_shape_main_z_error_rms_m=float("inf"),
                loaded_shape_twist_error_max_deg=float("inf"),
                loaded_shape_twist_error_rms_deg=float("inf"),
                loaded_shape_normalized_error=float("inf"),
                loaded_shape_penalty_kg=float("inf"),
                clearance_risk_score=float("inf"),
                clearance_hotspot_count=0,
                clearance_hotspot_mean_m=float("-inf"),
                clearance_penalty_kg=float("inf"),
                active_wall_risk_score=float("inf"),
                active_wall_tight_count=0,
                active_wall_penalty_kg=float("inf"),
                technically_clearance_fragile=False,
                objective_value_kg=FAILED_MASS_KG,
                target_shape_error_max_m=float("inf"),
                target_shape_error_rms_m=float("inf"),
                jig_ground_clearance_min_m=float("-inf"),
                jig_ground_clearance_margin_m=FAILED_MARGIN,
                max_jig_vertical_prebend_m=float("inf"),
                max_jig_vertical_curvature_per_m=float("inf"),
                safety_passed=False,
                manufacturing_passed=False,
                overall_feasible=False,
                mass_margin_kg=float(failed_mass_margin_kg),
                target_mass_passed=False if self.target_mass_kg is not None else True,
                overall_target_feasible=False,
                failures=("analysis_exception",),
                hard_margins=hard_margins,
                hard_violation_score=float("inf"),
                target_violation_score=float("inf"),
                rib_bay_surrogate=None,
                rib_design=rib_design,
                inverse_result=None,
                equivalent_result=None,
                mainline_model=None,
                production_result=None,
            )

        self.unique_evaluations += 1
        self._cache[key] = candidate
        self.archive.add(candidate)
        return candidate


def build_constraint_functions(
    *,
    evaluator: InverseDesignEvaluator,
    lb: np.ndarray,
    ub: np.ndarray,
) -> list[dict]:
    """COBYLA constraints for reduced-variable bounds and all hard margins."""

    constraints: list[dict] = []
    for idx in range(lb.size):
        constraints.append({"type": "ineq", "fun": lambda z, ii=idx: z[ii] - lb[ii]})
        constraints.append({"type": "ineq", "fun": lambda z, ii=idx: ub[ii] - z[ii]})

    for key in ALL_MARGIN_NAMES:
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda z, margin_name=key: float(
                    evaluator.evaluate(z, source=f"constraint:{margin_name}").hard_margins[margin_name]
                ),
            }
        )
    if evaluator.target_mass_kg is not None:
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda z: float(
                    evaluator.evaluate(z, source="constraint:target_mass").mass_margin_kg
                ),
            }
        )
    return constraints


def build_opt_result_from_candidate(candidate: InverseCandidate, cfg) -> OptimizationResult:
    """Rebuild an OptimizationResult-like object for export utilities."""

    load_case = cfg.structural_load_cases()[0]
    return OptimizationResult(
        success=bool(candidate.analysis_succeeded),
        message=f"reconstructed from inverse-design candidate ({candidate.source})",
        spar_mass_half_kg=0.5 * float(candidate.tube_mass_kg),
        spar_mass_full_kg=float(candidate.tube_mass_kg),
        total_mass_full_kg=float(candidate.total_structural_mass_kg),
        max_stress_main_Pa=0.0,
        max_stress_rear_Pa=0.0,
        allowable_stress_main_Pa=1.0,
        allowable_stress_rear_Pa=1.0,
        failure_index=float(candidate.equivalent_failure_index),
        buckling_index=float(candidate.equivalent_buckling_index),
        tip_deflection_m=float(candidate.equivalent_tip_deflection_m),
        max_tip_deflection_m=load_case.max_tip_deflection_m,
        twist_max_deg=float(candidate.equivalent_twist_max_deg),
        max_twist_limit_deg=load_case.max_twist_deg,
        main_t_seg_mm=np.asarray(candidate.main_t_seg_m, dtype=float) * 1000.0,
        main_r_seg_mm=np.asarray(candidate.main_r_seg_m, dtype=float) * 1000.0,
        rear_t_seg_mm=np.asarray(candidate.rear_t_seg_m, dtype=float) * 1000.0,
        rear_r_seg_mm=np.asarray(candidate.rear_r_seg_m, dtype=float) * 1000.0,
        disp=None,
        vonmises_main=None,
        vonmises_rear=None,
    )


def _shape_error_stats(*, target_shape, predicted_shape) -> tuple[float, float]:
    error_main = (
        np.asarray(predicted_shape.main_nodes_m, dtype=float)
        - np.asarray(target_shape.main_nodes_m, dtype=float)
    )
    error_rear = (
        np.asarray(predicted_shape.rear_nodes_m, dtype=float)
        - np.asarray(target_shape.rear_nodes_m, dtype=float)
    )
    stacked = np.vstack((error_main, error_rear))
    node_norms = np.linalg.norm(stacked, axis=1) if stacked.size else np.zeros(0, dtype=float)
    max_abs_error_m = float(np.max(node_norms)) if node_norms.size else 0.0
    rms_error_m = float(np.sqrt(np.mean(np.square(node_norms)))) if node_norms.size else 0.0
    return max_abs_error_m, rms_error_m


def _mapped_load_delta_metrics(previous_loads: dict, current_loads: dict) -> tuple[float, float, float, float]:
    y_curr = np.asarray(current_loads["y"], dtype=float)
    y_prev = np.asarray(previous_loads["y"], dtype=float)
    lift_prev = np.interp(
        y_curr,
        y_prev,
        np.asarray(previous_loads["lift_per_span"], dtype=float),
        left=0.0,
        right=0.0,
    )
    lift_curr = np.asarray(current_loads["lift_per_span"], dtype=float)
    torque_prev = np.interp(
        y_curr,
        y_prev,
        np.asarray(previous_loads["torque_per_span"], dtype=float),
        left=0.0,
        right=0.0,
    )
    torque_curr = np.asarray(current_loads["torque_per_span"], dtype=float)
    lift_delta = lift_curr - lift_prev
    torque_delta = torque_curr - torque_prev
    return (
        float(np.sqrt(np.mean(np.square(lift_delta)))),
        float(np.max(np.abs(lift_delta))),
        float(np.sqrt(np.mean(np.square(torque_delta)))),
        float(np.max(np.abs(torque_delta))),
    )


def _run_forward_refresh_check(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    optimizer: SparOptimizer,
    export_loads: dict,
    candidate: InverseCandidate,
    previous_iteration_index: int,
) -> ForwardRefreshCheck | None:
    if candidate.inverse_result is None:
        return None

    eq_result = optimizer.analyze(
        main_t_seg=np.asarray(candidate.main_t_seg_m, dtype=float),
        main_r_seg=np.asarray(candidate.main_r_seg_m, dtype=float),
        rear_t_seg=np.asarray(candidate.rear_t_seg_m, dtype=float),
        rear_r_seg=np.asarray(candidate.rear_r_seg_m, dtype=float),
    )
    model = build_dual_beam_mainline_model(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=eq_result,
        export_loads=export_loads,
        materials_db=materials_db,
    )
    refreshed = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
    )
    predicted_loaded_shape = predict_loaded_shape(
        jig_shape=candidate.inverse_result.jig_shape,
        disp_main_m=refreshed.disp_main_m,
        disp_rear_m=refreshed.disp_rear_m,
    )
    max_err_m, rms_err_m = _shape_error_stats(
        target_shape=candidate.inverse_result.target_loaded_shape,
        predicted_shape=predicted_loaded_shape,
    )
    return ForwardRefreshCheck(
        previous_iteration_index=int(previous_iteration_index),
        target_shape_error_max_m=max_err_m,
        target_shape_error_rms_m=rms_err_m,
        equivalent_tip_deflection_m=float(refreshed.optimizer.equivalent_gates.tip_deflection_m),
        equivalent_twist_max_deg=float(refreshed.optimizer.equivalent_gates.twist_max_deg),
    )


def _build_refresh_iteration_result(
    *,
    iteration_index: int,
    load_source: str,
    outcome: InverseOutcome,
    mapped_loads: dict,
    load_metrics: RefreshLoadMetrics,
    map_config: ReducedMapConfig,
    dynamic_design_space_applied: bool,
    previous: RefreshIterationResult | None,
    forward_check: ForwardRefreshCheck | None,
) -> RefreshIterationResult:
    result = RefreshIterationResult(
        iteration_index=int(iteration_index),
        load_source=str(load_source),
        outcome=outcome,
        load_metrics=load_metrics,
        mapped_loads=dict(mapped_loads),
        map_config_summary=_map_config_to_dict(map_config),
        dynamic_design_space_applied=bool(dynamic_design_space_applied),
        forward_check=forward_check,
    )
    if previous is None:
        return result

    prev_selected = previous.outcome.selected
    curr_selected = outcome.selected
    (
        result.lift_rms_delta_npm,
        result.lift_max_abs_delta_npm,
        result.torque_rms_delta_nmpm,
        result.torque_max_abs_delta_nmpm,
    ) = _mapped_load_delta_metrics(previous.mapped_loads, mapped_loads)
    result.mass_delta_kg = float(curr_selected.total_structural_mass_kg - prev_selected.total_structural_mass_kg)
    result.inverse_target_error_delta_m = float(
        curr_selected.target_shape_error_max_m - prev_selected.target_shape_error_max_m
    )
    result.ground_clearance_delta_m = float(
        curr_selected.jig_ground_clearance_min_m - prev_selected.jig_ground_clearance_min_m
    )
    result.prebend_delta_m = float(
        curr_selected.max_jig_vertical_prebend_m - prev_selected.max_jig_vertical_prebend_m
    )
    result.curvature_delta_per_m = float(
        curr_selected.max_jig_vertical_curvature_per_m - prev_selected.max_jig_vertical_curvature_per_m
    )
    result.failure_delta = float(
        curr_selected.equivalent_failure_index - prev_selected.equivalent_failure_index
    )
    result.buckling_delta = float(
        curr_selected.equivalent_buckling_index - prev_selected.equivalent_buckling_index
    )
    result.tip_deflection_delta_m = float(
        curr_selected.equivalent_tip_deflection_m - prev_selected.equivalent_tip_deflection_m
    )
    result.twist_delta_deg = float(
        curr_selected.equivalent_twist_max_deg - prev_selected.equivalent_twist_max_deg
    )
    return result


def candidate_to_summary_dict(candidate: InverseCandidate) -> dict[str, object]:
    inverse = candidate.inverse_result
    feasibility_report = None
    target_shape = None
    jig_shape = None
    predicted_loaded_shape = None
    clearance_hotspots = None
    validity_status = None
    if inverse is not None:
        clearance_hotspots = [
            asdict(hotspot)
            for hotspot in _clearance_hotspots(
                inverse_result=inverse,
                clearance_floor_z_m=float(inverse.ground_clearance.clearance_floor_z_m),
                top_k=5,
            )
        ]
        feasibility_report = {
            "analysis_succeeded": inverse.feasibility.analysis_succeeded,
            "geometry_validity_passed": inverse.feasibility.geometry_validity_passed,
            "equivalent_failure_passed": inverse.feasibility.equivalent_failure_passed,
            "equivalent_buckling_passed": inverse.feasibility.equivalent_buckling_passed,
            "equivalent_tip_passed": inverse.feasibility.equivalent_tip_passed,
            "equivalent_twist_passed": inverse.feasibility.equivalent_twist_passed,
            "loaded_shape_match_passed": inverse.feasibility.loaded_shape_match_passed,
            "target_shape_error_passed": inverse.feasibility.target_shape_error_passed,
            "ground_clearance_passed": inverse.feasibility.ground_clearance_passed,
            "manufacturing_passed": inverse.feasibility.manufacturing_passed,
            "safety_passed": inverse.feasibility.safety_passed,
            "overall_feasible": inverse.feasibility.overall_feasible,
            "failures": list(inverse.feasibility.failures),
            "loaded_shape_match": asdict(inverse.loaded_shape_match),
            "target_shape_error": asdict(inverse.target_shape_error),
            "ground_clearance": asdict(inverse.ground_clearance),
            "manufacturing": asdict(inverse.manufacturing),
            "monotonic_deflection": (
                None
                if inverse.monotonic_deflection is None
                else asdict(inverse.monotonic_deflection)
            ),
        }
        validity_status = _candidate_validity_status(candidate)
        target_shape = shape_to_dict(inverse.target_loaded_shape)
        jig_shape = shape_to_dict(inverse.jig_shape)
        predicted_loaded_shape = shape_to_dict(inverse.predicted_loaded_shape)

    return {
        "source": candidate.source,
        "message": candidate.message,
        "reduced_variables": {
            "main_plateau_scale": candidate.main_plateau_scale,
            "main_taper_fill": candidate.main_taper_fill,
            "rear_radius_scale": candidate.rear_radius_scale,
            "rear_outboard_fraction": candidate.rear_outboard_fraction,
            "wall_thickness_fraction": candidate.wall_thickness_fraction,
        },
        "tube_mass_kg": candidate.tube_mass_kg,
        "total_structural_mass_kg": candidate.total_structural_mass_kg,
        "equivalent_failure_index": candidate.equivalent_failure_index,
        "equivalent_buckling_index": candidate.equivalent_buckling_index,
        "equivalent_tip_deflection_m": candidate.equivalent_tip_deflection_m,
        "equivalent_twist_max_deg": candidate.equivalent_twist_max_deg,
        "analysis_succeeded": candidate.analysis_succeeded,
        "geometry_validity_succeeded": candidate.geometry_validity_succeeded,
        "loaded_shape_main_z_error_max_m": candidate.loaded_shape_main_z_error_max_m,
        "loaded_shape_main_z_error_rms_m": candidate.loaded_shape_main_z_error_rms_m,
        "loaded_shape_twist_error_max_deg": candidate.loaded_shape_twist_error_max_deg,
        "loaded_shape_twist_error_rms_deg": candidate.loaded_shape_twist_error_rms_deg,
        "loaded_shape_normalized_error": candidate.loaded_shape_normalized_error,
        "loaded_shape_penalty_kg": candidate.loaded_shape_penalty_kg,
        "clearance_risk_score": candidate.clearance_risk_score,
        "clearance_hotspot_count": candidate.clearance_hotspot_count,
        "clearance_hotspot_mean_m": candidate.clearance_hotspot_mean_m,
        "clearance_penalty_kg": candidate.clearance_penalty_kg,
        "active_wall_risk_score": candidate.active_wall_risk_score,
        "active_wall_tight_count": candidate.active_wall_tight_count,
        "active_wall_penalty_kg": candidate.active_wall_penalty_kg,
        "technically_clearance_fragile": candidate.technically_clearance_fragile,
        "objective_value_kg": candidate.objective_value_kg,
        "target_shape_error_max_m": candidate.target_shape_error_max_m,
        "target_shape_error_rms_m": candidate.target_shape_error_rms_m,
        "jig_ground_clearance_min_m": candidate.jig_ground_clearance_min_m,
        "jig_ground_clearance_margin_m": candidate.jig_ground_clearance_margin_m,
        "max_jig_vertical_prebend_m": candidate.max_jig_vertical_prebend_m,
        "max_jig_vertical_curvature_per_m": candidate.max_jig_vertical_curvature_per_m,
        "safety_passed": candidate.safety_passed,
        "manufacturing_passed": candidate.manufacturing_passed,
        "overall_feasible": candidate.overall_feasible,
        "mass_margin_kg": candidate.mass_margin_kg,
        "target_mass_passed": candidate.target_mass_passed,
        "overall_target_feasible": candidate.overall_target_feasible,
        "failures": list(candidate.failures),
        "validity_status": validity_status,
        "hard_violation_score": candidate.hard_violation_score,
        "target_violation_score": candidate.target_violation_score,
        "hard_margins": {key: float(value) for key, value in candidate.hard_margins.items()},
        "rib_bay_surrogate": (
            None if candidate.rib_bay_surrogate is None else asdict(candidate.rib_bay_surrogate)
        ),
        "rib_design": (
            None if candidate.rib_design is None else asdict(candidate.rib_design)
        ),
        "clearance_hotspots": clearance_hotspots,
        "design_mm": {
            "main_t": [float(value * 1000.0) for value in candidate.main_t_seg_m],
            "main_r": [float(value * 1000.0) for value in candidate.main_r_seg_m],
            "rear_t": [float(value * 1000.0) for value in candidate.rear_t_seg_m],
            "rear_r": [float(value * 1000.0) for value in candidate.rear_r_seg_m],
        },
        "target_loaded_shape": target_shape,
        "jig_shape": jig_shape,
        "predicted_loaded_shape": predicted_loaded_shape,
        "monotonic_deflection": (
            None
            if inverse is None or inverse.monotonic_deflection is None
            else asdict(inverse.monotonic_deflection)
        ),
        "feasibility_report": feasibility_report,
    }


def _build_lighten_probe_diagnostics(
    *,
    evaluator: InverseDesignEvaluator,
    selected: InverseCandidate,
    step_size: float = 0.03,
) -> tuple[dict[str, object], ...]:
    probes: list[dict[str, object]] = []
    z_base = np.asarray(selected.z, dtype=float).reshape(-1)
    rib_design_key = (
        evaluator.default_rib_design_key
        if selected.rib_design is None
        else selected.rib_design.design_key
    )
    for idx, name in enumerate(SCALE_NAMES):
        candidates: list[InverseCandidate] = []
        for direction, delta in (("minus", -float(step_size)), ("plus", float(step_size))):
            z_try = z_base.copy()
            z_try[idx] = np.clip(z_try[idx] + delta, 0.0, 1.0)
            if np.max(np.abs(z_try - z_base)) < 1.0e-12:
                continue
            candidates.append(
                evaluator.evaluate(
                    z_try,
                    source=f"probe:{name}:{direction}",
                    rib_design_key=rib_design_key,
                )
            )
        if not candidates:
            continue
        lighter = min(candidates, key=lambda cand: float(cand.total_structural_mass_kg))
        probes.append(
            {
                "variable": name,
                "selected_z": float(z_base[idx]),
                "trial_z": float(lighter.z[idx]),
                "mass_delta_kg": float(lighter.total_structural_mass_kg - selected.total_structural_mass_kg),
                "clearance_delta_m": float(lighter.jig_ground_clearance_min_m - selected.jig_ground_clearance_min_m),
                "failure_delta": float(lighter.equivalent_failure_index - selected.equivalent_failure_index),
                "buckling_delta": float(lighter.equivalent_buckling_index - selected.equivalent_buckling_index),
                "dominant_blocker": _dominant_blocker_name(lighter),
                "dominant_blocker_margin": float(
                    min(lighter.hard_margins.items(), key=lambda item: float(item[1]))[1]
                ),
                "overall_feasible": bool(lighter.overall_feasible),
                "target_mass_passed": bool(lighter.target_mass_passed),
                "clearance_risk_score": float(lighter.clearance_risk_score),
            }
        )
    return tuple(sorted(probes, key=lambda item: (item["mass_delta_kg"], item["dominant_blocker"])))


def _active_wall_diagnostics_for_candidate(
    *,
    candidate: InverseCandidate,
    cfg,
    lighten_probes: tuple[dict[str, object], ...],
) -> ActiveWallDiagnostics:
    geometry_walls = _geometry_wall_entries(candidate, cfg)
    reduced_bounds = _reduced_variable_bound_entries(candidate)
    blocker_counts: dict[str, int] = {}
    for probe in lighten_probes:
        blocker = str(probe["dominant_blocker"])
        blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
    principal_bottleneck = (
        max(blocker_counts.items(), key=lambda item: item[1])[0]
        if blocker_counts
        else _dominant_blocker_name(candidate)
    )
    if candidate.jig_ground_clearance_min_m <= 1.0e-6:
        primary_driver = "ground clearance"
    elif geometry_walls:
        primary_driver = geometry_walls[0].name
    else:
        primary_driver = principal_bottleneck
    return ActiveWallDiagnostics(
        principal_bottleneck=str(principal_bottleneck),
        primary_driver=str(primary_driver),
        active_wall_risk_score=float(candidate.active_wall_risk_score),
        tight_wall_count=int(candidate.active_wall_tight_count),
        geometry_walls=geometry_walls,
        reduced_variable_bounds=reduced_bounds,
        lighten_probes=lighten_probes,
    )


def _lift_wire_rigging_records(
    *,
    candidate: InverseCandidate,
    cfg,
    materials_db: MaterialDB,
) -> tuple[LiftWireRiggingRecord, ...]:
    if candidate.mainline_model is None or candidate.production_result is None:
        return ()
    if not (cfg.lift_wires.enabled and cfg.lift_wires.attachments):
        return ()

    model = candidate.mainline_model
    result = candidate.production_result
    wire_node_indices = tuple(int(idx) for idx in getattr(model, "wire_node_indices", ()))
    if not wire_node_indices:
        return ()

    wire_material = materials_db.get(cfg.lift_wires.cable_material)
    cable_area_m2 = float(np.pi * (0.5 * float(cfg.lift_wires.cable_diameter)) ** 2)
    allowable_tension_n = (
        float(cfg.lift_wires.max_tension_fraction) * float(wire_material.tensile_strength) * cable_area_m2
    )
    if hasattr(cfg.lift_wires, "attachment_wire_angles_deg"):
        wire_angles_deg = cfg.lift_wires.attachment_wire_angles_deg()
    else:
        wire_angles_deg = [float(cfg.lift_wires.wire_angle_deg)] * len(cfg.lift_wires.attachments)
    has_wire_resultants = hasattr(result.reactions, "wire_resultants_n")
    wire_resultants_n = np.asarray(
        getattr(result.reactions, "wire_resultants_n", np.zeros(0, dtype=float)),
        dtype=float,
    )
    wire_reactions_n = np.asarray(
        getattr(result.reactions, "wire_reactions_n", np.zeros(len(wire_node_indices), dtype=float)),
        dtype=float,
    )
    wire_anchor_points_m = np.asarray(
        getattr(model, "wire_anchor_points_m", np.zeros((0, 3), dtype=float)),
        dtype=float,
    )
    wire_unstretched_lengths_m = np.asarray(
        getattr(model, "wire_unstretched_lengths_m", np.zeros(0, dtype=float)),
        dtype=float,
    )
    wire_area_m2 = np.asarray(
        getattr(model, "wire_area_m2", np.full(len(wire_node_indices), cable_area_m2, dtype=float)),
        dtype=float,
    )
    wire_young_pa = np.asarray(
        getattr(model, "wire_young_pa", np.full(len(wire_node_indices), float(wire_material.E), dtype=float)),
        dtype=float,
    )
    wire_allowable_tension_n = np.asarray(
        getattr(model, "wire_allowable_tension_n", np.full(len(wire_node_indices), allowable_tension_n, dtype=float)),
        dtype=float,
    )

    records: list[LiftWireRiggingRecord] = []
    for idx, (att, angle_deg, node_index) in enumerate(
        zip(
            cfg.lift_wires.attachments,
            wire_angles_deg,
            wire_node_indices,
            strict=True,
        )
    ):
        loaded_attach = np.asarray(model.nodes_main_m[node_index], dtype=float) + np.asarray(
            result.disp_main_m[node_index, :3],
            dtype=float,
        )
        if wire_anchor_points_m.shape == (len(wire_node_indices), 3):
            anchor = np.asarray(wire_anchor_points_m[idx], dtype=float)
        else:
            anchor = np.array(
                [
                    float(model.nodes_main_m[node_index, 0]),
                    0.0,
                    float(att.fuselage_z),
                ],
                dtype=float,
            )
        L_flight_m = float(np.linalg.norm(loaded_attach - anchor))
        if has_wire_resultants and wire_resultants_n.shape == (len(wire_node_indices),):
            tension_force_n = max(float(wire_resultants_n[idx]), 0.0)
        else:
            theta = np.deg2rad(float(angle_deg))
            sin_theta = max(abs(float(np.sin(theta))), 1.0e-12)
            tension_force_n = float(abs(wire_reactions_n[idx]) / sin_theta)

        if wire_unstretched_lengths_m.shape == (len(wire_node_indices),):
            L_cut_m = float(wire_unstretched_lengths_m[idx])
        else:
            axial_rigidity_n = max(float(wire_area_m2[idx]) * float(wire_young_pa[idx]), 1.0e-12)
            L_cut_m = float(L_flight_m / (1.0 + tension_force_n / axial_rigidity_n))
        delta_L_m = float(L_flight_m - L_cut_m)
        allowable_n = (
            float(wire_allowable_tension_n[idx])
            if wire_allowable_tension_n.shape == (len(wire_node_indices),)
            else float(allowable_tension_n)
        )
        records.append(
            LiftWireRiggingRecord(
                identifier=str(att.label or f"wire-{len(records) + 1}"),
                side="positive_half_span",
                attach_node_index=int(node_index),
                attach_y_m=float(model.y_nodes_m[node_index]),
                attach_point_loaded_m=tuple(float(value) for value in loaded_attach),
                anchor_point_m=tuple(float(value) for value in anchor),
                L_flight_m=L_flight_m,
                delta_L_m=delta_L_m,
                L_cut_m=L_cut_m,
                tension_force_n=tension_force_n,
                vertical_reaction_n=float(wire_reactions_n[idx]),
                allowable_tension_n=allowable_n,
                tension_margin_n=float(allowable_n - tension_force_n),
                attach_label=str(att.label or ""),
            )
        )
    return tuple(records)


def build_report_text(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    map_config: ReducedMapConfig,
    outcome: InverseOutcome,
) -> str:
    baseline = outcome.baseline
    selected = outcome.selected
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    selected_inverse = selected.inverse_result
    loaded_shape_match = None if selected_inverse is None else selected_inverse.loaded_shape_match

    lines: list[str] = []
    lines.append("=" * 108)
    lines.append("Frozen-Load Aeroelastic Inverse Design MVP")
    lines.append("=" * 108)
    lines.append(f"Generated                     : {generated}")
    lines.append(f"Config                        : {config_path}")
    lines.append(f"Design report                 : {design_report}")
    lines.append(f"Cruise AoA                    : {cruise_aoa_deg:.3f} deg")
    lines.append("")
    lines.append("Definition:")
    lines.append("  target_loaded_shape         : current VSP / structural cruise geometry at the beam nodes")
    lines.append("  frozen_load_source          : cruise mapped loads on that target shape (no load refresh loop)")
    if loaded_shape_match is not None and loaded_shape_match.mode == "low_dim_descriptor":
        lines.append("  jig_shape                   : nodes_target - projected displacement that matches main-beam Z and twist at a few control stations")
        lines.append("  predicted_loaded_shape      : jig_shape + full structural displacement; noncritical nodewise mismatch is allowed")
    else:
        lines.append("  jig_shape                   : nodes_target - structural displacement")
        lines.append("  predicted_loaded_shape      : jig_shape + same frozen displacement")
    lines.append("")
    lines.append("Physics assumptions:")
    lines.append("  1. One-way frozen-load aeroelastic solve; aerodynamic loads are not refreshed after jig back-out.")
    lines.append("  2. Cruise target shape is represented on the existing main/rear spar beam lines, not the full wing skin.")
    if loaded_shape_match is not None and loaded_shape_match.mode == "low_dim_descriptor":
        lines.append("  3. Loaded-shape matching is enforced only on low-dimensional descriptors: main-beam prebend and spanwise twist at control stations.")
        lines.append("  4. Total structural mass remains the main objective; loaded-shape RMS only enters as a small penalty/tie-break.")
    else:
        lines.append("  3. Jig back-out uses the translational structural response from the production dual-beam kernel.")
    lines.append("")
    lines.append("Reduced map (existing V2 design variables):")
    lines.append(f"  main_plateau_scale upper    : {map_config.main_plateau_scale_upper:.4f}")
    lines.append(f"  main_taper_fill upper       : {map_config.main_taper_fill_upper:.4f}")
    lines.append(f"  rear_radius_scale upper     : {map_config.rear_radius_scale_upper:.4f}")
    lines.append(f"  delta_t_global_max          : {_mm(map_config.delta_t_global_max_m):.3f} mm")
    lines.append(f"  delta_t_rear_outboard_max   : {_mm(map_config.delta_t_rear_outboard_max_m):.3f} mm")
    lines.append("")
    lines.append("Manufacturing limits:")
    lines.append(f"  source                      : {outcome.manufacturing_limit_source}")
    lines.append(
        "  max jig vertical prebend    : "
        + (
            f"{_mm(outcome.max_jig_vertical_prebend_limit_m):.3f} mm"
            if outcome.max_jig_vertical_prebend_limit_m is not None
            else "none"
        )
    )
    lines.append(
        "  max jig vertical curvature  : "
        + (
            f"{outcome.max_jig_vertical_curvature_limit_per_m:.6f} 1/m"
            if outcome.max_jig_vertical_curvature_limit_per_m is not None
            else "none"
        )
    )
    lines.append("")
    lines.append("Run summary:")
    lines.append(f"  success                     : {outcome.success}")
    lines.append(f"  feasible                    : {outcome.feasible}")
    lines.append(f"  total wall time             : {outcome.total_wall_time_s:.3f} s")
    lines.append(f"  baseline eval wall time     : {outcome.baseline_eval_wall_time_s:.3f} s")
    lines.append(f"  nfev                        : {outcome.nfev}")
    lines.append(f"  nit                         : {outcome.nit}")
    lines.append(f"  equivalent analysis calls   : {outcome.equivalent_analysis_calls}")
    lines.append(f"  production analysis calls   : {outcome.production_analysis_calls}")
    lines.append(f"  unique evaluations          : {outcome.unique_evaluations}")
    lines.append(f"  cache hits                  : {outcome.cache_hits}")
    lines.append(f"  feasible archive count      : {outcome.feasible_count}")
    lines.append("")
    lines.append("Baseline candidate:")
    lines.append(f"  Total structural mass       {baseline.total_structural_mass_kg:11.3f} kg")
    lines.append(f"  Loaded-shape main-Z max     {_mm(baseline.loaded_shape_main_z_error_max_m):11.6f} mm")
    lines.append(f"  Loaded-shape twist max      {baseline.loaded_shape_twist_error_max_deg:11.6f} deg")
    lines.append(f"  Nodewise mismatch max       {_mm(baseline.target_shape_error_max_m):11.6f} mm")
    lines.append(f"  Jig min ground clearance    {_mm(baseline.jig_ground_clearance_min_m):11.3f} mm")
    lines.append(f"  Max jig prebend             {_mm(baseline.max_jig_vertical_prebend_m):11.3f} mm")
    lines.append(f"  Max jig curvature           {baseline.max_jig_vertical_curvature_per_m:11.6f} 1/m")
    lines.append(f"  Safety                      {_status(baseline.safety_passed)}")
    lines.append(f"  Manufacturing               {_status(baseline.manufacturing_passed)}")
    lines.append(f"  Overall feasible            {_status(baseline.overall_feasible)}")
    lines.append("")
    lines.append("Selected candidate:")
    lines.append(f"  Source                       {selected.source}")
    lines.append(f"  Message                      {selected.message}")
    lines.append(f"  Total structural mass        {selected.total_structural_mass_kg:11.3f} kg")
    lines.append(f"  Spar tube mass               {selected.tube_mass_kg:11.3f} kg")
    lines.append(f"  Loaded-shape main-Z max      {_mm(selected.loaded_shape_main_z_error_max_m):11.6f} mm")
    lines.append(f"  Loaded-shape main-Z rms      {_mm(selected.loaded_shape_main_z_error_rms_m):11.6f} mm")
    lines.append(f"  Loaded-shape twist max       {selected.loaded_shape_twist_error_max_deg:11.6f} deg")
    lines.append(f"  Loaded-shape twist rms       {selected.loaded_shape_twist_error_rms_deg:11.6f} deg")
    lines.append(f"  Loaded-shape penalty         {selected.loaded_shape_penalty_kg:11.6f} kg")
    lines.append(f"  Penalized objective          {selected.objective_value_kg:11.6f} kg")
    lines.append(f"  Nodewise mismatch max        {_mm(selected.target_shape_error_max_m):11.6f} mm")
    lines.append(f"  Nodewise mismatch rms        {_mm(selected.target_shape_error_rms_m):11.6f} mm")
    lines.append(f"  Jig min ground clearance     {_mm(selected.jig_ground_clearance_min_m):11.3f} mm")
    lines.append(f"  Jig clearance margin         {_mm(selected.jig_ground_clearance_margin_m):11.3f} mm")
    lines.append(f"  Max jig prebend              {_mm(selected.max_jig_vertical_prebend_m):11.3f} mm")
    lines.append(f"  Max jig curvature            {selected.max_jig_vertical_curvature_per_m:11.6f} 1/m")
    lines.append(
        f"  Equivalent failure           {_status(selected.equivalent_failure_index <= 0.01)}  value={selected.equivalent_failure_index:.4f}"
    )
    lines.append(
        f"  Equivalent buckling          {_status(selected.equivalent_buckling_index <= 0.01)}  value={selected.equivalent_buckling_index:.4f}"
    )
    lines.append(
        f"  Equivalent tip               value={_mm(selected.equivalent_tip_deflection_m):.3f} mm"
    )
    lines.append(
        f"  Equivalent twist             value={selected.equivalent_twist_max_deg:.3f} deg"
    )
    lines.append(f"  Safety                       {_status(selected.safety_passed)}")
    lines.append(f"  Manufacturing                {_status(selected.manufacturing_passed)}")
    lines.append(f"  Overall feasible             {_status(selected.overall_feasible)}")
    lines.append(f"  Failures                     {', '.join(selected.failures) or 'none'}")
    lines.append("")
    lines.append("Selected segment design (mm):")
    lines.append(f"  main_t                       : {_fmt_array_mm(selected.main_t_seg_m)}")
    lines.append(f"  main_r                       : {_fmt_array_mm(selected.main_r_seg_m)}")
    lines.append(f"  rear_t                       : {_fmt_array_mm(selected.rear_t_seg_m)}")
    lines.append(f"  rear_r                       : {_fmt_array_mm(selected.rear_r_seg_m)}")
    lines.append("")
    lines.append("Artifacts:")
    if outcome.artifacts is not None:
        lines.append(f"  target shape CSV             : {outcome.artifacts.target_shape_csv or 'not written'}")
        lines.append(f"  jig shape CSV                : {outcome.artifacts.jig_shape_csv or 'not written'}")
        lines.append(f"  loaded shape CSV             : {outcome.artifacts.loaded_shape_csv or 'not written'}")
        lines.append(f"  deflection CSV               : {outcome.artifacts.deflection_csv or 'not written'}")
        lines.append(f"  jig STEP                     : {outcome.artifacts.jig_step_path or 'not written'}")
        lines.append(f"  loaded STEP                  : {outcome.artifacts.loaded_step_path or 'not written'}")
        lines.append(f"  validity summary JSON        : {outcome.artifacts.validity_summary_json or 'not written'}")
        lines.append(f"  STEP engine                  : {outcome.artifacts.step_engine or 'not run'}")
        if outcome.artifacts.step_error:
            lines.append(f"  Jig STEP export note         : {outcome.artifacts.step_error}")
        if outcome.artifacts.loaded_step_error:
            lines.append(f"  Loaded STEP export note      : {outcome.artifacts.loaded_step_error}")
    else:
        lines.append("  no artifacts exported")
    if outcome.local_refine is not None:
        lines.append("")
        lines.append("Local refine:")
        lines.append(f"  start source                 : {outcome.local_refine.start_source}")
        lines.append(f"  start mass                   : {outcome.local_refine.start_mass_kg:.3f} kg")
        lines.append(f"  end mass                     : {outcome.local_refine.end_mass_kg:.3f} kg")
        lines.append(f"  success                      : {outcome.local_refine.success}")
        lines.append(f"  nfev / nit                   : {outcome.local_refine.nfev} / {outcome.local_refine.nit}")
        lines.append(f"  message                      : {outcome.local_refine.message}")
    return "\n".join(lines) + "\n"


def build_summary_json(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    map_config: ReducedMapConfig,
    outcome: InverseOutcome,
) -> dict[str, object]:
    selected_inverse = outcome.selected.inverse_result
    loaded_shape_match = None if selected_inverse is None else selected_inverse.loaded_shape_match
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "cruise_aoa_deg": float(cruise_aoa_deg),
        "mvp_definition": {
            "target_loaded_shape": "current VSP / structural cruise geometry on main and rear spar beam nodes",
            "jig_shape_rule": (
                "nodes_jig = nodes_target - projected_delta_u on main-beam Z and twist descriptors"
                if loaded_shape_match is not None and loaded_shape_match.mode == "low_dim_descriptor"
                else "nodes_jig = nodes_target - delta_u"
            ),
            "frozen_load_source": "cruise mapped loads on the target shape; no aerodynamic load refresh loop in this MVP",
            "loaded_shape_matching": (
                None
                if loaded_shape_match is None
                else {
                    "mode": loaded_shape_match.mode,
                    "control_station_fractions": list(loaded_shape_match.control_station_fractions),
                    "main_z_tolerance_m": loaded_shape_match.main_z_tolerance_m,
                    "twist_tolerance_deg": loaded_shape_match.twist_tolerance_deg,
                    "descriptors": ["main_beam_z", "spanwise_twist"],
                }
            ),
            "physics_assumptions": [
                "one-way frozen-load structural solve",
                "beam-line target shape, not full wing skin",
                (
                    "loaded shape is enforced on low-dimensional descriptors instead of exact nodewise closure"
                    if loaded_shape_match is not None and loaded_shape_match.mode == "low_dim_descriptor"
                    else "loaded-shape closure uses the same frozen displacement field"
                ),
            ],
        },
        "map_config": {
            "main_plateau_scale_upper": map_config.main_plateau_scale_upper,
            "main_taper_fill_upper": map_config.main_taper_fill_upper,
            "rear_radius_scale_upper": map_config.rear_radius_scale_upper,
            "delta_t_global_max_m": map_config.delta_t_global_max_m,
            "delta_t_rear_outboard_max_m": map_config.delta_t_rear_outboard_max_m,
        },
        "manufacturing_limits": {
            "source": outcome.manufacturing_limit_source,
            "max_jig_vertical_prebend_m": outcome.max_jig_vertical_prebend_limit_m,
            "max_jig_vertical_curvature_per_m": outcome.max_jig_vertical_curvature_limit_per_m,
        },
        "outcome": {
            "success": outcome.success,
            "feasible": outcome.feasible,
            "target_mass_kg": outcome.target_mass_kg,
            "message": outcome.message,
            "total_wall_time_s": outcome.total_wall_time_s,
            "baseline_eval_wall_time_s": outcome.baseline_eval_wall_time_s,
            "nfev": outcome.nfev,
            "nit": outcome.nit,
            "equivalent_analysis_calls": outcome.equivalent_analysis_calls,
            "production_analysis_calls": outcome.production_analysis_calls,
            "unique_evaluations": outcome.unique_evaluations,
            "cache_hits": outcome.cache_hits,
            "feasible_count": outcome.feasible_count,
            "target_feasible_count": outcome.target_feasible_count,
            "baseline": candidate_to_summary_dict(outcome.baseline),
            "best_overall_feasible": (
                None if outcome.best_overall_feasible is None else candidate_to_summary_dict(outcome.best_overall_feasible)
            ),
            "best_target_feasible": (
                None if outcome.best_target_feasible is None else candidate_to_summary_dict(outcome.best_target_feasible)
            ),
            "coarse_selected": candidate_to_summary_dict(outcome.coarse_selected),
            "coarse_candidate_count": outcome.coarse_candidate_count,
            "coarse_feasible_count": outcome.coarse_feasible_count,
            "coarse_target_feasible_count": outcome.coarse_target_feasible_count,
            "selected": candidate_to_summary_dict(outcome.selected),
            "local_refine": None if outcome.local_refine is None else asdict(outcome.local_refine),
            "active_wall_diagnostics": (
                None if outcome.active_wall_diagnostics is None else asdict(outcome.active_wall_diagnostics)
            ),
        },
        "artifacts": None if outcome.artifacts is None else asdict(outcome.artifacts),
    }


def _build_refresh_iteration_summary(iteration: RefreshIterationResult) -> dict[str, object]:
    selected = iteration.outcome.selected
    return {
        "iteration_index": iteration.iteration_index,
        "load_source": iteration.load_source,
        "dynamic_design_space_applied": iteration.dynamic_design_space_applied,
        "map_config": dict(iteration.map_config_summary),
        "load_metrics": asdict(iteration.load_metrics),
        "run_metrics": {
            "success": iteration.outcome.success,
            "feasible": iteration.outcome.feasible,
            "target_mass_kg": iteration.outcome.target_mass_kg,
            "message": iteration.outcome.message,
            "total_wall_time_s": iteration.outcome.total_wall_time_s,
            "baseline_eval_wall_time_s": iteration.outcome.baseline_eval_wall_time_s,
            "nfev": iteration.outcome.nfev,
            "nit": iteration.outcome.nit,
            "equivalent_analysis_calls": iteration.outcome.equivalent_analysis_calls,
            "production_analysis_calls": iteration.outcome.production_analysis_calls,
            "unique_evaluations": iteration.outcome.unique_evaluations,
            "cache_hits": iteration.outcome.cache_hits,
            "feasible_count": iteration.outcome.feasible_count,
            "target_feasible_count": iteration.outcome.target_feasible_count,
        },
        "search_diagnostics": {
            "coarse_candidate_count": iteration.outcome.coarse_candidate_count,
            "coarse_feasible_count": iteration.outcome.coarse_feasible_count,
            "coarse_target_feasible_count": iteration.outcome.coarse_target_feasible_count,
            "best_overall_feasible": (
                None if iteration.outcome.best_overall_feasible is None else candidate_to_summary_dict(iteration.outcome.best_overall_feasible)
            ),
            "best_target_feasible": (
                None if iteration.outcome.best_target_feasible is None else candidate_to_summary_dict(iteration.outcome.best_target_feasible)
            ),
            "coarse_selected": candidate_to_summary_dict(iteration.outcome.coarse_selected),
            "local_refine": None if iteration.outcome.local_refine is None else asdict(iteration.outcome.local_refine),
            "active_wall_diagnostics": (
                None
                if iteration.outcome.active_wall_diagnostics is None
                else asdict(iteration.outcome.active_wall_diagnostics)
            ),
        },
        "selected": candidate_to_summary_dict(selected),
        "forward_check": None if iteration.forward_check is None else asdict(iteration.forward_check),
        "deltas_vs_previous": {
            "mass_delta_kg": iteration.mass_delta_kg,
            "inverse_target_error_delta_m": iteration.inverse_target_error_delta_m,
            "ground_clearance_delta_m": iteration.ground_clearance_delta_m,
            "prebend_delta_m": iteration.prebend_delta_m,
            "curvature_delta_per_m": iteration.curvature_delta_per_m,
            "failure_delta": iteration.failure_delta,
            "buckling_delta": iteration.buckling_delta,
            "tip_deflection_delta_m": iteration.tip_deflection_delta_m,
            "twist_delta_deg": iteration.twist_delta_deg,
            "lift_rms_delta_npm": iteration.lift_rms_delta_npm,
            "lift_max_abs_delta_npm": iteration.lift_max_abs_delta_npm,
            "torque_rms_delta_nmpm": iteration.torque_rms_delta_nmpm,
            "torque_max_abs_delta_nmpm": iteration.torque_max_abs_delta_nmpm,
        },
    }


def build_refresh_report_text(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    map_config: ReducedMapConfig,
    outcome: RefreshRefinementOutcome,
    refresh_washout_scale: float,
) -> str:
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    final_iteration = outcome.final_iteration
    final_inverse = final_iteration.outcome.selected.inverse_result
    loaded_shape_match = None if final_inverse is None else final_inverse.loaded_shape_match

    lines: list[str] = []
    lines.append("=" * 108)
    lines.append("Inverse-Design Load Refresh Refinement")
    lines.append("=" * 108)
    lines.append(f"Generated                     : {generated}")
    lines.append(f"Config                        : {config_path}")
    lines.append(f"Design report                 : {design_report}")
    lines.append(f"Baseline cruise AoA           : {cruise_aoa_deg:.3f} deg")
    if final_iteration.outcome.target_mass_kg is not None:
        lines.append(f"Target mass cap               : {final_iteration.outcome.target_mass_kg:.3f} kg")
    if outcome.aero_contract is not None:
        contract = outcome.aero_contract
        lines.append(f"Aero source mode              : {contract.source_mode}")
        lines.append(
            "Aero load ownership           : "
            f"{contract.load_ownership}"
        )
        lines.append(
            "Aero artifact ownership       : "
            f"{contract.artifact_ownership}"
        )
        lines.append(
            "Candidate knobs               : "
            f"target_shape_z_scale={contract.requested_knobs.get('target_shape_z_scale', float('nan')):.6f}, "
            f"dihedral_multiplier={contract.requested_knobs.get('dihedral_multiplier', float('nan')):.6f}, "
            f"dihedral_exponent={contract.requested_knobs.get('dihedral_exponent', float('nan')):.6f}"
        )
        lines.append(
            "Candidate AoA sweep           : "
            + ", ".join(f"{value:.3f}" for value in contract.aoa_sweep_deg)
        )
        geometry_artifacts = contract.geometry_artifacts
        if geometry_artifacts.get("vsp3_path"):
            lines.append(f"Candidate VSP3                : {geometry_artifacts['vsp3_path']}")
        if geometry_artifacts.get("lod_path"):
            lines.append(f"Candidate LOD                 : {geometry_artifacts['lod_path']}")
        if geometry_artifacts.get("polar_path"):
            lines.append(f"Candidate polar               : {geometry_artifacts['polar_path']}")
        for note in contract.notes:
            lines.append(f"Candidate aero note           : {note}")
    if final_iteration.outcome.selected.rib_design is not None:
        rib_design = final_iteration.outcome.selected.rib_design
        lines.append(f"Rib design mode               : {rib_design.design_mode}")
        lines.append(f"Rib design profile            : {rib_design.design_key}")
        lines.append(f"Rib mix mode                  : {rib_design.mix_mode}")
        lines.append(
            "Rib effective knockdown       : "
            f"{rib_design.effective_warping_knockdown:.6f}"
        )
    lines.append("")
    lines.append("Definition:")
    lines.append("  target_loaded_shape         : current VSP / structural cruise geometry at the beam nodes")
    if loaded_shape_match is not None and loaded_shape_match.mode == "low_dim_descriptor":
        lines.append("  jig_shape                   : nodes_target - projected displacement field that only enforces main-beam Z and twist descriptors")
    else:
        lines.append("  jig_shape                   : nodes_target - structural displacement")
    lines.append(f"  refresh method              : {_refresh_method_text(outcome.aero_contract)}")
    lines.append("  outer updates               : 1-2 one-way refresh steps only; no inner converged aero-structural loop")
    lines.append(
        f"  dynamic design space        : {'enabled' if outcome.dynamic_design_space_enabled else 'disabled'}"
    )
    lines.append(
        f"  converged outer loop        : {'yes' if outcome.converged else 'no'}"
    )
    lines.append("")
    lines.append("Physics assumptions:")
    for idx, assumption in enumerate(
        _refresh_physics_assumptions(
            contract=outcome.aero_contract,
            low_dim_loaded_shape_matching=(
                loaded_shape_match is not None and loaded_shape_match.mode == "low_dim_descriptor"
            ),
        ),
        start=1,
    ):
        lines.append(f"  {idx}. {assumption}")
    lines.append("")
    lines.append("Difference from full coupling:")
    for item in _refresh_difference_from_full_coupling(
        contract=outcome.aero_contract,
        converged=outcome.converged,
        dynamic_design_space_enabled=outcome.dynamic_design_space_enabled,
    ):
        lines.append(f"  - {item}")
    lines.append("")
    lines.append("Initial reduced map:")
    lines.append(f"  main_plateau_scale upper    : {map_config.main_plateau_scale_upper:.4f}")
    lines.append(f"  main_taper_fill upper       : {map_config.main_taper_fill_upper:.4f}")
    lines.append(f"  rear_radius_scale upper     : {map_config.rear_radius_scale_upper:.4f}")
    lines.append(f"  delta_t_global_max          : {_mm(map_config.delta_t_global_max_m):.3f} mm")
    lines.append(f"  delta_t_rear_outboard_max   : {_mm(map_config.delta_t_rear_outboard_max_m):.3f} mm")
    lines.append("")
    lines.append("Manufacturing limits:")
    lines.append(f"  source                      : {outcome.manufacturing_limit_source}")
    lines.append(
        "  max jig vertical prebend    : "
        + (
            f"{_mm(outcome.max_jig_vertical_prebend_limit_m):.3f} mm"
            if outcome.max_jig_vertical_prebend_limit_m is not None
            else "none"
        )
    )
    lines.append(
        "  max jig vertical curvature  : "
        + (
            f"{outcome.max_jig_vertical_curvature_limit_per_m:.6f} 1/m"
            if outcome.max_jig_vertical_curvature_limit_per_m is not None
            else "none"
        )
    )
    lines.append(f"  refresh washout scale       : {float(refresh_washout_scale):.3f}")
    lines.append("")
    lines.append("Refresh summary:")
    lines.append(f"  requested outer steps       : {outcome.refresh_steps_requested}")
    lines.append(f"  completed outer steps       : {outcome.refresh_steps_completed}")
    lines.append(f"  dynamic map rebuilds        : {outcome.dynamic_design_space_rebuilds}")
    lines.append(f"  converged                   : {outcome.converged}")
    if outcome.convergence_reason is not None:
        lines.append(f"  convergence reason          : {outcome.convergence_reason}")
    lines.append(f"  final feasible              : {final_iteration.outcome.feasible}")
    lines.append(f"  final selected source       : {final_iteration.outcome.selected.source}")
    if final_iteration.outcome.best_overall_feasible is not None:
        lines.append(
            "  best overall feasible mass  : "
            f"{final_iteration.outcome.best_overall_feasible.total_structural_mass_kg:.3f} kg"
        )
    if final_iteration.outcome.best_target_feasible is not None:
        lines.append(
            "  best target-feasible mass   : "
            f"{final_iteration.outcome.best_target_feasible.total_structural_mass_kg:.3f} kg"
        )
    lines.append("")

    for iteration in outcome.iterations:
        selected = iteration.outcome.selected
        coarse_selected = iteration.outcome.coarse_selected
        lines.append(f"Iteration {iteration.iteration_index}:")
        lines.append(f"  load source                 : {iteration.load_source}")
        lines.append(f"  dynamic map rebuild         : {iteration.dynamic_design_space_applied}")
        lines.append(
            f"  map plateau / taper / rear  : "
            f"{iteration.map_config_summary.get('main_plateau_scale_upper', float('nan')):.4f} / "
            f"{iteration.map_config_summary.get('main_taper_fill_upper', float('nan')):.4f} / "
            f"{iteration.map_config_summary.get('rear_radius_scale_upper', float('nan')):.4f}"
        )
        lines.append(
            f"  map delta_t / rear_outboard : "
            f"{_mm(iteration.map_config_summary.get('delta_t_global_max_m')):11.6f} mm / "
            f"{_mm(iteration.map_config_summary.get('delta_t_rear_outboard_max_m')):11.6f} mm"
        )
        lines.append(f"  coarse selected mass        : {coarse_selected.total_structural_mass_kg:11.3f} kg")
        lines.append(f"  coarse candidate count      : {iteration.outcome.coarse_candidate_count:11d}")
        lines.append(f"  coarse feasible count       : {iteration.outcome.coarse_feasible_count:11d}")
        lines.append(f"  coarse target-feasible cnt  : {iteration.outcome.coarse_target_feasible_count:11d}")
        lines.append(f"  total structural mass       : {selected.total_structural_mass_kg:11.3f} kg")
        lines.append(
            f"  coarse -> selected delta    : {selected.total_structural_mass_kg - coarse_selected.total_structural_mass_kg:+11.3f} kg"
        )
        lines.append(f"  overall feasible            : {selected.overall_feasible}")
        if iteration.outcome.target_mass_kg is not None:
            lines.append(f"  target mass passed          : {selected.target_mass_passed}")
            lines.append(f"  mass margin                 : {selected.mass_margin_kg:+11.3f} kg")
        lines.append(f"  loaded-shape main-Z max     : {_mm(selected.loaded_shape_main_z_error_max_m):11.6f} mm")
        lines.append(f"  loaded-shape main-Z rms     : {_mm(selected.loaded_shape_main_z_error_rms_m):11.6f} mm")
        lines.append(f"  loaded-shape twist max      : {selected.loaded_shape_twist_error_max_deg:11.6f} deg")
        lines.append(f"  loaded-shape twist rms      : {selected.loaded_shape_twist_error_rms_deg:11.6f} deg")
        lines.append(f"  nodewise mismatch max       : {_mm(selected.target_shape_error_max_m):11.6f} mm")
        lines.append(f"  nodewise mismatch rms       : {_mm(selected.target_shape_error_rms_m):11.6f} mm")
        lines.append(f"  loaded-shape penalty        : {selected.loaded_shape_penalty_kg:11.6f} kg")
        lines.append(f"  jig min ground clearance    : {_mm(selected.jig_ground_clearance_min_m):11.3f} mm")
        lines.append(f"  clearance risk score        : {selected.clearance_risk_score:11.6f}")
        lines.append(f"  clearance hotspot count     : {selected.clearance_hotspot_count:11d}")
        lines.append(f"  hotspot mean clearance      : {_mm(selected.clearance_hotspot_mean_m):11.3f} mm")
        lines.append(f"  clearance penalty           : {selected.clearance_penalty_kg:11.6f} kg")
        lines.append(f"  active-wall risk score      : {selected.active_wall_risk_score:11.6f}")
        lines.append(f"  active-wall tight count     : {selected.active_wall_tight_count:11d}")
        lines.append(f"  active-wall penalty         : {selected.active_wall_penalty_kg:11.6f} kg")
        if selected.rib_design is not None:
            lines.append(f"  rib design key              : {selected.rib_design.design_key}")
            lines.append(f"  rib mix mode                : {selected.rib_design.mix_mode}")
            lines.append(
                f"  rib effective knockdown     : {selected.rib_design.effective_warping_knockdown:11.6f}"
            )
            lines.append(
                f"  rib unique families         : {selected.rib_design.unique_family_count:11d}"
                f" / {selected.rib_design.max_unique_families}"
            )
            lines.append(
                f"  rib family switches         : {selected.rib_design.family_switch_count:11d}"
            )
            lines.append(
                f"  rib design penalty          : {selected.rib_design.objective_penalty_kg:11.6f} kg"
            )
        lines.append(f"  clearance fragile           : {selected.technically_clearance_fragile}")
        lines.append(f"  max jig prebend             : {_mm(selected.max_jig_vertical_prebend_m):11.3f} mm")
        lines.append(f"  max jig curvature           : {selected.max_jig_vertical_curvature_per_m:11.6f} 1/m")
        lines.append(f"  equivalent failure          : {selected.equivalent_failure_index:11.6f}")
        lines.append(f"  equivalent buckling         : {selected.equivalent_buckling_index:11.6f}")
        lines.append(f"  equivalent tip              : {_mm(selected.equivalent_tip_deflection_m):11.3f} mm")
        lines.append(f"  equivalent twist            : {selected.equivalent_twist_max_deg:11.6f} deg")
        lines.append(f"  total half-span lift        : {iteration.load_metrics.total_lift_half_n:11.3f} N")
        lines.append(f"  total half-span drag        : {iteration.load_metrics.total_drag_half_n:11.3f} N")
        lines.append(
            f"  total |torque| half-span    : {iteration.load_metrics.total_abs_torque_half_nm:11.3f} N*m"
        )
        lines.append(
            f"  effective AoA range         : {iteration.load_metrics.aoa_eff_min_deg:8.3f} .. {iteration.load_metrics.aoa_eff_max_deg:8.3f} deg"
        )
        lines.append(
            f"  twist abs max (refresh)     : {iteration.load_metrics.twist_abs_max_deg:11.6f} deg"
        )
        lines.append(
            f"  AoA clip fraction           : {100.0 * iteration.load_metrics.aoa_clip_fraction:11.3f} %"
        )
        if iteration.outcome.local_refine is not None:
            lines.append("  local refine diagnostics:")
            lines.append(f"    seed count                : {iteration.outcome.local_refine.seed_count}")
            lines.append(f"    best seed                 : {iteration.outcome.local_refine.start_source}")
            lines.append(
                f"    best seed mass            : {iteration.outcome.local_refine.start_mass_kg:11.3f} kg"
            )
            lines.append(
                f"    best end mass             : {iteration.outcome.local_refine.end_mass_kg:11.3f} kg"
            )
            lines.append(
                f"    aggregate nfev / nit      : {iteration.outcome.local_refine.nfev} / {iteration.outcome.local_refine.nit}"
            )
            lines.append(
                f"    early stop                : {iteration.outcome.local_refine.early_stop_triggered}"
            )
            if iteration.outcome.local_refine.early_stop_reason is not None:
                lines.append(
                    f"    early stop reason         : {iteration.outcome.local_refine.early_stop_reason}"
                )
            for idx, attempt in enumerate(iteration.outcome.local_refine.attempts, start=1):
                lines.append(
                    f"    attempt {idx:02d}                : "
                    f"{attempt.seed_mass_kg:8.3f} kg -> {attempt.end_mass_kg:8.3f} kg"
                    f"  feasible={attempt.end_overall_feasible}"
                )
        if iteration.forward_check is not None:
            lines.append("  forward check on previous jig:")
            lines.append(
                f"    target mismatch max       : {_mm(iteration.forward_check.target_shape_error_max_m):11.6f} mm"
            )
            lines.append(
                f"    target mismatch rms       : {_mm(iteration.forward_check.target_shape_error_rms_m):11.6f} mm"
            )
            lines.append(
                f"    refreshed tip             : {_mm(iteration.forward_check.equivalent_tip_deflection_m):11.3f} mm"
            )
            lines.append(
                f"    refreshed twist           : {iteration.forward_check.equivalent_twist_max_deg:11.6f} deg"
            )
        if iteration.mass_delta_kg is not None:
            lines.append("  delta vs previous iteration:")
            lines.append(f"    mass                      : {iteration.mass_delta_kg:+11.3f} kg")
            lines.append(
                f"    nodewise mismatch max     : {_mm(iteration.inverse_target_error_delta_m):+11.6f} mm"
            )
            lines.append(
                f"    jig ground clearance      : {_mm(iteration.ground_clearance_delta_m):+11.3f} mm"
            )
            lines.append(f"    jig prebend               : {_mm(iteration.prebend_delta_m):+11.3f} mm")
            lines.append(
                f"    jig curvature             : {iteration.curvature_delta_per_m:+11.6f} 1/m"
            )
            lines.append(f"    failure index             : {iteration.failure_delta:+11.6f}")
            lines.append(f"    buckling index            : {iteration.buckling_delta:+11.6f}")
            lines.append(
                f"    tip deflection            : {_mm(iteration.tip_deflection_delta_m):+11.3f} mm"
            )
            lines.append(f"    twist                     : {iteration.twist_delta_deg:+11.6f} deg")
            lines.append(f"    lift RMS                  : {iteration.lift_rms_delta_npm:11.3f} N/m")
            lines.append(f"    lift max abs              : {iteration.lift_max_abs_delta_npm:11.3f} N/m")
            lines.append(f"    torque RMS                : {iteration.torque_rms_delta_nmpm:11.3f} N*m/m")
            lines.append(f"    torque max abs            : {iteration.torque_max_abs_delta_nmpm:11.3f} N*m/m")
        lines.append("")

    selected = final_iteration.outcome.selected
    hotspots = ()
    if selected.inverse_result is not None:
        hotspots = _clearance_hotspots(
            inverse_result=selected.inverse_result,
            clearance_floor_z_m=float(selected.inverse_result.ground_clearance.clearance_floor_z_m),
            top_k=5,
        )
    diagnostics = final_iteration.outcome.active_wall_diagnostics
    if hotspots or diagnostics is not None:
        lines.append("Active-wall diagnostics:")
        if hotspots:
            lines.append("  clearance hotspots:")
            for hotspot in hotspots:
                lines.append(
                    f"    rank {hotspot.rank:02d}                 : "
                    f"{hotspot.spar} node {hotspot.node_index} "
                    f"side={hotspot.side} y={hotspot.y_m:.3f} m "
                    f"z={hotspot.z_m:.6f} m clearance={hotspot.clearance_m * 1000.0:.6f} mm"
                )
        if diagnostics is not None:
            lines.append(f"  principal bottleneck        : {diagnostics.principal_bottleneck}")
            lines.append(f"  primary driver              : {diagnostics.primary_driver}")
            lines.append(f"  active-wall risk score      : {diagnostics.active_wall_risk_score:.6f}")
            for entry in diagnostics.geometry_walls[:5]:
                lines.append(
                    f"  wall {entry.name:<26} : margin={entry.margin * 1000.0:9.6f} mm  "
                    f"state={entry.boundary_state}  {entry.location}  {entry.detail}"
                )
            for entry in diagnostics.reduced_variable_bounds[:5]:
                lines.append(
                    f"  reduced var {entry.name:<19} : margin={entry.margin:8.6f}  "
                    f"state={entry.boundary_state}  {entry.detail}"
                )
            if diagnostics.lighten_probes:
                lines.append("  lightening probes:")
                for probe in diagnostics.lighten_probes:
                    lines.append(
                        f"    {probe['variable']:<24}: "
                        f"dm={probe['mass_delta_kg']:+8.3f} kg  "
                        f"dclear={probe['clearance_delta_m'] * 1000.0:+9.3f} mm  "
                        f"blocker={probe['dominant_blocker']}"
                    )
        lines.append("")

    lines.append("Artifacts:")
    if outcome.artifacts is not None:
        lines.append(f"  target shape CSV             : {outcome.artifacts.target_shape_csv or 'not written'}")
        lines.append(f"  jig shape CSV                : {outcome.artifacts.jig_shape_csv or 'not written'}")
        lines.append(f"  loaded shape CSV             : {outcome.artifacts.loaded_shape_csv or 'not written'}")
        lines.append(f"  deflection CSV               : {outcome.artifacts.deflection_csv or 'not written'}")
        lines.append(f"  jig STEP                     : {outcome.artifacts.jig_step_path or 'not written'}")
        lines.append(f"  loaded STEP                  : {outcome.artifacts.loaded_step_path or 'not written'}")
        lines.append(f"  diagnostics JSON             : {outcome.artifacts.diagnostics_json or 'not written'}")
        lines.append(f"  validity summary JSON        : {outcome.artifacts.validity_summary_json or 'not written'}")
        lines.append(f"  wire rigging JSON            : {outcome.artifacts.wire_rigging_json or 'not written'}")
        lines.append(f"  aero contract JSON           : {outcome.artifacts.aero_contract_json or 'not written'}")
        lines.append(f"  STEP engine                  : {outcome.artifacts.step_engine or 'not run'}")
        if outcome.artifacts.step_error:
            lines.append(f"  Jig STEP export note         : {outcome.artifacts.step_error}")
        if outcome.artifacts.loaded_step_error:
            lines.append(f"  Loaded STEP export note      : {outcome.artifacts.loaded_step_error}")
    else:
        lines.append("  no artifacts exported")
    return "\n".join(lines) + "\n"


def build_refresh_summary_json(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    map_config: ReducedMapConfig,
    outcome: RefreshRefinementOutcome,
    refresh_washout_scale: float,
) -> dict[str, object]:
    final_inverse = outcome.final_iteration.outcome.selected.inverse_result
    loaded_shape_match = None if final_inverse is None else final_inverse.loaded_shape_match
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "cruise_aoa_deg": float(cruise_aoa_deg),
        "refinement_definition": {
            "target_loaded_shape": "current VSP / structural cruise geometry on main and rear spar beam nodes",
            "jig_shape_rule": (
                "nodes_jig = nodes_target - projected_delta_u on low-dimensional descriptors"
                if loaded_shape_match is not None and loaded_shape_match.mode == "low_dim_descriptor"
                else "nodes_jig = nodes_target - delta_u"
            ),
            "refresh_method": _refresh_method_text(outcome.aero_contract),
            "target_mass_kg": outcome.final_iteration.outcome.target_mass_kg,
            "refresh_steps_requested": outcome.refresh_steps_requested,
            "refresh_steps_completed": outcome.refresh_steps_completed,
            "dynamic_design_space_enabled": outcome.dynamic_design_space_enabled,
            "dynamic_design_space_rebuilds": outcome.dynamic_design_space_rebuilds,
            "converged": outcome.converged,
            "convergence_reason": outcome.convergence_reason,
            "refresh_washout_scale": float(refresh_washout_scale),
            "loaded_shape_matching": (
                None
                if loaded_shape_match is None
                else {
                    "mode": loaded_shape_match.mode,
                    "control_station_fractions": list(loaded_shape_match.control_station_fractions),
                    "main_z_tolerance_m": loaded_shape_match.main_z_tolerance_m,
                    "twist_tolerance_deg": loaded_shape_match.twist_tolerance_deg,
                    "descriptors": ["main_beam_z", "spanwise_twist"],
                }
            ),
            "physics_assumptions": _refresh_physics_assumptions(
                contract=outcome.aero_contract,
                low_dim_loaded_shape_matching=(
                    loaded_shape_match is not None and loaded_shape_match.mode == "low_dim_descriptor"
                ),
            ),
            "difference_from_full_coupling": _refresh_difference_from_full_coupling(
                contract=outcome.aero_contract,
                converged=outcome.converged,
                dynamic_design_space_enabled=outcome.dynamic_design_space_enabled,
            ),
        },
        "map_config": {
            "main_plateau_scale_upper": map_config.main_plateau_scale_upper,
            "main_taper_fill_upper": map_config.main_taper_fill_upper,
            "rear_radius_scale_upper": map_config.rear_radius_scale_upper,
            "delta_t_global_max_m": map_config.delta_t_global_max_m,
            "delta_t_rear_outboard_max_m": map_config.delta_t_rear_outboard_max_m,
        },
        "aero_contract": None if outcome.aero_contract is None else asdict(outcome.aero_contract),
        "manufacturing_limits": {
            "source": outcome.manufacturing_limit_source,
            "max_jig_vertical_prebend_m": outcome.max_jig_vertical_prebend_limit_m,
            "max_jig_vertical_curvature_per_m": outcome.max_jig_vertical_curvature_limit_per_m,
        },
        "iterations": [_build_refresh_iteration_summary(iteration) for iteration in outcome.iterations],
        "artifacts": None if outcome.artifacts is None else asdict(outcome.artifacts),
    }


def _build_selected_diagnostics_payload(
    *,
    candidate: InverseCandidate,
    cfg,
    active_wall_diagnostics: ActiveWallDiagnostics | None,
) -> dict[str, object]:
    inverse = candidate.inverse_result
    hotspots = []
    if inverse is not None:
        hotspots = [
            asdict(hotspot)
            for hotspot in _clearance_hotspots(
                inverse_result=inverse,
                clearance_floor_z_m=float(inverse.ground_clearance.clearance_floor_z_m),
                top_k=5,
            )
        ]
    return {
        "selected_source": candidate.source,
        "mass_kg": float(candidate.total_structural_mass_kg),
        "minimum_clearance_m": float(candidate.jig_ground_clearance_min_m),
        "clearance_risk_score": float(candidate.clearance_risk_score),
        "clearance_hotspot_count": int(candidate.clearance_hotspot_count),
        "clearance_hotspot_mean_m": float(candidate.clearance_hotspot_mean_m),
        "technically_clearance_fragile": bool(candidate.technically_clearance_fragile),
        "clearance_hotspots": hotspots,
        "active_wall_diagnostics": (
            None if active_wall_diagnostics is None else asdict(active_wall_diagnostics)
        ),
        "hard_margins": {key: float(value) for key, value in candidate.hard_margins.items()},
        "reduced_variables": {
            name: float(value)
            for name, value in zip(SCALE_NAMES, np.asarray(candidate.z, dtype=float).reshape(-1), strict=True)
        },
    }


def _candidate_validity_status(candidate: InverseCandidate) -> dict[str, object] | None:
    inverse = candidate.inverse_result
    if inverse is None:
        return None

    monotonic_status = "not_checked"
    if inverse.monotonic_deflection is not None:
        monotonic_status = "pass" if inverse.monotonic_deflection.passed else "warn"

    mainline_status = "pass" if inverse.feasibility.overall_feasible else "fail"
    legacy_reference_status = "pass" if inverse.feasibility.legacy_reference_passed else "warn"
    overall_status = mainline_status
    if overall_status == "pass" and (
        legacy_reference_status != "pass" or monotonic_status == "warn"
    ):
        overall_status = "warn"

    return {
        "overall_status": overall_status,
        "mainline_gate_status": mainline_status,
        "legacy_reference_status": legacy_reference_status,
        "monotonic_deflection_status": monotonic_status,
    }


def _build_validity_summary_payload(
    *,
    candidate: InverseCandidate,
    active_wall_diagnostics: ActiveWallDiagnostics | None,
) -> dict[str, object]:
    inverse = candidate.inverse_result
    if inverse is None:
        return {
            "overall_status": "fail",
            "message": "selected candidate has no inverse-design payload",
            "selected_source": candidate.source,
        }

    inverse_margins = build_inverse_design_margins(inverse)
    negative_hard_margins = {
        key: float(value)
        for key, value in sorted(candidate.hard_margins.items())
        if float(value) < 0.0
    }
    validity_status = _candidate_validity_status(candidate)
    active_wall = None if active_wall_diagnostics is None else asdict(active_wall_diagnostics)
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "selected_source": candidate.source,
        "selected_message": candidate.message,
        "overall_status": None if validity_status is None else validity_status["overall_status"],
        "validity_status": validity_status,
        "mainline_feasibility": {
            "overall_feasible": bool(inverse.feasibility.overall_feasible),
            "safety_passed": bool(inverse.feasibility.safety_passed),
            "manufacturing_passed": bool(inverse.feasibility.manufacturing_passed),
            "failures": list(inverse.feasibility.failures),
        },
        "legacy_reference": {
            "passed": bool(inverse.feasibility.legacy_reference_passed),
            "failures": list(inverse.feasibility.legacy_reference_failures),
        },
        "metrics": {
            "loaded_shape_match": asdict(inverse.loaded_shape_match),
            "target_shape_error": asdict(inverse.target_shape_error),
            "ground_clearance": asdict(inverse.ground_clearance),
            "manufacturing": asdict(inverse.manufacturing),
            "monotonic_deflection": (
                None
                if inverse.monotonic_deflection is None
                else asdict(inverse.monotonic_deflection)
            ),
            "candidate": {
                "total_structural_mass_kg": float(candidate.total_structural_mass_kg),
                "tube_mass_kg": float(candidate.tube_mass_kg),
                "objective_value_kg": float(candidate.objective_value_kg),
                "clearance_risk_score": float(candidate.clearance_risk_score),
                "active_wall_risk_score": float(candidate.active_wall_risk_score),
                "technically_clearance_fragile": bool(candidate.technically_clearance_fragile),
            },
        },
        "margins": {
            "inverse_design": {key: float(value) for key, value in inverse_margins.items()},
            "hard_constraints": {
                key: float(value) for key, value in sorted(candidate.hard_margins.items())
            },
        },
        "blockers": {
            "primary_failures": list(inverse.feasibility.failures),
            "negative_hard_margins": negative_hard_margins,
            "technically_clearance_fragile": bool(candidate.technically_clearance_fragile),
            "active_wall_principal_bottleneck": (
                None if active_wall is None else active_wall.get("principal_bottleneck")
            ),
            "active_wall_primary_driver": (
                None if active_wall is None else active_wall.get("primary_driver")
            ),
        },
    }


def _write_deflection_csv(
    path: Path,
    *,
    candidate: InverseCandidate,
    model,
) -> None:
    """Write per-node displacement/rotation rows for main and rear spars."""

    inverse = candidate.inverse_result
    if inverse is None:
        raise ValueError("Cannot export deflection CSV without inverse_result.")
    if model is None:
        raise ValueError("Cannot export deflection CSV without mainline model.")
    main_nodes = (
        getattr(model, "nodes_main_m", None)
        if getattr(model, "nodes_main_m", None) is not None
        else getattr(model, "main_nodes_m", None)
    )
    rear_nodes = (
        getattr(model, "nodes_rear_m", None)
        if getattr(model, "nodes_rear_m", None) is not None
        else getattr(model, "rear_nodes_m", None)
    )
    if main_nodes is None or rear_nodes is None:
        raise ValueError("Model must expose main/rear node arrays.")

    disp_main = np.asarray(inverse.displacement_main_m, dtype=float)
    disp_rear = np.asarray(inverse.displacement_rear_m, dtype=float)
    production = candidate.production_result
    if production is not None:
        prod_main = np.asarray(production.disp_main_m, dtype=float)
        prod_rear = np.asarray(production.disp_rear_m, dtype=float)
        if prod_main.ndim == 2 and prod_main.shape[0] == disp_main.shape[0]:
            disp_main = prod_main
        if prod_rear.ndim == 2 and prod_rear.shape[0] == disp_rear.shape[0]:
            disp_rear = prod_rear

    y_main = np.asarray(main_nodes, dtype=float)[:, 1]
    y_rear = np.asarray(rear_nodes, dtype=float)[:, 1]
    if y_main.shape[0] != disp_main.shape[0]:
        raise ValueError("Main-node count and displacement row count do not match.")
    if y_rear.shape[0] != disp_rear.shape[0]:
        raise ValueError("Rear-node count and displacement row count do not match.")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "spar",
                "node_index",
                "y_m",
                "ux_m",
                "uy_m",
                "uz_m",
                "theta_x_rad",
                "theta_y_rad",
                "theta_z_rad",
            ]
        )
        for spar_name, y_arr, disp_arr in (
            ("main", y_main, disp_main),
            ("rear", y_rear, disp_rear),
        ):
            value_cols = min(6, int(disp_arr.shape[1])) if disp_arr.ndim == 2 else 0
            for idx in range(y_arr.shape[0]):
                row: list[str | int] = [spar_name, idx, f"{float(y_arr[idx]):.6f}"]
                for col in range(value_cols):
                    row.append(f"{float(disp_arr[idx, col]):.8e}")
                for _ in range(6 - value_cols):
                    row.append("0.0")
                writer.writerow(row)


def export_inverse_design_artifacts(
    *,
    output_dir: Path,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    export_loads: dict,
    candidate: InverseCandidate,
    active_wall_diagnostics: ActiveWallDiagnostics | None,
    step_engine: str,
    skip_step_export: bool,
) -> ArtifactBundle:
    """Write shape/deflection artifacts and optionally export jig+loaded STEP models."""

    if candidate.inverse_result is None:
        return ArtifactBundle(
            target_shape_csv=None,
            jig_shape_csv=None,
            loaded_shape_csv=None,
            deflection_csv=None,
            jig_step_path=None,
            loaded_step_path=None,
            step_engine=None,
            step_error="selected candidate has no inverse-design shape payload",
            loaded_step_error=None,
            diagnostics_json=None,
            validity_summary_json=None,
            wire_rigging_json=None,
        )

    opt_result = build_opt_result_from_candidate(candidate, cfg)
    exporter = ANSYSExporter(
        cfg,
        aircraft,
        opt_result,
        export_loads,
        materials_db,
        mode="dual_beam_production",
    )

    target_csv_path = output_dir / "target_loaded_shape_spar_data.csv"
    exporter.write_workbench_csv(target_csv_path)

    jig_csv_path = output_dir / "jig_shape_spar_data.csv"
    write_shape_csv_from_template(
        template_csv_path=target_csv_path,
        output_csv_path=jig_csv_path,
        shape=candidate.inverse_result.jig_shape,
    )
    loaded_csv_path = output_dir / "loaded_shape_spar_data.csv"
    write_shape_csv_from_template(
        template_csv_path=target_csv_path,
        output_csv_path=loaded_csv_path,
        shape=candidate.inverse_result.predicted_loaded_shape,
    )

    jig_step_path: str | None = None
    loaded_step_path: str | None = None
    resolved_engine: str | None = None
    step_error: str | None = None
    loaded_step_error: str | None = None
    if not skip_step_export:
        try:
            resolved_engine = export_step_from_csv(
                jig_csv_path,
                output_dir / "jig_shape.step",
                engine=step_engine,
            )
            jig_step_path = str((output_dir / "jig_shape.step").resolve())
        except Exception as exc:  # pragma: no cover - depends on local CAD stack
            step_error = f"{type(exc).__name__}: {exc}"
        try:
            loaded_engine = resolved_engine or step_engine
            export_step_from_csv(
                loaded_csv_path,
                output_dir / "loaded_shape.step",
                engine=loaded_engine,
            )
            loaded_step_path = str((output_dir / "loaded_shape.step").resolve())
            if resolved_engine is None:
                resolved_engine = loaded_engine
        except Exception as exc:  # pragma: no cover - depends on local CAD stack
            loaded_step_error = f"{type(exc).__name__}: {exc}"

    diagnostics_json_path = output_dir / "active_wall_diagnostics.json"
    diagnostics_json_path.write_text(
        json.dumps(
            _build_selected_diagnostics_payload(
                candidate=candidate,
                cfg=cfg,
                active_wall_diagnostics=active_wall_diagnostics,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    validity_summary_json_path = output_dir / "validity_summary.json"
    validity_summary_json_path.write_text(
        json.dumps(
            _build_validity_summary_payload(
                candidate=candidate,
                active_wall_diagnostics=active_wall_diagnostics,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    model_for_deflection = candidate.mainline_model
    if model_for_deflection is None:
        model_for_deflection = candidate.inverse_result.target_loaded_shape
    deflection_csv_path = output_dir / "node_deflections.csv"
    _write_deflection_csv(
        deflection_csv_path,
        candidate=candidate,
        model=model_for_deflection,
    )

    wire_records = _lift_wire_rigging_records(
        candidate=candidate,
        cfg=cfg,
        materials_db=materials_db,
    )
    wire_json_path = output_dir / "lift_wire_rigging.json"
    wire_json_path.write_text(
        json.dumps(
            {
                "wire_rigging": [asdict(record) for record in wire_records],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return ArtifactBundle(
        target_shape_csv=str(target_csv_path.resolve()),
        jig_shape_csv=str(jig_csv_path.resolve()),
        loaded_shape_csv=str(loaded_csv_path.resolve()),
        deflection_csv=str(deflection_csv_path.resolve()),
        jig_step_path=jig_step_path,
        loaded_step_path=loaded_step_path,
        step_engine=resolved_engine,
        step_error=step_error,
        loaded_step_error=loaded_step_error,
        diagnostics_json=str(diagnostics_json_path.resolve()),
        validity_summary_json=str(validity_summary_json_path.resolve()),
        wire_rigging_json=str(wire_json_path.resolve()),
    )


def run_inverse_design(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    optimizer: SparOptimizer,
    export_loads: dict,
    baseline_result,
    map_config: ReducedMapConfig,
    baseline_design: BaselineDesign | None = None,
    clearance_floor_z_m: float,
    target_shape_error_tol_m: float,
    max_jig_vertical_prebend_m: float | None,
    max_jig_vertical_curvature_per_m: float | None,
    loaded_shape_mode: str,
    loaded_shape_control_station_fractions: tuple[float, ...],
    loaded_shape_main_z_tol_m: float,
    loaded_shape_twist_tol_deg: float,
    loaded_shape_penalty_weight_kg: float,
    target_shape_z_scale: float,
    dihedral_exponent: float,
    clearance_risk_threshold_m: float,
    clearance_risk_top_k: int,
    clearance_penalty_weight_kg: float,
    active_wall_penalty_weight_kg: float,
    manufacturing_limit_source: str,
    main_plateau_grid: Iterable[float],
    main_taper_fill_grid: Iterable[float],
    rear_radius_grid: Iterable[float],
    rear_outboard_grid: Iterable[float],
    wall_thickness_grid: Iterable[float],
    cobyla_maxiter: int,
    cobyla_rhobeg: float,
    skip_local_refine: bool,
    target_mass_kg: float | None,
    local_refine_feasible_seeds: int,
    local_refine_near_feasible_seeds: int,
    local_refine_max_starts: int,
    local_refine_early_stop_patience: int,
    local_refine_early_stop_abs_improvement_kg: float,
    rib_zonewise_mode: str = RIB_ZONEWISE_LIMITED_MODE,
    rib_family_switch_penalty_kg: float = DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG,
    rib_family_mix_max_unique: int = DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE,
) -> InverseOutcome:
    if baseline_design is None:
        baseline_design = _baseline_design_from_result(baseline_result)
    evaluator = InverseDesignEvaluator(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=export_loads,
        baseline=baseline_design,
        map_config=map_config,
        clearance_floor_z_m=clearance_floor_z_m,
        target_shape_error_tol_m=target_shape_error_tol_m,
        max_jig_vertical_prebend_m=max_jig_vertical_prebend_m,
        max_jig_vertical_curvature_per_m=max_jig_vertical_curvature_per_m,
        loaded_shape_mode=loaded_shape_mode,
        loaded_shape_control_station_fractions=loaded_shape_control_station_fractions,
        loaded_shape_main_z_tol_m=loaded_shape_main_z_tol_m,
        loaded_shape_twist_tol_deg=loaded_shape_twist_tol_deg,
        loaded_shape_penalty_weight_kg=loaded_shape_penalty_weight_kg,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=dihedral_exponent,
        clearance_risk_threshold_m=clearance_risk_threshold_m,
        clearance_risk_top_k=clearance_risk_top_k,
        clearance_penalty_weight_kg=clearance_penalty_weight_kg,
        active_wall_penalty_weight_kg=active_wall_penalty_weight_kg,
        target_mass_kg=target_mass_kg,
        rib_zonewise_mode=rib_zonewise_mode,
        rib_family_switch_penalty_kg=rib_family_switch_penalty_kg,
        rib_family_mix_max_unique=rib_family_mix_max_unique,
    )

    total_start = perf_counter()
    baseline = evaluator.evaluate(
        np.zeros(5, dtype=float),
        source="baseline",
        rib_design_key=evaluator.default_rib_design_key,
    )

    coarse_grid = list(
        product(
            main_plateau_grid,
            main_taper_fill_grid,
            rear_radius_grid,
            rear_outboard_grid,
            wall_thickness_grid,
        )
    )
    for point in coarse_grid:
        for rib_design in evaluator.rib_design_profiles:
            evaluator.evaluate(
                np.asarray(point, dtype=float),
                source="coarse_grid",
                rib_design_key=rib_design.design_key,
            )

    coarse_selected = evaluator.archive.selected or baseline
    coarse_candidate_count = len(evaluator.archive.candidates)
    coarse_feasible_count = evaluator.archive.feasible_count
    coarse_target_feasible_count = evaluator.archive.target_feasible_count

    lb = np.zeros(5, dtype=float)
    ub = np.ones(5, dtype=float)
    local_refine: LocalRefineSummary | None = None
    total_nfev = 0
    total_nit = 0

    if not skip_local_refine:
        constraints = build_constraint_functions(evaluator=evaluator, lb=lb, ub=ub)
        start_candidates = evaluator.archive.local_refine_starts(
            feasible_limit=int(local_refine_feasible_seeds),
            near_feasible_limit=int(local_refine_near_feasible_seeds),
            max_starts=int(local_refine_max_starts),
            baseline=baseline,
        )
        attempts: list[tuple[LocalRefineAttempt, InverseCandidate, InverseCandidate]] = []
        best_eligible_mass_kg = float("inf")
        stagnation_count = 0
        early_stop_triggered = False
        early_stop_reason: str | None = None

        for seed_index, start_candidate in enumerate(start_candidates):
            objective_calls = {"n": 0}
            objective_source = f"local_objective_seed{seed_index}"
            final_source = f"local_final_seed{seed_index}"
            rib_design_key = (
                evaluator.default_rib_design_key
                if start_candidate.rib_design is None
                else start_candidate.rib_design.design_key
            )

            def _objective(z: np.ndarray, *, source_name: str = objective_source) -> float:
                objective_calls["n"] += 1
                cand = evaluator.evaluate(z, source=source_name, rib_design_key=rib_design_key)
                return float(cand.objective_value_kg)

            opt = minimize(
                _objective,
                np.asarray(start_candidate.z, dtype=float),
                method="COBYLA",
                constraints=constraints,
                options={
                    "maxiter": int(cobyla_maxiter),
                    "rhobeg": float(cobyla_rhobeg),
                    "tol": 1.0e-6,
                    "catol": 1.0e-6,
                },
            )
            end_candidate = evaluator.evaluate(
                np.asarray(opt.x, dtype=float),
                source=final_source,
                rib_design_key=rib_design_key,
            )
            nfev = int(getattr(opt, "nfev", objective_calls["n"]))
            nit = int(getattr(opt, "nit", 0) or 0)
            total_nfev += nfev
            total_nit += nit
            attempts.append(
                (
                    LocalRefineAttempt(
                        seed_source=start_candidate.source,
                        seed_mass_kg=float(start_candidate.total_structural_mass_kg),
                        seed_overall_feasible=bool(start_candidate.overall_feasible),
                        seed_hard_violation_score=float(start_candidate.hard_violation_score),
                        end_source=end_candidate.source,
                        end_mass_kg=float(end_candidate.total_structural_mass_kg),
                        end_overall_feasible=bool(end_candidate.overall_feasible),
                        success=bool(getattr(opt, "success", False)),
                        message=str(getattr(opt, "message", "")),
                        nfev=nfev,
                        nit=nit,
                    ),
                    start_candidate,
                    end_candidate,
                )
            )
            eligible = (
                bool(end_candidate.overall_target_feasible)
                if target_mass_kg is not None
                else bool(end_candidate.overall_feasible)
            )
            if eligible:
                improvement_kg = best_eligible_mass_kg - float(end_candidate.total_structural_mass_kg)
                if improvement_kg > float(local_refine_early_stop_abs_improvement_kg):
                    best_eligible_mass_kg = float(end_candidate.total_structural_mass_kg)
                    stagnation_count = 0
                else:
                    if np.isfinite(best_eligible_mass_kg):
                        stagnation_count += 1
                if (
                    np.isfinite(best_eligible_mass_kg)
                    and int(local_refine_early_stop_patience) > 0
                    and stagnation_count >= int(local_refine_early_stop_patience)
                ):
                    early_stop_triggered = True
                    early_stop_reason = (
                        "local_refine_stagnated_after_feasible_hit"
                        if target_mass_kg is None
                        else "target_mass_feasible_stagnated"
                    )
                    break

        if attempts:
            best_attempt, best_start_candidate, best_end_candidate = min(
                attempts,
                key=lambda item: (
                    _feasible_key(item[2])
                    if item[2].overall_feasible
                    else _violation_key(item[2])
                ),
            )
            local_refine = LocalRefineSummary(
                coarse_selected_source=coarse_selected.source,
                coarse_selected_mass_kg=float(coarse_selected.total_structural_mass_kg),
                coarse_candidate_count=int(coarse_candidate_count),
                coarse_feasible_count=int(coarse_feasible_count),
                coarse_target_feasible_count=int(coarse_target_feasible_count),
                seed_count=len(start_candidates),
                start_source=best_start_candidate.source,
                start_mass_kg=float(best_start_candidate.total_structural_mass_kg),
                end_mass_kg=float(best_end_candidate.total_structural_mass_kg),
                success=best_attempt.success,
                message=best_attempt.message,
                nfev=int(total_nfev),
                nit=int(total_nit),
                early_stop_triggered=bool(early_stop_triggered),
                early_stop_reason=early_stop_reason,
                attempts=tuple(attempt for attempt, _, _ in attempts),
            )

    selected = evaluator.archive.selected or baseline
    active_wall_diagnostics = _active_wall_diagnostics_for_candidate(
        candidate=selected,
        cfg=cfg,
        lighten_probes=_build_lighten_probe_diagnostics(
            evaluator=evaluator,
            selected=selected,
        ),
    )
    total_wall_time_s = float(perf_counter() - total_start)
    return InverseOutcome(
        success=bool(selected.overall_target_feasible if target_mass_kg is not None else selected.overall_feasible),
        feasible=bool(selected.overall_target_feasible if target_mass_kg is not None else selected.overall_feasible),
        target_mass_kg=None if target_mass_kg is None else float(target_mass_kg),
        message=selected.message,
        total_wall_time_s=total_wall_time_s,
        baseline_eval_wall_time_s=float(baseline.eval_wall_time_s),
        nfev=total_nfev,
        nit=total_nit,
        equivalent_analysis_calls=int(evaluator.equivalent_analysis_calls),
        production_analysis_calls=int(evaluator.production_analysis_calls),
        unique_evaluations=int(evaluator.unique_evaluations),
        cache_hits=int(evaluator.cache_hits),
        feasible_count=int(evaluator.archive.feasible_count),
        target_feasible_count=int(evaluator.archive.target_feasible_count),
        baseline=baseline,
        best_overall_feasible=evaluator.archive.best_feasible,
        best_target_feasible=evaluator.archive.best_target_feasible,
        coarse_selected=coarse_selected,
        coarse_candidate_count=int(coarse_candidate_count),
        coarse_feasible_count=int(coarse_feasible_count),
        coarse_target_feasible_count=int(coarse_target_feasible_count),
        selected=selected,
        local_refine=local_refine,
        active_wall_diagnostics=active_wall_diagnostics,
        manufacturing_limit_source=manufacturing_limit_source,
        max_jig_vertical_prebend_limit_m=max_jig_vertical_prebend_m,
        max_jig_vertical_curvature_limit_per_m=max_jig_vertical_curvature_per_m,
        artifacts=None,
    )


def run_inverse_design_load_refresh_refinement(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    optimizer: SparOptimizer,
    baseline_result,
    map_config: ReducedMapConfig,
    clearance_floor_z_m: float,
    target_shape_error_tol_m: float,
    max_jig_vertical_prebend_m: float | None,
    max_jig_vertical_curvature_per_m: float | None,
    loaded_shape_mode: str,
    loaded_shape_control_station_fractions: tuple[float, ...],
    loaded_shape_main_z_tol_m: float,
    loaded_shape_twist_tol_deg: float,
    loaded_shape_penalty_weight_kg: float,
    target_shape_z_scale: float,
    dihedral_exponent: float,
    clearance_risk_threshold_m: float,
    clearance_risk_top_k: int,
    clearance_penalty_weight_kg: float,
    active_wall_penalty_weight_kg: float,
    manufacturing_limit_source: str,
    main_plateau_grid: Iterable[float],
    main_taper_fill_grid: Iterable[float],
    rear_radius_grid: Iterable[float],
    rear_outboard_grid: Iterable[float],
    wall_thickness_grid: Iterable[float],
    cobyla_maxiter: int,
    cobyla_rhobeg: float,
    skip_local_refine: bool,
    target_mass_kg: float | None,
    local_refine_feasible_seeds: int,
    local_refine_near_feasible_seeds: int,
    local_refine_max_starts: int,
    local_refine_early_stop_patience: int,
    local_refine_early_stop_abs_improvement_kg: float,
    initial_mapped_loads: dict,
    refresh_model: LightweightLoadRefreshModel,
    aero_contract: CandidateAeroContract,
    refresh_steps: int,
    dynamic_design_space: bool = False,
    refresh_until_converged: bool = False,
    refresh_max_steps: int | None = None,
    refresh_convergence_mass_tol_kg: float = 0.05,
    refresh_convergence_lift_rms_tol_npm: float = 1.0,
    refresh_convergence_torque_rms_tol_nmpm: float = 0.5,
    rib_zonewise_mode: str = RIB_ZONEWISE_LIMITED_MODE,
    rib_family_switch_penalty_kg: float = DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG,
    rib_family_mix_max_unique: int = DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE,
) -> RefreshRefinementOutcome:
    design_case = cfg.structural_load_cases()[0]
    refresh_steps = int(refresh_steps)
    iterations: list[RefreshIterationResult] = []
    dynamic_design_space = bool(dynamic_design_space)
    refresh_until_converged = bool(refresh_until_converged)
    dynamic_rebuilds = 0
    converged = False
    convergence_reason: str | None = None
    current_baseline_design = _baseline_design_from_result(baseline_result)
    current_map_config = map_config
    requested_steps = refresh_steps
    if refresh_until_converged:
        requested_steps = max(1, int(refresh_max_steps or max(refresh_steps, 1)))

    optimizer.update_aero_loads(initial_mapped_loads)
    initial_export_loads = LoadMapper.apply_load_factor(initial_mapped_loads, design_case.aero_scale)
    frozen_outcome = run_inverse_design(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=initial_export_loads,
        baseline_result=baseline_result,
        map_config=current_map_config,
        baseline_design=current_baseline_design,
        clearance_floor_z_m=clearance_floor_z_m,
        target_shape_error_tol_m=target_shape_error_tol_m,
        max_jig_vertical_prebend_m=max_jig_vertical_prebend_m,
        max_jig_vertical_curvature_per_m=max_jig_vertical_curvature_per_m,
        loaded_shape_mode=loaded_shape_mode,
        loaded_shape_control_station_fractions=loaded_shape_control_station_fractions,
        loaded_shape_main_z_tol_m=loaded_shape_main_z_tol_m,
        loaded_shape_twist_tol_deg=loaded_shape_twist_tol_deg,
        loaded_shape_penalty_weight_kg=loaded_shape_penalty_weight_kg,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=dihedral_exponent,
        clearance_risk_threshold_m=clearance_risk_threshold_m,
        clearance_risk_top_k=clearance_risk_top_k,
        clearance_penalty_weight_kg=clearance_penalty_weight_kg,
        active_wall_penalty_weight_kg=active_wall_penalty_weight_kg,
        manufacturing_limit_source=manufacturing_limit_source,
        main_plateau_grid=main_plateau_grid,
        main_taper_fill_grid=main_taper_fill_grid,
        rear_radius_grid=rear_radius_grid,
        rear_outboard_grid=rear_outboard_grid,
        wall_thickness_grid=wall_thickness_grid,
        cobyla_maxiter=cobyla_maxiter,
        cobyla_rhobeg=cobyla_rhobeg,
        skip_local_refine=skip_local_refine,
        target_mass_kg=target_mass_kg,
        local_refine_feasible_seeds=local_refine_feasible_seeds,
        local_refine_near_feasible_seeds=local_refine_near_feasible_seeds,
        local_refine_max_starts=local_refine_max_starts,
        local_refine_early_stop_patience=local_refine_early_stop_patience,
        local_refine_early_stop_abs_improvement_kg=local_refine_early_stop_abs_improvement_kg,
        rib_zonewise_mode=rib_zonewise_mode,
        rib_family_switch_penalty_kg=rib_family_switch_penalty_kg,
        rib_family_mix_max_unique=rib_family_mix_max_unique,
    )
    iterations.append(
        _build_refresh_iteration_result(
            iteration_index=0,
            load_source=(
                f"{aero_contract.source_mode}:"
                f"{aero_contract.baseline_load_source}:"
                f"aoa_{float(refresh_model._baseline_case.aoa_deg):.3f}deg"
            ),
            outcome=frozen_outcome,
            mapped_loads=initial_mapped_loads,
            load_metrics=refresh_model.baseline_metrics(initial_mapped_loads),
            map_config=current_map_config,
            dynamic_design_space_applied=False,
            previous=None,
            forward_check=None,
        )
    )

    for step in range(1, requested_steps + 1):
        previous_iteration = iterations[-1]
        previous_selected = previous_iteration.outcome.selected
        if previous_selected.equivalent_result is None:
            convergence_reason = "selected_candidate_missing_equivalent_result"
            break

        refreshed_mapped_loads, refreshed_metrics = refresh_model.refresh_mapped_loads(
            equivalent_result=previous_selected.equivalent_result,
        )
        optimizer.update_aero_loads(refreshed_mapped_loads)
        refreshed_export_loads = LoadMapper.apply_load_factor(
            refreshed_mapped_loads,
            design_case.aero_scale,
        )
        forward_check = _run_forward_refresh_check(
            cfg=cfg,
            aircraft=aircraft,
            materials_db=materials_db,
            optimizer=optimizer,
            export_loads=refreshed_export_loads,
            candidate=previous_selected,
            previous_iteration_index=previous_iteration.iteration_index,
        )
        map_rebuilt = False
        if dynamic_design_space and previous_selected.overall_feasible:
            current_baseline_design, current_map_config = _rebuild_dynamic_map_config(
                selected_candidate=previous_selected,
                cfg=cfg,
                previous_map_config=current_map_config,
            )
            dynamic_rebuilds += 1
            map_rebuilt = True
        refreshed_outcome = run_inverse_design(
            cfg=cfg,
            aircraft=aircraft,
            materials_db=materials_db,
            optimizer=optimizer,
            export_loads=refreshed_export_loads,
            baseline_result=baseline_result,
            map_config=current_map_config,
            baseline_design=current_baseline_design,
            clearance_floor_z_m=clearance_floor_z_m,
            target_shape_error_tol_m=target_shape_error_tol_m,
            max_jig_vertical_prebend_m=max_jig_vertical_prebend_m,
            max_jig_vertical_curvature_per_m=max_jig_vertical_curvature_per_m,
            loaded_shape_mode=loaded_shape_mode,
            loaded_shape_control_station_fractions=loaded_shape_control_station_fractions,
            loaded_shape_main_z_tol_m=loaded_shape_main_z_tol_m,
            loaded_shape_twist_tol_deg=loaded_shape_twist_tol_deg,
            loaded_shape_penalty_weight_kg=loaded_shape_penalty_weight_kg,
            target_shape_z_scale=target_shape_z_scale,
            dihedral_exponent=dihedral_exponent,
            clearance_risk_threshold_m=clearance_risk_threshold_m,
            clearance_risk_top_k=clearance_risk_top_k,
            clearance_penalty_weight_kg=clearance_penalty_weight_kg,
            active_wall_penalty_weight_kg=active_wall_penalty_weight_kg,
            manufacturing_limit_source=manufacturing_limit_source,
            main_plateau_grid=main_plateau_grid,
            main_taper_fill_grid=main_taper_fill_grid,
            rear_radius_grid=rear_radius_grid,
            rear_outboard_grid=rear_outboard_grid,
            wall_thickness_grid=wall_thickness_grid,
            cobyla_maxiter=cobyla_maxiter,
            cobyla_rhobeg=cobyla_rhobeg,
            skip_local_refine=skip_local_refine,
            target_mass_kg=target_mass_kg,
            local_refine_feasible_seeds=local_refine_feasible_seeds,
            local_refine_near_feasible_seeds=local_refine_near_feasible_seeds,
            local_refine_max_starts=local_refine_max_starts,
            local_refine_early_stop_patience=local_refine_early_stop_patience,
            local_refine_early_stop_abs_improvement_kg=local_refine_early_stop_abs_improvement_kg,
            rib_zonewise_mode=rib_zonewise_mode,
            rib_family_switch_penalty_kg=rib_family_switch_penalty_kg,
            rib_family_mix_max_unique=rib_family_mix_max_unique,
        )
        iteration_result = _build_refresh_iteration_result(
            iteration_index=step,
            load_source=(
                f"{aero_contract.source_mode}:"
                f"{aero_contract.refresh_load_source}:"
                f"step_{step}_from_iteration_{previous_iteration.iteration_index}"
            ),
            outcome=refreshed_outcome,
            mapped_loads=refreshed_mapped_loads,
            load_metrics=refreshed_metrics,
            map_config=current_map_config,
            dynamic_design_space_applied=map_rebuilt,
            previous=previous_iteration,
            forward_check=forward_check,
        )
        iterations.append(iteration_result)
        if refresh_until_converged and _refresh_iteration_converged(
            iteration_result,
            mass_tol_kg=float(refresh_convergence_mass_tol_kg),
            lift_rms_tol_npm=float(refresh_convergence_lift_rms_tol_npm),
            torque_rms_tol_nmpm=float(refresh_convergence_torque_rms_tol_nmpm),
        ):
            converged = True
            convergence_reason = "load_and_mass_delta_below_tolerance"
            break

    return RefreshRefinementOutcome(
        refresh_steps_requested=requested_steps,
        refresh_steps_completed=max(0, len(iterations) - 1),
        dynamic_design_space_enabled=dynamic_design_space,
        dynamic_design_space_rebuilds=int(dynamic_rebuilds),
        converged=bool(converged),
        convergence_reason=convergence_reason,
        manufacturing_limit_source=manufacturing_limit_source,
        max_jig_vertical_prebend_limit_m=max_jig_vertical_prebend_m,
        max_jig_vertical_curvature_limit_per_m=max_jig_vertical_curvature_per_m,
        iterations=tuple(iterations),
        artifacts=None,
        aero_contract=aero_contract,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the inverse-design lightweight load-refresh refinement on the reduced direct dual-beam V2 map."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
        help="Path to YAML configuration file.",
    )
    parser.add_argument(
        "--design-report",
        default=str(
            Path(__file__).resolve().parent.parent
            / "output"
            / "blackcat_004_dual_beam_production_check"
            / "ansys"
            / "crossval_report.txt"
        ),
        help="Production baseline report used as the initial specimen.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(
            Path(__file__).resolve().parent.parent
            / "output"
            / "direct_dual_beam_inverse_design_refresh"
        ),
        help="Directory for the inverse-design report, summary, and shape artifacts.",
    )
    parser.add_argument("--main-plateau-scale-upper", type=float, default=1.14)
    parser.add_argument("--main-taper-fill-upper", type=float, default=0.80)
    parser.add_argument("--rear-radius-scale-upper", type=float, default=1.12)
    parser.add_argument("--main-plateau-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--main-taper-fill-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--rear-radius-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--rear-outboard-grid", default="0.0,0.5,1.0")
    parser.add_argument("--wall-thickness-grid", default="0.0,0.35,0.70")
    parser.add_argument("--cobyla-maxiter", type=int, default=160)
    parser.add_argument("--cobyla-rhobeg", type=float, default=0.18)
    parser.add_argument("--skip-local-refine", action="store_true")
    parser.add_argument(
        "--loaded-shape-mode",
        default="exact_nodal",
        choices=("exact_nodal", "low_dim_descriptor"),
        help="How the inverse jig backout enforces the loaded-shape target.",
    )
    parser.add_argument(
        "--loaded-shape-control-stations",
        default="0.0,0.5,1.0",
        help="Span fractions used by the low-dimensional loaded-shape matching descriptors.",
    )
    parser.add_argument(
        "--loaded-shape-z-tol",
        type=float,
        default=None,
        help=(
            "Override for maximum allowed main-beam loaded-shape error at control stations [m]. "
            "Default comes from config solver.loaded_shape_z_tol_m."
        ),
    )
    parser.add_argument(
        "--loaded-shape-twist-tol",
        type=float,
        default=None,
        help=(
            "Override for maximum allowed twist error at control stations [deg]. "
            "Default comes from config solver.loaded_shape_twist_tol_deg."
        ),
    )
    parser.add_argument(
        "--loaded-shape-main-z-tol-mm",
        type=float,
        default=None,
        help=(
            "Legacy alias for --loaded-shape-z-tol (millimeters). "
            "When omitted, uses config solver.loaded_shape_z_tol_m."
        ),
    )
    parser.add_argument(
        "--loaded-shape-twist-tol-deg",
        type=float,
        default=None,
        help=(
            "Legacy alias for --loaded-shape-twist-tol (degrees). "
            "When omitted, uses config solver.loaded_shape_twist_tol_deg."
        ),
    )
    parser.add_argument(
        "--loaded-shape-penalty-kg",
        type=float,
        default=0.05,
        help="Small objective penalty weight on normalized loaded-shape RMS error; mass remains the primary objective.",
    )
    parser.add_argument(
        "--target-shape-z-scale",
        type=float,
        default=1.0,
        help="Scale factor applied to the target loaded-shape Z coordinates before inverse jig backout.",
    )
    parser.add_argument(
        "--dihedral-exponent",
        type=float,
        default=1.0,
        help=(
            "Progressive dihedral scaling exponent for target-shape Z scaling "
            "(0=uniform, 1=linear root-to-tip ramp)."
        ),
    )
    parser.add_argument(
        "--aero-source-mode",
        default=LEGACY_AERO_SOURCE_MODE,
        choices=(LEGACY_AERO_SOURCE_MODE, CANDIDATE_RERUN_AERO_SOURCE_MODE),
        help=(
            "Choose whether outer-loop aero loads come from the shared legacy VSPAero sweep "
            "or a candidate-owned OpenVSP geometry rebuild plus VSPAero rerun."
        ),
    )
    parser.add_argument(
        "--candidate-aero-output-dir",
        default=None,
        help=(
            "Optional directory for candidate-owned geometry / VSPAero rerun artifacts when "
            "--aero-source-mode=candidate_rerun_vspaero. Defaults to <output-dir>/candidate_aero."
        ),
    )
    parser.add_argument(
        "--clearance-risk-threshold-mm",
        type=float,
        default=10.0,
        help="Clearance threshold used by the top-hotspot clearance risk metric.",
    )
    parser.add_argument(
        "--clearance-risk-top-k",
        type=int,
        default=5,
        help="Number of most critical jig nodes included in the clearance risk metric.",
    )
    parser.add_argument(
        "--clearance-penalty-kg",
        type=float,
        default=0.25,
        help="Small objective penalty weight on the clearance risk score.",
    )
    parser.add_argument(
        "--active-wall-penalty-kg",
        type=float,
        default=0.05,
        help="Small objective penalty weight on active geometry/discrete wall risk.",
    )
    parser.add_argument(
        "--rib-zonewise-mode",
        default=RIB_ZONEWISE_LIMITED_MODE,
        choices=(RIB_ZONEWISE_OFF_MODE, RIB_ZONEWISE_LIMITED_MODE),
        help=(
            "Whether rib design stays on the legacy single-contract baseline or uses a small "
            "zone-wise profile library inside the structural candidate contract."
        ),
    )
    parser.add_argument(
        "--rib-family-switch-penalty-kg",
        type=float,
        default=DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG,
        help="Small penalty added for each adjacent zone-to-zone rib-family switch in mix mode.",
    )
    parser.add_argument(
        "--rib-family-mix-max-unique",
        type=int,
        default=DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE,
        help="Maximum number of unique rib families allowed in one limited zone-wise candidate.",
    )
    parser.add_argument(
        "--target-mass-kg",
        type=float,
        default=None,
        help="Optional feasibility mass cap; when set, search prioritizes candidates that satisfy all constraints and total mass <= target.",
    )
    parser.add_argument(
        "--local-refine-feasible-seeds",
        type=int,
        default=1,
        help="Number of best feasible coarse candidates to use as local-refine starts per stage.",
    )
    parser.add_argument(
        "--local-refine-near-feasible-seeds",
        type=int,
        default=2,
        help="Number of low-violation coarse candidates to use as additional local-refine starts per stage.",
    )
    parser.add_argument(
        "--local-refine-max-starts",
        type=int,
        default=4,
        help="Maximum number of local-refine starts to run per stage after seed ranking and deduplication.",
    )
    parser.add_argument(
        "--local-refine-early-stop-patience",
        type=int,
        default=2,
        help="Stop local-refine restarts after this many feasible starts fail to improve the best mass by the configured tolerance.",
    )
    parser.add_argument(
        "--local-refine-early-stop-abs-improvement-kg",
        type=float,
        default=0.05,
        help="Absolute mass improvement threshold that resets local-refine stagnation counting.",
    )
    parser.add_argument("--clearance-floor-z-m", type=float, default=0.0)
    parser.add_argument("--target-shape-error-tol-m", type=float, default=1.0e-9)
    parser.add_argument("--max-jig-vertical-prebend-m", type=float, default=None)
    parser.add_argument("--max-jig-vertical-curvature-per-m", type=float, default=None)
    parser.add_argument(
        "--manufacturing-limit-scale",
        type=float,
        default=1.10,
        help="If an explicit manufacturing limit is omitted, scale the baseline inverse metric by this factor.",
    )
    parser.add_argument(
        "--refresh-steps",
        type=int,
        default=2,
        choices=(0, 1, 2),
        help="Number of lightweight outer load-refresh updates to run after the frozen-load stage.",
    )
    parser.add_argument(
        "--refresh-until-converged",
        action="store_true",
        help="Continue outer refresh updates until load/mass deltas fall below the configured tolerances.",
    )
    parser.add_argument(
        "--refresh-max-steps",
        type=int,
        default=5,
        help="Maximum outer refresh steps when --refresh-until-converged is enabled.",
    )
    parser.add_argument(
        "--refresh-convergence-mass-tol-kg",
        type=float,
        default=0.05,
        help="Mass-delta convergence threshold for --refresh-until-converged.",
    )
    parser.add_argument(
        "--refresh-convergence-lift-rms-tol-npm",
        type=float,
        default=1.0,
        help="Lift RMS delta threshold [N/m] for --refresh-until-converged.",
    )
    parser.add_argument(
        "--refresh-convergence-torque-rms-tol-nmpm",
        type=float,
        default=0.5,
        help="Torque RMS delta threshold [N*m/m] for --refresh-until-converged.",
    )
    parser.add_argument(
        "--refresh-washout-scale",
        type=float,
        default=1.0,
        help="Scale factor that converts structural twist into local effective-AoA reduction during refresh.",
    )
    parser.add_argument(
        "--dynamic-design-space",
        action="store_true",
        help="Rebuild the reduced V2 search map after each feasible refresh iteration.",
    )
    parser.add_argument("--step-engine", default="auto", choices=("auto", "cadquery", "build123d"))
    parser.add_argument("--skip-step-export", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    design_report = Path(args.design_report).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(config_path)
    specimen_metrics = parse_baseline_metrics(design_report)
    cfg.solver.n_beam_nodes = int(specimen_metrics.nodes_per_spar)
    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    baseline_result = build_specimen_result_from_crossval_report(design_report)
    loaded_shape_control_station_fractions = _parse_control_fractions(args.loaded_shape_control_stations)
    loaded_shape_main_z_tol_m = float(cfg.solver.loaded_shape_z_tol_m)
    if args.loaded_shape_main_z_tol_mm is not None:
        loaded_shape_main_z_tol_m = float(args.loaded_shape_main_z_tol_mm) * 1.0e-3
    if args.loaded_shape_z_tol is not None:
        loaded_shape_main_z_tol_m = float(args.loaded_shape_z_tol)
    loaded_shape_twist_tol_deg = float(cfg.solver.loaded_shape_twist_tol_deg)
    if args.loaded_shape_twist_tol_deg is not None:
        loaded_shape_twist_tol_deg = float(args.loaded_shape_twist_tol_deg)
    if args.loaded_shape_twist_tol is not None:
        loaded_shape_twist_tol_deg = float(args.loaded_shape_twist_tol)
    loaded_shape_penalty_weight_kg = float(args.loaded_shape_penalty_kg)
    target_shape_z_scale = float(args.target_shape_z_scale)
    dihedral_exponent = float(args.dihedral_exponent)
    if dihedral_exponent < 0.0:
        raise ValueError("--dihedral-exponent must be >= 0.0.")
    clearance_risk_threshold_m = float(args.clearance_risk_threshold_mm) * 1.0e-3
    clearance_risk_top_k = int(args.clearance_risk_top_k)
    clearance_penalty_weight_kg = float(args.clearance_penalty_kg)
    active_wall_penalty_weight_kg = float(args.active_wall_penalty_kg)
    rib_zonewise_mode = str(args.rib_zonewise_mode)
    rib_family_switch_penalty_kg = float(args.rib_family_switch_penalty_kg)
    rib_family_mix_max_unique = int(args.rib_family_mix_max_unique)
    aero_source_mode = str(args.aero_source_mode)
    candidate_aero_output_dir = (
        None
        if args.candidate_aero_output_dir is None
        else Path(args.candidate_aero_output_dir).expanduser().resolve()
    )

    legacy_aero_cases: list[SpanwiseLoad] | None = None
    if aero_source_mode == LEGACY_AERO_SOURCE_MODE and cfg.io.vsp_lod is not None:
        legacy_aero_cases = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar).parse()
    elif cfg.io.vsp_lod is not None and Path(cfg.io.vsp_lod).expanduser().is_file():
        legacy_aero_cases = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar).parse()

    aero_cases, cruise_case, mapped_loads, aero_contract = _resolve_outer_loop_candidate_aero(
        cfg=cfg,
        aircraft=aircraft,
        output_dir=output_dir,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=dihedral_exponent,
        aero_source_mode=aero_source_mode,
        legacy_aero_cases=legacy_aero_cases,
        candidate_aero_output_dir=candidate_aero_output_dir,
    )
    cruise_aoa_deg = float(cruise_case.aoa_deg)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)
    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, materials_db)
    refresh_model = LightweightLoadRefreshModel(
        aero_cases=aero_cases,
        baseline_case=cruise_case,
        cfg=cfg,
        aircraft=aircraft,
        washout_scale=float(args.refresh_washout_scale),
    )

    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
    map_config = build_reduced_map_config(
        baseline=baseline_design,
        cfg=cfg,
        main_plateau_scale_upper=float(args.main_plateau_scale_upper),
        main_taper_fill_upper=float(args.main_taper_fill_upper),
        rear_radius_scale_upper=float(args.rear_radius_scale_upper),
    )

    manufacturing_limit_source = "explicit"
    max_jig_vertical_prebend_m = args.max_jig_vertical_prebend_m
    max_jig_vertical_curvature_per_m = args.max_jig_vertical_curvature_per_m
    if max_jig_vertical_prebend_m is None or max_jig_vertical_curvature_per_m is None:
        seed_evaluator = InverseDesignEvaluator(
            cfg=cfg,
            aircraft=aircraft,
            materials_db=materials_db,
            optimizer=optimizer,
            export_loads=export_loads,
            baseline=baseline_design,
            map_config=map_config,
            clearance_floor_z_m=float(args.clearance_floor_z_m),
            target_shape_error_tol_m=float(args.target_shape_error_tol_m),
            max_jig_vertical_prebend_m=(
                float(max_jig_vertical_prebend_m)
                if max_jig_vertical_prebend_m is not None
                else 1.0e6
            ),
            max_jig_vertical_curvature_per_m=(
                float(max_jig_vertical_curvature_per_m)
                if max_jig_vertical_curvature_per_m is not None
                else 1.0e6
            ),
            loaded_shape_mode=str(args.loaded_shape_mode),
            loaded_shape_control_station_fractions=loaded_shape_control_station_fractions,
            loaded_shape_main_z_tol_m=loaded_shape_main_z_tol_m,
            loaded_shape_twist_tol_deg=loaded_shape_twist_tol_deg,
            loaded_shape_penalty_weight_kg=loaded_shape_penalty_weight_kg,
            target_shape_z_scale=target_shape_z_scale,
            dihedral_exponent=dihedral_exponent,
            clearance_risk_threshold_m=clearance_risk_threshold_m,
            clearance_risk_top_k=clearance_risk_top_k,
            clearance_penalty_weight_kg=clearance_penalty_weight_kg,
            active_wall_penalty_weight_kg=active_wall_penalty_weight_kg,
        )
        baseline_seed = seed_evaluator.evaluate(np.zeros(5, dtype=float), source="baseline_seed")
        if max_jig_vertical_prebend_m is None:
            max_jig_vertical_prebend_m = max(
                float(baseline_seed.max_jig_vertical_prebend_m) * float(args.manufacturing_limit_scale),
                1.0e-9,
            )
        if max_jig_vertical_curvature_per_m is None:
            max_jig_vertical_curvature_per_m = max(
                float(baseline_seed.max_jig_vertical_curvature_per_m) * float(args.manufacturing_limit_scale),
                1.0e-9,
            )
        manufacturing_limit_source = f"baseline_seed x {float(args.manufacturing_limit_scale):.3f}"

    refinement = run_inverse_design_load_refresh_refinement(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        baseline_result=baseline_result,
        map_config=map_config,
        clearance_floor_z_m=float(args.clearance_floor_z_m),
        target_shape_error_tol_m=float(args.target_shape_error_tol_m),
        max_jig_vertical_prebend_m=max_jig_vertical_prebend_m,
        max_jig_vertical_curvature_per_m=max_jig_vertical_curvature_per_m,
        loaded_shape_mode=str(args.loaded_shape_mode),
        loaded_shape_control_station_fractions=loaded_shape_control_station_fractions,
        loaded_shape_main_z_tol_m=loaded_shape_main_z_tol_m,
        loaded_shape_twist_tol_deg=loaded_shape_twist_tol_deg,
        loaded_shape_penalty_weight_kg=loaded_shape_penalty_weight_kg,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=dihedral_exponent,
        clearance_risk_threshold_m=clearance_risk_threshold_m,
        clearance_risk_top_k=clearance_risk_top_k,
        clearance_penalty_weight_kg=clearance_penalty_weight_kg,
        active_wall_penalty_weight_kg=active_wall_penalty_weight_kg,
        manufacturing_limit_source=manufacturing_limit_source,
        main_plateau_grid=_parse_grid(args.main_plateau_grid),
        main_taper_fill_grid=_parse_grid(args.main_taper_fill_grid),
        rear_radius_grid=_parse_grid(args.rear_radius_grid),
        rear_outboard_grid=_parse_grid(args.rear_outboard_grid),
        wall_thickness_grid=_parse_grid(args.wall_thickness_grid),
        cobyla_maxiter=int(args.cobyla_maxiter),
        cobyla_rhobeg=float(args.cobyla_rhobeg),
        skip_local_refine=bool(args.skip_local_refine),
        target_mass_kg=None if args.target_mass_kg is None else float(args.target_mass_kg),
        local_refine_feasible_seeds=int(args.local_refine_feasible_seeds),
        local_refine_near_feasible_seeds=int(args.local_refine_near_feasible_seeds),
        local_refine_max_starts=int(args.local_refine_max_starts),
        local_refine_early_stop_patience=int(args.local_refine_early_stop_patience),
        local_refine_early_stop_abs_improvement_kg=float(args.local_refine_early_stop_abs_improvement_kg),
        initial_mapped_loads=mapped_loads,
        refresh_model=refresh_model,
        aero_contract=aero_contract,
        refresh_steps=int(args.refresh_steps),
        dynamic_design_space=bool(args.dynamic_design_space),
        refresh_until_converged=bool(args.refresh_until_converged),
        refresh_max_steps=int(args.refresh_max_steps),
        refresh_convergence_mass_tol_kg=float(args.refresh_convergence_mass_tol_kg),
        refresh_convergence_lift_rms_tol_npm=float(args.refresh_convergence_lift_rms_tol_npm),
        refresh_convergence_torque_rms_tol_nmpm=float(args.refresh_convergence_torque_rms_tol_nmpm),
        rib_zonewise_mode=rib_zonewise_mode,
        rib_family_switch_penalty_kg=rib_family_switch_penalty_kg,
        rib_family_mix_max_unique=rib_family_mix_max_unique,
    )

    final_iteration = refinement.final_iteration
    final_export_loads = LoadMapper.apply_load_factor(
        final_iteration.mapped_loads,
        design_case.aero_scale,
    )
    artifacts = export_inverse_design_artifacts(
        output_dir=output_dir,
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        export_loads=final_export_loads,
        candidate=final_iteration.outcome.selected,
        active_wall_diagnostics=final_iteration.outcome.active_wall_diagnostics,
        step_engine=args.step_engine,
        skip_step_export=bool(args.skip_step_export),
    )
    aero_contract_json_path = output_dir / "candidate_aero_contract.json"
    aero_contract_json_path.write_text(
        json.dumps(asdict(aero_contract), indent=2) + "\n",
        encoding="utf-8",
    )
    artifacts = ArtifactBundle(
        **{
            **asdict(artifacts),
            "aero_contract_json": str(aero_contract_json_path.resolve()),
        }
    )
    refinement = RefreshRefinementOutcome(
        refresh_steps_requested=refinement.refresh_steps_requested,
        refresh_steps_completed=refinement.refresh_steps_completed,
        dynamic_design_space_enabled=refinement.dynamic_design_space_enabled,
        dynamic_design_space_rebuilds=refinement.dynamic_design_space_rebuilds,
        converged=refinement.converged,
        convergence_reason=refinement.convergence_reason,
        manufacturing_limit_source=refinement.manufacturing_limit_source,
        max_jig_vertical_prebend_limit_m=refinement.max_jig_vertical_prebend_limit_m,
        max_jig_vertical_curvature_limit_per_m=refinement.max_jig_vertical_curvature_limit_per_m,
        iterations=refinement.iterations,
        artifacts=artifacts,
        aero_contract=refinement.aero_contract,
    )

    report_path = output_dir / "direct_dual_beam_inverse_design_refresh_report.txt"
    report_path.write_text(
        build_refresh_report_text(
            config_path=config_path,
            design_report=design_report,
            cruise_aoa_deg=cruise_aoa_deg,
            map_config=map_config,
            outcome=refinement,
            refresh_washout_scale=float(args.refresh_washout_scale),
        ),
        encoding="utf-8",
    )

    json_path = output_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
    json_path.write_text(
        json.dumps(
            build_refresh_summary_json(
                config_path=config_path,
                design_report=design_report,
                cruise_aoa_deg=cruise_aoa_deg,
                map_config=map_config,
                outcome=refinement,
                refresh_washout_scale=float(args.refresh_washout_scale),
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    final_selected = refinement.final_iteration.outcome.selected
    print("Inverse-design lightweight load-refresh refinement complete.")
    print(f"  Config              : {config_path}")
    print(f"  Design report       : {design_report}")
    print(f"  Report              : {report_path}")
    print(f"  Summary JSON        : {json_path}")
    print(f"  Aero source mode    : {aero_contract.source_mode}")
    print(f"  Refresh steps       : {refinement.refresh_steps_completed}/{refinement.refresh_steps_requested}")
    print(f"  Dynamic map rebuild : {refinement.dynamic_design_space_rebuilds}")
    print(f"  Converged           : {refinement.converged}")
    if refinement.convergence_reason is not None:
        print(f"  Convergence reason  : {refinement.convergence_reason}")
    print(f"  Feasible            : {refinement.final_iteration.outcome.feasible}")
    if refinement.final_iteration.outcome.target_mass_kg is not None:
        print(f"  Target mass cap     : {refinement.final_iteration.outcome.target_mass_kg:.3f} kg")
    print(
        "  Coarse mass         : "
        f"{refinement.final_iteration.outcome.coarse_selected.total_structural_mass_kg:.3f} kg"
    )
    print(f"  Total mass          : {final_selected.total_structural_mass_kg:.3f} kg")
    print(f"  Loaded-shape Z max  : {_mm(final_selected.loaded_shape_main_z_error_max_m):.6f} mm")
    print(f"  Loaded-shape twist  : {final_selected.loaded_shape_twist_error_max_deg:.6f} deg")
    print(f"  Nodewise mismatch   : {_mm(final_selected.target_shape_error_max_m):.6f} mm")
    print(f"  Jig clearance min   : {_mm(final_selected.jig_ground_clearance_min_m):.3f} mm")
    print(f"  Target Z scale      : {target_shape_z_scale:.6f}")
    print(f"  Dihedral exponent   : {dihedral_exponent:.6f}")
    print(f"  Clearance risk      : {final_selected.clearance_risk_score:.6f}")
    print(f"  Active-wall risk    : {final_selected.active_wall_risk_score:.6f}")
    if refinement.final_iteration.forward_check is not None:
        print(
            "  Forward mismatch    : "
            f"{_mm(refinement.final_iteration.forward_check.target_shape_error_max_m):.6f} mm"
        )
    if refinement.artifacts is not None:
        print(f"  Target shape CSV    : {refinement.artifacts.target_shape_csv}")
        print(f"  Jig shape CSV       : {refinement.artifacts.jig_shape_csv}")
        print(f"  Loaded shape CSV    : {refinement.artifacts.loaded_shape_csv}")
        print(f"  Deflection CSV      : {refinement.artifacts.deflection_csv}")
        print(f"  Jig STEP            : {refinement.artifacts.jig_step_path or 'not written'}")
        print(f"  Loaded STEP         : {refinement.artifacts.loaded_step_path or 'not written'}")
        print(f"  Diagnostics JSON    : {refinement.artifacts.diagnostics_json or 'not written'}")
        print(f"  Validity summary    : {refinement.artifacts.validity_summary_json or 'not written'}")
        print(f"  Wire rigging JSON   : {refinement.artifacts.wire_rigging_json or 'not written'}")
        print(f"  Aero contract JSON  : {refinement.artifacts.aero_contract_json or 'not written'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
