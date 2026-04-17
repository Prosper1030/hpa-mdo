"""Optimizer-facing smooth quantities and feasibility summaries."""

from __future__ import annotations

import numpy as np

from hpa_mdo.structure.dual_beam_mainline.types import (
    ConstraintAssemblyResult,
    DualBeamMainlineModel,
    EquivalentGateResult,
    FeasibilitySummary,
    GlobalObservableReadinessResult,
    GeometryValidityMargins,
    LoadSplitResult,
    NumericalConsistencyResult,
    OptimizerFacingMetrics,
    ReactionRecoveryResult,
    RecoveryResult,
    ReportMetrics,
    SmoothAggregationResult,
    WireSupportValidityResult,
)

_EQ_FAILURE_TOL = 0.01
_EQ_BUCKLING_TOL = 0.01
_EQ_LIMIT_TOL = 1.02
_GEOMETRY_TOL = 1.0e-12
_EQUILIBRIUM_TOL_N = 1.0e-6
_COMPATIBILITY_TOL = 1.0e-8
_FORCE_CLOSURE_TOL_N = 1.0e-6
_MOMENT_CLOSURE_TOL_NM = 1.0e-6
_CONDITION_LIMIT = 1.0e12


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


def _build_dual_state_vector(
    *,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
) -> np.ndarray:
    return np.concatenate(
        (
            np.asarray(disp_main_m, dtype=float).reshape(-1),
            np.asarray(disp_rear_m, dtype=float).reshape(-1),
        )
    )


def _build_dual_load_vector(
    *,
    load_split: LoadSplitResult,
) -> np.ndarray:
    return np.concatenate(
        (
            np.asarray(load_split.main_loads_n, dtype=float).reshape(-1),
            np.asarray(load_split.rear_loads_n, dtype=float).reshape(-1),
        )
    )


def _nodal_resultant(
    *,
    nodes_m: np.ndarray,
    nodal_loads_n: np.ndarray,
    origin_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    resultant_force_n = np.zeros(3, dtype=float)
    resultant_moment_nm = np.zeros(3, dtype=float)
    for node_m, load_row in zip(
        np.asarray(nodes_m, dtype=float),
        np.asarray(nodal_loads_n, dtype=float),
        strict=True,
    ):
        force_n = np.asarray(load_row[:3], dtype=float)
        moment_nm = np.asarray(load_row[3:6], dtype=float)
        resultant_force_n += force_n
        resultant_moment_nm += moment_nm + np.cross(node_m - origin_m, force_n)
    return resultant_force_n, resultant_moment_nm


def _global_force_and_moment_closure(
    *,
    model: DualBeamMainlineModel,
    load_split: LoadSplitResult,
    reactions: ReactionRecoveryResult,
) -> tuple[float, float]:
    origin_m = np.asarray(model.nodes_main_m[0], dtype=float)
    applied_main_force_n, applied_main_moment_nm = _nodal_resultant(
        nodes_m=model.nodes_main_m,
        nodal_loads_n=load_split.main_loads_n,
        origin_m=origin_m,
    )
    applied_rear_force_n, applied_rear_moment_nm = _nodal_resultant(
        nodes_m=model.nodes_rear_m,
        nodal_loads_n=load_split.rear_loads_n,
        origin_m=origin_m,
    )
    applied_force_n = applied_main_force_n + applied_rear_force_n
    applied_moment_nm = applied_main_moment_nm + applied_rear_moment_nm

    nn = model.y_nodes_m.size
    constraint_resultant_force_n = np.zeros(3, dtype=float)
    constraint_resultant_moment_nm = np.zeros(3, dtype=float)
    total_constraint_vector_n = np.asarray(reactions.total_constraint_reaction_vector_n, dtype=float)
    for node_index, node_m in enumerate(np.asarray(model.nodes_main_m, dtype=float)):
        base = node_index * 6
        force_n = total_constraint_vector_n[base : base + 3]
        moment_nm = np.asarray(total_constraint_vector_n[base + 3 : base + 6], dtype=float).copy()
        # The current dual-beam kernel has no physical external Mz load channel; span-axis point-moment
        # recovery here is dominated by self-equilibrated constraint bookkeeping from offset-rigid links.
        moment_nm[2] = 0.0
        constraint_resultant_force_n += force_n
        constraint_resultant_moment_nm += np.cross(node_m - origin_m, force_n) - moment_nm
    for node_index, node_m in enumerate(np.asarray(model.nodes_rear_m, dtype=float)):
        base = (nn + node_index) * 6
        force_n = total_constraint_vector_n[base : base + 3]
        moment_nm = np.asarray(total_constraint_vector_n[base + 3 : base + 6], dtype=float).copy()
        moment_nm[2] = 0.0
        constraint_resultant_force_n += force_n
        constraint_resultant_moment_nm += np.cross(node_m - origin_m, force_n) - moment_nm

    return (
        float(np.linalg.norm(applied_force_n + constraint_resultant_force_n)),
        float(np.linalg.norm(applied_moment_nm + constraint_resultant_moment_nm)),
    )


def build_numerical_consistency_result(
    *,
    model: DualBeamMainlineModel,
    stiffness: np.ndarray,
    constraints: ConstraintAssemblyResult,
    multipliers: np.ndarray,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
    load_split: LoadSplitResult,
    reactions: ReactionRecoveryResult,
    explicit_wire_support: object | None = None,
) -> NumericalConsistencyResult:
    """Summarize solver residuals and constraint health for hard gating."""

    state = _build_dual_state_vector(
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
    )
    load_vector = _build_dual_load_vector(load_split=load_split)
    multiplier_vec = np.asarray(multipliers, dtype=float).reshape(-1)

    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        equilibrium_vector = (
            np.asarray(stiffness, dtype=float) @ state
            + (
                np.asarray(explicit_wire_support.internal_force_vector_n, dtype=float)
                if explicit_wire_support is not None
                else 0.0
            )
            + np.asarray(constraints.matrix, dtype=float).T @ multiplier_vec
            - load_vector
        )
        compatibility_vector = (
            np.asarray(constraints.matrix, dtype=float) @ state
            - np.asarray(constraints.rhs, dtype=float)
        )

    equilibrium_residual_n = float(
        np.linalg.norm(
            np.nan_to_num(
                equilibrium_vector,
                nan=np.inf,
                posinf=np.inf,
                neginf=np.inf,
            )
        )
    )
    compatibility_residual = float(
        np.linalg.norm(
            np.nan_to_num(
                compatibility_vector,
                nan=np.inf,
                posinf=np.inf,
                neginf=np.inf,
            )
        )
    )
    force_closure_residual_n, moment_closure_residual_nm = _global_force_and_moment_closure(
        model=model,
        load_split=load_split,
        reactions=reactions,
    )
    condition_number = float(constraints.audit.scaled_condition_number)
    full_row_rank = bool(constraints.audit.full_row_rank)
    equilibrium_passed = bool(equilibrium_residual_n <= _EQUILIBRIUM_TOL_N)
    compatibility_passed = bool(compatibility_residual <= _COMPATIBILITY_TOL)
    force_closure_passed = bool(force_closure_residual_n <= _FORCE_CLOSURE_TOL_N)
    moment_closure_passed = bool(moment_closure_residual_nm <= _MOMENT_CLOSURE_TOL_NM)
    conditioning_passed = bool(
        full_row_rank
        and np.isfinite(condition_number)
        and condition_number <= _CONDITION_LIMIT
    )

    return NumericalConsistencyResult(
        equilibrium_residual_n=equilibrium_residual_n,
        compatibility_residual=compatibility_residual,
        force_closure_residual_n=force_closure_residual_n,
        moment_closure_residual_nm=moment_closure_residual_nm,
        scaled_constraint_condition_number=condition_number,
        raw_constraint_rows=int(constraints.audit.raw_row_count),
        active_constraint_rows=int(constraints.audit.active_row_count),
        removed_constraint_rows=int(constraints.audit.removed_row_count),
        full_row_rank=full_row_rank,
        equilibrium_passed=equilibrium_passed,
        compatibility_passed=compatibility_passed,
        force_closure_passed=force_closure_passed,
        moment_closure_passed=moment_closure_passed,
        conditioning_passed=conditioning_passed,
        passed=bool(
            full_row_rank
            and equilibrium_passed
            and compatibility_passed
            and force_closure_passed
            and moment_closure_passed
            and conditioning_passed
        ),
    )


def build_global_observable_readiness(
    *,
    report: ReportMetrics,
    reactions: ReactionRecoveryResult,
) -> GlobalObservableReadinessResult:
    """Check whether the run produced finite global observables for downstream gating."""

    report_arrays = (
        np.array(
            [
                report.tip_deflection_main_m,
                report.tip_deflection_rear_m,
                report.rear_main_tip_ratio,
                report.max_vertical_displacement_m,
                report.wire_reaction_total_n,
                report.link_force_max_n,
            ],
            dtype=float,
        ),
        np.asarray(report.root_reaction_main_n, dtype=float),
        np.asarray(report.root_reaction_rear_n, dtype=float),
    )
    reactions_arrays = (
        np.asarray(reactions.root_main_reaction_n, dtype=float),
        np.asarray(reactions.root_rear_reaction_n, dtype=float),
        np.asarray(reactions.wire_reactions_n, dtype=float),
        np.asarray(reactions.link_resultants_n, dtype=float),
        np.asarray(reactions.link_reaction_on_main_n, dtype=float),
        np.asarray(reactions.link_reaction_on_rear_n, dtype=float),
    )
    report_finite = bool(all(np.all(np.isfinite(values)) for values in report_arrays))
    reactions_finite = bool(all(np.all(np.isfinite(values)) for values in reactions_arrays))
    return GlobalObservableReadinessResult(
        report_finite=report_finite,
        reactions_finite=reactions_finite,
        passed=bool(report_finite and reactions_finite),
    )


def build_wire_support_validity(
    *,
    recovery: RecoveryResult,
) -> WireSupportValidityResult:
    """Check whether the simplified wire-support surrogate stayed tension-only."""

    wire_count = int(np.asarray(recovery.wire_tension_estimates_n, dtype=float).size)
    return WireSupportValidityResult(
        wire_count=wire_count,
        max_tension_n=float(recovery.max_wire_tension_n),
        max_allowable_tension_n=float(recovery.max_wire_allowable_tension_n),
        max_tension_utilization=float(recovery.max_wire_tension_utilization),
        max_precompression_n=float(recovery.max_wire_precompression_n),
        max_upward_reaction_n=float(recovery.max_wire_upward_reaction_n),
        tension_only_passed=bool(recovery.wire_tension_only_passed),
        tension_limit_passed=bool(recovery.wire_tension_limit_passed),
        passed=bool(recovery.wire_tension_only_passed and recovery.wire_tension_limit_passed),
    )


def build_optimizer_facing_metrics(
    *,
    model: DualBeamMainlineModel,
    smooth: SmoothAggregationResult,
    stiffness: np.ndarray,
    constraints: ConstraintAssemblyResult,
    multipliers: np.ndarray,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
    load_split: LoadSplitResult,
    reactions: ReactionRecoveryResult,
    report: ReportMetrics,
    recovery: RecoveryResult,
    explicit_wire_support=None,
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
        numerical_consistency=build_numerical_consistency_result(
            model=model,
            stiffness=stiffness,
            constraints=constraints,
            multipliers=multipliers,
            disp_main_m=disp_main_m,
            disp_rear_m=disp_rear_m,
            load_split=load_split,
            reactions=reactions,
            explicit_wire_support=explicit_wire_support,
        ),
        global_observables=build_global_observable_readiness(
            report=report,
            reactions=reactions,
        ),
        wire_support_validity=build_wire_support_validity(
            recovery=recovery,
        ),
    )


def build_feasibility_summary(
    *,
    optimizer_metrics: OptimizerFacingMetrics,
    analysis_succeeded: bool,
) -> FeasibilitySummary:
    """Build the Phase-2 evaluator status split used by future optimizers."""

    hard_failures: list[str] = []
    candidate_constraint_failures: list[str] = []
    legacy_reference_failures: list[str] = []

    if not analysis_succeeded:
        hard_failures.append("dual_beam_analysis")
    if not optimizer_metrics.geometry_validity.valid:
        hard_failures.append("geometry_validity")
    if not optimizer_metrics.numerical_consistency.full_row_rank:
        hard_failures.append("constraint_rank")
    if not optimizer_metrics.numerical_consistency.equilibrium_passed:
        hard_failures.append("equilibrium_residual")
    if not optimizer_metrics.numerical_consistency.compatibility_passed:
        hard_failures.append("constraint_compatibility")
    if not optimizer_metrics.numerical_consistency.force_closure_passed:
        hard_failures.append("force_closure")
    if not optimizer_metrics.numerical_consistency.moment_closure_passed:
        hard_failures.append("moment_closure")
    if not optimizer_metrics.numerical_consistency.conditioning_passed:
        hard_failures.append("constraint_conditioning")
    if not optimizer_metrics.global_observables.passed:
        hard_failures.append("global_observables")
    if not optimizer_metrics.wire_support_validity.passed:
        if not optimizer_metrics.wire_support_validity.tension_only_passed:
            hard_failures.append("wire_tension_only")
        if not optimizer_metrics.wire_support_validity.tension_limit_passed:
            hard_failures.append("wire_tension_limit")

    eq = optimizer_metrics.equivalent_gates
    if not eq.analysis_success:
        legacy_reference_failures.append("equivalent_analysis")
    if not eq.failure_passed:
        legacy_reference_failures.append("equivalent_failure")
    if not eq.buckling_passed:
        legacy_reference_failures.append("equivalent_buckling")
    if not eq.tip_passed:
        legacy_reference_failures.append("equivalent_tip_deflection")
    if not eq.twist_passed:
        legacy_reference_failures.append("equivalent_twist")

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
            "legacy_equivalent_reference",
        ),
        numerical_consistency_passed=bool(optimizer_metrics.numerical_consistency.passed),
        global_observables_passed=bool(optimizer_metrics.global_observables.passed),
        wire_support_validity_passed=bool(optimizer_metrics.wire_support_validity.passed),
        legacy_reference_passed=not legacy_reference_failures,
        legacy_reference_failures=tuple(legacy_reference_failures),
    )
