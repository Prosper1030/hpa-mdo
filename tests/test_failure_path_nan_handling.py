from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hpa_mdo.structure.optimizer import SparOptimizer


class _Cfg(SimpleNamespace):
    def structural_load_cases(self):
        return [
            SimpleNamespace(
                name="default",
                max_twist_deg=self.wing.max_tip_twist_deg,
                max_tip_deflection_m=self.wing.max_tip_deflection_m,
            )
        ]


def _build_opt() -> SparOptimizer:
    opt = SparOptimizer.__new__(SparOptimizer)
    opt.cfg = _Cfg(
        rear_spar=SimpleNamespace(enabled=False),
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
    )
    return opt


def _base_raw() -> dict:
    return {
        "failure": -0.2,
        "buckling_index": -0.3,
        "twist_max_deg": 0.5,
        "tip_deflection_m": 0.1,
    }


def test_is_raw_feasible_rejects_nan_failure():
    opt = _build_opt()
    raw = _base_raw()
    raw["failure"] = np.nan
    assert opt._is_raw_feasible(raw) is False


def test_is_raw_feasible_rejects_nan_buckling():
    opt = _build_opt()
    raw = _base_raw()
    raw["buckling_index"] = np.nan
    assert opt._is_raw_feasible(raw) is False


def test_is_raw_feasible_rejects_nan_twist():
    opt = _build_opt()
    raw = _base_raw()
    raw["twist_max_deg"] = np.nan
    assert opt._is_raw_feasible(raw) is False


def test_is_raw_feasible_rejects_nan_tip_deflection():
    opt = _build_opt()
    raw = _base_raw()
    raw["tip_deflection_m"] = np.nan
    assert opt._is_raw_feasible(raw) is False
