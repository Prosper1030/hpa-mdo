from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.oas_structural import build_structural_problem


def _build_prob(*, rear_main_radius_ratio_min: float = 0.0):
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")
    cfg.solver.rear_main_radius_ratio_min = float(rear_main_radius_ratio_min)

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
        prob = build_structural_problem(cfg, aircraft, mapped_loads, mat_db)

        n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
        prob.set_val("struct.seg_mapper.main_t_seg", np.full(n_seg, 0.0012), units="m")
        prob.set_val("struct.seg_mapper.main_r_seg", np.full(n_seg, 0.0300), units="m")
        prob.set_val("struct.seg_mapper.rear_t_seg", np.full(n_seg, 0.0010), units="m")
        prob.set_val("struct.seg_mapper.rear_r_seg", np.full(n_seg, 0.0200), units="m")
        prob.run_model()
        return prob, cfg


def test_rear_engineering_constraints_are_registered():
    prob, _cfg = _build_prob()
    constraints = prob.model.get_constraints()

    assert "rear_hollow_tube_validity.margin" in constraints
    assert "main_rear_inboard_ei_cap.margin" in constraints


def test_rear_radius_ratio_guardrail_constraint_is_registered_when_enabled():
    prob, _cfg = _build_prob(rear_main_radius_ratio_min=0.40)
    constraints = prob.model.get_constraints()
    assert "rear_main_radius_ratio_guardrail.margin" in constraints


def test_rear_hollow_tube_validity_rejects_t_ge_r():
    prob, cfg = _build_prob()
    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))

    rear_r = np.full(n_seg, 0.011, dtype=float)
    rear_t = np.full(n_seg, 0.0010, dtype=float)
    rear_t[0] = rear_r[0] + 5.0e-4  # pathologic: t > R at root

    prob.set_val("struct.seg_mapper.rear_r_seg", rear_r, units="m")
    prob.set_val("struct.seg_mapper.rear_t_seg", rear_t, units="m")
    prob.run_model()

    margin = np.asarray(prob.get_val("rear_hollow_tube_validity.margin"), dtype=float)
    assert margin[0] < 0.0


def test_inboard_ei_cap_preserves_main_primary_role():
    prob, cfg = _build_prob()
    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))

    # Keep geometric validity while making rear overly stiff near root.
    main_t = np.full(n_seg, cfg.main_spar.min_wall_thickness, dtype=float)
    main_r = np.full(n_seg, 0.0300, dtype=float)
    rear_t = np.full(n_seg, 0.0010, dtype=float)
    rear_r = np.full(n_seg, 0.0200, dtype=float)

    rear_t[0] = 0.0075  # still valid: t <= 0.8R and t < R

    prob.set_val("struct.seg_mapper.main_t_seg", main_t, units="m")
    prob.set_val("struct.seg_mapper.main_r_seg", main_r, units="m")
    prob.set_val("struct.seg_mapper.rear_t_seg", rear_t, units="m")
    prob.set_val("struct.seg_mapper.rear_r_seg", rear_r, units="m")
    prob.run_model()

    # Root-side EI cap must detect rear spar becoming too dominant inboard.
    inboard_margin = np.asarray(prob.get_val("main_rear_inboard_ei_cap.margin"), dtype=float)
    assert np.min(inboard_margin) < 0.0


def test_rear_radius_ratio_guardrail_rejects_soft_rear_radius_pattern():
    prob, cfg = _build_prob(rear_main_radius_ratio_min=0.40)
    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))

    # Main and rear radii chosen so rear/main ratio = 0.30 < 0.40.
    prob.set_val("struct.seg_mapper.main_r_seg", np.full(n_seg, 0.0300), units="m")
    prob.set_val("struct.seg_mapper.rear_r_seg", np.full(n_seg, 0.0090), units="m")
    prob.run_model()

    margin = np.asarray(prob.get_val("rear_main_radius_ratio_guardrail.margin"), dtype=float)
    assert np.min(margin) < 0.0
