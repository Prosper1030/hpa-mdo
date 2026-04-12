#!/usr/bin/env python3
"""Frozen-load aeroelastic inverse-design MVP for the direct dual-beam V2 path."""

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

from hpa_mdo.aero import LoadMapper
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
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.structure.dual_beam_mainline import (
    build_dual_beam_mainline_model,
    run_dual_beam_mainline_kernel,
)
from hpa_mdo.structure.optimizer import OptimizationResult
from hpa_mdo.utils.cad_export import export_step_from_csv
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_crossval import _select_cruise_loads
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
    failures: tuple[str, ...]
    hard_margins: dict[str, float]
    hard_violation_score: float
    inverse_result: object | None = field(default=None, repr=False)


@dataclass
class CandidateArchive:
    candidates: list[InverseCandidate] = field(default_factory=list)
    best_feasible: InverseCandidate | None = None
    best_violation: InverseCandidate | None = None

    def add(self, cand: InverseCandidate) -> None:
        self.candidates.append(cand)
        if cand.overall_feasible:
            if self.best_feasible is None or _feasible_key(cand) < _feasible_key(self.best_feasible):
                self.best_feasible = cand
        if self.best_violation is None or _violation_key(cand) < _violation_key(self.best_violation):
            self.best_violation = cand

    @property
    def selected(self) -> InverseCandidate | None:
        return self.best_feasible or self.best_violation

    @property
    def feasible_count(self) -> int:
        return sum(1 for cand in self.candidates if cand.overall_feasible)


@dataclass(frozen=True)
class LocalRefineSummary:
    start_source: str
    start_mass_kg: float
    end_mass_kg: float
    success: bool
    message: str
    nfev: int
    nit: int


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
    baseline: InverseCandidate
    selected: InverseCandidate
    local_refine: LocalRefineSummary | None
    manufacturing_limit_source: str
    max_jig_vertical_prebend_limit_m: float | None
    max_jig_vertical_curvature_limit_per_m: float | None
    artifacts: ArtifactBundle | None = None


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
        self.archive = CandidateArchive()
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
                failures=tuple(inverse.feasibility.failures),
                hard_margins=hard_margins,
                hard_violation_score=float(hard_violation_score),
                inverse_result=inverse,
            )
        except Exception as exc:  # pragma: no cover - runtime failure guard
            hard_margins = {name: FAILED_MARGIN for name in ALL_MARGIN_NAMES}
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
                failures=("analysis_exception",),
                hard_margins=hard_margins,
                hard_violation_score=float("inf"),
                inverse_result=None,
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
        "failures": list(candidate.failures),
        "hard_violation_score": candidate.hard_violation_score,
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
            "baseline": candidate_to_summary_dict(outcome.baseline),
            "selected": candidate_to_summary_dict(outcome.selected),
            "local_refine": None if outcome.local_refine is None else asdict(outcome.local_refine),
        },
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

    lb = np.zeros(5, dtype=float)
    ub = np.ones(5, dtype=float)
    local_refine: LocalRefineSummary | None = None
    total_nfev = 0
    total_nit = 0

    if not skip_local_refine:
        constraints = build_constraint_functions(evaluator=evaluator, lb=lb, ub=ub)
        start_candidate = evaluator.archive.selected or baseline
        objective_calls = {"n": 0}

        def _objective(z: np.ndarray) -> float:
            objective_calls["n"] += 1
            cand = evaluator.evaluate(z, source="local_objective")
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
        end_candidate = evaluator.evaluate(np.asarray(opt.x, dtype=float), source="local_final")
        total_nfev = int(getattr(opt, "nfev", objective_calls["n"]))
        total_nit = int(getattr(opt, "nit", 0) or 0)
        local_refine = LocalRefineSummary(
            start_source=start_candidate.source,
            start_mass_kg=float(start_candidate.total_structural_mass_kg),
            end_mass_kg=float(end_candidate.total_structural_mass_kg),
            success=bool(getattr(opt, "success", False)),
            message=str(getattr(opt, "message", "")),
            nfev=total_nfev,
            nit=total_nit,
        )

    selected = evaluator.archive.selected or baseline
    total_wall_time_s = float(perf_counter() - total_start)
    return InverseOutcome(
        success=bool(selected.overall_feasible),
        feasible=bool(selected.overall_feasible),
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
        baseline=baseline,
        selected=selected,
        local_refine=local_refine,
        manufacturing_limit_source=manufacturing_limit_source,
        max_jig_vertical_prebend_limit_m=max_jig_vertical_prebend_m,
        max_jig_vertical_curvature_limit_per_m=max_jig_vertical_curvature_per_m,
        artifacts=None,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen-load aeroelastic inverse-design MVP on the reduced direct dual-beam V2 map."
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
            / "direct_dual_beam_inverse_design_mvp"
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

    outcome = run_inverse_design(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=export_loads,
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
    )

    artifacts = export_inverse_design_artifacts(
        output_dir=output_dir,
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        export_loads=export_loads,
        candidate=outcome.selected,
        step_engine=args.step_engine,
        skip_step_export=bool(args.skip_step_export),
    )
    outcome = InverseOutcome(
        success=outcome.success,
        feasible=outcome.feasible,
        message=outcome.message,
        total_wall_time_s=outcome.total_wall_time_s,
        baseline_eval_wall_time_s=outcome.baseline_eval_wall_time_s,
        nfev=outcome.nfev,
        nit=outcome.nit,
        equivalent_analysis_calls=outcome.equivalent_analysis_calls,
        production_analysis_calls=outcome.production_analysis_calls,
        unique_evaluations=outcome.unique_evaluations,
        cache_hits=outcome.cache_hits,
        feasible_count=outcome.feasible_count,
        baseline=outcome.baseline,
        selected=outcome.selected,
        local_refine=outcome.local_refine,
        manufacturing_limit_source=outcome.manufacturing_limit_source,
        max_jig_vertical_prebend_limit_m=outcome.max_jig_vertical_prebend_limit_m,
        max_jig_vertical_curvature_limit_per_m=outcome.max_jig_vertical_curvature_limit_per_m,
        artifacts=artifacts,
    )

    report_path = output_dir / "direct_dual_beam_inverse_design_report.txt"
    report_path.write_text(
        build_report_text(
            config_path=config_path,
            design_report=design_report,
            cruise_aoa_deg=cruise_aoa_deg,
            map_config=map_config,
            outcome=outcome,
        ),
        encoding="utf-8",
    )

    json_path = output_dir / "direct_dual_beam_inverse_design_summary.json"
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

    print("Frozen-load aeroelastic inverse design MVP complete.")
    print(f"  Config              : {config_path}")
    print(f"  Design report       : {design_report}")
    print(f"  Report              : {report_path}")
    print(f"  Summary JSON        : {json_path}")
    print(f"  Feasible            : {outcome.feasible}")
    print(f"  Total mass          : {outcome.selected.total_structural_mass_kg:.3f} kg")
    print(f"  Target error max    : {_mm(outcome.selected.target_shape_error_max_m):.6f} mm")
    print(f"  Jig clearance min   : {_mm(outcome.selected.jig_ground_clearance_min_m):.3f} mm")
    if outcome.artifacts is not None:
        print(f"  Target shape CSV    : {outcome.artifacts.target_shape_csv}")
        print(f"  Jig shape CSV       : {outcome.artifacts.jig_shape_csv}")
        print(f"  Jig STEP            : {outcome.artifacts.jig_step_path or 'not written'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
