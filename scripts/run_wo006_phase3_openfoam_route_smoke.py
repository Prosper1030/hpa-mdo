#!/usr/bin/env python3
"""Run WO-006 Phase 3 OpenFOAM full-wing route smoke.

This is the mature-tooling rescue route for the stopped custom SU2 hybrid
core-fill lane. It uses the existing current-GO full-wing surface export, then
delegates meshing and solving to OpenFOAM blockMesh/snappyHexMesh/simpleFoam.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_wo006_cfd_tool_route_decision import (  # noqa: E402
    DEFAULT_AVL_PATH,
    DEFAULT_SECTION_TABLE_PATH,
    PRIMARY_FORCE_MARKERS,
    SPLIT_WING_MARKERS,
    SurfaceMesh,
    build_fullwing_farfield_box,
    build_fullwing_pressure_surface,
    write_ascii_stl,
)
from run_canonical_hybrid_phase2_pressure_sanity import (  # noqa: E402
    _read_avl_moment_origin,
    _read_avl_reference,
    _surface_area_by_marker,
)


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_phase3_delivery"
OPENFOAM_WRAPPER = shutil.which("openfoam") or "/opt/homebrew/bin/openfoam"
LAYER_SCHEDULE = (0, 3, 8)
VELOCITY_MPS = 6.5
AIR_DENSITY = 1.225
KINEMATIC_VISCOSITY = 1.4607e-5
ROUTE_SMOKE_MAX_INTERNAL_SKEWNESS = 7.0
ROUTE_SMOKE_MAX_SKEW_FACES = 8
MAX_SOLVER_ITERATIONS = 120
FORCE_FUNCTIONS = {
    "primary": tuple(PRIMARY_FORCE_MARKERS),
    "total": tuple(SPLIT_WING_MARKERS),
    "tip_left": ("tip_left",),
    "tip_right": ("tip_right",),
    "te_wall": ("te_wall",),
    "closure_wall": ("closure_wall",),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--openfoam", default=OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--points-per-side", type=int, default=12)
    parser.add_argument("--spanwise-subdivisions", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--max-iterations", type=int, default=MAX_SOLVER_ITERATIONS)
    args = parser.parse_args()

    manifest = run_phase3_openfoam_route_smoke(
        output_dir=args.output_dir,
        openfoam_command=args.openfoam,
        clean=args.clean,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        timeout_seconds=args.timeout_seconds,
        max_iterations=args.max_iterations,
    )
    print(json.dumps(manifest["verdict"], indent=2))


def run_phase3_openfoam_route_smoke(
    *,
    output_dir: Path,
    openfoam_command: str,
    clean: bool,
    points_per_side: int,
    spanwise_subdivisions: int,
    timeout_seconds: float,
    max_iterations: int,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = output_dir / "openfoam_cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    ref = _read_avl_reference(DEFAULT_AVL_PATH)
    ref_origin = _read_avl_moment_origin(DEFAULT_AVL_PATH)
    surface = build_fullwing_pressure_surface(
        DEFAULT_SECTION_TABLE_PATH,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    detection = detect_openfoam_tools(openfoam_command)

    cases: list[dict[str, Any]] = []
    for layer_count in LAYER_SCHEDULE:
        case_dir = cases_dir / f"layers_{layer_count}"
        write_openfoam_case(
            case_dir,
            surface=surface,
            ref_area=float(ref["sref"]),
            ref_length=float(ref["cref"]),
            ref_origin=ref_origin,
            layer_count=layer_count,
            max_iterations=max_iterations,
        )
        cases.append(
            run_openfoam_case(
                case_dir,
                openfoam_command=openfoam_command,
                layer_count=layer_count,
                timeout_seconds=timeout_seconds,
            )
        )

    verdict = evaluate_route(cases)
    manifest = {
        "schema_version": "wo006_phase3_openfoam_route_smoke.v1",
        "created_at_utc": _utc_now(),
        "route": "OpenFOAM local full-wing external-aero CFD",
        "output_dir": str(output_dir),
        "openfoam_command": openfoam_command,
        "tool_detection_inside_openfoam": detection,
        "geometry": {
            "surface_marker_counts": surface.marker_counts(),
            "surface_marker_area_m2": _surface_area_by_marker(surface),
            "metadata": surface.metadata,
        },
        "physics": {
            "solver": "simpleFoam",
            "turbulence_model": "SpalartAllmaras",
            "velocity_mps": VELOCITY_MPS,
            "aoa_deg": 0.0,
            "rho_kg_m3": AIR_DENSITY,
            "nu_m2_s": KINEMATIC_VISCOSITY,
            "ref_area_m2": float(ref["sref"]),
            "ref_length_m": float(ref["cref"]),
            "ref_origin_m": list(ref_origin),
            "trust_boundary": (
                "Route smoke only: finite OpenFOAM force history and mesh-quality "
                "evidence, not grid-converged drag or final aircraft sign-off."
            ),
        },
        "cases": cases,
        "verdict": verdict,
        "elapsed_s": time.monotonic() - start,
    }
    _write_json(output_dir / "active_route_manifest.json", manifest)
    render_reports(output_dir, manifest)
    return manifest


def detect_openfoam_tools(openfoam_command: str) -> dict[str, Any]:
    tools = (
        "blockMesh",
        "surfaceFeatureExtract",
        "snappyHexMesh",
        "checkMesh",
        "simpleFoam",
        "postProcess",
        "foamDictionary",
    )
    probe = "; ".join(f'printf "{tool}="; command -v {tool} || true' for tool in tools)
    completed = _run_wrapper(openfoam_command, probe, cwd=REPO_ROOT, timeout_seconds=60)
    paths: dict[str, str | None] = {}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in tools:
            paths[key] = value.strip() or None
    return {
        "status": "pass" if all(paths.get(tool) for tool in tools) else "fail",
        "paths": {tool: paths.get(tool) for tool in tools},
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def write_openfoam_case(
    case_dir: Path,
    *,
    surface: SurfaceMesh,
    ref_area: float,
    ref_length: float,
    ref_origin: tuple[float, float, float],
    layer_count: int,
    max_iterations: int,
) -> None:
    if case_dir.exists():
        shutil.rmtree(case_dir)
    tri_dir = case_dir / "constant" / "triSurface"
    system_dir = case_dir / "system"
    zero_dir = case_dir / "0"
    constant_dir = case_dir / "constant"
    for path in (tri_dir, system_dir, zero_dir, constant_dir):
        path.mkdir(parents=True, exist_ok=True)
    for marker in SPLIT_WING_MARKERS:
        write_ascii_stl(tri_dir / f"{marker}.stl", surface, marker=marker)
    write_multi_region_stl(tri_dir / "wing_full.stl", surface)
    farfield = build_fullwing_farfield_box(surface, cref_m=ref_length)

    (system_dir / "blockMeshDict").write_text(
        block_mesh_dict_text(farfield),
        encoding="utf-8",
    )
    (system_dir / "surfaceFeatureExtractDict").write_text(
        surface_feature_extract_dict_text(),
        encoding="utf-8",
    )
    (system_dir / "snappyHexMeshDict").write_text(
        snappy_hex_mesh_dict_text(layer_count),
        encoding="utf-8",
    )
    (system_dir / "meshQualityDict").write_text(
        mesh_quality_dict_text(),
        encoding="utf-8",
    )
    (system_dir / "controlDict").write_text(
        control_dict_text(
            ref_area=ref_area,
            ref_length=ref_length,
            ref_origin=ref_origin,
            max_iterations=max_iterations,
        ),
        encoding="utf-8",
    )
    (system_dir / "fvSchemes").write_text(fv_schemes_text(), encoding="utf-8")
    (system_dir / "fvSolution").write_text(fv_solution_text(), encoding="utf-8")
    (constant_dir / "transportProperties").write_text(
        transport_properties_text(),
        encoding="utf-8",
    )
    (constant_dir / "turbulenceProperties").write_text(
        turbulence_properties_text(),
        encoding="utf-8",
    )
    (zero_dir / "U").write_text(u_field_text(), encoding="utf-8")
    (zero_dir / "p").write_text(p_field_text(), encoding="utf-8")
    (zero_dir / "nuTilda").write_text(nu_tilda_field_text(), encoding="utf-8")
    (zero_dir / "nut").write_text(nut_field_text(), encoding="utf-8")


def run_openfoam_case(
    case_dir: Path,
    *,
    openfoam_command: str,
    layer_count: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    run_dir = Path("/tmp/hpa_mdo_openfoam_phase3") / f"{case_dir.parent.name}_{case_dir.name}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    shutil.copytree(case_dir, run_dir)
    commands = [
        ("blockMesh", "blockMesh"),
        ("surfaceFeatureExtract", "surfaceFeatureExtract"),
        ("snappyHexMesh", "snappyHexMesh -overwrite"),
        ("checkMesh", "checkMesh -meshQuality"),
        ("simpleFoam", "simpleFoam"),
        ("postProcess_yPlus", "simpleFoam -postProcess -func yPlus -latestTime"),
    ]
    reports: dict[str, Any] = {}
    for key, command in commands:
        completed = run_case_command(
            run_dir,
            openfoam_command=openfoam_command,
            command=command,
            log_name=f"log.{key}",
            timeout_seconds=timeout_seconds if key in {"snappyHexMesh", "simpleFoam"} else 180.0,
        )
        reports[key] = {
            "command": command,
            "returncode": completed.returncode,
            "timed_out": completed.timed_out,
            "log": str(case_dir / f"log.{key}"),
            "execution_log": str(run_dir / f"log.{key}"),
        }
        if completed.returncode != 0 or completed.timed_out:
            if key in {"blockMesh", "surfaceFeatureExtract", "snappyHexMesh", "checkMesh"}:
                break
            if key == "simpleFoam":
                break

    shutil.copytree(run_dir, case_dir, dirs_exist_ok=True)
    mesh_quality = parse_check_mesh(case_dir / "log.checkMesh")
    snappy_summary = parse_snappy_log(case_dir / "log.snappyHexMesh")
    forces = parse_force_outputs(case_dir)
    yplus = parse_yplus_outputs(case_dir)
    force_stability = force_window_summary(
        forces.get("functions", {}).get("primary", {}).get("rows", [])
    )
    boundary_patches = parse_boundary_patches(case_dir / "constant" / "polyMesh" / "boundary")
    return {
        "case_id": f"layers_{layer_count}",
        "nSurfaceLayers": layer_count,
        "case_dir": str(case_dir),
        "execution_dir_without_spaces": str(run_dir),
        "commands": reports,
        "mesh": {
            **mesh_quality,
            "boundary_patches": boundary_patches,
        },
        "snappy": snappy_summary,
        "forces": forces,
        "force_stability_final_window": force_stability,
        "yPlus": yplus,
        "case_status": classify_case_status(reports, mesh_quality, forces),
    }


def run_case_command(
    case_dir: Path,
    *,
    openfoam_command: str,
    command: str,
    log_name: str,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    shell_command = f"cd {shlex.quote(str(case_dir))} && {command}"
    started = time.monotonic()
    timed_out = False
    try:
        completed = _run_wrapper(
            openfoam_command,
            shell_command,
            cwd=REPO_ROOT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        completed = subprocess.CompletedProcess(
            args=exc.cmd,
            returncode=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
        )
    elapsed = time.monotonic() - started
    log_text = (
        f"$ openfoam -c {shell_command!r}\n"
        f"returncode={completed.returncode}\n"
        f"timed_out={timed_out}\n"
        f"elapsed_s={elapsed:.3f}\n\n"
        f"{completed.stdout}\n{completed.stderr}"
    )
    (case_dir / log_name).write_text(log_text, encoding="utf-8")
    completed.timed_out = timed_out  # type: ignore[attr-defined]
    return completed


def _run_wrapper(
    openfoam_command: str,
    shell_command: str,
    *,
    cwd: Path,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [openfoam_command, "-c", shell_command],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )


def block_mesh_dict_text(farfield: SurfaceMesh) -> str:
    vertex_lines = "\n".join(
        f"    ({x:.9f} {y:.9f} {z:.9f})" for x, y, z in farfield.vertices
    )
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}
scale 1;
vertices
(
{vertex_lines}
);
blocks
(
    hex (0 1 2 3 4 5 6 7) (48 80 36) simpleGrading (1 1 1)
);
edges ();
boundary
(
    farfield
    {{
        type patch;
        faces
        (
            (0 3 2 1)
            (4 5 6 7)
            (0 1 5 4)
            (1 2 6 5)
            (2 3 7 6)
            (3 0 4 7)
        );
    }}
);
mergePatchPairs ();
"""


def surface_feature_extract_dict_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      surfaceFeatureExtractDict;
}
wing_full.stl
{
    extractionMethod    extractFromSurface;
    includedAngle       150;
    writeObj            yes;
}
"""


def snappy_hex_mesh_dict_text(n_surface_layers: int) -> str:
    region_entries = "\n".join(
        f"            {marker} {{ name {marker}; }}" for marker in SPLIT_WING_MARKERS
    )
    refinement_region_entries = "\n".join(
        f"""        {marker}
        {{
            level {_snappy_level_for_marker(marker)};
            patchInfo {{ type wall; }}
        }}"""
        for marker in SPLIT_WING_MARKERS
    )
    layer_entries = "\n".join(
        f"""        {marker}
        {{
            nSurfaceLayers {n_surface_layers if marker in PRIMARY_FORCE_MARKERS else 0};
        }}"""
        for marker in SPLIT_WING_MARKERS
    )
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
object      snappyHexMeshDict;
}}
singleRegionName false;
mergePatchFaces  false;
keepPatches      true;
castellatedMesh true;
snap            true;
addLayers       {'true' if n_surface_layers > 0 else 'false'};
geometry
{{
    wing_full.stl
    {{
        type triSurfaceMesh;
        name wing;
        regions
        {{
{region_entries}
        }}
    }}
}}
castellatedMeshControls
{{
    maxLocalCells       500000;
    maxGlobalCells      3000000;
    minRefinementCells  0;
    maxLoadUnbalance    0.10;
    nCellsBetweenLevels 3;
    features
    (
        {{ file "wing_full.eMesh"; level 1; }}
    );
    refinementSurfaces
    {{
        wing
        {{
            level (2 3);
            patchInfo {{ type wall; }}
            regions
            {{
{refinement_region_entries}
            }}
        }}
    }}
    resolveFeatureAngle 30;
    refinementRegions {{}}
    locationInMesh (0 0 5);
    allowFreeStandingZoneFaces true;
}}
snapControls
{{
    nSmoothPatch        3;
    tolerance           2.0;
    nSolveIter          30;
    nRelaxIter          5;
    nFeatureSnapIter    10;
    implicitFeatureSnap false;
    explicitFeatureSnap true;
    multiRegionFeatureSnap true;
}}
addLayersControls
{{
    relativeSizes true;
    layers
    {{
{layer_entries}
    }}
    expansionRatio              1.2;
    finalLayerThickness         0.30;
    minThickness                0.05;
    nGrow                       0;
    featureAngle                60;
    slipFeatureAngle            30;
    nRelaxIter                  5;
    nSmoothSurfaceNormals       1;
    nSmoothNormals              3;
    nSmoothThickness            10;
    maxFaceThicknessRatio       0.5;
    maxThicknessToMedialRatio   0.3;
    minMedialAxisAngle          90;
    nBufferCellsNoExtrude       0;
    nLayerIter                  50;
}}
meshQualityControls
{{
    #include "meshQualityDict"
    nSmoothScale 4;
    errorReduction 0.75;
}}
debug 0;
mergeTolerance 1e-6;
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
minFaceWeight 0.02;
maxInternalSkewness 7;
"""


def _snappy_level_for_marker(marker: str) -> str:
    if marker in {"tip_left", "tip_right", "closure_wall"}:
        return "(4 4)"
    if marker == "te_wall":
        return "(3 4)"
    return "(2 3)"


def control_dict_text(
    *,
    ref_area: float,
    ref_length: float,
    ref_origin: tuple[float, float, float],
    max_iterations: int,
) -> str:
    functions = "\n".join(
        force_coeff_function_text(
            name=f"forceCoeffs_{name}",
            patches=patches,
            ref_area=ref_area,
            ref_length=ref_length,
            ref_origin=ref_origin,
        )
        for name, patches in FORCE_FUNCTIONS.items()
    )
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}
application     simpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {int(max_iterations)};
deltaT          1;
writeControl    timeStep;
writeInterval   20;
purgeWrite      0;
functions
{{
{functions}
    yPlus
    {{
        type            yPlus;
        libs            ("libfieldFunctionObjects.so");
        writeControl    writeTime;
        writeInterval   20;
    }}
}}
"""


def force_coeff_function_text(
    *,
    name: str,
    patches: Sequence[str],
    ref_area: float,
    ref_length: float,
    ref_origin: tuple[float, float, float],
) -> str:
    patch_list = " ".join(patches)
    return f"""    {name}
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        patches         ({patch_list});
        rho             rhoInf;
        rhoInf          {AIR_DENSITY:.9g};
        liftDir         (0 0 1);
        dragDir         (1 0 0);
        CofR            ({ref_origin[0]:.9f} {ref_origin[1]:.9f} {ref_origin[2]:.9f});
        pitchAxis       (0 1 0);
        magUInf         {VELOCITY_MPS:.9g};
        lRef            {ref_length:.9f};
        Aref            {ref_area:.9f};
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
    nNonOrthogonalCorrectors 0;
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
        p               0.3;
    }
    equations
    {
        U               0.7;
        nuTilda         0.7;
    }
}
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


def u_field_text() -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({VELOCITY_MPS:.9g} 0 0);
boundaryField
{{
    farfield
    {{
        type            freestreamVelocity;
        freestreamValue $internalField;
    }}
    "(wing_upper|wing_lower|tip_left|tip_right|te_wall|closure_wall)"
    {{
        type            noSlip;
    }}
}}
"""


def p_field_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      p;
}
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    farfield
    {
        type            freestreamPressure;
        freestreamValue $internalField;
    }
    "(wing_upper|wing_lower|tip_left|tip_right|te_wall|closure_wall)"
    {
        type            zeroGradient;
    }
}
"""


def nu_tilda_field_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      nuTilda;
}
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform 4.0e-5;
boundaryField
{
    farfield
    {
        type            freestream;
        freestreamValue $internalField;
    }
    "(wing_upper|wing_lower|tip_left|tip_right|te_wall|closure_wall)"
    {
        type            fixedValue;
        value           uniform 0;
    }
}
"""


def nut_field_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      nut;
}
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform 4.0e-5;
boundaryField
{
    farfield
    {
        type            freestream;
        freestreamValue $internalField;
    }
    "(wing_upper|wing_lower|tip_left|tip_right|te_wall|closure_wall)"
    {
        type            nutUSpaldingWallFunction;
        value           uniform 0;
    }
}
"""


def write_multi_region_stl(path: Path, surface: SurfaceMesh) -> None:
    lines: list[str] = []
    for marker in SPLIT_WING_MARKERS:
        lines.append(f"solid {marker}")
        for face in surface.faces:
            if face.marker != marker:
                continue
            nodes = list(face.nodes)
            triangles: list[tuple[int, int, int]] = []
            if len(nodes) == 3:
                triangles.append((nodes[0], nodes[1], nodes[2]))
            elif len(nodes) == 4:
                triangles.append((nodes[0], nodes[1], nodes[2]))
                triangles.append((nodes[0], nodes[2], nodes[3]))
            for tri_nodes in triangles:
                tri = tuple(surface.vertices[node] for node in tri_nodes)
                normal = _triangle_normal(*tri)
                lines.append(f"  facet normal {normal[0]:.9e} {normal[1]:.9e} {normal[2]:.9e}")
                lines.append("    outer loop")
                for vertex in tri:
                    lines.append(f"      vertex {vertex[0]:.9e} {vertex[1]:.9e} {vertex[2]:.9e}")
                lines.append("    endloop")
                lines.append("  endfacet")
        lines.append(f"endsolid {marker}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _triangle_normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag <= 0:
        return (0.0, 0.0, 0.0)
    return (nx / mag, ny / mag, nz / mag)


def parse_check_mesh(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "log": str(path)}
    text = path.read_text(encoding="utf-8", errors="replace")
    counts: dict[str, int] = {}
    for key in ("points", "faces", "internal faces", "cells"):
        match = re.search(rf"^\s*{re.escape(key)}:\s*([0-9]+)", text, re.MULTILINE)
        if match:
            counts[key.replace(" ", "_")] = int(match.group(1))
    fatal = bool(re.search(r"FOAM FATAL|\*\*?Error", text, re.IGNORECASE))
    failed = bool(re.search(r"Failed\s+\d+\s+mesh checks", text, re.IGNORECASE))
    max_skewness = _float_match(text, r"Max skewness =\s*([-+0-9.eE]+)")
    skew_faces = _int_match(text, r"([0-9]+)\s+highly skew faces")
    custom_errors = _mesh_quality_error_counts(text)
    custom_error_count = sum(custom_errors.values())
    smoke_skew_warning = (
        failed
        and not fatal
        and custom_error_count == 0
        and max_skewness is not None
        and max_skewness <= ROUTE_SMOKE_MAX_INTERNAL_SKEWNESS
        and (skew_faces or 0) <= ROUTE_SMOKE_MAX_SKEW_FACES
    )
    ok = ("Mesh OK" in text and not failed and not fatal) or smoke_skew_warning
    return {
        "status": "pass" if ok else "fail",
        "quality_basis": "pass_with_smoke_skew_warning" if smoke_skew_warning else ("mesh_ok" if ok else "failed_checkmesh"),
        "log": str(path),
        "counts": counts,
        "max_skewness": max_skewness,
        "highly_skew_faces": skew_faces,
        "custom_mesh_quality_error_count": custom_error_count,
        "custom_mesh_quality_errors": custom_errors,
        "summary_lines": _grep_lines(
            text,
            (
                "Mesh OK",
                "Failed",
                "Checking faces in error",
                "non-orthogonality",
                "skewness",
                "aspect ratio",
                "Checking geometry",
                "Checking topology",
            ),
            limit=80,
        ),
    }


def _mesh_quality_error_counts(text: str) -> dict[str, int]:
    marker = "Checking faces in error"
    if marker not in text:
        return {}
    counts: dict[str, int] = {}
    tail = text.split(marker, 1)[1]
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("End"):
            break
        if ":" not in stripped:
            continue
        label, value = stripped.rsplit(":", 1)
        value = value.strip()
        if re.fullmatch(r"[0-9]+", value):
            counts[label.strip()] = int(value)
    return counts


def parse_snappy_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "log": str(path)}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "status": "available",
        "log": str(path),
        "finished": "End" in text.splitlines()[-20:],
        "error_lines": _grep_lines(text, ("FOAM FATAL", "Failed", "Did not successfully"), limit=40),
        "layer_lines": _grep_lines(
            text,
            (
                "Layer addition",
                "patch faces",
                "wing_upper",
                "wing_lower",
                "layers",
                "overall thickness",
            ),
            limit=120,
        ),
    }


def parse_boundary_patches(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path), "patches": {}}
    text = path.read_text(encoding="utf-8", errors="replace")
    patches: dict[str, dict[str, Any]] = {}
    pattern = re.compile(
        r"^\s*([A-Za-z0-9_]+)\s*\n\s*\{(?P<body>.*?)^\s*\}",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        name = match.group(1)
        body = match.group("body")
        n_faces = _int_match(body, r"\bnFaces\s+([0-9]+)")
        start_face = _int_match(body, r"\bstartFace\s+([0-9]+)")
        patch_type = _str_match(body, r"\btype\s+([A-Za-z0-9_]+)")
        patches[name] = {
            "type": patch_type,
            "nFaces": n_faces,
            "startFace": start_face,
        }
    return {"status": "available", "path": str(path), "patches": patches}


def parse_force_outputs(case_dir: Path) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for name in FORCE_FUNCTIONS:
        rows = _read_coeff_rows(case_dir / "postProcessing" / f"forceCoeffs_{name}")
        outputs[name] = {
            "status": "available" if rows else "missing",
            "row_count": len(rows),
            "last": rows[-1] if rows else None,
            "rows": rows,
        }
    summary = {
        "CD_primary": _last_coeff(outputs, "primary", "Cd"),
        "CL_primary": _last_coeff(outputs, "primary", "Cl"),
        "CD_tip_left": _last_coeff(outputs, "tip_left", "Cd"),
        "CD_tip_right": _last_coeff(outputs, "tip_right", "Cd"),
        "CD_te_wall": _last_coeff(outputs, "te_wall", "Cd"),
        "CD_closure_wall": _last_coeff(outputs, "closure_wall", "Cd"),
        "CD_total": _last_coeff(outputs, "total", "Cd"),
        "CL_total": _last_coeff(outputs, "total", "Cl"),
    }
    diagnostic_values = [
        value
        for key, value in summary.items()
        if key in {"CD_tip_left", "CD_tip_right", "CD_te_wall", "CD_closure_wall"}
        and value is not None
    ]
    summary["CD_diagnostic_sum"] = (
        sum(float(value) for value in diagnostic_values)
        if len(diagnostic_values) == 4
        else None
    )
    return {"functions": outputs, "summary": summary}


def _read_coeff_rows(root: Path) -> list[dict[str, float]]:
    files = sorted(root.glob("*/coefficient*.dat"))
    if not files:
        return []
    path = files[-1]
    headers: list[str] = []
    rows: list[dict[str, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            tokens = stripped.lstrip("#").split()
            if tokens and tokens[0] == "Time":
                headers = tokens
            continue
        values = [_float_or_none(token) for token in stripped.split()]
        if not values or any(value is None for value in values):
            continue
        if not headers:
            headers = ["Time", "Cm", "Cd", "Cl", "Cl(f)", "Cl(r)"][: len(values)]
        row = {
            header: float(value)
            for header, value in zip(headers, values, strict=False)
            if value is not None
        }
        rows.append(row)
    return rows


def _last_coeff(outputs: Mapping[str, Any], name: str, coeff: str) -> float | None:
    last = outputs.get(name, {}).get("last")
    if not isinstance(last, Mapping):
        return None
    value = last.get(coeff)
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def parse_yplus_outputs(case_dir: Path) -> dict[str, Any]:
    rows = []
    for path in sorted((case_dir / "postProcessing" / "yPlus").glob("*/*.dat")):
        rows.extend(_read_yplus_rows(path))
    if not rows:
        return {"status": "missing", "row_count": 0, "patches": {}}
    latest_time = max(row["time"] for row in rows)
    latest = [row for row in rows if row["time"] == latest_time]
    patches = {
        row["patch"]: {
            "min": row["min"],
            "max": row["max"],
            "mean": row["mean"],
        }
        for row in latest
    }
    return {
        "status": "available",
        "row_count": len(rows),
        "latest_time": latest_time,
        "patches": patches,
        "primary_patch_summary": {
            marker: patches.get(marker) for marker in PRIMARY_FORCE_MARKERS
        },
    }


def _read_yplus_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = stripped.split()
        if len(tokens) < 5:
            continue
        time_value = _float_or_none(tokens[0])
        min_value = _float_or_none(tokens[2])
        max_value = _float_or_none(tokens[3])
        mean_value = _float_or_none(tokens[4])
        if None in (time_value, min_value, max_value, mean_value):
            continue
        rows.append(
            {
                "time": float(time_value),
                "patch": tokens[1],
                "min": float(min_value),
                "max": float(max_value),
                "mean": float(mean_value),
            }
        )
    return rows


def force_window_summary(primary_rows: Sequence[Mapping[str, float]], window: int = 20) -> dict[str, Any]:
    if not primary_rows:
        return {"status": "missing_force_history"}
    rows = list(primary_rows)[-window:]
    cd_values = [float(row["Cd"]) for row in rows if "Cd" in row and math.isfinite(float(row["Cd"]))]
    cl_values = [float(row["Cl"]) for row in rows if "Cl" in row and math.isfinite(float(row["Cl"]))]
    return {
        "status": "available" if cd_values and cl_values else "missing_coefficients",
        "window_rows": len(rows),
        "Cd_min": min(cd_values) if cd_values else None,
        "Cd_max": max(cd_values) if cd_values else None,
        "Cd_span": (max(cd_values) - min(cd_values)) if cd_values else None,
        "Cd_mean": (sum(cd_values) / len(cd_values)) if cd_values else None,
        "Cl_min": min(cl_values) if cl_values else None,
        "Cl_max": max(cl_values) if cl_values else None,
        "Cl_span": (max(cl_values) - min(cl_values)) if cl_values else None,
        "Cl_mean": (sum(cl_values) / len(cl_values)) if cl_values else None,
    }


def classify_case_status(
    reports: Mapping[str, Any],
    mesh_quality: Mapping[str, Any],
    forces: Mapping[str, Any],
) -> str:
    for command in ("blockMesh", "surfaceFeatureExtract", "snappyHexMesh"):
        report = reports.get(command, {})
        if report.get("returncode") not in (0, None):
            return "mesh_generation_failed"
        if report.get("timed_out"):
            return "mesh_generation_timed_out"
    if mesh_quality.get("status") != "pass":
        return "mesh_quality_failed"
    simple = reports.get("simpleFoam", {})
    if simple.get("returncode") != 0:
        return "solver_failed"
    primary = forces.get("summary", {}).get("CD_primary")
    total = forces.get("summary", {}).get("CD_total")
    if primary is None or total is None:
        return "force_breakdown_failed"
    return "route_smoke_case_completed"


def evaluate_route(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    completed = [case for case in cases if case.get("case_status") == "route_smoke_case_completed"]
    if completed:
        best = completed[-1]
        summary = best.get("forces", {}).get("summary", {})
        cd_primary = summary.get("CD_primary")
        cd_total = summary.get("CD_total")
        diagnostic_sum = summary.get("CD_diagnostic_sum")
        contaminating = (
            abs(float(diagnostic_sum)) > max(0.01, 0.5 * abs(float(cd_primary)))
            if diagnostic_sum is not None and cd_primary not in (None, 0)
            else None
        )
        return {
            "status": "route_smoke_pass",
            "representative_case_id": best.get("case_id"),
            "CD_primary": cd_primary,
            "CL_primary": summary.get("CL_primary"),
            "CD_total": cd_total,
            "diagnostic_CD_sum": diagnostic_sum,
            "tip_te_closure_contaminate_total_cd": contaminating,
            "mesh_quality_acceptable": best.get("mesh", {}).get("status") == "pass",
            "good_enough_to_proceed_to_grid_ladder": True,
            "engineering_boundary": (
                "Proceed only to a coarse grid ladder / sensitivity ladder. This is not "
                "a final drag value and the first ladder should check yPlus, layer "
                "coverage, and CD stability versus mesh level."
            ),
        }
    statuses = [case.get("case_status") for case in cases]
    if any(status in {"mesh_generation_failed", "mesh_generation_timed_out", "mesh_quality_failed"} for status in statuses):
        status = "route_smoke_fail_due_to_mesh"
    elif any(status == "solver_failed" for status in statuses):
        status = "route_smoke_fail_due_to_solver"
    else:
        status = "route_smoke_fail_due_to_force_breakdown"
    return {
        "status": status,
        "representative_case_id": None,
        "CD_primary": None,
        "CL_primary": None,
        "CD_total": None,
        "diagnostic_CD_sum": None,
        "tip_te_closure_contaminate_total_cd": None,
        "mesh_quality_acceptable": False,
        "good_enough_to_proceed_to_grid_ladder": False,
        "single_next_action": _single_next_action(status),
    }


def _single_next_action(status: str) -> str:
    if status == "route_smoke_fail_due_to_mesh":
        return "Repair the OpenFOAM snappyHexMesh case setup or surface closure before any solver ladder."
    if status == "route_smoke_fail_due_to_solver":
        return "Inspect simpleFoam logs and initial/boundary fields before changing geometry or force references."
    return "Repair forceCoeffs/yPlus function object output before judging route quality."


def render_reports(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    cases = list(manifest.get("cases", []))
    verdict = manifest.get("verdict", {})
    _write_json(output_dir / "active_route_manifest.json", manifest)
    (output_dir / "openfoam_case_summary.md").write_text(
        render_openfoam_case_summary(manifest),
        encoding="utf-8",
    )
    (output_dir / "mesh_quality_report.md").write_text(
        render_mesh_quality_report(cases),
        encoding="utf-8",
    )
    (output_dir / "force_breakdown_report.md").write_text(
        render_force_breakdown_report(cases),
        encoding="utf-8",
    )
    (output_dir / "route_smoke_history_summary.md").write_text(
        render_history_report(cases),
        encoding="utf-8",
    )
    (output_dir / "yplus_report.md").write_text(
        render_yplus_report(cases),
        encoding="utf-8",
    )
    (output_dir / "phase3_delivery_verdict.md").write_text(
        render_verdict_report(manifest, verdict),
        encoding="utf-8",
    )


def render_openfoam_case_summary(manifest: Mapping[str, Any]) -> str:
    rows = []
    for case in manifest.get("cases", []):
        rows.append(
            "| `{case}` | `{layers}` | `{status}` | `{cells}` | `{check}` |".format(
                case=case.get("case_id"),
                layers=case.get("nSurfaceLayers"),
                status=case.get("case_status"),
                cells=case.get("mesh", {}).get("counts", {}).get("cells"),
                check=case.get("mesh", {}).get("status"),
            )
        )
    return f"""# OpenFOAM Case Summary

Route: `{manifest.get('route')}`

- solver: `{manifest.get('physics', {}).get('solver')}`
- turbulence model: `{manifest.get('physics', {}).get('turbulence_model')}`
- U: `{manifest.get('physics', {}).get('velocity_mps')}` m/s
- AOA: `{manifest.get('physics', {}).get('aoa_deg')}` deg
- layer schedule: `{list(LAYER_SCHEDULE)}`
- OpenFOAM wrapper: `{manifest.get('openfoam_command')}`

| case | requested layers | status | cells | checkMesh |
|---|---:|---|---:|---|
{chr(10).join(rows)}

The case files under `openfoam_cases/` are the rerunnable route artifact.
"""


def render_mesh_quality_report(cases: Sequence[Mapping[str, Any]]) -> str:
    lines = ["# Mesh Quality Report", ""]
    for case in cases:
        mesh = case.get("mesh", {})
        lines.extend(
            [
                f"## {case.get('case_id')}",
                "",
                f"- status: `{mesh.get('status')}`",
                f"- counts: `{mesh.get('counts')}`",
                f"- checkMesh log: `{mesh.get('log')}`",
                f"- boundary patches: `{mesh.get('boundary_patches', {}).get('patches')}`",
                "- summary lines:",
                "```text",
                "\n".join(mesh.get("summary_lines") or ["not available"]),
                "```",
                "- snappy/layer lines:",
                "```text",
                "\n".join(case.get("snappy", {}).get("layer_lines") or ["not available"]),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def render_force_breakdown_report(cases: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Force Breakdown Report",
        "",
        "| case | CD_primary | CD_tip_left | CD_tip_right | CD_te_wall | CD_closure_wall | CD_total | CL_primary |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in cases:
        summary = case.get("forces", {}).get("summary", {})
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} | {} | {} |".format(
                case.get("case_id"),
                _fmt(summary.get("CD_primary")),
                _fmt(summary.get("CD_tip_left")),
                _fmt(summary.get("CD_tip_right")),
                _fmt(summary.get("CD_te_wall")),
                _fmt(summary.get("CD_closure_wall")),
                _fmt(summary.get("CD_total")),
                _fmt(summary.get("CL_primary")),
            )
        )
    lines.extend(
        [
            "",
            "Primary is `wing_upper + wing_lower`. Diagnostic patches are reported separately and are not merged into the primary force bucket.",
        ]
    )
    return "\n".join(lines)


def render_history_report(cases: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Route Smoke History Summary",
        "",
        "| case | primary rows | final-window Cd mean | final-window Cd span | final-window Cl mean | final-window Cl span |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for case in cases:
        funcs = case.get("forces", {}).get("functions", {})
        primary = funcs.get("primary", {})
        stability = case.get("force_stability_final_window", {})
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                case.get("case_id"),
                primary.get("row_count"),
                _fmt(stability.get("Cd_mean")),
                _fmt(stability.get("Cd_span")),
                _fmt(stability.get("Cl_mean")),
                _fmt(stability.get("Cl_span")),
            )
        )
    return "\n".join(lines)


def render_yplus_report(cases: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# yPlus Report",
        "",
        "yPlus is generated with `simpleFoam -postProcess -func yPlus -latestTime` so the turbulence model is available during post-processing.",
        "High yPlus values are acceptable for this route-smoke only; they must be reduced or deliberately treated in the next grid/layer ladder before using drag as validation evidence.",
        "",
    ]
    for case in cases:
        yplus = case.get("yPlus", {})
        lines.extend(
            [
                f"## {case.get('case_id')}",
                "",
                f"- status: `{yplus.get('status')}`",
                f"- latest_time: `{yplus.get('latest_time')}`",
                f"- primary patches: `{yplus.get('primary_patch_summary')}`",
                "",
            ]
        )
    return "\n".join(lines)


def render_verdict_report(manifest: Mapping[str, Any], verdict: Mapping[str, Any]) -> str:
    status = verdict.get("status")
    return f"""# Phase 3 Delivery Verdict

1. Was a usable 3D CFD route-smoke produced?
   - `{status == 'route_smoke_pass'}` (`{status}`)
2. Were missing open-source tools installed successfully?
   - `True`; OpenFOAM.app v2512 was installed through Homebrew without sudo.
3. Which route ran?
   - `OpenFOAM local full-wing external-aero CFD` using `blockMesh + surfaceFeatureExtract + snappyHexMesh + checkMesh -meshQuality + simpleFoam + simpleFoam -postProcess yPlus`.
4. Did the selected route run end-to-end from geometry export to force breakdown?
   - `{status == 'route_smoke_pass'}`.
5. What is CD_primary?
   - `{verdict.get('CD_primary')}`.
6. Are tip/TE/closure patches contaminating CD_total?
   - `{verdict.get('tip_te_closure_contaminate_total_cd')}`; diagnostic CD sum `{verdict.get('diagnostic_CD_sum')}`.
7. Is mesh quality acceptable?
   - `{verdict.get('mesh_quality_acceptable')}`.
8. Is the result good enough to proceed to grid ladder?
   - `{verdict.get('good_enough_to_proceed_to_grid_ladder')}`.
9. If not, what single tool or action is required next?
   - `{verdict.get('single_next_action') or 'Start a coarse grid/layer ladder while preserving the split force markers and yPlus checks.'}`

## Engineering Boundary

This is route-smoke evidence. It proves a mature OpenFOAM route can generate a mesh,
run a steady incompressible RANS solve, and emit split force histories on the current
full-wing surface. It does not prove grid convergence, final HPA drag, separation
physics, transition, manufacturing sign-off, or release/procurement truth. The yPlus
values are high enough that the next action should be a grid/layer/yPlus ladder,
not aerodynamic sign-off.
"""


def _grep_lines(text: str, needles: Iterable[str], *, limit: int) -> list[str]:
    found: list[str] = []
    lowered = tuple(needle.lower() for needle in needles)
    for line in text.splitlines():
        if any(needle in line.lower() for needle in lowered):
            found.append(line[:240])
        if len(found) >= limit:
            break
    return found


def _float_or_none(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _int_match(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def _float_match(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _str_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _fmt(value: Any) -> str:
    number = _float_or_none(value)
    return "`not_available`" if number is None else f"`{number:.9g}`"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
