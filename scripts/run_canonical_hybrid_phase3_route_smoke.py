#!/usr/bin/env python3
"""Run Phase 3 viscous route-smoke for the canonical hybrid half-wing CFD route."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
SCRIPT_DIR = REPO_ROOT / "scripts"
for path in (HPA_MESHING_SRC, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    _add_discrete_marked_mesh_surfaces,
    _add_marked_mesh_surfaces,
    _line_between,
)
from hpa_meshing.mesh_native.blackcat import _subdivide_spanwise_stations  # noqa: E402
from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    BlockBoundaryFace,
    WingBoundaryLayerBlock,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.su2_structured import (  # noqa: E402
    SU2_PRISM,
    SU2_TETRAHEDRON,
    audit_su2_boundary_face_ownership,
    audit_su2_case_markers,
    parse_su2_marker_summary,
    _su2_volume_text,
    _volume_element_faces,
)
from hpa_meshing.mesh_native.wing_surface import Face, Reference, SurfaceMesh, WingSpec  # noqa: E402
from run_canonical_hybrid_phase2_pressure_sanity import (  # noqa: E402
    DEFAULT_AVL_PATH,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SECTION_TABLE_PATH,
    DEFAULT_SOLVER_COMMAND,
    build_phase2_pressure_surface,
    parse_su2_dual_control_volume_quality,
    _airfoil_source_transition_spans,
    _bounds,
    _closure_sections_for_spans,
    _forces_breakdown_report,
    _half_stations_from_rows,
    _half_farfield_vertices,
    _read_avl_moment_origin,
    _read_avl_reference,
    _read_csv_dicts,
    _run_solver,
)


DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "cfd_release_v0"
    / "route_smoke"
)
DEFAULT_POINTS_PER_SIDE = 6
DEFAULT_SPANWISE_SUBDIVISIONS = 4
DEFAULT_ROUTE_SMOKE_MAX_ITERATIONS = 500
DEFAULT_FIRST_LAYER_HEIGHT_M = 5.0e-5
DEFAULT_GROWTH_RATIO = 1.20
DEFAULT_BL_LAYERS = 24

VISCOUS_WALL_MARKERS = (
    "wing_upper",
    "wing_lower",
    "tip_wall",
    "te_wall",
    "closure_wall",
)
PRIMARY_FORCE_MARKERS = ("wing_upper", "wing_lower")
DIAGNOSTIC_FORCE_MARKERS = ("tip_wall", "te_wall", "closure_wall")
REQUIRED_MARKERS = (
    *VISCOUS_WALL_MARKERS,
    "root_symmetry",
    "farfield",
)

GMSH_TETRA = "4"
GMSH_HEXAHEDRON = "5"
GMSH_PRISM = "6"
GMSH_PYRAMID = "7"
GMSH_HYBRID_BL_TYPES = {GMSH_HEXAHEDRON, GMSH_PRISM}
SU2_TRIANGLE = 5

MIN_ROUTE_DUAL_ORTHOGONALITY_DEG = 1.0
MAX_ROUTE_DUAL_FACE_AREA_ASPECT_RATIO = 1.0e7
MAX_ROUTE_DUAL_SUB_VOLUME_RATIO = 1.0e7


def build_phase3_route_smoke_surface(
    section_table_path: Path | str = DEFAULT_SECTION_TABLE_PATH,
    *,
    points_per_side: int = DEFAULT_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
):
    surface = build_phase2_pressure_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    metadata = dict(surface.metadata)
    metadata.update(
        {
            "phase_gate": "ROUTE_SMOKE_PASS",
            "mesh_recipe": (
                "Gmsh boundary-layer extrusion preserves prism/hexa BL cells; "
                "Gmsh tetrahedra fill only the core."
            ),
            "force_monitoring_markers": list(VISCOUS_WALL_MARKERS),
            "primary_force_markers": list(PRIMARY_FORCE_MARKERS),
            "diagnostic_force_markers": list(DIAGNOSTIC_FORCE_MARKERS),
        }
    )
    return type(surface)(
        vertices=list(surface.vertices),
        faces=list(surface.faces),
        metadata=metadata,
    )


def route_smoke_cfg_text(
    *,
    ref_area: float,
    ref_length: float,
    ref_origin: tuple[float, float, float],
    velocity_mps: float,
    alpha_deg: float,
    max_iterations: int,
) -> str:
    alpha_rad = math.radians(alpha_deg)
    vx = velocity_mps * math.cos(alpha_rad)
    vz = velocity_mps * math.sin(alpha_rad)
    heatflux_entries = ", ".join(
        f"{marker}, 0.0" for marker in VISCOUS_WALL_MARKERS
    )
    return "\n".join(
        [
            "% Canonical hybrid half-wing Phase 3 viscous route-smoke.",
            "% Hybrid BL cells are preserved; do not treat this as grid-ladder truth.",
            "SOLVER= INC_RANS",
            "KIND_TURB_MODEL= SA",
            "MATH_PROBLEM= DIRECT",
            "RESTART_SOL= NO",
            "SYSTEM_MEASUREMENTS= SI",
            "INC_NONDIM= INITIAL_VALUES",
            "INC_DENSITY_MODEL= CONSTANT",
            "INC_DENSITY_INIT= 1.225000",
            "INC_TEMPERATURE_INIT= 288.150000",
            "VISCOSITY_MODEL= CONSTANT_VISCOSITY",
            "MU_CONSTANT= 1.789400e-05",
            "FREESTREAM_NU_FACTOR= 3.0",
            f"INC_VELOCITY_INIT= ( {vx:.6f}, 0.000000, {vz:.6f} )",
            f"AOA= {alpha_deg:.6f}",
            "SIDESLIP_ANGLE= 0.000000",
            f"REF_AREA= {ref_area:.9f}",
            f"REF_LENGTH= {ref_length:.9f}",
            f"REF_ORIGIN_MOMENT_X= {ref_origin[0]:.9f}",
            f"REF_ORIGIN_MOMENT_Y= {ref_origin[1]:.9f}",
            f"REF_ORIGIN_MOMENT_Z= {ref_origin[2]:.9f}",
            "MESH_FILENAME= mesh.su2",
            "MESH_FORMAT= SU2",
            f"MARKER_HEATFLUX= ( {heatflux_entries} )",
            "MARKER_SYM= ( root_symmetry )",
            "MARKER_FAR= ( farfield )",
            f"MARKER_MONITORING= ( {', '.join(VISCOUS_WALL_MARKERS)} )",
            f"MARKER_PLOTTING= ( {', '.join(VISCOUS_WALL_MARKERS)} )",
            "NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES",
            "CFL_NUMBER= 2.0",
            "CFL_ADAPT= NO",
            "MAX_DELTA_TIME= 1E6",
            "CONV_NUM_METHOD_FLOW= FDS",
            "MUSCL_FLOW= YES",
            "SLOPE_LIMITER_FLOW= NONE",
            "JST_SENSOR_COEFF= ( 0.0, 0.02 )",
            "TIME_DISCRE_FLOW= EULER_IMPLICIT",
            "CONV_NUM_METHOD_TURB= SCALAR_UPWIND",
            "MUSCL_TURB= NO",
            "SLOPE_LIMITER_TURB= VENKATAKRISHNAN",
            "TIME_DISCRE_TURB= EULER_IMPLICIT",
            "LINEAR_SOLVER= FGMRES",
            "LINEAR_SOLVER_PREC= ILU",
            "LINEAR_SOLVER_ERROR= 1E-8",
            "LINEAR_SOLVER_ITER= 10",
            f"ITER= {int(max_iterations)}",
            "CONV_FIELD= DRAG",
            "CONV_RESIDUAL_MINVAL= -9",
            "CONV_STARTITER= 10",
            "CONV_CAUCHY_ELEMS= 100",
            "CONV_CAUCHY_EPS= 1E-6",
            "CONV_FILENAME= history",
            "TABULAR_FORMAT= CSV",
            "RESTART_FILENAME= restart_flow",
            "VOLUME_FILENAME= flow",
            "SURFACE_FILENAME= surface_flow",
            "SCREEN_OUTPUT= (INNER_ITER, RMS_RES, AERO_COEFF)",
            "HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF)",
            "OUTPUT_FILES= (RESTART_ASCII, SURFACE_CSV)",
            "BREAKDOWN_FILENAME= forces_breakdown.dat",
            "WRT_FORCES_BREAKDOWN= YES",
            "",
        ]
    )


def evaluate_phase3_route_smoke_gate(report: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    mesh = _mapping(report.get("mesh"))
    solver = _mapping(report.get("solver"))
    history = _mapping(solver.get("history"))
    stability = _mapping(history.get("tail_stability"))
    marker_audit = _mapping(mesh.get("marker_audit"))
    mesh_gate = _mapping(mesh.get("mesh_quality_gate"))
    type_counts = {
        str(key): int(value)
        for key, value in _mapping(mesh.get("volume_element_type_counts")).items()
    }
    forces = _mapping(report.get("forces_breakdown"))
    primary = _mapping(report.get("primary_force_coefficients"))
    diagnostic = _mapping(report.get("diagnostic_force_coefficients"))
    dual_quality = _mapping(solver.get("dual_control_volume_quality"))

    if mesh.get("status") != "meshed":
        blockers.append("route_smoke_mesh_not_meshed")
    if marker_audit.get("status") != "pass":
        blockers.append("route_smoke_marker_audit_not_pass")
    if mesh_gate.get("status") != "pass":
        blockers.append("route_smoke_mesh_quality_not_pass")
    if mesh.get("required_markers_present") is not True:
        blockers.append("route_smoke_required_markers_missing")
    if int(mesh.get("boundary_layer_cell_count") or 0) <= 0:
        blockers.append("route_smoke_boundary_layer_cells_missing")
    if not any(type_counts.get(kind, 0) > 0 for kind in GMSH_HYBRID_BL_TYPES):
        blockers.append("route_smoke_hybrid_bl_cells_missing")
    if type_counts.get(GMSH_TETRA, 0) <= 0:
        blockers.append("route_smoke_core_tetra_cells_missing")
    if (
        int(mesh.get("volume_element_count") or 0) > 0
        and type_counts.get(GMSH_TETRA, 0) == int(mesh.get("volume_element_count") or 0)
    ):
        blockers.append("route_smoke_all_tet_mesh_forbidden")
    if int(mesh.get("max_farfield_vertex_incident_volume_cells") or 0) > 200:
        blockers.append("route_smoke_farfield_vertex_incident_cell_count_exceeds_200")

    if solver.get("run_status") != "completed":
        blockers.append("route_smoke_solver_not_completed")
    if int(history.get("row_count") or 0) < 100:
        blockers.append("route_smoke_history_too_short")
    if forces.get("status") != "available":
        blockers.append("route_smoke_forces_breakdown_missing")
    if dual_quality.get("status") != "available":
        blockers.append("route_smoke_su2_dual_quality_missing")
    else:
        min_orthogonality = _float_or_none(dual_quality.get("min_orthogonality_deg"))
        max_aspect = _float_or_none(dual_quality.get("max_cv_face_area_aspect_ratio"))
        max_sub_volume = _float_or_none(dual_quality.get("max_cv_sub_volume_ratio"))
        if (
            min_orthogonality is None
            or min_orthogonality < MIN_ROUTE_DUAL_ORTHOGONALITY_DEG
        ):
            blockers.append("route_smoke_su2_dual_min_orthogonality_pathological")
        if max_aspect is None or max_aspect > MAX_ROUTE_DUAL_FACE_AREA_ASPECT_RATIO:
            blockers.append("route_smoke_su2_dual_face_area_aspect_ratio_pathological")
        if max_sub_volume is None or max_sub_volume > MAX_ROUTE_DUAL_SUB_VOLUME_RATIO:
            blockers.append("route_smoke_su2_dual_sub_volume_ratio_pathological")

    primary_cd = _float_or_none(primary.get("cd"))
    pressure_cd = _float_or_none(primary.get("pressure_cd"))
    closure_cd = _float_or_none(_mapping(diagnostic.get("closure_wall")).get("cd"))
    if primary_cd is None:
        blockers.append("route_smoke_primary_cd_missing")
    elif abs(primary_cd) > 0.15:
        blockers.append("route_smoke_primary_cd_exceeds_0p15")
    elif abs(primary_cd) > 0.05:
        warnings.append("route_smoke_primary_cd_high_but_below_smoke_blocker")
    if pressure_cd is not None and abs(pressure_cd) > 0.12:
        blockers.append("route_smoke_primary_pressure_cd_too_large")
    if closure_cd is None:
        blockers.append("route_smoke_closure_cd_missing")
    elif primary_cd is not None and abs(closure_cd) > max(0.05, 0.5 * abs(primary_cd)):
        blockers.append("route_smoke_closure_cd_dominates")

    cl_span = _float_or_none(stability.get("cl_relative_span"))
    cd_span = _float_or_none(stability.get("cd_relative_span"))
    if cl_span is None or cd_span is None or cl_span > 0.05 or cd_span > 0.05:
        blockers.append("route_smoke_force_window_not_stable")

    status = "pass" if not blockers else "fail"
    return {
        "status": status,
        "release_status": "ROUTE_SMOKE_PASS" if status == "pass" else None,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "primary_force_coefficients": dict(primary),
        "diagnostic_force_coefficients": dict(diagnostic),
        "stable_window": dict(stability),
    }


def mark_manifest_route_smoke_pass(
    manifest_path: Path | str,
    summary: Mapping[str, Any],
) -> None:
    path = Path(manifest_path)
    manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    statuses = list(manifest.get("passed_gate_statuses") or [])
    for status in ("TOOLCHAIN_PASS", "PRESSURE_SANITY_PASS", "ROUTE_SMOKE_PASS"):
        if status not in statuses:
            statuses.append(status)
    manifest["passed_gate_statuses"] = statuses
    manifest["next_required_gate_status"] = "GRID_LADDER_PASS"
    manifest["phase3_route_smoke"] = {
        "status": "ROUTE_SMOKE_PASS",
        "report_path": summary.get("report_path"),
        "case_dir": summary.get("case_dir"),
        "mesh_recipe": _mapping(_mapping(summary.get("surface")).get("metadata")).get(
            "mesh_recipe"
        ),
    }
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def run_phase3_route_smoke(
    *,
    section_table_path: Path = DEFAULT_SECTION_TABLE_PATH,
    avl_path: Path = DEFAULT_AVL_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_su2: bool,
    update_manifest: bool = False,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    points_per_side: int = DEFAULT_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = DEFAULT_BL_LAYERS,
    wing_mesh_size: float = 0.5,
    farfield_mesh_size: float = 8.0,
    max_iterations: int = DEFAULT_ROUTE_SMOKE_MAX_ITERATIONS,
    solver_command: str = DEFAULT_SOLVER_COMMAND,
    threads: int = 4,
    timeout_seconds: float = 2400.0,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    ref = _read_avl_reference(avl_path)
    ref_origin = _read_avl_moment_origin(avl_path)
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    mesh_report = write_phase3_hybrid_mesh(
        surface,
        output_dir,
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
        wing_mesh_size=wing_mesh_size,
        farfield_mesh_size=farfield_mesh_size,
    )
    cfg_path = output_dir / "su2_runtime.cfg"
    cfg_path.write_text(
        route_smoke_cfg_text(
            ref_area=0.5 * ref["sref"],
            ref_length=ref["cref"],
            ref_origin=ref_origin,
            velocity_mps=6.5,
            alpha_deg=0.0,
            max_iterations=max_iterations,
        ),
        encoding="utf-8",
    )
    mesh_report["marker_audit"] = audit_su2_case_markers(output_dir / "mesh.su2", cfg_path)
    solver_report = _run_solver(
        output_dir,
        run_su2=run_su2,
        solver_command=solver_command,
        threads=threads,
        timeout_seconds=timeout_seconds,
    )
    forces_breakdown = _forces_breakdown_report(output_dir / "forces_breakdown.dat")
    primary_coefficients, diagnostic_coefficients = _force_coefficients_from_breakdown(
        forces_breakdown
    )
    report: dict[str, Any] = {
        "schema_version": "canonical_hybrid_phase3_route_smoke.v0",
        "route": "canonical_hybrid_halfwing_v0",
        "phase_gate": "ROUTE_SMOKE_PASS",
        "case_dir": str(output_dir),
        "section_table_path": str(section_table_path),
        "surface": {
            "marker_counts": surface.marker_counts(),
            "metadata": surface.metadata,
        },
        "mesh": mesh_report,
        "runtime_cfg_path": str(cfg_path),
        "solver": solver_report,
        "forces_breakdown": forces_breakdown,
        "primary_force_coefficients": primary_coefficients,
        "diagnostic_force_coefficients": diagnostic_coefficients,
        "engineering_assessment": {
            "scope": "wall_resolved_route_smoke_half_wing",
            "trust_boundary": (
                "This can clear only the first viscous route-smoke gate. It is not a "
                "coarse/medium/fine grid-ladder result and must not be used as final "
                "HPA drag truth."
            ),
        },
        "elapsed_s": time.monotonic() - start,
    }
    gate = evaluate_phase3_route_smoke_gate(report)
    report["gate"] = gate
    report_path = output_dir / "route_smoke_report.json"
    md_path = output_dir / "route_smoke_report.md"
    report["report_path"] = str(report_path)
    report["markdown_report_path"] = str(md_path)
    if update_manifest and gate["status"] == "pass":
        mark_manifest_route_smoke_pass(manifest_path, report)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return report


def write_phase3_hybrid_mesh(
    surface,
    case_dir: Path | str,
    *,
    first_layer_height_m: float,
    growth_ratio: float,
    bl_layers: int,
    wing_mesh_size: float,
    farfield_mesh_size: float,
) -> dict[str, Any]:
    import gmsh

    case_path = Path(case_dir)
    case_path.mkdir(parents=True, exist_ok=True)
    msh_path = case_path / "mesh.msh"
    su2_path = case_path / "mesh.su2"
    bounds = _bounds(surface.vertices)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Geometry.ExtrudeReturnLateralEntities", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.Algorithm", 5)
        gmsh.option.setNumber("Mesh.Algorithm3D", 10)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.model.add("canonical_hybrid_phase3_route_smoke")
        point_tags = [
            gmsh.model.geo.addPoint(x, y, z, wing_mesh_size)
            for x, y, z in surface.vertices
        ]
        line_cache: dict[tuple[int, int], tuple[int, int, int]] = {}
        surfaces_by_marker = _add_marked_mesh_surfaces(
            gmsh,
            surface.faces,
            vertices=surface.vertices,
            triangulation_policy="shorter_diagonal",
            point_tags=point_tags,
            line_cache=line_cache,
            node_offset=0,
        )
        wall_surface_tags = [
            int(tag)
            for marker in VISCOUS_WALL_MARKERS
            for tag in surfaces_by_marker.get(marker, [])
        ]
        gmsh.model.geo.synchronize()
        heights = _layer_cumulative_heights(first_layer_height_m, growth_ratio, bl_layers)
        extbl = gmsh.model.geo.extrudeBoundaryLayer(
            [(2, tag) for tag in wall_surface_tags],
            [1] * int(bl_layers),
            heights,
            True,
            False,
        )
        bl_volume_tags: list[int] = []
        bl_top_surface_tags: list[int] = []
        for index in range(1, len(extbl)):
            if int(extbl[index][0]) == 3:
                bl_volume_tags.append(int(extbl[index][1]))
                if int(extbl[index - 1][0]) == 2:
                    bl_top_surface_tags.append(int(extbl[index - 1][1]))
        gmsh.model.geo.synchronize()
        farfield_vertices, symmetry_surface_tags, farfield_surface_tags = (
            _add_farfield_box_with_symmetry_hole(
                gmsh,
                bounds=bounds,
                bl_top_surface_tags=bl_top_surface_tags,
                farfield_mesh_size=farfield_mesh_size,
            )
        )
        core_volume = gmsh.model.geo.addVolume(
            [
                gmsh.model.geo.addSurfaceLoop(
                    [*bl_top_surface_tags, *symmetry_surface_tags, *farfield_surface_tags]
                )
            ]
        )
        gmsh.model.geo.synchronize()

        physical_groups: dict[str, Any] = {}
        for marker, tags in surfaces_by_marker.items():
            group = gmsh.model.addPhysicalGroup(2, tags)
            gmsh.model.setPhysicalName(2, group, marker)
            physical_groups[marker] = {
                "dimension": 2,
                "physical_tag": int(group),
                "entity_count": len(tags),
            }
        symmetry_group = gmsh.model.addPhysicalGroup(2, symmetry_surface_tags)
        gmsh.model.setPhysicalName(2, symmetry_group, "root_symmetry")
        physical_groups["root_symmetry"] = {
            "dimension": 2,
            "physical_tag": int(symmetry_group),
            "entity_count": len(symmetry_surface_tags),
        }
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
        gmsh.model.setPhysicalName(2, farfield_group, "farfield")
        physical_groups["farfield"] = {
            "dimension": 2,
            "physical_tag": int(farfield_group),
            "entity_count": len(farfield_surface_tags),
        }
        fluid_group = gmsh.model.addPhysicalGroup(3, [core_volume, *bl_volume_tags])
        gmsh.model.setPhysicalName(3, fluid_group, "fluid")
        physical_groups["fluid"] = {
            "dimension": 3,
            "physical_tag": int(fluid_group),
            "entity_count": 1 + len(bl_volume_tags),
        }

        gmsh.option.setNumber("Mesh.MeshSizeMin", min(first_layer_height_m, wing_mesh_size))
        gmsh.option.setNumber("Mesh.MeshSizeMax", farfield_mesh_size)
        gmsh.model.mesh.generate(2)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(msh_path))
        gmsh.write(str(su2_path))

        marker_summary = parse_su2_marker_summary(su2_path)
        mesh_quality = _hybrid_mesh_quality_metrics(gmsh, farfield_vertices)
        element_types, element_tags, _ = gmsh.model.mesh.getElements(3)
        type_counts = {
            str(int(kind)): len(tags) for kind, tags in zip(element_types, element_tags)
        }
        bl_cell_count, bl_cell_type_counts = _count_elements_for_entities(
            gmsh,
            3,
            bl_volume_tags,
        )
        core_cell_count, core_cell_type_counts = _count_elements_for_entities(
            gmsh,
            3,
            [core_volume],
        )
        marker_names = set(marker_summary["markers"])
        required_markers_present = all(marker in marker_names for marker in REQUIRED_MARKERS)
        return {
            "status": "meshed",
            "mesh_path": str(msh_path),
            "su2_mesh_path": str(su2_path),
            "marker_summary": marker_summary,
            "required_markers_present": required_markers_present,
            "volume_element_type_counts": type_counts,
            "volume_element_count": sum(type_counts.values()),
            "boundary_layer_cell_count": int(bl_cell_count),
            "boundary_layer_cell_type_counts": bl_cell_type_counts,
            "core_cell_count": int(core_cell_count),
            "core_cell_type_counts": core_cell_type_counts,
            "min_volume_quality": mesh_quality["min_volume_quality"],
            "non_positive_quality_count": mesh_quality["non_positive_quality_count"],
            "min_sicn": mesh_quality["min_sicn"],
            "non_positive_sicn_count": mesh_quality["non_positive_sicn_count"],
            "max_farfield_vertex_incident_volume_cells": mesh_quality[
                "max_farfield_vertex_incident_volume_cells"
            ],
            "mesh_quality_gate": _hybrid_mesh_quality_gate(mesh_quality),
            "physical_groups": physical_groups,
            "boundary_layer": {
                "first_layer_height_m": float(first_layer_height_m),
                "growth_ratio": float(growth_ratio),
                "layers": int(bl_layers),
                "total_thickness_m": heights[-1] if heights else 0.0,
            },
            "forbidden_route_checks": {
                "all_tet_global_star_bl_handoff": False,
                "boundary_layer_split_to_tetra": False,
                "closure_faces_merged_into_wing_wall": False,
            },
        }
    finally:
        gmsh.finalize()


def build_phase3_owned_boundary_layer_block(
    section_table_path: Path | str = DEFAULT_SECTION_TABLE_PATH,
    *,
    points_per_side: int = DEFAULT_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = DEFAULT_BL_LAYERS,
) -> tuple[WingBoundaryLayerBlock, set[int]]:
    rows = _read_csv_dicts(Path(section_table_path))
    base_stations = _half_stations_from_rows(rows, points_per_side=points_per_side)
    stations = (
        base_stations
        if spanwise_subdivisions <= 1
        else _subdivide_spanwise_stations(base_stations, spanwise_subdivisions)
    )
    closure_sections = _closure_sections_for_spans(
        stations,
        _airfoil_source_transition_spans(rows),
    )
    spec = WingSpec(
        stations=stations,
        side="half",
        te_rule="sharp",
        tip_rule="planar_cap",
        root_rule="symmetry",
        reference=Reference(sref_full=1.0, cref=1.0, bref_full=1.0),
        twist_axis_x=0.25,
    )
    block = build_wing_boundary_layer_block(
        spec,
        BoundaryLayerBlockSpec(
            first_layer_height_m=first_layer_height_m,
            growth_ratio=growth_ratio,
            layer_count=bl_layers,
        ),
    )
    return block, closure_sections


def write_phase3_owned_bl_prism_handoff_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = DEFAULT_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = DEFAULT_BL_LAYERS,
) -> dict[str, Any]:
    """Write the mesh-native owned BL as prism cells with split diagnostic markers.

    This is the first direct-handoff building block for the replacement backend:
    it owns the BL topology and marker surfaces without using Gmsh
    ``extrudeBoundaryLayer``. It is not a complete farfield/core CFD mesh until a
    conformal tetra core is merged onto ``bl_outer_interface``.
    """
    block, closure_sections = build_phase3_owned_boundary_layer_block(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
    )
    volume = _owned_bl_prism_volume(block, closure_sections)
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _su2_volume_text(
            volume,
            comments=(
                "% Canonical hybrid half-wing mesh-native owned BL prism handoff.",
                "% This is not a complete CFD domain until a conformal tetra core is merged.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    return {
        "route": "canonical_hybrid_halfwing_owned_bl_prism_handoff",
        "status": "owned_bl_prism_handoff_ready_core_pending",
        "mesh_path": str(output_path),
        "node_count": len(volume["nodes"]),
        "volume_element_count": len(volume["elements"]),
        "volume_element_type_counts": {str(SU2_PRISM): len(volume["elements"])},
        "boundary_layer_cell_count": len(volume["elements"]),
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "block_quality": block.quality,
        "block_metadata": block.metadata,
        "closure_section_indices": sorted(int(index) for index in closure_sections),
        "forbidden_route_checks": {
            "all_tet_global_star_bl_handoff": False,
            "boundary_layer_split_to_tetra": False,
            "owner_pyramid_as_active_method": False,
        },
        "caveats": [
            "near-wall BL prism handoff only; core tetra mesh is not merged yet",
            "coefficients from this mesh are not interpretable because there is no farfield domain",
        ],
    }


def _owned_bl_prism_volume(
    block: WingBoundaryLayerBlock,
    closure_sections: set[int],
) -> dict[str, Any]:
    elements: list[tuple[int, tuple[int, ...]]] = []
    for cell in block.cells:
        nodes = tuple(int(node) for node in cell.nodes)
        elements.extend(
            [
                (SU2_PRISM, (nodes[4], nodes[5], nodes[6], nodes[0], nodes[1], nodes[2])),
                (SU2_PRISM, (nodes[4], nodes[6], nodes[7], nodes[0], nodes[2], nodes[3])),
            ]
        )

    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    for face in block.boundary_faces:
        marker = _owned_bl_boundary_marker(block, face, closure_sections)
        face_nodes = tuple(int(node) for node in face.nodes)
        if face.marker == "span_cap":
            marker_faces.setdefault(marker, []).extend(
                [
                    (SU2_TRIANGLE, (face_nodes[0], face_nodes[1], face_nodes[2])),
                    (SU2_TRIANGLE, (face_nodes[0], face_nodes[2], face_nodes[3])),
                ]
            )
        else:
            marker_faces.setdefault(marker, []).append((9, face_nodes))

    return {
        "nodes": list(block.vertices),
        "elements": elements,
        "marker_faces": marker_faces,
    }


def _owned_bl_boundary_marker(
    block: WingBoundaryLayerBlock,
    face: BlockBoundaryFace,
    closure_sections: set[int],
) -> str:
    section_vertex_count = int(block.metadata["section_vertex_count"])
    section_count = int(block.metadata["station_count"])
    wall_count = int(block.section_blocks[0].metadata["wall_node_count"])
    leading_edge_index = int(block.section_blocks[0].metadata["leading_edge_wall_index"])
    sections = [int(node) // section_vertex_count for node in face.nodes]
    local_nodes = [int(node) % section_vertex_count for node in face.nodes]

    if face.marker == "wing_wall":
        wall_indices = [local % wall_count for local in local_nodes if local < wall_count]
        if not wall_indices:
            return "closure_wall"
        segment_index = min(wall_indices)
        return "wing_upper" if segment_index < leading_edge_index else "wing_lower"
    if face.marker == "bl_outer_interface":
        return "bl_outer_interface"
    if face.marker == "wake_cut":
        if any(
            section in closure_sections or section - 1 in closure_sections
            for section in sections
        ):
            return "closure_wall"
        return "te_wall"
    if face.marker == "span_cap":
        if max(sections) == 0:
            return "root_symmetry"
        if min(sections) == section_count - 1:
            return "tip_wall"
    return "closure_wall"


def write_phase3_direct_surface_prism_handoff_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = DEFAULT_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = DEFAULT_BL_LAYERS,
) -> dict[str, Any]:
    """Write direct surface-triangle prism BL cells for a tetra-core interface.

    Unlike the owned airfoil-block handoff above, this representation starts
    from triangular wall panels so the outer BL interface is triangular and can
    be used directly as a preserved tetra-core boundary.
    """
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    volume = _direct_surface_prism_volume(
        surface.vertices,
        [
            (triangle, marker)
            for triangle, marker in _triangulated_wall_triangles(surface)
        ],
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
    )
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _su2_volume_text(
            volume,
            comments=(
                "% Canonical hybrid half-wing direct surface-prism BL handoff.",
                "% Triangular outer BL interface is intended for preserved tetra-core fill.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    outer_interface = marker_summary["markers"].get("bl_outer_interface", {})
    return {
        "route": "canonical_hybrid_halfwing_direct_surface_prism_handoff",
        "status": "direct_surface_prism_handoff_ready_core_pending",
        "mesh_path": str(output_path),
        "node_count": len(volume["nodes"]),
        "volume_element_count": len(volume["elements"]),
        "volume_element_type_counts": {str(SU2_PRISM): len(volume["elements"])},
        "boundary_layer_cell_count": len(volume["elements"]),
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "marker_area_vectors": _marker_area_vectors(
            volume["nodes"],
            volume["marker_faces"],
        ),
        "core_tetra_interface": {
            "status": (
                "ready_for_tet_core_boundary"
                if outer_interface.get("element_type_counts") == {str(SU2_TRIANGLE): int(outer_interface.get("element_count", 0))}
                else "blocked_by_non_triangular_outer_interface"
            ),
            "marker": "bl_outer_interface",
            "element_count": outer_interface.get("element_count", 0),
            "element_type_counts": outer_interface.get("element_type_counts", {}),
        },
        "forbidden_route_checks": {
            "all_tet_global_star_bl_handoff": False,
            "boundary_layer_split_to_tetra": False,
            "owner_pyramid_as_active_method": False,
        },
        "caveats": [
            "near-wall direct prism handoff only; core tetra mesh is not merged yet",
            "wall-normal offset is a first topology candidate and still needs mesh-quality and SU2 dual gates",
        ],
    }


def write_phase3_direct_surface_prism_core_hybrid_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = DEFAULT_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = DEFAULT_BL_LAYERS,
    core_mesh_size: float = 0.35,
    farfield_mesh_size: float = 8.0,
) -> dict[str, Any]:
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    bl_volume = _direct_surface_prism_volume(
        surface.vertices,
        _triangulated_wall_triangles(surface),
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
    )
    core = _direct_surface_prism_core_tets(
        bl_volume,
        surface_bounds=_bounds(surface.vertices),
        core_mesh_size=core_mesh_size,
        farfield_mesh_size=farfield_mesh_size,
    )
    merged_nodes = list(bl_volume["nodes"])
    core_node_map = _merged_core_node_map(core["nodes"], merged_nodes)
    elements = [
        *bl_volume["elements"],
        *[
            (SU2_TETRAHEDRON, tuple(core_node_map[int(node)] for node in nodes))
            for nodes in core["tetra_elements"]
        ],
    ]
    marker_faces = {
        marker: list(faces)
        for marker, faces in bl_volume["marker_faces"].items()
        if marker != "bl_outer_interface"
    }
    for marker, faces in core["marker_faces"].items():
        marker_faces.setdefault(marker, []).extend(
            [
                (element_type, tuple(core_node_map[int(node)] for node in nodes))
                for element_type, nodes in faces
            ]
        )

    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _su2_volume_text(
            {
                "nodes": merged_nodes,
                "elements": elements,
                "marker_faces": marker_faces,
            },
            comments=(
                "% Canonical hybrid half-wing direct surface-prism BL + tetra-core mesh.",
                "% This is a route-smoke candidate, not grid-ladder truth.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    type_counts = {
        str(SU2_PRISM): len(bl_volume["elements"]),
        str(SU2_TETRAHEDRON): len(core["tetra_elements"]),
    }
    required_markers_present = all(
        marker in marker_summary["markers"] for marker in REQUIRED_MARKERS
    )
    return {
        "route": "canonical_hybrid_halfwing_direct_surface_prism_core_hybrid",
        "status": "direct_surface_prism_core_hybrid_written",
        "mesh_path": str(output_path),
        "node_count": len(merged_nodes),
        "volume_element_count": len(elements),
        "volume_element_type_counts": type_counts,
        "boundary_layer_cell_count": len(bl_volume["elements"]),
        "core_cell_count": len(core["tetra_elements"]),
        "marker_summary": marker_summary["markers"],
        "required_markers_present": required_markers_present,
        "su2_boundary_ownership": boundary_ownership,
        "core_report": core["report"],
        "marker_area_vectors": _marker_area_vectors(merged_nodes, marker_faces),
        "forbidden_route_checks": {
            "all_tet_global_star_bl_handoff": False,
            "boundary_layer_split_to_tetra": False,
            "owner_pyramid_as_active_method": False,
            "closure_faces_merged_into_wing_wall": False,
        },
        "caveats": [
            "direct prism BL + core tetra topology only; SU2 route-smoke must still pass",
            "wall-normal offset quality and SU2 dual metrics remain solver-side gates",
        ],
    }


def _direct_surface_prism_core_tets(
    bl_volume: Mapping[str, Any],
    *,
    surface_bounds: Mapping[str, float],
    core_mesh_size: float,
    farfield_mesh_size: float,
) -> dict[str, Any]:
    import gmsh

    outer_surface = _compact_outer_interface_surface(bl_volume)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("canonical_direct_surface_prism_core")
        outer_by_marker = _add_discrete_marked_mesh_surfaces(
            gmsh,
            outer_surface,
            first_tag=3_000_001,
        )
        outer_tags = outer_by_marker["bl_outer_interface"]
        gmsh.model.geo.synchronize()
        _farfield_vertices, symmetry_tags, farfield_tags = _add_farfield_box_with_symmetry_hole(
            gmsh,
            bounds=surface_bounds,
            bl_top_surface_tags=outer_tags,
            farfield_mesh_size=farfield_mesh_size,
        )
        core_volume = gmsh.model.geo.addVolume(
            [
                gmsh.model.geo.addSurfaceLoop(
                    [*outer_tags, *symmetry_tags, *farfield_tags]
                )
            ]
        )
        gmsh.model.geo.synchronize()
        outer_group = gmsh.model.addPhysicalGroup(2, outer_tags)
        gmsh.model.setPhysicalName(2, outer_group, "bl_outer_interface")
        symmetry_group = gmsh.model.addPhysicalGroup(2, symmetry_tags)
        gmsh.model.setPhysicalName(2, symmetry_group, "root_symmetry")
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_tags)
        gmsh.model.setPhysicalName(2, farfield_group, "farfield")
        fluid_group = gmsh.model.addPhysicalGroup(3, [core_volume])
        gmsh.model.setPhysicalName(3, fluid_group, "fluid_core")
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(core_mesh_size, farfield_mesh_size))
        gmsh.option.setNumber("Mesh.MeshSizeMax", max(core_mesh_size, farfield_mesh_size))
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        core_algorithm3d = 1
        gmsh.option.setNumber("Mesh.Algorithm3D", core_algorithm3d)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.model.mesh.generate(3)
        nodes = _gmsh_node_coordinates(gmsh)
        tetra_elements = _gmsh_tetra_elements(gmsh)
        unknown_tetra_nodes = sorted(
            {
                int(node)
                for tetra in tetra_elements
                for node in tetra
                if int(node) not in nodes
            }
        )
        if unknown_tetra_nodes:
            raise RuntimeError(
                "Gmsh generated tetrahedra with node tags missing from getNodes(): "
                f"{unknown_tetra_nodes[:8]}"
            )
        raw_marker_faces = {
            "root_symmetry": _gmsh_surface_marker_faces(gmsh, symmetry_tags),
            "farfield": _gmsh_surface_marker_faces(gmsh, farfield_tags),
        }
        marker_faces = _orient_core_marker_faces_from_tetrahedra(
            tetra_elements,
            raw_marker_faces,
        )
        return {
            "nodes": nodes,
            "tetra_elements": tetra_elements,
            "marker_faces": marker_faces,
            "report": {
                "status": "meshed",
                "node_tag_integrity": {
                    "status": "pass",
                    "missing_tetra_node_tags": [],
                },
                "core_tetra_count": len(tetra_elements),
                "outer_interface_triangle_count": len(outer_surface.faces),
                "outer_interface_node_count": len(outer_surface.vertices),
                "root_symmetry_surface_count": len(symmetry_tags),
                "farfield_surface_count": len(farfield_tags),
                "mesh_sizing": {
                    "core_mesh_size": float(core_mesh_size),
                    "farfield_mesh_size": float(farfield_mesh_size),
                    "gmsh_algorithm3d": core_algorithm3d,
                },
            },
        }
    finally:
        gmsh.finalize()


def _compact_outer_interface_surface(bl_volume: Mapping[str, Any]) -> SurfaceMesh:
    """Return only the BL outer-interface vertices and triangular faces for Gmsh."""
    interface_faces = [
        tuple(int(node) for node in nodes)
        for element_type, nodes in bl_volume["marker_faces"]["bl_outer_interface"]
        if int(element_type) == SU2_TRIANGLE
    ]
    original_nodes = sorted({node for face in interface_faces for node in face})
    compact_by_original = {node: index for index, node in enumerate(original_nodes)}
    compact_vertices = [tuple(bl_volume["nodes"][node]) for node in original_nodes]
    compact_faces = [
        Face(
            nodes=tuple(compact_by_original[node] for node in face),
            marker="bl_outer_interface",
        )
        for face in interface_faces
    ]
    return SurfaceMesh(
        vertices=compact_vertices,
        faces=compact_faces,
        metadata={
            "surface_role": "direct_prism_outer_interface",
            "original_node_ids": original_nodes,
        },
    )


def _gmsh_node_coordinates(gmsh: Any) -> dict[int, tuple[float, float, float]]:
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    return {
        int(tag): (
            float(coords[3 * index]),
            float(coords[3 * index + 1]),
            float(coords[3 * index + 2]),
        )
        for index, tag in enumerate(node_tags)
    }


def _gmsh_tetra_elements(gmsh: Any) -> list[tuple[int, int, int, int]]:
    output: list[tuple[int, int, int, int]] = []
    element_types, element_tags, element_nodes = gmsh.model.mesh.getElements(3)
    for element_type, tags, nodes in zip(element_types, element_tags, element_nodes):
        if int(element_type) != 4:
            continue
        for offset in range(len(tags)):
            start = 4 * offset
            output.append(tuple(int(node) for node in nodes[start : start + 4]))
    return output


def _gmsh_surface_marker_faces(
    gmsh: Any,
    entity_tags: Sequence[int],
) -> list[tuple[int, tuple[int, ...]]]:
    output: list[tuple[int, tuple[int, ...]]] = []
    for entity in entity_tags:
        element_types, element_tags, element_nodes = gmsh.model.mesh.getElements(2, int(entity))
        for element_type, tags, nodes in zip(element_types, element_tags, element_nodes):
            if int(element_type) == 2:
                nodes_per_element = 3
                su2_type = SU2_TRIANGLE
            elif int(element_type) == 3:
                nodes_per_element = 4
                su2_type = 9
            else:
                continue
            for offset in range(len(tags)):
                start = nodes_per_element * offset
                output.append(
                    (
                        su2_type,
                        tuple(
                            int(node)
                            for node in nodes[start : start + nodes_per_element]
                        ),
                    )
                )
    return output


def _orient_core_marker_faces_from_tetrahedra(
    tetra_elements: Sequence[tuple[int, int, int, int]],
    marker_faces: Mapping[str, Sequence[tuple[int, tuple[int, ...]]]],
) -> dict[str, list[tuple[int, tuple[int, ...]]]]:
    oriented_boundary_faces: dict[tuple[int, ...], tuple[int, ...]] = {}
    face_counts: dict[tuple[int, ...], int] = {}
    for tetra in tetra_elements:
        for face in _volume_element_faces(SU2_TETRAHEDRON, tetra):
            key = tuple(sorted(int(node) for node in face))
            face_counts[key] = face_counts.get(key, 0) + 1
            oriented_boundary_faces[key] = tuple(int(node) for node in face)

    output: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    for marker, faces in marker_faces.items():
        output[marker] = []
        for element_type, nodes in faces:
            key = tuple(sorted(int(node) for node in nodes))
            oriented = (
                oriented_boundary_faces[key]
                if face_counts.get(key) == 1 and key in oriented_boundary_faces
                else tuple(int(node) for node in nodes)
            )
            output[marker].append((int(element_type), oriented))
    return output


def _merged_core_node_map(
    core_nodes: Mapping[int, tuple[float, float, float]],
    merged_nodes: list[tuple[float, float, float]],
) -> dict[int, int]:
    coord_to_node = {_coord_key(node): index for index, node in enumerate(merged_nodes)}
    output: dict[int, int] = {}
    for tag, coord in core_nodes.items():
        key = _coord_key(coord)
        if key not in coord_to_node:
            coord_to_node[key] = len(merged_nodes)
            merged_nodes.append(coord)
        output[int(tag)] = coord_to_node[key]
    return output


def _coord_key(coord: Sequence[float]) -> tuple[float, float, float]:
    return (round(float(coord[0]), 12), round(float(coord[1]), 12), round(float(coord[2]), 12))


def _triangulated_wall_triangles(surface) -> list[tuple[tuple[int, int, int], str]]:
    triangles: list[tuple[tuple[int, int, int], str]] = []
    for face in surface.faces:
        if face.marker not in VISCOUS_WALL_MARKERS:
            continue
        nodes = tuple(int(node) for node in face.nodes)
        if len(nodes) == 3:
            triangles.append((nodes, face.marker))
        elif len(nodes) == 4:
            triangles.extend(
                [
                    ((nodes[0], nodes[1], nodes[2]), face.marker),
                    ((nodes[0], nodes[2], nodes[3]), face.marker),
                ]
            )
        else:
            raise ValueError("Phase 3 wall faces must be triangles or quads")
    return triangles


def _direct_surface_prism_volume(
    base_vertices: Sequence[tuple[float, float, float]],
    triangles: Sequence[tuple[tuple[int, int, int], str]],
    *,
    first_layer_height_m: float,
    growth_ratio: float,
    bl_layers: int,
) -> dict[str, Any]:
    heights = [0.0, *_layer_cumulative_heights(first_layer_height_m, growth_ratio, bl_layers)]
    normals = _surface_vertex_normals(base_vertices, [triangle for triangle, _ in triangles])
    base_count = len(base_vertices)
    nodes = [
        (
            vertex[0] + height * normal[0],
            vertex[1] + height * normal[1],
            vertex[2] + height * normal[2],
        )
        for height in heights
        for vertex, normal in zip(base_vertices, normals)
    ]

    def node(layer: int, base_node: int) -> int:
        return layer * base_count + int(base_node)

    elements: list[tuple[int, tuple[int, ...]]] = []
    face_records: dict[tuple[int, ...], dict[str, Any]] = {}

    def add_face(face_nodes: tuple[int, ...], element_type: int, marker: str) -> None:
        key = tuple(sorted(face_nodes))
        record = face_records.setdefault(
            key,
            {
                "count": 0,
                "nodes": face_nodes,
                "element_type": element_type,
                "marker": marker,
            },
        )
        record["count"] = int(record["count"]) + 1

    for layer in range(bl_layers):
        for triangle, marker in triangles:
            a, b, c = triangle
            prism = (
                node(layer + 1, a),
                node(layer + 1, b),
                node(layer + 1, c),
                node(layer, a),
                node(layer, b),
                node(layer, c),
            )
            elements.append((SU2_PRISM, prism))
            add_face((prism[3], prism[4], prism[5]), SU2_TRIANGLE, marker)
            add_face(
                (prism[0], prism[2], prism[1]),
                SU2_TRIANGLE,
                "bl_outer_interface" if layer == bl_layers - 1 else "_internal_bl_layer",
            )
            add_face(
                (prism[0], prism[3], prism[4], prism[1]),
                9,
                _direct_prism_side_marker(base_vertices, (a, b), marker),
            )
            add_face(
                (prism[1], prism[4], prism[5], prism[2]),
                9,
                _direct_prism_side_marker(base_vertices, (b, c), marker),
            )
            add_face(
                (prism[2], prism[5], prism[3], prism[0]),
                9,
                _direct_prism_side_marker(base_vertices, (c, a), marker),
            )

    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    for record in face_records.values():
        if int(record["count"]) != 1:
            continue
        marker = str(record["marker"])
        if marker == "_internal_bl_layer":
            continue
        marker_faces.setdefault(marker, []).append(
            (int(record["element_type"]), tuple(int(node) for node in record["nodes"]))
        )
    return {
        "nodes": nodes,
        "elements": elements,
        "marker_faces": marker_faces,
    }


def _marker_area_vectors(
    vertices: Sequence[tuple[float, float, float]],
    marker_faces: Mapping[str, Sequence[tuple[int, Sequence[int]]]],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for marker, faces in marker_faces.items():
        vector = [0.0, 0.0, 0.0]
        area = 0.0
        for _element_type, nodes in faces:
            face_vector = _face_area_vector(vertices, [int(node) for node in nodes])
            vector[0] += face_vector[0]
            vector[1] += face_vector[1]
            vector[2] += face_vector[2]
            area += math.sqrt(
                face_vector[0] ** 2 + face_vector[1] ** 2 + face_vector[2] ** 2
            )
        output[marker] = {
            "area": area,
            "area_vector": tuple(vector),
        }
    return output


def _face_area_vector(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
) -> tuple[float, float, float]:
    points = [vertices[node] for node in nodes]
    origin = points[0]
    vector = [0.0, 0.0, 0.0]
    for index in range(1, len(points) - 1):
        left = _vector_between(origin, points[index])
        right = _vector_between(origin, points[index + 1])
        normal = _cross(left, right)
        vector[0] += 0.5 * normal[0]
        vector[1] += 0.5 * normal[1]
        vector[2] += 0.5 * normal[2]
    return (vector[0], vector[1], vector[2])


def _vector_between(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (right[0] - left[0], right[1] - left[1], right[2] - left[2])


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _direct_prism_side_marker(
    vertices: Sequence[tuple[float, float, float]],
    edge: tuple[int, int],
    source_marker: str,
) -> str:
    if all(abs(vertices[node][1]) <= 1.0e-9 for node in edge):
        return "root_symmetry"
    return source_marker


def _surface_vertex_normals(
    vertices: Sequence[tuple[float, float, float]],
    triangles: Sequence[tuple[int, int, int]],
) -> list[tuple[float, float, float]]:
    accum = [[0.0, 0.0, 0.0] for _ in vertices]
    for triangle in triangles:
        normal = _triangle_unit_normal(
            vertices[triangle[0]],
            vertices[triangle[1]],
            vertices[triangle[2]],
        )
        for node in triangle:
            accum[int(node)][0] += normal[0]
            accum[int(node)][1] += normal[1]
            accum[int(node)][2] += normal[2]
    normals: list[tuple[float, float, float]] = []
    for vector in accum:
        length = math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)
        if length <= 1.0e-14:
            normals.append((0.0, 0.0, 1.0))
        else:
            normals.append((vector[0] / length, vector[1] / length, vector[2] / length))
    return normals


def _triangle_unit_normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    normal = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    length = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
    if length <= 1.0e-14:
        return (0.0, 0.0, 0.0)
    return (normal[0] / length, normal[1] / length, normal[2] / length)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section-table", type=Path, default=DEFAULT_SECTION_TABLE_PATH)
    parser.add_argument("--avl", type=Path, default=DEFAULT_AVL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--run-su2", action="store_true")
    parser.add_argument("--update-manifest", action="store_true")
    parser.add_argument("--solver-command", default=DEFAULT_SOLVER_COMMAND)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=2400.0)
    parser.add_argument("--points-per-side", type=int, default=DEFAULT_POINTS_PER_SIDE)
    parser.add_argument("--spanwise-subdivisions", type=int, default=DEFAULT_SPANWISE_SUBDIVISIONS)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_ROUTE_SMOKE_MAX_ITERATIONS)
    parser.add_argument("--first-layer-height-m", type=float, default=DEFAULT_FIRST_LAYER_HEIGHT_M)
    parser.add_argument("--growth-ratio", type=float, default=DEFAULT_GROWTH_RATIO)
    parser.add_argument("--bl-layers", type=int, default=DEFAULT_BL_LAYERS)
    parser.add_argument("--wing-mesh-size", type=float, default=0.5)
    parser.add_argument("--farfield-mesh-size", type=float, default=8.0)
    args = parser.parse_args(argv)
    report = run_phase3_route_smoke(
        section_table_path=args.section_table,
        avl_path=args.avl,
        output_dir=args.output_dir,
        run_su2=args.run_su2,
        update_manifest=args.update_manifest,
        manifest_path=args.manifest,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        first_layer_height_m=args.first_layer_height_m,
        growth_ratio=args.growth_ratio,
        bl_layers=args.bl_layers,
        wing_mesh_size=args.wing_mesh_size,
        farfield_mesh_size=args.farfield_mesh_size,
        max_iterations=args.max_iterations,
        solver_command=args.solver_command,
        threads=args.threads,
        timeout_seconds=args.timeout_seconds,
    )
    gate = report["gate"]
    print(f"Phase 3 ROUTE_SMOKE_PASS gate: {gate['status']}")
    for blocker in gate["blockers"]:
        print(f"- {blocker}")
    return 0 if gate["status"] == "pass" else 1


def _layer_cumulative_heights(
    first_layer_height_m: float,
    growth_ratio: float,
    layers: int,
) -> list[float]:
    if first_layer_height_m <= 0.0:
        raise ValueError("first_layer_height_m must be positive")
    if growth_ratio < 1.0:
        raise ValueError("growth_ratio must be >= 1")
    if layers < 1:
        raise ValueError("layers must be positive")
    total = 0.0
    heights: list[float] = []
    for layer in range(int(layers)):
        total += first_layer_height_m * growth_ratio**layer
        heights.append(float(total))
    return heights


def _add_farfield_box_with_symmetry_hole(
    gmsh: Any,
    *,
    bounds: Mapping[str, float],
    bl_top_surface_tags: Sequence[int],
    farfield_mesh_size: float,
) -> tuple[list[tuple[float, float, float]], list[int], list[int]]:
    farfield_vertices = _half_farfield_vertices(bounds)
    point_tags = [
        gmsh.model.geo.addPoint(x, y, z, farfield_mesh_size)
        for x, y, z in farfield_vertices
    ]
    line_cache: dict[tuple[int, int], tuple[int, int, int]] = {}

    def line(left: int, right: int) -> int:
        return _line_between(gmsh, point_tags, line_cache, left, right)

    l1 = line(0, 1)
    l2 = line(1, 2)
    l3 = line(2, 3)
    l4 = line(3, 0)
    l5 = line(4, 5)
    l6 = line(5, 6)
    l7 = line(6, 7)
    l8 = line(7, 4)
    l9 = line(0, 4)
    l10 = line(1, 5)
    l11 = line(2, 6)
    l12 = line(3, 7)
    gmsh.model.geo.synchronize()

    hole_boundary = gmsh.model.getBoundary(
        [(2, int(tag)) for tag in bl_top_surface_tags],
        combined=True,
        oriented=True,
        recursive=False,
    )
    hole_curves = _order_curve_loop(
        gmsh,
        [abs(int(curve_tag)) for dim, curve_tag in hole_boundary if int(dim) == 1],
    )
    symmetry_surface = gmsh.model.geo.addPlaneSurface(
        [
            gmsh.model.geo.addCurveLoop([l1, l10, -l5, -l9]),
            gmsh.model.geo.addCurveLoop(hole_curves),
        ]
    )
    farfield_surfaces = [
        gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l2, l11, -l6, -l10])]),
        gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l3, l12, -l7, -l11])]),
        gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l4, l9, -l8, -l12])]),
        gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l1, l2, l3, l4])]),
        gmsh.model.geo.addPlaneSurface([gmsh.model.geo.addCurveLoop([l5, l6, l7, l8])]),
    ]
    return farfield_vertices, [int(symmetry_surface)], [int(tag) for tag in farfield_surfaces]


def _count_elements_for_entities(
    gmsh: Any,
    dim: int,
    entity_tags: Sequence[int],
) -> tuple[int, dict[str, int]]:
    counts: dict[str, int] = {}
    total = 0
    for entity in entity_tags:
        element_types, element_tags, _ = gmsh.model.mesh.getElements(dim, int(entity))
        for element_type, tags in zip(element_types, element_tags):
            count = len(tags)
            counts[str(int(element_type))] = counts.get(str(int(element_type)), 0) + count
            total += count
    return total, counts


def _hybrid_mesh_quality_metrics(
    gmsh: Any,
    farfield_vertices: Sequence[tuple[float, float, float]],
) -> dict[str, Any]:
    element_types, element_tags, element_nodes = gmsh.model.mesh.getElements(3)
    volume_measures: list[float] = []
    sicn_values: list[float] = []
    incident_counts: dict[int, int] = {}
    for tags, nodes in zip(element_tags, element_nodes):
        if len(tags):
            volume_measures.extend(
                float(value) for value in gmsh.model.mesh.getElementQualities(tags, "volume")
            )
            sicn_values.extend(
                float(value) for value in gmsh.model.mesh.getElementQualities(tags, "minSICN")
            )
        nodes_per_element = len(nodes) // max(1, len(tags))
        for element_index in range(len(tags)):
            unique_nodes = set(
                nodes[element_index * nodes_per_element : (element_index + 1) * nodes_per_element]
            )
            for node in unique_nodes:
                incident_counts[int(node)] = incident_counts.get(int(node), 0) + 1
    farfield_node_tags = _nearest_node_tags(gmsh, farfield_vertices)
    finite_volumes = [value for value in volume_measures if math.isfinite(value)]
    finite_sicn = [value for value in sicn_values if math.isfinite(value)]
    return {
        "min_volume_quality": min(finite_volumes) if finite_volumes else None,
        "non_positive_quality_count": sum(1 for value in finite_volumes if value <= 0.0),
        "min_sicn": min(finite_sicn) if finite_sicn else None,
        "non_positive_sicn_count": sum(1 for value in finite_sicn if value <= 0.0),
        "max_farfield_vertex_incident_volume_cells": max(
            (incident_counts.get(tag, 0) for tag in farfield_node_tags),
            default=0,
        ),
    }


def _hybrid_mesh_quality_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if _float_or_none(metrics.get("min_volume_quality")) is None:
        blockers.append("volume_quality_missing")
    elif float(metrics["min_volume_quality"]) <= 0.0:
        blockers.append("non_positive_volume_quality")
    if int(metrics.get("non_positive_quality_count") or 0) > 0:
        blockers.append("non_positive_volume_quality_count")
    if int(metrics.get("max_farfield_vertex_incident_volume_cells") or 0) > 200:
        blockers.append("farfield_vertex_incident_cell_count_exceeds_200")
    if int(metrics.get("non_positive_sicn_count") or 0) > 0:
        warnings.append("hybrid_prism_min_sicn_non_positive_check_su2_dual_quality")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "warnings": warnings,
    }


def _nearest_node_tags(
    gmsh: Any,
    targets: Sequence[tuple[float, float, float]],
) -> list[int]:
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    nodes = [
        (
            int(tag),
            (
                float(coords[3 * idx]),
                float(coords[3 * idx + 1]),
                float(coords[3 * idx + 2]),
            ),
        )
        for idx, tag in enumerate(node_tags)
    ]
    nearest: list[int] = []
    for target in targets:
        tag, _ = min(nodes, key=lambda item: _distance3(item[1], target))
        nearest.append(tag)
    return nearest


def _distance3(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return math.sqrt(
        (left[0] - right[0]) ** 2
        + (left[1] - right[1]) ** 2
        + (left[2] - right[2]) ** 2
    )


def _order_curve_loop(gmsh: Any, curve_tags: list[int]) -> list[int]:
    if not curve_tags:
        raise RuntimeError("cannot order an empty curve loop")
    endpoint_map = {int(tag): _curve_endpoint_tags(gmsh, int(tag)) for tag in curve_tags}
    ordered = [int(curve_tags[0])]
    used = {abs(int(curve_tags[0]))}
    _, current_end = endpoint_map[abs(int(curve_tags[0]))]
    while len(ordered) < len(curve_tags):
        found: int | None = None
        for raw_tag in curve_tags:
            tag = abs(int(raw_tag))
            if tag in used:
                continue
            start, end = endpoint_map[tag]
            if start == current_end:
                found = tag
                current_end = end
                break
            if end == current_end:
                found = -tag
                current_end = start
                break
        if found is None:
            raise RuntimeError(f"could not order curve loop from {curve_tags}")
        used.add(abs(found))
        ordered.append(found)
    return ordered


def _curve_endpoint_tags(gmsh: Any, curve_tag: int) -> tuple[int, int]:
    boundary = gmsh.model.getBoundary(
        [(1, int(curve_tag))],
        combined=False,
        oriented=True,
        recursive=False,
    )
    point_tags = [
        abs(int(entity_tag))
        for entity_dim, entity_tag in boundary
        if int(entity_dim) == 0
    ]
    if len(point_tags) != 2:
        raise RuntimeError(f"curve {curve_tag} does not expose exactly two endpoints")
    return int(point_tags[0]), int(point_tags[1])


def _force_coefficients_from_breakdown(
    forces_breakdown: Mapping[str, Any],
) -> tuple[dict[str, float | None], dict[str, dict[str, float | None]]]:
    parsed = _mapping(forces_breakdown.get("parsed"))
    surfaces = _mapping(parsed.get("surface_coefficients"))
    primary = _sum_surface_coefficients(surfaces, PRIMARY_FORCE_MARKERS)
    diagnostic = {
        marker: _single_surface_coefficients(_mapping(surfaces.get(marker)))
        for marker in DIAGNOSTIC_FORCE_MARKERS
    }
    return primary, diagnostic


def _sum_surface_coefficients(
    surfaces: Mapping[str, Any],
    markers: Sequence[str],
) -> dict[str, float | None]:
    keys = ("cl", "cd", "cmy")
    payload: dict[str, float | None] = {}
    for key in keys:
        total_values = [
            _float_or_none(_mapping(_mapping(surfaces.get(marker)).get(key)).get("total"))
            for marker in markers
        ]
        pressure_values = [
            _float_or_none(_mapping(_mapping(surfaces.get(marker)).get(key)).get("pressure"))
            for marker in markers
        ]
        friction_values = [
            _float_or_none(_mapping(_mapping(surfaces.get(marker)).get(key)).get("friction"))
            for marker in markers
        ]
        payload[key] = _sum_or_none(total_values)
        payload[f"pressure_{key}"] = _sum_or_none(pressure_values)
        payload[f"viscous_{key}"] = _sum_or_none(friction_values)
    return payload


def _single_surface_coefficients(surface: Mapping[str, Any]) -> dict[str, float | None]:
    return {
        "cl": _float_or_none(_mapping(surface.get("cl")).get("total")),
        "cd": _float_or_none(_mapping(surface.get("cd")).get("total")),
        "pressure_cd": _float_or_none(_mapping(surface.get("cd")).get("pressure")),
        "viscous_cd": _float_or_none(_mapping(surface.get("cd")).get("friction")),
    }


def _sum_or_none(values: Sequence[float | None]) -> float | None:
    if any(value is None for value in values):
        return None
    return float(sum(float(value) for value in values if value is not None))


def _markdown_report(report: Mapping[str, Any]) -> str:
    gate = _mapping(report.get("gate"))
    primary = _mapping(gate.get("primary_force_coefficients"))
    mesh = _mapping(report.get("mesh"))
    lines = [
        "# Canonical Hybrid Phase 3 Route Smoke",
        "",
        f"- route: `{report.get('route')}`",
        f"- phase gate: `{report.get('phase_gate')}`",
        f"- status: `{gate.get('status')}`",
        f"- release status: `{gate.get('release_status')}`",
        f"- blockers: `{gate.get('blockers')}`",
        f"- warnings: `{gate.get('warnings')}`",
        f"- primary CL: `{primary.get('cl')}`",
        f"- primary CD: `{primary.get('cd')}`",
        f"- volume element types: `{mesh.get('volume_element_type_counts')}`",
        f"- BL cell count: `{mesh.get('boundary_layer_cell_count')}`",
        "",
        "## Engineering Boundary",
        "",
        str(_mapping(report.get("engineering_assessment")).get("trust_boundary")),
        "",
    ]
    return "\n".join(lines)


def _parse_dual_quality_log_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    report = parse_su2_dual_control_volume_quality(
        path.read_text(encoding="utf-8", errors="replace")
    )
    report["path"] = str(path)
    return report


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


if __name__ == "__main__":
    raise SystemExit(main())
