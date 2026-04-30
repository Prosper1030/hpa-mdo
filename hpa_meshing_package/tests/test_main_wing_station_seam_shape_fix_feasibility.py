import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_shape_fix_feasibility import (
    build_main_wing_station_seam_shape_fix_feasibility_report,
    write_main_wing_station_seam_shape_fix_feasibility_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_same_parameter_report(path: Path, step_path: Path) -> Path:
    return _write_json(
        path,
        {
            "feasibility_status": "same_parameter_repair_not_recovered",
            "normalized_step_path": str(step_path),
            "requested_curve_tags": [36, 50],
            "requested_surface_tags": [12, 13, 19, 20],
            "target_edges": [
                {"curve_id": 36, "edge_index": 36, "face_ids": [12, 13]},
                {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]},
            ],
        },
    )


def _baseline_checks():
    return [
        {
            "curve_id": 36,
            "edge_index": 36,
            "same_parameter_flag": True,
            "edge_tolerance": 1e-7,
            "face_checks": [
                {
                    "face_id": 12,
                    "has_pcurve": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                },
                {
                    "face_id": 13,
                    "has_pcurve": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                },
            ],
        }
    ]


def _fake_runner(**kwargs):
    assert kwargs["step_path"].name == "normalized.stp"
    assert kwargs["target_edges"] == [
        {"curve_id": 36, "edge_index": 36, "face_ids": [12, 13]},
        {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]},
    ]
    assert kwargs["tolerances"] == [1e-7, 1e-6, 1e-5, 0.0001, 0.001]
    assert "fix_same_parameter_edge" in kwargs["operations"]
    baseline = _baseline_checks()
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline,
        "repair_attempts": [
            {
                "operation": operation,
                "tolerance": tolerance,
                "recovered": False,
                "operation_results": [
                    {
                        "curve_id": 36,
                        "edge_index": 36,
                        "face_operations": [
                            {
                                "label": operation,
                                "called": True,
                                "result": False,
                                "error": None,
                            }
                        ],
                    }
                ],
                "checks": baseline,
            }
            for tolerance in kwargs["tolerances"]
            for operation in kwargs["operations"]
        ],
    }


def test_shape_fix_feasibility_reports_not_recovered(tmp_path: Path):
    step_path = tmp_path / "normalized.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    report = build_main_wing_station_seam_shape_fix_feasibility_report(
        same_parameter_feasibility_path=_write_same_parameter_report(
            tmp_path / "same_parameter.json",
            step_path,
        ),
        feasibility_runner=_fake_runner,
    )

    assert report.feasibility_status == "shape_fix_repair_not_recovered"
    assert report.production_default_changed is False
    assert report.baseline_summary["all_target_pcurves_present"] is True
    assert report.baseline_summary["all_station_checks_pass"] is False
    assert report.attempt_summary["recovered_attempt_count"] == 0
    assert "shape_fix_edge_did_not_recover_station_curve_checks" in (
        report.engineering_findings
    )
    assert report.next_actions[0] == (
        "rebuild_station_pcurves_or_export_station_seams_before_meshing_policy"
    )


def test_write_shape_fix_feasibility_report(tmp_path: Path):
    step_path = tmp_path / "normalized.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    written = write_main_wing_station_seam_shape_fix_feasibility_report(
        tmp_path / "out",
        same_parameter_feasibility_path=_write_same_parameter_report(
            tmp_path / "same_parameter.json",
            step_path,
        ),
        feasibility_runner=_fake_runner,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_shape_fix_feasibility.v1"
    )
    assert payload["feasibility_status"] == "shape_fix_repair_not_recovered"
    assert "Main Wing Station Seam ShapeFix Feasibility v1" in markdown
