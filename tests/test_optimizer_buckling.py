from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hpa_mdo.structure import optimizer as optimizer_mod
from hpa_mdo.structure.optimizer import OptimizationResult, SparOptimizer
from hpa_mdo.utils.visualization import (
    print_optimization_summary,
    write_optimization_summary,
)


class _Cfg(SimpleNamespace):
    def spar_segment_lengths(self, spar):
        return [1.0, 1.0]


class _FakeProb:
    def __init__(self) -> None:
        self.values = {
            "struct.mass.total_mass_full": 12.0,
            "struct.failure.failure": -0.10,
            "struct.twist.twist_max_deg": 0.50,
            "struct.tip_defl.tip_deflection_m": 0.10,
            "struct.buckling.buckling_index": 0.00,
        }

    def set_val(self, name, value, units=None) -> None:
        self.values[name] = np.asarray(value)

    def get_val(self, name):
        return np.asarray(self.values[name])

    def run_model(self) -> None:
        return


def _dummy_result() -> OptimizationResult:
    return OptimizationResult(
        success=True,
        message="ok",
        spar_mass_half_kg=1.0,
        spar_mass_full_kg=2.0,
        total_mass_full_kg=2.5,
        max_stress_main_Pa=80e6,
        max_stress_rear_Pa=65e6,
        allowable_stress_main_Pa=300e6,
        allowable_stress_rear_Pa=300e6,
        failure_index=-0.2,
        buckling_index=-0.3,
        tip_deflection_m=0.15,
        max_tip_deflection_m=2.5,
        twist_max_deg=0.6,
        main_t_seg_mm=np.array([1.2, 1.1]),
        main_r_seg_mm=np.array([35.0, 34.0]),
        rear_t_seg_mm=np.array([1.0, 0.9]),
        rear_r_seg_mm=np.array([25.0, 24.0]),
    )


def test_optimization_result_has_buckling_index():
    """OptimizationResult dataclass exposes buckling_index field."""
    result = _dummy_result()
    assert hasattr(result, "buckling_index")
    assert result.buckling_index == -0.3


def test_eval_dict_includes_buckling(monkeypatch):
    """SparOptimizer._optimize_scipy._eval returns dict with 'buckling' key."""
    cfg = _Cfg(
        main_spar=SimpleNamespace(min_wall_thickness=0.001, material="carbon_fiber_hm"),
        rear_spar=SimpleNamespace(enabled=False, min_wall_thickness=0.001, material="carbon_fiber_hm"),
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
    )
    prob = _FakeProb()

    opt = SparOptimizer.__new__(SparOptimizer)
    opt.cfg = cfg
    opt._prob = prob
    opt.materials_db = None

    checks = {
        "penalty_uses_buckling": False,
        "constraints_include_buckling": False,
    }

    def fake_run_analysis(fake_prob):
        return {
            "spar_mass_half_kg": 2.0,
            "spar_mass_full_kg": 4.0,
            "total_mass_full_kg": float(fake_prob.get_val("struct.mass.total_mass_full")),
            "failure": float(fake_prob.get_val("struct.failure.failure")),
            "buckling_index": float(fake_prob.get_val("struct.buckling.buckling_index")),
            "twist_max_deg": float(fake_prob.get_val("struct.twist.twist_max_deg")),
            "tip_deflection_m": float(fake_prob.get_val("struct.tip_defl.tip_deflection_m")),
            "disp": np.zeros((3, 6)),
            "vonmises_main": np.zeros(2),
            "main_t_seg": np.array([0.001, 0.001]),
            "main_r_seg": np.array([0.02, 0.02]),
        }

    def fake_differential_evolution(penalty_obj, bounds, **kwargs):
        x0 = np.array([(lo + hi) * 0.5 for (lo, hi) in bounds])

        prob.values["struct.buckling.buckling_index"] = 0.00
        p0 = penalty_obj(x0)

        prob.values["struct.buckling.buckling_index"] = 0.20
        x1 = x0.copy()
        x1[0] += 1e-4
        p1 = penalty_obj(x1)

        checks["penalty_uses_buckling"] = p1 > p0
        prob.values["struct.buckling.buckling_index"] = 0.00
        return SimpleNamespace(x=x0)

    def fake_minimize(obj, x0, method, bounds, constraints, options):
        prob.values["struct.buckling.buckling_index"] = 0.23
        cvals = [c["fun"](np.asarray(x0)) for c in constraints]
        checks["constraints_include_buckling"] = any(np.isclose(v, -0.23) for v in cvals)
        prob.values["struct.buckling.buckling_index"] = 0.00
        return SimpleNamespace(x=np.asarray(x0))

    monkeypatch.setattr(optimizer_mod, "run_analysis", fake_run_analysis)
    monkeypatch.setattr(optimizer_mod, "differential_evolution", fake_differential_evolution)
    monkeypatch.setattr(optimizer_mod, "scipy_minimize", fake_minimize)
    monkeypatch.setattr(
        SparOptimizer,
        "_to_result",
        lambda self, raw, success, message, timing_s=None: {
            "success": success,
            "message": message,
            "buckling_index": raw["buckling_index"],
        },
    )

    opt._optimize_scipy()

    assert checks["penalty_uses_buckling"]
    assert checks["constraints_include_buckling"]


def test_summary_text_contains_buckling_line(tmp_path):
    """Summary text output contains 'Buckling index' line."""
    result = _dummy_result()

    summary_stdout = print_optimization_summary(result)
    assert "Buckling index" in summary_stdout

    out_path = tmp_path / "optimization_summary.txt"
    summary_file = write_optimization_summary(result, out_path)
    assert "Buckling index" in summary_file
    assert "Buckling index" in out_path.read_text(encoding="utf-8")
