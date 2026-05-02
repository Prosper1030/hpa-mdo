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
    assert cfg.mass.pilot_mass_kg == pytest.approx(62.5)
    assert cfg.mass.pilot_mass_cases_kg == (61.0, 62.5, 64.0)
    assert cfg.mass.design_pilot_mass_kg == pytest.approx(62.5)
    assert cfg.mass.baseline_aircraft_mass_kg == pytest.approx(36.0)
    assert cfg.mass.aircraft_empty_mass_cases_kg == (30.0, 36.0, 42.0)
    assert cfg.mass.design_aircraft_empty_mass_kg == pytest.approx(36.0)
    assert cfg.mass.gross_mass_sweep_kg == (91.0, 98.5, 106.0)
    assert cfg.mass.design_gross_mass_kg == pytest.approx(98.5)
    assert cfg.mass.use_gross_mass_sweep_for_mission_cases is True
    assert cfg.mass_closure.enabled is True
    assert cfg.mass_closure.fixed_nonwing_aircraft_mass_kg == pytest.approx(24.0)
    assert cfg.mass_closure.tube_system_mass_kg == pytest.approx(10.5)
    assert cfg.mass_closure.tube_system.estimation_enabled is True
    assert cfg.mass_closure.tube_system.root_outer_diameter_m == pytest.approx(0.070)
    assert cfg.mass_closure.tube_system.tip_outer_diameter_m == pytest.approx(0.035)
    assert cfg.mass_closure.tube_system.root_wall_thickness_m == pytest.approx(0.0007)
    assert cfg.mass_closure.tube_system.tip_wall_thickness_m == pytest.approx(0.0004)
    assert cfg.mass_closure.tube_system.density_kg_per_m3 == pytest.approx(1600.0)
    assert cfg.mass_closure.tube_system.num_spars_per_wing == 2
    assert cfg.mass_closure.tube_system.num_wings == 2
    assert cfg.mass_closure.rib_skin_areal_density_kgpm2 == pytest.approx(0.20)
    assert cfg.mass_closure.gross_mass_hard_max_kg == pytest.approx(115.0)
    assert cfg.mission.objective_mode == "fixed_range_best_time"
    assert cfg.mission.resolved_rider_model == "csv_power_curve"
    assert cfg.mission.rider_power_curve_csv is not None
    assert Path(cfg.mission.rider_power_curve_csv).is_file()
    assert cfg.mission.rider_power_curve_metadata_yaml is not None
    assert Path(cfg.mission.rider_power_curve_metadata_yaml).is_file()
    assert cfg.mission.rider_power_curve_thermal_adjustment_enabled is True
    assert cfg.mission.rider_power_curve_heat_loss_coefficient_per_h_c == pytest.approx(0.008)
    assert cfg.mission.speed_sweep_min_mps == pytest.approx(6.4)
    assert cfg.mission.speed_sweep_max_mps == pytest.approx(7.2)
    assert cfg.mission.speed_sweep_points == 5
    assert cfg.mission.slow_report_speeds_mps == (6.0,)
    assert cfg.launch.mode == "restrained_pre_spin"
    assert cfg.launch.prop_ready_before_release is True
    assert cfg.launch.release_speed_mps == pytest.approx(8.0)
    assert cfg.launch.release_rpm == pytest.approx(140.0)
    assert cfg.launch.min_trim_margin_deg == pytest.approx(2.0)
    assert cfg.stall_model.safe_clmax_scale == pytest.approx(0.90)
    assert cfg.stall_model.safe_clmax_delta == pytest.approx(0.05)
    assert cfg.stall_model.tip_3d_penalty_start_eta == pytest.approx(0.55)
    assert cfg.stall_model.tip_3d_penalty_max == pytest.approx(0.04)
    assert cfg.stall_model.tip_taper_penalty_weight == pytest.approx(0.35)
    assert cfg.stall_model.washout_relief_deg == pytest.approx(2.0)
    assert cfg.stall_model.washout_relief_max == pytest.approx(0.02)
    assert cfg.stall_model.local_stall_utilization_limit == pytest.approx(0.75)
    assert cfg.stall_model.turn_utilization_limit == pytest.approx(0.75)
    assert cfg.stall_model.launch_utilization_limit == pytest.approx(0.85)
    assert cfg.stall_model.slow_speed_report_utilization_limit == pytest.approx(0.85)
    assert cfg.prop.blade_count == 2
    assert cfg.prop.diameter_m == pytest.approx(3.0)
    assert cfg.prop.rpm_min == pytest.approx(100.0)
    assert cfg.prop.rpm_max == pytest.approx(160.0)
    assert cfg.prop.position_mode == "between_wing_and_tail"
    assert cfg.prop.efficiency_model.design_efficiency == pytest.approx(0.86)
    assert cfg.prop.efficiency_model.peak_speed_mps == pytest.approx(8.5)
    assert cfg.prop.efficiency_model.peak_shaft_power_w == pytest.approx(280.0)
    assert cfg.prop.efficiency_model.speed_falloff_per_mps == pytest.approx(0.015)
    assert cfg.prop.efficiency_model.power_falloff_per_w == pytest.approx(0.0004)
    assert cfg.prop.efficiency_model.speed_term_floor == pytest.approx(0.70)
    assert cfg.prop.efficiency_model.power_term_floor == pytest.approx(0.75)
    assert cfg.prop.efficiency_model.efficiency_floor == pytest.approx(0.50)
    assert cfg.prop.efficiency_model.efficiency_ceiling == pytest.approx(0.90)
    assert cfg.prop.efficiency_model.use_bemt_proxy is False
    assert cfg.prop.efficiency_model.bemt_blade_loss_constant == pytest.approx(0.174)
    assert cfg.prop.efficiency_model.bemt_profile_loss == pytest.approx(0.07)
    assert cfg.prop.efficiency_model.bemt_peak_advance_ratio == pytest.approx(1.10)
    assert cfg.prop.efficiency_model.bemt_advance_ratio_falloff == pytest.approx(0.10)
    assert cfg.prop.efficiency_model.bemt_advance_ratio_floor == pytest.approx(0.50)
    assert cfg.prop.efficiency_model.bemt_design_rpm == pytest.approx(140.0)
    assert cfg.prop.efficiency_model.bemt_v_tip_max_mps == pytest.approx(60.0)
    assert cfg.prop.efficiency_model.bemt_v_tip_penalty_slope == pytest.approx(0.5)
    assert cfg.launch.platform_height_m == pytest.approx(10.0)
    assert cfg.turn.required_bank_angle_deg == pytest.approx(15.0)
    assert cfg.rigging_drag.enabled is True
    assert cfg.rigging_drag.wire_diameter_m == pytest.approx(0.0020)
    assert cfg.rigging_drag.total_exposed_length_m == pytest.approx(24.0)
    assert cfg.rigging_drag.drag_coefficient == pytest.approx(1.10)
    assert cfg.rigging_drag.cda_override_m2 is None
    assert cfg.jig_shape_gate.enabled is True
    assert cfg.jig_shape_gate.spar_youngs_modulus_pa == pytest.approx(120.0e9)
    assert cfg.jig_shape_gate.spar_vertical_separation_m == pytest.approx(0.10)
    assert cfg.jig_shape_gate.deflection_taper_correction_factor == pytest.approx(1.7)
    assert cfg.jig_shape_gate.max_tip_deflection_to_halfspan_ratio == pytest.approx(0.30)
    assert cfg.jig_shape_gate.lift_wire_relief_enabled is True
    assert cfg.jig_shape_gate.lift_wire_attach_span_fraction == pytest.approx(0.70)
    assert cfg.jig_shape_gate.lift_wire_cruise_lift_fraction_carried == pytest.approx(0.35)
    assert cfg.jig_shape_gate.preferred_tip_deflection_m_min == pytest.approx(1.6)
    assert cfg.jig_shape_gate.preferred_tip_deflection_m_max == pytest.approx(2.2)
    assert cfg.lift_wire_gate.enabled is True
    assert cfg.lift_wire_gate.allowable_tension_n == pytest.approx(5000.0)
    assert cfg.lift_wire_gate.limit_load_factor == pytest.approx(1.75)
    assert cfg.lift_wire_gate.wing_lift_fraction_carried == pytest.approx(0.75)
    assert cfg.drivetrain.efficiency == pytest.approx(0.96)
    assert cfg.aero_proxies.parasite_drag.fuselage_misc_cd == pytest.approx(0.0035)
    assert cfg.aero_proxies.parasite_drag.tail_profile_coupling_factor == pytest.approx(0.20)
    assert cfg.aero_proxies.oswald_efficiency.base_efficiency == pytest.approx(0.88)
    assert cfg.aero_proxies.oswald_efficiency.dihedral_delta_slope_per_deg == pytest.approx(0.012)
    assert cfg.aero_proxies.oswald_efficiency.twist_delta_slope_per_deg == pytest.approx(0.008)
    assert cfg.aero_proxies.oswald_efficiency.spanload_shape_penalty_slope == pytest.approx(0.22)
    assert cfg.aero_proxies.oswald_efficiency.spanload_shape_penalty_max == pytest.approx(0.18)
    assert cfg.aero_proxies.oswald_efficiency.spanload_geometry_knockdown_weight == pytest.approx(0.50)
    assert cfg.aero_proxies.oswald_efficiency.efficiency_floor == pytest.approx(0.68)
    assert cfg.aero_proxies.oswald_efficiency.efficiency_ceiling == pytest.approx(0.92)
    assert cfg.aero_proxies.coarse_spanload.elliptic_loading_floor == pytest.approx(0.35)
    assert cfg.aero_proxies.coarse_spanload.washout_relief_fraction == pytest.approx(0.10)
    assert cfg.aero_proxies.coarse_spanload.cl_headroom_base == pytest.approx(0.24)
    assert cfg.airfoil_selection_score.drag_weight == pytest.approx(1.50)
    assert cfg.airfoil_selection_score.stall_weight == pytest.approx(4.25)
    assert cfg.airfoil_selection_score.margin_weight == pytest.approx(2.25)
    assert cfg.airfoil_selection_score.trim_weight == pytest.approx(1.25)
    assert cfg.airfoil_selection_score.spar_weight == pytest.approx(3.00)
    assert cfg.airfoil_selection_score.thickness_weight == pytest.approx(2.50)
    assert cfg.airfoil_selection_score.drag_penalty_scale == pytest.approx(0.022)
    assert cfg.airfoil_selection_score.stall_penalty_scale == pytest.approx(0.08)
    assert cfg.airfoil_selection_score.margin_target == pytest.approx(0.08)
    assert cfg.airfoil_selection_score.enforce_stall_as_hard_reject is False
    assert cfg.airfoil_selection_score.enforce_structural_as_hard_reject is False
    assert cfg.segmentation.min_segment_length_m == pytest.approx(1.0)
    assert cfg.segmentation.max_segment_length_m == pytest.approx(3.0)
    assert cfg.mass.design_gross_mass_kg == pytest.approx(98.5)
    assert cfg.geometry_family.sampling.mode == "latin_hypercube"
    assert cfg.geometry_family.sampling.sample_count == 96
    assert cfg.geometry_family.planform_parameterization == "mean_chord"
    assert cfg.geometry_family.primary_ranges.span_m.min == pytest.approx(29.5)
    assert cfg.geometry_family.primary_ranges.span_m.max == pytest.approx(35.0)
    assert cfg.geometry_family.primary_ranges.mean_chord_m.min == pytest.approx(0.78)
    assert cfg.geometry_family.primary_ranges.mean_chord_m.max == pytest.approx(1.15)
    assert cfg.geometry_family.primary_ranges.wing_loading_target_Npm2.min == pytest.approx(24.0)
    assert cfg.geometry_family.primary_ranges.wing_loading_target_Npm2.max == pytest.approx(42.0)
    assert cfg.geometry_family.primary_ranges.taper_ratio.min == pytest.approx(0.30)
    assert cfg.geometry_family.primary_ranges.taper_ratio.max == pytest.approx(0.38)
    assert cfg.geometry_family.primary_ranges.twist_mid_deg.min == pytest.approx(0.0)
    assert cfg.geometry_family.primary_ranges.twist_mid_deg.max == pytest.approx(1.25)
    assert cfg.geometry_family.primary_ranges.twist_outer_deg.min == pytest.approx(-1.0)
    assert cfg.geometry_family.primary_ranges.twist_outer_deg.max == pytest.approx(-0.25)
    assert cfg.geometry_family.primary_ranges.tip_twist_deg.min == pytest.approx(-3.5)
    assert cfg.geometry_family.primary_ranges.tip_twist_deg.max == pytest.approx(-1.0)
    assert cfg.geometry_family.primary_ranges.spanload_bias.min == pytest.approx(0.0)
    assert cfg.geometry_family.primary_ranges.spanload_bias.max == pytest.approx(0.12)
    assert cfg.geometry_family.hard_constraints.root_chord_min_m == pytest.approx(1.05)
    assert cfg.geometry_family.hard_constraints.tip_chord_min_m == pytest.approx(0.30)
    assert cfg.geometry_family.hard_constraints.wing_area_m2_range.min == pytest.approx(24.0)
    assert cfg.geometry_family.hard_constraints.wing_area_m2_range.max == pytest.approx(41.0)
    assert cfg.geometry_family.hard_constraints.aspect_ratio_range.max == pytest.approx(46.0)
    assert cfg.geometry_family.twist_root_deg == pytest.approx(2.0)
    assert cfg.geometry_family.twist_control_etas == pytest.approx((0.35, 0.70))
    assert cfg.geometry_family.spanload_bias_washout_gain_deg == pytest.approx(8.0)
    assert cfg.geometry_family.cg_xc == pytest.approx(0.30)
    assert cfg.geometry_family.tail_sizing_mode == "tail_volume"
    assert cfg.geometry_family.tail_volume_coefficient_candidates == pytest.approx(
        (0.35, 0.45, 0.55)
    )
    assert cfg.geometry_family.dihedral_root_deg_candidates == (0.0, 1.0, 2.0)
    assert cfg.geometry_family.dihedral_tip_deg_candidates == (4.0, 6.0, 8.0)
    assert cfg.geometry_family.dihedral_exponent_candidates == (1.0, 1.5, 2.0)
    assert cfg.cst_search.thickness_delta_levels == (
        -0.022,
        -0.018,
        -0.014,
        -0.010,
        -0.006,
        0.0,
        0.006,
        0.010,
        0.014,
        0.018,
        0.022,
    )
    assert cfg.cst_search.camber_delta_levels == (
        -0.016,
        -0.012,
        -0.008,
        -0.004,
        0.0,
        0.004,
        0.008,
        0.012,
        0.016,
    )
    assert cfg.cst_search.coarse_thickness_stride == 3
    assert cfg.cst_search.coarse_keep_top_k == 3
    assert cfg.cst_search.search_mode == "seedless_sobol"
    assert cfg.cst_search.seedless_sample_count == 512
    assert cfg.cst_search.seedless_max_oversample_factor == 16
    assert cfg.cst_search.successive_halving_enabled is True
    assert cfg.cst_search.successive_halving_rounds == 2
    assert cfg.cst_search.successive_halving_beam_width == 6
    assert cfg.cst_search.cma_es_enabled is True
    assert cfg.cst_search.cma_es_knee_count == 3
    assert cfg.cst_search.cma_es_iterations == 4
    assert cfg.cst_search.cma_es_population_lambda == 12
    assert cfg.cst_search.cma_es_sigma_init == pytest.approx(0.05)
    assert cfg.cst_search.cma_es_random_seed == 0
    assert cfg.pipeline.stations_per_half == 7
    assert cfg.pipeline.keep_top_n == 8
    assert cfg.pipeline.finalist_full_sweep_top_l == 4
    assert cfg.polar_worker.persistent_worker_count == 4
    assert cfg.polar_worker.log_cache_statistics is True
    assert cfg.polar_worker.xfoil_max_iter == 40
    assert cfg.polar_worker.xfoil_panel_count == 96
    assert cfg.output.export_candidate_bundle is True
    assert cfg.output.export_vsp is True
    assert cfg.output.export_vsp_for_top_n == 3


def test_load_concept_config_reads_birdman_low_speed_box_variants():
    repo_root = Path(__file__).resolve().parents[1]
    box_a = load_concept_config(
        repo_root / "configs" / "birdman_upstream_concept_box_a.yaml"
    )
    box_b = load_concept_config(
        repo_root / "configs" / "birdman_upstream_concept_box_b.yaml"
    )
    box_a_smoke = load_concept_config(
        repo_root / "configs" / "birdman_upstream_concept_box_a_smoke.yaml"
    )
    box_b_smoke = load_concept_config(
        repo_root / "configs" / "birdman_upstream_concept_box_b_smoke.yaml"
    )

    for cfg in (box_a, box_b, box_a_smoke, box_b_smoke):
        assert cfg.mass.pilot_mass_cases_kg == (61.0, 62.5, 64.0)
        assert cfg.mass.aircraft_empty_mass_cases_kg == (30.0, 36.0, 42.0)
        assert cfg.mass.gross_mass_sweep_kg == (91.0, 98.5, 106.0)
        assert cfg.mass.design_gross_mass_kg == pytest.approx(98.5)
        assert cfg.mass_closure.gross_mass_hard_max_kg == pytest.approx(115.0)

    assert box_a.mission.speed_sweep_min_mps == pytest.approx(6.4)
    assert box_a.mission.speed_sweep_max_mps == pytest.approx(7.2)
    assert box_a.geometry_family.primary_ranges.span_m.min == pytest.approx(31.0)
    assert box_a.geometry_family.primary_ranges.span_m.max == pytest.approx(35.0)
    assert box_a.geometry_family.planform_parameterization == "mean_chord"
    assert box_a.geometry_family.primary_ranges.mean_chord_m.min == pytest.approx(0.90)
    assert box_a.geometry_family.primary_ranges.mean_chord_m.max == pytest.approx(1.15)
    assert box_a.geometry_family.hard_constraints.wing_area_m2_range.max == pytest.approx(41.0)
    assert box_a.geometry_family.hard_constraints.aspect_ratio_range.max == pytest.approx(40.0)
    assert box_a.geometry_family.primary_ranges.taper_ratio == box_a_smoke.geometry_family.primary_ranges.taper_ratio
    assert box_a.geometry_family.primary_ranges.tip_twist_deg == box_a_smoke.geometry_family.primary_ranges.tip_twist_deg
    assert box_a_smoke.geometry_family.sampling.sample_count < box_a.geometry_family.sampling.sample_count

    assert box_b.mission.speed_sweep_min_mps == pytest.approx(6.4)
    assert box_b.mission.speed_sweep_max_mps == pytest.approx(7.2)
    assert box_b.geometry_family.primary_ranges.span_m.min == pytest.approx(32.0)
    assert box_b.geometry_family.primary_ranges.span_m.max == pytest.approx(35.0)
    assert box_b.geometry_family.planform_parameterization == "mean_chord"
    assert box_b.geometry_family.primary_ranges.mean_chord_m.min == pytest.approx(0.78)
    assert box_b.geometry_family.primary_ranges.mean_chord_m.max == pytest.approx(1.00)
    assert box_b.geometry_family.hard_constraints.wing_area_m2_range.max == pytest.approx(35.0)
    assert box_b.geometry_family.hard_constraints.aspect_ratio_range.max == pytest.approx(46.0)
    assert box_b.geometry_family.primary_ranges.taper_ratio == box_b_smoke.geometry_family.primary_ranges.taper_ratio
    assert box_b.geometry_family.primary_ranges.tip_twist_deg == box_b_smoke.geometry_family.primary_ranges.tip_twist_deg
    assert box_b_smoke.geometry_family.sampling.sample_count < box_b.geometry_family.sampling.sample_count


def test_load_concept_config_rejects_csv_rider_model_without_csv_path():
    with pytest.raises(ValueError, match="rider_power_curve_csv"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {
                    "target_distance_km": 42.195,
                    "rider_model": "csv_power_curve",
                },
            }
        )


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


def test_load_concept_config_rejects_legacy_launch_min_stall_margin_field():
    with pytest.raises(ValidationError, match="min_stall_margin"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "launch": {"min_stall_margin": 0.10},
            }
        )


def test_stall_model_allows_launch_transient_limit_above_cruise_limit():
    cfg = BirdmanConceptConfig.model_validate(
        {
            "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
            "mass": {
                "pilot_mass_kg": 60.0,
                "baseline_aircraft_mass_kg": 40.0,
                "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
            },
            "mission": {"target_distance_km": 42.195},
            "stall_model": {
                "safe_clmax_scale": 0.90,
                "safe_clmax_delta": 0.05,
                "launch_utilization_limit": 0.85,
                "turn_utilization_limit": 0.75,
                "local_stall_utilization_limit": 0.75,
                "slow_speed_report_utilization_limit": 0.85,
            },
        }
    )

    assert cfg.stall_model.launch_utilization_limit == pytest.approx(0.85)


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


def test_load_concept_config_rejects_slow_report_speed_above_cruise_min():
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    with pytest.raises(ValueError, match="slow_report_speeds_mps"):
        BirdmanConceptConfig.model_validate(
            {
                **load_concept_config(cfg_path).model_dump(),
                "mission": {
                    "target_distance_km": 42.195,
                    "rider_model": "fake_anchor_curve",
                    "anchor_power_w": 300.0,
                    "anchor_duration_min": 30.0,
                    "speed_sweep_min_mps": 7.0,
                    "speed_sweep_max_mps": 10.0,
                    "speed_sweep_points": 7,
                    "slow_report_speeds_mps": [7.5],
                },
            }
        )


def test_load_concept_config_rejects_unsorted_slow_report_speeds():
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    with pytest.raises(ValueError, match="slow_report_speeds_mps"):
        BirdmanConceptConfig.model_validate(
            {
                **load_concept_config(cfg_path).model_dump(),
                "mission": {
                    "target_distance_km": 42.195,
                    "rider_model": "fake_anchor_curve",
                    "anchor_power_w": 300.0,
                    "anchor_duration_min": 30.0,
                    "speed_sweep_min_mps": 7.0,
                    "speed_sweep_max_mps": 10.0,
                    "speed_sweep_points": 7,
                    "slow_report_speeds_mps": [6.5, 5.5],
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
    assert cfg.mass.design_gross_mass_kg == pytest.approx(100.0)
    assert cfg.mass.pilot_mass_cases_kg == (60.0,)
    assert cfg.mass.aircraft_empty_mass_cases_kg == (40.0,)
    assert cfg.mass.design_pilot_mass_kg == pytest.approx(60.0)
    assert cfg.mass.design_aircraft_empty_mass_kg == pytest.approx(40.0)


def test_load_concept_config_accepts_floating_pilot_and_aircraft_mass_cases():
    cfg = BirdmanConceptConfig.model_validate(
        {
            "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
            "mass": {
                "pilot_mass_kg": 62.5,
                "pilot_mass_cases_kg": [61.0, 62.5, 64.0],
                "baseline_aircraft_mass_kg": 36.0,
                "aircraft_empty_mass_cases_kg": [30.0, 36.0, 42.0],
                "gross_mass_sweep_kg": [91.0, 98.5, 106.0],
            },
            "mission": {"target_distance_km": 42.195},
        }
    )

    assert cfg.mass.design_gross_mass_kg == pytest.approx(98.5)
    assert cfg.mass.design_pilot_mass_kg == pytest.approx(62.5)
    assert cfg.mass.design_aircraft_empty_mass_kg == pytest.approx(36.0)


def test_load_concept_config_rejects_unsorted_mass_cases():
    with pytest.raises(ValueError, match="pilot_mass_cases_kg"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 62.5,
                    "pilot_mass_cases_kg": [61.0, 64.0, 62.5],
                    "baseline_aircraft_mass_kg": 38.5,
                    "aircraft_empty_mass_cases_kg": [35.0, 38.5, 42.0],
                    "gross_mass_sweep_kg": [96.0, 101.0, 106.0],
                },
                "mission": {"target_distance_km": 42.195},
            }
        )


def test_load_concept_config_rejects_impossible_geometry_candidates():
    with pytest.raises(ValueError, match="primary_ranges"):
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
                    "primary_ranges": {
                        "span_m": {"min": -32.0, "max": 34.0},
                        "wing_loading_target_Npm2": {"min": 26.0, "max": 34.0},
                        "taper_ratio": {"min": 0.3, "max": 1.2},
                        "tip_twist_deg": {"min": -90.0, "max": -1.0},
                    },
                    "tail_area_candidates_m2": [3.8, 4.2, 4.6],
                },
            }
        )


def test_load_concept_config_rejects_twist_out_of_bounds():
    with pytest.raises(ValueError, match="tip_twist_deg"):
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
                    "primary_ranges": {
                        "span_m": {"min": 30.0, "max": 34.0},
                        "wing_loading_target_Npm2": {"min": 26.0, "max": 34.0},
                        "taper_ratio": {"min": 0.3, "max": 0.4},
                        "tip_twist_deg": {"min": -10.1, "max": -1.0},
                    },
                    "tail_area_candidates_m2": [3.8, 4.2, 4.6],
                },
            }
        )


def test_load_concept_config_rejects_duplicate_geometry_candidates():
    with pytest.raises(ValueError, match="tail_area_candidates_m2"):
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
                    "tail_area_candidates_m2": [3.8, 4.2, 4.2],
                },
            }
        )


def test_load_concept_config_rejects_invalid_cst_search_levels():
    with pytest.raises(ValueError, match="cst_search"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "cst_search": {
                    "thickness_delta_levels": [-0.01, -0.01, 0.01],
                    "camber_delta_levels": [-0.01, 0.01],
                },
            }
        )


def test_load_concept_config_rejects_successive_halving_beam_width_above_candidate_count():
    with pytest.raises(ValueError, match="successive_halving_beam_width"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "cst_search": {
                    "thickness_delta_levels": [-0.01, 0.0, 0.01],
                    "camber_delta_levels": [-0.01, 0.0, 0.01],
                    "successive_halving_beam_width": 10,
                },
            }
        )


def test_load_concept_config_accepts_seedless_cst_search_mode():
    cfg = BirdmanConceptConfig.model_validate(
        {
            "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
            "mass": {
                "pilot_mass_kg": 60.0,
                "baseline_aircraft_mass_kg": 40.0,
                "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
            },
            "mission": {"target_distance_km": 42.195},
            "cst_search": {
                "search_mode": "seedless_sobol",
                "selection_strategy": "constrained_pareto",
                "seedless_sample_count": 8,
                "seedless_random_seed": 123,
                "seedless_max_oversample_factor": 4,
                "nsga_generation_count": 1,
                "nsga_offspring_count": 4,
                "nsga_parent_count": 4,
                "nsga_random_seed": 321,
                "nsga_mutation_scale": 0.08,
                "successive_halving_beam_width": 8,
            },
        }
    )

    assert cfg.cst_search.search_mode == "seedless_sobol"
    assert cfg.cst_search.selection_strategy == "constrained_pareto"
    assert cfg.cst_search.seedless_sample_count == 8
    assert cfg.cst_search.seedless_random_seed == 123
    assert cfg.cst_search.seedless_max_oversample_factor == 4
    assert cfg.cst_search.nsga_generation_count == 1
    assert cfg.cst_search.nsga_offspring_count == 4
    assert cfg.cst_search.nsga_parent_count == 4
    assert cfg.cst_search.nsga_random_seed == 321
    assert cfg.cst_search.nsga_mutation_scale == pytest.approx(0.08)


def test_load_concept_config_accepts_robust_airfoil_screening_controls():
    cfg = BirdmanConceptConfig.model_validate(
        {
            "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
            "mass": {
                "pilot_mass_kg": 60.0,
                "baseline_aircraft_mass_kg": 40.0,
                "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
            },
            "mission": {"target_distance_km": 42.195},
            "cst_search": {
                "robust_evaluation_enabled": True,
                "robust_reynolds_factors": [0.85, 1.0, 1.15],
                "robust_roughness_modes": ["clean", "rough"],
                "robust_min_pass_rate": 0.80,
            },
        }
    )

    assert cfg.cst_search.robust_evaluation_enabled is True
    assert cfg.cst_search.robust_reynolds_factors == (0.85, 1.0, 1.15)
    assert cfg.cst_search.robust_roughness_modes == ("clean", "rough")
    assert cfg.cst_search.robust_min_pass_rate == pytest.approx(0.80)


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
                    "primary_ranges": {
                        "span_m": {"min": 30.0, "max": 36.0},
                        "wing_loading_target_Npm2": {"min": 26.0, "max": 34.0},
                        "taper_ratio": {"min": 0.3, "max": 0.4},
                        "tip_twist_deg": {"min": -2.0, "max": -1.0},
                    },
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
