import json
from pathlib import Path

from hpa_meshing.main_wing_openvsp_section_station_topology_fixture import (
    build_main_wing_openvsp_section_station_topology_fixture_report,
    write_main_wing_openvsp_section_station_topology_fixture_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_station_trace(path: Path) -> Path:
    return _write_json(
        path,
        {
            "trace_status": "defect_edges_traced_to_gmsh_entities",
            "edge_traces": [
                {
                    "kind": "nonmanifold_edge",
                    "nodes": [251, 253],
                    "mesh_reported_use_count": 3,
                    "adjacent_surface_triangle_count": 3,
                    "adjacent_entity_tags": [12, 12, 13],
                    "unique_adjacent_entity_tags": [12, 13],
                    "openvsp_station_context": {
                        "defect_station_y_m": -10.5,
                        "nearest_rule_section": {
                            "source_section_index": 3,
                            "chord": 1.04,
                        },
                    },
                },
                {
                    "kind": "boundary_edge",
                    "nodes": [252, 253],
                    "mesh_reported_use_count": 1,
                    "adjacent_surface_triangle_count": 1,
                    "adjacent_entity_tags": [12],
                    "unique_adjacent_entity_tags": [12],
                    "openvsp_station_context": {
                        "defect_station_y_m": -10.5,
                    },
                },
                {
                    "kind": "boundary_edge",
                    "nodes": [251, 252],
                    "mesh_reported_use_count": 1,
                    "adjacent_surface_triangle_count": 1,
                    "adjacent_entity_tags": [12],
                    "unique_adjacent_entity_tags": [12],
                    "openvsp_station_context": {
                        "defect_station_y_m": -10.5,
                    },
                },
            ],
            "station_traces": [
                {
                    "defect_station_y_m": -10.5,
                    "candidate_curve_tags": [36],
                    "candidate_curves": [
                        {
                            "tag": 36,
                            "length": 2.136,
                            "owner_surface_tags": [12, 13],
                        }
                    ],
                    "openvsp_station_context": {
                        "nearest_rule_section": {
                            "source_section_index": 3,
                            "chord": 1.04,
                        },
                    },
                }
            ],
        },
    )


def _write_curve_audit(path: Path) -> Path:
    return _write_json(
        path,
        {
            "curve_station_rebuild_status": (
                "curve_tags_match_vsp3_section_profile_scale"
            ),
            "curve_matches": [
                {
                    "curve_tag": 36,
                    "defect_station_y_m": -10.5,
                    "source_section_index": 3,
                    "station_chord_m": 1.04,
                    "relative_length_delta": -0.01,
                    "within_tolerance": True,
                    "candidate_curve": {
                        "owner_surface_tags": [12, 13],
                    },
                }
            ],
        },
    )


def test_section_station_topology_fixture_materializes_real_defect_signature(
    tmp_path: Path,
):
    report = build_main_wing_openvsp_section_station_topology_fixture_report(
        gmsh_defect_entity_trace_path=_write_station_trace(tmp_path / "trace.json"),
        gmsh_curve_station_rebuild_audit_path=_write_curve_audit(
            tmp_path / "curve.json"
        ),
    )

    assert report.topology_fixture_status == "real_defect_station_fixture_materialized"
    assert report.fixture_summary["station_fixture_count"] == 1
    assert report.fixture_summary["total_boundary_edge_count"] == 2
    assert report.fixture_summary["total_nonmanifold_edge_count"] == 1
    assert report.fixture_summary["candidate_curve_tags"] == [36]
    case = report.station_fixture_cases[0]
    assert case["defect_station_y_m"] == -10.5
    assert case["source_section_index"] == 3
    assert case["observed_defect_signature"]["edge_kind_counts"] == {
        "boundary": 2,
        "nonmanifold": 1,
    }
    assert case["canonical_station_topology_contract"][
        "expected_boundary_edge_count"
    ] == 0
    assert case["canonical_station_topology_contract"][
        "expected_nonmanifold_edge_count"
    ] == 0
    assert case["canonical_station_topology_contract"][
        "current_signature_violates_contract"
    ] is True
    assert "real_defect_station_topology_fixture_materialized" in (
        report.engineering_findings
    )
    assert report.next_actions[0] == (
        "decide_station_seam_repair_before_solver_iteration_budget"
    )


def test_write_section_station_topology_fixture_report(tmp_path: Path):
    written = write_main_wing_openvsp_section_station_topology_fixture_report(
        tmp_path / "out",
        gmsh_defect_entity_trace_path=_write_station_trace(tmp_path / "trace.json"),
        gmsh_curve_station_rebuild_audit_path=_write_curve_audit(
            tmp_path / "curve.json"
        ),
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == (
        "main_wing_openvsp_section_station_topology_fixture.v1"
    )
    assert payload["production_default_changed"] is False
    assert "Main Wing OpenVSP Section Station Topology Fixture v1" in markdown
