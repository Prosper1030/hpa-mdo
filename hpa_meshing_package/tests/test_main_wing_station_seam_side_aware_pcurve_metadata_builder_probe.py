import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_side_aware_pcurve_metadata_builder_probe import (
    build_main_wing_station_seam_side_aware_pcurve_metadata_builder_probe_report,
    write_main_wing_station_seam_side_aware_pcurve_metadata_builder_probe_report,
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


def _write_metadata_repair_probe(path: Path, step_path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_side_aware_metadata_repair_probe.v1",
            "metadata_repair_status": "side_aware_station_metadata_repair_not_recovered",
            "candidate_step_path": str(step_path),
            "target_edges": [
                {"curve_id": 7, "edge_index": 7, "face_ids": [2, 3]},
                {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]},
            ],
            "same_parameter_attempt_summary": {
                "attempt_count": 2,
                "recovered_attempt_count": 0,
            },
            "shape_fix_attempt_summary": {
                "attempt_count": 2,
                "recovered_attempt_count": 0,
            },
            "residual_context_summary": {
                "max_sample_distance_m": 0.0,
                "unbounded_pcurve_domain_count": 4,
            },
            "blocking_reasons": [
                "side_aware_station_metadata_repair_not_recovered",
                "side_aware_candidate_mesh_handoff_not_run",
            ],
        },
    )


def _baseline_checks() -> list[dict]:
    return [
        {
            "edge_index": 7,
            "face_checks": [
                {
                    "face_id": 2,
                    "has_pcurve": True,
                    "pcurve_domain_bounded": False,
                    "check_pcurve_range": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                },
                {
                    "face_id": 3,
                    "has_pcurve": True,
                    "pcurve_domain_bounded": False,
                    "check_pcurve_range": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                },
            ],
        },
        {
            "edge_index": 50,
            "face_checks": [
                {
                    "face_id": 19,
                    "has_pcurve": True,
                    "pcurve_domain_bounded": False,
                    "check_pcurve_range": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                },
                {
                    "face_id": 20,
                    "has_pcurve": True,
                    "pcurve_domain_bounded": False,
                    "check_pcurve_range": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                },
            ],
        },
    ]


def _bounded_but_unrecovered_runner(**kwargs):
    assert kwargs["step_path"].name == "candidate_raw_dump.stp"
    assert kwargs["target_edges"] == [
        {"curve_id": 7, "edge_index": 7, "face_ids": [2, 3]},
        {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]},
    ]
    assert kwargs["strategies"] == [
        "bounded_existing_pcurve_update_edge",
        "bounded_existing_pcurve_update_edge_and_vertex_params",
    ]
    baseline = _baseline_checks()
    bounded_checks = [
        {
            **check,
            "face_checks": [
                {
                    **face_check,
                    "pcurve_domain_bounded": True,
                    "pcurve_type": "Geom2d_TrimmedCurve",
                    "pcurve_first_parameter": 0.0,
                    "pcurve_last_parameter": 1.0,
                }
                for face_check in check["face_checks"]
            ],
        }
        for check in baseline
    ]
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline,
        "strategy_attempts": [
            {
                "strategy": "bounded_existing_pcurve_update_edge",
                "operation_results": [{"called": True, "error": None}],
                "checks": bounded_checks,
            },
            {
                "strategy": "bounded_existing_pcurve_update_edge_and_vertex_params",
                "operation_results": [{"called": True, "error": None}],
                "checks": bounded_checks,
            },
        ],
    }


def _recovered_runner(**kwargs):
    baseline = _baseline_checks()
    recovered_checks = [
        {
            **check,
            "face_checks": [
                {
                    **face_check,
                    "pcurve_domain_bounded": True,
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
        "strategy_attempts": [
            {
                "strategy": kwargs["strategies"][0],
                "operation_results": [{"called": True, "error": None}],
                "checks": recovered_checks,
            }
        ],
    }


def test_side_aware_pcurve_metadata_builder_reports_partial_metadata_progress(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    brep_path = _write_brep_validation_probe(tmp_path / "brep.json", step_path)
    metadata_path = _write_metadata_repair_probe(tmp_path / "metadata.json", step_path)

    report = build_main_wing_station_seam_side_aware_pcurve_metadata_builder_probe_report(
        side_aware_brep_validation_probe_path=brep_path,
        metadata_repair_probe_path=metadata_path,
        strategies=[
            "bounded_existing_pcurve_update_edge",
            "bounded_existing_pcurve_update_edge_and_vertex_params",
        ],
        metadata_builder_runner=_bounded_but_unrecovered_runner,
    )

    assert (
        report.metadata_builder_status
        == "side_aware_station_pcurve_metadata_builder_partial"
    )
    assert report.production_default_changed is False
    assert report.target_edges[0] == {
        "curve_id": 7,
        "edge_index": 7,
        "face_ids": [2, 3],
    }
    assert report.strategy_attempt_summary["attempt_count"] == 2
    assert report.strategy_attempt_summary["recovered_attempt_count"] == 0
    assert report.strategy_attempt_summary["best_bounded_face_count"] == 4
    assert "bounded_pcurve_domains_observed_without_station_metadata_recovery" in (
        report.engineering_findings
    )
    assert "side_aware_station_pcurve_metadata_builder_not_recovered" in (
        report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "prototype_projected_or_sampled_pcurve_builder_with_vertex_orientation_gate"
    )


def test_side_aware_pcurve_metadata_builder_reports_recovered_when_strategy_recovers(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    brep_path = _write_brep_validation_probe(tmp_path / "brep.json", step_path)
    metadata_path = _write_metadata_repair_probe(tmp_path / "metadata.json", step_path)

    report = build_main_wing_station_seam_side_aware_pcurve_metadata_builder_probe_report(
        side_aware_brep_validation_probe_path=brep_path,
        metadata_repair_probe_path=metadata_path,
        strategies=["bounded_existing_pcurve_update_edge"],
        metadata_builder_runner=_recovered_runner,
    )

    assert (
        report.metadata_builder_status
        == "side_aware_station_pcurve_metadata_builder_recovered"
    )
    assert "materialize_repaired_side_aware_step_as_separate_artifact" in (
        report.next_actions
    )


def test_write_side_aware_pcurve_metadata_builder_probe_report(tmp_path: Path):
    step_path = tmp_path / "candidate_raw_dump.stp"
    brep_path = _write_brep_validation_probe(tmp_path / "brep.json", step_path)
    metadata_path = _write_metadata_repair_probe(tmp_path / "metadata.json", step_path)

    written = write_main_wing_station_seam_side_aware_pcurve_metadata_builder_probe_report(
        tmp_path / "out",
        side_aware_brep_validation_probe_path=brep_path,
        metadata_repair_probe_path=metadata_path,
        strategies=[
            "bounded_existing_pcurve_update_edge",
            "bounded_existing_pcurve_update_edge_and_vertex_params",
        ],
        metadata_builder_runner=_bounded_but_unrecovered_runner,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1"
    )
    assert (
        payload["metadata_builder_status"]
        == "side_aware_station_pcurve_metadata_builder_partial"
    )
    assert "PCurve Metadata Builder Probe v1" in markdown
