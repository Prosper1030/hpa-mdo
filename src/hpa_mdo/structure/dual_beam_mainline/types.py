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
    main_young_pa: float
    main_shear_pa: float
    rear_young_pa: float
    rear_shear_pa: float
    main_density_kgpm3: float
    rear_density_kgpm3: float
    main_allowable_stress_pa: float
    rear_allowable_stress_pa: float
    lift_per_span_npm: np.ndarray
    torque_per_span_nmpm: np.ndarray
    torque_input: TorqueInputDefinition
    gravity_scale: float
    max_tip_deflection_limit_m: float | None
    joint_node_indices: tuple[int, ...]
    dense_link_node_indices: tuple[int, ...]
    wire_node_indices: tuple[int, ...]
    joint_mass_half_kg: float
    fitting_mass_half_kg: float


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
    main_self_weight_fz_n: np.ndarray
    rear_self_weight_fz_n: np.ndarray
    rear_gravity_torque_my_n: np.ndarray
    torque_about_main_per_span_nmpm: np.ndarray
    total_applied_fz_n: float


@dataclass
class ConstraintAssemblyResult:
    """Exact-constraint assembly and bookkeeping for reaction recovery."""

    matrix: np.ndarray
    rhs: np.ndarray
    root_main_slice: slice
    root_rear_slice: slice
    wire_slice: slice
    link_row_slices: tuple[slice, ...]
    link_node_indices: tuple[int, ...]
    wire_node_indices: tuple[int, ...]
    constraint_mode: DualBeamConstraintMode


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
class ReportMetrics:
    """Raw engineering report quantities."""

    tip_deflection_main_m: float
    tip_deflection_rear_m: float
    max_vertical_displacement_m: float
    max_vertical_spar: str
    max_vertical_node: int
    root_reaction_main_n: np.ndarray
    root_reaction_rear_n: np.ndarray
    wire_reaction_total_n: float
    link_force_max_n: float


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
            aerodynamic_torque="main_rear_vertical_couple_about_main_spar",
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
            aerodynamic_torque="main_rear_vertical_couple_about_main_spar",
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
