from pathlib import Path

import pytest

from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    build_linear_wing_stations,
    build_segment_plan,
    enumerate_geometry_concepts,
)


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


def test_build_linear_wing_stations_preserves_segment_boundaries():
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=28.0,
        root_chord_m=1.30,
        tip_chord_m=0.45,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
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


def test_build_linear_wing_stations_rejects_too_few_stations():
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=28.0,
        root_chord_m=1.30,
        tip_chord_m=0.45,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
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
            tail_area_m2=4.0,
            cg_xc=0.30,
            segment_lengths_m=(1.5, 3.0, 3.0, 3.0, 3.0, 2.5),
        )


def test_enumerate_geometry_concepts_generates_multiple_candidates():
    cfg = load_concept_config(
        Path(__file__).resolve().parents[1] / "configs" / "birdman_upstream_concept_baseline.yaml"
    )
    concepts = enumerate_geometry_concepts(cfg)

    assert len(concepts) == 243

    first = concepts[0]
    assert first.span_m == pytest.approx(30.0)
    assert first.wing_area_m2 == pytest.approx(26.0)
    assert first.root_chord_m == pytest.approx(52.0 / 39.0)
    assert first.tip_chord_m == pytest.approx((52.0 / 39.0) * 0.30)
    assert sum(first.segment_lengths_m) == pytest.approx(first.span_m / 2.0)
