from pathlib import Path

import pytest
from pydantic import ValidationError

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
    assert cfg.launch.mode == "restrained_pre_spin"
    assert cfg.launch.prop_ready_before_release is True
    assert cfg.launch.release_speed_mps == pytest.approx(8.0)
    assert cfg.launch.release_rpm == pytest.approx(140.0)
    assert cfg.launch.min_trim_margin_deg == pytest.approx(2.0)
    assert cfg.launch.min_stall_margin == pytest.approx(0.10)
    assert cfg.prop.blade_count == 2
    assert cfg.prop.diameter_m == pytest.approx(3.0)
    assert cfg.prop.rpm_min == pytest.approx(100.0)
    assert cfg.prop.rpm_max == pytest.approx(160.0)
    assert cfg.prop.position_mode == "between_wing_and_tail"
    assert cfg.launch.platform_height_m == pytest.approx(10.0)
    assert cfg.turn.required_bank_angle_deg == pytest.approx(15.0)
    assert cfg.segmentation.min_segment_length_m == pytest.approx(1.0)
    assert cfg.segmentation.max_segment_length_m == pytest.approx(3.0)
    assert cfg.geometry_family.span_candidates_m == (30.0, 32.0, 34.0)
    assert cfg.geometry_family.taper_ratio_candidates == (0.30, 0.35, 0.40)
    assert cfg.geometry_family.dihedral_root_deg_candidates == (0.0, 1.0, 2.0)
    assert cfg.geometry_family.dihedral_tip_deg_candidates == (4.0, 6.0, 8.0)
    assert cfg.geometry_family.dihedral_exponent_candidates == (1.0, 1.5, 2.0)
    assert cfg.pipeline.stations_per_half == 7
    assert cfg.pipeline.keep_top_n == 5
    assert cfg.output.export_candidate_bundle is True
    assert cfg.output.export_vsp is False
    assert cfg.output.export_vsp_for_top_n == 0


def test_load_concept_config_rejects_unexpected_key():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_concept_config(
        repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    ).model_dump()
    cfg["unexpected_key"] = "boom"

    with pytest.raises(ValidationError, match="unexpected_key"):
        BirdmanConceptConfig.model_validate(cfg)


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


def test_launch_min_stall_margin_must_be_physical():
    with pytest.raises(ValueError, match="launch.min_stall_margin"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "launch": {"min_stall_margin": 2.0},
            }
        )


def test_load_concept_config_rejects_inverted_speed_sweep_bounds():
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    with pytest.raises(ValueError, match="speed_sweep_max_mps"):
        BirdmanConceptConfig.model_validate(
            {
                **load_concept_config(cfg_path).model_dump(),
                "mission": {
                    "target_distance_km": 42.195,
                    "rider_model": "fake_anchor_curve",
                    "anchor_power_w": 300.0,
                    "anchor_duration_min": 30.0,
                    "speed_sweep_min_mps": 10.0,
                    "speed_sweep_max_mps": 6.0,
                    "speed_sweep_points": 9,
                },
            }
        )


def test_load_concept_config_rejects_equal_speed_sweep_bounds():
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    with pytest.raises(ValueError, match="speed_sweep_max_mps"):
        BirdmanConceptConfig.model_validate(
            {
                **load_concept_config(cfg_path).model_dump(),
                "mission": {
                    "target_distance_km": 42.195,
                    "rider_model": "fake_anchor_curve",
                    "anchor_power_w": 300.0,
                    "anchor_duration_min": 30.0,
                    "speed_sweep_min_mps": 8.0,
                    "speed_sweep_max_mps": 8.0,
                    "speed_sweep_points": 9,
                },
            }
        )


def test_load_concept_config_rejects_nonpositive_and_unsorted_mass_sweep():
    with pytest.raises(ValueError, match="gross_mass_sweep_kg"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 94.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
            }
        )

    with pytest.raises(ValueError, match="gross_mass_sweep_kg"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 0.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
            }
        )


def test_load_concept_config_treats_reference_mass_as_independent():
    cfg = BirdmanConceptConfig.model_validate(
        {
            "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
            "mass": {
                "pilot_mass_kg": 60.0,
                "baseline_aircraft_mass_kg": 40.0,
                "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
            },
            "mission": {"target_distance_km": 42.195},
        }
    )

    assert cfg.mass.baseline_aircraft_mass_kg == pytest.approx(40.0)
    assert cfg.mass.gross_mass_sweep_kg == (95.0, 100.0, 105.0)


def test_load_concept_config_rejects_impossible_geometry_candidates():
    with pytest.raises(ValueError, match="geometry_family"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "geometry_family": {
                    "span_candidates_m": [30.0, -32.0, 34.0],
                    "wing_area_candidates_m2": [26.0, 28.0, 30.0],
                    "taper_ratio_candidates": [0.3, 1.2, 0.4],
                    "twist_tip_candidates_deg": [-2.0, -90.0, -1.0],
                    "tail_area_candidates_m2": [3.8, 4.2, 4.6],
                },
            }
        )


def test_load_concept_config_rejects_twist_out_of_bounds():
    with pytest.raises(ValueError, match="twist_tip_candidates_deg"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "geometry_family": {
                    "span_candidates_m": [30.0, 32.0, 34.0],
                    "wing_area_candidates_m2": [26.0, 28.0, 30.0],
                    "taper_ratio_candidates": [0.3, 0.35, 0.4],
                    "twist_tip_candidates_deg": [-2.0, -10.1, -1.0],
                    "tail_area_candidates_m2": [3.8, 4.2, 4.6],
                },
            }
        )


def test_load_concept_config_rejects_duplicate_geometry_candidates():
    with pytest.raises(ValueError, match="span_candidates_m"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "geometry_family": {
                    "span_candidates_m": [30.0, 30.0, 34.0],
                    "wing_area_candidates_m2": [26.0, 28.0, 30.0],
                    "taper_ratio_candidates": [0.3, 0.35, 0.4],
                    "twist_tip_candidates_deg": [-2.0, -1.5, -1.0],
                    "tail_area_candidates_m2": [3.8, 4.2, 4.6],
                },
            }
        )


def test_load_concept_config_rejects_invalid_dihedral_candidate_bounds():
    with pytest.raises(ValueError, match="dihedral_tip_deg_candidates"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "geometry_family": {
                    "span_candidates_m": [30.0, 32.0, 34.0],
                    "wing_area_candidates_m2": [26.0, 28.0, 30.0],
                    "taper_ratio_candidates": [0.3, 0.35, 0.4],
                    "twist_tip_candidates_deg": [-2.0, -1.5, -1.0],
                    "tail_area_candidates_m2": [3.8, 4.2, 4.6],
                    "dihedral_root_deg_candidates": [2.0, 4.0, 6.0],
                    "dihedral_tip_deg_candidates": [1.0, 3.0, 5.0],
                    "dihedral_exponent_candidates": [1.0, 1.5, 2.0],
                },
            }
        )


def test_load_concept_config_rejects_invalid_prop_rpm_bounds():
    with pytest.raises(ValueError, match="rpm_max"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "prop": {
                    "blade_count": 2,
                    "diameter_m": 3.0,
                    "rpm_min": 160.0,
                    "rpm_max": 100.0,
                    "position_mode": "between_wing_and_tail",
                },
            }
        )


def test_load_concept_config_rejects_invalid_pipeline_top_n():
    with pytest.raises(ValueError, match="keep_top_n"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "pipeline": {"stations_per_half": 7, "keep_top_n": 0},
            }
        )
