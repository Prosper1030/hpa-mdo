from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_rib_local_detail_geometry_freeze.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_rib_local_detail_geometry_freeze", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_freeze_package_writes_all_outputs(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    for key, p in paths.items():
        assert p.exists(), f"missing output: {key} -> {p}"


def test_freeze_json_schema_version(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    freeze = json.loads(paths["freeze_json"].read_text())
    assert freeze["schema_version"] == mod.SCHEMA_VERSION


def test_spar_tubes_derived_from_config(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    freeze = json.loads(paths["freeze_json"].read_text())
    ms = freeze["spar_tubes"]["main_spar"]
    rs = freeze["spar_tubes"]["rear_spar"]
    assert ms["od_m"] > 0
    assert ms["wall_m"] > 0
    assert rs["od_m"] > 0
    assert rs["wall_m"] > 0
    assert ms["od_m"] >= rs["od_m"], "main spar OD should be >= rear spar OD"
    assert ms["confidence"] == "design_derived"
    assert rs["confidence"] == "design_derived"


def test_spar_tubes_within_depth_constraint(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    freeze = json.loads(paths["freeze_json"].read_text())
    spar_data = freeze["spar_tubes"]
    assert freeze["spar_tubes"]["main_spar"]["od_m"] <= spar_data["depth_main_m"] + 1e-6
    assert freeze["spar_tubes"]["rear_spar"]["od_m"] <= spar_data["depth_rear_m"] + 1e-6


def test_all_missing_data_items_filled(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    freeze = json.loads(paths["freeze_json"].read_text())
    reg = freeze["missing_data_register_status"]
    expected_keys = [
        "adhesive_shear_allowable_pa",
        "adhesive_peel_allowable_pa",
        "bondline_width_thickness_fillet",
        "collar_material_thickness_contact_width",
        "spar_tube_od_wall_material",
        "balsa_cap_face_properties",
        "eps_core_properties",
        "skin_material_thickness_attachment",
    ]
    for k in expected_keys:
        assert k in reg, f"missing data key not filled: {k}"
        assert reg[k] != "supplier_or_coupon_missing", f"key still placeholder: {k}"


def test_preliminary_margins_all_present(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    freeze = json.loads(paths["freeze_json"].read_text())
    marg = freeze["preliminary_margins"]
    expected_coupons = [
        "C01_cap_shear_transfer",
        "C02_main_spar_bond_shear",
        "C03_rear_spar_bond_shear",
        "C04_bond_peel_main",
        "C05_collar_bearing",
        "C06_tube_crush_main",
        "C06_tube_crush_rear",
        "C07_skin_sag",
    ]
    for coupon in expected_coupons:
        assert coupon in marg, f"missing coupon margin: {coupon}"
        assert "margin" in marg[coupon], f"margin key missing in {coupon}"


def test_preliminary_margins_all_pass(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    report = json.loads(paths["report_json"].read_text())
    assert report["all_pass"] is True, (
        f"one or more preliminary margins failed: {report['preliminary_margin_summary']}"
    )
    assert report["worst_margin"] > 0.0, "worst margin is not positive"


def test_report_json_worst_margin_positive(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    report = json.loads(paths["report_json"].read_text())
    assert report["worst_margin"] > 0.0


def test_apdl_skeleton_no_negative_placeholders(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    apdl_text = paths["apdl_filled"].read_text()
    import re as _re
    placeholder_pattern = _re.compile(r"=\s*-1\s*$")
    for line in apdl_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("!"):
            continue
        if placeholder_pattern.search(stripped):
            pytest.fail(f"unfilled placeholder found: {stripped!r}")


def test_apdl_supplier_flag_cleared(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    apdl_text = paths["apdl_filled"].read_text()
    assert "SUPPLIER_DATA_REQUIRED = 0" in apdl_text


def test_freeze_csv_has_expected_rows(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    import csv as _csv
    with open(paths["freeze_csv"], newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    params = {r["parameter"] for r in rows}
    for key in ("main_spar_od_m", "adhesive_shear_allowable_pa", "skin_thickness_m"):
        assert key in params, f"parameter missing from freeze CSV: {key}"


def test_report_md_contains_claim_boundary(tmp_path: Path) -> None:
    mod = _load_module()
    paths = mod.write_geometry_freeze_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    md = paths["report_md"].read_text()
    assert "Claim Boundary" in md or "claim_boundary" in md.lower()
    assert "preliminary" in md.lower()
