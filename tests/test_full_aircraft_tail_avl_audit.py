from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "full_aircraft_tail_avl_audit_v0.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("full_aircraft_tail_avl_audit_v0", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
                "x_ref_avl_m": {"value": 0.25},
                "x_ac_w_m": {"value": None, "status": "blocking_missing"},
            },
            "cg_range_x_m": {"value": None, "status": "blocking_missing"},
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
                "z_ac_V_m": {"nominal": 0.5},
                "l_V_m": {"nominal": 1.0},
                "incidence_zero_deg": {"nominal": 0.0},
                "deflection_range_deg": [-25.0, 25.0],
                "deflection_reserve_deg": {"value": 5.0},
                "pivot_x_over_chord": {"nominal": 0.25},
                "airfoil_candidates": {"default": ["naca0009", "naca0010"]},
            }
        },
    }


def test_build_full_aircraft_deck_uses_whole_tail_rotation_without_control_proxy(tmp_path: Path) -> None:
    module = _load_script_module()
    wing = _write_minimal_wing_avl(tmp_path / "wing.avl")
    text, manifest = module.build_full_aircraft_deck_text(
        wing_avl_path=wing,
        contract=_minimal_contract(),
        delta_h_deg=5.0,
        delta_v_deg=-7.0,
    )

    assert "all_moving_geometry: r_H' = r_p,H + R_pitch(delta_H) * (r_H - r_p,H)" in text
    assert "all_moving_geometry: r_V' = r_p,V + R_yaw(delta_V) * (r_V - r_p,V)" in text
    assert "CONTROL" not in text
    assert "#IYsym  iZsym  Zsym\n0  0  0.000000" in text
    assert "SURFACE\nHorizontalTail_all_moving" in text
    assert "SURFACE\nVerticalTail_all_moving" in text

    h_root = manifest["tail_surfaces"]["horizontal_tail"]["sections"][0]
    v_root = manifest["tail_surfaces"]["vertical_tail"]["sections"][0]
    assert h_root["twist_deg"] == 5.0
    assert h_root["x_le_m"] > 4.0
    assert v_root["twist_deg"] == -7.0
    assert abs(v_root["y_le_m"]) > 0.0


def test_compute_screening_blocks_trim_when_cg_or_wing_ac_is_missing() -> None:
    module = _load_script_module()
    screening = module.compute_screening(
        contract=_minimal_contract(),
        case_results={
            "h_delta_minus_small": {"coefficients": {"Cm": 0.05, "CL": 0.8}},
            "h_delta_plus_small": {"coefficients": {"Cm": -0.03, "CL": 0.9}},
            "v_delta_minus_small": {"coefficients": {"Cn": 0.001, "Cl": -0.002}},
            "v_delta_plus_small": {"coefficients": {"Cn": 0.004, "Cl": 0.006}},
            "neutral": {
                "coefficients": {"CL": 0.85, "Cm": 0.01, "Cn": 0.002},
                "derivatives": {"CL_alpha": 5.0, "Cm_alpha": -0.4, "Cn_beta": 0.01},
            },
        },
        small_delta_h_deg=2.0,
        small_delta_v_deg=2.0,
        runner_status="completed",
    )

    assert screening["engineering_verdict"] == "blocked_by_missing_cg_or_reference_moment"
    assert screening["longitudinal_trim"]["status"] == "blocked_by_missing_cg_or_x_ac"
    assert screening["longitudinal_trim"]["CL_required"] == 0.196133
    assert screening["longitudinal_trim"]["delta_H_required"]["status"] == "blocked_by_missing_cg_or_x_ac"
    assert screening["directional"]["C_n_deltaV"] > 0.0
    assert "low_V_V_directional_authority_risk" in screening["directional"]["warnings"]


def test_parse_case_result_uses_stability_axis_cnb_not_spiral_ratio(tmp_path: Path) -> None:
    module = _load_script_module()
    st_path = tmp_path / "case.st"
    st_path.write_text(
        """
 Vortex Lattice Output -- Total Forces
  Alpha =   0.00000
  Beta  =   0.00000
  CXtot =  -0.01209     Cltot =  -0.00000     Cl'tot =  -0.00000
  CYtot =  -0.00000     Cmtot =  -0.04412
  CZtot =  -1.13060     Cntot =  -0.00000     Cn'tot =  -0.00000
  CLtot =   1.13060
  CDtot =   0.01209

 Stability-axis derivatives...
 z' force CL |    CLa =   6.188250    CLb =   0.000000
 y  force CY |    CYa =   0.000000    CYb =  -0.306049
 x' mom.  Cl'|    Cla =  -0.000000    Clb =  -0.239945
 y  mom.  Cm |    Cma =  -2.766096    Cmb =  -0.000000
 z' mom.  Cn'|    Cna =  -0.000000    Cnb =   0.002236

 Clb Cnr / Clr Cnb  =   7.674270    (  > 1 if spirally stable )
""",
        encoding="utf-8",
    )

    result = module._parse_case_result(st_path)

    assert result["derivatives"]["Cn_beta"] == 0.002236
    assert result["derivatives"]["Cl_beta"] == -0.239945
    assert result["coefficients"]["CL"] == 1.1306


def test_audit_writes_manifest_json_and_markdown_when_runner_is_disabled(tmp_path: Path) -> None:
    module = _load_script_module()
    wing = _write_minimal_wing_avl(tmp_path / "wing.avl")
    output_dir = tmp_path / "audit"
    report_json = tmp_path / "audit.json"
    report_md = tmp_path / "audit.md"

    summary = module.audit_full_aircraft_tail_avl_v0(
        contract=_minimal_contract(),
        wing_avl_path=wing,
        output_dir=output_dir,
        report_json_path=report_json,
        report_md_path=report_md,
        run_avl=False,
    )

    assert summary["runner_status"] == "runner_disabled"
    assert summary["engineering_verdict"] == "blocked_by_avl_runner_or_geometry_generation"
    assert report_json.exists()
    assert report_md.exists()
    loaded = json.loads(report_json.read_text(encoding="utf-8"))
    assert loaded["artifact_manifest"]["deck_count"] >= 9
    assert (output_dir / "manifest.json").exists()
    assert "blocked_by_avl_runner_or_geometry_generation" in report_md.read_text(encoding="utf-8")
