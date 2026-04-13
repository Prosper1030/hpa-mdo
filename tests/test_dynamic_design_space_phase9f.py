from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import load_config  # noqa: E402
from scripts.direct_dual_beam_inverse_design import (  # noqa: E402
    RefreshLoadMetrics,
    _build_refresh_iteration_result,
    _rebuild_dynamic_map_config,
)
from scripts.direct_dual_beam_v2 import ReducedMapConfig  # noqa: E402


def _cfg():
    return load_config(REPO_ROOT / "configs" / "blackcat_004.yaml")


def test_rebuild_dynamic_map_config_reseeds_from_selected_candidate() -> None:
    previous_map = ReducedMapConfig(
        main_plateau_scale_upper=1.14,
        main_taper_fill_upper=0.80,
        rear_radius_scale_upper=1.12,
        delta_t_global_max_m=0.001,
        delta_t_rear_outboard_max_m=0.0005,
        rear_outboard_mask=np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0]),
    )
    selected = SimpleNamespace(
        main_t_seg_m=np.full(6, 0.0012, dtype=float),
        main_r_seg_m=np.array([0.059, 0.059, 0.059, 0.059, 0.050, 0.040], dtype=float),
        rear_t_seg_m=np.full(6, 0.0010, dtype=float),
        rear_r_seg_m=np.full(6, 0.012, dtype=float),
    )

    baseline, rebuilt = _rebuild_dynamic_map_config(
        selected_candidate=selected,
        cfg=_cfg(),
        previous_map_config=previous_map,
    )

    assert np.allclose(baseline.main_r_seg_m, selected.main_r_seg_m)
    assert rebuilt.main_plateau_scale_upper < previous_map.main_plateau_scale_upper
    assert rebuilt.main_plateau_scale_upper <= 0.06 / 0.059 + 1.0e-9


def test_build_refresh_iteration_result_records_dynamic_map_metadata() -> None:
    result = _build_refresh_iteration_result(
        iteration_index=1,
        load_source="refresh_1",
        outcome=SimpleNamespace(selected=None),
        mapped_loads={},
        load_metrics=RefreshLoadMetrics(
            total_lift_half_n=1.0,
            total_drag_half_n=2.0,
            total_abs_torque_half_nm=3.0,
            max_lift_per_span_npm=4.0,
            max_abs_torque_per_span_nmpm=5.0,
            twist_abs_max_deg=6.0,
            aoa_eff_min_deg=7.0,
            aoa_eff_max_deg=8.0,
            aoa_clip_fraction=0.1,
        ),
        map_config=ReducedMapConfig(
            main_plateau_scale_upper=1.05,
            main_taper_fill_upper=0.60,
            rear_radius_scale_upper=1.08,
            delta_t_global_max_m=0.0008,
            delta_t_rear_outboard_max_m=0.0003,
            rear_outboard_mask=np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0]),
        ),
        dynamic_design_space_applied=True,
        previous=None,
        forward_check=None,
    )

    assert result.dynamic_design_space_applied is True
    assert result.map_config_summary["main_plateau_scale_upper"] == 1.05
    assert result.map_config_summary["delta_t_global_max_m"] == 0.0008
