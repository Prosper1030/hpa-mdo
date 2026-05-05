from __future__ import annotations

import pytest

from hpa_mdo.mission.contract import (
    MISSION_CONTRACT_SHADOW_FIELDS,
    build_mission_contract,
)


def _contract_context() -> dict[str, object]:
    return {
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


def test_build_mission_contract_uses_sizing_and_drag_budget_formulas() -> None:
    contract = build_mission_contract(
        {
            "speed_mps": 6.5,
            "span_m": 35.0,
            "aspect_ratio": 38.0,
            "mass_kg": 98.5,
            "rho": 1.1357,
            "eta_prop": 0.86,
            "eta_trans": 0.96,
            "pilot_power_hot_w": 205.0,
            "CLmax_effective_assumption": 1.55,
        },
        _contract_context(),
    )

    wing_area = 35.0**2 / 38.0
    weight_n = 98.5 * 9.80665
    cl_req = weight_n / (0.5 * 1.1357 * 6.5**2 * wing_area)

    assert contract.wing_area_m2 == pytest.approx(wing_area)
    assert contract.weight_n == pytest.approx(weight_n)
    assert contract.CL_req == pytest.approx(cl_req)
    assert contract.required_time_min == pytest.approx(42.195 * 1000.0 / 6.5 / 60.0)
    assert contract.CD_wing_profile_target == pytest.approx(0.017 - 0.13 / wing_area)
    assert contract.CD_wing_profile_boundary == pytest.approx(0.018 - 0.16 / wing_area)
    assert contract.mission_contract_source == "unit_test_context"


def test_mission_contract_shadow_fields_use_requested_export_names() -> None:
    contract = build_mission_contract(
        {
            "speed_mps": 6.6,
            "span_m": 34.0,
            "aspect_ratio": 37.0,
            "mass_kg": 101.0,
            "air_density_kg_m3": 1.14,
            "pilot_power_hot_w": 202.0,
            "CLmax_effective_assumption": 1.50,
        },
        _contract_context(),
    )

    fields = contract.to_shadow_fields()

    assert tuple(fields) == MISSION_CONTRACT_SHADOW_FIELDS
    assert fields["mission_CL_req"] == pytest.approx(contract.CL_req)
    assert fields["mission_CD_wing_profile_target"] == pytest.approx(
        contract.CD_wing_profile_target
    )
    assert fields["mission_CD_wing_profile_boundary"] == pytest.approx(
        contract.CD_wing_profile_boundary
    )
    assert fields["mission_CDA_nonwing_target_m2"] == pytest.approx(
        contract.CDA_nonwing_target_m2
    )
    assert fields["mission_CDA_nonwing_boundary_m2"] == pytest.approx(
        contract.CDA_nonwing_boundary_m2
    )
    assert fields["mission_power_margin_required_w"] == pytest.approx(5.0)
    assert fields["mission_contract_source"] == "unit_test_context"
