import json
from pathlib import Path

from hpa_meshing.main_wing_su2_surface_topology_audit import (
    build_main_wing_su2_surface_topology_audit_report,
    write_main_wing_su2_surface_topology_audit_report,
)


def _write_single_sheet_msh(path: Path) -> Path:
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


def test_surface_topology_audit_flags_single_sheet_fixture(tmp_path: Path):
    report = build_main_wing_su2_surface_topology_audit_report(
        mesh_path=_write_single_sheet_msh(tmp_path / "mesh.msh"),
        reference_area_m2=1.0,
    )

    assert report.audit_status == "open_or_lifting_surface_like"
    assert report.edge_topology_observed["boundary_edge_count"] == 4
    assert report.edge_topology_observed["boundary_edge_fraction"] == 0.8
    assert report.area_evidence_observed["surface_area_to_reference_area_ratio"] == 1.0
    assert "open_boundary_edges_present" in report.engineering_findings
    assert report.next_actions[0] == (
        "localize_main_wing_open_boundary_and_nonmanifold_edges"
    )


def test_write_surface_topology_audit_report(tmp_path: Path):
    written = write_main_wing_su2_surface_topology_audit_report(
        tmp_path / "out",
        mesh_path=_write_single_sheet_msh(tmp_path / "mesh.msh"),
        reference_area_m2=1.0,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_su2_surface_topology_audit.v1"
    assert payload["audit_status"] == "open_or_lifting_surface_like"
    assert "Main Wing SU2 Surface Topology Audit v1" in markdown
