#!/usr/bin/env python3
"""Experimental dual-beam local refinement path.

This workflow intentionally keeps the production equivalent-beam optimizer
unchanged. It adds a minimum viable refinement loop:

1) Run equivalent-beam optimization for a warm start.
2) Re-optimize locally using internal dual-beam analysis metrics.

ANSYS is intentionally excluded from the optimization loop.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
from typing import Callable

import numpy as np
from scipy.optimize import minimize

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import SparOptimizer
from hpa_mdo.structure.dual_beam_analysis import DualBeamAnalysisResult, run_dual_beam_analysis
from scripts.ansys_crossval import _select_cruise_loads, export_cross_validation_package_from_result


@dataclass(frozen=True)
class DualBeamCandidate:
    x: np.ndarray
    main_t_seg_m: np.ndarray
    main_r_seg_m: np.ndarray
    rear_t_seg_m: np.ndarray
    rear_r_seg_m: np.ndarray
    eq_mass_kg: float
    eq_tip_deflection_m: float
    eq_failure_index: float
    eq_buckling_index: float
    dual: DualBeamAnalysisResult

    @property
    def dual_tip_main_m(self) -> float:
        return float(abs(self.dual.tip_deflection_main_m))

    @property
    def dual_tip_rear_m(self) -> float:
        return float(abs(self.dual.tip_deflection_rear_m))

    @property
    def dual_max_uz_m(self) -> float:
        return float(abs(self.dual.max_vertical_displacement_m))

    @property
    def dual_mass_kg(self) -> float:
        return float(self.dual.spar_mass_full_kg)

    @property
    def rear_main_tip_ratio(self) -> float:
        return self.dual_tip_rear_m / max(self.dual_tip_main_m, 1e-12)


@dataclass(frozen=True)
class RefinementTargets:
    tip_main_limit_m: float
    max_uz_limit_m: float
    rear_main_tip_ratio_limit: float
    mass_cap_kg: float


@dataclass(frozen=True)
class RefinementOutcome:
    success: bool
    message: str
    attempt_scale: float
    objective_mass_kg: float
    nfev: int
    nit: int
    warm: DualBeamCandidate
    refined: DualBeamCandidate
    targets: RefinementTargets


class _DualBeamEvaluator:
    """Cached evaluator for dual-beam local refinement."""

    def __init__(
        self,
        *,
        cfg,
        optimizer: SparOptimizer,
        aircraft,
        mat_db: MaterialDB,
        export_loads: dict,
        n_seg: int,
    ):
        self.cfg = cfg
        self.optimizer = optimizer
        self.aircraft = aircraft
        self.mat_db = mat_db
        self.export_loads = export_loads
        self.n_seg = int(n_seg)
        self.rear_on = bool(cfg.rear_spar.enabled)
        self._cache: dict[tuple[float, ...], DualBeamCandidate] = {}

    def pack(
        self,
        main_t_seg_m: np.ndarray,
        main_r_seg_m: np.ndarray,
        rear_t_seg_m: np.ndarray,
        rear_r_seg_m: np.ndarray,
    ) -> np.ndarray:
        return np.concatenate(
            [
                np.asarray(main_t_seg_m, dtype=float),
                np.asarray(main_r_seg_m, dtype=float),
                np.asarray(rear_t_seg_m, dtype=float),
                np.asarray(rear_r_seg_m, dtype=float),
            ]
        )

    def _key(self, x: np.ndarray) -> tuple[float, ...]:
        return tuple(np.round(np.asarray(x, dtype=float), 10))

    def unpack(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        x_arr = np.asarray(x, dtype=float)
        n = self.n_seg
        main_t = x_arr[:n]
        main_r = x_arr[n : 2 * n]
        rear_t = x_arr[2 * n : 3 * n]
        rear_r = x_arr[3 * n : 4 * n]
        return main_t, main_r, rear_t, rear_r

    def evaluate(self, x: np.ndarray) -> DualBeamCandidate:
        x_arr = np.asarray(x, dtype=float)
        if not np.all(np.isfinite(x_arr)):
            raise ValueError("Non-finite design vector in dual-beam evaluator.")

        key = self._key(x_arr)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        main_t, main_r, rear_t, rear_r = self.unpack(x_arr)
        eq = self.optimizer.analyze(
            main_t_seg=main_t,
            main_r_seg=main_r,
            rear_t_seg=rear_t if self.rear_on else None,
            rear_r_seg=rear_r if self.rear_on else None,
        )
        dual = run_dual_beam_analysis(
            cfg=self.cfg,
            aircraft=self.aircraft,
            opt_result=eq,
            export_loads=self.export_loads,
            materials_db=self.mat_db,
            bc_penalty=self.cfg.solver.fem_bc_penalty,
        )

        cand = DualBeamCandidate(
            x=x_arr.copy(),
            main_t_seg_m=np.asarray(main_t, dtype=float).copy(),
            main_r_seg_m=np.asarray(main_r, dtype=float).copy(),
            rear_t_seg_m=np.asarray(rear_t, dtype=float).copy(),
            rear_r_seg_m=np.asarray(rear_r, dtype=float).copy(),
            eq_mass_kg=float(eq.spar_mass_full_kg),
            eq_tip_deflection_m=float(abs(eq.tip_deflection_m)),
            eq_failure_index=float(eq.failure_index),
            eq_buckling_index=float(eq.buckling_index),
            dual=dual,
        )
        self._cache[key] = cand
        return cand


def _build_bounds_from_warm_start(
    *,
    cfg,
    warm: DualBeamCandidate,
    radius_scale: float,
    thickness_scale: float,
) -> tuple[np.ndarray, np.ndarray]:
    n = warm.main_t_seg_m.size
    solver = cfg.solver
    min_t_main = float(cfg.main_spar.min_wall_thickness)
    min_t_rear = float(cfg.rear_spar.min_wall_thickness)
    max_t = float(solver.max_wall_thickness_m)
    min_r = float(solver.min_radius_m)
    max_r = float(solver.max_radius_m)

    lb = np.zeros(4 * n, dtype=float)
    ub = np.zeros(4 * n, dtype=float)

    def _scaled_bounds(x0: float, lo: float, hi: float, scale: float) -> tuple[float, float]:
        lo_local = max(lo, x0 * (1.0 - scale))
        hi_local = min(hi, x0 * (1.0 + scale))
        if hi_local < lo_local:
            lo_local, hi_local = lo, hi
        if hi_local - lo_local < 1e-9:
            hi_local = lo_local + 1e-9
        return lo_local, hi_local

    for i in range(n):
        lb[i], ub[i] = _scaled_bounds(
            float(warm.main_t_seg_m[i]), min_t_main, max_t, thickness_scale
        )
        lb[n + i], ub[n + i] = _scaled_bounds(
            float(warm.main_r_seg_m[i]), min_r, max_r, radius_scale
        )
        lb[2 * n + i], ub[2 * n + i] = _scaled_bounds(
            float(warm.rear_t_seg_m[i]), min_t_rear, max_t, thickness_scale
        )
        lb[3 * n + i], ub[3 * n + i] = _scaled_bounds(
            float(warm.rear_r_seg_m[i]), min_r, max_r, radius_scale
        )

    return lb, ub


def _candidate_margins(
    *,
    cand: DualBeamCandidate,
    cfg,
    targets: RefinementTargets,
) -> dict[str, np.ndarray | float]:
    eta = float(cfg.solver.max_thickness_to_radius_ratio)
    rear_min_inner = float(cfg.solver.rear_min_inner_radius_m)
    main_rear_dominance_margin = float(cfg.solver.main_spar_dominance_margin_m)
    max_tip_eq = cfg.wing.max_tip_deflection_m

    margins: dict[str, np.ndarray | float] = {
        "main_t_over_r": eta * cand.main_r_seg_m - cand.main_t_seg_m,
        "rear_t_over_r": eta * cand.rear_r_seg_m - cand.rear_t_seg_m,
        "rear_hollow": cand.rear_r_seg_m - cand.rear_t_seg_m - rear_min_inner,
        "main_rear_radius_dominance": (
            cand.main_r_seg_m - cand.rear_r_seg_m - main_rear_dominance_margin
        ),
        "dual_failure": -float(cand.dual.failure_index),
        "dual_tip_main": targets.tip_main_limit_m - cand.dual_tip_main_m,
        "dual_max_uz": targets.max_uz_limit_m - cand.dual_max_uz_m,
        "dual_rear_main_tip_ratio": targets.rear_main_tip_ratio_limit - cand.rear_main_tip_ratio,
        "dual_mass_cap": targets.mass_cap_kg - cand.dual_mass_kg,
        "eq_failure": -float(cand.eq_failure_index),
        "eq_buckling": -float(cand.eq_buckling_index),
    }
    if max_tip_eq is not None:
        margins["eq_tip_limit"] = float(max_tip_eq) - cand.eq_tip_deflection_m
    return margins


def _is_feasible(margins: dict[str, np.ndarray | float], tol: float = 1e-7) -> bool:
    for value in margins.values():
        arr = np.asarray(value, dtype=float).reshape(-1)
        if arr.size == 0:
            continue
        if float(np.min(arr)) < -tol:
            return False
    return True


def _build_cobyla_constraints(
    *,
    evaluator: _DualBeamEvaluator,
    lb: np.ndarray,
    ub: np.ndarray,
    cfg,
    targets: RefinementTargets,
) -> list[dict]:
    constraints: list[dict] = []

    for i in range(lb.size):
        constraints.append({"type": "ineq", "fun": lambda x, ii=i: x[ii] - lb[ii]})
        constraints.append({"type": "ineq", "fun": lambda x, ii=i: ub[ii] - x[ii]})

    def _scalar_margin(name: str, idx: int | None = None) -> Callable[[np.ndarray], float]:
        if idx is None:
            return lambda x: float(
                np.asarray(
                    _candidate_margins(
                        cand=evaluator.evaluate(x),
                        cfg=cfg,
                        targets=targets,
                    )[name],
                    dtype=float,
                ).item()
            )
        return lambda x: float(
            np.asarray(
                _candidate_margins(
                    cand=evaluator.evaluate(x),
                    cfg=cfg,
                    targets=targets,
                )[name],
                dtype=float,
            )[idx]
        )

    n = evaluator.n_seg
    for i in range(n):
        constraints.append({"type": "ineq", "fun": _scalar_margin("main_t_over_r", i)})
        constraints.append({"type": "ineq", "fun": _scalar_margin("rear_t_over_r", i)})
        constraints.append({"type": "ineq", "fun": _scalar_margin("rear_hollow", i)})
        constraints.append(
            {"type": "ineq", "fun": _scalar_margin("main_rear_radius_dominance", i)}
        )

    for name in (
        "dual_failure",
        "dual_tip_main",
        "dual_max_uz",
        "dual_rear_main_tip_ratio",
        "dual_mass_cap",
        "eq_failure",
        "eq_buckling",
    ):
        constraints.append({"type": "ineq", "fun": _scalar_margin(name)})

    if cfg.wing.max_tip_deflection_m is not None:
        constraints.append({"type": "ineq", "fun": _scalar_margin("eq_tip_limit")})

    return constraints


def refine_with_dual_beam(
    *,
    cfg,
    optimizer: SparOptimizer,
    aircraft,
    mat_db: MaterialDB,
    export_loads: dict,
    warm: DualBeamCandidate,
    radius_scale: float,
    thickness_scale: float,
    tip_improve_frac: float,
    max_uz_improve_frac: float,
    rear_main_tip_ratio_improve_frac: float,
    rear_main_tip_ratio_slack: float,
    mass_cap_frac: float,
    cobyla_maxiter: int,
    cobyla_rhobeg: float,
) -> RefinementOutcome:
    evaluator = _DualBeamEvaluator(
        cfg=cfg,
        optimizer=optimizer,
        aircraft=aircraft,
        mat_db=mat_db,
        export_loads=export_loads,
        n_seg=warm.main_t_seg_m.size,
    )
    lb, ub = _build_bounds_from_warm_start(
        cfg=cfg,
        warm=warm,
        radius_scale=radius_scale,
        thickness_scale=thickness_scale,
    )
    x0 = warm.x.copy()

    def _uniform_radius_scale_fallback(
        *,
        targets: RefinementTargets,
        attempt_scale: float,
    ) -> RefinementOutcome | None:
        scale_vals = np.linspace(1.0, 1.0 + max(radius_scale, 0.0), 9)
        min_r = float(cfg.solver.min_radius_m)
        max_r = float(cfg.solver.max_radius_m)
        best_cand: DualBeamCandidate | None = None
        n_eval = 0

        for s_main in scale_vals:
            for s_rear in scale_vals:
                main_r = np.clip(warm.main_r_seg_m * s_main, min_r, max_r)
                rear_r = np.clip(warm.rear_r_seg_m * s_rear, min_r, max_r)
                x = evaluator.pack(
                    warm.main_t_seg_m,
                    main_r,
                    warm.rear_t_seg_m,
                    rear_r,
                )
                cand = evaluator.evaluate(x)
                n_eval += 1
                margins = _candidate_margins(cand=cand, cfg=cfg, targets=targets)
                if not _is_feasible(margins):
                    continue
                if best_cand is None or cand.dual_mass_kg < best_cand.dual_mass_kg:
                    best_cand = cand

        if best_cand is None:
            return None
        return RefinementOutcome(
            success=True,
            message=(
                "COBYLA did not find a feasible point; "
                "accepted feasible uniform-radius fallback."
            ),
            attempt_scale=attempt_scale,
            objective_mass_kg=float(best_cand.dual_mass_kg),
            nfev=n_eval,
            nit=-1,
            warm=warm,
            refined=best_cand,
            targets=targets,
        )

    best: RefinementOutcome | None = None
    attempt_scales = (1.0, 0.7, 0.4, 0.2, 0.0)
    for scale in attempt_scales:
        targets = RefinementTargets(
            tip_main_limit_m=warm.dual_tip_main_m * (1.0 - tip_improve_frac * scale),
            max_uz_limit_m=warm.dual_max_uz_m * (1.0 - max_uz_improve_frac * scale),
            rear_main_tip_ratio_limit=warm.rear_main_tip_ratio * (
                1.0 - rear_main_tip_ratio_improve_frac * scale
            ) + rear_main_tip_ratio_slack,
            mass_cap_kg=warm.dual_mass_kg * (1.0 + mass_cap_frac),
        )
        constraints = _build_cobyla_constraints(
            evaluator=evaluator,
            lb=lb,
            ub=ub,
            cfg=cfg,
            targets=targets,
        )

        objective_calls = {"n": 0}

        def _objective(x: np.ndarray) -> float:
            objective_calls["n"] += 1
            cand = evaluator.evaluate(x)
            return float(cand.dual_mass_kg)

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
        cand = evaluator.evaluate(opt.x)
        margins = _candidate_margins(cand=cand, cfg=cfg, targets=targets)
        feasible = _is_feasible(margins)
        message = str(opt.message)

        outcome = RefinementOutcome(
            success=bool(feasible),
            message=message,
            attempt_scale=float(scale),
            objective_mass_kg=float(cand.dual_mass_kg),
            nfev=int(getattr(opt, "nfev", objective_calls["n"])),
            nit=int(getattr(opt, "nit", -1)),
            warm=warm,
            refined=cand,
            targets=targets,
        )
        best = outcome
        if feasible:
            return outcome

        fallback = _uniform_radius_scale_fallback(
            targets=targets,
            attempt_scale=float(scale),
        )
        if fallback is not None:
            return fallback

    assert best is not None
    return best


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run minimum-viable dual-beam local refinement: "
            "equivalent-beam warm start + internal dual-beam local re-optimization."
        )
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
        help="Path to YAML configuration file.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/blackcat_004_dual_beam_refinement",
        help="Output directory for the refinement report.",
    )
    parser.add_argument(
        "--optimizer-method",
        choices=("auto", "openmdao", "scipy"),
        default="auto",
        help="Method for warm-start equivalent-beam optimization.",
    )
    parser.add_argument(
        "--radius-scale",
        type=float,
        default=0.20,
        help="Local refinement search radius for spar radii (fraction around warm start).",
    )
    parser.add_argument(
        "--thickness-scale",
        type=float,
        default=0.25,
        help="Local refinement search radius for spar thickness (fraction around warm start).",
    )
    parser.add_argument(
        "--tip-improve-frac",
        type=float,
        default=0.03,
        help="Targeted dual-beam tip(main) improvement fraction vs warm start.",
    )
    parser.add_argument(
        "--max-uz-improve-frac",
        type=float,
        default=0.08,
        help="Targeted dual-beam max|UZ| improvement fraction vs warm start.",
    )
    parser.add_argument(
        "--rear-main-tip-ratio-improve-frac",
        type=float,
        default=0.0,
        help="Targeted dual-beam rear/main tip ratio improvement fraction vs warm start.",
    )
    parser.add_argument(
        "--rear-main-tip-ratio-slack",
        type=float,
        default=0.012,
        help="Absolute slack added to rear/main tip ratio constraint limit.",
    )
    parser.add_argument(
        "--mass-cap-frac",
        type=float,
        default=0.08,
        help="Upper bound on dual-beam mass growth during refinement.",
    )
    parser.add_argument(
        "--cobyla-maxiter",
        type=int,
        default=900,
        help="Maximum COBYLA iterations for each refinement attempt.",
    )
    parser.add_argument(
        "--cobyla-rhobeg",
        type=float,
        default=1.0e-3,
        help="Initial COBYLA trust region size in design-variable units [m].",
    )
    parser.add_argument(
        "--export-ansys-dual-spar",
        action="store_true",
        help=(
            "Export ANSYS dual-spar package for the final refined design. "
            "Writes spar_model.mac/.bdf, spar_data.csv, and crossval_report.txt."
        ),
    )
    parser.add_argument(
        "--ansys-subdir",
        default="ansys_refined",
        help=(
            "Subdirectory under --output-dir for refined-design ANSYS export "
            "when --export-ansys-dual-spar is enabled."
        ),
    )
    return parser


def _candidate_lines(prefix: str, cand: DualBeamCandidate) -> list[str]:
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


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    cfg_path = Path(args.config).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "dual_beam_refinement_report.txt"

    cfg = load_config(cfg_path)
    # Keep this experimental path independent from equivalent-beam guardrails.
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
    if x_warm.size != 4 * n_seg:
        raise RuntimeError("Dual-beam refinement requires dual-spar design variables.")

    warm_dual = run_dual_beam_analysis(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=warm_eq,
        export_loads=export_loads,
        materials_db=mat_db,
        bc_penalty=cfg.solver.fem_bc_penalty,
    )
    warm = DualBeamCandidate(
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

    outcome = refine_with_dual_beam(
        cfg=cfg,
        optimizer=optimizer,
        aircraft=aircraft,
        mat_db=mat_db,
        export_loads=export_loads,
        warm=warm,
        radius_scale=float(args.radius_scale),
        thickness_scale=float(args.thickness_scale),
        tip_improve_frac=float(args.tip_improve_frac),
        max_uz_improve_frac=float(args.max_uz_improve_frac),
        rear_main_tip_ratio_improve_frac=float(args.rear_main_tip_ratio_improve_frac),
        rear_main_tip_ratio_slack=float(args.rear_main_tip_ratio_slack),
        mass_cap_frac=float(args.mass_cap_frac),
        cobyla_maxiter=int(args.cobyla_maxiter),
        cobyla_rhobeg=float(args.cobyla_rhobeg),
    )

    w = outcome.warm
    r = outcome.refined
    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines: list[str] = []
    lines.append("=" * 96)
    lines.append("Dual-Beam Local Refinement Report (Experimental)")
    lines.append("=" * 96)
    lines.append(f"Generated      : {ts}")
    lines.append(f"Config         : {cfg_path.name}")
    lines.append(f"Cruise AoA     : {cruise_aoa_deg:.2f} deg")
    lines.append(f"Warm method    : {args.optimizer_method}")
    lines.append("Loop           : equivalent-beam warm start -> internal dual-beam local refinement")
    lines.append("ANSYS in loop  : disabled (analysis-only reference remains external)")
    lines.append("")
    lines.append("Refinement targets (active attempt):")
    lines.append(f"  attempt scale                    : {outcome.attempt_scale:.2f}")
    lines.append(f"  tip(main) limit (mm)             : {outcome.targets.tip_main_limit_m * 1000.0:.3f}")
    lines.append(f"  max |UZ| limit (mm)              : {outcome.targets.max_uz_limit_m * 1000.0:.3f}")
    lines.append(f"  rear/main tip ratio limit        : {outcome.targets.rear_main_tip_ratio_limit:.4f}")
    lines.append(f"  rear/main tip ratio slack        : {float(args.rear_main_tip_ratio_slack):.4f}")
    lines.append(f"  mass cap (kg)                    : {outcome.targets.mass_cap_kg:.3f}")
    lines.append("")
    lines.extend(_candidate_lines("Warm", w))
    lines.append("")
    lines.extend(_candidate_lines("Refined", r))
    lines.append("")
    lines.append("Delta (Refined - Warm):")
    lines.append(f"  eq mass delta (kg)               : {r.eq_mass_kg - w.eq_mass_kg:+.3f}")
    lines.append(
        f"  eq tip deflection delta (mm)     : {(r.eq_tip_deflection_m - w.eq_tip_deflection_m) * 1000.0:+.3f}"
    )
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
    lines.append(f"  Refined main_t                   : {_fmt_array_mm(r.main_t_seg_m)}")
    lines.append(f"  Warm main_r                      : {_fmt_array_mm(w.main_r_seg_m)}")
    lines.append(f"  Refined main_r                   : {_fmt_array_mm(r.main_r_seg_m)}")
    lines.append(f"  Warm rear_t                      : {_fmt_array_mm(w.rear_t_seg_m)}")
    lines.append(f"  Refined rear_t                   : {_fmt_array_mm(r.rear_t_seg_m)}")
    lines.append(f"  Warm rear_r                      : {_fmt_array_mm(w.rear_r_seg_m)}")
    lines.append(f"  Refined rear_r                   : {_fmt_array_mm(r.rear_r_seg_m)}")
    lines.append("")
    margins = _candidate_margins(cand=r, cfg=cfg, targets=outcome.targets)
    lines.append("Constraint margin minima (>= 0 means satisfied):")
    for key, value in margins.items():
        arr = np.asarray(value, dtype=float).reshape(-1)
        lines.append(f"  {key:32s}: {float(np.min(arr)):+.6e}")
    lines.append("")
    lines.append("Solver status:")
    lines.append(f"  success                          : {outcome.success}")
    lines.append(f"  message                          : {outcome.message}")
    lines.append(f"  objective mass (kg)              : {outcome.objective_mass_kg:.3f}")
    lines.append(f"  function evaluations             : {outcome.nfev}")
    lines.append(f"  iterations                       : {outcome.nit}")
    lines.append("")
    lines.append(
        "Note: This is a minimum-viable refinement path and does not change the "
        "production equivalent-beam optimizer default."
    )
    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text, encoding="utf-8")

    refined_ansys_package = None
    if args.export_ansys_dual_spar:
        refined_eq = optimizer.analyze(
            main_t_seg=r.main_t_seg_m,
            main_r_seg=r.main_r_seg_m,
            rear_t_seg=r.rear_t_seg_m,
            rear_r_seg=r.rear_r_seg_m,
        )
        refined_ansys_package = export_cross_validation_package_from_result(
            config_path=cfg_path,
            cfg=cfg,
            aircraft=aircraft,
            result=refined_eq,
            mapped_loads=mapped_loads,
            export_loads=export_loads,
            mat_db=mat_db,
            cruise_aoa_deg=cruise_aoa_deg,
            output_dir=output_dir,
            export_mode="dual_spar",
            ansys_subdir=args.ansys_subdir,
        )

    print("Dual-beam refinement complete.")
    print(f"  Report: {report_path}")
    print(f"  Success: {outcome.success}")
    print(f"  Warm dual max|UZ| (mm): {w.dual_max_uz_m * 1000.0:.3f}")
    print(f"  Refined dual max|UZ| (mm): {r.dual_max_uz_m * 1000.0:.3f}")
    print(f"  Warm dual mass (kg): {w.dual_mass_kg:.3f}")
    print(f"  Refined dual mass (kg): {r.dual_mass_kg:.3f}")
    if refined_ansys_package is not None:
        print("Refined-design dual-spar ANSYS package generated.")
        print(f"  Output dir: {refined_ansys_package.ansys_dir}")
        print(f"  APDL macro: {refined_ansys_package.apdl_path.name}")
        print(f"  NASTRAN BDF: {refined_ansys_package.bdf_path.name}")
        print(f"  Workbench CSV: {refined_ansys_package.csv_path.name}")
        print(f"  Baseline report: {refined_ansys_package.report_path.name}")
        print("  Next step: run ANSYS manually, then compare with:")
        print(
            "    uv run python scripts/ansys_dual_spar_spotcheck.py compare "
            f"--ansys-dir {refined_ansys_package.ansys_dir} "
            f"--baseline-report {refined_ansys_package.report_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
