import math
from pathlib import Path

import pytest

from hpa_mdo.concept.config import (
    JigShapeGateConfig,
    TubeSystemGeometryConfig,
    load_concept_config,
)
from hpa_mdo.concept.geometry import enumerate_geometry_concepts
from hpa_mdo.concept.jig_shape import estimate_tip_deflection_ratio


_GRAVITY = 9.80665


def _build_tube_geom(
    *,
    root_outer_diameter_m: float = 0.070,
    root_wall_thickness_m: float = 0.0007,
    num_spars_per_wing: int = 2,
    num_wings: int = 2,
) -> TubeSystemGeometryConfig:
    return TubeSystemGeometryConfig(
        estimation_enabled=True,
        root_outer_diameter_m=root_outer_diameter_m,
        tip_outer_diameter_m=0.040,
        root_wall_thickness_m=root_wall_thickness_m,
        tip_wall_thickness_m=0.0005,
        density_kg_per_m3=1600.0,
        num_spars_per_wing=num_spars_per_wing,
        num_wings=num_wings,
    )


def _build_gate_cfg(
    *,
    spar_vertical_separation_m: float = 0.10,
    deflection_taper_correction_factor: float = 1.0,
) -> JigShapeGateConfig:
    return JigShapeGateConfig(
        enabled=True,
        spar_youngs_modulus_pa=120.0e9,
        spar_vertical_separation_m=spar_vertical_separation_m,
        deflection_taper_correction_factor=deflection_taper_correction_factor,
        max_tip_deflection_to_halfspan_ratio=0.30,
    )


def test_tip_deflection_ratio_matches_uniform_cantilever_formula_no_separation():
    tube_geom = _build_tube_geom(num_spars_per_wing=1)
    gate_cfg = _build_gate_cfg(
        spar_vertical_separation_m=0.0,
        deflection_taper_correction_factor=1.0,
    )
    gross_mass_kg = 100.0
    span_m = 30.0
    half_span_m = 0.5 * span_m
    weight_n = gross_mass_kg * _GRAVITY
    distributed_load = weight_n / (2 * half_span_m)
    inertia = math.pi * 0.070**3 * 0.0007 / 8.0
    bending_stiffness = 120.0e9 * inertia
    expected_deflection = distributed_load * half_span_m**4 / (8.0 * bending_stiffness)
    expected_ratio = expected_deflection / half_span_m

    actual_ratio = estimate_tip_deflection_ratio(
        gross_mass_kg=gross_mass_kg,
        span_m=span_m,
        tube_geom=tube_geom,
        gate_cfg=gate_cfg,
    )
    assert actual_ratio == pytest.approx(expected_ratio, rel=1e-12)


def test_tip_deflection_ratio_drops_with_parallel_axis_separation():
    tube_geom = _build_tube_geom(num_spars_per_wing=2)
    gate_no_sep = _build_gate_cfg(spar_vertical_separation_m=0.0)
    gate_with_sep = _build_gate_cfg(spar_vertical_separation_m=0.10)

    ratio_no_sep = estimate_tip_deflection_ratio(
        gross_mass_kg=100.0,
        span_m=30.0,
        tube_geom=tube_geom,
        gate_cfg=gate_no_sep,
    )
    ratio_with_sep = estimate_tip_deflection_ratio(
        gross_mass_kg=100.0,
        span_m=30.0,
        tube_geom=tube_geom,
        gate_cfg=gate_with_sep,
    )
    assert ratio_with_sep < ratio_no_sep


def test_tip_deflection_ratio_taper_factor_scales_linearly():
    tube_geom = _build_tube_geom()
    gate_unit = _build_gate_cfg(deflection_taper_correction_factor=1.0)
    gate_double = _build_gate_cfg(deflection_taper_correction_factor=2.0)

    ratio_unit = estimate_tip_deflection_ratio(
        gross_mass_kg=100.0,
        span_m=30.0,
        tube_geom=tube_geom,
        gate_cfg=gate_unit,
    )
    ratio_double = estimate_tip_deflection_ratio(
        gross_mass_kg=100.0,
        span_m=30.0,
        tube_geom=tube_geom,
        gate_cfg=gate_double,
    )
    assert ratio_double == pytest.approx(2.0 * ratio_unit, rel=1e-12)


def test_tip_deflection_ratio_scales_with_span_squared_at_fixed_weight():
    tube_geom = _build_tube_geom(num_spars_per_wing=1)
    gate_cfg = _build_gate_cfg(
        spar_vertical_separation_m=0.0,
        deflection_taper_correction_factor=1.0,
    )
    ratio_short = estimate_tip_deflection_ratio(
        gross_mass_kg=100.0,
        span_m=30.0,
        tube_geom=tube_geom,
        gate_cfg=gate_cfg,
    )
    ratio_long = estimate_tip_deflection_ratio(
        gross_mass_kg=100.0,
        span_m=36.0,
        tube_geom=tube_geom,
        gate_cfg=gate_cfg,
    )
    span_ratio_squared = (36.0 / 30.0) ** 2
    assert ratio_long == pytest.approx(ratio_short * span_ratio_squared, rel=1e-12)


def test_tip_deflection_ratio_raises_on_nonpositive_span():
    tube_geom = _build_tube_geom()
    gate_cfg = _build_gate_cfg()
    with pytest.raises(ValueError):
        estimate_tip_deflection_ratio(
            gross_mass_kg=100.0,
            span_m=0.0,
            tube_geom=tube_geom,
            gate_cfg=gate_cfg,
        )


def test_accepted_concepts_carry_tip_deflection_ratio_when_gate_enabled():
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    assert cfg.jig_shape_gate.enabled
    concepts = enumerate_geometry_concepts(cfg)
    assert concepts, "baseline must yield at least one accepted concept"
    limit = float(cfg.jig_shape_gate.max_tip_deflection_to_halfspan_ratio)
    for concept in concepts:
        ratio = concept.tip_deflection_ratio_at_design_mass
        assert ratio is not None
        assert 0.0 <= ratio <= limit


def test_accepted_concepts_omit_tip_deflection_ratio_when_gate_disabled():
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg.jig_shape_gate.enabled = False
    concepts = enumerate_geometry_concepts(cfg)
    assert concepts
    for concept in concepts:
        assert concept.tip_deflection_ratio_at_design_mass is None
