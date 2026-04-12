"""Frozen-load aeroelastic inverse-design helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from hpa_mdo.structure.dual_beam_mainline.types import (
    DualBeamMainlineModel,
    DualBeamMainlineResult,
)


INVERSE_MARGIN_NAMES = (
    "target_shape_error_margin_m",
    "ground_clearance_margin_m",
    "jig_prebend_margin_m",
    "jig_curvature_margin_per_m",
)


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
class InverseDesignFeasibility:
    """Aggregated feasibility state for the inverse-design MVP."""

    analysis_succeeded: bool
    geometry_validity_passed: bool
    equivalent_failure_passed: bool
    equivalent_buckling_passed: bool
    equivalent_tip_passed: bool
    equivalent_twist_passed: bool
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
    target_shape_error: ShapeErrorMetrics
    ground_clearance: GroundClearanceMetrics
    manufacturing: ManufacturingMetrics
    feasibility: InverseDesignFeasibility


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


def build_target_loaded_shape(*, model: DualBeamMainlineModel) -> StructuralNodeShape:
    """Return the current structural beam geometry as the loaded target shape."""

    return StructuralNodeShape(
        main_nodes_m=_copy_nodes(model.nodes_main_m),
        rear_nodes_m=_copy_nodes(model.nodes_rear_m),
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
) -> FrozenLoadInverseDesignResult:
    """Construct the frozen-load inverse-design result for one candidate."""

    jig_shape = backout_jig_shape(
        target_loaded_shape=target_loaded_shape,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
    )
    predicted_loaded_shape = predict_loaded_shape(
        jig_shape=jig_shape,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
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
    if not target_shape_error.passed:
        failures.append("target_shape_error")
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
        target_shape_error=target_shape_error,
        ground_clearance=ground_clearance,
        manufacturing=manufacturing,
        feasibility=feasibility,
    )


def build_frozen_load_inverse_design_from_mainline(
    *,
    model: DualBeamMainlineModel,
    result: DualBeamMainlineResult,
    clearance_floor_z_m: float = 0.0,
    target_shape_error_tol_m: float = 1.0e-9,
    max_abs_vertical_prebend_m: float | None = None,
    max_abs_vertical_curvature_per_m: float | None = None,
) -> FrozenLoadInverseDesignResult:
    """Convenience wrapper for the current dual-beam production result."""

    return build_frozen_load_inverse_design(
        target_loaded_shape=build_target_loaded_shape(model=model),
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
    )


def build_inverse_design_margins(
    result: FrozenLoadInverseDesignResult,
) -> dict[str, float]:
    """Return scalar hard margins used by the inverse-design optimizer."""

    return {
        "target_shape_error_margin_m": float(
            result.target_shape_error.tolerance_m - result.target_shape_error.max_abs_error_m
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
