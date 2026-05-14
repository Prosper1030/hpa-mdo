from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r18_handoff_residual_localization.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r18_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_residual_localization_groups_unowned_loop_cap_fans() -> None:
    module = _load_module()
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (3.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
        (4.0, 1.0, 0.0),
        (3.0, 1.0, 0.0),
    ]
    core_rows = [
        {
            "core_face_index": 0,
            "marker": "core_wall_loop_cap",
            "triangle_nodes": [0, 1, 2],
            "candidate_owned": False,
            "matched_by_best_hybrid_split": False,
        },
        {
            "core_face_index": 1,
            "marker": "core_wall_loop_cap",
            "triangle_nodes": [0, 2, 3],
            "candidate_owned": False,
            "matched_by_best_hybrid_split": False,
        },
        {
            "core_face_index": 2,
            "marker": "core_wall_loop_cap",
            "triangle_nodes": [4, 5, 6],
            "candidate_owned": False,
            "matched_by_best_hybrid_split": False,
        },
        {
            "core_face_index": 3,
            "marker": "core_wall_loop_cap",
            "triangle_nodes": [4, 6, 7],
            "candidate_owned": False,
            "matched_by_best_hybrid_split": False,
        },
    ]

    residuals = module.summarize_handoff_residuals(
        vertices=vertices,
        core_triangle_rows=core_rows,
        cell_choice_rows=[],
    )

    assert residuals["status"] == "blocked"
    assert residuals["unowned_residual_count"] == 4
    assert residuals["unowned_residuals_by_marker"] == {"core_wall_loop_cap": 4}
    assert residuals["loop_cap_fans"]["status"] == "owner_cells_missing"
    assert residuals["loop_cap_fans"]["fan_count"] == 2
    assert residuals["loop_cap_fans"]["fans"][0]["triangle_count"] == 2
    assert residuals["recommended_next_repair"] == (
        "materialize_core_wall_loop_cap_owner_cells"
    )


def test_residual_localization_reports_incompatible_owned_cells() -> None:
    module = _load_module()
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
    ]
    core_rows = [
        {
            "core_face_index": 8,
            "marker": "wake_edge_receiver",
            "triangle_nodes": [0, 1, 2],
            "candidate_owned": True,
            "matched_by_best_hybrid_split": False,
        },
        {
            "core_face_index": 9,
            "marker": "core_tip_receiver_outer",
            "triangle_nodes": [0, 2, 3],
            "candidate_owned": True,
            "matched_by_best_hybrid_split": False,
        },
    ]
    cell_rows = [
        {
            "cell_index": 26110,
            "source": "tip_receiver",
            "role": "left_tip",
            "boundary_face_count": 3,
            "target_core_triangle_count": 6,
            "selected_pattern": "tet_35",
            "matched_triangle_count": 4,
            "unmatched_triangle_count": 2,
        }
    ]

    residuals = module.summarize_handoff_residuals(
        vertices=vertices,
        core_triangle_rows=core_rows,
        cell_choice_rows=cell_rows,
    )

    assert residuals["status"] == "blocked"
    assert residuals["incompatible_owned_residual_count"] == 2
    assert residuals["incompatible_owned_residuals_by_marker"] == {
        "core_tip_receiver_outer": 1,
        "wake_edge_receiver": 1,
    }
    assert residuals["incompatible_cells"]["count"] == 1
    assert residuals["incompatible_cells"]["cells"][0]["cell_index"] == 26110
    assert residuals["incompatible_cells"]["cells"][0]["source"] == "tip_receiver"


def test_r18_summary_keeps_baseline_cfd_incomplete() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        residuals={
            "status": "blocked",
            "recommended_next_repair": "materialize_core_wall_loop_cap_owner_cells",
            "unowned_residuals_by_marker": {"core_wall_loop_cap": 60},
            "incompatible_owned_residuals_by_marker": {},
        },
        output_dir=Path("/tmp/wo006r18"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["verdict"] == "handoff_residuals_localized_repair_required"
    assert "SU2 coarse/medium/fine ladder" in summary["blocked_claims"]
