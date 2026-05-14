from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r29_dual_quality_source_localization.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r29_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_internal_face_volume_jump_records_source_pair_and_centroid() -> None:
    module = _load_module()
    nodes = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -100.0),
    ]
    elements = [
        {
            "element_type": module.SU2_TETRA,
            "nodes": (0, 1, 2, 3),
            "source": "small_near_wall",
        },
        {
            "element_type": module.SU2_TETRA,
            "nodes": (0, 2, 1, 4),
            "source": "large_core",
        },
    ]

    records = module.internal_face_volume_jump_records(
        nodes=nodes,
        elements=elements,
        min_ratio=10.0,
    )

    assert len(records) == 1
    assert records[0]["source_pair"] == "large_core|small_near_wall"
    assert records[0]["volume_ratio"] == pytest.approx(100.0)
    assert records[0]["face_nodes"] == [0, 1, 2]
    assert records[0]["face_centroid"] == {"x": 1.0 / 3.0, "y": 1.0 / 3.0, "z": 0.0}


def test_source_pair_summary_promotes_pathological_jump_to_blocker() -> None:
    module = _load_module()
    records = [
        {
            "source_pair": "core_tet_mesh|culled_global_star_near_wall",
            "volume_ratio": 4.0e9,
            "face_area_m2": 1.0e-4,
        },
        {
            "source_pair": "loop_cap_owner_pyramid_tet_split|culled_global_star_near_wall",
            "volume_ratio": 2.0e5,
            "face_area_m2": 2.0e-4,
        },
    ]

    summary = module.summarize_source_pair_jumps(records, blocker_ratio=1.0e6)

    assert summary["status"] == "fail"
    assert summary["max_volume_ratio"] == 4.0e9
    assert summary["worst_source_pair"] == "core_tet_mesh|culled_global_star_near_wall"
    assert "internal_face_volume_jump_above_1e6" in summary["blockers"]
    assert summary["by_source_pair"]["core_tet_mesh|culled_global_star_near_wall"]["count"] == 1


def test_probe_summary_never_promotes_cfd_completion() -> None:
    module = _load_module()
    summary = module.build_probe_summary(
        output_dir=Path("/tmp/r29"),
        geometry_source="/tmp/section_table.csv",
        mesh_context={
            "node_count": 5,
            "volume_element_count": 2,
            "source_counts": {"small_near_wall": 1, "large_core": 1},
        },
        source_pair_summary={
            "status": "fail",
            "blockers": ["internal_face_volume_jump_above_1e6"],
            "max_volume_ratio": 4.0e9,
            "worst_source_pair": "large_core|small_near_wall",
        },
        top_records=[],
        elapsed_s=1.2,
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert "dual_quality_source_localization_only" in summary["blocked_claims"]
    assert "internal_face_volume_jump_above_1e6" in summary["blockers"]
