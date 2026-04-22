from __future__ import annotations

import inspect
import json
import math
import time
from pathlib import Path
from typing import Any

from .adapters import gmsh_backend
from .adapters.su2_backend import run_baseline_case
from .fallback.policy import run_with_fallback
from .frozen_baseline import evaluate_shell_v3_baseline_regression
from .geometry.validator import classify_geometry_family, validate_component_geometry
from .gmsh_runtime import GmshRuntimeError, load_gmsh
from .mesh.quality import quality_check
from .mesh.recipes import build_recipe
from .pipeline import run_job as _pipeline_run_job
from .reports.json_report import write_json_report
from .reports.markdown_report import write_markdown_report
from .schema import GeometryHandle, MeshJobConfig, SU2RuntimeConfig


FIXED_REF_AREA = 35.175
FIXED_REF_LENGTH = 1.0425
FIXED_DENSITY = 1.225
FIXED_VELOCITY = 6.5
FIXED_TEMPERATURE = 288.15
FIXED_DYNAMIC_VISCOSITY = 1.789e-5
FIXED_ALPHA_DEG = 0.0
FIXED_SIDESLIP_DEG = 0.0


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


def _reportable(data: Any) -> Any:
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    return data


def _mesh_summary(exec_result: dict[str, Any]) -> dict[str, Any]:
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


def _volume_element_count_from_mesh_summary(mesh_summary: dict[str, Any] | None) -> int:
    if not isinstance(mesh_summary, dict):
        return 0
    value = mesh_summary.get("volume_element_count")
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


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
        case_name=case_name,
        max_iterations=80,
        reference_mode="user_declared",
        reference_override={
            "ref_area": FIXED_REF_AREA,
            "ref_length": FIXED_REF_LENGTH,
            "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
            "source_label": "shell_v3_near_wall_fixed_case_contract",
        },
        wall_boundary_condition="adiabatic_no_slip",
    )


def _frozen_geometry_payload(mesh_handoff: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": mesh_handoff.get("source_path"),
        "normalized_geometry_path": mesh_handoff.get("normalized_geometry_path"),
        "geometry_family": mesh_handoff.get("geometry_family"),
        "geometry_source": mesh_handoff.get("geometry_source"),
        "geometry_provider": mesh_handoff.get("geometry_provider"),
    }


def build_frozen_cfd_context(
    manifest_path: str | Path,
    *,
    solver_summary_path: str | Path | None = None,
    out_dir: str | Path,
    source_root: Path | None = None,
) -> dict[str, Any]:
    out_dir = _resolve_path(out_dir, source_root)
    manifest_path = _resolve_path(manifest_path, source_root)
    manifest = _load_json(manifest_path)
    baseline_regression = evaluate_shell_v3_baseline_regression(manifest_path, source_root=source_root)
    mesh_metadata_path = _resolve_path(baseline_regression["artifacts"]["mesh_handoff"], source_root)
    mesh_handoff = _load_json(mesh_metadata_path)

    solver_summary = None
    if solver_summary_path is not None:
        solver_summary = _load_json(_resolve_path(solver_summary_path, source_root))

    historical_run = (solver_summary or {}).get("run_result", {}) or {}
    historical_reference = historical_run.get("reference_geometry", {}) or {}
    formal_runtime = _fixed_runtime("shell_v3_alpha0_coarse_compare")
    reynolds_number = _case_reynolds_number()

    context = {
        "contract": "frozen_cfd_context.v1",
        "status": "pass" if baseline_regression.get("status") == "pass" else "fail",
        "baseline_name": manifest.get("baseline_name", "shell_v3_quality_clean_baseline"),
        "baseline_manifest_path": str(manifest_path),
        "baseline_regression": baseline_regression,
        "current_mesh_metadata_path": str(mesh_metadata_path),
        "current_marker_summary_path": str(_resolve_path(mesh_handoff["artifacts"]["marker_summary"], source_root)),
        "current_mesh_artifact_path": str(_resolve_path(mesh_handoff["artifacts"]["mesh"], source_root)),
        "current_su2_config_path": None if not historical_run.get("runtime_cfg_path") else str(_resolve_path(historical_run["runtime_cfg_path"], source_root)),
        "current_coefficients": {
            "cl": historical_run.get("final_coefficients", {}).get("cl"),
            "cd": historical_run.get("final_coefficients", {}).get("cd"),
            "cm": historical_run.get("final_coefficients", {}).get("cm"),
        },
        "current_wall_bc_contract": "adiabatic_no_slip",
        "current_known_limitation": "no near-wall BL-capable mesh",
        "reference_geometry": {
            "ref_area": historical_reference.get("ref_area", FIXED_REF_AREA),
            "ref_length": historical_reference.get("ref_length", FIXED_REF_LENGTH),
        },
        "historical_flow_condition": {
            "velocity_mps": 10.0,
            "alpha_deg": FIXED_ALPHA_DEG,
            "sideslip_deg": FIXED_SIDESLIP_DEG,
        },
        "formal_case_contract": {
            "solver": formal_runtime.solver,
            "inc_nondim": formal_runtime.inc_nondim,
            "inc_density_model": formal_runtime.inc_density_model,
            "fluid_model": formal_runtime.fluid_model,
            "density_kgpm3": formal_runtime.density_kgpm3,
            "velocity_mps": formal_runtime.velocity_mps,
            "temperature_k": formal_runtime.temperature_k,
            "dynamic_viscosity_pas": formal_runtime.dynamic_viscosity_pas,
            "wall_boundary_condition": formal_runtime.wall_boundary_condition,
            "marker_heatflux": "( aircraft, 0.0 )",
            "marker_far": "( farfield )",
            "ref_area": FIXED_REF_AREA,
            "ref_length": FIXED_REF_LENGTH,
            "alpha_deg": FIXED_ALPHA_DEG,
            "sideslip_deg": FIXED_SIDESLIP_DEG,
            "reynolds_number_case_level": reynolds_number,
            "reynolds_number_note": "Case-level Reynolds number based on rho * V * REF_LENGTH / mu; not a local chord Reynolds number.",
        },
        "frozen_geometry": _frozen_geometry_payload(mesh_handoff),
    }
    _write_json(out_dir / "frozen_cfd_context.json", context)
    return context


def assess_near_wall_capability(
    frozen_context: dict[str, Any],
    *,
    out_dir: str | Path,
    source_root: Path | None = None,
) -> dict[str, Any]:
    out_dir = _resolve_path(out_dir, source_root)
    mesh_handoff = _load_json(frozen_context["current_mesh_metadata_path"])
    gmsh_source = Path(inspect.getsourcefile(gmsh_backend.apply_recipe) or "")
    gmsh_text = gmsh_source.read_text(encoding="utf-8") if gmsh_source.exists() else ""
    prism_guard = "boundary_layer.enabled requires a dedicated prism route" in gmsh_text
    baseline_volume_types = sorted(
        int(key)
        for key in (mesh_handoff.get("mesh_stats", {}).get("volume_element_type_counts", {}) or {}).keys()
    )
    current_shell = (
        (mesh_handoff.get("mesh_field", {}) or {})
        .get("volume_smoke_decoupled", {})
        .get("near_body_shell", {})
        or {}
    )
    tetra_fallback_supported = bool(
        (mesh_handoff.get("mesh_field", {}) or {}).get("volume_smoke_decoupled", {}).get("enabled", False)
    )
    conclusion = (
        "prism_layer_not_yet_feasible_use_refined_tetra_fallback"
        if prism_guard
        else "prism_layer_feasible"
    )
    report = {
        "contract": "near_wall_capability_report.v1",
        "baseline_name": frozen_context.get("baseline_name"),
        "prism_layer_guard_present": prism_guard,
        "prism_layer_feasible": not prism_guard,
        "wall_refined_tetra_fallback_supported": tetra_fallback_supported,
        "current_volume_element_types": baseline_volume_types,
        "current_near_body_shell": current_shell,
        "mesh_format_contract": {
            "source_mesh_format": mesh_handoff.get("mesh_format"),
            "required_markers": ["aircraft", "farfield", "fluid"],
            "wall_marker": "aircraft",
        },
        "su2_route_constraints": [
            "Current SU2 route expects mesh_handoff.v1 plus aircraft/farfield/fluid physical groups.",
            "Current force monitoring collapses to a whole-aircraft wall marker named aircraft.",
            "Current near-wall upgrade must stay on the existing INC_NAVIER_STOKES route with adiabatic no-slip wall BC.",
        ],
        "evidence": [
            {
                "type": "code_guard",
                "path": str(gmsh_source) if gmsh_source.exists() else None,
                "detail": "Current OCC tetra route still rejects boundary_layer.enabled and asks for a dedicated prism route.",
            },
            {
                "type": "mesh_field",
                "path": frozen_context.get("current_mesh_metadata_path"),
                "detail": "Frozen baseline already carries a bounded near-body tetra shell field under mesh_field.volume_smoke_decoupled.",
            },
            {
                "type": "element_family",
                "path": frozen_context.get("current_mesh_metadata_path"),
                "detail": f"Current frozen baseline volume element families are {baseline_volume_types}, so the active route is still prism-less.",
            },
        ],
        "conclusion": conclusion,
    }
    _write_json(out_dir / "near_wall_capability_report.json", report)
    return report


def _baseline_mesh_field_defaults(mesh_handoff: dict[str, Any]) -> dict[str, Any]:
    mesh_field = mesh_handoff.get("mesh_field", {}) or {}
    volume_smoke = mesh_field.get("volume_smoke_decoupled", {}) or {}
    coarse_profile = mesh_field.get("coarse_first_tetra", {}) or {}
    return {
        "surface_near_body_size": float(mesh_field.get("near_body_size", 0.0434375) or 0.0434375),
        "surface_distance_max": float(mesh_field.get("distance_max", 0.434375) or 0.434375),
        "edge_distance_max": float(mesh_field.get("edge_distance_max", 0.434375) or 0.434375),
        "farfield_size": float(mesh_field.get("farfield_size", 4.17) or 4.17),
        "mesh_algorithm_2d": int(mesh_field.get("mesh_algorithm_2d", 6) or 6),
        "mesh_algorithm_3d": int(mesh_field.get("mesh_algorithm_3d", 1) or 1),
        "volume_base_size": float(
            (volume_smoke.get("base_far_volume_field", {}) or {}).get("size", 12.0) or 12.0
        ),
        "coarse_first_tetra": coarse_profile,
    }


def _candidate_specs(mesh_handoff: dict[str, Any]) -> list[dict[str, Any]]:
    defaults = _baseline_mesh_field_defaults(mesh_handoff)
    base_near_body = defaults["surface_near_body_size"]
    base_dist = defaults["surface_distance_max"]
    base_edge_dist = defaults["edge_distance_max"]
    return [
        {
            "name": "conservative",
            "surface_near_body_size": round(base_near_body, 6),
            "volume_shell_size_min": round(base_near_body * 0.50, 6),
            "surface_distance_max": base_dist,
            "edge_distance_max": base_edge_dist,
            "shell_dist_max": 0.12,
            "shell_size_max": 1.8,
            "intent": "keep the baseline 2D surface mesh and add the first bounded volume-only near-wall shell",
        },
        {
            "name": "medium",
            "surface_near_body_size": round(base_near_body, 6),
            "volume_shell_size_min": round(base_near_body * 0.35, 6),
            "surface_distance_max": base_dist,
            "edge_distance_max": base_edge_dist,
            "shell_dist_max": 0.10,
            "shell_size_max": 1.2,
            "intent": "tighter volume-only wall shell with the baseline surface mesh held fixed",
        },
        {
            "name": "strong",
            "surface_near_body_size": round(base_near_body, 6),
            "volume_shell_size_min": round(base_near_body * 0.25, 6),
            "surface_distance_max": base_dist,
            "edge_distance_max": base_edge_dist,
            "shell_dist_max": 0.08,
            "shell_size_max": 0.8,
            "intent": "smallest bounded volume-only wall shell before element count is expected to escalate",
        },
    ]


def _frozen_candidate_config(
    *,
    mesh_handoff: dict[str, Any],
    candidate: dict[str, Any],
    out_dir: Path,
) -> MeshJobConfig:
    defaults = _baseline_mesh_field_defaults(mesh_handoff)
    coarse_profile = defaults["coarse_first_tetra"] if isinstance(defaults["coarse_first_tetra"], dict) else {}
    metadata = {
        "_frozen_geometry": {
            "source_path": mesh_handoff.get("source_path"),
            "normalized_geometry_path": mesh_handoff.get("normalized_geometry_path"),
            "geometry_source": mesh_handoff.get("geometry_source"),
            "geometry_provider": mesh_handoff.get("geometry_provider"),
        },
        "_frozen_mesh_handoff_path": mesh_handoff["artifacts"]["mesh_metadata"],
        "_frozen_surface_mesh_path": str(
            _resolve_path(mesh_handoff["artifacts"]["mesh_metadata"]).with_name("surface_mesh_2d.msh")
        ),
        "_frozen_farfield_bounds": mesh_handoff.get("farfield_bounds"),
        "esp_native_c1_surface_policy_enabled": True,
        "volume_smoke_decoupled_enabled": True,
        "volume_smoke_base_size": defaults["volume_base_size"],
        "volume_smoke_shell_enabled": True,
        "volume_smoke_shell_size_min": candidate["volume_shell_size_min"],
        "volume_smoke_shell_dist_max": candidate["shell_dist_max"],
        "volume_smoke_shell_size_max": candidate["shell_size_max"],
        "volume_smoke_shell_stop_at_dist_max": True,
        "mesh_field_distance_max": candidate["surface_distance_max"],
        "mesh_field_edge_distance_max": candidate["edge_distance_max"],
        "coarse_first_tetra_enabled": bool(coarse_profile.get("enabled", False)),
        "coarse_first_tetra_surface_nodes_per_reference_length": coarse_profile.get("surface_nodes_per_reference_length"),
        "coarse_first_tetra_edge_refinement_ratio": coarse_profile.get("edge_refinement_ratio"),
        "coarse_first_tetra_span_extreme_strip_floor_size": coarse_profile.get("span_extreme_strip_floor_size"),
        "coarse_first_tetra_suspect_strip_floor_size": coarse_profile.get("suspect_strip_floor_size"),
        "coarse_first_tetra_suspect_surface_algorithm": coarse_profile.get("suspect_surface_algorithm"),
        "coarse_first_tetra_general_surface_algorithm": coarse_profile.get("general_surface_algorithm"),
        "coarse_first_tetra_farfield_surface_algorithm": coarse_profile.get("farfield_surface_algorithm"),
        "coarse_first_tetra_clamp_mesh_size_min_to_near_body": coarse_profile.get(
            "clamp_mesh_size_min_to_near_body",
            True,
        ),
    }
    return MeshJobConfig(
        component="main_wing",
        geometry=Path(mesh_handoff["normalized_geometry_path"]),
        out_dir=out_dir / "candidates" / candidate["name"],
        geometry_source="esp_rebuilt",
        geometry_family=mesh_handoff["geometry_family"],
        geometry_provider=mesh_handoff.get("geometry_provider") or "esp_rebuilt",
        units=mesh_handoff.get("units", "m"),
        mesh_dim=3,
        mesh_algorithm_2d=defaults["mesh_algorithm_2d"],
        mesh_algorithm_3d=defaults["mesh_algorithm_3d"],
        global_min_size=float(candidate["surface_near_body_size"]),
        global_max_size=defaults["farfield_size"],
        metadata=metadata,
        su2=_fixed_runtime(candidate["name"]),
    )


def _run_job_with_frozen_geometry(config: MeshJobConfig, frozen_geometry: dict[str, Any]) -> dict[str, Any]:
    _prepare_out_dir(config.out_dir)
    source_path = _resolve_path(frozen_geometry["source_path"])
    normalized_geometry_path = _resolve_path(frozen_geometry["normalized_geometry_path"])
    geom = GeometryHandle(
        source_path=source_path,
        path=normalized_geometry_path,
        exists=normalized_geometry_path.exists(),
        suffix=normalized_geometry_path.suffix.lower(),
        loader="frozen_baseline",
        geometry_source=frozen_geometry.get("geometry_source", "esp_rebuilt"),
        declared_family=config.geometry_family,
        component=config.component,
        provider=frozen_geometry.get("geometry_provider"),
        provider_status="materialized",
        provider_result=None,
        metadata=config.metadata,
    )
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
            "provider": None,
            "classification": _reportable(classification),
            "validation": _reportable(val),
            "attempts": 0,
        }
        write_json_report(config.out_dir / "report.json", result)
        write_markdown_report(config.out_dir / "report.md", result)
        return result

    recipe = build_recipe(geom, classification, config)
    exec_result = run_with_fallback(recipe, geom, config)
    quality = quality_check(exec_result, config)
    mesh = _mesh_summary(exec_result)
    su2 = None

    backend_result = exec_result.get("backend_result", {})
    status = "success" if quality["ok"] else "failed"
    failure_code = None if status == "success" else quality.get("failure_code") or "quality_gate_failed"
    if status == "failed" and exec_result.get("status") != "success":
        failure_code = backend_result.get("failure_code") or "meshing_failed"

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
        "provider": None,
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
    if backend_result.get("error") is not None:
        result["error"] = backend_result["error"]
    if su2 is not None:
        result["su2"] = su2
        if su2.get("convergence_gate") is not None:
            result["convergence"] = su2["convergence_gate"]
    write_json_report(config.out_dir / "report.json", result)
    write_markdown_report(config.out_dir / "report.md", result)
    return result


def _mesh_handoff_from_surface_frozen_regenerate(
    config: MeshJobConfig,
    *,
    frozen_mesh_handoff: dict[str, Any],
    surface_mesh_path: Path,
) -> dict[str, Any]:
    _prepare_out_dir(config.out_dir)
    mesh_dir = config.out_dir / "artifacts" / "mesh"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = mesh_dir / "mesh.msh"
    metadata_path = mesh_dir / "mesh_metadata.json"
    marker_summary_path = mesh_dir / "marker_summary.json"
    gmsh_log_path = mesh_dir / "gmsh_log.txt"
    mesh3d_watchdog_path = mesh_dir / "mesh3d_watchdog.json"
    mesh3d_watchdog_sample_path = mesh_dir / "mesh3d_watchdog_sample.txt"

    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        return {
            "status": "failed",
            "failure_code": "gmsh_runtime_missing",
            "error": str(exc),
        }

    initialized = False
    logger_started = False
    try:
        gmsh.initialize()
        initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.logger.start()
        logger_started = True
        gmsh.open(str(surface_mesh_path))

        physical_lookup: dict[tuple[int, str], int] = {}
        for dim, tag in gmsh.model.getPhysicalGroups():
            physical_lookup[(int(dim), gmsh.model.getPhysicalName(int(dim), int(tag)))] = int(tag)

        aircraft_tag = physical_lookup[(2, "aircraft")]
        farfield_tag = physical_lookup[(2, "farfield")]
        fluid_tag = physical_lookup[(3, "fluid")]
        aircraft_surface_tags = [int(tag) for tag in gmsh.model.getEntitiesForPhysicalGroup(2, aircraft_tag)]
        farfield_surface_tags = [int(tag) for tag in gmsh.model.getEntitiesForPhysicalGroup(2, farfield_tag)]
        fluid_volume_tags = [int(tag) for tag in gmsh.model.getEntitiesForPhysicalGroup(3, fluid_tag)]

        farfield_bounds = config.metadata.get("_frozen_farfield_bounds") or frozen_mesh_handoff.get("farfield_bounds")
        field_info = gmsh_backend._configure_volume_smoke_decoupled_field(
            gmsh,
            aircraft_surface_tags=aircraft_surface_tags,
            near_body_size=float(config.global_min_size or frozen_mesh_handoff.get("mesh_field", {}).get("near_body_size", 0.0434375)),
            mesh_algorithm_3d=int(config.mesh_algorithm_3d or frozen_mesh_handoff.get("mesh_field", {}).get("mesh_algorithm_3d", 1)),
            bounds=dict(farfield_bounds),
            surface_patch_diagnostics=None,
            config=config,
        )

        pre_mesh_stats = {
            "mesh_dim": 3,
            "node_count": int(frozen_mesh_handoff.get("mesh_stats", {}).get("node_count", 0) or 0),
            "element_count": int(frozen_mesh_handoff.get("mesh_stats", {}).get("surface_element_count", 0) or 0),
            "surface_element_count": int(frozen_mesh_handoff.get("mesh_stats", {}).get("surface_element_count", 0) or 0),
            "volume_element_count": 0,
        }
        mesh3d_watchdog, mesh3d_error = gmsh_backend._run_mesh3d_with_watchdog(
            gmsh,
            watchdog_path=mesh3d_watchdog_path,
            sample_path=mesh3d_watchdog_sample_path,
            timeout_seconds=float(
                config.metadata.get("mesh3d_watchdog_timeout_sec", gmsh_backend.DEFAULT_MESH3D_WATCHDOG_TIMEOUT_SECONDS)
            ),
            sample_seconds=int(
                config.metadata.get("mesh3d_watchdog_sample_seconds", gmsh_backend.DEFAULT_MESH3D_WATCHDOG_SAMPLE_SECONDS)
            ),
            mesh_algorithm_3d=int(config.mesh_algorithm_3d or 1),
            pre_mesh_stats=pre_mesh_stats,
        )
        logger_messages = [str(message) for message in gmsh.logger.get()]
        gmsh_log_path.write_text("\n".join(logger_messages) + ("\n" if logger_messages else ""), encoding="utf-8")
        if mesh3d_error is not None:
            return {
                "status": "failed",
                "failure_code": "mesh3d_generate_failed",
                "error": str(mesh3d_error),
                "mesh3d_watchdog": mesh3d_watchdog,
                "artifacts": {
                    "gmsh_log": str(gmsh_log_path),
                    "mesh3d_watchdog": str(mesh3d_watchdog_path),
                    "mesh3d_watchdog_sample": str(mesh3d_watchdog_sample_path),
                },
            }

        gmsh.write(str(mesh_path))
        physical_groups = {
            "fluid": gmsh_backend._physical_group_summary(gmsh, 3, fluid_tag),
            "aircraft": gmsh_backend._physical_group_summary(gmsh, 2, aircraft_tag),
            "farfield": gmsh_backend._physical_group_summary(gmsh, 2, farfield_tag),
        }
        marker_summary = {
            "aircraft": physical_groups["aircraft"],
            "farfield": physical_groups["farfield"],
        }
        mesh_stats = {
            "mesh_dim": 3,
            **gmsh_backend._mesh_stats(gmsh),
        }
        quality_metrics = gmsh_backend._collect_volume_quality_metrics(
            gmsh,
            marker_summary=marker_summary,
            physical_groups=physical_groups,
            logger_messages=logger_messages,
        )

        mesh_handoff = dict(frozen_mesh_handoff)
        mesh_handoff["mesh_stats"] = mesh_stats
        mesh_handoff["marker_summary"] = marker_summary
        mesh_handoff["physical_groups"] = physical_groups
        mesh_handoff["quality_metrics"] = quality_metrics
        mesh_handoff["mesh_field"] = dict(frozen_mesh_handoff.get("mesh_field", {}) or {})
        mesh_handoff["mesh_field"]["volume_smoke_decoupled"] = field_info
        mesh_handoff["artifacts"] = {
            "mesh": str(mesh_path),
            "mesh_metadata": str(metadata_path),
            "marker_summary": str(marker_summary_path),
            "gmsh_log": str(gmsh_log_path),
            "mesh3d_watchdog": str(mesh3d_watchdog_path),
            "mesh3d_watchdog_sample": str(mesh3d_watchdog_sample_path),
        }
        _write_json(metadata_path, mesh_handoff)
        _write_json(marker_summary_path, marker_summary)
        return {
            "status": "success",
            "failure_code": None,
            "backend_result": {
                "status": "success",
                "failure_code": None,
                "backend": "gmsh",
                "backend_capability": "sheet_lifting_surface_meshing",
                "meshing_route": "gmsh_thin_sheet_surface",
                "geometry_family": frozen_mesh_handoff.get("geometry_family"),
                "geometry_source": frozen_mesh_handoff.get("geometry_source"),
                "geometry_provider": frozen_mesh_handoff.get("geometry_provider"),
                "route_stage": "baseline",
                "mesh_format": "msh",
                "units": frozen_mesh_handoff.get("units", "m"),
                "body_bounds": frozen_mesh_handoff.get("body_bounds"),
                "farfield_bounds": frozen_mesh_handoff.get("farfield_bounds"),
                "artifacts": mesh_handoff["artifacts"],
                "marker_summary": marker_summary,
                "physical_groups": physical_groups,
                "mesh_stats": mesh_stats,
                "mesh_handoff": mesh_handoff,
            },
            "mesh3d_watchdog": mesh3d_watchdog,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "failure_code": "surface_frozen_regenerate_failed",
            "error": str(exc),
        }
    finally:
        if logger_started:
            try:
                gmsh.logger.stop()
            except Exception:
                pass
        if initialized:
            gmsh.finalize()


def _run_surface_frozen_candidate_job(config: MeshJobConfig) -> dict[str, Any]:
    _prepare_out_dir(config.out_dir)
    frozen_geometry = config.metadata.get("_frozen_geometry", {})
    frozen_mesh_handoff_path = _resolve_path(config.metadata["_frozen_mesh_handoff_path"])
    surface_mesh_path = _resolve_path(config.metadata["_frozen_surface_mesh_path"])
    frozen_mesh_handoff = _load_json(frozen_mesh_handoff_path)
    backend_result = _mesh_handoff_from_surface_frozen_regenerate(
        config,
        frozen_mesh_handoff=frozen_mesh_handoff,
        surface_mesh_path=surface_mesh_path,
    )
    if backend_result.get("status") != "success":
        result = {
            "status": "failed",
            "failure_code": backend_result.get("failure_code") or "meshing_failed",
            "component": config.component,
            "geometry": str(config.geometry),
            "normalized_geometry": frozen_geometry.get("normalized_geometry_path"),
            "geometry_source": frozen_geometry.get("geometry_source"),
            "geometry_provider": frozen_geometry.get("geometry_provider"),
            "geometry_family": frozen_mesh_handoff.get("geometry_family"),
            "mesh": {},
            "run": backend_result,
            "quality": {"ok": False},
            "attempts": 1,
            "error": backend_result.get("error"),
        }
        write_json_report(config.out_dir / "report.json", result)
        write_markdown_report(config.out_dir / "report.md", result)
        return result

    mesh_handoff_payload = backend_result["backend_result"]["mesh_handoff"]
    mesh_summary = _mesh_summary(backend_result)
    if _volume_element_count_from_mesh_summary(mesh_summary) <= 0:
        result = {
            "status": "failed",
            "failure_code": "surface_frozen_no_volume_elements",
            "component": config.component,
            "geometry": str(config.geometry),
            "normalized_geometry": frozen_geometry.get("normalized_geometry_path"),
            "geometry_source": frozen_geometry.get("geometry_source"),
            "geometry_provider": frozen_geometry.get("geometry_provider"),
            "geometry_family": frozen_mesh_handoff.get("geometry_family"),
            "mesh": mesh_summary,
            "run": backend_result,
            "quality": {"ok": False},
            "attempts": 1,
            "error": "surface-frozen regenerate route did not produce any 3D fluid volume elements",
        }
        write_json_report(config.out_dir / "report.json", result)
        write_markdown_report(config.out_dir / "report.md", result)
        return result
    su2 = run_baseline_case(
        mesh_handoff_payload,
        config.su2,
        config.out_dir / "artifacts" / "su2",
        source_root=Path.cwd(),
    )
    status = "success" if su2.get("run_status") == "completed" else "failed"
    result = {
        "status": status,
        "failure_code": None if status == "success" else su2.get("failure_code") or "su2_run_failed",
        "component": config.component,
        "geometry": str(config.geometry),
        "normalized_geometry": frozen_geometry.get("normalized_geometry_path"),
        "geometry_source": frozen_geometry.get("geometry_source"),
        "geometry_provider": frozen_geometry.get("geometry_provider"),
        "geometry_family": frozen_mesh_handoff.get("geometry_family"),
        "mesh": mesh_summary,
        "run": backend_result,
        "quality": {"ok": True},
        "attempts": 1,
        "su2": su2,
    }
    if su2.get("convergence_gate") is not None:
        result["convergence"] = su2["convergence_gate"]
    write_json_report(config.out_dir / "report.json", result)
    write_markdown_report(config.out_dir / "report.md", result)
    return result


def run_job(config: MeshJobConfig) -> dict[str, Any]:
    frozen_surface_mesh = config.metadata.get("_frozen_surface_mesh_path") if isinstance(config.metadata, dict) else None
    if isinstance(frozen_surface_mesh, str):
        return _run_surface_frozen_candidate_job(config)
    frozen_geometry = config.metadata.get("_frozen_geometry") if isinstance(config.metadata, dict) else None
    if isinstance(frozen_geometry, dict):
        return _run_job_with_frozen_geometry(config, frozen_geometry)
    return _pipeline_run_job(config)


def compute_wall_region_element_stats(mesh_path: str | Path, marker_name: str = "aircraft") -> dict[str, Any]:
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        return {
            "marker_name": marker_name,
            "error": str(exc),
            "aircraft_boundary_node_count": None,
            "wall_adjacent_volume_element_count": None,
            "wall_adjacent_volume_fraction": None,
        }

    mesh_path = _resolve_path(mesh_path)
    initialized = False
    try:
        gmsh.initialize()
        initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(str(mesh_path))

        physical_tag = None
        for dim, tag in gmsh.model.getPhysicalGroups():
            if int(dim) != 2:
                continue
            if gmsh.model.getPhysicalName(int(dim), int(tag)) == marker_name:
                physical_tag = int(tag)
                break
        if physical_tag is None:
            return {
                "marker_name": marker_name,
                "error": f"physical group not found: {marker_name}",
                "aircraft_boundary_node_count": 0,
                "wall_adjacent_volume_element_count": 0,
                "wall_adjacent_volume_fraction": 0.0,
            }

        boundary_nodes: set[int] = set()
        for entity_tag in gmsh.model.getEntitiesForPhysicalGroup(2, physical_tag):
            element_types, _, node_tags_blocks = gmsh.model.mesh.getElements(2, int(entity_tag))
            for element_type, node_tags in zip(element_types, node_tags_blocks):
                _, _, _, num_nodes, _, _ = gmsh.model.mesh.getElementProperties(int(element_type))
                for start in range(0, len(node_tags), num_nodes):
                    boundary_nodes.update(int(node_tag) for node_tag in node_tags[start:start + num_nodes])

        wall_adjacent_volume_elements = 0
        total_volume_elements = 0
        for entity_dim, entity_tag in gmsh.model.getEntities(3):
            if int(entity_dim) != 3:
                continue
            element_types, _, node_tags_blocks = gmsh.model.mesh.getElements(3, int(entity_tag))
            for element_type, node_tags in zip(element_types, node_tags_blocks):
                _, _, _, num_nodes, _, _ = gmsh.model.mesh.getElementProperties(int(element_type))
                if num_nodes <= 0:
                    continue
                for start in range(0, len(node_tags), num_nodes):
                    total_volume_elements += 1
                    element_nodes = node_tags[start:start + num_nodes]
                    if any(int(node_tag) in boundary_nodes for node_tag in element_nodes):
                        wall_adjacent_volume_elements += 1

        wall_adjacent_fraction = (
            float(wall_adjacent_volume_elements / total_volume_elements)
            if total_volume_elements > 0
            else 0.0
        )
        return {
            "marker_name": marker_name,
            "aircraft_boundary_node_count": len(boundary_nodes),
            "wall_adjacent_volume_element_count": wall_adjacent_volume_elements,
            "wall_adjacent_volume_fraction": wall_adjacent_fraction,
        }
    finally:
        if initialized:
            gmsh.finalize()


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
    return {
        "iterative_status": iterative_gate.get("status"),
        "residual_trend_status": residual_trend.get("status"),
        "median_log_drop": (residual_trend.get("observed", {}) or {}).get("median_log_drop"),
        "warnings": iterative_gate.get("warnings", []),
    }


def _drag_anchor_cd(reynolds_number: float) -> float:
    if reynolds_number <= 0.0:
        return 0.02
    flat_plate_cf = 1.328 / math.sqrt(reynolds_number)
    return max(10.0 * flat_plate_cf, 0.015)


def _drag_reasonableness(candidate_cd: Any, coarse_cd: Any, reynolds_number: float) -> dict[str, Any]:
    if not isinstance(candidate_cd, (int, float)) or not math.isfinite(float(candidate_cd)) or float(candidate_cd) <= 0.0:
        return {
            "candidate_cd": candidate_cd,
            "coarse_cd": coarse_cd,
            "anchor_cd": _drag_anchor_cd(reynolds_number),
            "candidate_distance_to_anchor_log10": None,
            "coarse_distance_to_anchor_log10": None,
            "moved_toward_more_plausible_magnitude": False,
            "note": "Candidate drag was not a positive finite value.",
        }
    anchor_cd = _drag_anchor_cd(reynolds_number)
    candidate_distance = abs(math.log10(float(candidate_cd)) - math.log10(anchor_cd))
    coarse_distance = (
        abs(math.log10(float(coarse_cd)) - math.log10(anchor_cd))
        if isinstance(coarse_cd, (int, float)) and math.isfinite(float(coarse_cd)) and float(coarse_cd) > 0.0
        else None
    )
    improved = coarse_distance is None or candidate_distance < coarse_distance
    return {
        "candidate_cd": float(candidate_cd),
        "coarse_cd": coarse_cd,
        "anchor_cd": anchor_cd,
        "candidate_distance_to_anchor_log10": candidate_distance,
        "coarse_distance_to_anchor_log10": coarse_distance,
        "moved_toward_more_plausible_magnitude": improved,
        "note": "Anchor CD is a low-Re engineering order-of-magnitude heuristic from 10x laminar flat-plate Cf, not ground truth.",
    }


def _summarize_baseline_compare(
    *,
    run_result: dict[str, Any],
    elapsed_seconds: float,
    mesh_handoff: dict[str, Any],
    reynolds_number: float,
    out_dir: Path,
) -> dict[str, Any]:
    mesh_path = _resolve_path(mesh_handoff["artifacts"]["mesh"])
    mesh_summary = {
        "contract": "near_wall_candidate_mesh_summary.v1",
        "candidate_name": "coarse_compare",
        "mesh_path": str(mesh_path),
        "mesh_metadata_path": str(_resolve_path(mesh_handoff["artifacts"]["mesh_metadata"])),
        "node_count": mesh_handoff.get("mesh_stats", {}).get("node_count"),
        "element_count": mesh_handoff.get("mesh_stats", {}).get("element_count"),
        "surface_element_count": mesh_handoff.get("mesh_stats", {}).get("surface_element_count"),
        "volume_element_count": mesh_handoff.get("mesh_stats", {}).get("volume_element_count"),
        "wall_region_element_stats": compute_wall_region_element_stats(mesh_path),
        "near_wall_field": (
            (mesh_handoff.get("mesh_field", {}) or {}).get("volume_smoke_decoupled", {}).get("near_body_shell", {})
        ),
        "quality_metrics": mesh_handoff.get("quality_metrics", {}),
        "runtime_seconds": elapsed_seconds,
    }
    su2_summary = {
        "contract": "near_wall_su2_case_summary.v1",
        "candidate_name": "coarse_compare",
        "run_status": run_result.get("run_status"),
        "runtime_cfg_path": run_result.get("runtime_cfg_path"),
        "history_path": run_result.get("history_path"),
        "final_iteration": run_result.get("final_iteration"),
        "coefficients": run_result.get("final_coefficients", {}),
        "residual_behavior": _residual_behavior_summary(run_result),
        "solver_warnings": _solver_warnings((run_result.get("case_output_paths") or {}).get("solver_log")),
        "runtime_seconds": elapsed_seconds,
        "reynolds_number_case_level": reynolds_number,
    }
    _write_json(out_dir / "candidate_mesh_summaries" / "coarse_compare.json", mesh_summary)
    _write_json(out_dir / "su2_case_summaries" / "coarse_compare.json", su2_summary)
    return {
        "mesh_summary": mesh_summary,
        "su2_summary": su2_summary,
    }


def _summarize_candidate(
    *,
    candidate: dict[str, Any],
    result: dict[str, Any],
    elapsed_seconds: float,
    coarse_compare_cd: Any,
    reynolds_number: float,
    frozen_geometry_path: str,
    out_dir: Path,
) -> dict[str, Any]:
    mesh_summary_path = out_dir / "candidate_mesh_summaries" / f"{candidate['name']}.json"
    su2_summary_path = out_dir / "su2_case_summaries" / f"{candidate['name']}.json"

    mesh_summary = {
        "contract": "near_wall_candidate_mesh_summary.v1",
        "candidate_name": candidate["name"],
        "candidate_spec": candidate,
        "status": result.get("status"),
        "failure_code": result.get("failure_code"),
        "mesh_path": (result.get("mesh") or {}).get("mesh_artifact"),
        "mesh_metadata_path": (result.get("mesh") or {}).get("metadata_path"),
        "node_count": (result.get("mesh") or {}).get("node_count"),
        "element_count": (result.get("mesh") or {}).get("element_count"),
        "surface_element_count": (result.get("mesh") or {}).get("surface_element_count"),
        "volume_element_count": (result.get("mesh") or {}).get("volume_element_count"),
        "wall_region_element_stats": compute_wall_region_element_stats((result.get("mesh") or {}).get("mesh_artifact")),
        "runtime_seconds": elapsed_seconds,
        "geometry_frozen": (
            str(_resolve_path((result.get("normalized_geometry") or frozen_geometry_path)))
            == str(_resolve_path(frozen_geometry_path))
        ),
    }

    su2_result = result.get("su2", {}) or {}
    run_status = su2_result.get("run_status") or ("not_run" if not su2_result else None)
    drag_reasonableness = _drag_reasonableness(
        su2_result.get("final_coefficients", {}).get("cd"),
        coarse_compare_cd,
        reynolds_number,
    )
    su2_summary = {
        "contract": "near_wall_su2_case_summary.v1",
        "candidate_name": candidate["name"],
        "run_status": run_status,
        "runtime_cfg_path": su2_result.get("runtime_cfg_path"),
        "history_path": su2_result.get("history_path"),
        "final_iteration": su2_result.get("final_iteration"),
        "coefficients": su2_result.get("final_coefficients", {}),
        "residual_behavior": _residual_behavior_summary(su2_result),
        "solver_warnings": _solver_warnings((su2_result.get("case_output_paths") or {}).get("solver_log")),
        "runtime_seconds": elapsed_seconds,
        "reynolds_number_case_level": reynolds_number,
        "drag_reasonableness": drag_reasonableness,
    }
    _write_json(mesh_summary_path, mesh_summary)
    _write_json(su2_summary_path, su2_summary)
    return {
        "mesh_summary": mesh_summary,
        "su2_summary": su2_summary,
        "result": result,
    }


def _selection_gate(candidate_summary: dict[str, Any], coarse_compare: dict[str, Any]) -> dict[str, Any]:
    mesh_summary = candidate_summary["mesh_summary"]
    su2_summary = candidate_summary["su2_summary"]
    residual_behavior = su2_summary["residual_behavior"]
    drag_reasonableness = su2_summary["drag_reasonableness"]
    coarse_mesh = coarse_compare["mesh_summary"]

    volume_count = _volume_element_count_from_mesh_summary(mesh_summary)
    mesh_generation_success = (
        candidate_summary["result"].get("status") == "success"
        and mesh_summary["mesh_path"] is not None
        and volume_count > 0
    )
    solver_success = su2_summary.get("run_status") == "completed"
    residual_not_much_worse = solver_success and residual_behavior.get("iterative_status") != "fail"
    drag_more_reasonable = bool(drag_reasonableness.get("moved_toward_more_plausible_magnitude"))
    node_count = mesh_summary.get("node_count") or 0
    coarse_node_count = coarse_mesh.get("node_count") or 0
    coarse_volume_count = coarse_mesh.get("volume_element_count") or 0
    element_count_bounded = (
        node_count <= max(coarse_node_count * 6, coarse_node_count + 300000)
        and volume_count <= max(coarse_volume_count * 6, coarse_volume_count + 400000)
    )
    checks = {
        "geometry_frozen": bool(mesh_summary.get("geometry_frozen")),
        "mesh_generation_success": bool(mesh_generation_success),
        "solver_success": bool(solver_success),
        "residual_not_much_worse": bool(residual_not_much_worse),
        "drag_more_reasonable": bool(drag_more_reasonable),
        "element_count_bounded": bool(element_count_bounded),
    }
    pass_candidate = all(checks.values())
    return {
        "pass": pass_candidate,
        "checks": checks,
        "engineering_reason": (
            "Candidate stays on the frozen geometry, ran to completion, remained bounded, and moved CD toward a more plausible low-Re starter-mesh magnitude."
            if pass_candidate
            else "Candidate failed at least one selection gate for the next near-wall baseline."
        ),
    }


def _winner_payload(
    *,
    candidate_summary: dict[str, Any],
    selection: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    payload = {
        "contract": "shell_v3_near_wall_cfd_baseline_candidate.v1",
        "status": "success",
        "candidate_name": candidate_summary["mesh_summary"]["candidate_name"],
        "selection": selection,
        "artifacts": {
            "mesh_summary": str(out_dir / "candidate_mesh_summaries" / f"{candidate_summary['mesh_summary']['candidate_name']}.json"),
            "su2_case_summary": str(out_dir / "su2_case_summaries" / f"{candidate_summary['mesh_summary']['candidate_name']}.json"),
        },
    }
    _write_json(out_dir / "shell_v3_near_wall_cfd_baseline_candidate.json", payload)
    return payload


def _no_go_payload(
    *,
    candidate_summaries: list[dict[str, Any]],
    coarse_compare: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    all_zero_volume = all(
        (summary["mesh_summary"].get("volume_element_count") or 0) <= 0
        for summary in candidate_summaries
    )
    payload = {
        "contract": "near_wall_no_go_summary.v1",
        "status": "failed",
        "coarse_compare_cd": coarse_compare["su2_summary"]["coefficients"].get("cd"),
        "primary_blocker": (
            "Frozen exported wall/farfield mesh route did not regenerate any 3D fluid volume elements for the bounded near-wall candidates."
            if all_zero_volume
            else "No bounded near-wall candidate passed the mesh, solver, residual, and drag reasonableness gates."
        ),
        "candidate_evaluations": [
            {
                "candidate_name": summary["mesh_summary"]["candidate_name"],
                "selection": summary["selection"],
                "status": summary["mesh_summary"]["status"],
                "failure_code": summary["mesh_summary"]["failure_code"],
                "coefficients": summary["su2_summary"]["coefficients"],
                "residual_behavior": summary["su2_summary"]["residual_behavior"],
                "mesh": {
                    "node_count": summary["mesh_summary"]["node_count"],
                    "volume_element_count": summary["mesh_summary"]["volume_element_count"],
                },
            }
            for summary in candidate_summaries
        ],
        "next_mainline": (
            "Keep the frozen shell_v3 geometry and build a tetra near-wall route that preserves a 3D-remesh-capable fluid volume boundary contract before re-running drag comparisons."
            if all_zero_volume
            else "Keep the frozen shell_v3 geometry and continue only on bounded wall-refined tetra near-wall meshing until one candidate improves drag plausibility without blowing up element count or residual behavior."
        ),
    }
    _write_json(out_dir / "near_wall_no_go_summary.json", payload)
    return payload


def run_shell_v3_near_wall_study(
    manifest_path: str | Path,
    *,
    solver_summary_path: str | Path | None = None,
    out_dir: str | Path,
    source_root: Path | None = None,
) -> dict[str, Any]:
    out_dir = _resolve_path(out_dir, source_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidate_mesh_summaries").mkdir(parents=True, exist_ok=True)
    (out_dir / "su2_case_summaries").mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates").mkdir(parents=True, exist_ok=True)

    frozen_context = build_frozen_cfd_context(
        manifest_path,
        solver_summary_path=solver_summary_path,
        out_dir=out_dir,
        source_root=source_root,
    )
    capability_report = assess_near_wall_capability(frozen_context, out_dir=out_dir, source_root=source_root)

    mesh_handoff = _load_json(frozen_context["current_mesh_metadata_path"])
    runtime = _fixed_runtime("shell_v3_alpha0_coarse_compare")
    start = time.perf_counter()
    coarse_compare_run = run_baseline_case(
        mesh_handoff,
        runtime,
        out_dir / "artifacts" / "su2" / "coarse_compare",
        source_root=source_root,
    )
    coarse_compare = _summarize_baseline_compare(
        run_result=coarse_compare_run,
        elapsed_seconds=time.perf_counter() - start,
        mesh_handoff=mesh_handoff,
        reynolds_number=_case_reynolds_number(),
        out_dir=out_dir,
    )

    coarse_compare_cd = coarse_compare["su2_summary"]["coefficients"].get("cd")
    frozen_geometry_path = frozen_context["frozen_geometry"]["normalized_geometry_path"]
    candidate_summaries: list[dict[str, Any]] = []

    for candidate in _candidate_specs(mesh_handoff):
        config = _frozen_candidate_config(mesh_handoff=mesh_handoff, candidate=candidate, out_dir=out_dir)
        start = time.perf_counter()
        result = run_job(config)
        summary = _summarize_candidate(
            candidate=candidate,
            result=result,
            elapsed_seconds=time.perf_counter() - start,
            coarse_compare_cd=coarse_compare_cd,
            reynolds_number=_case_reynolds_number(),
            frozen_geometry_path=frozen_geometry_path,
            out_dir=out_dir,
        )
        summary["selection"] = _selection_gate(summary, coarse_compare)
        candidate_summaries.append(summary)

    passing = [summary for summary in candidate_summaries if summary["selection"]["pass"]]
    passing.sort(
        key=lambda summary: (
            summary["su2_summary"]["drag_reasonableness"].get("candidate_distance_to_anchor_log10")
            if summary["su2_summary"]["drag_reasonableness"].get("candidate_distance_to_anchor_log10") is not None
            else float("inf"),
            summary["mesh_summary"].get("volume_element_count") or float("inf"),
        )
    )

    if capability_report["conclusion"] == "prism_layer_feasible" and not passing:
        no_go = _no_go_payload(candidate_summaries=candidate_summaries, coarse_compare=coarse_compare, out_dir=out_dir)
        return {
            "status": "failed",
            "result_kind": "near_wall_no_go_summary",
            "artifacts": {
                "frozen_cfd_context": str(out_dir / "frozen_cfd_context.json"),
                "near_wall_capability_report": str(out_dir / "near_wall_capability_report.json"),
                "near_wall_no_go_summary": str(out_dir / "near_wall_no_go_summary.json"),
            },
            "no_go": no_go,
        }

    if passing:
        winner = _winner_payload(candidate_summary=passing[0], selection=passing[0]["selection"], out_dir=out_dir)
        return {
            "status": "success",
            "result_kind": "shell_v3_near_wall_cfd_baseline_candidate",
            "artifacts": {
                "frozen_cfd_context": str(out_dir / "frozen_cfd_context.json"),
                "near_wall_capability_report": str(out_dir / "near_wall_capability_report.json"),
                "shell_v3_near_wall_cfd_baseline_candidate": str(out_dir / "shell_v3_near_wall_cfd_baseline_candidate.json"),
            },
            "winner": winner,
        }

    no_go = _no_go_payload(candidate_summaries=candidate_summaries, coarse_compare=coarse_compare, out_dir=out_dir)
    return {
        "status": "failed",
        "result_kind": "near_wall_no_go_summary",
        "artifacts": {
            "frozen_cfd_context": str(out_dir / "frozen_cfd_context.json"),
            "near_wall_capability_report": str(out_dir / "near_wall_capability_report.json"),
            "near_wall_no_go_summary": str(out_dir / "near_wall_no_go_summary.json"),
        },
        "no_go": no_go,
    }
