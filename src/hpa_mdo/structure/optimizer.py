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

from hpa_mdo.core.layup_constraints import (
    effective_layup_thickness_step_limit,
    thickness_step_margin_min,
)
from hpa_mdo.core.logging import get_logger
from hpa_mdo.structure.groups.main import (
    _lift_wire_node_indices,
    _scaled_case_aero_distributions,
    _wire_precompression_for_case,
)
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
_MAX_THICKNESS_STEP_M = 0.003
_RADIUS_MIN_M = 0.010
_RADIUS_MAX_M = 0.060
_MAX_THICKNESS_TO_RADIUS_RATIO = 0.8
_MAIN_SPAR_DOMINANCE_MARGIN_M = 0.005
_MAIN_SPAR_EI_RATIO = 2.0
_REAR_MAIN_RADIUS_RATIO_MIN = 0.0
_REAR_MIN_INNER_RADIUS_M = 1.0e-4
_REAR_INBOARD_EI_TO_MAIN_RATIO_MAX = 0.20
_REAR_INBOARD_SPAN_M = 1.5

_FAILED_EVAL_MASS_KG = 1.0e12
_FAILED_EVAL_CONSTRAINT_VALUE = 1.0e3
_FAILED_EVAL_NEG_MARGIN = -1.0e3


def _format_design_vector_summary(x_arr: np.ndarray) -> str:
    """Compact design-vector summary for failure logs."""
    if x_arr.size == 0:
        return "size=0"
    if not np.all(np.isfinite(x_arr)):
        return f"size={x_arr.size}, finite=False"
    return f"size={x_arr.size}, min={float(np.min(x_arr)):.6g}, max={float(np.max(x_arr)):.6g}"


def _max_array_metric(values) -> float:
    """Return max finite array value for optional report metrics."""
    if values is None:
        return 0.0
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0
    return float(np.max(arr))


def _optimizer_thickness_step_limit_m(spar_cfg, solver_cfg, materials_db) -> float:
    """Return the continuous optimizer step cap, tightened by ply-drop settings when enabled."""
    base_limit = float(
        getattr(
            solver_cfg,
            "max_thickness_step_m",
            _MAX_THICKNESS_STEP_M,
        )
    )
    if spar_cfg is None:
        return base_limit
    try:
        return effective_layup_thickness_step_limit(spar_cfg, base_limit, materials_db)
    except Exception as exc:
        logger.warning("Failed to derive layup thickness-step limit: %s", exc)
        return 0.0


def _is_eval_valid(res: dict[str, float], *, rear_on: bool) -> bool:
    """Return True when evaluator output is finite for all required fields."""
    if not isinstance(res, dict):
        return False

    required = [
        "mass",
        "failure",
        "twist",
        "tip_defl",
        "buckling",
        "main_hollow_margin_min",
        "main_thickness_step_margin_min",
    ]
    if rear_on:
        required.extend(
            [
                "rear_hollow_margin_min",
                "rear_thickness_step_margin_min",
                "rear_main_radius_ratio_margin_min",
                "radius_dominance_margin_min",
                "ei_ratio_margin_min",
                "rear_inboard_ei_margin_min",
            ]
        )

    for key in required:
        if key not in res:
            return False
        try:
            val = float(np.asarray(res[key]).item())
        except Exception:
            return False
        if not np.isfinite(val):
            return False

    return True


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
        max_main_thickness_step_m: float,
        max_rear_thickness_step_m: float,
        main_spar_dominance_margin_m: float,
        main_spar_ei_ratio: float,
        rear_main_radius_ratio_min: float,
        rear_min_inner_radius_m: float,
        rear_inboard_ei_to_main_ratio_max: float,
        inboard_ei_element_indices: np.ndarray,
        cache_size: int = _SCIPY_EVAL_CACHE_SIZE,
    ):
        self.prob = prob
        self.n_seg = n_seg
        self.rear_on = rear_on
        self.max_twist = max_twist
        self.max_defl = max_defl
        self.max_thickness_to_radius_ratio = max_thickness_to_radius_ratio
        self.max_main_thickness_step_m = max(float(max_main_thickness_step_m), 0.0)
        self.max_rear_thickness_step_m = max(float(max_rear_thickness_step_m), 0.0)
        self.main_spar_dominance_margin_m = max(float(main_spar_dominance_margin_m), 0.0)
        self.main_spar_ei_ratio = max(float(main_spar_ei_ratio), 0.0)
        self.rear_main_radius_ratio_min = max(float(rear_main_radius_ratio_min), 0.0)
        self.rear_min_inner_radius_m = max(float(rear_min_inner_radius_m), 0.0)
        self.rear_inboard_ei_to_main_ratio_max = max(float(rear_inboard_ei_to_main_ratio_max), 0.0)
        self.inboard_ei_element_indices = np.asarray(inboard_ei_element_indices, dtype=int)
        self._cache_size = max(int(cache_size), 0)
        self._cache: OrderedDict[tuple[float, ...], dict[str, float]] = OrderedDict()
        self._n_run_model = 0
        self._n_cache_hit = 0
        self._n_cache_miss = 0

    def clear_cache(self) -> None:
        self._cache.clear()

    def _get_scalar(self, name: str) -> float:
        value = float(np.asarray(self.prob.get_val(name)).item())
        if not np.isfinite(value):
            raise om.AnalysisError(f"Non-finite scalar metric from '{name}': {value}")
        return value

    def _get_finite_array(self, name: str) -> np.ndarray:
        arr = np.asarray(self.prob.get_val(name), dtype=float)
        if not np.all(np.isfinite(arr)):
            raise om.AnalysisError(f"Non-finite array metric from '{name}'.")
        return arr

    def _failed_eval(
        self,
        reason: str,
        *,
        main_hollow_margin_min: float = _FAILED_EVAL_NEG_MARGIN,
        main_thickness_step_margin_min: float = _FAILED_EVAL_NEG_MARGIN,
        rear_hollow_margin_min: float = _FAILED_EVAL_NEG_MARGIN,
        rear_thickness_step_margin_min: float = _FAILED_EVAL_NEG_MARGIN,
        rear_main_radius_ratio_margin_min: float = _FAILED_EVAL_NEG_MARGIN,
        radius_dominance_margin_min: float = _FAILED_EVAL_NEG_MARGIN,
        ei_dominance_margin_min: float = _FAILED_EVAL_NEG_MARGIN,
        ei_ratio_margin_min: float = _FAILED_EVAL_NEG_MARGIN,
        rear_inboard_ei_margin_min: float = _FAILED_EVAL_NEG_MARGIN,
    ) -> dict[str, float]:
        return {
            "mass": _FAILED_EVAL_MASS_KG,
            "failure": _FAILED_EVAL_CONSTRAINT_VALUE,
            "twist": _FAILED_EVAL_CONSTRAINT_VALUE,
            "tip_defl": _FAILED_EVAL_CONSTRAINT_VALUE,
            "buckling": _FAILED_EVAL_CONSTRAINT_VALUE,
            "main_hollow_margin_min": float(main_hollow_margin_min),
            "main_thickness_step_margin_min": float(main_thickness_step_margin_min),
            "rear_hollow_margin_min": float(rear_hollow_margin_min),
            "rear_thickness_step_margin_min": float(rear_thickness_step_margin_min),
            "rear_main_radius_ratio_margin_min": float(rear_main_radius_ratio_margin_min),
            "radius_dominance_margin_min": float(radius_dominance_margin_min),
            "ei_dominance_margin_min": float(ei_dominance_margin_min),
            "ei_ratio_margin_min": float(ei_ratio_margin_min),
            "rear_inboard_ei_margin_min": float(rear_inboard_ei_margin_min),
        }

    def _cache_get(self, key: tuple[float, ...]) -> Optional[dict[str, float]]:
        if self._cache_size <= 0:
            self._n_cache_miss += 1
            return None
        cached = self._cache.get(key)
        if cached is None:
            self._n_cache_miss += 1
            return None
        self._n_cache_hit += 1
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
        self.prob.set_val("struct.seg_mapper.main_r_seg", x_arr[n_seg : 2 * n_seg], units="m")
        if self.rear_on:
            self.prob.set_val(
                "struct.seg_mapper.rear_t_seg", x_arr[2 * n_seg : 3 * n_seg], units="m"
            )
            self.prob.set_val("struct.seg_mapper.rear_r_seg", x_arr[3 * n_seg :], units="m")

    def _evaluate_scalars(self) -> dict[str, float]:
        self._n_run_model += 1
        self.prob.run_model()
        main_t = self._get_finite_array("struct.seg_mapper.main_t_seg")
        main_r = self._get_finite_array("struct.seg_mapper.main_r_seg")
        result = {
            "mass": self._get_scalar("struct.mass.total_mass_full"),
            "failure": self._get_scalar("struct.failure.failure"),
            "twist": self._get_scalar("struct.twist.twist_max_deg"),
            "tip_defl": self._get_scalar("struct.tip_defl.tip_deflection_m"),
            "buckling": self._get_scalar("struct.buckling.buckling_index"),
            "main_hollow_margin_min": float(np.min(main_r - main_t)),
            "main_thickness_step_margin_min": thickness_step_margin_min(
                main_t, self.max_main_thickness_step_m
            ),
        }
        if self.rear_on:
            rear_t = self._get_finite_array("struct.seg_mapper.rear_t_seg")
            rear_r = self._get_finite_array("struct.seg_mapper.rear_r_seg")
            rear_hollow_margin = rear_r - rear_t - self.rear_min_inner_radius_m
            result["rear_hollow_margin_min"] = float(np.min(rear_hollow_margin))
            result["rear_thickness_step_margin_min"] = thickness_step_margin_min(
                rear_t, self.max_rear_thickness_step_m
            )

            radius_ratio_margin = rear_r - self.rear_main_radius_ratio_min * main_r
            result["rear_main_radius_ratio_margin_min"] = float(np.min(radius_ratio_margin))

            radius_margin = main_r - rear_r - self.main_spar_dominance_margin_m
            result["radius_dominance_margin_min"] = float(np.min(radius_margin))

            ei_main = self._get_finite_array("struct.spar_props.EI_main")
            ei_rear = self._get_finite_array("struct.spar_props.EI_rear")
            ei_margin = ei_main - self.main_spar_ei_ratio * ei_rear
            ei_ratio_margin = ei_main / (ei_rear + 1e-30) - self.main_spar_ei_ratio
            result["ei_dominance_margin_min"] = float(np.min(ei_margin))
            result["ei_ratio_margin_min"] = float(np.min(ei_ratio_margin))

            if self.inboard_ei_element_indices.size > 0:
                idx = self.inboard_ei_element_indices
                inboard_margin = (
                    self.rear_inboard_ei_to_main_ratio_max * ei_main[idx] - ei_rear[idx]
                )
                result["rear_inboard_ei_margin_min"] = float(np.min(inboard_margin))
            else:
                result["rear_inboard_ei_margin_min"] = float("inf")
        else:
            result["rear_hollow_margin_min"] = float("inf")
            result["rear_thickness_step_margin_min"] = float("inf")
            result["rear_main_radius_ratio_margin_min"] = float("inf")
            result["radius_dominance_margin_min"] = float("inf")
            result["ei_dominance_margin_min"] = float("inf")
            result["ei_ratio_margin_min"] = float("inf")
            result["rear_inboard_ei_margin_min"] = float("inf")

        return result

    def evaluate(self, x):
        x_arr = np.asarray(x, dtype=float)
        if not np.all(np.isfinite(x_arr)):
            logger.warning(
                "SciPy evaluator received non-finite design vector; forcing failed eval (%s).",
                _format_design_vector_summary(x_arr),
            )
            return self._failed_eval("non_finite_design_vector")

        n_seg = self.n_seg
        x_main_t = x_arr[:n_seg]
        x_main_r = x_arr[n_seg : 2 * n_seg]
        if np.any(x_main_r - x_main_t <= 0.0):
            # Physical invalidity for hollow tube model.
            return self._failed_eval(
                "main_hollow_tube_invalid",
                main_hollow_margin_min=float(np.min(x_main_r - x_main_t)),
            )
        if self.rear_on:
            x_rear_t = x_arr[2 * n_seg : 3 * n_seg]
            x_rear_r = x_arr[3 * n_seg :]
            rear_hollow_margin = x_rear_r - x_rear_t - self.rear_min_inner_radius_m
            if np.any(rear_hollow_margin < 0.0):
                # Hard guard: never allow invalid/near-solid rear tube geometry.
                return self._failed_eval(
                    "rear_hollow_tube_invalid",
                    main_hollow_margin_min=float(np.min(x_main_r - x_main_t)),
                    rear_hollow_margin_min=float(np.min(rear_hollow_margin)),
                )

        key = tuple(np.round(x_arr, 12))
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        self._set_design_vector(x_arr)

        try:
            res = self._evaluate_scalars()
        except Exception as exc:  # normalize all evaluation-time failures
            logger.exception(
                "SciPy evaluator normalized failure [%s]: %s | %s",
                type(exc).__name__,
                exc,
                _format_design_vector_summary(x_arr),
            )
            res = self._failed_eval(f"{type(exc).__name__}: {exc}")

        if not _is_eval_valid(res, rear_on=self.rear_on):
            logger.warning(
                "SciPy evaluator produced invalid metrics; coercing to failed eval (%s).",
                _format_design_vector_summary(x_arr),
            )
            res = self._failed_eval("invalid_or_non_finite_metrics")

        self._cache_set(key, res)
        return res

    def penalty(self, x):
        r = self.evaluate(x)
        penalty = 0.0
        if r["failure"] > 0:
            penalty += 500.0 * (1.0 + r["failure"]) ** 2
        if r["twist"] > self.max_twist:
            excess = (r["twist"] - self.max_twist) / self.max_twist
            penalty += 1000.0 * excess**2
        if r["buckling"] > 0:
            penalty += 800.0 * (1.0 + r["buckling"]) ** 2
        if self.max_defl < float("inf") and r["tip_defl"] > self.max_defl:
            excess_defl = (r["tip_defl"] - self.max_defl) / self.max_defl
            penalty += 1000.0 * excess_defl**2

        n_seg = self.n_seg
        x_arr = np.asarray(x, dtype=float)
        x_main_t = x_arr[:n_seg]
        x_main_r = x_arr[n_seg : 2 * n_seg]
        t_r_margin_main = x_main_t - self.max_thickness_to_radius_ratio * x_main_r
        if np.any(t_r_margin_main > 0):
            penalty += 400.0 * float(np.sum(np.maximum(t_r_margin_main, 0.0) ** 2))

        main_step_margin_min = r["main_thickness_step_margin_min"]
        if main_step_margin_min < 0.0:
            norm = max(self.max_main_thickness_step_m, 1e-9)
            penalty += 1200.0 * (abs(main_step_margin_min) / norm) ** 2

        if self.rear_on:
            x_rear_t = x_arr[2 * n_seg : 3 * n_seg]
            x_rear_r = x_arr[3 * n_seg :]
            t_r_margin_rear = x_rear_t - self.max_thickness_to_radius_ratio * x_rear_r
            if np.any(t_r_margin_rear > 0):
                penalty += 400.0 * float(np.sum(np.maximum(t_r_margin_rear, 0.0) ** 2))

            rear_step_margin_min = r["rear_thickness_step_margin_min"]
            if rear_step_margin_min < 0.0:
                norm = max(self.max_rear_thickness_step_m, 1e-9)
                penalty += 1200.0 * (abs(rear_step_margin_min) / norm) ** 2

            radius_margin_min = r["radius_dominance_margin_min"]
            if radius_margin_min < 0.0:
                norm = max(self.main_spar_dominance_margin_m, 1e-9)
                penalty += 1200.0 * (abs(radius_margin_min) / norm) ** 2

            ei_ratio_margin_min = r["ei_ratio_margin_min"]
            if ei_ratio_margin_min < 0.0:
                penalty += 1200.0 * (abs(ei_ratio_margin_min)) ** 2

            rear_hollow_margin_min = r["rear_hollow_margin_min"]
            if rear_hollow_margin_min < 0.0:
                norm = max(self.rear_min_inner_radius_m, 1e-9)
                penalty += 2000.0 * (abs(rear_hollow_margin_min) / norm) ** 2

            rear_main_radius_ratio_margin_min = r["rear_main_radius_ratio_margin_min"]
            if self.rear_main_radius_ratio_min > 0.0 and rear_main_radius_ratio_margin_min < 0.0:
                min_main_radius = max(float(np.min(x_main_r)), 1e-9)
                norm = max(self.rear_main_radius_ratio_min * min_main_radius, 1e-9)
                penalty += 1200.0 * (abs(rear_main_radius_ratio_margin_min) / norm) ** 2

            rear_inboard_ei_margin_min = r["rear_inboard_ei_margin_min"]
            if rear_inboard_ei_margin_min < 0.0:
                penalty += 1200.0 * (abs(rear_inboard_ei_margin_min)) ** 2

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
    failure_index: float  # KS ≤ 0 means feasible
    buckling_index: float  # KS ≤ 0 means feasible
    tip_deflection_m: float
    max_tip_deflection_m: Optional[float]
    twist_max_deg: float

    # Design variables
    main_t_seg_mm: np.ndarray  # main spar segment thicknesses [mm]
    main_r_seg_mm: np.ndarray  # main spar outer radius per segment [mm]
    rear_t_seg_mm: Optional[np.ndarray] = None
    rear_r_seg_mm: Optional[np.ndarray] = field(default=None, repr=False)  # rear spar OD [mm]
    case_metrics: dict[str, dict[str, float]] = field(default_factory=dict)

    # Full results
    nodes: Optional[np.ndarray] = field(default=None, repr=False)
    disp: Optional[np.ndarray] = field(default=None, repr=False)
    vonmises_main: Optional[np.ndarray] = field(default=None, repr=False)
    vonmises_rear: Optional[np.ndarray] = field(default=None, repr=False)
    strain_envelope: dict[str, np.ndarray] = field(default_factory=dict, repr=False)
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
            and (
                self.max_tip_deflection_m is None
                or self.tip_deflection_m <= self.max_tip_deflection_m * 1.02
            )
        )
        status_text = (
            "✓ CONVERGED (Feasible)"
            if (self.success and feasible)
            else "✗ CONVERGED (Infeasible)"
            if self.success
            else "✗ FAILED"
        )

        lines = [
            "=" * 60,
            "  HPA-MDO Spar Optimization Result",
            "=" * 60,
            f"  Status         : {status_text} — {self.message}",
            f"  Total mass     : {self.total_mass_full_kg:.2f} kg (full span)",
            f"  Spar tube mass : {self.spar_mass_full_kg:.2f} kg (full span)",
        ]

        defl_str = f"{self.tip_deflection_m * 1000:.0f} mm"
        if self.max_tip_deflection_m is not None:
            defl_status = (
                "OK" if self.tip_deflection_m <= self.max_tip_deflection_m * 1.02 else "VIOLATED"
            )
            defl_str += f" / {self.max_tip_deflection_m * 1000:.0f} mm max ({defl_status})"

        lines.append(f"  Tip deflection : {defl_str}")
        twist_str = f"{self.twist_max_deg:.2f}°"
        if self.max_twist_limit_deg is not None:
            twist_status = (
                "OK" if self.twist_max_deg <= self.max_twist_limit_deg * 1.02 else "VIOLATED"
            )
            twist_str += f" / {self.max_twist_limit_deg:.2f}° max ({twist_status})"
        lines.append(f"  Max twist      : {twist_str}")
        lines.append(
            f"  Failure index  : {self.failure_index:.4f} ({'SAFE' if self.failure_index <= 0 else 'VIOLATED'})"
        )
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
            lines.append(f"    Segment {i + 1}: OD={r * 2:.1f}mm, t={t:.2f}mm")
        if self.rear_t_seg_mm is not None and self.rear_r_seg_mm is not None:
            lines.append("  Rear spar segments:")
            for i, (t, r) in enumerate(zip(self.rear_t_seg_mm, self.rear_r_seg_mm)):
                lines.append(f"    Segment {i + 1}: OD={r * 2:.1f}mm, t={t:.2f}mm")
        elif self.rear_t_seg_mm is not None:
            lines.append("  Rear spar segments [mm]:")
            for i, t in enumerate(self.rear_t_seg_mm):
                lines.append(f"    Segment {i + 1}: {t:.2f} mm")
        lines.append(
            f"  Max σ (main)   : {self.max_stress_main_Pa / 1e6:.1f} MPa "
            f"/ {self.allowable_stress_main_Pa / 1e6:.1f} MPa allowable"
        )
        if self.max_stress_rear_Pa > 0:
            lines.append(
                f"  Max σ (rear)   : {self.max_stress_rear_Pa / 1e6:.1f} MPa "
                f"/ {self.allowable_stress_rear_Pa / 1e6:.1f} MPa allowable"
            )
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
            These loads should remain at their mapped physical level.
            Case-level aerodynamic scaling belongs to ``load_case.aero_scale``
            inside the structural model; do not apply it again externally.
        materials_db : MaterialDB
        """
        self.cfg = cfg
        self.aircraft = aircraft
        self.aero_loads = aero_loads
        self.materials_db = materials_db

        # Build the OpenMDAO problem
        self._prob = build_structural_problem(cfg, aircraft, aero_loads, materials_db)

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
            twist_limit = default_twist if case.max_twist_deg is None else float(case.max_twist_deg)
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

    def _rear_min_inner_radius_m(self) -> float:
        solver_cfg = getattr(self.cfg, "solver", None)
        return max(
            float(
                getattr(
                    solver_cfg,
                    "rear_min_inner_radius_m",
                    _REAR_MIN_INNER_RADIUS_M,
                )
            ),
            0.0,
        )

    def _rear_inboard_ei_to_main_ratio_max(self) -> float:
        solver_cfg = getattr(self.cfg, "solver", None)
        return max(
            float(
                getattr(
                    solver_cfg,
                    "rear_inboard_ei_to_main_ratio_max",
                    _REAR_INBOARD_EI_TO_MAIN_RATIO_MAX,
                )
            ),
            0.0,
        )

    def _inboard_ei_element_indices(self, n_elem: int | None = None) -> np.ndarray:
        solver_cfg = getattr(self.cfg, "solver", None)
        inboard_span = max(
            float(
                getattr(
                    solver_cfg,
                    "rear_inboard_span_m",
                    _REAR_INBOARD_SPAN_M,
                )
            ),
            0.0,
        )
        if inboard_span <= 0.0:
            return np.zeros(0, dtype=int)

        prob = getattr(self, "_prob", None)
        struct_group = getattr(getattr(prob, "model", None), "struct", None)
        elem_centres = np.asarray(getattr(struct_group, "_elem_centres", np.array([])), dtype=float)
        if elem_centres.size == 0:
            if n_elem is None:
                return np.zeros(0, dtype=int)
            elem_centres = np.linspace(0.0, 1.0, int(n_elem), endpoint=False, dtype=float)

        idx = np.where(elem_centres <= inboard_span + 1e-12)[0]
        if idx.size == 0 and elem_centres.size > 0:
            idx = np.array([0], dtype=int)
        return np.asarray(idx, dtype=int)

    def _is_raw_feasible(self, raw: dict) -> bool:
        """Check full feasibility (stress, buckling, twist, tip deflection)."""
        if not isinstance(raw, dict):
            return False

        tol = 1.02

        def _finite_scalar(mapping: dict, *keys: str) -> Optional[float]:
            for key in keys:
                if key not in mapping:
                    continue
                try:
                    value = float(np.asarray(mapping[key]).item())
                except Exception:
                    return None
                if not np.isfinite(value):
                    return None
                return value
            return None

        def _finite_array(values) -> Optional[np.ndarray]:
            try:
                arr = np.asarray(values, dtype=float)
            except Exception:
                return None
            if not np.all(np.isfinite(arr)):
                return None
            return arr

        failure = _finite_scalar(raw, "failure")
        buckling = _finite_scalar(raw, "buckling_index", "buckling")
        twist = _finite_scalar(raw, "twist_max_deg")
        tip_defl = _finite_scalar(raw, "tip_deflection_m")
        if any(v is None for v in (failure, buckling, twist, tip_defl)):
            return False

        if failure > 0.01:
            return False
        if buckling > 0.01:
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
        if main_t is not None or main_r is not None:
            if main_t is None or main_r is None:
                return False
            main_t_arr = _finite_array(main_t)
            main_r_arr = _finite_array(main_r)
            if main_t_arr is None or main_r_arr is None:
                return False
            main_ratio_margin = ratio_limit * main_r_arr - main_t_arr
            if float(np.min(np.real(main_ratio_margin))) < -1e-9:
                return False
            main_step_limit = _optimizer_thickness_step_limit_m(
                getattr(self.cfg, "main_spar", None),
                solver_cfg,
                getattr(self, "materials_db", None),
            )
            if thickness_step_margin_min(main_t_arr, main_step_limit) < -1e-9:
                return False

        rear_cfg = getattr(self.cfg, "rear_spar", None)
        rear_enabled = bool(getattr(rear_cfg, "enabled", False))

        if rear_enabled:
            rear_min_inner_radius = self._rear_min_inner_radius_m()
            dominance_margin = float(
                getattr(
                    solver_cfg,
                    "main_spar_dominance_margin_m",
                    _MAIN_SPAR_DOMINANCE_MARGIN_M,
                )
            )
            rear_main_radius_ratio_min = max(
                float(
                    getattr(
                        solver_cfg,
                        "rear_main_radius_ratio_min",
                        _REAR_MAIN_RADIUS_RATIO_MIN,
                    )
                ),
                0.0,
            )
            rear_r = raw.get("rear_r_seg")
            if main_r is not None and rear_r is not None:
                main_r_arr = _finite_array(main_r)
                rear_r_arr = _finite_array(rear_r)
                if main_r_arr is None or rear_r_arr is None:
                    return False
                radius_margin = main_r_arr - rear_r_arr - dominance_margin
                if float(np.min(np.real(radius_margin))) < -1e-9:
                    return False
                if rear_main_radius_ratio_min > 0.0:
                    ratio_margin = rear_r_arr - rear_main_radius_ratio_min * main_r_arr
                    if float(np.min(np.real(ratio_margin))) < -1e-9:
                        return False

            rear_t = raw.get("rear_t_seg")
            if rear_t is not None and rear_r is not None:
                rear_t_arr = _finite_array(rear_t)
                rear_r_arr = _finite_array(rear_r)
                if rear_t_arr is None or rear_r_arr is None:
                    return False
                rear_ratio_margin = ratio_limit * rear_r_arr - rear_t_arr
                if float(np.min(np.real(rear_ratio_margin))) < -1e-9:
                    return False
                rear_hollow_margin = rear_r_arr - rear_t_arr - rear_min_inner_radius
                if float(np.min(np.real(rear_hollow_margin))) < -1e-9:
                    return False
                rear_step_limit = _optimizer_thickness_step_limit_m(
                    getattr(self.cfg, "rear_spar", None),
                    solver_cfg,
                    getattr(self, "materials_db", None),
                )
                if thickness_step_margin_min(rear_t_arr, rear_step_limit) < -1e-9:
                    return False

            ei_main = raw.get("EI_main_elem")
            ei_rear = raw.get("EI_rear_elem")
            if ei_main is not None and ei_rear is not None:
                ei_main_arr = _finite_array(ei_main)
                ei_rear_arr = _finite_array(ei_rear)
                if ei_main_arr is None or ei_rear_arr is None:
                    return False
                ei_ratio = float(
                    getattr(
                        solver_cfg,
                        "main_spar_ei_ratio",
                        _MAIN_SPAR_EI_RATIO,
                    )
                )
                ei_margin = ei_main_arr - ei_ratio * ei_rear_arr
                if float(np.min(np.real(ei_margin))) < -1e-9:
                    return False
                inboard_ratio = self._rear_inboard_ei_to_main_ratio_max()
                inboard_idx = self._inboard_ei_element_indices(len(ei_main_arr))
                if inboard_ratio < 1.0 and inboard_idx.size > 0:
                    inboard_margin = (
                        inboard_ratio * ei_main_arr[inboard_idx] - ei_rear_arr[inboard_idx]
                    )
                    if float(np.min(np.real(inboard_margin))) < -1e-9:
                        return False

        case_limits = self._constraint_limits_by_case()
        case_outputs = raw.get("cases")
        if case_outputs:
            if not isinstance(case_outputs, dict):
                return False
            default_twist = float(self.cfg.wing.max_tip_twist_deg)
            default_deflection = self.cfg.wing.max_tip_deflection_m
            for case_name, case_raw in case_outputs.items():
                if not isinstance(case_raw, dict):
                    return False
                case_failure = _finite_scalar(case_raw, "failure")
                case_buckling = _finite_scalar(case_raw, "buckling_index", "buckling")
                case_twist = _finite_scalar(case_raw, "twist_max_deg")
                case_deflection = _finite_scalar(case_raw, "tip_deflection_m")
                if any(
                    v is None for v in (case_failure, case_buckling, case_twist, case_deflection)
                ):
                    return False
                if case_failure > 0.01 or case_buckling > 0.01:
                    return False
                twist_limit, deflection_limit = case_limits.get(
                    case_name, (default_twist, default_deflection)
                )
                if case_twist > float(twist_limit) * tol:
                    return False
                if deflection_limit is not None and case_deflection > float(deflection_limit) * tol:
                    return False
            return True

        twist_candidates = [lim[0] for lim in case_limits.values()]
        twist_limit = (
            min(twist_candidates) if twist_candidates else float(self.cfg.wing.max_tip_twist_deg)
        )
        if twist > twist_limit * tol:
            return False

        deflection_candidates = [lim[1] for lim in case_limits.values() if lim[1] is not None]
        if deflection_candidates:
            deflection_limit = min(float(v) for v in deflection_candidates)
            if tip_defl > deflection_limit * tol:
                return False

        return True

    def _normalise_load_case_inputs_for_update(
        self, aero_loads: dict
    ) -> dict[str, tuple[object, dict]]:
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
                f"struct.case_{case_name}.ext_loads"
                if is_multi_case_problem
                else "struct.ext_loads"
            )
            comp = self._prob.model._get_subsystem(ext_loads_path)
            if comp is None:
                raise RuntimeError(
                    f"Cannot locate ExternalLoadsComp at '{ext_loads_path}' to refresh FSI loads."
                )

            n_nodes = int(comp.options["n_nodes"])
            lift, torque = _scaled_case_aero_distributions(
                case_name=case_name,
                load_case=load_case,
                case_loads=case_loads,
                n_nodes=n_nodes,
            )
            comp.options["lift_per_span"] = lift
            comp.options["torque_per_span"] = torque

            struct_y = np.asarray(self.aircraft.wing.y, dtype=float)
            node_spacings = np.zeros(n_nodes)
            dy = np.diff(struct_y)
            node_spacings[0] = dy[0] / 2.0
            node_spacings[-1] = dy[-1] / 2.0
            for i in range(1, n_nodes - 1):
                node_spacings[i] = (dy[i - 1] + dy[i]) / 2.0

            lift_wire_nodes = _lift_wire_node_indices(self.cfg, struct_y)
            wire_precompression = _wire_precompression_for_case(
                self.cfg,
                struct_y,
                node_spacings,
                lift_wire_nodes,
                load_case,
                case_loads,
                case_name=case_name,
            )

            stress_path = (
                f"struct.case_{case_name}.stress" if is_multi_case_problem else "struct.stress"
            )
            buckling_path = (
                f"struct.case_{case_name}.buckling" if is_multi_case_problem else "struct.buckling"
            )
            stress_comp = self._prob.model._get_subsystem(stress_path)
            buckling_comp = self._prob.model._get_subsystem(buckling_path)
            if stress_comp is not None:
                stress_comp.options["wire_precompression"] = wire_precompression
            if buckling_comp is not None:
                buckling_comp.options["wire_precompression"] = wire_precompression

    def analyze(
        self,
        main_t_seg: Optional[np.ndarray] = None,
        main_r_seg: Optional[np.ndarray] = None,
        rear_t_seg: Optional[np.ndarray] = None,
        rear_r_seg: Optional[np.ndarray] = None,
    ) -> OptimizationResult:
        """Run a single structural analysis (no optimization).

        Parameters
        ----------
        main_t_seg : (n_seg,) array or None
            Main spar segment wall thicknesses [m].
            If None, uses the current values.
        main_r_seg : (n_seg,) array or None
            Main spar outer radii [m].
            If None, uses the current values.
        rear_t_seg : (n_seg,) array or None
            Rear spar segment thicknesses [m].
        rear_r_seg : (n_seg,) array or None
            Rear spar outer radii [m].
        """
        if main_t_seg is not None:
            self._prob.set_val("struct.seg_mapper.main_t_seg", main_t_seg, units="m")
        if main_r_seg is not None:
            self._prob.set_val("struct.seg_mapper.main_r_seg", main_r_seg, units="m")
        if rear_t_seg is not None and self.cfg.rear_spar.enabled:
            self._prob.set_val("struct.seg_mapper.rear_t_seg", rear_t_seg, units="m")
        if rear_r_seg is not None and self.cfg.rear_spar.enabled:
            self._prob.set_val("struct.seg_mapper.rear_r_seg", rear_r_seg, units="m")

        raw = run_analysis(self._prob)
        return self._to_result(raw, success=True, message="Analysis complete")

    def analyze_dual_beam(
        self,
        main_t_seg: Optional[np.ndarray] = None,
        main_r_seg: Optional[np.ndarray] = None,
        rear_t_seg: Optional[np.ndarray] = None,
        rear_r_seg: Optional[np.ndarray] = None,
    ):
        """Run the internal dual-beam analysis path for the current design variables.

        This does not modify the existing optimization topology or Phase I gate.
        It is a separate analysis-only route for higher-fidelity model-form checks.
        """
        from hpa_mdo.structure.dual_beam_analysis import run_dual_beam_analysis

        design_result = self.analyze(
            main_t_seg=main_t_seg,
            main_r_seg=main_r_seg,
            rear_t_seg=rear_t_seg,
            rear_r_seg=rear_r_seg,
        )

        case_entries = _normalise_load_case_inputs(self.cfg, self.aero_loads)
        case_name = next(iter(case_entries))
        load_case, case_loads = case_entries[case_name]
        lift, torque = _scaled_case_aero_distributions(
            case_name=case_name,
            load_case=load_case,
            case_loads=case_loads,
            n_nodes=self.aircraft.wing.n_stations,
        )
        export_loads = {
            "lift_per_span": lift,
            "torque_per_span": torque,
            "total_lift": float(np.trapezoid(lift, self.aircraft.wing.y)),
        }

        return run_dual_beam_analysis(
            cfg=self.cfg,
            aircraft=self.aircraft,
            opt_result=design_result,
            export_loads=export_loads,
            materials_db=self.materials_db,
            bc_penalty=self.cfg.solver.fem_bc_penalty,
        )

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
                raw = run_analysis(self._prob)
                if self._is_raw_feasible(raw):
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
        max_main_thickness_step = _optimizer_thickness_step_limit_m(
            cfg.main_spar,
            solver_cfg,
            self.materials_db,
        )
        max_rear_thickness_step = (
            _optimizer_thickness_step_limit_m(cfg.rear_spar, solver_cfg, self.materials_db)
            if rear_on
            else float("inf")
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
        rear_main_radius_ratio_min = max(
            float(
                getattr(
                    solver_cfg,
                    "rear_main_radius_ratio_min",
                    _REAR_MAIN_RADIUS_RATIO_MIN,
                )
            ),
            0.0,
        )
        rear_min_inner_radius = self._rear_min_inner_radius_m()
        rear_inboard_ei_to_main_ratio_max = self._rear_inboard_ei_to_main_ratio_max()
        n_elem_guess = None
        if hasattr(self, "aircraft") and self.aircraft is not None:
            n_elem_guess = int(self.aircraft.wing.n_stations - 1)
        else:
            struct_group = getattr(getattr(self._prob, "model", None), "struct", None)
            elem_centres = np.asarray(
                getattr(struct_group, "_elem_centres", np.array([])), dtype=float
            )
            if elem_centres.size > 0:
                n_elem_guess = int(elem_centres.size)
            else:
                n_elem_guess = n_seg
        inboard_ei_element_indices = self._inboard_ei_element_indices(n_elem_guess)
        # DV layout: [main_t_seg..., main_r_seg..., rear_t_seg..., rear_r_seg...]
        min_t_main = cfg.main_spar.min_wall_thickness
        min_t_rear = cfg.rear_spar.min_wall_thickness if rear_on else min_t_main

        bounds_main_t = [(min_t_main, max_t)] * n_seg
        bounds_main_r = [(min_r, max_r)] * n_seg
        bounds_rear_t = [(min_t_rear, max_t)] * n_seg if rear_on else []
        bounds_rear_r = [(min_r, max_r)] * n_seg if rear_on else []
        bounds = bounds_main_t + bounds_main_r + bounds_rear_t + bounds_rear_r

        def _set_design_vars(x: np.ndarray) -> None:
            x_arr = np.asarray(x, dtype=float)
            self._prob.set_val("struct.seg_mapper.main_t_seg", x_arr[:n_seg], units="m")
            self._prob.set_val("struct.seg_mapper.main_r_seg", x_arr[n_seg : 2 * n_seg], units="m")
            if rear_on:
                self._prob.set_val(
                    "struct.seg_mapper.rear_t_seg", x_arr[2 * n_seg : 3 * n_seg], units="m"
                )
                self._prob.set_val("struct.seg_mapper.rear_r_seg", x_arr[3 * n_seg :], units="m")

        max_twist, max_defl = self._single_case_limits()
        t_total_start = perf_counter()

        evaluator = _ScipyBlackBoxEvaluator(
            self._prob,
            n_seg=n_seg,
            rear_on=rear_on,
            max_twist=max_twist,
            max_defl=max_defl,
            max_thickness_to_radius_ratio=ratio_limit,
            max_main_thickness_step_m=max_main_thickness_step,
            max_rear_thickness_step_m=max_rear_thickness_step,
            main_spar_dominance_margin_m=dominance_margin,
            main_spar_ei_ratio=main_spar_ei_ratio,
            rear_main_radius_ratio_min=rear_main_radius_ratio_min,
            rear_min_inner_radius_m=rear_min_inner_radius,
            rear_inboard_ei_to_main_ratio_max=rear_inboard_ei_to_main_ratio_max,
            inboard_ei_element_indices=inboard_ei_element_indices,
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
                de_func,
                bounds=bounds,
                seed=42,
                maxiter=200,
                tol=1e-5,
                polish=False,
                init="sobol",
                workers=de_workers,
                popsize=20,
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
                    lambda x, n=n_seg, eta=ratio_limit: np.min(
                        eta * np.asarray(x, dtype=float)[n : 2 * n] - np.asarray(x, dtype=float)[:n]
                    )
                ),
            },
        ]
        if n_seg > 1:
            constraints.append(
                {
                    "type": "ineq",
                    "fun": (
                        lambda x, n=n_seg, max_step=max_main_thickness_step: (
                            thickness_step_margin_min(np.asarray(x, dtype=float)[:n], max_step)
                        )
                    ),
                }
            )
        if rear_on:
            constraints.append(
                {
                    "type": "ineq",
                    "fun": (
                        lambda x, n=n_seg, eta=ratio_limit: np.min(
                            eta * np.asarray(x, dtype=float)[3 * n : 4 * n]
                            - np.asarray(x, dtype=float)[2 * n : 3 * n]
                        )
                    ),
                }
            )
            if n_seg > 1:
                constraints.append(
                    {
                        "type": "ineq",
                        "fun": (
                            lambda x, n=n_seg, max_step=max_rear_thickness_step: (
                                thickness_step_margin_min(
                                    np.asarray(x, dtype=float)[2 * n : 3 * n], max_step
                                )
                            )
                        ),
                    }
                )
            constraints.append(
                {
                    "type": "ineq",
                    "fun": (
                        lambda x, n=n_seg, min_core=rear_min_inner_radius: np.min(
                            np.asarray(x, dtype=float)[3 * n : 4 * n]
                            - np.asarray(x, dtype=float)[2 * n : 3 * n]
                            - min_core
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
            if rear_main_radius_ratio_min > 0.0:
                constraints.append(
                    {
                        "type": "ineq",
                        "fun": lambda x: evaluator.evaluate(x)["rear_main_radius_ratio_margin_min"],
                    }
                )
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda x: evaluator.evaluate(x)["ei_ratio_margin_min"],
                }
            )
            if inboard_ei_element_indices.size > 0 and rear_inboard_ei_to_main_ratio_max < 1.0:
                constraints.append(
                    {
                        "type": "ineq",
                        "fun": lambda x: evaluator.evaluate(x)["rear_inboard_ei_margin_min"],
                    }
                )
        if max_defl < float("inf"):
            constraints.append(
                {"type": "ineq", "fun": lambda x: max_defl - evaluator.evaluate(x)["tip_defl"]}
            )

        t_slsqp_start = perf_counter()
        slsqp = scipy_minimize(
            obj,
            x_de,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
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

        def _min_finite_or_neg_inf(arr: np.ndarray) -> float:
            arr = np.asarray(arr, dtype=float)
            if arr.size == 0 or not np.all(np.isfinite(arr)):
                return float("-inf")
            return float(np.min(arr))

        def _ratio_margin_mins(x: np.ndarray) -> tuple[float, Optional[float]]:
            x_arr = np.asarray(x, dtype=float)
            if not np.all(np.isfinite(x_arr)):
                return float("-inf"), (float("-inf") if rear_on else None)
            main_margin_min = _min_finite_or_neg_inf(
                ratio_limit * x_arr[n_seg : 2 * n_seg] - x_arr[:n_seg]
            )
            rear_margin_min: Optional[float] = None
            if rear_on:
                rear_margin_min = _min_finite_or_neg_inf(
                    ratio_limit * x_arr[3 * n_seg : 4 * n_seg] - x_arr[2 * n_seg : 3 * n_seg]
                )
            return main_margin_min, rear_margin_min

        def _hollow_margin_mins(x: np.ndarray) -> tuple[float, Optional[float]]:
            x_arr = np.asarray(x, dtype=float)
            if not np.all(np.isfinite(x_arr)):
                return float("-inf"), (float("-inf") if rear_on else None)
            main_hollow_margin_min = _min_finite_or_neg_inf(
                x_arr[n_seg : 2 * n_seg] - x_arr[:n_seg]
            )
            rear_hollow_margin_min: Optional[float] = None
            if rear_on:
                rear_hollow_margin_min = _min_finite_or_neg_inf(
                    x_arr[3 * n_seg : 4 * n_seg]
                    - x_arr[2 * n_seg : 3 * n_seg]
                    - rear_min_inner_radius
                )
            return main_hollow_margin_min, rear_hollow_margin_min

        def _candidate_valid(
            eval_result: dict[str, float],
            main_ratio_margin_min: float,
            main_hollow_margin_min: float,
            rear_ratio_margin_min: Optional[float],
            rear_hollow_margin_min: Optional[float],
        ) -> bool:
            if not _is_eval_valid(eval_result, rear_on=rear_on):
                return False
            if not np.isfinite(main_ratio_margin_min) or not np.isfinite(main_hollow_margin_min):
                return False
            if rear_on:
                if rear_ratio_margin_min is None or rear_hollow_margin_min is None:
                    return False
                if not np.isfinite(rear_ratio_margin_min) or not np.isfinite(
                    rear_hollow_margin_min
                ):
                    return False
            return True

        def _constraint_violation_score(
            eval_result: dict[str, float],
            is_valid: bool,
            main_ratio_margin_min: float,
            main_hollow_margin_min: float,
            rear_ratio_margin_min: Optional[float],
            rear_hollow_margin_min: Optional[float],
        ) -> float:
            if not is_valid:
                return float("inf")

            violation = (
                max(0.0, eval_result["failure"])
                + max(0.0, eval_result["twist"] - max_twist)
                + max(0.0, eval_result["buckling"])
            )
            if max_defl < float("inf"):
                violation += max(0.0, eval_result["tip_defl"] - max_defl) / max(max_defl, 1e-9)
            violation += max(0.0, -main_ratio_margin_min) / max(ratio_limit * min_r, 1e-9)
            violation += max(0.0, -main_hollow_margin_min) / max(min_r, 1e-9)
            violation += max(0.0, -eval_result["main_thickness_step_margin_min"]) / max(
                max_main_thickness_step, 1e-9
            )
            if rear_on:
                if rear_ratio_margin_min is None or rear_hollow_margin_min is None:
                    return float("inf")
                violation += max(0.0, -rear_ratio_margin_min) / max(ratio_limit * min_r, 1e-9)
                violation += max(0.0, -rear_hollow_margin_min) / max(rear_min_inner_radius, 1e-9)
                violation += max(0.0, -eval_result["rear_thickness_step_margin_min"]) / max(
                    max_rear_thickness_step, 1e-9
                )
                violation += max(0.0, -eval_result["radius_dominance_margin_min"]) / max(
                    dominance_margin, 1e-9
                )
                if rear_main_radius_ratio_min > 0.0:
                    violation += max(0.0, -eval_result["rear_main_radius_ratio_margin_min"]) / max(
                        rear_main_radius_ratio_min * min_r, 1e-9
                    )
                violation += max(0.0, -eval_result["ei_ratio_margin_min"])
                violation += max(0.0, -eval_result["rear_inboard_ei_margin_min"])

            return float(violation) if np.isfinite(violation) else float("inf")

        de_main_ratio_margin_min, de_rear_ratio_margin_min = _ratio_margin_mins(x_de)
        sq_main_ratio_margin_min, sq_rear_ratio_margin_min = _ratio_margin_mins(slsqp.x)
        de_main_hollow_margin_min, de_rear_hollow_margin_min = _hollow_margin_mins(x_de)
        sq_main_hollow_margin_min, sq_rear_hollow_margin_min = _hollow_margin_mins(slsqp.x)
        de_valid = _candidate_valid(
            r_de,
            de_main_ratio_margin_min,
            de_main_hollow_margin_min,
            de_rear_ratio_margin_min,
            de_rear_hollow_margin_min,
        )
        sq_valid = _candidate_valid(
            r_sq,
            sq_main_ratio_margin_min,
            sq_main_hollow_margin_min,
            sq_rear_ratio_margin_min,
            sq_rear_hollow_margin_min,
        )

        de_feas = de_valid and (
            r_de["failure"] <= tol_f
            and r_de["buckling"] <= tol_b
            and r_de["twist"] <= tol_tw
            and r_de["tip_defl"] <= tol_df
            and de_main_ratio_margin_min >= 0.0
            and de_main_hollow_margin_min >= 0.0
            and r_de["main_thickness_step_margin_min"] >= 0.0
            and (
                not rear_on
                or (de_rear_ratio_margin_min is not None and de_rear_ratio_margin_min >= 0.0)
            )
            and (
                not rear_on
                or (de_rear_hollow_margin_min is not None and de_rear_hollow_margin_min >= 0.0)
            )
            and (not rear_on or r_de["rear_thickness_step_margin_min"] >= 0.0)
            and (not rear_on or r_de["radius_dominance_margin_min"] >= 0.0)
            and (
                not rear_on
                or rear_main_radius_ratio_min <= 0.0
                or r_de["rear_main_radius_ratio_margin_min"] >= 0.0
            )
            and (not rear_on or r_de["ei_ratio_margin_min"] >= 0.0)
            and (not rear_on or r_de["rear_inboard_ei_margin_min"] >= 0.0)
        )
        sq_feas = sq_valid and (
            r_sq["failure"] <= tol_f
            and r_sq["buckling"] <= tol_b
            and r_sq["twist"] <= tol_tw
            and r_sq["tip_defl"] <= tol_df
            and sq_main_ratio_margin_min >= 0.0
            and sq_main_hollow_margin_min >= 0.0
            and r_sq["main_thickness_step_margin_min"] >= 0.0
            and (
                not rear_on
                or (sq_rear_ratio_margin_min is not None and sq_rear_ratio_margin_min >= 0.0)
            )
            and (
                not rear_on
                or (sq_rear_hollow_margin_min is not None and sq_rear_hollow_margin_min >= 0.0)
            )
            and (not rear_on or r_sq["rear_thickness_step_margin_min"] >= 0.0)
            and (not rear_on or r_sq["radius_dominance_margin_min"] >= 0.0)
            and (
                not rear_on
                or rear_main_radius_ratio_min <= 0.0
                or r_sq["rear_main_radius_ratio_margin_min"] >= 0.0
            )
            and (not rear_on or r_sq["ei_ratio_margin_min"] >= 0.0)
            and (not rear_on or r_sq["rear_inboard_ei_margin_min"] >= 0.0)
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
            try:
                _set_design_vars(slsqp.x)
                slsqp_raw = run_analysis(self._prob)
                if not self._is_raw_feasible(slsqp_raw):
                    failure_v = float(np.asarray(slsqp_raw.get("failure", np.nan)).item())
                    buckling_v = float(
                        np.asarray(
                            slsqp_raw.get("buckling_index", slsqp_raw.get("buckling", np.nan))
                        ).item()
                    )
                    twist_v = float(np.asarray(slsqp_raw.get("twist_max_deg", np.nan)).item())
                    tip_defl_v = float(np.asarray(slsqp_raw.get("tip_deflection_m", np.nan)).item())
                    reject_reasons: list[str] = []
                    if np.isfinite(failure_v) and failure_v > 0.01:
                        reject_reasons.append("failure")
                    if np.isfinite(buckling_v) and buckling_v > 0.01:
                        reject_reasons.append("buckling")
                    if np.isfinite(twist_v) and twist_v > max_twist * 1.02:
                        reject_reasons.append("twist")
                    if (
                        max_defl < float("inf")
                        and np.isfinite(tip_defl_v)
                        and tip_defl_v > max_defl * 1.02
                    ):
                        reject_reasons.append("tip_deflection")
                    if not reject_reasons:
                        reject_reasons.append("other_feasibility_constraints")
                    logger.warning(
                        "SLSQP candidate rejected by _is_raw_feasible; falling back to DE. "
                        "reasons=%s; failure=%.6f; buckling=%.6f; twist=%.6f (limit=%.6f); "
                        "tip_deflection=%.6f (limit=%.6f)",
                        ",".join(reject_reasons),
                        failure_v,
                        buckling_v,
                        twist_v,
                        max_twist,
                        tip_defl_v,
                        max_defl,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to log SLSQP rejection diagnostics before DE fallback: %s: %s",
                    type(exc).__name__,
                    exc,
                )
        else:
            # Neither feasible — pick the one with less constraint violation
            v_de = _constraint_violation_score(
                r_de,
                de_valid,
                de_main_ratio_margin_min,
                de_main_hollow_margin_min,
                de_rear_ratio_margin_min,
                de_rear_hollow_margin_min,
            )
            v_sq = _constraint_violation_score(
                r_sq,
                sq_valid,
                sq_main_ratio_margin_min,
                sq_main_hollow_margin_min,
                sq_rear_ratio_margin_min,
                sq_rear_hollow_margin_min,
            )

            x_best = slsqp.x if v_sq <= v_de else x_de
            msg = "scipy: no fully feasible solution — best compromise"

        # Set best solution and extract full results
        _set_design_vars(x_best)
        raw = run_analysis(self._prob)
        best_r = evaluator.evaluate(x_best)
        best_valid = _is_eval_valid(best_r, rear_on=rear_on)
        success = best_valid and self._is_raw_feasible(raw)
        success = success and best_r["main_thickness_step_margin_min"] >= 0.0
        if rear_on:
            success = (
                success
                and best_r["rear_hollow_margin_min"] >= 0.0
                and best_r["rear_thickness_step_margin_min"] >= 0.0
                and best_r["radius_dominance_margin_min"] >= 0.0
                and (
                    rear_main_radius_ratio_min <= 0.0
                    or best_r["rear_main_radius_ratio_margin_min"] >= 0.0
                )
                and best_r["ei_ratio_margin_min"] >= 0.0
                and best_r["rear_inboard_ei_margin_min"] >= 0.0
            )
        total_s = perf_counter() - t_total_start
        logger.info(
            "    Evaluator counters: n_run_model=%d, n_cache_hit=%d, n_cache_miss=%d",
            int(getattr(evaluator, "_n_run_model", -1)),
            int(getattr(evaluator, "_n_cache_hit", -1)),
            int(getattr(evaluator, "_n_cache_miss", -1)),
        )
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
                strain_env_case = case_raw.get("strain_envelope") or {}
                case_metrics[case_name] = {
                    "failure_index": float(case_raw["failure"]),
                    "buckling_index": float(case_raw["buckling_index"]),
                    "tip_deflection_m": float(case_raw["tip_deflection_m"]),
                    "twist_max_deg": float(case_raw["twist_max_deg"]),
                    "max_stress_main_Pa": (
                        float(np.max(vm_main_case))
                        if vm_main_case is not None and len(vm_main_case) > 0
                        else 0.0
                    ),
                    "max_stress_rear_Pa": (
                        float(np.max(vm_rear_case))
                        if vm_rear_case is not None and len(vm_rear_case) > 0
                        else 0.0
                    ),
                    "epsilon_x_absmax": _max_array_metric(
                        strain_env_case.get("epsilon_x_absmax")
                    ),
                    "kappa_absmax": _max_array_metric(strain_env_case.get("kappa_absmax")),
                    "torsion_rate_absmax": _max_array_metric(
                        strain_env_case.get("torsion_rate_absmax")
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
        twist_limit = (
            min(twist_candidates) if twist_candidates else float(cfg.wing.max_tip_twist_deg)
        )
        deflection_limit = (
            min(float(v) for v in deflection_candidates) if deflection_candidates else None
        )

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
            nodes=raw.get("nodes"),
            disp=disp,
            vonmises_main=vm_main,
            vonmises_rear=vm_rear if vm_rear is not None and len(vm_rear) > 0 else None,
            strain_envelope=raw.get("strain_envelope", {}),
            timing_s=timing_s or {},
            max_twist_limit_deg=twist_limit,
        )
