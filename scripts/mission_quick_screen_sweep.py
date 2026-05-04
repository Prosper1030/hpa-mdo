#!/usr/bin/env python3
"""Mission quick-screen sweep CLI."""

from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
import csv
from typing import Any

from hpa_mdo.mission import (
    MissionQuickScreenResult,
    RiderPowerEnvironment,
    load_csv_power_curve,
    load_rider_power_curve_metadata,
    sweep_quick_screen_grid,
    thermal_power_derate_factor,
)

DEFAULT_POWER_CSV = Path("data/pilot_power_curves/current_pilot_power_curve.csv")
DEFAULT_METADATA_YAML = Path(
    "data/pilot_power_curves/current_pilot_power_curve.metadata.yaml"
)
DEFAULT_OUTPUT_DIR = Path("output/mission_quick_screen_sweep")

ROBUST_STALL_BANDS = {"healthy", "caution"}


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Mission quick-screen sweep over speed/span/AR/CD0/CLmax."
    )
    parser.add_argument(
        "--power-csv",
        default=str(DEFAULT_POWER_CSV),
        help="Pilot power curve CSV path.",
    )
    parser.add_argument(
        "--metadata-yaml",
        default=str(DEFAULT_METADATA_YAML),
        help="Pilot power curve metadata YAML path.",
    )
    parser.add_argument("--speed-min", type=float, default=5.8, help="Minimum speed (m/s).")
    parser.add_argument("--speed-max", type=float, default=7.0, help="Maximum speed (m/s).")
    parser.add_argument("--speed-step", type=float, default=0.1, help="Speed step (m/s).")
    parser.add_argument(
        "--span-list",
        default="33,34,35",
        help='Comma-separated span list (m), e.g. "33,34,35".',
    )
    parser.add_argument(
        "--ar-list",
        default="37,38,39,40",
        help='Comma-separated AR list, e.g. "37,38,39,40".',
    )
    parser.add_argument(
        "--cd0-list",
        default="0.016,0.017,0.018,0.020",
        help='Comma-separated CD0 list, e.g. "0.016,0.017,0.018,0.020".',
    )
    parser.add_argument(
        "--clmax-list",
        default="1.45,1.55,1.65",
        help='Comma-separated effective CLmax list, e.g. "1.45,1.55,1.65".',
    )
    parser.add_argument("--mass-kg", type=float, default=98.5, help="Aircraft mass (kg).")
    parser.add_argument("--oswald-e", type=float, default=0.90, help="Oswald efficiency.")
    parser.add_argument("--rho", type=float, default=1.1357, help="Air density (kg/m^3).")
    parser.add_argument("--eta-prop", type=float, default=0.86, help="Propulsive efficiency.")
    parser.add_argument("--eta-trans", type=float, default=0.96, help="Transmission efficiency.")
    parser.add_argument(
        "--target-range-km", type=float, default=42.195, help="Mission range (km)."
    )
    parser.add_argument(
        "--target-temp-c",
        type=float,
        default=33.0,
        help="Target environment temperature (°C).",
    )
    parser.add_argument(
        "--target-rh",
        type=float,
        default=80.0,
        help="Target environment relative humidity (%).",
    )
    parser.add_argument(
        "--heat-k",
        type=float,
        default=0.008,
        help="Heat loss coefficient (1/°C).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output folder for results.csv and report.md.",
    )
    return parser


def _parse_float_list(raw: str, field_name: str) -> tuple[float, ...]:
    items = [item.strip() for item in raw.split(",")]
    if not items:
        raise ValueError(f"{field_name} requires at least one value.")
    values: list[float] = []
    for item in items:
        if not item:
            raise ValueError(f"{field_name} contains empty item: {raw!r}")
        values.append(float(item))
    return tuple(values)


def _build_speed_values(
    speed_min: float,
    speed_max: float,
    speed_step: float,
) -> list[float]:
    if speed_step <= 0.0:
        raise ValueError("speed-step must be > 0.")
    if speed_max < speed_min:
        raise ValueError("speed-max must be >= speed-min.")

    values: list[float] = []
    value = float(speed_min)
    while value <= float(speed_max) + 1.0e-9:
        values.append(round(value, 10))
        value += float(speed_step)
    if round(values[-1], 10) != round(float(speed_max), 10):
        values.append(round(float(speed_max), 10))

    unique: list[float] = []
    for speed_mps in values:
        if speed_mps not in unique:
            unique.append(speed_mps)
    return unique


def _find_metadata_measurement_environment(metadata: dict[str, Any]) -> RiderPowerEnvironment:
    measurement = metadata.get("measurement_environment")
    if not isinstance(measurement, dict):
        raise ValueError("metadata must contain measurement_environment.")
    try:
        return RiderPowerEnvironment(
            temperature_c=float(measurement["temperature_c"]),
            relative_humidity_percent=float(measurement["relative_humidity_percent"]),
        )
    except (TypeError, KeyError) as exc:
        raise ValueError("metadata measurement_environment is missing required fields.") from exc


def _missing_file_message(kind: str, path: Path) -> str:
    return (
        f"{kind} not found: {path}\n"
        "Tip: locate files with:\n"
        "  find data -iname \"*power*curve*.csv\"\n"
        "  find . -iname \"*power*curve*.metadata.yaml\""
    )


def _candidate_sort_key(case: MissionQuickScreenResult) -> tuple[int, int, float, float]:
    power_ok = 1 if case.power_passed else 0
    stall_ok = 1 if case.stall_band in ROBUST_STALL_BANDS else 0
    margin = -1.0e30 if case.power_margin_crank_w is None else case.power_margin_crank_w
    return (power_ok, stall_ok, margin, -case.required_time_min)


def _write_results_csv(
    path: Path, cases: list[MissionQuickScreenResult], mass_kg: float
) -> None:
    field_names = (
        "speed_mps",
        "span_m",
        "aspect_ratio",
        "cd0_total",
        "cl_max_effective",
        "mass_kg",
        "required_time_min",
        "cl_required",
        "cl_to_clmax_ratio",
        "stall_speed_mps",
        "stall_margin_speed_ratio",
        "cl_band",
        "stall_band",
        "induced_power_air_w",
        "parasite_power_air_w",
        "total_power_air_w",
        "required_crank_power_w",
        "pilot_power_test_w",
        "pilot_power_hot_w",
        "power_margin_crank_w",
        "cd0_max",
        "critical_drag_n",
        "power_passed",
    )
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=field_names)
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "speed_mps": f"{case.speed_mps:.6f}",
                    "span_m": f"{case.span_m:.6f}",
                    "aspect_ratio": f"{case.aspect_ratio:.6f}",
                    "cd0_total": f"{case.cd0_total:.6f}",
                    "cl_max_effective": f"{case.cl_max_effective:.6f}",
                    "mass_kg": f"{mass_kg:.6f}",
                    "required_time_min": f"{case.required_time_min:.6f}",
                    "cl_required": f"{case.cl_required:.6f}",
                    "cl_to_clmax_ratio": f"{case.cl_to_clmax_ratio:.6f}",
                    "stall_speed_mps": f"{case.stall_speed_mps:.6f}",
                    "stall_margin_speed_ratio": f"{case.stall_margin_speed_ratio:.6f}",
                    "cl_band": case.cl_band,
                    "stall_band": case.stall_band,
                    "induced_power_air_w": f"{case.induced_power_air_w:.6f}",
                    "parasite_power_air_w": f"{case.parasite_power_air_w:.6f}",
                    "total_power_air_w": f"{case.total_power_air_w:.6f}",
                    "required_crank_power_w": f"{case.required_crank_power_w:.6f}",
                    "pilot_power_test_w": "" if case.pilot_power_test_w is None else f"{case.pilot_power_test_w:.6f}",
                    "pilot_power_hot_w": "" if case.pilot_power_hot_w is None else f"{case.pilot_power_hot_w:.6f}",
                    "power_margin_crank_w": "" if case.power_margin_crank_w is None else f"{case.power_margin_crank_w:.6f}",
                    "cd0_max": "" if case.cd0_max is None else f"{case.cd0_max:.6f}",
                    "critical_drag_n": "" if case.critical_drag_n is None else f"{case.critical_drag_n:.6f}",
                    "power_passed": str(case.power_passed),
                }
            )


def _write_markdown_report(
    path: Path,
    *,
    power_csv: Path,
    metadata_yaml: Path,
    test_env: RiderPowerEnvironment,
    target_env: RiderPowerEnvironment,
    heat_derate: float,
    speed_values: list[float],
    span_list: tuple[float, ...],
    ar_list: tuple[float, ...],
    cd0_list: tuple[float, ...],
    clmax_list: tuple[float, ...],
    cases: list[MissionQuickScreenResult],
    robust_cases: list[MissionQuickScreenResult],
    top_candidates: list[MissionQuickScreenResult],
) -> None:
    total_cases = len(cases)
    passed_cases = sum(1 for case in cases if case.power_passed)
    robust_case_count = len(robust_cases)

    if robust_cases:
        robust_speeds = sorted({case.speed_mps for case in robust_cases})
        recommended_speed_interval = f"{min(robust_speeds):.1f} ~ {max(robust_speeds):.1f} m/s"
        cd0_count = Counter(case.cd0_total for case in robust_cases)
        recommended_cd0 = sorted(
            cd0_count.items(),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        )[0][0]
    else:
        recommended_speed_interval = "N/A"
        recommended_cd0 = "N/A"

    repr_speed_targets = (6.0, 6.3, 6.5, 7.0)
    def _find_by_speed(speed: float) -> MissionQuickScreenResult | None:
        exact = [case for case in cases if abs(case.speed_mps - speed) < 1.0e-9]
        if exact:
            return max(exact, key=lambda case: case.power_margin_crank_w or -1.0e30)
        return min(cases, key=lambda case: abs(case.speed_mps - speed)) if cases else None

    representative: list[tuple[float, MissionQuickScreenResult | None]] = [
        (speed, _find_by_speed(speed)) for speed in repr_speed_targets
    ]

    narrow_margin = [
        case
        for case in cases
        if case.power_passed and (case.power_margin_crank_w is not None) and case.power_margin_crank_w <= 5.0
    ]
    risky_stall = [
        case
        for case in cases
        if case.power_passed and case.stall_band not in ROBUST_STALL_BANDS
    ]

    lines = [
        "# Mission Quick-Screen Sweep Report",
        "",
        f"- Power CSV: `{power_csv.resolve()}`",
        f"- Metadata YAML: `{metadata_yaml.resolve()}`",
        f"- Test environment: {test_env.temperature_c:.2f}°C / {test_env.relative_humidity_percent:.1f}%RH",
        f"- Target environment: {target_env.temperature_c:.2f}°C / {target_env.relative_humidity_percent:.1f}%RH",
        f"- Heat derate factor: {heat_derate:.12f}",
        f"- Speeds: {speed_values}",
        f"- Spans: {span_list}",
        f"- AR list: {ar_list}",
        f"- CD0 list: {cd0_list}",
        f"- CLmax-effective list: {clmax_list}",
        f"- total cases: {total_cases}",
        f"- passed cases: {passed_cases}",
        f"- robust candidates: {robust_case_count}",
        f"- recommended speed interval: {recommended_speed_interval}",
        f"- recommended CD0_total: {recommended_cd0}",
        "",
        "## Top 10 candidates",
    ]

    if top_candidates:
        lines.append(
            "| rank | speed | span | AR | CD0 | CLmax | power_margin(W) | cl_band | stall_band | required_time(min) |"
        )
        lines.append(
            "|---|---:|---:|---:|---:|---:|---:|---|---|---:|"
        )
        for index, case in enumerate(top_candidates, start=1):
            margin_text = "n/a" if case.power_margin_crank_w is None else f"{case.power_margin_crank_w:.2f}"
            lines.append(
                f"| {index} | {case.speed_mps:.1f} | {case.span_m:.1f} | {case.aspect_ratio:.1f} | {case.cd0_total:.3f} | {case.cl_max_effective:.2f} | {margin_text} | {case.cl_band} | {case.stall_band} | {case.required_time_min:.2f} |"
            )
    else:
        lines.append("- No candidates.")

    lines.extend(
        [
            "",
            "## Representative speed results",
        ]
    )
    for speed, case in representative:
        if case is None:
            lines.append(f"- {speed:.1f} m/s: no candidate")
            continue
        margin_text = "n/a" if case.power_margin_crank_w is None else f"{case.power_margin_crank_w:.2f} W"
        lines.append(
            f"- {speed:.1f} m/s: speed={case.speed_mps:.1f}, span={case.span_m:.1f}, AR={case.aspect_ratio:.1f}, CD0={case.cd0_total:.3f}, CLmax={case.cl_max_effective:.2f}, margin={margin_text}, power={case.power_passed}"
        )

    lines.extend(
        [
            "",
            "## pass=True but power_margin <= 5 W",
        ]
    )
    if narrow_margin:
        for case in sorted(
            narrow_margin,
            key=lambda case: (case.power_passed is False, case.power_margin_crank_w or 0.0),
        ):
            lines.append(
                f"- speed={case.speed_mps:.1f} span={case.span_m:.1f} AR={case.aspect_ratio:.1f} CD0={case.cd0_total:.3f} CLmax={case.cl_max_effective:.2f} margin={case.power_margin_crank_w:.2f}W"
            )
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## power passed but stall band is risky",
        ]
    )
    if risky_stall:
        for case in sorted(
            risky_stall,
            key=lambda case: (case.power_margin_crank_w is None, case.power_margin_crank_w or 0.0),
        ):
            lines.append(
                f"- speed={case.speed_mps:.1f} span={case.span_m:.1f} AR={case.aspect_ratio:.1f} CD0={case.cd0_total:.3f} CLmax={case.cl_max_effective:.2f} margin={case.power_margin_crank_w:.2f}W stall_band={case.stall_band}"
            )
    else:
        lines.append("- None.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compute_robust_cases(cases: list[MissionQuickScreenResult]) -> list[MissionQuickScreenResult]:
    return [
        case
        for case in cases
        if case.power_passed
        and case.cl_band != "too_high"
        and case.stall_band in ROBUST_STALL_BANDS
    ]


def run_sweep(
    *,
    power_csv: Path,
    metadata_yaml: Path,
    speed_min: float,
    speed_max: float,
    speed_step: float,
    span_list: tuple[float, ...],
    ar_list: tuple[float, ...],
    cd0_list: tuple[float, ...],
    clmax_list: tuple[float, ...],
    mass_kg: float,
    oswald_e: float,
    rho: float,
    eta_prop: float,
    eta_trans: float,
    target_range_km: float,
    target_temp_c: float,
    target_rh: float,
    heat_k: float,
    output_dir: Path,
) -> tuple[Path, Path, list[MissionQuickScreenResult], list[MissionQuickScreenResult]]:
    if not power_csv.exists():
        raise FileNotFoundError(_missing_file_message("Power CSV", power_csv))
    if not metadata_yaml.exists():
        raise FileNotFoundError(_missing_file_message("Metadata YAML", metadata_yaml))

    metadata = load_rider_power_curve_metadata(metadata_yaml)
    test_env = _find_metadata_measurement_environment(metadata)
    target_env = RiderPowerEnvironment(
        temperature_c=float(target_temp_c),
        relative_humidity_percent=float(target_rh),
    )
    heat_derate_factor = thermal_power_derate_factor(
        test_environment=test_env,
        target_environment=target_env,
        heat_loss_coefficient_per_h_c=float(heat_k),
    )

    rider_curve = load_csv_power_curve(power_csv, reference_duration_min=60.0)
    speed_values = _build_speed_values(speed_min, speed_max, speed_step)

    cases = sweep_quick_screen_grid(
        speeds_mps=tuple(speed_values),
        spans_m=span_list,
        aspect_ratios=ar_list,
        cd0_totals=cd0_list,
        mass_kg=mass_kg,
        oswald_e=oswald_e,
        air_density_kg_m3=rho,
        eta_prop=eta_prop,
        eta_trans=eta_trans,
        target_range_km=target_range_km,
        cl_max_effectives=clmax_list,
        rider_curve=rider_curve,
        thermal_derate_factor=heat_derate_factor,
    )

    sorted_cases = sorted(
        cases,
        key=lambda case: (case.speed_mps, case.span_m, case.aspect_ratio, case.cd0_total, case.cl_max_effective),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    results_csv = output_dir / "results.csv"
    report_md = output_dir / "report.md"
    _write_results_csv(results_csv, sorted_cases, mass_kg=mass_kg)

    robust_cases = _compute_robust_cases(sorted_cases)
    top_candidates = sorted(sorted_cases, key=_candidate_sort_key, reverse=True)[:10]

    _write_markdown_report(
        report_md,
        power_csv=power_csv,
        metadata_yaml=metadata_yaml,
        test_env=test_env,
        target_env=target_env,
        heat_derate=heat_derate_factor,
        speed_values=speed_values,
        span_list=span_list,
        ar_list=ar_list,
        cd0_list=cd0_list,
        clmax_list=clmax_list,
        cases=sorted_cases,
        robust_cases=robust_cases,
        top_candidates=top_candidates,
    )
    return results_csv, report_md, sorted_cases, robust_cases


def _print_console_summary(
    *,
    power_csv: Path,
    metadata_yaml: Path,
    heat_derate: float,
    cases: list[MissionQuickScreenResult],
    robust_cases: list[MissionQuickScreenResult],
    top_candidates: list[MissionQuickScreenResult],
) -> None:
    total_cases = len(cases)
    passed_cases = sum(1 for case in cases if case.power_passed)
    robust_count = len(robust_cases)

    print(f"power CSV: {power_csv}")
    print(f"metadata: {metadata_yaml}")
    print(f"heat derate factor: {heat_derate:.12f}")
    print(f"total cases: {total_cases}")
    print(f"passed cases: {passed_cases}")
    print(f"robust candidates: {robust_count}")
    print("top 10 candidates:")
    for index, case in enumerate(top_candidates, start=1):
        if case.power_margin_crank_w is None:
            continue
        print(
            f"{index:>2d}. v={case.speed_mps:.1f} b={case.span_m:.1f} AR={case.aspect_ratio:.1f} "
            f"CD0={case.cd0_total:.3f} CLmax={case.cl_max_effective:.2f} "
            f"margin={case.power_margin_crank_w:.2f}W cl_band={case.cl_band} stall={case.stall_band}"
        )


def _parse_args() -> Any:
    parser = _build_parser()
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    power_csv = Path(args.power_csv)
    metadata_yaml = Path(args.metadata_yaml)
    output_dir = Path(args.output_dir)

    span_list = _parse_float_list(args.span_list, "--span-list")
    ar_list = _parse_float_list(args.ar_list, "--ar-list")
    cd0_list = _parse_float_list(args.cd0_list, "--cd0-list")
    clmax_list = _parse_float_list(args.clmax_list, "--clmax-list")

    try:
        results_csv, report_md, cases, robust_cases = run_sweep(
            power_csv=power_csv,
            metadata_yaml=metadata_yaml,
            speed_min=args.speed_min,
            speed_max=args.speed_max,
            speed_step=args.speed_step,
            span_list=span_list,
            ar_list=ar_list,
            cd0_list=cd0_list,
            clmax_list=clmax_list,
            mass_kg=args.mass_kg,
            oswald_e=args.oswald_e,
            rho=args.rho,
            eta_prop=args.eta_prop,
            eta_trans=args.eta_trans,
            target_range_km=args.target_range_km,
            target_temp_c=args.target_temp_c,
            target_rh=args.target_rh,
            heat_k=args.heat_k,
            output_dir=output_dir,
        )
        metadata = load_rider_power_curve_metadata(metadata_yaml)
        test_env = _find_metadata_measurement_environment(metadata)
        target_env = RiderPowerEnvironment(
            temperature_c=args.target_temp_c,
            relative_humidity_percent=args.target_rh,
        )
        heat_derate = thermal_power_derate_factor(
            test_environment=test_env,
            target_environment=target_env,
            heat_loss_coefficient_per_h_c=args.heat_k,
        )
    except Exception as exc:
        print(f"Failed: {exc}")
        return 1

    top_candidates = sorted(
        cases,
        key=_candidate_sort_key,
        reverse=True,
    )[:10]
    _print_console_summary(
        power_csv=power_csv,
        metadata_yaml=metadata_yaml,
        heat_derate=heat_derate,
        cases=cases,
        robust_cases=robust_cases,
        top_candidates=top_candidates,
    )
    print(f"results.csv: {results_csv}")
    print(f"report.md: {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
