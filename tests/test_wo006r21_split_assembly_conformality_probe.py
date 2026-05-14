from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r21_split_assembly_conformality.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r21_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_split_assembly_detects_internal_face_leak_from_mismatched_neighbor_diagonal() -> None:
    module = _load_module()
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        (1.0, 1.0, 1.0),
        (0.0, 1.0, 1.0),
        (2.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
        (2.0, 0.0, 1.0),
        (2.0, 1.0, 1.0),
    ]
    cells = [
        {"cell_index": 0, "nodes": [0, 1, 2, 3, 4, 5, 6, 7]},
        {"cell_index": 1, "nodes": [1, 8, 9, 2, 5, 10, 11, 6]},
    ]
    selected_patterns = {0: "tet_06", 1: "tet_17"}
    external_boundary_rows = [
        {"nodes": [0, 3, 7, 4], "role": "outer"},
        {"nodes": [8, 9, 11, 10], "role": "outer"},
    ]

    audit = module.audit_split_assembly_conformality(
        vertices=vertices,
        candidate_cells=cells,
        selected_patterns_by_cell=selected_patterns,
        external_boundary_rows=external_boundary_rows,
    )

    assert audit["status"] == "split_assembly_internal_nonconformal"
    assert audit["internal_split_leak_face_count"] > 0
    assert audit["volume_element_count"] == 12


def test_split_assembly_summary_keeps_cfd_incomplete() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        audit={
            "status": "split_assembly_conformal",
            "internal_split_leak_face_count": 0,
            "external_unclassified_face_count": 0,
        },
        output_dir=Path("/tmp/wo006r21"),
        geometry_source="/tmp/section_table.csv",
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert "merged BL+core SU2 handoff" in summary["blocked_claims"]
