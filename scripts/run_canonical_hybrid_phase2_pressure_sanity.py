#!/usr/bin/env python3
"""Run Phase 2 pressure-only sanity for the canonical hybrid half-wing CFD route."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
SCRIPT_DIR = REPO_ROOT / "scripts"
for path in (HPA_MESHING_SRC, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from diagnose_wo006j_drag_source import parse_forces_breakdown_text  # noqa: E402
from hpa_meshing.mesh_native.blackcat import (  # noqa: E402
    _resample_airfoil_loop,
    _subdivide_spanwise_stations,
)
from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    _add_marked_mesh_surfaces,
    _line_between,
)
from hpa_meshing.mesh_native.su2_structured import (  # noqa: E402
    audit_su2_case_markers,
    parse_su2_marker_summary,
)
from hpa_meshing.mesh_native.wing_surface import Face, Station, SurfaceMesh  # noqa: E402


CANDIDATE_ID = "current_avl_compromise_conservative_closed"
DEFAULT_SECTION_TABLE_PATH = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "production_inspection"
    / CANDIDATE_ID
    / "section_table.csv"
)
DEFAULT_AVL_PATH = DEFAULT_SECTION_TABLE_PATH.parent / f"{CANDIDATE_ID}.avl"
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "cfd_release_v0"
    / "pressure_sanity"
)
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR.parent / "manifest.yaml"
DEFAULT_SOLVER_COMMAND = "/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD"
DEFAULT_PRESSURE_POINTS_PER_SIDE = 6
DEFAULT_PRESSURE_SPANWISE_SUBDIVISIONS = 4
DEFAULT_PRESSURE_MAX_ITERATIONS = 500
REQUIRED_SURFACE_MARKERS = (
    "wing_upper",
    "wing_lower",
    "tip_wall",
    "te_wall",
    "closure_wall",
    "root_symmetry",
    "farfield",
)
EULER_WALL_MARKERS = ("wing_upper", "wing_lower", "tip_wall", "te_wall", "closure_wall")
PRIMARY_FORCE_MARKERS = ("wing_upper", "wing_lower")
MIN_DUAL_ORTHOGONALITY_DEG = 5.0
MAX_DUAL_FACE_AREA_ASPECT_RATIO = 20_000.0
MAX_DUAL_SUB_VOLUME_RATIO = 1_000_000.0


def build_phase2_pressure_surface(
    section_table_path: Path | str = DEFAULT_SECTION_TABLE_PATH,
    *,
    points_per_side: int = DEFAULT_PRESSURE_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_PRESSURE_SPANWISE_SUBDIVISIONS,
) -> SurfaceMesh:
    rows = _read_csv_dicts(Path(section_table_path))
    base_stations = _half_stations_from_rows(rows, points_per_side=points_per_side)
    stations = (
        base_stations
        if spanwise_subdivisions <= 1
        else _subdivide_spanwise_stations(base_stations, spanwise_subdivisions)
    )
    points_per_station = len(stations[0].airfoil_xz)
    leading_edge_index = points_per_side - 1
    vertices: list[tuple[float, float, float]] = []
    for station in stations:
        vertices.extend(_transform_station(station, twist_axis_x=0.25))

    source_transition_spans = _airfoil_source_transition_spans(rows)
    closure_sections = _closure_sections_for_spans(stations, source_transition_spans)
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
        [vid(len(stations) - 1, point) for point in range(points_per_station)],
    )
    return SurfaceMesh(
        vertices=vertices,
        faces=faces,
        metadata={
            "route": "canonical_hybrid_halfwing_v0",
            "phase_gate": "PRESSURE_SANITY_PASS",
            "side": "half",
            "root_symmetry_plane": "y=0",
            "pressure_mesh_recipe": (
                "coarse pressure-only mesh; avoids over-clustered tip-cap chordwise "
                "points and is not the viscous BL mesh recipe"
            ),
            "station_count": len(stations),
            "base_station_count": len(base_stations),
            "points_per_side": int(points_per_side),
            "points_per_station": points_per_station,
            "spanwise_subdivisions": int(spanwise_subdivisions),
            "source_transition_spans": source_transition_spans,
            "closure_section_indices": sorted(closure_sections),
            "force_monitoring_markers": list(PRIMARY_FORCE_MARKERS),
        },
    )


def pressure_sanity_cfg_text(
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
    return "\n".join(
        [
            "% Canonical hybrid half-wing Phase 2 pressure-only sanity.",
            "% Slip/Euler wall case; do not treat as viscous route-smoke.",
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
            f"MARKER_EULER= ( {', '.join(EULER_WALL_MARKERS)} )",
            "MARKER_SYM= ( root_symmetry )",
            "MARKER_FAR= ( farfield )",
            f"MARKER_MONITORING= ( {', '.join(PRIMARY_FORCE_MARKERS)} )",
            f"MARKER_PLOTTING= ( {', '.join(EULER_WALL_MARKERS)} )",
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


def evaluate_phase2_pressure_gate(report: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    solver = _mapping(report.get("solver"))
    history = _mapping(solver.get("history"))
    coeffs = _mapping(history.get("final_coefficients"))
    stability = _mapping(history.get("tail_stability"))
    mesh = _mapping(report.get("mesh"))
    marker_audit = _mapping(mesh.get("marker_audit"))
    mesh_gate = _mapping(mesh.get("mesh_quality_gate"))
    forces_breakdown = _mapping(report.get("forces_breakdown"))
    dual_quality = _mapping(solver.get("dual_control_volume_quality"))

    if solver.get("run_status") != "completed":
        blockers.append("pressure_solver_not_completed")
    if _int_or_zero(history.get("row_count")) < 100:
        blockers.append("pressure_history_too_short")
    if marker_audit.get("status") != "pass":
        blockers.append("pressure_marker_audit_not_pass")
    if mesh_gate.get("status") != "pass":
        blockers.append("pressure_mesh_quality_not_pass")
    if mesh.get("required_markers_present") is not True:
        blockers.append("pressure_required_markers_missing")
    if _float_or_none(mesh.get("max_farfield_vertex_incident_volume_cells")) is None:
        blockers.append("pressure_farfield_incident_count_missing")
    elif float(mesh["max_farfield_vertex_incident_volume_cells"]) > 200:
        blockers.append("farfield_vertex_incident_cell_count_exceeds_200")
    if forces_breakdown.get("status") != "available":
        blockers.append("pressure_forces_breakdown_missing")
    if dual_quality.get("status") != "available":
        blockers.append("pressure_su2_dual_quality_missing")
    else:
        min_orthogonality = _float_or_none(dual_quality.get("min_orthogonality_deg"))
        max_aspect = _float_or_none(dual_quality.get("max_cv_face_area_aspect_ratio"))
        max_sub_volume = _float_or_none(dual_quality.get("max_cv_sub_volume_ratio"))
        if min_orthogonality is None or min_orthogonality < MIN_DUAL_ORTHOGONALITY_DEG:
            blockers.append("pressure_su2_dual_min_orthogonality_pathological")
        if max_aspect is None or max_aspect > MAX_DUAL_FACE_AREA_ASPECT_RATIO:
            blockers.append("pressure_su2_dual_face_area_aspect_ratio_pathological")
        if max_sub_volume is None or max_sub_volume > MAX_DUAL_SUB_VOLUME_RATIO:
            blockers.append("pressure_su2_dual_sub_volume_ratio_pathological")

    cd = _float_or_none(coeffs.get("cd"))
    if cd is None:
        blockers.append("pressure_cd_missing")
    elif abs(cd) > 0.15:
        blockers.append("pressure_cd_exceeds_0p15")
    elif abs(cd) > 0.05:
        warnings.append("pressure_cd_high_but_below_route_smoke_blocker")
    cl_span = _float_or_none(stability.get("cl_relative_span"))
    cd_span = _float_or_none(stability.get("cd_relative_span"))
    if cl_span is None or cd_span is None or cl_span > 0.02 or cd_span > 0.02:
        blockers.append("pressure_force_window_not_stable")

    status = "pass" if not blockers else "fail"
    return {
        "status": status,
        "release_status": "PRESSURE_SANITY_PASS" if status == "pass" else None,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "final_coefficients": dict(coeffs),
        "stable_window": dict(stability),
    }


def mark_manifest_pressure_sanity_pass(
    manifest_path: Path | str,
    summary: Mapping[str, Any],
) -> None:
    path = Path(manifest_path)
    manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    statuses = list(manifest.get("passed_gate_statuses") or [])
    if "TOOLCHAIN_PASS" not in statuses:
        statuses.append("TOOLCHAIN_PASS")
    if "PRESSURE_SANITY_PASS" not in statuses:
        statuses.append("PRESSURE_SANITY_PASS")
    manifest["passed_gate_statuses"] = statuses
    manifest["next_required_gate_status"] = "ROUTE_SMOKE_PASS"
    manifest["phase2_pressure_sanity"] = {
        "status": "PRESSURE_SANITY_PASS",
        "report_path": summary.get("report_path"),
        "case_dir": summary.get("case_dir"),
        "mesh_recipe": _mapping(_mapping(summary.get("surface")).get("metadata")).get(
            "pressure_mesh_recipe"
        ),
    }
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def run_phase2_pressure_sanity(
    *,
    section_table_path: Path = DEFAULT_SECTION_TABLE_PATH,
    avl_path: Path = DEFAULT_AVL_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_su2: bool,
    update_manifest: bool = False,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    points_per_side: int = DEFAULT_PRESSURE_POINTS_PER_SIDE,
    spanwise_subdivisions: int = DEFAULT_PRESSURE_SPANWISE_SUBDIVISIONS,
    mesh_size: float = 4.0,
    wing_mesh_size: float = 0.75,
    farfield_mesh_size: float = 12.0,
    max_iterations: int = DEFAULT_PRESSURE_MAX_ITERATIONS,
    solver_command: str = DEFAULT_SOLVER_COMMAND,
    threads: int = 4,
    timeout_seconds: float = 1800.0,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    rows = _read_csv_dicts(section_table_path)
    ref_area_full = _read_avl_reference(avl_path)["sref"]
    ref_length = _read_avl_reference(avl_path)["cref"]
    ref_origin = _read_avl_moment_origin(avl_path)
    surface = build_phase2_pressure_surface(
        section_table_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    mesh_report = write_phase2_pressure_mesh(
        surface,
        output_dir,
        mesh_size=mesh_size,
        wing_mesh_size=wing_mesh_size,
        farfield_mesh_size=farfield_mesh_size,
    )
    cfg_path = output_dir / "su2_runtime.cfg"
    cfg_path.write_text(
        pressure_sanity_cfg_text(
            ref_area=0.5 * ref_area_full,
            ref_length=ref_length,
            ref_origin=ref_origin,
            velocity_mps=6.5,
            alpha_deg=0.0,
            max_iterations=max_iterations,
        ),
        encoding="utf-8",
    )
    marker_audit = audit_su2_case_markers(output_dir / "mesh.su2", cfg_path)
    mesh_report["marker_audit"] = marker_audit
    solver_report = _run_solver(
        output_dir,
        run_su2=run_su2,
        solver_command=solver_command,
        threads=threads,
        timeout_seconds=timeout_seconds,
    )
    forces_breakdown = _forces_breakdown_report(output_dir / "forces_breakdown.dat")
    report: dict[str, Any] = {
        "schema_version": "canonical_hybrid_phase2_pressure_sanity.v0",
        "route": "canonical_hybrid_halfwing_v0",
        "phase_gate": "PRESSURE_SANITY_PASS",
        "case_dir": str(output_dir),
        "section_table_path": str(section_table_path),
        "source_row_count": len(rows),
        "surface": {
            "marker_counts": surface.marker_counts(),
            "marker_area_m2": _surface_area_by_marker(surface),
            "metadata": surface.metadata,
        },
        "mesh": mesh_report,
        "runtime_cfg_path": str(cfg_path),
        "solver": solver_report,
        "forces_breakdown": forces_breakdown,
        "engineering_assessment": {
            "scope": "pressure_only_slip_wall_half_wing_sanity",
            "trust_boundary": (
                "This clears only pressure/geometry/marker/reference sanity. It is not "
                "a viscous BL route-smoke, y+ result, or grid-ladder result."
            ),
        },
        "elapsed_s": time.monotonic() - start,
    }
    gate = evaluate_phase2_pressure_gate(report)
    report["gate"] = gate
    report_path = output_dir / "pressure_sanity_report.json"
    md_path = output_dir / "pressure_sanity_report.md"
    report["report_path"] = str(report_path)
    report["markdown_report_path"] = str(md_path)
    if update_manifest and gate["status"] == "pass":
        mark_manifest_pressure_sanity_pass(manifest_path, report)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    return report


def write_phase2_pressure_mesh(
    surface: SurfaceMesh,
    case_dir: Path | str,
    *,
    mesh_size: float = 4.0,
    wing_mesh_size: float = 0.75,
    farfield_mesh_size: float = 12.0,
) -> dict[str, Any]:
    import gmsh

    case_path = Path(case_dir)
    case_path.mkdir(parents=True, exist_ok=True)
    msh_path = case_path / "mesh.msh"
    su2_path = case_path / "mesh.su2"
    bounds = _bounds(surface.vertices)
    farfield_vertices = _half_farfield_vertices(bounds)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("canonical_hybrid_phase2_pressure")
        point_tags = [
            *[
                gmsh.model.geo.addPoint(x, y, z, wing_mesh_size)
                for x, y, z in surface.vertices
            ],
            *[
                gmsh.model.geo.addPoint(x, y, z, farfield_mesh_size)
                for x, y, z in farfield_vertices
            ],
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
        farfield_offset = len(surface.vertices)
        farfield_surfaces = _add_farfield_and_symmetry_surfaces(
            gmsh,
            point_tags,
            line_cache,
            farfield_offset=farfield_offset,
            root_point_count=int(surface.metadata["points_per_station"]),
        )
        for marker, tags in farfield_surfaces.items():
            surfaces_by_marker.setdefault(marker, []).extend(tags)
        all_surfaces = [tag for tags in surfaces_by_marker.values() for tag in tags]
        fluid_loop = gmsh.model.geo.addSurfaceLoop(all_surfaces)
        fluid_volume = gmsh.model.geo.addVolume([fluid_loop])
        gmsh.model.geo.synchronize()
        for marker, tags in surfaces_by_marker.items():
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
        mesh_quality = _mesh_quality_metrics(gmsh, farfield_vertices)
        gmsh.write(str(msh_path))
        gmsh.write(str(su2_path))
        marker_summary = parse_su2_marker_summary(su2_path)
        marker_names = set(marker_summary["markers"])
        required_markers_present = all(marker in marker_names for marker in REQUIRED_SURFACE_MARKERS)
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
        }
    finally:
        gmsh.finalize()


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
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--points-per-side", type=int, default=DEFAULT_PRESSURE_POINTS_PER_SIDE)
    parser.add_argument(
        "--spanwise-subdivisions",
        type=int,
        default=DEFAULT_PRESSURE_SPANWISE_SUBDIVISIONS,
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_PRESSURE_MAX_ITERATIONS)
    parser.add_argument("--mesh-size", type=float, default=4.0)
    parser.add_argument("--wing-mesh-size", type=float, default=0.75)
    parser.add_argument("--farfield-mesh-size", type=float, default=12.0)
    args = parser.parse_args(argv)
    report = run_phase2_pressure_sanity(
        section_table_path=args.section_table,
        avl_path=args.avl,
        output_dir=args.output_dir,
        run_su2=args.run_su2,
        update_manifest=args.update_manifest,
        manifest_path=args.manifest,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        mesh_size=args.mesh_size,
        wing_mesh_size=args.wing_mesh_size,
        farfield_mesh_size=args.farfield_mesh_size,
        max_iterations=args.max_iterations,
        solver_command=args.solver_command,
        threads=args.threads,
        timeout_seconds=args.timeout_seconds,
    )
    gate = report["gate"]
    print(f"Phase 2 PRESSURE_SANITY_PASS gate: {gate['status']}")
    for blocker in gate["blockers"]:
        print(f"- {blocker}")
    return 0 if gate["status"] == "pass" else 1


def _half_stations_from_rows(
    rows: Sequence[Mapping[str, str]],
    *,
    points_per_side: int,
) -> list[Station]:
    airfoil_cache: dict[str, list[tuple[float, float]]] = {}
    stations: list[Station] = []
    for row in rows:
        dat_path = Path(row["airfoil_dat_path"])
        loop = airfoil_cache.get(str(dat_path))
        if loop is None:
            loop = _resample_airfoil_loop(
                _read_airfoil_dat(dat_path),
                points_per_side=points_per_side,
            )
            airfoil_cache[str(dat_path)] = loop
        stations.append(
            Station(
                y=_required_float(row, "y_m"),
                x_le=_required_float(row, "x_le_m", default=0.0),
                z_le=_required_float(row, "z_m"),
                chord=_required_float(row, "chord_m"),
                twist_deg=_required_float(row, "twist_deg"),
                airfoil_xz=loop,
            )
        )
    if abs(stations[0].y) > 1.0e-9:
        raise ValueError("Expected root station y_m to be zero")
    return stations


def _read_airfoil_dat(path: Path) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parts = raw_line.strip().replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            points.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if len(points) < 6:
        raise ValueError(f"Airfoil DAT has too few points: {path}")
    return points


def _transform_station(station: Station, twist_axis_x: float) -> list[tuple[float, float, float]]:
    theta = math.radians(station.twist_deg)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    twist_axis = station.chord * twist_axis_x
    transformed: list[tuple[float, float, float]] = []
    for x_norm, z_norm in station.airfoil_xz:
        x = station.chord * x_norm
        z = station.chord * z_norm
        x_rot = twist_axis + cos_theta * (x - twist_axis) + sin_theta * z
        z_rot = -sin_theta * (x - twist_axis) + cos_theta * z
        transformed.append((station.x_le + x_rot, station.y, station.z_le + z_rot))
    return transformed


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
) -> None:
    center = _centroid([vertices[node] for node in boundary])
    center_index = len(vertices)
    vertices.append(center)
    for index, node in enumerate(boundary):
        next_node = boundary[(index + 1) % len(boundary)]
        faces.append(Face(nodes=(center_index, node, next_node), marker="tip_wall"))


def _surface_area_by_marker(surface: SurfaceMesh) -> dict[str, float]:
    areas: dict[str, float] = {}
    for face in surface.faces:
        points = [surface.vertices[index] for index in face.nodes]
        if len(points) < 3:
            continue
        area = 0.0
        anchor = points[0]
        for left, right in zip(points[1:-1], points[2:]):
            area += _triangle_area(anchor, left, right)
        areas[face.marker] = areas.get(face.marker, 0.0) + area
    return {marker: areas[marker] for marker in sorted(areas)}


def _triangle_area(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return 0.5 * math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)


def _add_farfield_and_symmetry_surfaces(
    gmsh: Any,
    point_tags: list[int],
    line_cache: dict[tuple[int, int], tuple[int, int, int]],
    *,
    farfield_offset: int,
    root_point_count: int,
) -> dict[str, list[int]]:
    def fnode(index: int) -> int:
        return farfield_offset + index

    farfield_quads = [
        (fnode(0), fnode(3), fnode(2), fnode(1)),
        (fnode(4), fnode(5), fnode(6), fnode(7)),
        (fnode(3), fnode(7), fnode(6), fnode(2)),
        (fnode(0), fnode(4), fnode(7), fnode(3)),
        (fnode(1), fnode(2), fnode(6), fnode(5)),
    ]
    farfield_surfaces = [
        _add_plane_surface(gmsh, point_tags, line_cache, quad) for quad in farfield_quads
    ]
    outer_root_loop = gmsh.model.geo.addCurveLoop(
        [
            _line_between(gmsh, point_tags, line_cache, fnode(0), fnode(1)),
            _line_between(gmsh, point_tags, line_cache, fnode(1), fnode(5)),
            _line_between(gmsh, point_tags, line_cache, fnode(5), fnode(4)),
            _line_between(gmsh, point_tags, line_cache, fnode(4), fnode(0)),
        ]
    )
    inner_root_loop = gmsh.model.geo.addCurveLoop(
        [
            _line_between(
                gmsh,
                point_tags,
                line_cache,
                point,
                (point + 1) % root_point_count,
            )
            for point in range(root_point_count)
        ]
    )
    symmetry_surface = gmsh.model.geo.addPlaneSurface([outer_root_loop, inner_root_loop])
    return {"farfield": farfield_surfaces, "root_symmetry": [symmetry_surface]}


def _add_plane_surface(
    gmsh: Any,
    point_tags: list[int],
    line_cache: dict[tuple[int, int], tuple[int, int, int]],
    nodes: Sequence[int],
) -> int:
    curve_loop = gmsh.model.geo.addCurveLoop(
        [
            _line_between(gmsh, point_tags, line_cache, left, right)
            for left, right in zip(nodes, [*nodes[1:], nodes[0]])
        ]
    )
    return gmsh.model.geo.addPlaneSurface([curve_loop])


def _half_farfield_vertices(bounds: Mapping[str, float]) -> list[tuple[float, float, float]]:
    x_span = max(bounds["x_max"] - bounds["x_min"], 1.0)
    y_span = max(bounds["y_max"] - bounds["y_min"], 1.0)
    z_span = max(bounds["z_max"] - bounds["z_min"], 1.0)
    reference = max(x_span, y_span, z_span)
    x_min = bounds["x_min"] - 8.0 * x_span
    x_max = bounds["x_max"] + 12.0 * x_span
    y_min = 0.0
    y_max = bounds["y_max"] + 3.0 * y_span
    z_min = bounds["z_min"] - 3.0 * reference
    z_max = bounds["z_max"] + 3.0 * reference
    return [
        (x_min, y_min, z_min),
        (x_max, y_min, z_min),
        (x_max, y_max, z_min),
        (x_min, y_max, z_min),
        (x_min, y_min, z_max),
        (x_max, y_min, z_max),
        (x_max, y_max, z_max),
        (x_min, y_max, z_max),
    ]


def _mesh_quality_metrics(
    gmsh: Any,
    farfield_vertices: Sequence[tuple[float, float, float]],
) -> dict[str, Any]:
    element_types, element_tags, element_nodes = gmsh.model.mesh.getElements(3)
    type_counts = {str(int(kind)): len(tags) for kind, tags in zip(element_types, element_tags)}
    qualities: list[float] = []
    incident_counts: dict[int, int] = {}
    for tags, nodes in zip(element_tags, element_nodes):
        if len(tags):
            qualities.extend(float(value) for value in gmsh.model.mesh.getElementQualities(tags, "minSICN"))
        nodes_per_element = len(nodes) // max(1, len(tags))
        for element_index in range(len(tags)):
            unique_nodes = set(nodes[element_index * nodes_per_element : (element_index + 1) * nodes_per_element])
            for node in unique_nodes:
                incident_counts[int(node)] = incident_counts.get(int(node), 0) + 1
    farfield_node_tags = _nearest_node_tags(gmsh, farfield_vertices)
    max_farfield_incident = max((incident_counts.get(tag, 0) for tag in farfield_node_tags), default=0)
    finite_qualities = [quality for quality in qualities if math.isfinite(quality)]
    return {
        "volume_element_type_counts": type_counts,
        "volume_element_count": sum(type_counts.values()),
        "min_volume_quality": min(finite_qualities) if finite_qualities else None,
        "non_positive_quality_count": sum(1 for quality in finite_qualities if quality <= 0.0),
        "max_farfield_vertex_incident_volume_cells": max_farfield_incident,
    }


def _nearest_node_tags(
    gmsh: Any,
    targets: Sequence[tuple[float, float, float]],
) -> list[int]:
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    nodes = [
        (int(tag), (float(coords[3 * idx]), float(coords[3 * idx + 1]), float(coords[3 * idx + 2])))
        for idx, tag in enumerate(node_tags)
    ]
    nearest: list[int] = []
    for target in targets:
        tag, _ = min(nodes, key=lambda item: _distance3(item[1], target))
        nearest.append(tag)
    return nearest


def _mesh_quality_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if _float_or_none(metrics.get("min_volume_quality")) is None:
        blockers.append("volume_quality_missing")
    elif float(metrics["min_volume_quality"]) <= 0.0:
        blockers.append("non_positive_volume_quality")
    if _int_or_zero(metrics.get("non_positive_quality_count")) > 0:
        blockers.append("non_positive_volume_quality_count")
    if _int_or_zero(metrics.get("max_farfield_vertex_incident_volume_cells")) > 200:
        blockers.append("farfield_vertex_incident_cell_count_exceeds_200")
    return {"status": "pass" if not blockers else "fail", "blockers": blockers}


def parse_su2_dual_control_volume_quality(log_text: str) -> dict[str, Any]:
    patterns = {
        "orthogonality_angle_deg": r"Orthogonality Angle \(deg\.\)\|\s*([0-9.eE+-]+)\|\s*([0-9.eE+-]+)",
        "cv_face_area_aspect_ratio": r"CV Face Area Aspect Ratio\|\s*([0-9.eE+-]+)\|\s*([0-9.eE+-]+)",
        "cv_sub_volume_ratio": r"CV Sub-Volume Ratio\|\s*([0-9.eE+-]+)\|\s*([0-9.eE+-]+)",
    }
    values: dict[str, float] = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, log_text)
        if match is None:
            continue
        values[f"min_{name}"] = float(match.group(1))
        values[f"max_{name}"] = float(match.group(2))
    if len(values) != 6:
        return {"status": "missing", "available_metric_count": len(values)}
    return {
        "status": "available",
        "min_orthogonality_deg": values["min_orthogonality_angle_deg"],
        "max_orthogonality_deg": values["max_orthogonality_angle_deg"],
        "min_cv_face_area_aspect_ratio": values["min_cv_face_area_aspect_ratio"],
        "max_cv_face_area_aspect_ratio": values["max_cv_face_area_aspect_ratio"],
        "min_cv_sub_volume_ratio": values["min_cv_sub_volume_ratio"],
        "max_cv_sub_volume_ratio": values["max_cv_sub_volume_ratio"],
        "gate_thresholds": {
            "min_orthogonality_deg": MIN_DUAL_ORTHOGONALITY_DEG,
            "max_cv_face_area_aspect_ratio": MAX_DUAL_FACE_AREA_ASPECT_RATIO,
            "max_cv_sub_volume_ratio": MAX_DUAL_SUB_VOLUME_RATIO,
        },
    }


def _run_solver(
    case_dir: Path,
    *,
    run_su2: bool,
    solver_command: str,
    threads: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    if not run_su2:
        return {"run_requested": False, "run_status": "not_run", "reason": "run_su2_false"}
    solver = _resolve_solver(solver_command)
    worker_count = max(1, int(threads))
    command = [solver, "-t", str(worker_count), "su2_runtime.cfg"]
    solver_log = case_dir / "solver.log"
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(worker_count)
    start = time.monotonic()
    try:
        with solver_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                cwd=case_dir,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=timeout_seconds,
                env=env,
            )
    except subprocess.TimeoutExpired:
        dual_quality = _parse_dual_quality_log_file(solver_log)
        return {
            "run_requested": True,
            "run_status": "timeout",
            "timeout_seconds": timeout_seconds,
            "command": command,
            "solver_log_path": str(solver_log),
            "dual_control_volume_quality": dual_quality,
        }
    history_path = case_dir / "history.csv"
    history = parse_pressure_history(history_path) if history_path.exists() else None
    dual_quality = _parse_dual_quality_log_file(solver_log)
    return {
        "run_requested": True,
        "run_status": "completed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "elapsed_s": time.monotonic() - start,
        "command": command,
        "solver_log_path": str(solver_log),
        "history_path": str(history_path) if history_path.exists() else None,
        "history": history,
        "dual_control_volume_quality": dual_quality,
    }


def _parse_dual_quality_log_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    report = parse_su2_dual_control_volume_quality(
        path.read_text(encoding="utf-8", errors="replace")
    )
    report["path"] = str(path)
    return report


def parse_pressure_history(path: Path | str, *, tail_window: int = 100) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        raise ValueError(f"SU2 history has insufficient rows: {path}")
    header = [_normalize_history_key(value) for value in rows[0]]
    data = [
        {key: value.strip() for key, value in zip(header, row)}
        for row in rows[1:]
        if len(row) == len(header)
    ]
    final = data[-1]
    tail = data[-max(1, int(tail_window)) :]
    return {
        "path": str(path),
        "row_count": len(data),
        "final_iteration": _history_first_int(final, ("Inner_Iter", "ITER", "Iteration")),
        "final_coefficients": {
            "cl": _history_first_float(final, ("CL", "LIFT", "LIFT_COEFFICIENT")),
            "cd": _history_first_float(final, ("CD", "DRAG", "DRAG_COEFFICIENT")),
            "cmy": _history_first_float(final, ("CMz", "CMZ", "CMy", "CMY")),
        },
        "tail_stability": {
            "window_size": len(tail),
            "cl_relative_span": _relative_span(
                _history_first_float(row, ("CL", "LIFT", "LIFT_COEFFICIENT")) for row in tail
            ),
            "cd_relative_span": _relative_span(
                _history_first_float(row, ("CD", "DRAG", "DRAG_COEFFICIENT")) for row in tail
            ),
        },
    }


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


def _markdown_report(report: Mapping[str, Any]) -> str:
    gate = _mapping(report.get("gate"))
    coeffs = _mapping(gate.get("final_coefficients"))
    lines = [
        "# Canonical Hybrid Phase 2 Pressure Sanity",
        "",
        f"- route: `{report.get('route')}`",
        f"- phase gate: `{report.get('phase_gate')}`",
        f"- status: `{gate.get('status')}`",
        f"- release status: `{gate.get('release_status')}`",
        f"- blockers: `{gate.get('blockers')}`",
        f"- warnings: `{gate.get('warnings')}`",
        f"- final CL: `{coeffs.get('cl')}`",
        f"- final CD: `{coeffs.get('cd')}`",
        "",
        "## Engineering Boundary",
        "",
        str(_mapping(report.get("engineering_assessment")).get("trust_boundary")),
        "",
    ]
    return "\n".join(lines)


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _required_float(row: Mapping[str, str], key: str, default: float | None = None) -> float:
    raw = row.get(key)
    if raw in (None, "") and default is not None:
        return float(default)
    if raw in (None, ""):
        raise ValueError(f"Missing numeric field: {key}")
    return float(raw)


def _airfoil_source_transition_spans(rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for left, right in zip(rows[:-1], rows[1:]):
        if left.get("airfoil_id") != right.get("airfoil_id"):
            spans.append(
                {
                    "left_y_m": float(left["y_m"]),
                    "right_y_m": float(right["y_m"]),
                    "left_airfoil_id": left.get("airfoil_id"),
                    "right_airfoil_id": right.get("airfoil_id"),
                }
            )
    return spans


def _closure_sections_for_spans(
    stations: Sequence[Station],
    spans: Sequence[Mapping[str, Any]],
) -> set[int]:
    output: set[int] = set()
    for index, (left, right) in enumerate(zip(stations[:-1], stations[1:])):
        for span in spans:
            if left.y >= float(span["left_y_m"]) - 1.0e-9 and right.y <= float(span["right_y_m"]) + 1.0e-9:
                output.add(index)
    return output


def _read_avl_reference(path: Path) -> dict[str, float]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower().startswith("#sref"):
            parts = lines[index + 1].split()
            return {"sref": float(parts[0]), "cref": float(parts[1]), "bref": float(parts[2])}
    raise ValueError(f"Could not find AVL reference row in {path}")


def _read_avl_moment_origin(path: Path) -> tuple[float, float, float]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower().startswith("#xref"):
            parts = lines[index + 1].split()
            return float(parts[0]), float(parts[1]), float(parts[2])
    raise ValueError(f"Could not find AVL moment origin row in {path}")


def _bounds(vertices: Sequence[tuple[float, float, float]]) -> dict[str, float]:
    return {
        "x_min": min(vertex[0] for vertex in vertices),
        "x_max": max(vertex[0] for vertex in vertices),
        "y_min": min(vertex[1] for vertex in vertices),
        "y_max": max(vertex[1] for vertex in vertices),
        "z_min": min(vertex[2] for vertex in vertices),
        "z_max": max(vertex[2] for vertex in vertices),
    }


def _centroid(points: Sequence[tuple[float, float, float]]) -> tuple[float, float, float]:
    scale = 1.0 / len(points)
    return (
        sum(point[0] for point in points) * scale,
        sum(point[1] for point in points) * scale,
        sum(point[2] for point in points) * scale,
    )


def _distance3(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return math.sqrt(
        (left[0] - right[0]) ** 2
        + (left[1] - right[1]) ** 2
        + (left[2] - right[2]) ** 2
    )


def _resolve_solver(command: str) -> str:
    path = Path(command)
    if path.exists():
        return str(path)
    resolved = shutil.which(command)
    if resolved is None:
        raise FileNotFoundError(f"SU2 solver command not found: {command}")
    return resolved


def _normalize_history_key(value: str) -> str:
    return value.strip().strip('"').strip()


def _history_first_float(row: Mapping[str, str], keys: Iterable[str]) -> float | None:
    lookup = {key.upper(): value for key, value in row.items()}
    for key in keys:
        raw = lookup.get(key.upper())
        if raw is None:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return None


def _history_first_int(row: Mapping[str, str], keys: Iterable[str]) -> int | None:
    value = _history_first_float(row, keys)
    return None if value is None else int(value)


def _relative_span(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return None
    mean_abs = max(abs(sum(clean) / len(clean)), 1.0e-12)
    return (max(clean) - min(clean)) / mean_abs


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


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
