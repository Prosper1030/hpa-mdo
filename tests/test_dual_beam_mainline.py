from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from hpa_mdo.core import Aircraft, MaterialDB, load_config
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
    build_dual_beam_mainline_model,
    get_analysis_mode_definition,
    run_dual_beam_mainline_kernel,
)
from hpa_mdo.structure import SparOptimizer
from hpa_mdo.structure.dual_beam_mainline.constraints import build_constraint_assembly
from hpa_mdo.structure.dual_beam_mainline.load_split import (
    build_dual_beam_load_split,
    collapse_explicit_rear_weight_to_equivalent_my_n,
    convert_torque_to_main_spar_reference,
)
from hpa_mdo.structure.dual_beam_mainline.optimizer_view import (
    build_feasibility_summary,
    build_geometry_validity_margins,
    build_numerical_consistency_result,
    build_optimizer_facing_metrics,
)
from hpa_mdo.structure.dual_beam_mainline.builder import _wire_unstretched_lengths_from_pretension
from hpa_mdo.structure.dual_beam_mainline.recovery import recover_structural_response
from hpa_mdo.structure.dual_beam_mainline.recovery import build_report_metrics, recover_reactions
from hpa_mdo.structure.dual_beam_mainline.solver import solve_dual_beam_state
from hpa_mdo.structure.dual_beam_mainline.smooth import build_default_smooth_scales
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report
from scripts.direct_dual_beam_inverse_design import (
    BaselineDesign,
    build_reduced_map_config,
    design_from_reduced_variables,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _simple_model(
    *,
    lift_per_span_npm: np.ndarray | None = None,
    torque_per_span_nmpm: np.ndarray | None = None,
    main_mass_per_length_kgpm: np.ndarray | None = None,
    rear_mass_per_length_kgpm: np.ndarray | None = None,
    joint_node_indices: tuple[int, ...] = (1,),
    wire_node_indices: tuple[int, ...] = (),
    wire_attachment_angles_deg: tuple[float, ...] | None = None,
    wire_anchor_points_m: np.ndarray | None = None,
    torque_input: TorqueInputDefinition | None = None,
    wire_unstretched_lengths_m: np.ndarray | None = None,
    wire_allowable_tension_n: np.ndarray | None = None,
) -> DualBeamMainlineModel:
    y_nodes_m = np.array([0.0, 1.0, 2.0], dtype=float)
    nodes_main_m = np.column_stack((np.zeros(3), y_nodes_m, np.zeros(3)))
    nodes_rear_m = np.column_stack((np.ones(3), y_nodes_m, np.zeros(3)))
    spar_offset_vectors_m = nodes_rear_m - nodes_main_m
    spar_separation_nodes_m = spar_offset_vectors_m[:, 0]
    nn = y_nodes_m.size
    ne = nn - 1
    resolved_wire_angles_deg = (
        tuple(float(value) for value in wire_attachment_angles_deg)
        if wire_attachment_angles_deg is not None
        else tuple(45.0 for _ in wire_node_indices)
    )
    resolved_wire_anchor_points_m = (
        np.asarray(wire_anchor_points_m, dtype=float)
        if wire_anchor_points_m is not None
        else np.asarray(
            [
                [
                    float(nodes_main_m[node_index, 0]),
                    0.0,
                    float(
                        nodes_main_m[node_index, 2]
                        - y_nodes_m[node_index] * np.tan(np.deg2rad(angle_deg))
                    ),
                ]
                for node_index, angle_deg in zip(wire_node_indices, resolved_wire_angles_deg, strict=True)
            ],
            dtype=float,
        )
        if wire_node_indices
        else np.zeros((0, 3), dtype=float)
    )
    wire_area_m2 = (
        np.full(len(wire_node_indices), np.pi * (0.5 * 2.0e-3) ** 2, dtype=float)
        if wire_node_indices
        else np.zeros(0, dtype=float)
    )
    wire_young_pa = (
        np.full(len(wire_node_indices), 70.0e9, dtype=float)
        if wire_node_indices
        else np.zeros(0, dtype=float)
    )
    resolved_wire_allowable_tension_n = (
        np.asarray(wire_allowable_tension_n, dtype=float)
        if wire_allowable_tension_n is not None
        else np.full(len(wire_node_indices), 1.0e9, dtype=float)
        if wire_node_indices
        else np.zeros(0, dtype=float)
    )
    wire_reference_lengths_m = (
        np.linalg.norm(nodes_main_m[list(wire_node_indices)] - resolved_wire_anchor_points_m, axis=1)
        if wire_node_indices
        else np.zeros(0, dtype=float)
    )
    resolved_wire_unstretched_lengths_m = (
        np.asarray(wire_unstretched_lengths_m, dtype=float)
        if wire_unstretched_lengths_m is not None
        else wire_reference_lengths_m.copy()
    )

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
        wire_attachment_angles_deg=resolved_wire_angles_deg,
        wire_anchor_points_m=resolved_wire_anchor_points_m,
        wire_area_m2=wire_area_m2,
        wire_young_pa=wire_young_pa,
        wire_allowable_tension_n=resolved_wire_allowable_tension_n,
        wire_reference_lengths_m=wire_reference_lengths_m,
        wire_unstretched_lengths_m=resolved_wire_unstretched_lengths_m,
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


_TRACK_S_RERUN_Z = np.array(
    [1.0, 0.999999500019976, 0.9999997444012075, 1.0, 0.04630959736295326],
    dtype=float,
)
# Replay-derived structural export loads from the Track S seed-22/off rerun path.
_TRACK_S_EXPORT_LIFT_PER_SPAN_NPM = np.fromstring(
    """
    0 60.061978767027561 60.005527691372023 59.971567676423106 59.941560224438305
    59.914978092776281 59.889403277619564 59.865203225685612 59.842063335777972
    59.81828498043307 59.793623140446478 59.763030152115959 59.716751143746052
    59.668898169325146 59.610440474542116 59.551982779759086 59.360375542443762
    59.165962010440289 58.936096450655725 58.694511344190204 58.465505077547597
    58.238534260722304 58.064928353409805 57.932093946807129 57.876053658283766
    57.93271459434537 58.142119814045067 58.793164924294359 59.511192255210204
    60.809187920853155 61.950483042599565 63.346237106760334 64.707422735229002
    66.04730451762542 67.348041760070345 68.481543470531875 69.519816647270588
    70.066582645077204 70.205795065920114 69.988649620355758 69.278475282130188
    68.461905388855342 67.406791351780271 66.310620742380848 65.017821184610966
    63.720616586620146 62.238174772852368 60.757186229418913 58.876850237112201
    56.920346766918819 54.654604810804386 52.242614753332127 49.635882787033246
    46.902283900445362 43.985927422298381 40.866420703793708 37.734762913004253
    34.511790995324361 0 0
    """,
    sep=" ",
    dtype=float,
)
_TRACK_S_EXPORT_TORQUE_PER_SPAN_NMPM = np.fromstring(
    """
    0 -27.317166572746856 -27.303031572977314 -27.299679075499096 -27.298508097097649
    -27.301391047686685 -27.307026080673481 -27.311215012484528 -27.314288769313187
    -27.318007221846958 -27.322617780234495 -27.324065816910128 -27.317149979328821
    -27.309439654051875 -27.296376405287187 -27.283313156522496 -27.17658382659635
    -27.067005152877922 -26.907159010911457 -26.731283390872335 -26.570423775824374
    -26.411377533588574 -26.276986981628419 -26.159670781902651 -26.095061130029695
    -26.107727884588883 -26.261152352174623 -26.821337027857865 -27.435102800281193
    -28.573720568276048 -29.474225189870314 -30.567458990396876 -31.60376316586234
    -32.623584175612024 -33.587854614548924 -34.421646811444106 -35.166597866627576
    -35.517280700194675 -35.539829794474905 -35.299627253497214 -34.710813348654924
    -34.069518171977585 -33.348466902469816 -32.599773937026818 -31.808092200200843
    -30.997157117944539 -30.114339843619973 -29.219535794905475 -28.09751448712688
    -26.902505245185598 -25.593311403973715 -24.16844423270771 -22.680023325322651
    -21.136403845799578 -19.574915882617528 -18.008769104449147 -16.103166516146295
    -13.632754788170425 0 0
    """,
    sep=" ",
    dtype=float,
)


def _build_track_s_rerun_snapshot_model() -> DualBeamMainlineModel:
    """Rebuild the captured Track S rerun snapshot without rerunning VSPAero in tests."""

    config_path = REPO_ROOT / "configs/blackcat_004.yaml"
    design_report = REPO_ROOT / "output/blackcat_004/ansys/crossval_report.txt"

    cfg = load_config(config_path)
    specimen_metrics = parse_baseline_metrics(design_report)
    cfg.solver.n_beam_nodes = int(specimen_metrics.nodes_per_spar)
    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    baseline_result = build_specimen_result_from_crossval_report(design_report)
    design_case = cfg.structural_load_cases()[0]

    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
    map_config = build_reduced_map_config(
        baseline=baseline_design,
        cfg=cfg,
        main_plateau_scale_upper=1.14,
        main_taper_fill_upper=0.80,
        rear_radius_scale_upper=1.12,
    )
    main_t, main_r, rear_t, rear_r = design_from_reduced_variables(
        baseline=baseline_design,
        z=_TRACK_S_RERUN_Z,
        map_config=map_config,
    )

    export_loads = {
        "y": aircraft.wing.y.copy(),
        "lift_per_span": _TRACK_S_EXPORT_LIFT_PER_SPAN_NPM.copy(),
        "drag_per_span": np.zeros_like(_TRACK_S_EXPORT_LIFT_PER_SPAN_NPM),
        "torque_per_span": _TRACK_S_EXPORT_TORQUE_PER_SPAN_NMPM.copy(),
        "total_lift": float(
            np.trapezoid(_TRACK_S_EXPORT_LIFT_PER_SPAN_NPM, np.asarray(aircraft.wing.y, dtype=float))
        ),
    }
    mapped_loads = {
        key: (
            value / float(design_case.aero_scale)
            if key in {"lift_per_span", "drag_per_span", "torque_per_span", "total_lift"}
            else value
        )
        for key, value in export_loads.items()
    }
    optimizer = SparOptimizer(
        cfg=cfg,
        aircraft=aircraft,
        aero_loads=mapped_loads,
        materials_db=materials_db,
    )
    eq_result = optimizer.analyze(
        main_t_seg=main_t,
        main_r_seg=main_r,
        rear_t_seg=rear_t,
        rear_r_seg=rear_r,
    )
    return build_dual_beam_mainline_model(
        cfg=cfg,
        aircraft=aircraft,
        opt_result=eq_result,
        export_loads=export_loads,
        materials_db=materials_db,
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
    assert production.wire_bc == WireBCMode.WIRE_MAIN_TRUSS
    assert production.default_link_mode == LinkMode.JOINT_ONLY_OFFSET_RIGID
    assert LinkMode.DENSE_FINITE_RIB not in production.allowed_link_modes
    assert robustness.ownership.aerodynamic_torque == "main_beam_my_about_main_spar"
    assert robustness.wire_bc == WireBCMode.WIRE_MAIN_TRUSS
    assert robustness.default_link_mode == LinkMode.JOINT_ONLY_OFFSET_RIGID
    assert robustness.ownership.hardware_mass_structural_loads == "report_only"
    assert LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY in robustness.allowed_link_modes
    assert LinkMode.DENSE_FINITE_RIB in robustness.allowed_link_modes


def test_explicit_wire_truss_converges_for_track_s_rerun_snapshot() -> None:
    model = _build_track_s_rerun_snapshot_model()

    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
    )

    assert result.feasibility.analysis_succeeded is True
    assert result.recovery.max_wire_tension_n > 0.0
    assert np.isfinite(result.report.tip_deflection_main_m)
    assert np.isfinite(result.report.tip_deflection_rear_m)


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
    cable_axis = -result.reactions.wire_reaction_vectors_n[0]
    cable_axis = cable_axis / np.linalg.norm(cable_axis)
    np.testing.assert_allclose(
        result.recovery.wire_tension_estimates_n[0],
        np.linalg.norm(result.reactions.wire_reaction_vectors_n[0]),
        rtol=1.0e-10,
        atol=1.0e-10,
    )
    np.testing.assert_allclose(
        result.recovery.wire_precompression_n,
        np.array([result.recovery.wire_tension_estimates_n[0] * abs(cable_axis[1]), 0.0]),
        rtol=1.0e-10,
        atol=1.0e-10,
    )


def test_wire_axial_mode_constrains_displacement_along_cable_axis() -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, 0.0, 40.0]),
        joint_node_indices=(1,),
        wire_node_indices=(1,),
        wire_attachment_angles_deg=(45.0,),
    )
    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
        wire_bc=WireBCMode.WIRE_MAIN_AXIAL,
    )

    cable_axis = model.nodes_main_m[1] - model.wire_anchor_points_m[0]
    cable_axis = cable_axis / np.linalg.norm(cable_axis)
    assert np.dot(result.disp_main_m[1, :3], cable_axis) == pytest.approx(0.0, abs=1.0e-10)
    assert result.reactions.wire_resultants_n.shape == (1,)
    assert result.reactions.wire_resultants_n[0] > 0.0
    assert result.recovery.wire_tension_only_passed is True


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


def test_dense_finite_rib_surrogate_keeps_translation_closure_but_allows_rotation_slip() -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, 0.0, 40.0]),
        joint_node_indices=(1,),
    )
    rigid = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_ROBUSTNESS,
        link_mode=LinkMode.DENSE_OFFSET_RIGID,
    )
    finite = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_ROBUSTNESS,
        link_mode=LinkMode.DENSE_FINITE_RIB,
    )

    offset_vector_m = model.spar_offset_vectors_m[1]
    avg_theta = 0.5 * (finite.disp_main_m[1, 3:] + finite.disp_rear_m[1, 3:])
    translation_residual = (
        finite.disp_rear_m[1, :3]
        - finite.disp_main_m[1, :3]
        + _skew(offset_vector_m) @ avg_theta
    )
    rotation_slip = finite.disp_rear_m[1, 3:] - finite.disp_main_m[1, 3:]

    np.testing.assert_allclose(translation_residual, 0.0, atol=1.0e-10)
    assert np.linalg.norm(rotation_slip) > 1.0e-6
    np.testing.assert_allclose(
        rigid.disp_rear_m[1, 3:] - rigid.disp_main_m[1, 3:],
        0.0,
        atol=1.0e-10,
    )
    assert not np.isclose(
        finite.report.tip_deflection_rear_m,
        rigid.report.tip_deflection_rear_m,
        atol=1.0e-6,
    )


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


def test_constraint_assembly_exposes_dense_finite_rib_surrogate_rows() -> None:
    model = _simple_model()
    constraint_mode = DualBeamConstraintMode(
        root_bc=RootBCMode.ROOT_FIXED_BOTH,
        wire_bc=None,
        link_mode=LinkMode.DENSE_FINITE_RIB,
    )
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)

    assert constraints.link_node_indices == (1,)
    assert len(constraints.link_row_slices) == 1
    assert constraints.link_row_slices[0].stop - constraints.link_row_slices[0].start == 3


def test_constraint_assembly_skips_wire_rows_for_explicit_truss_mode() -> None:
    model = _simple_model(wire_node_indices=(2,))
    constraint_mode = DualBeamConstraintMode(
        root_bc=RootBCMode.ROOT_FIXED_BOTH,
        wire_bc=WireBCMode.WIRE_MAIN_TRUSS,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
    )
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)

    assert constraints.wire_slice.stop - constraints.wire_slice.start == 0


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
    assert result.optimizer.numerical_consistency.force_closure_passed is True
    assert result.optimizer.numerical_consistency.moment_closure_passed is True
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
    disp_main_m, disp_rear_m, multipliers, stiffness, explicit_wire_support = solve_dual_beam_state(
        model=model,
        main_loads_n=load_split.main_loads_n,
        rear_loads_n=load_split.rear_loads_n,
        constraints=constraints,
    )
    reactions = recover_reactions(
        constraints=constraints,
        multipliers=multipliers,
        nn=model.y_nodes_m.size,
        explicit_wire_support=explicit_wire_support,
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
        explicit_wire_support=explicit_wire_support,
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


def test_numerical_consistency_detects_force_closure_violation_from_tampered_reaction() -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, 12.0, 30.0]),
        joint_node_indices=(1,),
        wire_node_indices=(1,),
    )
    production = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_PRODUCTION)
    constraint_mode = DualBeamConstraintMode(
        root_bc=production.root_bc,
        wire_bc=production.wire_bc,
        link_mode=production.default_link_mode,
    )
    load_split = build_dual_beam_load_split(model=model, mode_definition=production)
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)
    disp_main_m, disp_rear_m, multipliers, stiffness, explicit_wire_support = solve_dual_beam_state(
        model=model,
        main_loads_n=load_split.main_loads_n,
        rear_loads_n=load_split.rear_loads_n,
        constraints=constraints,
    )
    reactions = recover_reactions(
        constraints=constraints,
        multipliers=multipliers,
        nn=model.y_nodes_m.size,
        explicit_wire_support=explicit_wire_support,
    )

    baseline = build_numerical_consistency_result(
        model=model,
        stiffness=stiffness,
        constraints=constraints,
        multipliers=multipliers,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        load_split=load_split,
        reactions=reactions,
    )
    assert baseline.force_closure_passed is True
    assert baseline.moment_closure_passed is True

    tampered = copy.deepcopy(reactions)
    tampered.total_constraint_reaction_vector_n[2] += 1.0
    violated = build_numerical_consistency_result(
        model=model,
        stiffness=stiffness,
        constraints=constraints,
        multipliers=multipliers,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        load_split=load_split,
        reactions=tampered,
    )
    assert violated.force_closure_passed is False
    assert violated.passed is False


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
        wire_bc=WireBCMode.WIRE_MAIN_VERTICAL,
    )

    assert result.reactions.wire_reactions_n[0] > 0.0
    assert result.recovery.wire_tension_only_passed is False
    assert result.feasibility.wire_support_validity_passed is False
    assert "wire_tension_only" in result.feasibility.hard_failures
    assert result.feasibility.overall_hard_feasible is False


def test_explicit_wire_truss_slacks_under_downward_load_without_hard_failure() -> None:
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

    np.testing.assert_allclose(result.reactions.wire_resultants_n, 0.0, atol=1.0e-12)
    np.testing.assert_allclose(result.reactions.wire_reaction_vectors_n, 0.0, atol=1.0e-12)
    assert result.recovery.wire_tension_only_passed is True
    assert result.feasibility.wire_support_validity_passed is True
    assert "wire_tension_only" not in result.feasibility.hard_failures


def test_explicit_wire_truss_uses_unstretched_length_to_apply_installed_pretension() -> None:
    wire_area_m2 = np.array([np.pi * (0.5 * 2.0e-3) ** 2], dtype=float)
    wire_young_pa = np.array([70.0e9], dtype=float)
    reference_length_m = np.array([1.0], dtype=float)
    target_pretension_n = np.array([250.0], dtype=float)
    wire_unstretched_lengths_m = _wire_unstretched_lengths_from_pretension(
        reference_lengths_m=reference_length_m,
        area_m2=wire_area_m2,
        young_pa=wire_young_pa,
        pretension_n=target_pretension_n,
    )
    model = _simple_model(
        joint_node_indices=(1,),
        wire_node_indices=(0,),
        wire_attachment_angles_deg=(45.0,),
        wire_anchor_points_m=np.array([[0.0, 0.0, -1.0]], dtype=float),
        wire_unstretched_lengths_m=wire_unstretched_lengths_m,
    )

    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
    )

    assert result.reactions.wire_resultants_n[0] == pytest.approx(target_pretension_n[0], rel=1.0e-9)
    assert result.recovery.wire_tension_estimates_n[0] == pytest.approx(target_pretension_n[0], rel=1.0e-9)
    assert result.recovery.wire_tension_only_passed is True


def test_wire_tension_limit_is_a_hard_gate_when_explicit_truss_exceeds_allowable() -> None:
    wire_area_m2 = np.array([np.pi * (0.5 * 2.0e-3) ** 2], dtype=float)
    wire_young_pa = np.array([70.0e9], dtype=float)
    reference_length_m = np.array([1.0], dtype=float)
    target_pretension_n = np.array([250.0], dtype=float)
    wire_unstretched_lengths_m = _wire_unstretched_lengths_from_pretension(
        reference_lengths_m=reference_length_m,
        area_m2=wire_area_m2,
        young_pa=wire_young_pa,
        pretension_n=target_pretension_n,
    )
    model = _simple_model(
        joint_node_indices=(1,),
        wire_node_indices=(0,),
        wire_attachment_angles_deg=(45.0,),
        wire_anchor_points_m=np.array([[0.0, 0.0, -1.0]], dtype=float),
        wire_unstretched_lengths_m=wire_unstretched_lengths_m,
        wire_allowable_tension_n=np.array([200.0], dtype=float),
    )

    result = run_dual_beam_mainline_kernel(
        model=model,
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
        link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
    )

    assert result.recovery.max_wire_tension_n > result.recovery.max_wire_allowable_tension_n
    assert result.recovery.max_wire_tension_utilization > 1.0
    assert result.recovery.wire_tension_limit_passed is False
    assert result.feasibility.wire_support_validity_passed is False
    assert "wire_tension_limit" in result.feasibility.hard_failures


def test_explicit_wire_truss_reaction_aligns_with_current_cable_axis_under_x_load() -> None:
    model = _simple_model(
        joint_node_indices=(1,),
        wire_node_indices=(1,),
        wire_attachment_angles_deg=(45.0,),
    )
    production = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_PRODUCTION)
    constraint_mode = DualBeamConstraintMode(
        root_bc=production.root_bc,
        wire_bc=production.wire_bc,
        link_mode=production.default_link_mode,
    )
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)
    main_loads_n = np.zeros((model.y_nodes_m.size, 6), dtype=float)
    rear_loads_n = np.zeros_like(main_loads_n)
    main_loads_n[1, 0] = 150.0

    disp_main_m, _, multipliers, _, explicit_wire_support = solve_dual_beam_state(
        model=model,
        main_loads_n=main_loads_n,
        rear_loads_n=rear_loads_n,
        constraints=constraints,
    )
    reactions = recover_reactions(
        constraints=constraints,
        multipliers=multipliers,
        nn=model.y_nodes_m.size,
        explicit_wire_support=explicit_wire_support,
    )

    current_axis = model.nodes_main_m[1] + disp_main_m[1, :3] - model.wire_anchor_points_m[0]
    current_axis = current_axis / np.linalg.norm(current_axis)
    reaction_axis = reactions.wire_reaction_vectors_n[0] / np.linalg.norm(reactions.wire_reaction_vectors_n[0])
    np.testing.assert_allclose(reaction_axis, -current_axis, atol=1.0e-8)


def test_explicit_wire_truss_recovery_uses_deformed_axis_for_precompression() -> None:
    model = _simple_model(
        joint_node_indices=(1,),
        wire_node_indices=(1,),
        wire_attachment_angles_deg=(45.0,),
    )
    production = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_PRODUCTION)
    constraint_mode = DualBeamConstraintMode(
        root_bc=production.root_bc,
        wire_bc=production.wire_bc,
        link_mode=production.default_link_mode,
    )
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)
    main_loads_n = np.zeros((model.y_nodes_m.size, 6), dtype=float)
    rear_loads_n = np.zeros_like(main_loads_n)
    main_loads_n[1, 0] = 150.0

    disp_main_m, disp_rear_m, multipliers, _, explicit_wire_support = solve_dual_beam_state(
        model=model,
        main_loads_n=main_loads_n,
        rear_loads_n=rear_loads_n,
        constraints=constraints,
    )
    reactions = recover_reactions(
        constraints=constraints,
        multipliers=multipliers,
        nn=model.y_nodes_m.size,
        explicit_wire_support=explicit_wire_support,
    )
    recovery = recover_structural_response(
        model=model,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        reactions=reactions,
        explicit_wire_support=explicit_wire_support,
    )

    current_axis = model.nodes_main_m[1] + disp_main_m[1, :3] - model.wire_anchor_points_m[0]
    current_axis = current_axis / np.linalg.norm(current_axis)
    expected_precompression_n = recovery.wire_tension_estimates_n[0] * abs(current_axis[1])
    assert recovery.wire_precompression_n[0] == pytest.approx(expected_precompression_n, rel=1.0e-10)


def test_explicit_wire_truss_flags_upward_reaction_for_anchor_above_attachment() -> None:
    model = _simple_model(
        joint_node_indices=(1,),
        wire_node_indices=(1,),
        wire_attachment_angles_deg=(45.0,),
        wire_anchor_points_m=np.array([[0.0, 0.0, 1.0]], dtype=float),
    )
    production = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_PRODUCTION)
    constraint_mode = DualBeamConstraintMode(
        root_bc=production.root_bc,
        wire_bc=production.wire_bc,
        link_mode=production.default_link_mode,
    )
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)
    main_loads_n = np.zeros((model.y_nodes_m.size, 6), dtype=float)
    rear_loads_n = np.zeros_like(main_loads_n)
    main_loads_n[1, 2] = -150.0

    disp_main_m, disp_rear_m, multipliers, _, explicit_wire_support = solve_dual_beam_state(
        model=model,
        main_loads_n=main_loads_n,
        rear_loads_n=rear_loads_n,
        constraints=constraints,
    )
    reactions = recover_reactions(
        constraints=constraints,
        multipliers=multipliers,
        nn=model.y_nodes_m.size,
        explicit_wire_support=explicit_wire_support,
    )
    recovery = recover_structural_response(
        model=model,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        reactions=reactions,
        explicit_wire_support=explicit_wire_support,
    )

    assert recovery.max_wire_upward_reaction_n > 0.0
    assert recovery.wire_tension_only_passed is False


def test_wire_axial_mode_flags_compression_resultant_as_invalid() -> None:
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
        wire_bc=WireBCMode.WIRE_MAIN_AXIAL,
    )

    assert result.reactions.wire_resultants_n[0] < 0.0
    assert result.recovery.wire_tension_only_passed is False
    assert result.feasibility.wire_support_validity_passed is False
    assert "wire_tension_only" in result.feasibility.hard_failures


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
