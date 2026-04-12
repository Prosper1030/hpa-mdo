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

if TYPE_CHECKING:
    from hpa_mdo.autoresearch.consumer import AutoresearchPrimaryConfig, AutoresearchPrimaryRun

RUN_RECORD_SCHEMA_NAME = "hpa_mdo.autoresearch.primary_run_record"
RUN_RECORD_SCHEMA_VERSION = "v1"
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
            error_message=_as_optional_str(payload.get("error_message")),
        )


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


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
    )


def resolve_git_commit_hash(cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root() if cwd is None else cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def build_success_run_record(
    run: "AutoresearchPrimaryRun",
    context: AutoresearchRunContext,
) -> AutoresearchRunRecord:
    snapshot_path = archive_decision_json(
        decision_json_path=run.decision_json_path,
        history_dir=context.history_dir,
        run_id=context.run_id,
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
        decision_schema_name=_as_optional_str(run.decision_interface.get("schema_name")),
        decision_schema_version=_as_optional_str(run.decision_interface.get("schema_version")),
        producer_name=_as_optional_str(run.manifest.get("producer_name")),
        producer_interface_version=_as_optional_str(run.manifest.get("producer_interface_version")),
        git_commit_hash=context.git_commit_hash,
        primary_slot_status=run.primary_slot_status,
        primary_fallback_reason_code=run.primary_fallback_reason_code,
    )


def build_failure_run_record(
    config: "AutoresearchPrimaryConfig",
    context: AutoresearchRunContext,
    error_message: str,
) -> AutoresearchRunRecord:
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
        decision_schema_name=None,
        decision_schema_version=None,
        producer_name=None,
        producer_interface_version=None,
        git_commit_hash=context.git_commit_hash,
        primary_slot_status=None,
        primary_fallback_reason_code=None,
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

    return {
        "run_record_schema_name": RUN_RECORD_SCHEMA_NAME,
        "run_record_schema_version": RUN_RECORD_SCHEMA_VERSION,
        "score_name": SCORE_NAME,
        "score_rule": SCORE_RULE,
        "total_runs": len(records),
        "scored_runs": len(scored_records),
        "failed_runs": len(failed_records),
        "best_run": None if best_record is None else _record_summary(best_record, best_record),
        "recent_runs": [_record_summary(record, best_record) for record in records[:capped_limit]],
    }


def _record_summary(
    record: AutoresearchRunRecord,
    best_record: AutoresearchRunRecord | None,
) -> dict[str, Any]:
    return {
        **record.to_dict(),
        "mass_delta_vs_best_kg": _delta(record.primary_mass_kg, None if best_record is None else best_record.primary_mass_kg),
        "margin_delta_vs_best_mm": _delta(
            record.primary_margin_mm,
            None if best_record is None else best_record.primary_margin_mm,
        ),
        "score_delta_vs_best": _delta(record.score, None if best_record is None else best_record.score),
    }


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
            f"mass={_format_optional_float(best_run['primary_mass_kg'])} kg, "
            f"margin={_format_optional_float(best_run['primary_margin_mm'])} mm)"
        )

    lines.append("Recent runs:")
    for item in summary["recent_runs"]:
        lines.append(
            "- "
            f"{item['run_timestamp_utc']} "
            f"run_id={item['run_id']} "
            f"status={item['status']} "
            f"score={_format_optional_float(item['score'])} "
            f"mass={_format_optional_float(item['primary_mass_kg'])}kg "
            f"margin={_format_optional_float(item['primary_margin_mm'])}mm "
            f"delta_mass_vs_best={_format_optional_float(item['mass_delta_vs_best_kg'])}kg "
            f"delta_margin_vs_best={_format_optional_float(item['margin_delta_vs_best_mm'])}mm "
            f"output_dir={item['output_dir']}"
        )
    return "\n".join(lines)


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"
