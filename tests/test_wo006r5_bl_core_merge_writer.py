from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006r5_bl_core_merge_writer.py"


def _load_campaign_module():
    spec = importlib.util.spec_from_file_location("wo006r5_campaign", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_wo006r5_report_only_run_writes_limitation_artifacts_without_handoff(
    tmp_path: Path,
):
    campaign = _load_campaign_module()

    result = campaign.run_campaign(
        output_dir=tmp_path / "wo006r5",
        clean=True,
        run_core_probe=False,
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    assert result["verdict"] == "wo006r5_core_merge_limitation_proven"
    assert result["bl_mesh_handoff_written"] is False
    assert result["bl_core_handoff_exists"] is False
    assert result["coefficient_interpretable"] is False
    assert result["authority_basis"]["design_gross_mass_kg"] == 98.5
    assert result["authority_basis"]["pipeline_full_span_m"] == 34.332286
    assert result["authority_basis"]["pipeline_half_span_m"] == 17.166143
    assert result["external_shape_changed"] is False
    assert result["merge_gate"]["can_write_bl_mesh_handoff"] is False
    assert "merged_mixed_su2_mesh_missing" in result["merge_gate"]["blockers"]
    assert "final_merged_marker_ownership_not_proven" in result["marker_ownership_audit"][
        "blockers"
    ]
    assert "merged_bl_core_su2_mesh_missing" in result["su2_readability_smoke"]["blockers"]

    for name in (
        "bl_core_merge_report.md",
        "bl_core_merge_gate.json",
        "blocker_register.csv",
        "full_non_wall_boundary_surface_probe.json",
        "geometry_deviation_report.md",
        "interface_conformality_audit.csv",
        "marker_ownership_audit.json",
        "merge_limitation_evidence.json",
        "mesh_quality_gate.json",
        "next_goal.md",
        "owned_bl_block_writer_probe.json",
        "owned_bl_block_probe.su2",
        "route_decision.json",
        "su2_readability_smoke.json",
    ):
        assert (tmp_path / "wo006r5" / name).exists()
    assert not (tmp_path / "wo006r5" / "bl_mesh_handoff.v1.json").exists()


def test_wo006r5_core_probe_uses_non_final_probe_su2_name(
    tmp_path: Path,
    monkeypatch,
):
    campaign = _load_campaign_module()
    seen_paths: dict[str, Path] = {}

    def fake_core_writer(_block, _farfield, out_path, *, su2_path, **_kwargs):
        seen_paths["msh"] = Path(out_path)
        seen_paths["su2"] = Path(su2_path)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("$MeshFormat\n", encoding="utf-8")
        Path(su2_path).write_text("NDIME= 3\nNELEM= 0\nNPOIN= 0\nNMARK= 0\n", encoding="utf-8")
        return {
            "status": "meshed",
            "route": "fake_core_probe",
            "mesh_path": str(out_path),
            "su2_path": str(su2_path),
            "volume_element_count": 1,
            "mesh_quality_gate": {"status": "pass", "blockers": []},
            "interface_conformality": {
                "status": "preserved",
                "can_merge_with_owned_bl_block": True,
                "remeshed_markers": [],
            },
            "bl_block_coupling": {
                "status": "partial",
                "can_merge_core_with_bl_block": False,
                "unmatched_core_interface_face_count": 1,
                "unmatched_bl_boundary_face_count": 1,
            },
        }

    monkeypatch.setattr(campaign, "write_boundary_layer_block_core_tet_mesh", fake_core_writer)

    result = campaign.run_campaign(
        output_dir=tmp_path / "wo006r5",
        clean=True,
        run_core_probe=True,
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    assert seen_paths["su2"].name == "core_preserved_interface_probe.su2"
    assert seen_paths["su2"].name != "core.su2"
    assert "core_probe_artifacts/core.su2" not in str(seen_paths["su2"])
    assert result["bl_mesh_handoff_written"] is False
    assert "owned_bl_core_coupling_incomplete" in result["merge_gate"]["blockers"]


def test_full_non_wall_boundary_probe_records_non_watertight_limitation():
    campaign = _load_campaign_module()
    geometry = campaign.load_campaign_geometry(points_per_side=8, spanwise_subdivisions=1)
    block = campaign.build_wing_boundary_layer_block(
        geometry.spec.wing_spec,
        campaign.BoundaryLayerBlockSpec(
            first_layer_height_m=campaign.BL_FIRST_HEIGHT_M,
            growth_ratio=campaign.BL_GROWTH_RATIO,
            layer_count=campaign.BL_LAYERS,
        ),
    )

    probe = campaign.probe_full_non_wall_boundary_surface(block)

    assert probe["status"] == "not_watertight"
    assert probe["can_use_as_core_inner_boundary"] is False
    assert "Non-watertight surface" in probe["error"]
