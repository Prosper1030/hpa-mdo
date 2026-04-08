from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hpa_mdo.core.materials import Material
from hpa_mdo.structure import optimizer as optimizer_mod
from hpa_mdo.structure.optimizer import OptimizationResult, SparOptimizer
from hpa_mdo.utils.visualization import (
    print_optimization_summary,
    write_optimization_summary,
)


class _Cfg(SimpleNamespace):
    def spar_segment_lengths(self, spar):
        return [1.0, 1.0]

    def structural_load_cases(self):
        configured = getattr(self, "_structural_cases", None)
        if configured is not None:
            return list(configured)
        return [
            SimpleNamespace(
                name="default",
                max_twist_deg=self.wing.max_tip_twist_deg,
                max_tip_deflection_m=self.wing.max_tip_deflection_m,
            )
        ]


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


def test_openmdao_feasibility_checks_twist_and_deflection(monkeypatch):
    cfg = _Cfg(
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
        _structural_cases=[
            SimpleNamespace(
                name="default",
                max_twist_deg=0.30,
                max_tip_deflection_m=0.05,
            )
        ],
    )

    opt = SparOptimizer.__new__(SparOptimizer)
    opt.cfg = cfg
    opt._prob = object()

    raw = {
        "failure": -0.10,
        "buckling_index": -0.20,
        "twist_max_deg": 0.40,
        "tip_deflection_m": 0.06,
    }

    monkeypatch.setattr(optimizer_mod, "run_optimization", lambda _prob: raw)
    monkeypatch.setattr(
        SparOptimizer,
        "_to_result",
        lambda self, raw, success, message, timing_s=None: {"success": success, "message": message},
    )

    result = opt._optimize_openmdao()
    assert result["success"] is False


def test_raw_feasible_honors_per_case_limits():
    cfg = _Cfg(
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
        _structural_cases=[
            SimpleNamespace(name="cruise", max_twist_deg=0.5, max_tip_deflection_m=0.2),
            SimpleNamespace(name="pullup", max_twist_deg=1.0, max_tip_deflection_m=0.4),
        ],
    )
    opt = SparOptimizer.__new__(SparOptimizer)
    opt.cfg = cfg

    raw = {
        "failure": -0.10,
        "buckling_index": -0.20,
        "cases": {
            "cruise": {"twist_max_deg": 0.40, "tip_deflection_m": 0.10},
            "pullup": {"twist_max_deg": 1.10, "tip_deflection_m": 0.30},
        },
    }
    assert opt._is_raw_feasible(raw) is False


def test_raw_feasible_rejects_main_spar_dominance_violations():
    cfg = _Cfg(
        rear_spar=SimpleNamespace(
            enabled=True, min_wall_thickness=0.001, material="carbon_fiber_hm"
        ),
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
        solver=SimpleNamespace(
            main_spar_dominance_margin_m=0.005,
            main_spar_ei_ratio=2.0,
        ),
        _structural_cases=[
            SimpleNamespace(
                name="default",
                max_twist_deg=2.0,
                max_tip_deflection_m=1.0,
            )
        ],
    )
    opt = SparOptimizer.__new__(SparOptimizer)
    opt.cfg = cfg

    raw = {
        "failure": -0.10,
        "buckling_index": -0.20,
        "twist_max_deg": 0.2,
        "tip_deflection_m": 0.1,
        "main_r_seg": np.array([0.020, 0.030]),
        "rear_r_seg": np.array([0.018, 0.028]),  # violates 5 mm margin
        "EI_main_elem": np.array([10.0, 10.0]),
        "EI_rear_elem": np.array([6.0, 6.0]),  # violates EI ratio 2.0
    }

    assert opt._is_raw_feasible(raw) is False


def test_to_result_uses_compressive_allowable_when_lower():
    cfg = _Cfg(
        main_spar=SimpleNamespace(material="main_cf"),
        rear_spar=SimpleNamespace(enabled=False, material="rear_cf"),
        safety=SimpleNamespace(material_safety_factor=1.5),
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
    )

    class _MatDB:
        def __init__(self):
            self._materials = {
                "main_cf": Material(
                    name="main_cf",
                    E=240e9,
                    G=90e9,
                    density=1600.0,
                    tensile_strength=2.5e9,
                    compressive_strength=1.5e9,
                ),
                "rear_cf": Material(
                    name="rear_cf",
                    E=240e9,
                    G=90e9,
                    density=1600.0,
                    tensile_strength=2.2e9,
                    compressive_strength=1.2e9,
                ),
            }

        def get(self, key):
            return self._materials[key]

    opt = SparOptimizer.__new__(SparOptimizer)
    opt.cfg = cfg
    opt.materials_db = _MatDB()

    raw = {
        "spar_mass_half_kg": 1.0,
        "spar_mass_full_kg": 2.0,
        "total_mass_full_kg": 3.0,
        "failure": -0.1,
        "buckling_index": -0.2,
        "tip_deflection_m": 0.1,
        "twist_max_deg": 0.2,
        "main_t_seg": np.array([0.001, 0.001]),
        "main_r_seg": np.array([0.02, 0.02]),
        "rear_t_seg": None,
        "rear_r_seg": None,
        "vonmises_main": np.array([1.0e8, 1.2e8]),
        "vonmises_rear": np.array([]),
        "disp": np.zeros((3, 6)),
    }

    result = opt._to_result(raw, success=True, message="ok")
    assert result.allowable_stress_main_Pa == 1.5e9 / 1.5
    assert result.allowable_stress_rear_Pa == 1.2e9 / 1.5
