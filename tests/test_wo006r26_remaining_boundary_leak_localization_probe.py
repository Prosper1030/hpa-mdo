from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r26_remaining_boundary_leak_localization.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r26_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classify_unmarked_faces_counts_adjacent_source_and_geometry_class() -> None:
    module = _load_module()
    nodes = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    elements = [
        {
            "element_type": module.SU2_TETRA,
            "nodes": (0, 1, 2, 3),
            "source": "loop_cap_owner_pyramid_tet_split",
        }
    ]
    markers = {
        "wing_wall": [
            {"element_type": module.SU2_TRIANGLE, "nodes": (0, 1, 3)},
            {"element_type": module.SU2_TRIANGLE, "nodes": (0, 2, 3)},
        ],
        "farfield": [
            {"element_type": module.SU2_TRIANGLE, "nodes": (1, 2, 3)},
        ],
    }
    classifier_index = {
        module.point_polygon_key([nodes[0], nodes[1], nodes[2]], digits=10): [
            {
                "family": "loop_cap_owner_pyramid_exterior",
                "marker_role": "wing_wall",
                "surface_owner": "loop_cap_owner_pyramid_tip_wall_closure",
            }
        ]
    }

    records = module.collect_remaining_boundary_leak_records(
        nodes=nodes,
        elements=elements,
        markers=markers,
        classifier_index=classifier_index,
        digits=10,
    )
    summary = module.summarize_remaining_boundary_leaks(records=records, output_dir=Path("/tmp/r26"))

    assert len(records) == 1
    assert records[0]["adjacent_source"] == "loop_cap_owner_pyramid_tet_split"
    assert records[0]["classification"] == "loop_cap_owner_pyramid_exterior"
    assert records[0]["recommended_marker"] == "wing_wall"
    assert summary["leak_count"] == 1
    assert summary["leak_counts_by_adjacent_source"] == {"loop_cap_owner_pyramid_tet_split": 1}
    assert summary["leak_counts_by_classification"] == {"loop_cap_owner_pyramid_exterior": 1}
    assert summary["boundary_marker_repair_plan"]["status"] == "repair_plan_ready"


def test_summary_blocks_repair_plan_when_any_face_is_unclassified() -> None:
    module = _load_module()
    records = [
        {
            "face_nodes": [0, 1, 2],
            "area_m2": 1.0,
            "adjacent_source": "core_tet_mesh",
            "classification": "unclassified_boundary_leak",
            "recommended_marker": "",
            "surface_owner": "unknown",
            "point_bounds": {"x": [0.0, 1.0], "y": [0.0, 1.0], "z": [0.0, 0.0]},
            "matches": [],
        }
    ]

    summary = module.summarize_remaining_boundary_leaks(records=records, output_dir=Path("/tmp/r26"))

    assert summary["verdict"] == "remaining_boundary_leaks_localized_repair_blocked"
    assert summary["boundary_marker_repair_plan"]["status"] == "blocked"
    assert "unclassified_boundary_leaks" in summary["blockers"]
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
