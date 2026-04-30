import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_profile_parametrization_audit import (
    build_main_wing_station_seam_profile_parametrization_audit_report,
    write_main_wing_station_seam_profile_parametrization_audit_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_csm(path: Path, *, station_y: float = 0.0) -> Path:
    lines = [
        "# profile parametrization audit fixture",
        'SET export_path $"candidate_raw_dump.stp"',
        "mark",
        f"skbeg 0 {station_y} 0",
        f"   linseg 1 {station_y} 0",
        f"   spline 1 {station_y} 1",
        f"   spline 0 {station_y} 1",
        f"   linseg 0 {station_y} 0",
        "skend",
        "rule",
        "DUMP !export_path 0 1",
        "END",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_profile_resample_report(path: Path, candidate_csm: Path, source_csm: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_profile_resample_strategy_probe.v1",
            "probe_status": "profile_resample_candidate_materialized_needs_brep_validation",
            "export_source_audit_path": str(path.parent / "export_source_audit.json"),
            "rebuild_csm_path": str(source_csm),
            "target_station_y_m": [0.0],
            "source_profile_point_counts": [4, 5, 4],
            "target_profile_point_count": 5,
            "candidate_report": {
                "candidate_profile_point_counts": [5],
                "materialization": {
                    "status": "materialized",
                    "csm_path": str(candidate_csm),
                    "step_path": str(path.parent / "candidate_raw_dump.stp"),
                },
            },
        },
    )


def _write_brep_validation_report(path: Path) -> Path:
    base_check = {
        "station_y_m": 0.0,
        "owner_surface_tags": [1, 2],
        "pcurve_presence_complete": True,
        "curve3d_with_pcurve_consistent": False,
        "same_parameter_by_face_ok": False,
        "vertex_tolerance_by_face_ok": False,
        "pcurve_range_matches_edge_range": True,
        "pcurve_checks_complete": False,
        "same_parameter_flag": True,
        "same_range_flag": True,
        "brep_valid_default": True,
        "brep_valid_exact": True,
    }
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_profile_resample_brep_validation_probe.v1",
            "probe_status": "profile_resample_candidate_station_brep_edges_suspect",
            "target_station_y_m": [0.0],
            "station_edge_checks": [
                {
                    **base_check,
                    "candidate_step_curve_tag": 10,
                    "gmsh_length_3d_m": 2.0,
                },
                {
                    **base_check,
                    "candidate_step_curve_tag": 11,
                    "gmsh_length_3d_m": 1.0,
                },
                {
                    **base_check,
                    "candidate_step_curve_tag": 12,
                    "gmsh_length_3d_m": 1.0,
                },
            ],
            "blocking_reasons": [
                "profile_resample_candidate_station_brep_pcurve_checks_suspect"
            ],
        },
    )


def test_profile_parametrization_audit_correlates_short_curves_to_terminal_linseg(
    tmp_path: Path,
):
    source_csm = _write_csm(tmp_path / "source.csm")
    candidate_csm = _write_csm(tmp_path / "candidate.csm")
    profile_path = _write_profile_resample_report(
        tmp_path / "profile_resample.json",
        candidate_csm,
        source_csm,
    )
    brep_path = _write_brep_validation_report(tmp_path / "brep_validation.json")

    report = build_main_wing_station_seam_profile_parametrization_audit_report(
        profile_resample_probe_path=profile_path,
        brep_validation_probe_path=brep_path,
    )

    assert (
        report.audit_status
        == "profile_parametrization_seam_fragment_correlation_observed"
    )
    assert report.production_default_changed is False
    assert report.candidate_profile_point_counts == [5]
    assert report.station_fragment_summary["station_count"] == 1
    station = report.target_station_correlations[0]
    assert station["terminal_linseg_match_count"] == 2
    assert station["rest_arc_match_count"] == 1
    assert station["failed_pcurve_check_count"] == 3
    assert station["segment_summary"]["first_segment_opcode"] == "linseg"
    assert station["segment_summary"]["closing_segment_opcode"] == "linseg"
    assert "station_short_curves_match_profile_terminal_linseg_segments" in (
        report.engineering_findings
    )
    assert (
        "profile_resample_candidate_parameter_consistency_fails_on_all_station_fragments"
        in report.engineering_findings
    )
    assert "profile_parametrization_export_change_needed_before_mesh_handoff" in (
        report.blocking_reasons
    )


def test_profile_parametrization_audit_blocks_when_inputs_are_missing(tmp_path: Path):
    report = build_main_wing_station_seam_profile_parametrization_audit_report(
        profile_resample_probe_path=tmp_path / "missing_profile.json",
        brep_validation_probe_path=tmp_path / "missing_brep.json",
    )

    assert report.audit_status == "blocked"
    assert "profile_resample_probe_missing" in report.blocking_reasons
    assert "brep_validation_probe_missing" in report.blocking_reasons


def test_write_profile_parametrization_audit_report(tmp_path: Path):
    source_csm = _write_csm(tmp_path / "source.csm")
    candidate_csm = _write_csm(tmp_path / "candidate.csm")
    profile_path = _write_profile_resample_report(
        tmp_path / "profile_resample.json",
        candidate_csm,
        source_csm,
    )
    brep_path = _write_brep_validation_report(tmp_path / "brep_validation.json")

    written = write_main_wing_station_seam_profile_parametrization_audit_report(
        tmp_path / "out",
        profile_resample_probe_path=profile_path,
        brep_validation_probe_path=brep_path,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_profile_parametrization_audit.v1"
    )
    assert (
        payload["audit_status"]
        == "profile_parametrization_seam_fragment_correlation_observed"
    )
    assert "Profile Parametrization Audit v1" in markdown
