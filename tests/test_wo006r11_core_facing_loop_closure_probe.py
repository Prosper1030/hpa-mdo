from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.test_wo006r10_near_wall_core_closure_probe import _sharp_te_block


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r11_core_facing_loop_closure.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r11_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_loop_caps_close_r10_core_facing_open_edges_without_promoting_to_cfd() -> None:
    module = _load_module()
    block = _sharp_te_block(layer_count=2)
    candidate = module.build_near_wall_merged_volume_candidate(block)

    summary = module.summarize_core_facing_loop_closure(block, candidate)
    probe = module.build_probe_summary(loop_closure=summary)

    assert summary["status"] == "core_facing_loop_cap_surface_ready_core_mesh_pending"
    assert summary["pre_cap_topology"]["status"] == "not_watertight"
    assert summary["post_cap_topology"]["status"] == "watertight"
    assert summary["loop_count"] == 2
    assert summary["cap_face_count"] == summary["pre_cap_topology"]["bad_edge_count"]
    assert summary["cap_quality"]["non_positive_cap_area_count"] == 0
    assert module.LOOP_CAP_MARKER in summary["surface_marker_counts"]
    assert "core_facing_loop_cap_surface_not_watertight" not in summary["blockers"]
    assert "core_farfield_mesh_not_generated" in summary["blockers"]
    assert probe["goal_status"] == "INCOMPLETE"
    assert probe["cfd_status"] == "mesh_ladder_incomplete"
    assert probe["coefficient_interpretable"] is False


def test_core_facing_loop_closure_probe_run_writes_artifacts(tmp_path: Path) -> None:
    module = _load_module()

    summary = module.run_probe(
        output_dir=tmp_path / "wo006r11",
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    closure = summary["loop_closure"]
    assert summary["verdict"] == "core_facing_loop_cap_surface_ready_not_handoff"
    assert closure["pre_cap_topology"]["status"] == "not_watertight"
    assert closure["post_cap_topology"]["status"] == "watertight"
    assert closure["loop_count"] == 2
    assert closure["cap_face_count"] == closure["pre_cap_topology"]["bad_edge_count"]
    assert closure["can_generate_core_mesh_probe"] is True
    assert (tmp_path / "wo006r11" / "summary.json").exists()
    assert (tmp_path / "wo006r11" / "loop_table.csv").exists()
    assert (tmp_path / "wo006r11" / "core_facing_loop_closure_report.md").exists()
