from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from math import floor, isclose
from itertools import product

import numpy as np
from scipy.stats import qmc

from hpa_mdo.concept.atmosphere import air_properties_from_environment
from hpa_mdo.concept.jig_shape import estimate_tip_deflection
from hpa_mdo.concept.lift_wire import estimate_lift_wire_tension_n
from hpa_mdo.concept.mass_closure import (
    estimate_tube_system_mass_kg,
)


def _resolve_tube_system_mass_kg(mass_closure_cfg, *, span_m: float) -> float:
    tube_geom = getattr(mass_closure_cfg, "tube_system", None)
    if tube_geom is not None and bool(tube_geom.estimation_enabled):
        return estimate_tube_system_mass_kg(
            span_m=float(span_m),
            root_outer_diameter_m=float(tube_geom.root_outer_diameter_m),
            tip_outer_diameter_m=float(tube_geom.tip_outer_diameter_m),
            root_wall_thickness_m=float(tube_geom.root_wall_thickness_m),
            tip_wall_thickness_m=float(tube_geom.tip_wall_thickness_m),
            density_kg_per_m3=float(tube_geom.density_kg_per_m3),
            num_spars_per_wing=int(tube_geom.num_spars_per_wing),
            num_wings=int(tube_geom.num_wings),
        )
    return float(mass_closure_cfg.tube_system_mass_kg)


def _tube_mass_source_tag(mass_closure_cfg) -> str:
    tube_geom = getattr(mass_closure_cfg, "tube_system", None)
    if tube_geom is not None and bool(tube_geom.estimation_enabled):
        return "geometry_thin_wall_v1"
    return "fixed_value"


@dataclass(frozen=True)
class WingStation:
    y_m: float
    chord_m: float
    twist_deg: float
    dihedral_deg: float


@dataclass(frozen=True)
class GeometryConcept:
    span_m: float
    wing_area_m2: float
    root_chord_m: float
    tip_chord_m: float
    twist_root_deg: float
    twist_tip_deg: float
    tail_area_m2: float
    cg_xc: float
    segment_lengths_m: tuple[float, ...]
    tail_area_source: str = "fixed_area_candidate"
    tail_volume_coefficient: float | None = None
    twist_control_points: tuple[tuple[float, float], ...] = ()
    spanload_bias: float = 0.0
    spanload_a3_over_a1: float = -0.05
    spanload_a5_over_a1: float = 0.0
    wing_loading_target_Npm2: float | None = None
    mean_chord_target_m: float | None = None
    wing_area_is_derived: bool = False
    planform_parameterization: str = "wing_loading"
    design_gross_mass_kg: float | None = None
    dihedral_root_deg: float = 0.0
    dihedral_tip_deg: float = 0.0
    dihedral_exponent: float = 1.0
    tip_deflection_ratio_at_design_mass: float | None = None
    tip_deflection_m_at_design_mass: float | None = None
    effective_dihedral_deg_at_design_mass: float | None = None
    unbraced_tip_deflection_m_at_design_mass: float | None = None
    lift_wire_relief_deflection_m_at_design_mass: float | None = None
    tip_deflection_preferred_status: str | None = None
    lift_wire_tension_at_limit_n: float | None = None

    def __post_init__(self) -> None:
        segment_lengths_m = tuple(float(length) for length in self.segment_lengths_m)
        object.__setattr__(self, "segment_lengths_m", segment_lengths_m)

        if self.span_m <= 0.0:
            raise ValueError("span_m must be positive.")
        if self.wing_area_m2 <= 0.0:
            raise ValueError("wing_area_m2 must be positive.")
        if self.root_chord_m <= 0.0:
            raise ValueError("root_chord_m must be positive.")
        if self.tip_chord_m <= 0.0:
            raise ValueError("tip_chord_m must be positive.")
        if self.dihedral_exponent <= 0.0:
            raise ValueError("dihedral_exponent must be positive.")
        if self.tail_area_m2 <= 0.0:
            raise ValueError("tail_area_m2 must be positive.")
        if self.tail_volume_coefficient is not None and self.tail_volume_coefficient <= 0.0:
            raise ValueError("tail_volume_coefficient must be positive when provided.")
        if self.spanload_bias < 0.0:
            raise ValueError("spanload_bias must be non-negative.")
        if not -0.5 <= self.spanload_a3_over_a1 <= 0.5:
            raise ValueError("spanload_a3_over_a1 must stay within [-0.5, 0.5].")
        if not -0.5 <= self.spanload_a5_over_a1 <= 0.5:
            raise ValueError("spanload_a5_over_a1 must stay within [-0.5, 0.5].")
        if self.wing_loading_target_Npm2 is not None and self.wing_loading_target_Npm2 <= 0.0:
            raise ValueError("wing_loading_target_Npm2 must be positive when provided.")
        if self.mean_chord_target_m is not None and self.mean_chord_target_m <= 0.0:
            raise ValueError("mean_chord_target_m must be positive when provided.")
        if self.design_gross_mass_kg is not None and self.design_gross_mass_kg <= 0.0:
            raise ValueError("design_gross_mass_kg must be positive when provided.")
        if (
            self.tip_deflection_ratio_at_design_mass is not None
            and self.tip_deflection_ratio_at_design_mass < 0.0
        ):
            raise ValueError(
                "tip_deflection_ratio_at_design_mass must be non-negative when provided."
            )
        for field_name, value in (
            ("tip_deflection_m_at_design_mass", self.tip_deflection_m_at_design_mass),
            (
                "effective_dihedral_deg_at_design_mass",
                self.effective_dihedral_deg_at_design_mass,
            ),
            (
                "unbraced_tip_deflection_m_at_design_mass",
                self.unbraced_tip_deflection_m_at_design_mass,
            ),
            (
                "lift_wire_relief_deflection_m_at_design_mass",
                self.lift_wire_relief_deflection_m_at_design_mass,
            ),
        ):
            if value is not None and value < 0.0:
                raise ValueError(f"{field_name} must be non-negative when provided.")
        if self.tip_deflection_preferred_status is not None and self.tip_deflection_preferred_status not in {
            "below_preferred",
            "within_preferred",
            "above_preferred",
        }:
            raise ValueError("tip_deflection_preferred_status has an unsupported value.")
        if (
            self.lift_wire_tension_at_limit_n is not None
            and self.lift_wire_tension_at_limit_n < 0.0
        ):
            raise ValueError(
                "lift_wire_tension_at_limit_n must be non-negative when provided."
            )
        if not 0.0 <= self.cg_xc <= 1.0:
            raise ValueError("cg_xc must be in [0, 1].")
        if self.dihedral_root_deg < -10.0 or self.dihedral_root_deg > 10.0:
            raise ValueError("dihedral_root_deg must be in [-10, 10].")
        if self.dihedral_tip_deg < -10.0 or self.dihedral_tip_deg > 10.0:
            raise ValueError("dihedral_tip_deg must be in [-10, 10].")
        if self.dihedral_tip_deg < self.dihedral_root_deg:
            raise ValueError("dihedral_tip_deg must be >= dihedral_root_deg.")
        if not self.segment_lengths_m:
            raise ValueError("segment_lengths_m must not be empty.")
        if any(length <= 0.0 for length in self.segment_lengths_m):
            raise ValueError("segment_lengths_m entries must all be positive.")
        normalized_twist_controls = tuple(
            (float(eta), float(twist_deg)) for eta, twist_deg in self.twist_control_points
        )
        if normalized_twist_controls:
            if len(normalized_twist_controls) < 2:
                raise ValueError("twist_control_points must contain at least root and tip controls.")
            if not isclose(normalized_twist_controls[0][0], 0.0, abs_tol=1.0e-9):
                raise ValueError("twist_control_points must start at eta=0.")
            if not isclose(normalized_twist_controls[-1][0], 1.0, abs_tol=1.0e-9):
                raise ValueError("twist_control_points must end at eta=1.")
            if any(
                later_eta <= earlier_eta
                for (earlier_eta, _), (later_eta, _) in zip(
                    normalized_twist_controls,
                    normalized_twist_controls[1:],
                )
            ):
                raise ValueError("twist_control_points eta values must be strictly increasing.")
            if any(eta < 0.0 or eta > 1.0 for eta, _ in normalized_twist_controls):
                raise ValueError("twist_control_points eta values must stay in [0, 1].")
            object.__setattr__(self, "twist_control_points", normalized_twist_controls)

        half_span_m = 0.5 * self.span_m
        if not isclose(sum(self.segment_lengths_m), half_span_m, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("segment_lengths_m must sum to half-span within tolerance.")

        expected_area_m2 = self.span_m * (self.root_chord_m + self.tip_chord_m) / 2.0
        if not isclose(self.wing_area_m2, expected_area_m2, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("trapezoidal wing area is inconsistent with span/root/tip chord.")

    @property
    def taper_ratio(self) -> float:
        return float(self.tip_chord_m / max(self.root_chord_m, 1.0e-9))

    @property
    def aspect_ratio(self) -> float:
        return float(self.span_m**2 / max(self.wing_area_m2, 1.0e-9))

    @property
    def mean_aerodynamic_chord_m(self) -> float:
        taper_ratio = self.taper_ratio
        return float(
            (2.0 / 3.0)
            * self.root_chord_m
            * (1.0 + taper_ratio + taper_ratio**2)
            / max(1.0 + taper_ratio, 1.0e-9)
        )

    @property
    def wing_area_source(self) -> str:
        if self.planform_parameterization == "mean_chord":
            return "derived_from_mean_chord_m"
        return (
            "derived_from_wing_loading_target_Npm2"
            if self.wing_area_is_derived
            else "explicit_planform_input"
        )


@dataclass(frozen=True)
class GeometryRejection:
    sample_index: int
    reason: str
    primary_values: dict[str, float]
    secondary_values: dict[str, float]
    details: dict[str, float | str]


@dataclass(frozen=True)
class GeometryEnumerationDiagnostics:
    sampling_mode: str
    requested_sample_count: int
    accepted_concept_count: int
    rejected_concepts: tuple[GeometryRejection, ...]
    design_gross_mass_kg: float

    @property
    def rejected_concept_count(self) -> int:
        return len(self.rejected_concepts)

    @property
    def rejection_reason_counts(self) -> dict[str, int]:
        return dict(Counter(rejection.reason for rejection in self.rejected_concepts))


_LAST_ENUMERATION_DIAGNOSTICS: GeometryEnumerationDiagnostics | None = None


def _lambda_min_from_tip_chord(*, c_bar_m: float, c_tip_min_m: float) -> float:
    c_bar = float(c_bar_m)
    c_tip_min = float(c_tip_min_m)
    if 2.0 * c_bar <= c_tip_min:
        return float("inf")
    return float(c_tip_min / (2.0 * c_bar - c_tip_min))


def _tip_re_design_speed_mps(cfg) -> float:
    tip_protection = cfg.geometry_family.planform_tip_protection
    if tip_protection.tip_re_design_speed_mps is not None:
        return float(tip_protection.tip_re_design_speed_mps)
    return 0.5 * (
        float(cfg.mission.speed_sweep_min_mps) + float(cfg.mission.speed_sweep_max_mps)
    )


def _planform_tip_required_chord_m(cfg) -> float:
    hard_constraints = cfg.geometry_family.hard_constraints
    tip_protection = cfg.geometry_family.planform_tip_protection
    if not bool(tip_protection.enabled):
        return float(hard_constraints.tip_chord_min_m)

    air_properties = air_properties_from_environment(
        temperature_c=float(cfg.environment.temperature_c),
        relative_humidity_percent=float(cfg.environment.relative_humidity),
        altitude_m=float(cfg.environment.altitude_m),
    )
    design_speed_mps = _tip_re_design_speed_mps(cfg)
    re_based_min_m = (
        float(tip_protection.tip_re_abs_min)
        * float(air_properties.dynamic_viscosity_pa_s)
        / max(float(air_properties.density_kg_per_m3) * design_speed_mps, 1.0e-9)
    )
    spar_based_min_m = float(tip_protection.tip_spar_depth_min_m) / max(
        float(tip_protection.tip_structural_tc_ratio),
        1.0e-9,
    )
    return max(
        float(hard_constraints.tip_chord_min_m),
        float(tip_protection.tip_chord_abs_min_m),
        re_based_min_m,
        spar_based_min_m,
    )


def _linear_chord_at_eta(concept: GeometryConcept, eta: float) -> float:
    eta_clamped = min(max(float(eta), 0.0), 1.0)
    return float(
        concept.root_chord_m
        + eta_clamped * (float(concept.tip_chord_m) - float(concept.root_chord_m))
    )


def _outer_loading_ratio_to_ellipse(*, spanload_bias: float, eta: float) -> float:
    return max(0.0, 1.0 - float(spanload_bias) * float(eta) ** 2)


def _fourier_spanload_ratio_to_ellipse(
    *,
    a3_over_a1: float,
    a5_over_a1: float,
    eta: float,
) -> float:
    eta_clamped = min(max(float(eta), 0.0), 1.0)
    eta2 = eta_clamped**2
    eta4 = eta2**2
    sin3_over_sin1 = 4.0 * eta2 - 1.0
    sin5_over_sin1 = 1.0 - 12.0 * eta2 + 16.0 * eta4
    return float(
        1.0
        + float(a3_over_a1) * sin3_over_sin1
        + float(a5_over_a1) * sin5_over_sin1
    )


def _fourier_spanload_shape(
    *,
    a3_over_a1: float,
    a5_over_a1: float,
    eta: float,
) -> float:
    eta_clamped = min(max(float(eta), 0.0), 1.0)
    elliptic = math.sqrt(max(1.0 - eta_clamped**2, 0.0))
    return float(
        elliptic
        * _fourier_spanload_ratio_to_ellipse(
            a3_over_a1=float(a3_over_a1),
            a5_over_a1=float(a5_over_a1),
            eta=eta_clamped,
        )
    )


def _progressive_schedule_value(
    start_value: float,
    end_value: float,
    frac: float,
    exponent: float,
) -> float:
    return start_value + (frac**exponent) * (end_value - start_value)


def _sample_unit_hypercube(
    *,
    mode: str,
    sample_count: int,
    seed: int,
    scramble: bool,
    dimensions: int,
) -> np.ndarray:
    if dimensions <= 0:
        raise ValueError("dimensions must be positive.")
    if mode == "latin_hypercube":
        return qmc.LatinHypercube(d=dimensions, seed=seed, scramble=scramble).random(sample_count)
    if mode == "sobol":
        return qmc.Sobol(d=dimensions, seed=seed, scramble=scramble).random(sample_count)
    if mode == "uniform_random":
        return np.random.default_rng(seed).random((sample_count, dimensions))
    if mode == "linspace_grid":
        samples_per_axis = max(1, int(round(sample_count ** (1.0 / float(dimensions)))))
        axis = np.linspace(0.0, 1.0, samples_per_axis)
        grid = np.asarray(tuple(product(axis, repeat=dimensions)), dtype=float)
        if grid.shape[0] == sample_count:
            return grid
        rng = np.random.default_rng(seed)
        if grid.shape[0] > sample_count:
            order = rng.permutation(grid.shape[0])[:sample_count]
            return grid[order]
        rows = []
        while len(rows) < sample_count:
            order = rng.permutation(grid.shape[0])
            rows.extend(grid[order].tolist())
        return np.asarray(rows[:sample_count], dtype=float)
    raise ValueError(f"Unsupported sampling mode: {mode}")


def _primary_variable_specs(cfg) -> tuple[tuple[str, object], ...]:
    ranges = cfg.geometry_family.primary_ranges
    planform_key = (
        "mean_chord_m"
        if str(cfg.geometry_family.planform_parameterization) == "mean_chord"
        else "wing_loading_target_Npm2"
    )
    planform_range = (
        ranges.mean_chord_m
        if str(cfg.geometry_family.planform_parameterization) == "mean_chord"
        else ranges.wing_loading_target_Npm2
    )
    return (
        ("span_m", ranges.span_m),
        (planform_key, planform_range),
        ("taper_ratio", ranges.taper_ratio),
        ("twist_mid_deg", ranges.twist_mid_deg),
        ("twist_outer_deg", ranges.twist_outer_deg),
        ("tip_twist_deg", ranges.tip_twist_deg),
        ("spanload_bias", ranges.spanload_bias),
    )


def _sample_primary_variables(cfg) -> tuple[dict[str, float], ...]:
    sampling = cfg.geometry_family.sampling
    variable_specs = _primary_variable_specs(cfg)
    unit_samples = _sample_unit_hypercube(
        mode=str(sampling.mode),
        sample_count=int(sampling.sample_count),
        seed=int(sampling.seed),
        scramble=bool(sampling.scramble),
        dimensions=len(variable_specs),
    )

    def _scale(range_cfg, unit_value: float) -> float:
        return float(range_cfg.min + unit_value * (range_cfg.max - range_cfg.min))

    return tuple(
        {
            variable_name: _scale(range_cfg, float(row[index]))
            for index, (variable_name, range_cfg) in enumerate(variable_specs)
        }
        for row in unit_samples
    )


def _sample_secondary_design_variables(cfg, count: int) -> tuple[tuple[float, float, float, float], ...]:
    tail_sizing_mode = str(getattr(cfg.geometry_family, "tail_sizing_mode", "fixed_area"))
    tail_candidates = (
        cfg.geometry_family.tail_volume_coefficient_candidates
        if tail_sizing_mode == "tail_volume"
        else cfg.geometry_family.tail_area_candidates_m2
    )
    base_combos = tuple(
        product(
            tail_candidates,
            cfg.geometry_family.dihedral_root_deg_candidates,
            cfg.geometry_family.dihedral_tip_deg_candidates,
            cfg.geometry_family.dihedral_exponent_candidates,
        )
    )
    if not base_combos:
        return ()

    rng = np.random.default_rng(int(cfg.geometry_family.sampling.seed) + 1)
    sampled: list[tuple[float, float, float, float]] = []
    while len(sampled) < count:
        order = list(base_combos)
        rng.shuffle(order)
        sampled.extend(order)
    return tuple(sampled[:count])


def _apply_spanload_bias_washout(
    *,
    twist_control_points: tuple[tuple[float, float], ...],
    spanload_bias: float,
    washout_gain_deg: float,
) -> tuple[tuple[float, float], ...]:
    if spanload_bias <= 0.0 or washout_gain_deg <= 0.0:
        return twist_control_points
    return tuple(
        (
            float(eta),
            float(twist_deg) - float(washout_gain_deg) * float(spanload_bias) * float(eta) ** 2,
        )
        for eta, twist_deg in twist_control_points
    )


def _geometry_rejection(
    *,
    sample_index: int,
    reason: str,
    primary_values: dict[str, float],
    secondary_values: dict[str, float],
    **details: float | str,
) -> GeometryRejection:
    return GeometryRejection(
        sample_index=sample_index,
        reason=reason,
        primary_values={key: float(value) for key, value in primary_values.items()},
        secondary_values={key: float(value) for key, value in secondary_values.items()},
        details=details,
    )


def _spanload_design_rejection(
    *,
    cfg,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    sample_index: int,
    primary_values: dict[str, float],
    secondary_values: dict[str, float],
) -> GeometryRejection | None:
    spanload_cfg = cfg.geometry_family.spanload_design
    if not bool(spanload_cfg.enabled):
        return None

    a3 = float(spanload_cfg.a3_over_a1)
    a5 = float(spanload_cfg.a5_over_a1)
    for eta, max_ratio in (
        (0.90, float(spanload_cfg.outer_loading_eta_0p90_max_ratio_to_ellipse)),
        (0.95, float(spanload_cfg.outer_loading_eta_0p95_max_ratio_to_ellipse)),
    ):
        ratio = _fourier_spanload_ratio_to_ellipse(
            a3_over_a1=a3,
            a5_over_a1=a5,
            eta=eta,
        )
        if ratio > max_ratio:
            return _geometry_rejection(
                sample_index=sample_index,
                reason="spanload_design_outer_loading_above_max",
                primary_values=primary_values,
                secondary_values=secondary_values,
                spanload_a3_over_a1=a3,
                spanload_a5_over_a1=a5,
                outer_loading_eta=float(eta),
                outer_loading_ratio_to_ellipse=float(ratio),
                outer_loading_max_ratio_to_ellipse=float(max_ratio),
            )

    air_properties = air_properties_from_environment(
        temperature_c=float(cfg.environment.temperature_c),
        relative_humidity_percent=float(cfg.environment.relative_humidity),
        altitude_m=float(cfg.environment.altitude_m),
    )
    design_speed_mps = (
        float(spanload_cfg.design_speed_mps)
        if spanload_cfg.design_speed_mps is not None
        else _tip_re_design_speed_mps(cfg)
    )
    dynamic_pressure_pa = (
        0.5 * float(air_properties.density_kg_per_m3) * design_speed_mps**2
    )
    design_cl = (
        float(cfg.mass.design_gross_mass_kg)
        * 9.80665
        / max(dynamic_pressure_pa * float(concept.wing_area_m2), 1.0e-9)
    )
    half_span_m = 0.5 * float(concept.span_m)
    station_records: list[dict[str, float]] = []
    target_etas = {
        float(value)
        for value in np.linspace(0.0, 1.0, int(spanload_cfg.target_station_count))
    }
    target_etas.update(
        0.0 if half_span_m <= 0.0 else float(station.y_m) / half_span_m
        for station in stations
    )
    for eta in sorted(min(max(float(value), 0.0), 1.0) for value in target_etas):
        shape = _fourier_spanload_shape(
            a3_over_a1=a3,
            a5_over_a1=a5,
            eta=eta,
        )
        if bool(spanload_cfg.require_positive_circulation) and eta < 0.999 and shape <= 0.0:
            return _geometry_rejection(
                sample_index=sample_index,
                reason="spanload_design_nonpositive_circulation",
                primary_values=primary_values,
                secondary_values=secondary_values,
                spanload_a3_over_a1=a3,
                spanload_a5_over_a1=a5,
                eta=float(eta),
                target_circulation_shape=float(shape),
            )
        station_records.append(
            {
                "eta": float(eta),
                "y_m": float(eta * half_span_m),
                "chord_m": _linear_chord_at_eta(concept, eta),
                "shape": float(shape),
            }
        )
    if len(station_records) < 2:
        return None

    shape_integral_m = 0.0
    for left, right in zip(station_records, station_records[1:]):
        dy_m = float(right["y_m"] - left["y_m"])
        shape_integral_m += 0.5 * dy_m * (
            float(left["shape"]) + float(right["shape"])
        )
    if shape_integral_m <= 0.0:
        return _geometry_rejection(
            sample_index=sample_index,
            reason="spanload_design_nonpositive_integrated_circulation",
            primary_values=primary_values,
            secondary_values=secondary_values,
            spanload_a3_over_a1=a3,
            spanload_a5_over_a1=a5,
            target_circulation_integral_m=float(shape_integral_m),
        )

    cl_scale = design_cl * float(concept.wing_area_m2) / max(
        2.0 * shape_integral_m,
        1.0e-9,
    )
    safe_clmax = float(spanload_cfg.local_clmax_safe_floor)
    worst_utilization = -1.0
    worst_eta = 0.0
    worst_local_cl = 0.0
    worst_outer_utilization = -1.0
    worst_outer_eta = 0.0
    worst_outer_local_cl = 0.0
    for record in station_records:
        local_cl = cl_scale * float(record["shape"]) / max(
            float(record["chord_m"]),
            1.0e-9,
        )
        utilization = local_cl / max(safe_clmax, 1.0e-9)
        if utilization > worst_utilization:
            worst_utilization = float(utilization)
            worst_eta = float(record["eta"])
            worst_local_cl = float(local_cl)
        if float(record["eta"]) >= float(spanload_cfg.outer_eta_start):
            if utilization > worst_outer_utilization:
                worst_outer_utilization = float(utilization)
                worst_outer_eta = float(record["eta"])
                worst_outer_local_cl = float(local_cl)

    if worst_utilization > float(spanload_cfg.local_clmax_utilization_max):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="spanload_design_local_clmax_utilization_exceeded",
            primary_values=primary_values,
            secondary_values=secondary_values,
            spanload_a3_over_a1=a3,
            spanload_a5_over_a1=a5,
            design_cl=float(design_cl),
            worst_eta=float(worst_eta),
            worst_local_cl=float(worst_local_cl),
            local_clmax_safe_floor=safe_clmax,
            local_clmax_utilization=float(worst_utilization),
            local_clmax_utilization_max=float(spanload_cfg.local_clmax_utilization_max),
        )
    if worst_outer_utilization > float(spanload_cfg.outer_cruise_clmax_utilization_max):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="spanload_design_outer_clmax_utilization_exceeded",
            primary_values=primary_values,
            secondary_values=secondary_values,
            spanload_a3_over_a1=a3,
            spanload_a5_over_a1=a5,
            design_cl=float(design_cl),
            worst_outer_eta=float(worst_outer_eta),
            worst_outer_local_cl=float(worst_outer_local_cl),
            local_clmax_safe_floor=safe_clmax,
            outer_clmax_utilization=float(worst_outer_utilization),
            outer_clmax_utilization_max=float(
                spanload_cfg.outer_cruise_clmax_utilization_max
            ),
        )

    tip_protection = cfg.geometry_family.planform_tip_protection
    if bool(tip_protection.enabled):
        aerodynamic_tip_eta = float(tip_protection.aerodynamic_tip_station_eta)
        tip_chord_m = _linear_chord_at_eta(concept, aerodynamic_tip_eta)
        tip_re = (
            float(air_properties.density_kg_per_m3)
            * design_speed_mps
            * tip_chord_m
            / max(float(air_properties.dynamic_viscosity_pa_s), 1.0e-12)
        )
        if tip_re < float(tip_protection.tip_re_abs_min):
            return _geometry_rejection(
                sample_index=sample_index,
                reason="spanload_design_tip_re_below_min",
                primary_values=primary_values,
                secondary_values=secondary_values,
                aerodynamic_tip_station_eta=aerodynamic_tip_eta,
                chord_at_aerodynamic_tip_eta_m=float(tip_chord_m),
                tip_re=float(tip_re),
                tip_re_abs_min=float(tip_protection.tip_re_abs_min),
                design_speed_mps=float(design_speed_mps),
            )
    return None


def _evaluate_hard_constraints(
    *,
    cfg,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    sample_index: int,
    primary_values: dict[str, float],
    secondary_values: dict[str, float],
) -> GeometryRejection | None:
    constraints = cfg.geometry_family.hard_constraints
    if concept.wing_area_m2 < float(constraints.wing_area_m2_range.min):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="wing_area_below_min",
            primary_values=primary_values,
            secondary_values=secondary_values,
            wing_area_m2=float(concept.wing_area_m2),
            wing_area_min_m2=float(constraints.wing_area_m2_range.min),
        )
    if concept.wing_area_m2 > float(constraints.wing_area_m2_range.max):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="wing_area_above_max",
            primary_values=primary_values,
            secondary_values=secondary_values,
            wing_area_m2=float(concept.wing_area_m2),
            wing_area_max_m2=float(constraints.wing_area_m2_range.max),
        )
    if concept.aspect_ratio < float(constraints.aspect_ratio_range.min):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="aspect_ratio_below_min",
            primary_values=primary_values,
            secondary_values=secondary_values,
            aspect_ratio=float(concept.aspect_ratio),
            aspect_ratio_min=float(constraints.aspect_ratio_range.min),
        )
    if concept.aspect_ratio > float(constraints.aspect_ratio_range.max):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="aspect_ratio_above_max",
            primary_values=primary_values,
            secondary_values=secondary_values,
            aspect_ratio=float(concept.aspect_ratio),
            aspect_ratio_max=float(constraints.aspect_ratio_range.max),
        )
    if concept.root_chord_m < float(constraints.root_chord_min_m):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="root_chord_below_min",
            primary_values=primary_values,
            secondary_values=secondary_values,
            root_chord_m=float(concept.root_chord_m),
            root_chord_min_m=float(constraints.root_chord_min_m),
        )
    tip_protection = cfg.geometry_family.planform_tip_protection
    required_tip_chord_m = _planform_tip_required_chord_m(cfg)
    tolerance_m = 1.0e-9
    if concept.tip_chord_m + tolerance_m < required_tip_chord_m:
        return _geometry_rejection(
            sample_index=sample_index,
            reason="tip_chord_below_min",
            primary_values=primary_values,
            secondary_values=secondary_values,
            tip_chord_m=float(concept.tip_chord_m),
            tip_chord_min_m=float(required_tip_chord_m),
        )
    if bool(tip_protection.enabled):
        aerodynamic_tip_eta = float(tip_protection.aerodynamic_tip_station_eta)
        chord_at_aero_tip_m = _linear_chord_at_eta(concept, aerodynamic_tip_eta)
        chord_at_aero_tip_min_m = float(
            tip_protection.require_chord_at_eta_0p95_min_m
        )
        if chord_at_aero_tip_m + tolerance_m < chord_at_aero_tip_min_m:
            return _geometry_rejection(
                sample_index=sample_index,
                reason="aerodynamic_tip_chord_below_min",
                primary_values=primary_values,
                secondary_values=secondary_values,
                aerodynamic_tip_station_eta=aerodynamic_tip_eta,
                chord_at_aerodynamic_tip_eta_m=float(chord_at_aero_tip_m),
                chord_at_aerodynamic_tip_eta_min_m=chord_at_aero_tip_min_m,
            )

        tip_spar_depth_m = float(concept.tip_chord_m) * float(
            tip_protection.tip_structural_tc_ratio
        )
        if tip_spar_depth_m + tolerance_m < float(tip_protection.tip_spar_depth_min_m):
            return _geometry_rejection(
                sample_index=sample_index,
                reason="tip_spar_depth_insufficient",
                primary_values=primary_values,
                secondary_values=secondary_values,
                tip_spar_depth_m=float(tip_spar_depth_m),
                tip_spar_depth_min_m=float(tip_protection.tip_spar_depth_min_m),
                tip_structural_tc_ratio=float(tip_protection.tip_structural_tc_ratio),
            )

        outer_loading_checks = (
            (
                0.90,
                float(tip_protection.outer_loading_eta_0p90_max_ratio_to_ellipse),
            ),
            (
                0.95,
                float(tip_protection.outer_loading_eta_0p95_max_ratio_to_ellipse),
            ),
        )
        for eta, max_ratio in outer_loading_checks:
            ratio = _outer_loading_ratio_to_ellipse(
                spanload_bias=float(concept.spanload_bias),
                eta=eta,
            )
            if ratio > max_ratio:
                return _geometry_rejection(
                    sample_index=sample_index,
                    reason="outer_loading_ratio_above_max",
                    primary_values=primary_values,
                    secondary_values=secondary_values,
                    spanload_bias=float(concept.spanload_bias),
                    outer_loading_eta=float(eta),
                    outer_loading_ratio_to_ellipse=float(ratio),
                    outer_loading_max_ratio_to_ellipse=float(max_ratio),
                )

    spanload_rejection = _spanload_design_rejection(
        cfg=cfg,
        concept=concept,
        stations=stations,
        sample_index=sample_index,
        primary_values=primary_values,
        secondary_values=secondary_values,
    )
    if spanload_rejection is not None:
        return spanload_rejection

    root_available_spar_depth_m = (
        float(concept.root_chord_m)
        * float(constraints.root_zone_min_tc_ratio)
        * float(constraints.root_zone_spar_depth_fraction)
    )
    if root_available_spar_depth_m < float(constraints.root_zone_required_spar_depth_m):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="root_zone_spar_depth_insufficient",
            primary_values=primary_values,
            secondary_values=secondary_values,
            available_spar_depth_m=float(root_available_spar_depth_m),
            required_spar_depth_m=float(constraints.root_zone_required_spar_depth_m),
        )

    minimum_station_chord_m = min(float(station.chord_m) for station in stations)
    if minimum_station_chord_m + tolerance_m < float(constraints.segment_min_chord_m):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="segment_chord_below_min",
            primary_values=primary_values,
            secondary_values=secondary_values,
            minimum_station_chord_m=float(minimum_station_chord_m),
            segment_min_chord_m=float(constraints.segment_min_chord_m),
        )
    return None


def build_segment_plan(
    *,
    half_span_m: float,
    min_segment_length_m: float,
    max_segment_length_m: float,
) -> tuple[float, ...]:
    if half_span_m <= 0.0:
        raise ValueError("half_span_m must be positive.")
    if min_segment_length_m <= 0.0:
        raise ValueError("min_segment_length_m must be positive.")
    if max_segment_length_m < min_segment_length_m:
        raise ValueError("max_segment_length_m must be >= min_segment_length_m.")

    segment_count = max(1, int(-(-half_span_m // max_segment_length_m)))
    segment_length = half_span_m / float(segment_count)
    if segment_length < min_segment_length_m:
        raise ValueError("half_span_m cannot be segmented within the configured bounds.")

    return tuple(float(segment_length) for _ in range(segment_count))


def _twist_at_span_fraction(concept: GeometryConcept, frac: float) -> float:
    frac = min(max(float(frac), 0.0), 1.0)
    controls = concept.twist_control_points
    if not controls:
        return float(
            concept.twist_root_deg
            + frac * (concept.twist_tip_deg - concept.twist_root_deg)
        )
    if frac <= controls[0][0]:
        return float(controls[0][1])
    for (left_eta, left_twist), (right_eta, right_twist) in zip(
        controls,
        controls[1:],
    ):
        if frac <= right_eta:
            local_frac = (frac - left_eta) / max(right_eta - left_eta, 1.0e-9)
            return float(left_twist + local_frac * (right_twist - left_twist))
    return float(controls[-1][1])


def build_linear_wing_stations(
    concept: GeometryConcept,
    *,
    stations_per_half: int,
) -> tuple[WingStation, ...]:
    segment_count = len(concept.segment_lengths_m)
    boundary_count = segment_count + 1
    if stations_per_half < boundary_count:
        raise ValueError(
            "stations_per_half must be at least len(concept.segment_lengths_m) + 1."
        )

    half_span_m = 0.5 * concept.span_m
    boundaries = [0.0]
    for segment_length in concept.segment_lengths_m:
        boundaries.append(boundaries[-1] + float(segment_length))

    if stations_per_half == boundary_count:
        y_locations = tuple(boundaries)
    else:
        extra_points = stations_per_half - boundary_count
        total_length = sum(concept.segment_lengths_m)
        ideal_shares = [
            extra_points * (segment_length / total_length)
            for segment_length in concept.segment_lengths_m
        ]
        per_segment_interior_points = [int(floor(share)) for share in ideal_shares]
        remaining_points = extra_points - sum(per_segment_interior_points)
        fractional_order = sorted(
            range(segment_count),
            key=lambda index: (
                -(ideal_shares[index] - per_segment_interior_points[index]),
                -concept.segment_lengths_m[index],
                index,
            ),
        )
        for index in fractional_order[:remaining_points]:
            per_segment_interior_points[index] += 1

        y_locations: list[float] = [boundaries[0]]
        for segment_index, (start_y_m, end_y_m) in enumerate(zip(boundaries, boundaries[1:])):
            interior_count = per_segment_interior_points[segment_index]
            segment_length_m = end_y_m - start_y_m
            for interior_index in range(1, interior_count + 1):
                frac = interior_index / float(interior_count + 1)
                y_locations.append(start_y_m + frac * segment_length_m)
            y_locations.append(end_y_m)
        y_locations = tuple(y_locations)

    stations: list[WingStation] = []
    for y_m in y_locations:
        frac = 0.0 if half_span_m == 0.0 else y_m / half_span_m
        chord_m = concept.root_chord_m + frac * (concept.tip_chord_m - concept.root_chord_m)
        twist_deg = _twist_at_span_fraction(concept, frac)
        dihedral_deg = _progressive_schedule_value(
            concept.dihedral_root_deg,
            concept.dihedral_tip_deg,
            frac,
            concept.dihedral_exponent,
        )
        stations.append(
            WingStation(y_m=y_m, chord_m=chord_m, twist_deg=twist_deg, dihedral_deg=dihedral_deg)
        )
    return tuple(stations)


def enumerate_geometry_concepts(cfg) -> tuple[GeometryConcept, ...]:
    global _LAST_ENUMERATION_DIAGNOSTICS

    accepted_concepts: list[GeometryConcept] = []
    rejected_concepts: list[GeometryRejection] = []
    primary_samples = _sample_primary_variables(cfg)
    secondary_samples = _sample_secondary_design_variables(cfg, len(primary_samples))

    for sample_index, (primary_values, secondary_values_tuple) in enumerate(
        zip(primary_samples, secondary_samples, strict=True),
        start=1,
    ):
        primary_values = dict(primary_values)
        span_m = float(primary_values["span_m"])
        planform_parameterization = str(cfg.geometry_family.planform_parameterization)
        taper_ratio = float(primary_values["taper_ratio"])
        twist_mid_deg = float(primary_values["twist_mid_deg"])
        twist_outer_deg = float(primary_values["twist_outer_deg"])
        tip_twist_deg = float(primary_values["tip_twist_deg"])
        spanload_bias = float(primary_values["spanload_bias"])
        (
            tail_design_value,
            dihedral_root_deg,
            dihedral_tip_deg,
            dihedral_exponent,
        ) = secondary_values_tuple
        tail_sizing_mode = str(cfg.geometry_family.tail_sizing_mode)
        tail_design_key = (
            "tail_volume_coefficient"
            if tail_sizing_mode == "tail_volume"
            else "tail_area_m2"
        )
        secondary_values = {
            tail_design_key: float(tail_design_value),
            "dihedral_root_deg": float(dihedral_root_deg),
            "dihedral_tip_deg": float(dihedral_tip_deg),
            "dihedral_exponent": float(dihedral_exponent),
        }
        twist_mid_eta, twist_outer_eta = (
            float(value) for value in cfg.geometry_family.twist_control_etas
        )
        twist_control_points = (
            (0.0, float(cfg.geometry_family.twist_root_deg)),
            (twist_mid_eta, twist_mid_deg),
            (twist_outer_eta, twist_outer_deg),
            (1.0, tip_twist_deg),
        )
        twist_control_points = _apply_spanload_bias_washout(
            twist_control_points=twist_control_points,
            spanload_bias=spanload_bias,
            washout_gain_deg=float(cfg.geometry_family.spanload_bias_washout_gain_deg),
        )
        if any(
            later_twist > earlier_twist
            for (_, earlier_twist), (_, later_twist) in zip(
                twist_control_points,
                twist_control_points[1:],
            )
        ):
            rejected_concepts.append(
                _geometry_rejection(
                    sample_index=sample_index,
                    reason="twist_schedule_not_monotone_washout",
                    primary_values=primary_values,
                    secondary_values=secondary_values,
                    twist_root_deg=float(cfg.geometry_family.twist_root_deg),
                    twist_mid_deg=twist_mid_deg,
                    twist_outer_deg=twist_outer_deg,
                    tip_twist_deg=tip_twist_deg,
                )
            )
            continue

        mean_chord_target_m: float | None = None
        if planform_parameterization == "mean_chord":
            mean_chord_target_m = float(primary_values["mean_chord_m"])
            initial_wing_area_m2 = float(span_m * mean_chord_target_m)
            wing_loading_target_Npm2 = float(
                cfg.design_gross_weight_n / max(initial_wing_area_m2, 1.0e-9)
            )
        else:
            wing_loading_target_Npm2 = float(primary_values["wing_loading_target_Npm2"])
            initial_wing_area_m2 = float(
                cfg.design_gross_weight_n / max(wing_loading_target_Npm2, 1.0e-9)
            )
        wing_area_m2 = initial_wing_area_m2
        design_gross_mass_kg = float(cfg.mass.design_gross_mass_kg)

        tip_protection = cfg.geometry_family.planform_tip_protection
        if bool(tip_protection.enabled) and bool(
            tip_protection.dynamic_lambda_min_from_tip_chord
        ):
            c_bar_m = float(wing_area_m2) / max(float(span_m), 1.0e-9)
            required_tip_chord_m = _planform_tip_required_chord_m(cfg)
            dynamic_lambda_min = _lambda_min_from_tip_chord(
                c_bar_m=c_bar_m,
                c_tip_min_m=required_tip_chord_m,
            )
            if not math.isfinite(dynamic_lambda_min):
                rejected_concepts.append(
                    _geometry_rejection(
                        sample_index=sample_index,
                        reason="tip_dynamic_lambda_infeasible",
                        primary_values=primary_values,
                        secondary_values=secondary_values,
                        mean_chord_m=float(c_bar_m),
                        tip_chord_min_m=float(required_tip_chord_m),
                    )
                )
                continue
            if taper_ratio < dynamic_lambda_min:
                primary_values["sampled_taper_ratio"] = float(taper_ratio)
                primary_values["dynamic_lambda_min_from_tip_chord"] = float(
                    dynamic_lambda_min
                )
                primary_values["tip_chord_min_governing_m"] = float(
                    required_tip_chord_m
                )
                taper_ratio = float(dynamic_lambda_min)
                primary_values["taper_ratio"] = float(taper_ratio)

        tail_volume_coefficient: float | None = None
        if tail_sizing_mode == "tail_volume":
            tail_volume_coefficient = float(tail_design_value)
            tail_area_m2 = (
                tail_volume_coefficient
                * float(wing_area_m2)
                / float(cfg.tail_model.tail_arm_to_mac)
            )
            tail_area_source = "derived_from_tail_volume_coefficient"
            secondary_values["tail_area_m2"] = float(tail_area_m2)
        else:
            tail_area_m2 = float(tail_design_value)
            tail_area_source = "fixed_area_candidate"
            secondary_values["tail_volume_coefficient"] = None

        jig_gate_cfg = getattr(cfg, "jig_shape_gate", None)
        accepted_tip_deflection_ratio: float | None = None
        accepted_tip_deflection_m: float | None = None
        accepted_effective_dihedral_deg: float | None = None
        accepted_unbraced_tip_deflection_m: float | None = None
        accepted_lift_wire_relief_deflection_m: float | None = None
        accepted_tip_deflection_preferred_status: str | None = None
        if jig_gate_cfg is not None and bool(jig_gate_cfg.enabled):
            tube_geom = getattr(cfg.mass_closure, "tube_system", None)
            if tube_geom is not None:
                deflection_estimate = estimate_tip_deflection(
                    gross_mass_kg=design_gross_mass_kg,
                    span_m=span_m,
                    tube_geom=tube_geom,
                    gate_cfg=jig_gate_cfg,
                )
                deflection_ratio = float(deflection_estimate.tip_deflection_ratio)
                limit_ratio = float(jig_gate_cfg.max_tip_deflection_to_halfspan_ratio)
                if deflection_ratio > limit_ratio:
                    rejected_concepts.append(
                        _geometry_rejection(
                            sample_index=sample_index,
                            reason="jig_shape_deflection_excessive",
                            primary_values=primary_values,
                            secondary_values=secondary_values,
                            tip_deflection_ratio=float(deflection_ratio),
                            tip_deflection_ratio_limit=float(limit_ratio),
                            design_gross_mass_kg=float(design_gross_mass_kg),
                        )
                    )
                    continue
                accepted_tip_deflection_ratio = float(deflection_ratio)
                accepted_tip_deflection_m = float(deflection_estimate.tip_deflection_m)
                accepted_effective_dihedral_deg = float(
                    deflection_estimate.effective_dihedral_deg
                )
                accepted_unbraced_tip_deflection_m = float(
                    deflection_estimate.unbraced_tip_deflection_m
                )
                accepted_lift_wire_relief_deflection_m = float(
                    deflection_estimate.lift_wire_relief_deflection_m
                )
                min_preferred_deflection_m = float(
                    jig_gate_cfg.preferred_tip_deflection_m_min
                )
                max_preferred_deflection_m = float(
                    jig_gate_cfg.preferred_tip_deflection_m_max
                )
                if accepted_tip_deflection_m < min_preferred_deflection_m:
                    accepted_tip_deflection_preferred_status = "below_preferred"
                elif accepted_tip_deflection_m > max_preferred_deflection_m:
                    accepted_tip_deflection_preferred_status = "above_preferred"
                else:
                    accepted_tip_deflection_preferred_status = "within_preferred"

        wire_gate_cfg = getattr(cfg, "lift_wire_gate", None)
        accepted_lift_wire_tension_n: float | None = None
        if wire_gate_cfg is not None and bool(wire_gate_cfg.enabled):
            tube_geom = getattr(cfg.mass_closure, "tube_system", None)
            if tube_geom is not None:
                wire_tension_n = estimate_lift_wire_tension_n(
                    gross_mass_kg=design_gross_mass_kg,
                    tube_geom=tube_geom,
                    gate_cfg=wire_gate_cfg,
                )
                allowable_n = float(wire_gate_cfg.allowable_tension_n)
                if wire_tension_n > allowable_n:
                    rejected_concepts.append(
                        _geometry_rejection(
                            sample_index=sample_index,
                            reason="lift_wire_tension_excessive",
                            primary_values=primary_values,
                            secondary_values=secondary_values,
                            estimated_wire_tension_n=float(wire_tension_n),
                            allowable_tension_n=allowable_n,
                            design_gross_mass_kg=float(design_gross_mass_kg),
                        )
                    )
                    continue
                accepted_lift_wire_tension_n = float(wire_tension_n)

        root_chord_m = 2.0 * wing_area_m2 / (span_m * (1.0 + taper_ratio))
        tip_chord_m = root_chord_m * taper_ratio

        try:
            segment_lengths_m = build_segment_plan(
                half_span_m=0.5 * span_m,
                min_segment_length_m=cfg.segmentation.min_segment_length_m,
                max_segment_length_m=cfg.segmentation.max_segment_length_m,
            )
        except ValueError as exc:
            rejected_concepts.append(
                _geometry_rejection(
                    sample_index=sample_index,
                    reason="segment_plan_infeasible",
                    primary_values=primary_values,
                    secondary_values=secondary_values,
                    error=str(exc),
                )
            )
            continue

        concept = GeometryConcept(
            span_m=float(span_m),
            wing_area_m2=float(wing_area_m2),
            root_chord_m=float(root_chord_m),
            tip_chord_m=float(tip_chord_m),
            twist_root_deg=float(cfg.geometry_family.twist_root_deg),
            twist_tip_deg=float(twist_control_points[-1][1]),
            twist_control_points=twist_control_points,
            spanload_bias=float(spanload_bias),
            spanload_a3_over_a1=float(cfg.geometry_family.spanload_design.a3_over_a1),
            spanload_a5_over_a1=float(cfg.geometry_family.spanload_design.a5_over_a1),
            dihedral_root_deg=float(dihedral_root_deg),
            dihedral_tip_deg=float(dihedral_tip_deg),
            dihedral_exponent=float(dihedral_exponent),
            tail_area_m2=float(tail_area_m2),
            tail_area_source=tail_area_source,
            tail_volume_coefficient=tail_volume_coefficient,
            cg_xc=float(cfg.geometry_family.cg_xc),
            segment_lengths_m=segment_lengths_m,
            wing_loading_target_Npm2=float(wing_loading_target_Npm2),
            mean_chord_target_m=mean_chord_target_m,
            wing_area_is_derived=True,
            planform_parameterization=planform_parameterization,
            design_gross_mass_kg=float(design_gross_mass_kg),
            tip_deflection_ratio_at_design_mass=accepted_tip_deflection_ratio,
            tip_deflection_m_at_design_mass=accepted_tip_deflection_m,
            effective_dihedral_deg_at_design_mass=accepted_effective_dihedral_deg,
            unbraced_tip_deflection_m_at_design_mass=accepted_unbraced_tip_deflection_m,
            lift_wire_relief_deflection_m_at_design_mass=accepted_lift_wire_relief_deflection_m,
            tip_deflection_preferred_status=accepted_tip_deflection_preferred_status,
            lift_wire_tension_at_limit_n=accepted_lift_wire_tension_n,
        )
        stations = build_linear_wing_stations(
            concept,
            stations_per_half=cfg.pipeline.stations_per_half,
        )
        rejection = _evaluate_hard_constraints(
            cfg=cfg,
            concept=concept,
            stations=stations,
            sample_index=sample_index,
            primary_values=primary_values,
            secondary_values=secondary_values,
        )
        if rejection is not None:
            rejected_concepts.append(rejection)
            continue
        accepted_concepts.append(concept)

    _LAST_ENUMERATION_DIAGNOSTICS = GeometryEnumerationDiagnostics(
        sampling_mode=str(cfg.geometry_family.sampling.mode),
        requested_sample_count=int(cfg.geometry_family.sampling.sample_count),
        accepted_concept_count=len(accepted_concepts),
        rejected_concepts=tuple(rejected_concepts),
        design_gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
    )
    return tuple(accepted_concepts)


def get_last_geometry_enumeration_diagnostics() -> GeometryEnumerationDiagnostics | None:
    return _LAST_ENUMERATION_DIAGNOSTICS
