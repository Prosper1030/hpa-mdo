#!/usr/bin/env python3
"""WO-006R8 basic BL airfoil benchmark for SU2 route sanity.

This is intentionally not Baseline A completion evidence.  It is a small,
physics-owned diagnostic case: a cambered 2D NACA 4412 airfoil at the HPA
main-wing Reynolds-number scale, with a Gmsh boundary-layer mesh and SU2
incompressible RANS/SA no-slip wall setup.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
if str(HPA_MESHING_SRC) not in sys.path:
    sys.path.insert(0, str(HPA_MESHING_SRC))

from hpa_meshing.mesh_native.cfd_advisory import (  # noqa: E402
    flat_plate_cf_estimates,
    first_cell_height_for_yplus,
    geometric_boundary_layer_total_thickness,
    reynolds_number,
)
from hpa_meshing.mesh_native.su2_structured import parse_su2_marker_summary  # noqa: E402


DEFAULT_OUTPUT_DIR = Path(
    "output/baseline_A_team_release/wo006_su2_baseline_validation/"
    "wo006r8_basic_airfoil_bl_benchmark"
)


@dataclass(frozen=True)
class BoundaryLayerSettings:
    first_layer_height_m: float
    growth_ratio: float
    layer_count: int
    total_thickness_m: float
    target_yplus: float


@dataclass(frozen=True)
class BasicAirfoilCase:
    airfoil: str
    chord_m: float
    velocity_mps: float
    alpha_deg: float
    density_kgpm3: float
    dynamic_viscosity_pas: float
    reynolds_number: float
    expected_cl: float
    expected_cd_range: tuple[float, float]
    absurd_cd_threshold: float
    boundary_layer: BoundaryLayerSettings
    points_per_side: int
    farfield_radius_chord: float
    farfield_mesh_size_chord: float
    airfoil_mesh_size_chord: float
    max_iterations: int


def naca4_airfoil_loop(code: str, *, points_per_side: int = 97) -> list[tuple[float, float]]:
    """Return TE-upper -> LE -> TE-lower unit-chord NACA 4-digit coordinates."""
    digits = code.strip().upper().removeprefix("NACA").replace(" ", "")
    if len(digits) != 4 or not digits.isdigit():
        raise ValueError("code must be a NACA 4-digit airfoil, e.g. '4412'")
    if points_per_side < 5:
        raise ValueError("points_per_side must be at least 5")

    max_camber = int(digits[0]) / 100.0
    camber_pos = int(digits[1]) / 10.0
    thickness = int(digits[2:]) / 100.0
    if thickness <= 0.0:
        raise ValueError("NACA thickness must be positive")

    beta_values = [
        math.pi * index / (points_per_side - 1)
        for index in range(points_per_side)
    ]
    x_values = [0.5 * (1.0 + math.cos(beta)) for beta in beta_values]
    upper: list[tuple[float, float]] = []
    lower_te_to_le: list[tuple[float, float]] = []
    for x_coord in x_values:
        y_t = 5.0 * thickness * (
            0.2969 * math.sqrt(max(x_coord, 0.0))
            - 0.1260 * x_coord
            - 0.3516 * x_coord**2
            + 0.2843 * x_coord**3
            - 0.1015 * x_coord**4
        )
        if max_camber <= 0.0 or camber_pos <= 0.0:
            y_c = 0.0
            dyc_dx = 0.0
        elif x_coord < camber_pos:
            y_c = max_camber / camber_pos**2 * (
                2.0 * camber_pos * x_coord - x_coord**2
            )
            dyc_dx = 2.0 * max_camber / camber_pos**2 * (camber_pos - x_coord)
        else:
            y_c = max_camber / (1.0 - camber_pos) ** 2 * (
                (1.0 - 2.0 * camber_pos)
                + 2.0 * camber_pos * x_coord
                - x_coord**2
            )
            dyc_dx = 2.0 * max_camber / (1.0 - camber_pos) ** 2 * (
                camber_pos - x_coord
            )
        theta = math.atan(dyc_dx)
        upper.append((x_coord - y_t * math.sin(theta), y_c + y_t * math.cos(theta)))
        lower_te_to_le.append(
            (x_coord + y_t * math.sin(theta), y_c - y_t * math.cos(theta))
        )

    return upper + list(reversed(lower_te_to_le[:-1]))


def build_basic_airfoil_case(
    *,
    airfoil: str = "NACA4412",
    chord_m: float = 1.130189765,
    velocity_mps: float = 6.5,
    alpha_deg: float = 4.0,
    density_kgpm3: float = 1.225,
    dynamic_viscosity_pas: float = 1.7894e-5,
    points_per_side: int = 97,
    max_iterations: int = 600,
) -> BasicAirfoilCase:
    re_value = reynolds_number(
        density_kgpm3=density_kgpm3,
        velocity_mps=velocity_mps,
        length_m=chord_m,
        dynamic_viscosity_pas=dynamic_viscosity_pas,
    )
    yplus_one = first_cell_height_for_yplus(
        target_yplus=1.0,
        density_kgpm3=density_kgpm3,
        velocity_mps=velocity_mps,
        dynamic_viscosity_pas=dynamic_viscosity_pas,
        reference_length_m=chord_m,
    )
    first_layer_height = min(5.0e-5, float(yplus_one["first_cell_height_m"]))
    layer_count = 28
    growth_ratio = 1.20
    total_thickness = geometric_boundary_layer_total_thickness(
        first_layer_height_m=first_layer_height,
        layers=layer_count,
        growth_ratio=growth_ratio,
    )
    expected_cl = 2.0 * math.pi * math.radians(alpha_deg - (-2.0))
    cf_estimates = flat_plate_cf_estimates(re_value)
    turbulent_profile_floor = 2.0 * cf_estimates["turbulent_schlichting"]
    cd_low = max(0.006, 0.7 * turbulent_profile_floor)
    cd_high = 0.08
    return BasicAirfoilCase(
        airfoil=airfoil,
        chord_m=float(chord_m),
        velocity_mps=float(velocity_mps),
        alpha_deg=float(alpha_deg),
        density_kgpm3=float(density_kgpm3),
        dynamic_viscosity_pas=float(dynamic_viscosity_pas),
        reynolds_number=re_value,
        expected_cl=expected_cl,
        expected_cd_range=(cd_low, cd_high),
        absurd_cd_threshold=0.20,
        boundary_layer=BoundaryLayerSettings(
            first_layer_height_m=first_layer_height,
            growth_ratio=growth_ratio,
            layer_count=layer_count,
            total_thickness_m=total_thickness,
            target_yplus=1.0,
        ),
        points_per_side=int(points_per_side),
        farfield_radius_chord=25.0,
        farfield_mesh_size_chord=1.0,
        airfoil_mesh_size_chord=0.02,
        max_iterations=int(max_iterations),
    )


def write_basic_airfoil_bl_mesh(
    case: BasicAirfoilCase,
    output_dir: Path | str,
) -> dict[str, Any]:
    import gmsh

    case_dir = Path(output_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = case_dir / "basic_airfoil_bl.msh"
    su2_mesh_path = case_dir / "mesh.su2"
    points = [
        (case.chord_m * x_coord, case.chord_m * y_coord, 0.0)
        for x_coord, y_coord in naca4_airfoil_loop(
            case.airfoil,
            points_per_side=case.points_per_side,
        )
    ]
    far = case.farfield_radius_chord * case.chord_m
    upstream = 0.5 * case.chord_m - far
    downstream = 0.5 * case.chord_m + far
    lower = -far
    upper = far

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("wo006r8_basic_airfoil_bl")
        airfoil_point_tags = [
            gmsh.model.geo.addPoint(
                x_coord,
                y_coord,
                z_coord,
                case.airfoil_mesh_size_chord * case.chord_m,
            )
            for x_coord, y_coord, z_coord in points
        ]
        airfoil_curves = [
            gmsh.model.geo.addLine(
                airfoil_point_tags[index],
                airfoil_point_tags[(index + 1) % len(airfoil_point_tags)],
            )
            for index in range(len(airfoil_point_tags))
        ]
        farfield_point_tags = [
            gmsh.model.geo.addPoint(
                x_coord,
                y_coord,
                0.0,
                case.farfield_mesh_size_chord * case.chord_m,
            )
            for x_coord, y_coord in [
                (upstream, lower),
                (downstream, lower),
                (downstream, upper),
                (upstream, upper),
            ]
        ]
        farfield_curves = [
            gmsh.model.geo.addLine(
                farfield_point_tags[index],
                farfield_point_tags[(index + 1) % len(farfield_point_tags)],
            )
            for index in range(len(farfield_point_tags))
        ]
        outer_loop = gmsh.model.geo.addCurveLoop(farfield_curves)
        airfoil_loop = gmsh.model.geo.addCurveLoop(airfoil_curves)
        fluid_surface = gmsh.model.geo.addPlaneSurface([outer_loop, airfoil_loop])
        gmsh.model.geo.synchronize()

        airfoil_group = gmsh.model.addPhysicalGroup(1, airfoil_curves)
        gmsh.model.setPhysicalName(1, airfoil_group, "airfoil")
        farfield_group = gmsh.model.addPhysicalGroup(1, farfield_curves)
        gmsh.model.setPhysicalName(1, farfield_group, "farfield")
        fluid_group = gmsh.model.addPhysicalGroup(2, [fluid_surface])
        gmsh.model.setPhysicalName(2, fluid_group, "fluid")

        bl_field = gmsh.model.mesh.field.add("BoundaryLayer")
        gmsh.model.mesh.field.setNumbers(bl_field, "CurvesList", airfoil_curves)
        gmsh.model.mesh.field.setNumber(
            bl_field,
            "hwall_n",
            case.boundary_layer.first_layer_height_m,
        )
        gmsh.model.mesh.field.setNumber(
            bl_field,
            "ratio",
            case.boundary_layer.growth_ratio,
        )
        gmsh.model.mesh.field.setNumber(
            bl_field,
            "thickness",
            case.boundary_layer.total_thickness_m,
        )
        gmsh.model.mesh.field.setNumber(bl_field, "Quads", 1)
        gmsh.model.mesh.field.setNumber(bl_field, "AnisoMax", 1000.0)
        gmsh.model.mesh.field.setAsBoundaryLayer(bl_field)

        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.MeshSizeMin", case.boundary_layer.first_layer_height_m)
        gmsh.option.setNumber(
            "Mesh.MeshSizeMax",
            case.farfield_mesh_size_chord * case.chord_m,
        )
        gmsh.model.mesh.generate(2)
        gmsh.write(str(mesh_path))
        gmsh.write(str(su2_mesh_path))

        node_tags, _, _ = gmsh.model.mesh.getNodes()
        element_types, element_tags, _ = gmsh.model.mesh.getElements(2)
        cell_type_counts = {
            str(int(element_type)): len(tags)
            for element_type, tags in zip(element_types, element_tags)
        }
        physical_groups = {
            "airfoil": {
                "dimension": 1,
                "physical_tag": int(airfoil_group),
                "entity_count": len(airfoil_curves),
            },
            "farfield": {
                "dimension": 1,
                "physical_tag": int(farfield_group),
                "entity_count": len(farfield_curves),
            },
            "fluid": {
                "dimension": 2,
                "physical_tag": int(fluid_group),
                "entity_count": 1,
            },
        }
    finally:
        gmsh.finalize()

    marker_summary = parse_su2_marker_summary(su2_mesh_path)
    return {
        "status": "meshed",
        "route": "wo006r8_basic_airfoil_bl_gmsh",
        "mesh_path": str(mesh_path),
        "su2_mesh_path": str(su2_mesh_path),
        "node_count": len(node_tags),
        "cell_count": sum(cell_type_counts.values()),
        "cell_type_counts": cell_type_counts,
        "boundary_layer_quad_count": int(cell_type_counts.get("3", 0)),
        "physical_groups": physical_groups,
        "marker_summary": marker_summary,
        "boundary_layer": asdict(case.boundary_layer),
    }


def write_su2_config(case: BasicAirfoilCase, cfg_path: Path | str) -> Path:
    cfg_path = Path(cfg_path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    alpha_rad = math.radians(case.alpha_deg)
    vx = case.velocity_mps * math.cos(alpha_rad)
    vy = case.velocity_mps * math.sin(alpha_rad)
    cfg = "\n".join(
        [
            "% WO-006R8 Basic cambered-airfoil BL benchmark.",
            "% This is diagnostic route evidence, not Baseline A completion.",
            "SOLVER= INC_RANS",
            "KIND_TURB_MODEL= SA",
            "MATH_PROBLEM= DIRECT",
            "RESTART_SOL= NO",
            "SYSTEM_MEASUREMENTS= SI",
            "INC_NONDIM= INITIAL_VALUES",
            "INC_DENSITY_MODEL= CONSTANT",
            f"INC_DENSITY_INIT= {case.density_kgpm3:.6f}",
            f"INC_VELOCITY_INIT= ( {vx:.6f}, {vy:.6f}, 0.000000 )",
            "INC_TEMPERATURE_INIT= 288.150000",
            "VISCOSITY_MODEL= CONSTANT_VISCOSITY",
            f"MU_CONSTANT= {case.dynamic_viscosity_pas:.6e}",
            "FREESTREAM_NU_FACTOR= 3.0",
            f"AOA= {case.alpha_deg:.6f}",
            "SIDESLIP_ANGLE= 0.000000",
            f"REF_ORIGIN_MOMENT_X= {0.25 * case.chord_m:.6f}",
            "REF_ORIGIN_MOMENT_Y= 0.000000",
            "REF_ORIGIN_MOMENT_Z= 0.000000",
            f"REF_LENGTH= {case.chord_m:.6f}",
            f"REF_AREA= {case.chord_m:.6f}",
            "MARKER_HEATFLUX= ( airfoil, 0.0 )",
            "MARKER_FAR= ( farfield )",
            "MARKER_PLOTTING= ( airfoil )",
            "MARKER_MONITORING= ( airfoil )",
            "NUM_METHOD_GRAD= GREEN_GAUSS",
            "CFL_NUMBER= 5.0",
            "CFL_ADAPT= NO",
            "MAX_DELTA_TIME= 1E6",
            "CONV_NUM_METHOD_FLOW= FDS",
            "MUSCL_FLOW= YES",
            "SLOPE_LIMITER_FLOW= NONE",
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
            f"ITER= {case.max_iterations}",
            "CONV_FIELD= DRAG",
            "CONV_RESIDUAL_MINVAL= -9",
            "CONV_STARTITER= 10",
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
    cfg_path.write_text(cfg, encoding="utf-8")
    return cfg_path


def parse_su2_history(path: Path | str, *, tail_window: int = 100) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        raise ValueError(f"SU2 history has insufficient rows: {path}")
    header = [_normalize_history_key(value) for value in rows[0]]
    data = [
        {key: value.strip() for key, value in zip(header, row)}
        for row in rows[1:]
        if len(row) == len(header)
    ]
    if not data:
        raise ValueError(f"SU2 history has no data rows: {path}")
    final = data[-1]
    final_coefficients = {
        "cl": _history_first_float(final, ("CL", "LIFT", "LIFT_COEFFICIENT")),
        "cd": _history_first_float(final, ("CD", "DRAG", "DRAG_COEFFICIENT")),
        "cmy": _history_first_float(final, ("CMz", "CMZ", "CMy", "CMY")),
    }
    tail = data[-max(1, int(tail_window)) :]
    return {
        "path": str(path),
        "row_count": len(data),
        "final_iteration": _history_first_int(final, ("Inner_Iter", "ITER", "Iteration")),
        "final_coefficients": final_coefficients,
        "tail_stability": {
            "window_size": len(tail),
            "cl_relative_span": _relative_span(
                _history_first_float(row, ("CL", "LIFT", "LIFT_COEFFICIENT"))
                for row in tail
            ),
            "cd_relative_span": _relative_span(
                _history_first_float(row, ("CD", "DRAG", "DRAG_COEFFICIENT"))
                for row in tail
            ),
            "cmy_relative_span": _relative_span(
                _history_first_float(row, ("CMz", "CMZ", "CMy", "CMY"))
                for row in tail
            ),
            "residual_log10_span": _absolute_span(
                _history_first_float(
                    row,
                    (
                        "rms[P]",
                        "rms[Rho]",
                        "RMS_PRESSURE",
                        "RMS_DENSITY",
                        "RMS_RES",
                    ),
                )
                for row in tail
            ),
        },
    }


def coefficient_sanity_gate(
    case: BasicAirfoilCase,
    coefficients: Mapping[str, float | None],
    *,
    stable_window: Mapping[str, float | None] | None = None,
) -> dict[str, Any]:
    cl = _float_or_none(coefficients.get("cl"))
    cd = _float_or_none(coefficients.get("cd"))
    cmy = _float_or_none(coefficients.get("cmy"))
    blockers: list[str] = []
    warnings: list[str] = []
    if cl is None:
        blockers.append("cl_missing")
    if cd is None:
        blockers.append("cd_missing")
    elif cd <= 0.0:
        blockers.append("cd_non_positive")
    elif cd >= case.absurd_cd_threshold:
        blockers.append("cd_absurd_high_for_basic_airfoil")
    elif not (case.expected_cd_range[0] <= cd <= case.expected_cd_range[1]):
        warnings.append("cd_outside_expected_0xx_range")
    if cl is not None and abs(cl - case.expected_cl) > 0.45:
        warnings.append("cl_far_from_thin_airfoil_sanity_estimate")

    stable = False
    if stable_window:
        cl_span = _float_or_none(stable_window.get("cl_relative_span"))
        cd_span = _float_or_none(stable_window.get("cd_relative_span"))
        stable = (
            cl_span is not None
            and cd_span is not None
            and cl_span <= 0.01
            and cd_span <= 0.01
        )
        if not stable:
            warnings.append("tail_force_window_not_within_1_percent")

    status = "fail" if blockers else "pass"
    if blockers:
        engineering_read = "reject_solver_output"
    elif stable:
        engineering_read = "usable_basic_sanity_signal"
    else:
        engineering_read = "solver_ran_but_not_converged"
    return {
        "status": status,
        "blockers": blockers,
        "warnings": sorted(set(warnings)),
        "final_coefficients": {"cl": cl, "cd": cd, "cmy": cmy},
        "expected": {
            "cl_sanity_estimate": case.expected_cl,
            "cd_reasonable_range": list(case.expected_cd_range),
            "cd_absurd_high_threshold": case.absurd_cd_threshold,
        },
        "stable_window": None if stable_window is None else dict(stable_window),
        "engineering_read": engineering_read,
    }


def run_basic_airfoil_benchmark(
    case: BasicAirfoilCase,
    output_dir: Path | str,
    *,
    run_su2: bool,
    solver_command: str = "/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD",
    threads: int = 4,
    timeout_seconds: float = 1800.0,
) -> dict[str, Any]:
    case_dir = Path(output_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    mesh_report = write_basic_airfoil_bl_mesh(case, case_dir)
    cfg_path = write_su2_config(case, case_dir / "su2_runtime.cfg")

    solver_report: dict[str, Any] = {
        "run_requested": bool(run_su2),
        "run_status": "not_run",
        "reason": "run_su2_false",
    }
    history = None
    gate = None
    if run_su2:
        solver = _resolve_solver(solver_command)
        command = [solver, "-t", str(max(1, int(threads))), cfg_path.name]
        solver_log_path = case_dir / "solver.log"
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(max(1, int(threads)))
        run_start = time.monotonic()
        try:
            with solver_log_path.open("w", encoding="utf-8") as handle:
                completed = subprocess.run(
                    command,
                    cwd=case_dir,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                    timeout=timeout_seconds,
                    env=env,
                )
            elapsed = time.monotonic() - run_start
            history_path = case_dir / "history.csv"
            if history_path.exists():
                history = parse_su2_history(history_path, tail_window=100)
                gate = coefficient_sanity_gate(
                    case,
                    history["final_coefficients"],
                    stable_window=history["tail_stability"],
                )
            solver_report = {
                "run_requested": True,
                "run_status": "completed" if completed.returncode == 0 else "failed",
                "returncode": completed.returncode,
                "elapsed_s": elapsed,
                "command": command,
                "solver_log_path": str(solver_log_path),
                "history_path": str(history_path) if history_path.exists() else None,
                "history": history,
                "coefficient_sanity_gate": gate,
            }
        except subprocess.TimeoutExpired:
            solver_report = {
                "run_requested": True,
                "run_status": "timeout",
                "timeout_seconds": timeout_seconds,
                "command": command,
                "solver_log_path": str(solver_log_path),
            }

    report = {
        "schema_version": "wo006r8_basic_airfoil_bl_benchmark.v1",
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "case": _case_dict(case),
        "mesh": mesh_report,
        "su2_config_path": str(cfg_path),
        "solver": solver_report,
        "engineering_assessment": _engineering_assessment(case, mesh_report, solver_report),
        "elapsed_s": time.monotonic() - start,
    }
    report_path = case_dir / "basic_airfoil_bl_benchmark_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path = case_dir / "basic_airfoil_bl_benchmark_report.md"
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    report["report_path"] = str(report_path)
    report["markdown_report_path"] = str(markdown_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _engineering_assessment(
    case: BasicAirfoilCase,
    mesh_report: Mapping[str, Any],
    solver_report: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    if int(mesh_report.get("boundary_layer_quad_count", 0)) <= 0:
        blockers.append("no_boundary_layer_quads")
    if solver_report.get("run_requested") and solver_report.get("run_status") != "completed":
        blockers.append("su2_basic_case_not_completed")
    gate = solver_report.get("coefficient_sanity_gate")
    if isinstance(gate, Mapping) and gate.get("status") == "fail":
        blockers.extend(str(item) for item in gate.get("blockers", []))
    return {
        "status": "blocked" if blockers else "basic_sanity_case_available",
        "blockers": sorted(set(blockers)),
        "interpretation": (
            "Basic BL case rejects the current solver/mesh output; fix the simple case first."
            if blockers
            else "Basic BL case is usable as route sanity, but it is not a Baseline A mesh ladder."
        ),
        "trust_boundary": (
            "This diagnostic uses a 2D NACA 4412 cambered airfoil at HPA Reynolds scale. "
            "It can catch BL/BC/SU2 coefficient-scale failures, but it cannot replace "
            "Baseline A 3D grid convergence."
        ),
        "expected_cd_scale": f"{case.expected_cd_range[0]:.3f}-{case.expected_cd_range[1]:.3f}",
    }


def _markdown_report(report: Mapping[str, Any]) -> str:
    case = report["case"]
    mesh = report["mesh"]
    solver = report["solver"]
    gate = solver.get("coefficient_sanity_gate") if isinstance(solver, Mapping) else None
    coeffs = (gate or {}).get("final_coefficients", {}) if isinstance(gate, Mapping) else {}
    return "\n".join(
        [
            "# WO-006R8 Basic Airfoil BL Benchmark",
            "",
            "This is a diagnostic simple case, not Baseline A completion evidence.",
            "",
            "## Case",
            "",
            f"- airfoil: `{case['airfoil']}`",
            f"- chord: `{case['chord_m']:.6f} m`",
            f"- velocity: `{case['velocity_mps']:.3f} m/s`",
            f"- alpha: `{case['alpha_deg']:.3f} deg`",
            f"- Reynolds number: `{case['reynolds_number']:.3e}`",
            f"- expected CL sanity estimate: `{case['expected_cl']:.3f}`",
            f"- expected CD scale: `{case['expected_cd_range'][0]:.3f}` to `{case['expected_cd_range'][1]:.3f}`",
            "",
            "## Mesh",
            "",
            f"- nodes: `{mesh['node_count']}`",
            f"- cells: `{mesh['cell_count']}`",
            f"- cell type counts: `{mesh['cell_type_counts']}`",
            f"- BL quad count: `{mesh['boundary_layer_quad_count']}`",
            f"- markers: `{sorted(mesh['marker_summary']['markers'])}`",
            "",
            "## SU2",
            "",
            f"- run status: `{solver.get('run_status')}`",
            f"- final CL: `{coeffs.get('cl')}`",
            f"- final CD: `{coeffs.get('cd')}`",
            f"- final CMy/CMz: `{coeffs.get('cmy')}`",
            f"- coefficient gate: `{None if gate is None else gate.get('status')}`",
            "",
            "## Assessment",
            "",
            f"- status: `{report['engineering_assessment']['status']}`",
            f"- blockers: `{report['engineering_assessment']['blockers']}`",
            f"- CFD_STATUS: `{report['cfd_status']}`",
            f"- GOAL_STATUS: `{report['goal_status']}`",
            "",
        ]
    )


def _case_dict(case: BasicAirfoilCase) -> dict[str, Any]:
    data = asdict(case)
    data["expected_cd_range"] = list(case.expected_cd_range)
    return data


def _normalize_history_key(value: str) -> str:
    return value.strip().strip('"').strip()


def _history_first_float(row: Mapping[str, str], keys: Iterable[str]) -> float | None:
    lookup = {key.upper(): value for key, value in row.items()}
    for key in keys:
        raw = lookup.get(key.upper())
        if raw is None:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return None


def _history_first_int(row: Mapping[str, str], keys: Iterable[str]) -> int | None:
    value = _history_first_float(row, keys)
    return None if value is None else int(value)


def _relative_span(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return None
    mean_abs = max(abs(sum(clean) / len(clean)), 1.0e-12)
    return (max(clean) - min(clean)) / mean_abs


def _absolute_span(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return None
    return max(clean) - min(clean)


def _float_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _resolve_solver(command: str) -> str:
    path = Path(command)
    if path.exists():
        return str(path)
    resolved = shutil.which(command)
    if resolved is None:
        raise FileNotFoundError(f"SU2 solver command not found: {command}")
    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--iterations", type=int, default=600)
    parser.add_argument("--points-per-side", type=int, default=97)
    parser.add_argument("--run-su2", action="store_true")
    parser.add_argument(
        "--solver-command",
        default="/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD",
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    args = parser.parse_args(argv)

    case = build_basic_airfoil_case(
        points_per_side=args.points_per_side,
        max_iterations=args.iterations,
    )
    report = run_basic_airfoil_benchmark(
        case,
        args.output_dir,
        run_su2=args.run_su2,
        solver_command=args.solver_command,
        threads=args.threads,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
