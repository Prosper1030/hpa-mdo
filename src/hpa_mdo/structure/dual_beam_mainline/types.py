"""Shared types for the dual-beam mainline analysis kernel."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class AnalysisModeName(str, Enum):
    """Named structural analysis modes with fixed load/BC ownership."""

    EQUIVALENT_VALIDATION = "equivalent_validation"
    DUAL_SPAR_ANSYS_PARITY = "dual_spar_ansys_parity"
    DUAL_BEAM_PRODUCTION = "dual_beam_production"
    DUAL_BEAM_ROBUSTNESS = "dual_beam_robustness"


class RootBCMode(str, Enum):
    """Supported root boundary-condition modes."""

    ROOT_FIXED_BOTH = "root_fixed_both"
    ROOT_MAIN_FIXED_REAR_LINKED = "root_main_fixed_rear_linked"


class WireBCMode(str, Enum):
    """Supported lift-wire boundary-condition modes."""

    WIRE_MAIN_VERTICAL = "wire_main_vertical"
    WIRE_MAIN_AXIAL = "wire_main_axial"


class LinkMode(str, Enum):
    """Supported main↔rear spar link modes."""

    JOINT_ONLY_EQUAL_DOF_PARITY = "joint_only_equal_dof_parity"
    JOINT_ONLY_OFFSET_RIGID = "joint_only_offset_rigid"
    DENSE_OFFSET_RIGID = "dense_offset_rigid"
    DENSE_FINITE_RIB = "dense_finite_rib"


class TorqueReferenceMode(str, Enum):
    """Reference used for the aerodynamic torque input."""

    ABOUT_MAIN_SPAR = "about_main_spar"
    ABOUT_REFERENCE = "about_reference"


class BeamLine(str, Enum):
    """Explicit beam-line identifiers."""

    MAIN = "main"
    REAR = "rear"


@dataclass(frozen=True)
class AnalysisOwnership:
    """Mode-specific ownership matrix for loads and BCs."""

    lift: str
    aerodynamic_torque: str
    main_spar_self_weight: str
    rear_spar_self_weight: str
    rear_gravity_torque: str
    hardware_mass_structural_loads: str


@dataclass(frozen=True)
class AnalysisModeDefinition:
    """Fixed configuration for a named structural analysis mode."""

    mode: AnalysisModeName
    description: str
    ownership: AnalysisOwnership
    root_bc: RootBCMode
    wire_bc: WireBCMode | None
    default_link_mode: LinkMode | None
    allowed_link_modes: tuple[LinkMode, ...]
    analysis_family: str


@dataclass(frozen=True)
class TorqueInputDefinition:
    """Single torque conversion rule for the aerodynamic input."""

    reference_mode: TorqueReferenceMode = TorqueReferenceMode.ABOUT_MAIN_SPAR
    reference_x_nodes_m: np.ndarray | None = None
    center_of_pressure_x_nodes_m: np.ndarray | None = None
    sign_convention: str = (
        "positive torque_per_span about the span axis produces +Fz on main and -Fz on rear"
    )


@dataclass(frozen=True)
class DualBeamConstraintMode:
    """Constraint-mode selection for a dual-beam solve."""

    root_bc: RootBCMode
    wire_bc: WireBCMode | None
    link_mode: LinkMode


@dataclass
class DualBeamMainlineModel:
    """All geometry, section, mass, and loading inputs for one dual-beam run."""

    y_nodes_m: np.ndarray
    node_spacings_m: np.ndarray
    element_lengths_m: np.ndarray
    main_t_seg_m: np.ndarray
    main_r_seg_m: np.ndarray
    rear_t_seg_m: np.ndarray
    rear_r_seg_m: np.ndarray
    nodes_main_m: np.ndarray
    nodes_rear_m: np.ndarray
    spar_offset_vectors_m: np.ndarray
    spar_separation_nodes_m: np.ndarray
    main_area_m2: np.ndarray
    main_iy_m4: np.ndarray
    main_iz_m4: np.ndarray
    main_j_m4: np.ndarray
    rear_area_m2: np.ndarray
    rear_iy_m4: np.ndarray
    rear_iz_m4: np.ndarray
    rear_j_m4: np.ndarray
    main_radius_elem_m: np.ndarray
    rear_radius_elem_m: np.ndarray
    main_mass_per_length_kgpm: np.ndarray
    rear_mass_per_length_kgpm: np.ndarray
    main_young_pa: np.ndarray | float
    main_shear_pa: np.ndarray | float
    rear_young_pa: np.ndarray | float
    rear_shear_pa: np.ndarray | float
    main_density_kgpm3: np.ndarray | float
    rear_density_kgpm3: np.ndarray | float
    main_allowable_stress_pa: np.ndarray | float
    rear_allowable_stress_pa: np.ndarray | float
    lift_per_span_npm: np.ndarray
    torque_per_span_nmpm: np.ndarray
    torque_input: TorqueInputDefinition
    gravity_scale: float
    max_tip_deflection_limit_m: float | None
    max_thickness_step_m: float
    max_thickness_to_radius_ratio: float
    main_spar_dominance_margin_m: float
    rear_main_radius_ratio_min: float
    main_spar_ei_ratio: float
    rear_min_inner_radius_m: float
    rear_inboard_span_m: float
    rear_inboard_ei_to_main_ratio_max: float
    joint_node_indices: tuple[int, ...]
    dense_link_node_indices: tuple[int, ...]
    wire_node_indices: tuple[int, ...]
    joint_mass_half_kg: float
    fitting_mass_half_kg: float
    equivalent_analysis_success: bool
    equivalent_failure_index: float
    equivalent_buckling_index: float
    equivalent_tip_deflection_m: float
    equivalent_tip_deflection_limit_m: float | None
    equivalent_twist_max_deg: float
    equivalent_twist_limit_deg: float | None


@dataclass
class LoadSplitResult:
    """Explicit main/rear nodal loads and their ownership breakdown."""

    mode_definition: AnalysisModeDefinition
    main_loads_n: np.ndarray
    rear_loads_n: np.ndarray
    lift_main_fz_n: np.ndarray
    lift_rear_fz_n: np.ndarray
    torque_main_fz_n: np.ndarray
    torque_rear_fz_n: np.ndarray
    torque_main_my_n: np.ndarray
    torque_rear_my_n: np.ndarray
    main_self_weight_fz_n: np.ndarray
    rear_self_weight_fz_n: np.ndarray
    rear_gravity_torque_my_n: np.ndarray
    torque_about_main_per_span_nmpm: np.ndarray
    total_applied_fz_n: float


@dataclass
class ConstraintAuditResult:
    """Rank/scaling audit for the assembled constraint matrix."""

    raw_row_count: int
    active_row_count: int
    removed_row_count: int
    raw_rank: int
    active_rank: int
    scaled_condition_number: float
    full_row_rank: bool
    kept_row_indices: tuple[int, ...]
    removed_row_indices: tuple[int, ...]


@dataclass
class ConstraintAssemblyResult:
    """Exact-constraint assembly and bookkeeping for reaction recovery."""

    matrix: np.ndarray
    rhs: np.ndarray
    scaled_matrix: np.ndarray
    scaled_rhs: np.ndarray
    row_scale_factors: np.ndarray
    root_main_slice: slice
    root_rear_slice: slice
    wire_slice: slice
    link_row_slices: tuple[slice, ...]
    link_node_indices: tuple[int, ...]
    wire_node_indices: tuple[int, ...]
    constraint_mode: DualBeamConstraintMode
    audit: ConstraintAuditResult


@dataclass
class ReactionRecoveryResult:
    """Recovered reactions and link resultants from the multiplier solution."""

    multipliers: np.ndarray
    total_constraint_reaction_vector_n: np.ndarray
    root_main_reaction_n: np.ndarray
    root_rear_reaction_n: np.ndarray
    wire_reactions_n: np.ndarray
    wire_node_indices: tuple[int, ...]
    link_resultants_n: np.ndarray
    link_reaction_on_main_n: np.ndarray
    link_reaction_on_rear_n: np.ndarray
    link_node_indices: tuple[int, ...]


@dataclass
class RecoveryResult:
    """Element-level recovery fields used for reporting."""

    vm_main_pa: np.ndarray
    vm_rear_pa: np.ndarray
    max_vm_main_pa: float
    max_vm_rear_pa: float
    failure_index: float
    spar_tube_mass_half_kg: float
    spar_tube_mass_full_kg: float
    joint_mass_half_kg: float
    joint_mass_full_kg: float
    fitting_mass_half_kg: float
    fitting_mass_full_kg: float
    total_structural_mass_full_kg: float


@dataclass
class SmoothScaleConfig:
    """Run-constant scales for future optimizer-facing smooth quantities."""

    u_scale_m: float
    lambda_scale_n: float
    eps_abs_u_m: float = 1.0e-6
    eps_norm_n: float = 1.0
    rho_u: float = 75.0
    rho_lambda: float = 50.0


@dataclass
class SmoothAggregationResult:
    """Smooth diagnostic quantities kept separate from raw report metrics."""

    u_scale_m: float
    lambda_scale_n: float
    psi_u_all_m: float
    psi_u_rear_m: float
    psi_u_rear_outboard_m: float
    psi_link_n: float


@dataclass
class GeometryValidityMargins:
    """Optimizer-facing geometry and manufacturability margin summary."""

    main_thickness_ratio_margin_min_m: float
    rear_thickness_ratio_margin_min_m: float
    main_hollow_margin_min_m: float
    rear_hollow_margin_min_m: float
    main_radius_taper_margin_min_m: float
    rear_radius_taper_margin_min_m: float
    main_thickness_step_margin_min_m: float
    rear_thickness_step_margin_min_m: float
    radius_dominance_margin_min_m: float
    rear_main_radius_ratio_margin_min_m: float
    ei_dominance_margin_min_nm2: float
    ei_ratio_margin_min: float
    rear_inboard_ei_margin_min_nm2: float
    valid: bool


@dataclass
class EquivalentGateResult:
    """Validated equivalent-beam gate values kept available beside the new dual path."""

    analysis_success: bool
    failure_index: float
    failure_margin: float
    failure_passed: bool
    buckling_index: float
    buckling_margin: float
    buckling_passed: bool
    tip_deflection_m: float
    tip_limit_m: float | None
    tip_margin_m: float
    tip_passed: bool
    twist_max_deg: float
    twist_limit_deg: float | None
    twist_margin_deg: float
    twist_passed: bool


@dataclass
class NumericalConsistencyResult:
    """Numerical-consistency diagnostics for the explicit dual-beam solve."""

    equilibrium_residual_n: float
    compatibility_residual: float
    scaled_constraint_condition_number: float
    raw_constraint_rows: int
    active_constraint_rows: int
    removed_constraint_rows: int
    full_row_rank: bool
    equilibrium_passed: bool
    compatibility_passed: bool
    conditioning_passed: bool
    passed: bool


@dataclass
class GlobalObservableReadinessResult:
    """Whether the run produced finite global observables usable for downstream checks."""

    report_finite: bool
    reactions_finite: bool
    passed: bool


@dataclass
class OptimizerFacingMetrics:
    """Smooth quantities and validated gates exposed to future optimizers."""

    psi_u_all_m: float
    psi_u_rear_m: float
    psi_u_rear_outboard_m: float
    dual_displacement_limit_m: float | None
    dual_displacement_margin_m: float
    geometry_validity: GeometryValidityMargins
    equivalent_gates: EquivalentGateResult
    numerical_consistency: NumericalConsistencyResult
    global_observables: GlobalObservableReadinessResult


@dataclass
class FeasibilitySummary:
    """Phase-2 evaluator summary with hard-fail and candidate-only splits."""

    analysis_succeeded: bool
    geometry_validity_succeeded: bool
    dual_displacement_candidate_passed: bool
    equivalent_failure_passed: bool
    equivalent_buckling_passed: bool
    equivalent_tip_passed: bool
    equivalent_twist_passed: bool
    overall_hard_feasible: bool
    overall_optimizer_candidate_feasible: bool
    hard_failures: tuple[str, ...]
    candidate_constraint_failures: tuple[str, ...]
    report_only_channels: tuple[str, ...]
    numerical_consistency_passed: bool = True
    global_observables_passed: bool = True
    legacy_reference_passed: bool = True
    legacy_reference_failures: tuple[str, ...] = ()


@dataclass
class ReportMetrics:
    """Raw engineering report quantities."""

    tip_deflection_main_m: float
    tip_deflection_rear_m: float
    rear_main_tip_ratio: float
    max_vertical_displacement_m: float
    max_vertical_spar: str
    max_vertical_node: int
    root_reaction_main_n: np.ndarray
    root_reaction_rear_n: np.ndarray
    wire_reaction_total_n: float
    link_force_max_n: float
    link_force_hotspot_node: int | None


@dataclass
class DualBeamMainlineResult:
    """High-level outputs for one mainline dual-beam analysis run."""

    mode_definition: AnalysisModeDefinition
    constraint_mode: DualBeamConstraintMode
    disp_main_m: np.ndarray
    disp_rear_m: np.ndarray
    load_split: LoadSplitResult
    reactions: ReactionRecoveryResult
    recovery: RecoveryResult
    smooth: SmoothAggregationResult
    optimizer: OptimizerFacingMetrics
    feasibility: FeasibilitySummary
    report: ReportMetrics


_MODE_DEFINITIONS = {
    AnalysisModeName.EQUIVALENT_VALIDATION: AnalysisModeDefinition(
        mode=AnalysisModeName.EQUIVALENT_VALIDATION,
        description="Single equivalent beam validation gate retained for Phase I parity.",
        ownership=AnalysisOwnership(
            lift="equivalent_beam_fz",
            aerodynamic_torque="equivalent_beam_my",
            main_spar_self_weight="equivalent_beam_fz",
            rear_spar_self_weight="equivalent_beam_fz",
            rear_gravity_torque="equivalent_beam_my",
            hardware_mass_structural_loads="report_only",
        ),
        root_bc=RootBCMode.ROOT_FIXED_BOTH,
        wire_bc=WireBCMode.WIRE_MAIN_VERTICAL,
        default_link_mode=None,
        allowed_link_modes=(),
        analysis_family="equivalent",
    ),
    AnalysisModeName.DUAL_SPAR_ANSYS_PARITY: AnalysisModeDefinition(
        mode=AnalysisModeName.DUAL_SPAR_ANSYS_PARITY,
        description="Two-spar ANSYS parity mode with equal-DOF links and no explicit spar self-weight.",
        ownership=AnalysisOwnership(
            lift="main_beam_fz",
            aerodynamic_torque="main_rear_vertical_couple_about_main_spar",
            main_spar_self_weight="disabled",
            rear_spar_self_weight="disabled",
            rear_gravity_torque="disabled",
            hardware_mass_structural_loads="report_only",
        ),
        root_bc=RootBCMode.ROOT_FIXED_BOTH,
        wire_bc=WireBCMode.WIRE_MAIN_VERTICAL,
        default_link_mode=LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY,
        allowed_link_modes=(LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY,),
        analysis_family="dual_beam",
    ),
    AnalysisModeName.DUAL_BEAM_PRODUCTION: AnalysisModeDefinition(
        mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
        description="Physics-first production analysis mode with explicit spar-line self-weight.",
        ownership=AnalysisOwnership(
            lift="main_beam_fz",
            aerodynamic_torque="main_beam_my_about_main_spar",
            main_spar_self_weight="main_beam_fz",
            rear_spar_self_weight="rear_beam_fz",
            rear_gravity_torque="disabled_explicit_dual_beam",
            hardware_mass_structural_loads="report_only",
        ),
        root_bc=RootBCMode.ROOT_FIXED_BOTH,
        wire_bc=WireBCMode.WIRE_MAIN_VERTICAL,
        default_link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
        allowed_link_modes=(
            LinkMode.JOINT_ONLY_OFFSET_RIGID,
            LinkMode.DENSE_OFFSET_RIGID,
            LinkMode.DENSE_FINITE_RIB,
        ),
        analysis_family="dual_beam",
    ),
    AnalysisModeName.DUAL_BEAM_ROBUSTNESS: AnalysisModeDefinition(
        mode=AnalysisModeName.DUAL_BEAM_ROBUSTNESS,
        description="Production load ownership rerun across non-default link modes for topology sensitivity.",
        ownership=AnalysisOwnership(
            lift="main_beam_fz",
            aerodynamic_torque="main_beam_my_about_main_spar",
            main_spar_self_weight="main_beam_fz",
            rear_spar_self_weight="rear_beam_fz",
            rear_gravity_torque="disabled_explicit_dual_beam",
            hardware_mass_structural_loads="report_only",
        ),
        root_bc=RootBCMode.ROOT_FIXED_BOTH,
        wire_bc=WireBCMode.WIRE_MAIN_VERTICAL,
        default_link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
        allowed_link_modes=(
            LinkMode.JOINT_ONLY_EQUAL_DOF_PARITY,
            LinkMode.JOINT_ONLY_OFFSET_RIGID,
            LinkMode.DENSE_OFFSET_RIGID,
            LinkMode.DENSE_FINITE_RIB,
        ),
        analysis_family="dual_beam",
    ),
}


def get_analysis_mode_definition(mode: AnalysisModeName | str) -> AnalysisModeDefinition:
    """Return the fixed definition for a named structural mode."""

    if not isinstance(mode, AnalysisModeName):
        mode = AnalysisModeName(str(mode))
    return _MODE_DEFINITIONS[mode]
