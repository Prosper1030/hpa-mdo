"""Spar structural optimizer using SQP (Sequential Quadratic Programming).

Minimises spar mass subject to:
    1. Stress constraint  : σ_max ≤ σ_allow / SF
    2. Deflection constraint : u_tip ≤ u_target  (or u_tip == u_target)
    3. Non-negative deflection everywhere
    4. Minimum wall thickness (enforced via bounds)

Design variables: [d_i_root, d_i_tip] — inner diameters at root and tip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
from scipy.optimize import minimize, OptimizeResult, differential_evolution

from hpa_mdo.core.materials import Material
from hpa_mdo.structure.beam_model import EulerBernoulliBeam, BeamResult
from hpa_mdo.structure.spar import TubularSpar


@dataclass
class OptimizationResult:
    """Output of the spar optimization."""
    success: bool
    message: str
    d_i_root: float           # optimal inner diameter at root [m]
    d_i_tip: float            # optimal inner diameter at tip [m]
    spar_mass_kg: float       # minimised spar mass for half-span [kg]
    spar_mass_full_kg: float  # full-span spar mass [kg]
    max_stress_Pa: float      # max bending stress [Pa]
    allowable_stress_Pa: float
    tip_deflection_m: float
    beam_result: Optional[BeamResult] = None
    spar_props: Optional[dict] = None
    scipy_result: Optional[OptimizeResult] = field(default=None, repr=False)


class SparOptimizer:
    """Spar mass minimiser with cached evaluations.

    Uses a single cached evaluation per design point so that the
    objective and all constraint functions see consistent results,
    avoiding the gradient confusion that plagued separate evaluations.
    """

    def __init__(
        self,
        spar: TubularSpar,
        beam_solver: EulerBernoulliBeam,
        f_ext: np.ndarray,
        safety_factor: float = 4.0,
        max_tip_deflection: Optional[float] = None,
        target_tip_deflection: Optional[float] = None,
        point_loads: Optional[dict] = None,
    ):
        self.spar = spar
        self.beam = beam_solver
        self.f_ext_base = f_ext
        self.safety_factor = safety_factor
        self.max_tip_deflection = max_tip_deflection
        self.target_tip_deflection = target_tip_deflection
        self.point_loads = point_loads

        self.material: Material = spar.material
        self.sigma_allow = self.material.tensile_strength / self.safety_factor

        # Evaluation cache — avoids redundant beam solves within one
        # optimizer iteration (objective + constraints share the result).
        self._cache_key: Optional[tuple] = None
        self._cache_val: Optional[tuple] = None

    def _evaluate(self, x: np.ndarray) -> tuple[float, BeamResult, dict, float]:
        """Evaluate spar mass, beam result, props, max_stress for design x.

        Returns (mass, beam_result, spar_props, max_stress_Pa).
        """
        key = (float(x[0]), float(x[1]))
        if self._cache_key == key and self._cache_val is not None:
            return self._cache_val

        d_i_root, d_i_tip = x
        props = self.spar.compute(d_i_root, d_i_tip)

        g = 9.80665
        spar_weight_per_span = props["mass_per_length"] * g
        f_net = self.f_ext_base - spar_weight_per_span

        result = self.beam.solve(
            y=self.spar.y,
            EI=props["EI"],
            f_ext=f_net,
            outer_radius=props["outer_radius"],
            point_loads=self.point_loads,
        )

        max_stress = float(np.max(np.abs(result.stress * self.material.E)))
        val = (props["total_mass"], result, props, max_stress)
        self._cache_key = key
        self._cache_val = val
        return val

    def _penalty_objective(self, x: np.ndarray) -> float:
        """Combined objective with penalty terms for robustness.

        Uses an augmented Lagrangian-style penalty so that gradient-based
        optimizers see a smooth landscape even when starting far from
        the feasible region.
        """
        mass, result, props, max_stress = self._evaluate(x)

        penalty = 0.0
        rho = 100.0  # penalty weight

        # Stress violation penalty
        stress_violation = max(0.0, max_stress - self.sigma_allow)
        penalty += rho * (stress_violation / self.sigma_allow) ** 2

        # Deflection violation penalty
        if self.max_tip_deflection is not None:
            defl_violation = max(0.0, result.tip_deflection - self.max_tip_deflection)
            penalty += rho * (defl_violation / self.max_tip_deflection) ** 2

        if self.target_tip_deflection is not None:
            defl_err = (result.tip_deflection - self.target_tip_deflection)
            penalty += rho * (defl_err / self.target_tip_deflection) ** 2

        # Negative deflection penalty
        min_defl = float(np.min(result.deflection))
        if min_defl < 0:
            penalty += rho * (min_defl ** 2)

        return mass * (1.0 + penalty)

    def optimize(
        self,
        method: str = "SLSQP",
        x0: Optional[np.ndarray] = None,
        tol: float = 1e-6,
        maxiter: int = 500,
    ) -> OptimizationResult:
        """Run the optimization.

        Strategy: first run differential_evolution (global, gradient-free)
        to find a good starting point, then refine with SLSQP.
        """
        bounds = self.spar.design_variable_bounds()

        # --- Phase 1: Global search with differential_evolution ---
        de_result = differential_evolution(
            self._penalty_objective,
            bounds=bounds,
            seed=42,
            maxiter=200,
            tol=1e-4,
            polish=False,
            init="sobol",
        )
        x_de = de_result.x

        # --- Phase 2: Local refinement with constrained optimizer ---
        if x0 is None:
            x0 = x_de

        self._cache_key = None  # clear cache

        def objective(x):
            mass, _, _, _ = self._evaluate(x)
            return mass

        constraints = []

        def stress_constraint(x):
            _, _, _, max_stress = self._evaluate(x)
            return self.sigma_allow - max_stress
        constraints.append({"type": "ineq", "fun": stress_constraint})

        if self.target_tip_deflection is not None:
            def deflection_eq(x):
                _, result, _, _ = self._evaluate(x)
                return result.tip_deflection - self.target_tip_deflection
            constraints.append({"type": "eq", "fun": deflection_eq})
        elif self.max_tip_deflection is not None:
            def deflection_ineq(x):
                _, result, _, _ = self._evaluate(x)
                return self.max_tip_deflection - result.tip_deflection
            constraints.append({"type": "ineq", "fun": deflection_ineq})

        def no_negative_deflection(x):
            _, result, _, _ = self._evaluate(x)
            return float(np.min(result.deflection))
        constraints.append({"type": "ineq", "fun": no_negative_deflection})

        res = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            tol=tol,
            options={"maxiter": maxiter, "disp": False, "ftol": tol},
        )

        # If SLSQP failed, fall back to the DE result
        if not res.success:
            mass_slsqp, _, _, stress_slsqp = self._evaluate(res.x)
            mass_de, _, _, stress_de = self._evaluate(x_de)
            # Pick the lighter feasible solution
            slsqp_feasible = stress_slsqp <= self.sigma_allow * 1.01
            de_feasible = stress_de <= self.sigma_allow * 1.01
            if de_feasible and (not slsqp_feasible or mass_de < mass_slsqp):
                res.x = x_de
                res.message = f"DE solution used (SLSQP failed: {res.message})"

        # Final evaluation at optimum
        mass, beam_result, spar_props, max_stress = self._evaluate(res.x)

        return OptimizationResult(
            success=res.success or max_stress <= self.sigma_allow * 1.01,
            message=res.message,
            d_i_root=float(res.x[0]),
            d_i_tip=float(res.x[1]),
            spar_mass_kg=mass,
            spar_mass_full_kg=mass * 2,
            max_stress_Pa=max_stress,
            allowable_stress_Pa=self.sigma_allow,
            tip_deflection_m=beam_result.tip_deflection,
            beam_result=beam_result,
            spar_props=spar_props,
            scipy_result=res,
        )
