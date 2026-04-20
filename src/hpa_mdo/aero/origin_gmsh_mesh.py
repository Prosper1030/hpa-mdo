"""Generate a Gmsh-backed external-flow SU2 mesh around origin STL geometry."""

from __future__ import annotations

import importlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_STL_EXTERNAL_FLOW_OPTIONS = {
    "upstream_factor": 1.0,
    "downstream_factor": 3.0,
    "lateral_factor": 1.2,
    "vertical_factor": 1.2,
    "near_body_size_factor": 0.035,
    "farfield_size_factor": 0.12,
    "distance_min_factor": 0.08,
    "distance_max_factor": 0.55,
    "mesh_algorithm_3d": 1,
    "mesh_size_from_curvature": 20,
}

ORIGIN_SU2_MESH_PRESETS: dict[str, dict[str, Any]] = {
    "baseline": dict(DEFAULT_STL_EXTERNAL_FLOW_OPTIONS),
    "study_coarse": {
        "near_body_size_factor": 0.055,
        "farfield_size_factor": 0.18,
        "distance_min_factor": 0.12,
        "distance_max_factor": 0.80,
    },
    "study_medium": {
        "near_body_size_factor": 0.028,
        "farfield_size_factor": 0.10,
        "distance_min_factor": 0.07,
        "distance_max_factor": 0.45,
    },
    "study_fine": {
        "near_body_size_factor": 0.018,
        "farfield_size_factor": 0.075,
        "distance_min_factor": 0.05,
        "distance_max_factor": 0.30,
    },
}

GMSH_TRIANGLE = 2
GMSH_QUAD = 3
GMSH_TETRA = 4
GMSH_HEXAHEDRON = 5
GMSH_PRISM = 6
GMSH_PYRAMID = 7

SU2_TRIANGLE = 5
SU2_QUAD = 9
SU2_TETRA = 10
SU2_HEXAHEDRON = 12
SU2_PRISM = 13
SU2_PYRAMID = 14


class GmshExternalFlowMeshError(RuntimeError):
    """Raised when the origin external-flow mesh cannot be created."""


def _candidate_gmsh_lib_dirs() -> list[Path]:
    candidates: list[Path] = []

    gmsh_binary = shutil.which("gmsh")
    if gmsh_binary is not None:
        binary_path = Path(gmsh_binary).expanduser().resolve()
        candidates.append(binary_path.parent.parent / "lib")

    for prefix in (
        Path("/opt/homebrew/opt/gmsh/lib"),
        Path("/usr/local/opt/gmsh/lib"),
    ):
        candidates.append(prefix)

    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)
    return unique_candidates


def _gmsh():
    try:
        import gmsh  # type: ignore

        return gmsh
    except ImportError:
        pass

    for lib_dir in _candidate_gmsh_lib_dirs():
        gmsh_py = lib_dir / "gmsh.py"
        if not gmsh_py.exists():
            continue
        if str(lib_dir) not in sys.path:
            sys.path.insert(0, str(lib_dir))
        importlib.invalidate_caches()
        try:
            import gmsh  # type: ignore

            return gmsh
        except ImportError:
            continue

    raise GmshExternalFlowMeshError(
        "gmsh Python API is not available. Install gmsh with Python bindings or keep Homebrew gmsh on PATH."
    )


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def resolve_origin_mesh_options(
    *,
    preset_name: str = "baseline",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if preset_name not in ORIGIN_SU2_MESH_PRESETS:
        raise ValueError(
            f"unknown origin SU2 mesh preset {preset_name!r}; expected one of {sorted(ORIGIN_SU2_MESH_PRESETS)}"
        )

    resolved = dict(DEFAULT_STL_EXTERNAL_FLOW_OPTIONS)
    resolved.update(ORIGIN_SU2_MESH_PRESETS[preset_name])
    if overrides:
        resolved.update(overrides)
    return resolved


def _global_bbox(gmsh, dim: int) -> tuple[list[float], list[float]]:
    entities = gmsh.model.getEntities(dim)
    if not entities:
        raise GmshExternalFlowMeshError(f"Gmsh model has no entities with dim={dim}")

    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    for _, tag in entities:
        x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(dim, tag)
        mins[0] = min(mins[0], float(x_min))
        mins[1] = min(mins[1], float(y_min))
        mins[2] = min(mins[2], float(z_min))
        maxs[0] = max(maxs[0], float(x_max))
        maxs[1] = max(maxs[1], float(y_max))
        maxs[2] = max(maxs[2], float(z_max))
    return mins, maxs


def _box_bounds(mins: list[float], maxs: list[float], options: dict[str, Any]) -> dict[str, float]:
    x_span = max(maxs[0] - mins[0], 1e-6)
    y_span = max(maxs[1] - mins[1], 1e-6)
    z_span = max(maxs[2] - mins[2], 1e-6)
    z_pad = float(options["vertical_factor"]) * max(abs(mins[2]), abs(maxs[2]), z_span, 1.0)
    return {
        "x_min": mins[0] - float(options["upstream_factor"]) * x_span,
        "x_max": maxs[0] + float(options["downstream_factor"]) * x_span,
        "y_min": mins[1] - float(options["lateral_factor"]) * y_span,
        "y_max": maxs[1] + float(options["lateral_factor"]) * y_span,
        "z_min": mins[2] - z_pad,
        "z_max": maxs[2] + z_pad,
    }


def _create_geo_farfield_box(gmsh, bounds: dict[str, float], mesh_size: float) -> list[int]:
    p000 = gmsh.model.geo.addPoint(bounds["x_min"], bounds["y_min"], bounds["z_min"], mesh_size)
    p100 = gmsh.model.geo.addPoint(bounds["x_max"], bounds["y_min"], bounds["z_min"], mesh_size)
    p110 = gmsh.model.geo.addPoint(bounds["x_max"], bounds["y_max"], bounds["z_min"], mesh_size)
    p010 = gmsh.model.geo.addPoint(bounds["x_min"], bounds["y_max"], bounds["z_min"], mesh_size)
    p001 = gmsh.model.geo.addPoint(bounds["x_min"], bounds["y_min"], bounds["z_max"], mesh_size)
    p101 = gmsh.model.geo.addPoint(bounds["x_max"], bounds["y_min"], bounds["z_max"], mesh_size)
    p111 = gmsh.model.geo.addPoint(bounds["x_max"], bounds["y_max"], bounds["z_max"], mesh_size)
    p011 = gmsh.model.geo.addPoint(bounds["x_min"], bounds["y_max"], bounds["z_max"], mesh_size)

    l000_100 = gmsh.model.geo.addLine(p000, p100)
    l100_110 = gmsh.model.geo.addLine(p100, p110)
    l110_010 = gmsh.model.geo.addLine(p110, p010)
    l010_000 = gmsh.model.geo.addLine(p010, p000)
    l001_101 = gmsh.model.geo.addLine(p001, p101)
    l101_111 = gmsh.model.geo.addLine(p101, p111)
    l111_011 = gmsh.model.geo.addLine(p111, p011)
    l011_001 = gmsh.model.geo.addLine(p011, p001)
    l000_001 = gmsh.model.geo.addLine(p000, p001)
    l100_101 = gmsh.model.geo.addLine(p100, p101)
    l110_111 = gmsh.model.geo.addLine(p110, p111)
    l010_011 = gmsh.model.geo.addLine(p010, p011)

    bottom_loop = gmsh.model.geo.addCurveLoop([l000_100, l100_110, l110_010, l010_000])
    top_loop = gmsh.model.geo.addCurveLoop([l001_101, l101_111, l111_011, l011_001])
    xmin_loop = gmsh.model.geo.addCurveLoop([l010_000, l000_001, -l011_001, -l010_011])
    xmax_loop = gmsh.model.geo.addCurveLoop([l100_110, l110_111, -l101_111, -l100_101])
    ymin_loop = gmsh.model.geo.addCurveLoop([l000_100, l100_101, -l001_101, -l000_001])
    ymax_loop = gmsh.model.geo.addCurveLoop([l110_010, l010_011, -l111_011, -l110_111])

    return [
        gmsh.model.geo.addPlaneSurface([bottom_loop]),
        gmsh.model.geo.addPlaneSurface([top_loop]),
        gmsh.model.geo.addPlaneSurface([xmin_loop]),
        gmsh.model.geo.addPlaneSurface([xmax_loop]),
        gmsh.model.geo.addPlaneSurface([ymin_loop]),
        gmsh.model.geo.addPlaneSurface([ymax_loop]),
    ]


def _configure_mesh_fields(gmsh, body_surface_tags: list[int], body_ranges: list[float], options: dict[str, Any]) -> dict[str, float]:
    characteristic_length = max(max(body_ranges), 1e-6)
    near_body_size = max(float(options["near_body_size_factor"]) * characteristic_length, 5e-3)
    farfield_size = max(float(options["farfield_size_factor"]) * characteristic_length, near_body_size * 1.5)

    distance_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(distance_field, "FacesList", body_surface_tags)

    threshold_field = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(threshold_field, "InField", distance_field)
    gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", near_body_size)
    gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", farfield_size)
    gmsh.model.mesh.field.setNumber(
        threshold_field,
        "DistMin",
        max(float(options["distance_min_factor"]) * characteristic_length, 1e-6),
    )
    gmsh.model.mesh.field.setNumber(
        threshold_field,
        "DistMax",
        max(float(options["distance_max_factor"]) * characteristic_length, near_body_size),
    )
    gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)

    gmsh.option.setNumber("Mesh.MeshSizeMin", near_body_size * 0.55)
    gmsh.option.setNumber("Mesh.MeshSizeMax", farfield_size)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", float(options["mesh_size_from_curvature"]))
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)
    gmsh.option.setNumber("Mesh.Algorithm3D", float(options["mesh_algorithm_3d"]))

    return {
        "NearBodySize": near_body_size,
        "FarfieldSize": farfield_size,
        "CharacteristicLength": characteristic_length,
    }


def _collect_physical_group_elements_raw(gmsh, dim: int, physical_tag: int) -> list[tuple[int, list[int]]]:
    supported_types = {
        GMSH_TRIANGLE: (SU2_TRIANGLE, 3),
        GMSH_QUAD: (SU2_QUAD, 4),
        GMSH_TETRA: (SU2_TETRA, 4),
        GMSH_HEXAHEDRON: (SU2_HEXAHEDRON, 8),
        GMSH_PRISM: (SU2_PRISM, 6),
        GMSH_PYRAMID: (SU2_PYRAMID, 5),
    }

    collected: list[tuple[int, list[int]]] = []
    seen_tags: set[int] = set()
    for entity_tag in gmsh.model.getEntitiesForPhysicalGroup(dim, physical_tag):
        element_types, element_tags_blocks, node_tags_blocks = gmsh.model.mesh.getElements(dim, entity_tag)
        for element_type, element_tags, node_tags in zip(element_types, element_tags_blocks, node_tags_blocks):
            if element_type not in supported_types:
                continue
            su2_type, node_count = supported_types[element_type]
            connectivity = np.asarray(node_tags, dtype=int).reshape(-1, node_count)
            for element_tag, nodes in zip(element_tags, connectivity):
                element_tag = int(element_tag)
                if element_tag in seen_tags:
                    continue
                seen_tags.add(element_tag)
                collected.append((su2_type, [int(node_tag) for node_tag in nodes]))
    return collected


def _write_su2_mesh(gmsh, output_path: Path, marker_names: dict[int, str], fluid_group_tag: int) -> dict[str, Any]:
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    if len(node_tags) == 0:
        raise GmshExternalFlowMeshError("Gmsh produced no mesh nodes")
    coordinates = np.asarray(coords, dtype=float).reshape(-1, 3)
    coordinate_map = {
        int(tag): (float(x_value), float(y_value), float(z_value))
        for tag, (x_value, y_value, z_value) in zip(node_tags, coordinates)
    }

    raw_volume_elements = _collect_physical_group_elements_raw(gmsh, 3, fluid_group_tag)
    if not raw_volume_elements:
        raise GmshExternalFlowMeshError("Gmsh produced no 3D volume elements")

    volume_type_counts: dict[str, int] = {}
    for su2_type, _ in raw_volume_elements:
        key = str(su2_type)
        volume_type_counts[key] = volume_type_counts.get(key, 0) + 1

    raw_marker_elements: dict[str, list[tuple[int, list[int]]]] = {}
    for dim, physical_tag in gmsh.model.getPhysicalGroups():
        if dim != 2:
            continue
        physical_name = gmsh.model.getPhysicalName(dim, physical_tag)
        raw_marker_elements[physical_name] = _collect_physical_group_elements_raw(gmsh, 2, physical_tag)

    used_node_tags: set[int] = set()
    for _, nodes in raw_volume_elements:
        used_node_tags.update(nodes)
    for elements in raw_marker_elements.values():
        for _, nodes in elements:
            used_node_tags.update(nodes)

    ordered_node_tags = [int(tag) for tag in node_tags if int(tag) in used_node_tags]
    if not ordered_node_tags:
        raise GmshExternalFlowMeshError("No referenced mesh nodes were found for SU2 export")
    node_map = {tag: index for index, tag in enumerate(ordered_node_tags)}

    volume_elements = [
        (su2_type, [node_map[node_tag] for node_tag in nodes])
        for su2_type, nodes in raw_volume_elements
    ]
    marker_elements = {
        name: [(su2_type, [node_map[node_tag] for node_tag in nodes]) for su2_type, nodes in elements]
        for name, elements in raw_marker_elements.items()
    }

    lines = [
        "NDIME= 3",
        f"NPOIN= {len(ordered_node_tags)}",
    ]
    for node_tag in ordered_node_tags:
        x_value, y_value, z_value = coordinate_map[node_tag]
        lines.append(f"{x_value:.12f} {y_value:.12f} {z_value:.12f}")

    lines.append(f"NELEM= {len(volume_elements)}")
    for su2_type, nodes in volume_elements:
        lines.append(f"{su2_type} {' '.join(str(node) for node in nodes)}")

    lines.append(f"NMARK= {len(marker_names)}")
    for marker_name in marker_names.values():
        elements = marker_elements.get(marker_name, [])
        lines.append(f"MARKER_TAG= {marker_name}")
        lines.append(f"MARKER_ELEMS= {len(elements)}")
        for su2_type, nodes in elements:
            lines.append(f"{su2_type} {' '.join(str(node) for node in nodes)}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "Nodes": int(len(ordered_node_tags)),
        "VolumeElements": int(len(volume_elements)),
        "VolumeElementTypeCounts": volume_type_counts,
        "MarkerElements": {name: int(len(elements)) for name, elements in marker_elements.items()},
    }


def generate_stl_external_flow_mesh(
    surface_stl_path: str | Path,
    output_path: str | Path,
    *,
    options: dict[str, Any] | None = None,
    preset_name: str = "baseline",
    body_marker: str = "aircraft",
    farfield_marker: str = "farfield",
) -> dict[str, Any]:
    gmsh = _gmsh()
    resolved_options = resolve_origin_mesh_options(preset_name=preset_name, overrides=options)

    surface_stl = Path(surface_stl_path).expanduser().resolve()
    if not surface_stl.exists():
        raise FileNotFoundError(f"surface STL not found: {surface_stl}")

    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    msh_path = output_path.with_suffix(".msh")

    marker_names = {
        2: body_marker,
        3: farfield_marker,
    }

    gmsh.initialize()
    try:
        gmsh.model.add("origin_external_flow")
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.merge(str(surface_stl))

        body_surface_tags = [tag for dim, tag in gmsh.model.getEntities(2)]
        if not body_surface_tags:
            raise GmshExternalFlowMeshError("STL import produced no body surface entities")

        body_mins, body_maxs = _global_bbox(gmsh, 2)
        body_ranges = [b - a for a, b in zip(body_mins, body_maxs)]
        bounds = _box_bounds(body_mins, body_maxs, resolved_options)
        farfield_mesh_size = max(
            float(resolved_options["farfield_size_factor"]) * max(body_ranges),
            1e-3,
        )

        body_shell = gmsh.model.geo.addSurfaceLoop(body_surface_tags)
        farfield_surfaces = _create_geo_farfield_box(gmsh, bounds, farfield_mesh_size)
        outer_shell = gmsh.model.geo.addSurfaceLoop(farfield_surfaces)
        fluid_volume = gmsh.model.geo.addVolume([outer_shell, body_shell])
        gmsh.model.geo.synchronize()

        fluid_group_tag = gmsh.model.addPhysicalGroup(3, [fluid_volume], 1)
        gmsh.model.setPhysicalName(3, fluid_group_tag, "fluid")
        body_group_tag = gmsh.model.addPhysicalGroup(2, body_surface_tags, 2)
        gmsh.model.setPhysicalName(2, body_group_tag, body_marker)
        farfield_group_tag = gmsh.model.addPhysicalGroup(2, farfield_surfaces, 3)
        gmsh.model.setPhysicalName(2, farfield_group_tag, farfield_marker)

        mesh_field_info = _configure_mesh_fields(
            gmsh,
            body_surface_tags=body_surface_tags,
            body_ranges=body_ranges,
            options=resolved_options,
        )

        gmsh.model.mesh.generate(3)
        gmsh.write(str(msh_path))
        su2_stats = _write_su2_mesh(gmsh, output_path, marker_names, fluid_group_tag)
    except Exception as exc:  # pragma: no cover - exercised via integration smoke
        if isinstance(exc, GmshExternalFlowMeshError):
            raise
        raise GmshExternalFlowMeshError(str(exc)) from exc
    finally:
        gmsh.finalize()

    metadata = {
        "MeshMode": "stl_external_box",
        "PresetName": preset_name,
        "SurfaceStl": str(surface_stl),
        "MeshFile": str(output_path),
        "NativeMshFile": str(msh_path),
        "BodySurfaceCount": int(len(body_surface_tags)),
        "FarfieldSurfaceCount": int(len(farfield_surfaces)),
        "FluidVolumeTag": int(fluid_volume),
        "BodyBounds": {
            "x_min": body_mins[0],
            "x_max": body_maxs[0],
            "y_min": body_mins[1],
            "y_max": body_maxs[1],
            "z_min": body_mins[2],
            "z_max": body_maxs[2],
        },
        "FarfieldBounds": bounds,
        "MeshFieldInfo": mesh_field_info,
        "Options": resolved_options,
        **su2_stats,
    }
    metadata_path = output_path.with_name("mesh_metadata.json")
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )
    metadata["MetadataFile"] = str(metadata_path)
    return metadata
