"""CLI entry point for the minimal built-in autoresearch consumer."""

from __future__ import annotations

import argparse

from hpa_mdo.autoresearch.consumer import (
    AutoresearchConsumerError,
    AutoresearchPrimaryConfig,
    default_output_dir,
    load_primary_mass_run,
)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the built-in HPA-MDO autoresearch consumer. "
            "This first version only reads the Primary design and scores "
            "score = -Primary.mass_kg."
        )
    )
    parser.add_argument("--output-dir")
    parser.add_argument("--config")
    parser.add_argument("--design-report")
    parser.add_argument("--v2m-summary-json")
    parser.add_argument("--primary-margin-floor-mm", type=float)
    parser.add_argument("--balanced-min-margin-mm", type=float)
    parser.add_argument("--balanced-max-mass-delta-kg", type=float)
    parser.add_argument("--conservative-mode")
    parser.add_argument("--producer-python")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
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
    try:
        run = load_primary_mass_run(config)
    except AutoresearchConsumerError as exc:
        print(f"❌ autoresearch consumer failed: {exc}")
        return 1

    print("HPA-MDO autoresearch consumer")
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
    print(f"Artifacts output dir: {run.config.output_dir}")
    print("Score rule: -Primary.mass_kg")
    print(f"分數: {run.score:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
