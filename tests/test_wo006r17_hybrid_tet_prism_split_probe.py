from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from hpa_meshing.mesh_native.wing_surface import Face, SurfaceMesh


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r17_hybrid_tet_prism_split.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r17_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _unit_hex_vertices() -> list[tuple[float, float, float]]:
    return [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        (1.0, 1.0, 1.0),
        (0.0, 1.0, 1.0),
    ]


def test_hybrid_split_can_match_adjacent_faces_that_need_tet_decomposition() -> None:
    module = _load_module()
    vertices = _unit_hex_vertices()
    candidate_cells = [
        {"cell_index": 0, "source": "wake_receiver", "role": "wake_receiver", "nodes": list(range(8))}
    ]
    boundary_faces = [
        {"source": "wake_receiver", "role": "bottom_interface", "nodes": [0, 1, 2, 3]},
        {"source": "wake_receiver", "role": "side_interface", "nodes": [0, 4, 5, 1]},
    ]
    core_interface = SurfaceMesh(
        vertices=vertices,
        faces=[
            Face(nodes=(0, 1, 2), marker="bottom_interface"),
            Face(nodes=(0, 2, 3), marker="bottom_interface"),
            Face(nodes=(0, 4, 5), marker="side_interface"),
            Face(nodes=(0, 5, 1), marker="side_interface"),
        ],
    )

    audit = module.audit_hybrid_tet_prism_split_compatibility(
        vertices=vertices,
        candidate_cells=candidate_cells,
        candidate_boundary_faces=boundary_faces,
        core_interface=core_interface,
    )

    assert audit["status"] == "pass"
    assert audit["matched_core_triangle_count"] == 4
    assert audit["core_triangle_count"] == 4
    assert audit["unmatched_core_triangles_by_marker"] == {}
    assert audit["cell_choice_rows"][0]["selected_pattern"].startswith("tet_")


def test_hybrid_split_still_blocks_when_core_triangle_has_no_candidate_boundary_owner() -> None:
    module = _load_module()
    vertices = [*_unit_hex_vertices(), (2.0, 2.0, 2.0)]
    candidate_cells = [
        {"cell_index": 0, "source": "owned_bl_block", "role": "boundary_layer", "nodes": list(range(8))}
    ]
    boundary_faces = [
        {"source": "owned_bl_block", "role": "bl_outer_interface", "nodes": [0, 1, 2, 3]},
    ]
    core_interface = SurfaceMesh(
        vertices=vertices,
        faces=[
            Face(nodes=(0, 1, 2), marker="bl_outer_interface"),
            Face(nodes=(0, 2, 3), marker="bl_outer_interface"),
            Face(nodes=(0, 1, 8), marker="core_wall_loop_cap"),
        ],
    )

    audit = module.audit_hybrid_tet_prism_split_compatibility(
        vertices=vertices,
        candidate_cells=candidate_cells,
        candidate_boundary_faces=boundary_faces,
        core_interface=core_interface,
    )

    assert audit["status"] == "blocked_by_unowned_core_interface_triangles"
    assert audit["matched_core_triangle_count"] == 2
    assert audit["core_triangle_count"] == 3
    assert audit["unmatched_core_triangles_by_marker"] == {"core_wall_loop_cap": 1}
    assert audit["blockers"] == ["core_interface_triangles_without_candidate_owner"]


def test_r17_summary_keeps_cfd_incomplete_for_partial_hybrid_match() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        audit={
            "status": "blocked_by_unowned_core_interface_triangles",
            "matched_core_triangle_count": 5590,
            "core_triangle_count": 5658,
            "unmatched_core_triangles_by_marker": {"core_wall_loop_cap": 60},
            "blockers": ["core_interface_triangles_without_candidate_owner"],
        },
        output_dir=Path("/tmp/wo006r17"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["verdict"] == "hybrid_tet_prism_handoff_blocked"
    assert "core_interface_triangles_without_candidate_owner" in summary["blockers"]
