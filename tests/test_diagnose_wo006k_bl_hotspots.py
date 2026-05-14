from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "diagnose_wo006k_bl_hotspots.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("diagnose_wo006k_bl_hotspots", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["diagnose_wo006k_bl_hotspots"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _section_rows():
    return [
        {
            "section_index": "4",
            "y_m": "12.0163",
            "chord_m": "0.862163835",
            "airfoil_id": "dae31",
        },
        {
            "section_index": "5",
            "y_m": "14.076237",
            "chord_m": "0.784941307",
            "airfoil_id": "cst_tip_nsga2_g05_child_0032_70ef8136",
        },
    ]


def test_classifies_hotspot_into_baseline_a_airfoil_transition_band() -> None:
    module = _load_module()

    classified = module.classify_hotspot(
        {
            "element_tag": 27923,
            "min_sicn": -9.882736117219326e-06,
            "min_sige": -0.015609619102982883,
            "centroid_xyz_m": [0.8455892240699573, -12.35962616339804, 1.215916027043983],
        },
        _section_rows(),
    )

    assert classified["abs_y_m"] == pytest.approx(12.35962616339804)
    assert classified["section_interval"]["left_airfoil_id"] == "dae31"
    assert classified["section_interval"]["right_airfoil_id"].startswith("cst_tip")
    assert classified["section_interval"]["is_airfoil_transition"] is True
    assert classified["x_over_local_chord"] == pytest.approx(0.986, rel=0.01)
    assert classified["location_flags"] == [
        "airfoil_transition_band",
        "aft_or_te_hotspot",
        "non_positive_min_sicn",
        "non_positive_min_sige",
    ]


def test_hotspot_summary_blocks_cfd_ladder_when_transition_prisms_are_bad() -> None:
    module = _load_module()

    summary = module.summarize_hotspots(
        [
            {
                "element_tag": 27923,
                "min_sicn": -9.88e-06,
                "min_sige": -0.015,
                "centroid_xyz_m": [0.845, -12.36, 1.216],
            },
            {
                "element_tag": 99227,
                "min_sicn": 1.0e-06,
                "min_sige": 0.0011,
                "centroid_xyz_m": [0.846, 12.36, 1.216],
            },
        ],
        _section_rows(),
        top_n=2,
    )

    assert summary["status"] == "blocked"
    assert summary["worst_min_sicn"] == pytest.approx(-9.88e-06)
    assert "non_positive_bl_sicn_hotspots" in summary["blockers"]
    assert "bl_hotspot_in_airfoil_transition_band" in summary["blockers"]
    assert "bl_hotspot_near_trailing_edge" in summary["blockers"]
    assert summary["top_hotspots"][0]["section_interval"]["is_airfoil_transition"] is True


def test_resolve_report_mesh_path_accepts_repo_relative_output_paths(tmp_path: Path) -> None:
    module = _load_module()
    mesh_path = tmp_path / "output" / "case" / "mesh.msh"
    mesh_path.parent.mkdir(parents=True)
    mesh_path.write_text("$MeshFormat\n", encoding="utf-8")

    resolved = module.resolve_report_mesh_path(
        "output/case/mesh.msh",
        report_parent=tmp_path / "output" / "case",
        search_root=tmp_path,
    )

    assert resolved == mesh_path
