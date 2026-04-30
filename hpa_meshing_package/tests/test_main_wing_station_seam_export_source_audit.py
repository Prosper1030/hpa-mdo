import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_export_source_audit import (
    build_main_wing_station_seam_export_source_audit_report,
    write_main_wing_station_seam_export_source_audit_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_shape_fix(path: Path, step_path: Path) -> Path:
    return _write_json(
        path,
        {
            "feasibility_status": "shape_fix_repair_not_recovered",
            "normalized_step_path": str(step_path),
        },
    )


def _write_topology_fixture(path: Path) -> Path:
    return _write_json(
        path,
        {
            "station_fixture_cases": [
                {
                    "defect_station_y_m": -10.5,
                    "source_section_index": 3,
                    "candidate_curve_tags": [36],
                    "owner_surface_entity_tags": [12, 13],
                },
                {
                    "defect_station_y_m": 13.5,
                    "source_section_index": 4,
                    "candidate_curve_tags": [50],
                    "owner_surface_entity_tags": [19, 20],
                },
            ]
        },
    )


def _write_csm(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                'SET export_path $"raw_dump.stp"',
                "mark",
                "skbeg 0 -16.5 0",
                "skend",
                "skbeg 0 -10.5 0",
                "skend",
                "skbeg 0 13.5 0",
                "skend",
                "skbeg 0 16.5 0",
                "skend",
                "rule",
                "DUMP !export_path 0 1",
                "END",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_lineage(path: Path) -> Path:
    return _write_json(
        path,
        {
            "surfaces": [
                {
                    "rule_sections": [
                        {"rule_section_index": 0, "y_le": -16.5, "side": "left_tip"},
                        {
                            "rule_section_index": 1,
                            "source_section_index": 3,
                            "y_le": -10.5,
                            "mirrored": True,
                            "side": "left_interior",
                        },
                        {
                            "rule_section_index": 2,
                            "source_section_index": 4,
                            "y_le": 13.5,
                            "mirrored": False,
                            "side": "right_interior",
                        },
                        {"rule_section_index": 3, "y_le": 16.5, "side": "right_tip"},
                    ]
                }
            ]
        },
    )


def test_export_source_audit_confirms_single_rule_internal_station_source(
    tmp_path: Path,
):
    step_path = tmp_path / "esp_runtime" / "normalized.stp"
    step_path.parent.mkdir(parents=True)
    step_path.write_text("STEP placeholder\n", encoding="utf-8")
    _write_csm(step_path.parent / "rebuild.csm")
    _write_lineage(step_path.parent / "topology_lineage_report.json")

    report = build_main_wing_station_seam_export_source_audit_report(
        shape_fix_feasibility_path=_write_shape_fix(
            tmp_path / "shape_fix.json",
            step_path,
        ),
        topology_fixture_path=_write_topology_fixture(tmp_path / "fixture.json"),
    )

    assert (
        report.audit_status
        == "single_rule_internal_station_export_source_confirmed"
    )
    assert report.production_default_changed is False
    assert report.csm_summary["single_rule_multi_section_loft"] is True
    assert {
        mapping["csm_station_role"] for mapping in report.target_station_mappings
    } == {"internal_station"}
    assert "generic_occt_edge_fix_sweeps_exhausted_without_recovery" in (
        report.engineering_findings
    )
    assert report.next_actions[0] == (
        "prototype_station_seam_export_strategy_before_solver_budget"
    )


def test_write_export_source_audit_report(tmp_path: Path):
    step_path = tmp_path / "esp_runtime" / "normalized.stp"
    step_path.parent.mkdir(parents=True)
    step_path.write_text("STEP placeholder\n", encoding="utf-8")
    _write_csm(step_path.parent / "rebuild.csm")
    _write_lineage(step_path.parent / "topology_lineage_report.json")

    written = write_main_wing_station_seam_export_source_audit_report(
        tmp_path / "out",
        shape_fix_feasibility_path=_write_shape_fix(
            tmp_path / "shape_fix.json",
            step_path,
        ),
        topology_fixture_path=_write_topology_fixture(tmp_path / "fixture.json"),
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_export_source_audit.v1"
    )
    assert (
        payload["audit_status"]
        == "single_rule_internal_station_export_source_confirmed"
    )
    assert "Main Wing Station Seam Export Source Audit v1" in markdown
