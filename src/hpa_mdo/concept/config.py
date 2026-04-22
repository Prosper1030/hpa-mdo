from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class EnvironmentConfig(BaseModel):
    temperature_c: float = Field(..., gt=-50.0, lt=80.0)
    relative_humidity: float = Field(..., ge=0.0, le=100.0)
    altitude_m: float = Field(0.0, ge=-100.0)


class MassConfig(BaseModel):
    pilot_mass_kg: float = Field(..., gt=0.0)
    baseline_aircraft_mass_kg: float = Field(..., gt=0.0)
    gross_mass_sweep_kg: tuple[float, ...] = Field(..., min_length=3, max_length=3)


class MissionConfig(BaseModel):
    target_distance_km: float = Field(42.195, gt=0.0)
    rider_model: Literal["fake_anchor_curve"] = "fake_anchor_curve"
    anchor_power_w: float = Field(300.0, gt=0.0)
    anchor_duration_min: float = Field(30.0, gt=0.0)
    speed_sweep_min_mps: float = Field(6.0, gt=0.0)
    speed_sweep_max_mps: float = Field(10.0, gt=0.0)
    speed_sweep_points: int = Field(9, ge=3)


class SegmentationConfig(BaseModel):
    min_segment_length_m: float = Field(1.0, gt=0.0)
    max_segment_length_m: float = Field(3.0, gt=0.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> SegmentationConfig:
        if self.max_segment_length_m < self.min_segment_length_m:
            raise ValueError("segmentation.max_segment_length_m must be >= min_segment_length_m.")
        return self


class LaunchConfig(BaseModel):
    platform_height_m: float = Field(10.0, gt=0.0)
    runup_length_m: float = Field(10.0, gt=0.0)
    use_ground_effect: bool = True


class TurnConfig(BaseModel):
    required_bank_angle_deg: float = Field(15.0, gt=0.0, lt=45.0)


class GeometryFamilyConfig(BaseModel):
    span_candidates_m: tuple[float, ...] = Field((30.0, 32.0, 34.0), min_length=1)
    wing_area_candidates_m2: tuple[float, ...] = Field((26.0, 28.0, 30.0), min_length=1)
    taper_ratio_candidates: tuple[float, ...] = Field((0.30, 0.35, 0.40), min_length=1)
    twist_tip_candidates_deg: tuple[float, ...] = Field((-2.0, -1.5, -1.0), min_length=1)
    tail_area_candidates_m2: tuple[float, ...] = Field((3.8, 4.2, 4.6), min_length=1)


class BirdmanConceptConfig(BaseModel):
    environment: EnvironmentConfig
    mass: MassConfig
    mission: MissionConfig
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    launch: LaunchConfig = Field(default_factory=LaunchConfig)
    turn: TurnConfig = Field(default_factory=TurnConfig)
    geometry_family: GeometryFamilyConfig = Field(default_factory=GeometryFamilyConfig)


def load_concept_config(path: str | Path) -> BirdmanConceptConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return BirdmanConceptConfig.model_validate(payload)
