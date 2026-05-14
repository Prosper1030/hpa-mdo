from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r19_loop_cap_owner_pyramid.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r19_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_loop_cap_owner_pyramids_match_unowned_cap_triangles() -> None:
    module = _load_module()
    candidate_vertices = [
        (0.0, -1.0, 0.0),
        (1.0, -1.0, 0.0),
        (2.0, -1.0, 0.0),
        (3.0, -1.0, 0.0),
        (0.0, -2.0, 0.0),
        (1.0, -2.0, 0.0),
        (2.0, -2.0, 0.0),
        (3.0, -2.0, 0.0),
    ]
    core_vertices = [
        *candidate_vertices,
        (1.5, -2.0, 1.0),
    ]
    physical_wall_edge_rows = [
        {"role": "physical_wall_edge_receiver", "nodes": [0, 1, 5, 4]},
        {"role": "physical_wall_edge_receiver", "nodes": [1, 2, 6, 5]},
        {"role": "physical_wall_edge_receiver", "nodes": [2, 3, 7, 6]},
    ]
    core_triangle_rows = [
        {
            "marker": "core_wall_loop_cap",
            "triangle_nodes": [8, 5, 4],
            "candidate_owned": False,
            "matched_by_best_hybrid_split": False,
        },
        {
            "marker": "core_wall_loop_cap",
            "triangle_nodes": [8, 6, 5],
            "candidate_owned": False,
            "matched_by_best_hybrid_split": False,
        },
        {
            "marker": "core_wall_loop_cap",
            "triangle_nodes": [8, 7, 6],
            "candidate_owned": False,
            "matched_by_best_hybrid_split": False,
        },
    ]

    audit = module.audit_loop_cap_owner_pyramids(
        candidate_vertices=candidate_vertices,
        core_vertices=core_vertices,
        physical_wall_edge_rows=physical_wall_edge_rows,
        core_triangle_rows=core_triangle_rows,
    )

    assert audit["status"] == "loop_cap_owner_pyramids_match"
    assert audit["owner_pyramid_cell_count"] == 3
    assert audit["core_wall_loop_cap_triangle_count"] == 3
    assert audit["matched_core_wall_loop_cap_triangle_count"] == 3
    assert audit["unmatched_core_wall_loop_cap_triangle_count"] == 0
    assert audit["non_positive_owner_pyramid_volume_count"] == 0


def test_loop_cap_owner_summary_still_blocks_cfd_completion() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        audit={
            "status": "loop_cap_owner_pyramids_match",
            "matched_core_wall_loop_cap_triangle_count": 60,
            "core_wall_loop_cap_triangle_count": 60,
            "remaining_hybrid_residuals_by_marker": {
                "core_tip_receiver_outer": 4,
                "wake_edge_receiver": 4,
            },
        },
        output_dir=Path("/tmp/wo006r19"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["verdict"] == "loop_cap_owner_pyramids_match_tip_split_still_blocked"
    assert "postprocessed near-wall y+" in summary["blocked_claims"]
