#!/usr/bin/env python3
"""Run same-mesh OpenFOAM architecture sensitivity cases for WO-006 HPA CFD.

The script creates lean continuations from the accepted Fine case, mutates only
the requested outlet/turbulence model settings, runs OpenFOAM from a no-space
temporary path, and summarizes the total-physical pressure/viscous force split.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CASE = (
    ROOT
    / "output/baseline_A_team_release/wo006_su2_baseline_validation"
    / "cfd_release_v0_hpa_solver_campaign_repair/fine_current_setup"
    / "openfoam_cases/fine/fullwing_artificial_tip_symmetry"
)
OUT_ROOT = (
    ROOT
    / "output/baseline_A_team_release/wo006_su2_baseline_validation"
    / "cfd_release_v0_hpa_model_architecture_sensitivity"
)
OPENFOAM = Path("/opt/homebrew/bin/openfoam")
TMP_ROOT = Path("/tmp/hpa_mdo_arch_openfoam")

RHO = 1.225
U_INF = 6.5
S_REF = 33.420059598
C_REF = 1.003721543
DRAG_DIR = (0.999995065, 0.0, 0.00314158749)
LIFT_DIR = (-0.00314158749, 0.0, 0.999995065)
Q_S = 0.5 * RHO * U_INF * U_INF * S_REF

TU = 0.005
C_MU = 0.09
K_INF = 1.5 * (U_INF * TU) ** 2
L_INF_LM = 0.001 * C_REF
OMEGA_INF_LM = math.sqrt(K_INF) / (C_MU**0.25 * L_INF_LM)
RE_THETA_T_INF = 879.6744
GAMMA_INF = 1.0

LATEST_TIME = "2000"
DEFAULT_END_TIME = 2200
FORCE_OBJECT = "forces_total_physical"


@dataclass(frozen=True)
class CaseSpec:
    name: str
    solver: str = "simpleFoam"
    outlet_pressure: str = "fixedValue"
    turbulence_model: str = "SpalartAllmaras"
    add_pref: bool = False
    relaxation: str = "baseline"
    attempt_note: str = ""


CASE_SPECS = {
    "sa_outlet_fixedValue0": CaseSpec(
        name="sa_outlet_fixedValue0",
        outlet_pressure="fixedValue",
        turbulence_model="SpalartAllmaras",
        attempt_note="accepted Fine SA baseline continued from time 2000",
    ),
    "sa_outlet_zeroGradient_pRef": CaseSpec(
        name="sa_outlet_zeroGradient_pRef",
        outlet_pressure="zeroGradient",
        turbulence_model="SpalartAllmaras",
        add_pref=True,
        attempt_note="outlet p zeroGradient with pRefCell/pRefValue",
    ),
    "sa_outlet_freestreamPressure": CaseSpec(
        name="sa_outlet_freestreamPressure",
        outlet_pressure="freestreamPressure",
        turbulence_model="SpalartAllmaras",
        attempt_note="outlet p set to farfield-consistent freestreamPressure",
    ),
    "sst_Tu0p5_L0p001c": CaseSpec(
        name="sst_Tu0p5_L0p001c",
        outlet_pressure="fixedValue",
        turbulence_model="kOmegaSST",
        relaxation="sst_conservative",
        attempt_note="SST bracket using Tu=0.5%, L=0.001c inlet turbulence",
    ),
    "lm_Tu0p5_L0p001c_r1": CaseSpec(
        name="lm_Tu0p5_L0p001c_r1",
        outlet_pressure="fixedValue",
        turbulence_model="kOmegaSSTLM",
        relaxation="lm_conservative",
        attempt_note="LM attempt 1 using low-Tu, L=0.001c and bounded conservative relaxation",
    ),
    "lm_Tu0p5_L0p001c_r2": CaseSpec(
        name="lm_Tu0p5_L0p001c_r2",
        outlet_pressure="fixedValue",
        turbulence_model="kOmegaSSTLM",
        relaxation="lm_very_conservative",
        attempt_note="LM attempt 2 with lower relaxation and first-order turbulence convection",
    ),
    "pimple_sst_Tu0p5_L0p001c": CaseSpec(
        name="pimple_sst_Tu0p5_L0p001c",
        solver="pimpleFoam",
        outlet_pressure="fixedValue",
        turbulence_model="kOmegaSST",
        relaxation="sst_conservative",
        attempt_note="URANS SST short-window probe using same mesh and Tu=0.5%, L=0.001c",
    ),
    "pimple_lm_Tu0p5_L0p001c_r2": CaseSpec(
        name="pimple_lm_Tu0p5_L0p001c_r2",
        solver="pimpleFoam",
        outlet_pressure="fixedValue",
        turbulence_model="kOmegaSSTLM",
        relaxation="lm_very_conservative",
        attempt_note="URANS LM short-window probe using r2 bounded setup",
    ),
}


def run(cmd: list[str], cwd: Path, log_path: Path | None = None) -> int:
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w") as log:
            log.write("$ " + " ".join(cmd) + "\n")
            log.flush()
            proc = subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
            return proc.returncode
    proc = subprocess.run(cmd, cwd=cwd)
    return proc.returncode


def replace_scalar(text: str, key: str, value: str) -> str:
    return re.sub(rf"(^\s*{re.escape(key)}\s+)([^;]+)(;)", rf"\g<1>{value}\3", text, flags=re.M)


def replace_patch_block(field_text: str, patch: str, block_body: str) -> str:
    pattern = re.compile(rf"(\n\s*{re.escape(patch)}\s*\{{)(.*?)(\n\s*\}})", re.S)
    replacement = rf"\1\n{block_body.rstrip()}\3"
    new_text, count = pattern.subn(replacement, field_text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not replace patch block {patch}")
    return new_text


def add_pref_to_simple(fv_solution: Path) -> None:
    text = fv_solution.read_text()
    if "pRefCell" in text and "pRefValue" in text:
        return
    pattern = re.compile(r"(SIMPLE\s*\{\n)")
    text, count = pattern.subn(r"\1    pRefCell       0;\n    pRefValue      0;\n", text, count=1)
    if count != 1:
        raise RuntimeError("Could not add pRefCell/pRefValue to SIMPLE dictionary")
    fv_solution.write_text(text)


def copy_lean_source(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for child in ("constant", "system", LATEST_TIME):
        shutil.copytree(SOURCE_CASE / child, dst / child, symlinks=False)
    post = dst / "postProcessing"
    if post.exists():
        shutil.rmtree(post)


def update_control_dict(case_dir: Path, end_time: float, solver: str) -> None:
    path = case_dir / "system/controlDict"
    text = path.read_text()
    text = replace_scalar(text, "application", solver)
    text = replace_scalar(text, "endTime", f"{end_time:g}")
    text = replace_scalar(text, "writeInterval", "10" if solver == "pimpleFoam" else "100")
    text = replace_scalar(text, "purgeWrite", "2")
    if solver == "pimpleFoam":
        text = replace_scalar(text, "deltaT", "0.02")
        additions = {
            "adjustTimeStep": "yes",
            "maxCo": "1",
            "maxDeltaT": "0.02",
        }
        for key, value in additions.items():
            if not re.search(rf"^\s*{key}\s+", text, flags=re.M):
                text = text.replace("writeInterval   10;\n", f"writeInterval   10;\n{key:<16}{value};\n", 1)
    path.write_text(text)


def update_outlet_pressure(case_dir: Path, outlet_pressure: str) -> None:
    path = case_dir / LATEST_TIME / "p"
    text = path.read_text()
    if outlet_pressure == "fixedValue":
        body = "        type            fixedValue;\n        value           uniform 0;"
    elif outlet_pressure == "zeroGradient":
        body = "        type            zeroGradient;"
    elif outlet_pressure == "freestreamPressure":
        body = (
            "        type            freestreamPressure;\n"
            "        freestreamValue uniform 0;\n"
            "        value           uniform 0;"
        )
    else:
        raise ValueError(outlet_pressure)
    path.write_text(replace_patch_block(text, "outlet", body))


def write_turbulence_properties(case_dir: Path, model: str) -> None:
    (case_dir / "constant/turbulenceProperties").write_text(
        """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}
simulationType          RAS;
RAS
{
    RASModel            %s;
    turbulence          on;
    printCoeffs         on;
}
"""
        % model
    )


def scalar_field_text(name: str, dimensions: str, internal: str, boundaries: dict[str, str]) -> str:
    patch_order = [
        "airfoil_upper",
        "airfoil_lower",
        "te_wall",
        "outlet",
        "farfield",
        "physical_tip_right",
        "physical_tip_left",
    ]
    lines = [
        "FoamFile",
        "{",
        "    version     2.0;",
        "    format      ascii;",
        "    class       volScalarField;",
        f'    location    "{LATEST_TIME}";',
        f"    object      {name};",
        "}",
        f"dimensions      {dimensions};",
        f"internalField   {internal};",
        "boundaryField",
        "{",
    ]
    for patch in patch_order:
        lines.append(f"    {patch}")
        lines.append("    {")
        lines.extend(boundaries[patch].splitlines())
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_sst_fields(case_dir: Path) -> None:
    time_dir = case_dir / LATEST_TIME
    k = f"{K_INF:.9g}"
    omega = f"{OMEGA_INF_LM:.12g}"
    walls = {
        "airfoil_upper",
        "airfoil_lower",
        "te_wall",
        "physical_tip_right",
        "physical_tip_left",
    }
    k_boundaries = {}
    omega_boundaries = {}
    nut_boundaries = {}
    for patch in [
        "airfoil_upper",
        "airfoil_lower",
        "te_wall",
        "outlet",
        "farfield",
        "physical_tip_right",
        "physical_tip_left",
    ]:
        if patch in walls:
            k_boundaries[patch] = "        type            fixedValue;\n        value           uniform 0;"
            omega_boundaries[patch] = f"        type            omegaWallFunction;\n        value           uniform {omega};"
            nut_boundaries[patch] = "        type            nutkWallFunction;\n        value           uniform 0;"
        elif patch == "outlet":
            k_boundaries[patch] = f"        type            inletOutlet;\n        inletValue      uniform {k};\n        value           uniform {k};"
            omega_boundaries[patch] = f"        type            inletOutlet;\n        inletValue      uniform {omega};\n        value           uniform {omega};"
            nut_boundaries[patch] = "        type            calculated;\n        value           uniform 0;"
        else:
            k_boundaries[patch] = f"        type            freestream;\n        freestreamValue uniform {k};\n        value           uniform {k};"
            omega_boundaries[patch] = f"        type            freestream;\n        freestreamValue uniform {omega};\n        value           uniform {omega};"
            nut_boundaries[patch] = "        type            calculated;\n        value           uniform 0;"
    (time_dir / "k").write_text(scalar_field_text("k", "[0 2 -2 0 0 0 0]", f"uniform {k}", k_boundaries))
    (time_dir / "omega").write_text(
        scalar_field_text("omega", "[0 0 -1 0 0 0 0]", f"uniform {omega}", omega_boundaries)
    )
    (time_dir / "nut").write_text(
        scalar_field_text("nut", "[0 2 -1 0 0 0 0]", "uniform 0", nut_boundaries)
    )


def write_lm_fields(case_dir: Path) -> None:
    write_sst_fields(case_dir)
    time_dir = case_dir / LATEST_TIME
    gamma = f"{GAMMA_INF:g}"
    retheta = f"{RE_THETA_T_INF:g}"
    walls = {
        "airfoil_upper",
        "airfoil_lower",
        "te_wall",
        "physical_tip_right",
        "physical_tip_left",
    }
    gamma_boundaries = {}
    retheta_boundaries = {}
    for patch in [
        "airfoil_upper",
        "airfoil_lower",
        "te_wall",
        "outlet",
        "farfield",
        "physical_tip_right",
        "physical_tip_left",
    ]:
        if patch in walls:
            gamma_boundaries[patch] = "        type            zeroGradient;"
            retheta_boundaries[patch] = "        type            zeroGradient;"
        elif patch == "outlet":
            gamma_boundaries[patch] = f"        type            inletOutlet;\n        inletValue      uniform {gamma};\n        value           uniform {gamma};"
            retheta_boundaries[patch] = f"        type            inletOutlet;\n        inletValue      uniform {retheta};\n        value           uniform {retheta};"
        else:
            gamma_boundaries[patch] = f"        type            freestream;\n        freestreamValue uniform {gamma};\n        value           uniform {gamma};"
            retheta_boundaries[patch] = f"        type            freestream;\n        freestreamValue uniform {retheta};\n        value           uniform {retheta};"
    (time_dir / "gammaInt").write_text(
        scalar_field_text("gammaInt", "[0 0 0 0 0 0 0]", f"uniform {gamma}", gamma_boundaries)
    )
    (time_dir / "ReThetat").write_text(
        scalar_field_text("ReThetat", "[0 0 0 0 0 0 0]", f"uniform {retheta}", retheta_boundaries)
    )


def write_sst_schemes(
    case_dir: Path, first_order_turbulence: bool = False, transient: bool = False
) -> None:
    turbulence_scheme = "bounded Gauss upwind" if first_order_turbulence else "bounded Gauss linearUpwind grad"
    ddt_scheme = "Euler" if transient else "steadyState"
    (case_dir / "system/fvSchemes").write_text(
        f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}}
ddtSchemes
{{
    default         {ddt_scheme};
}}
gradSchemes
{{
    default         Gauss linear;
}}
divSchemes
{{
    default                         none;
    div(phi,U)                      bounded Gauss linearUpwind grad(U);
    div(div(phi,U))                 Gauss linear;
    turbulence                      {turbulence_scheme};
    div(phi,k)                      $turbulence;
    div(phi,omega)                  $turbulence;
    div((nuEff*dev2(T(grad(U)))))   Gauss linear;
}}
laplacianSchemes
{{
    default         Gauss linear corrected;
}}
interpolationSchemes
{{
    default         linear;
}}
snGradSchemes
{{
    default         corrected;
}}
wallDist
{{
    method          meshWave;
}}
"""
    )


def write_lm_schemes(
    case_dir: Path, first_order_turbulence: bool = False, transient: bool = False
) -> None:
    write_sst_schemes(case_dir, first_order_turbulence, transient)
    path = case_dir / "system/fvSchemes"
    text = path.read_text()
    text = text.replace(
        "    div(phi,omega)                  $turbulence;\n",
        "    div(phi,omega)                  $turbulence;\n"
        "    div(phi,gammaInt)               $turbulence;\n"
        "    div(phi,ReThetat)               $turbulence;\n",
    )
    path.write_text(text)


def write_sst_solution(case_dir: Path, u_relax: float, turb_relax: float, p_relax: float) -> None:
    (case_dir / "system/fvSolution").write_text(
        f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}}
solvers
{{
    Phi
    {{
        solver          GAMG;
        smoother        DIC;
        tolerance       1e-06;
        relTol          0.01;
    }}

    p
    {{
        solver          GAMG;
        tolerance       1e-06;
        relTol          0.1;
        smoother        GaussSeidel;
    }}
    U
    {{
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0.1;
    }}
    "(k|omega)"
    {{
        solver          smoothSolver;
        smoother        symGaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0.1;
        maxIter         20;
    }}
}}
SIMPLE
{{
    nNonOrthogonalCorrectors 2;
    residualControl
    {{
        p               1e-5;
        U               1e-5;
        "(k|omega)"     1e-4;
    }}
}}
relaxationFactors
{{
    fields
    {{
        p               {p_relax:g};
    }}
    equations
    {{
        U               {u_relax:g};
        k               {turb_relax:g};
        omega           {turb_relax:g};
    }}
}}

potentialFlow
{{
    nNonOrthogonalCorrectors 4;
}}
"""
    )


def write_lm_solution(case_dir: Path, u_relax: float, turb_relax: float, p_relax: float) -> None:
    write_sst_solution(case_dir, u_relax, turb_relax, p_relax)
    path = case_dir / "system/fvSolution"
    text = path.read_text()
    text = text.replace('"(k|omega)"', '"(k|omega|gammaInt|ReThetat)"')
    text = text.replace('"(k|omega)"     1e-4;', '"(k|omega|gammaInt|ReThetat)" 1e-4;')
    text = text.replace(
        "        omega           {0:g};\n".format(turb_relax),
        "        omega           {0:g};\n"
        "        gammaInt        {0:g};\n"
        "        ReThetat        {0:g};\n".format(turb_relax),
    )
    path.write_text(text)


def convert_solution_to_pimple(case_dir: Path) -> None:
    path = case_dir / "system/fvSolution"
    text = path.read_text()
    if "pFinal" not in text:
        text = text.replace(
            "    U\n    {\n        solver          smoothSolver;",
            "    pFinal\n    {\n        $p;\n        relTol          0;\n    }\n    U\n    {\n        solver          smoothSolver;",
            1,
        )
    if "UFinal" not in text:
        text = text.replace(
            '    "(k|omega',
            "    UFinal\n    {\n        $U;\n        relTol          0;\n    }\n    \"(k|omega",
            1,
        )
    final_scalar_solver = """    kFinal
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0;
        maxIter         20;
    }
    omegaFinal
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0;
        maxIter         20;
    }
    gammaIntFinal
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0;
        maxIter         20;
    }
    ReThetatFinal
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0;
        maxIter         20;
    }
"""
    if "omegaFinal" not in text:
        text = text.replace("}\nPIMPLE", final_scalar_solver + "}\nPIMPLE", 1)
    text = re.sub(
        r"SIMPLE\s*\{.*?\}\nrelaxationFactors",
        (
            "PIMPLE\n"
            "{\n"
            "    nOuterCorrectors 1;\n"
            "    nCorrectors     2;\n"
            "    nNonOrthogonalCorrectors 1;\n"
            "}\n"
            "relaxationFactors"
        ),
        text,
        flags=re.S,
    )
    if "omegaFinal" not in text:
        text = text.replace("}\nPIMPLE", final_scalar_solver + "}\nPIMPLE", 1)
    path.write_text(text)


def write_decompose_dict(case_dir: Path, np: int) -> None:
    (case_dir / "system/decomposeParDict").write_text(
        f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      decomposeParDict;
}}
numberOfSubdomains {np};
method          scotch;
"""
    )


def configure_case(case_dir: Path, spec: CaseSpec, end_time: float, np: int) -> None:
    update_control_dict(case_dir, end_time, spec.solver)
    update_outlet_pressure(case_dir, spec.outlet_pressure)
    if spec.add_pref:
        add_pref_to_simple(case_dir / "system/fvSolution")
    if spec.turbulence_model != "SpalartAllmaras":
        write_turbulence_properties(case_dir, spec.turbulence_model)
        first_order_turb = spec.relaxation == "lm_very_conservative"
        if spec.turbulence_model == "kOmegaSST":
            write_sst_fields(case_dir)
            write_sst_schemes(case_dir, first_order_turbulence=False, transient=spec.solver == "pimpleFoam")
            write_sst_solution(case_dir, u_relax=0.45, turb_relax=0.3, p_relax=0.2)
            if spec.solver == "pimpleFoam":
                convert_solution_to_pimple(case_dir)
        elif spec.turbulence_model == "kOmegaSSTLM":
            write_lm_fields(case_dir)
            write_lm_schemes(
                case_dir,
                first_order_turbulence=first_order_turb,
                transient=spec.solver == "pimpleFoam",
            )
            if spec.relaxation == "lm_very_conservative":
                write_lm_solution(case_dir, u_relax=0.3, turb_relax=0.18, p_relax=0.15)
            else:
                write_lm_solution(case_dir, u_relax=0.4, turb_relax=0.25, p_relax=0.18)
            if spec.solver == "pimpleFoam":
                convert_solution_to_pimple(case_dir)
        else:
            raise ValueError(spec.turbulence_model)
    write_decompose_dict(case_dir, np)
    manifest = {
        "case": spec.name,
        "source_case": str(SOURCE_CASE),
        "same_mesh": True,
        "start_time": LATEST_TIME,
        "end_time": end_time,
        "solver": spec.solver,
        "outlet_pressure": spec.outlet_pressure,
        "turbulence_model": spec.turbulence_model,
        "parallel_subdomains": np,
        "note": spec.attempt_note,
        "reference": {
            "rho": RHO,
            "U_inf": U_INF,
            "S_ref": S_REF,
            "c_ref": C_REF,
            "drag_dir": DRAG_DIR,
            "lift_dir": LIFT_DIR,
        },
        "transition_inlet": {
            "Tu": TU,
            "k": K_INF,
            "L_for_LM": L_INF_LM,
            "omega_for_LM": OMEGA_INF_LM,
            "gammaInt": GAMMA_INF,
            "ReThetat": RE_THETA_T_INF,
        },
    }
    (case_dir / "architecture_sensitivity_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def openfoam_cmd(shell_cmd: str) -> list[str]:
    return [str(OPENFOAM), "-c", shell_cmd]


def run_openfoam_case(case_dir: Path, spec: CaseSpec, np: int) -> dict[str, object]:
    status: dict[str, object] = {"case": spec.name, "ok": False}
    t0 = time.time()
    dry_log = case_dir / f"log.dry_run_{spec.name}.txt"
    rc = run(openfoam_cmd(f"cd {case_dir} && {spec.solver} -dry-run"), cwd=Path("/tmp"), log_path=dry_log)
    status["dry_run_returncode"] = rc
    if rc != 0:
        status["failure_stage"] = "dry-run"
        status["elapsed_s"] = time.time() - t0
        return status

    if np <= 1:
        solve_log = case_dir / f"log.{spec.solver}_{spec.name}.txt"
        rc = run(openfoam_cmd(f"cd {case_dir} && {spec.solver}"), cwd=Path("/tmp"), log_path=solve_log)
        status["solve_returncode"] = rc
        if rc != 0:
            status["failure_stage"] = spec.solver
            status["elapsed_s"] = time.time() - t0
            return status
        status["ok"] = True
        status["elapsed_s"] = time.time() - t0
        return status

    decomp_log = case_dir / f"log.decomposePar_{spec.name}.txt"
    rc = run(openfoam_cmd(f"cd {case_dir} && decomposePar -force -latestTime"), cwd=Path("/tmp"), log_path=decomp_log)
    status["decompose_returncode"] = rc
    if rc != 0:
        status["failure_stage"] = "decomposePar"
        status["elapsed_s"] = time.time() - t0
        return status

    solve_log = case_dir / f"log.{spec.solver}_{spec.name}.txt"
    rc = run(
        openfoam_cmd(f"cd {case_dir} && mpirun -np {np} {spec.solver} -parallel"),
        cwd=Path("/tmp"),
        log_path=solve_log,
    )
    status["solve_returncode"] = rc
    if rc != 0:
        status["failure_stage"] = spec.solver
        status["elapsed_s"] = time.time() - t0
        return status

    recon_log = case_dir / f"log.reconstructPar_{spec.name}.txt"
    rc = run(openfoam_cmd(f"cd {case_dir} && reconstructPar -latestTime"), cwd=Path("/tmp"), log_path=recon_log)
    status["reconstruct_returncode"] = rc
    if rc != 0:
        status["failure_stage"] = "reconstructPar"
        status["elapsed_s"] = time.time() - t0
        return status

    merge_processor_post_processing(case_dir)
    for processor_dir in case_dir.glob("processor*"):
        if processor_dir.is_dir():
            shutil.rmtree(processor_dir)
    status["ok"] = True
    status["elapsed_s"] = time.time() - t0
    return status


def merge_processor_post_processing(case_dir: Path) -> None:
    root_post = case_dir / "postProcessing"
    root_post.mkdir(exist_ok=True)
    for processor_dir in sorted(case_dir.glob("processor*")):
        proc_post = processor_dir / "postProcessing"
        if not proc_post.exists():
            continue
        for child in proc_post.iterdir():
            dest = root_post / child.name
            if dest.exists():
                continue
            if child.is_dir():
                shutil.copytree(child, dest)
            else:
                shutil.copy2(child, dest)


def parse_force_file(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for line in path.read_text(errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 10:
            continue
        vals = [float(x) for x in parts[:10]]
        time_val = vals[0]
        total = vals[1:4]
        pressure = vals[4:7]
        viscous = vals[7:10]
        cd_total = dot(total, DRAG_DIR) / Q_S
        cd_pressure = dot(pressure, DRAG_DIR) / Q_S
        cd_viscous = dot(viscous, DRAG_DIR) / Q_S
        cl_total = dot(total, LIFT_DIR) / Q_S
        rows.append(
            {
                "time": time_val,
                "CD_total": cd_total,
                "CD_pressure": cd_pressure,
                "CD_viscous": cd_viscous,
                "CL": cl_total,
            }
        )
    return rows


def parse_force_coeffs_log(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    current_time: float | None = None
    in_block = False
    pending: dict[str, float] = {}
    time_re = re.compile(r"^Time =\s+([-+0-9.eE]+)")
    coeff_re = re.compile(r"^\s*(Cd|Cl):\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)")
    for line in path.read_text(errors="ignore").splitlines():
        time_match = time_re.match(line)
        if time_match:
            current_time = float(time_match.group(1))
            continue
        if line.strip() == "forceCoeffs forceCoeffs_total_physical write:":
            in_block = True
            pending = {}
            continue
        if not in_block:
            continue
        coeff_match = coeff_re.match(line)
        if coeff_match:
            name = coeff_match.group(1)
            total = float(coeff_match.group(2))
            pressure = float(coeff_match.group(3))
            viscous = float(coeff_match.group(4))
            if name == "Cd":
                pending["CD_total"] = total
                pending["CD_pressure"] = pressure
                pending["CD_viscous"] = viscous
            elif name == "Cl":
                pending["CL"] = total
        if {"CD_total", "CD_pressure", "CD_viscous", "CL"}.issubset(pending) and current_time is not None:
            rows.append(
                {
                    "time": current_time,
                    "CD_total": pending["CD_total"],
                    "CD_pressure": pending["CD_pressure"],
                    "CD_viscous": pending["CD_viscous"],
                    "CL": pending["CL"],
                }
            )
            in_block = False
            pending = {}
    return rows


def dot(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def summarize_case(case_dir: Path, spec: CaseSpec, status: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {
        "case": spec.name,
        "solver": spec.solver,
        "outlet_pressure": spec.outlet_pressure,
        "turbulence_model": spec.turbulence_model,
        "note": spec.attempt_note,
        "ok": bool(status.get("ok")),
        "failure_stage": status.get("failure_stage", ""),
        "elapsed_s": status.get("elapsed_s", ""),
    }
    force_files = sorted((case_dir / "postProcessing" / FORCE_OBJECT).glob("*/force.dat"))
    rows: list[dict[str, float]] = []
    if force_files:
        force_file = force_files[-1]
        rows = parse_force_file(force_file)
        summary["force_file"] = str(force_file)
    else:
        log_file = case_dir / f"log.{spec.solver}_{spec.name}.txt"
        if log_file.exists():
            rows = parse_force_coeffs_log(log_file)
            summary["force_file"] = str(log_file)
            summary["force_source"] = "solver_log_forceCoeffs_total_physical"
    if not rows:
        summary["force_file"] = summary.get("force_file", "")
        return summary
    summary["n_force_rows"] = len(rows)
    last = rows[-1]
    window = rows[-100:] if len(rows) >= 100 else rows
    for key in ("CD_total", "CD_pressure", "CD_viscous", "CL"):
        vals = [float(r[key]) for r in window]
        summary[f"{key}_last"] = last[key]
        summary[f"{key}_mean_final_window"] = sum(vals) / len(vals)
        summary[f"{key}_range_final_window"] = max(vals) - min(vals)
    summary["final_time"] = last["time"]
    summary["stable_force_window"] = (
        float(summary.get("CD_total_range_final_window", 1.0)) < 5e-4
        and float(summary.get("CL_range_final_window", 1.0)) < 8e-3
    )
    return summary


def write_summary(rows: list[dict[str, object]]) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_ROOT / "model_architecture_sensitivity_summary.csv"
    keys = [
        "case",
        "solver",
        "outlet_pressure",
        "turbulence_model",
        "ok",
        "failure_stage",
        "stable_force_window",
        "final_time",
        "CD_pressure_last",
        "CD_pressure_mean_final_window",
        "CD_pressure_range_final_window",
        "CD_viscous_last",
        "CD_viscous_mean_final_window",
        "CD_viscous_range_final_window",
        "CD_total_last",
        "CD_total_mean_final_window",
        "CD_total_range_final_window",
        "CL_last",
        "CL_mean_final_window",
        "CL_range_final_window",
        "elapsed_s",
        "n_force_rows",
        "force_file",
        "note",
    ]
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in keys})
    (OUT_ROOT / "model_architecture_sensitivity_summary.json").write_text(json.dumps(rows, indent=2) + "\n")


def copy_back(run_case: Path, dest_case: Path) -> None:
    dest_case.parent.mkdir(parents=True, exist_ok=True)
    if dest_case.exists():
        shutil.rmtree(dest_case)
    shutil.copytree(run_case, dest_case)


def run_cases(case_names: list[str], end_time: float, np: int, keep_tmp: bool) -> int:
    if not SOURCE_CASE.exists():
        raise FileNotFoundError(SOURCE_CASE)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "openfoam_cases").mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, object]] = []
    if (OUT_ROOT / "model_architecture_sensitivity_summary.json").exists():
        try:
            summaries = json.loads((OUT_ROOT / "model_architecture_sensitivity_summary.json").read_text())
        except json.JSONDecodeError:
            summaries = []
    by_case = {str(item.get("case")): item for item in summaries}

    for name in case_names:
        spec = CASE_SPECS[name]
        run_case = TMP_ROOT / name
        dest_case = OUT_ROOT / "openfoam_cases" / name
        copy_lean_source(run_case)
        configure_case(run_case, spec, end_time, np)
        status = run_openfoam_case(run_case, spec, np)
        (run_case / "architecture_sensitivity_status.json").write_text(json.dumps(status, indent=2) + "\n")
        copy_back(run_case, dest_case)
        summary = summarize_case(dest_case, spec, status)
        by_case[name] = summary
        write_summary([by_case[k] for k in sorted(by_case)])
        if not keep_tmp and run_case.exists():
            shutil.rmtree(run_case)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        nargs="+",
        default=[
            "sa_outlet_fixedValue0",
            "sa_outlet_zeroGradient_pRef",
            "sa_outlet_freestreamPressure",
            "sst_Tu0p5_L0p001c",
            "lm_Tu0p5_L0p001c_r1",
        ],
        choices=sorted(CASE_SPECS),
    )
    parser.add_argument("--end-time", type=float, default=DEFAULT_END_TIME)
    parser.add_argument("--np", type=int, default=1)
    parser.add_argument("--keep-tmp", action="store_true")
    args = parser.parse_args(argv)
    return run_cases(args.cases, args.end_time, args.np, args.keep_tmp)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
