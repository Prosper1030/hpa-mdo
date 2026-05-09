from __future__ import annotations

import pytest

from hpa_mdo.aero.tail_contract import screen_tail_contract


def test_screen_tail_contract_computes_volumes_and_keeps_missing_inputs() -> None:
    contract = {
        "contract_id": "unit_tail_contract_v0",
        "pathfinder": {"candidate_id": "current_avl_compromise_conservative_closed"},
        "reference": {
            "wing": {
                "S_w_m2": {"value": 33.420059598},
                "b_w_m": {"value": 34.332286},
                "cbar_w_m": {"value": 1.003721543},
                "x_ac_w_m": {
                    "value": None,
                    "status": "blocking_missing",
                    "reason": "No current artifact identifies wing aerodynamic center.",
                },
            },
            "cg_range_x_m": {
                "value": None,
                "status": "blocking_missing",
                "reason": "No current pathfinder CG manifest.",
            },
        },
        "horizontal_tail": {
            "design_box": {
                "S_H_m2": {"nominal": 3.6},
                "l_H_m": {"nominal": 6.478723488},
                "deflection_range_deg": [-20.0, 20.0],
                "deflection_reserve_deg": 5.0,
            }
        },
        "vertical_tail": {
            "design_box": {
                "S_V_m2": {"nominal": 1.68},
                "l_V_m": {"nominal": 6.928723488},
                "deflection_range_deg": [-25.0, 25.0],
                "deflection_reserve_deg": 5.0,
            }
        },
        "required_inputs_missing": [
            {"field": "cg_range_x_m", "reason": "No current pathfinder CG manifest."}
        ],
    }

    result = screen_tail_contract(contract)

    assert result["status"] == "required_inputs_missing"
    assert result["candidate_id"] == "current_avl_compromise_conservative_closed"
    assert result["computed"]["horizontal_tail"]["tail_volume_coefficient"] == pytest.approx(
        0.6952987999439312
    )
    assert result["computed"]["vertical_tail"]["tail_volume_coefficient"] == pytest.approx(
        0.01014501211088028
    )
    assert result["computed"]["horizontal_tail"]["usable_deflection_range_deg"] == [
        -15.0,
        15.0,
    ]
    assert result["computed"]["vertical_tail"]["usable_deflection_range_deg"] == [-20.0, 20.0]
    missing_fields = {item["field"] for item in result["required_inputs_missing"]}
    assert {"cg_range_x_m", "reference.wing.x_ac_w_m"}.issubset(missing_fields)


def test_screen_tail_contract_marks_missing_reference_values() -> None:
    result = screen_tail_contract(
        {
            "contract_id": "missing_wing_refs",
            "reference": {"wing": {"S_w_m2": {"value": 33.0}}},
            "horizontal_tail": {"design_box": {"S_H_m2": {"nominal": 3.0}}},
        }
    )

    assert result["status"] == "required_inputs_missing"
    missing_fields = {item["field"] for item in result["required_inputs_missing"]}
    assert "reference.wing.b_w_m" in missing_fields
    assert "reference.wing.cbar_w_m" in missing_fields
    assert result["computed"]["horizontal_tail"]["tail_volume_coefficient"] is None
