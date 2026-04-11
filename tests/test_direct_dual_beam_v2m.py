from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.direct_dual_beam_v2m import (  # noqa: E402
    BaselineDesign,
    DEFAULT_CATALOG_PROFILE,
    LEGACY_CATALOG_PROFILE,
    TUNED_CATALOG_PROFILE,
    CandidateArchive,
    ManufacturingCandidate,
    ManufacturingMapConfig,
    build_manufacturing_map_config,
    design_from_manufacturing_choice,
    get_catalog_profile_values_mm,
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
        main_plateau_delta_catalog_m=(0.0, 0.0015, 0.002811),
        main_outboard_pair_delta_catalog_m=(0.0, 0.000306),
        rear_general_radius_delta_catalog_m=(0.0, 0.0004),
        rear_outboard_tip_delta_t_catalog_m=(0.0, 0.00009),
        global_wall_delta_t_catalog_m=(0.0, 0.00005),
        rear_outboard_mask=np.array([0.0, 0.0, 0.0, 0.0, 0.35, 1.0], dtype=float),
    )


def _candidate(
    *,
    mass_kg: float,
    psi_u_all_m: float,
    hard_feasible: bool,
    candidate_feasible: bool,
    source: str,
) -> ManufacturingCandidate:
    design = _baseline_design()
    return ManufacturingCandidate(
        choice=(0, 0, 0, 0, 0),
        source=source,
        message="ok",
        eval_wall_time_s=0.0,
        main_plateau_delta_m=0.0,
        main_outboard_pair_delta_m=0.0,
        rear_general_radius_delta_m=0.0,
        rear_outboard_tip_delta_t_m=0.0,
        global_wall_delta_t_m=0.0,
        main_t_seg_m=design.main_t_seg_m.copy(),
        main_r_seg_m=design.main_r_seg_m.copy(),
        rear_t_seg_m=design.rear_t_seg_m.copy(),
        rear_r_seg_m=design.rear_r_seg_m.copy(),
        tube_mass_kg=mass_kg,
        total_structural_mass_kg=mass_kg,
        raw_main_tip_m=2.3,
        raw_rear_tip_m=2.9,
        raw_max_uz_m=2.9,
        raw_max_location="rear node 60",
        psi_u_all_m=psi_u_all_m,
        psi_u_rear_m=psi_u_all_m,
        psi_u_rear_outboard_m=psi_u_all_m,
        dual_displacement_limit_m=2.5,
        equivalent_failure_index=-0.2,
        equivalent_buckling_index=-0.3,
        equivalent_tip_deflection_m=2.3,
        equivalent_twist_max_deg=0.8,
        equivalent_failure_passed=True,
        equivalent_buckling_passed=True,
        equivalent_tip_passed=True,
        equivalent_twist_passed=True,
        geometry_validity_succeeded=hard_feasible,
        analysis_succeeded=hard_feasible,
        overall_hard_feasible=hard_feasible,
        overall_optimizer_candidate_feasible=candidate_feasible,
        hard_failures=() if hard_feasible else ("geometry_validity",),
        candidate_failures=() if candidate_feasible else ("dual_displacement_candidate",),
        hard_margins={"equivalent_failure_margin": 0.1},
        hard_violation_score=0.0 if hard_feasible else 1.0,
        candidate_excess_m=max(psi_u_all_m - 2.5, 0.0),
    )


def test_design_from_manufacturing_choice_groups_segments_and_applies_tapered_rear_sleeve() -> None:
    baseline = _baseline_design()
    map_config = _map_config()

    main_t, main_r, rear_t, rear_r = design_from_manufacturing_choice(
        baseline=baseline,
        choice=(2, 1, 1, 1, 1),
        map_config=map_config,
    )

    assert np.allclose(main_r[:4], main_r[0])
    assert np.isclose(main_r[4] - baseline.main_r_seg_m[4], 0.002811 + 0.000306)
    assert np.isclose(main_r[5] - baseline.main_r_seg_m[5], 0.002811 + 0.000306)
    assert np.allclose(rear_r, 0.0104)
    assert np.allclose(main_t - baseline.main_t_seg_m, 0.00005)
    assert np.isclose(rear_t[4] - baseline.rear_t_seg_m[4], 0.00005 + 0.35 * 0.00009)
    assert np.isclose(rear_t[5] - baseline.rear_t_seg_m[5], 0.00005 + 0.00009)


def test_candidate_archive_prefers_candidate_feasible_then_hard_feasible_then_lower_violation() -> None:
    archive = CandidateArchive()
    bad = _candidate(
        mass_kg=8.5,
        psi_u_all_m=2.6,
        hard_feasible=False,
        candidate_feasible=False,
        source="bad",
    )
    hard_only = _candidate(
        mass_kg=9.1,
        psi_u_all_m=2.55,
        hard_feasible=True,
        candidate_feasible=False,
        source="hard_only",
    )
    candidate = _candidate(
        mass_kg=9.7,
        psi_u_all_m=2.48,
        hard_feasible=True,
        candidate_feasible=True,
        source="candidate",
    )

    archive.add(bad)
    archive.add(hard_only)
    archive.add(candidate)

    assert archive.best_candidate_feasible is candidate
    assert archive.best_hard_feasible is candidate
    assert archive.best_violation is candidate
    assert archive.selected is candidate


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        solver=SimpleNamespace(
            max_wall_thickness_m=0.002,
            max_thickness_to_radius_ratio=0.2,
            rear_min_inner_radius_m=0.003,
            max_radius_m=0.04,
        )
    )


def test_catalog_profiles_preserve_legacy_values_and_default_to_tuned() -> None:
    assert DEFAULT_CATALOG_PROFILE == TUNED_CATALOG_PROFILE
    assert get_catalog_profile_values_mm(LEGACY_CATALOG_PROFILE)["main_plateau_delta_mm"] == (
        0.0,
        1.5,
        2.3,
        2.811,
        3.4,
    )
    assert get_catalog_profile_values_mm(TUNED_CATALOG_PROFILE)["main_plateau_delta_mm"] == (
        0.0,
        1.5,
        2.3,
        2.7,
        2.8,
        2.95,
        3.4,
    )


def test_build_manufacturing_map_config_tuned_profile_refines_active_ladders() -> None:
    baseline = _baseline_design()

    legacy = build_manufacturing_map_config(baseline=baseline, cfg=_cfg(), catalog_profile=LEGACY_CATALOG_PROFILE)
    tuned = build_manufacturing_map_config(baseline=baseline, cfg=_cfg(), catalog_profile=TUNED_CATALOG_PROFILE)

    assert np.allclose(
        np.asarray(legacy.main_outboard_pair_delta_catalog_m) * 1000.0,
        [0.0, 0.15, 0.306, 0.45],
    )
    assert np.allclose(
        np.asarray(tuned.main_outboard_pair_delta_catalog_m) * 1000.0,
        [0.0, 0.03, 0.06, 0.09, 0.12, 0.225, 0.306],
    )
    assert np.allclose(
        np.asarray(tuned.rear_outboard_tip_delta_t_catalog_m) * 1000.0,
        [0.0, 0.03, 0.06, 0.075, 0.09, 0.105, 0.12],
    )
    assert np.allclose(np.asarray(tuned.global_wall_delta_t_catalog_m) * 1000.0, [0.0, 0.05])


def test_get_catalog_profile_values_mm_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="Unsupported catalog profile"):
        get_catalog_profile_values_mm("unknown")
