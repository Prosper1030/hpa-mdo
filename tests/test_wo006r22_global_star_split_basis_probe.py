from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r22_global_star_split_basis.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r22_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_global_star_split_is_conformal_for_adjacent_hexes() -> None:
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
        (2.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (2.0, 0.0, 1.0),
        (2.0, 1.0, 1.0),
    ]
    cells = [
        {"cell_index": 0, "nodes": [0, 1, 2, 3, 4, 5, 6, 7]},
        {"cell_index": 1, "nodes": [1, 8, 9, 2, 5, 10, 11, 6]},
    ]
    external_boundary_rows = [
        {"nodes": [0, 1, 2, 3], "role": "outer"},
        {"nodes": [4, 7, 6, 5], "role": "outer"},
        {"nodes": [0, 4, 5, 1], "role": "outer"},
        {"nodes": [2, 6, 7, 3], "role": "outer"},
        {"nodes": [3, 7, 4, 0], "role": "outer"},
        {"nodes": [1, 8, 9, 2], "role": "outer"},
        {"nodes": [5, 6, 11, 10], "role": "outer"},
        {"nodes": [1, 5, 10, 8], "role": "outer"},
        {"nodes": [8, 10, 11, 9], "role": "outer"},
        {"nodes": [9, 11, 6, 2], "role": "outer"},
    ]

    audit = module.audit_global_star_split_basis(
        vertices=vertices,
        candidate_cells=cells,
        external_boundary_rows=external_boundary_rows,
        target_triangle_rows=[],
    )

    assert audit["status"] == "global_star_split_basis_ready"
    assert audit["internal_split_leak_face_count"] == 0
    assert audit["nonmanifold_split_face_count"] == 0
    assert audit["volume_element_count"] == 24
    assert audit["non_positive_tet_count"] == 0


def test_global_star_split_uses_target_boundary_triangles() -> None:
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
    cells = [{"cell_index": 0, "nodes": list(range(8))}]
    target_rows = [
        {
            "cell_index": 0,
            "marker": "core_tip_receiver_outer",
            "face_nodes": [4, 5, 6, 7],
            "triangle_nodes": [4, 5, 6],
        },
        {
            "cell_index": 0,
            "marker": "core_tip_receiver_outer",
            "face_nodes": [4, 5, 6, 7],
            "triangle_nodes": [4, 6, 7],
        },
    ]

    audit = module.audit_global_star_split_basis(
        vertices=vertices,
        candidate_cells=cells,
        external_boundary_rows=[{"nodes": [4, 5, 6, 7], "role": "outer"}],
        target_triangle_rows=target_rows,
    )

    assert audit["matched_target_triangle_count"] == 2
    assert audit["unmatched_target_triangle_count"] == 0
    assert audit["matched_target_triangles_by_marker"] == {"core_tip_receiver_outer": 2}


def test_global_star_split_reports_degenerate_star_triangles() -> None:
    module = _load_module()
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        (0.0, 1.0, 1.0),
    ]
    audit = module.audit_global_star_split_basis(
        vertices=vertices,
        candidate_cells=[{"cell_index": 0, "nodes": list(range(8))}],
        external_boundary_rows=[
            {"nodes": [0, 1, 2, 3], "role": "outer"},
            {"nodes": [4, 7, 6, 5], "role": "outer"},
            {"nodes": [0, 4, 5, 1], "role": "outer"},
            {"nodes": [1, 5, 6, 2], "role": "outer"},
            {"nodes": [2, 6, 7, 3], "role": "outer"},
            {"nodes": [3, 7, 4, 0], "role": "outer"},
        ],
        target_triangle_rows=[],
    )

    assert audit["status"] == "global_star_split_basis_degenerate_reduction_required"
    assert audit["degenerate_star_triangle_count"] > 0
    assert "degenerate_star_triangles_require_cell_type_reduction" in audit["blockers"]


def test_r22_summary_keeps_cfd_incomplete_until_su2_mesh_yplus_and_ladder() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        audit={
            "status": "global_star_split_basis_ready",
            "internal_split_leak_face_count": 0,
            "nonmanifold_split_face_count": 0,
            "unmatched_target_triangle_count": 0,
            "non_positive_tet_count": 0,
        },
        output_dir=Path("/tmp/wo006r22"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert "merged BL+core SU2 handoff" in summary["blocked_claims"]


def test_r22_summary_names_degenerate_reduction_blocker() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        audit={
            "status": "global_star_split_basis_degenerate_reduction_required",
            "internal_split_leak_face_count": 0,
            "nonmanifold_split_face_count": 0,
            "unmatched_target_triangle_count": 0,
            "non_positive_tet_count": 0,
            "degenerate_star_triangle_count": 128,
        },
        output_dir=Path("/tmp/wo006r22"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["verdict"] == "global_star_split_degenerate_reduction_required"
    assert "degenerate_star_triangles_require_cell_type_reduction" in summary["blockers"]
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
