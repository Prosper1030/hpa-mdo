"""Map aerodynamic loads onto structural beam nodes.

Aerodynamic solvers and the structural beam model typically use different
spanwise discretisations. LoadMapper interpolates sectional loads between
those grids.

The default is linear interpolation because cubic splines can overshoot on
sparse or oscillatory load distributions and silently change the integrated
force/moment. This utility is not a conservative remap scheme.

Handles:
    - Lift per span (Fz)
    - Drag per span (Fx)
    - Pitching moment / torque per span (Mx) from Cmy
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.interpolate import interp1d

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.core.errors import ErrorCode, HPAError
from hpa_mdo.core.logging import get_logger

logger = get_logger(__name__)
APPLIED_AERO_SCALE_KEY = "_applied_aero_scale"


class LoadMapper:
    """Interpolate SpanwiseLoad data onto a structural node grid."""

    def __init__(self, method: str = "linear"):
        """
        Parameters
        ----------
        method : str
            Interpolation kind passed to scipy.interpolate.interp1d.
            'linear', 'cubic', 'nearest', etc. Linear is the default because
            it avoids spline overshoot on sparse aero grids.
        """
        self.method = method

    def map_loads(
        self,
        aero_load: SpanwiseLoad,
        struct_y: np.ndarray,
        scale_factor: float = 1.0,
        actual_velocity: Optional[float] = None,
        actual_density: Optional[float] = None,
    ) -> dict:  # noqa: E501
        """Interpolate aerodynamic loads onto structural nodes.

        Parameters
        ----------
        aero_load : SpanwiseLoad
            Source aero data (from any parser).
        struct_y : np.ndarray
            Target structural node y-coordinates [m].
        scale_factor : float
            Multiplicative factor applied to loads (e.g. load_factor for
            gust/manoeuvre cases). Default 1.0.
            **Do not combine with** ``LoadMapper.apply_load_factor()`` on the
            same result — use one or the other to avoid double-scaling.
        actual_velocity : float | None
            If set, recompute dimensional loads using this velocity [m/s]
            instead of the aero solver's reference velocity.  This is
            critical when VSPAero was run at a different Vinf than the
            real cruise speed.
        actual_density : float | None
            If set, recompute dimensional loads using this air density
            [kg/m³] instead of the aero solver's value.

        Returns
        -------
        dict with keys:
            'y'                : structural y coordinates [m]
            'lift_per_span'    : interpolated lift/span [N/m]
            'drag_per_span'    : interpolated drag/span [N/m]
            'torque_per_span'  : interpolated pitching-moment torque [N.m/m]
            'chord'            : interpolated chord [m]
            'cl'               : interpolated lift coefficient
            'cm'               : interpolated pitching moment coefficient
            'total_lift'       : integrated half-span lift [N]
        """
        y_a = np.asarray(aero_load.y, dtype=float)
        y_s = np.asarray(struct_y, dtype=float)
        self._validate_inputs(aero_load, y_s)

        in_range_mask = (y_s >= y_a.min()) & (y_s <= y_a.max())

        # Clamp structural nodes to aero range to avoid extrapolation
        y_s_clamped = np.clip(y_s, y_a.min(), y_a.max())
        if not np.array_equal(y_s_clamped, y_s):
            logger.warning(
                "struct_y exceeded aero y-range [%.3f, %.3f]; "
                "out-of-range nodes carry zero aero load.",
                float(np.min(y_a)),
                float(np.max(y_a)),
            )

        def _interp(vals: np.ndarray) -> np.ndarray:
            f = interp1d(y_a, vals, kind=self.method, fill_value="extrapolate")
            return f(y_s_clamped)

        chord = _interp(aero_load.chord)
        cl = _interp(aero_load.cl)
        cd = _interp(aero_load.cd)
        cm = _interp(aero_load.cm)

        if not np.all(np.isfinite(chord)) or np.any(chord <= 0.0):
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "Mapped chord contains invalid values (NaN/Inf or <= 0).",
            )

        # Re-dimensionalise with actual flight conditions if specified
        if actual_velocity is not None or actual_density is not None:
            v = actual_velocity if actual_velocity is not None else aero_load.velocity
            rho = actual_density if actual_density is not None else (
                aero_load.dynamic_pressure * 2.0 / aero_load.velocity**2
                if aero_load.velocity > 0 else 1.225
            )
            q_actual = 0.5 * rho * v**2
            lift = q_actual * chord * cl * scale_factor
            drag = q_actual * chord * cd * scale_factor
            # Torque = q * c² * Cm (dimensional pitching moment per unit span)
            torque = q_actual * chord**2 * cm * scale_factor
        else:
            lift = _interp(aero_load.lift_per_span) * scale_factor
            drag = _interp(aero_load.drag_per_span) * scale_factor
            q_ref = aero_load.dynamic_pressure
            torque = q_ref * chord**2 * cm * scale_factor

        # Physical convention: nodes outside the aerodynamic span carry no load.
        # chord/cl/cm are geometry/coefficients and are left as interpolated
        # (clamped boundary) values — only the force/moment intensities are zeroed.
        if not np.all(in_range_mask):
            lift = np.asarray(lift).copy()
            drag = np.asarray(drag).copy()
            torque = np.asarray(torque).copy()
            lift[~in_range_mask] = 0.0
            drag[~in_range_mask] = 0.0
            torque[~in_range_mask] = 0.0

        total_lift = float(np.trapezoid(lift, y_s))
        logger.debug("Load mapping complete (total_lift=%.3f N).", total_lift)

        return {
            "y": y_s,
            "lift_per_span": lift,
            "drag_per_span": drag,
            "torque_per_span": torque,
            "chord": chord,
            "cl": cl,
            "cm": cm,
            "total_lift": total_lift,
            APPLIED_AERO_SCALE_KEY: float(scale_factor),
        }

    @staticmethod
    def _validate_inputs(aero_load: SpanwiseLoad, struct_y: np.ndarray) -> None:
        fields = {
            "y": aero_load.y,
            "chord": aero_load.chord,
            "cl": aero_load.cl,
            "cd": aero_load.cd,
            "cm": aero_load.cm,
            "lift_per_span": aero_load.lift_per_span,
            "drag_per_span": aero_load.drag_per_span,
        }

        n = len(np.asarray(aero_load.y))
        if n < 2:
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "SpanwiseLoad must contain at least 2 stations.",
            )

        for name, values in fields.items():
            arr = np.asarray(values, dtype=float).ravel()
            if arr.size != n:
                raise HPAError(
                    ErrorCode.LOAD_VALIDATION_FAIL,
                    f"SpanwiseLoad.{name} length mismatch: expected {n}, got {arr.size}.",
                )
            if not np.all(np.isfinite(arr)):
                raise HPAError(
                    ErrorCode.LOAD_VALIDATION_FAIL,
                    f"SpanwiseLoad.{name} contains NaN/Inf.",
                )

        chord = np.asarray(aero_load.chord, dtype=float)
        if np.any(chord <= 0.0):
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "SpanwiseLoad.chord must be strictly positive.",
            )

        y = np.asarray(aero_load.y, dtype=float)
        if not np.all(np.diff(y) > 0.0):
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "SpanwiseLoad.y must be strictly increasing.",
            )

        if not np.all(np.isfinite(struct_y)):
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "struct_y contains NaN/Inf.",
            )
        if struct_y.size < 2:
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "struct_y must contain at least 2 nodes.",
            )

    @staticmethod
    def apply_load_factor(mapped: dict, n: float) -> dict:
        """Scale an already-mapped load dict by an additional load factor."""
        out = dict(mapped)
        out["lift_per_span"] = mapped["lift_per_span"] * n
        out["drag_per_span"] = mapped["drag_per_span"] * n
        out["torque_per_span"] = mapped["torque_per_span"] * n
        out["total_lift"] = mapped["total_lift"] * n
        out[APPLIED_AERO_SCALE_KEY] = float(mapped.get(APPLIED_AERO_SCALE_KEY, 1.0)) * float(n)
        return out


class ConservativeLoadMapper(LoadMapper):
    """Opt-in conservative projection from aero stations to structural nodes.

    The mapper first uses the base ``LoadMapper`` interpolation to form the
    target-grid load vector, then applies a weighted constrained projection so
    selected integrated quantities match the source aero-grid values.
    """

    def __init__(
        self,
        method: str = "linear",
        *,
        weight_epsilon: float = 1.0e-12,
        large_correction_l2_threshold: float = 0.25,
        large_pointwise_correction_threshold: float = 0.50,
        peak_ratio_threshold: float = 2.50,
        sign_epsilon: float = 1.0e-10,
        conserve_drag: bool = True,
    ):
        super().__init__(method=method)
        self.weight_epsilon = float(weight_epsilon)
        self.large_correction_l2_threshold = float(large_correction_l2_threshold)
        self.large_pointwise_correction_threshold = float(large_pointwise_correction_threshold)
        self.peak_ratio_threshold = float(peak_ratio_threshold)
        self.sign_epsilon = float(sign_epsilon)
        self.conserve_drag = bool(conserve_drag)

    def map_loads(
        self,
        aero_load: SpanwiseLoad,
        struct_y: np.ndarray,
        scale_factor: float = 1.0,
        actual_velocity: Optional[float] = None,
        actual_density: Optional[float] = None,
    ) -> dict:
        """Map loads and project them onto integrated conservation constraints."""
        y_a = np.asarray(aero_load.y, dtype=float)
        y_s = np.asarray(struct_y, dtype=float)
        self._validate_conservative_inputs(aero_load, y_s)

        mapped = super().map_loads(
            aero_load,
            y_s,
            scale_factor=scale_factor,
            actual_velocity=actual_velocity,
            actual_density=actual_density,
        )
        source = self._source_dimensional_loads(
            aero_load,
            scale_factor=scale_factor,
            actual_velocity=actual_velocity,
            actual_density=actual_density,
        )
        struct_weights = self._trapezoid_weights(y_s)

        lift_before = np.asarray(mapped["lift_per_span"], dtype=float)
        lift_a = np.asarray(source["lift_per_span"], dtype=float)
        lift_targets = np.array(
            [
                self._weighted_integral(lift_a, self._trapezoid_weights(y_a)),
                self._weighted_integral(y_a * lift_a, self._trapezoid_weights(y_a)),
            ],
            dtype=float,
        )
        lift_constraints = np.vstack((struct_weights, struct_weights * y_s))
        lift_after = self._project(
            lift_before,
            constraints=lift_constraints,
            targets=lift_targets,
            weights=struct_weights,
        )

        torque_before = np.asarray(mapped["torque_per_span"], dtype=float)
        torque_a = np.asarray(source["torque_per_span"], dtype=float)
        torque_targets = np.array(
            [self._weighted_integral(torque_a, self._trapezoid_weights(y_a))],
            dtype=float,
        )
        torque_constraints = np.vstack((struct_weights,))
        torque_after = self._project(
            torque_before,
            constraints=torque_constraints,
            targets=torque_targets,
            weights=struct_weights,
        )

        drag_before = np.asarray(mapped["drag_per_span"], dtype=float)
        drag_after = drag_before
        drag_targets = None
        if self.conserve_drag:
            drag_a = np.asarray(source["drag_per_span"], dtype=float)
            drag_targets = np.array(
                [self._weighted_integral(drag_a, self._trapezoid_weights(y_a))],
                dtype=float,
            )
            drag_after = self._project(
                drag_before,
                constraints=torque_constraints,
                targets=drag_targets,
                weights=struct_weights,
            )

        diagnostics = self._build_diagnostics(
            y_s=y_s,
            struct_weights=struct_weights,
            lift_before=lift_before,
            lift_after=lift_after,
            lift_targets=lift_targets,
            torque_before=torque_before,
            torque_after=torque_after,
            torque_targets=torque_targets,
            drag_before=drag_before,
            drag_after=drag_after,
            drag_targets=drag_targets,
        )

        out = dict(mapped)
        out["lift_per_span"] = lift_after
        out["drag_per_span"] = drag_after
        out["torque_per_span"] = torque_after
        out["total_lift"] = self._weighted_integral(lift_after, struct_weights)
        out["conservation_diagnostics"] = diagnostics
        return out

    def _validate_conservative_inputs(
        self,
        aero_load: SpanwiseLoad,
        struct_y: np.ndarray,
    ) -> None:
        self._validate_inputs(aero_load, struct_y)
        if np.asarray(aero_load.y).size < 3:
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "ConservativeLoadMapper requires at least 3 aero stations.",
            )
        if struct_y.size < 3:
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "ConservativeLoadMapper requires at least 3 structural nodes.",
            )
        if not np.all(np.diff(struct_y) > 0.0):
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "ConservativeLoadMapper struct_y must be strictly increasing.",
            )

    def _source_dimensional_loads(
        self,
        aero_load: SpanwiseLoad,
        *,
        scale_factor: float,
        actual_velocity: Optional[float],
        actual_density: Optional[float],
    ) -> dict[str, np.ndarray]:
        chord = np.asarray(aero_load.chord, dtype=float)
        cl = np.asarray(aero_load.cl, dtype=float)
        cd = np.asarray(aero_load.cd, dtype=float)
        cm = np.asarray(aero_load.cm, dtype=float)
        scale = float(scale_factor)

        if actual_velocity is not None or actual_density is not None:
            v = actual_velocity if actual_velocity is not None else float(aero_load.velocity)
            rho = actual_density if actual_density is not None else (
                float(aero_load.dynamic_pressure) * 2.0 / float(aero_load.velocity) ** 2
                if float(aero_load.velocity) > 0.0 else 1.225
            )
            q = 0.5 * float(rho) * float(v) ** 2
            lift = q * chord * cl * scale
            drag = q * chord * cd * scale
            torque = q * chord**2 * cm * scale
        else:
            q = float(aero_load.dynamic_pressure)
            lift = np.asarray(aero_load.lift_per_span, dtype=float) * scale
            drag = np.asarray(aero_load.drag_per_span, dtype=float) * scale
            torque = q * chord**2 * cm * scale

        return {
            "lift_per_span": np.asarray(lift, dtype=float),
            "drag_per_span": np.asarray(drag, dtype=float),
            "torque_per_span": np.asarray(torque, dtype=float),
        }

    @staticmethod
    def _trapezoid_weights(y: np.ndarray) -> np.ndarray:
        y_arr = np.asarray(y, dtype=float)
        weights = np.empty_like(y_arr)
        weights[0] = 0.5 * (y_arr[1] - y_arr[0])
        weights[-1] = 0.5 * (y_arr[-1] - y_arr[-2])
        weights[1:-1] = 0.5 * (y_arr[2:] - y_arr[:-2])
        return weights

    @staticmethod
    def _weighted_integral(values: np.ndarray, weights: np.ndarray) -> float:
        return float(np.dot(np.asarray(weights, dtype=float), np.asarray(values, dtype=float)))

    def _project(
        self,
        x0: np.ndarray,
        *,
        constraints: np.ndarray,
        targets: np.ndarray,
        weights: np.ndarray,
    ) -> np.ndarray:
        x0_arr = np.asarray(x0, dtype=float)
        a = np.asarray(constraints, dtype=float)
        b = np.asarray(targets, dtype=float)
        safe_weights = np.maximum(np.asarray(weights, dtype=float), self.weight_epsilon)
        w_inv = 1.0 / safe_weights
        residual = a @ x0_arr - b
        middle = (a * w_inv[np.newaxis, :]) @ a.T
        correction = w_inv * (a.T @ (np.linalg.pinv(middle) @ residual))
        projected = x0_arr - correction
        if not np.all(np.isfinite(projected)):
            raise HPAError(
                ErrorCode.LOAD_VALIDATION_FAIL,
                "Conservative load projection produced NaN/Inf.",
            )
        return np.asarray(projected, dtype=float)

    def _build_diagnostics(
        self,
        *,
        y_s: np.ndarray,
        struct_weights: np.ndarray,
        lift_before: np.ndarray,
        lift_after: np.ndarray,
        lift_targets: np.ndarray,
        torque_before: np.ndarray,
        torque_after: np.ndarray,
        torque_targets: np.ndarray,
        drag_before: np.ndarray,
        drag_after: np.ndarray,
        drag_targets: np.ndarray | None,
    ) -> dict[str, float | int | str | list[str] | bool]:
        lift_before_total = self._weighted_integral(lift_before, struct_weights)
        lift_after_total = self._weighted_integral(lift_after, struct_weights)
        lift_before_moment = self._weighted_integral(y_s * lift_before, struct_weights)
        lift_after_moment = self._weighted_integral(y_s * lift_after, struct_weights)
        torque_before_total = self._weighted_integral(torque_before, struct_weights)
        torque_after_total = self._weighted_integral(torque_after, struct_weights)
        drag_before_total = self._weighted_integral(drag_before, struct_weights)
        drag_after_total = self._weighted_integral(drag_after, struct_weights)

        lift_stats = self._correction_stats(lift_before, lift_after)
        torque_stats = self._correction_stats(torque_before, torque_after)
        drag_stats = self._correction_stats(drag_before, drag_after)

        warnings: list[str] = []
        status = "conserved"
        if (
            lift_stats["sign_reversal_count"] > 0
            or torque_stats["sign_reversal_count"] > 0
            or drag_stats["sign_reversal_count"] > 0
            or max(
                lift_stats["peak_ratio"],
                torque_stats["peak_ratio"],
                drag_stats["peak_ratio"],
            ) > self.peak_ratio_threshold
        ):
            status = "conservation_projection_unphysical"
            warnings.append("projection introduced sign reversal or a large peak ratio")
        elif (
            max(
                lift_stats["correction_l2_norm"],
                torque_stats["correction_l2_norm"],
                drag_stats["correction_l2_norm"],
            ) > self.large_correction_l2_threshold
            or max(
                lift_stats["max_pointwise_correction"],
                torque_stats["max_pointwise_correction"],
                drag_stats["max_pointwise_correction"],
            ) > self.large_pointwise_correction_threshold
        ):
            status = "conserved_with_large_correction"
            warnings.append("projection correction is large relative to interpolated loads")

        diagnostics: dict[str, float | int | str | list[str] | bool] = {
            "status": status,
            "warnings": warnings,
            "total_lift_source_n": float(lift_targets[0]),
            "total_lift_before_n": float(lift_before_total),
            "total_lift_after_n": float(lift_after_total),
            "total_lift_error_before_n": float(lift_before_total - lift_targets[0]),
            "total_lift_error_after_n": float(lift_after_total - lift_targets[0]),
            "root_bending_moment_source_nm": float(lift_targets[1]),
            "root_bending_moment_before_nm": float(lift_before_moment),
            "root_bending_moment_after_nm": float(lift_after_moment),
            "root_moment_error_before_nm": float(lift_before_moment - lift_targets[1]),
            "root_moment_error_after_nm": float(lift_after_moment - lift_targets[1]),
            "total_torque_source_nm": float(torque_targets[0]),
            "total_torque_before_nm": float(torque_before_total),
            "total_torque_after_nm": float(torque_after_total),
            "torque_error_before_nm": float(torque_before_total - torque_targets[0]),
            "torque_error_after_nm": float(torque_after_total - torque_targets[0]),
            "total_drag_before_n": float(drag_before_total),
            "total_drag_after_n": float(drag_after_total),
            "lift_correction_l2_norm": lift_stats["correction_l2_norm"],
            "lift_correction_norm_npm": lift_stats["absolute_correction_norm"],
            "lift_max_pointwise_correction": lift_stats["max_pointwise_correction"],
            "lift_sign_reversal_count": lift_stats["sign_reversal_count"],
            "lift_peak_ratio": lift_stats["peak_ratio"],
            "torque_correction_l2_norm": torque_stats["correction_l2_norm"],
            "torque_correction_norm_nm_per_m": torque_stats["absolute_correction_norm"],
            "torque_max_pointwise_correction": torque_stats["max_pointwise_correction"],
            "torque_sign_reversal_count": torque_stats["sign_reversal_count"],
            "torque_peak_ratio": torque_stats["peak_ratio"],
            "drag_correction_l2_norm": drag_stats["correction_l2_norm"],
            "drag_max_pointwise_correction": drag_stats["max_pointwise_correction"],
            "drag_sign_reversal_count": drag_stats["sign_reversal_count"],
            "drag_peak_ratio": drag_stats["peak_ratio"],
            "correction_l2_norm": max(
                lift_stats["correction_l2_norm"],
                torque_stats["correction_l2_norm"],
                drag_stats["correction_l2_norm"],
            ),
            "max_pointwise_correction": max(
                lift_stats["max_pointwise_correction"],
                torque_stats["max_pointwise_correction"],
                drag_stats["max_pointwise_correction"],
            ),
            "sign_reversal_count": int(
                lift_stats["sign_reversal_count"]
                + torque_stats["sign_reversal_count"]
                + drag_stats["sign_reversal_count"]
            ),
            "peak_ratio": max(
                lift_stats["peak_ratio"],
                torque_stats["peak_ratio"],
                drag_stats["peak_ratio"],
            ),
            "conserved_total_lift": bool(abs(lift_after_total - lift_targets[0]) <= 1.0e-8),
            "conserved_root_bending_moment": bool(
                abs(lift_after_moment - lift_targets[1]) <= 1.0e-8
            ),
            "conserved_total_torque": bool(
                abs(torque_after_total - torque_targets[0]) <= 1.0e-8
            ),
        }
        if drag_targets is not None:
            diagnostics.update(
                {
                    "total_drag_source_n": float(drag_targets[0]),
                    "total_drag_error_before_n": float(drag_before_total - drag_targets[0]),
                    "total_drag_error_after_n": float(drag_after_total - drag_targets[0]),
                    "conserved_total_drag": bool(
                        abs(drag_after_total - drag_targets[0]) <= 1.0e-8
                    ),
                }
            )
        return diagnostics

    def _correction_stats(self, before: np.ndarray, after: np.ndarray) -> dict[str, float | int]:
        before_arr = np.asarray(before, dtype=float)
        after_arr = np.asarray(after, dtype=float)
        delta = after_arr - before_arr
        eps = self.weight_epsilon
        before_norm = float(np.linalg.norm(before_arr))
        before_abs_max = float(np.max(np.abs(before_arr))) if before_arr.size else 0.0
        after_abs_max = float(np.max(np.abs(after_arr))) if after_arr.size else 0.0
        active = (np.abs(before_arr) > self.sign_epsilon) & (np.abs(after_arr) > self.sign_epsilon)
        sign_reversal_count = int(
            np.count_nonzero(active & (np.sign(before_arr) != np.sign(after_arr)))
        )
        return {
            "absolute_correction_norm": float(np.linalg.norm(delta)),
            "correction_l2_norm": float(np.linalg.norm(delta) / (before_norm + eps)),
            "max_pointwise_correction": float(
                (np.max(np.abs(delta)) if delta.size else 0.0) / (before_abs_max + eps)
            ),
            "sign_reversal_count": sign_reversal_count,
            "peak_ratio": float(after_abs_max / (before_abs_max + eps)),
        }
