import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_side_aware_metadata_repair_probe import (
    build_main_wing_station_seam_side_aware_metadata_repair_probe_report,
    write_main_wing_station_seam_side_aware_metadata_repair_probe_report,
    _resolve_path,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_brep_validation_probe(path: Path, step_path: Path) -> Path:
    step_path.parent.mkdir(parents=True, exist_ok=True)
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_side_aware_brep_validation_probe.v1",
            "probe_status": "side_aware_candidate_station_brep_edges_suspect",
            "candidate_step_path": str(step_path),
            "target_station_y_m": [-10.5, 13.5],
            "target_selection": {
                "selection_mode": "station_y_geometry_on_candidate_step",
                "source_fixture_tags_replayed": False,
            },
            "station_edge_checks": [
                {
                    "station_y_m": -10.5,
                    "candidate_step_curve_tag": 7,
                    "candidate_step_edge_index": 7,
                    "ancestor_face_ids": [2, 3],
                    "pcurve_presence_complete": True,
                    "curve3d_with_pcurve_consistent": False,
                    "same_parameter_by_face_ok": False,
                    "vertex_tolerance_by_face_ok": False,
                },
                {
                    "station_y_m": 13.5,
                    "candidate_step_curve_tag": 50,
                    "candidate_step_edge_index": 50,
                    "ancestor_face_ids": [19, 20],
                    "pcurve_presence_complete": True,
                    "curve3d_with_pcurve_consistent": False,
                    "same_parameter_by_face_ok": False,
                    "vertex_tolerance_by_face_ok": False,
                },
            ],
        },
    )


def _write_residual_diagnostic(path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1",
            "diagnostic_status": "side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail",
            "candidate_step_path": "candidate_raw_dump.stp",
            "residual_summary": {
                "edge_face_residual_count": 4,
                "sampled_edge_face_count": 4,
                "max_sample_distance_m": 0.0,
                "max_sample_distance_over_edge_tolerance": 0.0,
                "shape_analysis_flag_failure_count": 4,
                "unbounded_pcurve_domain_count": 4,
                "pcurve_missing_count": 0,
            },
        },
    )


def _baseline_checks():
    return [
        {
            "curve_id": 7,
            "edge_index": 7,
            "face_checks": [
                {
                    "face_id": 2,
                    "has_pcurve": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                },
                {
                    "face_id": 3,
                    "has_pcurve": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                },
            ],
        },
        {
            "curve_id": 50,
            "edge_index": 50,
            "face_checks": [
                {
                    "face_id": 19,
                    "has_pcurve": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                }
            ],
        },
    ]


def _same_parameter_runner_not_recovered(**kwargs):
    assert kwargs["step_path"].name == "candidate_raw_dump.stp"
    assert kwargs["target_edges"] == [
        {"curve_id": 7, "edge_index": 7, "face_ids": [2, 3]},
        {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]},
    ]
    assert kwargs["tolerances"] == [1e-7, 1e-5]
    baseline = _baseline_checks()
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline,
        "repair_attempts": [
            {"tolerance": tolerance, "recovered": False, "checks": baseline}
            for tolerance in kwargs["tolerances"]
        ],
    }


def _shape_fix_runner_not_recovered(**kwargs):
    assert kwargs["step_path"].name == "candidate_raw_dump.stp"
    assert kwargs["target_edges"][0]["curve_id"] == 7
    assert kwargs["tolerances"] in ([1e-7], [1e-7, 1e-5])
    assert kwargs["operations"] == ["fix_same_parameter_edge"]
    baseline = _baseline_checks()
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline,
        "repair_attempts": [
            {
                "operation": "fix_same_parameter_edge",
                "tolerance": tolerance,
                "recovered": False,
                "checks": baseline,
            }
            for tolerance in kwargs["tolerances"]
        ],
    }


def _same_parameter_runner_recovered(**kwargs):
    baseline = _baseline_checks()
    recovered = [
        {
            **check,
            "face_checks": [
                {
                    **face_check,
                    "check_same_parameter": True,
                    "check_curve3d_with_pcurve": True,
                    "check_vertex_tolerance": True,
                }
                for face_check in check["face_checks"]
            ],
        }
        for check in baseline
    ]
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline,
        "repair_attempts": [
            {"tolerance": kwargs["tolerances"][0], "recovered": True, "checks": recovered}
        ],
    }


def test_side_aware_metadata_repair_probe_reports_unrecovered_metadata_gate(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    brep_path = _write_brep_validation_probe(tmp_path / "brep.json", step_path)
    residual_path = _write_residual_diagnostic(tmp_path / "residual.json")

    report = build_main_wing_station_seam_side_aware_metadata_repair_probe_report(
        side_aware_brep_validation_probe_path=brep_path,
        pcurve_residual_diagnostic_path=residual_path,
        tolerances=[1e-7, 1e-5],
        operations=["fix_same_parameter_edge"],
        same_parameter_runner=_same_parameter_runner_not_recovered,
        shape_fix_runner=_shape_fix_runner_not_recovered,
    )

    assert (
        report.metadata_repair_status
        == "side_aware_station_metadata_repair_not_recovered"
    )
    assert report.production_default_changed is False
    assert report.target_edges[0] == {
        "curve_id": 7,
        "edge_index": 7,
        "face_ids": [2, 3],
    }
    assert report.residual_context_summary["max_sample_distance_m"] == 0.0
    assert report.same_parameter_attempt_summary["recovered_attempt_count"] == 0
    assert report.shape_fix_attempt_summary["recovered_attempt_count"] == 0
    assert "side_aware_sampled_residual_zero_but_metadata_repair_not_recovered" in (
        report.engineering_findings
    )
    assert "side_aware_station_metadata_repair_not_recovered" in (
        report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "prototype_side_aware_station_pcurve_rewrite_or_export_metadata_builder"
    )


def test_side_aware_metadata_repair_probe_reports_recovered_when_any_runner_recovers(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    brep_path = _write_brep_validation_probe(tmp_path / "brep.json", step_path)
    residual_path = _write_residual_diagnostic(tmp_path / "residual.json")

    report = build_main_wing_station_seam_side_aware_metadata_repair_probe_report(
        side_aware_brep_validation_probe_path=brep_path,
        pcurve_residual_diagnostic_path=residual_path,
        tolerances=[1e-7],
        operations=["fix_same_parameter_edge"],
        same_parameter_runner=_same_parameter_runner_recovered,
        shape_fix_runner=_shape_fix_runner_not_recovered,
    )

    assert (
        report.metadata_repair_status
        == "side_aware_station_metadata_repair_recovered"
    )
    assert "materialize_side_aware_metadata_repaired_step_before_mesh_handoff" in (
        report.next_actions
    )


def test_write_side_aware_metadata_repair_probe_report(tmp_path: Path):
    step_path = tmp_path / "candidate_raw_dump.stp"
    brep_path = _write_brep_validation_probe(tmp_path / "brep.json", step_path)
    residual_path = _write_residual_diagnostic(tmp_path / "residual.json")

    written = write_main_wing_station_seam_side_aware_metadata_repair_probe_report(
        tmp_path / "out",
        side_aware_brep_validation_probe_path=brep_path,
        pcurve_residual_diagnostic_path=residual_path,
        tolerances=[1e-7, 1e-5],
        operations=["fix_same_parameter_edge"],
        same_parameter_runner=_same_parameter_runner_not_recovered,
        shape_fix_runner=_shape_fix_runner_not_recovered,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_side_aware_metadata_repair_probe.v1"
    )
    assert (
        payload["metadata_repair_status"]
        == "side_aware_station_metadata_repair_not_recovered"
    )
    assert "Side-Aware Metadata Repair Probe v1" in markdown


def test_resolve_path_accepts_package_relative_report_paths():
    assert _resolve_path("docs/current_status.md") == (
        Path(__file__).resolve().parents[1] / "docs" / "current_status.md"
    )
