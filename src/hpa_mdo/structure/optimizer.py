"""Spar structural optimiser — OpenMDAO-based.

Replaces the legacy scipy-only optimizer with a full OpenMDAO
architecture using the SpatialBeam FEM formulation.

Design variables : segment wall thicknesses (main + rear spar)
Objective        : total spar system mass [kg]
Constraints      : stress ≤ allowable, twist ≤ ±2°, deflection
Safety factors   : aerodynamic_load_factor applied to loads,
                   material_safety_factor applied to allowable stress
                   (these are NEVER conflated).

Usage
-----
    from hpa_mdo.core import load_config, Aircraft, MaterialDB
    from hpa_mdo.core.logging import get_logger
    from hpa_mdo.aero import VSPAeroParser, LoadMapper
    from hpa_mdo.structure import SparOptimizer

    logger = get_logger(__name__)
    cfg = load_config("configs/blackcat_004.yaml")
    ac = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    parser = VSPAeroParser(cfg.io.vsp_lod)
    aero = parser.parse()
    mapper = LoadMapper()
    loads = mapper.map_loads(aero[0], ac.wing.y,
                             actual_velocity=cfg.flight.velocity,
                             actual_density=cfg.flight.air_density)

    opt = SparOptimizer(cfg, ac, loads, mat_db)
    result = opt.run()
    logger.info("%s", result)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional

import numpy as np

from scipy.optimize import minimize as scipy_minimize
from scipy.optimize import differential_evolution

from hpa_mdo.core.logging import get_logger
from hpa_mdo.structure.oas_structural import (
    build_structural_problem,
    run_analysis,
    run_optimization,
)

logger = get_logger(__name__)


@dataclass
class OptimizationResult:
    """Output of the spar optimization."""
    success: bool
    message: str

    # Mass breakdown
    spar_mass_half_kg: float
    spar_mass_full_kg: float
    total_mass_full_kg: float  # includes joint penalty

    # Structural performance
    max_stress_main_Pa: float
    max_stress_rear_Pa: float
    allowable_stress_main_Pa: float
    allowable_stress_rear_Pa: float
    failure_index: float           # KS ≤ 0 means feasible
    buckling_index: float          # KS ≤ 0 means feasible
    tip_deflection_m: float
    max_tip_deflection_m: Optional[float]
    twist_max_deg: float

    # Design variables
    main_t_seg_mm: np.ndarray      # main spar segment thicknesses [mm]
    main_r_seg_mm: np.ndarray      # main spar outer radius per segment [mm]
    rear_t_seg_mm: Optional[np.ndarray] = None
    rear_r_seg_mm: Optional[np.ndarray] = field(default=None, repr=False)  # rear spar OD [mm]

    # Full results
    disp: Optional[np.ndarray] = field(default=None, repr=False)
    vonmises_main: Optional[np.ndarray] = field(default=None, repr=False)
    vonmises_rear: Optional[np.ndarray] = field(default=None, repr=False)
    timing_s: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable summary."""
        # Check overall feasibility
        feasible = (
            self.failure_index <= 0
            and self.buckling_index <= 0
            and (self.max_tip_deflection_m is None or self.tip_deflection_m <= self.max_tip_deflection_m * 1.02)
        )
        status_text = "✓ CONVERGED (Feasible)" if (self.success and feasible) else "✗ CONVERGED (Infeasible)" if self.success else "✗ FAILED"
        
        lines = [
            "=" * 60,
            "  HPA-MDO Spar Optimization Result",
            "=" * 60,
            f"  Status         : {status_text} — {self.message}",
            f"  Total mass     : {self.total_mass_full_kg:.2f} kg (full span)",
            f"  Spar tube mass : {self.spar_mass_full_kg:.2f} kg (full span)",
        ]
        
        defl_str = f"{self.tip_deflection_m*1000:.0f} mm"
        if self.max_tip_deflection_m is not None:
            defl_status = "OK" if self.tip_deflection_m <= self.max_tip_deflection_m * 1.02 else "VIOLATED"
            defl_str += f" / {self.max_tip_deflection_m*1000:.0f} mm max ({defl_status})"
            
        lines.append(f"  Tip deflection : {defl_str}")
        lines.append(f"  Max twist      : {self.twist_max_deg:.2f}°")
        lines.append(f"  Failure index  : {self.failure_index:.4f} ({'SAFE' if self.failure_index <= 0 else 'VIOLATED'})")
        lines.append(
            f"  Buckling index : {self.buckling_index:.4f} "
            f"({'SAFE' if self.buckling_index <= 0 else 'VIOLATED'})"
        )
        lines.append("")
        lines.append("  Main spar segments:")
        for i, (t, r) in enumerate(zip(self.main_t_seg_mm, self.main_r_seg_mm)):
            lines.append(f"    Segment {i+1}: OD={r*2:.1f}mm, t={t:.2f}mm")
        if self.rear_t_seg_mm is not None and self.rear_r_seg_mm is not None:
            lines.append("  Rear spar segments:")
            for i, (t, r) in enumerate(zip(self.rear_t_seg_mm, self.rear_r_seg_mm)):
                lines.append(f"    Segment {i+1}: OD={r*2:.1f}mm, t={t:.2f}mm")
        elif self.rear_t_seg_mm is not None:
            lines.append("  Rear spar segments [mm]:")
            for i, t in enumerate(self.rear_t_seg_mm):
                lines.append(f"    Segment {i+1}: {t:.2f} mm")
        lines.append(f"  Max σ (main)   : {self.max_stress_main_Pa/1e6:.1f} MPa "
                      f"/ {self.allowable_stress_main_Pa/1e6:.1f} MPa allowable")
        if self.max_stress_rear_Pa > 0:
            lines.append(f"  Max σ (rear)   : {self.max_stress_rear_Pa/1e6:.1f} MPa "
                          f"/ {self.allowable_stress_rear_Pa/1e6:.1f} MPa allowable")
        lines.append("=" * 60)
        return "\n".join(lines)


class SparOptimizer:
    """High-level interface for HPA spar structural optimization.

    Wraps the OpenMDAO model with a clean API for:
        - Single analysis (given thicknesses → results)
        - Full optimization (find minimum mass)
        - Parameter sweeps
    """

    def __init__(
        self,
        cfg,
        aircraft,
        aero_loads: dict,
        materials_db,
    ):
        """
        Parameters
        ----------
        cfg : HPAConfig
            Full configuration.
        aircraft : Aircraft
            Aircraft geometry and flight condition.
        aero_loads : dict
            Output of LoadMapper.map_loads() — must contain
            'lift_per_span' and optionally 'torque_per_span'.
            These loads must already be scaled to the design load case
            (for example via LoadMapper.apply_load_factor()).
        materials_db : MaterialDB
        """
        self.cfg = cfg
        self.aircraft = aircraft
        self.aero_loads = aero_loads
        self.materials_db = materials_db

        # Build the OpenMDAO problem
        self._prob = build_structural_problem(
            cfg, aircraft, aero_loads, materials_db)

    def analyze(
        self,
        main_t_seg: Optional[np.ndarray] = None,
        rear_t_seg: Optional[np.ndarray] = None,
    ) -> OptimizationResult:
        """Run a single structural analysis (no optimization).

        Parameters
        ----------
        main_t_seg : (n_seg,) array or None
            Main spar segment wall thicknesses [m].
            If None, uses the current values.
        rear_t_seg : (n_seg,) array or None
            Rear spar segment thicknesses [m].
        """
        if main_t_seg is not None:
            self._prob.set_val("struct.seg_mapper.main_t_seg", main_t_seg, units="m")
        if rear_t_seg is not None and self.cfg.rear_spar.enabled:
            self._prob.set_val("struct.seg_mapper.rear_t_seg", rear_t_seg, units="m")

        raw = run_analysis(self._prob)
        return self._to_result(raw, success=True, message="Analysis complete")

    def optimize(self, method: str = "auto") -> OptimizationResult:
        """Run the full structural optimization.

        Parameters
        ----------
        method : str
            "openmdao" — use OpenMDAO driver (needs working derivatives)
            "scipy"    — use scipy DE+SLSQP (robust, no derivatives needed)
            "auto"     — try OpenMDAO first, fall back to scipy

        Returns OptimizationResult with optimal thicknesses and performance.
        """
        if method == "openmdao":
            return self._optimize_openmdao()
        elif method == "scipy":
            return self._optimize_scipy()
        else:  # auto
            try:
                result = self._optimize_openmdao()
                if result.success and result.failure_index <= 0.01 and result.buckling_index <= 0.01:
                    return result
            except Exception:
                pass
            return self._optimize_scipy()

    def _optimize_openmdao(self) -> OptimizationResult:
        """Optimization via OpenMDAO ScipyOptimizeDriver."""
        raw = run_optimization(self._prob)
        success = raw["failure"] <= 0.01 and raw["buckling_index"] <= 0.01
        msg = "OpenMDAO converged" if success else "OpenMDAO did not fully converge"
        return self._to_result(raw, success=success, message=msg)

    def _optimize_scipy(self) -> OptimizationResult:
        """Robust optimization using scipy DE → SLSQP.

        Wraps the OpenMDAO model as a black-box function evaluator
        and uses scipy.optimize for the optimization loop.
        """
        cfg = self.cfg
        n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
        rear_on = cfg.rear_spar.enabled
        # DV layout: [main_t_seg..., main_r_seg..., rear_t_seg..., rear_r_seg...]
        n_dv = n_seg * (4 if rear_on else 2)
        min_t_main = cfg.main_spar.min_wall_thickness
        min_t_rear = cfg.rear_spar.min_wall_thickness if rear_on else min_t_main
        max_t = 0.012  # 12 mm

        bounds_main_t = [(min_t_main, max_t)] * n_seg
        bounds_main_r = [(0.010, 0.060)] * n_seg
        bounds_rear_t = [(min_t_rear, max_t)] * n_seg if rear_on else []
        bounds_rear_r = [(0.010, 0.060)] * n_seg if rear_on else []
        bounds = bounds_main_t + bounds_main_r + bounds_rear_t + bounds_rear_r

        max_twist = cfg.wing.max_tip_twist_deg
        max_defl = cfg.wing.max_tip_deflection_m if cfg.wing.max_tip_deflection_m is not None else float("inf")
        t_total_start = perf_counter()

        # Evaluation cache
        _cache = {}

        def _get_scalar(name: str) -> float:
            return float(np.asarray(self._prob.get_val(name)).item())

        def _eval(x):
            key = tuple(np.round(x, 8))
            if key in _cache:
                return _cache[key]
            x_main_t = x[:n_seg]
            x_main_r = x[n_seg:2*n_seg]
            self._prob.set_val("struct.seg_mapper.main_t_seg", x_main_t, units="m")
            self._prob.set_val("struct.seg_mapper.main_r_seg", x_main_r, units="m")
            if rear_on:
                x_rear_t = x[2*n_seg:3*n_seg]
                x_rear_r = x[3*n_seg:]
                self._prob.set_val("struct.seg_mapper.rear_t_seg", x_rear_t, units="m")
                self._prob.set_val("struct.seg_mapper.rear_r_seg", x_rear_r, units="m")
            run_analysis(self._prob)
            res = {
                "mass": _get_scalar("struct.mass.total_mass_full"),
                "failure": _get_scalar("struct.failure.failure"),
                "twist": _get_scalar("struct.twist.twist_max_deg"),
                "tip_defl": _get_scalar("struct.tip_defl.tip_deflection_m"),
                "buckling": _get_scalar("struct.buckling.buckling_index"),
            }
            _cache[key] = res
            return res

        # ── Phase 1: Global search with differential evolution ──
        logger.info("  [Phase 1] Differential Evolution global search...")

        def penalty_obj(x):
            r = _eval(x)
            penalty = 0.0
            # Stress violation — strong quadratic penalty
            if r["failure"] > 0:
                penalty += 500.0 * (1.0 + r["failure"]) ** 2
            # Twist violation — very strong penalty (this is the binding constraint)
            if r["twist"] > max_twist:
                excess = (r["twist"] - max_twist) / max_twist
                penalty += 1000.0 * excess ** 2
            # Buckling violation — strong penalty (latent silent failure if missed)
            if r["buckling"] > 0:
                penalty += 800.0 * (1.0 + r["buckling"]) ** 2
            # Deflection violation
            if max_defl < float("inf") and r["tip_defl"] > max_defl:
                excess_defl = (r["tip_defl"] - max_defl) / max_defl
                penalty += 1000.0 * excess_defl ** 2
            # Physically impossible tube: wall thickness > 95% of radius
            x_main_t = x[:n_seg]
            x_main_r = x[n_seg:2*n_seg]
            t_r_ratio_main = x_main_t / (x_main_r + 1e-10) - 0.95
            if np.any(t_r_ratio_main > 0):
                penalty += 200.0 * float(np.sum(np.maximum(t_r_ratio_main, 0.0) ** 2))
            if rear_on:
                x_rear_t = x[2*n_seg:3*n_seg]
                x_rear_r = x[3*n_seg:]
                t_r_ratio_rear = x_rear_t / (x_rear_r + 1e-10) - 0.95
                if np.any(t_r_ratio_rear > 0):
                    penalty += 200.0 * float(np.sum(np.maximum(t_r_ratio_rear, 0.0) ** 2))
            return r["mass"] * (1.0 + penalty)

        logger.info("  [Phase 1] Differential Evolution global search...")
        logger.info("  已啟用多核心運算，預期 CPU 使用率將會飆高")
        t_de_start = perf_counter()
        de_result = differential_evolution(
            penalty_obj, bounds=bounds, seed=42,
            maxiter=200, tol=1e-5, polish=False,
            init="sobol", workers=-1, popsize=20,
        )
        de_global_s = perf_counter() - t_de_start
        x_de = de_result.x
        r_de = _eval(x_de)
        logger.info(
            "    DE best: mass=%.2f kg, twist=%.2f°, failure=%.4f, buckling=%.4f",
            r_de["mass"],
            r_de["twist"],
            r_de["failure"],
            r_de["buckling"],
        )

        # ── Phase 2: Local refinement with SLSQP ──
        logger.info("  [Phase 2] SLSQP local refinement...")

        _cache.clear()

        def obj(x):
            return _eval(x)["mass"]

        constraints = [
            {"type": "ineq", "fun": lambda x: -_eval(x)["failure"]},
            {"type": "ineq", "fun": lambda x: max_twist - _eval(x)["twist"]},
            {"type": "ineq", "fun": lambda x: -_eval(x)["buckling"]},
        ]
        if max_defl < float("inf"):
            constraints.append({"type": "ineq", "fun": lambda x: max_defl - _eval(x)["tip_defl"]})

        t_slsqp_start = perf_counter()
        slsqp = scipy_minimize(
            obj, x_de, method="SLSQP",
            bounds=bounds, constraints=constraints,
            options={"maxiter": 500, "ftol": 1e-7, "disp": True},
        )
        slsqp_local_s = perf_counter() - t_slsqp_start

        # Pick best feasible solution
        r_de = _eval(x_de)
        r_sq = _eval(slsqp.x)

        tol_f = 0.01  # failure tolerance
        tol_b = 0.01  # buckling tolerance
        tol_tw = max_twist * 1.02  # 2% tolerance on twist
        tol_df = max_defl * 1.02 if max_defl < float("inf") else float("inf")

        de_feas = (
            r_de["failure"] <= tol_f
            and r_de["buckling"] <= tol_b
            and r_de["twist"] <= tol_tw
            and r_de["tip_defl"] <= tol_df
        )
        sq_feas = (
            r_sq["failure"] <= tol_f
            and r_sq["buckling"] <= tol_b
            and r_sq["twist"] <= tol_tw
            and r_sq["tip_defl"] <= tol_df
        )

        # ALWAYS prefer feasible over infeasible
        if sq_feas and de_feas:
            x_best = slsqp.x if r_sq["mass"] <= r_de["mass"] else x_de
            msg = "scipy converged (feasible)"
        elif sq_feas:
            x_best = slsqp.x
            msg = "scipy SLSQP converged (DE infeasible)"
        elif de_feas:
            x_best = x_de
            msg = "scipy DE solution (SLSQP infeasible)"
        else:
            # Neither feasible — pick the one with less constraint violation
            v_de = max(0, r_de["failure"]) + max(0, r_de["twist"] - max_twist) + max(0, r_de["buckling"])
            if max_defl < float("inf"):
                v_de += max(0, r_de["tip_defl"] - max_defl) / max_defl  # Normalized
            
            v_sq = max(0, r_sq["failure"]) + max(0, r_sq["twist"] - max_twist) + max(0, r_sq["buckling"])
            if max_defl < float("inf"):
                v_sq += max(0, r_sq["tip_defl"] - max_defl) / max_defl

            x_best = slsqp.x if v_sq <= v_de else x_de
            msg = "scipy: no fully feasible solution — best compromise"

        # Set best solution and extract full results
        self._prob.set_val("struct.seg_mapper.main_t_seg", x_best[:n_seg], units="m")
        self._prob.set_val("struct.seg_mapper.main_r_seg", x_best[n_seg:2*n_seg], units="m")
        if rear_on:
            self._prob.set_val("struct.seg_mapper.rear_t_seg", x_best[2*n_seg:3*n_seg], units="m")
            self._prob.set_val("struct.seg_mapper.rear_r_seg", x_best[3*n_seg:], units="m")
        raw = run_analysis(self._prob)
        best_r = _eval(x_best)
        success = (
            best_r["failure"] <= tol_f
            and best_r["buckling"] <= tol_b
            and best_r["twist"] <= tol_tw
            and best_r["tip_defl"] <= tol_df
        )
        total_s = perf_counter() - t_total_start
        return self._to_result(
            raw,
            success=success,
            message=msg,
            timing_s={
                "de_global_s": de_global_s,
                "slsqp_local_s": slsqp_local_s,
                "total_s": total_s,
            },
        )

    def _to_result(
        self,
        raw: dict,
        success: bool,
        message: str,
        timing_s: Optional[dict[str, float]] = None,
    ) -> OptimizationResult:
        """Convert raw results dict to OptimizationResult."""
        cfg = self.cfg
        mat_db = self.materials_db
        mat_main = mat_db.get(cfg.main_spar.material)
        mat_rear = mat_db.get(cfg.rear_spar.material)
        sigma_a_main = mat_main.tensile_strength / cfg.safety.material_safety_factor
        sigma_a_rear = mat_rear.tensile_strength / cfg.safety.material_safety_factor

        vm_main = raw.get("vonmises_main", np.array([0.0]))
        vm_rear = raw.get("vonmises_rear", np.array([0.0]))

        return OptimizationResult(
            success=success,
            message=message,
            spar_mass_half_kg=raw["spar_mass_half_kg"],
            spar_mass_full_kg=raw["spar_mass_full_kg"],
            total_mass_full_kg=raw["total_mass_full_kg"],
            max_stress_main_Pa=float(np.max(vm_main)) if len(vm_main) > 0 else 0.0,
            max_stress_rear_Pa=float(np.max(vm_rear)) if len(vm_rear) > 0 else 0.0,
            allowable_stress_main_Pa=sigma_a_main,
            allowable_stress_rear_Pa=sigma_a_rear,
            failure_index=raw["failure"],
            buckling_index=raw.get("buckling_index", raw.get("buckling", 0.0)),
            tip_deflection_m=raw["tip_deflection_m"],
            max_tip_deflection_m=cfg.wing.max_tip_deflection_m,
            twist_max_deg=raw["twist_max_deg"],
            main_t_seg_mm=raw["main_t_seg"] * 1000.0,
            main_r_seg_mm=raw["main_r_seg"] * 1000.0,
            rear_t_seg_mm=raw["rear_t_seg"] * 1000.0 if raw.get("rear_t_seg") is not None else None,
            rear_r_seg_mm=raw["rear_r_seg"] * 1000.0 if raw.get("rear_r_seg") is not None else None,
            disp=raw.get("disp"),
            vonmises_main=vm_main,
            vonmises_rear=vm_rear if len(vm_rear) > 0 else None,
            timing_s=timing_s or {},
        )
