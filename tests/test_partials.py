from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
from openmdao.utils.assert_utils import assert_check_totals

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.oas_structural import build_structural_problem


def _build_structural_prob():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")

    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)
        mat_db = MaterialDB()
        mapper = LoadMapper(method="linear")

        fake_load = SpanwiseLoad(
            y=np.linspace(0.0, aircraft.wing.half_span, 12),
            chord=np.linspace(cfg.wing.root_chord, cfg.wing.tip_chord, 12),
            cl=np.full(12, 0.55),
            cd=np.full(12, 0.02),
            cm=np.full(12, 0.04),
            lift_per_span=np.full(12, 75.0),
            drag_per_span=np.full(12, 2.0),
            aoa_deg=3.0,
            velocity=cfg.flight.velocity,
            dynamic_pressure=0.5 * cfg.flight.air_density * cfg.flight.velocity**2,
        )
        mapped_loads = mapper.map_loads(fake_load, aircraft.wing.y)

        prob = build_structural_problem(
            cfg,
            aircraft,
            mapped_loads,
            mat_db,
            force_alloc_complex=True,
        )
        n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
        prob.set_val("struct.seg_mapper.main_t_seg", np.full(n_seg, 0.0016), units="m")
        prob.set_val("struct.seg_mapper.main_r_seg", np.full(n_seg, 0.028), units="m")
        if cfg.rear_spar.enabled:
            prob.set_val("struct.seg_mapper.rear_t_seg", np.full(n_seg, 0.0012), units="m")
            prob.set_val("struct.seg_mapper.rear_r_seg", np.full(n_seg, 0.022), units="m")
        prob.run_model()
        return prob


def test_check_totals_full_structural_model():
    """Whole-problem total derivatives should match complex-step."""
    prob = _build_structural_prob()
    totals = prob.check_totals(
        of=[
            "struct.mass.total_mass_full",
            "struct.failure.failure",
            "struct.buckling.buckling_index",
            "struct.twist.twist_max_deg",
            "struct.tip_defl.tip_deflection_m",
        ],
        wrt=[
            "struct.seg_mapper.main_t_seg",
            "struct.seg_mapper.main_r_seg",
            "struct.seg_mapper.rear_t_seg",
            "struct.seg_mapper.rear_r_seg",
        ],
        method="cs",
        out_stream=None,
    )

    assert_check_totals(totals, atol=1e-5, rtol=1e-5)
