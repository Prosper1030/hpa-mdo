from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable

from ..gmsh_runtime import GmshRuntimeError, load_gmsh
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


class GmshBackendError(RuntimeError):
    """Raised when the real Gmsh backend cannot produce a mesh artifact."""


def _json_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _configure_mesh_field(
    gmsh,
    aircraft_surface_tags: list[int],
    body_bounds: tuple[list[float], list[float]],
    config: MeshJobConfig,
) -> Dict[str, Any]:
    mins, maxs = body_bounds
    characteristic_length = max(
        maxs[0] - mins[0],
        maxs[1] - mins[1],
        maxs[2] - mins[2],
        1e-3,
    )
    near_body_size = config.global_min_size or max(characteristic_length * 0.08, 1e-3)
    farfield_size = config.global_max_size or max(characteristic_length * 0.35, near_body_size * 2.5)
    # Keep the transition band tied to the requested mesh sizes so finer study
    # presets refine a meaningfully smaller neighborhood instead of reusing the
    # same broad distance ramp for every tier.
    distance_min = max(near_body_size * 2.0, characteristic_length * 0.04)
    distance_max = max(
        distance_min + 6.0 * near_body_size,
        farfield_size * 2.5,
        characteristic_length * 0.35,
    )
    mesh_algorithm_2d = int(config.mesh_algorithm_2d) if config.mesh_algorithm_2d is not None else 6
    mesh_algorithm_3d = int(config.mesh_algorithm_3d) if config.mesh_algorithm_3d is not None else 1

    distance_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(distance_field, "FacesList", aircraft_surface_tags)

    threshold_field = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(threshold_field, "InField", distance_field)
    gmsh.model.mesh.field.setNumber(threshold_field, "SizeMin", near_body_size)
    gmsh.model.mesh.field.setNumber(threshold_field, "SizeMax", farfield_size)
    gmsh.model.mesh.field.setNumber(threshold_field, "DistMin", distance_min)
    gmsh.model.mesh.field.setNumber(threshold_field, "DistMax", distance_max)
    gmsh.model.mesh.field.setAsBackgroundMesh(threshold_field)

    gmsh.option.setNumber("Mesh.MeshSizeMin", near_body_size)
    gmsh.option.setNumber("Mesh.MeshSizeMax", farfield_size)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 0)
    gmsh.option.setNumber("Mesh.Algorithm", float(mesh_algorithm_2d))
    gmsh.option.setNumber("Mesh.Algorithm3D", float(mesh_algorithm_3d))

    return {
        "characteristic_length": characteristic_length,
        "near_body_size": near_body_size,
        "farfield_size": farfield_size,
        "distance_min": distance_min,
        "distance_max": distance_max,
        "mesh_size_from_points": 0,
        "mesh_size_from_curvature": 0,
        "mesh_size_extend_from_boundary": 0,
        "mesh_algorithm_2d": mesh_algorithm_2d,
        "mesh_algorithm_3d": mesh_algorithm_3d,
    }


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
            "Real OCC backend currently implemented only for gmsh_thin_sheet_aircraft_assembly.",
            f"loader={handle.loader}",
            f"mesh_dim={config.mesh_dim}",
        ],
    }


def _apply_thin_sheet_aircraft_assembly_route(
    recipe: MeshRecipe,
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        raise GmshBackendError(str(exc)) from exc
    mesh_dir = config.out_dir / "artifacts" / "mesh"
    mesh_path = mesh_dir / "mesh.msh"
    metadata_path = mesh_dir / "mesh_metadata.json"
    marker_summary_path = mesh_dir / "marker_summary.json"
    mesh_dir.mkdir(parents=True, exist_ok=True)

    gmsh_initialized = False
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.Binary", 0)
        gmsh.model.add(f"hpa_meshing_{uuid.uuid4().hex}")

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

        body_dim_tags, healing_summary = _heal_imported_bodies(gmsh, body_dim_tags)
        imported_surface_count = len(gmsh.model.getEntities(2))

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

        fluid_group = gmsh.model.addPhysicalGroup(3, fluid_volume_tags)
        gmsh.model.setPhysicalName(3, fluid_group, "fluid")
        aircraft_group = gmsh.model.addPhysicalGroup(2, aircraft_surface_tags)
        gmsh.model.setPhysicalName(2, aircraft_group, "aircraft")
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
        gmsh.model.setPhysicalName(2, farfield_group, "farfield")

        field_info = _configure_mesh_field(gmsh, aircraft_surface_tags, body_bounds, config)
        gmsh.model.mesh.generate(config.mesh_dim)
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
            **handoff.model_dump(mode="json"),
            "geometry": {
                "source_path": str(handle.source_path),
                "normalized_path": str(handle.path),
                "geometry_source": recipe.geometry_source,
                "loader": handle.loader,
                "provider": handle.provider,
                "provider_status": handle.provider_status,
                "provider_topology": (
                    handle.provider_result.topology.model_dump(mode="json")
                    if handle.provider_result is not None
                    else None
                ),
            },
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
            },
            "marker_summary": {},
            "mesh_stats": {},
            "error": str(exc),
            "notes": [
                "baseline OCC external-flow mesh failed",
                f"loader={handle.loader}",
                f"mesh_dim={config.mesh_dim}",
            ],
        }
    finally:
        if gmsh_initialized:
            gmsh.finalize()


def apply_recipe(
    recipe: MeshRecipe,
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    if recipe.meshing_route == REAL_OCC_ROUTE:
        return _apply_thin_sheet_aircraft_assembly_route(recipe, handle, config)
    return _placeholder_backend_result(recipe, handle, config)


def apply_recipe_stub(
    recipe: MeshRecipe,
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> Dict[str, Any]:
    return apply_recipe(recipe, handle, config)
