from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConceptBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnvironmentConfig(ConceptBaseModel):
    temperature_c: float = Field(..., gt=-50.0, lt=80.0)
    relative_humidity: float = Field(..., ge=0.0, le=100.0)
    altitude_m: float = Field(0.0, ge=-100.0)


class MassConfig(ConceptBaseModel):
    pilot_mass_kg: float = Field(..., gt=0.0)
    baseline_aircraft_mass_kg: float = Field(..., gt=0.0)
    gross_mass_sweep_kg: tuple[float, ...] = Field(..., min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_gross_mass_sweep(self) -> MassConfig:
        if any(mass <= 0.0 for mass in self.gross_mass_sweep_kg):
            raise ValueError("mass.gross_mass_sweep_kg entries must all be positive.")
        if any(
            later < earlier
            for earlier, later in zip(self.gross_mass_sweep_kg, self.gross_mass_sweep_kg[1:])
        ):
            raise ValueError("mass.gross_mass_sweep_kg must be non-decreasing.")
        min_gross_mass = self.pilot_mass_kg + self.baseline_aircraft_mass_kg
        if any(mass < min_gross_mass for mass in self.gross_mass_sweep_kg):
            raise ValueError(
                "mass.gross_mass_sweep_kg entries must be >= pilot_mass_kg + baseline_aircraft_mass_kg."
            )
        return self


class MissionConfig(ConceptBaseModel):
    target_distance_km: float = Field(42.195, gt=0.0)
    rider_model: Literal["fake_anchor_curve"] = "fake_anchor_curve"
    anchor_power_w: float = Field(300.0, gt=0.0)
    anchor_duration_min: float = Field(30.0, gt=0.0)
    speed_sweep_min_mps: float = Field(6.0, gt=0.0)
    speed_sweep_max_mps: float = Field(10.0, gt=0.0)
    speed_sweep_points: int = Field(9, ge=3)

    @model_validator(mode="after")
    def validate_speed_sweep_bounds(self) -> MissionConfig:
        if self.speed_sweep_max_mps <= self.speed_sweep_min_mps:
            raise ValueError("mission.speed_sweep_max_mps must be > mission.speed_sweep_min_mps.")
        return self


class SegmentationConfig(ConceptBaseModel):
    min_segment_length_m: float = Field(1.0, gt=0.0)
    max_segment_length_m: float = Field(3.0, gt=0.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> SegmentationConfig:
        if self.max_segment_length_m < self.min_segment_length_m:
            raise ValueError("segmentation.max_segment_length_m must be >= min_segment_length_m.")
        return self


class LaunchConfig(ConceptBaseModel):
    platform_height_m: float = Field(10.0, gt=0.0)
    runup_length_m: float = Field(10.0, gt=0.0)
    use_ground_effect: bool = True


class TurnConfig(ConceptBaseModel):
    required_bank_angle_deg: float = Field(15.0, gt=0.0, lt=45.0)


class GeometryFamilyConfig(ConceptBaseModel):
    span_candidates_m: tuple[float, ...] = Field((30.0, 32.0, 34.0), min_length=1)
    wing_area_candidates_m2: tuple[float, ...] = Field((26.0, 28.0, 30.0), min_length=1)
    taper_ratio_candidates: tuple[float, ...] = Field((0.30, 0.35, 0.40), min_length=1)
    twist_tip_candidates_deg: tuple[float, ...] = Field((-2.0, -1.5, -1.0), min_length=1)
    tail_area_candidates_m2: tuple[float, ...] = Field((3.8, 4.2, 4.6), min_length=1)

    @model_validator(mode="after")
    def validate_candidate_ranges(self) -> GeometryFamilyConfig:
        if len(set(self.span_candidates_m)) != len(self.span_candidates_m):
            raise ValueError("geometry_family.span_candidates_m entries must be unique.")
        if len(set(self.wing_area_candidates_m2)) != len(self.wing_area_candidates_m2):
            raise ValueError("geometry_family.wing_area_candidates_m2 entries must be unique.")
        if len(set(self.taper_ratio_candidates)) != len(self.taper_ratio_candidates):
            raise ValueError("geometry_family.taper_ratio_candidates entries must be unique.")
        if len(set(self.twist_tip_candidates_deg)) != len(self.twist_tip_candidates_deg):
            raise ValueError("geometry_family.twist_tip_candidates_deg entries must be unique.")
        if len(set(self.tail_area_candidates_m2)) != len(self.tail_area_candidates_m2):
            raise ValueError("geometry_family.tail_area_candidates_m2 entries must be unique.")
        if any(span <= 0.0 for span in self.span_candidates_m):
            raise ValueError("geometry_family.span_candidates_m entries must all be positive.")
        if any(area <= 0.0 for area in self.wing_area_candidates_m2):
            raise ValueError("geometry_family.wing_area_candidates_m2 entries must all be positive.")
        if any(taper <= 0.0 or taper > 1.0 for taper in self.taper_ratio_candidates):
            raise ValueError(
                "geometry_family.taper_ratio_candidates entries must be in the interval (0, 1]."
            )
        if any(twist < -10.0 or twist > 10.0 for twist in self.twist_tip_candidates_deg):
            raise ValueError(
                "geometry_family.twist_tip_candidates_deg entries must be in the interval [-10, 10]."
            )
        if any(tail_area <= 0.0 for tail_area in self.tail_area_candidates_m2):
            raise ValueError("geometry_family.tail_area_candidates_m2 entries must all be positive.")
        return self


class BirdmanConceptConfig(ConceptBaseModel):
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
