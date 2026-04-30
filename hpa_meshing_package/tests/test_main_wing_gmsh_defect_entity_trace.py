import json
from pathlib import Path

from hpa_meshing.main_wing_gmsh_defect_entity_trace import (
    build_main_wing_gmsh_defect_entity_trace_report,
    write_main_wing_gmsh_defect_entity_trace_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_trace_fixture_msh(path: Path) -> Path:
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
                "0 0 2 0",
                "12 0 0 0 1 1 0 1 2 0",
                "13 0 0 0 1 1 0 1 2 0",
                "$EndEntities",
                "$Nodes",
                "1 4 1 4",
                "2 12 0 4",
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
                "2 3 1 3",
                "2 12 2 2",
                "101 1 2 3",
                "102 1 4 2",
                "2 13 2 1",
                "201 2 1 4",
                "$EndElements",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_gmsh_defect_entity_trace_records_adjacent_entities(tmp_path: Path):
    defect_path = _write_json(
        tmp_path / "defects.json",
        {
            "localization_status": "defects_localized",
            "defect_edges": [
                {
                    "kind": "nonmanifold_edge",
                    "nodes": [1, 2],
                    "use_count": 3,
                    "midpoint_xyz": [0.5, 0.0, 0.0],
                },
                {
                    "kind": "boundary_edge",
                    "nodes": [2, 3],
                    "use_count": 1,
                    "midpoint_xyz": [1.0, 0.5, 0.0],
                },
            ],
            "station_summary": [
                {"station_y_m": 0.0, "defect_count": 2},
            ],
        },
    )
    station_path = _write_json(
        tmp_path / "station_audit.json",
        {
            "station_alignment_status": (
                "defect_stations_aligned_to_openvsp_rule_sections"
            ),
            "station_mappings": [
                {
                    "defect_station_y_m": 0.0,
                    "nearest_rule_section": {
                        "rule_section_index": 5,
                        "source_section_index": 0,
                        "side": "center_or_start",
                    },
                }
            ],
        },
    )
    patch_path = _write_json(
        tmp_path / "surface_patch_diagnostics.json",
        {
            "surface_records": [
                {"tag": 12, "area": 1.0, "curve_tags": [36], "bbox": {"y_min": 0.0, "y_max": 1.0}},
                {"tag": 13, "area": 1.0, "curve_tags": [36], "bbox": {"y_min": -1.0, "y_max": 0.0}},
            ],
            "curve_records": [
                {
                    "tag": 36,
                    "owner_surface_tags": [12, 13],
                    "bbox": {"y_min": 0.0, "y_max": 0.0},
                    "length": 1.0,
                }
            ],
        },
    )

    report = build_main_wing_gmsh_defect_entity_trace_report(
        mesh_path=_write_trace_fixture_msh(tmp_path / "mesh.msh"),
        defect_localization_path=defect_path,
        openvsp_station_audit_path=station_path,
        surface_patch_diagnostics_path=patch_path,
    )

    assert report.trace_status == "defect_edges_traced_to_gmsh_entities"
    assert report.trace_summary["defect_edge_count"] == 2
    assert report.trace_summary["involved_surface_entity_tags"] == [12, 13]
    assert report.edge_traces[0]["adjacent_entity_tags"] == [12, 12, 13]
    assert report.edge_traces[0]["adjacent_elements"][0]["element_id"] == 101
    assert report.edge_traces[1]["adjacent_entity_tags"] == [12]
    assert report.station_traces[0]["candidate_curve_tags"] == [36]
    assert "defect_edges_traced_to_gmsh_surface_entities" in report.engineering_findings
    assert report.next_actions[0] == "inspect_gmsh_curve_tags_36_against_openvsp_section_rebuild"


def test_write_gmsh_defect_entity_trace_report(tmp_path: Path):
    defect_path = _write_json(
        tmp_path / "defects.json",
        {"localization_status": "no_defects", "defect_edges": [], "station_summary": []},
    )
    station_path = _write_json(tmp_path / "station_audit.json", {"station_mappings": []})
    patch_path = _write_json(tmp_path / "surface_patch_diagnostics.json", {})

    written = write_main_wing_gmsh_defect_entity_trace_report(
        tmp_path / "out",
        mesh_path=_write_trace_fixture_msh(tmp_path / "mesh.msh"),
        defect_localization_path=defect_path,
        openvsp_station_audit_path=station_path,
        surface_patch_diagnostics_path=patch_path,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_gmsh_defect_entity_trace.v1"
    assert payload["trace_status"] == "no_defect_edges"
    assert "Main Wing Gmsh Defect Entity Trace v1" in markdown
