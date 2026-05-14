from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r20_left_tip_star_tessellation.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r20_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cell_center_star_tessellation_matches_incompatible_boundary_faces() -> None:
    module = _load_module()
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        (1.0, 1.0, 1.0),
        (0.0, 1.0, 1.0),
    ]
    candidate_cells = [
        {"cell_index": 10, "source": "tip_receiver", "role": "left_tip", "nodes": list(range(8))}
    ]
    target_rows = [
        {"cell_index": 10, "marker": "core_tip_receiver_outer", "triangle_nodes": [4, 5, 6]},
        {"cell_index": 10, "marker": "core_tip_receiver_outer", "triangle_nodes": [4, 6, 7]},
        {"cell_index": 10, "marker": "wake_edge_receiver", "triangle_nodes": [1, 5, 6]},
        {"cell_index": 10, "marker": "wake_edge_receiver", "triangle_nodes": [1, 6, 2]},
        {"cell_index": 10, "marker": "core_outer_edge_receiver", "triangle_nodes": [2, 6, 7]},
        {"cell_index": 10, "marker": "core_outer_edge_receiver", "triangle_nodes": [2, 7, 3]},
    ]

    audit = module.audit_left_tip_star_tessellation(
        vertices=vertices,
        candidate_cells=candidate_cells,
        target_triangle_rows=target_rows,
    )

    assert audit["status"] == "left_tip_star_tessellation_match"
    assert audit["target_cell_count"] == 1
    assert audit["target_triangle_count"] == 6
    assert audit["matched_target_triangle_count"] == 6
    assert audit["non_positive_star_tet_count"] == 0


def test_target_rows_can_be_limited_to_incompatible_left_tip_cells() -> None:
    module = _load_module()
    candidate_vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        (1.0, 1.0, 1.0),
        (0.0, 1.0, 1.0),
        (2.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (2.0, 0.0, 1.0),
        (2.0, 1.0, 1.0),
    ]
    candidate_cells = [
        {"cell_index": 10, "source": "tip_receiver", "role": "left_tip", "nodes": list(range(8))},
        {
            "cell_index": 11,
            "source": "tip_receiver",
            "role": "left_tip",
            "nodes": [1, 8, 9, 2, 5, 10, 11, 6],
        },
    ]
    candidate_boundary_faces = [
        {"nodes": [4, 5, 6, 7]},
        {"nodes": [5, 10, 11, 6]},
    ]
    core_triangle_rows = [
        {"marker": "core_tip_receiver_outer", "triangle_nodes": [4, 5, 6]},
        {"marker": "core_tip_receiver_outer", "triangle_nodes": [4, 6, 7]},
        {"marker": "core_tip_receiver_outer", "triangle_nodes": [5, 10, 11]},
        {"marker": "core_tip_receiver_outer", "triangle_nodes": [5, 11, 6]},
    ]

    rows = module.left_tip_star_target_triangle_rows(
        candidate_vertices=candidate_vertices,
        candidate_cells=candidate_cells,
        candidate_boundary_faces=candidate_boundary_faces,
        core_vertices=candidate_vertices,
        core_triangle_rows=core_triangle_rows,
        target_cell_indices={10},
    )

    assert {row["cell_index"] for row in rows} == {10}
    assert len(rows) == 2


def test_r20_summary_keeps_cfd_incomplete_until_mixed_mesh_and_yplus_exist() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        audit={
            "status": "left_tip_star_tessellation_match",
            "target_cell_count": 2,
            "target_triangle_count": 12,
            "matched_target_triangle_count": 12,
            "remaining_r17_residuals_after_r19_r20": {},
        },
        output_dir=Path("/tmp/wo006r20"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["verdict"] == "left_tip_star_tessellation_match_mixed_mesh_still_missing"
    assert "merged BL+core SU2 handoff" in summary["blocked_claims"]
