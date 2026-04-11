#!/usr/bin/env python3
"""Phase-3 low-dimensional material/layup proxy screening on top of V2.m++."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from itertools import product
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import AnalysisModeName, SparOptimizer
from hpa_mdo.structure.dual_beam_mainline.api import run_dual_beam_mainline_kernel
from hpa_mdo.structure.dual_beam_mainline.builder import build_dual_beam_mainline_model
from hpa_mdo.structure.material_proxy_catalog import (
    EffectiveMaterialProperties,
    MaterialProxyCatalog,
    MaterialScalePackage,
    build_default_material_proxy_catalog,
    effective_properties,
    register_package_material,
    resolve_catalog_property_rows,
)
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_crossval import _select_cruise_loads
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report
from scripts.direct_dual_beam_v2m import (
    DEFAULT_CATALOG_PROFILE,
    BaselineDesign,
    ManufacturingMapConfig,
    build_manufacturing_map_config,
    design_from_manufacturing_choice,
)
from scripts.direct_dual_beam_v2x import build_candidate_hard_margins, hard_violation_score_from_margins


DEFAULT_V2M_SUMMARY_JSON = (
    Path(__file__).resolve().parent.parent
    / "output"
    / "direct_dual_beam_v2m_plusplus_compare"
    / "direct_dual_beam_v2m_summary.json"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "direct_dual_beam_v2m_material_proxy"
SCREEN_TOP_K = 10


@dataclass(frozen=True)
class GeometrySeed:
    label: str
    choice: tuple[int, int, int, int, int]
    note: str
    main_t_seg_m: np.ndarray
    main_r_seg_m: np.ndarray
    rear_t_seg_m: np.ndarray
    rear_r_seg_m: np.ndarray


@dataclass(frozen=True)
class PackageDeltaRow:
    axis: str
    package_key: str
    package_label: str
    tube_mass_kg: float
    delta_tube_mass_kg: float
    psi_u_all_mm: float
    delta_psi_u_all_mm: float
    candidate_margin_mm: float
    delta_candidate_margin_mm: float
    hard_feasible: bool
    candidate_feasible: bool


@dataclass(frozen=True)
class GeometryBestRow:
    geometry_label: str
    geometry_choice: tuple[int, int, int, int, int]
    note: str
    main_family_key: str
    rear_family_key: str
    rear_outboard_pkg_key: str
    tube_mass_kg: float
    psi_u_all_mm: float
    candidate_margin_mm: float
    candidate_feasible: bool


@dataclass(frozen=True)
class MaterialProxyCandidate:
    geometry_label: str
    geometry_choice: tuple[int, int, int, int, int]
    geometry_note: str
    main_family_key: str
    main_family_label: str
    rear_family_key: str
    rear_family_label: str
    rear_outboard_pkg_key: str
    rear_outboard_pkg_label: str
    source: str
    message: str
    eval_wall_time_s: float
    tube_mass_kg: float
    total_structural_mass_kg: float
    psi_u_all_m: float
    psi_u_rear_m: float
    psi_u_rear_outboard_m: float
    dual_displacement_limit_m: float | None
    equivalent_failure_index: float
    equivalent_buckling_index: float
    equivalent_tip_deflection_m: float
    equivalent_twist_max_deg: float
    overall_hard_feasible: bool
    overall_optimizer_candidate_feasible: bool
    hard_failures: tuple[str, ...]
    candidate_failures: tuple[str, ...]
    hard_violation_score: float
    candidate_margin_m: float
    main_family_properties: EffectiveMaterialProperties
    rear_family_properties: EffectiveMaterialProperties
    rear_outboard_tip_properties: EffectiveMaterialProperties


@dataclass
class CandidateArchive:
    candidates: list[MaterialProxyCandidate] = field(default_factory=list)

    def add(self, cand: MaterialProxyCandidate) -> None:
        self.candidates.append(cand)

    @property
    def best_mass_candidate_feasible(self) -> MaterialProxyCandidate | None:
        feasible = [cand for cand in self.candidates if cand.overall_optimizer_candidate_feasible]
        if not feasible:
            return None
        return min(feasible, key=lambda cand: (cand.tube_mass_kg, cand.psi_u_all_m, -cand.candidate_margin_m))

    @property
    def best_margin_candidate_feasible(self) -> MaterialProxyCandidate | None:
        feasible = [cand for cand in self.candidates if cand.overall_optimizer_candidate_feasible]
        if not feasible:
            return None
        return max(feasible, key=lambda cand: (cand.candidate_margin_m, -cand.tube_mass_kg, -cand.psi_u_all_m))

    @property
    def best_violation(self) -> MaterialProxyCandidate | None:
        if not self.candidates:
            return None
        return min(
            self.candidates,
            key=lambda cand: (cand.hard_violation_score, -cand.candidate_margin_m, cand.tube_mass_kg),
        )


@dataclass(frozen=True)
class MaterialProxyOutcome:
    success: bool
    total_wall_time_s: float
    geometry_seed_count: int
    screened_candidate_count: int
    equivalent_analysis_calls: int
    production_analysis_calls: int
    reference_candidate: MaterialProxyCandidate
    best_mass_candidate_feasible: MaterialProxyCandidate | None
    best_margin_candidate_feasible: MaterialProxyCandidate | None
    best_violation: MaterialProxyCandidate
    package_delta_rows: tuple[PackageDeltaRow, ...]
    geometry_best_rows: tuple[GeometryBestRow, ...]
    top_candidate_feasible: tuple[MaterialProxyCandidate, ...]


def _mm(value_m: float | None) -> float:
    if value_m is None:
        return float("nan")
    return float(value_m) * 1000.0


def _elementwise_property_array(values: np.ndarray | float, ne: int, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 0:
        return np.full(ne, float(arr), dtype=float)
    if arr.shape != (ne,):
        raise ValueError(f"{name} must be scalar or have shape ({ne},), got {arr.shape}.")
    return arr


def _segment_values_to_stations(
    seg_values: np.ndarray,
    seg_lengths: list[float],
    stations_m: np.ndarray,
) -> np.ndarray:
    seg_values = np.asarray(seg_values, dtype=float).reshape(-1)
    if seg_values.size != len(seg_lengths):
        raise ValueError(f"Expected {len(seg_lengths)} segment values, got {seg_values.size}.")
    boundaries = np.concatenate(([0.0], np.cumsum(np.asarray(seg_lengths, dtype=float))))
    out = np.empty(stations_m.size, dtype=float)
    for index, station in enumerate(stations_m):
        seg_index = int(np.searchsorted(boundaries[1:], station, side="right"))
        out[index] = seg_values[min(seg_index, seg_values.size - 1)]
    return out


def _load_v2m_selected_choice(path: Path) -> tuple[int, int, int, int, int]:
    obj = json.loads(path.read_text())
    selected = obj["outcome"]["selected"]
    return tuple(int(value) for value in selected["choice_indices"])


def build_geometry_seeds(
    *,
    selected_choice: tuple[int, int, int, int, int],
    baseline: BaselineDesign,
    map_config: ManufacturingMapConfig,
) -> tuple[GeometrySeed, ...]:
    seeds: list[GeometrySeed] = []
    seen: set[tuple[int, int, int, int, int]] = set()
    axis_sizes = (
        len(map_config.main_plateau_delta_catalog_m),
        len(map_config.main_outboard_pair_delta_catalog_m),
        len(map_config.rear_general_radius_delta_catalog_m),
        len(map_config.rear_outboard_tip_delta_t_catalog_m),
        len(map_config.global_wall_delta_t_catalog_m),
    )

    def _add(label: str, choice: tuple[int, int, int, int, int], note: str) -> None:
        if choice in seen:
            return
        main_t, main_r, rear_t, rear_r = design_from_manufacturing_choice(
            baseline=baseline,
            choice=choice,
            map_config=map_config,
        )
        seeds.append(
            GeometrySeed(
                label=label,
                choice=choice,
                note=note,
                main_t_seg_m=main_t.copy(),
                main_r_seg_m=main_r.copy(),
                rear_t_seg_m=rear_t.copy(),
                rear_r_seg_m=rear_r.copy(),
            )
        )
        seen.add(choice)

    _add(
        "selected",
        selected_choice,
        "Current V2.m++ candidate-feasible discrete optimum.",
    )

    seed_specs = (
        ("main_plateau_minus1", 0, -1, "Lighter main plateau neighbor."),
        ("rear_general_plus1", 2, +1, "One-step rear global reserve neighbor."),
        ("rear_outboard_minus1", 3, -1, "Lighter rear seg5-6 sleeve neighbor."),
        ("rear_outboard_plus1", 3, +1, "Stiffer rear seg5-6 sleeve neighbor."),
    )
    for label, axis, delta, note in seed_specs:
        next_choice = list(selected_choice)
        next_choice[axis] += delta
        if next_choice[axis] < 0 or next_choice[axis] >= axis_sizes[axis]:
            continue
        _add(label, tuple(int(value) for value in next_choice), note)

    return tuple(seeds)


def apply_rear_outboard_reinforcement(
    *,
    model,
    rear_seg_lengths: list[float],
    rear_outboard_mask: np.ndarray,
    package: MaterialScalePackage,
) -> EffectiveMaterialProperties:
    ne = model.element_lengths_m.size
    element_centres_m = 0.5 * (model.y_nodes_m[:-1] + model.y_nodes_m[1:])
    mask = _segment_values_to_stations(
        np.asarray(rear_outboard_mask, dtype=float),
        rear_seg_lengths,
        element_centres_m,
    )

    rear_young_pa = _elementwise_property_array(model.rear_young_pa, ne, "rear_young_pa")
    rear_shear_pa = _elementwise_property_array(model.rear_shear_pa, ne, "rear_shear_pa")
    rear_density_kgpm3 = _elementwise_property_array(model.rear_density_kgpm3, ne, "rear_density_kgpm3")
    rear_allowable_pa = _elementwise_property_array(
        model.rear_allowable_stress_pa,
        ne,
        "rear_allowable_stress_pa",
    )

    young_blend = 1.0 + mask * (float(package.young_scale) - 1.0)
    shear_blend = 1.0 + mask * (float(package.shear_scale) - 1.0)
    density_blend = 1.0 + mask * (float(package.density_scale) - 1.0)
    allowable_blend = 1.0 + mask * (float(package.final_allowable_scale) - 1.0)

    model.rear_young_pa = rear_young_pa * young_blend
    model.rear_shear_pa = rear_shear_pa * shear_blend
    model.rear_density_kgpm3 = rear_density_kgpm3 * density_blend
    model.rear_allowable_stress_pa = rear_allowable_pa * allowable_blend
    model.rear_mass_per_length_kgpm = model.rear_area_m2 * model.rear_density_kgpm3

    tip_index = int(np.argmax(mask))
    return EffectiveMaterialProperties(
        E_eff_pa=float(np.asarray(model.rear_young_pa, dtype=float)[tip_index]),
        G_eff_pa=float(np.asarray(model.rear_shear_pa, dtype=float)[tip_index]),
        density_eff_kgpm3=float(np.asarray(model.rear_density_kgpm3, dtype=float)[tip_index]),
        allowable_eff_pa=float(np.asarray(model.rear_allowable_stress_pa, dtype=float)[tip_index]),
    )


class MaterialProxyEvaluator:
    def __init__(
        self,
        *,
        cfg,
        aircraft,
        materials_db: MaterialDB,
        mapped_loads: dict,
        export_loads: dict,
        map_config: ManufacturingMapConfig,
        catalog: MaterialProxyCatalog,
    ):
        self.cfg = cfg
        self.aircraft = aircraft
        self.materials_db = materials_db
        self.mapped_loads = mapped_loads
        self.export_loads = export_loads
        self.map_config = map_config
        self.catalog = catalog
        self.archive = CandidateArchive()
        self._cache: dict[tuple[str, tuple[int, int, int, int, int], str, str, str], MaterialProxyCandidate] = {}
        self._optimizer_cache: dict[tuple[str, str], tuple[object, MaterialDB, SparOptimizer]] = {}
        self.equivalent_analysis_calls = 0
        self.production_analysis_calls = 0

    def _proxy_environment(
        self,
        *,
        main_package: MaterialScalePackage,
        rear_package: MaterialScalePackage,
    ) -> tuple[object, MaterialDB, SparOptimizer]:
        cache_key = (main_package.key, rear_package.key)
        cached = self._optimizer_cache.get(cache_key)
        if cached is not None:
            return cached

        proxy_cfg = self.cfg.model_copy(deep=True)
        proxy_db = deepcopy(self.materials_db)

        main_key = f"material_proxy::{main_package.scope}::{main_package.key}"
        rear_key = f"material_proxy::{rear_package.scope}::{rear_package.key}"
        register_package_material(
            materials_db=proxy_db,
            base_material=self.materials_db.get(self.cfg.main_spar.material),
            package=main_package,
            key=main_key,
        )
        register_package_material(
            materials_db=proxy_db,
            base_material=self.materials_db.get(self.cfg.rear_spar.material),
            package=rear_package,
            key=rear_key,
        )
        proxy_cfg.main_spar.material = main_key
        proxy_cfg.rear_spar.material = rear_key

        optimizer = SparOptimizer(proxy_cfg, self.aircraft, self.mapped_loads, proxy_db)
        env = (proxy_cfg, proxy_db, optimizer)
        self._optimizer_cache[cache_key] = env
        return env

    def evaluate(
        self,
        *,
        geometry_seed: GeometrySeed,
        main_package: MaterialScalePackage,
        rear_package: MaterialScalePackage,
        rear_outboard_package: MaterialScalePackage,
        source: str,
    ) -> MaterialProxyCandidate:
        cache_key = (
            geometry_seed.label,
            geometry_seed.choice,
            main_package.key,
            rear_package.key,
            rear_outboard_package.key,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        proxy_cfg, proxy_db, optimizer = self._proxy_environment(
            main_package=main_package,
            rear_package=rear_package,
        )
        main_family_properties = effective_properties(
            self.materials_db.get(self.cfg.main_spar.material),
            main_package,
            safety_factor=float(self.cfg.safety.material_safety_factor),
        )
        rear_family_properties = effective_properties(
            self.materials_db.get(self.cfg.rear_spar.material),
            rear_package,
            safety_factor=float(self.cfg.safety.material_safety_factor),
        )

        t0 = perf_counter()
        try:
            eq_result = optimizer.analyze(
                main_t_seg=geometry_seed.main_t_seg_m,
                main_r_seg=geometry_seed.main_r_seg_m,
                rear_t_seg=geometry_seed.rear_t_seg_m,
                rear_r_seg=geometry_seed.rear_r_seg_m,
            )
            self.equivalent_analysis_calls += 1

            model = build_dual_beam_mainline_model(
                cfg=proxy_cfg,
                aircraft=self.aircraft,
                opt_result=eq_result,
                export_loads=self.export_loads,
                materials_db=proxy_db,
            )
            rear_outboard_tip_properties = apply_rear_outboard_reinforcement(
                model=model,
                rear_seg_lengths=proxy_cfg.spar_segment_lengths(proxy_cfg.rear_spar),
                rear_outboard_mask=self.map_config.rear_outboard_mask,
                package=rear_outboard_package,
            )
            production = run_dual_beam_mainline_kernel(
                model=model,
                mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
            )
            self.production_analysis_calls += 1

            hard_margins = build_candidate_hard_margins(production)
            hard_violation_score = hard_violation_score_from_margins(
                hard_margins,
                analysis_succeeded=bool(production.feasibility.analysis_succeeded),
            )
            dual_limit = production.optimizer.dual_displacement_limit_m
            candidate_margin_m = (
                float("inf")
                if dual_limit is None
                else float(dual_limit) - float(production.optimizer.psi_u_all_m)
            )

            candidate = MaterialProxyCandidate(
                geometry_label=geometry_seed.label,
                geometry_choice=geometry_seed.choice,
                geometry_note=geometry_seed.note,
                main_family_key=main_package.key,
                main_family_label=main_package.label,
                rear_family_key=rear_package.key,
                rear_family_label=rear_package.label,
                rear_outboard_pkg_key=rear_outboard_package.key,
                rear_outboard_pkg_label=rear_outboard_package.label,
                source=source,
                message="analysis complete",
                eval_wall_time_s=float(perf_counter() - t0),
                tube_mass_kg=float(production.recovery.spar_tube_mass_full_kg),
                total_structural_mass_kg=float(production.recovery.total_structural_mass_full_kg),
                psi_u_all_m=float(production.optimizer.psi_u_all_m),
                psi_u_rear_m=float(production.optimizer.psi_u_rear_m),
                psi_u_rear_outboard_m=float(production.optimizer.psi_u_rear_outboard_m),
                dual_displacement_limit_m=None if dual_limit is None else float(dual_limit),
                equivalent_failure_index=float(production.optimizer.equivalent_gates.failure_index),
                equivalent_buckling_index=float(production.optimizer.equivalent_gates.buckling_index),
                equivalent_tip_deflection_m=float(production.optimizer.equivalent_gates.tip_deflection_m),
                equivalent_twist_max_deg=float(production.optimizer.equivalent_gates.twist_max_deg),
                overall_hard_feasible=bool(production.feasibility.overall_hard_feasible),
                overall_optimizer_candidate_feasible=bool(
                    production.feasibility.overall_optimizer_candidate_feasible
                ),
                hard_failures=tuple(production.feasibility.hard_failures),
                candidate_failures=tuple(production.feasibility.candidate_constraint_failures),
                hard_violation_score=float(hard_violation_score),
                candidate_margin_m=float(candidate_margin_m),
                main_family_properties=main_family_properties,
                rear_family_properties=rear_family_properties,
                rear_outboard_tip_properties=rear_outboard_tip_properties,
            )
        except Exception as exc:  # pragma: no cover - runtime failures
            candidate = MaterialProxyCandidate(
                geometry_label=geometry_seed.label,
                geometry_choice=geometry_seed.choice,
                geometry_note=geometry_seed.note,
                main_family_key=main_package.key,
                main_family_label=main_package.label,
                rear_family_key=rear_package.key,
                rear_family_label=rear_package.label,
                rear_outboard_pkg_key=rear_outboard_package.key,
                rear_outboard_pkg_label=rear_outboard_package.label,
                source=source,
                message=f"{type(exc).__name__}: {exc}",
                eval_wall_time_s=float(perf_counter() - t0),
                tube_mass_kg=float("inf"),
                total_structural_mass_kg=float("inf"),
                psi_u_all_m=float("inf"),
                psi_u_rear_m=float("inf"),
                psi_u_rear_outboard_m=float("inf"),
                dual_displacement_limit_m=None,
                equivalent_failure_index=float("inf"),
                equivalent_buckling_index=float("inf"),
                equivalent_tip_deflection_m=float("inf"),
                equivalent_twist_max_deg=float("inf"),
                overall_hard_feasible=False,
                overall_optimizer_candidate_feasible=False,
                hard_failures=("analysis_exception",),
                candidate_failures=("dual_displacement_candidate",),
                hard_violation_score=float("inf"),
                candidate_margin_m=float("-inf"),
                main_family_properties=main_family_properties,
                rear_family_properties=rear_family_properties,
                rear_outboard_tip_properties=rear_family_properties,
            )

        self._cache[cache_key] = candidate
        self.archive.add(candidate)
        return candidate


def build_package_delta_rows(
    *,
    evaluator: MaterialProxyEvaluator,
    geometry_seed: GeometrySeed,
    catalog: MaterialProxyCatalog,
) -> tuple[PackageDeltaRow, ...]:
    ref_main = catalog.main_spar_family[0]
    ref_rear = catalog.rear_spar_family[0]
    ref_outboard = catalog.rear_outboard_reinforcement_pkg[0]
    reference = evaluator.evaluate(
        geometry_seed=geometry_seed,
        main_package=ref_main,
        rear_package=ref_rear,
        rear_outboard_package=ref_outboard,
        source="selected_geometry_reference",
    )

    rows: list[PackageDeltaRow] = []

    for package in catalog.main_spar_family[1:]:
        candidate = evaluator.evaluate(
            geometry_seed=geometry_seed,
            main_package=package,
            rear_package=ref_rear,
            rear_outboard_package=ref_outboard,
            source=f"single_axis:main:{package.key}",
        )
        rows.append(
            PackageDeltaRow(
                axis="main_spar_family",
                package_key=package.key,
                package_label=package.label,
                tube_mass_kg=float(candidate.tube_mass_kg),
                delta_tube_mass_kg=float(candidate.tube_mass_kg - reference.tube_mass_kg),
                psi_u_all_mm=_mm(candidate.psi_u_all_m),
                delta_psi_u_all_mm=_mm(candidate.psi_u_all_m - reference.psi_u_all_m),
                candidate_margin_mm=_mm(candidate.candidate_margin_m),
                delta_candidate_margin_mm=_mm(candidate.candidate_margin_m - reference.candidate_margin_m),
                hard_feasible=bool(candidate.overall_hard_feasible),
                candidate_feasible=bool(candidate.overall_optimizer_candidate_feasible),
            )
        )

    for package in catalog.rear_spar_family[1:]:
        candidate = evaluator.evaluate(
            geometry_seed=geometry_seed,
            main_package=ref_main,
            rear_package=package,
            rear_outboard_package=ref_outboard,
            source=f"single_axis:rear:{package.key}",
        )
        rows.append(
            PackageDeltaRow(
                axis="rear_spar_family",
                package_key=package.key,
                package_label=package.label,
                tube_mass_kg=float(candidate.tube_mass_kg),
                delta_tube_mass_kg=float(candidate.tube_mass_kg - reference.tube_mass_kg),
                psi_u_all_mm=_mm(candidate.psi_u_all_m),
                delta_psi_u_all_mm=_mm(candidate.psi_u_all_m - reference.psi_u_all_m),
                candidate_margin_mm=_mm(candidate.candidate_margin_m),
                delta_candidate_margin_mm=_mm(candidate.candidate_margin_m - reference.candidate_margin_m),
                hard_feasible=bool(candidate.overall_hard_feasible),
                candidate_feasible=bool(candidate.overall_optimizer_candidate_feasible),
            )
        )

    for package in catalog.rear_outboard_reinforcement_pkg[1:]:
        candidate = evaluator.evaluate(
            geometry_seed=geometry_seed,
            main_package=ref_main,
            rear_package=ref_rear,
            rear_outboard_package=package,
            source=f"single_axis:rear_outboard:{package.key}",
        )
        rows.append(
            PackageDeltaRow(
                axis="rear_outboard_reinforcement_pkg",
                package_key=package.key,
                package_label=package.label,
                tube_mass_kg=float(candidate.tube_mass_kg),
                delta_tube_mass_kg=float(candidate.tube_mass_kg - reference.tube_mass_kg),
                psi_u_all_mm=_mm(candidate.psi_u_all_m),
                delta_psi_u_all_mm=_mm(candidate.psi_u_all_m - reference.psi_u_all_m),
                candidate_margin_mm=_mm(candidate.candidate_margin_m),
                delta_candidate_margin_mm=_mm(candidate.candidate_margin_m - reference.candidate_margin_m),
                hard_feasible=bool(candidate.overall_hard_feasible),
                candidate_feasible=bool(candidate.overall_optimizer_candidate_feasible),
            )
        )

    return tuple(rows)


def run_material_proxy_screen(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    mapped_loads: dict,
    export_loads: dict,
    map_config: ManufacturingMapConfig,
    geometry_seeds: tuple[GeometrySeed, ...],
    catalog: MaterialProxyCatalog,
) -> MaterialProxyOutcome:
    evaluator = MaterialProxyEvaluator(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        mapped_loads=mapped_loads,
        export_loads=export_loads,
        map_config=map_config,
        catalog=catalog,
    )
    total_start = perf_counter()

    ref_main = catalog.main_spar_family[0]
    ref_rear = catalog.rear_spar_family[0]
    ref_outboard = catalog.rear_outboard_reinforcement_pkg[0]
    reference_candidate = evaluator.evaluate(
        geometry_seed=geometry_seeds[0],
        main_package=ref_main,
        rear_package=ref_rear,
        rear_outboard_package=ref_outboard,
        source="selected_geometry_reference",
    )

    for geometry_seed, main_package, rear_package, rear_outboard_package in product(
        geometry_seeds,
        catalog.main_spar_family,
        catalog.rear_spar_family,
        catalog.rear_outboard_reinforcement_pkg,
    ):
        evaluator.evaluate(
            geometry_seed=geometry_seed,
            main_package=main_package,
            rear_package=rear_package,
            rear_outboard_package=rear_outboard_package,
            source="screening_grid",
        )

    package_delta_rows = build_package_delta_rows(
        evaluator=evaluator,
        geometry_seed=geometry_seeds[0],
        catalog=catalog,
    )

    geometry_best_rows: list[GeometryBestRow] = []
    for geometry_seed in geometry_seeds:
        subset = [cand for cand in evaluator.archive.candidates if cand.geometry_label == geometry_seed.label]
        feasible = [cand for cand in subset if cand.overall_optimizer_candidate_feasible]
        selected = (
            min(feasible, key=lambda cand: (cand.tube_mass_kg, cand.psi_u_all_m, -cand.candidate_margin_m))
            if feasible
            else min(subset, key=lambda cand: (cand.hard_violation_score, cand.tube_mass_kg))
        )
        geometry_best_rows.append(
            GeometryBestRow(
                geometry_label=geometry_seed.label,
                geometry_choice=geometry_seed.choice,
                note=geometry_seed.note,
                main_family_key=selected.main_family_key,
                rear_family_key=selected.rear_family_key,
                rear_outboard_pkg_key=selected.rear_outboard_pkg_key,
                tube_mass_kg=float(selected.tube_mass_kg),
                psi_u_all_mm=_mm(selected.psi_u_all_m),
                candidate_margin_mm=_mm(selected.candidate_margin_m),
                candidate_feasible=bool(selected.overall_optimizer_candidate_feasible),
            )
        )

    top_candidate_feasible = tuple(
        sorted(
            (cand for cand in evaluator.archive.candidates if cand.overall_optimizer_candidate_feasible),
            key=lambda cand: (cand.tube_mass_kg, cand.psi_u_all_m, -cand.candidate_margin_m),
        )[:SCREEN_TOP_K]
    )
    best_mass_candidate_feasible = evaluator.archive.best_mass_candidate_feasible
    best_margin_candidate_feasible = evaluator.archive.best_margin_candidate_feasible
    best_violation = evaluator.archive.best_violation
    if best_violation is None:  # pragma: no cover - impossible when reference exists
        raise RuntimeError("Material proxy screen produced no candidates.")

    return MaterialProxyOutcome(
        success=best_mass_candidate_feasible is not None,
        total_wall_time_s=float(perf_counter() - total_start),
        geometry_seed_count=len(geometry_seeds),
        screened_candidate_count=len(evaluator.archive.candidates),
        equivalent_analysis_calls=int(evaluator.equivalent_analysis_calls),
        production_analysis_calls=int(evaluator.production_analysis_calls),
        reference_candidate=reference_candidate,
        best_mass_candidate_feasible=best_mass_candidate_feasible,
        best_margin_candidate_feasible=best_margin_candidate_feasible,
        best_violation=best_violation,
        package_delta_rows=tuple(package_delta_rows),
        geometry_best_rows=tuple(geometry_best_rows),
        top_candidate_feasible=top_candidate_feasible,
    )


def candidate_to_summary_dict(candidate: MaterialProxyCandidate | None) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "geometry_label": candidate.geometry_label,
        "geometry_choice": list(candidate.geometry_choice),
        "geometry_note": candidate.geometry_note,
        "main_family_key": candidate.main_family_key,
        "main_family_label": candidate.main_family_label,
        "rear_family_key": candidate.rear_family_key,
        "rear_family_label": candidate.rear_family_label,
        "rear_outboard_pkg_key": candidate.rear_outboard_pkg_key,
        "rear_outboard_pkg_label": candidate.rear_outboard_pkg_label,
        "source": candidate.source,
        "message": candidate.message,
        "eval_wall_time_s": candidate.eval_wall_time_s,
        "tube_mass_kg": candidate.tube_mass_kg,
        "total_structural_mass_kg": candidate.total_structural_mass_kg,
        "psi_u_all_m": candidate.psi_u_all_m,
        "psi_u_rear_m": candidate.psi_u_rear_m,
        "psi_u_rear_outboard_m": candidate.psi_u_rear_outboard_m,
        "dual_displacement_limit_m": candidate.dual_displacement_limit_m,
        "candidate_margin_m": candidate.candidate_margin_m,
        "equivalent_failure_index": candidate.equivalent_failure_index,
        "equivalent_buckling_index": candidate.equivalent_buckling_index,
        "equivalent_tip_deflection_m": candidate.equivalent_tip_deflection_m,
        "equivalent_twist_max_deg": candidate.equivalent_twist_max_deg,
        "overall_hard_feasible": candidate.overall_hard_feasible,
        "overall_optimizer_candidate_feasible": candidate.overall_optimizer_candidate_feasible,
        "hard_failures": list(candidate.hard_failures),
        "candidate_failures": list(candidate.candidate_failures),
        "hard_violation_score": candidate.hard_violation_score,
        "main_family_properties": asdict(candidate.main_family_properties),
        "rear_family_properties": asdict(candidate.rear_family_properties),
        "rear_outboard_tip_properties": asdict(candidate.rear_outboard_tip_properties),
    }


def catalog_to_summary_dict(
    *,
    catalog: MaterialProxyCatalog,
    cfg,
    materials_db: MaterialDB,
) -> dict[str, object]:
    resolved = resolve_catalog_property_rows(
        catalog=catalog,
        materials_db=materials_db,
        axis_base_material_keys={
            "main_spar_family": cfg.main_spar.material,
            "rear_spar_family": cfg.rear_spar.material,
            "rear_outboard_reinforcement_pkg": cfg.rear_spar.material,
        },
        safety_factor=float(cfg.safety.material_safety_factor),
    )

    summary: dict[str, object] = {}
    for axis_name, rows in resolved.items():
        axis_info = catalog.axis_info(axis_name)
        packages: list[dict[str, object]] = []
        for row in rows:
            package = row.package
            props = row.effective_properties
            packages.append(
                {
                    "key": package.key,
                    "label": package.label,
                    "scope": package.scope,
                    "description": package.description,
                    "family_description": package.family_description,
                    "intended_role": package.intended_role,
                    "manufacturing_notes": package.manufacturing_notes,
                    "buckling_note": package.buckling_note,
                    "promotion_state": package.promotion_state,
                    "source_material_grade": package.source_material_grade,
                    "layup_reference": package.layup_reference,
                    "layup_fractions": asdict(package.layup_fractions),
                    "requires_balanced_symmetric": package.requires_balanced_symmetric,
                    "property_sources": asdict(package.property_sources),
                    "buckling_rules": asdict(package.buckling_rules),
                    "overlay_layers_equivalent": package.overlay_layers_equivalent,
                    "overlay_construction": package.overlay_construction,
                    "base_material_key": row.base_material_key,
                    "base_material_name": row.base_material_name,
                    "young_scale": package.young_scale,
                    "shear_scale": package.shear_scale,
                    "density_scale": package.density_scale,
                    "allowable_scale": package.allowable_scale,
                    "final_allowable_scale": package.final_allowable_scale,
                    "E_eff_pa": props.E_eff_pa,
                    "G_eff_pa": props.G_eff_pa,
                    "density_eff_kgpm3": props.density_eff_kgpm3,
                    "allowable_eff_pa": props.allowable_eff_pa,
                }
            )
        summary[axis_name] = {
            "axis": axis_name,
            "description": axis_info.description,
            "integration_mode": axis_info.integration_mode,
            "promotion_state": axis_info.promotion_state,
            "default_base_material_key": axis_info.default_base_material_key,
            "packages": packages,
        }
    return summary


def build_report_text(
    *,
    config_path: Path,
    design_report: Path,
    v2m_summary_json: Path,
    geometry_seeds: tuple[GeometrySeed, ...],
    catalog: MaterialProxyCatalog,
    cfg,
    materials_db: MaterialDB,
    outcome: MaterialProxyOutcome,
) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    catalog_summary = catalog_to_summary_dict(catalog=catalog, cfg=cfg, materials_db=materials_db)

    lines: list[str] = []
    lines.append("=" * 116)
    lines.append("Direct Dual-Beam V2.m++ Phase-3 Material / Layup Proxy Screen")
    lines.append("=" * 116)
    lines.append(f"Generated                     : {timestamp}")
    lines.append(f"Config                        : {config_path}")
    lines.append(f"Design report                 : {design_report}")
    lines.append(f"V2.m++ summary                : {v2m_summary_json}")
    lines.append(f"Catalog profile               : {DEFAULT_CATALOG_PROFILE}")
    lines.append("")
    lines.append("Intent:")
    lines.append("  Keep the V2.m++ geometry ladder fixed, then screen a low-dimensional material/layup proxy set.")
    lines.append("  Global main/rear family goes through equivalent + production.")
    lines.append("  Rear seg5-6 reinforcement package is local to production and remains conservative against equivalent gates.")
    lines.append("")
    lines.append("Proxy catalog (current baseline-material interpretation):")
    for axis_name in ("main_spar_family", "rear_spar_family", "rear_outboard_reinforcement_pkg"):
        axis_summary = catalog_summary[axis_name]
        lines.append(
            f"  {axis_name}: integration={axis_summary['integration_mode']}  promotion={axis_summary['promotion_state']}"
        )
        lines.append(f"    {axis_summary['description']}")
        for package in axis_summary["packages"]:
            layup = package["layup_fractions"]
            rules = package["buckling_rules"]
            lines.append(
                "    "
                f"{package['key']:24s} E={package['E_eff_pa'] / 1.0e9:7.2f} GPa  "
                f"G={package['G_eff_pa'] / 1.0e9:6.2f} GPa  "
                f"rho={package['density_eff_kgpm3']:7.1f}  "
                f"allow={package['allowable_eff_pa'] / 1.0e6:7.1f} MPa"
            )
            lines.append(f"      {package['description']}")
            lines.append(
                "      "
                f"layup[{package['layup_reference']}] 0={layup['axial_0'] * 100:4.0f}%  "
                f"+/-45={layup['shear_pm45'] * 100:4.0f}%  90={layup['hoop_90'] * 100:4.0f}%  "
                f"grade={package['source_material_grade']}"
            )
            lines.append(
                "      "
                f"rules: hoop>={rules['minimum_hoop_fraction'] * 100:4.0f}%  "
                f"outer_pure_0_forbidden={rules['forbid_outer_pure_axial']}  "
                f"allow_kd={rules['conservative_allowable_knockdown']:.2f}  "
                f"region={rules['allowed_region']}  "
                f"buckling_reserve={rules['local_buckling_reserve']}"
            )
    lines.append("")
    lines.append("Geometry seeds:")
    for seed in geometry_seeds:
        lines.append(f"  {seed.label:22s} choice={seed.choice}  {seed.note}")
    lines.append("")
    lines.append("Run summary:")
    lines.append(f"  success                     : {outcome.success}")
    lines.append(f"  total wall time             : {outcome.total_wall_time_s:.3f} s")
    lines.append(f"  geometry seeds              : {outcome.geometry_seed_count}")
    lines.append(f"  screened candidates         : {outcome.screened_candidate_count}")
    lines.append(f"  equivalent analysis calls   : {outcome.equivalent_analysis_calls}")
    lines.append(f"  production analysis calls   : {outcome.production_analysis_calls}")
    lines.append("")
    ref = outcome.reference_candidate
    lines.append("Selected-geometry reference (all packages at reference):")
    lines.append(f"  tube mass                   : {ref.tube_mass_kg:11.3f} kg")
    lines.append(f"  psi_u_all                   : {_mm(ref.psi_u_all_m):11.3f} mm")
    lines.append(f"  candidate margin            : {_mm(ref.candidate_margin_m):11.3f} mm")
    lines.append(
        f"  hard / candidate            : {ref.overall_hard_feasible} / {ref.overall_optimizer_candidate_feasible}"
    )
    lines.append("")
    lines.append("Selected-geometry one-axis package deltas:")
    lines.append(
        "  axis                         package                    dm[kg]   dpsi[mm]   margin[mm]   cand"
    )
    for row in outcome.package_delta_rows:
        lines.append(
            f"  {row.axis:28s} {row.package_key:24s} {row.delta_tube_mass_kg:+8.3f} "
            f"{row.delta_psi_u_all_mm:+10.3f} {row.candidate_margin_mm:11.3f} "
            f"{str(row.candidate_feasible):>5s}"
        )
    lines.append("")
    if outcome.best_mass_candidate_feasible is not None:
        best = outcome.best_mass_candidate_feasible
        lines.append("Best candidate-feasible by mass:")
        lines.append(
            f"  {best.geometry_label} / {best.main_family_key} / {best.rear_family_key} / {best.rear_outboard_pkg_key}"
        )
        lines.append(f"  tube mass                   : {best.tube_mass_kg:11.3f} kg")
        lines.append(f"  psi_u_all                   : {_mm(best.psi_u_all_m):11.3f} mm")
        lines.append(f"  candidate margin            : {_mm(best.candidate_margin_m):11.3f} mm")
        lines.append("")
    if outcome.best_margin_candidate_feasible is not None:
        best = outcome.best_margin_candidate_feasible
        lines.append("Best candidate-feasible by candidate margin:")
        lines.append(
            f"  {best.geometry_label} / {best.main_family_key} / {best.rear_family_key} / {best.rear_outboard_pkg_key}"
        )
        lines.append(f"  tube mass                   : {best.tube_mass_kg:11.3f} kg")
        lines.append(f"  psi_u_all                   : {_mm(best.psi_u_all_m):11.3f} mm")
        lines.append(f"  candidate margin            : {_mm(best.candidate_margin_m):11.3f} mm")
        lines.append("")
    lines.append("Best screened package set by geometry seed:")
    lines.append("  geometry                 combo                                         mass[kg]   psi[mm]   margin[mm]   cand")
    for row in outcome.geometry_best_rows:
        combo = f"{row.main_family_key}/{row.rear_family_key}/{row.rear_outboard_pkg_key}"
        lines.append(
            f"  {row.geometry_label:22s} {combo:44s} {row.tube_mass_kg:8.3f} "
            f"{row.psi_u_all_mm:9.3f} {row.candidate_margin_mm:11.3f} {str(row.candidate_feasible):>5s}"
        )
    lines.append("")
    lines.append("Promotion guidance:")
    lines.append("  1. Keep this as screening first; do not Cartesian-product the full V2.m++ grid with the full proxy catalog.")
    lines.append("  2. First promote only packages that repeat across the selected point and at least one nearby geometry seed.")
    lines.append("  3. Treat rear_outboard_reinforcement_pkg as the first candidate for formal promotion.")
    lines.append("  4. Do not split out a standalone torsion_oriented_reserve_pkg yet; keep it folded into the rear outboard package catalog.")
    lines.append("  5. Do not add a separate global_thickness_stiffness_reserve_pkg yet; V2.m++ already has global wall reserve.")
    return "\n".join(lines) + "\n"


def build_summary_json(
    *,
    config_path: Path,
    design_report: Path,
    v2m_summary_json: Path,
    geometry_seeds: tuple[GeometrySeed, ...],
    catalog: MaterialProxyCatalog,
    cfg,
    materials_db: MaterialDB,
    outcome: MaterialProxyOutcome,
) -> dict[str, object]:
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "v2m_summary_json": str(v2m_summary_json),
        "catalog_profile": DEFAULT_CATALOG_PROFILE,
        "geometry_seeds": [
            {
                "label": seed.label,
                "choice": list(seed.choice),
                "note": seed.note,
                "design_mm": {
                    "main_t": [float(value * 1000.0) for value in seed.main_t_seg_m],
                    "main_r": [float(value * 1000.0) for value in seed.main_r_seg_m],
                    "rear_t": [float(value * 1000.0) for value in seed.rear_t_seg_m],
                    "rear_r": [float(value * 1000.0) for value in seed.rear_r_seg_m],
                },
            }
            for seed in geometry_seeds
        ],
        "proxy_catalog": catalog_to_summary_dict(catalog=catalog, cfg=cfg, materials_db=materials_db),
        "outcome": {
            "success": outcome.success,
            "total_wall_time_s": outcome.total_wall_time_s,
            "geometry_seed_count": outcome.geometry_seed_count,
            "screened_candidate_count": outcome.screened_candidate_count,
            "equivalent_analysis_calls": outcome.equivalent_analysis_calls,
            "production_analysis_calls": outcome.production_analysis_calls,
            "reference_candidate": candidate_to_summary_dict(outcome.reference_candidate),
            "best_mass_candidate_feasible": candidate_to_summary_dict(outcome.best_mass_candidate_feasible),
            "best_margin_candidate_feasible": candidate_to_summary_dict(outcome.best_margin_candidate_feasible),
            "best_violation": candidate_to_summary_dict(outcome.best_violation),
            "package_delta_rows": [asdict(row) for row in outcome.package_delta_rows],
            "geometry_best_rows": [asdict(row) for row in outcome.geometry_best_rows],
            "top_candidate_feasible": [candidate_to_summary_dict(candidate) for candidate in outcome.top_candidate_feasible],
        },
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Screen low-dimensional material/layup proxy packages on top of V2.m++."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
    )
    parser.add_argument(
        "--design-report",
        default=str(
            Path(__file__).resolve().parent.parent
            / "output"
            / "blackcat_004_dual_beam_production_check"
            / "ansys"
            / "crossval_report.txt"
        ),
    )
    parser.add_argument(
        "--v2m-summary-json",
        default=str(DEFAULT_V2M_SUMMARY_JSON),
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    design_report = Path(args.design_report).expanduser().resolve()
    v2m_summary_json = Path(args.v2m_summary_json).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(config_path)
    specimen_metrics = parse_baseline_metrics(design_report)
    cfg.solver.n_beam_nodes = int(specimen_metrics.nodes_per_spar)
    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    baseline_result = build_specimen_result_from_crossval_report(design_report)

    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
    map_config = build_manufacturing_map_config(
        baseline=baseline_design,
        cfg=cfg,
        catalog_profile=DEFAULT_CATALOG_PROFILE,
    )
    selected_choice = _load_v2m_selected_choice(v2m_summary_json)
    geometry_seeds = build_geometry_seeds(
        selected_choice=selected_choice,
        baseline=baseline_design,
        map_config=map_config,
    )

    catalog = build_default_material_proxy_catalog()
    _, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)

    outcome = run_material_proxy_screen(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        mapped_loads=mapped_loads,
        export_loads=export_loads,
        map_config=map_config,
        geometry_seeds=geometry_seeds,
        catalog=catalog,
    )

    report_path = output_dir / "direct_dual_beam_v2m_material_proxy_report.txt"
    report_path.write_text(
        build_report_text(
            config_path=config_path,
            design_report=design_report,
            v2m_summary_json=v2m_summary_json,
            geometry_seeds=geometry_seeds,
            catalog=catalog,
            cfg=cfg,
            materials_db=materials_db,
            outcome=outcome,
        ),
        encoding="utf-8",
    )

    json_path = output_dir / "direct_dual_beam_v2m_material_proxy_summary.json"
    json_path.write_text(
        json.dumps(
            build_summary_json(
                config_path=config_path,
                design_report=design_report,
                v2m_summary_json=v2m_summary_json,
                geometry_seeds=geometry_seeds,
                catalog=catalog,
                cfg=cfg,
                materials_db=materials_db,
                outcome=outcome,
            ),
            indent=2,
            default=lambda value: value.tolist() if isinstance(value, np.ndarray) else value,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Direct dual-beam V2.m++ material proxy screen complete.")
    print(f"  Report              : {report_path}")
    print(f"  Summary JSON        : {json_path}")
    print(f"  Screened candidates : {outcome.screened_candidate_count}")
    print(f"  Total wall time     : {outcome.total_wall_time_s:.3f} s")
    if outcome.best_mass_candidate_feasible is not None:
        best = outcome.best_mass_candidate_feasible
        print(
            "  Best feasible       : "
            f"{best.geometry_label} / {best.main_family_key} / {best.rear_family_key} / {best.rear_outboard_pkg_key}"
        )
        print(f"  Best mass / psi     : {best.tube_mass_kg:.3f} kg / {_mm(best.psi_u_all_m):.3f} mm")
    else:
        print("  Best feasible       : none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
