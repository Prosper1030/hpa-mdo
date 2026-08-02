#!/usr/bin/env python3
"""Run same-mesh OpenFOAM architecture sensitivity cases for WO-006 HPA CFD.

The script creates lean continuations from the accepted Fine case, mutates only
the requested outlet/turbulence model settings, runs OpenFOAM from a no-space
temporary path, and summarizes the total-physical pressure/viscous force split.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import filecmp
import json
import math
import os
import re
import shlex
import signal
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
SCRATCH_BACKING_ROOT = ROOT.parent / "hpa-cfd-tmp/architecture_sensitivity"
TMP_ROOT = Path("/Volumes/hpa-cfd-tmp/architecture_sensitivity")

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
FORCE_OBJECT = "forces_total_physical"
MIN_FORCE_WINDOW_ROWS = 100
MAX_STEADY_CHECKPOINT_INTERVAL = 25
DEFAULT_MEMORY_FRACTION = 0.65
DEFAULT_MAX_RSS_GB = 12.0
DEFAULT_MIN_SCRATCH_FREE_GB = 20.0
MAX_FORCE_RELATIVE_SPAN = 0.01
MAX_CM_PITCH_ABSOLUTE_SPAN = 0.005


@dataclass(frozen=True)
class CaseSpec:
    name: str
    solver: str = "simpleFoam"
    outlet_pressure: str = "fixedValue"
    turbulence_model: str = "SpalartAllmaras"
    add_pref: bool = False
    relaxation: str = "baseline"
    warm_start_source: str | None = None
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
    "lm_warm_from_sst_Tu0p5_L0p001c": CaseSpec(
        name="lm_warm_from_sst_Tu0p5_L0p001c",
        outlet_pressure="fixedValue",
        turbulence_model="kOmegaSSTLM",
        relaxation="lm_very_conservative",
        warm_start_source="sst_Tu0p5_L0p001c",
        attempt_note="LM warm start preserving the qualified same-mesh SST U/p/phi/k/omega/nut fields",
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


def physical_memory_bytes() -> int | None:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    total = pages * page_size
    return total if total > 0 else None


def default_max_rss_gb() -> float:
    total = physical_memory_bytes()
    if total is None:
        return DEFAULT_MAX_RSS_GB
    return min(DEFAULT_MAX_RSS_GB, total * DEFAULT_MEMORY_FRACTION / 1.0e9)


def process_tree_rss_bytes(root_pid: int) -> int:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,rss="],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0
    rows: dict[int, tuple[int, int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        try:
            pid, ppid, rss_kib = map(int, parts)
        except ValueError:
            continue
        rows[pid] = (ppid, rss_kib)
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (ppid, _) in rows.items():
            if ppid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return 1024 * sum(rows.get(pid, (0, 0))[1] for pid in descendants)


def run_monitored(
    cmd: list[str],
    cwd: Path,
    log_path: Path,
    max_rss_bytes: int,
    poll_interval_s: float = 2.0,
) -> dict[str, object]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    peak_rss = 0
    stopped_by_memory_guard = False
    with log_path.open("w") as log:
        log.write("$ " + " ".join(cmd) + "\n")
        log.write(f"# max process-tree RSS: {max_rss_bytes / 1.0e9:.3f} GB\n")
        log.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        while proc.poll() is None:
            rss = process_tree_rss_bytes(proc.pid)
            peak_rss = max(peak_rss, rss)
            if max_rss_bytes > 0 and rss > max_rss_bytes:
                stopped_by_memory_guard = True
                log.write(
                    f"\n# memory guard: RSS {rss / 1.0e9:.3f} GB exceeded "
                    f"{max_rss_bytes / 1.0e9:.3f} GB\n"
                )
                log.flush()
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                break
            time.sleep(poll_interval_s)
        returncode = proc.wait()
    return {
        "returncode": returncode,
        "peak_rss_bytes": peak_rss,
        "max_rss_bytes": max_rss_bytes,
        "stopped_by_memory_guard": stopped_by_memory_guard,
    }


def replace_scalar(text: str, key: str, value: str) -> str:
    # controlDict top-level entries precede the functions dictionary.  Replacing
    # only the first match prevents checkpoint settings from silently changing
    # identically named function-object entries.
    return re.sub(
        rf"(^\s*{re.escape(key)}\s+)([^;]+)(;)",
        rf"\g<1>{value}\3",
        text,
        count=1,
        flags=re.M,
    )


def normalize_function_object_write_intervals(text: str) -> str:
    """Keep diagnostic objects at per-event cadence without touching checkpoints."""
    match = re.search(r"^\s*functions\s*\{", text, flags=re.M)
    if not match:
        return text
    prefix = text[: match.start()]
    functions = text[match.start() :]
    functions = re.sub(
        r"(^\s*writeInterval\s+)([^;]+)(;)",
        r"\g<1>1\3",
        functions,
        flags=re.M,
    )
    return prefix + functions


def remove_duplicate_shear_yplus_function(text: str) -> str:
    """Remove a second yPlus object; v2512 gives both objects the same registry name."""
    return re.sub(
        r"\n\s*yPlusShear\s*\{.*?\n\s*\}\s*(?=\n)",
        "",
        text,
        count=1,
        flags=re.S,
    )


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


def numeric_time_dirs(case_dir: Path) -> list[Path]:
    candidates: list[tuple[float, Path]] = []
    for child in case_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            value = float(child.name)
        except ValueError:
            continue
        candidates.append((value, child))
    return [path for _, path in sorted(candidates)]


def latest_time_name(case_dir: Path) -> str:
    time_dirs = numeric_time_dirs(case_dir)
    if not time_dirs:
        raise RuntimeError(f"No numeric time directory in {case_dir}")
    return time_dirs[-1].name


def copy_lean_case(
    source: Path,
    dst: Path,
    include_post_processing: bool = False,
    include_logs: bool = True,
) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    start_time = latest_time_name(source)
    for child in ("constant", "system", start_time):
        shutil.copytree(source / child, dst / child, symlinks=False)
    if include_post_processing and (source / "postProcessing").exists():
        shutil.copytree(source / "postProcessing", dst / "postProcessing", symlinks=False)
    if include_logs:
        for log_path in source.glob("log.*"):
            if log_path.is_file():
                shutil.copy2(log_path, dst / log_path.name)


def validate_sst_warm_start(case_dir: Path, time_name: str) -> None:
    expected = {
        "U": ("volVectorField", "[0 1 -1 0 0 0 0]"),
        "p": ("volScalarField", "[0 2 -2 0 0 0 0]"),
        "phi": ("surfaceScalarField", "[0 3 -1 0 0 0 0]"),
        "k": ("volScalarField", "[0 2 -2 0 0 0 0]"),
        "omega": ("volScalarField", "[0 0 -1 0 0 0 0]"),
        "nut": ("volScalarField", "[0 2 -1 0 0 0 0]"),
    }
    missing = [name for name in expected if not (case_dir / time_name / name).exists()]
    if missing:
        raise RuntimeError(f"SST warm start is missing required fields at {time_name}: {missing}")
    nonfinite = re.compile(rb"(?i)(?<![A-Za-z])[-+]?(?:nan|inf(?:inity)?)(?![A-Za-z])")
    for name, (field_class, dimensions) in expected.items():
        path = case_dir / time_name / name
        header = bytearray()
        with path.open("rb") as stream:
            for raw in stream:
                if len(header) < 8192:
                    header.extend(raw)
                if nonfinite.search(raw):
                    raise RuntimeError(f"SST warm-start field contains non-finite data: {path}")
        header_text = header.decode(errors="replace")
        if not re.search(rf"\bclass\s+{re.escape(field_class)}\s*;", header_text):
            raise RuntimeError(f"Unexpected OpenFOAM class for SST warm-start field: {path}")
        if not re.search(rf"\bdimensions\s+{re.escape(dimensions)}\s*;", header_text):
            raise RuntimeError(f"Unexpected dimensions for SST warm-start field: {path}")


def remove_derived_restart_fields(case_dir: Path, time_name: str) -> None:
    """Drop regenerable function-object fields from the scratch restart only."""
    time_dir = case_dir / time_name
    for path in time_dir.iterdir():
        if path.is_file() and (path.name == "yPlus" or path.name.endswith(":yPlus")):
            path.unlink()


def require_qualified_sst_summary(summary: dict[str, object], source_spec: CaseSpec) -> None:
    """Reject warm starts from unevolved or force-unqualified SST checkpoints."""
    qualified = bool(
        source_spec.turbulence_model == "kOmegaSST"
        and summary.get("ok")
        and summary.get("stable_force_window")
        and summary.get("finite_force_history")
        and summary.get("contiguous_final_window")
        and summary.get("force_reaches_latest_checkpoint")
        and int(summary.get("n_force_rows", 0)) >= MIN_FORCE_WINDOW_ROWS
        and float(summary.get("latest_checkpoint", -math.inf)) > float(LATEST_TIME)
    )
    if not qualified:
        raise RuntimeError("SST-to-LM warm start requires a qualified, evolved SST final-100 checkpoint")


def validate_warm_start_source_qualification(source: Path, source_spec: CaseSpec) -> None:
    status_path = source / "architecture_sensitivity_status.json"
    if not status_path.exists():
        raise RuntimeError(f"SST warm-start source has no controller status: {source}")
    status = json.loads(status_path.read_text())
    require_qualified_sst_summary(summarize_case(source, source_spec, status), source_spec)
    manifest_path = source / "architecture_sensitivity_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    model_text = (source / "constant/turbulenceProperties").read_text()
    if manifest.get("turbulence_model") != "kOmegaSST" or not re.search(
        r"\bRASModel\s+kOmegaSST\s*;", model_text
    ):
        raise RuntimeError("Warm-start source manifest/dictionary is not kOmegaSST")
    for name in ("boundary", "points", "faces", "owner", "neighbour"):
        if not filecmp.cmp(
            source / "constant/polyMesh" / name,
            SOURCE_CASE / "constant/polyMesh" / name,
            shallow=False,
        ):
            raise RuntimeError(f"Warm-start source mesh differs from accepted Fine mesh: {name}")


def checkpoint_interval(start_time: float, end_time: float, maximum: int = MAX_STEADY_CHECKPOINT_INTERVAL) -> int:
    duration = end_time - start_time
    rounded = int(round(duration))
    if duration <= 0 or not math.isclose(duration, rounded, abs_tol=1.0e-9):
        raise ValueError("Steady continuation duration must be a positive whole number of iterations")
    for interval in range(min(maximum, rounded), 0, -1):
        if rounded % interval == 0:
            return interval
    return 1


def update_control_dict(case_dir: Path, start_time: float, end_time: float, solver: str) -> None:
    path = case_dir / "system/controlDict"
    text = path.read_text()
    text = replace_scalar(text, "application", solver)
    text = replace_scalar(text, "endTime", f"{end_time:g}")
    write_interval = 10 if solver == "pimpleFoam" else checkpoint_interval(start_time, end_time)
    text = replace_scalar(text, "writeInterval", f"{write_interval:g}")
    text = replace_scalar(text, "purgeWrite", "2")
    text = remove_duplicate_shear_yplus_function(text)
    text = normalize_function_object_write_intervals(text)
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


def update_outlet_pressure(case_dir: Path, time_name: str, outlet_pressure: str) -> None:
    path = case_dir / time_name / "p"
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


def scalar_field_text(
    name: str,
    dimensions: str,
    internal: str,
    boundaries: dict[str, str],
    time_name: str,
) -> str:
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
        f'    location    "{time_name}";',
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


def write_sst_fields(case_dir: Path, time_name: str) -> None:
    time_dir = case_dir / time_name
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
    (time_dir / "k").write_text(
        scalar_field_text("k", "[0 2 -2 0 0 0 0]", f"uniform {k}", k_boundaries, time_name)
    )
    (time_dir / "omega").write_text(
        scalar_field_text("omega", "[0 0 -1 0 0 0 0]", f"uniform {omega}", omega_boundaries, time_name)
    )
    (time_dir / "nut").write_text(
        scalar_field_text("nut", "[0 2 -1 0 0 0 0]", "uniform 0", nut_boundaries, time_name)
    )


def write_lm_fields(case_dir: Path, time_name: str) -> None:
    write_sst_fields(case_dir, time_name)
    write_lm_transition_fields(case_dir, time_name)


def write_lm_transition_fields(case_dir: Path, time_name: str) -> None:
    """Add only LM-specific scalars, preserving an SST warm-start state."""
    time_dir = case_dir / time_name
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
        scalar_field_text(
            "gammaInt", "[0 0 0 0 0 0 0]", f"uniform {gamma}", gamma_boundaries, time_name
        )
    )
    (time_dir / "ReThetat").write_text(
        scalar_field_text(
            "ReThetat", "[0 0 0 0 0 0 0]", f"uniform {retheta}", retheta_boundaries, time_name
        )
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


def configure_case(
    case_dir: Path,
    spec: CaseSpec,
    start_time_name: str,
    end_time: float,
    np: int,
    initialize_turbulence_fields: bool,
    initialize_lm_transition_fields_only: bool,
    source_case: Path,
) -> None:
    start_time = float(start_time_name)
    remove_derived_restart_fields(case_dir, start_time_name)
    update_control_dict(case_dir, start_time, end_time, spec.solver)
    update_outlet_pressure(case_dir, start_time_name, spec.outlet_pressure)
    if spec.add_pref:
        add_pref_to_simple(case_dir / "system/fvSolution")
    if spec.turbulence_model != "SpalartAllmaras":
        write_turbulence_properties(case_dir, spec.turbulence_model)
        first_order_turb = spec.relaxation == "lm_very_conservative"
        if spec.turbulence_model == "kOmegaSST":
            if initialize_turbulence_fields:
                write_sst_fields(case_dir, start_time_name)
            write_sst_schemes(case_dir, first_order_turbulence=False, transient=spec.solver == "pimpleFoam")
            write_sst_solution(case_dir, u_relax=0.45, turb_relax=0.3, p_relax=0.2)
            if spec.solver == "pimpleFoam":
                convert_solution_to_pimple(case_dir)
        elif spec.turbulence_model == "kOmegaSSTLM":
            if initialize_turbulence_fields:
                write_lm_fields(case_dir, start_time_name)
            elif initialize_lm_transition_fields_only:
                validate_sst_warm_start(case_dir, start_time_name)
                write_lm_transition_fields(case_dir, start_time_name)
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
        "source_case": str(source_case),
        "same_mesh": True,
        "start_time": start_time,
        "end_time": end_time,
        "initialized_turbulence_fields": initialize_turbulence_fields,
        "initialized_lm_transition_fields_only": initialize_lm_transition_fields_only,
        "warm_start_source": spec.warm_start_source,
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


def case_shell_command(case_dir: Path, command: str) -> str:
    return f"cd {shlex.quote(str(case_dir))} && {command}"


def validate_openfoam_scratch_path(tmp_root: Path) -> None:
    """Reject paths that OpenFOAM's fileName validator cannot accept.

    Shell quoting is not sufficient here: OpenFOAM v2512 treats whitespace in
    the process working directory as an invalid ``fileName`` and aborts before
    the solver dry-run.  A no-whitespace mount point may still be backed by the
    required external SSD storage.
    """
    if any(character.isspace() for character in str(tmp_root)):
        raise ValueError(
            "OpenFOAM scratch paths must not contain whitespace; use a "
            f"no-whitespace mount point backed by the external SSD: {tmp_root}"
        )


def acquire_solver_lock(tmp_root: Path):
    """Prevent two WO-006 runner invocations from launching concurrent solvers."""
    lock_path = tmp_root / ".wo006_solver.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError(f"Another WO-006 solver runner holds {lock_path}") from None
    return handle


def run_openfoam_case(
    case_dir: Path,
    spec: CaseSpec,
    np: int,
    start_time: float,
    end_time: float,
    max_rss_bytes: int,
) -> dict[str, object]:
    status: dict[str, object] = {
        "case": spec.name,
        "ok": False,
        "start_time": start_time,
        "target_end_time": end_time,
    }
    t0 = time.time()
    dry_log = case_dir / f"log.dry_run_{spec.name}.txt"
    rc = run(
        openfoam_cmd(case_shell_command(case_dir, f"{spec.solver} -dry-run")),
        cwd=case_dir.parent,
        log_path=dry_log,
    )
    status["dry_run_returncode"] = rc
    if rc != 0:
        status["failure_stage"] = "dry-run"
        status["elapsed_s"] = time.time() - t0
        return status

    if np <= 1:
        solve_log = case_dir / f"log.{spec.solver}_{spec.name}_{start_time:g}_to_{end_time:g}.txt"
        monitored = run_monitored(
            openfoam_cmd(case_shell_command(case_dir, spec.solver)),
            cwd=case_dir.parent,
            log_path=solve_log,
            max_rss_bytes=max_rss_bytes,
        )
        status.update({f"solve_{key}": value for key, value in monitored.items()})
        status["solve_log"] = str(solve_log)
        if monitored["stopped_by_memory_guard"]:
            status["failure_stage"] = "memory-guard"
            status["elapsed_s"] = time.time() - t0
            return status
        if monitored["returncode"] != 0:
            status["failure_stage"] = spec.solver
            status["elapsed_s"] = time.time() - t0
            return status
        status["process_ok"] = True
        status["elapsed_s"] = time.time() - t0
        return status

    decomp_log = case_dir / f"log.decomposePar_{spec.name}.txt"
    rc = run(
        openfoam_cmd(case_shell_command(case_dir, "decomposePar -force -latestTime")),
        cwd=case_dir.parent,
        log_path=decomp_log,
    )
    status["decompose_returncode"] = rc
    if rc != 0:
        status["failure_stage"] = "decomposePar"
        status["elapsed_s"] = time.time() - t0
        return status

    solve_log = case_dir / f"log.{spec.solver}_{spec.name}_{start_time:g}_to_{end_time:g}.txt"
    monitored = run_monitored(
        openfoam_cmd(case_shell_command(case_dir, f"mpirun -np {np} {spec.solver} -parallel")),
        cwd=case_dir.parent,
        log_path=solve_log,
        max_rss_bytes=max_rss_bytes,
    )
    status.update({f"solve_{key}": value for key, value in monitored.items()})
    status["solve_log"] = str(solve_log)
    if monitored["stopped_by_memory_guard"]:
        status["failure_stage"] = "memory-guard"
        status["elapsed_s"] = time.time() - t0
        return status
    if monitored["returncode"] != 0:
        status["failure_stage"] = spec.solver
        status["elapsed_s"] = time.time() - t0
        return status

    recon_log = case_dir / f"log.reconstructPar_{spec.name}.txt"
    rc = run(
        openfoam_cmd(case_shell_command(case_dir, "reconstructPar -latestTime")),
        cwd=case_dir.parent,
        log_path=recon_log,
    )
    status["reconstruct_returncode"] = rc
    if rc != 0:
        status["failure_stage"] = "reconstructPar"
        status["elapsed_s"] = time.time() - t0
        return status

    merge_processor_post_processing(case_dir)
    for processor_dir in case_dir.glob("processor*"):
        if processor_dir.is_dir():
            shutil.rmtree(processor_dir)
    status["process_ok"] = True
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
    number = r"[-+]?(?:nan|inf(?:inity)?|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
    coeff_re = re.compile(
        rf"^\s*(Cd|Cl|CmPitch):\s+({number})\s+({number})\s+({number})\s+({number})",
        flags=re.I,
    )
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
            elif name == "CmPitch":
                pending["CmPitch"] = total
        if {"CD_total", "CD_pressure", "CD_viscous", "CL", "CmPitch"}.issubset(pending) and current_time is not None:
            rows.append(
                {
                    "time": current_time,
                    "CD_total": pending["CD_total"],
                    "CD_pressure": pending["CD_pressure"],
                    "CD_viscous": pending["CD_viscous"],
                    "CL": pending["CL"],
                    "CmPitch": pending["CmPitch"],
                }
            )
            in_block = False
            pending = {}
    return rows


def dot(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def merge_force_rows(row_groups: Iterable[Iterable[dict[str, float]]]) -> list[dict[str, float]]:
    by_time: dict[float, dict[str, float]] = {}
    for rows in row_groups:
        for row in rows:
            by_time[float(row["time"])] = row
    return [by_time[key] for key in sorted(by_time)]


def collect_force_rows(case_dir: Path, spec: CaseSpec) -> tuple[list[dict[str, float]], list[str]]:
    """Collect restart-safe force rows, preferring newer logs at duplicate times."""
    row_groups: list[list[dict[str, float]]] = []
    force_sources: list[str] = []
    force_files = sorted((case_dir / "postProcessing" / FORCE_OBJECT).glob("*/force.dat"))
    for force_file in force_files:
        row_groups.append(parse_force_file(force_file))
        force_sources.append(str(force_file))
    log_files = sorted(
        case_dir.glob(f"log.{spec.solver}_{spec.name}*.txt"),
        key=lambda path: path.stat().st_mtime,
    )
    for log_file in log_files:
        row_groups.append(parse_force_coeffs_log(log_file))
        force_sources.append(str(log_file))
    return merge_force_rows(row_groups), force_sources


def summarize_force_rows(rows: list[dict[str, float]]) -> dict[str, object]:
    if not rows:
        return {"stable_force_window": False, "force_window_status": "missing"}
    result: dict[str, object] = {
        "n_force_rows": len(rows),
        "final_time": rows[-1]["time"],
        "stable_force_window": False,
    }
    required_keys = ("time", "CD_total", "CD_pressure", "CD_viscous", "CL", "CmPitch")
    result["finite_force_history"] = all(
        key in row and math.isfinite(float(row[key])) for row in rows for key in required_keys
    )
    if not result["finite_force_history"]:
        result["force_window_status"] = "nonfinite"
        return result
    window = rows[-MIN_FORCE_WINDOW_ROWS:]
    for key in ("CD_total", "CD_pressure", "CD_viscous", "CL", "CmPitch"):
        if not all(key in row for row in window):
            continue
        vals = [float(row[key]) for row in window]
        result[f"{key}_last"] = rows[-1][key]
        result[f"{key}_mean_final_window"] = sum(vals) / len(vals)
        result[f"{key}_range_final_window"] = max(vals) - min(vals)
        result[f"{key}_relative_span_final_window"] = (
            math.inf if abs(result[f"{key}_mean_final_window"]) < 1.0e-16
            else result[f"{key}_range_final_window"] / abs(result[f"{key}_mean_final_window"])
        )
    if len(rows) < MIN_FORCE_WINDOW_ROWS:
        result["force_window_status"] = "insufficient_rows"
        return result
    window_times = [float(row["time"]) for row in window]
    result["final_window_start_time"] = window_times[0]
    result["final_window_end_time"] = window_times[-1]
    result["contiguous_final_window"] = all(
        math.isclose(current - previous, 1.0, abs_tol=1.0e-9)
        for previous, current in zip(window_times, window_times[1:])
    )
    result["force_window_status"] = "available"
    result["stable_force_window"] = bool(
        result["contiguous_final_window"]
        and float(result.get("CD_total_relative_span_final_window", math.inf)) < MAX_FORCE_RELATIVE_SPAN
        and float(result.get("CL_relative_span_final_window", math.inf)) < MAX_FORCE_RELATIVE_SPAN
        and float(result.get("CmPitch_range_final_window", math.inf)) < MAX_CM_PITCH_ABSOLUTE_SPAN
    )
    return result


def summarize_case(case_dir: Path, spec: CaseSpec, status: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {
        "case": spec.name,
        "solver": spec.solver,
        "outlet_pressure": spec.outlet_pressure,
        "turbulence_model": spec.turbulence_model,
        "note": spec.attempt_note,
        "process_ok": bool(status.get("process_ok", status.get("ok"))),
        "ok": False,
        "failure_stage": status.get("failure_stage", ""),
        "elapsed_s": status.get("elapsed_s", ""),
        "peak_rss_bytes": status.get("solve_peak_rss_bytes", ""),
    }
    rows, force_sources = collect_force_rows(case_dir, spec)
    summary["force_file"] = ";".join(force_sources)
    if not rows:
        if summary["process_ok"] and not summary["failure_stage"]:
            summary["failure_stage"] = "force-history-missing"
        summary.update(summarize_force_rows(rows))
        return summary
    summary.update(summarize_force_rows(rows))
    latest_checkpoint = float(latest_time_name(case_dir))
    summary["latest_checkpoint"] = latest_checkpoint
    summary["force_reaches_latest_checkpoint"] = math.isclose(
        float(summary["final_time"]), latest_checkpoint, abs_tol=1.0e-9
    )
    start_time = float(status.get("start_time", -math.inf))
    summary["advanced_past_start"] = float(summary["final_time"]) > start_time
    if summary["process_ok"] and not summary["advanced_past_start"]:
        summary["failure_stage"] = "time-not-advanced"
    elif summary["process_ok"] and not summary["force_reaches_latest_checkpoint"]:
        summary["failure_stage"] = "force-history-does-not-reach-checkpoint"
    elif summary["process_ok"] and summary["force_window_status"] == "nonfinite":
        summary["failure_stage"] = "force-history-nonfinite"
    elif summary["process_ok"] and summary["force_window_status"] == "insufficient_rows":
        summary["failure_stage"] = "force-window-insufficient"
    elif summary["process_ok"] and not summary["stable_force_window"]:
        summary["failure_stage"] = "force-window-unstable"
    summary["ok"] = bool(
        summary["process_ok"]
        and summary["advanced_past_start"]
        and summary["force_reaches_latest_checkpoint"]
        and summary["stable_force_window"]
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
        "process_ok",
        "ok",
        "failure_stage",
        "stable_force_window",
        "finite_force_history",
        "force_window_status",
        "contiguous_final_window",
        "advanced_past_start",
        "final_time",
        "latest_checkpoint",
        "force_reaches_latest_checkpoint",
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
        "CL_relative_span_final_window",
        "CmPitch_last",
        "CmPitch_mean_final_window",
        "CmPitch_range_final_window",
        "CmPitch_relative_span_final_window",
        "CD_total_relative_span_final_window",
        "elapsed_s",
        "peak_rss_bytes",
        "n_force_rows",
        "force_file",
        "note",
    ]
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in keys})
    (OUT_ROOT / "model_architecture_sensitivity_summary.json").write_text(json.dumps(rows, indent=2) + "\n")


def resummarize_existing(case_names: list[str]) -> int:
    rows: list[dict[str, object]] = []
    for name in case_names:
        spec = CASE_SPECS[name]
        case_dir = OUT_ROOT / "openfoam_cases" / name
        if not case_dir.exists():
            continue
        status_path = case_dir / "architecture_sensitivity_status.json"
        status: dict[str, object] = {}
        if status_path.exists():
            status = json.loads(status_path.read_text())
        manifest_path = case_dir / "architecture_sensitivity_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            status.setdefault("start_time", manifest.get("start_time", LATEST_TIME))
        else:
            status.setdefault("start_time", LATEST_TIME)
        rows.append(summarize_case(case_dir, spec, status))
    write_summary(sorted(rows, key=lambda row: str(row["case"])))
    return 0


def discover_existing_case_names() -> list[str]:
    """Include existing non-default recovery lanes in an unfiltered summary."""
    case_root = OUT_ROOT / "openfoam_cases"
    return [name for name in CASE_SPECS if (case_root / name).is_dir()]


def copy_back(run_case: Path, dest_case: Path) -> None:
    dest_case.parent.mkdir(parents=True, exist_ok=True)
    if dest_case.exists():
        shutil.rmtree(dest_case)
    shutil.copytree(run_case, dest_case)


def operational_exit_code(statuses: list[dict[str, object]]) -> int:
    """Return non-zero when any requested case failed before solver completion."""
    return int(any(not bool(status.get("process_ok", False)) for status in statuses))


def append_attempt_record(path: Path, record: dict[str, object]) -> dict[str, object]:
    """Append one controller attempt without overwriting earlier resource evidence."""
    existing = path.read_text().splitlines() if path.exists() else []
    payload = {"attempt_id": len(existing) + 1, **record}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
    return payload


def solver_log_diagnostics(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {"k_bounding_count": 0, "omega_bounding_count": 0, "lambda_warning_count": 0}
    text = path.read_text(errors="ignore")
    return {
        "k_bounding_count": text.count("bounding k"),
        "omega_bounding_count": text.count("bounding omega"),
        "lambda_warning_count": text.count("maxLambdaIter"),
    }


def run_cases(
    case_names: list[str],
    end_time: float | None,
    iterations: int | None,
    np: int,
    keep_tmp: bool,
    resume: bool,
    max_rss_gb: float,
    tmp_root: Path,
    min_scratch_free_gb: float,
    controller_command: str,
) -> int:
    if not SOURCE_CASE.exists():
        raise FileNotFoundError(SOURCE_CASE)
    validate_openfoam_scratch_path(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)
    solver_lock = acquire_solver_lock(tmp_root)
    (OUT_ROOT / "openfoam_cases").mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, object]] = []
    if (OUT_ROOT / "model_architecture_sensitivity_summary.json").exists():
        try:
            summaries = json.loads((OUT_ROOT / "model_architecture_sensitivity_summary.json").read_text())
        except json.JSONDecodeError:
            summaries = []
    by_case = {str(item.get("case")): item for item in summaries}
    run_statuses: list[dict[str, object]] = []

    for name in case_names:
        scratch_free_before_bytes = shutil.disk_usage(tmp_root).free
        scratch_free_gb = scratch_free_before_bytes / 1.0e9
        if scratch_free_gb < min_scratch_free_gb:
            raise RuntimeError(
                f"Scratch free space {scratch_free_gb:.2f} GB is below the "
                f"{min_scratch_free_gb:.2f} GB safety gate: {tmp_root}"
            )
        spec = CASE_SPECS[name]
        run_case = tmp_root / name
        dest_case = OUT_ROOT / "openfoam_cases" / name
        if resume:
            if not dest_case.exists():
                raise FileNotFoundError(f"Cannot resume missing case: {dest_case}")
            source = dest_case
        elif spec.warm_start_source:
            source = OUT_ROOT / "openfoam_cases" / spec.warm_start_source
            if not source.exists():
                raise FileNotFoundError(f"Cannot warm start from missing SST case: {source}")
            validate_warm_start_source_qualification(source, CASE_SPECS[spec.warm_start_source])
        else:
            source = SOURCE_CASE
        copy_lean_case(
            source,
            run_case,
            include_post_processing=resume,
            include_logs=resume,
        )
        start_time_name = latest_time_name(run_case)
        start_time = float(start_time_name)
        target_end_time = start_time + iterations if iterations is not None else end_time
        if target_end_time is None or target_end_time <= start_time:
            raise ValueError(
                f"Target end time {target_end_time} must be greater than case start time {start_time}"
            )
        initialize_lm_transition_fields_only = bool(not resume and spec.warm_start_source)
        initialize_turbulence_fields = bool(
            not resume
            and not initialize_lm_transition_fields_only
            and spec.turbulence_model != "SpalartAllmaras"
        )
        configure_case(
            run_case,
            spec,
            start_time_name,
            target_end_time,
            np,
            initialize_turbulence_fields=initialize_turbulence_fields,
            initialize_lm_transition_fields_only=initialize_lm_transition_fields_only,
            source_case=source,
        )
        status = run_openfoam_case(
            run_case,
            spec,
            np,
            start_time,
            target_end_time,
            max_rss_bytes=int(max_rss_gb * 1.0e9),
        )
        status["scratch_root"] = str(tmp_root)
        status["scratch_backing_root"] = str(SCRATCH_BACKING_ROOT)
        status["scratch_free_before_bytes"] = scratch_free_before_bytes
        status["scratch_free_after_bytes"] = shutil.disk_usage(tmp_root).free
        run_statuses.append(status)
        (run_case / "architecture_sensitivity_status.json").write_text(json.dumps(status, indent=2) + "\n")
        copy_back(run_case, dest_case)
        summary = summarize_case(dest_case, spec, status)
        by_case[name] = summary
        write_summary([by_case[k] for k in sorted(by_case)])
        solve_log = dest_case / Path(str(status.get("solve_log", ""))).name
        append_attempt_record(
            OUT_ROOT / "recovery_attempt_ledger.jsonl",
            {
                "controller_command": controller_command,
                "case": name,
                "start_time": status.get("start_time"),
                "target_end_time": status.get("target_end_time"),
                "process_ok": status.get("process_ok", False),
                "failure_stage": status.get("failure_stage", summary.get("failure_stage", "")),
                "dry_run_returncode": status.get("dry_run_returncode"),
                "solve_returncode": status.get("solve_returncode"),
                "elapsed_s": status.get("elapsed_s"),
                "peak_rss_bytes": status.get("solve_peak_rss_bytes"),
                "max_rss_bytes": status.get("solve_max_rss_bytes"),
                "stopped_by_memory_guard": status.get("solve_stopped_by_memory_guard", False),
                "scratch_root": status.get("scratch_root", str(tmp_root)),
                "scratch_backing_root": status.get("scratch_backing_root", str(SCRATCH_BACKING_ROOT)),
                "scratch_free_before_bytes": status.get("scratch_free_before_bytes"),
                "scratch_free_after_bytes": status.get("scratch_free_after_bytes"),
                "latest_checkpoint": summary.get("latest_checkpoint"),
                "unique_force_rows": summary.get("n_force_rows", 0),
                "force_final_time": summary.get("final_time"),
                "formal_force_window_stable": summary.get("stable_force_window", False),
                "solve_log": solve_log.name if solve_log.name else "",
                **solver_log_diagnostics(solve_log),
            },
        )
        if not keep_tmp and run_case.exists():
            shutil.rmtree(run_case)
    result = operational_exit_code(run_statuses)
    fcntl.flock(solver_lock.fileno(), fcntl.LOCK_UN)
    solver_lock.close()
    return result


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
    end_group = parser.add_mutually_exclusive_group()
    end_group.add_argument("--end-time", type=float)
    end_group.add_argument("--iterations", type=int)
    parser.add_argument("--np", type=int, default=1)
    parser.add_argument("--allow-parallel", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--max-rss-gb", type=float, default=default_max_rss_gb())
    parser.add_argument("--tmp-root", type=Path, default=TMP_ROOT)
    parser.add_argument("--min-scratch-free-gb", type=float, default=DEFAULT_MIN_SCRATCH_FREE_GB)
    parser.add_argument("--keep-tmp", action="store_true")
    args = parser.parse_args(argv)
    if args.summarize_only:
        case_names = args.cases if "--cases" in argv else discover_existing_case_names()
        return resummarize_existing(case_names)
    if args.np > 1 and not args.allow_parallel:
        parser.error("--np > 1 requires --allow-parallel; serial is the RAM-safe default")
    if args.max_rss_gb <= 0:
        parser.error("--max-rss-gb must be positive")
    if args.min_scratch_free_gb <= 0:
        parser.error("--min-scratch-free-gb must be positive")
    end_time = args.end_time
    iterations = args.iterations
    if end_time is None and iterations is None:
        iterations = 50
    return run_cases(
        args.cases,
        end_time=end_time,
        iterations=iterations,
        np=args.np,
        keep_tmp=args.keep_tmp,
        resume=args.resume,
        max_rss_gb=args.max_rss_gb,
        tmp_root=args.tmp_root,
        min_scratch_free_gb=args.min_scratch_free_gb,
        controller_command=shlex.join([sys.executable, str(Path(__file__).resolve()), *argv]),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
