"""Shared provenance helpers for producer and autoresearch traceability."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

TRACEABLE_INPUT_SOURCE_KEYS = ("config", "design_report", "v2m_summary_json")
RUN_FINGERPRINT_VERSION = "input_definition_v1"
EXPERIMENT_GOVERNANCE_VERSION = "v1"


def build_input_source_record(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None

    resolved = Path(path).expanduser().resolve()
    return {
        "path": str(resolved),
        "exists": resolved.exists(),
        "sha256": _file_sha256(resolved),
    }


def build_joint_decision_cli_overrides(
    *,
    primary_margin_floor_mm: float | None,
    balanced_min_margin_mm: float | None,
    balanced_max_mass_delta_kg: float | None,
    conservative_mode: str | None,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if primary_margin_floor_mm is not None:
        overrides["primary_margin_floor_mm"] = float(primary_margin_floor_mm)
    if balanced_min_margin_mm is not None:
        overrides["balanced_min_margin_mm"] = float(balanced_min_margin_mm)
    if balanced_max_mass_delta_kg is not None:
        overrides["balanced_max_mass_delta_kg"] = float(balanced_max_mass_delta_kg)
    if conservative_mode is not None:
        overrides["conservative_mode"] = str(conservative_mode)
    return overrides


def build_joint_decision_input_provenance(
    *,
    config_path: Path | str | None,
    design_report_path: Path | str | None,
    v2m_summary_json_path: Path | str | None,
    output_dir: Path | str,
    primary_margin_floor_mm: float | None,
    balanced_min_margin_mm: float | None,
    balanced_max_mass_delta_kg: float | None,
    conservative_mode: str | None,
) -> dict[str, Any]:
    return {
        "config": build_input_source_record(config_path),
        "design_report": build_input_source_record(design_report_path),
        "v2m_summary_json": build_input_source_record(v2m_summary_json_path),
        "output_dir": str(Path(output_dir).expanduser().resolve()),
        "producer_cli_overrides": build_joint_decision_cli_overrides(
            primary_margin_floor_mm=primary_margin_floor_mm,
            balanced_min_margin_mm=balanced_min_margin_mm,
            balanced_max_mass_delta_kg=balanced_max_mass_delta_kg,
            conservative_mode=conservative_mode,
        ),
    }


def build_run_fingerprint_payload(
    *,
    producer_name: str | None,
    producer_interface_version: str | None,
    decision_schema_name: str | None,
    decision_schema_version: str | None,
    input_provenance: dict[str, Any] | None,
    producer_cli_overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_input_provenance = input_provenance or {}
    return {
        "producer_name": producer_name,
        "producer_interface_version": producer_interface_version,
        "decision_schema_name": decision_schema_name,
        "decision_schema_version": decision_schema_version,
        "input_sources": {
            key: _normalize_input_source(normalized_input_provenance.get(key))
            for key in TRACEABLE_INPUT_SOURCE_KEYS
        },
        "producer_cli_overrides": _normalize_mapping(
            producer_cli_overrides
            if producer_cli_overrides is not None
            else normalized_input_provenance.get("producer_cli_overrides")
        ),
    }


def compute_run_fingerprint(
    *,
    producer_name: str | None,
    producer_interface_version: str | None,
    decision_schema_name: str | None,
    decision_schema_version: str | None,
    input_provenance: dict[str, Any] | None,
    producer_cli_overrides: dict[str, Any] | None,
) -> str | None:
    payload = build_run_fingerprint_payload(
        producer_name=producer_name,
        producer_interface_version=producer_interface_version,
        decision_schema_name=decision_schema_name,
        decision_schema_version=decision_schema_version,
        input_provenance=input_provenance,
        producer_cli_overrides=producer_cli_overrides,
    )
    if not any(payload["input_sources"].values()):
        return None
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:12]


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _normalize_input_source(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    path = value.get("path")
    exists = value.get("exists")
    sha_value = value.get("sha256")
    if path is None and exists is None and sha_value is None:
        return None
    return {
        "path": None if path is None else str(path),
        "exists": None if exists is None else bool(exists),
        "sha256": None if sha_value is None else str(sha_value),
    }


def _normalize_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        normalized[str(key)] = item
    return normalized


def _file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None

    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
