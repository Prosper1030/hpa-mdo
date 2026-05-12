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


def test_checker_flags_missed_current_channel_ready_and_rfq_control_patterns(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    docs_dir = tmp_path / "docs"
    work_orders_dir = docs_dir / "work_orders"
    work_orders_dir.mkdir(parents=True)
    (tmp_path / "output" / "baseline_A_team_release").mkdir(parents=True)

    (tmp_path / "README.md").write_text(
        "\n".join(
            [
                "verdict 是 `carbon_tube_rfq_pack_ready`：可以拿去問 vendor。",
                "`baseline_A_release_system_ready`：這包把 current pathfinder 轉成 team release package。",
                "`mass_cg_margin_ledger_ready`：gross screening mass `106.828608 kg`。",
                "RFQ 語言目前控制 positive half-wing `y`、structural `16.5 m` half-span、3 m splice stations。",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "CURRENT_MAINLINE.md").write_text(
        "\n".join(
            [
                "The 16.5 m half-span is local/splice screening only, not procurement truth.",
                "RFQ language controls structural 16.5 m half-span and splice station/span language.",
                "WO-005 carbon tube RFQ pack 的 verdict 是 `carbon_tube_rfq_pack_ready`；下一個 P1 是 WO-006 main-wing SU2 baseline validation。",
            ]
        ),
        encoding="utf-8",
    )
    (docs_dir / "README.md").write_text(
        "\n".join(
            [
                "| Baseline A team release | release verdict `baseline_A_release_system_ready` |",
                "| Baseline A mass ledger | ledger verdict `mass_cg_margin_ledger_ready` |",
                "| Carbon tube RFQ | verdict `carbon_tube_rfq_pack_ready`; controls RFQ station/span/splice language |",
                "目前下一個建議任務是 WO-006 main-wing SU2 baseline validation",
            ]
        ),
        encoding="utf-8",
    )
    (docs_dir / "AI_WORK_ORDER_PROTOCOL.md").write_text(
        "WO-006 is next after this cleanup.\n",
        encoding="utf-8",
    )
    (work_orders_dir / "QUEUE.md").write_text(
        "WO-006 | P1 | queued | Main-Wing SU2 Baseline Validation | next recommended task\n",
        encoding="utf-8",
    )

    violations = mod.check_authority_violations(tmp_path)
    violation_ids = {violation.rule_id for violation in violations}

    assert "active_ready_verdict_without_repair_boundary" in violation_ids
    assert "rfq_controls_16p5_span_station_splice" in violation_ids
    assert "wo006_next_without_data_authority_prerequisite" in violation_ids
    assert "sixteenp5_not_procurement_truth_then_rfq_controls" in violation_ids


def test_historical_generated_ready_verdicts_are_allowed_when_repair_labeled(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    docs_dir = tmp_path / "docs"
    work_orders_dir = docs_dir / "work_orders"
    work_orders_dir.mkdir(parents=True)
    (tmp_path / "output" / "baseline_A_team_release").mkdir(parents=True)

    safe_text = (
        "Old WO-001 to WO-005 verdicts such as `baseline_A_release_system_ready`, "
        "`mass_cg_margin_ledger_ready`, and `carbon_tube_rfq_pack_ready` are "
        "historical/generated evidence under data-authority repair, not active "
        "release, mass, RFQ, procurement, or current truth."
    )
    for rel in (
        "README.md",
        "CURRENT_MAINLINE.md",
        "docs/README.md",
        "docs/AI_WORK_ORDER_PROTOCOL.md",
        "docs/work_orders/QUEUE.md",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            safe_text
            + "\n16.5 m is local/splice screening only, not RFQ control, shop span, or procurement truth.\n"
            + "WO-006 remains paused until the checker passes and data-authority restoration is complete.\n",
            encoding="utf-8",
        )

    assert mod.check_authority_violations(tmp_path) == []


def test_checker_flags_paused_wo006_next_recommended_goal_context(tmp_path: Path) -> None:
    mod = _load_module()
    work_orders_dir = tmp_path / "docs" / "work_orders"
    work_orders_dir.mkdir(parents=True)

    (work_orders_dir / "QUEUE.md").write_text(
        "\n".join(
            [
                "# Baseline A Work Order Queue",
                "",
                "| ID | Priority | Status | Work order | Owner lane | Why now |",
                "|---|---:|---|---|---|---|",
                "| WO-006 | P1 | paused | Main-Wing SU2 Baseline Validation | aero validation | Paused until data authority is restored |",
                "",
                "## Next Recommended Work Order",
                "",
                "```text",
                "/goal In /Volumes/Samsung SSD/hpa-mdo, execute WO-006: Main-Wing SU2 Baseline Validation.",
                "",
                "Task:",
                "Build a bounded main-wing SU2 baseline validation for the current Baseline A pathfinder.",
                "```",
            ]
        ),
        encoding="utf-8",
    )

    violations = mod.check_authority_violations(tmp_path)
    violation_ids = {violation.rule_id for violation in violations}

    assert "wo006_next_recommended_goal_without_prerequisite" in violation_ids
    assert "wo006_paste_ready_goal_while_paused" in violation_ids
    assert "queue_paused_wo006_but_recommended_goal_executes_wo006" in violation_ids


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
