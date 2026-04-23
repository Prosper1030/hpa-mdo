from __future__ import annotations

from pathlib import Path
import shutil

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.concept import avl_loader as concept_avl_loader
from hpa_mdo.concept.avl_loader import (
    avl_zone_payload_from_spanwise_load,
    build_avl_backed_spanwise_loader,
    load_zone_requirements_from_avl,
    resample_spanwise_load_to_stations,
    select_avl_design_cases,
    select_avl_reference_condition,
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
