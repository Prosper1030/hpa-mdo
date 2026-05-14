from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r23_degenerate_star_cell_localization.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r23_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_collect_degenerate_star_triangles_reports_cell_face_and_repeated_points() -> None:
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
    records = module.collect_degenerate_star_triangle_records(
        vertices=vertices,
        candidate_cells=[
            {"cell_index": 7, "source": "unit", "role": "collapsed_hex", "nodes": list(range(8))}
        ],
        target_triangle_rows=[],
    )

    assert len(records) == 4
    assert {record["cell_index"] for record in records} == {7}
    assert {record["role"] for record in records} == {"collapsed_hex"}
    assert all(record["unique_point_count"] < 3 for record in records)
    assert all(record["repeated_point_keys"] for record in records)
    assert all("local_face_index" in record for record in records)


def test_degenerate_localization_summary_keeps_cfd_incomplete() -> None:
    module = _load_module()

    summary = module.build_localization_summary(
        records=[
            {
                "cell_index": 7,
                "source": "unit",
                "role": "collapsed_hex",
                "marker": "",
                "point_bounds": {
                    "x_min": 0.0,
                    "x_max": 1.0,
                    "y_min": 2.0,
                    "y_max": 2.0,
                    "z_min": -0.1,
                    "z_max": 0.1,
                },
            },
            {
                "cell_index": 8,
                "source": "unit",
                "role": "collapsed_hex",
                "marker": "core_tip_receiver_outer",
                "point_bounds": {
                    "x_min": 0.5,
                    "x_max": 1.5,
                    "y_min": 3.0,
                    "y_max": 3.0,
                    "z_min": -0.2,
                    "z_max": 0.2,
                },
            },
        ],
        output_dir=Path("/tmp/wo006r23"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["verdict"] == "degenerate_star_cells_localized_repair_required"
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["degenerate_star_triangle_count"] == 2
    assert summary["degenerate_cell_count"] == 2
    assert summary["records_by_role"] == {"collapsed_hex": 2}
    assert summary["records_by_marker"] == {"": 1, "core_tip_receiver_outer": 1}
    assert summary["bounds_m"]["y_min"] == 2.0
    assert summary["bounds_m"]["y_max"] == 3.0
