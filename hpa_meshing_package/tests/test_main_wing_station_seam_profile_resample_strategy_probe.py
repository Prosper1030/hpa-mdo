import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_profile_resample_strategy_probe import (
    build_main_wing_station_seam_profile_resample_strategy_probe_report,
    write_main_wing_station_seam_profile_resample_strategy_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_rebuild_csm(path: Path) -> Path:
    lines = [
        "# source csm",
        'SET export_path $"raw_dump.stp"',
        "mark",
        "skbeg 0 -1 0",
        "   linseg 1 -1 0",
        "   spline 1 -1 1",
        "   linseg 0 -1 0",
        "skend",
        "skbeg 0 0 0",
        "   linseg 1 0 0",
        "   spline 1 0 0.5",
        "   spline 1 0 1",
        "   linseg 0 0 0",
        "skend",
        "skbeg 0 1 0",
        "   linseg 1 1 0",
        "   spline 1 1 1",
        "   linseg 0 1 0",
        "skend",
        "rule",
        "DUMP !export_path 0 1",
        "END",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_export_source_audit(path: Path, rebuild_csm_path: Path) -> Path:
    return _write_json(
        path,
        {
            "audit_status": "single_rule_internal_station_export_source_confirmed",
            "rebuild_csm_path": str(rebuild_csm_path),
            "target_station_mappings": [
                {"defect_station_y_m": 0.0, "csm_section_index": 1},
            ],
        },
    )


def test_profile_resample_strategy_source_only_uniformizes_profile_counts(
    tmp_path: Path,
):
    csm_path = _write_rebuild_csm(tmp_path / "rebuild.csm")
    audit_path = _write_export_source_audit(tmp_path / "audit.json", csm_path)

    report = build_main_wing_station_seam_profile_resample_strategy_probe_report(
        export_source_audit_path=audit_path,
        materialization_requested=False,
    )

    assert (
        report.probe_status
        == "profile_resample_candidate_source_only_ready_for_materialization"
    )
    assert report.production_default_changed is False
    assert report.source_profile_point_counts == [4, 5, 4]
    assert report.target_profile_point_count == 5
    assert report.candidate_report["rule_count"] == 1
    assert report.candidate_report["candidate_profile_point_counts"] == [5, 5, 5]
    assert "source_profile_point_count_mismatch_observed" in report.engineering_findings
    assert "candidate_materialization_not_run" in report.blocking_reasons


def test_profile_resample_strategy_accepts_clean_materialized_inventory(
    tmp_path: Path,
):
    csm_path = _write_rebuild_csm(tmp_path / "rebuild.csm")
    audit_path = _write_export_source_audit(tmp_path / "audit.json", csm_path)

    report = build_main_wing_station_seam_profile_resample_strategy_probe_report(
        export_source_audit_path=audit_path,
        materialization_requested=True,
        materialization_root=tmp_path / "out",
        surface_inventory_override={
            "status": "topology_counted",
            "body_count": 1,
            "volume_count": 1,
            "surface_count": 8,
            "bbox": [0.0, -1.0, 0.0, 1.0, 1.0, 1.0],
            "surfaces": [
                {"tag": 1, "bbox": [0.0, -1.0, 0.0, 1.0, -1.0, 1.0]},
                {"tag": 2, "bbox": [0.0, 1.0, 0.0, 1.0, 1.0, 1.0]},
            ],
        },
    )

    assert (
        report.probe_status
        == "profile_resample_candidate_materialized_needs_brep_validation"
    )
    assert report.candidate_report["span_y_bounds_preserved"] is True
    assert report.candidate_report["target_station_face_groups"][0][
        "plane_face_count"
    ] == 0
    assert report.next_actions[0] == (
        "run_station_seam_brep_hotspot_probe_on_profile_resample_candidate"
    )


def test_write_profile_resample_strategy_probe_report(tmp_path: Path):
    csm_path = _write_rebuild_csm(tmp_path / "rebuild.csm")
    audit_path = _write_export_source_audit(tmp_path / "audit.json", csm_path)

    written = write_main_wing_station_seam_profile_resample_strategy_probe_report(
        tmp_path / "out",
        export_source_audit_path=audit_path,
        materialization_requested=False,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_profile_resample_strategy_probe.v1"
    )
    assert "Main Wing Station Seam Profile Resample Strategy Probe v1" in markdown
