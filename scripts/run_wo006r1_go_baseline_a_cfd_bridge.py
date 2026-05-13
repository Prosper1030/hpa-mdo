#!/usr/bin/env python3
"""Run the WO-006R1 GO/Baseline A mesh-native CFD bridge probe.

This is a bounded bridge/probe, not a production CFD validation runner. It adapts
the current GO/Baseline A section-table geometry into the existing mesh-native
indexed-surface route, writes a coarse marker-owned SU2 case, and optionally runs
a very short solver-readability smoke.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
if str(HPA_MESHING_SRC) not in sys.path:
    sys.path.insert(0, str(HPA_MESHING_SRC))

from hpa_meshing.mesh_native.blackcat import (  # noqa: E402
    _resample_airfoil_loop,
    _subdivide_spanwise_stations,
)
from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    _cfd_evidence_gate,
    _coefficient_sanity_gate,
    write_faceted_volume_su2_case,
)
from hpa_meshing.mesh_native.su2_structured import (  # noqa: E402
    _parse_smoke_history,
    audit_su2_case_markers,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    Reference,
    Station,
    SurfaceMesh,
    WingSpec,
    build_farfield_box_surface,
    build_wing_surface,
)


DESIGN_GROSS_MASS_KG = 98.5
PIPELINE_FULL_SPAN_M = 34.332286
PIPELINE_HALF_SPAN_M = 17.166143
CANDIDATE_ID = "current_avl_compromise_conservative_closed"

DEFAULT_GEOMETRY_DIR = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "production_inspection"
    / CANDIDATE_ID
)
DEFAULT_AUTHORITY_TABLE = (
    REPO_ROOT / "output" / "baseline_A_team_release" / "data_authority_table.csv"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "wo006r1_go_cfd_bridge"
)


@dataclass(frozen=True)
class MeshNativeSpecBundle:
    wing_spec: WingSpec
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CurrentGoGeometry:
    case_name: str
    geometry_dir: Path
    geometry_manifest_path: Path
    section_table_path: Path
    source_avl_path: Path
    design_gross_mass_kg: float
    full_span_m: float
    half_span_m: float
    reference: Reference
    moment_origin_m: tuple[float, float, float]
    base_half_station_count: int
    spec: MeshNativeSpecBundle
    manifest: dict[str, Any]


@dataclass(frozen=True)
class BridgeRunOptions:
    output_dir: Path = DEFAULT_OUTPUT_DIR
    points_per_side: int = 8
    spanwise_subdivisions: int = 3
    mesh_size: float = 8.0
    wing_mesh_size: float = 2.0
    farfield_mesh_size: float = 12.0
    gmsh_threads: int = 4
    mesh_algorithm3d: int = 10
    mesh_timeout_seconds: float = 60.0
    solver_timeout_seconds: float = 45.0
    velocity_mps: float = 6.5
    alpha_deg: float = 0.0
    solver_iterations: int = 3
    solver_command: str = "/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD"
    solver_threads: int = 1
    run_solver: bool = True


def load_current_go_geometry(
    geometry_dir: Path | str = DEFAULT_GEOMETRY_DIR,
    *,
    points_per_side: int = 8,
    spanwise_subdivisions: int = 3,
) -> CurrentGoGeometry:
    geometry_path = Path(geometry_dir)
    manifest_path = geometry_path / "geometry_manifest.json"
    section_table_path = geometry_path / "section_table.csv"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing geometry manifest: {manifest_path}")
    if not section_table_path.is_file():
        raise FileNotFoundError(f"Missing section table: {section_table_path}")

    manifest = _read_json(manifest_path)
    rows = _read_csv_dicts(section_table_path)
    if not rows:
        raise ValueError(f"Section table is empty: {section_table_path}")

    sref = _required_float(manifest, "Sref")
    cref = _required_float(manifest, "Cref")
    bref = _required_float(manifest, "Bref")
    half_span = _required_float(rows[-1], "y_m")
    full_span = 2.0 * half_span
    _require_close("manifest Bref", bref, PIPELINE_FULL_SPAN_M, tolerance=1.0e-6)
    _require_close("section-table full span", full_span, PIPELINE_FULL_SPAN_M, tolerance=1.0e-6)
    _require_close("section-table half span", half_span, PIPELINE_HALF_SPAN_M, tolerance=1.0e-6)

    source_avl_path = Path(str(manifest.get("source_avl_file_path") or ""))
    if not source_avl_path.is_file():
        source_avl_path = geometry_path / f"{CANDIDATE_ID}.avl"
    moment_origin = _parse_avl_moment_origin(source_avl_path)

    half_stations = _half_stations_from_rows(rows, points_per_side=points_per_side)
    full_stations = _mirror_half_wing(half_stations)
    refined_stations = _subdivide_spanwise_stations(full_stations, spanwise_subdivisions)
    reference = Reference(sref_full=sref, cref=cref, bref_full=bref)
    wing_spec = WingSpec(
        stations=refined_stations,
        side="full",
        te_rule="sharp",
        tip_rule="planar_cap",
        root_rule="full",
        reference=reference,
        twist_axis_x=0.25,
    )
    spec = MeshNativeSpecBundle(
        wing_spec=wing_spec,
        metadata={
            "base_half_station_count": len(half_stations),
            "base_full_station_count": len(full_stations),
            "full_station_count": len(refined_stations),
            "points_per_side": int(points_per_side),
            "points_per_station": len(refined_stations[0].airfoil_xz),
            "spanwise_subdivisions": int(spanwise_subdivisions),
            "surface_source": "production_inspection_section_table_plus_airfoil_dat",
            "x_le_source": "section_table_current_avl_x_le_zero",
            "twist_axis_x": 0.25,
        },
    )
    return CurrentGoGeometry(
        case_name=str(manifest.get("case_name") or CANDIDATE_ID),
        geometry_dir=geometry_path,
        geometry_manifest_path=manifest_path,
        section_table_path=section_table_path,
        source_avl_path=source_avl_path,
        design_gross_mass_kg=DESIGN_GROSS_MASS_KG,
        full_span_m=full_span,
        half_span_m=half_span,
        reference=reference,
        moment_origin_m=moment_origin,
        base_half_station_count=len(half_stations),
        spec=spec,
        manifest=manifest,
    )


def build_current_go_wing_surface(geometry: CurrentGoGeometry) -> SurfaceMesh:
    wing = build_wing_surface(geometry.spec.wing_spec)
    _require_close(
        "mesh-native wing span",
        float(wing.metadata["span_m"]),
        geometry.full_span_m,
        tolerance=1.0e-6,
    )
    _require_close(
        "mesh-native planform area",
        float(wing.metadata["planform_area_m2"]),
        geometry.reference.sref_full,
        tolerance=1.0e-6,
    )
    return wing


def choose_route(geometry: CurrentGoGeometry) -> dict[str, Any]:
    return {
        "schema_version": "wo006r1_route_decision.v1",
        "verdict": "mesh_native_selected_for_current_go_bridge",
        "selected_route": "mesh_native_current_go_section_table",
        "rejected_primary_route": "current_vsp3_esp_rebuilt_step_brep_gmsh",
        "legacy_route_status": "blocked_reference_only",
        "mesh_native_reason": "current_go_section_table_and_airfoil_dat_available",
        "route_A_old_wo006": {
            "route": "current Baseline A VSP3 -> esp_rebuilt -> STEP/BREP-like geometry -> Gmsh thin-sheet -> SU2",
            "status": "blocked_reference_only",
            "blockers": [
                "default probe timed out in Gmsh 3D volume insertion",
                "coarse sensitivity failed boundary parametrization topology",
                "no current pathfinder mesh_handoff.v1",
                "no usable current pathfinder SU2 CL/CD",
            ],
            "decision": "do_not_repair_blindly",
        },
        "route_B_mesh_native": {
            "route": "section_table + airfoil DAT -> indexed wing surface -> marker-owned faces -> HXT coarse mesh -> SU2",
            "status": "selected",
            "known_risk": "raw 9-station surface can be too warped near airfoil-transition; spanwise subdivisions are required",
            "memory_safe_policy": "coarse no-BL smoke first, no design-space CFD, bounded child process",
        },
        "authority_basis": {
            "design_gross_mass_kg": geometry.design_gross_mass_kg,
            "pipeline_full_span_m": geometry.full_span_m,
            "pipeline_half_span_m": geometry.half_span_m,
            "sref_m2": geometry.reference.sref_full,
            "cref_m": geometry.reference.cref,
            "bref_m": geometry.reference.bref_full,
            "moment_origin_m": list(geometry.moment_origin_m),
        },
    }


def run_bridge(options: BridgeRunOptions) -> dict[str, Path | None]:
    output_dir = options.output_dir
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    geometry = load_current_go_geometry(
        points_per_side=options.points_per_side,
        spanwise_subdivisions=options.spanwise_subdivisions,
    )
    route_decision = choose_route(geometry)
    _write_json(output_dir / "route_decision.json", route_decision)
    _write_route_evidence_comparison(output_dir / "route_evidence_comparison.csv")
    _write_geometry_authority_reconciliation(
        output_dir / "geometry_authority_reconciliation.csv",
        geometry,
    )

    case_dir = output_dir / "artifacts" / "mesh_native_su2_case"
    mesh_result = _run_case_materialization_with_timeout(
        options=options,
        case_dir=case_dir,
    )

    mesh_handoff_path: Path | None = None
    su2_manifest_path: Path | None = None
    solver_smoke_path: Path | None = None
    blocker_register: list[dict[str, str]] = []

    if mesh_result["status"] == "materialized":
        case_report = mesh_result["case_report"]
        runtime_cfg_path = Path(case_report["runtime_cfg_path"])
        _patch_runtime_reference_origin(runtime_cfg_path, geometry.moment_origin_m)
        marker_audit = audit_su2_case_markers(case_report["mesh_path"], runtime_cfg_path)
        case_report = {
            **case_report,
            "marker_audit": marker_audit,
            "current_authority_reference": _authority_reference_payload(geometry),
        }
        _write_json(Path(case_report["report_path"]), case_report)

        mesh_handoff_path = output_dir / "mesh_handoff.v1.json"
        _write_json(mesh_handoff_path, _mesh_handoff_payload(geometry, case_report, options))

        su2_manifest_path = output_dir / "su2_case_manifest.json"
        _write_json(su2_manifest_path, _su2_case_manifest_payload(geometry, case_report, options))

        if options.run_solver:
            solver_payload = _run_solver_smoke_with_timeout(
                case_report=case_report,
                geometry=geometry,
                options=options,
            )
        else:
            solver_payload = {
                "schema_version": "wo006r1_su2_solver_smoke.v1",
                "run_status": "not_run",
                "reason": "solver_disabled_by_cli",
                "aero_coefficients_interpretable": False,
            }
        solver_smoke_path = output_dir / "su2_solver_smoke.v1.json"
        _write_json(solver_smoke_path, solver_payload)
        blocker_register.extend(_blockers_from_successful_smoke(solver_payload))
    else:
        blocker_register.append(
            {
                "stage": "mesh_handoff",
                "status": "blocked",
                "failure": str(mesh_result.get("failure_code") or mesh_result["status"]),
                "evidence": str(mesh_result.get("error") or "mesh case did not materialize"),
                "owner": "wo006r1_mesh_native_adapter",
                "do_not_change": "do not change external Baseline A shape or mass/span authority",
            }
        )

    _write_blocker_register(output_dir / "blocker_register.csv", blocker_register)
    _write_next_repair_goal(output_dir / "next_repair_goal.md")
    _write_report(
        output_dir / "wo006r1_go_cfd_bridge_report.md",
        geometry=geometry,
        route_decision=route_decision,
        mesh_result=mesh_result,
        solver_smoke_path=solver_smoke_path,
        blockers=blocker_register,
    )
    return {
        "report": output_dir / "wo006r1_go_cfd_bridge_report.md",
        "route_decision": output_dir / "route_decision.json",
        "mesh_handoff": mesh_handoff_path,
        "su2_case_manifest": su2_manifest_path,
        "su2_solver_smoke": solver_smoke_path,
        "blocker_register": output_dir / "blocker_register.csv",
    }


def _run_case_materialization_with_timeout(
    *,
    options: BridgeRunOptions,
    case_dir: Path,
) -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue: mp.Queue = context.Queue()
    process = context.Process(
        target=_case_materialization_worker,
        kwargs={
            "queue": queue,
            "case_dir": str(case_dir),
            "points_per_side": options.points_per_side,
            "spanwise_subdivisions": options.spanwise_subdivisions,
            "mesh_size": options.mesh_size,
            "wing_mesh_size": options.wing_mesh_size,
            "farfield_mesh_size": options.farfield_mesh_size,
            "gmsh_threads": options.gmsh_threads,
            "mesh_algorithm3d": options.mesh_algorithm3d,
            "velocity_mps": options.velocity_mps,
            "alpha_deg": options.alpha_deg,
            "solver_iterations": options.solver_iterations,
        },
    )
    process.start()
    process.join(options.mesh_timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5.0)
        return {
            "status": "mesh_timeout",
            "failure_code": "mesh_materialization_timeout",
            "error": f"mesh materialization timed out after {options.mesh_timeout_seconds:.1f}s",
        }
    if queue.empty():
        return {
            "status": "mesh_failed",
            "failure_code": "mesh_worker_no_payload",
            "error": f"mesh worker exited with code {process.exitcode}",
        }
    payload = queue.get()
    if payload.get("status") != "materialized":
        return payload
    return payload


def _case_materialization_worker(
    *,
    queue: Any,
    case_dir: str,
    points_per_side: int,
    spanwise_subdivisions: int,
    mesh_size: float,
    wing_mesh_size: float,
    farfield_mesh_size: float,
    gmsh_threads: int,
    mesh_algorithm3d: int,
    velocity_mps: float,
    alpha_deg: float,
    solver_iterations: int,
) -> None:
    try:
        geometry = load_current_go_geometry(
            points_per_side=points_per_side,
            spanwise_subdivisions=spanwise_subdivisions,
        )
        wing = build_current_go_wing_surface(geometry)
        farfield = build_farfield_box_surface(
            wing,
            upstream_factor=1.5,
            downstream_factor=2.0,
            lateral_factor=1.2,
            vertical_factor=1.2,
        )
        report = write_faceted_volume_su2_case(
            wing,
            farfield,
            case_dir,
            ref_area=geometry.reference.sref_full,
            ref_length=geometry.reference.cref,
            mesh_size=mesh_size,
            wing_mesh_size=wing_mesh_size,
            farfield_mesh_size=farfield_mesh_size,
            velocity_mps=velocity_mps,
            alpha_deg=alpha_deg,
            max_iterations=solver_iterations,
            solver="INC_EULER",
            turbulence_model="NONE",
            wall_profile="euler_slip",
            gmsh_threads=gmsh_threads,
            mesh_algorithm3d=mesh_algorithm3d,
        )
        queue.put({"status": "materialized", "case_report": report})
    except Exception as exc:  # pragma: no cover - exercised by real route failures.
        queue.put(
            {
                "status": "mesh_failed",
                "failure_code": exc.__class__.__name__,
                "error": str(exc),
            }
        )


def _run_solver_smoke_with_timeout(
    *,
    case_report: Mapping[str, Any],
    geometry: CurrentGoGeometry,
    options: BridgeRunOptions,
) -> dict[str, Any]:
    case_dir = Path(case_report["runtime_cfg_path"]).parent
    solver_path = _resolve_solver_command(options.solver_command)
    solver_log = case_dir / "solver.log"
    history_path = case_dir / "history.csv"
    command = [solver_path, "-t", str(max(1, options.solver_threads)), "su2_runtime.cfg"]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(max(1, options.solver_threads))

    try:
        with solver_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                cwd=case_dir,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                env=env,
                timeout=options.solver_timeout_seconds,
            )
        history = _parse_smoke_history(history_path) if history_path.exists() else None
        failure_code = None
        if completed.returncode != 0:
            failure_code = "solver_execution_failed"
        elif history is None:
            failure_code = "history_missing"
        iterative_gate = None
        iterative_gate_status = "not_run"
        if history_path.exists():
            from hpa_meshing.convergence import evaluate_iterative_gate

            iterative_gate = evaluate_iterative_gate(history_path).model_dump(mode="json")
            iterative_gate_status = str(iterative_gate.get("status"))
        cfd_gate = _cfd_evidence_gate(
            max_iterations=options.solver_iterations,
            min_iterations=1000,
            iterative_gate_status=iterative_gate_status,
            history=history,
        )
        coefficient_gate = _coefficient_sanity_gate(history)
        run_status = "completed" if failure_code is None else "failed"
        aero_interpretable = (
            run_status == "completed"
            and iterative_gate_status == "pass"
            and cfd_gate["status"] == "pass"
            and coefficient_gate["status"] == "pass"
        )
        return {
            "schema_version": "wo006r1_su2_solver_smoke.v1",
            "execution_mode": "bounded_solver_readability_smoke",
            "run_status": run_status,
            "failure_code": failure_code,
            "returncode": completed.returncode,
            "solver_command": command,
            "solver_timeout_seconds": options.solver_timeout_seconds,
            "solver_log_path": str(solver_log),
            "history_path": str(history_path) if history_path.exists() else None,
            "history": history,
            "iterative_gate": iterative_gate,
            "iterative_gate_status": iterative_gate_status,
            "cfd_evidence_gate": cfd_gate,
            "coefficient_sanity_gate": coefficient_gate,
            "aero_coefficients_interpretable": aero_interpretable,
            "authority_basis": _authority_reference_payload(geometry),
            "engineering_read": (
                "SU2 can read and step the current GO mesh-native case, but this is not "
                "converged or coefficient-credible CFD."
            ),
        }
    except subprocess.TimeoutExpired:
        return {
            "schema_version": "wo006r1_su2_solver_smoke.v1",
            "execution_mode": "bounded_solver_readability_smoke",
            "run_status": "timeout",
            "failure_code": "solver_timeout",
            "solver_command": command,
            "solver_timeout_seconds": options.solver_timeout_seconds,
            "solver_log_path": str(solver_log),
            "history_path": str(history_path) if history_path.exists() else None,
            "history": None,
            "aero_coefficients_interpretable": False,
        }


def _half_stations_from_rows(
    rows: Sequence[Mapping[str, str]],
    *,
    points_per_side: int,
) -> list[Station]:
    airfoil_cache: dict[str, list[tuple[float, float]]] = {}
    stations: list[Station] = []
    for row in rows:
        dat_path = Path(row["airfoil_dat_path"])
        loop = airfoil_cache.get(str(dat_path))
        if loop is None:
            loop = _resample_airfoil_loop(
                _read_airfoil_dat(dat_path),
                points_per_side=points_per_side,
            )
            airfoil_cache[str(dat_path)] = loop
        stations.append(
            Station(
                y=_required_float(row, "y_m"),
                x_le=_required_float(row, "x_le_m", default=0.0),
                z_le=_required_float(row, "z_m"),
                chord=_required_float(row, "chord_m"),
                twist_deg=_required_float(row, "twist_deg"),
                airfoil_xz=loop,
            )
        )
    if abs(stations[0].y) > 1.0e-9:
        raise ValueError("Expected root station y_m to be zero")
    return stations


def _mirror_half_wing(half_stations: Sequence[Station]) -> list[Station]:
    mirrored = [
        Station(
            y=-station.y,
            x_le=station.x_le,
            z_le=station.z_le,
            chord=station.chord,
            twist_deg=station.twist_deg,
            airfoil_xz=station.airfoil_xz,
        )
        for station in reversed(half_stations[1:])
    ]
    return [*mirrored, *half_stations]


def _read_airfoil_dat(path: Path) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            points.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if len(points) < 6:
        raise ValueError(f"Airfoil DAT has too few points: {path}")
    return points


def _parse_avl_moment_origin(path: Path) -> tuple[float, float, float]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing AVL source for moment origin: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith("#xref"):
            parts = lines[idx + 1].split()
            if len(parts) < 3:
                raise ValueError(f"Malformed AVL Xref row in {path}")
            return (float(parts[0]), float(parts[1]), float(parts[2]))
    raise ValueError(f"Could not find #Xref row in {path}")


def _patch_runtime_reference_origin(
    runtime_cfg_path: Path,
    moment_origin_m: tuple[float, float, float],
) -> None:
    replacements = {
        "REF_ORIGIN_MOMENT_X=": f"REF_ORIGIN_MOMENT_X= {moment_origin_m[0]:.6f}",
        "REF_ORIGIN_MOMENT_Y=": f"REF_ORIGIN_MOMENT_Y= {moment_origin_m[1]:.6f}",
        "REF_ORIGIN_MOMENT_Z=": f"REF_ORIGIN_MOMENT_Z= {moment_origin_m[2]:.6f}",
    }
    lines = []
    for line in runtime_cfg_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        replacement = next(
            (value for prefix, value in replacements.items() if stripped.startswith(prefix)),
            None,
        )
        lines.append(replacement if replacement is not None else line)
    runtime_cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mesh_handoff_payload(
    geometry: CurrentGoGeometry,
    case_report: Mapping[str, Any],
    options: BridgeRunOptions,
) -> dict[str, Any]:
    mesh_report = case_report["mesh_report"]
    marker_audit = case_report["marker_audit"]
    return {
        "contract": "mesh_handoff.v1",
        "schema_version": "wo006r1_mesh_handoff.v1",
        "status": "written",
        "route": "mesh_native_current_go_faceted_hxt_coarse",
        "geometry_source": _geometry_source_payload(geometry),
        "mesh_path": case_report["mesh_path"],
        "gmsh_mesh_path": case_report["gmsh_mesh_path"],
        "node_count": mesh_report["node_count"],
        "volume_element_count": mesh_report["volume_element_count"],
        "surface_triangle_count": mesh_report["surface_triangle_count"],
        "physical_groups": mesh_report["physical_groups"],
        "marker_audit": marker_audit,
        "mesh_quality_gate": mesh_report["mesh_quality_gate"],
        "production_scale_gate": mesh_report["production_scale_gate"],
        "mesh_sizing": mesh_report["mesh_sizing"],
        "compute": mesh_report["compute"],
        "memory_safe_policy": {
            "mesh_timeout_seconds": options.mesh_timeout_seconds,
            "coarse_no_bl_first": True,
            "design_space_cfd": False,
        },
        "limitations": [
            "coarse no-BL mesh; not a wall-resolved drag mesh",
            "intended for current GO/Baseline A SU2 readability and marker ownership only",
        ],
    }


def _su2_case_manifest_payload(
    geometry: CurrentGoGeometry,
    case_report: Mapping[str, Any],
    options: BridgeRunOptions,
) -> dict[str, Any]:
    return {
        "schema_version": "wo006r1_su2_case_manifest.v1",
        "status": "su2_case_materialized",
        "route": "mesh_native_current_go_faceted_hxt_coarse",
        "case_dir": str(Path(case_report["runtime_cfg_path"]).parent),
        "mesh_path": case_report["mesh_path"],
        "runtime_cfg_path": case_report["runtime_cfg_path"],
        "mesh_report_path": case_report["report_path"],
        "marker_audit": case_report["marker_audit"],
        "runtime": {
            **case_report["runtime"],
            "ref_area": geometry.reference.sref_full,
            "ref_length": geometry.reference.cref,
            "ref_origin_moment": list(geometry.moment_origin_m),
            "solver_timeout_seconds": options.solver_timeout_seconds,
        },
        "authority_basis": _authority_reference_payload(geometry),
        "limitations": [
            "INC_EULER coarse smoke; no BL/prism layer and no viscous drag credibility",
            "case materialization is not convergence or aero validation",
        ],
    }


def _authority_reference_payload(geometry: CurrentGoGeometry) -> dict[str, Any]:
    return {
        "design_gross_mass_kg": geometry.design_gross_mass_kg,
        "pipeline_full_span_m": geometry.full_span_m,
        "pipeline_half_span_m": geometry.half_span_m,
        "sref_m2": geometry.reference.sref_full,
        "cref_m": geometry.reference.cref,
        "bref_m": geometry.reference.bref_full,
        "moment_origin_m": list(geometry.moment_origin_m),
        "authority_table_path": str(DEFAULT_AUTHORITY_TABLE),
    }


def _geometry_source_payload(geometry: CurrentGoGeometry) -> dict[str, Any]:
    return {
        "case_name": geometry.case_name,
        "geometry_manifest_path": str(geometry.geometry_manifest_path),
        "section_table_path": str(geometry.section_table_path),
        "source_avl_path": str(geometry.source_avl_path),
        "source_geometry": geometry.manifest.get("source_geometry"),
        "export_mode": geometry.manifest.get("export_mode"),
        "known_limitations": geometry.manifest.get("known_limitations", []),
        "mesh_native_adapter": geometry.spec.metadata,
    }


def _write_route_evidence_comparison(path: Path) -> None:
    rows = [
        {
            "route_id": "A",
            "route": "current Baseline A VSP3 -> esp_rebuilt/STEP-BREP-like geometry -> Gmsh thin-sheet -> SU2",
            "classification": "legacy_blocked_reference",
            "evidence": "WO-006 first bounded attempt: provider materialized, default 3D volume insertion timeout, coarse topology failure",
            "decision": "do_not_repair_blindly",
        },
        {
            "route_id": "B",
            "route": "current section_table + airfoil DAT -> mesh-native indexed surface -> marker-owned HXT mesh -> SU2",
            "classification": "selected_primary",
            "evidence": "current GO geometry package has reconciled section table, airfoil DAT files, Sref/Bref/Cref, and AVL Xref",
            "decision": "implement_coarse_no_bl_smoke_first",
        },
        {
            "route_id": "old_black_cat_mesh_native",
            "route": "Black Cat VSP-native mesh-native reports",
            "classification": "route_evidence_only",
            "evidence": "proves mesh-native HXT/SU2 mechanics; not current Baseline A aerodynamic evidence",
            "decision": "reuse_method_not_coefficients",
        },
    ]
    _write_csv(path, rows)


def _write_geometry_authority_reconciliation(
    path: Path,
    geometry: CurrentGoGeometry,
) -> None:
    rows = [
        _authority_row(
            "design_gross_mass",
            geometry.design_gross_mass_kg,
            "kg",
            "user_authority",
            "latest explicit user instruction + data_authority_table.csv",
            "used as WO-006R1 mass basis only",
        ),
        _authority_row(
            "pipeline_full_span",
            geometry.full_span_m,
            "m",
            "current_pipeline_truth",
            str(geometry.geometry_manifest_path),
            "used as Bref and full-span geometry check",
        ),
        _authority_row(
            "pipeline_half_span",
            geometry.half_span_m,
            "m",
            "current_pipeline_truth",
            str(geometry.section_table_path),
            "used as half-span station extent",
        ),
        _authority_row(
            "Sref",
            geometry.reference.sref_full,
            "m^2",
            "current_pipeline_truth",
            str(geometry.geometry_manifest_path),
            "used for SU2 REF_AREA",
        ),
        _authority_row(
            "Cref",
            geometry.reference.cref,
            "m",
            "current_pipeline_truth",
            str(geometry.geometry_manifest_path),
            "used for SU2 REF_LENGTH",
        ),
        _authority_row(
            "moment_origin_x",
            geometry.moment_origin_m[0],
            "m",
            "current_pipeline_truth",
            str(geometry.source_avl_path),
            "used for SU2 REF_ORIGIN_MOMENT_X",
        ),
        _authority_row(
            "local_splice_half_span",
            16.5,
            "m",
            "screening_estimate",
            "local/splice screening outputs",
            "classified only; not used in WO-006R1",
        ),
        _authority_row(
            "p1_screening_mass",
            106.828608,
            "kg",
            "screening_estimate",
            "P1 generated aggregate",
            "classified only; not used in WO-006R1",
        ),
    ]
    _write_csv(path, rows)


def _authority_row(
    topic: str,
    value: float,
    unit: str,
    authority_class: str,
    source: str,
    wo006r1_use: str,
) -> dict[str, str]:
    return {
        "topic": topic,
        "value": f"{value:.9g}",
        "unit": unit,
        "authority_class": authority_class,
        "source": source,
        "wo006r1_use": wo006r1_use,
    }


def _blockers_from_successful_smoke(solver_payload: Mapping[str, Any]) -> list[dict[str, str]]:
    rows = [
        {
            "stage": "aero_calibration",
            "status": "not_usable",
            "failure": "coarse_no_bl_smoke_only",
            "evidence": "mesh/SU2 readability does not provide wall-resolved drag or convergence",
            "owner": "data-authority-restored bounded CFD calibration worker",
            "do_not_change": "do not use old Black Cat CL/CD as current Baseline A result",
        }
    ]
    coefficient_gate = solver_payload.get("coefficient_sanity_gate")
    if isinstance(coefficient_gate, Mapping) and coefficient_gate.get("status") != "pass":
        rows.append(
            {
                "stage": "solver_smoke",
                "status": "readability_only",
                "failure": "coefficient_sanity_not_passed",
                "evidence": json.dumps(coefficient_gate, sort_keys=True),
                "owner": "data-authority-restored bounded CFD calibration worker",
                "do_not_change": "do not claim SU2 drag/power delta from this smoke",
            }
        )
    return rows


def _write_blocker_register(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    _write_csv(
        path,
        rows
        or [
            {
                "stage": "none",
                "status": "none",
                "failure": "none",
                "evidence": "no blocker recorded",
                "owner": "none",
                "do_not_change": "none",
            }
        ],
    )


def _write_next_repair_goal(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# Data-Authority-Restored WO-006R1 Repair Goal",
                "",
                "Paste-ready goal for the next worker:",
                "",
                "```text",
                "/goal In /Volumes/Samsung SSD/hpa-mdo, continue WO-006R1 from output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r1_go_cfd_bridge/: upgrade the current GO/Baseline A mesh-native SU2 smoke from coarse no-BL readability to a bounded wall/near-wall calibration probe without changing external shape, mass, CG, or span authority; preserve 98.5 kg and 34.332286 m / 17.166143 m as authority; do not use old Black Cat coefficients as current evidence; stop at a precise blocker if BL quality, y+, solver stability, or coefficient sanity fails.",
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_report(
    path: Path,
    *,
    geometry: CurrentGoGeometry,
    route_decision: Mapping[str, Any],
    mesh_result: Mapping[str, Any],
    solver_smoke_path: Path | None,
    blockers: Sequence[Mapping[str, str]],
) -> None:
    solver_payload = _read_json(solver_smoke_path) if solver_smoke_path else {}
    mesh_status = mesh_result.get("status")
    run_status = solver_payload.get("run_status", "not_run")
    verdict = (
        "wo006r1_go_cfd_bridge_smoke_ready"
        if mesh_status == "materialized" and run_status == "completed"
        else "wo006r1_su2_case_materialized"
        if mesh_status == "materialized"
        else "wo006r1_route_blocker_isolated"
    )
    lines = [
        "# WO-006R1 GO/Baseline A CFD Bridge",
        "",
        f"Verdict: `{verdict}`",
        "",
        "## Plain-Language Blocker",
        "",
        "WO-006 was blocked because the current pathfinder VSP3 materializes through "
        "`esp_rebuilt`, but the old Gmsh thin-sheet/STEP-BREP-like route does not get "
        "to a usable SU2 case. The default probe timed out during 3D volume insertion; "
        "the coarse probe hit boundary/topology failure. So there was no current "
        "Baseline A `mesh_handoff.v1` and no usable SU2 CL/CD.",
        "",
        "## Route Decision",
        "",
        f"- Selected route: `{route_decision['selected_route']}`.",
        "- Rejected as primary: old VSP3 -> esp_rebuilt / STEP-BREP-like -> Gmsh route.",
        "- Reason: current GO section-table geometry gives a controlled indexed wing "
        "surface with marker-owned wing/farfield faces; old Black Cat evidence is "
        "method evidence only.",
        "",
        "## Authority Basis",
        "",
        f"- Design gross mass: `{geometry.design_gross_mass_kg:.1f} kg`.",
        f"- Span: `{geometry.full_span_m:.6f} m` full / `{geometry.half_span_m:.6f} m` half.",
        f"- Sref / Cref / Bref: `{geometry.reference.sref_full:.9f}` / "
        f"`{geometry.reference.cref:.9f}` / `{geometry.reference.bref_full:.9f}`.",
        f"- Moment origin: `{geometry.moment_origin_m}` from current AVL source.",
        "- `106.828608 kg` was classified as suspect P1 screening aggregate, not current design truth; `16.5 m` was classified as local/splice screening only. Neither was used.",
        "",
        "## Result",
        "",
        f"- Mesh materialization status: `{mesh_status}`.",
    ]
    if mesh_status == "materialized":
        case_report = mesh_result["case_report"]
        mesh_report = case_report["mesh_report"]
        lines.extend(
            [
                f"- Mesh volume elements: `{mesh_report['volume_element_count']}`.",
                f"- Marker audit: `{case_report['marker_audit']['status']}`.",
                f"- Mesh quality gate: `{mesh_report['mesh_quality_gate']['status']}` "
                f"with warnings `{mesh_report['mesh_quality_gate'].get('warnings', [])}`.",
                f"- Solver smoke status: `{run_status}`.",
            ]
        )
        if solver_payload.get("history"):
            coeffs = solver_payload["history"]["final_coefficients"]
            lines.append(
                "- Final smoke coefficients (readability only): "
                f"`CL={coeffs.get('cl')}`, `CD={coeffs.get('cd')}`."
            )
    else:
        lines.append(f"- Mesh error: `{mesh_result.get('error')}`.")
    lines.extend(
        [
            "",
            "## Engineering Caveats",
            "",
            "- This is a coarse no-BL SU2 readability route, not validated aerodynamic drag.",
            "- The solver smoke is not convergence and does not reopen Baseline A.",
            "- Negative or unstable smoke coefficients are a warning that the case is not calibration evidence.",
            "- Next CFD work should add near-wall/BL quality and y+ evidence before any drag/power claim.",
            "",
            "## Artifacts",
            "",
            "- `route_decision.json`",
            "- `route_evidence_comparison.csv`",
            "- `geometry_authority_reconciliation.csv`",
            "- `mesh_handoff.v1.json`",
            "- `su2_case_manifest.json`",
            "- `su2_solver_smoke.v1.json`",
            "- `blocker_register.csv`",
            "- `next_repair_goal.md`",
            "",
            "## Current Blockers",
            "",
        ]
    )
    for row in blockers:
        lines.append(f"- `{row['stage']}`: `{row['failure']}` - {row['evidence']}")
    lines.extend(
        [
            "",
            "Baseline A reopen status: `not_evaluated`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _required_float(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: float | None = None,
) -> float:
    value = payload.get(key, default)
    if value is None:
        raise KeyError(key)
    return float(value)


def _require_close(name: str, observed: float, expected: float, *, tolerance: float) -> None:
    if abs(observed - expected) > tolerance:
        raise ValueError(
            f"{name} mismatch: observed {observed:.9g}, expected {expected:.9g}, "
            f"tolerance {tolerance:.3g}"
        )


def _resolve_solver_command(command: str) -> str:
    candidate = Path(command)
    if candidate.exists():
        return str(candidate)
    resolved = shutil.which(command)
    if resolved is None:
        raise FileNotFoundError(f"SU2 solver command not found: {command}")
    return resolved


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--points-per-side", type=int, default=8)
    parser.add_argument("--spanwise-subdivisions", type=int, default=3)
    parser.add_argument("--mesh-size", type=float, default=8.0)
    parser.add_argument("--wing-mesh-size", type=float, default=2.0)
    parser.add_argument("--farfield-mesh-size", type=float, default=12.0)
    parser.add_argument("--gmsh-threads", type=int, default=4)
    parser.add_argument("--mesh-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--solver-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--solver-command", type=str, default="/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD")
    parser.add_argument("--solver-iterations", type=int, default=3)
    parser.add_argument("--skip-solver", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    options = BridgeRunOptions(
        output_dir=args.out,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        mesh_size=args.mesh_size,
        wing_mesh_size=args.wing_mesh_size,
        farfield_mesh_size=args.farfield_mesh_size,
        gmsh_threads=args.gmsh_threads,
        mesh_timeout_seconds=args.mesh_timeout_seconds,
        solver_timeout_seconds=args.solver_timeout_seconds,
        solver_command=args.solver_command,
        solver_iterations=args.solver_iterations,
        run_solver=not args.skip_solver,
    )
    paths = run_bridge(options)
    print(json.dumps({key: None if value is None else str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
