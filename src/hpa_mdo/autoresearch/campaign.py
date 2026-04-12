"""Thin batch orchestration helpers for autoresearch campaigns."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import yaml

from hpa_mdo.autoresearch.consumer import (
    AutoresearchConsumerError,
    AutoresearchPrimaryConfig,
    load_primary_mass_run,
)
from hpa_mdo.autoresearch.history import (
    AutoresearchHistoryError,
    AutoresearchRunRecord,
    append_run_record,
    build_failure_run_record,
    build_run_context,
    build_success_run_record,
    default_history_dir,
)
from hpa_mdo.provenance import EXPERIMENT_GOVERNANCE_VERSION, RUN_FINGERPRINT_VERSION

CAMPAIGN_SCHEMA_NAME = "hpa_mdo.autoresearch.campaign"
CAMPAIGN_SCHEMA_VERSION = "v1"
SUMMARY_JSON_FILENAME = "campaign_summary.json"
SUMMARY_TEXT_FILENAME = "campaign_summary.txt"
ALLOWED_PRODUCER_OVERRIDE_KEYS = frozenset(
    {
        "primary_margin_floor_mm",
        "balanced_min_margin_mm",
        "balanced_max_mass_delta_kg",
        "conservative_mode",
    }
)
_MISSING = object()


class AutoresearchCampaignError(RuntimeError):
    """Raised when a campaign config or execution cannot be completed."""


@dataclass(frozen=True)
class CampaignRunSettings:
    config_path: Path | None = None
    design_report_path: Path | None = None
    v2m_summary_json_path: Path | None = None
    primary_margin_floor_mm: float | None = None
    balanced_min_margin_mm: float | None = None
    balanced_max_mass_delta_kg: float | None = None
    conservative_mode: str | None = None

    def producer_overrides(self) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        if self.primary_margin_floor_mm is not None:
            overrides["primary_margin_floor_mm"] = float(self.primary_margin_floor_mm)
        if self.balanced_min_margin_mm is not None:
            overrides["balanced_min_margin_mm"] = float(self.balanced_min_margin_mm)
        if self.balanced_max_mass_delta_kg is not None:
            overrides["balanced_max_mass_delta_kg"] = float(self.balanced_max_mass_delta_kg)
        if self.conservative_mode is not None:
            overrides["conservative_mode"] = str(self.conservative_mode)
        return overrides

    def to_config(self, output_dir: Path) -> AutoresearchPrimaryConfig:
        return AutoresearchPrimaryConfig(
            output_dir=output_dir,
            config_path=self.config_path,
            design_report_path=self.design_report_path,
            v2m_summary_json_path=self.v2m_summary_json_path,
            primary_margin_floor_mm=self.primary_margin_floor_mm,
            balanced_min_margin_mm=self.balanced_min_margin_mm,
            balanced_max_mass_delta_kg=self.balanced_max_mass_delta_kg,
            conservative_mode=self.conservative_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": None if self.config_path is None else str(self.config_path),
            "design_report": None if self.design_report_path is None else str(self.design_report_path),
            "v2m_summary_json": (
                None if self.v2m_summary_json_path is None else str(self.v2m_summary_json_path)
            ),
            "producer_overrides": self.producer_overrides(),
        }


@dataclass(frozen=True)
class CampaignRunDefinition:
    name: str
    output_dir: Path
    settings: CampaignRunSettings

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "output_dir": str(self.output_dir),
            **self.settings.to_dict(),
        }


@dataclass(frozen=True)
class CampaignDefinition:
    campaign_name: str
    config_path: Path
    results_dir: Path
    defaults: CampaignRunSettings
    runs: tuple[CampaignRunDefinition, ...]


@dataclass(frozen=True)
class CampaignRunExecution:
    run_name: str
    record: AutoresearchRunRecord
    history_dir: Path
    ledger_path: Path
    latest_record_path: Path

    def to_dict(self) -> dict[str, Any]:
        payload = self.record.to_dict()
        return {
            "run_name": self.run_name,
            "history_dir": str(self.history_dir),
            "ledger_path": str(self.ledger_path),
            "latest_record_path": str(self.latest_record_path),
            **payload,
        }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a thin batch autoresearch campaign. "
            "The campaign config defines defaults, per-run overrides, "
            "and where the batch summary is collected."
        )
    )
    parser.add_argument("--config", required=True, help="Path to a campaign YAML or JSON config.")
    return parser


def load_campaign_definition(config_path: str | Path) -> CampaignDefinition:
    resolved_config_path = Path(config_path).expanduser().resolve()
    try:
        raw_payload = yaml.safe_load(resolved_config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AutoresearchCampaignError(f"Campaign config not found: {resolved_config_path}") from exc
    except yaml.YAMLError as exc:
        raise AutoresearchCampaignError(f"Invalid campaign config YAML/JSON: {resolved_config_path}") from exc

    if not isinstance(raw_payload, dict):
        raise AutoresearchCampaignError(
            "Campaign config must be a mapping with campaign_name, results_dir, and runs."
        )

    _reject_unknown_keys(
        raw_payload,
        allowed={"campaign_name", "results_dir", "defaults", "runs"},
        context=f"campaign config {resolved_config_path}",
    )

    campaign_name = _require_non_empty_str(
        raw_payload.get("campaign_name"),
        context="campaign_name",
    )
    config_dir = resolved_config_path.parent
    results_dir = _resolve_required_path(
        raw_payload.get("results_dir"),
        base_dir=config_dir,
        context="results_dir",
    )

    defaults_raw = raw_payload.get("defaults")
    defaults_mapping = _as_mapping(defaults_raw, context="defaults") if defaults_raw is not None else {}
    defaults = _build_run_settings(
        defaults_mapping,
        base_dir=config_dir,
        context="defaults",
    )

    runs_raw = raw_payload.get("runs")
    if not isinstance(runs_raw, list) or not runs_raw:
        raise AutoresearchCampaignError("Campaign config must include a non-empty runs list.")

    runs: list[CampaignRunDefinition] = []
    seen_names: set[str] = set()
    for index, item in enumerate(runs_raw, start=1):
        run_mapping = _as_mapping(item, context=f"runs[{index}]")
        _reject_unknown_keys(
            run_mapping,
            allowed={
                "name",
                "output_dir",
                "config",
                "design_report",
                "v2m_summary_json",
                "producer_overrides",
            },
            context=f"runs[{index}]",
        )
        name = _require_non_empty_str(run_mapping.get("name"), context=f"runs[{index}].name")
        if name in seen_names:
            raise AutoresearchCampaignError(f"Duplicate campaign run name: {name}")
        seen_names.add(name)
        output_dir = _resolve_required_path(
            run_mapping.get("output_dir"),
            base_dir=config_dir,
            context=f"runs[{index}].output_dir",
        )
        settings = _merge_run_settings(
            defaults,
            run_mapping,
            base_dir=config_dir,
            context=f"runs[{index}]",
        )
        runs.append(CampaignRunDefinition(name=name, output_dir=output_dir, settings=settings))

    output_dirs = [str(run.output_dir) for run in runs]
    if len(set(output_dirs)) != len(output_dirs):
        raise AutoresearchCampaignError("Campaign run output_dir values must be unique.")

    return CampaignDefinition(
        campaign_name=campaign_name,
        config_path=resolved_config_path,
        results_dir=results_dir,
        defaults=defaults,
        runs=tuple(runs),
    )


def execute_campaign(campaign: CampaignDefinition) -> dict[str, Any]:
    results: list[CampaignRunExecution] = []
    for run in campaign.runs:
        results.append(_execute_campaign_run(run))

    generated_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary_json_path = campaign.results_dir / SUMMARY_JSON_FILENAME
    summary_text_path = campaign.results_dir / SUMMARY_TEXT_FILENAME
    summary = build_campaign_summary(
        campaign=campaign,
        results=results,
        generated_at_utc=generated_at_utc,
        summary_json_path=summary_json_path,
        summary_text_path=summary_text_path,
    )
    write_campaign_summary(summary)
    return summary


def build_campaign_summary(
    *,
    campaign: CampaignDefinition,
    results: list[CampaignRunExecution],
    generated_at_utc: str,
    summary_json_path: Path,
    summary_text_path: Path,
) -> dict[str, Any]:
    run_payloads = [item.to_dict() for item in results]
    scored_runs = [item for item in run_payloads if item.get("score") is not None]
    mass_runs = [item for item in run_payloads if item.get("primary_mass_kg") is not None]
    margin_runs = [item for item in run_payloads if item.get("primary_margin_mm") is not None]
    failed_run_count = sum(1 for item in run_payloads if item["status"] == "failed")
    completed_run_count = len(run_payloads) - failed_run_count

    best_score_run = max(scored_runs, key=lambda item: float(item["score"])) if scored_runs else None
    best_primary_mass_run = (
        min(mass_runs, key=lambda item: float(item["primary_mass_kg"])) if mass_runs else None
    )
    best_primary_margin_run = (
        max(margin_runs, key=lambda item: float(item["primary_margin_mm"])) if margin_runs else None
    )

    return {
        "campaign_schema_name": CAMPAIGN_SCHEMA_NAME,
        "campaign_schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign_name": campaign.campaign_name,
        "campaign_config_path": str(campaign.config_path),
        "results_dir": str(campaign.results_dir),
        "summary_json_path": str(summary_json_path),
        "summary_text_path": str(summary_text_path),
        "generated_at_utc": generated_at_utc,
        "experiment_governance_version": EXPERIMENT_GOVERNANCE_VERSION,
        "run_fingerprint_version": RUN_FINGERPRINT_VERSION,
        "run_count": len(run_payloads),
        "completed_run_count": completed_run_count,
        "failed_run_count": failed_run_count,
        "defaults": campaign.defaults.to_dict(),
        "runs": run_payloads,
        "best_score_run": _compact_run_summary(best_score_run),
        "best_primary_mass_run": _compact_run_summary(best_primary_mass_run),
        "best_primary_margin_run": _compact_run_summary(best_primary_margin_run),
    }


def write_campaign_summary(summary: dict[str, Any]) -> tuple[Path, Path]:
    summary_json_path = Path(summary["summary_json_path"]).expanduser().resolve()
    summary_text_path = Path(summary["summary_text_path"]).expanduser().resolve()
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_text_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_text_path.write_text(render_campaign_summary(summary) + "\n", encoding="utf-8")
    return summary_json_path, summary_text_path


def render_campaign_summary(summary: dict[str, Any]) -> str:
    lines = [
        "HPA-MDO autoresearch campaign summary",
        f"Campaign: {summary['campaign_name']}",
        f"Campaign config: {summary['campaign_config_path']}",
        f"Results dir: {summary['results_dir']}",
        f"Summary JSON: {summary['summary_json_path']}",
        f"Summary text: {summary['summary_text_path']}",
        f"Generated at (UTC): {summary['generated_at_utc']}",
        f"Governance: {summary['experiment_governance_version']}",
        f"Run fingerprint version: {summary['run_fingerprint_version']}",
        (
            "Runs: "
            f"total={summary['run_count']} "
            f"complete={summary['completed_run_count']} "
            f"failed={summary['failed_run_count']}"
        ),
        f"Best score: {_format_compact_metric(summary.get('best_score_run'), 'score')}",
        f"Best primary mass: {_format_compact_metric(summary.get('best_primary_mass_run'), 'primary_mass_kg')}",
        f"Best primary margin: {_format_compact_metric(summary.get('best_primary_margin_run'), 'primary_margin_mm')}",
        "Run results:",
    ]
    for item in summary["runs"]:
        lines.append(
            "- "
            f"run={item['run_name']} "
            f"run_id={item['run_id']} "
            f"status={item['status']} "
            f"score={_format_optional_float(item.get('score'))} "
            f"mass={_format_optional_float(item.get('primary_mass_kg'))}kg "
            f"margin={_format_optional_float(item.get('primary_margin_mm'))}mm "
            f"fp={item.get('run_fingerprint') or 'n/a'} "
            f"output_dir={item['output_dir']}"
        )
        lines.append(
            "  "
            f"decision={item.get('decision_json_path') or 'n/a'} "
            f"record={item['latest_record_path']} "
            f"overrides={_format_overrides(item.get('producer_cli_overrides'))}"
        )
        if item.get("error_message"):
            lines.append(f"  error={_format_single_line(item['error_message'])}")
    return "\n".join(lines)


def _execute_campaign_run(run: CampaignRunDefinition) -> CampaignRunExecution:
    config = run.settings.to_config(run.output_dir)
    history_dir = default_history_dir(run.output_dir)
    context = build_run_context(output_dir=run.output_dir, history_dir=history_dir)
    try:
        consumer_run = load_primary_mass_run(config)
        record = build_success_run_record(consumer_run, context)
        ledger_path, latest_path = append_run_record(record, history_dir)
    except AutoresearchConsumerError as exc:
        failure_record = build_failure_run_record(config, context, str(exc))
        try:
            ledger_path, latest_path = append_run_record(failure_record, history_dir)
        except AutoresearchHistoryError as history_exc:
            raise AutoresearchCampaignError(
                f"Failed to persist campaign run {run.name}: {history_exc}"
            ) from history_exc
        record = failure_record
    except AutoresearchHistoryError as exc:
        raise AutoresearchCampaignError(
            f"Failed to build campaign run {run.name}: {exc}"
        ) from exc

    return CampaignRunExecution(
        run_name=run.name,
        record=record,
        history_dir=history_dir,
        ledger_path=ledger_path,
        latest_record_path=latest_path,
    )


def _compact_run_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return {
        "run_name": payload["run_name"],
        "run_id": payload["run_id"],
        "status": payload["status"],
        "score": payload.get("score"),
        "primary_mass_kg": payload.get("primary_mass_kg"),
        "primary_margin_mm": payload.get("primary_margin_mm"),
        "run_fingerprint": payload.get("run_fingerprint"),
        "output_dir": payload["output_dir"],
        "decision_json_path": payload.get("decision_json_path"),
    }


def _format_compact_metric(payload: dict[str, Any] | None, metric_key: str) -> str:
    if payload is None:
        return "n/a"
    metric_value = _format_optional_float(payload.get(metric_key))
    return (
        f"{metric_value} "
        f"(run={payload['run_name']}, run_id={payload['run_id']}, "
        f"score={_format_optional_float(payload.get('score'))}, "
        f"mass={_format_optional_float(payload.get('primary_mass_kg'))}kg, "
        f"margin={_format_optional_float(payload.get('primary_margin_mm'))}mm)"
    )


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.6f}"


def _format_overrides(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    return ",".join(f"{key}={value[key]}" for key in sorted(value))


def _format_single_line(value: Any) -> str:
    return " | ".join(str(value).splitlines())


def _merge_run_settings(
    defaults: CampaignRunSettings,
    run_mapping: dict[str, Any],
    *,
    base_dir: Path,
    context: str,
) -> CampaignRunSettings:
    overrides = _merge_producer_overrides(
        defaults.producer_overrides(),
        run_mapping.get("producer_overrides", _MISSING),
        context=f"{context}.producer_overrides",
    )
    return CampaignRunSettings(
        config_path=_merge_optional_path(
            defaults.config_path,
            run_mapping,
            key="config",
            base_dir=base_dir,
            context=context,
        ),
        design_report_path=_merge_optional_path(
            defaults.design_report_path,
            run_mapping,
            key="design_report",
            base_dir=base_dir,
            context=context,
        ),
        v2m_summary_json_path=_merge_optional_path(
            defaults.v2m_summary_json_path,
            run_mapping,
            key="v2m_summary_json",
            base_dir=base_dir,
            context=context,
        ),
        primary_margin_floor_mm=_optional_float(overrides.get("primary_margin_floor_mm")),
        balanced_min_margin_mm=_optional_float(overrides.get("balanced_min_margin_mm")),
        balanced_max_mass_delta_kg=_optional_float(overrides.get("balanced_max_mass_delta_kg")),
        conservative_mode=_optional_str(overrides.get("conservative_mode")),
    )


def _build_run_settings(
    raw_mapping: dict[str, Any],
    *,
    base_dir: Path,
    context: str,
) -> CampaignRunSettings:
    _reject_unknown_keys(
        raw_mapping,
        allowed={"config", "design_report", "v2m_summary_json", "producer_overrides"},
        context=context,
    )
    overrides = _merge_producer_overrides({}, raw_mapping.get("producer_overrides", _MISSING), context=context)
    return CampaignRunSettings(
        config_path=_resolve_optional_path(
            raw_mapping.get("config", _MISSING),
            base_dir=base_dir,
            context=f"{context}.config",
        ),
        design_report_path=_resolve_optional_path(
            raw_mapping.get("design_report", _MISSING),
            base_dir=base_dir,
            context=f"{context}.design_report",
        ),
        v2m_summary_json_path=_resolve_optional_path(
            raw_mapping.get("v2m_summary_json", _MISSING),
            base_dir=base_dir,
            context=f"{context}.v2m_summary_json",
        ),
        primary_margin_floor_mm=_optional_float(overrides.get("primary_margin_floor_mm")),
        balanced_min_margin_mm=_optional_float(overrides.get("balanced_min_margin_mm")),
        balanced_max_mass_delta_kg=_optional_float(overrides.get("balanced_max_mass_delta_kg")),
        conservative_mode=_optional_str(overrides.get("conservative_mode")),
    )


def _merge_optional_path(
    default_value: Path | None,
    run_mapping: dict[str, Any],
    *,
    key: str,
    base_dir: Path,
    context: str,
) -> Path | None:
    raw_value = run_mapping.get(key, _MISSING)
    if raw_value is _MISSING:
        return default_value
    return _resolve_optional_path(raw_value, base_dir=base_dir, context=f"{context}.{key}")


def _merge_producer_overrides(
    defaults: dict[str, Any],
    raw_value: Any,
    *,
    context: str,
) -> dict[str, Any]:
    merged = dict(defaults)
    if raw_value is _MISSING:
        return merged
    if raw_value is None:
        return {}
    mapping = _as_mapping(raw_value, context=context)
    unknown = sorted(set(mapping) - set(ALLOWED_PRODUCER_OVERRIDE_KEYS))
    if unknown:
        raise AutoresearchCampaignError(
            f"Unsupported producer override keys in {context}: {', '.join(unknown)}"
        )
    for key, value in mapping.items():
        normalized = _normalize_override_value(key, value, context=context)
        if normalized is None:
            merged.pop(key, None)
        else:
            merged[key] = normalized
    return merged


def _normalize_override_value(key: str, value: Any, *, context: str) -> float | str | None:
    if key == "conservative_mode":
        return None if value is None else str(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AutoresearchCampaignError(
            f"{context}.{key} must be numeric or null."
        ) from exc


def _resolve_required_path(value: Any, *, base_dir: Path, context: str) -> Path:
    resolved = _resolve_optional_path(value, base_dir=base_dir, context=context)
    if resolved is None:
        raise AutoresearchCampaignError(f"{context} must be a non-empty path.")
    return resolved


def _resolve_optional_path(value: Any, *, base_dir: Path, context: str) -> Path | None:
    if value is _MISSING:
        return None
    if value is None:
        return None
    if not isinstance(value, (str, Path)):
        raise AutoresearchCampaignError(f"{context} must be a path string or null.")
    text = str(value).strip()
    if not text:
        raise AutoresearchCampaignError(f"{context} must not be empty.")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


def _require_non_empty_str(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AutoresearchCampaignError(f"{context} must be a non-empty string.")
    return value.strip()


def _as_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AutoresearchCampaignError(f"{context} must be a mapping.")
    return {str(key): item for key, item in value.items()}


def _reject_unknown_keys(payload: dict[str, Any], *, allowed: set[str], context: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise AutoresearchCampaignError(
            f"Unsupported keys in {context}: {', '.join(unknown)}"
        )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        campaign = load_campaign_definition(args.config)
        summary = execute_campaign(campaign)
    except AutoresearchCampaignError as exc:
        print(f"❌ autoresearch campaign failed: {exc}")
        return 1

    print(render_campaign_summary(summary))
    return 1 if summary["failed_run_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
