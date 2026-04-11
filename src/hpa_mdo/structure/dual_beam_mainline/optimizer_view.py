"""Optimizer-facing smooth quantities and feasibility summaries."""

from __future__ import annotations

import numpy as np

from hpa_mdo.structure.dual_beam_mainline.types import (
    DualBeamMainlineModel,
    EquivalentGateResult,
    FeasibilitySummary,
    GeometryValidityMargins,
    OptimizerFacingMetrics,
    SmoothAggregationResult,
)

_EQ_FAILURE_TOL = 0.01
_EQ_BUCKLING_TOL = 0.01
_EQ_LIMIT_TOL = 1.02
_GEOMETRY_TOL = 1.0e-12


def _min_or_inf(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        return float("inf")
    return float(np.min(arr))


def _taper_margin(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size < 2:
        return float("inf")
    return _min_or_inf(arr[:-1] - arr[1:])


def _step_margin(values: np.ndarray, max_step_m: float) -> float:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size < 2:
        return float("inf")
    return _min_or_inf(float(max_step_m) - np.abs(np.diff(arr)))


def _rear_inboard_element_indices(model: DualBeamMainlineModel) -> np.ndarray:
    element_centres_m = 0.5 * (model.y_nodes_m[:-1] + model.y_nodes_m[1:])
    if element_centres_m.size == 0:
        return np.zeros(0, dtype=int)
    idx = np.where(element_centres_m <= model.rear_inboard_span_m + 1.0e-12)[0]
    if idx.size == 0:
        return np.array([0], dtype=int)
    return np.asarray(idx, dtype=int)


def build_geometry_validity_margins(model: DualBeamMainlineModel) -> GeometryValidityMargins:
    """Build explicit geometry/manufacturability margins from the prepared model."""

    main_ei = np.asarray(model.main_young_pa, dtype=float) * np.asarray(model.main_iy_m4, dtype=float)
    rear_ei = np.asarray(model.rear_young_pa, dtype=float) * np.asarray(model.rear_iy_m4, dtype=float)
    rear_inboard_idx = _rear_inboard_element_indices(model)

    margins = GeometryValidityMargins(
        main_thickness_ratio_margin_min_m=_min_or_inf(
            model.max_thickness_to_radius_ratio * model.main_r_seg_m - model.main_t_seg_m
        ),
        rear_thickness_ratio_margin_min_m=_min_or_inf(
            model.max_thickness_to_radius_ratio * model.rear_r_seg_m - model.rear_t_seg_m
        ),
        main_hollow_margin_min_m=_min_or_inf(model.main_r_seg_m - model.main_t_seg_m),
        rear_hollow_margin_min_m=_min_or_inf(
            model.rear_r_seg_m - model.rear_t_seg_m - model.rear_min_inner_radius_m
        ),
        main_radius_taper_margin_min_m=_taper_margin(model.main_r_seg_m),
        rear_radius_taper_margin_min_m=_taper_margin(model.rear_r_seg_m),
        main_thickness_step_margin_min_m=_step_margin(
            model.main_t_seg_m,
            model.max_thickness_step_m,
        ),
        rear_thickness_step_margin_min_m=_step_margin(
            model.rear_t_seg_m,
            model.max_thickness_step_m,
        ),
        radius_dominance_margin_min_m=_min_or_inf(
            model.main_r_seg_m - model.rear_r_seg_m - model.main_spar_dominance_margin_m
        ),
        rear_main_radius_ratio_margin_min_m=_min_or_inf(
            model.rear_r_seg_m - model.rear_main_radius_ratio_min * model.main_r_seg_m
        ),
        ei_dominance_margin_min_nm2=_min_or_inf(
            main_ei - model.main_spar_ei_ratio * rear_ei
        ),
        ei_ratio_margin_min=_min_or_inf(
            main_ei / np.maximum(rear_ei, 1.0e-30) - model.main_spar_ei_ratio
        ),
        rear_inboard_ei_margin_min_nm2=_min_or_inf(
            model.rear_inboard_ei_to_main_ratio_max * main_ei[rear_inboard_idx]
            - rear_ei[rear_inboard_idx]
        ),
        valid=False,
    )
    finite_margins = (
        margins.main_thickness_ratio_margin_min_m,
        margins.rear_thickness_ratio_margin_min_m,
        margins.main_hollow_margin_min_m,
        margins.rear_hollow_margin_min_m,
        margins.main_radius_taper_margin_min_m,
        margins.rear_radius_taper_margin_min_m,
        margins.main_thickness_step_margin_min_m,
        margins.rear_thickness_step_margin_min_m,
        margins.radius_dominance_margin_min_m,
        margins.rear_main_radius_ratio_margin_min_m,
        margins.ei_dominance_margin_min_nm2,
        margins.ei_ratio_margin_min,
        margins.rear_inboard_ei_margin_min_nm2,
    )
    margins.valid = all(float(value) >= -_GEOMETRY_TOL for value in finite_margins)
    return margins


def build_equivalent_gate_result(model: DualBeamMainlineModel) -> EquivalentGateResult:
    """Project validated equivalent-beam gates into the Phase-2 result interface."""

    failure_margin = -float(model.equivalent_failure_index)
    buckling_margin = -float(model.equivalent_buckling_index)
    tip_limit_m = model.equivalent_tip_deflection_limit_m
    tip_margin_m = (
        float("inf")
        if tip_limit_m is None
        else float(tip_limit_m) - float(model.equivalent_tip_deflection_m)
    )
    twist_limit_deg = model.equivalent_twist_limit_deg
    twist_margin_deg = (
        float("inf")
        if twist_limit_deg is None
        else float(twist_limit_deg) - float(model.equivalent_twist_max_deg)
    )

    return EquivalentGateResult(
        analysis_success=bool(model.equivalent_analysis_success),
        failure_index=float(model.equivalent_failure_index),
        failure_margin=float(failure_margin),
        failure_passed=bool(
            model.equivalent_analysis_success
            and float(model.equivalent_failure_index) <= _EQ_FAILURE_TOL
        ),
        buckling_index=float(model.equivalent_buckling_index),
        buckling_margin=float(buckling_margin),
        buckling_passed=bool(
            model.equivalent_analysis_success
            and float(model.equivalent_buckling_index) <= _EQ_BUCKLING_TOL
        ),
        tip_deflection_m=float(model.equivalent_tip_deflection_m),
        tip_limit_m=tip_limit_m,
        tip_margin_m=float(tip_margin_m),
        tip_passed=bool(
            model.equivalent_analysis_success
            and (
                tip_limit_m is None
                or float(model.equivalent_tip_deflection_m)
                <= float(tip_limit_m) * _EQ_LIMIT_TOL
            )
        ),
        twist_max_deg=float(model.equivalent_twist_max_deg),
        twist_limit_deg=twist_limit_deg,
        twist_margin_deg=float(twist_margin_deg),
        twist_passed=bool(
            model.equivalent_analysis_success
            and (
                twist_limit_deg is None
                or float(model.equivalent_twist_max_deg)
                <= float(twist_limit_deg) * _EQ_LIMIT_TOL
            )
        ),
    )


def build_optimizer_facing_metrics(
    *,
    model: DualBeamMainlineModel,
    smooth: SmoothAggregationResult,
) -> OptimizerFacingMetrics:
    """Build future-optimizer metrics while keeping raw report channels separate."""

    dual_limit_m = model.max_tip_deflection_limit_m
    if dual_limit_m is None:
        dual_limit_m = model.equivalent_tip_deflection_limit_m

    return OptimizerFacingMetrics(
        psi_u_all_m=float(smooth.psi_u_all_m),
        psi_u_rear_m=float(smooth.psi_u_rear_m),
        psi_u_rear_outboard_m=float(smooth.psi_u_rear_outboard_m),
        dual_displacement_limit_m=dual_limit_m,
        dual_displacement_margin_m=(
            float("inf")
            if dual_limit_m is None
            else float(dual_limit_m) - float(smooth.psi_u_all_m)
        ),
        geometry_validity=build_geometry_validity_margins(model),
        equivalent_gates=build_equivalent_gate_result(model),
    )


def build_feasibility_summary(
    *,
    optimizer_metrics: OptimizerFacingMetrics,
    analysis_succeeded: bool,
) -> FeasibilitySummary:
    """Build the Phase-2 evaluator status split used by future optimizers."""

    hard_failures: list[str] = []
    candidate_constraint_failures: list[str] = []

    if not analysis_succeeded:
        hard_failures.append("dual_beam_analysis")
    if not optimizer_metrics.geometry_validity.valid:
        hard_failures.append("geometry_validity")

    eq = optimizer_metrics.equivalent_gates
    if not eq.analysis_success:
        hard_failures.append("equivalent_analysis")
    if not eq.failure_passed:
        hard_failures.append("equivalent_failure")
    if not eq.buckling_passed:
        hard_failures.append("equivalent_buckling")
    if not eq.tip_passed:
        hard_failures.append("equivalent_tip_deflection")
    if not eq.twist_passed:
        hard_failures.append("equivalent_twist")

    dual_displacement_passed = (
        optimizer_metrics.dual_displacement_limit_m is None
        or optimizer_metrics.dual_displacement_margin_m >= 0.0
    )
    if not dual_displacement_passed:
        candidate_constraint_failures.append("dual_displacement_candidate")

    return FeasibilitySummary(
        analysis_succeeded=bool(analysis_succeeded),
        geometry_validity_succeeded=bool(optimizer_metrics.geometry_validity.valid),
        dual_displacement_candidate_passed=bool(dual_displacement_passed),
        equivalent_failure_passed=bool(eq.failure_passed),
        equivalent_buckling_passed=bool(eq.buckling_passed),
        equivalent_tip_passed=bool(eq.tip_passed),
        equivalent_twist_passed=bool(eq.twist_passed),
        overall_hard_feasible=not hard_failures,
        overall_optimizer_candidate_feasible=not hard_failures
        and not candidate_constraint_failures,
        hard_failures=tuple(hard_failures),
        candidate_constraint_failures=tuple(candidate_constraint_failures),
        report_only_channels=(
            "raw_max_vertical_displacement",
            "raw_max_vertical_location",
            "raw_rear_main_tip_ratio",
            "raw_root_main_rear_reaction_partition",
            "raw_link_hotspot_metrics",
            "dual_stress_metrics",
            "dual_buckling_metrics",
            "smooth_link_force",
        ),
    )
