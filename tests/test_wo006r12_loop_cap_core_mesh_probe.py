from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.test_wo006r10_near_wall_core_closure_probe import _sharp_te_block


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r12_loop_cap_core_mesh_probe.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r12_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _core_mesh_report(*, status: str = "meshed") -> dict:
    quality_pass = status == "meshed"
    return {
        "status": status,
        "route": "mesh_native_inner_surface_core_tet_probe",
        "mesh_path": "/tmp/loop_cap_core_probe.msh",
        "su2_path": "/tmp/loop_cap_core_probe.su2",
        "node_count": 1234,
        "volume_element_count": 4567,
        "volume_element_type_counts": {"4": 4567},
        "inner_boundary": {
            "marker_counts": {
                "bl_outer_interface": 12,
                "core_wall_loop_cap": 2,
            },
            "input_mesh_element_counts": {},
            "generated_mesh_element_counts": {},
        },
        "farfield": {"marker_counts": {"farfield": 6}},
        "interface_conformality": {
            "status": "preserved",
            "can_merge_with_owned_bl_block": True,
            "expected_boundary_representation": "triangulated",
            "remeshed_markers": [],
        },
        "quality_metrics": {
            "tetra_element_count": 4567,
            "pyramid_element_count": 0,
            "non_positive_min_sicn_count": 0 if quality_pass else 1,
            "non_positive_min_sige_count": 0 if quality_pass else 1,
            "non_positive_volume_count": 0 if quality_pass else 1,
            "min_sicn": 0.02 if quality_pass else -0.1,
            "min_sige": 0.02 if quality_pass else -0.1,
            "min_volume": 1.0e-6 if quality_pass else -1.0e-6,
        },
        "mesh_quality_gate": {
            "status": "pass" if quality_pass else "fail",
            "blockers": [] if quality_pass else ["non_positive_volume"],
        },
        "su2_boundary_ownership": {"status": "pass", "markers": {}},
        "physical_groups": {
            "bl_outer_interface": {"dimension": 2, "entity_count": 12},
            "core_wall_loop_cap": {"dimension": 2, "entity_count": 2},
            "farfield": {"dimension": 2, "entity_count": 6},
            "fluid_core": {"dimension": 3, "entity_count": 1},
        },
    }


def test_loop_cap_core_mesh_probe_uses_r11_surface_markers_without_cfd_promotion(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    block = _sharp_te_block(layer_count=2)
    candidate = module.build_near_wall_merged_volume_candidate(block)
    calls = []

    def fake_writer(inner_boundary, farfield, out_path, **kwargs):
        calls.append(
            {
                "inner_marker_counts": inner_boundary.marker_counts(),
                "farfield_marker_counts": farfield.marker_counts(),
                "out_path": Path(out_path),
                "kwargs": kwargs,
            }
        )
        return _core_mesh_report()

    monkeypatch.setattr(module, "write_core_tet_mesh_from_inner_surface", fake_writer)
    monkeypatch.setattr(
        module,
        "audit_inner_surface_geometry",
        lambda _surface: {
            "exact_duplicate_group_count": 0,
            "exact_duplicate_vertex_count": 0,
            "welded_topology": {"bad_edge_count": 0},
        },
    )

    summary = module.run_loop_cap_core_mesh_probe(
        block=block,
        candidate=candidate,
        output_dir=tmp_path / "wo006r12",
        mesh_size=1.0,
        farfield_mesh_size=8.0,
    )

    assert calls
    assert calls[0]["inner_marker_counts"]["core_wall_loop_cap"] > 0
    assert calls[0]["kwargs"]["preserve_boundary_mesh"] is True
    assert calls[0]["kwargs"]["preserved_boundary_representation"] == "triangulated"
    assert calls[0]["kwargs"]["mesh_algorithm3d"] == 10
    assert calls[0]["farfield_marker_counts"] == {"farfield": 6}
    assert summary["loop_cap_core_mesh"]["status"] == "core_mesh_probe_pass_merged_handoff_pending"
    assert summary["loop_cap_core_mesh"]["core_mesh_quality_status"] == "pass"
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["coefficient_interpretable"] is False
    assert "merged_mixed_bl_core_su2_mesh_missing" in summary["loop_cap_core_mesh"]["blockers"]
    assert (tmp_path / "wo006r12" / "loop_cap_core_mesh_probe_summary.json").exists()


def test_loop_cap_core_mesh_probe_blocks_failed_core_quality() -> None:
    module = _load_module()

    summary = module.summarize_loop_cap_core_mesh_probe(
        loop_closure={"status": "core_facing_loop_cap_surface_ready_core_mesh_pending"},
        core_report=_core_mesh_report(status="failed"),
    )

    assert summary["status"] == "core_mesh_probe_blocked"
    assert "core_probe_not_meshed" in summary["blockers"]
    assert "core_mesh_quality_not_pass" in summary["blockers"]
    assert summary["coefficient_interpretable"] is False
