from pathlib import Path

import pytest

from hpa_mdo.concept import BirdmanConceptConfig, load_concept_config


def test_load_concept_config_reads_birdman_baseline():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_concept_config(
        repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    )

    assert cfg.environment.temperature_c == pytest.approx(33.0)
    assert cfg.environment.relative_humidity == pytest.approx(80.0)
    assert cfg.mass.pilot_mass_kg == pytest.approx(60.0)
    assert cfg.mass.gross_mass_sweep_kg == (95.0, 100.0, 105.0)
    assert cfg.launch.platform_height_m == pytest.approx(10.0)
    assert cfg.turn.required_bank_angle_deg == pytest.approx(15.0)
    assert cfg.segmentation.min_segment_length_m == pytest.approx(1.0)
    assert cfg.segmentation.max_segment_length_m == pytest.approx(3.0)
    assert cfg.geometry_family.span_candidates_m == (30.0, 32.0, 34.0)
    assert cfg.geometry_family.taper_ratio_candidates == (0.30, 0.35, 0.40)


def test_segment_length_bounds_must_be_ordered():
    with pytest.raises(ValueError, match="min_segment_length_m"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "segmentation": {
                    "min_segment_length_m": 3.5,
                    "max_segment_length_m": 3.0,
                },
            }
        )
