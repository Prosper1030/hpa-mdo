import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_export_strategy_probe import (
    build_main_wing_station_seam_export_strategy_probe_report,
    write_main_wing_station_seam_export_strategy_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_rebuild_csm(path: Path) -> Path:
    sections = [
        ("0", "-16.5", "0"),
        ("0", "-10.5", "0"),
        ("0", "13.5", "0"),
        ("0", "16.5", "0"),
    ]
    lines = [
        "# source csm",
        'SET export_path $"raw_dump.stp"',
        "mark",
    ]
    for x, y, z in sections:
        lines.extend(
            [
                f"skbeg {x} {y} {z}",
                f"   linseg 1 {y} {z}",
                f"   linseg {x} {y} {z}",
                "skend",
            ]
        )
    lines.extend(["rule", "DUMP !export_path 0 1", "END", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_export_source_audit(path: Path, csm_path: Path) -> Path:
    return _write_json(
        path,
        {
            "audit_status": "single_rule_internal_station_export_source_confirmed",
            "rebuild_csm_path": str(csm_path),
            "target_station_mappings": [
                {"csm_section_index": 1, "defect_station_y_m": -10.5},
                {"csm_section_index": 2, "defect_station_y_m": 13.5},
            ],
        },
    )


def test_export_strategy_probe_source_only_moves_targets_to_boundaries(tmp_path: Path):
    csm_path = _write_rebuild_csm(tmp_path / "rebuild.csm")
    audit_path = _write_export_source_audit(tmp_path / "audit.json", csm_path)

    report = build_main_wing_station_seam_export_strategy_probe_report(
        export_source_audit_path=audit_path,
        materialization_requested=False,
    )

    assert (
        report.probe_status
        == "export_strategy_candidate_source_only_ready_for_materialization"
    )
    assert report.production_default_changed is False
    assert report.target_rule_section_indices == [1, 2]
    assert len(report.candidate_reports) == 2
    assert all(
        candidate["all_targets_exported_as_rule_boundaries"]
        for candidate in report.candidate_reports
    )
    assert all(
        candidate["target_boundary_duplication_count"] == 2
        for candidate in report.candidate_reports
    )
    assert "split_candidate_moves_target_stations_to_rule_boundaries" in (
        report.engineering_findings
    )
    assert "candidate_materialization_not_run" in report.blocking_reasons


def test_write_export_strategy_probe_report(tmp_path: Path):
    csm_path = _write_rebuild_csm(tmp_path / "rebuild.csm")
    audit_path = _write_export_source_audit(tmp_path / "audit.json", csm_path)

    written = write_main_wing_station_seam_export_strategy_probe_report(
        tmp_path / "out",
        export_source_audit_path=audit_path,
        materialization_requested=False,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_export_strategy_probe.v1"
    )
    assert payload["probe_status"] == (
        "export_strategy_candidate_source_only_ready_for_materialization"
    )
    assert "Main Wing Station Seam Export Strategy Probe v1" in markdown
