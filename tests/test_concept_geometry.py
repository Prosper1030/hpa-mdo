from pathlib import Path

import pytest

from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    build_linear_wing_stations,
    build_segment_plan,
    enumerate_geometry_concepts,
    get_last_geometry_enumeration_diagnostics,
)
from hpa_mdo.concept.mass_closure import close_area_mass


def test_build_segment_plan_respects_min_and_max_segment_length():
    cfg = load_concept_config(
        Path(__file__).resolve().parents[1] / "configs" / "birdman_upstream_concept_baseline.yaml"
    )

    lengths = build_segment_plan(
        half_span_m=16.5,
        min_segment_length_m=cfg.segmentation.min_segment_length_m,
        max_segment_length_m=cfg.segmentation.max_segment_length_m,
    )

    assert pytest.approx(sum(lengths)) == 16.5
    assert all(
        cfg.segmentation.min_segment_length_m <= item <= cfg.segmentation.max_segment_length_m
        for item in lengths
    )


def test_build_linear_wing_stations_returns_monotone_stations():
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=28.0,
        root_chord_m=1.30,
        tip_chord_m=0.45,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
        dihedral_root_deg=0.0,
        dihedral_tip_deg=6.0,
        dihedral_exponent=1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.5, 3.0, 3.0, 3.0, 3.0, 2.5),
    )

    stations = build_linear_wing_stations(concept, stations_per_half=7)

    assert stations[0].y_m == pytest.approx(0.0)
    assert stations[-1].y_m == pytest.approx(16.0)
    assert [station.y_m for station in stations] == sorted(station.y_m for station in stations)
    assert stations[0].chord_m > stations[-1].chord_m
    assert stations[0].twist_deg > stations[-1].twist_deg
    assert stations[0].dihedral_deg == pytest.approx(0.0)
    assert stations[-1].dihedral_deg == pytest.approx(6.0)
    assert [station.dihedral_deg for station in stations] == sorted(
        station.dihedral_deg for station in stations
    )


def test_build_linear_wing_stations_interpolates_progressive_dihedral_schedule():
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=28.0,
        root_chord_m=1.30,
        tip_chord_m=0.45,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
        dihedral_root_deg=1.0,
        dihedral_tip_deg=5.0,
        dihedral_exponent=2.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.5, 3.0, 3.0, 3.0, 3.0, 2.5),
    )

    stations = build_linear_wing_stations(concept, stations_per_half=7)

    assert stations[0].dihedral_deg == pytest.approx(1.0)
    assert stations[-1].dihedral_deg == pytest.approx(5.0)
    assert stations[3].dihedral_deg == pytest.approx(
        1.0 + (stations[3].y_m / (concept.span_m / 2.0)) ** 2 * 4.0
    )


def test_build_linear_wing_stations_preserves_segment_boundaries():
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=28.0,
        root_chord_m=1.30,
        tip_chord_m=0.45,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
        dihedral_root_deg=0.0,
        dihedral_tip_deg=6.0,
        dihedral_exponent=1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.5, 3.0, 3.0, 3.0, 3.0, 2.5),
    )

    stations = build_linear_wing_stations(concept, stations_per_half=10)
    boundary_chain = (0.0, 1.5, 4.5, 7.5, 10.5, 13.5, 16.0)

    assert len(stations) == 10
    assert [station.y_m for station in stations] == sorted(station.y_m for station in stations)
    assert all(
        any(station.y_m == pytest.approx(boundary_y_m) for station in stations)
        for boundary_y_m in boundary_chain
    )
    assert any(
        boundary_y_m < station.y_m < next_boundary_y_m
        for boundary_y_m, next_boundary_y_m in zip(boundary_chain, boundary_chain[1:])
        for station in stations
    )


def test_build_linear_wing_stations_allocates_extra_points_by_span_coverage():
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=27.2,
        root_chord_m=1.20,
        tip_chord_m=0.50,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
        dihedral_root_deg=0.0,
        dihedral_tip_deg=6.0,
        dihedral_exponent=1.0,
        tail_area_m2=3.8,
        cg_xc=0.30,
        segment_lengths_m=(1.0, 1.0, 1.0, 1.0, 6.0, 6.0),
    )

    stations = build_linear_wing_stations(concept, stations_per_half=13)
    boundaries = (0.0, 1.0, 2.0, 3.0, 4.0, 10.0, 16.0)

    interior_counts = []
    for start_y_m, end_y_m in zip(boundaries, boundaries[1:]):
        interior_counts.append(
            sum(start_y_m < station.y_m < end_y_m for station in stations)
        )

    assert all(
        any(station.y_m == pytest.approx(boundary_y_m) for station in stations)
        for boundary_y_m in boundaries
    )
    assert interior_counts[4] > 0
    assert interior_counts[5] > 0
    assert max(interior_counts[4:]) > min(interior_counts[:4])


def test_build_linear_wing_stations_rejects_too_few_stations():
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=28.0,
        root_chord_m=1.30,
        tip_chord_m=0.45,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
        dihedral_root_deg=0.0,
        dihedral_tip_deg=6.0,
        dihedral_exponent=1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.5, 3.0, 3.0, 3.0, 3.0, 2.5),
    )

    with pytest.raises(ValueError, match="stations_per_half"):
        build_linear_wing_stations(concept, stations_per_half=6)


def test_geometry_concept_rejects_nonphysical_inputs():
    with pytest.raises(ValueError, match="cg_xc"):
        GeometryConcept(
            span_m=32.0,
            wing_area_m2=28.0,
            root_chord_m=1.30,
            tip_chord_m=0.45,
            twist_root_deg=2.0,
            twist_tip_deg=-1.5,
            dihedral_root_deg=0.0,
            dihedral_tip_deg=6.0,
            dihedral_exponent=1.0,
            tail_area_m2=4.0,
            cg_xc=1.1,
            segment_lengths_m=(1.5, 3.0, 3.0, 3.0, 3.0, 2.5),
        )

    with pytest.raises(ValueError, match="trapezoidal wing area"):
        GeometryConcept(
            span_m=32.0,
            wing_area_m2=25.0,
            root_chord_m=1.30,
            tip_chord_m=0.45,
            twist_root_deg=2.0,
            twist_tip_deg=-1.5,
            dihedral_root_deg=0.0,
            dihedral_tip_deg=6.0,
            dihedral_exponent=1.0,
            tail_area_m2=4.0,
            cg_xc=0.30,
            segment_lengths_m=(1.5, 3.0, 3.0, 3.0, 3.0, 2.5),
        )


def test_geometry_concept_normalizes_segment_lengths_to_tuple():
    segment_lengths = [1.5, 3.0, 3.0, 3.0, 3.0, 2.5]

    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=28.0,
        root_chord_m=1.30,
        tip_chord_m=0.45,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
        dihedral_root_deg=0.0,
        dihedral_tip_deg=6.0,
        dihedral_exponent=1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=segment_lengths,
    )

    segment_lengths[0] = 9.9

    assert isinstance(concept.segment_lengths_m, tuple)
    assert concept.segment_lengths_m == (1.5, 3.0, 3.0, 3.0, 3.0, 2.5)


def test_enumerate_geometry_concepts_generates_multiple_candidates():
    cfg = load_concept_config(
        Path(__file__).resolve().parents[1] / "configs" / "birdman_upstream_concept_baseline.yaml"
    )
    concepts = enumerate_geometry_concepts(cfg)
    diagnostics = get_last_geometry_enumeration_diagnostics()

    assert diagnostics is not None
    assert diagnostics.sampling_mode == "latin_hypercube"
    assert diagnostics.requested_sample_count == 48
    assert 1 <= len(concepts) <= diagnostics.requested_sample_count

    first = concepts[0]
    assert first.wing_loading_target_Npm2 is not None
    assert first.wing_area_is_derived is True
    assert first.design_gross_mass_kg != pytest.approx(cfg.mass.design_gross_mass_kg)
    assert first.wing_area_m2 == pytest.approx(
        first.design_gross_mass_kg * 9.80665 / first.wing_loading_target_Npm2
    )
    assert first.root_chord_m == pytest.approx(
        2.0
        * first.wing_area_m2
        / (first.span_m * (1.0 + first.taper_ratio))
    )
    assert first.tip_chord_m == pytest.approx(first.root_chord_m * first.taper_ratio)
    assert sum(first.segment_lengths_m) == pytest.approx(first.span_m / 2.0)
    assert any(abs(concept.span_m - round(concept.span_m)) > 1.0e-6 for concept in concepts)
    assert any(
        abs(float(concept.wing_loading_target_Npm2) - round(float(concept.wing_loading_target_Npm2)))
        > 1.0e-6
        for concept in concepts
        if concept.wing_loading_target_Npm2 is not None
    )


def test_enumerate_geometry_concepts_uses_area_coupled_design_mass():
    cfg_path = Path(__file__).resolve().parents[1] / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = load_concept_config(cfg_path).model_dump(mode="python")
    payload["geometry_family"]["sampling"]["sample_count"] = 1
    payload["geometry_family"]["primary_ranges"] = {
        "span_m": {"min": 32.0, "max": 32.0},
        "wing_loading_target_Npm2": {"min": 34.0, "max": 34.0},
        "taper_ratio": {"min": 0.30, "max": 0.30},
        "tip_twist_deg": {"min": -1.0, "max": -1.0},
    }
    cfg = BirdmanConceptConfig.model_validate(payload)
    expected = close_area_mass(
        wing_loading_target_Npm2=34.0,
        pilot_mass_kg=cfg.mass.pilot_mass_kg,
        fixed_non_area_aircraft_mass_kg=cfg.mass_closure.fixed_nonwing_aircraft_mass_kg,
        wing_areal_density_kgpm2=cfg.mass_closure.rib_skin_areal_density_kgpm2,
        tube_system_mass_kg=cfg.mass_closure.tube_system_mass_kg,
        wing_fittings_base_kg=cfg.mass_closure.wing_fittings_base_kg,
        wire_terminal_mass_kg=cfg.mass_closure.wire_terminal_mass_kg,
        extra_system_margin_kg=cfg.mass_closure.system_margin_kg,
        initial_wing_area_m2=cfg.design_gross_weight_n / 34.0,
    )

    concepts = enumerate_geometry_concepts(cfg)

    assert len(concepts) == 1
    concept = concepts[0]
    assert concept.design_gross_mass_kg == pytest.approx(expected.closed_gross_mass_kg)
    assert concept.wing_area_m2 == pytest.approx(expected.closed_wing_area_m2)
    assert concept.wing_area_m2 < cfg.design_gross_weight_n / 34.0


def test_enumerate_geometry_concepts_rejects_mass_closure_above_hard_max():
    cfg_path = Path(__file__).resolve().parents[1] / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = load_concept_config(cfg_path).model_dump(mode="python")
    payload["geometry_family"]["sampling"]["sample_count"] = 1
    payload["geometry_family"]["primary_ranges"] = {
        "span_m": {"min": 34.7, "max": 34.7},
        "wing_loading_target_Npm2": {"min": 21.187, "max": 21.187},
        "taper_ratio": {"min": 0.30, "max": 0.30},
        "tip_twist_deg": {"min": -1.0, "max": -1.0},
    }
    payload["geometry_family"]["hard_constraints"]["wing_area_m2_range"] = {
        "min": 1.0,
        "max": 90.0,
    }
    payload["geometry_family"]["hard_constraints"]["aspect_ratio_range"] = {
        "min": 1.0,
        "max": 90.0,
    }
    cfg = BirdmanConceptConfig.model_validate(payload)

    concepts = enumerate_geometry_concepts(cfg)
    diagnostics = get_last_geometry_enumeration_diagnostics()

    assert concepts == ()
    assert diagnostics is not None
    assert diagnostics.rejection_reason_counts["mass_hard_max_exceeded"] == 1


def test_enumerate_geometry_concepts_tracks_clear_rejection_reasons():
    cfg_path = Path(__file__).resolve().parents[1] / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = load_concept_config(cfg_path).model_dump(mode="python")
    payload["geometry_family"]["sampling"]["sample_count"] = 4
    payload["geometry_family"]["primary_ranges"] = {
        "span_m": {"min": 30.0, "max": 30.0},
        "wing_loading_target_Npm2": {"min": 34.0, "max": 34.0},
        "taper_ratio": {"min": 0.24, "max": 0.24},
        "tip_twist_deg": {"min": -1.0, "max": -1.0},
    }
    payload["geometry_family"]["hard_constraints"]["root_chord_min_m"] = 1.80
    cfg = BirdmanConceptConfig.model_validate(payload)

    concepts = enumerate_geometry_concepts(cfg)
    diagnostics = get_last_geometry_enumeration_diagnostics()

    assert concepts == ()
    assert diagnostics is not None
    assert diagnostics.rejected_concept_count == 4
    assert diagnostics.rejection_reason_counts["root_chord_below_min"] == 4
