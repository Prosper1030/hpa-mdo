from __future__ import annotations

import math

import pytest

from hpa_mdo.airfoils.database import (
    AirfoilDatabase,
    AirfoilPolarPoint,
    AirfoilRecord,
    ZoneAirfoilAssignment,
    default_airfoil_database,
    integrate_profile_drag_from_avl,
    lookup_airfoil_polar,
)
from hpa_mdo.mission.contract import MissionContract


def _mission_contract(*, span_m: float = 10.0, aspect_ratio: float = 10.0) -> MissionContract:
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


def _constant_cd_database(*, cd: float = 0.012, airfoil_id: str = "constant") -> AirfoilDatabase:
    points = tuple(
        AirfoilPolarPoint(Re=re_value, cl=cl_value, cd=cd, cm=-0.05, alpha_deg=cl_value * 10.0)
        for re_value in (500_000.0, 800_000.0)
        for cl_value in (-0.2, 0.5, 1.2)
    )
    record = AirfoilRecord(
        airfoil_id=airfoil_id,
        name="Constant CD Fixture",
        source="unit_test",
        source_quality="unit_test_fixture_not_mission_grade",
        zone_hint="root",
        thickness_ratio=0.12,
        max_camber=0.03,
        alpha_L0_deg=-2.0,
        cl_alpha_per_rad=2.0 * math.pi,
        cm_design=-0.05,
        safe_clmax=1.4,
        usable_clmax=1.5,
        polar_points=points,
        notes="Constant cd analytic integration fixture.",
    )
    return AirfoilDatabase.from_records((record,))


def _linear_cl_cd_database() -> AirfoilDatabase:
    points = tuple(
        AirfoilPolarPoint(
            Re=re_value,
            cl=cl_value,
            cd=0.010 + 0.020 * cl_value,
            cm=-0.05,
            alpha_deg=cl_value * 10.0,
        )
        for re_value in (500_000.0, 800_000.0)
        for cl_value in (0.0, 0.4, 1.2)
    )
    record = AirfoilRecord(
        airfoil_id="linear_cl_cd",
        name="Linear Cl CD Fixture",
        source="unit_test",
        source_quality="unit_test_fixture_not_mission_grade",
        zone_hint="root",
        thickness_ratio=0.12,
        max_camber=0.03,
        alpha_L0_deg=-2.0,
        cl_alpha_per_rad=2.0 * math.pi,
        cm_design=-0.05,
        safe_clmax=1.4,
        usable_clmax=1.5,
        polar_points=points,
        notes="Detects whether integration uses AVL actual cl.",
    )
    return AirfoilDatabase.from_records((record,))


def _full_span_constant_chord_stations(*, avl_cl: float, target_cl: float = 1.2) -> list[dict[str, float]]:
    return [
        {
            "eta": eta,
            "y_m": 5.0 * eta,
            "chord_m": 1.0,
            "avl_local_cl": avl_cl,
            "target_local_cl": target_cl,
        }
        for eta in (0.0, 0.5, 1.0)
    ]


def test_lookup_returns_finite_cd_for_in_range_fixture_query() -> None:
    result = lookup_airfoil_polar("fx76mp140", Re=410_000.0, cl=1.10)

    assert math.isfinite(result.cd)
    assert result.cd > 0.0
    assert result.interpolated is True
    assert "not_mission_grade" in result.source_quality


def test_out_of_range_query_marks_warning_and_non_mission_grade() -> None:
    result = lookup_airfoil_polar("fx76mp140", Re=50_000.0, cl=2.4)

    assert math.isfinite(result.cd)
    assert result.extrapolated is True
    assert result.warnings
    assert "not_mission_grade" in result.source_quality


def test_default_database_contains_manual_placeholder_records_only_as_non_mission_grade() -> None:
    database = default_airfoil_database()

    assert "dae31" in database.records
    assert all("not_mission_grade" in record.source_quality for record in database.records.values())


def test_profile_drag_integration_matches_constant_cd_analytic_case() -> None:
    contract = _mission_contract()
    database = _constant_cd_database(cd=0.012)
    assignments = (ZoneAirfoilAssignment("root", "constant", 0.0, 1.0),)

    result = integrate_profile_drag_from_avl(
        contract,
        _full_span_constant_chord_stations(avl_cl=0.5),
        _full_span_constant_chord_stations(avl_cl=0.5),
        assignments,
        database,
    )

    assert result.CD_profile == pytest.approx(0.012, rel=1.0e-9)
    assert result.station_warning_count == 0
    assert all(row["airfoil_id"] == "constant" for row in result.station_rows)


def test_profile_drag_uses_avl_actual_cl_not_fourier_target_cl() -> None:
    contract = _mission_contract()
    database = _linear_cl_cd_database()
    assignments = (ZoneAirfoilAssignment("root", "linear_cl_cd", 0.0, 1.0),)

    result = integrate_profile_drag_from_avl(
        contract,
        _full_span_constant_chord_stations(avl_cl=0.4, target_cl=1.2),
        _full_span_constant_chord_stations(avl_cl=0.4, target_cl=1.2),
        assignments,
        database,
    )

    assert result.CD_profile == pytest.approx(0.010 + 0.020 * 0.4, rel=1.0e-9)
    assert result.CD_profile != pytest.approx(0.010 + 0.020 * 1.2)


def test_mission_cd0_total_est_adds_nonwing_cda_over_wing_area() -> None:
    contract = _mission_contract()
    database = _constant_cd_database(cd=0.012)
    assignments = (ZoneAirfoilAssignment("root", "constant", 0.0, 1.0),)

    result = integrate_profile_drag_from_avl(
        contract,
        _full_span_constant_chord_stations(avl_cl=0.5),
        _full_span_constant_chord_stations(avl_cl=0.5),
        assignments,
        database,
    )

    assert result.cd0_total_est == pytest.approx(
        result.CD_profile + contract.CDA_nonwing_target_m2 / contract.wing_area_m2
    )
    assert result.drag_budget_band == "over_budget"
