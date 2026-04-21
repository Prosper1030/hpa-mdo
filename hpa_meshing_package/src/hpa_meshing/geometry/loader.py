from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from ..dispatch import default_family_for_component
from ..providers import materialize_geometry
from ..schema import GeometryProviderRequest
from ..schema import GeometryHandle, MeshJobConfig


def materialize_geometry_with_provider(path: Path, config: MeshJobConfig):
    geometry_family_hint = config.geometry_family or default_family_for_component(config.component)
    request = GeometryProviderRequest(
        provider=config.geometry_provider,
        source_path=path,
        component=config.component,
        staging_dir=config.out_dir / "artifacts" / "providers" / config.geometry_provider,
        geometry_family_hint=geometry_family_hint,
        units_hint=config.units,
        metadata=config.metadata,
    )
    return materialize_geometry(request)


def load_geometry(path: Path, config: MeshJobConfig) -> GeometryHandle:
    provider_result = None
    geometry_source = config.geometry_source
    geometry_path = path
    loader = "filesystem_stub"
    provider_status = None

    if config.geometry_provider is not None:
        provider_result = materialize_geometry_with_provider(path, config)
        geometry_source = provider_result.geometry_source
        provider_status = provider_result.status
        loader = f"provider:{provider_result.provider}"
        if provider_result.normalized_geometry_path is not None:
            geometry_path = provider_result.normalized_geometry_path

    return GeometryHandle(
        source_path=path,
        path=geometry_path,
        exists=geometry_path.exists(),
        suffix=geometry_path.suffix.lower(),
        loader=loader,
        geometry_source=geometry_source,
        declared_family=config.geometry_family,
        component=config.component,
        provider=config.geometry_provider,
        provider_status=provider_status,
        provider_result=provider_result,
        metadata=config.metadata,
    )


def load_geometry_stub(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "suffix": path.suffix.lower(),
        "loader": "stub",
    }
