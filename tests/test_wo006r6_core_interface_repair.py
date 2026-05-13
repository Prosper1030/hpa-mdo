from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006r6_core_interface_repair.py"


def _load_campaign_module():
    spec = importlib.util.spec_from_file_location("wo006r6_campaign", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_core_report(*, quality_status: str, coupling_status: str) -> dict:
    quality_blockers = [] if quality_status == "pass" else ["non_positive_volume"]
    coupling_complete = coupling_status == "complete"
    return {
        "status": "meshed",
        "route": "fake_preserved_core_probe",
        "mesh_path": "/tmp/core_preserved_interface_probe.msh",
        "su2_path": "/tmp/core_preserved_interface_probe.su2",
        "volume_element_count": 12,
        "volume_element_type_counts": {"4": 8, "7": 4},
        "mesh_quality_gate": {"status": quality_status, "blockers": quality_blockers},
        "quality_metrics": {
            "volume_element_count": 12,
            "non_positive_volume_count": 0 if quality_status == "pass" else 2,
            "non_positive_min_sicn_count": 0 if quality_status == "pass" else 2,
            "non_positive_min_sige_count": 0 if quality_status == "pass" else 2,
        },
        "interface_conformality": {
            "status": "preserved",
            "can_merge_with_owned_bl_block": True,
            "expected_boundary_representation": "native",
            "missing_markers": [],
            "extra_markers": [],
            "remeshed_markers": [],
            "markers": {
                "bl_outer_interface": {
                    "input_expected_element_count": 1,
                    "generated_element_count": 1,
                    "preserved": True,
                },
                "wake_cut": {
                    "input_expected_element_count": 1,
                    "generated_element_count": 1,
                    "preserved": True,
                },
                "span_cap": {
                    "input_expected_element_count": 1,
                    "generated_element_count": 1,
                    "preserved": True,
                },
            },
        },
        "bl_block_coupling": {
            "status": coupling_status,
            "can_merge_core_with_bl_block": coupling_complete,
            "matched_face_count": 1,
            "matched_face_counts_by_marker_pair": {"bl_outer_interface->bl_outer_interface": 1},
            "unmatched_core_interface_face_count": 0 if coupling_complete else 2,
            "unmatched_core_interface_face_counts_by_marker": {}
            if coupling_complete
            else {"wake_cut": 1, "span_cap": 1},
            "unmatched_bl_boundary_face_count": 0 if coupling_complete else 4,
            "unmatched_bl_boundary_face_counts_by_marker": {}
            if coupling_complete
            else {"wake_cut": 2, "span_cap": 2},
        },
        "physical_groups": {"farfield": {"dimension": 2, "entity_count": 1}},
    }


def test_wo006r6_core_quality_limitation_writes_required_artifacts_without_handoff(
    tmp_path: Path,
    monkeypatch,
):
    campaign = _load_campaign_module()

    monkeypatch.setattr(
        campaign,
        "_run_preserved_interface_core_probe",
        lambda *_args, **_kwargs: _fake_core_report(
            quality_status="fail",
            coupling_status="partial",
        ),
    )

    result = campaign.run_campaign(
        output_dir=tmp_path / "wo006r6",
        clean=True,
        run_core_probe=True,
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    assert result["verdict"] == "wo006r6_core_quality_limitation_proven"
    assert result["external_shape_changed"] is False
    assert result["coefficient_interpretable"] is False
    assert result["bl_mesh_handoff_written"] is False
    assert result["authority_basis"]["design_gross_mass_kg"] == 98.5
    assert result["authority_basis"]["pipeline_full_span_m"] == 34.332286
    assert result["authority_basis"]["pipeline_half_span_m"] == 17.166143
    assert "core_mesh_quality_gate_not_pass" in result["blockers"]

    for name in (
        "core_interface_repair_report.md",
        "route_decision.json",
        "interface_conformality_audit.csv",
        "mesh_quality_gate.json",
        "marker_ownership_audit.json",
        "su2_readability_smoke.json",
        "blocker_register.csv",
        "next_goal.md",
    ):
        assert (tmp_path / "wo006r6" / name).exists()
    assert not (tmp_path / "wo006r6" / "bl_mesh_handoff.v1.json").exists()


def test_wo006r6_quality_pass_but_unmatched_faces_is_topology_limitation(
    tmp_path: Path,
    monkeypatch,
):
    campaign = _load_campaign_module()

    monkeypatch.setattr(
        campaign,
        "_run_preserved_interface_core_probe",
        lambda *_args, **_kwargs: _fake_core_report(
            quality_status="pass",
            coupling_status="partial",
        ),
    )

    result = campaign.run_campaign(
        output_dir=tmp_path / "wo006r6",
        clean=True,
        run_core_probe=True,
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    assert result["verdict"] == "wo006r6_interface_topology_limitation_proven"
    assert result["bl_mesh_handoff_written"] is False
    assert "owned_bl_core_coupling_incomplete" in result["blockers"]
    assert result["interface_topology_audit"]["zero_unmatched_interface_faces"] is False


def _valid_minimal_su2(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "NDIME= 3",
                "NELEM= 1",
                "12 0 1 2 3 4 5 6 7 0",
                "NPOIN= 8",
                "0 0 0 0",
                "1 0 0 1",
                "1 1 0 2",
                "0 1 0 3",
                "0 0 1 4",
                "1 0 1 5",
                "1 1 1 6",
                "0 1 1 7",
                "NMARK= 2",
                "MARKER_TAG= wing_wall",
                "MARKER_ELEMS= 1",
                "9 0 1 2 3",
                "MARKER_TAG= farfield",
                "MARKER_ELEMS= 1",
                "9 4 5 6 7",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _passing_final_candidate(path: Path) -> dict:
    _valid_minimal_su2(path)
    return {
        "artifact_role": "final_merged_bl_core_su2",
        "core_status": "meshed",
        "su2_path": str(path),
        "bl_block_coupling": {
            "status": "complete",
            "can_merge_core_with_bl_block": True,
            "unmatched_core_interface_face_count": 0,
            "unmatched_bl_boundary_face_count": 0,
        },
        "marker_ownership_audit": {
            "status": "pass",
            "blockers": [],
            "final_mesh_boundary_markers": {
                "wing_wall": {"element_count": 1},
                "farfield": {"element_count": 1},
            },
        },
        "mesh_quality_gate": {
            "status": "pass",
            "blockers": [],
            "quality_metrics": {
                "non_positive_min_sicn_count": 0,
                "non_positive_min_sige_count": 0,
                "non_positive_volume_count": 0,
            },
        },
    }


def test_wo006r6_final_handoff_gate_requires_all_final_mesh_conditions(tmp_path: Path):
    campaign = _load_campaign_module()
    candidate = _passing_final_candidate(tmp_path / "merged_bl_core.su2")

    gate = campaign.evaluate_r6_final_handoff_gate(candidate)

    assert gate["status"] == "pass"
    assert gate["can_write_bl_mesh_handoff"] is True
    assert gate["blockers"] == []

    cases = {
        "unmatched_core_interface_faces": {
            "bl_block_coupling": {"unmatched_core_interface_face_count": 1}
        },
        "unmatched_bl_boundary_faces": {
            "bl_block_coupling": {"unmatched_bl_boundary_face_count": 1}
        },
        "marker_ownership_not_pass": {
            "marker_ownership_audit": {"status": "fail", "blockers": ["missing_farfield"]}
        },
        "non_positive_elements_present": {
            "mesh_quality_gate": {
                "quality_metrics": {"non_positive_volume_count": 1}
            }
        },
        "final_su2_readability_not_pass": {
            "su2_path": str(tmp_path / "missing_final.su2"),
        },
    }
    for expected_blocker, patch in cases.items():
        rejected = campaign.evaluate_r6_final_handoff_gate(
            campaign.deep_merge_dict(candidate, patch)
        )
        assert rejected["status"] == "blocked"
        assert rejected["can_write_bl_mesh_handoff"] is False
        assert expected_blocker in rejected["blockers"]

    probe_path = tmp_path / "core_preserved_interface_probe.su2"
    _valid_minimal_su2(probe_path)
    rejected_probe = campaign.evaluate_r6_final_handoff_gate(
        campaign.deep_merge_dict(
            candidate,
            {"artifact_role": "probe_su2", "su2_path": str(probe_path)},
        )
    )
    assert rejected_probe["status"] == "blocked"
    assert rejected_probe["can_write_bl_mesh_handoff"] is False
    assert "probe_su2_not_final" in rejected_probe["blockers"]
