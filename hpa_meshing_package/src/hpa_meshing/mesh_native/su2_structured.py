from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable, Literal, Sequence

from .wing_surface import SurfaceMesh, Vertex

SU2_QUAD = 9
SU2_HEXAHEDRON = 12
_AXES = ("x", "y", "z")


def write_structured_box_shell_su2(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    out_path: Path | str,
    *,
    wall_marker: str = "wing_wall",
    farfield_marker: str = "farfield",
) -> dict[str, Any]:
    """Write a tiny mesh-native SU2 smoke mesh around the wing bounding box.

    This is deliberately a topology/marker/SU2-parser smoke mesh: the actual
    wing surface is represented by its bounding box, so aerodynamic coefficients
    from this mesh are not physically meaningful.
    """
    out_path = Path(out_path)
    volume = _structured_box_shell_volume(
        wing,
        farfield,
        wall_marker=wall_marker,
        farfield_marker=farfield_marker,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_su2_text(volume), encoding="utf-8")
    return _report(volume)


def write_structured_box_shell_su2_case(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    case_dir: Path | str,
    *,
    ref_area: float,
    ref_length: float,
    velocity_mps: float = 6.5,
    alpha_deg: float = 0.0,
    max_iterations: int = 5,
    solver: str = "INC_EULER",
    wall_marker: str = "wing_wall",
    farfield_marker: str = "farfield",
) -> dict[str, Any]:
    if ref_area <= 0.0:
        raise ValueError("ref_area must be positive")
    if ref_length <= 0.0:
        raise ValueError("ref_length must be positive")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")

    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = case_dir / "mesh.su2"
    runtime_cfg_path = case_dir / "su2_runtime.cfg"
    report_path = case_dir / "mesh_native_su2_smoke_report.json"

    mesh_report = write_structured_box_shell_su2(
        wing,
        farfield,
        mesh_path,
        wall_marker=wall_marker,
        farfield_marker=farfield_marker,
    )
    runtime_cfg_path.write_text(
        _smoke_cfg_text(
            wing,
            solver=solver,
            ref_area=ref_area,
            ref_length=ref_length,
            velocity_mps=velocity_mps,
            alpha_deg=alpha_deg,
            max_iterations=max_iterations,
            wall_marker=wall_marker,
            farfield_marker=farfield_marker,
        ),
        encoding="utf-8",
    )
    marker_audit = audit_su2_case_markers(mesh_path, runtime_cfg_path)
    report = {
        "route": "mesh_native_structured_box_shell_su2_smoke_case",
        "mesh_path": str(mesh_path),
        "runtime_cfg_path": str(runtime_cfg_path),
        "report_path": str(report_path),
        "mesh_report": mesh_report,
        "marker_audit": marker_audit,
        "runtime": {
            "solver": solver,
            "velocity_mps": velocity_mps,
            "alpha_deg": alpha_deg,
            "max_iterations": max_iterations,
            "ref_area": ref_area,
            "ref_length": ref_length,
        },
        "caveats": [
            *mesh_report["caveats"],
            "case is intended to prove SU2 readability and marker ownership only",
        ],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def run_structured_box_shell_su2_smoke(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    case_dir: Path | str,
    *,
    ref_area: float,
    ref_length: float,
    velocity_mps: float = 6.5,
    alpha_deg: float = 0.0,
    max_iterations: int = 3,
    solver: str = "INC_EULER",
    solver_command: str = "SU2_CFD",
    threads: int = 1,
) -> dict[str, Any]:
    case_report = write_structured_box_shell_su2_case(
        wing,
        farfield,
        case_dir,
        ref_area=ref_area,
        ref_length=ref_length,
        velocity_mps=velocity_mps,
        alpha_deg=alpha_deg,
        max_iterations=max_iterations,
        solver=solver,
    )
    case_path = Path(case_dir)
    solver_path = _resolve_solver_command(solver_command)
    solver_log_path = case_path / "solver.log"
    history_path = case_path / "history.csv"
    worker_count = max(1, int(threads))
    command = [solver_path, "-t", str(worker_count), "su2_runtime.cfg"]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(worker_count)

    with solver_log_path.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            command,
            cwd=case_path,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            env=env,
        )

    history = _parse_smoke_history(history_path) if history_path.exists() else None
    failure_code = None
    if completed.returncode != 0:
        failure_code = "solver_execution_failed"
    elif history is None:
        failure_code = "history_missing"

    run_status = "completed" if failure_code is None else "failed"
    run_report = {
        **case_report,
        "run_status": run_status,
        "failure_code": failure_code,
        "returncode": completed.returncode,
        "solver_command": command,
        "solver_log_path": str(solver_log_path),
        "history_path": str(history_path) if history_path.exists() else None,
        "history": history,
        "engineering_assessment": {
            "solver_readability": "pass" if run_status == "completed" else "fail",
            "marker_ownership": case_report["marker_audit"]["status"],
            "aero_coefficients_interpretable": False,
            "reason": "bounding_box_obstacle_26_hexa_smoke_mesh",
        },
    }
    Path(case_report["report_path"]).write_text(json.dumps(run_report, indent=2), encoding="utf-8")
    return run_report


def audit_su2_case_markers(mesh_path: Path | str, runtime_cfg_path: Path | str) -> dict[str, Any]:
    mesh_summary = parse_su2_marker_summary(mesh_path)
    cfg_text = Path(runtime_cfg_path).read_text(encoding="utf-8", errors="replace")
    boundary_condition_markers = _boundary_condition_markers(cfg_text)

    mesh_markers = set(mesh_summary["markers"])
    assigned_bc_markers = {
        marker
        for markers in boundary_condition_markers.values()
        for marker in markers
    }
    zero_element_markers = sorted(
        marker
        for marker, summary in mesh_summary["markers"].items()
        if int(summary.get("element_count", 0)) <= 0
    )
    missing_from_mesh = sorted(assigned_bc_markers - mesh_markers)
    unassigned_mesh_markers = sorted(mesh_markers - assigned_bc_markers)
    status = (
        "pass"
        if not zero_element_markers
        and not missing_from_mesh
        and not unassigned_mesh_markers
        else "fail"
    )
    return {
        "status": status,
        "mesh_markers": sorted(mesh_markers),
        "boundary_condition_markers": boundary_condition_markers,
        "missing_from_mesh": missing_from_mesh,
        "unassigned_mesh_markers": unassigned_mesh_markers,
        "zero_element_markers": zero_element_markers,
        "mesh_summary": mesh_summary,
    }


def parse_su2_marker_summary(path: Path | str) -> dict[str, Any]:
    lines = [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    ndime = _header_int(lines, "NDIME")
    nelem = _header_int(lines, "NELEM")
    npoin = _header_int(lines, "NPOIN")
    nmark = _header_int(lines, "NMARK")

    markers: dict[str, dict[str, Any]] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("MARKER_TAG="):
            index += 1
            continue
        marker = line.split("=", 1)[1].strip()
        elem_count = int(lines[index + 1].split("=", 1)[1].strip())
        type_counts: dict[str, int] = {}
        for elem_line in lines[index + 2 : index + 2 + elem_count]:
            elem_type = elem_line.split()[0]
            type_counts[elem_type] = type_counts.get(elem_type, 0) + 1
        markers[marker] = {
            "element_count": elem_count,
            "element_type_counts": dict(sorted(type_counts.items())),
        }
        index += 2 + elem_count

    return {
        "ndime": ndime,
        "nelem": nelem,
        "npoin": npoin,
        "nmark": nmark,
        "markers": markers,
    }


def _resolve_solver_command(solver_command: str) -> str:
    command_path = Path(solver_command)
    if command_path.exists():
        return str(command_path)
    resolved = shutil.which(solver_command)
    if resolved is None:
        raise FileNotFoundError(f"SU2 solver command not found: {solver_command}")
    return resolved


def _parse_smoke_history(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        raise ValueError(f"SU2 history has insufficient rows: {path}")

    header = [_normalize_history_header(value) for value in rows[0]]
    data_rows = [
        {key: value.strip() for key, value in zip(header, raw_values)}
        for raw_values in rows[1:]
        if len(raw_values) == len(header)
    ]
    if not data_rows:
        raise ValueError(f"SU2 history has no parseable data rows: {path}")

    final = data_rows[-1]
    return {
        "row_count": len(data_rows),
        "final_iteration": _history_int(final, "Inner_Iter"),
        "final_coefficients": {
            "cl": _history_float(final, "CL"),
            "cd": _history_float(final, "CD"),
            "cmx": _history_float(final, "CMx"),
            "cmy": _history_float(final, "CMy"),
            "cmz": _history_float(final, "CMz"),
        },
    }


def _normalize_history_header(value: str) -> str:
    return value.strip().strip('"').strip()


def _history_float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _history_int(row: dict[str, str], key: str) -> int | None:
    value = _history_float(row, key)
    if value is None:
        return None
    return int(value)


def _smoke_cfg_text(
    wing: SurfaceMesh,
    *,
    solver: str,
    turbulence_model: str = "NONE",
    transition_model: str | None = None,
    ref_area: float,
    ref_length: float,
    velocity_mps: float,
    alpha_deg: float,
    max_iterations: int,
    wall_marker: str,
    farfield_marker: str,
    wall_profile: Literal["euler_slip", "adiabatic_no_slip"] = "euler_slip",
    conv_num_method_flow: str = "FDS",
    cfl_number: float = 1.0,
    linear_solver_error: float | str = "1e-6",
    linear_solver_iter: int = 10,
    jst_sensor_coeff: Sequence[float] | None = None,
    wall_function: str | None = None,
    conv_cauchy_elems: int | None = None,
    conv_cauchy_eps: float | str | None = None,
    output_files: Sequence[str] = ("RESTART_ASCII", "PARAVIEW_ASCII", "SURFACE_CSV"),
) -> str:
    if cfl_number <= 0.0:
        raise ValueError("cfl_number must be positive")
    if linear_solver_iter <= 0:
        raise ValueError("linear_solver_iter must be positive")
    if conv_cauchy_elems is not None and conv_cauchy_elems <= 0:
        raise ValueError("conv_cauchy_elems must be positive")
    if not output_files:
        raise ValueError("output_files must not be empty")
    if jst_sensor_coeff is not None and len(jst_sensor_coeff) != 2:
        raise ValueError("jst_sensor_coeff must contain exactly two values")
    if wall_profile not in {"euler_slip", "adiabatic_no_slip"}:
        raise ValueError(f"Unsupported wall_profile: {wall_profile}")
    resolved_solver = solver.strip().upper()
    resolved_turbulence_model = turbulence_model.strip().upper()
    resolved_transition_model = (
        "NONE" if transition_model is None else transition_model.strip().upper()
    )
    if resolved_turbulence_model != "NONE" and resolved_solver not in {"RANS", "INC_RANS"}:
        raise ValueError("turbulence_model requires RANS or INC_RANS solver")
    if wall_function is not None and resolved_turbulence_model == "NONE":
        raise ValueError("wall_function requires a turbulence model")

    alpha_rad = math.radians(alpha_deg)
    vx = velocity_mps * math.cos(alpha_rad)
    vz = velocity_mps * math.sin(alpha_rad)
    origin = _bounds_center(wing.bounds())
    flow_method = conv_num_method_flow.strip().upper()
    lines = [
        "% Auto-generated mesh-native SU2 smoke case.",
        "% This smoke case proves mesh readability and marker ownership only.",
        "% Do not interpret aerodynamic coefficients from this case.",
        f"SOLVER= {resolved_solver}",
        f"KIND_TURB_MODEL= {resolved_turbulence_model}",
        f"KIND_TRANS_MODEL= {resolved_transition_model}",
        "MATH_PROBLEM= DIRECT",
        "SYSTEM_MEASUREMENTS= SI",
        "RESTART_SOL= NO",
        "INC_NONDIM= DIMENSIONAL",
        "INC_DENSITY_MODEL= CONSTANT",
        "FLUID_MODEL= INC_IDEAL_GAS",
        "VISCOSITY_MODEL= CONSTANT_VISCOSITY",
        "MU_CONSTANT= 1.789400e-05",
        "INC_DENSITY_INIT= 1.225000",
        "INC_TEMPERATURE_INIT= 288.150000",
        f"INC_VELOCITY_INIT= ( {vx:.6f}, 0.000000, {vz:.6f} )",
        f"AOA= {alpha_deg:.6f}",
        "SIDESLIP_ANGLE= 0.000000",
        f"REF_AREA= {ref_area:.6f}",
        f"REF_LENGTH= {ref_length:.6f}",
        f"REF_ORIGIN_MOMENT_X= {origin[0]:.6f}",
        f"REF_ORIGIN_MOMENT_Y= {origin[1]:.6f}",
        f"REF_ORIGIN_MOMENT_Z= {origin[2]:.6f}",
        "MESH_FILENAME= mesh.su2",
        "MESH_FORMAT= SU2",
        *_wall_boundary_lines(wall_marker, wall_profile=wall_profile),
        f"MARKER_MONITORING= ( {wall_marker} )",
        f"MARKER_PLOTTING= ( {wall_marker} )",
        f"MARKER_FAR= ( {farfield_marker} )",
        *(
            []
            if wall_function is None
            else [f"MARKER_WALL_FUNCTIONS= ( {wall_marker}, {wall_function.strip().upper()} )"]
        ),
        *(
            []
            if resolved_turbulence_model == "NONE"
            else [
                "FREESTREAM_TURBULENCEINTENSITY= 0.05",
                "FREESTREAM_TURB2LAMVISCRATIO= 10.0",
            ]
        ),
        "NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES",
        f"CONV_NUM_METHOD_FLOW= {flow_method}",
        *(
            []
            if flow_method == "JST"
            else [
                "MUSCL_FLOW= YES",
                "SLOPE_LIMITER_FLOW= NONE",
            ]
        ),
        "TIME_DISCRE_FLOW= EULER_IMPLICIT",
        *(
            []
            if resolved_turbulence_model == "NONE"
            else [
                "CONV_NUM_METHOD_TURB= SCALAR_UPWIND",
                "MUSCL_TURB= NO",
                "SLOPE_LIMITER_TURB= VENKATAKRISHNAN",
                "TIME_DISCRE_TURB= EULER_IMPLICIT",
            ]
        ),
        "LINEAR_SOLVER= FGMRES",
        "LINEAR_SOLVER_PREC= ILU",
        f"LINEAR_SOLVER_ERROR= {_format_su2_value(linear_solver_error)}",
        f"LINEAR_SOLVER_ITER= {int(linear_solver_iter)}",
        f"ITER= {max_iterations}",
        f"CFL_NUMBER= {_format_su2_value(cfl_number)}",
        "CONV_FIELD= DRAG",
        "CONV_RESIDUAL_MINVAL= -9",
        "CONV_STARTITER= 1",
        "CONV_FILENAME= history",
        "TABULAR_FORMAT= CSV",
        "SCREEN_OUTPUT= (INNER_ITER, RMS_RES, AERO_COEFF)",
        "HISTORY_OUTPUT= (ITER, RMS_RES, AERO_COEFF)",
        f"OUTPUT_FILES= ({', '.join(output_files)})",
        "",
    ]
    if jst_sensor_coeff is not None:
        lines.insert(
            lines.index("TIME_DISCRE_FLOW= EULER_IMPLICIT"),
            "JST_SENSOR_COEFF= ( "
            f"{_format_su2_value(jst_sensor_coeff[0])}, "
            f"{_format_su2_value(jst_sensor_coeff[1])} )",
        )
    if conv_cauchy_elems is not None:
        lines.insert(-1, f"CONV_CAUCHY_ELEMS= {int(conv_cauchy_elems)}")
    if conv_cauchy_eps is not None:
        lines.insert(-1, f"CONV_CAUCHY_EPS= {_format_su2_value(conv_cauchy_eps)}")
    return "\n".join(lines)


def _wall_boundary_lines(
    wall_marker: str,
    *,
    wall_profile: Literal["euler_slip", "adiabatic_no_slip"],
) -> list[str]:
    if wall_profile == "euler_slip":
        return [f"MARKER_EULER= ( {wall_marker} )"]
    if wall_profile == "adiabatic_no_slip":
        return [f"MARKER_HEATFLUX= ( {wall_marker}, 0.0 )"]
    raise ValueError(f"Unsupported wall_profile: {wall_profile}")


def _bounds_center(bounds: dict[str, float]) -> Vertex:
    return (
        0.5 * (bounds["x_min"] + bounds["x_max"]),
        0.5 * (bounds["y_min"] + bounds["y_max"]),
        0.5 * (bounds["z_min"] + bounds["z_max"]),
    )


def _format_su2_value(value: float | str) -> str:
    if isinstance(value, str):
        return value
    return f"{float(value):.12g}"


def _boundary_condition_markers(cfg_text: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for key in ("MARKER_EULER", "MARKER_HEATFLUX", "MARKER_SYM", "MARKER_FAR"):
        markers = _cfg_marker_list(cfg_text, key)
        if markers:
            parsed[key] = markers
    return parsed


def _cfg_marker_list(cfg_text: str, key: str) -> list[str]:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*\(([^)]*)\)", cfg_text, flags=re.MULTILINE)
    if match is None:
        return []
    markers: list[str] = []
    for raw_token in match.group(1).split(","):
        token = raw_token.strip()
        if not token or _is_number(token):
            continue
        markers.append(token)
    return markers


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _header_int(lines: Iterable[str], key: str) -> int:
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            return int(line.split("=", 1)[1].strip())
    raise ValueError(f"SU2 header missing: {key}")


def _structured_box_shell_volume(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    *,
    wall_marker: str,
    farfield_marker: str,
) -> dict[str, Any]:
    wing_bounds = wing.bounds()
    farfield_bounds = farfield.bounds()
    axes = {
        axis: _axis_values(wing_bounds, farfield_bounds, axis)
        for axis in _AXES
    }
    nodes = _nodes(axes)
    elements: list[tuple[int, tuple[int, ...]]] = []
    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {
        farfield_marker: [],
        wall_marker: [],
    }
    excluded = (1, 1, 1)

    for i in range(3):
        for j in range(3):
            for k in range(3):
                cell = (i, j, k)
                if cell == excluded:
                    continue
                elements.append((SU2_HEXAHEDRON, _hex_nodes(i, j, k)))
                for direction in _cell_faces(i, j, k):
                    neighbor = (
                        i + direction["delta"][0],
                        j + direction["delta"][1],
                        k + direction["delta"][2],
                    )
                    if _outside_grid(neighbor):
                        marker_faces[farfield_marker].append((SU2_QUAD, direction["nodes"]))
                    elif neighbor == excluded:
                        marker_faces[wall_marker].append((SU2_QUAD, direction["nodes"]))

    return {
        "nodes": nodes,
        "elements": elements,
        "marker_faces": marker_faces,
        "wing_bounds": wing_bounds,
        "farfield_bounds": farfield_bounds,
    }


def _axis_values(
    wing_bounds: dict[str, float],
    farfield_bounds: dict[str, float],
    axis: Literal["x", "y", "z"],
) -> list[float]:
    values = [
        farfield_bounds[f"{axis}_min"],
        wing_bounds[f"{axis}_min"],
        wing_bounds[f"{axis}_max"],
        farfield_bounds[f"{axis}_max"],
    ]
    if not values[0] < values[1] < values[2] < values[3]:
        raise ValueError("Farfield bounds must strictly enclose wing bounds")
    return values


def _node_id(i: int, j: int, k: int) -> int:
    return i * 16 + j * 4 + k


def _nodes(axes: dict[str, list[float]]) -> list[Vertex]:
    nodes: list[Vertex] = []
    for i in range(4):
        for j in range(4):
            for k in range(4):
                nodes.append((axes["x"][i], axes["y"][j], axes["z"][k]))
    return nodes


def _hex_nodes(i: int, j: int, k: int) -> tuple[int, ...]:
    return (
        _node_id(i, j, k),
        _node_id(i + 1, j, k),
        _node_id(i + 1, j + 1, k),
        _node_id(i, j + 1, k),
        _node_id(i, j, k + 1),
        _node_id(i + 1, j, k + 1),
        _node_id(i + 1, j + 1, k + 1),
        _node_id(i, j + 1, k + 1),
    )


def _cell_faces(i: int, j: int, k: int) -> list[dict[str, Any]]:
    return [
        {
            "delta": (-1, 0, 0),
            "nodes": (
                _node_id(i, j, k),
                _node_id(i, j + 1, k),
                _node_id(i, j + 1, k + 1),
                _node_id(i, j, k + 1),
            ),
        },
        {
            "delta": (1, 0, 0),
            "nodes": (
                _node_id(i + 1, j, k),
                _node_id(i + 1, j, k + 1),
                _node_id(i + 1, j + 1, k + 1),
                _node_id(i + 1, j + 1, k),
            ),
        },
        {
            "delta": (0, -1, 0),
            "nodes": (
                _node_id(i, j, k),
                _node_id(i, j, k + 1),
                _node_id(i + 1, j, k + 1),
                _node_id(i + 1, j, k),
            ),
        },
        {
            "delta": (0, 1, 0),
            "nodes": (
                _node_id(i, j + 1, k),
                _node_id(i + 1, j + 1, k),
                _node_id(i + 1, j + 1, k + 1),
                _node_id(i, j + 1, k + 1),
            ),
        },
        {
            "delta": (0, 0, -1),
            "nodes": (
                _node_id(i, j, k),
                _node_id(i + 1, j, k),
                _node_id(i + 1, j + 1, k),
                _node_id(i, j + 1, k),
            ),
        },
        {
            "delta": (0, 0, 1),
            "nodes": (
                _node_id(i, j, k + 1),
                _node_id(i, j + 1, k + 1),
                _node_id(i + 1, j + 1, k + 1),
                _node_id(i + 1, j, k + 1),
            ),
        },
    ]


def _outside_grid(cell: tuple[int, int, int]) -> bool:
    return any(index < 0 or index > 2 for index in cell)


def _su2_text(volume: dict[str, Any]) -> str:
    lines = [
        "% Mesh-native structured box-shell smoke mesh.",
        "% The inner wing_wall marker is the wing bounding box, not the true wing surface.",
        "NDIME= 3",
        f"NELEM= {len(volume['elements'])}",
    ]
    for elem_id, (elem_type, nodes) in enumerate(volume["elements"]):
        lines.append(f"{elem_type} {' '.join(str(node) for node in nodes)} {elem_id}")

    lines.append(f"NPOIN= {len(volume['nodes'])}")
    for node_id, (x, y, z) in enumerate(volume["nodes"]):
        lines.append(f"{x:.16g} {y:.16g} {z:.16g} {node_id}")

    marker_faces = volume["marker_faces"]
    lines.append(f"NMARK= {len(marker_faces)}")
    for marker in sorted(marker_faces):
        faces = marker_faces[marker]
        lines.append(f"MARKER_TAG= {marker}")
        lines.append(f"MARKER_ELEMS= {len(faces)}")
        for elem_type, nodes in faces:
            lines.append(f"{elem_type} {' '.join(str(node) for node in nodes)}")
    lines.append("")
    return "\n".join(lines)


def _report(volume: dict[str, Any]) -> dict[str, Any]:
    return {
        "route": "mesh_native_structured_box_shell_smoke",
        "node_count": len(volume["nodes"]),
        "volume_element_count": len(volume["elements"]),
        "marker_summary": _marker_summary(volume["marker_faces"]),
        "wing_bounds": volume["wing_bounds"],
        "farfield_bounds": volume["farfield_bounds"],
        "caveats": [
            "wing boundary is represented by the wing bounding box for SU2 smoke only",
            "not valid for aerodynamic coefficient interpretation",
        ],
    }


def _marker_summary(marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for marker in sorted(marker_faces):
        type_counts: dict[str, int] = {}
        for elem_type, _nodes_for_face in marker_faces[marker]:
            key = str(elem_type)
            type_counts[key] = type_counts.get(key, 0) + 1
        summary[marker] = {
            "element_count": len(marker_faces[marker]),
            "element_type_counts": dict(sorted(type_counts.items())),
        }
    return summary
