from __future__ import annotations

import copy
import csv
import json
import math
import statistics
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .adapters.su2_backend import (
    _mpi_ranks as _backend_mpi_ranks,
    _omp_threads_per_rank as _backend_omp_threads_per_rank,
    _resolve_launch_requirements as _backend_resolve_launch_requirements,
    _solver_command as _backend_solver_command,
    _solver_env as _backend_solver_env,
)
from .gmsh_runtime import GmshRuntimeError, load_gmsh
from .providers.esp_pipeline import extract_native_lifting_surface_sections
from .reports.json_report import write_json_report
from .reports.markdown_report import write_markdown_report
from .schema import SU2RuntimeConfig


DEFAULT_ROUTE_NAME = "shell_v4_half_wing_bl_mesh_macsafe"
DEFAULT_CHORD_M = 1.05
DEFAULT_HALF_SPAN_M = 16.5
DEFAULT_HALF_WING_REF_AREA = 17.325
DEFAULT_FULL_WING_REF_AREA = 34.65
DEFAULT_REF_ORIGIN = {"x": 0.25 * DEFAULT_CHORD_M, "y": 0.0, "z": 0.0}
DEFAULT_GEOMETRY_SHAPE_MODE = "surrogate_naca0012"
DEFAULT_REAL_MAIN_WING_SHAPE_MODE = "esp_rebuilt_main_wing"

DEFAULT_FLOW_CONDITION = {
    "alpha_deg": 0.0,
    "velocity_mps": 6.5,
    "density_kgpm3": 1.225,
    "temperature_k": 288.15,
    "dynamic_viscosity_pas": 1.789e-5,
}

DEFAULT_STUDY_SPECS: dict[str, dict[str, Any]] = {
    "BL_macsafe_baseline": {
        "study_level": "BL_macsafe_baseline",
        "geometry": {
            "shape_mode": DEFAULT_GEOMETRY_SHAPE_MODE,
            "chord_m": DEFAULT_CHORD_M,
            "half_span_m": DEFAULT_HALF_SPAN_M,
            "airfoil_name": "NACA0012 surrogate",
            "airfoil_loop_points": 160,
            "half_span_stations": 108,
            "leading_edge_tangential_refinement": True,
            "trailing_edge_tangential_refinement": True,
        },
        "reference_values": {
            "ref_length": DEFAULT_CHORD_M,
            "ref_area": DEFAULT_HALF_WING_REF_AREA,
            "ref_area_mode": "half_wing_coefficients",
            "alternate_full_wing_ref_area": DEFAULT_FULL_WING_REF_AREA,
            "alternate_force_multiplier": 2.0,
            "ref_origin_moment": DEFAULT_REF_ORIGIN,
        },
        "boundary_layer": {
            "first_layer_height_m": 5.0e-5,
            "layers": 24,
            "growth_ratio": 1.24,
            "require_explicit_wall_normal_cells": True,
        },
        "wake_refinement": {
            "wake_length_chords": 5.0,
            "wake_height_chords": 0.7,
            "near_wake_cell_size_chords": 0.10,
        },
        "tip_refinement": {
            "spanwise_length_chords": 0.4,
            "cell_size_chords": 0.16,
        },
        "off_wall_growth": {
            "enabled": True,
            "support_cell_size_chords": 0.20,
            "support_dist_min_chords": 0.15,
            "support_dist_max_chords": 0.60,
            "stop_at_dist_max": True,
        },
        "farfield": {
            "upstream_chords": 5.0,
            "downstream_chords": 8.0,
            "normal_chords": 5.0,
            "outer_cell_size_chords": 2.40,
        },
        "cell_budget": {
            "target_total_cells_min": 1_500_000,
            "target_total_cells_max": 2_200_000,
            "hard_fail_total_cells": 3_000_000,
            "min_volume_to_wall_ratio": 15.0,
            "max_bl_collapse_rate": 0.02,
        },
        "solver": {
            "enabled": True,
            "solver": "INC_RANS",
            "turbulence_model": "SST",
            "transition_model": "NONE",
            "parallel_mode": "mpi",
            "mpi_launcher": "mpirun",
            "cpu_threads": 4,
            "mpi_ranks": 4,
            "omp_threads_per_rank": 1,
            "solver_command": "SU2_CFD",
            "min_iterations": 500,
            "stretch_iterations": 800,
            "cfl_number": 2.5,
            "linear_solver": "FGMRES",
            "linear_solver_prec": "LU_SGS",
            "linear_solver_error": 1.0e-5,
            "linear_solver_iterations": 6,
            "cauchy_field": "LIFT",
            "cauchy_elems": 100,
            "cauchy_eps": 5.0e-5,
            "cauchy_start_iter": 100,
        },
    },
    "BL_macsafe_upper": {
        "study_level": "BL_macsafe_upper",
        "geometry": {
            "shape_mode": DEFAULT_GEOMETRY_SHAPE_MODE,
            "chord_m": DEFAULT_CHORD_M,
            "half_span_m": DEFAULT_HALF_SPAN_M,
            "airfoil_name": "NACA0012 surrogate",
            "airfoil_loop_points": 176,
            "half_span_stations": 120,
            "leading_edge_tangential_refinement": True,
            "trailing_edge_tangential_refinement": True,
        },
        "reference_values": {
            "ref_length": DEFAULT_CHORD_M,
            "ref_area": DEFAULT_HALF_WING_REF_AREA,
            "ref_area_mode": "half_wing_coefficients",
            "alternate_full_wing_ref_area": DEFAULT_FULL_WING_REF_AREA,
            "alternate_force_multiplier": 2.0,
            "ref_origin_moment": DEFAULT_REF_ORIGIN,
        },
        "boundary_layer": {
            "first_layer_height_m": 5.0e-5,
            "layers": 24,
            "growth_ratio": 1.25,
            "require_explicit_wall_normal_cells": True,
        },
        "wake_refinement": {
            "wake_length_chords": 10.0,
            "wake_height_chords": 1.0,
            "near_wake_cell_size_chords": 0.04,
        },
        "tip_refinement": {
            "spanwise_length_chords": 1.0,
            "cell_size_chords": 0.06,
        },
        "farfield": {
            "upstream_chords": 8.0,
            "downstream_chords": 12.0,
            "normal_chords": 8.0,
            "outer_cell_size_chords": 1.05,
        },
        "cell_budget": {
            "target_total_cells_min": 2_000_000,
            "target_total_cells_max": 3_500_000,
            "hard_fail_total_cells": 3_500_000,
            "min_volume_to_wall_ratio": 15.0,
            "max_bl_collapse_rate": 0.02,
        },
        "solver": {
            "enabled": True,
            "solver": "INC_RANS",
            "turbulence_model": "SST",
            "transition_model": "NONE",
            "parallel_mode": "mpi",
            "mpi_launcher": "mpirun",
            "cpu_threads": 4,
            "mpi_ranks": 4,
            "omp_threads_per_rank": 1,
            "solver_command": "SU2_CFD",
            "min_iterations": 500,
            "stretch_iterations": 800,
            "cfl_number": 2.0,
            "linear_solver": "FGMRES",
            "linear_solver_prec": "LU_SGS",
            "linear_solver_error": 1.0e-5,
            "linear_solver_iterations": 8,
            "cauchy_field": "LIFT",
            "cauchy_elems": 120,
            "cauchy_eps": 5.0e-5,
            "cauchy_start_iter": 120,
        },
    },
}


def _deep_update(target: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
    return target


def _layer_cumulative_heights(
    first_layer_height_m: float,
    growth_ratio: float,
    layers: int,
) -> list[float]:
    cumulative: list[float] = []
    running = 0.0
    for idx in range(layers):
        running += first_layer_height_m * growth_ratio**idx
        cumulative.append(float(running))
    return cumulative


def _total_bl_thickness(first_layer_height_m: float, growth_ratio: float, layers: int) -> float:
    if layers <= 0:
        return 0.0
    if abs(growth_ratio - 1.0) < 1.0e-12:
        return float(first_layer_height_m * layers)
    return float(first_layer_height_m * (growth_ratio**layers - 1.0) / (growth_ratio - 1.0))


def estimate_first_cell_yplus_range(
    *,
    velocity_mps: float,
    density_kgpm3: float,
    dynamic_viscosity_pas: float,
    ref_length_m: float,
    first_layer_height_m: float,
) -> dict[str, float]:
    reynolds_number = max(
        1.0,
        density_kgpm3 * velocity_mps * ref_length_m / max(dynamic_viscosity_pas, 1.0e-12),
    )
    cf_laminar = 0.664 / math.sqrt(reynolds_number)
    cf_turbulent = 0.0592 / reynolds_number**0.2
    tau_laminar = 0.5 * density_kgpm3 * velocity_mps**2 * cf_laminar
    tau_turbulent = 0.5 * density_kgpm3 * velocity_mps**2 * cf_turbulent
    u_tau_laminar = math.sqrt(max(tau_laminar / density_kgpm3, 0.0))
    u_tau_turbulent = math.sqrt(max(tau_turbulent / density_kgpm3, 0.0))
    y_plus_laminar = density_kgpm3 * u_tau_laminar * first_layer_height_m / max(dynamic_viscosity_pas, 1.0e-12)
    y_plus_turbulent = density_kgpm3 * u_tau_turbulent * first_layer_height_m / max(dynamic_viscosity_pas, 1.0e-12)
    return {
        "reynolds_number": float(reynolds_number),
        "cf_laminar_proxy": float(cf_laminar),
        "cf_turbulent_proxy": float(cf_turbulent),
        "y_plus_min": float(min(y_plus_laminar, y_plus_turbulent)),
        "y_plus_max": float(max(y_plus_laminar, y_plus_turbulent)),
    }


def build_shell_v4_half_wing_bl_macsafe_spec(
    study_level: str = "BL_macsafe_baseline",
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if study_level not in DEFAULT_STUDY_SPECS:
        raise ValueError(f"unsupported study level: {study_level}")
    spec = copy.deepcopy(DEFAULT_STUDY_SPECS[study_level])
    if overrides:
        _deep_update(spec, copy.deepcopy(overrides))
        study_level = str(spec.get("study_level", study_level))
    spec["route_name"] = DEFAULT_ROUTE_NAME
    spec["study_level"] = study_level
    ref_values = spec["reference_values"]
    if float(ref_values.get("ref_area", 0.0) or 0.0) <= 0.0:
        raise ValueError("REF_AREA must stay positive for shell_v4_half_wing_bl_mesh_macsafe")
    bl = spec["boundary_layer"]
    total_thickness = _total_bl_thickness(
        float(bl["first_layer_height_m"]),
        float(bl["growth_ratio"]),
        int(bl["layers"]),
    )
    bl["target_total_thickness_m"] = total_thickness
    spec["solver"] = _normalize_solver_parallel_settings(spec["solver"])
    spec["flow_condition"] = copy.deepcopy(DEFAULT_FLOW_CONDITION)
    return spec


def _normalize_solver_parallel_settings(solver: dict[str, Any]) -> dict[str, Any]:
    parallel_mode = str(solver.get("parallel_mode", "threads"))
    solver["parallel_mode"] = parallel_mode
    solver["mpi_launcher"] = str(solver.get("mpi_launcher", "mpirun"))
    mpi_ranks = max(1, int(solver.get("mpi_ranks", 1)))
    solver["mpi_ranks"] = mpi_ranks
    if parallel_mode == "mpi":
        if "omp_threads_per_rank" in solver:
            omp_threads_per_rank = max(1, int(solver["omp_threads_per_rank"]))
            solver["cpu_threads"] = mpi_ranks * omp_threads_per_rank
        else:
            total_cpu_threads = max(1, int(solver.get("cpu_threads", mpi_ranks)))
            omp_threads_per_rank = max(1, total_cpu_threads // mpi_ranks)
            solver["cpu_threads"] = mpi_ranks * omp_threads_per_rank
        solver["omp_threads_per_rank"] = omp_threads_per_rank
        return solver
    total_cpu_threads = max(1, int(solver.get("cpu_threads", 1)))
    solver["cpu_threads"] = total_cpu_threads
    solver["omp_threads_per_rank"] = total_cpu_threads
    return solver


def _solver_runtime_config(spec: dict[str, Any]) -> SU2RuntimeConfig:
    solver = spec["solver"]
    return SU2RuntimeConfig(
        enabled=bool(solver.get("enabled", True)),
        solver_command=str(solver.get("solver_command", "SU2_CFD")),
        parallel_mode=str(solver.get("parallel_mode", "threads")),
        mpi_launcher=str(solver.get("mpi_launcher", "mpirun")),
        cpu_threads=max(1, int(solver.get("cpu_threads", 1))),
        mpi_ranks=max(1, int(solver.get("mpi_ranks", 1))),
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _quality_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "min": None,
            "p05": None,
            "median": None,
            "mean": None,
            "max": None,
        }
    return {
        "min": float(min(values)),
        "p05": _percentile(values, 0.05),
        "median": float(statistics.median(values)),
        "mean": float(statistics.fmean(values)),
        "max": float(max(values)),
    }


def _element_type_counts(
    element_types: Iterable[int],
    element_tags: Iterable[Iterable[int]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element_type, tags in zip(element_types, element_tags):
        counts[str(int(element_type))] = int(len(tags))
    return counts


def _read_history_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        return []
    header = [value.strip().strip('"') for value in rows[0]]
    data_rows: list[dict[str, str]] = []
    for raw in rows[1:]:
        if len(raw) != len(header):
            continue
        data_rows.append({key: value.strip() for key, value in zip(header, raw)})
    return data_rows


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    parsed = _parse_float(value)
    return None if parsed is None else int(parsed)


def _numeric_series(rows: list[dict[str, str]], column_names: Iterable[str]) -> tuple[list[float], str | None]:
    for column in column_names:
        if not rows or column not in rows[0]:
            continue
        values = []
        for row in rows:
            parsed = _parse_float(row.get(column))
            if parsed is not None:
                values.append(parsed)
        if values:
            return values, column
    return [], None


def _tail_force_variation(rows: list[dict[str, str]], window: int = 200) -> dict[str, Any]:
    if not rows:
        return {"reported": False}
    tail_rows = rows[-min(window, len(rows)) :]
    metrics: dict[str, Any] = {
        "reported": False,
        "sample_count": len(tail_rows),
    }
    overall_reported = True
    for label, candidates in {
        "cl": ("CL", "LIFT"),
        "cd": ("CD", "DRAG"),
        "cm": ("CMy", "CMY", "CMz", "CMZ", "CM"),
    }.items():
        series, column = _numeric_series(tail_rows, candidates)
        if not series:
            overall_reported = False
            metrics[label] = {"reported": False}
            continue
        mean_value = statistics.fmean(series)
        scale = max(abs(mean_value), abs(series[-1]), 1.0e-6)
        metrics[label] = {
            "reported": True,
            "column": column,
            "mean": float(mean_value),
            "range": float(max(series) - min(series)),
            "relative_range": float((max(series) - min(series)) / scale),
            "delta": float(series[-1] - series[0]),
        }
    metrics["reported"] = overall_reported
    return metrics


def _residual_behavior(rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        return {"status": "unavailable", "notes": ["history_rows_missing"]}
    residual_columns = [
        name
        for name in rows[0]
        if name.lower().startswith("rms[")
        or name.lower().startswith("rms_")
        or name.lower().startswith("res[")
        or name.lower().startswith("res_")
    ]
    if not residual_columns:
        return {"status": "unavailable", "notes": ["residual_columns_missing"]}
    drops: dict[str, float] = {}
    for column in residual_columns:
        series, _ = _numeric_series(rows, (column,))
        if len(series) < 6:
            continue
        startup_skip = min(10, max(0, len(series) // 8))
        trimmed = series[startup_skip:]
        if len(trimmed) < 4:
            trimmed = series
        baseline = trimmed[: max(2, len(trimmed) // 2)]
        tail = trimmed[-max(2, len(trimmed) // 4) :]
        drops[column] = float(statistics.median(baseline) - statistics.median(tail))
    if not drops:
        return {"status": "unavailable", "notes": ["residual_series_too_short"]}
    median_drop = statistics.median(drops.values())
    status = "decreasing" if median_drop >= 0.4 else "stable" if median_drop >= 0.1 else "flat_or_rising"
    return {
        "status": status,
        "median_log_drop": float(median_drop),
        "columns": drops,
    }


def _cauchy_cl_status(rows: list[dict[str, str]], force_variation: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return {"status": "unavailable"}
    cauchy_candidates = [name for name in rows[0] if "cauchy" in name.lower()]
    for candidate in cauchy_candidates:
        if "lift" not in candidate.lower() and "cl" not in candidate.lower():
            continue
        series, _ = _numeric_series(rows, (candidate,))
        if not series:
            continue
        tail = series[-min(50, len(series)) :]
        mean_abs = statistics.fmean(abs(value) for value in tail)
        status = "converged" if mean_abs <= 1.0e-4 else "nearly_flat" if mean_abs <= 5.0e-4 else "drifting"
        return {
            "status": status,
            "column": candidate,
            "tail_mean_abs": float(mean_abs),
        }
    cl_metrics = force_variation.get("cl", {}) if isinstance(force_variation, dict) else {}
    if cl_metrics.get("reported"):
        relative_range = float(cl_metrics.get("relative_range", 0.0))
        status = "nearly_flat" if relative_range <= 0.02 else "drifting"
        return {
            "status": status,
            "column": "CL tail flatness proxy",
            "tail_relative_range": relative_range,
        }
    return {"status": "unavailable"}


def _solver_memory_estimate_gb(
    *,
    total_nodes: int,
    total_cells: int,
    solver: dict[str, Any],
) -> float:
    base_gb = 1.25
    per_node_gb = 8.0e-6
    per_cell_gb = 2.0e-6
    solver_factor = 1.18 if solver.get("solver") == "INC_RANS" and solver.get("turbulence_model") == "SST" else 1.0
    thread_factor = 1.0 + 0.04 * max(0, int(solver.get("cpu_threads", 1)) - 1)
    return float((base_gb + total_nodes * per_node_gb + total_cells * per_cell_gb) * solver_factor * thread_factor)


def _memory_classification(estimated_ram_gb: float) -> dict[str, Any]:
    if estimated_ram_gb <= 11.0:
        return {
            "ram_class": "safe_physical",
            "auto_launch_allowed": True,
            "swap_risk": False,
            "notes": ["estimated RAM fits within a conservative 16 GB Mac mini band."],
        }
    if estimated_ram_gb <= 15.0:
        return {
            "ram_class": "swap_risk",
            "auto_launch_allowed": False,
            "swap_risk": True,
            "notes": ["estimated RAM may run on swap, but the route requires explicit override."],
        }
    return {
        "ram_class": "above_mac_safe",
        "auto_launch_allowed": False,
        "swap_risk": False,
        "notes": ["estimated RAM exceeds the Mac-safe range for a 16 GB unified-memory system."],
    }


def _naca0012_points(loop_points: int, chord_m: float) -> list[tuple[float, float]]:
    n_upper = max(4, loop_points // 2)
    samples: list[tuple[float, float]] = []
    for idx in range(n_upper):
        beta = math.pi * idx / max(1, n_upper - 1)
        x = 0.5 * (1.0 - math.cos(beta))
        thickness = 5.0 * 0.12 * (
            0.2969 * math.sqrt(max(x, 1.0e-12))
            - 0.1260 * x
            - 0.3516 * x**2
            + 0.2843 * x**3
            - 0.1036 * x**4
        )
        samples.append((x * chord_m, thickness * chord_m))
    upper = list(reversed(samples))
    lower = [(x, -z) for x, z in samples[1:-1]]
    return upper + lower


def _default_real_main_wing_source_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "blackcat_004_origin.vsp3"


def _geometry_shape_mode(geometry: dict[str, Any]) -> str:
    return str(geometry.get("shape_mode") or DEFAULT_GEOMETRY_SHAPE_MODE)


def _rotate_about_local_span(
    point: tuple[float, float, float],
    twist_deg: float,
) -> tuple[float, float, float]:
    angle = math.radians(-float(twist_deg))
    x, y, z = (float(value) for value in point)
    return (
        x * math.cos(angle) + z * math.sin(angle),
        y,
        -x * math.sin(angle) + z * math.cos(angle),
    )


def _global_section_profile_points(section: dict[str, Any]) -> list[tuple[float, float, float]]:
    chord = float(section["chord"])
    x_le = float(section["x_le"])
    y_le = float(section["y_le"])
    z_le = float(section["z_le"])
    twist_deg = float(section.get("twist_deg", 0.0) or 0.0)
    raw_coordinates = section.get("airfoil_coordinates") or []
    coordinates = [(float(x_value), float(z_value)) for x_value, z_value in raw_coordinates]
    if not coordinates:
        raise ValueError("real main wing section is missing airfoil coordinates")
    if len(coordinates) >= 2 and all(
        abs(lhs - rhs) <= 1.0e-12 for lhs, rhs in zip(coordinates[0], coordinates[-1])
    ):
        coordinates = coordinates[:-1]
    if len(coordinates) < 4:
        raise ValueError("real main wing section needs at least four profile points")
    global_points: list[tuple[float, float, float]] = []
    for x_rel, z_rel in coordinates:
        local_offset = _rotate_about_local_span((x_rel * chord, 0.0, z_rel * chord), twist_deg)
        global_points.append(
            (
                x_le + float(local_offset[0]),
                y_le + float(local_offset[1]),
                z_le + float(local_offset[2]),
            )
        )
    return global_points


def _leading_edge_index(points: list[tuple[float, float, float]]) -> int:
    if len(points) < 3:
        raise ValueError("profile loop needs at least three points")
    return min(range(len(points)), key=lambda index: (points[index][0], abs(points[index][2])))


def _section_bounds(points: list[tuple[float, float, float]]) -> dict[str, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    return {
        "x_min": float(min(xs)),
        "x_max": float(max(xs)),
        "y_min": float(min(ys)),
        "y_max": float(max(ys)),
        "z_min": float(min(zs)),
        "z_max": float(max(zs)),
    }


def _resolve_real_main_wing_geometry(
    *,
    geometry: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    source_path = Path(geometry.get("source_path") or _default_real_main_wing_source_path())
    if not source_path.exists():
        raise FileNotFoundError(f"real main wing source not found: {source_path}")
    component = str(geometry.get("component") or "main_wing")
    extracted = extract_native_lifting_surface_sections(
        source_path=source_path,
        component=component,
        include_mirrored=False,
    )
    if not extracted.get("surfaces"):
        raise RuntimeError("real main wing extraction returned no surfaces")
    surface = extracted["surfaces"][0]
    sections = list(surface.get("sections") or [])
    if len(sections) < 2:
        raise RuntimeError("real main wing extraction returned fewer than two spanwise sections")

    section_profiles = [_global_section_profile_points(section) for section in sections]
    section_bounds = [_section_bounds(points) for points in section_profiles]
    overall_bounds = {
        "x_min": min(bounds["x_min"] for bounds in section_bounds),
        "x_max": max(bounds["x_max"] for bounds in section_bounds),
        "y_min": min(bounds["y_min"] for bounds in section_bounds),
        "y_max": max(bounds["y_max"] for bounds in section_bounds),
        "z_min": min(bounds["z_min"] for bounds in section_bounds),
        "z_max": max(bounds["z_max"] for bounds in section_bounds),
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "real_main_wing_sections.json"
    write_json_report(
        artifact_path,
        {
            **extracted,
            "selected_surface": {
                "component": surface.get("component"),
                "name": surface.get("name"),
                "caps_group": surface.get("caps_group"),
                "rotation_deg": surface.get("rotation_deg"),
            },
            "overall_bounds": overall_bounds,
        },
    )
    return {
        "shape_mode": DEFAULT_REAL_MAIN_WING_SHAPE_MODE,
        "source_path": str(source_path),
        "component": component,
        "surface_name": surface.get("name"),
        "surface_rotation_deg": list(surface.get("rotation_deg") or [0.0, 0.0, 0.0]),
        "sections": sections,
        "section_profiles": section_profiles,
        "section_bounds": section_bounds,
        "overall_bounds": overall_bounds,
        "artifact_path": str(artifact_path),
    }


def _build_real_main_wing_occ_shell(
    *,
    gmsh: Any,
    section_profiles: list[list[tuple[float, float, float]]],
) -> tuple[list[int], list[int], dict[str, Any]]:
    occ = gmsh.model.occ
    wire_tags: list[int] = []
    tip_curves: list[int] = []
    for section_index, points in enumerate(section_profiles):
        point_tags = [occ.addPoint(float(x), float(y), float(z)) for x, y, z in points]
        split_idx = _leading_edge_index(points)
        upper_curve = occ.addSpline(point_tags[: split_idx + 1])
        lower_curve = occ.addSpline(point_tags[split_idx:])
        trailing_edge_curve = occ.addLine(point_tags[-1], point_tags[0])
        wire_tag = occ.addWire([upper_curve, lower_curve, trailing_edge_curve], checkClosed=True)
        wire_tags.append(int(wire_tag))
        if section_index == len(section_profiles) - 1:
            tip_curves = [int(upper_curve), int(lower_curve), int(trailing_edge_curve)]
    if len(wire_tags) < 2:
        raise RuntimeError("real main wing shell needs at least two section wires")
    loft_entities = occ.addThruSections(
        wire_tags,
        makeSolid=False,
        continuity="C1",
        parametrization="ChordLength",
        smoothing=True,
    )
    occ.synchronize()
    wall_surface_tags = [int(tag) for dim, tag in loft_entities if dim == 2]
    if not wall_surface_tags:
        raise RuntimeError("real main wing loft did not create any wall surfaces")
    tip_loop = occ.addCurveLoop(_order_curve_loop(gmsh, tip_curves))
    tip_surface_tag = int(occ.addPlaneSurface([tip_loop]))
    occ.synchronize()
    wall_surface_tags.append(tip_surface_tag)
    # The tip cap is geometrically coincident with the loft boundary, but OCC can
    # keep duplicate edges unless we explicitly collapse them before BL extrusion.
    occ.removeAllDuplicates()
    occ.synchronize()
    wall_surface_tags = [int(tag) for dim, tag in gmsh.model.getEntities(2) if dim == 2]
    return wall_surface_tags, tip_curves, {"tip_surface_tag": tip_surface_tag}


def _curve_endpoint_tags(gmsh: Any, curve_tag: int) -> tuple[int, int]:
    boundary = gmsh.model.getBoundary([(1, curve_tag)], combined=False)
    if len(boundary) != 2:
        raise RuntimeError(f"curve {curve_tag} does not expose exactly two endpoints")
    return int(boundary[0][1]), int(boundary[1][1])


def _order_curve_loop(gmsh: Any, curve_tags: list[int]) -> list[int]:
    endpoint_map = {tag: _curve_endpoint_tags(gmsh, tag) for tag in curve_tags}
    ordered = [curve_tags[0]]
    used = {curve_tags[0]}
    _, current_end = endpoint_map[curve_tags[0]]
    while len(ordered) < len(curve_tags):
        found: int | None = None
        for tag in curve_tags:
            if tag in used:
                continue
            start, end = endpoint_map[tag]
            if start == current_end:
                found = tag
                current_end = end
                break
            if end == current_end:
                found = -tag
                current_end = start
                break
        if found is None:
            raise RuntimeError(f"could not order loop from remaining curves {curve_tags}")
        used.add(abs(found))
        ordered.append(found)
    return ordered


def _set_shell_transfinite_controls(
    gmsh: Any,
    *,
    chord_m: float,
    half_span_m: float,
    airfoil_loop_points: int,
    half_span_stations: int,
) -> None:
    airfoil_curve_points = max(4, airfoil_loop_points // 2)
    te_curve_points = 3
    for dim, tag in gmsh.model.getEntities(1):
        if dim != 1:
            continue
        x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(dim, tag)
        y_span = y_max - y_min
        x_span = x_max - x_min
        z_span = z_max - z_min
        if y_span >= 0.8 * half_span_m:
            gmsh.model.mesh.setTransfiniteCurve(tag, half_span_stations)
        elif x_span >= 0.2 * chord_m or z_span >= 0.05 * chord_m:
            gmsh.model.mesh.setTransfiniteCurve(tag, airfoil_curve_points)
        else:
            gmsh.model.mesh.setTransfiniteCurve(tag, te_curve_points)
    for dim, tag in gmsh.model.getEntities(2):
        if dim != 2:
            continue
        try:
            gmsh.model.mesh.setTransfiniteSurface(tag)
        except Exception:
            continue


def _count_elements_for_entities(gmsh: Any, dim: int, entity_tags: Iterable[int]) -> tuple[int, dict[str, int]]:
    total = 0
    counts: dict[str, int] = {}
    for entity_tag in entity_tags:
        element_types, element_tags, _ = gmsh.model.mesh.getElements(dim, int(entity_tag))
        for element_type, tags in zip(element_types, element_tags):
            count = int(len(tags))
            total += count
            counts[str(int(element_type))] = counts.get(str(int(element_type)), 0) + count
    return total, counts


def _physical_group_summary(
    *,
    physical_tag: int | None,
    physical_name: str,
    dimension: int,
    entity_count: int,
    element_count: int,
    virtual: bool = False,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "exists": True,
        "physical_name": physical_name,
        "physical_tag": physical_tag,
        "dimension": dimension,
        "entity_count": int(entity_count),
        "element_count": int(element_count),
        "virtual": virtual,
        "notes": list(notes or []),
    }


def _surface_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{str(key).strip().strip('"'): str(value).strip() for key, value in row.items()} for row in reader]


def _surface_yplus_summary(path: Path) -> dict[str, Any] | None:
    rows = _surface_csv_rows(path)
    if not rows:
        return None
    y_plus_column = next((name for name in rows[0] if name.upper() == "Y_PLUS"), None)
    if y_plus_column is None:
        return None
    values = []
    for row in rows:
        parsed = _parse_float(row.get(y_plus_column))
        if parsed is not None:
            values.append(parsed)
    if not values:
        return None
    return {
        "source": "surface.csv",
        "min": float(min(values)),
        "mean": float(statistics.fmean(values)),
        "max": float(max(values)),
    }


def _coord_key(x: float, y: float, z: float, *, ndigits: int = 12) -> tuple[float, float, float]:
    return (round(float(x), ndigits), round(float(y), ndigits), round(float(z), ndigits))


def _height_lookup_maps_by_precision(
    point_first_layer_heights_m: dict[tuple[float, float, float], float],
) -> dict[int, dict[tuple[float, float, float], float]]:
    precision_maps: dict[int, dict[tuple[float, float, float], float]] = {}
    for ndigits in (12, 10, 8, 6, 4):
        precision_maps[ndigits] = {
            _coord_key(*coords, ndigits=ndigits): float(height)
            for coords, height in point_first_layer_heights_m.items()
        }
    return precision_maps


def _lookup_first_layer_height(
    height_maps_by_precision: dict[int, dict[tuple[float, float, float], float]],
    *,
    x: float,
    y: float,
    z: float,
) -> float | None:
    for ndigits in (12, 10, 8, 6, 4):
        precision_map = height_maps_by_precision.get(ndigits, {})
        value = precision_map.get(_coord_key(x, y, z, ndigits=ndigits))
        if value is not None:
            return float(value)
    return None


def _read_legacy_vtk_point_data(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    points: list[tuple[float, float, float]] = []
    scalars: dict[str, list[float]] = {}
    vectors: dict[str, list[tuple[float, float, float]]] = {}
    point_count: int | None = None
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        parts = stripped.split()
        keyword = parts[0].upper()
        if keyword == "POINTS" and len(parts) >= 3:
            point_count = int(parts[1])
            values: list[float] = []
            index += 1
            while index < len(lines) and len(values) < 3 * point_count:
                values.extend(float(token) for token in lines[index].split())
                index += 1
            points = [
                (float(values[offset]), float(values[offset + 1]), float(values[offset + 2]))
                for offset in range(0, 3 * point_count, 3)
            ]
            continue
        if keyword == "POINT_DATA" and len(parts) >= 2:
            point_count = int(parts[1])
            index += 1
            continue
        if keyword == "SCALARS" and point_count is not None and len(parts) >= 3:
            field_name = parts[1]
            component_count = int(parts[3]) if len(parts) >= 4 else 1
            index += 1
            if index < len(lines) and lines[index].strip().upper().startswith("LOOKUP_TABLE"):
                index += 1
            needed_values = point_count * component_count
            values: list[float] = []
            while index < len(lines) and len(values) < needed_values:
                values.extend(float(token) for token in lines[index].split())
                index += 1
            scalars[field_name] = [float(value) for value in values[:point_count]]
            continue
        if keyword == "VECTORS" and point_count is not None and len(parts) >= 3:
            field_name = parts[1]
            values: list[float] = []
            index += 1
            while index < len(lines) and len(values) < 3 * point_count:
                values.extend(float(token) for token in lines[index].split())
                index += 1
            vectors[field_name] = [
                (float(values[offset]), float(values[offset + 1]), float(values[offset + 2]))
                for offset in range(0, 3 * point_count, 3)
            ]
            continue
        index += 1
    if not points:
        return None
    return {
        "points": points,
        "scalars": scalars,
        "vectors": vectors,
    }


def _wing_wall_first_layer_height_map(mesh_path: Path) -> dict[tuple[float, float, float], float]:
    gmsh = load_gmsh()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(str(mesh_path))
        wall_tag = next(
            (
                int(tag)
                for dim, tag in gmsh.model.getPhysicalGroups(2)
                if gmsh.model.getPhysicalName(dim, tag) == "wing_wall"
            ),
            None,
        )
        if wall_tag is None:
            return {}
        wall_entities = gmsh.model.getEntitiesForPhysicalGroup(2, wall_tag)
        wall_faces: set[frozenset[int]] = set()
        for entity in wall_entities:
            element_types, _, element_node_tags = gmsh.model.mesh.getElements(2, int(entity))
            for element_type, node_tags in zip(element_types, element_node_tags):
                _, _, _, num_nodes, _, _ = gmsh.model.mesh.getElementProperties(int(element_type))
                if int(num_nodes) != 3:
                    continue
                for start in range(0, len(node_tags), 3):
                    wall_faces.add(frozenset(int(tag) for tag in node_tags[start : start + 3]))
        if not wall_faces:
            return {}

        node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
        coord_by_tag = {
            int(node_tag): (
                float(node_coords[3 * index]),
                float(node_coords[3 * index + 1]),
                float(node_coords[3 * index + 2]),
            )
            for index, node_tag in enumerate(node_tags)
        }

        heights_by_node: dict[int, list[float]] = defaultdict(list)
        element_types, _, element_node_tags = gmsh.model.mesh.getElements(3)
        for element_type, node_tags in zip(element_types, element_node_tags):
            _, _, _, num_nodes, _, _ = gmsh.model.mesh.getElementProperties(int(element_type))
            if int(num_nodes) != 6:
                continue
            for start in range(0, len(node_tags), 6):
                prism_nodes = [int(tag) for tag in node_tags[start : start + 6]]
                lower_face = frozenset(prism_nodes[:3])
                upper_face = frozenset(prism_nodes[3:6])
                if lower_face in wall_faces:
                    wall_nodes = prism_nodes[:3]
                    first_layer_nodes = prism_nodes[3:6]
                elif upper_face in wall_faces:
                    wall_nodes = prism_nodes[3:6]
                    first_layer_nodes = prism_nodes[:3]
                else:
                    continue
                for wall_node, first_layer_node in zip(wall_nodes, first_layer_nodes):
                    wx, wy, wz = coord_by_tag[wall_node]
                    fx, fy, fz = coord_by_tag[first_layer_node]
                    heights_by_node[wall_node].append(math.dist((wx, wy, wz), (fx, fy, fz)))

        return {
            _coord_key(*coord_by_tag[node_tag]): float(statistics.fmean(values))
            for node_tag, values in heights_by_node.items()
            if values
        }
    finally:
        gmsh.finalize()


def _yplus_from_skin_friction(
    *,
    skin_friction_coeff_magnitude: float,
    first_layer_height_m: float,
    density_kgpm3: float,
    velocity_mps: float,
    dynamic_viscosity_pas: float,
) -> float:
    tau_wall = 0.5 * density_kgpm3 * velocity_mps**2 * max(abs(skin_friction_coeff_magnitude), 0.0)
    u_tau = math.sqrt(max(tau_wall / max(density_kgpm3, 1.0e-12), 0.0))
    return float(
        density_kgpm3 * u_tau * first_layer_height_m / max(dynamic_viscosity_pas, 1.0e-12)
    )


def _derive_wall_diagnostics_from_surface_vtk(
    surface_vtk_path: Path,
    point_first_layer_heights_m: dict[tuple[float, float, float], float],
    flow: dict[str, Any],
) -> dict[str, Any] | None:
    dataset = _read_legacy_vtk_point_data(surface_vtk_path)
    if dataset is None:
        return None
    scalars = dataset["scalars"]
    vectors = dataset["vectors"]
    pressure_coeff_field = next(
        (name for name in ("Pressure_Coefficient", "PRESSURE_COEFF", "PressureCoeff") if name in scalars),
        None,
    )
    pressure_field = next((name for name in ("Pressure", "PRESSURE") if name in scalars), None)
    y_plus_field = next((name for name in ("Y_Plus", "Y_PLUS", "YPlus") if name in scalars), None)
    skin_friction_field = next(
        (
            name
            for name in (
                "Skin_Friction_Coefficient",
                "SKIN_FRICTION_COEFFICIENT",
                "Skin_Friction",
            )
            if name in vectors
        ),
        None,
    )
    if y_plus_field is None and skin_friction_field is None and pressure_coeff_field is None and pressure_field is None:
        return None

    height_maps_by_precision = _height_lookup_maps_by_precision(point_first_layer_heights_m)
    rows: list[dict[str, float]] = []
    y_plus_values: list[float] = []
    cf_values: list[float] = []
    y_plus_source = "native_surface_vtk_y_plus" if y_plus_field is not None else None
    for index, (x, y, z) in enumerate(dataset["points"]):
        row: dict[str, float] = {
            "x": float(x),
            "y": float(y),
            "z": float(z),
        }
        if pressure_coeff_field is not None:
            row["pressure_coefficient"] = float(scalars[pressure_coeff_field][index])
        if pressure_field is not None:
            row["pressure"] = float(scalars[pressure_field][index])
        if skin_friction_field is not None:
            cf_vector = vectors[skin_friction_field][index]
            cf_magnitude = math.sqrt(sum(component * component for component in cf_vector))
            row["skin_friction_x"] = float(cf_vector[0])
            row["skin_friction_y"] = float(cf_vector[1])
            row["skin_friction_z"] = float(cf_vector[2])
            row["skin_friction_coefficient_magnitude"] = float(cf_magnitude)
            cf_values.append(float(cf_magnitude))
        else:
            cf_magnitude = None

        first_layer_height_m = _lookup_first_layer_height(
            height_maps_by_precision,
            x=x,
            y=y,
            z=z,
        )
        if first_layer_height_m is not None:
            row["first_layer_height_m"] = float(first_layer_height_m)

        if y_plus_field is not None:
            y_plus_value = float(scalars[y_plus_field][index])
            row["y_plus"] = y_plus_value
            y_plus_values.append(y_plus_value)
        elif cf_magnitude is not None and first_layer_height_m is not None:
            y_plus_value = _yplus_from_skin_friction(
                skin_friction_coeff_magnitude=cf_magnitude,
                first_layer_height_m=first_layer_height_m,
                density_kgpm3=float(flow["density_kgpm3"]),
                velocity_mps=float(flow["velocity_mps"]),
                dynamic_viscosity_pas=float(flow["dynamic_viscosity_pas"]),
            )
            row["y_plus"] = y_plus_value
            y_plus_values.append(y_plus_value)
            y_plus_source = "derived_from_surface_vtk_skin_friction_and_mesh_first_layer_height"
        rows.append(row)
    if not rows:
        return None
    diagnostics = {
        "source": "surface.vtk" if y_plus_field is not None else "surface.vtk+mesh_first_layer",
        "point_count": len(rows),
        "pressure_coefficient_field": pressure_coeff_field,
        "pressure_field": pressure_field,
        "y_plus_field": y_plus_field,
        "skin_friction_field": skin_friction_field,
        "rows": rows,
    }
    if y_plus_values:
        diagnostics["y_plus"] = {
            "source": y_plus_source,
            "min": float(min(y_plus_values)),
            "mean": float(statistics.fmean(y_plus_values)),
            "max": float(max(y_plus_values)),
        }
    if cf_values:
        diagnostics["skin_friction_coefficient_magnitude"] = {
            "min": float(min(cf_values)),
            "mean": float(statistics.fmean(cf_values)),
            "max": float(max(cf_values)),
        }
    if pressure_coeff_field is not None:
        pressure_coeff_values = [row["pressure_coefficient"] for row in rows if "pressure_coefficient" in row]
        diagnostics["pressure_coefficient"] = {
            "min": float(min(pressure_coeff_values)),
            "mean": float(statistics.fmean(pressure_coeff_values)),
            "max": float(max(pressure_coeff_values)),
        }
    if pressure_field is not None:
        pressure_values = [row["pressure"] for row in rows if "pressure" in row]
        diagnostics["pressure"] = {
            "min": float(min(pressure_values)),
            "mean": float(statistics.fmean(pressure_values)),
            "max": float(max(pressure_values)),
        }
    return diagnostics


def _write_wall_diagnostics_from_surface_vtk(
    *,
    surface_vtk_path: Path,
    mesh_path: Path,
    flow: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    point_first_layer_heights = _wing_wall_first_layer_height_map(mesh_path)
    diagnostics = _derive_wall_diagnostics_from_surface_vtk(
        surface_vtk_path,
        point_first_layer_heights,
        flow,
    )
    if diagnostics is None:
        return {"status": "skipped", "reason": "surface_vtk_missing_required_wall_fields"}
    rows = diagnostics.pop("rows", [])
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "wing_wall_diagnostics.csv"
    json_path = out_dir / "wing_wall_diagnostics.json"
    fieldnames = [
        "x",
        "y",
        "z",
        "first_layer_height_m",
        "pressure_coefficient",
        "pressure",
        "skin_friction_x",
        "skin_friction_y",
        "skin_friction_z",
        "skin_friction_coefficient_magnitude",
        "y_plus",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    write_json_report(json_path, diagnostics)
    return {
        "status": "written",
        "surface_vtk_path": str(surface_vtk_path),
        "diagnostics_csv_path": str(csv_path),
        "diagnostics_json_path": str(json_path),
        "first_layer_height_map_points": len(point_first_layer_heights),
        **diagnostics,
    }


def _drag_split_from_history(rows: list[dict[str, str]]) -> tuple[float | None, float | None]:
    if not rows:
        return None, None
    final_row = rows[-1]
    pressure_candidates = (
        "CD_Pressure",
        "CD_PRESSURE",
        "CD(p)",
        "CD_P",
        "PRESSURE_DRAG",
    )
    viscous_candidates = (
        "CD_Friction",
        "CD_FRICTION",
        "CD(v)",
        "CD_V",
        "VISCOUS_DRAG",
    )
    pressure_drag = next(
        (_parse_float(final_row.get(name)) for name in pressure_candidates if name in final_row),
        None,
    )
    viscous_drag = next(
        (_parse_float(final_row.get(name)) for name in viscous_candidates if name in final_row),
        None,
    )
    return pressure_drag, viscous_drag


def _write_span_station_profiles(
    path: Path,
    *,
    rows: list[dict[str, str]],
    half_span_m: float,
) -> dict[str, Any]:
    if not rows:
        return {"status": "skipped", "reason": "surface_csv_missing"}
    header = rows[0].keys()
    if not {"x", "y", "z"}.issubset(set(header)):
        return {"status": "skipped", "reason": "surface_csv_missing_xyz"}
    pressure_name = next(
        (name for name in header if name in {"Pressure_Coeff", "PRESSURE_COEFF", "PressureCoeff", "Pressure"}),
        None,
    )
    cf_names = [name for name in header if name.upper() in {"SKIN_FRICTION-X", "SKIN_FRICTION-Y", "SKIN_FRICTION-Z"}]
    if pressure_name is None and not cf_names:
        return {"status": "skipped", "reason": "surface_csv_missing_cp_cf_columns"}

    grouped_y: dict[float, list[dict[str, str]]] = {}
    for row in rows:
        y_value = _parse_float(row.get("y"))
        if y_value is None:
            continue
        grouped_y.setdefault(round(y_value, 4), []).append(row)
    if not grouped_y:
        return {"status": "skipped", "reason": "surface_csv_missing_y_values"}

    target_stations = [0.15, 0.35, 0.55, 0.75, 0.95]
    station_payloads: list[dict[str, Any]] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    for fraction in target_stations:
        target_y = fraction * half_span_m
        selected_y = min(grouped_y, key=lambda value: abs(value - target_y))
        selected_rows = sorted(
            grouped_y[selected_y],
            key=lambda row: (_parse_float(row.get("x")) or 0.0, _parse_float(row.get("z")) or 0.0),
        )
        out_path = path.parent / f"span_station_{fraction:.2f}.csv"
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = ["x", "y", "z"]
            if pressure_name is not None:
                fieldnames.append(pressure_name)
            if cf_names:
                fieldnames.append("Cf_magnitude")
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in selected_rows:
                payload = {
                    "x": row.get("x"),
                    "y": row.get("y"),
                    "z": row.get("z"),
                }
                if pressure_name is not None:
                    payload[pressure_name] = row.get(pressure_name)
                if cf_names:
                    cf_values = [_parse_float(row.get(name)) or 0.0 for name in cf_names]
                    payload["Cf_magnitude"] = math.sqrt(sum(value * value for value in cf_values))
                writer.writerow(payload)
        station_payloads.append(
            {
                "fraction": fraction,
                "target_y_m": target_y,
                "actual_y_m": selected_y,
                "path": str(out_path),
            }
        )
    return {
        "status": "written",
        "stations": station_payloads,
    }


def _build_su2_cfg(
    *,
    spec: dict[str, Any],
    mesh_filename: str,
) -> str:
    flow = spec["flow_condition"]
    reference = spec["reference_values"]
    solver = spec["solver"]
    alpha_rad = math.radians(float(flow["alpha_deg"]))
    vx = float(flow["velocity_mps"]) * math.cos(alpha_rad)
    vz = float(flow["velocity_mps"]) * math.sin(alpha_rad)
    output_fields = "PRESSURE, PRESSURE_COEFF, SKIN_FRICTION-X, SKIN_FRICTION-Y, SKIN_FRICTION-Z, Y_PLUS"
    return "\n".join(
        [
            "% Auto-generated by shell_v4_half_wing_bl_mesh_macsafe",
            f"SOLVER= {solver['solver']}",
            f"KIND_TURB_MODEL= {solver['turbulence_model']}",
            f"KIND_TRANS_MODEL= {solver['transition_model']}",
            "MATH_PROBLEM= DIRECT",
            "SYSTEM_MEASUREMENTS= SI",
            "RESTART_SOL= NO",
            "INC_NONDIM= DIMENSIONAL",
            "INC_DENSITY_MODEL= CONSTANT",
            "FLUID_MODEL= CONSTANT_DENSITY",
            "VISCOSITY_MODEL= CONSTANT_VISCOSITY",
            f"MU_CONSTANT= {float(flow['dynamic_viscosity_pas']):.6e}",
            f"INC_DENSITY_INIT= {float(flow['density_kgpm3']):.6f}",
            f"INC_TEMPERATURE_INIT= {float(flow['temperature_k']):.6f}",
            f"INC_VELOCITY_INIT= ( {vx:.6f}, 0.0, {vz:.6f} )",
            f"AOA= {float(flow['alpha_deg']):.6f}",
            "SIDESLIP_ANGLE= 0.000000",
            f"REF_AREA= {float(reference['ref_area']):.6f}",
            f"REF_LENGTH= {float(reference['ref_length']):.6f}",
            f"REF_ORIGIN_MOMENT_X= {float(reference['ref_origin_moment']['x']):.6f}",
            f"REF_ORIGIN_MOMENT_Y= {float(reference['ref_origin_moment']['y']):.6f}",
            f"REF_ORIGIN_MOMENT_Z= {float(reference['ref_origin_moment']['z']):.6f}",
            f"MESH_FILENAME= {mesh_filename}",
            "MESH_FORMAT= SU2",
            "MARKER_HEATFLUX= ( wing_wall, 0.0 )",
            "MARKER_SYM= ( symmetry )",
            "MARKER_MONITORING= ( wing_wall )",
            "MARKER_PLOTTING= ( wing_wall )",
            "MARKER_FAR= ( farfield )",
            "FREESTREAM_TURBULENCEINTENSITY= 0.05",
            "FREESTREAM_TURB2LAMVISCRATIO= 10.0",
            "NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES",
            "CONV_NUM_METHOD_FLOW= FDS",
            "TIME_DISCRE_FLOW= EULER_IMPLICIT",
            f"LINEAR_SOLVER= {solver['linear_solver']}",
            f"LINEAR_SOLVER_PREC= {solver['linear_solver_prec']}",
            f"LINEAR_SOLVER_ERROR= {float(solver['linear_solver_error']):.0e}",
            f"LINEAR_SOLVER_ITER= {int(solver['linear_solver_iterations'])}",
            f"ITER= {int(solver['min_iterations'])}",
            f"CFL_NUMBER= {float(solver['cfl_number']):.2f}",
            f"CONV_FIELD= {solver['cauchy_field']}",
            f"CONV_CAUCHY_ELEMS= {int(solver['cauchy_elems'])}",
            f"CONV_CAUCHY_EPS= {float(solver['cauchy_eps']):.1e}",
            f"CONV_STARTITER= {int(solver['cauchy_start_iter'])}",
            "TABULAR_FORMAT= CSV",
            "SCREEN_OUTPUT= (INNER_ITER, RMS_RES, AERO_COEFF, CAUCHY)",
            "HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF, CAUCHY)",
            "OUTPUT_FILES= (RESTART_ASCII, PARAVIEW_ASCII, SURFACE_CSV, SURFACE_PARAVIEW_ASCII)",
            f"VOLUME_OUTPUT= {output_fields}",
            "",
        ]
    )


def _solver_command(spec: dict[str, Any], runtime_cfg_name: str) -> list[str]:
    runtime = _solver_runtime_config(spec)
    return _backend_solver_command(runtime, runtime_cfg_name)


def _solver_env(spec: dict[str, Any]) -> dict[str, str]:
    runtime = _solver_runtime_config(spec)
    return _backend_solver_env(runtime)


def _convert_msh_to_su2(mesh_path: Path, su2_path: Path) -> None:
    gmsh = load_gmsh()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(str(mesh_path))
        gmsh.write(str(su2_path))
    finally:
        gmsh.finalize()


def _solver_result_class(
    *,
    mesh_gate_ok: bool,
    solver_status: str,
    final_iteration: int | None,
    residual_behavior: dict[str, Any],
    cauchy_status: dict[str, Any],
    force_variation: dict[str, Any],
) -> tuple[str, bool, str]:
    residual_ok = residual_behavior.get("status") in {"stable", "decreasing"}
    cl_ok = cauchy_status.get("status") in {"converged", "nearly_flat"}
    force_ok = bool(force_variation.get("reported"))
    comparable = (
        mesh_gate_ok
        and solver_status == "completed"
        and (final_iteration or 0) >= 500
        and residual_ok
        and cl_ok
        and force_ok
    )
    if comparable:
        return (
            "mesh_and_solver_valid",
            True,
            "Solver completed with stable residual behavior and near-flat CL; aerodynamic trend interpretation is reasonable, but this remains a Mac-safe validation mesh.",
        )
    if solver_status != "completed":
        return (
            "smoke_only",
            False,
            "Route validation reached mesh-only or launch-only evidence; do not treat the output as aerodynamic trend truth.",
        )
    if force_ok:
        return (
            "trend_only",
            False,
            "Solver completed and force history exists, but comparability gates are still soft; use only for directional trend reading.",
        )
    return (
        "production_not_ready",
        False,
        "The route did not meet the minimum validation gates for useful force interpretation.",
    )


def _run_solver_if_allowed(
    *,
    spec: dict[str, Any],
    mesh_path: Path,
    case_dir: Path,
    estimated_ram: dict[str, Any],
    run_su2: bool,
    allow_swap_risk: bool,
) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=True)
    su2_mesh = case_dir / "mesh.su2"
    runtime_cfg = case_dir / "su2_runtime.cfg"
    solver_log = case_dir / "solver.log"
    surface_csv = case_dir / "surface.csv"
    surface_vtk = case_dir / "surface.vtk"
    history_csv = case_dir / "history.csv"
    runtime = _solver_runtime_config(spec)
    launch_command = _backend_solver_command(runtime, runtime_cfg.name)
    launch_env = _backend_solver_env(runtime)
    solver_summary: dict[str, Any] = {
        "status": "not_run",
        "run_status": "not_started",
        "launch_policy": "skip_su2" if not run_su2 else "pending_memory_gate",
        "solver_command": " ".join(launch_command),
        "parallel_mode": runtime.parallel_mode,
        "mpi_ranks": _backend_mpi_ranks(runtime),
        "omp_threads_per_rank": _backend_omp_threads_per_rank(runtime),
        "total_cpu_threads": int(runtime.cpu_threads),
        "mpi_launcher": runtime.mpi_launcher if runtime.parallel_mode == "mpi" else None,
        "launch_environment": {
            "OMP_NUM_THREADS": launch_env.get("OMP_NUM_THREADS"),
        },
        "runtime_cfg_path": str(runtime_cfg),
        "history_path": None,
        "surface_output_path": None,
        "surface_vtk_output_path": None,
        "memory_estimate": estimated_ram,
        "force_variation_last_200": {"reported": False},
        "residual_behavior": {"status": "unavailable"},
        "cauchy_cl": {"status": "unavailable"},
        "final_coefficients": {"cl": None, "cd": None, "cm": None},
        "y_plus": None,
        "wall_validation_fields": {"status": "skipped", "reason": "solver_not_run"},
        "span_station_profiles": {"status": "skipped", "reason": "solver_not_run"},
        "wake_slices": {"status": "skipped", "reason": "solver_not_run"},
        "pressure_drag": None,
        "viscous_drag": None,
        "runtime_seconds": None,
    }
    if not run_su2:
        return solver_summary
    if not estimated_ram.get("auto_launch_allowed", False):
        if not (estimated_ram.get("swap_risk") and allow_swap_risk):
            solver_summary["launch_policy"] = "swap_risk_override_required" if estimated_ram.get("swap_risk") else "blocked_memory"
            return solver_summary
        solver_summary["launch_policy"] = "swap_risk_override_enabled"
    else:
        solver_summary["launch_policy"] = "auto_launch"

    launch_requirement_error, missing_value = _backend_resolve_launch_requirements(runtime)
    if launch_requirement_error == "launcher_not_found":
        solver_summary["status"] = "launcher_unavailable"
        solver_summary["missing_runtime"] = missing_value
        solver_summary["run_status"] = "failed"
        return solver_summary
    if launch_requirement_error == "solver_not_found":
        solver_summary["status"] = "solver_unavailable"
        solver_summary["missing_runtime"] = missing_value
        solver_summary["run_status"] = "failed"
        return solver_summary

    _convert_msh_to_su2(mesh_path, su2_mesh)
    runtime_cfg.write_text(_build_su2_cfg(spec=spec, mesh_filename=su2_mesh.name), encoding="utf-8")
    started = time.perf_counter()
    with solver_log.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            launch_command,
            cwd=case_dir,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            env=launch_env,
        )
    solver_summary["runtime_seconds"] = float(time.perf_counter() - started)
    if completed.returncode != 0:
        solver_summary["status"] = "solver_failed"
        solver_summary["run_status"] = "failed"
        return solver_summary

    history_path = history_csv if history_csv.exists() else None
    surface_path = surface_csv if surface_csv.exists() else None
    surface_vtk_path = surface_vtk if surface_vtk.exists() else None
    rows = [] if history_path is None else _read_history_rows(history_path)
    solver_summary["status"] = "completed" if rows else "history_missing"
    solver_summary["run_status"] = "completed" if rows else "failed"
    solver_summary["history_path"] = None if history_path is None else str(history_path)
    solver_summary["surface_output_path"] = None if surface_path is None else str(surface_path)
    solver_summary["surface_vtk_output_path"] = None if surface_vtk_path is None else str(surface_vtk_path)
    if not rows:
        return solver_summary

    final_row = rows[-1]
    cm_column = next((name for name in ("CMy", "CMY", "CMz", "CMZ", "CM") if name in final_row), None)
    solver_summary["final_iteration"] = next(
        (_parse_int(final_row.get(name)) for name in ("Inner_Iter", "ITER", "Outer_Iter") if name in final_row),
        None,
    )
    solver_summary["final_coefficients"] = {
        "cl": _parse_float(final_row.get("CL")),
        "cd": _parse_float(final_row.get("CD")),
        "cm": _parse_float(final_row.get(cm_column)) if cm_column is not None else None,
    }
    pressure_drag, viscous_drag = _drag_split_from_history(rows)
    solver_summary["pressure_drag"] = pressure_drag
    solver_summary["viscous_drag"] = viscous_drag
    solver_summary["force_variation_last_200"] = _tail_force_variation(rows, window=200)
    solver_summary["residual_behavior"] = _residual_behavior(rows)
    solver_summary["cauchy_cl"] = _cauchy_cl_status(rows, solver_summary["force_variation_last_200"])
    if surface_path is not None:
        solver_summary["y_plus"] = _surface_yplus_summary(surface_path)
        solver_summary["span_station_profiles"] = _write_span_station_profiles(
            case_dir / "postprocess" / "span_station_profiles.csv",
            rows=_surface_csv_rows(surface_path),
            half_span_m=float(spec["geometry"]["half_span_m"]),
        )
    if surface_vtk_path is not None:
        solver_summary["wall_validation_fields"] = _write_wall_diagnostics_from_surface_vtk(
            surface_vtk_path=surface_vtk_path,
            mesh_path=mesh_path,
            flow=spec["flow_condition"],
            out_dir=case_dir / "postprocess",
        )
        if solver_summary["y_plus"] is None and solver_summary["wall_validation_fields"].get("status") == "written":
            solver_summary["y_plus"] = solver_summary["wall_validation_fields"].get("y_plus")
    solver_summary["wake_slices"] = {"status": "skipped", "reason": "not_affordable_in_default_macsafe_route"}
    return solver_summary


def run_shell_v4_half_wing_bl_mesh_macsafe(
    *,
    out_dir: str | Path,
    study_level: str = "BL_macsafe_baseline",
    run_su2: bool = True,
    allow_swap_risk: bool = False,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route_started = time.perf_counter()
    out_dir = Path(out_dir)
    mesh_dir = out_dir / "artifacts" / "mesh"
    su2_dir = out_dir / "artifacts" / "su2"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    su2_dir.mkdir(parents=True, exist_ok=True)
    spec = build_shell_v4_half_wing_bl_macsafe_spec(study_level, overrides=overrides)
    flow = spec["flow_condition"]
    geometry = spec["geometry"]
    geometry_shape_mode = _geometry_shape_mode(geometry)
    bl_spec = spec["boundary_layer"]
    cell_budget = spec["cell_budget"]
    reference_values = spec["reference_values"]
    mesh_path = mesh_dir / "mesh.msh"
    mesh_metadata_path = mesh_dir / "mesh_metadata.json"
    quality_path = mesh_dir / "mesh_quality.json"
    field_region_path = mesh_dir / "refinement_regions.json"
    real_wing_geometry: dict[str, Any] | None = None
    if geometry_shape_mode == DEFAULT_REAL_MAIN_WING_SHAPE_MODE:
        real_wing_geometry = _resolve_real_main_wing_geometry(
            geometry=geometry,
            artifact_dir=mesh_dir,
        )
        geometry["source_path"] = real_wing_geometry["source_path"]
        geometry["component"] = real_wing_geometry["component"]
        geometry["airfoil_name"] = f"{real_wing_geometry['surface_name']} extracted sections"
        geometry["real_main_wing_sections_path"] = real_wing_geometry["artifact_path"]
        geometry["source_section_count"] = len(real_wing_geometry["sections"])
        geometry["half_span_m"] = float(real_wing_geometry["overall_bounds"]["y_max"])
        geometry["actual_bounds"] = dict(real_wing_geometry["overall_bounds"])
        geometry["surface_name"] = real_wing_geometry["surface_name"]

    gmsh = load_gmsh()
    gmsh.initialize()
    wall_surface_tags: list[int] = []
    farfield_surface_tags: list[int] = []
    symmetry_surface_tag: int | None = None
    fluid_volume_tag: int | None = None
    bl_volume_tags: list[int] = []
    bl_top_surface_tags: list[int] = []
    quality_metrics: dict[str, Any] = {}
    surface_element_count = 0
    wall_face_count = 0
    symmetry_face_count = 0
    farfield_face_count = 0
    surface_element_type_counts: dict[str, int] = {}
    wall_element_type_counts: dict[str, int] = {}
    total_nodes = 0
    total_cells = 0
    volume_element_type_counts: dict[str, int] = {}
    bl_cell_count = 0
    bl_cell_type_counts: dict[str, int] = {}
    mesh_error: str | None = None
    physical_groups: dict[str, Any] = {}
    wall_group_tag: int | None = None
    symmetry_group_tag: int | None = None
    farfield_group_tag: int | None = None
    fluid_group_tag: int | None = None
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Geometry.ExtrudeReturnLateralEntities", 0)
        gmsh.option.setNumber("Mesh.Algorithm3D", 10)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber(
            "Mesh.MeshSizeMax",
            float(spec["farfield"]["outer_cell_size_chords"]) * float(geometry["chord_m"]),
        )
        gmsh.option.setNumber(
            "Mesh.MeshSizeMin",
            min(
                float(bl_spec["first_layer_height_m"]),
                float(spec["wake_refinement"]["near_wake_cell_size_chords"]) * float(geometry["chord_m"]),
                float(spec["tip_refinement"]["cell_size_chords"]) * float(geometry["chord_m"]),
            ),
        )
        gmsh.model.add(spec["route_name"])
        occ = gmsh.model.occ

        chord_m = float(geometry["chord_m"])
        half_span_m = float(geometry["half_span_m"])
        if real_wing_geometry is None:
            profile_points = _naca0012_points(int(geometry["airfoil_loop_points"]), chord_m)
            occ_points = [occ.addPoint(x, 0.0, z) for x, z in profile_points]
            split_idx = len(profile_points) // 2
            upper_curve = occ.addSpline(occ_points[: split_idx + 1])
            lower_curve = occ.addSpline(occ_points[split_idx:])
            trailing_edge_curve = occ.addLine(occ_points[-1], occ_points[0])
            occ.extrude([(1, upper_curve), (1, lower_curve), (1, trailing_edge_curve)], 0.0, half_span_m, 0.0)
            occ.synchronize()

            tip_curves: list[int] = []
            for dim, tag in gmsh.model.getEntities(1):
                if dim != 1:
                    continue
                x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(dim, tag)
                if abs(y_min - half_span_m) < 1.0e-6 and abs(y_max - half_span_m) < 1.0e-6:
                    tip_curves.append(int(tag))
            tip_loop = occ.addCurveLoop(_order_curve_loop(gmsh, tip_curves))
            occ.addPlaneSurface([tip_loop])
            occ.synchronize()
            geometry_bounds = {
                "x_min": 0.0,
                "x_max": chord_m,
                "y_min": 0.0,
                "y_max": half_span_m,
                "z_min": -0.5 * chord_m * 0.12,
                "z_max": 0.5 * chord_m * 0.12,
            }
            tip_bounds = {
                "x_min": 0.0,
                "x_max": chord_m,
                "y_min": half_span_m,
                "y_max": half_span_m,
                "z_min": -0.5 * chord_m * 0.12,
                "z_max": 0.5 * chord_m * 0.12,
            }
        else:
            wall_surface_tags, _, loft_info = _build_real_main_wing_occ_shell(
                gmsh=gmsh,
                section_profiles=real_wing_geometry["section_profiles"],
            )
            geometry_bounds = dict(real_wing_geometry["overall_bounds"])
            tip_bounds = dict(real_wing_geometry["section_bounds"][-1])
            geometry["tip_surface_tag"] = int(loft_info["tip_surface_tag"])

        _set_shell_transfinite_controls(
            gmsh,
            chord_m=chord_m,
            half_span_m=half_span_m,
            airfoil_loop_points=int(geometry["airfoil_loop_points"]),
            half_span_stations=int(geometry["half_span_stations"]),
        )

        if real_wing_geometry is None:
            wall_surface_tags = [int(tag) for dim, tag in gmsh.model.getEntities(2) if dim == 2]
        cumulative_heights = _layer_cumulative_heights(
            float(bl_spec["first_layer_height_m"]),
            float(bl_spec["growth_ratio"]),
            int(bl_spec["layers"]),
        )
        extbl = gmsh.model.geo.extrudeBoundaryLayer(
            [(2, tag) for tag in wall_surface_tags],
            [1] * int(bl_spec["layers"]),
            cumulative_heights,
            True,
        )
        for index in range(1, len(extbl)):
            if extbl[index][0] == 3:
                bl_volume_tags.append(int(extbl[index][1]))
                bl_top_surface_tags.append(int(extbl[index - 1][1]))
        gmsh.model.geo.synchronize()

        hole_boundary = gmsh.model.getBoundary(
            [(2, tag) for tag in bl_top_surface_tags],
            combined=True,
            oriented=False,
            recursive=False,
        )
        hole_curves = _order_curve_loop(gmsh, [int(curve_tag) for dim, curve_tag in hole_boundary if dim == 1])
        z_center = 0.5 * (float(geometry_bounds["z_min"]) + float(geometry_bounds["z_max"]))
        x_min = float(geometry_bounds["x_min"]) - float(spec["farfield"]["upstream_chords"]) * chord_m
        x_max = float(geometry_bounds["x_max"]) + float(spec["farfield"]["downstream_chords"]) * chord_m
        y_min = 0.0
        y_max = float(geometry_bounds["y_max"]) + float(spec["farfield"]["normal_chords"]) * chord_m
        z_min = float(geometry_bounds["z_min"]) - float(spec["farfield"]["normal_chords"]) * chord_m
        z_max = float(geometry_bounds["z_max"]) + float(spec["farfield"]["normal_chords"]) * chord_m

        p1 = gmsh.model.geo.addPoint(x_min, y_min, z_min, chord_m)
        p2 = gmsh.model.geo.addPoint(x_max, y_min, z_min, chord_m)
        p3 = gmsh.model.geo.addPoint(x_max, y_max, z_min, chord_m)
        p4 = gmsh.model.geo.addPoint(x_min, y_max, z_min, chord_m)
        p5 = gmsh.model.geo.addPoint(x_min, y_min, z_max, chord_m)
        p6 = gmsh.model.geo.addPoint(x_max, y_min, z_max, chord_m)
        p7 = gmsh.model.geo.addPoint(x_max, y_max, z_max, chord_m)
        p8 = gmsh.model.geo.addPoint(x_min, y_max, z_max, chord_m)

        l1 = gmsh.model.geo.addLine(p1, p2)
        l2 = gmsh.model.geo.addLine(p2, p3)
        l3 = gmsh.model.geo.addLine(p3, p4)
        l4 = gmsh.model.geo.addLine(p4, p1)
        l5 = gmsh.model.geo.addLine(p5, p6)
        l6 = gmsh.model.geo.addLine(p6, p7)
        l7 = gmsh.model.geo.addLine(p7, p8)
        l8 = gmsh.model.geo.addLine(p8, p5)
        l9 = gmsh.model.geo.addLine(p1, p5)
        l10 = gmsh.model.geo.addLine(p2, p6)
        l11 = gmsh.model.geo.addLine(p3, p7)
        l12 = gmsh.model.geo.addLine(p4, p8)

        cl_hole = gmsh.model.geo.addCurveLoop(hole_curves)
        cl_sym = gmsh.model.geo.addCurveLoop([l1, l10, -l5, -l9])
        symmetry_surface_tag = gmsh.model.geo.addPlaneSurface([cl_sym, cl_hole])
        farfield_surface_tags = [
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l2, l11, -l6, -l10])]),
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l3, l12, -l7, -l11])]),
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l4, l9, -l8, -l12])]),
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l1, l2, l3, l4])]),
            gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l5, l6, l7, l8])]),
        ]
        fluid_volume_tag = gmsh.model.geo.addVolume(
            [
                gmsh.model.geo.addSurfaceLoop(
                    bl_top_surface_tags + [int(symmetry_surface_tag)] + farfield_surface_tags
                )
            ]
        )

        refinement_regions = {
            "wake_refinement_region": {
                "kind": "box_field",
                "x_min": float(geometry_bounds["x_max"]),
                "x_max": float(geometry_bounds["x_max"]) + float(spec["wake_refinement"]["wake_length_chords"]) * chord_m,
                "y_min": 0.0,
                "y_max": float(geometry_bounds["y_max"]),
                "z_min": z_center - float(spec["wake_refinement"]["wake_height_chords"]) * chord_m,
                "z_max": z_center + float(spec["wake_refinement"]["wake_height_chords"]) * chord_m,
                "target_cell_size_m": float(spec["wake_refinement"]["near_wake_cell_size_chords"]) * chord_m,
            },
            "tip_refinement_region": {
                "kind": "box_field",
                "x_min": float(tip_bounds["x_min"]) - 0.05 * chord_m,
                "x_max": float(tip_bounds["x_max"]),
                "y_min": max(0.0, float(geometry_bounds["y_max"]) - float(spec["tip_refinement"]["spanwise_length_chords"]) * chord_m),
                "y_max": float(geometry_bounds["y_max"]),
                "z_min": float(tip_bounds["z_min"]) - 1.0 * chord_m,
                "z_max": float(tip_bounds["z_max"]) + 1.0 * chord_m,
                "target_cell_size_m": float(spec["tip_refinement"]["cell_size_chords"]) * chord_m,
            },
        }
        off_wall_growth = spec.get("off_wall_growth", {})
        outer_cell_size_m = float(spec["farfield"]["outer_cell_size_chords"]) * chord_m
        if bool(off_wall_growth.get("enabled")):
            refinement_regions["off_wall_growth_region"] = {
                "kind": "surface_distance_threshold",
                "support_cell_size_m": float(off_wall_growth["support_cell_size_chords"]) * chord_m,
                "outer_cell_size_m": outer_cell_size_m,
                "support_dist_min_m": float(off_wall_growth["support_dist_min_chords"]) * chord_m,
                "support_dist_max_m": float(off_wall_growth["support_dist_max_chords"]) * chord_m,
                "stop_at_dist_max": bool(off_wall_growth.get("stop_at_dist_max", True)),
            }

        wake_field = gmsh.model.mesh.field.add("Box")
        gmsh.model.mesh.field.setNumber(wake_field, "VIn", refinement_regions["wake_refinement_region"]["target_cell_size_m"])
        gmsh.model.mesh.field.setNumber(wake_field, "VOut", outer_cell_size_m)
        gmsh.model.mesh.field.setNumber(wake_field, "XMin", refinement_regions["wake_refinement_region"]["x_min"])
        gmsh.model.mesh.field.setNumber(wake_field, "XMax", refinement_regions["wake_refinement_region"]["x_max"])
        gmsh.model.mesh.field.setNumber(wake_field, "YMin", refinement_regions["wake_refinement_region"]["y_min"])
        gmsh.model.mesh.field.setNumber(wake_field, "YMax", refinement_regions["wake_refinement_region"]["y_max"])
        gmsh.model.mesh.field.setNumber(wake_field, "ZMin", refinement_regions["wake_refinement_region"]["z_min"])
        gmsh.model.mesh.field.setNumber(wake_field, "ZMax", refinement_regions["wake_refinement_region"]["z_max"])

        tip_field = gmsh.model.mesh.field.add("Box")
        gmsh.model.mesh.field.setNumber(tip_field, "VIn", refinement_regions["tip_refinement_region"]["target_cell_size_m"])
        gmsh.model.mesh.field.setNumber(tip_field, "VOut", outer_cell_size_m)
        gmsh.model.mesh.field.setNumber(tip_field, "XMin", refinement_regions["tip_refinement_region"]["x_min"])
        gmsh.model.mesh.field.setNumber(tip_field, "XMax", refinement_regions["tip_refinement_region"]["x_max"])
        gmsh.model.mesh.field.setNumber(tip_field, "YMin", refinement_regions["tip_refinement_region"]["y_min"])
        gmsh.model.mesh.field.setNumber(tip_field, "YMax", refinement_regions["tip_refinement_region"]["y_max"])
        gmsh.model.mesh.field.setNumber(tip_field, "ZMin", refinement_regions["tip_refinement_region"]["z_min"])
        gmsh.model.mesh.field.setNumber(tip_field, "ZMax", refinement_regions["tip_refinement_region"]["z_max"])

        fields_list = [wake_field, tip_field]
        if bool(off_wall_growth.get("enabled")):
            support_distance_field = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(support_distance_field, "FacesList", bl_top_surface_tags)

            support_threshold_field = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(support_threshold_field, "InField", support_distance_field)
            gmsh.model.mesh.field.setNumber(
                support_threshold_field,
                "SizeMin",
                refinement_regions["off_wall_growth_region"]["support_cell_size_m"],
            )
            gmsh.model.mesh.field.setNumber(
                support_threshold_field,
                "SizeMax",
                refinement_regions["off_wall_growth_region"]["outer_cell_size_m"],
            )
            gmsh.model.mesh.field.setNumber(
                support_threshold_field,
                "DistMin",
                refinement_regions["off_wall_growth_region"]["support_dist_min_m"],
            )
            gmsh.model.mesh.field.setNumber(
                support_threshold_field,
                "DistMax",
                refinement_regions["off_wall_growth_region"]["support_dist_max_m"],
            )
            gmsh.model.mesh.field.setNumber(
                support_threshold_field,
                "StopAtDistMax",
                1.0 if refinement_regions["off_wall_growth_region"]["stop_at_dist_max"] else 0.0,
            )
            fields_list.append(support_threshold_field)

        minimum_field = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(minimum_field, "FieldsList", fields_list)
        gmsh.model.mesh.field.setAsBackgroundMesh(minimum_field)
        gmsh.model.geo.synchronize()

        wall_group_tag = gmsh.model.addPhysicalGroup(2, wall_surface_tags)
        gmsh.model.setPhysicalName(2, wall_group_tag, "wing_wall")
        symmetry_group_tag = gmsh.model.addPhysicalGroup(2, [int(symmetry_surface_tag)])
        gmsh.model.setPhysicalName(2, symmetry_group_tag, "symmetry")
        farfield_group_tag = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
        gmsh.model.setPhysicalName(2, farfield_group_tag, "farfield")
        fluid_group_tag = gmsh.model.addPhysicalGroup(3, [int(fluid_volume_tag), *bl_volume_tags])
        gmsh.model.setPhysicalName(3, fluid_group_tag, "fluid")

        gmsh.model.mesh.generate(3)
        gmsh.write(str(mesh_path))
        gmsh.write(str(mesh_dir / "mesh.su2"))
        node_tags, _, _ = gmsh.model.mesh.getNodes()
        total_nodes = int(len(node_tags))
        element_types, element_tags, _ = gmsh.model.mesh.getElements(3)
        total_cells = sum(len(tags) for tags in element_tags)
        volume_element_type_counts = _element_type_counts(element_types, element_tags)
        all_surface_types, all_surface_tags, _ = gmsh.model.mesh.getElements(2)
        surface_element_count = sum(len(tags) for tags in all_surface_tags)
        surface_element_type_counts = _element_type_counts(all_surface_types, all_surface_tags)
        wall_face_count, wall_element_type_counts = _count_elements_for_entities(gmsh, 2, wall_surface_tags)
        if symmetry_surface_tag is not None:
            symmetry_face_count, _ = _count_elements_for_entities(gmsh, 2, [int(symmetry_surface_tag)])
        farfield_face_count, _ = _count_elements_for_entities(gmsh, 2, farfield_surface_tags)
        bl_cell_count, bl_cell_type_counts = _count_elements_for_entities(gmsh, 3, bl_volume_tags)

        volume_element_tags = [int(tag) for tags in element_tags for tag in tags]
        if volume_element_tags:
            quality_metrics = {
                "min_sicn": _quality_stats(list(gmsh.model.mesh.getElementQualities(volume_element_tags, "minSICN"))),
                "min_sige": _quality_stats(list(gmsh.model.mesh.getElementQualities(volume_element_tags, "minSIGE"))),
                "gamma": _quality_stats(list(gmsh.model.mesh.getElementQualities(volume_element_tags, "gamma"))),
                "volume": _quality_stats(list(gmsh.model.mesh.getElementQualities(volume_element_tags, "volume"))),
            }
        write_json_report(field_region_path, refinement_regions)
        write_json_report(quality_path, quality_metrics)
    except Exception as exc:
        mesh_error = str(exc)
    finally:
        gmsh.finalize()

    boundary_layer_total_thickness = float(bl_spec["target_total_thickness_m"])
    y_plus_estimate = estimate_first_cell_yplus_range(
        velocity_mps=float(flow["velocity_mps"]),
        density_kgpm3=float(flow["density_kgpm3"]),
        dynamic_viscosity_pas=float(flow["dynamic_viscosity_pas"]),
        ref_length_m=float(reference_values["ref_length"]),
        first_layer_height_m=float(bl_spec["first_layer_height_m"]),
    )
    average_achieved_layers = float(bl_cell_count / wall_face_count) if wall_face_count > 0 else 0.0
    achieved_layers = max(0, int(round(average_achieved_layers)))
    collapse_rate = 1.0
    if wall_face_count > 0 and int(bl_spec["layers"]) > 0:
        expected_bl_cells = wall_face_count * int(bl_spec["layers"])
        collapse_rate = max(0.0, 1.0 - float(bl_cell_count) / float(expected_bl_cells))
    volume_to_wall_ratio = float(total_cells / wall_face_count) if wall_face_count > 0 else 0.0

    physical_groups = {
        "wing_wall": _physical_group_summary(
            physical_tag=wall_group_tag,
            physical_name="wing_wall",
            dimension=2,
            entity_count=len(wall_surface_tags),
            element_count=wall_face_count,
        ),
        "symmetry": _physical_group_summary(
            physical_tag=symmetry_group_tag,
            physical_name="symmetry",
            dimension=2,
            entity_count=1 if symmetry_surface_tag is not None else 0,
            element_count=symmetry_face_count,
        ),
        "farfield": _physical_group_summary(
            physical_tag=farfield_group_tag,
            physical_name="farfield",
            dimension=2,
            entity_count=len(farfield_surface_tags),
            element_count=farfield_face_count,
        ),
        "wake_refinement_region": _physical_group_summary(
            physical_tag=None,
            physical_name="wake_refinement_region",
            dimension=3,
            entity_count=1,
            element_count=0,
            virtual=True,
            notes=["Represented as an explicit Box field region instead of an internal physical partition to preserve route robustness on Mac-safe meshes."],
        ),
        "tip_refinement_region": _physical_group_summary(
            physical_tag=None,
            physical_name="tip_refinement_region",
            dimension=3,
            entity_count=1,
            element_count=0,
            virtual=True,
            notes=["Represented as an explicit Box field region instead of an internal physical partition to preserve route robustness on Mac-safe meshes."],
        ),
    }
    estimated_ram_gb = _solver_memory_estimate_gb(
        total_nodes=total_nodes,
        total_cells=total_cells,
        solver=spec["solver"],
    )
    memory_estimate = {
        "estimated_ram_gb": estimated_ram_gb,
        **_memory_classification(estimated_ram_gb),
    }

    mesh_gate_ok = (
        mesh_error is None
        and total_cells > 0
        and total_cells <= int(cell_budget["hard_fail_total_cells"])
        and collapse_rate <= float(cell_budget["max_bl_collapse_rate"])
        and volume_to_wall_ratio >= float(cell_budget["min_volume_to_wall_ratio"])
    )
    status = "success" if mesh_gate_ok else "failed"
    failure_reasons = []
    if mesh_error is not None:
        failure_reasons.append(mesh_error)
    if total_cells > int(cell_budget["hard_fail_total_cells"]):
        failure_reasons.append("total_cells_exceeded_hard_limit")
    if collapse_rate > float(cell_budget["max_bl_collapse_rate"]):
        failure_reasons.append("boundary_layer_collapse_rate_exceeded")
    if volume_to_wall_ratio < float(cell_budget["min_volume_to_wall_ratio"]):
        failure_reasons.append("volume_to_wall_ratio_below_limit")
    if boundary_layer_total_thickness < 0.035 or boundary_layer_total_thickness > 0.05:
        failure_reasons.append("boundary_layer_total_thickness_outside_target_band")
        status = "failed"

    solver_result = _run_solver_if_allowed(
        spec=spec,
        mesh_path=mesh_path,
        case_dir=su2_dir / spec["study_level"],
        estimated_ram=memory_estimate,
        run_su2=run_su2 and mesh_gate_ok,
        allow_swap_risk=allow_swap_risk,
    )
    y_plus_actual = solver_result.get("y_plus")
    if y_plus_actual is not None:
        y_plus_report = y_plus_actual
    else:
        y_plus_report = {
            "source": "estimated_case_conditions",
            "min": y_plus_estimate["y_plus_min"],
            "mean": 0.5 * (y_plus_estimate["y_plus_min"] + y_plus_estimate["y_plus_max"]),
            "max": y_plus_estimate["y_plus_max"],
        }

    result_class, comparable, interpretation_note = _solver_result_class(
        mesh_gate_ok=mesh_gate_ok,
        solver_status=str(solver_result.get("run_status", "not_started")),
        final_iteration=solver_result.get("final_iteration"),
        residual_behavior=solver_result.get("residual_behavior", {}),
        cauchy_status=solver_result.get("cauchy_cl", {}),
        force_variation=solver_result.get("force_variation_last_200", {}),
    )

    mesh_summary = {
        "route_stage": "baseline",
        "backend": "gmsh",
        "meshing_route": DEFAULT_ROUTE_NAME,
        "mesh_artifact": str(mesh_path),
        "mesh_metadata_path": str(mesh_metadata_path),
        "mesh_quality_path": str(quality_path),
        "refinement_regions_path": str(field_region_path),
        "physical_groups": physical_groups,
        "total_cells": int(total_cells),
        "total_nodes": int(total_nodes),
        "surface_face_count": int(surface_element_count),
        "wall_face_count": int(wall_face_count),
        "volume_to_wall_ratio": float(volume_to_wall_ratio),
        "surface_element_type_counts": surface_element_type_counts,
        "wall_element_type_counts": wall_element_type_counts,
        "volume_element_type_counts": volume_element_type_counts,
    }

    result = {
        "status": status,
        "failure_code": None if status == "success" else "mesh_route_validation_failed",
        "route_name": DEFAULT_ROUTE_NAME,
        "study_level": spec["study_level"],
        "geometry": geometry,
        "reference_values": reference_values,
        "flow_condition": flow,
        "mesh": mesh_summary,
        "boundary_layer": {
            "first_layer_height_m": float(bl_spec["first_layer_height_m"]),
            "growth_ratio": float(bl_spec["growth_ratio"]),
            "requested_layers": int(bl_spec["layers"]),
            "achieved_layers": int(achieved_layers),
            "boundary_layer_cell_count": int(bl_cell_count),
            "boundary_layer_cell_type_counts": bl_cell_type_counts,
            "target_total_thickness_m": float(boundary_layer_total_thickness),
            "collapse_rate": float(collapse_rate),
            "pass": collapse_rate <= float(cell_budget["max_bl_collapse_rate"]),
            "estimated_first_cell_yplus_range": {
                "min": y_plus_estimate["y_plus_min"],
                "max": y_plus_estimate["y_plus_max"],
            },
        },
        "mesh_quality": quality_metrics,
        "memory_estimate": memory_estimate,
        "solver": solver_result,
        "comparability": {
            "result_class": result_class,
            "comparable": comparable,
            "interpretation_note": interpretation_note,
            "last_200_force_variation": solver_result.get("force_variation_last_200", {}),
            "residual_behavior": solver_result.get("residual_behavior", {}),
            "cauchy_cl": solver_result.get("cauchy_cl", {}),
        },
        "y_plus": y_plus_report,
        "notes": [
            "This route is tuned for Mac-safe validation on a 16 GB Mac mini, not as a final production mesh.",
            "wake_refinement_region and tip_refinement_region are carried as explicit named refinement fields rather than internal physical partitions to preserve meshing robustness.",
            interpretation_note,
        ],
    }
    if failure_reasons:
        result["notes"].extend(failure_reasons)
        result["error"] = "; ".join(failure_reasons)

    result["case_summary"] = {
        "total_cells": int(total_cells),
        "total_nodes": int(total_nodes),
        "surface_face_count": int(surface_element_count),
        "wall_face_count": int(wall_face_count),
        "requested_bl_layers": int(bl_spec["layers"]),
        "achieved_bl_layers": int(achieved_layers),
        "bl_collapse_rate": float(collapse_rate),
        "runtime_seconds": float(time.perf_counter() - route_started),
        "solver_status": solver_result.get("status"),
        "memory_estimate": memory_estimate,
        "parallel_mode": solver_result.get("parallel_mode"),
        "mpi_ranks": solver_result.get("mpi_ranks"),
        "omp_threads_per_rank": solver_result.get("omp_threads_per_rank"),
        "geometry_shape_mode": geometry_shape_mode,
        "comparability_classification": result_class,
        "reference_values_used": reference_values,
        "route_note": interpretation_note,
    }
    if geometry_shape_mode == DEFAULT_REAL_MAIN_WING_SHAPE_MODE:
        result["notes"].append(
            "Geometry used provider-extracted real main wing sections from the configured .vsp3 source instead of the NACA0012 surrogate."
        )

    write_json_report(mesh_metadata_path, result)
    write_json_report(out_dir / "report.json", result)
    write_markdown_report(out_dir / "report.md", result)
    return result
