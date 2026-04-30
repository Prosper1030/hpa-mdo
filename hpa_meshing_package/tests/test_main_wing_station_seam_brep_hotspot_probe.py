import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_brep_hotspot_probe import (
    build_main_wing_station_seam_brep_hotspot_probe_report,
    write_main_wing_station_seam_brep_hotspot_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_fixture(path: Path) -> Path:
    return _write_json(
        path,
        {
            "topology_fixture_status": "real_defect_station_fixture_materialized",
            "fixture_summary": {
                "station_fixture_count": 2,
                "total_boundary_edge_count": 4,
                "total_nonmanifold_edge_count": 2,
                "candidate_curve_tags": [36, 50],
                "owner_surface_entity_tags": [12, 13, 19, 20],
                "source_section_indices": [3, 4],
            },
            "station_fixture_cases": [
                {
                    "defect_station_y_m": -10.5,
                    "source_section_index": 3,
                    "candidate_curve_tags": [36],
                    "owner_surface_entity_tags": [12, 13],
                },
                {
                    "defect_station_y_m": 13.5,
                    "source_section_index": 4,
                    "candidate_curve_tags": [50],
                    "owner_surface_entity_tags": [19, 20],
                },
            ],
        },
    )


def _write_real_mesh_probe(path: Path, step_path: Path, diagnostics_path: Path) -> Path:
    return _write_json(
        path,
        {
            "probe_status": "mesh_handoff_pass",
            "normalized_geometry_path": str(step_path),
            "surface_patch_diagnostics_path": str(diagnostics_path),
        },
    )


def _fake_surface_patch_diagnostics() -> dict:
    return {
        "status": "available",
        "curve_records": [
            {"tag": 36, "length": 2.136, "owner_surface_tags": [12, 13]},
            {"tag": 50, "length": 1.684, "owner_surface_tags": [19, 20]},
        ],
        "surface_records": [
            {"tag": 12, "curve_tags": [6, 34, 35, 36]},
            {"tag": 13, "curve_tags": [9, 36, 37, 38]},
            {"tag": 19, "curve_tags": [27, 48, 49, 50]},
            {"tag": 20, "curve_tags": [30, 50, 51, 52]},
        ],
    }


def _fake_captured_hotspot(**kwargs):
    assert kwargs["requested_curve_tags"] == [36, 50]
    assert kwargs["requested_surface_tags"] == [12, 13, 19, 20]
    assert kwargs["scale_to_output_units"] == 0.001
    return {
        "status": "captured",
        "shape_valid_default": True,
        "shape_valid_exact": True,
        "selected_curve_tags": [36, 50],
        "selected_surface_tags": [12, 13, 19, 20],
        "curve_reports": [
            {
                "curve_id": 36,
                "owner_surface_tags": [12, 13],
                "gmsh_length_3d": 2.136,
                "edge_length_3d": 2.13600001,
                "match_score": 1.0e-7,
                "mapped_edge_index": 9,
                "ancestor_face_ids": [12, 13],
                "pcurve_presence_by_face": {"12": True, "13": True},
                "check_curve3d_with_pcurve_by_face": {"12": True, "13": True},
                "check_same_parameter_by_face": {"12": True, "13": True},
                "check_vertex_tolerance_by_face": {"12": True, "13": True},
                "pcurve_range_matches_edge_range_by_face": {"12": True, "13": True},
                "same_parameter_flag": True,
                "same_range_flag": True,
                "brepcheck": {"valid_default": True, "valid_exact": True},
            },
            {
                "curve_id": 50,
                "owner_surface_tags": [19, 20],
                "gmsh_length_3d": 1.684,
                "edge_length_3d": 1.68400001,
                "match_score": 1.0e-7,
                "mapped_edge_index": 37,
                "ancestor_face_ids": [19, 20],
                "pcurve_presence_by_face": {"19": True, "20": True},
                "check_curve3d_with_pcurve_by_face": {"19": True, "20": True},
                "check_same_parameter_by_face": {"19": True, "20": True},
                "check_vertex_tolerance_by_face": {"19": True, "20": True},
                "pcurve_range_matches_edge_range_by_face": {"19": True, "20": True},
                "same_parameter_flag": True,
                "same_range_flag": True,
                "brepcheck": {"valid_default": True, "valid_exact": True},
            },
        ],
        "face_reports": [
            {
                "surface_id": 12,
                "brepcheck": {"valid_default": True, "valid_exact": True},
                "wire_reports": [
                    {
                        "wire_order_ok": True,
                        "wire_connected": True,
                        "wire_closed": True,
                        "wire_self_intersection": False,
                    }
                ],
            },
            {
                "surface_id": 13,
                "brepcheck": {"valid_default": True, "valid_exact": True},
                "wire_reports": [
                    {
                        "wire_order_ok": True,
                        "wire_connected": True,
                        "wire_closed": True,
                        "wire_self_intersection": False,
                    }
                ],
            },
        ],
    }


def test_station_seam_brep_hotspot_probe_keeps_valid_brep_separate_from_mesh_blocker(
    tmp_path: Path,
):
    step_path = tmp_path / "normalized.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    diagnostics_path = _write_json(
        tmp_path / "surface_patch_diagnostics.json",
        _fake_surface_patch_diagnostics(),
    )
    report = build_main_wing_station_seam_brep_hotspot_probe_report(
        topology_fixture_path=_write_fixture(tmp_path / "fixture.json"),
        real_mesh_probe_report_path=_write_real_mesh_probe(
            tmp_path / "mesh_probe.json",
            step_path,
            diagnostics_path,
        ),
        hotspot_report_collector=_fake_captured_hotspot,
    )

    assert report.probe_status == "brep_hotspot_captured_station_edges_valid"
    assert report.production_default_changed is False
    assert report.station_fixture_observed["candidate_curve_tags"] == [36, 50]
    assert report.brep_hotspot_summary["shape_valid_exact"] is True
    assert report.curve_checks[0]["pcurve_checks_complete"] is True
    assert "station_fixture_failure_not_explained_by_missing_brep_pcurves" in (
        report.engineering_findings
    )
    assert report.prototype_candidates[0]["prototype_status"] == "prototype_not_applied"
    assert report.next_actions[0] == (
        "prototype_station_owner_surface_compound_meshing_policy_against_fixture"
    )
    assert any("does not run SU2_CFD" in item for item in report.limitations)


def test_write_station_seam_brep_hotspot_probe_report(tmp_path: Path):
    step_path = tmp_path / "normalized.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    diagnostics_path = _write_json(
        tmp_path / "surface_patch_diagnostics.json",
        _fake_surface_patch_diagnostics(),
    )
    written = write_main_wing_station_seam_brep_hotspot_probe_report(
        tmp_path / "out",
        topology_fixture_path=_write_fixture(tmp_path / "fixture.json"),
        real_mesh_probe_report_path=_write_real_mesh_probe(
            tmp_path / "mesh_probe.json",
            step_path,
            diagnostics_path,
        ),
        hotspot_report_collector=_fake_captured_hotspot,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_station_seam_brep_hotspot_probe.v1"
    assert payload["probe_status"] == "brep_hotspot_captured_station_edges_valid"
    assert "Main Wing Station Seam BRep Hotspot Probe v1" in markdown
