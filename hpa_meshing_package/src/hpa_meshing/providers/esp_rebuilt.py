from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..schema import (
    GeometryProviderRequest,
    GeometryProviderResult,
    GeometryTopologyMetadata,
)
from .esp_pipeline import EspMaterializationResult, materialize_with_esp
from .esp_runtime import detect_esp_runtime


def _write_provider_log(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _failed_result(
    *,
    request: GeometryProviderRequest,
    provider_log: Path,
    provider_version: str,
    representation: str,
    source_kind: str,
    resolved_units: Optional[str],
    notes: List[str],
    warnings: List[str],
    provenance: Dict[str, Any],
    artifacts: Optional[Dict[str, Path]] = None,
) -> GeometryProviderResult:
    artifact_map: Dict[str, Path] = {"provider_log": provider_log}
    if artifacts:
        artifact_map.update(artifacts)
    return GeometryProviderResult(
        provider="esp_rebuilt",
        provider_stage="experimental",
        status="failed",
        geometry_source="esp_rebuilt",
        source_path=request.source_path,
        geometry_family_hint=request.geometry_family_hint,
        provider_version=provider_version,
        topology=GeometryTopologyMetadata(
            representation=representation,
            source_kind=source_kind,
            units=resolved_units,
            notes=notes,
        ),
        artifacts=artifact_map,
        provenance=provenance,
        warnings=warnings,
        notes=[],
    )


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
        _write_provider_log(
            provider_log,
            {
                "provider": "esp_rebuilt",
                "provider_stage": "experimental",
                "status": "failed",
                "failure_code": "esp_runtime_missing",
                "source_path": str(request.source_path),
                "runtime": runtime.to_dict(),
                "reason": reason,
            },
        )
        return _failed_result(
            request=request,
            provider_log=provider_log,
            provider_version="esp-runtime-missing",
            representation="provider_failed",
            source_kind=source_kind,
            resolved_units=resolved_units,
            notes=[reason],
            warnings=[reason],
            provenance={
                "failure_code": "esp_runtime_missing",
                "runtime": runtime.to_dict(),
            },
        )

    try:
        pipeline_result = materialize_with_esp(
            source_path=request.source_path,
            staging_dir=request.staging_dir,
        )
    except NotImplementedError as exc:
        reason = f"ESP materialization pipeline not implemented: {exc}"
        _write_provider_log(
            provider_log,
            {
                "provider": "esp_rebuilt",
                "provider_stage": "experimental",
                "status": "failed",
                "failure_code": "esp_pipeline_not_implemented",
                "source_path": str(request.source_path),
                "runtime": runtime.to_dict(),
                "reason": reason,
            },
        )
        return _failed_result(
            request=request,
            provider_log=provider_log,
            provider_version="esp-pipeline-not-implemented",
            representation="provider_failed",
            source_kind=source_kind,
            resolved_units=resolved_units,
            notes=[reason],
            warnings=[reason],
            provenance={
                "failure_code": "esp_pipeline_not_implemented",
                "runtime": runtime.to_dict(),
            },
        )

    return _result_from_pipeline(
        request=request,
        provider_log=provider_log,
        runtime_payload=runtime.to_dict(),
        source_kind=source_kind,
        resolved_units=resolved_units,
        pipeline_result=pipeline_result,
    )


def _result_from_pipeline(
    *,
    request: GeometryProviderRequest,
    provider_log: Path,
    runtime_payload: Dict[str, Any],
    source_kind: str,
    resolved_units: Optional[str],
    pipeline_result: EspMaterializationResult,
) -> GeometryProviderResult:
    provider_version = pipeline_result.provider_version or "esp-rebuilt-unknown"
    pipeline_artifacts: Dict[str, Path] = {}
    if pipeline_result.normalized_geometry_path is not None:
        pipeline_artifacts["normalized_geometry"] = pipeline_result.normalized_geometry_path
    if pipeline_result.topology_report_path is not None:
        pipeline_artifacts["topology_report"] = pipeline_result.topology_report_path
    if pipeline_result.command_log_path is not None:
        pipeline_artifacts["command_log"] = pipeline_result.command_log_path
    if pipeline_result.script_path is not None:
        pipeline_artifacts["esp_script"] = pipeline_result.script_path

    if pipeline_result.status != "success":
        failure_code = pipeline_result.failure_code or "esp_pipeline_failed"
        notes = list(pipeline_result.notes) or [f"ESP pipeline failed: {failure_code}"]
        warnings = list(pipeline_result.warnings) or [f"ESP pipeline failed: {failure_code}"]
        _write_provider_log(
            provider_log,
            {
                "provider": "esp_rebuilt",
                "provider_stage": "experimental",
                "status": "failed",
                "failure_code": failure_code,
                "source_path": str(request.source_path),
                "runtime": runtime_payload,
                "pipeline_notes": list(pipeline_result.notes),
                "pipeline_warnings": list(pipeline_result.warnings),
            },
        )
        return _failed_result(
            request=request,
            provider_log=provider_log,
            provider_version=provider_version,
            representation="provider_failed",
            source_kind=source_kind,
            resolved_units=resolved_units,
            notes=notes,
            warnings=warnings,
            provenance={
                "failure_code": failure_code,
                "runtime": runtime_payload,
            },
            artifacts=pipeline_artifacts,
        )

    _write_provider_log(
        provider_log,
        {
            "provider": "esp_rebuilt",
            "provider_stage": "experimental",
            "status": "materialized",
            "source_path": str(request.source_path),
            "runtime": runtime_payload,
            "normalized_geometry_path": (
                str(pipeline_result.normalized_geometry_path)
                if pipeline_result.normalized_geometry_path is not None
                else None
            ),
            "topology_report_path": (
                str(pipeline_result.topology_report_path)
                if pipeline_result.topology_report_path is not None
                else None
            ),
        },
    )
    artifact_map: Dict[str, Path] = {"provider_log": provider_log}
    artifact_map.update(pipeline_artifacts)
    return GeometryProviderResult(
        provider="esp_rebuilt",
        provider_stage="experimental",
        status="materialized",
        geometry_source="esp_rebuilt",
        source_path=request.source_path,
        normalized_geometry_path=pipeline_result.normalized_geometry_path,
        geometry_family_hint=request.geometry_family_hint,
        provider_version=provider_version,
        topology=GeometryTopologyMetadata(
            representation="brep_component_volumes",
            source_kind=source_kind,
            units=resolved_units,
            notes=list(pipeline_result.notes),
        ),
        artifacts=artifact_map,
        provenance={
            "runtime": runtime_payload,
            "pipeline_status": pipeline_result.status,
        },
        warnings=list(pipeline_result.warnings),
        notes=[],
    )
