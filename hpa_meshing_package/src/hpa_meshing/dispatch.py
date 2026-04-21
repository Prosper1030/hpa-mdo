from __future__ import annotations

from typing import Dict, List, cast

from .errors import TopologyUnsupportedError
from .schema import (
    BackendCapabilityType,
    ComponentType,
    GeometryFamilyType,
    MeshingRouteResolution,
    MeshingRouteType,
)


COMPONENT_DEFAULT_FAMILIES: Dict[ComponentType, GeometryFamilyType] = {
    "main_wing": "thin_sheet_lifting_surface",
    "tail_wing": "thin_sheet_lifting_surface",
    "horizontal_tail": "thin_sheet_lifting_surface",
    "vertical_tail": "thin_sheet_lifting_surface",
    "fairing_solid": "closed_solid",
    "fairing_vented": "perforated_solid",
    "aircraft_assembly": "thin_sheet_aircraft_assembly",
}

COMPONENT_SUPPORTED_FAMILIES: Dict[ComponentType, List[GeometryFamilyType]] = {
    "main_wing": ["thin_sheet_lifting_surface"],
    "tail_wing": ["thin_sheet_lifting_surface"],
    "horizontal_tail": ["thin_sheet_lifting_surface"],
    "vertical_tail": ["thin_sheet_lifting_surface"],
    "fairing_solid": ["closed_solid"],
    "fairing_vented": ["perforated_solid"],
    "aircraft_assembly": ["thin_sheet_aircraft_assembly"],
}

ROUTE_REGISTRY: Dict[MeshingRouteType, Dict[str, object]] = {
    "gmsh_closed_solid_volume": {
        "geometry_family": "closed_solid",
        "backend": "gmsh",
        "backend_capability": "occ_closed_solid_meshing",
        "family_features": [
            "watertight_volume",
            "farfield_volume",
            "solid_wall_marker_preservation",
        ],
    },
    "gmsh_perforated_solid_volume": {
        "geometry_family": "perforated_solid",
        "backend": "gmsh",
        "backend_capability": "occ_perforated_solid_meshing",
        "family_features": [
            "watertight_volume_with_openings",
            "hole_edge_refinement",
            "marker_preservation_for_perforations",
        ],
    },
    "gmsh_thin_sheet_surface": {
        "geometry_family": "thin_sheet_lifting_surface",
        "backend": "gmsh",
        "backend_capability": "sheet_lifting_surface_meshing",
        "family_features": [
            "sheet_surface_meshing",
            "lifting_surface_edge_refinement",
            "farfield_envelope_generation",
        ],
    },
    "gmsh_thin_sheet_aircraft_assembly": {
        "geometry_family": "thin_sheet_aircraft_assembly",
        "backend": "gmsh",
        "backend_capability": "sheet_aircraft_assembly_meshing",
        "family_features": [
            "assembly_sheet_meshing",
            "multi_surface_tagging",
            "aircraft_envelope_generation",
        ],
    },
}

DEFAULT_ROUTE_BY_FAMILY: Dict[GeometryFamilyType, MeshingRouteType] = {
    cast(GeometryFamilyType, spec["geometry_family"]): route
    for route, spec in ROUTE_REGISTRY.items()
}


def default_family_for_component(component: ComponentType) -> GeometryFamilyType:
    return COMPONENT_DEFAULT_FAMILIES[component]


def supported_families_for_component(component: ComponentType) -> List[GeometryFamilyType]:
    return COMPONENT_SUPPORTED_FAMILIES[component]


def family_for_route(route: MeshingRouteType) -> GeometryFamilyType:
    return cast(GeometryFamilyType, ROUTE_REGISTRY[route]["geometry_family"])


def route_spec(route: MeshingRouteType) -> Dict[str, object]:
    return ROUTE_REGISTRY[route]


def resolve_meshing_route(
    geometry_family: GeometryFamilyType,
    meshing_route: MeshingRouteType | None = None,
    backend_capability: BackendCapabilityType | None = None,
) -> MeshingRouteResolution:
    if meshing_route is None:
        meshing_route = DEFAULT_ROUTE_BY_FAMILY[geometry_family]
        route_provenance = "geometry_family_registry"
    else:
        route_provenance = "config.meshing_route"

    spec = route_spec(meshing_route)
    route_family = cast(GeometryFamilyType, spec["geometry_family"])
    route_capability = cast(BackendCapabilityType, spec["backend_capability"])
    route_backend = cast(str, spec["backend"])

    if route_family != geometry_family:
        raise TopologyUnsupportedError(
            f"route {meshing_route} expects family {route_family}, got {geometry_family}"
        )

    if backend_capability is not None and route_capability != backend_capability:
        raise TopologyUnsupportedError(
            "backend capability hint does not match route registry: "
            f"{backend_capability} != {route_capability}"
        )

    notes = [
        f"geometry_family={geometry_family}",
        f"backend={route_backend}",
        f"backend_capability={route_capability}",
    ]
    return MeshingRouteResolution(
        meshing_route=meshing_route,
        backend="gmsh",
        backend_capability=route_capability,
        geometry_family=geometry_family,
        route_provenance=route_provenance,
        notes=notes,
    )
