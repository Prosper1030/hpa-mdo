from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hpa_mdo.structure import optimizer as optimizer_mod
from hpa_mdo.structure.optimizer import SparOptimizer


class _Cfg(SimpleNamespace):
    def spar_segment_lengths(self, _spar):
        return [1.0, 1.0]

    def structural_load_cases(self):
        return [
            SimpleNamespace(
                name="default",
                max_twist_deg=self.wing.max_tip_twist_deg,
                max_tip_deflection_m=self.wing.max_tip_deflection_m,
            )
        ]


class _FakeProb:
    def __init__(self) -> None:
        self.values = {}
        self.model = SimpleNamespace(
            struct=SimpleNamespace(_multi_case=False, _elem_centres=np.array([0.5, 1.5]))
        )

    def set_val(self, name, value, units=None) -> None:
        self.values[name] = np.asarray(value, dtype=float)


def _candidate(
    *,
    mass: float,
    failure: float,
    buckling: float,
    twist: float,
    tip_defl: float,
    main_hollow_margin_min: float = 1.0,
    main_thickness_step_margin_min: float = 1.0,
) -> dict[str, float]:
    # NOTE: `_is_eval_valid` requires every "required" margin key to be
    # finite — `float("inf")` fails `np.isfinite()`.  Use large finite
    # sentinels (1e6) for non-required margins just to stay consistent.
    _BIG = 1.0e6
    return {
        "mass": mass,
        "failure": failure,
        "buckling": buckling,
        "twist": twist,
        "tip_defl": tip_defl,
        "main_hollow_margin_min": main_hollow_margin_min,
        "main_thickness_step_margin_min": main_thickness_step_margin_min,
        "rear_hollow_margin_min": _BIG,
        "rear_thickness_step_margin_min": _BIG,
        "rear_main_radius_ratio_margin_min": _BIG,
        "radius_dominance_margin_min": _BIG,
        "ei_dominance_margin_min": _BIG,
        "ei_ratio_margin_min": _BIG,
        "rear_inboard_ei_margin_min": _BIG,
    }


def _build_optimizer() -> SparOptimizer:
    opt = SparOptimizer.__new__(SparOptimizer)
    opt.cfg = _Cfg(
        main_spar=SimpleNamespace(min_wall_thickness=0.001, material="carbon_fiber_hm"),
        rear_spar=SimpleNamespace(enabled=False, min_wall_thickness=0.001, material="carbon_fiber_hm"),
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
    )
    opt._prob = _FakeProb()
    opt.materials_db = None
    opt.aircraft = None
    return opt


def _patch_scipy_pipeline(monkeypatch, x_de, x_sq, r_de, r_sq):
    class _FakeEvaluator:
        def __init__(self, *_args, **_kwargs):
            pass

        def clear_cache(self):
            return

        def evaluate(self, x):
            x_arr = np.asarray(x, dtype=float)
            if np.allclose(x_arr, x_de):
                return dict(r_de)
            if np.allclose(x_arr, x_sq):
                return dict(r_sq)
            return dict(r_sq)

        def penalty(self, x):
            return float(self.evaluate(x)["mass"])

    monkeypatch.setattr(optimizer_mod, "_ScipyBlackBoxEvaluator", _FakeEvaluator)
    monkeypatch.setattr(
        optimizer_mod,
        "differential_evolution",
        lambda *_args, **_kwargs: SimpleNamespace(x=np.asarray(x_de, dtype=float)),
    )
    monkeypatch.setattr(
        optimizer_mod,
        "scipy_minimize",
        lambda *_args, **_kwargs: SimpleNamespace(x=np.asarray(x_sq, dtype=float)),
    )

    def _fake_run_analysis(prob):
        main_t = np.asarray(prob.values["struct.seg_mapper.main_t_seg"], dtype=float)
        main_r = np.asarray(prob.values["struct.seg_mapper.main_r_seg"], dtype=float)
        return {
            "spar_mass_half_kg": 1.0,
            "spar_mass_full_kg": 2.0,
            "total_mass_full_kg": 3.0,
            "failure": -0.2,
            "buckling_index": -0.2,
            "twist_max_deg": 0.3,
            "tip_deflection_m": 0.1,
            "disp": np.zeros((3, 6)),
            "vonmises_main": np.zeros(2),
            "main_t_seg": main_t,
            "main_r_seg": main_r,
            "EI_main_elem": np.ones(2),
        }

    monkeypatch.setattr(optimizer_mod, "run_analysis", _fake_run_analysis)
    monkeypatch.setattr(
        SparOptimizer,
        "_to_result",
        lambda _self, raw, success, message, timing_s=None: {
            "success": success,
            "message": message,
            "main_t_seg": np.asarray(raw["main_t_seg"], dtype=float),
        },
    )


def test_best_compromise_does_not_select_nan_candidate(monkeypatch):
    opt = _build_optimizer()
    x_de = np.array([0.0011, 0.0012, 0.020, 0.021], dtype=float)
    x_sq = np.array([0.0013, 0.0014, 0.022, 0.023], dtype=float)

    r_de = _candidate(
        mass=1.0,
        failure=np.nan,  # invalid candidate
        buckling=-0.1,
        twist=0.2,
        tip_defl=0.1,
    )
    r_sq = _candidate(
        mass=30.0,
        failure=0.4,  # finite but infeasible -> should still beat invalid in compromise branch
        buckling=0.2,
        twist=2.5,
        tip_defl=1.3,
    )

    _patch_scipy_pipeline(monkeypatch, x_de, x_sq, r_de, r_sq)

    result = opt._optimize_scipy()
    assert np.allclose(result["main_t_seg"], x_sq[:2])
    assert "best compromise" in result["message"]


def test_feasible_finite_candidate_beats_invalid_candidate(monkeypatch):
    opt = _build_optimizer()
    x_de = np.array([0.0012, 0.0012, 0.020, 0.020], dtype=float)
    x_sq = np.array([0.0015, 0.0015, 0.024, 0.024], dtype=float)

    r_de = _candidate(
        mass=0.5,
        failure=np.nan,  # invalid candidate should never win
        buckling=-0.1,
        twist=0.1,
        tip_defl=0.1,
    )
    r_sq = _candidate(
        mass=50.0,
        failure=-0.2,  # finite + feasible
        buckling=-0.2,
        twist=0.4,
        tip_defl=0.2,
    )

    _patch_scipy_pipeline(monkeypatch, x_de, x_sq, r_de, r_sq)

    result = opt._optimize_scipy()
    assert np.allclose(result["main_t_seg"], x_sq[:2])
    assert "SLSQP converged" in result["message"]
