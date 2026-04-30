from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Literal

from pydantic import BaseModel, Field

from .errors import TopologyUnsupportedError
from .geometry.loader import load_geometry
from .geometry.validator import classify_geometry_family, validate_component_geometry
from .mesh.recipes import build_recipe
from .route_readiness import build_component_family_route_readiness
from .schema import ComponentType, GeometryFamilyType, MeshJobConfig, MeshingRouteType


SMOKE_COMPONENTS: tuple[ComponentType, ...] = (
    "aircraft_assembly",
    "main_wing",
    "tail_wing",
    "horizontal_tail",
    "vertical_tail",
    "fairing_solid",
    "fairing_vented",
)

ValidationStatusType = Literal["pass", "fail"]
RecipeStatusType = Literal["resolved", "failed"]
SmokeStatusType = Literal["dispatch_smoke_pass", "dispatch_smoke_fail"]
PromotionStatusType = Literal[
    "not_a_promotion_gate",
    "blocked_before_mesh_handoff",
    "blocked_before_su2_handoff",
    "blocked_before_solver_convergence",
]


class ComponentFamilyRouteSmokeMatrixRow(BaseModel):
    component: ComponentType
    fixture_kind: Literal["synthetic_stub_step"] = "synthetic_stub_step"
    source_path: str
    geometry_source: str
    geometry_family: GeometryFamilyType
    classification_provenance: str
    validation_status: ValidationStatusType
    recipe_status: RecipeStatusType
    smoke_status: SmokeStatusType
    productization_status: str
    route_role: str
    meshing_route: MeshingRouteType | None = None
    backend: str | None = None
    backend_capability: str | None = None
    mesh_handoff_status: Literal["not_run"] = "not_run"
    su2_handoff_status: Literal["not_run"] = "not_run"
    convergence_gate_status: Literal["not_run"] = "not_run"
    promotion_status: PromotionStatusType
    blocking_reasons: List[str] = Field(default_factory=list)
    guarantees: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class ComponentFamilyRouteSmokeMatrixReport(BaseModel):
    schema_version: Literal["component_family_route_smoke_matrix.v1"] = (
        "component_family_route_smoke_matrix.v1"
    )
    target_pipeline: Literal["vsp_or_esp_to_gmsh_to_su2_for_hpa_main_wing_tail_fairing"] = (
        "vsp_or_esp_to_gmsh_to_su2_for_hpa_main_wing_tail_fairing"
    )
    execution_mode: Literal["pre_mesh_dispatch_smoke"] = "pre_mesh_dispatch_smoke"
    no_gmsh_execution: bool = True
    no_su2_execution: bool = True
    report_status: Literal["completed", "failed"] = "completed"
    rows: List[ComponentFamilyRouteSmokeMatrixRow]
    scope_policy: Dict[str, str] = Field(default_factory=dict)
    global_limitations: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)


def _write_stub_step(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")


def _row_promotion_status(component: ComponentType) -> PromotionStatusType:
    if component == "aircraft_assembly":
        return "not_a_promotion_gate"
    if component == "main_wing":
        return "blocked_before_solver_convergence"
    if component == "fairing_solid":
        return "blocked_before_solver_convergence"
    if component == "tail_wing":
        return "blocked_before_solver_convergence"
    return "blocked_before_mesh_handoff"


def _smoke_row(component: ComponentType, out_dir: Path) -> ComponentFamilyRouteSmokeMatrixRow:
    readiness = {
        row.component: row for row in build_component_family_route_readiness().components
    }[component]
    fixture_path = out_dir / "artifacts" / "fixtures" / f"{component}.step"
    _write_stub_step(fixture_path)

    config = MeshJobConfig(
        component=component,
        geometry=fixture_path,
        out_dir=out_dir / "artifacts" / "cases" / component,
        geometry_source="direct_cad",
    )
    handle = load_geometry(config.geometry, config)
    classification = classify_geometry_family(handle, config)
    validation = validate_component_geometry(handle, classification, config)

    recipe_status: RecipeStatusType = "failed"
    meshing_route = None
    backend = None
    backend_capability = None
    recipe_error = None
    if validation.ok:
        try:
            recipe = build_recipe(handle, classification, config)
            recipe_status = "resolved"
            meshing_route = recipe.meshing_route
            backend = recipe.backend
            backend_capability = recipe.backend_capability
        except TopologyUnsupportedError as exc:
            recipe_error = str(exc)

    smoke_pass = validation.ok and recipe_status == "resolved"
    guarantees = [
        "fixture_loaded",
        "component_family_classified",
        "component_family_validated",
        "route_dispatch_resolved",
    ]
    limitations = [
        "synthetic STEP fixture is a route-skeleton fixture, not aerodynamic geometry",
        "Gmsh was not executed",
        "SU2_CFD was not executed",
        "mesh_handoff.v1 was not emitted",
        "su2_handoff.v1 was not emitted",
        "convergence_gate.v1 was not emitted",
    ]
    if recipe_error is not None:
        limitations.append(f"recipe_error={recipe_error}")

    return ComponentFamilyRouteSmokeMatrixRow(
        component=component,
        source_path=str(fixture_path),
        geometry_source=classification.geometry_source,
        geometry_family=classification.geometry_family,
        classification_provenance=classification.provenance,
        validation_status="pass" if validation.ok else "fail",
        recipe_status=recipe_status,
        smoke_status="dispatch_smoke_pass" if smoke_pass else "dispatch_smoke_fail",
        productization_status=readiness.productization_status,
        route_role=readiness.route_role,
        meshing_route=meshing_route,
        backend=backend,
        backend_capability=backend_capability,
        promotion_status=_row_promotion_status(component),
        blocking_reasons=list(readiness.blocking_reasons),
        guarantees=guarantees if smoke_pass else guarantees[:2],
        limitations=limitations,
    )


def build_component_family_route_smoke_matrix(
    out_dir: Path,
) -> ComponentFamilyRouteSmokeMatrixReport:
    rows = [_smoke_row(component, out_dir) for component in SMOKE_COMPONENTS]
    report_status = (
        "completed"
        if all(row.smoke_status == "dispatch_smoke_pass" for row in rows)
        else "failed"
    )
    return ComponentFamilyRouteSmokeMatrixReport(
        report_status=report_status,
        rows=rows,
        scope_policy={
            "root_last3_policy": "excluded_not_product_route",
            "root_last4_policy": "excluded_overlap_non_regression_only",
            "bl_runtime_policy": "not_executed",
            "gmsh_policy": "not_executed",
            "su2_policy": "not_executed",
        },
        global_limitations=[
            "This is a report-only component-family smoke matrix.",
            "It checks route architecture coverage for VSP/ESP -> Gmsh -> SU2 handoff planning.",
            "A pass here means the route skeleton is visible and internally classified.",
            "It is not a production mesh pass, solver pass, BL promotion, or CFD credibility claim.",
        ],
        next_actions=[
            "replace synthetic fairing fixture with real fairing geometry before solver claims",
            "replace synthetic main_wing fixture with real ESP/VSP geometry before solver claims",
            "choose surface-only tail_wing mesh route or provider solidification before solver claims",
            "keep BL prelaunch excluded until handoff topology ownership passes",
        ],
    )


def _render_markdown(report: ComponentFamilyRouteSmokeMatrixReport) -> str:
    lines = [
        "# Component Family Route Smoke Matrix v1",
        "",
        "This is a pre-mesh dispatch smoke matrix. It does not execute Gmsh, BL runtime, or SU2.",
        "",
        f"- target_pipeline: `{report.target_pipeline}`",
        f"- execution_mode: `{report.execution_mode}`",
        f"- report_status: `{report.report_status}`",
        f"- no_gmsh_execution: `{report.no_gmsh_execution}`",
        f"- no_su2_execution: `{report.no_su2_execution}`",
        "",
        "## Matrix",
        "",
        "| component | smoke | family | route | productization | mesh_handoff | SU2 | promotion |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report.rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row.component}`",
                    f"`{row.smoke_status}`",
                    f"`{row.geometry_family}`",
                    f"`{row.meshing_route}`",
                    f"`{row.productization_status}`",
                    f"`{row.mesh_handoff_status}`",
                    f"`{row.su2_handoff_status}`",
                    f"`{row.promotion_status}`",
                ]
            )
            + " |"
        )

    lines.extend(["", "## Scope Policy", ""])
    lines.extend(f"- `{key}`: `{value}`" for key, value in report.scope_policy.items())
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.global_limitations)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    return "\n".join(lines).rstrip() + "\n"


def write_component_family_route_smoke_matrix_report(out_dir: Path) -> Dict[str, Path]:
    report = build_component_family_route_smoke_matrix(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "component_family_route_smoke_matrix.v1.json"
    markdown_path = out_dir / "component_family_route_smoke_matrix.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
