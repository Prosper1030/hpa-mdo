from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r27_apply_boundary_marker_repair.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r27_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_apply_marker_repair_marks_only_wing_wall_records() -> None:
    module = _load_module()
    markers = {
        "wing_wall": [{"element_type": module.SU2_TRIANGLE, "nodes": (0, 1, 3)}],
        "farfield": [],
    }
    records = [
        {
            "face_nodes": [0, 1, 2],
            "recommended_marker": "wing_wall",
            "classification": "loop_cap_owner_pyramid_exterior",
        },
        {
            "face_nodes": [1, 2, 3],
            "recommended_marker": "",
            "classification": "unclassified_boundary_leak",
        },
    ]

    repaired_markers, repair = module.apply_boundary_marker_repair(
        markers=markers,
        leak_records=records,
    )

    assert repair["applied_face_count"] == 1
    assert repair["skipped_face_count"] == 1
    assert repair["target_marker"] == "wing_wall"
    assert repaired_markers["wing_wall"] == [
        {"element_type": module.SU2_TRIANGLE, "nodes": (0, 1, 3)},
        {"element_type": module.SU2_TRIANGLE, "nodes": (0, 1, 2)},
    ]


def test_build_probe_summary_promotes_repaired_marker_pass_but_not_cfd_completion() -> None:
    module = _load_module()
    summary = module.build_probe_summary(
        output_dir=Path("/tmp/r27"),
        geometry_source="/tmp/section_table.csv",
        handoff={
            "status": "mixed_su2_handoff_written",
            "mesh_path": "/tmp/repaired.su2",
            "node_count": 4,
            "volume_element_count": 1,
            "volume_element_type_counts": {"10": 1},
            "marker_counts": {"wing_wall": 3, "farfield": 1},
        },
        boundary_audit={
            "status": "pass",
            "blockers": [],
            "unmarked_boundary_face_count": 0,
            "extra_marker_face_count": 0,
        },
        quality={"status": "pass", "blockers": [], "non_positive_volume_count": 0},
        marker_repair={"applied_face_count": 68, "target_marker": "wing_wall"},
        yplus={"status": "estimate_ready_not_solver_postprocessed"},
    )

    assert summary["verdict"] == "mixed_su2_handoff_marker_quality_pass_solver_ladder_pending"
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert "su2_solver_ladder_not_run" in summary["blockers"]
