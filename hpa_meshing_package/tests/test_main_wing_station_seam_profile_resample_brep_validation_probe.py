import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_profile_resample_brep_validation_probe import (
    build_main_wing_station_seam_profile_resample_brep_validation_probe_report,
    write_main_wing_station_seam_profile_resample_brep_validation_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_profile_resample_report(path: Path, step_path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_profile_resample_strategy_probe.v1",
            "probe_status": "profile_resample_candidate_materialized_needs_brep_validation",
            "target_station_y_m": [-10.5, 13.5],
            "candidate_report": {
                "candidate": "uniform_profile_resample_single_rule",
                "materialization_status": "materialized",
                "body_count": 1,
                "volume_count": 1,
                "span_y_bounds_preserved": True,
                "materialization": {
                    "status": "materialized",
                    "step_path": str(step_path),
                },
            },
        },
    )


def _valid_candidate_station_collector(**kwargs):
    assert kwargs["station_y_targets"] == [-10.5, 13.5]
    assert kwargs["scale_to_output_units"] == 1.0
    assert "requested_curve_tags" not in kwargs
    assert "requested_surface_tags" not in kwargs
    return {
        "status": "captured",
        "target_selection": {
            "selection_mode": "station_y_geometry_on_candidate_step",
            "source_fixture_tags_replayed": False,
            "selected_curve_tags": [7, 28],
            "selected_surface_tags": [2, 3, 9, 10],
            "station_edge_groups": [
                {
                    "station_y_m": -10.5,
                    "candidate_curve_tags": [7],
                    "owner_surface_tags": [2, 3],
                },
                {
                    "station_y_m": 13.5,
                    "candidate_curve_tags": [28],
                    "owner_surface_tags": [9, 10],
                },
            ],
        },
        "hotspot_report": {
            "status": "captured",
            "shape_valid_default": True,
            "shape_valid_exact": True,
            "scale_to_output_units": 1.0,
            "selected_curve_tags": [7, 28],
            "selected_surface_tags": [2, 3, 9, 10],
            "curve_reports": [
                {
                    "curve_id": 7,
                    "owner_surface_tags": [2, 3],
                    "gmsh_length_3d": 0.037,
                    "edge_length_3d": 0.037000001,
                    "match_score": 0.0,
                    "mapped_edge_index": 7,
                    "ancestor_face_ids": [2, 3],
                    "pcurve_presence_by_face": {"2": True, "3": True},
                    "check_curve3d_with_pcurve_by_face": {"2": True, "3": True},
                    "check_same_parameter_by_face": {"2": True, "3": True},
                    "check_vertex_tolerance_by_face": {"2": True, "3": True},
                    "pcurve_range_matches_edge_range_by_face": {"2": True, "3": True},
                    "same_parameter_flag": True,
                    "same_range_flag": True,
                    "brepcheck": {"valid_default": True, "valid_exact": True},
                },
                {
                    "curve_id": 28,
                    "owner_surface_tags": [9, 10],
                    "gmsh_length_3d": 0.029,
                    "edge_length_3d": 0.029000001,
                    "match_score": 0.0,
                    "mapped_edge_index": 28,
                    "ancestor_face_ids": [9, 10],
                    "pcurve_presence_by_face": {"9": True, "10": True},
                    "check_curve3d_with_pcurve_by_face": {"9": True, "10": True},
                    "check_same_parameter_by_face": {"9": True, "10": True},
                    "check_vertex_tolerance_by_face": {"9": True, "10": True},
                    "pcurve_range_matches_edge_range_by_face": {"9": True, "10": True},
                    "same_parameter_flag": True,
                    "same_range_flag": True,
                    "brepcheck": {"valid_default": True, "valid_exact": True},
                },
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
                },
                {
                    "surface_id": 3,
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
        },
    }


def test_profile_resample_brep_validation_uses_candidate_station_geometry_not_old_tags(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    report = build_main_wing_station_seam_profile_resample_brep_validation_probe_report(
        profile_resample_probe_path=_write_profile_resample_report(
            tmp_path / "profile_resample.json",
            step_path,
        ),
        station_brep_collector=_valid_candidate_station_collector,
    )

    assert (
        report.probe_status
        == "profile_resample_candidate_station_brep_edges_valid"
    )
    assert report.production_default_changed is False
    assert report.target_selection["source_fixture_tags_replayed"] is False
    assert report.target_selection["selected_curve_tags"] == [7, 28]
    assert report.station_edge_checks[0]["candidate_step_curve_tag"] == 7
    assert report.station_edge_checks[0]["pcurve_checks_complete"] is True
    assert "candidate_station_edges_geometrically_selected" in (
        report.engineering_findings
    )
    assert "profile_resample_candidate_mesh_handoff_not_run" in report.blocking_reasons


def test_profile_resample_brep_validation_reports_suspect_candidate_checks(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")

    def _suspect_collector(**kwargs):
        payload = _valid_candidate_station_collector(**kwargs)
        curve = payload["hotspot_report"]["curve_reports"][0]
        curve["check_same_parameter_by_face"] = {"2": False, "3": False}
        return payload

    report = build_main_wing_station_seam_profile_resample_brep_validation_probe_report(
        profile_resample_probe_path=_write_profile_resample_report(
            tmp_path / "profile_resample.json",
            step_path,
        ),
        station_brep_collector=_suspect_collector,
    )

    assert (
        report.probe_status
        == "profile_resample_candidate_station_brep_edges_suspect"
    )
    assert (
        "profile_resample_candidate_station_brep_pcurve_checks_suspect"
        in report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "repair_profile_resample_candidate_pcurve_export_before_mesh_handoff"
    )


def test_write_profile_resample_brep_validation_report(tmp_path: Path):
    step_path = tmp_path / "candidate_raw_dump.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    written = write_main_wing_station_seam_profile_resample_brep_validation_probe_report(
        tmp_path / "out",
        profile_resample_probe_path=_write_profile_resample_report(
            tmp_path / "profile_resample.json",
            step_path,
        ),
        station_brep_collector=_valid_candidate_station_collector,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_profile_resample_brep_validation_probe.v1"
    )
    assert (
        payload["probe_status"]
        == "profile_resample_candidate_station_brep_edges_valid"
    )
    assert "Profile Resample BRep Validation Probe v1" in markdown
