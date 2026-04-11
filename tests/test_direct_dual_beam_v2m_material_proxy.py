from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.direct_dual_beam_v2m import BaselineDesign, ManufacturingMapConfig  # noqa: E402
from scripts.direct_dual_beam_v2m_material_proxy import (  # noqa: E402
    MaterialScalePackage,
    apply_rear_outboard_reinforcement,
    build_default_material_proxy_catalog,
    build_geometry_seeds,
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


def test_default_material_proxy_catalog_keeps_first_batch_to_three_axes() -> None:
    catalog = build_default_material_proxy_catalog()

    assert [pkg.key for pkg in catalog.main_spar_family] == [
        "main_ref",
        "main_light_ud",
        "main_balanced_hm",
    ]
    assert [pkg.key for pkg in catalog.rear_spar_family] == [
        "rear_ref",
        "rear_balanced_shear",
        "rear_toughened_balance",
    ]
    assert [pkg.key for pkg in catalog.rear_outboard_reinforcement_pkg] == [
        "ob_none",
        "ob_light_wrap",
        "ob_balanced_sleeve",
        "ob_torsion_patch",
    ]


def test_build_geometry_seeds_stays_near_selected_v2m_choice() -> None:
    seeds = build_geometry_seeds(
        selected_choice=(4, 0, 0, 2, 0),
        baseline=_baseline_design(),
        map_config=_map_config(),
    )

    assert [seed.label for seed in seeds] == [
        "selected",
        "main_plateau_minus1",
        "rear_general_plus1",
        "rear_outboard_minus1",
        "rear_outboard_plus1",
    ]
    assert seeds[0].choice == (4, 0, 0, 2, 0)
    assert seeds[1].choice == (3, 0, 0, 2, 0)


def test_apply_rear_outboard_reinforcement_only_changes_outboard_elements() -> None:
    model = SimpleNamespace(
        element_lengths_m=np.array([1.0, 1.0], dtype=float),
        y_nodes_m=np.array([0.0, 1.0, 2.0], dtype=float),
        rear_young_pa=np.array([10.0, 10.0], dtype=float),
        rear_shear_pa=np.array([5.0, 5.0], dtype=float),
        rear_density_kgpm3=np.array([100.0, 100.0], dtype=float),
        rear_allowable_stress_pa=np.array([50.0, 50.0], dtype=float),
        rear_area_m2=np.array([2.0, 2.0], dtype=float),
        rear_mass_per_length_kgpm=np.array([200.0, 200.0], dtype=float),
    )
    package = MaterialScalePackage(
        key="test_pkg",
        label="Test package",
        scope="rear_outboard_reinforcement_pkg",
        young_scale=1.20,
        shear_scale=1.40,
        density_scale=1.10,
        allowable_scale=1.30,
        description="test",
    )

    tip_properties = apply_rear_outboard_reinforcement(
        model=model,
        rear_seg_lengths=[1.0, 1.0],
        rear_outboard_mask=np.array([0.0, 1.0], dtype=float),
        package=package,
    )

    np.testing.assert_allclose(model.rear_young_pa, np.array([10.0, 12.0]))
    np.testing.assert_allclose(model.rear_shear_pa, np.array([5.0, 7.0]))
    np.testing.assert_allclose(model.rear_density_kgpm3, np.array([100.0, 110.0]))
    np.testing.assert_allclose(model.rear_allowable_stress_pa, np.array([50.0, 65.0]))
    np.testing.assert_allclose(model.rear_mass_per_length_kgpm, np.array([200.0, 220.0]))
    assert tip_properties.E_eff_pa == 12.0
    assert tip_properties.G_eff_pa == 7.0
