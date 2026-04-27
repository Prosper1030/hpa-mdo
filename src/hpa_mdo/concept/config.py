from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from hpa_mdo.concept.airfoil_cst import (
    DEFAULT_CAMBER_DELTA_LEVELS,
    DEFAULT_THICKNESS_DELTA_LEVELS,
)


class ConceptBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnvironmentConfig(ConceptBaseModel):
    temperature_c: float = Field(..., gt=-50.0, lt=80.0)
    relative_humidity: float = Field(..., ge=0.0, le=100.0)
    altitude_m: float = Field(0.0, ge=-100.0)


class MassConfig(ConceptBaseModel):
    pilot_mass_kg: float = Field(..., gt=0.0)
    baseline_aircraft_mass_kg: float = Field(..., gt=0.0)
    # Reference aircraft mass is a starting estimate, not a lower bound on
    # the independently swept total gross-mass cases.
    gross_mass_sweep_kg: tuple[float, ...] = Field(..., min_length=3, max_length=3)
    design_gross_mass_kg: float | None = Field(
        None,
        gt=0.0,
        description=(
            "Mass case used to derive the primary wing sizing geometry. "
            "Defaults to the heaviest gross_mass_sweep_kg case so the concept "
            "line does not under-size the wing around an optimistic mass."
        ),
    )

    @model_validator(mode="after")
    def validate_gross_mass_sweep(self) -> MassConfig:
        if any(mass <= 0.0 for mass in self.gross_mass_sweep_kg):
            raise ValueError("mass.gross_mass_sweep_kg entries must all be positive.")
        if any(
            later < earlier
            for earlier, later in zip(self.gross_mass_sweep_kg, self.gross_mass_sweep_kg[1:])
        ):
            raise ValueError("mass.gross_mass_sweep_kg must be non-decreasing.")
        if self.design_gross_mass_kg is None:
            self.design_gross_mass_kg = float(max(self.gross_mass_sweep_kg))
        if not (
            min(self.gross_mass_sweep_kg)
            <= float(self.design_gross_mass_kg)
            <= max(self.gross_mass_sweep_kg)
        ):
            raise ValueError(
                "mass.design_gross_mass_kg must lie within mass.gross_mass_sweep_kg."
            )
        return self


class TubeSystemGeometryConfig(ConceptBaseModel):
    estimation_enabled: bool = True
    root_outer_diameter_m: float = Field(0.10, gt=0.0)
    tip_outer_diameter_m: float = Field(0.05, gt=0.0)
    root_wall_thickness_m: float = Field(0.0010, gt=0.0)
    tip_wall_thickness_m: float = Field(0.0006, gt=0.0)
    density_kg_per_m3: float = Field(1600.0, gt=0.0)
    num_spars_per_wing: int = Field(2, ge=1)
    num_wings: int = Field(2, ge=1)


class MassClosureConfig(ConceptBaseModel):
    enabled: bool = True
    fixed_nonwing_aircraft_mass_kg: float = Field(24.0, gt=0.0)
    tube_system_mass_kg: float = Field(10.5, ge=0.0)
    tube_system: TubeSystemGeometryConfig = Field(default_factory=TubeSystemGeometryConfig)
    rib_skin_areal_density_kgpm2: float = Field(0.20, ge=0.0)
    wing_fittings_base_kg: float = Field(1.5, ge=0.0)
    wire_terminal_mass_kg: float = Field(0.6, ge=0.0)
    system_margin_kg: float = Field(2.0, ge=0.0)
    gross_mass_hard_max_kg: float = Field(107.0, gt=0.0)
    area_tolerance_m2: float = Field(1.0e-6, gt=0.0)
    max_iterations: int = Field(50, ge=1)


class MissionConfig(ConceptBaseModel):
    objective_mode: Literal["max_range", "min_power"] = "max_range"
    target_distance_km: float = Field(42.195, gt=0.0)
    rider_model: Literal["fake_anchor_curve", "csv_power_curve"] = "fake_anchor_curve"
    anchor_power_w: float = Field(300.0, gt=0.0)
    anchor_duration_min: float = Field(30.0, gt=0.0)
    rider_power_curve_csv: str | None = None
    rider_power_curve_duration_column: str = "secs"
    rider_power_curve_power_column: str = "watts"
    speed_sweep_min_mps: float = Field(6.0, gt=0.0)
    speed_sweep_max_mps: float = Field(10.0, gt=0.0)
    speed_sweep_points: int = Field(9, ge=3)

    @model_validator(mode="after")
    def validate_speed_sweep_bounds(self) -> MissionConfig:
        if self.speed_sweep_max_mps <= self.speed_sweep_min_mps:
            raise ValueError("mission.speed_sweep_max_mps must be > mission.speed_sweep_min_mps.")
        if self.rider_model == "csv_power_curve" and self.rider_power_curve_csv is None:
            raise ValueError(
                "mission.rider_power_curve_csv must be provided when mission.rider_model=csv_power_curve."
            )
        if self.rider_power_curve_csv is not None:
            csv_path = Path(self.rider_power_curve_csv).expanduser()
            if not csv_path.exists():
                raise ValueError(
                    f"mission.rider_power_curve_csv does not exist: {csv_path}"
                )
            if not self.rider_power_curve_duration_column.strip():
                raise ValueError(
                    "mission.rider_power_curve_duration_column must not be blank."
                )
            if not self.rider_power_curve_power_column.strip():
                raise ValueError(
                    "mission.rider_power_curve_power_column must not be blank."
                )
        return self

    @property
    def resolved_rider_model(self) -> str:
        return "csv_power_curve" if self.rider_power_curve_csv is not None else str(self.rider_model)


class SegmentationConfig(ConceptBaseModel):
    min_segment_length_m: float = Field(1.0, gt=0.0)
    max_segment_length_m: float = Field(3.0, gt=0.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> SegmentationConfig:
        if self.max_segment_length_m < self.min_segment_length_m:
            raise ValueError("segmentation.max_segment_length_m must be >= min_segment_length_m.")
        return self


class LaunchConfig(ConceptBaseModel):
    mode: Literal["restrained_pre_spin"] = "restrained_pre_spin"
    prop_ready_before_release: bool = True
    release_speed_mps: float = Field(8.0, gt=0.0)
    release_rpm: float = Field(140.0, gt=0.0)
    min_trim_margin_deg: float = Field(2.0, gt=0.0)
    platform_height_m: float = Field(10.0, gt=0.0)
    runup_length_m: float = Field(10.0, gt=0.0)
    use_ground_effect: bool = True


class StallModelConfig(ConceptBaseModel):
    safe_clmax_scale: float = Field(0.90, gt=0.0, le=1.0)
    safe_clmax_delta: float = Field(0.05, ge=0.0)
    tip_3d_penalty_start_eta: float = Field(0.55, ge=0.0, lt=1.0)
    tip_3d_penalty_max: float = Field(0.04, ge=0.0)
    tip_taper_penalty_weight: float = Field(0.35, ge=0.0)
    washout_relief_deg: float = Field(2.0, gt=0.0)
    washout_relief_max: float = Field(0.02, ge=0.0)
    local_stall_utilization_limit: float = Field(0.75, gt=0.0, lt=1.0)
    turn_utilization_limit: float = Field(0.75, gt=0.0, lt=1.0)
    launch_utilization_limit: float = Field(0.85, gt=0.0, lt=1.0)
    slow_speed_report_utilization_limit: float = Field(0.85, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def validate_limit_order(self) -> StallModelConfig:
        if self.washout_relief_max > (self.tip_3d_penalty_max * (1.0 + self.tip_taper_penalty_weight)):
            raise ValueError(
                "stall_model.washout_relief_max must not exceed the configured tip 3D penalty budget."
            )
        return self


class PropConfig(ConceptBaseModel):
    blade_count: int = Field(2, ge=1)
    diameter_m: float = Field(3.0, gt=0.0)
    rpm_min: float = Field(100.0, gt=0.0)
    rpm_max: float = Field(160.0, gt=0.0)
    position_mode: Literal["between_wing_and_tail"] = "between_wing_and_tail"

    @model_validator(mode="after")
    def validate_rpm_bounds(self) -> PropConfig:
        if self.rpm_max <= self.rpm_min:
            raise ValueError("prop.rpm_max must be > prop.rpm_min.")
        return self


class TurnConfig(ConceptBaseModel):
    required_bank_angle_deg: float = Field(15.0, gt=0.0, lt=45.0)


class TailModelConfig(ConceptBaseModel):
    wing_ac_xc: float = Field(0.25, ge=0.0, le=1.0)
    tail_arm_to_mac: float = Field(4.0, gt=0.0)
    tail_dynamic_pressure_ratio: float = Field(0.90, gt=0.0, le=1.5)
    tail_efficiency: float = Field(0.90, gt=0.0, le=1.5)
    tail_cl_limit_abs: float = Field(0.80, gt=0.0)
    tail_aspect_ratio: float = Field(5.0, gt=0.0)
    tail_oswald_efficiency: float = Field(0.85, gt=0.0, le=1.5)
    body_cm_offset: float = Field(0.0, ge=-0.25, le=0.25)
    cm_spread_factor: float = Field(0.50, ge=0.0)


class ContinuousRangeConfig(ConceptBaseModel):
    min: float
    max: float

    @model_validator(mode="after")
    def validate_bounds(self) -> ContinuousRangeConfig:
        if self.max < self.min:
            raise ValueError("range.max must be >= range.min.")
        return self


class GeometrySamplingConfig(ConceptBaseModel):
    mode: Literal["latin_hypercube", "sobol", "uniform_random", "linspace_grid"] = (
        "latin_hypercube"
    )
    sample_count: int = Field(48, ge=1)
    seed: int = 42
    scramble: bool = True


class GeometryPrimaryRangesConfig(ConceptBaseModel):
    span_m: ContinuousRangeConfig = Field(
        default_factory=lambda: ContinuousRangeConfig(min=30.0, max=36.0)
    )
    wing_loading_target_Npm2: ContinuousRangeConfig = Field(
        default_factory=lambda: ContinuousRangeConfig(min=26.0, max=34.0)
    )
    taper_ratio: ContinuousRangeConfig = Field(
        default_factory=lambda: ContinuousRangeConfig(min=0.24, max=0.40)
    )
    tip_twist_deg: ContinuousRangeConfig = Field(
        default_factory=lambda: ContinuousRangeConfig(min=-3.0, max=-0.5)
    )

    @model_validator(mode="after")
    def validate_ranges(self) -> GeometryPrimaryRangesConfig:
        if self.span_m.min <= 0.0:
            raise ValueError("geometry_family.primary_ranges.span_m must stay positive.")
        if self.wing_loading_target_Npm2.min <= 0.0:
            raise ValueError(
                "geometry_family.primary_ranges.wing_loading_target_Npm2 must stay positive."
            )
        if self.taper_ratio.min <= 0.0 or self.taper_ratio.max > 1.0:
            raise ValueError(
                "geometry_family.primary_ranges.taper_ratio must stay within (0, 1]."
            )
        if self.tip_twist_deg.min < -10.0 or self.tip_twist_deg.max > 10.0:
            raise ValueError(
                "geometry_family.primary_ranges.tip_twist_deg must stay within [-10, 10]."
            )
        return self


class GeometryHardConstraintConfig(ConceptBaseModel):
    wing_area_m2_range: ContinuousRangeConfig = Field(
        default_factory=lambda: ContinuousRangeConfig(min=28.0, max=42.0)
    )
    aspect_ratio_range: ContinuousRangeConfig = Field(
        default_factory=lambda: ContinuousRangeConfig(min=24.0, max=36.0)
    )
    root_chord_min_m: float = Field(1.20, gt=0.0)
    tip_chord_min_m: float = Field(0.30, gt=0.0)
    segment_min_chord_m: float = Field(0.32, gt=0.0)
    root_zone_min_tc_ratio: float = Field(0.14, gt=0.0, le=1.0)
    root_zone_spar_depth_fraction: float = Field(0.62, gt=0.0, le=1.0)
    root_zone_required_spar_depth_m: float = Field(0.10, gt=0.0)


class GeometryFamilyConfig(ConceptBaseModel):
    sampling: GeometrySamplingConfig = Field(default_factory=GeometrySamplingConfig)
    primary_ranges: GeometryPrimaryRangesConfig = Field(
        default_factory=GeometryPrimaryRangesConfig
    )
    hard_constraints: GeometryHardConstraintConfig = Field(
        default_factory=GeometryHardConstraintConfig
    )
    twist_root_deg: float = Field(
        2.0,
        description=(
            "Root twist stays fixed so tip_twist_deg remains the primary wing twist variable."
        ),
    )
    tail_area_candidates_m2: tuple[float, ...] = Field((3.8, 4.2, 4.6), min_length=1)
    dihedral_root_deg_candidates: tuple[float, ...] = Field((0.0, 1.0, 2.0), min_length=1)
    dihedral_tip_deg_candidates: tuple[float, ...] = Field((4.0, 6.0, 8.0), min_length=1)
    dihedral_exponent_candidates: tuple[float, ...] = Field((1.0, 1.5, 2.0), min_length=1)

    @model_validator(mode="after")
    def validate_candidate_ranges(self) -> GeometryFamilyConfig:
        if len(set(self.tail_area_candidates_m2)) != len(self.tail_area_candidates_m2):
            raise ValueError("geometry_family.tail_area_candidates_m2 entries must be unique.")
        if len(set(self.dihedral_root_deg_candidates)) != len(self.dihedral_root_deg_candidates):
            raise ValueError(
                "geometry_family.dihedral_root_deg_candidates entries must be unique."
            )
        if len(set(self.dihedral_tip_deg_candidates)) != len(self.dihedral_tip_deg_candidates):
            raise ValueError("geometry_family.dihedral_tip_deg_candidates entries must be unique.")
        if len(set(self.dihedral_exponent_candidates)) != len(self.dihedral_exponent_candidates):
            raise ValueError(
                "geometry_family.dihedral_exponent_candidates entries must be unique."
            )
        if any(tail_area <= 0.0 for tail_area in self.tail_area_candidates_m2):
            raise ValueError("geometry_family.tail_area_candidates_m2 entries must all be positive.")
        if any(root < -10.0 or root > 10.0 for root in self.dihedral_root_deg_candidates):
            raise ValueError(
                "geometry_family.dihedral_root_deg_candidates entries must be in the interval [-10, 10]."
            )
        if any(tip < -10.0 or tip > 10.0 for tip in self.dihedral_tip_deg_candidates):
            raise ValueError(
                "geometry_family.dihedral_tip_deg_candidates entries must be in the interval [-10, 10]."
            )
        if min(self.dihedral_tip_deg_candidates) < max(self.dihedral_root_deg_candidates):
            raise ValueError(
                "geometry_family.dihedral_tip_deg_candidates must be >= dihedral_root_deg_candidates."
            )
        if any(exponent <= 0.0 for exponent in self.dihedral_exponent_candidates):
            raise ValueError(
                "geometry_family.dihedral_exponent_candidates entries must be positive."
            )
        if self.twist_root_deg < -10.0 or self.twist_root_deg > 10.0:
            raise ValueError("geometry_family.twist_root_deg must be in the interval [-10, 10].")
        return self


class CSTSearchConfig(ConceptBaseModel):
    search_mode: Literal["seed_neighborhood", "seedless_sobol"] = "seed_neighborhood"
    selection_strategy: Literal["scalar_score", "constrained_pareto"] = "scalar_score"
    thickness_delta_levels: tuple[float, ...] = Field(
        DEFAULT_THICKNESS_DELTA_LEVELS,
        min_length=3,
    )
    camber_delta_levels: tuple[float, ...] = Field(
        DEFAULT_CAMBER_DELTA_LEVELS,
        min_length=3,
    )
    coarse_to_fine_enabled: bool = True
    coarse_thickness_stride: int = Field(2, ge=1)
    coarse_camber_stride: int = Field(2, ge=1)
    coarse_keep_top_k: int = Field(2, ge=1)
    refine_neighbor_radius: int = Field(1, ge=0)
    seedless_sample_count: int = Field(32, ge=1)
    seedless_random_seed: int | None = 0
    seedless_max_oversample_factor: int = Field(8, ge=1)
    robust_evaluation_enabled: bool = False
    robust_reynolds_factors: tuple[float, ...] = (0.85, 1.0, 1.15)
    robust_roughness_modes: tuple[str, ...] = ("clean", "rough")
    robust_min_pass_rate: float = Field(0.75, gt=0.0, le=1.0)
    nsga_generation_count: int = Field(0, ge=0)
    nsga_offspring_count: int = Field(0, ge=0)
    nsga_parent_count: int = Field(8, ge=2)
    nsga_random_seed: int | None = 0
    nsga_mutation_scale: float = Field(0.06, ge=0.0, le=0.50)
    successive_halving_enabled: bool = True
    successive_halving_rounds: int = Field(2, ge=1)
    successive_halving_beam_width: int = Field(6, ge=1)
    cm_hard_lower_bound: float = Field(-0.16, le=0.0)
    cm_penalty_threshold: float = Field(-0.12, le=0.0)
    pareto_knee_count: int = Field(0, ge=0)
    cma_es_enabled: bool = False
    cma_es_knee_count: int = Field(0, ge=0)
    cma_es_iterations: int = Field(0, ge=0)
    cma_es_population_lambda: int = Field(16, ge=2)
    cma_es_sigma_init: float = Field(0.05, gt=0.0, le=1.0)
    cma_es_random_seed: int | None = 0

    @model_validator(mode="after")
    def validate_levels(self) -> CSTSearchConfig:
        for name in ("thickness_delta_levels", "camber_delta_levels"):
            levels = tuple(float(level) for level in getattr(self, name))
            if len(set(levels)) != len(levels):
                raise ValueError(f"cst_search.{name} entries must be unique.")
            if any(later < earlier for earlier, later in zip(levels, levels[1:])):
                raise ValueError(f"cst_search.{name} must be non-decreasing.")
            if 0.0 not in levels:
                raise ValueError(f"cst_search.{name} must include 0.0.")
            if any(abs(level) > 0.05 for level in levels):
                raise ValueError(f"cst_search.{name} entries must stay within +/-0.05.")
        if not self.robust_reynolds_factors:
            raise ValueError("cst_search.robust_reynolds_factors must not be empty.")
        if any(float(factor) <= 0.0 for factor in self.robust_reynolds_factors):
            raise ValueError("cst_search.robust_reynolds_factors entries must be positive.")
        if not self.robust_roughness_modes or any(
            not str(mode).strip() for mode in self.robust_roughness_modes
        ):
            raise ValueError("cst_search.robust_roughness_modes entries must be non-empty.")
        candidate_count = (
            self.seedless_sample_count
            if self.search_mode == "seedless_sobol"
            else len(self.thickness_delta_levels) * len(self.camber_delta_levels)
        )
        if self.coarse_keep_top_k > candidate_count:
            raise ValueError(
                "cst_search.coarse_keep_top_k must not exceed the total candidate count."
            )
        if self.successive_halving_beam_width > candidate_count:
            raise ValueError(
                "cst_search.successive_halving_beam_width must not exceed the total candidate count."
            )
        if self.cm_hard_lower_bound > self.cm_penalty_threshold:
            raise ValueError(
                "cst_search.cm_hard_lower_bound must be less than or equal to cm_penalty_threshold."
            )
        if self.cma_es_enabled:
            if self.cma_es_knee_count <= 0:
                raise ValueError(
                    "cst_search.cma_es_knee_count must be >= 1 when cma_es_enabled."
                )
            if self.cma_es_iterations <= 0:
                raise ValueError(
                    "cst_search.cma_es_iterations must be >= 1 when cma_es_enabled."
                )
            if self.pareto_knee_count <= 0:
                raise ValueError(
                    "cst_search.pareto_knee_count must be >= 1 when cma_es_enabled "
                    "(CMA-ES refines Pareto knees)."
                )
            if self.cma_es_knee_count > self.pareto_knee_count:
                raise ValueError(
                    "cst_search.cma_es_knee_count must not exceed pareto_knee_count."
                )
        return self


class PipelineConfig(ConceptBaseModel):
    stations_per_half: int = Field(7, ge=2)
    keep_top_n: int = Field(5, ge=1)
    finalist_full_sweep_top_l: int = Field(3, ge=1)

    @model_validator(mode="after")
    def clamp_finalist_full_sweep_top_l(self) -> PipelineConfig:
        if self.finalist_full_sweep_top_l > self.keep_top_n:
            self.finalist_full_sweep_top_l = self.keep_top_n
        return self


class PolarWorkerConfig(ConceptBaseModel):
    persistent_worker_count: int = Field(4, ge=1, le=64)
    log_cache_statistics: bool = True
    xfoil_max_iter: int = Field(40, ge=10, le=200)
    xfoil_panel_count: int = Field(96, ge=40, le=200)


class OutputConfig(ConceptBaseModel):
    export_candidate_bundle: bool = True
    export_vsp: bool = False
    export_vsp_for_top_n: int = Field(0, ge=0)

    @model_validator(mode="after")
    def validate_vsp_exports(self) -> OutputConfig:
        if not self.export_vsp and self.export_vsp_for_top_n != 0:
            raise ValueError(
                "output.export_vsp_for_top_n must be 0 when output.export_vsp is false."
            )
        return self


class BirdmanConceptConfig(ConceptBaseModel):
    environment: EnvironmentConfig
    mass: MassConfig
    mass_closure: MassClosureConfig = Field(default_factory=MassClosureConfig)
    mission: MissionConfig
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    launch: LaunchConfig = Field(default_factory=LaunchConfig)
    stall_model: StallModelConfig = Field(default_factory=StallModelConfig)
    prop: PropConfig = Field(default_factory=PropConfig)
    turn: TurnConfig = Field(default_factory=TurnConfig)
    tail_model: TailModelConfig = Field(default_factory=TailModelConfig)
    geometry_family: GeometryFamilyConfig = Field(default_factory=GeometryFamilyConfig)
    cst_search: CSTSearchConfig = Field(default_factory=CSTSearchConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    polar_worker: PolarWorkerConfig = Field(default_factory=PolarWorkerConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="after")
    def validate_cross_section(self) -> BirdmanConceptConfig:
        if not (self.prop.rpm_min <= self.launch.release_rpm <= self.prop.rpm_max):
            raise ValueError("launch.release_rpm must fall within prop.rpm_min and prop.rpm_max.")
        if self.output.export_vsp_for_top_n > self.pipeline.keep_top_n:
            raise ValueError("output.export_vsp_for_top_n must be <= pipeline.keep_top_n.")
        return self

    @property
    def design_gross_weight_n(self) -> float:
        return float(self.mass.design_gross_mass_kg) * 9.80665


def load_concept_config(path: str | Path) -> BirdmanConceptConfig:
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    mission_payload = payload.get("mission")
    if isinstance(mission_payload, dict):
        rider_power_curve_csv = mission_payload.get("rider_power_curve_csv")
        if rider_power_curve_csv is not None:
            mission_payload["rider_power_curve_csv"] = str(
                _resolve_optional_artifact_path(
                    raw_path=rider_power_curve_csv,
                    config_path=path,
                )
            )
    return BirdmanConceptConfig.model_validate(payload)


def _resolve_optional_artifact_path(
    *,
    raw_path: str | Path,
    config_path: Path,
) -> Path:
    raw_path = Path(raw_path).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve()

    repo_root = Path(__file__).resolve().parents[3]
    candidate_paths = [
        (config_path.resolve().parent / raw_path).resolve(),
        (repo_root / raw_path).resolve(),
    ]
    for candidate_path in candidate_paths:
        if candidate_path.exists():
            return candidate_path
    return candidate_paths[0]
