from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.direct_dual_beam_v2x import (  # noqa: E402
    BaselineDesign,
    CandidateArchive,
    DirectV2Candidate,
    ReducedMapConfig,
    candidate_priority_bucket,
    design_from_reduced_variables,
)


def _baseline_design() -> BaselineDesign:
    return BaselineDesign(
        main_t_seg_m=np.full(6, 0.0008, dtype=float),
        main_r_seg_m=np.array([0.030635, 0.030635, 0.030635, 0.030635, 0.022975, 0.015000]),
        rear_t_seg_m=np.full(6, 0.0008, dtype=float),
        rear_r_seg_m=np.full(6, 0.010000, dtype=float),
    )


def _map_config() -> ReducedMapConfig:
    mask = np.array([0.0, 0.0, 0.0, 0.0, 0.35, 1.0], dtype=float)
    return ReducedMapConfig(
        main_plateau_scale_upper=1.14,
        main_taper_fill_upper=0.24,
        main_tip_fill_upper=0.12,
        rear_radius_scale_upper=1.08,
        delta_t_global_max_m=0.004,
        delta_t_rear_outboard_max_m=0.0030,
        rear_outboard_mask=mask,
    )


def _candidate(
    *,
    mass_kg: float,
    psi_u_all_m: float,
    hard_feasible: bool,
    candidate_feasible: bool,
    hard_violation_score: float = 0.0,
    source: str = "test",
) -> DirectV2Candidate:
    design = _baseline_design()
    return DirectV2Candidate(
        z=np.zeros(6, dtype=float),
        source=source,
        message="ok",
        eval_wall_time_s=0.1,
        main_plateau_scale=1.0,
        main_taper_fill=0.0,
        main_tip_fill=0.0,
        rear_radius_scale=1.0,
        rear_outboard_fraction=0.0,
        wall_thickness_fraction=0.0,
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
        hard_violation_score=hard_violation_score,
        candidate_excess_m=max(psi_u_all_m - 2.5, 0.0),
    )


def test_design_from_reduced_variables_preserves_split_main_taper_and_tapered_rear_outboard_step() -> None:
    baseline = _baseline_design()
    map_config = _map_config()

    main_t, main_r, rear_t, rear_r = design_from_reduced_variables(
        baseline=baseline,
        z=np.array([0.67, 0.50, 0.17, 0.25, 1.0, 0.0]),
        map_config=map_config,
    )

    assert np.min(main_r[:-1] - main_r[1:]) >= 0.0
    assert np.min(rear_r[:-1] - rear_r[1:]) >= 0.0
    assert np.allclose(main_t - baseline.main_t_seg_m, main_t[0] - baseline.main_t_seg_m[0])
    assert main_r[4] > baseline.main_r_seg_m[4]
    assert main_r[5] > baseline.main_r_seg_m[5]
    assert np.isclose(rear_t[4] - rear_t[3], 0.35 * map_config.delta_t_rear_outboard_max_m)
    assert np.isclose(rear_t[5] - rear_t[4], 0.65 * map_config.delta_t_rear_outboard_max_m)
    assert rear_t[4] > rear_t[3]
    assert rear_t[5] > rear_t[4]


def test_candidate_archive_prefers_candidate_feasible_then_hard_feasible_then_lower_violation() -> None:
    archive = CandidateArchive()
    bad = _candidate(
        mass_kg=8.5,
        psi_u_all_m=2.45,
        hard_feasible=False,
        candidate_feasible=False,
        hard_violation_score=0.40,
        source="bad",
    )
    hard_only = _candidate(
        mass_kg=9.1,
        psi_u_all_m=2.70,
        hard_feasible=True,
        candidate_feasible=False,
        hard_violation_score=0.0,
        source="hard_only",
    )
    candidate = _candidate(
        mass_kg=9.7,
        psi_u_all_m=2.48,
        hard_feasible=True,
        candidate_feasible=True,
        hard_violation_score=0.0,
        source="candidate",
    )

    archive.add(bad)
    archive.add(hard_only)
    archive.add(candidate)

    assert candidate_priority_bucket(candidate) == 0
    assert candidate_priority_bucket(hard_only) == 1
    assert candidate_priority_bucket(bad) == 2
    assert archive.best_candidate_feasible is candidate
    assert archive.best_hard_feasible is candidate
    assert archive.best_violation is candidate
    assert archive.selected is candidate
