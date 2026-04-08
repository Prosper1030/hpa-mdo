"""Fluid–Structure Interaction coupling for the OpenMDAO structural stack."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.structure.optimizer import OptimizationResult, SparOptimizer


@dataclass
class FSIResult:
    """Result of an FSI coupling analysis."""

    converged: bool
    n_iterations: int
    tip_deflection_history: list[float]
    optimization_result: OptimizationResult
    final_beam_result: Optional[np.ndarray]
    deformed_y: np.ndarray
    deformed_z: np.ndarray


class FSICoupling:
    """Aeroelastic coupling engine using the current OpenMDAO path."""

    def __init__(
        self,
        cfg,
        aircraft,
        materials_db,
        load_mapper: Optional[LoadMapper] = None,
    ):
        self.cfg = cfg
        self.aircraft = aircraft
        self.materials_db = materials_db
        self.mapper = load_mapper or LoadMapper()
        # Reuse one optimizer instance for iterative FSI to avoid paying
        # OpenMDAO setup overhead on every coupling iteration.
        self._optimizer: Optional[SparOptimizer] = None

    @staticmethod
    def _normalize_optimizer_method(method: str) -> str:
        raw = method.strip().lower()
        if raw in {"openmdao", "scipy", "auto"}:
            return raw
        if raw in {"slsqp", "snopt", "ipopt"}:
            return "openmdao"
        return "auto"

    def _solve_once(
        self,
        aero_load: SpanwiseLoad,
        load_factor: float,
        optimizer_method: str,
    ) -> tuple[OptimizationResult, np.ndarray]:
        mapped = self.mapper.map_loads(
            aero_load,
            self.aircraft.wing.y,
            scale_factor=load_factor,
            actual_velocity=self.cfg.flight.velocity,
            actual_density=self.cfg.flight.air_density,
        )

        if self._optimizer is None:
            self._optimizer = SparOptimizer(
                self.cfg,
                self.aircraft,
                mapped,
                self.materials_db,
            )
        else:
            self._optimizer.update_aero_loads(mapped)

        result = self._optimizer.optimize(
            method=self._normalize_optimizer_method(optimizer_method)
        )
        return result, self._extract_deformed_z(result)

    def _extract_deformed_z(self, result: OptimizationResult) -> np.ndarray:
        span_y = np.asarray(self.aircraft.wing.y)
        if result.disp is None:
            return np.zeros_like(span_y, dtype=float)

        disp = np.asarray(result.disp)
        if disp.ndim == 2 and disp.shape[0] == span_y.size and disp.shape[1] >= 3:
            return np.asarray(disp[:, 2], dtype=float)

        if disp.ndim == 1 and disp.size == span_y.size * 6:
            return np.asarray(disp.reshape(span_y.size, 6)[:, 2], dtype=float)

        return np.zeros_like(span_y, dtype=float)

    def run_one_way(
        self,
        aero_load: SpanwiseLoad,
        load_factor: float = 1.0,
        optimizer_method: str = "openmdao",
    ) -> FSIResult:
        """One-way coupling: aero -> structure (single pass)."""

        result, deformed_z = self._solve_once(aero_load, load_factor, optimizer_method)
        return FSIResult(
            converged=True,
            n_iterations=1,
            tip_deflection_history=[result.tip_deflection_m],
            optimization_result=result,
            final_beam_result=result.disp,
            deformed_y=np.asarray(self.aircraft.wing.y, dtype=float),
            deformed_z=deformed_z,
        )

    def run_two_way(
        self,
        aero_load_func: Callable[[np.ndarray, np.ndarray], SpanwiseLoad],
        load_factor: float = 1.0,
        max_iter: int = 20,
        tol: float = 1e-3,
        optimizer_method: str = "openmdao",
        aero_solver: str = "vsp",
    ) -> FSIResult:
        """Two-way iterative FSI coupling.

        Parameters
        ----------
        aero_load_func:
            Function(deformed_y, deformed_z) -> SpanwiseLoad.
        aero_solver:
            Aero backend name. ``"xflr5"`` is explicitly unsupported for
            two-way coupling; ``"vsp"`` requires OpenVSP Python bindings.
        """

        self._validate_two_way_backend(aero_solver)

        if max_iter < 1:
            raise ValueError("max_iter must be >= 1")

        span_y = np.asarray(self.aircraft.wing.y, dtype=float)
        tip_history: list[float] = []
        deformed_z = np.zeros_like(span_y)
        prev_tip = 0.0
        last_result: Optional[OptimizationResult] = None

        for iteration in range(1, max_iter + 1):
            aero_load = aero_load_func(span_y, deformed_z)
            last_result, deformed_z = self._solve_once(
                aero_load, load_factor, optimizer_method
            )
            current_tip = last_result.tip_deflection_m
            tip_history.append(current_tip)

            if iteration > 1 and abs(current_tip - prev_tip) < tol:
                return FSIResult(
                    converged=True,
                    n_iterations=iteration,
                    tip_deflection_history=tip_history,
                    optimization_result=last_result,
                    final_beam_result=last_result.disp,
                    deformed_y=span_y,
                    deformed_z=deformed_z,
                )

            prev_tip = current_tip

        if last_result is None:
            raise RuntimeError("Two-way FSI did not execute any iteration.")

        return FSIResult(
            converged=False,
            n_iterations=max_iter,
            tip_deflection_history=tip_history,
            optimization_result=last_result,
            final_beam_result=last_result.disp,
            deformed_y=span_y,
            deformed_z=deformed_z,
        )

    @staticmethod
    def _validate_two_way_backend(aero_solver: str) -> None:
        backend = aero_solver.strip().lower()
        if backend == "xflr5":
            raise NotImplementedError(
                "Two-way FSI is not supported for XFLR5. "
                "Use one-way mode or switch to OpenVSP."
            )

        if backend in {"vsp", "vspaero", "openvsp"}:
            try:
                importlib.import_module("openvsp")
            except Exception as exc:  # pragma: no cover - depends on local env
                raise RuntimeError(
                    "Two-way FSI requires OpenVSP Python API (`openvsp`)."
                ) from exc
            return

        if backend not in {"custom", "callable"}:
            raise ValueError(
                f"Unsupported aero_solver '{aero_solver}'. "
                "Use 'vsp', 'xflr5', or 'custom'."
            )
