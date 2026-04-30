import json
from pathlib import Path

from hpa_meshing.main_wing_gmsh_curve_station_rebuild_audit import (
    build_main_wing_gmsh_curve_station_rebuild_audit_report,
    write_main_wing_gmsh_curve_station_rebuild_audit_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_minimal_vsp3(path: Path) -> Path:
    path.write_text(
        """
        <Vsp>
          <Geom>
            <ParmContainer>
              <Name>Main Wing</Name>
              <ID>IPAWXFWPQF</ID>
            </ParmContainer>
            <XSecSurf>
              <XSec>
                <ParmContainer><XSec /></ParmContainer>
                <FileAirfoil>
                  <UpperPnts>0,0,0,1,0,0</UpperPnts>
                  <LowerPnts>0,0,0,1,0,0</LowerPnts>
                </FileAirfoil>
              </XSec>
            </XSecSurf>
          </Geom>
        </Vsp>
        """,
        encoding="utf-8",
    )
    return path


def test_curve_station_rebuild_audit_compares_curve_length_to_vsp3_profile(
    tmp_path: Path,
):
    trace_path = _write_json(
        tmp_path / "trace.json",
        {
            "trace_status": "defect_edges_traced_to_gmsh_entities",
            "station_traces": [
                {
                    "defect_station_y_m": 0.0,
                    "openvsp_station_context": {
                        "nearest_rule_section": {
                            "rule_section_index": 5,
                            "source_section_index": 0,
                            "chord": 1.0,
                        },
                        "source_section": {"source_section_index": 0},
                    },
                    "candidate_curves": [
                        {
                            "tag": 36,
                            "length": 2.0,
                            "owner_surface_tags": [12, 13],
                        }
                    ],
                }
            ],
        },
    )

    report = build_main_wing_gmsh_curve_station_rebuild_audit_report(
        gmsh_defect_entity_trace_path=trace_path,
        source_vsp3_path=_write_minimal_vsp3(tmp_path / "main_wing.vsp3"),
    )

    assert report.curve_station_rebuild_status == (
        "curve_tags_match_vsp3_section_profile_scale"
    )
    assert report.curve_matches[0]["curve_tag"] == 36
    assert report.curve_matches[0]["source_section_index"] == 0
    assert report.curve_matches[0]["relative_length_delta"] == 0.0
    assert "curve_tags_match_vsp3_section_profile_scale" in report.engineering_findings
    assert report.next_actions[0] == "build_minimal_openvsp_section_station_topology_fixture"


def test_write_curve_station_rebuild_audit_report(tmp_path: Path):
    trace_path = _write_json(
        tmp_path / "trace.json",
        {
            "trace_status": "no_defect_edges",
            "station_traces": [],
        },
    )

    written = write_main_wing_gmsh_curve_station_rebuild_audit_report(
        tmp_path / "out",
        gmsh_defect_entity_trace_path=trace_path,
        source_vsp3_path=_write_minimal_vsp3(tmp_path / "main_wing.vsp3"),
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_gmsh_curve_station_rebuild_audit.v1"
    assert payload["curve_station_rebuild_status"] == "no_candidate_curves"
    assert "Main Wing Gmsh Curve Station Rebuild Audit v1" in markdown
