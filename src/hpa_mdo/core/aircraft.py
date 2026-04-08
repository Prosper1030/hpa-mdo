"""Aircraft data model — geometry, flight state, and airfoil utilities.

Converts HPAConfig into runtime objects with derived quantities.
Computes airfoil-aware spar Z positions for dual-spar stiffness.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from hpa_mdo.core.constants import G_STANDARD


@dataclass
class FlightCondition:
    velocity: float
    air_density: float
    kinematic_viscosity: float

    @property
    def dynamic_pressure(self) -> float:
        return 0.5 * self.air_density * self.velocity ** 2

    def reynolds(self, chord: float) -> float:
        return self.velocity * chord / self.kinematic_viscosity


@dataclass
class AirfoilData:
    """Upper and lower surface coordinates for an airfoil."""
    name: str
    x: np.ndarray  # chordwise [0..1]
    z_upper: np.ndarray
    z_lower: np.ndarray

    def camber_z_at(self, xc: float) -> float:
        """Z-coordinate on the camber line at a given x/c."""
        z_u = float(np.interp(xc, self.x, self.z_upper))
        z_l = float(np.interp(xc, self.x, self.z_lower))
        return (z_u + z_l) / 2.0

    def thickness_at(self, xc: float) -> float:
        """Airfoil thickness at x/c (fraction of chord)."""
        z_u = float(np.interp(xc, self.x, self.z_upper))
        z_l = float(np.interp(xc, self.x, self.z_lower))
        return z_u - z_l

    @classmethod
    def from_dat(cls, path: Path, name: str = "") -> AirfoilData:
        """Read Selig-format .dat file."""
        lines = path.read_text().splitlines()
        header = lines[0].strip()
        coords = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    coords.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    continue
        coords = np.array(coords)

        # Selig format: upper surface (TE→LE) then lower (LE→TE)
        # Find the leading edge (min x)
        le_idx = np.argmin(coords[:, 0])
        upper = coords[:le_idx + 1][::-1]  # LE → TE
        lower = coords[le_idx:]             # LE → TE

        # Ensure sorted by x
        upper = upper[np.argsort(upper[:, 0])]
        lower = lower[np.argsort(lower[:, 0])]

        return cls(
            name=name or header,
            x=upper[:, 0],
            z_upper=upper[:, 1],
            z_lower=np.interp(upper[:, 0], lower[:, 0], lower[:, 1]),
        )


@dataclass
class WingGeometry:
    y: np.ndarray             # spanwise stations [m], root→tip
    chord: np.ndarray
    twist_deg: np.ndarray
    dihedral_deg: np.ndarray
    airfoil_thickness: np.ndarray  # max t/c
    main_spar_xc: float
    rear_spar_xc: float
    # Z-offsets of spar tubes within the airfoil section (fraction of chord)
    main_spar_z_camber: np.ndarray
    rear_spar_z_camber: np.ndarray

    @property
    def n_stations(self) -> int:
        return len(self.y)

    @property
    def half_span(self) -> float:
        return float(self.y[-1])

    @property
    def area_half(self) -> float:
        return float(np.trapezoid(self.chord, self.y))

    def spar_separation(self) -> np.ndarray:
        """Chordwise distance between main and rear spar [m]."""
        return (self.rear_spar_xc - self.main_spar_xc) * self.chord


@dataclass
class Aircraft:
    name: str
    wing: WingGeometry
    flight: FlightCondition
    mass_total_kg: float
    mass_airframe_kg: float

    @property
    def weight_N(self) -> float:
        return self.mass_total_kg * G_STANDARD

    @classmethod
    def from_config(cls, cfg) -> Aircraft:
        from hpa_mdo.core.config import HPAConfig
        assert isinstance(cfg, HPAConfig)

        n = cfg.solver.n_beam_nodes
        half_span = cfg.half_span
        y = np.linspace(0, half_span, n)
        eta = y / half_span

        chord = cfg.wing.root_chord + eta * (cfg.wing.tip_chord - cfg.wing.root_chord)
        dihedral = cfg.wing.dihedral_root_deg + eta * (
            cfg.wing.dihedral_tip_deg - cfg.wing.dihedral_root_deg)
        twist = np.zeros(n)

        tc_root = cfg.wing.airfoil_root_tc
        tc_tip = cfg.wing.airfoil_tip_tc
        airfoil_tc = tc_root + eta * (tc_tip - tc_root)

        # Try to load airfoil .dat files for accurate Z positions
        main_xc = cfg.main_spar.location_xc
        rear_xc = cfg.rear_spar.location_xc

        main_z = np.zeros(n)
        rear_z = np.zeros(n)

        if cfg.io.airfoil_dir and Path(cfg.io.airfoil_dir).exists():
            airfoil_dir = Path(cfg.io.airfoil_dir)
            root_af = _try_load_airfoil(airfoil_dir, cfg.wing.airfoil_root)
            tip_af = _try_load_airfoil(airfoil_dir, cfg.wing.airfoil_tip)

            if root_af and tip_af:
                tc_root = root_af.thickness_at(main_xc)
                tc_tip = tip_af.thickness_at(main_xc)
                airfoil_tc = tc_root + eta * (tc_tip - tc_root)

                main_z_root = root_af.camber_z_at(main_xc)
                main_z_tip = tip_af.camber_z_at(main_xc)
                main_z = main_z_root + eta * (main_z_tip - main_z_root)

                rear_z_root = root_af.camber_z_at(rear_xc)
                rear_z_tip = tip_af.camber_z_at(rear_xc)
                rear_z = rear_z_root + eta * (rear_z_tip - rear_z_root)

        wing = WingGeometry(
            y=y, chord=chord, twist_deg=twist,
            dihedral_deg=dihedral,
            airfoil_thickness=airfoil_tc,
            main_spar_xc=main_xc,
            rear_spar_xc=rear_xc,
            main_spar_z_camber=main_z,
            rear_spar_z_camber=rear_z,
        )

        flight = FlightCondition(
            velocity=cfg.flight.velocity,
            air_density=cfg.flight.air_density,
            kinematic_viscosity=cfg.flight.kinematic_viscosity,
        )

        return cls(
            name=cfg.project_name,
            wing=wing, flight=flight,
            mass_total_kg=cfg.weight.operating_kg,
            mass_airframe_kg=cfg.weight.airframe_kg,
        )


def _try_load_airfoil(directory: Path, name: str) -> Optional[AirfoilData]:
    for suffix in [".dat", ".txt", ""]:
        p = directory / f"{name}{suffix}"
        if p.exists():
            return AirfoilData.from_dat(p, name)
    return None
