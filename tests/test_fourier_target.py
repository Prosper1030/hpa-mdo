from __future__ import annotations

import math

import numpy as np
import pytest

from hpa_mdo.aero.fourier_target import build_fourier_target, compare_fourier_target_to_avl
from hpa_mdo.mission.contract import MissionContract


def _mission_contract() -> MissionContract:
    span_m = 34.0
    aspect_ratio = 38.0
    wing_area_m2 = span_m**2 / aspect_ratio
    mass_kg = 98.5
    weight_n = mass_kg * 9.80665
    speed_mps = 6.6
    rho = 1.14
    cl_req = weight_n / (0.5 * rho * speed_mps**2 * wing_area_m2)
    return MissionContract(
        speed_mps=speed_mps,
        span_m=span_m,
        aspect_ratio=aspect_ratio,
        wing_area_m2=wing_area_m2,
        mass_kg=mass_kg,
        weight_n=weight_n,
        rho=rho,
        CL_req=cl_req,
        target_range_km=42.195,
        required_time_min=42.195 * 1000.0 / speed_mps / 60.0,
        eta_prop=0.88,
        eta_trans=0.96,
        pilot_power_hot_w=205.0,
        power_margin_required_w=5.0,
        CD0_total_target=0.017,
        CD0_total_boundary=0.018,
        CD0_total_rescue=0.020,
        CD_wing_profile_target=0.017 - 0.13 / wing_area_m2,
        CD_wing_profile_boundary=0.018 - 0.16 / wing_area_m2,
        CDA_nonwing_target_m2=0.13,
        CDA_nonwing_boundary_m2=0.16,
        CLmax_effective_assumption=1.55,
        mission_contract_source="unit_test_contract",
    )


def _eta_grid() -> tuple[float, ...]:
    return tuple(float(value) for value in np.linspace(0.0, 1.0, 81))


def _chord_ref(eta: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(1.22 - 0.72 * float(value) for value in eta)


def test_elliptical_target_has_unit_theoretical_efficiency_and_a1_from_contract() -> None:
    contract = _mission_contract()
    eta = _eta_grid()

    target = build_fourier_target(contract, _chord_ref(eta), eta, r3=0.0, r5=0.0)

    assert target.e_theory == pytest.approx(1.0)
    assert target.A1 == pytest.approx(contract.CL_req / (math.pi * contract.aspect_ratio))
    assert target.r3 == pytest.approx(0.0)
    assert target.r5 == pytest.approx(0.0)


def test_theoretical_efficiency_decreases_when_higher_harmonics_are_nonzero() -> None:
    contract = _mission_contract()
    eta = _eta_grid()
    elliptical = build_fourier_target(contract, _chord_ref(eta), eta, r3=0.0, r5=0.0)
    shaped = build_fourier_target(contract, _chord_ref(eta), eta, r3=-0.05, r5=0.02)

    assert shaped.e_theory < elliptical.e_theory
    assert shaped.e_theory == pytest.approx(1.0 / (1.0 + 3.0 * 0.05**2 + 5.0 * 0.02**2))


def test_integrated_target_lift_reconstructs_mission_weight() -> None:
    contract = _mission_contract()
    eta = _eta_grid()

    target = build_fourier_target(contract, _chord_ref(eta), eta, r3=-0.05, r5=0.01)

    assert target.lift_total_n == pytest.approx(contract.weight_n, rel=7.0e-3)
    assert abs(target.lift_error_fraction) < 7.0e-3


def test_gamma_is_nonnegative_for_nominal_accepted_candidate() -> None:
    contract = _mission_contract()
    eta = tuple(float(value) for value in np.linspace(0.0, 0.97, 65))

    target = build_fourier_target(contract, _chord_ref(eta), eta, r3=-0.05, r5=0.0)

    assert target.gamma_min >= -1.0e-9
    assert target.cl_max > 0.0
    assert all(math.isfinite(value) for value in target.cl_target)


def test_target_vs_avl_comparison_accepts_synthetic_matching_loading() -> None:
    contract = _mission_contract()
    eta = _eta_grid()
    target = build_fourier_target(contract, _chord_ref(eta), eta, r3=-0.04, r5=0.015)
    station_table = [
        {
            "eta": eta_value,
            "avl_circulation_proxy": gamma,
        }
        for eta_value, gamma in zip(target.eta, target.gamma_target)
    ]

    comparison = compare_fourier_target_to_avl(target, station_table)

    assert comparison["target_vs_avl_compare_success"] is True
    assert comparison["target_vs_avl_rms_delta"] == pytest.approx(0.0, abs=1.0e-9)
    assert comparison["target_vs_avl_max_delta"] == pytest.approx(0.0, abs=1.0e-9)
    assert comparison["target_vs_avl_outer_delta"] == pytest.approx(0.0, abs=1.0e-9)
