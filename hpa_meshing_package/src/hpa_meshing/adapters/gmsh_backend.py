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
}
DEFAULT_SURFACE_NODES_PER_REFERENCE_LENGTH = 128.0
DEFAULT_EDGE_REFINEMENT_RATIO = 0.5
DEFAULT_FARFIELD_REFERENCE_FACTOR = 4.0
DEFAULT_SURFACE_DISTANCE_FACTOR = 0.25
DEFAULT_EDGE_DISTANCE_FACTOR = 0.05
DEFAULT_SURFACE_TRANSITION_FACTOR = 10.0
DEFAULT_EDGE_TRANSITION_FACTOR = 10.0
SURFACE_REPAIR_CLASSIFY_ANGLE_DEGREES = 40.0
DEFAULT_MESH2D_WATCHDOG_TIMEOUT_SECONDS = 20.0
DEFAULT_MESH2D_WATCHDOG_SAMPLE_SECONDS = 1
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


class GmshBackendError(RuntimeError):
    """Raised when the real Gmsh backend cannot produce a mesh artifact."""


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


def _import_scale_to_units(handle: GeometryHandle) -> tuple[float, str | None]:
    provider_result = handle.provider_result
    if provider_result is None:
        return 1.0, None
    topology = provider_result.topology
    scale = topology.import_scale_to_units
    if scale is None or scale <= 0.0:
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


def _collect_surface_patch_diagnostics(
    gmsh,
    *,
    surface_tags: list[int],
    reference_length: float,
    near_body_size: float,
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
        "surface_records": surface_records,
        "smallest_area_surfaces": smallest_area_surfaces,
        "shortest_curves": shortest_curves,
        "suspicious_surfaces": suspicious_surfaces,
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


def _resolve_sizing_reference_length(handle: GeometryHandle, config: MeshJobConfig) -> float:
    reference_length = resolve_reference_length(
        handle.source_path,
        provider_result=handle.provider_result,
        metadata=config.metadata,
    )
    if reference_length is None or reference_length <= 0.0:
        raise GmshBackendError(
            "geometry-derived reference length is required for thin_sheet_aircraft_assembly surface sizing"
        )
    return float(reference_length)


def _configure_mesh_field(
    gmsh,
    aircraft_surface_tags: list[int],
    aircraft_curve_tags: list[int],
    reference_length: float,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    near_body_size = config.global_min_size or (reference_length / DEFAULT_SURFACE_NODES_PER_REFERENCE_LENGTH)
    if near_body_size > reference_length:
        raise GmshBackendError(
            "near-body surface size exceeds reference length; aircraft surface would be under-resolved"
        )
    edge_size = near_body_size * DEFAULT_EDGE_REFINEMENT_RATIO
    farfield_size = config.global_max_size or max(reference_length * DEFAULT_FARFIELD_REFERENCE_FACTOR, near_body_size * 40.0)
    distance_min = 0.0
    distance_max = max(reference_length * DEFAULT_SURFACE_DISTANCE_FACTOR, near_body_size * DEFAULT_SURFACE_TRANSITION_FACTOR)
    edge_distance_max = max(reference_length * DEFAULT_EDGE_DISTANCE_FACTOR, edge_size * DEFAULT_EDGE_TRANSITION_FACTOR)
    mesh_algorithm_2d = int(config.mesh_algorithm_2d) if config.mesh_algorithm_2d is not None else 6
    mesh_algorithm_3d = int(config.mesh_algorithm_3d) if config.mesh_algorithm_3d is not None else 1

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
    gmsh.model.mesh.field.setAsBackgroundMesh(combined_field)

    gmsh.option.setNumber("Mesh.MeshSizeMin", edge_size)
    gmsh.option.setNumber("Mesh.MeshSizeMax", farfield_size)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 0)
    gmsh.option.setNumber("Mesh.Algorithm", float(mesh_algorithm_2d))
    gmsh.option.setNumber("Mesh.Algorithm3D", float(mesh_algorithm_3d))

    return {
        "characteristic_length_policy": "reference_length",
        "reference_length": reference_length,
        "surface_target_nodes_per_reference_length": int(DEFAULT_SURFACE_NODES_PER_REFERENCE_LENGTH),
        "near_body_size": near_body_size,
        "edge_size": edge_size,
        "farfield_size": farfield_size,
        "distance_min": distance_min,
        "distance_max": distance_max,
        "edge_distance_max": edge_distance_max,
        "mesh_size_from_points": 0,
        "mesh_size_from_curvature": 0,
        "mesh_size_extend_from_boundary": 0,
        "mesh_algorithm_2d": mesh_algorithm_2d,
        "mesh_algorithm_3d": mesh_algorithm_3d,
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
        last_surface = _extract_last_meshing_surface(logger_messages)
        sample_result = sample_runner(int(os.getpid()), int(sample_seconds), sample_path)
        with payload_lock:
            payload["status"] = "triggered_while_meshing"
            payload["triggered_at_elapsed_sec"] = float(time.monotonic() - start)
            payload["logger_message_count"] = len(logger_messages)
            payload["logger_tail"] = _logger_tail(logger_messages)
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
    last_surface = _extract_last_meshing_surface(final_logger_messages)
    with payload_lock:
        payload["completed_elapsed_sec"] = float(time.monotonic() - start)
        payload["logger_message_count_after_generate"] = len(final_logger_messages)
        payload["logger_tail_after_generate"] = _logger_tail(final_logger_messages)
        if last_surface is not None:
            payload["last_meshing_surface_tag_after_generate"] = int(last_surface["surface_tag"])
            payload["last_meshing_surface_message_after_generate"] = str(last_surface["message"])
        if payload["status"] == "armed":
            payload["status"] = "completed_without_timeout"
        elif payload["status"] == "triggered_while_meshing":
            payload["status"] = "completed_after_timeout"
    _json_write(watchdog_path, payload)
    return payload


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
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.Binary", 0)
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
        gmsh.model.setPhysicalName(2, aircraft_group, "aircraft")
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
            gmsh.model.setPhysicalName(2, aircraft_group, "aircraft")
            farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
            gmsh.model.setPhysicalName(2, farfield_group, "farfield")

            gmsh.model.mesh.generate(3)
        gmsh.write(str(mesh_path))

        mesh_stats = _mesh_stats(gmsh)
        physical_groups = {
            "fluid": _physical_group_summary(gmsh, 3, fluid_group),
            "aircraft": _physical_group_summary(gmsh, 2, aircraft_group),
            "farfield": _physical_group_summary(gmsh, 2, farfield_group),
        }
        marker_summary = {
            "aircraft": physical_groups["aircraft"],
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
) -> Dict[str, Any]:
    gmsh = load_gmsh()
    results: list[Dict[str, Any]] = []
    for angle_deg in angle_degrees:
        gmsh.initialize()
        logger_started = False
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Binary", 0)
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
            gmsh.model.mesh.createGeometry()
            gmsh.model.mesh.createTopology(True, False)
            try:
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
            "Real OCC backend currently implemented for gmsh_thin_sheet_aircraft_assembly and gmsh_thin_sheet_surface.",
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
    gmsh_log_path = mesh_dir / "gmsh_log.txt"
    mesh2d_watchdog_path = mesh_dir / "mesh2d_watchdog.json"
    mesh2d_watchdog_sample_path = mesh_dir / "mesh2d_watchdog_sample.txt"
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
                "gmsh_log": str(gmsh_log_path),
                "mesh2d_watchdog": str(mesh2d_watchdog_path),
                "mesh2d_watchdog_sample": str(mesh2d_watchdog_sample_path),
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
    mesh2d_watchdog: Dict[str, Any] | None = None
    plc_probe: Dict[str, Any] | None = None
    surface_repair_result: Dict[str, Any] | None = None
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.Binary", 0)
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
                "normalized STEP did not import any OCC volumes for thin_sheet_aircraft_assembly."
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
        reference_length = _resolve_sizing_reference_length(handle, config)

        fluid_group = gmsh.model.addPhysicalGroup(3, fluid_volume_tags)
        gmsh.model.setPhysicalName(3, fluid_group, "fluid")
        aircraft_group = gmsh.model.addPhysicalGroup(2, aircraft_surface_tags)
        gmsh.model.setPhysicalName(2, aircraft_group, "aircraft")
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
        gmsh.model.setPhysicalName(2, farfield_group, "farfield")

        field_info = _configure_mesh_field(gmsh, aircraft_surface_tags, aircraft_curve_tags, reference_length, config)
        metadata["mesh_field"] = field_info
        surface_patch_diagnostics = _collect_surface_patch_diagnostics(
            gmsh,
            surface_tags=aircraft_surface_tags,
            reference_length=reference_length,
            near_body_size=float(field_info["near_body_size"]),
        )
        _json_write(surface_patch_diagnostics_path, surface_patch_diagnostics)
        metadata["surface_patch_diagnostics"] = {
            "artifact": str(surface_patch_diagnostics_path),
            "surface_count": int(surface_patch_diagnostics["surface_count"]),
            "curve_count": int(surface_patch_diagnostics["curve_count"]),
            "suspicious_surface_tags": [int(entry["tag"]) for entry in surface_patch_diagnostics["suspicious_surfaces"][:12]],
            "shortest_curve_tags": [int(entry["tag"]) for entry in surface_patch_diagnostics["shortest_curves"][:20]],
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
            surface_patch_lookup={
                int(record["tag"]): record
                for record in surface_patch_diagnostics["surface_records"]
            },
        )
        metadata["mesh2d_watchdog"] = {
            "artifact": str(mesh2d_watchdog_path),
            "sample_artifact": str(mesh2d_watchdog_sample_path),
            "status": mesh2d_watchdog["status"],
            "timeout_seconds": mesh2d_watchdog["timeout_seconds"],
            "triggered_at_elapsed_sec": mesh2d_watchdog.get("triggered_at_elapsed_sec"),
            "completed_elapsed_sec": mesh2d_watchdog.get("completed_elapsed_sec"),
            "last_meshing_surface_tag": mesh2d_watchdog.get("last_meshing_surface_tag"),
        }
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

        if config.mesh_dim == 3:
            try:
                gmsh.model.mesh.generate(3)
            except Exception as exc:
                logger_messages = [str(message) for message in gmsh.logger.get()]
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
                        mesh_stats = surface_repair_result["mesh_stats"]
                        body_bounds_dict = _bounds_dict(*body_bounds)
                        if unit_normalization is None:
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
                        artifacts = MeshArtifactBundle(
                            mesh=mesh_path,
                            mesh_metadata=metadata_path,
                            marker_summary=marker_summary_path,
                            surface_mesh_2d=surface_mesh_path if surface_mesh_path.exists() else None,
                            surface_patch_diagnostics=surface_patch_diagnostics_path if surface_patch_diagnostics_path.exists() else None,
                            gmsh_log=gmsh_log_path,
                            mesh2d_watchdog=mesh2d_watchdog_path if mesh2d_watchdog_path.exists() else None,
                            mesh2d_watchdog_sample=mesh2d_watchdog_sample_path if mesh2d_watchdog_sample_path.exists() else None,
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
                        metadata["physical_groups"] = physical_groups
                        metadata["marker_summary"] = marker_summary
                        metadata["mesh"] = {
                            "format": "msh",
                            "mesh_dim": config.mesh_dim,
                            **mesh_stats,
                        }
                        metadata["artifacts"] = {
                            "mesh": str(mesh_path),
                            "mesh_metadata": str(metadata_path),
                            "marker_summary": str(marker_summary_path),
                            "surface_mesh_2d": str(surface_mesh_path) if surface_mesh_path.exists() else None,
                            "surface_patch_diagnostics": str(surface_patch_diagnostics_path) if surface_patch_diagnostics_path.exists() else None,
                            "gmsh_log": str(gmsh_log_path),
                            "mesh2d_watchdog": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
                            "mesh2d_watchdog_sample": (
                                str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None
                            ),
                            "plc_probe": str(plc_probe_path) if plc_probe_path.exists() else None,
                            "surface_cleanup_report": str(surface_cleanup_report_path) if surface_cleanup_report_path.exists() else None,
                            "discrete_reparam_report": str(discrete_reparam_report_path) if discrete_reparam_report_path.exists() else None,
                            "retry_mesh_metadata": str(retry_mesh_metadata_path) if retry_mesh_metadata_path.exists() else None,
                            "classify_angle_probe": str(classify_angle_probe_path) if classify_angle_probe_path.exists() else None,
                        }
                        _json_write(metadata_path, metadata)
                        _json_write(marker_summary_path, marker_summary)
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
                raise
        gmsh.write(str(mesh_path))

        physical_groups = {
            "fluid": _physical_group_summary(gmsh, 3, fluid_group),
            "aircraft": _physical_group_summary(gmsh, 2, aircraft_group),
            "farfield": _physical_group_summary(gmsh, 2, farfield_group),
        }
        marker_summary = {
            name: physical_groups[name]
            for name in ("aircraft", "farfield")
        }
        mesh_stats = _mesh_stats(gmsh)
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
        artifacts = MeshArtifactBundle(
            mesh=mesh_path,
            mesh_metadata=metadata_path,
            marker_summary=marker_summary_path,
            surface_mesh_2d=surface_mesh_path if surface_mesh_path.exists() else None,
            surface_patch_diagnostics=surface_patch_diagnostics_path if surface_patch_diagnostics_path.exists() else None,
            gmsh_log=gmsh_log_path,
            mesh2d_watchdog=mesh2d_watchdog_path if mesh2d_watchdog_path.exists() else None,
            mesh2d_watchdog_sample=mesh2d_watchdog_sample_path if mesh2d_watchdog_sample_path.exists() else None,
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
        _json_write(metadata_path, metadata)
        _json_write(marker_summary_path, marker_summary)

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
            "backend_capability": handoff.backend_capability,
            "meshing_route": handoff.meshing_route,
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
                "gmsh_log": str(gmsh_log_path),
                "mesh2d_watchdog": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
                "mesh2d_watchdog_sample": (
                    str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None
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
        metadata["error"] = final_error
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
        metadata["artifacts"] = {
            "mesh": str(mesh_path),
            "mesh_metadata": str(metadata_path),
            "marker_summary": str(marker_summary_path),
            "surface_mesh_2d": str(surface_mesh_path) if surface_mesh_path.exists() else None,
            "surface_patch_diagnostics": str(surface_patch_diagnostics_path) if surface_patch_diagnostics_path.exists() else None,
            "gmsh_log": str(gmsh_log_path),
            "mesh2d_watchdog": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
            "mesh2d_watchdog_sample": (
                str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None
            ),
            "plc_probe": str(plc_probe_path) if plc_probe_path.exists() else None,
            "surface_cleanup_report": str(surface_cleanup_report_path) if surface_cleanup_report_path.exists() else None,
            "discrete_reparam_report": str(discrete_reparam_report_path) if discrete_reparam_report_path.exists() else None,
            "retry_mesh_metadata": str(retry_mesh_metadata_path) if retry_mesh_metadata_path.exists() else None,
            "classify_angle_probe": str(classify_angle_probe_path) if classify_angle_probe_path.exists() else None,
        }
        _json_write(metadata_path, metadata)
        _json_write(marker_summary_path, marker_summary)
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
                "surface_mesh_2d": str(surface_mesh_path) if surface_mesh_path.exists() else None,
                "surface_patch_diagnostics": str(surface_patch_diagnostics_path) if surface_patch_diagnostics_path.exists() else None,
                "gmsh_log": str(gmsh_log_path),
                "mesh2d_watchdog": str(mesh2d_watchdog_path) if mesh2d_watchdog_path.exists() else None,
                "mesh2d_watchdog_sample": (
                    str(mesh2d_watchdog_sample_path) if mesh2d_watchdog_sample_path.exists() else None
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
