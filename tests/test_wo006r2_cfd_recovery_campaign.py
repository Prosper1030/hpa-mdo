from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006r2_cfd_recovery_campaign.py"


def _load_campaign_module():
    spec = importlib.util.spec_from_file_location("wo006r2_campaign", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_campaign_geometry_reuses_current_go_authority_and_bl_defaults():
    campaign = _load_campaign_module()

    geometry = campaign.load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
    summary = campaign.build_yplus_nearwall_summary(geometry)

    assert geometry.full_span_m == 34.332286
    assert geometry.reference.sref_full == 33.420059598
    assert geometry.reference.cref == 1.003721543
    assert geometry.design_gross_mass_kg == 98.5
    assert summary["boundary_layer_policy"]["recommended_first_layer_height_m"] == 5.0e-5
    assert summary["boundary_layer_policy"]["recommended_layers"] == 24
    assert summary["boundary_layer_policy"]["recommended_growth_ratio"] == 1.24
    assert summary["current_go_reynolds_by_chord"]["mean_aerodynamic_chord"] > 4.0e5
    assert summary["current_go_first_layer_yplus_estimate"]["yplus_for_5e-5m"] > 0.0


def test_current_go_surface_passes_airfoil_loop_intersection_preflight():
    campaign = _load_campaign_module()
    from hpa_meshing.mesh_native.wing_surface import (
        preflight_wing_surface_airfoil_loop_intersections,
    )

    geometry = campaign.load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
    intersections = preflight_wing_surface_airfoil_loop_intersections(geometry.spec.wing_spec)

    assert intersections == []
    assert geometry.full_span_m == 34.332286
    assert geometry.reference.sref_full == 33.420059598
    assert geometry.reference.cref == 1.003721543


def test_route_decision_matrix_records_old_serious_bl_route_as_selected_adapter():
    campaign = _load_campaign_module()

    rows = campaign.build_route_decision_matrix_rows()
    by_route = {row["route_id"]: row for row in rows}

    assert by_route["old_mesh_native_wing_h_0p20_bl"]["decision"] == "reuse_as_primary_template"
    assert by_route["old_mesh_native_wing_h_0p20_bl"]["old_volume_elements"] == "1125409"
    assert by_route["old_mesh_native_wing_h_0p20_bl"]["bl_or_nearwall"] == "24_layer_prism_bl"
    assert by_route["wo006r1_current_go_coarse_no_bl"]["decision"] == "bridge_only_not_target"
    assert by_route["old_step_brep_esp_route"]["decision"] == "reject_as_primary"


def test_force_reference_audit_uses_current_full_wing_refs_and_blocks_legacy_truth():
    campaign = _load_campaign_module()
    geometry = campaign.load_campaign_geometry()

    audit = campaign.build_force_reference_audit(geometry)

    assert audit["current_authority"]["design_gross_mass_kg"] == 98.5
    assert audit["current_authority"]["sref_m2"] == 33.420059598
    assert audit["current_authority"]["cref_m"] == 1.003721543
    assert audit["current_authority"]["bref_m"] == 34.332286
    assert (
        audit["blocked_legacy_values"]["legacy_screening_mass_status"]
        == "blocked_not_current_truth"
    )
    assert (
        audit["blocked_legacy_values"]["legacy_local_splice_half_span_status"]
        == "blocked_not_current_truth"
    )
    assert audit["force_marker_contract"]["monitoring_marker"] == "wing_wall"
    assert audit["coefficient_acceptance"]["negative_cd_status"] == "reject"


def test_plc_intersection_context_maps_gmsh_points_to_current_go_sections():
    campaign = _load_campaign_module()
    log_tail = """
PLC Error: A segment and a facet intersect at point (0.821015,-12.7105,1.26614).
PLC Error: Two segments intersect at point (0.907069,10.4713,0.853959).
"""

    points = campaign.extract_plc_points(log_tail)
    context = campaign._plc_intersection_context(log_tail)

    assert points[0]["y_m"] == -12.7105
    assert context[0]["bracket_lower_section_index"] == 4
    assert context[0]["bracket_upper_section_index"] == 5
    assert context[0]["bracket_crosses_airfoil_family"] is True
    assert context[1]["bracket_lower_section_index"] == 3
    assert context[1]["bracket_upper_section_index"] == 4
    assert context[1]["bracket_crosses_airfoil_family"] is False


def test_final_verdict_prefers_geometry_adapter_when_bl_and_high_mesh_no_bl_fail():
    campaign = _load_campaign_module()

    verdict = campaign._final_verdict(
        [
            {
                "attempt_id": "attempt_00_avl_parity_coarse_bridge_control",
                "mesh_kind": "no_bl",
                "status": "completed",
                "mesh": {"volume_element_count": 3915},
                "solver": {"run_status": "not_run"},
            },
            {
                "attempt_id": "attempt_01_replay_old_mesh_native_bl_template",
                "mesh_kind": "bl",
                "status": "failed",
            },
            {
                "attempt_id": "attempt_03_current_go_high_mesh_no_bl_solver_control",
                "mesh_kind": "no_bl",
                "status": "failed",
            },
        ]
    )

    assert verdict == "wo006r2_current_geometry_adapter_blocker_isolated"


def test_short_blocker_evidence_summarizes_plc_section_context():
    campaign = _load_campaign_module()
    blocker = {
        "evidence": json.dumps(
            {
                "tail": "HXT 3D mesh failed",
                "plc_intersection_context": [
                    {
                        "x_m": 0.827965,
                        "y_m": -12.5391,
                        "z_m": 1.22456,
                        "bracket_lower_section_index": 4,
                        "bracket_upper_section_index": 5,
                        "bracket_lower_airfoil_id": "dae31",
                        "bracket_upper_airfoil_id": "cst_tip",
                        "bracket_crosses_airfoil_family": True,
                    }
                ],
            }
        )
    }

    summary = campaign._short_blocker_evidence(blocker)

    assert "PLC point" in summary
    assert "section bracket 4-5" in summary
    assert "dae31->cst_tip" in summary
