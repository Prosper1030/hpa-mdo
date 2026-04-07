from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.optimizer import SparOptimizer


@pytest.mark.slow
def test_full_pipeline_produces_valid_result():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")

    with patch.object(cfg.solver, "n_beam_nodes", 20), patch.object(
        cfg.solver, "optimizer_maxiter", 5
    ):
        aircraft = Aircraft.from_config(cfg)
        mat_db = MaterialDB()
        mapper = LoadMapper()

        fake_load = SpanwiseLoad(
            y=np.linspace(0.0, 16.5, 10),
            chord=np.ones(10) * 0.8,
            cl=np.ones(10) * 0.5,
            cd=np.zeros(10),
            cm=np.zeros(10),
            lift_per_span=np.ones(10) * 80.0,
            drag_per_span=np.zeros(10),
            aoa_deg=3.0,
            velocity=6.5,
            dynamic_pressure=24.4,
        )

        mapped_loads = mapper.map_loads(fake_load, aircraft.wing.y)
        result = SparOptimizer(cfg, aircraft, mapped_loads, mat_db).optimize(
            method="openmdao"
        )

    assert result.success is True or result.failure_index <= 0.5
    assert 0.0 < result.total_mass_full_kg < 99999
    assert result.tip_deflection_m > 0.0
    assert getattr(result, "val_weight", 0.0) != 99999
