from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from hpa_meshing.mesh_native.wing_surface import Face


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r9_triangulated_core_interface.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r9_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _core_report(*, quality_status: str = "pass", coupling_status: str = "partial") -> dict:
    coupling_complete = coupling_status == "complete"
    return {
        "status": "meshed",
        "mesh_path": "/tmp/core_triangulated_interface_probe.msh",
        "su2_path": "/tmp/core_triangulated_interface_probe.su2",
        "volume_element_count": 5994,
        "node_count": 28409,
        "volume_element_type_counts": {"4": 5994},
        "mesh_sizing": {
            "preserve_boundary_mesh": True,
            "preserved_boundary_representation": "triangulated",
        },
        "mesh_quality_gate": {
            "status": quality_status,
            "blockers": [] if quality_status == "pass" else ["non_positive_volume"],
        },
        "quality_metrics": {
            "tetra_element_count": 5994,
            "pyramid_element_count": 0,
            "non_positive_min_sicn_count": 0 if quality_status == "pass" else 1,
            "non_positive_min_sige_count": 0 if quality_status == "pass" else 1,
            "non_positive_volume_count": 0 if quality_status == "pass" else 1,
            "min_sicn": 0.0011,
            "min_sige": 0.00046,
            "min_volume": 1.2e-6,
        },
        "interface_conformality": {
            "status": "preserved",
            "can_merge_with_owned_bl_block": True,
            "expected_boundary_representation": "triangulated",
        },
        "bl_block_coupling": {
            "status": coupling_status,
            "can_merge_core_with_bl_block": coupling_complete,
            "matched_face_count": 2048,
            "unmatched_core_interface_face_count": 0 if coupling_complete else 126,
            "unmatched_core_interface_face_counts_by_marker": {}
            if coupling_complete
            else {"span_cap": 126},
            "unmatched_bl_boundary_face_count": 0 if coupling_complete else 6272,
            "unmatched_bl_boundary_face_counts_by_marker": {}
            if coupling_complete
            else {"span_cap": 3072, "wake_cut": 3200},
        },
    }


def test_summarizes_quality_repair_without_promoting_to_cfd_completion() -> None:
    module = _load_module()

    report = module.summarize_triangulated_core_probe(
        _core_report(quality_status="pass", coupling_status="partial"),
        merge_gate={
            "status": "blocked",
            "blockers": ["owned_bl_core_coupling_incomplete", "merged_mixed_su2_mesh_missing"],
        },
    )

    assert report["status"] == "blocked"
    assert report["goal_status"] == "INCOMPLETE"
    assert report["cfd_status"] == "mesh_ladder_incomplete"
    assert report["core_quality_repair_status"] == "pass"
    assert "core_quality_repaired_by_triangulated_interface" in report["evidence_flags"]
    assert "bl_core_coupling_incomplete" in report["blockers"]
    assert "merged_mixed_su2_mesh_missing" in report["blockers"]
    assert report["coefficient_interpretable"] is False


def test_rejects_triangulated_core_probe_when_quality_still_fails() -> None:
    module = _load_module()

    report = module.summarize_triangulated_core_probe(
        _core_report(quality_status="fail", coupling_status="partial"),
        merge_gate={"status": "blocked", "blockers": ["core_mesh_quality_gate_not_pass"]},
    )

    assert report["status"] == "blocked"
    assert "core_mesh_quality_not_pass" in report["blockers"]
    assert "core_quality_repaired_by_triangulated_interface" not in report["evidence_flags"]


def test_core_writer_uses_preserved_triangulated_hxt_interface(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    calls = []

    def fake_core_writer(block, farfield, out_path, **kwargs):
        calls.append(
            {
                "out_path": out_path,
                "kwargs": kwargs,
                "farfield_marker_counts": farfield.marker_counts(),
            }
        )
        return _core_report(quality_status="pass", coupling_status="partial")

    monkeypatch.setattr(module, "write_boundary_layer_block_core_tet_mesh", fake_core_writer)

    report = module.run_triangulated_core_probe(
        block=object(),
        core_interface=module.SurfaceMesh(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[Face(nodes=(0, 1, 2), marker="bl_outer_interface")],
        ),
        output_dir=tmp_path,
        mesh_size=1.0,
        farfield_mesh_size=8.0,
    )

    assert report["core_probe"]["mesh_sizing"]["preserved_boundary_representation"] == "triangulated"
    assert calls[0]["kwargs"]["preserve_boundary_mesh"] is True
    assert calls[0]["kwargs"]["preserved_boundary_representation"] == "triangulated"
    assert calls[0]["kwargs"]["mesh_algorithm3d"] == 10
    assert calls[0]["kwargs"]["gmsh_threads"] == 4
    assert calls[0]["farfield_marker_counts"] == {"farfield": 6}
