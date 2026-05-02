from __future__ import annotations

from collections import defaultdict
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable

from ..gmsh_runtime import GmshRuntimeError, load_gmsh
from ..reference_geometry import resolve_reference_length
from ..schema import (
    Bounds3D,
    FarfieldConfig,
    GeometryHandle,
    MeshArtifactBundle,
    MeshHandoff,
    MeshJobConfig,
    MeshRecipe,
)


SUPPORTED_GMSH_CAPABILITIES = {
    "occ_closed_solid_meshing",
    "occ_perforated_solid_meshing",
    "sheet_lifting_surface_meshing",
    "sheet_aircraft_assembly_meshing",
}

REAL_OCC_ROUTE = "gmsh_thin_sheet_aircraft_assembly"
REAL_OCC_ROUTES = {
    "gmsh_thin_sheet_aircraft_assembly",
    "gmsh_thin_sheet_surface",
    "gmsh_closed_solid_volume",
}
DEFAULT_SURFACE_NODES_PER_REFERENCE_LENGTH = 128.0
DEFAULT_EDGE_REFINEMENT_RATIO = 0.5
DEFAULT_FARFIELD_REFERENCE_FACTOR = 4.0
DEFAULT_SURFACE_DISTANCE_FACTOR = 0.25
DEFAULT_EDGE_DISTANCE_FACTOR = 0.05
DEFAULT_SURFACE_TRANSITION_FACTOR = 10.0
DEFAULT_EDGE_TRANSITION_FACTOR = 10.0
COARSE_FIRST_TETRA_SURFACE_NODES_PER_REFERENCE_LENGTH = 24.0
COARSE_FIRST_TETRA_EDGE_REFINEMENT_RATIO = 1.0
COARSE_FIRST_TETRA_SPAN_EXTREME_STRIP_FLOOR_SIZE = 0.12
COARSE_FIRST_TETRA_SUSPECT_STRIP_FLOOR_SIZE = 0.08
COARSE_FIRST_TETRA_SUSPECT_SURFACE_ALGORITHM = 5
COARSE_FIRST_TETRA_GENERAL_SURFACE_ALGORITHM = 5
COARSE_FIRST_TETRA_FARFIELD_SURFACE_ALGORITHM = 5
SURFACE_REPAIR_CLASSIFY_ANGLE_DEGREES = 40.0
DEFAULT_MESH2D_WATCHDOG_TIMEOUT_SECONDS = 20.0
DEFAULT_MESH2D_WATCHDOG_SAMPLE_SECONDS = 1
DEFAULT_MESH3D_WATCHDOG_TIMEOUT_SECONDS = 20.0
DEFAULT_MESH3D_WATCHDOG_SAMPLE_SECONDS = 1
SURFACE_REPAIR_ERROR_SIGNATURES = (
    "plc error",
    "self-intersecting facets",
    "failed to recover constrained lines/triangles",
    "invalid boundary mesh (overlapping facets)",
)
PLC_INTERSECTION_POINT_PATTERN = re.compile(
    r"\(\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\)"
)
OVERLAP_SURFACE_PATTERN = re.compile(
    r"overlapping facets\)\s+on surface\s+(\d+)\s+surface\s+(\d+)",
    re.IGNORECASE,
)
LOGGER_FACET_TAG_PATTERN = re.compile(
    r"(?:1st|2nd):\s*\[[^\]]+\]\s*#(\d+)",
    re.IGNORECASE,
)
LAST_MESHING_SURFACE_PATTERN = re.compile(
    r"Meshing surface\s+(\d+)\b",
    re.IGNORECASE,
)


def _wall_marker_name_for_recipe(recipe: MeshRecipe) -> str:
    if recipe.component == "fairing_solid" and recipe.geometry_family == "closed_solid":
        return "fairing_solid"
    if (
        recipe.component in {"main_wing", "tail_wing", "horizontal_tail", "vertical_tail"}
        and recipe.geometry_family == "thin_sheet_lifting_surface"
    ):
        return recipe.component
    return "aircraft"
LAST_MESHING_CURVE_PATTERN = re.compile(
    r"Meshing curve\s+(\d+)\b",
    re.IGNORECASE,
)
THREE_D_MESHING_VOLUME_PATTERN = re.compile(
    r"3D Meshing\s+(\d+)\s+volume(?:s)?\s+with\s+(\d+)\s+connected component",
    re.IGNORECASE,
)
TETRAHEDRIZING_NODE_PATTERN = re.compile(
    r"Tetrahedrizing\s+(\d+)\s+nodes",
    re.IGNORECASE,
)
THREE_D_INSERTION_ITERATION_PATTERN = re.compile(
    r"It\.\s*(\d+)\s*-\s*(\d+)\s+nodes created\s*-\s*worst tet radius\s*([-+0-9.eE]+)"
    r"(?:\s*\(nodes removed\s*(\d+)\s*(\d+)\))?",
    re.IGNORECASE,
)
HXT_DELAUNAY_POINTS_PATTERN = re.compile(
    r"Delaunay of\s+(\d+)\s+points on\s+\d+\s+threads\s+-\s+mesh\.nvert:\s+(\d+)",
    re.IGNORECASE,
)
HXT_POINTS_FILTERED_PATTERN = re.compile(
    r"-\s+(\d+)\s+points filtered",
    re.IGNORECASE,
)
HXT_POINTS_ADDED_PATTERN = re.compile(
    r"=\s+(\d+)\s+points added",
    re.IGNORECASE,
)
ILL_SHAPED_TETS_PATTERN = re.compile(
    r"(\d+)\s+ill-shaped tets are still in the mesh",
    re.IGNORECASE,
)
MESH_ALGORITHM_NAME_LOOKUP = {
    1: "MeshAdapt",
    2: "Automatic",
    3: "Initial",
    5: "Delaunay",
    6: "Frontal-Delaunay",
    7: "BAMG",
    8: "Frontal-Delaunay for Quads",
    9: "Packing of Parallelograms",
    11: "Quasi-structured Quad",
}


class GmshBackendError(RuntimeError):
    """Raised when the real Gmsh backend cannot produce a mesh artifact."""


def _configure_gmsh_runtime_options(
    gmsh: Any,
    *,
    thread_count: int,
    terminal: bool = False,
    binary: bool = False,
) -> None:
    gmsh.option.setNumber("General.Terminal", float(int(bool(terminal))))
    gmsh.option.setNumber("Mesh.Binary", float(int(bool(binary))))
    gmsh.option.setNumber("General.NumThreads", float(max(1, int(thread_count))))


def _json_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _text_write(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(line) for line in lines), encoding="utf-8")


def _logger_tail(messages: Iterable[str], *, limit: int = 80) -> list[str]:
    materialized = [str(message) for message in messages]
    return materialized[-limit:]


def _extract_last_meshing_surface(logger_messages: Iterable[str]) -> Dict[str, Any] | None:
    materialized = [str(message) for message in logger_messages]
    for message in reversed(materialized):
        match = LAST_MESHING_SURFACE_PATTERN.search(message)
        if match is None:
            continue
        return {
            "surface_tag": int(match.group(1)),
            "message": message,
        }
    return None


def _extract_last_meshing_curve(logger_messages: Iterable[str]) -> Dict[str, Any] | None:
    materialized = [str(message) for message in logger_messages]
    for message in reversed(materialized):
        match = LAST_MESHING_CURVE_PATTERN.search(message)
        if match is None:
            continue
        return {
            "curve_tag": int(match.group(1)),
            "message": message,
        }
    return None


def _extract_3d_meshing_volume(logger_messages: Iterable[str]) -> Dict[str, Any] | None:
    materialized = [str(message) for message in logger_messages]
    for message in reversed(materialized):
        match = THREE_D_MESHING_VOLUME_PATTERN.search(message)
        if match is None:
            continue
        return {
            "volume_count": int(match.group(1)),
            "connected_component_count": int(match.group(2)),
            "message": message,
        }
    return None


def _extract_tetrahedrizing_node_count(logger_messages: Iterable[str]) -> Dict[str, Any] | None:
    materialized = [str(message) for message in logger_messages]
    for message in reversed(materialized):
        match = TETRAHEDRIZING_NODE_PATTERN.search(message)
        if match is None:
            continue
        return {
            "tetrahedrizing_node_count": int(match.group(1)),
            "message": message,
        }
    return None


def _extract_3d_insertion_iteration(logger_messages: Iterable[str]) -> Dict[str, Any] | None:
    materialized = [str(message) for message in logger_messages]
    for message in reversed(materialized):
        match = THREE_D_INSERTION_ITERATION_PATTERN.search(message)
        if match is None:
            continue
        return {
            "iteration_count": int(match.group(1)),
            "nodes_created": int(match.group(2)),
            "worst_tet_radius": float(match.group(3)),
            "nodes_removed": int(match.group(4)) if match.group(4) is not None else None,
            "nodes_removed_total": int(match.group(5)) if match.group(5) is not None else None,
            "message": message,
        }
    return None


def _extract_hxt_iteration_summary(logger_messages: Iterable[str]) -> Dict[str, Any] | None:
    materialized = [str(message) for message in logger_messages]
    delaunay_match = None
    delaunay_message = None
    points_filtered = None
    points_added = None
    for message in reversed(materialized):
        if points_added is None:
            match = HXT_POINTS_ADDED_PATTERN.search(message)
            if match is not None:
                points_added = int(match.group(1))
        if points_filtered is None:
            match = HXT_POINTS_FILTERED_PATTERN.search(message)
            if match is not None:
                points_filtered = int(match.group(1))
        if delaunay_match is None:
            match = HXT_DELAUNAY_POINTS_PATTERN.search(message)
            if match is not None:
                delaunay_match = match
                delaunay_message = message
        if delaunay_match is not None and points_added is not None and points_filtered is not None:
            break
    if delaunay_match is None:
        return None
    return {
        "points_considered": int(delaunay_match.group(1)),
        "mesh_vertex_count": int(delaunay_match.group(2)),
        "points_filtered": points_filtered,
        "points_added": points_added,
        "message": delaunay_message,
    }


def _extract_ill_shaped_tet_count(logger_messages: Iterable[str]) -> int:
    materialized = [str(message) for message in logger_messages]
    for message in reversed(materialized):
        match = ILL_SHAPED_TETS_PATTERN.search(message)
        if match is not None:
            return int(match.group(1))
    return 0


def _ratio_or_none(numerator: int | float | None, denominator: int | float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _coerce_int_flag(value: Any, *, default: int) -> int:
    if value is None:
        return int(default)
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        return 1 if int(value) != 0 else 0
    except (TypeError, ValueError):
        return 1 if bool(value) else 0


def _normalize_post_optimize_methods(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_values = [str(part).strip() for part in value]
    else:
        raw_values = [str(value).strip()]

    methods: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        if not raw_value or raw_value in seen:
            continue
        seen.add(raw_value)
        methods.append(raw_value)
    return methods


def _resolve_mesh_optimization_settings(config: MeshJobConfig) -> Dict[str, Any]:
    metadata = config.metadata if isinstance(config.metadata, dict) else {}
    threshold_raw = metadata.get("mesh_optimize_threshold")
    methods_raw = metadata.get("mesh_post_optimize_methods", metadata.get("mesh_post_optimize_method"))
    return {
        "mesh_optimize": _coerce_int_flag(metadata.get("mesh_optimize"), default=1),
        "mesh_optimize_netgen": _coerce_int_flag(metadata.get("mesh_optimize_netgen"), default=0),
        "mesh_optimize_threshold": (float(threshold_raw) if threshold_raw is not None else None),
        "post_optimize_methods": _normalize_post_optimize_methods(methods_raw),
        "post_optimize_force": bool(metadata.get("mesh_post_optimize_force", False)),
        "post_optimize_niter": max(1, int(metadata.get("mesh_post_optimize_niter", 1) or 1)),
    }


def _apply_mesh_optimization_options(gmsh, optimization_settings: Dict[str, Any]) -> None:
    gmsh.option.setNumber("Mesh.Optimize", float(int(optimization_settings.get("mesh_optimize", 1) or 0)))
    gmsh.option.setNumber(
        "Mesh.OptimizeNetgen",
        float(int(optimization_settings.get("mesh_optimize_netgen", 0) or 0)),
    )
    threshold = optimization_settings.get("mesh_optimize_threshold")
    if threshold is not None:
        gmsh.option.setNumber("Mesh.OptimizeThreshold", float(threshold))


def _run_post_generate3_optimizers(gmsh, optimization_settings: Dict[str, Any]) -> list[Dict[str, Any]]:
    force = bool(optimization_settings.get("post_optimize_force", False))
    niter = max(1, int(optimization_settings.get("post_optimize_niter", 1) or 1))
    runs: list[Dict[str, Any]] = []
    for method in optimization_settings.get("post_optimize_methods", []):
        method_name = str(method).strip()
        if not method_name:
            continue
        gmsh.model.mesh.optimize(method_name, force, niter)
        runs.append(
            {
                "method": method_name,
                "force": force,
                "niter": niter,
            }
        )
    return runs


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


def _extended_distribution_summary(values: Iterable[float | None]) -> Dict[str, Any]:
    usable = sorted(float(value) for value in values if value is not None)
    if not usable:
        return {
            "count": 0,
            "min": None,
            "p01": None,
            "p05": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        }
    return {
        "count": len(usable),
        "min": usable[0],
        "p01": _percentile(usable, 0.01),
        "p05": _percentile(usable, 0.05),
        "p50": _percentile(usable, 0.50),
        "p95": _percentile(usable, 0.95),
        "p99": _percentile(usable, 0.99),
        "max": usable[-1],
    }


def _primary_node_slices(gmsh, element_type: int, element_tags: Iterable[int], node_tags_flat: Iterable[int]) -> list[tuple[int, list[int]]]:
    _, _, _, num_nodes, _, num_primary_nodes = gmsh.model.mesh.getElementProperties(int(element_type))
    node_count = int(num_nodes)
    primary_count = int(num_primary_nodes)
    materialized_tags = [int(tag) for tag in element_tags]
    materialized_nodes = [int(tag) for tag in node_tags_flat]
    slices: list[tuple[int, list[int]]] = []
    for index, element_tag in enumerate(materialized_tags):
        start = index * node_count
        element_node_tags = materialized_nodes[start : start + node_count]
        slices.append((int(element_tag), [int(tag) for tag in element_node_tags[:primary_count]]))
    return slices


def _get_node_coordinate(gmsh, node_tag: int, *, cache: Dict[int, list[float]]) -> list[float]:
    cached = cache.get(int(node_tag))
    if cached is not None:
        return cached
    coord, *_ = gmsh.model.mesh.getNode(int(node_tag))
    payload = [float(coord[0]), float(coord[1]), float(coord[2])]
    cache[int(node_tag)] = payload
    return payload


def _point_distance(point_a: Iterable[float], point_b: Iterable[float]) -> float:
    coord_a = [float(value) for value in point_a]
    coord_b = [float(value) for value in point_b]
    return math.sqrt(
        (coord_a[0] - coord_b[0]) ** 2
        + (coord_a[1] - coord_b[1]) ** 2
        + (coord_a[2] - coord_b[2]) ** 2
    )


def _triangle_metrics(points: list[list[float]]) -> Dict[str, float | None]:
    if len(points) < 3:
        return {
            "area": None,
            "gamma": None,
            "aspect_ratio": None,
            "min_edge_length": None,
            "max_edge_length": None,
        }
    edges = [
        _point_distance(points[0], points[1]),
        _point_distance(points[1], points[2]),
        _point_distance(points[2], points[0]),
    ]
    vector_ab = [points[1][axis] - points[0][axis] for axis in range(3)]
    vector_ac = [points[2][axis] - points[0][axis] for axis in range(3)]
    cross = [
        vector_ab[1] * vector_ac[2] - vector_ab[2] * vector_ac[1],
        vector_ab[2] * vector_ac[0] - vector_ab[0] * vector_ac[2],
        vector_ab[0] * vector_ac[1] - vector_ab[1] * vector_ac[0],
    ]
    area = 0.5 * math.sqrt(sum(component * component for component in cross))
    edge_sum_sq = sum(edge * edge for edge in edges)
    gamma = (4.0 * math.sqrt(3.0) * area / edge_sum_sq) if edge_sum_sq > 0.0 else None
    min_edge_length = min(edges) if edges else None
    max_edge_length = max(edges) if edges else None
    aspect_ratio = (
        max_edge_length / min_edge_length
        if min_edge_length is not None and min_edge_length > 0.0 and max_edge_length is not None
        else None
    )
    return {
        "area": float(area),
        "gamma": float(gamma) if gamma is not None else None,
        "aspect_ratio": float(aspect_ratio) if aspect_ratio is not None else None,
        "min_edge_length": float(min_edge_length) if min_edge_length is not None else None,
        "max_edge_length": float(max_edge_length) if max_edge_length is not None else None,
    }


def _tetra_edge_metrics(points: list[list[float]]) -> Dict[str, float | None]:
    if len(points) < 4:
        return {"min_edge_length": None, "max_edge_length": None}
    lengths = [
        _point_distance(points[first], points[second])
        for first, second in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    ]
    return {
        "min_edge_length": float(min(lengths)) if lengths else None,
        "max_edge_length": float(max(lengths)) if lengths else None,
    }


def _nearest_surface_payload(
    gmsh,
    *,
    point: list[float],
    surface_tag_to_name: Dict[int, str],
) -> Dict[str, Any] | None:
    best_match: Dict[str, Any] | None = None
    for surface_tag, physical_name in surface_tag_to_name.items():
        try:
            closest_coord, _ = gmsh.model.getClosestPoint(2, int(surface_tag), point)
        except Exception:
            continue
        if len(closest_coord) < 3:
            continue
        closest_point = [float(closest_coord[0]), float(closest_coord[1]), float(closest_coord[2])]
        distance = math.sqrt(
            (closest_point[0] - point[0]) ** 2
            + (closest_point[1] - point[1]) ** 2
            + (closest_point[2] - point[2]) ** 2
        )
        candidate = {
            "surface_tag": int(surface_tag),
            "physical_name": str(physical_name),
            "distance": float(distance),
            "closest_point": closest_point,
        }
        if best_match is None or candidate["distance"] < best_match["distance"]:
            best_match = candidate
    return best_match


def _nearest_curve_payload(
    gmsh,
    *,
    point: list[float],
    curve_tags: Iterable[int],
) -> Dict[str, Any] | None:
    best_match: Dict[str, Any] | None = None
    for curve_tag in curve_tags:
        try:
            closest_coord, _ = gmsh.model.getClosestPoint(1, int(curve_tag), point)
        except Exception:
            continue
        if len(closest_coord) < 3:
            continue
        closest_point = [float(closest_coord[0]), float(closest_coord[1]), float(closest_coord[2])]
        distance = _point_distance(closest_point, point)
        candidate = {
            "curve_tag": int(curve_tag),
            "distance": float(distance),
            "closest_point": closest_point,
        }
        if best_match is None or candidate["distance"] < best_match["distance"]:
            best_match = candidate
    return best_match


def _collect_surface_triangle_mesh_stats(gmsh, surface_tag: int) -> Dict[str, Any]:
    node_cache: Dict[int, list[float]] = {}
    triangle_areas: list[float] = []
    triangle_gamma: list[float] = []
    triangle_aspect_ratios: list[float] = []
    triangle_min_edges: list[float] = []
    triangle_max_edges: list[float] = []
    triangle_element_tags: list[int] = []
    element_types, element_tags_groups, node_tags_groups = gmsh.model.mesh.getElements(2, int(surface_tag))
    for element_type, element_tags, node_tags_flat in zip(element_types, element_tags_groups, node_tags_groups):
        _, dim, _, _, _, num_primary_nodes = gmsh.model.mesh.getElementProperties(int(element_type))
        if int(dim) != 2 or int(num_primary_nodes) != 3:
            continue
        for element_tag, node_tags in _primary_node_slices(gmsh, int(element_type), element_tags, node_tags_flat):
            points = [_get_node_coordinate(gmsh, node_tag, cache=node_cache) for node_tag in node_tags]
            metrics = _triangle_metrics(points)
            triangle_element_tags.append(int(element_tag))
            triangle_areas.append(float(metrics["area"]) if metrics["area"] is not None else 0.0)
            if metrics["gamma"] is not None:
                triangle_gamma.append(float(metrics["gamma"]))
            if metrics["aspect_ratio"] is not None:
                triangle_aspect_ratios.append(float(metrics["aspect_ratio"]))
            if metrics["min_edge_length"] is not None:
                triangle_min_edges.append(float(metrics["min_edge_length"]))
            if metrics["max_edge_length"] is not None:
                triangle_max_edges.append(float(metrics["max_edge_length"]))

    return {
        "triangle_count": len(triangle_element_tags),
        "min_area": min(triangle_areas) if triangle_areas else None,
        "gamma": _extended_distribution_summary(triangle_gamma),
        "aspect_ratio": _extended_distribution_summary(triangle_aspect_ratios),
        "min_edge_length": min(triangle_min_edges) if triangle_min_edges else None,
        "max_edge_length": max(triangle_max_edges) if triangle_max_edges else None,
    }


def _collect_curve_mesh_stats(gmsh, curve_tag: int) -> Dict[str, Any]:
    node_cache: Dict[int, list[float]] = {}
    edge_lengths: list[float] = []
    node_tags_seen: set[int] = set()
    element_types, element_tags_groups, node_tags_groups = gmsh.model.mesh.getElements(1, int(curve_tag))
    for element_type, element_tags, node_tags_flat in zip(element_types, element_tags_groups, node_tags_groups):
        _, dim, _, _, _, num_primary_nodes = gmsh.model.mesh.getElementProperties(int(element_type))
        if int(dim) != 1 or int(num_primary_nodes) < 2:
            continue
        for _, node_tags in _primary_node_slices(gmsh, int(element_type), element_tags, node_tags_flat):
            if len(node_tags) < 2:
                continue
            start = _get_node_coordinate(gmsh, node_tags[0], cache=node_cache)
            end = _get_node_coordinate(gmsh, node_tags[1], cache=node_cache)
            edge_lengths.append(_point_distance(start, end))
            node_tags_seen.update(int(tag) for tag in node_tags[:2])

    min_edge_length = min(edge_lengths) if edge_lengths else None
    max_edge_length = max(edge_lengths) if edge_lengths else None
    return {
        "node_count": len(node_tags_seen),
        "min_edge_length": min_edge_length,
        "max_edge_length": max_edge_length,
        "max_min_edge_ratio": (
            float(max_edge_length) / float(min_edge_length)
            if min_edge_length is not None and min_edge_length > 0.0 and max_edge_length is not None
            else None
        ),
    }


def _surface_target_size_hint(surface_tag: int, mesh_field: Dict[str, Any] | None) -> float | None:
    if not isinstance(mesh_field, dict):
        return None
    candidate_sizes: list[float] = []
    near_body_size = mesh_field.get("near_body_size")
    if near_body_size is not None:
        candidate_sizes.append(float(near_body_size))
    for entry in mesh_field.get("local_size_floors", []):
        if int(surface_tag) in {int(tag) for tag in entry.get("surface_tags", [])}:
            size = entry.get("size")
            if size is not None:
                candidate_sizes.append(float(size))
    if not candidate_sizes:
        return None
    return max(candidate_sizes)


def _collect_hotspot_patch_report(
    gmsh,
    *,
    surface_patch_diagnostics: Dict[str, Any] | None,
    quality_metrics: Dict[str, Any] | None,
    mesh_field: Dict[str, Any] | None = None,
    requested_surface_tags: Iterable[int] | None = None,
    top_surface_count: int = 4,
) -> Dict[str, Any]:
    surface_records = {
        int(record["tag"]): record
        for record in (surface_patch_diagnostics or {}).get("surface_records", [])
        if isinstance(record, dict) and record.get("tag") is not None
    }
    curve_records = {
        int(record["tag"]): record
        for record in (surface_patch_diagnostics or {}).get("curve_records", [])
        if isinstance(record, dict) and record.get("tag") is not None
    }
    worst_tets = [
        entry
        for entry in (quality_metrics or {}).get("worst_20_tets", [])
        if isinstance(entry, dict)
    ]

    requested = []
    seen_surface_tags: set[int] = set()
    for tag in requested_surface_tags or []:
        materialized = int(tag)
        if materialized in seen_surface_tags:
            continue
        seen_surface_tags.add(materialized)
        requested.append(materialized)

    hotspot_surface_counts: Dict[int, int] = defaultdict(int)
    ranked_surface_tags: list[int] = []
    for entry in worst_tets:
        nearest_surface = entry.get("nearest_surface")
        if not isinstance(nearest_surface, dict) or nearest_surface.get("surface_tag") is None:
            continue
        surface_tag = int(nearest_surface["surface_tag"])
        hotspot_surface_counts[surface_tag] += 1
        if surface_tag not in ranked_surface_tags:
            ranked_surface_tags.append(surface_tag)

    selection_limit = max(int(top_surface_count), len(requested), 1)
    selected_surface_tags: list[int] = []
    for surface_tag in requested + ranked_surface_tags:
        if surface_tag in selected_surface_tags:
            continue
        selected_surface_tags.append(int(surface_tag))
        if len(selected_surface_tags) >= selection_limit:
            break

    surface_reports: list[Dict[str, Any]] = []
    for surface_tag in selected_surface_tags:
        record = surface_records.get(int(surface_tag), {})
        curve_tags = [int(tag) for tag in record.get("curve_tags", [])]
        surface_triangle_stats = _collect_surface_triangle_mesh_stats(gmsh, int(surface_tag))
        boundary_curves = []
        for curve_tag in curve_tags:
            boundary_curves.append(
                {
                    "curve_id": int(curve_tag),
                    "curve_length": curve_records.get(int(curve_tag), {}).get("length"),
                    "owner_surface_tags": curve_records.get(int(curve_tag), {}).get("owner_surface_tags", []),
                    **_collect_curve_mesh_stats(gmsh, int(curve_tag)),
                }
            )
        adjacent_surfaces = sorted(
            {
                int(owner_surface_tag)
                for curve_tag in curve_tags
                for owner_surface_tag in curve_records.get(int(curve_tag), {}).get("owner_surface_tags", [])
                if int(owner_surface_tag) != int(surface_tag)
            }
        )
        worst_entries = []
        for entry in worst_tets:
            nearest_surface = entry.get("nearest_surface")
            if not isinstance(nearest_surface, dict) or int(nearest_surface.get("surface_tag", -1)) != int(surface_tag):
                continue
            nearest_curve = _nearest_curve_payload(
                gmsh,
                point=[float(value) for value in entry.get("barycenter", [0.0, 0.0, 0.0])],
                curve_tags=curve_tags,
            )
            worst_entries.append(
                {
                    "element_id": int(entry["element_id"]),
                    "barycenter": [float(value) for value in entry.get("barycenter", [])],
                    "distance_to_surface": nearest_surface.get("distance"),
                    "nearest_surface_id": int(surface_tag),
                    "nearest_curve_id": (
                        int(nearest_curve["curve_tag"])
                        if isinstance(nearest_curve, dict) and nearest_curve.get("curve_tag") is not None
                        else None
                    ),
                    "local_tetra_edge_length_min": entry.get("tetra_edge_length_min"),
                    "local_tetra_edge_length_max": entry.get("tetra_edge_length_max"),
                    "min_sicn": entry.get("min_sicn"),
                    "min_sige": entry.get("min_sige"),
                    "gamma": entry.get("gamma"),
                    "volume": entry.get("volume"),
                }
            )

        surface_reports.append(
            {
                "surface_id": int(surface_tag),
                "surface_area": record.get("area"),
                "surface_bbox": record.get("bbox"),
                "surface_role": record.get("surface_role"),
                "surface_triangle_count": surface_triangle_stats.get("triangle_count"),
                "surface_triangle_quality": surface_triangle_stats,
                "boundary_curves": boundary_curves,
                "adjacent_surfaces": adjacent_surfaces,
                "local_target_size_hint": _surface_target_size_hint(int(surface_tag), mesh_field),
                "family_hints": record.get("family_hints", []),
                "worst_tets_near_this_surface": {
                    "count": len(worst_entries),
                    "min_gamma": min((entry["gamma"] for entry in worst_entries), default=None),
                    "min_sicn": min((entry["min_sicn"] for entry in worst_entries), default=None),
                    "min_sige": min((entry["min_sige"] for entry in worst_entries), default=None),
                    "min_volume": min((entry["volume"] for entry in worst_entries), default=None),
                    "entries": worst_entries,
                },
            }
        )

    return {
        "status": "captured",
        "requested_surface_tags": requested,
        "selected_surface_tags": selected_surface_tags,
        "hotspot_surface_counts": dict(sorted(hotspot_surface_counts.items())),
        "surface_reports": surface_reports,
    }


def _collect_volume_quality_metrics(
    gmsh,
    *,
    marker_summary: Dict[str, Any] | None = None,
    physical_groups: Dict[str, Any] | None = None,
    logger_messages: Iterable[str] | None = None,
    worst_count: int = 20,
) -> Dict[str, Any]:
    volume_types, volume_element_tags, volume_node_tags = gmsh.model.mesh.getElements(3)
    tetra_tags: list[int] = []
    tetra_node_tags_lookup: Dict[int, list[int]] = {}
    for element_type, tags, node_tags_flat in zip(volume_types, volume_element_tags, volume_node_tags):
        if int(element_type) != 4:
            continue
        tetra_tags.extend(int(tag) for tag in tags)
        tetra_node_tags_lookup.update(
            {
                int(element_tag): [int(node_tag) for node_tag in node_tags]
                for element_tag, node_tags in _primary_node_slices(gmsh, int(element_type), tags, node_tags_flat)
            }
        )

    if not tetra_tags:
        return {
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
            "worst_20_tets": [],
        }

    min_sicn = [float(value) for value in gmsh.model.mesh.getElementQualities(tetra_tags, "minSICN")]
    min_sige = [float(value) for value in gmsh.model.mesh.getElementQualities(tetra_tags, "minSIGE")]
    gamma = [float(value) for value in gmsh.model.mesh.getElementQualities(tetra_tags, "gamma")]
    volume = [float(value) for value in gmsh.model.mesh.getElementQualities(tetra_tags, "volume")]
    barycenters_raw = gmsh.model.mesh.getBarycenters(4, -1, False, True)
    barycenters = [
        [
            float(barycenters_raw[index * 3]),
            float(barycenters_raw[index * 3 + 1]),
            float(barycenters_raw[index * 3 + 2]),
        ]
        for index in range(len(tetra_tags))
    ]

    surface_tag_to_name: Dict[int, str] = {}
    for marker_name, payload in (marker_summary or {}).items():
        if not isinstance(payload, dict) or not payload.get("exists"):
            continue
        physical_name = str(payload.get("physical_name") or marker_name)
        for entity in payload.get("entities", []):
            surface_tag_to_name[int(entity)] = physical_name

    physical_volume_name = None
    if isinstance(physical_groups, dict):
        for payload in physical_groups.values():
            if not isinstance(payload, dict) or not payload.get("exists"):
                continue
            if int(payload.get("dimension", -1) or -1) != 3:
                continue
            physical_volume_name = str(payload.get("physical_name") or "fluid")
            break
    if physical_volume_name is None:
        physical_volume_name = "fluid"

    worst_entries: list[Dict[str, Any]] = []
    for index, element_tag in enumerate(tetra_tags):
        barycenter = barycenters[index]
        worst_entries.append(
            {
                "element_id": int(element_tag),
                "barycenter": barycenter,
                "min_sicn": min_sicn[index],
                "min_sige": min_sige[index],
                "gamma": gamma[index],
                "volume": volume[index],
                "physical_volume_name": physical_volume_name,
            }
        )

    worst_entries.sort(
        key=lambda entry: (
            float(entry["min_sicn"]),
            float(entry["min_sige"]),
            float(entry["gamma"]),
            float(entry["volume"]),
            int(entry["element_id"]),
        )
    )

    fallback_ill_shaped_count = sum(
        1
        for sicn_value, sige_value, volume_value in zip(min_sicn, min_sige, volume)
        if sicn_value <= 0.0 or sige_value <= 0.0 or volume_value <= 0.0
    )
    logged_ill_shaped_count = _extract_ill_shaped_tet_count(logger_messages or [])

    worst_subset = worst_entries[: max(0, int(worst_count))]
    node_cache: Dict[int, list[float]] = {}
    if surface_tag_to_name:
        for entry in worst_subset:
            entry["nearest_surface"] = _nearest_surface_payload(
                gmsh,
                point=[float(value) for value in entry["barycenter"]],
                surface_tag_to_name=surface_tag_to_name,
            )
    else:
        for entry in worst_subset:
            entry["nearest_surface"] = None
    for entry in worst_subset:
        corner_node_tags = tetra_node_tags_lookup.get(int(entry["element_id"]), [])
        entry["corner_node_tags"] = list(corner_node_tags)
        tetra_points = [_get_node_coordinate(gmsh, node_tag, cache=node_cache) for node_tag in corner_node_tags]
        edge_metrics = _tetra_edge_metrics(tetra_points)
        entry["tetra_edge_length_min"] = edge_metrics["min_edge_length"]
        entry["tetra_edge_length_max"] = edge_metrics["max_edge_length"]

    return {
        "tetrahedron_count": len(tetra_tags),
        "ill_shaped_tet_count": int(logged_ill_shaped_count or fallback_ill_shaped_count),
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
        "worst_20_tets": worst_subset,
    }


def _classify_3d_timeout_phase(logger_messages: Iterable[str]) -> str:
    phase = "unknown"
    for message in logger_messages:
        lowered = str(message).lower()
        if "recover" in lowered:
            phase = "boundary_recovery"
        if THREE_D_INSERTION_ITERATION_PATTERN.search(str(message)) or "tetrahedriz" in lowered:
            phase = "volume_insertion"
        if (
            HXT_DELAUNAY_POINTS_PATTERN.search(str(message))
            or HXT_POINTS_ADDED_PATTERN.search(str(message))
            or HXT_POINTS_FILTERED_PATTERN.search(str(message))
        ):
            phase = "volume_insertion"
        if "optimiz" in lowered:
            phase = "optimization"
        if "writing" in lowered or "saving" in lowered:
            phase = "write_out"
    return phase


def _extract_3d_burden_metrics(
    logger_messages: Iterable[str],
    pre_mesh_stats: Dict[str, Any] | None,
) -> Dict[str, Any]:
    pre_mesh_stats = dict(pre_mesh_stats or {})
    boundary_node_count = int(pre_mesh_stats.get("node_count", 0) or 0)
    surface_triangle_count = int(pre_mesh_stats.get("surface_element_count", 0) or 0)
    iteration_summary = _extract_3d_insertion_iteration(logger_messages)
    hxt_summary = _extract_hxt_iteration_summary(logger_messages)
    metrics: Dict[str, Any] = {
        "boundary_node_count": boundary_node_count,
        "surface_triangle_count": surface_triangle_count,
        "timeout_phase_classification": _classify_3d_timeout_phase(logger_messages),
    }
    if iteration_summary is not None:
        metrics["iteration_count"] = int(iteration_summary["iteration_count"])
        metrics["nodes_created"] = int(iteration_summary["nodes_created"])
        metrics["nodes_created_per_boundary_node"] = _ratio_or_none(
            int(iteration_summary["nodes_created"]),
            boundary_node_count,
        )
        metrics["iterations_per_surface_triangle"] = _ratio_or_none(
            int(iteration_summary["iteration_count"]),
            surface_triangle_count,
        )
        metrics["latest_iteration_message"] = str(iteration_summary["message"])
        metrics["latest_worst_tet_radius"] = float(iteration_summary["worst_tet_radius"])
        if iteration_summary.get("nodes_removed") is not None:
            metrics["nodes_removed"] = int(iteration_summary["nodes_removed"])
        if iteration_summary.get("nodes_removed_total") is not None:
            metrics["nodes_removed_total"] = int(iteration_summary["nodes_removed_total"])
    elif hxt_summary is not None:
        if hxt_summary.get("points_added") is not None:
            metrics["nodes_created"] = int(hxt_summary["points_added"])
            metrics["nodes_created_per_boundary_node"] = _ratio_or_none(
                int(hxt_summary["points_added"]),
                boundary_node_count,
            )
            metrics["hxt_points_added"] = int(hxt_summary["points_added"])
        if hxt_summary.get("points_filtered") is not None:
            metrics["hxt_points_filtered"] = int(hxt_summary["points_filtered"])
        metrics["hxt_points_considered"] = int(hxt_summary["points_considered"])
        metrics["hxt_mesh_vertex_count"] = int(hxt_summary["mesh_vertex_count"])
        metrics["latest_iteration_message"] = str(hxt_summary["message"])
    return metrics


def _infer_meshing_stage(logger_messages: Iterable[str]) -> str | None:
    stage: str | None = None
    for message in logger_messages:
        text = str(message).lower()
        if "meshing 1d" in text:
            stage = "meshing_1d"
        elif "done meshing 1d" in text:
            stage = "completed_1d"
        elif "meshing 2d" in text:
            stage = "meshing_2d"
        elif "done meshing 2d" in text:
            stage = "completed_2d"
        elif "meshing 3d" in text:
            stage = "meshing_3d"
        elif "done meshing 3d" in text:
            stage = "completed_3d"
    return stage


def _run_process_sample(pid: int, sample_seconds: int, output_path: Path) -> Dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample_bin = Path("/usr/bin/sample")
    if not sample_bin.exists():
        return {
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": "sample binary not available at /usr/bin/sample",
        }
    completed = subprocess.run(
        [str(sample_bin), str(int(pid)), str(max(int(sample_seconds), 1)), "-file", str(output_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "returncode": int(completed.returncode),
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
    }


def _bbox_for_entities(gmsh, dim_tags: Iterable[tuple[int, int]]) -> tuple[list[float], list[float]]:
    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    has_entity = False
    for dim, tag in dim_tags:
        has_entity = True
        x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(dim, tag)
        mins[0] = min(mins[0], float(x_min))
        mins[1] = min(mins[1], float(y_min))
        mins[2] = min(mins[2], float(z_min))
        maxs[0] = max(maxs[0], float(x_max))
        maxs[1] = max(maxs[1], float(y_max))
        maxs[2] = max(maxs[2], float(z_max))
    if not has_entity:
        raise GmshBackendError("Gmsh entity list is empty.")
    return mins, maxs


def _bounds_dict(mins: list[float], maxs: list[float]) -> dict[str, float]:
    return {
        "x_min": mins[0],
        "x_max": maxs[0],
        "y_min": mins[1],
        "y_max": maxs[1],
        "z_min": mins[2],
        "z_max": maxs[2],
    }


def _bounds_model(mins: list[float], maxs: list[float]) -> Bounds3D:
    return Bounds3D(**_bounds_dict(mins, maxs))


def _entity_dim_tags_payload(dim_tags: Iterable[tuple[int, int]]) -> list[dict[str, int]]:
    return [{"dim": int(dim), "tag": int(tag)} for dim, tag in dim_tags]


def _entity_bbox_payload(gmsh, dim: int, tag: int) -> Dict[str, Any]:
    x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(int(dim), int(tag))
    return {
        "dim": int(dim),
        "tag": int(tag),
        "bbox": {
            "x_min": float(x_min),
            "y_min": float(y_min),
            "z_min": float(z_min),
            "x_max": float(x_max),
            "y_max": float(y_max),
            "z_max": float(z_max),
        },
    }


def _safe_occ_mass(gmsh, dim: int, tag: int) -> float | None:
    try:
        return float(gmsh.model.occ.getMass(int(dim), int(tag)))
    except Exception:
        return None


def _surface_patch_excerpt(surface_record: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if surface_record is None:
        return None
    return {
        "tag": int(surface_record["tag"]),
        "area": surface_record.get("area"),
        "min_curve_length": surface_record.get("min_curve_length"),
        "aspect_ratio_proxy": surface_record.get("aspect_ratio_proxy"),
        "flat_axis": surface_record.get("flat_axis"),
        "family_hints": list(surface_record.get("family_hints", [])),
        "bbox": surface_record.get("bbox"),
    }


def _farfield_bounds(mins: list[float], maxs: list[float], farfield: FarfieldConfig) -> dict[str, float]:
    x_span = max(maxs[0] - mins[0], 1e-6)
    y_span = max(maxs[1] - mins[1], 1e-6)
    z_span = max(maxs[2] - mins[2], 1e-6)
    return {
        "x_min": mins[0] - farfield.upstream_factor * x_span,
        "x_max": maxs[0] + farfield.downstream_factor * x_span,
        "y_min": mins[1] - farfield.lateral_factor * y_span,
        "y_max": maxs[1] + farfield.lateral_factor * y_span,
        "z_min": mins[2] - farfield.vertical_factor * z_span,
        "z_max": maxs[2] + farfield.vertical_factor * z_span,
    }


def _dominant_span_axis(bounds: Bounds3D | None) -> tuple[str, float] | None:
    if bounds is None:
        return None
    spans = {
        "x": float(bounds.x_max) - float(bounds.x_min),
        "y": float(bounds.y_max) - float(bounds.y_min),
        "z": float(bounds.z_max) - float(bounds.z_min),
    }
    positive = [
        (axis, span)
        for axis, span in spans.items()
        if math.isfinite(span) and span > 1.0e-12
    ]
    if not positive:
        return None
    positive.sort(key=lambda item: item[1], reverse=True)
    return positive[0]


def _import_scale_to_units(handle: GeometryHandle) -> tuple[float, str | None]:
    provider_result = handle.provider_result
    if provider_result is None:
        return 1.0, None
    topology = provider_result.topology
    scale = topology.import_scale_to_units
    if scale is None or scale <= 0.0:
        dominant_bounds = _dominant_span_axis(topology.bounds)
        dominant_import_bounds = _dominant_span_axis(topology.import_bounds)
        if (
            dominant_bounds is not None
            and dominant_import_bounds is not None
            and dominant_bounds[0] == dominant_import_bounds[0]
        ):
            inferred_scale = dominant_bounds[1] / dominant_import_bounds[1]
            if math.isfinite(inferred_scale) and inferred_scale > 0.0:
                if abs(inferred_scale - 1.0) <= 1.0e-6:
                    return 1.0, topology.units
                return float(inferred_scale), topology.units
        return 1.0, topology.units
    return float(scale), topology.units


def _boundary_surface_tags(gmsh, dim_tags: Iterable[tuple[int, int]]) -> list[int]:
    boundary = gmsh.model.getBoundary(list(dim_tags), oriented=False, recursive=False)
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


def _classify_outer_boundary_surfaces(
    gmsh,
    surface_tags: list[int],
    bounds: dict[str, float],
) -> tuple[list[int], list[int]]:
    spans = (
        bounds["x_max"] - bounds["x_min"],
        bounds["y_max"] - bounds["y_min"],
        bounds["z_max"] - bounds["z_min"],
    )
    tolerance = max(max(spans), 1.0) * 1e-6
    farfield_surface_tags: list[int] = []
    aircraft_surface_tags: list[int] = []

    for surface_tag in surface_tags:
        x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(2, surface_tag)
        is_box_face = any(
            (
                abs(float(entity_min) - target) <= tolerance
                and abs(float(entity_max) - target) <= tolerance
            )
            for entity_min, entity_max, target in (
                (x_min, x_max, bounds["x_min"]),
                (x_min, x_max, bounds["x_max"]),
                (y_min, y_max, bounds["y_min"]),
                (y_min, y_max, bounds["y_max"]),
                (z_min, z_max, bounds["z_min"]),
                (z_min, z_max, bounds["z_max"]),
            )
        )
        if is_box_face:
            farfield_surface_tags.append(surface_tag)
        else:
            aircraft_surface_tags.append(surface_tag)
    return aircraft_surface_tags, farfield_surface_tags


def _aircraft_curve_tags(gmsh, aircraft_surface_tags: list[int]) -> list[int]:
    curve_dim_tags = gmsh.model.getBoundary([(2, tag) for tag in aircraft_surface_tags], oriented=False, recursive=False)
    curve_tags: list[int] = []
    seen: set[int] = set()
    for dim, tag in curve_dim_tags:
        if dim != 1:
            continue
        curve_tag = int(tag)
        if curve_tag in seen:
            continue
        seen.add(curve_tag)
        curve_tags.append(curve_tag)
    return curve_tags


def _surface_connectivity_summary(gmsh, surface_tags: list[int]) -> Dict[str, Any]:
    curve_to_surfaces: dict[int, list[int]] = defaultdict(list)
    for surface_tag in surface_tags:
        boundary = gmsh.model.getBoundary([(2, int(surface_tag))], oriented=False, recursive=False)
        seen_curves: set[int] = set()
        for dim, tag in boundary:
            if dim != 1:
                continue
            curve_tag = int(tag)
            if curve_tag in seen_curves:
                continue
            seen_curves.add(curve_tag)
            curve_to_surfaces[curve_tag].append(int(surface_tag))

    free_curve_tags = sorted(tag for tag, owners in curve_to_surfaces.items() if len(owners) == 1)
    non_manifold_curve_tags = sorted(tag for tag, owners in curve_to_surfaces.items() if len(owners) > 2)
    return {
        "surface_count": len(surface_tags),
        "curve_count": len(curve_to_surfaces),
        "free_curve_count": len(free_curve_tags),
        "free_curve_tags_sample": free_curve_tags[:25],
        "non_manifold_curve_count": len(non_manifold_curve_tags),
        "non_manifold_curve_tags_sample": non_manifold_curve_tags[:25],
    }


def _distribution_summary(values: Iterable[float | None]) -> Dict[str, Any]:
    usable = sorted(float(value) for value in values if value is not None)
    if not usable:
        return {
            "count": 0,
            "min": None,
            "p05": None,
            "p50": None,
            "p95": None,
            "max": None,
        }

    def _pick(frac: float) -> float:
        index = min(len(usable) - 1, max(0, int(round((len(usable) - 1) * frac))))
        return usable[index]

    return {
        "count": len(usable),
        "min": usable[0],
        "p05": _pick(0.05),
        "p50": _pick(0.50),
        "p95": _pick(0.95),
        "max": usable[-1],
    }


def _bbox_union(bboxes: Iterable[Dict[str, float]]) -> Dict[str, float] | None:
    materialized = [bbox for bbox in bboxes]
    if not materialized:
        return None
    return {
        "x_min": min(float(bbox["x_min"]) for bbox in materialized),
        "y_min": min(float(bbox["y_min"]) for bbox in materialized),
        "z_min": min(float(bbox["z_min"]) for bbox in materialized),
        "x_max": max(float(bbox["x_max"]) for bbox in materialized),
        "y_max": max(float(bbox["y_max"]) for bbox in materialized),
        "z_max": max(float(bbox["z_max"]) for bbox in materialized),
    }


def _surface_family_groups(surface_records: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    grouped: dict[tuple[str, ...], Dict[str, Any]] = {}
    for record in surface_records:
        family_hints = tuple(sorted(str(hint) for hint in record.get("family_hints", [])))
        if not family_hints:
            continue
        group = grouped.setdefault(
            family_hints,
            {
                "family_hints": list(family_hints),
                "member_tags": [],
                "member_count": 0,
                "surface_roles": set(),
                "bbox_samples": [],
                "suspect_score_max": 0.0,
                "suspect_score_sum": 0.0,
                "short_curve_count_total": 0,
            },
        )
        group["member_tags"].append(int(record["tag"]))
        group["member_count"] += 1
        group["surface_roles"].add(str(record.get("surface_role", "aircraft")))
        group["bbox_samples"].append(record["bbox"])
        group["suspect_score_max"] = max(group["suspect_score_max"], float(record["suspect_score"]))
        group["suspect_score_sum"] += float(record["suspect_score"])
        group["short_curve_count_total"] += int(record.get("short_curve_count", 0))

    families: list[Dict[str, Any]] = []
    for group in grouped.values():
        families.append(
            {
                "family_hints": group["family_hints"],
                "member_tags": sorted(group["member_tags"]),
                "member_count": int(group["member_count"]),
                "surface_roles": sorted(group["surface_roles"]),
                "bbox_union": _bbox_union(group["bbox_samples"]),
                "suspect_score_max": float(group["suspect_score_max"]),
                "suspect_score_sum": float(group["suspect_score_sum"]),
                "short_curve_count_total": int(group["short_curve_count_total"]),
            }
        )

    return sorted(
        families,
        key=lambda record: (
            -float(record["suspect_score_max"]),
            -int(record["member_count"]),
            -float(record["suspect_score_sum"]),
            tuple(record["family_hints"]),
        ),
    )


def _collect_surface_patch_diagnostics(
    gmsh,
    *,
    surface_tags: list[int],
    reference_length: float,
    near_body_size: float,
    surface_role_lookup: Dict[int, str] | None = None,
) -> Dict[str, Any]:
    surface_to_curves: dict[int, list[int]] = {}
    curve_to_surfaces: dict[int, list[int]] = defaultdict(list)
    for surface_tag in surface_tags:
        curves: list[int] = []
        seen_curves: set[int] = set()
        boundary = gmsh.model.getBoundary([(2, int(surface_tag))], oriented=False, recursive=False)
        for dim, tag in boundary:
            if int(dim) != 1:
                continue
            curve_tag = int(tag)
            if curve_tag in seen_curves:
                continue
            seen_curves.add(curve_tag)
            curves.append(curve_tag)
            curve_to_surfaces[curve_tag].append(int(surface_tag))
        surface_to_curves[int(surface_tag)] = curves

    aircraft_mins, aircraft_maxs = _bbox_for_entities(gmsh, [(2, int(tag)) for tag in surface_tags])
    edge_size = near_body_size * DEFAULT_EDGE_REFINEMENT_RATIO
    short_curve_threshold = max(edge_size * 0.5, reference_length * 5.0e-4, 1.0e-6)
    tiny_face_area_threshold = max(reference_length * near_body_size * 0.5, edge_size * edge_size, 1.0e-8)
    extrema_tol = max(reference_length * 1.0e-3, near_body_size * 0.5, 1.0e-6)

    curve_records: list[Dict[str, Any]] = []
    curve_length_lookup: dict[int, float | None] = {}
    for curve_tag, owner_surface_tags in curve_to_surfaces.items():
        curve_length = _safe_occ_mass(gmsh, 1, curve_tag)
        curve_length_lookup[curve_tag] = curve_length
        curve_records.append(
            {
                "tag": int(curve_tag),
                "length": curve_length,
                "owner_surface_tags": list(owner_surface_tags),
                "bbox": _entity_bbox_payload(gmsh, 1, curve_tag)["bbox"],
            }
        )

    surface_records: list[Dict[str, Any]] = []
    for surface_tag in surface_tags:
        bbox_payload = _entity_bbox_payload(gmsh, 2, int(surface_tag))
        bbox = bbox_payload["bbox"]
        spans = {
            "x": max(0.0, float(bbox["x_max"]) - float(bbox["x_min"])),
            "y": max(0.0, float(bbox["y_max"]) - float(bbox["y_min"])),
            "z": max(0.0, float(bbox["z_max"]) - float(bbox["z_min"])),
        }
        flat_axis = min(spans, key=spans.get)
        nonzero_spans = sorted((value for value in spans.values() if value > 1.0e-12), reverse=True)
        aspect_ratio_proxy = (
            nonzero_spans[0] / max(nonzero_spans[-1], 1.0e-12)
            if len(nonzero_spans) >= 2
            else None
        )
        area = _safe_occ_mass(gmsh, 2, int(surface_tag))
        curve_tags = surface_to_curves.get(int(surface_tag), [])
        curve_lengths = [curve_length_lookup.get(curve_tag) for curve_tag in curve_tags]
        valid_curve_lengths = [length for length in curve_lengths if length is not None]
        short_curve_tags = [
            int(curve_tag)
            for curve_tag in curve_tags
            if (curve_length_lookup.get(curve_tag) is not None and curve_length_lookup[curve_tag] <= short_curve_threshold)
        ]
        extrema = {
            "near_x_min": abs(float(bbox["x_min"]) - aircraft_mins[0]) <= extrema_tol,
            "near_x_max": abs(float(bbox["x_max"]) - aircraft_maxs[0]) <= extrema_tol,
            "near_y_min": abs(float(bbox["y_min"]) - aircraft_mins[1]) <= extrema_tol,
            "near_y_max": abs(float(bbox["y_max"]) - aircraft_maxs[1]) <= extrema_tol,
            "near_z_min": abs(float(bbox["z_min"]) - aircraft_mins[2]) <= extrema_tol,
            "near_z_max": abs(float(bbox["z_max"]) - aircraft_maxs[2]) <= extrema_tol,
            "near_root_plane": min(abs(float(bbox["y_min"])), abs(float(bbox["y_max"]))) <= extrema_tol,
        }
        family_hints: list[str] = []
        if area is not None and area <= tiny_face_area_threshold:
            family_hints.append("tiny_face_candidate")
        if short_curve_tags:
            family_hints.append("short_curve_candidate")
        if aspect_ratio_proxy is not None and aspect_ratio_proxy >= 10.0:
            family_hints.append("high_aspect_strip_candidate")
        if extrema["near_y_min"] or extrema["near_y_max"]:
            family_hints.append("span_extreme_candidate")
        if (extrema["near_y_min"] or extrema["near_y_max"]) and flat_axis in {"x", "z"}:
            family_hints.append("span_extreme_strip_candidate")
        if extrema["near_root_plane"] and flat_axis == "y":
            family_hints.append("root_plane_cap_candidate")
        location_hints: list[str] = []
        if extrema["near_root_plane"]:
            location_hints.append("root_plane")
        if extrema["near_x_min"]:
            location_hints.append("x_min_extreme")
        if extrema["near_x_max"]:
            location_hints.append("x_max_extreme")
        if extrema["near_y_min"] or extrema["near_y_max"]:
            location_hints.append("span_extreme")
        if extrema["near_z_min"]:
            location_hints.append("z_min_extreme")
        if extrema["near_z_max"]:
            location_hints.append("z_max_extreme")

        suspect_score = 0.0
        if area is not None:
            suspect_score += min(25.0, tiny_face_area_threshold / max(area, 1.0e-12))
        if valid_curve_lengths:
            suspect_score += min(25.0, short_curve_threshold / max(min(valid_curve_lengths), 1.0e-12))
        if aspect_ratio_proxy is not None:
            suspect_score += min(15.0, aspect_ratio_proxy / 4.0)
        suspect_score += 2.5 * len(family_hints)

        surface_records.append(
            {
                "tag": int(surface_tag),
                "area": area,
                "bbox": bbox,
                "spans": spans,
                "flat_axis": flat_axis,
                "surface_role": (
                    str(surface_role_lookup.get(int(surface_tag), "aircraft"))
                    if surface_role_lookup is not None
                    else "aircraft"
                ),
                "curve_count": len(curve_tags),
                "curve_tags": list(curve_tags),
                "curve_owner_count_summary": {
                    "shared_curve_count": sum(1 for curve_tag in curve_tags if len(curve_to_surfaces.get(curve_tag, [])) > 1),
                    "boundary_curve_count": sum(1 for curve_tag in curve_tags if len(curve_to_surfaces.get(curve_tag, [])) == 1),
                },
                "min_curve_length": min(valid_curve_lengths) if valid_curve_lengths else None,
                "max_curve_length": max(valid_curve_lengths) if valid_curve_lengths else None,
                "short_curve_count": len(short_curve_tags),
                "short_curve_tags": short_curve_tags,
                "aspect_ratio_proxy": aspect_ratio_proxy,
                "extrema": extrema,
                "location_hints": location_hints,
                "family_hints": family_hints,
                "suspect_score": suspect_score,
            }
        )

    smallest_area_surfaces = sorted(
        surface_records,
        key=lambda record: float(record["area"]) if record["area"] is not None else float("inf"),
    )[:12]
    shortest_curves = sorted(
        curve_records,
        key=lambda record: float(record["length"]) if record["length"] is not None else float("inf"),
    )[:20]
    suspicious_surfaces = sorted(
        surface_records,
        key=lambda record: (
            -float(record["suspect_score"]),
            float(record["area"]) if record["area"] is not None else float("inf"),
            int(record["tag"]),
        ),
    )[:12]
    family_hint_counts: dict[str, int] = defaultdict(int)
    surface_role_counts: dict[str, int] = defaultdict(int)
    for record in surface_records:
        surface_role_counts[str(record["surface_role"])] += 1
        for hint in record["family_hints"]:
            family_hint_counts[str(hint)] += 1

    return {
        "status": "captured",
        "reference_length": float(reference_length),
        "near_body_size": float(near_body_size),
        "edge_size": float(edge_size),
        "short_curve_threshold": float(short_curve_threshold),
        "tiny_face_area_threshold": float(tiny_face_area_threshold),
        "aircraft_surface_bounds": _bounds_dict(aircraft_mins, aircraft_maxs),
        "surface_count": len(surface_tags),
        "curve_count": len(curve_records),
        "surface_role_counts": dict(surface_role_counts),
        "surface_area_distribution": _distribution_summary(record["area"] for record in surface_records),
        "curve_length_distribution": _distribution_summary(record["length"] for record in curve_records),
        "family_hint_counts": dict(sorted(family_hint_counts.items())),
        "curve_records": curve_records,
        "surface_records": surface_records,
        "smallest_area_surfaces": smallest_area_surfaces,
        "shortest_curves": shortest_curves,
        "suspicious_surfaces": suspicious_surfaces,
        "suspicious_family_groups": _surface_family_groups(suspicious_surfaces),
    }


def _scan_duplicate_surface_facets(gmsh, surface_tags: list[int]) -> Dict[str, Any]:
    duplicate_elements: dict[tuple[int, tuple[int, ...]], list[tuple[int, int]]] = defaultdict(list)

    for surface_tag in surface_tags:
        element_types, element_tags_blocks, node_tags_blocks = gmsh.model.mesh.getElements(2, int(surface_tag))
        for element_type, element_tags, node_tags in zip(element_types, element_tags_blocks, node_tags_blocks):
            if int(element_type) == 2:
                node_count = 3
            elif int(element_type) == 3:
                node_count = 4
            else:
                continue
            for index, element_tag in enumerate(element_tags):
                start = index * node_count
                nodes = node_tags[start:start + node_count]
                key = (int(element_type), tuple(sorted(int(node_tag) for node_tag in nodes)))
                duplicate_elements[key].append((int(surface_tag), int(element_tag)))

    duplicate_groups = [entries for entries in duplicate_elements.values() if len(entries) > 1]
    return {
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_facet_count": sum(len(entries) - 1 for entries in duplicate_groups),
        "sample_groups": [
            {
                "surface_tags": [surface_tag for surface_tag, _ in entries],
                "element_tags": [element_tag for _, element_tag in entries],
            }
            for entries in duplicate_groups[:10]
        ],
    }


def _remove_duplicate_surface_facets(gmsh, surface_tags: list[int]) -> Dict[str, Any]:
    duplicate_elements: dict[tuple[int, tuple[int, ...]], list[tuple[int, int]]] = defaultdict(list)

    for surface_tag in surface_tags:
        element_types, element_tags_blocks, node_tags_blocks = gmsh.model.mesh.getElements(2, int(surface_tag))
        for element_type, element_tags, node_tags in zip(element_types, element_tags_blocks, node_tags_blocks):
            if int(element_type) == 2:
                node_count = 3
            elif int(element_type) == 3:
                node_count = 4
            else:
                continue
            for index, element_tag in enumerate(element_tags):
                start = index * node_count
                nodes = node_tags[start:start + node_count]
                key = (int(element_type), tuple(sorted(int(node_tag) for node_tag in nodes)))
                duplicate_elements[key].append((int(surface_tag), int(element_tag)))

    duplicate_groups = [entries for entries in duplicate_elements.values() if len(entries) > 1]
    removed_facet_count = 0
    for entries in duplicate_groups:
        for surface_tag, element_tag in entries[1:]:
            gmsh.model.mesh.removeElements(2, int(surface_tag), [int(element_tag)])
            removed_facet_count += 1

    if removed_facet_count:
        gmsh.model.mesh.reclassifyNodes()

    node_count_before = len(gmsh.model.mesh.getNodes()[0])
    try:
        gmsh.model.mesh.removeDuplicateNodes()
    except Exception:
        duplicate_nodes_removed = None
    else:
        duplicate_nodes_removed = max(0, node_count_before - len(gmsh.model.mesh.getNodes()[0]))

    return {
        "duplicate_group_count": len(duplicate_groups),
        "removed_duplicate_facets": removed_facet_count,
        "duplicate_nodes_removed": duplicate_nodes_removed,
        "sample_groups": [
            {
                "surface_tags": [surface_tag for surface_tag, _ in entries],
                "element_tags": [element_tag for _, element_tag in entries],
            }
            for entries in duplicate_groups[:10]
        ],
    }


def _resolve_sizing_reference_length(
    handle: GeometryHandle,
    config: MeshJobConfig,
    *,
    fallback_body_bounds: tuple[list[float], list[float]] | None = None,
) -> float:
    reference_length = resolve_reference_length(
        handle.source_path,
        provider_result=handle.provider_result,
        metadata=config.metadata,
    )
    if (reference_length is None or reference_length <= 0.0) and fallback_body_bounds is not None:
        mins, maxs = fallback_body_bounds
        spans = [float(max_value) - float(min_value) for min_value, max_value in zip(mins, maxs)]
        reference_length = max(spans)
    if reference_length is None or reference_length <= 0.0:
        raise GmshBackendError(
            f"geometry-derived reference length is required for {config.component} surface sizing"
        )
    return float(reference_length)


def _resolve_coarse_first_tetra_profile(config: MeshJobConfig) -> Dict[str, Any]:
    metadata = config.metadata or {}
    enabled = bool(metadata.get("coarse_first_tetra_enabled", False))
    nodes_per_ref_length = float(
        metadata.get(
            "coarse_first_tetra_surface_nodes_per_reference_length",
            COARSE_FIRST_TETRA_SURFACE_NODES_PER_REFERENCE_LENGTH,
        )
    )
    edge_ratio = float(
        metadata.get(
            "coarse_first_tetra_edge_refinement_ratio",
            COARSE_FIRST_TETRA_EDGE_REFINEMENT_RATIO,
        )
    )
    span_extreme_floor = float(
        metadata.get(
            "coarse_first_tetra_span_extreme_strip_floor_size",
            COARSE_FIRST_TETRA_SPAN_EXTREME_STRIP_FLOOR_SIZE,
        )
    )
    suspect_floor = float(
        metadata.get(
            "coarse_first_tetra_suspect_strip_floor_size",
            COARSE_FIRST_TETRA_SUSPECT_STRIP_FLOOR_SIZE,
        )
    )
    suspect_algorithm = int(
        metadata.get(
            "coarse_first_tetra_suspect_surface_algorithm",
            COARSE_FIRST_TETRA_SUSPECT_SURFACE_ALGORITHM,
        )
    )
    general_algorithm = int(
        metadata.get(
            "coarse_first_tetra_general_surface_algorithm",
            COARSE_FIRST_TETRA_GENERAL_SURFACE_ALGORITHM,
        )
    )
    farfield_algorithm = int(
        metadata.get(
            "coarse_first_tetra_farfield_surface_algorithm",
            COARSE_FIRST_TETRA_FARFIELD_SURFACE_ALGORITHM,
        )
    )
    clamp_min_to_near_body = bool(
        metadata.get(
            "coarse_first_tetra_clamp_mesh_size_min_to_near_body",
            True,
        )
    )
    return {
        "enabled": enabled,
        "surface_nodes_per_reference_length": nodes_per_ref_length,
        "edge_refinement_ratio": edge_ratio,
        "span_extreme_strip_floor_size": span_extreme_floor,
        "suspect_strip_floor_size": suspect_floor,
        "suspect_surface_algorithm": suspect_algorithm,
        "general_surface_algorithm": general_algorithm,
        "farfield_surface_algorithm": farfield_algorithm,
        "clamp_mesh_size_min_to_near_body": clamp_min_to_near_body,
    }


def _resolve_mesh_field_defaults(reference_length: float, config: MeshJobConfig) -> Dict[str, Any]:
    coarse_profile = _resolve_coarse_first_tetra_profile(config)
    if coarse_profile["enabled"]:
        nodes_per_ref_length = float(coarse_profile["surface_nodes_per_reference_length"])
        edge_ratio = float(coarse_profile["edge_refinement_ratio"])
    else:
        nodes_per_ref_length = DEFAULT_SURFACE_NODES_PER_REFERENCE_LENGTH
        edge_ratio = DEFAULT_EDGE_REFINEMENT_RATIO
    near_body_size = config.global_min_size or (reference_length / nodes_per_ref_length)
    if near_body_size > reference_length:
        raise GmshBackendError(
            "near-body surface size exceeds reference length; aircraft surface would be under-resolved"
        )
    edge_size = near_body_size * edge_ratio
    farfield_size = config.global_max_size or max(reference_length * DEFAULT_FARFIELD_REFERENCE_FACTOR, near_body_size * 40.0)
    distance_min = 0.0
    distance_max = max(reference_length * DEFAULT_SURFACE_DISTANCE_FACTOR, near_body_size * DEFAULT_SURFACE_TRANSITION_FACTOR)
    edge_distance_max = max(reference_length * DEFAULT_EDGE_DISTANCE_FACTOR, edge_size * DEFAULT_EDGE_TRANSITION_FACTOR)
    if "mesh_field_distance_max" in config.metadata:
        distance_max = float(config.metadata["mesh_field_distance_max"])
    if "mesh_field_edge_distance_max" in config.metadata:
        edge_distance_max = float(config.metadata["mesh_field_edge_distance_max"])
    mesh_algorithm_2d = int(config.mesh_algorithm_2d) if config.mesh_algorithm_2d is not None else 6
    mesh_algorithm_3d = int(config.mesh_algorithm_3d) if config.mesh_algorithm_3d is not None else 1
    return {
        "near_body_size": float(near_body_size),
        "edge_size": float(edge_size),
        "farfield_size": float(farfield_size),
        "distance_min": float(distance_min),
        "distance_max": float(distance_max),
        "edge_distance_max": float(edge_distance_max),
        "mesh_algorithm_2d": int(mesh_algorithm_2d),
        "mesh_algorithm_3d": int(mesh_algorithm_3d),
        "surface_nodes_per_reference_length": float(nodes_per_ref_length),
        "edge_refinement_ratio": float(edge_ratio),
        "coarse_first_tetra": coarse_profile,
    }


def _mesh_algorithm_name(value: int) -> str:
    return MESH_ALGORITHM_NAME_LOOKUP.get(int(value), f"Unknown({int(value)})")


def _unique_sorted_ints(values: Iterable[int]) -> list[int]:
    return sorted({int(value) for value in values})


def _resolve_brep_hotspot_request(
    *,
    surface_patch_diagnostics: Dict[str, Any] | None,
    requested_surface_tags: Iterable[int] | None = None,
    requested_curve_tags: Iterable[int] | None = None,
) -> Dict[str, Any]:
    requested_surfaces = _unique_sorted_ints(requested_surface_tags or [])
    requested_curves = _unique_sorted_ints(requested_curve_tags or [])
    if not requested_surfaces and not requested_curves:
        return {"enabled": False, "reason": "no_requested_targets"}
    if not isinstance(surface_patch_diagnostics, dict):
        return {"enabled": False, "reason": "missing_surface_patch_diagnostics"}

    surface_lookup = {
        int(record["tag"]): record
        for record in surface_patch_diagnostics.get("surface_records", [])
        if record.get("tag") is not None
    }
    curve_lookup = {
        int(record["tag"]): record
        for record in surface_patch_diagnostics.get("curve_records", [])
        if record.get("tag") is not None
    }
    selected_surface_tags = [tag for tag in requested_surfaces if tag in surface_lookup]
    selected_curve_tags = [tag for tag in requested_curves if tag in curve_lookup]
    curve_owner_surface_tags = _unique_sorted_ints(
        surface_tag
        for curve_tag in selected_curve_tags
        for surface_tag in curve_lookup[curve_tag].get("owner_surface_tags", [])
    )
    curve_surface_context_tags = _unique_sorted_ints(
        list(selected_surface_tags) + list(curve_owner_surface_tags)
    )
    if not selected_surface_tags and not selected_curve_tags:
        return {
            "enabled": False,
            "reason": "requested_targets_not_found",
            "missing_surface_tags": [tag for tag in requested_surfaces if tag not in surface_lookup],
            "missing_curve_tags": [tag for tag in requested_curves if tag not in curve_lookup],
        }
    return {
        "enabled": True,
        "requested_surface_tags": requested_surfaces,
        "requested_curve_tags": requested_curves,
        "selected_surface_tags": selected_surface_tags,
        "selected_curve_tags": selected_curve_tags,
        "curve_owner_surface_tags": curve_owner_surface_tags,
        "curve_surface_context_tags": curve_surface_context_tags,
        "missing_surface_tags": [tag for tag in requested_surfaces if tag not in surface_lookup],
        "missing_curve_tags": [tag for tag in requested_curves if tag not in curve_lookup],
    }


def _resolve_tip_quality_buffer_policy(
    *,
    config: MeshJobConfig,
    surface_patch_diagnostics: Dict[str, Any] | None,
    near_body_size: float,
) -> Dict[str, Any]:
    policy = config.tip_quality_buffer_policy
    if policy is None or not bool(policy.enabled):
        return {"enabled": False, "reason": "disabled_by_config"}

    active_variant_name = policy.active_variant
    if active_variant_name is None and len(policy.variants) == 1:
        active_variant_name = policy.variants[0].name
    if active_variant_name is None:
        return {"enabled": False, "reason": "missing_active_variant"}

    active_variant = next((variant for variant in policy.variants if variant.name == active_variant_name), None)
    if active_variant is None:
        return {
            "enabled": False,
            "reason": "active_variant_not_found",
            "active_variant": active_variant_name,
        }

    request = _resolve_brep_hotspot_request(
        surface_patch_diagnostics=surface_patch_diagnostics,
        requested_surface_tags=policy.target_surfaces,
        requested_curve_tags=policy.target_curves,
    )
    if not request.get("enabled"):
        return {
            "enabled": False,
            "reason": request.get("reason"),
            "active_variant": active_variant_name,
            "target_surfaces": [int(tag) for tag in policy.target_surfaces],
            "target_curves": [int(tag) for tag in policy.target_curves],
            "missing_surface_tags": request.get("missing_surface_tags", []),
            "missing_curve_tags": request.get("missing_curve_tags", []),
        }

    surface_lookup = {
        int(record["tag"]): record
        for record in (surface_patch_diagnostics or {}).get("surface_records", [])
        if record.get("tag") is not None
    }
    selected_surface_tags = [int(tag) for tag in request.get("selected_surface_tags", [])]
    selected_curve_tags = [int(tag) for tag in request.get("selected_curve_tags", [])]
    if not selected_curve_tags:
        selected_curve_tags = _unique_sorted_ints(
            curve_tag
            for surface_tag in selected_surface_tags
            for curve_tag in surface_lookup.get(int(surface_tag), {}).get("curve_tags", [])
        )

    size_max_default = max(
        float(near_body_size),
        float(config.metadata.get("tip_quality_buffer_size_max", COARSE_FIRST_TETRA_SPAN_EXTREME_STRIP_FLOOR_SIZE)),
    )
    return {
        "enabled": True,
        "source_baseline": policy.source_baseline,
        "target_surfaces": [int(tag) for tag in policy.target_surfaces],
        "target_curves": [int(tag) for tag in policy.target_curves],
        "optional_expanded_surfaces": [int(tag) for tag in policy.optional_expanded_surfaces],
        "width_reference_m": float(policy.width_reference_m) if policy.width_reference_m is not None else None,
        "active_variant": active_variant.model_dump(mode="json"),
        "selected_surface_tags": selected_surface_tags,
        "selected_curve_tags": selected_curve_tags,
        "curve_owner_surface_tags": [int(tag) for tag in request.get("curve_owner_surface_tags", [])],
        "curve_surface_context_tags": [int(tag) for tag in request.get("curve_surface_context_tags", [])],
        "missing_surface_tags": [int(tag) for tag in request.get("missing_surface_tags", [])],
        "missing_curve_tags": [int(tag) for tag in request.get("missing_curve_tags", [])],
        "h_tip_m": float(active_variant.h_tip_m),
        "dist_min_m": float(active_variant.dist_min_m),
        "dist_max_m": float(active_variant.dist_max_m),
        "size_max_m": float(size_max_default),
        "stop_at_dist_max": bool(policy.stop_at_dist_max),
        "mesh_size_extend_from_boundary": int(policy.mesh_size_extend_from_boundary),
        "mesh_size_from_points": int(policy.mesh_size_from_points),
        "mesh_size_from_curvature": int(policy.mesh_size_from_curvature),
    }


def _resolve_sliver_volume_pocket_policy(
    *,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    policy = config.sliver_volume_pocket_policy
    if policy is None or not bool(policy.enabled):
        return {"enabled": False, "reason": "disabled_by_config"}

    active_variant_name = policy.active_variant
    if active_variant_name is None and len(policy.variants) == 1:
        active_variant_name = policy.variants[0].name
    if active_variant_name is None:
        return {"enabled": False, "reason": "missing_active_variant"}

    active_variant = next((variant for variant in policy.variants if variant.name == active_variant_name), None)
    if active_variant is None:
        return {
            "enabled": False,
            "reason": "active_variant_not_found",
            "active_variant": active_variant_name,
        }

    pockets = [pocket.model_dump(mode="json") for pocket in active_variant.pockets]
    return {
        "enabled": True,
        "source_baseline": policy.source_baseline,
        "cluster_report_path": policy.cluster_report_path,
        "active_variant": {
            "name": active_variant.name,
            "field_type": active_variant.field_type,
            "pockets": pockets,
        },
        "mesh_size_extend_from_boundary": int(policy.mesh_size_extend_from_boundary),
        "mesh_size_from_points": int(policy.mesh_size_from_points),
        "mesh_size_from_curvature": int(policy.mesh_size_from_curvature),
    }


def _collect_sliver_cluster_report(
    *,
    baseline: str,
    quality_metrics: Dict[str, Any] | None,
    hotspot_patch_report: Dict[str, Any] | None,
    focus_surface_tags: Iterable[int] | None = None,
) -> Dict[str, Any]:
    quality_metrics = dict(quality_metrics or {})
    ill_shaped_tet_count = int(quality_metrics.get("ill_shaped_tet_count", 0) or 0)
    worst_tets = list(quality_metrics.get("worst_20_tets", []) or [])
    bad_tet_entries = worst_tets[:ill_shaped_tet_count] if ill_shaped_tet_count > 0 else []
    focus_surface_set = {int(tag) for tag in (focus_surface_tags or [])}

    hotspot_distance_lookup: Dict[int, list[tuple[int, float]]] = defaultdict(list)
    for surface_report in (hotspot_patch_report or {}).get("surface_reports", []):
        surface_id = surface_report.get("surface_id")
        if surface_id is None:
            continue
        for entry in (surface_report.get("worst_tets_near_this_surface") or {}).get("entries", []):
            element_id = entry.get("element_id")
            distance_to_surface = entry.get("distance_to_surface")
            if element_id is None or distance_to_surface is None:
                continue
            hotspot_distance_lookup[int(element_id)].append((int(surface_id), float(distance_to_surface)))

    bad_tets: list[Dict[str, Any]] = []
    point_records: list[tuple[int, list[float]]] = []
    for entry in bad_tet_entries:
        element_id = int(entry.get("element_id", 0) or 0)
        barycenter = [float(value) for value in entry.get("barycenter", [0.0, 0.0, 0.0])]
        nearest_surface_info = entry.get("nearest_surface") or {}
        nearest_surface = nearest_surface_info.get("surface_tag", entry.get("nearest_surface_id"))
        nearest_surface = int(nearest_surface) if nearest_surface is not None else None
        distance_to_nearest_surface = nearest_surface_info.get("distance", entry.get("distance_to_surface"))
        distance_to_nearest_surface = (
            float(distance_to_nearest_surface) if distance_to_nearest_surface is not None else None
        )
        hotspot_distances = hotspot_distance_lookup.get(element_id, [])
        if focus_surface_set:
            hotspot_distances = [item for item in hotspot_distances if item[0] in focus_surface_set]
        nearest_hotspot_surface = None
        distance_to_focus_surfaces = None
        if hotspot_distances:
            nearest_hotspot_surface, distance_to_focus_surfaces = min(hotspot_distances, key=lambda item: item[1])
        min_edge = entry.get("tetra_edge_length_min", entry.get("local_tetra_edge_length_min"))
        max_edge = entry.get("tetra_edge_length_max", entry.get("local_tetra_edge_length_max"))
        min_edge = float(min_edge) if min_edge is not None else None
        max_edge = float(max_edge) if max_edge is not None else None
        edge_ratio = None
        if min_edge is not None and max_edge is not None and min_edge > 0:
            edge_ratio = float(max_edge / min_edge)
        bad_tets.append(
            {
                "element_id": element_id,
                "barycenter": barycenter,
                "volume": float(entry.get("volume", 0.0) or 0.0),
                "gamma": float(entry.get("gamma", 0.0) or 0.0),
                "minSICN": float(entry.get("min_sicn", 0.0) or 0.0),
                "minSIGE": float(entry.get("min_sige", 0.0) or 0.0),
                "min_edge": min_edge,
                "max_edge": max_edge,
                "edge_ratio": edge_ratio,
                "nearest_surface": nearest_surface,
                "distance_to_nearest_surface": distance_to_nearest_surface,
                "nearest_hotspot_surface": nearest_hotspot_surface,
                "distance_to_surfaces_30_21_31_32": distance_to_focus_surfaces,
            }
        )
        point_records.append((element_id, barycenter))

    clusters: list[Dict[str, Any]] = []
    if point_records:
        import numpy as np

        point_ids = [element_id for element_id, _ in point_records]
        points = np.asarray([coords for _, coords in point_records], dtype=float)
        if len(points) == 1:
            components = [[0]]
        else:
            distances = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
            np.fill_diagonal(distances, np.inf)
            nearest_neighbor_distances = np.min(distances, axis=1)
            finite_neighbor_distances = nearest_neighbor_distances[np.isfinite(nearest_neighbor_distances)]
            cluster_eps = 0.1
            if finite_neighbor_distances.size:
                cluster_eps = float(min(max(3.0 * np.median(finite_neighbor_distances), 0.05), 0.5))
            adjacency = {index: set() for index in range(len(points))}
            for i in range(len(points)):
                for j in range(i + 1, len(points)):
                    if float(distances[i, j]) <= cluster_eps:
                        adjacency[i].add(j)
                        adjacency[j].add(i)
            components = []
            remaining = set(range(len(points)))
            while remaining:
                start = remaining.pop()
                queue = [start]
                component = [start]
                while queue:
                    current = queue.pop()
                    for neighbor in adjacency[current]:
                        if neighbor in remaining:
                            remaining.remove(neighbor)
                            queue.append(neighbor)
                            component.append(neighbor)
                components.append(sorted(component))

        for cluster_id, component in enumerate(components):
            cluster_points = points[component]
            center = cluster_points.mean(axis=0)
            centered = cluster_points - center
            distances_to_center = np.linalg.norm(centered, axis=1)
            bbox_min = cluster_points.min(axis=0)
            bbox_max = cluster_points.max(axis=0)
            radius = float(distances_to_center.max()) if len(distances_to_center) else 0.0
            principal_axis = np.array([1.0, 0.0, 0.0], dtype=float)
            axis_span = 0.0
            perpendicular_radius = 0.0
            pca_ratio = 1.0
            if len(cluster_points) >= 2:
                cov = np.cov(centered.T)
                eigenvalues, eigenvectors = np.linalg.eigh(np.atleast_2d(cov))
                order = np.argsort(eigenvalues)[::-1]
                eigenvalues = eigenvalues[order]
                eigenvectors = eigenvectors[:, order]
                principal_axis = eigenvectors[:, 0]
                pca_ratio = float(eigenvalues[0] / max(float(eigenvalues[1]) if len(eigenvalues) > 1 else 1.0, 1e-12))
                projections = centered @ principal_axis
                axis_span = float(projections.max() - projections.min()) if len(projections) else 0.0
                perpendicular_vectors = centered - np.outer(projections, principal_axis)
                perpendicular_radius = (
                    float(np.linalg.norm(perpendicular_vectors, axis=1).max())
                    if len(perpendicular_vectors)
                    else 0.0
                )
            classification = "compact"
            recommended_field_type = "Ball"
            if pca_ratio >= 3.0:
                classification = "elongated"
                recommended_field_type = "Cylinder"
            elif radius > 0.8:
                classification = "scattered"
                recommended_field_type = "no_mesh_policy"
            clusters.append(
                {
                    "cluster_id": int(cluster_id),
                    "tet_count": len(component),
                    "center": [float(value) for value in center.tolist()],
                    "bbox_min": [float(value) for value in bbox_min.tolist()],
                    "bbox_max": [float(value) for value in bbox_max.tolist()],
                    "radius_m": float(radius),
                    "pca_eigenvalue_ratio": float(pca_ratio),
                    "classification": classification,
                    "recommended_field_type": recommended_field_type,
                    "source_bad_tet_ids": [int(point_ids[index]) for index in component],
                    "principal_axis": [float(value) for value in principal_axis.tolist()],
                    "axis_span_m": float(axis_span),
                    "perpendicular_radius_m": float(perpendicular_radius),
                }
            )

    return {
        "baseline": str(baseline),
        "ill_shaped_tet_count": ill_shaped_tet_count,
        "bad_tets": bad_tets,
        "clusters": clusters,
    }


def _summarize_sliver_volume_pocket_candidate(
    *,
    name: str,
    mesh_metadata: Dict[str, Any],
    hotspot_patch_report: Dict[str, Any] | None,
    sliver_cluster_report: Dict[str, Any] | None,
    sliver_volume_pocket_policy: Dict[str, Any] | None,
) -> Dict[str, Any]:
    mesh_stats = mesh_metadata.get("mesh", mesh_metadata.get("mesh_stats", {}))
    quality_metrics = mesh_metadata.get("quality_metrics", {})
    mesh3d_watchdog = mesh_metadata.get("mesh3d_watchdog", {})
    physical_groups = mesh_metadata.get("physical_groups", {})
    phase = (
        mesh3d_watchdog.get("phase_classification_after_return")
        or mesh3d_watchdog.get("timeout_phase_classification")
        or mesh_metadata.get("volume_meshing", {}).get("burden_metrics", {}).get("timeout_phase_classification")
    )
    active_variant = (sliver_volume_pocket_policy or {}).get("active_variant") or {}
    pockets = active_variant.get("pockets", []) if isinstance(active_variant, dict) else []
    primary_pocket = dict(pockets[0]) if pockets else {}
    worst_hotspot_surfaces = [
        int(entry["surface_id"])
        for entry in sorted(
            hotspot_patch_report.get("surface_reports", []) if isinstance(hotspot_patch_report, dict) else [],
            key=lambda record: (record.get("worst_tets_near_this_surface") or {}).get("count", 0),
            reverse=True,
        )
        if int((entry.get("worst_tets_near_this_surface") or {}).get("count", 0)) > 0
    ]

    candidate = {
        "name": str(name),
        "field_type": active_variant.get("field_type"),
        "center": primary_pocket.get("center"),
        "radius": primary_pocket.get("radius"),
        "thickness": primary_pocket.get("thickness"),
        "VIn": primary_pocket.get("VIn"),
        "VOut": primary_pocket.get("VOut"),
        "axis": primary_pocket.get("axis"),
        "length": primary_pocket.get("length"),
        "source_bad_tet_ids": primary_pocket.get("source_bad_tet_ids", []),
        "cluster_ids": [pocket.get("cluster_id") for pocket in pockets if pocket.get("cluster_id") is not None],
        "surface_triangle_count": int(mesh_stats.get("surface_element_count", 0) or 0),
        "volume_element_count": int(mesh_stats.get("volume_element_count", 0) or 0),
        "nodes_created_per_boundary_node": mesh3d_watchdog.get("nodes_created_per_boundary_node"),
        "ill_shaped_tet_count": int(quality_metrics.get("ill_shaped_tet_count", 0) or 0),
        "min_gamma": quality_metrics.get("min_gamma"),
        "min_sicn": quality_metrics.get("min_sicn"),
        "min_sige": quality_metrics.get("min_sige"),
        "min_volume": quality_metrics.get("min_volume"),
        "worst_hotspot_surfaces": worst_hotspot_surfaces,
        "timeout_phase_classification": phase,
        "passed": False,
        "failed_checks": [],
        "failure_reason": "",
        "cluster_report_cluster_count": len((sliver_cluster_report or {}).get("clusters", [])),
    }

    failed_checks: list[str] = []
    if str(mesh_metadata.get("status")) != "success":
        failed_checks.append("status_not_success")
    if candidate["surface_triangle_count"] <= 0:
        failed_checks.append("surface_triangle_count_missing")
    if candidate["volume_element_count"] <= 0:
        failed_checks.append("volume_element_count_missing")
    if candidate["surface_triangle_count"] >= 120000:
        failed_checks.append("surface_triangle_count_limit")
    if candidate["volume_element_count"] >= 180000:
        failed_checks.append("volume_element_count_limit")
    if candidate["ill_shaped_tet_count"] != 0:
        failed_checks.append("ill_shaped_tets_present")
    if float(candidate["min_volume"] or 0.0) <= 0.0:
        failed_checks.append("min_volume_not_positive")
    if float(candidate["min_sicn"] or 0.0) <= 0.0:
        failed_checks.append("min_sicn_not_positive")
    if float(candidate["min_sige"] or 0.0) <= 0.0:
        failed_checks.append("min_sige_not_positive")
    if candidate["nodes_created_per_boundary_node"] is None:
        failed_checks.append("nodes_created_per_boundary_node_missing")
    elif float(candidate["nodes_created_per_boundary_node"]) >= 0.5:
        failed_checks.append("nodes_created_per_boundary_node_limit")
    if str(phase or "") == "volume_insertion":
        failed_checks.append("volume_insertion_phase")
    wall_group_exists = any(
        bool(physical_groups.get(name, {}).get("exists"))
        for name in ("aircraft", "fairing_solid")
    )
    if not (wall_group_exists and all(bool(physical_groups.get(name, {}).get("exists")) for name in ("fluid", "farfield"))):
        failed_checks.append("physical_groups_not_preserved")

    candidate["failed_checks"] = failed_checks
    candidate["failure_reason"] = ", ".join(failed_checks)
    candidate["passed"] = not failed_checks
    return candidate


def _select_sliver_volume_pocket_winner(
    candidates: Iterable[Dict[str, Any]],
) -> tuple[Dict[str, Any] | None, str]:
    candidate_list = [dict(candidate) for candidate in candidates]
    passing = [candidate for candidate in candidate_list if bool(candidate.get("passed"))]
    if not passing:
        return None, "no passing candidates met the quality-clean gates"

    winner = sorted(
        passing,
        key=lambda candidate: (
            int(candidate.get("volume_element_count", 0) or 0),
            int(candidate.get("surface_triangle_count", 0) or 0),
            -float(candidate.get("min_sicn", 0.0) or 0.0),
            -float(candidate.get("min_sige", 0.0) or 0.0),
            str(candidate.get("name", "")),
        ),
    )[0]
    return winner, (
        "selected passing candidate with lowest volume_element_count, "
        "then lowest surface_triangle_count, then highest min_sicn/min_sige"
    )


def _evaluate_sliver_volume_pocket_controller(
    *,
    baseline_metrics: Dict[str, Any],
    candidates: Iterable[Dict[str, Any]],
    cycle_index: int,
) -> Dict[str, Any]:
    candidate_list = [dict(candidate) for candidate in candidates]
    winner, winner_reason = _select_sliver_volume_pocket_winner(candidate_list)
    if winner is not None:
        return {
            "winner": winner,
            "reason": winner_reason,
            "run_cycle_1": False,
            "mesh_only_no_go": False,
            "best_candidate": winner,
        }

    baseline_ill_shaped = int(baseline_metrics.get("ill_shaped_tet_count", 0) or 0)
    improved_candidates = [
        candidate
        for candidate in candidate_list
        if int(candidate.get("ill_shaped_tet_count", baseline_ill_shaped) or baseline_ill_shaped) < baseline_ill_shaped
        and int(candidate.get("volume_element_count", 10**9) or 10**9) < 180000
        and str(candidate.get("timeout_phase_classification") or "") != "volume_insertion"
        and float(candidate.get("nodes_created_per_boundary_node", 1.0) or 1.0) < 0.5
    ]
    if cycle_index == 0 and improved_candidates:
        best_candidate = sorted(
            improved_candidates,
            key=lambda candidate: (
                int(candidate.get("ill_shaped_tet_count", baseline_ill_shaped) or baseline_ill_shaped),
                int(candidate.get("volume_element_count", 0) or 0),
                int(candidate.get("surface_triangle_count", 0) or 0),
            ),
        )[0]
        return {
            "winner": None,
            "reason": "cycle_0_found_improved_candidate_for_cycle_1",
            "run_cycle_1": True,
            "mesh_only_no_go": False,
            "best_candidate": best_candidate,
        }

    return {
        "winner": None,
        "reason": "sliver volume pocket did not reduce residual ill-shaped tets",
        "run_cycle_1": False,
        "mesh_only_no_go": True,
        "best_candidate": None,
    }


def _build_rule_loft_pairing_repair_spec(
    *,
    known_good_suppression: Dict[str, Any],
    bad_aggressive_probe: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "reason": "mesh-only volume pocket failed or residual slivers are scattered",
        "source_section_index": 5,
        "known_good_suppression": dict(known_good_suppression),
        "bad_aggressive_probe": dict(bad_aggressive_probe),
        "do_not_do": [
            "increase trim count blindly",
            "compound 31/32 family",
            "global OCC healing",
        ],
        "next_upstream_contract": [
            "inspect rule-loft pairing at terminal tip TE neighborhood",
            "coalesce terminal source section 5 with adjacent panel topology before BRep face emission",
            "avoid emitting high-aspect terminal transition panels as independent faces",
            "preserve aircraft-wall physical attributes through old-face to new-face lineage map",
        ],
        "required_artifacts_for_next_attempt": [
            "old_face_to_new_face_map",
            "topology_lineage_report",
            "brep_valid_default/exact",
            "hotspot_patch_report",
            "mesh_metadata with quality_metrics",
        ],
    }


def _summarize_tip_quality_buffer_candidate(
    *,
    name: str,
    mesh_metadata: Dict[str, Any],
    hotspot_patch_report: Dict[str, Any] | None,
) -> Dict[str, Any]:
    mesh_stats = mesh_metadata.get("mesh", {})
    quality_metrics = mesh_metadata.get("quality_metrics", {})
    mesh3d_watchdog = mesh_metadata.get("mesh3d_watchdog", {})
    physical_groups = mesh_metadata.get("physical_groups", {})
    phase = (
        mesh3d_watchdog.get("phase_classification_after_return")
        or mesh3d_watchdog.get("timeout_phase_classification")
        or mesh_metadata.get("volume_meshing", {}).get("burden_metrics", {}).get("timeout_phase_classification")
    )
    worst_hotspot_surfaces = [
        int(entry["surface_id"])
        for entry in sorted(
            hotspot_patch_report.get("surface_reports", []) if isinstance(hotspot_patch_report, dict) else [],
            key=lambda record: (record.get("worst_tets_near_this_surface") or {}).get("count", 0),
            reverse=True,
        )
        if int((entry.get("worst_tets_near_this_surface") or {}).get("count", 0)) > 0
    ]

    candidate = {
        "name": str(name),
        "surface_triangle_count": int(mesh_stats.get("surface_element_count", 0) or 0),
        "volume_element_count": int(mesh_stats.get("volume_element_count", 0) or 0),
        "nodes_created_per_boundary_node": mesh3d_watchdog.get("nodes_created_per_boundary_node"),
        "ill_shaped_tet_count": int(quality_metrics.get("ill_shaped_tet_count", 0) or 0),
        "min_gamma": quality_metrics.get("min_gamma"),
        "min_sicn": quality_metrics.get("min_sicn"),
        "min_sige": quality_metrics.get("min_sige"),
        "min_volume": quality_metrics.get("min_volume"),
        "worst_hotspot_surfaces": worst_hotspot_surfaces,
        "passed": False,
        "failed_checks": [],
    }

    failed_checks: list[str] = []
    if str(mesh_metadata.get("status")) != "success":
        failed_checks.append("status_not_success")
    if candidate["surface_triangle_count"] <= 0:
        failed_checks.append("surface_triangle_count_missing")
    if candidate["volume_element_count"] <= 0:
        failed_checks.append("volume_element_count_missing")
    if candidate["surface_triangle_count"] >= 120000:
        failed_checks.append("surface_triangle_count_limit")
    if candidate["volume_element_count"] >= 180000:
        failed_checks.append("volume_element_count_limit")
    if candidate["ill_shaped_tet_count"] != 0:
        failed_checks.append("ill_shaped_tets_present")
    if float(candidate["min_volume"] or 0.0) <= 0.0:
        failed_checks.append("min_volume_not_positive")
    if float(candidate["min_sicn"] or 0.0) <= 0.0:
        failed_checks.append("min_sicn_not_positive")
    if float(candidate["min_sige"] or 0.0) <= 0.0:
        failed_checks.append("min_sige_not_positive")
    if candidate["nodes_created_per_boundary_node"] is None:
        failed_checks.append("nodes_created_per_boundary_node_missing")
    elif float(candidate["nodes_created_per_boundary_node"]) >= 0.5:
        failed_checks.append("nodes_created_per_boundary_node_limit")
    if str(phase or "") == "volume_insertion":
        failed_checks.append("volume_insertion_phase")
    wall_group_exists = any(
        bool(physical_groups.get(name, {}).get("exists"))
        for name in ("aircraft", "fairing_solid")
    )
    if not (wall_group_exists and all(bool(physical_groups.get(name, {}).get("exists")) for name in ("fluid", "farfield"))):
        failed_checks.append("physical_groups_not_preserved")

    candidate["failed_checks"] = failed_checks
    candidate["passed"] = not failed_checks
    return candidate


def _select_tip_quality_buffer_winner(
    candidates: Iterable[Dict[str, Any]],
) -> tuple[Dict[str, Any] | None, str]:
    candidate_list = [dict(candidate) for candidate in candidates]
    passing = [candidate for candidate in candidate_list if bool(candidate.get("passed"))]
    if not passing:
        return None, "no passing candidates met the quality-clean gates"

    winner = sorted(
        passing,
        key=lambda candidate: (
            int(candidate.get("volume_element_count", 0) or 0),
            int(candidate.get("surface_triangle_count", 0) or 0),
            -float(candidate.get("min_sicn", 0.0) or 0.0),
            -float(candidate.get("min_sige", 0.0) or 0.0),
            str(candidate.get("name", "")),
        ),
    )[0]
    return winner, (
        "selected passing candidate with lowest volume_element_count, "
        "then lowest surface_triangle_count, then highest min_sicn/min_sige"
    )


def _collect_brep_hotspot_report(
    *,
    step_path: Path,
    surface_patch_diagnostics: Dict[str, Any] | None,
    requested_surface_tags: Iterable[int] | None = None,
    requested_curve_tags: Iterable[int] | None = None,
    scale_to_output_units: float = 1.0,
    output_units: str = "m",
) -> Dict[str, Any]:
    request = _resolve_brep_hotspot_request(
        surface_patch_diagnostics=surface_patch_diagnostics,
        requested_surface_tags=requested_surface_tags,
        requested_curve_tags=requested_curve_tags,
    )
    if not request.get("enabled"):
        return {
            "status": "disabled",
            "reason": request.get("reason"),
            **request,
        }

    try:
        from OCP.BRep import BRep_Builder, BRep_Tool
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.BRepGProp import BRepGProp
        from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
        from OCP.Bnd import Bnd_Box
        from OCP.GProp import GProp_GProps
        from OCP.ShapeAnalysis import (
            ShapeAnalysis_CheckSmallFace,
            ShapeAnalysis_Edge,
            ShapeAnalysis_Wire,
        )
        from OCP.ShapeExtend import ShapeExtend_Status
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX, TopAbs_WIRE
        from OCP.TopExp import TopExp, TopExp_Explorer
        from OCP.TopTools import (
            TopTools_IndexedDataMapOfShapeListOfShape,
            TopTools_IndexedMapOfShape,
        )
        from OCP.TopoDS import TopoDS, TopoDS_Shape
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason": "ocp_python_runtime_not_available",
            "error": str(exc),
            **request,
        }

    scale = float(scale_to_output_units or 1.0)
    surface_lookup = {
        int(record["tag"]): record
        for record in (surface_patch_diagnostics or {}).get("surface_records", [])
        if record.get("tag") is not None
    }
    curve_lookup = {
        int(record["tag"]): record
        for record in (surface_patch_diagnostics or {}).get("curve_records", [])
        if record.get("tag") is not None
    }

    status_values = [
        ShapeExtend_Status.ShapeExtend_OK,
        ShapeExtend_Status.ShapeExtend_DONE,
        ShapeExtend_Status.ShapeExtend_DONE1,
        ShapeExtend_Status.ShapeExtend_DONE2,
        ShapeExtend_Status.ShapeExtend_DONE3,
        ShapeExtend_Status.ShapeExtend_DONE4,
        ShapeExtend_Status.ShapeExtend_DONE5,
        ShapeExtend_Status.ShapeExtend_DONE6,
        ShapeExtend_Status.ShapeExtend_DONE7,
        ShapeExtend_Status.ShapeExtend_DONE8,
        ShapeExtend_Status.ShapeExtend_FAIL,
        ShapeExtend_Status.ShapeExtend_FAIL1,
        ShapeExtend_Status.ShapeExtend_FAIL2,
        ShapeExtend_Status.ShapeExtend_FAIL3,
        ShapeExtend_Status.ShapeExtend_FAIL4,
        ShapeExtend_Status.ShapeExtend_FAIL5,
        ShapeExtend_Status.ShapeExtend_FAIL6,
        ShapeExtend_Status.ShapeExtend_FAIL7,
        ShapeExtend_Status.ShapeExtend_FAIL8,
    ]

    def _enum_name(value: Any) -> str:
        return str(getattr(value, "name", value)).split(".")[-1]

    def _scaled_number(value: float | None) -> float | None:
        if value is None:
            return None
        return float(value) * scale

    def _scaled_bbox(shape) -> Dict[str, float]:
        bbox = Bnd_Box()
        BRepBndLib.Add_s(shape, bbox)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
        return {
            "x_min": float(xmin) * scale,
            "y_min": float(ymin) * scale,
            "z_min": float(zmin) * scale,
            "x_max": float(xmax) * scale,
            "y_max": float(ymax) * scale,
            "z_max": float(zmax) * scale,
        }

    def _bbox_center(bbox: Dict[str, float]) -> tuple[float, float, float]:
        return (
            0.5 * (float(bbox["x_min"]) + float(bbox["x_max"])),
            0.5 * (float(bbox["y_min"]) + float(bbox["y_max"])),
            0.5 * (float(bbox["z_min"]) + float(bbox["z_max"])),
        )

    def _bbox_span(bbox: Dict[str, float]) -> tuple[float, float, float]:
        return (
            float(bbox["x_max"]) - float(bbox["x_min"]),
            float(bbox["y_max"]) - float(bbox["y_min"]),
            float(bbox["z_max"]) - float(bbox["z_min"]),
        )

    def _shape_status_payload(analyzer_default, analyzer_exact, subshape) -> Dict[str, Any]:
        return {
            "valid_default": bool(analyzer_default.IsValid(subshape)),
            "valid_exact": bool(analyzer_exact.IsValid(subshape)),
            "statuses_default": _shape_statuses(analyzer_default, subshape),
            "statuses_exact": _shape_statuses(analyzer_exact, subshape),
        }

    def _shape_statuses(analyzer, subshape) -> list[str]:
        result = analyzer.Result(subshape)
        if result is None:
            return []
        return [_enum_name(status) for status in list(result.Status())]

    def _linear_length(shape) -> float:
        props = GProp_GProps()
        BRepGProp.LinearProperties_s(shape, props)
        return float(props.Mass()) * scale

    def _surface_area(shape) -> float:
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(shape, props)
        return float(props.Mass()) * scale * scale

    def _shape_extend_statuses(checker, method_name: str) -> list[str]:
        method = getattr(checker, method_name)
        active: list[str] = []
        for status in status_values:
            try:
                if bool(method(status)):
                    active.append(_enum_name(status))
            except Exception:
                continue
        return active

    geometry_suffix = step_path.suffix.lower()
    geometry_reader = "step"
    if geometry_suffix in {".step", ".stp"}:
        reader = STEPControl_Reader()
        status = reader.ReadFile(str(step_path))
        if status != IFSelect_RetDone:
            return {
                "status": "failed_to_read_step",
                "reason": "step_reader_failed",
                "step_path": str(step_path),
                "geometry_path": str(step_path),
                "reader_status": int(status),
                **request,
            }
        reader.TransferRoots()
        shape = reader.OneShape()
    elif geometry_suffix == ".brep":
        geometry_reader = "brep"
        shape = TopoDS_Shape()
        builder = BRep_Builder()
        try:
            read_ok = bool(BRepTools.Read_s(shape, str(step_path), builder))
        except Exception as exc:
            return {
                "status": "failed_to_read_brep",
                "reason": "brep_reader_failed",
                "step_path": str(step_path),
                "geometry_path": str(step_path),
                "reader_error": str(exc),
                **request,
            }
        if not read_ok or shape.IsNull():
            return {
                "status": "failed_to_read_brep",
                "reason": "brep_reader_returned_null_shape",
                "step_path": str(step_path),
                "geometry_path": str(step_path),
                "reader_status": bool(read_ok),
                **request,
            }
    else:
        return {
            "status": "failed_to_read_geometry",
            "reason": "unsupported_geometry_format_for_brep_hotspot_reader",
            "step_path": str(step_path),
            "geometry_path": str(step_path),
            "geometry_suffix": geometry_suffix,
            **request,
        }

    analyzer_default = BRepCheck_Analyzer(shape)
    analyzer_exact = BRepCheck_Analyzer(shape)
    analyzer_exact.SetExactMethod(True)

    face_index_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_index_map)
    edge_index_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_index_map)
    vertex_index_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, vertex_index_map)
    edge_face_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, edge_face_map)

    face_shapes: Dict[int, Any] = {}
    for index in range(1, face_index_map.Size() + 1):
        face_shapes[index] = TopoDS.Face_s(face_index_map.FindKey(index))

    def _vertex_payload(vertex) -> Dict[str, Any]:
        point = BRep_Tool.Pnt_s(vertex)
        return {
            "vertex_index": int(vertex_index_map.FindIndex(vertex)),
            "coordinates": [float(point.X()) * scale, float(point.Y()) * scale, float(point.Z()) * scale],
            "tolerance": _scaled_number(BRep_Tool.Tolerance_s(vertex)),
        }

    def _edge_record(edge) -> Dict[str, Any]:
        edge_index = int(edge_index_map.FindIndex(edge))
        bbox = _scaled_bbox(edge)
        vertex_first = TopExp.FirstVertex_s(edge)
        vertex_last = TopExp.LastVertex_s(edge)
        edge_tolerance = _scaled_number(BRep_Tool.Tolerance_s(edge))
        edge_range = BRep_Tool.Range_s(edge)
        same_parameter_flag = bool(BRep_Tool.SameParameter_s(edge))
        same_range_flag = bool(BRep_Tool.SameRange_s(edge))
        ancestor_faces = _unique_sorted_ints(
            int(face_index_map.FindIndex(face_shape))
            for face_shape in list(edge_face_map.FindFromKey(edge))
        )
        sa_edge = ShapeAnalysis_Edge()
        pcurve_presence: Dict[str, bool] = {}
        curve3d_with_pcurve: Dict[str, bool | None] = {}
        same_parameter_by_face: Dict[str, bool | None] = {}
        vertex_tolerance_by_face: Dict[str, bool | None] = {}
        pcurve_range_by_face: Dict[str, list[float] | None] = {}
        pcurve_range_matches_edge_range: Dict[str, bool | None] = {}
        for face_id in ancestor_faces:
            face = face_shapes.get(int(face_id))
            if face is None:
                continue
            face_key = str(int(face_id))
            has_pcurve = bool(sa_edge.HasPCurve(edge, face))
            pcurve_presence[face_key] = has_pcurve
            curve3d_with_pcurve[face_key] = (
                bool(sa_edge.CheckCurve3dWithPCurve(edge, face)) if has_pcurve else None
            )
            same_parameter_by_face[face_key] = bool(sa_edge.CheckSameParameter(edge, face, 0.0, 23))
            vertex_tolerance_by_face[face_key] = bool(sa_edge.CheckVertexTolerance(edge, face, 0.0, 0.0))
            if has_pcurve:
                pcurve_range = BRep_Tool.Range_s(edge, face)
                pcurve_range_by_face[face_key] = [float(pcurve_range[0]), float(pcurve_range[1])]
                try:
                    pcurve = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
                    pcurve_range_matches_edge_range[face_key] = bool(
                        sa_edge.CheckPCurveRange(
                            float(edge_range[0]),
                            float(edge_range[1]),
                            pcurve,
                        )
                    )
                except Exception:
                    pcurve_range_matches_edge_range[face_key] = None
            else:
                pcurve_range_by_face[face_key] = None
                pcurve_range_matches_edge_range[face_key] = None
        overlap_edge_indices: list[int] = []
        for other_index in range(1, edge_index_map.Size() + 1):
            if other_index == edge_index:
                continue
            other_edge = TopoDS.Edge_s(edge_index_map.FindKey(other_index))
            other_ancestor_faces = _unique_sorted_ints(
                int(face_index_map.FindIndex(face_shape))
                for face_shape in list(edge_face_map.FindFromKey(other_edge))
            )
            if not set(other_ancestor_faces).intersection(ancestor_faces):
                continue
            tol_overlap = max(
                float(BRep_Tool.Tolerance_s(edge)),
                float(BRep_Tool.Tolerance_s(other_edge)),
                1.0e-9,
            )
            try:
                if bool(sa_edge.CheckOverlapping(edge, other_edge, tol_overlap)):
                    overlap_edge_indices.append(int(other_index))
            except Exception:
                continue
        max_vertex_tolerance = max(
            float(vertex_first.IsNull() and 0.0 or BRep_Tool.Tolerance_s(vertex_first)) * scale,
            float(vertex_last.IsNull() and 0.0 or BRep_Tool.Tolerance_s(vertex_last)) * scale,
        )
        edge_length = _linear_length(edge)
        return {
            "edge_index": edge_index,
            "length_3d": edge_length,
            "bbox": bbox,
            "bbox_center": list(_bbox_center(bbox)),
            "bbox_span": list(_bbox_span(bbox)),
            "edge_tolerance": edge_tolerance,
            "vertex_start": None if vertex_first.IsNull() else _vertex_payload(vertex_first),
            "vertex_end": None if vertex_last.IsNull() else _vertex_payload(vertex_last),
            "same_parameter_flag": same_parameter_flag,
            "same_range_flag": same_range_flag,
            "has_3d_curve": bool(sa_edge.HasCurve3d(edge)),
            "curve_range_3d": [float(edge_range[0]), float(edge_range[1])],
            "ancestor_face_ids": ancestor_faces,
            "pcurve_presence_by_face": pcurve_presence,
            "check_curve3d_with_pcurve_by_face": curve3d_with_pcurve,
            "check_same_parameter_by_face": same_parameter_by_face,
            "check_vertex_tolerance_by_face": vertex_tolerance_by_face,
            "pcurve_range_by_face": pcurve_range_by_face,
            "pcurve_range_matches_edge_range_by_face": pcurve_range_matches_edge_range,
            "brepcheck": _shape_status_payload(analyzer_default, analyzer_exact, edge),
            "overlap_edge_indices": overlap_edge_indices,
            "tolerance_ratios": {
                "length_over_edge_tolerance": (
                    float(edge_length) / float(edge_tolerance)
                    if edge_tolerance not in {None, 0.0}
                    else None
                ),
                "length_over_max_vertex_tolerance": (
                    float(edge_length) / float(max_vertex_tolerance)
                    if max_vertex_tolerance > 0.0
                    else None
                ),
            },
        }

    def _curve_match_score(curve_record: Dict[str, Any], edge_record: Dict[str, Any]) -> float:
        curve_bbox = curve_record.get("bbox", {})
        edge_bbox = edge_record.get("bbox", {})
        curve_center = _bbox_center(curve_bbox)
        edge_center = _bbox_center(edge_bbox)
        curve_span = _bbox_span(curve_bbox)
        edge_span = _bbox_span(edge_bbox)
        length_curve = float(curve_record.get("length", 0.0) or 0.0)
        length_edge = float(edge_record.get("length_3d", 0.0) or 0.0)
        length_scale = max(length_curve, length_edge, 1.0e-12)
        center_scale = max(max(curve_span), max(edge_span), length_scale, 1.0e-9)
        length_term = abs(length_curve - length_edge) / length_scale
        center_term = math.dist(curve_center, edge_center) / center_scale
        span_term = sum(abs(lhs - rhs) for lhs, rhs in zip(curve_span, edge_span)) / max(center_scale, 1.0e-12)
        return length_term * 100.0 + center_term * 10.0 + span_term

    def _match_curves_to_edges(
        curve_ids: list[int],
        edge_records: list[Dict[str, Any]],
    ) -> Dict[int, Dict[str, Any]]:
        pending_curves = [curve_lookup[int(tag)] for tag in curve_ids if int(tag) in curve_lookup]
        pending_edges = list(edge_records)
        matches: Dict[int, Dict[str, Any]] = {}
        while pending_curves and pending_edges:
            best_index_curve = None
            best_index_edge = None
            best_score = None
            for curve_index, curve_record in enumerate(pending_curves):
                for edge_index, edge_record in enumerate(pending_edges):
                    score = _curve_match_score(curve_record, edge_record)
                    if best_score is None or score < best_score:
                        best_score = score
                        best_index_curve = curve_index
                        best_index_edge = edge_index
            if best_index_curve is None or best_index_edge is None:
                break
            curve_record = pending_curves.pop(best_index_curve)
            edge_record = pending_edges.pop(best_index_edge)
            matches[int(curve_record["tag"])] = {
                **edge_record,
                "match_score": float(best_score or 0.0),
            }
        return matches

    context_edge_records: Dict[int, Dict[str, Any]] = {}
    face_reports: list[Dict[str, Any]] = []
    for surface_tag in request.get("selected_surface_tags", []):
        face = face_shapes.get(int(surface_tag))
        if face is None:
            continue
        surface_record = surface_lookup.get(int(surface_tag), {})
        boundary_edge_records: list[Dict[str, Any]] = []
        seen_edge_indices: set[int] = set()
        edge_exp = TopExp_Explorer(face, TopAbs_EDGE)
        while edge_exp.More():
            edge = TopoDS.Edge_s(edge_exp.Current())
            edge_index = int(edge_index_map.FindIndex(edge))
            if edge_index not in seen_edge_indices:
                record = _edge_record(edge)
                seen_edge_indices.add(edge_index)
                boundary_edge_records.append(record)
                context_edge_records[edge_index] = record
            edge_exp.Next()
        matched_curves = _match_curves_to_edges(
            [int(tag) for tag in surface_record.get("curve_tags", [])],
            boundary_edge_records,
        )
        wire_reports: list[Dict[str, Any]] = []
        wire_exp = TopExp_Explorer(face, TopAbs_WIRE)
        wire_index = 0
        while wire_exp.More():
            wire_index += 1
            wire = TopoDS.Wire_s(wire_exp.Current())
            wire_edges: list[int] = []
            wire_edge_explorer = BRepTools_WireExplorer()
            wire_edge_explorer.Init(wire, face)
            while wire_edge_explorer.More():
                wire_edge = TopoDS.Edge_s(wire_edge_explorer.Current())
                wire_edges.append(int(edge_index_map.FindIndex(wire_edge)))
                wire_edge_explorer.Next()
            if not wire_edges:
                edge_in_wire = TopExp_Explorer(wire, TopAbs_EDGE)
                while edge_in_wire.More():
                    wire_edge = TopoDS.Edge_s(edge_in_wire.Current())
                    wire_edges.append(int(edge_index_map.FindIndex(wire_edge)))
                    edge_in_wire.Next()
            wire_precision = max(
                [float(BRep_Tool.Tolerance_s(TopoDS.Edge_s(edge_index_map.FindKey(edge_id)))) for edge_id in wire_edges] or [1.0e-7]
            )
            wire_check = ShapeAnalysis_Wire()
            wire_check.Init(wire, face, wire_precision)
            wire_order_issue = bool(wire_check.CheckOrder(True, True))
            wire_connected_issue = bool(wire_check.CheckConnected())
            wire_closed_issue = bool(wire_check.CheckClosed())
            wire_self_intersection_issue = bool(wire_check.CheckSelfIntersection())
            wire_small_issue = bool(wire_check.CheckSmall())
            wire_reports.append(
                {
                    "wire_index": int(wire_index),
                    "edge_indices": wire_edges,
                    "edge_curve_ids": [
                        next(
                            (
                                int(curve_id)
                                for curve_id, record in matched_curves.items()
                                if int(record["edge_index"]) == int(edge_id)
                            ),
                            None,
                        )
                        for edge_id in wire_edges
                    ],
                    "wire_order_ok": not wire_order_issue,
                    "wire_connected": not wire_connected_issue,
                    "wire_closed": not wire_closed_issue,
                    "wire_self_intersection": wire_self_intersection_issue,
                    "small_edges_detected": wire_small_issue,
                    "status_order": _shape_extend_statuses(wire_check, "StatusOrder"),
                    "status_connected": _shape_extend_statuses(wire_check, "StatusConnected"),
                    "status_closed": _shape_extend_statuses(wire_check, "StatusClosed"),
                    "status_self_intersection": _shape_extend_statuses(wire_check, "StatusSelfIntersection"),
                    "status_small": _shape_extend_statuses(wire_check, "StatusSmall"),
                }
            )
            wire_exp.Next()
        edge_lengths = sorted(
            (
                (
                    float(record["length_3d"]),
                    next((int(curve_id) for curve_id, match in matched_curves.items() if int(match["edge_index"]) == int(record["edge_index"])), None),
                    int(record["edge_index"]),
                )
                for record in boundary_edge_records
            ),
            key=lambda item: item[0],
        )
        width_estimate = None
        length_estimate = None
        width_to_length_ratio = None
        strip_edges: list[int | None] = []
        if edge_lengths:
            length_estimate = float(edge_lengths[-1][0])
            if len(edge_lengths) >= 2:
                width_estimate = float(sum(item[0] for item in edge_lengths[:2]) / 2.0)
                strip_edges = [edge_lengths[0][1], edge_lengths[1][1]]
            else:
                width_estimate = float(edge_lengths[0][0])
                strip_edges = [edge_lengths[0][1]]
            if length_estimate > 0.0:
                width_to_length_ratio = float(width_estimate) / float(length_estimate)
        small_face = ShapeAnalysis_CheckSmallFace()
        strip_pair_hits: list[Dict[str, Any]] = []
        for lhs_index, lhs_record in enumerate(boundary_edge_records):
            lhs_edge = TopoDS.Edge_s(edge_index_map.FindKey(int(lhs_record["edge_index"])))
            for rhs_record in boundary_edge_records[lhs_index + 1:]:
                rhs_edge = TopoDS.Edge_s(edge_index_map.FindKey(int(rhs_record["edge_index"])))
                try:
                    strip_result = small_face.CheckStripFace(face, lhs_edge, rhs_edge, -1.0)
                except Exception:
                    strip_result = False
                try:
                    single_strip = small_face.CheckSingleStrip(face, lhs_edge, rhs_edge, -1.0)
                except Exception:
                    single_strip = False
                if strip_result or single_strip:
                    strip_pair_hits.append(
                        {
                            "lhs_edge_index": int(lhs_record["edge_index"]),
                            "rhs_edge_index": int(rhs_record["edge_index"]),
                            "lhs_curve_id": next((int(curve_id) for curve_id, match in matched_curves.items() if int(match["edge_index"]) == int(lhs_record["edge_index"])), None),
                            "rhs_curve_id": next((int(curve_id) for curve_id, match in matched_curves.items() if int(match["edge_index"]) == int(rhs_record["edge_index"])), None),
                            "check_strip_face_result": bool(strip_result),
                            "check_single_strip_result": bool(single_strip),
                        }
                    )
        uv_bounds = BRepTools.UVBounds_s(face)
        face_reports.append(
            {
                "surface_id": int(surface_tag),
                "surface_area": _surface_area(face),
                "surface_bbox": _scaled_bbox(face),
                "uv_bbox": {
                    "u_min": float(uv_bounds[0]),
                    "u_max": float(uv_bounds[1]),
                    "v_min": float(uv_bounds[2]),
                    "v_max": float(uv_bounds[3]),
                },
                "brepcheck": _shape_status_payload(analyzer_default, analyzer_exact, face),
                "boundary_curves": [
                    {
                        "curve_id": int(curve_id),
                        "edge_index": int(record["edge_index"]),
                        "owner_surface_tags": curve_lookup.get(int(curve_id), {}).get("owner_surface_tags", []),
                        "length_3d": float(record["length_3d"]),
                        "bbox": record["bbox"],
                        "edge_tolerance": record["edge_tolerance"],
                        "vertex_tolerances": {
                            "start": (
                                record["vertex_start"]["tolerance"]
                                if isinstance(record.get("vertex_start"), dict)
                                else None
                            ),
                            "end": (
                                record["vertex_end"]["tolerance"]
                                if isinstance(record.get("vertex_end"), dict)
                                else None
                            ),
                        },
                    }
                    for curve_id, record in sorted(matched_curves.items())
                ],
                "wire_reports": wire_reports,
                "small_face_analysis": {
                    "check_spot_face": bool(small_face.CheckSpotFace(face, -1.0)),
                    "is_strip_support": bool(small_face.IsStripSupport(face, -1.0)),
                    "strip_pair_hits": strip_pair_hits,
                    "geometric_strip_face_candidate": bool(
                        width_to_length_ratio is not None and width_to_length_ratio < 0.05
                    ),
                    "physical_width_estimate": width_estimate,
                    "physical_length_estimate": length_estimate,
                    "width_to_length_ratio": width_to_length_ratio,
                    "strip_edges": strip_edges,
                },
                "adjacent_surfaces_from_diagnostics": _unique_sorted_ints(
                    surface_id
                    for curve_id in surface_record.get("curve_tags", [])
                    for surface_id in curve_lookup.get(int(curve_id), {}).get("owner_surface_tags", [])
                    if int(surface_id) != int(surface_tag)
                ),
            }
        )

    for face_id in request.get("curve_surface_context_tags", []):
        face = face_shapes.get(int(face_id))
        if face is None:
            continue
        edge_exp = TopExp_Explorer(face, TopAbs_EDGE)
        while edge_exp.More():
            edge = TopoDS.Edge_s(edge_exp.Current())
            edge_index = int(edge_index_map.FindIndex(edge))
            if edge_index not in context_edge_records:
                context_edge_records[edge_index] = _edge_record(edge)
            edge_exp.Next()

    curve_reports: list[Dict[str, Any]] = []
    curve_matches = _match_curves_to_edges(
        [int(tag) for tag in request.get("selected_curve_tags", [])],
        list(context_edge_records.values()),
    )
    for curve_tag in request.get("selected_curve_tags", []):
        curve_record = curve_lookup.get(int(curve_tag))
        matched_edge = curve_matches.get(int(curve_tag))
        if curve_record is None:
            continue
        curve_reports.append(
            {
                "curve_id": int(curve_tag),
                "owner_surface_tags": [int(tag) for tag in curve_record.get("owner_surface_tags", [])],
                "gmsh_length_3d": float(curve_record.get("length", 0.0) or 0.0),
                "gmsh_bbox": curve_record.get("bbox"),
                "mapped_edge_index": (
                    int(matched_edge["edge_index"]) if isinstance(matched_edge, dict) else None
                ),
                "match_score": matched_edge.get("match_score") if isinstance(matched_edge, dict) else None,
                "edge_length_3d": matched_edge.get("length_3d") if isinstance(matched_edge, dict) else None,
                "edge_bbox": matched_edge.get("bbox") if isinstance(matched_edge, dict) else None,
                "ancestor_face_ids": matched_edge.get("ancestor_face_ids") if isinstance(matched_edge, dict) else None,
                "edge_tolerance": matched_edge.get("edge_tolerance") if isinstance(matched_edge, dict) else None,
                "vertex_start": matched_edge.get("vertex_start") if isinstance(matched_edge, dict) else None,
                "vertex_end": matched_edge.get("vertex_end") if isinstance(matched_edge, dict) else None,
                "same_parameter_flag": (
                    matched_edge.get("same_parameter_flag") if isinstance(matched_edge, dict) else None
                ),
                "same_range_flag": (
                    matched_edge.get("same_range_flag") if isinstance(matched_edge, dict) else None
                ),
                "has_3d_curve": matched_edge.get("has_3d_curve") if isinstance(matched_edge, dict) else None,
                "curve_range_3d": matched_edge.get("curve_range_3d") if isinstance(matched_edge, dict) else None,
                "pcurve_presence_by_face": (
                    matched_edge.get("pcurve_presence_by_face") if isinstance(matched_edge, dict) else {}
                ),
                "check_curve3d_with_pcurve_by_face": (
                    matched_edge.get("check_curve3d_with_pcurve_by_face") if isinstance(matched_edge, dict) else {}
                ),
                "check_same_parameter_by_face": (
                    matched_edge.get("check_same_parameter_by_face") if isinstance(matched_edge, dict) else {}
                ),
                "check_vertex_tolerance_by_face": (
                    matched_edge.get("check_vertex_tolerance_by_face") if isinstance(matched_edge, dict) else {}
                ),
                "pcurve_range_by_face": (
                    matched_edge.get("pcurve_range_by_face") if isinstance(matched_edge, dict) else {}
                ),
                "pcurve_range_matches_edge_range_by_face": (
                    matched_edge.get("pcurve_range_matches_edge_range_by_face") if isinstance(matched_edge, dict) else {}
                ),
                "overlap_edge_indices": (
                    matched_edge.get("overlap_edge_indices") if isinstance(matched_edge, dict) else []
                ),
                "tolerance_ratios": (
                    matched_edge.get("tolerance_ratios") if isinstance(matched_edge, dict) else {}
                ),
                "brepcheck": matched_edge.get("brepcheck") if isinstance(matched_edge, dict) else None,
            }
        )

    return {
        "status": "captured",
        "step_path": str(step_path),
        "geometry_path": str(step_path),
        "geometry_reader": geometry_reader,
        "units": str(output_units),
        "scale_to_output_units": scale,
        "shape_valid_default": bool(analyzer_default.IsValid(shape)),
        "shape_valid_exact": bool(analyzer_exact.IsValid(shape)),
        "shape_status_default": _shape_statuses(analyzer_default, shape),
        "shape_status_exact": _shape_statuses(analyzer_exact, shape),
        **request,
        "face_reports": face_reports,
        "curve_reports": curve_reports,
    }


def _normalize_compound_groups(groups: Any) -> list[list[int]]:
    normalized: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    if not isinstance(groups, Iterable) or isinstance(groups, (str, bytes, dict)):
        return normalized
    for raw_group in groups:
        if isinstance(raw_group, (str, bytes, dict)) or not isinstance(raw_group, Iterable):
            continue
        group = _unique_sorted_ints(raw_group)
        if len(group) < 2:
            continue
        key = tuple(group)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(group)
    return normalized


def _resolve_compound_meshing_policy(config: MeshJobConfig) -> Dict[str, Any]:
    metadata = config.metadata or {}
    enabled = bool(metadata.get("mesh_compound_enabled", False))
    if not enabled:
        return {"enabled": False, "reason": "disabled_by_metadata"}

    compound_surfaces = _normalize_compound_groups(metadata.get("mesh_compound_surface_groups", []))
    compound_curves = _normalize_compound_groups(metadata.get("mesh_compound_curve_groups", []))
    if not compound_surfaces and not compound_curves:
        return {"enabled": False, "reason": "no_targets"}

    compound_classify = int(metadata.get("mesh_compound_classify", 1))
    compound_mesh_size_factor = metadata.get("mesh_compound_mesh_size_factor")
    if compound_mesh_size_factor is not None:
        compound_mesh_size_factor = float(compound_mesh_size_factor)

    return {
        "enabled": True,
        "name": str(metadata.get("mesh_compound_policy_name", "small_family_compound_v0")),
        "compound_surfaces": compound_surfaces,
        "compound_curves": compound_curves,
        "compound_classify": compound_classify,
        "compound_mesh_size_factor": compound_mesh_size_factor,
        "notes": [
            "small-family compound/reclassify policy requested from config metadata",
            "compound curves are applied before compound surfaces",
            "compound classify is recorded explicitly to track tag preservation semantics",
        ],
    }


def _apply_compound_meshing_policy(
    gmsh,
    *,
    policy: Dict[str, Any],
) -> Dict[str, Any]:
    if not policy.get("enabled"):
        return {
            "status": "disabled",
            "compound_surface_group_count": 0,
            "compound_curve_group_count": 0,
            "compound_surface_tags": [],
            "compound_curve_tags": [],
            "2d_returned": None,
            "3d_returned": None,
            "reparam_success": None,
            "original_surface_tags_preserved": None,
            "original_curve_tags_preserved": None,
            "physical_groups_preserved": None,
        }

    compound_classify = int(policy.get("compound_classify", 1))
    gmsh.option.setNumber("Mesh.CompoundClassify", float(compound_classify))
    compound_mesh_size_factor = policy.get("compound_mesh_size_factor")
    if compound_mesh_size_factor is not None:
        gmsh.option.setNumber("Mesh.CompoundMeshSizeFactor", float(compound_mesh_size_factor))

    compound_curves = [list(group) for group in policy.get("compound_curves", [])]
    compound_surfaces = [list(group) for group in policy.get("compound_surfaces", [])]
    for curve_group in compound_curves:
        gmsh.model.mesh.setCompound(1, curve_group)
    for surface_group in compound_surfaces:
        gmsh.model.mesh.setCompound(2, surface_group)

    return {
        "status": "configured",
        "compound_classify": compound_classify,
        "compound_mesh_size_factor": (
            float(compound_mesh_size_factor) if compound_mesh_size_factor is not None else None
        ),
        "compound_surface_group_count": len(compound_surfaces),
        "compound_curve_group_count": len(compound_curves),
        "compound_surface_groups": compound_surfaces,
        "compound_curve_groups": compound_curves,
        "compound_surface_tags": _unique_sorted_ints(
            tag for group in compound_surfaces for tag in group
        ),
        "compound_curve_tags": _unique_sorted_ints(
            tag for group in compound_curves for tag in group
        ),
        "2d_returned": None,
        "3d_returned": None,
        "reparam_success": None,
        "original_surface_tags_preserved": None,
        "original_curve_tags_preserved": None,
        "physical_groups_preserved": None,
    }


def _entity_tag_set(gmsh, dim: int) -> set[int]:
    return {int(tag) for entity_dim, tag in gmsh.model.getEntities(dim) if int(entity_dim) == int(dim)}


def _safe_physical_group_summary(gmsh, dim: int, physical_tag: int | None) -> Dict[str, Any] | None:
    if physical_tag is None:
        return None
    try:
        return _physical_group_summary(gmsh, dim, int(physical_tag))
    except Exception:
        return None


def _refresh_compound_meshing_result(
    gmsh,
    *,
    compound_result: Dict[str, Any] | None,
    aircraft_group: int | None = None,
    farfield_group: int | None = None,
) -> Dict[str, Any] | None:
    if compound_result is None or compound_result.get("status") == "disabled":
        return compound_result

    surface_tags_present = _entity_tag_set(gmsh, 2)
    curve_tags_present = _entity_tag_set(gmsh, 1)
    compound_surface_tags = [int(tag) for tag in compound_result.get("compound_surface_tags", [])]
    compound_curve_tags = [int(tag) for tag in compound_result.get("compound_curve_tags", [])]
    compound_result["surface_tags_present_after_meshing"] = [
        int(tag) for tag in compound_surface_tags if int(tag) in surface_tags_present
    ]
    compound_result["curve_tags_present_after_meshing"] = [
        int(tag) for tag in compound_curve_tags if int(tag) in curve_tags_present
    ]
    compound_result["original_surface_tags_preserved"] = (
        all(int(tag) in surface_tags_present for tag in compound_surface_tags)
        if compound_surface_tags
        else None
    )
    compound_result["original_curve_tags_preserved"] = (
        all(int(tag) in curve_tags_present for tag in compound_curve_tags)
        if compound_curve_tags
        else None
    )

    aircraft_summary = _safe_physical_group_summary(gmsh, 2, aircraft_group)
    farfield_summary = _safe_physical_group_summary(gmsh, 2, farfield_group)
    if aircraft_summary is not None or farfield_summary is not None:
        compound_result["physical_group_summary"] = {
            "aircraft": aircraft_summary,
            "farfield": farfield_summary,
        }
        compound_result["physical_groups_preserved"] = bool(
            isinstance(aircraft_summary, dict)
            and aircraft_summary.get("exists")
            and isinstance(farfield_summary, dict)
            and farfield_summary.get("exists")
        )
    return compound_result


def _curve_tags_from_surface_records(surface_records: Iterable[Dict[str, Any]]) -> list[int]:
    curve_tags: list[int] = []
    for record in surface_records:
        for curve_tag in record.get("curve_tags", []):
            curve_tags.append(int(curve_tag))
    return _unique_sorted_ints(curve_tags)


def _build_native_esp_surface_meshing_policy(
    *,
    config: MeshJobConfig,
    aircraft_surface_tags: list[int],
    farfield_surface_tags: list[int],
    surface_patch_diagnostics: Dict[str, Any] | None,
    near_body_size: float,
    farfield_size: float,
) -> Dict[str, Any]:
    if config.geometry_provider != "esp_rebuilt":
        return {"enabled": False, "reason": "geometry_provider_not_esp_rebuilt"}
    if config.component not in {"main_wing", "aircraft_assembly"}:
        return {"enabled": False, "reason": "component_outside_c1_scope"}
    if config.metadata.get("esp_native_c1_surface_policy_enabled", True) is False:
        return {"enabled": False, "reason": "disabled_by_metadata"}
    if surface_patch_diagnostics is None:
        return {"enabled": False, "reason": "missing_surface_patch_diagnostics"}

    aircraft_surface_set = {int(tag) for tag in aircraft_surface_tags}
    surface_records = [
        record
        for record in surface_patch_diagnostics.get("surface_records", [])
        if int(record.get("tag", -1)) in aircraft_surface_set
    ]
    if not surface_records:
        return {"enabled": False, "reason": "no_aircraft_surface_records"}

    span_extreme_records: list[Dict[str, Any]] = []
    suspect_records: list[Dict[str, Any]] = []
    for record in surface_records:
        family_hints = {str(hint) for hint in record.get("family_hints", [])}
        if {"short_curve_candidate", "high_aspect_strip_candidate"} - family_hints:
            continue
        if "span_extreme_candidate" in family_hints:
            span_extreme_records.append(record)
            continue
        suspect_records.append(record)

    span_extreme_surface_tags = _unique_sorted_ints(int(record["tag"]) for record in span_extreme_records)
    suspect_surface_tags = _unique_sorted_ints(int(record["tag"]) for record in suspect_records)
    span_extreme_curve_tags = _curve_tags_from_surface_records(span_extreme_records)
    suspect_curve_tags = _curve_tags_from_surface_records(suspect_records)
    farfield_surface_tags_sorted = _unique_sorted_ints(farfield_surface_tags)

    coarse_profile = _resolve_coarse_first_tetra_profile(config)
    coarse_first_active = bool(coarse_profile["enabled"])
    if coarse_first_active:
        primary_floor_default = float(coarse_profile["span_extreme_strip_floor_size"])
        secondary_floor_default = float(coarse_profile["suspect_strip_floor_size"])
        suspect_algorithm_default = int(coarse_profile["suspect_surface_algorithm"])
        general_algorithm_default = int(coarse_profile["general_surface_algorithm"])
        farfield_algorithm_default = int(coarse_profile["farfield_surface_algorithm"])
        policy_name = "esp_rebuilt_native_rule_loft_c1_coarse_first_tetra"
        extra_notes = [
            "coarse-first-tetra surface budget reduction engaged",
            "span-extreme / suspect strip floors raised to defuse first 3D tetra attempt",
        ]
    else:
        primary_floor_default = 0.03
        secondary_floor_default = 0.02
        suspect_algorithm_default = 1
        general_algorithm_default = 5
        farfield_algorithm_default = 5
        policy_name = "esp_rebuilt_native_rule_loft_c1"
        extra_notes = []

    local_size_floors: list[Dict[str, Any]] = []
    if span_extreme_surface_tags:
        local_size_floors.append(
            {
                "name": "span_extreme_strip_floor",
                "size": max(near_body_size, float(config.metadata.get("esp_native_primary_strip_floor_size", primary_floor_default))),
                "surface_tags": span_extreme_surface_tags,
                "curve_tags": span_extreme_curve_tags,
            }
        )
    if suspect_surface_tags:
        local_size_floors.append(
            {
                "name": "suspect_strip_floor",
                "size": max(near_body_size, float(config.metadata.get("esp_native_secondary_strip_floor_size", secondary_floor_default))),
                "surface_tags": suspect_surface_tags,
                "curve_tags": suspect_curve_tags,
            }
        )
    if farfield_surface_tags_sorted:
        local_size_floors.append(
            {
                "name": "farfield_surface_floor",
                "size": max(farfield_size, near_body_size),
                "surface_tags": farfield_surface_tags_sorted,
                "curve_tags": [],
            }
        )

    suspect_family_surface_tags = [*span_extreme_surface_tags, *suspect_surface_tags]
    aircraft_general_surface_tags = _unique_sorted_ints(
        tag for tag in aircraft_surface_tags if int(tag) not in set(suspect_family_surface_tags)
    )

    per_surface_algorithms: list[Dict[str, Any]] = []
    if suspect_family_surface_tags:
        per_surface_algorithms.append(
            {
                "name": "suspect_strip_family",
                "algorithm": int(config.metadata.get("esp_native_suspect_surface_algorithm", suspect_algorithm_default)),
                "surface_tags": suspect_family_surface_tags,
            }
        )
    if aircraft_general_surface_tags:
        per_surface_algorithms.append(
            {
                "name": "aircraft_general_surfaces",
                "algorithm": int(config.metadata.get("esp_native_general_surface_algorithm", general_algorithm_default)),
                "surface_tags": aircraft_general_surface_tags,
            }
        )
    if farfield_surface_tags_sorted:
        per_surface_algorithms.append(
            {
                "name": "farfield_boundary_surfaces",
                "algorithm": int(config.metadata.get("esp_native_farfield_surface_algorithm", farfield_algorithm_default)),
                "surface_tags": farfield_surface_tags_sorted,
            }
        )

    if not local_size_floors and not per_surface_algorithms:
        return {"enabled": False, "reason": "no_policy_targets"}

    return {
        "enabled": True,
        "name": policy_name,
        "coarse_first_tetra_active": coarse_first_active,
        "local_size_floors": local_size_floors,
        "per_surface_algorithms": per_surface_algorithms,
        "notes": [
            "native esp_rebuilt C1 policy enabled",
            "farfield surfaces use a dedicated surface floor and 2D algorithm",
            "suspect strip family gets protected local size floors before full-route meshing",
            *extra_notes,
        ],
    }


def _add_constant_size_floor_field(
    gmsh,
    *,
    size: float,
    surface_tags: list[int],
    curve_tags: list[int],
) -> int:
    field_tag = gmsh.model.mesh.field.add("Constant")
    gmsh.model.mesh.field.setNumber(field_tag, "IncludeBoundary", 1)
    gmsh.model.mesh.field.setNumber(field_tag, "VIn", float(size))
    gmsh.model.mesh.field.setNumber(field_tag, "VOut", 0.0)
    if surface_tags:
        gmsh.model.mesh.field.setNumbers(field_tag, "SurfacesList", surface_tags)
    if curve_tags:
        gmsh.model.mesh.field.setNumbers(field_tag, "CurvesList", curve_tags)
    return field_tag


def _configure_volume_smoke_decoupled_field(
    gmsh,
    *,
    aircraft_surface_tags: list[int],
    near_body_size: float,
    mesh_algorithm_3d: int,
    bounds: Dict[str, float],
    surface_patch_diagnostics: Dict[str, Any] | None,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    if not bool(config.metadata.get("volume_smoke_decoupled_enabled", False)):
        return {"enabled": False, "reason": "disabled_by_metadata"}

    base_volume_size = float(
        config.metadata.get(
            "volume_smoke_base_size",
            config.global_max_size or max(near_body_size * 40.0, DEFAULT_FARFIELD_REFERENCE_FACTOR),
        )
    )
    shell_enabled = bool(config.metadata.get("volume_smoke_shell_enabled", True))
    shell_dist_min = float(config.metadata.get("volume_smoke_shell_dist_min", 0.0))
    shell_dist_max = float(
        config.metadata.get(
            "volume_smoke_shell_dist_max",
            config.metadata.get("mesh_field_distance_max", max(near_body_size * 4.0, 0.05)),
        )
    )
    shell_size_max = float(
        config.metadata.get(
            "volume_smoke_shell_size_max",
            config.metadata.get("volume_smoke_mid_volume_size", base_volume_size),
        )
    )
    stop_at_dist_max = bool(config.metadata.get("volume_smoke_shell_stop_at_dist_max", True))

    base_field = gmsh.model.mesh.field.add("Box")
    gmsh.model.mesh.field.setNumber(base_field, "VIn", base_volume_size)
    gmsh.model.mesh.field.setNumber(base_field, "VOut", base_volume_size)
    gmsh.model.mesh.field.setNumber(base_field, "XMin", float(bounds["x_min"]))
    gmsh.model.mesh.field.setNumber(base_field, "XMax", float(bounds["x_max"]))
    gmsh.model.mesh.field.setNumber(base_field, "YMin", float(bounds["y_min"]))
    gmsh.model.mesh.field.setNumber(base_field, "YMax", float(bounds["y_max"]))
    gmsh.model.mesh.field.setNumber(base_field, "ZMin", float(bounds["z_min"]))
    gmsh.model.mesh.field.setNumber(base_field, "ZMax", float(bounds["z_max"]))

    background_field_tag = base_field
    background_field_composition = "base_far_volume_only"
    near_body_distance_field = None
    near_body_shell_field = None
    fields_list = [base_field]
    tip_quality_buffer_policy = _resolve_tip_quality_buffer_policy(
        config=config,
        surface_patch_diagnostics=surface_patch_diagnostics,
        near_body_size=near_body_size,
    )
    sliver_volume_pocket_policy = _resolve_sliver_volume_pocket_policy(config=config)
    tip_distance_field = None
    tip_threshold_field = None
    sliver_volume_field_tags: list[int] = []

    if shell_enabled:
        near_body_distance_field = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(near_body_distance_field, "FacesList", aircraft_surface_tags)

        near_body_shell_field = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(near_body_shell_field, "InField", near_body_distance_field)
        gmsh.model.mesh.field.setNumber(near_body_shell_field, "SizeMin", near_body_size)
        gmsh.model.mesh.field.setNumber(near_body_shell_field, "SizeMax", shell_size_max)
        gmsh.model.mesh.field.setNumber(near_body_shell_field, "DistMin", shell_dist_min)
        gmsh.model.mesh.field.setNumber(near_body_shell_field, "DistMax", shell_dist_max)
        gmsh.model.mesh.field.setNumber(
            near_body_shell_field,
            "StopAtDistMax",
            1.0 if stop_at_dist_max else 0.0,
        )

        fields_list.append(near_body_shell_field)
        background_field_composition = "min_base_far_volume_with_bounded_shell"

    if tip_quality_buffer_policy.get("enabled"):
        tip_distance_field = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(
            tip_distance_field,
            "FacesList",
            [int(tag) for tag in tip_quality_buffer_policy["selected_surface_tags"]],
        )
        if tip_quality_buffer_policy.get("selected_curve_tags"):
            gmsh.model.mesh.field.setNumbers(
                tip_distance_field,
                "CurvesList",
                [int(tag) for tag in tip_quality_buffer_policy["selected_curve_tags"]],
            )

        tip_threshold_field = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(tip_threshold_field, "InField", tip_distance_field)
        gmsh.model.mesh.field.setNumber(tip_threshold_field, "SizeMin", float(tip_quality_buffer_policy["h_tip_m"]))
        gmsh.model.mesh.field.setNumber(tip_threshold_field, "SizeMax", float(tip_quality_buffer_policy["size_max_m"]))
        gmsh.model.mesh.field.setNumber(tip_threshold_field, "DistMin", float(tip_quality_buffer_policy["dist_min_m"]))
        gmsh.model.mesh.field.setNumber(tip_threshold_field, "DistMax", float(tip_quality_buffer_policy["dist_max_m"]))
        gmsh.model.mesh.field.setNumber(
            tip_threshold_field,
            "StopAtDistMax",
            1.0 if tip_quality_buffer_policy.get("stop_at_dist_max", True) else 0.0,
        )
        fields_list.append(tip_threshold_field)
        if background_field_composition == "base_far_volume_only":
            background_field_composition = "min_base_far_volume_with_tip_quality_buffer"
        else:
            background_field_composition = "min_base_far_volume_with_bounded_shell_and_tip_quality_buffer"

    if sliver_volume_pocket_policy.get("enabled"):
        active_variant = sliver_volume_pocket_policy.get("active_variant", {})
        for pocket in active_variant.get("pockets", []):
            field_type = str(active_variant.get("field_type", "Ball"))
            pocket_field = gmsh.model.mesh.field.add(field_type)
            center = [float(value) for value in pocket.get("center", [0.0, 0.0, 0.0])]
            gmsh.model.mesh.field.setNumber(pocket_field, "XCenter", center[0])
            gmsh.model.mesh.field.setNumber(pocket_field, "YCenter", center[1])
            gmsh.model.mesh.field.setNumber(pocket_field, "ZCenter", center[2])
            gmsh.model.mesh.field.setNumber(pocket_field, "Radius", float(pocket.get("radius", 0.0) or 0.0))
            gmsh.model.mesh.field.setNumber(pocket_field, "VIn", float(pocket.get("VIn", base_volume_size)))
            gmsh.model.mesh.field.setNumber(pocket_field, "VOut", float(pocket.get("VOut", 1e22)))
            if field_type == "Ball":
                gmsh.model.mesh.field.setNumber(
                    pocket_field,
                    "Thickness",
                    float(pocket.get("thickness", 0.0) or 0.0),
                )
            elif field_type == "Cylinder":
                axis = [float(value) for value in pocket.get("axis", [1.0, 0.0, 0.0])]
                length = float(pocket.get("length", 0.0) or 0.0)
                # Gmsh Cylinder fields are anchored at the center of the first circular face,
                # not the midpoint of the whole finite cylinder. Shift from the requested
                # pocket midpoint so the local sliver cluster sits inside the intended pocket.
                cylinder_face_center = [
                    center[0] - 0.5 * axis[0] * length,
                    center[1] - 0.5 * axis[1] * length,
                    center[2] - 0.5 * axis[2] * length,
                ]
                gmsh.model.mesh.field.setNumber(pocket_field, "XCenter", cylinder_face_center[0])
                gmsh.model.mesh.field.setNumber(pocket_field, "YCenter", cylinder_face_center[1])
                gmsh.model.mesh.field.setNumber(pocket_field, "ZCenter", cylinder_face_center[2])
                gmsh.model.mesh.field.setNumber(pocket_field, "XAxis", axis[0] * length)
                gmsh.model.mesh.field.setNumber(pocket_field, "YAxis", axis[1] * length)
                gmsh.model.mesh.field.setNumber(pocket_field, "ZAxis", axis[2] * length)
            sliver_volume_field_tags.append(int(pocket_field))
            fields_list.append(pocket_field)
        if sliver_volume_field_tags:
            if background_field_composition == "base_far_volume_only":
                background_field_composition = "min_base_far_volume_with_sliver_volume_pocket"
            elif "tip_quality_buffer" in background_field_composition:
                background_field_composition += "_and_sliver_volume_pocket"
            else:
                background_field_composition = "min_base_far_volume_with_bounded_shell_and_sliver_volume_pocket"

    if len(fields_list) > 1:
        background_field_tag = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(background_field_tag, "FieldsList", fields_list)

    effective_mesh_size_min = float(near_body_size)
    if tip_quality_buffer_policy.get("enabled"):
        effective_mesh_size_min = min(effective_mesh_size_min, float(tip_quality_buffer_policy["h_tip_m"]))
    if sliver_volume_pocket_policy.get("enabled"):
        pocket_sizes = [
            float(pocket.get("VIn", effective_mesh_size_min) or effective_mesh_size_min)
            for pocket in sliver_volume_pocket_policy.get("active_variant", {}).get("pockets", [])
        ]
        if pocket_sizes:
            effective_mesh_size_min = min(effective_mesh_size_min, min(pocket_sizes))

    gmsh.model.mesh.field.setAsBackgroundMesh(background_field_tag)
    gmsh.option.setNumber("Mesh.MeshSizeMin", float(effective_mesh_size_min))
    gmsh.option.setNumber("Mesh.MeshSizeMax", float(base_volume_size))
    gmsh.option.setNumber(
        "Mesh.MeshSizeFromPoints",
        float(sliver_volume_pocket_policy.get("mesh_size_from_points", 0))
        if sliver_volume_pocket_policy.get("enabled")
        else float(tip_quality_buffer_policy.get("mesh_size_from_points", 0))
        if tip_quality_buffer_policy.get("enabled")
        else 0.0,
    )
    gmsh.option.setNumber(
        "Mesh.MeshSizeFromCurvature",
        float(sliver_volume_pocket_policy.get("mesh_size_from_curvature", 0))
        if sliver_volume_pocket_policy.get("enabled")
        else float(tip_quality_buffer_policy.get("mesh_size_from_curvature", 0))
        if tip_quality_buffer_policy.get("enabled")
        else 0.0,
    )
    gmsh.option.setNumber(
        "Mesh.MeshSizeExtendFromBoundary",
        float(sliver_volume_pocket_policy.get("mesh_size_extend_from_boundary", 0))
        if sliver_volume_pocket_policy.get("enabled")
        else float(tip_quality_buffer_policy.get("mesh_size_extend_from_boundary", 0))
        if tip_quality_buffer_policy.get("enabled")
        else 0.0,
    )
    gmsh.option.setNumber("Mesh.Algorithm3D", float(mesh_algorithm_3d))

    return {
        "enabled": True,
        "name": "volume_smoke_decoupled_v0",
        "background_field_tag": int(background_field_tag),
        "background_field_composition": background_field_composition,
        "base_far_volume_field": {
            "field_tag": int(base_field),
            "kind": "Box",
            "size": float(base_volume_size),
            "bounds": {
                "x_min": float(bounds["x_min"]),
                "x_max": float(bounds["x_max"]),
                "y_min": float(bounds["y_min"]),
                "y_max": float(bounds["y_max"]),
                "z_min": float(bounds["z_min"]),
                "z_max": float(bounds["z_max"]),
            },
        },
        "near_body_shell": {
            "enabled": shell_enabled,
            "distance_field_tag": int(near_body_distance_field) if near_body_distance_field is not None else None,
            "threshold_field_tag": int(near_body_shell_field) if near_body_shell_field is not None else None,
            "surfaces_list": [int(tag) for tag in aircraft_surface_tags] if shell_enabled else [],
            "size_min": float(near_body_size) if shell_enabled else None,
            "size_max": float(shell_size_max) if shell_enabled else None,
            "dist_min": float(shell_dist_min) if shell_enabled else None,
            "dist_max": float(shell_dist_max) if shell_enabled else None,
            "stop_at_dist_max": bool(stop_at_dist_max) if shell_enabled else None,
        },
        "tip_quality_buffer_policy": {
            "enabled": bool(tip_quality_buffer_policy.get("enabled", False)),
            "source_baseline": tip_quality_buffer_policy.get("source_baseline"),
            "target_surfaces": [int(tag) for tag in tip_quality_buffer_policy.get("target_surfaces", [])],
            "target_curves": [int(tag) for tag in tip_quality_buffer_policy.get("target_curves", [])],
            "optional_expanded_surfaces": [
                int(tag) for tag in tip_quality_buffer_policy.get("optional_expanded_surfaces", [])
            ],
            "width_reference_m": tip_quality_buffer_policy.get("width_reference_m"),
            "active_variant": tip_quality_buffer_policy.get("active_variant"),
            "selected_surface_tags": [
                int(tag) for tag in tip_quality_buffer_policy.get("selected_surface_tags", [])
            ],
            "selected_curve_tags": [int(tag) for tag in tip_quality_buffer_policy.get("selected_curve_tags", [])],
            "curve_owner_surface_tags": [
                int(tag) for tag in tip_quality_buffer_policy.get("curve_owner_surface_tags", [])
            ],
            "curve_surface_context_tags": [
                int(tag) for tag in tip_quality_buffer_policy.get("curve_surface_context_tags", [])
            ],
            "h_tip_m": tip_quality_buffer_policy.get("h_tip_m"),
            "size_max_m": tip_quality_buffer_policy.get("size_max_m"),
            "dist_min_m": tip_quality_buffer_policy.get("dist_min_m"),
            "dist_max_m": tip_quality_buffer_policy.get("dist_max_m"),
            "stop_at_dist_max": tip_quality_buffer_policy.get("stop_at_dist_max"),
            "mesh_size_from_points": tip_quality_buffer_policy.get("mesh_size_from_points"),
            "mesh_size_from_curvature": tip_quality_buffer_policy.get("mesh_size_from_curvature"),
            "mesh_size_extend_from_boundary": tip_quality_buffer_policy.get("mesh_size_extend_from_boundary"),
            "distance_field_tag": int(tip_distance_field) if tip_distance_field is not None else None,
            "threshold_field_tag": int(tip_threshold_field) if tip_threshold_field is not None else None,
            "missing_surface_tags": [
                int(tag) for tag in tip_quality_buffer_policy.get("missing_surface_tags", [])
            ],
            "missing_curve_tags": [int(tag) for tag in tip_quality_buffer_policy.get("missing_curve_tags", [])],
        },
        "sliver_volume_pocket_policy": {
            "enabled": bool(sliver_volume_pocket_policy.get("enabled", False)),
            "source_baseline": sliver_volume_pocket_policy.get("source_baseline"),
            "cluster_report_path": sliver_volume_pocket_policy.get("cluster_report_path"),
            "active_variant": sliver_volume_pocket_policy.get("active_variant"),
            "field_tags": sliver_volume_field_tags,
            "mesh_size_from_points": sliver_volume_pocket_policy.get("mesh_size_from_points"),
            "mesh_size_from_curvature": sliver_volume_pocket_policy.get("mesh_size_from_curvature"),
            "mesh_size_extend_from_boundary": sliver_volume_pocket_policy.get("mesh_size_extend_from_boundary"),
        },
        "field_architecture": {
            "base_far_volume_enabled": True,
            "base_far_volume_kind": "Box",
            "near_body_shell_enabled": bool(shell_enabled),
            "near_body_shell_stop_at_dist_max": bool(stop_at_dist_max) if shell_enabled else False,
            "tip_quality_buffer_enabled": bool(tip_quality_buffer_policy.get("enabled", False)),
            "tip_quality_buffer_stop_at_dist_max": bool(tip_quality_buffer_policy.get("stop_at_dist_max", False)),
            "sliver_volume_pocket_enabled": bool(sliver_volume_pocket_policy.get("enabled", False)),
            "effective_mesh_size_min": float(effective_mesh_size_min),
            "mesh_size_from_points": (
                int(sliver_volume_pocket_policy.get("mesh_size_from_points", 0))
                if sliver_volume_pocket_policy.get("enabled")
                else (
                int(tip_quality_buffer_policy.get("mesh_size_from_points", 0))
                if tip_quality_buffer_policy.get("enabled")
                else 0
                )
            ),
            "mesh_size_from_curvature": (
                int(sliver_volume_pocket_policy.get("mesh_size_from_curvature", 0))
                if sliver_volume_pocket_policy.get("enabled")
                else (
                int(tip_quality_buffer_policy.get("mesh_size_from_curvature", 0))
                if tip_quality_buffer_policy.get("enabled")
                else 0
                )
            ),
            "mesh_size_extend_from_boundary": (
                int(sliver_volume_pocket_policy.get("mesh_size_extend_from_boundary", 0))
                if sliver_volume_pocket_policy.get("enabled")
                else (
                int(tip_quality_buffer_policy.get("mesh_size_extend_from_boundary", 0))
                if tip_quality_buffer_policy.get("enabled")
                else 0
                )
            ),
            "distance_faces_source": "aircraft_surfaces_only" if shell_enabled else "disabled",
            "distance_faces_exclude_farfield": True,
            "background_field_composition": background_field_composition,
        },
    }


def _configure_mesh_field(
    gmsh,
    aircraft_surface_tags: list[int],
    aircraft_curve_tags: list[int],
    reference_length: float,
    config: MeshJobConfig,
    *,
    farfield_surface_tags: list[int] | None = None,
    surface_patch_diagnostics: Dict[str, Any] | None = None,
    resolved_field_defaults: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    field_defaults = resolved_field_defaults or _resolve_mesh_field_defaults(reference_length, config)
    near_body_size = float(field_defaults["near_body_size"])
    edge_size = float(field_defaults["edge_size"])
    farfield_size = float(field_defaults["farfield_size"])
    distance_min = float(field_defaults["distance_min"])
    distance_max = float(field_defaults["distance_max"])
    edge_distance_max = float(field_defaults["edge_distance_max"])
    mesh_algorithm_2d = int(field_defaults["mesh_algorithm_2d"])
    mesh_algorithm_3d = int(field_defaults["mesh_algorithm_3d"])

    surface_distance_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(surface_distance_field, "FacesList", aircraft_surface_tags)

    surface_threshold_field = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(surface_threshold_field, "InField", surface_distance_field)
    gmsh.model.mesh.field.setNumber(surface_threshold_field, "SizeMin", near_body_size)
    gmsh.model.mesh.field.setNumber(surface_threshold_field, "SizeMax", farfield_size)
    gmsh.model.mesh.field.setNumber(surface_threshold_field, "DistMin", distance_min)
    gmsh.model.mesh.field.setNumber(surface_threshold_field, "DistMax", distance_max)

    edge_distance_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(edge_distance_field, "CurvesList", aircraft_curve_tags)

    edge_threshold_field = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(edge_threshold_field, "InField", edge_distance_field)
    gmsh.model.mesh.field.setNumber(edge_threshold_field, "SizeMin", edge_size)
    gmsh.model.mesh.field.setNumber(edge_threshold_field, "SizeMax", near_body_size)
    gmsh.model.mesh.field.setNumber(edge_threshold_field, "DistMin", 0.0)
    gmsh.model.mesh.field.setNumber(edge_threshold_field, "DistMax", edge_distance_max)

    combined_field = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(combined_field, "FieldsList", [surface_threshold_field, edge_threshold_field])

    surface_policy = _build_native_esp_surface_meshing_policy(
        config=config,
        aircraft_surface_tags=aircraft_surface_tags,
        farfield_surface_tags=farfield_surface_tags or [],
        surface_patch_diagnostics=surface_patch_diagnostics,
        near_body_size=near_body_size,
        farfield_size=farfield_size,
    )
    background_field_tag = combined_field
    background_field_composition = "base_min_field"
    local_size_floors_payload: list[Dict[str, Any]] = []
    if surface_policy.get("enabled"):
        fields_list = [combined_field]
        for floor in surface_policy["local_size_floors"]:
            floor_surface_tags = _unique_sorted_ints(floor.get("surface_tags", []))
            floor_curve_tags = _unique_sorted_ints(floor.get("curve_tags", []))
            field_tag = _add_constant_size_floor_field(
                gmsh,
                size=float(floor["size"]),
                surface_tags=floor_surface_tags,
                curve_tags=floor_curve_tags,
            )
            fields_list.append(field_tag)
            local_size_floors_payload.append(
                {
                    "name": str(floor["name"]),
                    "size": float(floor["size"]),
                    "surface_tags": floor_surface_tags,
                    "curve_tags": floor_curve_tags,
                }
            )
        if len(fields_list) > 1:
            background_field_tag = gmsh.model.mesh.field.add("Max")
            gmsh.model.mesh.field.setNumbers(background_field_tag, "FieldsList", fields_list)
            background_field_composition = "max_with_local_floors"
        for algorithm_spec in surface_policy["per_surface_algorithms"]:
            for surface_tag in algorithm_spec["surface_tags"]:
                gmsh.model.mesh.setAlgorithm(2, int(surface_tag), int(algorithm_spec["algorithm"]))
    gmsh.model.mesh.field.setAsBackgroundMesh(background_field_tag)

    coarse_profile = field_defaults.get("coarse_first_tetra") if isinstance(field_defaults, dict) else None
    if coarse_profile is None:
        coarse_profile = _resolve_coarse_first_tetra_profile(config)
    coarse_first_active = bool(coarse_profile.get("enabled", False))
    mesh_size_min_value = float(
        near_body_size if (coarse_first_active and coarse_profile.get("clamp_mesh_size_min_to_near_body", True)) else edge_size
    )
    surface_nodes_per_reference_length = float(
        field_defaults.get("surface_nodes_per_reference_length", DEFAULT_SURFACE_NODES_PER_REFERENCE_LENGTH)
        if isinstance(field_defaults, dict)
        else DEFAULT_SURFACE_NODES_PER_REFERENCE_LENGTH
    )
    edge_refinement_ratio_value = float(
        field_defaults.get("edge_refinement_ratio", DEFAULT_EDGE_REFINEMENT_RATIO)
        if isinstance(field_defaults, dict)
        else DEFAULT_EDGE_REFINEMENT_RATIO
    )
    optimization_settings = _resolve_mesh_optimization_settings(config)

    gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size_min_value)
    gmsh.option.setNumber("Mesh.MeshSizeMax", farfield_size)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    _apply_mesh_optimization_options(gmsh, optimization_settings)
    gmsh.option.setNumber("Mesh.Algorithm", float(mesh_algorithm_2d))
    gmsh.option.setNumber("Mesh.Algorithm3D", float(mesh_algorithm_3d))

    return {
        "characteristic_length_policy": "reference_length",
        "reference_length": reference_length,
        "surface_target_nodes_per_reference_length": (
            int(surface_nodes_per_reference_length)
            if surface_nodes_per_reference_length.is_integer()
            else surface_nodes_per_reference_length
        ),
        "edge_refinement_ratio": edge_refinement_ratio_value,
        "near_body_size": near_body_size,
        "edge_size": edge_size,
        "farfield_size": farfield_size,
        "distance_min": distance_min,
        "distance_max": distance_max,
        "edge_distance_max": edge_distance_max,
        "mesh_size_min": mesh_size_min_value,
        "mesh_size_from_points": 0,
        "mesh_size_from_curvature": 0,
        "mesh_size_extend_from_boundary": 0,
        "volume_optimization": optimization_settings,
        "mesh_algorithm_2d": mesh_algorithm_2d,
        "mesh_algorithm_3d": mesh_algorithm_3d,
        "background_field_tag": int(background_field_tag),
        "background_field_composition": background_field_composition,
        "local_size_floors": local_size_floors_payload,
        "per_surface_algorithms": [
            {
                "name": str(spec["name"]),
                "algorithm": int(spec["algorithm"]),
                "algorithm_name": _mesh_algorithm_name(int(spec["algorithm"])),
                "surface_tags": [int(tag) for tag in spec["surface_tags"]],
            }
            for spec in surface_policy.get("per_surface_algorithms", [])
        ],
        "surface_policy": {
            "enabled": bool(surface_policy.get("enabled", False)),
            "name": surface_policy.get("name"),
            "reason": surface_policy.get("reason"),
            "notes": list(surface_policy.get("notes", [])),
            "coarse_first_tetra_active": bool(surface_policy.get("coarse_first_tetra_active", False)),
        },
        "coarse_first_tetra": {
            "enabled": coarse_first_active,
            "clamp_mesh_size_min_to_near_body": bool(coarse_profile.get("clamp_mesh_size_min_to_near_body", True)),
            "surface_nodes_per_reference_length": float(coarse_profile.get("surface_nodes_per_reference_length", COARSE_FIRST_TETRA_SURFACE_NODES_PER_REFERENCE_LENGTH)),
            "edge_refinement_ratio": float(coarse_profile.get("edge_refinement_ratio", COARSE_FIRST_TETRA_EDGE_REFINEMENT_RATIO)),
            "span_extreme_strip_floor_size": float(coarse_profile.get("span_extreme_strip_floor_size", COARSE_FIRST_TETRA_SPAN_EXTREME_STRIP_FLOOR_SIZE)),
            "suspect_strip_floor_size": float(coarse_profile.get("suspect_strip_floor_size", COARSE_FIRST_TETRA_SUSPECT_STRIP_FLOOR_SIZE)),
            "suspect_surface_algorithm": int(coarse_profile.get("suspect_surface_algorithm", COARSE_FIRST_TETRA_SUSPECT_SURFACE_ALGORITHM)),
            "general_surface_algorithm": int(coarse_profile.get("general_surface_algorithm", COARSE_FIRST_TETRA_GENERAL_SURFACE_ALGORITHM)),
            "farfield_surface_algorithm": int(coarse_profile.get("farfield_surface_algorithm", COARSE_FIRST_TETRA_FARFIELD_SURFACE_ALGORITHM)),
        },
    }


def _run_mesh2d_with_watchdog(
    gmsh,
    *,
    watchdog_path: Path,
    sample_path: Path,
    timeout_seconds: float,
    sample_seconds: int,
    sample_runner: Callable[[int, int, Path], Dict[str, Any]] = _run_process_sample,
    surface_patch_lookup: Dict[int, Dict[str, Any]] | None = None,
    curve_patch_lookup: Dict[int, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": "armed",
        "pid": int(os.getpid()),
        "timeout_seconds": float(timeout_seconds),
        "sample_seconds": int(sample_seconds),
        "sample_artifact": str(sample_path),
        "partial_surface_mesh_artifact": None,
        "partial_surface_mesh_attempted": False,
        "partial_surface_mesh_reason": "not_attempted_while_gmsh_generate2_is_active",
    }
    start = time.monotonic()
    completed = threading.Event()
    payload_lock = threading.Lock()

    def _trigger_watchdog() -> None:
        if completed.wait(float(timeout_seconds)):
            return
        try:
            logger_messages = [str(message) for message in gmsh.logger.get()]
        except Exception as exc:
            logger_messages = [f"gmsh.logger.get failed during Mesh2D watchdog capture: {exc}"]
        last_curve = _extract_last_meshing_curve(logger_messages)
        last_surface = _extract_last_meshing_surface(logger_messages)
        sample_result = sample_runner(int(os.getpid()), int(sample_seconds), sample_path)
        with payload_lock:
            payload["status"] = "triggered_while_meshing"
            payload["triggered_at_elapsed_sec"] = float(time.monotonic() - start)
            payload["logger_message_count"] = len(logger_messages)
            payload["meshing_stage_at_timeout"] = _infer_meshing_stage(logger_messages)
            payload["logger_tail"] = _logger_tail(logger_messages)
            payload["last_meshing_curve_tag"] = (
                int(last_curve["curve_tag"]) if last_curve is not None else None
            )
            payload["last_meshing_curve_message"] = (
                str(last_curve["message"]) if last_curve is not None else None
            )
            payload["last_meshing_curve_record"] = (
                curve_patch_lookup.get(int(last_curve["curve_tag"]))
                if (last_curve is not None and curve_patch_lookup is not None)
                else None
            )
            payload["last_meshing_surface_tag"] = (
                int(last_surface["surface_tag"]) if last_surface is not None else None
            )
            payload["last_meshing_surface_message"] = (
                str(last_surface["message"]) if last_surface is not None else None
            )
            payload["last_meshing_surface_record"] = _surface_patch_excerpt(
                surface_patch_lookup.get(int(last_surface["surface_tag"]))
                if (last_surface is not None and surface_patch_lookup is not None)
                else None
            )
            payload["sample"] = sample_result
        _json_write(watchdog_path, payload)

    watchdog_thread = threading.Thread(target=_trigger_watchdog, name="mesh2d-watchdog", daemon=True)
    watchdog_thread.start()
    try:
        gmsh.model.mesh.generate(2)
    finally:
        completed.set()
        watchdog_thread.join(timeout=0.5)

    try:
        final_logger_messages = [str(message) for message in gmsh.logger.get()]
    except Exception as exc:
        final_logger_messages = [f"gmsh.logger.get failed after Mesh2D: {exc}"]
    last_curve = _extract_last_meshing_curve(final_logger_messages)
    last_surface = _extract_last_meshing_surface(final_logger_messages)
    with payload_lock:
        payload["completed_elapsed_sec"] = float(time.monotonic() - start)
        payload["logger_message_count_after_generate"] = len(final_logger_messages)
        payload["meshing_stage_after_generate"] = _infer_meshing_stage(final_logger_messages)
        payload["logger_tail_after_generate"] = _logger_tail(final_logger_messages)
        if last_curve is not None:
            payload["last_meshing_curve_tag_after_generate"] = int(last_curve["curve_tag"])
            payload["last_meshing_curve_message_after_generate"] = str(last_curve["message"])
        if last_surface is not None:
            payload["last_meshing_surface_tag_after_generate"] = int(last_surface["surface_tag"])
            payload["last_meshing_surface_message_after_generate"] = str(last_surface["message"])
        if payload["status"] == "armed":
            payload["status"] = "completed_without_timeout"
        elif payload["status"] == "triggered_while_meshing":
            payload["status"] = "completed_after_timeout"
    _json_write(watchdog_path, payload)
    return payload


def _run_mesh3d_with_watchdog(
    gmsh,
    *,
    watchdog_path: Path,
    sample_path: Path,
    timeout_seconds: float,
    sample_seconds: int,
    mesh_algorithm_3d: int,
    pre_mesh_stats: Dict[str, Any] | None = None,
    sample_runner: Callable[[int, int, Path], Dict[str, Any]] = _run_process_sample,
) -> tuple[Dict[str, Any], Exception | None]:
    payload: Dict[str, Any] = {
        "status": "armed",
        "pid": int(os.getpid()),
        "timeout_seconds": float(timeout_seconds),
        "sample_seconds": int(sample_seconds),
        "sample_artifact": str(sample_path),
        "mesh_algorithm_3d": int(mesh_algorithm_3d),
        "pre_mesh_stats": dict(pre_mesh_stats or {}),
    }
    start = time.monotonic()
    completed = threading.Event()
    payload_lock = threading.Lock()

    def _trigger_watchdog() -> None:
        if completed.wait(float(timeout_seconds)):
            return
        try:
            logger_messages = [str(message) for message in gmsh.logger.get()]
        except Exception as exc:
            logger_messages = [f"gmsh.logger.get failed during Mesh3D watchdog capture: {exc}"]
        volume_summary = _extract_3d_meshing_volume(logger_messages)
        tetra_summary = _extract_tetrahedrizing_node_count(logger_messages)
        sample_result = sample_runner(int(os.getpid()), int(sample_seconds), sample_path)
        burden_metrics = _extract_3d_burden_metrics(logger_messages, pre_mesh_stats)
        with payload_lock:
            payload["status"] = "triggered_while_meshing"
            payload["triggered_at_elapsed_sec"] = float(time.monotonic() - start)
            payload["logger_message_count"] = len(logger_messages)
            payload["meshing_stage_at_timeout"] = _infer_meshing_stage(logger_messages)
            payload["logger_tail"] = _logger_tail(logger_messages)
            payload.update(burden_metrics)
            if volume_summary is not None:
                payload["volume_count"] = int(volume_summary["volume_count"])
                payload["connected_component_count"] = int(volume_summary["connected_component_count"])
                payload["volume_meshing_message"] = str(volume_summary["message"])
            if tetra_summary is not None:
                payload["tetrahedrizing_node_count"] = int(tetra_summary["tetrahedrizing_node_count"])
                payload["tetrahedrizing_message"] = str(tetra_summary["message"])
            payload["sample"] = sample_result
        _json_write(watchdog_path, payload)

    watchdog_thread = threading.Thread(target=_trigger_watchdog, name="mesh3d-watchdog", daemon=True)
    watchdog_thread.start()
    mesh_error: Exception | None = None
    try:
        gmsh.model.mesh.generate(3)
    except Exception as exc:
        mesh_error = exc
    finally:
        completed.set()
        watchdog_thread.join(timeout=0.5)

    try:
        final_logger_messages = [str(message) for message in gmsh.logger.get()]
    except Exception as exc:
        final_logger_messages = [f"gmsh.logger.get failed after Mesh3D: {exc}"]
    volume_summary = _extract_3d_meshing_volume(final_logger_messages)
    tetra_summary = _extract_tetrahedrizing_node_count(final_logger_messages)
    burden_metrics_after_return = _extract_3d_burden_metrics(final_logger_messages, pre_mesh_stats)
    with payload_lock:
        payload["completed_elapsed_sec"] = float(time.monotonic() - start)
        payload["logger_message_count_after_return"] = len(final_logger_messages)
        payload["meshing_stage_after_return"] = _infer_meshing_stage(final_logger_messages)
        payload["logger_tail_after_return"] = _logger_tail(final_logger_messages)
        payload["phase_classification_after_return"] = burden_metrics_after_return.get("timeout_phase_classification")
        if payload.get("timeout_phase_classification") is None:
            payload["timeout_phase_classification"] = payload["phase_classification_after_return"]
        for key in (
            "boundary_node_count",
            "surface_triangle_count",
            "iteration_count",
            "nodes_created",
            "nodes_created_per_boundary_node",
            "iterations_per_surface_triangle",
            "hxt_points_considered",
            "hxt_mesh_vertex_count",
            "hxt_points_filtered",
            "hxt_points_added",
            "latest_iteration_message",
            "latest_worst_tet_radius",
            "nodes_removed",
            "nodes_removed_total",
        ):
            if key in burden_metrics_after_return:
                payload[f"{key}_after_return"] = burden_metrics_after_return[key]
                if payload.get(key) is None:
                    payload[key] = burden_metrics_after_return[key]
        if volume_summary is not None:
            payload["volume_count_after_return"] = int(volume_summary["volume_count"])
            payload["connected_component_count_after_return"] = int(volume_summary["connected_component_count"])
            payload["volume_meshing_message_after_return"] = str(volume_summary["message"])
            if payload.get("volume_count") is None:
                payload["volume_count"] = int(volume_summary["volume_count"])
            if payload.get("connected_component_count") is None:
                payload["connected_component_count"] = int(volume_summary["connected_component_count"])
        if tetra_summary is not None:
            payload["tetrahedrizing_node_count_after_return"] = int(tetra_summary["tetrahedrizing_node_count"])
            payload["tetrahedrizing_message_after_return"] = str(tetra_summary["message"])
            if payload.get("tetrahedrizing_node_count") is None:
                payload["tetrahedrizing_node_count"] = int(tetra_summary["tetrahedrizing_node_count"])
            if payload.get("tetrahedrizing_message") is None:
                payload["tetrahedrizing_message"] = str(tetra_summary["message"])
        if mesh_error is not None:
            payload["error"] = str(mesh_error)
            if payload["status"] == "armed":
                payload["status"] = "failed_without_timeout"
            elif payload["status"] == "triggered_while_meshing":
                payload["status"] = "failed_after_timeout"
        elif payload["status"] == "armed":
            payload["status"] = "completed_without_timeout"
        elif payload["status"] == "triggered_while_meshing":
            payload["status"] = "completed_after_timeout"
    _json_write(watchdog_path, payload)
    return payload, mesh_error


def _heal_imported_bodies(gmsh, body_dim_tags: list[tuple[int, int]]) -> tuple[list[tuple[int, int]], Dict[str, Any]]:
    summary: Dict[str, Any] = {
        "attempted": True,
        "input_volume_count": len(body_dim_tags),
        "input_surface_count": len(gmsh.model.getEntities(2)),
        "tolerance": 1.0e-8,
    }
    healed_entities = gmsh.model.occ.healShapes(
        body_dim_tags,
        tolerance=1.0e-8,
        fixDegenerated=True,
        fixSmallEdges=True,
        fixSmallFaces=True,
        sewFaces=True,
        makeSolids=True,
    )
    gmsh.model.occ.removeAllDuplicates()
    gmsh.model.occ.synchronize()

    healed_body_dim_tags = [entity for entity in healed_entities if entity[0] == 3]
    if not healed_body_dim_tags:
        healed_body_dim_tags = gmsh.model.getEntities(3)

    summary.update(
        {
            "output_volume_count": len(healed_body_dim_tags),
            "output_surface_count": len(gmsh.model.getEntities(2)),
        }
    )
    return healed_body_dim_tags, summary


def _should_skip_occ_heal(handle: GeometryHandle) -> bool:
    # ESP normalization removes known symmetry interfaces, but the resulting OCC shell can
    # still contain free curves or overlapping surface patches that only show up during the
    # external-flow cut/mesh path. Keep healing enabled until the route proves it can import
    # these provider outputs without geometric inconsistencies.
    return False


def _maybe_heal_imported_bodies(
    gmsh,
    body_dim_tags: list[tuple[int, int]],
    *,
    skip_heal: bool,
) -> tuple[list[tuple[int, int]], Dict[str, Any]]:
    if not skip_heal:
        return _heal_imported_bodies(gmsh, body_dim_tags)
    summary = {
        "attempted": False,
        "reason": "skipped_for_provider_declared_clean_external_geometry",
        "input_volume_count": len(body_dim_tags),
        "input_surface_count": len(gmsh.model.getEntities(2)),
        "output_volume_count": len(body_dim_tags),
        "output_surface_count": len(gmsh.model.getEntities(2)),
    }
    return body_dim_tags, summary


def _count_elements_for_entities(gmsh, dim: int, entity_tags: Iterable[int]) -> tuple[int, Dict[str, int]]:
    total = 0
    type_counts: Dict[str, int] = {}
    for entity_tag in entity_tags:
        types, element_tags, _ = gmsh.model.mesh.getElements(dim, int(entity_tag))
        for element_type, tags in zip(types, element_tags):
            count = len(tags)
            total += count
            type_counts[str(int(element_type))] = type_counts.get(str(int(element_type)), 0) + count
    return total, type_counts


def _physical_group_summary(gmsh, dim: int, physical_tag: int) -> Dict[str, Any]:
    entity_tags = [int(tag) for tag in gmsh.model.getEntitiesForPhysicalGroup(dim, physical_tag)]
    element_count, element_type_counts = _count_elements_for_entities(gmsh, dim, entity_tags)
    physical_name = gmsh.model.getPhysicalName(dim, physical_tag)
    return {
        "exists": True,
        "dimension": dim,
        "physical_name": physical_name,
        "physical_tag": physical_tag,
        "entity_count": len(entity_tags),
        "entities": entity_tags,
        "element_count": element_count,
        "element_type_counts": element_type_counts,
    }


def _mesh_stats(gmsh) -> Dict[str, Any]:
    node_tags, _, _ = gmsh.model.mesh.getNodes()
    all_types, all_element_tags, _ = gmsh.model.mesh.getElements()
    surface_types, surface_element_tags, _ = gmsh.model.mesh.getElements(2)
    volume_types, volume_element_tags, _ = gmsh.model.mesh.getElements(3)
    return {
        "node_count": len(node_tags),
        "element_count": sum(len(tags) for tags in all_element_tags),
        "surface_element_count": sum(len(tags) for tags in surface_element_tags),
        "volume_element_count": sum(len(tags) for tags in volume_element_tags),
        "element_type_counts": {
            str(int(element_type)): len(tags)
            for element_type, tags in zip(all_types, all_element_tags)
        },
        "surface_element_type_counts": {
            str(int(element_type)): len(tags)
            for element_type, tags in zip(surface_types, surface_element_tags)
        },
        "volume_element_type_counts": {
            str(int(element_type)): len(tags)
            for element_type, tags in zip(volume_types, volume_element_tags)
        },
    }


def _extract_logged_intersection_points(logger_messages: Iterable[str]) -> list[list[float]]:
    points: list[list[float]] = []
    seen: set[tuple[float, float, float]] = set()
    for message in logger_messages:
        for match in PLC_INTERSECTION_POINT_PATTERN.finditer(str(message)):
            point = (
                float(match.group(1)),
                float(match.group(2)),
                float(match.group(3)),
            )
            if point in seen:
                continue
            seen.add(point)
            points.append([point[0], point[1], point[2]])
    return points


def _probe_radius_for_point(point: list[float]) -> float:
    scale = max(max(abs(float(value)) for value in point), 1.0)
    return max(scale * 1.0e-5, 1.0e-4)


def _should_attempt_surface_repair_fallback(error_text: str, logger_messages: Iterable[str]) -> bool:
    combined = "\n".join([str(error_text), *(str(message) for message in logger_messages)]).lower()
    return any(signature in combined for signature in SURFACE_REPAIR_ERROR_SIGNATURES)


def _should_probe_discrete_classify_angles(
    surface_repair_result: Dict[str, Any] | None,
    *,
    surface_mesh_exists: bool,
    classify_probe_exists: bool,
) -> bool:
    if not surface_repair_result or surface_repair_result.get("status") != "failed":
        return False
    if not surface_mesh_exists or classify_probe_exists:
        return False
    error_text = str(surface_repair_result.get("error") or "").lower()
    if "did not generate any volume elements" in error_text:
        return False
    return True


def _physical_groups_payload(gmsh) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for dim, tag in gmsh.model.getPhysicalGroups():
        groups.append(
            {
                "dim": int(dim),
                "tag": int(tag),
                "name": gmsh.model.getPhysicalName(int(dim), int(tag)),
            }
        )
    return groups


def _entity_counts_snapshot(gmsh) -> Dict[str, Any]:
    return {
        "point_count": len(gmsh.model.getEntities(0)),
        "curve_count": len(gmsh.model.getEntities(1)),
        "surface_count": len(gmsh.model.getEntities(2)),
        "volume_count": len(gmsh.model.getEntities(3)),
        "physical_groups": _physical_groups_payload(gmsh),
    }


def _remove_all_physical_groups(gmsh) -> list[dict[str, Any]]:
    groups = gmsh.model.getPhysicalGroups()
    if groups:
        remove_groups = getattr(gmsh.model, "removePhysicalGroups", None)
        if callable(remove_groups):
            remove_groups(groups)
    return _entity_dim_tags_payload(groups)


def _extract_overlap_surface_details(
    gmsh,
    error_text: str,
    logger_messages: Iterable[str],
) -> Dict[str, Any] | None:
    combined_messages = [str(error_text), *(str(message) for message in logger_messages)]
    surface_match = None
    for message in reversed(combined_messages):
        surface_match = OVERLAP_SURFACE_PATTERN.search(message)
        if surface_match is not None:
            break
    if surface_match is None:
        return None

    surface_tags = [int(surface_match.group(1)), int(surface_match.group(2))]
    facet_tags_from_logger: list[int] = []
    for message in combined_messages:
        facet_match = LOGGER_FACET_TAG_PATTERN.search(message)
        if facet_match is None:
            continue
        facet_tags_from_logger.append(int(facet_match.group(1)))

    intersection_kind = None
    lowered_messages = "\n".join(combined_messages).lower()
    if "exactly self-intersecting facets" in lowered_messages:
        intersection_kind = "exact"
    elif "nearly self-intersecting facets" in lowered_messages:
        intersection_kind = "near"

    surface_bboxes: list[Dict[str, Any]] = []
    for surface_tag in surface_tags:
        try:
            surface_bboxes.append(_entity_bbox_payload(gmsh, 2, surface_tag))
        except Exception:
            surface_bboxes.append({"dim": 2, "tag": int(surface_tag), "bbox": None})

    return {
        "surface_tags": surface_tags,
        "facet_tags_from_logger": facet_tags_from_logger,
        "self_intersection_kind": intersection_kind,
        "surface_bboxes": surface_bboxes,
    }


def _surface_bbox_area_proxy(bbox: Dict[str, float] | tuple[float, float, float, float, float, float] | None) -> float:
    if bbox is None:
        return float("inf")
    if isinstance(bbox, tuple):
        bbox = {
            "x_min": float(bbox[0]),
            "y_min": float(bbox[1]),
            "z_min": float(bbox[2]),
            "x_max": float(bbox[3]),
            "y_max": float(bbox[4]),
            "z_max": float(bbox[5]),
        }
    spans = sorted(
        [
            max(0.0, float(bbox["x_max"]) - float(bbox["x_min"])),
            max(0.0, float(bbox["y_max"]) - float(bbox["y_min"])),
            max(0.0, float(bbox["z_max"]) - float(bbox["z_min"])),
        ],
        reverse=True,
    )
    return spans[0] * spans[1]


def _ensure_positive_volume_mesh(mesh_stats: Dict[str, Any], *, context: str) -> None:
    if int(mesh_stats.get("volume_element_count", 0) or 0) > 0:
        return
    raise GmshBackendError(f"{context} returned without exception but did not generate any volume elements")


def _backend_failure_code(error_text: str) -> str:
    lowered = str(error_text).lower()
    if "plc error" in lowered:
        return "gmsh_plc_error"
    if "invalid boundary mesh" in lowered:
        return "gmsh_invalid_boundary_mesh"
    if "wrong topology of boundary mesh for parametrization" in lowered:
        return "gmsh_boundary_parametrization_topology"
    if "hxt 3d mesh failed" in lowered:
        return "gmsh_hxt_3d_failed"
    if "did not generate any volume elements" in lowered:
        return "gmsh_no_volume_elements"
    if "surface-only probe" in lowered:
        return "surface_mesh_only_probe"
    return "gmsh_backend_failed"


def _resolve_exact_overlap_surface_pair(gmsh, overlap_details: Dict[str, Any] | None) -> Dict[str, Any]:
    if not overlap_details:
        return {"status": "skipped", "reason": "missing_overlap_details"}
    if overlap_details.get("self_intersection_kind") != "exact":
        return {"status": "skipped", "reason": "overlap_not_exact"}

    surface_bboxes = overlap_details.get("surface_bboxes") or []
    if len(surface_bboxes) != 2:
        return {"status": "skipped", "reason": "expected_two_surface_bboxes"}

    ranked = sorted(
        surface_bboxes,
        key=lambda entry: (
            _surface_bbox_area_proxy(entry.get("bbox")),
            int(entry["tag"]),
        ),
    )
    removed_surface = ranked[0]
    kept_surface = ranked[1]

    gmsh.model.mesh.removeElements(2, int(removed_surface["tag"]), [])
    gmsh.model.mesh.reclassifyNodes()
    gmsh.model.mesh.removeDuplicateNodes()

    return {
        "status": "resolved",
        "removed_surface_tag": int(removed_surface["tag"]),
        "kept_surface_tag": int(kept_surface["tag"]),
        "removed_surface_area_proxy": _surface_bbox_area_proxy(removed_surface.get("bbox")),
        "kept_surface_area_proxy": _surface_bbox_area_proxy(kept_surface.get("bbox")),
    }


def _collect_plc_error_probe(
    gmsh,
    *,
    error_text: str,
    logger_messages: list[str],
    surface_mesh_path: Path | None,
    mesh_algorithm_3d: int,
) -> Dict[str, Any]:
    last_entity_error_dim_tags = _entity_dim_tags_payload(getattr(gmsh.model.mesh, "getLastEntityError", lambda: [])())
    last_node_error_tags = [int(tag) for tag in getattr(gmsh.model.mesh, "getLastNodeError", lambda: [])()]

    last_node_error_nodes: list[Dict[str, Any]] = []
    for node_tag in last_node_error_tags:
        try:
            coordinates, _, dim, entity_tag = gmsh.model.mesh.getNode(int(node_tag))
        except Exception:
            continue
        last_node_error_nodes.append(
            {
                "tag": int(node_tag),
                "coordinates": [float(coordinates[0]), float(coordinates[1]), float(coordinates[2])],
                "dim": int(dim),
                "entity_tag": int(entity_tag),
            }
        )

    intersection_points = [
        {"source": "logger", "coordinates": point}
        for point in _extract_logged_intersection_points(logger_messages)
    ]
    if not intersection_points:
        seen_node_points: set[tuple[float, float, float]] = set()
        for node in last_node_error_nodes:
            point = tuple(float(value) for value in node["coordinates"])
            if point in seen_node_points:
                continue
            seen_node_points.add(point)
            intersection_points.append({"source": "last_node_error", "coordinates": list(point)})

    point_hits: list[Dict[str, Any]] = []
    for point in intersection_points[:8]:
        radius = _probe_radius_for_point(point["coordinates"])
        x, y, z = point["coordinates"]
        try:
            dim_tags = gmsh.model.getEntitiesInBoundingBox(
                x - radius,
                y - radius,
                z - radius,
                x + radius,
                y + radius,
                z + radius,
                -1,
            )
        except Exception:
            continue
        point_hits.append(
            {
                "coordinates": [float(x), float(y), float(z)],
                "source": point["source"],
                "radius": float(radius),
                "entities": _entity_dim_tags_payload(dim_tags),
                "entity_bboxes": [
                    _entity_bbox_payload(gmsh, dim, tag)
                    for dim, tag in dim_tags[:12]
                ],
            }
        )

    return {
        "status": "captured",
        "error": error_text,
        "mesh_algorithm_3d": int(mesh_algorithm_3d),
        "surface_mesh_artifact": str(surface_mesh_path) if surface_mesh_path is not None else None,
        "logger_message_count": len(logger_messages),
        "logger_tail": [str(message) for message in logger_messages[-80:]],
        "intersection_points": intersection_points,
        "intersection_point_entity_hits": point_hits,
        "last_entity_error_dim_tags": last_entity_error_dim_tags,
        "last_entity_error_bboxes": [
            _entity_bbox_payload(gmsh, dim_tag["dim"], dim_tag["tag"])
            for dim_tag in last_entity_error_dim_tags[:12]
        ],
        "last_node_error_tags": last_node_error_tags,
        "last_node_error_nodes": last_node_error_nodes,
    }


def _run_3d_algorithm_probe(
    gmsh,
    *,
    aircraft_surface_tags: list[int] | None,
    fluid_volume_tags: list[int],
    algorithm3d: int,
    logger_checkpoint: int,
    surface_mesh_path: Path | None,
) -> Dict[str, Any]:
    try:
        gmsh.model.mesh.clear()
    except Exception as exc:
        return {
            "status": "failed_to_prepare",
            "mesh_algorithm_3d": int(algorithm3d),
            "error": f"failed to clear previous mesh state: {exc}",
        }

    surface_probe: Dict[str, Any] = {}
    try:
        gmsh.model.mesh.generate(2)
        if aircraft_surface_tags:
            pre_cleanup_duplicates = _scan_duplicate_surface_facets(gmsh, aircraft_surface_tags)
            duplicate_cleanup = _remove_duplicate_surface_facets(gmsh, aircraft_surface_tags)
            post_cleanup_duplicates = _scan_duplicate_surface_facets(gmsh, aircraft_surface_tags)
            surface_probe = {
                "duplicate_facets_before_cleanup": pre_cleanup_duplicates,
                "duplicate_facets_after_cleanup": post_cleanup_duplicates,
                "cleanup_actions": duplicate_cleanup,
            }
    except Exception as exc:
        logger_messages = [str(message) for message in gmsh.logger.get()[logger_checkpoint:]]
        return {
            "status": "failed_surface_remesh",
            "mesh_algorithm_3d": int(algorithm3d),
            "error": str(exc),
            "probe": _collect_plc_error_probe(
                gmsh,
                error_text=str(exc),
                logger_messages=logger_messages,
                surface_mesh_path=surface_mesh_path,
                mesh_algorithm_3d=algorithm3d,
            ),
        }

    gmsh.option.setNumber("Mesh.Algorithm3D", float(algorithm3d))
    try:
        gmsh.model.mesh.generate(3)
    except Exception as exc:
        logger_messages = [str(message) for message in gmsh.logger.get()[logger_checkpoint:]]
        return {
            "status": "failed",
            "mesh_algorithm_3d": int(algorithm3d),
            "probe": _collect_plc_error_probe(
                gmsh,
                error_text=str(exc),
                logger_messages=logger_messages,
                surface_mesh_path=surface_mesh_path,
                mesh_algorithm_3d=algorithm3d,
            ),
        }

    mesh_stats = _mesh_stats(gmsh)
    try:
        _ensure_positive_volume_mesh(mesh_stats, context="3D probe")
    except GmshBackendError as exc:
        logger_messages = [str(message) for message in gmsh.logger.get()[logger_checkpoint:]]
        return {
            "status": "failed_no_volume_elements",
            "mesh_algorithm_3d": int(algorithm3d),
            "error": str(exc),
            "mesh_stats": mesh_stats,
            "surface_probe": surface_probe,
            "logger_tail": logger_messages[-80:],
        }

    return {
        "status": "success",
        "mesh_algorithm_3d": int(algorithm3d),
        "mesh_stats": mesh_stats,
        "surface_probe": surface_probe,
    }


def _run_surface_repair_fallback(
    *,
    surface_mesh_path: Path,
    bounds: dict[str, float],
    mesh_path: Path,
    cleanup_report_path: Path,
    discrete_reparam_report_path: Path,
    retry_metadata_path: Path,
    mesh_algorithm_2d: int,
    mesh_algorithm_3d: int,
    wall_marker_name: str = "aircraft",
    thread_count: int = 4,
) -> Dict[str, Any]:
    gmsh = load_gmsh()
    cleanup_report: Dict[str, Any] = {
        "status": "started",
        "surface_mesh_artifact": str(surface_mesh_path),
        "mesh_algorithm_2d": int(mesh_algorithm_2d),
        "mesh_algorithm_3d": int(mesh_algorithm_3d),
    }
    discrete_report: Dict[str, Any] = {
        "status": "started",
        "surface_mesh_artifact": str(surface_mesh_path),
        "classify_angle_degrees": float(SURFACE_REPAIR_CLASSIFY_ANGLE_DEGREES),
        "mesh_algorithm_2d": int(mesh_algorithm_2d),
        "mesh_algorithm_3d": int(mesh_algorithm_3d),
    }
    retry_metadata: Dict[str, Any] = {
        "status": "started",
        "route_stage": "surface_repair_fallback",
        "surface_mesh_artifact": str(surface_mesh_path),
        "mesh_artifact": str(mesh_path),
        "mesh_algorithm_2d": int(mesh_algorithm_2d),
        "mesh_algorithm_3d": int(mesh_algorithm_3d),
        "cleanup_report_artifact": str(cleanup_report_path),
        "discrete_reparam_report_artifact": str(discrete_reparam_report_path),
    }

    gmsh_initialized = False
    gmsh_logger_started = False
    try:
        gmsh.initialize()
        gmsh_initialized = True
        _configure_gmsh_runtime_options(gmsh, thread_count=thread_count)
        gmsh.option.setNumber("Mesh.Algorithm", float(mesh_algorithm_2d))
        gmsh.option.setNumber("Mesh.Algorithm3D", float(mesh_algorithm_3d))
        gmsh.option.setNumber("Mesh.MeshOnlyEmpty", 1)
        gmsh.logger.start()
        gmsh_logger_started = True

        gmsh.open(str(surface_mesh_path))
        cleanup_report["pre_cleanup"] = _entity_counts_snapshot(gmsh)
        node_count_before = len(gmsh.model.mesh.getNodes()[0])
        cleanup_report["node_count_before"] = node_count_before
        gmsh.model.mesh.removeDuplicateNodes()
        node_count_after = len(gmsh.model.mesh.getNodes()[0])
        cleanup_report["node_count_after"] = node_count_after
        cleanup_report["duplicate_nodes_removed"] = max(0, node_count_before - node_count_after)
        try:
            gmsh.model.mesh.removeDuplicateElements([])
        except TypeError:
            gmsh.model.mesh.removeDuplicateElements()
        cleanup_report["remove_duplicate_elements_called"] = True
        cleanup_report["post_cleanup"] = _entity_counts_snapshot(gmsh)
        cleanup_report["status"] = "completed"
        _json_write(cleanup_report_path, cleanup_report)

        discrete_report["pre_classify"] = _entity_counts_snapshot(gmsh)
        classify_angle = SURFACE_REPAIR_CLASSIFY_ANGLE_DEGREES * math.pi / 180.0
        gmsh.model.mesh.classifySurfaces(
            classify_angle,
            True,
            True,
            math.pi,
            True,
        )
        discrete_report["post_classify"] = _entity_counts_snapshot(gmsh)
        gmsh.model.mesh.createGeometry()
        discrete_report["post_create_geometry"] = _entity_counts_snapshot(gmsh)
        gmsh.model.mesh.createTopology(True, False)
        discrete_report["post_create_topology"] = _entity_counts_snapshot(gmsh)

        fluid_volume_tags = [int(tag) for dim, tag in gmsh.model.getEntities(3) if dim == 3]
        if not fluid_volume_tags:
            raise GmshBackendError("surface-repair fallback did not recover any fluid volume.")

        boundary_surface_tags = _boundary_surface_tags(gmsh, [(3, tag) for tag in fluid_volume_tags])
        aircraft_surface_tags, farfield_surface_tags = _classify_outer_boundary_surfaces(
            gmsh,
            boundary_surface_tags,
            bounds,
        )
        if not aircraft_surface_tags:
            raise GmshBackendError("surface-repair fallback did not recover aircraft boundary surfaces.")
        if not farfield_surface_tags:
            raise GmshBackendError("surface-repair fallback did not recover farfield boundary surfaces.")

        discrete_report["boundary_surface_count"] = len(boundary_surface_tags)
        discrete_report["aircraft_surface_count"] = len(aircraft_surface_tags)
        discrete_report["farfield_surface_count"] = len(farfield_surface_tags)
        discrete_report["removed_physical_groups"] = _remove_all_physical_groups(gmsh)

        fluid_group = gmsh.model.addPhysicalGroup(3, fluid_volume_tags)
        gmsh.model.setPhysicalName(3, fluid_group, "fluid")
        aircraft_group = gmsh.model.addPhysicalGroup(2, aircraft_surface_tags)
        gmsh.model.setPhysicalName(2, aircraft_group, wall_marker_name)
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
        gmsh.model.setPhysicalName(2, farfield_group, "farfield")

        discrete_report["post_group_rebuild"] = _entity_counts_snapshot(gmsh)
        discrete_report["status"] = "completed"
        _json_write(discrete_reparam_report_path, discrete_report)

        overlap_resolution = None
        try:
            gmsh.model.mesh.generate(3)
        except Exception as exc:
            logger_messages = [str(message) for message in gmsh.logger.get()]
            overlap_details = _extract_overlap_surface_details(gmsh, str(exc), logger_messages)
            overlap_resolution = _resolve_exact_overlap_surface_pair(gmsh, overlap_details)
            if overlap_resolution.get("status") != "resolved":
                raise
            try:
                gmsh.model.mesh.clear([(3, int(tag)) for tag in fluid_volume_tags])
            except Exception:
                pass

            removed_surface_tag = int(overlap_resolution["removed_surface_tag"])
            aircraft_surface_tags = [tag for tag in aircraft_surface_tags if int(tag) != removed_surface_tag]
            farfield_surface_tags = [tag for tag in farfield_surface_tags if int(tag) != removed_surface_tag]
            discrete_report["overlap_resolution"] = overlap_resolution
            discrete_report["aircraft_surface_count_after_overlap_resolution"] = len(aircraft_surface_tags)
            discrete_report["farfield_surface_count_after_overlap_resolution"] = len(farfield_surface_tags)
            discrete_report["removed_physical_groups_after_overlap_resolution"] = _remove_all_physical_groups(gmsh)

            fluid_group = gmsh.model.addPhysicalGroup(3, fluid_volume_tags)
            gmsh.model.setPhysicalName(3, fluid_group, "fluid")
            aircraft_group = gmsh.model.addPhysicalGroup(2, aircraft_surface_tags)
            gmsh.model.setPhysicalName(2, aircraft_group, wall_marker_name)
            farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
            gmsh.model.setPhysicalName(2, farfield_group, "farfield")

            gmsh.model.mesh.generate(3)
        gmsh.write(str(mesh_path))

        mesh_stats = {
            "mesh_dim": 3,
            **_mesh_stats(gmsh),
        }
        physical_groups = {
            "fluid": _physical_group_summary(gmsh, 3, fluid_group),
            wall_marker_name: _physical_group_summary(gmsh, 2, aircraft_group),
            "farfield": _physical_group_summary(gmsh, 2, farfield_group),
        }
        marker_summary = {
            wall_marker_name: physical_groups[wall_marker_name],
            "farfield": physical_groups["farfield"],
        }
        retry_metadata.update(
            {
                "marker_summary": marker_summary,
                "physical_groups": physical_groups,
                "mesh": {
                    "format": "msh",
                    "mesh_dim": 3,
                    **mesh_stats,
                },
            }
        )
        if overlap_resolution is not None:
            retry_metadata["overlap_resolution"] = overlap_resolution
        _ensure_positive_volume_mesh(mesh_stats, context="surface-repair fallback")
        retry_metadata["status"] = "success"
        _json_write(retry_metadata_path, retry_metadata)
        return {
            "status": "success",
            "route_stage": "surface_repair_fallback",
            "marker_summary": marker_summary,
            "physical_groups": physical_groups,
            "mesh_stats": mesh_stats,
            "cleanup_report_path": cleanup_report_path,
            "discrete_reparam_report_path": discrete_reparam_report_path,
            "retry_metadata_path": retry_metadata_path,
            "notes": [
                "fresh-session surface mesh cleanup and discrete reparametrization completed",
                "boundary groups rebuilt from discrete fallback volume boundary",
                *(
                    [f"resolved_exact_overlap_surface_pair:removed_surface={overlap_resolution['removed_surface_tag']}"]
                    if overlap_resolution is not None
                    else []
                ),
            ],
        }
    except Exception as exc:
        logger_messages = [str(message) for message in gmsh.logger.get()] if gmsh_logger_started else []
        overlap_details = _extract_overlap_surface_details(gmsh, str(exc), logger_messages)
        if cleanup_report.get("status") == "started":
            cleanup_report["status"] = "failed"
            cleanup_report["error"] = str(exc)
            _json_write(cleanup_report_path, cleanup_report)
        discrete_report["status"] = "failed"
        discrete_report["error"] = str(exc)
        if overlap_details is not None:
            discrete_report["overlap_surface_pair"] = overlap_details
        if logger_messages:
            discrete_report["logger_tail"] = logger_messages[-80:]
        _json_write(discrete_reparam_report_path, discrete_report)

        plc_probe = None
        if gmsh_initialized:
            try:
                plc_probe = _collect_plc_error_probe(
                    gmsh,
                    error_text=str(exc),
                    logger_messages=logger_messages,
                    surface_mesh_path=surface_mesh_path,
                    mesh_algorithm_3d=int(mesh_algorithm_3d),
                )
            except Exception:
                plc_probe = None
        retry_metadata.update(
            {
                "status": "failed",
                "error": str(exc),
                "plc_probe": plc_probe,
            }
        )
        if overlap_details is not None:
            retry_metadata["overlap_surface_pair"] = overlap_details
        _json_write(retry_metadata_path, retry_metadata)
        return {
            "status": "failed",
            "route_stage": "surface_repair_fallback",
            "error": str(exc),
            "marker_summary": {},
            "physical_groups": {},
            "mesh_stats": {},
            "cleanup_report_path": cleanup_report_path,
            "discrete_reparam_report_path": discrete_reparam_report_path,
            "retry_metadata_path": retry_metadata_path,
            "notes": [
                "fresh-session surface mesh cleanup and discrete reparametrization failed",
            ],
        }
    finally:
        if gmsh_initialized:
            if gmsh_logger_started:
                try:
                    gmsh.logger.stop()
                except Exception:
                    pass
            gmsh.finalize()


def _probe_discrete_classify_angles(
    *,
    surface_mesh_path: Path,
    probe_path: Path,
    angle_degrees: list[float],
    mesh_algorithm_2d: int,
    mesh_algorithm_3d: int,
    thread_count: int = 4,
) -> Dict[str, Any]:
    gmsh = load_gmsh()
    results: list[Dict[str, Any]] = []
    for angle_deg in angle_degrees:
        gmsh.initialize()
        logger_started = False
        try:
            _configure_gmsh_runtime_options(gmsh, thread_count=thread_count)
            gmsh.option.setNumber("Mesh.Algorithm", float(mesh_algorithm_2d))
            gmsh.option.setNumber("Mesh.Algorithm3D", float(mesh_algorithm_3d))
            gmsh.option.setNumber("Mesh.MeshOnlyEmpty", 1)
            gmsh.logger.start()
            logger_started = True

            gmsh.open(str(surface_mesh_path))
            gmsh.model.mesh.removeDuplicateNodes()
            try:
                gmsh.model.mesh.removeDuplicateElements([])
            except TypeError:
                gmsh.model.mesh.removeDuplicateElements()

            gmsh.model.mesh.classifySurfaces(
                float(angle_deg) * math.pi / 180.0,
                True,
                True,
                math.pi,
                True,
            )
            counts = {
                "surfaces_after_classify": len(gmsh.model.getEntities(2)),
                "curves_after_classify": len(gmsh.model.getEntities(1)),
            }
            try:
                gmsh.model.mesh.createGeometry()
                gmsh.model.mesh.createTopology(True, False)
                gmsh.model.mesh.generate(3)
                node_tags, _, _ = gmsh.model.mesh.getNodes()
                _, volume_element_tags, _ = gmsh.model.mesh.getElements(3)
                results.append(
                    {
                        "angle_deg": float(angle_deg),
                        "status": "success",
                        **counts,
                        "node_count": len(node_tags),
                        "volume_element_count": sum(len(tags) for tags in volume_element_tags),
                    }
                )
            except Exception as exc:
                logger_messages = [str(message) for message in gmsh.logger.get()]
                results.append(
                    {
                        "angle_deg": float(angle_deg),
                        "status": "failed",
                        **counts,
                        "error": str(exc),
                        "logger_tail": logger_messages[-40:],
                        "overlap_surface_pair": _extract_overlap_surface_details(gmsh, str(exc), logger_messages),
                    }
                )
        finally:
            if logger_started:
                try:
                    gmsh.logger.stop()
                except Exception:
                    pass
            gmsh.finalize()

    payload = {
        "status": "completed",
        "surface_mesh_artifact": str(surface_mesh_path),
        "mesh_algorithm_2d": int(mesh_algorithm_2d),
        "mesh_algorithm_3d": int(mesh_algorithm_3d),
        "results": results,
    }
    _json_write(probe_path, payload)
    return payload


def _placeholder_backend_result(
    recipe: MeshRecipe,
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    capability_supported = recipe.backend_capability in SUPPORTED_GMSH_CAPABILITIES
    return {
        "status": "success" if capability_supported else "failed",
        "backend": recipe.backend,
        "backend_capability": recipe.backend_capability,
        "meshing_route": recipe.meshing_route,
        "geometry_family": recipe.geometry_family,
        "geometry_source": recipe.geometry_source,
        "route_stage": "placeholder",
        "artifacts": {},
        "marker_summary": {},
        "mesh_stats": {},
        "notes": [
            (
                "Real OCC backend currently implemented for gmsh_thin_sheet_aircraft_assembly, "
                "gmsh_thin_sheet_surface, and gmsh_closed_solid_volume."
            ),
            f"loader={handle.loader}",
            f"mesh_dim={config.mesh_dim}",
        ],
    }


def _apply_occ_external_flow_route(
    recipe: MeshRecipe,
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    mesh_dir = config.out_dir / "artifacts" / "mesh"
    mesh_path = mesh_dir / "mesh.msh"
    metadata_path = mesh_dir / "mesh_metadata.json"
    marker_summary_path = mesh_dir / "marker_summary.json"
    surface_mesh_path = mesh_dir / "surface_mesh_2d.msh"
    surface_patch_diagnostics_path = mesh_dir / "surface_patch_diagnostics.json"
    brep_hotspot_report_path = mesh_dir / "brep_hotspot_report.json"
    hotspot_patch_report_path = mesh_dir / "hotspot_patch_report.json"
    sliver_cluster_report_path = mesh_dir / "sliver_cluster_report.json"
    compound_report_path = mesh_dir / "compound_report.json"
    gmsh_log_path = mesh_dir / "gmsh_log.txt"
    mesh2d_watchdog_path = mesh_dir / "mesh2d_watchdog.json"
    mesh2d_watchdog_sample_path = mesh_dir / "mesh2d_watchdog_sample.txt"
    mesh3d_watchdog_path = mesh_dir / "mesh3d_watchdog.json"
    mesh3d_watchdog_sample_path = mesh_dir / "mesh3d_watchdog_sample.txt"
    plc_probe_path = mesh_dir / "plc_probe.json"
    surface_cleanup_report_path = mesh_dir / "surface_cleanup_report.json"
    discrete_reparam_report_path = mesh_dir / "discrete_reparam_report.json"
    retry_mesh_metadata_path = mesh_dir / "retry_mesh_metadata.json"
    classify_angle_probe_path = mesh_dir / "classify_angle_probe.json"
    if config.boundary_layer.enabled:
        return {
            "status": "failed",
            "backend": recipe.backend,
            "backend_capability": recipe.backend_capability,
            "meshing_route": recipe.meshing_route,
            "geometry_family": recipe.geometry_family,
            "geometry_source": recipe.geometry_source,
            "route_stage": "baseline",
            "artifacts": {
                "mesh": str(mesh_path),
                "mesh_metadata": str(metadata_path),
                "marker_summary": str(marker_summary_path),
                "surface_mesh_2d": str(surface_mesh_path),
                "surface_patch_diagnostics": str(surface_patch_diagnostics_path),
                "brep_hotspot_report": str(brep_hotspot_report_path),
                "hotspot_patch_report": str(hotspot_patch_report_path),
                "compound_report": str(compound_report_path),
                "gmsh_log": str(gmsh_log_path),
                "mesh2d_watchdog": str(mesh2d_watchdog_path),
                "mesh2d_watchdog_sample": str(mesh2d_watchdog_sample_path),
                "mesh3d_watchdog": str(mesh3d_watchdog_path),
                "mesh3d_watchdog_sample": str(mesh3d_watchdog_sample_path),
                "plc_probe": str(plc_probe_path),
                "surface_cleanup_report": str(surface_cleanup_report_path),
                "discrete_reparam_report": str(discrete_reparam_report_path),
                "retry_mesh_metadata": str(retry_mesh_metadata_path),
                "classify_angle_probe": str(classify_angle_probe_path),
            },
            "marker_summary": {},
            "mesh_stats": {},
            "error": (
                "3D boundary layer / prism layers are not implemented for the current OCC tetra route; "
                "boundary_layer.enabled requires a dedicated prism route"
            ),
            "notes": [
                "baseline OCC external-flow mesh failed before meshing",
                f"loader={handle.loader}",
                f"mesh_dim={config.mesh_dim}",
            ],
        }
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        raise GmshBackendError(str(exc)) from exc
    mesh_dir.mkdir(parents=True, exist_ok=True)

    gmsh_initialized = False
    gmsh_logger_started = False
    metadata: Dict[str, Any] = {
        "status": "started",
        "route_stage": "baseline",
        "backend": recipe.backend,
        "backend_capability": recipe.backend_capability,
        "meshing_route": recipe.meshing_route,
        "geometry_family": recipe.geometry_family,
        "geometry_source": recipe.geometry_source,
        "geometry": {
            "source_path": str(handle.source_path),
            "normalized_path": str(handle.path),
            "loader": handle.loader,
            "provider": handle.provider,
            "provider_status": handle.provider_status,
            "provider_topology": (
                handle.provider_result.topology.model_dump(mode="json")
                if handle.provider_result is not None
                else None
            ),
        },
    }
    marker_summary: Dict[str, Any] = {}
    physical_groups: Dict[str, Any] = {}
    field_info: Dict[str, Any] = {}
    body_bounds_dict: Dict[str, Any] | None = None
    bounds: Dict[str, float] | None = None
    unit_normalization: Dict[str, Any] | None = None
    mesh_stats: Dict[str, Any] = {}
    surface_patch_diagnostics: Dict[str, Any] | None = None
    brep_hotspot_report: Dict[str, Any] | None = None
    compound_policy: Dict[str, Any] | None = None
    compound_report: Dict[str, Any] | None = None
    mesh2d_watchdog: Dict[str, Any] | None = None
    mesh3d_watchdog: Dict[str, Any] | None = None
    plc_probe: Dict[str, Any] | None = None
    surface_repair_result: Dict[str, Any] | None = None
    try:
        gmsh.initialize()
        gmsh_initialized = True
        _configure_gmsh_runtime_options(gmsh, thread_count=config.gmsh_threads)
        gmsh.model.add(f"hpa_meshing_{uuid.uuid4().hex}")
        gmsh.logger.start()
        gmsh_logger_started = True

        imported_entities = gmsh.model.occ.importShapes(str(handle.path))
        gmsh.model.occ.synchronize()
        body_dim_tags = [entity for entity in imported_entities if entity[0] == 3]
        if not body_dim_tags:
            body_dim_tags = gmsh.model.getEntities(3)
        if not body_dim_tags:
            raise GmshBackendError(
                f"normalized STEP did not import any OCC volumes for {recipe.meshing_route}."
            )
        imported_surface_count = len(gmsh.model.getEntities(2))
        imported_body_bounds = _bbox_for_entities(gmsh, body_dim_tags)
        import_scale, output_units = _import_scale_to_units(handle)
        backend_rescale_applied = abs(import_scale - 1.0) > 1e-9
        if backend_rescale_applied:
            gmsh.model.occ.dilate(imported_entities or body_dim_tags, 0.0, 0.0, 0.0, import_scale, import_scale, import_scale)
            gmsh.model.occ.synchronize()
            body_dim_tags = gmsh.model.getEntities(3)
            imported_surface_count = len(gmsh.model.getEntities(2))

        body_dim_tags, healing_summary = _maybe_heal_imported_bodies(
            gmsh,
            body_dim_tags,
            skip_heal=_should_skip_occ_heal(handle),
        )
        imported_surface_count = len(gmsh.model.getEntities(2))
        metadata["body"] = {
            "imported_volume_count": len(body_dim_tags),
            "imported_surface_count": imported_surface_count,
            "healing": healing_summary,
        }

        body_bounds = _bbox_for_entities(gmsh, body_dim_tags)
        bounds = _farfield_bounds(*body_bounds, farfield=config.farfield)
        box_tag = gmsh.model.occ.addBox(
            bounds["x_min"],
            bounds["y_min"],
            bounds["z_min"],
            bounds["x_max"] - bounds["x_min"],
            bounds["y_max"] - bounds["y_min"],
            bounds["z_max"] - bounds["z_min"],
        )
        fluid_entities, _ = gmsh.model.occ.cut(
            [(3, box_tag)],
            body_dim_tags,
            removeObject=True,
            removeTool=True,
        )
        gmsh.model.occ.synchronize()

        fluid_volume_tags = [int(tag) for dim, tag in fluid_entities if dim == 3]
        if not fluid_volume_tags:
            raise GmshBackendError("OCC farfield cut did not leave any fluid volumes.")

        boundary_surface_tags = _boundary_surface_tags(gmsh, [(3, tag) for tag in fluid_volume_tags])
        aircraft_surface_tags, farfield_surface_tags = _classify_outer_boundary_surfaces(
            gmsh,
            boundary_surface_tags,
            bounds,
        )
        if not aircraft_surface_tags:
            raise GmshBackendError("Failed to recover aircraft boundary surfaces from fluid boundary.")
        if not farfield_surface_tags:
            raise GmshBackendError("Failed to recover farfield boundary surfaces from fluid boundary.")
        metadata["surface_topology"] = {
            "boundary_surface_count": len(boundary_surface_tags),
            "aircraft_surface_count": len(aircraft_surface_tags),
            "farfield_surface_count": len(farfield_surface_tags),
            "aircraft_connectivity_before_meshing": _surface_connectivity_summary(gmsh, aircraft_surface_tags),
        }

        aircraft_curve_tags = _aircraft_curve_tags(gmsh, aircraft_surface_tags)
        reference_length = _resolve_sizing_reference_length(
            handle,
            config,
            fallback_body_bounds=body_bounds if recipe.geometry_family == "closed_solid" else None,
        )
        resolved_field_defaults = _resolve_mesh_field_defaults(reference_length, config)
        surface_patch_diagnostics = _collect_surface_patch_diagnostics(
            gmsh,
            surface_tags=aircraft_surface_tags,
            reference_length=reference_length,
            near_body_size=float(resolved_field_defaults["near_body_size"]),
        )

        wall_marker_name = _wall_marker_name_for_recipe(recipe)

        fluid_group = gmsh.model.addPhysicalGroup(3, fluid_volume_tags)
        gmsh.model.setPhysicalName(3, fluid_group, "fluid")
        aircraft_group = gmsh.model.addPhysicalGroup(2, aircraft_surface_tags)
        gmsh.model.setPhysicalName(2, aircraft_group, wall_marker_name)
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
        gmsh.model.setPhysicalName(2, farfield_group, "farfield")

        field_info = _configure_mesh_field(
            gmsh,
            aircraft_surface_tags,
            aircraft_curve_tags,
            reference_length,
            config,
            farfield_surface_tags=farfield_surface_tags,
            surface_patch_diagnostics=surface_patch_diagnostics,
            resolved_field_defaults=resolved_field_defaults,
        )
        metadata["mesh_field"] = field_info
        _json_write(surface_patch_diagnostics_path, surface_patch_diagnostics)
        metadata["surface_patch_diagnostics"] = {
            "artifact": str(surface_patch_diagnostics_path),
            "surface_count": int(surface_patch_diagnostics["surface_count"]),
            "curve_count": int(surface_patch_diagnostics["curve_count"]),
            "suspicious_surface_tags": [int(entry["tag"]) for entry in surface_patch_diagnostics["suspicious_surfaces"][:12]],
            "shortest_curve_tags": [int(entry["tag"]) for entry in surface_patch_diagnostics["shortest_curves"][:20]],
            "family_hint_counts": surface_patch_diagnostics["family_hint_counts"],
        }
        brep_hotspot_report = _collect_brep_hotspot_report(
            step_path=handle.path,
            surface_patch_diagnostics=surface_patch_diagnostics,
            requested_surface_tags=config.metadata.get("mesh_brep_hotspot_surface_tags"),
            requested_curve_tags=config.metadata.get("mesh_brep_hotspot_curve_tags"),
            scale_to_output_units=import_scale,
            output_units=output_units or config.units,
        )
        if brep_hotspot_report.get("status") != "disabled":
            _json_write(brep_hotspot_report_path, brep_hotspot_report)
            metadata["brep_hotspot_report"] = {
                "artifact": str(brep_hotspot_report_path),
                "status": brep_hotspot_report.get("status"),
                "selected_surface_tags": brep_hotspot_report.get("selected_surface_tags", []),
                "selected_curve_tags": brep_hotspot_report.get("selected_curve_tags", []),
                "shape_valid_default": brep_hotspot_report.get("shape_valid_default"),
                "shape_valid_exact": brep_hotspot_report.get("shape_valid_exact"),
            }
        compound_policy = _resolve_compound_meshing_policy(config)
        compound_result = _apply_compound_meshing_policy(gmsh, policy=compound_policy)
        compound_report = {
            "status": str(compound_result.get("status", "disabled")),
            "compound_policy": compound_policy,
            "compound_result": compound_result,
        }
        if compound_policy.get("enabled"):
            metadata["compound_policy"] = {
                "artifact": str(compound_report_path),
                "name": compound_policy.get("name"),
                "compound_surface_groups": compound_policy.get("compound_surfaces", []),
                "compound_curve_groups": compound_policy.get("compound_curves", []),
                "compound_classify": compound_policy.get("compound_classify"),
                "compound_mesh_size_factor": compound_policy.get("compound_mesh_size_factor"),
            }
        watchdog_surface_lookup = {
            int(record["tag"]): record
            for record in surface_patch_diagnostics["surface_records"]
        }
        for farfield_surface_tag in farfield_surface_tags:
            if int(farfield_surface_tag) in watchdog_surface_lookup:
                continue
            watchdog_surface_lookup[int(farfield_surface_tag)] = {
                "tag": int(farfield_surface_tag),
                "surface_role": "farfield",
                "area": _safe_occ_mass(gmsh, 2, int(farfield_surface_tag)),
                "bbox": _entity_bbox_payload(gmsh, 2, int(farfield_surface_tag))["bbox"],
                "family_hints": ["farfield_boundary"],
            }
        mesh2d_watchdog = _run_mesh2d_with_watchdog(
            gmsh,
            watchdog_path=mesh2d_watchdog_path,
            sample_path=mesh2d_watchdog_sample_path,
            timeout_seconds=float(
                config.metadata.get("mesh2d_watchdog_timeout_sec", DEFAULT_MESH2D_WATCHDOG_TIMEOUT_SECONDS)
            ),
            sample_seconds=int(
                config.metadata.get("mesh2d_watchdog_sample_seconds", DEFAULT_MESH2D_WATCHDOG_SAMPLE_SECONDS)
            ),
            surface_patch_lookup=watchdog_surface_lookup,
            curve_patch_lookup={
                int(record["tag"]): record
                for record in surface_patch_diagnostics["curve_records"]
            },
        )
        metadata["mesh2d_watchdog"] = {
            "artifact": str(mesh2d_watchdog_path),
            "sample_artifact": str(mesh2d_watchdog_sample_path),
            "status": mesh2d_watchdog["status"],
            "timeout_seconds": mesh2d_watchdog["timeout_seconds"],
            "triggered_at_elapsed_sec": mesh2d_watchdog.get("triggered_at_elapsed_sec"),
            "completed_elapsed_sec": mesh2d_watchdog.get("completed_elapsed_sec"),
            "meshing_stage_at_timeout": mesh2d_watchdog.get("meshing_stage_at_timeout"),
            "last_meshing_curve_tag": mesh2d_watchdog.get("last_meshing_curve_tag"),
            "last_meshing_surface_tag": mesh2d_watchdog.get("last_meshing_surface_tag"),
        }
        if compound_report is not None:
            compound_report["status"] = "generate2_returned"
            compound_report["compound_result"]["2d_returned"] = True
            compound_report["compound_result"]["reparam_success"] = True
            _refresh_compound_meshing_result(
                gmsh,
                compound_result=compound_report["compound_result"],
                aircraft_group=aircraft_group,
                farfield_group=farfield_group,
            )
        pre_cleanup_duplicates = _scan_duplicate_surface_facets(gmsh, aircraft_surface_tags)
        duplicate_cleanup = _remove_duplicate_surface_facets(gmsh, aircraft_surface_tags)
        post_cleanup_duplicates = _scan_duplicate_surface_facets(gmsh, aircraft_surface_tags)
        surface_element_count, surface_element_type_counts = _count_elements_for_entities(
            gmsh,
            2,
            aircraft_surface_tags,
        )
        metadata["surface_mesh"] = {
            "aircraft_surface_element_count": surface_element_count,
            "aircraft_surface_element_type_counts": surface_element_type_counts,
            "duplicate_facets_before_cleanup": pre_cleanup_duplicates,
            "duplicate_facets_after_cleanup": post_cleanup_duplicates,
            "cleanup_actions": duplicate_cleanup,
            "mesh2d_watchdog_status": mesh2d_watchdog.get("status") if mesh2d_watchdog is not None else None,
            "last_meshing_surface_tag_from_watchdog": (
                mesh2d_watchdog.get("last_meshing_surface_tag")
                if mesh2d_watchdog is not None
                else None
            ),
            "artifact": str(surface_mesh_path),
        }
        gmsh.write(str(surface_mesh_path))
        mesh_stats = {
            "mesh_dim": int(config.mesh_dim),
            **_mesh_stats(gmsh),
        }
        body_bounds_dict = _bounds_dict(*body_bounds)
        unit_normalization = {
            "units": output_units or config.units,
            "backend_rescale_applied": backend_rescale_applied,
            "import_scale_to_units": import_scale,
            "imported_body_bounds": _bounds_dict(*imported_body_bounds),
            "provider_topology_bounds": (
                handle.provider_result.topology.bounds.model_dump(mode="json")
                if handle.provider_result is not None and handle.provider_result.topology.bounds is not None
                else None
            ),
        }
        physical_groups = {
            "fluid": _physical_group_summary(gmsh, 3, fluid_group),
            wall_marker_name: _physical_group_summary(gmsh, 2, aircraft_group),
            "farfield": _physical_group_summary(gmsh, 2, farfield_group),
        }
        marker_summary = {
            name: physical_groups[name]
            for name in (wall_marker_name, "farfield")
        }
        volume_smoke_decoupled = None
        if config.mesh_dim == 3:
            volume_smoke_decoupled = _configure_volume_smoke_decoupled_field(
                gmsh,
                aircraft_surface_tags=aircraft_surface_tags,
                near_body_size=float(field_info.get("near_body_size", 0.0)),
                mesh_algorithm_3d=int(field_info.get("mesh_algorithm_3d", 1)),
                bounds=bounds,
                surface_patch_diagnostics=surface_patch_diagnostics,
                config=config,
            )
            if volume_smoke_decoupled.get("enabled"):
                field_info["volume_smoke_decoupled"] = volume_smoke_decoupled
        metadata["volume_meshing"] = {
            "requested": bool(config.mesh_dim == 3),
            "attempted": False,
            "completed": False,
            "mesh_dim_requested": int(config.mesh_dim),
            "mesh_algorithm_3d": int(field_info.get("mesh_algorithm_3d", 1)),
            "optimization": {
                **(field_info.get("volume_optimization", {}) if isinstance(field_info, dict) else {}),
                "post_runs": [],
            },
            "field_architecture": (
                volume_smoke_decoupled.get("field_architecture")
                if isinstance(volume_smoke_decoupled, dict) and volume_smoke_decoupled.get("enabled")
                else None
            ),
            "tip_quality_buffer_policy": (
                volume_smoke_decoupled.get("tip_quality_buffer_policy")
                if isinstance(volume_smoke_decoupled, dict) and volume_smoke_decoupled.get("enabled")
                else None
            ),
            "sliver_volume_pocket_policy": (
                volume_smoke_decoupled.get("sliver_volume_pocket_policy")
                if isinstance(volume_smoke_decoupled, dict) and volume_smoke_decoupled.get("enabled")
                else None
            ),
            "pre_generate3_mesh_stats": {
                "mesh_dim": int(mesh_stats.get("mesh_dim", 0) or 0),
                "node_count": int(mesh_stats.get("node_count", 0) or 0),
                "element_count": int(mesh_stats.get("element_count", 0) or 0),
                "surface_element_count": int(mesh_stats.get("surface_element_count", 0) or 0),
                "volume_element_count": int(mesh_stats.get("volume_element_count", 0) or 0),
            },
        }

        if config.mesh_dim != 3:
            if compound_report is not None:
                compound_report["status"] = "surface_only_probe"
                compound_report["compound_result"]["3d_returned"] = False
                _json_write(compound_report_path, compound_report)
                metadata["compound_result"] = {
                    "artifact": str(compound_report_path),
                    **compound_report["compound_result"],
                }
            gmsh.write(str(mesh_path))
            metadata["status"] = "surface_mesh_only"
            metadata["route_stage"] = "surface_mesh_only"
            metadata["failure_code"] = "surface_mesh_only_probe"
            metadata["error"] = (
                "surface-only probe completed without volume meshing; "
                "config.mesh_dim=2 skipped generate(3)"
            )
            metadata["physical_groups"] = physical_groups
            metadata["marker_summary"] = marker_summary
            metadata["mesh"] = {
                "format": "msh",
                "mesh_dim": int(config.mesh_dim),
                **mesh_stats,
            }
            metadata["artifacts"] = {
                "mesh": str(mesh_path),
                "mesh_metadata": str(metadata_path),
                "marker_summary": str(marker_summary_path),
                "surface_mesh_2d": str(surface_mesh_path) if surface_mesh_path.exists() else None,
                "surface_patch_diagnostics": str(surface_patch_diagnostics_path) if surface_patch_diagnostics_path.exists() else None,
                "brep_hotspot_report": str(brep_hotspot_report_path) if brep_hotspot_report is not None else None,
                "hotspot_patch_report": None,
                "sliver_cluster_report": None,
                "compound_report": str(compound_report_path) if compound_report is not None else None,
                "gmsh_log": str(gmsh_log_path),
                "mesh2d_watchdog": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
                "mesh2d_watchdog_sample": (
                    str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None
                ),
                "mesh3d_watchdog": None,
                "mesh3d_watchdog_sample": None,
                "plc_probe": None,
                "surface_cleanup_report": None,
                "discrete_reparam_report": None,
                "retry_mesh_metadata": None,
                "classify_angle_probe": None,
            }
            _json_write(metadata_path, metadata)
            _json_write(marker_summary_path, marker_summary)
            return {
                "status": "failed",
                "failure_code": "surface_mesh_only_probe",
                "backend": recipe.backend,
                "backend_capability": recipe.backend_capability,
                "meshing_route": recipe.meshing_route,
                "geometry_family": recipe.geometry_family,
                "geometry_source": recipe.geometry_source,
                "route_stage": "surface_mesh_only",
                "mesh_format": "msh",
                "units": output_units or config.units,
                "body_bounds": body_bounds_dict,
                "farfield_bounds": bounds,
                "unit_normalization": unit_normalization,
                "artifacts": metadata["artifacts"],
                "marker_summary": marker_summary,
                "physical_groups": physical_groups,
                "mesh_stats": mesh_stats,
                "error": metadata["error"],
                "notes": [
                    "surface-only probe completed; volume meshing was intentionally not attempted",
                    f"loader={handle.loader}",
                    f"mesh_dim={config.mesh_dim}",
                ],
            }

        mesh3d_watchdog, mesh3d_error = _run_mesh3d_with_watchdog(
            gmsh,
            watchdog_path=mesh3d_watchdog_path,
            sample_path=mesh3d_watchdog_sample_path,
            timeout_seconds=float(
                config.metadata.get("mesh3d_watchdog_timeout_sec", DEFAULT_MESH3D_WATCHDOG_TIMEOUT_SECONDS)
            ),
            sample_seconds=int(
                config.metadata.get("mesh3d_watchdog_sample_seconds", DEFAULT_MESH3D_WATCHDOG_SAMPLE_SECONDS)
            ),
            mesh_algorithm_3d=int(field_info.get("mesh_algorithm_3d", 1)),
            pre_mesh_stats=metadata["volume_meshing"]["pre_generate3_mesh_stats"],
        )
        metadata["mesh3d_watchdog"] = {
            "artifact": str(mesh3d_watchdog_path),
            "sample_artifact": str(mesh3d_watchdog_sample_path),
            "status": mesh3d_watchdog.get("status"),
            "timeout_seconds": mesh3d_watchdog.get("timeout_seconds"),
            "triggered_at_elapsed_sec": mesh3d_watchdog.get("triggered_at_elapsed_sec"),
            "completed_elapsed_sec": mesh3d_watchdog.get("completed_elapsed_sec"),
            "meshing_stage_at_timeout": mesh3d_watchdog.get("meshing_stage_at_timeout"),
            "meshing_stage_after_return": mesh3d_watchdog.get("meshing_stage_after_return"),
            "timeout_phase_classification": mesh3d_watchdog.get("timeout_phase_classification"),
            "phase_classification_after_return": mesh3d_watchdog.get("phase_classification_after_return"),
            "boundary_node_count": mesh3d_watchdog.get("boundary_node_count"),
            "surface_triangle_count": mesh3d_watchdog.get("surface_triangle_count"),
            "iteration_count": mesh3d_watchdog.get("iteration_count"),
            "nodes_created": mesh3d_watchdog.get("nodes_created"),
            "nodes_created_per_boundary_node": mesh3d_watchdog.get("nodes_created_per_boundary_node"),
            "iterations_per_surface_triangle": mesh3d_watchdog.get("iterations_per_surface_triangle"),
            "hxt_points_considered": mesh3d_watchdog.get("hxt_points_considered"),
            "hxt_mesh_vertex_count": mesh3d_watchdog.get("hxt_mesh_vertex_count"),
            "hxt_points_filtered": mesh3d_watchdog.get("hxt_points_filtered"),
            "hxt_points_added": mesh3d_watchdog.get("hxt_points_added"),
            "tetrahedrizing_node_count": mesh3d_watchdog.get("tetrahedrizing_node_count"),
            "volume_count": mesh3d_watchdog.get("volume_count"),
            "connected_component_count": mesh3d_watchdog.get("connected_component_count"),
            "error": mesh3d_watchdog.get("error"),
        }
        metadata["volume_meshing"]["attempted"] = True
        metadata["volume_meshing"]["watchdog_status"] = mesh3d_watchdog.get("status")
        metadata["volume_meshing"]["watchdog_artifact"] = str(mesh3d_watchdog_path)
        metadata["volume_meshing"]["watchdog_sample_artifact"] = str(mesh3d_watchdog_sample_path)
        metadata["volume_meshing"]["burden_metrics"] = {
            "boundary_node_count": mesh3d_watchdog.get("boundary_node_count"),
            "surface_triangle_count": mesh3d_watchdog.get("surface_triangle_count"),
            "iteration_count": mesh3d_watchdog.get("iteration_count"),
            "nodes_created": mesh3d_watchdog.get("nodes_created"),
            "nodes_created_per_boundary_node": mesh3d_watchdog.get("nodes_created_per_boundary_node"),
            "iterations_per_surface_triangle": mesh3d_watchdog.get("iterations_per_surface_triangle"),
            "timeout_phase_classification": mesh3d_watchdog.get("timeout_phase_classification"),
            "hxt_points_considered": mesh3d_watchdog.get("hxt_points_considered"),
            "hxt_mesh_vertex_count": mesh3d_watchdog.get("hxt_mesh_vertex_count"),
            "hxt_points_filtered": mesh3d_watchdog.get("hxt_points_filtered"),
            "hxt_points_added": mesh3d_watchdog.get("hxt_points_added"),
        }

        if mesh3d_error is not None:
            if compound_report is not None:
                compound_report["status"] = "generate3_failed"
                compound_report["compound_result"]["3d_returned"] = False
                _refresh_compound_meshing_result(
                    gmsh,
                    compound_result=compound_report["compound_result"],
                    aircraft_group=aircraft_group,
                    farfield_group=farfield_group,
                )
            try:
                logger_messages = [str(message) for message in gmsh.logger.get()]
            except Exception:
                logger_messages = []
            exc = mesh3d_error
            plc_probe = _collect_plc_error_probe(
                gmsh,
                error_text=str(exc),
                logger_messages=logger_messages,
                surface_mesh_path=surface_mesh_path,
                mesh_algorithm_3d=int(field_info.get("mesh_algorithm_3d", 1)),
            )
            if "PLC Error" in str(exc):
                hxt_logger_checkpoint = len(logger_messages)
                plc_probe["hxt_probe"] = _run_3d_algorithm_probe(
                    gmsh,
                    aircraft_surface_tags=aircraft_surface_tags,
                    fluid_volume_tags=fluid_volume_tags,
                    algorithm3d=10,
                    logger_checkpoint=hxt_logger_checkpoint,
                    surface_mesh_path=surface_mesh_path,
                )
            _json_write(plc_probe_path, plc_probe)
            metadata["plc_probe"] = plc_probe
            if _should_attempt_surface_repair_fallback(str(exc), logger_messages) and surface_mesh_path.exists():
                if gmsh_logger_started:
                    _text_write(gmsh_log_path, [str(message) for message in gmsh.logger.get()])
                    try:
                        gmsh.logger.stop()
                    except Exception:
                        pass
                    gmsh_logger_started = False
                if gmsh_initialized:
                    gmsh.finalize()
                    gmsh_initialized = False
                surface_repair_result = _run_surface_repair_fallback(
                    surface_mesh_path=surface_mesh_path,
                    bounds=bounds,
                    mesh_path=mesh_path,
                    cleanup_report_path=surface_cleanup_report_path,
                    discrete_reparam_report_path=discrete_reparam_report_path,
                    retry_metadata_path=retry_mesh_metadata_path,
                    mesh_algorithm_2d=int(field_info.get("mesh_algorithm_2d", 6)),
                    mesh_algorithm_3d=int(field_info.get("mesh_algorithm_3d", 1)),
                    wall_marker_name=wall_marker_name,
                    thread_count=config.gmsh_threads,
                )
                metadata["surface_repair_fallback"] = {
                    "status": surface_repair_result["status"],
                    "route_stage": surface_repair_result["route_stage"],
                    "cleanup_report_artifact": str(surface_cleanup_report_path),
                    "discrete_reparam_report_artifact": str(discrete_reparam_report_path),
                    "retry_mesh_metadata_artifact": str(retry_mesh_metadata_path),
                    "notes": surface_repair_result.get("notes", []),
                }
                if surface_repair_result["status"] == "success":
                    physical_groups = surface_repair_result["physical_groups"]
                    marker_summary = surface_repair_result["marker_summary"]
                    mesh_stats = {
                        "mesh_dim": int(config.mesh_dim),
                        **surface_repair_result["mesh_stats"],
                    }
                    artifacts = MeshArtifactBundle(
                        mesh=mesh_path,
                        mesh_metadata=metadata_path,
                        marker_summary=marker_summary_path,
                        surface_mesh_2d=surface_mesh_path if surface_mesh_path.exists() else None,
                        surface_patch_diagnostics=surface_patch_diagnostics_path if surface_patch_diagnostics_path.exists() else None,
                        brep_hotspot_report=brep_hotspot_report_path if brep_hotspot_report is not None else None,
                        compound_report=compound_report_path if compound_report is not None else None,
                        gmsh_log=gmsh_log_path,
                        mesh2d_watchdog=mesh2d_watchdog_path if mesh2d_watchdog_path.exists() else None,
                        mesh2d_watchdog_sample=mesh2d_watchdog_sample_path if mesh2d_watchdog_sample_path.exists() else None,
                        mesh3d_watchdog=mesh3d_watchdog_path if mesh3d_watchdog_path.exists() else None,
                        mesh3d_watchdog_sample=mesh3d_watchdog_sample_path if mesh3d_watchdog_sample_path.exists() else None,
                        plc_probe=plc_probe_path if plc_probe_path.exists() else None,
                        surface_cleanup_report=surface_cleanup_report_path if surface_cleanup_report_path.exists() else None,
                        discrete_reparam_report=discrete_reparam_report_path if discrete_reparam_report_path.exists() else None,
                        retry_mesh_metadata=retry_mesh_metadata_path if retry_mesh_metadata_path.exists() else None,
                        classify_angle_probe=classify_angle_probe_path if classify_angle_probe_path.exists() else None,
                    )
                    provider_provenance = None
                    if handle.provider_result is not None:
                        provider_provenance = {
                            "provider": handle.provider_result.provider,
                            "provider_stage": handle.provider_result.provider_stage,
                            "provider_status": handle.provider_result.status,
                            "topology": handle.provider_result.topology.model_dump(mode="json"),
                            "provenance": handle.provider_result.provenance,
                            "artifacts": {
                                key: str(value)
                                for key, value in handle.provider_result.artifacts.items()
                            },
                        }
                    handoff = MeshHandoff(
                        route_stage="surface_repair_fallback",
                        backend_capability=recipe.backend_capability,
                        meshing_route=recipe.meshing_route,
                        geometry_family=recipe.geometry_family,
                        geometry_source=recipe.geometry_source,
                        geometry_provider=handle.provider,
                        source_path=handle.source_path,
                        normalized_geometry_path=handle.path,
                        units=output_units or config.units,
                        body_bounds=_bounds_model(*body_bounds),
                        farfield_bounds=Bounds3D(**bounds),
                        mesh_stats=mesh_stats,
                        marker_summary=marker_summary,
                        physical_groups=physical_groups,
                        artifacts=artifacts,
                        provenance={
                            "route_provenance": recipe.route_provenance,
                            "geometry_loader": handle.loader,
                            "provider": provider_provenance,
                        },
                        unit_normalization=unit_normalization or {},
                    )
                    metadata["status"] = "success"
                    metadata["route_stage"] = "surface_repair_fallback"
                    metadata["volume_meshing"]["completed"] = True
                    metadata["physical_groups"] = physical_groups
                    metadata["marker_summary"] = marker_summary
                    metadata["mesh"] = {
                        "format": "msh",
                        "mesh_dim": config.mesh_dim,
                        **mesh_stats,
                    }
                    if compound_report is not None:
                        metadata["compound_result"] = {
                            "artifact": str(compound_report_path),
                            **compound_report["compound_result"],
                        }
                    metadata["artifacts"] = {
                        "mesh": str(mesh_path),
                        "mesh_metadata": str(metadata_path),
                        "marker_summary": str(marker_summary_path),
                        "surface_mesh_2d": str(surface_mesh_path) if surface_mesh_path.exists() else None,
                        "surface_patch_diagnostics": str(surface_patch_diagnostics_path) if surface_patch_diagnostics_path.exists() else None,
                        "brep_hotspot_report": str(brep_hotspot_report_path) if brep_hotspot_report is not None else None,
                        "compound_report": str(compound_report_path) if compound_report is not None else None,
                        "gmsh_log": str(gmsh_log_path),
                        "mesh2d_watchdog": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
                        "mesh2d_watchdog_sample": (
                            str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None
                        ),
                        "mesh3d_watchdog": str(mesh3d_watchdog_path) if mesh3d_watchdog_path.exists() else None,
                        "mesh3d_watchdog_sample": (
                            str(mesh3d_watchdog_sample_path) if mesh3d_watchdog_sample_path.exists() else None
                        ),
                        "plc_probe": str(plc_probe_path) if plc_probe_path.exists() else None,
                        "surface_cleanup_report": str(surface_cleanup_report_path) if surface_cleanup_report_path.exists() else None,
                        "discrete_reparam_report": str(discrete_reparam_report_path) if discrete_reparam_report_path.exists() else None,
                        "retry_mesh_metadata": str(retry_mesh_metadata_path) if retry_mesh_metadata_path.exists() else None,
                        "classify_angle_probe": str(classify_angle_probe_path) if classify_angle_probe_path.exists() else None,
                    }
                    _json_write(metadata_path, metadata)
                    _json_write(marker_summary_path, marker_summary)
                    if compound_report is not None:
                        _json_write(compound_report_path, compound_report)
                if surface_repair_result["status"] != "success":
                    raise exc
                return {
                    "status": "success",
                        "backend": recipe.backend,
                        "backend_capability": recipe.backend_capability,
                        "meshing_route": recipe.meshing_route,
                        "geometry_family": recipe.geometry_family,
                        "geometry_source": recipe.geometry_source,
                        "route_stage": "surface_repair_fallback",
                        "mesh_format": "msh",
                        "units": output_units or config.units,
                        "contract": handoff.contract,
                        "geometry_provider": handoff.geometry_provider,
                        "body_bounds": body_bounds_dict,
                        "farfield_bounds": bounds,
                        "unit_normalization": unit_normalization,
                        "artifacts": metadata["artifacts"],
                        "marker_summary": marker_summary,
                        "physical_groups": physical_groups,
                        "mesh_stats": mesh_stats,
                        "mesh_handoff": handoff.model_dump(mode="json"),
                        "provenance": handoff.provenance,
                        "notes": [
                            "baseline OCC external-flow mesh failed, then surface-repair fallback generated a tetra mesh",
                            f"loader={handle.loader}",
                            f"mesh_dim={config.mesh_dim}",
                        ],
                    }
            raise exc
        if compound_report is not None:
            compound_report["status"] = "generate3_returned"
            compound_report["compound_result"]["3d_returned"] = True
            _refresh_compound_meshing_result(
                gmsh,
                compound_result=compound_report["compound_result"],
                aircraft_group=aircraft_group,
                farfield_group=farfield_group,
            )
        optimization_settings = (
            field_info.get("volume_optimization", {}) if isinstance(field_info, dict) else {}
        )
        post_optimize_runs = _run_post_generate3_optimizers(gmsh, optimization_settings)
        metadata["volume_meshing"]["optimization"] = {
            **optimization_settings,
            "post_runs": post_optimize_runs,
        }
        gmsh.write(str(mesh_path))
        mesh_stats = {
            "mesh_dim": int(config.mesh_dim),
            **_mesh_stats(gmsh),
        }
        final_logger_messages: list[str] = []
        try:
            final_logger_messages = [str(message) for message in gmsh.logger.get()]
        except Exception:
            final_logger_messages = []
        quality_metrics = (
            _collect_volume_quality_metrics(
                gmsh,
                marker_summary=marker_summary,
                physical_groups=physical_groups,
                logger_messages=final_logger_messages,
            )
            if int(mesh_stats.get("volume_element_count", 0) or 0) > 0
            else None
        )
        hotspot_patch_report = (
            _collect_hotspot_patch_report(
                gmsh,
                surface_patch_diagnostics=surface_patch_diagnostics,
                quality_metrics=quality_metrics,
                mesh_field=field_info,
                requested_surface_tags=config.metadata.get("mesh_hotspot_surface_tags"),
            )
            if quality_metrics is not None
            else None
        )
        sliver_cluster_report = (
            _collect_sliver_cluster_report(
                baseline=str(
                    config.metadata.get(
                        "codex_case_name",
                        (config.sliver_volume_pocket_policy.source_baseline if config.sliver_volume_pocket_policy else "baseline"),
                    )
                ),
                quality_metrics=quality_metrics,
                hotspot_patch_report=hotspot_patch_report,
                focus_surface_tags=config.metadata.get("mesh_hotspot_surface_tags"),
            )
            if quality_metrics is not None and config.sliver_volume_pocket_policy is not None
            else None
        )
        metadata["volume_meshing"]["completed"] = True
        artifacts = MeshArtifactBundle(
            mesh=mesh_path,
            mesh_metadata=metadata_path,
            marker_summary=marker_summary_path,
            surface_mesh_2d=surface_mesh_path if surface_mesh_path.exists() else None,
            surface_patch_diagnostics=surface_patch_diagnostics_path if surface_patch_diagnostics_path.exists() else None,
            brep_hotspot_report=brep_hotspot_report_path if brep_hotspot_report is not None else None,
            hotspot_patch_report=hotspot_patch_report_path if hotspot_patch_report is not None else None,
            sliver_cluster_report=sliver_cluster_report_path if sliver_cluster_report is not None else None,
            compound_report=compound_report_path if compound_report is not None else None,
            gmsh_log=gmsh_log_path,
            mesh2d_watchdog=mesh2d_watchdog_path if mesh2d_watchdog_path.exists() else None,
            mesh2d_watchdog_sample=mesh2d_watchdog_sample_path if mesh2d_watchdog_sample_path.exists() else None,
            mesh3d_watchdog=mesh3d_watchdog_path if mesh3d_watchdog_path.exists() else None,
            mesh3d_watchdog_sample=mesh3d_watchdog_sample_path if mesh3d_watchdog_sample_path.exists() else None,
            plc_probe=plc_probe_path if plc_probe_path.exists() else None,
            surface_cleanup_report=surface_cleanup_report_path if surface_cleanup_report_path.exists() else None,
            discrete_reparam_report=discrete_reparam_report_path if discrete_reparam_report_path.exists() else None,
            retry_mesh_metadata=retry_mesh_metadata_path if retry_mesh_metadata_path.exists() else None,
            classify_angle_probe=classify_angle_probe_path if classify_angle_probe_path.exists() else None,
        )
        provider_provenance = None
        if handle.provider_result is not None:
            provider_provenance = {
                "provider": handle.provider_result.provider,
                "provider_stage": handle.provider_result.provider_stage,
                "provider_status": handle.provider_result.status,
                "topology": handle.provider_result.topology.model_dump(mode="json"),
                "provenance": handle.provider_result.provenance,
            }
        handoff = MeshHandoff(
            route_stage="baseline",
            backend=recipe.backend,
            backend_capability=recipe.backend_capability,
            meshing_route=recipe.meshing_route,
            geometry_family=recipe.geometry_family,
            geometry_source=recipe.geometry_source,
            geometry_provider=handle.provider,
            source_path=handle.source_path,
            normalized_geometry_path=handle.path,
            units=output_units or config.units,
            mesh_format="msh",
            body_bounds=_bounds_model(*body_bounds),
            farfield_bounds=Bounds3D(**bounds),
            mesh_stats={
                "mesh_dim": config.mesh_dim,
                **mesh_stats,
            },
            marker_summary=marker_summary,
            physical_groups=physical_groups,
            artifacts=artifacts,
            provenance={
                "route_provenance": recipe.route_provenance,
                "loader": handle.loader,
                "provider": provider_provenance,
                "body": {
                    "imported_volume_count": len(body_dim_tags),
                    "imported_surface_count": imported_surface_count,
                    "healing": healing_summary,
                },
                "farfield": {
                    "enabled": config.farfield.enabled,
                    "scale_factors": {
                        "upstream_factor": config.farfield.upstream_factor,
                        "downstream_factor": config.farfield.downstream_factor,
                        "lateral_factor": config.farfield.lateral_factor,
                        "vertical_factor": config.farfield.vertical_factor,
                    },
                },
                "mesh_field": field_info,
            },
            unit_normalization=unit_normalization,
        )
        metadata = {
            **metadata,
            "status": "success",
            **handoff.model_dump(mode="json"),
            "body": {
                "imported_volume_count": len(body_dim_tags),
                "imported_surface_count": imported_surface_count,
                "bounds": body_bounds_dict,
                "healing": healing_summary,
            },
            "farfield": {
                "enabled": config.farfield.enabled,
                "bounds": bounds,
                "scale_factors": {
                    "upstream_factor": config.farfield.upstream_factor,
                    "downstream_factor": config.farfield.downstream_factor,
                    "lateral_factor": config.farfield.lateral_factor,
                    "vertical_factor": config.farfield.vertical_factor,
                },
            },
            "mesh_field": field_info,
            "mesh": {
                "format": "msh",
                "mesh_dim": config.mesh_dim,
                **mesh_stats,
            },
        }
        if quality_metrics is not None:
            metadata["quality_metrics"] = quality_metrics
        if (
            isinstance(volume_smoke_decoupled, dict)
            and isinstance(volume_smoke_decoupled.get("tip_quality_buffer_policy"), dict)
            and volume_smoke_decoupled["tip_quality_buffer_policy"].get("enabled")
        ):
            metadata["tip_quality_buffer_policy"] = volume_smoke_decoupled["tip_quality_buffer_policy"]
        if (
            isinstance(volume_smoke_decoupled, dict)
            and isinstance(volume_smoke_decoupled.get("sliver_volume_pocket_policy"), dict)
            and volume_smoke_decoupled["sliver_volume_pocket_policy"].get("enabled")
        ):
            metadata["sliver_volume_pocket_policy"] = volume_smoke_decoupled["sliver_volume_pocket_policy"]
        if brep_hotspot_report is not None:
            metadata["brep_hotspot_report"] = {
                "artifact": str(brep_hotspot_report_path),
                "status": brep_hotspot_report.get("status"),
                "selected_surface_tags": brep_hotspot_report.get("selected_surface_tags", []),
                "selected_curve_tags": brep_hotspot_report.get("selected_curve_tags", []),
                "shape_valid_default": brep_hotspot_report.get("shape_valid_default"),
                "shape_valid_exact": brep_hotspot_report.get("shape_valid_exact"),
            }
        if hotspot_patch_report is not None:
            metadata["hotspot_patch_report"] = {
                "artifact": str(hotspot_patch_report_path),
                "selected_surface_tags": hotspot_patch_report.get("selected_surface_tags", []),
                "requested_surface_tags": hotspot_patch_report.get("requested_surface_tags", []),
            }
        if sliver_cluster_report is not None:
            metadata["sliver_cluster_report"] = {
                "artifact": str(sliver_cluster_report_path),
                "baseline": sliver_cluster_report.get("baseline"),
                "ill_shaped_tet_count": sliver_cluster_report.get("ill_shaped_tet_count"),
                "cluster_count": len(sliver_cluster_report.get("clusters", [])),
            }
        if compound_report is not None:
            compound_report["status"] = "success"
            metadata["compound_result"] = {
                "artifact": str(compound_report_path),
                **compound_report["compound_result"],
            }
        _json_write(metadata_path, metadata)
        _json_write(marker_summary_path, marker_summary)
        if brep_hotspot_report is not None:
            _json_write(brep_hotspot_report_path, brep_hotspot_report)
        if hotspot_patch_report is not None:
            _json_write(hotspot_patch_report_path, hotspot_patch_report)
        if sliver_cluster_report is not None:
            _json_write(sliver_cluster_report_path, sliver_cluster_report)
        if compound_report is not None:
            _json_write(compound_report_path, compound_report)

        return {
            "status": "success",
            "backend": recipe.backend,
            "backend_capability": recipe.backend_capability,
            "meshing_route": recipe.meshing_route,
            "geometry_family": recipe.geometry_family,
            "geometry_source": recipe.geometry_source,
            "route_stage": "baseline",
            "mesh_format": "msh",
            "units": output_units or config.units,
            "contract": handoff.contract,
            "geometry_provider": handoff.geometry_provider,
            "body_bounds": body_bounds_dict,
            "farfield_bounds": bounds,
            "unit_normalization": unit_normalization,
            "artifacts": {
                "mesh": str(mesh_path),
                "mesh_metadata": str(metadata_path),
                "marker_summary": str(marker_summary_path),
                "surface_mesh_2d": str(surface_mesh_path) if surface_mesh_path.exists() else None,
                "surface_patch_diagnostics": str(surface_patch_diagnostics_path) if surface_patch_diagnostics_path.exists() else None,
                "brep_hotspot_report": str(brep_hotspot_report_path) if brep_hotspot_report is not None else None,
                "hotspot_patch_report": str(hotspot_patch_report_path) if hotspot_patch_report is not None else None,
                "sliver_cluster_report": str(sliver_cluster_report_path) if sliver_cluster_report is not None else None,
                "compound_report": str(compound_report_path) if compound_report is not None else None,
                "gmsh_log": str(gmsh_log_path),
                "mesh2d_watchdog": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
                "mesh2d_watchdog_sample": (
                    str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None
                ),
                "mesh3d_watchdog": str(mesh3d_watchdog_path) if mesh3d_watchdog_path.exists() else None,
                "mesh3d_watchdog_sample": (
                    str(mesh3d_watchdog_sample_path) if mesh3d_watchdog_sample_path.exists() else None
                ),
                "plc_probe": str(plc_probe_path) if plc_probe_path.exists() else None,
                "surface_cleanup_report": str(surface_cleanup_report_path) if surface_cleanup_report_path.exists() else None,
                "discrete_reparam_report": str(discrete_reparam_report_path) if discrete_reparam_report_path.exists() else None,
                "retry_mesh_metadata": str(retry_mesh_metadata_path) if retry_mesh_metadata_path.exists() else None,
                "classify_angle_probe": str(classify_angle_probe_path) if classify_angle_probe_path.exists() else None,
            },
            "marker_summary": marker_summary,
            "physical_groups": physical_groups,
            "mesh_stats": mesh_stats,
            "mesh_handoff": handoff.model_dump(mode="json"),
            "provenance": handoff.provenance,
            "notes": [
                "baseline OCC external-flow mesh generated from normalized STEP",
                f"loader={handle.loader}",
                f"mesh_dim={config.mesh_dim}",
            ],
        }
    except Exception as exc:
        final_error = (
            surface_repair_result["error"]
            if surface_repair_result is not None and surface_repair_result.get("status") == "failed"
            else str(exc)
        )
        metadata["status"] = "failed"
        metadata["failure_code"] = _backend_failure_code(final_error)
        metadata["error"] = final_error
        if compound_report is not None:
            if compound_report["compound_result"].get("2d_returned") is None:
                compound_report["status"] = "generate2_failed"
                compound_report["compound_result"]["2d_returned"] = False
                compound_report["compound_result"]["3d_returned"] = False
                compound_report["compound_result"]["reparam_success"] = False
            elif (
                config.mesh_dim == 3
                and compound_report["compound_result"].get("3d_returned") is None
            ):
                compound_report["status"] = "generate3_failed"
                compound_report["compound_result"]["3d_returned"] = False
            if gmsh_initialized:
                _refresh_compound_meshing_result(
                    gmsh,
                    compound_result=compound_report["compound_result"],
                    aircraft_group=locals().get("aircraft_group"),
                    farfield_group=locals().get("farfield_group"),
                )
            metadata["compound_result"] = {
                "artifact": str(compound_report_path),
                **compound_report["compound_result"],
            }
        if body_bounds_dict is not None:
            metadata.setdefault("body", {})
            metadata["body"]["bounds"] = body_bounds_dict
        if bounds is not None:
            metadata["farfield"] = {
                "enabled": config.farfield.enabled,
                "bounds": bounds,
                "scale_factors": {
                    "upstream_factor": config.farfield.upstream_factor,
                    "downstream_factor": config.farfield.downstream_factor,
                    "lateral_factor": config.farfield.lateral_factor,
                    "vertical_factor": config.farfield.vertical_factor,
                },
            }
        if field_info:
            metadata["mesh_field"] = field_info
        if unit_normalization is not None:
            metadata["unit_normalization"] = unit_normalization
        if surface_repair_result is not None:
            if _should_probe_discrete_classify_angles(
                surface_repair_result,
                surface_mesh_exists=surface_mesh_path.exists(),
                classify_probe_exists=classify_angle_probe_path.exists(),
            ):
                _probe_discrete_classify_angles(
                    surface_mesh_path=surface_mesh_path,
                    probe_path=classify_angle_probe_path,
                    angle_degrees=[40.0, 20.0, 10.0],
                    mesh_algorithm_2d=int(field_info.get("mesh_algorithm_2d", 6) or 6),
                    mesh_algorithm_3d=int(field_info.get("mesh_algorithm_3d", 1) or 1),
                    thread_count=config.gmsh_threads,
                )
            metadata["surface_repair_fallback"] = {
                "status": surface_repair_result["status"],
                "route_stage": surface_repair_result["route_stage"],
                "error": surface_repair_result.get("error"),
                "cleanup_report_artifact": str(surface_cleanup_report_path) if surface_cleanup_report_path.exists() else None,
                "discrete_reparam_report_artifact": (
                    str(discrete_reparam_report_path) if discrete_reparam_report_path.exists() else None
                ),
                "retry_mesh_metadata_artifact": (
                    str(retry_mesh_metadata_path) if retry_mesh_metadata_path.exists() else None
                ),
                "classify_angle_probe_artifact": (
                    str(classify_angle_probe_path) if classify_angle_probe_path.exists() else None
                ),
                "notes": surface_repair_result.get("notes", []),
            }
            if classify_angle_probe_path.exists():
                metadata["surface_repair_fallback"]["classify_angle_probe_artifact"] = str(classify_angle_probe_path)
        if physical_groups:
            metadata["physical_groups"] = physical_groups
        if marker_summary:
            metadata["marker_summary"] = marker_summary
        if mesh_stats:
            metadata["mesh"] = {
                "format": "msh",
                "mesh_dim": config.mesh_dim,
                **mesh_stats,
            }
        if surface_patch_diagnostics is not None and "surface_patch_diagnostics" not in metadata:
            metadata["surface_patch_diagnostics"] = {
                "artifact": str(surface_patch_diagnostics_path) if surface_patch_diagnostics_path.exists() else None,
                "surface_count": int(surface_patch_diagnostics["surface_count"]),
                "curve_count": int(surface_patch_diagnostics["curve_count"]),
                "suspicious_surface_tags": [int(entry["tag"]) for entry in surface_patch_diagnostics["suspicious_surfaces"][:12]],
                "shortest_curve_tags": [int(entry["tag"]) for entry in surface_patch_diagnostics["shortest_curves"][:20]],
            }
        if brep_hotspot_report is not None and "brep_hotspot_report" not in metadata:
            metadata["brep_hotspot_report"] = {
                "artifact": str(brep_hotspot_report_path) if brep_hotspot_report_path.exists() else None,
                "status": brep_hotspot_report.get("status"),
                "selected_surface_tags": brep_hotspot_report.get("selected_surface_tags", []),
                "selected_curve_tags": brep_hotspot_report.get("selected_curve_tags", []),
                "shape_valid_default": brep_hotspot_report.get("shape_valid_default"),
                "shape_valid_exact": brep_hotspot_report.get("shape_valid_exact"),
            }
        if mesh2d_watchdog is not None:
            metadata["mesh2d_watchdog"] = {
                "artifact": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
                "sample_artifact": str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None,
                "status": mesh2d_watchdog.get("status"),
                "timeout_seconds": mesh2d_watchdog.get("timeout_seconds"),
                "triggered_at_elapsed_sec": mesh2d_watchdog.get("triggered_at_elapsed_sec"),
                "completed_elapsed_sec": mesh2d_watchdog.get("completed_elapsed_sec"),
                "last_meshing_surface_tag": mesh2d_watchdog.get("last_meshing_surface_tag"),
            }
        if mesh3d_watchdog is not None:
            metadata["mesh3d_watchdog"] = {
                "artifact": str(mesh3d_watchdog_path) if mesh3d_watchdog_path.exists() else None,
                "sample_artifact": str(mesh3d_watchdog_sample_path) if mesh3d_watchdog_sample_path.exists() else None,
                "status": mesh3d_watchdog.get("status"),
                "timeout_seconds": mesh3d_watchdog.get("timeout_seconds"),
                "triggered_at_elapsed_sec": mesh3d_watchdog.get("triggered_at_elapsed_sec"),
                "completed_elapsed_sec": mesh3d_watchdog.get("completed_elapsed_sec"),
                "meshing_stage_at_timeout": mesh3d_watchdog.get("meshing_stage_at_timeout"),
                "meshing_stage_after_return": mesh3d_watchdog.get("meshing_stage_after_return"),
                "tetrahedrizing_node_count": mesh3d_watchdog.get("tetrahedrizing_node_count"),
                "volume_count": mesh3d_watchdog.get("volume_count"),
                "connected_component_count": mesh3d_watchdog.get("connected_component_count"),
                "error": mesh3d_watchdog.get("error"),
            }
        metadata["artifacts"] = {
            "mesh": str(mesh_path),
            "mesh_metadata": str(metadata_path),
            "marker_summary": str(marker_summary_path),
            "surface_mesh_2d": str(surface_mesh_path) if surface_mesh_path.exists() else None,
            "surface_patch_diagnostics": str(surface_patch_diagnostics_path) if surface_patch_diagnostics_path.exists() else None,
            "brep_hotspot_report": str(brep_hotspot_report_path) if brep_hotspot_report is not None else None,
            "sliver_cluster_report": str(sliver_cluster_report_path) if sliver_cluster_report_path.exists() else None,
            "compound_report": str(compound_report_path) if compound_report is not None else None,
            "gmsh_log": str(gmsh_log_path),
            "mesh2d_watchdog": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
            "mesh2d_watchdog_sample": (
                str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None
            ),
            "mesh3d_watchdog": str(mesh3d_watchdog_path) if mesh3d_watchdog_path.exists() else None,
            "mesh3d_watchdog_sample": (
                str(mesh3d_watchdog_sample_path) if mesh3d_watchdog_sample_path.exists() else None
            ),
            "plc_probe": str(plc_probe_path) if plc_probe_path.exists() else None,
            "surface_cleanup_report": str(surface_cleanup_report_path) if surface_cleanup_report_path.exists() else None,
            "discrete_reparam_report": str(discrete_reparam_report_path) if discrete_reparam_report_path.exists() else None,
            "retry_mesh_metadata": str(retry_mesh_metadata_path) if retry_mesh_metadata_path.exists() else None,
            "classify_angle_probe": str(classify_angle_probe_path) if classify_angle_probe_path.exists() else None,
        }
        _json_write(metadata_path, metadata)
        _json_write(marker_summary_path, marker_summary)
        if brep_hotspot_report is not None:
            _json_write(brep_hotspot_report_path, brep_hotspot_report)
        if compound_report is not None:
            _json_write(compound_report_path, compound_report)
        return {
            "status": "failed",
            "failure_code": _backend_failure_code(final_error),
            "backend": recipe.backend,
            "backend_capability": recipe.backend_capability,
            "meshing_route": recipe.meshing_route,
            "geometry_family": recipe.geometry_family,
            "geometry_source": recipe.geometry_source,
            "route_stage": "baseline",
            "artifacts": {
                "mesh": str(mesh_path),
                "mesh_metadata": str(metadata_path),
                "marker_summary": str(marker_summary_path),
                "surface_mesh_2d": str(surface_mesh_path) if surface_mesh_path.exists() else None,
                "surface_patch_diagnostics": str(surface_patch_diagnostics_path) if surface_patch_diagnostics_path.exists() else None,
                "brep_hotspot_report": str(brep_hotspot_report_path) if brep_hotspot_report is not None else None,
                "compound_report": str(compound_report_path) if compound_report is not None else None,
                "gmsh_log": str(gmsh_log_path),
                "mesh2d_watchdog": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
                "mesh2d_watchdog_sample": (
                    str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None
                ),
                "mesh3d_watchdog": str(mesh3d_watchdog_path) if mesh3d_watchdog_path.exists() else None,
                "mesh3d_watchdog_sample": (
                    str(mesh3d_watchdog_sample_path) if mesh3d_watchdog_sample_path.exists() else None
                ),
                "plc_probe": str(plc_probe_path) if plc_probe_path.exists() else None,
                "surface_cleanup_report": str(surface_cleanup_report_path) if surface_cleanup_report_path.exists() else None,
                "discrete_reparam_report": str(discrete_reparam_report_path) if discrete_reparam_report_path.exists() else None,
                "retry_mesh_metadata": str(retry_mesh_metadata_path) if retry_mesh_metadata_path.exists() else None,
                "classify_angle_probe": str(classify_angle_probe_path) if classify_angle_probe_path.exists() else None,
            },
            "marker_summary": marker_summary,
            "mesh_stats": mesh_stats,
            "physical_groups": physical_groups,
            "error": final_error,
            "notes": [
                (
                    "baseline OCC external-flow mesh failed and surface-repair fallback did not resolve the boundary mesh"
                    if surface_repair_result is not None
                    else "baseline OCC external-flow mesh failed"
                ),
                f"loader={handle.loader}",
                f"mesh_dim={config.mesh_dim}",
            ],
        }
    finally:
        if gmsh_initialized:
            if gmsh_logger_started:
                try:
                    _text_write(gmsh_log_path, [str(message) for message in gmsh.logger.get()])
                except Exception:
                    pass
                try:
                    gmsh.logger.stop()
                except Exception:
                    pass
            gmsh.finalize()


def apply_recipe(
    recipe: MeshRecipe,
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    if recipe.meshing_route in REAL_OCC_ROUTES:
        return _apply_occ_external_flow_route(recipe, handle, config)
    return _placeholder_backend_result(recipe, handle, config)


def apply_recipe_stub(
    recipe: MeshRecipe,
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    return apply_recipe(recipe, handle, config)
