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
SUMMARY_JSON_FILENAME = "summary.json"


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


def _range_pair(values: list[float]) -> list[float] | None:
    if not values:
        return None
    return [min(values), max(values)]


def _robust_range(value_key: str, cases: list[MissionQuickScreenResult]) -> list[float] | None:
    values = [float(getattr(case, value_key)) for case in cases]
    return _range_pair(values)


def _clmax_robust_counts(
    by_clmax_rows: list[dict[str, object]],
    *,
    include_zero: bool = True,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in by_clmax_rows:
        key = f"{float(row['cl_max_effective']):.6g}"  # stable text keys for JSON
        count = int(row["robust_cases"])
        if include_zero or count > 0:
            counts[key] = count
    return counts


def _robust_region(cases: list[MissionQuickScreenResult]) -> dict[str, list[float] | None]:
    if not cases:
        return {
            "speed_mps": None,
            "span_m": None,
            "aspect_ratio": None,
            "cd0_total": None,
            "cl_max_effective": None,
            "mass_kg": None,
            "oswald_e": None,
        }
    return {
        "speed_mps": _robust_range("speed_mps", cases),
        "span_m": _robust_range("span_m", cases),
        "aspect_ratio": _robust_range("aspect_ratio", cases),
        "cd0_total": _robust_range("cd0_total", cases),
        "cl_max_effective": _robust_range("cl_max_effective", cases),
        "mass_kg": _robust_range("mass_kg", cases),
        "oswald_e": _robust_range("oswald_e", cases),
    }


def _select_main_design_region(cases: list[MissionQuickScreenResult], by_cd0_rows: list[dict[str, object]]) -> dict[str, list[float] | None]:
    if not cases:
        return {
            "speed_mps": None,
            "span_m": None,
            "aspect_ratio": None,
            "cd0_total": None,
            "cl_max_effective": None,
            "mass_kg": None,
            "oswald_e": None,
        }

    cd0_counts: dict[float, int] = {}
    for row in by_cd0_rows:
        cd0 = float(row["cd0_total"])
        cd0_counts[cd0] = int(row["robust_cases"])

    if not cd0_counts:
        return _robust_region(cases)

    max_cd0_count = max(cd0_counts.values())
    if max_cd0_count <= 0:
        return _robust_region(cases)

    threshold = max(1, int(max_cd0_count * 0.20))
    if threshold <= 0:
        threshold = 1
    keep_cd0 = {
        cd0
        for cd0, count in cd0_counts.items()
        if count >= threshold
    }
    filtered_cases = [
        case for case in cases if float(case.cd0_total) in keep_cd0
    ]
    if not filtered_cases:
        return _robust_region(cases)
    return _robust_region(filtered_cases)


def _build_summary_payload(
    spec,
    *,
    cases: list[MissionQuickScreenResult],
    envelopes: list[dict[str, object]],
    summary: dict[str, int | float],
    heat_derate: float,
    test_env: RiderPowerEnvironment,
    target_env: RiderPowerEnvironment,
    plot_paths: dict[str, str],
) -> dict[str, object]:
    robust_cases = [case for case in cases if is_robust_case(case, spec.filters)]
    has_robust = len(robust_cases) > 0

    by_cd0 = [row for row in envelopes if row.get("group") == "by_cd0"]
    by_ar = [row for row in envelopes if row.get("group") == "by_aspect_ratio"]
    by_span = [row for row in envelopes if row.get("group") == "by_span"]
    by_clmax = [row for row in envelopes if row.get("group") == "by_clmax"]
    robust_by_clmax = [row for row in by_clmax if row.get("robust_cases", 0) > 0]

    observed_robust_envelope = _robust_region(robust_cases)
    suggested_main_design_region = _select_main_design_region(
        cases=robust_cases,
        by_cd0_rows=by_cd0,
    )

    by_speed = [row for row in envelopes if row.get("group") == "by_speed"]
    robust_speed_rows = [row for row in by_speed if row.get("robust_cases", 0) > 0]
    by_cd0_robust_rows = [row for row in by_cd0 if row.get("robust_cases", 0) > 0]
    by_ar_robust_rows = [row for row in by_ar if row.get("robust_cases", 0) > 0]
    by_span_robust_rows = [row for row in by_span if row.get("robust_cases", 0) > 0]

    payload: dict[str, object] = {
        "input_paths": {
            "power_csv": str(spec.rider_power_csv),
            "metadata_yaml": str(spec.rider_metadata_yaml),
        },
        "environments": {
            "test_environment": {
                "temperature_c": test_env.temperature_c,
                "relative_humidity_percent": test_env.relative_humidity_percent,
            },
            "target_environment": {
                "temperature_c": target_env.temperature_c,
                "relative_humidity_percent": target_env.relative_humidity_percent,
            },
            "heat_derate_factor": heat_derate,
        },
        "counts": {
            "total_cases": summary["total_cases"],
            "power_passed_cases": summary["power_passed_cases"],
            "robust_cases": summary["robust_cases"],
            "margin_ge_min_cases": summary["margin_ge_min_cases"],
            "margin_ge_robust_cases": summary["margin_ge_robust_cases"],
        },
        "robust_definition": {
            "power_passed_required": True,
            "min_power_margin_crank_w": spec.filters.min_power_margin_crank_w,
            "robust_power_margin_crank_w": spec.filters.robust_power_margin_crank_w,
            "allowed_cl_bands": list(spec.filters.allowed_cl_bands),
            "allowed_stall_bands": list(spec.filters.allowed_stall_bands),
            "max_cl_to_clmax_ratio": spec.filters.max_cl_to_clmax_ratio,
        },
        "robust_speed_envelope": observed_robust_envelope["speed_mps"],
        "cd0_envelope": observed_robust_envelope["cd0_total"],
        "ar_envelope": observed_robust_envelope["aspect_ratio"],
        "span_envelope": observed_robust_envelope["span_m"],
        "observed_robust_envelope": observed_robust_envelope,
        "clmax_robust_counts": _clmax_robust_counts(robust_by_clmax),
        "suggested_main_design_region": suggested_main_design_region,
        "has_robust_design_space": has_robust,
        "output_files": {
            "full_results_csv": "full_results.csv",
            "envelope_by_speed_csv": "envelope_by_speed.csv",
            "envelope_by_cd0_csv": "envelope_by_cd0.csv",
            "envelope_by_ar_csv": "envelope_by_ar.csv",
            "envelope_by_span_csv": "envelope_by_span.csv",
            "envelope_by_clmax_csv": "envelope_by_clmax.csv",
            "boundary_speed_cd0_csv": "boundary_speed_cd0.csv",
            "report_md": "report.md",
        },
        "robust_summary_by_speed": [
            {
                "speed_mps": row["speed_mps"],
                "robust_cases": row["robust_cases"],
            }
            for row in robust_speed_rows
        ],
        "cd0_envelope_by_cd0": [
            {
                "cd0_total": row["cd0_total"],
                "robust_cases": row["robust_cases"],
                "feasible_speed_min": row["feasible_speed_min"],
                "feasible_speed_max": row["feasible_speed_max"],
            }
            for row in by_cd0_robust_rows
        ],
        "ar_envelope_by_ar": [
            {
                "aspect_ratio": row["aspect_ratio"],
                "robust_cases": row["robust_cases"],
                "feasible_speed_min": row["feasible_speed_min"],
                "feasible_speed_max": row["feasible_speed_max"],
            }
            for row in by_ar_robust_rows
        ],
        "span_envelope_by_span": [
            {
                "span_m": row["span_m"],
                "robust_cases": row["robust_cases"],
                "feasible_speed_min": row["feasible_speed_min"],
                "feasible_speed_max": row["feasible_speed_max"],
            }
            for row in by_span_robust_rows
        ],
        "clmax_robust_counts_detail": {
            f"{float(row['cl_max_effective']):.6g}": {
                "robust_cases": int(row["robust_cases"]),
                "over_clmax_cases": int(row["over_clmax_cases"]),
                "thin_margin_cases": int(row["thin_margin_cases"]),
                "healthy_cases": int(row["healthy_cases"]),
                "caution_cases": int(row["caution_cases"]),
            }
            for row in robust_by_clmax
        },
        "plot_paths": plot_paths,
    }
    return payload


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
            summary_json_path=spec.output_dir / SUMMARY_JSON_FILENAME,
            plot_paths=plot_paths or None,
        )

    summary_json_path = spec.output_dir / SUMMARY_JSON_FILENAME
    payload = _build_summary_payload(
        spec,
        cases=cases,
        envelopes=envelopes,
        summary=summary,
        heat_derate=heat_derate,
        test_env=test_env,
        target_env=target_env,
        plot_paths=plot_paths if spec.write_plots and not skip_plots else {},
    )
    summary_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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
