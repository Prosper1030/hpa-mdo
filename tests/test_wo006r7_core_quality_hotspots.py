from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r7_core_quality_hotspots.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r7_core_hotspots", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _section_rows() -> list[dict[str, str]]:
    return [
        {
            "section_index": "4",
            "y_m": "12.0163",
            "chord_m": "0.862163835",
            "x_le_m": "0.0",
            "airfoil_id": "dae31",
        },
        {
            "section_index": "5",
            "y_m": "14.076237",
            "chord_m": "0.784941307",
            "x_le_m": "0.0",
            "airfoil_id": "cst_tip_nsga2_g05_child_0032_70ef8136",
        },
    ]


def test_classifies_r6_bad_core_pyramid_as_preserved_bl_outer_interface_hotspot() -> None:
    module = _load_module()

    classified = module.classify_core_hotspot(
        {
            "element_tag": 14842,
            "element_type": 7,
            "element_type_name": "Pyramid 5",
            "min_sicn": -0.00494822257627465,
            "min_sige": -0.0018875018761725468,
            "volume": -2.955911203573579e-06,
            "centroid_xyz_m": [0.8285095742902124, 12.542569526851873, 1.3007599266739445],
            "matched_boundary_marker": "bl_outer_interface",
            "matched_boundary_element_type": 3,
        },
        _section_rows(),
    )

    assert classified["element_family"] == "pyramid"
    assert classified["matched_boundary_marker"] == "bl_outer_interface"
    assert classified["section_interval"]["is_airfoil_transition"] is True
    assert classified["x_over_local_chord"] == pytest.approx(1.0, rel=0.06)
    assert classified["location_flags"] == [
        "airfoil_transition_band",
        "aft_or_te_hotspot",
        "non_positive_min_sicn",
        "non_positive_min_sige",
        "non_positive_core_volume",
        "core_pyramid_element",
        "adjacent_to_bl_outer_interface",
        "preserved_quad_to_core_pyramid_transition",
    ]


def test_summary_blocks_handoff_when_core_pyramids_are_bad_on_bl_outer_interface() -> None:
    module = _load_module()

    summary = module.summarize_core_hotspots(
        [
            {
                "element_tag": 14842,
                "element_type": 7,
                "element_type_name": "Pyramid 5",
                "min_sicn": -0.0049,
                "min_sige": -0.0018,
                "volume": -2.9e-6,
                "centroid_xyz_m": [0.828, 12.54, 1.30],
                "matched_boundary_marker": "bl_outer_interface",
                "matched_boundary_element_type": 3,
            },
            {
                "element_tag": 14461,
                "element_type": 7,
                "element_type_name": "Pyramid 5",
                "min_sicn": -5.8e-5,
                "min_sige": -2.3e-5,
                "volume": -1.0e-8,
                "centroid_xyz_m": [0.883, -5.19, 0.285],
                "matched_boundary_marker": "bl_outer_interface",
                "matched_boundary_element_type": 3,
            },
        ],
        _section_rows(),
        top_n=2,
    )

    assert summary["status"] == "blocked"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["coefficient_interpretable"] is False
    assert summary["hotspot_count"] == 2
    assert summary["element_family_counts"] == {"pyramid": 2}
    assert summary["matched_boundary_marker_counts"] == {"bl_outer_interface": 2}
    assert "non_positive_core_volume_quality_hotspots" in summary["blockers"]
    assert "core_pyramid_hotspots_on_bl_outer_interface" in summary["blockers"]
    assert "core_quality_hotspots_near_trailing_edge" in summary["blockers"]
    assert "pyramid transition" in summary["engineering_read"]


def test_r7_run_writes_core_quality_hotspot_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    section_table = tmp_path / "section_table.csv"
    section_table.write_text(
        "\n".join(
            [
                "section_index,y_m,chord_m,x_le_m,airfoil_id",
                "4,12.0163,0.862163835,0.0,dae31",
                "5,14.076237,0.784941307,0.0,cst_tip_nsga2_g05_child_0032_70ef8136",
                "",
            ]
        ),
        encoding="utf-8",
    )
    hotspots_path = tmp_path / "hotspots.json"
    hotspots_path.write_text(
        json.dumps(
            [
                {
                    "element_tag": 14842,
                    "element_type": 7,
                    "element_type_name": "Pyramid 5",
                    "min_sicn": -0.0049,
                    "min_sige": -0.0018,
                    "volume": -2.9e-6,
                    "centroid_xyz_m": [0.828, 12.54, 1.30],
                    "matched_boundary_marker": "bl_outer_interface",
                    "matched_boundary_element_type": 3,
                }
            ]
        ),
        encoding="utf-8",
    )

    summary = module.run_diagnosis(
        section_table=section_table,
        output_dir=tmp_path / "wo006r7",
        hotspots_json=hotspots_path,
        top_n=1,
    )

    assert summary["status"] == "blocked"
    assert (tmp_path / "wo006r7" / "core_quality_hotspots.json").exists()
    assert (tmp_path / "wo006r7" / "core_quality_hotspots.csv").exists()
    assert (tmp_path / "wo006r7" / "core_quality_hotspot_report.md").exists()
