#!/usr/bin/env python3
"""Manufacturing-aware grouped/discrete direct dual-beam map."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from itertools import product
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import AnalysisModeName, SparOptimizer, run_dual_beam_mainline_analysis
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_crossval import _select_cruise_loads
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report
from scripts.direct_dual_beam_v2x import (
    BaselineDesign,
    build_candidate_hard_margins,
    hard_violation_score_from_margins,
)


FAILED_MASS_KG = 1.0e12
FAILED_MARGIN = -1.0e3
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
class ManufacturingMapConfig:
    main_plateau_delta_catalog_m: tuple[float, ...]
    main_outboard_pair_delta_catalog_m: tuple[float, ...]
    rear_general_radius_delta_catalog_m: tuple[float, ...]
    rear_outboard_tip_delta_t_catalog_m: tuple[float, ...]
    global_wall_delta_t_catalog_m: tuple[float, ...]
    rear_outboard_mask: np.ndarray


@dataclass(frozen=True)
class ManufacturingCandidate:
    choice: tuple[int, int, int, int, int]
    source: str
    message: str
    eval_wall_time_s: float
    main_plateau_delta_m: float
    main_outboard_pair_delta_m: float
    rear_general_radius_delta_m: float
    rear_outboard_tip_delta_t_m: float
    global_wall_delta_t_m: float
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
    candidates: list[ManufacturingCandidate] = field(default_factory=list)
    best_candidate_feasible: ManufacturingCandidate | None = None
    best_hard_feasible: ManufacturingCandidate | None = None
    best_violation: ManufacturingCandidate | None = None

    def add(self, cand: ManufacturingCandidate) -> None:
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
    def selected(self) -> ManufacturingCandidate | None:
        return self.best_candidate_feasible or self.best_hard_feasible or self.best_violation

    @property
    def candidate_feasible_count(self) -> int:
        return sum(1 for cand in self.candidates if cand.overall_optimizer_candidate_feasible)

    @property
    def hard_feasible_count(self) -> int:
        return sum(1 for cand in self.candidates if cand.overall_hard_feasible)


@dataclass(frozen=True)
class ManufacturingOutcome:
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
    archive_candidate_feasible_count: int
    archive_hard_feasible_count: int
    baseline: ManufacturingCandidate
    selected: ManufacturingCandidate


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


def _candidate_feasible_key(candidate: ManufacturingCandidate) -> tuple[float, float, float]:
    return (
        float(candidate.tube_mass_kg),
        float(candidate.psi_u_all_m),
        float(candidate.total_structural_mass_kg),
    )


def _hard_feasible_key(candidate: ManufacturingCandidate) -> tuple[float, float, float]:
    return (
        float(candidate.candidate_excess_m),
        float(candidate.tube_mass_kg),
        float(candidate.psi_u_all_m),
    )


def _violation_key(candidate: ManufacturingCandidate) -> tuple[float, float, float]:
    return (
        float(candidate.hard_violation_score),
        float(candidate.candidate_excess_m),
        float(candidate.tube_mass_kg),
    )


def _candidate_reference_key(candidate: ManufacturingCandidate | None) -> tuple[float, float] | None:
    if candidate is None:
        return None
    return (
        float(candidate.tube_mass_kg),
        float(candidate.psi_u_all_m),
    )


def build_manufacturing_map_config(*, baseline: BaselineDesign, cfg) -> ManufacturingMapConfig:
    solver = cfg.solver
    max_t = float(solver.max_wall_thickness_m)
    ratio_limit = float(solver.max_thickness_to_radius_ratio)
    rear_inner = float(solver.rear_min_inner_radius_m)
    max_radius = float(solver.max_radius_m)

    rear_outboard_mask = np.array([0.0, 0.0, 0.0, 0.0, 0.35, 1.0], dtype=float)

    main_plateau_delta_catalog_m = tuple(
        1.0e-3 * value_mm
        for value_mm in (0.0, 1.5, 2.3, 2.811, 3.4)
        if baseline.main_r_seg_m[3] + 1.0e-3 * value_mm <= max_radius + 1.0e-12
    )
    main_outboard_pair_delta_catalog_m = tuple(1.0e-3 * value_mm for value_mm in (0.0, 0.15, 0.306, 0.45))
    rear_general_radius_delta_catalog_m = tuple(
        1.0e-3 * value_mm
        for value_mm in (0.0, 0.2, 0.4)
        if baseline.rear_r_seg_m[0] + 1.0e-3 * value_mm <= max_radius + 1.0e-12
    )

    raw_global_wall_catalog_m = tuple(1.0e-3 * value_mm for value_mm in (0.0, 0.05))
    raw_rear_tip_delta_catalog_m = tuple(1.0e-3 * value_mm for value_mm in (0.0, 0.03, 0.06, 0.09, 0.12))

    global_wall_delta_t_catalog_m: list[float] = []
    for delta_t in raw_global_wall_catalog_m:
        all_t = np.concatenate((baseline.main_t_seg_m + delta_t, baseline.rear_t_seg_m + delta_t))
        all_r = np.concatenate((baseline.main_r_seg_m, baseline.rear_r_seg_m))
        if np.min(max_t - all_t) < -1.0e-12:
            continue
        if np.min(ratio_limit * all_r - all_t) < -1.0e-12:
            continue
        if np.min(baseline.main_r_seg_m - (baseline.main_t_seg_m + delta_t)) < -1.0e-12:
            continue
        if np.min(baseline.rear_r_seg_m - (baseline.rear_t_seg_m + delta_t) - rear_inner) < -1.0e-12:
            continue
        global_wall_delta_t_catalog_m.append(float(delta_t))

    rear_outboard_tip_delta_t_catalog_m: list[float] = []
    rear_outboard_idx = np.where(rear_outboard_mask > 0.0)[0]
    for delta_t_tip in raw_rear_tip_delta_catalog_m:
        rear_t = baseline.rear_t_seg_m.copy()
        rear_t += rear_outboard_mask * float(delta_t_tip)
        if np.min(max_t - rear_t[rear_outboard_idx]) < -1.0e-12:
            continue
        if np.min(ratio_limit * baseline.rear_r_seg_m[rear_outboard_idx] - rear_t[rear_outboard_idx]) < -1.0e-12:
            continue
        if np.min(baseline.rear_r_seg_m[rear_outboard_idx] - rear_t[rear_outboard_idx] - rear_inner) < -1.0e-12:
            continue
        rear_outboard_tip_delta_t_catalog_m.append(float(delta_t_tip))

    return ManufacturingMapConfig(
        main_plateau_delta_catalog_m=tuple(main_plateau_delta_catalog_m),
        main_outboard_pair_delta_catalog_m=tuple(main_outboard_pair_delta_catalog_m),
        rear_general_radius_delta_catalog_m=tuple(rear_general_radius_delta_catalog_m),
        rear_outboard_tip_delta_t_catalog_m=tuple(rear_outboard_tip_delta_t_catalog_m),
        global_wall_delta_t_catalog_m=tuple(global_wall_delta_t_catalog_m),
        rear_outboard_mask=rear_outboard_mask,
    )


def decode_manufacturing_choice(
    *,
    choice: tuple[int, int, int, int, int],
    map_config: ManufacturingMapConfig,
) -> dict[str, float]:
    return {
        "main_plateau_delta_m": float(map_config.main_plateau_delta_catalog_m[choice[0]]),
        "main_outboard_pair_delta_m": float(map_config.main_outboard_pair_delta_catalog_m[choice[1]]),
        "rear_general_radius_delta_m": float(map_config.rear_general_radius_delta_catalog_m[choice[2]]),
        "rear_outboard_tip_delta_t_m": float(map_config.rear_outboard_tip_delta_t_catalog_m[choice[3]]),
        "global_wall_delta_t_m": float(map_config.global_wall_delta_t_catalog_m[choice[4]]),
    }


def design_from_manufacturing_choice(
    *,
    baseline: BaselineDesign,
    choice: tuple[int, int, int, int, int],
    map_config: ManufacturingMapConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    decoded = decode_manufacturing_choice(choice=choice, map_config=map_config)

    main_plateau_delta = float(decoded["main_plateau_delta_m"])
    main_outboard_pair_delta = float(decoded["main_outboard_pair_delta_m"])
    rear_general_radius_delta = float(decoded["rear_general_radius_delta_m"])
    rear_outboard_tip_delta_t = float(decoded["rear_outboard_tip_delta_t_m"])
    global_wall_delta_t = float(decoded["global_wall_delta_t_m"])

    main_plateau_radius = float(baseline.main_r_seg_m[3]) + main_plateau_delta
    main_r = np.asarray(baseline.main_r_seg_m, dtype=float).copy()
    main_r[:4] = main_plateau_radius
    main_r[4] = float(baseline.main_r_seg_m[4]) + main_plateau_delta + main_outboard_pair_delta
    main_r[5] = float(baseline.main_r_seg_m[5]) + main_plateau_delta + main_outboard_pair_delta

    rear_radius = float(baseline.rear_r_seg_m[0]) + rear_general_radius_delta
    rear_r = np.full(6, rear_radius, dtype=float)

    main_t = np.asarray(baseline.main_t_seg_m, dtype=float) + global_wall_delta_t
    rear_t = (
        np.asarray(baseline.rear_t_seg_m, dtype=float)
        + global_wall_delta_t
        + map_config.rear_outboard_mask * rear_outboard_tip_delta_t
    )
    return main_t, main_r, rear_t, rear_r


class ManufacturingSmoothEvaluator:
    def __init__(
        self,
        *,
        cfg,
        aircraft,
        materials_db: MaterialDB,
        optimizer: SparOptimizer,
        export_loads: dict,
        baseline: BaselineDesign,
        map_config: ManufacturingMapConfig,
    ):
        self.cfg = cfg
        self.aircraft = aircraft
        self.materials_db = materials_db
        self.optimizer = optimizer
        self.export_loads = export_loads
        self.baseline = baseline
        self.map_config = map_config
        self.archive = CandidateArchive()
        self._cache: dict[tuple[int, int, int, int, int], ManufacturingCandidate] = {}
        self.unique_evaluations = 0
        self.cache_hits = 0
        self.equivalent_analysis_calls = 0
        self.production_analysis_calls = 0
        self.smooth_evaluator_calls = 0

    def evaluate(
        self,
        choice: tuple[int, int, int, int, int],
        *,
        source: str,
    ) -> ManufacturingCandidate:
        cached = self._cache.get(choice)
        if cached is not None:
            self.cache_hits += 1
            return cached

        decoded = decode_manufacturing_choice(choice=choice, map_config=self.map_config)
        main_t, main_r, rear_t, rear_r = design_from_manufacturing_choice(
            baseline=self.baseline,
            choice=choice,
            map_config=self.map_config,
        )

        t0 = perf_counter()
        try:
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

            candidate = ManufacturingCandidate(
                choice=choice,
                source=source,
                message="analysis complete",
                eval_wall_time_s=float(perf_counter() - t0),
                main_plateau_delta_m=float(decoded["main_plateau_delta_m"]),
                main_outboard_pair_delta_m=float(decoded["main_outboard_pair_delta_m"]),
                rear_general_radius_delta_m=float(decoded["rear_general_radius_delta_m"]),
                rear_outboard_tip_delta_t_m=float(decoded["rear_outboard_tip_delta_t_m"]),
                global_wall_delta_t_m=float(decoded["global_wall_delta_t_m"]),
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
                dual_displacement_limit_m=None if dual_limit is None else float(dual_limit),
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
        except Exception as exc:  # pragma: no cover - runtime failures
            hard_margins = {name: FAILED_MARGIN for name in HARD_MARGIN_NAMES}
            candidate = ManufacturingCandidate(
                choice=choice,
                source=source,
                message=f"{type(exc).__name__}: {exc}",
                eval_wall_time_s=float(perf_counter() - t0),
                main_plateau_delta_m=float(decoded["main_plateau_delta_m"]),
                main_outboard_pair_delta_m=float(decoded["main_outboard_pair_delta_m"]),
                rear_general_radius_delta_m=float(decoded["rear_general_radius_delta_m"]),
                rear_outboard_tip_delta_t_m=float(decoded["rear_outboard_tip_delta_t_m"]),
                global_wall_delta_t_m=float(decoded["global_wall_delta_t_m"]),
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
        self._cache[choice] = candidate
        self.archive.add(candidate)
        return candidate


def run_direct_dual_beam_v2m(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    optimizer: SparOptimizer,
    export_loads: dict,
    baseline_result,
    map_config: ManufacturingMapConfig,
) -> ManufacturingOutcome:
    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
    evaluator = ManufacturingSmoothEvaluator(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=export_loads,
        baseline=baseline_design,
        map_config=map_config,
    )

    total_start = perf_counter()
    baseline = evaluator.evaluate((0, 0, 0, 0, 0), source="baseline")

    full_grid = product(
        range(len(map_config.main_plateau_delta_catalog_m)),
        range(len(map_config.main_outboard_pair_delta_catalog_m)),
        range(len(map_config.rear_general_radius_delta_catalog_m)),
        range(len(map_config.rear_outboard_tip_delta_t_catalog_m)),
        range(len(map_config.global_wall_delta_t_catalog_m)),
    )
    for choice in full_grid:
        evaluator.evaluate(tuple(int(value) for value in choice), source="catalog_grid")

    selected = evaluator.archive.selected or baseline
    return ManufacturingOutcome(
        success=bool(selected.overall_hard_feasible),
        feasible=bool(selected.overall_optimizer_candidate_feasible),
        message=selected.message,
        total_wall_time_s=float(perf_counter() - total_start),
        baseline_eval_wall_time_s=float(baseline.eval_wall_time_s),
        nfev=0,
        nit=0,
        equivalent_analysis_calls=int(evaluator.equivalent_analysis_calls),
        production_analysis_calls=int(evaluator.production_analysis_calls),
        smooth_evaluator_calls=int(evaluator.smooth_evaluator_calls),
        unique_evaluations=int(evaluator.unique_evaluations),
        cache_hits=int(evaluator.cache_hits),
        archive_candidate_feasible_count=int(evaluator.archive.candidate_feasible_count),
        archive_hard_feasible_count=int(evaluator.archive.hard_feasible_count),
        baseline=baseline,
        selected=selected,
    )


def candidate_to_summary_dict(candidate: ManufacturingCandidate) -> dict[str, object]:
    return {
        "source": candidate.source,
        "message": candidate.message,
        "choice_indices": list(candidate.choice),
        "manufacturing_variables": {
            "main_plateau_delta_mm": _mm(candidate.main_plateau_delta_m),
            "main_outboard_pair_delta_mm": _mm(candidate.main_outboard_pair_delta_m),
            "rear_general_radius_delta_mm": _mm(candidate.rear_general_radius_delta_m),
            "rear_outboard_tip_delta_t_mm": _mm(candidate.rear_outboard_tip_delta_t_m),
            "global_wall_delta_t_mm": _mm(candidate.global_wall_delta_t_m),
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


def _load_reference_summary(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    obj = json.loads(path.read_text())
    outcome = obj.get("outcome", obj.get("analysis", {}).get("v2_outcome"))
    if not isinstance(outcome, dict):
        return None
    selected = outcome.get("selected")
    if not isinstance(selected, dict):
        return None
    return {
        "path": str(path),
        "success": bool(outcome.get("success", selected.get("overall_hard_feasible", False))),
        "feasible": bool(outcome.get("feasible", selected.get("overall_optimizer_candidate_feasible", False))),
        "total_wall_time_s": float(outcome.get("total_wall_time_s", float("nan"))),
        "tube_mass_kg": float(selected["tube_mass_kg"]),
        "raw_main_tip_m": float(selected["raw_main_tip_m"]),
        "raw_rear_tip_m": float(selected["raw_rear_tip_m"]),
        "raw_max_uz_m": float(selected["raw_max_uz_m"]),
        "psi_u_all_m": float(selected["psi_u_all_m"]),
        "psi_u_rear_m": float(selected["psi_u_rear_m"]),
        "psi_u_rear_outboard_m": float(selected["psi_u_rear_outboard_m"]),
        "overall_hard_feasible": bool(selected["overall_hard_feasible"]),
        "overall_optimizer_candidate_feasible": bool(selected["overall_optimizer_candidate_feasible"]),
        "variables": selected.get("reduced_variables", selected.get("manufacturing_variables", {})),
        "design_mm": selected.get("design_mm", {}),
    }


def build_report_text(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    map_config: ManufacturingMapConfig,
    outcome: ManufacturingOutcome,
    continuous_reference: dict[str, object] | None,
) -> str:
    baseline = outcome.baseline
    selected = outcome.selected
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    lines: list[str] = []
    lines.append("=" * 108)
    lines.append("Direct Dual-Beam V2.m Report (Manufacturing-Aware Grouped/Discrete Map)")
    lines.append("=" * 108)
    lines.append(f"Generated                     : {generated}")
    lines.append(f"Config                        : {config_path}")
    lines.append(f"Design report                 : {design_report}")
    lines.append(f"Cruise AoA                    : {cruise_aoa_deg:.3f} deg")
    lines.append("Loop                          : baseline specimen -> grouped/discrete catalog search")
    lines.append("")
    lines.append("Manufacturing-aware V1 map:")
    lines.append("  main plateau group          : seg1-4 share one discrete tube family")
    lines.append("  main outboard pair          : seg5-6 share one discrete companion delta")
    lines.append("  main tip                    : derived from baseline taper; downgraded from free variable")
    lines.append("  rear general group          : seg1-6 share one discrete tube family (reserve)")
    lines.append("  rear outboard sleeve        : seg5-6 use tapered discrete sleeve stack")
    lines.append("  global wall                 : reserve discrete ply step")
    lines.append("")
    lines.append("Catalogs:")
    lines.append(
        "  main_plateau_delta_mm       : "
        + ", ".join(f"{_mm(value):.3f}" for value in map_config.main_plateau_delta_catalog_m)
    )
    lines.append(
        "  main_outboard_pair_delta_mm : "
        + ", ".join(f"{_mm(value):.3f}" for value in map_config.main_outboard_pair_delta_catalog_m)
    )
    lines.append(
        "  rear_general_radius_delta_mm: "
        + ", ".join(f"{_mm(value):.3f}" for value in map_config.rear_general_radius_delta_catalog_m)
    )
    lines.append(
        "  rear_outboard_tip_dt_mm     : "
        + ", ".join(f"{_mm(value):.3f}" for value in map_config.rear_outboard_tip_delta_t_catalog_m)
    )
    lines.append(
        "  global_wall_dt_mm           : "
        + ", ".join(f"{_mm(value):.3f}" for value in map_config.global_wall_delta_t_catalog_m)
    )
    lines.append(f"  rear_outboard_mask          : {np.asarray(map_config.rear_outboard_mask, dtype=float).tolist()}")
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
    lines.append(f"  archive hard feasible       : {outcome.archive_hard_feasible_count}")
    lines.append(f"  archive candidate feasible  : {outcome.archive_candidate_feasible_count}")
    lines.append("")
    lines.append("Baseline (unoptimized specimen):")
    lines.append(f"  Mass                         {baseline.tube_mass_kg:11.3f} kg")
    lines.append(f"  Raw main tip                 {_mm(baseline.raw_main_tip_m):11.3f} mm")
    lines.append(f"  Raw rear tip                 {_mm(baseline.raw_rear_tip_m):11.3f} mm")
    lines.append(f"  Raw max |UZ|                 {_mm(baseline.raw_max_uz_m):11.3f} mm")
    lines.append(f"  psi_u_all                    {_mm(baseline.psi_u_all_m):11.3f} mm")
    lines.append(f"  Overall hard feasible        {_status(baseline.overall_hard_feasible)}")
    lines.append(
        f"  Optimizer candidate feasible {_status(baseline.overall_optimizer_candidate_feasible)}"
    )
    lines.append("")
    if continuous_reference is not None:
        lines.append("Continuous Reference (current reduced map):")
        lines.append(f"  Source path                   {continuous_reference['path']}")
        lines.append(f"  Success / feasible            {continuous_reference['success']} / {continuous_reference['feasible']}")
        lines.append(f"  Wall time                     {continuous_reference['total_wall_time_s']:.3f} s")
        lines.append(f"  Mass                          {continuous_reference['tube_mass_kg']:11.3f} kg")
        lines.append(f"  Raw main tip                  {_mm(continuous_reference['raw_main_tip_m']):11.3f} mm")
        lines.append(f"  Raw rear tip                  {_mm(continuous_reference['raw_rear_tip_m']):11.3f} mm")
        lines.append(f"  Raw max |UZ|                  {_mm(continuous_reference['raw_max_uz_m']):11.3f} mm")
        lines.append(f"  psi_u_all                     {_mm(continuous_reference['psi_u_all_m']):11.3f} mm")
        lines.append(
            f"  Hard / candidate              {_status(bool(continuous_reference['overall_hard_feasible']))}"
            f" / {_status(bool(continuous_reference['overall_optimizer_candidate_feasible']))}"
        )
        lines.append("")
    lines.append("Selected manufacturing-aware candidate:")
    lines.append(f"  Source                       {selected.source}")
    lines.append(f"  Message                      {selected.message}")
    lines.append(f"  Choice indices               {selected.choice}")
    lines.append(f"  Mass                         {selected.tube_mass_kg:11.3f} kg")
    lines.append(f"  Total structural mass        {selected.total_structural_mass_kg:11.3f} kg")
    lines.append(f"  Raw main tip                 {_mm(selected.raw_main_tip_m):11.3f} mm")
    lines.append(f"  Raw rear tip                 {_mm(selected.raw_rear_tip_m):11.3f} mm")
    lines.append(f"  Raw max |UZ|                 {_mm(selected.raw_max_uz_m):11.3f} mm")
    lines.append(f"  Raw max |UZ| location        {selected.raw_max_location}")
    lines.append(f"  psi_u_all                    {_mm(selected.psi_u_all_m):11.3f} mm")
    lines.append(f"  psi_u_rear                   {_mm(selected.psi_u_rear_m):11.3f} mm")
    lines.append(f"  psi_u_rear_outboard          {_mm(selected.psi_u_rear_outboard_m):11.3f} mm")
    lines.append(f"  Overall hard feasible        {_status(selected.overall_hard_feasible)}")
    lines.append(f"  Optimizer candidate feasible {_status(selected.overall_optimizer_candidate_feasible)}")
    lines.append("")
    lines.append("Selected grouped/discrete variables:")
    lines.append(f"  main_plateau_delta           : {_mm(selected.main_plateau_delta_m):.3f} mm")
    lines.append(f"  main_outboard_pair_delta     : {_mm(selected.main_outboard_pair_delta_m):.3f} mm")
    lines.append(f"  rear_general_radius_delta    : {_mm(selected.rear_general_radius_delta_m):.3f} mm")
    lines.append(f"  rear_outboard_tip_delta_t    : {_mm(selected.rear_outboard_tip_delta_t_m):.3f} mm")
    lines.append(f"  global_wall_delta_t          : {_mm(selected.global_wall_delta_t_m):.3f} mm")
    lines.append("")
    lines.append("Selected segment design (mm):")
    lines.append(f"  main_t                       : {_fmt_array_mm(selected.main_t_seg_m)}")
    lines.append(f"  main_r                       : {_fmt_array_mm(selected.main_r_seg_m)}")
    lines.append(f"  rear_t                       : {_fmt_array_mm(selected.rear_t_seg_m)}")
    lines.append(f"  rear_r                       : {_fmt_array_mm(selected.rear_r_seg_m)}")
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
    if continuous_reference is not None:
        lines.append("")
        lines.append("Delta (Manufacturing-aware - Continuous reference):")
        lines.append(
            f"  Mass delta                   {selected.tube_mass_kg - float(continuous_reference['tube_mass_kg']):+11.3f} kg"
        )
        lines.append(
            f"  Raw main tip delta           {_signed_mm_delta(selected.raw_main_tip_m - float(continuous_reference['raw_main_tip_m'])):+11.3f} mm"
        )
        lines.append(
            f"  Raw rear tip delta           {_signed_mm_delta(selected.raw_rear_tip_m - float(continuous_reference['raw_rear_tip_m'])):+11.3f} mm"
        )
        lines.append(
            f"  Raw max |UZ| delta           {_signed_mm_delta(selected.raw_max_uz_m - float(continuous_reference['raw_max_uz_m'])):+11.3f} mm"
        )
        lines.append(
            f"  psi_u_all delta              {_signed_mm_delta(selected.psi_u_all_m - float(continuous_reference['psi_u_all_m'])):+11.3f} mm"
        )
    return "\n".join(lines) + "\n"


def build_summary_json(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    map_config: ManufacturingMapConfig,
    outcome: ManufacturingOutcome,
    continuous_reference: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "cruise_aoa_deg": float(cruise_aoa_deg),
        "map_config": {
            "main_plateau_delta_catalog_mm": [_mm(value) for value in map_config.main_plateau_delta_catalog_m],
            "main_outboard_pair_delta_catalog_mm": [
                _mm(value) for value in map_config.main_outboard_pair_delta_catalog_m
            ],
            "rear_general_radius_delta_catalog_mm": [
                _mm(value) for value in map_config.rear_general_radius_delta_catalog_m
            ],
            "rear_outboard_tip_delta_t_catalog_mm": [
                _mm(value) for value in map_config.rear_outboard_tip_delta_t_catalog_m
            ],
            "global_wall_delta_t_catalog_mm": [_mm(value) for value in map_config.global_wall_delta_t_catalog_m],
            "rear_outboard_mask": [float(value) for value in map_config.rear_outboard_mask],
        },
        "continuous_reference": continuous_reference,
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
            "archive_candidate_feasible_count": outcome.archive_candidate_feasible_count,
            "archive_hard_feasible_count": outcome.archive_hard_feasible_count,
            "baseline": candidate_to_summary_dict(outcome.baseline),
            "selected": candidate_to_summary_dict(outcome.selected),
        },
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run manufacturing-aware grouped/discrete dual-beam map with the production smooth evaluator."
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
        default=str(Path(__file__).resolve().parent.parent / "output" / "direct_dual_beam_v2m_baseline"),
        help="Directory for the manufacturing-aware report and JSON summary.",
    )
    parser.add_argument(
        "--continuous-reference-json",
        default=str(
            Path(__file__).resolve().parent.parent
            / "output"
            / "direct_dual_beam_v2x_baseline"
            / "direct_dual_beam_v2x_summary.json"
        ),
        help="Optional summary JSON from the current continuous reduced map.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    design_report = Path(args.design_report).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    continuous_reference_path = Path(args.continuous_reference_json).expanduser().resolve()

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
    map_config = build_manufacturing_map_config(baseline=baseline_design, cfg=cfg)

    outcome = run_direct_dual_beam_v2m(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=export_loads,
        baseline_result=baseline_result,
        map_config=map_config,
    )
    continuous_reference = _load_reference_summary(continuous_reference_path)

    report_text = build_report_text(
        config_path=config_path,
        design_report=design_report,
        cruise_aoa_deg=cruise_aoa_deg,
        map_config=map_config,
        outcome=outcome,
        continuous_reference=continuous_reference,
    )
    report_path = output_dir / "direct_dual_beam_v2m_report.txt"
    report_path.write_text(report_text, encoding="utf-8")

    summary = build_summary_json(
        config_path=config_path,
        design_report=design_report,
        cruise_aoa_deg=cruise_aoa_deg,
        map_config=map_config,
        outcome=outcome,
        continuous_reference=continuous_reference,
    )
    json_path = output_dir / "direct_dual_beam_v2m_summary.json"
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    selected = outcome.selected
    print("Direct dual-beam V2.m complete.")
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
