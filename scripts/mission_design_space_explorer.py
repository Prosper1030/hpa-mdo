#!/usr/bin/env python3
"""Mission design-space explorer CLI."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import Any
import json

from hpa_mdo.mission import (
    MissionQuickScreenResult,
    RiderPowerEnvironment,
    build_boundary_tables,
    build_feasible_envelope,
    MissionDesignSpaceSpec,
    load_mission_design_space_spec,
    summarize_design_space,
    write_design_space_report,
    write_design_space_plots,
    write_envelope_rows,
    write_full_results_csv,
    is_robust_case,
    sort_design_space_cases,
    load_rider_power_curve_metadata,
    load_csv_power_curve,
    thermal_power_derate_factor,
)
from hpa_mdo.mission.quick_screen import sweep_quick_screen_grid


DEFAULT_CONFIG_PATH = "configs/mission_design_space_example.yaml"


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Explore quick-screen design-space feasibility with reusable outputs."
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="YAML path for design-space sweep setup.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output_dir in config outputs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Expand cases and print counts without evaluating.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit evaluations to the first N cases (for testing).",
    )
    parser.add_argument(
        "--skip-plots",
        action="store_true",
        help="Skip matplotlib plot generation.",
    )
    return parser


def _missing_file_message(kind: str, path: Path) -> str:
    return (
        f"{kind} not found: {path}\n"
        "Tip: locate files with:\n"
        "  find data -iname \"*power*curve*.csv\"\n"
        "  find . -iname \"*power*curve*.metadata.yaml\""
    )


def _parse_args(argv: list[str] | None = None) -> Namespace:
    return _build_parser().parse_args(argv)


def _update_summary_json_with_plots(
    summary_json_path: Path,
    plot_paths: dict[str, str],
) -> None:
    payload = json.loads(summary_json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("summary.json should be a JSON object.")
    payload["plot_paths"] = plot_paths
    summary_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _evaluate_design_space(
    spec: Any,
    limit: int | None,
) -> list[MissionQuickScreenResult]:
    metadata = load_rider_power_curve_metadata(spec.rider_metadata_yaml)
    test_env = RiderPowerEnvironment(
        temperature_c=float(metadata["measurement_environment"]["temperature_c"]),
        relative_humidity_percent=float(
            metadata["measurement_environment"]["relative_humidity_percent"]
        ),
    )
    target_env = RiderPowerEnvironment(
        temperature_c=spec.target_temperature_c,
        relative_humidity_percent=spec.target_relative_humidity_percent,
    )
    heat_derate = thermal_power_derate_factor(
        test_environment=test_env,
        target_environment=target_env,
        heat_loss_coefficient_per_h_c=spec.heat_loss_coefficient_per_h_c,
    )

    rider_curve = load_csv_power_curve(spec.rider_power_csv, reference_duration_min=60.0)
    all_cases: list[MissionQuickScreenResult] = []

    for mass_kg, air_density_kg_m3, oswald_e, eta_prop, eta_trans in product(
        spec.mass_kg,
        spec.air_density_kg_m3,
        spec.oswald_e,
        spec.eta_prop,
        spec.eta_trans,
    ):
        all_cases.extend(
            sweep_quick_screen_grid(
                speeds_mps=spec.speeds_mps,
                spans_m=spec.spans_m,
                aspect_ratios=spec.aspect_ratios,
                cd0_totals=spec.cd0_totals,
                mass_kg=mass_kg,
                oswald_e=oswald_e,
                air_density_kg_m3=air_density_kg_m3,
                eta_prop=eta_prop,
                eta_trans=eta_trans,
                target_range_km=spec.target_range_km,
                cl_max_effectives=spec.cl_max_effectives,
                rider_curve=rider_curve,
                thermal_derate_factor=heat_derate,
            )
        )

    return sort_design_space_cases(all_cases[:limit] if limit else all_cases)


def run_mission_design_space(
    *,
    spec: MissionDesignSpaceSpec,
    output_dir_override: Path | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    skip_plots: bool = False,
) -> tuple[Path, Path, list[MissionQuickScreenResult]]:
    if output_dir_override is not None:
        spec = replace(spec, output_dir=output_dir_override)

    if not spec.rider_power_csv.exists():
        raise FileNotFoundError(_missing_file_message("Power CSV", spec.rider_power_csv))
    if not spec.rider_metadata_yaml.exists():
        raise FileNotFoundError(
            _missing_file_message("Metadata YAML", spec.rider_metadata_yaml),
        )

    if spec.output_dir.exists() is False:
        spec.output_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        return spec.output_dir / "full_results.csv", spec.output_dir / "report.md", []

    cases = _evaluate_design_space(spec, limit=limit)
    summary = summarize_design_space(cases, spec.filters)
    envelopes = build_feasible_envelope(cases, spec.filters)
    boundaries = build_boundary_tables(cases, spec.filters)

    metadata = load_rider_power_curve_metadata(spec.rider_metadata_yaml)
    test_env = RiderPowerEnvironment(
        temperature_c=float(metadata["measurement_environment"]["temperature_c"]),
        relative_humidity_percent=float(
            metadata["measurement_environment"]["relative_humidity_percent"]
        ),
    )
    target_env = RiderPowerEnvironment(
        temperature_c=spec.target_temperature_c,
        relative_humidity_percent=spec.target_relative_humidity_percent,
    )
    heat_derate = thermal_power_derate_factor(
        test_environment=test_env,
        target_environment=target_env,
        heat_loss_coefficient_per_h_c=spec.heat_loss_coefficient_per_h_c,
    )

    full_results_csv = spec.output_dir / "full_results.csv"
    report_md = spec.output_dir / "report.md"
    plot_paths: dict[str, str] = {}
    if spec.write_plots and not skip_plots:
        plot_paths = write_design_space_plots(
            spec.output_dir,
            spec=spec,
            results=cases,
            envelopes=envelopes,
            boundary_tables=boundaries,
            test_env=test_env,
            target_env=target_env,
            filters=spec.filters,
        )
    if spec.write_full_results_csv:
        write_full_results_csv(full_results_csv, cases, spec.filters)
    if spec.write_markdown_report:
        write_design_space_report(
            report_md,
            spec=spec,
            results=cases,
            summary=summary,
            envelopes=envelopes,
            boundary_tables=boundaries,
            test_env=test_env,
            target_env=target_env,
            heat_derate=heat_derate,
            filters=spec.filters,
            plot_paths=plot_paths or None,
        )

    summary_json_path = spec.output_dir / "summary.json"
    if summary_json_path.exists() and plot_paths:
        _update_summary_json_with_plots(summary_json_path, plot_paths)
    if spec.write_envelope_csv:
        by_speed = [row for row in envelopes if row.get("group") == "by_speed"]
        by_cd0 = [row for row in envelopes if row.get("group") == "by_cd0"]
        by_ar = [row for row in envelopes if row.get("group") == "by_aspect_ratio"]
        by_span = [row for row in envelopes if row.get("group") == "by_span"]
        by_clmax = [row for row in envelopes if row.get("group") == "by_clmax"]
        write_envelope_rows(spec.output_dir / "envelope_by_speed.csv", by_speed)
        write_envelope_rows(spec.output_dir / "envelope_by_cd0.csv", by_cd0)
        write_envelope_rows(spec.output_dir / "envelope_by_ar.csv", by_ar)
        write_envelope_rows(spec.output_dir / "envelope_by_span.csv", by_span)
        write_envelope_rows(spec.output_dir / "envelope_by_clmax.csv", by_clmax)
        best_margin_by_speed_cd0 = boundaries["best_margin_by_speed_cd0"]
        robust_count_by_speed_cd0 = boundaries["robust_count_by_speed_cd0"]
        combined = []
        for speed_cd0 in sorted(
            {
                (bm["speed_mps"], bm["cd0_total"])
                for bm in best_margin_by_speed_cd0
            }
        ):
            speed_mps, cd0_total = speed_cd0
            best_margin_entry = next(
                (row for row in best_margin_by_speed_cd0 if row["speed_mps"] == speed_mps and row["cd0_total"] == cd0_total),
                {},
            )
            robust_entry = next(
                (row for row in robust_count_by_speed_cd0 if row["speed_mps"] == speed_mps and row["cd0_total"] == cd0_total),
                {},
            )
            combined.append(
                {
                    "speed_mps": speed_mps,
                    "cd0_total": cd0_total,
                    "best_power_margin_crank_w": best_margin_entry.get("best_power_margin_crank_w"),
                    "robust_cases": robust_entry.get("robust_cases", 0),
                    "span_m": best_margin_entry.get("span_m"),
                    "aspect_ratio": best_margin_entry.get("aspect_ratio"),
                    "cl_max_effective": best_margin_entry.get("cl_max_effective"),
                },
            )
        write_envelope_rows(spec.output_dir / "boundary_speed_cd0.csv", combined)
        _ = boundaries["stall_risk_by_speed_clmax"]

    return full_results_csv, report_md, cases


def _print_console_summary(
    *,
    spec: Any,
    cases: list[MissionQuickScreenResult],
    full_results_csv: Path,
    report_md: Path,
) -> None:
    robust_count = len([case for case in cases if is_robust_case(case, spec.filters)])
    passed_count = len([case for case in cases if case.power_passed])
    print(f"power CSV: {spec.rider_power_csv.resolve()}")
    print(f"metadata: {spec.rider_metadata_yaml.resolve()}")
    print(f"total cases: {len(cases)}")
    print(f"passed cases: {passed_count}")
    print(f"robust candidates: {robust_count}")
    print(f"full_results.csv: {full_results_csv}")
    print(f"report.md: {report_md}")


def main() -> int:
    args = _parse_args()
    try:
        spec = load_mission_design_space_spec(args.config)
        if args.output_dir:
            spec = replace(spec, output_dir=Path(args.output_dir))
        total_cases = (
            len(spec.speeds_mps)
            * len(spec.spans_m)
            * len(spec.aspect_ratios)
            * len(spec.cd0_totals)
            * len(spec.cl_max_effectives)
            * len(spec.mass_kg)
            * len(spec.air_density_kg_m3)
            * len(spec.oswald_e)
            * len(spec.eta_prop)
            * len(spec.eta_trans)
        )

        if args.dry_run:
            print(f"Dry run enabled. total cases: {total_cases}")
            if args.limit is not None:
                print(f"limit requested: {args.limit} cases")
            return 0

        if args.limit is not None:
            print(f"limit set to {args.limit}")

        full_csv, report_md, results = run_mission_design_space(
            spec=spec,
            output_dir_override=Path(args.output_dir) if args.output_dir else None,
            dry_run=False,
            limit=args.limit,
            skip_plots=args.skip_plots,
        )
        _print_console_summary(
            spec=spec,
            cases=results,
            full_results_csv=full_csv,
            report_md=report_md,
        )
        print(f"total case combinations: {total_cases}")
    except Exception as exc:
        print(f"Failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
