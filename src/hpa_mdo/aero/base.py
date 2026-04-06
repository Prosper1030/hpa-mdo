"""Abstract base class for aerodynamic data sources.

Every aero back-end (VSPAero, XFLR5, AVL, future CFD) must implement
this interface so that downstream modules (load mapper, optimizer, FSI)
are solver-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class SpanwiseLoad:
    """Aerodynamic load distribution along the half-span.

    All arrays are sized (n_stations,) running root → tip.
    Coordinates are in the body frame (y = spanwise, z = vertical).
    """
    y: np.ndarray              # spanwise station [m]
    chord: np.ndarray          # local chord [m]
    cl: np.ndarray             # local lift coefficient
    cd: np.ndarray             # local drag coefficient
    cm: np.ndarray             # local pitching moment coefficient
    lift_per_span: np.ndarray  # dimensional lift per unit span [N/m]
    drag_per_span: np.ndarray  # dimensional drag per unit span [N/m]
    aoa_deg: float             # global angle of attack [deg]
    velocity: float            # freestream velocity [m/s]
    dynamic_pressure: float    # q∞ [Pa]

    @property
    def n_stations(self) -> int:
        return len(self.y)

    @property
    def total_lift(self) -> float:
        """Integrate lift over the half-span [N]."""
        return float(np.trapz(self.lift_per_span, self.y))

    @property
    def total_drag(self) -> float:
        return float(np.trapz(self.drag_per_span, self.y))


class AeroParser(ABC):
    """Interface that all aerodynamic back-ends must implement."""

    @abstractmethod
    def parse(self, **kwargs) -> list[SpanwiseLoad]:
        """Return a list of SpanwiseLoad, one per angle-of-attack case."""
        ...

    @abstractmethod
    def get_load_at_aoa(self, aoa_deg: float) -> SpanwiseLoad:
        """Return the SpanwiseLoad closest to the requested AoA."""
        ...
