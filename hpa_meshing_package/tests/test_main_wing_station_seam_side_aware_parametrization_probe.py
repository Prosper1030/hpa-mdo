import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_side_aware_parametrization_probe import (
    build_main_wing_station_seam_side_aware_parametrization_probe_report,
    write_main_wing_station_seam_side_aware_parametrization_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_rebuild_csm(path: Path) -> Path:
    lines = [
        "# side-aware source fixture",
        'SET export_path $"raw_dump.stp"',
        "mark",
        "skbeg 1 -1 0",
        "   spline 0.5 -1 0.2",
        "   spline 0 -1 0",
        "   spline 0.5 -1 -0.2",
        "   linseg 1 -1 0",
        "skend",
        "skbeg 1 1 0",
        "   spline 0.66 1 0.18",
        "   spline 0.33 1 0.24",
        "   spline 0 1 0",
        "   spline 0.33 1 -0.24",
        "   spline 0.66 1 -0.18",
        "   linseg 1 1 0",
        "skend",
        "rule",
        "DUMP !export_path 0 1",
        "END",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_parametrization_audit(path: Path, rebuild_csm_path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_profile_parametrization_audit.v1",
            "audit_status": "profile_parametrization_seam_fragment_correlation_observed",
            "source_csm_path": str(rebuild_csm_path),
            "target_station_y_m": [0.0],
        },
    )


def test_side_aware_parametrization_source_only_preserves_le_anchor_and_side_counts(
    tmp_path: Path,
):
    rebuild_csm = _write_rebuild_csm(tmp_path / "rebuild.csm")
    audit_path = _write_parametrization_audit(tmp_path / "audit.json", rebuild_csm)

    report = build_main_wing_station_seam_side_aware_parametrization_probe_report(
        profile_parametrization_audit_path=audit_path,
        materialization_requested=False,
    )

    assert (
        report.probe_status
        == "side_aware_parametrization_source_only_ready_for_materialization"
    )
    assert report.production_default_changed is False
    assert report.source_profile_point_counts == [5, 7]
    assert report.candidate_profile_point_counts == [7, 7]
    summary = report.side_parametrization_summary
    assert summary["target_upper_side_point_count"] == 4
    assert summary["target_lower_side_point_count"] == 4
    assert summary["max_le_anchor_delta_m"] == 0.0
    assert "leading_edge_anchors_preserved" in report.engineering_findings
    assert "side_aware_candidate_materialization_not_run" in report.blocking_reasons


def test_side_aware_parametrization_accepts_clean_materialized_inventory(
    tmp_path: Path,
):
    rebuild_csm = _write_rebuild_csm(tmp_path / "rebuild.csm")
    audit_path = _write_parametrization_audit(tmp_path / "audit.json", rebuild_csm)

    report = build_main_wing_station_seam_side_aware_parametrization_probe_report(
        profile_parametrization_audit_path=audit_path,
        materialization_requested=True,
        materialization_root=tmp_path / "out",
        surface_inventory_override={
            "status": "topology_counted",
            "body_count": 1,
            "volume_count": 1,
            "surface_count": 8,
            "bbox": [0.0, -1.0, -0.25, 1.0, 1.0, 0.25],
            "surfaces": [
                {"tag": 1, "bbox": [0.0, -1.0, -0.2, 1.0, -1.0, 0.2]},
                {"tag": 2, "bbox": [0.0, 1.0, -0.2, 1.0, 1.0, 0.2]},
            ],
        },
    )

    assert (
        report.probe_status
        == "side_aware_parametrization_candidate_materialized_needs_brep_validation"
    )
    assert report.candidate_report["span_y_bounds_preserved"] is True
    assert report.candidate_report["target_station_face_groups"][0][
        "plane_face_count"
    ] == 0
    assert report.next_actions[0] == (
        "run_profile_resample_brep_validation_on_side_aware_candidate"
    )


def test_write_side_aware_parametrization_probe_report(tmp_path: Path):
    rebuild_csm = _write_rebuild_csm(tmp_path / "rebuild.csm")
    audit_path = _write_parametrization_audit(tmp_path / "audit.json", rebuild_csm)

    written = write_main_wing_station_seam_side_aware_parametrization_probe_report(
        tmp_path / "out",
        profile_parametrization_audit_path=audit_path,
        materialization_requested=False,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_side_aware_parametrization_probe.v1"
    )
    assert (
        payload["probe_status"]
        == "side_aware_parametrization_source_only_ready_for_materialization"
    )
    assert "Side-Aware Parametrization Probe v1" in markdown
