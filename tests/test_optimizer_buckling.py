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
        rear_spar=SimpleNamespace(
            enabled=False, min_wall_thickness=0.001, material="carbon_fiber_hm"
        ),
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


def test_scipy_evaluator_penalizes_thickness_step_violation():
    prob = _FakeProb()
    evaluator = optimizer_mod._ScipyBlackBoxEvaluator(
        prob,
        n_seg=2,
        rear_on=False,
        max_twist=2.0,
        max_defl=1.0,
        max_thickness_to_radius_ratio=0.8,
        max_main_thickness_step_m=0.0002,
        max_rear_thickness_step_m=0.0002,
        main_spar_dominance_margin_m=0.0,
        main_spar_ei_ratio=1.0,
        rear_main_radius_ratio_min=0.0,
        rear_min_inner_radius_m=1e-4,
        rear_inboard_ei_to_main_ratio_max=1.0,
        inboard_ei_element_indices=np.zeros(0, dtype=int),
        cache_size=0,
    )
    x_good = np.array([0.0010, 0.0011, 0.020, 0.020])
    x_bad = np.array([0.0010, 0.0014, 0.020, 0.020])

    good = evaluator.evaluate(x_good)
    bad = evaluator.evaluate(x_bad)

    assert np.isclose(good["main_thickness_step_margin_min"], 0.0001)
    assert np.isclose(bad["main_thickness_step_margin_min"], -0.0002)
    assert evaluator.penalty(x_bad) > evaluator.penalty(x_good)


def test_summary_text_contains_buckling_line(tmp_path):
    """Summary text output contains 'Buckling index' line."""
    result = _dummy_result()

    summary_stdout = print_optimization_summary(result)
    assert "Buckling index" in summary_stdout

    out_path = tmp_path / "optimization_summary.txt"
    summary_file = write_optimization_summary(result, out_path)
    assert "Buckling index" in summary_file
    assert "Buckling index" in out_path.read_text(encoding="utf-8")


def test_analyze_accepts_snapped_segment_radii(monkeypatch):
    cfg = _Cfg(rear_spar=SimpleNamespace(enabled=True))
    prob = _FakeProb()

    opt = SparOptimizer.__new__(SparOptimizer)
    opt.cfg = cfg
    opt._prob = prob

    monkeypatch.setattr(optimizer_mod, "run_analysis", lambda _prob: {"ok": True})
    monkeypatch.setattr(
        SparOptimizer,
        "_to_result",
        lambda self, raw, success, message, timing_s=None: {
            "raw": raw,
            "success": success,
            "message": message,
        },
    )

    result = opt.analyze(
        main_t_seg=np.array([0.0012, 0.0011]),
        main_r_seg=np.array([0.040, 0.035]),
        rear_t_seg=np.array([0.0009, 0.0008]),
        rear_r_seg=np.array([0.020, 0.018]),
    )

    np.testing.assert_allclose(
        prob.values["struct.seg_mapper.main_t_seg"], np.array([0.0012, 0.0011])
    )
    np.testing.assert_allclose(
        prob.values["struct.seg_mapper.main_r_seg"], np.array([0.040, 0.035])
    )
    np.testing.assert_allclose(
        prob.values["struct.seg_mapper.rear_t_seg"], np.array([0.0009, 0.0008])
    )
    np.testing.assert_allclose(
        prob.values["struct.seg_mapper.rear_r_seg"], np.array([0.020, 0.018])
    )
    assert result["success"] is True
    assert result["message"] == "Analysis complete"


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


def test_auto_mode_falls_back_when_openmdao_raw_is_not_fully_feasible(monkeypatch):
    cfg = _Cfg(
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
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
    opt._prob = object()

    openmdao_result = SimpleNamespace(
        success=True,
        failure_index=-0.2,
        buckling_index=-0.2,
        message="OpenMDAO converged",
    )
    scipy_result = SimpleNamespace(message="scipy fallback")

    monkeypatch.setattr(SparOptimizer, "_has_multiple_load_cases", lambda _self: False)
    monkeypatch.setattr(SparOptimizer, "_optimize_openmdao", lambda _self: openmdao_result)
    monkeypatch.setattr(SparOptimizer, "_optimize_scipy", lambda _self: scipy_result)
    monkeypatch.setattr(
        optimizer_mod,
        "run_analysis",
        lambda _prob: {
            "failure": -0.2,
            "buckling_index": -0.2,
            "twist_max_deg": 2.2,  # violates 2.0 deg cap
            "tip_deflection_m": 0.1,
        },
    )

    result = opt.optimize(method="auto")
    assert result is scipy_result


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


def test_raw_feasible_rejects_rear_tube_validity_violation_even_if_ratio_passes():
    cfg = _Cfg(
        rear_spar=SimpleNamespace(
            enabled=True, min_wall_thickness=0.001, material="carbon_fiber_hm"
        ),
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
        solver=SimpleNamespace(
            max_thickness_to_radius_ratio=2.0,  # deliberately loose for isolation
            rear_min_inner_radius_m=1e-4,
            main_spar_dominance_margin_m=0.0,
            main_spar_ei_ratio=1.0,
            rear_inboard_ei_to_main_ratio_max=1.0,
            rear_inboard_span_m=1.0,
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
    opt._prob = SimpleNamespace(
        model=SimpleNamespace(struct=SimpleNamespace(_elem_centres=np.array([0.5])))
    )

    raw = {
        "failure": -0.10,
        "buckling_index": -0.20,
        "twist_max_deg": 0.2,
        "tip_deflection_m": 0.1,
        "main_t_seg": np.array([0.002, 0.002]),
        "main_r_seg": np.array([0.020, 0.020]),
        "rear_t_seg": np.array([0.0105, 0.001]),
        "rear_r_seg": np.array([0.0100, 0.012]),
        "EI_main_elem": np.array([10.0]),
        "EI_rear_elem": np.array([1.0]),
    }

    assert opt._is_raw_feasible(raw) is False


def test_raw_feasible_rejects_inboard_rear_ei_overdominance():
    cfg = _Cfg(
        rear_spar=SimpleNamespace(
            enabled=True, min_wall_thickness=0.001, material="carbon_fiber_hm"
        ),
        wing=SimpleNamespace(max_tip_twist_deg=2.0, max_tip_deflection_m=1.0),
        solver=SimpleNamespace(
            max_thickness_to_radius_ratio=0.8,
            rear_min_inner_radius_m=1e-4,
            main_spar_dominance_margin_m=0.0,
            main_spar_ei_ratio=2.0,  # global cap: EI_rear <= 0.5 * EI_main
            rear_inboard_ei_to_main_ratio_max=0.2,  # stricter root-side cap
            rear_inboard_span_m=1.0,
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
    opt._prob = SimpleNamespace(
        model=SimpleNamespace(struct=SimpleNamespace(_elem_centres=np.array([0.5, 2.0])))
    )

    raw = {
        "failure": -0.10,
        "buckling_index": -0.20,
        "twist_max_deg": 0.2,
        "tip_deflection_m": 0.1,
        "main_t_seg": np.array([0.001, 0.001]),
        "main_r_seg": np.array([0.020, 0.020]),
        "rear_t_seg": np.array([0.001, 0.001]),
        "rear_r_seg": np.array([0.012, 0.012]),
        "EI_main_elem": np.array([10.0, 10.0]),
        "EI_rear_elem": np.array([2.5, 1.0]),  # root element violates only inboard cap
    }

    assert opt._is_raw_feasible(raw) is False
