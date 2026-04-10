from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

from hpa_mdo.core.config import load_config
from hpa_mdo.structure.dual_beam_analysis import DualBeamAnalysisResult

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.dual_beam_refinement import (
    DualBeamCandidate,
    RefinementTargets,
    _build_bounds_from_warm_start,
    _candidate_margins,
    _is_feasible,
)


def _dummy_candidate() -> DualBeamCandidate:
    n = 6
    x = np.concatenate(
        [
            np.full(n, 0.0010),
            np.full(n, 0.0250),
            np.full(n, 0.0009),
            np.full(n, 0.0120),
        ]
    )
    dual = DualBeamAnalysisResult(
        disp_main=np.zeros((61, 6)),
        disp_rear=np.zeros((61, 6)),
        tip_deflection_main_m=2.7,
        tip_deflection_rear_m=3.1,
        max_vertical_displacement_m=3.1,
        max_vertical_spar="rear",
        max_vertical_node=60,
        spar_mass_half_kg=4.8,
        spar_mass_full_kg=9.6,
        total_applied_fz_n=910.0,
        support_reaction_fz_n=910.0,
        max_vm_main_pa=500e6,
        max_vm_rear_pa=450e6,
        failure_index=-0.2,
        loads_main_fz_n=np.zeros(61),
        loads_rear_fz_n=np.zeros(61),
        joint_node_indices=(0, 10, 20, 30, 40, 50, 60),
        wire_node_indices=(20, 40),
    )
    return DualBeamCandidate(
        x=x,
        main_t_seg_m=np.full(n, 0.0010),
        main_r_seg_m=np.full(n, 0.0250),
        rear_t_seg_m=np.full(n, 0.0009),
        rear_r_seg_m=np.full(n, 0.0120),
        eq_mass_kg=9.5,
        eq_tip_deflection_m=2.4,
        eq_failure_index=-0.3,
        eq_buckling_index=-0.4,
        dual=dual,
    )


def test_build_bounds_from_warm_start_respects_limits():
    cfg = load_config(Path(__file__).resolve().parents[1] / "configs" / "blackcat_004.yaml")
    warm = _dummy_candidate()
    lb, ub = _build_bounds_from_warm_start(
        cfg=cfg,
        warm=warm,
        radius_scale=0.20,
        thickness_scale=0.25,
    )

    assert lb.shape == warm.x.shape
    assert ub.shape == warm.x.shape
    assert np.all(ub > lb)
    assert np.all(lb <= warm.x + 1e-12)
    assert np.all(ub >= warm.x - 1e-12)


def test_candidate_margins_and_feasibility():
    cfg = load_config(Path(__file__).resolve().parents[1] / "configs" / "blackcat_004.yaml")
    warm = _dummy_candidate()
    targets = RefinementTargets(
        tip_main_limit_m=2.8,
        max_uz_limit_m=3.2,
        rear_main_tip_ratio_limit=1.2,
        mass_cap_kg=10.0,
    )
    margins = _candidate_margins(cand=warm, cfg=cfg, targets=targets)
    assert _is_feasible(margins)

    bad_targets = RefinementTargets(
        tip_main_limit_m=2.5,
        max_uz_limit_m=3.2,
        rear_main_tip_ratio_limit=1.2,
        mass_cap_kg=10.0,
    )
    bad_margins = _candidate_margins(cand=warm, cfg=cfg, targets=bad_targets)
    assert not _is_feasible(bad_margins)
