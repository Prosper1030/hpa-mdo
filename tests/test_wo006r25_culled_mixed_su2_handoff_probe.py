from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r25_culled_mixed_su2_handoff.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r25_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_star_tets_skip_degenerate_triangles_and_count_culls() -> None:
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
    writer = module.MixedMeshBuilder(digits=10)
    result = module.build_culled_global_star_near_wall_elements(
        vertices=vertices,
        candidate_cells=[{"cell_index": 0, "nodes": list(range(8)), "role": "wake_receiver"}],
        target_triangle_rows=[],
        writer=writer,
    )

    assert result["element_count"] > 0
    assert result["culled_degenerate_triangle_count"] > 0
    assert result["non_positive_volume_count"] == 0
    assert all(len(set(element["nodes"])) == 4 for element in result["elements"])


def test_boundary_audit_requires_all_exterior_faces_to_be_marked() -> None:
    module = _load_module()
    elements = [
        {"element_type": module.SU2_TETRA, "nodes": (0, 1, 2, 3), "source": "tet"},
    ]
    markers = {
        "wing_wall": [
            {"element_type": module.SU2_TRIANGLE, "nodes": (0, 1, 2)},
            {"element_type": module.SU2_TRIANGLE, "nodes": (0, 1, 3)},
            {"element_type": module.SU2_TRIANGLE, "nodes": (0, 2, 3)},
        ],
    }

    audit = module.audit_volume_boundary_markers(elements=elements, markers=markers)

    assert audit["status"] == "fail"
    assert audit["unmarked_boundary_face_count"] == 1
    assert audit["extra_marker_face_count"] == 0
    assert audit["marker_face_counts"] == {"wing_wall": 3}


def test_boundary_audit_passes_when_tet_exterior_is_fully_marked() -> None:
    module = _load_module()
    elements = [
        {"element_type": module.SU2_TETRA, "nodes": (0, 1, 2, 3), "source": "tet"},
    ]
    markers = {
        "wing_wall": [
            {"element_type": module.SU2_TRIANGLE, "nodes": (0, 1, 2)},
            {"element_type": module.SU2_TRIANGLE, "nodes": (0, 1, 3)},
        ],
        "farfield": [
            {"element_type": module.SU2_TRIANGLE, "nodes": (0, 2, 3)},
            {"element_type": module.SU2_TRIANGLE, "nodes": (1, 2, 3)},
        ],
    }

    audit = module.audit_volume_boundary_markers(elements=elements, markers=markers)

    assert audit["status"] == "pass"
    assert audit["unmarked_boundary_face_count"] == 0
    assert audit["extra_marker_face_count"] == 0
    assert audit["boundary_face_count"] == 4


def test_build_probe_summary_keeps_solver_ladder_incomplete_after_handoff_pass() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        output_dir=Path("/tmp/wo006r25"),
        geometry_source="/tmp/section_table.csv",
        handoff={
            "status": "mixed_su2_handoff_written",
            "mesh_path": "/tmp/mesh.su2",
            "node_count": 4,
            "volume_element_count": 1,
            "volume_element_type_counts": {"10": 1},
            "marker_counts": {"wing_wall": 2, "farfield": 2},
            "surface_ownership": {"wing_wall": "wall", "farfield": "far"},
        },
        boundary_audit={
            "status": "pass",
            "blockers": [],
            "boundary_face_count": 4,
            "unmarked_boundary_face_count": 0,
            "extra_marker_face_count": 0,
        },
        quality={
            "status": "pass",
            "blockers": [],
            "non_positive_volume_count": 0,
        },
        yplus={
            "status": "estimate_ready_not_solver_postprocessed",
            "first_layer_height_m": 5.0e-5,
        },
        core_report={"status": "meshed"},
        star_split={"element_count": 1, "culled_degenerate_triangle_count": 0},
        loop_cap={"element_count": 0, "non_positive_volume_count": 0},
    )

    assert summary["verdict"] == "mixed_su2_handoff_written_solver_ladder_pending"
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert "SU2 coarse/medium/fine ladder" in summary["blocked_claims"]
