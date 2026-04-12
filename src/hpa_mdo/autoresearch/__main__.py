"""CLI entry point for the minimal built-in autoresearch consumer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from hpa_mdo.autoresearch.consumer import (
    AutoresearchConsumerError,
    AutoresearchPrimaryConfig,
    default_output_dir,
    load_primary_mass_run,
)
from hpa_mdo.autoresearch.history import (
    AutoresearchHistoryError,
    append_run_record,
    build_failure_run_record,
    build_run_context,
    build_success_run_record,
    default_history_dir,
    load_run_records,
    render_run_summary,
    summarize_run_records,
)


def _build_run_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the built-in HPA-MDO autoresearch consumer. "
            "This first version only reads the Primary design and scores "
            "score = -Primary.mass_kg."
        )
    )
    parser.add_argument("--output-dir")
    parser.add_argument("--history-dir")
    parser.add_argument("--config")
    parser.add_argument("--design-report")
    parser.add_argument("--v2m-summary-json")
    parser.add_argument("--primary-margin-floor-mm", type=float)
    parser.add_argument("--balanced-min-margin-mm", type=float)
    parser.add_argument("--balanced-max-mass-delta-kg", type=float)
    parser.add_argument("--conservative-mode")
    parser.add_argument("--producer-python")
    return parser


def _build_summary_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize recorded autoresearch runs.")
    parser.add_argument("--history-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json-out")
    return parser


def _resolve_history_dir(args_history_dir: str | None, output_dir: Path) -> Path:
    if args_history_dir is not None:
        return Path(args_history_dir).expanduser().resolve()
    return default_history_dir(output_dir)


def _run_mode(argv: list[str]) -> int:
    args = _build_run_arg_parser().parse_args(argv)
    config = AutoresearchPrimaryConfig(
        output_dir=args.output_dir if args.output_dir is not None else default_output_dir(),
        config_path=args.config,
        design_report_path=args.design_report,
        v2m_summary_json_path=args.v2m_summary_json,
        primary_margin_floor_mm=args.primary_margin_floor_mm,
        balanced_min_margin_mm=args.balanced_min_margin_mm,
        balanced_max_mass_delta_kg=args.balanced_max_mass_delta_kg,
        conservative_mode=args.conservative_mode,
        python_executable=args.producer_python,
    )
    history_dir = _resolve_history_dir(args.history_dir, config.output_dir)
    context = build_run_context(output_dir=config.output_dir, history_dir=history_dir)

    try:
        run = load_primary_mass_run(config)
        record = build_success_run_record(run, context)
        ledger_path, latest_path = append_run_record(record, history_dir)
    except AutoresearchConsumerError as exc:
        failure_record = build_failure_run_record(config, context, str(exc))
        try:
            ledger_path, latest_path = append_run_record(failure_record, history_dir)
        except AutoresearchHistoryError as history_exc:
            print(f"❌ autoresearch consumer failed: {exc}")
            print(f"❌ autoresearch run record failed: {history_exc}")
            return 1
        print(f"❌ autoresearch consumer failed: {exc}")
        print(f"Run ID: {failure_record.run_id}")
        print(f"Run timestamp (UTC): {failure_record.run_timestamp_utc}")
        print(f"Run record: {latest_path}")
        print(f"Run ledger: {ledger_path}")
        return 1
    except AutoresearchHistoryError as exc:
        print(f"❌ autoresearch run record failed: {exc}")
        return 1

    print("HPA-MDO autoresearch consumer")
    print(f"Run ID: {record.run_id}")
    print(f"Run timestamp (UTC): {record.run_timestamp_utc}")
    print(f"Producer command: {' '.join(run.producer_command)}")
    print(
        "Decision schema: "
        f"{run.decision_interface.get('schema_name')} "
        f"{run.decision_interface.get('schema_version')}"
    )
    print(f"Decision status: {run.decision_interface.get('status')}")
    print(f"Primary slot status: {run.primary_slot_status}")
    print(f"Primary fallback reason: {run.primary_fallback_reason_code}")
    print(f"Primary mass (kg): {run.primary_mass_kg:.6f}")
    if run.primary_margin_mm is not None:
        print(f"Primary margin (mm): {run.primary_margin_mm:.6f}")
    print(f"Decision JSON: {run.decision_json_path}")
    print(f"Decision JSON snapshot: {record.decision_json_snapshot_path}")
    print(f"Artifacts output dir: {run.config.output_dir}")
    print(f"Run record: {latest_path}")
    print(f"Run ledger: {ledger_path}")
    print("Score rule: -Primary.mass_kg")
    print(f"分數: {run.score:.6f}")
    return 0


def _summary_mode(argv: list[str]) -> int:
    args = _build_summary_arg_parser().parse_args(argv)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir is not None
        else default_output_dir()
    )
    history_dir = _resolve_history_dir(args.history_dir, output_dir)
    try:
        records = load_run_records(history_dir)
        summary = summarize_run_records(records, limit=args.limit)
    except AutoresearchHistoryError as exc:
        print(f"❌ autoresearch summary failed: {exc}")
        return 1

    if args.json_out is not None:
        json_out_path = Path(args.json_out).expanduser().resolve()
        json_out_path.parent.mkdir(parents=True, exist_ok=True)
        json_out_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(render_run_summary(summary, history_dir))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] in {"summary", "compare"}:
        return _summary_mode(args[1:])
    return _run_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
