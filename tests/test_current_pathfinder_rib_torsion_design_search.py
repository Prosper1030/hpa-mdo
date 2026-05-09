from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_rib_torsion_design_search.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_rib_torsion_design_search",
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
    thickness_m: float,
    density: float,
) -> dict:
    return {
        "family_key": family_key,
        "material_category": category,
        "rear_spar_participation": f"bounded_{int(round(rear * 100)):02d}pct_screening",
        "rear_stiffness_scale": rear,
        "rib_basis": {
            "family_key": family_key,
            "spacing_m": 0.30,
            "max_recommended_subbay_m": 0.297063,
            "half_wing_station_count": 61,
            "full_wing_rib_count": 121,
            "estimated_full_wing_rib_mass_kg": rib_mass,
            "estimated_rib_pack_cg_x_m": 0.461633,
            "warping_knockdown": 0.82 if "hybrid" in category or "face" in category else 0.50,
            "material_basis": {
                "family_key": family_key,
                "family_category": category,
                "thickness_m": thickness_m,
                "density_kgpm3": density,
                "trust_level": "test_screening",
                "label": family_key,
                "stiffness_proxy": {
                    "construction_factor": 1.0,
                    "rotational_fixity_factor": 1.0,
                    "shear_transfer_factor": 1.0,
                },
                "spacing_guidance": {"min_m": 0.18, "nominal_m": 0.30, "max_m": 0.36},
            },
        },
        "mass_cg_assessment": {
            "screening_status": "final_cg_screening_row_remains_available_with_rebalance",
            "final_screening_cg_x_m": 0.75,
            "uncompensated_cg_x_m": 0.793296,
            "required_forward_rebalance_m": 0.079276,
            "forward_rebalance_mass_kg": 56.0,
        },
        "projection": {
            "candidate_rework_verdict": "candidate_for_tail_aware_closure_rerun",
            "effective_gj_ratio_vs_balsa_selected": gj_ratio,
            "projected_direct_spar_pair_twist_deg": direct,
            "projected_bounded_physical_twist_deg": bounded,
            "baseline_direct_spar_pair_twist_deg": 5.413617,
            "baseline_bounded_physical_twist_deg": 3.256324,
            "elastic_twist_screening_bound_deg": 3.0,
            "blockers": [],
        },
    }


def _sensitivity_payload() -> dict:
    rows = []
    families = [
        ("balsa_sheet_3mm", "balsa_baseline", 3.029671, 1.00, 5.413617, 3.256324, 0.003, 160.0),
        ("eps_hd_foam_cnc_10mm", "eps_foam_only", 1.893544, 0.62, 8.731640, 5.252135, 0.010, 30.0),
        ("xps_high_compressive_cnc_10mm", "xps_foam_only", 2.019781, 0.66, 8.202450, 4.933824, 0.010, 32.0),
        ("structural_foam_cnc_10mm", "structural_foam_only", 3.787089, 0.85, 6.368961, 3.831000, 0.010, 60.0),
        (
            "eps_balsa_cap_hybrid_10mm",
            "capped_hybrid_foam_rib",
            5.365042,
            2.032971,
            2.662909,
            1.601756,
            0.010,
            85.0,
        ),
        (
            "structural_foam_glass_face_10mm",
            "structural_foam_caps_faces",
            11.361265,
            2.38,
            2.274629,
            1.368203,
            0.010,
            180.0,
        ),
    ]
    for family in families:
        key, category, mass, gj_at_65, direct_at_65, bounded_at_65, thickness, density = family
        for rear, rear_factor in ((0.50, 0.80), (0.65, 1.00), (0.75, 1.12)):
            gj_ratio = gj_at_65 * rear_factor
            rows.append(
                _candidate(
                    family_key=key,
                    category=category,
                    rear=rear,
                    rib_mass=mass,
                    gj_ratio=gj_ratio,
                    direct=direct_at_65 / rear_factor,
                    bounded=bounded_at_65 / rear_factor,
                    thickness_m=thickness,
                    density=density,
                )
            )
    return {
        "candidate_id": "current_avl_compromise_conservative_closed",
        "selected_basis": {
            "rib_spacing_m": 0.30,
            "rear_spar_participation": "bounded_50pct_screening",
            "rear_stiffness_scale": 0.50,
            "structural_mass_delta": {
                "estimated_full_wing_rib_mass_kg": 3.029671,
                "tail_mass_delta_kg": 1.172727,
            },
            "cg_impact": {
                "screening_status": "final_cg_screening_row_remains_available_with_rebalance",
                "final_screening_cg_x_m": 0.75,
                "uncompensated_cg_x_m": 0.801026,
                "required_forward_rebalance_m": 0.091302,
                "forward_rebalance_mass_kg": 56.0,
            },
            "tail_trim_static_directional_margins_after_mass_stiffness_changes": {
                "worst_static_margin": 0.088378,
                "C_n_beta_min_row": 0.016153,
                "worst_delta_H_margin_to_limit_deg": 5.673498,
                "worst_delta_V_margin_to_limit_deg": 16.068122,
            },
        },
        "stiffness_rework_candidates": rows,
    }


def _selected_closure_payload() -> dict:
    return {
        "engineering_verdict": "ready_for_fem_apdl_loadcase_package",
        "basis": {
            "aeroelastic_effects": {
                "direct_spar_pair_rotation_max_abs_deg": 3.449294,
                "conservative_bounded_physical_projection_max_abs_deg": 2.070316,
                "elastic_twist_screening_bound_deg": 3.0,
            },
            "trim_static_directional": {
                "status": "pass",
                "static_margin": 0.094301,
                "C_n_beta": 0.01403,
                "delta_H_margin_to_limit_deg": 4.792985,
                "delta_V_margin_to_limit_deg": 16.716831,
            },
            "cg_management": {
                "status": "managed_final_cg_pass",
                "final_cg_x_m": 0.75,
                "uncompensated_cg_x_m": 0.793296,
                "required_forward_rebalance_m": 0.079276,
                "forward_rebalance_mass_kg": 56.0,
            },
            "selected_stiffness_basis": {
                "rib_family": "eps_balsa_cap_hybrid_10mm",
                "rear_spar_participation": "bounded_65pct_screening",
                "structural_kernel_stiffness_override": {
                    "status": "applied_screening_surrogate",
                    "applied_global_torsion_cell_scale": 2.032971,
                },
            },
        },
    }


def test_design_variable_contract_includes_required_ranges_and_rear_bounds() -> None:
    module = _load_script_module()

    contract = module.build_design_variable_contract()

    assert 0.003 in contract["rib_core_thickness_m"]
    assert 0.010 in contract["rib_core_thickness_m"]
    assert min(contract["rib_core_thickness_m"]) < 0.003
    assert max(contract["rib_core_thickness_m"]) > 0.010
    assert contract["rear_spar_participation_values"] == [0.50, 0.65, 0.75]
    assert 1.0 not in contract["rear_spar_participation_values"]
    assert {
        "balsa",
        "eps_xps_foam_core_shape_only",
        "structural_foam_shape_core_reference",
        "hybrid_foam_balsa_cap",
        "hybrid_foam_glass_carbon_face",
    } <= set(contract["material_family_groups"])
    assert contract["local_reinforcement_options"]["torque_critical_y_m"] == pytest.approx(
        2.327757,
        rel=1.0e-4,
    )


def test_search_shortlist_clears_bounded_twist_and_keeps_foam_only_out_of_structural_pass() -> None:
    module = _load_script_module()

    summary = module.build_rib_torsion_design_search(
        sensitivity_payload=_sensitivity_payload(),
        selected_closure_payload=_selected_closure_payload(),
    )

    assert summary["engineering_verdict"] == "fast_design_loop_ready_for_fem_calibration"
    assert summary["selected_fast_candidate"]["fast_model_bounded_twist_deg"] < 3.0
    assert summary["selected_fast_candidate"]["rear_spar_participation"] != "bounded_100pct_screening"
    assert summary["selected_fast_candidate"]["evidence_status"] == (
        "fast_model_result_needs_FEM_calibration"
    )
    assert {
        "mass_kg",
        "cg_x_m",
        "required_forward_rebalance_m",
        "tail_delta_H_margin_deg",
        "static_margin",
        "C_n_beta",
        "manufacturability_score",
    } <= set(summary["selected_fast_candidate"]["trade_metrics"])

    foam_only_rows = [
        row
        for row in summary["candidate_rows"]
        if row["material_family_group"] == "eps_xps_foam_core_shape_only"
    ]
    assert foam_only_rows
    assert all(row["selection_status"] != "selected" for row in foam_only_rows)
    assert all("foam_only_shape_core_not_structural_bracing" in row["blockers"] for row in foam_only_rows)
    assert any(row["fast_model_bounded_twist_deg"] < 3.0 for row in summary["shortlist"])


def test_calibration_samples_and_feedback_interface_are_written(tmp_path: Path) -> None:
    module = _load_script_module()

    paths = module.write_rib_torsion_design_search_package(
        sensitivity_payload=_sensitivity_payload(),
        selected_closure_payload=_selected_closure_payload(),
        output_dir=tmp_path,
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))

    roles = {sample["sample_role"] for sample in summary["fem_calibration_samples"]}
    assert {
        "baseline_balsa_3mm",
        "selected_hybrid_10mm",
        "aggressive_plausible_hybrid",
        "lightweight_foam_core_reference",
    } <= roles
    assert summary["calibration_interface"]["result_schema"]["fem_twist_deg"]["required"] is True
    assert summary["calibration_interface"]["update_policy"]["next_loop_action"] == (
        "apply_family_and_zone_correction_factors_then_rerun_fast_search"
    )

    assert paths["candidate_csv"].exists()
    assert paths["shortlist_csv"].exists()
    assert paths["fem_sample_csv"].exists()
    assert paths["calibration_input_template_csv"].exists()
    assert paths["selected_closure_basis_json"].exists()
    assert paths["calculix_manifest_json"].exists()
    assert paths["apdl_manifest_json"].exists()
    assert any(path.name.endswith(".inp") for path in paths["calculix_decks"])
    assert any(path.name.endswith(".mac") for path in paths["apdl_decks"])
    first_deck = paths["calculix_decks"][0].read_text(encoding="utf-8")
    assert "FAST MODEL CALIBRATION SKELETON" in first_deck
    assert "foam-only rows are calibration references, not structural pass basis" in first_deck
    closure_basis = json.loads(paths["selected_closure_basis_json"].read_text(encoding="utf-8"))
    assert closure_basis["selected_basis"]["rear_spar_participation"] in {
        "bounded_50pct_screening",
        "bounded_65pct_screening",
        "bounded_75pct_screening",
    }
    assert closure_basis["selected_basis"]["structural_kernel_stiffness_override"][
        "status"
    ] == "screening_surrogate_ready_for_closure_rerun"


def test_calibration_results_generate_surrogate_correction_without_final_truth_claim() -> None:
    module = _load_script_module()
    summary = module.build_rib_torsion_design_search(
        sensitivity_payload=_sensitivity_payload(),
        selected_closure_payload=_selected_closure_payload(),
    )
    sample_map = {sample["sample_role"]: sample for sample in summary["fem_calibration_samples"]}

    update = module.derive_fast_model_calibration_update(
        summary,
        calibration_results=[
            {
                "sample_id": sample_map["baseline_balsa_3mm"]["sample_id"],
                "solver": "calculix",
                "fem_twist_deg": 3.60,
                "fem_mass_kg": 3.10,
                "status": "completed",
            },
            {
                "sample_id": sample_map["selected_hybrid_10mm"]["sample_id"],
                "solver": "apdl",
                "fem_twist_deg": 2.45,
                "fem_mass_kg": 5.50,
                "status": "completed",
            },
        ],
    )

    assert update["status"] == "calibration_update_ready_for_fast_loop"
    assert update["claim_boundary"] == "calibration_correction_for_search_only_not_final_FEM_truth"
    assert update["family_correction_factors"]["eps_balsa_cap_hybrid_10mm"]["twist_factor"] > 1.0
    assert update["next_loop_action"] == "rerun_fast_search_with_calibrated_twist_factors"
