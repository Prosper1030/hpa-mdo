import math
from pathlib import Path

import pytest

import scripts.birdman_spanload_design_smoke as smoke
from hpa_mdo.airfoils.database import (
    AirfoilDatabase,
    AirfoilPolarPoint,
    AirfoilRecord,
)
from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.geometry import GeometryConcept, build_linear_wing_stations


def test_fourier_summary_labels_target_not_actual_or_ranking_e() -> None:
    summary = smoke._fourier_efficiency(-0.05, 0.0)

    assert summary["target_fourier_e"] == pytest.approx(1.0 / (1.0 + 3.0 * 0.05**2))
    assert summary["target_fourier_deviation"] == pytest.approx((3.0 * 0.05**2) ** 0.5)
    assert "fourier_e" not in summary
    assert "ranking_e" not in summary


def test_accepted_leaderboards_keep_high_ar_visible() -> None:
    low_utilization = {
        "sample_index": 1,
        "geometry": {"aspect_ratio": 31.0},
        "spanload_gate_health": {"max_local_clmax_utilization": 0.55, "max_outer_clmax_utilization": 0.42},
        "target_fourier_power_proxy": {"power_required_w": 140.0},
        "avl_cdi_power_proxy": {"power_required_w": 170.0, "power_margin_w": 10.0},
    }
    high_ar = {
        "sample_index": 2,
        "geometry": {"aspect_ratio": 42.0},
        "spanload_gate_health": {"max_local_clmax_utilization": 0.70, "max_outer_clmax_utilization": 0.60},
        "target_fourier_power_proxy": {"power_required_w": 130.0},
        "avl_cdi_power_proxy": {"power_required_w": 180.0, "power_margin_w": 1.0},
    }
    low_power = {
        "sample_index": 3,
        "geometry": {"aspect_ratio": 35.0},
        "spanload_gate_health": {"max_local_clmax_utilization": 0.58, "max_outer_clmax_utilization": 0.50},
        "target_fourier_power_proxy": {"power_required_w": 200.0},
        "avl_cdi_power_proxy": {"power_required_w": 150.0, "power_margin_w": 30.0},
    }

    leaderboards = smoke._select_accepted_leaderboards(
        [low_utilization, high_ar, low_power],
        per_board_count=1,
    )

    assert leaderboards["highest_AR_physical_accepted"][0]["sample_index"] == 2
    assert leaderboards["best_avl_cdi_power_proxy_accepted"][0]["sample_index"] == 3
    assert leaderboards["best_power_margin_accepted"][0]["sample_index"] == 3
    assert leaderboards["lowest_utilization_accepted"][0]["sample_index"] == 1


def test_twist_physical_gates_reject_outer_washin_bump() -> None:
    stations = (
        smoke.WingStation(y_m=0.0, chord_m=1.2, twist_deg=2.0, dihedral_deg=0.0),
        smoke.WingStation(y_m=4.0, chord_m=1.0, twist_deg=1.0, dihedral_deg=0.0),
        smoke.WingStation(y_m=10.0, chord_m=0.8, twist_deg=4.6, dihedral_deg=0.0),
        smoke.WingStation(y_m=12.0, chord_m=0.7, twist_deg=3.8, dihedral_deg=0.0),
        smoke.WingStation(y_m=16.0, chord_m=0.5, twist_deg=-2.0, dihedral_deg=0.0),
    )

    metrics = smoke._twist_gate_metrics(stations)

    assert metrics["twist_physical_gates_pass"] is False
    assert metrics["max_outer_washin_bump_deg"] > 2.0
    assert "outer_washin_bump_exceeded" in metrics["twist_gate_failures"]


def test_regularized_twist_initial_guess_stays_within_physical_bounds() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = GeometryConcept(
        span_m=34.0,
        wing_area_m2=32.0,
        root_chord_m=1.34,
        tip_chord_m=0.5423529411764706,
        twist_root_deg=2.0,
        twist_tip_deg=-2.0,
        twist_control_points=((0.0, 2.0), (0.35, 0.5), (0.70, -1.2), (1.0, -2.0)),
        spanload_a3_over_a1=-0.05,
        spanload_a5_over_a1=0.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(2.5, 2.5, 3.0, 3.0, 3.0, 3.0),
        design_gross_mass_kg=98.5,
    )
    baseline_stations = build_linear_wing_stations(concept, stations_per_half=7)

    inverse_stations, summary = smoke._build_regularized_twist_initial_stations(
        cfg=cfg,
        concept=concept,
        stations=baseline_stations,
        design_speed_mps=6.8,
    )

    assert summary["model"] == "regularized_inverse_twist_initial_lift_curve"
    assert len(inverse_stations) == len(baseline_stations)
    assert inverse_stations[0].twist_deg == pytest.approx(2.0)
    metrics = smoke._twist_gate_metrics(inverse_stations)
    assert metrics["twist_range_deg"] <= 7.0
    assert metrics["max_adjacent_twist_jump_deg"] <= 2.0


def test_candidate_physical_status_requires_e_load_twist_and_power() -> None:
    base = {
        "avl_reference_case": {"avl_e_cdi": 0.90},
        "avl_match_metrics": {"max_target_avl_circulation_norm_delta": 0.10, "rms_target_avl_circulation_norm_delta": 0.05},
        "twist_gate_metrics": {"twist_physical_gates_pass": True},
        "spanload_gate_health": {
            "local_margin_to_limit": 0.1,
            "outer_margin_to_limit": 0.1,
        },
        "tip_gate_summary": {"tip_gates_pass": True},
        "avl_cdi_power_proxy": {"power_margin_w": -20.0},
    }
    assert smoke._physical_acceptance_status(base)["status"] == "physically_acceptable"

    bad_twist = {
        **base,
        "twist_gate_metrics": {
            "twist_physical_gates_pass": False,
            "twist_gate_failures": ["twist_range_exceeded"],
        },
    }
    assert smoke._physical_acceptance_status(bad_twist)["status"] == "spanload_matched_but_twist_unphysical"


def test_inverse_chord_geometry_uses_cl_schedule_not_linear_taper() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))

    metric, rejection = smoke._build_inverse_chord_stage0_metric(
        cfg=cfg,
        sample_index=7,
        span_m=34.5,
        tail_volume_coefficient=0.42,
        a3=-0.06,
        a5=0.01,
        cl_controls=(1.16, 1.28, 0.98, 0.55),
        design_speed_mps=6.8,
    )

    assert rejection is None
    assert metric is not None
    assert metric["spanload_to_geometry"]["mode"] == "inverse_chord_then_inverse_twist"
    stations = metric["stations"]
    assert stations[0].chord_m == pytest.approx(metric["geometry"]["root_chord_m"])
    assert 1.15 <= metric["geometry"]["root_chord_m"] <= 1.45
    assert metric["geometry"]["tip_chord_m"] >= 0.43
    assert metric["tip_gate_summary"]["chord_at_aerodynamic_tip_eta_m"] >= 0.42
    mid_linear_chord = 0.5 * (stations[0].chord_m + stations[-1].chord_m)
    assert abs(stations[len(stations) // 2].chord_m - mid_linear_chord) > 0.03
    assert metric["spanload_to_geometry"]["local_cl_schedule"]["control_etas"] == [0.0, 0.35, 0.7, 0.95]


def test_new_mode_does_not_reject_on_target_avl_delta_alone() -> None:
    base = {
        "avl_reference_case": {"avl_e_cdi": 0.88},
        "avl_match_metrics": {"max_target_avl_circulation_norm_delta": 0.35, "rms_target_avl_circulation_norm_delta": 0.14},
        "twist_gate_metrics": {"twist_physical_gates_pass": True},
        "spanload_gate_health": {
            "local_margin_to_limit": 0.05,
            "outer_margin_to_limit": 0.05,
        },
        "tip_gate_summary": {"tip_gates_pass": True},
        "avl_cdi_power_proxy": {"power_margin_w": -30.0},
    }

    status = smoke._physical_acceptance_status(base, target_delta_is_hard_gate=False)

    assert status["status"] == "physically_acceptable"
    assert "target_avl_max_delta_exceeded" not in status["failure_reasons"]


def test_engineering_leaderboards_include_requested_inverse_chord_boards() -> None:
    records = [
        {
            "sample_index": 1,
            "status": "physically_acceptable",
            "geometry": {"aspect_ratio": 38.0},
            "physical_acceptance": {"physically_acceptable": True, "failure_reasons": []},
            "avl_reference_case": {"avl_e_cdi": 0.86},
            "avl_cdi_power_proxy": {"power_required_w": 240.0, "power_margin_w": -20.0},
            "twist_gate_metrics": {"twist_physical_gates_pass": True},
            "spanload_gate_health": {"local_margin_to_limit": 0.1, "outer_margin_to_limit": 0.1},
            "tip_gate_summary": {"tip_gates_pass": True},
        },
        {
            "sample_index": 2,
            "status": "physically_acceptable",
            "geometry": {"aspect_ratio": 35.0},
            "physical_acceptance": {"physically_acceptable": True, "failure_reasons": []},
            "avl_reference_case": {"avl_e_cdi": 0.91},
            "avl_cdi_power_proxy": {"power_required_w": 230.0, "power_margin_w": -10.0},
            "twist_gate_metrics": {"twist_physical_gates_pass": True},
            "spanload_gate_health": {"local_margin_to_limit": 0.1, "outer_margin_to_limit": 0.1},
            "tip_gate_summary": {"tip_gates_pass": True},
        },
        {
            "sample_index": 3,
            "status": "rejected",
            "geometry": {"aspect_ratio": 40.0},
            "physical_acceptance": {"physically_acceptable": False, "failure_reasons": ["twist_physical_gates_failed"]},
            "avl_reference_case": {"avl_e_cdi": 0.89},
            "avl_cdi_power_proxy": {"power_required_w": 235.0, "power_margin_w": -15.0},
            "twist_gate_metrics": {"twist_physical_gates_pass": False, "twist_gate_failures": ["twist_range_exceeded"]},
            "spanload_gate_health": {"local_margin_to_limit": 0.1, "outer_margin_to_limit": 0.1},
            "tip_gate_summary": {"tip_gates_pass": True},
        },
        {
            "sample_index": 4,
            "status": "rejected",
            "geometry": {"aspect_ratio": 41.0},
            "physical_acceptance": {"physically_acceptable": False, "failure_reasons": ["tip_geometry_gates_failed"]},
            "avl_reference_case": {"avl_e_cdi": 0.87},
            "avl_cdi_power_proxy": {"power_required_w": 236.0, "power_margin_w": -16.0},
            "twist_gate_metrics": {"twist_physical_gates_pass": True},
            "spanload_gate_health": {"local_margin_to_limit": 0.1, "outer_margin_to_limit": 0.1},
            "tip_gate_summary": {"tip_gates_pass": False},
        },
    ]

    leaderboards = smoke._select_engineering_leaderboards(records, per_board_count=1)

    assert leaderboards["highest_AR_engineering_candidate"][0]["sample_index"] == 1
    assert leaderboards["best_AVL_e_CDi_candidate"][0]["sample_index"] == 2
    assert leaderboards["best_AVL_CDi_power_proxy_candidate"][0]["sample_index"] == 2
    assert leaderboards["closest_rejected_due_to_twist"][0]["sample_index"] == 3
    assert leaderboards["closest_rejected_due_to_tip_or_local_cl"][0]["sample_index"] == 4


def test_top_candidate_export_uses_seed_airfoil_files_not_naca_fallback(tmp_path: Path) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    metric, rejection = smoke._build_inverse_chord_stage0_metric(
        cfg=cfg,
        sample_index=8,
        span_m=34.0,
        tail_volume_coefficient=0.40,
        a3=-0.05,
        a5=0.0,
        cl_controls=(1.16, 1.26, 0.96, 0.58),
        design_speed_mps=6.8,
    )
    assert rejection is None
    assert metric is not None
    record = {
        "sample_index": 8,
        "geometry": metric["geometry"],
        "spanload_fourier": metric["spanload_fourier"],
        "station_table": [
            {
                "eta": row["eta"],
                "y_m": row["y_m"],
                "chord_m": row["chord_m"],
                "avl_local_cl": row["target_local_cl"],
                "twist_deg": 0.0,
                "ainc_deg": 0.0,
                "dihedral_deg": 0.0,
            }
            for row in metric["station_table"]
        ],
        "avl_reference_case": {"avl_case_dir": str(tmp_path / "avl_case")},
        "mission_CL_req": 1.18,
        "mission_CD_wing_profile_target": 0.0128,
        "mission_CD_wing_profile_boundary": 0.0135,
        "mission_CDA_nonwing_target_m2": 0.13,
        "mission_CDA_nonwing_boundary_m2": 0.16,
        "mission_power_margin_required_w": 5.0,
        "mission_contract_source": "unit_test_context",
        "mission_contract": {
            "speed_mps": 6.8,
            "span_m": metric["geometry"]["span_m"],
            "aspect_ratio": metric["geometry"]["aspect_ratio"],
            "wing_area_m2": metric["geometry"]["wing_area_m2"],
            "mass_kg": 98.5,
            "weight_n": 98.5 * 9.80665,
            "rho": 1.14,
            "CL_req": 1.18,
            "target_range_km": 42.195,
            "required_time_min": 42.195 * 1000.0 / 6.8 / 60.0,
            "eta_prop": 0.88,
            "eta_trans": 0.96,
            "pilot_power_hot_w": 205.0,
            "power_margin_required_w": 5.0,
            "CD0_total_target": 0.017,
            "CD0_total_boundary": 0.018,
            "CD0_total_rescue": 0.020,
            "CD_wing_profile_target": 0.0128,
            "CD_wing_profile_boundary": 0.0135,
            "CDA_nonwing_target_m2": 0.13,
            "CDA_nonwing_boundary_m2": 0.16,
            "CLmax_effective_assumption": 1.55,
            "mission_contract_source": "unit_test_context",
            "source_mode": "shadow_no_ranking_gate",
        },
    }
    smoke._attach_mission_fourier_shadow_fields([record])
    smoke._attach_loaded_shape_jig_shadow_fields([record])
    smoke._attach_airfoil_profile_drag_shadow_fields([record])
    record["zone_envelope"] = [
        {
            "zone_name": "root",
            "eta_min": 0.0,
            "eta_max": 0.25,
            "re_min": 100000.0,
            "re_max": 120000.0,
            "re_p50": 110000.0,
            "cl_min": 0.9,
            "cl_max": 1.1,
            "cl_p50": 1.0,
            "cl_p90": 1.08,
            "max_avl_actual_cl": 1.1,
            "max_fourier_target_cl": 1.0,
            "target_vs_actual_cl_delta": -0.1,
            "current_airfoil_id": "fx76mp140",
            "current_stall_margin": 3.0,
            "current_profile_cd_estimate": 0.012,
            "source": "loaded_dihedral_avl",
        }
    ]
    record["zone_airfoil_topk"] = {
        "root": [
            {
                "zone_name": "root",
                "airfoil_id": "fx76mp140",
                "score": 0.02,
                "source_quality": "not_mission_grade_sidecar",
            }
        ]
    }
    record["airfoil_sidecar"] = {
        "source": "zone_airfoil_sidecar_avl_rerun_shadow_v1",
        "source_mode": "shadow_no_ranking_gate",
        "ranking_behavior": "unchanged_no_rejection_no_sort_key",
    }
    record["airfoil_sidecar_combinations"] = [
        {
            "combination_index": 0,
            "status": "ok",
            "is_baseline": True,
            "assignment_label": "root:fx76mp140|mid1:fx76mp140|mid2:clarkysm|tip:clarkysm",
            "CL": 1.18,
            "CDi": 0.015,
            "e_CDi": 0.92,
            "target_vs_avl_rms": 0.02,
            "target_vs_avl_max": 0.04,
            "target_vs_avl_outer_delta": 0.03,
            "profile_cd_airfoil_db": 0.012,
            "cd0_total_est_airfoil_db": 0.016,
            "mission_drag_budget_band": "target",
            "min_stall_margin_airfoil_db": 2.5,
            "max_station_cl_utilization_airfoil_db": 0.72,
            "source_quality": "not_mission_grade_sidecar",
            "profile_drag_cl_source_shape_mode": "loaded_dihedral_avl",
            "profile_drag_cl_source_loaded_shape": True,
            "profile_drag_cl_source_warning_count": 0,
            "airfoil_profile_drag": {
                "station_rows": [
                    {
                        "eta": 0.0,
                        "y": 0.0,
                        "chord": 1.0,
                        "Re": 100000.0,
                        "cl_actual_avl": 1.0,
                        "airfoil_id": "fx76mp140",
                        "cd_profile": 0.012,
                        "cm": -0.08,
                        "stall_margin_deg": 2.5,
                        "source_quality": "manual_placeholder_not_mission_grade",
                        "warning_flags": [],
                        "profile_drag_cl_source_shape_mode": "loaded_dihedral_avl",
                        "profile_drag_cl_source_loaded_shape": True,
                    }
                ]
            },
        }
    ]
    record["airfoil_sidecar_best"] = record["airfoil_sidecar_combinations"][0]
    record.update(
        {
            "sidecar_best_airfoil_assignment": record["airfoil_sidecar_best"][
                "assignment_label"
            ],
            "sidecar_best_e_CDi": 0.92,
            "sidecar_best_target_vs_avl_rms": 0.02,
            "sidecar_best_target_vs_avl_outer_delta": 0.03,
            "sidecar_best_profile_cd": 0.012,
            "sidecar_best_cd0_total_est": 0.016,
            "sidecar_best_min_stall_margin": 2.5,
            "sidecar_best_source_quality": "not_mission_grade_sidecar",
            "sidecar_improved_vs_baseline": False,
            "sidecar_improvement_notes": ["baseline_assignment_remains_best_sidecar"],
        }
    )
    avl_file = tmp_path / "avl_case" / "concept_wing.avl"
    avl_file.parent.mkdir(parents=True)
    avl_file.write_text("SECTION\nAFILE\n", encoding="utf-8")

    artifacts = smoke._export_top_candidate_artifacts(
        cfg=cfg,
        record=record,
        output_dir=tmp_path,
        rank=1,
    )

    assert Path(artifacts["avl_file_path"]).is_file()
    assert Path(artifacts["station_table_csv_path"]).is_file()
    assert Path(artifacts["mission_contract_json_path"]).is_file()
    assert Path(artifacts["mission_contract_csv_path"]).is_file()
    assert Path(artifacts["fourier_target_json_path"]).is_file()
    assert Path(artifacts["fourier_target_csv_path"]).is_file()
    assert Path(artifacts["airfoil_profile_drag_json_path"]).is_file()
    assert Path(artifacts["airfoil_profile_drag_csv_path"]).is_file()
    assert Path(artifacts["zone_envelope_json_path"]).is_file()
    assert Path(artifacts["zone_envelope_csv_path"]).is_file()
    assert Path(artifacts["airfoil_sidecar_combinations_csv_path"]).is_file()
    assert Path(artifacts["airfoil_sidecar_best_json_path"]).is_file()
    assert "target_circulation" in Path(artifacts["station_table_csv_path"]).read_text(encoding="utf-8").splitlines()[0]
    mission_contract = Path(artifacts["mission_contract_json_path"]).read_text(encoding="utf-8")
    assert "mission_CL_req" in mission_contract
    assert "mission_CD_wing_profile_target" in mission_contract
    assert "mission_contract_source" in Path(artifacts["mission_contract_csv_path"]).read_text(encoding="utf-8").splitlines()[0]
    airfoil_profile_drag = Path(artifacts["airfoil_profile_drag_json_path"]).read_text(
        encoding="utf-8"
    )
    assert "profile_cd_airfoil_db" in airfoil_profile_drag
    assert "cd0_total_est_airfoil_db" in airfoil_profile_drag
    assert "profile_drag_cl_source_shape_mode" in airfoil_profile_drag
    airfoil_profile_drag_csv_header = Path(artifacts["airfoil_profile_drag_csv_path"]).read_text(
        encoding="utf-8"
    ).splitlines()[0]
    assert "cl_actual_avl" in airfoil_profile_drag_csv_header
    assert "cd_profile" in airfoil_profile_drag_csv_header
    fourier_target_csv_header = Path(artifacts["fourier_target_csv_path"]).read_text(
        encoding="utf-8"
    ).splitlines()[0]
    assert "gamma_target" in fourier_target_csv_header
    assert "cl_target" in fourier_target_csv_header
    zone_envelope = Path(artifacts["zone_envelope_json_path"]).read_text(encoding="utf-8")
    assert "loaded_dihedral_avl" in zone_envelope
    assert "zone_airfoil_topk" in zone_envelope
    sidecar_csv_header = Path(artifacts["airfoil_sidecar_combinations_csv_path"]).read_text(
        encoding="utf-8"
    ).splitlines()[0]
    assert "assignment_label" in sidecar_csv_header
    assert "profile_drag_cl_source_shape_mode" in sidecar_csv_header
    sidecar_best = Path(artifacts["airfoil_sidecar_best_json_path"]).read_text(
        encoding="utf-8"
    )
    assert "sidecar_best_profile_cd" in sidecar_best
    metadata = Path(artifacts["vsp_metadata_path"]).read_text(encoding="utf-8")
    script = Path(artifacts["vsp_script_path"]).read_text(encoding="utf-8")
    assert "selected_cst_dat_files" in metadata
    assert "ReadFileAirfoil" in script
    assert "NACA 0012" not in script


def test_loaded_shape_jig_shadow_attach_preserves_ranking_inputs() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    metric, rejection = smoke._build_inverse_chord_stage0_metric(
        cfg=cfg,
        sample_index=12,
        span_m=34.0,
        tail_volume_coefficient=0.40,
        a3=-0.05,
        a5=0.01,
        cl_controls=(1.16, 1.26, 0.96, 0.58),
        design_speed_mps=6.8,
    )
    assert rejection is None
    assert metric is not None
    record = {
        "sample_index": 12,
        "geometry": metric["geometry"],
        "station_table": [dict(row) for row in metric["station_table"]],
        "objective_value": 4.25,
    }
    before_objective = record["objective_value"]

    smoke._attach_loaded_shape_jig_shadow_fields([record])

    assert record["objective_value"] == before_objective
    assert record["loaded_shape_mode"] in {"concept_dihedral_fields", "flat"}
    assert record["loaded_tip_z_m"] is not None
    assert record["jig_source_quality"] in {
        "concept_jig_shape_estimate_tip_deflection_shadow",
        "placeholder_not_structure_grade",
    }
    assert "jig_feasible_shadow" in record
    assert record["jig_warning_count"] >= 0
    compact = smoke._stage1_compact_record(record)
    assert compact["loaded_shape_mode"] == record["loaded_shape_mode"]
    assert "jig_feasibility_band" in compact


def test_loaded_shape_shadow_prefers_station_dihedral_over_tip_formula() -> None:
    record = {
        "geometry": {
            "span_m": 20.0,
            "dihedral_tip_deg": 6.0,
            "dihedral_exponent": 1.5,
        },
        "station_table": [
            {"eta": 0.0, "y_m": 0.0, "chord_m": 1.0, "dihedral_deg": 0.0},
            {"eta": 0.5, "y_m": 5.0, "chord_m": 1.0, "dihedral_deg": 2.0},
            {"eta": 1.0, "y_m": 10.0, "chord_m": 1.0, "dihedral_deg": 4.0},
        ],
    }

    smoke._attach_loaded_shape_jig_shadow_fields([record])

    assert record["loaded_shape_source"] == "station_table_dihedral_fields_shadow"
    assert record["loaded_tip_z_m"] == pytest.approx(
        5.0 * math.tan(math.radians(1.0)) + 5.0 * math.tan(math.radians(3.0))
    )
    assert record["loaded_tip_z_m"] != pytest.approx(10.0 * math.tan(math.radians(6.0)))


def test_mission_fourier_shadow_attach_preserves_ranking_inputs() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    metric, rejection = smoke._build_inverse_chord_stage0_metric(
        cfg=cfg,
        sample_index=9,
        span_m=34.0,
        tail_volume_coefficient=0.40,
        a3=-0.05,
        a5=0.01,
        cl_controls=(1.16, 1.26, 0.96, 0.58),
        design_speed_mps=6.8,
    )
    assert rejection is None
    assert metric is not None
    records = [
        {
            "sample_index": 9,
            "geometry": metric["geometry"],
            "spanload_fourier": metric["spanload_fourier"],
            "station_table": [
                {
                    **row,
                    "avl_circulation_proxy": row["target_circulation_proxy"],
                    "avl_local_cl": row["target_local_cl"],
                }
                for row in metric["station_table"]
            ],
            "mission_contract": {
                "speed_mps": 6.8,
                "span_m": metric["geometry"]["span_m"],
                "aspect_ratio": metric["geometry"]["aspect_ratio"],
                "wing_area_m2": metric["geometry"]["wing_area_m2"],
                "mass_kg": 98.5,
                "weight_n": 98.5 * 9.80665,
                "rho": 1.14,
                "CL_req": 1.18,
                "target_range_km": 42.195,
                "required_time_min": 42.195 * 1000.0 / 6.8 / 60.0,
                "eta_prop": 0.88,
                "eta_trans": 0.96,
                "pilot_power_hot_w": 205.0,
                "power_margin_required_w": 5.0,
                "CD0_total_target": 0.017,
                "CD0_total_boundary": 0.018,
                "CD0_total_rescue": 0.020,
                "CD_wing_profile_target": 0.0128,
                "CD_wing_profile_boundary": 0.0135,
                "CDA_nonwing_target_m2": 0.13,
                "CDA_nonwing_boundary_m2": 0.16,
                "CLmax_effective_assumption": 1.55,
                "mission_contract_source": "unit_test_context",
                "source_mode": "shadow_no_ranking_gate",
            },
            "objective_value": 3.5,
        },
    ]
    before_order = [record["sample_index"] for record in records]
    before_objectives = [record["objective_value"] for record in records]

    smoke._attach_mission_fourier_shadow_fields(records)

    assert [record["sample_index"] for record in records] == before_order
    assert [record["objective_value"] for record in records] == before_objectives
    record = records[0]
    assert record["mission_fourier_e_target"] < 1.0
    assert record["mission_fourier_r3"] == pytest.approx(-0.05)
    assert record["mission_fourier_r5"] == pytest.approx(0.01)
    assert record["mission_fourier_cl_max"] > 0.0
    assert record["mission_fourier_outer_lift_ratio"] > 0.0
    assert record["mission_fourier_root_bending_proxy"] > 0.0
    assert record["target_vs_avl_rms_delta"] is not None
    assert record["target_vs_avl_max_delta"] is not None
    compact = smoke._stage1_compact_record(record)
    assert compact["mission_fourier_e_target"] == pytest.approx(
        record["mission_fourier_e_target"]
    )
    assert "target_vs_avl_rms_delta" in compact


def test_airfoil_profile_drag_shadow_attach_preserves_ranking_inputs() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    metric, rejection = smoke._build_inverse_chord_stage0_metric(
        cfg=cfg,
        sample_index=10,
        span_m=34.0,
        tail_volume_coefficient=0.40,
        a3=-0.05,
        a5=0.01,
        cl_controls=(1.16, 1.26, 0.96, 0.58),
        design_speed_mps=6.8,
    )
    assert rejection is None
    assert metric is not None
    record = {
        "sample_index": 10,
        "geometry": metric["geometry"],
        "station_table": [
            {
                **row,
                "avl_local_cl": 0.50,
                "target_local_cl": 1.20,
            }
            for row in metric["station_table"]
        ],
        "mission_contract": {
            "speed_mps": 6.8,
            "span_m": metric["geometry"]["span_m"],
            "aspect_ratio": metric["geometry"]["aspect_ratio"],
            "wing_area_m2": metric["geometry"]["wing_area_m2"],
            "mass_kg": 98.5,
            "weight_n": 98.5 * 9.80665,
            "rho": 1.14,
            "CL_req": 1.18,
            "target_range_km": 42.195,
            "required_time_min": 42.195 * 1000.0 / 6.8 / 60.0,
            "eta_prop": 0.88,
            "eta_trans": 0.96,
            "pilot_power_hot_w": 205.0,
            "power_margin_required_w": 5.0,
            "CD0_total_target": 0.017,
            "CD0_total_boundary": 0.018,
            "CD0_total_rescue": 0.020,
            "CD_wing_profile_target": 0.0128,
            "CD_wing_profile_boundary": 0.0135,
            "CDA_nonwing_target_m2": 0.13,
            "CDA_nonwing_boundary_m2": 0.16,
            "CLmax_effective_assumption": 1.55,
            "mission_contract_source": "unit_test_context",
            "source_mode": "shadow_no_ranking_gate",
        },
        "objective_value": 4.25,
    }
    before_objective = record["objective_value"]

    smoke._attach_airfoil_profile_drag_shadow_fields([record])

    assert record["objective_value"] == before_objective
    assert record["profile_cd_airfoil_db"] > 0.0
    assert record["cd0_total_est_airfoil_db"] == pytest.approx(
        record["profile_cd_airfoil_db"]
        + 0.13 / record["mission_contract"]["wing_area_m2"]
    )
    assert "not_mission_grade" in record["profile_cd_airfoil_db_source_quality"]
    assert record["mission_drag_budget_band_airfoil_db"] in {
        "target",
        "boundary",
        "rescue",
        "over_budget",
    }
    assert record["profile_drag_station_warning_count"] >= 0
    assert record["profile_drag_cl_source_shape_mode"] == "flat_or_unverified_loaded_shape"
    assert record["profile_drag_cl_source_loaded_shape"] is False
    assert record["profile_drag_cl_source_warning_count"] >= 1
    assert record["max_station_cl_utilization_airfoil_db"] > 0.0
    compact = smoke._stage1_compact_record(record)
    assert compact["profile_cd_airfoil_db"] == pytest.approx(
        record["profile_cd_airfoil_db"]
    )
    assert "cd0_total_est_airfoil_db" in compact
    assert compact["profile_drag_cl_source_shape_mode"] == "flat_or_unverified_loaded_shape"


def _sidecar_test_database() -> AirfoilDatabase:
    def record(airfoil_id: str) -> AirfoilRecord:
        points = tuple(
            AirfoilPolarPoint(
                Re=re_value,
                cl=cl_value,
                cd=0.010 + 0.004 * cl_value,
                cm=-0.05,
                alpha_deg=8.0 * cl_value,
            )
            for re_value in (100_000.0, 410_000.0)
            for cl_value in (0.0, 0.5, 1.1, 1.4)
        )
        return AirfoilRecord(
            airfoil_id=airfoil_id,
            name=airfoil_id,
            source="unit_test_fixture",
            source_quality="manual_placeholder_not_mission_grade",
            zone_hint="unit_test",
            thickness_ratio=0.12,
            max_camber=0.03,
            alpha_L0_deg=-2.0,
            cl_alpha_per_rad=2.0 * math.pi,
            cm_design=-0.05,
            safe_clmax=1.4,
            usable_clmax=1.5,
            polar_points=points,
            notes="unit test sidecar fixture",
        )

    return AirfoilDatabase.from_records((record("fx76mp140"), record("clarkysm")))


def _sidecar_record(metric: dict, *, objective_value: float = 4.25) -> dict:
    return {
        "sample_index": 14,
        "status": "physically_acceptable",
        "physical_acceptance_status": "physically_acceptable",
        "physical_acceptance": {"physically_acceptable": True, "failure_reasons": []},
        "geometry": metric["geometry"],
        "spanload_fourier": metric["spanload_fourier"],
        "station_table": [
            {
                **row,
                "avl_local_cl": 0.20,
                "avl_circulation_proxy": 0.20 * row["chord_m"],
                "target_circulation_norm": row.get("target_circulation_norm", 1.0),
                "dihedral_deg": 5.0 * row["eta"],
            }
            for row in metric["station_table"]
        ],
        "mission_contract": {
            "speed_mps": 6.8,
            "span_m": metric["geometry"]["span_m"],
            "aspect_ratio": metric["geometry"]["aspect_ratio"],
            "wing_area_m2": metric["geometry"]["wing_area_m2"],
            "mass_kg": 98.5,
            "weight_n": 98.5 * 9.80665,
            "rho": 1.14,
            "CL_req": 1.18,
            "target_range_km": 42.195,
            "required_time_min": 42.195 * 1000.0 / 6.8 / 60.0,
            "eta_prop": 0.88,
            "eta_trans": 0.96,
            "pilot_power_hot_w": 205.0,
            "power_margin_required_w": 5.0,
            "CD0_total_target": 0.017,
            "CD0_total_boundary": 0.018,
            "CD0_total_rescue": 0.020,
            "CD_wing_profile_target": 0.0128,
            "CD_wing_profile_boundary": 0.0135,
            "CDA_nonwing_target_m2": 0.13,
            "CDA_nonwing_boundary_m2": 0.16,
            "CLmax_effective_assumption": 1.55,
            "mission_contract_source": "unit_test_context",
            "source_mode": "shadow_no_ranking_gate",
        },
        "objective_value": objective_value,
    }


def test_airfoil_sidecar_profile_drag_uses_rerun_avl_actual_cl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    metric, rejection = smoke._build_inverse_chord_stage0_metric(
        cfg=cfg,
        sample_index=14,
        span_m=34.0,
        tail_volume_coefficient=0.40,
        a3=-0.05,
        a5=0.01,
        cl_controls=(1.16, 1.26, 0.96, 0.58),
        design_speed_mps=6.8,
    )
    assert rejection is None
    assert metric is not None
    record = _sidecar_record(metric)

    def fake_run_reference_avl_case(**kwargs):
        stations = kwargs["stations"]
        return {
            "status": "ok",
            "trim_cl": 1.18,
            "trim_cd_induced": 0.015,
            "avl_e_cdi": 0.92,
            "profile_drag_cl_source_shape_mode": "loaded_dihedral_avl",
            "profile_drag_cl_source_loaded_shape": True,
            "profile_drag_cl_source_warning_count": 0,
            "station_points": [
                {
                    "station_y_m": station.y_m,
                    "chord_m": station.chord_m,
                    "cl_target": 1.10,
                    "reynolds": 150_000.0,
                }
                for station in stations
            ],
        }

    monkeypatch.setattr(smoke, "_run_reference_avl_case", fake_run_reference_avl_case)

    result = smoke._evaluate_airfoil_sidecar_combination(
        cfg=cfg,
        record=record,
        combination=smoke.fixed_seed_zone_airfoil_assignments(),
        combination_index=0,
        output_dir=tmp_path,
        design_speed_mps=6.8,
        avl_binary=None,
        database=_sidecar_test_database(),
        is_baseline=True,
    )

    assert result["status"] == "ok"
    station_rows = result["airfoil_profile_drag"]["station_rows"]
    assert all(row["cl_actual_avl"] == pytest.approx(1.10) for row in station_rows)
    assert all(row["cl_actual_avl"] != pytest.approx(0.20) for row in station_rows)
    assert result["profile_drag_cl_source_shape_mode"] == "loaded_dihedral_avl"
    assert result["profile_drag_cl_source_loaded_shape"] is True


def test_airfoil_sidecar_attach_preserves_ranking_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    metric, rejection = smoke._build_inverse_chord_stage0_metric(
        cfg=cfg,
        sample_index=15,
        span_m=34.0,
        tail_volume_coefficient=0.40,
        a3=-0.05,
        a5=0.01,
        cl_controls=(1.16, 1.26, 0.96, 0.58),
        design_speed_mps=6.8,
    )
    assert rejection is None
    assert metric is not None
    record = _sidecar_record(metric, objective_value=4.25)
    before_status = record["status"]
    before_physical = record["physical_acceptance_status"]
    before_objective = record["objective_value"]

    def fake_evaluate(**kwargs):
        return {
            "combination_index": kwargs["combination_index"],
            "status": "ok",
            "is_baseline": kwargs["is_baseline"],
            "assignment_label": smoke.assignment_label(kwargs["combination"]),
            "e_CDi": 0.91,
            "target_vs_avl_rms": 0.02,
            "target_vs_avl_outer_delta": 0.03,
            "profile_cd_airfoil_db": 0.012,
            "cd0_total_est_airfoil_db": 0.016,
            "min_stall_margin_airfoil_db": 3.0,
            "source_quality": "not_mission_grade_sidecar",
        }

    monkeypatch.setattr(smoke, "_evaluate_airfoil_sidecar_combination", fake_evaluate)

    smoke._attach_airfoil_sidecar_shadow_fields(
        [record],
        cfg=cfg,
        output_dir=tmp_path,
        design_speed_mps=6.8,
        avl_binary=None,
        max_airfoil_combinations=1,
    )

    assert record["status"] == before_status
    assert record["physical_acceptance_status"] == before_physical
    assert record["objective_value"] == before_objective
    assert record["sidecar_best_airfoil_assignment"]
    assert record["sidecar_best_source_quality"] == "not_mission_grade_sidecar"
    compact = smoke._stage1_compact_record(record)
    assert compact["sidecar_best_profile_cd"] == pytest.approx(0.012)


def test_mission_contract_shadow_attach_preserves_record_order_and_rank_inputs() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    records = [
        {
            "sample_index": 2,
            "geometry": {"span_m": 35.0, "aspect_ratio": 38.0},
            "avl_cdi_power_proxy": {
                "speed_mps": 6.6,
                "mass_kg": 98.5,
                "available_power_w": 204.0,
                "power_margin_w": -10.0,
            },
            "objective_value": 3.5,
        },
        {
            "sample_index": 1,
            "geometry": {"span_m": 34.0, "aspect_ratio": 37.0},
            "avl_cdi_power_proxy": {
                "speed_mps": 6.8,
                "mass_kg": 98.5,
                "available_power_w": 203.0,
                "power_margin_w": -9.0,
            },
            "objective_value": 2.5,
        },
    ]
    context = {
        "mission_contract_source": "unit_test_context",
        "mission_context": {"target_range_km": 42.195},
        "mission_gate": {"robust_power_margin_crank_w_min": 5.0},
        "total_drag_budget": {
            "cd0_total_target": 0.017,
            "cd0_total_boundary": 0.018,
            "cd0_total_rescue": 0.020,
        },
        "nonwing_reserve": {
            "cda_target_m2": 0.13,
            "cda_boundary_m2": 0.16,
        },
        "propulsion_budget": {
            "eta_prop_target": 0.88,
            "eta_trans": 0.96,
        },
    }
    before_order = [record["sample_index"] for record in records]
    before_objectives = [record["objective_value"] for record in records]

    smoke._attach_mission_contract_shadow_fields(
        records,
        cfg=cfg,
        design_speed_mps=6.6,
        context=context,
    )

    assert [record["sample_index"] for record in records] == before_order
    assert [record["objective_value"] for record in records] == before_objectives
    for record in records:
        assert record["mission_CL_req"] > 0.0
        assert record["mission_CD_wing_profile_target"] > 0.0
        assert record["mission_CDA_nonwing_target_m2"] == pytest.approx(0.13)
        assert record["mission_contract_source"] == "unit_test_context"
        assert record["mission_contract"]["source_mode"] == "shadow_no_ranking_gate"


def test_outer_loading_diagnostics_flags_underloaded_outer_stations() -> None:
    station_table = [
        {
            "eta": 0.70,
            "target_circulation_norm": 0.80,
            "avl_circulation_norm": 0.78,
            "target_local_cl": 1.00,
            "avl_local_cl": 0.98,
            "target_clmax_utilization": 0.60,
            "reynolds": 300000.0,
            "chord_m": 0.70,
            "ainc_deg": 0.5,
        },
        {
            "eta": 0.82,
            "target_circulation_norm": 0.58,
            "avl_circulation_norm": 0.40,
            "target_local_cl": 0.90,
            "avl_local_cl": 0.62,
            "target_clmax_utilization": 0.55,
            "reynolds": 240000.0,
            "chord_m": 0.56,
            "ainc_deg": 0.0,
        },
        {
            "eta": 0.90,
            "target_circulation_norm": 0.42,
            "avl_circulation_norm": 0.25,
            "target_local_cl": 0.78,
            "avl_local_cl": 0.46,
            "target_clmax_utilization": 0.47,
            "reynolds": 205000.0,
            "chord_m": 0.48,
            "ainc_deg": -0.4,
        },
        {
            "eta": 0.95,
            "target_circulation_norm": 0.28,
            "avl_circulation_norm": 0.15,
            "target_local_cl": 0.62,
            "avl_local_cl": 0.33,
            "target_clmax_utilization": 0.38,
            "reynolds": 180000.0,
            "chord_m": 0.43,
            "ainc_deg": -0.9,
        },
    ]

    diagnostics = smoke._outer_loading_diagnostics(
        station_table=station_table,
        spanload_gate_health={"local_margin_to_limit": 0.20, "outer_margin_to_limit": 0.18},
        tip_gate_summary={
            "tip_chord_m": 0.43,
            "tip_required_chord_m": 0.42,
            "tip_re": 180000.0,
            "tip_re_preferred_min": 180000.0,
        },
        twist_gate_metrics={"twist_physical_gates_pass": True, "max_abs_flight_twist_deg": 2.0},
    )

    assert diagnostics["outer_underloaded"] is True
    assert diagnostics["eta_samples"]["0.90"]["avl_to_target_circulation_ratio"] == pytest.approx(0.25 / 0.42)
    assert diagnostics["eta_samples"]["0.95"]["avl_cl_to_target_cl_ratio"] == pytest.approx(0.33 / 0.62)
    assert "outer_underloaded" in diagnostics["e_cdi_loss_diagnosis"]["drivers"]


def test_smooth_small_outer_ainc_correction_is_allowed_by_twist_gates() -> None:
    stations = (
        smoke.WingStation(y_m=0.0, chord_m=1.2, twist_deg=2.0, dihedral_deg=0.0),
        smoke.WingStation(y_m=5.0, chord_m=1.0, twist_deg=1.2, dihedral_deg=0.0),
        smoke.WingStation(y_m=9.0, chord_m=0.8, twist_deg=0.7, dihedral_deg=0.0),
        smoke.WingStation(y_m=12.0, chord_m=0.7, twist_deg=0.95, dihedral_deg=0.0),
        smoke.WingStation(y_m=15.0, chord_m=0.55, twist_deg=0.4, dihedral_deg=0.0),
        smoke.WingStation(y_m=17.0, chord_m=0.45, twist_deg=-0.8, dihedral_deg=0.0),
    )

    metrics = smoke._twist_gate_metrics(stations)

    assert metrics["outer_monotonic_washout"] is False
    assert metrics["max_outer_wash_in_step_deg"] <= 0.6
    assert metrics["twist_physical_gates_pass"] is True


def test_objective_prioritizes_avl_cdi_over_spanload_match() -> None:
    low_cdi_worse_match = {
        "avl_match_metrics": {
            "rms_target_avl_circulation_norm_delta": 0.20,
            "max_target_avl_circulation_norm_delta": 0.32,
        },
        "twist_gate_metrics": {"twist_physical_gates_pass": True, "outer_monotonic_washout": True},
        "spanload_gate_health": {"local_margin_to_limit": 0.1, "outer_margin_to_limit": 0.1},
        "avl_reference_case": {"avl_e_cdi": 0.91, "trim_cd_induced": 0.0120},
        "avl_cdi_power_proxy": {"induced_cd": 0.0120},
        "inverse_twist": {"smoothness_penalty": 0.0},
    }
    high_cdi_better_match = {
        **low_cdi_worse_match,
        "avl_match_metrics": {
            "rms_target_avl_circulation_norm_delta": 0.02,
            "max_target_avl_circulation_norm_delta": 0.04,
        },
        "avl_reference_case": {"avl_e_cdi": 0.82, "trim_cd_induced": 0.0180},
        "avl_cdi_power_proxy": {"induced_cd": 0.0180},
    }

    assert smoke._twist_objective_value(low_cdi_worse_match) < smoke._twist_objective_value(high_cdi_better_match)


def test_inverse_chord_stage0_metric_records_outer_chord_bump_passthrough() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    metric, rejection = smoke._build_inverse_chord_stage0_metric(
        cfg=cfg,
        sample_index=11,
        span_m=34.5,
        tail_volume_coefficient=0.42,
        a3=-0.06,
        a5=0.01,
        cl_controls=(1.16, 1.28, 0.98, 0.55),
        design_speed_mps=6.8,
        outer_chord_bump_amp=0.0,
    )
    assert rejection is None
    assert metric is not None
    assert metric["outer_chord_bump_amp"] == pytest.approx(0.0)
    assert metric["outer_chord_redistribution"]["succeeded"] is True
    assert metric["outer_chord_redistribution"]["outer_chord_bump_amp"] == pytest.approx(0.0)
    inner_chord = metric["spanload_to_geometry"]["inverse_chord"]["fitted_chords_m"]
    assert all(
        station.chord_m == pytest.approx(chord, abs=1.0e-6)
        for station, chord in zip(metric["stations"], inner_chord)
    )


def test_inverse_chord_stage0_metric_grows_outer_chord_under_bump() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    common_kwargs = dict(
        cfg=cfg,
        sample_index=12,
        span_m=34.5,
        tail_volume_coefficient=0.42,
        a3=-0.06,
        a5=0.01,
        cl_controls=(1.16, 1.28, 0.98, 0.55),
        design_speed_mps=6.8,
    )
    no_bump_metric, _ = smoke._build_inverse_chord_stage0_metric(
        outer_chord_bump_amp=0.0, **common_kwargs
    )
    bumped_metric, _ = smoke._build_inverse_chord_stage0_metric(
        outer_chord_bump_amp=0.20, **common_kwargs
    )
    assert no_bump_metric is not None
    assert bumped_metric is not None
    assert bumped_metric["outer_chord_bump_amp"] == pytest.approx(0.20)
    assert bumped_metric["outer_chord_redistribution"]["succeeded"]
    half_span = no_bump_metric["stations"][-1].y_m
    outer_chord_grew = False
    inner_chord_shrunk = False
    for original, bumped in zip(no_bump_metric["stations"], bumped_metric["stations"]):
        eta = original.y_m / half_span
        if 0.70 < eta < 0.95:
            if bumped.chord_m > original.chord_m + 1.0e-6:
                outer_chord_grew = True
        if eta < 0.50:
            if bumped.chord_m < original.chord_m - 1.0e-6:
                inner_chord_shrunk = True
    assert outer_chord_grew
    assert inner_chord_shrunk
    assert bumped_metric["geometry"]["wing_area_m2"] == pytest.approx(
        no_bump_metric["geometry"]["wing_area_m2"], rel=1.0e-6
    )


def test_stage0_inverse_chord_sobol_prefilter_uses_nine_dimensions() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    result = smoke._stage0_inverse_chord_sobol_prefilter(
        cfg=cfg,
        sample_count=64,
        design_speed_mps=6.4,
        seed=20260601,
    )
    assert result["counts"]["accepted"] >= 1
    bump_amps = [
        float(metric["outer_chord_bump_amp"]) for metric in result["accepted"]
    ]
    assert all(0.0 <= amp <= smoke.OUTER_CHORD_BUMP_AMP_RANGE[1] + 1.0e-9 for amp in bump_amps)
    assert max(bump_amps) > 1.0e-3, (
        "9-dim Sobol sampling must produce at least one non-zero outer chord bump"
    )
