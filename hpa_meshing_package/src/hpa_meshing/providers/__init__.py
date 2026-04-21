from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict

from ..schema import (
    GeometryProviderRequest,
    GeometryProviderResult,
    GeometryProviderStageType,
    GeometryProviderType,
)
from .esp_rebuilt import materialize as materialize_esp_rebuilt
from .openvsp_surface_intersection import materialize as materialize_openvsp_surface_intersection


Materializer = Callable[[GeometryProviderRequest], GeometryProviderResult]


@dataclass(frozen=True)
class GeometryProviderSpec:
    name: GeometryProviderType
    stage: GeometryProviderStageType
    description: str
    materializer: Materializer


PROVIDER_REGISTRY: Dict[GeometryProviderType, GeometryProviderSpec] = {
    "openvsp_surface_intersection": GeometryProviderSpec(
        name="openvsp_surface_intersection",
        stage="v1",
        description="OpenVSP SurfaceIntersection trimmed STEP normalization.",
        materializer=materialize_openvsp_surface_intersection,
    ),
    "esp_rebuilt": GeometryProviderSpec(
        name="esp_rebuilt",
        stage="experimental",
        description="Experimental ESP/OpenCSM provider contract placeholder.",
        materializer=materialize_esp_rebuilt,
    ),
}


def get_provider(name: GeometryProviderType) -> GeometryProviderSpec:
    return PROVIDER_REGISTRY[name]


def materialize_geometry(request: GeometryProviderRequest) -> GeometryProviderResult:
    return get_provider(request.provider).materializer(request)
