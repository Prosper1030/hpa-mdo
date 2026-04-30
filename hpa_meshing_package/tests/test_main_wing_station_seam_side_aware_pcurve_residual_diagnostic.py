import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_side_aware_pcurve_residual_diagnostic import (
    build_main_wing_station_seam_side_aware_pcurve_residual_diagnostic_report,
    write_main_wing_station_seam_side_aware_pcurve_residual_diagnostic_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_brep_validation_probe(path: Path, step_path: Path) -> Path:
    step_path.parent.mkdir(parents=True, exist_ok=True)
    step_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_side_aware_brep_validation_probe.v1",
            "probe_status": "side_aware_candidate_station_brep_edges_suspect",
            "candidate_step_path": str(step_path),
            "target_station_y_m": [-10.5],
            "target_selection": {
                "selection_mode": "station_y_geometry_on_candidate_step",
                "source_fixture_tags_replayed": False,
                "selected_curve_tags": [7],
                "selected_surface_tags": [2, 3],
            },
            "station_edge_checks": [
                {
                    "station_y_m": -10.5,
                    "candidate_step_curve_tag": 7,
                    "candidate_step_edge_index": 7,
                    "owner_surface_tags": [2, 3],
                    "ancestor_face_ids": [2, 3],
                    "pcurve_presence_complete": True,
                    "curve3d_with_pcurve_consistent": False,
                    "same_parameter_by_face_ok": False,
                    "vertex_tolerance_by_face_ok": False,
                    "pcurve_range_matches_edge_range": True,
                }
            ],
            "blocking_reasons": [
                "side_aware_candidate_station_brep_pcurve_checks_suspect",
            ],
            "next_actions": [
                "repair_side_aware_candidate_pcurve_export_before_mesh_handoff",
            ],
        },
    )


def _low_residual_sampler(**_kwargs):
    return {
        "runtime_status": "evaluated",
        "edge_face_residuals": [
            {
                "station_y_m": -10.5,
                "candidate_step_curve_tag": 7,
                "candidate_step_face_tag": 2,
                "pcurve_present": True,
                "shape_analysis_curve3d_with_pcurve": False,
                "shape_analysis_same_parameter": False,
                "shape_analysis_vertex_tolerance": False,
                "edge_tolerance_m": 1.0e-7,
                "max_vertex_tolerance_m": 1.0e-7,
                "max_sample_distance_m": 2.0e-10,
                "mean_sample_distance_m": 1.0e-10,
                "max_sample_distance_over_edge_tolerance": 0.002,
                "sample_count": 11,
                "curve3d_type": "Geom_BSplineCurve",
                "pcurve_type": "Geom2d_Line",
                "pcurve_first_parameter": -2.0e100,
                "pcurve_last_parameter": 2.0e100,
            },
            {
                "station_y_m": -10.5,
                "candidate_step_curve_tag": 7,
                "candidate_step_face_tag": 3,
                "pcurve_present": True,
                "shape_analysis_curve3d_with_pcurve": False,
                "shape_analysis_same_parameter": False,
                "shape_analysis_vertex_tolerance": False,
                "edge_tolerance_m": 1.0e-7,
                "max_vertex_tolerance_m": 1.0e-7,
                "max_sample_distance_m": 0.0,
                "mean_sample_distance_m": 0.0,
                "max_sample_distance_over_edge_tolerance": 0.0,
                "sample_count": 11,
                "curve3d_type": "Geom_BSplineCurve",
                "pcurve_type": "Geom2d_Line",
                "pcurve_first_parameter": -2.0e100,
                "pcurve_last_parameter": 2.0e100,
            },
        ],
    }


def _high_residual_sampler(**_kwargs):
    payload = _low_residual_sampler()
    payload["edge_face_residuals"][0]["max_sample_distance_m"] = 4.0e-6
    payload["edge_face_residuals"][0][
        "max_sample_distance_over_edge_tolerance"
    ] = 40.0
    return payload


def test_side_aware_pcurve_residual_diagnostic_separates_low_residual_shape_flags(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    brep_path = _write_brep_validation_probe(tmp_path / "brep.json", step_path)

    report = build_main_wing_station_seam_side_aware_pcurve_residual_diagnostic_report(
        side_aware_brep_validation_probe_path=brep_path,
        residual_sampler=_low_residual_sampler,
        sample_count=11,
    )

    assert (
        report.diagnostic_status
        == "side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail"
    )
    assert report.target_selection["source_fixture_tags_replayed"] is False
    assert report.residual_summary["edge_face_residual_count"] == 2
    assert report.residual_summary["max_sample_distance_m"] == 2.0e-10
    assert "station_pcurve_sampled_geometric_residuals_within_edge_tolerance" in (
        report.engineering_findings
    )
    assert "shape_analysis_flags_fail_despite_low_sampled_residual" in (
        report.engineering_findings
    )
    assert "unbounded_line_pcurve_parameter_domain_observed" in (
        report.engineering_findings
    )
    assert "side_aware_station_shape_analysis_flags_still_block_mesh_handoff" in (
        report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "test_side_aware_same_parameter_metadata_repair_before_mesh_handoff"
    )


def test_side_aware_pcurve_residual_diagnostic_blocks_geometric_residuals(
    tmp_path: Path,
):
    step_path = tmp_path / "candidate_raw_dump.stp"
    brep_path = _write_brep_validation_probe(tmp_path / "brep.json", step_path)

    report = build_main_wing_station_seam_side_aware_pcurve_residual_diagnostic_report(
        side_aware_brep_validation_probe_path=brep_path,
        residual_sampler=_high_residual_sampler,
        sample_count=11,
    )

    assert (
        report.diagnostic_status
        == "side_aware_station_pcurve_sampled_residuals_exceed_tolerance"
    )
    assert "side_aware_station_pcurve_geometric_residual_exceeds_tolerance" in (
        report.blocking_reasons
    )


def test_write_side_aware_pcurve_residual_diagnostic_report(tmp_path: Path):
    step_path = tmp_path / "candidate_raw_dump.stp"
    brep_path = _write_brep_validation_probe(tmp_path / "brep.json", step_path)

    written = write_main_wing_station_seam_side_aware_pcurve_residual_diagnostic_report(
        tmp_path / "out",
        side_aware_brep_validation_probe_path=brep_path,
        residual_sampler=_low_residual_sampler,
        sample_count=11,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1"
    )
    assert "Side-Aware PCurve Residual Diagnostic v1" in markdown
