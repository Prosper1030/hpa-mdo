from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r24_degenerate_cull_handoff_basis.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r24_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evaluate_degenerate_cull_basis_accepts_empty_marker_wake_receiver_records() -> None:
    module = _load_module()

    result = module.evaluate_degenerate_cull_basis(
        global_star_audit={
            "status": "global_star_split_basis_degenerate_reduction_required",
            "target_triangle_count": 5594,
            "matched_target_triangle_count": 5594,
            "unmatched_target_triangle_count": 0,
            "internal_split_leak_face_count": 0,
            "nonmanifold_split_face_count": 0,
            "non_positive_tet_count": 0,
            "degenerate_star_triangle_count": 2,
        },
        localization={
            "degenerate_star_triangle_count": 2,
            "degenerate_cell_count": 2,
            "records_by_role": {"wake_receiver": 2},
            "records_by_marker": {"": 2},
        },
    )

    assert result["status"] == "degenerate_cull_basis_ready"
    assert result["blockers"] == []
    assert result["culled_degenerate_triangle_count"] == 2


def test_evaluate_degenerate_cull_basis_rejects_marked_or_non_wake_records() -> None:
    module = _load_module()

    result = module.evaluate_degenerate_cull_basis(
        global_star_audit={
            "status": "global_star_split_basis_degenerate_reduction_required",
            "target_triangle_count": 5594,
            "matched_target_triangle_count": 5594,
            "unmatched_target_triangle_count": 0,
            "internal_split_leak_face_count": 0,
            "nonmanifold_split_face_count": 0,
            "non_positive_tet_count": 0,
            "degenerate_star_triangle_count": 3,
        },
        localization={
            "degenerate_star_triangle_count": 3,
            "degenerate_cell_count": 2,
            "records_by_role": {"wake_receiver": 2, "tip_receiver": 1},
            "records_by_marker": {"": 2, "core_tip_receiver_outer": 1},
        },
    )

    assert result["status"] == "degenerate_cull_basis_blocked"
    assert "degenerate_records_include_non_wake_receiver_roles" in result["blockers"]
    assert "degenerate_records_include_owned_markers" in result["blockers"]


def test_build_probe_summary_stays_cfd_incomplete_when_cull_basis_ready() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        cull_basis={
            "status": "degenerate_cull_basis_ready",
            "blockers": [],
            "culled_degenerate_triangle_count": 2,
        },
        output_dir=Path("/tmp/wo006r24"),
        r22_summary_path=Path("/tmp/r22.json"),
        r23_summary_path=Path("/tmp/r23.json"),
    )

    assert summary["verdict"] == "degenerate_cull_basis_ready_mixed_mesh_pending"
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert "merged BL+core SU2 handoff" in summary["blocked_claims"]
