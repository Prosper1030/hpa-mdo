"""Centralized configuration management for HPA-MDO v2.

Schema mirrors configs/blackcat_004.yaml exactly.
All engineering constants are read from YAML — nothing is hardcoded.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, Field


# ── Sub-configs ─────────────────────────────────────────────────────────────

class FlightConfig(BaseModel):
    velocity: float = Field(..., description="Cruise TAS [m/s]")
    altitude: float = Field(0.0)
    air_density: float = Field(1.225, description="[kg/m³]")
    kinematic_viscosity: float = Field(1.46e-5)


class SafetyConfig(BaseModel):
    aerodynamic_load_factor: float = Field(2.0, description="Limit load [G]")
    material_safety_factor: float = Field(1.5, description="Knock-down on UTS")


class WeightConfig(BaseModel):
    airframe_kg: float
    pilot_kg: float
    max_takeoff_kg: float

    @property
    def operating_kg(self) -> float:
        return self.airframe_kg + self.pilot_kg


class WingConfig(BaseModel):
    span: float
    root_chord: float
    tip_chord: float
    dihedral_root_deg: float = 0.0
    dihedral_tip_deg: float = 6.0
    spar_location_xc: float = 0.25
    airfoil_root: str = "clarkysm"
    airfoil_tip: str = "fx76mp140"
    max_tip_twist_deg: float = Field(2.0, description="Torsion constraint [deg]")


class SparConfig(BaseModel):
    """Shared schema for main_spar and rear_spar."""
    material: str = "carbon_fiber_hm"
    location_xc: float = 0.25

    outer_diameter_root: Optional[float] = None
    outer_diameter_tip: Optional[float] = None
    thickness_fraction_root: float = 0.65
    thickness_fraction_tip: float = 0.80

    min_wall_thickness: float = 0.8e-3
    max_segment_length: float = 3.0

    segments: Optional[List[float]] = None

    joint_material: str = "aluminum_6061_t6"
    joint_mass_kg: float = 0.15

    enabled: bool = True


class LiftWireAttachment(BaseModel):
    y: float
    fuselage_z: float = -1.5
    label: str = ""


class LiftWireConfig(BaseModel):
    enabled: bool = True
    cable_material: str = "steel_4130"
    cable_diameter: float = 2.0e-3
    max_tension_fraction: float = 0.5
    attachments: List[LiftWireAttachment] = []


class SolverConfig(BaseModel):
    n_beam_nodes: int = 60
    optimizer: str = "SLSQP"
    optimizer_tol: float = 1e-6
    optimizer_maxiter: int = 500
    fsi_coupling: Literal["one-way", "two-way"] = "one-way"
    fsi_max_iter: int = 20
    fsi_tol: float = 1e-3


class IOConfig(BaseModel):
    vsp_model: Optional[Path] = None
    vsp_lod: Optional[Path] = None
    vsp_polar: Optional[Path] = None
    airfoil_dir: Optional[Path] = None
    output_dir: Path = Path("output")
    training_db: Path = Path("database/training_data.csv")


# ── Top-level ───────────────────────────────────────────────────────────────

class HPAConfig(BaseModel):
    project_name: str = "HPA-MDO"
    flight: FlightConfig
    safety: SafetyConfig = SafetyConfig()
    weight: WeightConfig
    wing: WingConfig
    main_spar: SparConfig
    rear_spar: SparConfig = SparConfig(
        enabled=True, location_xc=0.70,
        thickness_fraction_root=0.55, thickness_fraction_tip=0.65,
        joint_mass_kg=0.10,
    )
    lift_wires: LiftWireConfig = LiftWireConfig()
    solver: SolverConfig = SolverConfig()
    io: IOConfig = IOConfig()

    @property
    def half_span(self) -> float:
        return self.wing.span / 2.0

    def spar_segment_lengths(self, spar_cfg: SparConfig) -> List[float]:
        """Return segment lengths, auto-dividing if not explicit."""
        if spar_cfg.segments:
            return list(spar_cfg.segments)
        hs = self.half_span
        msl = spar_cfg.max_segment_length
        n = int(hs // msl)
        remainder = hs - n * msl
        segs = ([remainder] if remainder > 0.01 else []) + [msl] * n
        return segs

    @staticmethod
    def joint_positions(segments: List[float]) -> List[float]:
        """Cumulative sum excluding the last element → joint y-coords."""
        import numpy as np
        cs = list(np.cumsum(segments))
        return cs[:-1]  # last entry is the tip, not a joint


def load_config(path) -> HPAConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    return HPAConfig(**data)
