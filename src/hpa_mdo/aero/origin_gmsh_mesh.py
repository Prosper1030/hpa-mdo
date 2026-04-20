"""Generate a Gmsh-backed external-flow SU2 mesh around origin STL geometry."""

from __future__ import annotations

from collections import defaultdict
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


def _dim_tags_bbox(gmsh, dim_tags: list[tuple[int, int]]) -> tuple[list[float], list[float]]:
    if not dim_tags:
        raise GmshExternalFlowMeshError("Gmsh entity list is empty")

    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    for dim, tag in dim_tags:
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


def _configure_mesh_fields(
    gmsh,
    body_surface_tags: list[int],
    body_ranges: list[float],
    options: dict[str, Any],
    *,
    optimize_netgen: bool = True,
) -> dict[str, float]:
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
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1 if optimize_netgen else 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", float(options["mesh_algorithm_3d"]))

    return {
        "NearBodySize": near_body_size,
        "FarfieldSize": farfield_size,
        "CharacteristicLength": characteristic_length,
        "OptimizeNetgen": bool(optimize_netgen),
    }


def _boundary_surface_tags(gmsh, dim_tags: list[tuple[int, int]]) -> list[int]:
    if not dim_tags:
        return []

    boundary = gmsh.model.getBoundary(dim_tags, oriented=False, recursive=False)
    surface_tags: list[int] = []
    seen: set[int] = set()
    for dim, tag in boundary:
        if dim != 2:
            continue
        entity_tag = int(tag)
        if entity_tag in seen:
            continue
        seen.add(entity_tag)
        surface_tags.append(entity_tag)
    return surface_tags


def _is_box_face_surface(gmsh, surface_tag: int, bounds: dict[str, float], tolerance: float) -> bool:
    x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(2, surface_tag)
    face_bounds = (
        (x_min, x_max, bounds["x_min"], bounds["x_min"]),
        (x_min, x_max, bounds["x_max"], bounds["x_max"]),
        (y_min, y_max, bounds["y_min"], bounds["y_min"]),
        (y_min, y_max, bounds["y_max"], bounds["y_max"]),
        (z_min, z_max, bounds["z_min"], bounds["z_min"]),
        (z_min, z_max, bounds["z_max"], bounds["z_max"]),
    )
    return any(
        abs(entity_min - target_min) <= tolerance and abs(entity_max - target_max) <= tolerance
        for entity_min, entity_max, target_min, target_max in face_bounds
    )


def _classify_outer_boundary_surfaces(gmsh, surface_tags: list[int], bounds: dict[str, float]) -> tuple[list[int], list[int]]:
    box_spans = (
        bounds["x_max"] - bounds["x_min"],
        bounds["y_max"] - bounds["y_min"],
        bounds["z_max"] - bounds["z_min"],
    )
    tolerance = max(max(box_spans), 1.0) * 1e-6

    farfield_surface_tags = [
        tag for tag in surface_tags if _is_box_face_surface(gmsh, tag, bounds, tolerance)
    ]
    body_surface_tags = [tag for tag in surface_tags if tag not in set(farfield_surface_tags)]
    return body_surface_tags, farfield_surface_tags


def _embedded_surface_tags(gmsh, volume_tags: list[int]) -> list[int]:
    embedded_surface_tags: list[int] = []
    seen: set[int] = set()
    for volume_tag in volume_tags:
        for dim, tag in gmsh.model.mesh.getEmbedded(3, int(volume_tag)):
            if dim != 2:
                continue
            surface_tag = int(tag)
            if surface_tag in seen:
                continue
            seen.add(surface_tag)
            embedded_surface_tags.append(surface_tag)
    return embedded_surface_tags


def _surface_tags_from_occ_map(occ_map: list[list[tuple[int, int]]]) -> list[int]:
    surface_tags: list[int] = []
    seen: set[int] = set()
    for mapping in occ_map:
        for dim, tag in mapping:
            if dim != 2:
                continue
            surface_tag = int(tag)
            if surface_tag in seen:
                continue
            seen.add(surface_tag)
            surface_tags.append(surface_tag)
    return surface_tags


def _remove_duplicate_surface_facets(gmsh, surface_tags: list[int]) -> int:
    duplicate_elements: dict[tuple[int, tuple[int, ...]], list[tuple[int, int]]] = defaultdict(list)

    for surface_tag in surface_tags:
        element_types, element_tags_blocks, node_tags_blocks = gmsh.model.mesh.getElements(2, surface_tag)
        for element_type, element_tags, node_tags in zip(element_types, element_tags_blocks, node_tags_blocks):
            if element_type == GMSH_TRIANGLE:
                node_count = 3
            elif element_type == GMSH_QUAD:
                node_count = 4
            else:
                continue
            connectivity = np.asarray(node_tags, dtype=int).reshape(-1, node_count)
            for element_tag, nodes in zip(element_tags, connectivity):
                key = (int(element_type), tuple(sorted(int(node_tag) for node_tag in nodes)))
                duplicate_elements[key].append((int(surface_tag), int(element_tag)))

    removed_count = 0
    for entries in duplicate_elements.values():
        if len(entries) < 2:
            continue
        for surface_tag, element_tag in entries[1:]:
            gmsh.model.mesh.removeElements(2, surface_tag, [element_tag])
            removed_count += 1

    if removed_count:
        gmsh.model.mesh.reclassifyNodes()
    return removed_count


def _select_outer_fluid_volumes(
    gmsh,
    candidate_volume_tags: list[int],
    bounds: dict[str, float],
) -> tuple[list[int], list[int], list[int]]:
    fluid_volume_tags: list[int] = []
    body_boundary_surface_tags: list[int] = []
    farfield_surface_tags: list[int] = []
    seen_body_surface_tags: set[int] = set()
    seen_farfield_surface_tags: set[int] = set()

    for volume_tag in candidate_volume_tags:
        boundary_surfaces = _boundary_surface_tags(gmsh, [(3, int(volume_tag))])
        if not boundary_surfaces:
            continue

        body_surfaces, farfield_surfaces = _classify_outer_boundary_surfaces(
            gmsh,
            boundary_surfaces,
            bounds,
        )
        if not farfield_surfaces:
            continue

        fluid_volume_tags.append(int(volume_tag))
        for surface_tag in body_surfaces:
            if surface_tag in seen_body_surface_tags:
                continue
            seen_body_surface_tags.add(surface_tag)
            body_boundary_surface_tags.append(surface_tag)
        for surface_tag in farfield_surfaces:
            if surface_tag in seen_farfield_surface_tags:
                continue
            seen_farfield_surface_tags.add(surface_tag)
            farfield_surface_tags.append(surface_tag)

    return fluid_volume_tags, body_boundary_surface_tags, farfield_surface_tags


def _write_metadata(metadata: dict[str, Any]) -> None:
    metadata_path = metadata.get("MetadataFile")
    if metadata_path is None:
        return
    Path(metadata_path).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )


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


def _filter_marker_elements_to_volume_nodes(
    marker_elements: dict[str, list[tuple[int, list[int]]]],
    *,
    volume_node_tags: set[int],
) -> dict[str, list[tuple[int, list[int]]]]:
    return {
        name: [
            (su2_type, nodes)
            for su2_type, nodes in elements
            if set(nodes).issubset(volume_node_tags)
        ]
        for name, elements in marker_elements.items()
    }


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

    volume_node_tags = {node_tag for _, nodes in raw_volume_elements for node_tag in nodes}

    raw_marker_elements: dict[str, list[tuple[int, list[int]]]] = {}
    for dim, physical_tag in gmsh.model.getPhysicalGroups():
        if dim != 2:
            continue
        physical_name = gmsh.model.getPhysicalName(dim, physical_tag)
        raw_marker_elements[physical_name] = _collect_physical_group_elements_raw(gmsh, 2, physical_tag)

    filtered_marker_elements = _filter_marker_elements_to_volume_nodes(
        raw_marker_elements,
        volume_node_tags=volume_node_tags,
    )
    marker_elements_dropped_outside_volume = {
        name: int(len(raw_marker_elements.get(name, [])) - len(filtered_marker_elements.get(name, [])))
        for name in raw_marker_elements
    }

    used_node_tags: set[int] = set(volume_node_tags)
    for elements in filtered_marker_elements.values():
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
        for name, elements in filtered_marker_elements.items()
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
        "MarkerElementsDroppedOutsideVolume": marker_elements_dropped_outside_volume,
    }


def generate_step_occ_external_flow_mesh(
    step_path: str | Path,
    output_path: str | Path,
    *,
    options: dict[str, Any] | None = None,
    preset_name: str = "baseline",
    body_marker: str = "aircraft",
    farfield_marker: str = "farfield",
) -> dict[str, Any]:
    step_file = Path(step_path).expanduser().resolve()
    if not step_file.exists():
        raise FileNotFoundError(f"surface STEP not found: {step_file}")

    gmsh = _gmsh()
    resolved_options = resolve_origin_mesh_options(preset_name=preset_name, overrides=options)

    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    msh_path = output_path.with_suffix(".msh")

    marker_names = {
        2: body_marker,
        3: farfield_marker,
    }

    gmsh.initialize()
    try:
        gmsh.model.add("origin_external_flow_occ")
        gmsh.option.setNumber("General.Terminal", 1)

        imported_entities = gmsh.model.occ.importShapes(str(step_file), highestDimOnly=False)
        gmsh.model.occ.synchronize()
        if not imported_entities:
            raise GmshExternalFlowMeshError("STEP import produced no OCC entities")

        imported_volume_tags = sorted({int(tag) for dim, tag in imported_entities if dim == 3})
        imported_surface_tags = sorted({int(tag) for dim, tag in imported_entities if dim == 2})
        if not imported_volume_tags and not imported_surface_tags:
            raise GmshExternalFlowMeshError("STEP import produced no body surfaces or volumes")

        body_bbox_dim_tags = (
            [(3, tag) for tag in imported_volume_tags]
            if imported_volume_tags
            else [(2, tag) for tag in imported_surface_tags]
        )
        body_mins, body_maxs = _dim_tags_bbox(gmsh, body_bbox_dim_tags)
        body_ranges = [b - a for a, b in zip(body_mins, body_maxs)]
        bounds = _box_bounds(body_mins, body_maxs, resolved_options)

        outer_box = gmsh.model.occ.addBox(
            bounds["x_min"],
            bounds["y_min"],
            bounds["z_min"],
            bounds["x_max"] - bounds["x_min"],
            bounds["y_max"] - bounds["y_min"],
            bounds["z_max"] - bounds["z_min"],
        )
        body_entity_mode = "closed_volumes" if imported_volume_tags else "embedded_surfaces"
        body_tool_dim_tags = (
            [(3, tag) for tag in imported_volume_tags]
            if imported_volume_tags
            else [(2, tag) for tag in imported_surface_tags]
        )
        if imported_volume_tags:
            fluid_entities, occ_map = gmsh.model.occ.cut(
                [(3, outer_box)],
                body_tool_dim_tags,
                removeObject=True,
                removeTool=False,
            )
        else:
            fluid_entities, occ_map = gmsh.model.occ.fragment(
                [(3, outer_box)],
                body_tool_dim_tags,
                removeObject=True,
                removeTool=False,
            )
        gmsh.model.occ.synchronize()

        candidate_volume_tags = [int(tag) for dim, tag in fluid_entities if dim == 3]
        if not candidate_volume_tags:
            raise GmshExternalFlowMeshError("STEP/OCC route produced no external-flow volume")

        fluid_volume_tags, body_surface_tags, farfield_surface_tags = _select_outer_fluid_volumes(
            gmsh,
            candidate_volume_tags,
            bounds,
        )
        if not fluid_volume_tags:
            raise GmshExternalFlowMeshError("STEP/OCC route could not identify external fluid volumes")
        embedded_surface_count = 0
        if body_entity_mode == "embedded_surfaces":
            embedded_surface_tags = _embedded_surface_tags(gmsh, fluid_volume_tags)
            if not embedded_surface_tags:
                embedded_surface_tags = _surface_tags_from_occ_map(occ_map[1:])
            embedded_surface_count = int(len(embedded_surface_tags))
            body_surface_tags = sorted(
                set(body_surface_tags).union(embedded_surface_tags).difference(farfield_surface_tags)
            )
        if not body_surface_tags:
            raise GmshExternalFlowMeshError("STEP/OCC route could not identify aircraft boundary surfaces")
        if not farfield_surface_tags:
            raise GmshExternalFlowMeshError("STEP/OCC route could not identify farfield boundary surfaces")

        fluid_group_tag = gmsh.model.addPhysicalGroup(3, fluid_volume_tags, 1)
        gmsh.model.setPhysicalName(3, fluid_group_tag, "fluid")
        body_group_tag = gmsh.model.addPhysicalGroup(2, body_surface_tags, 2)
        gmsh.model.setPhysicalName(2, body_group_tag, body_marker)
        farfield_group_tag = gmsh.model.addPhysicalGroup(2, farfield_surface_tags, 3)
        gmsh.model.setPhysicalName(2, farfield_group_tag, farfield_marker)

        mesh_field_info = _configure_mesh_fields(
            gmsh,
            body_surface_tags=body_surface_tags,
            body_ranges=body_ranges,
            options=resolved_options,
            optimize_netgen=body_entity_mode != "embedded_surfaces",
        )

        removed_duplicate_boundary_facets = 0
        if body_entity_mode == "embedded_surfaces":
            gmsh.model.mesh.generate(2)
            removed_duplicate_boundary_facets = _remove_duplicate_surface_facets(gmsh, body_surface_tags)
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
        "MeshMode": "step_occ_box",
        "PresetName": preset_name,
        "BodyEntityMode": body_entity_mode,
        "SurfaceStep": str(step_file),
        "MeshFile": str(output_path),
        "NativeMshFile": str(msh_path),
        "ImportedVolumeCount": int(len(imported_volume_tags)),
        "ImportedSurfaceCount": int(len(imported_surface_tags)),
        "BodyVolumeCount": int(len(imported_volume_tags)),
        "CandidateFluidVolumeCount": int(len(candidate_volume_tags)),
        "FluidVolumeCount": int(len(fluid_volume_tags)),
        "BodySurfaceCount": int(len(body_surface_tags)),
        "EmbeddedSurfaceCount": embedded_surface_count,
        "RemovedDuplicateBoundaryFacets": int(removed_duplicate_boundary_facets),
        "FarfieldSurfaceCount": int(len(farfield_surface_tags)),
        "FluidVolumeTags": fluid_volume_tags,
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
    metadata["MetadataFile"] = str(metadata_path)
    _write_metadata(metadata)
    return metadata


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
    metadata["MetadataFile"] = str(metadata_path)
    _write_metadata(metadata)
    return metadata


def generate_origin_external_flow_mesh(
    *,
    step_path: str | Path | None,
    stl_path: str | Path,
    output_path: str | Path,
    preset_name: str = "baseline",
    mesh_overrides: dict[str, Any] | None = None,
    prefer_step_occ: bool = True,
    body_marker: str = "aircraft",
    farfield_marker: str = "farfield",
) -> dict[str, Any]:
    if prefer_step_occ and step_path is not None:
        try:
            return generate_step_occ_external_flow_mesh(
                step_path,
                output_path,
                preset_name=preset_name,
                options=mesh_overrides,
                body_marker=body_marker,
                farfield_marker=farfield_marker,
            )
        except (FileNotFoundError, GmshExternalFlowMeshError) as exc:
            fallback = generate_stl_external_flow_mesh(
                stl_path,
                output_path,
                preset_name=preset_name,
                options=mesh_overrides,
                body_marker=body_marker,
                farfield_marker=farfield_marker,
            )
            fallback["MeshMode"] = "stl_external_box_fallback"
            fallback["FallbackReason"] = str(exc)
            _write_metadata(fallback)
            return fallback

    return generate_stl_external_flow_mesh(
        stl_path,
        output_path,
        preset_name=preset_name,
        options=mesh_overrides,
        body_marker=body_marker,
        farfield_marker=farfield_marker,
    )
