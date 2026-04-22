from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from .adapters.su2_backend import run_baseline_case
from .errors import TopologyUnsupportedError
from .fallback.policy import run_with_fallback
from .frozen_baseline import evaluate_shell_v3_baseline_regression
from .geometry.validator import classify_geometry_family, validate_component_geometry
from .mesh.quality import quality_check
from .mesh.recipes import build_recipe
from .pipeline import _mesh_summary
from .reports.json_report import write_json_report
from .reports.markdown_report import write_markdown_report
from .schema import (
    GeometryHandle,
    GeometryProviderResult,
    GeometryTopologyMetadata,
    MeshJobConfig,
    SU2RuntimeConfig,
)


FIXED_REF_AREA = 35.175
FIXED_REF_LENGTH = 1.0425
FIXED_DENSITY = 1.225
FIXED_VELOCITY = 6.5
FIXED_TEMPERATURE = 288.15
FIXED_DYNAMIC_VISCOSITY = 1.789e-5
FIXED_ALPHA_DEG = 0.0
FIXED_SIDESLIP_DEG = 0.0
CASE_SPECS = (
    ("coarse", 1.00, True),
    ("medium", 0.94, False),
    ("fine", 0.90, False),
)


def _resolve_path(path_value: str | Path, source_root: Path | None = None) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    root = (source_root or Path.cwd()).resolve()
    return (root / path).resolve()


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepare_out_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "artifacts").mkdir(parents=True, exist_ok=True)


def _case_reynolds_number(
    *,
    density_kgpm3: float = FIXED_DENSITY,
    velocity_mps: float = FIXED_VELOCITY,
    ref_length_m: float = FIXED_REF_LENGTH,
    dynamic_viscosity_pas: float = FIXED_DYNAMIC_VISCOSITY,
) -> float:
    return float(density_kgpm3 * velocity_mps * ref_length_m / dynamic_viscosity_pas)


def _fixed_runtime(case_name: str) -> SU2RuntimeConfig:
    return SU2RuntimeConfig(
        enabled=True,
        alpha_deg=FIXED_ALPHA_DEG,
        velocity_mps=FIXED_VELOCITY,
        density_kgpm3=FIXED_DENSITY,
        temperature_k=FIXED_TEMPERATURE,
        dynamic_viscosity_pas=FIXED_DYNAMIC_VISCOSITY,
        solver="INC_NAVIER_STOKES",
        inc_nondim="DIMENSIONAL",
        inc_density_model="CONSTANT",
        fluid_model="CONSTANT_DENSITY",
        case_name=f"shell_v3_refinement_{case_name}",
        max_iterations=80,
        reference_mode="user_declared",
        reference_override={
            "ref_area": FIXED_REF_AREA,
            "ref_length": FIXED_REF_LENGTH,
            "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
            "source_label": "shell_v3_refinement_fixed_case_contract",
        },
        wall_boundary_condition="adiabatic_no_slip",
    )


def _solver_warnings(solver_log_path: str | Path | None) -> list[str]:
    if not solver_log_path:
        return []
    path = _resolve_path(solver_log_path)
    if not path.exists():
        return []
    warnings = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "warn" not in line.lower():
            continue
        warnings.append(line.strip())
    return warnings[:20]


def _residual_behavior_summary(su2_result: dict[str, Any]) -> dict[str, Any]:
    convergence = su2_result.get("convergence_gate", {}) or {}
    iterative_gate = convergence.get("iterative_gate", {}) or {}
    residual_trend = (iterative_gate.get("checks", {}) or {}).get("residual_trend", {}) or {}
    overall_gate = convergence.get("overall_convergence_gate", {}) or {}
    return {
        "iterative_status": iterative_gate.get("status"),
        "residual_trend_status": residual_trend.get("status"),
        "median_log_drop": (residual_trend.get("observed", {}) or {}).get("median_log_drop"),
        "comparability_level": overall_gate.get("comparability_level"),
        "overall_status": overall_gate.get("status"),
        "warnings": iterative_gate.get("warnings", []),
    }


def _reconstruct_provider_result(mesh_handoff: dict[str, Any]) -> GeometryProviderResult:
    provider = ((mesh_handoff.get("provenance") or {}).get("provider") or {})
    topology_payload = provider.get("topology")
    if not isinstance(topology_payload, dict):
        raise ValueError("mesh_handoff provenance.provider.topology missing")
    return GeometryProviderResult(
        provider=str(provider.get("provider") or mesh_handoff.get("geometry_provider") or "esp_rebuilt"),
        provider_stage=str(provider.get("provider_stage") or "experimental"),
        status=str(provider.get("provider_status") or "materialized"),
        geometry_source=str(mesh_handoff.get("geometry_source") or "esp_rebuilt"),
        source_path=_resolve_path(mesh_handoff["source_path"]),
        normalized_geometry_path=_resolve_path(mesh_handoff["normalized_geometry_path"]),
        geometry_family_hint=mesh_handoff.get("geometry_family"),
        topology=GeometryTopologyMetadata.model_validate(topology_payload),
        provenance=provider.get("provenance", {}) or {},
    )


def _build_case_specs(mesh_handoff: dict[str, Any]) -> list[dict[str, Any]]:
    mesh_field = mesh_handoff.get("mesh_field", {}) or {}
    volume_smoke = mesh_field.get("volume_smoke_decoupled", {}) or {}
    shell = volume_smoke.get("near_body_shell", {}) or {}
    base_near_body = float(mesh_field.get("near_body_size", 0.0434375) or 0.0434375)
    base_distance_max = float(mesh_field.get("distance_max", 0.434375) or 0.434375)
    base_edge_distance_max = float(mesh_field.get("edge_distance_max", 0.434375) or 0.434375)
    base_shell_dist_max = float(shell.get("dist_max", 0.18) or 0.18)
    base_shell_size_min = float(shell.get("size_min", base_near_body) or base_near_body)
    specs: list[dict[str, Any]] = []
    for name, scale, reuse_frozen_mesh in CASE_SPECS:
        specs.append(
            {
                "name": name,
                "scale": float(scale),
                "reuse_frozen_mesh": bool(reuse_frozen_mesh),
                "surface_near_body_size": round(base_near_body * scale, 8),
                "surface_distance_max": round(base_distance_max * scale, 8),
                "edge_distance_max": round(base_edge_distance_max * scale, 8),
                "volume_shell_size_min": round(base_shell_size_min * scale, 8),
                "volume_shell_dist_max": round(base_shell_dist_max * scale, 8),
            }
        )
    return specs


def _refined_case_config(
    mesh_handoff: dict[str, Any],
    spec: dict[str, Any],
    out_dir: Path,
) -> MeshJobConfig:
    mesh_field = mesh_handoff.get("mesh_field", {}) or {}
    volume_smoke = mesh_field.get("volume_smoke_decoupled", {}) or {}
    shell = volume_smoke.get("near_body_shell", {}) or {}
    coarse_first_tetra = mesh_field.get("coarse_first_tetra", {}) or {}
    metadata = {
        "esp_native_c1_surface_policy_enabled": True,
        "mesh_field_distance_max": spec["surface_distance_max"],
        "mesh_field_edge_distance_max": spec["edge_distance_max"],
        "volume_smoke_decoupled_enabled": bool(volume_smoke.get("enabled", False)),
        "volume_smoke_base_size": float(
            (volume_smoke.get("base_far_volume_field", {}) or {}).get("size", 12.0) or 12.0
        ),
        "volume_smoke_shell_enabled": bool(shell.get("enabled", False)),
        "volume_smoke_shell_size_min": spec["volume_shell_size_min"],
        "volume_smoke_shell_dist_max": spec["volume_shell_dist_max"],
        "volume_smoke_shell_size_max": float(shell.get("size_max", 3.0) or 3.0),
        "volume_smoke_shell_stop_at_dist_max": True,
        "coarse_first_tetra_enabled": bool(coarse_first_tetra.get("enabled", False)),
        "coarse_first_tetra_surface_nodes_per_reference_length": coarse_first_tetra.get(
            "surface_nodes_per_reference_length"
        ),
        "coarse_first_tetra_edge_refinement_ratio": coarse_first_tetra.get("edge_refinement_ratio"),
        "coarse_first_tetra_span_extreme_strip_floor_size": coarse_first_tetra.get(
            "span_extreme_strip_floor_size"
        ),
        "coarse_first_tetra_suspect_strip_floor_size": coarse_first_tetra.get("suspect_strip_floor_size"),
        "coarse_first_tetra_suspect_surface_algorithm": coarse_first_tetra.get(
            "suspect_surface_algorithm"
        ),
        "coarse_first_tetra_general_surface_algorithm": coarse_first_tetra.get(
            "general_surface_algorithm"
        ),
        "coarse_first_tetra_farfield_surface_algorithm": coarse_first_tetra.get(
            "farfield_surface_algorithm"
        ),
        "coarse_first_tetra_clamp_mesh_size_min_to_near_body": coarse_first_tetra.get(
            "clamp_mesh_size_min_to_near_body",
            True,
        ),
    }
    return MeshJobConfig(
        component="main_wing",
        geometry=_resolve_path(mesh_handoff["source_path"]),
        out_dir=out_dir / "cases" / spec["name"],
        geometry_source=mesh_handoff.get("geometry_source", "esp_rebuilt"),
        geometry_family=mesh_handoff.get("geometry_family"),
        geometry_provider=mesh_handoff.get("geometry_provider"),
        units=mesh_handoff.get("units", "m"),
        mesh_dim=3,
        mesh_algorithm_2d=int(mesh_field.get("mesh_algorithm_2d", 6) or 6),
        mesh_algorithm_3d=int(mesh_field.get("mesh_algorithm_3d", 1) or 1),
        global_min_size=float(spec["surface_near_body_size"]),
        global_max_size=float(mesh_field.get("farfield_size", 4.17) or 4.17),
        metadata=metadata,
        su2=_fixed_runtime(spec["name"]),
    )


def _run_refined_case_job(config: MeshJobConfig, *, mesh_handoff: dict[str, Any]) -> dict[str, Any]:
    _prepare_out_dir(config.out_dir)
    provider_result = _reconstruct_provider_result(mesh_handoff)
    geom = GeometryHandle(
        source_path=_resolve_path(mesh_handoff["source_path"]),
        path=_resolve_path(mesh_handoff["normalized_geometry_path"]),
        exists=True,
        suffix=Path(mesh_handoff["normalized_geometry_path"]).suffix.lower(),
        loader=f"provider:{provider_result.provider}",
        geometry_source=mesh_handoff.get("geometry_source", "esp_rebuilt"),
        declared_family=config.geometry_family,
        component=config.component,
        provider=provider_result.provider,
        provider_status=provider_result.status,
        provider_result=provider_result,
        metadata=config.metadata,
    )
    classification = classify_geometry_family(geom, config)
    validation = validate_component_geometry(geom, classification, config)
    if not validation.ok:
        result = {
            "status": "failed",
            "failure_code": validation.failure_code or "geometry_invalid",
            "component": config.component,
            "geometry": str(config.geometry),
            "normalized_geometry": str(geom.path),
            "geometry_source": classification.geometry_source,
            "geometry_provider": geom.provider,
            "geometry_family": classification.geometry_family,
            "provider": provider_result.model_dump(mode="json"),
            "classification": classification.model_dump(mode="json"),
            "validation": validation.model_dump(mode="json"),
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
            "provider": provider_result.model_dump(mode="json"),
            "classification": classification.model_dump(mode="json"),
            "validation": validation.model_dump(mode="json"),
            "dispatch": {"error": str(exc)},
            "attempts": 0,
        }
        write_json_report(config.out_dir / "report.json", result)
        write_markdown_report(config.out_dir / "report.md", result)
        return result

    exec_result = run_with_fallback(recipe, geom, config)
    quality = quality_check(exec_result, config)
    mesh = _mesh_summary(exec_result)
    backend_result = exec_result.get("backend_result", {})
    status = "success" if quality["ok"] else "failed"
    if status == "success":
        failure_code = None
    elif exec_result.get("status") != "success":
        failure_code = backend_result.get("failure_code") or "meshing_failed"
    else:
        failure_code = quality.get("failure_code") or "quality_gate_failed"

    su2 = None
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
        "provider": provider_result.model_dump(mode="json"),
        "classification": classification.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
        "dispatch": {
            "meshing_route": recipe.meshing_route,
            "backend": recipe.backend,
            "backend_capability": recipe.backend_capability,
            "route_provenance": recipe.route_provenance,
        },
        "recipe": recipe.model_dump(mode="json"),
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


def _mesh_case_summary(
    *,
    case_name: str,
    mesh_handoff: dict[str, Any],
    mesh_summary: dict[str, Any] | None = None,
    status: str = "success",
    failure_code: str | None = None,
) -> dict[str, Any]:
    mesh_stats = (mesh_handoff.get("mesh_stats") or {}).copy()
    if mesh_summary is not None:
        mesh_stats.update(
            {
                "node_count": mesh_summary.get("node_count", mesh_stats.get("node_count")),
                "element_count": mesh_summary.get("element_count", mesh_stats.get("element_count")),
                "surface_element_count": mesh_summary.get(
                    "surface_element_count",
                    mesh_stats.get("surface_element_count"),
                ),
                "volume_element_count": mesh_summary.get(
                    "volume_element_count",
                    mesh_stats.get("volume_element_count"),
                ),
            }
        )
    mesh3d_watchdog = mesh_handoff.get("mesh3d_watchdog", {}) or {}
    quality_metrics = mesh_handoff.get("quality_metrics", {}) or {}
    return {
        "case_name": case_name,
        "status": status,
        "failure_code": failure_code,
        "mesh_artifact": (mesh_handoff.get("artifacts") or {}).get("mesh"),
        "mesh_metadata_path": (mesh_handoff.get("artifacts") or {}).get("mesh_metadata"),
        "surface_triangle_count": mesh_stats.get("surface_element_count"),
        "volume_element_count": mesh_stats.get("volume_element_count"),
        "node_count": mesh_stats.get("node_count"),
        "element_count": mesh_stats.get("element_count"),
        "boundary_nodes": mesh3d_watchdog.get("boundary_node_count"),
        "nodes_created": mesh3d_watchdog.get("nodes_created"),
        "nodes_created_per_boundary_node": mesh3d_watchdog.get("nodes_created_per_boundary_node"),
        "ill_shaped_tet_count": quality_metrics.get("ill_shaped_tet_count"),
        "wall_region_element_stats": {
            "boundary_nodes": mesh3d_watchdog.get("boundary_node_count"),
            "nodes_created": mesh3d_watchdog.get("nodes_created"),
            "nodes_created_per_boundary_node": mesh3d_watchdog.get("nodes_created_per_boundary_node"),
        },
    }


def _case_summary(
    *,
    case_name: str,
    mesh_handoff: dict[str, Any],
    mesh_summary: dict[str, Any] | None,
    result_status: str,
    failure_code: str | None,
    su2_result: dict[str, Any] | None,
    runtime_seconds: float,
) -> dict[str, Any]:
    coefficients = ((su2_result or {}).get("final_coefficients") or {}).copy()
    return {
        "contract": "shell_v3_refinement_case_summary.v1",
        "case_name": case_name,
        "status": result_status,
        "failure_code": failure_code,
        "mesh": _mesh_case_summary(
            case_name=case_name,
            mesh_handoff=mesh_handoff,
            mesh_summary=mesh_summary,
            status=result_status,
            failure_code=failure_code,
        ),
        "su2": {
            "run_status": None if su2_result is None else su2_result.get("run_status"),
            "runtime_cfg_path": None if su2_result is None else su2_result.get("runtime_cfg_path"),
            "history_path": None if su2_result is None else su2_result.get("history_path"),
            "final_iteration": None if su2_result is None else su2_result.get("final_iteration"),
            "coefficients": coefficients,
            "residual_behavior": {} if su2_result is None else _residual_behavior_summary(su2_result),
            "solver_warnings": [] if su2_result is None else _solver_warnings((su2_result.get("case_output_paths") or {}).get("solver_log")),
            "runtime_seconds": runtime_seconds,
        },
        "runtime_seconds": runtime_seconds,
        "case_level_reynolds_number": _case_reynolds_number(),
    }


def _drag_values(case_summaries: list[dict[str, Any]]) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    for summary in case_summaries:
        cd = ((summary.get("su2") or {}).get("coefficients") or {}).get("cd")
        if isinstance(cd, (int, float)) and math.isfinite(float(cd)) and float(cd) > 0.0:
            values.append((str(summary.get("case_name")), float(cd)))
    return values


def _study_summary_payload(
    *,
    baseline_manifest_path: Path,
    baseline_mesh_metadata_path: Path,
    out_dir: Path,
    case_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    drag_values = _drag_values(case_summaries)
    best_cd_case = min(drag_values, key=lambda item: item[1])[0] if drag_values else None
    coarse_cd = next((value for name, value in drag_values if name == "coarse"), None)
    fine_cd = next((value for name, value in drag_values if name == "fine"), None)
    medium_cd = next((value for name, value in drag_values if name == "medium"), None)
    medium_fine_gap = (
        abs(fine_cd - medium_cd) / abs(fine_cd)
        if medium_cd is not None and fine_cd is not None and fine_cd != 0.0
        else None
    )
    if medium_fine_gap is not None and medium_fine_gap > 0.08:
        next_step = "continue_same_route_refinement"
    else:
        next_step = "near_wall_or_bl_now_worth_revisiting"
    payload = {
        "contract": "shell_v3_mesh_refinement_summary.v1",
        "status": "success",
        "baseline_manifest_path": str(baseline_manifest_path),
        "baseline_mesh_metadata_path": str(baseline_mesh_metadata_path),
        "case_level_reynolds_number": _case_reynolds_number(),
        "case_level_reynolds_number_note": (
            "Case-level Reynolds number based on rho * V * REF_LENGTH / mu; not a local chord Reynolds number."
        ),
        "fixed_case_contract": {
            "solver": "INC_NAVIER_STOKES",
            "wall_bc": "MARKER_HEATFLUX = ( aircraft, 0.0 )",
            "farfield_bc": "MARKER_FAR = ( farfield )",
            "velocity_mps": FIXED_VELOCITY,
            "density_kgpm3": FIXED_DENSITY,
            "temperature_k": FIXED_TEMPERATURE,
            "dynamic_viscosity_pas": FIXED_DYNAMIC_VISCOSITY,
            "ref_area": FIXED_REF_AREA,
            "ref_length": FIXED_REF_LENGTH,
            "turbulence_model": "NONE",
        },
        "cases": case_summaries,
        "conclusion": {
            "drag_trend": {
                "coarse_cd": coarse_cd,
                "fine_cd": fine_cd,
                "best_cd_case": best_cd_case,
                "coarse_to_fine_delta": None if coarse_cd is None or fine_cd is None else fine_cd - coarse_cd,
                "medium_fine_relative_gap": medium_fine_gap,
            },
            "stability_direction": {
                "appears_more_stable_with_refinement": bool(
                    medium_fine_gap is not None and medium_fine_gap <= 0.08
                ),
                "recommended_next_step": next_step,
            },
        },
        "artifacts": {
            "case_summaries_dir": str(out_dir / "case_summaries"),
            "cases_dir": str(out_dir / "cases"),
            "mesh_refinement_summary": str(out_dir / "mesh_refinement_summary.json"),
        },
    }
    _write_json(out_dir / "mesh_refinement_summary.json", payload)
    return payload


def run_shell_v3_refinement_study(
    manifest_path: str | Path,
    *,
    out_dir: str | Path,
    mesh_handoff_path: str | Path | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    manifest_path = _resolve_path(manifest_path, source_root)
    out_dir = _resolve_path(out_dir, source_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "case_summaries").mkdir(parents=True, exist_ok=True)
    (out_dir / "cases").mkdir(parents=True, exist_ok=True)

    baseline_regression = evaluate_shell_v3_baseline_regression(
        manifest_path,
        mesh_handoff_path=mesh_handoff_path,
        source_root=source_root,
    )
    baseline_mesh_metadata_path = _resolve_path(baseline_regression["artifacts"]["mesh_handoff"], source_root)
    mesh_handoff = _load_json(baseline_mesh_metadata_path)

    case_summaries: list[dict[str, Any]] = []
    for spec in _build_case_specs(mesh_handoff):
        started = time.perf_counter()
        if spec["reuse_frozen_mesh"]:
            su2_result = run_baseline_case(
                mesh_handoff,
                _fixed_runtime(spec["name"]),
                out_dir / "cases" / spec["name"] / "artifacts" / "su2",
                source_root=source_root,
            )
            case_summary = _case_summary(
                case_name=spec["name"],
                mesh_handoff=mesh_handoff,
                mesh_summary=None,
                result_status="success" if su2_result.get("run_status") == "completed" else "failed",
                failure_code=None if su2_result.get("run_status") == "completed" else su2_result.get("failure_code"),
                su2_result=su2_result,
                runtime_seconds=time.perf_counter() - started,
            )
        else:
            config = _refined_case_config(mesh_handoff, spec, out_dir)
            result = _run_refined_case_job(config, mesh_handoff=mesh_handoff)
            mesh_metadata_path = (result.get("mesh") or {}).get("metadata_path")
            refreshed_mesh_handoff = (
                _load_json(_resolve_path(mesh_metadata_path, source_root))
                if isinstance(mesh_metadata_path, str) and Path(_resolve_path(mesh_metadata_path, source_root)).exists()
                else mesh_handoff
            )
            case_summary = _case_summary(
                case_name=spec["name"],
                mesh_handoff=refreshed_mesh_handoff,
                mesh_summary=result.get("mesh"),
                result_status=result.get("status", "failed"),
                failure_code=result.get("failure_code"),
                su2_result=result.get("su2"),
                runtime_seconds=time.perf_counter() - started,
            )
        _write_json(out_dir / "case_summaries" / f"{spec['name']}.json", case_summary)
        case_summaries.append(case_summary)

    return _study_summary_payload(
        baseline_manifest_path=manifest_path,
        baseline_mesh_metadata_path=baseline_mesh_metadata_path,
        out_dir=out_dir,
        case_summaries=case_summaries,
    )
