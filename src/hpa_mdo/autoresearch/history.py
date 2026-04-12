"""Thin run record and summary helpers for the built-in autoresearch consumer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hpa_mdo.provenance import (
    EXPERIMENT_GOVERNANCE_VERSION,
    RUN_FINGERPRINT_VERSION,
    build_joint_decision_input_provenance,
    compute_run_fingerprint,
)

if TYPE_CHECKING:
    from hpa_mdo.autoresearch.consumer import AutoresearchPrimaryConfig, AutoresearchPrimaryRun

RUN_RECORD_SCHEMA_NAME = "hpa_mdo.autoresearch.primary_run_record"
RUN_RECORD_SCHEMA_VERSION = "v2"
RUN_RECORDS_FILENAME = "autoresearch_run_records.jsonl"
LATEST_RECORD_FILENAME = "autoresearch_latest_run_record.json"
DECISION_SNAPSHOT_DIRNAME = "decision_snapshots"
SCORE_NAME = "negative_primary_mass_kg"
SCORE_RULE = "-Primary.mass_kg"


class AutoresearchHistoryError(RuntimeError):
    """Raised when run record persistence or history loading fails."""


@dataclass(frozen=True)
class AutoresearchRunContext:
    run_id: str
    run_timestamp_utc: str
    history_dir: Path
    git_commit_hash: str | None
    git_branch: str | None
    git_worktree_dirty: bool | None


@dataclass(frozen=True)
class AutoresearchRunRecord:
    run_record_schema_name: str
    run_record_schema_version: str
    run_id: str
    run_timestamp_utc: str
    status: str
    score_name: str
    score_rule: str
    score: float | None
    primary_mass_kg: float | None
    primary_margin_mm: float | None
    output_dir: Path
    decision_json_path: Path | None
    decision_json_snapshot_path: Path | None
    decision_schema_name: str | None
    decision_schema_version: str | None
    producer_name: str | None
    producer_interface_version: str | None
    git_commit_hash: str | None
    primary_slot_status: str | None
    primary_fallback_reason_code: str | None
    producer_command: tuple[str, ...] | None = None
    producer_python_executable: str | None = None
    producer_cli_overrides: dict[str, Any] | None = None
    input_provenance: dict[str, Any] | None = None
    run_fingerprint: str | None = None
    run_fingerprint_version: str | None = None
    git_branch: str | None = None
    git_worktree_dirty: bool | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_record_schema_name": self.run_record_schema_name,
            "run_record_schema_version": self.run_record_schema_version,
            "run_id": self.run_id,
            "run_timestamp_utc": self.run_timestamp_utc,
            "status": self.status,
            "score_name": self.score_name,
            "score_rule": self.score_rule,
            "score": self.score,
            "primary_mass_kg": self.primary_mass_kg,
            "primary_margin_mm": self.primary_margin_mm,
            "output_dir": str(self.output_dir),
            "decision_json_path": None if self.decision_json_path is None else str(self.decision_json_path),
            "decision_json_snapshot_path": (
                None
                if self.decision_json_snapshot_path is None
                else str(self.decision_json_snapshot_path)
            ),
            "decision_schema_name": self.decision_schema_name,
            "decision_schema_version": self.decision_schema_version,
            "producer_name": self.producer_name,
            "producer_interface_version": self.producer_interface_version,
            "git_commit_hash": self.git_commit_hash,
            "primary_slot_status": self.primary_slot_status,
            "primary_fallback_reason_code": self.primary_fallback_reason_code,
            "producer_command": None if self.producer_command is None else list(self.producer_command),
            "producer_python_executable": self.producer_python_executable,
            "producer_cli_overrides": self.producer_cli_overrides,
            "input_provenance": self.input_provenance,
            "run_fingerprint": self.run_fingerprint,
            "run_fingerprint_version": self.run_fingerprint_version,
            "git_branch": self.git_branch,
            "git_worktree_dirty": self.git_worktree_dirty,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AutoresearchRunRecord":
        return cls(
            run_record_schema_name=str(payload["run_record_schema_name"]),
            run_record_schema_version=str(payload["run_record_schema_version"]),
            run_id=str(payload["run_id"]),
            run_timestamp_utc=str(payload["run_timestamp_utc"]),
            status=str(payload["status"]),
            score_name=str(payload.get("score_name", SCORE_NAME)),
            score_rule=str(payload.get("score_rule", SCORE_RULE)),
            score=None if payload.get("score") is None else float(payload["score"]),
            primary_mass_kg=(
                None if payload.get("primary_mass_kg") is None else float(payload["primary_mass_kg"])
            ),
            primary_margin_mm=(
                None
                if payload.get("primary_margin_mm") is None
                else float(payload["primary_margin_mm"])
            ),
            output_dir=Path(payload["output_dir"]).expanduser().resolve(),
            decision_json_path=(
                None
                if payload.get("decision_json_path") is None
                else Path(payload["decision_json_path"]).expanduser().resolve()
            ),
            decision_json_snapshot_path=(
                None
                if payload.get("decision_json_snapshot_path") is None
                else Path(payload["decision_json_snapshot_path"]).expanduser().resolve()
            ),
            decision_schema_name=_as_optional_str(payload.get("decision_schema_name")),
            decision_schema_version=_as_optional_str(payload.get("decision_schema_version")),
            producer_name=_as_optional_str(payload.get("producer_name")),
            producer_interface_version=_as_optional_str(payload.get("producer_interface_version")),
            git_commit_hash=_as_optional_str(payload.get("git_commit_hash")),
            primary_slot_status=_as_optional_str(payload.get("primary_slot_status")),
            primary_fallback_reason_code=_as_optional_str(payload.get("primary_fallback_reason_code")),
            producer_command=_as_optional_tuple(payload.get("producer_command")),
            producer_python_executable=_as_optional_str(payload.get("producer_python_executable")),
            producer_cli_overrides=_as_optional_dict(payload.get("producer_cli_overrides")),
            input_provenance=_as_optional_dict(payload.get("input_provenance")),
            run_fingerprint=_as_optional_str(payload.get("run_fingerprint")),
            run_fingerprint_version=_as_optional_str(payload.get("run_fingerprint_version")),
            git_branch=_as_optional_str(payload.get("git_branch")),
            git_worktree_dirty=_as_optional_bool(payload.get("git_worktree_dirty")),
            error_message=_as_optional_str(payload.get("error_message")),
        )


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_optional_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        normalized[str(key)] = item
    return normalized


def _as_optional_tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return None


def _as_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def default_history_dir(output_dir: Path | str) -> Path:
    return Path(output_dir).expanduser().resolve() / "autoresearch_history"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def run_records_path(history_dir: Path | str) -> Path:
    return Path(history_dir).expanduser().resolve() / RUN_RECORDS_FILENAME


def latest_record_path(history_dir: Path | str) -> Path:
    return Path(history_dir).expanduser().resolve() / LATEST_RECORD_FILENAME


def build_run_context(
    output_dir: Path | str,
    history_dir: Path | str | None = None,
) -> AutoresearchRunContext:
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_history_dir = (
        default_history_dir(resolved_output_dir)
        if history_dir is None
        else Path(history_dir).expanduser().resolve()
    )
    run_timestamp = datetime.now(timezone.utc)
    timestamp_slug = run_timestamp.strftime("%Y%m%dT%H%M%SZ")
    return AutoresearchRunContext(
        run_id=f"{timestamp_slug}-{uuid4().hex[:8]}",
        run_timestamp_utc=run_timestamp.isoformat().replace("+00:00", "Z"),
        history_dir=resolved_history_dir,
        git_commit_hash=resolve_git_commit_hash(),
        git_branch=resolve_git_branch(),
        git_worktree_dirty=resolve_git_worktree_dirty(),
    )


def resolve_git_commit_hash(cwd: Path | None = None) -> str | None:
    result = _run_git_command(["rev-parse", "HEAD"], cwd)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def resolve_git_branch(cwd: Path | None = None) -> str | None:
    result = _run_git_command(["branch", "--show-current"], cwd)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def resolve_git_worktree_dirty(cwd: Path | None = None) -> bool | None:
    result = _run_git_command(["status", "--porcelain"], cwd)
    if result is None or result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _run_git_command(args: list[str], cwd: Path | None) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root() if cwd is None else cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None


def build_success_run_record(
    run: "AutoresearchPrimaryRun",
    context: AutoresearchRunContext,
) -> AutoresearchRunRecord:
    snapshot_path = archive_decision_json(
        decision_json_path=run.decision_json_path,
        history_dir=context.history_dir,
        run_id=context.run_id,
    )
    input_provenance = _resolve_input_provenance(run.manifest.get("input_provenance"), run.config)
    producer_name = _as_optional_str(run.manifest.get("producer_name"))
    producer_interface_version = _as_optional_str(run.manifest.get("producer_interface_version"))
    decision_schema_name = _as_optional_str(run.decision_interface.get("schema_name"))
    decision_schema_version = _as_optional_str(run.decision_interface.get("schema_version"))
    producer_cli_overrides = _resolve_producer_cli_overrides(
        run.manifest.get("producer_cli_overrides"),
        input_provenance,
    )

    return AutoresearchRunRecord(
        run_record_schema_name=RUN_RECORD_SCHEMA_NAME,
        run_record_schema_version=RUN_RECORD_SCHEMA_VERSION,
        run_id=context.run_id,
        run_timestamp_utc=context.run_timestamp_utc,
        status=str(run.decision_interface.get("status", "complete")),
        score_name=SCORE_NAME,
        score_rule=SCORE_RULE,
        score=run.score,
        primary_mass_kg=run.primary_mass_kg,
        primary_margin_mm=run.primary_margin_mm,
        output_dir=run.config.output_dir,
        decision_json_path=run.decision_json_path,
        decision_json_snapshot_path=snapshot_path,
        decision_schema_name=decision_schema_name,
        decision_schema_version=decision_schema_version,
        producer_name=producer_name,
        producer_interface_version=producer_interface_version,
        git_commit_hash=context.git_commit_hash,
        primary_slot_status=run.primary_slot_status,
        primary_fallback_reason_code=run.primary_fallback_reason_code,
        producer_command=run.producer_command,
        producer_python_executable=_extract_producer_python_executable(run.producer_command),
        producer_cli_overrides=producer_cli_overrides,
        input_provenance=input_provenance,
        run_fingerprint=compute_run_fingerprint(
            producer_name=producer_name,
            producer_interface_version=producer_interface_version,
            decision_schema_name=decision_schema_name,
            decision_schema_version=decision_schema_version,
            input_provenance=input_provenance,
            producer_cli_overrides=producer_cli_overrides,
        ),
        run_fingerprint_version=RUN_FINGERPRINT_VERSION,
        git_branch=context.git_branch,
        git_worktree_dirty=context.git_worktree_dirty,
    )


def build_failure_run_record(
    config: "AutoresearchPrimaryConfig",
    context: AutoresearchRunContext,
    error_message: str,
) -> AutoresearchRunRecord:
    from hpa_mdo.autoresearch.consumer import (
        EXPECTED_DECISION_SCHEMA_NAME,
        EXPECTED_DECISION_SCHEMA_VERSION,
        build_producer_cli_argv,
    )
    from hpa_mdo.producer import PRODUCER_INTERFACE_VERSION, PRODUCER_NAME

    producer_command = tuple(build_producer_cli_argv(config))
    input_provenance = _build_input_provenance_from_config(config)
    producer_cli_overrides = _resolve_producer_cli_overrides(None, input_provenance)

    return AutoresearchRunRecord(
        run_record_schema_name=RUN_RECORD_SCHEMA_NAME,
        run_record_schema_version=RUN_RECORD_SCHEMA_VERSION,
        run_id=context.run_id,
        run_timestamp_utc=context.run_timestamp_utc,
        status="failed",
        score_name=SCORE_NAME,
        score_rule=SCORE_RULE,
        score=None,
        primary_mass_kg=None,
        primary_margin_mm=None,
        output_dir=config.output_dir,
        decision_json_path=None,
        decision_json_snapshot_path=None,
        decision_schema_name=EXPECTED_DECISION_SCHEMA_NAME,
        decision_schema_version=EXPECTED_DECISION_SCHEMA_VERSION,
        producer_name=PRODUCER_NAME,
        producer_interface_version=PRODUCER_INTERFACE_VERSION,
        git_commit_hash=context.git_commit_hash,
        primary_slot_status=None,
        primary_fallback_reason_code=None,
        producer_command=producer_command,
        producer_python_executable=_extract_producer_python_executable(producer_command),
        producer_cli_overrides=producer_cli_overrides,
        input_provenance=input_provenance,
        run_fingerprint=compute_run_fingerprint(
            producer_name=PRODUCER_NAME,
            producer_interface_version=PRODUCER_INTERFACE_VERSION,
            decision_schema_name=EXPECTED_DECISION_SCHEMA_NAME,
            decision_schema_version=EXPECTED_DECISION_SCHEMA_VERSION,
            input_provenance=input_provenance,
            producer_cli_overrides=producer_cli_overrides,
        ),
        run_fingerprint_version=RUN_FINGERPRINT_VERSION,
        git_branch=context.git_branch,
        git_worktree_dirty=context.git_worktree_dirty,
        error_message=error_message,
    )


def archive_decision_json(
    decision_json_path: Path | str,
    history_dir: Path | str,
    run_id: str,
) -> Path:
    source = Path(decision_json_path).expanduser().resolve()
    if not source.exists():
        raise AutoresearchHistoryError(f"Decision JSON not found for archival: {source}")
    snapshot_dir = Path(history_dir).expanduser().resolve() / DECISION_SNAPSHOT_DIRNAME
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{run_id}_{source.name}"
    shutil.copyfile(source, snapshot_path)
    return snapshot_path


def append_run_record(record: AutoresearchRunRecord, history_dir: Path | str) -> tuple[Path, Path]:
    resolved_history_dir = Path(history_dir).expanduser().resolve()
    resolved_history_dir.mkdir(parents=True, exist_ok=True)
    records_file = run_records_path(resolved_history_dir)
    latest_file = latest_record_path(resolved_history_dir)

    with records_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
    latest_file.write_text(
        json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return records_file, latest_file


def load_run_records(history_dir: Path | str) -> list[AutoresearchRunRecord]:
    records_file = run_records_path(history_dir)
    if not records_file.exists():
        return []

    records: list[AutoresearchRunRecord] = []
    for line_number, raw_line in enumerate(records_file.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise AutoresearchHistoryError(
                f"Invalid JSONL record at {records_file}:{line_number}"
            ) from exc
        try:
            records.append(AutoresearchRunRecord.from_dict(payload))
        except (KeyError, TypeError, ValueError) as exc:
            raise AutoresearchHistoryError(
                f"Malformed run record at {records_file}:{line_number}"
            ) from exc
    records.sort(key=lambda item: item.run_timestamp_utc, reverse=True)
    return records


def summarize_run_records(
    records: list[AutoresearchRunRecord],
    limit: int = 5,
) -> dict[str, Any]:
    capped_limit = max(int(limit), 1)
    scored_records = [record for record in records if record.score is not None]
    failed_records = [record for record in records if record.status == "failed"]
    best_record = max(scored_records, key=lambda item: item.score) if scored_records else None
    lineage_groups = _build_lineage_groups(records)
    group_map = {
        item["run_fingerprint"]: item
        for item in lineage_groups
        if item.get("run_fingerprint") is not None
    }

    recent_records = records[:capped_limit]
    previous_map: dict[str, AutoresearchRunRecord | None] = {}
    for index, record in enumerate(recent_records):
        previous_map[record.run_id] = None if index == 0 else recent_records[index - 1]

    return {
        "run_record_schema_name": RUN_RECORD_SCHEMA_NAME,
        "run_record_schema_version": RUN_RECORD_SCHEMA_VERSION,
        "score_name": SCORE_NAME,
        "score_rule": SCORE_RULE,
        "experiment_governance_version": EXPERIMENT_GOVERNANCE_VERSION,
        "run_fingerprint_version": RUN_FINGERPRINT_VERSION,
        "total_runs": len(records),
        "scored_runs": len(scored_records),
        "failed_runs": len(failed_records),
        "best_run": (
            None
            if best_record is None
            else _record_summary(
                best_record,
                best_record=best_record,
                previous_record=None,
                lineage_group=group_map.get(best_record.run_fingerprint),
            )
        ),
        "recent_runs": [
            _record_summary(
                record,
                best_record=best_record,
                previous_record=previous_map[record.run_id],
                lineage_group=group_map.get(record.run_fingerprint),
            )
            for record in recent_records
        ],
        "lineage_groups": lineage_groups,
    }


def _record_summary(
    record: AutoresearchRunRecord,
    *,
    best_record: AutoresearchRunRecord | None,
    previous_record: AutoresearchRunRecord | None,
    lineage_group: dict[str, Any] | None,
) -> dict[str, Any]:
    same_lineage_run_ids: list[str] = []
    same_lineage_run_count: int | None = None
    if lineage_group is not None:
        same_lineage_run_ids = [
            run_id for run_id in lineage_group["run_ids"] if run_id != record.run_id
        ]
        same_lineage_run_count = int(lineage_group["run_count"])

    return {
        **record.to_dict(),
        "mass_delta_vs_best_kg": _delta(
            record.primary_mass_kg,
            None if best_record is None else best_record.primary_mass_kg,
        ),
        "margin_delta_vs_best_mm": _delta(
            record.primary_margin_mm,
            None if best_record is None else best_record.primary_margin_mm,
        ),
        "score_delta_vs_best": _delta(
            record.score,
            None if best_record is None else best_record.score,
        ),
        "same_lineage_run_count": same_lineage_run_count,
        "same_lineage_other_run_ids": same_lineage_run_ids,
        "provenance_diff_vs_previous": _build_provenance_diff(
            current=record,
            previous=previous_record,
        ),
        "provenance_highlights": _build_provenance_highlights(record),
    }


def _build_lineage_groups(records: list[AutoresearchRunRecord]) -> list[dict[str, Any]]:
    grouped: dict[str, list[AutoresearchRunRecord]] = {}
    for record in records:
        if record.run_fingerprint is None:
            continue
        grouped.setdefault(record.run_fingerprint, []).append(record)

    lineage_groups: list[dict[str, Any]] = []
    for run_fingerprint, items in grouped.items():
        ordered_items = sorted(items, key=lambda item: item.run_timestamp_utc, reverse=True)
        scored_values = [float(item.score) for item in ordered_items if item.score is not None]
        lineage_groups.append(
            {
                "run_fingerprint": run_fingerprint,
                "run_count": len(ordered_items),
                "latest_run_id": ordered_items[0].run_id,
                "latest_run_timestamp_utc": ordered_items[0].run_timestamp_utc,
                "run_ids": [item.run_id for item in ordered_items],
                "score_min": None if not scored_values else min(scored_values),
                "score_max": None if not scored_values else max(scored_values),
                "has_score_variation": len({value for value in scored_values}) > 1,
                "git_commit_hashes": sorted(
                    {value for value in (item.git_commit_hash for item in ordered_items) if value}
                ),
                "provenance_highlights": _build_provenance_highlights(ordered_items[0]),
            }
        )
    lineage_groups.sort(key=lambda item: item["latest_run_timestamp_utc"], reverse=True)
    return lineage_groups


def _build_provenance_diff(
    *,
    current: AutoresearchRunRecord,
    previous: AutoresearchRunRecord | None,
) -> list[str]:
    if previous is None:
        return []

    changes: list[str] = []
    if current.run_fingerprint != previous.run_fingerprint:
        changes.append("run_fingerprint")
    if _source_signature(current, "config") != _source_signature(previous, "config"):
        changes.append("config_source")
    if _source_signature(current, "design_report") != _source_signature(previous, "design_report"):
        changes.append("design_report_source")
    if _source_signature(current, "v2m_summary_json") != _source_signature(previous, "v2m_summary_json"):
        changes.append("v2m_summary_json_source")
    if (current.producer_cli_overrides or {}) != (previous.producer_cli_overrides or {}):
        changes.append("producer_cli_overrides")
    if current.git_commit_hash != previous.git_commit_hash:
        changes.append("git_commit_hash")
    if current.git_branch != previous.git_branch:
        changes.append("git_branch")
    if current.git_worktree_dirty != previous.git_worktree_dirty:
        changes.append("git_worktree_dirty")
    if current.producer_interface_version != previous.producer_interface_version:
        changes.append("producer_interface_version")
    if (
        current.decision_schema_name != previous.decision_schema_name
        or current.decision_schema_version != previous.decision_schema_version
    ):
        changes.append("decision_schema")
    return changes


def _build_provenance_highlights(record: AutoresearchRunRecord) -> dict[str, str]:
    return {
        "config": _format_source_label(record, "config"),
        "design_report": _format_source_label(record, "design_report"),
        "v2m_summary_json": _format_source_label(record, "v2m_summary_json"),
        "overrides": _format_overrides_label(record.producer_cli_overrides),
        "git": _format_git_label(record),
    }


def _format_source_label(record: AutoresearchRunRecord, source_name: str) -> str:
    source = _get_input_source(record, source_name)
    if source is None:
        return "n/a"

    path_value = source.get("path")
    sha_value = source.get("sha256")
    if path_value is None and sha_value is None:
        return "n/a"

    label = "n/a" if path_value is None else Path(path_value).name
    if sha_value is None:
        return label
    return f"{label}@{str(sha_value)[:8]}"


def _format_overrides_label(overrides: dict[str, Any] | None) -> str:
    if not overrides:
        return "none"
    parts = [f"{key}={overrides[key]}" for key in sorted(overrides)]
    return ",".join(parts)


def _format_git_label(record: AutoresearchRunRecord) -> str:
    commit = "n/a" if record.git_commit_hash is None else record.git_commit_hash[:12]
    branch = "n/a" if record.git_branch is None else record.git_branch
    if record.git_worktree_dirty is None:
        cleanliness = "dirty=n/a"
    else:
        cleanliness = "dirty=yes" if record.git_worktree_dirty else "dirty=no"
    return f"{branch}@{commit} {cleanliness}"


def _get_input_source(record: AutoresearchRunRecord, source_name: str) -> dict[str, Any] | None:
    input_provenance = record.input_provenance or {}
    source = input_provenance.get(source_name)
    if not isinstance(source, dict):
        return None
    return source


def _source_signature(record: AutoresearchRunRecord, source_name: str) -> tuple[str | None, str | None]:
    source = _get_input_source(record, source_name)
    if source is None:
        return (None, None)
    path_value = source.get("path")
    sha_value = source.get("sha256")
    return (
        None if path_value is None else str(path_value),
        None if sha_value is None else str(sha_value),
    )


def _resolve_input_provenance(
    manifest_input_provenance: Any,
    config: "AutoresearchPrimaryConfig",
) -> dict[str, Any]:
    provenance_from_manifest = _as_optional_dict(manifest_input_provenance)
    if provenance_from_manifest is not None:
        return provenance_from_manifest
    return _build_input_provenance_from_config(config)


def _resolve_producer_cli_overrides(
    manifest_overrides: Any,
    input_provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(manifest_overrides, dict):
        return {str(key): value for key, value in manifest_overrides.items()}
    if isinstance(input_provenance, dict):
        overrides = input_provenance.get("producer_cli_overrides")
        if isinstance(overrides, dict):
            return {str(key): value for key, value in overrides.items()}
    return {}


def _build_input_provenance_from_config(config: "AutoresearchPrimaryConfig") -> dict[str, Any]:
    from hpa_mdo.producer import JointDecisionProducerConfig

    defaults = JointDecisionProducerConfig()
    producer_config = JointDecisionProducerConfig(
        config_path=config.config_path if config.config_path is not None else defaults.config_path,
        design_report_path=(
            config.design_report_path
            if config.design_report_path is not None
            else defaults.design_report_path
        ),
        v2m_summary_json_path=(
            config.v2m_summary_json_path
            if config.v2m_summary_json_path is not None
            else defaults.v2m_summary_json_path
        ),
        output_dir=config.output_dir,
        primary_margin_floor_mm=config.primary_margin_floor_mm,
        balanced_min_margin_mm=config.balanced_min_margin_mm,
        balanced_max_mass_delta_kg=config.balanced_max_mass_delta_kg,
        conservative_mode=config.conservative_mode,
    )
    return build_joint_decision_input_provenance(
        config_path=producer_config.config_path,
        design_report_path=producer_config.design_report_path,
        v2m_summary_json_path=producer_config.v2m_summary_json_path,
        output_dir=producer_config.output_dir,
        primary_margin_floor_mm=producer_config.primary_margin_floor_mm,
        balanced_min_margin_mm=producer_config.balanced_min_margin_mm,
        balanced_max_mass_delta_kg=producer_config.balanced_max_mass_delta_kg,
        conservative_mode=producer_config.conservative_mode,
    )


def _extract_producer_python_executable(producer_command: tuple[str, ...] | None) -> str | None:
    if not producer_command:
        return None
    return str(producer_command[0])


def _delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return float(value) - float(baseline)


def render_run_summary(summary: dict[str, Any], history_dir: Path | str) -> str:
    resolved_history_dir = Path(history_dir).expanduser().resolve()
    lines = [
        "HPA-MDO autoresearch run summary",
        f"History dir: {resolved_history_dir}",
        f"Ledger: {run_records_path(resolved_history_dir)}",
        f"Governance: {summary['experiment_governance_version']}",
        f"Run fingerprint version: {summary['run_fingerprint_version']}",
        f"Total runs: {summary['total_runs']}",
        f"Scored runs: {summary['scored_runs']}",
        f"Failed runs: {summary['failed_runs']}",
    ]

    best_run = summary.get("best_run")
    if best_run is None:
        lines.append("Best score: n/a")
    else:
        lines.append(
            "Best score: "
            f"{_format_optional_float(best_run['score'])} "
            f"(run_id={best_run['run_id']}, "
            f"fp={best_run.get('run_fingerprint') or 'n/a'}, "
            f"mass={_format_optional_float(best_run['primary_mass_kg'])} kg, "
            f"margin={_format_optional_float(best_run['primary_margin_mm'])} mm)"
        )

    lines.append("Recent runs:")
    for item in summary["recent_runs"]:
        provenance_diff = ",".join(item["provenance_diff_vs_previous"]) or "none"
        lines.append(
            "- "
            f"{item['run_timestamp_utc']} "
            f"run_id={item['run_id']} "
            f"status={item['status']} "
            f"score={_format_optional_float(item['score'])} "
            f"mass={_format_optional_float(item['primary_mass_kg'])}kg "
            f"margin={_format_optional_float(item['primary_margin_mm'])}mm "
            f"fp={item.get('run_fingerprint') or 'n/a'} "
            f"same_lineage_runs={item.get('same_lineage_run_count') or 0} "
            f"delta_mass_vs_best={_format_optional_float(item['mass_delta_vs_best_kg'])}kg "
            f"delta_margin_vs_best={_format_optional_float(item['margin_delta_vs_best_mm'])}mm "
            f"diff_vs_previous={provenance_diff} "
            f"output_dir={item['output_dir']}"
        )
        provenance = item["provenance_highlights"]
        lines.append(
            "  provenance: "
            f"config={provenance['config']} "
            f"design_report={provenance['design_report']} "
            f"v2m_summary_json={provenance['v2m_summary_json']} "
            f"overrides={provenance['overrides']} "
            f"git={provenance['git']}"
        )

    repeated_lineages = [item for item in summary.get("lineage_groups", []) if item["run_count"] > 1]
    if repeated_lineages:
        lines.append("Repeated lineages:")
        for item in repeated_lineages:
            provenance = item["provenance_highlights"]
            lines.append(
                "- "
                f"fp={item['run_fingerprint']} "
                f"runs={item['run_count']} "
                f"latest_run={item['latest_run_id']} "
                f"score_min={_format_optional_float(item['score_min'])} "
                f"score_max={_format_optional_float(item['score_max'])} "
                f"score_var={'yes' if item['has_score_variation'] else 'no'} "
                f"commits={','.join(item['git_commit_hashes']) or 'n/a'} "
                f"config={provenance['config']} "
                f"overrides={provenance['overrides']}"
            )
    return "\n".join(lines)


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"
