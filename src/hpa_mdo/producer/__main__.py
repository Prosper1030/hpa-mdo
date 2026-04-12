"""CLI entry point for the stable dual-beam joint decision producer."""

from __future__ import annotations

import argparse
import json

from hpa_mdo.producer.joint_decision import (
    JointDecisionProducerConfig,
    produce_joint_decision_interface,
)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the stable dual-beam joint geometry + material decision producer "
            "and emit a machine-readable producer manifest."
        )
    )
    parser.add_argument("--config")
    parser.add_argument("--design-report")
    parser.add_argument("--v2m-summary-json")
    parser.add_argument("--output-dir")
    parser.add_argument("--primary-margin-floor-mm", type=float)
    parser.add_argument("--balanced-min-margin-mm", type=float)
    parser.add_argument("--balanced-max-mass-delta-kg", type=float)
    parser.add_argument("--conservative-mode")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    defaults = JointDecisionProducerConfig()
    config = JointDecisionProducerConfig(
        config_path=args.config if args.config is not None else defaults.config_path,
        design_report_path=args.design_report if args.design_report is not None else defaults.design_report_path,
        v2m_summary_json_path=(
            args.v2m_summary_json if args.v2m_summary_json is not None else defaults.v2m_summary_json_path
        ),
        output_dir=args.output_dir if args.output_dir is not None else defaults.output_dir,
        primary_margin_floor_mm=args.primary_margin_floor_mm,
        balanced_min_margin_mm=args.balanced_min_margin_mm,
        balanced_max_mass_delta_kg=args.balanced_max_mass_delta_kg,
        conservative_mode=args.conservative_mode,
    )
    run = produce_joint_decision_interface(config)
    print(json.dumps(run.to_manifest_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
