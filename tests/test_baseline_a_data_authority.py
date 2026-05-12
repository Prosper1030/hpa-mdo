from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "check_baseline_a_data_authority.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_baseline_a_data_authority", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_checker_flags_known_suspect_promotions(tmp_path: Path) -> None:
    mod = _load_module()
    release_dir = tmp_path / "output" / "baseline_A_team_release"
    release_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text(
        "\n".join(
            [
                "Baseline A current design gross mass is 106.828608 kg.",
                "Use 16.5 m as current pipeline half-span and procurement truth.",
                "WO-003 -9 W is the current full-pipeline mission verdict.",
                "Coupon/FEM readiness is final aircraft sign-off.",
                "QPROP/XROTOR resolves the structural blocker verdict.",
                "The RFQ is purchase-ready while mass/span authority is conflict-blocked.",
            ]
        ),
        encoding="utf-8",
    )

    violations = mod.check_authority_violations(tmp_path)
    violation_ids = {violation.rule_id for violation in violations}

    assert "suspect_mass_as_current_truth" in violation_ids
    assert "suspect_half_span_as_procurement_truth" in violation_ids
    assert "stage0_power_as_current_mission_verdict" in violation_ids
    assert "screening_readiness_as_final_signoff" in violation_ids
    assert "propulsion_mixed_into_structure_verdict" in violation_ids
    assert "rfq_purchase_ready_while_conflict_blocked" in violation_ids


def test_audit_artifacts_include_inventory_conflicts_authority_and_gate_debt(tmp_path: Path) -> None:
    mod = _load_module()
    docs_dir = tmp_path / "docs"
    reports_dir = docs_dir / "reports"
    release_dir = tmp_path / "output" / "baseline_A_team_release"
    current_dir = tmp_path / "output" / "current_pathfinder_tail"
    phase_dir = tmp_path / "output" / "phase99_legacy"
    for path in (reports_dir, release_dir, current_dir, phase_dir):
        path.mkdir(parents=True)
    (tmp_path / "README.md").write_text(
        "Current design mass authority is 98.5 kg. "
        "106.828608 kg is suspect screening aggregate only.\n",
        encoding="utf-8",
    )
    (tmp_path / "CURRENT_MAINLINE.md").write_text(
        "Current pipeline span evidence is 34.332286 m full span and "
        "17.166143 m half-span; 16.5 m is splice screening only.\n",
        encoding="utf-8",
    )
    (reports_dir / "lane.md").write_text(
        "P1/C04 remains coupon/local FEM readiness, not final aircraft sign-off.\n",
        encoding="utf-8",
    )
    (release_dir / "summary.md").write_text(
        "WO-005 RFQ pack is draft/vendor-screening only until authority is repaired.\n",
        encoding="utf-8",
    )
    (current_dir / "tail.json").write_text(
        json.dumps({"half_span_m": 17.166143, "status": "screening"}),
        encoding="utf-8",
    )
    (phase_dir / "old.md").write_text(
        "Legacy phase mass estimate 106.828608 kg, not current truth.\n",
        encoding="utf-8",
    )

    result = mod.write_audit_artifacts(tmp_path)

    inventory_csv = release_dir / "data_authority_claim_inventory.csv"
    inventory_json = release_dir / "data_authority_claim_inventory.json"
    conflict_csv = release_dir / "data_authority_conflict_register.csv"
    authority_csv = release_dir / "data_authority_table.csv"
    authority_json = release_dir / "data_authority_table.json"
    audit_md = reports_dir / "baseline_A_data_authority_audit.md"
    gate_debt_md = reports_dir / "baseline_A_gate_debt_register.md"
    hygiene_md = reports_dir / "repo_channel_hygiene_plan.md"

    for path in (
        inventory_csv,
        inventory_json,
        conflict_csv,
        authority_csv,
        authority_json,
        audit_md,
        gate_debt_md,
        hygiene_md,
    ):
        assert path.exists(), path

    assert result.files_scanned >= 6
    assert result.claims_extracted >= 4
    conflict_categories = {
        row["category"] for row in csv.DictReader(conflict_csv.open(encoding="utf-8"))
    }
    assert "mass / CG / rebalance" in conflict_categories
    assert "span / half-span / station / rib spacing" in conflict_categories
    authority_rows = {
        row["authority_id"]: row
        for row in csv.DictReader(authority_csv.open(encoding="utf-8"))
    }
    assert authority_rows["design_gross_mass_98p5"]["authority_class"] == "user_authority"
    assert authority_rows["p1_screening_mass_106p828608"]["authority_class"] == (
        "screening_estimate"
    )


def test_current_main_and_release_docs_do_not_promote_suspect_authority() -> None:
    mod = _load_module()

    violations = mod.check_authority_violations(_REPO_ROOT)

    assert violations == []
