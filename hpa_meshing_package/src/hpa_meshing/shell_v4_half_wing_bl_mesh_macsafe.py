from __future__ import annotations

import bisect
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
ROOT_CLOSURE_MODE_SINGLE_HOLED_SYMMETRY_FACE = "single_holed_symmetry_face"
ROOT_CLOSURE_MODE_USE_BL_GENERATED_FACES = "use_bl_generated_faces"

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
            "root_closure_mode": ROOT_CLOSURE_MODE_SINGLE_HOLED_SYMMETRY_FACE,
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
        "real_wing_bl_protection": {
            "enabled": True,
            "outboard_activation_local_chords": 2.5,
            "max_total_to_half_thickness_fraction": 0.85,
            "tip_zone_chords": 0.75,
            "tip_scale_at_tip": 0.8,
            "thickness_limit_x_rel_min": 0.05,
            "thickness_limit_x_rel_max": 0.92,
            "min_local_scale": 0.05,
            "exclude_tip_cap_from_bl": False,
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
            "root_closure_mode": ROOT_CLOSURE_MODE_SINGLE_HOLED_SYMMETRY_FACE,
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
        "real_wing_bl_protection": {
            "enabled": True,
            "outboard_activation_local_chords": 2.5,
            "max_total_to_half_thickness_fraction": 0.85,
            "tip_zone_chords": 0.75,
            "tip_scale_at_tip": 0.8,
            "thickness_limit_x_rel_min": 0.05,
            "thickness_limit_x_rel_max": 0.92,
            "min_local_scale": 0.05,
            "exclude_tip_cap_from_bl": False,
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


def _geometry_root_closure_mode(
    geometry: dict[str, Any],
    *,
    geometry_shape_mode: str,
) -> str:
    configured = str(geometry.get("root_closure_mode") or "").strip()
    if geometry_shape_mode == DEFAULT_REAL_MAIN_WING_SHAPE_MODE:
        if configured == ROOT_CLOSURE_MODE_USE_BL_GENERATED_FACES:
            return configured
        return ROOT_CLOSURE_MODE_USE_BL_GENERATED_FACES
    if configured:
        return configured
    return ROOT_CLOSURE_MODE_SINGLE_HOLED_SYMMETRY_FACE


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


def _section_airfoil_coordinates(section: dict[str, Any]) -> list[tuple[float, float]]:
    coordinates = [
        (float(x_value), float(z_value))
        for x_value, z_value in (section.get("airfoil_coordinates") or [])
    ]
    if len(coordinates) >= 2 and all(
        abs(lhs - rhs) <= 1.0e-12 for lhs, rhs in zip(coordinates[0], coordinates[-1])
    ):
        coordinates = coordinates[:-1]
    if len(coordinates) < 4:
        raise ValueError("real main wing section needs at least four airfoil coordinates")
    return coordinates


def _leading_edge_index_2d(points: list[tuple[float, float]]) -> int:
    if len(points) < 3:
        raise ValueError("airfoil loop needs at least three points")
    return min(range(len(points)), key=lambda index: (points[index][0], abs(points[index][1])))


def _monotonic_branch(
    points: list[tuple[float, float]],
    *,
    take_max: bool,
) -> list[tuple[float, float]]:
    ordered = sorted((float(x), float(z)) for x, z in points)
    merged: list[tuple[float, float]] = []
    for x_value, z_value in ordered:
        if merged and abs(x_value - merged[-1][0]) <= 1.0e-12:
            previous_x, previous_z = merged[-1]
            merged[-1] = (
                previous_x,
                max(previous_z, z_value) if take_max else min(previous_z, z_value),
            )
        else:
            merged.append((x_value, z_value))
    if len(merged) < 2:
        raise ValueError("airfoil branch needs at least two monotonic points")
    return merged


def _section_thickness_branches(section: dict[str, Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    coordinates = _section_airfoil_coordinates(section)
    leading_edge_index = _leading_edge_index_2d(coordinates)
    upper = _monotonic_branch(list(reversed(coordinates[: leading_edge_index + 1])), take_max=True)
    lower = _monotonic_branch(coordinates[leading_edge_index:], take_max=False)
    return upper, lower


def _interpolate_branch(branch: list[tuple[float, float]], x_value: float) -> float:
    if x_value <= branch[0][0]:
        return float(branch[0][1])
    if x_value >= branch[-1][0]:
        return float(branch[-1][1])
    xs = [point[0] for point in branch]
    index = max(0, min(len(xs) - 2, bisect.bisect_right(xs, x_value) - 1))
    x0, z0 = branch[index]
    x1, z1 = branch[index + 1]
    if abs(x1 - x0) <= 1.0e-12:
        return float(0.5 * (z0 + z1))
    ratio = float((x_value - x0) / (x1 - x0))
    return float(z0 + ratio * (z1 - z0))


def _section_local_thickness_at_x(section: dict[str, Any], x_rel: float) -> float:
    upper, lower = _section_thickness_branches(section)
    x_clamped = float(max(upper[0][0], min(upper[-1][0], x_rel)))
    z_upper = _interpolate_branch(upper, x_clamped)
    z_lower = _interpolate_branch(lower, x_clamped)
    return max(0.0, float(z_upper - z_lower) * float(section["chord"]))


def _section_frame_parameters(section: dict[str, Any]) -> dict[str, float]:
    return {
        "x_le": float(section["x_le"]),
        "y_le": float(section["y_le"]),
        "z_le": float(section["z_le"]),
        "chord": float(section["chord"]),
        "twist_deg": float(section.get("twist_deg", 0.0) or 0.0),
    }


def _inverse_rotate_about_local_span(
    point: tuple[float, float, float],
    twist_deg: float,
) -> tuple[float, float, float]:
    angle = math.radians(float(twist_deg))
    x, y, z = (float(value) for value in point)
    return (
        x * math.cos(angle) + z * math.sin(angle),
        y,
        -x * math.sin(angle) + z * math.cos(angle),
    )


def _local_section_coordinates_for_point(
    section: dict[str, Any],
    point_xyz: tuple[float, float, float],
) -> tuple[float, float]:
    frame = _section_frame_parameters(section)
    local_x, _, local_z = _inverse_rotate_about_local_span(
        (
            float(point_xyz[0]) - frame["x_le"],
            0.0,
            float(point_xyz[2]) - frame["z_le"],
        ),
        frame["twist_deg"],
    )
    chord = max(frame["chord"], 1.0e-12)
    return float(local_x / chord), float(local_z / chord)


def _interpolate_between_sections(
    lower_value: float,
    upper_value: float,
    ratio: float,
) -> float:
    return float((1.0 - ratio) * lower_value + ratio * upper_value)


def _bracketing_section_indices(
    sections: list[dict[str, Any]],
    y_value: float,
) -> tuple[int, int, float]:
    if len(sections) < 2:
        return 0, 0, 0.0
    y_sections = [float(section["y_le"]) for section in sections]
    if y_value <= y_sections[0]:
        return 0, 0, 0.0
    if y_value >= y_sections[-1]:
        last_index = len(sections) - 1
        return last_index, last_index, 0.0
    lower_index = max(0, min(len(y_sections) - 2, bisect.bisect_right(y_sections, y_value) - 1))
    upper_index = lower_index + 1
    y0 = y_sections[lower_index]
    y1 = y_sections[upper_index]
    if abs(y1 - y0) <= 1.0e-12:
        return lower_index, upper_index, 0.0
    return lower_index, upper_index, float((y_value - y0) / (y1 - y0))


def _real_wing_local_clearance_at_point(
    *,
    sections: list[dict[str, Any]],
    point_xyz: tuple[float, float, float],
) -> dict[str, float]:
    lower_index, upper_index, ratio = _bracketing_section_indices(sections, float(point_xyz[1]))
    lower_section = sections[lower_index]
    upper_section = sections[upper_index]
    lower_x_rel, _ = _local_section_coordinates_for_point(lower_section, point_xyz)
    upper_x_rel, _ = _local_section_coordinates_for_point(upper_section, point_xyz)
    lower_thickness = _section_local_thickness_at_x(lower_section, lower_x_rel)
    upper_thickness = _section_local_thickness_at_x(upper_section, upper_x_rel)
    if lower_index == upper_index:
        thickness = lower_thickness
    else:
        thickness = _interpolate_between_sections(lower_thickness, upper_thickness, ratio)
    frame = {
        key: _interpolate_between_sections(
            _section_frame_parameters(lower_section)[key],
            _section_frame_parameters(upper_section)[key],
            ratio,
        )
        for key in ("x_le", "y_le", "z_le", "chord", "twist_deg")
    }
    local_x, _ = _local_section_coordinates_for_point(
        {
            **lower_section,
            **frame,
        },
        point_xyz,
    )
    return {
        "local_thickness_m": float(max(0.0, thickness)),
        "local_half_thickness_m": float(max(0.0, 0.5 * thickness)),
        "local_x_rel": float(local_x),
        "local_chord_m": float(frame["chord"]),
        "span_y_m": float(point_xyz[1]),
    }


def _build_real_wing_bl_protection_field(
    *,
    gmsh: Any,
    wall_surface_tags: list[int],
    sections: list[dict[str, Any]],
    protection: dict[str, Any],
    base_total_thickness_m: float,
    ref_chord_m: float,
    half_span_m: float,
) -> dict[str, Any] | None:
    if not bool(protection.get("enabled", True)):
        return None
    outboard_activation_local_chords = float(protection["outboard_activation_local_chords"])
    node_payloads: dict[int, dict[str, float]] = {}
    for surface_tag in wall_surface_tags:
        node_tags, coordinates, _ = gmsh.model.mesh.getNodes(
            2,
            int(surface_tag),
            includeBoundary=True,
            returnParametricCoord=False,
        )
        for node_index, node_tag in enumerate(node_tags):
            node_key = int(node_tag)
            if node_key in node_payloads:
                continue
            xyz = (
                float(coordinates[3 * node_index]),
                float(coordinates[3 * node_index + 1]),
                float(coordinates[3 * node_index + 2]),
            )
            clearance = _real_wing_local_clearance_at_point(sections=sections, point_xyz=xyz)
            local_half_thickness = max(clearance["local_half_thickness_m"], 1.0e-9)
            local_chord_m = max(clearance["local_chord_m"], 1.0e-9)
            tip_distance_m = max(0.0, float(half_span_m) - xyz[1])
            outboard_activation_span_m = max(0.0, outboard_activation_local_chords * local_chord_m)
            outboard_activated = tip_distance_m <= outboard_activation_span_m + 1.0e-12
            x_rel_min = float(protection["thickness_limit_x_rel_min"])
            x_rel_max = float(protection["thickness_limit_x_rel_max"])
            within_thickness_window = x_rel_min <= clearance["local_x_rel"] <= x_rel_max
            thickness_limit_active = within_thickness_window and outboard_activated
            allowed_from_thickness = float(base_total_thickness_m)
            if thickness_limit_active:
                allowed_from_thickness = (
                    float(protection["max_total_to_half_thickness_fraction"]) * local_half_thickness
                )
            tip_zone_span_m = max(1.0e-9, float(protection["tip_zone_chords"]) * local_chord_m)
            tip_progress = 0.0
            tip_scale = 1.0
            if tip_distance_m < tip_zone_span_m:
                tip_progress = float(1.0 - tip_distance_m / tip_zone_span_m)
                tip_scale = _interpolate_between_sections(
                    1.0,
                    float(protection["tip_scale_at_tip"]),
                    tip_progress,
                )
            allowed_total_thickness = min(
                float(base_total_thickness_m),
                float(allowed_from_thickness * tip_scale),
            )
            raw_scale = float(allowed_total_thickness / max(base_total_thickness_m, 1.0e-12))
            scale = float(max(float(protection["min_local_scale"]), min(1.0, raw_scale)))
            node_payloads[node_key] = {
                "x": xyz[0],
                "y": xyz[1],
                "z": xyz[2],
                "local_thickness_m": float(clearance["local_thickness_m"]),
                "local_half_thickness_m": float(clearance["local_half_thickness_m"]),
                "local_x_rel": float(clearance["local_x_rel"]),
                "local_chord_m": float(local_chord_m),
                "tip_distance_m": float(tip_distance_m),
                "outboard_activation_span_m": float(outboard_activation_span_m),
                "allowed_total_thickness_m": float(allowed_total_thickness),
                "scale": scale,
                "tip_progress": float(tip_progress),
                "thickness_window_active": 1.0 if within_thickness_window else 0.0,
                "outboard_activated": 1.0 if outboard_activated else 0.0,
                "thickness_limit_active": 1.0 if thickness_limit_active else 0.0,
                "thickness_limited": 1.0
                if thickness_limit_active and allowed_from_thickness < base_total_thickness_m - 1.0e-12
                else 0.0,
                "tip_limited": 1.0 if tip_progress > 0.0 else 0.0,
            }
    if not node_payloads:
        return None
    view_tag = gmsh.view.add("real_wing_bl_protection_scale")
    node_tags = list(node_payloads.keys())
    gmsh.view.addModelData(
        view_tag,
        0,
        gmsh.model.getCurrent(),
        "NodeData",
        node_tags,
        [[node_payloads[node_tag]["scale"]] for node_tag in node_tags],
        numComponents=1,
    )
    triggered_nodes = [payload for payload in node_payloads.values() if payload["scale"] < 0.999999]
    summary = {
        "enabled": True,
        "mode": "local_thickness_scaled_boundary_layer",
        "view_tag": int(view_tag),
        "view_index": int(gmsh.view.getIndex(view_tag)),
        "base_total_thickness_m": float(base_total_thickness_m),
        "outboard_activation_local_chords": float(outboard_activation_local_chords),
        "max_total_to_half_thickness_fraction": float(protection["max_total_to_half_thickness_fraction"]),
        "tip_zone_chords": float(protection["tip_zone_chords"]),
        "tip_scale_at_tip": float(protection["tip_scale_at_tip"]),
        "thickness_limit_x_rel_min": float(protection["thickness_limit_x_rel_min"]),
        "thickness_limit_x_rel_max": float(protection["thickness_limit_x_rel_max"]),
        "min_local_scale": float(protection["min_local_scale"]),
        "layer_count_preserved": True,
        "thickness_scaled_locally": True,
        "node_count": int(len(node_payloads)),
        "triggered_node_count": int(len(triggered_nodes)),
        "triggered_node_fraction": float(len(triggered_nodes) / max(len(node_payloads), 1)),
        "scale_min": float(min(payload["scale"] for payload in node_payloads.values())),
        "scale_max": float(max(payload["scale"] for payload in node_payloads.values())),
        "scale_mean": float(statistics.fmean(payload["scale"] for payload in node_payloads.values())),
        "outboard_activated_node_count": int(sum(int(payload["outboard_activated"]) for payload in node_payloads.values())),
        "thickness_window_node_count": int(sum(int(payload["thickness_window_active"]) for payload in node_payloads.values())),
        "thickness_limit_active_node_count": int(sum(int(payload["thickness_limit_active"]) for payload in node_payloads.values())),
        "thickness_limited_node_count": int(sum(int(payload["thickness_limited"]) for payload in triggered_nodes)),
        "tip_limited_node_count": int(sum(int(payload["tip_limited"]) for payload in triggered_nodes)),
    }
    if triggered_nodes:
        summary["triggered_span_y_range_m"] = {
            "min": float(min(payload["y"] for payload in triggered_nodes)),
            "max": float(max(payload["y"] for payload in triggered_nodes)),
        }
        summary["triggered_x_rel_range"] = {
            "min": float(min(payload["local_x_rel"] for payload in triggered_nodes)),
            "max": float(max(payload["local_x_rel"] for payload in triggered_nodes)),
        }
        summary["triggered_allowed_total_thickness_m"] = {
            "min": float(min(payload["allowed_total_thickness_m"] for payload in triggered_nodes)),
            "max": float(max(payload["allowed_total_thickness_m"] for payload in triggered_nodes)),
            "mean": float(statistics.fmean(payload["allowed_total_thickness_m"] for payload in triggered_nodes)),
        }
        summary["triggered_scale_range"] = {
            "min": float(min(payload["scale"] for payload in triggered_nodes)),
            "max": float(max(payload["scale"] for payload in triggered_nodes)),
            "mean": float(statistics.fmean(payload["scale"] for payload in triggered_nodes)),
        }
        summary["triggered_tip_distance_range_m"] = {
            "min": float(min(payload["tip_distance_m"] for payload in triggered_nodes)),
            "max": float(max(payload["tip_distance_m"] for payload in triggered_nodes)),
        }
        summary["triggered_local_chord_range_m"] = {
            "min": float(min(payload["local_chord_m"] for payload in triggered_nodes)),
            "max": float(max(payload["local_chord_m"] for payload in triggered_nodes)),
        }
    return summary


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


def _signed_curve_endpoint_tags(gmsh: Any, signed_curve_tag: int) -> tuple[int, int]:
    start_tag, end_tag = _curve_endpoint_tags(gmsh, abs(int(signed_curve_tag)))
    if int(signed_curve_tag) < 0:
        return end_tag, start_tag
    return start_tag, end_tag


def _point_xyz(gmsh: Any, point_tag: int) -> tuple[float, float, float]:
    values = gmsh.model.getValue(0, int(point_tag), [])
    if len(values) != 3:
        raise RuntimeError(f"point {point_tag} did not resolve to 3 coordinates")
    return (float(values[0]), float(values[1]), float(values[2]))


def _unique_preserve_order(values: Iterable[int]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for value in values:
        key = int(value)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _duplicate_curve_tags(curve_tags: Iterable[int]) -> list[int]:
    counts: dict[int, int] = {}
    duplicates: list[int] = []
    for curve_tag in curve_tags:
        key = abs(int(curve_tag))
        counts[key] = counts.get(key, 0) + 1
        if counts[key] == 2:
            duplicates.append(key)
    return duplicates


def _curve_length_proxy(gmsh: Any, curve_tag: int) -> float:
    start_tag, end_tag = _curve_endpoint_tags(gmsh, abs(int(curve_tag)))
    start_xyz = _point_xyz(gmsh, start_tag)
    end_xyz = _point_xyz(gmsh, end_tag)
    return float(
        math.hypot(end_xyz[0] - start_xyz[0], end_xyz[2] - start_xyz[2])
    )


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
        try:
            x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(dim, tag)
        except Exception:
            continue
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


def _sample_curve_polyline(
    gmsh: Any,
    signed_curve_tag: int,
    *,
    sample_count: int = 16,
) -> list[tuple[float, float, float]]:
    curve_tag = abs(int(signed_curve_tag))
    if sample_count < 2:
        sample_count = 2
    try:
        param_min, param_max = gmsh.model.getParametrizationBounds(1, curve_tag)
        u_start = float(param_min[0])
        u_end = float(param_max[0])
        params = [
            u_start + (u_end - u_start) * float(index) / float(sample_count - 1)
            for index in range(sample_count)
        ]
        points = [
            tuple(float(value) for value in gmsh.model.getValue(1, curve_tag, [param]))
            for param in params
        ]
    except Exception:
        start_tag, end_tag = _curve_endpoint_tags(gmsh, curve_tag)
        points = [_point_xyz(gmsh, start_tag), _point_xyz(gmsh, end_tag)]
    if int(signed_curve_tag) < 0:
        points.reverse()
    cleaned: list[tuple[float, float, float]] = []
    for point in points:
        if cleaned and math.dist(point, cleaned[-1]) <= 1.0e-10:
            continue
        cleaned.append(point)
    return cleaned


def _polyline_area_xz(points: list[tuple[float, float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        area += point[0] * next_point[2] - next_point[0] * point[2]
    return 0.5 * area


def _orientation_2d(
    lhs: tuple[float, float],
    rhs: tuple[float, float],
    other: tuple[float, float],
) -> float:
    return (rhs[0] - lhs[0]) * (other[1] - lhs[1]) - (rhs[1] - lhs[1]) * (other[0] - lhs[0])


def _on_segment_2d(
    lhs: tuple[float, float],
    rhs: tuple[float, float],
    other: tuple[float, float],
    *,
    tol: float = 1.0e-10,
) -> bool:
    return (
        min(lhs[0], rhs[0]) - tol <= other[0] <= max(lhs[0], rhs[0]) + tol
        and min(lhs[1], rhs[1]) - tol <= other[1] <= max(lhs[1], rhs[1]) + tol
    )


def _segments_intersect_xz(
    start_a: tuple[float, float, float],
    end_a: tuple[float, float, float],
    start_b: tuple[float, float, float],
    end_b: tuple[float, float, float],
) -> bool:
    a0 = (float(start_a[0]), float(start_a[2]))
    a1 = (float(end_a[0]), float(end_a[2]))
    b0 = (float(start_b[0]), float(start_b[2]))
    b1 = (float(end_b[0]), float(end_b[2]))
    if any(
        math.dist(lhs, rhs) <= 1.0e-10
        for lhs in (a0, a1)
        for rhs in (b0, b1)
    ):
        return False
    o1 = _orientation_2d(a0, a1, b0)
    o2 = _orientation_2d(a0, a1, b1)
    o3 = _orientation_2d(b0, b1, a0)
    o4 = _orientation_2d(b0, b1, a1)
    tol = 1.0e-10
    if (o1 > tol and o2 < -tol or o1 < -tol and o2 > tol) and (
        o3 > tol and o4 < -tol or o3 < -tol and o4 > tol
    ):
        return True
    if abs(o1) <= tol and _on_segment_2d(a0, a1, b0, tol=tol):
        return True
    if abs(o2) <= tol and _on_segment_2d(a0, a1, b1, tol=tol):
        return True
    if abs(o3) <= tol and _on_segment_2d(b0, b1, a0, tol=tol):
        return True
    if abs(o4) <= tol and _on_segment_2d(b0, b1, a1, tol=tol):
        return True
    return False


def _loop_self_intersections(points: list[tuple[float, float, float]]) -> list[tuple[int, int]]:
    if len(points) < 4:
        return []
    closed = list(points)
    if math.dist(closed[0], closed[-1]) > 1.0e-10:
        closed.append(closed[0])
    segment_count = len(closed) - 1
    intersections: list[tuple[int, int]] = []
    for first_index in range(segment_count):
        for second_index in range(first_index + 1, segment_count):
            if abs(first_index - second_index) <= 1:
                continue
            if first_index == 0 and second_index == segment_count - 1:
                continue
            if _segments_intersect_xz(
                closed[first_index],
                closed[first_index + 1],
                closed[second_index],
                closed[second_index + 1],
            ):
                intersections.append((first_index, second_index))
    return intersections


def _surface_lies_on_y_plane(gmsh: Any, surface_tag: int, *, y_value: float, tol: float = 1.0e-9) -> bool:
    boundary = gmsh.model.getBoundary([(2, int(surface_tag))], combined=False, oriented=False, recursive=False)
    point_tags: list[int] = []
    for dim, curve_tag in boundary:
        if dim != 1:
            continue
        point_tags.extend(point_tag for _, point_tag in gmsh.model.getBoundary([(1, int(curve_tag))], combined=False, oriented=False))
    if not point_tags:
        return False
    return all(abs(_point_xyz(gmsh, point_tag)[1] - y_value) <= tol for point_tag in point_tags)


def _collect_root_side_surface_tags(gmsh: Any, extbl: list[tuple[int, int]]) -> list[int]:
    root_surfaces: list[int] = []
    for dim, tag in extbl:
        if int(dim) != 2:
            continue
        surface_tag = int(tag)
        if surface_tag in root_surfaces:
            continue
        if _surface_lies_on_y_plane(gmsh, surface_tag, y_value=0.0):
            root_surfaces.append(surface_tag)
    return root_surfaces


def _cleanup_root_side_surface_mesh(
    gmsh: Any,
    surface_tags: list[int],
) -> dict[str, Any]:
    cleanup: dict[str, Any] = {
        "surface_tags": [int(tag) for tag in surface_tags],
        "removed_degenerate_element_count": 0,
        "removed_degenerate_elements_sample_limit": 40,
        "removed_degenerate_elements_sample": [],
        "removed_degenerate_element_count_by_surface": {},
    }
    if not surface_tags:
        return cleanup
    for surface_tag in surface_tags:
        element_types, element_tags_by_type, node_tags_by_type = gmsh.model.mesh.getElements(2, int(surface_tag))
        surface_remove_tags: list[int] = []
        for element_type, element_tags, node_tags in zip(
            element_types,
            element_tags_by_type,
            node_tags_by_type,
            strict=False,
        ):
            _, _, _, node_count, _, _ = gmsh.model.mesh.getElementProperties(int(element_type))
            node_count_int = int(node_count)
            if node_count_int <= 0:
                continue
            for element_index, element_tag in enumerate(element_tags):
                start = element_index * node_count_int
                stop = start + node_count_int
                element_node_tags = [int(node) for node in node_tags[start:stop]]
                if len(set(element_node_tags)) == len(element_node_tags):
                    continue
                surface_remove_tags.append(int(element_tag))
                cleanup["removed_degenerate_element_count_by_surface"][int(surface_tag)] = (
                    int(cleanup["removed_degenerate_element_count_by_surface"].get(int(surface_tag), 0)) + 1
                )
                if len(cleanup["removed_degenerate_elements_sample"]) < int(
                    cleanup["removed_degenerate_elements_sample_limit"]
                ):
                    cleanup["removed_degenerate_elements_sample"].append(
                        {
                            "surface_tag": int(surface_tag),
                            "element_type": int(element_type),
                            "element_tag": int(element_tag),
                            "node_tags": element_node_tags,
                        }
                    )
        if surface_remove_tags:
            gmsh.model.mesh.removeElements(2, int(surface_tag), surface_remove_tags)
            cleanup["removed_degenerate_element_count"] += len(surface_remove_tags)
    gmsh.model.mesh.removeDuplicateElements([(2, int(tag)) for tag in surface_tags])
    gmsh.model.mesh.removeDuplicateNodes([(2, int(tag)) for tag in surface_tags])
    gmsh.model.mesh.reclassifyNodes()
    return cleanup


def _root_opening_curve_tags(
    gmsh: Any,
    bl_top_surface_tags: list[int],
) -> tuple[list[int], list[int], list[int]]:
    hole_boundary = gmsh.model.getBoundary(
        [(2, tag) for tag in bl_top_surface_tags],
        combined=True,
        oriented=False,
        recursive=False,
    )
    raw_curve_tags = [int(curve_tag) for dim, curve_tag in hole_boundary if dim == 1]
    duplicate_curve_tags = _duplicate_curve_tags(raw_curve_tags)
    ordered_curve_tags = _order_curve_loop(gmsh, _unique_preserve_order(raw_curve_tags))
    return raw_curve_tags, duplicate_curve_tags, ordered_curve_tags


def _orient_curve_from_to(gmsh: Any, curve_tag: int, start_point_tag: int, end_point_tag: int) -> int:
    start_tag, end_tag = _curve_endpoint_tags(gmsh, int(curve_tag))
    if start_tag == int(start_point_tag) and end_tag == int(end_point_tag):
        return int(curve_tag)
    if start_tag == int(end_point_tag) and end_tag == int(start_point_tag):
        return -int(curve_tag)
    raise RuntimeError(
        f"curve {curve_tag} does not connect points {start_point_tag} and {end_point_tag}"
    )


def _classify_root_opening_curves(gmsh: Any, ordered_curve_tags: list[int]) -> dict[str, Any]:
    if len(ordered_curve_tags) != 3:
        raise RuntimeError("real-wing root opening currently expects exactly three ordered curves")
    te_curve_tag = min(
        (abs(curve_tag) for curve_tag in ordered_curve_tags),
        key=lambda curve_tag: _curve_length_proxy(gmsh, curve_tag),
    )
    long_curve_tags = [abs(curve_tag) for curve_tag in ordered_curve_tags if abs(curve_tag) != te_curve_tag]
    if len(long_curve_tags) != 2:
        raise RuntimeError("could not isolate the two long root-opening curves")
    first_endpoints = set(_curve_endpoint_tags(gmsh, long_curve_tags[0]))
    second_endpoints = set(_curve_endpoint_tags(gmsh, long_curve_tags[1]))
    shared_points = list(first_endpoints.intersection(second_endpoints))
    if len(shared_points) != 1:
        raise RuntimeError("real-wing root opening did not expose a unique leading-edge point")
    leading_edge_point = int(shared_points[0])
    long_curve_records: list[dict[str, Any]] = []
    for curve_tag in long_curve_tags:
        start_tag, end_tag = _curve_endpoint_tags(gmsh, curve_tag)
        te_point = end_tag if start_tag == leading_edge_point else start_tag
        long_curve_records.append(
            {
                "curve_tag": int(curve_tag),
                "te_point_tag": int(te_point),
                "te_point_xyz": _point_xyz(gmsh, int(te_point)),
            }
        )
    long_curve_records.sort(key=lambda record: (record["te_point_xyz"][2], record["te_point_xyz"][0]))
    lower_record = long_curve_records[0]
    upper_record = long_curve_records[-1]
    lower_curve_signed = _orient_curve_from_to(
        gmsh,
        lower_record["curve_tag"],
        leading_edge_point,
        lower_record["te_point_tag"],
    )
    upper_curve_signed = _orient_curve_from_to(
        gmsh,
        upper_record["curve_tag"],
        upper_record["te_point_tag"],
        leading_edge_point,
    )
    te_curve_signed = _orient_curve_from_to(
        gmsh,
        te_curve_tag,
        lower_record["te_point_tag"],
        upper_record["te_point_tag"],
    )
    return {
        "leading_edge_point_tag": leading_edge_point,
        "leading_edge_point_xyz": _point_xyz(gmsh, leading_edge_point),
        "upper_curve_signed": int(upper_curve_signed),
        "lower_curve_signed": int(lower_curve_signed),
        "te_curve_signed": int(te_curve_signed),
        "upper_te_point_tag": int(upper_record["te_point_tag"]),
        "upper_te_point_xyz": tuple(float(value) for value in upper_record["te_point_xyz"]),
        "lower_te_point_tag": int(lower_record["te_point_tag"]),
        "lower_te_point_xyz": tuple(float(value) for value in lower_record["te_point_xyz"]),
    }


def _build_real_wing_root_closure_plan(
    *,
    gmsh: Any,
    extbl: list[tuple[int, int]],
    bl_top_surface_tags: list[int],
    chord_m: float,
    bl_total_thickness_m: float,
    x_min: float,
    x_max: float,
    z_min: float,
    z_max: float,
) -> dict[str, Any]:
    root_side_surface_tags = _collect_root_side_surface_tags(gmsh, extbl)
    if not root_side_surface_tags:
        raise RuntimeError(
            "real-wing root closure did not receive any BL-generated root-side faces"
        )
    raw_curve_tags, duplicate_curve_tags, ordered_curve_tags = _root_opening_curve_tags(gmsh, bl_top_surface_tags)
    loop_data = _classify_root_opening_curves(gmsh, ordered_curve_tags)
    le_xyz = loop_data["leading_edge_point_xyz"]
    upper_te_xyz = loop_data["upper_te_point_xyz"]
    lower_te_xyz = loop_data["lower_te_point_xyz"]
    te_gap = math.hypot(upper_te_xyz[0] - lower_te_xyz[0], upper_te_xyz[2] - lower_te_xyz[2])
    x_pad = max(0.15 * chord_m, 4.0 * bl_total_thickness_m, 12.0 * te_gap)
    z_pad = max(0.05 * chord_m, 2.0 * bl_total_thickness_m, 10.0 * te_gap)
    local_patch_size = max(0.02 * chord_m, 2.0 * bl_total_thickness_m, 6.0 * te_gap)
    z_mid = 0.5 * (upper_te_xyz[2] + lower_te_xyz[2])
    q_le = (float(le_xyz[0] - x_pad), 0.0, float(le_xyz[2]))
    q_upper = (float(max(upper_te_xyz[0], lower_te_xyz[0]) + x_pad), 0.0, float(z_mid + z_pad))
    q_lower = (float(max(upper_te_xyz[0], lower_te_xyz[0]) + x_pad), 0.0, float(z_mid - z_pad))
    p1 = (float(x_min), 0.0, float(z_min))
    p2 = (float(x_max), 0.0, float(z_min))
    p5 = (float(x_min), 0.0, float(z_max))
    p6 = (float(x_max), 0.0, float(z_max))

    upper_curve_polyline = _sample_curve_polyline(gmsh, loop_data["upper_curve_signed"])
    lower_curve_polyline = _sample_curve_polyline(gmsh, loop_data["lower_curve_signed"])
    te_curve_polyline = _sample_curve_polyline(gmsh, loop_data["te_curve_signed"])
    patch_polylines = {
        "ring_upper": [q_le, q_upper, upper_te_xyz, *upper_curve_polyline[1:], q_le],
        "ring_lower": [q_le, *lower_curve_polyline, q_lower, q_le],
        "ring_te": [q_upper, q_lower, lower_te_xyz, *te_curve_polyline[1:], q_upper],
        "outer_left": [p5, q_le, p1, p5],
        "outer_top": [q_le, q_upper, p6, p5, q_le],
        "outer_right": [q_upper, q_lower, p2, p6, q_upper],
        "outer_bottom": [q_lower, q_le, p1, p2, q_lower],
    }
    loop_checks = {
        patch_name: {
            "self_intersections": _loop_self_intersections(polyline),
            "area_xz": float(_polyline_area_xz(polyline)),
        }
        for patch_name, polyline in patch_polylines.items()
    }
    return {
        "mode": ROOT_CLOSURE_MODE_USE_BL_GENERATED_FACES,
        "holed_symmetry_face_used": False,
        "root_side_surface_tags": root_side_surface_tags,
        "raw_root_curve_tags": raw_curve_tags,
        "duplicate_curve_tags": duplicate_curve_tags,
        "ordered_root_curve_tags": ordered_curve_tags,
        "root_loop": loop_data,
        "local_patch_size_m": float(local_patch_size),
        "local_points": {
            "q_le": q_le,
            "q_upper": q_upper,
            "q_lower": q_lower,
            "p1": p1,
            "p2": p2,
            "p5": p5,
            "p6": p6,
        },
        "patch_loop_checks": loop_checks,
    }


def _build_real_wing_root_closure_surfaces(
    *,
    gmsh: Any,
    plan: dict[str, Any],
    p1_tag: int,
    p2_tag: int,
    p5_tag: int,
    p6_tag: int,
    l1_tag: int,
    l5_tag: int,
    l9_tag: int,
    l10_tag: int,
) -> tuple[list[int], dict[str, Any]]:
    geo = gmsh.model.geo
    if plan["duplicate_curve_tags"]:
        raise RuntimeError(
            f"real-wing root closure found duplicate root-opening curves {plan['duplicate_curve_tags']}"
        )
    bad_patches = [
        patch_name
        for patch_name, payload in plan["patch_loop_checks"].items()
        if payload["self_intersections"]
    ]
    if bad_patches:
        raise RuntimeError(
            f"real-wing root closure detected self-intersecting closure loops {bad_patches}"
        )

    loop_data = plan["root_loop"]
    local_points = plan["local_points"]
    local_patch_size = float(plan["local_patch_size_m"])
    q_le_tag = geo.addPoint(*local_points["q_le"], local_patch_size)
    q_upper_tag = geo.addPoint(*local_points["q_upper"], local_patch_size)
    q_lower_tag = geo.addPoint(*local_points["q_lower"], local_patch_size)

    upper_te_point_tag = int(loop_data["upper_te_point_tag"])
    lower_te_point_tag = int(loop_data["lower_te_point_tag"])
    leading_edge_point_tag = int(loop_data["leading_edge_point_tag"])
    outer_upper_tag = geo.addLine(q_le_tag, q_upper_tag)
    outer_lower_tag = geo.addLine(q_lower_tag, q_le_tag)
    outer_te_tag = geo.addLine(q_upper_tag, q_lower_tag)
    left_upper_tag = geo.addLine(p5_tag, q_le_tag)
    left_lower_tag = geo.addLine(q_le_tag, p1_tag)
    right_upper_tag = geo.addLine(q_upper_tag, p6_tag)
    right_lower_tag = geo.addLine(p2_tag, q_lower_tag)
    le_connector_tag = geo.addLine(q_le_tag, leading_edge_point_tag)
    upper_connector_tag = geo.addLine(q_upper_tag, upper_te_point_tag)
    lower_connector_tag = geo.addLine(lower_te_point_tag, q_lower_tag)

    ring_upper_tag = geo.addPlaneSurface(
        [
            geo.addCurveLoop(
                [
                    outer_upper_tag,
                    upper_connector_tag,
                    int(loop_data["upper_curve_signed"]),
                    -le_connector_tag,
                ]
            )
        ]
    )
    ring_lower_tag = geo.addPlaneSurface(
        [
            geo.addCurveLoop(
                [
                    le_connector_tag,
                    int(loop_data["lower_curve_signed"]),
                    lower_connector_tag,
                    outer_lower_tag,
                ]
            )
        ]
    )
    ring_te_tag = geo.addPlaneSurface(
        [
            geo.addCurveLoop(
                [
                    outer_te_tag,
                    -lower_connector_tag,
                    int(loop_data["te_curve_signed"]),
                    -upper_connector_tag,
                ]
            )
        ]
    )
    outer_left_tag = geo.addPlaneSurface([geo.addCurveLoop([left_upper_tag, left_lower_tag, l9_tag])])
    outer_top_tag = geo.addPlaneSurface(
        [geo.addCurveLoop([outer_upper_tag, right_upper_tag, -l5_tag, left_upper_tag])]
    )
    outer_right_tag = geo.addPlaneSurface(
        [geo.addCurveLoop([outer_te_tag, -right_lower_tag, l10_tag, -right_upper_tag])]
    )
    outer_bottom_tag = geo.addPlaneSurface(
        [geo.addCurveLoop([outer_lower_tag, left_lower_tag, l1_tag, right_lower_tag])]
    )
    geo.synchronize()
    gmsh.model.mesh.setSize(
        [
            (0, leading_edge_point_tag),
            (0, upper_te_point_tag),
            (0, lower_te_point_tag),
            (0, q_le_tag),
            (0, q_upper_tag),
            (0, q_lower_tag),
        ],
        local_patch_size,
    )
    return (
        list(plan["root_side_surface_tags"])
        + [
            int(ring_upper_tag),
            int(ring_lower_tag),
            int(ring_te_tag),
            int(outer_left_tag),
            int(outer_top_tag),
            int(outer_right_tag),
            int(outer_bottom_tag),
        ],
        {
            **plan,
            "surface_tags": {
                "root_side": list(plan["root_side_surface_tags"]),
                "ring": [int(ring_upper_tag), int(ring_lower_tag), int(ring_te_tag)],
                "outer": [
                    int(outer_left_tag),
                    int(outer_top_tag),
                    int(outer_right_tag),
                    int(outer_bottom_tag),
                ],
            },
        },
    )


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
    root_closure_mode = _geometry_root_closure_mode(
        geometry,
        geometry_shape_mode=geometry_shape_mode,
    )
    geometry["root_closure_mode"] = root_closure_mode
    bl_spec = spec["boundary_layer"]
    boundary_layer_total_thickness = float(bl_spec["target_total_thickness_m"])
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
    symmetry_surface_tags: list[int] = []
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
    bl_protection_summary: dict[str, Any] | None = None
    bl_excluded_surface_tags: list[int] = []
    protection_config = dict(spec.get("real_wing_bl_protection", {}))
    mesh_algorithm3d = 10
    topology_checks: dict[str, Any] = {
        "root_closure": {
            "mode": root_closure_mode,
            "holed_symmetry_face_used": root_closure_mode == ROOT_CLOSURE_MODE_SINGLE_HOLED_SYMMETRY_FACE,
            "duplicate_curve_tags": [],
            "patch_loop_checks": {},
        }
    }
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
        bl_source_surface_tags = list(wall_surface_tags)
        if geometry_shape_mode == DEFAULT_REAL_MAIN_WING_SHAPE_MODE:
            # Real-wing root closure consumes the BL-generated lateral faces on the
            # symmetry plane directly; without them Gmsh falls back to the old
            # holed-face behavior that is not robust for this geometry family.
            mesh_algorithm3d = 1
            gmsh.option.setNumber("Mesh.Algorithm3D", float(mesh_algorithm3d))
            gmsh.option.setNumber("Geometry.ExtrudeReturnLateralEntities", 1)
            tip_surface_tag = geometry.get("tip_surface_tag")
            if bool(protection_config.get("exclude_tip_cap_from_bl", True)) and tip_surface_tag is not None:
                bl_source_surface_tags = [
                    int(tag) for tag in wall_surface_tags if int(tag) != int(tip_surface_tag)
                ]
            bl_excluded_surface_tags = [
                int(tag) for tag in wall_surface_tags if int(tag) not in bl_source_surface_tags
            ]
            gmsh.model.mesh.generate(2)
            protection_summary = _build_real_wing_bl_protection_field(
                gmsh=gmsh,
                wall_surface_tags=bl_source_surface_tags,
                sections=list(real_wing_geometry["sections"]),
                protection=protection_config,
                base_total_thickness_m=boundary_layer_total_thickness,
                ref_chord_m=chord_m,
                half_span_m=half_span_m,
            )
            if protection_summary is not None:
                bl_protection_summary = protection_summary
        cumulative_heights = _layer_cumulative_heights(
            float(bl_spec["first_layer_height_m"]),
            float(bl_spec["growth_ratio"]),
            int(bl_spec["layers"]),
        )
        extbl = gmsh.model.geo.extrudeBoundaryLayer(
            [(2, tag) for tag in bl_source_surface_tags],
            [1] * int(bl_spec["layers"]),
            cumulative_heights,
            True,
            False,
            -1 if bl_protection_summary is None else int(bl_protection_summary["view_index"]),
        )
        if geometry_shape_mode == DEFAULT_REAL_MAIN_WING_SHAPE_MODE:
            if bl_protection_summary is None:
                bl_protection_summary = {"enabled": False}
            bl_protection_summary["exclude_tip_cap_from_bl"] = bool(
                protection_config.get("exclude_tip_cap_from_bl", True)
            )
            bl_protection_summary["excluded_surface_tags_from_bl"] = list(bl_excluded_surface_tags)
        for index in range(1, len(extbl)):
            if extbl[index][0] == 3:
                bl_volume_tags.append(int(extbl[index][1]))
                bl_top_surface_tags.append(int(extbl[index - 1][1]))
        gmsh.model.geo.synchronize()
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
        if geometry_shape_mode == DEFAULT_REAL_MAIN_WING_SHAPE_MODE:
            if root_closure_mode != ROOT_CLOSURE_MODE_USE_BL_GENERATED_FACES:
                raise RuntimeError(
                    "real-wing shell_v4 root closure must use BL-generated faces; holed symmetry faces are disabled"
                )
            root_closure_plan = _build_real_wing_root_closure_plan(
                gmsh=gmsh,
                extbl=extbl,
                bl_top_surface_tags=bl_top_surface_tags,
                chord_m=chord_m,
                bl_total_thickness_m=boundary_layer_total_thickness,
                x_min=x_min,
                x_max=x_max,
                z_min=z_min,
                z_max=z_max,
            )
            symmetry_surface_tags, topology_checks["root_closure"] = _build_real_wing_root_closure_surfaces(
                gmsh=gmsh,
                plan=root_closure_plan,
                p1_tag=p1,
                p2_tag=p2,
                p5_tag=p5,
                p6_tag=p6,
                l1_tag=l1,
                l5_tag=l5,
                l9_tag=l9,
                l10_tag=l10,
            )
        else:
            hole_boundary = gmsh.model.getBoundary(
                [(2, tag) for tag in bl_top_surface_tags],
                combined=True,
                oriented=False,
                recursive=False,
            )
            hole_curves = _order_curve_loop(gmsh, [int(curve_tag) for dim, curve_tag in hole_boundary if dim == 1])
            topology_checks["root_closure"] = {
                "mode": ROOT_CLOSURE_MODE_SINGLE_HOLED_SYMMETRY_FACE,
                "holed_symmetry_face_used": True,
                "duplicate_curve_tags": _duplicate_curve_tags(hole_curves),
                "patch_loop_checks": {},
            }
            cl_hole = gmsh.model.geo.addCurveLoop(hole_curves)
            cl_sym = gmsh.model.geo.addCurveLoop([l1, l10, -l5, -l9])
            symmetry_surface_tags = [int(gmsh.model.geo.addPlaneSurface([cl_sym, cl_hole]))]
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
                    bl_top_surface_tags + symmetry_surface_tags + farfield_surface_tags
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
        symmetry_group_tag = gmsh.model.addPhysicalGroup(2, symmetry_surface_tags)
        gmsh.model.setPhysicalName(2, symmetry_group_tag, "symmetry")
        farfield_group_tag = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
        gmsh.model.setPhysicalName(2, farfield_group_tag, "farfield")
        fluid_group_tag = gmsh.model.addPhysicalGroup(3, [int(fluid_volume_tag), *bl_volume_tags])
        gmsh.model.setPhysicalName(3, fluid_group_tag, "fluid")

        gmsh.model.mesh.generate(2)
        if geometry_shape_mode == DEFAULT_REAL_MAIN_WING_SHAPE_MODE:
            root_side_surface_tags = topology_checks["root_closure"].get("surface_tags", {}).get("root_side", [])
            for surface_tag in root_side_surface_tags:
                gmsh.model.mesh.splitQuadrangles(1.0, int(surface_tag))
            topology_checks["root_closure"]["surface_mesh_cleanup"] = _cleanup_root_side_surface_mesh(
                gmsh,
                list(root_side_surface_tags),
            )
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
        if symmetry_surface_tags:
            symmetry_face_count, _ = _count_elements_for_entities(gmsh, 2, symmetry_surface_tags)
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
            entity_count=len(symmetry_surface_tags),
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
        "mesh_algorithm3d": int(mesh_algorithm3d),
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
        "topology_checks": topology_checks,
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
            "local_protection": bl_protection_summary,
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
        "mesh_algorithm3d": int(mesh_algorithm3d),
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
        "root_closure_mode": root_closure_mode,
        "bl_local_protection_triggered": bool(
            bl_protection_summary and int(bl_protection_summary.get("triggered_node_count", 0)) > 0
        ),
        "bl_local_protection": bl_protection_summary,
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
