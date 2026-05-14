from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006u_bl_core_envelope_topology.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006u_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classifies_non_wall_edge_that_opens_to_wing_wall() -> None:
    module = _load_module()

    classification = module.classify_candidate_edge_gap(
        candidate_markers=["wake_cut"],
        all_boundary_markers=["wake_cut", "wing_wall"],
    )

    assert classification == "candidate_open_edge_touches_wing_wall"


def test_summarizes_candidate_surface_bad_edges_by_marker_and_wall_contact() -> None:
    module = _load_module()
    faces = [
        module.SimpleFace((0, 1, 2, 3), "wing_wall"),
        module.SimpleFace((10, 11, 12, 13), "wing_wall"),
        module.SimpleFace((0, 4, 5, 1), "wake_cut"),
        module.SimpleFace((4, 6, 7, 5), "wake_cut"),
        module.SimpleFace((6, 8, 9, 7), "span_cap"),
        module.SimpleFace((10, 14, 15, 11), "wake_cut"),
    ]

    summary = module.summarize_candidate_surface_topology(
        candidate_faces=[face for face in faces if face.marker != "wing_wall"],
        all_boundary_faces=faces,
    )

    assert summary["status"] == "not_watertight"
    assert summary["bad_edge_count"] > 0
    assert summary["bad_edge_class_counts"]["candidate_open_edge_touches_wing_wall"] == 2
    assert summary["bad_edge_marker_combo_counts"]["wake_cut"] >= 2


def test_envelope_summary_rejects_full_non_wall_when_bad_edges_remain() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        {
            "candidate_id": "full_non_wall_boundary",
            "status": "not_watertight",
            "bad_edge_count": 124,
            "bad_edge_class_counts": {
                "candidate_open_edge_touches_wing_wall": 124,
            },
        }
    )

    assert summary["verdict"] == "bl_core_envelope_topology_blocked"
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
