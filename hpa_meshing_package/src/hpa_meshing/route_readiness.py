from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Literal

from pydantic import BaseModel, Field

from .dispatch import route_spec
from .schema import ComponentType, GeometryFamilyType, MeshingRouteType


ProductizationStatusType = Literal[
    "formal_v1",
    "experimental",
    "registered_not_productized",
    "diagnostic_only",
]
RouteRoleType = Literal[
    "current_product_line",
    "experimental_and_diagnostic",
    "registered_future_route",
]
SU2ReadinessStatusType = Literal[
    "baseline_productized",
    "not_productized",
    "blocked_until_route_smoke",
    "blocked_until_su2_handoff",
    "handoff_materialized_solver_not_run",
    "handoff_materialized_force_marker_owned_solver_not_run",
    "real_handoff_materialized_force_marker_owned_solver_not_run_reference_warn",
    "reference_override_materialized_force_marker_owned_solver_not_run_moment_origin_warn",
]
BLContractPolicyType = Literal[
    "not_required_for_baseline",
    "not_default",
    "promotion_only_when_hpa_mdo_owns_handoff_topology",
]
GmshBoundaryRecoveryPolicyType = Literal[
    "baseline_gmsh_backend_boundary_recovery",
    "core_tetra_only_after_owned_boundary_handoff",
    "not_allowed_as_owned_boundary_handoff",
]


class ComponentFamilyRouteReadiness(BaseModel):
    component: ComponentType
    geometry_family: GeometryFamilyType
    default_route: MeshingRouteType
    recommended_primary_geometry_family: GeometryFamilyType | None = None
    recommended_primary_route: MeshingRouteType | None = None
    backend: str = "gmsh"
    backend_capability: str
    provider_strategy: str
    productization_status: ProductizationStatusType
    route_role: RouteRoleType
    su2_status: SU2ReadinessStatusType
    bl_contract_policy: BLContractPolicyType
    gmsh_boundary_recovery_policy: GmshBoundaryRecoveryPolicyType
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class ComponentFamilyRouteReadinessReport(BaseModel):
    schema_version: Literal["component_family_route_readiness.v1"] = (
        "component_family_route_readiness.v1"
    )
    target_pipeline: Literal["vsp_or_esp_to_gmsh_to_su2_for_hpa_main_wing_tail_fairing"] = (
        "vsp_or_esp_to_gmsh_to_su2_for_hpa_main_wing_tail_fairing"
    )
    primary_decision: Literal["switch_to_component_family_route_architecture"] = (
        "switch_to_component_family_route_architecture"
    )
    product_line_rule: str
    components: List[ComponentFamilyRouteReadiness]
    promotion_gates: List[str] = Field(default_factory=list)
    shell_v4_policy: Dict[str, str] = Field(default_factory=dict)
    gmsh_source_policy: Dict[str, str] = Field(default_factory=dict)
    route_order: List[str] = Field(default_factory=list)


def _backend_capability(route: MeshingRouteType) -> str:
    return str(route_spec(route)["backend_capability"])


def _row(
    *,
    component: ComponentType,
    geometry_family: GeometryFamilyType,
    default_route: MeshingRouteType,
    recommended_primary_geometry_family: GeometryFamilyType | None = None,
    recommended_primary_route: MeshingRouteType | None = None,
    provider_strategy: str,
    productization_status: ProductizationStatusType,
    route_role: RouteRoleType,
    su2_status: SU2ReadinessStatusType,
    bl_contract_policy: BLContractPolicyType,
    gmsh_boundary_recovery_policy: GmshBoundaryRecoveryPolicyType,
    blocking_reasons: List[str],
    next_actions: List[str],
    notes: List[str] | None = None,
) -> ComponentFamilyRouteReadiness:
    return ComponentFamilyRouteReadiness(
        component=component,
        geometry_family=geometry_family,
        default_route=default_route,
        recommended_primary_geometry_family=recommended_primary_geometry_family,
        recommended_primary_route=recommended_primary_route,
        backend_capability=_backend_capability(default_route),
        provider_strategy=provider_strategy,
        productization_status=productization_status,
        route_role=route_role,
        su2_status=su2_status,
        bl_contract_policy=bl_contract_policy,
        gmsh_boundary_recovery_policy=gmsh_boundary_recovery_policy,
        blocking_reasons=blocking_reasons,
        next_actions=next_actions,
        notes=[] if notes is None else notes,
    )


def build_component_family_route_readiness() -> ComponentFamilyRouteReadinessReport:
    lifting_surface_next_actions = [
        "build_geometry_family_smoke_before_bl_prelaunch",
        "promote_route_only_after_mesh_handoff_and_su2_handoff_exist",
        "keep_bl_transition_contract_as_promotion_gate_not_default_runtime",
    ]
    fairing_next_actions = [
        "add_family_specific_geometry_smoke",
        "prove_mesh_handoff_markers_before_su2_claims",
        "promote_to_product_line_only_after_convergence_gate_artifact",
    ]

    components = [
        _row(
            component="aircraft_assembly",
            geometry_family="thin_sheet_aircraft_assembly",
            default_route="gmsh_thin_sheet_aircraft_assembly",
            provider_strategy="openvsp_surface_intersection_formal_v1",
            productization_status="formal_v1",
            route_role="current_product_line",
            su2_status="baseline_productized",
            bl_contract_policy="not_required_for_baseline",
            gmsh_boundary_recovery_policy="baseline_gmsh_backend_boundary_recovery",
            blocking_reasons=[],
            next_actions=[
                "use_mesh_study_v1_before_alpha_sweep",
                "keep_convergence_gate_separate_from_run_success",
            ],
            notes=[
                "This remains the only package-native route that should be called productized today.",
            ],
        ),
        _row(
            component="main_wing",
            geometry_family="thin_sheet_lifting_surface",
            default_route="gmsh_thin_sheet_surface",
            recommended_primary_geometry_family="mesh_native_lifting_surface",
            recommended_primary_route="gmsh_mesh_native_lifting_surface",
            provider_strategy="esp_rebuilt_experimental_or_direct_cad",
            productization_status="experimental",
            route_role="experimental_and_diagnostic",
            su2_status="handoff_materialized_force_marker_owned_solver_not_run",
            bl_contract_policy="promotion_only_when_hpa_mdo_owns_handoff_topology",
            gmsh_boundary_recovery_policy="not_allowed_as_owned_boundary_handoff",
            blocking_reasons=[
                "step_brep_repair_route_not_primary_product_path",
                "shell_v4_root_last3_is_not_product_route",
                "explicit_bl_to_core_handoff_topology_not_owned",
                "main_wing_real_geometry_mesh_handoff_timeout",
                "main_wing_real_geometry_mesh3d_volume_insertion_timeout",
                "main_wing_solver_not_run",
                "convergence_gate_not_run",
            ],
            next_actions=[
                "mesh_native_indexed_surface_builder_missing",
                "mesh_native_topology_gate_missing",
                "mesh_native_gmsh_discrete_volume_smoke_missing",
                "repair_real_main_wing_mesh3d_volume_insertion_policy",
                "run_solver_only_after_force_marker_and_real_geometry_evidence",
                "keep_bl_transition_contract_as_promotion_gate_not_default_runtime",
            ],
            notes=[
                "shell_v3 is the frozen geometry/coarse CFD reference.",
                "shell_v4 is a BL diagnostic and solver-entry exploration branch.",
                "main_wing_esp_rebuilt_geometry_smoke_available",
                "main_wing_real_mesh_handoff_probe_timeout_available",
                "main_wing_mesh_handoff_smoke_available_non_bl_synthetic",
                "main_wing_su2_handoff_materialization_smoke_available",
                "main_wing_component_specific_force_marker_available",
                "STEP/BREP repair evidence is now diagnostic evidence for route retirement, not the product critical path.",
            ],
        ),
        _row(
            component="tail_wing",
            geometry_family="thin_sheet_lifting_surface",
            default_route="gmsh_thin_sheet_surface",
            provider_strategy="esp_rebuilt_experimental_or_direct_cad",
            productization_status="registered_not_productized",
            route_role="registered_future_route",
            su2_status="handoff_materialized_force_marker_owned_solver_not_run",
            bl_contract_policy="not_default",
            gmsh_boundary_recovery_policy="core_tetra_only_after_owned_boundary_handoff",
            blocking_reasons=[
                "tail_real_geometry_mesh_handoff_blocked_surface_only",
                "tail_naive_gmsh_heal_solidification_no_volume",
                "tail_explicit_volume_route_blocked_by_orientation_or_baffle_plc",
                "tail_surface_only_mesh_not_su2_volume_handoff",
                "tail_wing_solver_not_run",
                "convergence_gate_not_run",
            ],
            next_actions=[
                "repair_explicit_tail_volume_orientation_or_baffle_surface_ownership",
                "run_solver_only_after_force_marker_and_real_geometry_evidence",
                "keep_bl_transition_contract_as_promotion_gate_not_default_runtime",
            ],
            notes=[
                "tail_wing_esp_rebuilt_geometry_smoke_available",
                "tail_wing_real_mesh_handoff_probe_surface_only_blocker_available",
                "tail_wing_surface_mesh_probe_available_not_su2_ready",
                "tail_wing_solidification_probe_naive_heal_no_volume",
                "tail_wing_explicit_volume_route_probe_blocked",
                "tail_wing_mesh_handoff_smoke_available_non_bl_synthetic",
                "tail_wing_su2_handoff_materialization_smoke_available",
                "tail_wing_specific_force_marker_available",
            ],
        ),
        _row(
            component="horizontal_tail",
            geometry_family="thin_sheet_lifting_surface",
            default_route="gmsh_thin_sheet_surface",
            provider_strategy="esp_rebuilt_experimental_or_direct_cad",
            productization_status="registered_not_productized",
            route_role="registered_future_route",
            su2_status="blocked_until_route_smoke",
            bl_contract_policy="not_default",
            gmsh_boundary_recovery_policy="core_tetra_only_after_owned_boundary_handoff",
            blocking_reasons=[
                "horizontal_tail_backend_not_productized",
                "tail_specific_geometry_smoke_missing",
            ],
            next_actions=lifting_surface_next_actions,
        ),
        _row(
            component="vertical_tail",
            geometry_family="thin_sheet_lifting_surface",
            default_route="gmsh_thin_sheet_surface",
            provider_strategy="esp_rebuilt_experimental_or_direct_cad",
            productization_status="registered_not_productized",
            route_role="registered_future_route",
            su2_status="blocked_until_route_smoke",
            bl_contract_policy="not_default",
            gmsh_boundary_recovery_policy="core_tetra_only_after_owned_boundary_handoff",
            blocking_reasons=[
                "vertical_tail_backend_not_productized",
                "tail_specific_geometry_smoke_missing",
            ],
            next_actions=lifting_surface_next_actions,
        ),
        _row(
            component="fairing_solid",
            geometry_family="closed_solid",
            default_route="gmsh_closed_solid_volume",
            provider_strategy="direct_cad_or_future_fairing_provider",
            productization_status="registered_not_productized",
            route_role="registered_future_route",
            su2_status="reference_override_materialized_force_marker_owned_solver_not_run_moment_origin_warn",
            bl_contract_policy="not_default",
            gmsh_boundary_recovery_policy="baseline_gmsh_backend_boundary_recovery",
            blocking_reasons=[
                "fairing_solver_not_run",
                "convergence_gate_not_run",
                "fairing_moment_origin_policy_incomplete_for_moment_coefficients",
            ],
            next_actions=[
                "run_real_fairing_solver_smoke_only_after_reference_policy_is_explicit",
                "replace_borrowed_zero_moment_origin_before_moment_coefficients_are_trusted",
                "promote_to_product_line_only_after_convergence_gate_artifact",
            ],
            notes=[
                "fairing_solid_real_geometry_smoke_available",
                "fairing_solid_real_mesh_handoff_probe_pass_available",
                "fairing_solid_real_su2_handoff_probe_available",
                "fairing_solid_reference_policy_probe_available",
                "fairing_solid_reference_override_su2_handoff_probe_available",
                "fairing_solid_mesh_handoff_smoke_available",
                "fairing_component_specific_force_marker_available_in_mesh_handoff_smoke",
                "su2_backend_materializes_fairing_solid_marker_without_running_su2",
                "fairing_solid_su2_handoff_materialization_smoke_available",
            ],
        ),
        _row(
            component="fairing_vented",
            geometry_family="perforated_solid",
            default_route="gmsh_perforated_solid_volume",
            provider_strategy="direct_cad_or_future_fairing_provider",
            productization_status="registered_not_productized",
            route_role="registered_future_route",
            su2_status="blocked_until_route_smoke",
            bl_contract_policy="not_default",
            gmsh_boundary_recovery_policy="baseline_gmsh_backend_boundary_recovery",
            blocking_reasons=[
                "fairing_vented_backend_not_productized",
                "perforation_ownership_and_marker_contract_missing",
            ],
            next_actions=fairing_next_actions,
        ),
    ]

    return ComponentFamilyRouteReadinessReport(
        product_line_rule=(
            "Do not promote a component family by making one shell_v4 fixture pass; promote it only "
            "after provider, meshing, mesh_handoff, su2_handoff, and convergence artifacts exist."
        ),
        components=components,
        promotion_gates=[
            "provider_materialized_or_formal_source_available",
            "geometry_family_classifier_resolved",
            "route_specific_mesh_smoke_completed",
            "mesh_handoff_v1_written",
            "su2_handoff_v1_written",
            "convergence_gate_v1_reported",
            "bl_transition_contract_passed_only_for_bl_promotions",
            "mesh_native_indexed_surface_topology_gate_passed_before_primary_main_wing_promotion",
            "mesh_native_su2_marker_smoke_passed_before_primary_main_wing_promotion",
        ],
        shell_v4_policy={
            "role": "diagnostic_regression_branch",
            "root_last3_policy": "not_a_product_route",
            "root_last4_policy": "overlap_non_regression_only",
            "promotion_rule": "no_full_prelaunch_until_handoff_topology_is_owned",
        },
        gmsh_source_policy={
            "primary_use": "forensics_and_instrumentation",
            "do_not_use_as": "primary_product_repair_path",
            "fork_threshold": "only_after_reproducible_cross_fixture_gmsh_bug",
        },
        route_order=[
            "aircraft_assembly_formal_v1_baseline",
            "component_family_route_matrix",
            "main_wing_mesh-native_primary_route_contract",
            "robust_non_bl_or_baseline_mesh_route",
            "su2_baseline_and_convergence_gate",
            "bl_route_promotion_after_owned_handoff_topology",
        ],
    )


def _render_markdown(report: ComponentFamilyRouteReadinessReport) -> str:
    lines = [
        "# Component Family Route Readiness v1",
        "",
        f"- target_pipeline: `{report.target_pipeline}`",
        f"- primary_decision: `{report.primary_decision}`",
        f"- product_line_rule: {report.product_line_rule}",
        "",
        "## Route Matrix",
        "",
        "| component | status | route role | default route | recommended primary route | SU2 | BL policy | Gmsh boundary policy |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report.components:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row.component}`",
                    f"`{row.productization_status}`",
                    f"`{row.route_role}`",
                    f"`{row.default_route}`",
                    (
                        f"`{row.recommended_primary_route}`"
                        if row.recommended_primary_route is not None
                        else "`same_as_default`"
                    ),
                    f"`{row.su2_status}`",
                    f"`{row.bl_contract_policy}`",
                    f"`{row.gmsh_boundary_recovery_policy}`",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Promotion Gates",
            "",
            *[f"- `{gate}`" for gate in report.promotion_gates],
            "",
            "## shell_v4 Policy",
            "",
            *[f"- `{key}`: `{value}`" for key, value in report.shell_v4_policy.items()],
            "",
            "## Gmsh Source Policy",
            "",
            *[f"- `{key}`: `{value}`" for key, value in report.gmsh_source_policy.items()],
            "",
            "## Mesh-Native Main Wing Policy",
            "",
            "- mesh-native indexed surfaces are the recommended primary CFD geometry route for the main wing.",
            "- STEP/BREP repair remains useful as diagnostic evidence and fallback comparison, not as the product critical path.",
            "",
            "## Blocking Reasons",
            "",
        ]
    )
    for row in report.components:
        if not row.blocking_reasons:
            continue
        lines.append(f"### `{row.component}`")
        lines.extend(f"- `{reason}`" for reason in row.blocking_reasons)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_component_family_route_readiness_report(out_dir: Path) -> Dict[str, Path]:
    report = build_component_family_route_readiness()
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "component_family_route_readiness.v1.json"
    markdown_path = out_dir / "component_family_route_readiness.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
