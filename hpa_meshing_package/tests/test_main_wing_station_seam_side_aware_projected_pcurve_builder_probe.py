import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_side_aware_projected_pcurve_builder_probe import (
    build_main_wing_station_seam_side_aware_projected_pcurve_builder_probe_report,
    write_main_wing_station_seam_side_aware_projected_pcurve_builder_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_pcurve_metadata_builder_probe(path: Path, step_path: Path) -> Path:
    step_path.parent.mkdir(parents=True, exist_ok=True)
    step_path.write_text("STEP fixture placeholder\n", encoding="utf-8")
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1",
            "metadata_builder_status": "side_aware_station_pcurve_metadata_builder_partial",
            "candidate_step_path": str(step_path),
            "target_edges": [
                {"curve_id": 7, "edge_index": 7, "face_ids": [2, 3]},
            ],
            "baseline_summary": {
                "target_edge_count": 1,
                "target_face_count": 2,
                "pcurve_present_face_count": 2,
                "bounded_pcurve_face_count": 0,
                "passed_face_count": 0,
                "all_station_metadata_checks_pass": False,
            },
            "strategy_attempt_summary": {
                "attempt_count": 2,
                "recovered_attempt_count": 0,
                "best_bounded_face_count": 2,
                "best_passed_face_count": 0,
            },
            "blocking_reasons": [
                "side_aware_station_pcurve_metadata_builder_not_recovered",
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
        }
    ]


def _partial_projected_runner(**kwargs):
    assert kwargs["sample_count"] == 23
    assert kwargs["projection_tolerance_m"] == 1.0e-7
    assert kwargs["interpolation_tolerance"] == 1.0e-9
    checks = [
        {
            "edge_index": 7,
            "face_checks": [
                {
                    "face_id": 2,
                    "has_pcurve": True,
                    "pcurve_domain_bounded": True,
                    "check_pcurve_range": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                    "same_parameter_flag": True,
                    "same_range_flag": True,
                },
                {
                    "face_id": 3,
                    "has_pcurve": True,
                    "pcurve_domain_bounded": True,
                    "check_pcurve_range": True,
                    "check_same_parameter": False,
                    "check_curve3d_with_pcurve": False,
                    "check_vertex_tolerance": False,
                    "same_parameter_flag": True,
                    "same_range_flag": True,
                },
            ],
        }
    ]
    return {
        "runtime_status": "evaluated",
        "baseline_checks": _baseline_checks(),
        "strategy_attempts": [
            {
                "strategy": "sampled_surface_project_interpolate_update_edge_then_same_parameter",
                "operation_results": [
                    {
                        "edge_index": 7,
                        "edge_found": True,
                        "face_operations": [
                            {
                                "face_id": 2,
                                "called": True,
                                "projected_pcurve_built": True,
                                "pcurve_type": "Geom2d_BSplineCurve",
                                "max_projection_distance_m": 2.0e-15,
                                "endpoint_orientation_gate": {
                                    "orientation_preserved": True,
                                    "endpoint_residual_within_tolerance": True,
                                },
                                "error": None,
                            },
                            {
                                "face_id": 3,
                                "called": True,
                                "projected_pcurve_built": True,
                                "pcurve_type": "Geom2d_BSplineCurve",
                                "max_projection_distance_m": 3.0e-15,
                                "endpoint_orientation_gate": {
                                    "orientation_preserved": True,
                                    "endpoint_residual_within_tolerance": True,
                                },
                                "error": None,
                            },
                        ],
                    }
                ],
                "checks": checks,
            }
        ],
    }


def _recovered_projected_runner(**_kwargs):
    recovered_checks = [
        {
            "edge_index": 7,
            "face_checks": [
                {
                    "face_id": 2,
                    "has_pcurve": True,
                    "pcurve_domain_bounded": True,
                    "check_pcurve_range": True,
                    "check_same_parameter": True,
                    "check_curve3d_with_pcurve": True,
                    "check_vertex_tolerance": True,
                },
                {
                    "face_id": 3,
                    "has_pcurve": True,
                    "pcurve_domain_bounded": True,
                    "check_pcurve_range": True,
                    "check_same_parameter": True,
                    "check_curve3d_with_pcurve": True,
                    "check_vertex_tolerance": True,
                },
            ],
        }
    ]
    return {
        "runtime_status": "evaluated",
        "baseline_checks": _baseline_checks(),
        "strategy_attempts": [
            {
                "strategy": "sampled_surface_project_interpolate_update_edge_then_same_parameter",
                "operation_results": [
                    {
                        "edge_index": 7,
                        "edge_found": True,
                        "face_operations": [
                            {
                                "face_id": 2,
                                "called": True,
                                "projected_pcurve_built": True,
                                "endpoint_orientation_gate": {
                                    "orientation_preserved": True,
                                    "endpoint_residual_within_tolerance": True,
                                },
                                "error": None,
                            },
                            {
                                "face_id": 3,
                                "called": True,
                                "projected_pcurve_built": True,
                                "endpoint_orientation_gate": {
                                    "orientation_preserved": True,
                                    "endpoint_residual_within_tolerance": True,
                                },
                                "error": None,
                            },
                        ],
                    }
                ],
                "checks": recovered_checks,
            }
        ],
    }


def test_projected_pcurve_builder_reports_partial_when_projection_succeeds_but_gate_fails(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    pcurve_metadata_builder_path = _write_pcurve_metadata_builder_probe(
        tmp_path / "pcurve_builder.json",
        step_path,
    )

    report = build_main_wing_station_seam_side_aware_projected_pcurve_builder_probe_report(
        pcurve_metadata_builder_probe_path=pcurve_metadata_builder_path,
        strategies=["sampled_surface_project_interpolate_update_edge_then_same_parameter"],
        projected_pcurve_builder_runner=_partial_projected_runner,
    )

    assert (
        report.projected_builder_status
        == "side_aware_station_projected_pcurve_builder_partial"
    )
    assert report.production_default_changed is False
    assert report.target_edges == [{"curve_id": 7, "edge_index": 7, "face_ids": [2, 3]}]
    assert report.strategy_attempt_summary["attempt_count"] == 1
    assert report.strategy_attempt_summary["projected_pcurve_built_face_count"] == 2
    assert report.strategy_attempt_summary["endpoint_orientation_pass_face_count"] == 2
    assert report.strategy_attempt_summary["best_passed_face_count"] == 0
    assert "projected_endpoint_orientation_gate_passed" in report.engineering_findings
    assert "shape_analysis_gate_still_fails_after_projected_or_sampled_pcurves" in (
        report.engineering_findings
    )
    assert "side_aware_station_projected_pcurve_builder_not_recovered" in (
        report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "move_repair_upstream_to_section_parametrization_or_export_pcurve_generation"
    )


def test_projected_pcurve_builder_reports_recovered_when_shape_analysis_gate_passes(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    pcurve_metadata_builder_path = _write_pcurve_metadata_builder_probe(
        tmp_path / "pcurve_builder.json",
        step_path,
    )

    report = build_main_wing_station_seam_side_aware_projected_pcurve_builder_probe_report(
        pcurve_metadata_builder_probe_path=pcurve_metadata_builder_path,
        strategies=["sampled_surface_project_interpolate_update_edge_then_same_parameter"],
        projected_pcurve_builder_runner=_recovered_projected_runner,
    )

    assert (
        report.projected_builder_status
        == "side_aware_station_projected_pcurve_builder_recovered"
    )
    assert report.strategy_attempt_summary["recovered_attempt_count"] == 1
    assert "materialize_projected_pcurve_repaired_step_as_separate_artifact" in (
        report.next_actions
    )


def test_write_projected_pcurve_builder_probe_report(tmp_path: Path):
    step_path = tmp_path / "candidate_raw_dump.stp"
    pcurve_metadata_builder_path = _write_pcurve_metadata_builder_probe(
        tmp_path / "pcurve_builder.json",
        step_path,
    )

    written = write_main_wing_station_seam_side_aware_projected_pcurve_builder_probe_report(
        tmp_path / "out",
        pcurve_metadata_builder_probe_path=pcurve_metadata_builder_path,
        strategies=["sampled_surface_project_interpolate_update_edge_then_same_parameter"],
        projected_pcurve_builder_runner=_partial_projected_runner,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_side_aware_projected_pcurve_builder_probe.v1"
    )
    assert (
        payload["projected_builder_status"]
        == "side_aware_station_projected_pcurve_builder_partial"
    )
    assert "Projected PCurve Builder Probe v1" in markdown
