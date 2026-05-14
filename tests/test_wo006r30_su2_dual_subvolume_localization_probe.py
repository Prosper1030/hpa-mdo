from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r30_su2_dual_subvolume_localization.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r30_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_su2_style_subvolume_hotspots_find_vertex_not_tet_pair() -> None:
    module = _load_module()
    nodes = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (100.0, 0.0, 0.0),
        (0.0, 100.0, 0.0),
        (0.0, 0.0, 100.0),
    ]
    elements = [
        {
            "element_type": module.SU2_TETRA,
            "nodes": (0, 1, 2, 3),
            "source": "small_near_wall",
        },
        {
            "element_type": module.SU2_TETRA,
            "nodes": (0, 4, 5, 6),
            "source": "large_core",
        },
    ]

    records, metric = module.su2_style_dual_subvolume_hotspots(
        nodes=nodes,
        elements=elements,
        min_ratio=1.0e5,
        top_count=5,
    )

    assert metric["status"] == "fail"
    assert metric["max_cv_sub_volume_ratio"] == pytest.approx(1.0e6)
    assert records[0]["point_index"] == 0
    assert records[0]["source_pair"] == "large_core|small_near_wall"
    assert records[0]["min_subvolume"]["source"] == "small_near_wall"
    assert records[0]["max_subvolume"]["source"] == "large_core"


def test_probe_summary_never_promotes_dual_hotspot_to_cfd_completion() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        output_dir=Path("/tmp/r30"),
        geometry_source="/tmp/section_table.csv",
        mesh_context={
            "node_count": 7,
            "volume_element_count": 2,
            "source_counts": {"small_near_wall": 1, "large_core": 1},
        },
        dual_metric_summary={
            "status": "fail",
            "blockers": ["su2_style_dual_subvolume_ratio_extreme"],
            "max_cv_sub_volume_ratio": 1.0e6,
            "worst_point_index": 0,
            "worst_source_pair": "large_core|small_near_wall",
        },
        top_records=[],
        elapsed_s=1.0,
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["coefficient_interpretable"] is False
    assert "SU2 coarse/medium/fine ladder" in summary["blocked_claims"]
    assert "su2_style_dual_subvolume_ratio_extreme" in summary["blockers"]


def test_enrich_hotspots_adds_boundary_marker_and_incident_source_context() -> None:
    module = _load_module()
    records = [
        {
            "point_index": 0,
            "point": {"x": 0.0, "y": 0.0, "z": 0.0},
            "cv_sub_volume_ratio": 1.0e6,
        }
    ]
    markers = {
        "farfield": [{"element_type": module.SU2_TRIANGLE, "nodes": (0, 1, 2)}],
        "wing_wall": [{"element_type": module.SU2_TRIANGLE, "nodes": (3, 4, 5)}],
    }
    elements = [
        {"element_type": module.SU2_TETRA, "nodes": (0, 1, 2, 3), "source": "core_tet_mesh"},
        {
            "element_type": module.SU2_TETRA,
            "nodes": (0, 4, 5, 6),
            "source": "culled_global_star_near_wall",
        },
    ]

    enriched = module.enrich_hotspot_records_with_point_context(
        records=records,
        markers=markers,
        elements=elements,
    )

    assert enriched[0]["point_markers"] == ["farfield"]
    assert enriched[0]["incident_element_source_counts"] == {
        "core_tet_mesh": 1,
        "culled_global_star_near_wall": 1,
    }
