from __future__ import annotations

import numpy as np
import pytest

from hpa_mdo.structure.optimizer import _ScipyBlackBoxEvaluator


class _FakeProb:
    def __init__(self) -> None:
        self.run_model_calls = 0
        self.values: dict[str, np.ndarray] = {
            "struct.seg_mapper.main_t_seg": np.array([0.0010, 0.0010]),
            "struct.seg_mapper.main_r_seg": np.array([0.0200, 0.0200]),
            "struct.failure.failure": np.array([-0.2]),
            "struct.twist.twist_max_deg": np.array([0.1]),
            "struct.tip_defl.tip_deflection_m": np.array([0.1]),
            "struct.buckling.buckling_index": np.array([-0.1]),
            "struct.mass.total_mass_full": np.array([0.0]),
        }

    def set_val(self, name, value, units=None) -> None:
        self.values[name] = np.asarray(value, dtype=float)

    def get_val(self, name):
        return np.asarray(self.values[name], dtype=float)

    def run_model(self) -> None:
        self.run_model_calls += 1
        main_t = np.asarray(self.values["struct.seg_mapper.main_t_seg"], dtype=float)
        main_r = np.asarray(self.values["struct.seg_mapper.main_r_seg"], dtype=float)
        mass = float(np.sum(main_t) + np.sum(main_r))
        self.values["struct.mass.total_mass_full"] = np.array([mass])


@pytest.mark.xfail(strict=False, reason="Finding O5")
def test_cache_key_does_not_alias_fd_step_1p49e_minus8():
    prob = _FakeProb()
    evaluator = _ScipyBlackBoxEvaluator(
        prob,
        n_seg=2,
        rear_on=False,
        max_twist=2.0,
        max_defl=1.0,
        max_thickness_to_radius_ratio=0.8,
        max_main_thickness_step_m=0.003,
        max_rear_thickness_step_m=0.003,
        main_spar_dominance_margin_m=0.0,
        main_spar_ei_ratio=1.0,
        rear_main_radius_ratio_min=0.0,
        rear_min_inner_radius_m=1e-4,
        rear_inboard_ei_to_main_ratio_max=1.0,
        inboard_ei_element_indices=np.zeros(0, dtype=int),
        cache_size=16,
    )

    # Synthetic large-magnitude vector chosen so np.round(..., 8) aliases
    # x and (x + 1.49e-8) into the same decimal bucket.
    x0 = np.array(
        [
            43_820_041.86763375,
            43_820_041.86763375,
            43_820_041.96763375,
            43_820_041.96763375,
        ],
        dtype=float,
    )
    x1 = x0.copy()
    x1[0] += 1.49e-8

    r0 = evaluator.evaluate(x0)
    r1 = evaluator.evaluate(x1)

    assert prob.run_model_calls == 2
    assert r0["mass"] != r1["mass"]
