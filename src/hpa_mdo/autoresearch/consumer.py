"""Minimal autoresearch consumer built on top of the stable producer boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

EXPECTED_DECISION_SCHEMA_NAME = "direct_dual_beam_v2m_joint_material_decision_interface"
EXPECTED_DECISION_SCHEMA_VERSION = "v1"
PRIMARY_DESIGN_CLASS = "primary"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_output_dir() -> Path:
    return repo_root() / "output" / "autoresearch_dual_beam_primary"


@dataclass(frozen=True)
class AutoresearchPrimaryConfig:
    output_dir: Path = field(default_factory=default_output_dir)
    config_path: Path | None = None
    design_report_path: Path | None = None
    v2m_summary_json_path: Path | None = None
    primary_margin_floor_mm: float | None = None
    balanced_min_margin_mm: float | None = None
    balanced_max_mass_delta_kg: float | None = None
    conservative_mode: str | None = None
    python_executable: str | Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_dir", Path(self.output_dir).expanduser().resolve())
        if self.config_path is not None:
            object.__setattr__(self, "config_path", Path(self.config_path).expanduser().resolve())
        if self.design_report_path is not None:
            object.__setattr__(
                self,
                "design_report_path",
                Path(self.design_report_path).expanduser().resolve(),
            )
        if self.v2m_summary_json_path is not None:
            object.__setattr__(
                self,
                "v2m_summary_json_path",
                Path(self.v2m_summary_json_path).expanduser().resolve(),
            )
        if self.python_executable is not None:
            object.__setattr__(self, "python_executable", Path(self.python_executable))


@dataclass(frozen=True)
class AutoresearchPrimaryRun:
    config: AutoresearchPrimaryConfig
    producer_command: tuple[str, ...]
    manifest: dict[str, Any]
    decision_interface: dict[str, Any]
    decision_json_path: Path
    primary_design: dict[str, Any]
    primary_mass_kg: float
    primary_margin_mm: float | None
    primary_slot_status: str
    primary_fallback_reason_code: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer_command": list(self.producer_command),
            "decision_json_path": str(self.decision_json_path),
            "decision_status": self.decision_interface.get("status"),
            "primary_slot_status": self.primary_slot_status,
            "primary_fallback_reason_code": self.primary_fallback_reason_code,
            "primary_mass_kg": self.primary_mass_kg,
            "primary_margin_mm": self.primary_margin_mm,
            "score_name": "negative_primary_mass_kg",
            "score": self.score,
        }


class AutoresearchConsumerError(RuntimeError):
    """Raised when the minimal autoresearch consumer cannot complete successfully."""


def build_primary_mass_score(primary_mass_kg: float) -> float:
    return -float(primary_mass_kg)


def build_producer_cli_argv(config: AutoresearchPrimaryConfig) -> list[str]:
    python_executable = config.python_executable or sys.executable
    argv = [
        str(python_executable),
        "-m",
        "hpa_mdo.producer",
        "--output-dir",
        str(config.output_dir),
    ]
    if config.config_path is not None:
        argv.extend(["--config", str(config.config_path)])
    if config.design_report_path is not None:
        argv.extend(["--design-report", str(config.design_report_path)])
    if config.v2m_summary_json_path is not None:
        argv.extend(["--v2m-summary-json", str(config.v2m_summary_json_path)])
    if config.primary_margin_floor_mm is not None:
        argv.extend(["--primary-margin-floor-mm", str(config.primary_margin_floor_mm)])
    if config.balanced_min_margin_mm is not None:
        argv.extend(["--balanced-min-margin-mm", str(config.balanced_min_margin_mm)])
    if config.balanced_max_mass_delta_kg is not None:
        argv.extend(["--balanced-max-mass-delta-kg", str(config.balanced_max_mass_delta_kg)])
    if config.conservative_mode is not None:
        argv.extend(["--conservative-mode", str(config.conservative_mode)])
    return argv


def _run_producer_manifest(config: AutoresearchPrimaryConfig) -> tuple[dict[str, Any], tuple[str, ...]]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    argv = build_producer_cli_argv(config)
    result = subprocess.run(
        argv,
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AutoresearchConsumerError(
            "Producer invocation failed.\n"
            f"command: {' '.join(argv)}\n"
            f"exit_code: {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    try:
        return json.loads(result.stdout), tuple(argv)
    except json.JSONDecodeError as exc:
        raise AutoresearchConsumerError(
            "Producer stdout is not valid JSON manifest.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        ) from exc


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AutoresearchConsumerError(f"JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AutoresearchConsumerError(f"Invalid JSON file: {path}") from exc


def _validate_decision_schema(decision: dict[str, Any]) -> None:
    if decision.get("schema_name") != EXPECTED_DECISION_SCHEMA_NAME:
        raise AutoresearchConsumerError(
            "Unexpected decision schema_name: "
            f"{decision.get('schema_name')!r}."
        )
    if decision.get("schema_version") != EXPECTED_DECISION_SCHEMA_VERSION:
        raise AutoresearchConsumerError(
            "Unexpected decision schema_version: "
            f"{decision.get('schema_version')!r}."
        )


def _extract_primary_design(decision: dict[str, Any]) -> dict[str, Any]:
    for design in decision.get("designs", []):
        if design.get("design_class") == PRIMARY_DESIGN_CLASS:
            return design
    raise AutoresearchConsumerError("Decision JSON does not contain a Primary design slot.")


def load_primary_mass_run(
    config: AutoresearchPrimaryConfig | None = None,
) -> AutoresearchPrimaryRun:
    resolved_config = AutoresearchPrimaryConfig() if config is None else config
    manifest, producer_command = _run_producer_manifest(resolved_config)

    artifacts = manifest.get("artifacts") or {}
    decision_json_raw = artifacts.get("decision_json_path")
    if not decision_json_raw:
        raise AutoresearchConsumerError(
            "Producer manifest is missing artifacts.decision_json_path."
        )

    decision_json_path = Path(decision_json_raw).expanduser().resolve()
    decision_interface = _load_json_file(decision_json_path)
    _validate_decision_schema(decision_interface)

    primary_design = _extract_primary_design(decision_interface)
    primary_mass = primary_design.get("mass_kg")
    if primary_mass is None:
        raise AutoresearchConsumerError("Primary design does not expose mass_kg.")

    primary_margin = primary_design.get("candidate_margin_mm")

    return AutoresearchPrimaryRun(
        config=resolved_config,
        producer_command=producer_command,
        manifest=manifest,
        decision_interface=decision_interface,
        decision_json_path=decision_json_path,
        primary_design=primary_design,
        primary_mass_kg=float(primary_mass),
        primary_margin_mm=None if primary_margin is None else float(primary_margin),
        primary_slot_status=str(primary_design.get("slot_status")),
        primary_fallback_reason_code=str(primary_design.get("fallback_reason_code")),
        score=build_primary_mass_score(float(primary_mass)),
    )
