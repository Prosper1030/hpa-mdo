#!/usr/bin/env python3
"""Inverse-design load-refresh refinement for the direct dual-beam V2 path."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime
from itertools import product
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Iterable

import numpy as np
from scipy.optimize import minimize

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper, VSPAeroParser
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
    build_candidate_hard_margins,
    build_reduced_map_config,
    decode_reduced_variables,
    design_from_reduced_variables,
    hard_violation_score_from_margins,
)


FAILED_MASS_KG = 1.0e12
FAILED_MARGIN = -1.0e3
ALL_MARGIN_NAMES = HARD_MARGIN_NAMES + INVERSE_MARGIN_NAMES


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
    inverse_result: object | None = field(default=None, repr=False)
    equivalent_result: OptimizationResult | None = field(default=None, repr=False)


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
            key = tuple(np.round(np.asarray(candidate.z, dtype=float).reshape(-1), 10))
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
    target_shape_csv: str | None
    jig_shape_csv: str | None
    jig_step_path: str | None
    step_engine: str | None
    step_error: str | None


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
    manufacturing_limit_source: str
    max_jig_vertical_prebend_limit_m: float | None
    max_jig_vertical_curvature_limit_per_m: float | None
    iterations: tuple[RefreshIterationResult, ...]
    artifacts: ArtifactBundle | None = None

    @property
    def final_iteration(self) -> RefreshIterationResult:
        if not self.iterations:
            raise RuntimeError("Refresh refinement outcome has no iterations.")
        return self.iterations[-1]


def _parse_grid(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Grid specification must contain at least one float.")
    for value in values:
        if value < -1.0e-12 or value > 1.0 + 1.0e-12:
            raise ValueError("Grid fractions must stay within [0, 1].")
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


def _feasible_key(candidate: InverseCandidate) -> tuple[float, float, float]:
    return (
        float(candidate.total_structural_mass_kg),
        float(candidate.max_jig_vertical_prebend_m),
        float(candidate.max_jig_vertical_curvature_per_m),
    )


def _violation_key(candidate: InverseCandidate) -> tuple[float, float, float]:
    return (
        float(candidate.hard_violation_score),
        float(candidate.total_structural_mass_kg),
        float(candidate.max_jig_vertical_prebend_m),
    )


def _target_violation_key(candidate: InverseCandidate) -> tuple[float, float, float]:
    overshoot_kg = max(-float(candidate.mass_margin_kg), 0.0)
    return (
        float(candidate.target_violation_score),
        float(overshoot_kg),
        float(candidate.total_structural_mass_kg),
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
        target_mass_kg: float | None = None,
    ):
        self.cfg = cfg
        self.aircraft = aircraft
        self.materials_db = materials_db
        self.optimizer = optimizer
        self.export_loads = export_loads
        self.baseline = baseline
        self.map_config = map_config
        self.clearance_floor_z_m = float(clearance_floor_z_m)
        self.target_shape_error_tol_m = float(target_shape_error_tol_m)
        self.max_jig_vertical_prebend_m = max_jig_vertical_prebend_m
        self.max_jig_vertical_curvature_per_m = max_jig_vertical_curvature_per_m
        self.target_mass_kg = None if target_mass_kg is None else float(target_mass_kg)
        self.archive = CandidateArchive(target_mass_kg=self.target_mass_kg)
        self._cache: dict[tuple[float, ...], InverseCandidate] = {}
        self.unique_evaluations = 0
        self.cache_hits = 0
        self.equivalent_analysis_calls = 0
        self.production_analysis_calls = 0

    def _key(self, z: np.ndarray) -> tuple[float, ...]:
        return tuple(np.round(np.asarray(z, dtype=float).reshape(5), 10))

    def evaluate(self, z: np.ndarray, *, source: str) -> InverseCandidate:
        z_arr = np.asarray(z, dtype=float).reshape(5)
        key = self._key(z_arr)
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        z_bounded = np.clip(z_arr, 0.0, 1.0)
        bounds_violated = bool(np.max(np.abs(z_bounded - z_arr)) > 1.0e-12)
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

            eq_result = self.optimizer.analyze(
                main_t_seg=main_t,
                main_r_seg=main_r,
                rear_t_seg=rear_t,
                rear_r_seg=rear_r,
            )
            self.equivalent_analysis_calls += 1

            model = build_dual_beam_mainline_model(
                cfg=self.cfg,
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

            finite_scalars = [
                float(production.recovery.spar_tube_mass_full_kg),
                float(production.recovery.total_structural_mass_full_kg),
                float(production.optimizer.equivalent_gates.failure_index),
                float(production.optimizer.equivalent_gates.buckling_index),
                float(production.optimizer.equivalent_gates.tip_deflection_m),
                float(production.optimizer.equivalent_gates.twist_max_deg),
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
                inverse_result=inverse,
                equivalent_result=eq_result,
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
                inverse_result=None,
                equivalent_result=None,
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
    previous: RefreshIterationResult | None,
    forward_check: ForwardRefreshCheck | None,
) -> RefreshIterationResult:
    result = RefreshIterationResult(
        iteration_index=int(iteration_index),
        load_source=str(load_source),
        outcome=outcome,
        load_metrics=load_metrics,
        mapped_loads=dict(mapped_loads),
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
    if inverse is not None:
        feasibility_report = {
            "analysis_succeeded": inverse.feasibility.analysis_succeeded,
            "geometry_validity_passed": inverse.feasibility.geometry_validity_passed,
            "equivalent_failure_passed": inverse.feasibility.equivalent_failure_passed,
            "equivalent_buckling_passed": inverse.feasibility.equivalent_buckling_passed,
            "equivalent_tip_passed": inverse.feasibility.equivalent_tip_passed,
            "equivalent_twist_passed": inverse.feasibility.equivalent_twist_passed,
            "target_shape_error_passed": inverse.feasibility.target_shape_error_passed,
            "ground_clearance_passed": inverse.feasibility.ground_clearance_passed,
            "manufacturing_passed": inverse.feasibility.manufacturing_passed,
            "safety_passed": inverse.feasibility.safety_passed,
            "overall_feasible": inverse.feasibility.overall_feasible,
            "failures": list(inverse.feasibility.failures),
            "target_shape_error": asdict(inverse.target_shape_error),
            "ground_clearance": asdict(inverse.ground_clearance),
            "manufacturing": asdict(inverse.manufacturing),
        }
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
        "hard_violation_score": candidate.hard_violation_score,
        "target_violation_score": candidate.target_violation_score,
        "hard_margins": {key: float(value) for key, value in candidate.hard_margins.items()},
        "design_mm": {
            "main_t": [float(value * 1000.0) for value in candidate.main_t_seg_m],
            "main_r": [float(value * 1000.0) for value in candidate.main_r_seg_m],
            "rear_t": [float(value * 1000.0) for value in candidate.rear_t_seg_m],
            "rear_r": [float(value * 1000.0) for value in candidate.rear_r_seg_m],
        },
        "target_loaded_shape": target_shape,
        "jig_shape": jig_shape,
        "predicted_loaded_shape": predicted_loaded_shape,
        "feasibility_report": feasibility_report,
    }


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
    lines.append("  jig_shape                   : nodes_target - structural displacement")
    lines.append("  predicted_loaded_shape      : jig_shape + same frozen displacement")
    lines.append("")
    lines.append("Physics assumptions:")
    lines.append("  1. One-way frozen-load aeroelastic solve; aerodynamic loads are not refreshed after jig back-out.")
    lines.append("  2. Cruise target shape is represented on the existing main/rear spar beam lines, not the full wing skin.")
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
    lines.append(f"  Target shape error max      {_mm(baseline.target_shape_error_max_m):11.6f} mm")
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
    lines.append(f"  Target shape error max       {_mm(selected.target_shape_error_max_m):11.6f} mm")
    lines.append(f"  Target shape error rms       {_mm(selected.target_shape_error_rms_m):11.6f} mm")
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
        lines.append(f"  jig STEP                     : {outcome.artifacts.jig_step_path or 'not written'}")
        lines.append(f"  STEP engine                  : {outcome.artifacts.step_engine or 'not run'}")
        if outcome.artifacts.step_error:
            lines.append(f"  STEP export note             : {outcome.artifacts.step_error}")
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
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "cruise_aoa_deg": float(cruise_aoa_deg),
        "mvp_definition": {
            "target_loaded_shape": "current VSP / structural cruise geometry on main and rear spar beam nodes",
            "jig_shape_rule": "nodes_jig = nodes_target - delta_u",
            "frozen_load_source": "cruise mapped loads on the target shape; no aerodynamic load refresh loop in this MVP",
            "physics_assumptions": [
                "one-way frozen-load structural solve",
                "beam-line target shape, not full wing skin",
                "loaded-shape closure uses the same frozen displacement field",
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
        },
        "artifacts": None if outcome.artifacts is None else asdict(outcome.artifacts),
    }


def _build_refresh_iteration_summary(iteration: RefreshIterationResult) -> dict[str, object]:
    selected = iteration.outcome.selected
    return {
        "iteration_index": iteration.iteration_index,
        "load_source": iteration.load_source,
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
    lines.append("")
    lines.append("Definition:")
    lines.append("  target_loaded_shape         : current VSP / structural cruise geometry at the beam nodes")
    lines.append("  jig_shape                   : nodes_target - structural displacement")
    lines.append("  refresh method              : reuse existing VSPAero AoA sweep, reduce local effective AoA by structural twist")
    lines.append("  outer updates               : 1-2 one-way refresh steps only; no inner converged aero-structural loop")
    lines.append("")
    lines.append("Physics assumptions:")
    lines.append("  1. Each stage is still a one-way structural solve on the existing beam-line target shape.")
    lines.append("  2. Refreshed loads are interpolated from existing VSPAero AoA cases; OpenVSP is not rerun.")
    lines.append("  3. Structural twist is treated as local washout with a simple scalar scale factor.")
    lines.append("  4. The forward refresh check estimates frozen-load bias by applying refreshed displacement to the previous jig.")
    lines.append("")
    lines.append("Difference from full coupling:")
    lines.append("  - capped outer refresh count instead of iterating to convergence")
    lines.append("  - no geometry rebuild / CFD rerun between stages")
    lines.append("  - no trim solve or dynamic design-space update")
    lines.append("")
    lines.append("Reduced map (unchanged V2 design variables):")
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
        lines.append(f"  inverse target error max    : {_mm(selected.target_shape_error_max_m):11.6f} mm")
        lines.append(f"  inverse target error rms    : {_mm(selected.target_shape_error_rms_m):11.6f} mm")
        lines.append(f"  jig min ground clearance    : {_mm(selected.jig_ground_clearance_min_m):11.3f} mm")
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
                f"    inverse target error max  : {_mm(iteration.inverse_target_error_delta_m):+11.6f} mm"
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

    lines.append("Artifacts:")
    if outcome.artifacts is not None:
        lines.append(f"  target shape CSV             : {outcome.artifacts.target_shape_csv or 'not written'}")
        lines.append(f"  jig shape CSV                : {outcome.artifacts.jig_shape_csv or 'not written'}")
        lines.append(f"  jig STEP                     : {outcome.artifacts.jig_step_path or 'not written'}")
        lines.append(f"  STEP engine                  : {outcome.artifacts.step_engine or 'not run'}")
        if outcome.artifacts.step_error:
            lines.append(f"  STEP export note             : {outcome.artifacts.step_error}")
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
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "cruise_aoa_deg": float(cruise_aoa_deg),
        "refinement_definition": {
            "target_loaded_shape": "current VSP / structural cruise geometry on main and rear spar beam nodes",
            "jig_shape_rule": "nodes_jig = nodes_target - delta_u",
            "refresh_method": "reuse existing VSPAero AoA sweep and reduce local effective AoA by structural twist-derived washout",
            "target_mass_kg": outcome.final_iteration.outcome.target_mass_kg,
            "refresh_steps_requested": outcome.refresh_steps_requested,
            "refresh_steps_completed": outcome.refresh_steps_completed,
            "refresh_washout_scale": float(refresh_washout_scale),
            "physics_assumptions": [
                "each outer stage is still one-way with frozen loads inside that stage",
                "beam-line target shape is fixed across refreshes",
                "no OpenVSP rerun; loads come from interpolation across existing AoA cases",
                "forward refresh check estimates old-jig mismatch under refreshed displacement",
            ],
            "difference_from_full_coupling": [
                "no convergence loop to aero-structural tolerance",
                "no geometry rebuild or new aerodynamic solve between stages",
                "no trim update or dynamic design-space rewrite",
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
        "iterations": [_build_refresh_iteration_summary(iteration) for iteration in outcome.iterations],
        "artifacts": None if outcome.artifacts is None else asdict(outcome.artifacts),
    }


def export_inverse_design_artifacts(
    *,
    output_dir: Path,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    export_loads: dict,
    candidate: InverseCandidate,
    step_engine: str,
    skip_step_export: bool,
) -> ArtifactBundle:
    """Write target/jig CSV artifacts and optionally export a jig STEP model."""

    if candidate.inverse_result is None:
        return ArtifactBundle(
            target_shape_csv=None,
            jig_shape_csv=None,
            jig_step_path=None,
            step_engine=None,
            step_error="selected candidate has no inverse-design shape payload",
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

    jig_step_path: str | None = None
    resolved_engine: str | None = None
    step_error: str | None = None
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

    return ArtifactBundle(
        target_shape_csv=str(target_csv_path.resolve()),
        jig_shape_csv=str(jig_csv_path.resolve()),
        jig_step_path=jig_step_path,
        step_engine=resolved_engine,
        step_error=step_error,
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
    clearance_floor_z_m: float,
    target_shape_error_tol_m: float,
    max_jig_vertical_prebend_m: float | None,
    max_jig_vertical_curvature_per_m: float | None,
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
) -> InverseOutcome:
    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
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
        target_mass_kg=target_mass_kg,
    )

    total_start = perf_counter()
    baseline = evaluator.evaluate(np.zeros(5, dtype=float), source="baseline")

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
        evaluator.evaluate(np.asarray(point, dtype=float), source="coarse_grid")

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

            def _objective(z: np.ndarray, *, source_name: str = objective_source) -> float:
                objective_calls["n"] += 1
                cand = evaluator.evaluate(z, source=source_name)
                return float(cand.total_structural_mass_kg)

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
            end_candidate = evaluator.evaluate(np.asarray(opt.x, dtype=float), source=final_source)
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
    refresh_steps: int,
) -> RefreshRefinementOutcome:
    design_case = cfg.structural_load_cases()[0]
    refresh_steps = int(refresh_steps)
    iterations: list[RefreshIterationResult] = []

    optimizer.update_aero_loads(initial_mapped_loads)
    initial_export_loads = LoadMapper.apply_load_factor(initial_mapped_loads, design_case.aero_scale)
    frozen_outcome = run_inverse_design(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=initial_export_loads,
        baseline_result=baseline_result,
        map_config=map_config,
        clearance_floor_z_m=clearance_floor_z_m,
        target_shape_error_tol_m=target_shape_error_tol_m,
        max_jig_vertical_prebend_m=max_jig_vertical_prebend_m,
        max_jig_vertical_curvature_per_m=max_jig_vertical_curvature_per_m,
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
    )
    iterations.append(
        _build_refresh_iteration_result(
            iteration_index=0,
            load_source=f"target_shape_frozen_aoa_{float(refresh_model._baseline_case.aoa_deg):.3f}deg",
            outcome=frozen_outcome,
            mapped_loads=initial_mapped_loads,
            load_metrics=refresh_model.baseline_metrics(initial_mapped_loads),
            previous=None,
            forward_check=None,
        )
    )

    for step in range(1, refresh_steps + 1):
        previous_iteration = iterations[-1]
        previous_selected = previous_iteration.outcome.selected
        if previous_selected.equivalent_result is None:
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
        refreshed_outcome = run_inverse_design(
            cfg=cfg,
            aircraft=aircraft,
            materials_db=materials_db,
            optimizer=optimizer,
            export_loads=refreshed_export_loads,
            baseline_result=baseline_result,
            map_config=map_config,
            clearance_floor_z_m=clearance_floor_z_m,
            target_shape_error_tol_m=target_shape_error_tol_m,
            max_jig_vertical_prebend_m=max_jig_vertical_prebend_m,
            max_jig_vertical_curvature_per_m=max_jig_vertical_curvature_per_m,
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
        )
        iterations.append(
            _build_refresh_iteration_result(
                iteration_index=step,
                load_source=f"refresh_{step}_from_iteration_{previous_iteration.iteration_index}",
                outcome=refreshed_outcome,
                mapped_loads=refreshed_mapped_loads,
                load_metrics=refreshed_metrics,
                previous=previous_iteration,
                forward_check=forward_check,
            )
        )

    return RefreshRefinementOutcome(
        refresh_steps_requested=refresh_steps,
        refresh_steps_completed=max(0, len(iterations) - 1),
        manufacturing_limit_source=manufacturing_limit_source,
        max_jig_vertical_prebend_limit_m=max_jig_vertical_prebend_m,
        max_jig_vertical_curvature_limit_per_m=max_jig_vertical_curvature_per_m,
        iterations=tuple(iterations),
        artifacts=None,
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
        "--refresh-washout-scale",
        type=float,
        default=1.0,
        help="Scale factor that converts structural twist into local effective-AoA reduction during refresh.",
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

    aero_cases = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar).parse()
    cruise_case, mapped_loads = _select_cruise_case_and_mapped_loads(
        cfg,
        aircraft,
        aero_cases,
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
        refresh_steps=int(args.refresh_steps),
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
        step_engine=args.step_engine,
        skip_step_export=bool(args.skip_step_export),
    )
    refinement = RefreshRefinementOutcome(
        refresh_steps_requested=refinement.refresh_steps_requested,
        refresh_steps_completed=refinement.refresh_steps_completed,
        manufacturing_limit_source=refinement.manufacturing_limit_source,
        max_jig_vertical_prebend_limit_m=refinement.max_jig_vertical_prebend_limit_m,
        max_jig_vertical_curvature_limit_per_m=refinement.max_jig_vertical_curvature_limit_per_m,
        iterations=refinement.iterations,
        artifacts=artifacts,
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
    print(f"  Refresh steps       : {refinement.refresh_steps_completed}/{refinement.refresh_steps_requested}")
    print(f"  Feasible            : {refinement.final_iteration.outcome.feasible}")
    if refinement.final_iteration.outcome.target_mass_kg is not None:
        print(f"  Target mass cap     : {refinement.final_iteration.outcome.target_mass_kg:.3f} kg")
    print(
        "  Coarse mass         : "
        f"{refinement.final_iteration.outcome.coarse_selected.total_structural_mass_kg:.3f} kg"
    )
    print(f"  Total mass          : {final_selected.total_structural_mass_kg:.3f} kg")
    print(f"  Target error max    : {_mm(final_selected.target_shape_error_max_m):.6f} mm")
    print(f"  Jig clearance min   : {_mm(final_selected.jig_ground_clearance_min_m):.3f} mm")
    if refinement.final_iteration.forward_check is not None:
        print(
            "  Forward mismatch    : "
            f"{_mm(refinement.final_iteration.forward_check.target_shape_error_max_m):.6f} mm"
        )
    if refinement.artifacts is not None:
        print(f"  Target shape CSV    : {refinement.artifacts.target_shape_csv}")
        print(f"  Jig shape CSV       : {refinement.artifacts.jig_shape_csv}")
        print(f"  Jig STEP            : {refinement.artifacts.jig_step_path or 'not written'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
