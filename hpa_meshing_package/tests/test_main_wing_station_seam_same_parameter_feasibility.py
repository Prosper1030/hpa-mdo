import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_same_parameter_feasibility import (
    build_main_wing_station_seam_same_parameter_feasibility_report,
    write_main_wing_station_seam_same_parameter_feasibility_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_brep_hotspot_probe(path: Path, step_path: Path) -> Path:
    return _write_json(
        path,
        {
            "probe_status": "brep_hotspot_captured_station_edges_suspect",
            "normalized_step_path": str(step_path),
            "requested_curve_tags": [36, 50],
            "requested_surface_tags": [12, 13, 19, 20],
            "curve_checks": [
                {
                    "curve_id": 36,
                    "mapped_edge_index": 36,
                    "owner_surface_tags": [12, 13],
                },
                {
                    "curve_id": 50,
                    "mapped_edge_index": 50,
                    "owner_surface_tags": [19, 20],
                },
            ],
        },
    )


def _fake_runner(**kwargs):
    assert kwargs["step_path"].name == "normalized.stp"
    assert kwargs["target_edges"] == [
        {"curve_id": 36, "edge_index": 36, "face_ids": [12, 13]},
        {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]},
    ]
    assert kwargs["tolerances"] == [1e-7, 1e-6, 1e-5, 0.0001, 0.001]
    baseline = [
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
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline,
        "repair_attempts": [
            {
                "tolerance": tolerance,
                "recovered": False,
                "checks": baseline,
            }
            for tolerance in kwargs["tolerances"]
        ],
    }


def test_same_parameter_feasibility_reports_not_recovered(tmp_path: Path):
    step_path = tmp_path / "normalized.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    report = build_main_wing_station_seam_same_parameter_feasibility_report(
        brep_hotspot_probe_path=_write_brep_hotspot_probe(
            tmp_path / "brep_hotspot.json",
            step_path,
        ),
        feasibility_runner=_fake_runner,
    )

    assert report.feasibility_status == "same_parameter_repair_not_recovered"
    assert report.production_default_changed is False
    assert report.baseline_summary["all_target_pcurves_present"] is True
    assert report.baseline_summary["all_same_parameter_checks_pass"] is False
    assert report.attempt_summary["recovered_attempt_count"] == 0
    assert "breplib_same_parameter_did_not_recover_station_curve_checks" in (
        report.engineering_findings
    )
    assert report.next_actions[0] == (
        "inspect_or_rebuild_station_pcurves_before_compound_meshing_policy"
    )


def test_write_same_parameter_feasibility_report(tmp_path: Path):
    step_path = tmp_path / "normalized.stp"
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    written = write_main_wing_station_seam_same_parameter_feasibility_report(
        tmp_path / "out",
        brep_hotspot_probe_path=_write_brep_hotspot_probe(
            tmp_path / "brep_hotspot.json",
            step_path,
        ),
        feasibility_runner=_fake_runner,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_same_parameter_feasibility.v1"
    )
    assert payload["feasibility_status"] == "same_parameter_repair_not_recovered"
    assert "Main Wing Station Seam Same-Parameter Feasibility v1" in markdown
