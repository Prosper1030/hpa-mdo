from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from tests.test_dual_beam_mainline import _simple_model


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "tail_aware_rib_rear_spar_sensitivity.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "tail_aware_rib_rear_spar_sensitivity",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _tail_basis() -> dict:
    return {
        "engineering_verdict": "ready_for_tail_aware_rib_rear_spar_sensitivity",
        "selected_basis": {
            "recommended_cg_range_x_m": [0.68, 0.75],
            "worst_static_margin": 0.088378,
            "max_abs_delta_H_required_deg": 9.326502,
            "worst_delta_H_margin_to_limit_deg": 5.673498,
            "max_abs_delta_V_required_deg": 3.931878,
            "worst_delta_V_margin_to_limit_deg": 16.068122,
            "geometry": {
                "horizontal_tail": {"S_H_m2": 4.5, "x_ac_H_m": 8.28125},
                "vertical_tail": {"S_V_m2": 3.36, "x_ac_V_m": 8.35},
            },
        },
        "tail_drag_mass_treatment": {
            "tail_cd0_increment_estimate": 0.002352,
            "tail_mass_delta_kg_estimate": 1.172727,
        },
        "rows": [
            {
                "cg_x_m": 0.75,
                "status": "pass_screening",
                "longitudinal_trim": {
                    "static_margin": 0.088378,
                    "delta_H_required_deg": 9.326502,
                    "delta_H_margin_to_limit_deg": 5.673498,
                },
                "directional": {
                    "C_n_beta": 0.016153,
                    "delta_V_required_deg": -3.779974,
                    "delta_V_margin_to_limit_deg": 16.220026,
                },
            }
        ],
    }


def test_cg_assessment_flags_uncompensated_aft_tail_shift_without_silencing_ready_row() -> None:
    module = _load_script_module()

    assessment = module.assess_mass_cg_coupling(
        base_mass_kg=96.0,
        base_cg_x_m=0.72,
        cg_range_x_m=(0.68, 0.75),
        final_screening_cg_x_m=0.75,
        mass_items=(
            module.MassItem("tail_delta", 1.172727, 8.31),
            module.MassItem("physical_rib_pack", 2.0, 0.52),
        ),
        forward_rebalance_mass_kg=56.0,
        forward_rebalance_limit_m=0.20,
    )

    assert assessment["uncompensated_status"] == "uncompensated_cg_exceeds_screening_range"
    assert assessment["screening_status"] == "final_cg_screening_row_remains_available_with_rebalance"
    assert assessment["uncompensated_cg_x_m"] > 0.75
    assert assessment["required_forward_rebalance_m"] == pytest.approx(0.098675, rel=1.0e-3)


def test_rib_mass_estimate_uses_each_family_material_density_and_thickness(tmp_path) -> None:
    module = _load_script_module()
    config_path = tmp_path / "simple_wing.yaml"
    config_path.write_text(
        """
wing:
  span: 2.0
  root_chord: 1.0
  tip_chord: 1.0
  airfoil_root_tc: 0.10
  airfoil_tip_tc: 0.10
""".lstrip(),
        encoding="utf-8",
    )
    stations = (0.0, 0.5, 1.0)

    balsa_mass = module._estimate_full_wing_rib_mass_kg(
        stations_y_m=stations,
        config_path=config_path,
        family_key="balsa_sheet_3mm",
    )
    eps_mass = module._estimate_full_wing_rib_mass_kg(
        stations_y_m=stations,
        config_path=config_path,
        family_key="eps_hd_foam_cnc_10mm",
    )

    assert eps_mass == pytest.approx(balsa_mass * (30.0 * 0.010) / (160.0 * 0.003))
    assert eps_mass != pytest.approx(balsa_mass)


def test_projected_material_family_closure_verdict_blocks_lower_gj_foam() -> None:
    module = _load_script_module()

    projection = module.project_material_family_aeroelastic_closure(
        family_key="eps_hd_foam_cnc_10mm",
        baseline_closure_basis={
            "aeroelastic_effects": {
                "elastic_twist_max_abs_deg": 5.4,
                "elastic_twist_screening_bound_deg": 3.0,
            },
            "trim_static_directional": {
                "status": "pass",
                "delta_H_margin_to_limit_deg": 3.7,
                "static_margin": 0.09,
                "C_n_beta": 0.012,
                "delta_V_margin_to_limit_deg": 17.0,
            },
        },
        balsa_selected_effective_gj_nm2=100.0,
        family_selected_effective_gj_nm2=50.0,
        structural_status="pass_screening_sensitivity",
        mass_cg_status="final_cg_screening_row_remains_available_with_rebalance",
    )

    assert projection["projected_elastic_twist_max_abs_deg"] == pytest.approx(10.8)
    assert projection["aeroelastic_closure_verdict"] == "foam_only_not_selectable_for_current_aeroelastic_closure"
    assert "elastic_twist_exceeds_screening_bound" in projection["blockers"]


def test_sensitivity_case_requires_finite_rib_basis_and_reports_effective_stiffness_changes() -> None:
    module = _load_script_module()
    model = _simple_model(
        lift_per_span_npm=[0.0, 18.0, 36.0],
        torque_per_span_nmpm=[0.0, -4.0, -8.0],
        joint_node_indices=(1,),
        wire_node_indices=(1,),
    )

    rejected = module.evaluate_structural_case(
        case_id="joint_only",
        model=model,
        rear_stiffness_scale=1.0,
        link_mode=module.LinkMode.JOINT_ONLY_OFFSET_RIGID,
        warping_knockdown=0.50,
        require_physical_rib_stations=True,
        physical_rib_station_count=0,
        baseline=None,
    )
    assert "physical_rib_station_basis_missing" in rejected.blockers

    baseline = module.evaluate_structural_case(
        case_id="finite_baseline",
        model=model,
        rear_stiffness_scale=1.0,
        link_mode=module.LinkMode.DENSE_FINITE_RIB,
        warping_knockdown=0.50,
        require_physical_rib_stations=True,
        physical_rib_station_count=7,
        baseline=None,
    )
    case = module.evaluate_structural_case(
        case_id="finite_rear_0p50",
        model=model,
        rear_stiffness_scale=0.5,
        link_mode=module.LinkMode.DENSE_FINITE_RIB,
        warping_knockdown=0.42,
        require_physical_rib_stations=True,
        physical_rib_station_count=7,
        baseline=baseline,
    )

    assert case.status == "pass_screening_sensitivity"
    assert case.effective_ei_flap_ratio_vs_baseline < 1.0
    assert case.effective_gj_ratio_vs_baseline < 1.0
    assert case.tip_main_delta_vs_baseline_pct != pytest.approx(0.0)


def test_summary_verdict_selects_ready_basis_with_tail_margins_and_closure_ranking() -> None:
    module = _load_script_module()
    ready_case = module.StructuralSensitivityCase(
        case_id="finite_rear_0p50",
        status="pass_screening_sensitivity",
        blockers=(),
        link_mode="dense_finite_rib",
        rear_stiffness_scale=0.5,
        rear_spar_participation="bounded_50pct_screening",
        warping_knockdown=0.5033,
        physical_rib_station_count=61,
        full_wing_rib_count=121,
        tip_main_m=0.63,
        tip_rear_m=0.64,
        max_vertical_displacement_m=0.64,
        max_spar_pair_line_angle_delta_deg=5.2,
        link_force_max_n=627.0,
        wire_tension_max_n=1194.0,
        tip_main_delta_vs_baseline_pct=48.0,
        max_vertical_delta_vs_baseline_pct=48.0,
        angle_delta_vs_baseline_deg=0.2,
        effective_ei_flap_ratio_vs_baseline=0.72,
        effective_gj_ratio_vs_baseline=0.54,
        structural_read="screening pass",
    )

    summary = module.build_summary_payload(
        candidate_id="current_avl_compromise_conservative_closed",
        tail_basis=_tail_basis(),
        structural_cases=(ready_case,),
        selected_case=ready_case,
        mass_cg_assessment={
            "screening_status": "final_cg_screening_row_remains_available_with_rebalance",
            "uncompensated_status": "uncompensated_cg_exceeds_screening_range",
            "final_screening_cg_x_m": 0.75,
            "uncompensated_cg_x_m": 0.79,
            "required_forward_rebalance_m": 0.10,
        },
        rib_basis={
            "family_key": "balsa_sheet_3mm",
            "spacing_m": 0.30,
            "half_wing_station_count": 61,
            "full_wing_rib_count": 121,
            "estimated_full_wing_rib_mass_kg": 2.0,
        },
        closure_rows=(
            {"selected_role": "raw_best", "closure_status": "loop_back_to_airfoil_selection"},
            {"selected_role": "conservative_best", "closure_status": "closed_for_screening"},
        ),
    )

    assert summary["engineering_verdict"] == "ready_for_tail_aware_aeroelastic_closure"
    assert summary["selected_basis"]["tail_margins_after_mass_stiffness_changes"][
        "worst_static_margin"
    ] == pytest.approx(0.088378)
    assert summary["selected_basis"]["closure_ranking_changes"] == "no_change_conservative_best_remains_screening_closed"
