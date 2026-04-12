from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from hpa_mdo.autoresearch import (
    AutoresearchPrimaryConfig,
    build_producer_cli_argv,
    default_history_dir,
    load_primary_mass_run,
)
from hpa_mdo.autoresearch import __main__ as autoresearch_main
from hpa_mdo.autoresearch import consumer as consumer_impl
from hpa_mdo.autoresearch import history as history_impl


def _write_decision_json(path: Path, mass_kg: float = 10.0, margin_mm: float = 99.0) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_name": consumer_impl.EXPECTED_DECISION_SCHEMA_NAME,
                "schema_version": consumer_impl.EXPECTED_DECISION_SCHEMA_VERSION,
                "status": "complete",
                "decision_layer_config": {"schema_version": "v1"},
                "designs": [
                    {
                        "design_class": "primary",
                        "design_label": "Primary design",
                        "slot_status": "selected",
                        "fallback_reason_code": "none",
                        "geometry_seed": "selected",
                        "geometry_choice": [4, 0, 0, 2, 0],
                        "material_choice": {
                            "main_spar_family": "main_light_ud",
                            "rear_outboard_reinforcement_pkg": "ob_none",
                        },
                        "mass_kg": mass_kg,
                        "raw_main_tip_mm": 1700.0,
                        "raw_rear_tip_mm": 2400.0,
                        "raw_max_uz_mm": 2400.0,
                        "psi_u_all_mm": 2401.0,
                        "candidate_margin_mm": margin_mm,
                        "rule_trigger": "rule",
                        "selection_rationale": "why",
                        "qualifying_candidate_count": 10,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_build_producer_cli_argv_uses_same_python_and_passes_through_flags(tmp_path: Path) -> None:
    config = AutoresearchPrimaryConfig(
        output_dir=tmp_path / "out",
        config_path=tmp_path / "config.yaml",
        primary_margin_floor_mm=60.0,
        python_executable=Path("/tmp/custom-python"),
    )

    argv = build_producer_cli_argv(config)

    assert argv[:3] == ["/tmp/custom-python", "-m", "hpa_mdo.producer"]
    assert "--output-dir" in argv
    assert str((tmp_path / "out").resolve()) in argv
    assert "--config" in argv
    assert str((tmp_path / "config.yaml").resolve()) in argv
    assert "--primary-margin-floor-mm" in argv


def test_load_primary_mass_run_consumes_manifest_and_scores_primary_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    decision_path = tmp_path / "run" / "direct_dual_beam_v2m_joint_material_decision_interface.json"
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    _write_decision_json(decision_path, mass_kg=10.25, margin_mm=88.0)
    manifest = {
        "producer_name": "hpa_mdo.dual_beam_joint_decision",
        "producer_interface_version": "v1",
        "artifacts": {
            "output_dir": str(decision_path.parent),
            "decision_json_path": str(decision_path),
        },
    }

    def _fake_run(argv, cwd, capture_output, text, check):
        assert argv[:3] == [sys.executable, "-m", "hpa_mdo.producer"]
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(manifest),
            stderr="",
        )

    monkeypatch.setattr(consumer_impl.subprocess, "run", _fake_run)

    run = load_primary_mass_run(AutoresearchPrimaryConfig(output_dir=tmp_path / "run"))

    assert run.primary_mass_kg == 10.25
    assert run.primary_margin_mm == 88.0
    assert run.score == -10.25
    assert run.primary_slot_status == "selected"
    assert run.decision_json_path == decision_path.resolve()


def test_autoresearch_cli_prints_score_line(capsys, monkeypatch, tmp_path: Path) -> None:
    decision_path = tmp_path / "run" / "decision.json"
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    _write_decision_json(decision_path, mass_kg=10.5, margin_mm=77.0)
    fake_run = consumer_impl.AutoresearchPrimaryRun(
        config=AutoresearchPrimaryConfig(output_dir=tmp_path / "run"),
        producer_command=(sys.executable, "-m", "hpa_mdo.producer", "--output-dir", str(tmp_path / "run")),
        manifest={
            "producer_name": "hpa_mdo.dual_beam_joint_decision",
            "producer_interface_version": "v1",
        },
        decision_interface={
            "schema_name": consumer_impl.EXPECTED_DECISION_SCHEMA_NAME,
            "schema_version": consumer_impl.EXPECTED_DECISION_SCHEMA_VERSION,
            "status": "complete",
        },
        decision_json_path=decision_path.resolve(),
        primary_design={"design_class": "primary"},
        primary_mass_kg=10.5,
        primary_margin_mm=77.0,
        primary_slot_status="selected",
        primary_fallback_reason_code="none",
        score=-10.5,
    )
    monkeypatch.setattr(autoresearch_main, "load_primary_mass_run", lambda config: fake_run)
    monkeypatch.setattr(history_impl, "resolve_git_commit_hash", lambda cwd=None: "abc123def456")

    exit_code = autoresearch_main.main(["--output-dir", str(tmp_path / "run")])
    captured = capsys.readouterr()
    history_dir = default_history_dir(tmp_path / "run")
    latest_record = json.loads(
        history_impl.latest_record_path(history_dir).read_text(encoding="utf-8")
    )

    assert exit_code == 0
    assert "Score rule: -Primary.mass_kg" in captured.out
    assert "分數: -10.500000" in captured.out
    assert "Run record:" in captured.out
    assert latest_record["score"] == -10.5
    assert latest_record["primary_mass_kg"] == 10.5
    assert latest_record["git_commit_hash"] == "abc123def456"
    assert Path(latest_record["decision_json_snapshot_path"]).exists()


def test_autoresearch_cli_records_failure_runs(capsys, monkeypatch, tmp_path: Path) -> None:
    def _raise_failure(config):
        raise consumer_impl.AutoresearchConsumerError("boom")

    monkeypatch.setattr(autoresearch_main, "load_primary_mass_run", _raise_failure)
    monkeypatch.setattr(history_impl, "resolve_git_commit_hash", lambda cwd=None: "deadbeef")

    exit_code = autoresearch_main.main(["--output-dir", str(tmp_path / "run")])
    captured = capsys.readouterr()
    latest_record = json.loads(
        history_impl.latest_record_path(default_history_dir(tmp_path / "run")).read_text(encoding="utf-8")
    )

    assert exit_code == 1
    assert "autoresearch consumer failed: boom" in captured.out
    assert latest_record["status"] == "failed"
    assert latest_record["error_message"] == "boom"
    assert latest_record["score"] is None


def test_autoresearch_summary_cli_lists_recent_runs(capsys, tmp_path: Path) -> None:
    history_dir = tmp_path / "history"
    records = [
        history_impl.AutoresearchRunRecord(
            run_record_schema_name=history_impl.RUN_RECORD_SCHEMA_NAME,
            run_record_schema_version=history_impl.RUN_RECORD_SCHEMA_VERSION,
            run_id="run-001",
            run_timestamp_utc="2026-04-12T00:00:00Z",
            status="complete",
            score_name=history_impl.SCORE_NAME,
            score_rule=history_impl.SCORE_RULE,
            score=-10.0,
            primary_mass_kg=10.0,
            primary_margin_mm=70.0,
            output_dir=(tmp_path / "run_a").resolve(),
            decision_json_path=(tmp_path / "run_a" / "decision.json").resolve(),
            decision_json_snapshot_path=(tmp_path / "history" / "snap_a.json").resolve(),
            decision_schema_name=consumer_impl.EXPECTED_DECISION_SCHEMA_NAME,
            decision_schema_version=consumer_impl.EXPECTED_DECISION_SCHEMA_VERSION,
            producer_name="hpa_mdo.dual_beam_joint_decision",
            producer_interface_version="v1",
            git_commit_hash="abc",
            primary_slot_status="selected",
            primary_fallback_reason_code="none",
        ),
        history_impl.AutoresearchRunRecord(
            run_record_schema_name=history_impl.RUN_RECORD_SCHEMA_NAME,
            run_record_schema_version=history_impl.RUN_RECORD_SCHEMA_VERSION,
            run_id="run-002",
            run_timestamp_utc="2026-04-12T00:05:00Z",
            status="complete",
            score_name=history_impl.SCORE_NAME,
            score_rule=history_impl.SCORE_RULE,
            score=-9.5,
            primary_mass_kg=9.5,
            primary_margin_mm=66.0,
            output_dir=(tmp_path / "run_b").resolve(),
            decision_json_path=(tmp_path / "run_b" / "decision.json").resolve(),
            decision_json_snapshot_path=(tmp_path / "history" / "snap_b.json").resolve(),
            decision_schema_name=consumer_impl.EXPECTED_DECISION_SCHEMA_NAME,
            decision_schema_version=consumer_impl.EXPECTED_DECISION_SCHEMA_VERSION,
            producer_name="hpa_mdo.dual_beam_joint_decision",
            producer_interface_version="v1",
            git_commit_hash="def",
            primary_slot_status="selected",
            primary_fallback_reason_code="none",
        ),
        history_impl.AutoresearchRunRecord(
            run_record_schema_name=history_impl.RUN_RECORD_SCHEMA_NAME,
            run_record_schema_version=history_impl.RUN_RECORD_SCHEMA_VERSION,
            run_id="run-003",
            run_timestamp_utc="2026-04-12T00:10:00Z",
            status="failed",
            score_name=history_impl.SCORE_NAME,
            score_rule=history_impl.SCORE_RULE,
            score=None,
            primary_mass_kg=None,
            primary_margin_mm=None,
            output_dir=(tmp_path / "run_c").resolve(),
            decision_json_path=None,
            decision_json_snapshot_path=None,
            decision_schema_name=None,
            decision_schema_version=None,
            producer_name=None,
            producer_interface_version=None,
            git_commit_hash="ghi",
            primary_slot_status=None,
            primary_fallback_reason_code=None,
            error_message="producer failed",
        ),
    ]
    for record in records:
        history_impl.append_run_record(record, history_dir)

    json_out = tmp_path / "summary.json"
    exit_code = autoresearch_main.main(
        ["summary", "--history-dir", str(history_dir), "--limit", "2", "--json-out", str(json_out)]
    )
    captured = capsys.readouterr()
    summary = json.loads(json_out.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Total runs: 3" in captured.out
    assert "Best score: -9.500000" in captured.out
    assert "run_id=run-003" in captured.out
    assert summary["best_run"]["run_id"] == "run-002"
    assert len(summary["recent_runs"]) == 2
