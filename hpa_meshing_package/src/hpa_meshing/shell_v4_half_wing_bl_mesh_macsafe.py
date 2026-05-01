from __future__ import annotations

import bisect
import copy
import csv
import math
import statistics
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .adapters.su2_backend import (
    _mpi_ranks as _backend_mpi_ranks,
    _omp_threads_per_rank as _backend_omp_threads_per_rank,
    _resolve_launch_requirements as _backend_resolve_launch_requirements,
    _solver_command as _backend_solver_command,
    _solver_env as _backend_solver_env,
)
from .compiler.compiler_v1 import compile_topology_family_v1
from .compiler.motif_registry_v1 import MotifRegistryV1
from .compiler.operator_library_v1 import FAILED_STEINER_RESIDUAL_FAMILY, OperatorLibraryV1
from .compiler.pre_plc_audit_v1 import (
    PlanningManualEditCandidateV1,
    PlanningBudgetRecommendationV1,
    PlanningBudgetRegionV1,
    PlanningBudgetSectionV1,
    PlanningBudgetingV1,
    PrePLCAuditConfigV1,
    PrePLCAuditObservedEvidenceV1,
    run_pre_plc_audit_v1,
)
from .compiler.topology_ir_v1 import build_topology_ir_v1
from .gmsh_runtime import load_gmsh
from .providers.esp_pipeline import (
    _apply_terminal_strip_suppression,
    _build_native_rebuild_model,
    _build_topology_lineage_report,
    extract_native_lifting_surface_sections,
)
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
TOPOLOGY_COMPILER_GATE_OFF = "off"
TOPOLOGY_COMPILER_GATE_PLAN_ONLY = "plan_only"
BL_CANDIDATE_APPLY_GATE_OFF = "off"
BL_CANDIDATE_APPLY_GATE_STAGEBACK_PLUS_TRUNCATION_FOCUSED = "stageback_plus_truncation_focused"
BL_CANDIDATE_APPLY_GATE_STAGED_TRANSITION_GUARD_FOCUSED = (
    "stage_with_termination_guard_8_to_7_focused"
)
BL_STAGEBACK_PLUS_TRUNCATION_CANDIDATE_ID = "bl_candidate_stageback_plus_truncation"
BL_STAGED_TRANSITION_GUARD_PROTOTYPE_ID = "stage_with_termination_guard_8_to_7"
BL_CANDIDATE_PARAMETER_SWEEP_CONTRACT = "bl_candidate_parameter_sweep.v1"
BL_STAGEBACK_LOOP_CONTINUITY_DIAGNOSTIC_CONTRACT = "bl_stageback_loop_continuity_diagnostic.v1"
BL_TOPOLOGY_PRESERVING_STAGED_TRANSITION_PROTOTYPES_CONTRACT = (
    "bl_topology_preserving_staged_transition_prototypes.v1"
)
BL_STAGED_TRANSITION_APPLY_COMPARISON_CONTRACT = "staged_transition_apply_comparison.v1"
PRE_PLC_REPRO_FAMILY_CONFIGS: dict[str, dict[str, Any]] = {
    "root_last3_segment_facet": {
        "section_index_offsets": [0, -3, -2, -1],
        "expected_failure_kind": "segment_facet_intersection",
        "expected_error_substrings": ["PLC Error:  A segment and a facet intersect at point"],
    },
    "root_last4_overlap": {
        "section_index_offsets": [0, -4, -3, -2, -1],
        "expected_failure_kind": "facet_facet_overlap",
        "expected_error_substrings": ["Invalid boundary mesh (overlapping facets)"],
    },
}


def _normalize_recoversegment_failed_steiner_evidence(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    residual_family = str(payload.get("residual_family") or payload.get("family") or "")
    throw_site_label = str(payload.get("throw_site_label") or "")
    if (
        residual_family != FAILED_STEINER_RESIDUAL_FAMILY
        and throw_site_label != "addsteiner4recoversegment:failed_insert_steiner"
    ):
        return {}
    normalized: dict[str, Any] = {
        "residual_family": FAILED_STEINER_RESIDUAL_FAMILY,
        "evidence_level": str(payload.get("evidence_level") or "observed_candidate"),
        "throw_site_label": throw_site_label or None,
        "throw_site_file": (
            str(payload.get("throw_site_file"))
            if payload.get("throw_site_file") is not None
            else None
        ),
        "throw_site_line": (
            int(payload["throw_site_line"])
            if payload.get("throw_site_line") is not None
            else None
        ),
        "local_surface_tags": [
            int(tag) for tag in list(payload.get("local_surface_tags") or [])
        ],
        "local_y_band": [
            float(value) for value in list(payload.get("local_y_band") or [])
        ],
        "suspicious_window": [
            float(value) for value in list(payload.get("suspicious_window") or [])
        ],
        "sevent_e_type": (
            int(payload["sevent_e_type"])
            if payload.get("sevent_e_type") is not None
            else None
        ),
        "degenerated_prism_seen": (
            bool(payload["degenerated_prism_seen"])
            if payload.get("degenerated_prism_seen") is not None
            else None
        ),
    }
    return {key: value for key, value in normalized.items() if value is not None and value != []}


def _recoversegment_failed_steiner_evidence_from_observed(observed: Any) -> dict[str, Any]:
    if not isinstance(observed, dict):
        return {}
    for key in (
        "forensic_evidence",
        "boundary_recovery_forensic_evidence",
        "recoversegment_failed_steiner_evidence",
    ):
        normalized = _normalize_recoversegment_failed_steiner_evidence(observed.get(key))
        if normalized:
            return normalized
    route_result = observed.get("route_result")
    if isinstance(route_result, dict):
        for key in (
            "forensic_evidence",
            "boundary_recovery_forensic_evidence",
            "recoversegment_failed_steiner_evidence",
        ):
            normalized = _normalize_recoversegment_failed_steiner_evidence(route_result.get(key))
            if normalized:
                return normalized
        topology_checks = route_result.get("topology_checks")
        if isinstance(topology_checks, dict):
            normalized = _normalize_recoversegment_failed_steiner_evidence(
                topology_checks.get("recoversegment_failed_steiner")
            )
            if normalized:
                return normalized
    error_text = str(observed.get("error") or "")
    if "addsteiner4recoversegment:failed_insert_steiner" in error_text:
        return _normalize_recoversegment_failed_steiner_evidence(
            {
                "throw_site_label": "addsteiner4recoversegment:failed_insert_steiner",
            }
        )
    return {}


@dataclass(frozen=True)
class ClosureRingPatchDesc:
    source_surface_tag: int
    legacy_surface_tag: int
    connector_curve_tag: int
    source_signed_boundary_curves: tuple[int, ...]
    wire_source_signed_curves: tuple[int, int, int, int]
    semantic_corner_point_tags: tuple[int, int, int, int]

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
            "tip_clearance_zone_chords": 1.25,
            "tip_min_bl_top_clearance_m": 0.005,
            "tip_min_bl_top_clearance_fraction_of_base_thickness": 0.30,
            "tip_truncation_scale_threshold": 0.35,
            "tip_truncation_inboard_buffer_chords": 2.0,
            "tip_truncation_connector_band_chords": 0.01,
            "tip_truncation_auto_exclude_tip_cap": True,
            "tip_truncation_facet_overlap_angle_tol_deg": 0.001,
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
            "tip_clearance_zone_chords": 1.25,
            "tip_min_bl_top_clearance_m": 0.005,
            "tip_min_bl_top_clearance_fraction_of_base_thickness": 0.30,
            "tip_truncation_scale_threshold": 0.35,
            "tip_truncation_inboard_buffer_chords": 2.0,
            "tip_truncation_connector_band_chords": 0.01,
            "tip_truncation_auto_exclude_tip_cap": True,
            "tip_truncation_facet_overlap_angle_tol_deg": 0.001,
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


def _real_wing_local_clearance_at_spanwise_x_rel(
    *,
    sections: list[dict[str, Any]],
    y_value: float,
    x_rel: float,
) -> dict[str, float]:
    lower_index, upper_index, ratio = _bracketing_section_indices(sections, float(y_value))
    lower_section = sections[lower_index]
    upper_section = sections[upper_index]
    lower_thickness = _section_local_thickness_at_x(lower_section, x_rel)
    upper_thickness = _section_local_thickness_at_x(upper_section, x_rel)
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
    return {
        "local_thickness_m": float(max(0.0, thickness)),
        "local_half_thickness_m": float(max(0.0, 0.5 * thickness)),
        "local_x_rel": float(x_rel),
        "local_chord_m": float(frame["chord"]),
        "span_y_m": float(y_value),
    }


def _required_tip_bl_top_clearance_m(
    *,
    protection: dict[str, Any],
    base_total_thickness_m: float,
) -> float:
    return float(
        max(
            float(protection.get("tip_min_bl_top_clearance_m", 0.0) or 0.0),
            float(protection.get("tip_min_bl_top_clearance_fraction_of_base_thickness", 0.0) or 0.0)
            * float(base_total_thickness_m),
        )
    )


def _real_wing_bl_protection_payload(
    *,
    clearance: dict[str, float],
    protection: dict[str, Any],
    base_total_thickness_m: float,
    half_span_m: float,
    point_xyz: tuple[float, float, float] | None = None,
) -> dict[str, float]:
    local_thickness = max(float(clearance["local_thickness_m"]), 0.0)
    local_half_thickness = max(float(clearance["local_half_thickness_m"]), 1.0e-9)
    local_chord_m = max(float(clearance["local_chord_m"]), 1.0e-9)
    span_y_m = float(clearance["span_y_m"])
    tip_distance_m = max(0.0, float(half_span_m) - span_y_m)
    outboard_activation_local_chords = float(protection["outboard_activation_local_chords"])
    outboard_activation_span_m = max(0.0, outboard_activation_local_chords * local_chord_m)
    outboard_activated = tip_distance_m <= outboard_activation_span_m + 1.0e-12
    x_rel_min = float(protection["thickness_limit_x_rel_min"])
    x_rel_max = float(protection["thickness_limit_x_rel_max"])
    local_x_rel = float(clearance["local_x_rel"])
    within_thickness_window = x_rel_min <= local_x_rel <= x_rel_max
    thickness_limit_active = within_thickness_window and outboard_activated

    allowed_from_thickness = float(base_total_thickness_m)
    if thickness_limit_active:
        allowed_from_thickness = float(protection["max_total_to_half_thickness_fraction"]) * local_half_thickness

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

    required_min_bl_top_clearance_m = _required_tip_bl_top_clearance_m(
        protection=protection,
        base_total_thickness_m=base_total_thickness_m,
    )
    tip_clearance_zone_span_m = max(
        1.0e-9,
        float(protection.get("tip_clearance_zone_chords", protection["tip_zone_chords"])) * local_chord_m,
    )
    tip_clearance_active = (
        within_thickness_window and outboard_activated and tip_distance_m <= tip_clearance_zone_span_m + 1.0e-12
    )
    allowed_from_tip_clearance = float(base_total_thickness_m)
    required_scale_for_tip_clearance = 1.0
    if tip_clearance_active:
        allowed_from_tip_clearance = max(
            0.0,
            0.5 * max(local_thickness - required_min_bl_top_clearance_m, 0.0),
        )
        required_scale_for_tip_clearance = float(
            allowed_from_tip_clearance / max(base_total_thickness_m, 1.0e-12)
        )

    raw_allowed_total = min(
        float(base_total_thickness_m),
        float(allowed_from_thickness * tip_scale),
        float(allowed_from_tip_clearance),
    )
    raw_scale = float(raw_allowed_total / max(base_total_thickness_m, 1.0e-12))
    scale = float(max(float(protection["min_local_scale"]), min(1.0, raw_scale)))
    applied_total_thickness = float(scale * base_total_thickness_m)
    predicted_bl_top_clearance = max(0.0, float(local_thickness - 2.0 * applied_total_thickness))
    truncation_candidate = tip_clearance_active and (
        required_scale_for_tip_clearance <= float(protection.get("tip_truncation_scale_threshold", 0.35)) + 1.0e-12
    )
    tip_clearance_risk = tip_clearance_active and (
        predicted_bl_top_clearance < required_min_bl_top_clearance_m - 1.0e-12 or truncation_candidate
    )

    payload = {
        "local_thickness_m": float(local_thickness),
        "local_half_thickness_m": float(local_half_thickness),
        "local_x_rel": float(local_x_rel),
        "local_chord_m": float(local_chord_m),
        "span_y_m": float(span_y_m),
        "tip_distance_m": float(tip_distance_m),
        "outboard_activation_span_m": float(outboard_activation_span_m),
        "tip_zone_span_m": float(tip_zone_span_m),
        "tip_clearance_zone_span_m": float(tip_clearance_zone_span_m),
        "required_min_bl_top_clearance_m": float(required_min_bl_top_clearance_m),
        "required_scale_for_tip_clearance": float(required_scale_for_tip_clearance),
        "allowed_total_thickness_m": float(applied_total_thickness),
        "raw_allowed_total_thickness_m": float(raw_allowed_total),
        "scale": float(scale),
        "raw_scale_before_clamp": float(raw_scale),
        "predicted_bl_top_clearance_m": float(predicted_bl_top_clearance),
        "tip_progress": float(tip_progress),
        "thickness_window_active": 1.0 if within_thickness_window else 0.0,
        "outboard_activated": 1.0 if outboard_activated else 0.0,
        "thickness_limit_active": 1.0 if thickness_limit_active else 0.0,
        "thickness_limited": 1.0
        if thickness_limit_active and allowed_from_thickness < base_total_thickness_m - 1.0e-12
        else 0.0,
        "tip_limited": 1.0 if tip_progress > 0.0 else 0.0,
        "tip_clearance_active": 1.0 if tip_clearance_active else 0.0,
        "tip_clearance_risk": 1.0 if tip_clearance_risk else 0.0,
        "truncation_candidate": 1.0 if truncation_candidate else 0.0,
    }
    if point_xyz is not None:
        payload["x"] = float(point_xyz[0])
        payload["y"] = float(point_xyz[1])
        payload["z"] = float(point_xyz[2])
    else:
        payload["y"] = float(span_y_m)
    return payload


def _collect_real_wing_bl_node_payloads(
    *,
    gmsh: Any,
    wall_surface_tags: list[int],
    sections: list[dict[str, Any]],
    protection: dict[str, Any],
    base_total_thickness_m: float,
    half_span_m: float,
) -> dict[int, dict[str, float]]:
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
            node_payloads[node_key] = _real_wing_bl_protection_payload(
                clearance=clearance,
                protection=protection,
                base_total_thickness_m=base_total_thickness_m,
                half_span_m=half_span_m,
                point_xyz=xyz,
            )
    return node_payloads


def _build_real_wing_bl_protection_summary(
    *,
    payloads: Iterable[dict[str, float]],
    protection: dict[str, Any],
    base_total_thickness_m: float,
    view_tag: int | None = None,
    view_index: int | None = None,
) -> dict[str, Any]:
    payload_list = [dict(payload) for payload in payloads]
    if not payload_list:
        return {
            "enabled": bool(protection.get("enabled", True)),
            "mode": "local_thickness_scaled_boundary_layer",
            "intervention_mode": "none",
            "base_total_thickness_m": float(base_total_thickness_m),
            "node_count": 0,
            "triggered_node_count": 0,
        }

    triggered_nodes = [payload for payload in payload_list if payload["scale"] < 0.999999]
    tip_truncation_nodes = [payload for payload in payload_list if int(payload["truncation_candidate"]) == 1]
    intervention_mode = "none"
    if triggered_nodes:
        intervention_mode = "scaling_only"
    if triggered_nodes and tip_truncation_nodes:
        intervention_mode = "scaling_and_truncation"

    summary: dict[str, Any] = {
        "enabled": True,
        "mode": "local_thickness_scaled_boundary_layer",
        "intervention_mode": intervention_mode,
        "base_total_thickness_m": float(base_total_thickness_m),
        "outboard_activation_local_chords": float(protection["outboard_activation_local_chords"]),
        "max_total_to_half_thickness_fraction": float(protection["max_total_to_half_thickness_fraction"]),
        "tip_zone_chords": float(protection["tip_zone_chords"]),
        "tip_scale_at_tip": float(protection["tip_scale_at_tip"]),
        "tip_clearance_zone_chords": float(
            protection.get("tip_clearance_zone_chords", protection["tip_zone_chords"])
        ),
        "tip_min_bl_top_clearance_m": float(protection.get("tip_min_bl_top_clearance_m", 0.0) or 0.0),
        "tip_min_bl_top_clearance_fraction_of_base_thickness": float(
            protection.get("tip_min_bl_top_clearance_fraction_of_base_thickness", 0.0) or 0.0
        ),
        "required_min_bl_top_clearance_m": float(
            max(payload["required_min_bl_top_clearance_m"] for payload in payload_list)
        ),
        "tip_truncation_scale_threshold": float(protection.get("tip_truncation_scale_threshold", 0.35)),
        "tip_truncation_inboard_buffer_chords": float(
            protection.get("tip_truncation_inboard_buffer_chords", 0.0)
        ),
        "thickness_limit_x_rel_min": float(protection["thickness_limit_x_rel_min"]),
        "thickness_limit_x_rel_max": float(protection["thickness_limit_x_rel_max"]),
        "min_local_scale": float(protection["min_local_scale"]),
        "layer_count_preserved": True,
        "thickness_scaled_locally": True,
        "node_count": int(len(payload_list)),
        "triggered_node_count": int(len(triggered_nodes)),
        "triggered_node_fraction": float(len(triggered_nodes) / max(len(payload_list), 1)),
        "scale_min": float(min(payload["scale"] for payload in payload_list)),
        "scale_max": float(max(payload["scale"] for payload in payload_list)),
        "scale_mean": float(statistics.fmean(payload["scale"] for payload in payload_list)),
        "outboard_activated_node_count": int(sum(int(payload["outboard_activated"]) for payload in payload_list)),
        "thickness_window_node_count": int(sum(int(payload["thickness_window_active"]) for payload in payload_list)),
        "thickness_limit_active_node_count": int(sum(int(payload["thickness_limit_active"]) for payload in payload_list)),
        "thickness_limited_node_count": int(sum(int(payload["thickness_limited"]) for payload in triggered_nodes)),
        "tip_limited_node_count": int(sum(int(payload["tip_limited"]) for payload in triggered_nodes)),
        "tip_clearance_active_node_count": int(sum(int(payload["tip_clearance_active"]) for payload in payload_list)),
        "tip_clearance_risk_node_count": int(sum(int(payload["tip_clearance_risk"]) for payload in payload_list)),
        "tip_truncation_candidate_node_count": int(len(tip_truncation_nodes)),
        "predicted_bl_top_clearance_range_m": {
            "min": float(min(payload["predicted_bl_top_clearance_m"] for payload in payload_list)),
            "max": float(max(payload["predicted_bl_top_clearance_m"] for payload in payload_list)),
        },
    }
    if view_tag is not None:
        summary["view_tag"] = int(view_tag)
    if view_index is not None:
        summary["view_index"] = int(view_index)
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
    if tip_truncation_nodes:
        summary["tip_truncation_candidate_span_y_range_m"] = {
            "min": float(min(payload["y"] for payload in tip_truncation_nodes)),
            "max": float(max(payload["y"] for payload in tip_truncation_nodes)),
        }
        summary["tip_truncation_candidate_tip_distance_range_m"] = {
            "min": float(min(payload["tip_distance_m"] for payload in tip_truncation_nodes)),
            "max": float(max(payload["tip_distance_m"] for payload in tip_truncation_nodes)),
        }
        summary["tip_truncation_candidate_scale_range"] = {
            "min": float(min(payload["required_scale_for_tip_clearance"] for payload in tip_truncation_nodes)),
            "max": float(max(payload["required_scale_for_tip_clearance"] for payload in tip_truncation_nodes)),
        }
    return summary


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
    node_payloads = _collect_real_wing_bl_node_payloads(
        gmsh=gmsh,
        wall_surface_tags=wall_surface_tags,
        sections=sections,
        protection=protection,
        base_total_thickness_m=base_total_thickness_m,
        half_span_m=half_span_m,
    )
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
    return _build_real_wing_bl_protection_summary(
        payloads=node_payloads.values(),
        protection=protection,
        base_total_thickness_m=base_total_thickness_m,
        view_tag=int(view_tag),
        view_index=int(gmsh.view.getIndex(view_tag)),
    )


def _sample_real_wing_bl_interference_payloads(
    *,
    sections: list[dict[str, Any]],
    protection: dict[str, Any],
    base_total_thickness_m: float,
    half_span_m: float,
    span_samples_per_interval: int = 13,
    chordwise_samples: int = 19,
    truncation_start_y_m: float | None = None,
) -> tuple[list[dict[str, float]], list[dict[str, float]], list[dict[str, float]]]:
    x_rel_min = float(protection["thickness_limit_x_rel_min"])
    x_rel_max = float(protection["thickness_limit_x_rel_max"])
    chordwise_count = max(3, int(chordwise_samples))
    x_samples = [
        float(x_rel_min + (x_rel_max - x_rel_min) * index / max(chordwise_count - 1, 1))
        for index in range(chordwise_count)
    ]

    full_payloads: list[dict[str, float]] = []
    retained_payloads: list[dict[str, float]] = []
    suppressed_payloads: list[dict[str, float]] = []
    y_values = [float(section["y_le"]) for section in sections]
    samples_per_interval = max(3, int(span_samples_per_interval))
    for interval_index, (y0, y1) in enumerate(zip(y_values[:-1], y_values[1:])):
        for sample_index in range(samples_per_interval):
            if interval_index > 0 and sample_index == 0:
                continue
            ratio = float(sample_index / max(samples_per_interval - 1, 1))
            y_value = float(y0 + (y1 - y0) * ratio)
            for x_rel in x_samples:
                clearance = _real_wing_local_clearance_at_spanwise_x_rel(
                    sections=sections,
                    y_value=y_value,
                    x_rel=x_rel,
                )
                payload = _real_wing_bl_protection_payload(
                    clearance=clearance,
                    protection=protection,
                    base_total_thickness_m=base_total_thickness_m,
                    half_span_m=half_span_m,
                )
                full_payloads.append(payload)
                if truncation_start_y_m is not None and y_value >= float(truncation_start_y_m) - 1.0e-12:
                    suppressed_payloads.append(payload)
                else:
                    retained_payloads.append(payload)
    return full_payloads, retained_payloads, suppressed_payloads


def _budget_recommendation_value(
    recommendations: list[PlanningBudgetRecommendationV1],
    action_kind: str,
    field_name: str,
) -> float | None:
    for recommendation in recommendations:
        if recommendation.kind != action_kind:
            continue
        value = getattr(recommendation, field_name)
        if value is not None:
            return float(value)
    return None


def _budget_manual_candidate_reason(
    *,
    target_kind: str,
    target_id: str,
    recommended_action_kinds: list[str],
    ratio_deficit: float | None,
    available_budget_ratio_deficit: float | None,
) -> str:
    deficit_fragments: list[str] = []
    if ratio_deficit is not None:
        deficit_fragments.append(f"clearance_ratio_deficit={float(ratio_deficit):.6g}")
    if available_budget_ratio_deficit is not None:
        deficit_fragments.append(
            f"available_budget_ratio_deficit={float(available_budget_ratio_deficit):.6g}"
        )
    action_fragment = ",".join(recommended_action_kinds) if recommended_action_kinds else "manual_review"
    deficit_fragment = "; ".join(deficit_fragments) if deficit_fragments else "no_numeric_deficit"
    return (
        f"{target_kind} {target_id} is a tight BL budget window; actions={action_fragment}; "
        f"{deficit_fragment}."
    )


def _build_budget_manual_edit_candidate(
    *,
    target_kind: str,
    target_id: str,
    span_y_range_m: dict[str, float],
    current_total_bl_thickness_m: float,
    min_local_clearance_m: float | None,
    current_clearance_ratio: float | None,
    ratio_deficit: float | None,
    available_budget_ratio: float | None,
    available_budget_ratio_deficit: float | None,
    recommended_action_kinds: list[str],
    recommendations: list[PlanningBudgetRecommendationV1],
) -> PlanningManualEditCandidateV1:
    suggested_max_total = (
        float(current_total_bl_thickness_m) * float(available_budget_ratio)
        if available_budget_ratio is not None
        else None
    )
    suggested_reduction = (
        max(0.0, float(current_total_bl_thickness_m) - float(suggested_max_total))
        if suggested_max_total is not None
        else None
    )
    suggested_truncation_start = _budget_recommendation_value(
        recommendations,
        "truncate_tip_zone",
        "suggested_truncation_start_y_m",
    )
    if suggested_truncation_start is None and "truncate_tip_zone" in recommended_action_kinds:
        suggested_truncation_start = float(span_y_range_m.get("min", 0.0))
    return PlanningManualEditCandidateV1(
        candidate_id=f"manual_edit:{target_kind}:{target_id}",
        target_kind=target_kind,
        target_id=target_id,
        planning_only=True,
        span_y_range_m=dict(span_y_range_m),
        current_total_bl_thickness_m=float(current_total_bl_thickness_m),
        min_local_clearance_m=(
            float(min_local_clearance_m) if min_local_clearance_m is not None else None
        ),
        current_clearance_ratio=(
            float(current_clearance_ratio) if current_clearance_ratio is not None else None
        ),
        ratio_deficit=float(ratio_deficit) if ratio_deficit is not None else None,
        available_budget_ratio_deficit=(
            float(available_budget_ratio_deficit)
            if available_budget_ratio_deficit is not None
            else None
        ),
        suggested_max_total_bl_thickness_m=suggested_max_total,
        suggested_thickness_reduction_m=suggested_reduction,
        suggested_truncation_start_y_m=suggested_truncation_start,
        suggested_split_boundary_y_m=float(span_y_range_m.get("min", 0.0)),
        suggested_layer_stage_back_direction="reduce_layers_outboard_first",
        recommendation_kinds=list(recommended_action_kinds),
        recommendation_reason=_budget_manual_candidate_reason(
            target_kind=target_kind,
            target_id=target_id,
            recommended_action_kinds=recommended_action_kinds,
            ratio_deficit=ratio_deficit,
            available_budget_ratio_deficit=available_budget_ratio_deficit,
        ),
        notes=[
            "Manual edit candidate is planning-only and must not mutate shell_v4 geometry or BL settings.",
        ],
    )


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalized_y_span(payload: dict[str, Any]) -> dict[str, float]:
    span = payload.get("span_y_range_m")
    if not isinstance(span, dict):
        span = payload.get("target_y_span")
    if isinstance(span, dict):
        lower = _safe_float(span.get("min"), 0.0)
        upper = _safe_float(span.get("max"), lower)
        if lower is not None and upper is not None and upper > lower:
            return {"min": float(lower), "max": float(upper)}
    center = _safe_float(payload.get("span_y_m"), 0.0)
    center_value = float(center or 0.0)
    return {"min": center_value, "max": center_value + 1.0e-9}


def _first_manual_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("manual_edit_candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        return dict(candidates[0])
    return {}


def _select_bl_candidate_target(planning_budgeting: dict[str, Any]) -> dict[str, Any]:
    regions = [
        dict(region)
        for region in planning_budgeting.get("tightest_regions", [])
        if isinstance(region, dict)
    ] or [
        dict(region)
        for region in planning_budgeting.get("region_budgets", [])
        if isinstance(region, dict)
    ]
    sections = [
        dict(section)
        for section in planning_budgeting.get("tightest_sections", [])
        if isinstance(section, dict)
    ] or [
        dict(section)
        for section in planning_budgeting.get("section_budgets", [])
        if isinstance(section, dict)
    ]

    def _rank(payload: dict[str, Any]) -> tuple[int, float, float, float]:
        region_kind = str(payload.get("region_kind") or "")
        preferred_kind_rank = {
            "tip_truncation_candidate_zone": 0,
            "tip_clearance_active_zone": 1,
            "outboard_scaling_zone": 2,
            "suppressed_tip_zone": 3,
        }.get(region_kind, 4)
        budget_deficit = _safe_float(payload.get("available_budget_ratio_deficit"), 0.0) or 0.0
        clearance_deficit = _safe_float(payload.get("clearance_to_thickness_ratio_deficit"), 0.0) or 0.0
        span = _normalized_y_span(payload)
        return (preferred_kind_rank, -budget_deficit, -clearance_deficit, -span["max"])

    if regions:
        target = sorted(regions, key=_rank)[0]
        target["target_kind"] = "region"
        return target
    if sections:
        target = sorted(sections, key=_rank)[0]
        target["target_kind"] = "section"
        return target
    return {
        "target_kind": "unknown",
        "region_kind": "unknown",
        "span_y_range_m": {"min": 0.0, "max": 0.0},
        "manual_edit_candidates": [],
    }


def _candidate_estimated_ratio(
    *,
    min_local_clearance_m: float | None,
    proposed_total_bl_thickness: float | None,
    fallback_ratio: float,
) -> float:
    if proposed_total_bl_thickness is None:
        return float(fallback_ratio)
    if proposed_total_bl_thickness <= 0.0:
        return 1.0
    if min_local_clearance_m is None:
        return float(fallback_ratio)
    return float(min_local_clearance_m) / max(float(proposed_total_bl_thickness), 1.0e-12)


def _candidate_ratio_deficit(ratio: float) -> float:
    return float(max(0.0, 1.0 - float(ratio)))


def _build_bl_stageback_truncation_candidate_comparison(
    *,
    planning_budgeting: dict[str, Any],
    planning_policy_fail_kinds: list[str],
    planning_policy_recommendation_kinds: list[str],
    original_layer_count: int | None = None,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    target = _select_bl_candidate_target(dict(planning_budgeting or {}))
    manual_candidate = _first_manual_candidate(target)
    target_span = _normalized_y_span(target)
    original_total = (
        _safe_float(planning_budgeting.get("total_bl_thickness_m"))
        or _safe_float(manual_candidate.get("current_total_bl_thickness_m"))
        or 0.0
    )
    min_local_clearance = (
        _safe_float(target.get("min_local_half_thickness_m"))
        or _safe_float(manual_candidate.get("min_local_clearance_m"))
    )
    current_ratio = (
        _safe_float(target.get("min_clearance_to_thickness_ratio"))
        or _safe_float(manual_candidate.get("current_clearance_ratio"))
        or _candidate_estimated_ratio(
            min_local_clearance_m=min_local_clearance,
            proposed_total_bl_thickness=original_total,
            fallback_ratio=0.0,
        )
    )
    suggested_max_total = (
        _safe_float(manual_candidate.get("suggested_max_total_bl_thickness_m"))
        or (
            float(original_total)
            * float(target.get("min_available_budget_ratio"))
            if target.get("min_available_budget_ratio") is not None
            else None
        )
        or min_local_clearance
        or original_total
    )
    suggested_max_total = max(0.0, min(float(original_total), float(suggested_max_total)))
    split_boundary_y = (
        _safe_float(manual_candidate.get("suggested_split_boundary_y_m"))
        or float(target_span["min"])
    )
    truncation_start_y = (
        _safe_float(manual_candidate.get("suggested_truncation_start_y_m"))
        or float(target_span["min"])
    )
    layer_count = int(original_layer_count or 0)
    proposed_stageback_layers = (
        max(1, min(layer_count - 1, math.ceil(layer_count * 0.65)))
        if layer_count > 1
        else None
    )
    stageback_total = (
        float(original_total) * (float(proposed_stageback_layers) / float(layer_count))
        if proposed_stageback_layers is not None and layer_count > 0
        else float(original_total) * 0.65
    )
    combined_total = min(float(stageback_total), float(suggested_max_total))
    target_hint_parts = [
        str(target.get("region_id") or target.get("section_id") or target.get("target_id") or "unknown"),
        f"region_kind={target.get('region_kind', 'unknown')}",
    ]
    if target.get("section_ids"):
        target_hint_parts.append(f"section_ids={','.join(str(value) for value in target['section_ids'])}")
    target_hint = "; ".join(target_hint_parts)

    def _candidate(
        *,
        candidate_id: str,
        candidate_kind: str,
        proposed_total_bl_thickness: float | None = None,
        proposed_layer_count: int | None = None,
        expected_effect_on_failed_steiner: str,
        expected_effect_on_degenerated_prism: str,
        risk_notes: list[str],
        suggested_truncation_start_y_value: float | None = None,
        split_boundary_y_value: float | None = None,
        reduction_delta: float | None = None,
    ) -> dict[str, Any]:
        proposed_total = (
            float(proposed_total_bl_thickness)
            if proposed_total_bl_thickness is not None
            else None
        )
        ratio_after = _candidate_estimated_ratio(
            min_local_clearance_m=min_local_clearance,
            proposed_total_bl_thickness=proposed_total,
            fallback_ratio=float(current_ratio),
        )
        payload = {
            "candidate_id": candidate_id,
            "candidate_kind": candidate_kind,
            "target_y_span": copy.deepcopy(target_span),
            "target_surface_or_region_hint": target_hint,
            "original_layer_count": layer_count or None,
            "original_total_bl_thickness": float(original_total),
            "proposed_total_bl_thickness": proposed_total,
            "proposed_layer_count": proposed_layer_count,
            "estimated_clearance_ratio_after": float(ratio_after),
            "estimated_ratio_deficit_after": _candidate_ratio_deficit(ratio_after),
            "expected_effect_on_failed_steiner": expected_effect_on_failed_steiner,
            "expected_effect_on_degenerated_prism": expected_effect_on_degenerated_prism,
            "risk_notes": list(risk_notes),
            "planning_only": True,
        }
        if suggested_truncation_start_y_value is not None:
            payload["suggested_truncation_start_y"] = float(suggested_truncation_start_y_value)
        if split_boundary_y_value is not None:
            payload["split_boundary_y"] = float(split_boundary_y_value)
        if reduction_delta is not None:
            payload["reduction_delta"] = float(reduction_delta)
        return payload

    candidates = [
        _candidate(
            candidate_id="bl_candidate_baseline_current_policy",
            candidate_kind="baseline",
            proposed_total_bl_thickness=float(original_total),
            proposed_layer_count=layer_count or None,
            expected_effect_on_failed_steiner="unlikely",
            expected_effect_on_degenerated_prism="unlikely",
            risk_notes=[
                "Keeps the current BL policy and therefore preserves the known failed-Steiner residual and degenerated-prism risk.",
            ],
        ),
        _candidate(
            candidate_id="bl_candidate_tip_zone_stageback",
            candidate_kind="tip_zone_stageback",
            proposed_total_bl_thickness=float(stageback_total),
            proposed_layer_count=proposed_stageback_layers,
            expected_effect_on_failed_steiner="uncertain",
            expected_effect_on_degenerated_prism="likely_improves",
            risk_notes=[
                "Layer-count rollback can reduce prism crowding, but by itself may not remove the terminal recovery discontinuity.",
                "Needs an explicit experimental apply gate before any runtime use.",
            ],
        ),
        _candidate(
            candidate_id="bl_candidate_tip_zone_truncation",
            candidate_kind="tip_zone_truncation",
            proposed_total_bl_thickness=0.0,
            proposed_layer_count=0,
            expected_effect_on_failed_steiner="likely_improves",
            expected_effect_on_degenerated_prism="likely_improves",
            risk_notes=[
                "Stops BL before the terminal tight region in planning only; this may change local aerodynamic wall treatment and must be reviewed before applying.",
            ],
            suggested_truncation_start_y_value=truncation_start_y,
        ),
        _candidate(
            candidate_id="bl_candidate_split_region_budget",
            candidate_kind="split_region_budget",
            proposed_total_bl_thickness=float(original_total),
            proposed_layer_count=layer_count or None,
            expected_effect_on_failed_steiner="uncertain",
            expected_effect_on_degenerated_prism="uncertain",
            risk_notes=[
                "Splitting the budget is a control-surface for later policy decisions; it does not directly reduce BL thickness.",
            ],
            split_boundary_y_value=split_boundary_y,
        ),
        _candidate(
            candidate_id="bl_candidate_shrink_total_thickness",
            candidate_kind="shrink_total_thickness",
            proposed_total_bl_thickness=float(suggested_max_total),
            proposed_layer_count=layer_count or None,
            expected_effect_on_failed_steiner="uncertain",
            expected_effect_on_degenerated_prism="likely_improves",
            risk_notes=[
                "Uses the local clearance budget to cap total BL thickness, but it does not explicitly stop the BL at the failed-Steiner terminal region.",
            ],
            reduction_delta=max(0.0, float(original_total) - float(suggested_max_total)),
        ),
        _candidate(
            candidate_id=BL_STAGEBACK_PLUS_TRUNCATION_CANDIDATE_ID,
            candidate_kind="stageback_plus_truncation",
            proposed_total_bl_thickness=float(combined_total),
            proposed_layer_count=proposed_stageback_layers,
            expected_effect_on_failed_steiner="likely_improves",
            expected_effect_on_degenerated_prism="likely_improves",
            risk_notes=[
                "Combines prism-pressure relief with terminal BL removal; this is the best planning candidate, not a runtime default.",
                "Requires a separate explicit experimental apply gate and a focused topology rerun.",
            ],
            suggested_truncation_start_y_value=truncation_start_y,
            reduction_delta=max(0.0, float(original_total) - float(combined_total)),
        ),
    ]
    candidate_table = [
        {
            "candidate_id": candidate["candidate_id"],
            "candidate_kind": candidate["candidate_kind"],
            "estimated_clearance_ratio_after": candidate["estimated_clearance_ratio_after"],
            "estimated_ratio_deficit_after": candidate["estimated_ratio_deficit_after"],
            "expected_effect_on_failed_steiner": candidate["expected_effect_on_failed_steiner"],
            "expected_effect_on_degenerated_prism": candidate["expected_effect_on_degenerated_prism"],
        }
        for candidate in candidates
    ]
    payload = {
        "contract": "bl_stageback_truncation_candidate_comparison.v1",
        "status": "written",
        "planning_only": True,
        "plan_report_only": True,
        "runtime_apply_gate_enabled": False,
        "runtime_apply_gate_disabled": True,
        "runtime_bl_spec_mutation": False,
        "runtime_geometry_mutation": False,
        "production_default_mutation": False,
        "current_verdict": (
            "topology_attempted_but_bl_policy_blocked"
            if planning_policy_fail_kinds
            else "bl_candidate_review_only"
        ),
        "planning_policy_fail_kinds": list(planning_policy_fail_kinds),
        "planning_policy_recommendation_kinds": list(planning_policy_recommendation_kinds),
        "candidate_kinds": [candidate["candidate_kind"] for candidate in candidates],
        "candidates": candidates,
        "candidate_comparison_table": candidate_table,
        "recommended_candidate_id": BL_STAGEBACK_PLUS_TRUNCATION_CANDIDATE_ID,
        "recommendation_reason": (
            "The failed-Steiner residual and degenerated-prism signal both sit in the terminal tip pressure window; "
            "the combined candidate reduces prism crowding and removes the BL from the terminal recovery region while staying planning-only."
        ),
        "topology_rerun_recommended_after_candidate_application": True,
        "artifact_path": str(artifact_path) if artifact_path is not None else None,
        "notes": [
            "Candidate comparison is derived from planning budgeting evidence only.",
            "It does not modify the shell_v4 runtime BL spec, production defaults, Gmsh, or topology operators.",
            "Applying any candidate requires a separate explicit experimental apply gate.",
        ],
    }
    if artifact_path is not None:
        write_json_report(Path(artifact_path), payload)
    return payload


def _build_real_wing_bl_budgeting_plan(
    *,
    sections: list[dict[str, Any]],
    protection: dict[str, Any],
    base_total_thickness_m: float,
    half_span_m: float,
    truncation_start_y_m: float | None = None,
) -> PlanningBudgetingV1:
    if not bool(protection.get("enabled", True)) or len(sections) < 2:
        return PlanningBudgetingV1(
            status="unsupported",
            total_bl_thickness_m=float(base_total_thickness_m),
            notes=["Need an enabled real-wing BL protection contract with at least two sections."],
        )

    full_payloads, _, suppressed_payloads = _sample_real_wing_bl_interference_payloads(
        sections=sections,
        protection=protection,
        base_total_thickness_m=base_total_thickness_m,
        half_span_m=half_span_m,
        truncation_start_y_m=truncation_start_y_m,
    )
    if not full_payloads:
        return PlanningBudgetingV1(
            status="unsupported",
            total_bl_thickness_m=float(base_total_thickness_m),
            notes=["No BL budgeting samples were produced from the provided sections."],
        )

    by_section: dict[float, list[dict[str, float]]] = defaultdict(list)
    for payload in full_payloads:
        by_section[round(float(payload["span_y_m"]), 6)].append(payload)
    ordered_section_y = sorted(by_section)

    def _span_window_for_section(index: int) -> dict[str, float]:
        center = float(ordered_section_y[index])
        lower = (
            center
            if index == 0
            else 0.5 * (float(ordered_section_y[index - 1]) + center)
        )
        upper = (
            center
            if index == len(ordered_section_y) - 1
            else 0.5 * (center + float(ordered_section_y[index + 1]))
        )
        return {"min": float(lower), "max": float(upper)}

    section_budgets: list[PlanningBudgetSectionV1] = []
    for index, section_y in enumerate(ordered_section_y):
        payloads = by_section[section_y]
        sample_count = len(payloads)
        triggered_sample_count = sum(1 for payload in payloads if float(payload["scale"]) < 0.999999)
        min_clearance_ratio = min(
            float(payload["local_half_thickness_m"]) / max(float(base_total_thickness_m), 1.0e-12)
            for payload in payloads
        )
        min_allowed_total_thickness = min(
            float(payload["raw_allowed_total_thickness_m"]) for payload in payloads
        )
        min_available_budget_ratio = float(min_allowed_total_thickness) / max(
            float(base_total_thickness_m),
            1.0e-12,
        )
        min_required_scale = min(float(payload["required_scale_for_tip_clearance"]) for payload in payloads)
        clearance_pressure = max(0.0, float(1.0 - min_available_budget_ratio))
        clearance_ratio_deficit = max(0.0, float(1.0 - min_clearance_ratio))
        budget_ratio_deficit = max(0.0, float(1.0 - min_available_budget_ratio))
        span_y_range_m = _span_window_for_section(index)
        region_kind = "baseline_clearance_zone"
        if truncation_start_y_m is not None and float(section_y) >= float(truncation_start_y_m) - 1.0e-12:
            region_kind = "suppressed_tip_zone"
        elif any(int(payload["truncation_candidate"]) == 1 for payload in payloads):
            region_kind = "tip_truncation_candidate_zone"
        elif any(int(payload["tip_clearance_active"]) == 1 for payload in payloads):
            region_kind = "tip_clearance_active_zone"
        elif triggered_sample_count > 0:
            region_kind = "outboard_scaling_zone"

        recommended_action_kinds: list[str] = []
        if min_available_budget_ratio < 0.999999 or min_clearance_ratio < 1.0 - 1.0e-12:
            recommended_action_kinds.append("shrink_total_thickness")
        if region_kind in {
            "outboard_scaling_zone",
            "tip_clearance_active_zone",
            "tip_truncation_candidate_zone",
            "suppressed_tip_zone",
        } or 0 < triggered_sample_count < sample_count:
            recommended_action_kinds.append("split_region_budget")
        if any(int(payload["thickness_limited"]) == 1 or int(payload["tip_limited"]) == 1 for payload in payloads):
            recommended_action_kinds.append("stage_back_layers")
        if any(int(payload["truncation_candidate"]) == 1 for payload in payloads):
            recommended_action_kinds.append("truncate_tip_zone")
        recommended_action_kinds = list(dict.fromkeys(recommended_action_kinds))
        recommendations: list[PlanningBudgetRecommendationV1] = []
        for action_kind in recommended_action_kinds:
            if action_kind == "shrink_total_thickness":
                recommendations.append(
                    PlanningBudgetRecommendationV1(
                        kind="shrink_total_thickness",
                        direction="decrease_total_thickness",
                        span_y_range_m=span_y_range_m,
                        delta_total_thickness_m=float(
                            max(0.0, float(base_total_thickness_m) - float(min_allowed_total_thickness))
                        ),
                        delta_total_thickness_ratio=float(budget_ratio_deficit),
                        notes=[
                            "Plan-only recommendation based on the tightest local allowed total thickness in this section window.",
                        ],
                    )
                )
            elif action_kind == "split_region_budget":
                recommendations.append(
                    PlanningBudgetRecommendationV1(
                        kind="split_region_budget",
                        direction="split_outboard_budget_zone",
                        span_y_range_m=span_y_range_m,
                        notes=["Separate this pressured span window from the inboard budget before changing runtime BL settings."],
                    )
                )
            elif action_kind == "stage_back_layers":
                recommendations.append(
                    PlanningBudgetRecommendationV1(
                        kind="stage_back_layers",
                        direction="reduce_layers_outboard_first",
                        span_y_range_m=span_y_range_m,
                        notes=["This window contains thickness-limited or tip-limited samples; prefer staged layer rollback here first."],
                    )
                )
            elif action_kind == "truncate_tip_zone":
                recommendations.append(
                    PlanningBudgetRecommendationV1(
                        kind="truncate_tip_zone",
                        direction="move_truncation_inboard",
                        span_y_range_m=span_y_range_m,
                        suggested_truncation_start_y_m=float(section_y),
                        notes=["This section window is already a truncation candidate under the planning policy."],
                    )
                )

        min_local_half_thickness = min(
            float(payload["local_half_thickness_m"]) for payload in payloads
        )
        manual_edit_candidates = (
            [
                _build_budget_manual_edit_candidate(
                    target_kind="section",
                    target_id=f"section_y:{section_y:.6f}",
                    span_y_range_m=span_y_range_m,
                    current_total_bl_thickness_m=float(base_total_thickness_m),
                    min_local_clearance_m=float(min_local_half_thickness),
                    current_clearance_ratio=float(min_clearance_ratio),
                    ratio_deficit=float(clearance_ratio_deficit),
                    available_budget_ratio=float(min_available_budget_ratio),
                    available_budget_ratio_deficit=float(budget_ratio_deficit),
                    recommended_action_kinds=recommended_action_kinds,
                    recommendations=recommendations,
                )
            ]
            if recommended_action_kinds
            else []
        )
        section_budgets.append(
            PlanningBudgetSectionV1(
                section_id=f"section_y:{section_y:.6f}",
                span_y_m=float(section_y),
                span_y_range_m=span_y_range_m,
                region_kind=region_kind,
                sample_count=sample_count,
                triggered_sample_count=triggered_sample_count,
                min_local_half_thickness_m=float(min_local_half_thickness),
                min_clearance_to_thickness_ratio=float(min_clearance_ratio),
                clearance_to_thickness_ratio_deficit=float(clearance_ratio_deficit),
                min_available_budget_ratio=float(min_available_budget_ratio),
                available_budget_ratio_deficit=float(budget_ratio_deficit),
                min_required_scale_for_tip_clearance=float(min_required_scale),
                min_predicted_bl_top_clearance_m=min(
                    float(payload["predicted_bl_top_clearance_m"]) for payload in payloads
                ),
                clearance_pressure=float(clearance_pressure),
                recommended_action_kinds=recommended_action_kinds,
                recommendations=recommendations,
                manual_edit_candidates=manual_edit_candidates,
                notes=[
                    "Budgeting guidance is plan-only and should not be auto-applied to runtime geometry.",
                    *(
                        ["suppressed_by_truncation_window"]
                        if region_kind == "suppressed_tip_zone" and suppressed_payloads
                        else []
                    ),
                ],
            )
        )

    region_groups: dict[str, list[PlanningBudgetSectionV1]] = defaultdict(list)
    for section in section_budgets:
        region_groups[section.region_kind].append(section)

    def _recommendation_metric_by_kind(
        section: PlanningBudgetSectionV1,
        action_kind: str,
        field_name: str,
    ) -> float | None:
        for recommendation in section.recommendations:
            if recommendation.kind != action_kind:
                continue
            value = getattr(recommendation, field_name)
            if value is not None:
                return float(value)
        return None

    region_budgets: list[PlanningBudgetRegionV1] = []
    for region_kind, grouped_sections in region_groups.items():
        section_ids = [section.section_id for section in grouped_sections]
        span_y_range_m = {
            "min": float(
                min(
                    section.span_y_range_m.get("min", section.span_y_m)
                    for section in grouped_sections
                )
            ),
            "max": float(
                max(
                    section.span_y_range_m.get("max", section.span_y_m)
                    for section in grouped_sections
                )
            ),
        }
        min_clearance_ratio = min(
            section.min_clearance_to_thickness_ratio for section in grouped_sections
        )
        min_budget_ratio = min(
            section.min_available_budget_ratio for section in grouped_sections
        )
        peak_clearance_pressure = max(
            section.clearance_pressure if section.clearance_pressure is not None else 0.0
            for section in grouped_sections
        )
        recommended_action_kinds = list(
            dict.fromkeys(
                action
                for section in grouped_sections
                for action in section.recommended_action_kinds
            )
        )
        recommendations: list[PlanningBudgetRecommendationV1] = []
        for action_kind in recommended_action_kinds:
            if action_kind == "shrink_total_thickness":
                shrink_deltas = [
                    value
                    for value in (
                        _recommendation_metric_by_kind(
                            section,
                            "shrink_total_thickness",
                            "delta_total_thickness_m",
                        )
                        for section in grouped_sections
                    )
                    if value is not None
                ]
                recommendations.append(
                    PlanningBudgetRecommendationV1(
                        kind="shrink_total_thickness",
                        direction="decrease_total_thickness",
                        span_y_range_m=span_y_range_m,
                        delta_total_thickness_m=float(
                            max(shrink_deltas) if shrink_deltas else 0.0
                        ),
                        delta_total_thickness_ratio=float(max(0.0, 1.0 - float(min_budget_ratio))),
                    )
                )
            elif action_kind == "split_region_budget":
                recommendations.append(
                    PlanningBudgetRecommendationV1(
                        kind="split_region_budget",
                        direction="split_outboard_budget_zone",
                        span_y_range_m=span_y_range_m,
                    )
                )
            elif action_kind == "stage_back_layers":
                recommendations.append(
                    PlanningBudgetRecommendationV1(
                        kind="stage_back_layers",
                        direction="reduce_layers_outboard_first",
                        span_y_range_m=span_y_range_m,
                    )
                )
            elif action_kind == "truncate_tip_zone":
                recommendations.append(
                    PlanningBudgetRecommendationV1(
                        kind="truncate_tip_zone",
                        direction="move_truncation_inboard",
                        span_y_range_m=span_y_range_m,
                        suggested_truncation_start_y_m=float(span_y_range_m["min"]),
                    )
                )
        min_local_clearance = min(
            float(section.min_local_half_thickness_m)
            for section in grouped_sections
            if section.min_local_half_thickness_m is not None
        )
        region_manual_edit_candidates = (
            [
                _build_budget_manual_edit_candidate(
                    target_kind="region",
                    target_id=f"region:{region_kind}",
                    span_y_range_m=span_y_range_m,
                    current_total_bl_thickness_m=float(base_total_thickness_m),
                    min_local_clearance_m=float(min_local_clearance),
                    current_clearance_ratio=float(min_clearance_ratio),
                    ratio_deficit=float(max(0.0, 1.0 - float(min_clearance_ratio))),
                    available_budget_ratio=float(min_budget_ratio),
                    available_budget_ratio_deficit=float(max(0.0, 1.0 - float(min_budget_ratio))),
                    recommended_action_kinds=recommended_action_kinds,
                    recommendations=recommendations,
                )
            ]
            if recommended_action_kinds
            else []
        )
        region_budgets.append(
            PlanningBudgetRegionV1(
                region_id=f"region:{region_kind}",
                region_kind=region_kind,
                section_ids=section_ids,
                section_count=len(grouped_sections),
                span_y_range_m=span_y_range_m,
                min_clearance_to_thickness_ratio=min_clearance_ratio,
                clearance_to_thickness_ratio_deficit=float(max(0.0, 1.0 - float(min_clearance_ratio))),
                min_available_budget_ratio=min_budget_ratio,
                available_budget_ratio_deficit=float(max(0.0, 1.0 - float(min_budget_ratio))),
                peak_clearance_pressure=float(peak_clearance_pressure),
                recommended_action_kinds=recommended_action_kinds,
                recommendations=recommendations,
                manual_edit_candidates=region_manual_edit_candidates,
                notes=[
                    "Regionwise budgeting groups sections by observed clearance-pressure regime, not by topology family.",
                ],
            )
        )

    ranked_sections = sorted(
        section_budgets,
        key=lambda section: (
            float(section.min_available_budget_ratio if section.min_available_budget_ratio is not None else 999.0),
            float(section.min_clearance_to_thickness_ratio if section.min_clearance_to_thickness_ratio is not None else 999.0),
            -float(section.span_y_m),
        ),
    )
    ranked_regions = sorted(
        region_budgets,
        key=lambda region: (
            float(region.min_available_budget_ratio if region.min_available_budget_ratio is not None else 999.0),
            float(region.min_clearance_to_thickness_ratio if region.min_clearance_to_thickness_ratio is not None else 999.0),
        ),
    )
    recommendation_kinds = list(
        dict.fromkeys(
            action
            for section in section_budgets
            for action in section.recommended_action_kinds
        )
    )
    manual_edit_candidates = [
        candidate
        for budget in [*ranked_sections[:3], *ranked_regions[:3]]
        for candidate in budget.manual_edit_candidates
    ]
    return PlanningBudgetingV1(
        status="available",
        total_bl_thickness_m=float(base_total_thickness_m),
        section_budgets=section_budgets,
        region_budgets=region_budgets,
        tightest_section_ids=[section.section_id for section in ranked_sections[:3]],
        tightest_region_ids=[region.region_id for region in ranked_regions[:3]],
        tightest_sections=[section.model_copy(deep=True) for section in ranked_sections[:3]],
        tightest_regions=[region.model_copy(deep=True) for region in ranked_regions[:3]],
        recommendation_kinds=recommendation_kinds,
        manual_edit_candidates=[candidate.model_copy(deep=True) for candidate in manual_edit_candidates],
        notes=[
            "Sectionwise/regionwise budgeting remains planning-only guidance.",
            "Recommendations do not mutate shell_v4 geometry or BL settings at runtime.",
        ],
    )


def _analyze_real_wing_tip_bl_interference(
    *,
    sections: list[dict[str, Any]],
    protection: dict[str, Any],
    base_total_thickness_m: float,
    half_span_m: float,
    span_samples_per_interval: int = 13,
    chordwise_samples: int = 19,
    truncation_start_y_m: float | None = None,
) -> dict[str, Any]:
    if not bool(protection.get("enabled", True)) or len(sections) < 2:
        return {
            "enabled": False,
            "intervention_mode": "none",
            "sample_count": 0,
            "risk_sample_count": 0,
            "tip_truncation": {"enabled": False, "start_y_m": None},
        }
    full_payloads, retained_payloads, suppressed_payloads = _sample_real_wing_bl_interference_payloads(
        sections=sections,
        protection=protection,
        base_total_thickness_m=base_total_thickness_m,
        half_span_m=half_span_m,
        span_samples_per_interval=span_samples_per_interval,
        chordwise_samples=chordwise_samples,
        truncation_start_y_m=truncation_start_y_m,
    )
    y_values = [float(section["y_le"]) for section in sections]

    if not full_payloads:
        return {
            "enabled": True,
            "intervention_mode": "none",
            "sample_count": 0,
            "risk_sample_count": 0,
            "tip_truncation": {"enabled": False, "start_y_m": truncation_start_y_m},
        }

    risk_samples = [payload for payload in retained_payloads if int(payload["tip_clearance_risk"]) == 1]
    suppressed_risk_samples = [
        payload for payload in suppressed_payloads if int(payload["tip_clearance_risk"]) == 1
    ]
    full_risk_samples = [payload for payload in full_payloads if int(payload["tip_clearance_risk"]) == 1]
    truncation_samples = [payload for payload in full_payloads if int(payload["truncation_candidate"]) == 1]
    truncation_guard_samples = [
        payload
        for payload in full_payloads
        if int(payload["tip_clearance_active"]) == 1 and payload["scale"] < 0.999999
    ]
    retained_scaling_active = any(payload["scale"] < 0.999999 for payload in retained_payloads)
    full_scaling_active = any(payload["scale"] < 0.999999 for payload in full_payloads)
    tip_truncation_enabled = truncation_start_y_m is not None or bool(truncation_samples)
    intervention_mode = "none"
    if retained_scaling_active:
        intervention_mode = "scaling_only"
    if tip_truncation_enabled:
        intervention_mode = "truncation_only"
        if full_scaling_active:
            intervention_mode = "scaling_and_truncation"

    tip_truncation_start_y = truncation_start_y_m
    if truncation_samples:
        anchor = min(
            truncation_guard_samples or truncation_samples,
            key=lambda payload: float(payload["span_y_m"]),
        )
        buffer_m = float(protection.get("tip_truncation_inboard_buffer_chords", 0.0) or 0.0) * float(
            anchor["local_chord_m"]
        )
        recommended_tip_truncation_start_y = max(float(y_values[0]), float(anchor["span_y_m"]) - buffer_m)
        if tip_truncation_start_y is None:
            tip_truncation_start_y = recommended_tip_truncation_start_y
    
    analysis: dict[str, Any] = {
        "enabled": True,
        "intervention_mode": intervention_mode,
        "sample_count": int(len(retained_payloads)),
        "retained_sample_count": int(len(retained_payloads)),
        "suppressed_sample_count": int(len(suppressed_payloads)),
        "full_sample_count": int(len(full_payloads)),
        "risk_sample_count": int(len(risk_samples)),
        "suppressed_risk_sample_count": int(len(suppressed_risk_samples)),
        "full_risk_sample_count": int(len(full_risk_samples)),
        "required_min_bl_top_clearance_m": float(
            max(payload["required_min_bl_top_clearance_m"] for payload in full_payloads)
        ),
        "min_predicted_bl_top_clearance_m": float(
            min(
                payload["predicted_bl_top_clearance_m"]
                for payload in (retained_payloads or full_payloads)
            )
        ),
        "full_min_predicted_bl_top_clearance_m": float(
            min(payload["predicted_bl_top_clearance_m"] for payload in full_payloads)
        ),
        "tip_truncation": {
            "enabled": bool(tip_truncation_enabled),
            "start_y_m": float(tip_truncation_start_y) if tip_truncation_start_y is not None else None,
            "suppressed_sample_count": int(len(suppressed_payloads)),
            "suppressed_risk_sample_count": int(len(suppressed_risk_samples)),
        },
    }
    if retained_payloads:
        analysis["retained_min_predicted_bl_top_clearance_m"] = float(
            min(payload["predicted_bl_top_clearance_m"] for payload in retained_payloads)
        )
    if risk_samples:
        analysis["triggered_span_y_range_m"] = {
            "min": float(min(payload["span_y_m"] for payload in risk_samples)),
            "max": float(max(payload["span_y_m"] for payload in risk_samples)),
        }
        analysis["triggered_tip_distance_range_m"] = {
            "min": float(min(payload["tip_distance_m"] for payload in risk_samples)),
            "max": float(max(payload["tip_distance_m"] for payload in risk_samples)),
        }
    if suppressed_risk_samples:
        analysis["suppressed_risk_span_y_range_m"] = {
            "min": float(min(payload["span_y_m"] for payload in suppressed_risk_samples)),
            "max": float(max(payload["span_y_m"] for payload in suppressed_risk_samples)),
        }
        analysis["suppressed_risk_tip_distance_range_m"] = {
            "min": float(min(payload["tip_distance_m"] for payload in suppressed_risk_samples)),
            "max": float(max(payload["tip_distance_m"] for payload in suppressed_risk_samples)),
        }
    if truncation_samples:
        analysis["tip_truncation"]["required_scale_range"] = {
            "min": float(min(payload["required_scale_for_tip_clearance"] for payload in truncation_samples)),
            "max": float(max(payload["required_scale_for_tip_clearance"] for payload in truncation_samples)),
        }
        analysis["tip_truncation"]["recommended_start_y_m"] = float(recommended_tip_truncation_start_y)
    analysis["planning_budgeting"] = _build_real_wing_bl_budgeting_plan(
        sections=sections,
        protection=protection,
        base_total_thickness_m=base_total_thickness_m,
        half_span_m=half_span_m,
        truncation_start_y_m=truncation_start_y_m,
    ).model_dump(mode="json")
    return analysis


def _interpolate_real_wing_section(
    lower_section: dict[str, Any],
    upper_section: dict[str, Any],
    *,
    y_target: float,
    branch_samples: int = 31,
) -> dict[str, Any]:
    y0 = float(lower_section["y_le"])
    y1 = float(upper_section["y_le"])
    if abs(y1 - y0) <= 1.0e-12:
        ratio = 0.0
    else:
        ratio = float((y_target - y0) / (y1 - y0))

    lower_upper_branch, lower_lower_branch = _section_thickness_branches(lower_section)
    upper_upper_branch, upper_lower_branch = _section_thickness_branches(upper_section)
    x_samples = [
        float(0.5 * (1.0 - math.cos(math.pi * index / max(branch_samples - 1, 1))))
        for index in range(max(3, int(branch_samples)))
    ]
    upper_coords = []
    for x_value in reversed(x_samples):
        z_lower = _interpolate_branch(lower_upper_branch, x_value)
        z_upper = _interpolate_branch(upper_upper_branch, x_value)
        upper_coords.append((x_value, _interpolate_between_sections(z_lower, z_upper, ratio)))
    lower_coords = []
    for x_value in x_samples[1:-1]:
        z_lower = _interpolate_branch(lower_lower_branch, x_value)
        z_upper = _interpolate_branch(upper_lower_branch, x_value)
        lower_coords.append((x_value, _interpolate_between_sections(z_lower, z_upper, ratio)))
    airfoil_coordinates = upper_coords + lower_coords + [upper_coords[0]]

    synthetic_section = copy.deepcopy(lower_section)
    synthetic_section.update(
        {
            "x_le": _interpolate_between_sections(float(lower_section["x_le"]), float(upper_section["x_le"]), ratio),
            "y_le": float(y_target),
            "z_le": _interpolate_between_sections(float(lower_section["z_le"]), float(upper_section["z_le"]), ratio),
            "chord": _interpolate_between_sections(float(lower_section["chord"]), float(upper_section["chord"]), ratio),
            "twist_deg": _interpolate_between_sections(
                float(lower_section.get("twist_deg", 0.0) or 0.0),
                float(upper_section.get("twist_deg", 0.0) or 0.0),
                ratio,
            ),
            "airfoil_name": f"synthetic_tip_cut_{y_target:.4f}m",
            "airfoil_source": "interpolated_tip_truncation_section",
            "airfoil_coordinates": airfoil_coordinates,
            "synthetic_tip_cut": True,
        }
    )
    return synthetic_section


def _insert_real_wing_section_if_needed(
    *,
    sections: list[dict[str, Any]],
    y_target: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if y_target is None or len(sections) < 2:
        return list(sections), {"inserted_section": False, "y_target_m": y_target}

    y_values = [float(section["y_le"]) for section in sections]
    if y_target <= y_values[0] + 1.0e-9 or y_target >= y_values[-1] - 1.0e-9:
        return list(sections), {"inserted_section": False, "y_target_m": float(y_target)}
    for y_value in y_values:
        if abs(float(y_target) - y_value) <= 1.0e-9:
            return list(sections), {"inserted_section": False, "y_target_m": float(y_value)}

    lower_index, upper_index, _ = _bracketing_section_indices(list(sections), float(y_target))
    lower_section = sections[lower_index]
    upper_section = sections[min(upper_index, len(sections) - 1)]
    synthetic_section = _interpolate_real_wing_section(
        lower_section,
        upper_section,
        y_target=float(y_target),
    )
    augmented = list(sections[: upper_index]) + [synthetic_section] + list(sections[upper_index:])
    return augmented, {
        "inserted_section": True,
        "y_target_m": float(y_target),
        "inserted_index": int(upper_index),
    }


def _augment_real_wing_sections_for_tip_truncation(
    *,
    sections: list[dict[str, Any]],
    start_y_m: float | None,
    protection: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if start_y_m is None or len(sections) < 2:
        return list(sections), {"enabled": False, "inserted_section": False, "start_y_m": start_y_m}

    protection_config = dict(protection or {})
    connector_band_start_y = _tip_truncation_connector_band_start_y_m(
        sections=list(sections),
        start_y_m=float(start_y_m),
        protection=protection_config,
    )
    augmented = list(sections)
    inserted_any = False
    insertion_records: dict[str, dict[str, Any]] = {}
    y_targets = [
        ("connector_band", connector_band_start_y),
        ("start", float(start_y_m)),
    ]
    for label, y_target in sorted(
        ((label, y_target) for label, y_target in y_targets if y_target is not None),
        key=lambda item: float(item[1]),
    ):
        augmented, insertion_records[label] = _insert_real_wing_section_if_needed(
            sections=augmented,
            y_target=float(y_target),
        )
        inserted_any = inserted_any or bool(insertion_records[label]["inserted_section"])
    return augmented, {
        "enabled": True,
        "inserted_section": bool(inserted_any),
        "start_y_m": float(start_y_m),
        "connector_band_start_y_m": float(connector_band_start_y) if connector_band_start_y is not None else None,
        "inserted_index": insertion_records.get("start", {}).get("inserted_index"),
        "inserted_start_section": bool(insertion_records.get("start", {}).get("inserted_section", False)),
        "inserted_connector_band_section": bool(
            insertion_records.get("connector_band", {}).get("inserted_section", False)
        ),
    }


def _real_main_wing_geometry_from_sections(
    *,
    base_geometry: dict[str, Any],
    sections: list[dict[str, Any]],
    artifact_path: Path,
) -> dict[str, Any]:
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
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_report(
        artifact_path,
        {
            "source_path": base_geometry["source_path"],
            "component": base_geometry["component"],
            "surface_name": base_geometry["surface_name"],
            "selected_section_count": len(sections),
            "selected_section_y_le_m": [float(section["y_le"]) for section in sections],
            "sections": sections,
            "overall_bounds": overall_bounds,
        },
    )
    return {
        "shape_mode": DEFAULT_REAL_MAIN_WING_SHAPE_MODE,
        "source_path": str(base_geometry["source_path"]),
        "component": base_geometry["component"],
        "surface_name": base_geometry["surface_name"],
        "surface_rotation_deg": list(base_geometry.get("surface_rotation_deg") or [0.0, 0.0, 0.0]),
        "sections": sections,
        "section_profiles": section_profiles,
        "section_bounds": section_bounds,
        "overall_bounds": overall_bounds,
        "artifact_path": str(artifact_path),
    }


def _resolve_pre_plc_repro_section_offsets(section_count: int, offsets: list[int]) -> list[int]:
    resolved: list[int] = []
    for offset in offsets:
        index = int(offset)
        if index < 0:
            index = section_count + index
        if index < 0 or index >= section_count:
            raise IndexError(f"pre-PLC fixture section index out of range: {offset}")
        if index not in resolved:
            resolved.append(index)
    return resolved


def _build_shell_v4_pre_plc_repro_fixture(
    *,
    source_path: Path,
    component: str,
    family: str,
    artifact_dir: Path,
) -> dict[str, Any]:
    family_config = PRE_PLC_REPRO_FAMILY_CONFIGS.get(family)
    if family_config is None:
        raise ValueError(f"Unsupported shell_v4 pre-PLC repro fixture family: {family}")
    base_geometry = _resolve_real_main_wing_geometry(
        geometry={
            "shape_mode": DEFAULT_REAL_MAIN_WING_SHAPE_MODE,
            "source_path": str(source_path),
            "component": component,
        },
        artifact_dir=artifact_dir / "base_geometry",
    )
    spec = build_shell_v4_half_wing_bl_macsafe_spec("BL_macsafe_baseline")
    protection = dict(spec.get("real_wing_bl_protection", {}))
    analysis = _analyze_real_wing_tip_bl_interference(
        sections=list(base_geometry["sections"]),
        protection=protection,
        base_total_thickness_m=float(spec["boundary_layer"]["target_total_thickness_m"]),
        half_span_m=float(base_geometry["overall_bounds"]["y_max"]),
    )
    start_y_m = float((analysis.get("tip_truncation") or {}).get("start_y_m") or base_geometry["overall_bounds"]["y_max"])
    augmented_sections, truncation = _augment_real_wing_sections_for_tip_truncation(
        sections=list(base_geometry["sections"]),
        start_y_m=start_y_m,
        protection=protection,
    )
    selected_indices = _resolve_pre_plc_repro_section_offsets(
        len(augmented_sections),
        list(family_config["section_index_offsets"]),
    )
    selected_sections = [copy.deepcopy(augmented_sections[index]) for index in selected_indices]
    geometry_payload = _real_main_wing_geometry_from_sections(
        base_geometry=base_geometry,
        sections=selected_sections,
        artifact_path=artifact_dir / f"{family}_sections.json",
    )
    return {
        "fixture_id": f"shell_v4_pre_plc::{family}",
        "family": family,
        "component": component,
        "source_path": str(source_path),
        "selected_section_indices": selected_indices,
        "selected_section_y_le_m": [float(section["y_le"]) for section in selected_sections],
        "expected_failure_kind": str(family_config["expected_failure_kind"]),
        "expected_error_substrings": list(family_config["expected_error_substrings"]),
        "tip_truncation_seed": {
            "requested_start_y_m": float(start_y_m),
            "resolved": truncation,
        },
        "geometry": geometry_payload,
    }


def _build_shell_v4_pre_plc_fixture_topology_report(
    fixture: dict[str, Any],
) -> dict[str, Any]:
    resolved = dict((fixture.get("tip_truncation_seed") or {}).get("resolved") or {})
    post_band_transition_seed = dict(fixture.get("post_band_transition_seed") or {})
    boundary_recovery_seed = dict(fixture.get("post_transition_boundary_recovery_seed") or {})
    selected_section_y_le_m = [float(value) for value in fixture.get("selected_section_y_le_m", [])]
    return {
        "representation": "shell_v4_pre_plc_fixture",
        "source_kind": "fixture",
        "units": "m",
        "body_count": 1,
        "surface_count": max(len(selected_section_y_le_m) - 1, 0),
        "volume_count": 1,
        "source_path": str(fixture.get("source_path") or ""),
        "export_path": str(fixture.get("geometry", {}).get("artifact_path") or ""),
        "compiler_context": {
            "truncation_connector_band": {
                "enabled": bool(resolved.get("enabled")),
                "root_y_le_m": selected_section_y_le_m[0] if selected_section_y_le_m else None,
                "connector_band_start_y_le_m": resolved.get("connector_band_start_y_m"),
                "truncation_start_y_le_m": resolved.get("start_y_m"),
                "tip_y_le_m": selected_section_y_le_m[-1] if selected_section_y_le_m else None,
                "selected_section_y_le_m": selected_section_y_le_m,
                "post_band_transition_guard_y_le_m": post_band_transition_seed.get("guard_y_le_m"),
                "post_transition_boundary_recovery_relief_y_le_m": boundary_recovery_seed.get(
                    "relief_y_le_m"
                ),
            }
        },
    }


def _build_shell_v4_pre_plc_fixture_topology_lineage_report(
    fixture: dict[str, Any],
) -> dict[str, Any]:
    sections = [dict(section) for section in fixture.get("geometry", {}).get("sections", [])]
    rule_sections: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        if index == 0:
            side = "center_or_start"
        elif index == len(sections) - 1:
            side = "right_tip"
        else:
            side = "right_span"
        rule_sections.append(
            {
                "rule_section_index": index,
                "source_section_index": index,
                "mirrored": False,
                "side": side,
                "x_le": float(section.get("x_le", 0.0)),
                "y_le": float(section.get("y_le", 0.0)),
                "z_le": float(section.get("z_le", 0.0)),
                "chord": float(section.get("chord", 0.0)),
                "twist_deg": float(section.get("twist_deg", 0.0)),
                "airfoil_source": str(section.get("airfoil_source", "inline_coordinates")),
            }
        )
    return {
        "status": "captured",
        "surface_count": 1,
        "surfaces": [
            {
                "component": str(fixture.get("component") or "main_wing"),
                "geom_id": f"fixture::{fixture.get('family', 'unknown')}",
                "name": str(fixture.get("family") or "fixture"),
                "caps_group": str(fixture.get("component") or "main_wing"),
                "symmetric_xz": False,
                "source_section_count": len(rule_sections),
                "rule_section_count": len(rule_sections),
                "rule_sections": rule_sections,
                "terminal_strip_candidates": [],
            }
        ],
        "notes": [],
    }


def _apply_truncation_connector_band_operator_to_pre_plc_fixture(
    fixture: dict[str, Any],
    *,
    artifact_dir: Path,
) -> dict[str, Any]:
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    topology_report = _build_shell_v4_pre_plc_fixture_topology_report(fixture)
    topology_lineage_report = _build_shell_v4_pre_plc_fixture_topology_lineage_report(fixture)
    topology_suppression_report = {
        "status": "captured",
        "applied": False,
        "surface_count": 1,
        "suppressed_source_section_count": 0,
        "surfaces": [{"suppressed_source_section_indices": [], "suppressed_sections": [], "applied": False}],
        "notes": [],
    }
    topology_ir = build_topology_ir_v1(
        topology_report=topology_report,
        topology_lineage_report=topology_lineage_report,
        topology_suppression_report=topology_suppression_report,
        component=str(fixture.get("component") or "main_wing"),
    )
    motif_match = next(
        (
            match
            for match in MotifRegistryV1().detect(topology_ir).matches
            if match.kind == "TRUNCATION_CONNECTOR_BAND"
        ),
        None,
    )
    if motif_match is None:
        raise RuntimeError("TRUNCATION_CONNECTOR_BAND motif was not classified for the pre-PLC fixture")

    operator_result = OperatorLibraryV1().execute(
        "regularize_truncation_connector_band",
        motif_match,
        topology_ir,
    )

    regularized_fixture = copy.deepcopy(fixture)
    original_sections = [copy.deepcopy(section) for section in fixture.get("geometry", {}).get("sections", [])]
    if operator_result.applied:
        drop_section_y_le_m = {
            float(value)
            for value in operator_result.details["regularization_plan"].get("drop_section_y_le_m", [])
        }
        kept_sections = [
            section
            for section in original_sections
            if float(section.get("y_le", 0.0)) not in drop_section_y_le_m
        ]
    else:
        kept_sections = original_sections

    kept_y_le_m = [float(section.get("y_le", 0.0)) for section in kept_sections]
    regularized_fixture["selected_section_y_le_m"] = kept_y_le_m
    regularized_fixture["selected_section_indices"] = [
        index for index, section in enumerate(kept_sections)
    ]
    regularized_fixture["geometry"]["sections"] = kept_sections
    regularized_fixture["geometry"]["selected_section_count"] = len(kept_sections)
    regularized_fixture["geometry"]["selected_section_y_le_m"] = kept_y_le_m

    report_path = artifact_dir / "truncation_connector_band_regularization_report.json"
    write_json_report(
        report_path,
        {
            "fixture_id": fixture.get("fixture_id"),
            "family": fixture.get("family"),
            "operator_result": operator_result.model_dump(mode="json"),
            "selected_section_y_le_m_before": list(fixture.get("selected_section_y_le_m", [])),
            "selected_section_y_le_m_after": kept_y_le_m,
        },
    )
    return {
        "fixture": regularized_fixture,
        "operator_result": operator_result.model_dump(mode="json"),
        "report_path": str(report_path),
    }


def _pre_plc_observed_check_kind_from_failure_kind(
    observed_failure_kind: str | None,
) -> str | None:
    mapping = {
        "segment_facet_intersection": "segment_facet_intersection_risk",
        "facet_facet_overlap": "facet_facet_overlap_risk",
        "boundary_recovery_error_2": "boundary_recovery_error_2_risk",
        FAILED_STEINER_RESIDUAL_FAMILY: "boundary_recovery_error_2_risk",
    }
    return mapping.get(str(observed_failure_kind or ""))


def _section_at_span_y(
    sections: list[dict[str, Any]],
    y_value: float | None,
    *,
    tolerance: float = 1.0e-6,
) -> dict[str, Any] | None:
    if y_value is None:
        return None
    for section in sections:
        if abs(float(section.get("y_le", 0.0)) - float(y_value)) <= tolerance:
            return section
    return None


def _spanwise_yz_angle_deg(
    inboard_section: dict[str, Any] | None,
    outboard_section: dict[str, Any] | None,
) -> float | None:
    if inboard_section is None or outboard_section is None:
        return None
    dy = float(outboard_section.get("y_le", 0.0)) - float(inboard_section.get("y_le", 0.0))
    dz = float(outboard_section.get("z_le", 0.0)) - float(inboard_section.get("z_le", 0.0))
    if abs(dy) <= 1.0e-9:
        return None
    return float(math.degrees(math.atan2(dz, dy)))


def _post_relief_local_clearance_evidence(
    *,
    sections: list[dict[str, Any]],
    relief_y_le_m: float | None,
    terminal_y_le_m: float | None,
) -> dict[str, Any]:
    if relief_y_le_m is None or terminal_y_le_m is None or terminal_y_le_m <= relief_y_le_m:
        return {
            "status": "unknown",
            "reason": "missing_post_relief_span",
        }
    if len(sections) < 2:
        return {
            "status": "unknown",
            "reason": "missing_sections",
        }
    sample_y_values = [
        float(relief_y_le_m),
        float(0.5 * (relief_y_le_m + terminal_y_le_m)),
        float(terminal_y_le_m),
    ]
    samples: list[dict[str, float]] = []
    for y_value in sample_y_values:
        clearance = _real_wing_local_clearance_at_spanwise_x_rel(
            sections=sections,
            y_value=y_value,
            x_rel=0.5,
        )
        samples.append(
            {
                "span_y_m": float(y_value),
                "sample_x_rel": 0.5,
                "local_clearance_m": float(clearance["local_half_thickness_m"]),
                "local_thickness_m": float(clearance["local_thickness_m"]),
            }
        )
    return {
        "status": "inferred",
        "sample_x_rel": 0.5,
        "min_post_relief_local_clearance_m": float(
            min(sample["local_clearance_m"] for sample in samples)
        ),
        "samples": samples,
        "notes": [
            "Local clearance is inferred from section half-thickness samples, not from native BREP face distance.",
        ],
    }


def _classify_boundary_recovery_error_2_downstream_residual(
    *,
    fixture: dict[str, Any],
    observed_failure_kind: str,
    error_text: str,
) -> dict[str, Any]:
    forensic_evidence = _normalize_recoversegment_failed_steiner_evidence(
        fixture.get("boundary_recovery_forensic_evidence")
    )
    if not forensic_evidence:
        forensic_evidence = _normalize_recoversegment_failed_steiner_evidence(
            dict(fixture.get("post_transition_boundary_recovery_seed") or {}).get("forensic_evidence")
        )
    selected_y = [
        float(value)
        for value in fixture.get("selected_section_y_le_m", [])
        if value is not None
    ]
    selected_y = sorted(dict.fromkeys(selected_y))
    sections = [dict(section) for section in fixture.get("geometry", {}).get("sections", [])]
    post_band_seed = dict(fixture.get("post_band_transition_seed") or {})
    relief_seed = dict(fixture.get("post_transition_boundary_recovery_seed") or {})
    guard_y = post_band_seed.get("guard_y_le_m")
    relief_y = relief_seed.get("relief_y_le_m")
    terminal_y = selected_y[-1] if selected_y else None
    guard_y = float(guard_y) if guard_y is not None else None
    relief_y = float(relief_y) if relief_y is not None else None
    terminal_y = float(terminal_y) if terminal_y is not None else None

    guard_to_tip_span = (
        float(terminal_y - guard_y)
        if guard_y is not None and terminal_y is not None
        else None
    )
    guard_to_relief_spacing = (
        float(relief_y - guard_y)
        if guard_y is not None and relief_y is not None
        else None
    )
    relief_to_terminal_spacing = (
        float(terminal_y - relief_y)
        if relief_y is not None and terminal_y is not None
        else None
    )
    guard_to_relief_ratio = (
        float(guard_to_relief_spacing / guard_to_tip_span)
        if guard_to_relief_spacing is not None and guard_to_tip_span and guard_to_tip_span > 0.0
        else None
    )
    relief_to_terminal_ratio = (
        float(relief_to_terminal_spacing / guard_to_tip_span)
        if relief_to_terminal_spacing is not None and guard_to_tip_span and guard_to_tip_span > 0.0
        else None
    )
    min_spacing = min(
        spacing
        for spacing in (guard_to_relief_spacing, relief_to_terminal_spacing)
        if spacing is not None
    ) if guard_to_relief_spacing is not None and relief_to_terminal_spacing is not None else None
    min_spacing_ratio = (
        float(min_spacing / guard_to_tip_span)
        if min_spacing is not None and guard_to_tip_span and guard_to_tip_span > 0.0
        else None
    )

    guard_section = _section_at_span_y(sections, guard_y)
    relief_section = _section_at_span_y(sections, relief_y)
    terminal_section = _section_at_span_y(sections, terminal_y)
    guard_relief_angle = _spanwise_yz_angle_deg(guard_section, relief_section)
    relief_terminal_angle = _spanwise_yz_angle_deg(relief_section, terminal_section)
    terminal_band_angle_jump = (
        abs(float(relief_terminal_angle) - float(guard_relief_angle))
        if guard_relief_angle is not None and relief_terminal_angle is not None
        else None
    )
    orientation_monotonic_y = all(rhs > lhs for lhs, rhs in zip(selected_y[:-1], selected_y[1:]))
    orientation_positive_chords = all(float(section.get("chord", 0.0)) > 0.0 for section in sections)
    orientation_conflict = not (orientation_monotonic_y and orientation_positive_chords)
    clearance_evidence = _post_relief_local_clearance_evidence(
        sections=sections,
        relief_y_le_m=relief_y,
        terminal_y_le_m=terminal_y,
    )

    evidence = {
        "selected_section_y_le_m": selected_y,
        "residual_family": forensic_evidence.get("residual_family"),
        "evidence_level": forensic_evidence.get("evidence_level"),
        "throw_site_label": forensic_evidence.get("throw_site_label"),
        "throw_site_file": forensic_evidence.get("throw_site_file"),
        "throw_site_line": forensic_evidence.get("throw_site_line"),
        "local_surface_tags": list(forensic_evidence.get("local_surface_tags") or []),
        "local_y_band": list(forensic_evidence.get("local_y_band") or []),
        "suspicious_window": list(forensic_evidence.get("suspicious_window") or []),
        "sevent_e_type": forensic_evidence.get("sevent_e_type"),
        "degenerated_prism_seen": forensic_evidence.get("degenerated_prism_seen"),
        "guard_y_le_m": guard_y,
        "relief_y_le_m": relief_y,
        "terminal_y_le_m": terminal_y,
        "guard_to_tip_interval_span_m": guard_to_tip_span,
        "guard_to_relief_spacing_m": guard_to_relief_spacing,
        "relief_to_terminal_spacing_m": relief_to_terminal_spacing,
        "guard_to_relief_spacing_ratio": guard_to_relief_ratio,
        "relief_to_terminal_spacing_ratio": relief_to_terminal_ratio,
        "min_relief_spacing_m": min_spacing,
        "min_relief_spacing_ratio": min_spacing_ratio,
        "guard_relief_yz_angle_deg": guard_relief_angle,
        "relief_terminal_yz_angle_deg": relief_terminal_angle,
        "terminal_band_angle_jump_deg": terminal_band_angle_jump,
        "orientation_consistency": {
            "status": "conflict" if orientation_conflict else "pass",
            "monotonic_y": bool(orientation_monotonic_y),
            "positive_chords": bool(orientation_positive_chords),
        },
        "post_relief_local_clearance": clearance_evidence,
    }

    def _entry(
        *,
        family: str,
        status: str,
        reason: str,
        evidence_fields: list[str],
    ) -> dict[str, Any]:
        return {
            "family": family,
            "status": status,
            "reason": reason,
            "evidence": {
                key: evidence.get(key)
                for key in evidence_fields
            },
        }

    if observed_failure_kind != "boundary_recovery_error_2":
        return {
            "contract": "boundary_recovery_error_2_downstream_residual_classifier.v1",
            "classification_status": "not_applicable",
            "primary_residual_family": None,
            "source_failure_kind": observed_failure_kind,
            "evidence": evidence,
            "classifications": [],
            "notes": [
                "Downstream residual classification only applies after a relief rerun still observes boundary_recovery_error_2.",
            ],
        }

    missing_relief_context = (
        guard_y is None
        or relief_y is None
        or terminal_y is None
        or guard_to_tip_span is None
        or guard_to_tip_span <= 0.0
    )
    if forensic_evidence.get("residual_family") == FAILED_STEINER_RESIDUAL_FAMILY:
        classification_status = "observed_candidate"
        primary_family = FAILED_STEINER_RESIDUAL_FAMILY
    elif missing_relief_context:
        classification_status = "unknown"
        primary_family = "boundary_recovery_error_2_residual_unknown"
    else:
        classification_status = "inferred"
        primary_family = "residual_contact_near_tip_terminal"

    post_relief_too_short = (
        relief_to_terminal_spacing is not None
        and guard_to_tip_span is not None
        and relief_to_terminal_spacing <= max(0.05, 0.10 * guard_to_tip_span)
    )
    spacing_insufficient = (
        min_spacing is not None
        and guard_to_tip_span is not None
        and min_spacing <= max(0.05, 0.10 * guard_to_tip_span)
    )
    angle_jump = (
        terminal_band_angle_jump is not None
        and terminal_band_angle_jump >= 5.0
    )
    classifications = [
        _entry(
            family=FAILED_STEINER_RESIDUAL_FAMILY,
            status=(
                "observed_candidate"
                if forensic_evidence.get("residual_family") == FAILED_STEINER_RESIDUAL_FAMILY
                else "unknown"
            ),
            reason=(
                "Gmsh throw-site evidence points to addsteiner4recoversegment failing to insert a Steiner point "
                "during segment recovery near the post-band tip-terminal interval."
            ),
            evidence_fields=[
                "evidence_level",
                "throw_site_label",
                "throw_site_file",
                "throw_site_line",
                "local_surface_tags",
                "local_y_band",
                "suspicious_window",
                "sevent_e_type",
                "degenerated_prism_seen",
            ],
        ),
        _entry(
            family="residual_contact_near_tip_terminal",
            status=(
                "rejected"
                if forensic_evidence.get("residual_family") == FAILED_STEINER_RESIDUAL_FAMILY
                else "unknown" if missing_relief_context else "inferred"
            ),
            reason=(
                "Boundary recovery still fails after the bounded relief section, so the residual locus is inferred "
                "inside the narrowed relief-to-terminal interval."
            ),
            evidence_fields=[
                "relief_y_le_m",
                "terminal_y_le_m",
                "relief_to_terminal_spacing_m",
                "relief_to_terminal_spacing_ratio",
            ],
        ),
        _entry(
            family="post_relief_interval_too_short",
            status="inferred" if post_relief_too_short else "rejected",
            reason=(
                "The post-relief interval is below the deterministic minimum spacing threshold."
                if post_relief_too_short
                else "The post-relief interval is above the deterministic minimum spacing threshold."
            ),
            evidence_fields=[
                "guard_to_tip_interval_span_m",
                "relief_to_terminal_spacing_m",
                "relief_to_terminal_spacing_ratio",
            ],
        ),
        _entry(
            family="relief_section_spacing_insufficient",
            status="inferred" if spacing_insufficient else "rejected",
            reason=(
                "At least one guard/relief/terminal spacing is below the deterministic minimum spacing threshold."
                if spacing_insufficient
                else "Guard/relief/terminal spacings clear the deterministic minimum spacing threshold."
            ),
            evidence_fields=[
                "guard_to_relief_spacing_m",
                "relief_to_terminal_spacing_m",
                "min_relief_spacing_m",
                "min_relief_spacing_ratio",
            ],
        ),
        _entry(
            family="terminal_band_angle_jump",
            status=(
                "unknown"
                if terminal_band_angle_jump is None
                else "inferred"
                if angle_jump
                else "rejected"
            ),
            reason=(
                "The terminal relief-to-tip span has a local yz-angle jump above the threshold."
                if angle_jump
                else "No terminal yz-angle jump above the threshold was inferred from section frames."
            ),
            evidence_fields=[
                "guard_relief_yz_angle_deg",
                "relief_terminal_yz_angle_deg",
                "terminal_band_angle_jump_deg",
            ],
        ),
        _entry(
            family="recovery_wire_orientation_conflict",
            status="inferred" if orientation_conflict else "rejected",
            reason=(
                "The selected relief fixture has non-monotone span order or non-positive section chords."
                if orientation_conflict
                else "The relief fixture keeps monotone span order and positive section chords."
            ),
            evidence_fields=["orientation_consistency"],
        ),
        _entry(
            family="post_relief_local_clearance",
            status=str(clearance_evidence.get("status", "unknown")),
            reason="Post-relief local clearance is sampled as evidence, but this classifier does not mutate BL policy.",
            evidence_fields=["post_relief_local_clearance"],
        ),
    ]

    return {
        "contract": "boundary_recovery_error_2_downstream_residual_classifier.v1",
        "classification_status": classification_status,
        "primary_residual_family": primary_family,
        "source_failure_kind": observed_failure_kind,
        "error_text_contains_boundary_recovery_error_2": (
            "Could not recover boundary mesh: error 2" in str(error_text)
        ),
        "evidence": evidence,
        "classifications": classifications,
        "notes": [
            "This classifier is reporting-only and does not add or apply a second repair operator.",
            (
                "Runtime-native throw-site evidence upgrades this family to observed_candidate, but no sevent marker "
                "or int_point was captured, so this is not full observed contact."
                if forensic_evidence
                else "Observed Gmsh text does not expose an exact contact point, so the terminal residual locus is inferred from the bounded relief interval."
            ),
        ],
    }


def _build_pre_plc_audit_for_fixture_baseline(
    *,
    topology_ir: Any,
    fixture: dict[str, Any],
    baseline_observed: dict[str, Any] | None,
) -> Any:
    observed_evidence: list[PrePLCAuditObservedEvidenceV1] = []
    observed_failure_kind = str((baseline_observed or {}).get("observed_failure_kind") or "")
    check_kind = _pre_plc_observed_check_kind_from_failure_kind(observed_failure_kind)
    if check_kind is not None:
        forensic_evidence = (
            _recoversegment_failed_steiner_evidence_from_observed(baseline_observed)
            if check_kind == "boundary_recovery_error_2_risk"
            else {}
        )
        observed_evidence.append(
            PrePLCAuditObservedEvidenceV1(
                fixture_id=str(fixture.get("fixture_id") or ""),
                check_kind=check_kind,
                error_text=str((baseline_observed or {}).get("error") or ""),
                selected_section_y_le_m=[
                    float(value) for value in fixture.get("selected_section_y_le_m", [])
                ],
                report_path=str((baseline_observed or {}).get("report_path") or ""),
                evidence_level=str(forensic_evidence.get("evidence_level") or "observed"),
                residual_family=forensic_evidence.get("residual_family"),
                throw_site_label=forensic_evidence.get("throw_site_label"),
                throw_site_file=forensic_evidence.get("throw_site_file"),
                throw_site_line=forensic_evidence.get("throw_site_line"),
                local_surface_tags=list(forensic_evidence.get("local_surface_tags") or []),
                local_y_band=list(forensic_evidence.get("local_y_band") or []),
                suspicious_window=list(forensic_evidence.get("suspicious_window") or []),
                sevent_e_type=forensic_evidence.get("sevent_e_type"),
                degenerated_prism_seen=forensic_evidence.get("degenerated_prism_seen"),
                notes=[
                    f"observed_failure_kind={observed_failure_kind}",
                    *(
                        ["forensic_family=recoversegment_failed_insert_steiner"]
                        if forensic_evidence
                        else []
                    ),
                ],
            )
        )
    return run_pre_plc_audit_v1(
        topology_ir,
        config=PrePLCAuditConfigV1(observed_evidence=observed_evidence),
    )


def _apply_post_band_transition_split_operator_to_pre_plc_fixture(
    fixture: dict[str, Any],
    *,
    baseline_observed: dict[str, Any] | None,
    artifact_dir: Path,
) -> dict[str, Any]:
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    topology_report = _build_shell_v4_pre_plc_fixture_topology_report(fixture)
    topology_lineage_report = _build_shell_v4_pre_plc_fixture_topology_lineage_report(fixture)
    topology_suppression_report = {
        "status": "captured",
        "applied": False,
        "surface_count": 1,
        "suppressed_source_section_count": 0,
        "surfaces": [{"suppressed_source_section_indices": [], "suppressed_sections": [], "applied": False}],
        "notes": [],
    }
    topology_ir = build_topology_ir_v1(
        topology_report=topology_report,
        topology_lineage_report=topology_lineage_report,
        topology_suppression_report=topology_suppression_report,
        component=str(fixture.get("component") or "main_wing"),
    )
    audit_report = _build_pre_plc_audit_for_fixture_baseline(
        topology_ir=topology_ir,
        fixture=fixture,
        baseline_observed=baseline_observed,
    )
    motif_registry = MotifRegistryV1().detect(topology_ir, audit_report=audit_report)
    motif_match = next(
        (
            match
            for match in motif_registry.matches
            if match.kind == "CANONICAL_CONNECTOR_BAND_POST_TRANSITION"
        ),
        None,
    )
    if motif_match is None:
        contract = OperatorLibraryV1().describe("prototype_split_post_band_transition")
        operator_result = {
            "contract": "operator_result.v1",
            "operator_name": "prototype_split_post_band_transition",
            "motif_kind": "CANONICAL_CONNECTOR_BAND_POST_TRANSITION",
            "status": "rejected",
            "applied": False,
            "report_key": contract.report_key,
            "expected_artifact_keys": list(contract.expected_artifact_keys),
            "details": {
                "transition_split_plan": {
                    "contract": "post_band_transition_split_plan.v1",
                    "applicable": False,
                    "reject_reasons": ["canonical_post_band_transition_motif_not_detected"],
                    "blocking_topology_check_kinds": list(
                        getattr(audit_report, "blocking_topology_check_kinds", []) or []
                    ),
                }
            },
            "notes": [
                "The post-band transition prototype requires a canonical connector-band family with a segment-facet blocker.",
            ],
        }
        transformed_fixture = copy.deepcopy(fixture)
    else:
        operator_result_model = OperatorLibraryV1().execute(
            "prototype_split_post_band_transition",
            motif_match,
            topology_ir,
            audit_report=audit_report,
        )
        operator_result = operator_result_model.model_dump(mode="json")
        transformed_fixture = copy.deepcopy(fixture)
        original_sections = [copy.deepcopy(section) for section in fixture.get("geometry", {}).get("sections", [])]
        if operator_result_model.applied:
            split_y = operator_result["details"]["transition_split_plan"].get("proposed_split_y_le_m")
            transformed_sections, insertion_record = _insert_real_wing_section_if_needed(
                sections=original_sections,
                y_target=float(split_y) if split_y is not None else None,
            )
            transformed_y_le_m = [float(section.get("y_le", 0.0)) for section in transformed_sections]
            transformed_fixture["selected_section_y_le_m"] = transformed_y_le_m
            transformed_fixture["selected_section_indices"] = list(range(len(transformed_sections)))
            transformed_fixture["geometry"]["sections"] = transformed_sections
            transformed_fixture["geometry"]["selected_section_count"] = len(transformed_sections)
            transformed_fixture["geometry"]["selected_section_y_le_m"] = transformed_y_le_m
            transformed_fixture["post_band_transition_seed"] = {
                "enabled": True,
                "guard_y_le_m": float(split_y) if split_y is not None else None,
                "source_operator": "prototype_split_post_band_transition",
            }
            operator_result["details"]["transition_split_plan"]["inserted_section"] = bool(
                insertion_record.get("inserted_section", False)
            )
            operator_result["details"]["transition_split_plan"]["inserted_index"] = insertion_record.get(
                "inserted_index"
            )

    report_path = artifact_dir / "post_band_transition_split_report.json"
    write_json_report(
        report_path,
        {
            "fixture_id": fixture.get("fixture_id"),
            "family": fixture.get("family"),
            "baseline_observed": baseline_observed,
            "operator_result": operator_result,
            "selected_section_y_le_m_before": list(fixture.get("selected_section_y_le_m", [])),
            "selected_section_y_le_m_after": list(transformed_fixture.get("selected_section_y_le_m", [])),
        },
    )
    return {
        "fixture": transformed_fixture,
        "operator_result": operator_result,
        "report_path": str(report_path),
    }


def _apply_post_transition_boundary_recovery_operator_to_pre_plc_fixture(
    fixture: dict[str, Any],
    *,
    baseline_observed: dict[str, Any] | None,
    artifact_dir: Path,
) -> dict[str, Any]:
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    topology_report = _build_shell_v4_pre_plc_fixture_topology_report(fixture)
    topology_lineage_report = _build_shell_v4_pre_plc_fixture_topology_lineage_report(fixture)
    topology_suppression_report = {
        "status": "captured",
        "applied": False,
        "surface_count": 1,
        "suppressed_source_section_count": 0,
        "surfaces": [{"suppressed_source_section_indices": [], "suppressed_sections": [], "applied": False}],
        "notes": [],
    }
    topology_ir = build_topology_ir_v1(
        topology_report=topology_report,
        topology_lineage_report=topology_lineage_report,
        topology_suppression_report=topology_suppression_report,
        component=str(fixture.get("component") or "main_wing"),
    )
    audit_report = _build_pre_plc_audit_for_fixture_baseline(
        topology_ir=topology_ir,
        fixture=fixture,
        baseline_observed=baseline_observed,
    )
    motif_registry = MotifRegistryV1().detect(topology_ir, audit_report=audit_report)
    motif_match = next(
        (
            match
            for match in motif_registry.matches
            if match.kind == "POST_BAND_TRANSITION_BOUNDARY_RECOVERY"
        ),
        None,
    )
    if motif_match is None:
        contract = OperatorLibraryV1().describe("regularize_recoversegment_failed_steiner_post_band")
        operator_result = {
            "contract": "operator_result.v1",
            "operator_name": "regularize_recoversegment_failed_steiner_post_band",
            "motif_kind": "POST_BAND_TRANSITION_BOUNDARY_RECOVERY",
            "status": "rejected",
            "applied": False,
            "report_key": contract.report_key,
            "expected_artifact_keys": list(contract.expected_artifact_keys),
            "details": {
                "boundary_recovery_regularization_plan": {
                    "contract": "post_transition_boundary_recovery_regularization_plan.v1",
                    "applicable": False,
                    "reject_reasons": ["post_transition_boundary_recovery_motif_not_detected"],
                    "blocking_topology_check_kinds": list(
                        getattr(audit_report, "blocking_topology_check_kinds", []) or []
                    ),
                }
            },
            "notes": [
                "The boundary-recovery regularization requires a split post-band transition family with observed `error 2` evidence.",
            ],
        }
        transformed_fixture = copy.deepcopy(fixture)
    else:
        operator_result_model = OperatorLibraryV1().execute(
            "regularize_recoversegment_failed_steiner_post_band",
            motif_match,
            topology_ir,
            audit_report=audit_report,
        )
        operator_result = operator_result_model.model_dump(mode="json")
        transformed_fixture = copy.deepcopy(fixture)
        original_sections = [copy.deepcopy(section) for section in fixture.get("geometry", {}).get("sections", [])]
        forensic_evidence = _recoversegment_failed_steiner_evidence_from_observed(baseline_observed)
        if operator_result_model.applied:
            relief_y = operator_result["details"]["boundary_recovery_regularization_plan"].get(
                "proposed_relief_y_le_m"
            )
            transformed_sections, insertion_record = _insert_real_wing_section_if_needed(
                sections=original_sections,
                y_target=float(relief_y) if relief_y is not None else None,
            )
            transformed_y_le_m = [float(section.get("y_le", 0.0)) for section in transformed_sections]
            transformed_fixture["selected_section_y_le_m"] = transformed_y_le_m
            transformed_fixture["selected_section_indices"] = list(range(len(transformed_sections)))
            transformed_fixture["geometry"]["sections"] = transformed_sections
            transformed_fixture["geometry"]["selected_section_count"] = len(transformed_sections)
            transformed_fixture["geometry"]["selected_section_y_le_m"] = transformed_y_le_m
            transformed_fixture["post_transition_boundary_recovery_seed"] = {
                "enabled": True,
                "relief_y_le_m": float(relief_y) if relief_y is not None else None,
                "source_operator": "regularize_recoversegment_failed_steiner_post_band",
            }
            if forensic_evidence:
                transformed_fixture["boundary_recovery_forensic_evidence"] = dict(forensic_evidence)
                transformed_fixture["post_transition_boundary_recovery_seed"][
                    "forensic_evidence"
                ] = dict(forensic_evidence)
            operator_result["details"]["boundary_recovery_regularization_plan"][
                "inserted_section"
            ] = bool(insertion_record.get("inserted_section", False))
            operator_result["details"]["boundary_recovery_regularization_plan"][
                "inserted_index"
            ] = insertion_record.get("inserted_index")

    report_path = artifact_dir / "post_transition_boundary_recovery_regularization_report.json"
    write_json_report(
        report_path,
        {
            "fixture_id": fixture.get("fixture_id"),
            "family": fixture.get("family"),
            "baseline_observed": baseline_observed,
            "operator_result": operator_result,
            "selected_section_y_le_m_before": list(fixture.get("selected_section_y_le_m", [])),
            "selected_section_y_le_m_after": list(transformed_fixture.get("selected_section_y_le_m", [])),
        },
    )
    return {
        "fixture": transformed_fixture,
        "operator_result": operator_result,
        "report_path": str(report_path),
    }


def _shell_v4_pre_plc_repro_overrides(fixture: dict[str, Any]) -> dict[str, Any]:
    overrides = {
        "geometry": {
            "shape_mode": DEFAULT_REAL_MAIN_WING_SHAPE_MODE,
            "source_path": str(fixture["source_path"]),
            "component": str(fixture["component"]),
            "airfoil_loop_points": 48,
            "half_span_stations": 18,
            "_preloaded_real_main_wing_geometry": copy.deepcopy(fixture["geometry"]),
        },
        "boundary_layer": {
            "first_layer_height_m": 1.0e-3,
            "layers": 8,
            "growth_ratio": 1.20,
        },
        "wake_refinement": {
            "wake_length_chords": 2.0,
            "wake_height_chords": 0.4,
            "near_wake_cell_size_chords": 0.18,
        },
        "farfield": {
            "upstream_chords": 2.0,
            "downstream_chords": 3.0,
            "normal_chords": 2.0,
            "outer_cell_size_chords": 2.2,
        },
        "tip_refinement": {
            "spanwise_length_chords": 0.25,
            "cell_size_chords": 0.20,
        },
        "cell_budget": {
            "target_total_cells_min": 10_000,
            "target_total_cells_max": 500_000,
            "hard_fail_total_cells": 1_000_000,
            "min_volume_to_wall_ratio": 5.0,
            "max_bl_collapse_rate": 0.2,
        },
    }
    focused_apply = fixture.get("focused_bl_candidate_apply")
    if isinstance(focused_apply, dict) and focused_apply.get("enabled"):
        mutations = dict(focused_apply.get("focused_mutations") or {})
        layers_after = mutations.get("layers_after")
        if layers_after is not None:
            overrides["boundary_layer"]["layers"] = max(1, int(layers_after))
        forced_truncation_start = mutations.get("forced_tip_truncation_start_y_m")
        staged_transition_guard_y = mutations.get("terminal_guard_y_m")
        if forced_truncation_start is not None or staged_transition_guard_y is not None:
            protection = dict(overrides.get("real_wing_bl_protection") or {})
            if forced_truncation_start is not None:
                protection["forced_tip_truncation_start_y_m"] = float(forced_truncation_start)
            if staged_transition_guard_y is not None:
                protection["_experimental_staged_transition_guard_y_m"] = float(
                    staged_transition_guard_y
                )
                protection["_experimental_staged_transition_schedule"] = list(
                    mutations.get("staged_layer_schedule") or []
                )
            protection["_experimental_bl_candidate_apply_gate"] = str(
                focused_apply.get("apply_gate") or ""
            )
            protection["_experimental_bl_candidate_id"] = str(
                focused_apply.get("candidate_id") or ""
            )
            overrides["real_wing_bl_protection"] = protection
    return overrides


def _run_shell_v4_pre_plc_repro_fixture(
    fixture: dict[str, Any],
    *,
    out_dir: Path,
) -> dict[str, Any]:
    result = run_shell_v4_half_wing_bl_mesh_macsafe(
        out_dir=out_dir,
        run_su2=False,
        allow_swap_risk=False,
        overrides=_shell_v4_pre_plc_repro_overrides(fixture),
    )
    error_text = str(result.get("error") or "")
    observed_failure_kind = "unknown"
    if "PLC Error:  A segment and a facet intersect at point" in error_text:
        observed_failure_kind = "segment_facet_intersection"
    elif "Invalid boundary mesh (overlapping facets)" in error_text:
        observed_failure_kind = "facet_facet_overlap"
    elif "Could not recover boundary mesh: error 2" in error_text:
        observed_failure_kind = "boundary_recovery_error_2"
    result_payload = {
        "fixture_id": str(fixture["fixture_id"]),
        "family": str(fixture["family"]),
        "status": str(result.get("status")),
        "error": error_text,
        "observed_failure_kind": observed_failure_kind,
        "report_path": str(out_dir / "report.json"),
        "route_result": result,
    }
    if fixture.get("post_transition_boundary_recovery_seed"):
        result_payload["downstream_residual_classifier"] = (
            _classify_boundary_recovery_error_2_downstream_residual(
                fixture=fixture,
                observed_failure_kind=observed_failure_kind,
                error_text=error_text,
            )
        )
    return result_payload


def _find_bl_candidate(
    bl_candidate_comparison: dict[str, Any],
    candidate_id: str,
) -> dict[str, Any]:
    for candidate in list(bl_candidate_comparison.get("candidates") or []):
        if isinstance(candidate, dict) and candidate.get("candidate_id") == candidate_id:
            return dict(candidate)
    return {}


def _focused_stageback_layers_for_candidate(
    candidate: dict[str, Any],
    *,
    focused_layers_before: int,
) -> int | None:
    proposed_layer_count = candidate.get("proposed_layer_count")
    original_layer_count = candidate.get("original_layer_count")
    if proposed_layer_count is None:
        return None
    proposed = int(proposed_layer_count)
    original = int(original_layer_count or focused_layers_before)
    if proposed <= 0 or original <= 0 or focused_layers_before <= 1:
        return None
    ratio = min(0.99, max(0.05, float(proposed) / float(original)))
    return max(1, min(focused_layers_before - 1, int(math.ceil(focused_layers_before * ratio))))


def _validate_stageback_plus_truncation_candidate(
    *,
    apply_gate: str,
    bl_candidate_comparison: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    if apply_gate == BL_CANDIDATE_APPLY_GATE_OFF:
        return {}, "apply_gate_disabled"
    if apply_gate != BL_CANDIDATE_APPLY_GATE_STAGEBACK_PLUS_TRUNCATION_FOCUSED:
        return {}, "unsupported_apply_gate"
    if bl_candidate_comparison.get("recommended_candidate_id") != BL_STAGEBACK_PLUS_TRUNCATION_CANDIDATE_ID:
        return {}, "recommended_candidate_not_stageback_plus_truncation"
    candidate = _find_bl_candidate(
        bl_candidate_comparison,
        BL_STAGEBACK_PLUS_TRUNCATION_CANDIDATE_ID,
    )
    if not candidate:
        return {}, "stageback_plus_truncation_candidate_missing"
    if candidate.get("candidate_kind") != "stageback_plus_truncation":
        return candidate, "candidate_kind_not_stageback_plus_truncation"
    if candidate.get("planning_only") is not True:
        return candidate, "candidate_is_not_from_planning_surface"
    if candidate.get("suggested_truncation_start_y") is None:
        return candidate, "candidate_missing_suggested_truncation_start_y"
    if _focused_stageback_layers_for_candidate(candidate, focused_layers_before=8) is None:
        return candidate, "candidate_missing_valid_stageback_layer_count"
    return candidate, None


def _bl_blocking_kinds_from_observed(observed: dict[str, Any]) -> list[str]:
    route_result = observed.get("route_result")
    if not isinstance(route_result, dict):
        return []
    boundary_layer = route_result.get("boundary_layer")
    if not isinstance(boundary_layer, dict):
        return []
    blocking: list[str] = []
    pre_3d = boundary_layer.get("pre_3d_clearance")
    if isinstance(pre_3d, dict) and int(pre_3d.get("risk_sample_count", 0) or 0) > 0:
        blocking.append("extrusion_self_contact_risk")
    if float(boundary_layer.get("collapse_rate", 0.0) or 0.0) > 0.0:
        blocking.append("degenerated_prism_risk")
    return list(dict.fromkeys(blocking))


def _diagnostic_text_from_observed(observed: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "observed_failure_kind",
        "failure_code",
        "error",
        "stderr",
        "stdout",
    ):
        value = observed.get(key)
        if value is not None:
            parts.append(str(value))
    route_result = observed.get("route_result")
    if isinstance(route_result, dict):
        for key in (
            "observed_failure_kind",
            "failure_code",
            "error",
            "stderr",
            "stdout",
        ):
            value = route_result.get(key)
            if value is not None:
                parts.append(str(value))
        for key in ("failure_reasons", "validation_failures"):
            value = route_result.get(key)
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
    return " ; ".join(parts)


def _focused_route_failure_diagnostic(observed: dict[str, Any]) -> dict[str, Any]:
    route_result = observed.get("route_result")
    route_result = route_result if isinstance(route_result, dict) else {}
    mesh = route_result.get("mesh")
    mesh = mesh if isinstance(mesh, dict) else {}
    boundary_layer = route_result.get("boundary_layer")
    boundary_layer = boundary_layer if isinstance(boundary_layer, dict) else {}
    text = _diagnostic_text_from_observed(observed)
    text_lower = text.lower()
    observed_failure_kind = str(observed.get("observed_failure_kind") or "")

    symptoms: list[str] = []
    loop_not_closed = "forming a closed loop" in text_lower
    if loop_not_closed:
        symptoms.append("gmsh_1d_loop_not_closed")
    if "boundary_layer_collapse_rate_exceeded" in text_lower:
        symptoms.append("boundary_layer_collapse_rate_exceeded")
    if "volume_to_wall_ratio_below_limit" in text_lower:
        symptoms.append("volume_to_wall_ratio_below_limit")
    if "boundary_layer_total_thickness_outside_target_band" in text_lower:
        symptoms.append("boundary_layer_total_thickness_outside_target_band")

    achieved_layers = _parse_int(boundary_layer.get("achieved_layers"))
    requested_layers = _parse_int(boundary_layer.get("requested_layers"))
    collapse_rate = _parse_float(boundary_layer.get("collapse_rate"))
    total_cells = _parse_int(mesh.get("total_cells"))
    total_nodes = _parse_int(mesh.get("total_nodes"))
    volume_to_wall_ratio = _parse_float(mesh.get("volume_to_wall_ratio"))
    if requested_layers is not None and achieved_layers == 0:
        symptoms.append("bl_collapse_zero_achieved_layers")
    if collapse_rate is not None and collapse_rate >= 1.0:
        symptoms.append("bl_collapse_rate_1p0")
    if total_cells == 0:
        symptoms.append("no_volume_cells")
    if total_nodes == 0:
        symptoms.append("no_mesh_nodes")
    if volume_to_wall_ratio == 0.0:
        symptoms.append("zero_volume_to_wall_ratio")

    reached_gmsh_3d_boundary_recovery = (
        observed_failure_kind == "boundary_recovery_error_2"
        or "could not recover boundary mesh" in text_lower
        or "recoversegment" in text_lower
    )
    diagnostic_family: str | None = None
    failure_phase = "unknown"
    if loop_not_closed:
        diagnostic_family = "gmsh_1d_loop_closure_failure"
        failure_phase = "gmsh_2d"
    elif reached_gmsh_3d_boundary_recovery:
        failure_phase = "gmsh_3d_boundary_recovery"
    elif observed_failure_kind == "segment_facet_intersection":
        failure_phase = "gmsh_3d_boundary_recovery"

    return {
        "diagnostic_family": diagnostic_family,
        "failure_phase": failure_phase,
        "observed_symptoms": list(dict.fromkeys(symptoms)),
        "reached_gmsh_3d_boundary_recovery": bool(reached_gmsh_3d_boundary_recovery),
        "requested_layers": requested_layers,
        "achieved_layers": achieved_layers,
        "collapse_rate": collapse_rate,
        "total_cells": total_cells,
        "total_nodes": total_nodes,
        "volume_to_wall_ratio": volume_to_wall_ratio,
    }


def _focused_residual_summary(
    *,
    observed: dict[str, Any],
    fallback_forensic_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed_failure_kind = str(observed.get("observed_failure_kind") or "")
    blocking_bl = _bl_blocking_kinds_from_observed(observed)
    residual_classifier = dict(observed.get("downstream_residual_classifier") or {})
    residual_evidence = dict(residual_classifier.get("evidence") or {})
    forensic_evidence = _recoversegment_failed_steiner_evidence_from_observed(observed)
    if not forensic_evidence and isinstance(fallback_forensic_evidence, dict):
        forensic_evidence = _normalize_recoversegment_failed_steiner_evidence(
            fallback_forensic_evidence
        )
    if observed_failure_kind == "boundary_recovery_error_2":
        residual_family = (
            residual_classifier.get("primary_residual_family")
            or residual_evidence.get("residual_family")
            or forensic_evidence.get("residual_family")
        )
        local_y_band = (
            residual_evidence.get("local_y_band")
            or forensic_evidence.get("local_y_band")
            or []
        )
        suspicious_window = (
            residual_evidence.get("suspicious_window")
            or forensic_evidence.get("suspicious_window")
            or []
        )
        residual_status = residual_classifier.get("classification_status")
    else:
        residual_family = None
        local_y_band = []
        suspicious_window = []
        residual_status = "not_applicable"
    degenerated_prism_seen = (
        residual_evidence.get("degenerated_prism_seen")
        if residual_evidence.get("degenerated_prism_seen") is not None
        else forensic_evidence.get("degenerated_prism_seen")
        if observed_failure_kind == "boundary_recovery_error_2"
        else None
    )
    if degenerated_prism_seen is None and "degenerated_prism_risk" in blocking_bl:
        degenerated_prism_seen = True
    route_diagnostic = _focused_route_failure_diagnostic(observed)
    return {
        "observed_failure_kind": observed.get("observed_failure_kind"),
        "residual_family": residual_family,
        "residual_status": residual_status,
        "local_y_band": [float(value) for value in list(local_y_band or [])],
        "suspicious_window": [float(value) for value in list(suspicious_window or [])],
        "degenerated_prism_seen": degenerated_prism_seen,
        "blocking_bl_compatibility_check_kinds": blocking_bl,
        "bl_policy_fail_kinds": (
            ["bl_clearance_incompatibility"] if blocking_bl else []
        ),
        "diagnostic_family": route_diagnostic.get("diagnostic_family"),
        "failure_phase": route_diagnostic.get("failure_phase"),
        "observed_symptoms": list(route_diagnostic.get("observed_symptoms") or []),
        "reached_gmsh_3d_boundary_recovery": route_diagnostic.get(
            "reached_gmsh_3d_boundary_recovery"
        ),
        "route_failure_diagnostic": route_diagnostic,
        "report_path": observed.get("report_path"),
    }


def _focused_apply_verdict(
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    applied: bool,
    reject_reason: str | None,
) -> str:
    if not applied or reject_reason:
        return "rejected"
    before_failure = str(before.get("observed_failure_kind") or "")
    after_failure = str(after.get("observed_failure_kind") or "")
    before_family = str(before.get("residual_family") or "")
    after_family = str(after.get("residual_family") or "")
    if after_failure in {"facet_facet_overlap", "segment_facet_intersection"} and after_failure != before_failure:
        return "worsened"
    if before_family == FAILED_STEINER_RESIDUAL_FAMILY and after_family != before_family:
        if after_family or after_failure != before_failure:
            return "shifted_to_cleaner_family"
    local_change = _window_change_label(before.get("local_y_band"), after.get("local_y_band"))
    suspicious_change = _window_change_label(before.get("suspicious_window"), after.get("suspicious_window"))
    prism_improved = before.get("degenerated_prism_seen") is True and after.get("degenerated_prism_seen") is False
    if local_change == "reduced" or suspicious_change == "reduced" or prism_improved:
        return "improved"
    if before_family == FAILED_STEINER_RESIDUAL_FAMILY and after_family == before_family:
        return "unchanged_same_failed_steiner"
    return "unknown"


def _sweep_float_slug(value: float) -> str:
    return f"{float(value):.3f}".replace(".", "p")


def _derive_focused_sweep_target_and_truncation_grid(
    planning_budgeting: dict[str, Any],
) -> tuple[dict[str, float], list[float], list[str]]:
    notes: list[str] = []
    target_span = {"min": 15.875, "max": DEFAULT_HALF_SPAN_M}
    values: list[float] = []
    tip_region = None
    for region in list(planning_budgeting.get("tightest_regions") or []):
        if not isinstance(region, dict):
            continue
        if region.get("region_kind") == "tip_truncation_candidate_zone":
            tip_region = region
            break
    if isinstance(tip_region, dict):
        target_span = _normalized_y_span(tip_region)
        values.append(float(target_span["min"]))
        notes.append(
            "Truncation grid starts from the planning-budgeting tip_truncation_candidate_zone span."
        )
        for section_id in list(tip_region.get("section_ids") or []):
            text = str(section_id)
            if text.startswith("section_y:"):
                try:
                    values.append(float(text.split(":", 1)[1]))
                except ValueError:
                    continue
    for candidate in list(planning_budgeting.get("manual_edit_candidates") or []):
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("suggested_truncation_start_y_m")
        if value is not None:
            values.append(float(value))
    if not values:
        values.extend([15.95, 16.0, 16.10, 16.25])
        notes.append(
            "Fell back to a bounded engineering grid because no planning-budgeting truncation candidates were available."
        )
    unique_values = sorted({round(float(value), 6) for value in values})
    bounded = [
        value
        for value in unique_values
        if float(target_span["min"]) - 1.0e-6 <= value <= float(target_span["max"]) + 1.0e-6
    ]
    if not bounded:
        bounded = [float(target_span["min"])]
    notes.append(
        "Using existing planning-budgeting section/manual candidate y stations instead of the example sweep values."
    )
    return target_span, [float(value) for value in bounded[:4]], notes


def _build_focused_bl_candidate_sweep_cases(
    *,
    target_y_span: dict[str, float],
    truncation_start_y_values: list[float],
    original_layer_count: int = 8,
) -> list[dict[str, Any]]:
    if not truncation_start_y_values:
        truncation_start_y_values = [float(target_y_span["min"])]
    primary = float(truncation_start_y_values[0])
    mild_values = [
        float(value)
        for value in truncation_start_y_values
        if float(value) > primary + 1.0e-9
    ][:2]
    if len(mild_values) < 2:
        mild_values = [float(value) for value in truncation_start_y_values[:2]]
    strong_values = [primary, *mild_values]
    cases: list[dict[str, Any]] = [
        {
            "sweep_case_id": "baseline_no_apply",
            "candidate_kind": "baseline_no_apply",
            "stageback_layer_count": None,
            "original_layer_count": int(original_layer_count),
            "truncation_start_y": None,
            "target_y_span": copy.deepcopy(target_y_span),
            "applied": False,
            "reject_reason": None,
        }
    ]
    for layers_after in (7, 6, 5):
        cases.append(
            {
                "sweep_case_id": f"stageback_only_layers{layers_after}",
                "candidate_kind": "stageback_only",
                "stageback_layer_count": int(layers_after),
                "original_layer_count": int(original_layer_count),
                "truncation_start_y": None,
                "target_y_span": copy.deepcopy(target_y_span),
                "applied": True,
                "reject_reason": None,
            }
        )
    for value in truncation_start_y_values:
        slug = _sweep_float_slug(float(value))
        cases.append(
            {
                "sweep_case_id": f"truncation_only_y{slug}",
                "candidate_kind": "truncation_only",
                "stageback_layer_count": None,
                "original_layer_count": int(original_layer_count),
                "truncation_start_y": float(value),
                "target_y_span": copy.deepcopy(target_y_span),
                "applied": True,
                "reject_reason": None,
            }
        )
    for value in mild_values[:2]:
        slug = _sweep_float_slug(float(value))
        cases.append(
            {
                "sweep_case_id": f"combined_mild_layers7_truncation_y{slug}",
                "candidate_kind": "combined_mild_stageback_truncation",
                "stageback_layer_count": 7,
                "original_layer_count": int(original_layer_count),
                "truncation_start_y": float(value),
                "target_y_span": copy.deepcopy(target_y_span),
                "applied": True,
                "reject_reason": None,
            }
        )
    for value in strong_values[:3]:
        slug = _sweep_float_slug(float(value))
        case_id = f"combined_stronger_layers6_truncation_y{slug}"
        if abs(float(value) - primary) <= 1.0e-9:
            case_id = f"{case_id}_current"
        cases.append(
            {
                "sweep_case_id": case_id,
                "candidate_kind": "combined_stronger_stageback_truncation",
                "stageback_layer_count": 6,
                "original_layer_count": int(original_layer_count),
                "truncation_start_y": float(value),
                "target_y_span": copy.deepcopy(target_y_span),
                "applied": True,
                "reject_reason": None,
            }
        )
    return cases


def _apply_bl_candidate_sweep_case_to_fixture(
    fixture: dict[str, Any],
    *,
    sweep_case: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    if not sweep_case.get("applied"):
        return copy.deepcopy(fixture), None
    layers_after = sweep_case.get("stageback_layer_count")
    truncation_start_y = sweep_case.get("truncation_start_y")
    if layers_after is None and truncation_start_y is None:
        return copy.deepcopy(fixture), "sweep_case_has_no_mutation"
    transformed_fixture = copy.deepcopy(fixture)
    focused_mutations: dict[str, Any] = {
        "layers_before": int(sweep_case.get("original_layer_count") or 8),
        "focused_fixture_only": True,
        "applies_to_family": "root_last3_segment_facet",
        "applies_to_region": "root_last3_tip_terminal_tight_region",
        "sweep_case_id": str(sweep_case["sweep_case_id"]),
    }
    if layers_after is not None:
        focused_mutations["layers_after"] = int(layers_after)
    if truncation_start_y is not None:
        focused_mutations["forced_tip_truncation_start_y_m"] = float(truncation_start_y)
    transformed_fixture["focused_bl_candidate_apply"] = {
        "enabled": True,
        "apply_gate": "bl_candidate_parameter_sweep_focused",
        "candidate_id": str(sweep_case["sweep_case_id"]),
        "candidate_kind": str(sweep_case["candidate_kind"]),
        "candidate": copy.deepcopy(sweep_case),
        "focused_mutations": focused_mutations,
        "sweep_report_only": True,
    }
    return transformed_fixture, None


def _focused_sweep_case_after_diagnostic_family(
    *,
    sweep_case: dict[str, Any],
    after_summary: dict[str, Any],
) -> str | None:
    diagnostic_family = after_summary.get("diagnostic_family")
    if (
        sweep_case.get("sweep_case_id") == "stageback_only_layers5"
        and sweep_case.get("candidate_kind") == "stageback_only"
        and int(sweep_case.get("stageback_layer_count") or 0) == 5
        and diagnostic_family == "gmsh_1d_loop_closure_failure"
    ):
        return "stageback_induced_1d_loop_closure_failure"
    return str(diagnostic_family) if diagnostic_family else None


def _focused_failure_relation_to_failed_steiner(
    *,
    after_diagnostic_family: str | None,
    after_summary: dict[str, Any],
) -> str:
    if after_summary.get("residual_family") == FAILED_STEINER_RESIDUAL_FAMILY:
        return "possible_upstream_cause"
    if after_diagnostic_family == "stageback_induced_1d_loop_closure_failure":
        return "different_family"
    if after_summary.get("observed_failure_kind") == "boundary_recovery_error_2":
        return "possible_upstream_cause"
    return "unclear"


def _focused_failure_relation_to_segment_facet(
    *,
    after_diagnostic_family: str | None,
    after_summary: dict[str, Any],
) -> str:
    if after_summary.get("observed_failure_kind") == "segment_facet_intersection":
        return "regression_risk"
    if after_diagnostic_family == "stageback_induced_1d_loop_closure_failure":
        return "different_family"
    return "unclear"


def _focused_sweep_case_diagnostic_family_report(
    *,
    sweep_case: dict[str, Any],
    before_summary: dict[str, Any],
    after_summary: dict[str, Any],
    after_diagnostic_family: str | None,
    relation_to_failed_steiner: str,
    relation_to_segment_facet: str,
) -> dict[str, Any]:
    if not after_diagnostic_family:
        return {}
    route_diagnostic = dict(after_summary.get("route_failure_diagnostic") or {})
    return {
        "diagnostic_family": after_diagnostic_family,
        "source_candidate_id": str(sweep_case["sweep_case_id"]),
        "stageback_layer_count": sweep_case.get("stageback_layer_count"),
        "original_layer_count": sweep_case.get("original_layer_count"),
        "truncation_start_y": sweep_case.get("truncation_start_y"),
        "whether_reached_gmsh_3d_recovery": bool(
            after_summary.get("reached_gmsh_3d_boundary_recovery")
        ),
        "failure_phase": after_summary.get("failure_phase") or "unknown",
        "observed_symptoms": list(after_summary.get("observed_symptoms") or []),
        "local_y_band_before": list(before_summary.get("local_y_band") or []),
        "local_y_band_after": list(after_summary.get("local_y_band") or []),
        "target_y_span": copy.deepcopy(sweep_case.get("target_y_span") or {}),
        "relation_to_failed_steiner": relation_to_failed_steiner,
        "relation_to_segment_facet": relation_to_segment_facet,
        "requested_layers": route_diagnostic.get("requested_layers"),
        "achieved_layers": route_diagnostic.get("achieved_layers"),
        "collapse_rate": route_diagnostic.get("collapse_rate"),
        "total_cells": route_diagnostic.get("total_cells"),
        "total_nodes": route_diagnostic.get("total_nodes"),
        "volume_to_wall_ratio": route_diagnostic.get("volume_to_wall_ratio"),
    }


def _focused_sweep_case_verdict(
    *,
    sweep_case: dict[str, Any],
    before_summary: dict[str, Any],
    after_summary: dict[str, Any],
    applied: bool,
    reject_reason: str | None,
) -> tuple[str, list[str]]:
    if reject_reason:
        return "rejected", [str(reject_reason)]
    if not applied:
        return "unchanged", ["baseline_no_apply"]
    after_diagnostic_family = _focused_sweep_case_after_diagnostic_family(
        sweep_case=sweep_case,
        after_summary=after_summary,
    )
    before_family = str(before_summary.get("residual_family") or "")
    after_family = str(after_summary.get("residual_family") or "")
    after_failure = str(after_summary.get("observed_failure_kind") or "")
    failed_steiner_before = before_family == FAILED_STEINER_RESIDUAL_FAMILY
    failed_steiner_resolved = failed_steiner_before and after_family != FAILED_STEINER_RESIDUAL_FAMILY
    prism_improved = (
        before_summary.get("degenerated_prism_seen") is True
        and after_summary.get("degenerated_prism_seen") is False
    )
    supporting: list[str] = []
    if prism_improved:
        supporting.append("partial_degenerated_prism_improved_needs_follow_up")
    if after_failure == "segment_facet_intersection":
        return "too_aggressive_reintroduces_segment_facet", supporting
    if after_diagnostic_family == "stageback_induced_1d_loop_closure_failure":
        supporting.append("pre_recovery_topology_failure")
        supporting.append("stageback_induced_bl_collapse")
        return after_diagnostic_family, supporting
    if failed_steiner_resolved and after_failure and after_failure != "unknown":
        return "promising", supporting
    if after_family == FAILED_STEINER_RESIDUAL_FAMILY or after_failure == "boundary_recovery_error_2":
        return "insufficient_still_failed_steiner", supporting
    if (
        after_failure == before_summary.get("observed_failure_kind")
        and after_family == before_family
    ):
        return "unchanged", supporting
    return "unknown", supporting


def _build_focused_sweep_case_payload(
    *,
    sweep_case: dict[str, Any],
    before_summary: dict[str, Any],
    after_summary: dict[str, Any],
    reject_reason: str | None,
) -> dict[str, Any]:
    verdict, supporting_verdicts = _focused_sweep_case_verdict(
        sweep_case=sweep_case,
        before_summary=before_summary,
        after_summary=after_summary,
        applied=bool(sweep_case.get("applied")),
        reject_reason=reject_reason,
    )
    before_failure = before_summary.get("observed_failure_kind")
    after_failure = after_summary.get("observed_failure_kind")
    before_family = before_summary.get("residual_family")
    after_family = after_summary.get("residual_family")
    segment_facet_regressed = (
        after_failure == "segment_facet_intersection"
        and before_failure != "segment_facet_intersection"
    )
    failed_steiner_resolved = (
        before_family == FAILED_STEINER_RESIDUAL_FAMILY
        and after_family != FAILED_STEINER_RESIDUAL_FAMILY
    )
    after_diagnostic_family = _focused_sweep_case_after_diagnostic_family(
        sweep_case=sweep_case,
        after_summary=after_summary,
    )
    relation_to_failed_steiner = _focused_failure_relation_to_failed_steiner(
        after_diagnostic_family=after_diagnostic_family,
        after_summary=after_summary,
    )
    relation_to_segment_facet = _focused_failure_relation_to_segment_facet(
        after_diagnostic_family=after_diagnostic_family,
        after_summary=after_summary,
    )
    diagnostic_family_report = _focused_sweep_case_diagnostic_family_report(
        sweep_case=sweep_case,
        before_summary=before_summary,
        after_summary=after_summary,
        after_diagnostic_family=after_diagnostic_family,
        relation_to_failed_steiner=relation_to_failed_steiner,
        relation_to_segment_facet=relation_to_segment_facet,
    )
    return {
        "sweep_case_id": str(sweep_case["sweep_case_id"]),
        "candidate_kind": str(sweep_case["candidate_kind"]),
        "stageback_layer_count": sweep_case.get("stageback_layer_count"),
        "original_layer_count": sweep_case.get("original_layer_count"),
        "truncation_start_y": sweep_case.get("truncation_start_y"),
        "target_y_span": copy.deepcopy(sweep_case.get("target_y_span") or {}),
        "applied": bool(sweep_case.get("applied")),
        "reject_reason": reject_reason,
        "before_residual_family": before_family,
        "after_residual_family": after_family,
        "before_failure_kind": before_failure,
        "after_failure_kind": after_failure,
        "after_diagnostic_family": after_diagnostic_family,
        "failure_phase": after_summary.get("failure_phase") or "unknown",
        "reached_gmsh_3d_boundary_recovery": bool(
            after_summary.get("reached_gmsh_3d_boundary_recovery")
        ),
        "observed_symptoms": list(after_summary.get("observed_symptoms") or []),
        "relation_to_failed_steiner": relation_to_failed_steiner,
        "relation_to_segment_facet": relation_to_segment_facet,
        "diagnostic_family_report": diagnostic_family_report,
        "segment_facet_regressed": bool(segment_facet_regressed),
        "failed_steiner_resolved": bool(failed_steiner_resolved),
        "degenerated_prism_seen_before": before_summary.get("degenerated_prism_seen"),
        "degenerated_prism_seen_after": after_summary.get("degenerated_prism_seen"),
        "local_y_band_before": list(before_summary.get("local_y_band") or []),
        "local_y_band_after": list(after_summary.get("local_y_band") or []),
        "suspicious_window_before": list(before_summary.get("suspicious_window") or []),
        "suspicious_window_after": list(after_summary.get("suspicious_window") or []),
        "partial_needs_follow_up": "partial_degenerated_prism_improved_needs_follow_up"
        in supporting_verdicts,
        "supporting_verdicts": supporting_verdicts,
        "verdict": verdict,
    }


def _select_focused_sweep_recommendation(sweep_cases: list[dict[str, Any]]) -> dict[str, Any]:
    promising = [case for case in sweep_cases if case.get("verdict") == "promising"]
    if promising:
        selected = promising[0]
        return {
            "recommended_sweep_case_id": selected["sweep_case_id"],
            "promising_candidate_found": True,
            "closest_promising_sweep_case_id": selected["sweep_case_id"],
            "recommendation_reason": (
                "Selected the first bounded case that resolved the failed-Steiner residual without "
                "reintroducing segment-facet intersection."
            ),
            "whether_next_runtime_apply_is_recommended": True,
            "whether_more_gmsh_debug_needed": False,
            "whether_topology_operator_should_remain_paused": True,
        }

    def _score(case: dict[str, Any]) -> tuple[int, int, int, int]:
        if case.get("verdict") == "too_aggressive_reintroduces_segment_facet":
            return (-100, 0, 0, 0)
        failed_resolved = 1 if case.get("failed_steiner_resolved") else 0
        prism_improved = 1 if case.get("degenerated_prism_seen_after") is False else 0
        applied = 1 if case.get("applied") else 0
        layers = int(case.get("stageback_layer_count") or case.get("original_layer_count") or 0)
        return (failed_resolved * 20 + prism_improved * 5 + applied, layers, 0, 0)

    closest = max(sweep_cases, key=_score) if sweep_cases else {}
    closest_id = closest.get("sweep_case_id")
    return {
        "recommended_sweep_case_id": None,
        "promising_candidate_found": False,
        "closest_promising_sweep_case_id": None,
        "closest_diagnostic_boundary_sweep_case_id": closest_id,
        "recommendation_reason": (
            "No promising case was found; keep runtime apply disabled. The diagnostic boundary case "
            "is for failure-family analysis only, not for runtime application."
        ),
        "whether_next_runtime_apply_is_recommended": False,
        "whether_more_gmsh_debug_needed": True,
        "whether_topology_operator_should_remain_paused": True,
    }


def _stageback_layer_schedule(case: dict[str, Any]) -> list[int]:
    original = int(case.get("original_layer_count") or 0)
    stageback = case.get("stageback_layer_count")
    schedule: list[int] = []
    if original > 0:
        schedule.append(original)
    if stageback is not None:
        stageback_int = int(stageback)
        if not schedule or stageback_int != schedule[-1]:
            schedule.append(stageback_int)
    return schedule


def _infer_loop_continuity_case(case: dict[str, Any]) -> dict[str, Any]:
    symptoms = set(str(item) for item in case.get("observed_symptoms") or [])
    diagnostic_report = dict(case.get("diagnostic_family_report") or {})
    target_y_span = copy.deepcopy(case.get("target_y_span") or {})
    loop_not_closed = (
        case.get("after_diagnostic_family") == "stageback_induced_1d_loop_closure_failure"
        or "gmsh_1d_loop_not_closed" in symptoms
    )
    reached_3d = bool(case.get("reached_gmsh_3d_boundary_recovery"))
    if loop_not_closed:
        loop_closed: bool | str = False
        inferred_loop_count: int | None = 0
        observed_loop_count: int | None = None
        open_loop_gap_count: int | None = 1
        open_loop_y_ranges = [copy.deepcopy(target_y_span)] if target_y_span else []
        termination_ring_valid: bool | str = False
        connector_band_continuity = "fail"
        diagnostic_verdict = "loop_not_closed"
        evidence_quality = "inferred_from_gmsh_1d_failure"
    elif reached_3d:
        loop_closed = True
        inferred_loop_count = 1
        observed_loop_count = None
        open_loop_gap_count = 0
        open_loop_y_ranges: list[dict[str, Any]] = []
        termination_ring_valid = "unknown"
        connector_band_continuity = "pass"
        diagnostic_verdict = "loop_continuity_pass"
        evidence_quality = "inferred_from_reaching_gmsh_3d_boundary_recovery"
    else:
        loop_closed = "unknown"
        inferred_loop_count = None
        observed_loop_count = None
        open_loop_gap_count = None
        open_loop_y_ranges = []
        termination_ring_valid = "unknown"
        connector_band_continuity = "unknown"
        diagnostic_verdict = "insufficient_evidence"
        evidence_quality = "insufficient_route_phase_evidence"

    return {
        "diagnostic_case_id": f"loop_continuity::{case.get('sweep_case_id')}",
        "source_candidate_id": str(case.get("sweep_case_id") or "unknown"),
        "stageback_layer_schedule": _stageback_layer_schedule(case),
        "target_y_span": target_y_span,
        "expected_loop_count": 1,
        "observed_loop_count": observed_loop_count,
        "inferred_loop_count": inferred_loop_count,
        "loop_closed": loop_closed,
        "open_loop_gap_count": open_loop_gap_count,
        "open_loop_gap_locations": [],
        "open_loop_gap_y_ranges": open_loop_y_ranges,
        "termination_ring_valid": termination_ring_valid,
        "connector_band_continuity": connector_band_continuity,
        "collapse_rate": diagnostic_report.get("collapse_rate"),
        "achieved_bl_layers": diagnostic_report.get("achieved_layers"),
        "volume_to_wall_ratio": diagnostic_report.get("volume_to_wall_ratio"),
        "failure_phase": case.get("failure_phase") or "unknown",
        "diagnostic_verdict": diagnostic_verdict,
        "evidence_quality": evidence_quality,
        "evidence_notes": [
            "No BREP-edge loop graph is available in this report-only layer; loop status is inferred from focused route failure phase and Gmsh messages.",
        ],
    }


def _build_bl_stageback_loop_continuity_diagnostic(
    *,
    sweep_cases: list[dict[str, Any]],
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    diagnostic_cases = [_infer_loop_continuity_case(case) for case in sweep_cases]
    verdict_summary = {
        verdict: sum(
            1
            for case in diagnostic_cases
            if case.get("diagnostic_verdict") == verdict
        )
        for verdict in sorted({str(case.get("diagnostic_verdict")) for case in diagnostic_cases})
    }
    stageback_layers5 = next(
        (
            case
            for case in diagnostic_cases
            if case.get("source_candidate_id") == "stageback_only_layers5"
        ),
        None,
    )
    payload = {
        "contract": BL_STAGEBACK_LOOP_CONTINUITY_DIAGNOSTIC_CONTRACT,
        "status": "written",
        "report_only": True,
        "planning_only": True,
        "diagnostic_scope": "focused_root_last3_stageback_sweep_cases",
        "expected_loop_count_basis": "one closed connector-band termination loop per focused case",
        "diagnostic_cases": diagnostic_cases,
        "verdict_summary": verdict_summary,
        "stageback_only_layers5_verdict": (
            None if stageback_layers5 is None else stageback_layers5.get("diagnostic_verdict")
        ),
        "stageback_only_layers5_runtime_recommendation": False,
        "runtime_geometry_mutation": False,
        "runtime_bl_spec_mutation": False,
        "topology_operator_added": False,
        "notes": [
            "Loop gaps are not directly measured from a BREP edge graph yet; unknown values are intentionally left unknown.",
            "A stageback case that fails before Gmsh 3D boundary recovery is diagnostic evidence, not a runtime recommendation.",
        ],
        "artifact_path": str(artifact_path) if artifact_path is not None else None,
    }
    if artifact_path is not None:
        write_json_report(Path(artifact_path), payload)
    return payload


def _minimum_breakpoint_interval(y_breakpoints: list[float]) -> float | None:
    if len(y_breakpoints) < 2:
        return None
    ordered = sorted(float(value) for value in y_breakpoints)
    return min(
        float(right) - float(left)
        for left, right in zip(ordered[:-1], ordered[1:])
    )


def _build_topology_preserving_staged_transition_prototypes(
    *,
    target_y_span: dict[str, Any],
    original_layer_count: int,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    y_min = float(target_y_span.get("min", 15.875))
    y_max = float(target_y_span.get("max", DEFAULT_HALF_SPAN_M))
    span = max(y_max - y_min, 1.0e-6)
    mid_y = y_min + 0.50 * span
    hold_y = y_min + 0.35 * span
    guard_y = max(y_min, y_max - max(0.05, 0.18 * span))
    layer_count = int(original_layer_count or 8)

    def _prototype(
        *,
        prototype_id: str,
        layer_schedule: list[int],
        y_breakpoints: list[float],
        expected_loop_continuity: str,
        expected_termination_ring_validity: str,
        expected_effect_on_failed_steiner: str,
        expected_effect_on_segment_facet_regression: str,
        expected_effect_on_loop_closure: str,
        risk_notes: list[str],
    ) -> dict[str, Any]:
        normalized_breakpoints = [round(float(value), 6) for value in y_breakpoints]
        return {
            "prototype_id": prototype_id,
            "layer_schedule": [int(value) for value in layer_schedule],
            "y_breakpoints": normalized_breakpoints,
            "min_interval_between_breakpoints": _minimum_breakpoint_interval(
                normalized_breakpoints
            ),
            "expected_loop_continuity": expected_loop_continuity,
            "expected_termination_ring_validity": expected_termination_ring_validity,
            "expected_effect_on_failed_steiner": expected_effect_on_failed_steiner,
            "expected_effect_on_segment_facet_regression": expected_effect_on_segment_facet_regression,
            "expected_effect_on_loop_closure": expected_effect_on_loop_closure,
            "risk_notes": list(risk_notes),
            "planning_only": True,
        }

    prototypes = [
        _prototype(
            prototype_id="direct_baseline_layers8",
            layer_schedule=[layer_count],
            y_breakpoints=[],
            expected_loop_continuity="preserved_by_no_stageback",
            expected_termination_ring_validity="unchanged",
            expected_effect_on_failed_steiner="insufficient_known_failed_steiner_remains",
            expected_effect_on_segment_facet_regression="low_regression_risk",
            expected_effect_on_loop_closure="low_new_loop_closure_risk",
            risk_notes=[
                "Keeps the known failed-Steiner blocker and therefore is a reference, not a repair.",
            ],
        ),
        _prototype(
            prototype_id="mild_staged_8_to_7",
            layer_schedule=[layer_count, max(layer_count - 1, 1)],
            y_breakpoints=[y_min],
            expected_loop_continuity="likely_preserved_but_unproven",
            expected_termination_ring_validity="unknown_until_loop_instrumented",
            expected_effect_on_failed_steiner="possibly_insufficient",
            expected_effect_on_segment_facet_regression="low_to_medium_regression_risk",
            expected_effect_on_loop_closure="lower_risk_than_direct_deeper_stageback",
            risk_notes=[
                "A one-layer step is intentionally mild, but prior 8->7 sweep evidence was insufficient.",
            ],
        ),
        _prototype(
            prototype_id="smoother_staged_8_to_7_to_6",
            layer_schedule=[layer_count, max(layer_count - 1, 1), max(layer_count - 2, 1)],
            y_breakpoints=[y_min, mid_y],
            expected_loop_continuity="plausible_if_breakpoint_spacing_is_preserved",
            expected_termination_ring_validity="unknown_until_loop_instrumented",
            expected_effect_on_failed_steiner="more_relief_than_8_to_7",
            expected_effect_on_segment_facet_regression="medium_regression_risk",
            expected_effect_on_loop_closure="medium_risk_due_second_drop",
            risk_notes=[
                "This is smoother than a direct 8->6 jump, but the final 6-layer region still needs loop continuity evidence.",
            ],
        ),
        _prototype(
            prototype_id="hold_then_stage_8_hold_7_6_terminal",
            layer_schedule=[layer_count, layer_count, max(layer_count - 1, 1), max(layer_count - 2, 1)],
            y_breakpoints=[y_min, hold_y, guard_y],
            expected_loop_continuity="plausible_with_terminal_hold_guard",
            expected_termination_ring_validity="unknown_but_better_than_direct_terminal_drop",
            expected_effect_on_failed_steiner="targets_terminal_pressure_after_preserving_upstream_band",
            expected_effect_on_segment_facet_regression="medium_regression_risk",
            expected_effect_on_loop_closure="medium_low_if_guard_spacing_holds",
            risk_notes=[
                "Holding 8 layers before staging reduces abrupt upstream topology change but still reaches 6 layers near the terminal.",
            ],
        ),
        _prototype(
            prototype_id="stage_with_termination_guard_8_to_7",
            layer_schedule=[layer_count, max(layer_count - 1, 1)],
            y_breakpoints=[guard_y],
            expected_loop_continuity="best_expected_preservation_without_new_operator",
            expected_termination_ring_validity="guarded_but_unproven",
            expected_effect_on_failed_steiner="limited_relief_but_cleanest_next_experiment",
            expected_effect_on_segment_facet_regression="lowest_staged_regression_risk",
            expected_effect_on_loop_closure="lowest_stageback_loop_closure_risk",
            risk_notes=[
                "Keeps the layer transition away from the terminal ring until a guard check can prove continuity.",
                "Recommended only for a future experimental apply, not runtime default promotion.",
            ],
        ),
    ]
    payload = {
        "contract": BL_TOPOLOGY_PRESERVING_STAGED_TRANSITION_PROTOTYPES_CONTRACT,
        "status": "written",
        "report_only": True,
        "planning_only": True,
        "target_y_span": {"min": y_min, "max": y_max},
        "prototypes": prototypes,
        "excluded_schedule_ids": ["direct_drop_8_to_5"],
        "excluded_schedule_reasons": {
            "direct_drop_8_to_5": (
                "stageback_only_layers5 is classified as loop_not_closed / "
                "stageback_induced_1d_loop_closure_failure, not a promising candidate."
            ),
        },
        "recommended_next_experimental_apply_prototype_id": "stage_with_termination_guard_8_to_7",
        "recommendation_reason": (
            "It is the mildest topology-preserving staged transition with an explicit terminal guard; "
            "it tests whether one-layer relief helps without repeating the direct 8->5 loop failure."
        ),
        "runtime_geometry_mutation": False,
        "runtime_bl_spec_mutation": False,
        "runtime_apply_candidate_added": False,
        "topology_operator_added": False,
        "artifact_path": str(artifact_path) if artifact_path is not None else None,
    }
    if artifact_path is not None:
        write_json_report(Path(artifact_path), payload)
    return payload


def _run_shell_v4_bl_candidate_parameter_sweep_focused(
    *,
    out_dir: Path,
    source_path: Path,
    component: str,
    root_last3_failed_steiner_forensic_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_dir = Path(out_dir) / "artifacts" / "topology_compiler" / "bl_candidate_parameter_sweep"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    spec = build_shell_v4_half_wing_bl_macsafe_spec(
        overrides={
            "geometry": {
                "shape_mode": DEFAULT_REAL_MAIN_WING_SHAPE_MODE,
                "source_path": str(source_path),
                "component": component,
                "airfoil_loop_points": 48,
                "half_span_stations": 18,
            },
            "boundary_layer": {
                "first_layer_height_m": 1.0e-3,
                "layers": 8,
                "growth_ratio": 1.20,
            },
        }
    )
    real_wing_geometry = _resolve_real_main_wing_geometry(
        geometry=dict(spec["geometry"]),
        artifact_dir=artifact_dir / "geometry",
    )
    planning_budgeting = _build_real_wing_bl_budgeting_plan(
        sections=[dict(section) for section in real_wing_geometry.get("sections", [])],
        protection=dict(spec.get("real_wing_bl_protection") or {}),
        base_total_thickness_m=float(spec["boundary_layer"]["target_total_thickness_m"]),
        half_span_m=float(spec["geometry"].get("half_span_m") or DEFAULT_HALF_SPAN_M),
    ).model_dump(mode="json")
    target_y_span, truncation_grid, grid_notes = _derive_focused_sweep_target_and_truncation_grid(
        planning_budgeting
    )
    sweep_plan_cases = _build_focused_bl_candidate_sweep_cases(
        target_y_span=target_y_span,
        truncation_start_y_values=truncation_grid,
        original_layer_count=8,
    )
    root_last3_fixture = _build_shell_v4_pre_plc_repro_fixture(
        source_path=source_path,
        component=component,
        family="root_last3_segment_facet",
        artifact_dir=artifact_dir / "root_last3" / "fixture",
    )
    baseline = _run_shell_v4_pre_plc_repro_fixture(
        root_last3_fixture,
        out_dir=artifact_dir / "root_last3" / "baseline_probe",
    )
    transition = _apply_post_band_transition_split_operator_to_pre_plc_fixture(
        root_last3_fixture,
        baseline_observed=baseline,
        artifact_dir=artifact_dir / "root_last3" / "post_band_transition",
    )
    error2_observed = _run_shell_v4_pre_plc_repro_fixture(
        transition["fixture"],
        out_dir=artifact_dir / "root_last3" / "post_band_transition_probe",
    )
    if root_last3_failed_steiner_forensic_evidence:
        error2_observed["forensic_evidence"] = dict(root_last3_failed_steiner_forensic_evidence)
    localized = _apply_post_transition_boundary_recovery_operator_to_pre_plc_fixture(
        transition["fixture"],
        baseline_observed=error2_observed,
        artifact_dir=artifact_dir / "root_last3" / "boundary_recovery_regularization",
    )
    before_observed = _run_shell_v4_pre_plc_repro_fixture(
        localized["fixture"],
        out_dir=artifact_dir / "root_last3" / "before_sweep_probe",
    )
    before_summary = _focused_residual_summary(
        observed=before_observed,
        fallback_forensic_evidence=root_last3_failed_steiner_forensic_evidence,
    )

    sweep_cases: list[dict[str, Any]] = []
    for sweep_case in sweep_plan_cases:
        candidate_fixture, reject_reason = _apply_bl_candidate_sweep_case_to_fixture(
            localized["fixture"],
            sweep_case=sweep_case,
        )
        if reject_reason is None and sweep_case.get("applied"):
            after_observed = _run_shell_v4_pre_plc_repro_fixture(
                candidate_fixture,
                out_dir=artifact_dir / "root_last3" / "cases" / str(sweep_case["sweep_case_id"]),
            )
            after_summary = _focused_residual_summary(observed=after_observed)
        else:
            after_summary = copy.deepcopy(before_summary)
        sweep_cases.append(
            _build_focused_sweep_case_payload(
                sweep_case=sweep_case,
                before_summary=before_summary,
                after_summary=after_summary,
                reject_reason=reject_reason,
            )
        )

    recommendation = _select_focused_sweep_recommendation(sweep_cases)
    root_last4_non_regression = _run_root_last4_overlap_non_regression_check(
        source_path=source_path,
        component=component,
        artifact_dir=artifact_dir / "root_last4_overlap_non_regression",
    )
    artifact_path = artifact_dir / "bl_candidate_parameter_sweep.v1.json"
    loop_diagnostic_path = artifact_dir / "bl_stageback_loop_continuity_diagnostic.v1.json"
    loop_continuity_diagnostic = _build_bl_stageback_loop_continuity_diagnostic(
        sweep_cases=sweep_cases,
        artifact_path=loop_diagnostic_path,
    )
    staged_transition_prototypes_path = (
        artifact_dir / "bl_topology_preserving_staged_transition_prototypes.v1.json"
    )
    staged_transition_prototypes = _build_topology_preserving_staged_transition_prototypes(
        target_y_span=target_y_span,
        original_layer_count=8,
        artifact_path=staged_transition_prototypes_path,
    )
    verdict_summary = {
        verdict: sum(1 for case in sweep_cases if case.get("verdict") == verdict)
        for verdict in sorted({str(case.get("verdict")) for case in sweep_cases})
    }
    payload = {
        "contract": BL_CANDIDATE_PARAMETER_SWEEP_CONTRACT,
        "status": "written",
        "experimental": True,
        "focused": True,
        "report_only": True,
        "plan_report_only": True,
        "focused_path": "root_last3_segment_facet",
        "focused_scope": "isolated_pre_plc_fixture_rerun",
        "full_prelaunch_pass_attempted": False,
        "candidate_grid": {
            "original_layer_count": 8,
            "stageback_layer_counts": [7, 6, 5],
            "truncation_start_y_values": list(truncation_grid),
            "target_y_span": copy.deepcopy(target_y_span),
            "grid_source_notes": grid_notes,
        },
        "sweep_cases": sweep_cases,
        "verdict_summary": verdict_summary,
        "loop_continuity_diagnostic": loop_continuity_diagnostic,
        "staged_transition_prototypes": staged_transition_prototypes,
        **recommendation,
        "root_last4_non_regression": root_last4_non_regression,
        "production_default_changed": False,
        "topology_compiler_gate_off_changed": False,
        "plan_only_behavior_changed": False,
        "runtime_bl_spec_mutation": False,
        "runtime_geometry_mutation": False,
        "gmsh_settings_changed": False,
        "shell_v3_changed": False,
        "topology_operator_added": False,
        "root_last4_overlap_path_changed": False,
        "artifacts": {
            "bl_candidate_parameter_sweep": str(artifact_path),
            "loop_continuity_diagnostic": str(loop_diagnostic_path),
            "staged_transition_prototypes": str(staged_transition_prototypes_path),
            "before_root_last3_report": str(before_observed.get("report_path")),
        },
        "notes": [
            "Focused experimental sweep compares BL stageback/truncation parameters only.",
            "No sweep candidate is a production default or topology operator.",
            "The current stageback-plus-truncation candidate is represented by the strongest layers6 case at the first derived truncation station.",
            "Loop-continuity diagnostics and staged-transition prototypes are report-only evidence for selecting a future experimental apply.",
        ],
    }
    write_json_report(artifact_path, payload)
    return payload


def _apply_stageback_plus_truncation_candidate_to_fixture(
    fixture: dict[str, Any],
    *,
    candidate: dict[str, Any],
    apply_gate: str,
    artifact_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    focused_layers_before = 8
    layers_after = _focused_stageback_layers_for_candidate(
        candidate,
        focused_layers_before=focused_layers_before,
    )
    truncation_start_y = candidate.get("suggested_truncation_start_y")
    if layers_after is None:
        return copy.deepcopy(fixture), {}, "candidate_missing_valid_stageback_layer_count"
    if truncation_start_y is None:
        return copy.deepcopy(fixture), {}, "candidate_missing_suggested_truncation_start_y"

    transformed_fixture = copy.deepcopy(fixture)
    focused_mutations = {
        "layers_before": int(focused_layers_before),
        "layers_after": int(layers_after),
        "forced_tip_truncation_start_y_m": float(truncation_start_y),
        "focused_fixture_only": True,
        "applies_to_family": "root_last3_segment_facet",
        "applies_to_region": "root_last3_tip_terminal_tight_region",
    }
    transformed_fixture["focused_bl_candidate_apply"] = {
        "enabled": True,
        "apply_gate": apply_gate,
        "candidate_id": BL_STAGEBACK_PLUS_TRUNCATION_CANDIDATE_ID,
        "candidate_kind": "stageback_plus_truncation",
        "candidate": copy.deepcopy(candidate),
        "focused_mutations": focused_mutations,
    }
    artifact = {
        "contract": "applied_bl_candidate.v1",
        "candidate_id": BL_STAGEBACK_PLUS_TRUNCATION_CANDIDATE_ID,
        "candidate_kind": "stageback_plus_truncation",
        "apply_gate": apply_gate,
        "applied": True,
        "reject_reason": None,
        "candidate": copy.deepcopy(candidate),
        "focused_mutations": focused_mutations,
        "production_default_changed": False,
        "topology_compiler_gate_off_changed": False,
        "plan_only_behavior_changed": False,
        "notes": [
            "This applied candidate only mutates the isolated focused pre-PLC fixture rerun.",
            "It does not change shell_v4 production defaults, Gmsh settings, shell_v3, or topology_compiler_gate=off.",
        ],
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "applied_candidate.v1.json"
    write_json_report(artifact_path, artifact)
    artifact["artifact_path"] = str(artifact_path)
    return transformed_fixture, artifact, None


def _run_root_last4_overlap_non_regression_check(
    *,
    source_path: Path,
    component: str,
    artifact_dir: Path,
) -> dict[str, Any]:
    fixture = _build_shell_v4_pre_plc_repro_fixture(
        source_path=source_path,
        component=component,
        family="root_last4_overlap",
        artifact_dir=artifact_dir / "fixture",
    )
    regularized = _apply_truncation_connector_band_operator_to_pre_plc_fixture(
        fixture,
        artifact_dir=artifact_dir / "regularized",
    )
    canonical_observed = _run_shell_v4_pre_plc_repro_fixture(
        regularized["fixture"],
        out_dir=artifact_dir / "canonical_probe",
    )
    transformed = _apply_post_band_transition_split_operator_to_pre_plc_fixture(
        regularized["fixture"],
        baseline_observed=canonical_observed,
        artifact_dir=artifact_dir / "post_band_transition",
    )
    observed = _run_shell_v4_pre_plc_repro_fixture(
        transformed["fixture"],
        out_dir=artifact_dir / "post_band_transition_probe",
    )
    localized = _apply_post_transition_boundary_recovery_operator_to_pre_plc_fixture(
        transformed["fixture"],
        baseline_observed=observed,
        artifact_dir=artifact_dir / "boundary_recovery_regularization",
    )
    after = _run_shell_v4_pre_plc_repro_fixture(
        localized["fixture"],
        out_dir=artifact_dir / "boundary_recovery_probe",
    )
    overlap_returned = (
        after.get("observed_failure_kind") == "facet_facet_overlap"
        or "Invalid boundary mesh (overlapping facets)" in str(after.get("error") or "")
    )
    return {
        "family": "root_last4_overlap",
        "candidate_applied": False,
        "overlap_non_regression": "fail" if overlap_returned else "pass",
        "canonical_failure_kind": canonical_observed.get("observed_failure_kind"),
        "post_transition_failure_kind": observed.get("observed_failure_kind"),
        "after_boundary_recovery_failure_kind": after.get("observed_failure_kind"),
        "report_path": after.get("report_path"),
    }


def _write_rejected_bl_candidate_apply_comparison(
    *,
    artifact_dir: Path,
    apply_gate: str,
    reject_reason: str,
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "bl_candidate_apply_comparison.v1.json"
    payload = {
        "contract": "bl_candidate_apply_comparison.v1",
        "candidate_id": (candidate or {}).get("candidate_id", BL_STAGEBACK_PLUS_TRUNCATION_CANDIDATE_ID),
        "candidate_kind": (candidate or {}).get("candidate_kind", "stageback_plus_truncation"),
        "apply_gate": apply_gate,
        "focused_path": "root_last3_segment_facet",
        "applied": False,
        "reject_reason": reject_reason,
        "before": {},
        "after": {},
        "comparison_verdict": "rejected",
        "production_default_changed": False,
        "topology_compiler_gate_off_changed": False,
        "plan_only_behavior_changed": False,
        "artifacts": {
            "bl_candidate_apply_comparison": str(artifact_path),
        },
        "notes": [
            "Rejected deterministically before mutating any focused fixture.",
            "Experimental BL candidate application is default-off.",
        ],
    }
    write_json_report(artifact_path, payload)
    return payload


def _run_shell_v4_bl_stageback_plus_truncation_focused_apply(
    *,
    out_dir: Path,
    apply_gate: str,
    source_path: Path,
    component: str,
    bl_candidate_comparison: dict[str, Any],
    root_last3_failed_steiner_forensic_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    apply_gate = _normalize_bl_candidate_apply_gate(apply_gate)
    artifact_dir = Path(out_dir) / "artifacts" / "topology_compiler" / "bl_candidate_apply"
    candidate, reject_reason = _validate_stageback_plus_truncation_candidate(
        apply_gate=apply_gate,
        bl_candidate_comparison=dict(bl_candidate_comparison or {}),
    )
    if reject_reason is not None:
        return _write_rejected_bl_candidate_apply_comparison(
            artifact_dir=artifact_dir,
            apply_gate=apply_gate,
            reject_reason=reject_reason,
            candidate=candidate,
        )

    root_last3_fixture = _build_shell_v4_pre_plc_repro_fixture(
        source_path=source_path,
        component=component,
        family="root_last3_segment_facet",
        artifact_dir=artifact_dir / "root_last3" / "fixture",
    )
    baseline = _run_shell_v4_pre_plc_repro_fixture(
        root_last3_fixture,
        out_dir=artifact_dir / "root_last3" / "baseline_probe",
    )
    transition = _apply_post_band_transition_split_operator_to_pre_plc_fixture(
        root_last3_fixture,
        baseline_observed=baseline,
        artifact_dir=artifact_dir / "root_last3" / "post_band_transition",
    )
    error2_observed = _run_shell_v4_pre_plc_repro_fixture(
        transition["fixture"],
        out_dir=artifact_dir / "root_last3" / "post_band_transition_probe",
    )
    if root_last3_failed_steiner_forensic_evidence:
        error2_observed["forensic_evidence"] = dict(root_last3_failed_steiner_forensic_evidence)
    localized = _apply_post_transition_boundary_recovery_operator_to_pre_plc_fixture(
        transition["fixture"],
        baseline_observed=error2_observed,
        artifact_dir=artifact_dir / "root_last3" / "boundary_recovery_regularization",
    )
    before_observed = _run_shell_v4_pre_plc_repro_fixture(
        localized["fixture"],
        out_dir=artifact_dir / "root_last3" / "before_apply_probe",
    )
    applied_fixture, applied_candidate, apply_reject_reason = _apply_stageback_plus_truncation_candidate_to_fixture(
        localized["fixture"],
        candidate=candidate,
        apply_gate=apply_gate,
        artifact_dir=artifact_dir,
    )
    if apply_reject_reason is not None:
        return _write_rejected_bl_candidate_apply_comparison(
            artifact_dir=artifact_dir,
            apply_gate=apply_gate,
            reject_reason=apply_reject_reason,
            candidate=candidate,
        )
    after_observed = _run_shell_v4_pre_plc_repro_fixture(
        applied_fixture,
        out_dir=artifact_dir / "root_last3" / "after_apply_probe",
    )
    before_summary = _focused_residual_summary(
        observed=before_observed,
        fallback_forensic_evidence=root_last3_failed_steiner_forensic_evidence,
    )
    after_summary = _focused_residual_summary(
        observed=after_observed,
        fallback_forensic_evidence=None,
    )
    root_last4_non_regression = _run_root_last4_overlap_non_regression_check(
        source_path=source_path,
        component=component,
        artifact_dir=artifact_dir / "root_last4_overlap_non_regression",
    )
    artifact_path = artifact_dir / "bl_candidate_apply_comparison.v1.json"
    payload = {
        "contract": "bl_candidate_apply_comparison.v1",
        "candidate_id": BL_STAGEBACK_PLUS_TRUNCATION_CANDIDATE_ID,
        "candidate_kind": "stageback_plus_truncation",
        "apply_gate": apply_gate,
        "focused_path": "root_last3_segment_facet",
        "focused_scope": "isolated_pre_plc_fixture_rerun",
        "applied": True,
        "reject_reason": None,
        "before": before_summary,
        "after": after_summary,
        "comparison_verdict": _focused_apply_verdict(
            before=before_summary,
            after=after_summary,
            applied=True,
            reject_reason=None,
        ),
        "applied_candidate": applied_candidate,
        "non_regression_checks": {
            "root_last4_overlap": root_last4_non_regression,
        },
        "production_default_changed": False,
        "topology_compiler_gate_off_changed": False,
        "plan_only_behavior_changed": False,
        "artifacts": {
            "applied_candidate": str(applied_candidate["artifact_path"]),
            "bl_candidate_apply_comparison": str(artifact_path),
            "before_root_last3_report": str(before_observed.get("report_path")),
            "after_root_last3_report": str(after_observed.get("report_path")),
        },
        "notes": [
            "This is an explicit experimental focused apply gate, not a production default.",
            "Success criteria are failed-Steiner/degenerated-prism/local-window improvement or a cleaner downstream family, not a full prelaunch pass.",
            "root_last4 overlap is checked as a non-regression path and the candidate is not applied there.",
        ],
    }
    write_json_report(artifact_path, payload)
    return payload


def _find_staged_transition_prototype(
    staged_transition_prototypes: dict[str, Any],
    prototype_id: str = BL_STAGED_TRANSITION_GUARD_PROTOTYPE_ID,
) -> dict[str, Any]:
    for prototype in list(staged_transition_prototypes.get("prototypes") or []):
        if isinstance(prototype, dict) and prototype.get("prototype_id") == prototype_id:
            return dict(prototype)
    return {}


def _validate_staged_transition_guard_prototype(
    *,
    apply_gate: str,
    staged_transition_prototypes: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    if apply_gate == BL_CANDIDATE_APPLY_GATE_OFF:
        return {}, "apply_gate_disabled"
    if apply_gate != BL_CANDIDATE_APPLY_GATE_STAGED_TRANSITION_GUARD_FOCUSED:
        return {}, "unsupported_apply_gate"
    if not isinstance(staged_transition_prototypes, dict) or not staged_transition_prototypes:
        return {}, "staged_transition_prototypes_missing"
    if (
        staged_transition_prototypes.get("contract")
        != BL_TOPOLOGY_PRESERVING_STAGED_TRANSITION_PROTOTYPES_CONTRACT
    ):
        return {}, "staged_transition_prototypes_contract_mismatch"
    if (
        staged_transition_prototypes.get("recommended_next_experimental_apply_prototype_id")
        != BL_STAGED_TRANSITION_GUARD_PROTOTYPE_ID
    ):
        return {}, "recommended_prototype_not_stage_with_termination_guard_8_to_7"
    prototype = _find_staged_transition_prototype(staged_transition_prototypes)
    if not prototype:
        return {}, "stage_with_termination_guard_8_to_7_prototype_missing"
    if prototype.get("planning_only") is not True:
        return prototype, "prototype_is_not_from_planning_surface"
    layer_schedule = [int(value) for value in list(prototype.get("layer_schedule") or [])]
    if layer_schedule != [8, 7]:
        return prototype, "prototype_layer_schedule_not_mild_8_to_7"
    if any(layer <= 6 for layer in layer_schedule[1:]):
        return prototype, "prototype_layer_schedule_too_aggressive"
    breakpoints = [float(value) for value in list(prototype.get("y_breakpoints") or [])]
    if len(breakpoints) != 1:
        return prototype, "prototype_missing_single_terminal_guard_breakpoint"
    target_y_span = dict(staged_transition_prototypes.get("target_y_span") or {})
    if target_y_span.get("min") is None or target_y_span.get("max") is None:
        return prototype, "prototype_missing_target_y_span"
    y_min = float(target_y_span["min"])
    y_max = float(target_y_span["max"])
    guard_y = float(breakpoints[0])
    if guard_y <= y_min or guard_y >= y_max:
        return prototype, "prototype_guard_not_inside_terminal_span"
    return prototype, None


def _loop_fields_from_focused_summary(
    summary: dict[str, Any],
    *,
    guarded_transition: bool,
) -> dict[str, Any]:
    symptoms = set(str(value) for value in list(summary.get("observed_symptoms") or []))
    if (
        summary.get("diagnostic_family") == "gmsh_1d_loop_closure_failure"
        or "gmsh_1d_loop_not_closed" in symptoms
    ):
        return {
            "loop_closed": False,
            "termination_ring_valid": False,
            "connector_band_continuity": "fail",
        }
    if summary.get("reached_gmsh_3d_boundary_recovery") or summary.get("failure_phase") == "gmsh_3d_boundary_recovery":
        return {
            "loop_closed": True,
            "termination_ring_valid": "guarded_inferred" if guarded_transition else "inferred",
            "connector_band_continuity": "pass",
        }
    return {
        "loop_closed": "unknown",
        "termination_ring_valid": "unknown",
        "connector_band_continuity": "unknown",
    }


def _staged_transition_endpoint_summary(
    summary: dict[str, Any],
    *,
    guarded_transition: bool,
) -> dict[str, Any]:
    loop_fields = _loop_fields_from_focused_summary(
        summary,
        guarded_transition=guarded_transition,
    )
    return {
        "residual_family": summary.get("residual_family"),
        "failure_kind": summary.get("observed_failure_kind"),
        "local_y_band": list(summary.get("local_y_band") or []),
        "suspicious_window": list(summary.get("suspicious_window") or []),
        "degenerated_prism_seen": summary.get("degenerated_prism_seen"),
        **loop_fields,
    }


def _staged_transition_apply_verdict(
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    applied: bool,
    reject_reason: str | None,
) -> str:
    if not applied or reject_reason:
        return "rejected"
    if after.get("loop_closed") is False:
        return "induced_loop_closure_failure"
    before_failure = str(before.get("failure_kind") or "")
    after_failure = str(after.get("failure_kind") or "")
    before_family = str(before.get("residual_family") or "")
    after_family = str(after.get("residual_family") or "")
    if after_failure == "segment_facet_intersection" and after_failure != before_failure:
        return "reintroduced_segment_facet"
    if after_failure == "facet_facet_overlap" and after_failure != before_failure:
        return "worsened"
    local_change = _window_change_label(before.get("local_y_band"), after.get("local_y_band"))
    suspicious_change = _window_change_label(
        before.get("suspicious_window"),
        after.get("suspicious_window"),
    )
    prism_improved = (
        before.get("degenerated_prism_seen") is True
        and after.get("degenerated_prism_seen") is False
    )
    if local_change == "reduced" or suspicious_change == "reduced" or prism_improved:
        return "improved"
    if before_family == FAILED_STEINER_RESIDUAL_FAMILY and after_family != before_family:
        if after_family or after_failure != before_failure:
            return "shifted_to_cleaner_family"
    if before_family == FAILED_STEINER_RESIDUAL_FAMILY and after_family == before_family:
        return "unchanged_same_failed_steiner"
    return "unknown"


def _staged_transition_recommended_next_action(comparison_verdict: str) -> str:
    if comparison_verdict in {"improved", "shifted_to_cleaner_family"}:
        return "keep_stage_guard_candidate"
    if comparison_verdict == "unchanged_same_failed_steiner":
        return "tune_guard_location"
    if comparison_verdict in {"reintroduced_segment_facet", "worsened"}:
        return "revert_candidate"
    if comparison_verdict == "induced_loop_closure_failure":
        return "requires_loop_graph_instrumentation"
    if comparison_verdict == "rejected":
        return "requires_loop_graph_instrumentation"
    return "requires_loop_graph_instrumentation"


def _write_rejected_staged_transition_apply_comparison(
    *,
    artifact_dir: Path,
    apply_gate: str,
    reject_reason: str,
    prototype: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "staged_transition_apply_comparison.v1.json"
    payload = {
        "contract": BL_STAGED_TRANSITION_APPLY_COMPARISON_CONTRACT,
        "prototype_id": (prototype or {}).get(
            "prototype_id",
            BL_STAGED_TRANSITION_GUARD_PROTOTYPE_ID,
        ),
        "apply_gate": apply_gate,
        "focused_path": "root_last3_segment_facet",
        "focused_scope": "isolated_pre_plc_fixture_rerun",
        "planning_only": False,
        "experimental_focused_only": True,
        "full_prelaunch_pass_attempted": False,
        "applied": False,
        "reject_reason": reject_reason,
        "before": {},
        "after": {},
        "comparison_verdict": "rejected",
        "recommended_next_action": _staged_transition_recommended_next_action("rejected"),
        "production_default_changed": False,
        "topology_compiler_gate_off_changed": False,
        "plan_only_behavior_changed": False,
        "runtime_bl_spec_mutation": False,
        "runtime_geometry_mutation": False,
        "gmsh_settings_changed": False,
        "shell_v3_changed": False,
        "topology_operator_added": False,
        "root_last4_overlap_path_changed": False,
        "artifacts": {
            "staged_transition_apply_comparison": str(artifact_path),
        },
        "notes": [
            "Rejected deterministically before mutating any focused fixture.",
            "The guarded staged-transition apply gate is explicit, experimental, and default-off.",
        ],
    }
    write_json_report(artifact_path, payload)
    return payload


def _apply_staged_transition_guard_prototype_to_fixture(
    fixture: dict[str, Any],
    *,
    prototype: dict[str, Any],
    apply_gate: str,
    artifact_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    layer_schedule = [int(value) for value in list(prototype.get("layer_schedule") or [])]
    breakpoints = [float(value) for value in list(prototype.get("y_breakpoints") or [])]
    if layer_schedule != [8, 7]:
        return copy.deepcopy(fixture), {}, "prototype_layer_schedule_not_mild_8_to_7"
    if len(breakpoints) != 1:
        return copy.deepcopy(fixture), {}, "prototype_missing_single_terminal_guard_breakpoint"

    guard_y = float(breakpoints[0])
    transformed_fixture = copy.deepcopy(fixture)
    focused_mutations = {
        "layers_before": int(layer_schedule[0]),
        "layers_after": int(layer_schedule[-1]),
        "staged_layer_schedule": list(layer_schedule),
        "stage_transition_y_m": guard_y,
        "terminal_guard_y_m": guard_y,
        "focused_fixture_only": True,
        "applies_to_family": "root_last3_segment_facet",
        "applies_to_region": "root_last3_tip_terminal_tight_region",
        "topology_preserving_transition": True,
        "avoids_direct_drop_8_to_5": True,
        "avoids_aggressive_drop_8_to_6": True,
    }
    transformed_fixture["focused_bl_candidate_apply"] = {
        "enabled": True,
        "apply_gate": apply_gate,
        "candidate_id": BL_STAGED_TRANSITION_GUARD_PROTOTYPE_ID,
        "candidate_kind": "topology_preserving_staged_transition",
        "prototype_id": BL_STAGED_TRANSITION_GUARD_PROTOTYPE_ID,
        "prototype": copy.deepcopy(prototype),
        "focused_mutations": focused_mutations,
    }
    artifact = {
        "contract": "applied_staged_transition.v1",
        "prototype_id": BL_STAGED_TRANSITION_GUARD_PROTOTYPE_ID,
        "apply_gate": apply_gate,
        "applied": True,
        "reject_reason": None,
        "prototype": copy.deepcopy(prototype),
        "focused_mutations": focused_mutations,
        "production_default_changed": False,
        "topology_compiler_gate_off_changed": False,
        "plan_only_behavior_changed": False,
        "runtime_geometry_mutation": False,
        "runtime_bl_spec_mutation": False,
        "notes": [
            "This applies the staged transition only to the isolated root_last3 focused fixture rerun.",
            "The production shell_v4 route defaults, shell_v3, Gmsh settings, and topology operators are unchanged.",
        ],
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "applied_staged_transition.v1.json"
    write_json_report(artifact_path, artifact)
    artifact["artifact_path"] = str(artifact_path)
    return transformed_fixture, artifact, None


def _run_shell_v4_bl_staged_transition_guard_focused_apply(
    *,
    out_dir: Path,
    apply_gate: str,
    source_path: Path,
    component: str,
    staged_transition_prototypes: dict[str, Any],
    root_last3_failed_steiner_forensic_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    apply_gate = _normalize_bl_candidate_apply_gate(apply_gate)
    artifact_dir = Path(out_dir) / "artifacts" / "topology_compiler" / "staged_transition_apply"
    prototype, reject_reason = _validate_staged_transition_guard_prototype(
        apply_gate=apply_gate,
        staged_transition_prototypes=dict(staged_transition_prototypes or {}),
    )
    if reject_reason is not None:
        return _write_rejected_staged_transition_apply_comparison(
            artifact_dir=artifact_dir,
            apply_gate=apply_gate,
            reject_reason=reject_reason,
            prototype=prototype,
        )

    root_last3_fixture = _build_shell_v4_pre_plc_repro_fixture(
        source_path=source_path,
        component=component,
        family="root_last3_segment_facet",
        artifact_dir=artifact_dir / "root_last3" / "fixture",
    )
    baseline = _run_shell_v4_pre_plc_repro_fixture(
        root_last3_fixture,
        out_dir=artifact_dir / "root_last3" / "baseline_probe",
    )
    transition = _apply_post_band_transition_split_operator_to_pre_plc_fixture(
        root_last3_fixture,
        baseline_observed=baseline,
        artifact_dir=artifact_dir / "root_last3" / "post_band_transition",
    )
    error2_observed = _run_shell_v4_pre_plc_repro_fixture(
        transition["fixture"],
        out_dir=artifact_dir / "root_last3" / "post_band_transition_probe",
    )
    if root_last3_failed_steiner_forensic_evidence:
        error2_observed["forensic_evidence"] = dict(root_last3_failed_steiner_forensic_evidence)
    localized = _apply_post_transition_boundary_recovery_operator_to_pre_plc_fixture(
        transition["fixture"],
        baseline_observed=error2_observed,
        artifact_dir=artifact_dir / "root_last3" / "boundary_recovery_regularization",
    )
    before_observed = _run_shell_v4_pre_plc_repro_fixture(
        localized["fixture"],
        out_dir=artifact_dir / "root_last3" / "before_apply_probe",
    )
    applied_fixture, applied_transition, apply_reject_reason = (
        _apply_staged_transition_guard_prototype_to_fixture(
            localized["fixture"],
            prototype=prototype,
            apply_gate=apply_gate,
            artifact_dir=artifact_dir,
        )
    )
    if apply_reject_reason is not None:
        return _write_rejected_staged_transition_apply_comparison(
            artifact_dir=artifact_dir,
            apply_gate=apply_gate,
            reject_reason=apply_reject_reason,
            prototype=prototype,
        )
    after_observed = _run_shell_v4_pre_plc_repro_fixture(
        applied_fixture,
        out_dir=artifact_dir / "root_last3" / "after_apply_probe",
    )
    before_summary = _focused_residual_summary(
        observed=before_observed,
        fallback_forensic_evidence=root_last3_failed_steiner_forensic_evidence,
    )
    after_summary = _focused_residual_summary(observed=after_observed)
    before_endpoint = _staged_transition_endpoint_summary(
        before_summary,
        guarded_transition=False,
    )
    after_endpoint = _staged_transition_endpoint_summary(
        after_summary,
        guarded_transition=True,
    )
    comparison_verdict = _staged_transition_apply_verdict(
        before=before_endpoint,
        after=after_endpoint,
        applied=True,
        reject_reason=None,
    )
    root_last4_non_regression = _run_root_last4_overlap_non_regression_check(
        source_path=source_path,
        component=component,
        artifact_dir=artifact_dir / "root_last4_overlap_non_regression",
    )
    artifact_path = artifact_dir / "staged_transition_apply_comparison.v1.json"
    payload = {
        "contract": BL_STAGED_TRANSITION_APPLY_COMPARISON_CONTRACT,
        "prototype_id": BL_STAGED_TRANSITION_GUARD_PROTOTYPE_ID,
        "apply_gate": apply_gate,
        "focused_path": "root_last3_segment_facet",
        "focused_scope": "isolated_pre_plc_fixture_rerun",
        "planning_only": False,
        "experimental_focused_only": True,
        "full_prelaunch_pass_attempted": False,
        "applied": True,
        "reject_reason": None,
        "before": before_endpoint,
        "after": after_endpoint,
        "comparison_verdict": comparison_verdict,
        "recommended_next_action": _staged_transition_recommended_next_action(
            comparison_verdict
        ),
        "applied_staged_transition": applied_transition,
        "non_regression_checks": {
            "root_last4_overlap": root_last4_non_regression,
        },
        "production_default_changed": False,
        "topology_compiler_gate_off_changed": False,
        "plan_only_behavior_changed": False,
        "runtime_bl_spec_mutation": False,
        "runtime_geometry_mutation": False,
        "gmsh_settings_changed": False,
        "shell_v3_changed": False,
        "topology_operator_added": False,
        "root_last4_overlap_path_changed": False,
        "artifacts": {
            "applied_staged_transition": str(applied_transition["artifact_path"]),
            "staged_transition_apply_comparison": str(artifact_path),
            "before_root_last3_report": str(before_observed.get("report_path")),
            "after_root_last3_report": str(after_observed.get("report_path")),
        },
        "notes": [
            "This is an explicit default-off focused experimental apply for stage_with_termination_guard_8_to_7.",
            "Success criteria are not a full prelaunch pass; they are no segment-facet regression, no loop-closure failure, and improvement in failed-Steiner/degenerated-prism/local-window evidence.",
            "root_last4 overlap is checked only as non-regression; the staged transition is not applied to root_last4.",
        ],
    }
    write_json_report(artifact_path, payload)
    return payload


def _float_window_width(values: Any) -> float | None:
    if not isinstance(values, list) or len(values) < 2:
        return None
    numeric = [float(value) for value in values]
    return max(numeric) - min(numeric)


def _window_change_label(before: Any, after: Any) -> str:
    before_width = _float_window_width(before)
    after_width = _float_window_width(after)
    if before_width is None or after_width is None:
        return "unknown"
    tolerance = 1.0e-9
    if after_width < before_width - tolerance:
        return "reduced"
    if after_width > before_width + tolerance:
        return "expanded"
    return "not_reduced"


def _manual_candidate_handoff_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "candidate_id",
        "target_kind",
        "target_id",
        "planning_only",
        "span_y_range_m",
        "current_total_bl_thickness_m",
        "min_local_clearance_m",
        "current_clearance_ratio",
        "ratio_deficit",
        "available_budget_ratio_deficit",
        "suggested_max_total_bl_thickness_m",
        "suggested_thickness_reduction_m",
        "suggested_truncation_start_y_m",
        "suggested_split_boundary_y_m",
        "suggested_layer_stage_back_direction",
        "recommendation_kinds",
        "recommendation_reason",
    )
    return {field: candidate.get(field) for field in fields if field in candidate}


def _top_manual_candidate_handoffs(planning_budgeting: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    candidate_sources = [
        list(planning_budgeting.get("manual_edit_candidates") or []),
    ]
    for section in list(planning_budgeting.get("tightest_sections") or []):
        if isinstance(section, dict):
            candidate_sources.append(list(section.get("manual_edit_candidates") or []))
    for region in list(planning_budgeting.get("tightest_regions") or []):
        if isinstance(region, dict):
            candidate_sources.append(list(region.get("manual_edit_candidates") or []))
    for source in candidate_sources:
        for candidate in source:
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("candidate_id") or "")
            if candidate_id and candidate_id in seen:
                continue
            if candidate_id:
                seen.add(candidate_id)
            candidates.append(_manual_candidate_handoff_payload(candidate))
            if len(candidates) == 3:
                return candidates
    return candidates


def _boundary_recovery_plan_from_operator_result(operator_result: dict[str, Any]) -> dict[str, Any]:
    details = operator_result.get("details")
    if not isinstance(details, dict):
        return {}
    plan = details.get("boundary_recovery_regularization_plan")
    return dict(plan) if isinstance(plan, dict) else {}


def _failed_steiner_runtime_transition(
    *,
    before_observed: dict[str, Any],
    after_observed: dict[str, Any],
    residual_family: str | None,
    residual_status: str | None,
) -> str:
    before_kind = str(before_observed.get("observed_failure_kind") or "")
    after_kind = str(after_observed.get("observed_failure_kind") or "")
    if (
        residual_family == FAILED_STEINER_RESIDUAL_FAMILY
        and residual_status == "observed_candidate"
        and after_kind == before_kind
    ):
        return "unresolved_same_family"
    if after_kind and before_kind and after_kind != before_kind:
        return "cleaner_downstream_family"
    if not after_kind or after_kind == "unknown":
        return "unknown"
    if after_kind == before_kind:
        return "unresolved_same_family"
    return "unknown"


def _handoff_verdicts(
    *,
    operator_status: str,
    topology_next_action: str | None,
    failure_transition: str,
    bl_policy_fail_kinds: list[str],
    bl_recommended_action_kinds: list[str],
) -> tuple[str, list[str]]:
    supporting: list[str] = []
    if "stage_back_layers" in bl_recommended_action_kinds:
        supporting.append("requires_tip_zone_bl_stageback")
    if "truncate_tip_zone" in bl_recommended_action_kinds:
        supporting.append("tip_truncation_required")
    if "shrink_total_thickness" in bl_recommended_action_kinds:
        supporting.append("insufficient_clearance_budget")
    if failure_transition == "unresolved_same_family":
        supporting.append("unresolved_same_failed_steiner_family")
    if failure_transition == "unknown":
        supporting.append("runtime_rerun_required")
    if bl_policy_fail_kinds and operator_status == "applied":
        return "topology_attempted_but_bl_policy_blocked", supporting
    if failure_transition == "unresolved_same_family":
        return "unresolved_same_failed_steiner_family", supporting
    if topology_next_action == "local_transition_regularization":
        return "local_transition_regularization_candidate", supporting
    return "runtime_rerun_required", supporting


def _build_topology_bl_handoff_summary(
    *,
    operator_regression_runs: list[dict[str, Any]],
    blocking_bl_compatibility_check_kinds: list[str],
    planning_policy_fail_kinds: list[str],
    planning_policy_recommendation_kinds: list[str],
    planning_budgeting: dict[str, Any],
    bl_candidate_comparison: dict[str, Any] | None = None,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    manual_candidates = _top_manual_candidate_handoffs(planning_budgeting)
    candidate_comparison = bl_candidate_comparison or _build_bl_stageback_truncation_candidate_comparison(
        planning_budgeting=planning_budgeting,
        planning_policy_fail_kinds=list(planning_policy_fail_kinds),
        planning_policy_recommendation_kinds=list(planning_policy_recommendation_kinds),
    )
    candidate_list = copy.deepcopy(candidate_comparison.get("candidates", []))
    family_payloads: dict[str, Any] = {}
    for entry in operator_regression_runs:
        family = str(entry.get("family") or "unknown")
        before_observed = dict(entry.get("observed") or {})
        after_observed = dict(entry.get("boundary_recovery_observed") or {})
        operator_result = dict(entry.get("post_transition_boundary_recovery_operator_result") or {})
        plan = _boundary_recovery_plan_from_operator_result(operator_result)
        residual_classifier = dict(after_observed.get("downstream_residual_classifier") or {})
        residual_evidence = dict(residual_classifier.get("evidence") or {})
        before_forensic = _recoversegment_failed_steiner_evidence_from_observed(before_observed)
        residual_family = (
            residual_classifier.get("primary_residual_family")
            or plan.get("residual_family")
            or before_forensic.get("residual_family")
        )
        evidence_level = (
            residual_evidence.get("evidence_level")
            or plan.get("evidence_level")
            or before_forensic.get("evidence_level")
        )
        throw_site_label = (
            residual_evidence.get("throw_site_label")
            or plan.get("throw_site_label")
            or before_forensic.get("throw_site_label")
        )
        local_y_band = (
            residual_evidence.get("local_y_band")
            or plan.get("local_y_band")
            or before_forensic.get("local_y_band")
            or []
        )
        suspicious_window = (
            residual_evidence.get("suspicious_window")
            or plan.get("suspicious_window")
            or before_forensic.get("suspicious_window")
            or []
        )
        degenerated_prism_seen = (
            residual_evidence.get("degenerated_prism_seen")
            if residual_evidence.get("degenerated_prism_seen") is not None
            else plan.get("degenerated_prism_seen")
            if plan.get("degenerated_prism_seen") is not None
            else before_forensic.get("degenerated_prism_seen")
        )
        recommended_next_action = plan.get("recommended_next_action")
        topology_next_action = (
            str(recommended_next_action.get("kind"))
            if isinstance(recommended_next_action, dict) and recommended_next_action.get("kind")
            else None
        )
        failure_transition = _failed_steiner_runtime_transition(
            before_observed=before_observed,
            after_observed=after_observed,
            residual_family=str(residual_family) if residual_family is not None else None,
            residual_status=str(residual_classifier.get("classification_status") or ""),
        )
        final_verdict, supporting_verdicts = _handoff_verdicts(
            operator_status=str(operator_result.get("status") or ""),
            topology_next_action=topology_next_action,
            failure_transition=failure_transition,
            bl_policy_fail_kinds=list(planning_policy_fail_kinds),
            bl_recommended_action_kinds=list(planning_policy_recommendation_kinds),
        )
        family_payloads[family] = {
            "fixture_id": entry.get("fixture_id"),
            "residual_family": residual_family,
            "evidence_level": evidence_level,
            "throw_site_label": throw_site_label,
            "local_y_band": list(local_y_band),
            "suspicious_window": list(suspicious_window),
            "degenerated_prism_seen": degenerated_prism_seen,
            "operator_action_kind": plan.get("mutation_kind") or operator_result.get("operator_name"),
            "operator_result_status": operator_result.get("status"),
            "topology_recommended_next_action": topology_next_action,
            "bl_blocking_kinds": list(blocking_bl_compatibility_check_kinds),
            "bl_policy_fail_kinds": list(planning_policy_fail_kinds),
            "bl_recommended_action_kinds": list(planning_policy_recommendation_kinds),
            "manual_candidate_top_1_3": copy.deepcopy(manual_candidates),
            "bl_candidate_policy_surface": "planning_only_report",
            "candidate_comparison": copy.deepcopy(candidate_list),
            "recommended_bl_candidate_id": candidate_comparison.get("recommended_candidate_id"),
            "bl_candidate_recommendation_reason": candidate_comparison.get("recommendation_reason"),
            "topology_rerun_recommended_after_bl_candidate_application": candidate_comparison.get(
                "topology_rerun_recommended_after_candidate_application"
            ),
            "runtime_apply_gate_disabled": candidate_comparison.get("runtime_apply_gate_disabled", True),
            "runtime_comparison": {
                "validation_level": "focused_fixture_runtime_probe",
                "before_failure_kind": before_observed.get("observed_failure_kind"),
                "after_failure_kind": after_observed.get("observed_failure_kind"),
                "failure_transition": failure_transition,
                "residual_status": residual_classifier.get("classification_status"),
                "local_y_band_before": list(before_forensic.get("local_y_band") or []),
                "local_y_band_after": list(local_y_band),
                "local_y_band_change": _window_change_label(
                    before_forensic.get("local_y_band"),
                    list(local_y_band),
                ),
                "suspicious_window_before": list(before_forensic.get("suspicious_window") or []),
                "suspicious_window_after": list(suspicious_window),
                "suspicious_window_change": _window_change_label(
                    before_forensic.get("suspicious_window"),
                    list(suspicious_window),
                ),
                "throw_site_label_after": throw_site_label,
                "degenerated_prism_seen_after": degenerated_prism_seen,
            },
            "final_handoff_verdict": final_verdict,
            "supporting_verdicts": supporting_verdicts,
            "notes": [
                "Handoff is plan/report-only and must not mutate runtime geometry or BL specification.",
                "Focused fixture probes exercise the route failure path, but failed-Steiner throw-site metadata comes from the forensic artifact when local Gmsh is not patched.",
            ],
        }
    current_verdict = "topology_attempted_but_bl_policy_blocked" if planning_policy_fail_kinds else (
        candidate_comparison.get("current_verdict") or "runtime_rerun_required"
    )
    if family_payloads:
        verdicts = [
            str(payload.get("final_handoff_verdict") or "")
            for payload in family_payloads.values()
        ]
        if "topology_attempted_but_bl_policy_blocked" in verdicts:
            current_verdict = "topology_attempted_but_bl_policy_blocked"
        elif any(verdicts):
            current_verdict = verdicts[0]
    payload = {
        "contract": "topology_bl_handoff_summary.v1",
        "status": "written",
        "plan_report_only": True,
        "runtime_geometry_mutation": False,
        "runtime_bl_spec_mutation": False,
        "artifact_path": str(artifact_path) if artifact_path is not None else None,
        "current_verdict": current_verdict,
        "candidate_comparison": copy.deepcopy(candidate_list),
        "candidate_comparison_table": copy.deepcopy(
            candidate_comparison.get("candidate_comparison_table", [])
        ),
        "recommended_candidate_id": candidate_comparison.get("recommended_candidate_id"),
        "recommendation_reason": candidate_comparison.get("recommendation_reason"),
        "topology_rerun_recommended_after_candidate_application": candidate_comparison.get(
            "topology_rerun_recommended_after_candidate_application"
        ),
        "runtime_apply_gate_enabled": candidate_comparison.get("runtime_apply_gate_enabled", False),
        "runtime_apply_gate_disabled": candidate_comparison.get("runtime_apply_gate_disabled", True),
        "bl_policy": {
            "blocking_kinds": list(blocking_bl_compatibility_check_kinds),
            "fail_kinds": list(planning_policy_fail_kinds),
            "recommended_action_kinds": list(planning_policy_recommendation_kinds),
            "manual_candidate_top_1_3": copy.deepcopy(manual_candidates),
            "candidate_comparison_contract": candidate_comparison.get("contract"),
        },
        "families": family_payloads,
        "notes": [
            "This summary aligns topology residual/operator evidence with BL budgeting advice for downstream decision-making.",
            "It is not a full prelaunch pass claim.",
            "BL candidate comparison is planning-only; runtime apply remains disabled.",
        ],
    }
    if artifact_path is not None:
        write_json_report(Path(artifact_path), payload)
    return payload


def _normalize_topology_compiler_gate(topology_compiler_gate: str | None) -> str:
    normalized = str(topology_compiler_gate or TOPOLOGY_COMPILER_GATE_OFF).strip().lower()
    if normalized not in {
        TOPOLOGY_COMPILER_GATE_OFF,
        TOPOLOGY_COMPILER_GATE_PLAN_ONLY,
    }:
        raise ValueError(
            "Unsupported shell_v4 topology compiler gate: "
            f"{topology_compiler_gate!r}; expected 'off' or 'plan_only'."
        )
    return normalized


def _normalize_bl_candidate_apply_gate(bl_candidate_apply_gate: str | None) -> str:
    normalized = str(bl_candidate_apply_gate or BL_CANDIDATE_APPLY_GATE_OFF).strip().lower()
    if normalized in {"stageback_plus_truncation", "apply_stageback_plus_truncation_focused"}:
        normalized = BL_CANDIDATE_APPLY_GATE_STAGEBACK_PLUS_TRUNCATION_FOCUSED
    if normalized in {
        "stage_with_termination_guard_8_to_7",
        "apply_stage_with_termination_guard_8_to_7_focused",
    }:
        normalized = BL_CANDIDATE_APPLY_GATE_STAGED_TRANSITION_GUARD_FOCUSED
    if normalized not in {
        BL_CANDIDATE_APPLY_GATE_OFF,
        BL_CANDIDATE_APPLY_GATE_STAGEBACK_PLUS_TRUNCATION_FOCUSED,
        BL_CANDIDATE_APPLY_GATE_STAGED_TRANSITION_GUARD_FOCUSED,
    }:
        raise ValueError(
            "Unsupported shell_v4 BL candidate apply gate: "
            f"{bl_candidate_apply_gate!r}; expected 'off' or "
            f"'{BL_CANDIDATE_APPLY_GATE_STAGEBACK_PLUS_TRUNCATION_FOCUSED}' or "
            f"'{BL_CANDIDATE_APPLY_GATE_STAGED_TRANSITION_GUARD_FOCUSED}'."
        )
    return normalized


def _collect_shell_v4_pre_plc_observed_evidence(
    *,
    source_path: Path,
    component: str,
    artifact_dir: Path,
) -> tuple[list[PrePLCAuditObservedEvidenceV1], list[dict[str, Any]]]:
    evidences: list[PrePLCAuditObservedEvidenceV1] = []
    fixture_runs: list[dict[str, Any]] = []
    observed_dir = artifact_dir / "observed_fixtures"
    for family, check_kind in (
        ("root_last3_segment_facet", "segment_facet_intersection_risk"),
        ("root_last4_overlap", "facet_facet_overlap_risk"),
    ):
        fixture_dir = observed_dir / family
        fixture = _build_shell_v4_pre_plc_repro_fixture(
            source_path=source_path,
            component=component,
            family=family,
            artifact_dir=fixture_dir / "fixture",
        )
        observed = _run_shell_v4_pre_plc_repro_fixture(
            fixture,
            out_dir=fixture_dir / "run",
        )
        matched = (
            observed["status"] == "failed"
            and observed["observed_failure_kind"] == fixture["expected_failure_kind"]
            and all(
                substring in observed["error"]
                for substring in fixture["expected_error_substrings"]
            )
        )
        fixture_runs.append(
            {
                "fixture": fixture,
                "observed": observed,
                "matched_expected_failure": matched,
            }
        )
        if not matched:
            continue
        evidences.append(
            PrePLCAuditObservedEvidenceV1(
                fixture_id=str(fixture["fixture_id"]),
                check_kind=check_kind,
                error_text=str(observed["error"]),
                selected_section_y_le_m=[
                    float(value) for value in fixture.get("selected_section_y_le_m", [])
                ],
                report_path=str(observed["report_path"]),
                notes=[
                    f"family={family}",
                    f"observed_failure_kind={observed['observed_failure_kind']}",
                ],
            )
        )
    write_json_report(observed_dir / "fixture_runs.json", {"fixture_runs": fixture_runs})
    return evidences, fixture_runs


def _collect_shell_v4_pre_plc_operator_regression_reports(
    *,
    fixture_runs: list[dict[str, Any]],
    artifact_dir: Path,
) -> tuple[list[dict[str, Any]], Path]:
    regression_dir = artifact_dir / "operator_regression"
    regression_runs: list[dict[str, Any]] = []
    for entry in fixture_runs:
        fixture = dict(entry["fixture"])
        family = str(fixture["family"])
        regularized = _apply_truncation_connector_band_operator_to_pre_plc_fixture(
            fixture,
            artifact_dir=regression_dir / family / "operator",
        )
        canonical_observed = _run_shell_v4_pre_plc_repro_fixture(
            regularized["fixture"],
            out_dir=regression_dir / family / "canonical_run",
        )
        transition_split = _apply_post_band_transition_split_operator_to_pre_plc_fixture(
            regularized["fixture"],
            baseline_observed=canonical_observed,
            artifact_dir=regression_dir / family / "post_band_transition",
        )
        observed = _run_shell_v4_pre_plc_repro_fixture(
            transition_split["fixture"],
            out_dir=regression_dir / family / "run",
        )
        boundary_recovery_regularized = _apply_post_transition_boundary_recovery_operator_to_pre_plc_fixture(
            transition_split["fixture"],
            baseline_observed=observed,
            artifact_dir=regression_dir / family / "boundary_recovery_regularization",
        )
        boundary_recovery_observed = _run_shell_v4_pre_plc_repro_fixture(
            boundary_recovery_regularized["fixture"],
            out_dir=regression_dir / family / "boundary_recovery_run",
        )
        regression_runs.append(
            {
                "fixture_id": fixture["fixture_id"],
                "family": family,
                "baseline_expected_failure_kind": fixture["expected_failure_kind"],
                "truncation_connector_band_operator_result": regularized["operator_result"],
                "post_band_transition_operator_result": transition_split["operator_result"],
                "post_transition_boundary_recovery_operator_result": boundary_recovery_regularized[
                    "operator_result"
                ],
                "regularized_fixture": {
                    "selected_section_y_le_m": regularized["fixture"]["selected_section_y_le_m"],
                },
                "transition_split_fixture": {
                    "selected_section_y_le_m": transition_split["fixture"]["selected_section_y_le_m"],
                },
                "boundary_recovery_fixture": {
                    "selected_section_y_le_m": boundary_recovery_regularized["fixture"][
                        "selected_section_y_le_m"
                    ],
                },
                "canonical_observed": canonical_observed,
                "observed": observed,
                "boundary_recovery_observed": boundary_recovery_observed,
                "improved_original_failure_family": (
                    observed["observed_failure_kind"] != fixture["expected_failure_kind"]
                ),
                "changed_failure_kind_after_transition_split": (
                    observed["observed_failure_kind"] != canonical_observed["observed_failure_kind"]
                ),
                "changed_failure_kind_after_boundary_recovery_operator": (
                    boundary_recovery_observed["observed_failure_kind"] != observed["observed_failure_kind"]
                ),
            }
        )
    report_path = regression_dir / "operator_regression_runs.json"
    write_json_report(report_path, {"fixture_runs": regression_runs})
    return regression_runs, report_path


def _build_shell_v4_topology_compiler_topology_report(
    *,
    source_path: Path,
    export_path: Path,
    topology_lineage_report_path: Path,
    topology_suppression_report_path: Path,
    topology_lineage_report: dict[str, Any],
) -> dict[str, Any]:
    interval_count = sum(
        max(len(surface.get("rule_sections", []) or []) - 1, 0)
        for surface in topology_lineage_report.get("surfaces", [])
    )
    surface_count = int(interval_count) if interval_count > 0 else int(
        topology_lineage_report.get("surface_count", 0) or 0
    )
    return {
        "representation": "shell_v4_native_section_lineage",
        "source_kind": str(source_path.suffix.lower().lstrip(".") or "unknown"),
        "units": "m",
        "body_count": int(topology_lineage_report.get("surface_count", 0) or 0),
        "surface_count": surface_count,
        "volume_count": 1,
        "source_path": str(source_path),
        "export_path": str(export_path),
        "topology_lineage_report": {"artifact": str(topology_lineage_report_path)},
        "topology_suppression_report": {"artifact": str(topology_suppression_report_path)},
    }


def _run_shell_v4_topology_compiler_plan_only(
    *,
    out_dir: Path,
    geometry: dict[str, Any],
    real_wing_geometry: dict[str, Any],
    boundary_layer: dict[str, Any],
    real_wing_bl_protection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_dir = Path(out_dir) / "artifacts" / "topology_compiler"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(real_wing_geometry.get("source_path") or geometry.get("source_path") or _default_real_main_wing_source_path())
    component = str(real_wing_geometry.get("component") or geometry.get("component") or "main_wing")
    provider_dir = artifact_dir / "provider_inputs"

    rebuild_model = _build_native_rebuild_model(source_path=source_path, component=component)
    baseline_rebuild_model, topology_suppression_report = _apply_terminal_strip_suppression(rebuild_model)
    topology_lineage_report = _build_topology_lineage_report(baseline_rebuild_model)
    topology_lineage_report_path = provider_dir / "topology_lineage_report.json"
    topology_suppression_report_path = provider_dir / "topology_suppression_report.json"
    write_json_report(topology_lineage_report_path, topology_lineage_report)
    write_json_report(topology_suppression_report_path, topology_suppression_report)

    observed_evidence, fixture_runs = _collect_shell_v4_pre_plc_observed_evidence(
        source_path=source_path,
        component=component,
        artifact_dir=artifact_dir,
    )
    planning_budgeting = _build_real_wing_bl_budgeting_plan(
        sections=[dict(section) for section in real_wing_geometry.get("sections", [])],
        protection=dict(real_wing_bl_protection or {}),
        base_total_thickness_m=float(boundary_layer["target_total_thickness_m"]),
        half_span_m=float(geometry.get("half_span_m") or DEFAULT_HALF_SPAN_M),
    )
    operator_regression_runs, operator_regression_report_path = (
        _collect_shell_v4_pre_plc_operator_regression_reports(
            fixture_runs=fixture_runs,
            artifact_dir=artifact_dir,
        )
    )
    topology_report = _build_shell_v4_topology_compiler_topology_report(
        source_path=source_path,
        export_path=Path(real_wing_geometry["artifact_path"]),
        topology_lineage_report_path=topology_lineage_report_path,
        topology_suppression_report_path=topology_suppression_report_path,
        topology_lineage_report=topology_lineage_report,
    )
    result = compile_topology_family_v1(
        topology_report=topology_report,
        topology_lineage_report=topology_lineage_report,
        topology_suppression_report=topology_suppression_report,
        component=component,
        shell_role="shell_v4",
        out_dir=artifact_dir,
        audit_config=PrePLCAuditConfigV1(
            first_layer_height_m=float(boundary_layer["first_layer_height_m"]),
            total_boundary_layer_thickness_m=float(boundary_layer["target_total_thickness_m"]),
            observed_evidence=observed_evidence,
            planning_budgeting=planning_budgeting,
        ),
    )
    bl_candidate_comparison_path = artifact_dir / "bl_stageback_truncation_candidate_comparison.v1.json"
    bl_candidate_comparison = _build_bl_stageback_truncation_candidate_comparison(
        planning_budgeting=result.pre_plc_audit.planning_budgeting.model_dump(mode="json"),
        planning_policy_fail_kinds=list(result.pre_plc_audit.planning_policy_fail_kinds),
        planning_policy_recommendation_kinds=list(
            result.pre_plc_audit.planning_policy_recommendation_kinds
        ),
        original_layer_count=int(boundary_layer.get("layers") or 0),
        artifact_path=bl_candidate_comparison_path,
    )
    handoff_summary_path = artifact_dir / "topology_bl_handoff_summary.v1.json"
    handoff_summary = _build_topology_bl_handoff_summary(
        operator_regression_runs=operator_regression_runs,
        blocking_bl_compatibility_check_kinds=list(
            result.pre_plc_audit.blocking_bl_compatibility_check_kinds
        ),
        planning_policy_fail_kinds=list(result.pre_plc_audit.planning_policy_fail_kinds),
        planning_policy_recommendation_kinds=list(
            result.pre_plc_audit.planning_policy_recommendation_kinds
        ),
        planning_budgeting=result.pre_plc_audit.planning_budgeting.model_dump(mode="json"),
        bl_candidate_comparison=bl_candidate_comparison,
        artifact_path=handoff_summary_path,
    )
    return {
        "gate": TOPOLOGY_COMPILER_GATE_PLAN_ONLY,
        "status": "written",
        "contract": result.contract,
        "source_path": str(source_path),
        "component": component,
        "artifacts": {
            "topology_ir": str(result.artifacts.topology_ir),
            "motif_registry": str(result.artifacts.motif_registry),
            "operator_plan": str(result.artifacts.operator_plan),
            "pre_plc_audit": str(result.artifacts.pre_plc_audit),
            "summary": str(result.artifacts.summary),
            "bl_candidate_comparison": str(bl_candidate_comparison_path),
            "handoff_summary": str(handoff_summary_path),
        },
        "handoff_summary": handoff_summary,
        "bl_candidate_comparison": bl_candidate_comparison,
        "provider_artifacts": {
            "topology_lineage_report": str(topology_lineage_report_path),
            "topology_suppression_report": str(topology_suppression_report_path),
            "fixture_runs": str((artifact_dir / "observed_fixtures" / "fixture_runs.json")),
            "operator_regression_runs": str(operator_regression_report_path),
        },
        "observed_fixture_count": int(len(observed_evidence)),
        "matched_fixture_families": [
            str(entry["fixture"]["family"])
            for entry in fixture_runs
            if entry.get("matched_expected_failure")
        ],
        "operator_regression_summary": {
            "regularization_applied_fixture_families": [
                str(entry["family"])
                for entry in operator_regression_runs
                if entry["truncation_connector_band_operator_result"]["status"] == "applied"
            ],
            "post_band_transition_applied_fixture_families": [
                str(entry["family"])
                for entry in operator_regression_runs
                if entry["post_band_transition_operator_result"]["status"] == "applied"
            ],
            "post_band_transition_changed_failure_kind_families": [
                str(entry["family"])
                for entry in operator_regression_runs
                if entry["changed_failure_kind_after_transition_split"]
            ],
            "post_transition_boundary_recovery_applied_fixture_families": [
                str(entry["family"])
                for entry in operator_regression_runs
                if entry["post_transition_boundary_recovery_operator_result"]["status"] == "applied"
            ],
            "post_transition_boundary_recovery_changed_failure_kind_families": [
                str(entry["family"])
                for entry in operator_regression_runs
                if entry["changed_failure_kind_after_boundary_recovery_operator"]
            ],
            "post_transition_boundary_recovery_same_failure_kind_families": [
                str(entry["family"])
                for entry in operator_regression_runs
                if not entry["changed_failure_kind_after_boundary_recovery_operator"]
            ],
            "post_transition_boundary_recovery_residual_families": {
                str(entry["family"]): entry["boundary_recovery_observed"]
                .get("downstream_residual_classifier", {})
                .get("primary_residual_family")
                for entry in operator_regression_runs
                if entry["boundary_recovery_observed"].get("downstream_residual_classifier")
            },
            "post_transition_boundary_recovery_residual_statuses": {
                str(entry["family"]): entry["boundary_recovery_observed"]
                .get("downstream_residual_classifier", {})
                .get("classification_status")
                for entry in operator_regression_runs
                if entry["boundary_recovery_observed"].get("downstream_residual_classifier")
            },
            "improved_fixture_families": [
                str(entry["family"])
                for entry in operator_regression_runs
                if entry["improved_original_failure_family"]
            ],
            "unchanged_fixture_families": [
                str(entry["family"])
                for entry in operator_regression_runs
                if not entry["improved_original_failure_family"]
            ],
        },
        "blocking_topology_check_kinds": list(result.pre_plc_audit.blocking_topology_check_kinds),
        "blocking_bl_compatibility_check_kinds": list(
            result.pre_plc_audit.blocking_bl_compatibility_check_kinds
        ),
        "planning_policy_fail_kinds": list(result.pre_plc_audit.planning_policy_fail_kinds),
        "planning_policy_recommendation_kinds": list(
            result.pre_plc_audit.planning_policy_recommendation_kinds
        ),
        "planning_policy": result.pre_plc_audit.planning_policy.model_dump(mode="json"),
        "planning_budgeting": result.pre_plc_audit.planning_budgeting.model_dump(mode="json"),
        "shell_role_policy": result.shell_role_policy.model_dump(mode="json"),
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
    loft_surface_tags: list[int] = []
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
    for lower_wire, upper_wire in zip(wire_tags[:-1], wire_tags[1:]):
        loft_entities = occ.addThruSections(
            [lower_wire, upper_wire],
            makeSolid=False,
            continuity="C1",
            parametrization="ChordLength",
            smoothing=True,
        )
        loft_surface_tags.extend(int(tag) for dim, tag in loft_entities if dim == 2)
    occ.synchronize()
    if not loft_surface_tags:
        raise RuntimeError("real main wing loft did not create any wall surfaces")
    tip_loop = occ.addCurveLoop(_order_curve_loop(gmsh, tip_curves))
    tip_surface_tag = int(occ.addPlaneSurface([tip_loop]))
    occ.synchronize()
    loft_surface_tags.append(tip_surface_tag)
    # The tip cap is geometrically coincident with the loft boundary, but OCC can
    # keep duplicate edges unless we explicitly collapse them before BL extrusion.
    occ.removeAllDuplicates()
    occ.synchronize()
    wall_surface_tags = [int(tag) for dim, tag in gmsh.model.getEntities(2) if dim == 2]
    (
        wall_surface_tags,
        tip_surface_tag,
        duplicate_surface_groups,
    ) = _deduplicate_wall_surfaces(
        gmsh,
        wall_surface_tags,
        tip_surface_tag=tip_surface_tag,
    )
    return wall_surface_tags, tip_curves, {
        "tip_surface_tag": tip_surface_tag,
        "duplicate_surface_groups": duplicate_surface_groups,
    }


def _select_tip_truncation_surface_tags(
    *,
    gmsh: Any,
    wall_surface_tags: list[int],
    start_y_m: float,
    tip_surface_tag: int | None,
    include_tip_cap: bool,
) -> list[int]:
    tolerance = 1.0e-6
    selected: list[int] = []
    for surface_tag in wall_surface_tags:
        if tip_surface_tag is not None and int(surface_tag) == int(tip_surface_tag):
            if include_tip_cap:
                selected.append(int(surface_tag))
            continue
        try:
            _x_min, y_min, _z_min, _x_max, y_max, _z_max = gmsh.model.getBoundingBox(2, int(surface_tag))
        except Exception:
            continue
        if y_min >= float(start_y_m) - tolerance and y_max > float(start_y_m) + tolerance:
            selected.append(int(surface_tag))
    return _unique_preserve_order(selected)


def _select_tip_truncation_connector_band_surface_tags(
    *,
    gmsh: Any,
    wall_surface_tags: list[int],
    band_start_y_m: float | None,
    start_y_m: float,
    tip_surface_tag: int | None,
) -> list[int]:
    if band_start_y_m is None:
        return []
    tolerance = 1.0e-6
    selected: list[int] = []
    for surface_tag in wall_surface_tags:
        if tip_surface_tag is not None and int(surface_tag) == int(tip_surface_tag):
            continue
        try:
            _x_min, y_min, _z_min, _x_max, y_max, _z_max = gmsh.model.getBoundingBox(2, int(surface_tag))
        except Exception:
            continue
        if (
            y_min >= float(band_start_y_m) - tolerance
            and y_max >= float(start_y_m) - tolerance
            and y_max <= float(start_y_m) + tolerance
            and y_min < float(start_y_m) - tolerance
        ):
            selected.append(int(surface_tag))
    return _unique_preserve_order(selected)


def _surface_boundary_curve_tags(
    gmsh: Any,
    surface_tag: int,
) -> list[int]:
    return [
        abs(int(entity_tag))
        for entity_dim, entity_tag in gmsh.model.getBoundary(
            [(2, int(surface_tag))],
            combined=False,
            oriented=True,
            recursive=False,
        )
        if int(entity_dim) == 1
    ]


def _extrude_boundary_layer_source_groups(
    *,
    gmsh: Any,
    source_surface_tags: list[int],
    extbl: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    index = 0
    for source_surface_tag in source_surface_tags:
        source_boundary_curve_tags = _surface_boundary_curve_tags(gmsh, int(source_surface_tag))
        group_length = len(source_boundary_curve_tags) + 2
        group_entities = list(extbl[index : index + group_length])
        index += group_length
        if len(group_entities) != group_length:
            raise RuntimeError(
                f"boundary-layer extrusion group for source surface {int(source_surface_tag)} is incomplete"
            )
        top_dim, top_surface_tag = group_entities[0]
        volume_dim, volume_tag = group_entities[1]
        if int(top_dim) != 2 or int(volume_dim) != 3:
            raise RuntimeError(
                f"unexpected boundary-layer group layout for source surface {int(source_surface_tag)}"
            )
        side_surface_by_curve: dict[int, int] = {}
        for curve_tag, (side_dim, side_surface_tag) in zip(
            source_boundary_curve_tags,
            group_entities[2:],
            strict=False,
        ):
            if int(side_dim) != 2:
                raise RuntimeError(
                    f"boundary-layer side entity for source surface {int(source_surface_tag)} curve {int(curve_tag)}"
                    " is not a surface"
                )
            side_surface_by_curve[int(curve_tag)] = int(side_surface_tag)
        groups.append(
            {
                "source_surface_tag": int(source_surface_tag),
                "source_boundary_curve_tags": list(source_boundary_curve_tags),
                "top_surface_tag": int(top_surface_tag),
                "volume_tag": int(volume_tag),
                "side_surface_by_curve": dict(side_surface_by_curve),
            }
        )
    if index != len(extbl):
        raise RuntimeError("boundary-layer extrusion groups did not consume all returned entities")
    return groups


def _select_tip_truncation_closure_source_surface_tags(
    *,
    gmsh: Any,
    bl_source_surface_tags: list[int],
    connector_band_start_y_m: float | None,
) -> list[int]:
    if connector_band_start_y_m is None:
        return []
    tolerance = 1.0e-6
    selected: list[int] = []
    for surface_tag in bl_source_surface_tags:
        try:
            _x_min, y_min, _z_min, _x_max, y_max, _z_max = gmsh.model.getBoundingBox(2, int(surface_tag))
        except Exception:
            continue
        if (
            y_max >= float(connector_band_start_y_m) - tolerance
            and y_max <= float(connector_band_start_y_m) + tolerance
            and y_min < float(connector_band_start_y_m) - tolerance
        ):
            selected.append(int(surface_tag))
    return _unique_preserve_order(selected)


def _ordered_curve_mesh_node_tags(
    gmsh: Any,
    curve_tag: int,
) -> list[int]:
    element_types, _element_tags_by_type, node_tags_by_type = gmsh.model.mesh.getElements(1, int(curve_tag))
    edges: list[tuple[int, int]] = []
    for element_type, node_tags in zip(element_types, node_tags_by_type, strict=False):
        if int(element_type) != 1:
            continue
        for index in range(0, len(node_tags), 2):
            edges.append((int(node_tags[index]), int(node_tags[index + 1])))
    if not edges:
        return []

    adjacency: dict[int, list[int]] = defaultdict(list)
    for start_node_tag, end_node_tag in edges:
        adjacency[int(start_node_tag)].append(int(end_node_tag))
        adjacency[int(end_node_tag)].append(int(start_node_tag))
    endpoints = [int(node_tag) for node_tag, neighbors in adjacency.items() if len(neighbors) == 1]
    start_node_tag = endpoints[0] if endpoints else int(edges[0][0])
    ordered_node_tags = [int(start_node_tag)]
    previous_node_tag: int | None = None
    current_node_tag = int(start_node_tag)
    max_steps = len(edges) + 2
    while len(ordered_node_tags) <= max_steps:
        next_candidates = [
            int(node_tag)
            for node_tag in adjacency.get(int(current_node_tag), [])
            if previous_node_tag is None or int(node_tag) != int(previous_node_tag)
        ]
        if not next_candidates:
            break
        next_node_tag = int(next_candidates[0])
        ordered_node_tags.append(int(next_node_tag))
        previous_node_tag = int(current_node_tag)
        current_node_tag = int(next_node_tag)
        if int(current_node_tag) == int(start_node_tag):
            break
    return [int(node_tag) for node_tag in ordered_node_tags]


def _deduplicate_polyline_points(
    points: Iterable[tuple[float, float, float]],
    *,
    tolerance: float = 1.0e-12,
) -> list[tuple[float, float, float]]:
    deduplicated: list[tuple[float, float, float]] = []
    for point in points:
        candidate = (float(point[0]), float(point[1]), float(point[2]))
        if deduplicated and math.dist(deduplicated[-1], candidate) <= tolerance:
            continue
        deduplicated.append(candidate)
    return deduplicated


def _curve_polyline_points(
    gmsh: Any,
    curve_tag: int,
    *,
    geometric_sample_count: int = 24,
) -> list[tuple[float, float, float]]:
    ordered_node_tags = _ordered_curve_mesh_node_tags(gmsh, int(curve_tag))
    if ordered_node_tags:
        return _deduplicate_polyline_points(
            tuple(float(value) for value in gmsh.model.mesh.getNode(int(node_tag))[0])
            for node_tag in ordered_node_tags
        )

    try:
        lower_bounds, upper_bounds = gmsh.model.getParametrizationBounds(1, int(curve_tag))
        lower = float(lower_bounds[0])
        upper = float(upper_bounds[0])
    except Exception:
        lower = 0.0
        upper = 0.0
    if geometric_sample_count > 1:
        sample_parameters = [
            float(lower + (upper - lower) * index / (geometric_sample_count - 1))
            for index in range(geometric_sample_count)
        ]
    else:
        sample_parameters = [float(lower)]
    try:
        sampled_points = _deduplicate_polyline_points(
            tuple(float(value) for value in gmsh.model.getValue(1, int(curve_tag), [parameter]))
            for parameter in sample_parameters
        )
        if len(sampled_points) >= 2 and _polyline_length(list(sampled_points)) > 1.0e-8:
            return sampled_points
    except Exception:
        pass
    boundary_points = gmsh.model.getBoundary(
        [(1, int(curve_tag))],
        combined=False,
        oriented=True,
        recursive=False,
    )
    return _deduplicate_polyline_points(
        tuple(float(value) for value in gmsh.model.getValue(0, int(entity_tag), []))
        for entity_dim, entity_tag in boundary_points
        if int(entity_dim) == 0
    )


def _polyline_length(
    points: list[tuple[float, float, float]],
) -> float:
    if len(points) < 2:
        return 0.0
    return float(
        sum(
            math.dist(points[index], points[index + 1])
            for index in range(len(points) - 1)
        )
    )


def _add_polyline_curve(
    geo: Any,
    points: list[tuple[float, float, float]],
    *,
    start_point_tag: int | None = None,
    end_point_tag: int | None = None,
) -> tuple[int, list[int]]:
    point_tags: list[int] = []
    for index, point in enumerate(points):
        if index == 0 and start_point_tag is not None:
            point_tags.append(int(start_point_tag))
            continue
        if index == len(points) - 1 and end_point_tag is not None:
            point_tags.append(int(end_point_tag))
            continue
        point_tags.append(int(geo.addPoint(*point)))
    if len(point_tags) < 2:
        raise RuntimeError("polyline curve reconstruction requires at least two distinct points")
    if len(point_tags) == 2:
        return int(geo.addLine(int(point_tags[0]), int(point_tags[1]))), [int(tag) for tag in point_tags]
    return int(geo.addSpline(point_tags)), [int(tag) for tag in point_tags]

def _limit_polyline_control_points(
    points: list[tuple[float, float, float]],
    *,
    max_points: int,
) -> list[tuple[float, float, float]]:
    if len(points) <= int(max_points):
        return list(points)
    if int(max_points) < 2:
        return [tuple(points[0]), tuple(points[-1])]
    selected_indices = _unique_preserve_order(
        int(round(index * (len(points) - 1) / (int(max_points) - 1)))
        for index in range(int(max_points))
    )
    limited_points = [tuple(points[index]) for index in selected_indices]
    if limited_points[0] != tuple(points[0]):
        limited_points[0] = tuple(points[0])
    if limited_points[-1] != tuple(points[-1]):
        limited_points[-1] = tuple(points[-1])
    return list(limited_points)


def _surface_signed_boundary_curve_loop(
    gmsh: Any,
    surface_tag: int,
) -> tuple[int, ...]:
    return tuple(
        int(entity_tag)
        for entity_dim, entity_tag in gmsh.model.getBoundary(
            [(2, int(surface_tag))],
            combined=False,
            oriented=True,
            recursive=False,
        )
        if int(entity_dim) == 1
    )


def _ordered_surface_boundary_curve_loop(
    gmsh: Any,
    surface_tag: int,
) -> tuple[int, ...]:
    return tuple(
        int(curve_tag)
        for curve_tag in _order_curve_loop(
            gmsh,
            _surface_boundary_curve_tags(gmsh, int(surface_tag)),
        )
    )


def _reverse_signed_curve_loop(
    signed_curve_tags: Iterable[int],
) -> tuple[int, ...]:
    return tuple(-int(curve_tag) for curve_tag in reversed(tuple(int(tag) for tag in signed_curve_tags)))


def _rotate_signed_curve_loop_to_start(
    signed_curve_tags: Iterable[int],
    *,
    start_signed_curve_tag: int,
) -> tuple[int, ...]:
    ordered = tuple(int(tag) for tag in signed_curve_tags)
    start_index = ordered.index(int(start_signed_curve_tag))
    return tuple(ordered[start_index:] + ordered[:start_index])


def _canonicalize_closure_wire_loop(
    signed_curve_tags: Iterable[int],
    *,
    connector_signed_curve_tag: int,
) -> tuple[int, int, int, int]:
    ordered = tuple(int(tag) for tag in signed_curve_tags)
    if len(ordered) != 4:
        raise RuntimeError(
            f"required closure ring wire must be 4-edge, got {len(ordered)} edges: {ordered}"
        )
    for candidate in (ordered, _reverse_signed_curve_loop(ordered)):
        if int(connector_signed_curve_tag) not in set(candidate):
            continue
        rotated = _rotate_signed_curve_loop_to_start(
            candidate,
            start_signed_curve_tag=int(connector_signed_curve_tag),
        )
        if len(rotated) == 4:
            return tuple(int(tag) for tag in rotated)
    raise RuntimeError(
        f"could not orient closure wire {ordered} around connector curve {int(connector_signed_curve_tag)}"
    )


def _curve_loop_vertex_degrees(
    gmsh: Any,
    signed_curve_tags: Iterable[int],
) -> dict[int, int]:
    vertex_degree: dict[int, int] = defaultdict(int)
    for signed_curve_tag in signed_curve_tags:
        start_point_tag, end_point_tag = _signed_curve_endpoint_tags(gmsh, int(signed_curve_tag))
        vertex_degree[int(start_point_tag)] += 1
        vertex_degree[int(end_point_tag)] += 1
    return {int(point_tag): int(degree) for point_tag, degree in vertex_degree.items()}


def _closure_wire_corner_point_tags(
    gmsh: Any,
    wire_signed_curves: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    connector_signed_curve, right_signed_curve, outer_signed_curve, left_signed_curve = (
        int(wire_signed_curves[0]),
        int(wire_signed_curves[1]),
        int(wire_signed_curves[2]),
        int(wire_signed_curves[3]),
    )
    connector_left_point_tag, connector_right_point_tag = _signed_curve_endpoint_tags(gmsh, connector_signed_curve)
    right_start_point_tag, outer_right_point_tag = _signed_curve_endpoint_tags(gmsh, right_signed_curve)
    outer_start_point_tag, outer_left_point_tag = _signed_curve_endpoint_tags(gmsh, outer_signed_curve)
    left_start_point_tag, left_end_point_tag = _signed_curve_endpoint_tags(gmsh, left_signed_curve)
    if right_start_point_tag != connector_right_point_tag:
        raise RuntimeError("closure wire right connector does not start at the connector endpoint")
    if outer_start_point_tag != outer_right_point_tag:
        raise RuntimeError("closure wire outer curve does not continue from the right connector")
    if left_start_point_tag != outer_left_point_tag:
        raise RuntimeError("closure wire left connector does not start at the outer endpoint")
    if left_end_point_tag != connector_left_point_tag:
        raise RuntimeError("closure wire left connector does not close back to the connector start")
    return (
        int(connector_left_point_tag),
        int(connector_right_point_tag),
        int(outer_right_point_tag),
        int(outer_left_point_tag),
    )


def _curve_mesh_point_count(
    gmsh: Any,
    curve_tag: int,
) -> int | None:
    ordered_node_tags = _ordered_curve_mesh_node_tags(gmsh, int(curve_tag))
    if not ordered_node_tags:
        return None
    return int(len(_unique_preserve_order(int(node_tag) for node_tag in ordered_node_tags)))


def _curve_length(
    gmsh: Any,
    curve_tag: int,
) -> float:
    curve_points = _curve_polyline_points(gmsh, int(curve_tag))
    return float(
        max(
            _polyline_length(list(curve_points)),
            _curve_length_proxy(gmsh, int(curve_tag)),
        )
    )


def _closure_patch_collapse_diagnostics(
    gmsh: Any,
    descriptor: ClosureRingPatchDesc,
    *,
    abs_tol: float = 1.0e-7,
    rel_tol: float = 1.0e-6,
) -> dict[str, Any]:
    connector_curve_length = _curve_length(gmsh, abs(int(descriptor.wire_source_signed_curves[0])))
    outer_curve_length = _curve_length(gmsh, abs(int(descriptor.wire_source_signed_curves[2])))
    right_curve_length = _curve_length(gmsh, abs(int(descriptor.wire_source_signed_curves[1])))
    left_curve_length = _curve_length(gmsh, abs(int(descriptor.wire_source_signed_curves[3])))
    connector_left_point_tag, connector_right_point_tag, outer_right_point_tag, outer_left_point_tag = (
        int(descriptor.semantic_corner_point_tags[0]),
        int(descriptor.semantic_corner_point_tags[1]),
        int(descriptor.semantic_corner_point_tags[2]),
        int(descriptor.semantic_corner_point_tags[3]),
    )
    right_span = math.dist(
        _point_xyz(gmsh, int(connector_right_point_tag)),
        _point_xyz(gmsh, int(outer_right_point_tag)),
    )
    left_span = math.dist(
        _point_xyz(gmsh, int(outer_left_point_tag)),
        _point_xyz(gmsh, int(connector_left_point_tag)),
    )
    collapse_tol = max(
        float(abs_tol),
        float(rel_tol) * max(float(connector_curve_length), float(outer_curve_length), 1.0),
    )
    collapsed_side_curve_tags = [
        abs(int(descriptor.wire_source_signed_curves[1]))
        if float(right_curve_length) <= float(collapse_tol) or float(right_span) <= float(collapse_tol)
        else None,
        abs(int(descriptor.wire_source_signed_curves[3]))
        if float(left_curve_length) <= float(collapse_tol) or float(left_span) <= float(collapse_tol)
        else None,
    ]
    collapsed_side_curve_tags = [
        int(curve_tag)
        for curve_tag in collapsed_side_curve_tags
        if curve_tag is not None
    ]
    return {
        "collapsed": bool(collapsed_side_curve_tags),
        "collapse_tol_m": float(collapse_tol),
        "connector_curve_length_m": float(connector_curve_length),
        "outer_curve_length_m": float(outer_curve_length),
        "right_curve_length_m": float(right_curve_length),
        "left_curve_length_m": float(left_curve_length),
        "right_span_m": float(right_span),
        "left_span_m": float(left_span),
        "collapsed_side_curve_tags": list(collapsed_side_curve_tags),
    }


def _collapsed_triangular_end_cap_source_surface_tags(
    descriptors: Iterable[ClosureRingPatchDesc],
    collapse_diagnostics: Iterable[dict[str, Any]],
) -> set[int]:
    descriptor_list = [descriptor for descriptor in descriptors]
    diagnostics_by_source_surface = {
        int(diagnostic["source_surface_tag"]): dict(diagnostic)
        for diagnostic in collapse_diagnostics
    }
    if len(descriptor_list) != 3:
        return set()
    source_surface_tags = [int(descriptor.source_surface_tag) for descriptor in descriptor_list]
    if len(set(source_surface_tags)) != 3:
        return set()
    if not all(
        bool(diagnostics_by_source_surface.get(int(source_surface_tag), {}).get("collapsed"))
        for source_surface_tag in source_surface_tags
    ):
        return set()
    return {int(source_surface_tag) for source_surface_tag in source_surface_tags}


def _get_or_make_rebuilt_point_tag(
    *,
    gmsh: Any,
    geo: Any,
    source_point_tag: int,
    point_registry: dict[int, int],
) -> int:
    existing_tag = point_registry.get(int(source_point_tag))
    if existing_tag is not None:
        return int(existing_tag)
    rebuilt_point_tag = int(geo.addPoint(*_point_xyz(gmsh, int(source_point_tag))))
    point_registry[int(source_point_tag)] = int(rebuilt_point_tag)
    return int(rebuilt_point_tag)


def _get_or_make_rebuilt_curve_tag(
    *,
    gmsh: Any,
    geo: Any,
    source_curve_tag: int,
    point_registry: dict[int, int],
    curve_registry: dict[int, int],
) -> tuple[int, int | None]:
    source_curve_tag = abs(int(source_curve_tag))
    existing_curve_tag = curve_registry.get(int(source_curve_tag))
    if existing_curve_tag is not None:
        return int(existing_curve_tag), _curve_mesh_point_count(gmsh, int(source_curve_tag))

    source_start_point_tag, source_end_point_tag = _curve_endpoint_tags(gmsh, int(source_curve_tag))
    start_xyz = _point_xyz(gmsh, int(source_start_point_tag))
    end_xyz = _point_xyz(gmsh, int(source_end_point_tag))
    curve_points = _curve_polyline_points(gmsh, int(source_curve_tag))
    if not curve_points:
        curve_points = [tuple(start_xyz), tuple(end_xyz)]
    if math.dist(tuple(curve_points[0]), tuple(start_xyz)) > math.dist(tuple(curve_points[-1]), tuple(start_xyz)):
        curve_points = list(reversed(curve_points))
    limited_curve_points = _limit_polyline_control_points(list(curve_points), max_points=8)
    if len(limited_curve_points) < 2:
        limited_curve_points = [tuple(start_xyz), tuple(end_xyz)]
    if math.dist(tuple(limited_curve_points[0]), tuple(start_xyz)) > 1.0e-10:
        limited_curve_points[0] = tuple(start_xyz)
    if math.dist(tuple(limited_curve_points[-1]), tuple(end_xyz)) > 1.0e-10:
        limited_curve_points[-1] = tuple(end_xyz)

    rebuilt_start_point_tag = _get_or_make_rebuilt_point_tag(
        gmsh=gmsh,
        geo=geo,
        source_point_tag=int(source_start_point_tag),
        point_registry=point_registry,
    )
    rebuilt_end_point_tag = _get_or_make_rebuilt_point_tag(
        gmsh=gmsh,
        geo=geo,
        source_point_tag=int(source_end_point_tag),
        point_registry=point_registry,
    )
    rebuilt_curve_tag, _rebuilt_point_tags = _add_polyline_curve(
        geo,
        list(limited_curve_points),
        start_point_tag=int(rebuilt_start_point_tag),
        end_point_tag=int(rebuilt_end_point_tag),
    )
    curve_registry[int(source_curve_tag)] = int(rebuilt_curve_tag)
    return int(rebuilt_curve_tag), _curve_mesh_point_count(gmsh, int(source_curve_tag))


def _signed_curve_loop_equivalent(
    lhs: Iterable[int],
    rhs: Iterable[int],
) -> bool:
    lhs_ordered = tuple(int(tag) for tag in lhs)
    rhs_ordered = tuple(int(tag) for tag in rhs)
    if len(lhs_ordered) != len(rhs_ordered):
        return False
    if not lhs_ordered and not rhs_ordered:
        return True
    for candidate in (rhs_ordered, _reverse_signed_curve_loop(rhs_ordered)):
        for start_index in range(len(candidate)):
            rotated = candidate[start_index:] + candidate[:start_index]
            if lhs_ordered == rotated:
                return True
    return False


def _build_required_closure_ring_patch_descriptors(
    *,
    gmsh: Any,
    closure_groups: list[dict[str, Any]],
    connector_closure_curve_tags: list[int],
) -> list[ClosureRingPatchDesc]:
    connector_curve_tag_set = {int(tag) for tag in connector_closure_curve_tags}
    descriptors: list[ClosureRingPatchDesc] = []
    for group in closure_groups:
        source_surface_tag = int(group["source_surface_tag"])
        source_signed_boundary_curves = _ordered_surface_boundary_curve_loop(gmsh, int(source_surface_tag))
        connector_signed_curves = [
            int(signed_curve_tag)
            for signed_curve_tag in source_signed_boundary_curves
            if abs(int(signed_curve_tag)) in connector_curve_tag_set
        ]
        if not connector_signed_curves:
            continue
        if len(connector_signed_curves) != 1:
            raise RuntimeError(
                f"source surface {int(source_surface_tag)} has ambiguous closure connector curves {connector_signed_curves}"
            )
        connector_signed_curve_tag = int(connector_signed_curves[0])
        connector_curve_tag = abs(int(connector_signed_curve_tag))
        legacy_surface_tag = int((group.get("side_surface_by_curve") or {})[int(connector_curve_tag)])
        wire_source_signed_curves = _canonicalize_closure_wire_loop(
            _ordered_surface_boundary_curve_loop(gmsh, int(legacy_surface_tag)),
            connector_signed_curve_tag=int(connector_signed_curve_tag),
        )
        descriptors.append(
            ClosureRingPatchDesc(
                source_surface_tag=int(source_surface_tag),
                legacy_surface_tag=int(legacy_surface_tag),
                connector_curve_tag=int(connector_curve_tag),
                source_signed_boundary_curves=tuple(int(tag) for tag in source_signed_boundary_curves),
                wire_source_signed_curves=tuple(int(tag) for tag in wire_source_signed_curves),
                semantic_corner_point_tags=_closure_wire_corner_point_tags(
                    gmsh,
                    tuple(int(tag) for tag in wire_source_signed_curves),
                ),
            )
        )
    return list(descriptors)


def _rebuild_closure_ring_surface_from_patch_descriptor(
    *,
    gmsh: Any,
    descriptor: ClosureRingPatchDesc,
    point_registry: dict[int, int],
    curve_registry: dict[int, int],
) -> dict[str, Any]:
    geo = gmsh.model.geo
    rebuilt_wire_signed_curves: list[int] = []
    source_curve_point_counts: dict[int, int | None] = {}
    for source_signed_curve_tag in descriptor.wire_source_signed_curves:
        rebuilt_curve_tag, source_curve_point_count = _get_or_make_rebuilt_curve_tag(
            gmsh=gmsh,
            geo=geo,
            source_curve_tag=abs(int(source_signed_curve_tag)),
            point_registry=point_registry,
            curve_registry=curve_registry,
        )
        rebuilt_wire_signed_curves.append(
            int(rebuilt_curve_tag)
            if int(source_signed_curve_tag) > 0
            else -int(rebuilt_curve_tag)
        )
        source_curve_point_counts[abs(int(source_signed_curve_tag))] = (
            int(source_curve_point_count)
            if source_curve_point_count is not None
            else None
        )

    curve_loop_tag = int(geo.addCurveLoop(list(rebuilt_wire_signed_curves)))
    rebuilt_surface_tag = int(geo.addSurfaceFilling([curve_loop_tag]))
    gmsh.model.geo.synchronize()

    rebuilt_corner_point_tags = tuple(
        int(point_registry[int(source_point_tag)])
        for source_point_tag in descriptor.semantic_corner_point_tags
    )
    for source_signed_curve_tag, rebuilt_signed_curve_tag in zip(
        descriptor.wire_source_signed_curves,
        rebuilt_wire_signed_curves,
        strict=True,
    ):
        point_count = source_curve_point_counts.get(abs(int(source_signed_curve_tag)))
        if point_count is not None and int(point_count) >= 2:
            gmsh.model.mesh.setTransfiniteCurve(abs(int(rebuilt_signed_curve_tag)), int(point_count))

    inner_count = source_curve_point_counts.get(abs(int(descriptor.wire_source_signed_curves[0])))
    right_count = source_curve_point_counts.get(abs(int(descriptor.wire_source_signed_curves[1])))
    outer_count = source_curve_point_counts.get(abs(int(descriptor.wire_source_signed_curves[2])))
    left_count = source_curve_point_counts.get(abs(int(descriptor.wire_source_signed_curves[3])))
    transfinite_surface_applied = False
    if (
        inner_count is not None
        and right_count is not None
        and outer_count is not None
        and left_count is not None
        and int(inner_count) == int(outer_count)
        and int(right_count) == int(left_count)
    ):
        gmsh.model.mesh.setTransfiniteSurface(
            int(rebuilt_surface_tag),
            cornerTags=list(rebuilt_corner_point_tags),
        )
        transfinite_surface_applied = True

    rebuilt_boundary_roundtrip = _ordered_surface_boundary_curve_loop(gmsh, int(rebuilt_surface_tag))
    wire_vertex_degrees = _curve_loop_vertex_degrees(gmsh, rebuilt_wire_signed_curves)
    return {
        "source_surface_tag": int(descriptor.source_surface_tag),
        "legacy_surface_tag": int(descriptor.legacy_surface_tag),
        "rebuilt_surface_tag": int(rebuilt_surface_tag),
        "curve_loop_tag": int(curve_loop_tag),
        "connector_curve_tag": int(descriptor.connector_curve_tag),
        "source_signed_boundary_curves": [int(tag) for tag in descriptor.source_signed_boundary_curves],
        "wire_source_signed_curves": [int(tag) for tag in descriptor.wire_source_signed_curves],
        "wire_source_curve_tags": [
            abs(int(tag)) for tag in descriptor.wire_source_signed_curves
        ],
        "rebuilt_wire_signed_curves": [int(tag) for tag in rebuilt_wire_signed_curves],
        "rebuilt_wire_curve_tags": [
            abs(int(tag)) for tag in rebuilt_wire_signed_curves
        ],
        "semantic_corner_point_tags": [int(tag) for tag in descriptor.semantic_corner_point_tags],
        "rebuilt_corner_point_tags": [int(tag) for tag in rebuilt_corner_point_tags],
        "source_curve_point_counts": {
            int(curve_tag): (
                int(point_count)
                if point_count is not None
                else None
            )
            for curve_tag, point_count in source_curve_point_counts.items()
        },
        "rebuilt_curve_tag_by_source_curve_tag": {
            abs(int(source_signed_curve_tag)): abs(int(rebuilt_signed_curve_tag))
            for source_signed_curve_tag, rebuilt_signed_curve_tag in zip(
                descriptor.wire_source_signed_curves,
                rebuilt_wire_signed_curves,
                strict=True,
            )
        },
        "duplicate_wire_curve_tags": _duplicate_curve_tags(rebuilt_wire_signed_curves),
        "wire_vertex_degrees": dict(wire_vertex_degrees),
        "boundary_roundtrip_ok": _signed_curve_loop_equivalent(
            rebuilt_wire_signed_curves,
            rebuilt_boundary_roundtrip,
        ),
        "construction": "oriented_patch_descriptor_exact_4edge_wire_surface_filling",
        "transfinite_surface_applied": bool(transfinite_surface_applied),
    }


def _rebuild_tip_truncation_closure_block(
    *,
    gmsh: Any,
    bl_source_surface_tags: list[int],
    extbl: list[tuple[int, int]],
    connector_band_surface_tags: list[int],
    connector_band_start_y_m: float | None,
) -> dict[str, Any] | None:
    closure_source_surface_tags = _select_tip_truncation_closure_source_surface_tags(
        gmsh=gmsh,
        bl_source_surface_tags=bl_source_surface_tags,
        connector_band_start_y_m=connector_band_start_y_m,
    )
    if not closure_source_surface_tags:
        return None

    extbl_groups = _extrude_boundary_layer_source_groups(
        gmsh=gmsh,
        source_surface_tags=bl_source_surface_tags,
        extbl=extbl,
    )
    group_by_source_surface = {
        int(group["source_surface_tag"]): dict(group)
        for group in extbl_groups
    }
    closure_groups = [
        group_by_source_surface[int(surface_tag)]
        for surface_tag in closure_source_surface_tags
        if int(surface_tag) in group_by_source_surface
    ]
    if len(closure_groups) < 2:
        return None

    connector_boundary_curve_tags: set[int] = set()
    for surface_tag in connector_band_surface_tags:
        connector_boundary_curve_tags.update(abs(int(tag)) for tag in _surface_boundary_curve_tags(gmsh, int(surface_tag)))

    initial_curve_occurrence_count: dict[int, int] = defaultdict(int)
    initial_side_surface_tags_by_curve: dict[int, int] = {}
    for group in closure_groups:
        for curve_tag, side_surface_tag in (group.get("side_surface_by_curve") or {}).items():
            initial_curve_occurrence_count[int(curve_tag)] += 1
            initial_side_surface_tags_by_curve.setdefault(int(curve_tag), int(side_surface_tag))

    initial_outer_boundary_curve_tags = [
        int(curve_tag)
        for curve_tag, count in initial_curve_occurrence_count.items()
        if int(count) == 1
    ]
    initial_connector_closure_curve_tags = [
        int(curve_tag)
        for curve_tag in initial_outer_boundary_curve_tags
        if int(curve_tag) in connector_boundary_curve_tags
    ]
    initial_legacy_closure_surface_tags = _unique_preserve_order(
        initial_side_surface_tags_by_curve[curve_tag]
        for curve_tag in initial_connector_closure_curve_tags
        if int(curve_tag) in initial_side_surface_tags_by_curve
    )
    closure_ring_patch_descriptors = _build_required_closure_ring_patch_descriptors(
        gmsh=gmsh,
        closure_groups=closure_groups,
        connector_closure_curve_tags=initial_connector_closure_curve_tags,
    )
    if len(closure_ring_patch_descriptors) != len(initial_legacy_closure_surface_tags):
        raise RuntimeError(
            "required closure ring descriptor count does not match legacy closure surface count"
        )

    collapsed_end_cap_patch_diagnostics: list[dict[str, Any]] = []
    for descriptor in closure_ring_patch_descriptors:
        collapse_diagnostics = dict(_closure_patch_collapse_diagnostics(gmsh, descriptor))
        collapse_diagnostics["source_surface_tag"] = int(descriptor.source_surface_tag)
        collapse_diagnostics["legacy_surface_tag"] = int(descriptor.legacy_surface_tag)
        collapse_diagnostics["connector_curve_tag"] = int(descriptor.connector_curve_tag)
        collapsed_end_cap_patch_diagnostics.append(collapse_diagnostics)
    collapsed_end_cap_source_surface_tags = _collapsed_triangular_end_cap_source_surface_tags(
        closure_ring_patch_descriptors,
        collapsed_end_cap_patch_diagnostics,
    )
    collapsed_end_cap_legacy_surface_tags = {
        int(descriptor.legacy_surface_tag)
        for descriptor in closure_ring_patch_descriptors
        if int(descriptor.source_surface_tag) in collapsed_end_cap_source_surface_tags
    }
    collapsed_end_cap_connector_curve_tags = {
        int(descriptor.connector_curve_tag)
        for descriptor in closure_ring_patch_descriptors
        if int(descriptor.source_surface_tag) in collapsed_end_cap_source_surface_tags
    }
    collapsed_end_cap_side_curve_tags = {
        int(curve_tag)
        for diagnostic in collapsed_end_cap_patch_diagnostics
        if int(diagnostic["source_surface_tag"]) in collapsed_end_cap_source_surface_tags
        for curve_tag in diagnostic.get("collapsed_side_curve_tags", [])
    }

    if collapsed_end_cap_source_surface_tags:
        closure_groups = [
            group
            for group in closure_groups
            if int(group["source_surface_tag"]) not in collapsed_end_cap_source_surface_tags
        ]
        closure_ring_patch_descriptors = [
            descriptor
            for descriptor in closure_ring_patch_descriptors
            if int(descriptor.source_surface_tag) not in collapsed_end_cap_source_surface_tags
        ]
        # If the remaining connector-side closure family collapses to end caps,
        # keep the original extBL termination instead of forcing a degenerated local rebuild.
        if len(closure_groups) < 2 or not closure_ring_patch_descriptors:
            return None

    curve_occurrence_count: dict[int, int] = defaultdict(int)
    side_surface_tags_by_curve: dict[int, int] = {}
    for group in closure_groups:
        for curve_tag, side_surface_tag in (group.get("side_surface_by_curve") or {}).items():
            curve_occurrence_count[int(curve_tag)] += 1
            side_surface_tags_by_curve.setdefault(int(curve_tag), int(side_surface_tag))

    outer_boundary_curve_tags = [
        int(curve_tag)
        for curve_tag, count in curve_occurrence_count.items()
        if int(count) == 1
    ]
    internal_transition_curve_tags = [
        int(curve_tag)
        for curve_tag, count in curve_occurrence_count.items()
        if int(count) > 1
    ]
    connector_closure_curve_tags = [
        int(curve_tag)
        for curve_tag in outer_boundary_curve_tags
        if int(curve_tag) in connector_boundary_curve_tags
    ]
    retained_outer_interface_curve_tags = [
        int(curve_tag)
        for curve_tag in outer_boundary_curve_tags
        if int(curve_tag) not in set(connector_closure_curve_tags)
    ]

    rebuilt_source_surface_tags = [int(group["source_surface_tag"]) for group in closure_groups]
    rebuilt_top_surface_tags = [int(group["top_surface_tag"]) for group in closure_groups]
    removed_volume_tags = [int(group["volume_tag"]) for group in closure_groups]
    root_side_surface_tags = _unique_preserve_order(
        side_surface_tag
        for group in closure_groups
        for side_surface_tag in (group.get("side_surface_by_curve") or {}).values()
        if _surface_lies_on_y_plane(gmsh, int(side_surface_tag), y_value=0.0, tol=1.0e-6)
    )
    removed_transition_surface_tags = _unique_preserve_order(
        side_surface_tags_by_curve[curve_tag]
        for curve_tag in internal_transition_curve_tags
        if int(curve_tag) in side_surface_tags_by_curve
    )
    legacy_closure_surface_tags = _unique_preserve_order(
        side_surface_tags_by_curve[curve_tag]
        for curve_tag in connector_closure_curve_tags
        if int(curve_tag) in side_surface_tags_by_curve
    )
    retained_outer_interface_surface_tags = _unique_preserve_order(
        side_surface_tags_by_curve[curve_tag]
        for curve_tag in retained_outer_interface_curve_tags
        if int(curve_tag) in side_surface_tags_by_curve
    )
    if len(closure_ring_patch_descriptors) != len(legacy_closure_surface_tags):
        raise RuntimeError(
            "required closure ring descriptor count does not match legacy closure surface count"
        )

    gmsh.model.geo.remove([(3, int(tag)) for tag in removed_volume_tags], recursive=False)
    surfaces_to_remove = [
        *list(removed_transition_surface_tags),
        *list(legacy_closure_surface_tags),
    ]
    if surfaces_to_remove:
        gmsh.model.geo.remove(
            [(2, int(tag)) for tag in surfaces_to_remove],
            recursive=False,
        )
    gmsh.model.geo.synchronize()

    closure_ring_rebuild_details: list[dict[str, Any]] = []
    rebuilt_closure_ring_surface_tags: list[int] = []
    legacy_to_rebuilt_surface_tags: dict[int, int] = {}
    point_registry: dict[int, int] = {}
    curve_registry: dict[int, int] = {}
    for descriptor in closure_ring_patch_descriptors:
        rebuild = _rebuild_closure_ring_surface_from_patch_descriptor(
            gmsh=gmsh,
            descriptor=descriptor,
            point_registry=point_registry,
            curve_registry=curve_registry,
        )
        rebuilt_tag = int(rebuild["rebuilt_surface_tag"])
        rebuilt_closure_ring_surface_tags.append(rebuilt_tag)
        legacy_to_rebuilt_surface_tags[int(descriptor.legacy_surface_tag)] = rebuilt_tag
        closure_ring_rebuild_details.append(rebuild)
    gmsh.model.geo.synchronize()

    surface_loop_surfaces = [
        *rebuilt_source_surface_tags,
        *rebuilt_top_surface_tags,
        *root_side_surface_tags,
        *retained_outer_interface_surface_tags,
        *rebuilt_closure_ring_surface_tags,
    ]
    closure_block_volume_tag = int(
        gmsh.model.geo.addVolume([gmsh.model.geo.addSurfaceLoop(surface_loop_surfaces)])
    )
    gmsh.model.geo.synchronize()

    return {
        "enabled": True,
        "source_surface_tags": list(rebuilt_source_surface_tags),
        "top_surface_tags": list(rebuilt_top_surface_tags),
        "root_side_surface_tags": list(root_side_surface_tags),
        "removed_volume_tags": list(removed_volume_tags),
        "removed_transition_surface_tags": list(removed_transition_surface_tags),
        "legacy_closure_surface_tags": list(legacy_closure_surface_tags),
        "closure_ring_surface_tags": list(rebuilt_closure_ring_surface_tags),
        "rebuilt_closure_ring_surface_tags": list(rebuilt_closure_ring_surface_tags),
        "legacy_to_rebuilt_surface_tags": dict(legacy_to_rebuilt_surface_tags),
        "closure_ring_rebuild_details": list(closure_ring_rebuild_details),
        "retained_outer_interface_surface_tags": list(retained_outer_interface_surface_tags),
        "connector_closure_curve_tags": list(connector_closure_curve_tags),
        "retained_outer_interface_curve_tags": list(retained_outer_interface_curve_tags),
        "collapsed_end_cap_source_surface_tags": sorted(int(tag) for tag in collapsed_end_cap_source_surface_tags),
        "collapsed_end_cap_legacy_surface_tags": sorted(int(tag) for tag in collapsed_end_cap_legacy_surface_tags),
        "collapsed_end_cap_connector_curve_tags": sorted(
            int(tag) for tag in collapsed_end_cap_connector_curve_tags
        ),
        "collapsed_end_cap_side_curve_tags": sorted(int(tag) for tag in collapsed_end_cap_side_curve_tags),
        "collapsed_end_cap_patch_diagnostics": list(collapsed_end_cap_patch_diagnostics),
        "construction_rule": "closure_family_to_oriented_patch_descriptor_to_exact_4edge_wire_surface_filling",
        "block_volume_tag": int(closure_block_volume_tag),
    }


def _surface_identity_signature(
    gmsh: Any,
    surface_tag: int,
) -> tuple[tuple[float, float, float, float, float, float], tuple[int, ...]]:
    bbox = tuple(round(float(value), 9) for value in gmsh.model.getBoundingBox(2, int(surface_tag)))
    boundary = gmsh.model.getBoundary(
        [(2, int(surface_tag))],
        combined=False,
        oriented=True,
        recursive=False,
    )
    curve_tags = tuple(
        sorted(abs(int(entity_tag)) for entity_dim, entity_tag in boundary if int(entity_dim) == 1)
    )
    return bbox, curve_tags


def _deduplicate_wall_surfaces(
    gmsh: Any,
    wall_surface_tags: list[int],
    *,
    tip_surface_tag: int | None,
) -> tuple[list[int], int | None, list[dict[str, Any]]]:
    occ = gmsh.model.occ
    signature_owner: dict[
        tuple[tuple[float, float, float, float, float, float], tuple[int, ...]],
        int,
    ] = {}
    duplicate_surface_groups: dict[int, list[int]] = {}
    for surface_tag in _unique_preserve_order(wall_surface_tags):
        signature = _surface_identity_signature(gmsh, int(surface_tag))
        owner = signature_owner.get(signature)
        if owner is None:
            signature_owner[signature] = int(surface_tag)
            continue
        duplicate_surface_groups.setdefault(int(owner), []).append(int(surface_tag))
    duplicate_surface_tags = [
        int(tag)
        for duplicate_tags in duplicate_surface_groups.values()
        for tag in duplicate_tags
    ]
    if duplicate_surface_tags:
        occ.remove([(2, int(tag)) for tag in duplicate_surface_tags], recursive=False)
        occ.synchronize()
    surviving_surface_tags = {
        int(tag)
        for dim, tag in gmsh.model.getEntities(2)
        if int(dim) == 2
    }
    kept_surface_tags = [
        int(tag)
        for tag in _unique_preserve_order(wall_surface_tags)
        if int(tag) in surviving_surface_tags and int(tag) not in set(duplicate_surface_tags)
    ]
    duplicate_surface_reports = [
        {"kept": int(owner), "removed": [int(tag) for tag in removed_tags]}
        for owner, removed_tags in duplicate_surface_groups.items()
    ]
    updated_tip_surface_tag = int(tip_surface_tag) if tip_surface_tag in surviving_surface_tags else None
    return kept_surface_tags, updated_tip_surface_tag, duplicate_surface_reports


def _curve_boundary_point_tags(
    gmsh: Any,
    curve_tag: int,
) -> tuple[int, int]:
    boundary = gmsh.model.getBoundary(
        [(1, int(curve_tag))],
        combined=False,
        oriented=True,
        recursive=False,
    )
    point_tags = [
        abs(int(entity_tag))
        for entity_dim, entity_tag in boundary
        if int(entity_dim) == 0
    ]
    if len(point_tags) != 2:
        raise RuntimeError(f"curve {curve_tag} does not expose exactly two endpoints")
    return int(point_tags[0]), int(point_tags[1])


def _curve_endpoint_tags(gmsh: Any, curve_tag: int) -> tuple[int, int]:
    first_point_tag, second_point_tag = _curve_boundary_point_tags(gmsh, int(curve_tag))
    sampled_points = _curve_polyline_points(gmsh, int(curve_tag))
    if len(sampled_points) < 2:
        return int(first_point_tag), int(second_point_tag)
    first_point_xyz = _point_xyz(gmsh, int(first_point_tag))
    second_point_xyz = _point_xyz(gmsh, int(second_point_tag))
    forward_cost = math.dist(sampled_points[0], first_point_xyz) + math.dist(sampled_points[-1], second_point_xyz)
    reverse_cost = math.dist(sampled_points[0], second_point_xyz) + math.dist(sampled_points[-1], first_point_xyz)
    if reverse_cost < forward_cost:
        return int(second_point_tag), int(first_point_tag)
    return int(first_point_tag), int(second_point_tag)


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
        if y_span >= max(0.10 * chord_m, 0.8 * max(x_span, z_span)):
            gmsh.model.mesh.setTransfiniteCurve(tag, half_span_stations)
        elif x_span >= 0.2 * chord_m or z_span >= 0.05 * chord_m:
            gmsh.model.mesh.setTransfiniteCurve(tag, airfoil_curve_points)
        else:
            gmsh.model.mesh.setTransfiniteCurve(tag, te_curve_points)
    for dim, tag in gmsh.model.getEntities(2):
        if dim != 2:
            continue
        try:
            boundary = gmsh.model.getBoundary([(2, int(tag))], combined=False, oriented=True, recursive=False)
            curve_count = len({abs(int(entity_tag)) for entity_dim, entity_tag in boundary if int(entity_dim) == 1})
            if curve_count in {3, 4}:
                gmsh.model.mesh.setTransfiniteSurface(tag)
        except Exception:
            continue


def _remove_mesh_constraints_from_surfaces(
    gmsh: Any,
    surface_tags: Iterable[int],
) -> list[int]:
    surface_dimtags = [(2, int(tag)) for tag in _unique_preserve_order(surface_tags)]
    if not surface_dimtags:
        return []
    gmsh.model.mesh.removeConstraints(surface_dimtags)
    return [int(tag) for _, tag in surface_dimtags]


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
    boundary = gmsh.model.getBoundary([(2, int(surface_tag))], combined=False, oriented=True, recursive=False)
    point_tags: list[int] = []
    for dim, curve_tag in boundary:
        if dim != 1:
            continue
        point_tags.extend(
            abs(int(point_tag))
            for _, point_tag in gmsh.model.getBoundary(
                [(1, abs(int(curve_tag)))],
                combined=False,
                oriented=True,
                recursive=False,
            )
        )
    if not point_tags:
        return False
    return all(abs(_point_xyz(gmsh, point_tag)[1] - y_value) <= tol for point_tag in point_tags)


def _surface_boundary_y_range(gmsh: Any, surface_tag: int) -> tuple[float, float] | None:
    boundary = gmsh.model.getBoundary([(2, int(surface_tag))], combined=False, oriented=True, recursive=False)
    point_tags: list[int] = []
    for dim, curve_tag in boundary:
        if dim != 1:
            continue
        point_tags.extend(
            abs(int(point_tag))
            for curve_dim, point_tag in gmsh.model.getBoundary(
                [(1, abs(int(curve_tag)))],
                combined=False,
                oriented=True,
                recursive=False,
            )
            if int(curve_dim) == 0
        )
    if not point_tags:
        return None
    y_values = [_point_xyz(gmsh, point_tag)[1] for point_tag in set(point_tags)]
    if not y_values:
        return None
    return float(min(y_values)), float(max(y_values))


def _collect_root_side_surface_tags(gmsh: Any, extbl: list[tuple[int, int]]) -> list[int]:
    return _collect_extbl_surfaces_on_y_plane(gmsh, extbl, y_value=0.0)


def _collect_extbl_surfaces_on_y_plane(
    gmsh: Any,
    extbl: list[tuple[int, int]],
    *,
    y_value: float,
) -> list[int]:
    matching_surfaces: list[int] = []
    existing_surface_tags = {
        int(tag)
        for dim, tag in gmsh.model.getEntities(2)
        if int(dim) == 2
    }
    for dim, tag in extbl:
        if int(dim) != 2:
            continue
        surface_tag = int(tag)
        if surface_tag in matching_surfaces:
            continue
        if surface_tag not in existing_surface_tags:
            continue
        if _surface_lies_on_y_plane(gmsh, surface_tag, y_value=float(y_value), tol=1.0e-6):
            matching_surfaces.append(surface_tag)
    return matching_surfaces


def _collect_extbl_surfaces_in_y_band(
    gmsh: Any,
    extbl: list[tuple[int, int]],
    *,
    y_min: float,
    y_max: float,
) -> list[int]:
    matching_surfaces: list[int] = []
    existing_surface_tags = {
        int(tag)
        for dim, tag in gmsh.model.getEntities(2)
        if int(dim) == 2
    }
    tol = 1.0e-6
    for dim, tag in extbl:
        if int(dim) != 2:
            continue
        surface_tag = int(tag)
        if surface_tag in matching_surfaces or surface_tag not in existing_surface_tags:
            continue
        try:
            y_range = _surface_boundary_y_range(gmsh, surface_tag)
        except Exception:
            y_range = None
        if y_range is None:
            try:
                _x_min, bbox_y_min, _z_min, _x_max, bbox_y_max, _z_max = gmsh.model.getBoundingBox(2, surface_tag)
                y_range = (float(bbox_y_min), float(bbox_y_max))
            except Exception:
                continue
        bbox_y_min, bbox_y_max = y_range
        if bbox_y_max >= float(y_min) - tol and bbox_y_min <= float(y_max) + tol:
            matching_surfaces.append(surface_tag)
    return matching_surfaces


def _tip_truncation_cleanup_buffer_m(
    *,
    sections: list[dict[str, Any]],
    start_y_m: float,
    protection: dict[str, Any],
) -> float:
    local_section = _real_wing_local_clearance_at_spanwise_x_rel(
        sections=sections,
        y_value=float(start_y_m),
        x_rel=0.5,
    )
    local_chord_m = max(float(local_section["local_chord_m"]), 1.0e-9)
    return float(protection.get("tip_truncation_inboard_buffer_chords", 0.0) or 0.0) * local_chord_m


def _tip_truncation_connector_band_start_y_m(
    *,
    sections: list[dict[str, Any]],
    start_y_m: float | None,
    protection: dict[str, Any],
) -> float | None:
    if start_y_m is None or len(sections) < 2:
        return None
    band_chords = float(protection.get("tip_truncation_connector_band_chords", 0.0) or 0.0)
    if band_chords <= 0.0:
        return None
    lower_y_candidates = sorted(
        float(section["y_le"])
        for section in sections
        if float(section["y_le"]) < float(start_y_m) - 1.0e-9
    )
    if not lower_y_candidates:
        return None
    lower_y = lower_y_candidates[-1]
    local_section = _real_wing_local_clearance_at_spanwise_x_rel(
        sections=sections,
        y_value=float(start_y_m),
        x_rel=0.5,
    )
    local_chord_m = max(float(local_section["local_chord_m"]), 1.0e-9)
    band_depth_m = min(float(start_y_m) - lower_y, band_chords * local_chord_m)
    if band_depth_m <= 1.0e-9:
        return None
    connector_band_start_y = max(lower_y, float(start_y_m) - band_depth_m)
    if connector_band_start_y >= float(start_y_m) - 1.0e-9:
        return None
    return float(connector_band_start_y)


def _cleanup_surface_mesh(
    gmsh: Any,
    surface_tags: list[int],
) -> dict[str, Any]:
    cleanup: dict[str, Any] = {
        "surface_tags": [int(tag) for tag in surface_tags],
        "removed_degenerate_element_count": 0,
        "removed_cross_surface_duplicate_element_count": 0,
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
    duplicate_element_tags_by_surface: dict[int, list[int]] = defaultdict(list)
    signature_owner: dict[tuple[int, ...], tuple[int, int]] = {}
    for surface_tag in surface_tags:
        element_types, element_tags_by_type, node_tags_by_type = gmsh.model.mesh.getElements(2, int(surface_tag))
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
                signature = tuple(sorted(int(node) for node in node_tags[start:stop]))
                owner = signature_owner.get(signature)
                if owner is None:
                    signature_owner[signature] = (int(surface_tag), int(element_tag))
                    continue
                duplicate_element_tags_by_surface[int(surface_tag)].append(int(element_tag))
                cleanup["removed_cross_surface_duplicate_element_count"] += 1
                if len(cleanup["removed_degenerate_elements_sample"]) < int(
                    cleanup["removed_degenerate_elements_sample_limit"]
                ):
                    cleanup["removed_degenerate_elements_sample"].append(
                        {
                            "surface_tag": int(surface_tag),
                            "element_type": int(element_type),
                            "element_tag": int(element_tag),
                            "node_tags": list(signature),
                            "duplicate_of_surface_tag": int(owner[0]),
                            "duplicate_of_element_tag": int(owner[1]),
                        }
                    )
    for surface_tag, duplicate_element_tags in duplicate_element_tags_by_surface.items():
        gmsh.model.mesh.removeElements(2, int(surface_tag), duplicate_element_tags)
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
        oriented=True,
        recursive=False,
    )
    raw_curve_tags = [abs(int(curve_tag)) for dim, curve_tag in hole_boundary if dim == 1]
    if len(raw_curve_tags) > 3:
        root_plane_curve_tags: list[int] = []
        for curve_tag in raw_curve_tags:
            try:
                start_tag, end_tag = _curve_endpoint_tags(gmsh, int(curve_tag))
                start_xyz = _point_xyz(gmsh, start_tag)
                end_xyz = _point_xyz(gmsh, end_tag)
            except Exception:
                continue
            if abs(start_xyz[1]) <= 1.0e-6 and abs(end_xyz[1]) <= 1.0e-6:
                root_plane_curve_tags.append(int(curve_tag))
        if len(root_plane_curve_tags) >= 3:
            raw_curve_tags = root_plane_curve_tags
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
    topology_compiler_gate: str = TOPOLOGY_COMPILER_GATE_OFF,
    bl_candidate_apply_gate: str = BL_CANDIDATE_APPLY_GATE_OFF,
) -> dict[str, Any]:
    route_started = time.perf_counter()
    out_dir = Path(out_dir)
    mesh_dir = out_dir / "artifacts" / "mesh"
    su2_dir = out_dir / "artifacts" / "su2"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    su2_dir.mkdir(parents=True, exist_ok=True)
    topology_compiler_gate = _normalize_topology_compiler_gate(topology_compiler_gate)
    bl_candidate_apply_gate = _normalize_bl_candidate_apply_gate(bl_candidate_apply_gate)
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
    protection_config = dict(spec.get("real_wing_bl_protection", {}))
    tip_truncation_summary: dict[str, Any] | None = None
    restart_overrides: dict[str, Any] | None = None
    real_wing_geometry: dict[str, Any] | None = None
    if geometry_shape_mode == DEFAULT_REAL_MAIN_WING_SHAPE_MODE:
        preloaded_real_wing_geometry = geometry.get("_preloaded_real_main_wing_geometry")
        if isinstance(preloaded_real_wing_geometry, dict):
            real_wing_geometry = copy.deepcopy(preloaded_real_wing_geometry)
        else:
            real_wing_geometry = _resolve_real_main_wing_geometry(
                geometry=geometry,
                artifact_dir=mesh_dir,
            )
        source_section_count = len(real_wing_geometry["sections"])
        forced_tip_truncation_start_y = protection_config.get("forced_tip_truncation_start_y_m")
        if forced_tip_truncation_start_y is not None:
            tip_truncation_summary = {
                "enabled": True,
                "start_y_m": float(forced_tip_truncation_start_y),
                "forced_restart": True,
            }
        else:
            tip_interference_analysis = _analyze_real_wing_tip_bl_interference(
                sections=list(real_wing_geometry["sections"]),
                protection=protection_config,
                base_total_thickness_m=boundary_layer_total_thickness,
                half_span_m=float(real_wing_geometry["overall_bounds"]["y_max"]),
            )
            tip_truncation_summary = dict(tip_interference_analysis.get("tip_truncation") or {})
        if tip_truncation_summary.get("enabled"):
            augmented_sections, truncation_geometry = _augment_real_wing_sections_for_tip_truncation(
                sections=list(real_wing_geometry["sections"]),
                start_y_m=tip_truncation_summary.get("start_y_m"),
                protection=protection_config,
            )
            real_wing_geometry["sections"] = augmented_sections
            real_wing_geometry["section_profiles"] = [
                _global_section_profile_points(section) for section in augmented_sections
            ]
            real_wing_geometry["section_bounds"] = [
                _section_bounds(points) for points in real_wing_geometry["section_profiles"]
            ]
            tip_truncation_summary.update(truncation_geometry)
        geometry["source_path"] = real_wing_geometry["source_path"]
        geometry["component"] = real_wing_geometry["component"]
        geometry["airfoil_name"] = f"{real_wing_geometry['surface_name']} extracted sections"
        geometry["real_main_wing_sections_path"] = real_wing_geometry["artifact_path"]
        geometry["source_section_count"] = int(source_section_count)
        geometry["meshing_section_count"] = int(len(real_wing_geometry["sections"]))
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
    tip_termination_surface_tags: list[int] = []
    quality_metrics: dict[str, Any] = {}
    surface_element_count = 0
    wall_face_count = 0
    bl_active_wall_face_count = 0
    bl_excluded_wall_face_count = 0
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
    pre_3d_bl_clearance: dict[str, Any] | None = None
    bl_excluded_surface_tags: list[int] = []
    tip_truncation_seam_surface_tags: list[int] = []
    tip_truncation_local_surface_tags: list[int] = []
    tip_truncation_connector_band_surface_tags: list[int] = []
    tip_truncation_closure_block_summary: dict[str, Any] | None = None
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
            if loft_info.get("tip_surface_tag") is not None:
                geometry["tip_surface_tag"] = int(loft_info["tip_surface_tag"])
            geometry["duplicate_wall_surface_groups"] = list(loft_info.get("duplicate_surface_groups") or [])

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
            auto_exclude_tip_cap = bool(protection_config.get("exclude_tip_cap_from_bl", True))
            if tip_truncation_summary and tip_truncation_summary.get("enabled"):
                auto_exclude_tip_cap = bool(
                    protection_config.get("tip_truncation_auto_exclude_tip_cap", True)
                ) or auto_exclude_tip_cap
                tip_truncation_surface_tags = _select_tip_truncation_surface_tags(
                    gmsh=gmsh,
                    wall_surface_tags=wall_surface_tags,
                    start_y_m=float(tip_truncation_summary["start_y_m"]),
                    tip_surface_tag=int(tip_surface_tag) if tip_surface_tag is not None else None,
                    include_tip_cap=bool(
                        protection_config.get("tip_truncation_auto_exclude_tip_cap", True)
                    ),
                )
                tip_truncation_connector_band_surface_tags = (
                    _select_tip_truncation_connector_band_surface_tags(
                        gmsh=gmsh,
                        wall_surface_tags=wall_surface_tags,
                        band_start_y_m=tip_truncation_summary.get("connector_band_start_y_m"),
                        start_y_m=float(tip_truncation_summary["start_y_m"]),
                        tip_surface_tag=int(tip_surface_tag) if tip_surface_tag is not None else None,
                    )
                )
                tip_truncation_summary["surface_tags"] = _unique_preserve_order(
                    [*tip_truncation_surface_tags, *tip_truncation_connector_band_surface_tags]
                )
                tip_truncation_summary["connector_band_surface_tags"] = list(
                    tip_truncation_connector_band_surface_tags
                )
            else:
                tip_truncation_surface_tags = []
                tip_truncation_connector_band_surface_tags = []
            if auto_exclude_tip_cap and tip_surface_tag is not None:
                tip_truncation_surface_tags = _unique_preserve_order(
                    [*tip_truncation_surface_tags, int(tip_surface_tag)]
                )
            relaxed_tip_surface_tags = _remove_mesh_constraints_from_surfaces(
                gmsh,
                tip_truncation_surface_tags,
            )
            if tip_truncation_summary is not None:
                tip_truncation_summary["relaxed_surface_mesh_constraints"] = list(
                    relaxed_tip_surface_tags
                )
            tip_truncation_bl_excluded_surface_tags = _unique_preserve_order(
                [*tip_truncation_surface_tags, *tip_truncation_connector_band_surface_tags]
            )
            bl_source_surface_tags = [
                int(tag)
                for tag in wall_surface_tags
                if int(tag) not in set(tip_truncation_bl_excluded_surface_tags)
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
            if tip_truncation_summary and tip_truncation_summary.get("enabled") and bl_protection_summary is not None:
                triggered_span = (bl_protection_summary.get("triggered_span_y_range_m") or {}).get("min")
                current_start = float(tip_truncation_summary.get("start_y_m") or 0.0)
                restart_count = int(protection_config.get("_tip_truncation_restart_count", 0) or 0)
                connector_band_locked = tip_truncation_summary.get("connector_band_start_y_m") is not None
                if (
                    not connector_band_locked
                    and
                    triggered_span is not None
                    and float(triggered_span) < current_start - 1.0e-4
                    and restart_count < 3
                ):
                    restart_overrides = copy.deepcopy(overrides or {})
                    restart_protection = dict(restart_overrides.get("real_wing_bl_protection") or {})
                    restart_protection["forced_tip_truncation_start_y_m"] = float(triggered_span)
                    restart_protection["_tip_truncation_restart_count"] = restart_count + 1
                    restart_overrides["real_wing_bl_protection"] = restart_protection
                    raise RuntimeError("tip_truncation_restart_requested")
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
                geometry.get("tip_surface_tag") in set(bl_excluded_surface_tags)
            )
            bl_protection_summary["excluded_surface_tags_from_bl"] = list(bl_excluded_surface_tags)
            if tip_truncation_summary is not None:
                bl_protection_summary["tip_truncation"] = dict(tip_truncation_summary)
                bl_protection_summary["tip_termination_surface_tags"] = list(tip_termination_surface_tags)
                bl_protection_summary["tip_truncation_connector_band_surface_tags"] = list(
                    tip_truncation_connector_band_surface_tags
                )
                if tip_truncation_summary.get("enabled"):
                    bl_protection_summary["intervention_mode"] = "scaling_and_truncation"
        for index in range(1, len(extbl)):
            if extbl[index][0] == 3:
                bl_volume_tags.append(int(extbl[index][1]))
                bl_top_surface_tags.append(int(extbl[index - 1][1]))
        gmsh.model.geo.synchronize()
        if tip_truncation_summary and tip_truncation_summary.get("enabled"):
            tip_truncation_closure_block_summary = _rebuild_tip_truncation_closure_block(
                gmsh=gmsh,
                bl_source_surface_tags=bl_source_surface_tags,
                extbl=extbl,
                connector_band_surface_tags=tip_truncation_connector_band_surface_tags,
                connector_band_start_y_m=tip_truncation_summary.get("connector_band_start_y_m"),
            )
            if tip_truncation_closure_block_summary is not None:
                removed_volume_tags = set(
                    int(tag)
                    for tag in tip_truncation_closure_block_summary.get("removed_volume_tags", [])
                )
                closure_block_volume_tag = tip_truncation_closure_block_summary.get("block_volume_tag")
                bl_volume_tags = [
                    int(tag)
                    for tag in bl_volume_tags
                    if int(tag) not in removed_volume_tags
                ]
                if closure_block_volume_tag is not None:
                    bl_volume_tags.append(int(closure_block_volume_tag))
                bl_volume_tags = _unique_preserve_order(bl_volume_tags)
                tip_termination_surface_tags = list(
                    tip_truncation_closure_block_summary.get("rebuilt_closure_ring_surface_tags") or []
                )
                tip_truncation_seam_surface_tags = list(tip_termination_surface_tags)
                tip_truncation_local_surface_tags = list(tip_termination_surface_tags)
                if bl_protection_summary is not None:
                    bl_protection_summary["tip_truncation_closure_block"] = dict(
                        tip_truncation_closure_block_summary
                    )
                    bl_protection_summary["tip_termination_surface_tags"] = list(
                        tip_termination_surface_tags
                    )
                    bl_protection_summary["tip_truncation_seam_surface_tags"] = list(
                        tip_truncation_seam_surface_tags
                    )
                    bl_protection_summary["tip_truncation_local_surface_tags"] = list(
                        tip_truncation_local_surface_tags
                    )
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
                oriented=True,
                recursive=False,
            )
            hole_curves = _order_curve_loop(
                gmsh,
                [abs(int(curve_tag)) for dim, curve_tag in hole_boundary if dim == 1],
            )
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
        if tip_truncation_summary and tip_truncation_summary.get("enabled"):
            if tip_truncation_closure_block_summary is None:
                tip_termination_surface_tags = _collect_extbl_surfaces_on_y_plane(
                    gmsh,
                    extbl,
                    y_value=float(tip_truncation_summary["start_y_m"]),
                )
                seam_cleanup_buffer_m = _tip_truncation_cleanup_buffer_m(
                    sections=list(real_wing_geometry["sections"]),
                    start_y_m=float(tip_truncation_summary["start_y_m"]),
                    protection=protection_config,
                )
                tip_truncation_seam_surface_tags = _collect_extbl_surfaces_in_y_band(
                    gmsh,
                    extbl,
                    y_min=float(tip_truncation_summary["start_y_m"]) - seam_cleanup_buffer_m,
                    y_max=float(tip_truncation_summary["start_y_m"]),
                )
                tip_truncation_local_surface_tags = _unique_preserve_order(
                    [*tip_truncation_surface_tags, *tip_truncation_seam_surface_tags]
                )
            else:
                seam_cleanup_buffer_m = _tip_truncation_cleanup_buffer_m(
                    sections=list(real_wing_geometry["sections"]),
                    start_y_m=float(tip_truncation_summary["start_y_m"]),
                    protection=protection_config,
                )
            if bl_protection_summary is not None:
                bl_protection_summary["tip_termination_surface_tags"] = list(tip_termination_surface_tags)
                bl_protection_summary["tip_truncation_seam_surface_tags"] = list(
                    tip_truncation_seam_surface_tags
                )
                bl_protection_summary["tip_truncation_local_surface_tags"] = list(
                    tip_truncation_local_surface_tags
                )
                bl_protection_summary["tip_truncation_cleanup_buffer_m"] = float(seam_cleanup_buffer_m)
        fluid_volume_tag = gmsh.model.geo.addVolume(
            [
                gmsh.model.geo.addSurfaceLoop(
                    _unique_preserve_order(
                        bl_top_surface_tags
                        + tip_termination_surface_tags
                        + bl_excluded_surface_tags
                        + symmetry_surface_tags
                        + farfield_surface_tags
                    )
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
            topology_checks["root_closure"]["surface_mesh_cleanup"] = _cleanup_surface_mesh(
                gmsh,
                list(root_side_surface_tags),
            )
            if tip_truncation_closure_block_summary is None:
                if tip_termination_surface_tags:
                    for surface_tag in tip_termination_surface_tags:
                        gmsh.model.mesh.splitQuadrangles(1.0, int(surface_tag))
                    tip_termination_cleanup = _cleanup_surface_mesh(
                        gmsh,
                        list(tip_termination_surface_tags),
                    )
                    if bl_protection_summary is not None:
                        bl_protection_summary["tip_termination_surface_mesh_cleanup"] = tip_termination_cleanup
                if tip_truncation_local_surface_tags:
                    for surface_tag in tip_truncation_local_surface_tags:
                        gmsh.model.mesh.splitQuadrangles(1.0, int(surface_tag))
                    tip_truncation_seam_cleanup = _cleanup_surface_mesh(
                        gmsh,
                        list(tip_truncation_local_surface_tags),
                    )
                    if bl_protection_summary is not None:
                        bl_protection_summary["tip_truncation_seam_surface_mesh_cleanup"] = (
                            tip_truncation_seam_cleanup
                        )
            else:
                closure_block_cleanup_surface_tags = _unique_preserve_order(
                    [
                        *list(
                            tip_truncation_closure_block_summary.get("retained_outer_interface_surface_tags") or []
                        ),
                        *list(
                            tip_truncation_closure_block_summary.get("rebuilt_closure_ring_surface_tags") or []
                        ),
                    ]
                )
                if closure_block_cleanup_surface_tags:
                    for surface_tag in closure_block_cleanup_surface_tags:
                        gmsh.model.mesh.splitQuadrangles(1.0, int(surface_tag))
                    closure_block_surface_cleanup = _cleanup_surface_mesh(
                        gmsh,
                        list(closure_block_cleanup_surface_tags),
                    )
                    if bl_protection_summary is not None:
                        bl_protection_summary["tip_truncation_closure_block_surface_mesh_cleanup"] = (
                            closure_block_surface_cleanup
                        )
            if tip_truncation_summary and tip_truncation_summary.get("enabled"):
                facet_overlap_angle_tol_deg = float(
                    protection_config.get("tip_truncation_facet_overlap_angle_tol_deg", 0.001)
                )
                gmsh.option.setNumber(
                    "Mesh.AngleToleranceFacetOverlap",
                    facet_overlap_angle_tol_deg,
                )
                if bl_protection_summary is not None:
                    bl_protection_summary["tip_truncation_facet_overlap_angle_tol_deg"] = (
                        facet_overlap_angle_tol_deg
                    )
            pre_3d_bl_clearance = _analyze_real_wing_tip_bl_interference(
                sections=list(real_wing_geometry["sections"]),
                protection=protection_config,
                base_total_thickness_m=boundary_layer_total_thickness,
                half_span_m=half_span_m,
                truncation_start_y_m=(
                    float(tip_truncation_summary["start_y_m"])
                    if tip_truncation_summary and tip_truncation_summary.get("enabled")
                    else None
                ),
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
        if bl_source_surface_tags:
            bl_active_wall_face_count, _ = _count_elements_for_entities(gmsh, 2, bl_source_surface_tags)
        if bl_excluded_surface_tags:
            bl_excluded_wall_face_count, _ = _count_elements_for_entities(gmsh, 2, bl_excluded_surface_tags)
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

    if restart_overrides is not None:
        return run_shell_v4_half_wing_bl_mesh_macsafe(
            out_dir=out_dir,
            study_level=study_level,
            run_su2=run_su2,
            allow_swap_risk=allow_swap_risk,
            overrides=restart_overrides,
            topology_compiler_gate=topology_compiler_gate,
            bl_candidate_apply_gate=bl_candidate_apply_gate,
        )

    y_plus_estimate = estimate_first_cell_yplus_range(
        velocity_mps=float(flow["velocity_mps"]),
        density_kgpm3=float(flow["density_kgpm3"]),
        dynamic_viscosity_pas=float(flow["dynamic_viscosity_pas"]),
        ref_length_m=float(reference_values["ref_length"]),
        first_layer_height_m=float(bl_spec["first_layer_height_m"]),
    )
    bl_reference_wall_face_count = bl_active_wall_face_count if bl_active_wall_face_count > 0 else wall_face_count
    average_achieved_layers = float(bl_cell_count / bl_reference_wall_face_count) if bl_reference_wall_face_count > 0 else 0.0
    achieved_layers = max(0, int(round(average_achieved_layers)))
    collapse_rate = 1.0
    if bl_reference_wall_face_count > 0 and int(bl_spec["layers"]) > 0:
        expected_bl_cells = bl_reference_wall_face_count * int(bl_spec["layers"])
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
    engineering_warnings: list[str] = []
    if boundary_layer_total_thickness < 0.035 or boundary_layer_total_thickness > 0.05:
        engineering_warnings.append("boundary_layer_total_thickness_outside_recommended_band")

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
        "bl_active_wall_face_count": int(bl_active_wall_face_count),
        "bl_excluded_wall_face_count": int(bl_excluded_wall_face_count),
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
            "bl_active_wall_face_count": int(bl_active_wall_face_count),
            "bl_excluded_wall_face_count": int(bl_excluded_wall_face_count),
            "target_total_thickness_m": float(boundary_layer_total_thickness),
            "collapse_rate": float(collapse_rate),
            "pass": collapse_rate <= float(cell_budget["max_bl_collapse_rate"]),
            "estimated_first_cell_yplus_range": {
                "min": y_plus_estimate["y_plus_min"],
                "max": y_plus_estimate["y_plus_max"],
            },
            "local_protection": bl_protection_summary,
            "pre_3d_clearance": pre_3d_bl_clearance,
        },
        "mesh_quality": quality_metrics,
        "memory_estimate": memory_estimate,
        "solver": solver_result,
        "engineering_warnings": engineering_warnings,
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
    if engineering_warnings:
        result["notes"].extend(engineering_warnings)

    result["case_summary"] = {
        "total_cells": int(total_cells),
        "total_nodes": int(total_nodes),
        "mesh_algorithm3d": int(mesh_algorithm3d),
        "surface_face_count": int(surface_element_count),
        "wall_face_count": int(wall_face_count),
        "bl_active_wall_face_count": int(bl_active_wall_face_count),
        "bl_excluded_wall_face_count": int(bl_excluded_wall_face_count),
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
        "pre_3d_bl_clearance": pre_3d_bl_clearance,
        "comparability_classification": result_class,
        "reference_values_used": reference_values,
        "route_note": interpretation_note,
    }
    if geometry_shape_mode == DEFAULT_REAL_MAIN_WING_SHAPE_MODE:
        result["notes"].append(
            "Geometry used provider-extracted real main wing sections from the configured .vsp3 source instead of the NACA0012 surrogate."
        )
        if tip_truncation_summary and tip_truncation_summary.get("enabled"):
            result["notes"].append(
                f"Tip-near explicit BL termination was auto-armed from y={float(tip_truncation_summary['start_y_m']):.4f} m outward to protect upper/lower BL-top clearance."
            )
    if topology_compiler_gate == TOPOLOGY_COMPILER_GATE_PLAN_ONLY:
        if geometry_shape_mode != DEFAULT_REAL_MAIN_WING_SHAPE_MODE or real_wing_geometry is None:
            result["topology_compiler"] = {
                "gate": TOPOLOGY_COMPILER_GATE_PLAN_ONLY,
                "status": "unsupported",
                "reason": "shell_v4 topology compiler plan-only gate currently supports real-wing prelaunch only",
            }
        else:
            try:
                result["topology_compiler"] = _run_shell_v4_topology_compiler_plan_only(
                    out_dir=out_dir,
                    geometry=geometry,
                    real_wing_geometry=real_wing_geometry,
                    boundary_layer=bl_spec,
                    real_wing_bl_protection=protection_config,
                )
            except Exception as exc:
                result["topology_compiler"] = {
                    "gate": TOPOLOGY_COMPILER_GATE_PLAN_ONLY,
                    "status": "failed",
                    "error": str(exc),
                }
                result["notes"].append(
                    "Topology compiler plan-only gate failed after the runtime path completed; runtime outputs are unchanged."
                )

    if bl_candidate_apply_gate != BL_CANDIDATE_APPLY_GATE_OFF:
        if geometry_shape_mode != DEFAULT_REAL_MAIN_WING_SHAPE_MODE or real_wing_geometry is None:
            if bl_candidate_apply_gate == BL_CANDIDATE_APPLY_GATE_STAGED_TRANSITION_GUARD_FOCUSED:
                result["bl_candidate_apply"] = _write_rejected_staged_transition_apply_comparison(
                    artifact_dir=out_dir
                    / "artifacts"
                    / "topology_compiler"
                    / "staged_transition_apply",
                    apply_gate=bl_candidate_apply_gate,
                    reject_reason="real_wing_focused_validation_required",
                )
            else:
                result["bl_candidate_apply"] = _write_rejected_bl_candidate_apply_comparison(
                    artifact_dir=out_dir / "artifacts" / "topology_compiler" / "bl_candidate_apply",
                    apply_gate=bl_candidate_apply_gate,
                    reject_reason="real_wing_focused_validation_required",
                )
        else:
            try:
                focused_budgeting_payload = (
                    result.get("topology_compiler", {}).get("planning_budgeting")
                    if isinstance(result.get("topology_compiler"), dict)
                    else None
                )
                if not isinstance(focused_budgeting_payload, dict):
                    focused_budgeting_payload = _build_real_wing_bl_budgeting_plan(
                        sections=[dict(section) for section in real_wing_geometry.get("sections", [])],
                        protection=dict(protection_config),
                        base_total_thickness_m=float(bl_spec["target_total_thickness_m"]),
                        half_span_m=float(geometry.get("half_span_m") or DEFAULT_HALF_SPAN_M),
                    ).model_dump(mode="json")
                if bl_candidate_apply_gate == BL_CANDIDATE_APPLY_GATE_STAGED_TRANSITION_GUARD_FOCUSED:
                    target_y_span, _, _ = _derive_focused_sweep_target_and_truncation_grid(
                        focused_budgeting_payload
                    )
                    staged_transition_prototypes = _build_topology_preserving_staged_transition_prototypes(
                        target_y_span=target_y_span,
                        original_layer_count=8,
                    )
                    result["bl_candidate_apply"] = (
                        _run_shell_v4_bl_staged_transition_guard_focused_apply(
                            out_dir=out_dir,
                            apply_gate=bl_candidate_apply_gate,
                            source_path=Path(
                                real_wing_geometry.get("source_path") or geometry.get("source_path")
                            ),
                            component=str(
                                real_wing_geometry.get("component")
                                or geometry.get("component")
                                or "main_wing"
                            ),
                            staged_transition_prototypes=staged_transition_prototypes,
                        )
                    )
                else:
                    existing_comparison = (
                        result.get("topology_compiler", {}).get("bl_candidate_comparison")
                        if isinstance(result.get("topology_compiler"), dict)
                        else None
                    )
                    if not isinstance(existing_comparison, dict):
                        existing_comparison = _build_bl_stageback_truncation_candidate_comparison(
                            planning_budgeting=focused_budgeting_payload,
                            planning_policy_fail_kinds=["bl_clearance_incompatibility"],
                            planning_policy_recommendation_kinds=list(
                                focused_budgeting_payload.get("recommendation_kinds") or []
                            ),
                            original_layer_count=int(bl_spec.get("layers") or 0),
                        )
                    result["bl_candidate_apply"] = _run_shell_v4_bl_stageback_plus_truncation_focused_apply(
                        out_dir=out_dir,
                        apply_gate=bl_candidate_apply_gate,
                        source_path=Path(real_wing_geometry.get("source_path") or geometry.get("source_path")),
                        component=str(real_wing_geometry.get("component") or geometry.get("component") or "main_wing"),
                        bl_candidate_comparison=existing_comparison,
                    )
            except Exception as exc:
                if bl_candidate_apply_gate == BL_CANDIDATE_APPLY_GATE_STAGED_TRANSITION_GUARD_FOCUSED:
                    result["bl_candidate_apply"] = _write_rejected_staged_transition_apply_comparison(
                        artifact_dir=out_dir
                        / "artifacts"
                        / "topology_compiler"
                        / "staged_transition_apply",
                        apply_gate=bl_candidate_apply_gate,
                        reject_reason=f"focused_apply_failed:{exc}",
                    )
                else:
                    result["bl_candidate_apply"] = _write_rejected_bl_candidate_apply_comparison(
                        artifact_dir=out_dir / "artifacts" / "topology_compiler" / "bl_candidate_apply",
                        apply_gate=bl_candidate_apply_gate,
                        reject_reason=f"focused_apply_failed:{exc}",
                    )
                result["notes"].append(
                    "Experimental BL candidate focused apply failed after the runtime path completed; production runtime outputs are unchanged."
                )

    write_json_report(mesh_metadata_path, result)
    write_json_report(out_dir / "report.json", result)
    write_markdown_report(out_dir / "report.md", result)
    return result
