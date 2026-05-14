#!/usr/bin/env python3
"""Run Phase 3 viscous route-smoke for the canonical hybrid half-wing CFD route."""

from __future__ import annotations

import argparse
import itertools
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
    SU2_QUAD,
    SU2_PRISM,
    SU2_PYRAMID,
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
MAX_ROUTE_DUAL_HOTSPOT_INCIDENT_EDGE_RATIO = 1000.0
MAX_DIRECT_ROOT_SYMMETRY_QUAD_ASPECT_RATIO = 1000.0


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
    direct_prism_quality = _direct_prism_quality_metrics(volume)
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
        "direct_prism_quality": direct_prism_quality,
        "direct_prism_quality_gate": _direct_prism_quality_gate(
            direct_prism_quality
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
    element_sources = [
        *[
            _phase3_volume_element_source(element_type)
            for element_type, _nodes in bl_volume["elements"]
        ],
        *(["tetra_core"] * len(core["tetra_elements"])),
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
    compacted_volume, node_compaction = _compact_volume_node_indices(
        {
            "nodes": merged_nodes,
            "elements": elements,
            "marker_faces": marker_faces,
        }
    )
    dual_subvolume_proxy = _mixed_dual_subvolume_proxy_report(
        compacted_volume["nodes"],
        compacted_volume["elements"],
        element_sources=element_sources,
        marker_faces=compacted_volume["marker_faces"],
        min_ratio=MAX_ROUTE_DUAL_SUB_VOLUME_RATIO,
        top_count=20,
    )

    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _su2_volume_text(
            compacted_volume,
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
    direct_prism_quality = _direct_prism_quality_metrics(bl_volume)
    return {
        "route": "canonical_hybrid_halfwing_direct_surface_prism_core_hybrid",
        "status": "direct_surface_prism_core_hybrid_written",
        "mesh_path": str(output_path),
        "node_count": len(compacted_volume["nodes"]),
        "volume_element_count": len(elements),
        "volume_element_type_counts": type_counts,
        "boundary_layer_cell_count": len(bl_volume["elements"]),
        "core_cell_count": len(core["tetra_elements"]),
        "node_compaction": node_compaction,
        "marker_summary": marker_summary["markers"],
        "required_markers_present": required_markers_present,
        "su2_boundary_ownership": boundary_ownership,
        "core_report": core["report"],
        "marker_area_vectors": _marker_area_vectors(
            compacted_volume["nodes"],
            compacted_volume["marker_faces"],
        ),
        "dual_subvolume_proxy": dual_subvolume_proxy,
        "direct_prism_quality": direct_prism_quality,
        "direct_prism_quality_gate": _direct_prism_quality_gate(
            direct_prism_quality
        ),
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
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Closed-wall direct prism wrapper candidate only. It may clear the "
                "dual proxy at some low-resolution layer counts, but it must also "
                "pass prism signed volume, root sidewall aspect, and pressure sanity."
            ),
        },
    }


def write_phase3_partial_wing_prism_handoff_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = 42,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = DEFAULT_BL_LAYERS,
) -> dict[str, Any]:
    """Write a wing-surface-only prism BL handoff and stop before cap closure.

    This deliberately extrudes only the primary force surfaces. The resulting
    prism block is useful evidence for the next topology step, but it is not a
    complete CFD domain because tip/TE/closure caps still need explicit
    materialization before tetra-core merge.
    """
    prism_wall_markers = set(PRIMARY_FORCE_MARKERS)
    required_cap_markers = [
        marker for marker in DIAGNOSTIC_FORCE_MARKERS if marker not in prism_wall_markers
    ]
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    prism_triangles = [
        (triangle, marker)
        for triangle, marker in wall_triangles
        if marker in prism_wall_markers
    ]
    cap_edge_marker_map = _cap_edge_marker_map(
        [
            (triangle, marker)
            for triangle, marker in wall_triangles
            if marker in required_cap_markers
        ]
    )
    volume = _direct_surface_prism_volume(
        surface.vertices,
        prism_triangles,
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
        edge_marker_map=cap_edge_marker_map,
    )
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _su2_volume_text(
            volume,
            comments=(
                "% Canonical hybrid half-wing partial wing-surface prism handoff.",
                "% Tip/TE/closure caps are intentionally not materialized here.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    direct_prism_quality = _direct_prism_quality_metrics(volume)
    outer_interface = marker_summary["markers"].get("bl_outer_interface", {})
    cap_counts = {
        marker: surface.marker_counts().get(marker, 0)
        for marker in required_cap_markers
    }
    return {
        "route": "canonical_hybrid_halfwing_partial_wing_prism_handoff",
        "status": "partial_wing_prism_ready_caps_pending",
        "mesh_path": str(output_path),
        "node_count": len(volume["nodes"]),
        "volume_element_count": len(volume["elements"]),
        "volume_element_type_counts": {str(SU2_PRISM): len(volume["elements"])},
        "boundary_layer_cell_count": len(volume["elements"]),
        "prism_wall_markers": list(PRIMARY_FORCE_MARKERS),
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "marker_area_vectors": _marker_area_vectors(
            volume["nodes"],
            volume["marker_faces"],
        ),
        "direct_prism_quality": direct_prism_quality,
        "direct_prism_quality_gate": _direct_prism_quality_gate(
            direct_prism_quality
        ),
        "core_tetra_interface": {
            "status": "blocked_until_caps_materialized",
            "marker": "bl_outer_interface",
            "element_count": outer_interface.get("element_count", 0),
            "element_type_counts": outer_interface.get("element_type_counts", {}),
        },
        "cap_closure_topology": {
            "status": "blocked_cap_faces_missing",
            "required_cap_markers": required_cap_markers,
            "source_surface_face_counts": cap_counts,
            "required_policy": (
                "Materialize conformal root/tip/TE/closure caps between the "
                "wall surface and BL outer interface before tetra-core merge."
            ),
        },
        "forbidden_route_checks": {
            "all_tet_global_star_bl_handoff": False,
            "boundary_layer_split_to_tetra": False,
            "owner_pyramid_as_active_method": False,
            "closure_faces_merged_into_wing_wall": False,
        },
        "caveats": [
            "partial wing-upper/lower prism BL only; not a complete volume mesh",
            "tip/TE/closure caps remain separate required topology before route-smoke",
        ],
    }


def run_phase3_closed_wall_wrapper_layer_window_probe(
    section_table_path: Path | str,
    output_dir: Path | str,
    *,
    points_per_side: int = 42,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    layer_counts: Sequence[int] = (4, 6, 7, 8, 16),
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    core_mesh_size: float = 0.35,
    farfield_mesh_size: float = 8.0,
    run_dual_proxy: bool = False,
) -> dict[str, Any]:
    """Probe whether closed-wall BL has a simple positive-prism layer window."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    rows: list[dict[str, Any]] = []
    for layers in layer_counts:
        layer_count = int(layers)
        volume = _direct_surface_prism_volume(
            surface.vertices,
            wall_triangles,
            first_layer_height_m=first_layer_height_m,
            growth_ratio=growth_ratio,
            bl_layers=layer_count,
        )
        quality = _direct_prism_quality_metrics(volume)
        quality_gate = _direct_prism_quality_gate(quality)
        row: dict[str, Any] = {
            "layers": layer_count,
            "boundary_layer_cell_count": len(volume["elements"]),
            "total_thickness_m": _layer_cumulative_heights(
                first_layer_height_m,
                growth_ratio,
                layer_count,
            )[-1],
            "direct_prism_quality": quality,
            "direct_prism_quality_gate": quality_gate,
            "dual_subvolume_proxy": {
                "status": "not_run",
                "reason": "run_dual_proxy_false",
            },
        }
        if (
            run_dual_proxy
            and quality_gate["status"] == "pass"
            and int(quality["prism_signed_volume"]["non_positive_count"]) == 0
        ):
            core = _direct_surface_prism_core_tets(
                volume,
                surface_bounds=_bounds(surface.vertices),
                core_mesh_size=core_mesh_size,
                farfield_mesh_size=farfield_mesh_size,
            )
            row["core_cell_count"] = len(core["tetra_elements"])
            row["dual_subvolume_proxy"] = _closed_wall_wrapper_dual_proxy(
                volume,
                core,
            )
        rows.append(row)

    viable_rows = [
        row
        for row in rows
        if _mapping(row.get("direct_prism_quality_gate")).get("status") == "pass"
        and _mapping(row.get("dual_subvolume_proxy")).get("status") in {
            "pass",
            "not_run",
        }
    ]
    report = {
        "route": "canonical_hybrid_halfwing_closed_wall_wrapper_layer_window_probe",
        "status": (
            "closed_wall_wrapper_has_candidate_window"
            if run_dual_proxy and any(
                _mapping(row.get("dual_subvolume_proxy")).get("status") == "pass"
                for row in viable_rows
            )
            else "closed_wall_wrapper_no_simple_layer_window"
        ),
        "case_dir": str(output_path),
        "surface": {
            "marker_counts": surface.marker_counts(),
            "metadata": surface.metadata,
        },
        "rows": rows,
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Layer-window diagnostic only. A row with positive prisms is not a "
                "route-smoke mesh unless it also clears the dual proxy and pressure "
                "sanity; a row with inverted prisms is an immediate topology blocker."
            ),
        },
    }
    report_path = output_path / "closed_wall_wrapper_layer_window_report.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def run_phase3_closed_wall_te_stageback_layer_probe(
    section_table_path: Path | str,
    output_dir: Path | str,
    *,
    points_per_side: int = 42,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    full_wall_layers: int = 16,
    cap_layers: int = 6,
    stageback_segments: Sequence[int] = (0, 4, 6, 8),
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
) -> dict[str, Any]:
    """Probe whether TE/aft BL stageback reduces closed-wrapper prism inversion."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    points_per_station = int(surface.metadata["points_per_station"])

    rows: list[dict[str, Any]] = []
    for stageback_segment_count in stageback_segments:
        stageback_count = int(stageback_segment_count)
        triangle_layer_counts: list[int] = []
        stageback_primary_triangle_count = 0
        cap_triangle_count = 0
        for triangle, marker in wall_triangles:
            if marker in DIAGNOSTIC_FORCE_MARKERS:
                triangle_layer_counts.append(int(cap_layers))
                cap_triangle_count += 1
                continue
            if marker in PRIMARY_FORCE_MARKERS and _triangle_touches_te_stageback_band(
                triangle,
                points_per_station=points_per_station,
                stageback_segments=stageback_count,
            ):
                triangle_layer_counts.append(int(cap_layers))
                stageback_primary_triangle_count += 1
                continue
            triangle_layer_counts.append(int(full_wall_layers))

        volume = _direct_surface_prism_volume(
            surface.vertices,
            wall_triangles,
            first_layer_height_m=first_layer_height_m,
            growth_ratio=growth_ratio,
            bl_layers=int(full_wall_layers),
            triangle_layer_counts=triangle_layer_counts,
        )
        quality = _direct_prism_quality_metrics(volume)
        marker_face_counts = {
            str(marker): len(faces)
            for marker, faces in sorted(_mapping(volume["marker_faces"]).items())
        }
        rows.append(
            {
                "stageback_segments": stageback_count,
                "full_wall_layers": int(full_wall_layers),
                "cap_layers": int(cap_layers),
                "stageback_primary_triangle_count": stageback_primary_triangle_count,
                "cap_triangle_count": cap_triangle_count,
                "boundary_layer_cell_count": len(volume["elements"]),
                "marker_face_counts": marker_face_counts,
                "termination_interface_quad_count": sum(
                    1
                    for element_type, _nodes in volume["marker_faces"].get(
                        "bl_termination_interface",
                        [],
                    )
                    if int(element_type) == SU2_QUAD
                ),
                "direct_prism_quality": quality,
                "direct_prism_quality_gate": _direct_prism_quality_gate(quality),
            }
        )

    report = {
        "route": "canonical_hybrid_halfwing_closed_wall_te_stageback_layer_probe",
        "status": "closed_wall_te_stageback_probe_completed",
        "case_dir": str(output_path),
        "surface": {
            "marker_counts": surface.marker_counts(),
            "metadata": surface.metadata,
        },
        "rows": rows,
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "TE/aft stageback signed-volume diagnostic only. A positive row "
                "still needs an explicit termination/collar topology, dual-quality "
                "scan, and pressure sanity before any RANS route-smoke."
            ),
        },
    }
    report_path = output_path / "closed_wall_te_stageback_layer_report.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def write_phase3_closed_wall_te_stageback_core_hybrid_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = 12,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    full_wall_layers: int = 8,
    cap_layers: int = 3,
    stageback_segments: int = 2,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    core_mesh_size: float = 0.35,
    farfield_mesh_size: float = 8.0,
) -> dict[str, Any]:
    """Write a stageback BL + tetra-core hybrid mesh with hidden internal interfaces."""
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    points_per_station = int(surface.metadata["points_per_station"])
    triangle_layer_counts: list[int] = []
    for triangle, marker in wall_triangles:
        if marker in DIAGNOSTIC_FORCE_MARKERS:
            triangle_layer_counts.append(int(cap_layers))
        elif marker in PRIMARY_FORCE_MARKERS and _triangle_touches_te_stageback_band(
            triangle,
            points_per_station=points_per_station,
            stageback_segments=int(stageback_segments),
        ):
            triangle_layer_counts.append(int(cap_layers))
        else:
            triangle_layer_counts.append(int(full_wall_layers))

    bl_volume = _direct_surface_prism_volume(
        surface.vertices,
        wall_triangles,
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=int(full_wall_layers),
        triangle_layer_counts=triangle_layer_counts,
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
        if marker not in {"bl_outer_interface", "bl_termination_interface"}
    }
    for marker, faces in core["marker_faces"].items():
        marker_faces.setdefault(marker, []).extend(
            [
                (element_type, tuple(core_node_map[int(node)] for node in nodes))
                for element_type, nodes in faces
            ]
        )
    compacted_volume, node_compaction = _compact_volume_node_indices(
        {
            "nodes": merged_nodes,
            "elements": elements,
            "marker_faces": marker_faces,
        }
    )
    element_sources = [
        *[
            _phase3_volume_element_source(element_type)
            for element_type, _nodes in bl_volume["elements"]
        ],
        *(["tetra_core"] * len(core["tetra_elements"])),
    ]
    dual_subvolume_proxy = _mixed_dual_subvolume_proxy_report(
        compacted_volume["nodes"],
        compacted_volume["elements"],
        element_sources=element_sources,
        marker_faces=compacted_volume["marker_faces"],
        min_ratio=MAX_ROUTE_DUAL_SUB_VOLUME_RATIO,
        top_count=20,
    )

    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _su2_volume_text(
            compacted_volume,
            comments=(
                "% Canonical hybrid half-wing closed-wall TE-stageback mesh.",
                "% Internal BL outer/termination interfaces are hidden from SU2 markers.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    direct_prism_quality = _direct_prism_quality_metrics(bl_volume)
    return {
        "route": "canonical_hybrid_halfwing_closed_wall_te_stageback_core_hybrid",
        "status": "closed_wall_te_stageback_core_hybrid_written",
        "mesh_path": str(output_path),
        "node_count": len(compacted_volume["nodes"]),
        "volume_element_count": len(elements),
        "volume_element_type_counts": {
            str(SU2_PRISM): len(bl_volume["elements"]),
            str(SU2_TETRAHEDRON): len(core["tetra_elements"]),
        },
        "termination_interface_quad_count": sum(
            1
            for element_type, _nodes in bl_volume["marker_faces"].get(
                "bl_termination_interface",
                [],
            )
            if int(element_type) == SU2_QUAD
        ),
        "node_compaction": node_compaction,
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "core_report": core["report"],
        "dual_subvolume_proxy": dual_subvolume_proxy,
        "direct_prism_quality": direct_prism_quality,
        "direct_prism_quality_gate": _direct_prism_quality_gate(direct_prism_quality),
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Stageback core-hybrid topology candidate only. It must clear "
                "dual-quality and pressure sanity before any RANS route-smoke."
            ),
        },
    }


def write_phase3_closed_wall_te_stageback_buffered_core_hybrid_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = 12,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    full_wall_layers: int = 8,
    cap_layers: int = 3,
    stageback_segments: int = 2,
    transition_buffer_layers: int = 2,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    core_mesh_size: float = 0.35,
    farfield_mesh_size: float = 8.0,
) -> dict[str, Any]:
    """Write stageback BL with a non-wall prism buffer before tetra core."""
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    points_per_station = int(surface.metadata["points_per_station"])
    triangle_layer_counts: list[int] = []
    for triangle, marker in wall_triangles:
        if marker in DIAGNOSTIC_FORCE_MARKERS:
            triangle_layer_counts.append(int(cap_layers))
        elif marker in PRIMARY_FORCE_MARKERS and _triangle_touches_te_stageback_band(
            triangle,
            points_per_station=points_per_station,
            stageback_segments=int(stageback_segments),
        ):
            triangle_layer_counts.append(int(cap_layers))
        else:
            triangle_layer_counts.append(int(full_wall_layers))

    bl_volume = _direct_surface_prism_volume(
        surface.vertices,
        wall_triangles,
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=int(full_wall_layers),
        triangle_layer_counts=triangle_layer_counts,
    )
    buffered_volume = _stageback_transition_buffer_volume(
        bl_volume,
        buffer_layers=int(transition_buffer_layers),
        first_buffer_height_m=first_layer_height_m * growth_ratio ** int(cap_layers),
        growth_ratio=growth_ratio,
    )
    combined_prism_quality = _direct_prism_quality_metrics(buffered_volume)
    try:
        core = _direct_surface_prism_core_tets(
            buffered_volume,
            surface_bounds=_bounds(surface.vertices),
            core_mesh_size=core_mesh_size,
            farfield_mesh_size=farfield_mesh_size,
        )
    except Exception as exc:
        return {
            "route": "canonical_hybrid_halfwing_closed_wall_te_stageback_buffered_core_hybrid",
            "status": "closed_wall_te_stageback_buffered_core_hybrid_blocked",
            "mesh_path": str(out_path),
            "boundary_layer_prism_count": len(bl_volume["elements"]),
            "transition_buffer_prism_count": int(
                buffered_volume["transition_buffer_prism_count"]
            ),
            "combined_prism_quality": combined_prism_quality,
            "combined_prism_quality_gate": _direct_prism_quality_gate(
                combined_prism_quality
            ),
            "core_report": {
                "status": "blocked_before_core_tet_fill",
                "error": str(exc),
            },
            "engineering_assessment": {
                "route_smoke_ready": False,
                "trust_boundary": (
                    "Naive whole-interface transition-buffer extrusion is blocked "
                    "before SU2 handoff; do not promote it to a route candidate."
                ),
            },
        }
    merged_nodes = list(buffered_volume["nodes"])
    core_node_map = _merged_core_node_map(core["nodes"], merged_nodes)
    elements = [
        *buffered_volume["elements"],
        *[
            (SU2_TETRAHEDRON, tuple(core_node_map[int(node)] for node in nodes))
            for nodes in core["tetra_elements"]
        ],
    ]
    marker_faces = {
        marker: list(faces)
        for marker, faces in buffered_volume["marker_faces"].items()
        if marker not in {"bl_outer_interface", "bl_termination_interface"}
    }
    for marker, faces in core["marker_faces"].items():
        marker_faces.setdefault(marker, []).extend(
            [
                (element_type, tuple(core_node_map[int(node)] for node in nodes))
                for element_type, nodes in faces
            ]
        )
    compacted_volume, node_compaction = _compact_volume_node_indices(
        {
            "nodes": merged_nodes,
            "elements": elements,
            "marker_faces": marker_faces,
        }
    )
    element_sources = [
        *[
            _phase3_volume_element_source(element_type)
            for element_type, _nodes in bl_volume["elements"]
        ],
        *(["transition_buffer_prism"] * int(buffered_volume["transition_buffer_prism_count"])),
        *(["tetra_core"] * len(core["tetra_elements"])),
    ]
    dual_subvolume_proxy = _mixed_dual_subvolume_proxy_report(
        compacted_volume["nodes"],
        compacted_volume["elements"],
        element_sources=element_sources,
        marker_faces=compacted_volume["marker_faces"],
        min_ratio=MAX_ROUTE_DUAL_SUB_VOLUME_RATIO,
        top_count=20,
    )

    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _su2_volume_text(
            compacted_volume,
            comments=(
                "% Canonical hybrid half-wing TE-stageback buffered transition mesh.",
                "% Non-wall transition buffer separates thin BL prisms from tetra core.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    return {
        "route": "canonical_hybrid_halfwing_closed_wall_te_stageback_buffered_core_hybrid",
        "status": "closed_wall_te_stageback_buffered_core_hybrid_written",
        "mesh_path": str(output_path),
        "node_count": len(compacted_volume["nodes"]),
        "volume_element_count": len(elements),
        "volume_element_type_counts": {
            str(SU2_PRISM): len(buffered_volume["elements"]),
            str(SU2_TETRAHEDRON): len(core["tetra_elements"]),
        },
        "boundary_layer_prism_count": len(bl_volume["elements"]),
        "transition_buffer_prism_count": int(buffered_volume["transition_buffer_prism_count"]),
        "node_compaction": node_compaction,
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "core_report": core["report"],
        "dual_subvolume_proxy": dual_subvolume_proxy,
        "combined_prism_quality": combined_prism_quality,
        "combined_prism_quality_gate": _direct_prism_quality_gate(combined_prism_quality),
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Buffered stageback topology candidate only. Passing parser and "
                "ownership checks is not pressure sanity or RANS route-smoke."
            ),
        },
    }


def run_phase3_partial_wing_cap_core_probe(
    section_table_path: Path | str,
    output_dir: Path | str,
    *,
    points_per_side: int = 12,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = 4,
    core_mesh_size: float = 0.35,
    farfield_mesh_size: float = 8.0,
) -> dict[str, Any]:
    """Probe the partial-BL cap-materialized inner boundary with a tetra core."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    cap_markers = set(DIAGNOSTIC_FORCE_MARKERS)
    cap_triangles = [
        (triangle, marker)
        for triangle, marker in wall_triangles
        if marker in cap_markers
    ]
    prism_volume = _direct_surface_prism_volume(
        surface.vertices,
        [
            (triangle, marker)
            for triangle, marker in wall_triangles
            if marker in PRIMARY_FORCE_MARKERS
        ],
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
        edge_marker_map=_cap_edge_marker_map(cap_triangles),
    )
    inner_boundary = _partial_wing_cap_core_inner_boundary_surface(
        prism_volume,
        cap_triangles=cap_triangles,
    )
    core_report = _partial_wing_cap_core_tets(
        inner_boundary,
        surface_bounds=_bounds(surface.vertices),
        output_dir=output_path,
        core_mesh_size=core_mesh_size,
        farfield_mesh_size=farfield_mesh_size,
    )
    report = {
        "route": "canonical_hybrid_halfwing_partial_wing_cap_core_probe",
        "status": "partial_wing_cap_core_probe_meshed",
        "case_dir": str(output_path),
        "surface": {
            "marker_counts": surface.marker_counts(),
            "metadata": surface.metadata,
        },
        "partial_prism": {
            "node_count": len(prism_volume["nodes"]),
            "volume_element_count": len(prism_volume["elements"]),
            "direct_prism_quality": _direct_prism_quality_metrics(prism_volume),
            "direct_prism_quality_gate": _direct_prism_quality_gate(
                _direct_prism_quality_metrics(prism_volume)
            ),
        },
        "inner_boundary": {
            "marker_counts": inner_boundary.marker_counts(),
            "face_count": len(inner_boundary.faces),
        },
        "inner_boundary_topology": _surface_edge_topology(inner_boundary),
        "core_report": core_report,
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Small cap-materialized core probe only. It proves the partial-BL "
                "cap topology can tetra-fill without pyramids at this resolution, "
                "but it is not the wall-resolved route-smoke mesh."
            ),
        },
    }
    (output_path / "partial_wing_cap_core_probe_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def write_phase3_minimal_transition_unit_su2(out_path: Path | str) -> dict[str, Any]:
    """Write a tiny prism->pyramid->tet collar contract mesh.

    This is deliberately not the real wing. It is the topology unit GPT Pro
    recommended before touching the full half-wing again: prism BL cells may
    touch tetra core through triangular outer faces, but exposed prism rim quads
    must transition through pyramid collars before tetra cells appear.
    """
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    volume = _minimal_transition_unit_volume()
    output_path.write_text(
        _su2_volume_text(
            volume,
            comments=(
                "% Canonical hybrid half-wing minimal transition topology unit.",
                "% Prism rim quads are connected through pyramid collars before tetra core.",
                "% This is a topology contract only, not an aerodynamic CFD mesh.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    topology = _transition_topology_report(volume)
    quality = _transition_element_quality(volume)
    quality_gate = _transition_element_quality_gate(quality)
    gate = _minimal_transition_unit_gate(topology, quality_gate, boundary_ownership)
    type_counts: dict[str, int] = {}
    for element_type, _nodes in volume["elements"]:
        key = str(element_type)
        type_counts[key] = type_counts.get(key, 0) + 1
    report = {
        "route": "canonical_hybrid_halfwing_minimal_transition_unit",
        "status": "transition_topology_unit_pass" if gate["status"] == "pass" else "transition_topology_unit_fail",
        "mesh_path": str(output_path),
        "report_path": str(output_path.with_suffix(".report.json")),
        "node_count": len(volume["nodes"]),
        "volume_element_count": len(volume["elements"]),
        "volume_element_type_counts": dict(sorted(type_counts.items())),
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "topology": topology,
        "element_quality": quality,
        "element_quality_gate": quality_gate,
        "gate": gate,
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Minimal artificial topology unit only. It proves the contract "
                "for prism BL, pyramid transition collar, and tetra core handoff; "
                "it does not prove the real wing caps, SU2 dual quality, or drag."
            ),
        },
    }
    Path(report["report_path"]).write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def write_phase3_segmented_collar_scale_transition_unit_su2(
    out_path: Path | str,
) -> dict[str, Any]:
    """Write a segmented rim-collar unit that limits BL-to-core scale jumps."""
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    volume = _segmented_collar_scale_transition_unit_volume()
    output_path.write_text(
        _su2_volume_text(
            volume,
            comments=(
                "% Canonical hybrid half-wing segmented collar scale-transition unit.",
                "% Long prism rim quads are split before pyramid collar handoff.",
                "% This is a topology/scale contract only, not an aerodynamic CFD mesh.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    topology = _transition_topology_report(volume)
    quality = _transition_element_quality(volume)
    quality_gate = _transition_element_quality_gate(quality)
    element_sources = [
        _phase3_volume_element_source(element_type)
        for element_type, _nodes in volume["elements"]
    ]
    dual_subvolume_proxy = _mixed_dual_subvolume_proxy_report(
        volume["nodes"],
        volume["elements"],
        element_sources=element_sources,
        marker_faces=volume["marker_faces"],
        min_ratio=MAX_ROUTE_DUAL_SUB_VOLUME_RATIO,
        top_count=20,
    )
    gate = _minimal_transition_unit_gate(topology, quality_gate, boundary_ownership)
    blockers = [*gate["blockers"], *dual_subvolume_proxy["blockers"]]
    type_counts: dict[str, int] = {}
    for element_type, _nodes in volume["elements"]:
        key = str(element_type)
        type_counts[key] = type_counts.get(key, 0) + 1
    report = {
        "route": "canonical_hybrid_halfwing_segmented_collar_scale_transition_unit",
        "status": (
            "segmented_collar_scale_transition_unit_pass"
            if not blockers
            else "segmented_collar_scale_transition_unit_fail"
        ),
        "mesh_path": str(output_path),
        "report_path": str(output_path.with_suffix(".report.json")),
        "node_count": len(volume["nodes"]),
        "volume_element_count": len(volume["elements"]),
        "volume_element_type_counts": dict(sorted(type_counts.items())),
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "topology": topology,
        "element_quality": quality,
        "element_quality_gate": quality_gate,
        "dual_subvolume_proxy": dual_subvolume_proxy,
        "segmented_collar": volume["segmented_collar"],
        "gate": {
            "status": "pass" if not blockers else "fail",
            "blockers": sorted(set(blockers)),
        },
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Artificial segmented-collar scale-transition unit only. It proves "
                "a local rim segmentation rule can satisfy the pre-solver scale-jump "
                "gate; it does not prove real-wing cap/ramp geometry or pressure CD."
            ),
        },
    }
    Path(report["report_path"]).write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def write_phase3_structured_transition_patch_unit_su2(
    out_path: Path | str,
) -> dict[str, Any]:
    """Write an artificial multi-row transition patch before tetra core."""
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    volume = _structured_transition_patch_unit_volume()
    output_path.write_text(
        _su2_volume_text(
            volume,
            comments=(
                "% Canonical hybrid half-wing structured transition patch unit.",
                "% Pyramid collar side triangles feed transition prism rows before tetra core.",
                "% This is a topology/scale contract only, not an aerodynamic CFD mesh.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    topology = _transition_topology_report(volume)
    quality = _transition_element_quality(volume)
    quality_gate = _transition_element_quality_gate(quality)
    element_sources = [
        str(_mapping(role).get("source") or _phase3_volume_element_source(element_type))
        for (element_type, _nodes), role in zip(
            volume["elements"],
            volume["element_roles"],
        )
    ]
    dual_subvolume_proxy = _mixed_dual_subvolume_proxy_report(
        volume["nodes"],
        volume["elements"],
        element_sources=element_sources,
        marker_faces=volume["marker_faces"],
        min_ratio=MAX_ROUTE_DUAL_SUB_VOLUME_RATIO,
        top_count=20,
    )
    scale_blockers: list[str] = []
    if int(topology.get("tet_to_prism_quad_contact") or 0) != 0:
        scale_blockers.append("structured_transition_tet_contacts_prism_quad")
    if int(topology.get("pyramid_boundary_face_count") or 0) != 0:
        scale_blockers.append("structured_transition_pyramid_boundary_faces_exposed")
    if quality_gate.get("status") != "pass":
        scale_blockers.extend(
            str(blocker) for blocker in quality_gate.get("blockers") or []
        )
    if boundary_ownership.get("status") != "pass":
        scale_blockers.append("structured_transition_su2_boundary_ownership_not_pass")
    scale_blockers.extend(
        str(blocker) for blocker in dual_subvolume_proxy.get("blockers") or []
    )
    sidewall_quad_count = int(topology.get("non_root_exposed_prism_quad_count") or 0)
    sidewall_blockers = (
        ["structured_transition_sidewall_quads_pending"]
        if sidewall_quad_count > 0
        else []
    )
    blockers = [*scale_blockers, *sidewall_blockers]
    if not blockers:
        status = "structured_transition_patch_unit_pass"
    elif not scale_blockers and sidewall_blockers:
        status = "structured_transition_patch_unit_scale_pass_sidewalls_pending"
    else:
        status = "structured_transition_patch_unit_fail"
    type_counts: dict[str, int] = {}
    for element_type, _nodes in volume["elements"]:
        key = str(element_type)
        type_counts[key] = type_counts.get(key, 0) + 1
    report = {
        "route": "canonical_hybrid_halfwing_structured_transition_patch_unit",
        "status": status,
        "mesh_path": str(output_path),
        "report_path": str(output_path.with_suffix(".report.json")),
        "node_count": len(volume["nodes"]),
        "volume_element_count": len(volume["elements"]),
        "volume_element_type_counts": dict(sorted(type_counts.items())),
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "topology": topology,
        "element_quality": quality,
        "element_quality_gate": quality_gate,
        "dual_subvolume_proxy": dual_subvolume_proxy,
        "structured_transition": {
            **volume["structured_transition"],
            "sidewall_quad_status": (
                "pending" if sidewall_quad_count > 0 else "pass"
            ),
            "core_interface_sidewall_quad_count": sidewall_quad_count,
        },
        "gate": {
            "status": "pass" if not blockers else "blocked",
            "blockers": sorted(set(blockers)),
        },
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Artificial structured-transition unit only. It proves that "
                "collar-side triangles can be handed to prism transition rows "
                "before tetra core so large core edges do not touch BL/collar "
                "vertices directly. It does not prove real-wing cap/ramp geometry."
            ),
        },
    }
    Path(report["report_path"]).write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def write_phase3_partial_wing_transition_collar_handoff_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = 12,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = 4,
    collar_height_m: float = 1.0e-4,
) -> dict[str, Any]:
    """Convert partial-BL rim quads into pyramid transition-collar faces.

    This is a real-wing handoff probe, not the final merged core. It preserves
    prism BL on `wing_upper`/`wing_lower`, turns TE/tip/closure prism side quads
    into pyramid bases, and exposes only triangular transition faces for a future
    tetra core. Original cap faces and the core fill remain explicit blockers.
    """
    prism_wall_markers = set(PRIMARY_FORCE_MARKERS)
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    cap_triangles = [
        (triangle, marker)
        for triangle, marker in wall_triangles
        if marker in DIAGNOSTIC_FORCE_MARKERS
    ]
    prism_volume = _direct_surface_prism_volume(
        surface.vertices,
        [
            (triangle, marker)
            for triangle, marker in wall_triangles
            if marker in prism_wall_markers
        ],
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
        edge_marker_map=_cap_edge_marker_map(cap_triangles),
    )
    collar_volume, collar_report = _partial_wing_transition_collar_volume(
        prism_volume,
        collar_height_m=collar_height_m,
    )
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _su2_volume_text(
            collar_volume,
            comments=(
                "% Canonical hybrid half-wing partial-BL transition-collar handoff.",
                "% TE/tip/closure prism rim quads are internal pyramid bases.",
                "% Original cap faces and tetra core are still pending.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    type_counts: dict[str, int] = {}
    for element_type, _nodes in collar_volume["elements"]:
        key = str(element_type)
        type_counts[key] = type_counts.get(key, 0) + 1
    outer_interface = marker_summary["markers"].get("bl_outer_interface", {})
    collar_interface = marker_summary["markers"].get("transition_collar_interface", {})
    interface_element_count = int(outer_interface.get("element_count") or 0) + int(
        collar_interface.get("element_count") or 0
    )
    direct_prism_quality = _direct_prism_quality_metrics(collar_volume)
    report = {
        "route": "canonical_hybrid_halfwing_partial_wing_transition_collar_handoff",
        "status": "partial_wing_transition_collar_ready_caps_pending",
        "mesh_path": str(output_path),
        "node_count": len(collar_volume["nodes"]),
        "volume_element_count": len(collar_volume["elements"]),
        "volume_element_type_counts": dict(sorted(type_counts.items())),
        "boundary_layer_cell_count": int(type_counts.get(str(SU2_PRISM), 0)),
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "direct_prism_quality": direct_prism_quality,
        "direct_prism_quality_gate": _direct_prism_quality_gate(direct_prism_quality),
        "transition_collar": collar_report,
        "core_tetra_interface": {
            "status": "triangular_transition_interface_ready_caps_pending",
            "markers": ["bl_outer_interface", "transition_collar_interface"],
            "element_count": interface_element_count,
            "element_type_counts": {str(SU2_TRIANGLE): interface_element_count},
        },
        "cap_closure_topology": {
            "status": "blocked_original_caps_and_core_missing",
            "source_surface_face_counts": {
                marker: surface.marker_counts().get(marker, 0)
                for marker in DIAGNOSTIC_FORCE_MARKERS
            },
            "required_policy": (
                "Original tip/TE/closure cap faces must be materialized as physical "
                "core boundary markers; prism rim side quads must remain internal "
                "transition-collar bases, not force walls."
            ),
        },
        "forbidden_route_checks": {
            "all_tet_global_star_bl_handoff": False,
            "boundary_layer_split_to_tetra": False,
            "closure_faces_merged_into_wing_wall": False,
            "prism_rim_quads_exposed_as_force_walls": (
                collar_report["force_wall_rim_marker_leak_count"] > 0
            ),
        },
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Real-wing partial-BL collar handoff only. It proves rim quads can "
                "be converted to pyramid transition bases with triangular core "
                "interface faces, but original cap faces, tetra core, SU2 dual "
                "quality, pressure sanity, and RANS route-smoke are still pending."
            ),
        },
    }
    return report


def write_phase3_segmented_partial_wing_transition_collar_handoff_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = 12,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = 4,
    collar_height_m: float = 1.0e-4,
) -> dict[str, Any]:
    """Split source rim edges before creating the partial-BL collar handoff."""
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    cap_triangles = [
        (triangle, marker)
        for triangle, marker in wall_triangles
        if marker in DIAGNOSTIC_FORCE_MARKERS
    ]
    edge_marker_map = _cap_edge_marker_map(cap_triangles)
    source_edge_segments, source_edge_report = _source_rim_edge_split_plan(
        surface.vertices,
        [
            (triangle, marker)
            for triangle, marker in wall_triangles
            if marker in PRIMARY_FORCE_MARKERS
        ],
        edge_marker_map=edge_marker_map,
        first_layer_height_m=first_layer_height_m,
    )
    segmented_vertices, segmented_wall_triangles, segmented_surface_report = (
        _split_wall_triangles_on_source_edges(
            surface.vertices,
            wall_triangles,
            edge_segment_counts=source_edge_segments,
        )
    )
    segmented_cap_triangles = [
        (triangle, marker)
        for triangle, marker in segmented_wall_triangles
        if marker in DIAGNOSTIC_FORCE_MARKERS
    ]
    prism_volume = _direct_surface_prism_volume(
        segmented_vertices,
        [
            (triangle, marker)
            for triangle, marker in segmented_wall_triangles
            if marker in PRIMARY_FORCE_MARKERS
        ],
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
        edge_marker_map=_cap_edge_marker_map(segmented_cap_triangles),
    )
    collar_volume, collar_report = _partial_wing_transition_collar_volume(
        prism_volume,
        collar_height_m=collar_height_m,
    )
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _su2_volume_text(
            collar_volume,
            comments=(
                "% Canonical hybrid half-wing segmented partial-BL collar handoff.",
                "% Source rim edges are split before BL extrusion.",
                "% Original cap faces and tetra core are still pending.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    type_counts: dict[str, int] = {}
    for element_type, _nodes in collar_volume["elements"]:
        key = str(element_type)
        type_counts[key] = type_counts.get(key, 0) + 1
    direct_prism_quality = _direct_prism_quality_metrics(collar_volume)
    return {
        "route": (
            "canonical_hybrid_halfwing_segmented_partial_wing_transition_collar_handoff"
        ),
        "status": "segmented_partial_wing_transition_collar_ready_caps_pending",
        "mesh_path": str(output_path),
        "node_count": len(collar_volume["nodes"]),
        "volume_element_count": len(collar_volume["elements"]),
        "volume_element_type_counts": dict(sorted(type_counts.items())),
        "boundary_layer_cell_count": int(type_counts.get(str(SU2_PRISM), 0)),
        "source_rim_edge_split_plan": source_edge_report,
        "segmented_surface": segmented_surface_report,
        "marker_summary": marker_summary["markers"],
        "su2_boundary_ownership": boundary_ownership,
        "direct_prism_quality": direct_prism_quality,
        "direct_prism_quality_gate": _direct_prism_quality_gate(direct_prism_quality),
        "transition_collar": collar_report,
        "forbidden_route_checks": {
            "all_tet_global_star_bl_handoff": False,
            "boundary_layer_split_to_tetra": False,
            "closure_faces_merged_into_wing_wall": False,
            "prism_rim_quads_exposed_as_force_walls": (
                collar_report["force_wall_rim_marker_leak_count"] > 0
            ),
        },
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Segmented source-rim handoff only. It verifies that the long "
                "TE/tip/closure rim edges can be split before prism extrusion so "
                "the pyramid collar bases stay inside the local edge-ratio gate. "
                "Merged tetra core, dual-quality, pressure sanity, and RANS are "
                "still pending."
            ),
        },
    }


def write_phase3_segmented_partial_wing_transition_collar_core_hybrid_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = 12,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = 4,
    collar_height_m: float = 1.0e-4,
    core_mesh_size: float = 0.35,
    farfield_mesh_size: float = 8.0,
    core_boundary_point_mesh_size: float | None = None,
    core_boundary_point_markers: Sequence[str] = ("transition_collar_interface",),
) -> dict[str, Any]:
    """Write segmented source-rim partial-BL collar plus tetra-core SU2 mesh."""
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    cap_triangles = [
        (triangle, marker)
        for triangle, marker in wall_triangles
        if marker in DIAGNOSTIC_FORCE_MARKERS
    ]
    source_edge_segments, source_edge_report = _source_rim_edge_split_plan(
        surface.vertices,
        [
            (triangle, marker)
            for triangle, marker in wall_triangles
            if marker in PRIMARY_FORCE_MARKERS
        ],
        edge_marker_map=_cap_edge_marker_map(cap_triangles),
        first_layer_height_m=first_layer_height_m,
    )
    segmented_vertices, segmented_wall_triangles, segmented_surface_report = (
        _split_wall_triangles_on_source_edges(
            surface.vertices,
            wall_triangles,
            edge_segment_counts=source_edge_segments,
        )
    )
    segmented_cap_triangles = [
        (triangle, marker)
        for triangle, marker in segmented_wall_triangles
        if marker in DIAGNOSTIC_FORCE_MARKERS
    ]
    prism_volume = _direct_surface_prism_volume(
        segmented_vertices,
        [
            (triangle, marker)
            for triangle, marker in segmented_wall_triangles
            if marker in PRIMARY_FORCE_MARKERS
        ],
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
        edge_marker_map=_cap_edge_marker_map(segmented_cap_triangles),
    )
    collar_volume, collar_report = _partial_wing_transition_collar_volume(
        prism_volume,
        collar_height_m=collar_height_m,
    )
    inner_boundary = _partial_wing_transition_collar_core_inner_boundary_surface(
        collar_volume,
        cap_triangles=segmented_cap_triangles,
    )
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    core = _partial_wing_transition_collar_core_tets(
        inner_boundary,
        surface_bounds=_bounds(segmented_vertices),
        output_dir=output_path.parent / f"{output_path.stem}_core",
        core_mesh_size=core_mesh_size,
        farfield_mesh_size=farfield_mesh_size,
        boundary_point_mesh_size=core_boundary_point_mesh_size,
        boundary_point_markers=core_boundary_point_markers,
    )
    merged_nodes = list(collar_volume["nodes"])
    core_node_map = _merged_core_node_map(core["nodes"], merged_nodes)
    collar_element_sources = [
        _phase3_volume_element_source(element_type)
        for element_type, _nodes in collar_volume["elements"]
    ]
    elements = [
        *collar_volume["elements"],
        *[
            (SU2_TETRAHEDRON, tuple(core_node_map[int(node)] for node in nodes))
            for nodes in core["tetra_elements"]
        ],
    ]
    element_sources = [
        *collar_element_sources,
        *(["tetra_core"] * len(core["tetra_elements"])),
    ]
    marker_faces = {
        marker: list(faces)
        for marker, faces in collar_volume["marker_faces"].items()
        if marker not in {"bl_outer_interface", "transition_collar_interface"}
    }
    for marker, faces in core["marker_faces"].items():
        marker_faces.setdefault(marker, []).extend(
            [
                (element_type, tuple(core_node_map[int(node)] for node in nodes))
                for element_type, nodes in faces
            ]
        )
    compacted_volume, node_compaction = _compact_volume_node_indices(
        {
            "nodes": merged_nodes,
            "elements": elements,
            "marker_faces": marker_faces,
        }
    )
    dual_subvolume_proxy = _mixed_dual_subvolume_proxy_report(
        compacted_volume["nodes"],
        compacted_volume["elements"],
        element_sources=element_sources,
        marker_faces=compacted_volume["marker_faces"],
        min_ratio=MAX_ROUTE_DUAL_SUB_VOLUME_RATIO,
        top_count=20,
    )
    output_path.write_text(
        _su2_volume_text(
            compacted_volume,
            comments=(
                "% Canonical hybrid half-wing segmented partial-BL collar core mesh.",
                "% Internal BL/collar interfaces are merged and not written as markers.",
                "% This is a topology/pressure-sanity candidate, not route-smoke truth.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    type_counts: dict[str, int] = {}
    for element_type, _nodes in elements:
        key = str(element_type)
        type_counts[key] = type_counts.get(key, 0) + 1
    required_markers_present = all(
        marker in marker_summary["markers"] for marker in REQUIRED_MARKERS
    )
    direct_prism_quality = _direct_prism_quality_metrics(collar_volume)
    return {
        "route": (
            "canonical_hybrid_halfwing_segmented_partial_wing_transition_collar_core_hybrid"
        ),
        "status": "segmented_partial_wing_transition_collar_core_hybrid_written",
        "mesh_path": str(output_path),
        "node_count": len(compacted_volume["nodes"]),
        "volume_element_count": len(elements),
        "volume_element_type_counts": dict(sorted(type_counts.items())),
        "boundary_layer_cell_count": int(type_counts.get(str(SU2_PRISM), 0)),
        "source_rim_edge_split_plan": source_edge_report,
        "segmented_surface": segmented_surface_report,
        "node_compaction": node_compaction,
        "transition_collar": collar_report,
        "core_report": core["report"],
        "marker_summary": marker_summary["markers"],
        "required_markers_present": required_markers_present,
        "su2_boundary_ownership": boundary_ownership,
        "dual_subvolume_proxy": dual_subvolume_proxy,
        "direct_prism_quality": direct_prism_quality,
        "direct_prism_quality_gate": _direct_prism_quality_gate(direct_prism_quality),
        "forbidden_route_checks": {
            "all_tet_global_star_bl_handoff": False,
            "boundary_layer_split_to_tetra": False,
            "closure_faces_merged_into_wing_wall": False,
            "interface_markers_written_to_final_mesh": any(
                marker in marker_summary["markers"]
                for marker in ("bl_outer_interface", "transition_collar_interface")
            ),
        },
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Merged segmented source-rim hybrid mesh only. The dual proxy is "
                "the pre-solver decision point; pressure/RANS remain blocked if "
                "the collar/core interface still fails this gate."
            ),
        },
    }


def run_phase3_partial_wing_transition_collar_core_probe(
    section_table_path: Path | str,
    output_dir: Path | str,
    *,
    points_per_side: int = 12,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = 4,
    collar_height_m: float = 1.0e-4,
    core_mesh_size: float = 0.35,
    farfield_mesh_size: float = 8.0,
) -> dict[str, Any]:
    """Probe tetra-core fill after real-wing partial-BL pyramid collars."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    cap_triangles = [
        (triangle, marker)
        for triangle, marker in wall_triangles
        if marker in DIAGNOSTIC_FORCE_MARKERS
    ]
    prism_volume = _direct_surface_prism_volume(
        surface.vertices,
        [
            (triangle, marker)
            for triangle, marker in wall_triangles
            if marker in PRIMARY_FORCE_MARKERS
        ],
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
        edge_marker_map=_cap_edge_marker_map(cap_triangles),
    )
    collar_volume, collar_report = _partial_wing_transition_collar_volume(
        prism_volume,
        collar_height_m=collar_height_m,
    )
    inner_boundary = _partial_wing_transition_collar_core_inner_boundary_surface(
        collar_volume,
        cap_triangles=cap_triangles,
    )
    core_report = _partial_wing_cap_core_tets(
        inner_boundary,
        surface_bounds=_bounds(surface.vertices),
        output_dir=output_path,
        core_mesh_size=core_mesh_size,
        farfield_mesh_size=farfield_mesh_size,
    )
    report = {
        "route": "canonical_hybrid_halfwing_partial_wing_transition_collar_core_probe",
        "status": "partial_wing_transition_collar_core_probe_meshed",
        "case_dir": str(output_path),
        "surface": {
            "marker_counts": surface.marker_counts(),
            "metadata": surface.metadata,
        },
        "partial_prism": {
            "node_count": len(prism_volume["nodes"]),
            "volume_element_count": len(prism_volume["elements"]),
            "direct_prism_quality": _direct_prism_quality_metrics(prism_volume),
            "direct_prism_quality_gate": _direct_prism_quality_gate(
                _direct_prism_quality_metrics(prism_volume)
            ),
        },
        "transition_collar": collar_report,
        "inner_boundary": {
            "marker_counts": inner_boundary.marker_counts(),
            "face_count": len(inner_boundary.faces),
        },
        "inner_boundary_topology": _surface_edge_topology(inner_boundary),
        "core_report": core_report,
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Small collar-plus-cap core probe only. It proves the real-wing "
                "partial-BL collar interface can tetra-fill at this resolution, "
                "but it is not a merged SU2 hybrid mesh and not route-smoke."
            ),
        },
    }
    (output_path / "partial_wing_transition_collar_core_probe_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def write_phase3_partial_wing_transition_collar_core_hybrid_su2(
    section_table_path: Path | str,
    out_path: Path | str,
    *,
    points_per_side: int = 12,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    first_layer_height_m: float = DEFAULT_FIRST_LAYER_HEIGHT_M,
    growth_ratio: float = DEFAULT_GROWTH_RATIO,
    bl_layers: int = 4,
    collar_height_m: float = 1.0e-4,
    core_mesh_size: float = 0.35,
    farfield_mesh_size: float = 8.0,
) -> dict[str, Any]:
    """Write merged partial-BL prism/pyramid collar plus tetra-core SU2 mesh."""
    surface = build_phase3_route_smoke_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    wall_triangles = _triangulated_wall_triangles(surface)
    cap_triangles = [
        (triangle, marker)
        for triangle, marker in wall_triangles
        if marker in DIAGNOSTIC_FORCE_MARKERS
    ]
    prism_volume = _direct_surface_prism_volume(
        surface.vertices,
        [
            (triangle, marker)
            for triangle, marker in wall_triangles
            if marker in PRIMARY_FORCE_MARKERS
        ],
        first_layer_height_m=first_layer_height_m,
        growth_ratio=growth_ratio,
        bl_layers=bl_layers,
        edge_marker_map=_cap_edge_marker_map(cap_triangles),
    )
    collar_volume, collar_report = _partial_wing_transition_collar_volume(
        prism_volume,
        collar_height_m=collar_height_m,
    )
    inner_boundary = _partial_wing_transition_collar_core_inner_boundary_surface(
        collar_volume,
        cap_triangles=cap_triangles,
    )
    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    core = _partial_wing_transition_collar_core_tets(
        inner_boundary,
        surface_bounds=_bounds(surface.vertices),
        output_dir=output_path.parent / f"{output_path.stem}_core",
        core_mesh_size=core_mesh_size,
        farfield_mesh_size=farfield_mesh_size,
    )
    merged_nodes = list(collar_volume["nodes"])
    core_node_map = _merged_core_node_map(core["nodes"], merged_nodes)
    collar_element_sources = [
        _phase3_volume_element_source(element_type)
        for element_type, _nodes in collar_volume["elements"]
    ]
    elements = [
        *collar_volume["elements"],
        *[
            (SU2_TETRAHEDRON, tuple(core_node_map[int(node)] for node in nodes))
            for nodes in core["tetra_elements"]
        ],
    ]
    element_sources = [
        *collar_element_sources,
        *(["tetra_core"] * len(core["tetra_elements"])),
    ]
    marker_faces = {
        marker: list(faces)
        for marker, faces in collar_volume["marker_faces"].items()
        if marker not in {"bl_outer_interface", "transition_collar_interface"}
    }
    for marker, faces in core["marker_faces"].items():
        marker_faces.setdefault(marker, []).extend(
            [
                (element_type, tuple(core_node_map[int(node)] for node in nodes))
                for element_type, nodes in faces
            ]
        )
    compacted_volume, node_compaction = _compact_volume_node_indices(
        {
            "nodes": merged_nodes,
            "elements": elements,
            "marker_faces": marker_faces,
        }
    )
    dual_subvolume_proxy = _mixed_dual_subvolume_proxy_report(
        compacted_volume["nodes"],
        compacted_volume["elements"],
        element_sources=element_sources,
        marker_faces=compacted_volume["marker_faces"],
        min_ratio=MAX_ROUTE_DUAL_SUB_VOLUME_RATIO,
        top_count=20,
    )
    output_path.write_text(
        _su2_volume_text(
            compacted_volume,
            comments=(
                "% Canonical hybrid half-wing partial-BL transition-collar core mesh.",
                "% Internal BL/collar interfaces are merged and not written as markers.",
                "% This is a topology/pressure-sanity candidate, not route-smoke truth.",
            ),
        ),
        encoding="utf-8",
    )
    marker_summary = parse_su2_marker_summary(output_path)
    boundary_ownership = audit_su2_boundary_face_ownership(output_path)
    type_counts: dict[str, int] = {}
    for element_type, _nodes in elements:
        key = str(element_type)
        type_counts[key] = type_counts.get(key, 0) + 1
    required_markers_present = all(
        marker in marker_summary["markers"] for marker in REQUIRED_MARKERS
    )
    direct_prism_quality = _direct_prism_quality_metrics(collar_volume)
    return {
        "route": "canonical_hybrid_halfwing_partial_wing_transition_collar_core_hybrid",
        "status": "partial_wing_transition_collar_core_hybrid_written",
        "mesh_path": str(output_path),
        "node_count": len(compacted_volume["nodes"]),
        "volume_element_count": len(elements),
        "volume_element_type_counts": dict(sorted(type_counts.items())),
        "boundary_layer_cell_count": int(type_counts.get(str(SU2_PRISM), 0)),
        "node_compaction": node_compaction,
        "transition_collar": collar_report,
        "core_report": core["report"],
        "marker_summary": marker_summary["markers"],
        "required_markers_present": required_markers_present,
        "su2_boundary_ownership": boundary_ownership,
        "dual_subvolume_proxy": dual_subvolume_proxy,
        "direct_prism_quality": direct_prism_quality,
        "direct_prism_quality_gate": _direct_prism_quality_gate(direct_prism_quality),
        "forbidden_route_checks": {
            "all_tet_global_star_bl_handoff": False,
            "boundary_layer_split_to_tetra": False,
            "closure_faces_merged_into_wing_wall": False,
            "interface_markers_written_to_final_mesh": any(
                marker in marker_summary["markers"]
                for marker in ("bl_outer_interface", "transition_collar_interface")
            ),
        },
        "engineering_assessment": {
            "route_smoke_ready": False,
            "trust_boundary": (
                "Merged small-scale hybrid mesh only. The mixed-element dual-subvolume "
                "proxy is a pre-solver blocker if it reproduces SU2-scale CV pathology; "
                "do not run RANS until the collar/core interface passes this gate."
            ),
        },
    }


def _partial_wing_transition_collar_core_tets(
    inner_boundary: SurfaceMesh,
    *,
    surface_bounds: Mapping[str, float],
    output_dir: Path,
    core_mesh_size: float,
    farfield_mesh_size: float,
    boundary_point_mesh_size: float | None = None,
    boundary_point_markers: Sequence[str] = ("transition_collar_interface",),
) -> dict[str, Any]:
    import gmsh

    output_dir.mkdir(parents=True, exist_ok=True)
    inner_surface_first_tag = 7_000_001
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("canonical_partial_wing_transition_collar_core")
        inner_by_marker = _add_discrete_marked_mesh_surfaces(
            gmsh,
            inner_boundary,
            first_tag=inner_surface_first_tag,
            triangulation_policy="fixed_diagonal",
        )
        inner_tags = [
            tag for tags in inner_by_marker.values() for tag in tags
        ]
        gmsh.model.geo.synchronize()
        _farfield_vertices, symmetry_tags, farfield_tags = _add_farfield_box_with_symmetry_hole(
            gmsh,
            bounds=surface_bounds,
            bl_top_surface_tags=inner_tags,
            farfield_mesh_size=farfield_mesh_size,
        )
        core_volume = gmsh.model.geo.addVolume(
            [
                gmsh.model.geo.addSurfaceLoop(
                    [*inner_tags, *symmetry_tags, *farfield_tags]
                )
            ]
        )
        gmsh.model.geo.synchronize()
        for marker in (*DIAGNOSTIC_FORCE_MARKERS, "bl_outer_interface", "transition_collar_interface"):
            tags = inner_by_marker.get(marker, [])
            if tags:
                group = gmsh.model.addPhysicalGroup(2, tags)
                gmsh.model.setPhysicalName(2, group, marker)
        symmetry_group = gmsh.model.addPhysicalGroup(2, symmetry_tags)
        gmsh.model.setPhysicalName(2, symmetry_group, "root_symmetry")
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_tags)
        gmsh.model.setPhysicalName(2, farfield_group, "farfield")
        fluid_group = gmsh.model.addPhysicalGroup(3, [core_volume])
        gmsh.model.setPhysicalName(3, fluid_group, "fluid_core")
        boundary_point_entities, boundary_point_report = _core_boundary_point_size_targets(
            inner_boundary,
            point_tag_offset=inner_surface_first_tag,
            mesh_size=boundary_point_mesh_size,
            markers=boundary_point_markers,
        )
        if boundary_point_entities and boundary_point_mesh_size is not None:
            gmsh.model.mesh.setSize(
                boundary_point_entities,
                float(boundary_point_mesh_size),
            )
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(core_mesh_size, farfield_mesh_size))
        gmsh.option.setNumber("Mesh.MeshSizeMax", max(core_mesh_size, farfield_mesh_size))
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        core_algorithm3d = 1
        gmsh.option.setNumber("Mesh.Algorithm3D", core_algorithm3d)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(output_dir / "core.msh"))
        all_nodes = _gmsh_node_coordinates(gmsh)
        tetra_elements = _gmsh_tetra_elements(gmsh)
        raw_marker_faces = {
            marker: _gmsh_surface_marker_faces(gmsh, inner_by_marker.get(marker, []))
            for marker in DIAGNOSTIC_FORCE_MARKERS
            if inner_by_marker.get(marker)
        }
        raw_marker_faces["root_symmetry"] = _gmsh_surface_marker_faces(gmsh, symmetry_tags)
        raw_marker_faces["farfield"] = _gmsh_surface_marker_faces(gmsh, farfield_tags)
        marker_faces = _orient_core_marker_faces_from_tetrahedra(
            tetra_elements,
            raw_marker_faces,
        )
        nodes, unused_node_tags = _active_core_node_coordinates(
            all_nodes,
            tetra_elements,
            marker_faces,
        )
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
        volume_types, volume_tags, _ = gmsh.model.mesh.getElements(3)
        type_counts = {
            str(element_type): len(tags)
            for element_type, tags in zip(volume_types, volume_tags)
        }
        forbidden_counts = {
            kind: count
            for kind, count in type_counts.items()
            if kind != GMSH_TETRA and int(count) > 0
        }
        return {
            "nodes": nodes,
            "tetra_elements": tetra_elements,
            "marker_faces": marker_faces,
            "report": {
                "status": "meshed",
                "node_tag_integrity": {
                    "status": "pass",
                    "missing_tetra_node_tags": [],
                    "all_gmsh_node_count": len(all_nodes),
                    "active_node_count": len(nodes),
                    "unused_gmsh_node_count": len(unused_node_tags),
                    "unused_gmsh_node_samples": unused_node_tags[:8],
                },
                "volume_element_type_counts": type_counts,
                "forbidden_element_type_counts": forbidden_counts,
                "core_tetra_count": len(tetra_elements),
                "inner_surface_entity_count": len(inner_tags),
                "root_symmetry_surface_count": len(symmetry_tags),
                "farfield_surface_count": len(farfield_tags),
                "mesh_path": str(output_dir / "core.msh"),
                "mesh_sizing": {
                    "core_mesh_size": float(core_mesh_size),
                    "farfield_mesh_size": float(farfield_mesh_size),
                    "boundary_point_sizing": boundary_point_report,
                    "gmsh_algorithm3d": core_algorithm3d,
                    "inner_boundary_representation": "triangulated_discrete",
                },
            },
        }
    finally:
        gmsh.finalize()


def _closed_wall_wrapper_dual_proxy(
    bl_volume: Mapping[str, Any],
    core: Mapping[str, Any],
) -> dict[str, Any]:
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
    compacted_volume, _node_compaction = _compact_volume_node_indices(
        {
            "nodes": merged_nodes,
            "elements": elements,
            "marker_faces": marker_faces,
        }
    )
    element_sources = [
        *[
            _phase3_volume_element_source(element_type)
            for element_type, _nodes in bl_volume["elements"]
        ],
        *(["tetra_core"] * len(core["tetra_elements"])),
    ]
    return _mixed_dual_subvolume_proxy_report(
        compacted_volume["nodes"],
        compacted_volume["elements"],
        element_sources=element_sources,
        marker_faces=compacted_volume["marker_faces"],
        min_ratio=MAX_ROUTE_DUAL_SUB_VOLUME_RATIO,
        top_count=20,
    )


def _partial_wing_transition_collar_core_inner_boundary_surface(
    collar_volume: Mapping[str, Any],
    *,
    cap_triangles: Sequence[tuple[tuple[int, int, int], str]],
) -> SurfaceMesh:
    faces: list[Face] = []
    for marker in ("bl_outer_interface", "transition_collar_interface"):
        for element_type, nodes in collar_volume["marker_faces"].get(marker, []):
            if int(element_type) == SU2_TRIANGLE:
                faces.append(Face(nodes=tuple(int(node) for node in nodes), marker=marker))
    for triangle, marker in cap_triangles:
        faces.append(Face(nodes=tuple(int(node) for node in triangle), marker=marker))
    return SurfaceMesh(
        vertices=[tuple(vertex) for vertex in collar_volume["nodes"]],
        faces=faces,
        metadata={"surface_role": "partial_wing_transition_collar_core_inner_boundary"},
    )


def _core_boundary_point_size_targets(
    inner_boundary: SurfaceMesh,
    *,
    point_tag_offset: int,
    mesh_size: float | None,
    markers: Sequence[str],
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    marker_names = [str(marker) for marker in markers]
    if mesh_size is None:
        return [], {"status": "disabled", "markers": marker_names}
    target_markers = set(marker_names)
    point_indices = sorted(
        {
            int(node)
            for face in inner_boundary.faces
            if str(face.marker) in target_markers
            for node in face.nodes
        }
    )
    point_tags = [int(point_tag_offset) + index for index in point_indices]
    return [(0, tag) for tag in point_tags], {
        "status": "enabled" if point_tags else "missing_points",
        "markers": marker_names,
        "mesh_size": float(mesh_size),
        "point_count": len(point_tags),
        "point_tag_samples": point_tags[:8],
    }


def _partial_wing_transition_collar_volume(
    prism_volume: Mapping[str, Any],
    *,
    collar_height_m: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if collar_height_m <= 0.0:
        raise ValueError("collar_height_m must be positive")
    nodes = [tuple(vertex) for vertex in prism_volume["nodes"]]
    elements = list(prism_volume["elements"])
    face_owners = _volume_face_owner_map(elements)
    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    converted_by_marker = {marker: 0 for marker in DIAGNOSTIC_FORCE_MARKERS}
    required_segments_by_marker = {marker: 0 for marker in DIAGNOSTIC_FORCE_MARKERS}
    required_segment_counts: list[int] = []
    single_base_edge_ratios: list[float] = []
    segmentation_plan_records: list[dict[str, Any]] = []
    source_edge_split_records: dict[tuple[str, tuple[int, int]], dict[str, Any]] = {}
    pyramid_signed_volumes: list[float] = []
    base_vertex_count = int(prism_volume.get("base_vertex_count") or 0)

    for marker, faces in _mapping(prism_volume.get("marker_faces")).items():
        for element_type, face_nodes in faces:
            nodes_tuple = tuple(int(node) for node in face_nodes)
            if marker in DIAGNOSTIC_FORCE_MARKERS and int(element_type) == SU2_QUAD:
                edge_lengths = [
                    length for length in _face_edge_lengths(nodes, nodes_tuple) if length > 0.0
                ]
                edge_ratio = max(edge_lengths) / min(edge_lengths)
                required_segments = max(
                    1,
                    math.ceil(edge_ratio / MAX_ROUTE_DUAL_HOTSPOT_INCIDENT_EDGE_RATIO),
                )
                planned_segment_base_edge_ratio = edge_ratio / required_segments
                single_base_edge_ratios.append(edge_ratio)
                required_segment_counts.append(required_segments)
                required_segments_by_marker[str(marker)] = (
                    required_segments_by_marker.get(str(marker), 0) + required_segments
                )
                segmentation_plan_records.append(
                    {
                        "marker": str(marker),
                        "face_nodes": [int(node) for node in nodes_tuple],
                        "single_pyramid_base_edge_ratio": edge_ratio,
                        "planned_segment_base_edge_ratio": (
                            planned_segment_base_edge_ratio
                        ),
                        "required_segments": required_segments,
                        "min_edge_length_m": min(edge_lengths),
                        "max_edge_length_m": max(edge_lengths),
                    }
                )
                source_edge = _source_edge_from_layered_quad(
                    nodes_tuple,
                    base_vertex_count=base_vertex_count,
                )
                if source_edge is not None:
                    source_key = (str(marker), source_edge)
                    source_record = source_edge_split_records.setdefault(
                        source_key,
                        {
                            "marker": str(marker),
                            "source_edge": [int(node) for node in source_edge],
                            "required_segments": 0,
                            "single_pyramid_base_edge_ratio": 0.0,
                            "planned_segment_base_edge_ratio": 0.0,
                            "min_edge_length_m": min(edge_lengths),
                            "max_edge_length_m": max(edge_lengths),
                        },
                    )
                    if edge_ratio > float(source_record["single_pyramid_base_edge_ratio"]):
                        source_record["single_pyramid_base_edge_ratio"] = edge_ratio
                        source_record["required_segments"] = required_segments
                        source_record["planned_segment_base_edge_ratio"] = (
                            planned_segment_base_edge_ratio
                        )
                        source_record["min_edge_length_m"] = min(edge_lengths)
                        source_record["max_edge_length_m"] = max(edge_lengths)
                owner = _single_face_owner(face_owners, nodes_tuple, SU2_PRISM)
                apex = _collar_apex_for_prism_face(
                    nodes,
                    nodes_tuple,
                    elements[int(owner["element_index"])][1],
                    collar_height_m=collar_height_m,
                )
                nodes.append(apex)
                pyramid = _oriented_pyramid_positive(nodes, nodes_tuple, len(nodes) - 1)
                elements.append((SU2_PYRAMID, pyramid))
                pyramid_signed_volumes.append(_su2_pyramid_signed_volume(nodes, pyramid))
                for side_face in _volume_element_faces(SU2_PYRAMID, pyramid)[1:]:
                    marker_faces.setdefault("transition_collar_interface", []).append(
                        (SU2_TRIANGLE, tuple(int(node) for node in side_face))
                    )
                converted_by_marker[str(marker)] = converted_by_marker.get(str(marker), 0) + 1
                continue
            marker_faces.setdefault(str(marker), []).append((int(element_type), nodes_tuple))

    force_wall_rim_marker_leak_count = sum(
        len(marker_faces.get(marker, [])) for marker in DIAGNOSTIC_FORCE_MARKERS
    )
    finite_pyramid_volumes = [
        value for value in pyramid_signed_volumes if math.isfinite(value)
    ]
    source_edge_records = list(source_edge_split_records.values())
    source_required_segments_by_marker = {marker: 0 for marker in DIAGNOSTIC_FORCE_MARKERS}
    for record in source_edge_records:
        marker = str(record["marker"])
        source_required_segments_by_marker[marker] = (
            source_required_segments_by_marker.get(marker, 0)
            + int(record["required_segments"])
        )

    report = {
        "converted_prism_rim_quads_by_marker": converted_by_marker,
        "converted_prism_rim_quad_count": sum(converted_by_marker.values()),
        "segmented_collar_requirement": {
            "threshold_max_edge_ratio": MAX_ROUTE_DUAL_HOTSPOT_INCIDENT_EDGE_RATIO,
            "required_rim_segments_by_marker": required_segments_by_marker,
            "total_required_rim_segments": sum(required_segment_counts),
            "max_required_segments_per_quad": (
                max(required_segment_counts) if required_segment_counts else 0
            ),
            "max_single_pyramid_base_edge_ratio": (
                max(single_base_edge_ratios) if single_base_edge_ratios else 0.0
            ),
            "max_planned_segment_base_edge_ratio": (
                max(
                    record["planned_segment_base_edge_ratio"]
                    for record in segmentation_plan_records
                )
                if segmentation_plan_records
                else 0.0
            ),
            "plan_record_count": len(segmentation_plan_records),
            "plan_samples": segmentation_plan_records[:8],
            "split_policy": "split_longest_prism_rim_edge_pair",
            "source_edge_split_requirement": {
                "source_edge_count": len(source_edge_records),
                "required_source_edge_segments_by_marker": (
                    source_required_segments_by_marker
                ),
                "total_required_source_edge_segments": sum(
                    int(record["required_segments"]) for record in source_edge_records
                ),
                "max_required_segments_per_source_edge": (
                    max(int(record["required_segments"]) for record in source_edge_records)
                    if source_edge_records
                    else 0
                ),
                "max_single_source_edge_base_ratio": (
                    max(
                        float(record["single_pyramid_base_edge_ratio"])
                        for record in source_edge_records
                    )
                    if source_edge_records
                    else 0.0
                ),
                "max_planned_source_edge_base_ratio": (
                    max(
                        float(record["planned_segment_base_edge_ratio"])
                        for record in source_edge_records
                    )
                    if source_edge_records
                    else 0.0
                ),
                "plan_samples": source_edge_records[:8],
            },
        },
        "interface_triangle_count": len(marker_faces.get("transition_collar_interface", [])),
        "force_wall_rim_marker_leak_count": force_wall_rim_marker_leak_count,
        "collar_height_m": float(collar_height_m),
        "pyramid_signed_volume": {
            "count": len(pyramid_signed_volumes),
            "min": min(finite_pyramid_volumes) if finite_pyramid_volumes else None,
            "max": max(finite_pyramid_volumes) if finite_pyramid_volumes else None,
            "non_positive_count": sum(
                1 for value in finite_pyramid_volumes if value <= 0.0
            ),
        },
    }
    return {
        "nodes": nodes,
        "elements": elements,
        "marker_faces": marker_faces,
    }, report


def _single_face_owner(
    face_owners: Mapping[tuple[int, ...], Sequence[Mapping[str, Any]]],
    face_nodes: Sequence[int],
    element_type: int,
) -> Mapping[str, Any]:
    owners = [
        owner
        for owner in face_owners.get(_face_key_nodes(face_nodes), [])
        if int(owner["element_type"]) == int(element_type)
    ]
    if len(owners) != 1:
        raise RuntimeError(
            f"expected one owner of type {element_type} for face {tuple(face_nodes)}, got {len(owners)}"
        )
    return owners[0]


def _source_edge_from_layered_quad(
    face_nodes: Sequence[int],
    *,
    base_vertex_count: int,
) -> tuple[int, int] | None:
    if base_vertex_count <= 0:
        return None
    source_nodes = sorted({int(node) % int(base_vertex_count) for node in face_nodes})
    if len(source_nodes) != 2:
        return None
    return (source_nodes[0], source_nodes[1])


def _collar_apex_for_prism_face(
    vertices: Sequence[tuple[float, float, float]],
    face_nodes: Sequence[int],
    owner_nodes: Sequence[int],
    *,
    collar_height_m: float,
) -> tuple[float, float, float]:
    face_points = [vertices[int(node)] for node in face_nodes]
    face_centroid = (
        sum(point[0] for point in face_points) / len(face_points),
        sum(point[1] for point in face_points) / len(face_points),
        sum(point[2] for point in face_points) / len(face_points),
    )
    owner_points = [vertices[int(node)] for node in owner_nodes]
    owner_centroid = (
        sum(point[0] for point in owner_points) / len(owner_points),
        sum(point[1] for point in owner_points) / len(owner_points),
        sum(point[2] for point in owner_points) / len(owner_points),
    )
    area_vector = _face_area_vector(vertices, tuple(int(node) for node in face_nodes))
    area_norm = math.sqrt(
        area_vector[0] ** 2 + area_vector[1] ** 2 + area_vector[2] ** 2
    )
    if area_norm <= 1.0e-14:
        direction = _vector_between(owner_centroid, face_centroid)
        direction_norm = math.sqrt(_dot(direction, direction))
        if direction_norm <= 1.0e-14:
            direction = (0.0, 0.0, 1.0)
            direction_norm = 1.0
        normal = (
            direction[0] / direction_norm,
            direction[1] / direction_norm,
            direction[2] / direction_norm,
        )
    else:
        normal = (
            area_vector[0] / area_norm,
            area_vector[1] / area_norm,
            area_vector[2] / area_norm,
        )
    outward_hint = _vector_between(owner_centroid, face_centroid)
    if _dot(normal, outward_hint) < 0.0:
        normal = (-normal[0], -normal[1], -normal[2])
    return (
        face_centroid[0] + collar_height_m * normal[0],
        face_centroid[1] + collar_height_m * normal[1],
        face_centroid[2] + collar_height_m * normal[2],
    )


def _minimal_transition_unit_volume() -> dict[str, Any]:
    nodes: list[tuple[float, float, float]] = []
    elements: list[tuple[int, tuple[int, ...]]] = []
    element_roles: list[dict[str, str]] = []
    marker_overrides: dict[tuple[int, ...], str] = {}

    def add_node(coord: tuple[float, float, float]) -> int:
        nodes.append(coord)
        return len(nodes) - 1

    def add_element(element_type: int, element_nodes: Sequence[int], **role: str) -> int:
        elements.append((int(element_type), tuple(int(node) for node in element_nodes)))
        element_roles.append(dict(role))
        return len(elements) - 1

    def add_transition_patch(
        *,
        x0: float,
        wall_marker: str,
        outer_core_marker: str,
    ) -> None:
        a = add_node((x0, 0.0, 0.0))
        b = add_node((x0 + 1.0, 0.0, 0.0))
        c = add_node((x0, 1.0, 0.0))
        d = add_node((x0, 0.0, 0.10))
        e = add_node((x0 + 1.0, 0.0, 0.10))
        f = add_node((x0, 1.0, 0.10))
        prism = (d, e, f, a, b, c)
        add_element(SU2_PRISM, prism, role="boundary_layer_prism")
        prism_faces = _volume_element_faces(SU2_PRISM, prism)
        marker_overrides[_face_key_nodes(prism_faces[1])] = wall_marker
        marker_overrides[_face_key_nodes(prism_faces[3])] = "root_symmetry"

        outer_node = add_node((x0 + 0.30, 0.35, 0.52))
        add_element(
            SU2_TETRAHEDRON,
            _oriented_tetra_for_shared_face(nodes, prism_faces[0], outer_node),
            role="outer_core_tetra",
            boundary_marker=outer_core_marker,
        )

        collar_specs = [
            {
                "base_face": prism_faces[2],
                "apex": (x0 + 0.50, -0.22, 0.05),
                "role": "te_transition_pyramid",
                "boundary_marker": "te_wall",
            },
            {
                "base_face": prism_faces[4],
                "apex": (x0 - 0.22, 0.50, 0.05),
                "role": "tip_transition_pyramid",
                "boundary_marker": "tip_wall",
            },
        ]
        for collar_index, spec in enumerate(collar_specs):
            apex = add_node(spec["apex"])
            pyramid = _oriented_pyramid_positive(nodes, spec["base_face"], apex)
            add_element(SU2_PYRAMID, pyramid, role=str(spec["role"]))
            for side_index, side_face in enumerate(
                _volume_element_faces(SU2_PYRAMID, pyramid)[1:]
            ):
                extension = add_node(
                    _tet_extension_point(
                        nodes,
                        side_face,
                        magnitude=0.24 + 0.03 * side_index + 0.02 * collar_index,
                    )
                )
                add_element(
                    SU2_TETRAHEDRON,
                    _oriented_tetra_for_shared_face(nodes, side_face, extension),
                    role="transition_core_tetra",
                    boundary_marker=str(spec["boundary_marker"]),
                )

    add_transition_patch(x0=0.0, wall_marker="wing_upper", outer_core_marker="farfield")
    add_transition_patch(x0=2.2, wall_marker="wing_lower", outer_core_marker="closure_wall")

    volume: dict[str, Any] = {
        "nodes": nodes,
        "elements": elements,
        "element_roles": element_roles,
        "marker_overrides": marker_overrides,
    }
    volume["marker_faces"] = _minimal_transition_marker_faces(volume)
    return volume


def _segmented_collar_scale_transition_unit_volume() -> dict[str, Any]:
    segment_count = 16
    segment_length = 0.03
    strip_width = 0.03
    layer_height = 6.0e-5
    collar_offset = 0.015
    core_extension = 0.03
    nodes: list[tuple[float, float, float]] = []
    elements: list[tuple[int, tuple[int, ...]]] = []
    element_roles: list[dict[str, str]] = []
    rim_quad_edge_ratios: list[float] = []

    def add_node(coord: tuple[float, float, float]) -> int:
        nodes.append(coord)
        return len(nodes) - 1

    node_cache: dict[tuple[int, int, int], int] = {}

    def grid_node(ix: int, iy: int, iz: int) -> int:
        key = (int(ix), int(iy), int(iz))
        existing = node_cache.get(key)
        if existing is not None:
            return existing
        node_cache[key] = add_node(
            (
                ix * segment_length,
                iy * strip_width,
                iz * layer_height,
            )
        )
        return node_cache[key]

    def add_element(element_type: int, element_nodes: Sequence[int], **role: str) -> int:
        elements.append((int(element_type), tuple(int(node) for node in element_nodes)))
        element_roles.append(dict(role))
        return len(elements) - 1

    def add_top_core_tet(shared_face: Sequence[int]) -> None:
        point = _tet_extension_point(nodes, shared_face, magnitude=core_extension)
        extension = add_node(point)
        add_element(
            SU2_TETRAHEDRON,
            _oriented_tetra_for_shared_face(nodes, shared_face, extension),
            role="segmented_outer_core_tetra",
            boundary_marker="farfield",
        )

    def add_segmented_pyramid_collar(base_face: Sequence[int]) -> None:
        base_points = [nodes[int(node)] for node in base_face]
        centroid = _centroid_tuple(base_points)
        apex = add_node((centroid[0], centroid[1] - collar_offset, centroid[2]))
        pyramid = _oriented_pyramid_positive(nodes, base_face, apex)
        add_element(SU2_PYRAMID, pyramid, role="segmented_transition_pyramid")
        edge_lengths = _face_edge_lengths(nodes, base_face)
        positive_edges = [length for length in edge_lengths if length > 0.0]
        rim_quad_edge_ratios.append(max(positive_edges) / min(positive_edges))
        for side_face in _volume_element_faces(SU2_PYRAMID, pyramid)[1:]:
            extension = add_node(
                _tet_extension_point(nodes, side_face, magnitude=core_extension)
            )
            add_element(
                SU2_TETRAHEDRON,
                _oriented_tetra_for_shared_face(nodes, side_face, extension),
                role="segmented_transition_core_tetra",
                boundary_marker="te_wall",
            )

    for index in range(segment_count):
        b00 = grid_node(index, 0, 0)
        b10 = grid_node(index + 1, 0, 0)
        b01 = grid_node(index, 1, 0)
        b11 = grid_node(index + 1, 1, 0)
        t00 = grid_node(index, 0, 1)
        t10 = grid_node(index + 1, 0, 1)
        t01 = grid_node(index, 1, 1)
        t11 = grid_node(index + 1, 1, 1)

        first_prism = (t00, t10, t01, b00, b10, b01)
        second_prism = (t10, t11, t01, b10, b11, b01)
        add_element(SU2_PRISM, first_prism, role="segmented_boundary_layer_prism")
        add_element(SU2_PRISM, second_prism, role="segmented_boundary_layer_prism")

        first_faces = _volume_element_faces(SU2_PRISM, first_prism)
        second_faces = _volume_element_faces(SU2_PRISM, second_prism)
        add_top_core_tet(first_faces[0])
        add_top_core_tet(second_faces[0])

        rim_face = _find_face_with_nodes(first_faces, (b00, b10, t00, t10))
        add_segmented_pyramid_collar(rim_face)

    volume: dict[str, Any] = {
        "nodes": nodes,
        "elements": elements,
        "element_roles": element_roles,
        "segmented_collar": {
            "segment_count": segment_count,
            "segment_length_m": segment_length,
            "layer_height_m": layer_height,
            "rim_quad_max_edge_ratio": max(rim_quad_edge_ratios),
            "rim_quad_edge_ratio_threshold": (
                MAX_ROUTE_DUAL_HOTSPOT_INCIDENT_EDGE_RATIO
            ),
        },
    }
    volume["marker_faces"] = _segmented_transition_marker_faces(volume)
    return volume


def _structured_transition_patch_unit_volume() -> dict[str, Any]:
    segment_count = 4
    segment_length = 0.03
    strip_width = 0.03
    layer_height = 6.0e-5
    collar_offset = 0.015
    transition_row_heights = (0.03, 0.09)
    core_extension = 0.12
    nodes: list[tuple[float, float, float]] = []
    elements: list[tuple[int, tuple[int, ...]]] = []
    element_roles: list[dict[str, str]] = []
    rim_quad_edge_ratios: list[float] = []

    def add_node(coord: tuple[float, float, float]) -> int:
        nodes.append(coord)
        return len(nodes) - 1

    node_cache: dict[tuple[int, int, int], int] = {}

    def grid_node(ix: int, iy: int, iz: int) -> int:
        key = (int(ix), int(iy), int(iz))
        existing = node_cache.get(key)
        if existing is not None:
            return existing
        node_cache[key] = add_node(
            (
                ix * segment_length,
                iy * strip_width,
                iz * layer_height,
            )
        )
        return node_cache[key]

    def add_element(element_type: int, element_nodes: Sequence[int], **role: str) -> int:
        elements.append((int(element_type), tuple(int(node) for node in element_nodes)))
        element_roles.append(dict(role))
        return len(elements) - 1

    def side_face_outward_direction(
        pyramid_nodes: Sequence[int],
        side_face: Sequence[int],
    ) -> tuple[float, float, float]:
        pyramid_centroid = _centroid_tuple([nodes[int(node)] for node in pyramid_nodes])
        face_centroid = _centroid_tuple([nodes[int(node)] for node in side_face])
        direction = _vector_between(pyramid_centroid, face_centroid)
        length = _distance3(direction, (0.0, 0.0, 0.0))
        if length <= 1.0e-14:
            normal = _triangle_unit_normal(
                nodes[int(side_face[0])],
                nodes[int(side_face[1])],
                nodes[int(side_face[2])],
            )
            length = _distance3(normal, (0.0, 0.0, 0.0))
            if length <= 1.0e-14:
                return (0.0, -1.0, 0.0)
            return (normal[0] / length, normal[1] / length, normal[2] / length)
        return (direction[0] / length, direction[1] / length, direction[2] / length)

    def offset_triangle(
        triangle: Sequence[int],
        direction: tuple[float, float, float],
        distance: float,
    ) -> tuple[int, int, int]:
        return tuple(
            add_node(
                (
                    nodes[int(node)][0] + distance * direction[0],
                    nodes[int(node)][1] + distance * direction[1],
                    nodes[int(node)][2] + distance * direction[2],
                )
            )
            for node in triangle
        )

    def add_structured_rows(
        *,
        pyramid_nodes: Sequence[int],
        side_face: Sequence[int],
        side_index: int,
    ) -> None:
        direction = side_face_outward_direction(pyramid_nodes, side_face)
        inner = tuple(int(node) for node in side_face)
        cumulative = 0.0
        for row_index, height in enumerate(transition_row_heights):
            cumulative += float(height)
            outer = offset_triangle(side_face, direction, cumulative)
            prism = _oriented_prism_positive(nodes, inner, outer)
            add_element(
                SU2_PRISM,
                prism,
                role="structured_transition_prism",
                source="structured_transition_prism",
                boundary_marker="transition_patch_boundary",
            )
            inner = outer
        extension = add_node(
            _offset_point(
                _centroid_tuple([nodes[int(node)] for node in inner]),
                direction,
                core_extension + 0.01 * side_index,
            )
        )
        add_element(
            SU2_TETRAHEDRON,
            _oriented_tetra_for_shared_face(nodes, inner, extension),
            role="structured_outer_core_tetra",
            source="tetra_core",
            boundary_marker="farfield",
        )

    for index in range(segment_count):
        b00 = grid_node(index, 0, 0)
        b10 = grid_node(index + 1, 0, 0)
        b01 = grid_node(index, 1, 0)
        b11 = grid_node(index + 1, 1, 0)
        t00 = grid_node(index, 0, 1)
        t10 = grid_node(index + 1, 0, 1)
        t01 = grid_node(index, 1, 1)
        t11 = grid_node(index + 1, 1, 1)

        first_prism = (t00, t10, t01, b00, b10, b01)
        second_prism = (t10, t11, t01, b10, b11, b01)
        add_element(
            SU2_PRISM,
            first_prism,
            role="structured_boundary_layer_prism",
            source="boundary_layer_prism",
        )
        add_element(
            SU2_PRISM,
            second_prism,
            role="structured_boundary_layer_prism",
            source="boundary_layer_prism",
        )

        first_faces = _volume_element_faces(SU2_PRISM, first_prism)
        second_faces = _volume_element_faces(SU2_PRISM, second_prism)
        for face_index, top_face in enumerate((first_faces[0], second_faces[0])):
            extension = add_node(
                _tet_extension_point(nodes, top_face, magnitude=segment_length)
            )
            add_element(
                SU2_TETRAHEDRON,
                _oriented_tetra_for_shared_face(nodes, top_face, extension),
                role="structured_bl_outer_core_tetra",
                source="tetra_core",
                boundary_marker="farfield",
                face_index=str(face_index),
            )

        rim_face = _find_face_with_nodes(first_faces, (b00, b10, t00, t10))
        rim_edges = [length for length in _face_edge_lengths(nodes, rim_face) if length > 0.0]
        rim_quad_edge_ratios.append(max(rim_edges) / min(rim_edges))
        base_points = [nodes[int(node)] for node in rim_face]
        centroid = _centroid_tuple(base_points)
        apex = add_node((centroid[0], centroid[1] - collar_offset, centroid[2]))
        pyramid = _oriented_pyramid_positive(nodes, rim_face, apex)
        add_element(
            SU2_PYRAMID,
            pyramid,
            role="structured_transition_pyramid",
            source="transition_collar_pyramid",
        )
        for side_index, side_face in enumerate(
            _volume_element_faces(SU2_PYRAMID, pyramid)[1:]
        ):
            add_structured_rows(
                pyramid_nodes=pyramid,
                side_face=side_face,
                side_index=side_index,
            )

    volume: dict[str, Any] = {
        "nodes": nodes,
        "elements": elements,
        "element_roles": element_roles,
        "structured_transition": {
            "segment_count": segment_count,
            "row_count": len(transition_row_heights),
            "row_heights_m": list(transition_row_heights),
            "first_row_height_m": transition_row_heights[0],
            "max_row_growth_ratio": max(
                transition_row_heights[index + 1] / transition_row_heights[index]
                for index in range(len(transition_row_heights) - 1)
            ),
            "core_extension_m": core_extension,
            "rim_quad_max_edge_ratio": max(rim_quad_edge_ratios),
        },
    }
    volume["marker_faces"] = _structured_transition_marker_faces(volume)
    return volume


def _find_face_with_nodes(
    faces: Sequence[Sequence[int]],
    expected_nodes: Sequence[int],
) -> tuple[int, ...]:
    expected = _face_key_nodes(expected_nodes)
    for face in faces:
        if _face_key_nodes(face) == expected:
            return tuple(int(node) for node in face)
    raise RuntimeError(f"could not find face with nodes {expected}")


def _minimal_transition_marker_faces(
    volume: Mapping[str, Any],
) -> dict[str, list[tuple[int, tuple[int, ...]]]]:
    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    face_owners = _volume_face_owner_map(volume["elements"])
    marker_overrides = {
        tuple(int(node) for node in key): str(marker)
        for key, marker in _mapping(volume.get("marker_overrides")).items()
    }
    roles = list(volume.get("element_roles") or [])
    for key, owners in face_owners.items():
        if len(owners) != 1:
            continue
        owner = owners[0]
        marker = marker_overrides.get(key)
        if marker is None and int(owner["element_type"]) == SU2_TETRAHEDRON:
            marker = str(_mapping(roles[int(owner["element_index"])]).get("boundary_marker") or "farfield")
        if marker is None:
            continue
        face_nodes = tuple(int(node) for node in owner["face_nodes"])
        surface_type = SU2_QUAD if len(face_nodes) == 4 else SU2_TRIANGLE
        marker_faces.setdefault(marker, []).append((surface_type, face_nodes))
    return marker_faces


def _segmented_transition_marker_faces(
    volume: Mapping[str, Any],
) -> dict[str, list[tuple[int, tuple[int, ...]]]]:
    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    vertices = [tuple(vertex) for vertex in volume["nodes"]]
    face_owners = _volume_face_owner_map(volume["elements"])
    roles = list(volume.get("element_roles") or [])
    for _key, owners in face_owners.items():
        if len(owners) != 1:
            continue
        owner = owners[0]
        element_type = int(owner["element_type"])
        face_nodes = tuple(int(node) for node in owner["face_nodes"])
        marker: str | None = None
        if element_type == SU2_PRISM:
            if len(face_nodes) == 3 and _face_average_z(vertices, face_nodes) < 0.5e-5:
                marker = "wing_upper"
            elif len(face_nodes) == 4:
                marker = "root_symmetry"
            else:
                marker = "farfield"
        elif element_type == SU2_TETRAHEDRON:
            marker = str(
                _mapping(roles[int(owner["element_index"])]).get("boundary_marker")
                or "farfield"
            )
        elif element_type == SU2_PYRAMID:
            marker = "te_wall"
        if marker is None:
            continue
        surface_type = SU2_QUAD if len(face_nodes) == 4 else SU2_TRIANGLE
        marker_faces.setdefault(marker, []).append((surface_type, face_nodes))
    return marker_faces


def _structured_transition_marker_faces(
    volume: Mapping[str, Any],
) -> dict[str, list[tuple[int, tuple[int, ...]]]]:
    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    vertices = [tuple(vertex) for vertex in volume["nodes"]]
    face_owners = _volume_face_owner_map(volume["elements"])
    roles = list(volume.get("element_roles") or [])
    for _key, owners in face_owners.items():
        if len(owners) != 1:
            continue
        owner = owners[0]
        element_type = int(owner["element_type"])
        face_nodes = tuple(int(node) for node in owner["face_nodes"])
        role = _mapping(roles[int(owner["element_index"])])
        marker: str | None = None
        if element_type == SU2_PRISM:
            if role.get("role") == "structured_boundary_layer_prism":
                if len(face_nodes) == 3 and _face_average_z(vertices, face_nodes) < 0.5e-5:
                    marker = "wing_upper"
                elif len(face_nodes) == 4 and _face_average_y(vertices, face_nodes) <= 1.0e-9:
                    marker = "root_symmetry"
                else:
                    marker = "farfield"
            else:
                marker = str(role.get("boundary_marker") or "transition_patch_boundary")
        elif element_type == SU2_TETRAHEDRON:
            marker = str(role.get("boundary_marker") or "farfield")
        elif element_type == SU2_PYRAMID:
            marker = str(role.get("boundary_marker") or "te_wall")
        if marker is None:
            continue
        surface_type = SU2_QUAD if len(face_nodes) == 4 else SU2_TRIANGLE
        marker_faces.setdefault(marker, []).append((surface_type, face_nodes))
    return marker_faces


def _face_average_z(
    vertices: Sequence[tuple[float, float, float]],
    face_nodes: Sequence[int],
) -> float:
    return sum(vertices[int(node)][2] for node in face_nodes) / len(face_nodes)


def _face_average_y(
    vertices: Sequence[tuple[float, float, float]],
    face_nodes: Sequence[int],
) -> float:
    return sum(abs(vertices[int(node)][1]) for node in face_nodes) / len(face_nodes)


def _volume_face_owner_map(
    elements: Sequence[tuple[int, Sequence[int]]],
) -> dict[tuple[int, ...], list[dict[str, Any]]]:
    face_owners: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    for element_index, (element_type, nodes) in enumerate(elements):
        for face_nodes in _volume_element_faces(int(element_type), tuple(int(node) for node in nodes)):
            key = _face_key_nodes(face_nodes)
            face_owners.setdefault(key, []).append(
                {
                    "element_index": int(element_index),
                    "element_type": int(element_type),
                    "face_nodes": tuple(int(node) for node in face_nodes),
                }
            )
    return face_owners


def _transition_topology_report(volume: Mapping[str, Any]) -> dict[str, Any]:
    face_owners = _volume_face_owner_map(volume["elements"])
    marker_key_counts: dict[tuple[int, ...], int] = {}
    marker_key_to_marker: dict[tuple[int, ...], str] = {}
    for marker, faces in _mapping(volume.get("marker_faces")).items():
        for _element_type, nodes in faces:
            key = _face_key_nodes(nodes)
            marker_key_counts[key] = marker_key_counts.get(key, 0) + 1
            marker_key_to_marker[key] = str(marker)

    boundary_keys = {
        key for key, owners in face_owners.items() if len(owners) == 1
    }
    marker_keys = set(marker_key_counts)
    prism_quad_keys = {
        key
        for key, owners in face_owners.items()
        for owner in owners
        if int(owner["element_type"]) == SU2_PRISM and len(owner["face_nodes"]) == 4
    }
    tet_face_keys = {
        key
        for key, owners in face_owners.items()
        for owner in owners
        if int(owner["element_type"]) == SU2_TETRAHEDRON
    }

    prism_quad_to_pyramid = 0
    pyramid_triangle_to_tet = 0
    tet_to_prism_triangle = 0
    for owners in face_owners.values():
        if len(owners) != 2:
            continue
        owner_types = sorted(int(owner["element_type"]) for owner in owners)
        node_count = len(owners[0]["face_nodes"])
        if node_count == 4 and owner_types == sorted([SU2_PRISM, SU2_PYRAMID]):
            prism_quad_to_pyramid += 1
        if node_count == 3 and owner_types == sorted([SU2_PYRAMID, SU2_TETRAHEDRON]):
            pyramid_triangle_to_tet += 1
        if node_count == 3 and owner_types == sorted([SU2_PRISM, SU2_TETRAHEDRON]):
            tet_to_prism_triangle += 1

    tet_to_prism_quad_contact = 0
    for tet_key in tet_face_keys:
        tet_nodes = set(tet_key)
        for prism_quad_key in prism_quad_keys:
            if len(prism_quad_key) == 4 and tet_nodes.issubset(set(prism_quad_key)):
                tet_to_prism_quad_contact += 1

    non_root_exposed_prism_quad_count = 0
    pyramid_boundary_face_count = 0
    for key in boundary_keys:
        owner = face_owners[key][0]
        if int(owner["element_type"]) == SU2_PRISM and len(owner["face_nodes"]) == 4:
            if marker_key_to_marker.get(key) != "root_symmetry":
                non_root_exposed_prism_quad_count += 1
        if int(owner["element_type"]) == SU2_PYRAMID:
            pyramid_boundary_face_count += 1

    return {
        "boundary_face_count": len(boundary_keys),
        "boundary_faces_unmarked": len(boundary_keys - marker_keys),
        "orphan_marker_faces": len(marker_keys - boundary_keys),
        "duplicate_marker_faces": sum(
            count - 1 for count in marker_key_counts.values() if count > 1
        ),
        "internal_face_count": sum(
            1 for owners in face_owners.values() if len(owners) == 2
        ),
        "nonmanifold_face_count": sum(
            1 for owners in face_owners.values() if len(owners) > 2
        ),
        "prism_quad_to_pyramid_base_contact": prism_quad_to_pyramid,
        "pyramid_triangle_to_tet_contact": pyramid_triangle_to_tet,
        "tet_to_prism_triangle_contact": tet_to_prism_triangle,
        "tet_to_prism_quad_contact": tet_to_prism_quad_contact,
        "non_root_exposed_prism_quad_count": non_root_exposed_prism_quad_count,
        "pyramid_boundary_face_count": pyramid_boundary_face_count,
    }


def _transition_element_quality(volume: Mapping[str, Any]) -> dict[str, Any]:
    vertices = [tuple(vertex) for vertex in volume["nodes"]]
    by_type: dict[str, list[float]] = {
        str(SU2_PRISM): [],
        str(SU2_PYRAMID): [],
        str(SU2_TETRAHEDRON): [],
    }
    for element_type, nodes in volume["elements"]:
        if int(element_type) == SU2_PRISM:
            by_type[str(SU2_PRISM)].append(_su2_prism_signed_volume(vertices, nodes))
        elif int(element_type) == SU2_PYRAMID:
            by_type[str(SU2_PYRAMID)].append(_su2_pyramid_signed_volume(vertices, nodes))
        elif int(element_type) == SU2_TETRAHEDRON:
            n = tuple(int(node) for node in nodes)
            by_type[str(SU2_TETRAHEDRON)].append(
                _tet_signed_volume(vertices[n[0]], vertices[n[1]], vertices[n[2]], vertices[n[3]])
            )
    return {
        key: {
            "count": len(values),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "non_positive_count": sum(1 for value in values if value <= 0.0),
        }
        for key, values in by_type.items()
    }


def _transition_element_quality_gate(quality: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    for element_type in (str(SU2_PRISM), str(SU2_PYRAMID), str(SU2_TETRAHEDRON)):
        metrics = _mapping(quality.get(element_type))
        if int(metrics.get("count") or 0) <= 0:
            blockers.append(f"transition_unit_element_type_{element_type}_missing")
        if int(metrics.get("non_positive_count") or 0) > 0:
            blockers.append(f"transition_unit_element_type_{element_type}_non_positive_volume")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": sorted(blockers),
    }


def _mixed_dual_subvolume_proxy_report(
    vertices: Sequence[tuple[float, float, float]],
    elements: Sequence[tuple[int, Sequence[int]]],
    *,
    element_sources: Sequence[str],
    marker_faces: Mapping[str, Sequence[tuple[int, Sequence[int]]]],
    min_ratio: float,
    top_count: int,
) -> dict[str, Any]:
    """Mirror SU2's vertex CV sub-volume ratio closely enough for blockers.

    SU2 computes the reported CV Sub-Volume Ratio from the min/max sub-volumes
    attached to a vertex dual control volume.  This proxy samples every
    element face into vertex-edge-face-centroid-cell-centroid tetrahedra for
    prisms, pyramids, and tetrahedra, which is enough to localize the current
    collar/core-interface pathology before running the solver.
    """

    if len(element_sources) != len(elements):
        raise ValueError("element_sources must match elements length")
    min_records: list[dict[str, Any] | None] = [None] * len(vertices)
    max_records: list[dict[str, Any] | None] = [None] * len(vertices)
    positive_subvolume_count = 0
    non_positive_subvolume_count = 0
    unsupported_element_count = 0
    supported_types = {SU2_PRISM, SU2_PYRAMID, SU2_TETRAHEDRON}
    element_geometries = _element_geometry_records(vertices, elements, element_sources)

    for element_index, ((element_type, element_nodes), source) in enumerate(
        zip(elements, element_sources)
    ):
        element_type = int(element_type)
        if element_type not in supported_types:
            unsupported_element_count += 1
            continue
        nodes = tuple(int(node) for node in element_nodes)
        element_centroid = _centroid_tuple([vertices[node] for node in nodes])
        for face_nodes in _volume_element_faces(element_type, nodes):
            face = tuple(int(node) for node in face_nodes)
            face_centroid = _centroid_tuple([vertices[node] for node in face])
            for edge_offset, point_index in enumerate(face):
                next_point_index = face[(edge_offset + 1) % len(face)]
                edge_midpoint = _centroid_tuple(
                    [vertices[int(point_index)], vertices[int(next_point_index)]]
                )
                subvolume = abs(
                    _tet_signed_volume(
                        vertices[int(point_index)],
                        edge_midpoint,
                        face_centroid,
                        element_centroid,
                    )
                )
                if subvolume <= 0.0 or not math.isfinite(subvolume):
                    non_positive_subvolume_count += 1
                    continue
                positive_subvolume_count += 1
                record = {
                    "subvolume_m3": float(subvolume),
                    "point_index": int(point_index),
                    "element_index": int(element_index),
                    "element_type": int(element_type),
                    "source": str(source),
                    "element_geometry": dict(element_geometries[int(element_index)]),
                    "element_nodes": [int(node) for node in nodes],
                    "face_nodes": [int(node) for node in face],
                    "edge_nodes": [int(point_index), int(next_point_index)],
                }
                current_min = min_records[int(point_index)]
                if (
                    current_min is None
                    or subvolume < float(current_min["subvolume_m3"])
                ):
                    min_records[int(point_index)] = record
                current_max = max_records[int(point_index)]
                if (
                    current_max is None
                    or subvolume > float(current_max["subvolume_m3"])
                ):
                    max_records[int(point_index)] = record

    point_markers = _point_markers_from_marker_faces(marker_faces)
    incident_source_counts = _incident_source_counts_by_point(elements, element_sources)
    records: list[dict[str, Any]] = []
    for point_index, (min_record, max_record) in enumerate(
        zip(min_records, max_records)
    ):
        if min_record is None or max_record is None:
            continue
        min_volume = float(min_record["subvolume_m3"])
        if min_volume <= 0.0:
            continue
        max_volume = float(max_record["subvolume_m3"])
        ratio = max_volume / min_volume
        if ratio < min_ratio:
            continue
        source_pair = "|".join(
            sorted((str(min_record["source"]), str(max_record["source"])))
        )
        records.append(
            {
                "point_index": int(point_index),
                "point": _point_payload(vertices[point_index]),
                "cv_sub_volume_ratio": float(ratio),
                "source_pair": source_pair,
                "point_markers": sorted(point_markers.get(point_index, set())),
                "incident_element_source_counts": dict(
                    sorted(incident_source_counts.get(point_index, {}).items())
                ),
                "incident_element_geometry_by_source": (
                    _incident_element_geometry_by_source(
                        int(point_index),
                        elements,
                        element_geometries,
                    )
                ),
                "min_subvolume": dict(min_record),
                "max_subvolume": dict(max_record),
            }
        )

    records.sort(
        key=lambda record: float(record["cv_sub_volume_ratio"]),
        reverse=True,
    )
    worst = records[0] if records else None
    max_ratio = 0.0 if worst is None else float(worst["cv_sub_volume_ratio"])
    max_incident_edge_ratio = _max_incident_edge_length_ratio(records)
    blockers = []
    if max_ratio > MAX_ROUTE_DUAL_SUB_VOLUME_RATIO:
        blockers.append("mixed_dual_subvolume_ratio_exceeds_route_gate")
    if max_incident_edge_ratio > MAX_ROUTE_DUAL_HOTSPOT_INCIDENT_EDGE_RATIO:
        blockers.append("mixed_dual_hotspot_incident_edge_ratio_exceeds_route_gate")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "thresholds": {
            "max_cv_sub_volume_ratio": MAX_ROUTE_DUAL_SUB_VOLUME_RATIO,
            "record_min_ratio": float(min_ratio),
            "max_hotspot_incident_edge_length_ratio": (
                MAX_ROUTE_DUAL_HOTSPOT_INCIDENT_EDGE_RATIO
            ),
        },
        "positive_subvolume_count": int(positive_subvolume_count),
        "non_positive_subvolume_count": int(non_positive_subvolume_count),
        "unsupported_element_count": int(unsupported_element_count),
        "record_count": len(records),
        "max_cv_sub_volume_ratio": max_ratio,
        "max_incident_edge_length_ratio": max_incident_edge_ratio,
        "worst_point_index": None if worst is None else int(worst["point_index"]),
        "worst_point": None if worst is None else dict(worst["point"]),
        "worst_source_pair": None if worst is None else str(worst["source_pair"]),
        "top_hotspots": [dict(record) for record in records[: max(0, int(top_count))]],
    }


def _max_incident_edge_length_ratio(records: Sequence[Mapping[str, Any]]) -> float:
    ratios: list[float] = []
    for record in records:
        geometry_by_source = _mapping(record.get("incident_element_geometry_by_source"))
        for source_metrics in geometry_by_source.values():
            ratio = _float_or_none(_mapping(source_metrics).get("max_edge_length_ratio"))
            if ratio is not None:
                ratios.append(ratio)
    return max(ratios) if ratios else 0.0


def _element_geometry_records(
    vertices: Sequence[tuple[float, float, float]],
    elements: Sequence[tuple[int, Sequence[int]]],
    element_sources: Sequence[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for element_index, ((element_type, nodes), source) in enumerate(
        zip(elements, element_sources)
    ):
        nodes_tuple = tuple(int(node) for node in nodes)
        edge_lengths = _volume_element_edge_lengths(vertices, int(element_type), nodes_tuple)
        positive_edge_lengths = [
            float(length)
            for length in edge_lengths
            if math.isfinite(float(length)) and float(length) > 0.0
        ]
        min_edge = min(positive_edge_lengths) if positive_edge_lengths else None
        max_edge = max(positive_edge_lengths) if positive_edge_lengths else None
        records.append(
            {
                "element_index": int(element_index),
                "element_type": int(element_type),
                "source": str(source),
                "abs_volume_m3": _volume_element_abs_volume(
                    vertices,
                    int(element_type),
                    nodes_tuple,
                ),
                "min_edge_length_m": min_edge,
                "max_edge_length_m": max_edge,
                "max_edge_length_ratio": (
                    None if min_edge in (None, 0.0) or max_edge is None else max_edge / min_edge
                ),
            }
        )
    return records


def _volume_element_edge_lengths(
    vertices: Sequence[tuple[float, float, float]],
    element_type: int,
    nodes: Sequence[int],
) -> list[float]:
    edge_keys: set[tuple[int, int]] = set()
    for face in _volume_element_faces(int(element_type), tuple(int(node) for node in nodes)):
        face_nodes = tuple(int(node) for node in face)
        for index, node in enumerate(face_nodes):
            edge_keys.add(tuple(sorted((int(node), int(face_nodes[(index + 1) % len(face_nodes)])))))
    return [
        _distance3(vertices[first], vertices[second])
        for first, second in sorted(edge_keys)
    ]


def _volume_element_abs_volume(
    vertices: Sequence[tuple[float, float, float]],
    element_type: int,
    nodes: Sequence[int],
) -> float | None:
    element_type = int(element_type)
    if element_type == SU2_TETRAHEDRON:
        n = tuple(int(node) for node in nodes)
        return abs(_tet_signed_volume(vertices[n[0]], vertices[n[1]], vertices[n[2]], vertices[n[3]]))
    if element_type == SU2_PRISM:
        return abs(_su2_prism_signed_volume(vertices, nodes))
    if element_type == SU2_PYRAMID:
        return abs(_su2_pyramid_signed_volume(vertices, nodes))
    return None


def _incident_element_geometry_by_source(
    point_index: int,
    elements: Sequence[tuple[int, Sequence[int]]],
    element_geometries: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for element, geometry in zip(elements, element_geometries):
        _element_type, nodes = element
        if int(point_index) not in {int(node) for node in nodes}:
            continue
        source = str(geometry["source"])
        grouped.setdefault(source, []).append(geometry)

    return {
        source: _summarize_element_geometries(records)
        for source, records in sorted(grouped.items())
    }


def _summarize_element_geometries(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    volumes = [
        float(record["abs_volume_m3"])
        for record in records
        if _float_or_none(record.get("abs_volume_m3")) is not None
    ]
    min_edges = [
        float(record["min_edge_length_m"])
        for record in records
        if _float_or_none(record.get("min_edge_length_m")) is not None
    ]
    max_edges = [
        float(record["max_edge_length_m"])
        for record in records
        if _float_or_none(record.get("max_edge_length_m")) is not None
    ]
    edge_ratios = [
        float(record["max_edge_length_ratio"])
        for record in records
        if _float_or_none(record.get("max_edge_length_ratio")) is not None
    ]
    return {
        "count": len(records),
        "min_abs_volume_m3": min(volumes) if volumes else None,
        "max_abs_volume_m3": max(volumes) if volumes else None,
        "min_edge_length_m": min(min_edges) if min_edges else None,
        "max_edge_length_m": max(max_edges) if max_edges else None,
        "max_edge_length_ratio": max(edge_ratios) if edge_ratios else None,
    }


def _phase3_volume_element_source(element_type: int) -> str:
    if int(element_type) == SU2_PRISM:
        return "boundary_layer_prism"
    if int(element_type) == SU2_PYRAMID:
        return "transition_collar_pyramid"
    if int(element_type) == SU2_TETRAHEDRON:
        return "tetra_core"
    return f"element_type_{int(element_type)}"


def _point_markers_from_marker_faces(
    marker_faces: Mapping[str, Sequence[tuple[int, Sequence[int]]]],
) -> dict[int, set[str]]:
    point_markers: dict[int, set[str]] = {}
    for marker, faces in marker_faces.items():
        for _element_type, nodes in faces:
            for node in nodes:
                point_markers.setdefault(int(node), set()).add(str(marker))
    return point_markers


def _incident_source_counts_by_point(
    elements: Sequence[tuple[int, Sequence[int]]],
    element_sources: Sequence[str],
) -> dict[int, dict[str, int]]:
    counts: dict[int, dict[str, int]] = {}
    for (_element_type, nodes), source in zip(elements, element_sources):
        source_name = str(source)
        for node in nodes:
            bucket = counts.setdefault(int(node), {})
            bucket[source_name] = bucket.get(source_name, 0) + 1
    return counts


def _centroid_tuple(
    points: Sequence[Sequence[float]],
) -> tuple[float, float, float]:
    count = float(len(points))
    return (
        sum(float(point[0]) for point in points) / count,
        sum(float(point[1]) for point in points) / count,
        sum(float(point[2]) for point in points) / count,
    )


def _point_payload(point: Sequence[float]) -> dict[str, float]:
    return {"x": float(point[0]), "y": float(point[1]), "z": float(point[2])}


def _minimal_transition_unit_gate(
    topology: Mapping[str, Any],
    quality_gate: Mapping[str, Any],
    boundary_ownership: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    if int(topology.get("tet_to_prism_quad_contact") or 0) != 0:
        blockers.append("transition_unit_tet_directly_contacts_prism_quad")
    if int(topology.get("prism_quad_to_pyramid_base_contact") or 0) <= 0:
        blockers.append("transition_unit_prism_to_pyramid_contact_missing")
    if int(topology.get("pyramid_triangle_to_tet_contact") or 0) <= 0:
        blockers.append("transition_unit_pyramid_to_tet_contact_missing")
    if int(topology.get("tet_to_prism_triangle_contact") or 0) <= 0:
        blockers.append("transition_unit_prism_outer_triangle_to_tet_contact_missing")
    for key in (
        "boundary_faces_unmarked",
        "orphan_marker_faces",
        "duplicate_marker_faces",
        "nonmanifold_face_count",
        "non_root_exposed_prism_quad_count",
        "pyramid_boundary_face_count",
    ):
        if int(topology.get(key) or 0) != 0:
            blockers.append(f"transition_unit_{key}")
    if quality_gate.get("status") != "pass":
        blockers.extend(str(blocker) for blocker in quality_gate.get("blockers") or [])
    if boundary_ownership.get("status") != "pass":
        blockers.append("transition_unit_su2_boundary_ownership_not_pass")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": sorted(set(blockers)),
    }


def _oriented_tetra_for_shared_face(
    vertices: Sequence[tuple[float, float, float]],
    shared_face: Sequence[int],
    fourth_node: int,
) -> tuple[int, int, int, int]:
    face = tuple(int(node) for node in shared_face)
    candidate = (face[0], face[1], face[2], int(fourth_node))
    n = candidate
    signed = _tet_signed_volume(vertices[n[0]], vertices[n[1]], vertices[n[2]], vertices[n[3]])
    if signed > 0.0:
        return candidate
    flipped = (face[1], face[0], face[2], int(fourth_node))
    n = flipped
    signed = _tet_signed_volume(vertices[n[0]], vertices[n[1]], vertices[n[2]], vertices[n[3]])
    if signed > 0.0:
        return flipped
    raise RuntimeError("could not orient tetra with positive signed volume")


def _oriented_pyramid_positive(
    vertices: Sequence[tuple[float, float, float]],
    base_face: Sequence[int],
    apex_node: int,
) -> tuple[int, int, int, int, int]:
    base = tuple(int(node) for node in base_face)
    for permutation in itertools.permutations(base):
        candidate = (*permutation, int(apex_node))
        if _su2_pyramid_signed_volume(vertices, candidate) > 0.0:
            return candidate
    raise RuntimeError("could not orient pyramid with positive signed volume")


def _oriented_prism_positive(
    vertices: Sequence[tuple[float, float, float]],
    inner_face: Sequence[int],
    outer_face: Sequence[int],
) -> tuple[int, int, int, int, int, int]:
    inner = tuple(int(node) for node in inner_face)
    outer = tuple(int(node) for node in outer_face)
    for outer_permutation in itertools.permutations(outer):
        for inner_permutation in (inner, (inner[1], inner[0], inner[2])):
            candidate = (*outer_permutation, *inner_permutation)
            if _su2_prism_signed_volume(vertices, candidate) > 0.0:
                return candidate
    raise RuntimeError("could not orient prism with positive signed volume")


def _tet_extension_point(
    vertices: Sequence[tuple[float, float, float]],
    face_nodes: Sequence[int],
    *,
    magnitude: float,
) -> tuple[float, float, float]:
    points = [vertices[int(node)] for node in face_nodes]
    centroid = (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
        sum(point[2] for point in points) / len(points),
    )
    normal = _triangle_unit_normal(points[0], points[1], points[2])
    if _distance3(normal, (0.0, 0.0, 0.0)) <= 1.0e-14:
        normal = (0.0, 0.0, 1.0)
    return (
        centroid[0] + magnitude * normal[0],
        centroid[1] + magnitude * normal[1],
        centroid[2] + magnitude * normal[2],
    )


def _offset_point(
    point: tuple[float, float, float],
    direction: tuple[float, float, float],
    distance: float,
) -> tuple[float, float, float]:
    return (
        point[0] + distance * direction[0],
        point[1] + distance * direction[1],
        point[2] + distance * direction[2],
    )


def _su2_pyramid_signed_volume(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
) -> float:
    n = tuple(int(node) for node in nodes)
    return (
        _tet_signed_volume(vertices[n[0]], vertices[n[1]], vertices[n[2]], vertices[n[4]])
        + _tet_signed_volume(vertices[n[0]], vertices[n[2]], vertices[n[3]], vertices[n[4]])
    )


def _face_key_nodes(nodes: Sequence[int]) -> tuple[int, ...]:
    return tuple(sorted(int(node) for node in nodes))


def _partial_wing_cap_core_inner_boundary_surface(
    prism_volume: Mapping[str, Any],
    *,
    cap_triangles: Sequence[tuple[tuple[int, int, int], str]],
) -> SurfaceMesh:
    faces: list[Face] = []
    for element_type, nodes in prism_volume["marker_faces"]["bl_outer_interface"]:
        if int(element_type) == SU2_TRIANGLE:
            faces.append(Face(nodes=tuple(int(node) for node in nodes), marker="bl_outer_interface"))
    for marker in DIAGNOSTIC_FORCE_MARKERS:
        for element_type, nodes in prism_volume["marker_faces"].get(marker, []):
            if int(element_type) in {SU2_TRIANGLE, SU2_QUAD}:
                faces.append(Face(nodes=tuple(int(node) for node in nodes), marker=marker))
    for triangle, marker in cap_triangles:
        faces.append(Face(nodes=tuple(int(node) for node in triangle), marker=marker))
    return SurfaceMesh(
        vertices=[tuple(vertex) for vertex in prism_volume["nodes"]],
        faces=faces,
        metadata={"surface_role": "partial_wing_cap_core_inner_boundary"},
    )


def _surface_edge_topology(surface: SurfaceMesh) -> dict[str, Any]:
    edge_counts: dict[tuple[int, int], int] = {}
    edge_roles: dict[tuple[int, int], list[str]] = {}
    for face in surface.faces:
        nodes = tuple(int(node) for node in face.nodes)
        for start, end in zip(nodes, [*nodes[1:], nodes[0]]):
            key = tuple(sorted((start, end)))
            edge_counts[key] = edge_counts.get(key, 0) + 1
            edge_roles.setdefault(key, []).append(face.marker)
    bad_edges = {
        edge: count for edge, count in edge_counts.items() if int(count) != 2
    }
    count_histogram: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for edge, count in bad_edges.items():
        key = str(count)
        count_histogram[key] = count_histogram.get(key, 0) + 1
        for role in sorted(set(edge_roles.get(edge, []))):
            role_counts[role] = role_counts.get(role, 0) + 1
    return {
        "edge_count": len(edge_counts),
        "bad_edge_count": len(bad_edges),
        "bad_edge_count_histogram": count_histogram,
        "bad_edge_count_by_role": role_counts,
    }


def _partial_wing_cap_core_tets(
    inner_boundary: SurfaceMesh,
    *,
    surface_bounds: Mapping[str, float],
    output_dir: Path,
    core_mesh_size: float,
    farfield_mesh_size: float,
) -> dict[str, Any]:
    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("canonical_partial_wing_cap_core_probe")
        inner_by_marker = _add_discrete_marked_mesh_surfaces(
            gmsh,
            inner_boundary,
            first_tag=6_000_001,
            triangulation_policy="fixed_diagonal",
        )
        inner_tags = [
            tag for tags in inner_by_marker.values() for tag in tags
        ]
        gmsh.model.geo.synchronize()
        _farfield_vertices, symmetry_tags, farfield_tags = _add_farfield_box_with_symmetry_hole(
            gmsh,
            bounds=surface_bounds,
            bl_top_surface_tags=inner_tags,
            farfield_mesh_size=farfield_mesh_size,
        )
        core_volume = gmsh.model.geo.addVolume(
            [
                gmsh.model.geo.addSurfaceLoop(
                    [*inner_tags, *symmetry_tags, *farfield_tags]
                )
            ]
        )
        gmsh.model.geo.synchronize()
        gmsh.model.addPhysicalGroup(3, [core_volume])
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(core_mesh_size, farfield_mesh_size))
        gmsh.option.setNumber("Mesh.MeshSizeMax", max(core_mesh_size, farfield_mesh_size))
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(output_dir / "core.msh"))
        node_tags, _, _ = gmsh.model.mesh.getNodes()
        volume_types, volume_tags, _ = gmsh.model.mesh.getElements(3)
        type_counts = {
            str(element_type): len(tags)
            for element_type, tags in zip(volume_types, volume_tags)
        }
        forbidden_counts = {
            kind: count
            for kind, count in type_counts.items()
            if kind != GMSH_TETRA and int(count) > 0
        }
        return {
            "status": "meshed",
            "node_count": len(node_tags),
            "volume_element_type_counts": type_counts,
            "forbidden_element_type_counts": forbidden_counts,
            "inner_surface_entity_count": len(inner_tags),
            "root_symmetry_surface_count": len(symmetry_tags),
            "farfield_surface_count": len(farfield_tags),
            "mesh_path": str(output_dir / "core.msh"),
            "mesh_sizing": {
                "core_mesh_size": float(core_mesh_size),
                "farfield_mesh_size": float(farfield_mesh_size),
                "gmsh_algorithm3d": 1,
                "inner_boundary_representation": "triangulated_discrete",
            },
        }
    finally:
        gmsh.finalize()


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
        all_nodes = _gmsh_node_coordinates(gmsh)
        tetra_elements = _gmsh_tetra_elements(gmsh)
        raw_marker_faces = {
            "root_symmetry": _gmsh_surface_marker_faces(gmsh, symmetry_tags),
            "farfield": _gmsh_surface_marker_faces(gmsh, farfield_tags),
        }
        marker_faces = _orient_core_marker_faces_from_tetrahedra(
            tetra_elements,
            raw_marker_faces,
        )
        nodes, unused_node_tags = _active_core_node_coordinates(
            all_nodes,
            tetra_elements,
            marker_faces,
        )
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
        return {
            "nodes": nodes,
            "tetra_elements": tetra_elements,
            "marker_faces": marker_faces,
            "report": {
                "status": "meshed",
                "node_tag_integrity": {
                    "status": "pass",
                    "missing_tetra_node_tags": [],
                    "all_gmsh_node_count": len(all_nodes),
                    "active_node_count": len(nodes),
                    "unused_gmsh_node_count": len(unused_node_tags),
                    "unused_gmsh_node_samples": unused_node_tags[:8],
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
    """Return BL outer/termination interface vertices and triangular faces for Gmsh."""
    interface_faces: list[tuple[int, int, int]] = []
    for marker in ("bl_outer_interface", "bl_termination_interface"):
        for element_type, nodes in bl_volume["marker_faces"].get(marker, []):
            face_nodes = tuple(int(node) for node in nodes)
            if int(element_type) == SU2_TRIANGLE and len(face_nodes) == 3:
                interface_faces.append(face_nodes)
            elif int(element_type) == SU2_QUAD and len(face_nodes) == 4:
                interface_faces.extend(
                    [
                        (face_nodes[0], face_nodes[1], face_nodes[2]),
                        (face_nodes[0], face_nodes[2], face_nodes[3]),
                    ]
                )
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


def _stageback_transition_buffer_volume(
    bl_volume: Mapping[str, Any],
    *,
    buffer_layers: int,
    first_buffer_height_m: float,
    growth_ratio: float,
) -> dict[str, Any]:
    if buffer_layers <= 0:
        raise ValueError("buffer_layers must be positive")
    interface = _compact_outer_interface_surface(bl_volume)
    original_node_ids = [
        int(node) for node in interface.metadata.get("original_node_ids", [])
    ]
    interface_triangles = [tuple(int(node) for node in face.nodes) for face in interface.faces]
    raw_normals = _surface_vertex_normals(interface.vertices, interface_triangles)
    normals = [(-normal[0], -normal[1], -normal[2]) for normal in raw_normals]
    heights = _layer_cumulative_heights(
        first_buffer_height_m,
        growth_ratio,
        buffer_layers,
    )
    nodes = [tuple(node) for node in bl_volume["nodes"]]
    generated_nodes: dict[tuple[int, int], int] = {}

    def node(layer: int, local_node: int) -> int:
        local = int(local_node)
        if layer == 0:
            return original_node_ids[local]
        key = (int(layer), local)
        existing = generated_nodes.get(key)
        if existing is not None:
            return existing
        base_point = interface.vertices[local]
        normal = normals[local]
        height = heights[int(layer) - 1]
        generated_nodes[key] = len(nodes)
        nodes.append(
            (
                base_point[0] + height * normal[0],
                base_point[1] + height * normal[1],
                base_point[2] + height * normal[2],
            )
        )
        return generated_nodes[key]

    elements: list[tuple[int, tuple[int, ...]]] = []
    element_metadata: list[dict[str, Any]] = []
    face_records: dict[tuple[int, ...], dict[str, Any]] = {}

    def add_face(face_nodes: tuple[int, ...], element_type: int, marker: str) -> None:
        key = tuple(sorted(face_nodes))
        record = face_records.setdefault(
            key,
            {
                "count": 0,
                "nodes": face_nodes,
                "element_type": int(element_type),
                "marker": marker,
            },
        )
        record["count"] = int(record["count"]) + 1

    for layer in range(buffer_layers):
        for triangle in interface_triangles:
            a, b, c = triangle
            prism = (
                node(layer + 1, a),
                node(layer + 1, b),
                node(layer + 1, c),
                node(layer, a),
                node(layer, b),
                node(layer, c),
            )
            if _su2_prism_signed_volume(nodes, prism) <= 0.0:
                prism = (
                    node(layer + 1, a),
                    node(layer + 1, c),
                    node(layer + 1, b),
                    node(layer, a),
                    node(layer, c),
                    node(layer, b),
                )
            elements.append((SU2_PRISM, prism))
            element_metadata.append(
                {
                    "marker": "transition_buffer",
                    "layer": int(layer),
                    "layer_count": int(buffer_layers),
                    "base_triangle": [
                        original_node_ids[int(a)],
                        original_node_ids[int(b)],
                        original_node_ids[int(c)],
                    ],
                }
            )
            add_face(
                (prism[0], prism[2], prism[1]),
                SU2_TRIANGLE,
                "bl_outer_interface" if layer == buffer_layers - 1 else "_internal_bl_layer",
            )
            add_face(
                (prism[0], prism[3], prism[4], prism[1]),
                SU2_QUAD,
                _direct_prism_side_marker(
                    nodes,
                    (prism[3], prism[4]),
                    "bl_termination_interface",
                ),
            )
            add_face(
                (prism[1], prism[4], prism[5], prism[2]),
                SU2_QUAD,
                _direct_prism_side_marker(
                    nodes,
                    (prism[4], prism[5]),
                    "bl_termination_interface",
                ),
            )
            add_face(
                (prism[2], prism[5], prism[3], prism[0]),
                SU2_QUAD,
                _direct_prism_side_marker(
                    nodes,
                    (prism[5], prism[3]),
                    "bl_termination_interface",
                ),
            )

    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {
        str(marker): [
            (int(element_type), tuple(int(node) for node in face_nodes))
            for element_type, face_nodes in faces
        ]
        for marker, faces in _mapping(bl_volume.get("marker_faces")).items()
        if marker not in {"bl_outer_interface", "bl_termination_interface"}
    }
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
        "elements": [*bl_volume["elements"], *elements],
        "element_metadata": [*list(bl_volume.get("element_metadata") or []), *element_metadata],
        "marker_faces": marker_faces,
        "transition_buffer_prism_count": len(elements),
    }


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


def _active_core_node_coordinates(
    nodes: Mapping[int, tuple[float, float, float]],
    tetra_elements: Sequence[tuple[int, int, int, int]],
    marker_faces: Mapping[str, Sequence[tuple[int, Sequence[int]]]],
) -> tuple[dict[int, tuple[float, float, float]], list[int]]:
    used = {
        int(node)
        for tetra in tetra_elements
        for node in tetra
    }
    used.update(
        int(node)
        for faces in marker_faces.values()
        for _element_type, face_nodes in faces
        for node in face_nodes
    )
    active = {
        int(tag): coord
        for tag, coord in nodes.items()
        if int(tag) in used
    }
    unused = sorted(int(tag) for tag in nodes if int(tag) not in used)
    return active, unused


def _compact_volume_node_indices(volume: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = [tuple(vertex) for vertex in volume["nodes"]]
    elements = [
        (int(element_type), tuple(int(node) for node in element_nodes))
        for element_type, element_nodes in volume["elements"]
    ]
    marker_faces = {
        str(marker): [
            (int(element_type), tuple(int(node) for node in face_nodes))
            for element_type, face_nodes in faces
        ]
        for marker, faces in _mapping(volume.get("marker_faces")).items()
    }
    used = {
        int(node)
        for _element_type, element_nodes in elements
        for node in element_nodes
    }
    used.update(
        int(node)
        for faces in marker_faces.values()
        for _element_type, face_nodes in faces
        for node in face_nodes
    )
    ordered_used = sorted(used)
    node_map = {old: new for new, old in enumerate(ordered_used)}
    compacted = {
        "nodes": [nodes[old] for old in ordered_used],
        "elements": [
            (
                element_type,
                tuple(node_map[int(node)] for node in element_nodes),
            )
            for element_type, element_nodes in elements
        ],
        "marker_faces": {
            marker: [
                (
                    element_type,
                    tuple(node_map[int(node)] for node in face_nodes),
                )
                for element_type, face_nodes in faces
            ]
            for marker, faces in marker_faces.items()
        },
    }
    unused = [index for index in range(len(nodes)) if index not in used]
    return compacted, {
        "original_node_count": len(nodes),
        "compacted_node_count": len(compacted["nodes"]),
        "removed_unused_node_count": len(unused),
        "removed_unused_node_samples": unused[:8],
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
    edge_marker_map: Mapping[tuple[int, int], str] | None = None,
    triangle_layer_counts: Sequence[int] | None = None,
) -> dict[str, Any]:
    if triangle_layer_counts is None:
        effective_layer_counts = [int(bl_layers)] * len(triangles)
    else:
        if len(triangle_layer_counts) != len(triangles):
            raise ValueError("triangle_layer_counts length must match triangles")
        effective_layer_counts = [int(count) for count in triangle_layer_counts]
    if any(count <= 0 for count in effective_layer_counts):
        raise ValueError("all triangle layer counts must be positive")
    max_layer_count = max(effective_layer_counts) if effective_layer_counts else int(bl_layers)
    heights = [
        0.0,
        *_layer_cumulative_heights(first_layer_height_m, growth_ratio, max_layer_count),
    ]
    normals = _surface_vertex_normals(base_vertices, [triangle for triangle, _ in triangles])
    base_edge_counts: dict[tuple[int, int], int] = {}
    for triangle, _marker in triangles:
        for edge in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
            key = tuple(sorted((int(edge[0]), int(edge[1]))))
            base_edge_counts[key] = base_edge_counts.get(key, 0) + 1
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
    element_metadata: list[dict[str, Any]] = []
    face_records: dict[tuple[int, ...], dict[str, Any]] = {}

    def add_face(
        face_nodes: tuple[int, ...],
        element_type: int,
        marker: str,
        *,
        base_edge: tuple[int, int] | None = None,
    ) -> None:
        key = tuple(sorted(face_nodes))
        record = face_records.setdefault(
            key,
            {
                "count": 0,
                "nodes": face_nodes,
                "element_type": element_type,
                "marker": marker,
                "base_edge": base_edge,
            },
        )
        record["count"] = int(record["count"]) + 1

    for layer in range(max_layer_count):
        for triangle_index, (triangle, marker) in enumerate(triangles):
            triangle_layers = effective_layer_counts[triangle_index]
            if layer >= triangle_layers:
                continue
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
            element_metadata.append(
                {
                    "marker": str(marker),
                    "layer": int(layer),
                    "layer_count": int(triangle_layers),
                    "base_triangle": [int(a), int(b), int(c)],
                }
            )
            add_face((prism[3], prism[4], prism[5]), SU2_TRIANGLE, marker)
            add_face(
                (prism[0], prism[2], prism[1]),
                SU2_TRIANGLE,
                "bl_outer_interface" if layer == triangle_layers - 1 else "_internal_bl_layer",
            )
            add_face(
                (prism[0], prism[3], prism[4], prism[1]),
                SU2_QUAD,
                _direct_prism_side_marker(
                    base_vertices,
                    (a, b),
                    marker,
                    edge_marker_map=edge_marker_map,
                ),
                base_edge=(a, b),
            )
            add_face(
                (prism[1], prism[4], prism[5], prism[2]),
                SU2_QUAD,
                _direct_prism_side_marker(
                    base_vertices,
                    (b, c),
                    marker,
                    edge_marker_map=edge_marker_map,
                ),
                base_edge=(b, c),
            )
            add_face(
                (prism[2], prism[5], prism[3], prism[0]),
                SU2_QUAD,
                _direct_prism_side_marker(
                    base_vertices,
                    (c, a),
                    marker,
                    edge_marker_map=edge_marker_map,
                ),
                base_edge=(c, a),
            )

    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    for record in face_records.values():
        if int(record["count"]) != 1:
            continue
        marker = str(record["marker"])
        if marker == "_internal_bl_layer":
            continue
        base_edge = record.get("base_edge")
        if base_edge is not None:
            edge_key = tuple(sorted((int(base_edge[0]), int(base_edge[1]))))
            if base_edge_counts.get(edge_key, 0) > 1:
                marker = "bl_termination_interface"
        marker_faces.setdefault(marker, []).append(
            (int(record["element_type"]), tuple(int(node) for node in record["nodes"]))
        )
    return {
        "nodes": nodes,
        "elements": elements,
        "element_metadata": element_metadata,
        "marker_faces": marker_faces,
        "base_vertex_count": base_count,
    }


def _cap_edge_marker_map(
    cap_triangles: Sequence[tuple[tuple[int, int, int], str]],
) -> dict[tuple[int, int], str]:
    precedence = {
        "tip_wall": 0,
        "te_wall": 1,
        "closure_wall": 2,
    }
    edge_markers: dict[tuple[int, int], str] = {}
    for triangle, marker in cap_triangles:
        for edge in (
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ):
            key = tuple(sorted((int(edge[0]), int(edge[1]))))
            existing = edge_markers.get(key)
            if existing is None or precedence.get(marker, 99) < precedence.get(
                existing, 99
            ):
                edge_markers[key] = marker
    return edge_markers


def _source_rim_edge_split_plan(
    base_vertices: Sequence[tuple[float, float, float]],
    triangles: Sequence[tuple[tuple[int, int, int], str]],
    *,
    edge_marker_map: Mapping[tuple[int, int], str],
    first_layer_height_m: float,
) -> tuple[dict[tuple[int, int], int], dict[str, Any]]:
    if first_layer_height_m <= 0.0:
        raise ValueError("first_layer_height_m must be positive")
    edge_segments: dict[tuple[int, int], int] = {}
    records_by_edge: dict[tuple[int, int], dict[str, Any]] = {}
    for triangle, _marker in triangles:
        for edge in (
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ):
            key = tuple(sorted((int(edge[0]), int(edge[1]))))
            marker = edge_marker_map.get(key)
            if marker not in DIAGNOSTIC_FORCE_MARKERS:
                continue
            if all(abs(base_vertices[node][1]) <= 1.0e-9 for node in key):
                continue
            length = _distance3(base_vertices[key[0]], base_vertices[key[1]])
            single_base_ratio = length / first_layer_height_m
            required_segments = max(
                1,
                math.ceil(
                    single_base_ratio / MAX_ROUTE_DUAL_HOTSPOT_INCIDENT_EDGE_RATIO
                ),
            )
            if required_segments <= 1:
                continue
            record = records_by_edge.get(key)
            if record is not None and single_base_ratio <= float(
                record["single_pyramid_base_edge_ratio"]
            ):
                continue
            edge_segments[key] = required_segments
            records_by_edge[key] = {
                "marker": str(marker),
                "source_edge": [int(key[0]), int(key[1])],
                "required_segments": int(required_segments),
                "single_pyramid_base_edge_ratio": float(single_base_ratio),
                "planned_segment_base_edge_ratio": float(
                    single_base_ratio / required_segments
                ),
                "edge_length_m": float(length),
                "first_layer_height_m": float(first_layer_height_m),
            }
    records = list(records_by_edge.values())
    required_by_marker = {marker: 0 for marker in DIAGNOSTIC_FORCE_MARKERS}
    for record in records:
        marker = str(record["marker"])
        required_by_marker[marker] = required_by_marker.get(marker, 0) + int(
            record["required_segments"]
        )
    report = {
        "threshold_max_edge_ratio": MAX_ROUTE_DUAL_HOTSPOT_INCIDENT_EDGE_RATIO,
        "source_edge_count": len(records),
        "required_source_edge_segments_by_marker": required_by_marker,
        "total_required_source_edge_segments": sum(
            int(record["required_segments"]) for record in records
        ),
        "max_required_segments_per_source_edge": (
            max(int(record["required_segments"]) for record in records)
            if records
            else 0
        ),
        "max_single_source_edge_base_ratio": (
            max(float(record["single_pyramid_base_edge_ratio"]) for record in records)
            if records
            else 0.0
        ),
        "max_planned_source_edge_base_ratio": (
            max(float(record["planned_segment_base_edge_ratio"]) for record in records)
            if records
            else 0.0
        ),
        "split_policy": "split_source_rim_edge_before_bl_extrusion",
        "plan_samples": records[:8],
    }
    return edge_segments, report


def _split_wall_triangles_on_source_edges(
    base_vertices: Sequence[tuple[float, float, float]],
    triangles: Sequence[tuple[tuple[int, int, int], str]],
    *,
    edge_segment_counts: Mapping[tuple[int, int], int],
) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[tuple[int, int, int], str]],
    dict[str, Any],
]:
    vertices = [tuple(vertex) for vertex in base_vertices]
    edge_node_cache: dict[tuple[int, int], list[int]] = {}

    def edge_nodes(start: int, end: int) -> list[int]:
        key = tuple(sorted((int(start), int(end))))
        segments = int(edge_segment_counts.get(key, 1))
        if segments <= 1:
            return [int(start), int(end)]
        cached = edge_node_cache.get(key)
        if cached is None:
            low, high = key
            low_point = vertices[low]
            high_point = vertices[high]
            nodes = [low]
            for index in range(1, segments):
                fraction = index / segments
                vertices.append(
                    (
                        low_point[0] + fraction * (high_point[0] - low_point[0]),
                        low_point[1] + fraction * (high_point[1] - low_point[1]),
                        low_point[2] + fraction * (high_point[2] - low_point[2]),
                    )
                )
                nodes.append(len(vertices) - 1)
            nodes.append(high)
            cached = nodes
            edge_node_cache[key] = cached
        if int(start) == cached[0] and int(end) == cached[-1]:
            return list(cached)
        return list(reversed(cached))

    split_triangles: list[tuple[tuple[int, int, int], str]] = []
    max_boundary_vertex_count = 0
    for triangle, marker in triangles:
        a, b, c = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
        ab = edge_nodes(a, b)
        bc = edge_nodes(b, c)
        ca = edge_nodes(c, a)
        boundary = [*ab, *bc[1:], *ca[1:-1]]
        max_boundary_vertex_count = max(max_boundary_vertex_count, len(boundary))
        for sub_triangle in _triangulate_convex_boundary_polygon(vertices, boundary):
            split_triangles.append((sub_triangle, str(marker)))
    return vertices, split_triangles, {
        "input_vertex_count": len(base_vertices),
        "output_vertex_count": len(vertices),
        "added_source_vertices": len(vertices) - len(base_vertices),
        "input_triangle_count": len(triangles),
        "output_triangle_count": len(split_triangles),
        "split_source_edge_count": len(edge_node_cache),
        "max_boundary_vertex_count": max_boundary_vertex_count,
    }


def _triangulate_convex_boundary_polygon(
    vertices: Sequence[tuple[float, float, float]],
    boundary_nodes: Sequence[int],
) -> list[tuple[int, int, int]]:
    remaining = [int(node) for node in boundary_nodes]
    if len(remaining) < 3:
        return []
    triangles: list[tuple[int, int, int]] = []
    guard = 0
    while len(remaining) > 3:
        guard += 1
        if guard > len(boundary_nodes) * len(boundary_nodes):
            raise RuntimeError("could not triangulate split boundary polygon")
        for index, current in enumerate(remaining):
            candidate = (
                remaining[index - 1],
                current,
                remaining[(index + 1) % len(remaining)],
            )
            if _triangle_area_norm(vertices, candidate) <= 1.0e-14:
                continue
            remaining_after_ear = [*remaining[:index], *remaining[index + 1 :]]
            if (
                len(remaining_after_ear) >= 3
                and _polygon_area_norm(vertices, remaining_after_ear) <= 1.0e-14
            ):
                continue
            triangles.append(candidate)
            del remaining[index]
            break
        else:
            raise RuntimeError("split boundary polygon is degenerate")
    final_triangle = tuple(remaining)
    if _triangle_area_norm(vertices, final_triangle) > 1.0e-14:
        triangles.append(final_triangle)
    return triangles


def _triangle_area_norm(
    vertices: Sequence[tuple[float, float, float]],
    triangle: Sequence[int],
) -> float:
    return _polygon_area_norm(vertices, triangle)


def _polygon_area_norm(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
) -> float:
    area_vector = _face_area_vector(vertices, nodes)
    return math.sqrt(
        area_vector[0] ** 2 + area_vector[1] ** 2 + area_vector[2] ** 2
    )


def _direct_prism_quality_metrics(volume: Mapping[str, Any]) -> dict[str, Any]:
    vertices = [tuple(vertex) for vertex in volume["nodes"]]
    prism_signed_volumes: list[float] = []
    prism_by_marker: dict[str, list[float]] = {}
    non_positive_by_layer: dict[str, int] = {}
    non_positive_hotspots: list[dict[str, Any]] = []
    element_metadata = list(volume.get("element_metadata") or [])
    prism_index = 0
    for element_index, (element_type, nodes) in enumerate(volume["elements"]):
        if int(element_type) != SU2_PRISM:
            continue
        signed_volume = _su2_prism_signed_volume(vertices, nodes)
        prism_signed_volumes.append(signed_volume)
        metadata = (
            _mapping(element_metadata[prism_index])
            if prism_index < len(element_metadata)
            else {}
        )
        marker = str(metadata.get("marker") or "unknown")
        layer = int(metadata.get("layer") or 0)
        prism_by_marker.setdefault(marker, []).append(signed_volume)
        if signed_volume <= 0.0 or not math.isfinite(signed_volume):
            layer_key = str(layer)
            non_positive_by_layer[layer_key] = (
                non_positive_by_layer.get(layer_key, 0) + 1
            )
            prism_nodes = tuple(int(node) for node in nodes)
            points = [vertices[node] for node in prism_nodes]
            centroid = _centroid_tuple(points)
            non_positive_hotspots.append(
                {
                    "element_index": int(element_index),
                    "prism_index": int(prism_index),
                    "marker": marker,
                    "layer": int(layer),
                    "signed_volume": float(signed_volume),
                    "centroid": _point_payload(centroid),
                    "base_triangle": [
                        int(node)
                        for node in (metadata.get("base_triangle") or [])
                    ],
                    "nodes": [int(node) for node in prism_nodes],
                }
            )
        prism_index += 1
    quad_aspect_by_marker: dict[str, dict[str, Any]] = {}
    worst_root_quad: dict[str, Any] | None = None
    for marker, faces in _mapping(volume.get("marker_faces")).items():
        aspects: list[float] = []
        marker_worst: dict[str, Any] | None = None
        for element_type, face_nodes in faces:
            nodes = tuple(int(node) for node in face_nodes)
            if int(element_type) != 9 or len(nodes) != 4:
                continue
            edge_lengths = _face_edge_lengths(vertices, nodes)
            min_edge = min(edge_lengths) if edge_lengths else 0.0
            max_edge = max(edge_lengths) if edge_lengths else 0.0
            aspect = max_edge / min_edge if min_edge > 0.0 else math.inf
            aspects.append(aspect)
            record = {
                "marker": str(marker),
                "nodes": list(nodes),
                "aspect_ratio": float(aspect),
                "edge_lengths_m": [float(value) for value in edge_lengths],
            }
            if marker_worst is None or aspect > float(marker_worst["aspect_ratio"]):
                marker_worst = record
        if aspects:
            quad_aspect_by_marker[str(marker)] = {
                "count": len(aspects),
                "max": max(aspects),
                "min": min(aspects),
                "count_over_1000": sum(
                    1
                    for aspect in aspects
                    if aspect > MAX_DIRECT_ROOT_SYMMETRY_QUAD_ASPECT_RATIO
                ),
                "worst_quad": marker_worst,
            }
        if str(marker) == "root_symmetry":
            worst_root_quad = marker_worst

    root_aspect = quad_aspect_by_marker.get(
        "root_symmetry",
        {"count": 0, "max": None, "min": None, "count_over_1000": 0},
    )
    finite_prism_volumes = [
        value for value in prism_signed_volumes if math.isfinite(value)
    ]
    return {
        "prism_signed_volume": {
            "count": len(prism_signed_volumes),
            "min": min(finite_prism_volumes) if finite_prism_volumes else None,
            "max": max(finite_prism_volumes) if finite_prism_volumes else None,
            "non_positive_count": sum(
                1 for value in finite_prism_volumes if value <= 0.0
            ),
        },
        "prism_signed_volume_by_marker": {
            marker: _signed_volume_bucket(values)
            for marker, values in sorted(prism_by_marker.items())
        },
        "non_positive_prism_by_layer": dict(
            sorted(non_positive_by_layer.items(), key=lambda item: int(item[0]))
        ),
        "non_positive_prism_hotspots": sorted(
            non_positive_hotspots,
            key=lambda record: float(record["signed_volume"]),
        )[:20],
        "marker_quad_aspect": quad_aspect_by_marker,
        "root_symmetry_quad_aspect": root_aspect,
        "worst_root_symmetry_quad": worst_root_quad,
    }


def _signed_volume_bucket(values: Sequence[float]) -> dict[str, Any]:
    finite_values = [value for value in values if math.isfinite(value)]
    return {
        "count": len(values),
        "min": min(finite_values) if finite_values else None,
        "max": max(finite_values) if finite_values else None,
        "non_positive_count": sum(1 for value in finite_values if value <= 0.0),
    }


def _direct_prism_quality_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    prism_volume = _mapping(metrics.get("prism_signed_volume"))
    root_aspect = _mapping(metrics.get("root_symmetry_quad_aspect"))
    root_aspect_max = _float_or_none(root_aspect.get("max"))

    if int(prism_volume.get("count") or 0) <= 0:
        blockers.append("direct_prism_cells_missing")
    if int(prism_volume.get("non_positive_count") or 0) > 0:
        blockers.append("direct_prism_non_positive_signed_volume")
    if int(root_aspect.get("count") or 0) <= 0:
        blockers.append("root_symmetry_sidewall_quads_missing")
    if (
        root_aspect_max is None
        or root_aspect_max > MAX_DIRECT_ROOT_SYMMETRY_QUAD_ASPECT_RATIO
    ):
        blockers.append("root_symmetry_sidewall_quad_aspect_ratio_exceeds_1000")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": sorted(set(blockers)),
        "thresholds": {
            "max_root_symmetry_quad_aspect_ratio": (
                MAX_DIRECT_ROOT_SYMMETRY_QUAD_ASPECT_RATIO
            ),
        },
    }


def _su2_prism_signed_volume(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
) -> float:
    n = tuple(int(node) for node in nodes)
    return (
        _tet_signed_volume(vertices[n[3]], vertices[n[4]], vertices[n[5]], vertices[n[0]])
        + _tet_signed_volume(vertices[n[4]], vertices[n[1]], vertices[n[5]], vertices[n[0]])
        + _tet_signed_volume(vertices[n[5]], vertices[n[1]], vertices[n[2]], vertices[n[0]])
    )


def _tet_signed_volume(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    d: tuple[float, float, float],
) -> float:
    return _dot(_vector_between(a, b), _cross(_vector_between(a, c), _vector_between(a, d))) / 6.0


def _face_edge_lengths(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
) -> list[float]:
    return [
        _distance3(vertices[int(nodes[index])], vertices[int(nodes[(index + 1) % len(nodes)])])
        for index in range(len(nodes))
    ]


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


def _dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _direct_prism_side_marker(
    vertices: Sequence[tuple[float, float, float]],
    edge: tuple[int, int],
    source_marker: str,
    *,
    edge_marker_map: Mapping[tuple[int, int], str] | None = None,
) -> str:
    if all(abs(vertices[node][1]) <= 1.0e-9 for node in edge):
        return "root_symmetry"
    key = tuple(sorted((int(edge[0]), int(edge[1]))))
    if edge_marker_map and key in edge_marker_map:
        return edge_marker_map[key]
    return source_marker


def _triangle_touches_te_stageback_band(
    triangle: Sequence[int],
    *,
    points_per_station: int,
    stageback_segments: int,
) -> bool:
    if stageback_segments <= 0:
        return False
    segment_count = int(stageback_segments)
    station_points = int(points_per_station)
    local_indices = [int(node) % station_points for node in triangle]
    return any(
        local_index < segment_count
        or local_index >= station_points - segment_count
        for local_index in local_indices
    )


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
