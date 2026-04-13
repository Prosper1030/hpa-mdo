"""Frozen-load aeroelastic inverse-design helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import logging
from pathlib import Path

import numpy as np

from hpa_mdo.core.config import SolverConfig
from hpa_mdo.structure.dual_beam_mainline.types import (
    DualBeamMainlineModel,
    DualBeamMainlineResult,
)


INVERSE_MARGIN_NAMES = (
    "loaded_shape_main_z_margin_m",
    "loaded_shape_twist_margin_deg",
    "ground_clearance_margin_m",
    "jig_prebend_margin_m",
    "jig_curvature_margin_per_m",
)

_DEFAULT_SOLVER_CONFIG = SolverConfig()
DEFAULT_LOADED_SHAPE_Z_TOL_M = float(_DEFAULT_SOLVER_CONFIG.loaded_shape_z_tol_m)
DEFAULT_LOADED_SHAPE_TWIST_TOL_DEG = float(
    _DEFAULT_SOLVER_CONFIG.loaded_shape_twist_tol_deg
)
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StructuralNodeShape:
    """Explicit main/rear spar node coordinates for one structural shape."""

    main_nodes_m: np.ndarray
    rear_nodes_m: np.ndarray


@dataclass(frozen=True)
class ShapeErrorMetrics:
    """Loaded-shape closure error for the frozen-load inverse construction."""

    max_abs_error_m: float
    rms_error_m: float
    tolerance_m: float
    passed: bool


@dataclass(frozen=True)
class LoadedShapeMatchMetrics:
    """Low-dimensional loaded-shape matching metrics on a few control stations."""

    mode: str
    control_station_fractions: tuple[float, ...]
    control_station_y_m: tuple[float, ...]
    main_z_target_m: tuple[float, ...]
    main_z_loaded_m: tuple[float, ...]
    main_z_error_m: tuple[float, ...]
    twist_target_deg: tuple[float, ...]
    twist_loaded_deg: tuple[float, ...]
    twist_error_deg: tuple[float, ...]
    main_z_tolerance_m: float
    twist_tolerance_deg: float
    main_z_max_abs_error_m: float
    main_z_rms_error_m: float
    twist_max_abs_error_deg: float
    twist_rms_error_deg: float
    normalized_max_error: float
    normalized_rms_error: float
    passed: bool


@dataclass(frozen=True)
class GroundClearanceMetrics:
    """Ground-clearance metrics evaluated on the back-solved jig shape."""

    clearance_floor_z_m: float
    min_main_z_m: float
    min_rear_z_m: float
    min_z_m: float
    margin_m: float
    passed: bool


@dataclass(frozen=True)
class ManufacturingMetrics:
    """Simple jig manufacturability metrics for the required pre-bend."""

    max_abs_vertical_prebend_m: float
    max_abs_vertical_curvature_per_m: float
    prebend_limit_m: float | None
    curvature_limit_per_m: float | None
    prebend_margin_m: float
    curvature_margin_per_m: float
    prebend_passed: bool
    curvature_passed: bool
    passed: bool


@dataclass(frozen=True)
class MonotonicDeflectionCheck:
    """Diagnostic summary for per-segment monotonic vertical deflection."""

    segments_checked: int
    segments_monotonic: int
    worst_violation_m: float
    worst_violation_node_y_m: float
    passed: bool
    details: tuple[str, ...]


@dataclass(frozen=True)
class InverseDesignFeasibility:
    """Aggregated feasibility state for the inverse-design MVP."""

    analysis_succeeded: bool
    geometry_validity_passed: bool
    equivalent_failure_passed: bool
    equivalent_buckling_passed: bool
    equivalent_tip_passed: bool
    equivalent_twist_passed: bool
    loaded_shape_match_passed: bool
    target_shape_error_passed: bool
    ground_clearance_passed: bool
    manufacturing_passed: bool
    safety_passed: bool
    overall_feasible: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class FrozenLoadInverseDesignResult:
    """Complete frozen-load inverse-design reconstruction for one candidate."""

    target_loaded_shape: StructuralNodeShape
    jig_shape: StructuralNodeShape
    predicted_loaded_shape: StructuralNodeShape
    displacement_main_m: np.ndarray
    displacement_rear_m: np.ndarray
    loaded_shape_match: LoadedShapeMatchMetrics
    target_shape_error: ShapeErrorMetrics
    ground_clearance: GroundClearanceMetrics
    manufacturing: ManufacturingMetrics
    feasibility: InverseDesignFeasibility
    monotonic_deflection: MonotonicDeflectionCheck | None = None


def _copy_nodes(nodes_m: np.ndarray) -> np.ndarray:
    arr = np.asarray(nodes_m, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(f"Expected node array with shape (n_nodes, 3), got {arr.shape}.")
    return arr.copy()


def _translation_columns(disp_m: np.ndarray, label: str) -> np.ndarray:
    arr = np.asarray(disp_m, dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError(f"{label} must have shape (n_nodes, >=3), got {arr.shape}.")
    return arr[:, :3].copy()


def build_target_loaded_shape(
    *,
    model: DualBeamMainlineModel,
    z_scale: float = 1.0,
    dihedral_exponent: float = 1.0,
) -> StructuralNodeShape:
    """Return the current structural beam geometry as the loaded target shape."""

    main_nodes_m = _copy_nodes(model.nodes_main_m)
    rear_nodes_m = _copy_nodes(model.nodes_rear_m)
    scale = float(z_scale)
    if abs(scale - 1.0) > 1.0e-12:
        exp = float(dihedral_exponent)
        half_span = float(model.nodes_main_m[-1, 1]) if model.nodes_main_m.size else 0.0
        if half_span > 0.0:
            eta_main = np.clip(np.asarray(model.nodes_main_m[:, 1], dtype=float) / half_span, 0.0, 1.0)
            eta_rear = np.clip(np.asarray(model.nodes_rear_m[:, 1], dtype=float) / half_span, 0.0, 1.0)
        else:
            eta_main = np.zeros(main_nodes_m.shape[0], dtype=float)
            eta_rear = np.zeros(rear_nodes_m.shape[0], dtype=float)
        factor_main = 1.0 + (scale - 1.0) * np.power(eta_main, exp)
        factor_rear = 1.0 + (scale - 1.0) * np.power(eta_rear, exp)
        main_nodes_m[:, 2] *= factor_main
        rear_nodes_m[:, 2] *= factor_rear
    return StructuralNodeShape(
        main_nodes_m=main_nodes_m,
        rear_nodes_m=rear_nodes_m,
    )


def backout_jig_shape(
    *,
    target_loaded_shape: StructuralNodeShape,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
) -> StructuralNodeShape:
    """Return ``nodes_jig = nodes_target - ΔU`` for both beam lines."""

    main_translation = _translation_columns(disp_main_m, "disp_main_m")
    rear_translation = _translation_columns(disp_rear_m, "disp_rear_m")

    if main_translation.shape[0] != target_loaded_shape.main_nodes_m.shape[0]:
        raise ValueError("disp_main_m length must match target main-node count.")
    if rear_translation.shape[0] != target_loaded_shape.rear_nodes_m.shape[0]:
        raise ValueError("disp_rear_m length must match target rear-node count.")

    return StructuralNodeShape(
        main_nodes_m=_copy_nodes(target_loaded_shape.main_nodes_m) - main_translation,
        rear_nodes_m=_copy_nodes(target_loaded_shape.rear_nodes_m) - rear_translation,
    )


def backout_jig_shape_low_dim(
    *,
    target_loaded_shape: StructuralNodeShape,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
    y_nodes_m: np.ndarray,
    control_station_fractions: tuple[float, ...],
) -> StructuralNodeShape:
    """Back out a jig shape that only matches low-dimensional loaded-shape descriptors."""

    main_translation = _translation_columns(disp_main_m, "disp_main_m")
    rear_translation = _translation_columns(disp_rear_m, "disp_rear_m")
    y_arr = np.asarray(y_nodes_m, dtype=float).reshape(-1)
    if y_arr.ndim != 1 or y_arr.size != target_loaded_shape.main_nodes_m.shape[0]:
        raise ValueError("y_nodes_m must be a 1D array matching the beam-node count.")
    if y_arr.size != target_loaded_shape.rear_nodes_m.shape[0]:
        raise ValueError("main and rear beam-node counts must match for low-dimensional matching.")
    if np.any(np.diff(y_arr) <= 0.0):
        raise ValueError("y_nodes_m must be strictly increasing.")

    y_ctrl = _control_station_y(y_arr, control_station_fractions)
    main_dz = np.asarray(main_translation[:, 2], dtype=float)
    rear_dz = np.asarray(rear_translation[:, 2], dtype=float)
    delta_dz = rear_dz - main_dz

    main_dz_ctrl = np.interp(y_ctrl, y_arr, main_dz)
    delta_dz_ctrl = np.interp(y_ctrl, y_arr, delta_dz)
    main_dz_proj = np.interp(y_arr, y_ctrl, main_dz_ctrl)
    delta_dz_proj = np.interp(y_arr, y_ctrl, delta_dz_ctrl)
    rear_dz_proj = main_dz_proj + delta_dz_proj

    main_nodes = _copy_nodes(target_loaded_shape.main_nodes_m)
    rear_nodes = _copy_nodes(target_loaded_shape.rear_nodes_m)
    main_nodes[:, 0] -= main_translation[:, 0]
    main_nodes[:, 1] -= main_translation[:, 1]
    main_nodes[:, 2] -= main_dz_proj
    rear_nodes[:, 0] -= rear_translation[:, 0]
    rear_nodes[:, 1] -= rear_translation[:, 1]
    rear_nodes[:, 2] -= rear_dz_proj

    return StructuralNodeShape(main_nodes_m=main_nodes, rear_nodes_m=rear_nodes)


def predict_loaded_shape(
    *,
    jig_shape: StructuralNodeShape,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
) -> StructuralNodeShape:
    """Return the frozen-load loaded shape predicted from the jig geometry."""

    main_translation = _translation_columns(disp_main_m, "disp_main_m")
    rear_translation = _translation_columns(disp_rear_m, "disp_rear_m")

    return StructuralNodeShape(
        main_nodes_m=_copy_nodes(jig_shape.main_nodes_m) + main_translation,
        rear_nodes_m=_copy_nodes(jig_shape.rear_nodes_m) + rear_translation,
    )


def _control_station_y(y_nodes_m: np.ndarray, control_station_fractions: tuple[float, ...]) -> np.ndarray:
    y_arr = np.asarray(y_nodes_m, dtype=float).reshape(-1)
    if y_arr.size == 0:
        raise ValueError("Need at least one beam node to define control stations.")
    if np.any(np.diff(y_arr) < 0.0):
        raise ValueError("y_nodes_m must be monotonic.")
    fractions = np.asarray(control_station_fractions, dtype=float).reshape(-1)
    if fractions.size == 0:
        raise ValueError("Need at least one control-station fraction.")
    if np.any(fractions < -1.0e-12) or np.any(fractions > 1.0 + 1.0e-12):
        raise ValueError("Control-station fractions must stay within [0, 1].")
    span = float(y_arr[-1] - y_arr[0])
    if span <= 0.0:
        return np.full_like(fractions, y_arr[0], dtype=float)
    return y_arr[0] + np.clip(fractions, 0.0, 1.0) * span


def _interp_component_at_y(nodes_m: np.ndarray, y_query_m: np.ndarray, component_idx: int) -> np.ndarray:
    nodes_arr = _copy_nodes(nodes_m)
    return np.interp(
        np.asarray(y_query_m, dtype=float),
        np.asarray(nodes_arr[:, 1], dtype=float),
        np.asarray(nodes_arr[:, component_idx], dtype=float),
    )


def _shape_twist_deg_at_y(shape: StructuralNodeShape, y_query_m: np.ndarray) -> np.ndarray:
    main_x = _interp_component_at_y(shape.main_nodes_m, y_query_m, 0)
    main_z = _interp_component_at_y(shape.main_nodes_m, y_query_m, 2)
    rear_x = _interp_component_at_y(shape.rear_nodes_m, y_query_m, 0)
    rear_z = _interp_component_at_y(shape.rear_nodes_m, y_query_m, 2)
    chord_dx = rear_x - main_x
    chord_dz = rear_z - main_z
    return np.degrees(np.arctan2(chord_dz, chord_dx))


def _loaded_shape_match_metrics(
    *,
    target_loaded_shape: StructuralNodeShape,
    predicted_loaded_shape: StructuralNodeShape,
    y_nodes_m: np.ndarray,
    control_station_fractions: tuple[float, ...],
    main_z_tolerance_m: float,
    twist_tolerance_deg: float,
    mode: str,
) -> LoadedShapeMatchMetrics:
    y_ctrl = _control_station_y(np.asarray(y_nodes_m, dtype=float), control_station_fractions)
    main_z_target = _interp_component_at_y(target_loaded_shape.main_nodes_m, y_ctrl, 2)
    main_z_loaded = _interp_component_at_y(predicted_loaded_shape.main_nodes_m, y_ctrl, 2)
    main_z_error = main_z_loaded - main_z_target
    twist_target = _shape_twist_deg_at_y(target_loaded_shape, y_ctrl)
    twist_loaded = _shape_twist_deg_at_y(predicted_loaded_shape, y_ctrl)
    twist_error = twist_loaded - twist_target

    main_z_max_abs = float(np.max(np.abs(main_z_error))) if main_z_error.size else 0.0
    main_z_rms = float(np.sqrt(np.mean(np.square(main_z_error)))) if main_z_error.size else 0.0
    twist_max_abs = float(np.max(np.abs(twist_error))) if twist_error.size else 0.0
    twist_rms = float(np.sqrt(np.mean(np.square(twist_error)))) if twist_error.size else 0.0

    z_scale = max(float(main_z_tolerance_m), 1.0e-12)
    twist_scale = max(float(twist_tolerance_deg), 1.0e-12)
    normalized_max = float(max(main_z_max_abs / z_scale, twist_max_abs / twist_scale))
    normalized_rms = float(np.sqrt((main_z_rms / z_scale) ** 2 + (twist_rms / twist_scale) ** 2))

    return LoadedShapeMatchMetrics(
        mode=str(mode),
        control_station_fractions=tuple(float(value) for value in control_station_fractions),
        control_station_y_m=tuple(float(value) for value in y_ctrl),
        main_z_target_m=tuple(float(value) for value in main_z_target),
        main_z_loaded_m=tuple(float(value) for value in main_z_loaded),
        main_z_error_m=tuple(float(value) for value in main_z_error),
        twist_target_deg=tuple(float(value) for value in twist_target),
        twist_loaded_deg=tuple(float(value) for value in twist_loaded),
        twist_error_deg=tuple(float(value) for value in twist_error),
        main_z_tolerance_m=float(main_z_tolerance_m),
        twist_tolerance_deg=float(twist_tolerance_deg),
        main_z_max_abs_error_m=main_z_max_abs,
        main_z_rms_error_m=main_z_rms,
        twist_max_abs_error_deg=twist_max_abs,
        twist_rms_error_deg=twist_rms,
        normalized_max_error=normalized_max,
        normalized_rms_error=normalized_rms,
        passed=bool(
            main_z_max_abs <= float(main_z_tolerance_m) + 1.0e-12
            and twist_max_abs <= float(twist_tolerance_deg) + 1.0e-12
        ),
    )


def _shape_error_metrics(
    *,
    target_loaded_shape: StructuralNodeShape,
    predicted_loaded_shape: StructuralNodeShape,
    tolerance_m: float,
) -> ShapeErrorMetrics:
    error_main = predicted_loaded_shape.main_nodes_m - target_loaded_shape.main_nodes_m
    error_rear = predicted_loaded_shape.rear_nodes_m - target_loaded_shape.rear_nodes_m
    stacked = np.vstack((error_main, error_rear))
    node_norms = np.linalg.norm(stacked, axis=1) if stacked.size else np.zeros(0, dtype=float)
    max_abs_error_m = float(np.max(node_norms)) if node_norms.size else 0.0
    rms_error_m = (
        float(np.sqrt(np.mean(np.square(node_norms))))
        if node_norms.size
        else 0.0
    )
    return ShapeErrorMetrics(
        max_abs_error_m=max_abs_error_m,
        rms_error_m=rms_error_m,
        tolerance_m=float(tolerance_m),
        passed=bool(max_abs_error_m <= float(tolerance_m) + 1.0e-12),
    )


def _ground_clearance_metrics(
    *,
    jig_shape: StructuralNodeShape,
    clearance_floor_z_m: float,
) -> GroundClearanceMetrics:
    min_main_z_m = float(np.min(jig_shape.main_nodes_m[:, 2]))
    min_rear_z_m = float(np.min(jig_shape.rear_nodes_m[:, 2]))
    min_z_m = min(min_main_z_m, min_rear_z_m)
    margin_m = min_z_m - float(clearance_floor_z_m)
    return GroundClearanceMetrics(
        clearance_floor_z_m=float(clearance_floor_z_m),
        min_main_z_m=min_main_z_m,
        min_rear_z_m=min_rear_z_m,
        min_z_m=min_z_m,
        margin_m=float(margin_m),
        passed=bool(margin_m >= -1.0e-12),
    )


def _max_abs_vertical_curvature_per_m(y_nodes_m: np.ndarray, z_offset_m: np.ndarray) -> float:
    y_arr = np.asarray(y_nodes_m, dtype=float).reshape(-1)
    z_arr = np.asarray(z_offset_m, dtype=float).reshape(-1)
    if y_arr.shape != z_arr.shape:
        raise ValueError("y_nodes_m and z_offset_m must have the same shape.")
    if y_arr.size < 3:
        return 0.0

    curvatures: list[float] = []
    for idx in range(1, y_arr.size - 1):
        dy_prev = float(y_arr[idx] - y_arr[idx - 1])
        dy_next = float(y_arr[idx + 1] - y_arr[idx])
        if dy_prev <= 0.0 or dy_next <= 0.0:
            raise ValueError("y_nodes_m must be strictly increasing.")
        second_derivative = (
            2.0 * z_arr[idx - 1] / (dy_prev * (dy_prev + dy_next))
            - 2.0 * z_arr[idx] / (dy_prev * dy_next)
            + 2.0 * z_arr[idx + 1] / (dy_next * (dy_prev + dy_next))
        )
        curvatures.append(abs(float(second_derivative)))
    return max(curvatures, default=0.0)


def check_monotonic_deflection(
    *,
    y_nodes_m: np.ndarray,
    uz_m: np.ndarray,
    wire_y_positions: tuple[float, ...] = (),
    tolerance_m: float = 1.0e-4,
) -> MonotonicDeflectionCheck:
    """Check uz monotonicity in each span segment split by wire attachment Y."""

    y_arr = np.asarray(y_nodes_m, dtype=float).reshape(-1)
    uz_arr = np.asarray(uz_m, dtype=float).reshape(-1)
    if y_arr.size != uz_arr.size:
        raise ValueError("y_nodes_m and uz_m must have the same length.")
    if y_arr.size == 0:
        return MonotonicDeflectionCheck(
            segments_checked=0,
            segments_monotonic=0,
            worst_violation_m=0.0,
            worst_violation_node_y_m=0.0,
            passed=True,
            details=(),
        )
    if np.any(np.diff(y_arr) < 0.0):
        raise ValueError("y_nodes_m must be monotonic non-decreasing.")

    root_y = float(y_arr[0])
    tip_y = float(y_arr[-1])
    interior_wire_y = sorted(
        {
            float(y)
            for y in wire_y_positions
            if root_y < float(y) < tip_y
        }
    )
    boundaries = [root_y, *interior_wire_y, tip_y]
    tolerance = float(tolerance_m)
    segment_details: list[str] = []
    segments_checked = 0
    segments_monotonic = 0
    worst_violation = 0.0
    worst_y = root_y

    for start_y, end_y in zip(boundaries[:-1], boundaries[1:]):
        node_mask = (y_arr >= float(start_y) - 1.0e-12) & (y_arr <= float(end_y) + 1.0e-12)
        idx = np.flatnonzero(node_mask)
        if idx.size < 2:
            continue
        segments_checked += 1
        segment_passed = True
        for left, right in zip(idx[:-1], idx[1:]):
            violation = float(uz_arr[left] - uz_arr[right] - tolerance)
            if violation > 0.0:
                segment_passed = False
                if violation > worst_violation:
                    worst_violation = violation
                    worst_y = float(y_arr[right])
                segment_details.append(
                    (
                        f"segment [{start_y:.3f}, {end_y:.3f}] m: non-monotonic at "
                        f"y={float(y_arr[right]):.3f} m, violation={violation:.6e} m"
                    )
                )
        if segment_passed:
            segments_monotonic += 1

    passed = bool(segments_checked == segments_monotonic)
    return MonotonicDeflectionCheck(
        segments_checked=int(segments_checked),
        segments_monotonic=int(segments_monotonic),
        worst_violation_m=float(worst_violation),
        worst_violation_node_y_m=float(worst_y),
        passed=passed,
        details=tuple(segment_details),
    )


def _manufacturing_metrics(
    *,
    target_loaded_shape: StructuralNodeShape,
    jig_shape: StructuralNodeShape,
    y_nodes_m: np.ndarray,
    max_abs_vertical_prebend_m: float | None,
    max_abs_vertical_curvature_per_m: float | None,
) -> ManufacturingMetrics:
    main_prebend_z_m = target_loaded_shape.main_nodes_m[:, 2] - jig_shape.main_nodes_m[:, 2]
    rear_prebend_z_m = target_loaded_shape.rear_nodes_m[:, 2] - jig_shape.rear_nodes_m[:, 2]
    max_prebend_m = float(
        max(
            np.max(np.abs(main_prebend_z_m), initial=0.0),
            np.max(np.abs(rear_prebend_z_m), initial=0.0),
        )
    )
    max_curvature_per_m = float(
        max(
            _max_abs_vertical_curvature_per_m(y_nodes_m, main_prebend_z_m),
            _max_abs_vertical_curvature_per_m(y_nodes_m, rear_prebend_z_m),
        )
    )
    prebend_margin_m = (
        float("inf")
        if max_abs_vertical_prebend_m is None
        else float(max_abs_vertical_prebend_m) - max_prebend_m
    )
    curvature_margin_per_m = (
        float("inf")
        if max_abs_vertical_curvature_per_m is None
        else float(max_abs_vertical_curvature_per_m) - max_curvature_per_m
    )
    prebend_passed = max_abs_vertical_prebend_m is None or prebend_margin_m >= -1.0e-12
    curvature_passed = (
        max_abs_vertical_curvature_per_m is None
        or curvature_margin_per_m >= -1.0e-12
    )
    return ManufacturingMetrics(
        max_abs_vertical_prebend_m=max_prebend_m,
        max_abs_vertical_curvature_per_m=max_curvature_per_m,
        prebend_limit_m=(
            None
            if max_abs_vertical_prebend_m is None
            else float(max_abs_vertical_prebend_m)
        ),
        curvature_limit_per_m=(
            None
            if max_abs_vertical_curvature_per_m is None
            else float(max_abs_vertical_curvature_per_m)
        ),
        prebend_margin_m=float(prebend_margin_m),
        curvature_margin_per_m=float(curvature_margin_per_m),
        prebend_passed=bool(prebend_passed),
        curvature_passed=bool(curvature_passed),
        passed=bool(prebend_passed and curvature_passed),
    )


def build_frozen_load_inverse_design(
    *,
    target_loaded_shape: StructuralNodeShape,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
    y_nodes_m: np.ndarray,
    analysis_succeeded: bool,
    geometry_validity_passed: bool,
    equivalent_failure_passed: bool,
    equivalent_buckling_passed: bool,
    equivalent_tip_passed: bool,
    equivalent_twist_passed: bool,
    clearance_floor_z_m: float = 0.0,
    target_shape_error_tol_m: float = 1.0e-9,
    max_abs_vertical_prebend_m: float | None = None,
    max_abs_vertical_curvature_per_m: float | None = None,
    loaded_shape_mode: str = "exact_nodal",
    loaded_shape_control_station_fractions: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0),
    loaded_shape_main_z_tol_m: float = DEFAULT_LOADED_SHAPE_Z_TOL_M,
    loaded_shape_twist_tol_deg: float = DEFAULT_LOADED_SHAPE_TWIST_TOL_DEG,
    monotonic_deflection: MonotonicDeflectionCheck | None = None,
) -> FrozenLoadInverseDesignResult:
    """Construct the frozen-load inverse-design result for one candidate."""

    if loaded_shape_mode == "exact_nodal":
        jig_shape = backout_jig_shape(
            target_loaded_shape=target_loaded_shape,
            disp_main_m=disp_main_m,
            disp_rear_m=disp_rear_m,
        )
    elif loaded_shape_mode == "low_dim_descriptor":
        jig_shape = backout_jig_shape_low_dim(
            target_loaded_shape=target_loaded_shape,
            disp_main_m=disp_main_m,
            disp_rear_m=disp_rear_m,
            y_nodes_m=np.asarray(y_nodes_m, dtype=float),
            control_station_fractions=tuple(loaded_shape_control_station_fractions),
        )
    else:
        raise ValueError(f"Unsupported loaded_shape_mode: {loaded_shape_mode}")
    predicted_loaded_shape = predict_loaded_shape(
        jig_shape=jig_shape,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
    )
    loaded_shape_match = _loaded_shape_match_metrics(
        target_loaded_shape=target_loaded_shape,
        predicted_loaded_shape=predicted_loaded_shape,
        y_nodes_m=np.asarray(y_nodes_m, dtype=float),
        control_station_fractions=tuple(loaded_shape_control_station_fractions),
        main_z_tolerance_m=float(loaded_shape_main_z_tol_m),
        twist_tolerance_deg=float(loaded_shape_twist_tol_deg),
        mode=str(loaded_shape_mode),
    )
    target_shape_error = _shape_error_metrics(
        target_loaded_shape=target_loaded_shape,
        predicted_loaded_shape=predicted_loaded_shape,
        tolerance_m=float(target_shape_error_tol_m),
    )
    ground_clearance = _ground_clearance_metrics(
        jig_shape=jig_shape,
        clearance_floor_z_m=float(clearance_floor_z_m),
    )
    manufacturing = _manufacturing_metrics(
        target_loaded_shape=target_loaded_shape,
        jig_shape=jig_shape,
        y_nodes_m=np.asarray(y_nodes_m, dtype=float),
        max_abs_vertical_prebend_m=max_abs_vertical_prebend_m,
        max_abs_vertical_curvature_per_m=max_abs_vertical_curvature_per_m,
    )

    failures: list[str] = []
    if not analysis_succeeded:
        failures.append("dual_beam_analysis")
    if not geometry_validity_passed:
        failures.append("geometry_validity")
    if not equivalent_failure_passed:
        failures.append("equivalent_failure")
    if not equivalent_buckling_passed:
        failures.append("equivalent_buckling")
    if not equivalent_tip_passed:
        failures.append("equivalent_tip_deflection")
    if not equivalent_twist_passed:
        failures.append("equivalent_twist")
    if not loaded_shape_match.passed:
        failures.append("loaded_shape_match")
    if not ground_clearance.passed:
        failures.append("ground_clearance")
    if not manufacturing.prebend_passed:
        failures.append("jig_prebend")
    if not manufacturing.curvature_passed:
        failures.append("jig_curvature")

    safety_passed = bool(
        analysis_succeeded
        and geometry_validity_passed
        and equivalent_failure_passed
        and equivalent_buckling_passed
        and equivalent_tip_passed
        and equivalent_twist_passed
    )
    feasibility = InverseDesignFeasibility(
        analysis_succeeded=bool(analysis_succeeded),
        geometry_validity_passed=bool(geometry_validity_passed),
        equivalent_failure_passed=bool(equivalent_failure_passed),
        equivalent_buckling_passed=bool(equivalent_buckling_passed),
        equivalent_tip_passed=bool(equivalent_tip_passed),
        equivalent_twist_passed=bool(equivalent_twist_passed),
        loaded_shape_match_passed=bool(loaded_shape_match.passed),
        target_shape_error_passed=bool(target_shape_error.passed),
        ground_clearance_passed=bool(ground_clearance.passed),
        manufacturing_passed=bool(manufacturing.passed),
        safety_passed=bool(safety_passed),
        overall_feasible=not failures,
        failures=tuple(failures),
    )
    return FrozenLoadInverseDesignResult(
        target_loaded_shape=target_loaded_shape,
        jig_shape=jig_shape,
        predicted_loaded_shape=predicted_loaded_shape,
        displacement_main_m=_translation_columns(disp_main_m, "disp_main_m"),
        displacement_rear_m=_translation_columns(disp_rear_m, "disp_rear_m"),
        loaded_shape_match=loaded_shape_match,
        target_shape_error=target_shape_error,
        ground_clearance=ground_clearance,
        manufacturing=manufacturing,
        feasibility=feasibility,
        monotonic_deflection=monotonic_deflection,
    )


def build_frozen_load_inverse_design_from_mainline(
    *,
    model: DualBeamMainlineModel,
    result: DualBeamMainlineResult,
    clearance_floor_z_m: float = 0.0,
    target_shape_error_tol_m: float = 1.0e-9,
    max_abs_vertical_prebend_m: float | None = None,
    max_abs_vertical_curvature_per_m: float | None = None,
    loaded_shape_mode: str = "exact_nodal",
    loaded_shape_control_station_fractions: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0),
    loaded_shape_main_z_tol_m: float = DEFAULT_LOADED_SHAPE_Z_TOL_M,
    loaded_shape_twist_tol_deg: float = DEFAULT_LOADED_SHAPE_TWIST_TOL_DEG,
    target_loaded_shape_z_scale: float = 1.0,
    target_loaded_shape_dihedral_exponent: float = 1.0,
    wire_y_positions: tuple[float, ...] = (),
    monotonic_tolerance_m: float = 1.0e-4,
) -> FrozenLoadInverseDesignResult:
    """Convenience wrapper for the current dual-beam production result."""

    monotonic_check = check_monotonic_deflection(
        y_nodes_m=np.asarray(model.nodes_main_m[:, 1], dtype=float),
        uz_m=np.asarray(result.disp_main_m[:, 2], dtype=float),
        wire_y_positions=tuple(float(value) for value in wire_y_positions),
        tolerance_m=float(monotonic_tolerance_m),
    )
    if not monotonic_check.passed:
        LOGGER.warning(
            "Non-monotonic deflection detected: worst violation %.4f m at y=%.2f m",
            float(monotonic_check.worst_violation_m),
            float(monotonic_check.worst_violation_node_y_m),
        )

    return build_frozen_load_inverse_design(
        target_loaded_shape=build_target_loaded_shape(
            model=model,
            z_scale=target_loaded_shape_z_scale,
            dihedral_exponent=target_loaded_shape_dihedral_exponent,
        ),
        disp_main_m=result.disp_main_m,
        disp_rear_m=result.disp_rear_m,
        y_nodes_m=model.y_nodes_m,
        analysis_succeeded=result.feasibility.analysis_succeeded,
        geometry_validity_passed=result.feasibility.geometry_validity_succeeded,
        equivalent_failure_passed=result.feasibility.equivalent_failure_passed,
        equivalent_buckling_passed=result.feasibility.equivalent_buckling_passed,
        equivalent_tip_passed=result.feasibility.equivalent_tip_passed,
        equivalent_twist_passed=result.feasibility.equivalent_twist_passed,
        clearance_floor_z_m=clearance_floor_z_m,
        target_shape_error_tol_m=target_shape_error_tol_m,
        max_abs_vertical_prebend_m=max_abs_vertical_prebend_m,
        max_abs_vertical_curvature_per_m=max_abs_vertical_curvature_per_m,
        loaded_shape_mode=loaded_shape_mode,
        loaded_shape_control_station_fractions=loaded_shape_control_station_fractions,
        loaded_shape_main_z_tol_m=loaded_shape_main_z_tol_m,
        loaded_shape_twist_tol_deg=loaded_shape_twist_tol_deg,
        monotonic_deflection=monotonic_check,
    )


def build_inverse_design_margins(
    result: FrozenLoadInverseDesignResult,
) -> dict[str, float]:
    """Return scalar hard margins used by the inverse-design optimizer."""

    return {
        "loaded_shape_main_z_margin_m": float(
            result.loaded_shape_match.main_z_tolerance_m - result.loaded_shape_match.main_z_max_abs_error_m
        ),
        "loaded_shape_twist_margin_deg": float(
            result.loaded_shape_match.twist_tolerance_deg - result.loaded_shape_match.twist_max_abs_error_deg
        ),
        "ground_clearance_margin_m": float(result.ground_clearance.margin_m),
        "jig_prebend_margin_m": float(result.manufacturing.prebend_margin_m),
        "jig_curvature_margin_per_m": float(result.manufacturing.curvature_margin_per_m),
    }


def shape_to_dict(shape: StructuralNodeShape) -> dict[str, list[list[float]]]:
    """Return a JSON-serializable representation of a node shape."""

    return {
        "main_nodes_m": np.asarray(shape.main_nodes_m, dtype=float).tolist(),
        "rear_nodes_m": np.asarray(shape.rear_nodes_m, dtype=float).tolist(),
    }


def write_shape_csv_from_template(
    *,
    template_csv_path: str | Path,
    output_csv_path: str | Path,
    shape: StructuralNodeShape,
) -> Path:
    """Rewrite beam-node coordinates in an ANSYS/STEP template CSV."""

    template_path = Path(template_csv_path)
    output_path = Path(output_csv_path)
    with template_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    if not rows:
        raise ValueError(f"No rows found in template CSV: {template_path}")
    if not fieldnames:
        raise ValueError(f"Template CSV has no header: {template_path}")

    required = {"Y_Position_m", "Main_X_m", "Main_Z_m", "Rear_X_m", "Rear_Z_m"}
    missing = sorted(required - set(fieldnames))
    if missing:
        raise ValueError(
            f"Template CSV {template_path} is missing required columns: {', '.join(missing)}"
        )

    main_nodes_m = _copy_nodes(shape.main_nodes_m)
    rear_nodes_m = _copy_nodes(shape.rear_nodes_m)
    if main_nodes_m.shape != rear_nodes_m.shape:
        raise ValueError("main_nodes_m and rear_nodes_m must have the same shape.")
    if len(rows) != main_nodes_m.shape[0]:
        raise ValueError(
            "Template row count must match shape node count. "
            f"Expected {main_nodes_m.shape[0]}, got {len(rows)}."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for idx, row in enumerate(rows):
            updated = dict(row)
            updated["Y_Position_m"] = f"{main_nodes_m[idx, 1]:.12g}"
            updated["Main_X_m"] = f"{main_nodes_m[idx, 0]:.12g}"
            updated["Main_Z_m"] = f"{main_nodes_m[idx, 2]:.12g}"
            updated["Rear_X_m"] = f"{rear_nodes_m[idx, 0]:.12g}"
            updated["Rear_Z_m"] = f"{rear_nodes_m[idx, 2]:.12g}"
            writer.writerow(updated)

    return output_path
