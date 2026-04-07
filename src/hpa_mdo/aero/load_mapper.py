"""Map aerodynamic loads onto structural beam nodes.

Aerodynamic solvers and the structural beam model typically use different
spanwise discretisations.  LoadMapper performs conservative interpolation
to transfer loads while preserving the total integrated force and moment.

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
from hpa_mdo.core.logging import get_logger

logger = get_logger(__name__)


class LoadMapper:
    """Interpolate SpanwiseLoad data onto a structural node grid."""

    def __init__(self, method: str = "cubic"):
        """
        Parameters
        ----------
        method : str
            Interpolation kind passed to scipy.interpolate.interp1d.
            'linear', 'cubic', 'nearest', etc.
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

        # Clamp structural nodes to aero range to avoid extrapolation
        y_s_clamped = np.clip(y_s, y_a.min(), y_a.max())
        if not np.array_equal(y_s_clamped, y_s):
            logger.warning(
                "struct_y exceeded aero y-range; clamped to [%.3f, %.3f].",
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
            raise ValueError("Mapped chord contains invalid values (NaN/Inf or <= 0).")

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

        total_lift = float(np.trapz(lift, y_s))
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
            raise ValueError("SpanwiseLoad must contain at least 2 stations.")

        for name, values in fields.items():
            arr = np.asarray(values, dtype=float).ravel()
            if arr.size != n:
                raise ValueError(
                    f"SpanwiseLoad.{name} length mismatch: expected {n}, got {arr.size}."
                )
            if not np.all(np.isfinite(arr)):
                raise ValueError(f"SpanwiseLoad.{name} contains NaN/Inf.")

        chord = np.asarray(aero_load.chord, dtype=float)
        if np.any(chord <= 0.0):
            raise ValueError("SpanwiseLoad.chord must be strictly positive.")

        y = np.asarray(aero_load.y, dtype=float)
        if not np.all(np.diff(y) > 0.0):
            raise ValueError("SpanwiseLoad.y must be strictly increasing.")

        if not np.all(np.isfinite(struct_y)):
            raise ValueError("struct_y contains NaN/Inf.")
        if struct_y.size < 2:
            raise ValueError("struct_y must contain at least 2 nodes.")

    @staticmethod
    def apply_load_factor(mapped: dict, n: float) -> dict:
        """Scale an already-mapped load dict by an additional load factor."""
        out = dict(mapped)
        out["lift_per_span"] = mapped["lift_per_span"] * n
        out["drag_per_span"] = mapped["drag_per_span"] * n
        out["torque_per_span"] = mapped["torque_per_span"] * n
        out["total_lift"] = mapped["total_lift"] * n
        return out
