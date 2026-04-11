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
    build_joint_choice_indices,
    build_joint_geometry_seeds,
    build_joint_search_space,
)
from hpa_mdo.structure.material_proxy_catalog import build_default_material_proxy_catalog  # noqa: E402


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
