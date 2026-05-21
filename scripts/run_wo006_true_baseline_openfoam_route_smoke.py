#!/usr/bin/env python3
"""Run WO-006 Phase 4 OpenFOAM route-smoke on the accepted swept C-grid mesh."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_true_baseline_openfoam_route_smoke"
DEFAULT_SOURCE_CASE = (
    REPO_ROOT
    / ".claude"
    / "worktrees"
    / "vibrant-meninsky-c9e255"
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "cfd_release_v0_true_airfoil_bay_gate"
    / "openfoam_cases"
    / "fullwing_debug"
    / "swept_cgrid"
)
OPENFOAM_WRAPPER = shutil.which("openfoam") or "/opt/homebrew/bin/openfoam"

VELOCITY_MPS = 6.5
AIR_DENSITY = 1.225
KINEMATIC_VISCOSITY = 1.4607e-5
AOA_DEG = 0.18
REF_AREA_M2 = 33.420059598
REF_LENGTH_M = 1.003721543
REF_ORIGIN_M = (0.246276512, 0.0, 0.0)
AUTHORITY_HALF_SPAN_M = 17.166143
AUTHORITY_FULL_SPAN_M = 34.332286
CASE_NAME = "true_baseline_swept_cgrid"
SOURCE_COMMIT = "35dfadb0"

SOLID_WALL_PRIORITY = (
    "airfoil_upper",
    "airfoil_lower",
    "wing_upper",
    "wing_lower",
    "te_wall",
    "tip_left",
    "tip_right",
    "closure_wall",
)
FLOW_PATCH_HINTS = ("farfield", "inlet", "outlet", "outer")
FIELD_NAMES = ("U", "p", "nut", "nuTilda")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source-case", type=Path, default=DEFAULT_SOURCE_CASE)
    parser.add_argument("--openfoam", default=OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--first-iterations", type=int, default=200)
    parser.add_argument("--final-iterations", type=int, default=500)
    args = parser.parse_args()

    manifest = run_route_smoke(
        output_dir=args.output_dir,
        source_case=args.source_case,
        openfoam_command=args.openfoam,
        clean=args.clean,
        setup_only=args.setup_only,
        timeout_seconds=args.timeout_seconds,
        first_iterations=args.first_iterations,
        final_iterations=args.final_iterations,
    )
    print(json.dumps(manifest["verdict"], indent=2, sort_keys=True))


def run_route_smoke(
    *,
    output_dir: Path,
    source_case: Path,
    openfoam_command: str,
    clean: bool,
    setup_only: bool,
    timeout_seconds: float,
    first_iterations: int,
    final_iterations: int,
) -> dict[str, Any]:
    start = time.monotonic()
    source_case = source_case.resolve()
    output_dir = output_dir.resolve()
    case_dir = output_dir / "openfoam_cases" / CASE_NAME
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    accepted_boundary = parse_boundary(source_case / "constant" / "polyMesh" / "boundary")
    patch_policy = classify_patches(accepted_boundary["patches"])
    case_setup = generate_case(
        case_dir=case_dir,
        source_case=source_case,
        patches=accepted_boundary["patches"],
        patch_policy=patch_policy,
        max_iterations=first_iterations,
        start_from="startTime",
    )
    patch_geometry = audit_patch_geometry(case_dir / "constant" / "polyMesh")
    write_patch_inventory(output_dir, source_case, accepted_boundary, patch_policy)
    write_bc_policy(output_dir, accepted_boundary, patch_policy)
    write_generated_case_report(output_dir, case_setup)
    write_forcecoeffs_setup_report(output_dir, case_setup)
    write_patch_geometry_extents(output_dir, patch_geometry)

    checkmesh: dict[str, Any] | None = None
    dry_run: dict[str, Any] | None = None
    first_run: dict[str, Any] | None = None
    final_run: dict[str, Any] | None = None
    yplus_post: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    validation = validate_case(case_dir, case_setup)

    if not setup_only:
        checkmesh = run_openfoam_command(
            case_dir,
            openfoam_command=openfoam_command,
            command="checkMesh -meshQuality",
            log_name="log.checkMesh",
            timeout_seconds=900.0,
        )
        validation = validate_case(case_dir, case_setup, checkmesh=checkmesh)
        if checkmesh["returncode"] == 0:
            dry_run = run_openfoam_command(
                case_dir,
                openfoam_command=openfoam_command,
                command="simpleFoam -dry-run",
                log_name="log.simpleFoam_dry_run",
                timeout_seconds=600.0,
            )
            if dry_run["returncode"] == 0:
                first_run = run_openfoam_command(
                    case_dir,
                    openfoam_command=openfoam_command,
                    command="simpleFoam",
                    log_name="log.simpleFoam_200",
                    timeout_seconds=timeout_seconds,
                )
                (case_dir / "log.simpleFoam").write_text(
                    (case_dir / "log.simpleFoam_200").read_text(
                        encoding="utf-8",
                        errors="replace",
                    ),
                    encoding="utf-8",
                )
                if first_run["returncode"] == 0 and solver_run_is_stable(case_dir / "log.simpleFoam_200"):
                    update_control_dict(
                        case_dir / "system" / "controlDict",
                        end_time=final_iterations,
                        start_from="latestTime",
                    )
                    final_run = run_openfoam_command(
                        case_dir,
                        openfoam_command=openfoam_command,
                        command="simpleFoam",
                        log_name="log.simpleFoam_500",
                        timeout_seconds=timeout_seconds,
                    )
                    (case_dir / "log.simpleFoam").write_text(
                        (case_dir / "log.simpleFoam_500").read_text(
                            encoding="utf-8",
                            errors="replace",
                        ),
                        encoding="utf-8",
                    )
                if (final_run or first_run)["returncode"] == 0:
                    yplus_post = run_openfoam_command(
                        case_dir,
                        openfoam_command=openfoam_command,
                        command="simpleFoam -postProcess -func yPlus -latestTime",
                        log_name="log.yPlus",
                        timeout_seconds=900.0,
                    )
            else:
                failure = classify_failure(case_dir / "log.simpleFoam_dry_run")
        else:
            failure = {
                "class": "mesh_quality_too_severe",
                "evidence": grep_lines(case_dir / "log.checkMesh", ("Failed", "FOAM FATAL", "Failed")),
            }
    else:
        validation = validate_case(case_dir, case_setup)

    coeffs = parse_force_coefficients(case_dir, case_setup["force_groups"])
    force_split = parse_force_splits(case_dir, case_setup["force_groups"])
    yplus = parse_yplus(case_dir, case_setup["solid_walls"])
    residuals = parse_residuals(case_dir / "log.simpleFoam")
    stability = force_stability(
        coeffs.get("functions", {}).get("primary", {}).get("rows", [])
    )
    if failure is None and first_run and first_run["returncode"] != 0:
        failure = classify_failure(case_dir / "log.simpleFoam_200")
    if failure is None and final_run and final_run["returncode"] != 0:
        failure = classify_failure(case_dir / "log.simpleFoam_500")

    verdict = build_verdict(
        validation=validation,
        checkmesh=checkmesh,
        dry_run=dry_run,
        first_run=first_run,
        final_run=final_run,
        yplus_post=yplus_post,
        coeffs=coeffs,
        force_split=force_split,
        yplus=yplus,
        residuals=residuals,
        stability=stability,
        patch_geometry=patch_geometry,
        failure=failure,
    )
    manifest = {
        "schema_version": "wo006_phase4_true_baseline_openfoam_route_smoke.v1",
        "created_at_utc": utc_now(),
        "output_dir": str(output_dir),
        "case_dir": str(case_dir),
        "source_case": str(source_case),
        "source_commit": SOURCE_COMMIT,
        "openfoam_command": openfoam_command,
        "accepted_patch_inventory": accepted_boundary,
        "case_setup": case_setup,
        "pre_solver_validation": validation,
        "commands": {
            "checkMesh": checkmesh,
            "simpleFoam_dry_run": dry_run,
            "simpleFoam_200": first_run,
            "simpleFoam_500": final_run,
            "postProcess_yPlus": yplus_post,
        },
        "coefficients": coeffs,
        "force_split": force_split,
        "yPlus": yplus,
        "residuals": residuals,
        "force_stability": stability,
        "patch_geometry_extents": patch_geometry,
        "failure": failure,
        "verdict": verdict,
        "elapsed_s": time.monotonic() - start,
    }
    write_json(output_dir / "route_smoke_manifest.json", manifest)
    write_pre_solver_validation_report(output_dir, validation, checkmesh)
    write_run_reports(output_dir, manifest)
    write_rerun(output_dir, source_case)
    return manifest


def generate_case(
    *,
    case_dir: Path,
    source_case: Path,
    patches: Mapping[str, Mapping[str, Any]],
    patch_policy: Mapping[str, Any],
    max_iterations: int,
    start_from: str,
) -> dict[str, Any]:
    if case_dir.exists():
        shutil.rmtree(case_dir)
    (case_dir / "constant").mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_case / "constant" / "polyMesh", case_dir / "constant" / "polyMesh")
    rewrite_boundary_patch_types(
        case_dir / "constant" / "polyMesh" / "boundary",
        patch_types={name: "wall" for name in patch_policy["solid_walls"]},
    )
    for path in (case_dir / "0", case_dir / "system"):
        path.mkdir(parents=True, exist_ok=True)
    solid_walls = tuple(patch_policy["solid_walls"])
    flow_boundaries = tuple(patch_policy["flow_boundaries"])
    diagnostic_patches = tuple(patch_policy["diagnostic_patches"])
    force_groups = build_force_groups(solid_walls, diagnostic_patches)
    flow_bc_policy = build_flow_bc_policy(flow_boundaries)

    (case_dir / "system" / "controlDict").write_text(
        control_dict_text(
            force_groups=force_groups,
            max_iterations=max_iterations,
            start_from=start_from,
        ),
        encoding="utf-8",
    )
    (case_dir / "system" / "fvSchemes").write_text(fv_schemes_text(), encoding="utf-8")
    (case_dir / "system" / "fvSolution").write_text(fv_solution_text(), encoding="utf-8")
    (case_dir / "system" / "meshQualityDict").write_text(mesh_quality_dict_text(), encoding="utf-8")
    (case_dir / "constant" / "transportProperties").write_text(
        transport_properties_text(),
        encoding="utf-8",
    )
    (case_dir / "constant" / "turbulenceProperties").write_text(
        turbulence_properties_text(),
        encoding="utf-8",
    )
    for field_name, text in {
        "U": u_field_text(solid_walls=solid_walls, flow_bc_policy=flow_bc_policy),
        "p": p_field_text(solid_walls=solid_walls, flow_bc_policy=flow_bc_policy),
        "nut": nut_field_text(solid_walls=solid_walls, flow_bc_policy=flow_bc_policy),
        "nuTilda": nu_tilda_field_text(
            solid_walls=solid_walls,
            flow_bc_policy=flow_bc_policy,
        ),
    }.items():
        (case_dir / "0" / field_name).write_text(text, encoding="utf-8")

    return {
        "case_dir": str(case_dir),
        "source_case": str(source_case),
        "mesh_topology_policy": "copied accepted polyMesh; no point/face/owner/neighbour topology edits",
        "boundary_patch_type_policy": {
            "changed_to_wall_for_wall_bc": sorted(solid_walls),
            "flow_boundaries_left_as_patch": sorted(flow_boundaries),
        },
        "solver": "simpleFoam",
        "turbulence_model": "SpalartAllmaras",
        "turbulence_dictionary": "constant/turbulenceProperties",
        "velocity_mps": VELOCITY_MPS,
        "aoa_deg": AOA_DEG,
        "aoa_source": (
            "accepted Phase 4 source case 0/U already encoded 0.18 deg "
            "via U=(6.49996787 0 0.0204373355)"
        ),
        "inlet_U": list(inlet_velocity(AOA_DEG)),
        "dragDir": list(drag_dir(AOA_DEG)),
        "liftDir": list(lift_dir(AOA_DEG)),
        "rho_kg_m3": AIR_DENSITY,
        "nu_m2_s": KINEMATIC_VISCOSITY,
        "ref_area_m2": REF_AREA_M2,
        "ref_length_m": REF_LENGTH_M,
        "ref_origin_m": list(REF_ORIGIN_M),
        "solid_walls": list(solid_walls),
        "flow_boundaries": list(flow_boundaries),
        "diagnostic_patches": list(diagnostic_patches),
        "force_groups": {key: list(value) for key, value in force_groups.items()},
        "flow_bc_policy": flow_bc_policy,
    }


def build_force_groups(
    solid_walls: Sequence[str],
    diagnostic_patches: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    if "airfoil_upper" in solid_walls and "airfoil_lower" in solid_walls:
        primary = ("airfoil_upper", "airfoil_lower")
    else:
        primary = tuple(patch for patch in ("wing_upper", "wing_lower") if patch in solid_walls)
    diagnostic = tuple(patch for patch in diagnostic_patches if patch in solid_walls)
    groups = {
        "primary": primary,
        "total": primary + diagnostic,
    }
    for patch in diagnostic:
        groups[patch] = (patch,)
    return {key: value for key, value in groups.items() if value}


def build_flow_bc_policy(flow_boundaries: Sequence[str]) -> dict[str, dict[str, str]]:
    policy: dict[str, dict[str, str]] = {}
    for name in flow_boundaries:
        lowered = name.lower()
        if "outlet" in lowered:
            policy[name] = {
                "U": "inletOutlet",
                "p": "fixedValue",
                "nut": "calculated",
                "nuTilda": "inletOutlet",
            }
        else:
            policy[name] = {
                "U": "freestreamVelocity",
                "p": "freestreamPressure",
                "nut": "calculated",
                "nuTilda": "freestream",
            }
    return policy


def classify_patches(patches: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    patch_names = set(patches)
    solid_walls = [name for name in SOLID_WALL_PRIORITY if name in patch_names]
    flow_boundaries = [
        name
        for name in patches
        if any(hint in name.lower() for hint in FLOW_PATCH_HINTS)
    ]
    diagnostic = [
        name
        for name in ("tip_left", "tip_right", "te_wall", "closure_wall")
        if name in patch_names
    ]
    return {
        "solid_walls": solid_walls,
        "flow_boundaries": flow_boundaries,
        "diagnostic_patches": diagnostic,
        "primary_patch_naming": "airfoil_upper/airfoil_lower"
        if {"airfoil_upper", "airfoil_lower"} <= patch_names
        else "wing_upper/wing_lower"
        if {"wing_upper", "wing_lower"} <= patch_names
        else "unknown",
        "has_outlet": "outlet" in patch_names,
        "has_inlet": any("inlet" in name.lower() for name in patch_names),
        "has_farfield": "farfield" in patch_names,
    }


def parse_boundary(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    patches: dict[str, dict[str, Any]] = {}
    pattern = re.compile(
        r"^\s*([A-Za-z0-9_]+)\s*\n\s*\{(?P<body>.*?)^\s*\}",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        body = match.group("body")
        name = match.group(1)
        n_faces = int_match(body, r"\bnFaces\s+([0-9]+)")
        start_face = int_match(body, r"\bstartFace\s+([0-9]+)")
        if n_faces is None or start_face is None:
            continue
        patches[name] = {
            "type": str_match(body, r"\btype\s+([A-Za-z0-9_]+)"),
            "nFaces": n_faces,
            "startFace": start_face,
        }
    return {"status": "available", "path": str(path), "patches": patches}


def audit_patch_geometry(poly_mesh_dir: Path) -> dict[str, Any]:
    boundary = parse_boundary(poly_mesh_dir / "boundary")
    points = parse_points(poly_mesh_dir / "points")
    faces = parse_faces(poly_mesh_dir / "faces")
    patches: dict[str, dict[str, Any]] = {}
    domain = empty_extent()
    for point in points:
        update_extent(domain, point)
    for name, patch in boundary["patches"].items():
        extent = empty_extent()
        start = int(patch["startFace"])
        stop = start + int(patch["nFaces"])
        for face in faces[start:stop]:
            for point_index in face:
                update_extent(extent, points[point_index])
        patches[name] = {
            "type": patch.get("type"),
            "nFaces": patch.get("nFaces"),
            "startFace": patch.get("startFace"),
            "extent": finalize_extent(extent),
        }
    domain_extent = finalize_extent(domain)
    y_min = domain_extent["y"]["min"]
    y_max = domain_extent["y"]["max"]
    y_span = None if y_min is None or y_max is None else y_max - y_min
    note = (
        "tip_left is exactly y=0 plane while tip_right is y=17.166143 plane; "
        "this looks like a half-span/root-symmetry domain, not a +/- full-span wing."
    )
    if y_span is not None and abs(y_span - AUTHORITY_FULL_SPAN_M) < 1e-4:
        note = "domain y span matches current full-span authority."
    return {
        "status": "available",
        "domain_extent": domain_extent,
        "domain_y_span_m": y_span,
        "authority_half_span_m": AUTHORITY_HALF_SPAN_M,
        "authority_full_span_m": AUTHORITY_FULL_SPAN_M,
        "engineering_note": note,
        "patches": patches,
    }


def parse_points(path: Path) -> list[tuple[float, float, float]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    points: list[tuple[float, float, float]] = []
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    pattern = re.compile(rf"\(\s*({number})\s+({number})\s+({number})\s*\)")
    for match in pattern.finditer(text):
        points.append((float(match.group(1)), float(match.group(2)), float(match.group(3))))
    if not points:
        raise RuntimeError(f"no OpenFOAM points parsed from {path}")
    return points


def parse_faces(path: Path) -> list[tuple[int, ...]]:
    faces: list[tuple[int, ...]] = []
    in_list = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not in_list:
                if stripped == "(":
                    in_list = True
                continue
            if stripped == ")":
                break
            match = re.match(r"\d+\(([^)]*)\)", stripped)
            if match:
                faces.append(tuple(int(token) for token in match.group(1).split()))
    if not faces:
        raise RuntimeError(f"no OpenFOAM faces parsed from {path}")
    return faces


def empty_extent() -> dict[str, list[float | None]]:
    return {
        "x": [None, None],
        "y": [None, None],
        "z": [None, None],
    }


def update_extent(extent: dict[str, list[float | None]], point: tuple[float, float, float]) -> None:
    for axis, value in zip(("x", "y", "z"), point):
        current = extent[axis]
        current[0] = value if current[0] is None else min(float(current[0]), value)
        current[1] = value if current[1] is None else max(float(current[1]), value)


def finalize_extent(extent: Mapping[str, Sequence[float | None]]) -> dict[str, dict[str, float | None]]:
    return {
        axis: {"min": values[0], "max": values[1]}
        for axis, values in extent.items()
    }


def rewrite_boundary_patch_types(path: Path, *, patch_types: Mapping[str, str]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for patch, patch_type in patch_types.items():
        pattern = re.compile(
            rf"(^\s*{re.escape(patch)}\s*\n\s*\{{.*?^\s*type\s+)([A-Za-z0-9_]+)(\s*;)",
            re.MULTILINE | re.DOTALL,
        )
        text, count = pattern.subn(rf"\g<1>{patch_type}\g<3>", text, count=1)
        if count != 1:
            raise RuntimeError(f"could not update boundary patch type for {patch}")
    path.write_text(text, encoding="utf-8")


def update_control_dict(path: Path, *, end_time: int, start_from: str) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\bstartFrom\s+\w+\s*;", f"startFrom       {start_from};", text)
    text = re.sub(r"\bendTime\s+[0-9.eE+-]+\s*;", f"endTime         {int(end_time)};", text)
    path.write_text(text, encoding="utf-8")


def control_dict_text(
    *,
    force_groups: Mapping[str, Sequence[str]],
    max_iterations: int,
    start_from: str,
) -> str:
    force_objects = "\n".join(
        force_coeff_function_text(name=f"forceCoeffs_{name}", patches=patches)
        + "\n"
        + forces_function_text(name=f"forces_{name}", patches=patches)
        for name, patches in force_groups.items()
    )
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}
application     simpleFoam;
startFrom       {start_from};
startTime       0;
stopAt          endTime;
endTime         {int(max_iterations)};
deltaT          1;
writeControl    timeStep;
writeInterval   100;
purgeWrite      2;
functions
{{
{force_objects}
    yPlus
    {{
        type            yPlus;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeInterval   100;
    }}
}}
"""


def force_coeff_function_text(*, name: str, patches: Sequence[str]) -> str:
    patch_list = " ".join(patches)
    lift = lift_dir(AOA_DEG)
    drag = drag_dir(AOA_DEG)
    return f"""    {name}
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        patches         ({patch_list});
        rho             rhoInf;
        rhoInf          {AIR_DENSITY:.9g};
        liftDir         ({lift[0]:.9g} {lift[1]:.9g} {lift[2]:.9g});
        dragDir         ({drag[0]:.9g} {drag[1]:.9g} {drag[2]:.9g});
        CofR            ({REF_ORIGIN_M[0]:.9f} {REF_ORIGIN_M[1]:.9f} {REF_ORIGIN_M[2]:.9f});
        pitchAxis       (0 1 0);
        magUInf         {VELOCITY_MPS:.9g};
        lRef            {REF_LENGTH_M:.9f};
        Aref            {REF_AREA_M2:.9f};
        writeControl    timeStep;
        writeInterval   1;
        log             true;
    }}
"""


def forces_function_text(*, name: str, patches: Sequence[str]) -> str:
    patch_list = " ".join(patches)
    return f"""    {name}
    {{
        type            forces;
        libs            ("libforces.so");
        patches         ({patch_list});
        rho             rhoInf;
        rhoInf          {AIR_DENSITY:.9g};
        CofR            ({REF_ORIGIN_M[0]:.9f} {REF_ORIGIN_M[1]:.9f} {REF_ORIGIN_M[2]:.9f});
        writeControl    timeStep;
        writeInterval   1;
        log             true;
    }}
"""


def fv_schemes_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}
ddtSchemes
{
    default         steadyState;
}
gradSchemes
{
    default         Gauss linear;
}
divSchemes
{
    default                         none;
    div(phi,U)                      bounded Gauss linearUpwind grad(U);
    div(phi,nuTilda)                bounded Gauss linearUpwind grad(nuTilda);
    div((nuEff*dev2(T(grad(U)))))   Gauss linear;
}
laplacianSchemes
{
    default         Gauss linear corrected;
}
interpolationSchemes
{
    default         linear;
}
snGradSchemes
{
    default         corrected;
}
wallDist
{
    method          meshWave;
}
"""


def fv_solution_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}
solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-06;
        relTol          0.1;
        smoother        GaussSeidel;
    }
    U
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0.1;
    }
    nuTilda
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0.1;
    }
}
SIMPLE
{
    nNonOrthogonalCorrectors 2;
    residualControl
    {
        p               1e-5;
        U               1e-5;
        nuTilda         1e-5;
    }
}
relaxationFactors
{
    fields
    {
        p               0.25;
    }
    equations
    {
        U               0.55;
        nuTilda         0.55;
    }
}
"""


def mesh_quality_dict_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      meshQualityDict;
}
#includeEtc "caseDicts/meshQualityDict"
maxNonOrtho     90;
maxBoundarySkewness 20;
maxInternalSkewness 4;
maxConcave      80;
minFlatness     0.5;
minVol          1e-18;
minTetQuality   -1e30;
minArea         -1;
minTwist        0;
minDeterminant  1e-08;
minFaceWeight   0.02;
minVolRatio     0.01;
minTriangleTwist -1;
nSmoothScale    4;
errorReduction  0.75;
"""


def transport_properties_text() -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      transportProperties;
}}
transportModel  Newtonian;
nu              {KINEMATIC_VISCOSITY:.9g};
"""


def turbulence_properties_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}
simulationType          RAS;
RAS
{
    RASModel            SpalartAllmaras;
    turbulence          on;
    printCoeffs         on;
}
"""


def u_field_text(
    *,
    solid_walls: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    u = inlet_velocity(AOA_DEG)
    return field_header("volVectorField", "U", "[0 1 -1 0 0 0 0]", f"uniform {vec(u)}") + "\n".join(
        flow_u_entry(name, policy["U"], u)
        for name, policy in flow_bc_policy.items()
    ) + "\n" + "\n".join(no_slip_entry(name) for name in solid_walls) + "\n}\n"


def p_field_text(
    *,
    solid_walls: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    return field_header("volScalarField", "p", "[0 2 -2 0 0 0 0]", "uniform 0") + "\n".join(
        flow_p_entry(name, policy["p"])
        for name, policy in flow_bc_policy.items()
    ) + "\n" + "\n".join(zero_gradient_entry(name) for name in solid_walls) + "\n}\n"


def nu_tilda_field_text(
    *,
    solid_walls: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    return field_header("volScalarField", "nuTilda", "[0 2 -1 0 0 0 0]", "uniform 4.0e-5") + "\n".join(
        flow_nu_tilda_entry(name, policy["nuTilda"])
        for name, policy in flow_bc_policy.items()
    ) + "\n" + "\n".join(fixed_value_scalar_entry(name, "0") for name in solid_walls) + "\n}\n"


def nut_field_text(
    *,
    solid_walls: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    return field_header("volScalarField", "nut", "[0 2 -1 0 0 0 0]", "uniform 0") + "\n".join(
        calculated_scalar_entry(name)
        for name in flow_bc_policy
    ) + "\n" + "\n".join(nut_wall_entry(name) for name in solid_walls) + "\n}\n"


def field_header(field_class: str, obj: str, dimensions: str, internal_field: str) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       {field_class};
    object      {obj};
}}
dimensions      {dimensions};
internalField   {internal_field};
boundaryField
{{
"""


def flow_u_entry(name: str, bc_type: str, u: tuple[float, float, float]) -> str:
    if bc_type == "inletOutlet":
        return f"""    {name}
    {{
        type            inletOutlet;
        inletValue      uniform {vec(u)};
        value           uniform {vec(u)};
    }}"""
    return f"""    {name}
    {{
        type            freestreamVelocity;
        freestreamValue uniform {vec(u)};
        value           uniform {vec(u)};
    }}"""


def flow_p_entry(name: str, bc_type: str) -> str:
    if bc_type == "fixedValue":
        return f"""    {name}
    {{
        type            fixedValue;
        value           uniform 0;
    }}"""
    return f"""    {name}
    {{
        type            freestreamPressure;
        freestreamValue uniform 0;
        value           uniform 0;
    }}"""


def flow_nu_tilda_entry(name: str, bc_type: str) -> str:
    if bc_type == "inletOutlet":
        return f"""    {name}
    {{
        type            inletOutlet;
        inletValue      uniform 4.0e-5;
        value           uniform 4.0e-5;
    }}"""
    return f"""    {name}
    {{
        type            freestream;
        freestreamValue uniform 4.0e-5;
        value           uniform 4.0e-5;
    }}"""


def no_slip_entry(name: str) -> str:
    return f"""    {name}
    {{
        type            noSlip;
    }}"""


def zero_gradient_entry(name: str) -> str:
    return f"""    {name}
    {{
        type            zeroGradient;
    }}"""


def fixed_value_scalar_entry(name: str, value: str) -> str:
    return f"""    {name}
    {{
        type            fixedValue;
        value           uniform {value};
    }}"""


def calculated_scalar_entry(name: str) -> str:
    return f"""    {name}
    {{
        type            calculated;
        value           uniform 0;
    }}"""


def nut_wall_entry(name: str) -> str:
    return f"""    {name}
    {{
        type            nutUSpaldingWallFunction;
        value           uniform 0;
    }}"""


def run_openfoam_command(
    case_dir: Path,
    *,
    openfoam_command: str,
    command: str,
    log_name: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    safe_root = Path("/tmp/hpa_mdo_true_baseline_openfoam")
    run_dir = safe_root / case_dir.name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    safe_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(case_dir, run_dir)
    log_path = run_dir / log_name
    wrapped = f"cd {shlex.quote(str(run_dir))} && {command}"
    started = time.monotonic()
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log:
        try:
            completed = subprocess.run(
                ["/usr/bin/time", "-l", openfoam_command, "-c", wrapped],
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = 124
            log.write(f"\nTIMEOUT after {timeout_seconds:.1f} seconds\n")
    normalize_logs(run_dir)
    shutil.copytree(run_dir, case_dir, dirs_exist_ok=True)
    return {
        "command": command,
        "log": str(case_dir / log_name),
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_s": time.monotonic() - started,
        "resource_usage": parse_time_l_log(case_dir / log_name),
        "tail": tail(case_dir / log_name, 80),
    }


def normalize_logs(case_dir: Path) -> None:
    for path in case_dir.glob("log.*"):
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = [line.rstrip() for line in text.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_case(
    case_dir: Path,
    case_setup: Mapping[str, Any],
    checkmesh: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    boundary = parse_boundary(case_dir / "constant" / "polyMesh" / "boundary")
    patches = boundary["patches"]
    field_entries = {
        field: parse_field_patch_entries(case_dir / "0" / field)
        for field in FIELD_NAMES
    }
    missing_by_field = {
        field: sorted(set(patches) - set(entries))
        for field, entries in field_entries.items()
    }
    force_patch_missing = {
        name: sorted(set(group) - set(patches))
        for name, group in case_setup["force_groups"].items()
        if set(group) - set(patches)
    }
    wall_type_errors = {
        patch: patches.get(patch, {}).get("type")
        for patch in case_setup["solid_walls"]
        if patches.get(patch, {}).get("type") != "wall"
    }
    tip_bc_errors = {
        field: entries.get("tip_left", {}).get("type")
        for field, entries in field_entries.items()
        if "tip_left" in patches and field == "U" and entries.get("tip_left", {}).get("type") != "noSlip"
    }
    if "tip_right" in patches:
        tip_type = field_entries["U"].get("tip_right", {}).get("type")
        if tip_type != "noSlip":
            tip_bc_errors["U_tip_right"] = tip_type
    outlet_entries = {
        field: field_entries[field].get("outlet")
        for field in FIELD_NAMES
        if "outlet" in patches
    }
    checks = {
        "all_fields_cover_all_patches": all(not missing for missing in missing_by_field.values()),
        "force_patch_names_exist": not force_patch_missing,
        "wall_patches_have_wall_boundary_class": not wall_type_errors,
        "tips_are_noslip_walls": not tip_bc_errors,
        "outlet_has_required_field_entries": bool(outlet_entries) and all(outlet_entries.values())
        if "outlet" in patches
        else True,
        "farfield_has_required_field_entries": all(
            field_entries[field].get("farfield") for field in FIELD_NAMES
        )
        if "farfield" in patches
        else False,
    }
    if checkmesh is not None:
        checks["checkMesh_returncode_zero"] = checkmesh.get("returncode") == 0
        checks["checkMesh_finished"] = "End" in "\n".join(checkmesh.get("tail", []))
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "boundary": boundary,
        "field_entries": field_entries,
        "missing_by_field": missing_by_field,
        "force_patch_missing": force_patch_missing,
        "wall_type_errors": wall_type_errors,
        "tip_bc_errors": tip_bc_errors,
        "outlet_entries": outlet_entries,
        "checkmesh": checkmesh,
    }


def parse_field_patch_entries(path: Path) -> dict[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    boundary_text = text.split("boundaryField", 1)[-1]
    entries: dict[str, dict[str, Any]] = {}
    for match in re.finditer(
        r"^\s*([A-Za-z0-9_]+)\s*\n\s*\{(?P<body>.*?)^\s*\}",
        boundary_text,
        re.MULTILINE | re.DOTALL,
    ):
        body = match.group("body")
        entries[match.group(1)] = {
            "type": str_match(body, r"\btype\s+([A-Za-z0-9_]+)"),
            "body": "\n".join(line.strip() for line in body.splitlines() if line.strip()),
        }
    return entries


def solver_run_is_stable(log_path: Path) -> bool:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    fatal = (
        "FOAM FATAL" in text
        or "Floating point exception" in text
        or "Divergence detected" in text
        or re.search(r"\b[nN][aA][nN]\b", text) is not None
    )
    return not fatal and "End" in text.splitlines()[-60:]


def classify_failure(log_path: Path) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    lower = text.lower()
    if "cannot find patchfield entry" in lower or "cannot find patch" in lower:
        kind = "missing_bc_entry"
    elif "unknown patchfield type" in lower or "not a wall" in lower or "wall function" in lower:
        kind = "incompatible_patch_type"
    elif "nut" in lower or "nutilda" in lower or "rasmodel" in lower or "spalart" in lower:
        kind = "turbulence_variable_issue"
    elif "forcecoeffs" in lower or "forces" in lower:
        kind = "forceCoeffs_patch_mismatch"
    elif "floating point exception" in lower or "diverg" in lower or "nan" in lower:
        kind = "numerical_divergence"
    else:
        kind = "unknown_solver_setup_failure"
    return {
        "class": kind,
        "log": str(log_path),
        "evidence": grep_lines(log_path, ("FOAM FATAL", "Cannot find", "Unknown", "not a wall", "Divergence", "nan", "Floating"), limit=60),
        "tail": tail(log_path, 80),
    }


def parse_check_mesh_metrics(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {"status": "missing"}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return {
        "status": "pass"
        if "Failed 0 mesh checks" in text or "Mesh OK" in text
        else "completed_with_inherited_quality_flags"
        if "End" in text and "Failed" in text
        else "unknown",
        "cells": int_match(text, r"cells:\s*([0-9]+)"),
        "maxNonOrtho": float_match(text, r"Mesh non-orthogonality Max:\s*([-+0-9.eE]+)"),
        "maxSkew": float_match(text, r"Max skewness =\s*([-+0-9.eE]+)"),
        "negativeVolumeCells": int_match(text, r"Number of cells with negative volume:\s*([0-9]+)"),
        "openCells": int_match(text, r"Number of regions:\s*[0-9]+[\s\S]*?Number of open cells:\s*([0-9]+)"),
        "failedChecks": int_match(text, r"Failed\s+([0-9]+)\s+mesh checks"),
        "error_lines": grep_lines(log_path, ("Failed", "***Max", "negative volume", "open cells", "pyramids"), limit=80),
    }


def parse_force_coefficients(
    case_dir: Path,
    force_groups: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    functions: dict[str, Any] = {}
    for group in force_groups:
        rows = read_coeff_rows(case_dir / "postProcessing" / f"forceCoeffs_{group}")
        functions[group] = {
            "status": "available" if rows else "missing",
            "row_count": len(rows),
            "last": rows[-1] if rows else None,
            "rows": rows,
        }
    summary: dict[str, float | None] = {
        "CD_primary": last_coeff(functions, "primary", "Cd"),
        "CL_primary": last_coeff(functions, "primary", "Cl"),
        "CD_total": last_coeff(functions, "total", "Cd"),
        "CL_total": last_coeff(functions, "total", "Cl"),
    }
    for group in force_groups:
        if group not in {"primary", "total"}:
            summary[f"CD_{group}"] = last_coeff(functions, group, "Cd")
    diagnostic_values = [
        value
        for key, value in summary.items()
        if key.startswith("CD_") and key not in {"CD_primary", "CD_total"} and value is not None
    ]
    summary["CD_diagnostic_sum"] = sum(diagnostic_values) if diagnostic_values else None
    return {"functions": functions, "summary": summary}


def read_coeff_rows(root: Path) -> list[dict[str, float]]:
    files = sorted(root.glob("*/coefficient*.dat"))
    if not files:
        return []
    headers: list[str] = []
    rows: list[dict[str, float]] = []
    for line in files[-1].read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            tokens = stripped.lstrip("#").split()
            if tokens and tokens[0] == "Time":
                headers = tokens
            continue
        values = [float_or_none(token) for token in stripped.split()]
        if not values or any(value is None for value in values):
            continue
        if not headers:
            headers = ["Time", "Cm", "Cd", "Cl", "Cl(f)", "Cl(r)"][: len(values)]
        rows.append(
            {
                header: float(value)
                for header, value in zip(headers, values, strict=False)
                if value is not None
            }
        )
    return rows


def parse_force_splits(
    case_dir: Path,
    force_groups: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    q_area = 0.5 * AIR_DENSITY * VELOCITY_MPS * VELOCITY_MPS * REF_AREA_M2
    drag = drag_dir(AOA_DEG)
    lift = lift_dir(AOA_DEG)
    out: dict[str, Any] = {}
    for group in force_groups:
        rows = read_forces_rows(case_dir / "postProcessing" / f"forces_{group}")
        last = rows[-1] if rows else None
        split = None
        if last:
            split = {
                "CD_pressure": dot(last["force_pressure"], drag) / q_area,
                "CD_viscous": dot(last["force_viscous"], drag) / q_area,
                "CD_porous": dot(last["force_porous"], drag) / q_area,
                "CL_pressure": dot(last["force_pressure"], lift) / q_area,
                "CL_viscous": dot(last["force_viscous"], lift) / q_area,
                "CL_porous": dot(last["force_porous"], lift) / q_area,
            }
            split["CD_pressure_plus_viscous"] = split["CD_pressure"] + split["CD_viscous"]
            split["CL_pressure_plus_viscous"] = split["CL_pressure"] + split["CL_viscous"]
        out[group] = {
            "status": "available" if rows else "missing",
            "row_count": len(rows),
            "last": last,
            "split_coefficients": split,
        }
    return {
        "source": "OpenFOAM forces function object; forceCoeffs Cd(f)/Cd(r) are not used as pressure/viscous split.",
        "groups": out,
    }


def read_forces_rows(root: Path) -> list[dict[str, Any]]:
    files = sorted(root.glob("*/force.dat"))
    if not files:
        return []
    rows: list[dict[str, Any]] = []
    for line in files[-1].read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        time_match = re.match(r"([-+0-9.eE]+)\s+", stripped)
        if not time_match:
            continue
        values = [float_or_none(token) for token in stripped.split()]
        if any(value is None for value in values) or len(values) < 10:
            continue
        raw = [float(value) for value in values]
        rows.append(
            {
                "Time": raw[0],
                "force_total": (raw[1], raw[2], raw[3]),
                "force_pressure": (raw[4], raw[5], raw[6]),
                "force_viscous": (raw[7], raw[8], raw[9]),
                "force_porous": (0.0, 0.0, 0.0),
            }
        )
    return rows


def parse_yplus(case_dir: Path, wall_patches: Sequence[str]) -> dict[str, Any]:
    yplus_files = sorted(path for path in case_dir.glob("[0-9]*/yPlus") if path.is_file())
    dat_rows = []
    for path in sorted((case_dir / "postProcessing" / "yPlus").glob("*/*.dat")):
        dat_rows.extend(read_yplus_dat_rows(path))
    if not yplus_files and not dat_rows:
        return {"status": "missing", "patches": {}, "source": None}
    patch_stats = parse_yplus_field(yplus_files[-1], wall_patches) if yplus_files else {}
    if not patch_stats and dat_rows:
        latest_time = max(row["time"] for row in dat_rows)
        patch_stats = {
            row["patch"]: {
                "min": row["min"],
                "mean": row["mean"],
                "max": row["max"],
                "p90": None,
                "p95": None,
                "p99": None,
                "count": None,
            }
            for row in dat_rows
            if row["time"] == latest_time
        }
    primary_values = [
        value
        for patch in ("airfoil_upper", "airfoil_lower", "wing_upper", "wing_lower")
        for value in patch_stats.get(patch, {}).get("values", [])
    ]
    primary_summary = stats_from_values(primary_values)
    for data in patch_stats.values():
        data.pop("values", None)
    return {
        "status": "available",
        "source": str(yplus_files[-1]) if yplus_files else "postProcessing/yPlus/*.dat",
        "patches": patch_stats,
        "primary_main_wall_summary": primary_summary,
    }


def parse_yplus_field(path: Path, wall_patches: Sequence[str]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, Any] = {}
    for patch in wall_patches:
        match = re.search(
            rf"^\s*{re.escape(patch)}\s*\n\s*\{{(?P<body>.*?)^\s*\}}",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if not match:
            continue
        body = match.group("body")
        values_match = re.search(
            r"value\s+nonuniform\s+List<scalar>\s+([0-9]+)\s*\((?P<values>.*?)\)\s*;",
            body,
            re.DOTALL,
        )
        if not values_match:
            uniform = float_match(body, r"value\s+uniform\s+([-+0-9.eE]+)")
            values = [uniform] if uniform is not None else []
        else:
            values = [
                float(token)
                for token in values_match.group("values").split()
                if float_or_none(token) is not None
            ]
        out[patch] = stats_from_values(values)
        out[patch]["values"] = values
    return out


def read_yplus_dat_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = stripped.split()
        if len(tokens) < 5:
            continue
        values = [float_or_none(token) for token in (tokens[0], tokens[2], tokens[3], tokens[4])]
        if any(value is None for value in values):
            continue
        rows.append(
            {
                "time": float(values[0]),
                "patch": tokens[1],
                "min": float(values[1]),
                "max": float(values[2]),
                "mean": float(values[3]),
            }
        )
    return rows


def stats_from_values(values: Sequence[float]) -> dict[str, Any]:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
        }
    return {
        "count": len(finite),
        "min": finite[0],
        "mean": sum(finite) / len(finite),
        "p90": quantile_sorted(finite, 0.90),
        "p95": quantile_sorted(finite, 0.95),
        "p99": quantile_sorted(finite, 0.99),
        "max": finite[-1],
    }


def quantile_sorted(values: Sequence[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    pos = q * (len(values) - 1)
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return values[lower]
    frac = pos - lower
    return values[lower] * (1.0 - frac) + values[upper] * frac


def parse_residuals(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "fields": {}}
    fields: dict[str, list[dict[str, float]]] = {}
    pattern = re.compile(
        r"Solving for ([A-Za-z0-9_]+), Initial residual = ([-+0-9.eE]+), Final residual = ([-+0-9.eE]+), No Iterations ([0-9]+)"
    )
    time_value = 0.0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Time ="):
            value = float_or_none(line.split("=", 1)[1].strip())
            if value is not None:
                time_value = value
        match = pattern.search(line)
        if not match:
            continue
        field = match.group(1)
        fields.setdefault(field, []).append(
            {
                "Time": time_value,
                "initial": float(match.group(2)),
                "final": float(match.group(3)),
                "iterations": float(match.group(4)),
            }
        )
    summary = {}
    for field, rows in fields.items():
        summary[field] = {
            "count": len(rows),
            "first_initial": rows[0]["initial"],
            "last_initial": rows[-1]["initial"],
            "first_final": rows[0]["final"],
            "last_final": rows[-1]["final"],
            "max_initial": max(row["initial"] for row in rows),
            "min_final": min(row["final"] for row in rows),
        }
    return {"status": "available" if fields else "missing", "fields": summary}


def force_stability(rows: Sequence[Mapping[str, float]], window: int = 50) -> dict[str, Any]:
    if not rows:
        return {"status": "missing"}
    tail_rows = list(rows[-window:])
    out: dict[str, Any] = {"window": len(tail_rows)}
    for key in ("Cd", "Cl", "Cs", "CmPitch"):
        values = [float(row[key]) for row in tail_rows if key in row]
        if not values:
            continue
        mean = sum(values) / len(values)
        span = max(values) - min(values)
        out[key] = {
            "last": values[-1],
            "mean": mean,
            "min": min(values),
            "max": max(values),
            "span": span,
            "relative_span": abs(span / mean) if mean else None,
        }
    cd_rel = out.get("Cd", {}).get("relative_span")
    cl_rel = out.get("Cl", {}).get("relative_span")
    out["status"] = "available"
    out["route_smoke_stable"] = (
        cd_rel is not None
        and cl_rel is not None
        and cd_rel < 0.05
        and cl_rel < 0.05
    )
    return out


def build_verdict(
    *,
    validation: Mapping[str, Any],
    checkmesh: Mapping[str, Any] | None,
    dry_run: Mapping[str, Any] | None,
    first_run: Mapping[str, Any] | None,
    final_run: Mapping[str, Any] | None,
    yplus_post: Mapping[str, Any] | None,
    coeffs: Mapping[str, Any],
    force_split: Mapping[str, Any],
    yplus: Mapping[str, Any],
    residuals: Mapping[str, Any],
    stability: Mapping[str, Any],
    patch_geometry: Mapping[str, Any],
    failure: Mapping[str, Any] | None,
) -> dict[str, Any]:
    simplefoam_ran = bool((final_run or first_run) and (final_run or first_run).get("returncode") == 0)
    y_summary = yplus.get("primary_main_wall_summary", {})
    patch_note = patch_geometry.get("engineering_note")
    return {
        "status": "route_smoke_pass" if simplefoam_ran and failure is None else "blocked",
        "bc_reconciliation_complete": validation.get("status") == "pass",
        "every_patch_has_valid_bcs": validation.get("checks", {}).get("all_fields_cover_all_patches") is True,
        "checkMesh_passed": checkmesh is not None and checkmesh.get("returncode") == 0,
        "simpleFoam_ran": simplefoam_ran,
        "dry_run_passed": dry_run is not None and dry_run.get("returncode") == 0,
        "yPlus_postprocess_passed": yplus_post is not None and yplus_post.get("returncode") == 0,
        "coefficients": coeffs.get("summary", {}),
        "yPlus_primary_mean_p95_max": {
            "mean": y_summary.get("mean"),
            "p95": y_summary.get("p95"),
            "max": y_summary.get("max"),
        },
        "force_window_stability": stability,
        "residuals": residuals,
        "pressure_viscous_split_available": any(
            group.get("status") == "available"
            for group in force_split.get("groups", {}).values()
        ),
        "trust_boundary": (
            "OpenFOAM route-smoke only. Passing checkMesh and simpleFoam here "
            "does not establish grid-converged, wall-resolved, or release-grade drag."
        ),
        "yplus_classification": classify_yplus(
            y_summary,
            yplus.get("patches", {}) if isinstance(yplus.get("patches"), Mapping) else {},
        ),
        "xfoil_comparable": False,
        "xfoil_comparison_note": (
            "Not comparable to XFOIL CD≈0.02602 yet; this is a first 3D route-smoke "
            "on a high-nonorthogonal structured mesh and needs patch-role/domain, "
            "farfield, mesh, and yPlus sensitivity."
        ),
        "patch_geometry_engineering_note": patch_note,
        "failure": failure,
    }


def classify_yplus(
    summary: Mapping[str, Any],
    patch_summaries: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    mean = summary.get("mean")
    p95 = summary.get("p95")
    max_value = summary.get("max")
    if mean is None or p95 is None or max_value is None:
        return "failed"
    non_primary_high = False
    for patch, data in (patch_summaries or {}).items():
        if patch in {"airfoil_upper", "airfoil_lower", "wing_upper", "wing_lower"}:
            continue
        patch_max = data.get("max")
        if isinstance(patch_max, (int, float)) and float(patch_max) > 300.0:
            non_primary_high = True
    if mean < 5 and p95 < 10:
        if non_primary_high:
            return "main_wall_resolved_like_but_tip_high_yplus_not_validated"
        return "wall_resolved_like_yplus_not_validated"
    if 30 <= mean <= 300 and p95 < 1000:
        return "high_yplus_wall_function_smoke"
    return "high_yplus_or_mixed_near_wall_smoke"


def write_patch_inventory(
    output_dir: Path,
    source_case: Path,
    boundary: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    inventory = {
        "source_case": str(source_case),
        "source_commit": SOURCE_COMMIT,
        "patches": boundary["patches"],
        "solid_walls": policy["solid_walls"],
        "flow_boundaries": policy["flow_boundaries"],
        "diagnostic_only": policy["diagnostic_patches"],
        "primary_patch_naming": policy["primary_patch_naming"],
        "farfield_exists": policy["has_farfield"],
        "inlet_exists": policy["has_inlet"],
        "outlet_exists": policy["has_outlet"],
        "exact_farfield_names": [name for name in boundary["patches"] if "farfield" in name.lower()],
        "exact_inlet_names": [name for name in boundary["patches"] if "inlet" in name.lower()],
        "exact_outlet_names": [name for name in boundary["patches"] if "outlet" in name.lower()],
    }
    write_json(output_dir / "openfoam_patch_inventory.json", inventory)
    lines = ["# OpenFOAM Patch Inventory", ""]
    lines.append(f"- source case: `{source_case}`")
    lines.append(f"- source commit: `{SOURCE_COMMIT}`")
    lines.append(f"- primary surface names: `{policy['primary_patch_naming']}`")
    lines.append(f"- farfield patches: `{inventory['exact_farfield_names']}`")
    lines.append(f"- inlet patches: `{inventory['exact_inlet_names']}`")
    lines.append(f"- outlet patches: `{inventory['exact_outlet_names']}`")
    lines.append("")
    lines.append("| patch | boundary type in accepted mesh | nFaces | role |")
    lines.append("|---|---:|---:|---|")
    for name, data in boundary["patches"].items():
        role = "solid wall" if name in policy["solid_walls"] else "flow boundary" if name in policy["flow_boundaries"] else "diagnostic-only"
        if name in policy["diagnostic_patches"]:
            role = "solid wall / diagnostic force patch"
        lines.append(f"| `{name}` | `{data.get('type')}` | {data.get('nFaces')} | {role} |")
    lines.append("")
    lines.append(
        "Note: `tip_left` and `tip_right` are reported with their accepted mesh boundary type, "
        "then converted to OpenFOAM `wall` class in the generated solver case without changing face topology."
    )
    (output_dir / "openfoam_patch_inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_bc_policy(
    output_dir: Path,
    boundary: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    lines = ["# OpenFOAM Boundary-Condition Policy", ""]
    lines.append("- solver: `simpleFoam`")
    lines.append("- turbulence model: `SpalartAllmaras`")
    lines.append("- AoA: `0.18 deg`; U/dragDir/liftDir rotated consistently")
    lines.append("- tips: `tip_left` and `tip_right` are physical full-wing tips, so they are noSlip walls, not symmetry planes")
    lines.append("")
    lines.append("| patch | role | U | p | nut | nuTilda | generated boundary class |")
    lines.append("|---|---|---|---|---|---|---|")
    for name in boundary["patches"]:
        if name in policy["solid_walls"]:
            lines.append(f"| `{name}` | wall | `noSlip` | `zeroGradient` | `nutUSpaldingWallFunction` | `fixedValue 0` | `wall` |")
        else:
            flow = build_flow_bc_policy([name]).get(name, {})
            role = "flow boundary"
            lines.append(
                f"| `{name}` | {role} | `{flow.get('U', 'n/a')}` | `{flow.get('p', 'n/a')}` | "
                f"`{flow.get('nut', 'n/a')}` | `{flow.get('nuTilda', 'n/a')}` | `{boundary['patches'][name].get('type')}` |"
            )
    lines.append("")
    lines.append("No `k`/`omega` fields are used because this case uses Spalart-Allmaras (`nuTilda`).")
    (output_dir / "openfoam_bc_policy.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_generated_case_report(output_dir: Path, case_setup: Mapping[str, Any]) -> None:
    lines = ["# Generated Case Report", ""]
    for key in (
        "case_dir",
        "source_case",
        "mesh_topology_policy",
        "solver",
        "turbulence_model",
        "velocity_mps",
        "aoa_deg",
        "aoa_source",
        "ref_area_m2",
        "ref_length_m",
        "ref_origin_m",
    ):
        lines.append(f"- {key}: `{case_setup.get(key)}`")
    lines.append("")
    lines.append(f"- inlet U: `{case_setup['inlet_U']}`")
    lines.append(f"- dragDir: `{case_setup['dragDir']}`")
    lines.append(f"- liftDir: `{case_setup['liftDir']}`")
    lines.append(f"- solid walls: `{case_setup['solid_walls']}`")
    lines.append(f"- flow boundaries: `{case_setup['flow_boundaries']}`")
    lines.append("")
    lines.append("Generated files are under `openfoam_cases/true_baseline_swept_cgrid/0`, `constant`, and `system`.")
    (output_dir / "generated_case_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_forcecoeffs_setup_report(output_dir: Path, case_setup: Mapping[str, Any]) -> None:
    lines = ["# forceCoeffs Setup Report", ""]
    lines.append("- primary group: `airfoil_upper + airfoil_lower`")
    lines.append("- diagnostic groups are separate and not merged into one `wing_wall`")
    lines.append("- `forces` functionObjects are also enabled for pressure/viscous split")
    lines.append("- `Cd(f)` / `Cd(r)` from `forceCoeffs` are front/rear components, not pressure/viscous split")
    lines.append("")
    lines.append("| group | patches |")
    lines.append("|---|---|")
    for name, patches in case_setup["force_groups"].items():
        lines.append(f"| `{name}` | `{patches}` |")
    (output_dir / "forcecoeffs_setup_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_patch_geometry_extents(output_dir: Path, patch_geometry: Mapping[str, Any]) -> None:
    write_json(output_dir / "patch_geometry_extents.json", patch_geometry)
    domain_y = patch_geometry["domain_extent"]["y"]
    lines = ["# Patch Geometry Extents", ""]
    lines.append(f"- domain y extent: `[{domain_y['min']}, {domain_y['max']}]` m")
    lines.append(
        "- authority half/full span reference: "
        f"`{patch_geometry['authority_half_span_m']}` / `{patch_geometry['authority_full_span_m']}` m"
    )
    lines.append(f"- engineering note: {patch_geometry['engineering_note']}")
    lines.append("")
    lines.append("| patch | type | y min | y max | x min/max | z min/max |")
    lines.append("|---|---|---:|---:|---|---|")
    for name, data in patch_geometry["patches"].items():
        extent = data["extent"]
        x = extent["x"]
        y = extent["y"]
        z = extent["z"]
        lines.append(
            f"| `{name}` | `{data.get('type')}` | `{y['min']}` | `{y['max']}` | "
            f"`[{x['min']}, {x['max']}]` | `[{z['min']}, {z['max']}]` |"
        )
    (output_dir / "patch_geometry_extents_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def write_pre_solver_validation_report(
    output_dir: Path,
    validation: Mapping[str, Any],
    checkmesh: Mapping[str, Any] | None,
) -> None:
    metrics = parse_check_mesh_metrics(Path(checkmesh["log"])) if checkmesh else {"status": "not_run"}
    lines = ["# Pre-Solver Validation Report", ""]
    lines.append(f"- status: `{validation['status']}`")
    lines.append(f"- checkMesh metrics: `{metrics}`")
    lines.append("")
    for name, passed in validation["checks"].items():
        lines.append(f"- {name}: `{passed}`")
    lines.append("")
    lines.append(f"- missing field entries: `{validation['missing_by_field']}`")
    lines.append(f"- missing force patches: `{validation['force_patch_missing']}`")
    lines.append(f"- wall type errors: `{validation['wall_type_errors']}`")
    lines.append(f"- tip BC errors: `{validation['tip_bc_errors']}`")
    (output_dir / "pre_solver_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_reports(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    verdict = manifest["verdict"]
    coeffs = manifest["coefficients"]["summary"]
    yplus = manifest["yPlus"]
    split = manifest["force_split"]
    residuals = manifest["residuals"]
    stability = manifest["force_stability"]
    commands = manifest["commands"]
    failure = manifest["failure"]
    patch_geometry = manifest.get("patch_geometry_extents", {})
    domain_y = (
        patch_geometry.get("domain_extent", {}).get("y", {})
        if isinstance(patch_geometry, Mapping)
        else {}
    )
    patch_geometry_note = (
        patch_geometry.get("engineering_note")
        if isinstance(patch_geometry, Mapping)
        else None
    )

    route_lines = ["# Route Smoke Report", ""]
    route_lines.append(f"- status: `{verdict['status']}`")
    route_lines.append(f"- simpleFoam ran: `{verdict['simpleFoam_ran']}`")
    route_lines.append(f"- dry-run passed: `{verdict['dry_run_passed']}`")
    route_lines.append(f"- yPlus postprocess passed: `{verdict['yPlus_postprocess_passed']}`")
    route_lines.append(f"- CD_primary: `{coeffs.get('CD_primary')}`")
    route_lines.append(f"- CL_primary: `{coeffs.get('CL_primary')}`")
    route_lines.append(f"- CD_total: `{coeffs.get('CD_total')}`")
    if domain_y:
        route_lines.append(f"- domain y extent: `[{domain_y.get('min')}, {domain_y.get('max')}]` m")
    if patch_geometry_note:
        route_lines.append(f"- patch-geometry audit: {patch_geometry_note}")
    for name, command in commands.items():
        if command:
            route_lines.append(f"- {name}: rc `{command.get('returncode')}`, elapsed_s `{command.get('elapsed_s')}`")
    if failure:
        route_lines.append(f"- failure: `{failure}`")
    (output_dir / "route_smoke_report.md").write_text("\n".join(route_lines) + "\n", encoding="utf-8")

    force_lines = ["# Force Breakdown Report", ""]
    force_lines.append("| coefficient | value |")
    force_lines.append("|---|---:|")
    for key, value in coeffs.items():
        force_lines.append(f"| `{key}` | `{value}` |")
    if coeffs.get("CD_diagnostic_sum") is not None and coeffs.get("CD_total"):
        fraction = coeffs["CD_diagnostic_sum"] / coeffs["CD_total"]
        force_lines.append("")
        force_lines.append(
            f"Diagnostic CD is `{fraction:.6g}` of total CD; keep `CD_primary` separated until "
            "root/tip patch roles are resolved."
        )
    (output_dir / "force_breakdown_report.md").write_text("\n".join(force_lines) + "\n", encoding="utf-8")

    y_lines = ["# yPlus Report", ""]
    y_lines.append(f"- status: `{yplus.get('status')}`")
    y_lines.append(f"- source: `{yplus.get('source')}`")
    y_lines.append(f"- primary main-wall summary: `{yplus.get('primary_main_wall_summary')}`")
    y_lines.append("")
    y_lines.append("| patch | mean | p90 | p95 | p99 | max | count |")
    y_lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for patch, data in yplus.get("patches", {}).items():
        y_lines.append(
            f"| `{patch}` | `{data.get('mean')}` | `{data.get('p90')}` | `{data.get('p95')}` | "
            f"`{data.get('p99')}` | `{data.get('max')}` | `{data.get('count')}` |"
        )
    (output_dir / "yplus_report.md").write_text("\n".join(y_lines) + "\n", encoding="utf-8")

    stability_lines = ["# Residual and Force Stability Report", ""]
    stability_lines.append(f"- residuals: `{residuals}`")
    stability_lines.append(f"- force final-window stability: `{stability}`")
    stability_lines.append("- side-force sanity uses `Cs` in the forceCoeffs primary final window when available.")
    (output_dir / "residual_and_force_stability_report.md").write_text(
        "\n".join(stability_lines) + "\n",
        encoding="utf-8",
    )

    if verdict["pressure_viscous_split_available"]:
        split_lines = ["# Pressure / Viscous Split Report", ""]
        split_lines.append(split["source"])
        split_lines.append("")
        split_lines.append("| group | CD_pressure | CD_viscous | CL_pressure | CL_viscous |")
        split_lines.append("|---|---:|---:|---:|---:|")
        for name, data in split["groups"].items():
            values = data.get("split_coefficients") or {}
            split_lines.append(
                f"| `{name}` | `{values.get('CD_pressure')}` | `{values.get('CD_viscous')}` | "
                f"`{values.get('CL_pressure')}` | `{values.get('CL_viscous')}` |"
            )
        (output_dir / "pressure_viscous_split_report.md").write_text(
            "\n".join(split_lines) + "\n",
            encoding="utf-8",
        )

    verdict_lines = ["# Phase 4 True Baseline OpenFOAM Route-Smoke Verdict", ""]
    questions = [
        ("1. Did BC reconciliation complete?", verdict["bc_reconciliation_complete"]),
        ("2. Did every patch have valid BCs?", verdict["every_patch_has_valid_bcs"]),
        ("3. Did checkMesh still pass on the accepted full-wing mesh?", verdict["checkMesh_passed"]),
        ("4. Did simpleFoam run?", verdict["simpleFoam_ran"]),
        ("5. What are CD_primary, CL_primary, CD_total?", {
            "CD_primary": coeffs.get("CD_primary"),
            "CL_primary": coeffs.get("CL_primary"),
            "CD_total": coeffs.get("CD_total"),
        }),
        ("6. What is yPlus mean/p95/max?", verdict["yPlus_primary_mean_p95_max"]),
        ("7. Are tip/TE/closure diagnostics contaminating CD?", {
            "diagnostic_sum": coeffs.get("CD_diagnostic_sum"),
            "diagnostic_fraction_of_total": (
                coeffs.get("CD_diagnostic_sum") / coeffs.get("CD_total")
                if coeffs.get("CD_diagnostic_sum") is not None and coeffs.get("CD_total")
                else None
            ),
            "interpretation": (
                "Primary CD is separated, but diagnostic tip patches are not negligible in CD_total; "
                "do not use CD_total for profile-drag comparison without resolving patch role/domain symmetry."
            ),
        }),
        ("8. Is the force window stable enough for route-smoke?", stability.get("route_smoke_stable")),
        ("9. Is this result high-yPlus, wall-function, wall-resolved, or failed?", verdict["yplus_classification"]),
        ("10. Is this result comparable to XFOIL CD≈0.02602 yet?", verdict["xfoil_comparable"]),
        (
            "11. What is the next action?",
            "patch-role/domain audit before AoA sweep; then farfield/outlet sensitivity on the corrected BC convention",
        ),
    ]
    for question, answer in questions:
        verdict_lines.append(f"{question}\n   - `{answer}`")
    verdict_lines.append("")
    verdict_lines.append(f"Engineering boundary: {verdict['trust_boundary']}")
    if patch_geometry_note:
        verdict_lines.append(f"Patch-geometry audit: {patch_geometry_note}")
    (output_dir / "phase4_true_baseline_openfoam_route_smoke_verdict.md").write_text(
        "\n".join(verdict_lines) + "\n",
        encoding="utf-8",
    )


def write_rerun(output_dir: Path, source_case: Path) -> None:
    text = f"""# RERUN

From `/Volumes/Samsung SSD/hpa-mdo`:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/run_wo006_true_baseline_openfoam_route_smoke.py \\
  --source-case {shlex.quote(str(source_case))} \\
  --output-dir {shlex.quote(str(output_dir))} \\
  --clean
```

The runner copies the accepted polyMesh from the source case and only regenerates
OpenFOAM boundary-condition dictionaries, functionObjects, validation reports,
and solver logs. It does not rerun section, bay, geometry, TE-gap, or mesh-topology
generation.
"""
    (output_dir / "RERUN.md").write_text(text, encoding="utf-8")


def inlet_velocity(aoa_deg: float) -> tuple[float, float, float]:
    alpha = math.radians(aoa_deg)
    return (VELOCITY_MPS * math.cos(alpha), 0.0, VELOCITY_MPS * math.sin(alpha))


def drag_dir(aoa_deg: float) -> tuple[float, float, float]:
    alpha = math.radians(aoa_deg)
    return (math.cos(alpha), 0.0, math.sin(alpha))


def lift_dir(aoa_deg: float) -> tuple[float, float, float]:
    alpha = math.radians(aoa_deg)
    return (-math.sin(alpha), 0.0, math.cos(alpha))


def vec(values: Sequence[float]) -> str:
    return f"({values[0]:.9g} {values[1]:.9g} {values[2]:.9g})"


def parse_vector(text: str) -> tuple[float, float, float]:
    values = [float(token) for token in text.strip("() ").split()]
    if len(values) != 3:
        raise ValueError(f"expected 3-vector, got {text!r}")
    return (values[0], values[1], values[2])


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(float(x) * float(y) for x, y in zip(a, b, strict=True)))


def parse_time_l_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return {
        "maximum_resident_set_size_bytes": int_match(text, r"([0-9]+)\s+maximum resident set size"),
        "real_s": float_match(text, r"([-+0-9.eE]+)\s+real"),
        "user_s": float_match(text, r"([-+0-9.eE]+)\s+user"),
        "sys_s": float_match(text, r"([-+0-9.eE]+)\s+sys"),
    }


def last_coeff(functions: Mapping[str, Any], name: str, coeff: str) -> float | None:
    last = functions.get(name, {}).get("last")
    if not isinstance(last, Mapping):
        return None
    value = last.get(coeff)
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def grep_lines(path: Path, patterns: Iterable[str], *, limit: int = 40) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if any(pattern in line for pattern in patterns):
            out.append(line.strip())
            if len(out) >= limit:
                break
    return out


def tail(path: Path, count: int) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]


def int_match(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def float_match(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def str_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def float_or_none(value: str) -> float | None:
    try:
        out = float(value)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    main()
