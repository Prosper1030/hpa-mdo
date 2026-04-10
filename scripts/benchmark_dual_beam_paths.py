#!/usr/bin/env python3
"""Baseline benchmark for equivalent/hybrid/direct dual-beam optimization paths.

This script is intentionally experimental and isolated from production defaults.
It compares three optimization paths on one baseline case:

1) equivalent-beam optimizer (current production path)
2) hybrid (equivalent warm start + dual-beam local refinement)
3) direct dual-beam optimizer (experimental, no equivalent warm start)
"""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
from scipy.optimize import minimize

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import SparOptimizer
from hpa_mdo.structure.dual_beam_analysis import DualBeamAnalysisResult, run_dual_beam_analysis
from scripts.ansys_crossval import _select_cruise_loads

import scripts.dual_beam_refinement as dbr


@dataclass(frozen=True)
class PathMetrics:
    path: str
    wall_time_s: float
    success: bool
    feasible: bool
    message: str
    eq_mass_kg: float
    dual_mass_kg: float
    tip_main_m: float
    max_uz_m: float
    rear_tip_m: float
    rear_main_tip_ratio: float
    optimizer_iterations: int | None
    function_evaluations: int | None
    analysis_calls_eq: int | None
    analysis_calls_dual: int | None
    run_model_calls: int | None


@dataclass(frozen=True)
class BenchmarkSummary:
    generated_at: str
    config: str
    optimizer_method: str
    direct_maxiter: int
    direct_rhobeg: float
    metrics: list[PathMetrics]


@contextmanager
def _count_prob_run_model_calls(prob) -> dict[str, int]:
    counter = {"n": 0}
    orig_run_model = prob.run_model

    def _wrapped_run_model(*args, **kwargs):
        counter["n"] += 1
        return orig_run_model(*args, **kwargs)

    prob.run_model = _wrapped_run_model
    try:
        yield counter
    finally:
        prob.run_model = orig_run_model


@contextmanager
def _count_optimizer_analyze_calls(optimizer: SparOptimizer) -> dict[str, int]:
    counter = {"n": 0}
    orig_analyze = optimizer.analyze

    def _wrapped_analyze(*args, **kwargs):
        counter["n"] += 1
        return orig_analyze(*args, **kwargs)

    optimizer.analyze = _wrapped_analyze  # type: ignore[method-assign]
    try:
        yield counter
    finally:
        optimizer.analyze = orig_analyze  # type: ignore[method-assign]


@contextmanager
def _count_dbr_dual_analysis_calls() -> dict[str, int]:
    counter = {"n": 0}
    orig_func = dbr.run_dual_beam_analysis

    def _wrapped_run_dual_beam_analysis(*args, **kwargs):
        counter["n"] += 1
        return orig_func(*args, **kwargs)

    dbr.run_dual_beam_analysis = _wrapped_run_dual_beam_analysis  # type: ignore[assignment]
    try:
        yield counter
    finally:
        dbr.run_dual_beam_analysis = orig_func  # type: ignore[assignment]


def _extract_driver_counts(prob) -> tuple[int | None, int | None]:
    """Best-effort extraction of optimizer iterations / function eval counts."""
    driver = getattr(prob, "driver", None)
    if driver is None:
        return None, None

    nit: int | None = None
    nfev: int | None = None

    for source in (driver, getattr(driver, "result", None), getattr(driver, "opt_result", None)):
        if source is None:
            continue
        for key in ("iter_count", "nit", "iterations"):
            val = getattr(source, key, None)
            if val is not None:
                try:
                    nit = int(val)
                except Exception:
                    pass
                break
        for key in ("nfev", "func_evals", "model_evals"):
            val = getattr(source, key, None)
            if val is not None:
                try:
                    nfev = int(val)
                except Exception:
                    pass
                break

    return nit, nfev


def _dual_metrics(dual: DualBeamAnalysisResult) -> tuple[float, float, float, float]:
    tip_main = float(abs(dual.tip_deflection_main_m))
    max_uz = float(abs(dual.max_vertical_displacement_m))
    rear_tip = float(abs(dual.tip_deflection_rear_m))
    ratio = rear_tip / max(tip_main, 1e-12)
    return tip_main, max_uz, rear_tip, ratio


def _is_eq_feasible(*, eq_result, cfg) -> bool:
    return bool(
        eq_result.failure_index <= 0.01
        and eq_result.buckling_index <= 0.01
        and eq_result.twist_max_deg <= float(cfg.wing.max_tip_twist_deg) * 1.02
        and (
            cfg.wing.max_tip_deflection_m is None
            or eq_result.tip_deflection_m <= float(cfg.wing.max_tip_deflection_m) * 1.02
        )
    )


def _build_global_bounds(cfg, n_seg: int) -> tuple[np.ndarray, np.ndarray]:
    min_t_main = float(cfg.main_spar.min_wall_thickness)
    min_t_rear = float(cfg.rear_spar.min_wall_thickness)
    max_t = float(cfg.solver.max_wall_thickness_m)
    min_r = float(cfg.solver.min_radius_m)
    max_r = float(cfg.solver.max_radius_m)

    lb = np.concatenate(
        [
            np.full(n_seg, min_t_main, dtype=float),
            np.full(n_seg, min_r, dtype=float),
            np.full(n_seg, min_t_rear, dtype=float),
            np.full(n_seg, min_r, dtype=float),
        ]
    )
    ub = np.concatenate(
        [
            np.full(n_seg, max_t, dtype=float),
            np.full(n_seg, max_r, dtype=float),
            np.full(n_seg, max_t, dtype=float),
            np.full(n_seg, max_r, dtype=float),
        ]
    )
    return lb, ub


def _initial_design_vector(optimizer: SparOptimizer, n_seg: int) -> np.ndarray:
    prob = optimizer._prob
    return np.concatenate(
        [
            np.asarray(prob.get_val("struct.seg_mapper.main_t_seg", units="m"), dtype=float).reshape(n_seg),
            np.asarray(prob.get_val("struct.seg_mapper.main_r_seg", units="m"), dtype=float).reshape(n_seg),
            np.asarray(prob.get_val("struct.seg_mapper.rear_t_seg", units="m"), dtype=float).reshape(n_seg),
            np.asarray(prob.get_val("struct.seg_mapper.rear_r_seg", units="m"), dtype=float).reshape(n_seg),
        ]
    )


def _build_context(cfg_path: Path):
    cfg = load_config(cfg_path)
    aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()

    cruise_aoa_deg, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)
    return cfg, aircraft, mat_db, cruise_aoa_deg, mapped_loads, export_loads


def _run_equivalent_path(
    *,
    cfg,
    aircraft,
    mat_db,
    mapped_loads,
    export_loads,
    optimizer_method: str,
) -> PathMetrics:
    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, mat_db)

    with _count_prob_run_model_calls(optimizer._prob) as run_model_counter:
        t0 = perf_counter()
        eq_result = optimizer.optimize(method=optimizer_method)
        wall_s = perf_counter() - t0

    dual = run_dual_beam_analysis(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=eq_result,
        export_loads=export_loads,
        materials_db=mat_db,
        bc_penalty=cfg.solver.fem_bc_penalty,
    )

    nit, nfev = _extract_driver_counts(optimizer._prob)
    tip_main, max_uz, rear_tip, ratio = _dual_metrics(dual)
    feasible = _is_eq_feasible(eq_result=eq_result, cfg=cfg)
    return PathMetrics(
        path="equivalent",
        wall_time_s=float(wall_s),
        success=bool(eq_result.success),
        feasible=bool(feasible),
        message=str(eq_result.message),
        eq_mass_kg=float(eq_result.spar_mass_full_kg),
        dual_mass_kg=float(dual.spar_mass_full_kg),
        tip_main_m=tip_main,
        max_uz_m=max_uz,
        rear_tip_m=rear_tip,
        rear_main_tip_ratio=ratio,
        optimizer_iterations=nit,
        function_evaluations=nfev,
        analysis_calls_eq=None,
        analysis_calls_dual=1,
        run_model_calls=int(run_model_counter["n"]),
    )


def _run_hybrid_path(
    *,
    cfg,
    aircraft,
    mat_db,
    mapped_loads,
    export_loads,
    optimizer_method: str,
    radius_scale: float,
    thickness_scale: float,
    tip_improve_frac: float,
    max_uz_improve_frac: float,
    rear_main_tip_ratio_improve_frac: float,
    rear_main_tip_ratio_slack: float,
    mass_cap_frac: float,
    cobyla_maxiter: int,
    cobyla_rhobeg: float,
) -> PathMetrics:
    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, mat_db)
    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))

    with _count_prob_run_model_calls(optimizer._prob) as run_model_counter, _count_optimizer_analyze_calls(
        optimizer
    ) as analyze_counter, _count_dbr_dual_analysis_calls() as dual_counter:
        t0 = perf_counter()

        warm_eq = optimizer.optimize(method=optimizer_method)
        x_warm = np.concatenate(
            [
                np.asarray(warm_eq.main_t_seg_mm, dtype=float) * 1e-3,
                np.asarray(warm_eq.main_r_seg_mm, dtype=float) * 1e-3,
                np.asarray(warm_eq.rear_t_seg_mm, dtype=float) * 1e-3,
                np.asarray(warm_eq.rear_r_seg_mm, dtype=float) * 1e-3,
            ]
        )
        if x_warm.size != 4 * n_seg:
            raise RuntimeError("Hybrid path requires dual-spar design variables.")

        warm_dual = dbr.run_dual_beam_analysis(
            cfg=cfg,
            aircraft=aircraft,
            opt_result=warm_eq,
            export_loads=export_loads,
            materials_db=mat_db,
            bc_penalty=cfg.solver.fem_bc_penalty,
        )
        warm_cand = dbr.DualBeamCandidate(
            x=x_warm.copy(),
            main_t_seg_m=x_warm[:n_seg].copy(),
            main_r_seg_m=x_warm[n_seg : 2 * n_seg].copy(),
            rear_t_seg_m=x_warm[2 * n_seg : 3 * n_seg].copy(),
            rear_r_seg_m=x_warm[3 * n_seg : 4 * n_seg].copy(),
            eq_mass_kg=float(warm_eq.spar_mass_full_kg),
            eq_tip_deflection_m=float(abs(warm_eq.tip_deflection_m)),
            eq_failure_index=float(warm_eq.failure_index),
            eq_buckling_index=float(warm_eq.buckling_index),
            dual=warm_dual,
        )

        outcome = dbr.refine_with_dual_beam(
            cfg=cfg,
            optimizer=optimizer,
            aircraft=aircraft,
            mat_db=mat_db,
            export_loads=export_loads,
            warm=warm_cand,
            radius_scale=float(radius_scale),
            thickness_scale=float(thickness_scale),
            tip_improve_frac=float(tip_improve_frac),
            max_uz_improve_frac=float(max_uz_improve_frac),
            rear_main_tip_ratio_improve_frac=float(rear_main_tip_ratio_improve_frac),
            rear_main_tip_ratio_slack=float(rear_main_tip_ratio_slack),
            mass_cap_frac=float(mass_cap_frac),
            cobyla_maxiter=int(cobyla_maxiter),
            cobyla_rhobeg=float(cobyla_rhobeg),
        )

        refined = outcome.refined
        eq_result = optimizer.analyze(
            main_t_seg=refined.main_t_seg_m,
            main_r_seg=refined.main_r_seg_m,
            rear_t_seg=refined.rear_t_seg_m,
            rear_r_seg=refined.rear_r_seg_m,
        )
        wall_s = perf_counter() - t0

    tip_main, max_uz, rear_tip, ratio = _dual_metrics(refined.dual)
    feasible = bool(outcome.success) and _is_eq_feasible(eq_result=eq_result, cfg=cfg)

    return PathMetrics(
        path="hybrid",
        wall_time_s=float(wall_s),
        success=bool(outcome.success),
        feasible=bool(feasible),
        message=str(outcome.message),
        eq_mass_kg=float(eq_result.spar_mass_full_kg),
        dual_mass_kg=float(refined.dual_mass_kg),
        tip_main_m=tip_main,
        max_uz_m=max_uz,
        rear_tip_m=rear_tip,
        rear_main_tip_ratio=ratio,
        optimizer_iterations=int(outcome.nit) if outcome.nit >= 0 else None,
        function_evaluations=int(outcome.nfev),
        analysis_calls_eq=int(analyze_counter["n"]),
        analysis_calls_dual=int(dual_counter["n"]),
        run_model_calls=int(run_model_counter["n"]),
    )


def _run_direct_path(
    *,
    cfg,
    aircraft,
    mat_db,
    mapped_loads,
    export_loads,
    maxiter: int,
    rhobeg: float,
    ratio_limit: float,
    mass_cap_mult: float,
    include_eq_tip_limit: bool,
) -> PathMetrics:
    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, mat_db)
    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))

    evaluator = dbr._DualBeamEvaluator(
        cfg=cfg,
        optimizer=optimizer,
        aircraft=aircraft,
        mat_db=mat_db,
        export_loads=export_loads,
        n_seg=n_seg,
    )
    lb, ub = _build_global_bounds(cfg, n_seg)
    x0 = _initial_design_vector(optimizer, n_seg)

    warm = evaluator.evaluate(x0)
    defl_limit = float(cfg.wing.max_tip_deflection_m) if cfg.wing.max_tip_deflection_m is not None else warm.dual_tip_main_m * 10.0
    targets = dbr.RefinementTargets(
        tip_main_limit_m=float(defl_limit),
        max_uz_limit_m=float(defl_limit),
        rear_main_tip_ratio_limit=float(ratio_limit),
        mass_cap_kg=float(max(warm.dual_mass_kg, 1e-9) * max(mass_cap_mult, 1.0)),
    )
    constraints_cfg = cfg if include_eq_tip_limit else copy.deepcopy(cfg)
    if not include_eq_tip_limit:
        constraints_cfg.wing.max_tip_deflection_m = None

    constraints = dbr._build_cobyla_constraints(
        evaluator=evaluator,
        lb=lb,
        ub=ub,
        cfg=constraints_cfg,
        targets=targets,
    )

    objective_calls = {"n": 0}

    def _objective(x: np.ndarray) -> float:
        objective_calls["n"] += 1
        return float(evaluator.evaluate(x).dual_mass_kg)

    with _count_prob_run_model_calls(optimizer._prob) as run_model_counter, _count_optimizer_analyze_calls(
        optimizer
    ) as analyze_counter, _count_dbr_dual_analysis_calls() as dual_counter:
        t0 = perf_counter()
        opt = minimize(
            _objective,
            x0,
            method="COBYLA",
            constraints=constraints,
            options={
                "maxiter": int(maxiter),
                "rhobeg": float(rhobeg),
                "tol": 1e-6,
                "catol": 1e-6,
            },
        )
        cand = evaluator.evaluate(np.asarray(opt.x, dtype=float))
        eq_result = optimizer.analyze(
            main_t_seg=cand.main_t_seg_m,
            main_r_seg=cand.main_r_seg_m,
            rear_t_seg=cand.rear_t_seg_m,
            rear_r_seg=cand.rear_r_seg_m,
        )
        wall_s = perf_counter() - t0

    margins = dbr._candidate_margins(cand=cand, cfg=constraints_cfg, targets=targets)
    feasible = bool(dbr._is_feasible(margins)) and _is_eq_feasible(eq_result=eq_result, cfg=cfg)
    tip_main, max_uz, rear_tip, ratio = _dual_metrics(cand.dual)

    return PathMetrics(
        path="direct_dual_beam",
        wall_time_s=float(wall_s),
        success=bool(getattr(opt, "success", False)) and feasible,
        feasible=feasible,
        message=str(getattr(opt, "message", "")),
        eq_mass_kg=float(eq_result.spar_mass_full_kg),
        dual_mass_kg=float(cand.dual_mass_kg),
        tip_main_m=tip_main,
        max_uz_m=max_uz,
        rear_tip_m=rear_tip,
        rear_main_tip_ratio=ratio,
        optimizer_iterations=(int(getattr(opt, "nit")) if getattr(opt, "nit", None) is not None else None),
        function_evaluations=int(getattr(opt, "nfev", objective_calls["n"])),
        analysis_calls_eq=int(analyze_counter["n"]),
        analysis_calls_dual=int(dual_counter["n"]),
        run_model_calls=int(run_model_counter["n"]),
    )


def _format_metrics_table(metrics: list[PathMetrics]) -> str:
    lines: list[str] = []
    lines.append("=" * 118)
    lines.append("Baseline Benchmark: equivalent vs hybrid vs direct dual-beam")
    lines.append("=" * 118)
    lines.append(
        "path               wall[s]   success feasible  eq_mass[kg] dual_mass[kg]  tip_main[mm] max|UZ|[mm] rear_tip[mm] ratio    nfev   nit"
    )
    lines.append("-" * 118)
    for m in metrics:
        nfev_str = "-" if m.function_evaluations is None else str(int(m.function_evaluations))
        nit_str = "-" if m.optimizer_iterations is None else str(int(m.optimizer_iterations))
        lines.append(
            f"{m.path:18s} {m.wall_time_s:8.2f} {str(m.success):>8s} {str(m.feasible):>8s} "
            f"{m.eq_mass_kg:11.3f} {m.dual_mass_kg:12.3f} {m.tip_main_m*1000.0:12.3f} "
            f"{m.max_uz_m*1000.0:10.3f} {m.rear_tip_m*1000.0:11.3f} {m.rear_main_tip_ratio:7.4f} {nfev_str:>6s} {nit_str:>5s}"
        )
    lines.append("=" * 118)
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run baseline benchmark for equivalent / hybrid / direct dual-beam optimization paths."
        )
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
        help="Path to YAML configuration file.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/dual_beam_path_benchmark",
        help="Directory for benchmark report and JSON summary.",
    )
    parser.add_argument(
        "--optimizer-method",
        choices=("auto", "openmdao", "scipy"),
        default="auto",
        help="Equivalent optimizer method used by equivalent + hybrid warm start.",
    )
    parser.add_argument(
        "--direct-maxiter",
        type=int,
        default=900,
        help="Maximum COBYLA iterations for direct dual-beam path.",
    )
    parser.add_argument(
        "--direct-rhobeg",
        type=float,
        default=1.0e-3,
        help="Initial COBYLA trust region for direct dual-beam path.",
    )
    parser.add_argument(
        "--direct-ratio-limit",
        type=float,
        default=10.0,
        help="Rear/main tip ratio upper bound used in direct-path constraints (large=effectively inactive).",
    )
    parser.add_argument(
        "--direct-mass-cap-mult",
        type=float,
        default=20.0,
        help="Direct-path mass cap multiplier relative to initial dual-beam mass.",
    )
    parser.add_argument(
        "--direct-include-eq-tip-limit",
        action="store_true",
        help="Also enforce equivalent-beam tip-deflection limit in direct-path constraints.",
    )
    parser.add_argument(
        "--hybrid-radius-scale",
        type=float,
        default=0.20,
        help="Hybrid local radius search scale around equivalent warm start.",
    )
    parser.add_argument(
        "--hybrid-thickness-scale",
        type=float,
        default=0.25,
        help="Hybrid local thickness search scale around equivalent warm start.",
    )
    parser.add_argument(
        "--hybrid-tip-improve-frac",
        type=float,
        default=0.03,
        help="Hybrid target dual tip(main) improvement fraction.",
    )
    parser.add_argument(
        "--hybrid-max-uz-improve-frac",
        type=float,
        default=0.08,
        help="Hybrid target dual max|UZ| improvement fraction.",
    )
    parser.add_argument(
        "--hybrid-rear-main-tip-ratio-improve-frac",
        type=float,
        default=0.0,
        help="Hybrid target rear/main tip ratio improvement fraction.",
    )
    parser.add_argument(
        "--hybrid-rear-main-tip-ratio-slack",
        type=float,
        default=0.012,
        help="Hybrid rear/main tip ratio absolute slack.",
    )
    parser.add_argument(
        "--hybrid-mass-cap-frac",
        type=float,
        default=0.08,
        help="Hybrid allowable dual-mass growth fraction during refinement.",
    )
    parser.add_argument(
        "--hybrid-cobyla-maxiter",
        type=int,
        default=900,
        help="Hybrid COBYLA max iterations per attempt.",
    )
    parser.add_argument(
        "--hybrid-cobyla-rhobeg",
        type=float,
        default=1.0e-3,
        help="Hybrid COBYLA initial trust region.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    cfg_path = Path(args.config).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "benchmark_report.txt"
    json_path = output_dir / "benchmark_summary.json"

    cfg, aircraft, mat_db, cruise_aoa_deg, mapped_loads, export_loads = _build_context(cfg_path)

    metrics: list[PathMetrics] = []
    metrics.append(
        _run_equivalent_path(
            cfg=cfg,
            aircraft=aircraft,
            mat_db=mat_db,
            mapped_loads=mapped_loads,
            export_loads=export_loads,
            optimizer_method=args.optimizer_method,
        )
    )
    metrics.append(
        _run_hybrid_path(
            cfg=cfg,
            aircraft=aircraft,
            mat_db=mat_db,
            mapped_loads=mapped_loads,
            export_loads=export_loads,
            optimizer_method=args.optimizer_method,
            radius_scale=float(args.hybrid_radius_scale),
            thickness_scale=float(args.hybrid_thickness_scale),
            tip_improve_frac=float(args.hybrid_tip_improve_frac),
            max_uz_improve_frac=float(args.hybrid_max_uz_improve_frac),
            rear_main_tip_ratio_improve_frac=float(args.hybrid_rear_main_tip_ratio_improve_frac),
            rear_main_tip_ratio_slack=float(args.hybrid_rear_main_tip_ratio_slack),
            mass_cap_frac=float(args.hybrid_mass_cap_frac),
            cobyla_maxiter=int(args.hybrid_cobyla_maxiter),
            cobyla_rhobeg=float(args.hybrid_cobyla_rhobeg),
        )
    )
    metrics.append(
        _run_direct_path(
            cfg=cfg,
            aircraft=aircraft,
            mat_db=mat_db,
            mapped_loads=mapped_loads,
            export_loads=export_loads,
            maxiter=int(args.direct_maxiter),
            rhobeg=float(args.direct_rhobeg),
            ratio_limit=float(args.direct_ratio_limit),
            mass_cap_mult=float(args.direct_mass_cap_mult),
            include_eq_tip_limit=bool(args.direct_include_eq_tip_limit),
        )
    )

    summary = BenchmarkSummary(
        generated_at=datetime.now().astimezone().isoformat(),
        config=str(cfg_path),
        optimizer_method=str(args.optimizer_method),
        direct_maxiter=int(args.direct_maxiter),
        direct_rhobeg=float(args.direct_rhobeg),
        metrics=metrics,
    )

    table = _format_metrics_table(metrics)
    ratio_lines = ["", "Runtime ratios:"]
    wall = {m.path: m.wall_time_s for m in metrics}
    if "equivalent" in wall and wall["equivalent"] > 0:
        ratio_lines.append(
            f"  hybrid / equivalent           : {wall['hybrid'] / wall['equivalent']:.3f}x"
        )
        ratio_lines.append(
            f"  direct_dual_beam / equivalent : {wall['direct_dual_beam'] / wall['equivalent']:.3f}x"
        )
    if "hybrid" in wall and wall["hybrid"] > 0:
        ratio_lines.append(
            f"  direct_dual_beam / hybrid     : {wall['direct_dual_beam'] / wall['hybrid']:.3f}x"
        )

    lines: list[str] = []
    lines.append(table)
    lines.append(f"Config       : {cfg_path}")
    lines.append(f"Cruise AoA   : {cruise_aoa_deg:.3f} deg")
    lines.append(f"Output dir   : {output_dir}")
    lines.extend(ratio_lines)
    report_text = "\n".join(lines) + "\n"

    report_path.write_text(report_text, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                **asdict(summary),
                "metrics": [asdict(m) for m in metrics],
                "runtime_ratios": {
                    "hybrid_over_equivalent": (
                        wall["hybrid"] / wall["equivalent"] if wall.get("equivalent", 0.0) > 0 else None
                    ),
                    "direct_over_equivalent": (
                        wall["direct_dual_beam"] / wall["equivalent"]
                        if wall.get("equivalent", 0.0) > 0
                        else None
                    ),
                    "direct_over_hybrid": (
                        wall["direct_dual_beam"] / wall["hybrid"] if wall.get("hybrid", 0.0) > 0 else None
                    ),
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(table)
    print(f"Config       : {cfg_path}")
    print(f"Cruise AoA   : {cruise_aoa_deg:.3f} deg")
    print(f"Report       : {report_path}")
    print(f"JSON summary : {json_path}")
    for ln in ratio_lines:
        if ln:
            print(ln)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
