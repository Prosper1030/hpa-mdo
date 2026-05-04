#!/usr/bin/env python3
"""Mission design-space explorer CLI."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from dataclasses import replace
from itertools import product
from pathlib import Path
import json
from typing import Any, Sequence

from hpa_mdo.mission import (
    MissionQuickScreenResult,
    RiderPowerEnvironment,
    build_boundary_tables,
    build_feasible_envelope,
    MissionDesignSpaceSpec,
    load_mission_design_space_spec,
    summarize_seed_tier_counts,
    summarize_optimizer_exploration_tier_counts,
    write_candidate_seed_pool_csv,
    build_candidate_seed_pool,
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
CANDIDATE_SEED_POOL_CSV_FILENAME = "candidate_seed_pool.csv"
OPTIMIZER_HANDOFF_JSON_FILENAME = "optimizer_handoff.json"
HUMAN_READABLE_SUMMARY_JSON_FILENAME = "human_readable_summary.json"


def _format_stall_band_counts(cases: Sequence[MissionQuickScreenResult]) -> str:
    bands = ("healthy", "caution", "thin_margin", "over_clmax")
    return " / ".join(
        f"{band}:{sum(1 for case in cases if case.stall_band == band)}"
        for band in bands
    )


def _coerce_bounds(values: Sequence[float] | None) -> list[float] | None:
    if not values:
        return None
    return [float(min(values)), float(max(values))]


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


def _coerce_range_from_region(
    region: dict[str, list[float] | None],
    key: str,
    fallback: Sequence[float],
) -> list[float]:
    value = region.get(key)
    if value is not None and len(value) == 2:
        return value
    return [float(min(fallback)), float(max(fallback))]


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
    robust_region: dict[str, list[float] | None] | None = None,
    suggested_main_design_region: dict[str, list[float] | None] | None = None,
    optimizer_handoff_json: str | None = None,
    candidate_seed_pool_csv: str | None = None,
    seed_tier_counts: dict[str, int] | None = None,
    optimizer_exploration_tier_counts: dict[str, int] | None = None,
) -> dict[str, object]:
    robust_cases = [case for case in cases if is_robust_case(case, spec.filters)]
    has_robust = len(robust_cases) > 0

    by_cd0 = [row for row in envelopes if row.get("group") == "by_cd0"]
    by_ar = [row for row in envelopes if row.get("group") == "by_aspect_ratio"]
    by_span = [row for row in envelopes if row.get("group") == "by_span"]
    by_clmax = [row for row in envelopes if row.get("group") == "by_clmax"]
    robust_by_clmax = [row for row in by_clmax if row.get("robust_cases", 0) > 0]

    observed_robust_envelope = (
        robust_region
        if robust_region is not None
        else _robust_region(robust_cases)
    )
    resolved_suggested_region = (
        suggested_main_design_region
        if suggested_main_design_region is not None
        else _select_main_design_region(
            cases=robust_cases,
            by_cd0_rows=by_cd0,
        )
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
        "suggested_main_design_region": resolved_suggested_region,
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
            "candidate_seed_pool_csv": (
                candidate_seed_pool_csv if candidate_seed_pool_csv is not None else None
            ),
            "optimizer_handoff_json": (
                optimizer_handoff_json if optimizer_handoff_json is not None else None
            ),
        },
        "optimizer_handoff": {
            "optimizer_handoff_json": (
                optimizer_handoff_json if optimizer_handoff_json is not None else None
            ),
            "candidate_seed_pool_csv": (
                candidate_seed_pool_csv if candidate_seed_pool_csv is not None else None
            ),
            "seed_tier_counts": (
                seed_tier_counts
                if seed_tier_counts is not None
                else {
                    "high_confidence": 0,
                    "primary": 0,
                    "boundary": 0,
                    "reject": 0,
                }
            ),
            "optimizer_exploration_tier_counts": (
                optimizer_exploration_tier_counts
                if optimizer_exploration_tier_counts is not None
                else {
                    "exploration_primary": 0,
                    "exploration_promising": 0,
                    "exploration_boundary": 0,
                    "exploration_reject": 0,
                }
            ),
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


def _build_human_readable_summary(
    *,
    spec: MissionDesignSpaceSpec,
    summary: dict[str, int | float],
    cases: list[MissionQuickScreenResult],
    summary_payload: dict[str, object],
    robust_region: dict[str, list[float] | None] | None,
    candidate_seed_pool_csv_path: Path,
    optimizer_handoff_json_path: Path,
    test_env: RiderPowerEnvironment,
    target_env: RiderPowerEnvironment,
    report_path: Path,
) -> dict[str, object]:
    robust_cases = summary_payload.get("counts", {}).get("robust_cases", 0)
    has_robust_design_space = bool(robust_cases)
    robust_speed_values = []
    if cases:
        robust_speed_values = sorted(
            {float(case.speed_mps) for case in cases if is_robust_case(case, spec.filters)},
        )
    robust_speed_envelope = (
        [float(min(robust_speed_values)), float(max(robust_speed_values))]
        if robust_speed_values
        else None
    )

    suggested_main_design_region = summary_payload.get("suggested_main_design_region")
    by_cd0 = summary_payload.get("cd0_envelope_by_cd0")
    cd0_sensitivity = "資料不足，CD0 敏感度無法判讀。"
    if isinstance(by_cd0, list) and by_cd0:
        best_cd0 = max(by_cd0, key=lambda row: int(row.get("robust_cases", 0)))
        least_cd0 = min(by_cd0, key=lambda row: int(row.get("robust_cases", 0)))
        cd0_sensitivity = (
            "CD0 影響可行密度明顯："
            f"{best_cd0['cd0_total']} 段有較多 robust 候選({best_cd0['robust_cases']})，"
            f"{least_cd0['cd0_total']} 段較少({least_cd0['robust_cases']})。"
        )

    clmax_counts = summary_payload.get("clmax_robust_counts_detail", {})
    if isinstance(clmax_counts, dict) and clmax_counts:
        clmax_sorted = sorted(
            (float(k), v) for k, v in clmax_counts.items() if isinstance(v, dict)
        )
        stall_summary = []
        for clmax_value, details in clmax_sorted:
            stall_summary.append(
                f"CLmax={clmax_value:g}:healthy={details.get('healthy_cases', 0)},"
                f"caution={details.get('caution_cases', 0)},thin_margin={details.get('thin_margin_cases', 0)},"
                f"over={details.get('over_clmax_cases', 0)}"
            )
        stall_sensitivity = "；".join(stall_summary[:3])
    else:
        stall_sensitivity = "CLmax/stall 分佈資料不足，建議補足候選點。"

    low_speed = min((float(case.speed_mps) for case in cases), default=None)
    high_speed = max((float(case.speed_mps) for case in cases), default=None)
    low_speed_cases = (
        [case for case in cases if low_speed is not None and abs(float(case.speed_mps) - low_speed) <= 1e-9]
        if low_speed is not None
        else []
    )
    high_speed_cases = (
        [case for case in cases if high_speed is not None and abs(float(case.speed_mps) - high_speed) <= 1e-9]
        if high_speed is not None
        else []
    )

    low_speed_risk = (
        f"{low_speed:.2f} m/s: {_format_stall_band_counts(low_speed_cases)}"
        if low_speed is not None
        else "no data"
    )
    high_speed_risk = (
        f"{high_speed:.2f} m/s: {_format_stall_band_counts(high_speed_cases)}"
        if high_speed is not None
        else "no data"
    )

    return {
        "schema_version": "mission_human_summary_v1",
        "mission": {
            "target_range_km": spec.target_range_km,
            "target_speed_mps": {
                "min": float(min((case.speed_mps for case in cases), default=0.0)),
                "max": float(max((case.speed_mps for case in cases), default=0.0)),
            },
        },
        "environment": {
            "test_environment": {
                "temperature_c": test_env.temperature_c,
                "relative_humidity_percent": test_env.relative_humidity_percent,
            },
            "target_environment": {
                "temperature_c": target_env.temperature_c,
                "relative_humidity_percent": target_env.relative_humidity_percent,
            },
        },
        "headline": {
            "has_robust_design_space": has_robust_design_space,
            "robust_cases": robust_cases,
            "total_cases": summary["total_cases"],
            "observed_robust_speed_envelope": robust_speed_envelope or [],
            "suggested_main_design_region": suggested_main_design_region,
        },
        "risk_summary": {
            "cd0_sensitivity": cd0_sensitivity,
            "stall_sensitivity": stall_sensitivity,
            "low_speed_risk": low_speed_risk,
            "high_speed_risk": high_speed_risk,
        },
        "user_guidance": [
            "這不是 optimizer。",
            "這不是唯一最佳設計。",
            "請用此輸出決定下一層分析範圍。",
        ],
        "important_paths": {
            "report_md": str(report_path),
            "summary_json": str(report_path.parent / SUMMARY_JSON_FILENAME),
            "optimizer_handoff_json": str(optimizer_handoff_json_path),
            "candidate_seed_pool_csv": str(candidate_seed_pool_csv_path),
            "plots_dir": str(report_path.parent / "plots"),
            "candidate_robust_region": robust_region,
        },
    }


def _build_optimizer_handoff_payload(
    *,
    spec: MissionDesignSpaceSpec,
    suggested_region: dict[str, list[float] | None],
    observed_robust_envelope: dict[str, list[float] | None],
    candidate_seed_pool: list[dict[str, float | int | None | str]],
    seed_tier_counts: dict[str, int],
    optimizer_exploration_tier_counts: dict[str, int] | None = None,
    candidate_seed_pool_path: str = CANDIDATE_SEED_POOL_CSV_FILENAME,
    optimizer_handoff_path: str = OPTIMIZER_HANDOFF_JSON_FILENAME,
    test_env: RiderPowerEnvironment,
    target_env: RiderPowerEnvironment,
    heat_derate: float,
) -> dict[str, object]:
    return {
        "schema_version": "mission_optimizer_handoff_v1",
        "input_files": {
            "summary_json": "summary.json",
            "full_results_csv": "full_results.csv",
            "candidate_seed_pool_csv": candidate_seed_pool_path,
            "report_md": "report.md",
        },
        "mission_context": {
            "target_range_km": spec.target_range_km,
            "test_environment": {
                "temperature_c": test_env.temperature_c,
                "relative_humidity_percent": test_env.relative_humidity_percent,
            },
            "target_environment": {
                "temperature_c": target_env.temperature_c,
                "relative_humidity_percent": target_env.relative_humidity_percent,
            },
            "heat_derate_factor": heat_derate,
            "rider_power_csv": str(spec.rider_power_csv),
            "rider_metadata_yaml": str(spec.rider_metadata_yaml),
        },
        "optimizer_role": {
            "role": "search_bounds_and_pre_gate",
            "note": "This handoff defines initial search bounds, seed candidates, and mission feasibility gates. It is not a final design selection.",
        },
        "search_bounds": {
            "speed_mps": _coerce_range_from_region(
                region=suggested_region,
                key="speed_mps",
                fallback=spec.speeds_mps,
            ),
            "span_m": _coerce_range_from_region(
                region=suggested_region,
                key="span_m",
                fallback=spec.spans_m,
            ),
            "aspect_ratio": _coerce_range_from_region(
                region=suggested_region,
                key="aspect_ratio",
                fallback=spec.aspect_ratios,
            ),
            "cd0_total": _coerce_range_from_region(
                region=suggested_region,
                key="cd0_total",
                fallback=spec.cd0_totals,
            ),
            "cl_max_effective": _coerce_range_from_region(
                region=suggested_region,
                key="cl_max_effective",
                fallback=spec.cl_max_effectives,
            ),
            "mass_kg": _coerce_range_from_region(
                region={"mass_kg": _coerce_bounds(list(spec.mass_kg))},
                key="mass_kg",
                fallback=spec.mass_kg,
            ),
            "oswald_e": _coerce_range_from_region(
                region={"oswald_e": _coerce_bounds(list(spec.oswald_e))},
                key="oswald_e",
                fallback=spec.oswald_e,
            ),
        },
        "observed_robust_envelope": observed_robust_envelope,
        "suggested_main_design_region": suggested_region,
        "mission_gate": {
            "power_margin_crank_w_min": 0.0,
            "robust_power_margin_crank_w_min": 5.0,
            "cl_to_clmax_ratio_max": 0.90,
            "allowed_cl_bands": ["normal"],
            "allowed_stall_bands": ["healthy", "caution"],
        },
        "soft_objectives": {
            "maximize_power_margin": True,
            "minimize_required_time": True,
            "maximize_stall_margin": True,
            "prefer_lower_cd0": True,
            "prefer_higher_robust_fraction": True,
        },
        "seed_policy": {
            "group_key": ["speed_mps", "span_m", "aspect_ratio", "cd0_total"],
            "scenario_dimensions": [
                "mass_kg",
                "oswald_e",
                "cl_max_effective",
                "eta_prop",
                "eta_trans",
                "air_density_kg_m3",
            ],
            "ranking_fields": [
                "optimizer_exploration_tier",
                "strict_tier",
                "tier",
                "robust_fraction",
                "p10_power_margin_crank_w",
                "median_power_margin_crank_w",
                "max_power_margin_crank_w",
                "min_required_time_min",
            ],
        },
        "optimizer_exploration_policy": {
            "description": (
                "Use optimizer_exploration_tier for optimizer initialization seeds. "
                "strict_tier remains conservative engineering annotation."
            ),
            "tier_definitions": {
                "exploration_primary": {
                    "robust_scenarios": "> 0",
                    "median_power_margin_crank_w_min": 5.0,
                    "max_cl_to_clmax_ratio": 0.95,
                },
                "exploration_promising": {
                    "robust_scenarios": "> 0",
                    "median_power_margin_crank_w_min": 0.0,
                    "max_cl_to_clmax_ratio": 1.0,
                },
                "exploration_boundary": {
                    "power_passed_scenarios": "> 0",
                    "default": "not primary or promising",
                },
                "exploration_reject": {"power_passed_scenarios": "= 0"},
            },
            "tier_counts": {
                "exploration_primary": (
                    (optimizer_exploration_tier_counts or {}).get(
                        "exploration_primary",
                        0,
                    )
                    if optimizer_exploration_tier_counts is not None
                    else 0
                ),
                "exploration_promising": (
                    (optimizer_exploration_tier_counts or {}).get(
                        "exploration_promising",
                        0,
                    )
                    if optimizer_exploration_tier_counts is not None
                    else 0
                ),
                "exploration_boundary": (
                    (optimizer_exploration_tier_counts or {}).get(
                        "exploration_boundary",
                        0,
                    )
                    if optimizer_exploration_tier_counts is not None
                    else 0
                ),
                "exploration_reject": (
                    (optimizer_exploration_tier_counts or {}).get(
                        "exploration_reject",
                        0,
                    )
                    if optimizer_exploration_tier_counts is not None
                    else 0
                ),
            },
        },
        "output_files": {
            "candidate_seed_pool_csv": candidate_seed_pool_path,
            "optimizer_handoff_json": optimizer_handoff_path,
            "summary_json": "summary.json",
            "full_results_csv": "full_results.csv",
        },
        "seed_tier_counts": seed_tier_counts,
        "optimizer_exploration_tier_counts": (
            optimizer_exploration_tier_counts
            if optimizer_exploration_tier_counts is not None
            else {
                "exploration_primary": 0,
                "exploration_promising": 0,
                "exploration_boundary": 0,
                "exploration_reject": 0,
            }
        ),
        "candidate_seed_pool_count": len(candidate_seed_pool),
    }


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
    robust_cases = [case for case in cases if is_robust_case(case, spec.filters)]
    by_cd0 = [row for row in envelopes if row.get("group") == "by_cd0"]
    suggested_main_design_region = _select_main_design_region(
        cases=robust_cases,
        by_cd0_rows=by_cd0,
    )
    observed_robust_envelope = _robust_region(robust_cases)

    candidate_seed_pool = build_candidate_seed_pool(cases, spec.filters)
    seed_tier_counts = summarize_seed_tier_counts(candidate_seed_pool)
    optimizer_exploration_tier_counts = (
        summarize_optimizer_exploration_tier_counts(candidate_seed_pool)
    )

    candidate_seed_pool_csv = spec.output_dir / CANDIDATE_SEED_POOL_CSV_FILENAME
    optimizer_handoff_json = spec.output_dir / OPTIMIZER_HANDOFF_JSON_FILENAME
    human_readable_summary_json = (
        spec.output_dir / HUMAN_READABLE_SUMMARY_JSON_FILENAME
    )
    write_candidate_seed_pool_csv(candidate_seed_pool_csv, candidate_seed_pool)
    handoff_payload = _build_optimizer_handoff_payload(
        spec=spec,
        suggested_region=suggested_main_design_region,
        observed_robust_envelope=observed_robust_envelope,
        candidate_seed_pool=candidate_seed_pool,
        seed_tier_counts=seed_tier_counts,
        optimizer_exploration_tier_counts=optimizer_exploration_tier_counts,
        candidate_seed_pool_path=CANDIDATE_SEED_POOL_CSV_FILENAME,
        optimizer_handoff_path=OPTIMIZER_HANDOFF_JSON_FILENAME,
        test_env=test_env,
        target_env=target_env,
        heat_derate=heat_derate,
    )
    optimizer_handoff_json.write_text(
        json.dumps(handoff_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    full_results_csv = spec.output_dir / "full_results.csv"
    report_md = spec.output_dir / "report.md"
    summary_json_path = spec.output_dir / SUMMARY_JSON_FILENAME
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
            summary_json_path=summary_json_path,
            candidate_seed_pool_csv=candidate_seed_pool_csv,
            optimizer_handoff_json=optimizer_handoff_json,
            human_readable_summary_json=human_readable_summary_json,
            plot_paths=plot_paths or None,
        )

    payload = _build_summary_payload(
        spec,
        cases=cases,
        envelopes=envelopes,
        summary=summary,
        heat_derate=heat_derate,
        test_env=test_env,
        target_env=target_env,
        plot_paths=plot_paths if spec.write_plots and not skip_plots else {},
        robust_region=observed_robust_envelope,
        suggested_main_design_region=suggested_main_design_region,
        optimizer_handoff_json=OPTIMIZER_HANDOFF_JSON_FILENAME,
        candidate_seed_pool_csv=CANDIDATE_SEED_POOL_CSV_FILENAME,
        seed_tier_counts=seed_tier_counts,
        optimizer_exploration_tier_counts=optimizer_exploration_tier_counts,
    )
    summary_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    human_readable_summary_json.write_text(
        json.dumps(
            _build_human_readable_summary(
                spec=spec,
                summary=summary,
                cases=cases,
                summary_payload=payload,
                robust_region=observed_robust_envelope,
                candidate_seed_pool_csv_path=candidate_seed_pool_csv,
                optimizer_handoff_json_path=optimizer_handoff_json,
                test_env=test_env,
                target_env=target_env,
                report_path=report_md,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
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
    candidate_seed_pool_csv: Path | None = None,
    optimizer_handoff_json: Path | None = None,
    human_readable_summary_json: Path | None = None,
    summary_json: Path | None = None,
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
    if candidate_seed_pool_csv is not None:
        print(f"candidate_seed_pool.csv: {candidate_seed_pool_csv}")
    if optimizer_handoff_json is not None:
        print(f"optimizer_handoff.json: {optimizer_handoff_json}")
    if human_readable_summary_json is not None:
        print(f"human_readable_summary.json: {human_readable_summary_json}")
    if summary_json is not None:
        print(f"summary.json: {summary_json}")


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
            candidate_seed_pool_csv=full_csv.parent / "candidate_seed_pool.csv",
            optimizer_handoff_json=full_csv.parent / "optimizer_handoff.json",
            human_readable_summary_json=full_csv.parent
            / "human_readable_summary.json",
            summary_json=full_csv.parent / "summary.json",
        )
        print(f"total case combinations: {total_cases}")
    except Exception as exc:
        print(f"Failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
