from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.test_wo006r10_near_wall_core_closure_probe import _sharp_te_block


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r13_loop_cap_geometric_seam_repair.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r13_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _core_mesh_report() -> dict:
    return {
        "status": "meshed",
        "route": "mesh_native_inner_surface_core_tet_probe",
        "mesh_path": "/tmp/repaired_loop_cap_core_probe.msh",
        "su2_path": "/tmp/repaired_loop_cap_core_probe.su2",
        "node_count": 29993,
        "volume_element_count": 9691,
        "volume_element_type_counts": {"4": 9691},
        "inner_boundary": {
            "marker_counts": {
                "bl_outer_interface": 12,
                "wake_edge_receiver": 4,
                "core_wall_loop_cap": 2,
            },
        },
        "farfield": {"marker_counts": {"farfield": 6}},
        "interface_conformality": {
            "status": "preserved",
            "can_merge_with_owned_bl_block": True,
            "expected_boundary_representation": "triangulated",
            "remeshed_markers": [],
        },
        "quality_metrics": {
            "tetra_element_count": 9691,
            "pyramid_element_count": 0,
            "non_positive_min_sicn_count": 0,
            "non_positive_min_sige_count": 0,
            "non_positive_volume_count": 0,
            "min_sicn": 1.0e-5,
            "min_sige": 1.0e-5,
            "min_volume": 1.0e-6,
        },
        "mesh_quality_gate": {
            "status": "pass",
            "blockers": [],
            "warnings": ["very_low_min_sicn"],
        },
        "su2_boundary_ownership": {"status": "pass", "markers": {}},
        "physical_groups": {
            "bl_outer_interface": {"dimension": 2, "entity_count": 12},
            "wake_edge_receiver": {"dimension": 2, "entity_count": 4},
            "core_wall_loop_cap": {"dimension": 2, "entity_count": 2},
            "farfield": {"dimension": 2, "entity_count": 6},
            "fluid_core": {"dimension": 3, "entity_count": 1},
        },
    }


def test_repair_welds_duplicate_coordinates_and_drops_duplicate_seam_faces() -> None:
    module = _load_module()
    block = _sharp_te_block(layer_count=2)
    candidate = module.build_near_wall_merged_volume_candidate(block)
    cap_surface = module.build_loop_cap_surface(block, candidate)

    repaired, report = module.repair_loop_cap_geometric_seams(cap_surface)

    assert report["status"] == "pass"
    assert report["pre_repair_audit"]["exact_duplicate_group_count"] > 0
    assert report["pre_repair_audit"]["welded_topology"]["bad_edge_count"] > 0
    assert report["dropped_duplicate_face_count"] > 0
    assert report["post_repair_audit"]["exact_duplicate_group_count"] == 0
    assert report["post_repair_audit"]["welded_topology"]["bad_edge_count"] == 0
    assert repaired.marker_counts()["core_wall_loop_cap"] < cap_surface.marker_counts()[
        "core_wall_loop_cap"
    ]


def test_repaired_loop_cap_core_mesh_probe_keeps_cfd_incomplete(
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

    summary = module.run_repaired_loop_cap_core_mesh_probe(
        block=block,
        candidate=candidate,
        output_dir=tmp_path / "wo006r13",
        mesh_size=1.0,
        farfield_mesh_size=8.0,
    )

    assert calls
    assert calls[0]["kwargs"]["preserved_boundary_representation"] == "triangulated"
    assert summary["verdict"] == "loop_cap_geometric_seam_repair_core_mesh_pass_not_handoff"
    assert summary["loop_cap_core_mesh"]["status"] == "core_mesh_probe_pass_merged_handoff_pending"
    assert summary["loop_cap_core_mesh"]["core_mesh_quality_status"] == "pass"
    assert summary["loop_cap_core_mesh"]["core_mesh_marker_status"] == "pass"
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["coefficient_interpretable"] is False
    assert "merged_mixed_bl_core_su2_mesh_missing" in summary["loop_cap_core_mesh"]["blockers"]
