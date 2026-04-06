"""Map aerodynamic loads onto structural beam nodes.

Aerodynamic solvers and the structural beam model typically use different
spanwise discretisations.  LoadMapper performs conservative interpolation
to transfer loads while preserving the total integrated force and moment.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d

from hpa_mdo.aero.base import SpanwiseLoad


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
        actual_velocity: float | None = None,
        actual_density: float | None = None,
    ) -> dict[str, np.ndarray]:
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
            'y'             : structural y coordinates [m]
            'lift_per_span' : interpolated lift/span [N/m]
            'drag_per_span' : interpolated drag/span [N/m]
            'chord'         : interpolated chord [m]
            'cl'            : interpolated lift coefficient
            'total_lift'    : integrated half-span lift [N] (for sanity check)
        """
        y_a = aero_load.y
        y_s = struct_y

        # Clamp structural nodes to aero range to avoid extrapolation
        y_s_clamped = np.clip(y_s, y_a.min(), y_a.max())

        def _interp(vals: np.ndarray) -> np.ndarray:
            f = interp1d(y_a, vals, kind=self.method, fill_value="extrapolate")
            return f(y_s_clamped)

        chord = _interp(aero_load.chord)
        cl = _interp(aero_load.cl)
        cd = _interp(aero_load.cd)

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
        else:
            lift = _interp(aero_load.lift_per_span) * scale_factor
            drag = _interp(aero_load.drag_per_span) * scale_factor

        total_lift = float(np.trapz(lift, y_s))

        return {
            "y": y_s,
            "lift_per_span": lift,
            "drag_per_span": drag,
            "chord": chord,
            "cl": cl,
            "total_lift": total_lift,
        }

    @staticmethod
    def apply_load_factor(mapped: dict, n: float) -> dict:
        """Scale an already-mapped load dict by an additional load factor."""
        out = dict(mapped)
        out["lift_per_span"] = mapped["lift_per_span"] * n
        out["drag_per_span"] = mapped["drag_per_span"] * n
        out["total_lift"] = mapped["total_lift"] * n
        return out
