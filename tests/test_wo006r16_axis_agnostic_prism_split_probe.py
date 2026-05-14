from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from hpa_meshing.mesh_native.wing_surface import Face, SurfaceMesh


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r16_axis_agnostic_prism_split.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r16_probe", SCRIPT_PATH)
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


def test_axis_agnostic_split_can_match_a_side_face_that_r15_cannot_split() -> None:
    module = _load_module()
    vertices = _unit_hex_vertices()
    candidate_cells = [
        {"cell_index": 0, "source": "owned_bl_block", "role": "boundary_layer", "nodes": list(range(8))}
    ]
    boundary_faces = [
        {"source": "owned_bl_block", "role": "bl_outer_interface", "nodes": [0, 4, 5, 1]},
    ]
    core_interface = SurfaceMesh(
        vertices=vertices,
        faces=[
            Face(nodes=(0, 4, 5), marker="bl_outer_interface"),
            Face(nodes=(0, 5, 1), marker="bl_outer_interface"),
        ],
    )

    audit = module.audit_axis_agnostic_prism_split_compatibility(
        vertices=vertices,
        candidate_cells=candidate_cells,
        candidate_boundary_faces=boundary_faces,
        core_interface=core_interface,
    )

    assert audit["status"] == "pass"
    assert audit["matched_core_triangle_count"] == 2
    assert audit["core_triangle_count"] == 2
    assert audit["unmatched_core_triangles_by_marker"] == {}
    assert audit["cell_choice_rows"][0]["selected_pattern"].startswith("y_")


def test_axis_agnostic_split_still_blocks_when_adjacent_faces_need_different_axes() -> None:
    module = _load_module()
    vertices = _unit_hex_vertices()
    candidate_cells = [
        {"cell_index": 0, "source": "owned_bl_block", "role": "boundary_layer", "nodes": list(range(8))}
    ]
    boundary_faces = [
        {"source": "owned_bl_block", "role": "bottom_interface", "nodes": [0, 1, 2, 3]},
        {"source": "owned_bl_block", "role": "side_interface", "nodes": [0, 4, 5, 1]},
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

    audit = module.audit_axis_agnostic_prism_split_compatibility(
        vertices=vertices,
        candidate_cells=candidate_cells,
        candidate_boundary_faces=boundary_faces,
        core_interface=core_interface,
    )

    assert audit["status"] == "blocked_by_incompatible_axis_agnostic_prism_split"
    assert audit["matched_core_triangle_count"] == 2
    assert audit["core_triangle_count"] == 4
    assert audit["unmatched_core_triangle_count"] == 2


def test_r16_summary_keeps_cfd_incomplete_until_all_core_triangles_match() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        audit={
            "status": "blocked_by_incompatible_axis_agnostic_prism_split",
            "matched_core_triangle_count": 5274,
            "core_triangle_count": 5658,
            "unmatched_core_triangles_by_marker": {"wake_edge_receiver": 192},
        },
        output_dir=Path("/tmp/wo006r16"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["verdict"] == "axis_agnostic_prism_split_handoff_blocked"
    assert "shared_interface_tessellation_missing" in summary["blockers"]
