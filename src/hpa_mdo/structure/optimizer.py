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

from collections import OrderedDict
import multiprocessing as mp
import os
from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional

import numpy as np
import openmdao.api as om

from scipy.optimize import minimize as scipy_minimize
from scipy.optimize import differential_evolution

from hpa_mdo.core.logging import get_logger
from hpa_mdo.structure.oas_structural import (
    _normalise_load_case_inputs,
    build_structural_problem,
    run_analysis,
    run_optimization,
)

logger = get_logger(__name__)

_DE_EVALUATOR = None
_SCIPY_EVAL_CACHE_SIZE = 2048
_DE_MAX_WORKERS = 4
_MAX_WALL_THICKNESS_M = 0.015
_RADIUS_MIN_M = 0.010
_RADIUS_MAX_M = 0.060
_MAX_THICKNESS_TO_RADIUS_RATIO = 0.8
_MAIN_SPAR_DOMINANCE_MARGIN_M = 0.005
_MAIN_SPAR_EI_RATIO = 2.0


class _ScipyBlackBoxEvaluator:
    """Evaluate the structural problem for SciPy black-box optimization."""

    def __init__(
        self,
        prob,
        n_seg: int,
        rear_on: bool,
        max_twist: float,
        max_defl: float,
        max_thickness_to_radius_ratio: float,
        main_spar_dominance_margin_m: float,
        main_spar_ei_ratio: float,
        cache_size: int = _SCIPY_EVAL_CACHE_SIZE,
    ):
        self.prob = prob
        self.n_seg = n_seg
        self.rear_on = rear_on
        self.max_twist = max_twist
        self.max_defl = max_defl
        self.max_thickness_to_radius_ratio = max_thickness_to_radius_ratio
        self.main_spar_dominance_margin_m = max(float(main_spar_dominance_margin_m), 0.0)
        self.main_spar_ei_ratio = max(float(main_spar_ei_ratio), 0.0)
        self._cache_size = max(int(cache_size), 0)
        self._cache: OrderedDict[tuple[float, ...], dict[str, float]] = OrderedDict()

    def clear_cache(self) -> None:
        self._cache.clear()

    def _get_scalar(self, name: str) -> float:
        return float(np.asarray(self.prob.get_val(name)).item())

    def _cache_get(self, key: tuple[float, ...]) -> Optional[dict[str, float]]:
        if self._cache_size <= 0:
            return None
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
        return cached

    def _cache_set(self, key: tuple[float, ...], value: dict[str, float]) -> None:
        if self._cache_size <= 0:
            return
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def _set_design_vector(self, x_arr: np.ndarray) -> None:
        n_seg = self.n_seg
        self.prob.set_val("struct.seg_mapper.main_t_seg", x_arr[:n_seg], units="m")
        self.prob.set_val("struct.seg_mapper.main_r_seg", x_arr[n_seg:2 * n_seg], units="m")
        if self.rear_on:
            self.prob.set_val(
                "struct.seg_mapper.rear_t_seg", x_arr[2 * n_seg:3 * n_seg], units="m"
            )
            self.prob.set_val("struct.seg_mapper.rear_r_seg", x_arr[3 * n_seg:], units="m")

    def _evaluate_scalars(self) -> dict[str, float]:
        self.prob.run_model()
        result = {
            "mass": self._get_scalar("struct.mass.total_mass_full"),
            "failure": self._get_scalar("struct.failure.failure"),
            "twist": self._get_scalar("struct.twist.twist_max_deg"),
            "tip_defl": self._get_scalar("struct.tip_defl.tip_deflection_m"),
            "buckling": self._get_scalar("struct.buckling.buckling_index"),
        }
        if self.rear_on:
            main_r = np.asarray(self.prob.get_val("struct.seg_mapper.main_r_seg"), dtype=float)
            rear_r = np.asarray(self.prob.get_val("struct.seg_mapper.rear_r_seg"), dtype=float)
            radius_margin = main_r - rear_r - self.main_spar_dominance_margin_m
            result["radius_dominance_margin_min"] = float(np.min(radius_margin))

            ei_main = np.asarray(self.prob.get_val("struct.spar_props.EI_main"), dtype=float)
            ei_rear = np.asarray(self.prob.get_val("struct.spar_props.EI_rear"), dtype=float)
            ei_margin = ei_main - self.main_spar_ei_ratio * ei_rear
            ei_ratio_margin = ei_main / (ei_rear + 1e-30) - self.main_spar_ei_ratio
            result["ei_dominance_margin_min"] = float(np.min(ei_margin))
            result["ei_ratio_margin_min"] = float(np.min(ei_ratio_margin))
        else:
            result["radius_dominance_margin_min"] = float("inf")
            result["ei_dominance_margin_min"] = float("inf")
            result["ei_ratio_margin_min"] = float("inf")

        return result

    def evaluate(self, x):
        x_arr = np.asarray(x, dtype=float)
        key = tuple(np.round(x_arr, 8))
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        self._set_design_vector(x_arr)

        try:
            res = self._evaluate_scalars()
        except om.AnalysisError:
            res = {
                "mass": 1e12,
                "failure": 1e3,
                "twist": 1e3,
                "tip_defl": 1e3,
                "buckling": 1e3,
                "radius_dominance_margin_min": -1e3,
                "ei_dominance_margin_min": -1e3,
                "ei_ratio_margin_min": -1e3,
            }
        self._cache_set(key, res)
        return res

    def penalty(self, x):
        r = self.evaluate(x)
        penalty = 0.0
        if r["failure"] > 0:
            penalty += 500.0 * (1.0 + r["failure"]) ** 2
        if r["twist"] > self.max_twist:
            excess = (r["twist"] - self.max_twist) / self.max_twist
            penalty += 1000.0 * excess ** 2
        if r["buckling"] > 0:
            penalty += 800.0 * (1.0 + r["buckling"]) ** 2
        if self.max_defl < float("inf") and r["tip_defl"] > self.max_defl:
            excess_defl = (r["tip_defl"] - self.max_defl) / self.max_defl
            penalty += 1000.0 * excess_defl ** 2

        n_seg = self.n_seg
        x_arr = np.asarray(x, dtype=float)
        x_main_t = x_arr[:n_seg]
        x_main_r = x_arr[n_seg:2 * n_seg]
        t_r_margin_main = x_main_t - self.max_thickness_to_radius_ratio * x_main_r
        if np.any(t_r_margin_main > 0):
            penalty += 400.0 * float(np.sum(np.maximum(t_r_margin_main, 0.0) ** 2))

        if self.rear_on:
            x_rear_t = x_arr[2 * n_seg:3 * n_seg]
            x_rear_r = x_arr[3 * n_seg:]
            t_r_margin_rear = x_rear_t - self.max_thickness_to_radius_ratio * x_rear_r
            if np.any(t_r_margin_rear > 0):
                penalty += 400.0 * float(np.sum(np.maximum(t_r_margin_rear, 0.0) ** 2))

            radius_margin_min = r["radius_dominance_margin_min"]
            if radius_margin_min < 0.0:
                norm = max(self.main_spar_dominance_margin_m, 1e-9)
                penalty += 1200.0 * (abs(radius_margin_min) / norm) ** 2

            ei_ratio_margin_min = r["ei_ratio_margin_min"]
            if ei_ratio_margin_min < 0.0:
                penalty += 1200.0 * (abs(ei_ratio_margin_min)) ** 2

        return r["mass"] * (1.0 + penalty)


def _de_penalty_worker(x):
    if _DE_EVALUATOR is None:
        raise RuntimeError("DE evaluator was not initialized before worker dispatch.")
    return _DE_EVALUATOR.penalty(x)


class _ForkPoolMap:
    """Map-like wrapper for SciPy DE using a forked multiprocessing pool."""

    def __init__(self, processes: int):
        self._ctx = mp.get_context("fork")
        self._pool = self._ctx.Pool(processes=processes)

    def __call__(self, func, iterable):
        return self._pool.map(func, iterable)

    def close(self) -> None:
        self._pool.close()
        self._pool.join()


def _recommended_de_workers(max_workers: int) -> int:
    """Return a bounded worker count to avoid DE memory blow-up."""
    cpu_count = os.cpu_count() or 1
    return max(1, min(cpu_count, max_workers))


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
    case_metrics: dict[str, dict[str, float]] = field(default_factory=dict)

    # Full results
    disp: Optional[np.ndarray] = field(default=None, repr=False)
    vonmises_main: Optional[np.ndarray] = field(default=None, repr=False)
    vonmises_rear: Optional[np.ndarray] = field(default=None, repr=False)
    timing_s: dict[str, float] = field(default_factory=dict)
    max_twist_limit_deg: Optional[float] = None

    def summary(self) -> str:
        """Human-readable summary."""
        # Check overall feasibility
        feasible = (
            self.failure_index <= 0
            and self.buckling_index <= 0
            and (
                self.max_twist_limit_deg is None
                or self.twist_max_deg <= self.max_twist_limit_deg * 1.02
            )
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
        twist_str = f"{self.twist_max_deg:.2f}°"
        if self.max_twist_limit_deg is not None:
            twist_status = (
                "OK"
                if self.twist_max_deg <= self.max_twist_limit_deg * 1.02
                else "VIOLATED"
            )
            twist_str += f" / {self.max_twist_limit_deg:.2f}° max ({twist_status})"
        lines.append(f"  Max twist      : {twist_str}")
        lines.append(f"  Failure index  : {self.failure_index:.4f} ({'SAFE' if self.failure_index <= 0 else 'VIOLATED'})")
        lines.append(
            f"  Buckling index : {self.buckling_index:.4f} "
            f"({'SAFE' if self.buckling_index <= 0 else 'VIOLATED'})"
        )
        if self.case_metrics:
            lines.append("  Load cases:")
            for case_name, metrics in self.case_metrics.items():
                defl_mm = metrics["tip_deflection_m"] * 1000.0
                lines.append(
                    f"    {case_name}: defl={defl_mm:.0f} mm, twist={metrics['twist_max_deg']:.2f}°, "
                    f"failure={metrics['failure_index']:.4f}, buckling={metrics['buckling_index']:.4f}"
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

    def _has_multiple_load_cases(self) -> bool:
        model = getattr(self._prob, "model", None)
        struct = getattr(model, "struct", None)
        return bool(getattr(struct, "_multi_case", False))

    def _constraint_limits_by_case(self) -> dict[str, tuple[float, Optional[float]]]:
        """Return per-case (twist_limit_deg, tip_deflection_limit_m) limits."""
        default_twist = float(self.cfg.wing.max_tip_twist_deg)
        default_deflection = self.cfg.wing.max_tip_deflection_m

        case_limits: dict[str, tuple[float, Optional[float]]] = {}
        for case in self.cfg.structural_load_cases():
            twist_limit = (
                default_twist if case.max_twist_deg is None else float(case.max_twist_deg)
            )
            deflection_limit = (
                default_deflection
                if case.max_tip_deflection_m is None
                else float(case.max_tip_deflection_m)
            )
            case_limits[case.name] = (twist_limit, deflection_limit)
        return case_limits

    def _single_case_limits(self) -> tuple[float, float]:
        """Return (twist_limit_deg, deflection_limit_m_or_inf) for single-case mode."""
        case_limits = self._constraint_limits_by_case()
        if len(case_limits) != 1:
            raise ValueError("Single-case limits requested with multiple configured load cases.")
        twist_limit, deflection_limit = next(iter(case_limits.values()))
        max_deflection = float("inf") if deflection_limit is None else float(deflection_limit)
        return float(twist_limit), max_deflection

    def _is_raw_feasible(self, raw: dict) -> bool:
        """Check full feasibility (stress, buckling, twist, tip deflection)."""
        tol = 1.02
        if float(raw["failure"]) > 0.01:
            return False
        if float(raw.get("buckling_index", raw.get("buckling", 0.0))) > 0.01:
            return False

        solver_cfg = getattr(self.cfg, "solver", None)
        ratio_limit = float(
            getattr(
                solver_cfg,
                "max_thickness_to_radius_ratio",
                _MAX_THICKNESS_TO_RADIUS_RATIO,
            )
        )
        main_t = raw.get("main_t_seg")
        main_r = raw.get("main_r_seg")
        if main_t is not None and main_r is not None:
            main_ratio_margin = ratio_limit * np.asarray(main_r) - np.asarray(main_t)
            if float(np.min(np.real(main_ratio_margin))) < -1e-9:
                return False

        rear_cfg = getattr(self.cfg, "rear_spar", None)
        rear_enabled = bool(getattr(rear_cfg, "enabled", False))

        if rear_enabled:
            dominance_margin = float(
                getattr(
                    solver_cfg,
                    "main_spar_dominance_margin_m",
                    _MAIN_SPAR_DOMINANCE_MARGIN_M,
                )
            )
            rear_r = raw.get("rear_r_seg")
            if main_r is not None and rear_r is not None:
                radius_margin = np.asarray(main_r) - np.asarray(rear_r) - dominance_margin
                if float(np.min(np.real(radius_margin))) < -1e-9:
                    return False

            rear_t = raw.get("rear_t_seg")
            if rear_t is not None and rear_r is not None:
                rear_ratio_margin = ratio_limit * np.asarray(rear_r) - np.asarray(rear_t)
                if float(np.min(np.real(rear_ratio_margin))) < -1e-9:
                    return False

            ei_main = raw.get("EI_main_elem")
            ei_rear = raw.get("EI_rear_elem")
            if ei_main is not None and ei_rear is not None:
                ei_ratio = float(
                    getattr(
                        solver_cfg,
                        "main_spar_ei_ratio",
                        _MAIN_SPAR_EI_RATIO,
                    )
                )
                ei_margin = np.asarray(ei_main) - ei_ratio * np.asarray(ei_rear)
                if float(np.min(np.real(ei_margin))) < -1e-9:
                    return False

        case_limits = self._constraint_limits_by_case()
        case_outputs = raw.get("cases")
        if case_outputs:
            default_twist = float(self.cfg.wing.max_tip_twist_deg)
            default_deflection = self.cfg.wing.max_tip_deflection_m
            for case_name, case_raw in case_outputs.items():
                twist_limit, deflection_limit = case_limits.get(
                    case_name, (default_twist, default_deflection)
                )
                if float(case_raw["twist_max_deg"]) > float(twist_limit) * tol:
                    return False
                if (
                    deflection_limit is not None
                    and float(case_raw["tip_deflection_m"]) > float(deflection_limit) * tol
                ):
                    return False
            return True

        twist_candidates = [lim[0] for lim in case_limits.values()]
        twist_limit = (
            min(twist_candidates)
            if twist_candidates
            else float(self.cfg.wing.max_tip_twist_deg)
        )
        if float(raw["twist_max_deg"]) > twist_limit * tol:
            return False

        deflection_candidates = [
            lim[1] for lim in case_limits.values() if lim[1] is not None
        ]
        if deflection_candidates:
            deflection_limit = min(float(v) for v in deflection_candidates)
            if float(raw["tip_deflection_m"]) > deflection_limit * tol:
                return False

        return True

    def _normalise_load_case_inputs_for_update(self, aero_loads: dict) -> dict[str, tuple[object, dict]]:
        """Return normalized load-case inputs using the structural model helper."""
        return _normalise_load_case_inputs(self.cfg, aero_loads)

    def update_aero_loads(self, aero_loads: dict) -> None:
        """Replace aerodynamic loads on the existing OpenMDAO problem.

        This is the FSI-friendly path: ``build_structural_problem()`` is
        expensive (component setup, partial declarations, matrix allocation),
        so iterative FSI should reuse the same ``Problem`` instance and only
        refresh external load inputs between iterations.

        Parameters
        ----------
        aero_loads : dict
            Same shape accepted by ``SparOptimizer.__init__``:
            either a legacy single mapped-load dict or
            ``{case_name: mapped_loads}`` for multi-case configs.

        Notes
        -----
        The updated loads must match the existing structural mesh
        (same number of beam nodes). Mesh/topology changes require rebuilding
        the optimizer and OpenMDAO problem from scratch.
        """
        case_entries = self._normalise_load_case_inputs_for_update(aero_loads)
        struct_group = self._prob.model._get_subsystem("struct")
        is_multi_case_problem = bool(getattr(struct_group, "_multi_case", False))

        if is_multi_case_problem != (len(case_entries) > 1):
            raise ValueError(
                "Load-case count mismatch when updating aerodynamic loads. "
                "Rebuild SparOptimizer if load-case topology changes."
            )

        self.aero_loads = aero_loads

        for case_name, (load_case, case_loads) in case_entries.items():
            ext_loads_path = (
                f"struct.case_{case_name}.ext_loads" if is_multi_case_problem else "struct.ext_loads"
            )
            comp = self._prob.model._get_subsystem(ext_loads_path)
            if comp is None:
                raise RuntimeError(
                    f"Cannot locate ExternalLoadsComp at '{ext_loads_path}' to refresh FSI loads."
                )

            n_nodes = int(comp.options["n_nodes"])
            lift = np.asarray(case_loads["lift_per_span"], dtype=float)
            if lift.shape != (n_nodes,):
                raise ValueError(
                    f"lift_per_span shape mismatch for '{case_name}': expected {(n_nodes,)}, got {lift.shape}."
                )

            torque_raw = case_loads.get("torque_per_span")
            if torque_raw is None:
                torque = np.zeros(n_nodes, dtype=float)
            else:
                torque = np.asarray(torque_raw, dtype=float)
                if torque.shape != (n_nodes,):
                    raise ValueError(
                        f"torque_per_span shape mismatch for '{case_name}': "
                        f"expected {(n_nodes,)}, got {torque.shape}."
                    )

            aero_scale = float(load_case.aero_scale)
            comp.options["lift_per_span"] = lift * aero_scale
            comp.options["torque_per_span"] = torque * aero_scale

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
            if self._has_multiple_load_cases():
                return self._optimize_openmdao()
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
        success = self._is_raw_feasible(raw)
        msg = "OpenMDAO converged" if success else "OpenMDAO did not fully converge"
        return self._to_result(raw, success=success, message=msg)

    def _optimize_scipy(self) -> OptimizationResult:
        """Robust optimization using scipy DE → SLSQP.

        Wraps the OpenMDAO model as a black-box function evaluator
        and uses scipy.optimize for the optimization loop.
        """
        if self._has_multiple_load_cases():
            raise NotImplementedError(
                "SciPy multi-load-case optimization is not supported; use method='openmdao'."
            )

        cfg = self.cfg
        n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
        rear_on = cfg.rear_spar.enabled
        solver_cfg = getattr(cfg, "solver", None)
        max_t = float(getattr(solver_cfg, "max_wall_thickness_m", _MAX_WALL_THICKNESS_M))
        min_r = float(getattr(solver_cfg, "min_radius_m", _RADIUS_MIN_M))
        max_r = float(getattr(solver_cfg, "max_radius_m", _RADIUS_MAX_M))
        ratio_limit = float(
            getattr(
                solver_cfg,
                "max_thickness_to_radius_ratio",
                _MAX_THICKNESS_TO_RADIUS_RATIO,
            )
        )
        cache_size = int(getattr(solver_cfg, "scipy_eval_cache_size", _SCIPY_EVAL_CACHE_SIZE))
        de_max_workers = int(getattr(solver_cfg, "de_max_workers", _DE_MAX_WORKERS))
        dominance_margin = float(
            getattr(
                solver_cfg,
                "main_spar_dominance_margin_m",
                _MAIN_SPAR_DOMINANCE_MARGIN_M,
            )
        )
        main_spar_ei_ratio = float(
            getattr(
                solver_cfg,
                "main_spar_ei_ratio",
                _MAIN_SPAR_EI_RATIO,
            )
        )
        # DV layout: [main_t_seg..., main_r_seg..., rear_t_seg..., rear_r_seg...]
        min_t_main = cfg.main_spar.min_wall_thickness
        min_t_rear = cfg.rear_spar.min_wall_thickness if rear_on else min_t_main

        bounds_main_t = [(min_t_main, max_t)] * n_seg
        bounds_main_r = [(min_r, max_r)] * n_seg
        bounds_rear_t = [(min_t_rear, max_t)] * n_seg if rear_on else []
        bounds_rear_r = [(min_r, max_r)] * n_seg if rear_on else []
        bounds = bounds_main_t + bounds_main_r + bounds_rear_t + bounds_rear_r

        max_twist, max_defl = self._single_case_limits()
        t_total_start = perf_counter()

        evaluator = _ScipyBlackBoxEvaluator(
            self._prob,
            n_seg=n_seg,
            rear_on=rear_on,
            max_twist=max_twist,
            max_defl=max_defl,
            max_thickness_to_radius_ratio=ratio_limit,
            main_spar_dominance_margin_m=dominance_margin,
            main_spar_ei_ratio=main_spar_ei_ratio,
            cache_size=cache_size,
        )

        # ── Phase 1: Global search with differential evolution ──
        logger.info("  [Phase 1] Differential Evolution global search...")
        logger.info("  已啟用多核心運算，預期 CPU 使用率將會飆高")
        de_workers = 1
        de_func = evaluator.penalty
        pool_map = None
        if "fork" in mp.get_all_start_methods():
            global _DE_EVALUATOR
            _DE_EVALUATOR = evaluator
            worker_count = _recommended_de_workers(de_max_workers)
            pool_map = _ForkPoolMap(processes=worker_count)
            de_workers = pool_map
            de_func = _de_penalty_worker
            logger.info("  DE worker pool size: %d", worker_count)
        else:
            logger.warning(
                "No 'fork' multiprocessing start method is available; "
                "falling back to serial DE evaluation."
            )

        t_de_start = perf_counter()
        try:
            de_result = differential_evolution(
                de_func, bounds=bounds, seed=42,
                maxiter=200, tol=1e-5, polish=False,
                init="sobol", workers=de_workers, popsize=20,
            )
        finally:
            if pool_map is not None:
                pool_map.close()
                _DE_EVALUATOR = None
        de_global_s = perf_counter() - t_de_start
        x_de = de_result.x
        r_de = evaluator.evaluate(x_de)
        logger.info(
            "    DE best: mass=%.2f kg, twist=%.2f°, failure=%.4f, buckling=%.4f",
            r_de["mass"],
            r_de["twist"],
            r_de["failure"],
            r_de["buckling"],
        )

        # ── Phase 2: Local refinement with SLSQP ──
        logger.info("  [Phase 2] SLSQP local refinement...")

        evaluator.clear_cache()

        def obj(x):
            return evaluator.evaluate(x)["mass"]

        constraints = [
            {"type": "ineq", "fun": lambda x: -evaluator.evaluate(x)["failure"]},
            {"type": "ineq", "fun": lambda x: max_twist - evaluator.evaluate(x)["twist"]},
            {"type": "ineq", "fun": lambda x: -evaluator.evaluate(x)["buckling"]},
            {
                "type": "ineq",
                "fun": (
                    lambda x, n=n_seg, eta=ratio_limit: (
                        np.min(
                            eta * np.asarray(x, dtype=float)[n:2 * n]
                            - np.asarray(x, dtype=float)[:n]
                        )
                    )
                ),
            },
        ]
        if rear_on:
            constraints.append(
                {
                    "type": "ineq",
                    "fun": (
                        lambda x, n=n_seg, eta=ratio_limit: (
                            np.min(
                                eta * np.asarray(x, dtype=float)[3 * n:4 * n]
                                - np.asarray(x, dtype=float)[2 * n:3 * n]
                            )
                        )
                    ),
                }
            )
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda x: evaluator.evaluate(x)["radius_dominance_margin_min"],
                }
            )
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda x: evaluator.evaluate(x)["ei_ratio_margin_min"],
                }
            )
        if max_defl < float("inf"):
            constraints.append(
                {"type": "ineq", "fun": lambda x: max_defl - evaluator.evaluate(x)["tip_defl"]}
            )

        t_slsqp_start = perf_counter()
        slsqp = scipy_minimize(
            obj, x_de, method="SLSQP",
            bounds=bounds, constraints=constraints,
            options={"maxiter": 500, "ftol": 1e-7, "disp": True},
        )
        slsqp_local_s = perf_counter() - t_slsqp_start

        # Pick best feasible solution
        r_de = evaluator.evaluate(x_de)
        r_sq = evaluator.evaluate(slsqp.x)

        tol_f = 0.01  # failure tolerance
        tol_b = 0.01  # buckling tolerance
        tol_tw = max_twist * 1.02  # 2% tolerance on twist
        tol_df = max_defl * 1.02 if max_defl < float("inf") else float("inf")

        def _ratio_margin_mins(x: np.ndarray) -> tuple[float, Optional[float]]:
            x_arr = np.asarray(x, dtype=float)
            main_margin_min = float(
                np.min(ratio_limit * x_arr[n_seg:2 * n_seg] - x_arr[:n_seg])
            )
            rear_margin_min: Optional[float] = None
            if rear_on:
                rear_margin_min = float(
                    np.min(ratio_limit * x_arr[3 * n_seg:4 * n_seg] - x_arr[2 * n_seg:3 * n_seg])
                )
            return main_margin_min, rear_margin_min

        de_main_ratio_margin_min, de_rear_ratio_margin_min = _ratio_margin_mins(x_de)
        sq_main_ratio_margin_min, sq_rear_ratio_margin_min = _ratio_margin_mins(slsqp.x)

        de_feas = (
            r_de["failure"] <= tol_f
            and r_de["buckling"] <= tol_b
            and r_de["twist"] <= tol_tw
            and r_de["tip_defl"] <= tol_df
            and de_main_ratio_margin_min >= 0.0
            and (not rear_on or (de_rear_ratio_margin_min is not None and de_rear_ratio_margin_min >= 0.0))
            and (not rear_on or r_de["radius_dominance_margin_min"] >= 0.0)
            and (not rear_on or r_de["ei_ratio_margin_min"] >= 0.0)
        )
        sq_feas = (
            r_sq["failure"] <= tol_f
            and r_sq["buckling"] <= tol_b
            and r_sq["twist"] <= tol_tw
            and r_sq["tip_defl"] <= tol_df
            and sq_main_ratio_margin_min >= 0.0
            and (not rear_on or (sq_rear_ratio_margin_min is not None and sq_rear_ratio_margin_min >= 0.0))
            and (not rear_on or r_sq["radius_dominance_margin_min"] >= 0.0)
            and (not rear_on or r_sq["ei_ratio_margin_min"] >= 0.0)
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
            v_de += max(0, -de_main_ratio_margin_min) / max(ratio_limit * min_r, 1e-9)
            if rear_on:
                if de_rear_ratio_margin_min is not None:
                    v_de += max(0, -de_rear_ratio_margin_min) / max(ratio_limit * min_r, 1e-9)
                v_de += max(0, -r_de["radius_dominance_margin_min"]) / max(dominance_margin, 1e-9)
                v_de += max(0, -r_de["ei_ratio_margin_min"])
            
            v_sq = max(0, r_sq["failure"]) + max(0, r_sq["twist"] - max_twist) + max(0, r_sq["buckling"])
            if max_defl < float("inf"):
                v_sq += max(0, r_sq["tip_defl"] - max_defl) / max_defl
            v_sq += max(0, -sq_main_ratio_margin_min) / max(ratio_limit * min_r, 1e-9)
            if rear_on:
                if sq_rear_ratio_margin_min is not None:
                    v_sq += max(0, -sq_rear_ratio_margin_min) / max(ratio_limit * min_r, 1e-9)
                v_sq += max(0, -r_sq["radius_dominance_margin_min"]) / max(dominance_margin, 1e-9)
                v_sq += max(0, -r_sq["ei_ratio_margin_min"])

            x_best = slsqp.x if v_sq <= v_de else x_de
            msg = "scipy: no fully feasible solution — best compromise"

        # Set best solution and extract full results
        self._prob.set_val("struct.seg_mapper.main_t_seg", x_best[:n_seg], units="m")
        self._prob.set_val("struct.seg_mapper.main_r_seg", x_best[n_seg:2*n_seg], units="m")
        if rear_on:
            self._prob.set_val("struct.seg_mapper.rear_t_seg", x_best[2*n_seg:3*n_seg], units="m")
            self._prob.set_val("struct.seg_mapper.rear_r_seg", x_best[3*n_seg:], units="m")
        raw = run_analysis(self._prob)
        best_r = evaluator.evaluate(x_best)
        success = self._is_raw_feasible(raw)
        if rear_on:
            success = (
                success
                and best_r["radius_dominance_margin_min"] >= 0.0
                and best_r["ei_ratio_margin_min"] >= 0.0
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

        case_metrics: dict[str, dict[str, float]] = {}
        if raw.get("cases"):
            case_outputs = raw["cases"]
            for case_name, case_raw in case_outputs.items():
                vm_main_case = case_raw.get("vonmises_main")
                vm_rear_case = case_raw.get("vonmises_rear")
                case_metrics[case_name] = {
                    "failure_index": float(case_raw["failure"]),
                    "buckling_index": float(case_raw["buckling_index"]),
                    "tip_deflection_m": float(case_raw["tip_deflection_m"]),
                    "twist_max_deg": float(case_raw["twist_max_deg"]),
                    "max_stress_main_Pa": (
                        float(np.max(vm_main_case)) if vm_main_case is not None and len(vm_main_case) > 0 else 0.0
                    ),
                    "max_stress_rear_Pa": (
                        float(np.max(vm_rear_case)) if vm_rear_case is not None and len(vm_rear_case) > 0 else 0.0
                    ),
                }

            max_stress_main = max(m["max_stress_main_Pa"] for m in case_metrics.values())
            max_stress_rear = max(m["max_stress_rear_Pa"] for m in case_metrics.values())
            vm_main = None
            vm_rear = None
            disp = None
        else:
            vm_main = raw.get("vonmises_main", np.array([0.0]))
            vm_rear = raw.get("vonmises_rear", np.array([0.0]))
            max_stress_main = float(np.max(vm_main)) if len(vm_main) > 0 else 0.0
            max_stress_rear = float(np.max(vm_rear)) if len(vm_rear) > 0 else 0.0
            disp = raw.get("disp")

        case_limits = self._constraint_limits_by_case()
        twist_candidates = [lim[0] for lim in case_limits.values()]
        deflection_candidates = [lim[1] for lim in case_limits.values() if lim[1] is not None]
        twist_limit = min(twist_candidates) if twist_candidates else float(cfg.wing.max_tip_twist_deg)
        deflection_limit = min(float(v) for v in deflection_candidates) if deflection_candidates else None

        return OptimizationResult(
            success=success,
            message=message,
            spar_mass_half_kg=raw["spar_mass_half_kg"],
            spar_mass_full_kg=raw["spar_mass_full_kg"],
            total_mass_full_kg=raw["total_mass_full_kg"],
            max_stress_main_Pa=max_stress_main,
            max_stress_rear_Pa=max_stress_rear,
            allowable_stress_main_Pa=sigma_a_main,
            allowable_stress_rear_Pa=sigma_a_rear,
            failure_index=raw["failure"],
            buckling_index=raw.get("buckling_index", raw.get("buckling", 0.0)),
            tip_deflection_m=raw["tip_deflection_m"],
            max_tip_deflection_m=deflection_limit,
            twist_max_deg=raw["twist_max_deg"],
            case_metrics=case_metrics,
            main_t_seg_mm=raw["main_t_seg"] * 1000.0,
            main_r_seg_mm=raw["main_r_seg"] * 1000.0,
            rear_t_seg_mm=raw["rear_t_seg"] * 1000.0 if raw.get("rear_t_seg") is not None else None,
            rear_r_seg_mm=raw["rear_r_seg"] * 1000.0 if raw.get("rear_r_seg") is not None else None,
            disp=disp,
            vonmises_main=vm_main,
            vonmises_rear=vm_rear if vm_rear is not None and len(vm_rear) > 0 else None,
            timing_s=timing_s or {},
            max_twist_limit_deg=twist_limit,
        )
