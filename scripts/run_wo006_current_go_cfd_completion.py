#!/usr/bin/env python3
"""Run a current-GO Baseline A main-wing CFD completion case.

This runner deliberately uses the repaired current-GO no-BL mesh-native route.
It does not promote the result to BL-resolved drag calibration; it only closes
the route-level requirement that a newly generated Baseline A mesh is marker
compatible, quality-gated, SU2-readable, and run far enough to write finite
force history.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.convergence import evaluate_iterative_gate  # noqa: E402
from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    build_wing_feature_refinement_boxes,
    write_faceted_volume_su2_case,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    build_farfield_box_surface,
)
from run_wo006r1_go_baseline_a_cfd_bridge import (  # noqa: E402
    DESIGN_GROSS_MASS_KG,
    PIPELINE_FULL_SPAN_M,
    PIPELINE_HALF_SPAN_M,
    _patch_runtime_reference_origin,
    build_current_go_wing_surface,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    MU_PA_S,
    RHO_KGPM3,
    SU2_COMMAND,
    VELOCITY_MPS,
    load_campaign_geometry,
)


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006_current_go_cfd_completion"
SREF_M2 = 33.420059598
CREF_M = 1.003721543
BREF_M = 34.332286
REQUIRED_MARKERS = ("wing_wall", "farfield")


def evaluate_completion_gate(
    run_report: Mapping[str, Any],
    *,
    minimum_iterations: int = 100,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []

    if run_report.get("run_status") != "completed" or run_report.get("returncode") != 0:
        blockers.append("su2_run_not_completed")

    mesh_report = run_report.get("mesh_report") or {}
    mesh_gate = mesh_report.get("mesh_quality_gate") or {}
    quality = mesh_report.get("quality_metrics") or {}
    if mesh_gate.get("status") != "pass":
        blockers.append("mesh_quality_gate_not_pass")
    for key in (
        "non_positive_volume_count",
        "non_positive_min_sicn_count",
        "non_positive_min_sige_count",
        "ill_shaped_volume_element_count",
    ):
        if int(quality.get(key) or 0) > 0:
            blockers.append(key)

    marker_audit = run_report.get("marker_audit") or {}
    mesh_summary = marker_audit.get("mesh_summary") or {}
    marker_summary = mesh_summary.get("markers") or {}
    if marker_audit.get("status") != "pass":
        blockers.append("mesh_marker_audit_not_pass")
    for marker in REQUIRED_MARKERS:
        marker_payload = marker_summary.get(marker) or {}
        if int(marker_payload.get("element_count") or 0) <= 0:
            blockers.append(f"{marker}_marker_missing_or_empty")

    history = run_report.get("history") or {}
    final_iteration = _optional_int(history.get("final_iteration"))
    if final_iteration is None:
        blockers.append("su2_iteration_missing")
    elif final_iteration < minimum_iterations:
        blockers.append("su2_iterations_below_minimum")

    coefficients = history.get("final_coefficients") or {}
    cl = _optional_float(coefficients.get("cl"))
    cd = _optional_float(coefficients.get("cd"))
    if cl is None:
        blockers.append("missing_cl")
    elif not math.isfinite(cl):
        blockers.append("non_finite_cl")
    if cd is None:
        blockers.append("missing_cd")
    elif not math.isfinite(cd):
        blockers.append("non_finite_cd")
    elif cd < 0.0:
        blockers.append("negative_cd")
    if cd is not None and math.isfinite(cd) and cd > 0.12:
        warnings.append("no_bl_drag_high_not_calibration_truth")

    residuals = history.get("final_residuals") or {}
    if not residuals:
        blockers.append("residuals_missing")
    for key, value in residuals.items():
        residual = _optional_float(value)
        if residual is None or not math.isfinite(residual):
            blockers.append(f"non_finite_residual_{key}")

    blockers = _dedupe(blockers)
    nan_inf_blockers = [
        blocker
        for blocker in blockers
        if blocker.startswith("non_finite") or blocker in {"missing_cl", "missing_cd"}
    ]
    return {
        "schema_version": "wo006_current_go_completion_gate.v1",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "warnings": warnings,
        "minimum_iterations": int(minimum_iterations),
        "su2_iterations_completed": final_iteration,
        "cl": cl,
        "cd": cd,
        "residual_status": "pass" if residuals and not nan_inf_blockers else "fail",
        "nan_inf_status": "pass" if not nan_inf_blockers else "fail",
        "mesh_quality_status": mesh_gate.get("status"),
        "marker_status": marker_audit.get("status"),
        "marker_policy": {
            "required": list(REQUIRED_MARKERS),
            "symmetry": "not_used_full_span_current_go_mesh_native_route",
        },
        "force_evidence_role": (
            "finite current-GO no-BL SU2 force history; usable as route-level "
            "force evidence, not BL/y+ viscous drag calibration"
        ),
    }


def run_completion_case(
    *,
    output_dir: Path,
    clean: bool = True,
    wing_h: float = 0.15,
    alpha_deg: float = 5.0,
    iterations: int = 160,
    minimum_iterations: int = 100,
    solver_command: str = SU2_COMMAND,
    solver_threads: int = 4,
    solver_timeout_seconds: float = 3600.0,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    geometry = load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
    wing = build_current_go_wing_surface(geometry)
    farfield = build_farfield_box_surface(
        wing,
        upstream_factor=2.0,
        downstream_factor=4.0,
        lateral_factor=2.0,
        vertical_factor=2.0,
    )
    feature_size = max(0.12, 1.5 * wing_h)
    case_report = write_faceted_volume_su2_case(
        wing,
        farfield,
        output_dir,
        ref_area=geometry.reference.sref_full,
        ref_length=geometry.reference.cref,
        mesh_size=max(2.0, 25.0 * wing_h),
        wing_mesh_size=wing_h,
        farfield_mesh_size=max(4.0, 40.0 * wing_h),
        wing_refinement_radius=6.0,
        refinement_boxes=build_wing_feature_refinement_boxes(wing, mesh_size=feature_size),
        velocity_mps=VELOCITY_MPS,
        alpha_deg=alpha_deg,
        max_iterations=iterations,
        solver="INC_RANS",
        turbulence_model="SA",
        wall_profile="adiabatic_no_slip",
        conv_num_method_flow="JST",
        cfl_number=0.15,
        linear_solver_error="1e-5",
        linear_solver_iter=12,
        conv_cauchy_elems=999,
        conv_cauchy_eps="1e-12",
        output_files=("RESTART_ASCII", "SURFACE_CSV"),
        gmsh_threads=4,
        mesh_algorithm3d=10,
        surface_triangulation_policy="shorter_diagonal",
    )
    runtime_cfg = Path(case_report["runtime_cfg_path"])
    _patch_runtime_cfg(runtime_cfg, geometry.moment_origin_m)

    solver_log = output_dir / "solver.log"
    history_path = output_dir / "history.csv"
    command = [str(solver_command), "-t", str(max(1, solver_threads)), runtime_cfg.name]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(max(1, solver_threads))
    try:
        with solver_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                cwd=output_dir,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                env=env,
                timeout=solver_timeout_seconds,
            )
        run_status = "completed" if completed.returncode == 0 and history_path.exists() else "failed"
        failure_code = None if run_status == "completed" else "solver_failed_or_history_missing"
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        run_status = "failed"
        failure_code = "solver_timeout"
        returncode = None

    history = parse_history_detail(history_path) if history_path.exists() else None
    iterative_gate = None
    if history_path.exists():
        iterative_gate = evaluate_iterative_gate(history_path).model_dump(mode="json")

    run_report = {
        **case_report,
        "schema_version": "wo006_current_go_cfd_completion.v1",
        "route": "current_go_mesh_native_no_bl_hxt_completion",
        "run_status": run_status,
        "failure_code": failure_code,
        "returncode": returncode,
        "solver_command": command,
        "solver_log_path": str(solver_log),
        "history_path": str(history_path) if history_path.exists() else None,
        "history": history,
        "iterative_gate": iterative_gate,
        "authority_basis": authority_payload(geometry),
        "geometry_recovery": geometry_recovery_payload(geometry),
        "boundary_layer_status": "not_used_no_bl_route",
        "external_shape_changed": False,
        "engineering_trust_boundary": (
            "No-BL RANS on a tet mesh is acceptable here only as finite SU2 "
            "route/force evidence. It is not BL-resolved drag, power, y+, grid "
            "V&V, RFQ, or final aircraft sign-off evidence."
        ),
    }
    gate = evaluate_completion_gate(run_report, minimum_iterations=minimum_iterations)
    run_report["completion_gate"] = gate
    write_json(output_dir / "completion_evidence.json", run_report)
    (output_dir / "completion_report.md").write_text(render_report(run_report), encoding="utf-8")
    return run_report


def parse_history_detail(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"SU2 history has no rows: {path}")
    final = rows[-1]
    normalized = {_norm_key(key): value for key, value in final.items()}
    residuals = {
        key.strip().strip('"'): _optional_float(value)
        for key, value in final.items()
        if key.strip().strip('"').lower().startswith("rms[")
    }
    return {
        "row_count": len(rows),
        "final_iteration": _lookup_int(normalized, "INNER_ITER", "OUTER_ITER", "ITER"),
        "final_coefficients": {
            "cl": _lookup_float(normalized, "CL", "LIFT"),
            "cd": _lookup_float(normalized, "CD", "DRAG"),
            "cmx": _lookup_float(normalized, "CMX"),
            "cmy": _lookup_float(normalized, "CMY", "CM"),
            "cmz": _lookup_float(normalized, "CMZ"),
        },
        "final_residuals": residuals,
    }


def authority_payload(geometry: Any) -> dict[str, Any]:
    return {
        "design_gross_mass_kg": DESIGN_GROSS_MASS_KG,
        "full_span_m": PIPELINE_FULL_SPAN_M,
        "half_span_m": PIPELINE_HALF_SPAN_M,
        "sref_m2": geometry.reference.sref_full,
        "cref_m": geometry.reference.cref,
        "bref_m": geometry.reference.bref_full,
        "density_kgpm3": RHO_KGPM3,
        "dynamic_viscosity_pa_s": MU_PA_S,
        "velocity_mps": VELOCITY_MPS,
        "geometry_source": str(geometry.section_table_path),
    }


def geometry_recovery_payload(geometry: Any, *, tolerance_m: float = 1.0e-6) -> dict[str, Any]:
    return {
        "status": "pass"
        if abs(geometry.full_span_m - PIPELINE_FULL_SPAN_M) <= tolerance_m
        and abs(geometry.half_span_m - PIPELINE_HALF_SPAN_M) <= tolerance_m
        else "fail",
        "tolerance_m": tolerance_m,
        "recovered_full_span_m": geometry.full_span_m,
        "authority_full_span_m": PIPELINE_FULL_SPAN_M,
        "recovered_half_span_m": geometry.half_span_m,
        "authority_half_span_m": PIPELINE_HALF_SPAN_M,
        "external_shape_changed": False,
    }


def render_report(run_report: Mapping[str, Any]) -> str:
    gate = run_report["completion_gate"]
    history = run_report.get("history") or {}
    coeffs = history.get("final_coefficients") or {}
    authority = run_report["authority_basis"]
    mesh_report = run_report.get("mesh_report") or {}
    quality = mesh_report.get("quality_metrics") or {}
    marker_audit = run_report.get("marker_audit") or {}
    marker_summary = (marker_audit.get("mesh_summary") or {}).get("markers") or {}
    lines = [
        "# WO-006 Current-GO CFD Completion Evidence",
        "",
        f"Completion gate: `{gate['status']}`",
        "",
        "## Route",
        "",
        "- route: `current_go_mesh_native_no_bl_hxt_completion`",
        "- boundary-layer route: `not_used_no_bl_route`",
        "- symmetry marker: `not_used_full_span_current_go_mesh_native_route`",
        "",
        "## Authority",
        "",
        f"- design mass: `{authority['design_gross_mass_kg']} kg`",
        f"- full span: `{authority['full_span_m']} m`",
        f"- half span: `{authority['half_span_m']} m`",
        f"- geometry source: `{authority['geometry_source']}`",
        "",
        "## Mesh",
        "",
        f"- mesh: `{run_report.get('mesh_path')}`",
        f"- quality gate: `{(mesh_report.get('mesh_quality_gate') or {}).get('status')}`",
        f"- volume elements: `{quality.get('volume_element_count')}`",
        f"- non-positive volumes: `{quality.get('non_positive_volume_count')}`",
        f"- markers: `{sorted(marker_summary)}`",
        "",
        "## SU2",
        "",
        f"- config: `{run_report.get('runtime_cfg_path')}`",
        f"- history: `{run_report.get('history_path')}`",
        f"- iterations completed: `{gate.get('su2_iterations_completed')}`",
        f"- CL: `{coeffs.get('cl')}`",
        f"- CD: `{coeffs.get('cd')}`",
        f"- NaN/Inf status: `{gate.get('nan_inf_status')}`",
        f"- residual status: `{gate.get('residual_status')}`",
        "",
        "## Engineering Trust Boundary",
        "",
        str(run_report["engineering_trust_boundary"]),
        "",
    ]
    return "\n".join(lines)


def _patch_runtime_cfg(path: Path, origin: tuple[float, float, float]) -> None:
    _patch_runtime_reference_origin(path, origin)
    text = path.read_text(encoding="utf-8")
    text = text.replace("CONV_STARTITER= 1", "CONV_STARTITER= 10000")
    additions = []
    if "MUSCL_FLOW= NO" not in text:
        additions.append("MUSCL_FLOW= NO")
    if "MUSCL_TURB= NO" not in text:
        additions.append("MUSCL_TURB= NO")
    if additions:
        text = text.rstrip() + "\n" + "\n".join(additions) + "\n"
    path.write_text(text, encoding="utf-8")


def _norm_key(value: str) -> str:
    return value.strip().strip('"').upper().replace(" ", "")


def _lookup_float(row: Mapping[str, str], *names: str) -> float | None:
    for name in names:
        value = row.get(_norm_key(name))
        if value is None or value == "":
            continue
        return _optional_float(value)
    return None


def _lookup_int(row: Mapping[str, str], *names: str) -> int | None:
    value = _lookup_float(row, *names)
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--wing-h", type=float, default=0.15)
    parser.add_argument("--alpha-deg", type=float, default=5.0)
    parser.add_argument("--iterations", type=int, default=160)
    parser.add_argument("--minimum-iterations", type=int, default=100)
    parser.add_argument("--solver-command", type=str, default=SU2_COMMAND)
    parser.add_argument("--solver-threads", type=int, default=4)
    parser.add_argument("--solver-timeout-seconds", type=float, default=3600.0)
    args = parser.parse_args(argv)

    report = run_completion_case(
        output_dir=args.output_dir,
        clean=not args.no_clean,
        wing_h=args.wing_h,
        alpha_deg=args.alpha_deg,
        iterations=args.iterations,
        minimum_iterations=args.minimum_iterations,
        solver_command=args.solver_command,
        solver_threads=args.solver_threads,
        solver_timeout_seconds=args.solver_timeout_seconds,
    )
    gate = report["completion_gate"]
    print(
        json.dumps(
            {
                "status": gate["status"],
                "output_dir": str(args.output_dir),
                "mesh": report.get("mesh_path"),
                "config": report.get("runtime_cfg_path"),
                "history": report.get("history_path"),
                "iterations": gate.get("su2_iterations_completed"),
                "cl": gate.get("cl"),
                "cd": gate.get("cd"),
                "blockers": gate.get("blockers"),
            },
            indent=2,
            allow_nan=False,
        )
    )
    return 0 if gate["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
