from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_carbon_tube_rfq_pack.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_carbon_tube_rfq_pack", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path: Path) -> tuple[dict[str, Path], Path]:
    mod = _load_module()
    output_dir = tmp_path / "baseline_A_team_release"
    paths = mod.write_carbon_tube_rfq_pack(output_dir=output_dir)
    return paths, output_dir


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_rfq_pack_writes_all_required_artifacts(tmp_path: Path) -> None:
    paths, output_dir = _run(tmp_path)

    expected = {
        "carbon_tube_rfq_spec.md",
        "carbon_tube_rfq_pack.md",
        "controlled_station_span_splice_manifest.csv",
        "vendor_questionnaire.md",
        "procurement_risk_register.json",
        "tube_splice_tolerance_requirements.csv",
        "rfq_daily_review.md",
    }
    assert expected == {path.name for path in paths.values()}
    for name in expected:
        assert (output_dir / name).exists(), name

    pack = (output_dir / "carbon_tube_rfq_pack.md").read_text(encoding="utf-8")
    assert "carbon_tube_rfq_pack_draft_vendor_screening" in pack
    assert "not purchase-ready" in pack
    assert "does not block bounded WO-006 aero calibration" in pack
    assert "QPROP/XROTOR is independent" in pack


def test_station_manifest_carries_wo004_conventions_and_warnings(tmp_path: Path) -> None:
    _, output_dir = _run(tmp_path)
    rows = {
        row["manifest_id"]: row
        for row in _csv_rows(output_dir / "controlled_station_span_splice_manifest.csv")
    }

    assert rows["rfq_station_convention"]["status"] == "draft_vendor_screening_only"
    assert rows["structural_half_span_basis"]["rfq_y_m"] == "16.500000"
    assert rows["structural_half_span_basis"]["status"] == (
        "local_splice_screening_not_procurement_truth"
    )
    assert "not current pipeline half-span" in rows["structural_half_span_basis"]["rfq_language"]
    assert rows["aero_half_span_reference"]["source_y_m"] == "17.166143"
    assert rows["materialized_rib_extent_reference"]["source_y_m"] == "17.324041"
    assert rows["release_rib_spacing_basis"]["source_y_m"] == "0.300000"
    assert rows["selected_stiffness_spacing_label"]["status"] == "not_rfq_controlled_dimension"
    assert "0.345" in rows["selected_stiffness_spacing_label"]["rfq_language"]

    for y in (3, 6, 9, 12, 15):
        row = rows[f"transport_splice_y{y:02d}"]
        assert row["status"] == "draft_vendor_screening_only"
        assert row["wo004_warning_carried"] == "splice_station_contract_mismatch"
        assert "nearest materialized spar-joint rib" in row["rfq_language"]

    for key in (
        "transport_station_contract_open",
        "control_station_contract_open",
        "airfoil_transition_contract_open",
        "twist_transition_contract_open",
    ):
        assert rows[key]["status"] == "missing_contract_not_drawing_control"


def test_tolerance_table_keeps_y3_splice_warning_and_tube_basis(tmp_path: Path) -> None:
    _, output_dir = _run(tmp_path)
    rows = {
        row["requirement_id"]: row
        for row in _csv_rows(output_dir / "tube_splice_tolerance_requirements.csv")
    }

    assert rows["main_spar_od_mm"]["nominal_value"] == "100.0"
    assert rows["main_spar_id_mm"]["nominal_value"] == "98.0"
    assert rows["rear_spar_od_mm"]["nominal_value"] == "80.0"
    assert rows["rear_spar_id_mm"]["nominal_value"] == "78.0"
    assert rows["max_shipping_segment_m"]["nominal_value"] == "3.0"
    assert rows["spigot_wall_y3_mm"]["nominal_value"] == "1.02"
    assert rows["spigot_wall_y3_mm"]["evidence_status"] == "critical_screening_warning"
    assert rows["spigot_overlap_each_side_mm"]["nominal_value"] == "400.0"
    assert rows["ovality_tolerance"]["evidence_status"] == "open_vendor_response"


def test_risk_register_names_procurement_and_reopen_review_triggers(tmp_path: Path) -> None:
    _, output_dir = _run(tmp_path)
    register = json.loads(
        (output_dir / "procurement_risk_register.json").read_text(encoding="utf-8")
    )

    assert register["schema_version"] == "baseline_a_carbon_tube_rfq_pack_v1"
    assert register["verdict"] == "carbon_tube_rfq_pack_draft_vendor_screening"
    assert register["authority_status"] == "blocks_release_procurement_only"
    assert register["wo006_impact"] == "does_not_block_bounded_aero_calibration"
    risks = {row["risk_id"]: row for row in register["risk_register"]}
    assert "tube_family_unavailable" in risks
    assert "y3_splice_zero_margin_consumed" in risks
    assert "station_convention_mixed" in risks
    assert "baseline_A_reopen_watch" in register
    assert any("spar OD" in item for item in register["baseline_A_reopen_watch"])


def test_vendor_questionnaire_requests_supplier_data_needed_for_screening(tmp_path: Path) -> None:
    _, output_dir = _run(tmp_path)
    questionnaire = (output_dir / "vendor_questionnaire.md").read_text(encoding="utf-8")

    for phrase in (
        "ovality",
        "straightness",
        "wall-thickness",
        "surface finish",
        "witness coupons",
        "material certificates",
        "minimum order quantity",
    ):
        assert phrase in questionnaire


def test_context_uses_current_splice_and_rib_evidence() -> None:
    mod = _load_module()
    context = mod.build_rfq_context()

    assert context["splice"]["worst_joint_y_m"] == pytest.approx(3.0)
    assert context["splice"]["worst_joint_margin"] == pytest.approx(0.0)
    assert context["rib_trace"]["target_spacing_m"] == pytest.approx(0.30)
    assert context["rib_trace"]["full_wing_station_count"] == 121
    assert context["main_tube"]["product"] == "CF-HM-100x98"
    assert context["rear_tube"]["product"] == "CF-HM-80x78"
