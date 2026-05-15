#!/usr/bin/env python3
"""Run WO-006 Baseline A structured-hexa OpenFOAM verification route.

This route deliberately bypasses snappyHexMesh, cfMesh, Gmsh, TetGen, meshpy,
and the retired partial-BL tetra/prism core-fill line.  It builds a closed
structured quadrilateral wing body surface, inflates that surface along smoothed
outward normals, connects radial layers with hexahedra, and writes OpenFOAM
``constant/polyMesh`` files directly.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for _path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    Face,
    Reference,
    Station,
    SurfaceMesh,
    _transform_station,
    orient_surface_mesh_outward,
    validate_surface_mesh,
)
from run_wo006_cfd_tool_route_decision import (  # noqa: E402
    ALLOWED_SPLIT_MARKERS,
    DIAGNOSTIC_FORCE_MARKERS,
    PRIMARY_FORCE_MARKERS,
    SPLIT_WING_MARKERS,
    _airfoil_source_transition_spans,
    _fullwing_closure_sections,
    _read_avl_moment_origin,
    _read_csv_dicts,
    _segment_marker,
)
from run_wo006_phase3_openfoam_route_smoke import (  # noqa: E402
    AIR_DENSITY,
    FORCE_FUNCTIONS,
    KINEMATIC_VISCOSITY,
    VELOCITY_MPS,
    detect_openfoam_tools,
    force_coeff_function_text,
    force_window_summary,
    fv_schemes_text,
    fv_solution_text,
    mesh_quality_dict_text,
    nut_field_text,
    nu_tilda_field_text,
    parse_boundary_patches,
    parse_check_mesh,
    parse_force_outputs,
    parse_yplus_outputs,
    p_field_text,
    run_case_command,
    transport_properties_text,
    turbulence_properties_text,
    u_field_text,
)
from run_wo006r1_go_baseline_a_cfd_bridge import (  # noqa: E402
    CANDIDATE_ID,
    DEFAULT_GEOMETRY_DIR,
    load_current_go_geometry,
)


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_structured_hexa_verification"
OPENFOAM_WRAPPER = shutil.which("openfoam") or "/opt/homebrew/bin/openfoam"
BOUNDARY_PATCH_ORDER = (
    "wing_upper",
    "wing_lower",
    "tip_left",
    "tip_right",
    "te_wall",
    "closure_wall",
    "farfield",
)
WALL_PATCHES = BOUNDARY_PATCH_ORDER[:-1]
REQUIRED_BODY_MARKERS = tuple(
    marker for marker in SPLIT_WING_MARKERS if marker != "closure_wall"
)
HEX_FACE_NODE_ORDERS = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)
XFOIL_SPANWISE_CD_TOTAL = 0.02602
PHASE2_SU2_PRESSURE_ONLY_CD = 0.017787
OPENFOAM_HIGH_YPLUS_CD_PRIMARY = 0.08141586
OPENFOAM_STRICT_SNAPPY_CD_PRIMARY = 0.07326929


Vertex = tuple[float, float, float]


@dataclass(frozen=True)
class StructuredHexaConfig:
    case_id: str
    n_span: int
    n_perimeter: int
    radial_layers: int
    near_wall_layers: int
    first_layer_height_m: float = 5.0e-5
    near_wall_growth: float = 1.12
    farfield_chords: float = 25.0
    normal_smoothing_iterations: int = 4
    outer_mapping: str = "normal"


@dataclass(frozen=True)
class StructuredWingGeometry:
    stations: tuple[Station, ...]
    reference: Reference
    source: dict[str, Any]


@dataclass(frozen=True)
class FaceRecord:
    nodes: tuple[int, ...]
    owner: int
    neighbour: int | None
    patch: str | None


@dataclass
class StructuredHexaMesh:
    points: list[Vertex]
    cells: list[tuple[int, int, int, int, int, int, int, int]]
    faces: list[tuple[int, ...]]
    owner: list[int]
    neighbour: list[int]
    boundary_ranges: dict[str, dict[str, int]]
    boundary_face_counts: dict[str, int]
    radial_distances_m: list[float]
    config: StructuredHexaConfig
    surface_metadata: dict[str, Any]
    nonmanifold_face_count: int = 0
    unmarked_boundary_face_count: int = 0

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    @property
    def face_count(self) -> int:
        return len(self.faces)

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def internal_face_count(self) -> int:
        return len(self.neighbour)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--openfoam", default=OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--skip-verification", action="store_true")
    parser.add_argument("--debug-iterations", type=int, default=40)
    parser.add_argument("--verification-iterations", type=int, default=80)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    args = parser.parse_args(argv)

    manifest = run_structured_hexa_verification(
        output_dir=args.output_dir,
        openfoam_command=args.openfoam,
        clean=args.clean,
        run_verification=not args.skip_verification,
        debug_iterations=args.debug_iterations,
        verification_iterations=args.verification_iterations,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(manifest["verdict"], indent=2))
    return 0 if manifest["verdict"]["status"] in {"solver_evidence_available", "hard_blocked"} else 1


def run_structured_hexa_verification(
    *,
    output_dir: Path,
    openfoam_command: str,
    clean: bool,
    run_verification: bool,
    debug_iterations: int,
    verification_iterations: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = output_dir / "openfoam_cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()

    manifest: dict[str, Any] = {
        "schema_version": "wo006_structured_hexa_verification.v1",
        "created_at_utc": _utc_now(),
        "route": "Baseline A body-fitted structured hexa inflated-wing OpenFOAM route",
        "output_dir": str(output_dir),
        "openfoam_command": openfoam_command,
        "tool_detection_inside_openfoam": detect_openfoam_tools(openfoam_command),
        "hard_prohibitions_observed": {
            "snappyHexMesh": "not_used",
            "cfMesh": "not_used",
            "gmsh": "not_used",
            "tetgen": "not_used",
            "meshpy": "not_used",
            "tetra_prism_core_fill": "not_used",
        },
        "artificial_unit": {},
        "debug_case": {},
        "verification_case": {},
    }

    artificial_config = StructuredHexaConfig(
        case_id="artificial_unit",
        n_span=4,
        n_perimeter=16,
        radial_layers=4,
        near_wall_layers=2,
        farfield_chords=3.0,
        normal_smoothing_iterations=1,
    )
    artificial_geometry = build_artificial_rectangular_wing_geometry(
        n_span=artificial_config.n_span,
        n_perimeter=artificial_config.n_perimeter,
    )
    artificial_surface = build_structured_body_surface(artificial_geometry)
    artificial_mesh = build_structured_hexa_mesh(
        artificial_surface,
        artificial_config,
        cref_m=artificial_geometry.reference.cref,
    )
    artificial_quality = audit_structured_hexa_mesh(artificial_mesh)
    manifest["artificial_unit"] = {
        "config": _config_dict(artificial_config),
        "mesh": _mesh_summary(artificial_mesh, artificial_quality),
    }
    if artificial_quality["status"] != "pass":
        manifest["verdict"] = _hard_blocked_verdict(
            "artificial_unit_mesh_failed",
            manifest,
        )
        write_all_reports(output_dir, manifest)
        return manifest

    baseline_debug = build_baseline_a_structured_geometry(n_span=32, n_perimeter=96)
    geometry_report = geometry_source_report_text(baseline_debug)
    (output_dir / "geometry_source_report.md").write_text(geometry_report, encoding="utf-8")
    (output_dir / "mesh_generator_design.md").write_text(
        mesh_generator_design_text(),
        encoding="utf-8",
    )

    debug_attempts: list[dict[str, Any]] = []
    debug_case: dict[str, Any] | None = None
    for debug_config in debug_attempt_configs():
        attempt = build_and_optionally_run_case(
            cases_dir / debug_config.case_id,
            geometry=baseline_debug,
            config=debug_config,
            openfoam_command=openfoam_command,
            max_iterations=debug_iterations,
            timeout_seconds=timeout_seconds,
            run_solver=True,
        )
        debug_attempts.append(attempt)
        if attempt.get("case_status") in {
            "solver_completed",
            "solver_failed_after_force_or_yplus",
        }:
            debug_case = attempt
            break
    if debug_case is None:
        debug_case = debug_attempts[-1]
    manifest["debug_attempts"] = debug_attempts
    manifest["debug_case"] = debug_case

    debug_status = debug_case.get("case_status")
    if debug_status not in {"solver_completed", "solver_failed_after_force_or_yplus"}:
        manifest["verdict"] = _hard_blocked_verdict("debug_mesh_or_solver_gate_failed", manifest)
        write_all_reports(output_dir, manifest)
        return manifest

    if run_verification:
        baseline_verification = build_baseline_a_structured_geometry(
            n_span=64,
            n_perimeter=160,
        )
        verification_config = StructuredHexaConfig(
            case_id="baseline_A_verification_structured_hexa",
            n_span=64,
            n_perimeter=160,
            radial_layers=80,
            near_wall_layers=40,
            farfield_chords=25.0,
            normal_smoothing_iterations=5,
        )
        verification_case = build_and_optionally_run_case(
            cases_dir / "baseline_verification_structured_hexa",
            geometry=baseline_verification,
            config=verification_config,
            openfoam_command=openfoam_command,
            max_iterations=verification_iterations,
            timeout_seconds=timeout_seconds,
            run_solver=True,
        )
        manifest["verification_case"] = verification_case
    else:
        manifest["verification_case"] = {
            "case_status": "not_run_by_cli_flag",
            "reason": "skip_verification_requested",
        }

    manifest["elapsed_s"] = time.monotonic() - start
    manifest["verdict"] = evaluate_structured_hexa_verdict(manifest)
    write_all_reports(output_dir, manifest)
    return manifest


def build_artificial_rectangular_wing_geometry(
    *,
    n_span: int,
    n_perimeter: int,
) -> StructuredWingGeometry:
    _require_surface_resolution(n_span, n_perimeter)
    airfoil = _synthetic_airfoil_loop(n_perimeter, thickness=0.12)
    stations: list[Station] = []
    for index in range(n_span + 1):
        y = -1.0 + 2.0 * index / n_span
        stations.append(
            Station(
                y=y,
                airfoil_xz=airfoil,
                chord=1.0,
                twist_deg=0.0,
                x_le=0.0,
                z_le=0.03 * abs(y),
            )
        )
    return StructuredWingGeometry(
        stations=tuple(stations),
        reference=Reference(sref_full=2.0, cref=1.0, bref_full=2.0),
        source={
            "type": "artificial_rectangular_wing",
            "purpose": "unit_topology_test_only",
        },
    )


def build_baseline_a_structured_geometry(
    *,
    n_span: int,
    n_perimeter: int,
    geometry_dir: Path = DEFAULT_GEOMETRY_DIR,
) -> StructuredWingGeometry:
    _require_surface_resolution(n_span, n_perimeter)
    base_full_span_cells = 16
    if n_span % base_full_span_cells != 0:
        raise ValueError(
            "Baseline A n_span must be divisible by 16 to preserve section-table intervals"
        )
    geometry = load_current_go_geometry(
        geometry_dir=geometry_dir,
        points_per_side=n_perimeter // 2 + 1,
        spanwise_subdivisions=n_span // base_full_span_cells,
    )
    if len(geometry.spec.wing_spec.stations) != n_span + 1:
        raise ValueError("Baseline A geometry station count does not match requested n_span")
    if len(geometry.spec.wing_spec.stations[0].airfoil_xz) != n_perimeter:
        raise ValueError("Baseline A airfoil perimeter count does not match request")
    return StructuredWingGeometry(
        stations=tuple(geometry.spec.wing_spec.stations),
        reference=geometry.reference,
        source={
            "type": "current_go_production_inspection_section_table",
            "candidate_id": CANDIDATE_ID,
            "geometry_dir": str(geometry.geometry_dir),
            "geometry_manifest_path": str(geometry.geometry_manifest_path),
            "section_table_path": str(geometry.section_table_path),
            "source_avl_path": str(geometry.source_avl_path),
            "moment_origin_m": list(geometry.moment_origin_m),
            "design_gross_mass_kg": geometry.design_gross_mass_kg,
            "base_half_station_count": geometry.base_half_station_count,
            "full_span_m": geometry.full_span_m,
            "half_span_m": geometry.half_span_m,
            "manifest_schema": geometry.manifest.get("schema_version"),
            "incidence_mode": geometry.manifest.get("incidence_mode"),
            "incidence_offset_deg_added_to_all_sections": geometry.manifest.get(
                "incidence_offset_deg_added_to_all_sections"
            ),
        },
    )


def build_structured_body_surface(geometry: StructuredWingGeometry) -> SurfaceMesh:
    stations = list(geometry.stations)
    n_span = len(stations) - 1
    n_perimeter = len(stations[0].airfoil_xz)
    _require_surface_resolution(n_span, n_perimeter)
    if any(len(station.airfoil_xz) != n_perimeter for station in stations):
        raise ValueError("All stations must share n_perimeter")

    vertices: list[Vertex] = []
    for station in stations:
        vertices.extend(_transform_station(station, 0.25))

    m = n_perimeter // 4
    leading_edge_index = n_perimeter // 2
    closure_sections: set[int] = set()
    source = geometry.source
    section_table_path = source.get("section_table_path")
    if section_table_path:
        rows = _read_csv_dicts(Path(str(section_table_path)))
        closure_sections = _fullwing_closure_sections(
            stations,
            _airfoil_source_transition_spans(rows),
        )

    faces: list[Face] = []

    def vid(section: int, point: int) -> int:
        return section * n_perimeter + (point % n_perimeter)

    for section_index in range(n_span):
        for point_index in range(n_perimeter):
            marker = _segment_marker(
                point_index,
                points_per_station=n_perimeter,
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

    _append_tip_quad_disk(
        vertices,
        faces,
        [vid(0, point) for point in range(n_perimeter)],
        side_subdivisions=m,
        marker="tip_left",
    )
    _append_tip_quad_disk(
        vertices,
        faces,
        [vid(n_span, point) for point in range(n_perimeter)],
        side_subdivisions=m,
        marker="tip_right",
    )

    surface = SurfaceMesh(
        vertices=vertices,
        faces=faces,
        metadata={
            "route": "wo006_structured_hexa_body_surface",
            "station_count": len(stations),
            "n_span": n_span,
            "n_perimeter": n_perimeter,
            "tip_cap_side_subdivisions": m,
            "tip_cap_topology": "coons_square_to_airfoil_quad_disk",
            "closure_section_indices": sorted(closure_sections),
            "source": source,
        },
    )
    validate_surface_mesh(
        surface,
        allowed_markers=ALLOWED_SPLIT_MARKERS,
        required_markers=REQUIRED_BODY_MARKERS,
    )
    oriented = orient_surface_mesh_outward(surface)
    validate_surface_mesh(
        oriented,
        allowed_markers=ALLOWED_SPLIT_MARKERS,
        required_markers=REQUIRED_BODY_MARKERS,
    )
    if any(len(face.nodes) != 4 for face in oriented.faces):
        raise ValueError("Structured hexa body surface requires quadrilateral faces only")
    return oriented


def build_structured_hexa_mesh(
    surface: SurfaceMesh,
    config: StructuredHexaConfig,
    *,
    cref_m: float,
) -> StructuredHexaMesh:
    if config.radial_layers < 1:
        raise ValueError("radial_layers must be positive")
    if config.first_layer_height_m <= 0.0:
        raise ValueError("first_layer_height_m must be positive")
    if config.farfield_chords <= 0.0:
        raise ValueError("farfield_chords must be positive")
    if any(len(face.nodes) != 4 for face in surface.faces):
        raise ValueError("All structured-hexa surface faces must be quads")

    normals = _smoothed_vertex_normals(surface, config.normal_smoothing_iterations)
    distances = radial_distances(
        radial_layers=config.radial_layers,
        near_wall_layers=config.near_wall_layers,
        first_layer_height_m=config.first_layer_height_m,
        near_wall_growth=config.near_wall_growth,
        farfield_distance_m=config.farfield_chords * cref_m,
    )
    point_count_per_level = len(surface.vertices)
    points: list[Vertex] = []
    if config.outer_mapping == "normal":
        for distance in distances:
            for vertex, normal in zip(surface.vertices, normals, strict=True):
                points.append(_vadd(vertex, _vscale(normal, distance)))
    else:
        if config.outer_mapping == "generic_radial":
            outer_targets = _generic_outer_targets(
                surface.vertices,
                normals,
                config.farfield_chords * cref_m,
            )
        elif config.outer_mapping == "section_scaled":
            outer_targets = _outer_targets(surface, normals, config.farfield_chords * cref_m)
        else:
            raise ValueError(f"Unknown outer_mapping: {config.outer_mapping}")
        first_height = distances[1] if len(distances) > 1 else distances[-1]
        first_layer_points = [
            _vadd(vertex, _vscale(normal, first_height))
            for vertex, normal in zip(surface.vertices, normals, strict=True)
        ]
        farfield_distance = distances[-1]
        for level, distance in enumerate(distances):
            if level == 0:
                points.extend(surface.vertices)
                continue
            if level == 1 or farfield_distance <= first_height:
                points.extend(first_layer_points)
                continue
            s = (distance - first_height) / (farfield_distance - first_height)
            for first_point, outer in zip(first_layer_points, outer_targets, strict=True):
                points.append(
                    _vadd(
                        _vscale(first_point, 1.0 - s),
                        _vscale(outer, s),
                    )
                )

    cells: list[tuple[int, int, int, int, int, int, int, int]] = []
    face_map: dict[tuple[int, ...], dict[str, Any]] = {}
    nonmanifold_face_count = 0
    orientation_flip_count = 0

    def level_node(level: int, surface_node: int) -> int:
        return level * point_count_per_level + surface_node

    for radial_index in range(config.radial_layers):
        for surface_face in surface.faces:
            inner = tuple(level_node(radial_index, node) for node in surface_face.nodes)
            outer = tuple(level_node(radial_index + 1, node) for node in surface_face.nodes)
            cell = (
                inner[0],
                inner[1],
                inner[2],
                inner[3],
                outer[0],
                outer[1],
                outer[2],
                outer[3],
            )
            oriented_cell = _best_positive_hex_orientation(points, inner, outer)
            if oriented_cell != cell:
                cell = oriented_cell
                orientation_flip_count += 1
            cell_index = len(cells)
            cells.append(cell)
            patch_by_face = {
                0: surface_face.marker if radial_index == 0 else None,
                1: "farfield" if radial_index == config.radial_layers - 1 else None,
            }
            for face_index, order in enumerate(HEX_FACE_NODE_ORDERS):
                face_nodes = tuple(cell[node_index] for node_index in order)
                key = tuple(sorted(face_nodes))
                patch = patch_by_face.get(face_index)
                existing = face_map.get(key)
                if existing is None:
                    face_map[key] = {
                        "nodes": face_nodes,
                        "owner": cell_index,
                        "neighbour": None,
                        "patch": patch,
                        "count": 1,
                    }
                    continue
                existing["count"] = int(existing["count"]) + 1
                if existing["neighbour"] is None:
                    existing["neighbour"] = cell_index
                    existing["patch"] = None
                else:
                    nonmanifold_face_count += 1

    records = [
        FaceRecord(
            nodes=tuple(payload["nodes"]),
            owner=int(payload["owner"]),
            neighbour=(
                None if payload["neighbour"] is None else int(payload["neighbour"])
            ),
            patch=None if payload["patch"] is None else str(payload["patch"]),
        )
        for payload in face_map.values()
    ]
    internal = [record for record in records if record.neighbour is not None]
    boundary_by_patch: dict[str, list[FaceRecord]] = {patch: [] for patch in BOUNDARY_PATCH_ORDER}
    unmarked_boundary_face_count = 0
    for record in records:
        if record.neighbour is not None:
            continue
        if record.patch not in boundary_by_patch:
            unmarked_boundary_face_count += 1
            continue
        boundary_by_patch[str(record.patch)].append(record)

    faces: list[tuple[int, ...]] = []
    owner: list[int] = []
    neighbour: list[int] = []
    boundary_ranges: dict[str, dict[str, int]] = {}
    for record in internal:
        faces.append(record.nodes)
        owner.append(record.owner)
        assert record.neighbour is not None
        neighbour.append(record.neighbour)
    for patch in BOUNDARY_PATCH_ORDER:
        start = len(faces)
        for record in boundary_by_patch[patch]:
            faces.append(record.nodes)
            owner.append(record.owner)
        boundary_ranges[patch] = {
            "startFace": start,
            "nFaces": len(boundary_by_patch[patch]),
        }

    mesh = StructuredHexaMesh(
        points=points,
        cells=cells,
        faces=faces,
        owner=owner,
        neighbour=neighbour,
        boundary_ranges=boundary_ranges,
        boundary_face_counts={
            patch: boundary_ranges[patch]["nFaces"] for patch in BOUNDARY_PATCH_ORDER
        },
        radial_distances_m=distances,
        config=config,
        surface_metadata=dict(surface.metadata),
        nonmanifold_face_count=nonmanifold_face_count,
        unmarked_boundary_face_count=unmarked_boundary_face_count,
    )
    mesh.surface_metadata["orientation_flip_count"] = orientation_flip_count
    return mesh


def audit_structured_hexa_mesh(mesh: StructuredHexaMesh) -> dict[str, Any]:
    volumes: list[float] = []
    aspect_ratios: list[float] = []
    non_positive_volume_count = 0
    min_signed_volume: float | None = None
    max_signed_volume: float | None = None
    for cell in mesh.cells:
        volume = _hex_signed_volume(mesh.points, cell)
        volumes.append(volume)
        if min_signed_volume is None or volume < min_signed_volume:
            min_signed_volume = volume
        if max_signed_volume is None or volume > max_signed_volume:
            max_signed_volume = volume
        if volume <= 0.0 or not math.isfinite(volume):
            non_positive_volume_count += 1
        aspect_ratios.append(_hex_aspect_ratio_proxy(mesh.points, cell))

    duplicate_point_count = _duplicate_point_count(mesh.points)
    missing_boundary_patch_count = sum(
        1 for patch in BOUNDARY_PATCH_ORDER if patch not in mesh.boundary_face_counts
    )
    blockers = []
    if non_positive_volume_count:
        blockers.append("non_positive_hex_volume")
    if duplicate_point_count:
        blockers.append("duplicate_points")
    if mesh.nonmanifold_face_count:
        blockers.append("nonmanifold_faces")
    if mesh.unmarked_boundary_face_count:
        blockers.append("unmarked_boundary_faces")
    if missing_boundary_patch_count:
        blockers.append("missing_boundary_patch")
    if len(mesh.owner) != len(mesh.faces):
        blockers.append("owner_face_count_mismatch")
    if len(mesh.neighbour) != mesh.internal_face_count:
        blockers.append("neighbour_internal_count_mismatch")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "node_count": mesh.point_count,
        "cell_count": mesh.cell_count,
        "face_count": mesh.face_count,
        "internal_face_count": mesh.internal_face_count,
        "boundary_face_counts": mesh.boundary_face_counts,
        "cell_type_counts": {"hex": mesh.cell_count},
        "first_layer_height_m": (
            mesh.radial_distances_m[1] - mesh.radial_distances_m[0]
            if len(mesh.radial_distances_m) > 1
            else None
        ),
        "radial_layer_distribution_m": mesh.radial_distances_m,
        "non_positive_volume_count": non_positive_volume_count,
        "duplicate_point_count": duplicate_point_count,
        "nonmanifold_face_count": mesh.nonmanifold_face_count,
        "unmarked_boundary_face_count": mesh.unmarked_boundary_face_count,
        "missing_boundary_patch_count": missing_boundary_patch_count,
        "min_signed_volume": min_signed_volume,
        "max_signed_volume": max_signed_volume,
        "volume_percentiles": _percentile_summary(volumes),
        "aspect_ratio_proxy_percentiles": _percentile_summary(aspect_ratios),
    }


def write_openfoam_poly_mesh(poly_mesh_dir: Path, mesh: StructuredHexaMesh) -> None:
    poly_mesh_dir.mkdir(parents=True, exist_ok=True)
    _write_openfoam_points(poly_mesh_dir / "points", mesh.points)
    _write_openfoam_faces(poly_mesh_dir / "faces", mesh.faces)
    _write_openfoam_label_list(poly_mesh_dir / "owner", "owner", mesh.owner)
    _write_openfoam_label_list(poly_mesh_dir / "neighbour", "neighbour", mesh.neighbour)
    _write_openfoam_boundary(poly_mesh_dir / "boundary", mesh.boundary_ranges)


def build_and_optionally_run_case(
    case_dir: Path,
    *,
    geometry: StructuredWingGeometry,
    config: StructuredHexaConfig,
    openfoam_command: str,
    max_iterations: int,
    timeout_seconds: float,
    run_solver: bool,
) -> dict[str, Any]:
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    surface = build_structured_body_surface(geometry)
    mesh = build_structured_hexa_mesh(surface, config, cref_m=geometry.reference.cref)
    custom_quality = audit_structured_hexa_mesh(mesh)
    write_openfoam_case(
        case_dir,
        mesh=mesh,
        geometry=geometry,
        config=config,
        custom_quality=custom_quality,
        max_iterations=max_iterations,
    )
    if custom_quality["status"] != "pass":
        return {
            "case_id": config.case_id,
            "case_dir": str(case_dir),
            "case_status": "custom_mesh_quality_failed",
            "config": _config_dict(config),
            "mesh": _mesh_summary(mesh, custom_quality),
            "commands": {},
        }

    run_result = run_openfoam_structured_case(
        case_dir,
        openfoam_command=openfoam_command,
        timeout_seconds=timeout_seconds,
        run_solver=run_solver,
    )
    return {
        "case_id": config.case_id,
        "case_dir": str(case_dir),
        "config": _config_dict(config),
        "mesh": _mesh_summary(mesh, custom_quality),
        **run_result,
    }


def debug_attempt_configs() -> list[StructuredHexaConfig]:
    common = {
        "n_span": 32,
        "n_perimeter": 96,
        "radial_layers": 40,
        "near_wall_layers": 20,
    }
    return [
        StructuredHexaConfig(
            case_id="debug_attempt_01_normal_smooth4_far20",
            **common,
            farfield_chords=20.0,
            normal_smoothing_iterations=4,
            outer_mapping="normal",
        ),
        StructuredHexaConfig(
            case_id="debug_attempt_02_normal_smooth0_far20",
            **common,
            farfield_chords=20.0,
            normal_smoothing_iterations=0,
            outer_mapping="normal",
        ),
        StructuredHexaConfig(
            case_id="debug_attempt_03_normal_smooth8_far20",
            **common,
            farfield_chords=20.0,
            normal_smoothing_iterations=8,
            outer_mapping="normal",
        ),
        StructuredHexaConfig(
            case_id="debug_attempt_04_generic_radial_smooth2_far20",
            **common,
            farfield_chords=20.0,
            normal_smoothing_iterations=2,
            outer_mapping="generic_radial",
        ),
        StructuredHexaConfig(
            case_id="debug_attempt_05_generic_radial_smooth4_far20",
            **common,
            farfield_chords=20.0,
            normal_smoothing_iterations=4,
            outer_mapping="generic_radial",
        ),
        StructuredHexaConfig(
            case_id="debug_attempt_06_section_scaled_far20",
            **common,
            farfield_chords=20.0,
            normal_smoothing_iterations=4,
            outer_mapping="section_scaled",
        ),
    ]


def write_openfoam_case(
    case_dir: Path,
    *,
    mesh: StructuredHexaMesh,
    geometry: StructuredWingGeometry,
    config: StructuredHexaConfig,
    custom_quality: Mapping[str, Any],
    max_iterations: int,
) -> None:
    system_dir = case_dir / "system"
    zero_dir = case_dir / "0"
    constant_dir = case_dir / "constant"
    for path in (system_dir, zero_dir, constant_dir):
        path.mkdir(parents=True, exist_ok=True)
    write_openfoam_poly_mesh(constant_dir / "polyMesh", mesh)

    ref_origin = _moment_origin_from_geometry(geometry)
    (system_dir / "controlDict").write_text(
        structured_control_dict_text(
            ref_area=geometry.reference.sref_full,
            ref_length=geometry.reference.cref,
            ref_origin=ref_origin,
            max_iterations=max_iterations,
        ),
        encoding="utf-8",
    )
    (system_dir / "fvSchemes").write_text(fv_schemes_text(), encoding="utf-8")
    (system_dir / "fvSolution").write_text(fv_solution_text(), encoding="utf-8")
    (system_dir / "meshQualityDict").write_text(
        mesh_quality_dict_text(),
        encoding="utf-8",
    )
    (constant_dir / "transportProperties").write_text(
        transport_properties_text(),
        encoding="utf-8",
    )
    (constant_dir / "turbulenceProperties").write_text(
        turbulence_properties_text(),
        encoding="utf-8",
    )
    (zero_dir / "U").write_text(u_field_text(), encoding="utf-8")
    (zero_dir / "p").write_text(p_field_text(), encoding="utf-8")
    (zero_dir / "nuTilda").write_text(nu_tilda_field_text(), encoding="utf-8")
    (zero_dir / "nut").write_text(nut_field_text(), encoding="utf-8")
    _write_json(
        case_dir / "structured_hexa_mesh_metadata.json",
        {
            "schema_version": "wo006_structured_hexa_mesh_metadata.v1",
            "config": _config_dict(config),
            "geometry_source": geometry.source,
            "reference": {
                "Sref": geometry.reference.sref_full,
                "Cref": geometry.reference.cref,
                "Bref": geometry.reference.bref_full,
            },
            "mesh": _mesh_summary(mesh, custom_quality),
        },
    )


def run_openfoam_structured_case(
    case_dir: Path,
    *,
    openfoam_command: str,
    timeout_seconds: float,
    run_solver: bool,
) -> dict[str, Any]:
    run_dir = Path("/tmp/hpa_mdo_structured_hexa_openfoam") / case_dir.name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    shutil.copytree(case_dir, run_dir)
    commands = [("checkMesh", "checkMesh -meshQuality")]
    if run_solver:
        commands.extend(
            [
                ("simpleFoam", "simpleFoam"),
                ("postProcess_yPlus", "simpleFoam -postProcess -func yPlus -latestTime"),
            ]
        )
    reports: dict[str, Any] = {}
    for key, command in commands:
        completed = run_case_command(
            run_dir,
            openfoam_command=openfoam_command,
            command=command,
            log_name=f"log.{key}",
            timeout_seconds=timeout_seconds if key == "simpleFoam" else 240.0,
        )
        reports[key] = {
            "command": command,
            "returncode": completed.returncode,
            "timed_out": completed.timed_out,
            "log": str(case_dir / f"log.{key}"),
            "execution_log": str(run_dir / f"log.{key}"),
        }
        if completed.returncode != 0 or completed.timed_out:
            break
        if key == "checkMesh":
            immediate_check = parse_check_mesh(run_dir / f"log.{key}")
            if immediate_check.get("status") != "pass":
                break

    shutil.copytree(run_dir, case_dir, dirs_exist_ok=True)
    mesh_quality = parse_check_mesh(case_dir / "log.checkMesh")
    forces = parse_force_outputs(case_dir)
    pressure_viscous = parse_pressure_viscous_force_outputs(case_dir)
    yplus = parse_yplus_outputs(case_dir)
    force_stability = force_window_summary(
        forces.get("functions", {}).get("primary", {}).get("rows", [])
    )
    boundary_patches = parse_boundary_patches(case_dir / "constant" / "polyMesh" / "boundary")
    case_status = classify_structured_case_status(reports, mesh_quality, forces, yplus)
    return {
        "execution_dir_without_spaces": str(run_dir),
        "commands": reports,
        "checkMesh": {
            **mesh_quality,
            "boundary_patches": boundary_patches,
        },
        "forces": forces,
        "pressure_viscous_split": pressure_viscous,
        "yPlus": yplus,
        "force_stability_final_window": force_stability,
        "case_status": case_status,
    }


def classify_structured_case_status(
    reports: Mapping[str, Any],
    mesh_quality: Mapping[str, Any],
    forces: Mapping[str, Any],
    yplus: Mapping[str, Any],
) -> str:
    check = reports.get("checkMesh", {})
    if check.get("returncode") != 0 or check.get("timed_out"):
        return "checkmesh_command_failed"
    if mesh_quality.get("status") != "pass":
        return "checkmesh_failed"
    simple = reports.get("simpleFoam")
    if simple is None:
        return "checkmesh_only_pass"
    if simple.get("returncode") != 0 or simple.get("timed_out"):
        return "solver_failed"
    summary = forces.get("summary", {})
    if summary.get("CD_primary") is None or summary.get("CL_primary") is None:
        return "solver_failed_after_force_or_yplus"
    if yplus.get("status") != "available":
        return "solver_failed_after_force_or_yplus"
    return "solver_completed"


def structured_control_dict_text(
    *,
    ref_area: float,
    ref_length: float,
    ref_origin: tuple[float, float, float],
    max_iterations: int,
) -> str:
    function_blocks: list[str] = []
    for name, patches in FORCE_FUNCTIONS.items():
        function_blocks.append(
            force_coeff_function_text(
                name=f"forceCoeffs_{name}",
                patches=patches,
                ref_area=ref_area,
                ref_length=ref_length,
                ref_origin=ref_origin,
            )
        )
        function_blocks.append(
            force_function_text(
                name=f"forces_{name}",
                patches=patches,
                ref_origin=ref_origin,
            )
        )
    functions = "\n".join(function_blocks)
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}
application     simpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {int(max_iterations)};
deltaT          1;
writeControl    timeStep;
writeInterval   20;
purgeWrite      0;
functions
{{
{functions}
    yPlus
    {{
        type            yPlus;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeInterval   20;
    }}
}}
"""


def force_function_text(
    *,
    name: str,
    patches: Sequence[str],
    ref_origin: tuple[float, float, float],
) -> str:
    patch_list = " ".join(patches)
    return f"""    {name}
    {{
        type            forces;
        libs            ("libforces.so");
        patches         ({patch_list});
        rho             rhoInf;
        rhoInf          {AIR_DENSITY:.9g};
        CofR            ({ref_origin[0]:.9f} {ref_origin[1]:.9f} {ref_origin[2]:.9f});
        writeControl    timeStep;
        writeInterval   1;
        log             true;
    }}
"""


def parse_pressure_viscous_force_outputs(case_dir: Path) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    q_ref = 0.5 * AIR_DENSITY * VELOCITY_MPS * VELOCITY_MPS
    ref_area = _read_ref_area_from_control_dict(case_dir / "system" / "controlDict")
    for name in FORCE_FUNCTIONS:
        rows = _read_force_rows(case_dir / "postProcessing" / f"forces_{name}")
        last = rows[-1] if rows else None
        split = None
        if last is not None and ref_area:
            split = {
                "CD_pressure": last["pressure_force"][0] / (q_ref * ref_area),
                "CD_viscous": last["viscous_force"][0] / (q_ref * ref_area),
                "CL_pressure": last["pressure_force"][2] / (q_ref * ref_area),
                "CL_viscous": last["viscous_force"][2] / (q_ref * ref_area),
            }
            split["CD_pressure_plus_viscous"] = split["CD_pressure"] + split["CD_viscous"]
            split["CL_pressure_plus_viscous"] = split["CL_pressure"] + split["CL_viscous"]
        outputs[name] = {
            "status": "available" if rows else "missing",
            "row_count": len(rows),
            "last": last,
            "split": split,
        }
    return {
        "status": (
            "available"
            if outputs.get("primary", {}).get("split") is not None
            else "missing"
        ),
        "note": "OpenFOAM forces pressure/viscous columns, not forceCoeffs front/rear Cd(f)/Cd(r).",
        "functions": outputs,
        "primary": outputs.get("primary", {}).get("split"),
        "total": outputs.get("total", {}).get("split"),
    }


def _read_force_rows(root: Path) -> list[dict[str, Any]]:
    files = sorted(root.glob("*/*.dat"))
    if not files:
        return []
    path = files[-1]
    rows: list[dict[str, Any]] = []
    tuple_pattern = re.compile(r"\(([-+0-9.eE ]+)\)")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = stripped.split(maxsplit=1)
        if len(tokens) < 2:
            continue
        try:
            time_value = float(tokens[0])
        except ValueError:
            continue
        groups = tuple_pattern.findall(tokens[1])
        if len(groups) < 6:
            continue
        vectors = [_parse_vector_group(group) for group in groups[:6]]
        if any(vector is None for vector in vectors):
            continue
        rows.append(
            {
                "time": time_value,
                "pressure_force": vectors[0],
                "viscous_force": vectors[1],
                "porous_force": vectors[2],
                "pressure_moment": vectors[3],
                "viscous_moment": vectors[4],
                "porous_moment": vectors[5],
            }
        )
    return rows


def _parse_vector_group(group: str) -> tuple[float, float, float] | None:
    values = group.split()
    if len(values) != 3:
        return None
    try:
        vector = tuple(float(value) for value in values)
    except ValueError:
        return None
    if any(not math.isfinite(value) for value in vector):
        return None
    return vector  # type: ignore[return-value]


def _read_ref_area_from_control_dict(path: Path) -> float | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"\bAref\s+([-+0-9.eE]+)", text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0.0 else None


def evaluate_structured_hexa_verdict(manifest: Mapping[str, Any]) -> dict[str, Any]:
    verification = _mapping(manifest.get("verification_case"))
    debug = _mapping(manifest.get("debug_case"))
    candidate = verification if verification.get("case_status") else debug
    if verification.get("case_status") == "solver_completed":
        basis = "verification"
        case = verification
    elif debug.get("case_status") == "solver_completed":
        basis = "debug_only"
        case = debug
    else:
        return _hard_blocked_verdict("no_structured_hexa_solver_evidence", manifest)

    forces = _mapping(case.get("forces"))
    summary = _mapping(forces.get("summary"))
    yplus = _mapping(case.get("yPlus"))
    yplus_summary = summarize_primary_yplus(yplus)
    split = _mapping(case.get("pressure_viscous_split"))
    cd_primary = _float_or_none(summary.get("CD_primary"))
    cl_primary = _float_or_none(summary.get("CL_primary"))
    cd_total = _float_or_none(summary.get("CD_total"))
    wall_regime = classify_wall_regime(yplus_summary)
    return {
        "status": "solver_evidence_available",
        "basis": basis,
        "case_id": case.get("case_id"),
        "valid_mesh_generated": _mapping(case.get("mesh")).get("status") == "pass",
        "checkMesh_passed": _mapping(case.get("checkMesh")).get("status") == "pass",
        "solver_ran": case.get("case_status") == "solver_completed",
        "CD_primary": cd_primary,
        "CL_primary": cl_primary,
        "CD_total": cd_total,
        "diagnostic_CD_sum": summary.get("CD_diagnostic_sum"),
        "pressure_viscous_primary": split.get("primary"),
        "yPlus": yplus_summary,
        "wall_regime": wall_regime,
        "supports_xfoil_cd": (
            _xfoil_comparison_status(cd_primary) if cd_primary is not None else "not_evaluable"
        ),
        "good_enough_for_engineering_team_cfd_verification": (
            basis == "verification"
            and wall_regime == "wall_resolved_attempt"
            and cd_primary is not None
        ),
        "engineering_boundary": (
            "Structured all-hexa evidence can only be treated as CFD verification "
            "if the verification mesh ran and yPlus is in the wall-resolved target. "
            "Otherwise it remains route/debug evidence."
        ),
    }


def _hard_blocked_verdict(reason: str, manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "hard_blocked",
        "reason": reason,
        "valid_mesh_generated": _mapping(manifest.get("debug_case")).get("case_status")
        in {"checkmesh_only_pass", "solver_completed", "solver_failed_after_force_or_yplus"},
        "checkMesh_passed": _mapping(_mapping(manifest.get("debug_case")).get("checkMesh")).get(
            "status"
        )
        == "pass",
        "solver_ran": _mapping(manifest.get("debug_case")).get("case_status")
        == "solver_completed",
        "engineering_boundary": (
            "This is a hard structured-route blocker, not CFD drag truth. The verdict "
            "does not authorize returning to snappy/cfMesh/Gmsh/TetGen/core-fill routes."
        ),
    }


def write_all_reports(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    _write_json(output_dir / "structured_hexa_manifest.json", manifest)
    (output_dir / "artificial_unit_mesh_report.md").write_text(
        artificial_unit_mesh_report_text(manifest),
        encoding="utf-8",
    )
    (output_dir / "baseline_debug_mesh_report.md").write_text(
        debug_mesh_report_text(manifest),
        encoding="utf-8",
    )
    (output_dir / "verification_mesh_quality_report.md").write_text(
        case_mesh_report_text(
            "Verification Mesh Quality Report",
            _mapping(manifest.get("verification_case")),
        ),
        encoding="utf-8",
    )
    (output_dir / "openfoam_solver_report.md").write_text(
        solver_report_text(manifest),
        encoding="utf-8",
    )
    (output_dir / "force_breakdown_report.md").write_text(
        force_breakdown_report_text(manifest),
        encoding="utf-8",
    )
    (output_dir / "yplus_report.md").write_text(
        yplus_report_text(manifest),
        encoding="utf-8",
    )
    (output_dir / "pressure_viscous_split_report.md").write_text(
        pressure_viscous_split_report_text(manifest),
        encoding="utf-8",
    )
    (output_dir / "cfd_vs_xfoil_comparison_report.md").write_text(
        cfd_vs_xfoil_comparison_report_text(manifest),
        encoding="utf-8",
    )
    (output_dir / "phase3_structured_hexa_verdict.md").write_text(
        phase3_structured_hexa_verdict_text(manifest),
        encoding="utf-8",
    )
    (output_dir / "rerun_instructions.md").write_text(
        rerun_instructions_text(output_dir),
        encoding="utf-8",
    )
    if not (output_dir / "geometry_source_report.md").exists():
        (output_dir / "geometry_source_report.md").write_text(
            "Geometry was not loaded before the hard blocker.\n",
            encoding="utf-8",
        )
    if not (output_dir / "mesh_generator_design.md").exists():
        (output_dir / "mesh_generator_design.md").write_text(
            mesh_generator_design_text(),
            encoding="utf-8",
        )


def geometry_source_report_text(geometry: StructuredWingGeometry) -> str:
    source = geometry.source
    return f"""# Geometry Source Report

- candidate: `{source.get('candidate_id')}`
- geometry source type: `{source.get('type')}`
- geometry directory: `{source.get('geometry_dir')}`
- geometry manifest: `{source.get('geometry_manifest_path')}`
- section table: `{source.get('section_table_path')}`
- source AVL: `{source.get('source_avl_path')}`
- station count: `{len(geometry.stations)}`
- full span: `{geometry.reference.bref_full:.9f}` m
- reference area Sref: `{geometry.reference.sref_full:.9f}` m2
- reference chord Cref: `{geometry.reference.cref:.9f}` m
- incidence mode: `{source.get('incidence_mode')}`
- incidence offset in export: `{source.get('incidence_offset_deg_added_to_all_sections')}` deg

This route stops if these authority files cannot be loaded. It does not invent a
replacement wing, change AOA, or modify the Baseline A external geometry to force
drag agreement.
"""


def mesh_generator_design_text() -> str:
    return """# Mesh Generator Design

The generator creates a closed quadrilateral body surface for the full Baseline A
wing, including split upper/lower wall patches, TE/closure strips, and structured
quad tip disks. It then computes smoothed outward vertex normals and inflates the
closed surface to a body-like farfield with the same topology. Radial layers are
connected face-by-face, so every volume cell is a hexahedron.

No automatic layer insertion, unstructured core fill, snappyHexMesh, cfMesh,
Gmsh, TetGen, meshpy, receiver caps, or cycle caps are used. OpenFOAM polyMesh is
written directly as points, faces, owner, neighbour, and boundary files.

The first cell height is explicit in the radial distribution. The default
Baseline debug route uses n_span=32, n_perimeter=96, radial_layers=40. The
verification route uses n_span=64, n_perimeter=160, radial_layers=80.
"""


def artificial_unit_mesh_report_text(manifest: Mapping[str, Any]) -> str:
    unit = _mapping(manifest.get("artificial_unit"))
    mesh = _mapping(unit.get("mesh"))
    return f"""# Artificial Unit Mesh Report

- status: `{mesh.get('status')}`
- config: `{unit.get('config')}`
- nodes: `{mesh.get('node_count')}`
- cells: `{mesh.get('cell_count')}`
- faces: `{mesh.get('face_count')}`
- boundary face counts: `{mesh.get('boundary_face_counts')}`
- non-positive hex volumes: `{mesh.get('non_positive_volume_count')}`
- nonmanifold faces: `{mesh.get('nonmanifold_face_count')}`

This is the required tiny artificial rectangular-wing unit topology check before
Baseline A case generation.
"""


def case_mesh_report_text(title: str, case: Mapping[str, Any]) -> str:
    mesh = _mapping(case.get("mesh"))
    check = _mapping(case.get("checkMesh"))
    return f"""# {title}

- case status: `{case.get('case_status')}`
- case directory: `{case.get('case_dir')}`
- custom mesh status: `{mesh.get('status')}`
- nodes: `{mesh.get('node_count')}`
- cells: `{mesh.get('cell_count')}`
- faces: `{mesh.get('face_count')}`
- boundary face counts: `{mesh.get('boundary_face_counts')}`
- first layer height: `{mesh.get('first_layer_height_m')}` m
- min signed volume: `{mesh.get('min_signed_volume')}`
- max signed volume: `{mesh.get('max_signed_volume')}`
- volume percentiles: `{mesh.get('volume_percentiles')}`
- aspect-ratio proxy percentiles: `{mesh.get('aspect_ratio_proxy_percentiles')}`
- checkMesh status: `{check.get('status')}`
- checkMesh quality basis: `{check.get('quality_basis')}`
- checkMesh counts: `{check.get('counts')}`

```text
{chr(10).join(check.get('summary_lines') or ['not available'])}
```
"""


def debug_mesh_report_text(manifest: Mapping[str, Any]) -> str:
    case = _mapping(manifest.get("debug_case"))
    attempts = list(manifest.get("debug_attempts") or [])
    rows = [
        "| attempt | mapping | smooth | farfield chords | custom status | checkMesh | non-positive custom volumes | min signed volume |",
        "|---|---|---:|---:|---|---|---:|---:|",
    ]
    for attempt in attempts:
        item = _mapping(attempt)
        config = _mapping(item.get("config"))
        mesh = _mapping(item.get("mesh"))
        check = _mapping(item.get("checkMesh"))
        rows.append(
            "| `{}` | `{}` | {} | {} | `{}` | `{}` | {} | {} |".format(
                item.get("case_id"),
                config.get("outer_mapping"),
                config.get("normal_smoothing_iterations"),
                config.get("farfield_chords"),
                mesh.get("status"),
                check.get("status"),
                mesh.get("non_positive_volume_count"),
                _fmt(mesh.get("min_signed_volume")),
            )
        )
    return (
        case_mesh_report_text("Baseline Debug Mesh Report", case)
        + "\n## Bounded Debug Attempts\n\n"
        + "\n".join(rows)
        + "\n"
    )


def solver_report_text(manifest: Mapping[str, Any]) -> str:
    lines = ["# OpenFOAM Solver Report", ""]
    for name in ("debug_case", "verification_case"):
        case = _mapping(manifest.get(name))
        lines.extend(
            [
                f"## {name}",
                "",
                f"- case status: `{case.get('case_status')}`",
                f"- case directory: `{case.get('case_dir')}`",
                f"- commands: `{case.get('commands')}`",
                f"- force stability final window: `{case.get('force_stability_final_window')}`",
                "",
            ]
        )
    return "\n".join(lines)


def force_breakdown_report_text(manifest: Mapping[str, Any]) -> str:
    lines = [
        "# Force Breakdown Report",
        "",
        "| case | CD_primary | CL_primary | CD_total | diagnostic CD sum |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ("debug_case", "verification_case"):
        case = _mapping(manifest.get(name))
        summary = _mapping(_mapping(case.get("forces")).get("summary"))
        lines.append(
            "| `{}` | {} | {} | {} | {} |".format(
                name,
                _fmt(summary.get("CD_primary")),
                _fmt(summary.get("CL_primary")),
                _fmt(summary.get("CD_total")),
                _fmt(summary.get("CD_diagnostic_sum")),
            )
        )
    lines.append("")
    lines.append(
        "Primary remains `wing_upper + wing_lower`; tip, TE, and closure patches are kept diagnostic."
    )
    return "\n".join(lines)


def yplus_report_text(manifest: Mapping[str, Any]) -> str:
    lines = ["# yPlus Report", ""]
    for name in ("debug_case", "verification_case"):
        case = _mapping(manifest.get(name))
        yplus = _mapping(case.get("yPlus"))
        lines.extend(
            [
                f"## {name}",
                "",
                f"- status: `{yplus.get('status')}`",
                f"- latest time: `{yplus.get('latest_time')}`",
                f"- primary patches: `{yplus.get('primary_patch_summary')}`",
                f"- combined primary summary: `{summarize_primary_yplus(yplus)}`",
                "",
            ]
        )
    return "\n".join(lines)


def pressure_viscous_split_report_text(manifest: Mapping[str, Any]) -> str:
    lines = [
        "# Pressure Viscous Split Report",
        "",
        "This report uses OpenFOAM `forces` pressure/viscous columns. It does not treat `Cd(f)` and `Cd(r)` from `forceCoeffs` as pressure/viscous split.",
        "",
    ]
    for name in ("debug_case", "verification_case"):
        case = _mapping(manifest.get(name))
        split = _mapping(case.get("pressure_viscous_split"))
        lines.extend(
            [
                f"## {name}",
                "",
                f"- status: `{split.get('status')}`",
                f"- primary: `{split.get('primary')}`",
                f"- total: `{split.get('total')}`",
                "",
            ]
        )
    return "\n".join(lines)


def cfd_vs_xfoil_comparison_report_text(manifest: Mapping[str, Any]) -> str:
    verdict = _mapping(manifest.get("verdict"))
    return f"""# CFD vs XFOIL Comparison Report

- XFOIL/spanwise-integrated CD_total reference: `{XFOIL_SPANWISE_CD_TOTAL}`
- Phase 2 SU2 pressure-only CD reference: `{PHASE2_SU2_PRESSURE_ONLY_CD}`
- previous OpenFOAM high-yPlus layers_8 CD_primary: `{OPENFOAM_HIGH_YPLUS_CD_PRIMARY}`
- closest strict-snappy CD_primary: `{OPENFOAM_STRICT_SNAPPY_CD_PRIMARY}`
- structured-hexa basis: `{verdict.get('basis')}`
- structured-hexa CD_primary: `{verdict.get('CD_primary')}`
- structured-hexa CD_total: `{verdict.get('CD_total')}`
- comparison status: `{verdict.get('supports_xfoil_cd')}`

The structured result is allowed to support, contradict, or remain inconclusive
relative to XFOIL. Agreement is not forced by changing geometry or AOA.
"""


def phase3_structured_hexa_verdict_text(manifest: Mapping[str, Any]) -> str:
    verdict = _mapping(manifest.get("verdict"))
    return f"""# Phase 3 Structured Hexa Verdict

1. Did the structured hexa route generate a valid mesh?
   - `{verdict.get('valid_mesh_generated')}`
2. Did checkMesh pass?
   - `{verdict.get('checkMesh_passed')}`
3. Did the solver run?
   - `{verdict.get('solver_ran')}`
4. What are CD_primary, CL_primary, CD_total?
   - CD_primary `{verdict.get('CD_primary')}`, CL_primary `{verdict.get('CL_primary')}`, CD_total `{verdict.get('CD_total')}`
5. What are pressure and viscous contributions, if available?
   - `{verdict.get('pressure_viscous_primary')}`
6. What are yPlus mean/p95/max?
   - `{verdict.get('yPlus')}`
7. Is this wall-resolved, wall-function, or sanity-level CFD?
   - `{verdict.get('wall_regime')}`
8. Does this CFD support or contradict XFOIL/spanwise-integrated CD around 0.02602?
   - `{verdict.get('supports_xfoil_cd')}`
9. Is the result good enough to give to the engineering team as CFD verification?
   - `{verdict.get('good_enough_for_engineering_team_cfd_verification')}`
10. If not, what remains impossible or blocked?
   - `{verdict.get('reason') or verdict.get('engineering_boundary')}`

Engineering caveat: passing software gates is not aircraft validation. The result
still needs review of wall regime, farfield adequacy, force stability, turbulence
model assumptions, and whether the body-like O-grid farfield contaminates the
force balance.
"""


def rerun_instructions_text(output_dir: Path) -> str:
    return f"""# Rerun Instructions

```bash
.venv/bin/python scripts/run_wo006_structured_hexa_verification.py \\
  --output-dir {output_dir} \\
  --openfoam {OPENFOAM_WRAPPER} \\
  --clean
```

Use `--skip-verification` to rerun only the artificial and debug gates.
"""


def summarize_primary_yplus(yplus: Mapping[str, Any]) -> dict[str, Any]:
    patches = _mapping(yplus.get("patches"))
    values = []
    for marker in PRIMARY_FORCE_MARKERS:
        row = _mapping(patches.get(marker))
        if row:
            values.append(row)
    if not values:
        return {"status": "missing"}
    means = [_float_or_none(row.get("mean")) for row in values]
    maxes = [_float_or_none(row.get("max")) for row in values]
    means = [value for value in means if value is not None]
    maxes = [value for value in maxes if value is not None]
    return {
        "status": "available" if means and maxes else "missing",
        "mean": sum(means) / len(means) if means else None,
        "p95": None,
        "max": max(maxes) if maxes else None,
        "source_limitation": "OpenFOAM yPlus.dat reports patch min/max/mean; p95 is not available from this functionObject output.",
    }


def classify_wall_regime(yplus_summary: Mapping[str, Any]) -> str:
    mean = _float_or_none(yplus_summary.get("mean"))
    max_value = _float_or_none(yplus_summary.get("max"))
    if mean is None or max_value is None:
        return "no_yplus_evidence"
    if mean < 5.0 and max_value < 40.0:
        return "wall_resolved_attempt"
    if 30.0 <= mean <= 300.0:
        return "wall_function_range"
    return "sanity_level_only"


def _xfoil_comparison_status(cd_primary: float) -> str:
    delta = cd_primary - XFOIL_SPANWISE_CD_TOTAL
    if abs(delta) <= 0.005:
        return "broadly_supports_xfoil_cd"
    if cd_primary > XFOIL_SPANWISE_CD_TOTAL + 0.02:
        return "contradicts_xfoil_or_indicates_cfd_setup_drag_excess"
    return "inconclusive_relative_to_xfoil"


def _append_tip_quad_disk(
    vertices: list[Vertex],
    faces: list[Face],
    boundary: list[int],
    *,
    side_subdivisions: int,
    marker: str,
) -> None:
    m = side_subdivisions
    if len(boundary) != 4 * m:
        raise ValueError("Tip boundary node count must equal 4 * side_subdivisions")

    grid: list[list[int | None]] = [[None for _ in range(m + 1)] for _ in range(m + 1)]
    for i in range(m + 1):
        grid[i][0] = boundary[i]
        grid[m][i] = boundary[m + i]
        grid[m - i][m] = boundary[2 * m + i]
        grid[0][m - i] = boundary[(3 * m + i) % (4 * m)]

    b_curve = [_point(vertices[grid[i][0]]) for i in range(m + 1)]  # type: ignore[index]
    r_curve = [_point(vertices[grid[m][j]]) for j in range(m + 1)]  # type: ignore[index]
    t_curve = [_point(vertices[grid[i][m]]) for i in range(m + 1)]  # type: ignore[index]
    l_curve = [_point(vertices[grid[0][j]]) for j in range(m + 1)]  # type: ignore[index]
    c00, c10, c11, c01 = b_curve[0], b_curve[-1], t_curve[-1], t_curve[0]
    for i in range(1, m):
        u = i / m
        for j in range(1, m):
            v = j / m
            point = _coons_point(
                u,
                v,
                b_curve[i],
                t_curve[i],
                l_curve[j],
                r_curve[j],
                c00,
                c10,
                c11,
                c01,
            )
            grid[i][j] = len(vertices)
            vertices.append(point)

    for i in range(m):
        for j in range(m):
            n00 = grid[i][j]
            n10 = grid[i + 1][j]
            n11 = grid[i + 1][j + 1]
            n01 = grid[i][j + 1]
            if None in (n00, n10, n11, n01):
                raise ValueError("Incomplete tip cap grid")
            faces.append(Face(nodes=(n00, n10, n11, n01), marker=marker))  # type: ignore[arg-type]


def _coons_point(
    u: float,
    v: float,
    bottom: Vertex,
    top: Vertex,
    left: Vertex,
    right: Vertex,
    c00: Vertex,
    c10: Vertex,
    c11: Vertex,
    c01: Vertex,
) -> Vertex:
    blended = _vadd(
        _vadd(_vscale(bottom, 1.0 - v), _vscale(top, v)),
        _vadd(_vscale(left, 1.0 - u), _vscale(right, u)),
    )
    corner = _vadd(
        _vadd(_vscale(c00, (1.0 - u) * (1.0 - v)), _vscale(c10, u * (1.0 - v))),
        _vadd(_vscale(c11, u * v), _vscale(c01, (1.0 - u) * v)),
    )
    return _vsub(blended, corner)


def _smoothed_vertex_normals(
    surface: SurfaceMesh,
    iterations: int,
) -> list[Vertex]:
    normals = [(0.0, 0.0, 0.0) for _ in surface.vertices]
    adjacency: list[set[int]] = [set() for _ in surface.vertices]
    for face in surface.faces:
        points = [surface.vertices[node] for node in face.nodes]
        normal = _face_normal(points)
        area = _face_area(points)
        weighted = _vscale(normal, area)
        for node in face.nodes:
            normals[node] = _vadd(normals[node], weighted)
        for left, right in zip(face.nodes, face.nodes[1:] + face.nodes[:1]):
            adjacency[left].add(right)
            adjacency[right].add(left)
    base = [_vnormalize(normal, fallback=_fallback_normal(surface.vertices[index])) for index, normal in enumerate(normals)]
    current = list(base)
    for _ in range(max(0, iterations)):
        nxt: list[Vertex] = []
        for index, normal in enumerate(current):
            accum = normal
            for neighbor in adjacency[index]:
                accum = _vadd(accum, current[neighbor])
            smoothed = _vnormalize(accum, fallback=base[index])
            if _vdot(smoothed, base[index]) < 0.0:
                smoothed = _vscale(smoothed, -1.0)
            nxt.append(smoothed)
        current = nxt
    return current


def _outer_targets(
    surface: SurfaceMesh,
    normals: Sequence[Vertex],
    farfield_distance_m: float,
) -> list[Vertex]:
    vertices = surface.vertices
    n_span = int(surface.metadata.get("n_span") or 0)
    n_perimeter = int(surface.metadata.get("n_perimeter") or 0)
    if n_span <= 0 or n_perimeter <= 0:
        return _generic_outer_targets(vertices, normals, farfield_distance_m)
    side_node_count = (n_span + 1) * n_perimeter
    if side_node_count > len(vertices):
        return _generic_outer_targets(vertices, normals, farfield_distance_m)
    half_span = max(abs(vertices[0][1]), abs(vertices[(side_node_count - 1)][1]), 1.0e-9)
    span_offset = 0.35 * farfield_distance_m
    section_centers: list[Vertex] = []
    section_scales: list[tuple[float, float]] = []
    for section in range(n_span + 1):
        loop = vertices[section * n_perimeter : (section + 1) * n_perimeter]
        center = _centroid(loop)
        section_centers.append(center)
        max_dx = max(abs(point[0] - center[0]) for point in loop)
        max_dz = max(abs(point[2] - center[2]) for point in loop)
        section_scales.append(
            (
                1.0 + farfield_distance_m / max(max_dx, 1.0e-9),
                1.0 + farfield_distance_m / max(max_dz, 1.0e-9),
            )
        )

    targets: list[Vertex] = []
    for index, vertex in enumerate(vertices):
        if index < side_node_count:
            section = index // n_perimeter
            center = section_centers[section]
            x_scale, z_scale = section_scales[section]
            dx = vertex[0] - center[0]
            dz = vertex[2] - center[2]
            span_fraction = min(1.0, abs(vertex[1]) / half_span)
            y_offset = math.copysign(span_offset * (span_fraction**3), vertex[1])
            target = (
                center[0] + dx * x_scale,
                vertex[1] + y_offset,
                center[2] + dz * z_scale,
            )
            targets.append(target)
            continue

        tip_side = -1.0 if vertex[1] < 0.0 else 1.0
        section = 0 if tip_side < 0.0 else n_span
        center = section_centers[section]
        x_scale, z_scale = section_scales[section]
        local = (vertex[0] - center[0], 0.0, vertex[2] - center[2])
        target = (
            center[0] + local[0] * x_scale,
            vertex[1] + tip_side * span_offset,
            center[2] + local[2] * z_scale,
        )
        targets.append(target)
    return targets


def _generic_outer_targets(
    vertices: Sequence[Vertex],
    normals: Sequence[Vertex],
    farfield_distance_m: float,
) -> list[Vertex]:
    center = _centroid(vertices)
    targets: list[Vertex] = []
    for vertex, normal in zip(vertices, normals, strict=True):
        radial = _vsub(vertex, center)
        radial = _vnormalize(radial, fallback=normal)
        if _vdot(radial, normal) < 0.0:
            radial = _vscale(radial, -1.0)
        direction = radial
        if _vdot(direction, normal) < 0.0:
            direction = _vscale(direction, -1.0)
        target = _vadd(vertex, _vscale(direction, farfield_distance_m))
        targets.append(
            _enforce_outward_displacement(
                vertex,
                target,
                normal,
                minimum_normal_distance=0.02 * farfield_distance_m,
            )
        )
    return targets


def _enforce_outward_displacement(
    vertex: Vertex,
    target: Vertex,
    normal: Vertex,
    *,
    minimum_normal_distance: float,
) -> Vertex:
    displacement = _vsub(target, vertex)
    normal_distance = _vdot(displacement, normal)
    if normal_distance >= minimum_normal_distance:
        return target
    return _vadd(target, _vscale(normal, minimum_normal_distance - normal_distance))


def _smoothstep(value: float) -> float:
    x = min(1.0, max(0.0, value))
    return x * x * (3.0 - 2.0 * x)


def radial_distances(
    *,
    radial_layers: int,
    near_wall_layers: int,
    first_layer_height_m: float,
    near_wall_growth: float,
    farfield_distance_m: float,
) -> list[float]:
    if radial_layers < 1:
        raise ValueError("radial_layers must be positive")
    near_count = min(max(1, near_wall_layers), radial_layers)
    increments: list[float] = []
    for index in range(near_count):
        increments.append(first_layer_height_m * (near_wall_growth**index))
    remaining_count = radial_layers - near_count
    near_distance = sum(increments)
    if remaining_count > 0:
        remaining_distance = farfield_distance_m - near_distance
        if remaining_distance <= 0.0:
            raise ValueError("farfield distance must exceed near-wall distance")
        start = increments[-1]
        growth = _solve_growth_for_distance(
            first_increment=start,
            count=remaining_count,
            total_distance=remaining_distance,
        )
        for index in range(remaining_count):
            increments.append(start * (growth ** (index + 1)))
    distances = [0.0]
    total = 0.0
    for increment in increments:
        total += increment
        distances.append(total)
    return distances


def _solve_growth_for_distance(
    *,
    first_increment: float,
    count: int,
    total_distance: float,
) -> float:
    if count <= 0:
        return 1.0
    if count == 1:
        return total_distance / first_increment
    lo = 1.0
    hi = 2.0
    while _geometric_sum(first_increment, hi, count) < total_distance:
        hi *= 1.5
        if hi > 100.0:
            break
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _geometric_sum(first_increment, mid, count) < total_distance:
            lo = mid
        else:
            hi = mid
    return hi


def _geometric_sum(first: float, ratio: float, count: int) -> float:
    if abs(ratio - 1.0) < 1.0e-12:
        return first * count
    return first * ratio * (ratio**count - 1.0) / (ratio - 1.0)


def _write_openfoam_points(path: Path, points: Sequence[Vertex]) -> None:
    lines = [_foam_header("vectorField", "points"), str(len(points)), "("]
    lines.extend(f"({x:.12g} {y:.12g} {z:.12g})" for x, y, z in points)
    lines.extend([")", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_openfoam_faces(path: Path, faces: Sequence[Sequence[int]]) -> None:
    lines = [_foam_header("faceList", "faces"), str(len(faces)), "("]
    for face in faces:
        lines.append(f"{len(face)}(" + " ".join(str(node) for node in face) + ")")
    lines.extend([")", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_openfoam_label_list(path: Path, object_name: str, values: Sequence[int]) -> None:
    lines = [_foam_header("labelList", object_name), str(len(values)), "("]
    lines.extend(str(value) for value in values)
    lines.extend([")", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_openfoam_boundary(
    path: Path,
    boundary_ranges: Mapping[str, Mapping[str, int]],
) -> None:
    lines = [_foam_header("polyBoundaryMesh", "boundary"), str(len(BOUNDARY_PATCH_ORDER)), "("]
    for patch in BOUNDARY_PATCH_ORDER:
        payload = boundary_ranges[patch]
        patch_type = "patch" if patch == "farfield" else "wall"
        lines.extend(
            [
                f"    {patch}",
                "    {",
                f"        type            {patch_type};",
                f"        nFaces          {int(payload['nFaces'])};",
                f"        startFace       {int(payload['startFace'])};",
                "    }",
            ]
        )
    lines.extend([")", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _foam_header(class_name: str, object_name: str) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       {class_name};
    location    "constant/polyMesh";
    object      {object_name};
}}"""


def _hex_signed_volume(
    points: Sequence[Vertex],
    cell: Sequence[int],
) -> float:
    volume = 0.0
    for order in HEX_FACE_NODE_ORDERS:
        face_nodes = [cell[index] for index in order]
        tris = ((face_nodes[0], face_nodes[1], face_nodes[2]), (face_nodes[0], face_nodes[2], face_nodes[3]))
        for a, b, c in tris:
            volume += _tetra_signed_volume(points[a], points[b], points[c])
    return volume


def _best_positive_hex_orientation(
    points: Sequence[Vertex],
    inner: Sequence[int],
    outer: Sequence[int],
) -> tuple[int, int, int, int, int, int, int, int]:
    candidates = [
        (
            inner[0],
            inner[1],
            inner[2],
            inner[3],
            outer[0],
            outer[1],
            outer[2],
            outer[3],
        ),
        (
            inner[0],
            inner[3],
            inner[2],
            inner[1],
            outer[0],
            outer[3],
            outer[2],
            outer[1],
        ),
        (
            inner[3],
            inner[2],
            inner[1],
            inner[0],
            outer[3],
            outer[2],
            outer[1],
            outer[0],
        ),
        (
            inner[1],
            inner[2],
            inner[3],
            inner[0],
            outer[1],
            outer[2],
            outer[3],
            outer[0],
        ),
    ]
    return max(candidates, key=lambda cell: _hex_signed_volume(points, cell))


def _tetra_signed_volume(a: Vertex, b: Vertex, c: Vertex) -> float:
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    ) / 6.0


def _hex_aspect_ratio_proxy(points: Sequence[Vertex], cell: Sequence[int]) -> float:
    edges = (
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    )
    lengths = [_vdistance(points[cell[a]], points[cell[b]]) for a, b in edges]
    shortest = min(lengths)
    longest = max(lengths)
    return math.inf if shortest <= 0.0 else longest / shortest


def _synthetic_airfoil_loop(n_perimeter: int, *, thickness: float) -> list[tuple[float, float]]:
    points_per_side = n_perimeter // 2 + 1
    upper_x = [0.5 * (1.0 + math.cos(math.pi * i / (points_per_side - 1))) for i in range(points_per_side)]
    lower_x = list(reversed(upper_x))
    upper = [(x, 0.5 * thickness * math.sin(math.pi * x)) for x in upper_x]
    lower = [(x, -0.5 * thickness * math.sin(math.pi * x)) for x in lower_x[1:-1]]
    return upper + lower


def _require_surface_resolution(n_span: int, n_perimeter: int) -> None:
    if n_span < 1:
        raise ValueError("n_span must be positive")
    if n_perimeter < 8:
        raise ValueError("n_perimeter must be at least 8")
    if n_perimeter % 4 != 0:
        raise ValueError("n_perimeter must be divisible by 4 for quad tip disks")


def _moment_origin_from_geometry(geometry: StructuredWingGeometry) -> tuple[float, float, float]:
    payload = geometry.source.get("moment_origin_m")
    if isinstance(payload, Sequence) and len(payload) >= 3:
        return (float(payload[0]), float(payload[1]), float(payload[2]))
    source_avl = geometry.source.get("source_avl_path")
    if source_avl:
        return _read_avl_moment_origin(Path(str(source_avl)))
    return (0.25 * geometry.reference.cref, 0.0, 0.0)


def _mesh_summary(mesh: StructuredHexaMesh, quality: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": quality.get("status"),
        "blockers": quality.get("blockers"),
        "node_count": quality.get("node_count"),
        "cell_count": quality.get("cell_count"),
        "face_count": quality.get("face_count"),
        "internal_face_count": quality.get("internal_face_count"),
        "boundary_face_counts": quality.get("boundary_face_counts"),
        "first_layer_height_m": quality.get("first_layer_height_m"),
        "radial_layer_distribution_m": quality.get("radial_layer_distribution_m"),
        "volume_percentiles": quality.get("volume_percentiles"),
        "aspect_ratio_proxy_percentiles": quality.get("aspect_ratio_proxy_percentiles"),
        "min_signed_volume": quality.get("min_signed_volume"),
        "max_signed_volume": quality.get("max_signed_volume"),
        "non_positive_volume_count": quality.get("non_positive_volume_count"),
        "duplicate_point_count": quality.get("duplicate_point_count"),
        "nonmanifold_face_count": quality.get("nonmanifold_face_count"),
        "unmarked_boundary_face_count": quality.get("unmarked_boundary_face_count"),
        "missing_boundary_patch_count": quality.get("missing_boundary_patch_count"),
        "surface_metadata": mesh.surface_metadata,
    }


def _config_dict(config: StructuredHexaConfig) -> dict[str, Any]:
    return {
        "case_id": config.case_id,
        "n_span": config.n_span,
        "n_perimeter": config.n_perimeter,
        "radial_layers": config.radial_layers,
        "near_wall_layers": config.near_wall_layers,
        "first_layer_height_m": config.first_layer_height_m,
        "near_wall_growth": config.near_wall_growth,
        "farfield_chords": config.farfield_chords,
        "normal_smoothing_iterations": config.normal_smoothing_iterations,
        "outer_mapping": config.outer_mapping,
    }


def _percentile_summary(values: Sequence[float]) -> dict[str, float | None]:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return {"min": None, "p05": None, "p50": None, "p95": None, "max": None}
    return {
        "min": finite[0],
        "p05": _percentile(finite, 0.05),
        "p50": _percentile(finite, 0.50),
        "p95": _percentile(finite, 0.95),
        "max": finite[-1],
    }


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = fraction * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    weight = pos - lo
    return sorted_values[lo] * (1.0 - weight) + sorted_values[hi] * weight


def _duplicate_point_count(points: Sequence[Vertex], *, digits: int = 12) -> int:
    seen: set[tuple[float, float, float]] = set()
    duplicate = 0
    for point in points:
        key = (round(point[0], digits), round(point[1], digits), round(point[2], digits))
        if key in seen:
            duplicate += 1
        else:
            seen.add(key)
    return duplicate


def _face_normal(points: Sequence[Vertex]) -> Vertex:
    if len(points) < 3:
        return (0.0, 0.0, 0.0)
    normal = (0.0, 0.0, 0.0)
    for left, right in zip(points, points[1:] + points[:1]):
        normal = (
            normal[0] + (left[1] - right[1]) * (left[2] + right[2]),
            normal[1] + (left[2] - right[2]) * (left[0] + right[0]),
            normal[2] + (left[0] - right[0]) * (left[1] + right[1]),
        )
    return _vnormalize(normal, fallback=(0.0, 0.0, 1.0))


def _face_area(points: Sequence[Vertex]) -> float:
    if len(points) == 3:
        return _triangle_area(points[0], points[1], points[2])
    if len(points) == 4:
        return _triangle_area(points[0], points[1], points[2]) + _triangle_area(
            points[0],
            points[2],
            points[3],
        )
    raise ValueError("Only triangle/quad face area supported")


def _triangle_area(a: Vertex, b: Vertex, c: Vertex) -> float:
    return 0.5 * _vnorm(_vcross(_vsub(b, a), _vsub(c, a)))


def _fallback_normal(point: Vertex) -> Vertex:
    x, y, z = point
    if abs(y) > max(abs(x), abs(z), 1.0e-9):
        return (0.0, 1.0 if y >= 0.0 else -1.0, 0.0)
    if abs(z) > 1.0e-9:
        return (0.0, 0.0, 1.0 if z >= 0.0 else -1.0)
    return (1.0, 0.0, 0.0)


def _vadd(a: Vertex, b: Vertex) -> Vertex:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vsub(a: Vertex, b: Vertex) -> Vertex:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vscale(a: Vertex, scale: float) -> Vertex:
    return (a[0] * scale, a[1] * scale, a[2] * scale)


def _vdot(a: Vertex, b: Vertex) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vcross(a: Vertex, b: Vertex) -> Vertex:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vnorm(a: Vertex) -> float:
    return math.sqrt(_vdot(a, a))


def _vnormalize(a: Vertex, *, fallback: Vertex) -> Vertex:
    norm = _vnorm(a)
    if norm <= 1.0e-15 or not math.isfinite(norm):
        fallback_norm = _vnorm(fallback)
        if fallback_norm <= 1.0e-15:
            return (1.0, 0.0, 0.0)
        return (fallback[0] / fallback_norm, fallback[1] / fallback_norm, fallback[2] / fallback_norm)
    return (a[0] / norm, a[1] / norm, a[2] / norm)


def _vdistance(a: Vertex, b: Vertex) -> float:
    return _vnorm(_vsub(a, b))


def _point(point: Vertex) -> Vertex:
    return (float(point[0]), float(point[1]), float(point[2]))


def _centroid(points: Sequence[Vertex]) -> Vertex:
    if not points:
        raise ValueError("Cannot compute centroid of empty point list")
    scale = 1.0 / len(points)
    return (
        sum(point[0] for point in points) * scale,
        sum(point[1] for point in points) * scale,
        sum(point[2] for point in points) * scale,
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _fmt(value: Any) -> str:
    number = _float_or_none(value)
    return "`not_available`" if number is None else f"`{number:.9g}`"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
