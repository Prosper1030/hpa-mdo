from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SURFACE_TRIANGLE_RELATIVE_DRIFT_LIMIT = 0.05
DEFAULT_VOLUME_ELEMENT_RELATIVE_DRIFT_LIMIT = 0.05


def _resolve_path(path_value: str | Path, source_root: Path | None) -> Path:
    path = Path(path_value)
    if path.is_absolute() or source_root is None:
        return path
    return (source_root / path).resolve()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _status_for_checks(*statuses: str) -> str:
    if any(status == "fail" for status in statuses):
        return "fail"
    if any(status == "warn" for status in statuses):
        return "warn"
    return "pass"


def _check(status: str, *, observed: dict[str, Any] | None = None, expected: dict[str, Any] | None = None, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "observed": observed or {},
        "expected": expected or {},
        "notes": notes or [],
    }


def _artifact_path(
    manifest: dict[str, Any],
    manifest_path: Path,
    artifact_key: str,
    fallback_relative_path: str,
) -> Path:
    artifacts = manifest.get("artifacts", {})
    artifact_value = artifacts.get(artifact_key) if isinstance(artifacts, dict) else None
    if isinstance(artifact_value, str) and artifact_value:
        return _resolve_path(artifact_value, manifest_path.parent)
    return manifest_path.parent / fallback_relative_path


def _relative_drift(expected: int | float, observed: int | float) -> float:
    if float(expected) == 0.0:
        return 0.0 if float(observed) == 0.0 else 1.0
    return abs(float(observed) - float(expected)) / abs(float(expected))


def evaluate_shell_v3_baseline_regression(
    manifest_path: str | Path,
    *,
    mesh_handoff_path: str | Path | None = None,
    source_root: Path | None = None,
    surface_triangle_relative_drift_limit: float = DEFAULT_SURFACE_TRIANGLE_RELATIVE_DRIFT_LIMIT,
    volume_element_relative_drift_limit: float = DEFAULT_VOLUME_ELEMENT_RELATIVE_DRIFT_LIMIT,
) -> dict[str, Any]:
    manifest_path = _resolve_path(manifest_path, source_root)
    manifest = _load_json(manifest_path)
    current_run = manifest.get("current_run", {})
    if not isinstance(current_run, dict):
        raise ValueError(f"baseline manifest missing current_run object: {manifest_path}")

    summary_path = manifest_path.with_name("shell_v3_quality_clean_baseline_summary.md")
    resolved_mesh_handoff_path = (
        _resolve_path(mesh_handoff_path, source_root)
        if mesh_handoff_path is not None
        else _artifact_path(
            manifest,
            manifest_path,
            "mesh_metadata_json",
            "artifacts/mesh/mesh_metadata.json",
        )
    )
    gmsh_log_path = _artifact_path(
        manifest,
        manifest_path,
        "gmsh_log_txt",
        "artifacts/mesh/gmsh_log.txt",
    )
    topology_report_path = _artifact_path(
        manifest,
        manifest_path,
        "topology_suppression_report_json",
        "artifacts/providers/esp_rebuilt/esp_runtime/topology_suppression_report.json",
    )

    mesh_handoff = _load_json(resolved_mesh_handoff_path)
    mesh_stats = mesh_handoff.get("mesh_stats", {})
    quality_metrics = mesh_handoff.get("quality_metrics", {})

    gmsh_log_text = gmsh_log_path.read_text(encoding="utf-8", errors="replace")
    topology_report = _load_json(topology_report_path)
    summary_exists = summary_path.exists()

    expected_surface_triangles = int(current_run.get("surface_triangle_count", 0) or 0)
    observed_surface_triangles = int(mesh_stats.get("surface_element_count", 0) or 0)
    expected_volume_elements = int(current_run.get("volume_element_count", 0) or 0)
    observed_volume_elements = int(mesh_stats.get("volume_element_count", 0) or 0)
    observed_ill_shaped = int(quality_metrics.get("ill_shaped_tet_count", 0) or 0)

    surface_triangle_drift = _relative_drift(expected_surface_triangles, observed_surface_triangles)
    volume_element_drift = _relative_drift(expected_volume_elements, observed_volume_elements)

    checks = {
        "manifest_readable": _check(
            "pass",
            observed={"path": str(manifest_path), "baseline_name": manifest.get("baseline_name")},
            expected={"baseline_name": "shell_v3_quality_clean_baseline"},
        ),
        "baseline_summary_readable": _check(
            "pass" if summary_exists else "fail",
            observed={"path": str(summary_path), "exists": summary_exists},
            expected={"exists": True},
        ),
        "mesh_handoff_readable": _check(
            "pass",
            observed={"path": str(resolved_mesh_handoff_path), "contract": mesh_handoff.get("contract")},
            expected={"contract": "mesh_handoff.v1"},
        ),
        "ill_shaped_tet_count": _check(
            "pass" if observed_ill_shaped == 0 else "fail",
            observed={
                "manifest_ill_shaped_tet_count": int(current_run.get("ill_shaped_tet_count", 0) or 0),
                "mesh_handoff_ill_shaped_tet_count": observed_ill_shaped,
            },
            expected={"ill_shaped_tet_count": 0},
        ),
        "surface_triangle_count": _check(
            "pass" if surface_triangle_drift <= surface_triangle_relative_drift_limit else "fail",
            observed={
                "manifest": expected_surface_triangles,
                "mesh_handoff": observed_surface_triangles,
                "relative_drift": surface_triangle_drift,
            },
            expected={"relative_drift_lte": surface_triangle_relative_drift_limit},
        ),
        "volume_element_count": _check(
            "pass" if volume_element_drift <= volume_element_relative_drift_limit else "fail",
            observed={
                "manifest": expected_volume_elements,
                "mesh_handoff": observed_volume_elements,
                "relative_drift": volume_element_drift,
            },
            expected={"relative_drift_lte": volume_element_relative_drift_limit},
        ),
        "gmsh_log": _check(
            "pass" if "No ill-shaped tets in the mesh" in gmsh_log_text else "fail",
            observed={"path": str(gmsh_log_path)},
            expected={"contains": "No ill-shaped tets in the mesh"},
        ),
        "topology_suppression_origin": _check(
            "pass" if topology_report.get("applied") is False else "fail",
            observed={
                "path": str(topology_report_path),
                "applied": topology_report.get("applied"),
                "suppressed_source_section_count": topology_report.get("suppressed_source_section_count"),
            },
            expected={"applied": False},
        ),
    }
    status = _status_for_checks(*(check["status"] for check in checks.values()))
    return {
        "contract": "shell_v3_baseline_regression.v1",
        "baseline_name": manifest.get("baseline_name", "shell_v3_quality_clean_baseline"),
        "status": status,
        "checks": checks,
        "artifacts": {
            "baseline_manifest": str(manifest_path),
            "baseline_summary": str(summary_path),
            "mesh_handoff": str(resolved_mesh_handoff_path),
            "gmsh_log": str(gmsh_log_path),
            "topology_suppression_report": str(topology_report_path),
        },
        "notes": [
            "Regression gate freezes the promoted shell_v3 baseline and checks only baseline-side artifacts.",
            "This gate does not rerun geometry or meshing.",
        ],
    }
