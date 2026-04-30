import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_side_aware_brep_validation_probe import (
    build_main_wing_station_seam_side_aware_brep_validation_probe_report,
    write_main_wing_station_seam_side_aware_brep_validation_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_side_aware_parametrization_probe(path: Path, step_path: Path) -> Path:
    step_path.parent.mkdir(parents=True, exist_ok=True)
    step_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_side_aware_parametrization_probe.v1",
            "probe_status": "side_aware_parametrization_candidate_materialized_needs_brep_validation",
            "target_station_y_m": [-10.5],
            "candidate_report": {
                "materialization": {
                    "step_path": str(step_path),
                },
            },
        },
    )


def _station_brep_collector(**_kwargs):
    return {
        "status": "captured",
        "target_selection": {
            "selection_mode": "station_y_geometry_on_candidate_step",
            "source_fixture_tags_replayed": False,
            "station_tolerance_m": 1.0e-4,
            "target_station_y_m": [-10.5],
            "selected_curve_tags": [7],
            "selected_surface_tags": [2],
            "station_edge_groups": [
                {
                    "station_y_m": -10.5,
                    "candidate_curve_tags": [7],
                    "owner_surface_tags": [2],
                }
            ],
        },
        "hotspot_report": {
            "status": "captured",
            "shape_valid_default": True,
            "shape_valid_exact": True,
            "selected_curve_tags": [7],
            "selected_surface_tags": [2],
            "curve_reports": [
                {
                    "curve_id": 7,
                    "mapped_edge_index": 7,
                    "owner_surface_tags": [2],
                    "ancestor_face_ids": [2],
                    "gmsh_length_3d": 0.1,
                    "edge_length_3d": 0.1,
                    "match_score": 0.0,
                    "pcurve_presence_by_face": {"2": True},
                    "check_curve3d_with_pcurve_by_face": {"2": False},
                    "check_same_parameter_by_face": {"2": False},
                    "check_vertex_tolerance_by_face": {"2": False},
                    "pcurve_range_matches_edge_range_by_face": {"2": True},
                    "same_parameter_flag": True,
                    "same_range_flag": True,
                    "brepcheck": {"valid_default": True, "valid_exact": True},
                }
            ],
            "face_reports": [
                {
                    "surface_id": 2,
                    "brepcheck": {"valid_default": True, "valid_exact": True},
                    "wire_reports": [
                        {
                            "wire_order_ok": True,
                            "wire_connected": True,
                            "wire_closed": True,
                            "wire_self_intersection": False,
                        }
                    ],
                }
            ],
        },
    }


def test_side_aware_brep_validation_reports_suspect_pcurve_without_old_tag_replay(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    side_aware_path = _write_side_aware_parametrization_probe(
        tmp_path / "side_aware.json",
        step_path,
    )

    report = build_main_wing_station_seam_side_aware_brep_validation_probe_report(
        side_aware_parametrization_probe_path=side_aware_path,
        station_brep_collector=_station_brep_collector,
    )

    assert report.probe_status == "side_aware_candidate_station_brep_edges_suspect"
    assert report.target_selection["source_fixture_tags_replayed"] is False
    assert "source_fixture_curve_surface_tags_not_replayed" in (
        report.engineering_findings
    )
    assert "side_aware_candidate_station_brep_pcurve_checks_suspect" in (
        report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "repair_side_aware_candidate_pcurve_export_before_mesh_handoff"
    )


def test_write_side_aware_brep_validation_probe_report(tmp_path: Path):
    step_path = tmp_path / "candidate_raw_dump.stp"
    side_aware_path = _write_side_aware_parametrization_probe(
        tmp_path / "side_aware.json",
        step_path,
    )

    written = write_main_wing_station_seam_side_aware_brep_validation_probe_report(
        tmp_path / "out",
        side_aware_parametrization_probe_path=side_aware_path,
        station_brep_collector=_station_brep_collector,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_side_aware_brep_validation_probe.v1"
    )
    assert (
        payload["upstream_validation_schema"]
        == "main_wing_station_seam_profile_resample_brep_validation_probe.v1"
    )
    assert "Side-Aware BRep Validation Probe v1" in markdown
