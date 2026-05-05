from pathlib import Path

import pytest

import scripts.birdman_spanload_design_smoke as smoke
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
        "station_table": [
            {
                "eta": row["eta"],
                "y_m": row["y_m"],
                "chord_m": row["chord_m"],
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
        "mission_contract": {"mission_contract_source": "unit_test_context"},
    }
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
    assert "target_circulation" in Path(artifacts["station_table_csv_path"]).read_text(encoding="utf-8").splitlines()[0]
    mission_contract = Path(artifacts["mission_contract_json_path"]).read_text(encoding="utf-8")
    assert "mission_CL_req" in mission_contract
    assert "mission_CD_wing_profile_target" in mission_contract
    assert "mission_contract_source" in Path(artifacts["mission_contract_csv_path"]).read_text(encoding="utf-8").splitlines()[0]
    metadata = Path(artifacts["vsp_metadata_path"]).read_text(encoding="utf-8")
    script = Path(artifacts["vsp_script_path"]).read_text(encoding="utf-8")
    assert "selected_cst_dat_files" in metadata
    assert "ReadFileAirfoil" in script
    assert "NACA 0012" not in script


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
