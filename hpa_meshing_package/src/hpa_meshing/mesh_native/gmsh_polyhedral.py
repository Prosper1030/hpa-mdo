from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable, Sequence

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
    wing_mesh_size: float | None = None,
    farfield_mesh_size: float | None = None,
    wing_refinement_radius: float | None = None,
    refinement_boxes: Sequence[dict[str, Any]] | None = None,
    wall_marker: str = "wing_wall",
    farfield_marker: str = "farfield",
    fluid_marker: str = "fluid",
    production_target_volume_elements: int = 1_000_000,
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
    resolved_wing_mesh_size = mesh_size if wing_mesh_size is None else float(wing_mesh_size)
    resolved_farfield_mesh_size = (
        mesh_size if farfield_mesh_size is None else float(farfield_mesh_size)
    )
    if resolved_wing_mesh_size <= 0.0:
        raise ValueError("wing_mesh_size must be positive")
    if resolved_farfield_mesh_size <= 0.0:
        raise ValueError("farfield_mesh_size must be positive")
    resolved_wing_refinement_radius = (
        max(resolved_farfield_mesh_size, 3.0 * resolved_wing_mesh_size)
        if wing_refinement_radius is None
        else float(wing_refinement_radius)
    )
    if resolved_wing_refinement_radius <= 0.0:
        raise ValueError("wing_refinement_radius must be positive")
    resolved_refinement_boxes = _validate_refinement_boxes(
        refinement_boxes or (),
        farfield_mesh_size=resolved_farfield_mesh_size,
    )

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("mesh_native_faceted_volume")

        point_tags = [
            *[
                gmsh.model.geo.addPoint(x, y, z, resolved_wing_mesh_size)
                for x, y, z in wing.vertices
            ],
            *[
                gmsh.model.geo.addPoint(x, y, z, resolved_farfield_mesh_size)
                for x, y, z in farfield.vertices
            ],
        ]
        wing_point_tags = point_tags[: len(wing.vertices)]
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
        mesh_size_field = _install_background_mesh_size_field(
            gmsh,
            wing_point_tags=wing_point_tags,
            wing_mesh_size=resolved_wing_mesh_size,
            farfield_mesh_size=resolved_farfield_mesh_size,
            wing_refinement_radius=resolved_wing_refinement_radius,
            refinement_boxes=resolved_refinement_boxes,
        )

        wing_group = gmsh.model.addPhysicalGroup(2, wing_surfaces)
        gmsh.model.setPhysicalName(2, wing_group, wall_marker)
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surfaces)
        gmsh.model.setPhysicalName(2, farfield_group, farfield_marker)
        fluid_group = gmsh.model.addPhysicalGroup(3, [fluid_volume])
        gmsh.model.setPhysicalName(3, fluid_group, fluid_marker)

        gmsh.option.setNumber(
            "Mesh.MeshSizeMin",
            min(
                [
                    resolved_wing_mesh_size,
                    resolved_farfield_mesh_size,
                    *(box["size"] for box in resolved_refinement_boxes),
                ]
            ),
        )
        gmsh.option.setNumber(
            "Mesh.MeshSizeMax",
            max(resolved_wing_mesh_size, resolved_farfield_mesh_size),
        )
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
        quality_metrics = _collect_volume_quality_metrics(gmsh)
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
            "mesh_sizing": {
                "default_mesh_size": float(mesh_size),
                "wing_mesh_size": float(resolved_wing_mesh_size),
                "farfield_mesh_size": float(resolved_farfield_mesh_size),
                "wing_refinement_radius": float(resolved_wing_refinement_radius),
                "refinement_boxes": resolved_refinement_boxes,
                "background_field": mesh_size_field,
            },
            "quality_metrics": quality_metrics,
            "mesh_quality_gate": _mesh_quality_gate(quality_metrics),
            "production_scale_gate": _production_scale_gate(
                volume_element_count,
                target_volume_elements=production_target_volume_elements,
            ),
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


def run_faceted_volume_refinement_ladder(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    case_dir: Path | str,
    *,
    mesh_sizes: Sequence[float],
    target_volume_elements: int = 1_000_000,
    max_volume_elements: int = 250_000,
    farfield_mesh_size: float | None = None,
    wing_refinement_radius: float | None = None,
    write_su2: bool = True,
    refinement_boxes: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a coarse-to-fine mesh-size ladder with explicit cell-count guardrails."""
    if target_volume_elements <= 0:
        raise ValueError("target_volume_elements must be positive")
    if max_volume_elements <= 0:
        raise ValueError("max_volume_elements must be positive")

    ordered_mesh_sizes = sorted((float(value) for value in mesh_sizes), reverse=True)
    if not ordered_mesh_sizes:
        raise ValueError("mesh_sizes must not be empty")
    if any(value <= 0.0 for value in ordered_mesh_sizes):
        raise ValueError("mesh_sizes must all be positive")

    ladder_path = Path(case_dir)
    ladder_path.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    selected_case: dict[str, Any] | None = None
    status = "target_not_reached"

    for index, mesh_size in enumerate(ordered_mesh_sizes):
        mesh_case_path = ladder_path / f"{index:02d}_h_{_mesh_size_slug(mesh_size)}"
        mesh_case_path.mkdir(parents=True, exist_ok=True)
        su2_path = mesh_case_path / "mesh.su2" if write_su2 else None
        mesh_report = write_faceted_volume_mesh(
            wing,
            farfield,
            mesh_case_path / "mesh.msh",
            su2_path=su2_path,
            mesh_size=mesh_size,
            wing_mesh_size=mesh_size,
            farfield_mesh_size=farfield_mesh_size,
            wing_refinement_radius=wing_refinement_radius,
            refinement_boxes=refinement_boxes,
            production_target_volume_elements=target_volume_elements,
        )
        case_report = {
            **mesh_report,
            "case_dir": str(mesh_case_path),
            "mesh_size": mesh_size,
        }
        cases.append(case_report)

        if int(case_report["volume_element_count"]) > max_volume_elements:
            status = "blocked_by_volume_element_guard"
            break
        if int(case_report["volume_element_count"]) >= target_volume_elements:
            selected_case = case_report
            status = "target_reached"
            break

    report = {
        "route": "mesh_native_faceted_gmsh_volume_refinement_ladder",
        "status": status,
        "report_path": str(ladder_path / "refinement_ladder_report.json"),
        "target_volume_elements": int(target_volume_elements),
        "max_volume_elements": int(max_volume_elements),
        "mesh_sizes": ordered_mesh_sizes,
        "selected_case": selected_case,
        "cases": cases,
        "engineering_assessment": {
            "production_scale_target_volume_elements": int(target_volume_elements),
            "budget_guard_volume_elements": int(max_volume_elements),
            "selected_for_cfd_interpretation": status == "target_reached",
            "aero_coefficients_interpretable": False,
            "reason": "mesh_density_ladder_only_no_converged_su2_solution",
        },
        "caveats": [
            "mesh-size ladder changes global tet sizing only",
            "no boundary-layer prism strategy yet",
            "million-scale target is an engineering credibility gate, not a convergence proof",
        ],
    }
    Path(report["report_path"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


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


def build_wing_feature_refinement_boxes(
    wing: SurfaceMesh,
    *,
    mesh_size: float,
    trailing_edge_box_chords: float = 0.20,
    tip_box_chords: float = 1.0,
    wake_length_chords: float = 4.0,
    wake_half_height_chords: float = 0.75,
    wake_span_padding_chords: float = 0.50,
    transition_chords: float = 0.50,
) -> list[dict[str, Any]]:
    """Build simple TE/tip/wake box fields from mesh-native wing bounds."""
    if mesh_size <= 0.0:
        raise ValueError("mesh_size must be positive")
    for name, value in {
        "trailing_edge_box_chords": trailing_edge_box_chords,
        "tip_box_chords": tip_box_chords,
        "wake_length_chords": wake_length_chords,
        "wake_half_height_chords": wake_half_height_chords,
        "wake_span_padding_chords": wake_span_padding_chords,
        "transition_chords": transition_chords,
    }.items():
        if value <= 0.0:
            raise ValueError(f"{name} must be positive")

    bounds = wing.bounds()
    x_min = float(bounds["x_min"])
    x_max = float(bounds["x_max"])
    y_min = float(bounds["y_min"])
    y_max = float(bounds["y_max"])
    z_min = float(bounds["z_min"])
    z_max = float(bounds["z_max"])
    chord_scale = max(x_max - x_min, 1.0e-9)
    vertical_padding = wake_half_height_chords * chord_scale
    transition = transition_chords * chord_scale

    te_dx = trailing_edge_box_chords * chord_scale
    tip_dy = tip_box_chords * chord_scale
    wake_length = wake_length_chords * chord_scale
    wake_span_padding = wake_span_padding_chords * chord_scale

    return [
        {
            "name": "trailing_edge_refinement_region",
            "size": float(mesh_size),
            "x_min": x_max - te_dx,
            "x_max": x_max + te_dx,
            "y_min": y_min,
            "y_max": y_max,
            "z_min": z_min - vertical_padding,
            "z_max": z_max + vertical_padding,
            "transition_thickness": transition,
        },
        {
            "name": "tip_left_refinement_region",
            "size": float(mesh_size),
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_min + tip_dy,
            "z_min": z_min - vertical_padding,
            "z_max": z_max + vertical_padding,
            "transition_thickness": transition,
        },
        {
            "name": "tip_right_refinement_region",
            "size": float(mesh_size),
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_max - tip_dy,
            "y_max": y_max,
            "z_min": z_min - vertical_padding,
            "z_max": z_max + vertical_padding,
            "transition_thickness": transition,
        },
        {
            "name": "wake_refinement_region",
            "size": float(mesh_size),
            "x_min": x_max,
            "x_max": x_max + wake_length,
            "y_min": y_min - wake_span_padding,
            "y_max": y_max + wake_span_padding,
            "z_min": z_min - vertical_padding,
            "z_max": z_max + vertical_padding,
            "transition_thickness": transition,
        },
    ]


def _validate_refinement_boxes(
    boxes: Sequence[dict[str, Any]],
    *,
    farfield_mesh_size: float,
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    for index, box in enumerate(boxes):
        name = str(box.get("name") or f"refinement_box_{index}")
        size = float(box["size"])
        transition = float(box.get("transition_thickness", 0.0))
        if size <= 0.0:
            raise ValueError(f"{name}.size must be positive")
        if transition < 0.0:
            raise ValueError(f"{name}.transition_thickness must be non-negative")
        bounds = {
            key: float(box[key])
            for key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")
        }
        if bounds["x_min"] >= bounds["x_max"]:
            raise ValueError(f"{name}.x_min must be smaller than x_max")
        if bounds["y_min"] >= bounds["y_max"]:
            raise ValueError(f"{name}.y_min must be smaller than y_max")
        if bounds["z_min"] >= bounds["z_max"]:
            raise ValueError(f"{name}.z_min must be smaller than z_max")
        validated.append(
            {
                "name": name,
                "size": size,
                "outside_size": float(box.get("outside_size", farfield_mesh_size)),
                "transition_thickness": transition,
                **bounds,
            }
        )
    return validated


def _install_background_mesh_size_field(
    gmsh,
    *,
    wing_point_tags: list[int],
    wing_mesh_size: float,
    farfield_mesh_size: float,
    wing_refinement_radius: float,
    refinement_boxes: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    fields: list[dict[str, Any]] = []
    wing_field = _install_wing_refinement_field(
        gmsh,
        wing_point_tags=wing_point_tags,
        wing_mesh_size=wing_mesh_size,
        farfield_mesh_size=farfield_mesh_size,
        wing_refinement_radius=wing_refinement_radius,
    )
    if wing_field is not None:
        fields.append(wing_field)

    for box in refinement_boxes:
        fields.append(_install_box_refinement_field(gmsh, box))

    if not fields:
        return None
    if len(fields) == 1:
        gmsh.model.mesh.field.setAsBackgroundMesh(fields[0]["field_tag"])
        return fields[0]

    min_field = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(
        min_field,
        "FieldsList",
        [field["field_tag"] for field in fields],
    )
    gmsh.model.mesh.field.setAsBackgroundMesh(min_field)
    return {
        "type": "Min",
        "field_tag": int(min_field),
        "fields": fields,
    }


def _install_wing_refinement_field(
    gmsh,
    *,
    wing_point_tags: list[int],
    wing_mesh_size: float,
    farfield_mesh_size: float,
    wing_refinement_radius: float,
) -> dict[str, Any] | None:
    if (
        not wing_point_tags
        or abs(float(wing_mesh_size) - float(farfield_mesh_size)) <= 1.0e-12
    ):
        return None

    distance_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(distance_field, "NodesList", wing_point_tags)
    threshold_field = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(threshold_field, "InField", distance_field)
    gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", float(wing_mesh_size))
    gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", float(farfield_mesh_size))
    gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", 0.0)
    gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", float(wing_refinement_radius))
    return {
        "type": "DistanceThreshold",
        "field_tag": int(threshold_field),
        "distance_field_tag": int(distance_field),
        "threshold_field_tag": int(threshold_field),
        "node_count": len(wing_point_tags),
    }


def _install_box_refinement_field(gmsh, box: dict[str, Any]) -> dict[str, Any]:
    box_field = gmsh.model.mesh.field.add("Box")
    gmsh.model.mesh.field.setNumber(box_field, "VIn", float(box["size"]))
    gmsh.model.mesh.field.setNumber(box_field, "VOut", float(box["outside_size"]))
    gmsh.model.mesh.field.setNumber(box_field, "XMin", float(box["x_min"]))
    gmsh.model.mesh.field.setNumber(box_field, "XMax", float(box["x_max"]))
    gmsh.model.mesh.field.setNumber(box_field, "YMin", float(box["y_min"]))
    gmsh.model.mesh.field.setNumber(box_field, "YMax", float(box["y_max"]))
    gmsh.model.mesh.field.setNumber(box_field, "ZMin", float(box["z_min"]))
    gmsh.model.mesh.field.setNumber(box_field, "ZMax", float(box["z_max"]))
    gmsh.model.mesh.field.setNumber(
        box_field,
        "Thickness",
        float(box["transition_thickness"]),
    )
    return {
        "type": "Box",
        "field_tag": int(box_field),
        **box,
    }


def _collect_volume_quality_metrics(gmsh) -> dict[str, Any]:
    volume_types, volume_element_tags, _ = gmsh.model.mesh.getElements(3)
    tetra_tags: list[int] = []
    for element_type, tags in zip(volume_types, volume_element_tags):
        if int(element_type) == 4:
            tetra_tags.extend(int(tag) for tag in tags)

    if not tetra_tags:
        return {
            "tetra_element_count": 0,
            "tetrahedron_count": 0,
            "ill_shaped_tet_count": 0,
            "non_positive_min_sicn_count": 0,
            "non_positive_min_sige_count": 0,
            "non_positive_volume_count": 0,
            "min_gamma": None,
            "min_sicn": None,
            "min_sige": None,
            "min_volume": None,
            "gamma_percentiles": {"p01": None, "p05": None, "p50": None},
            "min_sicn_percentiles": {"p01": None, "p05": None, "p50": None},
            "min_sige_percentiles": {"p01": None, "p05": None, "p50": None},
            "volume_percentiles": {"p01": None, "p05": None, "p50": None},
        }

    min_sicn = [float(value) for value in gmsh.model.mesh.getElementQualities(tetra_tags, "minSICN")]
    min_sige = [float(value) for value in gmsh.model.mesh.getElementQualities(tetra_tags, "minSIGE")]
    gamma = [float(value) for value in gmsh.model.mesh.getElementQualities(tetra_tags, "gamma")]
    volume = [float(value) for value in gmsh.model.mesh.getElementQualities(tetra_tags, "volume")]
    ill_shaped_tet_count = sum(
        1
        for sicn_value, sige_value, volume_value in zip(min_sicn, min_sige, volume)
        if sicn_value <= 0.0 or sige_value <= 0.0 or volume_value <= 0.0
    )

    return {
        "tetra_element_count": len(tetra_tags),
        "tetrahedron_count": len(tetra_tags),
        "ill_shaped_tet_count": int(ill_shaped_tet_count),
        "non_positive_min_sicn_count": sum(1 for value in min_sicn if value <= 0.0),
        "non_positive_min_sige_count": sum(1 for value in min_sige if value <= 0.0),
        "non_positive_volume_count": sum(1 for value in volume if value <= 0.0),
        "min_gamma": min(gamma),
        "min_sicn": min(min_sicn),
        "min_sige": min(min_sige),
        "min_volume": min(volume),
        "gamma_percentiles": {
            "p01": _percentile(gamma, 0.01),
            "p05": _percentile(gamma, 0.05),
            "p50": _percentile(gamma, 0.50),
        },
        "min_sicn_percentiles": {
            "p01": _percentile(min_sicn, 0.01),
            "p05": _percentile(min_sicn, 0.05),
            "p50": _percentile(min_sicn, 0.50),
        },
        "min_sige_percentiles": {
            "p01": _percentile(min_sige, 0.01),
            "p05": _percentile(min_sige, 0.05),
            "p50": _percentile(min_sige, 0.50),
        },
        "volume_percentiles": {
            "p01": _percentile(volume, 0.01),
            "p05": _percentile(volume, 0.05),
            "p50": _percentile(volume, 0.50),
        },
    }


def _mesh_quality_gate(quality_metrics: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if int(quality_metrics.get("tetra_element_count") or 0) <= 0:
        blockers.append("tetra_elements_missing")
    if int(quality_metrics.get("non_positive_min_sicn_count") or 0) > 0:
        blockers.append("non_positive_min_sicn")
    if int(quality_metrics.get("non_positive_min_sige_count") or 0) > 0:
        blockers.append("non_positive_min_sige")
    if int(quality_metrics.get("non_positive_volume_count") or 0) > 0:
        blockers.append("non_positive_volume")
    min_gamma = quality_metrics.get("min_gamma")
    if min_gamma is not None and float(min_gamma) <= 0.0:
        blockers.append("non_positive_gamma")
    if min_gamma is not None and 0.0 < float(min_gamma) < 1.0e-4:
        warnings.append("very_low_min_gamma")
    min_sicn = quality_metrics.get("min_sicn")
    if min_sicn is not None and 0.0 < float(min_sicn) < 1.0e-4:
        warnings.append("very_low_min_sicn")
    gamma_percentiles = quality_metrics.get("gamma_percentiles") or {}
    p01_gamma = gamma_percentiles.get("p01") if isinstance(gamma_percentiles, dict) else None
    if p01_gamma is not None and float(p01_gamma) < 0.02:
        warnings.append("low_p01_gamma")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "warnings": warnings,
        "warning_thresholds": {
            "min_gamma": 1.0e-4,
            "min_sicn": 1.0e-4,
            "p01_gamma": 0.02,
        },
    }


def _production_scale_gate(
    volume_element_count: int,
    *,
    target_volume_elements: int,
) -> dict[str, Any]:
    target = int(target_volume_elements)
    if target <= 0:
        raise ValueError("target_volume_elements must be positive")
    observed = int(volume_element_count)
    shortfall = max(0, target - observed)
    return {
        "status": "meets_target" if observed >= target else "underresolved",
        "target_volume_elements": target,
        "observed_volume_elements": observed,
        "shortfall_volume_elements": shortfall,
        "observed_to_target_ratio": observed / target,
    }


def _percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    clamped_fraction = min(max(float(fraction), 0.0), 1.0)
    position = clamped_fraction * float(len(ordered) - 1)
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return ordered[lower_index]
    lower_weight = float(upper_index) - position
    upper_weight = position - float(lower_index)
    return ordered[lower_index] * lower_weight + ordered[upper_index] * upper_weight


def _mesh_size_slug(mesh_size: float) -> str:
    return f"{float(mesh_size):.6g}".replace("-", "m").replace(".", "p")
