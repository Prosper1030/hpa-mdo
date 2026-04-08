from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import LoadCaseConfig, load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.oas_structural import build_structural_problem, run_analysis
from hpa_mdo.structure.optimizer import SparOptimizer


def _build_structural_inputs(*, explicit_single_case: bool = False, multi_case: bool = False):
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")

    if explicit_single_case:
        cfg.flight.cases = [
            LoadCaseConfig(
                name="cruise",
                aero_scale=cfg.safety.aerodynamic_load_factor,
                nz=cfg.safety.aerodynamic_load_factor,
                velocity=cfg.flight.velocity,
                air_density=cfg.flight.air_density,
            )
        ]
    elif multi_case:
        cfg.flight.cases = [
            LoadCaseConfig(
                name="cruise",
                aero_scale=1.0,
                nz=1.0,
                velocity=cfg.flight.velocity,
                air_density=cfg.flight.air_density,
            ),
            LoadCaseConfig(
                name="pullup",
                aero_scale=1.5,
                nz=1.5,
                velocity=cfg.flight.velocity,
                air_density=cfg.flight.air_density,
            ),
        ]

    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)

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
    aero_loads = mapped_loads
    if explicit_single_case:
        aero_loads = {"cruise": mapped_loads}
    elif multi_case:
        aero_loads = {
            "cruise": mapped_loads,
            "pullup": LoadMapper.apply_load_factor(mapped_loads, 1.5),
        }

    return cfg, aircraft, MaterialDB(), aero_loads


def _build_problem(*, explicit_single_case: bool = False, multi_case: bool = False):
    cfg, aircraft, mat_db, aero_loads = _build_structural_inputs(
        explicit_single_case=explicit_single_case,
        multi_case=multi_case,
    )
    prob = build_structural_problem(cfg, aircraft, aero_loads, mat_db)
    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
    prob.set_val("struct.seg_mapper.main_t_seg", np.full(n_seg, 0.0016), units="m")
    prob.set_val("struct.seg_mapper.main_r_seg", np.full(n_seg, 0.028), units="m")
    if cfg.rear_spar.enabled:
        prob.set_val("struct.seg_mapper.rear_t_seg", np.full(n_seg, 0.0012), units="m")
        prob.set_val("struct.seg_mapper.rear_r_seg", np.full(n_seg, 0.022), units="m")
    prob.run_model()
    return prob, cfg, aircraft, mat_db, aero_loads


def test_single_case_backward_compatibility_matches_explicit_case():
    """Legacy single-case input should match an explicit one-case configuration."""
    legacy_prob, *_ = _build_problem()
    explicit_prob, *_ = _build_problem(explicit_single_case=True)

    legacy = run_analysis(legacy_prob)
    explicit = run_analysis(explicit_prob)

    assert legacy["failure"] == pytest.approx(explicit["failure"])
    assert legacy["buckling_index"] == pytest.approx(explicit["buckling_index"])
    assert legacy["twist_max_deg"] == pytest.approx(explicit["twist_max_deg"])
    assert legacy["tip_deflection_m"] == pytest.approx(explicit["tip_deflection_m"])
    assert legacy["total_mass_full_kg"] == pytest.approx(explicit["total_mass_full_kg"])


def test_multi_case_problem_builds_and_exposes_case_constraints():
    """Multi-case structural problem should run and expose per-case outputs."""
    prob, *_ = _build_problem(multi_case=True)

    assert np.isfinite(float(np.asarray(prob.get_val("struct.case_cruise.failure")).item()))
    assert np.isfinite(float(np.asarray(prob.get_val("struct.case_pullup.failure")).item()))
    assert np.isfinite(float(np.asarray(prob.get_val("struct.case_cruise.tip_deflection_m")).item()))
    assert np.isfinite(float(np.asarray(prob.get_val("struct.case_pullup.tip_deflection_m")).item()))

    with pytest.raises(KeyError):
        prob.get_val("struct.failure.failure")


def test_pullup_case_produces_higher_main_spar_stress_than_cruise():
    """The 1.5G pull-up branch should be more demanding than cruise."""
    prob, *_ = _build_problem(multi_case=True)

    cruise_vm = np.asarray(prob.get_val("struct.case_cruise.vonmises_main"))
    pullup_vm = np.asarray(prob.get_val("struct.case_pullup.vonmises_main"))
    cruise_defl = float(np.asarray(prob.get_val("struct.case_cruise.tip_deflection_m")).item())
    pullup_defl = float(np.asarray(prob.get_val("struct.case_pullup.tip_deflection_m")).item())

    assert np.max(pullup_vm) > np.max(cruise_vm)
    assert pullup_defl > cruise_defl


def test_scipy_optimizer_rejects_multi_case_configuration():
    """Multi-case optimization should stay on the OpenMDAO path for now."""
    cfg, aircraft, mat_db, aero_loads = _build_structural_inputs(multi_case=True)
    opt = SparOptimizer(cfg, aircraft, aero_loads, mat_db)

    with pytest.raises(NotImplementedError):
        opt.optimize(method="scipy")


def test_load_case_aero_scale_is_applied_to_external_aero_loads():
    """Per-case aero_scale should amplify aero loads without changing gravity scaling."""
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")
    cfg.flight.cases = [
        LoadCaseConfig(
            name="cruise",
            aero_scale=1.0,
            nz=1.0,
            velocity=cfg.flight.velocity,
            air_density=cfg.flight.air_density,
        )
    ]

    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)

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
    mapped = mapper.map_loads(fake_load, aircraft.wing.y)
    mat_db = MaterialDB()

    prob_base = build_structural_problem(cfg, aircraft, {"cruise": mapped}, mat_db)
    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
    prob_base.set_val("struct.seg_mapper.main_t_seg", np.full(n_seg, 0.0016), units="m")
    prob_base.set_val("struct.seg_mapper.main_r_seg", np.full(n_seg, 0.028), units="m")
    if cfg.rear_spar.enabled:
        prob_base.set_val("struct.seg_mapper.rear_t_seg", np.full(n_seg, 0.0012), units="m")
        prob_base.set_val("struct.seg_mapper.rear_r_seg", np.full(n_seg, 0.022), units="m")
    prob_base.run_model()
    base_tip = float(np.asarray(prob_base.get_val("struct.tip_defl.tip_deflection_m")).item())

    cfg.flight.cases[0].aero_scale = 2.0
    prob_scaled = build_structural_problem(cfg, aircraft, {"cruise": mapped}, mat_db)
    prob_scaled.set_val("struct.seg_mapper.main_t_seg", np.full(n_seg, 0.0016), units="m")
    prob_scaled.set_val("struct.seg_mapper.main_r_seg", np.full(n_seg, 0.028), units="m")
    if cfg.rear_spar.enabled:
        prob_scaled.set_val("struct.seg_mapper.rear_t_seg", np.full(n_seg, 0.0012), units="m")
        prob_scaled.set_val("struct.seg_mapper.rear_r_seg", np.full(n_seg, 0.022), units="m")
    prob_scaled.run_model()
    scaled_tip = float(np.asarray(prob_scaled.get_val("struct.tip_defl.tip_deflection_m")).item())

    assert scaled_tip > base_tip * 1.8
