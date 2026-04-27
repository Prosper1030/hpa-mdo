from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import floor, isclose
from itertools import product

import numpy as np
from scipy.stats import qmc

from hpa_mdo.concept.mass_closure import close_area_mass, estimate_tube_system_mass_kg


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
    wing_loading_target_Npm2: float | None = None
    wing_area_is_derived: bool = False
    design_gross_mass_kg: float | None = None
    dihedral_root_deg: float = 0.0
    dihedral_tip_deg: float = 0.0
    dihedral_exponent: float = 1.0

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
        if self.wing_loading_target_Npm2 is not None and self.wing_loading_target_Npm2 <= 0.0:
            raise ValueError("wing_loading_target_Npm2 must be positive when provided.")
        if self.design_gross_mass_kg is not None and self.design_gross_mass_kg <= 0.0:
            raise ValueError("design_gross_mass_kg must be positive when provided.")
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
) -> np.ndarray:
    if mode == "latin_hypercube":
        return qmc.LatinHypercube(d=4, seed=seed, scramble=scramble).random(sample_count)
    if mode == "sobol":
        return qmc.Sobol(d=4, seed=seed, scramble=scramble).random(sample_count)
    if mode == "uniform_random":
        return np.random.default_rng(seed).random((sample_count, 4))
    if mode == "linspace_grid":
        samples_per_axis = max(1, int(round(sample_count ** 0.25)))
        axis = np.linspace(0.0, 1.0, samples_per_axis)
        grid = np.asarray(tuple(product(axis, repeat=4)), dtype=float)
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


def _sample_primary_variables(cfg) -> tuple[dict[str, float], ...]:
    sampling = cfg.geometry_family.sampling
    ranges = cfg.geometry_family.primary_ranges
    unit_samples = _sample_unit_hypercube(
        mode=str(sampling.mode),
        sample_count=int(sampling.sample_count),
        seed=int(sampling.seed),
        scramble=bool(sampling.scramble),
    )

    def _scale(range_cfg, unit_value: float) -> float:
        return float(range_cfg.min + unit_value * (range_cfg.max - range_cfg.min))

    return tuple(
        {
            "span_m": _scale(ranges.span_m, float(row[0])),
            "wing_loading_target_Npm2": _scale(
                ranges.wing_loading_target_Npm2, float(row[1])
            ),
            "taper_ratio": _scale(ranges.taper_ratio, float(row[2])),
            "tip_twist_deg": _scale(ranges.tip_twist_deg, float(row[3])),
        }
        for row in unit_samples
    )


def _sample_secondary_design_variables(cfg, count: int) -> tuple[tuple[float, float, float, float], ...]:
    base_combos = tuple(
        product(
            cfg.geometry_family.tail_area_candidates_m2,
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
    if concept.tip_chord_m < float(constraints.tip_chord_min_m):
        return _geometry_rejection(
            sample_index=sample_index,
            reason="tip_chord_below_min",
            primary_values=primary_values,
            secondary_values=secondary_values,
            tip_chord_m=float(concept.tip_chord_m),
            tip_chord_min_m=float(constraints.tip_chord_min_m),
        )

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
    if minimum_station_chord_m < float(constraints.segment_min_chord_m):
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
        twist_deg = concept.twist_root_deg + frac * (concept.twist_tip_deg - concept.twist_root_deg)
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
        span_m = float(primary_values["span_m"])
        wing_loading_target_Npm2 = float(primary_values["wing_loading_target_Npm2"])
        taper_ratio = float(primary_values["taper_ratio"])
        tip_twist_deg = float(primary_values["tip_twist_deg"])
        (
            tail_area_m2,
            dihedral_root_deg,
            dihedral_tip_deg,
            dihedral_exponent,
        ) = secondary_values_tuple
        secondary_values = {
            "tail_area_m2": float(tail_area_m2),
            "dihedral_root_deg": float(dihedral_root_deg),
            "dihedral_tip_deg": float(dihedral_tip_deg),
            "dihedral_exponent": float(dihedral_exponent),
        }

        initial_wing_area_m2 = float(
            cfg.design_gross_weight_n / max(wing_loading_target_Npm2, 1.0e-9)
        )
        wing_area_m2 = initial_wing_area_m2
        design_gross_mass_kg = float(cfg.mass.design_gross_mass_kg)
        if bool(cfg.mass_closure.enabled):
            tube_mass_kg = _resolve_tube_system_mass_kg(cfg.mass_closure, span_m=span_m)
            try:
                mass_closure = close_area_mass(
                    wing_loading_target_Npm2=wing_loading_target_Npm2,
                    pilot_mass_kg=float(cfg.mass.pilot_mass_kg),
                    fixed_non_area_aircraft_mass_kg=float(
                        cfg.mass_closure.fixed_nonwing_aircraft_mass_kg
                    ),
                    wing_areal_density_kgpm2=float(
                        cfg.mass_closure.rib_skin_areal_density_kgpm2
                    ),
                    tube_system_mass_kg=tube_mass_kg,
                    wing_fittings_base_kg=float(cfg.mass_closure.wing_fittings_base_kg),
                    wire_terminal_mass_kg=float(cfg.mass_closure.wire_terminal_mass_kg),
                    extra_system_margin_kg=float(cfg.mass_closure.system_margin_kg),
                    initial_wing_area_m2=initial_wing_area_m2,
                    tolerance_m2=float(cfg.mass_closure.area_tolerance_m2),
                    max_iterations=int(cfg.mass_closure.max_iterations),
                )
            except ValueError as exc:
                rejected_concepts.append(
                    _geometry_rejection(
                        sample_index=sample_index,
                        reason="mass_area_closure_failed",
                        primary_values=primary_values,
                        secondary_values=secondary_values,
                        error=str(exc),
                    )
                )
                continue
            if not mass_closure.converged:
                rejected_concepts.append(
                    _geometry_rejection(
                        sample_index=sample_index,
                        reason="mass_area_closure_failed",
                        primary_values=primary_values,
                        secondary_values=secondary_values,
                        area_residual_m2=float(mass_closure.area_residual_m2),
                    )
                )
                continue
            if mass_closure.closed_gross_mass_kg > float(
                cfg.mass_closure.gross_mass_hard_max_kg
            ):
                rejected_concepts.append(
                    _geometry_rejection(
                        sample_index=sample_index,
                        reason="mass_hard_max_exceeded",
                        primary_values=primary_values,
                        secondary_values=secondary_values,
                        closed_gross_mass_kg=float(mass_closure.closed_gross_mass_kg),
                        gross_mass_hard_max_kg=float(cfg.mass_closure.gross_mass_hard_max_kg),
                        closed_wing_area_m2=float(mass_closure.closed_wing_area_m2),
                    )
                )
                continue
            wing_area_m2 = float(mass_closure.closed_wing_area_m2)
            design_gross_mass_kg = float(mass_closure.closed_gross_mass_kg)
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
            twist_tip_deg=float(tip_twist_deg),
            dihedral_root_deg=float(dihedral_root_deg),
            dihedral_tip_deg=float(dihedral_tip_deg),
            dihedral_exponent=float(dihedral_exponent),
            tail_area_m2=float(tail_area_m2),
            cg_xc=0.30,
            segment_lengths_m=segment_lengths_m,
            wing_loading_target_Npm2=float(wing_loading_target_Npm2),
            wing_area_is_derived=True,
            design_gross_mass_kg=float(design_gross_mass_kg),
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
