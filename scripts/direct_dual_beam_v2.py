#!/usr/bin/env python3
"""Reduced direct dual-beam optimizer V2 using the production smooth evaluator."""

from __future__ import annotations

import argparse
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

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import AnalysisModeName, SparOptimizer, run_dual_beam_mainline_analysis
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_crossval import _select_cruise_loads
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report


FAILED_MASS_KG = 1.0e12
FAILED_MARGIN = -1.0e3
SCALE_NAMES = (
    "main_plateau_scale",
    "main_taper_fill",
    "rear_radius_scale",
    "rear_outboard_fraction",
    "wall_thickness_fraction",
)
GEOMETRY_MARGIN_NAMES = (
    "main_thickness_ratio_margin_min_m",
    "rear_thickness_ratio_margin_min_m",
    "main_hollow_margin_min_m",
    "rear_hollow_margin_min_m",
    "main_radius_taper_margin_min_m",
    "rear_radius_taper_margin_min_m",
    "main_thickness_step_margin_min_m",
    "rear_thickness_step_margin_min_m",
    "radius_dominance_margin_min_m",
    "rear_main_radius_ratio_margin_min_m",
    "ei_dominance_margin_min_nm2",
    "ei_ratio_margin_min",
    "rear_inboard_ei_margin_min_nm2",
)
EQ_MARGIN_NAMES = (
    "equivalent_failure_margin",
    "equivalent_buckling_margin",
    "equivalent_tip_margin",
    "equivalent_twist_margin",
)
HARD_MARGIN_NAMES = GEOMETRY_MARGIN_NAMES + EQ_MARGIN_NAMES


@dataclass(frozen=True)
class BaselineDesign:
    main_t_seg_m: np.ndarray
    main_r_seg_m: np.ndarray
    rear_t_seg_m: np.ndarray
    rear_r_seg_m: np.ndarray


@dataclass(frozen=True)
class ReducedMapConfig:
    main_plateau_scale_upper: float
    main_taper_fill_upper: float
    rear_radius_scale_upper: float
    delta_t_global_max_m: float
    delta_t_rear_outboard_max_m: float
    rear_outboard_mask: np.ndarray


@dataclass(frozen=True)
class DirectV2Candidate:
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
    raw_main_tip_m: float
    raw_rear_tip_m: float
    raw_max_uz_m: float
    raw_max_location: str
    psi_u_all_m: float
    psi_u_rear_m: float
    psi_u_rear_outboard_m: float
    dual_displacement_limit_m: float | None
    equivalent_failure_index: float
    equivalent_buckling_index: float
    equivalent_tip_deflection_m: float
    equivalent_twist_max_deg: float
    equivalent_failure_passed: bool
    equivalent_buckling_passed: bool
    equivalent_tip_passed: bool
    equivalent_twist_passed: bool
    geometry_validity_succeeded: bool
    analysis_succeeded: bool
    overall_hard_feasible: bool
    overall_optimizer_candidate_feasible: bool
    hard_failures: tuple[str, ...]
    candidate_failures: tuple[str, ...]
    hard_margins: dict[str, float]
    hard_violation_score: float
    candidate_excess_m: float


@dataclass
class CandidateArchive:
    candidates: list[DirectV2Candidate] = field(default_factory=list)
    best_candidate_feasible: DirectV2Candidate | None = None
    best_hard_feasible: DirectV2Candidate | None = None
    best_violation: DirectV2Candidate | None = None

    def add(self, cand: DirectV2Candidate) -> None:
        self.candidates.append(cand)
        if cand.overall_optimizer_candidate_feasible:
            if (
                self.best_candidate_feasible is None
                or _candidate_feasible_key(cand) < _candidate_feasible_key(self.best_candidate_feasible)
            ):
                self.best_candidate_feasible = cand
        if cand.overall_hard_feasible:
            if self.best_hard_feasible is None or _hard_feasible_key(cand) < _hard_feasible_key(
                self.best_hard_feasible
            ):
                self.best_hard_feasible = cand
        if self.best_violation is None or _violation_key(cand) < _violation_key(self.best_violation):
            self.best_violation = cand

    @property
    def selected(self) -> DirectV2Candidate | None:
        return self.best_candidate_feasible or self.best_hard_feasible or self.best_violation

    @property
    def candidate_feasible_count(self) -> int:
        return sum(1 for cand in self.candidates if cand.overall_optimizer_candidate_feasible)

    @property
    def hard_feasible_count(self) -> int:
        return sum(1 for cand in self.candidates if cand.overall_hard_feasible)


@dataclass(frozen=True)
class LocalStageSummary:
    label: str
    target_psi_u_all_m: float
    start_source: str
    start_mass_kg: float
    start_psi_u_all_m: float
    end_mass_kg: float
    end_psi_u_all_m: float
    success: bool
    message: str
    nfev: int
    nit: int


@dataclass(frozen=True)
class DirectV2Outcome:
    success: bool
    feasible: bool
    message: str
    total_wall_time_s: float
    baseline_eval_wall_time_s: float
    nfev: int
    nit: int
    equivalent_analysis_calls: int
    production_analysis_calls: int
    smooth_evaluator_calls: int
    unique_evaluations: int
    cache_hits: int
    coarse_unique_evaluations: int
    local_unique_evaluations: int
    archive_candidate_feasible_count: int
    archive_hard_feasible_count: int
    baseline: DirectV2Candidate
    selected: DirectV2Candidate
    stage_summaries: tuple[LocalStageSummary, ...]


def _parse_grid(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Grid specification must contain at least one float.")
    return values


def _status(flag: bool) -> str:
    return "PASS" if flag else "FAIL"


def _mm(value_m: float | None) -> float:
    if value_m is None:
        return float("nan")
    return abs(float(value_m) * 1000.0)


def _signed_mm_delta(delta_m: float) -> float:
    return float(delta_m) * 1000.0


def _fmt_array_mm(values_m: np.ndarray) -> str:
    values_mm = np.asarray(values_m, dtype=float) * 1000.0
    return "[" + ", ".join(f"{value:.3f}" for value in values_mm) + "]"


def _safe_log_scale_upper(scale_upper: float) -> float:
    return max(float(scale_upper), 1.0 + 1.0e-12)


def build_reduced_map_config(
    *,
    baseline: BaselineDesign,
    cfg,
    main_plateau_scale_upper: float,
    main_taper_fill_upper: float,
    rear_radius_scale_upper: float,
) -> ReducedMapConfig:
    """Build the reduced V2 map constants from the baseline specimen."""

    n_seg = int(baseline.main_r_seg_m.size)
    if n_seg != 6 or baseline.rear_r_seg_m.size != 6:
        raise ValueError(
            "direct_dual_beam_v2 currently supports the Black Cat 004 six-segment reduced map only."
        )

    solver = cfg.solver
    max_t = float(solver.max_wall_thickness_m)
    ratio_limit = float(solver.max_thickness_to_radius_ratio)
    rear_inner = float(solver.rear_min_inner_radius_m)
    max_radius = float(solver.max_radius_m)
    max_step = float(solver.max_thickness_step_m)

    all_t = np.concatenate((baseline.main_t_seg_m, baseline.rear_t_seg_m))
    all_r = np.concatenate((baseline.main_r_seg_m, baseline.rear_r_seg_m))
    delta_t_global_max_m = float(
        max(
            min(
                np.min(max_t - all_t),
                np.min(ratio_limit * all_r - all_t),
                np.min(baseline.main_r_seg_m - baseline.main_t_seg_m),
                np.min(baseline.rear_r_seg_m - baseline.rear_t_seg_m - rear_inner),
            ),
            0.0,
        )
    )

    rear_outboard_mask = np.zeros(6, dtype=float)
    rear_outboard_mask[-2:] = 1.0
    step_margin_45 = max_step - abs(float(baseline.rear_t_seg_m[4] - baseline.rear_t_seg_m[3]))
    outboard_idx = np.where(rear_outboard_mask > 0.5)[0]
    delta_t_rear_outboard_max_m = float(
        max(
            min(
                step_margin_45,
                float(np.min(max_t - baseline.rear_t_seg_m[outboard_idx])),
                float(np.min(ratio_limit * baseline.rear_r_seg_m[outboard_idx] - baseline.rear_t_seg_m[outboard_idx])),
                float(
                    np.min(
                        baseline.rear_r_seg_m[outboard_idx]
                        - baseline.rear_t_seg_m[outboard_idx]
                        - rear_inner
                    )
                ),
            ),
            0.0,
        )
    )

    plateau_radius = float(baseline.main_r_seg_m[3])
    rear_radius_max = float(np.max(baseline.rear_r_seg_m))
    plateau_scale_cap = min(
        float(main_plateau_scale_upper),
        max_radius / max(plateau_radius, 1.0e-12),
    )
    rear_scale_cap = min(
        float(rear_radius_scale_upper),
        max_radius / max(rear_radius_max, 1.0e-12),
    )

    return ReducedMapConfig(
        main_plateau_scale_upper=float(max(plateau_scale_cap, 1.0)),
        main_taper_fill_upper=float(max(main_taper_fill_upper, 0.0)),
        rear_radius_scale_upper=float(max(rear_scale_cap, 1.0)),
        delta_t_global_max_m=delta_t_global_max_m,
        delta_t_rear_outboard_max_m=delta_t_rear_outboard_max_m,
        rear_outboard_mask=rear_outboard_mask,
    )


def decode_reduced_variables(
    *,
    z: np.ndarray,
    map_config: ReducedMapConfig,
) -> dict[str, float]:
    """Decode the normalized [0, 1]^5 vector into physical reduced variables."""

    z_arr = np.asarray(z, dtype=float).reshape(5)
    if not np.all(np.isfinite(z_arr)):
        raise ValueError("Non-finite reduced variable encountered.")
    if np.min(z_arr) < -1.0e-12 or np.max(z_arr) > 1.0 + 1.0e-12:
        raise ValueError("Reduced variables must stay within [0, 1].")

    main_plateau_log_upper = math.log(_safe_log_scale_upper(map_config.main_plateau_scale_upper))
    rear_radius_log_upper = math.log(_safe_log_scale_upper(map_config.rear_radius_scale_upper))

    main_plateau_scale = math.exp(float(z_arr[0]) * main_plateau_log_upper)
    main_taper_fill = float(z_arr[1]) * float(map_config.main_taper_fill_upper)
    rear_radius_scale = math.exp(float(z_arr[2]) * rear_radius_log_upper)
    rear_outboard_fraction = float(z_arr[3])
    wall_thickness_fraction = float(z_arr[4])

    return {
        "main_plateau_scale": float(main_plateau_scale),
        "main_taper_fill": float(main_taper_fill),
        "rear_radius_scale": float(rear_radius_scale),
        "rear_outboard_fraction": rear_outboard_fraction,
        "wall_thickness_fraction": wall_thickness_fraction,
    }


def design_from_reduced_variables(
    *,
    baseline: BaselineDesign,
    z: np.ndarray,
    map_config: ReducedMapConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Map the five reduced V2 variables to full segment design arrays."""

    vars_physical = decode_reduced_variables(z=z, map_config=map_config)

    plateau = float(baseline.main_r_seg_m[3]) * vars_physical["main_plateau_scale"]
    drop_45 = float(baseline.main_r_seg_m[3] - baseline.main_r_seg_m[4]) * math.exp(
        -vars_physical["main_taper_fill"]
    )
    drop_56 = float(baseline.main_r_seg_m[4] - baseline.main_r_seg_m[5]) * math.exp(
        -vars_physical["main_taper_fill"]
    )

    main_r = np.array(
        [
            plateau,
            plateau,
            plateau,
            plateau,
            plateau - drop_45,
            plateau - drop_45 - drop_56,
        ],
        dtype=float,
    )
    rear_r = np.asarray(baseline.rear_r_seg_m, dtype=float) * vars_physical["rear_radius_scale"]

    delta_t_global = vars_physical["wall_thickness_fraction"] * map_config.delta_t_global_max_m
    delta_t_rear_outboard = (
        vars_physical["rear_outboard_fraction"] * map_config.delta_t_rear_outboard_max_m
    )
    main_t = np.asarray(baseline.main_t_seg_m, dtype=float) + delta_t_global
    rear_t = (
        np.asarray(baseline.rear_t_seg_m, dtype=float)
        + delta_t_global
        + map_config.rear_outboard_mask * delta_t_rear_outboard
    )

    return main_t, main_r, rear_t, rear_r


def _eq_tip_margin(eq) -> float:
    if eq.tip_limit_m is None:
        return float("inf")
    return float(eq.tip_limit_m) * 1.02 - float(eq.tip_deflection_m)


def _eq_twist_margin(eq) -> float:
    if eq.twist_limit_deg is None:
        return float("inf")
    return float(eq.twist_limit_deg) * 1.02 - float(eq.twist_max_deg)


def build_candidate_hard_margins(result) -> dict[str, float]:
    """Collect scalar hard margins used by V2 feasibility-first search."""

    geometry = result.optimizer.geometry_validity
    eq = result.optimizer.equivalent_gates

    margins = {name: float(getattr(geometry, name)) for name in GEOMETRY_MARGIN_NAMES}
    margins.update(
        {
            "equivalent_failure_margin": 0.01 - float(eq.failure_index),
            "equivalent_buckling_margin": 0.01 - float(eq.buckling_index),
            "equivalent_tip_margin": _eq_tip_margin(eq),
            "equivalent_twist_margin": _eq_twist_margin(eq),
        }
    )
    return margins


def hard_violation_score_from_margins(
    margins: dict[str, float],
    *,
    analysis_succeeded: bool,
) -> float:
    score = 0.0 if analysis_succeeded else 1.0
    for value in margins.values():
        if not np.isfinite(value):
            return float("inf")
        score += float(max(-value, 0.0) ** 2)
    return float(score)


def candidate_priority_bucket(candidate: DirectV2Candidate) -> int:
    if candidate.overall_optimizer_candidate_feasible:
        return 0
    if candidate.overall_hard_feasible:
        return 1
    return 2


def _candidate_feasible_key(candidate: DirectV2Candidate) -> tuple[float, float, float]:
    return (
        float(candidate.tube_mass_kg),
        float(candidate.psi_u_all_m),
        float(candidate.total_structural_mass_kg),
    )


def _hard_feasible_key(candidate: DirectV2Candidate) -> tuple[float, float, float]:
    return (
        float(candidate.candidate_excess_m),
        float(candidate.tube_mass_kg),
        float(candidate.psi_u_all_m),
    )


def _violation_key(candidate: DirectV2Candidate) -> tuple[float, float, float]:
    return (
        float(candidate.hard_violation_score),
        float(candidate.candidate_excess_m),
        float(candidate.tube_mass_kg),
    )


class ProductionSmoothEvaluator:
    """Cached black-box evaluator that reuses the production smooth mainline."""

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
    ):
        self.cfg = cfg
        self.aircraft = aircraft
        self.materials_db = materials_db
        self.optimizer = optimizer
        self.export_loads = export_loads
        self.baseline = baseline
        self.map_config = map_config
        self.archive = CandidateArchive()
        self._cache: dict[tuple[float, ...], DirectV2Candidate] = {}
        self.unique_evaluations = 0
        self.cache_hits = 0
        self.equivalent_analysis_calls = 0
        self.production_analysis_calls = 0
        self.smooth_evaluator_calls = 0

    def _key(self, z: np.ndarray) -> tuple[float, ...]:
        return tuple(np.round(np.asarray(z, dtype=float).reshape(5), 10))

    def evaluate(self, z: np.ndarray, *, source: str) -> DirectV2Candidate:
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

            production = run_dual_beam_mainline_analysis(
                cfg=self.cfg,
                aircraft=self.aircraft,
                opt_result=eq_result,
                export_loads=self.export_loads,
                materials_db=self.materials_db,
                mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
            )
            self.production_analysis_calls += 1
            self.smooth_evaluator_calls += 1

            hard_margins = build_candidate_hard_margins(production)
            finite_scalars = [
                float(production.recovery.spar_tube_mass_full_kg),
                float(production.recovery.total_structural_mass_full_kg),
                float(production.report.tip_deflection_main_m),
                float(production.report.tip_deflection_rear_m),
                float(production.report.max_vertical_displacement_m),
                float(production.optimizer.psi_u_all_m),
                float(production.optimizer.psi_u_rear_m),
                float(production.optimizer.psi_u_rear_outboard_m),
                float(production.optimizer.equivalent_gates.failure_index),
                float(production.optimizer.equivalent_gates.buckling_index),
                float(production.optimizer.equivalent_gates.tip_deflection_m),
                float(production.optimizer.equivalent_gates.twist_max_deg),
                *[float(value) for value in hard_margins.values()],
            ]
            if not np.all(np.isfinite(np.asarray(finite_scalars, dtype=float))):
                raise ValueError("Non-finite production metrics encountered.")
            hard_violation_score = hard_violation_score_from_margins(
                hard_margins,
                analysis_succeeded=bool(production.feasibility.analysis_succeeded),
            )
            dual_limit = production.optimizer.dual_displacement_limit_m
            candidate_excess_m = max(
                float(production.optimizer.psi_u_all_m) - float(dual_limit or float("inf")),
                0.0,
            )

            candidate = DirectV2Candidate(
                z=z_arr.copy(),
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
                raw_main_tip_m=float(abs(production.report.tip_deflection_main_m)),
                raw_rear_tip_m=float(abs(production.report.tip_deflection_rear_m)),
                raw_max_uz_m=float(abs(production.report.max_vertical_displacement_m)),
                raw_max_location=f"{production.report.max_vertical_spar} node {production.report.max_vertical_node}",
                psi_u_all_m=float(production.optimizer.psi_u_all_m),
                psi_u_rear_m=float(production.optimizer.psi_u_rear_m),
                psi_u_rear_outboard_m=float(production.optimizer.psi_u_rear_outboard_m),
                dual_displacement_limit_m=(
                    None
                    if dual_limit is None
                    else float(dual_limit)
                ),
                equivalent_failure_index=float(production.optimizer.equivalent_gates.failure_index),
                equivalent_buckling_index=float(production.optimizer.equivalent_gates.buckling_index),
                equivalent_tip_deflection_m=float(production.optimizer.equivalent_gates.tip_deflection_m),
                equivalent_twist_max_deg=float(production.optimizer.equivalent_gates.twist_max_deg),
                equivalent_failure_passed=bool(production.feasibility.equivalent_failure_passed),
                equivalent_buckling_passed=bool(production.feasibility.equivalent_buckling_passed),
                equivalent_tip_passed=bool(production.feasibility.equivalent_tip_passed),
                equivalent_twist_passed=bool(production.feasibility.equivalent_twist_passed),
                geometry_validity_succeeded=bool(production.feasibility.geometry_validity_succeeded),
                analysis_succeeded=bool(production.feasibility.analysis_succeeded),
                overall_hard_feasible=bool(production.feasibility.overall_hard_feasible),
                overall_optimizer_candidate_feasible=bool(
                    production.feasibility.overall_optimizer_candidate_feasible
                ),
                hard_failures=tuple(production.feasibility.hard_failures),
                candidate_failures=tuple(production.feasibility.candidate_constraint_failures),
                hard_margins=hard_margins,
                hard_violation_score=float(hard_violation_score),
                candidate_excess_m=float(candidate_excess_m),
            )
        except Exception as exc:  # pragma: no cover - exercised by runtime failures
            hard_margins = {name: FAILED_MARGIN for name in HARD_MARGIN_NAMES}
            candidate = DirectV2Candidate(
                z=z_arr.copy(),
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
                raw_main_tip_m=float("inf"),
                raw_rear_tip_m=float("inf"),
                raw_max_uz_m=float("inf"),
                raw_max_location="analysis_failed",
                psi_u_all_m=float("inf"),
                psi_u_rear_m=float("inf"),
                psi_u_rear_outboard_m=float("inf"),
                dual_displacement_limit_m=float(self.cfg.wing.max_tip_deflection_m)
                if self.cfg.wing.max_tip_deflection_m is not None
                else None,
                equivalent_failure_index=float("inf"),
                equivalent_buckling_index=float("inf"),
                equivalent_tip_deflection_m=float("inf"),
                equivalent_twist_max_deg=float("inf"),
                equivalent_failure_passed=False,
                equivalent_buckling_passed=False,
                equivalent_tip_passed=False,
                equivalent_twist_passed=False,
                geometry_validity_succeeded=False,
                analysis_succeeded=False,
                overall_hard_feasible=False,
                overall_optimizer_candidate_feasible=False,
                hard_failures=("analysis_exception",),
                candidate_failures=("dual_displacement_candidate",),
                hard_margins=hard_margins,
                hard_violation_score=float("inf"),
                candidate_excess_m=float("inf"),
            )

        self.unique_evaluations += 1
        self._cache[key] = candidate
        self.archive.add(candidate)
        return candidate


def build_constraint_functions(
    *,
    evaluator: ProductionSmoothEvaluator,
    lb: np.ndarray,
    ub: np.ndarray,
) -> list[dict]:
    """COBYLA constraints for normalized bounds and hard-feasibility margins."""

    constraints: list[dict] = []
    for idx in range(lb.size):
        constraints.append({"type": "ineq", "fun": lambda z, ii=idx: z[ii] - lb[ii]})
        constraints.append({"type": "ineq", "fun": lambda z, ii=idx: ub[ii] - z[ii]})

    for key in HARD_MARGIN_NAMES:
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda z, margin_name=key: float(
                    evaluator.evaluate(z, source=f"constraint:{margin_name}").hard_margins[margin_name]
                ),
            }
        )
    return constraints


def build_target_schedule(
    *,
    baseline_psi_u_all_m: float,
    dual_limit_m: float | None,
) -> tuple[float, ...]:
    """Return a small continuation schedule that tightens toward the configured limit."""

    if dual_limit_m is None or not np.isfinite(dual_limit_m) or baseline_psi_u_all_m <= dual_limit_m:
        return (float(baseline_psi_u_all_m),)

    gap = float(baseline_psi_u_all_m - dual_limit_m)
    return (
        float(baseline_psi_u_all_m - 0.35 * gap),
        float(baseline_psi_u_all_m - 0.70 * gap),
        float(dual_limit_m),
    )


def _soft_objective(
    *,
    candidate: DirectV2Candidate,
    baseline: DirectV2Candidate,
    target_psi_u_all_m: float,
    soft_penalty_weight: float,
) -> float:
    if not np.isfinite(candidate.tube_mass_kg):
        return FAILED_MASS_KG
    psi_scale = max(
        abs(float(baseline.psi_u_all_m) - float(target_psi_u_all_m)),
        0.05 * max(float(baseline.psi_u_all_m), 1.0),
        1.0e-3,
    )
    psi_excess = max(float(candidate.psi_u_all_m) - float(target_psi_u_all_m), 0.0)
    soft_penalty = (
        float(soft_penalty_weight)
        * max(float(baseline.tube_mass_kg), 1.0)
        * (psi_excess / psi_scale) ** 2
    )
    return float(candidate.tube_mass_kg + soft_penalty)


def _grid_fraction(values: Iterable[float]) -> tuple[float, ...]:
    cleaned = tuple(float(v) for v in values)
    if not cleaned:
        raise ValueError("Need at least one grid fraction.")
    for value in cleaned:
        if value < -1.0e-12 or value > 1.0 + 1.0e-12:
            raise ValueError("Grid fractions must stay in [0, 1].")
    return cleaned


def run_direct_dual_beam_v2(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    optimizer: SparOptimizer,
    export_loads: dict,
    baseline_result,
    map_config: ReducedMapConfig,
    main_plateau_grid: Iterable[float],
    main_taper_fill_grid: Iterable[float],
    rear_radius_grid: Iterable[float],
    rear_outboard_grid: Iterable[float],
    wall_thickness_grid: Iterable[float],
    cobyla_maxiter: int,
    cobyla_rhobeg: float,
    soft_penalty_weight: float,
) -> DirectV2Outcome:
    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
    evaluator = ProductionSmoothEvaluator(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=export_loads,
        baseline=baseline_design,
        map_config=map_config,
    )

    total_start = perf_counter()
    baseline = evaluator.evaluate(np.zeros(5, dtype=float), source="baseline")

    coarse_grid = list(
        product(
            _grid_fraction(main_plateau_grid),
            _grid_fraction(main_taper_fill_grid),
            _grid_fraction(rear_radius_grid),
            _grid_fraction(rear_outboard_grid),
            _grid_fraction(wall_thickness_grid),
        )
    )
    for point in coarse_grid:
        evaluator.evaluate(np.asarray(point, dtype=float), source="coarse_grid")
    coarse_unique_evaluations = int(evaluator.unique_evaluations)

    lb = np.zeros(5, dtype=float)
    ub = np.ones(5, dtype=float)
    constraints = build_constraint_functions(evaluator=evaluator, lb=lb, ub=ub)
    target_schedule = build_target_schedule(
        baseline_psi_u_all_m=float(baseline.psi_u_all_m),
        dual_limit_m=baseline.dual_displacement_limit_m,
    )

    stage_summaries: list[LocalStageSummary] = []
    total_nfev = 0
    total_nit = 0
    selected_after_coarse = evaluator.archive.selected or baseline
    x_current = np.asarray(selected_after_coarse.z, dtype=float).copy()

    if selected_after_coarse.overall_optimizer_candidate_feasible:
        stage_summaries.append(
            LocalStageSummary(
                label="local_refine_skipped",
                target_psi_u_all_m=float(selected_after_coarse.psi_u_all_m),
                start_source=selected_after_coarse.source,
                start_mass_kg=float(selected_after_coarse.tube_mass_kg),
                start_psi_u_all_m=float(selected_after_coarse.psi_u_all_m),
                end_mass_kg=float(selected_after_coarse.tube_mass_kg),
                end_psi_u_all_m=float(selected_after_coarse.psi_u_all_m),
                success=True,
                message=(
                    "coarse grid already produced a candidate-feasible design; "
                    "kept the feasible archive and skipped local polish"
                ),
                nfev=0,
                nit=0,
            )
        )
    else:
        for stage_idx, target_psi_u_all_m in enumerate(target_schedule, start=1):
            start_candidate = evaluator.evaluate(x_current, source=f"stage_{stage_idx}_start")
            objective_calls = {"n": 0}

            def _objective(z: np.ndarray) -> float:
                objective_calls["n"] += 1
                cand = evaluator.evaluate(z, source=f"stage_{stage_idx}_objective")
                return _soft_objective(
                    candidate=cand,
                    baseline=baseline,
                    target_psi_u_all_m=float(target_psi_u_all_m),
                    soft_penalty_weight=float(soft_penalty_weight),
                )

            opt = minimize(
                _objective,
                x_current,
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
                source=f"stage_{stage_idx}_final",
            )
            total_nfev += int(getattr(opt, "nfev", objective_calls["n"]))
            total_nit += int(getattr(opt, "nit", 0) or 0)
            stage_summaries.append(
                LocalStageSummary(
                    label=f"stage_{stage_idx}",
                    target_psi_u_all_m=float(target_psi_u_all_m),
                    start_source=start_candidate.source,
                    start_mass_kg=float(start_candidate.tube_mass_kg),
                    start_psi_u_all_m=float(start_candidate.psi_u_all_m),
                    end_mass_kg=float(end_candidate.tube_mass_kg),
                    end_psi_u_all_m=float(end_candidate.psi_u_all_m),
                    success=bool(getattr(opt, "success", False)),
                    message=str(getattr(opt, "message", "")),
                    nfev=int(getattr(opt, "nfev", objective_calls["n"])),
                    nit=int(getattr(opt, "nit", 0) or 0),
                )
            )
            x_current = np.asarray((evaluator.archive.selected or end_candidate).z, dtype=float).copy()

    selected = evaluator.archive.selected or baseline
    total_wall_time_s = float(perf_counter() - total_start)
    local_unique_evaluations = int(evaluator.unique_evaluations - coarse_unique_evaluations)
    success = bool(selected.overall_hard_feasible)
    feasible = bool(selected.overall_optimizer_candidate_feasible)

    return DirectV2Outcome(
        success=success,
        feasible=feasible,
        message=selected.message,
        total_wall_time_s=total_wall_time_s,
        baseline_eval_wall_time_s=float(baseline.eval_wall_time_s),
        nfev=int(total_nfev),
        nit=int(total_nit),
        equivalent_analysis_calls=int(evaluator.equivalent_analysis_calls),
        production_analysis_calls=int(evaluator.production_analysis_calls),
        smooth_evaluator_calls=int(evaluator.smooth_evaluator_calls),
        unique_evaluations=int(evaluator.unique_evaluations),
        cache_hits=int(evaluator.cache_hits),
        coarse_unique_evaluations=int(coarse_unique_evaluations),
        local_unique_evaluations=int(local_unique_evaluations),
        archive_candidate_feasible_count=int(evaluator.archive.candidate_feasible_count),
        archive_hard_feasible_count=int(evaluator.archive.hard_feasible_count),
        baseline=baseline,
        selected=selected,
        stage_summaries=tuple(stage_summaries),
    )


def candidate_to_summary_dict(candidate: DirectV2Candidate) -> dict[str, object]:
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
        "raw_main_tip_m": candidate.raw_main_tip_m,
        "raw_rear_tip_m": candidate.raw_rear_tip_m,
        "raw_max_uz_m": candidate.raw_max_uz_m,
        "raw_max_location": candidate.raw_max_location,
        "psi_u_all_m": candidate.psi_u_all_m,
        "psi_u_rear_m": candidate.psi_u_rear_m,
        "psi_u_rear_outboard_m": candidate.psi_u_rear_outboard_m,
        "dual_displacement_limit_m": candidate.dual_displacement_limit_m,
        "equivalent_failure_index": candidate.equivalent_failure_index,
        "equivalent_buckling_index": candidate.equivalent_buckling_index,
        "equivalent_tip_deflection_m": candidate.equivalent_tip_deflection_m,
        "equivalent_twist_max_deg": candidate.equivalent_twist_max_deg,
        "equivalent_failure_passed": candidate.equivalent_failure_passed,
        "equivalent_buckling_passed": candidate.equivalent_buckling_passed,
        "equivalent_tip_passed": candidate.equivalent_tip_passed,
        "equivalent_twist_passed": candidate.equivalent_twist_passed,
        "geometry_validity_succeeded": candidate.geometry_validity_succeeded,
        "analysis_succeeded": candidate.analysis_succeeded,
        "overall_hard_feasible": candidate.overall_hard_feasible,
        "overall_optimizer_candidate_feasible": candidate.overall_optimizer_candidate_feasible,
        "hard_failures": list(candidate.hard_failures),
        "candidate_failures": list(candidate.candidate_failures),
        "hard_violation_score": candidate.hard_violation_score,
        "candidate_excess_m": candidate.candidate_excess_m,
        "design_mm": {
            "main_t": [float(value * 1000.0) for value in candidate.main_t_seg_m],
            "main_r": [float(value * 1000.0) for value in candidate.main_r_seg_m],
            "rear_t": [float(value * 1000.0) for value in candidate.rear_t_seg_m],
            "rear_r": [float(value * 1000.0) for value in candidate.rear_r_seg_m],
        },
    }


def build_report_text(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    map_config: ReducedMapConfig,
    outcome: DirectV2Outcome,
) -> str:
    baseline = outcome.baseline
    selected = outcome.selected
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    lines: list[str] = []
    lines.append("=" * 108)
    lines.append("Direct Dual-Beam V2 Report (Production Smooth Evaluator)")
    lines.append("=" * 108)
    lines.append(f"Generated                     : {generated}")
    lines.append(f"Config                        : {config_path}")
    lines.append(f"Design report                 : {design_report}")
    lines.append(f"Cruise AoA                    : {cruise_aoa_deg:.3f} deg")
    lines.append("Loop                          : baseline specimen -> reduced 5D grid -> COBYLA continuation")
    lines.append("")
    lines.append("Reduced map (Black Cat 004 / 6-segment specific):")
    lines.append(f"  main_plateau_scale upper    : {map_config.main_plateau_scale_upper:.4f}")
    lines.append(f"  main_taper_fill upper       : {map_config.main_taper_fill_upper:.4f}")
    lines.append(f"  rear_radius_scale upper     : {map_config.rear_radius_scale_upper:.4f}")
    lines.append(f"  delta_t_global_max          : {_mm(map_config.delta_t_global_max_m):.3f} mm")
    lines.append(
        f"  delta_t_rear_outboard_max   : {_mm(map_config.delta_t_rear_outboard_max_m):.3f} mm"
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
    lines.append(f"  smooth evaluator calls      : {outcome.smooth_evaluator_calls}")
    lines.append(f"  unique evaluations          : {outcome.unique_evaluations}")
    lines.append(f"  cache hits                  : {outcome.cache_hits}")
    lines.append(f"  coarse unique evaluations   : {outcome.coarse_unique_evaluations}")
    lines.append(f"  local unique evaluations    : {outcome.local_unique_evaluations}")
    lines.append(f"  archive hard feasible       : {outcome.archive_hard_feasible_count}")
    lines.append(f"  archive candidate feasible  : {outcome.archive_candidate_feasible_count}")
    lines.append("")
    lines.append("Baseline (unoptimized specimen):")
    lines.append(f"  Mass                         {baseline.tube_mass_kg:11.3f} kg")
    lines.append(f"  Raw main tip                 {_mm(baseline.raw_main_tip_m):11.3f} mm")
    lines.append(f"  Raw rear tip                 {_mm(baseline.raw_rear_tip_m):11.3f} mm")
    lines.append(f"  Raw max |UZ|                 {_mm(baseline.raw_max_uz_m):11.3f} mm")
    lines.append(f"  psi_u_all                    {_mm(baseline.psi_u_all_m):11.3f} mm")
    lines.append(f"  psi_u_rear                   {_mm(baseline.psi_u_rear_m):11.3f} mm")
    lines.append(f"  psi_u_rear_outboard          {_mm(baseline.psi_u_rear_outboard_m):11.3f} mm")
    lines.append(f"  Equivalent failure           {_status(baseline.equivalent_failure_passed)}")
    lines.append(f"  Equivalent buckling          {_status(baseline.equivalent_buckling_passed)}")
    lines.append(f"  Equivalent tip               {_status(baseline.equivalent_tip_passed)}")
    lines.append(f"  Equivalent twist             {_status(baseline.equivalent_twist_passed)}")
    lines.append(f"  Overall hard feasible        {_status(baseline.overall_hard_feasible)}")
    lines.append(
        f"  Optimizer candidate feasible {_status(baseline.overall_optimizer_candidate_feasible)}"
    )
    lines.append("")
    lines.append("Selected candidate:")
    lines.append(f"  Source                       {selected.source}")
    lines.append(f"  Message                      {selected.message}")
    lines.append(f"  Mass                         {selected.tube_mass_kg:11.3f} kg")
    lines.append(
        f"  Total structural mass        {selected.total_structural_mass_kg:11.3f} kg"
    )
    lines.append(f"  Raw main tip                 {_mm(selected.raw_main_tip_m):11.3f} mm")
    lines.append(f"  Raw rear tip                 {_mm(selected.raw_rear_tip_m):11.3f} mm")
    lines.append(f"  Raw max |UZ|                 {_mm(selected.raw_max_uz_m):11.3f} mm")
    lines.append(f"  Raw max |UZ| location        {selected.raw_max_location}")
    lines.append(f"  psi_u_all                    {_mm(selected.psi_u_all_m):11.3f} mm")
    lines.append(f"  psi_u_rear                   {_mm(selected.psi_u_rear_m):11.3f} mm")
    lines.append(f"  psi_u_rear_outboard          {_mm(selected.psi_u_rear_outboard_m):11.3f} mm")
    lines.append(
        f"  Dual displacement limit      {_mm(selected.dual_displacement_limit_m):11.3f} mm"
        if selected.dual_displacement_limit_m is not None
        else "  Dual displacement limit      none"
    )
    lines.append(
        f"  Equivalent failure           {_status(selected.equivalent_failure_passed)}  value={selected.equivalent_failure_index:.4f}"
    )
    lines.append(
        f"  Equivalent buckling          {_status(selected.equivalent_buckling_passed)}  value={selected.equivalent_buckling_index:.4f}"
    )
    lines.append(
        f"  Equivalent tip               {_status(selected.equivalent_tip_passed)}  value={_mm(selected.equivalent_tip_deflection_m):.3f} mm"
    )
    lines.append(
        f"  Equivalent twist             {_status(selected.equivalent_twist_passed)}  value={selected.equivalent_twist_max_deg:.3f} deg"
    )
    lines.append(f"  Overall hard feasible        {_status(selected.overall_hard_feasible)}")
    lines.append(
        f"  Optimizer candidate feasible {_status(selected.overall_optimizer_candidate_feasible)}"
    )
    lines.append(f"  Hard failures                {', '.join(selected.hard_failures) or 'none'}")
    lines.append(f"  Candidate-only failures      {', '.join(selected.candidate_failures) or 'none'}")
    lines.append("")
    lines.append("Delta (Selected - Baseline):")
    lines.append(f"  Mass delta                   {selected.tube_mass_kg - baseline.tube_mass_kg:+11.3f} kg")
    lines.append(
        f"  Raw main tip delta           {_signed_mm_delta(selected.raw_main_tip_m - baseline.raw_main_tip_m):+11.3f} mm"
    )
    lines.append(
        f"  Raw rear tip delta           {_signed_mm_delta(selected.raw_rear_tip_m - baseline.raw_rear_tip_m):+11.3f} mm"
    )
    lines.append(
        f"  Raw max |UZ| delta           {_signed_mm_delta(selected.raw_max_uz_m - baseline.raw_max_uz_m):+11.3f} mm"
    )
    lines.append(
        f"  psi_u_all delta              {_signed_mm_delta(selected.psi_u_all_m - baseline.psi_u_all_m):+11.3f} mm"
    )
    lines.append(
        f"  psi_u_rear delta             {_signed_mm_delta(selected.psi_u_rear_m - baseline.psi_u_rear_m):+11.3f} mm"
    )
    lines.append(
        f"  psi_u_rear_outboard delta    {_signed_mm_delta(selected.psi_u_rear_outboard_m - baseline.psi_u_rear_outboard_m):+11.3f} mm"
    )
    lines.append("")
    lines.append("Selected reduced variables:")
    lines.append(f"  main_plateau_scale           : {selected.main_plateau_scale:.6f}")
    lines.append(f"  main_taper_fill              : {selected.main_taper_fill:.6f}")
    lines.append(f"  rear_radius_scale            : {selected.rear_radius_scale:.6f}")
    lines.append(f"  rear_outboard_fraction       : {selected.rear_outboard_fraction:.6f}")
    lines.append(f"  wall_thickness_fraction      : {selected.wall_thickness_fraction:.6f}")
    lines.append("")
    lines.append("Selected segment design (mm):")
    lines.append(f"  main_t                       : {_fmt_array_mm(selected.main_t_seg_m)}")
    lines.append(f"  main_r                       : {_fmt_array_mm(selected.main_r_seg_m)}")
    lines.append(f"  rear_t                       : {_fmt_array_mm(selected.rear_t_seg_m)}")
    lines.append(f"  rear_r                       : {_fmt_array_mm(selected.rear_r_seg_m)}")
    lines.append("")
    lines.append("Local continuation stages:")
    for stage in outcome.stage_summaries:
        lines.append(
            f"  {stage.label:10s} target={_mm(stage.target_psi_u_all_m):8.3f} mm  "
            f"start mass={stage.start_mass_kg:8.3f} kg psi={_mm(stage.start_psi_u_all_m):8.3f} mm  "
            f"end mass={stage.end_mass_kg:8.3f} kg psi={_mm(stage.end_psi_u_all_m):8.3f} mm  "
            f"nfev={stage.nfev:4d} nit={stage.nit:4d} success={stage.success}"
        )
        lines.append(f"    message: {stage.message}")
    return "\n".join(lines) + "\n"


def build_summary_json(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    map_config: ReducedMapConfig,
    outcome: DirectV2Outcome,
) -> dict[str, object]:
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "cruise_aoa_deg": float(cruise_aoa_deg),
        "map_config": {
            "main_plateau_scale_upper": map_config.main_plateau_scale_upper,
            "main_taper_fill_upper": map_config.main_taper_fill_upper,
            "rear_radius_scale_upper": map_config.rear_radius_scale_upper,
            "delta_t_global_max_m": map_config.delta_t_global_max_m,
            "delta_t_rear_outboard_max_m": map_config.delta_t_rear_outboard_max_m,
        },
        "outcome": {
            "success": outcome.success,
            "feasible": outcome.feasible,
            "message": outcome.message,
            "total_wall_time_s": outcome.total_wall_time_s,
            "baseline_eval_wall_time_s": outcome.baseline_eval_wall_time_s,
            "nfev": outcome.nfev,
            "nit": outcome.nit,
            "equivalent_analysis_calls": outcome.equivalent_analysis_calls,
            "production_analysis_calls": outcome.production_analysis_calls,
            "smooth_evaluator_calls": outcome.smooth_evaluator_calls,
            "unique_evaluations": outcome.unique_evaluations,
            "cache_hits": outcome.cache_hits,
            "coarse_unique_evaluations": outcome.coarse_unique_evaluations,
            "local_unique_evaluations": outcome.local_unique_evaluations,
            "archive_candidate_feasible_count": outcome.archive_candidate_feasible_count,
            "archive_hard_feasible_count": outcome.archive_hard_feasible_count,
            "baseline": candidate_to_summary_dict(outcome.baseline),
            "selected": candidate_to_summary_dict(outcome.selected),
            "stage_summaries": [asdict(stage) for stage in outcome.stage_summaries],
        },
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run reduced direct dual-beam optimizer V2 with the production smooth evaluator."
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
        help="Production baseline report used as the unoptimized specimen.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent.parent / "output" / "direct_dual_beam_v2_baseline"),
        help="Directory for the V2 report and JSON summary.",
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
    parser.add_argument("--soft-penalty-weight", type=float, default=4.0)
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

    cruise_aoa_deg, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)
    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, materials_db)

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

    outcome = run_direct_dual_beam_v2(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=export_loads,
        baseline_result=baseline_result,
        map_config=map_config,
        main_plateau_grid=_parse_grid(args.main_plateau_grid),
        main_taper_fill_grid=_parse_grid(args.main_taper_fill_grid),
        rear_radius_grid=_parse_grid(args.rear_radius_grid),
        rear_outboard_grid=_parse_grid(args.rear_outboard_grid),
        wall_thickness_grid=_parse_grid(args.wall_thickness_grid),
        cobyla_maxiter=int(args.cobyla_maxiter),
        cobyla_rhobeg=float(args.cobyla_rhobeg),
        soft_penalty_weight=float(args.soft_penalty_weight),
    )

    report_text = build_report_text(
        config_path=config_path,
        design_report=design_report,
        cruise_aoa_deg=cruise_aoa_deg,
        map_config=map_config,
        outcome=outcome,
    )
    report_path = output_dir / "direct_dual_beam_v2_report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    json_path = output_dir / "direct_dual_beam_v2_summary.json"
    json_path.write_text(
        json.dumps(
            build_summary_json(
                config_path=config_path,
                design_report=design_report,
                cruise_aoa_deg=cruise_aoa_deg,
                map_config=map_config,
                outcome=outcome,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    selected = outcome.selected
    print("Direct dual-beam V2 complete.")
    print(f"  Config              : {config_path}")
    print(f"  Design report       : {design_report}")
    print(f"  Report              : {report_path}")
    print(f"  Summary JSON        : {json_path}")
    print(f"  Success / feasible  : {outcome.success} / {outcome.feasible}")
    print(f"  Total wall time     : {outcome.total_wall_time_s:.3f} s")
    print(f"  psi_u_all           : {_mm(selected.psi_u_all_m):.3f} mm")
    print(f"  Mass                : {selected.tube_mass_kg:.3f} kg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
