from __future__ import annotations

import json

from ..schema import (
    GeometryProviderRequest,
    GeometryProviderResult,
    GeometryTopologyMetadata,
)


def materialize(request: GeometryProviderRequest) -> GeometryProviderResult:
    request.staging_dir.mkdir(parents=True, exist_ok=True)
    provider_log = request.staging_dir / "provider_log.json"
    provider_log.write_text(
        json.dumps(
            {
                "provider": "esp_rebuilt",
                "provider_stage": "experimental",
                "status": "not_materialized",
                "source_path": str(request.source_path),
                "reason": "ESP/OpenCSM remains an experimental provider contract in this round.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return GeometryProviderResult(
        provider="esp_rebuilt",
        provider_stage="experimental",
        status="not_materialized",
        geometry_source="esp_rebuilt",
        source_path=request.source_path,
        geometry_family_hint=request.geometry_family_hint,
        provider_version="experimental-contract",
        topology=GeometryTopologyMetadata(
            representation="provider_deferred",
            source_kind=request.source_path.suffix.lstrip(".") or "unknown",
            units=None if request.units_hint == "auto" else request.units_hint,
            notes=["experimental provider contract only; no materialization in this round"],
        ),
        artifacts={"provider_log": provider_log},
        provenance={
            "status": "experimental_not_materialized",
            "decision": "keep ESP/OpenCSM experimental until runtime and meshing evidence justify promotion",
        },
        warnings=["normalized geometry artifact not produced"],
    )
