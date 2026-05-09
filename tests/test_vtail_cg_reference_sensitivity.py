from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "vtail_cg_reference_sensitivity_v0.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("vtail_cg_reference_sensitivity_v0", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _minimal_contract() -> dict:
    return {
        "schema_version": "current_pathfinder_tail_contract_v0",
        "contract_id": "test_tail_contract",
        "pathfinder": {"candidate_id": "unit_candidate"},
        "reference": {
            "wing": {
                "S_w_m2": {"value": 10.0},
                "b_w_m": {"value": 10.0},
                "cbar_w_m": {"value": 1.0},
                "x_ref_avl_m": {
                    "value": 0.25,
                    "status": "reference_only_not_wing_aerodynamic_center",
                    "source": "unit.avl:#Xref",
                },
                "x_ac_w_m": {
                    "value": None,
                    "status": "blocking_missing",
                    "reason": "unit test keeps wing AC missing",
                },
            },
            "cg_range_x_m": {
                "value": None,
                "status": "blocking_missing",
                "reason": "unit test keeps CG missing",
            },
            "mission_cases": {
                "cruise": {
                    "speed_mps": {"value": 10.0},
                    "rho_kgpm3": {"value": 1.0},
                    "dynamic_pressure_pa": {"value": 50.0},
                    "mass_kg": {"value": 10.0},
                    "load_factor": {"value": 1.0},
                }
            },
        },
        "horizontal_tail": {
            "design_box": {
                "S_H_m2": {"nominal": 2.0},
                "span_m": {"nominal": 4.0},
                "mean_chord_m": {"nominal": 0.5},
                "x_le_m": {"nominal": 4.0},
                "z_ac_H_m": {"nominal": 0.0},
                "incidence_zero_deg": {"nominal": 0.0},
                "deflection_range_deg": [-20.0, 20.0],
                "deflection_reserve_deg": {"value": 5.0},
                "pivot_x_over_chord": {"nominal": 0.25},
                "airfoil_candidates": {"default": "naca0010"},
            }
        },
        "vertical_tail": {
            "design_box": {
                "S_V_m2": {"nominal": 1.0},
                "height_or_span_m": {"nominal": 2.0},
                "mean_chord_m": {"nominal": 0.5},
                "x_le_m": {"nominal": 5.0},
                "x_ac_V_m": {"nominal": 5.125},
                "z_ac_V_m": {"nominal": 0.5},
                "l_V_m": {"nominal": 4.875},
                "incidence_zero_deg": {"nominal": 0.0},
                "deflection_range_deg": [-25.0, 25.0],
                "deflection_reserve_deg": {"value": 5.0},
                "pivot_x_over_chord": {"nominal": 0.25},
                "airfoil_candidates": {"default": ["naca0009", "naca0010"]},
            }
        },
    }


def _write_minimal_wing_avl(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "Minimal wing",
                "#Mach",
                "0.000000",
                "#IYsym  iZsym  Zsym",
                "1  0  0.000000",
                "#Sref  Cref  Bref",
                "10.000000000  1.000000000  10.000000000",
                "#Xref  Yref  Zref",
                "0.250000000  0.000000000  0.000000000",
                "#CDp",
                "0.000000",
                "#",
                "SURFACE",
                "Wing",
                "8  1.0  12  -2.0",
                "#",
                "SECTION",
                "0.000000000  0.000000000  0.000000000  1.000000000  0.000000000",
                "NACA",
                "0012",
                "#",
                "SECTION",
                "0.000000000  5.000000000  0.000000000  1.000000000  0.000000000",
                "NACA",
                "0012",
                "#",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_vtail_variant_scales_area_chord_and_tail_arm_without_mutating_source() -> None:
    module = _load_script_module()
    contract = _minimal_contract()
    case = module.VtailSizingCase(name="sv2p0_xaft0p5", area_multiplier=2.0, aft_shift_m=0.5)

    variant, warnings = module.build_vtail_contract_variant(contract, case)

    original_vbox = contract["vertical_tail"]["design_box"]
    vbox = variant["vertical_tail"]["design_box"]
    assert original_vbox["S_V_m2"]["nominal"] == 1.0
    assert vbox["S_V_m2"]["nominal"] == pytest.approx(2.0)
    assert vbox["mean_chord_m"]["nominal"] == pytest.approx(1.0)
    assert vbox["x_le_m"]["nominal"] == pytest.approx(5.5)
    assert vbox["x_ac_V_m"]["nominal"] == pytest.approx(5.75)
    assert vbox["l_V_m"]["nominal"] == pytest.approx(5.5)
    assert module.vertical_tail_volume(variant) == pytest.approx(0.11)
    assert warnings == []


def test_reference_audit_does_not_promote_xref_xnp_or_estimated_mass_to_cg_truth() -> None:
    module = _load_script_module()
    audit = module.audit_cg_reference_contract(
        _minimal_contract(),
        full_aircraft_audit={
            "case_results": {
                "neutral": {
                    "raw_derivatives": {
                        "Xref": 0.25,
                        "Xnp": 0.72,
                        "Cref": 1.0,
                    }
                }
            }
        },
        candidate_mass_config={
            "mass_budget": {
                "pilot": {
                    "m_kg": 56.0,
                    "xyz_m": [0.4, 0.0, -0.5],
                    "source": "estimated",
                }
            }
        },
        candidate_mass_config_tracked=False,
    )

    assert audit["overall_status"] == "blocked_by_missing_cg_or_reference_moment"
    assert audit["Xref"]["status"] == "reference_only_not_aerodynamic_center"
    assert audit["Xnp"]["status"] == "candidate_only_convention_not_verified"
    assert audit["x_ac_w"]["status"] == "blocking_missing"
    assert audit["x_cg"]["status"] == "blocking_missing"
    assert audit["mass_manifest"]["status"] == "estimated_or_untracked_not_promoted"


def test_case_summary_marks_directional_signs_and_yaw_roll_coupling() -> None:
    module = _load_script_module()
    summary = module.summarize_vtail_case(
        case=module.VtailSizingCase(name="unit", area_multiplier=1.0, aft_shift_m=0.0),
        variant_contract=_minimal_contract(),
        case_results={
            "neutral": {
                "run_status": "completed",
                "derivatives": {"Cn_beta": 0.006, "Cl_beta": -0.18},
            },
            "v_delta_minus_small": {
                "run_status": "completed",
                "coefficients": {"Cn": -0.001, "Cl": 0.0005},
            },
            "v_delta_plus_small": {
                "run_status": "completed",
                "coefficients": {"Cn": 0.003, "Cl": -0.0005},
            },
        },
        small_delta_deg=2.0,
        run_status="completed",
        geometry_warnings=[],
    )

    assert summary["V_V"] == pytest.approx(0.04875)
    assert summary["C_n_beta"] == 0.006
    assert summary["C_n_deltaV"] > 0.0
    assert summary["derivative_signs"]["C_n_beta"]["physically_plausible"] is True
    assert summary["derivative_signs"]["C_n_deltaV"]["physically_plausible"] is True
    assert summary["yaw_roll_coupling_warning"]["status"] == "warning_not_limit_checked"


def test_sensitivity_writes_json_markdown_and_manifest_when_runner_is_disabled(tmp_path: Path) -> None:
    module = _load_script_module()
    output_dir = tmp_path / "vtail_sensitivity"
    report_json = tmp_path / "sensitivity.json"
    report_md = tmp_path / "sensitivity.md"

    summary = module.run_vtail_cg_reference_sensitivity_v0(
        contract=_minimal_contract(),
        wing_avl_path=_write_minimal_wing_avl(tmp_path / "wing.avl"),
        output_dir=output_dir,
        report_json_path=report_json,
        report_md_path=report_md,
        cases=(module.VtailSizingCase(name="sv1p0_xaft0p0", area_multiplier=1.0, aft_shift_m=0.0),),
        run_avl=False,
        full_aircraft_audit={},
        candidate_mass_config={},
        candidate_mass_config_tracked=False,
    )

    assert summary["engineering_verdict"] == "blocked_by_geometry_or_avl_generation"
    assert summary["runner_status"] == "runner_disabled"
    assert summary["sensitivity_cases"][0]["deck_run_status"] == "runner_disabled"
    assert report_json.exists()
    assert report_md.exists()
    assert (output_dir / "manifest.json").exists()
    loaded = json.loads(report_json.read_text(encoding="utf-8"))
    assert loaded["artifact_manifest"]["deck_count"] == 3
    assert "blocked_by_geometry_or_avl_generation" in report_md.read_text(encoding="utf-8")
