"""Reusable mission design-space analysis helpers for quick-screen sweeps."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from statistics import median
from typing import Any

from .objective import RiderPowerEnvironment
from .quick_screen import MissionQuickScreenResult

import csv
import yaml


def _fmt_or_blank(value: Any, fmt: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int)):
        return str(value)
    return format(float(value), fmt)


@dataclass(frozen=True)
class MissionDesignSpaceFilters:
    min_power_margin_crank_w: float = 5.0
    robust_power_margin_crank_w: float = 10.0
    allowed_cl_bands: tuple[str, ...] = ("normal",)
    allowed_stall_bands: tuple[str, ...] = ("healthy", "caution")
    max_cl_to_clmax_ratio: float = 0.9


@dataclass(frozen=True)
class MissionDesignSpaceSpec:
    schema_version: str
    target_range_km: float

    rider_power_csv: Path
    rider_metadata_yaml: Path

    target_temperature_c: float
    target_relative_humidity_percent: float
    heat_loss_coefficient_per_h_c: float

    mass_kg: tuple[float, ...]
    air_density_kg_m3: tuple[float, ...]
    oswald_e: tuple[float, ...]
    eta_prop: tuple[float, ...]
    eta_trans: tuple[float, ...]

    speeds_mps: tuple[float, ...]
    spans_m: tuple[float, ...]
    aspect_ratios: tuple[float, ...]
    cd0_totals: tuple[float, ...]
    cl_max_effectives: tuple[float, ...]

    filters: MissionDesignSpaceFilters

    output_dir: Path
    write_full_results_csv: bool = True
    write_envelope_csv: bool = True
    write_markdown_report: bool = True
    write_plots: bool = True
    plot_dpi: int = 160
    plot_format: str = "png"
    max_candidate_rows_in_report: int = 10


def _coerce_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover
        raise ValueError(f"{field_name} must be a real number.") from exc


def _coerce_float_sequence(value: Any, field_name: str) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence.")
    values: list[float] = []
    for raw in value:
        values.append(_coerce_float(raw, field_name))
    if len(values) == 0:
        raise ValueError(f"{field_name} must contain at least one value.")
    return tuple(float(v) for v in values)


def _coerce_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping.")
    return value


def build_speed_values(
    speed_min: float,
    speed_max: float,
    speed_step: float,
) -> tuple[float, ...]:
    min_value = _coerce_float(speed_min, "speed min")
    max_value = _coerce_float(speed_max, "speed max")
    step = _coerce_float(speed_step, "speed step")
    if step <= 0.0:
        raise ValueError("speed step must be > 0.")
    if max_value < min_value:
        raise ValueError("speed max must be >= speed min.")
    if not isfinite(min_value) or not isfinite(max_value) or not isfinite(step):
        raise ValueError("speed values must be finite.")

    values: list[float] = []
    value = min_value
    while value <= max_value + 1.0e-9:
        values.append(round(value, 10))
        value += step
    if not values:
        raise ValueError("No speed value produced.")
    if round(values[-1], 10) != round(max_value, 10):
        values.append(round(max_value, 10))

    # preserve order, deduplicate due numeric jitter
    unique: list[float] = []
    for item in values:
        if item not in unique:
            unique.append(item)
    return tuple(unique)


def _coerce_speed_range(value: Any) -> tuple[float, ...]:
    mapping = _coerce_mapping(value, "design_space.speeds_mps")
    return build_speed_values(
        speed_min=mapping.get("min"),
        speed_max=mapping.get("max"),
        speed_step=mapping.get("step"),
    )


def _coerce_filters(value: Any) -> MissionDesignSpaceFilters:
    mapping = _coerce_mapping(value, "filters")
    return MissionDesignSpaceFilters(
        min_power_margin_crank_w=float(mapping.get("min_power_margin_crank_w", 5.0)),
        robust_power_margin_crank_w=float(
            mapping.get("robust_power_margin_crank_w", 10.0),
        ),
        allowed_cl_bands=tuple(str(item) for item in mapping.get("allowed_cl_bands", ("normal",))),
        allowed_stall_bands=tuple(str(item) for item in mapping.get("allowed_stall_bands", ("healthy", "caution"))),
        max_cl_to_clmax_ratio=float(mapping.get("max_cl_to_clmax_ratio", 0.90)),
    )


def _coerce_outputs(value: Any) -> tuple[Path, bool, bool, bool, bool]:
    mapping = _coerce_mapping(value, "outputs")
    output_dir = Path(str(mapping.get("output_dir", "output/mission_design_space")))
    write_full_results_csv = bool(mapping.get("write_full_results_csv", True))
    write_envelope_csv = bool(mapping.get("write_envelope_csv", True))
    write_markdown_report = bool(mapping.get("write_markdown_report", True))
    write_plots = bool(mapping.get("write_plots", True))
    return (
        output_dir,
        write_full_results_csv,
        write_envelope_csv,
        write_markdown_report,
        write_plots,
    )


def _coerce_plots(value: Any) -> tuple[int, str, int]:
    mapping = _coerce_mapping(value, "plots")
    dpi = int(mapping.get("dpi", 160))
    if dpi <= 0:
        raise ValueError("plots.dpi must be > 0.")
    plot_format = str(mapping.get("format", "png")).strip().lower() or "png"
    max_rows = int(mapping.get("max_candidate_rows_in_report", 10))
    if max_rows <= 0:
        raise ValueError("plots.max_candidate_rows_in_report must be > 0.")
    return dpi, plot_format, max_rows


def load_mission_design_space_spec(config_yaml: str | Path) -> MissionDesignSpaceSpec:
    payload = yaml.safe_load(Path(config_yaml).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("YAML config must be a mapping.")

    schema_version = payload.get("schema_version", "")
    if schema_version != "mission_design_space_v1":
        raise ValueError("schema_version must be mission_design_space_v1.")

    mission = _coerce_mapping(payload.get("mission"), "mission")
    rider = _coerce_mapping(payload.get("rider"), "rider")
    environment = _coerce_mapping(payload.get("environment"), "environment")
    aircraft = _coerce_mapping(payload.get("aircraft"), "aircraft")
    design_space = _coerce_mapping(payload.get("design_space"), "design_space")
    filters = _coerce_filters(payload.get("filters", {}))
    output_dir, write_full, write_env_csv, write_report, write_plots = _coerce_outputs(
        payload.get("outputs", {}),
    )
    plot_dpi, plot_format, max_candidate_rows = _coerce_plots(payload.get("plots", {}))

    return MissionDesignSpaceSpec(
        schema_version=schema_version,
        target_range_km=_coerce_float(mission.get("target_range_km"), "mission.target_range_km"),
        rider_power_csv=Path(rider.get("power_csv")),
        rider_metadata_yaml=Path(rider.get("metadata_yaml")),
        target_temperature_c=_coerce_float(
            environment.get("target_temperature_c"),
            "environment.target_temperature_c",
        ),
        target_relative_humidity_percent=_coerce_float(
            environment.get("target_relative_humidity_percent"),
            "environment.target_relative_humidity_percent",
        ),
        heat_loss_coefficient_per_h_c=_coerce_float(
            environment.get("heat_loss_coefficient_per_h_c"),
            "environment.heat_loss_coefficient_per_h_c",
        ),
        mass_kg=_coerce_float_sequence(aircraft.get("mass_kg"), "aircraft.mass_kg"),
        air_density_kg_m3=_coerce_float_sequence(
            aircraft.get("air_density_kg_m3"),
            "aircraft.air_density_kg_m3",
        ),
        oswald_e=_coerce_float_sequence(aircraft.get("oswald_e"), "aircraft.oswald_e"),
        eta_prop=_coerce_float_sequence(aircraft.get("eta_prop"), "aircraft.eta_prop"),
        eta_trans=_coerce_float_sequence(aircraft.get("eta_trans"), "aircraft.eta_trans"),
        speeds_mps=_coerce_speed_range(design_space.get("speeds_mps")),
        spans_m=_coerce_float_sequence(design_space.get("spans_m"), "design_space.spans_m"),
        aspect_ratios=_coerce_float_sequence(
            design_space.get("aspect_ratios"),
            "design_space.aspect_ratios",
        ),
        cd0_totals=_coerce_float_sequence(
            design_space.get("cd0_totals"),
            "design_space.cd0_totals",
        ),
        cl_max_effectives=_coerce_float_sequence(
            design_space.get("cl_max_effectives"),
            "design_space.cl_max_effectives",
        ),
        filters=filters,
        output_dir=output_dir,
        write_full_results_csv=write_full,
        write_envelope_csv=write_env_csv,
        write_markdown_report=write_report,
        write_plots=write_plots,
        plot_dpi=plot_dpi,
        plot_format=plot_format,
        max_candidate_rows_in_report=max_candidate_rows,
    )


def count_design_space_cases(spec: MissionDesignSpaceSpec) -> int:
    return (
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


def is_robust_case(result: MissionQuickScreenResult, filters: MissionDesignSpaceFilters) -> bool:
    if not result.power_passed:
        return False
    if result.power_margin_crank_w is None:
        return False
    if result.power_margin_crank_w < filters.min_power_margin_crank_w:
        return False
    if result.cl_band not in filters.allowed_cl_bands:
        return False
    if result.stall_band not in filters.allowed_stall_bands:
        return False
    if result.cl_to_clmax_ratio > filters.max_cl_to_clmax_ratio:
        return False
    return True


def summarize_design_space(
    results: Sequence[MissionQuickScreenResult],
    filters: MissionDesignSpaceFilters,
) -> dict[str, int | float]:
    robust_cases = [result for result in results if is_robust_case(result, filters)]
    power_passed_cases = [result for result in results if result.power_passed]
    normal_cl_cases = [result for result in results if result.cl_band == "normal"]
    healthy_or_caution_stall_cases = [
        result
        for result in results
        if result.stall_band in {"healthy", "caution"}
    ]
    margin_ge_min_cases = [
        result
        for result in results
        if result.power_margin_crank_w is not None
        and result.power_margin_crank_w >= filters.min_power_margin_crank_w
    ]
    margin_ge_robust_cases = [
        result
        for result in results
        if result.power_margin_crank_w is not None
        and result.power_margin_crank_w >= filters.robust_power_margin_crank_w
    ]
    return {
        "total_cases": len(results),
        "power_passed_cases": len(power_passed_cases),
        "robust_cases": len(robust_cases),
        "normal_cl_cases": len(normal_cl_cases),
        "healthy_or_caution_stall_cases": len(healthy_or_caution_stall_cases),
        "margin_ge_min_cases": len(margin_ge_min_cases),
        "margin_ge_robust_cases": len(margin_ge_robust_cases),
    }


def _min_or_none(values: Sequence[float | None]) -> float | None:
    filtered = [value for value in values if value is not None and isfinite(float(value))]
    return min(filtered) if filtered else None


def _max_or_none(values: Sequence[float | None]) -> float | None:
    filtered = [value for value in values if value is not None and isfinite(float(value))]
    return max(filtered) if filtered else None


def _max_margin(cases: Sequence[MissionQuickScreenResult]) -> float | None:
    return _max_or_none([case.power_margin_crank_w for case in cases])


def build_feasible_envelope(
    results: Sequence[MissionQuickScreenResult],
    filters: MissionDesignSpaceFilters,
) -> list[dict[str, float | int | str | bool | None]]:
    by_speed: dict[float, list[MissionQuickScreenResult]] = defaultdict(list)
    by_cd0: dict[float, list[MissionQuickScreenResult]] = defaultdict(list)
    by_ar: dict[float, list[MissionQuickScreenResult]] = defaultdict(list)
    by_span: dict[float, list[MissionQuickScreenResult]] = defaultdict(list)
    by_clmax: dict[float, list[MissionQuickScreenResult]] = defaultdict(list)

    for result in results:
        by_speed[result.speed_mps].append(result)
        by_cd0[result.cd0_total].append(result)
        by_ar[result.aspect_ratio].append(result)
        by_span[result.span_m].append(result)
        by_clmax[result.cl_max_effective].append(result)

    rows: list[dict[str, float | int | str | bool | None]] = []

    def _append_by_speed(speed: float, group_cases: list[MissionQuickScreenResult]) -> None:
        robust_cases = [case for case in group_cases if is_robust_case(case, filters)]
        rows.append(
            {
                "group": "by_speed",
                "key": speed,
                "speed_mps": speed,
                "total_cases": len(group_cases),
                "robust_cases": len(robust_cases),
                "max_power_margin_crank_w": _max_margin(group_cases),
                "min_cd0_total_among_robust": _min_or_none(
                    [case.cd0_total for case in robust_cases],
                ),
                "max_cd0_total_among_robust": _max_or_none(
                    [case.cd0_total for case in robust_cases],
                ),
                "min_required_time_min": _min_or_none([case.required_time_min for case in group_cases]),
                "max_required_time_min": _max_or_none([case.required_time_min for case in group_cases]),
            },
        )

    for speed, group_cases in sorted(by_speed.items(), key=lambda item: item[0]):
        _append_by_speed(speed, group_cases)

    for cd0, group_cases in sorted(by_cd0.items(), key=lambda item: item[0]):
        robust_cases = [case for case in group_cases if is_robust_case(case, filters)]
        rows.append(
            {
                "group": "by_cd0",
                "key": cd0,
                "cd0_total": cd0,
                "total_cases": len(group_cases),
                "robust_cases": len(robust_cases),
                "feasible_speed_min": (
                    min(case.speed_mps for case in robust_cases)
                    if robust_cases
                    else None
                ),
                "feasible_speed_max": (
                    max(case.speed_mps for case in robust_cases)
                    if robust_cases
                    else None
                ),
                "max_power_margin_crank_w": _max_margin(group_cases),
            },
        )

    for ar, group_cases in sorted(by_ar.items(), key=lambda item: item[0]):
        robust_cases = [case for case in group_cases if is_robust_case(case, filters)]
        rows.append(
            {
                "group": "by_aspect_ratio",
                "key": ar,
                "aspect_ratio": ar,
                "total_cases": len(group_cases),
                "robust_cases": len(robust_cases),
                "feasible_speed_min": (
                    min(case.speed_mps for case in robust_cases)
                    if robust_cases
                    else None
                ),
                "feasible_speed_max": (
                    max(case.speed_mps for case in robust_cases)
                    if robust_cases
                    else None
                ),
                "max_power_margin_crank_w": _max_margin(group_cases),
            },
        )

    for span, group_cases in sorted(by_span.items(), key=lambda item: item[0]):
        robust_cases = [case for case in group_cases if is_robust_case(case, filters)]
        rows.append(
            {
                "group": "by_span",
                "key": span,
                "span_m": span,
                "total_cases": len(group_cases),
                "robust_cases": len(robust_cases),
                "feasible_speed_min": (
                    min(case.speed_mps for case in robust_cases)
                    if robust_cases
                    else None
                ),
                "feasible_speed_max": (
                    max(case.speed_mps for case in robust_cases)
                    if robust_cases
                    else None
                ),
                "max_power_margin_crank_w": _max_margin(group_cases),
            },
        )

    for clmax, group_cases in sorted(by_clmax.items(), key=lambda item: item[0]):
        rows.append(
            {
                "group": "by_clmax",
                "key": clmax,
                "cl_max_effective": clmax,
                "total_cases": len(group_cases),
                "robust_cases": len([case for case in group_cases if is_robust_case(case, filters)]),
                "over_clmax_cases": len([c for c in group_cases if c.stall_band == "over_clmax"]),
                "thin_margin_cases": len([c for c in group_cases if c.stall_band == "thin_margin"]),
                "healthy_cases": len([c for c in group_cases if c.stall_band == "healthy"]),
                "caution_cases": len([c for c in group_cases if c.stall_band == "caution"]),
            },
        )
    return rows


def _median_or_none(values: Sequence[float | None]) -> float | None:
    filtered = [float(v) for v in values if v is not None and isfinite(float(v))]
    if not filtered:
        return None
    return float(median(filtered))


def build_boundary_tables(
    results: Sequence[MissionQuickScreenResult],
    filters: MissionDesignSpaceFilters,
) -> dict[str, list[dict[str, float | int | str | bool | None]]]:
    cd0_max_rows: list[dict[str, float | int | str | bool | None]] = []
    best_margin_rows: list[dict[str, float | int | str | bool | None]] = []
    robust_count_rows: list[dict[str, float | int | str | bool | None]] = []
    stall_risk_rows: list[dict[str, float | int | str | bool | None]] = []

    speed_span_ar_key: defaultdict[
        tuple[float, float, float, float, float, float, float, float],
        list[MissionQuickScreenResult],
    ] = defaultdict(list)
    speed_cd0_to_cases: defaultdict[tuple[float, float], list[MissionQuickScreenResult]] = defaultdict(list)
    speed_clmax_to_cases: defaultdict[tuple[float, float], list[MissionQuickScreenResult]] = defaultdict(list)

    for result in results:
        speed_span_ar_key[
            (
                result.speed_mps,
                result.span_m,
                result.aspect_ratio,
                result.mass_kg,
                result.eta_prop,
                result.eta_trans,
                result.air_density_kg_m3,
                result.cl_max_effective,
            )
        ].append(result)
        speed_cd0_to_cases[(result.speed_mps, result.cd0_total)].append(result)
        speed_clmax_to_cases[(result.speed_mps, result.cl_max_effective)].append(result)

    for key, group_cases in sorted(speed_span_ar_key.items()):
        speed_mps, span_m, aspect_ratio, mass_kg, eta_prop, eta_trans, air_density_kg_m3, cl_max_effective = key
        cd0_max_values = [case.cd0_max for case in group_cases if case.cd0_max is not None]
        cd0_max_rows.append(
            {
                "speed_mps": speed_mps,
                "span_m": span_m,
                "aspect_ratio": aspect_ratio,
                "mass_kg": mass_kg,
                "air_density_kg_m3": air_density_kg_m3,
                "eta_prop": eta_prop,
                "eta_trans": eta_trans,
                "cl_max_effective": cl_max_effective,
                "cd0_max_min": _min_or_none(cd0_max_values),
                "cd0_max_median": _median_or_none(cd0_max_values),
                "cd0_max_max": _max_or_none(cd0_max_values),
            },
        )

    for key, group_cases in sorted(speed_cd0_to_cases.items()):
        speed_mps, cd0_total = key
        robust_cases = [case for case in group_cases if is_robust_case(case, filters)]
        robust_count_rows.append(
            {
                "speed_mps": speed_mps,
                "cd0_total": cd0_total,
                "robust_cases": len(robust_cases),
            }
        )
        finite_cases = [case for case in group_cases if case.power_margin_crank_w is not None]
        if finite_cases:
            best = max(finite_cases, key=lambda case: case.power_margin_crank_w)
            best_margin_rows.append(
                {
                    "speed_mps": speed_mps,
                    "cd0_total": cd0_total,
                    "best_power_margin_crank_w": best.power_margin_crank_w,
                    "span_m": best.span_m,
                    "aspect_ratio": best.aspect_ratio,
                    "mass_kg": best.mass_kg,
                    "cl_max_effective": best.cl_max_effective,
                    "required_time_min": best.required_time_min,
                    "total_power_air_w": best.total_power_air_w,
                },
            )
        else:
            best_margin_rows.append(
                {
                    "speed_mps": speed_mps,
                    "cd0_total": cd0_total,
                    "best_power_margin_crank_w": None,
                    "span_m": None,
                    "aspect_ratio": None,
                    "mass_kg": None,
                    "cl_max_effective": None,
                    "required_time_min": None,
                    "total_power_air_w": None,
                },
            )

    for key, group_cases in sorted(speed_clmax_to_cases.items()):
        speed_mps, cl_max_effective = key
        stall_risk_rows.append(
            {
                "speed_mps": speed_mps,
                "cl_max_effective": cl_max_effective,
                "over_clmax_cases": len([c for c in group_cases if c.stall_band == "over_clmax"]),
                "thin_margin_cases": len([c for c in group_cases if c.stall_band == "thin_margin"]),
                "caution_cases": len([c for c in group_cases if c.stall_band == "caution"]),
                "healthy_cases": len([c for c in group_cases if c.stall_band == "healthy"]),
            },
        )

    return {
        "cd0_max_by_speed_span_ar": cd0_max_rows,
        "best_margin_by_speed_cd0": sorted(
            best_margin_rows,
            key=lambda item: (item["speed_mps"], item["cd0_total"]),
        ),
        "robust_count_by_speed_cd0": sorted(
            robust_count_rows,
            key=lambda item: (item["speed_mps"], item["cd0_total"]),
        ),
        "stall_risk_by_speed_clmax": sorted(
            stall_risk_rows,
            key=lambda item: (item["speed_mps"], item["cl_max_effective"]),
        ),
    }


_DESIGN_SPACE_PLOT_FILES: dict[str, str] = {
    "robust_cases_by_speed": "robust_cases_by_speed.png",
    "max_margin_by_speed": "max_margin_by_speed.png",
    "feasible_speed_range_by_cd0": "feasible_speed_range_by_cd0.png",
    "feasible_speed_range_by_ar": "feasible_speed_range_by_ar.png",
    "feasible_speed_range_by_span": "feasible_speed_range_by_span.png",
    "robust_cases_by_clmax": "robust_cases_by_clmax.png",
    "robust_count_heatmap_speed_cd0": "robust_count_heatmap_speed_cd0.png",
    "raw_best_margin_heatmap_speed_cd0": "raw_best_margin_heatmap_speed_cd0.png",
    "stall_risk_by_speed_clmax": "stall_risk_by_speed_clmax.png",
    "robust_candidates_speed_cd0_scatter": "robust_candidates_speed_cd0_scatter.png",
}


def _fmt_plot_float(value: Any) -> str:
    return f"{float(value):.6g}" if value is not None else "n/a"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(as_float):
        return None
    return as_float


def _plot_subtitle(spec: MissionDesignSpaceSpec, env: RiderPowerEnvironment) -> str:
    return (
        f"Mission: {spec.target_range_km:.3f} km | "
        f"Env: {env.temperature_c:.1f}°C / {env.relative_humidity_percent:.1f}%RH"
    )


def _pivot_grid(
    rows: Sequence[dict[str, Any]],
    x_key: str,
    y_key: str,
    value_key: str,
    default_value: float,
) -> tuple[list[float], list[float], list[list[float]]]:
    x_values = sorted({_safe_float(row.get(x_key)) for row in rows if _safe_float(row.get(x_key)) is not None})
    y_values = sorted({_safe_float(row.get(y_key)) for row in rows if _safe_float(row.get(y_key)) is not None})

    value_lookup: dict[tuple[float, float], float] = {}
    for row in rows:
        x_value = _safe_float(row.get(x_key))
        y_value = _safe_float(row.get(y_key))
        if x_value is None or y_value is None:
            continue
        value = _safe_float(row.get(value_key))
        if value is None:
            value = default_value
        value_lookup[(x_value, y_value)] = value

    matrix: list[list[float]] = []
    for y_value in y_values:
        matrix_row: list[float] = []
        for x_value in x_values:
            matrix_row.append(value_lookup.get((x_value, y_value), default_value))
        matrix.append(matrix_row)
    return x_values, y_values, matrix


def _safe_plot_title(ax: Any, title: str, subtitle: str) -> None:
    ax.set_title(f"{title}\n{subtitle}", loc="left", pad=12)


def _write_plot(fig: Any, path: Path, dpi: int, plot_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, format=plot_format)


def _plot_speed_group_envelopes(
    ax: Any,
    groups: dict[float, list[float]],
    x_label: str,
    y_label: str,
) -> None:
    for group_value, speeds in sorted(groups.items()):
        unique_speeds = sorted(set(speeds))
        if not unique_speeds:
            continue
        ax.plot(
            unique_speeds,
            [group_value] * len(unique_speeds),
            marker="o",
            markersize=3.0,
            linewidth=1.0,
        )
    if len(groups) <= 24:
        ax.legend(
            [f"{y_label}={y:g}" for y in sorted(groups.keys())],
            fontsize=7,
            loc="upper right",
            ncol=2,
        )


def _plot_heatmap(
    ax: Any,
    x_values: list[float],
    y_values: list[float],
    matrix: list[list[float]],
    xlabel: str,
    ylabel: str,
    color_label: str,
) -> None:
    if not x_values or not y_values:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        return
    if not matrix:
        matrix = [[0.0 for _ in x_values] for __ in y_values]

    image = ax.imshow(matrix, origin="lower", aspect="auto", cmap="viridis")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_xticks(range(len(x_values)))
    ax.set_xticklabels([_fmt_plot_float(value) for value in x_values], rotation=45, ha="right")
    ax.set_yticks(range(len(y_values)))
    ax.set_yticklabels([_fmt_plot_float(value) for value in y_values])
    colorbar = ax.figure.colorbar(image, ax=ax)
    colorbar.set_label(color_label)


def _write_design_space_plot_paths(
    filename: str,
) -> str:
    return f"plots/{filename}"


def write_design_space_plots(
    output_dir: Path,
    *,
    spec: MissionDesignSpaceSpec,
    results: Sequence[MissionQuickScreenResult],
    envelopes: Sequence[dict[str, Any]],
    boundary_tables: dict[str, list[dict[str, Any]]],
    test_env: RiderPowerEnvironment,
    target_env: RiderPowerEnvironment,
    filters: MissionDesignSpaceFilters,
) -> dict[str, str]:
    if not spec.write_plots:
        return {}
    if spec.plot_format.lower() != "png":
        raise ValueError("Only png plot output is supported.")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    by_speed = [row for row in envelopes if row.get("group") == "by_speed"]
    by_cd0 = [row for row in envelopes if row.get("group") == "by_cd0"]
    by_ar = [row for row in envelopes if row.get("group") == "by_aspect_ratio"]
    by_span = [row for row in envelopes if row.get("group") == "by_span"]
    by_clmax = [row for row in envelopes if row.get("group") == "by_clmax"]
    robust_results = [case for case in results if is_robust_case(case, filters)]

    by_cd0_cases: defaultdict[float, list[float]] = defaultdict(list)
    by_ar_cases: defaultdict[float, list[float]] = defaultdict(list)
    by_span_cases: defaultdict[float, list[float]] = defaultdict(list)

    robust_cd0_scatter: list[tuple[float, float, float]] = []
    for case in robust_results:
        by_cd0_cases[case.cd0_total].append(case.speed_mps)
        by_ar_cases[case.aspect_ratio].append(case.speed_mps)
        by_span_cases[case.span_m].append(case.speed_mps)
        if case.power_margin_crank_w is not None:
            robust_cd0_scatter.append(
                (case.speed_mps, case.cd0_total, case.power_margin_crank_w),
            )

    speeds = [float(row["speed_mps"]) for row in by_speed if row.get("speed_mps") is not None]
    subtitle = _plot_subtitle(spec, target_env)
    plot_paths: dict[str, str] = {}

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ax.plot(
        speeds,
        [int(row["robust_cases"]) for row in by_speed],
        marker="o",
        linewidth=1.5,
    )
    ax.set_xlabel("speed_mps")
    ax.set_ylabel("robust_cases")
    ax.grid(alpha=0.3)
    _safe_plot_title(ax, "Robust cases by speed", subtitle)
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["robust_cases_by_speed"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["robust_cases_by_speed"] = _write_design_space_plot_paths(path.name)

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ax.plot(
        speeds,
        [_safe_float(row["max_power_margin_crank_w"]) for row in by_speed],
        marker="o",
        linewidth=1.5,
    )
    ax.set_xlabel("speed_mps")
    ax.set_ylabel("max_power_margin_crank_w")
    ax.grid(alpha=0.3)
    _safe_plot_title(ax, "Max margin by speed", subtitle)
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["max_margin_by_speed"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["max_margin_by_speed"] = _write_design_space_plot_paths(path.name)

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    _plot_speed_group_envelopes(ax, by_cd0_cases, "speed_mps", "CD0")
    ax.set_xlabel("speed_mps")
    ax.set_ylabel("cd0_total")
    ax.grid(alpha=0.25)
    _safe_plot_title(ax, "Feasible speed range by CD0", subtitle)
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["feasible_speed_range_by_cd0"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["feasible_speed_range_by_cd0"] = _write_design_space_plot_paths(path.name)

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    _plot_speed_group_envelopes(ax, by_ar_cases, "speed_mps", "AR")
    ax.set_xlabel("speed_mps")
    ax.set_ylabel("aspect_ratio")
    ax.grid(alpha=0.25)
    _safe_plot_title(ax, "Feasible speed range by AR", subtitle)
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["feasible_speed_range_by_ar"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["feasible_speed_range_by_ar"] = _write_design_space_plot_paths(path.name)

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    _plot_speed_group_envelopes(ax, by_span_cases, "speed_mps", "Span")
    ax.set_xlabel("speed_mps")
    ax.set_ylabel("span_m")
    ax.grid(alpha=0.25)
    _safe_plot_title(ax, "Feasible speed range by span", subtitle)
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["feasible_speed_range_by_span"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["feasible_speed_range_by_span"] = _write_design_space_plot_paths(path.name)

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ax.plot(
        [_safe_float(row["cl_max_effective"]) for row in by_clmax],
        [int(row["robust_cases"]) for row in by_clmax],
        marker="o",
        linewidth=1.5,
    )
    ax.set_xlabel("cl_max_effective")
    ax.set_ylabel("robust_cases")
    ax.grid(alpha=0.3)
    _safe_plot_title(ax, "Robust cases by CLmax", subtitle)
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["robust_cases_by_clmax"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["robust_cases_by_clmax"] = _write_design_space_plot_paths(path.name)

    robust_count_rows = boundary_tables["robust_count_by_speed_cd0"]
    x_values, y_values, robust_matrix = _pivot_grid(
        robust_count_rows,
        "speed_mps",
        "cd0_total",
        "robust_cases",
        0.0,
    )
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    _plot_heatmap(
        ax,
        x_values,
        y_values,
        robust_matrix,
        "speed_mps",
        "cd0_total",
        "robust_cases",
    )
    ax.set_title("Robust case count heatmap by speed/CD0", loc="left", pad=12)
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["robust_count_heatmap_speed_cd0"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["robust_count_heatmap_speed_cd0"] = _write_design_space_plot_paths(path.name)

    best_margin_rows = boundary_tables["best_margin_by_speed_cd0"]
    x_values, y_values, best_margin_matrix = _pivot_grid(
        best_margin_rows,
        "speed_mps",
        "cd0_total",
        "best_power_margin_crank_w",
        float("nan"),
    )
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    _plot_heatmap(
        ax,
        x_values,
        y_values,
        best_margin_matrix,
        "speed_mps",
        "cd0_total",
        "best_power_margin_crank_w",
    )
    ax.set_title(
        (
            "Raw power-only best margin heatmap by speed/CD0\\n"
            "raw power-only boundary, may include stall-risky cases\n"
            + subtitle
        ),
        loc="left",
        pad=12,
    )
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["raw_best_margin_heatmap_speed_cd0"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["raw_best_margin_heatmap_speed_cd0"] = _write_design_space_plot_paths(path.name)

    stall_rows = boundary_tables["stall_risk_by_speed_clmax"]
    stall_risk_rows: list[dict[str, float | int | None]] = []
    for row in stall_rows:
        caution = int(row.get("caution_cases", 0))
        thin_margin = int(row.get("thin_margin_cases", 0))
        over_clmax = int(row.get("over_clmax_cases", 0))
        healthy = int(row.get("healthy_cases", 0))
        total = caution + thin_margin + over_clmax + healthy
        risk_score = None
        if total > 0:
            risk_score = (1.0 * caution + 2.0 * thin_margin + 4.0 * over_clmax) / total
        stall_risk_rows.append(
            {
                "speed_mps": row.get("speed_mps"),
                "cl_max_effective": row.get("cl_max_effective"),
                "risk_score": risk_score,
            },
        )
    x_values, y_values, risk_matrix = _pivot_grid(
        stall_risk_rows,
        "speed_mps",
        "cl_max_effective",
        "risk_score",
        0.0,
    )
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    _plot_heatmap(
        ax,
        x_values,
        y_values,
        risk_matrix,
        "speed_mps",
        "cl_max_effective",
        "risk score",
    )
    ax.set_title(
        (
            "Stall risk by speed/CLmax\\n"
            "color is a weighted score from over_clmax/thin_margin/caution/healthy\\n"
            + subtitle
        ),
        loc="left",
        pad=12,
    )
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["stall_risk_by_speed_clmax"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["stall_risk_by_speed_clmax"] = _write_design_space_plot_paths(path.name)

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    if robust_cd0_scatter:
        robust_cd0_scatter = sorted(robust_cd0_scatter, key=lambda item: (item[0], item[1]))
        x_scatter = [entry[0] for entry in robust_cd0_scatter]
        y_scatter = [entry[1] for entry in robust_cd0_scatter]
        c_scatter = [entry[2] for entry in robust_cd0_scatter]
        image = ax.scatter(x_scatter, y_scatter, c=c_scatter, cmap="viridis")
        cbar = fig.colorbar(image, ax=ax)
        cbar.set_label("power_margin_crank_w")
    else:
        ax.text(0.5, 0.5, "No robust candidates", ha="center", va="center")
    ax.set_xlabel("speed_mps")
    ax.set_ylabel("cd0_total")
    ax.grid(alpha=0.25)
    _safe_plot_title(ax, "Robust candidates: speed/CD0 (power margin color)", subtitle)
    path = plots_dir / _DESIGN_SPACE_PLOT_FILES["robust_candidates_speed_cd0_scatter"]
    _write_plot(fig, path, spec.plot_dpi, spec.plot_format)
    plt.close(fig)
    plot_paths["robust_candidates_speed_cd0_scatter"] = _write_design_space_plot_paths(path.name)

    return plot_paths


def write_full_results_csv(
    path: Path,
    cases: Sequence[MissionQuickScreenResult],
    filters: MissionDesignSpaceFilters,
) -> None:
    field_names = (
        "speed_mps",
        "span_m",
        "aspect_ratio",
        "cd0_total",
        "cl_max_effective",
        "mass_kg",
        "oswald_e",
        "air_density_kg_m3",
        "eta_prop",
        "eta_trans",
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
        "robust_passed",
    )

    path.parent.mkdir(parents=True, exist_ok=True)
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
                    "mass_kg": f"{case.mass_kg:.6f}",
                    "oswald_e": f"{case.oswald_e:.6f}",
                    "air_density_kg_m3": f"{case.air_density_kg_m3:.6f}",
                    "eta_prop": f"{case.eta_prop:.6f}",
                    "eta_trans": f"{case.eta_trans:.6f}",
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
                    "robust_passed": str(is_robust_case(case, filters)),
                }
            )


def write_envelope_rows(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=tuple(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            clean_row = {}
            for key, value in row.items():
                if isinstance(value, float):
                    clean_row[key] = f"{value:.6f}"
                else:
                    clean_row[key] = "" if value is None else value
            writer.writerow(clean_row)


def _table_rows_from_iterable(
    rows: Sequence[MissionQuickScreenResult],
    title: str,
    filters: MissionDesignSpaceFilters,
    limit: int = 20,
) -> list[str]:
    def _safe_margin(case: MissionQuickScreenResult) -> float:
        return case.power_margin_crank_w if case.power_margin_crank_w is not None else float("-inf")

    headers = [
        "rank",
        "speed_mps",
        "span_m",
        "AR",
        "CD0",
        "CLmax",
        "mass_kg",
        "oswald_e",
        "eta_prop",
        "eta_trans",
        "margin(W)",
        "req_crank_W",
        "pilot_hot_W",
        "cl_req",
        "cl_to_clmax",
        "cl_band",
        "stall_band",
        "power_passed",
        "robust_passed",
        "req_time_min",
    ]

    if not rows:
        return [f"### {title}", "", "No cases."]

    sort_keys = {
        "Robust candidates sorted by speed": lambda case: (
            case.speed_mps,
            case.cd0_total,
            -_safe_margin(case),
        ),
        "Robust candidates grouped by CD0": lambda case: (
            case.cd0_total,
            case.speed_mps,
            -_safe_margin(case),
        ),
        "Conservative CLmax robust candidates": lambda case: (
            case.speed_mps,
            case.cd0_total,
            -_safe_margin(case),
        ),
        "High-speed robust candidates": lambda case: (
            case.speed_mps,
            case.cd0_total,
            -_safe_margin(case),
        ),
        "Low-risk candidates": lambda case: (
            -_safe_margin(case),
            case.speed_mps,
            case.cd0_total,
        ),
        "Boundary / risky cases, not recommended as primary design": lambda case: (
            abs(_safe_margin(case)),
            case.speed_mps,
            case.cd0_total,
        ),
    }.get(title, lambda case: (case.speed_mps, case.cd0_total, -_safe_margin(case)))

    ordered_rows = sorted(rows, key=sort_keys)

    lines = [
        f"### {title}",
        "",
        "| " + " | ".join(headers) + " |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|:--:|:--:|---:|",
    ]
    for index, case in enumerate(ordered_rows[:limit], start=1):
        margin_text = (
            "n/a" if case.power_margin_crank_w is None else f"{case.power_margin_crank_w:.2f}"
        )
        required_crank_text = (
            "n/a" if case.required_crank_power_w is None else f"{case.required_crank_power_w:.2f}"
        )
        pilot_hot_text = (
            "n/a" if case.pilot_power_hot_w is None else f"{case.pilot_power_hot_w:.2f}"
        )
        lines.append(
            "| " + " | ".join(
                (
                    f"{index}",
                    f"{case.speed_mps:.2f}",
                    f"{case.span_m:.1f}",
                    f"{case.aspect_ratio:.1f}",
                    f"{case.cd0_total:.3f}",
                    f"{case.cl_max_effective:.2f}",
                    f"{case.mass_kg:.3f}",
                    f"{case.oswald_e:.3f}",
                    f"{case.eta_prop:.3f}",
                    f"{case.eta_trans:.3f}",
                    margin_text,
                    required_crank_text,
                    pilot_hot_text,
                    f"{case.cl_required:.3f}",
                    f"{case.cl_to_clmax_ratio:.3f}",
                    case.cl_band,
                    case.stall_band,
                    f"{case.power_passed}",
                    f"{is_robust_case(case, filters)}",
                    f"{case.required_time_min:.2f}",
                )
            ) + " |",
        )
    return lines


def write_design_space_report(
    path: Path,
    *,
    spec: MissionDesignSpaceSpec,
    results: Sequence[MissionQuickScreenResult],
    summary: dict[str, int | float],
    envelopes: Sequence[dict[str, Any]],
    boundary_tables: dict[str, list[dict[str, Any]]],
    test_env: RiderPowerEnvironment,
    target_env: RiderPowerEnvironment,
    heat_derate: float,
    filters: MissionDesignSpaceFilters,
    plot_paths: dict[str, str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    robust_cases = [case for case in results if is_robust_case(case, filters)]

    by_speed = [row for row in envelopes if row.get("group") == "by_speed"]
    by_cd0 = [row for row in envelopes if row.get("group") == "by_cd0"]
    by_ar = [row for row in envelopes if row.get("group") == "by_aspect_ratio"]
    by_span = [row for row in envelopes if row.get("group") == "by_span"]
    by_clmax = [row for row in envelopes if row.get("group") == "by_clmax"]

    lines = ["# Mission Design Space Explorer Report", ""]
    lines += [
        "## Inputs",
        "",
        f"- mission target range: {spec.target_range_km:.3f} km",
        f"- rider power csv: `{spec.rider_power_csv}`",
        f"- rider metadata: `{spec.rider_metadata_yaml}`",
        f"- test environment: {test_env.temperature_c:.2f}°C / {test_env.relative_humidity_percent:.1f}%RH",
        f"- target environment: {target_env.temperature_c:.2f}°C / {target_env.relative_humidity_percent:.1f}%RH",
        f"- heat derate factor: {heat_derate:.12f}",
        f"- speeds: {list(spec.speeds_mps)}",
        f"- spans: {list(spec.spans_m)}",
        f"- AR: {list(spec.aspect_ratios)}",
        f"- CD0: {list(spec.cd0_totals)}",
        f"- CLmax-effective: {list(spec.cl_max_effectives)}",
        f"- mass: {list(spec.mass_kg)}",
        f"- oswald_e: {list(spec.oswald_e)}",
        f"- rho: {list(spec.air_density_kg_m3)}",
        f"- eta_prop: {list(spec.eta_prop)}",
        f"- eta_trans: {list(spec.eta_trans)}",
        "",
        "## Case Counts",
        "",
        f"- total cases: {summary['total_cases']}",
        f"- power passed cases: {summary['power_passed_cases']}",
        f"- robust cases: {summary['robust_cases']}",
        f"- margin >= min threshold cases: {summary['margin_ge_min_cases']}",
        f"- margin >= robust threshold cases: {summary['margin_ge_robust_cases']}",
        "",
        "robust_passed definition:",
        (
            "- power_passed == True"
            f", power_margin_crank_w >= {filters.min_power_margin_crank_w:.3f}"
        ),
        f"- cl_band in {list(filters.allowed_cl_bands)}",
        f"- stall_band in {list(filters.allowed_stall_bands)}",
        f"- cl_to_clmax_ratio <= {filters.max_cl_to_clmax_ratio:.3f}",
        "",
        "- CLmax is used for stall-related screening only (stall band / stall margin),"
        " and does not change air power calculation in quick-screen.",
        "",
    ]
    if plot_paths:
        lines.extend(
            [
                "## Visual Summary",
                "",
                "### 1) Robust cases by speed",
                f"![robust_cases_by_speed]({plot_paths['robust_cases_by_speed']})",
                "Robust counts across speed reveal which speed band has larger design flexibility.",
                "",
                "### 2) Max margin by speed",
                f"![max_margin_by_speed]({plot_paths['max_margin_by_speed']})",
                "Power margin envelope by speed helps compare energy feasibility margin.",
                "",
                "### 3) Feasible speed ranges by CD0",
                f"![feasible_speed_range_by_cd0]({plot_paths['feasible_speed_range_by_cd0']})",
                "Each CD0 slice shows where robust operation is available.",
                "",
                "### 4) Feasible speed ranges by AR",
                f"![feasible_speed_range_by_ar]({plot_paths['feasible_speed_range_by_ar']})",
                "Each AR slice shows speed coverage trend.",
                "",
                "### 5) Feasible speed ranges by span",
                f"![feasible_speed_range_by_span]({plot_paths['feasible_speed_range_by_span']})",
                "Each span slice shows speed coverage trend.",
                "",
                "### 6) Robust cases by CLmax",
                f"![robust_cases_by_clmax]({plot_paths['robust_cases_by_clmax']})",
                "Higher CLmax generally broadens stall-capable but does not imply lower heat-risk.",
                "",
                "### 7) Robust case count heatmap (speed, CD0)",
                f"![robust_count_heatmap_speed_cd0]({plot_paths['robust_count_heatmap_speed_cd0']})",
                "Count intensity maps where robust combos still exist.",
                "",
                "### 8) Raw best margin heatmap (speed, CD0)",
                f"![raw_best_margin_heatmap_speed_cd0]({plot_paths['raw_best_margin_heatmap_speed_cd0']})",
                "Raw power-only boundary, may include stall-risky cases.",
                "",
                "### 9) Stall risk heatmap by speed, CLmax",
                f"![stall_risk_by_speed_clmax]({plot_paths['stall_risk_by_speed_clmax']})",
                "Colored by weighted stall risk from over_clmax / thin_margin / caution / healthy counts.",
                "",
                "### 10) Robust candidates scatter",
                f"![robust_candidates_speed_cd0_scatter]({plot_paths['robust_candidates_speed_cd0_scatter']})",
                "Each point is robust candidate; color shows power margin.",
                "",
            ]
        )

    lines.extend(
        [
            "## Feasible Envelopes",
            "",
            "### By speed",
        ]
    )

    if by_speed:
        lines.extend(
            [
                "| speed_mps | total_cases | robust_cases | max_margin(W) | min_CD0_robust | max_CD0_robust | min_time(min) | max_time(min) |",
                "|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in by_speed:
            lines.append(
                f"| {row['speed_mps']:.3f} | {row['total_cases']} | {row['robust_cases']} | "
                f"{_fmt_or_blank(row['max_power_margin_crank_w'], '.2f')} | "
                f"{_fmt_or_blank(row['min_cd0_total_among_robust'], '.3f')} | "
                f"{_fmt_or_blank(row['max_cd0_total_among_robust'], '.3f')} | "
                f"{_fmt_or_blank(row['min_required_time_min'], '.2f')} | "
                f"{_fmt_or_blank(row['max_required_time_min'], '.2f')} |"
            )
    else:
        lines.append("No speed groups.")

    lines += [
        "",
        "### Feasible speed ranges by CD0",
    ]
    if by_cd0:
        lines.extend(
            [
                "| CD0 | total_cases | robust_cases | feasible_speed_min | feasible_speed_max | best_margin(W) |",
                "|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in by_cd0:
            lines.append(
                f"| {row['cd0_total']:.3f} | {row['total_cases']} | {row['robust_cases']} | "
                f"{_fmt_or_blank(row['feasible_speed_min'], '.2f')} | "
                f"{_fmt_or_blank(row['feasible_speed_max'], '.2f')} | "
                f"{_fmt_or_blank(row['max_power_margin_crank_w'], '.2f')} |"
            )
    else:
        lines.append("No CD0 groups.")

    lines += [
        "",
        "### Feasible speed ranges by AR",
        "",
    ]
    if by_ar:
        lines.extend(
            [
                "| AR | total_cases | robust_cases | feasible_speed_min | feasible_speed_max | best_margin(W) |",
                "|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in by_ar:
            lines.append(
                f"| {row['aspect_ratio']:.1f} | {row['total_cases']} | {row['robust_cases']} | "
                f"{_fmt_or_blank(row['feasible_speed_min'], '.2f')} | "
                f"{_fmt_or_blank(row['feasible_speed_max'], '.2f')} | "
                f"{_fmt_or_blank(row['max_power_margin_crank_w'], '.2f')} |"
            )
    else:
        lines.append("No AR groups.")

    lines += [
        "",
        "### Feasible speed ranges by span",
        "",
    ]
    if by_span:
        lines.extend(
            [
                "| span_m | total_cases | robust_cases | feasible_speed_min | feasible_speed_max | best_margin(W) |",
                "|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in by_span:
            lines.append(
                f"| {row['span_m']:.1f} | {row['total_cases']} | {row['robust_cases']} | "
                f"{_fmt_or_blank(row['feasible_speed_min'], '.2f')} | "
                f"{_fmt_or_blank(row['feasible_speed_max'], '.2f')} | "
                f"{_fmt_or_blank(row['max_power_margin_crank_w'], '.2f')} |"
            )
    else:
        lines.append("No span groups.")

    lines += [
        "",
        "### Robust count by CLmax",
        "",
    ]
    if by_clmax:
        lines.extend(
            [
                "| CLmax | total_cases | robust_cases | over_clmax | thin_margin | healthy | caution |",
                "|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in by_clmax:
            lines.append(
                f"| {row['cl_max_effective']:.2f} | {row['total_cases']} | {row['robust_cases']} | "
                f"{row['over_clmax_cases']} | {row['thin_margin_cases']} | {row['healthy_cases']} | {row['caution_cases']} |"
            )
    else:
        lines.append("No CLmax groups.")

    lines += [
        "",
        "## Boundary Tables",
        "",
        "### best margin by speed/CD0",
        "| speed | CD0 | best_margin(W) | span | AR | clmax |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in boundary_tables["best_margin_by_speed_cd0"]:
        lines.append(
            f"| {row['speed_mps']:.2f} | {row['cd0_total']:.3f} | "
            f"{_fmt_or_blank(row['best_power_margin_crank_w'], '.2f')} | "
            f"{_fmt_or_blank(row['span_m'], '.1f')} | "
            f"{_fmt_or_blank(row['aspect_ratio'], '.1f')} | "
            f"{_fmt_or_blank(row['cl_max_effective'], '.2f')} |"
        )
    lines += [
        "",
        "### robust count by speed/CD0",
        "| speed | CD0 | robust_count |",
        "|---:|---:|---:|",
    ]
    for row in boundary_tables["robust_count_by_speed_cd0"]:
        lines.append(
            f"| {row['speed_mps']:.2f} | {row['cd0_total']:.3f} | {row['robust_cases']} |"
        )
    lines += [
        "",
        "### stall risk by speed/CLmax",
        "| speed | CLmax | healthy | caution | thin_margin | over_clmax |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in boundary_tables["stall_risk_by_speed_clmax"]:
        lines.append(
            f"| {row['speed_mps']:.2f} | {row['cl_max_effective']:.2f} | "
            f"{row['healthy_cases']} | {row['caution_cases']} | {row['thin_margin_cases']} | {row['over_clmax_cases']} |"
        )

    lines += [
        "",
        "## Design Interpretation Guide",
        "",
        "- 這是一份 design-space report，提供可行區間、邊界與風險分布，不輸出唯一最佳解。",
        "- observed robust speed envelope + CD0 sensitivity observation 可直接作為後續 AVL/XFOIL/結構/推進器再分析的邊界條件。",
        "- 若某速度僅在較低 CD0 才通過，代表此速度段對 CD0 敏感。",
        "- 若穩健候選僅在高 CLmax 下成立，代表失速前提偏樂觀。",
        "- 正值但接近零的功率裕度只代表邊界點，不建議作為主設計。",
        "- CD0 可行區間與 stall band 共同決定 risk envelope；CLmax 只影響失速條件，不改變空氣動力功率計算。",
        "",
        "## Candidate Tables",
        "",
    ]

    robust_sorted_speed = sorted(
        [case for case in robust_cases if case.power_margin_crank_w is not None],
        key=lambda case: case.speed_mps,
    )
    robust_group_by_cd0 = sorted(
        robust_cases,
        key=lambda case: (case.cd0_total, case.speed_mps),
    )
    low_risk = [
        case
        for case in results
        if is_robust_case(case, filters)
        and case.power_margin_crank_w is not None
        and case.power_margin_crank_w >= filters.robust_power_margin_crank_w
        and case.stall_band == "healthy"
        and case.cl_band == "normal"
    ]
    conservative_clmax = [
        case
        for case in robust_cases
        if case.cl_max_effective <= 1.45
        and case.cl_band == "normal"
        and case.stall_band not in {"thin_margin", "over_clmax"}
    ]
    high_speed_robust = [
        case
        for case in robust_cases
        if case.speed_mps >= 6.5
        and case.stall_band not in {"thin_margin", "over_clmax"}
    ]
    low_risk = sorted(
        low_risk,
        key=lambda case: (
            -case.power_margin_crank_w if case.power_margin_crank_w is not None else float("-inf"),
            case.speed_mps,
            case.cd0_total,
        ),
    )
    boundary_candidates = {
        case
        for case in results
        if (case.power_passed and not is_robust_case(case, filters))
        or (
            case.power_margin_crank_w is not None
            and abs(case.power_margin_crank_w) <= filters.min_power_margin_crank_w
        )
    }

    for section in [
        ("Robust candidates sorted by speed", robust_sorted_speed),
        ("Robust candidates grouped by CD0", robust_group_by_cd0),
        ("Conservative CLmax robust candidates", conservative_clmax),
        ("High-speed robust candidates", high_speed_robust),
        ("Low-risk candidates", low_risk),
        ("Boundary / risky cases, not recommended as primary design", list(boundary_candidates)),
    ]:
        lines.extend(
            _table_rows_from_iterable(
                section[1],
                section[0],
                filters,
                limit=spec.max_candidate_rows_in_report,
            ),
        )
        lines.append("")

    lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def sort_design_space_cases(
    cases: Sequence[MissionQuickScreenResult],
) -> list[MissionQuickScreenResult]:
    return sorted(
        cases,
        key=lambda case: (
            case.speed_mps,
            case.span_m,
            case.aspect_ratio,
            case.cd0_total,
            case.cl_max_effective,
            case.mass_kg,
        ),
    )
