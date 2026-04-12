from __future__ import annotations

import json
import sys
from pathlib import Path

from hpa_mdo.autoresearch import campaign as campaign_impl
from hpa_mdo.autoresearch import consumer as consumer_impl
from hpa_mdo.autoresearch.consumer import AutoresearchPrimaryConfig
from hpa_mdo.provenance import build_joint_decision_input_provenance


def _write_input_sources(base_dir: Path) -> tuple[Path, Path, Path]:
    config_path = base_dir / "config.yaml"
    design_report_path = base_dir / "design_report.txt"
    v2m_summary_json_path = base_dir / "v2m_summary.json"
    config_path.write_text("wing: blackcat\n", encoding="utf-8")
    design_report_path.write_text("margin report\n", encoding="utf-8")
    v2m_summary_json_path.write_text(json.dumps({"summary": "ok"}) + "\n", encoding="utf-8")
    return config_path, design_report_path, v2m_summary_json_path


def _write_decision_json(path: Path, *, mass_kg: float, margin_mm: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_name": consumer_impl.EXPECTED_DECISION_SCHEMA_NAME,
                "schema_version": consumer_impl.EXPECTED_DECISION_SCHEMA_VERSION,
                "status": "complete",
                "designs": [
                    {
                        "design_class": "primary",
                        "slot_status": "selected",
                        "fallback_reason_code": "none",
                        "mass_kg": mass_kg,
                        "candidate_margin_mm": margin_mm,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _build_fake_run(
    config: AutoresearchPrimaryConfig,
    *,
    decision_path: Path,
    mass_kg: float,
    margin_mm: float,
) -> consumer_impl.AutoresearchPrimaryRun:
    input_provenance = build_joint_decision_input_provenance(
        config_path=config.config_path,
        design_report_path=config.design_report_path,
        v2m_summary_json_path=config.v2m_summary_json_path,
        output_dir=config.output_dir,
        primary_margin_floor_mm=config.primary_margin_floor_mm,
        balanced_min_margin_mm=config.balanced_min_margin_mm,
        balanced_max_mass_delta_kg=config.balanced_max_mass_delta_kg,
        conservative_mode=config.conservative_mode,
    )
    return consumer_impl.AutoresearchPrimaryRun(
        config=config,
        producer_command=(sys.executable, "-m", "hpa_mdo.producer", "--output-dir", str(config.output_dir)),
        manifest={
            "producer_name": "hpa_mdo.dual_beam_joint_decision",
            "producer_interface_version": "v1",
            "producer_cli_overrides": input_provenance["producer_cli_overrides"],
            "input_provenance": input_provenance,
        },
        decision_interface={
            "schema_name": consumer_impl.EXPECTED_DECISION_SCHEMA_NAME,
            "schema_version": consumer_impl.EXPECTED_DECISION_SCHEMA_VERSION,
            "status": "complete",
        },
        decision_json_path=decision_path.resolve(),
        primary_design={"design_class": "primary"},
        primary_mass_kg=mass_kg,
        primary_margin_mm=margin_mm,
        primary_slot_status="selected",
        primary_fallback_reason_code="none",
        score=-mass_kg,
    )


def test_load_campaign_definition_merges_defaults_and_resolves_paths(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    config_path, design_report_path, v2m_summary_json_path = _write_input_sources(inputs_dir)
    campaign_config = tmp_path / "campaign.yaml"
    campaign_config.write_text(
        "\n".join(
            [
                "campaign_name: margin-floor-sweep",
                "results_dir: results",
                "defaults:",
                f"  config: {config_path.relative_to(tmp_path)}",
                f"  design_report: {design_report_path.relative_to(tmp_path)}",
                f"  v2m_summary_json: {v2m_summary_json_path.relative_to(tmp_path)}",
                "  producer_overrides:",
                "    primary_margin_floor_mm: 60.0",
                "runs:",
                "  - name: baseline",
                "    output_dir: output/baseline",
                "  - name: relaxed",
                "    output_dir: output/relaxed",
                "    producer_overrides:",
                "      primary_margin_floor_mm: null",
                "      balanced_min_margin_mm: 120.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    campaign = campaign_impl.load_campaign_definition(campaign_config)

    assert campaign.campaign_name == "margin-floor-sweep"
    assert campaign.results_dir == (tmp_path / "results").resolve()
    assert campaign.defaults.config_path == config_path.resolve()
    assert campaign.runs[0].output_dir == (tmp_path / "output" / "baseline").resolve()
    assert campaign.runs[0].settings.primary_margin_floor_mm == 60.0
    assert campaign.runs[1].settings.primary_margin_floor_mm is None
    assert campaign.runs[1].settings.balanced_min_margin_mm == 120.0


def test_campaign_cli_runs_batch_and_writes_summary(capsys, monkeypatch, tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    config_path, design_report_path, v2m_summary_json_path = _write_input_sources(inputs_dir)
    campaign_config = tmp_path / "campaign.yaml"
    campaign_config.write_text(
        "\n".join(
            [
                "campaign_name: primary-batch",
                "results_dir: campaign_results",
                "defaults:",
                f"  config: {config_path.relative_to(tmp_path)}",
                f"  design_report: {design_report_path.relative_to(tmp_path)}",
                f"  v2m_summary_json: {v2m_summary_json_path.relative_to(tmp_path)}",
                "runs:",
                "  - name: base",
                "    output_dir: output/base",
                "  - name: lighter",
                "    output_dir: output/lighter",
                "    producer_overrides:",
                "      primary_margin_floor_mm: 80.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def _fake_load_primary_mass_run(config: AutoresearchPrimaryConfig) -> consumer_impl.AutoresearchPrimaryRun:
        run_name = Path(config.output_dir).name
        if run_name == "base":
            decision_path = config.output_dir / "decision_base.json"
            _write_decision_json(decision_path, mass_kg=10.2, margin_mm=72.0)
            return _build_fake_run(config, decision_path=decision_path, mass_kg=10.2, margin_mm=72.0)
        decision_path = config.output_dir / "decision_lighter.json"
        _write_decision_json(decision_path, mass_kg=9.8, margin_mm=68.0)
        return _build_fake_run(config, decision_path=decision_path, mass_kg=9.8, margin_mm=68.0)

    monkeypatch.setattr(campaign_impl, "load_primary_mass_run", _fake_load_primary_mass_run)
    exit_code = campaign_impl.main(["--config", str(campaign_config)])
    captured = capsys.readouterr()
    summary_path = tmp_path / "campaign_results" / campaign_impl.SUMMARY_JSON_FILENAME
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Campaign: primary-batch" in captured.out
    assert "Best score: -9.800000" in captured.out
    assert summary["campaign_name"] == "primary-batch"
    assert summary["run_count"] == 2
    assert summary["failed_run_count"] == 0
    assert summary["best_score_run"]["run_name"] == "lighter"
    assert summary["best_primary_mass_run"]["primary_mass_kg"] == 9.8
    assert summary["best_primary_margin_run"]["primary_margin_mm"] == 72.0
    assert summary["runs"][0]["run_name"] == "base"
    assert Path(summary["runs"][0]["latest_record_path"]).exists()
    assert Path(summary["summary_text_path"]).exists()


def test_campaign_cli_records_failures_but_keeps_summary(capsys, monkeypatch, tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    config_path, design_report_path, v2m_summary_json_path = _write_input_sources(inputs_dir)
    campaign_config = tmp_path / "campaign.yaml"
    campaign_config.write_text(
        "\n".join(
            [
                "campaign_name: batch-with-failure",
                "results_dir: campaign_results",
                "defaults:",
                f"  config: {config_path.relative_to(tmp_path)}",
                f"  design_report: {design_report_path.relative_to(tmp_path)}",
                f"  v2m_summary_json: {v2m_summary_json_path.relative_to(tmp_path)}",
                "runs:",
                "  - name: ok",
                "    output_dir: output/ok",
                "  - name: boom",
                "    output_dir: output/boom",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def _fake_load_primary_mass_run(config: AutoresearchPrimaryConfig) -> consumer_impl.AutoresearchPrimaryRun:
        run_name = Path(config.output_dir).name
        if run_name == "boom":
            raise consumer_impl.AutoresearchConsumerError("producer exploded")
        decision_path = config.output_dir / "decision_ok.json"
        _write_decision_json(decision_path, mass_kg=10.1, margin_mm=71.0)
        return _build_fake_run(config, decision_path=decision_path, mass_kg=10.1, margin_mm=71.0)

    monkeypatch.setattr(campaign_impl, "load_primary_mass_run", _fake_load_primary_mass_run)
    exit_code = campaign_impl.main(["--config", str(campaign_config)])
    captured = capsys.readouterr()
    summary_path = tmp_path / "campaign_results" / campaign_impl.SUMMARY_JSON_FILENAME
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert "failed=1" in captured.out
    assert summary["failed_run_count"] == 1
    assert summary["completed_run_count"] == 1
    assert summary["best_score_run"]["run_name"] == "ok"
    failed_run = next(item for item in summary["runs"] if item["run_name"] == "boom")
    assert failed_run["status"] == "failed"
    assert failed_run["error_message"] == "producer exploded"
    assert Path(failed_run["latest_record_path"]).exists()
