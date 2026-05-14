#!/usr/bin/env python3
"""Run a bounded SU2 route-smoke on the WO-006R27 repaired Baseline A mesh.

This probe is deliberately narrower than grid convergence.  R27 proved that the
mixed Baseline A SU2 handoff has explicit boundary ownership.  R28 checks the
next CFD-facing question: can SU2 read that repaired mesh with the intended
wall-resolved INC_RANS/SA setup, and do the first route-smoke coefficients avoid
an obviously wrong HPA main-wing drag scale?

It must not be promoted to coarse/medium/fine CFD completion.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.su2_structured import parse_su2_marker_summary  # noqa: E402
from run_wo006r1_go_baseline_a_cfd_bridge import (  # noqa: E402
    _authority_reference_payload,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    MU_PA_S,
    RHO_KGPM3,
    VELOCITY_MPS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r28_r27_su2_route_smoke_probe.v1"
DEFAULT_R27_DIR = WO006_ROOT / "wo006r27_apply_boundary_marker_repair_probe"
DEFAULT_R27_SUMMARY_PATH = DEFAULT_R27_DIR / "summary.json"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r28_r27_su2_route_smoke_probe"
DEFAULT_SOLVER_COMMAND = "/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD"
HPA_MAIN_WING_CD_PLAUSIBILITY_MAX = 0.15
FORCE_WINDOW_ROWS = 100
FORCE_RELATIVE_SPREAD_TOL = 0.01
CM_ABSOLUTE_SPREAD_TOL = 0.005
RESIDUAL_SLOPE_TOL = 0.0


def build_r27_route_smoke_config(
    *,
    ref_area_m2: float,
    ref_length_m: float,
    moment_origin_m: Sequence[float],
    iterations: int = 180,
    alpha_deg: float = 5.0,
    velocity_mps: float = VELOCITY_MPS,
    density_kgpm3: float = RHO_KGPM3,
    dynamic_viscosity_pa_s: float = MU_PA_S,
    wall_marker: str = "wing_wall",
    farfield_marker: str = "farfield",
    cfl_number: float = 1.0,
    conv_num_method_flow: str = "FDS",
    muscl_flow: bool = True,
    slope_limiter_flow: str = "NONE",
) -> str:
    """Return an R8-style incompressible RANS/SA config for the R27 mesh."""

    if ref_area_m2 <= 0.0:
        raise ValueError("ref_area_m2 must be positive")
    if ref_length_m <= 0.0:
        raise ValueError("ref_length_m must be positive")
    if len(moment_origin_m) != 3:
        raise ValueError("moment_origin_m must contain exactly three values")
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if velocity_mps <= 0.0:
        raise ValueError("velocity_mps must be positive")
    if cfl_number <= 0.0:
        raise ValueError("cfl_number must be positive")

    alpha_rad = math.radians(alpha_deg)
    vx = velocity_mps * math.cos(alpha_rad)
    vz = velocity_mps * math.sin(alpha_rad)
    origin = tuple(float(value) for value in moment_origin_m)
    flow_method = conv_num_method_flow.strip().upper()
    if not flow_method:
        raise ValueError("conv_num_method_flow must not be empty")
    limiter = slope_limiter_flow.strip().upper()
    muscl_lines = [f"MUSCL_FLOW= {'YES' if muscl_flow else 'NO'}"]
    if muscl_flow:
        muscl_lines.append(f"SLOPE_LIMITER_FLOW= {limiter or 'NONE'}")
    return "\n".join(
        [
            "% WO-006R28 R27 repaired-mesh SU2 route-smoke.",
            "% Baseline A main wing only; not grid convergence evidence.",
            "SOLVER= INC_RANS",
            "KIND_TURB_MODEL= SA",
            "KIND_TRANS_MODEL= NONE",
            "MATH_PROBLEM= DIRECT",
            "RESTART_SOL= NO",
            "SYSTEM_MEASUREMENTS= SI",
            "INC_NONDIM= INITIAL_VALUES",
            "INC_DENSITY_MODEL= CONSTANT",
            f"INC_DENSITY_INIT= {density_kgpm3:.6f}",
            f"INC_VELOCITY_INIT= ( {vx:.6f}, 0.000000, {vz:.6f} )",
            "INC_TEMPERATURE_INIT= 288.150000",
            "VISCOSITY_MODEL= CONSTANT_VISCOSITY",
            f"MU_CONSTANT= {dynamic_viscosity_pa_s:.6e}",
            "FREESTREAM_NU_FACTOR= 3.0",
            f"AOA= {alpha_deg:.6f}",
            "SIDESLIP_ANGLE= 0.000000",
            f"REF_ORIGIN_MOMENT_X= {origin[0]:.6f}",
            f"REF_ORIGIN_MOMENT_Y= {origin[1]:.6f}",
            f"REF_ORIGIN_MOMENT_Z= {origin[2]:.6f}",
            f"REF_LENGTH= {ref_length_m:.6f}",
            f"REF_AREA= {ref_area_m2:.6f}",
            f"MARKER_HEATFLUX= ( {wall_marker}, 0.0 )",
            f"MARKER_FAR= ( {farfield_marker} )",
            f"MARKER_PLOTTING= ( {wall_marker} )",
            f"MARKER_MONITORING= ( {wall_marker} )",
            "NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES",
            "CFL_NUMBER= " + _format_su2_float(cfl_number),
            "CFL_ADAPT= NO",
            "MAX_DELTA_TIME= 1E6",
            f"CONV_NUM_METHOD_FLOW= {flow_method}",
            *muscl_lines,
            "JST_SENSOR_COEFF= ( 0.0, 0.02 )",
            "TIME_DISCRE_FLOW= EULER_IMPLICIT",
            "CONV_NUM_METHOD_TURB= SCALAR_UPWIND",
            "MUSCL_TURB= NO",
            "SLOPE_LIMITER_TURB= VENKATAKRISHNAN",
            "TIME_DISCRE_TURB= EULER_IMPLICIT",
            "LINEAR_SOLVER= FGMRES",
            "LINEAR_SOLVER_PREC= ILU",
            "LINEAR_SOLVER_ERROR= 1E-8",
            "LINEAR_SOLVER_ITER= 10",
            f"ITER= {int(iterations)}",
            "CONV_FIELD= DRAG",
            "CONV_RESIDUAL_MINVAL= -9",
            "CONV_STARTITER= 10000",
            "CONV_CAUCHY_ELEMS= 100",
            "CONV_CAUCHY_EPS= 1E-6",
            "MESH_FILENAME= mesh.su2",
            "MESH_FORMAT= SU2",
            "TABULAR_FORMAT= CSV",
            "CONV_FILENAME= history",
            "RESTART_FILENAME= restart_flow",
            "VOLUME_FILENAME= flow",
            "SURFACE_FILENAME= surface_flow",
            "SCREEN_OUTPUT= (INNER_ITER, WALL_TIME, RMS_PRESSURE, RMS_NU_TILDE, LIFT, DRAG)",
            "HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF)",
            "OUTPUT_FILES= (RESTART_ASCII, SURFACE_CSV)",
            "",
        ]
    )


def audit_config_markers(
    mesh_marker_summary: Mapping[str, Any],
    cfg_text: str,
) -> dict[str, Any]:
    mesh_markers = {
        str(marker)
        for marker, payload in (mesh_marker_summary.get("markers") or {}).items()
        if int((payload or {}).get("element_count") or 0) > 0
    }
    boundary_condition_markers = {
        key: _cfg_marker_list(cfg_text, key)
        for key in ("MARKER_HEATFLUX", "MARKER_FAR", "MARKER_EULER", "MARKER_SYM")
    }
    boundary_condition_markers = {
        key: value for key, value in boundary_condition_markers.items() if value
    }
    assigned_markers = {
        marker
        for markers in boundary_condition_markers.values()
        for marker in markers
    }
    missing_from_mesh = sorted(assigned_markers - mesh_markers)
    unassigned_mesh_markers = sorted(mesh_markers - assigned_markers)
    zero_element_markers = sorted(
        str(marker)
        for marker, payload in (mesh_marker_summary.get("markers") or {}).items()
        if int((payload or {}).get("element_count") or 0) <= 0
    )
    blockers: list[str] = []
    if missing_from_mesh:
        blockers.append("config_marker_missing_from_mesh")
    if unassigned_mesh_markers:
        blockers.append("mesh_marker_without_boundary_condition")
    if zero_element_markers:
        blockers.append("zero_element_mesh_marker")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "mesh_markers": sorted(mesh_markers),
        "boundary_condition_markers": boundary_condition_markers,
        "missing_from_mesh": missing_from_mesh,
        "unassigned_mesh_markers": unassigned_mesh_markers,
        "zero_element_markers": zero_element_markers,
    }


def prepare_route_smoke_case(
    *,
    output_dir: Path,
    r27_summary: Mapping[str, Any],
    authority: Mapping[str, Any],
    iterations: int,
    alpha_deg: float,
    cfl_number: float,
    conv_num_method_flow: str,
    muscl_flow: bool,
    slope_limiter_flow: str,
    clean: bool = True,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    handoff = r27_summary.get("mixed_su2_handoff") or {}
    source_mesh = _resolve_repo_path(str(handoff.get("mesh_path") or ""))
    if not source_mesh.is_file():
        raise FileNotFoundError(f"Missing R27 repaired mesh: {source_mesh}")

    case_mesh = output_dir / "mesh.su2"
    shutil.copy2(source_mesh, case_mesh)
    cfg_text = build_r27_route_smoke_config(
        ref_area_m2=float(authority["sref_m2"]),
        ref_length_m=float(authority["cref_m"]),
        moment_origin_m=authority["moment_origin_m"],
        iterations=iterations,
        alpha_deg=alpha_deg,
        cfl_number=cfl_number,
        conv_num_method_flow=conv_num_method_flow,
        muscl_flow=muscl_flow,
        slope_limiter_flow=slope_limiter_flow,
    )
    cfg_path = output_dir / "su2_runtime.cfg"
    cfg_path.write_text(cfg_text, encoding="utf-8")

    marker_summary = parse_su2_marker_summary(case_mesh)
    marker_audit = audit_config_markers(marker_summary, cfg_text)
    return {
        "status": "prepared",
        "source_mesh_path": str(source_mesh),
        "mesh_path": str(case_mesh),
        "runtime_cfg_path": str(cfg_path),
        "marker_summary": marker_summary,
        "marker_audit": marker_audit,
        "iterations": int(iterations),
        "alpha_deg": float(alpha_deg),
        "numerics": {
            "cfl_number": float(cfl_number),
            "conv_num_method_flow": conv_num_method_flow.strip().upper(),
            "muscl_flow": bool(muscl_flow),
            "slope_limiter_flow": slope_limiter_flow.strip().upper(),
        },
    }


def run_solver(
    *,
    case_dir: Path,
    solver_command: str = DEFAULT_SOLVER_COMMAND,
    threads: int = 4,
    timeout_seconds: float = 1800.0,
) -> dict[str, Any]:
    case_dir = Path(case_dir)
    solver = _resolve_solver(solver_command)
    solver_log_path = case_dir / "solver.log"
    history_path = case_dir / "history.csv"
    base_command = [solver, "-t", str(max(1, int(threads))), "su2_runtime.cfg"]
    time_command = ["/usr/bin/time", "-l", *base_command]
    command = time_command if Path("/usr/bin/time").is_file() else base_command
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(max(1, int(threads)))
    start = time.monotonic()
    try:
        with solver_log_path.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                cwd=case_dir,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                env=env,
                timeout=timeout_seconds,
            )
        elapsed = time.monotonic() - start
        return {
            "run_requested": True,
            "run_status": (
                "completed"
                if completed.returncode == 0 and history_path.is_file()
                else "failed"
            ),
            "returncode": completed.returncode,
            "elapsed_s": elapsed,
            "command": command,
            "solver_log_path": str(solver_log_path),
            "history_path": str(history_path) if history_path.is_file() else None,
            "resource_trace_source": "/usr/bin/time -l" if command == time_command else None,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return {
            "run_requested": True,
            "run_status": "timeout",
            "returncode": None,
            "elapsed_s": elapsed,
            "command": command,
            "solver_log_path": str(solver_log_path),
            "history_path": str(history_path) if history_path.is_file() else None,
            "failure_code": "solver_timeout",
            "resource_trace_source": "/usr/bin/time -l" if command == time_command else None,
        }


def summarize_history(path: Path | str, *, window_rows: int = FORCE_WINDOW_ROWS) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"SU2 history has no rows: {path}")

    normalized_rows = [
        {_normalize_history_key(key): value for key, value in row.items()}
        for row in rows
    ]
    final = normalized_rows[-1]
    window = normalized_rows[-min(max(1, int(window_rows)), len(normalized_rows)) :]
    final_coefficients = {
        "cl": _first_float(final, "CL", "LIFT", "LIFT_COEFFICIENT"),
        "cd": _first_float(final, "CD", "DRAG", "DRAG_COEFFICIENT"),
        "cm": _first_float(final, "CMy", "CMY", "CMz", "CMZ", "CM"),
        "cmx": _first_float(final, "CMx", "CMX"),
        "cmy": _first_float(final, "CMy", "CMY"),
        "cmz": _first_float(final, "CMz", "CMZ"),
    }
    force_stability = _force_stability(window)
    residual_stability = _residual_stability(window)
    return {
        "path": str(path),
        "row_count": len(rows),
        "final_iteration": _first_int(final, "Inner_Iter", "INNER_ITER", "ITER", "Iteration"),
        "final_coefficients": final_coefficients,
        "force_stability": force_stability,
        "residual_stability": residual_stability,
    }


def parse_solver_mesh_quality_from_log(path: Path | str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    orthogonality = _solver_quality_row_min(text, "Orthogonality Angle")
    cv_face_aspect = _solver_quality_row_max(text, "CV Face Area Aspect Ratio")
    cv_sub_volume = _solver_quality_row_max(text, "CV Sub-Volume Ratio")
    blockers: list[str] = []
    if orthogonality is None:
        blockers.append("su2_dual_mesh_quality_orthogonality_missing")
    elif orthogonality < 1.0:
        blockers.append("su2_dual_orthogonality_angle_extreme")
    if cv_face_aspect is None:
        blockers.append("su2_dual_mesh_quality_aspect_ratio_missing")
    elif cv_face_aspect > 1.0e5:
        blockers.append("su2_dual_cv_face_area_aspect_ratio_extreme")
    if cv_sub_volume is None:
        blockers.append("su2_dual_mesh_quality_sub_volume_ratio_missing")
    elif cv_sub_volume > 1.0e6:
        blockers.append("su2_dual_cv_sub_volume_ratio_extreme")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "minimum_orthogonality_angle_deg": orthogonality,
        "maximum_cv_face_area_aspect_ratio": cv_face_aspect,
        "maximum_cv_sub_volume_ratio": cv_sub_volume,
        "engineering_limits": {
            "minimum_orthogonality_angle_deg_warn": 1.0,
            "maximum_cv_face_area_aspect_ratio_warn": 1.0e5,
            "maximum_cv_sub_volume_ratio_warn": 1.0e6,
        },
    }


def build_route_smoke_summary(
    *,
    output_dir: Path,
    r27_summary: Mapping[str, Any],
    authority: Mapping[str, Any],
    marker_audit: Mapping[str, Any],
    solver_report: Mapping[str, Any],
    solver_mesh_quality: Mapping[str, Any] | None = None,
    history: Mapping[str, Any] | None,
) -> dict[str, Any]:
    blockers: list[str] = ["coarse_medium_fine_solver_ladder_not_run"]
    warnings: list[str] = []
    if marker_audit.get("status") != "pass":
        blockers.append("r27_mesh_config_marker_mismatch")
    if not solver_report.get("run_requested"):
        blockers.append("su2_route_smoke_not_run")
    elif solver_report.get("run_status") != "completed":
        blockers.append("su2_route_smoke_failed_or_missing_history")
    if solver_mesh_quality and solver_mesh_quality.get("status") == "fail":
        blockers.extend(str(item) for item in solver_mesh_quality.get("blockers") or [])
    if history is None:
        blockers.append("su2_route_smoke_history_missing")

    coeffs = (history or {}).get("final_coefficients") or {}
    coefficient_gate = coefficient_plausibility_gate(coeffs)
    if coefficient_gate["status"] == "fail":
        blockers.extend(coefficient_gate["blockers"])
    force_stability = (history or {}).get("force_stability") or {}
    residual_stability = (history or {}).get("residual_stability") or {}
    if history is not None and int(force_stability.get("window_rows") or 0) < FORCE_WINDOW_ROWS:
        warnings.append("route_smoke_force_window_shorter_than_100_iterations")
    if history is not None and force_stability.get("status") != "pass":
        warnings.append("route_smoke_force_tail_not_stable")
    if history is not None and residual_stability.get("status") != "pass":
        warnings.append("route_smoke_residual_tail_not_stable")

    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "r27_su2_route_smoke_completed_ladder_pending"
            if solver_report.get("run_status") == "completed"
            and marker_audit.get("status") == "pass"
            and coefficient_gate["status"] == "pass"
            else "r27_su2_route_smoke_blocked_or_plausibility_failed"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable_for_grid_convergence": False,
        "output_dir": str(output_dir),
        "geometry_source": r27_summary.get("geometry_source"),
        "authority": dict(authority),
        "r27_mesh": dict(r27_summary.get("mixed_su2_handoff") or {}),
        "near_wall_yplus": dict(r27_summary.get("near_wall_yplus") or {}),
        "marker_audit": dict(marker_audit),
        "solver_mesh_quality": None
        if solver_mesh_quality is None
        else dict(solver_mesh_quality),
        "solver": dict(solver_report),
        "history": None if history is None else dict(history),
        "coefficient_plausibility_gate": coefficient_gate,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "blocked_claims": [
            "coarse/medium/fine mesh ladder",
            "grid convergence",
            "solver-postprocessed y+ acceptance",
            "engineering-ready Baseline A drag",
        ],
        "engineering_read": _engineering_read(
            solver_report=solver_report,
            coefficient_gate=coefficient_gate,
            force_stability=force_stability,
            residual_stability=residual_stability,
            solver_mesh_quality=solver_mesh_quality or {},
        ),
    }


def run_probe(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    r27_summary_path: Path = DEFAULT_R27_SUMMARY_PATH,
    iterations: int = 180,
    alpha_deg: float = 5.0,
    cfl_number: float = 1.0,
    conv_num_method_flow: str = "FDS",
    muscl_flow: bool = True,
    slope_limiter_flow: str = "NONE",
    run_su2: bool = False,
    solver_command: str = DEFAULT_SOLVER_COMMAND,
    threads: int = 4,
    timeout_seconds: float = 1800.0,
    clean: bool = True,
) -> dict[str, Any]:
    start = time.monotonic()
    r27_summary = _read_json(r27_summary_path)
    geometry = load_campaign_geometry(points_per_side=16, spanwise_subdivisions=2)
    authority = _authority_reference_payload(geometry)
    prepared = prepare_route_smoke_case(
        output_dir=output_dir,
        r27_summary=r27_summary,
        authority=authority,
        iterations=iterations,
        alpha_deg=alpha_deg,
        cfl_number=cfl_number,
        conv_num_method_flow=conv_num_method_flow,
        muscl_flow=muscl_flow,
        slope_limiter_flow=slope_limiter_flow,
        clean=clean,
    )
    solver_report: dict[str, Any] = {
        "run_requested": bool(run_su2),
        "run_status": "not_run",
        "reason": "run_su2_false",
    }
    history: dict[str, Any] | None = None
    solver_mesh_quality: dict[str, Any] | None = None
    if run_su2:
        solver_report = run_solver(
            case_dir=output_dir,
            solver_command=solver_command,
            threads=threads,
            timeout_seconds=timeout_seconds,
        )
        history_path = solver_report.get("history_path")
        solver_log_path = solver_report.get("solver_log_path")
        if solver_log_path:
            try:
                solver_mesh_quality = parse_solver_mesh_quality_from_log(
                    Path(str(solver_log_path))
                )
            except OSError as exc:
                solver_report["mesh_quality_parse_error"] = str(exc)
        if history_path:
            try:
                history = summarize_history(Path(str(history_path)))
            except (OSError, ValueError) as exc:
                solver_report["history_parse_error"] = str(exc)

    summary = build_route_smoke_summary(
        output_dir=output_dir,
        r27_summary=r27_summary,
        authority=authority,
        marker_audit=prepared["marker_audit"],
        solver_report=solver_report,
        solver_mesh_quality=solver_mesh_quality,
        history=history,
    )
    summary["case_preparation"] = prepared
    summary["elapsed_s"] = time.monotonic() - start
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "route_smoke_report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def coefficient_plausibility_gate(coefficients: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    cd = _float_or_none(coefficients.get("cd"))
    cl = _float_or_none(coefficients.get("cl"))
    cm = _float_or_none(coefficients.get("cm"))
    if cl is None:
        blockers.append("route_smoke_cl_missing_or_nonfinite")
    if cm is None:
        blockers.append("route_smoke_cm_missing_or_nonfinite")
    if cd is None:
        blockers.append("route_smoke_cd_missing_or_nonfinite")
    elif cd <= 0.0:
        blockers.append("route_smoke_cd_nonpositive")
    elif cd > HPA_MAIN_WING_CD_PLAUSIBILITY_MAX:
        blockers.append("route_smoke_cd_implausibly_high_for_hpa_main_wing")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "cd_max_for_hpa_main_wing": HPA_MAIN_WING_CD_PLAUSIBILITY_MAX,
        "final_coefficients": {"cl": cl, "cd": cd, "cm": cm},
        "basis": (
            "HPA main-wing route-smoke drag must stay near the 0.0XX engineering "
            "scale before spending time on medium/fine ladder runs."
        ),
    }


def render_report(summary: Mapping[str, Any]) -> str:
    history = summary.get("history") or {}
    coeffs = history.get("final_coefficients") or {}
    solver = summary.get("solver") or {}
    marker_audit = summary.get("marker_audit") or {}
    r27_mesh = summary.get("r27_mesh") or {}
    return "\n".join(
        [
            "# WO-006R28 R27 SU2 Route-Smoke Probe",
            "",
            "This is a bounded SU2 route-smoke, not grid-convergence evidence.",
            "",
            f"GOAL_STATUS: `{summary.get('goal_status')}`",
            f"CFD_STATUS: `{summary.get('cfd_status')}`",
            f"- verdict: `{summary.get('verdict')}`",
            f"- mesh: `{r27_mesh.get('mesh_path')}`",
            f"- nodes / cells: `{r27_mesh.get('node_count')}` / `{r27_mesh.get('volume_element_count')}`",
            f"- marker audit: `{marker_audit.get('status')}`",
            f"- solver status: `{solver.get('run_status')}`",
            f"- iterations: `{history.get('final_iteration')}`",
            f"- CL/CD/Cm: `{coeffs.get('cl')}` / `{coeffs.get('cd')}` / `{coeffs.get('cm')}`",
            f"- coefficient plausibility: `{summary.get('coefficient_plausibility_gate', {}).get('status')}`",
            f"- blockers: `{summary.get('blockers')}`",
            f"- warnings: `{summary.get('warnings')}`",
            "",
            f"Engineering read: {summary.get('engineering_read')}",
            "",
        ]
    )


def _force_stability(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    spreads = {
        "cl": _relative_span(_first_float(row, "CL", "LIFT") for row in rows),
        "cd": _relative_span(_first_float(row, "CD", "DRAG") for row in rows),
        "cm": _absolute_span(_first_float(row, "CMy", "CMY", "CMz", "CMZ", "CM") for row in rows),
    }
    reasons: list[str] = []
    if len(rows) < FORCE_WINDOW_ROWS:
        reasons.append("force_window_too_short")
    if spreads["cl"] is None:
        reasons.append("cl_window_missing")
    elif float(spreads["cl"]) > FORCE_RELATIVE_SPREAD_TOL:
        reasons.append("cl_window_spread_high")
    if spreads["cd"] is None:
        reasons.append("cd_window_missing")
    elif float(spreads["cd"]) > FORCE_RELATIVE_SPREAD_TOL:
        reasons.append("cd_window_spread_high")
    if spreads["cm"] is None:
        reasons.append("cm_window_missing")
    elif float(spreads["cm"]) > CM_ABSOLUTE_SPREAD_TOL:
        reasons.append("cm_window_spread_high")
    return {
        "status": "pass" if not reasons else "fail",
        "window_rows": len(rows),
        "relative_spread_tolerance": FORCE_RELATIVE_SPREAD_TOL,
        "cm_absolute_spread_tolerance": CM_ABSOLUTE_SPREAD_TOL,
        "spreads": spreads,
        "reasons": reasons,
    }


def _residual_stability(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    residual_columns = [
        key
        for key in rows[-1].keys()
        if key.lower().startswith("rms") or key.lower().startswith("res")
    ] if rows else []
    slopes: dict[str, float | None] = {}
    reasons: list[str] = []
    if len(rows) < FORCE_WINDOW_ROWS:
        reasons.append("residual_window_too_short")
    for column in residual_columns:
        values = [_float_or_none(row.get(column)) for row in rows]
        values = [value for value in values if value is not None]
        if len(values) < 2:
            slopes[column] = None
            reasons.append(f"{column}_window_missing")
            continue
        slope = (values[-1] - values[0]) / max(1, len(values) - 1)
        slopes[column] = slope
        if slope > RESIDUAL_SLOPE_TOL:
            reasons.append(f"{column}_worsening")
    if not residual_columns:
        reasons.append("residual_columns_missing")
    return {
        "status": "pass" if not reasons else "fail",
        "window_rows": len(rows),
        "max_abs_slope_per_iter": max(
            [abs(value) for value in slopes.values() if value is not None],
            default=None,
        ),
        "trend": "not_worsening" if not reasons else "unstable",
        "slopes": slopes,
        "reasons": reasons,
    }


def _engineering_read(
    *,
    solver_report: Mapping[str, Any],
    coefficient_gate: Mapping[str, Any],
    force_stability: Mapping[str, Any],
    residual_stability: Mapping[str, Any],
    solver_mesh_quality: Mapping[str, Any],
) -> str:
    if solver_mesh_quality.get("status") == "fail":
        return (
            "SU2 reached the R27 mesh and markers, but the solver-side dual-control-"
            "volume quality is pathological. Fix the BL/core transition sizing and "
            "dual-volume quality before medium/fine runs."
        )
    if solver_report.get("run_status") != "completed":
        return (
            "R27 marker repair is wired into a wall-resolved SU2 config, but the "
            "route-smoke has not produced a completed SU2 history yet. Do not run "
            "medium/fine meshes before this parser/BC gate clears."
        )
    if coefficient_gate.get("status") != "pass":
        return (
            "SU2 produced a route-smoke history, but the coefficient scale is not "
            "physically credible for an HPA main wing. Treat this as a CFD setup "
            "blocker, not as useful drag evidence."
        )
    if force_stability.get("status") != "pass" or residual_stability.get("status") != "pass":
        return (
            "SU2 produced finite, plausible-scale route-smoke coefficients, but "
            "the tail stability is not yet strong enough for ladder runs."
        )
    return (
        "R27 repaired mesh, markers, and wall-resolved SU2 config clear the bounded "
        "route-smoke gate. This permits attempting a true coarse/medium/fine ladder, "
        "but is still not grid-convergence evidence."
    )


def _cfg_marker_list(cfg_text: str, key: str) -> list[str]:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*\(([^)]*)\)", cfg_text, flags=re.MULTILINE)
    if match is None:
        return []
    markers: list[str] = []
    for token in match.group(1).split(","):
        stripped = token.strip()
        if not stripped or _is_number(stripped):
            continue
        markers.append(stripped)
    return markers


def _solver_quality_row_min(text: str, label: str) -> float | None:
    values = _solver_quality_row_values(text, label)
    return None if values is None else values[0]


def _solver_quality_row_max(text: str, label: str) -> float | None:
    values = _solver_quality_row_values(text, label)
    return None if values is None else values[1]


def _solver_quality_row_values(text: str, label: str) -> tuple[float, float] | None:
    pattern = re.compile(
        r"\|\s*"
        + re.escape(label)
        + r".*?\|\s*([-+0-9.eE]+)\s*\|\s*([-+0-9.eE]+)\s*\|"
    )
    match = pattern.search(text)
    if match is None:
        return None
    return float(match.group(1)), float(match.group(2))


def _normalize_history_key(key: str | None) -> str:
    return "" if key is None else key.strip().strip('"').strip()


def _first_float(row: Mapping[str, Any], *keys: str) -> float | None:
    lookup = {str(key).upper(): value for key, value in row.items()}
    for key in keys:
        value = _float_or_none(lookup.get(key.upper()))
        if value is not None:
            return value
    return None


def _first_int(row: Mapping[str, Any], *keys: str) -> int | None:
    value = _first_float(row, *keys)
    return None if value is None else int(value)


def _relative_span(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return None
    scale = max(abs(sum(clean) / len(clean)), 1.0e-12)
    return (max(clean) - min(clean)) / scale


def _absolute_span(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return None
    return max(clean) - min(clean)


def _float_or_none(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _format_su2_float(value: float) -> str:
    return f"{float(value):.12g}"


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _resolve_repo_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return REPO_ROOT / candidate


def _resolve_solver(command: str) -> str:
    path = Path(command)
    if path.exists():
        return str(path)
    resolved = shutil.which(command)
    if resolved is None:
        raise FileNotFoundError(f"SU2 solver command not found: {command}")
    return resolved


def _read_json(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path | str, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--r27-summary-path", type=Path, default=DEFAULT_R27_SUMMARY_PATH)
    parser.add_argument("--iterations", type=int, default=180)
    parser.add_argument("--alpha-deg", type=float, default=5.0)
    parser.add_argument("--cfl-number", type=float, default=1.0)
    parser.add_argument("--conv-num-method-flow", default="FDS")
    parser.add_argument("--muscl-flow", choices=("yes", "no"), default="yes")
    parser.add_argument("--slope-limiter-flow", default="NONE")
    parser.add_argument("--run-su2", action="store_true")
    parser.add_argument("--solver-command", default=DEFAULT_SOLVER_COMMAND)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args(argv)

    summary = run_probe(
        output_dir=args.output_dir,
        r27_summary_path=args.r27_summary_path,
        iterations=args.iterations,
        alpha_deg=args.alpha_deg,
        cfl_number=args.cfl_number,
        conv_num_method_flow=args.conv_num_method_flow,
        muscl_flow=args.muscl_flow == "yes",
        slope_limiter_flow=args.slope_limiter_flow,
        run_su2=args.run_su2,
        solver_command=args.solver_command,
        threads=args.threads,
        timeout_seconds=args.timeout_seconds,
        clean=not args.no_clean,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("verdict") == "r27_su2_route_smoke_completed_ladder_pending" else 2


if __name__ == "__main__":
    raise SystemExit(main())
