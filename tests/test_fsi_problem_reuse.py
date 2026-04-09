"""FSI reuse checks: avoid rebuilding SparOptimizer on every iteration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.fsi.coupling import FSICoupling
from hpa_mdo.structure.optimizer import SparOptimizer


REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_aero(span_half: float, *, lift_per_span: float = 75.0) -> SpanwiseLoad:
    y = np.linspace(0.0, span_half, 12)
    return SpanwiseLoad(
        y=y,
        chord=np.full(12, 1.0),
        cl=np.full(12, 0.55),
        cd=np.full(12, 0.02),
        cm=np.full(12, 0.04),
        lift_per_span=np.full(12, lift_per_span),
        drag_per_span=np.full(12, 2.0),
        aoa_deg=3.0,
        velocity=10.0,
        dynamic_pressure=0.5 * 1.225 * 10.0**2,
    )


def test_fsi_two_way_reuses_single_optimizer_instance():
    cfg = load_config(REPO_ROOT / "configs" / "blackcat_004.yaml")
    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    fsi = FSICoupling(cfg, aircraft, mat_db)

    init_calls: list[int] = []
    update_calls: list[int] = []

    real_init = SparOptimizer.__init__
    real_update = SparOptimizer.update_aero_loads

    def spy_init(self, *args, **kwargs):
        init_calls.append(1)
        return real_init(self, *args, **kwargs)

    def spy_update(self, *args, **kwargs):
        update_calls.append(1)
        return real_update(self, *args, **kwargs)

    def fake_optimize(self, method: str = "auto"):
        return MagicMock(
            tip_deflection_m=0.1,
            disp=np.zeros((aircraft.wing.n_stations, 6)),
        )

    with (
        patch.object(SparOptimizer, "__init__", spy_init),
        patch.object(SparOptimizer, "update_aero_loads", spy_update),
        patch.object(SparOptimizer, "optimize", fake_optimize),
    ):
        fsi._solve_once(_make_aero(aircraft.wing.half_span), 1.0, "auto")
        fsi._solve_once(_make_aero(aircraft.wing.half_span), 1.0, "auto")
        fsi._solve_once(_make_aero(aircraft.wing.half_span), 1.0, "auto")

    assert sum(init_calls) == 1, (
        f"Expected SparOptimizer to be built once, got {sum(init_calls)} builds"
    )
    assert sum(update_calls) == 2, (
        f"Expected update_aero_loads to be called twice, got {sum(update_calls)}"
    )


def test_fsi_one_way_still_works():
    """Smoke test: run_one_way must still produce a valid FSIResult."""
    cfg = load_config(REPO_ROOT / "configs" / "blackcat_004.yaml")
    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    fsi = FSICoupling(cfg, aircraft, mat_db)

    def fake_optimize(self, method: str = "auto"):
        return MagicMock(
            tip_deflection_m=0.1,
            disp=np.zeros((aircraft.wing.n_stations, 6)),
        )

    with patch.object(SparOptimizer, "optimize", fake_optimize):
        result = fsi.run_one_way(
            _make_aero(aircraft.wing.half_span),
            optimizer_method="scipy",
        )

    assert result.converged is True
    assert result.n_iterations == 1


def test_update_aero_loads_refreshes_wire_precompression():
    cfg = load_config(REPO_ROOT / "configs" / "blackcat_004.yaml")
    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)

    mat_db = MaterialDB()
    mapper = LoadMapper(method="linear")
    initial_loads = mapper.map_loads(_make_aero(aircraft.wing.half_span), aircraft.wing.y)
    optimizer = SparOptimizer(cfg, aircraft, initial_loads, mat_db)

    stress_comp = optimizer._prob.model._get_subsystem("struct.stress")
    before = np.asarray(stress_comp.options["wire_precompression"], dtype=float).copy()

    updated_loads = mapper.map_loads(
        _make_aero(aircraft.wing.half_span, lift_per_span=150.0),
        aircraft.wing.y,
    )
    optimizer.update_aero_loads(updated_loads)

    after = np.asarray(stress_comp.options["wire_precompression"], dtype=float)
    np.testing.assert_allclose(after, before * 2.0, rtol=1e-10, atol=1e-10)
