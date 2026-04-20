from __future__ import annotations

from typing import Dict, Any

from ..dispatch import default_family_for_component, supported_families_for_component, family_for_route
from ..schema import (
    GeometryClassification,
    GeometryHandle,
    GeometryValidationResult,
    MeshJobConfig,
)


SUPPORTED_SUFFIXES = {".step", ".stp", ".iges", ".igs"}


def classify_geometry_family(
    handle: GeometryHandle,
    config: MeshJobConfig,
) -> GeometryClassification:
    if config.geometry_family is not None:
        geometry_family = config.geometry_family
        inferred_family = None
        provenance = "config.geometry_family"
        notes = ["geometry family declared in config"]
    elif config.meshing_route is not None:
        geometry_family = family_for_route(config.meshing_route)
        inferred_family = geometry_family
        provenance = "config.meshing_route"
        notes = ["geometry family derived from explicit meshing route"]
    elif handle.provider_result is not None and handle.provider_result.geometry_family_hint is not None:
        geometry_family = handle.provider_result.geometry_family_hint
        inferred_family = geometry_family
        provenance = "provider.geometry_family_hint"
        notes = ["geometry family derived from provider hint"]
    else:
        geometry_family = default_family_for_component(config.component)
        inferred_family = geometry_family
        provenance = "component_family_default"
        notes = ["geometry family derived from component default family map"]

    notes.append(f"component={config.component}")
    notes.append(f"geometry_source={handle.geometry_source}")
    return GeometryClassification(
        geometry_source=handle.geometry_source,
        geometry_provider=handle.provider,
        declared_family=config.geometry_family,
        inferred_family=inferred_family,
        geometry_family=geometry_family,
        provenance=provenance,
        notes=notes,
    )


def validate_component_geometry(
    handle: GeometryHandle,
    classification: GeometryClassification,
    config: MeshJobConfig,
) -> GeometryValidationResult:
    provider_ready = True
    if handle.provider_result is not None:
        provider_ready = handle.provider_result.status == "materialized"
    suffix_ok = handle.suffix in SUPPORTED_SUFFIXES
    exists_ok = handle.exists
    supported_families = supported_families_for_component(config.component)
    component_family_ok = classification.geometry_family in supported_families

    failure_code = None
    if not provider_ready:
        failure_code = "geometry_provider_not_materialized"
    elif not exists_ok:
        failure_code = "geometry_missing"
    elif not suffix_ok:
        failure_code = "geometry_suffix_unsupported"
    elif not component_family_ok:
        failure_code = "geometry_family_component_mismatch"

    notes = [
        "Replace stub validation with provider-aware topology checks.",
        f"component={config.component}",
        f"geometry_family={classification.geometry_family}",
    ]
    return GeometryValidationResult(
        ok=bool(provider_ready and suffix_ok and exists_ok and component_family_ok),
        exists_ok=exists_ok,
        suffix_ok=suffix_ok,
        component_family_ok=component_family_ok,
        provider_ready=provider_ready,
        geometry_source=classification.geometry_source,
        geometry_provider=handle.provider,
        geometry_family=classification.geometry_family,
        failure_code=failure_code,
        supported_suffixes=sorted(SUPPORTED_SUFFIXES),
        supported_families=supported_families,
        notes=notes,
    )


def validate_component_geometry_stub(geom: Dict[str, Any], config: MeshJobConfig) -> Dict[str, Any]:
    suffix_ok = geom["suffix"] in SUPPORTED_SUFFIXES
    exists_ok = geom["exists"]
    return {
        "ok": bool(suffix_ok and exists_ok),
        "exists_ok": exists_ok,
        "suffix_ok": suffix_ok,
        "notes": [
            "Replace this stub with Gmsh OCC import + topology checks.",
            f"component={config.component}",
        ],
    }
