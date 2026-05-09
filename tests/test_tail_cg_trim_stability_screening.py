from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_tail_cg_trim_stability_screening.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_tail_cg_trim_stability_screening",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _minimal_contract() -> dict:
    return {
        "schema_version": "current_pathfinder_tail_contract_v0",
        "contract_id": "unit_tail_contract",
        "pathfinder": {"candidate_id": "unit_candidate"},
        "reference": {
            "wing": {
                "S_w_m2": {"value": 10.0},
                "b_w_m": {"value": 10.0},
                "cbar_w_m": {"value": 1.0},
                "x_ref_avl_m": {"value": 0.25},
            },
            "mission_cases": {
                "cruise": {
                    "dynamic_pressure_pa": {"value": 50.0},
                    "mass_kg": {"value": 10.0},
                    "load_factor": {"value": 1.0},
                }
            },
        },
        "horizontal_tail": {
            "design_box": {
                "S_H_m2": {"nominal": 2.0, "range": [2.0, 2.0]},
                "span_m": {"nominal": 4.0},
                "mean_chord_m": {"nominal": 0.5},
                "x_le_m": {"nominal": 4.0},
                "x_ac_H_m": {"nominal": 4.125},
                "l_H_m": {"nominal": 3.875},
                "deflection_range_deg": [-20.0, 20.0],
                "deflection_reserve_deg": {"value": 5.0},
            }
        },
        "vertical_tail": {
            "design_box": {
                "S_V_m2": {"nominal": 1.0, "range": [1.0, 1.0]},
                "height_or_span_m": {"nominal": 2.0},
                "mean_chord_m": {"nominal": 0.5},
                "x_le_m": {"nominal": 5.0},
                "x_ac_V_m": {"nominal": 5.125},
                "l_V_m": {"nominal": 4.875},
                "deflection_range_deg": [-25.0, 25.0],
                "deflection_reserve_deg": {"value": 5.0},
            }
        },
    }


def _case_results() -> dict:
    return {
        "neutral": {
            "coefficients": {"CL": 1.10, "Cm": 0.20, "Cn": 0.0, "Cl": 0.0},
            "derivatives": {
                "CL_alpha": 6.0,
                "Cm_alpha": -0.72,
                "Cn_beta": 0.016,
                "Cl_beta": -0.18,
            },
            "raw_derivatives": {
                "Xref": 0.72,
                "Cref": 1.0,
                "Xnp": 0.84,
            },
        },
        "h_delta_minus_small": {"coefficients": {"CL": 1.09, "Cm": 0.26}},
        "h_delta_plus_small": {"coefficients": {"CL": 1.11, "Cm": 0.08}},
        "v_delta_minus_small": {"coefficients": {"Cn": -0.0018, "Cl": 0.0001}},
        "v_delta_plus_small": {"coefficients": {"Cn": 0.0018, "Cl": -0.0001}},
    }


def test_tail_variant_scales_h_and_v_tail_geometry_without_promoting_source_contract() -> None:
    module = _load_script_module()
    contract = _minimal_contract()
    case = module.TailCgTrimSizingCase(
        name="unit",
        h_area_multiplier=1.25,
        h_aft_shift_m=0.5,
        v_area_multiplier=2.0,
        v_aft_shift_m=1.0,
    )

    variant, warnings = module.build_tail_contract_variant(contract, case)

    assert contract["horizontal_tail"]["design_box"]["S_H_m2"]["nominal"] == 2.0
    hbox = variant["horizontal_tail"]["design_box"]
    vbox = variant["vertical_tail"]["design_box"]
    assert hbox["S_H_m2"]["nominal"] == pytest.approx(2.5)
    assert hbox["mean_chord_m"]["nominal"] == pytest.approx(0.625)
    assert hbox["x_le_m"]["nominal"] == pytest.approx(4.5)
    assert hbox["x_ac_H_m"]["nominal"] == pytest.approx(4.65625)
    assert hbox["l_H_m"]["nominal"] == pytest.approx(4.40625)
    assert vbox["S_V_m2"]["nominal"] == pytest.approx(2.0)
    assert vbox["x_le_m"]["nominal"] == pytest.approx(6.0)
    assert warnings == []


def test_xnp_convention_is_verified_from_derivatives_and_not_promoted_blindly() -> None:
    module = _load_script_module()

    verified = module.verify_xnp_convention(
        _case_results()["neutral"],
        xref_m=0.72,
        cref_m=1.0,
    )
    assert verified["status"] == "verified_by_Cma_CLa_reference_sweep_formula"
    assert verified["xnp_from_derivatives_m"] == pytest.approx(0.84)
    assert verified["residual_m"] == pytest.approx(0.0)

    inconsistent = module.verify_xnp_convention(
        {
            **_case_results()["neutral"],
            "raw_derivatives": {"Xnp": 0.60},
        },
        xref_m=0.72,
        cref_m=1.0,
    )
    assert inconsistent["status"] == "inconsistent_do_not_use_xnp"


def test_screening_row_solves_trim_and_yaw_authority_with_explicit_cg_reference() -> None:
    module = _load_script_module()
    case = module.TailCgTrimSizingCase(
        name="unit",
        h_area_multiplier=1.25,
        h_aft_shift_m=0.5,
        v_area_multiplier=2.0,
        v_aft_shift_m=1.0,
    )

    row = module.summarize_cg_screening_row(
        sizing_case=case,
        variant_contract=_minimal_contract(),
        cg_x_m=0.72,
        case_results=_case_results(),
        cl_required=1.18,
        small_delta_deg=2.0,
        beta_screen_deg=12.0,
        static_margin_min=0.05,
        xnp_tolerance_m=1.0e-3,
    )

    assert row["status"] == "pass_screening"
    assert row["moment_reference"]["Xref_role"] == "screening_cg_moment_reference"
    assert row["xnp_convention"]["status"] == "verified_by_Cma_CLa_reference_sweep_formula"
    assert row["longitudinal_trim"]["delta_H_required_deg"] == pytest.approx(4.288288)
    assert row["longitudinal_trim"]["static_margin"] == pytest.approx(0.12)
    assert row["directional"]["delta_V_required_deg"] == pytest.approx(-3.723369)
    assert row["directional"]["delta_V_margin_to_limit_deg"] == pytest.approx(16.276631)
