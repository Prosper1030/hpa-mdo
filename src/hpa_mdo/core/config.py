"""Centralized configuration management for HPA-MDO v2.

Schema mirrors configs/blackcat_004.yaml exactly.
All engineering constants are read from YAML, with an optional local
overlay file for per-machine path differences.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


_LOCAL_PATHS_FILENAME = "local_paths.yaml"
_EXTERNAL_IO_FIELDS = ("vsp_model", "vsp_lod", "vsp_polar", "airfoil_dir")
_INTERNAL_IO_FIELDS = ("output_dir", "training_db")


# ── Sub-configs ─────────────────────────────────────────────────────────────

class FlightConfig(BaseModel):
    velocity: float = Field(..., description="Cruise TAS [m/s]")
    altitude: float = Field(0.0)
    air_density: float = Field(1.225, description="[kg/m³]")
    kinematic_viscosity: float = Field(1.46e-5)


class SafetyConfig(BaseModel):
    aerodynamic_load_factor: float = Field(2.0, description="Limit load [G]")
    material_safety_factor: float = Field(1.5, description="Knock-down on UTS")
    ks_rho_stress: float = Field(
        100.0, description="KS aggregation sharpness for stress constraint"
    )
    ks_rho_buckling: float = Field(
        50.0, description="KS aggregation sharpness for buckling constraint"
    )
    ks_rho_twist: float = Field(
        100.0, description="KS aggregation sharpness for twist constraint"
    )
    shell_buckling_knockdown: float = Field(
        default=0.65,
        description="NASA SP-8007 knockdown factor for CF tube shell buckling",
        ge=0.1,
        le=1.0,
    )
    shell_buckling_bending_enhancement: float = Field(
        default=1.3,
        description="Enhancement factor for pure bending vs pure axial",
        ge=1.0,
        le=2.0,
    )


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
    airfoil_root_tc: float = Field(0.117, description="Root airfoil max t/c")
    airfoil_tip_tc: float = Field(0.140, description="Tip airfoil max t/c")
    max_tip_twist_deg: float = Field(2.0, description="Torsion constraint [deg]")
    max_tip_deflection_m: Optional[float] = Field(
        None, description="Max allowable tip deflection [m]"
    )


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
    attachments: List[LiftWireAttachment] = Field(default_factory=list)


class SolverConfig(BaseModel):
    n_beam_nodes: int = 60
    optimizer: str = "SLSQP"
    optimizer_tol: float = 1e-6
    optimizer_maxiter: int = 500
    fsi_coupling: Literal["one-way", "two-way"] = "one-way"
    fsi_max_iter: int = 20
    fsi_tol: float = 1e-3


class IOConfig(BaseModel):
    sync_root: Optional[Path] = None
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

    @model_validator(mode="after")
    def validate_spanwise_layout(self) -> HPAConfig:
        tol = 1e-6
        half_span = self.half_span

        for spar_name, spar_cfg in (
            ("main_spar", self.main_spar),
            ("rear_spar", self.rear_spar),
        ):
            if not spar_cfg.enabled:
                continue
            segments = self.spar_segment_lengths(spar_cfg)
            total = float(sum(segments))
            if abs(total - half_span) > tol:
                raise ValueError(
                    f"{spar_name}.segments sum to {total:.9f} m, "
                    f"but wing.span/2 is {half_span:.9f} m."
                )

        if self.lift_wires.enabled and self.lift_wires.attachments:
            main_joints = self.joint_positions(
                self.spar_segment_lengths(self.main_spar)
            )
            for att in self.lift_wires.attachments:
                if not any(abs(att.y - jy) <= tol for jy in main_joints):
                    raise ValueError(
                        "lift_wires attachment y must lie on a segment boundary "
                        f"(got y={att.y})."
                    )

        return self


def _read_yaml(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _discover_local_paths_path(
    config_path: Path,
    local_paths_path: Optional[Path | str],
) -> Optional[Path]:
    if local_paths_path is not None:
        candidate = Path(local_paths_path).expanduser()
        if not candidate.is_absolute():
            candidate = (config_path.parent / candidate).resolve()
        return candidate

    env_override = os.getenv("HPA_MDO_LOCAL_PATHS")
    if env_override:
        return Path(env_override).expanduser().resolve()

    return (config_path.parent / _LOCAL_PATHS_FILENAME).resolve()


def _project_root_from_config(config_path: Path) -> Path:
    if config_path.parent.name == "configs":
        return config_path.parent.parent
    return config_path.parent


def _resolve_path(path_value: Optional[Path], base_dir: Path) -> Optional[Path]:
    if path_value is None:
        return None
    if path_value.is_absolute():
        return path_value
    return (base_dir / path_value).resolve()


def _resolve_io_paths(cfg: HPAConfig, project_root: Path) -> HPAConfig:
    sync_root = _resolve_path(cfg.io.sync_root, project_root)
    cfg.io.sync_root = sync_root

    for field_name in _EXTERNAL_IO_FIELDS:
        raw_path = getattr(cfg.io, field_name)
        if raw_path is None:
            continue
        if raw_path.is_absolute():
            resolved = raw_path
        elif sync_root is not None:
            resolved = (sync_root / raw_path).resolve()
        else:
            resolved = (project_root / raw_path).resolve()
        setattr(cfg.io, field_name, resolved)

    for field_name in _INTERNAL_IO_FIELDS:
        resolved = _resolve_path(getattr(cfg.io, field_name), project_root)
        if resolved is not None:
            setattr(cfg.io, field_name, resolved)

    return cfg


def load_config(
    path,
    local_paths_path: Optional[Path | str] = None,
) -> HPAConfig:
    config_path = Path(path).expanduser().resolve()
    project_root = _project_root_from_config(config_path)

    data = _read_yaml(config_path)
    overlay_path = _discover_local_paths_path(config_path, local_paths_path)
    if overlay_path is not None and overlay_path.exists():
        data = _deep_merge(data, _read_yaml(overlay_path))

    cfg = HPAConfig(**data)
    return _resolve_io_paths(cfg, project_root)
