import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_internal_cap_probe import (
    build_main_wing_station_seam_internal_cap_probe_report,
    write_main_wing_station_seam_internal_cap_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_export_source_audit(path: Path) -> Path:
    return _write_json(
        path,
        {
            "audit_status": "single_rule_internal_station_export_source_confirmed",
            "target_station_mappings": [
                {"defect_station_y_m": -10.5, "csm_section_index": 2},
                {"defect_station_y_m": 13.5, "csm_section_index": 9},
            ],
        },
    )


def _write_export_strategy_probe(
    path: Path,
    *,
    export_source_audit_path: Path,
) -> Path:
    return _write_json(
        path,
        {
            "probe_status": "export_strategy_candidate_materialized_but_topology_risk",
            "export_source_audit_path": str(export_source_audit_path),
            "materialization_requested": True,
            "target_rule_section_indices": [2, 9],
            "candidate_reports": [
                {
                    "candidate": "split_at_defect_sections_no_union",
                    "all_targets_exported_as_rule_boundaries": True,
                    "target_boundary_duplication_count": 2,
                    "span_y_bounds_preserved": True,
                    "materialization": {
                        "status": "materialized",
                        "step_path": str(path.parent / "no_union.step"),
                        "topology": {
                            "body_count": 3,
                            "volume_count": 3,
                            "surface_count": 36,
                            "bbox": [0.0, -16.5, 0.0, 1.0, 16.5, 1.0],
                        },
                    },
                },
                {
                    "candidate": "split_at_defect_sections_union",
                    "all_targets_exported_as_rule_boundaries": True,
                    "target_boundary_duplication_count": 2,
                    "span_y_bounds_preserved": False,
                    "materialization": {
                        "status": "materialized",
                        "step_path": str(path.parent / "union.step"),
                        "topology": {
                            "body_count": 1,
                            "volume_count": 1,
                            "surface_count": 34,
                            "bbox": [0.0, -16.5, 0.0, 1.0, 13.5, 1.0],
                        },
                    },
                },
            ],
            "blocking_reasons": [
                "split_candidate_topology_not_single_volume_or_has_duplicate_cap_risk",
                "split_candidate_does_not_preserve_full_span_bounds",
            ],
        },
    )


def test_internal_cap_probe_classifies_duplicate_station_cap_faces(tmp_path: Path):
    audit_path = _write_export_source_audit(tmp_path / "audit.json")
    strategy_path = _write_export_strategy_probe(
        tmp_path / "strategy.json",
        export_source_audit_path=audit_path,
    )

    report = build_main_wing_station_seam_internal_cap_probe_report(
        export_strategy_probe_path=strategy_path,
        surface_inventory_by_candidate={
            "split_at_defect_sections_no_union": {
                "status": "topology_counted",
                "body_count": 3,
                "volume_count": 3,
                "surface_count": 36,
                "bbox": [0.0, -16.5, 0.0, 1.0, 16.5, 1.0],
                "surfaces": [
                    {"tag": 27, "bbox": [0.05, -10.5, 0.28, 1.09, -10.5, 0.46]},
                    {"tag": 36, "bbox": [0.05, -10.5, 0.28, 1.09, -10.5, 0.46]},
                    {"tag": 4, "bbox": [0.11, 13.5, 0.50, 0.94, 13.5, 0.64]},
                    {"tag": 28, "bbox": [0.11, 13.5, 0.50, 0.94, 13.5, 0.64]},
                ],
            },
            "split_at_defect_sections_union": {
                "status": "topology_counted",
                "body_count": 1,
                "volume_count": 1,
                "surface_count": 34,
                "bbox": [0.0, -16.5, 0.0, 1.0, 13.5, 1.0],
                "surfaces": [
                    {"tag": 29, "bbox": [0.11, 13.5, 0.50, 0.94, 13.5, 0.64]},
                    {"tag": 30, "bbox": [0.87, 13.5, 0.50, 0.91, 13.5, 0.51]},
                    {"tag": 31, "bbox": [0.14, 13.5, 0.52, 0.16, 13.5, 0.52]},
                    {"tag": 32, "bbox": [0.12, 13.5, 0.53, 0.13, 13.5, 0.53]},
                    {"tag": 33, "bbox": [0.11, 13.5, 0.54, 0.12, 13.5, 0.56]},
                    {"tag": 34, "bbox": [0.62, 13.5, 0.52, 0.71, 13.5, 0.52]},
                ],
            },
        },
    )

    assert report.probe_status == "split_candidate_internal_cap_risk_confirmed"
    assert report.production_default_changed is False
    assert report.target_station_y_m == [-10.5, 13.5]
    no_union = report.candidate_inspections[0]
    union = report.candidate_inspections[1]
    assert no_union["candidate"] == "split_at_defect_sections_no_union"
    assert no_union["target_station_face_groups"][0]["plane_face_count"] == 2
    assert no_union["target_station_face_groups"][0]["duplicate_station_cap_faces"]
    assert union["candidate"] == "split_at_defect_sections_union"
    assert union["target_station_face_groups"][1]["plane_face_count"] == 6
    assert union["span_y_bounds_preserved"] is False
    assert "internal_station_cap_faces_present" in report.blocking_reasons
    assert "split_candidate_span_truncation_confirmed" in report.blocking_reasons
    assert report.next_actions[0] == "try_pcurve_rebuild_strategy_without_split_caps"


def test_write_internal_cap_probe_report(tmp_path: Path):
    audit_path = _write_export_source_audit(tmp_path / "audit.json")
    strategy_path = _write_export_strategy_probe(
        tmp_path / "strategy.json",
        export_source_audit_path=audit_path,
    )

    written = write_main_wing_station_seam_internal_cap_probe_report(
        tmp_path / "out",
        export_strategy_probe_path=strategy_path,
        surface_inventory_by_candidate={},
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_station_seam_internal_cap_probe.v1"
    assert "Main Wing Station Seam Internal Cap Probe v1" in markdown
