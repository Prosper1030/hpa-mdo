#!/usr/bin/env python3
"""Run the bounded WO-006 CFD tool-route decision.

This script deliberately stops the Phase 3 custom partial-BL SU2 hybrid
core-fill route. It only records two bounded rescue tracks:

* Track A: full-wing OpenFOAM external-aero route, with a hard stop if the
  local OpenFOAM toolchain cannot run the 0- and 3-layer attempts.
* Track B: full-wing SU2 pressure-only/slip-wall sanity, with split force
  markers and no wall-resolved hybrid BL.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
SCRIPT_DIR = REPO_ROOT / "scripts"
for path in (HPA_MESHING_SRC, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from diagnose_wo006j_drag_source import parse_forces_breakdown_text  # noqa: E402
from hpa_meshing.mesh_native.blackcat import _subdivide_spanwise_stations  # noqa: E402
from hpa_meshing.mesh_native.gmsh_polyhedral import _add_marked_mesh_surfaces  # noqa: E402
from hpa_meshing.mesh_native.su2_structured import (  # noqa: E402
    audit_su2_case_markers,
    parse_su2_marker_summary,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    Face,
    Station,
    SurfaceMesh,
    orient_surface_mesh_outward,
    validate_surface_mesh,
)
from run_canonical_hybrid_phase2_pressure_sanity import (  # noqa: E402
    DEFAULT_AVL_PATH,
    DEFAULT_SECTION_TABLE_PATH,
    DEFAULT_SOLVER_COMMAND,
    _airfoil_source_transition_spans,
    _bounds,
    _half_stations_from_rows,
    _mapping,
    _mesh_quality_gate,
    _mesh_quality_metrics,
    _read_avl_moment_origin,
    _read_avl_reference,
    _read_csv_dicts,
    _run_solver,
    _surface_area_by_marker,
    _transform_station,
    parse_pressure_history,
    parse_su2_dual_control_volume_quality,
)


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_tool_route_decision"
SPLIT_WING_MARKERS = (
    "wing_upper",
    "wing_lower",
    "tip_left",
    "tip_right",
    "te_wall",
    "closure_wall",
)
PRIMARY_FORCE_MARKERS = ("wing_upper", "wing_lower")
DIAGNOSTIC_FORCE_MARKERS = ("tip_left", "tip_right", "te_wall", "closure_wall")
REQUIRED_SU2_MARKERS = (*SPLIT_WING_MARKERS, "farfield")
ALLOWED_SPLIT_MARKERS = frozenset(REQUIRED_SU2_MARKERS)
PREVIOUS_HALF_WING_PRESSURE_CD = 0.0177873
DEFAULT_POINTS_PER_SIDE = 6
DEFAULT_SPANWISE_SUBDIVISIONS = 4
DEFAULT_MAX_ITERATIONS = 500
DEFAULT_VELOCITY_MPS = 6.5
OPENFOAM_TOOLS = ("blockMesh", "snappyHexMesh", "checkMesh", "simpleFoam")


def build_fullwing_pressure_surface(
    section_table_path: Path | str = DEFAULT_SECTION_TABLE_PATH,
    *,
    points_per_side: int = DEFAULT_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
) -> SurfaceMesh:
    """Build a watertight full-wing faceted surface with split physical markers."""

    rows = _read_csv_dicts(Path(section_table_path))
    base_half = _half_stations_from_rows(rows, points_per_side=points_per_side)
    half = (
        base_half
        if spanwise_subdivisions <= 1
        else _subdivide_spanwise_stations(base_half, spanwise_subdivisions)
    )
    stations = _mirror_half_wing(half)
    points_per_station = len(stations[0].airfoil_xz)
    leading_edge_index = points_per_side - 1
    vertices: list[tuple[float, float, float]] = []
    for station in stations:
        vertices.extend(_transform_station(station, twist_axis_x=0.25))

    source_transition_spans = _airfoil_source_transition_spans(rows)
    closure_sections = _fullwing_closure_sections(stations, source_transition_spans)
    faces: list[Face] = []

    def vid(section: int, point: int) -> int:
        return section * points_per_station + (point % points_per_station)

    for section_index in range(len(stations) - 1):
        for point_index in range(points_per_station):
            marker = _segment_marker(
                point_index,
                points_per_station=points_per_station,
                leading_edge_index=leading_edge_index,
                is_source_transition_te=section_index in closure_sections,
            )
            faces.append(
                Face(
                    nodes=(
                        vid(section_index, point_index),
                        vid(section_index + 1, point_index),
                        vid(section_index + 1, point_index + 1),
                        vid(section_index, point_index + 1),
                    ),
                    marker=marker,
                )
            )
    _append_tip_cap(
        vertices,
        faces,
        [vid(0, point) for point in range(points_per_station)],
        marker="tip_left",
        reverse=True,
    )
    _append_tip_cap(
        vertices,
        faces,
        [vid(len(stations) - 1, point) for point in range(points_per_station)],
        marker="tip_right",
        reverse=False,
    )
    surface = SurfaceMesh(
        vertices=vertices,
        faces=faces,
        metadata={
            "route": "wo006_fullwing_pressure_only_tool_route_decision",
            "side": "full",
            "root_symmetry": "not_used_full_wing",
            "points_per_side": int(points_per_side),
            "points_per_station": points_per_station,
            "base_half_station_count": len(base_half),
            "station_count": len(stations),
            "spanwise_subdivisions": int(spanwise_subdivisions),
            "source_transition_spans": source_transition_spans,
            "closure_section_indices": sorted(closure_sections),
            "force_primary_markers": list(PRIMARY_FORCE_MARKERS),
            "force_diagnostic_markers": list(DIAGNOSTIC_FORCE_MARKERS),
        },
    )
    validate_surface_mesh(
        surface,
        allowed_markers=ALLOWED_SPLIT_MARKERS,
        required_markers=SPLIT_WING_MARKERS,
    )
    oriented = orient_surface_mesh_outward(surface)
    validate_surface_mesh(
        oriented,
        allowed_markers=ALLOWED_SPLIT_MARKERS,
        required_markers=SPLIT_WING_MARKERS,
    )
    return oriented


def fullwing_pressure_cfg_text(
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
    marker_list = ", ".join(SPLIT_WING_MARKERS)
    return "\n".join(
        [
            "% WO-006 Track B full-wing SU2 pressure-only sanity.",
            "% Slip/Euler walls only; do not use this for wall-resolved BL drag.",
            "SOLVER= INC_EULER",
            "KIND_TURB_MODEL= NONE",
            "MATH_PROBLEM= DIRECT",
            "RESTART_SOL= NO",
            "SYSTEM_MEASUREMENTS= SI",
            "INC_NONDIM= INITIAL_VALUES",
            "INC_DENSITY_MODEL= CONSTANT",
            "INC_DENSITY_INIT= 1.225000",
            "INC_TEMPERATURE_INIT= 288.150000",
            "VISCOSITY_MODEL= CONSTANT_VISCOSITY",
            "MU_CONSTANT= 1.789400e-05",
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
            f"MARKER_EULER= ( {marker_list} )",
            "MARKER_FAR= ( farfield )",
            f"MARKER_MONITORING= ( {marker_list} )",
            f"MARKER_PLOTTING= ( {marker_list} )",
            "NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES",
            "CONV_NUM_METHOD_FLOW= FDS",
            "MUSCL_FLOW= YES",
            "SLOPE_LIMITER_FLOW= NONE",
            "TIME_DISCRE_FLOW= EULER_IMPLICIT",
            "LINEAR_SOLVER= FGMRES",
            "LINEAR_SOLVER_PREC= ILU",
            "LINEAR_SOLVER_ERROR= 1e-6",
            "LINEAR_SOLVER_ITER= 10",
            f"ITER= {int(max_iterations)}",
            "CFL_NUMBER= 1.0",
            "CONV_FIELD= DRAG",
            "CONV_RESIDUAL_MINVAL= -9",
            "CONV_STARTITER= 10",
            "CONV_CAUCHY_ELEMS= 100",
            "CONV_CAUCHY_EPS= 1e-5",
            "CONV_FILENAME= history",
            "TABULAR_FORMAT= CSV",
            "SCREEN_OUTPUT= (INNER_ITER, RMS_RES, AERO_COEFF)",
            "HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF)",
            "OUTPUT_FILES= (RESTART_ASCII, SURFACE_CSV)",
            "BREAKDOWN_FILENAME= forces_breakdown.dat",
            "WRT_FORCES_BREAKDOWN= YES",
            "",
        ]
    )


def plan_openfoam_track_attempts(
    tool_paths: Mapping[str, str | None],
    *,
    layer_schedule: Sequence[int] = (0, 3, 8),
) -> dict[str, Any]:
    missing = [tool for tool in OPENFOAM_TOOLS if not tool_paths.get(tool)]
    attempts: list[dict[str, Any]] = []
    hard_stop = False
    for layer_count in layer_schedule:
        if missing:
            if layer_count in (0, 3):
                attempts.append(
                    {
                        "nSurfaceLayers": int(layer_count),
                        "status": "not_run",
                        "reason": "openfoam_executables_missing",
                        "missing_tools": missing,
                    }
                )
            else:
                hard_stop = True
                break
        else:
            attempts.append(
                {
                    "nSurfaceLayers": int(layer_count),
                    "status": "planned",
                    "reason": "toolchain_available_not_executed_by_planner",
                    "missing_tools": [],
                }
            )
    skipped = [int(layer) for layer in layer_schedule if layer not in {a["nSurfaceLayers"] for a in attempts}]
    blockers = ["openfoam_executables_missing"] if missing else []
    return {
        "schema_version": "wo006_track_a_openfoam_attempt_plan.v1",
        "status": "blocked_tool_unavailable" if missing else "ready_to_run",
        "tool_paths": {tool: tool_paths.get(tool) for tool in OPENFOAM_TOOLS},
        "blockers": blockers,
        "attempts": attempts,
        "skipped_layers": skipped,
        "hard_stop_triggered": hard_stop or bool(missing and skipped),
        "hard_stop_rule": "stop after nSurfaceLayers=0 and 3 if Track A cannot mesh or run",
    }


def summarize_split_marker_forces(parsed_forces: Mapping[str, Any]) -> dict[str, Any]:
    surfaces = _mapping(parsed_forces.get("surface_coefficients"))

    def marker_coeff(marker: str, coeff: str) -> float | None:
        payload = _mapping(_mapping(surfaces.get(marker)).get(coeff))
        value = payload.get("total")
        if value is None:
            return None
        try:
            converted = float(value)
        except (TypeError, ValueError):
            return None
        return converted if math.isfinite(converted) else None

    def sum_coeff(markers: Iterable[str], coeff: str) -> float | None:
        values = [marker_coeff(marker, coeff) for marker in markers]
        if any(value is None for value in values):
            return None
        return round(sum(float(value) for value in values if value is not None), 10)

    diagnostics = {
        marker: {
            "cd": marker_coeff(marker, "cd"),
            "cl": marker_coeff(marker, "cl"),
        }
        for marker in DIAGNOSTIC_FORCE_MARKERS
    }
    primary = {
        "cd": sum_coeff(PRIMARY_FORCE_MARKERS, "cd"),
        "cl": sum_coeff(PRIMARY_FORCE_MARKERS, "cl"),
    }
    diagnostic_total = {
        "cd": sum_coeff(DIAGNOSTIC_FORCE_MARKERS, "cd"),
        "cl": sum_coeff(DIAGNOSTIC_FORCE_MARKERS, "cl"),
    }
    return {
        "primary": primary,
        "diagnostics": diagnostics,
        "diagnostic_total": diagnostic_total,
        "total": {
            "cd": sum_coeff(SPLIT_WING_MARKERS, "cd"),
            "cl": sum_coeff(SPLIT_WING_MARKERS, "cl"),
        },
        "missing_surfaces": sorted(marker for marker in SPLIT_WING_MARKERS if marker not in surfaces),
    }


def run_tool_route_decision(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    clean: bool = True,
    run_su2: bool = True,
    solver_command: str = DEFAULT_SOLVER_COMMAND,
    threads: int = 4,
    timeout_seconds: float = 1800.0,
    points_per_side: int = DEFAULT_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_SPANWISE_SUBDIVISIONS,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    ref = _read_avl_reference(DEFAULT_AVL_PATH)
    ref_origin = _read_avl_moment_origin(DEFAULT_AVL_PATH)
    surface = build_fullwing_pressure_surface(
        DEFAULT_SECTION_TABLE_PATH,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    track_a = run_track_a_openfoam(
        output_dir / "track_a_openfoam_case",
        surface=surface,
        cref_m=float(ref["cref"]),
    )
    track_b = run_track_b_su2_pressure(
        output_dir / "track_b_su2_fullwing_pressure",
        surface=surface,
        ref_area=float(ref["sref"]),
        ref_length=float(ref["cref"]),
        ref_origin=ref_origin,
        run_su2=run_su2,
        solver_command=solver_command,
        threads=threads,
        timeout_seconds=timeout_seconds,
        max_iterations=max_iterations,
    )
    decision = build_tool_route_decision(track_a, track_b)
    manifest = {
        "schema_version": "wo006_cfd_tool_route_decision.v1",
        "created_at_utc": _utc_now(),
        "output_dir": str(output_dir),
        "stopped_route": {
            "name": "Phase 3 custom partial-BL SU2 hybrid core-fill",
            "status": "stopped",
            "do_not_continue": [
                "discrete PLC core-fill",
                "receiver/cycle/cap patching",
                "Gmsh reconstruct of the large discrete shell",
                "meshpy/TetGen retries on the same .poly",
                "SU2 hybrid writer repairs",
                "new R-series or Phase-3 topology patches",
            ],
        },
        "track_a": _manifest_track_payload(track_a),
        "track_b": _manifest_track_payload(track_b),
        "decision": decision,
        "elapsed_s": time.monotonic() - start,
    }
    write_json(output_dir / "route_decision_manifest.json", manifest)
    (output_dir / "openfoam_track_summary.md").write_text(
        render_openfoam_summary(track_a),
        encoding="utf-8",
    )
    (output_dir / "su2_fullwing_pressure_sanity_summary.md").write_text(
        render_su2_summary(track_b),
        encoding="utf-8",
    )
    (output_dir / "tool_route_decision.md").write_text(
        render_tool_route_decision(decision, track_a, track_b),
        encoding="utf-8",
    )
    return manifest


def run_track_a_openfoam(case_dir: Path, *, surface: SurfaceMesh, cref_m: float) -> dict[str, Any]:
    tool_paths = {tool: shutil.which(tool) for tool in OPENFOAM_TOOLS}
    case_dir.mkdir(parents=True, exist_ok=True)
    write_openfoam_case_scaffold(case_dir, surface=surface, cref_m=cref_m)
    plan = plan_openfoam_track_attempts(tool_paths)
    return {
        **plan,
        "case_dir": str(case_dir),
        "surface_marker_counts": surface.marker_counts(),
        "case_scaffold": {
            "status": "written",
            "surface_patch_files": [
                str(case_dir / "constant" / "triSurface" / f"{marker}.stl")
                for marker in SPLIT_WING_MARKERS
            ],
            "block_mesh_dict": str(case_dir / "system" / "blockMeshDict"),
            "snappy_hex_mesh_dict": str(case_dir / "system" / "snappyHexMeshDict"),
        },
        "engineering_assessment": {
            "status": "not_run_locally",
            "reason": "OpenFOAM executables are not installed on PATH"
            if plan["blockers"]
            else "OpenFOAM tools available; run attempts are outside planner mode",
            "trust_boundary": (
                "No OpenFOAM mesh, checkMesh, yPlus, or forceCoeffs evidence exists "
                "unless the layer attempts run and write logs."
            ),
        },
    }


def run_track_b_su2_pressure(
    case_dir: Path,
    *,
    surface: SurfaceMesh,
    ref_area: float,
    ref_length: float,
    ref_origin: tuple[float, float, float],
    run_su2: bool,
    solver_command: str,
    threads: int,
    timeout_seconds: float,
    max_iterations: int,
) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=True)
    mesh_report = write_fullwing_pressure_mesh(surface, case_dir)
    cfg_path = case_dir / "su2_runtime.cfg"
    cfg_path.write_text(
        fullwing_pressure_cfg_text(
            ref_area=ref_area,
            ref_length=ref_length,
            ref_origin=ref_origin,
            velocity_mps=DEFAULT_VELOCITY_MPS,
            alpha_deg=0.0,
            max_iterations=max_iterations,
        ),
        encoding="utf-8",
    )
    marker_audit = audit_su2_case_markers(case_dir / "mesh.su2", cfg_path)
    mesh_report["marker_audit"] = marker_audit
    solver_report = _safe_run_solver(
        case_dir,
        run_su2=run_su2,
        solver_command=solver_command,
        threads=threads,
        timeout_seconds=timeout_seconds,
    )
    forces_report = _forces_breakdown_report(case_dir / "forces_breakdown.dat")
    force_summary = (
        summarize_split_marker_forces(_mapping(forces_report.get("parsed")))
        if forces_report.get("status") == "available"
        else _empty_force_summary()
    )
    report = {
        "schema_version": "wo006_track_b_su2_fullwing_pressure.v1",
        "route": "fullwing_su2_pressure_only_slip_wall",
        "case_dir": str(case_dir),
        "surface": {
            "marker_counts": surface.marker_counts(),
            "marker_area_m2": _surface_area_by_marker(surface),
            "metadata": surface.metadata,
        },
        "mesh": mesh_report,
        "runtime_cfg_path": str(cfg_path),
        "solver": solver_report,
        "forces_breakdown": forces_report,
        "force_summary": force_summary,
        "previous_halfwing_phase2_pressure_cd": PREVIOUS_HALF_WING_PRESSURE_CD,
        "engineering_assessment": {
            "scope": "full-wing pressure-only/slip-wall marker/reference sanity",
            "trust_boundary": (
                "This is not wall-resolved BL, not y+, not viscous drag truth, "
                "and not a replacement for OpenFOAM or mature external meshing."
            ),
        },
    }
    report["gate"] = evaluate_track_b_gate(report)
    write_json(case_dir / "su2_fullwing_pressure_report.json", report)
    return report


def write_fullwing_pressure_mesh(
    surface: SurfaceMesh,
    case_dir: Path | str,
    *,
    mesh_size: float = 4.0,
    wing_mesh_size: float = 0.75,
    farfield_mesh_size: float = 12.0,
) -> dict[str, Any]:
    import gmsh

    case_path = Path(case_dir)
    msh_path = case_path / "mesh.msh"
    su2_path = case_path / "mesh.su2"
    farfield = build_fullwing_farfield_box(surface, cref_m=_read_avl_reference(DEFAULT_AVL_PATH)["cref"])
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("wo006_fullwing_pressure")
        point_tags = [
            *[
                gmsh.model.geo.addPoint(x, y, z, wing_mesh_size)
                for x, y, z in surface.vertices
            ],
            *[
                gmsh.model.geo.addPoint(x, y, z, farfield_mesh_size)
                for x, y, z in farfield.vertices
            ],
        ]
        line_cache: dict[tuple[int, int], tuple[int, int, int]] = {}
        wing_surfaces_by_marker = _add_marked_mesh_surfaces(
            gmsh,
            surface.faces,
            vertices=surface.vertices,
            triangulation_policy="shorter_diagonal",
            point_tags=point_tags,
            line_cache=line_cache,
            node_offset=0,
        )
        farfield_surfaces_by_marker = _add_marked_mesh_surfaces(
            gmsh,
            farfield.faces,
            vertices=farfield.vertices,
            triangulation_policy="shorter_diagonal",
            point_tags=point_tags,
            line_cache=line_cache,
            node_offset=len(surface.vertices),
        )
        wing_surfaces = [
            tag for tags in wing_surfaces_by_marker.values() for tag in tags
        ]
        farfield_surfaces = [
            tag for tags in farfield_surfaces_by_marker.values() for tag in tags
        ]
        outer_loop = gmsh.model.geo.addSurfaceLoop(farfield_surfaces)
        inner_loop = gmsh.model.geo.addSurfaceLoop(wing_surfaces)
        fluid_volume = gmsh.model.geo.addVolume([outer_loop, inner_loop])
        gmsh.model.geo.synchronize()

        for marker, tags in {
            **wing_surfaces_by_marker,
            **farfield_surfaces_by_marker,
        }.items():
            group = gmsh.model.addPhysicalGroup(2, tags)
            gmsh.model.setPhysicalName(2, group, marker)
        fluid_group = gmsh.model.addPhysicalGroup(3, [fluid_volume])
        gmsh.model.setPhysicalName(3, fluid_group, "fluid")
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(mesh_size, wing_mesh_size))
        gmsh.option.setNumber("Mesh.MeshSizeMax", farfield_mesh_size)
        gmsh.option.setNumber("Mesh.Algorithm", 5)
        gmsh.option.setNumber("Mesh.Algorithm3D", 10)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.model.mesh.generate(3)
        mesh_quality = _mesh_quality_metrics(gmsh, farfield.vertices)
        gmsh.write(str(msh_path))
        gmsh.write(str(su2_path))
        marker_summary = parse_su2_marker_summary(su2_path)
        marker_names = set(marker_summary["markers"])
        required_markers_present = all(marker in marker_names for marker in REQUIRED_SU2_MARKERS)
        return {
            "status": "meshed",
            "mesh_path": str(msh_path),
            "su2_mesh_path": str(su2_path),
            "marker_summary": marker_summary,
            "required_markers_present": required_markers_present,
            "volume_element_type_counts": mesh_quality["volume_element_type_counts"],
            "volume_element_count": mesh_quality["volume_element_count"],
            "min_volume_quality": mesh_quality["min_volume_quality"],
            "non_positive_quality_count": mesh_quality["non_positive_quality_count"],
            "max_farfield_vertex_incident_volume_cells": mesh_quality[
                "max_farfield_vertex_incident_volume_cells"
            ],
            "mesh_quality_gate": _mesh_quality_gate(mesh_quality),
            "surface_marker_counts": surface.marker_counts(),
            "farfield_bounds": farfield.metadata,
        }
    finally:
        gmsh.finalize()


def build_fullwing_farfield_box(surface: SurfaceMesh, *, cref_m: float) -> SurfaceMesh:
    bounds = _bounds(surface.vertices)
    clearance_y = max(3.0 * cref_m, 0.05 * (bounds["y_max"] - bounds["y_min"]))
    x_min = bounds["x_min"] - 10.0 * cref_m
    x_max = bounds["x_max"] + 20.0 * cref_m
    y_min = bounds["y_min"] - clearance_y
    y_max = bounds["y_max"] + clearance_y
    z_min = bounds["z_min"] - 10.0 * cref_m
    z_max = bounds["z_max"] + 10.0 * cref_m
    vertices = [
        (x_min, y_min, z_min),
        (x_max, y_min, z_min),
        (x_max, y_max, z_min),
        (x_min, y_max, z_min),
        (x_min, y_min, z_max),
        (x_max, y_min, z_max),
        (x_max, y_max, z_max),
        (x_min, y_max, z_max),
    ]
    faces = [
        Face(nodes=(0, 3, 2, 1), marker="farfield"),
        Face(nodes=(4, 5, 6, 7), marker="farfield"),
        Face(nodes=(0, 1, 5, 4), marker="farfield"),
        Face(nodes=(1, 2, 6, 5), marker="farfield"),
        Face(nodes=(2, 3, 7, 6), marker="farfield"),
        Face(nodes=(3, 0, 4, 7), marker="farfield"),
    ]
    mesh = SurfaceMesh(
        vertices=vertices,
        faces=faces,
        metadata={
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_max,
            "z_min": z_min,
            "z_max": z_max,
            "upstream_clearance_chords": 10.0,
            "downstream_clearance_chords": 20.0,
            "vertical_clearance_chords": 10.0,
            "spanwise_clearance_each_side_m": clearance_y,
        },
    )
    validate_surface_mesh(
        mesh,
        allowed_markers=ALLOWED_SPLIT_MARKERS,
        required_markers=("farfield",),
    )
    return orient_surface_mesh_outward(mesh)


def evaluate_track_b_gate(report: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    mesh = _mapping(report.get("mesh"))
    solver = _mapping(report.get("solver"))
    history = _mapping(solver.get("history"))
    marker_audit = _mapping(mesh.get("marker_audit"))
    dual_quality = _mapping(solver.get("dual_control_volume_quality"))
    force_summary = _mapping(report.get("force_summary"))
    primary = _mapping(force_summary.get("primary"))
    diagnostics = _mapping(force_summary.get("diagnostic_total"))

    if mesh.get("status") != "meshed":
        blockers.append("track_b_mesh_not_meshed")
    if marker_audit.get("status") != "pass":
        blockers.append("track_b_marker_audit_not_pass")
    if mesh.get("required_markers_present") is not True:
        blockers.append("track_b_required_markers_missing")
    if _mapping(mesh.get("mesh_quality_gate")).get("status") != "pass":
        blockers.append("track_b_mesh_quality_not_pass")
    if solver.get("run_status") != "completed":
        blockers.append("track_b_solver_not_completed")
    if int(history.get("row_count") or 0) < 20:
        blockers.append("track_b_history_too_short")
    if _mapping(report.get("forces_breakdown")).get("status") != "available":
        blockers.append("track_b_forces_breakdown_missing")
    if dual_quality.get("status") != "available":
        blockers.append("track_b_dual_quality_missing")
    else:
        min_orthogonality = _float_or_none(dual_quality.get("min_orthogonality_deg"))
        max_aspect = _float_or_none(dual_quality.get("max_cv_face_area_aspect_ratio"))
        max_subvolume = _float_or_none(dual_quality.get("max_cv_sub_volume_ratio"))
        if min_orthogonality is None or min_orthogonality < 5.0:
            blockers.append("track_b_dual_min_orthogonality_pathological")
        if max_aspect is None or max_aspect > 20_000.0:
            blockers.append("track_b_dual_face_area_aspect_ratio_pathological")
        if max_subvolume is None or max_subvolume > 1_000_000.0:
            blockers.append("track_b_dual_sub_volume_ratio_pathological")

    cd_primary = _float_or_none(primary.get("cd"))
    cl_primary = _float_or_none(primary.get("cl"))
    if cd_primary is None:
        blockers.append("track_b_primary_cd_missing")
    elif not math.isfinite(cd_primary):
        blockers.append("track_b_primary_cd_non_finite")
    elif abs(cd_primary) > 0.08:
        blockers.append("track_b_primary_cd_pathological")
    else:
        delta = cd_primary - PREVIOUS_HALF_WING_PRESSURE_CD
        if abs(delta) > 0.02:
            blockers.append("track_b_primary_cd_not_broadly_consistent_with_halfwing_phase2")
        elif abs(delta) > 0.01:
            warnings.append("track_b_primary_cd_shift_needs_engineering_review")
    diagnostic_cd = _float_or_none(diagnostics.get("cd"))
    if (
        diagnostic_cd is not None
        and cd_primary is not None
        and abs(diagnostic_cd) > max(0.01, 0.5 * abs(cd_primary))
    ):
        warnings.append("track_b_diagnostic_patch_cd_large_relative_to_primary")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "cd_primary": cd_primary,
        "cl_primary": cl_primary,
        "cd_diagnostic_total": diagnostic_cd,
        "cd_total": _float_or_none(_mapping(force_summary.get("total")).get("cd")),
        "previous_halfwing_phase2_pressure_cd": PREVIOUS_HALF_WING_PRESSURE_CD,
    }


def build_tool_route_decision(
    track_a: Mapping[str, Any],
    track_b: Mapping[str, Any],
) -> dict[str, Any]:
    track_a_ran = not _mapping(track_a.get("engineering_assessment")).get("status") == "not_run_locally"
    track_b_gate = _mapping(track_b.get("gate"))
    track_b_mesh = _mapping(track_b.get("mesh"))
    track_b_marker_ok = (
        _mapping(track_b_mesh.get("marker_audit")).get("status") == "pass"
        and track_b_mesh.get("required_markers_present") is True
    )
    if track_a.get("status") == "ready_to_run":
        recommendation = "A_openfoam_as_active_cfd_route_after_local_toolchain_run"
    elif track_b_gate.get("status") == "pass" or track_b_marker_ok:
        recommendation = "B_mature_external_mesher_to_su2"
    else:
        recommendation = "C_commercial_or_mature_external_mesher"
    if track_b_gate.get("status") == "fail" and "track_b_marker_audit_not_pass" in track_b_gate.get(
        "blockers", []
    ):
        recommendation = "D_geometry_reference_correction_before_more_cfd"
    return {
        "schema_version": "wo006_tool_route_decision_verdict.v1",
        "openfoam_fullwing_rescue_meshed_and_ran": bool(track_a_ran),
        "openfoam_cd_primary_reasonable": None,
        "openfoam_diagnostic_patches_contaminate_total_cd": None,
        "su2_fullwing_pressure_sanity_pass": track_b_gate.get("status") == "pass",
        "su2_cd_primary": track_b_gate.get("cd_primary"),
        "su2_cd_total": track_b_gate.get("cd_total"),
        "recommendation": recommendation,
        "engineering_read": (
            "The custom partial-BL core-fill route is stopped. In this checkout, "
            "OpenFOAM cannot run because the executable toolchain is missing; SU2 "
            "full-wing pressure-only is the only live local route-decision run."
        ),
    }


def write_openfoam_case_scaffold(case_dir: Path, *, surface: SurfaceMesh, cref_m: float) -> None:
    tri_dir = case_dir / "constant" / "triSurface"
    system_dir = case_dir / "system"
    zero_dir = case_dir / "0"
    constant_dir = case_dir / "constant"
    for path in (tri_dir, system_dir, zero_dir, constant_dir):
        path.mkdir(parents=True, exist_ok=True)
    for marker in SPLIT_WING_MARKERS:
        write_ascii_stl(tri_dir / f"{marker}.stl", surface, marker=marker)
    farfield = build_fullwing_farfield_box(surface, cref_m=cref_m)
    (system_dir / "blockMeshDict").write_text(block_mesh_dict_text(farfield), encoding="utf-8")
    (system_dir / "snappyHexMeshDict").write_text(
        snappy_hex_mesh_dict_text(n_surface_layers=0),
        encoding="utf-8",
    )
    (system_dir / "controlDict").write_text(openfoam_control_dict_text(), encoding="utf-8")
    (constant_dir / "transportProperties").write_text(
        "nu [0 2 -1 0 0 0 0] 1.4607e-5;\n",
        encoding="utf-8",
    )
    (constant_dir / "turbulenceProperties").write_text(
        "simulationType RAS;\nRAS { RASModel SpalartAllmaras; turbulence on; printCoeffs on; }\n",
        encoding="utf-8",
    )
    (zero_dir / "U").write_text(openfoam_u_field_text(), encoding="utf-8")
    (zero_dir / "p").write_text(openfoam_p_field_text(), encoding="utf-8")


def block_mesh_dict_text(farfield: SurfaceMesh) -> str:
    vertices = farfield.vertices
    vertex_lines = "\n".join(f"    ({x:.9f} {y:.9f} {z:.9f})" for x, y, z in vertices)
    return f"""FoamFile
{{
    version 2.0;
    format ascii;
    class dictionary;
    object blockMeshDict;
}}
convertToMeters 1;
vertices
(
{vertex_lines}
);
blocks
(
    hex (0 1 2 3 4 5 6 7) (70 80 50) simpleGrading (1 1 1)
);
edges ();
boundary
(
    farfield
    {{
        type patch;
        faces
        (
            (0 3 2 1)
            (4 5 6 7)
            (0 1 5 4)
            (1 2 6 5)
            (2 3 7 6)
            (3 0 4 7)
        );
    }}
);
mergePatchPairs ();
"""


def snappy_hex_mesh_dict_text(*, n_surface_layers: int) -> str:
    geometry_entries = "\n".join(
        f"    {marker}.stl {{ type triSurfaceMesh; name {marker}; }}"
        for marker in SPLIT_WING_MARKERS
    )
    refinement_entries = "\n".join(
        f"        {marker} {{ level (2 3); patchInfo {{ type wall; }} }}"
        for marker in SPLIT_WING_MARKERS
    )
    layer_entries = "\n".join(
        f"        {marker} {{ nSurfaceLayers {n_surface_layers if marker in PRIMARY_FORCE_MARKERS else 0}; }}"
        for marker in SPLIT_WING_MARKERS
    )
    return f"""FoamFile
{{
    version 2.0;
    format ascii;
    class dictionary;
    object snappyHexMeshDict;
}}
castellatedMesh true;
snap true;
addLayers {'true' if n_surface_layers > 0 else 'false'};
geometry
{{
{geometry_entries}
}}
castellatedMeshControls
{{
    maxLocalCells 1000000;
    maxGlobalCells 8000000;
    minRefinementCells 0;
    nCellsBetweenLevels 3;
    features ();
    refinementSurfaces
    {{
{refinement_entries}
    }}
    resolveFeatureAngle 30;
    locationInMesh (0 0 5);
    allowFreeStandingZoneFaces true;
}}
snapControls
{{
    nSmoothPatch 3;
    tolerance 2.0;
    nSolveIter 30;
    nRelaxIter 5;
}}
addLayersControls
{{
    relativeSizes true;
    layers
    {{
{layer_entries}
    }}
    expansionRatio 1.2;
    finalLayerThickness 0.3;
    minThickness 0.05;
    nGrow 0;
    featureAngle 60;
    nRelaxIter 5;
    nSmoothSurfaceNormals 1;
    nSmoothNormals 3;
    nSmoothThickness 10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedianAxisAngle 90;
    nBufferCellsNoExtrude 0;
    nLayerIter 50;
}}
meshQualityControls {{}}
debug 0;
mergeTolerance 1e-6;
"""


def openfoam_control_dict_text() -> str:
    patches_primary = "(wing_upper wing_lower)"
    patches_all = "(wing_upper wing_lower tip_left tip_right te_wall closure_wall)"
    return f"""FoamFile
{{
    version 2.0;
    format ascii;
    class dictionary;
    object controlDict;
}}
application simpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime 500;
deltaT 1;
writeControl timeStep;
writeInterval 100;
functions
{{
    forceCoeffs_primary
    {{
        type forceCoeffs;
        libs ("libforces.so");
        patches {patches_primary};
        rho rhoInf;
        rhoInf 1.225;
        liftDir (0 0 1);
        dragDir (1 0 0);
        CofR (0.246276512 0 0);
        pitchAxis (0 1 0);
        magUInf 6.5;
        lRef 1.003721543;
        Aref 33.420059598;
    }}
    forceCoeffs_allDiagnostics
    {{
        type forceCoeffs;
        libs ("libforces.so");
        patches {patches_all};
        rho rhoInf;
        rhoInf 1.225;
        liftDir (0 0 1);
        dragDir (1 0 0);
        CofR (0.246276512 0 0);
        pitchAxis (0 1 0);
        magUInf 6.5;
        lRef 1.003721543;
        Aref 33.420059598;
    }}
    yPlus
    {{
        type yPlus;
        libs ("libfieldFunctionObjects.so");
        writeControl writeTime;
    }}
}}
"""


def openfoam_u_field_text() -> str:
    return """FoamFile
{
    version 2.0;
    format ascii;
    class volVectorField;
    object U;
}
dimensions [0 1 -1 0 0 0 0];
internalField uniform (6.5 0 0);
boundaryField { farfield { type freestreamVelocity; freestreamValue uniform (6.5 0 0); } }
"""


def openfoam_p_field_text() -> str:
    return """FoamFile
{
    version 2.0;
    format ascii;
    class volScalarField;
    object p;
}
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField { farfield { type freestreamPressure; freestreamValue uniform 0; } }
"""


def write_ascii_stl(path: Path, surface: SurfaceMesh, *, marker: str) -> None:
    triangles: list[tuple[tuple[float, float, float], ...]] = []
    for face in surface.faces:
        if face.marker != marker:
            continue
        nodes = list(face.nodes)
        if len(nodes) == 3:
            triangles.append(tuple(surface.vertices[node] for node in nodes))
        elif len(nodes) == 4:
            triangles.append(tuple(surface.vertices[node] for node in (nodes[0], nodes[1], nodes[2])))
            triangles.append(tuple(surface.vertices[node] for node in (nodes[0], nodes[2], nodes[3])))
    lines = [f"solid {marker}"]
    for tri in triangles:
        normal = _triangle_normal(*tri)
        lines.append(f"  facet normal {normal[0]:.9e} {normal[1]:.9e} {normal[2]:.9e}")
        lines.append("    outer loop")
        for vertex in tri:
            lines.append(f"      vertex {vertex[0]:.9e} {vertex[1]:.9e} {vertex[2]:.9e}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {marker}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_openfoam_summary(track_a: Mapping[str, Any]) -> str:
    attempts = "\n".join(
        f"- nSurfaceLayers={attempt['nSurfaceLayers']}: {attempt['status']} "
        f"({attempt['reason']})"
        for attempt in track_a.get("attempts", [])
    )
    return f"""# Track A - OpenFOAM Full-Wing Rescue Route

Status: `{track_a.get('status')}`

## Result

OpenFOAM did not mesh or run in this local environment. Required executables:
`blockMesh`, `snappyHexMesh`, `checkMesh`, and `simpleFoam`.

- mesh cell count: `not available`
- checkMesh summary: `not available`
- wing_upper/wing_lower layer coverage: `not available`
- yPlus min/mean/max: `not available`
- CD_primary / CL_primary: `not available`
- diagnostic patch CDs: `not available`
- force stability over last window: `not available`

## Attempts

{attempts}

Skipped layers after hard stop: `{track_a.get('skipped_layers')}`

## Scaffold

- case dir: `{track_a.get('case_dir')}`
- patches preserved: `{list(SPLIT_WING_MARKERS)}`
- primary layer patches: `{list(PRIMARY_FORCE_MARKERS)}`
- diagnostic no-layer patches: `{list(DIAGNOSTIC_FORCE_MARKERS)}`

## Engineering Boundary

No OpenFOAM `checkMesh`, yPlus, forceCoeffs, cell count, or force-stability evidence
exists yet. This is a toolchain blocker, not an aerodynamic result.
"""


def render_su2_summary(track_b: Mapping[str, Any]) -> str:
    gate = _mapping(track_b.get("gate"))
    force = _mapping(track_b.get("force_summary"))
    primary = _mapping(force.get("primary"))
    diagnostics = _mapping(force.get("diagnostics"))
    mesh = _mapping(track_b.get("mesh"))
    solver = _mapping(track_b.get("solver"))
    dual = _mapping(solver.get("dual_control_volume_quality"))
    diag_lines = "\n".join(
        f"- {marker}: CD `{_mapping(diagnostics.get(marker)).get('cd')}`, "
        f"CL `{_mapping(diagnostics.get(marker)).get('cl')}`"
        for marker in DIAGNOSTIC_FORCE_MARKERS
    )
    return f"""# Track B - SU2 Full-Wing Pressure-Only Sanity

Status: `{gate.get('status')}`

## Result

- case dir: `{track_b.get('case_dir')}`
- mesh cell count: `{mesh.get('volume_element_count')}`
- marker audit: `{_mapping(mesh.get('marker_audit')).get('status')}`
- SU2 run status: `{solver.get('run_status')}`
- dual quality: min orthogonality `{dual.get('min_orthogonality_deg')}`, max
  face-area aspect ratio `{dual.get('max_cv_face_area_aspect_ratio')}`, max
  sub-volume ratio `{dual.get('max_cv_sub_volume_ratio')}`
- primary CD: `{primary.get('cd')}`
- primary CL: `{primary.get('cl')}`
- total CD: `{_mapping(force.get('total')).get('cd')}`
- previous half-wing Phase 2 pressure-only CD: `{PREVIOUS_HALF_WING_PRESSURE_CD}`
- blockers: `{gate.get('blockers')}`
- warnings: `{gate.get('warnings')}`

## Diagnostic Patch Forces

{diag_lines}

## Engineering Boundary

This run checks full-wing geometry/reference/marker/force convention only. It is
pressure-only/slip-wall evidence, not wall-resolved viscous CD, yPlus, grid
ladder, or final aircraft drag truth.
"""


def render_tool_route_decision(
    decision: Mapping[str, Any],
    track_a: Mapping[str, Any],
    track_b: Mapping[str, Any],
) -> str:
    track_b_gate = _mapping(track_b.get("gate"))
    return f"""# WO-006 CFD Tool Route Decision

## Answers

1. Did OpenFOAM full-wing rescue route mesh and run?
   - `{decision.get('openfoam_fullwing_rescue_meshed_and_ran')}`. Local blocker:
     `{track_a.get('blockers')}`.
2. Is CD_primary reasonable or still pathological?
   - OpenFOAM: `not evaluated`.
   - SU2 pressure-only primary CD: `{track_b_gate.get('cd_primary')}` with gate
     `{track_b_gate.get('status')}`.
3. Are tip/TE/closure patches contaminating total CD?
   - OpenFOAM: `not evaluated`.
   - SU2 pressure-only diagnostic total CD:
     `{track_b_gate.get('cd_diagnostic_total')}`.
4. Does full-wing SU2 pressure-only sanity pass?
   - `{decision.get('su2_fullwing_pressure_sanity_pass')}`. Blockers:
     `{track_b_gate.get('blockers')}`.
5. Should we continue with A/B/C/D?
   - Recommendation: `{decision.get('recommendation')}`.

## Stopped Route

Do not continue the Phase 3 custom partial-BL SU2 hybrid core-fill route. That
means no discrete PLC core-fill, no receiver/cycle/cap patching, no large
discrete-shell Gmsh reconstruction, no meshpy/TetGen retries on the same `.poly`,
no SU2 hybrid writer repairs, and no new R-series / Phase-3 topology patches.

## Engineering Read

{decision.get('engineering_read')}

Test-passing software artifacts here are route-decision evidence only. They do
not sign off 3D viscous drag, BL yPlus, load paths, or aircraft performance.
"""


def _safe_run_solver(
    case_dir: Path,
    *,
    run_su2: bool,
    solver_command: str,
    threads: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    try:
        return _run_solver(
            case_dir,
            run_su2=run_su2,
            solver_command=solver_command,
            threads=threads,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - exercised by integration runs.
        log_path = case_dir / "solver.log"
        dual_quality = (
            parse_su2_dual_control_volume_quality(
                log_path.read_text(encoding="utf-8", errors="replace")
            )
            if log_path.exists()
            else {"status": "missing", "path": str(log_path)}
        )
        history_path = case_dir / "history.csv"
        history = parse_pressure_history(history_path) if history_path.exists() else None
        return {
            "run_requested": run_su2,
            "run_status": "failed",
            "exception": repr(exc),
            "history_path": str(history_path) if history_path.exists() else None,
            "history": history,
            "dual_control_volume_quality": dual_quality,
        }


def _manifest_track_payload(track: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "status": track.get("status") or _mapping(track.get("gate")).get("status"),
        "case_dir": track.get("case_dir"),
    }
    if "gate" in track:
        payload["gate"] = track["gate"]
    if "blockers" in track:
        payload["blockers"] = track["blockers"]
    return payload


def _fullwing_closure_sections(
    stations: Sequence[Station],
    source_transition_spans: Sequence[Mapping[str, Any]],
) -> set[int]:
    output: set[int] = set()
    for index, (left, right) in enumerate(zip(stations[:-1], stations[1:])):
        lo = min(abs(left.y), abs(right.y))
        hi = max(abs(left.y), abs(right.y))
        for span in source_transition_spans:
            if lo >= float(span["left_y_m"]) - 1.0e-9 and hi <= float(span["right_y_m"]) + 1.0e-9:
                output.add(index)
    return output


def _mirror_half_wing(half_stations: Sequence[Station]) -> list[Station]:
    mirrored = [
        Station(
            y=-station.y,
            x_le=station.x_le,
            z_le=station.z_le,
            chord=station.chord,
            twist_deg=station.twist_deg,
            airfoil_xz=station.airfoil_xz,
        )
        for station in reversed(half_stations[1:])
    ]
    return [*mirrored, *half_stations]


def _segment_marker(
    point_index: int,
    *,
    points_per_station: int,
    leading_edge_index: int,
    is_source_transition_te: bool,
) -> str:
    if point_index == points_per_station - 1:
        return "closure_wall" if is_source_transition_te else "te_wall"
    if point_index < leading_edge_index:
        return "wing_upper"
    return "wing_lower"


def _append_tip_cap(
    vertices: list[tuple[float, float, float]],
    faces: list[Face],
    boundary: list[int],
    *,
    marker: str,
    reverse: bool,
) -> None:
    center = _centroid([vertices[node] for node in boundary])
    center_index = len(vertices)
    vertices.append(center)
    ordered = list(reversed(boundary)) if reverse else list(boundary)
    for index, node in enumerate(ordered):
        next_node = ordered[(index + 1) % len(ordered)]
        faces.append(Face(nodes=(center_index, node, next_node), marker=marker))


def _centroid(points: Sequence[tuple[float, float, float]]) -> tuple[float, float, float]:
    scale = 1.0 / len(points)
    return (
        sum(point[0] for point in points) * scale,
        sum(point[1] for point in points) * scale,
        sum(point[2] for point in points) * scale,
    )


def _triangle_normal(
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
    norm = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
    if norm <= 0.0:
        return (0.0, 0.0, 0.0)
    return (normal[0] / norm, normal[1] / norm, normal[2] / norm)


def _forces_breakdown_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    parsed = parse_forces_breakdown_text(path.read_text(encoding="utf-8", errors="replace"))
    return {
        "status": "available",
        "path": str(path),
        "surface_names": sorted((parsed.get("surface_coefficients") or {}).keys()),
        "parsed": parsed,
    }


def _empty_force_summary() -> dict[str, Any]:
    return {
        "primary": {"cd": None, "cl": None},
        "diagnostics": {
            marker: {"cd": None, "cl": None} for marker in DIAGNOSTIC_FORCE_MARKERS
        },
        "diagnostic_total": {"cd": None, "cl": None},
        "total": {"cd": None, "cl": None},
        "missing_surfaces": list(SPLIT_WING_MARKERS),
    }


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--no-run-su2", action="store_true")
    parser.add_argument("--solver-command", default=DEFAULT_SOLVER_COMMAND)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--points-per-side", type=int, default=DEFAULT_POINTS_PER_SIDE)
    parser.add_argument("--spanwise-subdivisions", type=int, default=DEFAULT_SPANWISE_SUBDIVISIONS)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    args = parser.parse_args(argv)
    manifest = run_tool_route_decision(
        output_dir=args.output_dir,
        clean=not args.no_clean,
        run_su2=not args.no_run_su2,
        solver_command=args.solver_command,
        threads=args.threads,
        timeout_seconds=args.timeout_seconds,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        max_iterations=args.max_iterations,
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "track_a_status": manifest["track_a"]["status"],
                "track_b_status": manifest["track_b"]["status"],
                "recommendation": manifest["decision"]["recommendation"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
