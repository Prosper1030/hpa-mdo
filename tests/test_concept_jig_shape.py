import math
from pathlib import Path

import pytest

from hpa_mdo.concept.config import (
    JigShapeGateConfig,
    TubeSystemGeometryConfig,
    load_concept_config,
)
from hpa_mdo.concept.geometry import enumerate_geometry_concepts
from hpa_mdo.concept.jig_shape import estimate_tip_deflection, estimate_tip_deflection_ratio


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
    lift_wire_relief_enabled: bool = False,
    lift_wire_attach_span_fraction: float = 0.70,
    lift_wire_cruise_lift_fraction_carried: float = 0.35,
) -> JigShapeGateConfig:
    return JigShapeGateConfig(
        enabled=True,
        spar_youngs_modulus_pa=120.0e9,
        spar_vertical_separation_m=spar_vertical_separation_m,
        deflection_taper_correction_factor=deflection_taper_correction_factor,
        max_tip_deflection_to_halfspan_ratio=0.30,
        lift_wire_relief_enabled=lift_wire_relief_enabled,
        lift_wire_attach_span_fraction=lift_wire_attach_span_fraction,
        lift_wire_cruise_lift_fraction_carried=lift_wire_cruise_lift_fraction_carried,
        preferred_tip_deflection_m_min=1.6,
        preferred_tip_deflection_m_max=2.2,
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


def test_tip_deflection_estimate_reduces_cantilever_deflection_with_lift_wire_relief():
    tube_geom = _build_tube_geom(num_spars_per_wing=1)
    gate_cfg = _build_gate_cfg(
        spar_vertical_separation_m=0.0,
        deflection_taper_correction_factor=1.0,
        lift_wire_relief_enabled=True,
        lift_wire_attach_span_fraction=0.70,
        lift_wire_cruise_lift_fraction_carried=0.35,
    )
    gross_mass_kg = 100.0
    span_m = 30.0
    half_span_m = 0.5 * span_m
    weight_n = gross_mass_kg * _GRAVITY
    distributed_load = weight_n / (2 * half_span_m)
    support_reaction = 0.35 * distributed_load * half_span_m
    attach_m = 0.70 * half_span_m
    inertia = math.pi * 0.070**3 * 0.0007 / 8.0
    bending_stiffness = 120.0e9 * inertia
    unbraced_deflection = distributed_load * half_span_m**4 / (8.0 * bending_stiffness)
    relief_deflection = support_reaction * attach_m**2 * (3.0 * half_span_m - attach_m) / (
        6.0 * bending_stiffness
    )

    estimate = estimate_tip_deflection(
        gross_mass_kg=gross_mass_kg,
        span_m=span_m,
        tube_geom=tube_geom,
        gate_cfg=gate_cfg,
    )

    assert estimate.unbraced_tip_deflection_m == pytest.approx(unbraced_deflection, rel=1e-12)
    assert estimate.lift_wire_relief_deflection_m == pytest.approx(relief_deflection, rel=1e-12)
    assert estimate.tip_deflection_m == pytest.approx(unbraced_deflection - relief_deflection, rel=1e-12)
    assert estimate.effective_dihedral_deg == pytest.approx(
        math.degrees(math.atan2(estimate.tip_deflection_m, half_span_m)),
        rel=1e-12,
    )


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
        assert concept.tip_deflection_m_at_design_mass is not None
        assert concept.effective_dihedral_deg_at_design_mass is not None
        assert concept.unbraced_tip_deflection_m_at_design_mass is not None
        assert concept.lift_wire_relief_deflection_m_at_design_mass is not None
        assert concept.tip_deflection_preferred_status in {
            "below_preferred",
            "within_preferred",
            "above_preferred",
        }


def test_accepted_concepts_omit_tip_deflection_ratio_when_gate_disabled():
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg.jig_shape_gate.enabled = False
    concepts = enumerate_geometry_concepts(cfg)
    assert concepts
    for concept in concepts:
        assert concept.tip_deflection_ratio_at_design_mass is None
        assert concept.tip_deflection_m_at_design_mass is None
        assert concept.effective_dihedral_deg_at_design_mass is None
        assert concept.tip_deflection_preferred_status is None
