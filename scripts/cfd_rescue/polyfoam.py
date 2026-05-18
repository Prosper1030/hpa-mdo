from __future__ import annotations

import math
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cfd_rescue.swept_hexa import SweptHexaMesh, write_openfoam_poly_mesh  # noqa: E402
from run_wo006_phase3_openfoam_route_smoke import (  # noqa: E402
    AIR_DENSITY,
    KINEMATIC_VISCOSITY,
    VELOCITY_MPS,
    force_window_summary,
    fv_schemes_text,
    fv_solution_text,
    mesh_quality_dict_text,
    parse_boundary_patches,
    parse_check_mesh,
    parse_force_outputs,
    parse_yplus_outputs,
    run_case_command,
    transport_properties_text,
    turbulence_properties_text,
)


WALL_PATCH_REGEX = '"(wing_upper|wing_lower|tip_left|tip_right|te_wall|closure_wall)"'
FORCE_FUNCTIONS = {
    "primary": ("wing_upper", "wing_lower"),
    "total": ("wing_upper", "wing_lower", "tip_left", "tip_right", "te_wall", "closure_wall"),
    "tip_left": ("tip_left",),
    "tip_right": ("tip_right",),
    "te_wall": ("te_wall",),
    "closure_wall": ("closure_wall",),
}


def write_openfoam_case(
    case_dir: Path,
    *,
    mesh: SweptHexaMesh,
    ref_area: float,
    ref_length: float,
    ref_origin: tuple[float, float, float],
    aoa_deg: float,
    max_iterations: int,
    quality: Mapping[str, Any] | None = None,
) -> None:
    if case_dir.exists():
        shutil.rmtree(case_dir)
    for path in (case_dir / "system", case_dir / "constant", case_dir / "0"):
        path.mkdir(parents=True, exist_ok=True)
    write_openfoam_poly_mesh(case_dir / "constant" / "polyMesh", mesh)
    (case_dir / "system" / "controlDict").write_text(
        control_dict_text(
            ref_area=ref_area,
            ref_length=ref_length,
            ref_origin=ref_origin,
            aoa_deg=aoa_deg,
            max_iterations=max_iterations,
        ),
        encoding="utf-8",
    )
    (case_dir / "system" / "fvSchemes").write_text(fv_schemes_text(), encoding="utf-8")
    (case_dir / "system" / "fvSolution").write_text(fv_solution_text(), encoding="utf-8")
    (case_dir / "system" / "meshQualityDict").write_text(
        mesh_quality_dict_text(),
        encoding="utf-8",
    )
    (case_dir / "constant" / "transportProperties").write_text(
        transport_properties_text(),
        encoding="utf-8",
    )
    (case_dir / "constant" / "turbulenceProperties").write_text(
        turbulence_properties_text(),
        encoding="utf-8",
    )
    (case_dir / "0" / "U").write_text(u_field_text(aoa_deg=aoa_deg), encoding="utf-8")
    (case_dir / "0" / "p").write_text(p_field_text(), encoding="utf-8")
    (case_dir / "0" / "nuTilda").write_text(nu_tilda_field_text(), encoding="utf-8")
    (case_dir / "0" / "nut").write_text(nut_field_text(), encoding="utf-8")
    _write_json_like(
        case_dir / "swept_ogrid_mesh_metadata.json",
        {
            "mesh": mesh.metadata,
            "quality": quality,
            "physics": {
                "aoa_deg": aoa_deg,
                "velocity_mps": VELOCITY_MPS,
                "rho_kg_m3": AIR_DENSITY,
                "nu_m2_s": KINEMATIC_VISCOSITY,
                "ref_area_m2": ref_area,
                "ref_length_m": ref_length,
                "ref_origin_m": list(ref_origin),
            },
        },
    )


def run_checkmesh(
    case_dir: Path,
    *,
    openfoam_command: str,
    timeout_seconds: float = 300.0,
    full_geometry: bool = False,
    stop_on_failure: bool = True,
) -> dict[str, Any]:
    run_dir = _prepare_safe_run_dir(case_dir)
    commands = [("checkMesh", "checkMesh -meshQuality")]
    if full_geometry:
        commands.append(
            (
                "checkMesh_allGeometry",
                "checkMesh -allTopology -allGeometry -meshQuality",
            )
        )
    results: dict[str, Any] = {}
    for key, command in commands:
        completed = run_case_command(
            run_dir,
            openfoam_command=openfoam_command,
            command=command,
            log_name=f"log.{key}",
            timeout_seconds=timeout_seconds,
        )
        parsed = parse_check_mesh(run_dir / f"log.{key}")
        results[key] = {
            "command": command,
            "returncode": completed.returncode,
            "timed_out": completed.timed_out,
            "parsed": parsed,
        }
        if stop_on_failure and (completed.returncode != 0 or parsed.get("status") != "pass"):
            break
    _copy_run_dir_back(run_dir, case_dir)
    return {
        "status": "pass"
        if results and all(item["parsed"].get("status") == "pass" for item in results.values())
        else "fail",
        "commands": results,
    }


def run_simplefoam(
    case_dir: Path,
    *,
    openfoam_command: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    run_dir = _prepare_safe_run_dir(case_dir)
    completed = run_case_command(
        run_dir,
        openfoam_command=openfoam_command,
        command="simpleFoam",
        log_name="log.simpleFoam",
        timeout_seconds=timeout_seconds,
    )
    yplus_completed = None
    if completed.returncode == 0 and not completed.timed_out:
        yplus_completed = run_case_command(
            run_dir,
            openfoam_command=openfoam_command,
            command="simpleFoam -postProcess -func yPlus -latestTime",
            log_name="log.yPlus",
            timeout_seconds=min(timeout_seconds, 300.0),
        )
    _copy_run_dir_back(run_dir, case_dir)
    forces = parse_force_outputs(case_dir)
    yplus = parse_yplus_outputs(case_dir)
    return {
        "status": "pass"
        if completed.returncode == 0 and not completed.timed_out
        else "fail",
        "simpleFoam": {
            "returncode": completed.returncode,
            "timed_out": completed.timed_out,
            "log": str(case_dir / "log.simpleFoam"),
        },
        "yPlus_command": None
        if yplus_completed is None
        else {
            "returncode": yplus_completed.returncode,
            "timed_out": yplus_completed.timed_out,
            "log": str(case_dir / "log.yPlus"),
        },
        "forces": forces,
        "yplus": yplus,
        "force_stability": force_window_summary(
            forces.get("functions", {}).get("primary", {}).get("rows", [])
        ),
        "boundary_patches": parse_boundary_patches(
            case_dir / "constant" / "polyMesh" / "boundary"
        ),
    }


def _prepare_safe_run_dir(case_dir: Path) -> Path:
    safe_root = Path("/tmp/hpa_mdo_swept_cgrid_openfoam")
    run_dir = safe_root / case_dir.name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    safe_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(case_dir, run_dir)
    return run_dir


def _copy_run_dir_back(run_dir: Path, case_dir: Path) -> None:
    shutil.copytree(run_dir, case_dir, dirs_exist_ok=True)
    _normalize_openfoam_logs(case_dir)


def _normalize_openfoam_logs(case_dir: Path) -> None:
    for log_path in case_dir.glob("log.*"):
        if not log_path.is_file():
            continue
        text = log_path.read_text(encoding="utf-8", errors="replace")
        lines = [line.rstrip() for line in text.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def control_dict_text(
    *,
    ref_area: float,
    ref_length: float,
    ref_origin: tuple[float, float, float],
    aoa_deg: float,
    max_iterations: int,
) -> str:
    functions = "\n".join(
        force_coeff_function_text(
            name=f"forceCoeffs_{name}",
            patches=patches,
            ref_area=ref_area,
            ref_length=ref_length,
            ref_origin=ref_origin,
            aoa_deg=aoa_deg,
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
    aoa_deg: float,
) -> str:
    patch_list = " ".join(patches)
    drag = drag_dir(aoa_deg)
    lift = lift_dir(aoa_deg)
    return f"""    {name}
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        patches         ({patch_list});
        rho             rhoInf;
        rhoInf          {AIR_DENSITY:.9g};
        liftDir         ({lift[0]:.9g} {lift[1]:.9g} {lift[2]:.9g});
        dragDir         ({drag[0]:.9g} {drag[1]:.9g} {drag[2]:.9g});
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


def u_field_text(*, aoa_deg: float) -> str:
    u = inlet_velocity(aoa_deg)
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({u[0]:.9g} {u[1]:.9g} {u[2]:.9g});
boundaryField
{{
    farfield
    {{
        type            freestreamVelocity;
        freestreamValue $internalField;
    }}
    {WALL_PATCH_REGEX}
    {{
        type            noSlip;
    }}
}}
"""


def p_field_text() -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      p;
}}
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{{
    farfield
    {{
        type            freestreamPressure;
        freestreamValue $internalField;
    }}
    {WALL_PATCH_REGEX}
    {{
        type            zeroGradient;
    }}
}}
"""


def nu_tilda_field_text() -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      nuTilda;
}}
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform 4.0e-5;
boundaryField
{{
    farfield
    {{
        type            freestream;
        freestreamValue $internalField;
    }}
    {WALL_PATCH_REGEX}
    {{
        type            fixedValue;
        value           uniform 0;
    }}
}}
"""


def nut_field_text() -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      nut;
}}
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform 0;
boundaryField
{{
    farfield
    {{
        type            calculated;
        value           uniform 0;
    }}
    {WALL_PATCH_REGEX}
    {{
        type            nutUSpaldingWallFunction;
        value           uniform 0;
    }}
}}
"""


def inlet_velocity(aoa_deg: float) -> tuple[float, float, float]:
    alpha = math.radians(aoa_deg)
    return (VELOCITY_MPS * math.cos(alpha), 0.0, VELOCITY_MPS * math.sin(alpha))


def drag_dir(aoa_deg: float) -> tuple[float, float, float]:
    alpha = math.radians(aoa_deg)
    return (math.cos(alpha), 0.0, math.sin(alpha))


def lift_dir(aoa_deg: float) -> tuple[float, float, float]:
    alpha = math.radians(aoa_deg)
    return (-math.sin(alpha), 0.0, math.cos(alpha))


def _write_json_like(path: Path, payload: Mapping[str, Any]) -> None:
    import json

    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
