from __future__ import annotations

from pathlib import Path
import shutil

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.concept import avl_loader as concept_avl_loader
from hpa_mdo.concept.atmosphere import interpolate_sea_level_air_properties
from hpa_mdo.concept.avl_loader import (
    avl_zone_payload_from_spanwise_load,
    build_avl_backed_spanwise_loader,
    load_zone_requirements_from_avl,
    resample_spanwise_load_to_stations,
    select_avl_design_cases,
    select_avl_reference_condition,
    write_concept_wing_only_avl,
)
from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.geometry import GeometryConcept, build_linear_wing_stations, build_segment_plan


def _sample_concept() -> GeometryConcept:
    span_m = 32.0
    wing_area_m2 = 28.0
    root_chord_m = 2.0 * wing_area_m2 / (span_m * (1.0 + 0.35))
    tip_chord_m = root_chord_m * 0.35
    return GeometryConcept(
        span_m=span_m,
        wing_area_m2=wing_area_m2,
        root_chord_m=root_chord_m,
        tip_chord_m=tip_chord_m,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
        dihedral_root_deg=1.0,
        dihedral_tip_deg=6.0,
        dihedral_exponent=1.5,
        tail_area_m2=4.2,
        cg_xc=0.30,
        segment_lengths_m=build_segment_plan(
            half_span_m=0.5 * span_m,
            min_segment_length_m=1.0,
            max_segment_length_m=3.0,
        ),
    )


def _sample_spanwise_load() -> SpanwiseLoad:
    y = np.asarray([0.0, 4.0, 8.0, 12.0, 16.0], dtype=float)
    chord = np.asarray([1.30, 1.15, 1.00, 0.82, 0.67], dtype=float)
    cl = np.asarray([0.78, 0.75, 0.70, 0.63, 0.56], dtype=float)
    cd = np.asarray([0.020, 0.019, 0.018, 0.019, 0.021], dtype=float)
    cm = np.asarray([-0.12, -0.11, -0.10, -0.09, -0.08], dtype=float)
    q_pa = 0.5 * 1.10 * 8.0**2
    return SpanwiseLoad(
        y=y,
        chord=chord,
        cl=cl,
        cd=cd,
        cm=cm,
        lift_per_span=q_pa * chord * cl,
        drag_per_span=q_pa * chord * cd,
        aoa_deg=3.0,
        velocity=8.0,
        dynamic_pressure=q_pa,
    )


def test_resample_spanwise_load_to_stations_matches_station_layout() -> None:
    concept = _sample_concept()
    stations = build_linear_wing_stations(concept, stations_per_half=7)

    resampled = resample_spanwise_load_to_stations(
        spanwise_load=_sample_spanwise_load(),
        stations=stations,
    )

    assert len(resampled.y) == len(stations)
    assert np.allclose(resampled.y, [station.y_m for station in stations])
    assert np.isclose(resampled.cl[0], 0.78)
    assert np.isclose(resampled.cl[-1], 0.56)
    assert resampled.dynamic_pressure > 0.0


def test_avl_zone_payload_from_spanwise_load_preserves_station_y() -> None:
    concept = _sample_concept()
    stations = build_linear_wing_stations(concept, stations_per_half=7)
    resampled = resample_spanwise_load_to_stations(
        spanwise_load=_sample_spanwise_load(),
        stations=stations,
    )

    payload = avl_zone_payload_from_spanwise_load(
        spanwise_load=resampled,
        stations=stations,
    )

    assert tuple(payload) == ("root", "mid1", "mid2", "tip")
    assert sum(len(zone["points"]) for zone in payload.values()) == len(stations)
    assert payload["root"]["points"][0]["station_y_m"] == stations[0].y_m
    assert payload["root"]["points"][0]["chord_m"] == pytest.approx(resampled.chord[0])
    assert payload["tip"]["points"][-1]["station_y_m"] == stations[-1].y_m
    assert payload["tip"]["points"][-1]["chord_m"] == pytest.approx(resampled.chord[-1])
    assert all(point["weight"] > 0.0 for zone in payload.values() for point in zone["points"])


def test_avl_zone_payload_from_spanwise_load_uses_temperature_table_viscosity() -> None:
    concept = _sample_concept()
    stations = build_linear_wing_stations(concept, stations_per_half=7)
    air_props = interpolate_sea_level_air_properties(33.5)
    resampled = resample_spanwise_load_to_stations(
        spanwise_load=_sample_spanwise_load(),
        stations=stations,
    )

    payload = avl_zone_payload_from_spanwise_load(
        spanwise_load=resampled,
        stations=stations,
        dynamic_viscosity_pa_s=air_props.dynamic_viscosity_pa_s,
    )

    expected_density = 2.0 * resampled.dynamic_pressure / (resampled.velocity**2)
    expected_reynolds = (
        expected_density
        * resampled.velocity
        * resampled.chord[0]
        / air_props.dynamic_viscosity_pa_s
    )
    assert payload["root"]["points"][0]["reynolds"] == pytest.approx(expected_reynolds)


def test_select_avl_reference_condition_uses_range_speed_for_max_range() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg = cfg.model_copy(
        update={
            "mission": cfg.mission.model_copy(update={"objective_mode": "max_range"})
        }
    )

    reference = select_avl_reference_condition(
        cfg=cfg,
        concept=_sample_concept(),
        air_density_kg_per_m3=1.10,
    )

    assert reference["objective_mode"] == "max_range"
    assert reference["mass_selection_reason"] == "min_best_range_feasible_m"
    assert (
        reference["reference_condition_policy"]
        == "low_speed_primary_multipoint_design_cases_v4_feasible_reference_proxy"
    )
    if reference["selected_mass_case"]["best_range_feasible_speed_mps"] is not None:
        assert reference["reference_speed_reason"] == "best_range_feasible_speed_mps"
        assert reference["reference_speed_mps"] == pytest.approx(
            reference["selected_mass_case"]["best_range_feasible_speed_mps"]
        )
    elif reference["selected_mass_case"]["estimated_first_feasible_speed_mps"] is not None:
        assert reference["reference_speed_reason"] == "estimated_first_feasible_speed_mps"
        assert reference["reference_speed_mps"] == pytest.approx(
            reference["selected_mass_case"]["estimated_first_feasible_speed_mps"]
        )
    else:
        assert reference["reference_speed_reason"] == "best_range_speed_mps_unconstrained_fallback"
        assert reference["reference_speed_mps"] == pytest.approx(
            reference["selected_mass_case"]["best_range_speed_mps"]
        )
    assert reference["reference_gross_mass_kg"] == pytest.approx(
        reference["selected_mass_case"]["gross_mass_kg"]
    )


def test_avl_mass_cases_convert_shaft_power_to_pedal_power_with_drivetrain() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    assert cfg.drivetrain.efficiency == pytest.approx(0.96)

    mass_cases = concept_avl_loader._mission_mass_cases_for_avl(
        cfg=cfg,
        concept=_sample_concept(),
        air_density_kg_per_m3=1.10,
    )

    first_case = mass_cases[0]
    shaft_power = tuple(first_case["shaft_power_required_w_by_speed"])
    pedal_power = tuple(first_case["pedal_power_required_w_by_speed"])
    assert len(shaft_power) == len(pedal_power)
    assert all(pedal_w > shaft_w > 0.0 for shaft_w, pedal_w in zip(shaft_power, pedal_power))
    for shaft_w, pedal_w in zip(shaft_power, pedal_power):
        assert pedal_w == pytest.approx(shaft_w / cfg.drivetrain.efficiency)
    assert tuple(first_case["power_required_w"]) == pytest.approx(pedal_power)


def test_select_avl_reference_condition_prefers_feasible_range_speed_for_max_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg = cfg.model_copy(
        update={
            "mission": cfg.mission.model_copy(update={"objective_mode": "max_range"})
        }
    )

    monkeypatch.setattr(
        concept_avl_loader,
        "_mission_mass_cases_for_avl",
        lambda **_: [
            {
                "gross_mass_kg": 95.0,
                "best_range_m": 6800.0,
                "best_range_speed_mps": 6.0,
                "best_range_feasible_m": 1600.0,
                "best_range_feasible_speed_mps": 9.5,
                "estimated_first_feasible_speed_mps": None,
                "min_power_w": 350.0,
                "min_power_speed_mps": 6.0,
                "min_power_feasible_w": 480.0,
                "min_power_feasible_speed_mps": 9.5,
                "mission_feasible": False,
                "target_range_passed": False,
                "mission_score": 0.0,
            },
            {
                "gross_mass_kg": 105.0,
                "best_range_m": 5900.0,
                "best_range_speed_mps": 6.0,
                "best_range_feasible_m": 1200.0,
                "best_range_feasible_speed_mps": 10.0,
                "estimated_first_feasible_speed_mps": None,
                "min_power_w": 360.0,
                "min_power_speed_mps": 6.0,
                "min_power_feasible_w": 520.0,
                "min_power_feasible_speed_mps": 10.0,
                "mission_feasible": False,
                "target_range_passed": False,
                "mission_score": 0.0,
            },
        ],
    )

    reference = select_avl_reference_condition(
        cfg=cfg,
        concept=_sample_concept(),
        air_density_kg_per_m3=1.10,
    )

    assert reference["mass_selection_reason"] == "min_best_range_feasible_m"
    assert reference["reference_speed_reason"] == "best_range_feasible_speed_mps"
    assert reference["reference_speed_mps"] == pytest.approx(10.0)
    assert reference["reference_gross_mass_kg"] == pytest.approx(105.0)


def test_select_avl_reference_condition_falls_back_to_estimated_first_feasible_speed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg = cfg.model_copy(
        update={
            "mission": cfg.mission.model_copy(update={"objective_mode": "max_range"})
        }
    )

    monkeypatch.setattr(
        concept_avl_loader,
        "_mission_mass_cases_for_avl",
        lambda **_: [
            {
                "gross_mass_kg": 95.0,
                "best_range_m": 6800.0,
                "best_range_speed_mps": 6.0,
                "best_range_feasible_m": 1600.0,
                "best_range_feasible_speed_mps": 9.5,
                "estimated_first_feasible_speed_mps": None,
                "min_power_w": 350.0,
                "min_power_speed_mps": 6.0,
                "min_power_feasible_w": 480.0,
                "min_power_feasible_speed_mps": 9.5,
                "mission_feasible": False,
                "target_range_passed": False,
                "mission_score": 0.0,
            },
            {
                "gross_mass_kg": 105.0,
                "best_range_m": 5900.0,
                "best_range_speed_mps": 6.0,
                "best_range_feasible_m": 0.0,
                "best_range_feasible_speed_mps": None,
                "estimated_first_feasible_speed_mps": 8.7,
                "min_power_w": 360.0,
                "min_power_speed_mps": 6.0,
                "min_power_feasible_w": None,
                "min_power_feasible_speed_mps": None,
                "mission_feasible": False,
                "target_range_passed": False,
                "mission_score": 0.0,
            },
        ],
    )

    reference = select_avl_reference_condition(
        cfg=cfg,
        concept=_sample_concept(),
        air_density_kg_per_m3=1.10,
    )

    assert reference["mass_selection_reason"] == "min_best_range_feasible_m"
    assert reference["reference_speed_reason"] == "estimated_first_feasible_speed_mps"
    assert reference["reference_speed_mps"] == pytest.approx(8.7)
    assert reference["reference_gross_mass_kg"] == pytest.approx(105.0)


def test_select_avl_reference_condition_uses_slowest_worst_finish_case_for_fixed_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg = cfg.model_copy(
        update={
            "mission": cfg.mission.model_copy(
                update={"objective_mode": "fixed_range_best_time"}
            )
        }
    )

    monkeypatch.setattr(
        concept_avl_loader,
        "_mission_mass_cases_for_avl",
        lambda **_: [
            {
                "gross_mass_kg": 95.0,
                "target_range_passed": True,
                "best_time_s": 5_800.0,
                "best_time_speed_mps": 7.275,
                "best_time_feasible_s": 5_800.0,
                "best_time_feasible_speed_mps": 7.275,
                "best_range_feasible_m": 45_000.0,
                "best_range_feasible_speed_mps": 7.0,
                "estimated_first_feasible_speed_mps": None,
                "best_range_m": 46_000.0,
                "best_range_speed_mps": 7.0,
                "mission_score": 5_800.0,
            },
            {
                "gross_mass_kg": 105.0,
                "target_range_passed": True,
                "best_time_s": 6_300.0,
                "best_time_speed_mps": 6.698,
                "best_time_feasible_s": 6_300.0,
                "best_time_feasible_speed_mps": 6.698,
                "best_range_feasible_m": 43_000.0,
                "best_range_feasible_speed_mps": 6.5,
                "estimated_first_feasible_speed_mps": None,
                "best_range_m": 43_500.0,
                "best_range_speed_mps": 6.5,
                "mission_score": 6_300.0,
            },
        ],
    )

    reference = select_avl_reference_condition(
        cfg=cfg,
        concept=_sample_concept(),
        air_density_kg_per_m3=1.10,
    )

    assert reference["objective_mode"] == "fixed_range_best_time"
    assert reference["mass_selection_reason"] == "fixed_range_worst_time_or_range"
    assert reference["reference_speed_reason"] == "best_time_feasible_speed_mps"
    assert reference["reference_speed_mps"] == pytest.approx(6.698)
    assert reference["reference_gross_mass_kg"] == pytest.approx(105.0)


def test_select_avl_reference_condition_fixed_range_miss_falls_back_to_range_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg = cfg.model_copy(
        update={
            "mission": cfg.mission.model_copy(
                update={"objective_mode": "fixed_range_best_time"}
            )
        }
    )

    monkeypatch.setattr(
        concept_avl_loader,
        "_mission_mass_cases_for_avl",
        lambda **_: [
            {
                "gross_mass_kg": 95.0,
                "target_range_passed": False,
                "best_time_s": None,
                "best_time_speed_mps": None,
                "best_time_feasible_s": None,
                "best_time_feasible_speed_mps": None,
                "best_range_feasible_m": 30_000.0,
                "best_range_feasible_speed_mps": 8.0,
                "estimated_first_feasible_speed_mps": None,
                "best_range_m": 31_000.0,
                "best_range_speed_mps": 7.5,
                "mission_score": 970_000.0,
            },
            {
                "gross_mass_kg": 105.0,
                "target_range_passed": False,
                "best_time_s": None,
                "best_time_speed_mps": None,
                "best_time_feasible_s": None,
                "best_time_feasible_speed_mps": None,
                "best_range_feasible_m": 24_000.0,
                "best_range_feasible_speed_mps": 8.5,
                "estimated_first_feasible_speed_mps": None,
                "best_range_m": 25_000.0,
                "best_range_speed_mps": 8.0,
                "mission_score": 976_000.0,
            },
        ],
    )

    reference = select_avl_reference_condition(
        cfg=cfg,
        concept=_sample_concept(),
        air_density_kg_per_m3=1.10,
    )

    assert reference["mass_selection_reason"] == "fixed_range_worst_time_or_range"
    assert reference["reference_speed_reason"] == "best_range_feasible_speed_mps"
    assert reference["reference_speed_mps"] == pytest.approx(8.5)
    assert reference["reference_gross_mass_kg"] == pytest.approx(105.0)


def test_select_avl_reference_condition_uses_min_power_speed_for_min_power() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg = cfg.model_copy(
        update={
            "mission": cfg.mission.model_copy(update={"objective_mode": "min_power"})
        }
    )

    reference = select_avl_reference_condition(
        cfg=cfg,
        concept=_sample_concept(),
        air_density_kg_per_m3=1.10,
    )

    assert reference["objective_mode"] == "min_power"
    assert reference["mass_selection_reason"] == "max_min_power_feasible_w"
    assert (
        reference["reference_condition_policy"]
        == "low_speed_primary_multipoint_design_cases_v4_feasible_reference_proxy"
    )
    if reference["selected_mass_case"]["min_power_feasible_speed_mps"] is not None:
        assert reference["reference_speed_reason"] == "min_power_feasible_speed_mps"
        assert reference["reference_speed_mps"] == pytest.approx(
            reference["selected_mass_case"]["min_power_feasible_speed_mps"]
        )
    elif reference["selected_mass_case"]["estimated_first_feasible_speed_mps"] is not None:
        assert reference["reference_speed_reason"] == "estimated_first_feasible_speed_mps"
        assert reference["reference_speed_mps"] == pytest.approx(
            reference["selected_mass_case"]["estimated_first_feasible_speed_mps"]
        )
    else:
        assert reference["reference_speed_reason"] == "min_power_speed_mps_unconstrained_fallback"
        assert reference["reference_speed_mps"] == pytest.approx(
            reference["selected_mass_case"]["min_power_speed_mps"]
        )
    assert reference["reference_gross_mass_kg"] == pytest.approx(
        reference["selected_mass_case"]["gross_mass_kg"]
    )


def test_select_avl_reference_condition_for_min_power_prefers_feasible_case_over_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg = cfg.model_copy(
        update={
            "mission": cfg.mission.model_copy(update={"objective_mode": "min_power"})
        }
    )

    monkeypatch.setattr(
        concept_avl_loader,
        "_mission_mass_cases_for_avl",
        lambda **_: [
            {
                "gross_mass_kg": 95.0,
                "best_range_m": 6800.0,
                "best_range_speed_mps": 6.0,
                "best_range_feasible_m": 1600.0,
                "best_range_feasible_speed_mps": 9.5,
                "estimated_first_feasible_speed_mps": None,
                "min_power_w": 350.0,
                "min_power_speed_mps": 6.0,
                "min_power_feasible_w": None,
                "min_power_feasible_speed_mps": None,
                "mission_feasible": False,
                "target_range_passed": False,
                "mission_score": 0.0,
            },
            {
                "gross_mass_kg": 105.0,
                "best_range_m": 5900.0,
                "best_range_speed_mps": 6.0,
                "best_range_feasible_m": 1200.0,
                "best_range_feasible_speed_mps": 10.0,
                "estimated_first_feasible_speed_mps": None,
                "min_power_w": 360.0,
                "min_power_speed_mps": 6.0,
                "min_power_feasible_w": 520.0,
                "min_power_feasible_speed_mps": 10.0,
                "mission_feasible": False,
                "target_range_passed": False,
                "mission_score": 0.0,
            },
        ],
    )

    reference = select_avl_reference_condition(
        cfg=cfg,
        concept=_sample_concept(),
        air_density_kg_per_m3=1.10,
    )

    assert reference["reference_gross_mass_kg"] == pytest.approx(105.0)
    assert reference["reference_speed_reason"] == "min_power_feasible_speed_mps"
    assert reference["reference_speed_mps"] == pytest.approx(10.0)


def test_select_avl_design_cases_exposes_reference_slow_launch_and_turn_cases() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))

    payload = select_avl_design_cases(
        cfg=cfg,
        concept=_sample_concept(),
        air_density_kg_per_m3=1.10,
    )

    labels = [case["case_label"] for case in payload["design_cases"]]
    assert labels == [
        "reference_avl_case",
        "slow_avl_case",
        "launch_release_case",
        "turn_avl_case",
    ]
    turn_case = payload["design_cases"][-1]
    assert turn_case["evaluation_speed_mps"] == pytest.approx(cfg.launch.release_speed_mps)
    assert turn_case["evaluation_gross_mass_kg"] == pytest.approx(max(cfg.mass.gross_mass_sweep_kg))
    assert turn_case["load_factor"] == pytest.approx(
        1.0 / np.cos(np.radians(cfg.turn.required_bank_angle_deg))
    )
    assert (
        payload["reference_condition_policy"]
        == "low_speed_primary_multipoint_design_cases_v4_feasible_reference_proxy"
    )
    case_weights = {case["case_label"]: case["case_weight"] for case in payload["design_cases"]}
    assert case_weights["slow_avl_case"] > case_weights["reference_avl_case"]
    assert case_weights["launch_release_case"] > case_weights["reference_avl_case"]
    assert case_weights["turn_avl_case"] > case_weights["reference_avl_case"]
    assert payload["primary_case_labels"] == [
        "slow_avl_case",
        "launch_release_case",
        "turn_avl_case",
    ]
    assert payload["secondary_case_labels"] == ["reference_avl_case"]


def test_write_concept_wing_only_avl_can_use_selected_zone_airfoils(tmp_path: Path) -> None:
    concept = _sample_concept()
    stations = build_linear_wing_stations(concept, stations_per_half=7)
    airfoil_paths = {}
    for zone_name in ("root", "mid1", "mid2", "tip"):
        dat_path = tmp_path / f"{zone_name}.dat"
        dat_path.write_text(
            "test\n1.0 0.0\n0.5 0.05\n0.0 0.0\n0.5 -0.04\n1.0 0.0\n",
            encoding="utf-8",
        )
        airfoil_paths[zone_name] = dat_path

    avl_path = write_concept_wing_only_avl(
        concept=concept,
        stations=stations,
        output_path=tmp_path / "concept_wing.avl",
        zone_airfoil_paths=airfoil_paths,
    )

    avl_text = avl_path.read_text(encoding="utf-8")

    assert str(airfoil_paths["root"]) in avl_text
    assert str(airfoil_paths["mid1"]) in avl_text
    assert str(airfoil_paths["mid2"]) in avl_text
    assert str(airfoil_paths["tip"]) in avl_text


def test_write_concept_wing_only_avl_uses_mac_as_cref(tmp_path: Path) -> None:
    concept = _sample_concept()
    stations = build_linear_wing_stations(concept, stations_per_half=7)

    avl_path = write_concept_wing_only_avl(
        concept=concept,
        stations=stations,
        output_path=tmp_path / "concept_wing.avl",
    )

    avl_lines = avl_path.read_text(encoding="utf-8").splitlines()
    sref_line_index = avl_lines.index("#Sref  Cref  Bref") + 1
    sref_m2, cref_m, bref_m = [float(token) for token in avl_lines[sref_line_index].split()]

    assert sref_m2 == pytest.approx(concept.wing_area_m2)
    assert cref_m == pytest.approx(concept.mean_aerodynamic_chord_m)
    assert bref_m == pytest.approx(concept.span_m)


def test_load_zone_requirements_from_avl_applies_reference_override_and_case_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = _sample_concept()
    stations = build_linear_wing_stations(concept, stations_per_half=7)
    captured_case_dirs: list[Path] = []

    monkeypatch.setattr(
        concept_avl_loader,
        "select_avl_design_cases",
        lambda **_: {
            "objective_mode": "max_range",
            "reference_speed_mps": 6.0,
            "reference_gross_mass_kg": 105.0,
            "reference_speed_reason": "proxy_reference_speed",
            "mass_selection_reason": "proxy_mass_case",
            "reference_condition_policy": "proxy_reference_policy",
            "primary_case_labels": [
                "slow_avl_case",
                "launch_release_case",
                "turn_avl_case",
            ],
            "secondary_case_labels": ["reference_avl_case"],
            "selected_mass_case": {
                "gross_mass_kg": 105.0,
                "best_range_m": 5900.0,
                "best_range_feasible_m": 1200.0,
                "best_range_speed_mps": 6.0,
                "best_range_feasible_speed_mps": 10.0,
                "feasible_speed_set_mps": (9.5, 10.0),
                "reference_speed_filter_model": "pre_avl_local_stall_feasible_speed_proxy_v1",
            },
            "mass_cases": [],
            "design_cases": [
                {
                    "case_label": "reference_avl_case",
                    "evaluation_speed_mps": 6.0,
                    "evaluation_gross_mass_kg": 105.0,
                    "load_factor": 1.0,
                    "case_weight": 0.35,
                    "speed_reason": "proxy_reference_speed",
                    "mass_reason": "proxy_mass_case",
                    "case_reason": "secondary_cruise_objective_case",
                },
                {
                    "case_label": "slow_avl_case",
                    "evaluation_speed_mps": 6.0,
                    "evaluation_gross_mass_kg": 105.0,
                    "load_factor": 1.0,
                    "case_weight": 1.75,
                    "speed_reason": "speed_sweep_min_mps",
                    "mass_reason": "max_gross_mass",
                    "case_reason": "primary_low_speed_heavy_mass_case",
                },
                {
                    "case_label": "launch_release_case",
                    "evaluation_speed_mps": 7.0,
                    "evaluation_gross_mass_kg": 105.0,
                    "load_factor": 1.0,
                    "case_weight": 2.0,
                    "speed_reason": "launch.release_speed_mps",
                    "mass_reason": "max_gross_mass",
                    "case_reason": "primary_launch_release_heavy_mass_case",
                },
                {
                    "case_label": "turn_avl_case",
                    "evaluation_speed_mps": 7.0,
                    "evaluation_gross_mass_kg": 105.0,
                    "load_factor": 1.03,
                    "case_weight": 2.25,
                    "speed_reason": "launch.release_speed_mps",
                    "mass_reason": "max_gross_mass",
                    "case_reason": "primary_banked_turn_heavy_mass_case",
                },
            ],
        },
    )
    monkeypatch.setattr(
        concept_avl_loader,
        "_run_avl_trim_case",
        lambda **kwargs: captured_case_dirs.append(Path(kwargs["case_dir"]))
        or {"aoa_trim_deg": 3.0, "cl_trim": float(kwargs["cl_required"])},
    )
    monkeypatch.setattr(
        concept_avl_loader,
        "_run_avl_spanwise_case",
        lambda **kwargs: Path(kwargs["case_dir"]) / "concept_spanwise.fs",
    )
    monkeypatch.setattr(
        concept_avl_loader,
        "build_spanwise_load_from_avl_strip_forces",
        lambda **_: _sample_spanwise_load(),
    )

    airfoil_templates = {
        zone_name: {
            "coordinates": [
                [1.0, 0.0],
                [0.5, 0.05],
                [0.0, 0.0],
                [0.5, -0.04],
                [1.0, 0.0],
            ]
        }
        for zone_name in ("root", "mid1", "mid2", "tip")
    }
    payload = load_zone_requirements_from_avl(
        cfg=cfg,
        concept=concept,
        stations=stations,
        working_root=tmp_path,
        airfoil_templates=airfoil_templates,
        reference_condition_override={
            "reference_speed_mps": 9.5,
            "reference_gross_mass_kg": 100.0,
            "reference_speed_reason": "post_airfoil_best_range_feasible_speed_mps",
            "mass_selection_reason": "post_airfoil_worst_case_gross_mass",
            "reference_condition_policy": "post_airfoil_feasible_reference_avl_rerun_v1",
        },
        case_tag="finalist_post_airfoil_avl_rerun",
    )

    assert captured_case_dirs
    assert all("finalist_post_airfoil_avl_rerun" in str(path) for path in captured_case_dirs)
    assert payload["root"]["reference_speed_mps"] == pytest.approx(9.5)
    assert payload["root"]["reference_gross_mass_kg"] == pytest.approx(100.0)
    assert payload["root"]["reference_speed_reason"] == "post_airfoil_best_range_feasible_speed_mps"
    assert payload["root"]["mass_selection_reason"] == "post_airfoil_worst_case_gross_mass"
    assert payload["root"]["reference_condition_policy"] == "post_airfoil_feasible_reference_avl_rerun_v1"
    assert payload["root"]["design_cases"][0]["evaluation_speed_mps"] == pytest.approx(9.5)
    assert payload["root"]["design_cases"][0]["evaluation_gross_mass_kg"] == pytest.approx(100.0)


def test_avl_backed_loader_falls_back_on_avl_failure(tmp_path: Path, monkeypatch) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = _sample_concept()
    stations = build_linear_wing_stations(concept, stations_per_half=7)
    fallback_calls: list[tuple[float, int]] = []
    fallback_payload = {
        "root": {
            "source": "coarse_loader",
            "points": [{"reynolds": 1.0, "cl_target": 0.1, "cm_target": -0.1, "weight": 1.0}],
        },
        "mid1": {"points": []},
        "mid2": {"points": []},
        "tip": {"points": []},
    }

    monkeypatch.setattr(
        concept_avl_loader,
        "load_zone_requirements_from_avl",
        lambda **_: (_ for _ in ()).throw(RuntimeError("avl failed")),
    )
    loader = build_avl_backed_spanwise_loader(
        cfg=cfg,
        working_root=tmp_path,
        fallback_loader=lambda concept_arg, stations_arg: fallback_calls.append(
            (concept_arg.span_m, len(stations_arg))
        )
        or fallback_payload,
    )

    payload = loader(concept, stations)

    assert payload["root"]["points"] == fallback_payload["root"]["points"]
    assert payload["root"]["source"] == "fallback_coarse_loader"
    assert payload["root"]["fallback_reason"] == "avl failed"
    assert fallback_calls == [(concept.span_m, len(stations))]


def test_avl_backed_loader_uses_avl_payload_when_available(tmp_path: Path, monkeypatch) -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = _sample_concept()
    stations = build_linear_wing_stations(concept, stations_per_half=7)
    expected_payload = {
        "root": {"points": [{"reynolds": 250000.0, "cl_target": 0.7, "cm_target": -0.1, "weight": 1.0}]},
        "mid1": {"points": []},
        "mid2": {"points": []},
        "tip": {"points": []},
    }
    fallback_calls: list[bool] = []

    monkeypatch.setattr(
        concept_avl_loader,
        "load_zone_requirements_from_avl",
        lambda **_: expected_payload,
    )
    loader = build_avl_backed_spanwise_loader(
        cfg=cfg,
        working_root=tmp_path,
        fallback_loader=lambda *_: fallback_calls.append(True) or {"root": {"points": []}},
    )

    payload = loader(concept, stations)

    assert payload == expected_payload
    assert fallback_calls == []


def test_load_zone_requirements_from_avl_returns_nonempty_payload(tmp_path: Path) -> None:
    avl_binary = shutil.which("avl")
    if avl_binary is None:
        pytest.skip("AVL binary not available in test environment.")

    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = _sample_concept()
    stations = build_linear_wing_stations(concept, stations_per_half=7)

    payload = load_zone_requirements_from_avl(
        cfg=cfg,
        concept=concept,
        stations=stations,
        working_root=tmp_path,
        avl_binary=avl_binary,
    )

    assert tuple(payload) == ("root", "mid1", "mid2", "tip")
    assert all(zone_payload["source"] == "avl_strip_forces" for zone_payload in payload.values())
    assert sum(len(zone["points"]) for zone in payload.values()) == 4 * len(stations)
    assert payload["root"]["design_case_count"] == 4
    assert {case["case_label"] for case in payload["root"]["design_cases"]} == {
        "reference_avl_case",
        "slow_avl_case",
        "launch_release_case",
        "turn_avl_case",
    }
    assert payload["root"]["reference_cl_required"] > 0.0
