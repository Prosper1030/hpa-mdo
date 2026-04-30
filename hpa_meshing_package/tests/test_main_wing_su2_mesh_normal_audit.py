import json
from pathlib import Path

import pytest

from hpa_meshing.main_wing_su2_mesh_normal_audit import (
    build_main_wing_su2_mesh_normal_audit_report,
    write_main_wing_su2_mesh_normal_audit_report,
)


def _write_tiny_msh(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "$MeshFormat",
                "4.1 0 8",
                "$EndMeshFormat",
                "$PhysicalNames",
                "1",
                '2 2 "main_wing"',
                "$EndPhysicalNames",
                "$Entities",
                "0 0 1 0",
                "1 0 0 0 1 1 0 1 2 0",
                "$EndEntities",
                "$Nodes",
                "1 4 1 4",
                "2 1 0 4",
                "1",
                "2",
                "3",
                "4",
                "0 0 0",
                "1 0 0",
                "0 1 0",
                "1 1 0",
                "$EndNodes",
                "$Elements",
                "1 2 1 2",
                "2 1 2 2",
                "1 1 2 3",
                "2 4 2 3",
                "$EndElements",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_main_wing_su2_mesh_normal_audit_detects_mixed_surface_normals(
    tmp_path: Path,
):
    report = build_main_wing_su2_mesh_normal_audit_report(
        mesh_path=_write_tiny_msh(tmp_path / "mesh.msh")
    )

    assert report.normal_audit_status == "pass"
    assert report.surface_triangle_count == 2
    assert report.main_wing_surface_entity_count == 1
    assert report.normal_orientation["z_positive_fraction"] == pytest.approx(0.5)
    assert report.normal_orientation["z_negative_fraction"] == pytest.approx(0.5)
    assert report.normal_orientation["area_weighted_mean_normal"] == pytest.approx(
        [0.0, 0.0, 0.0]
    )
    assert "main_wing_surface_normals_mixed_upper_lower" in report.engineering_findings
    assert "single_global_normal_flip_not_supported" in report.engineering_findings
    assert report.next_actions[0] == (
        "compare_openvsp_panel_wake_model_against_su2_thin_sheet_wall_semantics"
    )


def test_write_main_wing_su2_mesh_normal_audit_report(tmp_path: Path):
    out_dir = tmp_path / "normal_audit"

    written = write_main_wing_su2_mesh_normal_audit_report(
        out_dir,
        mesh_path=_write_tiny_msh(tmp_path / "mesh.msh"),
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_su2_mesh_normal_audit.v1"
    assert payload["normal_audit_status"] == "pass"
    assert "Main Wing SU2 Mesh Normal Audit v1" in markdown
