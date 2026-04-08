from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.fsi.coupling import FSICoupling
from hpa_mdo.structure.optimizer import OptimizationResult


def _fake_aero_load_dict(lift_value: float) -> dict:
    y = np.linspace(0.0, 16.5, 10)
    return {
        "y": y,
        "lift_per_span": np.ones(10) * lift_value,
        "drag_per_span": np.zeros(10),
        "torque_per_span": np.zeros(10),
        "chord": np.ones(10) * 0.8,
        "total_lift": 825.0 * (lift_value / 50.0),
    }


def _spanwise_load_from_dict(aero_load: dict) -> SpanwiseLoad:
    y = np.asarray(aero_load["y"], dtype=float)
    chord = np.asarray(aero_load["chord"], dtype=float)
    lift = np.asarray(aero_load["lift_per_span"], dtype=float)
    drag = np.asarray(aero_load["drag_per_span"], dtype=float)

    q = 25.0
    cl = lift / (q * chord)
    cd = drag / (q * chord + 1e-12)
    cm = np.zeros_like(chord)

    return SpanwiseLoad(
        y=y,
        chord=chord,
        cl=cl,
        cd=cd,
        cm=cm,
        lift_per_span=lift,
        drag_per_span=drag,
        aoa_deg=3.0,
        velocity=6.5,
        dynamic_pressure=q,
    )


def _fake_optimization_result(tip_deflection_m: float) -> OptimizationResult:
    n_seg = 6
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
        tip_deflection_m=tip_deflection_m,
        max_tip_deflection_m=2.5,
        twist_max_deg=0.6,
        main_t_seg_mm=np.full(n_seg, 1.2),
        main_r_seg_mm=np.full(n_seg, 35.0),
        rear_t_seg_mm=np.full(n_seg, 1.0),
        rear_r_seg_mm=np.full(n_seg, 25.0),
        disp=np.zeros((10, 6)),
        vonmises_main=np.zeros(9),
        vonmises_rear=np.zeros(9),
    )


def _build_fsi() -> FSICoupling:
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")
    aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    return FSICoupling(cfg, aircraft, mat_db)


def test_one_way_returns_fsi_result(monkeypatch):
    aero_load = _fake_aero_load_dict(lift_value=50.0)
    spanwise = _spanwise_load_from_dict(aero_load)
    coupling = _build_fsi()

    def _fake_solve_once(self, aero_load, load_factor, optimizer_method):
        deformed_z = np.linspace(0.0, 0.15, len(self.aircraft.wing.y))
        return _fake_optimization_result(tip_deflection_m=0.15), deformed_z

    monkeypatch.setattr(FSICoupling, "_solve_once", _fake_solve_once)

    result = coupling.run_one_way(spanwise)

    assert result is not None
    opt_result = result.optimization_result
    assert hasattr(opt_result, "tip_deflection_m")
    assert hasattr(opt_result, "twist_max_deg")
    assert hasattr(opt_result, "total_mass_full_kg")
    assert opt_result.tip_deflection_m > 0


def test_two_way_raises_not_implemented_for_xflr5():
    coupling = _build_fsi()

    with pytest.raises(NotImplementedError):
        coupling.run_two_way(aero_load_func=lambda _: {}, aero_solver="xflr5")


def test_two_way_raises_for_missing_openvsp():
    coupling = _build_fsi()

    with patch.dict(sys.modules, {"openvsp": None}):
        with pytest.raises((ImportError, RuntimeError)):
            coupling.run_two_way(aero_load_func=lambda _: {}, aero_solver="vspaero")


def test_one_way_load_factor_applied_once(monkeypatch):
    coupling = _build_fsi()
    light_load = _spanwise_load_from_dict(_fake_aero_load_dict(lift_value=50.0))
    heavy_load = _spanwise_load_from_dict(_fake_aero_load_dict(lift_value=100.0))

    def _fake_solve_once(self, aero_load, load_factor, optimizer_method):
        mean_lift = float(np.mean(aero_load.lift_per_span))
        tip_deflection = mean_lift * 1e-3
        deformed_z = np.linspace(0.0, tip_deflection, len(self.aircraft.wing.y))
        return _fake_optimization_result(tip_deflection_m=tip_deflection), deformed_z

    monkeypatch.setattr(FSICoupling, "_solve_once", _fake_solve_once)

    result_light = coupling.run_one_way(light_load)
    result_heavy = coupling.run_one_way(heavy_load)

    assert (
        result_heavy.optimization_result.tip_deflection_m
        > result_light.optimization_result.tip_deflection_m
    )
