import json
from pathlib import Path

from hpa_meshing.main_wing_openvsp_defect_station_audit import (
    build_main_wing_openvsp_defect_station_audit_report,
    write_main_wing_openvsp_defect_station_audit_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_minimal_vsp3(path: Path) -> Path:
    xsecs = []
    for index in range(5):
        xsecs.append(
            f"""
            <XSec>
              <ParmContainer>
                <XSec>
                  <Span Value=\"{index + 1}.0\"/>
                  <Root_Chord Value=\"{1.3 - index * 0.1}\"/>
                  <Tip_Chord Value=\"{1.2 - index * 0.1}\"/>
                  <SectTess_U Value=\"{10 + index}\"/>
                  <Sweep Value=\"{index * 0.25}\"/>
                  <Dihedral Value=\"{index * 0.5}\"/>
                  <Twist Value=\"0.0\"/>
                </XSec>
              </ParmContainer>
            </XSec>
            """
        )
    path.write_text(
        f"""
        <Vsp>
          <Geom>
            <ParmContainer>
              <Name>Main Wing</Name>
              <ID>IPAWXFWPQF</ID>
            </ParmContainer>
            <XSecSurf>{''.join(xsecs)}</XSecSurf>
          </Geom>
        </Vsp>
        """,
        encoding="utf-8",
    )
    return path


def test_openvsp_defect_station_audit_maps_defects_to_rule_sections(tmp_path: Path):
    defect_path = _write_json(
        tmp_path / "defects.json",
        {
            "localization_status": "defects_localized",
            "defect_summary": {
                "boundary_edge_count": 4,
                "nonmanifold_edge_count": 2,
                "station_count": 2,
            },
            "station_summary": [
                {
                    "station_y_m": -10.5,
                    "defect_count": 3,
                    "defect_kind_counts": {
                        "boundary_edge": 2,
                        "nonmanifold_edge": 1,
                    },
                },
                {
                    "station_y_m": 13.5,
                    "defect_count": 3,
                    "defect_kind_counts": {
                        "boundary_edge": 2,
                        "nonmanifold_edge": 1,
                    },
                },
            ],
        },
    )
    topology_path = _write_json(
        tmp_path / "topology_lineage_report.json",
        {
            "surfaces": [
                {
                    "component": "main_wing",
                    "rule_sections": [
                        {
                            "rule_section_index": 2,
                            "source_section_index": 3,
                            "mirrored": True,
                            "side": "left_span",
                            "x_le": 0.0575,
                            "y_le": -10.5,
                            "z_le": 0.338,
                            "chord": 1.04,
                        },
                        {
                            "rule_section_index": 9,
                            "source_section_index": 4,
                            "mirrored": False,
                            "side": "right_span",
                            "x_le": 0.1182,
                            "y_le": 13.5,
                            "z_le": 0.5449,
                            "chord": 0.83,
                        },
                    ],
                }
            ]
        },
    )
    report = build_main_wing_openvsp_defect_station_audit_report(
        defect_localization_path=defect_path,
        topology_lineage_path=topology_path,
        source_vsp3_path=_write_minimal_vsp3(tmp_path / "main_wing.vsp3"),
    )

    assert report.station_alignment_status == (
        "defect_stations_aligned_to_openvsp_rule_sections"
    )
    assert report.alignment_summary["defect_station_count"] == 2
    assert report.alignment_summary["exact_rule_section_match_count"] == 2
    assert report.station_mappings[0]["defect_station_y_m"] == -10.5
    assert report.station_mappings[0]["nearest_rule_section"]["source_section_index"] == 3
    assert report.station_mappings[0]["source_section"]["sect_tess_u"] == 13.0
    assert report.station_mappings[1]["nearest_rule_section"]["side"] == "right_span"
    assert "defect_stations_align_with_openvsp_rule_sections" in report.engineering_findings
    assert report.next_actions[0] == (
        "trace_defect_edges_to_gmsh_entities_at_openvsp_section_stations"
    )


def test_write_openvsp_defect_station_audit_report(tmp_path: Path):
    defect_path = _write_json(
        tmp_path / "defects.json",
        {
            "localization_status": "no_defects",
            "station_summary": [],
        },
    )
    topology_path = _write_json(tmp_path / "topology_lineage_report.json", {"surfaces": []})

    written = write_main_wing_openvsp_defect_station_audit_report(
        tmp_path / "out",
        defect_localization_path=defect_path,
        topology_lineage_path=topology_path,
        source_vsp3_path=_write_minimal_vsp3(tmp_path / "main_wing.vsp3"),
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_openvsp_defect_station_audit.v1"
    assert payload["station_alignment_status"] == "no_defect_stations"
    assert "Main Wing OpenVSP Defect Station Audit v1" in markdown
