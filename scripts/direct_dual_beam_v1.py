#!/usr/bin/env python3
"""Reduced direct dual-beam optimizer V1.

This experimental path keeps the production equivalent-beam optimizer unchanged.
It uses an equivalent-beam optimum only as a seed, then optimizes a small set of
physics-informed dual-beam scale variables against internal dual-beam metrics.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from itertools import product
from pathlib import Path
import sys
from typing import Iterable

import numpy as np
from scipy.optimize import minimize

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import SparOptimizer
from hpa_mdo.structure.dual_beam_analysis import run_dual_beam_analysis
from scripts.ansys_crossval import _select_cruise_loads

import scripts.dual_beam_refinement as dbr


SCALE_NAMES = (
    "main_s1_4_radius_scale",
    "main_s5_6_radius_scale",
    "rear_radius_scale",
    "wall_thickness_scale",
)


@dataclass(frozen=True)
class ReducedDirectOutcome:
    success: bool
    message: str
    warm: dbr.DualBeamCandidate
    refined: dbr.DualBeamCandidate
    targets: dbr.RefinementTargets
    scales: np.ndarray
    objective_mass_kg: float
    nfev: int
    nit: int
    coarse_evaluations: int
    coarse_feasible: int
    local_evaluations: int
    best_violation: float


def _parse_grid(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Grid specification must contain at least one float.")
    return values


def _main_s1_4_slice(n_seg: int) -> slice:
    return slice(0, min(4, n_seg))


def _main_s5_6_slice(n_seg: int) -> slice:
    return slice(min(4, n_seg), n_seg)


def design_from_reduced_scales(
    *,
    warm: dbr.DualBeamCandidate,
    scales: np.ndarray,
    cfg,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Map the 4D V1 scale vector to full segment design variables."""
    s = np.asarray(scales, dtype=float).reshape(4)
    n_seg = int(warm.main_t_seg_m.size)

    main_t = np.asarray(warm.main_t_seg_m, dtype=float).copy() * s[3]
    rear_t = np.asarray(warm.rear_t_seg_m, dtype=float).copy() * s[3]
    main_r = np.asarray(warm.main_r_seg_m, dtype=float).copy()
    rear_r = np.asarray(warm.rear_r_seg_m, dtype=float).copy()

    main_r[_main_s1_4_slice(n_seg)] *= s[0]
    main_r[_main_s5_6_slice(n_seg)] *= s[1]
    rear_r *= s[2]

    solver = cfg.solver
    main_t = np.clip(
        main_t,
        float(cfg.main_spar.min_wall_thickness),
        float(solver.max_wall_thickness_m),
    )
    rear_t = np.clip(
        rear_t,
        float(cfg.rear_spar.min_wall_thickness),
        float(solver.max_wall_thickness_m),
    )
    main_r = np.clip(main_r, float(solver.min_radius_m), float(solver.max_radius_m))
    rear_r = np.clip(rear_r, float(solver.min_radius_m), float(solver.max_radius_m))

    return main_t, main_r, rear_t, rear_r


def _scale_to_candidate(
    *,
    evaluator: dbr._DualBeamEvaluator,
    warm: dbr.DualBeamCandidate,
    scales: np.ndarray,
    cfg,
) -> dbr.DualBeamCandidate:
    main_t, main_r, rear_t, rear_r = design_from_reduced_scales(
        warm=warm,
        scales=np.asarray(scales, dtype=float),
        cfg=cfg,
    )
    return evaluator.evaluate(evaluator.pack(main_t, main_r, rear_t, rear_r))


def reduced_candidate_margins(
    *,
    cand: dbr.DualBeamCandidate,
    cfg,
    targets: dbr.RefinementTargets,
) -> dict[str, np.ndarray | float]:
    """Return V1 feasibility margins, including taper constraints omitted by hybrid."""
    margins = dict(dbr._candidate_margins(cand=cand, cfg=cfg, targets=targets))
    max_step = float(cfg.solver.max_thickness_step_m)

    margins["main_radius_taper"] = cand.main_r_seg_m[:-1] - cand.main_r_seg_m[1:]
    margins["rear_radius_taper"] = cand.rear_r_seg_m[:-1] - cand.rear_r_seg_m[1:]
    margins["main_thickness_step"] = max_step - np.abs(np.diff(cand.main_t_seg_m))
    margins["rear_thickness_step"] = max_step - np.abs(np.diff(cand.rear_t_seg_m))
    return margins


def _is_reduced_feasible(
    margins: dict[str, np.ndarray | float],
    *,
    tol: float = 1e-7,
) -> bool:
    return dbr._is_feasible(margins, tol=tol)


def _violation_score(margins: dict[str, np.ndarray | float]) -> float:
    score = 0.0
    for value in margins.values():
        arr = np.asarray(value, dtype=float).reshape(-1)
        if arr.size == 0:
            continue
        finite = np.all(np.isfinite(arr))
        if not finite:
            return float("inf")
        score += float(np.sum(np.maximum(-arr, 0.0) ** 2))
    return score


def build_targets_from_warm(
    *,
    warm: dbr.DualBeamCandidate,
    tip_improve_frac: float,
    max_uz_improve_frac: float,
    rear_main_tip_ratio_slack: float,
    mass_cap_frac: float,
) -> dbr.RefinementTargets:
    """Build default V1 targets from the equivalent-seeded dual-beam response."""
    return dbr.RefinementTargets(
        tip_main_limit_m=warm.dual_tip_main_m * (1.0 - float(tip_improve_frac)),
        max_uz_limit_m=warm.dual_max_uz_m * (1.0 - float(max_uz_improve_frac)),
        rear_main_tip_ratio_limit=warm.rear_main_tip_ratio
        + float(rear_main_tip_ratio_slack),
        mass_cap_kg=warm.dual_mass_kg * (1.0 + float(mass_cap_frac)),
    )


def _constraint_functions(
    *,
    evaluate_scales,
    cfg,
    targets: dbr.RefinementTargets,
    lb: np.ndarray,
    ub: np.ndarray,
) -> list[dict]:
    constraints: list[dict] = []

    for i in range(lb.size):
        constraints.append({"type": "ineq", "fun": lambda x, ii=i: x[ii] - lb[ii]})
        constraints.append({"type": "ineq", "fun": lambda x, ii=i: ub[ii] - x[ii]})

    probe = evaluate_scales(lb)
    probe_margins = reduced_candidate_margins(cand=probe, cfg=cfg, targets=targets)

    def _margin_value(name: str, idx: int | None = None):
        if idx is None:
            return lambda x: float(
                np.asarray(
                    reduced_candidate_margins(
                        cand=evaluate_scales(x),
                        cfg=cfg,
                        targets=targets,
                    )[name],
                    dtype=float,
                ).item()
            )
        return lambda x: float(
            np.asarray(
                reduced_candidate_margins(
                    cand=evaluate_scales(x),
                    cfg=cfg,
                    targets=targets,
                )[name],
                dtype=float,
            ).reshape(-1)[idx]
        )

    for name, value in probe_margins.items():
        arr = np.asarray(value, dtype=float).reshape(-1)
        if arr.size == 1:
            constraints.append({"type": "ineq", "fun": _margin_value(name)})
        else:
            for idx in range(arr.size):
                constraints.append({"type": "ineq", "fun": _margin_value(name, idx)})

    return constraints


def optimize_reduced_direct_dual_beam_v1(
    *,
    cfg,
    optimizer: SparOptimizer,
    aircraft,
    mat_db: MaterialDB,
    export_loads: dict,
    warm: dbr.DualBeamCandidate,
    targets: dbr.RefinementTargets,
    main_s1_4_grid: Iterable[float] = (1.0, 1.025, 1.05, 1.075, 1.10, 1.125),
    main_s5_6_grid: Iterable[float] = (1.0, 1.025, 1.05, 1.075, 1.10),
    rear_grid: Iterable[float] = (1.0, 1.025, 1.05, 1.075, 1.10),
    thickness_grid: Iterable[float] = (1.0,),
    scale_lower: Iterable[float] = (1.0, 1.0, 1.0, 1.0),
    scale_upper: Iterable[float] = (1.14, 1.14, 1.14, 1.08),
    cobyla_maxiter: int = 260,
    cobyla_rhobeg: float = 0.025,
    run_local_refine: bool = True,
) -> ReducedDirectOutcome:
    """Run reduced V1 direct dual-beam optimization."""
    evaluator = dbr._DualBeamEvaluator(
        cfg=cfg,
        optimizer=optimizer,
        aircraft=aircraft,
        mat_db=mat_db,
        export_loads=export_loads,
        n_seg=warm.main_t_seg_m.size,
    )

    lb = np.asarray(tuple(scale_lower), dtype=float)
    ub = np.asarray(tuple(scale_upper), dtype=float)
    if lb.shape != (4,) or ub.shape != (4,):
        raise ValueError("scale_lower and scale_upper must each contain four values.")
    if np.any(ub <= lb):
        raise ValueError("Every scale upper bound must be greater than lower bound.")

    best_feasible: tuple[float, np.ndarray, dbr.DualBeamCandidate] | None = None
    best_any: tuple[float, float, np.ndarray, dbr.DualBeamCandidate] | None = None
    coarse_evals = 0
    coarse_feasible = 0

    def _consider(scales: np.ndarray, cand: dbr.DualBeamCandidate) -> None:
        nonlocal best_feasible, best_any, coarse_feasible
        margins = reduced_candidate_margins(cand=cand, cfg=cfg, targets=targets)
        violation = _violation_score(margins)
        scales_copy = np.asarray(scales, dtype=float).copy()
        if best_any is None or (violation, cand.dual_mass_kg) < (
            best_any[0],
            best_any[1],
        ):
            best_any = (violation, cand.dual_mass_kg, scales_copy, cand)
        if _is_reduced_feasible(margins):
            if best_feasible is None or cand.dual_mass_kg < best_feasible[0]:
                best_feasible = (cand.dual_mass_kg, scales_copy, cand)

    def _evaluate_scales(scales: np.ndarray) -> dbr.DualBeamCandidate:
        scales_arr = np.asarray(scales, dtype=float)
        cand = _scale_to_candidate(
            evaluator=evaluator,
            warm=warm,
            scales=np.clip(scales_arr, lb, ub),
            cfg=cfg,
        )
        _consider(scales_arr, cand)
        return cand

    for scales_tuple in product(
        tuple(main_s1_4_grid),
        tuple(main_s5_6_grid),
        tuple(rear_grid),
        tuple(thickness_grid),
    ):
        scales = np.clip(np.asarray(scales_tuple, dtype=float), lb, ub)
        cand = _evaluate_scales(scales)
        coarse_evals += 1
        margins = reduced_candidate_margins(cand=cand, cfg=cfg, targets=targets)
        if _is_reduced_feasible(margins):
            coarse_feasible += 1

    if best_any is None:
        raise RuntimeError("Reduced direct grid search did not evaluate any candidates.")

    x0 = best_feasible[1].copy() if best_feasible is not None else best_any[2].copy()
    local_nfev = 0
    nit = -1
    local_message = "local refine skipped"

    if run_local_refine:
        objective_calls = {"n": 0}

        def _objective(scales: np.ndarray) -> float:
            objective_calls["n"] += 1
            cand = _evaluate_scales(scales)
            return float(cand.dual_mass_kg)

        constraints = _constraint_functions(
            evaluate_scales=_evaluate_scales,
            cfg=cfg,
            targets=targets,
            lb=lb,
            ub=ub,
        )
        opt = minimize(
            _objective,
            x0,
            method="COBYLA",
            constraints=constraints,
            options={
                "maxiter": int(cobyla_maxiter),
                "rhobeg": float(cobyla_rhobeg),
                "tol": 1e-6,
                "catol": 1e-6,
            },
        )
        local_nfev = int(getattr(opt, "nfev", objective_calls["n"]))
        nit = int(getattr(opt, "nit", -1))
        local_message = str(getattr(opt, "message", ""))
        cand = _evaluate_scales(np.asarray(opt.x, dtype=float))
        margins = reduced_candidate_margins(cand=cand, cfg=cfg, targets=targets)
        if _is_reduced_feasible(margins) and (
            best_feasible is None or cand.dual_mass_kg < best_feasible[0]
        ):
            best_feasible = (cand.dual_mass_kg, np.asarray(opt.x, dtype=float).copy(), cand)

    if best_feasible is not None:
        final_mass, final_scales, final_cand = best_feasible
        final_margins = reduced_candidate_margins(cand=final_cand, cfg=cfg, targets=targets)
        success = True
        best_violation = _violation_score(final_margins)
        message = (
            "reduced V1 feasible archive accepted"
            if local_message
            else "reduced V1 feasible grid point accepted"
        )
        if local_message:
            message += f"; local status: {local_message}"
    else:
        violation, final_mass, final_scales, final_cand = best_any
        success = False
        best_violation = float(violation)
        message = f"reduced V1 found no feasible point; best violation={violation:.6e}"

    nfev = len(getattr(evaluator, "_cache", {}))
    return ReducedDirectOutcome(
        success=bool(success),
        message=message,
        warm=warm,
        refined=final_cand,
        targets=targets,
        scales=np.asarray(final_scales, dtype=float).copy(),
        objective_mass_kg=float(final_mass),
        nfev=int(nfev),
        nit=int(nit),
        coarse_evaluations=int(coarse_evals),
        coarse_feasible=int(coarse_feasible),
        local_evaluations=int(local_nfev),
        best_violation=float(best_violation),
    )


def _candidate_lines(prefix: str, cand: dbr.DualBeamCandidate) -> list[str]:
    return [
        f"{prefix} eq mass (kg)                    : {cand.eq_mass_kg:.3f}",
        f"{prefix} eq tip deflection (mm)           : {cand.eq_tip_deflection_m * 1000.0:.3f}",
        f"{prefix} eq failure index                : {cand.eq_failure_index:.4f}",
        f"{prefix} eq buckling index               : {cand.eq_buckling_index:.4f}",
        f"{prefix} dual mass (kg)                  : {cand.dual_mass_kg:.3f}",
        f"{prefix} dual tip(main) (mm)             : {cand.dual_tip_main_m * 1000.0:.3f}",
        f"{prefix} dual max|UZ| (mm)               : {cand.dual_max_uz_m * 1000.0:.3f}",
        f"{prefix} dual tip(rear) (mm)             : {cand.dual_tip_rear_m * 1000.0:.3f}",
        f"{prefix} dual rear/main tip ratio        : {cand.rear_main_tip_ratio:.4f}",
        f"{prefix} dual max|UZ| location           : {cand.dual.max_vertical_spar} node {cand.dual.max_vertical_node}",
        f"{prefix} dual failure index              : {cand.dual.failure_index:.4f}",
    ]


def _fmt_array_mm(arr_m: np.ndarray) -> str:
    arr_mm = np.asarray(arr_m, dtype=float) * 1000.0
    return "[" + ", ".join(f"{v:.3f}" for v in arr_mm) + "]"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run reduced direct dual-beam optimizer V1."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
        help="Path to YAML configuration file.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/direct_dual_beam_v1",
        help="Output directory for the V1 report.",
    )
    parser.add_argument(
        "--optimizer-method",
        choices=("auto", "openmdao", "scipy"),
        default="auto",
        help="Equivalent optimizer method used only to create the seed design.",
    )
    parser.add_argument("--tip-improve-frac", type=float, default=0.13)
    parser.add_argument("--max-uz-improve-frac", type=float, default=0.12)
    parser.add_argument("--rear-main-tip-ratio-slack", type=float, default=0.02)
    parser.add_argument("--mass-cap-frac", type=float, default=0.08)
    parser.add_argument("--main-s1-4-grid", default="1.0,1.025,1.05,1.075,1.10,1.125")
    parser.add_argument("--main-s5-6-grid", default="1.0,1.025,1.05,1.075,1.10")
    parser.add_argument("--rear-grid", default="1.0,1.025,1.05,1.075,1.10")
    parser.add_argument("--thickness-grid", default="1.0")
    parser.add_argument("--scale-lower", default="1.0,1.0,1.0,1.0")
    parser.add_argument("--scale-upper", default="1.14,1.14,1.14,1.08")
    parser.add_argument("--cobyla-maxiter", type=int, default=260)
    parser.add_argument("--cobyla-rhobeg", type=float, default=0.025)
    parser.add_argument("--skip-local-refine", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    cfg_path = Path(args.config).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "direct_dual_beam_v1_report.txt"

    cfg = load_config(cfg_path)
    cfg.solver.rear_main_radius_ratio_min = 0.0
    aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    cruise_aoa_deg, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)

    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, mat_db)
    warm_eq = optimizer.optimize(method=args.optimizer_method)
    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
    x_warm = np.concatenate(
        [
            np.asarray(warm_eq.main_t_seg_mm, dtype=float) * 1e-3,
            np.asarray(warm_eq.main_r_seg_mm, dtype=float) * 1e-3,
            np.asarray(warm_eq.rear_t_seg_mm, dtype=float) * 1e-3,
            np.asarray(warm_eq.rear_r_seg_mm, dtype=float) * 1e-3,
        ]
    )
    warm_dual = run_dual_beam_analysis(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=warm_eq,
        export_loads=export_loads,
        materials_db=mat_db,
        bc_penalty=cfg.solver.fem_bc_penalty,
    )
    warm = dbr.DualBeamCandidate(
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
    targets = build_targets_from_warm(
        warm=warm,
        tip_improve_frac=float(args.tip_improve_frac),
        max_uz_improve_frac=float(args.max_uz_improve_frac),
        rear_main_tip_ratio_slack=float(args.rear_main_tip_ratio_slack),
        mass_cap_frac=float(args.mass_cap_frac),
    )

    outcome = optimize_reduced_direct_dual_beam_v1(
        cfg=cfg,
        optimizer=optimizer,
        aircraft=aircraft,
        mat_db=mat_db,
        export_loads=export_loads,
        warm=warm,
        targets=targets,
        main_s1_4_grid=_parse_grid(args.main_s1_4_grid),
        main_s5_6_grid=_parse_grid(args.main_s5_6_grid),
        rear_grid=_parse_grid(args.rear_grid),
        thickness_grid=_parse_grid(args.thickness_grid),
        scale_lower=_parse_grid(args.scale_lower),
        scale_upper=_parse_grid(args.scale_upper),
        cobyla_maxiter=int(args.cobyla_maxiter),
        cobyla_rhobeg=float(args.cobyla_rhobeg),
        run_local_refine=not bool(args.skip_local_refine),
    )

    w = outcome.warm
    r = outcome.refined
    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines: list[str] = []
    lines.append("=" * 96)
    lines.append("Reduced Direct Dual-Beam V1 Report (Experimental)")
    lines.append("=" * 96)
    lines.append(f"Generated      : {ts}")
    lines.append(f"Config         : {cfg_path.name}")
    lines.append(f"Cruise AoA     : {cruise_aoa_deg:.2f} deg")
    lines.append(f"Seed method    : {args.optimizer_method}")
    lines.append("Loop           : equivalent seed -> reduced direct dual-beam feasible search")
    lines.append("ANSYS in loop  : disabled")
    lines.append("")
    lines.append("Reduced design variables:")
    for name, value in zip(SCALE_NAMES, outcome.scales):
        lines.append(f"  {name:32s}: {float(value):.6f}")
    lines.append("")
    lines.append("Targets:")
    lines.append(f"  tip(main) limit (mm)             : {outcome.targets.tip_main_limit_m * 1000.0:.3f}")
    lines.append(f"  max |UZ| limit (mm)              : {outcome.targets.max_uz_limit_m * 1000.0:.3f}")
    lines.append(f"  rear/main tip ratio limit        : {outcome.targets.rear_main_tip_ratio_limit:.4f}")
    lines.append(f"  mass cap (kg)                    : {outcome.targets.mass_cap_kg:.3f}")
    lines.append("")
    lines.extend(_candidate_lines("Warm", w))
    lines.append("")
    lines.extend(_candidate_lines("V1", r))
    lines.append("")
    lines.append("Delta (V1 - Warm):")
    lines.append(f"  dual mass delta (kg)             : {r.dual_mass_kg - w.dual_mass_kg:+.3f}")
    lines.append(
        f"  dual tip(main) delta (mm)        : {(r.dual_tip_main_m - w.dual_tip_main_m) * 1000.0:+.3f}"
    )
    lines.append(
        f"  dual max|UZ| delta (mm)          : {(r.dual_max_uz_m - w.dual_max_uz_m) * 1000.0:+.3f}"
    )
    lines.append(
        f"  dual tip(rear) delta (mm)        : {(r.dual_tip_rear_m - w.dual_tip_rear_m) * 1000.0:+.3f}"
    )
    lines.append(
        f"  rear/main tip ratio delta        : {r.rear_main_tip_ratio - w.rear_main_tip_ratio:+.4f}"
    )
    lines.append("")
    lines.append("Design variable comparison (segment values in mm):")
    lines.append(f"  Warm main_t                      : {_fmt_array_mm(w.main_t_seg_m)}")
    lines.append(f"  V1 main_t                        : {_fmt_array_mm(r.main_t_seg_m)}")
    lines.append(f"  Warm main_r                      : {_fmt_array_mm(w.main_r_seg_m)}")
    lines.append(f"  V1 main_r                        : {_fmt_array_mm(r.main_r_seg_m)}")
    lines.append(f"  Warm rear_t                      : {_fmt_array_mm(w.rear_t_seg_m)}")
    lines.append(f"  V1 rear_t                        : {_fmt_array_mm(r.rear_t_seg_m)}")
    lines.append(f"  Warm rear_r                      : {_fmt_array_mm(w.rear_r_seg_m)}")
    lines.append(f"  V1 rear_r                        : {_fmt_array_mm(r.rear_r_seg_m)}")
    lines.append("")
    margins = reduced_candidate_margins(cand=r, cfg=cfg, targets=outcome.targets)
    lines.append("Constraint margin minima (>= 0 means satisfied):")
    for key, value in margins.items():
        arr = np.asarray(value, dtype=float).reshape(-1)
        lines.append(f"  {key:32s}: {float(np.min(arr)):+.6e}")
    lines.append("")
    lines.append("Solver status:")
    lines.append(f"  success                          : {outcome.success}")
    lines.append(f"  message                          : {outcome.message}")
    lines.append(f"  objective mass (kg)              : {outcome.objective_mass_kg:.3f}")
    lines.append(f"  unique analysis evaluations      : {outcome.nfev}")
    lines.append(f"  coarse evaluations               : {outcome.coarse_evaluations}")
    lines.append(f"  coarse feasible                  : {outcome.coarse_feasible}")
    lines.append(f"  local evaluations                : {outcome.local_evaluations}")
    lines.append(f"  iterations                       : {outcome.nit}")
    lines.append(f"  best violation score             : {outcome.best_violation:.6e}")
    lines.append("")
    lines.append(
        "Note: V1 intentionally uses a reduced, taper-preserving design space. "
        "It is an experimental architecture-decision path, not a production default."
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("Reduced direct dual-beam V1 complete.")
    print(f"  Success : {outcome.success}")
    print(f"  Mass    : {r.dual_mass_kg:.3f} kg")
    print(f"  Max |UZ|: {r.dual_max_uz_m * 1000.0:.3f} mm")
    print(f"  Report  : {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
