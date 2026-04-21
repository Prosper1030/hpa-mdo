from __future__ import annotations

import json

from ..schema import (
    GeometryProviderRequest,
    GeometryProviderResult,
    GeometryTopologyMetadata,
)
from .esp_runtime import detect_esp_runtime


def materialize(request: GeometryProviderRequest) -> GeometryProviderResult:
    request.staging_dir.mkdir(parents=True, exist_ok=True)
    provider_log = request.staging_dir / "provider_log.json"
    runtime = detect_esp_runtime()
    source_kind = request.source_path.suffix.lstrip(".") or "unknown"
    resolved_units = None if request.units_hint == "auto" else request.units_hint

    if not runtime.available:
        reason = (
            "ESP/OpenCSM runtime not found on PATH; missing binaries: "
            + ", ".join(runtime.missing)
        )
        provider_log.write_text(
            json.dumps(
                {
                    "provider": "esp_rebuilt",
                    "provider_stage": "experimental",
                    "status": "failed",
                    "failure_code": "esp_runtime_missing",
                    "source_path": str(request.source_path),
                    "runtime": runtime.to_dict(),
                    "reason": reason,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return GeometryProviderResult(
            provider="esp_rebuilt",
            provider_stage="experimental",
            status="failed",
            geometry_source="esp_rebuilt",
            source_path=request.source_path,
            geometry_family_hint=request.geometry_family_hint,
            provider_version="esp-runtime-missing",
            topology=GeometryTopologyMetadata(
                representation="provider_failed",
                source_kind=source_kind,
                units=resolved_units,
                notes=[reason],
            ),
            artifacts={"provider_log": provider_log},
            provenance={
                "failure_code": "esp_runtime_missing",
                "runtime": runtime.to_dict(),
            },
            warnings=[reason],
            notes=[],
        )

    provider_log.write_text(
        json.dumps(
            {
                "provider": "esp_rebuilt",
                "provider_stage": "experimental",
                "status": "not_materialized",
                "source_path": str(request.source_path),
                "runtime": runtime.to_dict(),
                "reason": "ESP runtime detected but materialization pipeline not yet implemented.",
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
        provider_version="esp-runtime-present-pipeline-pending",
        topology=GeometryTopologyMetadata(
            representation="provider_deferred",
            source_kind=source_kind,
            units=resolved_units,
            notes=[
                "ESP runtime detected but materialization pipeline not yet wired.",
            ],
        ),
        artifacts={"provider_log": provider_log},
        provenance={
            "status": "runtime_ready_pipeline_pending",
            "runtime": runtime.to_dict(),
        },
        warnings=["normalized geometry artifact not produced"],
    )
