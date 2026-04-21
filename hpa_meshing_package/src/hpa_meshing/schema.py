from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, List, Dict, Any

from pydantic import BaseModel, Field


ComponentType = Literal[
    "main_wing",
    "tail_wing",
    "fairing_solid",
    "fairing_vented",
    "aircraft_assembly",
]
GeometrySourceType = Literal[
    "direct_cad",
    "esp_rebuilt",
    "provider_generated",
    "manifest_declared",
]
GeometryProviderType = Literal[
    "openvsp_surface_intersection",
    "esp_rebuilt",
]
GeometryProviderStageType = Literal["v1", "experimental"]
GeometryProviderStatusType = Literal["materialized", "not_materialized"]
GeometryFamilyType = Literal[
    "closed_solid",
    "thin_sheet_lifting_surface",
    "thin_sheet_aircraft_assembly",
    "perforated_solid",
]
MeshingRouteType = Literal[
    "gmsh_closed_solid_volume",
    "gmsh_perforated_solid_volume",
    "gmsh_thin_sheet_surface",
    "gmsh_thin_sheet_aircraft_assembly",
]
BackendCapabilityType = Literal[
    "occ_closed_solid_meshing",
    "occ_perforated_solid_meshing",
    "sheet_lifting_surface_meshing",
    "sheet_aircraft_assembly_meshing",
]
ProvenanceConfidenceType = Literal["low", "medium", "high"]
GateStatusType = Literal["pass", "warn", "fail"]
ComparabilityLevelType = Literal["preliminary_compare", "run_only", "not_comparable"]
MeshStudyTierType = Literal["coarse", "medium", "fine", "super-fine"]
MeshStudyVerdictType = Literal["insufficient", "still_run_only", "preliminary_compare"]
SU2ReferenceModeType = Literal[
    "auto",
    "baseline_envelope_derived",
    "geometry_derived",
    "user_declared",
]
SU2ReferenceSourceCategoryType = Literal[
    "baseline_envelope_derived",
    "geometry_derived",
    "user_declared",
]
ForceSurfaceScopeType = Literal["whole_aircraft_wall", "component_subset", "unknown"]
ComponentForceSurfaceProvenanceType = Literal[
    "not_available",
    "geometry_labels_present_but_not_mapped",
    "component_groups_mapped",
]


class BoundaryLayerConfig(BaseModel):
    enabled: bool = False
    first_layer_height: Optional[float] = None
    total_thickness: Optional[float] = None
    growth_rate: float = 1.2
    n_layers: int = 8


class FarfieldConfig(BaseModel):
    enabled: bool = True
    upstream_factor: float = 5.0
    downstream_factor: float = 12.0
    lateral_factor: float = 8.0
    vertical_factor: float = 8.0
    wake_box_factor: Optional[float] = None


class QualityGateConfig(BaseModel):
    max_skewness: Optional[float] = None
    min_scaled_jacobian: Optional[float] = None
    max_elements: Optional[int] = None
    allow_no_bl_fallback: bool = True


class FallbackConfig(BaseModel):
    max_attempts: int = 4
    relax_local_size_factor: float = 1.25
    reduce_bl_layers_step: int = 2
    increase_global_size_factor: float = 1.2
    disable_bl_on_final_attempt: bool = True


class ComponentRuleConfig(BaseModel):
    min_feature_size: Optional[float] = None
    max_holes: Optional[int] = None
    min_hole_width: Optional[float] = None
    min_hole_spacing: Optional[float] = None
    supported_vent_shapes: List[str] = Field(default_factory=list)


class Bounds3D(BaseModel):
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float


class Point3D(BaseModel):
    x: float
    y: float
    z: float


SU2RunStatusType = Literal["not_started", "completed", "failed"]


class SU2ReferenceOverride(BaseModel):
    ref_area: float
    ref_length: float
    ref_origin_moment: Point3D
    source_label: str = "user_declared"
    source_path: Optional[Path] = None
    notes: List[str] = Field(default_factory=list)


class SU2RuntimeConfig(BaseModel):
    enabled: bool = False
    alpha_deg: float = 0.0
    velocity_mps: float = 10.0
    density_kgpm3: float = 1.225
    temperature_k: float = 288.15
    dynamic_viscosity_pas: float = 1.789e-5
    solver: Literal["INC_NAVIER_STOKES"] = "INC_NAVIER_STOKES"
    solver_command: str = "SU2_CFD"
    case_name: str = "alpha_0_baseline"
    max_iterations: int = 50
    cfl_number: float = 5.0
    linear_solver_error: float = 1e-6
    linear_solver_iterations: int = 8
    reference_mode: SU2ReferenceModeType = "auto"
    reference_override: Optional[SU2ReferenceOverride] = None


class GeometryTopologyMetadata(BaseModel):
    representation: str
    source_kind: str
    units: Optional[Literal["m", "mm"]] = None
    bounds: Optional[Bounds3D] = None
    import_bounds: Optional[Bounds3D] = None
    import_scale_to_units: Optional[float] = None
    backend_rescale_required: bool = False
    body_count: Optional[int] = None
    surface_count: Optional[int] = None
    volume_count: Optional[int] = None
    labels_present: Optional[bool] = None
    label_schema: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


class GeometryProviderRequest(BaseModel):
    provider: GeometryProviderType
    source_path: Path
    component: ComponentType
    staging_dir: Path
    target_representation: str = "brep_component_volumes"
    geometry_family_hint: Optional[GeometryFamilyType] = None
    units_hint: Literal["auto", "m", "mm"] = "auto"
    label_policy: str = "preserve_component_labels"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GeometryProviderResult(BaseModel):
    provider: GeometryProviderType
    provider_stage: GeometryProviderStageType
    status: GeometryProviderStatusType
    geometry_source: GeometrySourceType
    source_path: Path
    normalized_geometry_path: Optional[Path] = None
    geometry_family_hint: Optional[GeometryFamilyType] = None
    provider_version: Optional[str] = None
    topology: GeometryTopologyMetadata
    artifacts: Dict[str, Path] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class GeometryHandle(BaseModel):
    source_path: Path
    path: Path
    exists: bool
    suffix: str
    loader: str = "filesystem_stub"
    geometry_source: GeometrySourceType = "direct_cad"
    declared_family: Optional[GeometryFamilyType] = None
    component: ComponentType
    provider: Optional[GeometryProviderType] = None
    provider_status: Optional[GeometryProviderStatusType] = None
    provider_result: Optional[GeometryProviderResult] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GeometryClassification(BaseModel):
    geometry_source: GeometrySourceType
    geometry_provider: Optional[GeometryProviderType] = None
    declared_family: Optional[GeometryFamilyType] = None
    inferred_family: Optional[GeometryFamilyType] = None
    geometry_family: GeometryFamilyType
    provenance: str
    notes: List[str] = Field(default_factory=list)


class GeometryValidationResult(BaseModel):
    ok: bool
    exists_ok: bool
    suffix_ok: bool
    component_family_ok: bool
    provider_ready: bool = True
    geometry_source: GeometrySourceType
    geometry_provider: Optional[GeometryProviderType] = None
    geometry_family: GeometryFamilyType
    failure_code: Optional[str] = None
    supported_suffixes: List[str] = Field(default_factory=list)
    supported_families: List[GeometryFamilyType] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class MeshingRouteResolution(BaseModel):
    meshing_route: MeshingRouteType
    backend: Literal["gmsh"] = "gmsh"
    backend_capability: BackendCapabilityType
    geometry_family: GeometryFamilyType
    route_provenance: str
    notes: List[str] = Field(default_factory=list)


class MeshRecipe(BaseModel):
    name: str
    component: ComponentType
    geometry: str
    geometry_source: GeometrySourceType
    geometry_provider: Optional[GeometryProviderType] = None
    geometry_family: GeometryFamilyType
    meshing_route: MeshingRouteType
    backend: Literal["gmsh"] = "gmsh"
    backend_capability: BackendCapabilityType
    route_provenance: str
    family_features: List[str] = Field(default_factory=list)
    farfield_enabled: bool
    boundary_layer_enabled: bool
    global_min_size: Optional[float]
    global_max_size: Optional[float]


class MeshJobConfig(BaseModel):
    component: ComponentType
    geometry: Path
    out_dir: Path
    geometry_source: GeometrySourceType = "direct_cad"
    geometry_family: Optional[GeometryFamilyType] = None
    meshing_route: Optional[MeshingRouteType] = None
    backend_capability: Optional[BackendCapabilityType] = None
    geometry_provider: Optional[GeometryProviderType] = None
    units: Literal["m", "mm"] = "m"
    mesh_dim: Literal[2, 3] = 3
    mesh_algorithm_2d: Optional[int] = None
    mesh_algorithm_3d: Optional[int] = None
    global_min_size: Optional[float] = None
    global_max_size: Optional[float] = None
    boundary_layer: BoundaryLayerConfig = Field(default_factory=BoundaryLayerConfig)
    farfield: FarfieldConfig = Field(default_factory=FarfieldConfig)
    quality_gate: QualityGateConfig = Field(default_factory=QualityGateConfig)
    fallback: FallbackConfig = Field(default_factory=FallbackConfig)
    rules: ComponentRuleConfig = Field(default_factory=ComponentRuleConfig)
    tags: Dict[str, str] = Field(default_factory=lambda: {
        "wall": "wall",
        "farfield": "farfield",
        "symmetry": "symmetry",
    })
    metadata: Dict[str, Any] = Field(default_factory=dict)
    su2: SU2RuntimeConfig = Field(default_factory=SU2RuntimeConfig)


class MeshArtifactBundle(BaseModel):
    mesh: Path
    mesh_metadata: Path
    marker_summary: Path


class MeshHandoff(BaseModel):
    contract: Literal["mesh_handoff.v1"] = "mesh_handoff.v1"
    route_stage: str
    backend: Literal["gmsh"] = "gmsh"
    backend_capability: Optional[BackendCapabilityType] = None
    meshing_route: Optional[MeshingRouteType] = None
    geometry_family: GeometryFamilyType
    geometry_source: GeometrySourceType
    geometry_provider: Optional[GeometryProviderType] = None
    source_path: Path
    normalized_geometry_path: Path
    units: Literal["m", "mm"]
    mesh_format: str = "msh"
    body_bounds: Bounds3D
    farfield_bounds: Bounds3D
    mesh_stats: Dict[str, Any] = Field(default_factory=dict)
    marker_summary: Dict[str, Any] = Field(default_factory=dict)
    physical_groups: Dict[str, Any] = Field(default_factory=dict)
    artifacts: MeshArtifactBundle
    provenance: Dict[str, Any] = Field(default_factory=dict)
    unit_normalization: Dict[str, Any] = Field(default_factory=dict)


class SU2ReferenceQuantityProvenance(BaseModel):
    source_category: SU2ReferenceSourceCategoryType
    method: str
    confidence: ProvenanceConfidenceType = "low"
    source_path: Optional[Path] = None
    source_units: Optional[Literal["m", "mm"]] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class SU2ReferenceGeometry(BaseModel):
    ref_area: float
    ref_length: float
    ref_origin_moment: Point3D
    area_provenance: SU2ReferenceQuantityProvenance
    length_provenance: SU2ReferenceQuantityProvenance
    moment_origin_provenance: SU2ReferenceQuantityProvenance
    gate_status: GateStatusType = "warn"
    confidence: ProvenanceConfidenceType = "low"
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class SU2CaseArtifacts(BaseModel):
    case_dir: Path
    su2_mesh: Path
    history: Optional[Path] = None
    solver_log: Path
    surface_output: Optional[Path] = None
    restart_output: Optional[Path] = None
    volume_output: Optional[Path] = None
    contract_path: Path


class SU2HistorySummary(BaseModel):
    history_path: Optional[Path] = None
    final_iteration: Optional[int] = None
    cl: Optional[float] = None
    cd: Optional[float] = None
    cm: Optional[float] = None
    cm_axis: Optional[str] = None
    source_columns: Dict[str, str] = Field(default_factory=dict)


class SU2ForceSurfaceMarkerGroup(BaseModel):
    marker_name: str
    physical_name: str
    physical_tag: Optional[int] = None
    dimension: Optional[int] = None
    entity_count: Optional[int] = None
    element_count: Optional[int] = None


class SU2ForceSurfaceProvenance(BaseModel):
    gate_status: GateStatusType = "fail"
    confidence: ProvenanceConfidenceType = "low"
    source_kind: Literal["mesh_physical_group", "unknown"] = "unknown"
    wall_marker: str
    monitoring_markers: List[str] = Field(default_factory=list)
    plotting_markers: List[str] = Field(default_factory=list)
    euler_markers: List[str] = Field(default_factory=list)
    source_groups: List[SU2ForceSurfaceMarkerGroup] = Field(default_factory=list)
    primary_group: Optional[SU2ForceSurfaceMarkerGroup] = None
    matches_wall_marker: bool = False
    matches_entire_aircraft_wall: bool = False
    scope: ForceSurfaceScopeType = "unknown"
    body_count: Optional[int] = None
    component_labels_present_in_geometry: Optional[bool] = None
    component_label_schema: Optional[str] = None
    component_provenance: ComponentForceSurfaceProvenanceType = "not_available"
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class SU2GateCheck(BaseModel):
    status: GateStatusType = "warn"
    confidence: ProvenanceConfidenceType = "low"
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class SU2ProvenanceGates(BaseModel):
    overall_status: GateStatusType = "warn"
    reference_quantities: SU2GateCheck = Field(default_factory=SU2GateCheck)
    force_surface: SU2GateCheck = Field(default_factory=SU2GateCheck)
    warnings: List[str] = Field(default_factory=list)


class ConvergenceGateCheck(BaseModel):
    status: GateStatusType = "warn"
    observed: Dict[str, Any] = Field(default_factory=dict)
    expected: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class ConvergenceGateSection(BaseModel):
    status: GateStatusType = "warn"
    confidence: ProvenanceConfidenceType = "low"
    checks: Dict[str, ConvergenceGateCheck] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class OverallConvergenceGate(ConvergenceGateSection):
    comparability_level: ComparabilityLevelType = "run_only"


class BaselineConvergenceGate(BaseModel):
    contract: Literal["convergence_gate.v1"] = "convergence_gate.v1"
    mesh_gate: ConvergenceGateSection = Field(default_factory=ConvergenceGateSection)
    iterative_gate: ConvergenceGateSection = Field(default_factory=ConvergenceGateSection)
    overall_convergence_gate: OverallConvergenceGate = Field(default_factory=OverallConvergenceGate)


class MeshStudyPresetRuntime(BaseModel):
    max_iterations: int
    cfl_number: float
    linear_solver_error: float = 1e-6
    linear_solver_iterations: int = 8


class MeshStudyPreset(BaseModel):
    name: str
    tier: MeshStudyTierType
    characteristic_length_policy: Literal["body_max_span"] = "body_max_span"
    near_body_factor: float
    farfield_factor: float
    near_body_size: float
    farfield_size: float
    runtime: MeshStudyPresetRuntime
    notes: List[str] = Field(default_factory=list)


class MeshStudyMeshStats(BaseModel):
    mesh_dim: Optional[int] = None
    node_count: Optional[int] = None
    element_count: Optional[int] = None
    surface_element_count: Optional[int] = None
    volume_element_count: Optional[int] = None
    characteristic_length: Optional[float] = None
    near_body_size: Optional[float] = None
    farfield_size: Optional[float] = None


class MeshStudyCFDResult(BaseModel):
    case_name: str
    history_path: Optional[Path] = None
    final_iteration: Optional[int] = None
    cl: Optional[float] = None
    cd: Optional[float] = None
    cm: Optional[float] = None
    cm_axis: Optional[str] = None


class MeshStudyCaseResult(BaseModel):
    preset: MeshStudyPreset
    out_dir: Path
    report_path: Path
    status: Literal["success", "failed"] = "success"
    failure_code: Optional[str] = None
    mesh: MeshStudyMeshStats = Field(default_factory=MeshStudyMeshStats)
    cfd: Optional[MeshStudyCFDResult] = None
    convergence_gate: Optional[BaselineConvergenceGate] = None
    overall_convergence_status: Optional[GateStatusType] = None
    comparability_level: Optional[ComparabilityLevelType] = None
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class MeshStudyComparison(BaseModel):
    expected_case_count: int
    completed_case_count: int
    case_order: List[str] = Field(default_factory=list)
    mesh_hierarchy: ConvergenceGateCheck = Field(default_factory=ConvergenceGateCheck)
    coefficient_spread: Dict[str, ConvergenceGateCheck] = Field(default_factory=dict)
    convergence_progress: ConvergenceGateCheck = Field(default_factory=ConvergenceGateCheck)
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class MeshStudyVerdict(BaseModel):
    verdict: MeshStudyVerdictType = "insufficient"
    comparability_level: ComparabilityLevelType = "not_comparable"
    confidence: ProvenanceConfidenceType = "low"
    blockers: List[str] = Field(default_factory=list)
    checks: Dict[str, ConvergenceGateCheck] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class MeshStudyReport(BaseModel):
    contract: Literal["mesh_study.v1"] = "mesh_study.v1"
    study_name: str = "baseline_mesh_study"
    component: ComponentType
    geometry: Path
    geometry_provider: Optional[GeometryProviderType] = None
    cases: List[MeshStudyCaseResult] = Field(default_factory=list)
    comparison: MeshStudyComparison
    verdict: MeshStudyVerdict
    notes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class SU2CaseHandoff(BaseModel):
    contract: Literal["su2_handoff.v1"] = "su2_handoff.v1"
    route_stage: Literal["baseline"] = "baseline"
    source_contract: Literal["mesh_handoff.v1"] = "mesh_handoff.v1"
    geometry_family: GeometryFamilyType
    units: Literal["m", "mm"]
    input_mesh_artifact: Path
    mesh_markers: Dict[str, Any] = Field(default_factory=dict)
    reference_geometry: SU2ReferenceGeometry
    runtime: SU2RuntimeConfig
    runtime_cfg_path: Path
    case_output_paths: SU2CaseArtifacts
    history: SU2HistorySummary = Field(default_factory=SU2HistorySummary)
    run_status: SU2RunStatusType = "not_started"
    solver_command: List[str] = Field(default_factory=list)
    force_surface_provenance: Optional[SU2ForceSurfaceProvenance] = None
    provenance_gates: SU2ProvenanceGates = Field(default_factory=SU2ProvenanceGates)
    convergence_gate: Optional[BaselineConvergenceGate] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class BatchManifest(BaseModel):
    jobs: List[MeshJobConfig]
