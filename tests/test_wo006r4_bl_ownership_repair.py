from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006r4_bl_ownership_repair.py"


def _load_campaign_module():
    spec = importlib.util.spec_from_file_location("wo006r4_campaign", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_owned_bl_block_builds_positive_current_go_nearwall_topology():
    campaign = _load_campaign_module()
    geometry = campaign.load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
    block = campaign.build_wing_boundary_layer_block(
        geometry.spec.wing_spec,
        campaign.BoundaryLayerBlockSpec(
            first_layer_height_m=campaign.BL_FIRST_HEIGHT_M,
            growth_ratio=campaign.BL_GROWTH_RATIO,
            layer_count=campaign.BL_LAYERS,
        ),
    )
    core_interface = campaign.build_boundary_layer_core_interface_surface(block)

    summary = campaign.build_owned_bl_block_summary(block, core_interface)

    assert summary["block_cells"] == 49152
    assert summary["marker_counts"]["boundary_layer"] == 47616
    assert summary["marker_counts"]["trailing_edge_connector"] == 1536
    assert summary["quality"]["non_positive_volume_count"] == 0
    assert summary["quality"]["unowned_boundary_face_count"] == 0
    assert summary["boundary_layer"]["first_height_m"] == 5.0e-5
    assert summary["boundary_layer"]["layers"] == 24
    assert summary["core_interface_marker_counts"] == {
        "bl_outer_interface": 2048,
        "span_cap": 126,
        "wake_cut": 32,
    }


def test_surface_geometry_deviation_reports_no_r4_shape_cleanup():
    campaign = _load_campaign_module()
    geometry = campaign.load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
    wing = campaign.build_current_go_wing_surface(geometry)
    block = campaign.build_wing_boundary_layer_block(
        geometry.spec.wing_spec,
        campaign.BoundaryLayerBlockSpec(
            first_layer_height_m=campaign.BL_FIRST_HEIGHT_M,
            growth_ratio=campaign.BL_GROWTH_RATIO,
            layer_count=campaign.BL_LAYERS,
        ),
    )

    report = campaign.build_surface_geometry_deviation(wing, block)

    assert report["external_authority_files_changed"] is False
    assert report["r4_new_adapter_cleanup_applied"] is False
    assert report["max_nearest_distance_m"] < 1.0e-12
    assert report["p95_nearest_distance_m"] < 1.0e-12


def test_core_probe_classifier_rejects_preserved_but_unmergeable_interface():
    campaign = _load_campaign_module()
    result = campaign.classify_core_probe_result(
        attempt_id="probe",
        role="unit fixture",
        elapsed_seconds=0.0,
        report={
            "volume_element_count": 10,
            "volume_element_type_counts": {"4": 8, "7": 2},
            "mesh_quality_gate": {"status": "pass", "blockers": []},
            "quality_metrics": {"non_positive_volume_count": 0},
            "interface_conformality": {
                "can_merge_with_owned_bl_block": True,
                "status": "preserved",
            },
            "bl_block_coupling": {
                "can_merge_core_with_bl_block": False,
                "unmatched_core_interface_face_counts_by_marker": {
                    "wake_cut": 1,
                    "span_cap": 2,
                },
            },
            "physical_groups": {},
            "caveats": [],
        },
    )

    assert result["status"] == "blocked"
    assert result["failure_mode"] == "owned_bl_core_coupling_partial_wake_span_cap_not_conformal"
    assert "wake/span-cap ownership" in result["rejected_for"]


def test_route_decision_proves_limitation_until_conformal_core_candidate():
    campaign = _load_campaign_module()
    geometry = campaign.load_campaign_geometry(points_per_side=8, spanwise_subdivisions=1)

    decision = campaign.build_route_decision(
        geometry=geometry,
        attempts=[
            {"attempt_id": "a", "status": "blocked"},
            {"attempt_id": "b", "status": "rejected_workaround"},
        ],
        block_summary={
            "block_cells": 1,
            "quality": {"non_positive_volume_count": 0},
            "boundary_layer": {"first_height_m": 5.0e-5, "layers": 24},
        },
        deviation_report={
            "external_authority_files_changed": False,
            "max_nearest_distance_m": 0.0,
        },
    )

    assert decision["verdict"] == "wo006r4_adapter_limitation_proven"
    assert decision["bl_mesh_handoff_written"] is False
    assert decision["coefficient_interpretable"] is False
    assert decision["authority_basis"]["design_gross_mass_kg"] == 98.5
    assert decision["authority_basis"]["pipeline_full_span_m"] == 34.332286
    assert "conformal owned BL block + core merge" in decision["limitation_proof"][
        "smallest_blocker"
    ]


def test_report_only_campaign_writes_required_artifacts_without_bl_handoff(tmp_path: Path):
    campaign = _load_campaign_module()

    decision = campaign.run_campaign(
        output_dir=tmp_path / "wo006r4",
        clean=True,
        run_core_probes=False,
    )

    assert decision["verdict"] == "wo006r4_adapter_limitation_proven"
    assert decision["bl_mesh_handoff_written"] is False
    for name in (
        "cfd_recovery_campaign_report.md",
        "old_evidence_map.md",
        "route_decision.json",
        "surface_geometry_deviation_report.md",
        "yplus_and_boundary_layer_basis.md",
        "solver_evidence_gate.json",
        "blocker_register.csv",
        "next_goal.md",
        "owned_bl_block_summary.json",
    ):
        assert (tmp_path / "wo006r4" / name).exists()
    assert not (tmp_path / "wo006r4" / "bl_mesh_handoff.v1.json").exists()
