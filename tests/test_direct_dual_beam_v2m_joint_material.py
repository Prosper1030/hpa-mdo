from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.direct_dual_beam_v2m import BaselineDesign, ManufacturingMapConfig  # noqa: E402
from scripts.direct_dual_beam_v2m_joint_material import (  # noqa: E402
    COMPACT_STRATEGY,
    EXPANDED_STRATEGY,
    JointRepresentativeRegion,
    build_ridge_refinement_geometry_seeds,
    build_pareto_frontier_candidates,
    build_joint_choice_indices,
    build_joint_geometry_seeds,
    build_joint_search_space,
    build_representative_regions,
    build_representative_support_geometry_seeds,
    select_balanced_compromise_candidate,
    select_margin_first_candidate,
    select_mass_first_candidate,
)
from scripts.direct_dual_beam_v2m_material_proxy import MaterialProxyCandidate  # noqa: E402
from hpa_mdo.structure.material_proxy_catalog import (  # noqa: E402
    EffectiveMaterialProperties,
    build_default_material_proxy_catalog,
)


def _baseline_design() -> BaselineDesign:
    return BaselineDesign(
        main_t_seg_m=np.full(6, 0.0008, dtype=float),
        main_r_seg_m=np.array([0.030635, 0.030635, 0.030635, 0.030635, 0.022975, 0.015000]),
        rear_t_seg_m=np.full(6, 0.0008, dtype=float),
        rear_r_seg_m=np.full(6, 0.010000, dtype=float),
    )


def _map_config() -> ManufacturingMapConfig:
    return ManufacturingMapConfig(
        main_plateau_delta_catalog_m=(0.0, 0.0015, 0.0023, 0.0028, 0.00295),
        main_outboard_pair_delta_catalog_m=(0.0, 0.00003, 0.00006, 0.00009),
        rear_general_radius_delta_catalog_m=(0.0, 0.0002, 0.0004),
        rear_outboard_tip_delta_t_catalog_m=(0.0, 0.00003, 0.00006, 0.00009, 0.00012),
        global_wall_delta_t_catalog_m=(0.0, 0.00005),
        rear_outboard_mask=np.array([0.0, 0.0, 0.0, 0.0, 0.35, 1.0], dtype=float),
    )


def _props() -> EffectiveMaterialProperties:
    return EffectiveMaterialProperties(
        E_eff_pa=100.0,
        G_eff_pa=10.0,
        density_eff_kgpm3=1600.0,
        allowable_eff_pa=500.0,
    )


def _candidate(
    *,
    geometry_label: str,
    geometry_choice: tuple[int, int, int, int, int],
    main_family_key: str,
    rear_outboard_pkg_key: str,
    tube_mass_kg: float,
    candidate_margin_m: float,
) -> MaterialProxyCandidate:
    props = _props()
    psi_u_all_m = 2.5 - candidate_margin_m
    return MaterialProxyCandidate(
        geometry_label=geometry_label,
        geometry_choice=geometry_choice,
        geometry_note="test",
        main_family_key=main_family_key,
        main_family_label=main_family_key,
        rear_family_key="rear_ref",
        rear_family_label="rear_ref",
        rear_outboard_pkg_key=rear_outboard_pkg_key,
        rear_outboard_pkg_label=rear_outboard_pkg_key,
        source="test",
        message="ok",
        eval_wall_time_s=0.1,
        tube_mass_kg=tube_mass_kg,
        total_structural_mass_kg=tube_mass_kg + 1.0,
        raw_main_tip_m=1.5,
        raw_rear_tip_m=2.0,
        raw_max_uz_m=2.0,
        raw_max_location="rear node 10",
        psi_u_all_m=psi_u_all_m,
        psi_u_rear_m=psi_u_all_m,
        psi_u_rear_outboard_m=psi_u_all_m,
        dual_displacement_limit_m=2.5,
        equivalent_failure_index=0.9,
        equivalent_buckling_index=0.8,
        equivalent_tip_deflection_m=2.0,
        equivalent_twist_max_deg=1.0,
        overall_hard_feasible=True,
        overall_optimizer_candidate_feasible=True,
        hard_failures=(),
        candidate_failures=(),
        hard_violation_score=0.0,
        candidate_margin_m=candidate_margin_m,
        main_family_properties=props,
        rear_family_properties=props,
        rear_outboard_tip_properties=props,
    )


def test_joint_search_space_uses_only_promoted_axes_and_small_geometry_neighborhood() -> None:
    catalog = build_default_material_proxy_catalog()
    geometry_seeds = build_joint_geometry_seeds(
        strategy=COMPACT_STRATEGY,
        selected_choice=(4, 0, 0, 2, 0),
        baseline=_baseline_design(),
        map_config=_map_config(),
    )

    search_space = build_joint_search_space(
        geometry_seeds=geometry_seeds,
        main_packages=catalog.main_spar_family,
        rear_outboard_packages=catalog.rear_outboard_reinforcement_pkg,
    )

    assert len(geometry_seeds) == 5
    assert len(search_space) == 5 * 3 * 4
    assert {row[1].key for row in search_space} == {
        "main_ref",
        "main_light_ud",
        "main_balanced_hm",
    }
    assert {row[2].key for row in search_space} == {
        "ob_none",
        "ob_light_wrap",
        "ob_balanced_sleeve",
        "ob_torsion_patch",
    }


def test_expanded_joint_geometry_strategy_is_bounded_and_adds_pairwise_neighbors() -> None:
    catalog = build_default_material_proxy_catalog()
    geometry_seeds = build_joint_geometry_seeds(
        strategy=EXPANDED_STRATEGY,
        selected_choice=(4, 0, 0, 2, 0),
        baseline=_baseline_design(),
        map_config=_map_config(),
    )

    search_space = build_joint_search_space(
        geometry_seeds=geometry_seeds,
        main_packages=catalog.main_spar_family,
        rear_outboard_packages=catalog.rear_outboard_reinforcement_pkg,
    )

    labels = {seed.label for seed in geometry_seeds}
    assert len(geometry_seeds) == 17
    assert len({seed.choice for seed in geometry_seeds}) == len(geometry_seeds)
    assert {
        "selected",
        "main_outboard_plus1",
        "global_wall_plus1",
        "main_plateau_minus2",
        "rear_general_plus2",
        "light_main_plus_rear_general",
        "rear_general_plus1_plus_outboard_plus1",
    } <= labels
    assert len(search_space) == 17 * 3 * 4


def test_joint_choice_indices_append_promoted_material_axes_after_geometry_axes() -> None:
    assert build_joint_choice_indices(
        geometry_choice=(4, 0, 0, 2, 0),
        main_family_index=1,
        rear_outboard_index=2,
    ) == (4, 0, 0, 2, 0, 1, 2)


def test_representative_support_geometry_seeds_expand_controlled_local_neighborhoods() -> None:
    support_seeds = build_representative_support_geometry_seeds(
        representative_centres=(
            ("mass_first", (3, 0, 0, 1, 0)),
            ("balanced", (4, 0, 2, 2, 0)),
        ),
        baseline=_baseline_design(),
        map_config=_map_config(),
        existing_choices={(4, 0, 0, 2, 0), (4, 0, 1, 2, 0)},
    )

    assert len({seed.choice for seed in support_seeds}) == len(support_seeds)
    assert (4, 0, 0, 2, 0) not in {seed.choice for seed in support_seeds}
    assert {seed.label for seed in support_seeds} >= {
        "mass_first_center",
        "balanced_center",
    }


def test_ridge_refinement_geometry_seeds_stay_small_and_follow_margin_balanced_branch() -> None:
    ridge_seeds = build_ridge_refinement_geometry_seeds(
        representative_centres=(
            ("margin_first", (4, 0, 1, 2, 1)),
            ("balanced", (4, 0, 2, 3, 0)),
        ),
        baseline=_baseline_design(),
        map_config=_map_config(),
        existing_choices={(4, 0, 1, 2, 1), (4, 0, 2, 3, 0)},
    )

    assert len(ridge_seeds) == 5
    assert len({seed.choice for seed in ridge_seeds}) == len(ridge_seeds)
    assert {seed.choice for seed in ridge_seeds} == {
        (4, 0, 2, 2, 1),
        (4, 0, 1, 3, 1),
        (4, 0, 2, 3, 1),
        (4, 0, 2, 4, 0),
        (4, 0, 2, 4, 1),
    }


def test_pareto_frontier_and_balanced_representative_focus_on_tradeoff_candidates() -> None:
    feasible_candidates = (
        _candidate(
            geometry_label="mass",
            geometry_choice=(3, 0, 0, 1, 0),
            main_family_key="main_light_ud",
            rear_outboard_pkg_key="ob_none",
            tube_mass_kg=10.00,
            candidate_margin_m=0.010,
        ),
        _candidate(
            geometry_label="mid",
            geometry_choice=(3, 0, 0, 2, 0),
            main_family_key="main_light_ud",
            rear_outboard_pkg_key="ob_light_wrap",
            tube_mass_kg=10.05,
            candidate_margin_m=0.030,
        ),
        _candidate(
            geometry_label="balanced",
            geometry_choice=(4, 0, 1, 2, 0),
            main_family_key="main_light_ud",
            rear_outboard_pkg_key="ob_balanced_sleeve",
            tube_mass_kg=10.08,
            candidate_margin_m=0.050,
        ),
        _candidate(
            geometry_label="margin",
            geometry_choice=(4, 0, 1, 2, 1),
            main_family_key="main_light_ud",
            rear_outboard_pkg_key="ob_balanced_sleeve",
            tube_mass_kg=10.30,
            candidate_margin_m=0.200,
        ),
        _candidate(
            geometry_label="dominated",
            geometry_choice=(4, 0, 1, 2, 0),
            main_family_key="main_ref",
            rear_outboard_pkg_key="ob_none",
            tube_mass_kg=10.12,
            candidate_margin_m=0.040,
        ),
    )

    pareto = build_pareto_frontier_candidates(feasible_candidates)
    mass_first = select_mass_first_candidate(pareto)
    margin_first = select_margin_first_candidate(pareto)
    balanced = select_balanced_compromise_candidate(
        pareto,
        mass_first_candidate=mass_first,
        margin_first_candidate=margin_first,
    )

    assert [candidate.geometry_label for candidate in pareto] == ["mass", "mid", "balanced", "margin"]
    assert mass_first is not None and mass_first.geometry_label == "mass"
    assert margin_first is not None and margin_first.geometry_label == "margin"
    assert balanced is not None and balanced.geometry_label == "balanced"


def test_representative_regions_summarize_local_material_roles() -> None:
    feasible_candidates = (
        _candidate(
            geometry_label="mass",
            geometry_choice=(3, 0, 0, 1, 0),
            main_family_key="main_light_ud",
            rear_outboard_pkg_key="ob_none",
            tube_mass_kg=10.00,
            candidate_margin_m=0.010,
        ),
        _candidate(
            geometry_label="mass_wrap",
            geometry_choice=(3, 0, 0, 2, 0),
            main_family_key="main_light_ud",
            rear_outboard_pkg_key="ob_light_wrap",
            tube_mass_kg=10.03,
            candidate_margin_m=0.025,
        ),
        _candidate(
            geometry_label="balanced",
            geometry_choice=(4, 0, 1, 2, 0),
            main_family_key="main_light_ud",
            rear_outboard_pkg_key="ob_balanced_sleeve",
            tube_mass_kg=10.08,
            candidate_margin_m=0.050,
        ),
        _candidate(
            geometry_label="balanced_plus",
            geometry_choice=(4, 0, 1, 2, 1),
            main_family_key="main_light_ud",
            rear_outboard_pkg_key="ob_balanced_sleeve",
            tube_mass_kg=10.20,
            candidate_margin_m=0.130,
        ),
        _candidate(
            geometry_label="balanced_alt",
            geometry_choice=(4, 0, 1, 1, 0),
            main_family_key="main_light_ud",
            rear_outboard_pkg_key="ob_torsion_patch",
            tube_mass_kg=10.11,
            candidate_margin_m=0.060,
        ),
    )

    regions = build_representative_regions(
        feasible_candidates=feasible_candidates,
        mass_first_candidate=feasible_candidates[0],
        margin_first_candidate=feasible_candidates[3],
        balanced_candidate=feasible_candidates[2],
    )
    region_map = {region.region_key: region for region in regions}

    mass_region = region_map["mass_first"]
    assert isinstance(mass_region, JointRepresentativeRegion)
    assert mass_region.geometry_choice_count == 2
    assert mass_region.best_mass_candidate_feasible is not None
    assert mass_region.best_mass_candidate_feasible.geometry_label == "mass"

    balanced_region = region_map["balanced"]
    assert balanced_region.geometry_choice_count == 3
    assert balanced_region.pareto_rear_outboard_pkg_counts[0][0] == "ob_balanced_sleeve"
    assert balanced_region.best_margin_candidate_feasible is not None
    assert balanced_region.best_margin_candidate_feasible.geometry_label == "balanced_plus"
