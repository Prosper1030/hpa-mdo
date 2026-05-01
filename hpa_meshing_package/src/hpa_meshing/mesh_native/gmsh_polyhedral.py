from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .su2_structured import (
    _parse_smoke_history,
    _resolve_solver_command,
    _smoke_cfg_text,
    audit_su2_case_markers,
)
from .wing_surface import Face, SurfaceMesh


def write_faceted_volume_mesh(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    out_path: Path | str,
    *,
    su2_path: Path | str | None = None,
    mesh_size: float = 2.0,
    wall_marker: str = "wing_wall",
    farfield_marker: str = "farfield",
    fluid_marker: str = "fluid",
) -> dict[str, Any]:
    """Generate a Gmsh volume from mesh-native faceted boundary surfaces.

    The geometry source of truth remains the mesh-native indexed surface. Gmsh is
    used here as a volume mesher over built-in plane surfaces, not as a CAD repair
    step or STEP/BREP importer.
    """
    import gmsh

    msh_path = Path(out_path)
    msh_path.parent.mkdir(parents=True, exist_ok=True)
    su2_output_path = Path(su2_path) if su2_path is not None else None
    if su2_output_path is not None:
        su2_output_path.parent.mkdir(parents=True, exist_ok=True)

    if mesh_size <= 0.0:
        raise ValueError("mesh_size must be positive")

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("mesh_native_faceted_volume")

        vertices = [*wing.vertices, *farfield.vertices]
        point_tags = [
            gmsh.model.geo.addPoint(x, y, z, mesh_size)
            for x, y, z in vertices
        ]
        line_cache: dict[tuple[int, int], tuple[int, int, int]] = {}
        wing_surfaces = _add_mesh_surfaces(
            gmsh,
            wing.faces,
            point_tags=point_tags,
            line_cache=line_cache,
            node_offset=0,
        )
        farfield_surfaces = _add_mesh_surfaces(
            gmsh,
            farfield.faces,
            point_tags=point_tags,
            line_cache=line_cache,
            node_offset=len(wing.vertices),
        )

        outer_loop = gmsh.model.geo.addSurfaceLoop(farfield_surfaces)
        inner_loop = gmsh.model.geo.addSurfaceLoop(wing_surfaces)
        fluid_volume = gmsh.model.geo.addVolume([outer_loop, inner_loop])
        gmsh.model.geo.synchronize()

        wing_group = gmsh.model.addPhysicalGroup(2, wing_surfaces)
        gmsh.model.setPhysicalName(2, wing_group, wall_marker)
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surfaces)
        gmsh.model.setPhysicalName(2, farfield_group, farfield_marker)
        fluid_group = gmsh.model.addPhysicalGroup(3, [fluid_volume])
        gmsh.model.setPhysicalName(3, fluid_group, fluid_marker)

        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size)
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
        gmsh.option.setNumber("Mesh.Algorithm", 5)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.model.mesh.generate(3)

        node_tags, _, _ = gmsh.model.mesh.getNodes()
        volume_element_types, volume_element_tags, _ = gmsh.model.mesh.getElements(3)
        volume_type_counts = {
            str(element_type): len(tags)
            for element_type, tags in zip(volume_element_types, volume_element_tags)
        }
        volume_element_count = sum(volume_type_counts.values())
        gmsh.write(str(msh_path))
        if su2_output_path is not None:
            gmsh.write(str(su2_output_path))

        return {
            "status": "meshed",
            "route": "mesh_native_faceted_gmsh_volume",
            "mesh_path": str(msh_path),
            "su2_path": None if su2_output_path is None else str(su2_output_path),
            "volume_count": len(gmsh.model.getEntities(3)),
            "node_count": len(node_tags),
            "volume_element_count": volume_element_count,
            "volume_element_type_counts": volume_type_counts,
            "surface_triangle_count": len(wing_surfaces) + len(farfield_surfaces),
            "physical_groups": {
                wall_marker: {
                    "dimension": 2,
                    "physical_tag": wing_group,
                    "entity_count": len(wing_surfaces),
                },
                farfield_marker: {
                    "dimension": 2,
                    "physical_tag": farfield_group,
                    "entity_count": len(farfield_surfaces),
                },
                fluid_marker: {
                    "dimension": 3,
                    "physical_tag": fluid_group,
                    "entity_count": 1,
                },
            },
            "caveats": [
                "wing boundary is faceted from mesh-native panels",
                "tet volume mesh only; no boundary-layer prism strategy",
            ],
        }
    finally:
        gmsh.finalize()


def write_faceted_volume_su2_case(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    case_dir: Path | str,
    *,
    ref_area: float,
    ref_length: float,
    mesh_size: float = 2.0,
    velocity_mps: float = 6.5,
    alpha_deg: float = 0.0,
    max_iterations: int = 3,
    solver: str = "INC_EULER",
) -> dict[str, Any]:
    if ref_area <= 0.0:
        raise ValueError("ref_area must be positive")
    if ref_length <= 0.0:
        raise ValueError("ref_length must be positive")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")

    case_path = Path(case_dir)
    case_path.mkdir(parents=True, exist_ok=True)
    msh_path = case_path / "mesh.msh"
    su2_path = case_path / "mesh.su2"
    runtime_cfg_path = case_path / "su2_runtime.cfg"
    report_path = case_path / "mesh_native_faceted_su2_smoke_report.json"

    mesh_report = write_faceted_volume_mesh(
        wing,
        farfield,
        msh_path,
        su2_path=su2_path,
        mesh_size=mesh_size,
    )
    runtime_cfg_path.write_text(
        _smoke_cfg_text(
            wing,
            solver=solver,
            ref_area=ref_area,
            ref_length=ref_length,
            velocity_mps=velocity_mps,
            alpha_deg=alpha_deg,
            max_iterations=max_iterations,
            wall_marker="wing_wall",
            farfield_marker="farfield",
        ),
        encoding="utf-8",
    )
    marker_audit = audit_su2_case_markers(su2_path, runtime_cfg_path)
    report = {
        "route": "mesh_native_faceted_gmsh_volume_su2_smoke_case",
        "mesh_path": str(su2_path),
        "gmsh_mesh_path": str(msh_path),
        "runtime_cfg_path": str(runtime_cfg_path),
        "report_path": str(report_path),
        "mesh_report": mesh_report,
        "marker_audit": marker_audit,
        "runtime": {
            "solver": solver,
            "velocity_mps": velocity_mps,
            "alpha_deg": alpha_deg,
            "max_iterations": max_iterations,
            "ref_area": ref_area,
            "ref_length": ref_length,
            "mesh_size": mesh_size,
        },
        "caveats": [
            *mesh_report["caveats"],
            "smoke case is not a convergence or aerodynamic validation case",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def run_faceted_volume_su2_smoke(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    case_dir: Path | str,
    *,
    ref_area: float,
    ref_length: float,
    mesh_size: float = 2.0,
    velocity_mps: float = 6.5,
    alpha_deg: float = 0.0,
    max_iterations: int = 3,
    solver: str = "INC_EULER",
    solver_command: str = "SU2_CFD",
    threads: int = 1,
) -> dict[str, Any]:
    case_report = write_faceted_volume_su2_case(
        wing,
        farfield,
        case_dir,
        ref_area=ref_area,
        ref_length=ref_length,
        mesh_size=mesh_size,
        velocity_mps=velocity_mps,
        alpha_deg=alpha_deg,
        max_iterations=max_iterations,
        solver=solver,
    )
    case_path = Path(case_dir)
    solver_path = _resolve_solver_command(solver_command)
    solver_log_path = case_path / "solver.log"
    history_path = case_path / "history.csv"
    worker_count = max(1, int(threads))
    command = [solver_path, "-t", str(worker_count), "su2_runtime.cfg"]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(worker_count)

    with solver_log_path.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            command,
            cwd=case_path,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            env=env,
        )

    history = _parse_smoke_history(history_path) if history_path.exists() else None
    failure_code = None
    if completed.returncode != 0:
        failure_code = "solver_execution_failed"
    elif history is None:
        failure_code = "history_missing"

    run_status = "completed" if failure_code is None else "failed"
    run_report = {
        **case_report,
        "run_status": run_status,
        "failure_code": failure_code,
        "returncode": completed.returncode,
        "solver_command": command,
        "solver_log_path": str(solver_log_path),
        "history_path": str(history_path) if history_path.exists() else None,
        "history": history,
        "engineering_assessment": {
            "solver_readability": "pass" if run_status == "completed" else "fail",
            "marker_ownership": case_report["marker_audit"]["status"],
            "aero_coefficients_interpretable": False,
            "reason": "faceted_wing_tet_smoke_not_converged",
        },
    }
    Path(case_report["report_path"]).write_text(json.dumps(run_report, indent=2), encoding="utf-8")
    return run_report


def _add_mesh_surfaces(
    gmsh,
    faces: list[Face],
    *,
    point_tags: list[int],
    line_cache: dict[tuple[int, int], tuple[int, int, int]],
    node_offset: int,
) -> list[int]:
    surfaces: list[int] = []
    for face in faces:
        for triangle in _triangulate(face):
            shifted = tuple(node + node_offset for node in triangle)
            curve_loop = gmsh.model.geo.addCurveLoop(
                [
                    _line_between(gmsh, point_tags, line_cache, shifted[0], shifted[1]),
                    _line_between(gmsh, point_tags, line_cache, shifted[1], shifted[2]),
                    _line_between(gmsh, point_tags, line_cache, shifted[2], shifted[0]),
                ]
            )
            surfaces.append(gmsh.model.geo.addPlaneSurface([curve_loop]))
    return surfaces


def _triangulate(face: Face) -> list[tuple[int, int, int]]:
    nodes = tuple(face.nodes)
    if len(nodes) == 3:
        return [nodes]
    if len(nodes) == 4:
        return [
            (nodes[0], nodes[1], nodes[2]),
            (nodes[0], nodes[2], nodes[3]),
        ]
    raise ValueError("Only triangle and quad faces can be converted to plane surfaces")


def _line_between(
    gmsh,
    point_tags: list[int],
    line_cache: dict[tuple[int, int], tuple[int, int, int]],
    start: int,
    end: int,
) -> int:
    key = tuple(sorted((start, end)))
    if key not in line_cache:
        line_cache[key] = (
            gmsh.model.geo.addLine(point_tags[key[0]], point_tags[key[1]]),
            key[0],
            key[1],
        )
    line_tag, stored_start, stored_end = line_cache[key]
    return line_tag if (start, end) == (stored_start, stored_end) else -line_tag
