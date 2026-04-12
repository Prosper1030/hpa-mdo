from __future__ import annotations

import json
from pathlib import Path

from hpa_mdo.provenance import build_joint_decision_input_provenance  # noqa: E402
from hpa_mdo.producer import (  # noqa: E402
    DECISION_JSON_FILENAME,
    DECISION_TEXT_FILENAME,
    PRODUCER_INTERFACE_VERSION,
    PRODUCER_NAME,
    REPORT_FILENAME,
    SUMMARY_JSON_FILENAME,
    JointDecisionProducerArtifacts,
    JointDecisionProducerConfig,
    JointDecisionProducerRun,
    build_joint_decision_cli_argv,
    produce_joint_decision_interface,
)
from hpa_mdo.producer import __main__ as producer_main  # noqa: E402
from hpa_mdo.producer import joint_decision as producer_impl  # noqa: E402


class _FakeInternalJointModule:
    def main(self, argv: list[str]) -> int:
        output_dir = Path(argv[argv.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / REPORT_FILENAME).write_text("report\n", encoding="utf-8")
        (output_dir / SUMMARY_JSON_FILENAME).write_text(
            json.dumps({"outcome": {"success": True}}) + "\n",
            encoding="utf-8",
        )
        (output_dir / DECISION_JSON_FILENAME).write_text(
            json.dumps(
                {
                    "schema_name": "direct_dual_beam_v2m_joint_material_decision_interface",
                    "schema_version": "v1",
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
                            "mass_kg": 10.0,
                            "raw_main_tip_mm": 1700.0,
                            "raw_rear_tip_mm": 2400.0,
                            "raw_max_uz_mm": 2400.0,
                            "psi_u_all_mm": 2401.0,
                            "candidate_margin_mm": 99.0,
                            "rule_trigger": "rule",
                            "selection_rationale": "why",
                            "qualifying_candidate_count": 10,
                        },
                        {
                            "design_class": "balanced",
                            "design_label": "Balanced design",
                            "slot_status": "selected",
                            "fallback_reason_code": "none",
                            "geometry_seed": "balanced",
                            "geometry_choice": [4, 0, 2, 4, 0],
                            "material_choice": {
                                "main_spar_family": "main_light_ud",
                                "rear_outboard_reinforcement_pkg": "ob_balanced_sleeve",
                            },
                            "mass_kg": 10.3,
                            "raw_main_tip_mm": 1690.0,
                            "raw_rear_tip_mm": 2310.0,
                            "raw_max_uz_mm": 2310.0,
                            "psi_u_all_mm": 2311.0,
                            "candidate_margin_mm": 189.0,
                            "rule_trigger": "rule",
                            "selection_rationale": "why",
                            "qualifying_candidate_count": 2,
                        },
                        {
                            "design_class": "conservative",
                            "design_label": "Conservative design",
                            "slot_status": "selected",
                            "fallback_reason_code": "none",
                            "geometry_seed": "conservative",
                            "geometry_choice": [4, 0, 2, 4, 1],
                            "material_choice": {
                                "main_spar_family": "main_light_ud",
                                "rear_outboard_reinforcement_pkg": "ob_balanced_sleeve",
                            },
                            "mass_kg": 10.9,
                            "raw_main_tip_mm": 1580.0,
                            "raw_rear_tip_mm": 2160.0,
                            "raw_max_uz_mm": 2160.0,
                            "psi_u_all_mm": 2161.0,
                            "candidate_margin_mm": 339.0,
                            "rule_trigger": "rule",
                            "selection_rationale": "why",
                            "qualifying_candidate_count": 20,
                        },
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (output_dir / DECISION_TEXT_FILENAME).write_text("decision text\n", encoding="utf-8")
        print("internal workflow stdout")
        return 0


def _write_input_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    config_path = tmp_path / "config.yaml"
    design_report_path = tmp_path / "design_report.txt"
    v2m_summary_json_path = tmp_path / "v2m_summary.json"
    config_path.write_text("wing: blackcat\n", encoding="utf-8")
    design_report_path.write_text("margin report\n", encoding="utf-8")
    v2m_summary_json_path.write_text(json.dumps({"summary": "ok"}) + "\n", encoding="utf-8")
    return config_path, design_report_path, v2m_summary_json_path


def test_build_joint_decision_cli_argv_forces_workflow_strategy(tmp_path: Path) -> None:
    config = JointDecisionProducerConfig(
        output_dir=tmp_path / "out",
        primary_margin_floor_mm=60.0,
        balanced_min_margin_mm=190.0,
    )

    argv = build_joint_decision_cli_argv(config)

    assert argv[:2] == ["--strategy", "workflow"]
    assert "--output-dir" in argv
    assert str((tmp_path / "out").resolve()) in argv
    assert "--primary-margin-floor-mm" in argv
    assert "--balanced-min-margin-mm" in argv


def test_produce_joint_decision_interface_returns_manifest_and_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path, design_report_path, v2m_summary_json_path = _write_input_sources(tmp_path)
    monkeypatch.setattr(
        producer_impl,
        "_load_internal_joint_material_module",
        lambda: _FakeInternalJointModule(),
    )
    config = JointDecisionProducerConfig(
        config_path=config_path,
        design_report_path=design_report_path,
        v2m_summary_json_path=v2m_summary_json_path,
        output_dir=tmp_path / "producer_run",
        primary_margin_floor_mm=60.0,
    )

    run = produce_joint_decision_interface(config)

    assert run.producer_name == PRODUCER_NAME
    assert run.producer_interface_version == PRODUCER_INTERFACE_VERSION
    assert run.decision_interface["schema_version"] == "v1"
    assert run.artifacts.decision_json_path.exists()
    assert "internal workflow stdout" in run.captured_stdout
    manifest = run.to_manifest_dict()
    assert manifest["decision_status"] == "complete"
    assert manifest["design_statuses"][0]["design_class"] == "primary"
    assert manifest["producer_cli_overrides"] == {"primary_margin_floor_mm": 60.0}
    assert manifest["input_provenance"] == build_joint_decision_input_provenance(
        config_path=config_path,
        design_report_path=design_report_path,
        v2m_summary_json_path=v2m_summary_json_path,
        output_dir=tmp_path / "producer_run",
        primary_margin_floor_mm=60.0,
        balanced_min_margin_mm=None,
        balanced_max_mass_delta_kg=None,
        conservative_mode=None,
    )


def test_producer_cli_prints_machine_readable_manifest(capsys, monkeypatch, tmp_path: Path) -> None:
    config_path, design_report_path, v2m_summary_json_path = _write_input_sources(tmp_path)
    artifacts = JointDecisionProducerArtifacts(
        output_dir=tmp_path / "run",
        report_path=tmp_path / "run" / REPORT_FILENAME,
        summary_json_path=tmp_path / "run" / SUMMARY_JSON_FILENAME,
        decision_json_path=tmp_path / "run" / DECISION_JSON_FILENAME,
        decision_text_path=tmp_path / "run" / DECISION_TEXT_FILENAME,
    )
    fake_run = JointDecisionProducerRun(
        producer_name=PRODUCER_NAME,
        producer_interface_version=PRODUCER_INTERFACE_VERSION,
        config=JointDecisionProducerConfig(
            config_path=config_path,
            design_report_path=design_report_path,
            v2m_summary_json_path=v2m_summary_json_path,
            output_dir=tmp_path / "run",
            balanced_min_margin_mm=190.0,
        ),
        artifacts=artifacts,
        decision_interface={
            "schema_name": "direct_dual_beam_v2m_joint_material_decision_interface",
            "schema_version": "v1",
            "status": "complete",
            "designs": [
                {
                    "design_class": "primary",
                    "slot_status": "selected",
                    "fallback_reason_code": "none",
                }
            ],
        },
        summary_json={"outcome": {"success": True}},
        captured_stdout="",
    )
    monkeypatch.setattr(producer_main, "produce_joint_decision_interface", lambda config: fake_run)

    exit_code = producer_main.main(["--output-dir", str(tmp_path / "run")])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["producer_name"] == PRODUCER_NAME
    assert payload["decision_schema_version"] == "v1"
    assert payload["artifacts"]["decision_json_path"].endswith(DECISION_JSON_FILENAME)
    assert payload["producer_cli_overrides"] == {"balanced_min_margin_mm": 190.0}
    assert payload["input_provenance"]["config"]["path"] == str(config_path.resolve())
    assert payload["input_provenance"]["config"]["sha256"] is not None
