import json
from pathlib import Path

from hpa_meshing.main_wing_su2_topology_defect_localization import (
    build_main_wing_su2_topology_defect_localization_report,
    write_main_wing_su2_topology_defect_localization_report,
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


def test_topology_defect_localization_reports_edge_coordinates(tmp_path: Path):
    report = build_main_wing_su2_topology_defect_localization_report(
        mesh_path=_write_single_sheet_msh(tmp_path / "mesh.msh")
    )

    assert report.localization_status == "defects_localized"
    assert report.defect_summary["boundary_edge_count"] == 4
    assert report.defect_summary["nonmanifold_edge_count"] == 0
    first = report.defect_edges[0]
    assert first["kind"] == "boundary_edge"
    assert first["use_count"] == 1
    assert first["midpoint_xyz"] == [0.5, 0.0, 0.0]
    assert first["semispan_fraction"] == 0.0
    assert report.next_actions[0] == (
        "inspect_openvsp_export_topology_at_localized_defect_span_stations"
    )


def test_write_topology_defect_localization_report(tmp_path: Path):
    written = write_main_wing_su2_topology_defect_localization_report(
        tmp_path / "out",
        mesh_path=_write_single_sheet_msh(tmp_path / "mesh.msh"),
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == (
        "main_wing_su2_topology_defect_localization.v1"
    )
    assert payload["localization_status"] == "defects_localized"
    assert "Main Wing SU2 Topology Defect Localization v1" in markdown
