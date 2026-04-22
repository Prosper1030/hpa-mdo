from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..convergence import evaluate_baseline_convergence_gate
from ..gmsh_runtime import GmshRuntimeError, load_gmsh
from ..reference_geometry import is_zero_vector, load_openvsp_reference_data
from ..schema import (
    MeshHandoff,
    Point3D,
    SU2CaseArtifacts,
    SU2CaseHandoff,
    SU2ForceSurfaceMarkerGroup,
    SU2ForceSurfaceProvenance,
    SU2GateCheck,
    SU2HistorySummary,
    SU2ProvenanceGates,
    SU2ReferenceGeometry,
    SU2ReferenceQuantityProvenance,
    SU2RuntimeConfig,
)


class SU2BackendError(RuntimeError):
    """Raised when the package-native SU2 baseline route cannot be materialized."""


def _resolve_path(path: Path, source_root: Path | None) -> Path:
    if path.is_absolute():
        return path
    root = (source_root or Path.cwd()).resolve()
    return (root / path).resolve()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _require_marker(mesh_handoff: MeshHandoff, name: str) -> dict[str, Any]:
    marker = mesh_handoff.marker_summary.get(name, {})
    if not marker.get("exists", False):
        raise SU2BackendError(f"mesh_handoff missing required marker: {name}")
    return marker


def _overall_gate_status(*statuses: str) -> str:
    if any(status == "fail" for status in statuses):
        return "fail"
    if any(status == "warn" for status in statuses):
        return "warn"
    return "pass"


def _baseline_reference_geometry(mesh_handoff: MeshHandoff) -> SU2ReferenceGeometry:
    bounds = mesh_handoff.body_bounds
    x_span = max(bounds.x_max - bounds.x_min, 1e-6)
    y_span = max(bounds.y_max - bounds.y_min, 1e-6)

    return SU2ReferenceGeometry(
        ref_area=0.5 * x_span * y_span,
        ref_length=x_span,
        ref_origin_moment=Point3D(
            x=0.5 * (bounds.x_min + bounds.x_max),
            y=0.5 * (bounds.y_min + bounds.y_max),
            z=0.5 * (bounds.z_min + bounds.z_max),
        ),
        area_provenance=SU2ReferenceQuantityProvenance(
            source_category="baseline_envelope_derived",
            method="mesh.body_bounds.half_x_span_times_y_span",
            confidence="low",
            details={"x_span": x_span, "y_span": y_span},
        ),
        length_provenance=SU2ReferenceQuantityProvenance(
            source_category="baseline_envelope_derived",
            method="mesh.body_bounds.x_span",
            confidence="low",
            details={"x_span": x_span},
        ),
        moment_origin_provenance=SU2ReferenceQuantityProvenance(
            source_category="baseline_envelope_derived",
            method="mesh.body_bounds.centroid",
            confidence="low",
            details={
                "x_center": 0.5 * (bounds.x_min + bounds.x_max),
                "y_center": 0.5 * (bounds.y_min + bounds.y_max),
                "z_center": 0.5 * (bounds.z_min + bounds.z_max),
            },
        ),
        gate_status="warn",
        confidence="low",
        warnings=[
            "reference_quantities_use_baseline_envelope_proxy",
            "geometry_derived_reference_unavailable_for_current_contract",
        ],
        notes=[
            "Baseline-only reference geometry derived from mesh_handoff.body_bounds.",
            "REF_AREA uses 0.5 * body x-span * body y-span for thin_sheet_aircraft_assembly.",
            "REF_ORIGIN_MOMENT uses the body-bounds centroid and is not yet CG-calibrated.",
        ],
    )

def _load_vsp_reference_data(source_path: Path) -> dict[str, Any] | None:
    return load_openvsp_reference_data(source_path)


def _mesh_handoff_provider_reference_data(mesh_handoff: MeshHandoff) -> dict[str, Any] | None:
    provider = mesh_handoff.provenance.get("provider", {})
    if not isinstance(provider, dict):
        return None
    provider_provenance = provider.get("provenance", {})
    if not isinstance(provider_provenance, dict):
        return None
    reference_geometry = provider_provenance.get("reference_geometry")
    if not isinstance(reference_geometry, dict):
        return None
    return reference_geometry


def _user_declared_reference_geometry(runtime: SU2RuntimeConfig) -> SU2ReferenceGeometry | None:
    override = runtime.reference_override
    if override is None:
        return None
    return SU2ReferenceGeometry(
        ref_area=override.ref_area,
        ref_length=override.ref_length,
        ref_origin_moment=override.ref_origin_moment,
        area_provenance=SU2ReferenceQuantityProvenance(
            source_category="user_declared",
            method="runtime.reference_override.ref_area",
            confidence="high",
            source_path=override.source_path,
            details={"source_label": override.source_label},
        ),
        length_provenance=SU2ReferenceQuantityProvenance(
            source_category="user_declared",
            method="runtime.reference_override.ref_length",
            confidence="high",
            source_path=override.source_path,
            details={"source_label": override.source_label},
        ),
        moment_origin_provenance=SU2ReferenceQuantityProvenance(
            source_category="user_declared",
            method="runtime.reference_override.ref_origin_moment",
            confidence="high",
            source_path=override.source_path,
            details={"source_label": override.source_label},
        ),
        gate_status="pass",
        confidence="high",
        notes=[f"Reference quantities supplied via {override.source_label}."],
    )


def _geometry_reference_geometry(
    source_path: Path,
    *,
    reference_data: dict[str, Any] | None = None,
) -> SU2ReferenceGeometry | None:
    if reference_data is None:
        reference_data = _load_vsp_reference_data(source_path)
    if reference_data is None:
        return None
    warnings = list(reference_data.get("warnings", []))
    if is_zero_vector(reference_data.get("ref_origin_moment", {})):
        warnings.append("geometry_derived_moment_origin_is_zero_vector")
    gate_status = "pass" if not warnings else "warn"
    confidence = "high" if gate_status == "pass" else "medium"
    shared_details = {
        "reference_wing_id": reference_data.get("reference_wing_id"),
        "reference_wing_name": reference_data.get("reference_wing_name"),
        "settings": reference_data.get("settings", {}),
        "wing_quantities": reference_data.get("wing_quantities", {}),
    }
    return SU2ReferenceGeometry(
        ref_area=float(reference_data["ref_area"]),
        ref_length=float(reference_data["ref_length"]),
        ref_origin_moment=Point3D.model_validate(reference_data["ref_origin_moment"]),
        area_provenance=SU2ReferenceQuantityProvenance(
            source_category="geometry_derived",
            method=str(reference_data["area_method"]),
            confidence=confidence,
            source_path=source_path,
            source_units="m",
            details=shared_details,
            warnings=warnings,
        ),
        length_provenance=SU2ReferenceQuantityProvenance(
            source_category="geometry_derived",
            method=str(reference_data["length_method"]),
            confidence=confidence,
            source_path=source_path,
            source_units="m",
            details=shared_details,
            warnings=warnings,
        ),
        moment_origin_provenance=SU2ReferenceQuantityProvenance(
            source_category="geometry_derived",
            method=str(reference_data["moment_method"]),
            confidence="medium",
            source_path=source_path,
            source_units="m",
            details={"settings": reference_data.get("settings", {})},
            warnings=warnings,
        ),
        gate_status=gate_status,
        confidence=confidence,
        warnings=warnings,
        notes=[
            "Reference quantities resolved from source OpenVSP geometry.",
        ],
    )


def _resolve_reference_geometry(
    mesh_handoff: MeshHandoff,
    runtime: SU2RuntimeConfig,
    *,
    source_root: Path | None = None,
) -> SU2ReferenceGeometry:
    source_path = _resolve_path(mesh_handoff.source_path, source_root)
    if runtime.reference_mode == "user_declared":
        reference = _user_declared_reference_geometry(runtime)
        if reference is not None:
            return reference
        baseline = _baseline_reference_geometry(mesh_handoff)
        baseline.gate_status = "fail"
        baseline.warnings.insert(0, "reference_mode=user_declared but reference_override was not provided")
        return baseline

    if runtime.reference_mode in {"auto", "geometry_derived"}:
        provider_reference = _mesh_handoff_provider_reference_data(mesh_handoff)
        reference = _geometry_reference_geometry(source_path, reference_data=provider_reference)
        if reference is None:
            reference = _geometry_reference_geometry(source_path)
        if reference is not None:
            return reference
        baseline = _baseline_reference_geometry(mesh_handoff)
        if runtime.reference_mode == "geometry_derived":
            baseline.gate_status = "fail"
            baseline.warnings.insert(0, "reference_mode=geometry_derived but no supported geometry-derived reference was available")
        return baseline

    return _baseline_reference_geometry(mesh_handoff)


def _physical_group_lookup(mesh_handoff: MeshHandoff) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for key, group in mesh_handoff.physical_groups.items():
        if not isinstance(group, dict):
            continue
        lookup[str(key)] = group
        physical_name = group.get("physical_name")
        if isinstance(physical_name, str) and physical_name:
            lookup[physical_name] = group
    return lookup


def _force_surface_group(marker_name: str, group: dict[str, Any] | None) -> SU2ForceSurfaceMarkerGroup | None:
    if group is None:
        return None
    return SU2ForceSurfaceMarkerGroup(
        marker_name=marker_name,
        physical_name=str(group.get("physical_name", marker_name)),
        physical_tag=group.get("physical_tag"),
        dimension=group.get("dimension"),
        entity_count=group.get("entity_count"),
        element_count=group.get("element_count"),
    )


def _build_force_surface_provenance(
    mesh_handoff: MeshHandoff,
    markers: dict[str, Any],
) -> SU2ForceSurfaceProvenance:
    monitoring_markers = list(markers.get("monitoring", []))
    plotting_markers = list(markers.get("plotting", []))
    euler_markers = list(markers.get("euler", []))
    wall_marker = str(markers["wall"])
    group_lookup = _physical_group_lookup(mesh_handoff)

    source_groups: list[SU2ForceSurfaceMarkerGroup] = []
    missing: list[str] = []
    for marker_name in monitoring_markers:
        group = _force_surface_group(marker_name, group_lookup.get(marker_name))
        if group is None:
            missing.append(marker_name)
            continue
        source_groups.append(group)

    primary_group = _force_surface_group(wall_marker, group_lookup.get(wall_marker))
    provider_topology = mesh_handoff.provenance.get("provider", {}).get("topology", {})
    component_labels_present = provider_topology.get("labels_present")
    component_label_schema = provider_topology.get("label_schema")
    body_count = provider_topology.get("body_count")

    matches_wall_marker = bool(monitoring_markers) and set(monitoring_markers) == {wall_marker}
    matches_entire_aircraft_wall = matches_wall_marker and len(monitoring_markers) == 1 and primary_group is not None
    scope = "whole_aircraft_wall" if matches_entire_aircraft_wall else "unknown"
    component_provenance = "not_available"
    notes: list[str] = []
    warnings: list[str] = []
    if component_labels_present:
        if len(source_groups) > 1:
            component_provenance = "component_groups_mapped"
        else:
            component_provenance = "geometry_labels_present_but_not_mapped"
            notes.append("geometry carried component labels, but force monitoring collapsed to a whole-aircraft wall marker")

    gate_status = "pass"
    confidence = "medium"
    if missing:
        gate_status = "fail"
        confidence = "low"
        scope = "unknown"
        warnings.append(f"missing_force_surface_groups={','.join(missing)}")

    return SU2ForceSurfaceProvenance(
        gate_status=gate_status,
        confidence=confidence,
        source_kind="mesh_physical_group",
        wall_marker=wall_marker,
        monitoring_markers=monitoring_markers,
        plotting_markers=plotting_markers,
        euler_markers=euler_markers,
        source_groups=source_groups,
        primary_group=primary_group,
        matches_wall_marker=matches_wall_marker,
        matches_entire_aircraft_wall=matches_entire_aircraft_wall,
        scope=scope,
        body_count=body_count,
        component_labels_present_in_geometry=component_labels_present,
        component_label_schema=component_label_schema,
        component_provenance=component_provenance,
        warnings=warnings,
        notes=notes,
    )


def _build_provenance_gates(
    reference_geometry: SU2ReferenceGeometry,
    force_surface_provenance: SU2ForceSurfaceProvenance,
) -> SU2ProvenanceGates:
    return SU2ProvenanceGates(
        overall_status=_overall_gate_status(reference_geometry.gate_status, force_surface_provenance.gate_status),
        reference_quantities=SU2GateCheck(
            status=reference_geometry.gate_status,
            confidence=reference_geometry.confidence,
            warnings=reference_geometry.warnings,
            notes=reference_geometry.notes,
        ),
        force_surface=SU2GateCheck(
            status=force_surface_provenance.gate_status,
            confidence=force_surface_provenance.confidence,
            warnings=force_surface_provenance.warnings,
            notes=force_surface_provenance.notes,
        ),
        warnings=[*reference_geometry.warnings, *force_surface_provenance.warnings],
    )


def _velocity_components(velocity_mps: float, alpha_deg: float) -> tuple[float, float, float]:
    alpha_rad = math.radians(float(alpha_deg))
    return (
        float(velocity_mps * math.cos(alpha_rad)),
        0.0,
        float(velocity_mps * math.sin(alpha_rad)),
    )


def _cfg_text(
    runtime: SU2RuntimeConfig,
    reference: SU2ReferenceGeometry,
    markers: dict[str, Any],
) -> str:
    vx, vy, vz = _velocity_components(runtime.velocity_mps, runtime.alpha_deg)
    wall_boundary_lines = (
        [f"MARKER_EULER= ( {', '.join(markers['euler'])} )"]
        if runtime.wall_boundary_condition == "euler"
        else [f"MARKER_HEATFLUX= ( {markers['wall']}, 0.0 )"]
    )
    lines = [
        "% Auto-generated by hpa_meshing.adapters.su2_backend",
        "% Package-native baseline SU2 case built from mesh_handoff.v1",
        f"% alpha={runtime.alpha_deg:.6f} deg",
        f"SOLVER= {runtime.solver}",
        "KIND_TURB_MODEL= NONE",
        "MATH_PROBLEM= DIRECT",
        "SYSTEM_MEASUREMENTS= SI",
        "RESTART_SOL= NO",
        f"INC_NONDIM= {runtime.inc_nondim}",
        f"INC_DENSITY_MODEL= {runtime.inc_density_model}",
        f"FLUID_MODEL= {runtime.fluid_model}",
        "VISCOSITY_MODEL= CONSTANT_VISCOSITY",
        f"MU_CONSTANT= {runtime.dynamic_viscosity_pas:.6e}",
        f"INC_DENSITY_INIT= {runtime.density_kgpm3:.6f}",
        f"INC_TEMPERATURE_INIT= {runtime.temperature_k:.6f}",
        f"INC_VELOCITY_INIT= ( {vx:.6f}, {vy:.6f}, {vz:.6f} )",
        f"AOA= {runtime.alpha_deg:.6f}",
        "SIDESLIP_ANGLE= 0.000000",
        f"REF_AREA= {reference.ref_area:.6f}",
        f"REF_LENGTH= {reference.ref_length:.6f}",
        f"REF_ORIGIN_MOMENT_X= {reference.ref_origin_moment.x:.6f}",
        f"REF_ORIGIN_MOMENT_Y= {reference.ref_origin_moment.y:.6f}",
        f"REF_ORIGIN_MOMENT_Z= {reference.ref_origin_moment.z:.6f}",
        "MESH_FILENAME= mesh.su2",
        "MESH_FORMAT= SU2",
        *wall_boundary_lines,
        f"MARKER_MONITORING= ( {', '.join(markers['monitoring'])} )",
        f"MARKER_PLOTTING= ( {', '.join(markers['plotting'])} )",
        f"MARKER_FAR= ( {markers['farfield']} )",
        "NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES",
        "CONV_NUM_METHOD_FLOW= FDS",
        "TIME_DISCRE_FLOW= EULER_IMPLICIT",
        "LINEAR_SOLVER= FGMRES",
        "LINEAR_SOLVER_PREC= ILU",
        f"LINEAR_SOLVER_ERROR= {runtime.linear_solver_error:.0e}",
        f"LINEAR_SOLVER_ITER= {runtime.linear_solver_iterations}",
        f"ITER= {runtime.max_iterations}",
        f"CFL_NUMBER= {runtime.cfl_number:.1f}",
        "CONV_FIELD= DRAG",
        "CONV_RESIDUAL_MINVAL= -9",
        "CONV_STARTITER= 5",
        "CONV_FILENAME= history",
        "TABULAR_FORMAT= CSV",
        "SCREEN_OUTPUT= (INNER_ITER, RMS_RES, AERO_COEFF)",
        "HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF)",
        "OUTPUT_FILES= (RESTART_ASCII, PARAVIEW_ASCII, SURFACE_CSV)",
        "",
    ]
    return "\n".join(lines)


def _mpi_ranks(runtime: SU2RuntimeConfig) -> int:
    return max(1, int(runtime.mpi_ranks))


def _omp_threads_per_rank(runtime: SU2RuntimeConfig) -> int:
    total_cores = max(1, int(runtime.cpu_threads))
    if runtime.parallel_mode == "mpi":
        return max(1, total_cores // _mpi_ranks(runtime))
    return total_cores


def _solver_command(runtime: SU2RuntimeConfig, runtime_cfg_name: str) -> list[str]:
    omp_threads = _omp_threads_per_rank(runtime)
    if runtime.parallel_mode == "mpi":
        return [
            runtime.mpi_launcher,
            "-np",
            str(_mpi_ranks(runtime)),
            runtime.solver_command,
            "-t",
            str(omp_threads),
            runtime_cfg_name,
        ]
    return [
        runtime.solver_command,
        "-t",
        str(omp_threads),
        runtime_cfg_name,
    ]


def _solver_env(runtime: SU2RuntimeConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(_omp_threads_per_rank(runtime))
    return env


def _resolve_launch_requirements(runtime: SU2RuntimeConfig) -> tuple[str | None, str | None]:
    if runtime.parallel_mode == "mpi" and shutil.which(runtime.mpi_launcher) is None:
        return "launcher_not_found", runtime.mpi_launcher
    if shutil.which(runtime.solver_command) is None:
        return "solver_not_found", runtime.solver_command
    return None, None


def _convert_mesh_to_su2(source_mesh: Path, output_mesh: Path, *, thread_count: int = 4) -> None:
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        raise SU2BackendError(str(exc)) from exc

    initialized = False
    try:
        gmsh.initialize()
        initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", float(max(1, int(thread_count))))
        gmsh.open(str(source_mesh))
        gmsh.write(str(output_mesh))
    finally:
        if initialized:
            gmsh.finalize()


def materialize_baseline_case(
    mesh_handoff: MeshHandoff | dict[str, Any],
    runtime: SU2RuntimeConfig,
    case_root: Path,
    *,
    source_root: Path | None = None,
) -> SU2CaseHandoff:
    mesh_handoff = MeshHandoff.model_validate(mesh_handoff)
    aircraft_marker = _require_marker(mesh_handoff, "aircraft")
    farfield_marker = _require_marker(mesh_handoff, "farfield")
    case_dir = case_root / runtime.case_name
    case_dir.mkdir(parents=True, exist_ok=True)

    input_mesh = _resolve_path(mesh_handoff.artifacts.mesh, source_root)
    if not input_mesh.exists():
        raise SU2BackendError(f"mesh_handoff input mesh not found: {input_mesh}")

    source_metadata = _resolve_path(mesh_handoff.artifacts.mesh_metadata, source_root)
    source_marker_summary = _resolve_path(mesh_handoff.artifacts.marker_summary, source_root)

    reference = _resolve_reference_geometry(mesh_handoff, runtime, source_root=source_root)
    markers = {
        "wall": aircraft_marker.get("physical_name", "aircraft"),
        "farfield": farfield_marker.get("physical_name", "farfield"),
        "monitoring": [aircraft_marker.get("physical_name", "aircraft")],
        "plotting": [aircraft_marker.get("physical_name", "aircraft")],
        "euler": [aircraft_marker.get("physical_name", "aircraft")],
    }
    force_surface_provenance = _build_force_surface_provenance(mesh_handoff, markers)
    provenance_gates = _build_provenance_gates(reference, force_surface_provenance)

    artifacts = SU2CaseArtifacts(
        case_dir=case_dir,
        su2_mesh=case_dir / "mesh.su2",
        history=case_dir / "history.csv",
        solver_log=case_dir / "solver.log",
        surface_output=case_dir / "surface.csv",
        restart_output=case_dir / "restart.csv",
        volume_output=case_dir / "vol_solution.vtk",
        contract_path=case_dir / "su2_handoff.json",
    )
    runtime_cfg_path = case_dir / "su2_runtime.cfg"

    _convert_mesh_to_su2(input_mesh, artifacts.su2_mesh, thread_count=runtime.cpu_threads)
    runtime_cfg_path.write_text(_cfg_text(runtime, reference, markers), encoding="utf-8")

    case = SU2CaseHandoff(
        geometry_family=mesh_handoff.geometry_family,
        units=mesh_handoff.units,
        input_mesh_artifact=input_mesh,
        mesh_markers=markers,
        reference_geometry=reference,
        runtime=runtime,
        runtime_cfg_path=runtime_cfg_path,
        case_output_paths=artifacts,
        solver_command=_solver_command(runtime, runtime_cfg_path.name),
        force_surface_provenance=force_surface_provenance,
        provenance_gates=provenance_gates,
        provenance={
            "source_contract": mesh_handoff.contract,
            "source_mesh_metadata": str(source_metadata),
            "source_marker_summary": str(source_marker_summary),
            "source_units": mesh_handoff.units,
            "source_geometry_family": mesh_handoff.geometry_family,
            "source_body_bounds": mesh_handoff.body_bounds.model_dump(mode="json"),
            "source_farfield_bounds": mesh_handoff.farfield_bounds.model_dump(mode="json"),
            "reference_source_path": str(_resolve_path(mesh_handoff.source_path, source_root)),
            "reference_mode_requested": runtime.reference_mode,
            "parallel_mode_requested": runtime.parallel_mode,
            "mpi_launcher": runtime.mpi_launcher,
            "mpi_ranks": _mpi_ranks(runtime),
            "omp_threads_per_rank": _omp_threads_per_rank(runtime),
            "reference_gate_status": reference.gate_status,
            "force_surface_gate_status": force_surface_provenance.gate_status,
        },
        notes=[
            "Package-native SU2 baseline case materialized directly from mesh_handoff.v1.",
            "This baseline route trusts mesh_handoff markers, units, and bounds without recomputing them.",
        ],
    )
    _write_json(artifacts.contract_path, case.model_dump(mode="json"))
    return case


def _normalize_header(value: str) -> str:
    return value.strip().strip('"').strip()


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def _read_history_rows(history_path: Path) -> list[dict[str, str]]:
    if history_path.suffix.lower() == ".csv":
        with history_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        if len(rows) < 2:
            raise ValueError(f"history file has insufficient rows: {history_path}")
        header = [_normalize_header(value) for value in rows[0]]
        data_rows: list[dict[str, str]] = []
        for raw_values in rows[1:]:
            if not raw_values or len(raw_values) != len(header):
                continue
            data_rows.append({key: value.strip() for key, value in zip(header, raw_values)})
        if not data_rows:
            raise ValueError(f"history file has no parseable data rows: {history_path}")
        return data_rows

    lines = [
        line.strip()
        for line in history_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    if len(lines) < 2:
        raise ValueError(f"history file has insufficient data: {history_path}")

    header = [_normalize_header(value) for value in lines[0].replace("\t", ",").split(",")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        values = [value.strip() for value in line.replace("\t", ",").split(",")]
        if len(values) != len(header):
            continue
        rows.append({key: value for key, value in zip(header, values)})
    if not rows:
        raise ValueError(f"history file has no parseable data rows: {history_path}")
    return rows


def parse_history(history_path: Path) -> dict[str, Any]:
    rows = _read_history_rows(history_path)
    final_row = rows[-1]

    cm_column = next((name for name in ("CMy", "CMY", "CMz", "CMZ", "CMx", "CMX", "CM") if name in final_row), None)
    final_iteration = next(
        (
            _parse_int(final_row.get(name))
            for name in ("Inner_Iter", "ITER", "Outer_Iter", "Time_Iter")
            if name in final_row
        ),
        None,
    )
    return {
        "history_path": str(history_path),
        "final_iteration": final_iteration,
        "cl": _parse_float(final_row.get("CL")),
        "cd": _parse_float(final_row.get("CD")),
        "cm": _parse_float(final_row.get(cm_column)) if cm_column is not None else None,
        "cm_axis": cm_column,
        "source_columns": {
            "cl": "CL" if "CL" in final_row else "",
            "cd": "CD" if "CD" in final_row else "",
            "cm": cm_column or "",
        },
    }


def _find_history_file(case_dir: Path) -> Path | None:
    for candidate in (
        case_dir / "history.csv",
        case_dir / "history.dat",
        case_dir / "conv_history.csv",
        case_dir / "conv_history.dat",
    ):
        if candidate.exists():
            return candidate
    return None


def _failure_result(
    case: SU2CaseHandoff | None,
    *,
    failure_code: str,
    error: str,
) -> dict[str, Any]:
    payload = {
        "contract": "su2_handoff.v1",
        "run_status": "failed",
        "failure_code": failure_code,
        "error": error,
        "solver_command": "" if case is None else " ".join(case.solver_command),
        "runtime_cfg_path": None if case is None else str(case.runtime_cfg_path),
        "history_path": None if case is None or case.case_output_paths.history is None else str(case.case_output_paths.history),
        "case_output_paths": {} if case is None else case.case_output_paths.model_dump(mode="json"),
        "final_coefficients": {"cl": None, "cd": None, "cm": None, "cm_axis": None},
        "reference_geometry": None if case is None else case.reference_geometry.model_dump(mode="json"),
        "force_surface_provenance": None if case is None or case.force_surface_provenance is None else case.force_surface_provenance.model_dump(mode="json"),
        "provenance_gates": None if case is None else case.provenance_gates.model_dump(mode="json"),
        "convergence_gate": None if case is None or case.convergence_gate is None else case.convergence_gate.model_dump(mode="json"),
        "provenance": {} if case is None else case.provenance,
        "notes": [] if case is None else [*case.notes, error],
    }
    if case is not None:
        case.run_status = "failed"
        case.notes.append(error)
        _write_json(case.case_output_paths.contract_path, case.model_dump(mode="json"))
    return payload


def run_baseline_case(
    mesh_handoff: MeshHandoff | dict[str, Any],
    runtime: SU2RuntimeConfig,
    case_root: Path,
    *,
    source_root: Path | None = None,
) -> dict[str, Any]:
    try:
        case = materialize_baseline_case(mesh_handoff, runtime, case_root, source_root=source_root)
    except Exception as exc:
        return _failure_result(None, failure_code="materialization_failed", error=str(exc))

    failure_code, missing_command = _resolve_launch_requirements(runtime)
    if failure_code is not None and missing_command is not None:
        return _failure_result(
            case,
            failure_code=failure_code,
            error=f"{missing_command} not found on PATH",
        )
    solver_path = shutil.which(runtime.solver_command) or runtime.solver_command
    launcher_path = None if runtime.parallel_mode != "mpi" else (shutil.which(runtime.mpi_launcher) or runtime.mpi_launcher)

    try:
        with case.case_output_paths.solver_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                case.solver_command,
                cwd=case.case_output_paths.case_dir,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                env=_solver_env(runtime),
            )
    except Exception as exc:
        return _failure_result(case, failure_code="solver_execution_failed", error=str(exc))

    history_path = _find_history_file(case.case_output_paths.case_dir)
    if completed.returncode != 0:
        return _failure_result(
            case,
            failure_code="solver_execution_failed",
            error=f"{runtime.solver_command} exited with code {completed.returncode}",
        )
    if history_path is None:
        return _failure_result(
            case,
            failure_code="history_missing",
            error="SU2 completed without writing a history file",
        )

    try:
        parsed_history = parse_history(history_path)
    except Exception as exc:
        return _failure_result(case, failure_code="history_parse_failed", error=str(exc))

    case.case_output_paths.history = history_path
    case.history = SU2HistorySummary.model_validate(parsed_history)
    case.convergence_gate = evaluate_baseline_convergence_gate(
        mesh_handoff,
        history_path=history_path,
        provenance_gates=case.provenance_gates,
        source_root=source_root,
    )
    case.run_status = "completed"
    case.provenance["solver_binary"] = solver_path
    if launcher_path is not None:
        case.provenance["launcher_binary"] = launcher_path
    case.provenance["convergence_gate_status"] = case.convergence_gate.overall_convergence_gate.status
    case.provenance["comparability_level"] = case.convergence_gate.overall_convergence_gate.comparability_level
    _write_json(case.case_output_paths.contract_path, case.model_dump(mode="json"))

    return {
        "contract": case.contract,
        "run_status": case.run_status,
        "solver_command": " ".join(case.solver_command),
        "runtime_cfg_path": str(case.runtime_cfg_path),
        "history_path": str(history_path),
        "final_iteration": case.history.final_iteration,
        "case_output_paths": case.case_output_paths.model_dump(mode="json"),
        "final_coefficients": {
            "cl": case.history.cl,
            "cd": case.history.cd,
            "cm": case.history.cm,
            "cm_axis": case.history.cm_axis,
        },
        "reference_geometry": case.reference_geometry.model_dump(mode="json"),
        "force_surface_provenance": None if case.force_surface_provenance is None else case.force_surface_provenance.model_dump(mode="json"),
        "provenance_gates": case.provenance_gates.model_dump(mode="json"),
        "convergence_gate": None if case.convergence_gate is None else case.convergence_gate.model_dump(mode="json"),
        "provenance": case.provenance,
        "notes": case.notes,
    }
