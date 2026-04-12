#!/usr/bin/env python3
"""Reduced joint geometry + promoted-material discrete search on top of V2.m++."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import product
import json
from pathlib import Path
import sys
from time import perf_counter
from collections import Counter

import numpy as np

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure.material_proxy_catalog import build_default_material_proxy_catalog
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_crossval import _select_cruise_loads
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report
from scripts.direct_dual_beam_v2m import (
    DEFAULT_CATALOG_PROFILE,
    BaselineDesign,
    build_manufacturing_map_config,
    design_from_manufacturing_choice,
)
from scripts.direct_dual_beam_v2m_material_proxy import (
    GeometrySeed,
    MaterialProxyCandidate,
    MaterialProxyEvaluator,
    build_geometry_seeds as build_compact_geometry_seeds,
    catalog_to_summary_dict,
    candidate_to_summary_dict,
)


DEFAULT_V2M_SUMMARY_JSON = (
    Path(__file__).resolve().parent.parent
    / "output"
    / "direct_dual_beam_v2m_plusplus_compare"
    / "direct_dual_beam_v2m_summary.json"
)
DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent / "output" / "direct_dual_beam_v2m_joint_material"
)
TOP_K = 10
COMPACT_STRATEGY = "compact"
EXPANDED_STRATEGY = "expanded"
WORKFLOW_STRATEGY = "workflow"
DEFAULT_STRATEGY = WORKFLOW_STRATEGY
REPRESENTATIVE_REGION_RADIUS_L1 = 1
RIDGE_REFINEMENT_GEOMETRY_SPECS = {
    "margin_first": (
        (
            "ridge_rear_general_plus1",
            {2: +1},
            "Push one step further along rear global reserve at the current margin-side wall level.",
        ),
        (
            "ridge_rear_outboard_plus1",
            {3: +1},
            "Push one step stiffer in rear seg5-6 sleeve while keeping the current margin-side wall level.",
        ),
        (
            "ridge_rear_general_plus1_plus_outboard_plus1",
            {2: +1, 3: +1},
            "Couple rear global reserve and rear seg5-6 sleeve to extend the margin ridge.",
        ),
    ),
    "balanced": (
        (
            "ridge_global_wall_plus1",
            {4: +1},
            "Add one-step global wall reserve on top of the current balanced ridge point.",
        ),
        (
            "ridge_rear_outboard_plus1",
            {3: +1},
            "Push one step stiffer in rear seg5-6 sleeve along the balanced ridge.",
        ),
        (
            "ridge_rear_outboard_plus1_plus_global_wall_plus1",
            {3: +1, 4: +1},
            "Couple rear sleeve and global wall reserve to probe the upper balanced-to-margin ridge.",
        ),
    ),
}
EXPANDED_PAIRWISE_GEOMETRY_SPECS = (
    ("light_main_plus_rear_general", {0: -1, 2: +1}, "Lighter main plateau with one-step rear global reserve."),
    (
        "light_main_plus_rear_outboard_minus1",
        {0: -1, 3: -1},
        "Lighter main plateau with one-step lighter rear seg5-6 sleeve.",
    ),
    (
        "light_main_plus_rear_outboard_plus1",
        {0: -1, 3: +1},
        "Lighter main plateau with one-step stiffer rear seg5-6 sleeve.",
    ),
    (
        "light_main_plus_global_wall",
        {0: -1, 4: +1},
        "Lighter main plateau offset by one-step global wall thickening.",
    ),
    (
        "rear_general_plus1_plus_outboard_plus1",
        {2: +1, 3: +1},
        "Rear reserve stack: one-step rear global reserve plus stiffer outboard sleeve.",
    ),
    (
        "main_outboard_plus1_plus_rear_outboard_plus1",
        {1: +1, 3: +1},
        "Main outboard pair thickening coupled with one-step stiffer rear sleeve.",
    ),
)


@dataclass(frozen=True)
class JointGeometryBestRow:
    geometry_label: str
    geometry_choice: tuple[int, int, int, int, int]
    joint_choice_indices: tuple[int, int, int, int, int, int, int]
    main_family_key: str
    rear_outboard_pkg_key: str
    tube_mass_kg: float
    psi_u_all_mm: float
    candidate_margin_mm: float
    candidate_feasible: bool


@dataclass(frozen=True)
class JointMaterialOutcome:
    success: bool
    feasible: bool
    message: str
    search_strategy: str
    total_wall_time_s: float
    geometry_seed_count: int
    discovery_geometry_seed_count: int
    support_geometry_seed_count: int
    ridge_geometry_seed_count: int
    evaluated_candidate_count: int
    search_space_size: int
    equivalent_analysis_calls: int
    production_analysis_calls: int
    reference_candidate: MaterialProxyCandidate
    selected_candidate: MaterialProxyCandidate
    mass_first_candidate_feasible: MaterialProxyCandidate | None
    margin_first_candidate_feasible: MaterialProxyCandidate | None
    balanced_compromise_candidate_feasible: MaterialProxyCandidate | None
    best_margin_candidate_feasible: MaterialProxyCandidate | None
    best_violation: MaterialProxyCandidate
    geometry_best_rows: tuple[JointGeometryBestRow, ...]
    pareto_frontier_candidate_feasible: tuple[MaterialProxyCandidate, ...]
    representative_regions: tuple["JointRepresentativeRegion", ...]
    top_candidate_feasible: tuple[MaterialProxyCandidate, ...]


@dataclass(frozen=True)
class JointRepresentativeRegion:
    region_key: str
    center_geometry_choice: tuple[int, int, int, int, int]
    support_radius_l1: int
    geometry_choice_count: int
    feasible_candidate_count: int
    pareto_candidate_count: int
    best_mass_candidate_feasible: MaterialProxyCandidate | None
    best_margin_candidate_feasible: MaterialProxyCandidate | None
    balanced_compromise_candidate_feasible: MaterialProxyCandidate | None
    pareto_main_family_counts: tuple[tuple[str, int], ...]
    pareto_rear_outboard_pkg_counts: tuple[tuple[str, int], ...]


def _mm(value_m: float | None) -> float:
    if value_m is None:
        return float("nan")
    return float(value_m) * 1000.0


def _signed_mm_delta(delta_m: float) -> float:
    return float(delta_m) * 1000.0


def _choice_signature(candidate: MaterialProxyCandidate) -> tuple[tuple[int, int, int, int, int], str, str]:
    return (
        tuple(int(value) for value in candidate.geometry_choice),
        str(candidate.main_family_key),
        str(candidate.rear_outboard_pkg_key),
    )


def _candidate_joint_choice(
    *,
    candidate: MaterialProxyCandidate,
    main_index_map: dict[str, int],
    outboard_index_map: dict[str, int],
) -> tuple[int, int, int, int, int, int, int]:
    return build_joint_choice_indices(
        geometry_choice=candidate.geometry_choice,
        main_family_index=main_index_map[candidate.main_family_key],
        rear_outboard_index=outboard_index_map[candidate.rear_outboard_pkg_key],
    )


def _append_candidate_block(
    *,
    lines: list[str],
    title: str,
    candidate: MaterialProxyCandidate | None,
    main_index_map: dict[str, int],
    outboard_index_map: dict[str, int],
) -> None:
    lines.append(title)
    if candidate is None:
        lines.append("  none")
        lines.append("")
        return
    joint_choice = _candidate_joint_choice(
        candidate=candidate,
        main_index_map=main_index_map,
        outboard_index_map=outboard_index_map,
    )
    lines.append(f"  geometry seed               : {candidate.geometry_label}")
    lines.append(f"  geometry choice             : {candidate.geometry_choice}")
    lines.append(f"  joint choice indices        : {joint_choice}")
    lines.append(f"  main_spar_family            : {candidate.main_family_key}")
    lines.append(f"  rear_outboard_pkg           : {candidate.rear_outboard_pkg_key}")
    lines.append(f"  mass                        : {candidate.tube_mass_kg:11.3f} kg")
    lines.append(f"  total structural mass       : {candidate.total_structural_mass_kg:11.3f} kg")
    lines.append(f"  raw main tip                : {_mm(candidate.raw_main_tip_m):11.3f} mm")
    lines.append(f"  raw rear tip                : {_mm(candidate.raw_rear_tip_m):11.3f} mm")
    lines.append(f"  raw max |UZ|                : {_mm(candidate.raw_max_uz_m):11.3f} mm")
    lines.append(f"  raw max |UZ| location       : {candidate.raw_max_location}")
    lines.append(f"  psi_u_all                   : {_mm(candidate.psi_u_all_m):11.3f} mm")
    lines.append(f"  candidate margin            : {_mm(candidate.candidate_margin_m):11.3f} mm")
    lines.append(f"  hard / candidate            : {candidate.overall_hard_feasible} / {candidate.overall_optimizer_candidate_feasible}")
    lines.append("")


def _format_count_pairs(counts: tuple[tuple[str, int], ...]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={count}" for key, count in counts)


def _axis_sizes_from_map_config(map_config) -> tuple[int, int, int, int, int]:
    return (
        len(map_config.main_plateau_delta_catalog_m),
        len(map_config.main_outboard_pair_delta_catalog_m),
        len(map_config.rear_general_radius_delta_catalog_m),
        len(map_config.rear_outboard_tip_delta_t_catalog_m),
        len(map_config.global_wall_delta_t_catalog_m),
    )


def _offset_choice(
    *,
    base_choice: tuple[int, int, int, int, int],
    axis_deltas: dict[int, int],
    axis_sizes: tuple[int, int, int, int, int],
) -> tuple[int, int, int, int, int] | None:
    next_choice = list(base_choice)
    for axis, delta in axis_deltas.items():
        next_choice[axis] += int(delta)
        if next_choice[axis] < 0 or next_choice[axis] >= axis_sizes[axis]:
            return None
    return tuple(int(value) for value in next_choice)


def _append_geometry_seed(
    *,
    seeds: list[GeometrySeed],
    seen: set[tuple[int, int, int, int, int]],
    label: str,
    choice: tuple[int, int, int, int, int] | None,
    note: str,
    baseline: BaselineDesign,
    map_config,
) -> None:
    if choice is None or choice in seen:
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


def build_expanded_geometry_seeds(
    *,
    selected_choice: tuple[int, int, int, int, int],
    baseline: BaselineDesign,
    map_config,
) -> tuple[GeometrySeed, ...]:
    seeds = list(
        build_compact_geometry_seeds(
            selected_choice=selected_choice,
            baseline=baseline,
            map_config=map_config,
        )
    )
    seen = {tuple(int(value) for value in seed.choice) for seed in seeds}
    axis_sizes = _axis_sizes_from_map_config(map_config)

    single_axis_specs = (
        ("main_outboard_plus1", {1: +1}, "One-step main outboard pair thickening neighbor."),
        ("global_wall_plus1", {4: +1}, "One-step global wall thickening neighbor."),
        ("main_plateau_minus2", {0: -2}, "Two-step lighter main plateau neighbor."),
        ("rear_general_plus2", {2: +2}, "Two-step rear global reserve neighbor."),
        ("rear_outboard_minus2", {3: -2}, "Two-step lighter rear seg5-6 sleeve neighbor."),
        ("rear_outboard_plus2", {3: +2}, "Two-step stiffer rear seg5-6 sleeve neighbor."),
    )
    for label, axis_deltas, note in single_axis_specs:
        _append_geometry_seed(
            seeds=seeds,
            seen=seen,
            label=label,
            choice=_offset_choice(
                base_choice=selected_choice,
                axis_deltas=axis_deltas,
                axis_sizes=axis_sizes,
            ),
            note=note,
            baseline=baseline,
            map_config=map_config,
        )

    for label, axis_deltas, note in EXPANDED_PAIRWISE_GEOMETRY_SPECS:
        _append_geometry_seed(
            seeds=seeds,
            seen=seen,
            label=label,
            choice=_offset_choice(
                base_choice=selected_choice,
                axis_deltas=axis_deltas,
                axis_sizes=axis_sizes,
            ),
            note=note,
            baseline=baseline,
            map_config=map_config,
        )

    return tuple(seeds)


def build_joint_geometry_seeds(
    *,
    strategy: str,
    selected_choice: tuple[int, int, int, int, int],
    baseline: BaselineDesign,
    map_config,
) -> tuple[GeometrySeed, ...]:
    if strategy == COMPACT_STRATEGY:
        return build_compact_geometry_seeds(
            selected_choice=selected_choice,
            baseline=baseline,
            map_config=map_config,
        )
    if strategy == EXPANDED_STRATEGY:
        return build_expanded_geometry_seeds(
            selected_choice=selected_choice,
            baseline=baseline,
            map_config=map_config,
        )
    raise ValueError(f"Unsupported joint search strategy: {strategy}")


def build_representative_support_geometry_seeds(
    *,
    representative_centres: tuple[tuple[str, tuple[int, int, int, int, int]], ...],
    baseline: BaselineDesign,
    map_config,
    existing_choices: set[tuple[int, int, int, int, int]] | None = None,
) -> tuple[GeometrySeed, ...]:
    seeds: list[GeometrySeed] = []
    seen = set() if existing_choices is None else {tuple(choice) for choice in existing_choices}

    for region_key, choice in representative_centres:
        compact_neighborhood = build_compact_geometry_seeds(
            selected_choice=choice,
            baseline=baseline,
            map_config=map_config,
        )
        for compact_seed in compact_neighborhood:
            label_suffix = "center" if compact_seed.label == "selected" else compact_seed.label
            _append_geometry_seed(
                seeds=seeds,
                seen=seen,
                label=f"{region_key}_{label_suffix}",
                choice=compact_seed.choice,
                note=f"{region_key} stability neighborhood: {compact_seed.note}",
                baseline=baseline,
                map_config=map_config,
            )

    return tuple(seeds)


def build_ridge_refinement_geometry_seeds(
    *,
    representative_centres: tuple[tuple[str, tuple[int, int, int, int, int]], ...],
    baseline: BaselineDesign,
    map_config,
    existing_choices: set[tuple[int, int, int, int, int]] | None = None,
) -> tuple[GeometrySeed, ...]:
    seeds: list[GeometrySeed] = []
    seen = set() if existing_choices is None else {tuple(choice) for choice in existing_choices}
    axis_sizes = _axis_sizes_from_map_config(map_config)

    for region_key, choice in representative_centres:
        region_specs = RIDGE_REFINEMENT_GEOMETRY_SPECS.get(region_key, ())
        for label_suffix, axis_deltas, note in region_specs:
            _append_geometry_seed(
                seeds=seeds,
                seen=seen,
                label=f"{region_key}_{label_suffix}",
                choice=_offset_choice(
                    base_choice=choice,
                    axis_deltas=axis_deltas,
                    axis_sizes=axis_sizes,
                ),
                note=f"{region_key} ridge refinement: {note}",
                baseline=baseline,
                map_config=map_config,
            )

    return tuple(seeds)


def select_balanced_compromise_candidate(
    feasible_candidates: tuple[MaterialProxyCandidate, ...],
    *,
    mass_first_candidate: MaterialProxyCandidate | None,
    margin_first_candidate: MaterialProxyCandidate | None,
) -> MaterialProxyCandidate | None:
    if not feasible_candidates:
        return None

    masses = np.asarray([candidate.tube_mass_kg for candidate in feasible_candidates], dtype=float)
    margins = np.asarray([candidate.candidate_margin_m for candidate in feasible_candidates], dtype=float)
    mass_min = float(np.min(masses))
    mass_max = float(np.max(masses))
    margin_min = float(np.min(margins))
    margin_max = float(np.max(margins))
    mass_span = max(mass_max - mass_min, 0.0)
    margin_span = max(margin_max - margin_min, 0.0)

    excluded_signatures = set()
    if mass_first_candidate is not None:
        excluded_signatures.add(_choice_signature(mass_first_candidate))
    if margin_first_candidate is not None:
        excluded_signatures.add(_choice_signature(margin_first_candidate))

    candidate_pool = [
        candidate for candidate in feasible_candidates if _choice_signature(candidate) not in excluded_signatures
    ]
    if not candidate_pool:
        candidate_pool = list(feasible_candidates)

    def _score(candidate: MaterialProxyCandidate) -> tuple[float, float, float, float, float]:
        mass_score = 1.0 if mass_span <= 1.0e-12 else (mass_max - candidate.tube_mass_kg) / mass_span
        margin_score = 1.0 if margin_span <= 1.0e-12 else (candidate.candidate_margin_m - margin_min) / margin_span
        harmonic_score = (
            0.0
            if (mass_score + margin_score) <= 1.0e-12
            else (2.0 * mass_score * margin_score) / (mass_score + margin_score)
        )
        balance_gap = abs(mass_score - margin_score)
        return (
            float(harmonic_score),
            float(-balance_gap),
            float(mass_score + margin_score),
            float(candidate.candidate_margin_m),
            float(-candidate.tube_mass_kg),
        )

    return max(candidate_pool, key=_score)


def select_mass_first_candidate(
    feasible_candidates: tuple[MaterialProxyCandidate, ...],
) -> MaterialProxyCandidate | None:
    if not feasible_candidates:
        return None
    return min(
        feasible_candidates,
        key=lambda cand: (cand.tube_mass_kg, cand.psi_u_all_m, -cand.candidate_margin_m),
    )


def select_margin_first_candidate(
    feasible_candidates: tuple[MaterialProxyCandidate, ...],
) -> MaterialProxyCandidate | None:
    if not feasible_candidates:
        return None
    return max(
        feasible_candidates,
        key=lambda cand: (cand.candidate_margin_m, -cand.tube_mass_kg, -cand.psi_u_all_m),
    )


def build_pareto_frontier_candidates(
    feasible_candidates: tuple[MaterialProxyCandidate, ...],
) -> tuple[MaterialProxyCandidate, ...]:
    frontier: list[MaterialProxyCandidate] = []
    for idx, candidate in enumerate(feasible_candidates):
        dominated = False
        for other_idx, other in enumerate(feasible_candidates):
            if idx == other_idx:
                continue
            lighter_or_equal = other.tube_mass_kg <= candidate.tube_mass_kg + 1.0e-12
            stronger_or_equal = other.candidate_margin_m >= candidate.candidate_margin_m - 1.0e-12
            strictly_better = (
                other.tube_mass_kg < candidate.tube_mass_kg - 1.0e-12
                or other.candidate_margin_m > candidate.candidate_margin_m + 1.0e-12
            )
            if lighter_or_equal and stronger_or_equal and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return tuple(sorted(frontier, key=lambda cand: (cand.tube_mass_kg, -cand.candidate_margin_m, cand.psi_u_all_m)))


def _choice_l1_distance(
    lhs: tuple[int, int, int, int, int],
    rhs: tuple[int, int, int, int, int],
) -> int:
    return sum(abs(int(a) - int(b)) for a, b in zip(lhs, rhs))


def _count_pairs(values: list[str]) -> tuple[tuple[str, int], ...]:
    counter = Counter(values)
    return tuple(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def build_representative_regions(
    *,
    feasible_candidates: tuple[MaterialProxyCandidate, ...],
    mass_first_candidate: MaterialProxyCandidate | None,
    margin_first_candidate: MaterialProxyCandidate | None,
    balanced_candidate: MaterialProxyCandidate | None,
) -> tuple[JointRepresentativeRegion, ...]:
    regions: list[JointRepresentativeRegion] = []
    for region_key, representative in (
        ("mass_first", mass_first_candidate),
        ("margin_first", margin_first_candidate),
        ("balanced", balanced_candidate),
    ):
        if representative is None:
            continue
        local_feasible = tuple(
            candidate
            for candidate in feasible_candidates
            if _choice_l1_distance(candidate.geometry_choice, representative.geometry_choice)
            <= REPRESENTATIVE_REGION_RADIUS_L1
        )
        if not local_feasible:
            continue
        local_pareto = build_pareto_frontier_candidates(local_feasible)
        local_pool = local_pareto or local_feasible
        local_mass = select_mass_first_candidate(local_pool)
        local_margin = select_margin_first_candidate(local_pool)
        local_balanced = select_balanced_compromise_candidate(
            local_pool,
            mass_first_candidate=local_mass,
            margin_first_candidate=local_margin,
        )
        regions.append(
            JointRepresentativeRegion(
                region_key=region_key,
                center_geometry_choice=representative.geometry_choice,
                support_radius_l1=REPRESENTATIVE_REGION_RADIUS_L1,
                geometry_choice_count=len({candidate.geometry_choice for candidate in local_feasible}),
                feasible_candidate_count=len(local_feasible),
                pareto_candidate_count=len(local_pareto),
                best_mass_candidate_feasible=local_mass,
                best_margin_candidate_feasible=local_margin,
                balanced_compromise_candidate_feasible=local_balanced,
                pareto_main_family_counts=_count_pairs(
                    [candidate.main_family_key for candidate in local_pool]
                ),
                pareto_rear_outboard_pkg_counts=_count_pairs(
                    [candidate.rear_outboard_pkg_key for candidate in local_pool]
                ),
            )
        )
    return tuple(regions)


def _load_v2m_selected_choice(path: Path) -> tuple[int, int, int, int, int]:
    obj = json.loads(path.read_text())
    selected = obj["outcome"]["selected"]
    return tuple(int(value) for value in selected["choice_indices"])


def _load_v2m_reference(path: Path) -> dict[str, object]:
    obj = json.loads(path.read_text())
    outcome = obj["outcome"]
    selected = outcome["selected"]
    dual_limit = (
        None
        if selected.get("dual_displacement_limit_m") is None
        else float(selected["dual_displacement_limit_m"])
    )
    candidate_margin_m = (
        None
        if dual_limit is None
        else float(dual_limit) - float(selected["psi_u_all_m"])
    )
    return {
        "path": str(path),
        "success": bool(outcome["success"]),
        "feasible": bool(outcome["feasible"]),
        "total_wall_time_s": float(outcome["total_wall_time_s"]),
        "tube_mass_kg": float(selected["tube_mass_kg"]),
        "total_structural_mass_kg": float(selected["total_structural_mass_kg"]),
        "raw_main_tip_m": float(selected["raw_main_tip_m"]),
        "raw_rear_tip_m": float(selected["raw_rear_tip_m"]),
        "raw_max_uz_m": float(selected["raw_max_uz_m"]),
        "raw_max_location": str(selected["raw_max_location"]),
        "psi_u_all_m": float(selected["psi_u_all_m"]),
        "psi_u_rear_m": float(selected["psi_u_rear_m"]),
        "psi_u_rear_outboard_m": float(selected["psi_u_rear_outboard_m"]),
        "dual_displacement_limit_m": dual_limit,
        "candidate_margin_m": candidate_margin_m,
        "overall_hard_feasible": bool(selected["overall_hard_feasible"]),
        "overall_optimizer_candidate_feasible": bool(selected["overall_optimizer_candidate_feasible"]),
        "choice_indices": tuple(int(value) for value in selected["choice_indices"]),
        "manufacturing_variables": dict(selected["manufacturing_variables"]),
        "design_mm": dict(selected["design_mm"]),
    }


def build_joint_search_space(
    *,
    geometry_seeds,
    main_packages,
    rear_outboard_packages,
) -> tuple[tuple[object, object, object, int, int], ...]:
    rows = []
    for geometry_seed, (main_index, main_package), (outboard_index, rear_outboard_package) in product(
        geometry_seeds,
        enumerate(main_packages),
        enumerate(rear_outboard_packages),
    ):
        rows.append(
            (
                geometry_seed,
                main_package,
                rear_outboard_package,
                int(main_index),
                int(outboard_index),
            )
        )
    return tuple(rows)


def build_joint_choice_indices(
    *,
    geometry_choice: tuple[int, int, int, int, int],
    main_family_index: int,
    rear_outboard_index: int,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        int(geometry_choice[0]),
        int(geometry_choice[1]),
        int(geometry_choice[2]),
        int(geometry_choice[3]),
        int(geometry_choice[4]),
        int(main_family_index),
        int(rear_outboard_index),
    )


def _evaluate_joint_search_grid(
    *,
    evaluator: MaterialProxyEvaluator,
    geometry_seeds: tuple[GeometrySeed, ...],
    main_packages,
    rear_ref,
    rear_outboard_packages,
    source: str,
) -> dict[tuple[str, str, str], tuple[int, int]]:
    best_index_map: dict[tuple[str, str, str], tuple[int, int]] = {}
    for geometry_seed, main_package, outboard_package, main_index, outboard_index in build_joint_search_space(
        geometry_seeds=geometry_seeds,
        main_packages=main_packages,
        rear_outboard_packages=rear_outboard_packages,
    ):
        evaluator.evaluate(
            geometry_seed=geometry_seed,
            main_package=main_package,
            rear_package=rear_ref,
            rear_outboard_package=outboard_package,
            source=source,
        )
        best_index_map[(geometry_seed.label, main_package.key, outboard_package.key)] = (
            int(main_index),
            int(outboard_index),
        )
    return best_index_map


def _build_geometry_best_rows(
    *,
    geometry_seeds: tuple[GeometrySeed, ...],
    candidates: tuple[MaterialProxyCandidate, ...],
    best_index_map: dict[tuple[str, str, str], tuple[int, int]],
) -> tuple[JointGeometryBestRow, ...]:
    rows: list[JointGeometryBestRow] = []
    for geometry_seed in geometry_seeds:
        subset = [cand for cand in candidates if cand.geometry_label == geometry_seed.label]
        feasible = [cand for cand in subset if cand.overall_optimizer_candidate_feasible]
        selected = (
            min(feasible, key=lambda cand: (cand.tube_mass_kg, cand.psi_u_all_m, -cand.candidate_margin_m))
            if feasible
            else min(subset, key=lambda cand: (cand.hard_violation_score, cand.tube_mass_kg))
        )
        main_index, outboard_index = best_index_map[
            (geometry_seed.label, selected.main_family_key, selected.rear_outboard_pkg_key)
        ]
        rows.append(
            JointGeometryBestRow(
                geometry_label=geometry_seed.label,
                geometry_choice=geometry_seed.choice,
                joint_choice_indices=build_joint_choice_indices(
                    geometry_choice=geometry_seed.choice,
                    main_family_index=main_index,
                    rear_outboard_index=outboard_index,
                ),
                main_family_key=selected.main_family_key,
                rear_outboard_pkg_key=selected.rear_outboard_pkg_key,
                tube_mass_kg=float(selected.tube_mass_kg),
                psi_u_all_mm=_mm(selected.psi_u_all_m),
                candidate_margin_mm=_mm(selected.candidate_margin_m),
                candidate_feasible=bool(selected.overall_optimizer_candidate_feasible),
            )
        )
    return tuple(rows)


def _build_joint_material_outcome(
    *,
    search_strategy: str,
    geometry_seeds: tuple[GeometrySeed, ...],
    discovery_geometry_seed_count: int,
    support_geometry_seed_count: int,
    ridge_geometry_seed_count: int,
    search_space_size: int,
    total_start: float,
    reference_candidate: MaterialProxyCandidate,
    evaluator: MaterialProxyEvaluator,
    best_index_map: dict[tuple[str, str, str], tuple[int, int]],
) -> JointMaterialOutcome:
    geometry_best_rows = _build_geometry_best_rows(
        geometry_seeds=geometry_seeds,
        candidates=tuple(evaluator.archive.candidates),
        best_index_map=best_index_map,
    )

    best_violation = evaluator.archive.best_violation
    if best_violation is None:  # pragma: no cover - impossible when reference exists
        raise RuntimeError("Joint geometry/material search produced no candidates.")

    feasible_candidates = tuple(
        sorted(
            (cand for cand in evaluator.archive.candidates if cand.overall_optimizer_candidate_feasible),
            key=lambda cand: (cand.tube_mass_kg, cand.psi_u_all_m, -cand.candidate_margin_m),
        )
    )
    pareto_frontier = build_pareto_frontier_candidates(feasible_candidates)
    representative_pool = pareto_frontier or feasible_candidates
    best_mass_candidate_feasible = select_mass_first_candidate(representative_pool)
    best_margin_candidate_feasible = select_margin_first_candidate(representative_pool)
    balanced_compromise = select_balanced_compromise_candidate(
        representative_pool,
        mass_first_candidate=best_mass_candidate_feasible,
        margin_first_candidate=best_margin_candidate_feasible,
    )
    representative_regions = build_representative_regions(
        feasible_candidates=feasible_candidates,
        mass_first_candidate=best_mass_candidate_feasible,
        margin_first_candidate=best_margin_candidate_feasible,
        balanced_candidate=balanced_compromise,
    )
    selected_candidate = best_mass_candidate_feasible or best_violation

    return JointMaterialOutcome(
        success=bool(selected_candidate.overall_hard_feasible),
        feasible=bool(selected_candidate.overall_optimizer_candidate_feasible),
        message=str(selected_candidate.message),
        search_strategy=search_strategy,
        total_wall_time_s=float(perf_counter() - total_start),
        geometry_seed_count=len(geometry_seeds),
        discovery_geometry_seed_count=discovery_geometry_seed_count,
        support_geometry_seed_count=support_geometry_seed_count,
        ridge_geometry_seed_count=ridge_geometry_seed_count,
        evaluated_candidate_count=len(evaluator.archive.candidates),
        search_space_size=search_space_size,
        equivalent_analysis_calls=int(evaluator.equivalent_analysis_calls),
        production_analysis_calls=int(evaluator.production_analysis_calls),
        reference_candidate=reference_candidate,
        selected_candidate=selected_candidate,
        mass_first_candidate_feasible=best_mass_candidate_feasible,
        margin_first_candidate_feasible=best_margin_candidate_feasible,
        balanced_compromise_candidate_feasible=balanced_compromise,
        best_margin_candidate_feasible=best_margin_candidate_feasible,
        best_violation=best_violation,
        geometry_best_rows=geometry_best_rows,
        pareto_frontier_candidate_feasible=pareto_frontier,
        representative_regions=representative_regions,
        top_candidate_feasible=feasible_candidates[:TOP_K],
    )


def run_joint_material_search(
    *,
    search_strategy: str,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    mapped_loads: dict,
    export_loads: dict,
    map_config,
    geometry_seeds,
):
    catalog = build_default_material_proxy_catalog()
    rear_ref = catalog.rear_spar_family[0]
    ref_main = catalog.main_spar_family[0]
    ref_outboard = catalog.rear_outboard_reinforcement_pkg[0]

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
    reference_candidate = evaluator.evaluate(
        geometry_seed=geometry_seeds[0],
        main_package=ref_main,
        rear_package=rear_ref,
        rear_outboard_package=ref_outboard,
        source="joint_reference:selected_v2m",
    )
    best_index_map = _evaluate_joint_search_grid(
        evaluator=evaluator,
        geometry_seeds=tuple(geometry_seeds),
        main_packages=catalog.main_spar_family,
        rear_ref=rear_ref,
        rear_outboard_packages=catalog.rear_outboard_reinforcement_pkg,
        source="joint_promoted_grid",
    )

    return catalog, _build_joint_material_outcome(
        search_strategy=search_strategy,
        geometry_seeds=tuple(geometry_seeds),
        discovery_geometry_seed_count=len(geometry_seeds),
        support_geometry_seed_count=0,
        ridge_geometry_seed_count=0,
        search_space_size=len(geometry_seeds)
        * len(catalog.main_spar_family)
        * len(catalog.rear_outboard_reinforcement_pkg),
        total_start=total_start,
        reference_candidate=reference_candidate,
        evaluator=evaluator,
        best_index_map=best_index_map,
    )


def run_joint_material_workflow_search(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    mapped_loads: dict,
    export_loads: dict,
    map_config,
    baseline: BaselineDesign,
    selected_choice: tuple[int, int, int, int, int],
) -> tuple[tuple[GeometrySeed, ...], object, JointMaterialOutcome]:
    discovery_geometry_seeds = build_joint_geometry_seeds(
        strategy=EXPANDED_STRATEGY,
        selected_choice=selected_choice,
        baseline=baseline,
        map_config=map_config,
    )
    catalog = build_default_material_proxy_catalog()
    rear_ref = catalog.rear_spar_family[0]
    ref_main = catalog.main_spar_family[0]
    ref_outboard = catalog.rear_outboard_reinforcement_pkg[0]
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
    reference_candidate = evaluator.evaluate(
        geometry_seed=discovery_geometry_seeds[0],
        main_package=ref_main,
        rear_package=rear_ref,
        rear_outboard_package=ref_outboard,
        source="joint_reference:selected_v2m",
    )
    discovery_index_map = _evaluate_joint_search_grid(
        evaluator=evaluator,
        geometry_seeds=discovery_geometry_seeds,
        main_packages=catalog.main_spar_family,
        rear_ref=rear_ref,
        rear_outboard_packages=catalog.rear_outboard_reinforcement_pkg,
        source="joint_promoted_grid:discovery",
    )
    discovery_outcome = _build_joint_material_outcome(
        search_strategy=EXPANDED_STRATEGY,
        geometry_seeds=discovery_geometry_seeds,
        discovery_geometry_seed_count=len(discovery_geometry_seeds),
        support_geometry_seed_count=0,
        ridge_geometry_seed_count=0,
        search_space_size=len(discovery_geometry_seeds)
        * len(catalog.main_spar_family)
        * len(catalog.rear_outboard_reinforcement_pkg),
        total_start=total_start,
        reference_candidate=reference_candidate,
        evaluator=evaluator,
        best_index_map=discovery_index_map,
    )
    representative_centres = tuple(
        (region_key, candidate.geometry_choice)
        for region_key, candidate in (
            ("mass_first", discovery_outcome.mass_first_candidate_feasible),
            ("margin_first", discovery_outcome.margin_first_candidate_feasible),
            ("balanced", discovery_outcome.balanced_compromise_candidate_feasible),
        )
        if candidate is not None
    )
    support_geometry_seeds = build_representative_support_geometry_seeds(
        representative_centres=representative_centres,
        baseline=baseline,
        map_config=map_config,
        existing_choices={seed.choice for seed in discovery_geometry_seeds},
    )
    support_index_map = {}
    if support_geometry_seeds:
        support_index_map = _evaluate_joint_search_grid(
            evaluator=evaluator,
            geometry_seeds=support_geometry_seeds,
            main_packages=catalog.main_spar_family,
            rear_ref=rear_ref,
            rear_outboard_packages=catalog.rear_outboard_reinforcement_pkg,
            source="joint_promoted_grid:representative_support",
        )
    support_combined_geometry_seeds = tuple(discovery_geometry_seeds) + tuple(support_geometry_seeds)
    support_combined_index_map = {**discovery_index_map, **support_index_map}
    support_outcome = _build_joint_material_outcome(
        search_strategy=WORKFLOW_STRATEGY,
        geometry_seeds=support_combined_geometry_seeds,
        discovery_geometry_seed_count=len(discovery_geometry_seeds),
        support_geometry_seed_count=len(support_geometry_seeds),
        ridge_geometry_seed_count=0,
        search_space_size=len(support_combined_geometry_seeds)
        * len(catalog.main_spar_family)
        * len(catalog.rear_outboard_reinforcement_pkg),
        total_start=total_start,
        reference_candidate=reference_candidate,
        evaluator=evaluator,
        best_index_map=support_combined_index_map,
    )
    ridge_geometry_seeds = build_ridge_refinement_geometry_seeds(
        representative_centres=tuple(
            (region_key, candidate.geometry_choice)
            for region_key, candidate in (
                ("margin_first", support_outcome.margin_first_candidate_feasible),
                ("balanced", support_outcome.balanced_compromise_candidate_feasible),
            )
            if candidate is not None
        ),
        baseline=baseline,
        map_config=map_config,
        existing_choices={seed.choice for seed in support_combined_geometry_seeds},
    )
    ridge_index_map = {}
    if ridge_geometry_seeds:
        ridge_index_map = _evaluate_joint_search_grid(
            evaluator=evaluator,
            geometry_seeds=ridge_geometry_seeds,
            main_packages=catalog.main_spar_family,
            rear_ref=rear_ref,
            rear_outboard_packages=catalog.rear_outboard_reinforcement_pkg,
            source="joint_promoted_grid:ridge_refinement",
        )
    combined_geometry_seeds = support_combined_geometry_seeds + tuple(ridge_geometry_seeds)
    combined_index_map = {**support_combined_index_map, **ridge_index_map}
    outcome = _build_joint_material_outcome(
        search_strategy=WORKFLOW_STRATEGY,
        geometry_seeds=combined_geometry_seeds,
        discovery_geometry_seed_count=len(discovery_geometry_seeds),
        support_geometry_seed_count=len(support_geometry_seeds),
        ridge_geometry_seed_count=len(ridge_geometry_seeds),
        search_space_size=len(combined_geometry_seeds)
        * len(catalog.main_spar_family)
        * len(catalog.rear_outboard_reinforcement_pkg),
        total_start=total_start,
        reference_candidate=reference_candidate,
        evaluator=evaluator,
        best_index_map=combined_index_map,
    )
    return combined_geometry_seeds, catalog, outcome


def run_joint_material_strategy(
    *,
    search_strategy: str,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    mapped_loads: dict,
    export_loads: dict,
    map_config,
    baseline: BaselineDesign,
    selected_choice: tuple[int, int, int, int, int],
) -> tuple[tuple[GeometrySeed, ...], object, JointMaterialOutcome]:
    if search_strategy == WORKFLOW_STRATEGY:
        return run_joint_material_workflow_search(
            cfg=cfg,
            aircraft=aircraft,
            materials_db=materials_db,
            mapped_loads=mapped_loads,
            export_loads=export_loads,
            map_config=map_config,
            baseline=baseline,
            selected_choice=selected_choice,
        )

    geometry_seeds = build_joint_geometry_seeds(
        strategy=search_strategy,
        selected_choice=selected_choice,
        baseline=baseline,
        map_config=map_config,
    )
    catalog, outcome = run_joint_material_search(
        search_strategy=search_strategy,
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        mapped_loads=mapped_loads,
        export_loads=export_loads,
        map_config=map_config,
        geometry_seeds=geometry_seeds,
    )
    return tuple(geometry_seeds), catalog, outcome


def build_report_text(
    *,
    config_path: Path,
    design_report: Path,
    v2m_summary_json: Path,
    v2m_reference: dict[str, object],
    geometry_seeds,
    catalog,
    cfg,
    materials_db: MaterialDB,
    outcome: JointMaterialOutcome,
) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    catalog_summary = catalog_to_summary_dict(catalog=catalog, cfg=cfg, materials_db=materials_db)
    selected = outcome.selected_candidate
    best_margin = outcome.best_margin_candidate_feasible

    main_packages = catalog_summary["main_spar_family"]["packages"]
    outboard_packages = catalog_summary["rear_outboard_reinforcement_pkg"]["packages"]
    main_index_map = {pkg["key"]: idx for idx, pkg in enumerate(main_packages)}
    outboard_index_map = {pkg["key"]: idx for idx, pkg in enumerate(outboard_packages)}

    lines: list[str] = []
    lines.append("=" * 120)
    lines.append("Direct Dual-Beam V2.m++ Joint Geometry + Promoted-Material Discrete Search")
    lines.append("=" * 120)
    lines.append(f"Generated                     : {timestamp}")
    lines.append(f"Config                        : {config_path}")
    lines.append(f"Design report                 : {design_report}")
    lines.append(f"Reference V2.m++ summary      : {v2m_summary_json}")
    lines.append(f"Geometry catalog profile      : {DEFAULT_CATALOG_PROFILE}")
    lines.append("")
    lines.append("Search strategy:")
    lines.append("  Promote only main_spar_family and rear_outboard_reinforcement_pkg to formal discrete axes.")
    lines.append("  Keep rear_spar_family fixed at rear_ref for this phase.")
    if outcome.search_strategy == COMPACT_STRATEGY:
        lines.append("  Search only the selected V2.m++ point plus a compact nearby geometry neighborhood.")
    elif outcome.search_strategy == EXPANDED_STRATEGY:
        lines.append("  Search the selected V2.m++ point, valid one-step neighbors, a few two-step checks, and a small set of pairwise couplings.")
    else:
        lines.append("  Workflow stage 1: expanded discovery around the selected V2.m++ point.")
        lines.append("  Workflow stage 2: compact local support neighborhoods around the discovered mass-first / margin-first / balanced representatives.")
        lines.append("  Workflow stage 3: a very small ridge-refinement set along the current margin / balanced tradeoff branch.")
    lines.append(f"  Strategy                     : {outcome.search_strategy}")
    lines.append(
        f"  Search-space size            : {outcome.search_space_size} = {outcome.geometry_seed_count} geometry seeds x "
        f"{len(main_packages)} main families x {len(outboard_packages)} outboard packages"
    )
    if outcome.search_strategy == WORKFLOW_STRATEGY:
        lines.append(f"  Discovery geometry seeds     : {outcome.discovery_geometry_seed_count}")
        lines.append(f"  Support geometry seeds       : {outcome.support_geometry_seed_count}")
        lines.append(f"  Ridge geometry seeds         : {outcome.ridge_geometry_seed_count}")
    lines.append("")
    lines.append("Promoted axes:")
    for axis_name in ("main_spar_family", "rear_outboard_reinforcement_pkg"):
        axis_summary = catalog_summary[axis_name]
        lines.append(
            f"  {axis_name}: integration={axis_summary['integration_mode']}  promotion={axis_summary['promotion_state']}"
        )
        for package in axis_summary["packages"]:
            lines.append(
                "    "
                f"{package['key']:24s} E={package['E_eff_pa'] / 1.0e9:7.2f} GPa  "
                f"G={package['G_eff_pa'] / 1.0e9:6.2f} GPa  "
                f"rho={package['density_eff_kgpm3']:7.1f}  "
                f"allow={package['allowable_eff_pa'] / 1.0e6:7.1f} MPa"
            )
            lines.append(f"      {package['description']}")
    lines.append("")
    lines.append("Geometry neighborhood:")
    for seed in geometry_seeds:
        lines.append(f"  {seed.label:22s} choice={seed.choice}  {seed.note}")
    lines.append("")
    lines.append("Reference pure-geometry V2.m++ selected point:")
    lines.append(f"  choice indices              : {v2m_reference['choice_indices']}")
    lines.append(f"  mass                        : {v2m_reference['tube_mass_kg']:11.3f} kg")
    lines.append(f"  raw main tip                : {_mm(v2m_reference['raw_main_tip_m']):11.3f} mm")
    lines.append(f"  raw rear tip                : {_mm(v2m_reference['raw_rear_tip_m']):11.3f} mm")
    lines.append(f"  raw max |UZ|                : {_mm(v2m_reference['raw_max_uz_m']):11.3f} mm")
    lines.append(f"  psi_u_all                   : {_mm(v2m_reference['psi_u_all_m']):11.3f} mm")
    lines.append(f"  candidate margin            : {_mm(v2m_reference['candidate_margin_m']):11.3f} mm")
    lines.append(
        f"  hard / candidate            : {v2m_reference['overall_hard_feasible']} / "
        f"{v2m_reference['overall_optimizer_candidate_feasible']}"
    )
    lines.append("")
    lines.append("Run summary:")
    lines.append(f"  success                     : {outcome.success}")
    lines.append(f"  feasible                    : {outcome.feasible}")
    lines.append(f"  total wall time             : {outcome.total_wall_time_s:.3f} s")
    lines.append(f"  evaluated candidates        : {outcome.evaluated_candidate_count}")
    lines.append(f"  Pareto-feasible candidates  : {len(outcome.pareto_frontier_candidate_feasible)}")
    lines.append(f"  equivalent analysis calls   : {outcome.equivalent_analysis_calls}")
    lines.append(f"  production analysis calls   : {outcome.production_analysis_calls}")
    lines.append("")
    _append_candidate_block(
        lines=lines,
        title="Mass-first candidate-feasible representative:",
        candidate=outcome.mass_first_candidate_feasible,
        main_index_map=main_index_map,
        outboard_index_map=outboard_index_map,
    )
    _append_candidate_block(
        lines=lines,
        title="Margin-first candidate-feasible representative:",
        candidate=best_margin,
        main_index_map=main_index_map,
        outboard_index_map=outboard_index_map,
    )
    _append_candidate_block(
        lines=lines,
        title="Balanced compromise candidate-feasible representative:",
        candidate=outcome.balanced_compromise_candidate_feasible,
        main_index_map=main_index_map,
        outboard_index_map=outboard_index_map,
    )
    if outcome.pareto_frontier_candidate_feasible:
        lines.append("Pareto-feasible tradeoff frontier:")
        lines.append("  geometry                 combo                         mass[kg]   psi[mm]   margin[mm]")
        for candidate in outcome.pareto_frontier_candidate_feasible:
            combo = f"{candidate.main_family_key}/{candidate.rear_outboard_pkg_key}"
            lines.append(
                f"  {candidate.geometry_label:22s} {combo:28s} {candidate.tube_mass_kg:8.3f} "
                f"{_mm(candidate.psi_u_all_m):9.3f} {_mm(candidate.candidate_margin_m):11.3f}"
            )
        lines.append("")
    if outcome.representative_regions:
        lines.append("Representative-region stability (evaluated local geometry L1 radius <= 1):")
        for region in outcome.representative_regions:
            lines.append(
                f"  {region.region_key:12s} center={region.center_geometry_choice}  "
                f"geometries={region.geometry_choice_count}  feasible={region.feasible_candidate_count}  "
                f"pareto={region.pareto_candidate_count}"
            )
            if region.best_mass_candidate_feasible is not None:
                lines.append(
                    "    "
                    f"local mass-first     : {region.best_mass_candidate_feasible.main_family_key}/"
                    f"{region.best_mass_candidate_feasible.rear_outboard_pkg_key}  "
                    f"{region.best_mass_candidate_feasible.tube_mass_kg:8.3f} kg  "
                    f"margin={_mm(region.best_mass_candidate_feasible.candidate_margin_m):8.3f} mm"
                )
            if region.best_margin_candidate_feasible is not None:
                lines.append(
                    "    "
                    f"local margin-first   : {region.best_margin_candidate_feasible.main_family_key}/"
                    f"{region.best_margin_candidate_feasible.rear_outboard_pkg_key}  "
                    f"{region.best_margin_candidate_feasible.tube_mass_kg:8.3f} kg  "
                    f"margin={_mm(region.best_margin_candidate_feasible.candidate_margin_m):8.3f} mm"
                )
            if region.balanced_compromise_candidate_feasible is not None:
                lines.append(
                    "    "
                    f"local balanced       : {region.balanced_compromise_candidate_feasible.main_family_key}/"
                    f"{region.balanced_compromise_candidate_feasible.rear_outboard_pkg_key}  "
                    f"{region.balanced_compromise_candidate_feasible.tube_mass_kg:8.3f} kg  "
                    f"margin={_mm(region.balanced_compromise_candidate_feasible.candidate_margin_m):8.3f} mm"
                )
            lines.append(
                f"    local pareto main family   : {_format_count_pairs(region.pareto_main_family_counts)}"
            )
            lines.append(
                f"    local pareto outboard pkg  : {_format_count_pairs(region.pareto_rear_outboard_pkg_counts)}"
            )
        lines.append("")
    lines.append("Best promoted-material combination by geometry seed:")
    lines.append("  geometry                 joint choice                  mass[kg]   psi[mm]   margin[mm]   cand")
    for row in outcome.geometry_best_rows:
        combo = f"{row.main_family_key}/{row.rear_outboard_pkg_key}"
        lines.append(
            f"  {row.geometry_label:22s} {combo:27s} {row.tube_mass_kg:8.3f} "
            f"{row.psi_u_all_mm:9.3f} {row.candidate_margin_mm:11.3f} {str(row.candidate_feasible):>5s}"
        )
    lines.append("")
    lines.append("Delta (selected joint candidate - pure-geometry V2.m++ selected point):")
    lines.append(
        f"  mass delta                   {selected.tube_mass_kg - float(v2m_reference['tube_mass_kg']):+11.3f} kg"
    )
    lines.append(
        f"  psi_u_all delta              {_signed_mm_delta(selected.psi_u_all_m - float(v2m_reference['psi_u_all_m'])):+11.3f} mm"
    )
    lines.append(
        f"  candidate margin delta       "
        f"{_signed_mm_delta(selected.candidate_margin_m - float(v2m_reference['candidate_margin_m'] or 0.0)):+11.3f} mm"
    )
    lines.append(
        f"  wall-time delta              {outcome.total_wall_time_s - float(v2m_reference['total_wall_time_s']):+11.3f} s"
    )
    return "\n".join(lines) + "\n"


def build_summary_json(
    *,
    config_path: Path,
    design_report: Path,
    v2m_summary_json: Path,
    v2m_reference: dict[str, object],
    geometry_seeds,
    catalog,
    cfg,
    materials_db: MaterialDB,
    outcome: JointMaterialOutcome,
) -> dict[str, object]:
    catalog_summary = catalog_to_summary_dict(catalog=catalog, cfg=cfg, materials_db=materials_db)
    main_packages = catalog_summary["main_spar_family"]["packages"]
    outboard_packages = catalog_summary["rear_outboard_reinforcement_pkg"]["packages"]
    main_index_map = {pkg["key"]: idx for idx, pkg in enumerate(main_packages)}
    outboard_index_map = {pkg["key"]: idx for idx, pkg in enumerate(outboard_packages)}
    selected = outcome.selected_candidate
    selected_joint_choice = _candidate_joint_choice(
        candidate=selected,
        main_index_map=main_index_map,
        outboard_index_map=outboard_index_map,
    )

    def _representative_dict(candidate: MaterialProxyCandidate | None) -> dict[str, object] | None:
        if candidate is None:
            return None
        return {
            **candidate_to_summary_dict(candidate),
            "joint_choice_indices": list(
                _candidate_joint_choice(
                    candidate=candidate,
                    main_index_map=main_index_map,
                    outboard_index_map=outboard_index_map,
                )
            ),
        }

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "v2m_summary_json": str(v2m_summary_json),
        "search_strategy": {
            "geometry_seed_strategy": (
                "selected_plus_nearby_v2m_neighbors"
                if outcome.search_strategy == COMPACT_STRATEGY
                else (
                    "selected_plus_controlled_joint_neighbors"
                    if outcome.search_strategy == EXPANDED_STRATEGY
                    else "expanded_discovery_plus_representative_support_neighborhoods"
                )
            ),
            "strategy_name": outcome.search_strategy,
            "geometry_seed_count": len(geometry_seeds),
            "discovery_geometry_seed_count": outcome.discovery_geometry_seed_count,
            "support_geometry_seed_count": outcome.support_geometry_seed_count,
            "ridge_geometry_seed_count": outcome.ridge_geometry_seed_count,
            "representative_region_radius_l1": REPRESENTATIVE_REGION_RADIUS_L1,
            "promoted_axes": ["main_spar_family", "rear_outboard_reinforcement_pkg"],
            "fixed_axes": {"rear_spar_family": "rear_ref"},
            "search_space_size": outcome.search_space_size,
        },
        "geometry_seeds": [
            {
                "label": seed.label,
                "choice": list(seed.choice),
                "note": seed.note,
            }
            for seed in geometry_seeds
        ],
        "promoted_catalog": {
            "main_spar_family": catalog_summary["main_spar_family"],
            "rear_outboard_reinforcement_pkg": catalog_summary["rear_outboard_reinforcement_pkg"],
        },
        "reference_v2m_selected": v2m_reference,
        "outcome": {
            "success": outcome.success,
            "feasible": outcome.feasible,
            "message": outcome.message,
            "total_wall_time_s": outcome.total_wall_time_s,
            "evaluated_candidate_count": outcome.evaluated_candidate_count,
            "equivalent_analysis_calls": outcome.equivalent_analysis_calls,
            "production_analysis_calls": outcome.production_analysis_calls,
            "reference_candidate": candidate_to_summary_dict(outcome.reference_candidate),
            "selected_candidate": {
                **candidate_to_summary_dict(outcome.selected_candidate),
                "joint_choice_indices": list(selected_joint_choice),
            },
            "pareto_frontier_candidate_feasible": [
                _representative_dict(candidate) for candidate in outcome.pareto_frontier_candidate_feasible
            ],
            "representative_candidates": {
                "mass_first_feasible": _representative_dict(outcome.mass_first_candidate_feasible),
                "margin_first_feasible": _representative_dict(outcome.margin_first_candidate_feasible),
                "balanced_compromise": _representative_dict(outcome.balanced_compromise_candidate_feasible),
            },
            "representative_regions": {
                region.region_key: {
                    "center_geometry_choice": list(region.center_geometry_choice),
                    "support_radius_l1": region.support_radius_l1,
                    "geometry_choice_count": region.geometry_choice_count,
                    "feasible_candidate_count": region.feasible_candidate_count,
                    "pareto_candidate_count": region.pareto_candidate_count,
                    "best_mass_candidate_feasible": _representative_dict(region.best_mass_candidate_feasible),
                    "best_margin_candidate_feasible": _representative_dict(region.best_margin_candidate_feasible),
                    "balanced_compromise_candidate_feasible": _representative_dict(
                        region.balanced_compromise_candidate_feasible
                    ),
                    "pareto_main_family_counts": {
                        key: count for key, count in region.pareto_main_family_counts
                    },
                    "pareto_rear_outboard_pkg_counts": {
                        key: count for key, count in region.pareto_rear_outboard_pkg_counts
                    },
                }
                for region in outcome.representative_regions
            },
            "best_margin_candidate_feasible": candidate_to_summary_dict(
                outcome.best_margin_candidate_feasible
            ),
            "best_violation": candidate_to_summary_dict(outcome.best_violation),
            "geometry_best_rows": [asdict(row) for row in outcome.geometry_best_rows],
            "top_candidate_feasible": [candidate_to_summary_dict(candidate) for candidate in outcome.top_candidate_feasible],
        },
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run reduced joint geometry + promoted-material discrete search on top of V2.m++."
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
    parser.add_argument(
        "--strategy",
        choices=(COMPACT_STRATEGY, EXPANDED_STRATEGY, WORKFLOW_STRATEGY),
        default=DEFAULT_STRATEGY,
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
    v2m_reference = _load_v2m_reference(v2m_summary_json)

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

    _, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)

    geometry_seeds, catalog, outcome = run_joint_material_strategy(
        search_strategy=args.strategy,
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        mapped_loads=mapped_loads,
        export_loads=export_loads,
        map_config=map_config,
        baseline=baseline_design,
        selected_choice=selected_choice,
    )

    report_path = output_dir / "direct_dual_beam_v2m_joint_material_report.txt"
    report_path.write_text(
        build_report_text(
            config_path=config_path,
            design_report=design_report,
            v2m_summary_json=v2m_summary_json,
            v2m_reference=v2m_reference,
            geometry_seeds=geometry_seeds,
            catalog=catalog,
            cfg=cfg,
            materials_db=materials_db,
            outcome=outcome,
        ),
        encoding="utf-8",
    )

    json_path = output_dir / "direct_dual_beam_v2m_joint_material_summary.json"
    json_path.write_text(
        json.dumps(
            build_summary_json(
                config_path=config_path,
                design_report=design_report,
                v2m_summary_json=v2m_summary_json,
                v2m_reference=v2m_reference,
                geometry_seeds=geometry_seeds,
                catalog=catalog,
                cfg=cfg,
                materials_db=materials_db,
                outcome=outcome,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    selected = outcome.selected_candidate
    print("Direct dual-beam V2.m++ joint geometry + material search complete.")
    print(f"  Report              : {report_path}")
    print(f"  Summary JSON        : {json_path}")
    print(f"  Strategy            : {args.strategy}")
    print(f"  Success / feasible  : {outcome.success} / {outcome.feasible}")
    print(f"  Total wall time     : {outcome.total_wall_time_s:.3f} s")
    print(f"  Search-space size   : {outcome.search_space_size}")
    print(f"  Mass                : {selected.tube_mass_kg:.3f} kg")
    print(f"  psi_u_all           : {_mm(selected.psi_u_all_m):.3f} mm")
    print(f"  Material choice     : {selected.main_family_key} / {selected.rear_outboard_pkg_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
