"""Fluid–Structure Interaction coupling module.

Supports two coupling strategies:

1. **One-way** (recommended for initial design):
   Aero loads computed on the undeformed wing → structural deflection.
   As shown in the reference paper (Vanderhoydonck et al., 2016), for
   high-aspect-ratio HPA wings, the first iteration is already within
   0.2% of the converged FSI result.

2. **Two-way** (iterative Gauss–Seidel):
   Aero → Structure → update wing shape → re-run Aero → ...
   Converges when tip deflection change < tolerance.

For two-way coupling, the aero solver must support re-meshing on a
deformed geometry. VSPAero via the OpenVSP Python API can do this;
XFLR5 cannot (one-way only).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.structure.beam_model import EulerBernoulliBeam, BeamResult
from hpa_mdo.structure.spar import TubularSpar
from hpa_mdo.structure.optimizer import SparOptimizer, OptimizationResult
from hpa_mdo.core.materials import Material


@dataclass
class FSIResult:
    """Result of an FSI coupling analysis."""
    converged: bool
    n_iterations: int
    tip_deflection_history: list[float]
    optimization_result: OptimizationResult
    final_beam_result: BeamResult
    deformed_y: np.ndarray
    deformed_z: np.ndarray


class FSICoupling:
    """Aeroelastic coupling engine.

    Orchestrates the load transfer between aerodynamic and structural
    solvers, optionally iterating to convergence.
    """

    def __init__(
        self,
        spar: TubularSpar,
        material: Material,
        load_mapper: LoadMapper,
        safety_factor: float = 4.0,
        max_tip_deflection: float | None = None,
        target_tip_deflection: float | None = None,
    ):
        self.spar = spar
        self.material = material
        self.mapper = load_mapper
        self.beam = EulerBernoulliBeam()
        self.safety_factor = safety_factor
        self.max_tip_deflection = max_tip_deflection
        self.target_tip_deflection = target_tip_deflection

    def run_one_way(
        self,
        aero_load: SpanwiseLoad,
        load_factor: float = 1.0,
        optimizer_method: str = "SLSQP",
    ) -> FSIResult:
        """One-way coupling: aero → structure (single pass).

        Parameters
        ----------
        aero_load : SpanwiseLoad
            Aerodynamic load from any parser.
        load_factor : float
            Design load factor (e.g. 3.0 for 2G * 1.5).
        optimizer_method : str
            SciPy optimization method.
        """
        # Map aero loads onto structural nodes
        mapped = self.mapper.map_loads(
            aero_load, self.spar.y, scale_factor=load_factor
        )
        f_ext = mapped["lift_per_span"]

        # Run structural optimization
        opt = SparOptimizer(
            spar=self.spar,
            beam_solver=self.beam,
            f_ext=f_ext,
            safety_factor=self.safety_factor,
            max_tip_deflection=self.max_tip_deflection,
            target_tip_deflection=self.target_tip_deflection,
        )
        result = opt.optimize(method=optimizer_method)

        # Compute deformed shape
        defl = result.beam_result.deflection if result.beam_result else np.zeros_like(self.spar.y)
        deformed_z = defl  # deflection is in the Z direction

        return FSIResult(
            converged=True,
            n_iterations=1,
            tip_deflection_history=[result.tip_deflection_m],
            optimization_result=result,
            final_beam_result=result.beam_result,
            deformed_y=self.spar.y,
            deformed_z=deformed_z,
        )

    def run_two_way(
        self,
        aero_load_func,
        load_factor: float = 1.0,
        max_iter: int = 20,
        tol: float = 1e-3,
        optimizer_method: str = "SLSQP",
    ) -> FSIResult:
        """Two-way iterative FSI coupling.

        Parameters
        ----------
        aero_load_func : callable
            Function(deformed_y, deformed_z) -> SpanwiseLoad
            Must re-compute aero loads on the deformed wing shape.
            Typically wraps OpenVSP Python API calls.
        load_factor : float
            Design load factor.
        max_iter : int
            Maximum coupling iterations.
        tol : float
            Convergence tolerance on tip deflection change [m].
        optimizer_method : str
            SciPy optimization method.
        """
        tip_history = []
        deformed_z = np.zeros_like(self.spar.y)
        prev_tip = 0.0

        for iteration in range(1, max_iter + 1):
            # Get aero loads on current (possibly deformed) shape
            aero_load = aero_load_func(self.spar.y, deformed_z)

            # Map loads
            mapped = self.mapper.map_loads(
                aero_load, self.spar.y, scale_factor=load_factor
            )
            f_ext = mapped["lift_per_span"]

            # Structural optimization
            opt = SparOptimizer(
                spar=self.spar,
                beam_solver=self.beam,
                f_ext=f_ext,
                safety_factor=self.safety_factor,
                max_tip_deflection=self.max_tip_deflection,
                target_tip_deflection=self.target_tip_deflection,
            )
            result = opt.optimize(method=optimizer_method)

            deformed_z = result.beam_result.deflection if result.beam_result else deformed_z
            current_tip = result.tip_deflection_m
            tip_history.append(current_tip)

            # Check convergence
            if iteration > 1 and abs(current_tip - prev_tip) < tol:
                return FSIResult(
                    converged=True,
                    n_iterations=iteration,
                    tip_deflection_history=tip_history,
                    optimization_result=result,
                    final_beam_result=result.beam_result,
                    deformed_y=self.spar.y,
                    deformed_z=deformed_z,
                )

            prev_tip = current_tip

        return FSIResult(
            converged=False,
            n_iterations=max_iter,
            tip_deflection_history=tip_history,
            optimization_result=result,
            final_beam_result=result.beam_result,
            deformed_y=self.spar.y,
            deformed_z=deformed_z,
        )
