from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable

from .schema import (
    BaselineConvergenceGate,
    ConvergenceGateCheck,
    ConvergenceGateSection,
    GateStatusType,
    MeshHandoff,
    OverallConvergenceGate,
)


DEFAULT_MIN_ITERATIONS = 20
DEFAULT_TAIL_WINDOW = 10
DEFAULT_RESIDUAL_STARTUP_SKIP = 5
DEFAULT_RESIDUAL_MEDIAN_DROP = 0.5
DEFAULT_COEFFICIENT_REL_RANGE_PASS = 0.02
DEFAULT_COEFFICIENT_REL_RANGE_WARN = 0.05
DEFAULT_COEFFICIENT_ABS_TOL = 5.0e-4
DEFAULT_COEFFICIENT_SCALE_FLOOR = 1.0e-3


def _overall_status(*statuses: GateStatusType) -> GateStatusType:
    if any(status == "fail" for status in statuses):
        return "fail"
    if any(status == "warn" for status in statuses):
        return "warn"
    return "pass"


def _confidence_for_status(status: GateStatusType) -> str:
    return {"pass": "high", "warn": "medium", "fail": "low"}[status]


def _collect_warnings(checks: dict[str, ConvergenceGateCheck]) -> list[str]:
    warnings: list[str] = []
    for name, check in checks.items():
        warnings.extend(f"{name}:{warning}" for warning in check.warnings)
    return warnings


def _collect_notes(checks: dict[str, ConvergenceGateCheck]) -> list[str]:
    notes: list[str] = []
    for name, check in checks.items():
        notes.extend(f"{name}:{note}" for note in check.notes)
    return notes


def _check(
    status: GateStatusType,
    *,
    observed: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    notes: list[str] | None = None,
) -> ConvergenceGateCheck:
    return ConvergenceGateCheck(
        status=status,
        observed=observed or {},
        expected=expected or {},
        warnings=warnings or [],
        notes=notes or [],
    )


def _resolve_path(path_value: Path | str, source_root: Path | None) -> Path:
    path = Path(path_value)
    if path.is_absolute() or source_root is None:
        return path
    return source_root / path


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"missing_file={path}"
    except json.JSONDecodeError as exc:
        return None, f"json_decode_error={path}:{exc.msg}"
    if not isinstance(payload, dict):
        return None, f"json_root_not_object={path}"
    return payload, None


def _valid_bounds(bounds: Any) -> bool:
    if not isinstance(bounds, dict):
        return False
    values = []
    for key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max"):
        value = bounds.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return False
        values.append(float(value))
    return values[0] < values[1] and values[2] < values[3] and values[4] < values[5]


def _farfield_contains_body(body_bounds: dict[str, Any], farfield_bounds: dict[str, Any]) -> bool:
    return (
        float(farfield_bounds["x_min"]) < float(body_bounds["x_min"])
        and float(farfield_bounds["x_max"]) > float(body_bounds["x_max"])
        and float(farfield_bounds["y_min"]) < float(body_bounds["y_min"])
        and float(farfield_bounds["y_max"]) > float(body_bounds["y_max"])
        and float(farfield_bounds["z_min"]) < float(body_bounds["z_min"])
        and float(farfield_bounds["z_max"]) > float(body_bounds["z_max"])
    )


def _group_exists(group: Any) -> bool:
    return isinstance(group, dict) and group.get("exists") is True and int(group.get("entity_count", 0) or 0) > 0


def evaluate_mesh_gate(
    mesh_handoff: MeshHandoff | dict[str, Any],
    *,
    source_root: Path | None = None,
) -> ConvergenceGateSection:
    try:
        handoff = MeshHandoff.model_validate(mesh_handoff)
    except Exception as exc:
        checks = {
            "mesh_handoff_complete": _check(
                "fail",
                observed={"validation_error": str(exc)},
                expected={"contract": "mesh_handoff.v1", "route_stage": "baseline"},
                warnings=["mesh_handoff_validation_failed"],
            )
        }
        return ConvergenceGateSection(
            status="fail",
            confidence="low",
            checks=checks,
            warnings=_collect_warnings(checks),
            notes=["Mesh gate could not validate mesh_handoff.v1."],
        )

    mesh_path = _resolve_path(handoff.artifacts.mesh, source_root)
    metadata_path = _resolve_path(handoff.artifacts.mesh_metadata, source_root)
    marker_summary_path = _resolve_path(handoff.artifacts.marker_summary, source_root)
    metadata_payload, metadata_error = _load_json(metadata_path)
    marker_payload, marker_error = _load_json(marker_summary_path)

    required_fields_present = all(
        getattr(handoff, field_name, None) is not None
        for field_name in (
            "contract",
            "route_stage",
            "units",
            "body_bounds",
            "farfield_bounds",
            "marker_summary",
            "physical_groups",
            "mesh_stats",
        )
    )
    handoff_status: GateStatusType = "pass"
    handoff_warnings: list[str] = []
    if handoff.contract != "mesh_handoff.v1" or handoff.route_stage != "baseline" or not required_fields_present:
        handoff_status = "fail"
        if handoff.route_stage != "baseline":
            handoff_warnings.append("route_stage_must_be_baseline")
        if not required_fields_present:
            handoff_warnings.append("mesh_handoff_required_fields_missing")

    artifact_warnings = [warning for warning in (metadata_error, marker_error) if warning is not None]
    if not mesh_path.exists():
        artifact_warnings.append(f"missing_file={mesh_path}")
    artifacts_status: GateStatusType = "pass" if not artifact_warnings else "fail"

    body_bounds = handoff.body_bounds.model_dump(mode="json")
    farfield_bounds = handoff.farfield_bounds.model_dump(mode="json")
    bounds_warnings: list[str] = []
    bounds_status: GateStatusType = "pass"
    if handoff.units not in {"m", "mm"}:
        bounds_status = "fail"
        bounds_warnings.append("units_missing_or_unsupported")
    if not _valid_bounds(body_bounds) or not _valid_bounds(farfield_bounds):
        bounds_status = "fail"
        bounds_warnings.append("bounds_invalid")
    elif not _farfield_contains_body(body_bounds, farfield_bounds):
        bounds_status = "fail"
        bounds_warnings.append("farfield_does_not_contain_body")

    required_marker_status = {
        "aircraft": bool(handoff.marker_summary.get("aircraft", {}).get("exists")),
        "farfield": bool(handoff.marker_summary.get("farfield", {}).get("exists")),
    }
    required_group_status = {
        "aircraft": _group_exists(handoff.physical_groups.get("aircraft")),
        "farfield": _group_exists(handoff.physical_groups.get("farfield")),
        "fluid": _group_exists(handoff.physical_groups.get("fluid")),
    }
    marker_group_status: GateStatusType = (
        "pass" if all(required_marker_status.values()) and all(required_group_status.values()) else "fail"
    )

    mesh_stats = handoff.mesh_stats
    element_status: GateStatusType = "pass"
    element_warnings: list[str] = []
    if int(mesh_stats.get("mesh_dim", 0) or 0) != 3:
        element_status = "fail"
        element_warnings.append("mesh_dim_must_be_3")
    for key in ("node_count", "element_count", "volume_element_count"):
        value = mesh_stats.get(key)
        if not isinstance(value, int) or value <= 0:
            element_status = "fail"
            element_warnings.append(f"{key}_must_be_positive")

    checks = {
        "mesh_handoff_complete": _check(
            handoff_status,
            observed={
                "contract": handoff.contract,
                "route_stage": handoff.route_stage,
                "mesh_format": handoff.mesh_format,
                "required_fields_present": required_fields_present,
            },
            expected={"contract": "mesh_handoff.v1", "route_stage": "baseline", "mesh_format": "msh"},
            warnings=handoff_warnings,
        ),
        "artifact_files": _check(
            artifacts_status,
            observed={
                "mesh_exists": mesh_path.exists(),
                "mesh_metadata_exists": metadata_path.exists(),
                "mesh_metadata_parse_ok": metadata_payload is not None,
                "marker_summary_exists": marker_summary_path.exists(),
                "marker_summary_parse_ok": marker_payload is not None,
            },
            expected={"mesh_exists": True, "mesh_metadata_parse_ok": True, "marker_summary_parse_ok": True},
            warnings=artifact_warnings,
        ),
        "units_and_bounds": _check(
            bounds_status,
            observed={
                "units": handoff.units,
                "body_bounds_valid": _valid_bounds(body_bounds),
                "farfield_bounds_valid": _valid_bounds(farfield_bounds),
                "farfield_contains_body": _farfield_contains_body(body_bounds, farfield_bounds)
                if _valid_bounds(body_bounds) and _valid_bounds(farfield_bounds)
                else False,
            },
            expected={"units": ["m", "mm"], "body_bounds_valid": True, "farfield_contains_body": True},
            warnings=bounds_warnings,
        ),
        "required_markers_and_groups": _check(
            marker_group_status,
            observed={
                "markers": required_marker_status,
                "physical_groups": required_group_status,
            },
            expected={
                "markers": {"aircraft": True, "farfield": True},
                "physical_groups": {"aircraft": True, "farfield": True, "fluid": True},
            },
        ),
        "element_counts": _check(
            element_status,
            observed={
                "mesh_dim": mesh_stats.get("mesh_dim"),
                "node_count": mesh_stats.get("node_count"),
                "element_count": mesh_stats.get("element_count"),
                "volume_element_count": mesh_stats.get("volume_element_count"),
            },
            expected={
                "mesh_dim": 3,
                "node_count": "> 0",
                "element_count": "> 0",
                "volume_element_count": "> 0",
            },
            warnings=element_warnings,
        ),
    }
    status = _overall_status(*(check.status for check in checks.values()))
    return ConvergenceGateSection(
        status=status,
        confidence=_confidence_for_status(status),
        checks=checks,
        warnings=_collect_warnings(checks),
        notes=[
            "Mesh gate uses existing mesh_handoff.v1 plus mesh metadata artifacts only.",
            *_collect_notes(checks),
        ],
    )


def _normalize_header(value: str) -> str:
    return value.strip().strip('"').strip()


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def _read_history_rows(history_path: Path) -> list[dict[str, str]]:
    if history_path.suffix.lower() == ".csv":
        with history_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        if len(rows) < 2:
            raise ValueError(f"history file has insufficient rows: {history_path}")
        header = [_normalize_header(value) for value in rows[0]]
        data_rows: list[dict[str, str]] = []
        for raw_values in rows[1:]:
            if not raw_values or len(raw_values) != len(header):
                continue
            data_rows.append({key: value.strip() for key, value in zip(header, raw_values)})
        if not data_rows:
            raise ValueError(f"history file has no parseable data rows: {history_path}")
        return data_rows

    lines = [
        line.strip()
        for line in history_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    if len(lines) < 2:
        raise ValueError(f"history file has insufficient data: {history_path}")

    header = [_normalize_header(value) for value in lines[0].replace("\t", ",").split(",")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        values = [value.strip() for value in line.replace("\t", ",").split(",")]
        if len(values) != len(header):
            continue
        rows.append({key: value for key, value in zip(header, values)})
    if not rows:
        raise ValueError(f"history file has no parseable data rows: {history_path}")
    return rows


def _numeric_series(rows: list[dict[str, str]], column: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        parsed = _parse_float(row.get(column))
        if parsed is not None:
            values.append(parsed)
    return values


def _tail_metrics(series: list[float], tail_window: int) -> dict[str, float]:
    tail = series[-tail_window:]
    tail_mean = sum(tail) / len(tail)
    tail_range = max(tail) - min(tail)
    tail_delta = tail[-1] - tail[0]
    scale = max(abs(tail_mean), abs(tail[-1]), DEFAULT_COEFFICIENT_SCALE_FLOOR)
    return {
        "tail_mean": tail_mean,
        "tail_range": tail_range,
        "tail_delta": tail_delta,
        "tail_relative_range": tail_range / scale,
        "scale": scale,
    }


def _residual_columns(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    columns = list(rows[0].keys())
    return [
        name
        for name in columns
        if name.lower().startswith("rms[") or name.lower().startswith("res_") or name.lower().startswith("res[")
    ]


def _residual_windows(series: list[float], tail_window: int) -> tuple[list[float], list[float], int]:
    if len(series) < 2:
        return series, series, 0

    max_skip = max(len(series) - 2, 0)
    startup_skip = min(DEFAULT_RESIDUAL_STARTUP_SKIP, max_skip)
    analysis_series = series[startup_skip:]
    if len(analysis_series) < 2:
        startup_skip = 0
        analysis_series = series

    tail_size = min(tail_window, len(analysis_series) - 1)
    if tail_size <= 0:
        return analysis_series[:1], analysis_series, startup_skip
    baseline_size = len(analysis_series) - tail_size
    baseline = analysis_series[:baseline_size]
    tail = analysis_series[-tail_size:]
    return baseline, tail, startup_skip


def _cm_column(final_row: dict[str, str]) -> str | None:
    return next(
        (name for name in ("CMy", "CMY", "CMz", "CMZ", "CMx", "CMX", "CM") if name in final_row),
        None,
    )


def evaluate_iterative_gate(
    history_path: Path | str,
    *,
    min_iterations: int = DEFAULT_MIN_ITERATIONS,
    tail_window: int = DEFAULT_TAIL_WINDOW,
) -> ConvergenceGateSection:
    path = Path(history_path)
    try:
        rows = _read_history_rows(path)
    except Exception as exc:
        checks = {
            "history_rows": _check(
                "fail",
                observed={"history_path": str(path)},
                expected={"history_file_exists": True, "parseable_rows": True},
                warnings=["history_parse_failed"],
                notes=[str(exc)],
            )
        }
        return ConvergenceGateSection(
            status="fail",
            confidence="low",
            checks=checks,
            warnings=_collect_warnings(checks),
            notes=["Iterative gate could not parse history output."],
        )

    final_row = rows[-1]
    final_iteration = next(
        (
            _parse_int(final_row.get(name))
            for name in ("Inner_Iter", "ITER", "Outer_Iter", "Time_Iter")
            if name in final_row
        ),
        None,
    )
    history_status: GateStatusType = "pass"
    history_check = _check(
        history_status,
        observed={"history_path": str(path), "row_count": len(rows), "columns": list(rows[0].keys())},
        expected={"history_file_exists": True, "parseable_rows": True},
    )

    iteration_status: GateStatusType = "pass"
    iteration_warnings: list[str] = []
    if len(rows) < tail_window:
        iteration_status = "fail"
        iteration_warnings.append("row_count_below_tail_window")
    elif len(rows) < min_iterations:
        iteration_status = "warn"
        iteration_warnings.append("row_count_below_min_iterations")
    iteration_check = _check(
        iteration_status,
        observed={"row_count": len(rows), "final_iteration": final_iteration},
        expected={"minimum_iterations": min_iterations, "tail_window": tail_window},
        warnings=iteration_warnings,
    )

    residual_columns = _residual_columns(rows)
    residual_status: GateStatusType
    residual_warnings: list[str] = []
    residual_observed: dict[str, Any] = {"columns": residual_columns}
    if not residual_columns:
        residual_status = "fail"
        residual_warnings.append("no_residual_columns_found")
    else:
        improvement_by_column = {}
        baseline_median_by_column = {}
        tail_median_by_column = {}
        startup_skip = 0
        for column in residual_columns:
            series = _numeric_series(rows, column)
            if len(series) < 2:
                continue
            baseline_window, tail_window_values, startup_skip = _residual_windows(series, tail_window)
            baseline_median = statistics.median(baseline_window)
            tail_median = statistics.median(tail_window_values)
            baseline_median_by_column[column] = baseline_median
            tail_median_by_column[column] = tail_median
            improvement_by_column[column] = baseline_median - tail_median
        residual_observed["improvement_by_column"] = improvement_by_column
        residual_observed["improved_columns"] = [name for name, drop in improvement_by_column.items() if drop > 0.0]
        residual_observed["startup_skip"] = startup_skip
        residual_observed["baseline_median_by_column"] = baseline_median_by_column
        residual_observed["tail_median_by_column"] = tail_median_by_column
        residual_observed["median_log_drop"] = (
            statistics.median(improvement_by_column.values()) if improvement_by_column else None
        )
        if improvement_by_column and residual_observed["median_log_drop"] >= DEFAULT_RESIDUAL_MEDIAN_DROP:
            residual_status = "pass"
        else:
            residual_status = "warn"
            residual_warnings.append("residual_drop_below_threshold")
    residual_check = _check(
        residual_status,
        observed=residual_observed,
        expected={"minimum_median_log_drop": DEFAULT_RESIDUAL_MEDIAN_DROP},
        warnings=residual_warnings,
        notes=[
            "Residual columns are treated as log10 RMS values, so lower is better.",
            "Residual trend ignores the startup transient rows before comparing early-vs-tail medians.",
        ],
    )

    coefficient_statuses: list[GateStatusType] = []
    coefficient_observed: dict[str, Any] = {"tail_window": tail_window}
    coefficient_warnings: list[str] = []
    cm_column = _cm_column(final_row)
    coefficient_columns = {"cl": "CL", "cd": "CD", "cm": cm_column}
    for key, column in coefficient_columns.items():
        if column is None:
            coefficient_statuses.append("fail")
            coefficient_warnings.append(f"missing_column={key}")
            coefficient_observed[key] = {"status": "fail"}
            continue
        series = _numeric_series(rows, column)
        if len(series) < tail_window:
            coefficient_statuses.append("fail")
            coefficient_warnings.append(f"insufficient_points={key}")
            coefficient_observed[key] = {"status": "fail", "count": len(series)}
            continue
        metrics = _tail_metrics(series, tail_window)
        pass_delta_limit = max(DEFAULT_COEFFICIENT_ABS_TOL, DEFAULT_COEFFICIENT_REL_RANGE_PASS * metrics["scale"])
        warn_delta_limit = max(DEFAULT_COEFFICIENT_ABS_TOL * 2.0, DEFAULT_COEFFICIENT_REL_RANGE_WARN * metrics["scale"])
        abs_tail_delta = abs(metrics["tail_delta"])
        if (
            metrics["tail_relative_range"] <= DEFAULT_COEFFICIENT_REL_RANGE_PASS
            and abs_tail_delta <= pass_delta_limit
        ):
            status = "pass"
        elif (
            metrics["tail_relative_range"] <= DEFAULT_COEFFICIENT_REL_RANGE_WARN
            and abs_tail_delta <= warn_delta_limit
        ):
            status = "warn"
        else:
            status = "fail"
            coefficient_warnings.append(f"{key}_tail_still_drifting")
        coefficient_statuses.append(status)
        coefficient_observed[key] = {
            "status": status,
            **metrics,
            "pass_relative_range_limit": DEFAULT_COEFFICIENT_REL_RANGE_PASS,
            "warn_relative_range_limit": DEFAULT_COEFFICIENT_REL_RANGE_WARN,
            "pass_delta_limit": pass_delta_limit,
            "warn_delta_limit": warn_delta_limit,
        }

    coefficient_check = _check(
        _overall_status(*coefficient_statuses),
        observed=coefficient_observed,
        expected={
            "tail_window": tail_window,
            "pass_relative_range_limit": DEFAULT_COEFFICIENT_REL_RANGE_PASS,
            "warn_relative_range_limit": DEFAULT_COEFFICIENT_REL_RANGE_WARN,
            "absolute_tolerance": DEFAULT_COEFFICIENT_ABS_TOL,
        },
        warnings=coefficient_warnings,
    )

    checks = {
        "history_rows": history_check,
        "iteration_budget": iteration_check,
        "residual_trend": residual_check,
        "coefficient_stability": coefficient_check,
    }
    status = _overall_status(*(check.status for check in checks.values()))
    return ConvergenceGateSection(
        status=status,
        confidence=_confidence_for_status(status),
        checks=checks,
        warnings=_collect_warnings(checks),
        notes=[
            "Iterative gate reads history.csv directly and does not infer extra solver state.",
            *_collect_notes(checks),
        ],
    )


def build_overall_convergence_gate(
    *,
    mesh_gate_status: GateStatusType,
    iterative_gate_status: GateStatusType,
    reference_gate_status: GateStatusType,
    force_surface_gate_status: GateStatusType,
) -> OverallConvergenceGate:
    checks = {
        "mesh_gate": _check(
            mesh_gate_status,
            observed={"status": mesh_gate_status},
            expected={"status": "pass"},
        ),
        "iterative_gate": _check(
            iterative_gate_status,
            observed={"status": iterative_gate_status},
            expected={"status": "pass"},
        ),
        "reference_gate": _check(
            reference_gate_status,
            observed={"status": reference_gate_status},
            expected={"status": "pass"},
        ),
        "force_surface_gate": _check(
            force_surface_gate_status,
            observed={"status": force_surface_gate_status},
            expected={"status": "pass"},
        ),
    }
    status = _overall_status(
        mesh_gate_status,
        iterative_gate_status,
        reference_gate_status,
        force_surface_gate_status,
    )
    comparability_level = {
        "pass": "preliminary_compare",
        "warn": "run_only",
        "fail": "not_comparable",
    }[status]
    notes = {
        "pass": ["Baseline run passed mesh, iterative, and provenance comparability gates."],
        "warn": ["Baseline run completed, but warned gates mean it should only be treated as runnable."],
        "fail": ["At least one critical gate failed, so this baseline run should not be compared."],
    }[status]
    warnings = [f"{name}={check.status}" for name, check in checks.items() if check.status != "pass"]
    return OverallConvergenceGate(
        status=status,
        confidence=_confidence_for_status(status),
        comparability_level=comparability_level,
        checks=checks,
        warnings=warnings,
        notes=notes,
    )


def evaluate_baseline_convergence_gate(
    mesh_handoff: MeshHandoff | dict[str, Any],
    *,
    history_path: Path | str,
    provenance_gates: Any,
    source_root: Path | None = None,
    min_iterations: int = DEFAULT_MIN_ITERATIONS,
    tail_window: int = DEFAULT_TAIL_WINDOW,
) -> BaselineConvergenceGate:
    mesh_gate = evaluate_mesh_gate(mesh_handoff, source_root=source_root)
    iterative_gate = evaluate_iterative_gate(
        history_path,
        min_iterations=min_iterations,
        tail_window=tail_window,
    )
    provenance_payload = (
        provenance_gates.model_dump(mode="json")
        if hasattr(provenance_gates, "model_dump")
        else dict(provenance_gates or {})
    )
    reference_gate_status = str(
        provenance_payload.get("reference_quantities", {}).get("status", "warn")
    )
    force_surface_gate_status = str(
        provenance_payload.get("force_surface", {}).get("status", "warn")
    )
    overall_gate = build_overall_convergence_gate(
        mesh_gate_status=mesh_gate.status,
        iterative_gate_status=iterative_gate.status,
        reference_gate_status=reference_gate_status,
        force_surface_gate_status=force_surface_gate_status,
    )
    return BaselineConvergenceGate(
        mesh_gate=mesh_gate,
        iterative_gate=iterative_gate,
        overall_convergence_gate=overall_gate,
    )
