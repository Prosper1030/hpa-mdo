from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_rib_torsion_rework_verdict.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_rib_torsion_rework_verdict",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _candidate(
    *,
    family_key: str,
    category: str,
    rear: float,
    rib_mass: float,
    gj_ratio: float,
    direct: float,
    bounded: float,
    verdict: str = "candidate_for_tail_aware_closure_rerun",
) -> dict:
    return {
        "family_key": family_key,
        "material_category": category,
        "rear_spar_participation": f"bounded_{int(round(rear * 100)):02d}pct_screening",
        "rear_stiffness_scale": rear,
        "rib_basis": {
            "family_key": family_key,
            "estimated_full_wing_rib_mass_kg": rib_mass,
            "estimated_rib_pack_cg_x_m": 0.52,
            "warping_knockdown": 0.8 if "hybrid" in category or "caps" in category else 0.5,
        },
        "mass_cg_assessment": {
            "screening_status": "final_cg_screening_row_remains_available_with_rebalance",
            "final_screening_cg_x_m": 0.75,
            "uncompensated_cg_x_m": 0.802,
            "required_forward_rebalance_m": 0.095,
            "forward_rebalance_mass_kg": 56.0,
        },
        "projection": {
            "candidate_rework_verdict": verdict,
            "effective_gj_ratio_vs_balsa_selected": gj_ratio,
            "projected_direct_spar_pair_twist_deg": direct,
            "projected_bounded_physical_twist_deg": bounded,
            "baseline_direct_spar_pair_twist_deg": 5.413617,
            "baseline_bounded_physical_twist_deg": 3.256324,
            "elastic_twist_screening_bound_deg": 3.0,
            "blockers": []
            if verdict == "candidate_for_tail_aware_closure_rerun"
            else ["bounded_physical_twist_still_exceeds_screening_bound"],
        },
    }


def _sensitivity_payload() -> dict:
    return {
        "candidate_id": "current_avl_compromise_conservative_closed",
        "selected_basis": {
            "case_id": "finite_rib_rear_0p50_selected_screening_basis",
            "rib_spacing_m": 0.30,
            "rear_spar_participation": "bounded_50pct_screening",
            "rear_stiffness_scale": 0.50,
            "warping_knockdown": 0.50246,
            "structural_mass_delta": {
                "estimated_full_wing_rib_mass_kg": 3.029671,
                "tail_mass_delta_kg": 1.172727,
                "rear_spar_mass_delta_kg": 0.0,
            },
            "cg_impact": {
                "screening_status": "final_cg_screening_row_remains_available_with_rebalance",
                "final_screening_cg_x_m": 0.75,
                "uncompensated_cg_x_m": 0.801026,
                "required_forward_rebalance_m": 0.091302,
                "forward_rebalance_mass_kg": 56.0,
            },
        },
        "stiffness_rework_candidates": [
            _candidate(
                family_key="balsa_sheet_3mm",
                category="balsa_baseline",
                rear=1.0,
                rib_mass=3.029671,
                gj_ratio=1.9,
                direct=2.85,
                bounded=1.72,
            ),
            _candidate(
                family_key="eps_hd_foam_cnc_10mm",
                category="eps_foam_only",
                rear=0.65,
                rib_mass=1.9,
                gj_ratio=2.2,
                direct=2.46,
                bounded=1.48,
            ),
            _candidate(
                family_key="eps_balsa_cap_hybrid_10mm",
                category="capped_hybrid_foam_rib",
                rear=0.50,
                rib_mass=5.365042,
                gj_ratio=1.63,
                direct=3.33,
                bounded=2.00,
            ),
            _candidate(
                family_key="eps_balsa_cap_hybrid_10mm",
                category="capped_hybrid_foam_rib",
                rear=0.65,
                rib_mass=5.365042,
                gj_ratio=2.03,
                direct=2.66,
                bounded=1.60,
            ),
            _candidate(
                family_key="structural_foam_glass_face_10mm",
                category="structural_foam_caps_faces",
                rear=0.50,
                rib_mass=11.361265,
                gj_ratio=1.83,
                direct=2.95,
                bounded=1.78,
            ),
        ],
    }


def _closure_payload() -> dict:
    return {
        "engineering_verdict": "needs_aeroelastic_geometry_or_stiffness_rework",
        "blockers": ["elastic_twist_exceeds_screening_bound"],
        "warnings": ["negative_diagnostic_stall_margin_not_gate"],
        "basis": {
            "aeroelastic_effects": {
                "elastic_twist_max_abs_deg": 5.413617,
                "direct_spar_pair_rotation_max_abs_deg": 5.413494,
                "conservative_bounded_physical_projection_max_abs_deg": 3.256324,
                "elastic_twist_screening_bound_deg": 3.0,
            },
            "aeroelastic_twist_source_audit": {
                "dominant_source_at_direct_max_station": {
                    "dominant_component": "aerodynamic_torque_only",
                    "station_y_m": 2.327757,
                },
                "interpretation_summary": {
                    "direct_spar_pair_rotation_max_abs_deg": 5.413494,
                    "direct_spar_pair_rotation_max_station_y_m": 2.327757,
                    "conservative_bounded_physical_projection_max_abs_deg": 3.256324,
                    "conservative_bounded_physical_projection_max_station_y_m": 2.327757,
                    "screening_bound_deg": 3.0,
                },
            },
            "trim_static_directional": {"status": "pass"},
            "cg_management": {"status": "managed_final_cg_pass"},
        },
    }


def _audit_payload() -> dict:
    return {
        "overall_verdict": "blocked_needs_materialized_bond_shape_data",
        "station_bay_trace": {
            "full_wing_station_count": 121,
            "full_wing_bay_count": 120,
            "max_materialized_bay_m": 0.297063,
        },
        "mandatory_rib_reason": [
            {"contract_item": "root", "status": "materialized_mandatory"},
            {"contract_item": "transport_joint", "status": "missing_contract"},
            {"contract_item": "control_station", "status": "missing_contract"},
            {"contract_item": "airfoil_transition", "status": "missing_contract"},
            {"contract_item": "twist_transition", "status": "missing_contract"},
        ],
        "skin_sag_screening": [
            {"shape_sag_status": "unknown_requires_test"},
            {"shape_sag_status": "unknown_requires_test_torque_zone"},
        ],
        "bond_collar_risk_screening": [
            {"bond_risk_status": "needs_data"},
            {"bond_risk_status": "needs_data_torque_or_mandatory_zone"},
        ],
        "local_fem_trigger_report": {
            "overall_verdict": "local_fem_required_before_hybrid_pass_claim",
            "peak_twist_station_y_m": 2.327757,
            "dominant_twist_source": "aerodynamic_torque_only",
            "recommended_hybrid_reinforcement_zones": [
                {
                    "zone_id": "positive_torque_critical_hybrid_reinforcement_zone",
                    "y_start_m": 2.028,
                    "y_end_m": 2.628,
                    "station_ids": ["R067", "R068", "R069"],
                }
            ],
        },
    }


def test_selects_low_mass_hybrid_candidate_and_accounts_mass_cg_tail_trim() -> None:
    module = _load_script_module()

    summary = module.build_rib_torsion_rework_verdict(
        sensitivity_payload=_sensitivity_payload(),
        closure_payload=_closure_payload(),
        audit_payload=_audit_payload(),
    )

    selected = summary["selected_rework_candidate"]
    assert selected["family_key"] == "eps_balsa_cap_hybrid_10mm"
    assert selected["rear_spar_participation"] == "bounded_65pct_screening"
    assert selected["projected_direct_spar_pair_twist_deg"] < 3.0
    assert selected["projected_bounded_physical_twist_deg"] < 3.0
    assert selected["mass_cg_tail_trim_impact"]["rib_mass_delta_vs_baseline_kg"] == pytest.approx(
        2.335371
    )
    assert selected["mass_cg_tail_trim_impact"]["mass_cg_status"] == (
        "final_cg_screening_row_remains_available_with_rebalance"
    )


def test_projection_and_missing_detail_block_fem_apdl_package_ready_claim() -> None:
    module = _load_script_module()

    summary = module.build_rib_torsion_rework_verdict(
        sensitivity_payload=_sensitivity_payload(),
        closure_payload=_closure_payload(),
        audit_payload=_audit_payload(),
    )

    assert (
        summary["engineering_verdict"]
        == "candidate_ready_for_local_FEM_and_coupon_before_FEM_package"
    )
    gate = summary["fem_apdl_package_gate"]
    assert gate["ready"] is False
    assert "hybrid_effective_gj_is_projection_only_not_closure_rerun" in gate["blockers"]
    assert "missing_transition_or_control_station_contract" in gate["blockers"]
    assert "skin_sag_unknown_requires_test" in gate["blockers"]
    assert "bond_collar_spar_contact_needs_data" in gate["blockers"]
    assert "torque_critical_local_fem_required" in gate["blockers"]


def test_rear_spar_one_point_zero_and_foam_only_are_never_selected_pass_basis() -> None:
    module = _load_script_module()

    summary = module.build_rib_torsion_rework_verdict(
        sensitivity_payload=_sensitivity_payload(),
        closure_payload=_closure_payload(),
        audit_payload=_audit_payload(),
    )

    rejected = {
        (row["family_key"], row["rear_spar_participation"]): row["rejection_reasons"]
        for row in summary["candidate_trade_rows"]
        if row["selection_status"] == "rejected"
    }
    assert "rear_spar_participation_1p00_is_upper_bound_only" in rejected[
        ("balsa_sheet_3mm", "bounded_100pct_screening")
    ]
    assert "foam_only_not_allowed_as_structural_bracing" in rejected[
        ("eps_hd_foam_cnc_10mm", "bounded_65pct_screening")
    ]
    assert summary["selected_rework_candidate"]["rear_stiffness_scale"] < 1.0


def test_closure_rerun_still_reports_direct_stress_test_and_detail_blockers() -> None:
    module = _load_script_module()

    closure_rerun = {
        "engineering_verdict": "ready_for_fem_apdl_loadcase_package",
        "basis": {
            "aeroelastic_effects": {
                "elastic_twist_max_abs_deg": 2.72,
                "direct_spar_pair_rotation_max_abs_deg": 3.18,
                "conservative_bounded_physical_projection_max_abs_deg": 2.44,
                "elastic_twist_screening_bound_deg": 3.0,
            }
        },
    }
    summary = module.build_rib_torsion_rework_verdict(
        sensitivity_payload=_sensitivity_payload(),
        closure_payload=_closure_payload(),
        audit_payload=_audit_payload(),
        closure_rerun_payload=closure_rerun,
    )

    assert (
        summary["engineering_verdict"]
        == "candidate_ready_for_local_FEM_and_coupon_before_FEM_package"
    )
    assert summary["closure_rerun_assessment"]["bounded_twist_status"] == "clears_bound"
    assert summary["closure_rerun_assessment"]["direct_stress_test_status"] == (
        "above_bound_conservative_stress_test"
    )
    assert summary["fem_apdl_package_gate"]["ready"] is False
    assert "bond_collar_spar_contact_needs_data" in summary["fem_apdl_package_gate"]["blockers"]


def test_kernel_owned_hybrid_closure_rerun_removes_projection_only_blocker() -> None:
    module = _load_script_module()

    closure_rerun = {
        "engineering_verdict": "ready_for_fem_apdl_loadcase_package",
        "basis": {
            "aeroelastic_effects": {
                "elastic_twist_max_abs_deg": 3.72,
                "direct_spar_pair_rotation_max_abs_deg": 3.72,
                "conservative_bounded_physical_projection_max_abs_deg": 2.24,
                "elastic_twist_screening_bound_deg": 3.0,
            },
            "selected_stiffness_basis": {
                "structural_kernel_stiffness_override": {
                    "status": "applied_screening_surrogate",
                    "applied_global_torsion_cell_scale": 2.032971,
                }
            },
        },
    }
    summary = module.build_rib_torsion_rework_verdict(
        sensitivity_payload=_sensitivity_payload(),
        closure_payload=_closure_payload(),
        audit_payload=_audit_payload(),
        closure_rerun_payload=closure_rerun,
    )

    assert (
        summary["engineering_verdict"]
        == "candidate_ready_for_local_FEM_and_coupon_before_FEM_package"
    )
    assert summary["closure_rerun_assessment"]["bounded_twist_status"] == "clears_bound"
    assert summary["closure_rerun_assessment"]["direct_stress_test_status"] == (
        "above_bound_conservative_stress_test"
    )
    blockers = summary["fem_apdl_package_gate"]["blockers"]
    assert "hybrid_effective_gj_is_projection_only_not_closure_rerun" not in blockers
    assert "closure_rerun_elastic_twist_exceeds_bound" not in blockers
    assert "direct_spar_pair_stress_test_still_above_bound" not in blockers
    assert "bond_collar_spar_contact_needs_data" in blockers
    required = summary["local_fem_coupon_requirements"]["required_before_fem_apdl_package"]
    assert "closure rerun with the selected effective stiffness model wired in" not in required
    carry_forward = summary["local_fem_coupon_requirements"]["closure_evidence_to_carry_forward"]
    assert carry_forward["owns_selected_hybrid_stiffness_model"] is True
    package = summary["local_fem_coupon_validation_package"]
    assert package["package_verdict"] == (
        "ready_to_start_local_FEM_and_coupon_definition_not_FEM_APDL_package"
    )
    assert package["closure_evidence"]["bounded_twist_status"] == "clears_bound"
    assert "positive_torque_critical_hybrid_reinforcement_zone" in {
        row["zone_id"] for row in package["local_fem_zones"]
    }
    workstreams = {row["workstream_id"] for row in package["validation_workstreams"]}
    assert {
        "rib_spar_bond_collar_local_fem",
        "skin_sag_panel_coupon",
        "direct_stress_test_aero_surface_mapping",
    } <= workstreams
    assert "EPS/XPS/structural-foam-only as structural bracing" in package["do_not_promote"]


def test_builds_rear_spar_closure_rerun_basis_without_promoting_hybrid_projection() -> None:
    module = _load_script_module()

    payload = module.build_closure_rerun_selected_basis_payload(
        sensitivity_payload=_sensitivity_payload(),
        family_key="eps_balsa_cap_hybrid_10mm",
        rear_spar_participation="bounded_65pct_screening",
    )

    assert payload["candidate_id"] == "current_avl_compromise_conservative_closed"
    assert payload["rib_basis"]["family_key"] == "eps_balsa_cap_hybrid_10mm"
    assert payload["selected_basis"]["case_id"] == (
        "closure_rerun_eps_balsa_cap_hybrid_10mm_bounded_65pct_screening_structural_kernel_v1"
    )
    assert payload["selected_basis"]["rear_spar_participation"] == "bounded_65pct_screening"
    assert payload["selected_basis"]["rear_stiffness_scale"] == pytest.approx(0.65)
    override = payload["selected_basis"]["structural_kernel_stiffness_override"]
    assert override["status"] == "screening_surrogate_ready_for_closure_rerun"
    assert override["model_id"] == "hybrid_main_rear_torsion_cell_scale_v1"
    assert override["global_torsion_cell_scale"] == pytest.approx(2.03, rel=1.0e-3)
    assert payload["selected_basis"]["hybrid_effective_gj_claim_boundary"] == (
        "screening_surrogate_consumed_by_structural_kernel"
    )
    assert payload["selected_basis"]["structural_mass_delta"][
        "estimated_full_wing_rib_mass_kg"
    ] == pytest.approx(5.365042)
