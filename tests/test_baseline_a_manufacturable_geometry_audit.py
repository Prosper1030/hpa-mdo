from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "baseline_a_manufacturable_geometry_audit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "baseline_a_manufacturable_geometry_audit",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_audit_verdict_and_categories_are_work_order_contract() -> None:
    module = _load_module()

    audit = module.build_manufacturable_geometry_audit()
    rows = audit["geometry_discretization_rows"]
    categories = {row["category"] for row in rows}

    assert audit["verdict"] == "geometry_freeze_needs_fix"
    assert categories <= module.ALLOWED_CATEGORIES
    assert "smooth_and_manufacturable" in categories
    assert "smooth_but_not_manufacturable" in categories
    assert "manufacturable_but_geometry_discontinuity_risk" in categories
    assert "needs_redesign" not in categories


def test_json_warning_contract_contains_required_fields_and_reopen_boundary() -> None:
    module = _load_module()

    audit = module.build_manufacturable_geometry_audit()
    warning = audit["smoothness_warning"]

    assert warning["schema_version"] == module.SCHEMA_VERSION
    assert warning["work_order"] == "WO-004 Manufacturable Smoothness / Discretization Audit"
    assert warning["verdict"] == "geometry_freeze_needs_fix"
    assert warning["checked_sources"]
    assert warning["reopen_triggers"]["manufacturing_discretization_forces_reopen"] == (
        "not_triggered"
    )
    assert warning["next_recommended_work_order"] == "WO-005 Carbon Tube RFQ + Procurement Pack"

    warning_ids = {item["id"] for item in warning["warnings"]}
    assert "span_extent_contract_mismatch" in warning_ids
    assert "splice_station_contract_mismatch" in warning_ids
    assert "inboard_splice_zero_margin_rfq_warning" in warning_ids


def test_rib_and_splice_findings_preserve_engineering_numbers() -> None:
    module = _load_module()

    audit = module.build_manufacturable_geometry_audit()
    rows = {row["finding_id"]: row for row in audit["geometry_discretization_rows"]}

    rib = rows["rib_0p30_materialized"]
    assert rib["category"] == "smooth_and_manufacturable"
    assert "max materialized bay 0.297063 m" in rib["observed"]
    assert "121 full-wing stations" in rib["observed"]

    relaxed = rows["release_vs_selected_stiffness_rib_spacing"]
    assert relaxed["category"] == "smooth_but_not_manufacturable"
    assert "0.345 m" in relaxed["observed"]

    splice = rows["splice_station_contract_mismatch"]
    assert splice["category"] == "manufacturable_but_geometry_discontinuity_risk"
    assert "3.0/6.0/9.0/12.0/15.0 m" in splice["observed"]
    assert "1.455/4.365/7.574/10.509/13.462 m" in splice["observed"]


def test_output_package_writes_required_files(tmp_path: Path) -> None:
    module = _load_module()

    paths = module.write_manufacturable_geometry_audit_package(output_dir=tmp_path)

    assert paths["report_md"].name == "manufacturable_geometry_audit.md"
    assert paths["geometry_csv"].name == "geometry_discretization_report.csv"
    assert paths["warning_json"].name == "smoothness_warning.json"
    for path in paths.values():
        assert path.exists()

    warning = json.loads(paths["warning_json"].read_text(encoding="utf-8"))
    assert warning["verdict"] == "geometry_freeze_needs_fix"

    with paths["geometry_csv"].open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    assert set(rows[0]) == set(module.CSV_FIELDNAMES)
    assert {row["category"] for row in rows} <= module.ALLOWED_CATEGORIES

    report = paths["report_md"].read_text(encoding="utf-8")
    assert "geometry_freeze_needs_fix" in report
    assert "not final manufacturing drawing sign-off" in report
