from pathlib import Path

import pytest

from hpa_mdo.concept.config import (
    LiftWireGateConfig,
    TubeSystemGeometryConfig,
    load_concept_config,
)
from hpa_mdo.concept.geometry import enumerate_geometry_concepts
from hpa_mdo.concept.lift_wire import estimate_lift_wire_tension_n


_GRAVITY = 9.80665


def _build_tube_geom(num_wings: int = 2) -> TubeSystemGeometryConfig:
    return TubeSystemGeometryConfig(num_wings=num_wings)


def test_estimate_lift_wire_tension_matches_closed_form():
    tube_geom = _build_tube_geom(num_wings=2)
    gate_cfg = LiftWireGateConfig(
        allowable_tension_n=5000.0,
        limit_load_factor=1.75,
        wing_lift_fraction_carried=0.75,
    )
    expected = (105.0 * _GRAVITY / 2.0) * 1.75 * 0.75
    actual = estimate_lift_wire_tension_n(
        gross_mass_kg=105.0,
        tube_geom=tube_geom,
        gate_cfg=gate_cfg,
    )
    assert actual == pytest.approx(expected, rel=1e-12)


def test_estimate_lift_wire_tension_scales_inversely_with_num_wings():
    gate_cfg = LiftWireGateConfig()
    one = estimate_lift_wire_tension_n(
        gross_mass_kg=100.0,
        tube_geom=_build_tube_geom(num_wings=1),
        gate_cfg=gate_cfg,
    )
    two = estimate_lift_wire_tension_n(
        gross_mass_kg=100.0,
        tube_geom=_build_tube_geom(num_wings=2),
        gate_cfg=gate_cfg,
    )
    assert two == pytest.approx(0.5 * one, rel=1e-12)


def test_lift_wire_gate_passes_baseline_concepts_with_default_allowable():
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    assert cfg.lift_wire_gate.enabled
    concepts = enumerate_geometry_concepts(cfg)
    assert concepts, "baseline must yield at least one accepted concept"
    allowable = float(cfg.lift_wire_gate.allowable_tension_n)
    for concept in concepts:
        tension = concept.lift_wire_tension_at_limit_n
        assert tension is not None
        assert 0.0 < tension <= allowable


def test_lift_wire_gate_rejects_when_allowable_is_below_estimate():
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    # Force the allowable below the design-gross-mass tension at default
    # load factor + fraction; every concept should be rejected as
    # lift_wire_tension_excessive.
    cfg.lift_wire_gate.allowable_tension_n = 100.0
    concepts = enumerate_geometry_concepts(cfg)
    assert concepts == ()


def test_lift_wire_gate_off_does_not_set_concept_field():
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg.lift_wire_gate.enabled = False
    concepts = enumerate_geometry_concepts(cfg)
    assert concepts
    for concept in concepts:
        assert concept.lift_wire_tension_at_limit_n is None
