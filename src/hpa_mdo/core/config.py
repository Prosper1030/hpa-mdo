"""Centralized configuration management for HPA-MDO.

All design parameters, file paths, and solver settings are defined here
using Pydantic models for validation. Configs can be loaded from YAML files
or constructed programmatically for API / agent use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------

class FlightConditionConfig(BaseModel):
    """Atmospheric and kinematic flight state."""
    velocity: float = Field(..., description="Cruise true airspeed [m/s]")
    altitude: float = Field(0.0, description="Altitude ASL [m]")
    air_density: float = Field(1.225, description="Air density [kg/m³]")
    kinematic_viscosity: float = Field(1.46e-5, description="Kinematic viscosity [m²/s]")
    load_factor: float = Field(3.0, description="Design limit load factor (n)")


class WeightConfig(BaseModel):
    """Mass breakdown."""
    airframe_kg: float = Field(..., description="Airframe dry mass [kg]")
    pilot_kg: float = Field(..., description="Pilot + equipment mass [kg]")
    max_takeoff_kg: float = Field(..., description="Maximum design MTOW [kg]")

    @property
    def operating_kg(self) -> float:
        return self.airframe_kg + self.pilot_kg


class WingConfig(BaseModel):
    """Wing planform definition."""
    span: float = Field(..., description="Full wingspan [m]")
    root_chord: float = Field(..., description="Root chord length [m]")
    tip_chord: float = Field(..., description="Tip chord length [m]")
    dihedral_root_deg: float = Field(0.0, description="Dihedral at root [deg]")
    dihedral_tip_deg: float = Field(6.0, description="Dihedral at tip [deg]")
    spar_location_xc: float = Field(0.25, description="Spar chordwise position x/c")
    airfoil_root: str = Field("clarkysm", description="Root airfoil name")
    airfoil_tip: str = Field("fx76mp140", description="Tip airfoil name")


class SparConfig(BaseModel):
    """Spar structural parameters."""
    material: str = Field("carbon_fiber_hm", description="Material key in MaterialDB")
    outer_diameter_root: Optional[float] = Field(
        None, description="Root outer diameter [m]. None = auto from airfoil thickness"
    )
    outer_diameter_tip: Optional[float] = Field(None, description="Tip outer diameter [m]")
    thickness_fraction_root: float = Field(0.65, description="OD / airfoil-thickness at root")
    thickness_fraction_tip: float = Field(0.80, description="OD / airfoil-thickness at tip")
    min_wall_thickness: float = Field(0.8e-3, description="Minimum wall thickness [m]")
    safety_factor: float = Field(4.0, description="Safety factor on tensile strength")


class SolverConfig(BaseModel):
    """Numerical solver settings."""
    n_beam_nodes: int = Field(50, description="Number of beam FD nodes per half-span")
    optimizer_method: Literal["SLSQP", "trust-constr", "COBYLA"] = Field("SLSQP")
    optimizer_tol: float = Field(1e-6, description="Optimizer convergence tolerance")
    optimizer_maxiter: int = Field(500, description="Max optimizer iterations")
    fsi_max_iter: int = Field(20, description="Max FSI coupling iterations")
    fsi_tol: float = Field(1e-3, description="FSI convergence tolerance on tip deflection [m]")


class IOConfig(BaseModel):
    """Paths for input data and output results."""
    vsp_model: Optional[Path] = Field(None, description="Path to .vsp3 file")
    vsp_lod: Optional[Path] = Field(None, description="Path to VSPAero .lod file")
    vsp_polar: Optional[Path] = Field(None, description="Path to VSPAero .polar file")
    xflr5_csv: Optional[Path] = Field(None, description="Path to XFLR5 exported CSV")
    airfoil_dir: Optional[Path] = Field(None, description="Directory containing .dat airfoil files")
    output_dir: Path = Field(Path("output"), description="Output directory")


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

class HPAConfig(BaseModel):
    """Root configuration for the entire MDO framework."""
    project_name: str = Field("HPA-MDO", description="Project identifier")
    flight: FlightConditionConfig
    weight: WeightConfig
    wing: WingConfig
    spar: SparConfig = SparConfig()
    solver: SolverConfig = SolverConfig()
    io: IOConfig = IOConfig()


def load_config(path: "str | Path") -> HPAConfig:
    """Load configuration from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return HPAConfig(**data)
