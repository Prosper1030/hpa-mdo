from __future__ import annotations

import math

import pytest

from hpa_mdo.airfoils.database import (
    AirfoilDatabase,
    AirfoilPolarPoint,
    AirfoilRecord,
    ZoneAirfoilAssignment,
    fixed_seed_zone_airfoil_assignments,
)
from hpa_mdo.airfoils.sidecar import (
    build_zone_envelopes,
    generate_airfoil_sidecar_combinations,
    query_zone_airfoil_topk,
)
from hpa_mdo.mission.contract import MissionContract


def _mission_contract() -> MissionContract:
    span_m = 20.0
    aspect_ratio = 20.0
    wing_area_m2 = span_m**2 / aspect_ratio
    speed_mps = 10.0
    rho = 1.2
    mass_kg = 20.0
    weight_n = mass_kg * 9.80665
    return MissionContract(
        speed_mps=speed_mps,
        span_m=span_m,
        aspect_ratio=aspect_ratio,
        wing_area_m2=wing_area_m2,
        mass_kg=mass_kg,
        weight_n=weight_n,
        rho=rho,
        CL_req=weight_n / (0.5 * rho * speed_mps**2 * wing_area_m2),
        target_range_km=42.195,
        required_time_min=42.195 * 1000.0 / speed_mps / 60.0,
        eta_prop=0.88,
        eta_trans=0.96,
        pilot_power_hot_w=205.0,
        power_margin_required_w=5.0,
        CD0_total_target=0.017,
        CD0_total_boundary=0.018,
        CD0_total_rescue=0.020,
        CD_wing_profile_target=0.0125,
        CD_wing_profile_boundary=0.0140,
        CDA_nonwing_target_m2=0.13,
        CDA_nonwing_boundary_m2=0.16,
        CLmax_effective_assumption=1.55,
        mission_contract_source="unit_test_contract",
    )


def _station_rows() -> list[dict[str, float]]:
    return [
        {"eta": 0.00, "y_m": 0.0, "chord_m": 1.0, "avl_local_cl": 1.0, "reynolds": 100_000.0},
        {"eta": 0.20, "y_m": 2.0, "chord_m": 1.0, "avl_local_cl": 1.2, "reynolds": 120_000.0},
        {"eta": 0.40, "y_m": 4.0, "chord_m": 0.9, "avl_local_cl": 0.8, "reynolds": 140_000.0},
        {"eta": 0.70, "y_m": 7.0, "chord_m": 0.7, "avl_local_cl": 0.5, "reynolds": 160_000.0},
        {"eta": 0.90, "y_m": 9.0, "chord_m": 0.5, "avl_local_cl": 0.3, "reynolds": 180_000.0},
    ]


def _fourier_target() -> dict[str, list[float]]:
    return {
        "eta": [0.0, 0.25, 0.55, 0.80, 1.0],
        "cl_target": [1.1, 1.0, 0.7, 0.45, 0.2],
    }


def _database() -> AirfoilDatabase:
    def record(airfoil_id: str, cd: float, safe_clmax: float, cm: float) -> AirfoilRecord:
        points = tuple(
            AirfoilPolarPoint(
                Re=re_value,
                cl=cl_value,
                cd=cd + 0.001 * abs(cl_value - 0.7),
                cm=cm,
                alpha_deg=cl_value * 9.0,
            )
            for re_value in (100_000.0, 180_000.0)
            for cl_value in (0.0, 0.6, 1.0, 1.3)
        )
        return AirfoilRecord(
            airfoil_id=airfoil_id,
            name=airfoil_id,
            source="unit_test",
            source_quality="manual_placeholder_not_mission_grade",
            zone_hint="test",
            thickness_ratio=0.12,
            max_camber=0.03,
            alpha_L0_deg=-2.0,
            cl_alpha_per_rad=2.0 * math.pi,
            cm_design=cm,
            safe_clmax=safe_clmax,
            usable_clmax=safe_clmax + 0.1,
            polar_points=points,
            notes="unit test fixture",
        )

    return AirfoilDatabase.from_records(
        (
            record("baseline", 0.012, 1.2, -0.05),
            record("low_cd", 0.010, 1.4, -0.04),
            record("low_clmax", 0.009, 0.65, -0.02),
        )
    )


def test_zone_envelope_uses_loaded_shape_avl_cl_re_and_percentiles() -> None:
    envelopes = build_zone_envelopes(
        loaded_avl_spanwise_result=_station_rows(),
        chord_distribution=_station_rows(),
        mission_contract=_mission_contract(),
        fourier_target=_fourier_target(),
        zone_definitions=(ZoneAirfoilAssignment("root", "baseline", 0.0, 0.25),),
        current_profile_drag_rows=[
            {"eta": 0.0, "stall_margin_deg": 3.0, "cd_profile": 0.012},
            {"eta": 0.2, "stall_margin_deg": 1.0, "cd_profile": 0.014},
        ],
    )

    root = envelopes[0]
    assert root.source == "loaded_dihedral_avl"
    assert root.re_min == pytest.approx(100_000.0)
    assert root.re_max == pytest.approx(120_000.0)
    assert root.re_p50 == pytest.approx(110_000.0)
    assert root.cl_min == pytest.approx(1.0)
    assert root.cl_max == pytest.approx(1.2)
    assert root.cl_p50 == pytest.approx(1.1)
    assert root.cl_p90 == pytest.approx(1.18)
    assert root.max_avl_actual_cl == pytest.approx(1.2)
    assert root.max_fourier_target_cl == pytest.approx(1.1)
    assert root.target_vs_actual_cl_delta == pytest.approx(-0.1)
    assert root.current_airfoil_id == "baseline"
    assert root.current_stall_margin == pytest.approx(1.0)
    assert root.current_profile_cd_estimate == pytest.approx(0.013)


def test_topk_query_returns_zone_level_candidates_not_station_picks() -> None:
    envelopes = build_zone_envelopes(
        loaded_avl_spanwise_result=_station_rows(),
        chord_distribution=_station_rows(),
        mission_contract=_mission_contract(),
        fourier_target=_fourier_target(),
        zone_definitions=(ZoneAirfoilAssignment("root", "baseline", 0.0, 0.25),),
    )

    topk = query_zone_airfoil_topk(envelopes, _database(), top_k=2)

    assert tuple(topk) == ("root",)
    assert len(topk["root"]) == 2
    assert all(candidate["zone_name"] == "root" for candidate in topk["root"])
    assert all("station_index" not in candidate for candidate in topk["root"])
    assert all(candidate["source_quality"] == "not_mission_grade_sidecar" for candidate in topk["root"])


def test_sidecar_combination_cap_and_baseline_first() -> None:
    baseline = fixed_seed_zone_airfoil_assignments()
    topk = {
        "root": ({"airfoil_id": "fx76mp140"}, {"airfoil_id": "dae11"}),
        "mid1": ({"airfoil_id": "fx76mp140"}, {"airfoil_id": "dae21"}),
        "mid2": ({"airfoil_id": "dae31"}, {"airfoil_id": "clarkysm"}),
        "tip": ({"airfoil_id": "dae31"}, {"airfoil_id": "dae41"}),
    }

    combos = generate_airfoil_sidecar_combinations(
        baseline,
        topk,
        available_airfoil_ids=("fx76mp140", "clarkysm", "dae11", "dae21", "dae31", "dae41"),
        max_airfoil_combinations=3,
    )

    assert len(combos) == 3
    assert [assignment.airfoil_id for assignment in combos[0]] == [
        assignment.airfoil_id for assignment in baseline
    ]
    assert any(
        assignment.zone_name == "mid2" and assignment.airfoil_id == "dae31"
        for assignment in combos[1]
    )
