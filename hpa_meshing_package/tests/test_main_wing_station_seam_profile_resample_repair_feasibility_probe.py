import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_profile_resample_repair_feasibility_probe import (
    build_main_wing_station_seam_profile_resample_repair_feasibility_probe_report,
    write_main_wing_station_seam_profile_resample_repair_feasibility_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_validation_report(path: Path, step_path: Path) -> Path:
    return _write_json(
        path,
        {
            "probe_status": "profile_resample_candidate_station_brep_edges_suspect",
            "candidate_step_path": str(step_path),
            "station_edge_checks": [
                {
                    "station_y_m": -10.5,
                    "candidate_step_curve_tag": 36,
                    "candidate_step_edge_index": 36,
                    "ancestor_face_ids": [12, 13],
                    "pcurve_checks_complete": False,
                },
                {
                    "station_y_m": 13.5,
                    "candidate_step_curve_tag": 50,
                    "candidate_step_edge_index": 50,
                    "ancestor_face_ids": [19, 20],
                    "pcurve_checks_complete": False,
                },
            ],
        },
    )


def _baseline_checks():
    return [
        {
            "curve_id": 36,
            "edge_index": 36,
            "same_parameter_flag": True,
            "same_range_flag": True,
            "face_checks": [
                {
                    "face_id": 12,
                    "has_pcurve": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                }
            ],
        }
    ]


def _fake_runner(**kwargs):
    assert kwargs["step_path"].name == "candidate_raw_dump.stp"
    assert kwargs["target_edges"] == [
        {"curve_id": 36, "edge_index": 36, "face_ids": [12, 13]},
        {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]},
    ]
    assert kwargs["tolerances"] == [1e-7, 1e-6, 1e-5, 0.0001, 0.001]
    baseline = _baseline_checks()
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline,
        "repair_attempts": [
            {
                "operation": operation,
                "tolerance": tolerance,
                "recovered": False,
                "operation_results": [],
                "checks": baseline,
            }
            for tolerance in kwargs["tolerances"]
            for operation in kwargs["operations"]
        ],
    }


def test_profile_resample_repair_feasibility_reports_not_recovered(tmp_path: Path):
    step_path = tmp_path / "candidate_raw_dump.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    report = build_main_wing_station_seam_profile_resample_repair_feasibility_probe_report(
        brep_validation_probe_path=_write_validation_report(
            tmp_path / "brep_validation.json",
            step_path,
        ),
        feasibility_runner=_fake_runner,
    )

    assert (
        report.feasibility_status
        == "profile_resample_station_shape_fix_repair_not_recovered"
    )
    assert report.production_default_changed is False
    assert report.target_edges[0]["curve_id"] == 36
    assert report.attempt_summary["recovered_attempt_count"] == 0
    assert "profile_resample_station_shape_fix_did_not_recover_candidate_checks" in (
        report.engineering_findings
    )
    assert report.next_actions[0] == (
        "change_profile_resample_export_pcurve_generation_or_section_parametrization"
    )


def test_write_profile_resample_repair_feasibility_report(tmp_path: Path):
    step_path = tmp_path / "candidate_raw_dump.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    written = (
        write_main_wing_station_seam_profile_resample_repair_feasibility_probe_report(
            tmp_path / "out",
            brep_validation_probe_path=_write_validation_report(
                tmp_path / "brep_validation.json",
                step_path,
            ),
            feasibility_runner=_fake_runner,
        )
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_profile_resample_repair_feasibility_probe.v1"
    )
    assert (
        payload["feasibility_status"]
        == "profile_resample_station_shape_fix_repair_not_recovered"
    )
    assert "Profile Resample Repair Feasibility Probe v1" in markdown
