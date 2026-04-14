from __future__ import annotations

import numpy as np
import openmdao.api as om

from hpa_mdo.structure.optimizer import _ScipyBlackBoxEvaluator


class _FakeProb:
    def __init__(self, *, run_model_exc: Exception | None = None, failure_value: float = -0.2):
        self._run_model_exc = run_model_exc
        self.values = {
            "struct.mass.total_mass_full": np.array([12.0]),
            "struct.failure.failure": np.array([failure_value]),
            "struct.twist.twist_max_deg": np.array([0.4]),
            "struct.tip_defl.tip_deflection_m": np.array([0.2]),
            "struct.buckling.buckling_index": np.array([-0.1]),
            "struct.seg_mapper.main_t_seg": np.array([0.0010, 0.0010]),
            "struct.seg_mapper.main_r_seg": np.array([0.0200, 0.0200]),
        }

    def set_val(self, name, value, units=None):
        self.values[name] = np.asarray(value, dtype=float)

    def get_val(self, name):
        return np.asarray(self.values[name])

    def run_model(self):
        if self._run_model_exc is not None:
            raise self._run_model_exc


def _build_evaluator(prob: _FakeProb) -> _ScipyBlackBoxEvaluator:
    return _ScipyBlackBoxEvaluator(
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
        cache_size=0,
    )


def test_analysis_error_becomes_failed_eval():
    prob = _FakeProb(run_model_exc=om.AnalysisError("solver diverged"))
    evaluator = _build_evaluator(prob)

    res = evaluator.evaluate(np.array([0.0012, 0.0013, 0.022, 0.023]))

    assert res["mass"] >= 1.0e12
    assert res["failure"] > 0.0
    assert res["buckling"] > 0.0


def test_nonfinite_metrics_become_failed_eval():
    prob = _FakeProb(failure_value=np.nan)
    evaluator = _build_evaluator(prob)

    res = evaluator.evaluate(np.array([0.0012, 0.0013, 0.022, 0.023]))

    assert res["mass"] >= 1.0e12
    assert res["failure"] > 0.0
    assert res["tip_defl"] > 0.0


def test_unexpected_exception_is_normalized_with_logging(monkeypatch):
    prob = _FakeProb(run_model_exc=RuntimeError("boom"))
    evaluator = _build_evaluator(prob)
    calls = []
    monkeypatch.setattr(
        "hpa_mdo.structure.optimizer.logger.exception",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    res = evaluator.evaluate(np.array([0.0012, 0.0013, 0.022, 0.023]))

    assert res["mass"] >= 1.0e12
    assert len(calls) == 1
