from __future__ import annotations

from typing import Dict, Any

from ..dispatch import resolve_meshing_route, route_spec
from ..schema import GeometryClassification, GeometryHandle, MeshJobConfig, MeshRecipe


def build_recipe(
    geom: GeometryHandle,
    classification: GeometryClassification,
    config: MeshJobConfig,
) -> MeshRecipe:
    route = resolve_meshing_route(
        classification.geometry_family,
        meshing_route=config.meshing_route,
        backend_capability=config.backend_capability,
    )
    spec = route_spec(route.meshing_route)
    family_features = list(spec["family_features"])
    if config.component in {"main_wing", "tail_wing", "horizontal_tail", "vertical_tail"}:
        family_features.append("component_profile:lifting_surface")
    if config.component == "fairing_vented":
        family_features.append("component_profile:perforation_aware")
    if config.component == "aircraft_assembly":
        family_features.append("component_profile:assembly_orchestration")

    return MeshRecipe(
        name=f"{route.meshing_route}:{config.component}",
        component=config.component,
        geometry=str(geom.path),
        geometry_source=classification.geometry_source,
        geometry_provider=geom.provider,
        geometry_family=classification.geometry_family,
        meshing_route=route.meshing_route,
        backend=route.backend,
        backend_capability=route.backend_capability,
        route_provenance=route.route_provenance,
        family_features=family_features,
        farfield_enabled=config.farfield.enabled,
        boundary_layer_enabled=config.boundary_layer.enabled,
        global_min_size=config.global_min_size,
        global_max_size=config.global_max_size,
    )


def build_recipe_stub(geom: Dict[str, Any], config: MeshJobConfig) -> Dict[str, Any]:
    return {
        "name": f"{config.component}_v1_stub",
        "component": config.component,
        "geometry": geom["path"],
        "farfield_enabled": config.farfield.enabled,
        "boundary_layer_enabled": config.boundary_layer.enabled,
        "global_min_size": config.global_min_size,
        "global_max_size": config.global_max_size,
    }
