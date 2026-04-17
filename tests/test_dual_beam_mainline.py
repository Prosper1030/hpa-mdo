from __future__ import annotations

import numpy as np
import pytest

from hpa_mdo.structure.dual_beam_mainline import (
    AnalysisModeName,
    DualBeamConstraintMode,
    DualBeamMainlineModel,
    LinkMode,
    RootBCMode,
    SmoothAggregationResult,
    TorqueInputDefinition,
    TorqueReferenceMode,
    WireBCMode,
    get_analysis_mode_definition,
    run_dual_beam_mainline_kernel,
)
from hpa_mdo.structure.dual_beam_mainline.constraints import build_constraint_assembly
from hpa_mdo.structure.dual_beam_mainline.load_split import (
    build_dual_beam_load_split,
    collapse_explicit_rear_weight_to_equivalent_my_n,
    convert_torque_to_main_spar_reference,
)
from hpa_mdo.structure.dual_beam_mainline.optimizer_view import (
    build_feasibility_summary,
    build_geometry_validity_margins,
    build_optimizer_facing_metrics,
)
from hpa_mdo.structure.dual_beam_mainline.recovery import recover_structural_response
from hpa_mdo.structure.dual_beam_mainline.recovery import build_report_metrics, recover_reactions
from hpa_mdo.structure.dual_beam_mainline.solver import solve_dual_beam_state
from hpa_mdo.structure.dual_beam_mainline.smooth import build_default_smooth_scales


def _simple_model(
    *,
    lift_per_span_npm: np.ndarray | None = None,
    torque_per_span_nmpm: np.ndarray | None = None,
    main_mass_per_length_kgpm: np.ndarray | None = None,
    rear_mass_per_length_kgpm: np.ndarray | None = None,
    joint_node_indices: tuple[int, ...] = (1,),
    wire_node_indices: tuple[int, ...] = (),
    wire_attachment_angles_deg: tuple[float, ...] | None = None,
    torque_input: TorqueInputDefinition | None = None,
) -> DualBeamMainlineModel:
    y_nodes_m = np.array([0.0, 1.0, 2.0], dtype=float)
    nodes_main_m = np.column_stack((np.zeros(3), y_nodes_m, np.zeros(3)))
    nodes_rear_m = np.column_stack((np.ones(3), y_nodes_m, np.zeros(3)))
    spar_offset_vectors_m = nodes_rear_m - nodes_main_m
    spar_separation_nodes_m = spar_offset_vectors_m[:, 0]
    nn = y_nodes_m.size
    ne = nn - 1

    return DualBeamMainlineModel(
        y_nodes_m=y_nodes_m,
        node_spacings_m=np.array([0.5, 1.0, 0.5], dtype=float),
        element_lengths_m=np.array([1.0, 1.0], dtype=float),
        main_t_seg_m=np.array([0.0020, 0.0018], dtype=float),
        main_r_seg_m=np.array([0.0400, 0.0360], dtype=float),
        rear_t_seg_m=np.array([0.0014, 0.0012], dtype=float),
        rear_r_seg_m=np.array([0.0240, 0.0220], dtype=float),
        nodes_main_m=nodes_main_m,
        nodes_rear_m=nodes_rear_m,
        spar_offset_vectors_m=spar_offset_vectors_m,
        spar_separation_nodes_m=spar_separation_nodes_m,
        main_area_m2=np.full(ne, 1.0e-3),
        main_iy_m4=np.full(ne, 1.8e-6),
        main_iz_m4=np.full(ne, 1.8e-6),
        main_j_m4=np.full(ne, 3.6e-6),
        rear_area_m2=np.full(ne, 1.0e-3),
        rear_iy_m4=np.full(ne, 2.5e-7),
        rear_iz_m4=np.full(ne, 2.5e-7),
        rear_j_m4=np.full(ne, 5.0e-7),
        main_radius_elem_m=np.full(ne, 0.04),
        rear_radius_elem_m=np.full(ne, 0.04),
        main_mass_per_length_kgpm=np.full(ne, 0.5)
        if main_mass_per_length_kgpm is None
        else np.asarray(main_mass_per_length_kgpm, dtype=float),
        rear_mass_per_length_kgpm=np.full(ne, 0.4)
        if rear_mass_per_length_kgpm is None
        else np.asarray(rear_mass_per_length_kgpm, dtype=float),
        main_young_pa=70.0e9,
        main_shear_pa=27.0e9,
        rear_young_pa=70.0e9,
        rear_shear_pa=27.0e9,
        main_density_kgpm3=1600.0,
        rear_density_kgpm3=1600.0,
        main_allowable_stress_pa=400.0e6,
        rear_allowable_stress_pa=400.0e6,
        lift_per_span_npm=np.zeros(nn) if lift_per_span_npm is None else np.asarray(lift_per_span_npm, dtype=float),
        torque_per_span_nmpm=np.zeros(nn)
        if torque_per_span_nmpm is None
        else np.asarray(torque_per_span_nmpm, dtype=float),
        torque_input=torque_input or TorqueInputDefinition(),
        gravity_scale=1.0,
        max_tip_deflection_limit_m=2.5,
        max_thickness_step_m=0.003,
        max_thickness_to_radius_ratio=0.8,
        main_spar_dominance_margin_m=0.005,
        rear_main_radius_ratio_min=0.0,
        main_spar_ei_ratio=2.0,
        rear_min_inner_radius_m=1.0e-4,
        rear_inboard_span_m=1.5,
        rear_inboard_ei_to_main_ratio_max=0.20,
        joint_node_indices=joint_node_indices,
        dense_link_node_indices=tuple(range(1, nn - 1)),
        wire_node_indices=wire_node_indices,
        wire_attachment_angles_deg=(
            tuple(float(value) for value in wire_attachment_angles_deg)
            if wire_attachment_angles_deg is not None
            else tuple(45.0 for _ in wire_node_indices)
        ),
        joint_mass_half_kg=0.2,
        fitting_mass_half_kg=0.0,
        equivalent_analysis_success=True,
        equivalent_failure_index=-0.20,
        equivalent_buckling_index=-0.30,
        equivalent_tip_deflection_m=1.2,
        equivalent_tip_deflection_limit_m=2.5,
        equivalent_twist_max_deg=0.8,
        equivalent_twist_limit_deg=2.0,
    )


def _skew(offset_m: np.ndarray) -> np.ndarray:
    dx, dy, dz = offset_m
    return np.array(
        [
            [0.0, -dz, dy],
            [dz, 0.0, -dx],
            [-dy, dx, 0.0],
        ]
    )


def test_mode_matrix_freezes_reviewer_required_load_and_bc_ownership() -> None:
    equivalent = get_analysis_mode_definition(AnalysisModeName.EQUIVALENT_VALIDATION)
    parity = get_analysis_mode_definition(AnalysisModeName.DUAL_SPAR_ANSYS_PARITY)
    production = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_PRODUCTION)
    robustness = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_ROBUSTNESS)

    assert equivalent.ownership.rear_gravity_torque == "equivalent_beam_my"
    assert parity.ownership.main_spar_self_weight == "disabled"
    assert parity.ownership.rear_spar_self_weight == "disabled"
    assert parity.ownership.rear_gravity_torque == "disabled"
    assert parity.ownership.aerodynamic_torque == "main_rear_vertical_couple_about_main_spar"
    assert production.ownership.main_spar_self_weight == "main_beam_fz"
    assert production.ownership.rear_spar_self_weight == "rear_beam_fz"
    assert production.ownership.rear_gravity_torque == "disabled_explicit_dual_beam"
    assert production.ownership.aerodynamic_torque == "main_beam_my_about_main_spar"
    assert production.default_link_mode == LinkMode.JOINT_ONLY_OFFSET_RIGID
    assert robustness.ownership.aerodynamic_torque == "main_beam_my_about_main_spar"
    assert robustness.default_link_mode == LinkMode.JOINT_ONLY_OFFSET_RIGID
    assert robustness.ownership.hardware_mass_structural_loads == "report_only"
    assert LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY in robustness.allowed_link_modes


def test_torque_conversion_and_dual_beam_torque_path_uses_mode_owned_representation() -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, 10.0, 0.0]),
        torque_per_span_nmpm=np.array([0.0, 4.0, 0.0]),
        main_mass_per_length_kgpm=np.zeros(2),
        rear_mass_per_length_kgpm=np.zeros(2),
    )
    parity = get_analysis_mode_definition(AnalysisModeName.DUAL_SPAR_ANSYS_PARITY)
    production = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_PRODUCTION)
    parity_load_split = build_dual_beam_load_split(model=model, mode_definition=parity)
    load_split = build_dual_beam_load_split(model=model, mode_definition=production)

    np.testing.assert_allclose(parity_load_split.torque_main_fz_n, np.array([0.0, 4.0, 0.0]))
    np.testing.assert_allclose(parity_load_split.torque_rear_fz_n, np.array([0.0, -4.0, 0.0]))
    np.testing.assert_allclose(parity_load_split.torque_main_my_n, 0.0)
    np.testing.assert_allclose(parity_load_split.main_loads_n[:, 2], np.array([0.0, 14.0, 0.0]))
    np.testing.assert_allclose(parity_load_split.rear_loads_n[:, 2], np.array([0.0, -4.0, 0.0]))
    np.testing.assert_allclose(parity_load_split.main_loads_n[:, 4], 0.0)

    np.testing.assert_allclose(load_split.lift_main_fz_n, np.array([0.0, 10.0, 0.0]))
    np.testing.assert_allclose(load_split.torque_main_fz_n, 0.0)
    np.testing.assert_allclose(load_split.torque_rear_fz_n, 0.0)
    np.testing.assert_allclose(load_split.torque_main_my_n, np.array([0.0, 4.0, 0.0]))
    np.testing.assert_allclose(load_split.torque_rear_my_n, 0.0)
    np.testing.assert_allclose(load_split.main_loads_n[:, 2], np.array([0.0, 10.0, 0.0]))
    np.testing.assert_allclose(load_split.rear_loads_n[:, 2], np.array([0.0, 0.0, 0.0]))
    np.testing.assert_allclose(load_split.main_loads_n[:, 4], np.array([0.0, 4.0, 0.0]))
    np.testing.assert_allclose(load_split.rear_loads_n[:, 4], 0.0)

    converted = convert_torque_to_main_spar_reference(
        lift_per_span_npm=np.array([10.0]),
        torque_per_span_nmpm=np.array([6.0]),
        main_spar_x_nodes_m=np.array([0.0]),
        torque_input=TorqueInputDefinition(
            reference_mode=TorqueReferenceMode.ABOUT_REFERENCE,
            reference_x_nodes_m=np.array([0.2]),
            center_of_pressure_x_nodes_m=np.array([0.3]),
        ),
    )
    np.testing.assert_allclose(converted, np.array([3.0]))


def test_parity_mode_keeps_production_self_weight_out_and_production_does_not_double_count_rear_gravity() -> None:
    model = _simple_model(
        main_mass_per_length_kgpm=np.array([0.5, 0.5]),
        rear_mass_per_length_kgpm=np.array([0.4, 0.4]),
    )
    parity = get_analysis_mode_definition(AnalysisModeName.DUAL_SPAR_ANSYS_PARITY)
    production = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_PRODUCTION)

    parity_loads = build_dual_beam_load_split(model=model, mode_definition=parity)
    production_loads = build_dual_beam_load_split(model=model, mode_definition=production)

    np.testing.assert_allclose(parity_loads.main_self_weight_fz_n, 0.0)
    np.testing.assert_allclose(parity_loads.rear_self_weight_fz_n, 0.0)
    np.testing.assert_allclose(production_loads.main_loads_n[:, 4], 0.0)
    np.testing.assert_allclose(production_loads.rear_loads_n[:, 4], 0.0)
    np.testing.assert_allclose(production_loads.rear_gravity_torque_my_n, 0.0)
    assert np.min(production_loads.main_self_weight_fz_n) < 0.0
    assert np.min(production_loads.rear_self_weight_fz_n) < 0.0

    spar_separation_elem_m = np.full(model.element_lengths_m.size, 1.0)
    collapsed_my = collapse_explicit_rear_weight_to_equivalent_my_n(
        rear_mass_per_length_kgpm=model.rear_mass_per_length_kgpm,
        spar_separation_elem_m=spar_separation_elem_m,
        element_lengths_m=model.element_lengths_m,
        gravity_scale=model.gravity_scale,
    )
    assert np.min(collapsed_my) < 0.0
    np.testing.assert_allclose(
        np.sum(production_loads.rear_self_weight_fz_n),
        -np.sum(model.rear_mass_per_length_kgpm * 9.80665 * model.element_lengths_m),
    )


def test_exact_reaction_recovery_balances_root_and_wire_constraints() -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, 12.0, 30.0]),
        joint_node_indices=(1,),
        wire_node_indices=(1,),
    )
    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
    )

    total_vertical_reaction = (
        result.reactions.root_main_reaction_n[2]
        + result.reactions.root_rear_reaction_n[2]
        + result.report.wire_reaction_total_n
    )
    assert np.isfinite(total_vertical_reaction)
    np.testing.assert_allclose(
        total_vertical_reaction + result.load_split.total_applied_fz_n,
        0.0,
        atol=1.0e-8,
    )
    assert result.reactions.link_resultants_n.shape == (1, 6)


def test_wire_recovery_estimates_tension_and_inboard_precompression_from_downward_reaction() -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, 12.0, 30.0]),
        joint_node_indices=(1,),
        wire_node_indices=(1,),
        wire_attachment_angles_deg=(45.0,),
    )
    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
    )

    assert result.recovery.wire_tension_only_passed is True
    assert result.recovery.max_wire_tension_n > 0.0
    assert result.recovery.max_wire_precompression_n > 0.0
    np.testing.assert_allclose(
        result.recovery.wire_tension_estimates_n[0],
        -result.reactions.wire_reactions_n[0] / np.sin(np.deg2rad(45.0)),
        rtol=1.0e-10,
        atol=1.0e-10,
    )
    np.testing.assert_allclose(
        result.recovery.wire_precompression_n,
        np.array([-result.reactions.wire_reactions_n[0], 0.0]),
        rtol=1.0e-10,
        atol=1.0e-10,
    )


def test_link_mode_constraints_are_enforced_with_mode_specific_kinematics() -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, 0.0, 40.0]),
        joint_node_indices=(1,),
    )
    parity = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_SPAR_ANSYS_PARITY,
    )
    offset = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
    )

    np.testing.assert_allclose(
        parity.disp_rear_m[1] - parity.disp_main_m[1],
        0.0,
        atol=1.0e-10,
    )

    offset_vector_m = model.spar_offset_vectors_m[1]
    avg_theta = 0.5 * (offset.disp_main_m[1, 3:] + offset.disp_rear_m[1, 3:])
    translation_residual = (
        offset.disp_rear_m[1, :3]
        - offset.disp_main_m[1, :3]
        + _skew(offset_vector_m) @ avg_theta
    )
    rotation_residual = offset.disp_rear_m[1, 3:] - offset.disp_main_m[1, 3:]
    np.testing.assert_allclose(translation_residual, 0.0, atol=1.0e-10)
    np.testing.assert_allclose(rotation_residual, 0.0, atol=1.0e-10)


def test_constraint_assembly_exposes_explicit_boundary_groups() -> None:
    model = _simple_model(wire_node_indices=(2,))
    constraint_mode = DualBeamConstraintMode(
        root_bc=RootBCMode.ROOT_FIXED_BOTH,
        wire_bc=WireBCMode.WIRE_MAIN_VERTICAL,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
    )
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)

    assert constraints.root_main_slice.stop - constraints.root_main_slice.start == 6
    assert constraints.root_rear_slice.stop - constraints.root_rear_slice.start == 6
    assert constraints.wire_slice.stop - constraints.wire_slice.start == 1
    assert len(constraints.link_row_slices) == 1
    assert constraints.link_row_slices[0].stop - constraints.link_row_slices[0].start == 6


def test_constraint_assembly_prunes_redundant_root_link_rows_and_scales_active_rows() -> None:
    model = _simple_model(joint_node_indices=(0, 1))
    constraint_mode = DualBeamConstraintMode(
        root_bc=RootBCMode.ROOT_FIXED_BOTH,
        wire_bc=None,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
    )

    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)

    assert constraints.audit.raw_row_count == 24
    assert constraints.audit.removed_row_count == 6
    assert constraints.audit.active_row_count == 18
    assert constraints.audit.full_row_rank is True
    assert constraints.link_row_slices[0].stop - constraints.link_row_slices[0].start == 0
    assert constraints.link_row_slices[1].stop - constraints.link_row_slices[1].start == 6
    np.testing.assert_allclose(
        np.linalg.norm(constraints.scaled_matrix, axis=1),
        1.0,
        atol=1.0e-12,
    )
    np.testing.assert_allclose(
        constraints.scaled_rhs,
        constraints.rhs * constraints.row_scale_factors,
        atol=1.0e-12,
    )


def test_phase2_optimizer_metrics_keep_raw_report_channels_separate() -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, 18.0, 36.0]),
        joint_node_indices=(1,),
        wire_node_indices=(1,),
    )
    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
    )

    assert result.optimizer.psi_u_all_m >= abs(result.report.max_vertical_displacement_m)
    assert result.optimizer.psi_u_rear_m >= abs(result.report.tip_deflection_rear_m)
    assert result.optimizer.psi_u_rear_outboard_m >= abs(result.report.tip_deflection_rear_m)
    assert result.report.rear_main_tip_ratio == pytest.approx(
        abs(result.report.tip_deflection_rear_m)
        / max(abs(result.report.tip_deflection_main_m), 1.0e-12)
    )
    assert result.report.link_force_hotspot_node == 2
    assert result.feasibility.overall_hard_feasible is True
    assert result.feasibility.overall_optimizer_candidate_feasible is True
    with pytest.raises(AttributeError):
        _ = result.optimizer.rear_main_tip_ratio


def test_default_smooth_scale_is_run_constant_and_limit_anchored() -> None:
    model_a = _simple_model(
        lift_per_span_npm=np.array([0.0, 5.0, 10.0]),
    )
    model_b = _simple_model(
        lift_per_span_npm=np.array([0.0, 50.0, 100.0]),
    )

    scales_a = build_default_smooth_scales(model_a)
    scales_b = build_default_smooth_scales(model_b)

    assert scales_a.u_scale_m == pytest.approx(2.5)
    assert scales_b.u_scale_m == pytest.approx(2.5)
    assert scales_a.lambda_scale_n == pytest.approx(scales_b.lambda_scale_n)


def test_feasibility_summary_keeps_dual_displacement_as_candidate_only() -> None:
    model = _simple_model()
    production = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_PRODUCTION)
    constraint_mode = DualBeamConstraintMode(
        root_bc=production.root_bc,
        wire_bc=production.wire_bc,
        link_mode=production.default_link_mode,
    )
    load_split = build_dual_beam_load_split(model=model, mode_definition=production)
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)
    disp_main_m, disp_rear_m, multipliers, stiffness = solve_dual_beam_state(
        model=model,
        main_loads_n=load_split.main_loads_n,
        rear_loads_n=load_split.rear_loads_n,
        constraints=constraints,
    )
    reactions = recover_reactions(
        constraints=constraints,
        multipliers=multipliers,
        nn=model.y_nodes_m.size,
    )
    report = build_report_metrics(
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        reactions=reactions,
    )
    recovery = recover_structural_response(
        model=model,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        reactions=reactions,
    )
    optimizer_metrics = build_optimizer_facing_metrics(
        model=model,
        smooth=SmoothAggregationResult(
            u_scale_m=2.5,
            lambda_scale_n=1.0,
            psi_u_all_m=2.8,
            psi_u_rear_m=2.7,
            psi_u_rear_outboard_m=2.6,
            psi_link_n=120.0,
        ),
        stiffness=stiffness,
        constraints=constraints,
        multipliers=multipliers,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        load_split=load_split,
        reactions=reactions,
        report=report,
        recovery=recovery,
    )
    feasibility = build_feasibility_summary(
        optimizer_metrics=optimizer_metrics,
        analysis_succeeded=True,
    )

    assert feasibility.overall_hard_feasible is True
    assert feasibility.dual_displacement_candidate_passed is False
    assert feasibility.overall_optimizer_candidate_feasible is False
    assert feasibility.hard_failures == ()
    assert feasibility.candidate_constraint_failures == ("dual_displacement_candidate",)
    assert feasibility.numerical_consistency_passed is True
    assert feasibility.global_observables_passed is True
    assert feasibility.wire_support_validity_passed is True
    assert feasibility.legacy_reference_passed is True


def test_equivalent_gates_are_legacy_reference_only_for_dual_beam_feasibility() -> None:
    model = _simple_model()
    model.equivalent_analysis_success = False
    model.equivalent_failure_index = 0.25
    model.equivalent_buckling_index = 0.35
    model.equivalent_tip_deflection_m = 9.0
    model.equivalent_twist_max_deg = 9.0

    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
    )

    assert result.feasibility.overall_hard_feasible is True
    assert result.feasibility.overall_optimizer_candidate_feasible is True
    assert result.feasibility.hard_failures == ()
    assert result.feasibility.legacy_reference_passed is False
    assert result.feasibility.legacy_reference_failures == (
        "equivalent_analysis",
        "equivalent_failure",
        "equivalent_buckling",
        "equivalent_tip_deflection",
        "equivalent_twist",
    )


def test_wire_tension_only_violation_is_a_hard_gate_when_support_reaction_turns_upward() -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, -10.0, -20.0]),
        joint_node_indices=(1,),
        wire_node_indices=(1,),
        wire_attachment_angles_deg=(45.0,),
    )

    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
    )

    assert result.reactions.wire_reactions_n[0] > 0.0
    assert result.recovery.wire_tension_only_passed is False
    assert result.feasibility.wire_support_validity_passed is False
    assert "wire_tension_only" in result.feasibility.hard_failures
    assert result.feasibility.overall_hard_feasible is False


def test_geometry_validity_margins_flag_invalid_ratio_or_taper() -> None:
    model = _simple_model()
    model.main_t_seg_m = np.array([0.050, 0.001], dtype=float)
    model.main_r_seg_m = np.array([0.040, 0.041], dtype=float)

    margins = build_geometry_validity_margins(model)

    assert margins.valid is False
    assert margins.main_thickness_ratio_margin_min_m < 0.0
    assert margins.main_radius_taper_margin_min_m < 0.0


def test_kernel_accepts_elementwise_material_arrays_and_uses_local_stiffness() -> None:
    baseline = _simple_model(
        lift_per_span_npm=np.array([0.0, 0.0, 40.0]),
        joint_node_indices=(1,),
    )
    stiffened = _simple_model(
        lift_per_span_npm=np.array([0.0, 0.0, 40.0]),
        joint_node_indices=(1,),
    )
    stiffened.main_young_pa = np.array([70.0e9, 140.0e9], dtype=float)
    stiffened.main_shear_pa = np.array([27.0e9, 54.0e9], dtype=float)
    stiffened.rear_young_pa = np.array([70.0e9, 140.0e9], dtype=float)
    stiffened.rear_shear_pa = np.array([27.0e9, 54.0e9], dtype=float)

    baseline_result = run_dual_beam_mainline_kernel(
        model=baseline,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
    )
    stiffened_result = run_dual_beam_mainline_kernel(
        model=stiffened,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
    )

    assert abs(stiffened_result.report.tip_deflection_main_m) < abs(baseline_result.report.tip_deflection_main_m)
    assert stiffened_result.optimizer.psi_u_all_m < baseline_result.optimizer.psi_u_all_m


def test_recovery_uses_elementwise_allowables_for_failure_index() -> None:
    model = _simple_model()
    model.main_allowable_stress_pa = np.array([1.0e12, 1.0e6], dtype=float)
    disp_main = np.zeros((3, 6), dtype=float)
    disp_rear = np.zeros((3, 6), dtype=float)
    disp_main[2, 3] = 0.02

    recovery = recover_structural_response(
        model=model,
        disp_main_m=disp_main,
        disp_rear_m=disp_rear,
    )

    assert recovery.max_vm_main_pa > 0.0
    assert recovery.failure_index > 0.0
