"""Stable producer boundary for the dual-beam joint decision interface."""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass, field
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

PRODUCER_NAME = "hpa_mdo.dual_beam_joint_decision"
PRODUCER_INTERFACE_VERSION = "v1"
INTERNAL_SEARCH_STRATEGY = "workflow"
REPORT_FILENAME = "direct_dual_beam_v2m_joint_material_report.txt"
SUMMARY_JSON_FILENAME = "direct_dual_beam_v2m_joint_material_summary.json"
DECISION_JSON_FILENAME = "direct_dual_beam_v2m_joint_material_decision_interface.json"
DECISION_TEXT_FILENAME = "direct_dual_beam_v2m_joint_material_decision_interface.txt"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_config_path() -> Path:
    return repo_root() / "configs" / "blackcat_004.yaml"


def default_design_report_path() -> Path:
    return (
        repo_root()
        / "output"
        / "blackcat_004_dual_beam_production_check"
        / "ansys"
        / "crossval_report.txt"
    )


def default_v2m_summary_json_path() -> Path:
    return (
        repo_root()
        / "output"
        / "direct_dual_beam_v2m_plusplus_compare"
        / "direct_dual_beam_v2m_summary.json"
    )


def default_output_dir() -> Path:
    return repo_root() / "output" / "direct_dual_beam_v2m_joint_material"


@dataclass(frozen=True)
class JointDecisionProducerConfig:
    config_path: Path = field(default_factory=default_config_path)
    design_report_path: Path = field(default_factory=default_design_report_path)
    v2m_summary_json_path: Path = field(default_factory=default_v2m_summary_json_path)
    output_dir: Path = field(default_factory=default_output_dir)
    primary_margin_floor_mm: float | None = None
    balanced_min_margin_mm: float | None = None
    balanced_max_mass_delta_kg: float | None = None
    conservative_mode: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "config_path", Path(self.config_path))
        object.__setattr__(self, "design_report_path", Path(self.design_report_path))
        object.__setattr__(self, "v2m_summary_json_path", Path(self.v2m_summary_json_path))
        object.__setattr__(self, "output_dir", Path(self.output_dir))


@dataclass(frozen=True)
class JointDecisionProducerArtifacts:
    output_dir: Path
    report_path: Path
    summary_json_path: Path
    decision_json_path: Path
    decision_text_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "report_path": str(self.report_path),
            "summary_json_path": str(self.summary_json_path),
            "decision_json_path": str(self.decision_json_path),
            "decision_text_path": str(self.decision_text_path),
        }


@dataclass(frozen=True)
class JointDecisionProducerRun:
    producer_name: str
    producer_interface_version: str
    config: JointDecisionProducerConfig
    artifacts: JointDecisionProducerArtifacts
    decision_interface: dict[str, Any]
    summary_json: dict[str, Any]
    captured_stdout: str

    def to_manifest_dict(self) -> dict[str, Any]:
        design_statuses = [
            {
                "design_class": design["design_class"],
                "slot_status": design["slot_status"],
                "fallback_reason_code": design["fallback_reason_code"],
            }
            for design in self.decision_interface.get("designs", [])
        ]
        return {
            "producer_name": self.producer_name,
            "producer_interface_version": self.producer_interface_version,
            "search_strategy": INTERNAL_SEARCH_STRATEGY,
            "decision_schema_name": self.decision_interface.get("schema_name"),
            "decision_schema_version": self.decision_interface.get("schema_version"),
            "decision_status": self.decision_interface.get("status"),
            "artifacts": self.artifacts.to_dict(),
            "design_statuses": design_statuses,
        }


def _load_internal_joint_material_module() -> ModuleType:
    script_path = repo_root() / "scripts" / "direct_dual_beam_v2m_joint_material.py"
    spec = importlib.util.spec_from_file_location(
        "hpa_mdo._internal_direct_dual_beam_v2m_joint_material",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load joint material workflow script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_joint_decision_cli_argv(
    config: JointDecisionProducerConfig,
) -> list[str]:
    argv = [
        "--strategy",
        INTERNAL_SEARCH_STRATEGY,
        "--config",
        str(config.config_path.expanduser().resolve()),
        "--design-report",
        str(config.design_report_path.expanduser().resolve()),
        "--v2m-summary-json",
        str(config.v2m_summary_json_path.expanduser().resolve()),
        "--output-dir",
        str(config.output_dir.expanduser().resolve()),
    ]
    if config.primary_margin_floor_mm is not None:
        argv.extend(["--primary-margin-floor-mm", str(config.primary_margin_floor_mm)])
    if config.balanced_min_margin_mm is not None:
        argv.extend(["--balanced-min-margin-mm", str(config.balanced_min_margin_mm)])
    if config.balanced_max_mass_delta_kg is not None:
        argv.extend(["--balanced-max-mass-delta-kg", str(config.balanced_max_mass_delta_kg)])
    if config.conservative_mode is not None:
        argv.extend(["--conservative-mode", str(config.conservative_mode)])
    return argv


def decision_artifact_paths(output_dir: str | Path) -> JointDecisionProducerArtifacts:
    resolved = Path(output_dir).expanduser().resolve()
    return JointDecisionProducerArtifacts(
        output_dir=resolved,
        report_path=resolved / REPORT_FILENAME,
        summary_json_path=resolved / SUMMARY_JSON_FILENAME,
        decision_json_path=resolved / DECISION_JSON_FILENAME,
        decision_text_path=resolved / DECISION_TEXT_FILENAME,
    )


def load_decision_interface(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def load_summary_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def produce_joint_decision_interface(
    config: JointDecisionProducerConfig | None = None,
) -> JointDecisionProducerRun:
    resolved_config = JointDecisionProducerConfig() if config is None else config
    argv = build_joint_decision_cli_argv(resolved_config)
    artifacts = decision_artifact_paths(resolved_config.output_dir)
    module = _load_internal_joint_material_module()

    captured_stdout = io.StringIO()
    with redirect_stdout(captured_stdout):
        exit_code = module.main(argv)
    if exit_code != 0:
        raise RuntimeError(
            "Joint decision producer failed with exit code "
            f"{exit_code}. Captured output:\n{captured_stdout.getvalue()}"
        )

    return JointDecisionProducerRun(
        producer_name=PRODUCER_NAME,
        producer_interface_version=PRODUCER_INTERFACE_VERSION,
        config=resolved_config,
        artifacts=artifacts,
        decision_interface=load_decision_interface(artifacts.decision_json_path),
        summary_json=load_summary_json(artifacts.summary_json_path),
        captured_stdout=captured_stdout.getvalue(),
    )
