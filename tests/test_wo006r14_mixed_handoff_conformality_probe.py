from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from hpa_meshing.mesh_native.wing_surface import Face, SurfaceMesh


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r14_mixed_handoff_conformality.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r14_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_conformality_audit_separates_polygon_match_from_triangle_mismatch() -> None:
    module = _load_module()
    near_wall = SurfaceMesh(
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        faces=[Face(nodes=(0, 1, 2, 3), marker="bl_outer_interface")],
    )
    core = SurfaceMesh(
        vertices=list(near_wall.vertices),
        faces=[Face(nodes=(3, 2, 1, 0), marker="bl_outer_interface")],
    )

    audit = module.audit_mixed_handoff_conformality(
        near_wall_interface=near_wall,
        core_interface=core,
    )

    assert audit["status"] == "blocked_by_interface_triangulation_mismatch"
    assert audit["polygon_matched_core_face_count"] == 1
    assert audit["triangle_matched_core_face_count"] == 0
    assert audit["polygon_matched_but_triangle_unmatched_count"] == 1
    assert audit["unmatched_core_triangles_by_marker"] == {"bl_outer_interface": 2}


def test_summary_keeps_cfd_incomplete_until_mixed_handoff_is_conformal() -> None:
    module = _load_module()
    audit = {
        "status": "blocked_by_interface_triangulation_mismatch",
        "polygon_matched_core_face_count": 1,
        "polygon_matched_but_triangle_unmatched_count": 1,
        "unmatched_core_triangles_by_marker": {"bl_outer_interface": 2},
    }

    summary = module.build_probe_summary(
        audit=audit,
        output_dir=Path("/tmp/wo006r14"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["merged_handoff_status"] == "blocked_by_interface_triangulation_mismatch"
    assert "solver_ladder_not_run" in summary["blockers"]
