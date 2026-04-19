"""Centralized configuration management for HPA-MDO v2.

Schema mirrors configs/blackcat_004.yaml exactly.
All engineering constants are read from YAML, with an optional local
overlay file for per-machine path differences.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


_LOCAL_PATHS_FILENAME = "local_paths.yaml"
_EXTERNAL_IO_FIELDS = ("vsp_model", "vsp_lod", "vsp_polar", "airfoil_dir")
_INTERNAL_IO_FIELDS = ("output_dir", "training_db")


class LoadCaseConfig(BaseModel):
    name: str
    aero_scale: float = Field(1.0, description="Scale factor on aerodynamic loads")
    nz: float = Field(1.0, description="Gravity/inertial scale factor in g")
    velocity: Optional[float] = Field(None, description="Flight speed [m/s]")
    air_density: Optional[float] = Field(None, description="Air density [kg/m^3]")
    max_tip_deflection_m: Optional[float] = Field(
        None, description="Optional per-case deflection constraint override [m]"
    )
    max_twist_deg: Optional[float] = Field(
        None, description="Optional per-case twist constraint override [deg]"
    )

    @property
    def gravity_scale(self) -> float:
        return self.nz


# ── Sub-configs ─────────────────────────────────────────────────────────────


class FlightConfig(BaseModel):
    velocity: float = Field(..., description="Cruise TAS [m/s]")
    altitude: float = Field(0.0)
    air_density: float = Field(1.225, description="[kg/m³]")
    kinematic_viscosity: float = Field(1.46e-5)
    cases: List[LoadCaseConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_case_defaults(self) -> FlightConfig:
        for case in self.cases:
            if case.velocity is None:
                case.velocity = self.velocity
            if case.air_density is None:
                case.air_density = self.air_density
        return self


class SafetyConfig(BaseModel):
    aerodynamic_load_factor: float = Field(2.0, description="Limit load [G]")
    material_safety_factor: float = Field(1.5, description="Knock-down on UTS")
    ks_rho_stress: float = Field(
        100.0, description="KS aggregation sharpness for stress constraint"
    )
    ks_rho_buckling: float = Field(
        50.0, description="KS aggregation sharpness for buckling constraint"
    )
    ks_rho_twist: float = Field(100.0, description="KS aggregation sharpness for twist constraint")
    shell_buckling_knockdown: float = Field(
        default=0.65,
        description="NASA SP-8007 knockdown factor for CF tube shell buckling",
        ge=0.1,
        le=1.0,
    )
    shell_buckling_bending_enhancement: float = Field(
        default=1.3,
        description="Enhancement factor for pure bending vs pure axial",
        ge=1.0,
        le=2.0,
    )
    dual_spar_warping_knockdown: float = Field(
        default=1.0,
        description=(
            "Reduction factor on the rigid-rib dual-spar torsional coupling term "
            "(1.0 = fully rigid ribs). Can also be derived from rib.* when the "
            "legacy scalar is omitted."
        ),
        ge=0.0,
        le=1.0,
    )


class WeightConfig(BaseModel):
    airframe_kg: float
    pilot_kg: float
    max_takeoff_kg: float

    @property
    def operating_kg(self) -> float:
        return self.airframe_kg + self.pilot_kg


class WingConfig(BaseModel):
    span: float
    root_chord: float
    tip_chord: float
    dihedral_schedule: Optional[List[List[float]]] = Field(
        None,
        description=(
            "Optional half-wing dihedral schedule as [[y_m, z_m], ...]. "
            "When provided, VSP builders reconstruct segment dihedral from this "
            "piecewise-linear z(y) curve instead of the legacy root/tip ramp."
        ),
    )
    dihedral_root_deg: float = 0.0
    dihedral_tip_deg: float = 6.0
    dihedral_scaling_exponent: float = Field(
        1.0,
        description=(
            "Progressive dihedral scaling exponent "
            "(0=uniform, 1=linear root-to-tip ramp, 2=quadratic ramp)"
        ),
        ge=0.0,
    )
    spar_location_xc: float = 0.25
    airfoil_root: str = "fx76mp140"
    airfoil_tip: str = "clarkysm"
    airfoil_root_tc: float = Field(0.140, description="Root airfoil max t/c")
    airfoil_tip_tc: float = Field(0.117, description="Tip airfoil max t/c")
    max_tip_twist_deg: float = Field(2.0, description="Torsion constraint [deg]")
    max_tip_deflection_m: Optional[float] = Field(
        None, description="Max allowable tip deflection [m]"
    )

    @model_validator(mode="after")
    def validate_dihedral_schedule(self) -> WingConfig:
        if not self.dihedral_schedule:
            return self

        half_span = 0.5 * float(self.span)
        prev_y = -math.inf
        for idx, pair in enumerate(self.dihedral_schedule):
            if len(pair) != 2:
                raise ValueError("wing.dihedral_schedule entries must be [y_m, z_m].")
            y_m = float(pair[0])
            if y_m < prev_y - 1.0e-9:
                raise ValueError("wing.dihedral_schedule y stations must be non-decreasing.")
            if y_m < -1.0e-9 or y_m > half_span + 1.0e-9:
                raise ValueError(
                    f"wing.dihedral_schedule y={y_m:.6f} lies outside [0, span/2={half_span:.6f}]."
                )
            if idx == 0 and abs(y_m) > 1.0e-9:
                raise ValueError("wing.dihedral_schedule must start at y=0.0.")
            prev_y = y_m

        if abs(float(self.dihedral_schedule[-1][0]) - half_span) > 1.0e-6:
            raise ValueError("wing.dihedral_schedule must end at wing.span/2.")

        return self


class LiftingSurfaceConfig(BaseModel):
    enabled: bool = True
    name: str
    x_location: float
    y_location: float = 0.0
    z_location: float = 0.0
    span: float = Field(..., gt=0.0, description="Full span or vertical extent [m]")
    root_chord: float = Field(..., gt=0.0)
    tip_chord: float = Field(..., gt=0.0)
    airfoil: str
    incidence_deg: float = 0.0
    x_rotation_deg: float = 0.0
    y_rotation_deg: float = 0.0
    z_rotation_deg: float = 0.0
    symmetry: Literal["xz", "none"] = "none"
    control_surface_name: Optional[str] = None
    control_surface_limit_deg: Optional[float] = Field(None, ge=0.0)


class HorizontalTailConfig(LiftingSurfaceConfig):
    name: str = "Elevator"
    airfoil: str = "NACA 0009"
    symmetry: Literal["xz", "none"] = "xz"
    control_surface_name: Optional[str] = "elevator"
    control_surface_limit_deg: Optional[float] = Field(20.0, ge=0.0)


class VerticalFinConfig(LiftingSurfaceConfig):
    name: str = "Fin"
    airfoil: str = "NACA 0009"
    x_rotation_deg: float = 90.0
    symmetry: Literal["xz", "none"] = "none"
    control_surface_name: Optional[str] = "rudder"
    control_surface_limit_deg: Optional[float] = Field(25.0, ge=0.0)


class SparConfig(BaseModel):
    """Shared schema for main_spar and rear_spar."""

    material: str = "carbon_fiber_hm"
    location_xc: float = 0.25
    layup_mode: Literal["isotropic", "discrete_clt"] = "isotropic"
    ply_material: str | None = None
    min_plies_0: int = Field(1, ge=1, description="Minimum 0° plies per half-layup")
    min_plies_45_pairs: int = Field(
        1,
        ge=1,
        description="Minimum ±45° ply pairs per half-layup",
    )
    min_plies_90: int = Field(0, ge=0, description="Minimum 90° plies per half-layup")
    max_total_plies: int = Field(
        14,
        ge=2,
        description="Maximum total symmetric laminate plies",
    )
    max_ply_drop_per_segment: int = Field(
        1,
        ge=0,
        description=(
            "Maximum half-layup ply-count change between adjacent segments. "
            "For symmetric laminates, one step equals two physical plies in wall thickness."
        ),
    )
    min_layup_run_length_m: float = Field(
        1.5,
        ge=0.0,
        description=(
            "Minimum spanwise length for a continuous constant-ply layup run. "
            "Set to 0 to disable the run-length report gate."
        ),
    )

    outer_diameter_root: Optional[float] = None
    outer_diameter_tip: Optional[float] = None
    thickness_fraction_root: float = 0.65
    thickness_fraction_tip: float = 0.80

    min_wall_thickness: float = 0.8e-3
    max_segment_length: float = 3.0

    segments: Optional[List[float]] = None

    joint_material: str = "aluminum_6061_t6"
    joint_mass_kg: float = 0.15

    enabled: bool = True


class LiftWireAttachment(BaseModel):
    y: float
    fuselage_z: float = -1.5
    label: str = ""


class LiftWireConfig(BaseModel):
    enabled: bool = True
    cable_material: str = "steel_4130"
    cable_diameter: float = 2.0e-3
    max_tension_fraction: float = 0.5
    pretension_n: float | List[float] = Field(
        default=0.0,
        description=(
            "Optional installed pretension per wire [N]. "
            "A scalar applies to every attachment; a list must align with attachments."
        ),
    )
    wire_angle_deg: float = Field(
        default=45.0,
        description=(
            "Inclination of lift wire from horizontal plane [deg]. "
            "Used to split wire tension into vertical (reaction) and "
            "horizontal (spar compression) components."
        ),
        gt=0.0,
        lt=90.0,
    )
    attachments: List[LiftWireAttachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pretension_values(self) -> LiftWireConfig:
        self.attachment_pretensions_n()
        return self

    def attachment_wire_angles_deg(self) -> List[float]:
        """Return one effective wire angle per configured attachment.

        For the historical single-wire baseline, preserve the explicit
        config value to avoid perturbing established regressions. For
        multi-wire layouts, derive each angle from that wire's spanwise
        reach and vertical drop when possible.
        """
        if not self.attachments:
            return []
        if len(self.attachments) == 1:
            return [float(self.wire_angle_deg)]

        angles: List[float] = []
        fallback = float(self.wire_angle_deg)
        for attachment in self.attachments:
            reach_m = abs(float(attachment.y))
            drop_m = abs(float(attachment.fuselage_z))
            if reach_m > 0.0 and drop_m > 0.0:
                angles.append(math.degrees(math.atan2(drop_m, reach_m)))
            else:
                angles.append(fallback)
        return angles

    def attachment_pretensions_n(self) -> List[float]:
        """Return one installed pretension value per configured attachment."""

        if not self.attachments:
            return []

        raw = self.pretension_n
        if isinstance(raw, (int, float)):
            value = float(raw)
            if value < 0.0:
                raise ValueError("lift_wires.pretension_n must be non-negative.")
            return [value for _ in self.attachments]

        values = [float(value) for value in raw]
        if len(values) != len(self.attachments):
            raise ValueError(
                "lift_wires.pretension_n list must align with lift_wires.attachments."
            )
        if any(value < 0.0 for value in values):
            raise ValueError("lift_wires.pretension_n must be non-negative.")
        return values


class AeroGatesConfig(BaseModel):
    min_lift_kg: float = Field(100.0, description="Minimum acceptable lift [kg]")
    min_ld_ratio: float = Field(25.0, description="Minimum acceptable lift-to-drag ratio")
    cd_profile_estimate: float = Field(
        0.010,
        description="Estimated profile drag coefficient for AVL induced-drag correction",
    )
    max_trim_aoa_deg: float = Field(
        12.0,
        description="Hard upper bound on trim AoA [deg]. Above this the sweep "
        "rejects the design. Sets the lower edge of the stall-margin budget.",
    )
    soft_trim_aoa_deg: float = Field(
        10.0,
        description="Soft design target for trim AoA [deg]. Trim above this "
        "value still passes the sweep but raises a design-warning flag.",
    )
    stall_alpha_deg: float = Field(
        13.5,
        description="Conservative stall angle for the wing root airfoil at "
        "cruise Re [deg]. Default is tuned for FX 76 MP 140 / Clark Y SM "
        "family at Re ~ 5e5; override per-airfoil if you change sections.",
    )
    min_stall_margin_deg: float = Field(
        2.0,
        description="Minimum required (stall_alpha_deg - trim_alpha_deg) [deg]. "
        "Designs below this margin are flagged for review.",
    )
    max_sideslip_deg: float = Field(
        12.0,
        description="Maximum required trimmed sideslip angle [deg]",
    )
    min_spiral_time_to_double_s: float = Field(
        10.0,
        description="Minimum acceptable spiral-mode time-to-double [s]",
        gt=0.0,
    )
    beta_sweep_values: List[float] = Field(
        default_factory=lambda: [0.0, 5.0, 10.0, 12.0],
        description="AVL beta sweep values [deg] for directional stability checks",
    )

    @model_validator(mode="after")
    def validate_beta_sweep_values(self) -> AeroGatesConfig:
        if not self.beta_sweep_values:
            raise ValueError("aero_gates.beta_sweep_values must not be empty.")
        if any(float(value) < 0.0 for value in self.beta_sweep_values):
            raise ValueError("aero_gates.beta_sweep_values must be non-negative.")
        return self


class SolverConfig(BaseModel):
    n_beam_nodes: int = 60
    optimizer: str = "SLSQP"
    optimizer_tol: float = 1e-6
    optimizer_maxiter: int = 500
    max_wall_thickness_m: float = Field(
        0.015, description="Global upper bound for spar wall thickness design vars [m]"
    )
    max_thickness_step_m: float = Field(
        0.003,
        description="Maximum wall thickness change between adjacent segments [m]",
    )
    min_radius_m: float = Field(
        0.010, description="Global lower bound for spar outer-radius design vars [m]"
    )
    max_radius_m: float = Field(
        0.060, description="Global upper bound for spar outer-radius design vars [m]"
    )
    max_thickness_to_radius_ratio: float = Field(
        0.8, description="Geometric limit enforced as t <= ratio * R"
    )
    fem_max_matrix_entry: float = Field(
        1e12, description="Numerical guard: max allowed absolute FEM matrix entry"
    )
    fem_max_disp_entry: float = Field(
        1e2, description="Numerical guard: max allowed absolute displacement/Jacobian entry"
    )
    fem_bc_penalty: float = Field(1e15, description="Penalty stiffness added on constrained DOFs")
    scipy_eval_cache_size: int = Field(
        2048, description="LRU cache size for SciPy black-box evaluations"
    )
    de_max_workers: int = Field(
        4, description="Upper bound on DE multiprocessing workers to limit memory footprint"
    )
    main_spar_dominance_margin_m: float = Field(
        0.005,
        description="Main spar segment radius must exceed rear spar radius by at least this margin [m]",
    )
    rear_main_radius_ratio_min: float = Field(
        0.0,
        description=(
            "Optional rear-spar softness guardrail: enforce rear_r >= ratio * main_r "
            "per segment. Set to 0 to disable."
        ),
        ge=0.0,
        le=1.0,
    )
    main_spar_ei_ratio: float = Field(
        2.0,
        description="Main spar element bending stiffness must satisfy EI_main >= ratio * EI_rear",
    )
    rear_min_inner_radius_m: float = Field(
        1.0e-4,
        description=(
            "Hard physical guard for rear hollow tube validity: "
            "rear inner radius (R - t) must be at least this value [m]"
        ),
        ge=0.0,
    )
    rear_inboard_span_m: float = Field(
        1.5,
        description=(
            "Root-side span extent [m] where an additional rear-secondary EI cap is enforced"
        ),
        ge=0.0,
    )
    rear_inboard_ei_to_main_ratio_max: float = Field(
        0.20,
        description=(
            "Inboard rear-secondary cap: enforce EI_rear <= ratio * EI_main "
            "within rear_inboard_span_m"
        ),
        ge=0.0,
        le=1.0,
    )
    loaded_shape_z_tol_m: float = Field(
        0.025,
        description=(
            "Maximum allowed main-beam loaded-shape control-station "
            "error used by inverse design [m]"
        ),
    )
    loaded_shape_twist_tol_deg: float = Field(
        0.15,
        description=(
            "Maximum allowed loaded-shape twist control-station error used by inverse design [deg]"
        ),
    )
    fsi_coupling: Literal["one-way", "two-way"] = "one-way"
    fsi_max_iter: int = 20
    fsi_tol: float = 1e-3


class StructureConfig(BaseModel):
    """Structural solver options beyond what SolverConfig carries."""

    failure_criterion: Literal["von_mises", "tsai_hill", "tsai_wu"] = Field(
        "von_mises",
        description=(
            "Failure criterion applied to spar tube elements. "
            "'von_mises' uses isotropic σ_vm ≤ σ_allow; "
            "'tsai_hill' uses the Tsai-Hill anisotropic quadratic; "
            "'tsai_wu' uses the full Tsai-Wu tensor polynomial. "
            "Both composite criteria require F1t/F1c/F2t/F2c/F6 in materials.yaml."
        ),
    )


class RibConfig(BaseModel):
    enabled: bool = True
    family: Optional[str] = Field(
        None,
        description="Optional rib family key from data/rib_properties.yaml.",
    )
    spacing_m: Optional[float] = Field(
        None,
        gt=0.0,
        description="Nominal rib spacing used for derived warping knockdown [m].",
    )
    derive_warping_knockdown: bool = Field(
        True,
        description=(
            "If true and safety.dual_spar_warping_knockdown is omitted, derive the "
            "legacy scalar from the rib catalog."
        ),
    )
    warping_knockdown_override: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Optional rib-level override for the derived warping knockdown.",
    )
    catalog_path: Optional[Path] = Field(
        None,
        description="Optional custom rib catalog path. Relative paths resolve from the config root.",
    )


class IOConfig(BaseModel):
    sync_root: Optional[Path] = None
    vsp_model: Optional[Path] = None
    vsp_lod: Optional[Path] = None
    vsp_polar: Optional[Path] = None
    airfoil_dir: Optional[Path] = None
    output_dir: Path = Path("output")
    training_db: Path = Path("database/training_data.csv")


class ASWINGExportConfig(BaseModel):
    """Seed values for the ASWING .asw exporter.

    Flight physics constants (air density, gravity) come from
    `flight` and `safety`; material properties come from MaterialDB.
    This block holds only the ASWING-file-format seed parameters
    that ASWING itself needs but that the rest of the MDO does not
    carry elsewhere.
    """

    sonic_speed_mps: float = Field(
        343.0,
        description="Speed of sound at cruise altitude [m/s].",
    )
    cl_alpha_per_rad: float = Field(
        2.0 * math.pi,
        description="Sectional lift-curve slope [1/rad]. Default is thin-airfoil 2pi.",
    )
    cl_max: float = Field(
        1.35,
        description="Positive-stall sectional Cl_max used for ASWING gust/beta limits.",
    )
    cl_min: float = Field(
        -1.10,
        description="Negative-stall sectional Cl_min used for ASWING gust/beta limits.",
    )
    tail_stiffness_eicc_n_m2: float = Field(
        5.0e3,
        description="Chordwise bending stiffness EIcc for tail beam blocks [N*m^2].",
    )
    tail_stiffness_einn_n_m2: float = Field(
        2.0e3,
        description="Normal bending stiffness EInn for tail beam blocks [N*m^2].",
    )
    tail_stiffness_gj_n_m2: float = Field(
        1.0e3,
        description="Torsional stiffness GJ for tail beam blocks [N*m^2].",
    )
    tail_axial_stiffness_ea_n: float = Field(
        5.0e5,
        description="Axial stiffness EA for tail beam blocks [N].",
    )
    tail_weight_per_length_npm: float = Field(
        0.35,
        description="Distributed weight per unit length for tail beam blocks [N/m].",
    )


# ── High-fidelity validation stack (blueprint — see ────────────────────────
#    docs/hi_fidelity_validation_stack.md).  All solvers default to
#    disabled.  Populate binaries in configs/local_paths.yaml so this
#    file stays portable.


class GmshConfig(BaseModel):
    enabled: bool = False
    binary: Optional[str] = None
    mesh_size_m: float = Field(0.05, gt=0.0)
    # Max distance [m] a NamedPoint coordinate may sit from the nearest mesh
    # node when building Physical Groups (root / tip / wire-joint tags) in
    # ``hpa_mdo.hifi.gmsh_runner``.  Kept tight by default; override per-config
    # for coarser meshes.
    point_tol_m: float = Field(1.0e-3, gt=0.0)


class CalculiXConfig(BaseModel):
    enabled: bool = False
    ccx_binary: Optional[str] = None
    cgx_binary: Optional[str] = None


class ParaViewConfig(BaseModel):
    enabled: bool = False
    binary: Optional[str] = None


class SU2Config(BaseModel):
    """Blueprint only — CFD runner not yet implemented."""
    enabled: bool = False
    binary: Optional[str] = None
    cfg_template: Optional[str] = None


class ASWINGRunConfig(BaseModel):
    """ASWING nonlinear aeroelastic runner (M-ASWING)."""
    enabled: bool = False
    binary: Optional[str] = Field(
        None,
        description="Path to aswing binary; auto-detected from PATH if null.",
    )
    timeout_s: int = Field(
        600,
        description="Subprocess timeout [s] before ASWING is killed.",
        gt=0,
    )
    n_panels: int = Field(
        20,
        description="ASWING spanwise vortex panels per wing half-span.",
        gt=0,
    )
    vinf_mps: Optional[float] = Field(
        None,
        description="Trim airspeed [m/s]; null inherits from flight.velocity.",
    )
    warn_threshold_pct: float = Field(
        10.0,
        description=(
            "Percentage difference above which the ASWING vs MDO comparison "
            "is flagged WARN (not an error) in the report."
        ),
        gt=0.0,
    )


class HiFidelityConfig(BaseModel):
    """External solver stack for last-mile validation on Apple Silicon."""
    gmsh: GmshConfig = GmshConfig()
    calculix: CalculiXConfig = CalculiXConfig()
    paraview: ParaViewConfig = ParaViewConfig()
    su2: SU2Config = SU2Config()
    aswing: ASWINGRunConfig = ASWINGRunConfig()


# ── Mass / CG / Inertia budget (M14) ────────────────────────────────────────

_MASS_BUDGET_STANDARD_KEYS = (
    "pilot",
    "fuselage_structure",
    "wing_secondary_structure",
    "drivetrain",
    "propeller",
    "empennage",
    "controls",
    "avionics",
    "landing_gear",
    "payload",
    "ballast",
    "miscellaneous",
)


class MassItemConfig(BaseModel):
    m_kg: float = Field(default=0.0, ge=0.0)
    xyz_m: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    sigma_kg: float = Field(default=0.0, ge=0.0)
    principal_inertia_kgm2: Optional[List[float]] = None
    enabled: bool = True
    notes: str = ""
    source: str = "estimated"

    @model_validator(mode="after")
    def _check_shapes(self) -> MassItemConfig:
        if len(self.xyz_m) != 3:
            raise ValueError("mass_budget item xyz_m must be length 3.")
        if self.principal_inertia_kgm2 is not None and len(self.principal_inertia_kgm2) != 3:
            raise ValueError("mass_budget item principal_inertia_kgm2 must be length 3.")
        return self


class MassBudgetConfig(BaseModel):
    """Aircraft-wide mass accounting with reserved top-level slots.

    The named fields cover the usual full-aircraft buckets while
    ``extra_items`` provides an escape hatch for any project-specific
    subsystem that does not fit the baseline template.
    """

    reference_point_m: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    target_total_mass_kg: Optional[float] = None
    include_spar_from_optimization: bool = True
    include_lift_wires_from_geometry: bool = True

    pilot: Optional[MassItemConfig] = None
    fuselage_structure: Optional[MassItemConfig] = None
    wing_secondary_structure: Optional[MassItemConfig] = None
    drivetrain: Optional[MassItemConfig] = None
    propeller: Optional[MassItemConfig] = None
    empennage: Optional[MassItemConfig] = None
    controls: Optional[MassItemConfig] = None
    avionics: Optional[MassItemConfig] = None
    landing_gear: Optional[MassItemConfig] = None
    payload: Optional[MassItemConfig] = None
    ballast: Optional[MassItemConfig] = None
    miscellaneous: Optional[MassItemConfig] = None

    extra_items: Dict[str, MassItemConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_items(cls, data):
        if not isinstance(data, dict):
            return data

        payload = dict(data)
        if "mtow_target_kg" in payload and "target_total_mass_kg" not in payload:
            payload["target_total_mass_kg"] = payload.pop("mtow_target_kg")

        legacy_items = payload.pop("items", None) or []
        extra_items = dict(payload.get("extra_items") or {})
        for raw_item in legacy_items:
            if not isinstance(raw_item, dict):
                continue
            name = str(raw_item.get("name", "")).strip()
            if not name:
                continue
            item_payload = {
                "m_kg": raw_item.get("m_kg", raw_item.get("mass_kg", 0.0)),
                "xyz_m": raw_item.get("xyz_m", raw_item.get("cg_m", [0.0, 0.0, 0.0])),
                "sigma_kg": raw_item.get("sigma_kg", 0.0),
                "principal_inertia_kgm2": raw_item.get("principal_inertia_kgm2"),
                "enabled": raw_item.get("enabled", True),
                "notes": raw_item.get("notes", ""),
                "source": raw_item.get("source", "estimated"),
            }
            if name in _MASS_BUDGET_STANDARD_KEYS and payload.get(name) is None:
                payload[name] = item_payload
            else:
                extra_items[name] = item_payload
        payload["extra_items"] = extra_items
        return payload

    @model_validator(mode="after")
    def _check_shapes(self) -> MassBudgetConfig:
        if len(self.reference_point_m) != 3:
            raise ValueError("mass_budget.reference_point_m must be length 3.")
        return self


# ── Top-level ───────────────────────────────────────────────────────────────


class HPAConfig(BaseModel):
    project_name: str = "HPA-MDO"
    flight: FlightConfig
    safety: SafetyConfig = SafetyConfig()
    weight: WeightConfig
    wing: WingConfig
    horizontal_tail: HorizontalTailConfig = HorizontalTailConfig(
        x_location=4.0,
        span=3.0,
        root_chord=0.8,
        tip_chord=0.8,
    )
    vertical_fin: VerticalFinConfig = VerticalFinConfig(
        x_location=5.0,
        z_location=-0.7,
        span=2.4,
        root_chord=0.7,
        tip_chord=0.7,
    )
    main_spar: SparConfig
    rear_spar: SparConfig = SparConfig(
        enabled=True,
        location_xc=0.70,
        thickness_fraction_root=0.55,
        thickness_fraction_tip=0.65,
        joint_mass_kg=0.10,
    )
    lift_wires: LiftWireConfig = LiftWireConfig()
    aero_gates: AeroGatesConfig = AeroGatesConfig()
    solver: SolverConfig = SolverConfig()
    structure: StructureConfig = StructureConfig()
    rib: RibConfig = RibConfig()
    io: IOConfig = IOConfig()
    aswing: ASWINGExportConfig = ASWINGExportConfig()
    hi_fidelity: HiFidelityConfig = HiFidelityConfig()
    mass_budget: MassBudgetConfig = MassBudgetConfig()

    @property
    def half_span(self) -> float:
        return self.wing.span / 2.0

    def spar_segment_lengths(self, spar_cfg: SparConfig) -> List[float]:
        """Return segment lengths, auto-dividing if not explicit."""
        if spar_cfg.segments:
            return list(spar_cfg.segments)
        hs = self.half_span
        msl = spar_cfg.max_segment_length
        n = int(hs // msl)
        remainder = hs - n * msl
        segs = ([remainder] if remainder > 0.01 else []) + [msl] * n
        return segs

    def structural_load_cases(self) -> List[LoadCaseConfig]:
        """Return explicit structural load cases, falling back to legacy single-case mode."""
        if self.flight.cases:
            return list(self.flight.cases)

        return [
            LoadCaseConfig(
                name="default",
                aero_scale=self.safety.aerodynamic_load_factor,
                nz=self.safety.aerodynamic_load_factor,
                velocity=self.flight.velocity,
                air_density=self.flight.air_density,
                max_tip_deflection_m=self.wing.max_tip_deflection_m,
                max_twist_deg=self.wing.max_tip_twist_deg,
            )
        ]

    @staticmethod
    def joint_positions(segments: List[float]) -> List[float]:
        """Cumulative sum excluding the last element → joint y-coords."""
        import numpy as np

        cs = list(np.cumsum(segments))
        return cs[:-1]  # last entry is the tip, not a joint

    @model_validator(mode="after")
    def validate_spanwise_layout(self) -> HPAConfig:
        tol = 1e-6
        half_span = self.half_span

        for spar_name, spar_cfg in (
            ("main_spar", self.main_spar),
            ("rear_spar", self.rear_spar),
        ):
            if not spar_cfg.enabled:
                continue
            segments = self.spar_segment_lengths(spar_cfg)
            total = float(sum(segments))
            if abs(total - half_span) > tol:
                raise ValueError(
                    f"{spar_name}.segments sum to {total:.9f} m, "
                    f"but wing.span/2 is {half_span:.9f} m."
                )

        if self.lift_wires.enabled and self.lift_wires.attachments:
            main_joints = self.joint_positions(self.spar_segment_lengths(self.main_spar))
            for att in self.lift_wires.attachments:
                if not any(abs(att.y - jy) <= tol for jy in main_joints):
                    raise ValueError(
                        f"lift_wires attachment y must lie on a segment boundary (got y={att.y})."
                    )

        return self


def _read_yaml(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _discover_local_paths_path(
    config_path: Path,
    local_paths_path: Optional[Path | str],
) -> Optional[Path]:
    if local_paths_path is not None:
        candidate = Path(local_paths_path).expanduser()
        if not candidate.is_absolute():
            candidate = (config_path.parent / candidate).resolve()
        return candidate

    env_override = os.getenv("HPA_MDO_LOCAL_PATHS")
    if env_override:
        return Path(env_override).expanduser().resolve()

    return (config_path.parent / _LOCAL_PATHS_FILENAME).resolve()


def _project_root_from_config(config_path: Path) -> Path:
    if config_path.parent.name == "configs":
        return config_path.parent.parent
    return config_path.parent


def _resolve_path(path_value: Optional[Path], base_dir: Path) -> Optional[Path]:
    if path_value is None:
        return None
    if path_value.is_absolute():
        return path_value
    return (base_dir / path_value).resolve()


def _resolve_io_paths(cfg: HPAConfig, project_root: Path) -> HPAConfig:
    sync_root = _resolve_path(cfg.io.sync_root, project_root)
    cfg.io.sync_root = sync_root

    for field_name in _EXTERNAL_IO_FIELDS:
        raw_path = getattr(cfg.io, field_name)
        if raw_path is None:
            continue
        if raw_path.is_absolute():
            resolved = raw_path
        elif sync_root is not None:
            resolved = (sync_root / raw_path).resolve()
        else:
            resolved = (project_root / raw_path).resolve()
        setattr(cfg.io, field_name, resolved)

    for field_name in _INTERNAL_IO_FIELDS:
        resolved = _resolve_path(getattr(cfg.io, field_name), project_root)
        if resolved is not None:
            setattr(cfg.io, field_name, resolved)

    return cfg


def _resolve_rib_path(cfg: HPAConfig, project_root: Path) -> HPAConfig:
    resolved_catalog = _resolve_path(cfg.rib.catalog_path, project_root)
    if resolved_catalog is not None:
        cfg.rib.catalog_path = resolved_catalog
    return cfg


def _apply_derived_rib_knockdown(
    cfg: HPAConfig,
    data: Dict[str, Any],
) -> HPAConfig:
    safety_payload = data.get("safety")
    if isinstance(safety_payload, dict) and "dual_spar_warping_knockdown" in safety_payload:
        return cfg
    if not cfg.rib.enabled or not cfg.rib.derive_warping_knockdown:
        return cfg

    from hpa_mdo.structure.rib_properties import resolve_rib_warping_knockdown

    cfg.safety.dual_spar_warping_knockdown = resolve_rib_warping_knockdown(
        family_key=cfg.rib.family,
        spacing_m=cfg.rib.spacing_m,
        catalog_path=cfg.rib.catalog_path,
        warping_knockdown_override=cfg.rib.warping_knockdown_override,
    )
    return cfg


def load_config(
    path,
    local_paths_path: Optional[Path | str] = None,
) -> HPAConfig:
    config_path = Path(path).expanduser().resolve()
    project_root = _project_root_from_config(config_path)

    data = _read_yaml(config_path)
    overlay_path = _discover_local_paths_path(config_path, local_paths_path)
    if overlay_path is not None and overlay_path.exists():
        data = _deep_merge(data, _read_yaml(overlay_path))

    cfg = HPAConfig(**data)
    cfg = _resolve_io_paths(cfg, project_root)
    cfg = _resolve_rib_path(cfg, project_root)
    return _apply_derived_rib_knockdown(cfg, data)
