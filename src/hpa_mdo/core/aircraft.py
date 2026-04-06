"""Aircraft data model — runtime representation of geometry and flight state.

This module converts the declarative HPAConfig into rich objects that carry
derived quantities (Reynolds number, dynamic pressure, wing area, etc.) and
are passed to solver modules.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field


@dataclass
class FlightCondition:
    """Immutable snapshot of the flight environment."""
    velocity: float          # m/s
    air_density: float       # kg/m³
    kinematic_viscosity: float  # m²/s
    load_factor: float       # dimensionless

    @property
    def dynamic_pressure(self) -> float:
        """q = 0.5 * rho * V^2"""
        return 0.5 * self.air_density * self.velocity ** 2

    def reynolds(self, chord: float) -> float:
        """Chord Reynolds number."""
        return self.velocity * chord / self.kinematic_viscosity


@dataclass
class WingGeometry:
    """Discretised half-span wing geometry.

    All arrays are sized (n_stations,) and run from root (index 0)
    to tip (index -1).
    """
    y: np.ndarray             # spanwise station positions [m] (half-span)
    chord: np.ndarray         # local chord [m]
    twist_deg: np.ndarray     # local twist angle [deg]
    dihedral_deg: np.ndarray  # local dihedral angle [deg]
    spar_xc: float            # chordwise spar position (fraction of chord)
    airfoil_thickness: np.ndarray  # local max-thickness / chord

    @property
    def n_stations(self) -> int:
        return len(self.y)

    @property
    def half_span(self) -> float:
        return float(self.y[-1])

    @property
    def area_half(self) -> float:
        """Half-wing planform area via trapezoidal integration."""
        return float(np.trapz(self.chord, self.y))


@dataclass
class Aircraft:
    """Top-level aircraft representation combining geometry + flight state."""
    name: str
    wing: WingGeometry
    flight: FlightCondition
    mass_total_kg: float
    mass_airframe_kg: float

    @property
    def weight_N(self) -> float:
        return self.mass_total_kg * 9.80665

    @property
    def design_load_N(self) -> float:
        """Total design load = W * n (load factor)."""
        return self.weight_N * self.flight.load_factor

    @classmethod
    def from_config(cls, cfg) -> Aircraft:
        """Build Aircraft from an HPAConfig object."""
        from hpa_mdo.core.config import HPAConfig
        assert isinstance(cfg, HPAConfig)

        n = cfg.solver.n_beam_nodes
        half_span = cfg.wing.span / 2.0
        y = np.linspace(0, half_span, n)
        eta = y / half_span  # normalised span 0..1

        chord = cfg.wing.root_chord + eta * (cfg.wing.tip_chord - cfg.wing.root_chord)
        dihedral = cfg.wing.dihedral_root_deg + eta * (
            cfg.wing.dihedral_tip_deg - cfg.wing.dihedral_root_deg
        )
        twist = np.zeros(n)  # TODO: populate from VSP / user input

        # Approximate airfoil max thickness/chord — linear interpolation
        # Clark Y SM ≈ 11.7%, FX 76-MP-140 ≈ 14.0%
        tc_root = 0.117
        tc_tip = 0.140
        airfoil_tc = tc_root + eta * (tc_tip - tc_root)

        wing = WingGeometry(
            y=y,
            chord=chord,
            twist_deg=twist,
            dihedral_deg=dihedral,
            spar_xc=cfg.wing.spar_location_xc,
            airfoil_thickness=airfoil_tc,
        )

        flight = FlightCondition(
            velocity=cfg.flight.velocity,
            air_density=cfg.flight.air_density,
            kinematic_viscosity=cfg.flight.kinematic_viscosity,
            load_factor=cfg.flight.load_factor,
        )

        return cls(
            name=cfg.project_name,
            wing=wing,
            flight=flight,
            mass_total_kg=cfg.weight.operating_kg,
            mass_airframe_kg=cfg.weight.airframe_kg,
        )
