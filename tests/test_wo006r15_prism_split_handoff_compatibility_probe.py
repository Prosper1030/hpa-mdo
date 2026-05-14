from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from hpa_meshing.mesh_native.wing_surface import Face, SurfaceMesh


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r15_prism_split_handoff_compatibility.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r15_probe", SCRIPT_PATH)
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


def test_prism_split_audit_passes_when_one_split_matches_all_core_triangles() -> None:
    module = _load_module()
    vertices = _unit_hex_vertices()
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
        ],
    )

    audit = module.audit_prism_split_handoff_compatibility(
        vertices=vertices,
        candidate_cells=candidate_cells,
        candidate_boundary_faces=boundary_faces,
        core_interface=core_interface,
    )

    assert audit["status"] == "pass"
    assert audit["matched_core_triangle_count"] == 2
    assert audit["core_triangle_count"] == 2
    assert audit["best_pattern_counts"] == {"pattern_0": 1}
    assert audit["unmatched_core_triangles_by_marker"] == {}


def test_prism_split_audit_blocks_when_one_cell_needs_conflicting_face_diagonals() -> None:
    module = _load_module()
    vertices = _unit_hex_vertices()
    candidate_cells = [
        {"cell_index": 0, "source": "owned_bl_block", "role": "boundary_layer", "nodes": list(range(8))}
    ]
    boundary_faces = [
        {"source": "owned_bl_block", "role": "bl_outer_interface", "nodes": [0, 1, 2, 3]},
        {"source": "owned_bl_block", "role": "core_tip_receiver_outer", "nodes": [4, 5, 6, 7]},
    ]
    core_interface = SurfaceMesh(
        vertices=vertices,
        faces=[
            Face(nodes=(0, 1, 2), marker="bl_outer_interface"),
            Face(nodes=(0, 2, 3), marker="bl_outer_interface"),
            Face(nodes=(4, 5, 7), marker="core_tip_receiver_outer"),
            Face(nodes=(5, 6, 7), marker="core_tip_receiver_outer"),
        ],
    )

    audit = module.audit_prism_split_handoff_compatibility(
        vertices=vertices,
        candidate_cells=candidate_cells,
        candidate_boundary_faces=boundary_faces,
        core_interface=core_interface,
    )

    assert audit["status"] == "blocked_by_incompatible_prism_split"
    assert audit["matched_core_triangle_count"] == 2
    assert audit["core_triangle_count"] == 4
    assert audit["unmatched_core_triangles_by_marker"] == {"core_tip_receiver_outer": 2}
    assert audit["cell_choice_rows"][0]["matched_triangle_count"] == 2
    assert audit["cell_choice_rows"][0]["unmatched_triangle_count"] == 2


def test_r15_summary_keeps_baseline_a_cfd_incomplete_until_shared_interface_exists() -> None:
    module = _load_module()
    summary = module.build_probe_summary(
        audit={
            "status": "blocked_by_incompatible_prism_split",
            "matched_core_triangle_count": 2,
            "core_triangle_count": 4,
            "unmatched_core_triangles_by_marker": {"core_tip_receiver_outer": 2},
        },
        output_dir=Path("/tmp/wo006r15"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["verdict"] == "prism_split_handoff_compatibility_blocked"
    assert "shared_interface_tessellation_missing" in summary["blockers"]
