from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

from hpa_mdo.core.config import load_config
from hpa_mdo.structure.dual_beam_analysis import DualBeamAnalysisResult

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.direct_dual_beam_v1 import (  # noqa: E402
    build_targets_from_warm,
    design_from_reduced_scales,
    reduced_candidate_margins,
)
from scripts.dual_beam_refinement import DualBeamCandidate  # noqa: E402


def _dummy_candidate() -> DualBeamCandidate:
    n = 6
    main_t = np.full(n, 0.0008)
    main_r = np.array([0.030, 0.030, 0.030, 0.030, 0.023, 0.015])
    rear_t = np.full(n, 0.0008)
    rear_r = np.full(n, 0.010)
    x = np.concatenate([main_t, main_r, rear_t, rear_r])
    dual = DualBeamAnalysisResult(
        disp_main=np.zeros((61, 6)),
        disp_rear=np.zeros((61, 6)),
        tip_deflection_main_m=2.8,
        tip_deflection_rear_m=3.3,
        max_vertical_displacement_m=3.3,
        max_vertical_spar="rear",
        max_vertical_node=60,
        spar_mass_half_kg=4.7,
        spar_mass_full_kg=9.4,
        total_applied_fz_n=910.0,
        support_reaction_fz_n=910.0,
        max_vm_main_pa=500e6,
        max_vm_rear_pa=450e6,
        failure_index=-0.2,
        loads_main_fz_n=np.zeros(61),
        loads_rear_fz_n=np.zeros(61),
        joint_node_indices=(5, 16, 27, 38, 49),
        wire_node_indices=(27,),
    )
    return DualBeamCandidate(
        x=x,
        main_t_seg_m=main_t,
        main_r_seg_m=main_r,
        rear_t_seg_m=rear_t,
        rear_r_seg_m=rear_r,
        eq_mass_kg=9.4,
        eq_tip_deflection_m=2.4,
        eq_failure_index=-0.3,
        eq_buckling_index=-0.4,
        dual=dual,
    )


def test_design_from_reduced_scales_maps_taper_preserving_groups() -> None:
    cfg = load_config(Path(__file__).resolve().parents[1] / "configs" / "blackcat_004.yaml")
    warm = _dummy_candidate()

    main_t, main_r, rear_t, rear_r = design_from_reduced_scales(
        warm=warm,
        scales=np.array([1.05, 1.10, 1.025, 1.0]),
        cfg=cfg,
    )

    assert np.allclose(main_t, warm.main_t_seg_m)
    assert np.allclose(rear_t, warm.rear_t_seg_m)
    assert np.allclose(main_r[:4], warm.main_r_seg_m[:4] * 1.05)
    assert np.allclose(main_r[4:], warm.main_r_seg_m[4:] * 1.10)
    assert np.allclose(rear_r, warm.rear_r_seg_m * 1.025)
    assert np.min(main_r[:-1] - main_r[1:]) >= 0.0
    assert np.min(rear_r[:-1] - rear_r[1:]) >= 0.0


def test_reduced_margins_include_targets_and_manufacturing_taper() -> None:
    cfg = load_config(Path(__file__).resolve().parents[1] / "configs" / "blackcat_004.yaml")
    warm = _dummy_candidate()
    targets = build_targets_from_warm(
        warm=warm,
        tip_improve_frac=0.0,
        max_uz_improve_frac=0.0,
        rear_main_tip_ratio_slack=0.02,
        mass_cap_frac=0.10,
    )

    margins = reduced_candidate_margins(cand=warm, cfg=cfg, targets=targets)

    assert "dual_max_uz" in margins
    assert "main_radius_taper" in margins
    assert "rear_radius_taper" in margins
    assert np.min(np.asarray(margins["main_radius_taper"])) >= 0.0
    assert np.min(np.asarray(margins["rear_radius_taper"])) >= 0.0
