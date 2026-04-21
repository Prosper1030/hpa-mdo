from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .adapters.su2_backend import run_baseline_case
from .schema import MeshJobConfig
from .errors import TopologyUnsupportedError
from .geometry.loader import load_geometry
from .geometry.validator import classify_geometry_family, validate_component_geometry
from .mesh.recipes import build_recipe
from .mesh.quality import quality_check
from .fallback.policy import run_with_fallback
from .reports.json_report import write_json_report
from .reports.markdown_report import write_markdown_report


def _prepare_out_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "artifacts").mkdir(parents=True, exist_ok=True)


def _reportable(data: Any) -> Any:
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    return data


def _mesh_summary(exec_result: Dict[str, Any]) -> Dict[str, Any]:
    backend_result = exec_result.get("backend_result", {})
    mesh_handoff = backend_result.get("mesh_handoff", {})
    artifacts = mesh_handoff.get("artifacts", backend_result.get("artifacts", {}))
    mesh_stats = mesh_handoff.get("mesh_stats", backend_result.get("mesh_stats", {}))
    return {
        "contract": mesh_handoff.get("contract"),
        "route_stage": backend_result.get("route_stage"),
        "backend": mesh_handoff.get("backend", backend_result.get("backend")),
        "backend_capability": mesh_handoff.get(
            "backend_capability",
            backend_result.get("backend_capability"),
        ),
        "meshing_route": mesh_handoff.get("meshing_route", backend_result.get("meshing_route")),
        "geometry_family": mesh_handoff.get("geometry_family", backend_result.get("geometry_family")),
        "geometry_source": mesh_handoff.get("geometry_source", backend_result.get("geometry_source")),
        "geometry_provider": mesh_handoff.get("geometry_provider", backend_result.get("geometry_provider")),
        "mesh_format": mesh_handoff.get("mesh_format", backend_result.get("mesh_format")),
        "units": mesh_handoff.get("units", backend_result.get("units")),
        "mesh_dim": mesh_stats.get("mesh_dim"),
        "mesh_artifact": artifacts.get("mesh"),
        "metadata_path": artifacts.get("mesh_metadata"),
        "marker_summary_path": artifacts.get("marker_summary"),
        "source_path": mesh_handoff.get("source_path"),
        "normalized_geometry_path": mesh_handoff.get("normalized_geometry_path"),
        "body_bounds": mesh_handoff.get("body_bounds", backend_result.get("body_bounds")),
        "farfield_bounds": mesh_handoff.get("farfield_bounds", backend_result.get("farfield_bounds")),
        "node_count": mesh_stats.get("node_count"),
        "element_count": mesh_stats.get("element_count"),
        "surface_element_count": mesh_stats.get("surface_element_count"),
        "volume_element_count": mesh_stats.get("volume_element_count"),
        "marker_summary": mesh_handoff.get("marker_summary", backend_result.get("marker_summary", {})),
        "physical_groups": mesh_handoff.get("physical_groups", backend_result.get("physical_groups", {})),
        "provenance": mesh_handoff.get("provenance", backend_result.get("provenance")),
        "unit_normalization": backend_result.get("unit_normalization"),
    }


def validate_geometry_only(config: MeshJobConfig) -> Dict[str, Any]:
    _prepare_out_dir(config.out_dir)
    geom = load_geometry(config.geometry, config)
    classification = classify_geometry_family(geom, config)
    val = validate_component_geometry(geom, classification, config)
    result = {
        "status": "success" if val.ok else "failed",
        "failure_code": None if val.ok else val.failure_code or "geometry_invalid",
        "component": config.component,
        "geometry": str(config.geometry),
        "normalized_geometry": str(geom.path),
        "geometry_source": classification.geometry_source,
        "geometry_provider": geom.provider,
        "geometry_family": classification.geometry_family,
        "provider": _reportable(geom.provider_result),
        "classification": _reportable(classification),
        "validation": _reportable(val),
    }
    write_json_report(config.out_dir / "report.json", result)
    write_markdown_report(config.out_dir / "report.md", result)
    return result


def run_job(config: MeshJobConfig) -> Dict[str, Any]:
    _prepare_out_dir(config.out_dir)
    geom = load_geometry(config.geometry, config)
    classification = classify_geometry_family(geom, config)
    val = validate_component_geometry(geom, classification, config)
    if not val.ok:
        result = {
            "status": "failed",
            "failure_code": val.failure_code or "geometry_invalid",
            "component": config.component,
            "geometry": str(config.geometry),
            "normalized_geometry": str(geom.path),
            "geometry_source": classification.geometry_source,
            "geometry_provider": geom.provider,
            "geometry_family": classification.geometry_family,
            "provider": _reportable(geom.provider_result),
            "classification": _reportable(classification),
            "validation": _reportable(val),
            "attempts": 0,
        }
        write_json_report(config.out_dir / "report.json", result)
        write_markdown_report(config.out_dir / "report.md", result)
        return result

    try:
        recipe = build_recipe(geom, classification, config)
    except TopologyUnsupportedError as exc:
        result = {
            "status": "failed",
            "failure_code": "dispatch_invalid",
            "component": config.component,
            "geometry": str(config.geometry),
            "normalized_geometry": str(geom.path),
            "geometry_source": classification.geometry_source,
            "geometry_provider": geom.provider,
            "geometry_family": classification.geometry_family,
            "provider": _reportable(geom.provider_result),
            "classification": _reportable(classification),
            "validation": _reportable(val),
            "dispatch": {
                "error": str(exc),
            },
            "attempts": 0,
        }
        write_json_report(config.out_dir / "report.json", result)
        write_markdown_report(config.out_dir / "report.md", result)
        return result

    exec_result = run_with_fallback(recipe, geom, config)
    quality = quality_check(exec_result, config)
    mesh = _mesh_summary(exec_result)
    su2 = None

    backend_result = exec_result.get("backend_result", {})
    status = "success" if quality["ok"] else "failed"
    if status == "success":
        failure_code = None
    elif exec_result.get("status") != "success":
        failure_code = backend_result.get("failure_code") or "meshing_failed"
    else:
        failure_code = quality.get("failure_code") or "quality_gate_failed"
    if config.su2.enabled:
        mesh_handoff_payload = backend_result.get("mesh_handoff")
        if mesh_handoff_payload is None:
            su2 = {
                "contract": "su2_handoff.v1",
                "run_status": "failed",
                "failure_code": "mesh_handoff_missing",
                "error": "backend_result did not expose mesh_handoff.v1",
                "solver_command": "",
                "runtime_cfg_path": None,
                "history_path": None,
                "final_coefficients": {"cl": None, "cd": None, "cm": None, "cm_axis": None},
                "provenance": {"source_contract": None},
                "notes": ["Package-native SU2 baseline requires mesh_handoff.v1."],
            }
        else:
            su2 = run_baseline_case(
                mesh_handoff_payload,
                config.su2,
                config.out_dir / "artifacts" / "su2",
                source_root=Path.cwd(),
            )
        if status == "success" and su2.get("run_status") != "completed":
            status = "failed"
            failure_code = su2.get("failure_code") or "su2_run_failed"

    result = {
        "status": status,
        "failure_code": failure_code,
        "component": config.component,
        "geometry": str(config.geometry),
        "normalized_geometry": str(geom.path),
        "geometry_source": classification.geometry_source,
        "geometry_provider": geom.provider,
        "geometry_family": classification.geometry_family,
        "provider": _reportable(geom.provider_result),
        "classification": _reportable(classification),
        "validation": _reportable(val),
        "dispatch": {
            "meshing_route": recipe.meshing_route,
            "backend": recipe.backend,
            "backend_capability": recipe.backend_capability,
            "route_provenance": recipe.route_provenance,
        },
        "recipe": _reportable(recipe),
        "mesh": mesh,
        "run": exec_result,
        "quality": quality,
        "attempts": exec_result.get("attempts", 1),
    }
    backend_error = backend_result.get("error")
    if backend_error is not None:
        result["error"] = backend_error
    if su2 is not None:
        result["su2"] = su2
        if su2.get("convergence_gate") is not None:
            result["convergence"] = su2["convergence_gate"]
    write_json_report(config.out_dir / "report.json", result)
    write_markdown_report(config.out_dir / "report.md", result)
    return result
