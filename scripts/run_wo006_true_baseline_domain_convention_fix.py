#!/usr/bin/env python3
"""Correct the WO-006 true Baseline OpenFOAM half-wing domain convention."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
import time
from typing import Any, Mapping, Sequence

import run_wo006_true_baseline_openfoam_route_smoke as base


OUTPUT_DIR = base.WO006_ROOT / "cfd_release_v0_true_baseline_domain_convention_fix"
CASE_NAME = "true_baseline_swept_cgrid_halfwing_convention"
FULL_REF_AREA_M2 = base.REF_AREA_M2
HALF_REF_AREA_M2 = FULL_REF_AREA_M2 / 2.0
PREVIOUS = {
    "CD_primary": 0.01837651,
    "CL_primary": 0.5654834,
    "CD_total": 0.06993191,
    "diagnostic_fraction_of_total": 0.7372226718818348,
    "yplus_mean": 0.5882082748397414,
    "yplus_p95": 1.17049,
    "yplus_max": 2.8138,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--source-case", type=Path, default=base.DEFAULT_SOURCE_CASE)
    parser.add_argument("--openfoam", default=base.OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--iterations", type=int, default=500)
    args = parser.parse_args()
    manifest = run_domain_convention_fix(
        output_dir=args.output_dir,
        source_case=args.source_case,
        openfoam_command=args.openfoam,
        clean=args.clean,
        setup_only=args.setup_only,
        timeout_seconds=args.timeout_seconds,
        iterations=args.iterations,
    )
    print(json.dumps(manifest["verdict"], indent=2, sort_keys=True))


def run_domain_convention_fix(
    *,
    output_dir: Path,
    source_case: Path,
    openfoam_command: str,
    clean: bool,
    setup_only: bool,
    timeout_seconds: float,
    iterations: int,
) -> dict[str, Any]:
    start = time.monotonic()
    output_dir = output_dir.resolve()
    source_case = source_case.resolve()
    case_dir = output_dir / "openfoam_cases" / CASE_NAME
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    original_geometry = base.audit_patch_geometry(source_case / "constant" / "polyMesh")
    domain_identity = classify_domain_identity(original_geometry)
    patch_roles = classify_patch_roles(original_geometry, domain_identity)
    alias_mapping = build_alias_mapping(patch_roles)
    case_setup = generate_corrected_case(
        case_dir=case_dir,
        source_case=source_case,
        domain_identity=domain_identity,
        patch_roles=patch_roles,
        alias_mapping=alias_mapping,
        iterations=iterations,
    )
    corrected_geometry = base.audit_patch_geometry(case_dir / "constant" / "polyMesh")
    validation = validate_corrected_case(case_dir, case_setup, domain_identity)

    write_domain_identity_audit(output_dir, domain_identity, original_geometry)
    write_patch_role_classification(output_dir, patch_roles)
    write_bc_policy(output_dir, case_setup)
    write_force_normalization_policy(output_dir, case_setup)
    write_patch_alias_mapping(output_dir, alias_mapping)
    write_patch_metadata_fix_report(output_dir, alias_mapping, corrected_geometry)

    checkmesh: dict[str, Any] | None = None
    dry_run: dict[str, Any] | None = None
    solver_run: dict[str, Any] | None = None
    yplus_post: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = []

    if not setup_only:
        checkmesh = base.run_openfoam_command(
            case_dir,
            openfoam_command=openfoam_command,
            command="checkMesh -meshQuality",
            log_name="log.checkMesh",
            timeout_seconds=900.0,
        )
        validation = validate_corrected_case(case_dir, case_setup, domain_identity, checkmesh)
        if checkmesh["returncode"] == 0:
            dry_run = base.run_openfoam_command(
                case_dir,
                openfoam_command=openfoam_command,
                command="simpleFoam -dry-run",
                log_name="log.simpleFoam_dry_run",
                timeout_seconds=600.0,
            )
            attempts.append({"attempt": 1, "stage": "dry_run", "returncode": dry_run["returncode"]})
            if dry_run["returncode"] == 0:
                solver_run = base.run_openfoam_command(
                    case_dir,
                    openfoam_command=openfoam_command,
                    command="simpleFoam",
                    log_name="log.simpleFoam_500",
                    timeout_seconds=timeout_seconds,
                )
                attempts.append({"attempt": 1, "stage": "simpleFoam_500", "returncode": solver_run["returncode"]})
                (case_dir / "log.simpleFoam").write_text(
                    (case_dir / "log.simpleFoam_500").read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                )
                if solver_run["returncode"] == 0:
                    yplus_post = base.run_openfoam_command(
                        case_dir,
                        openfoam_command=openfoam_command,
                        command="simpleFoam -postProcess -func yPlus -latestTime",
                        log_name="log.yPlus",
                        timeout_seconds=900.0,
                    )
            else:
                failure = base.classify_failure(case_dir / "log.simpleFoam_dry_run")
        else:
            failure = {
                "class": "mesh_quality_too_severe_or_symmetry_patch_issue",
                "evidence": base.grep_lines(
                    case_dir / "log.checkMesh",
                    ("FOAM FATAL", "Failed", "symmetry", "plane", "wrong", "Error"),
                    limit=80,
                ),
            }
    coeffs = base.parse_force_coefficients(case_dir, case_setup["force_groups"])
    force_split = base.parse_force_splits(case_dir, case_setup["force_groups"])
    yplus = base.parse_yplus(case_dir, case_setup["solid_walls"])
    residuals = base.parse_residuals(case_dir / "log.simpleFoam")
    stability = base.force_stability(
        coeffs.get("functions", {}).get("primary", {}).get("rows", [])
    )
    if failure is None and solver_run and solver_run["returncode"] != 0:
        failure = classify_corrected_solver_failure(case_dir / "log.simpleFoam_500", stability)
    if failure is None and force_history_is_runaway(stability):
        failure = classify_corrected_solver_failure(case_dir / "log.simpleFoam_500", stability)
    converted = build_coefficient_summary(coeffs)
    verdict = build_verdict(
        domain_identity=domain_identity,
        validation=validation,
        checkmesh=checkmesh,
        dry_run=dry_run,
        solver_run=solver_run,
        yplus_post=yplus_post,
        coeffs=coeffs,
        converted=converted,
        yplus=yplus,
        stability=stability,
        force_split=force_split,
        failure=failure,
    )
    comparison = build_before_after_comparison(converted, yplus, stability)
    manifest = {
        "schema_version": "wo006_phase4_domain_convention_fix.v1",
        "created_at_utc": base.utc_now(),
        "output_dir": str(output_dir),
        "case_dir": str(case_dir),
        "source_case": str(source_case),
        "source_commit": base.SOURCE_COMMIT,
        "openfoam_command": openfoam_command,
        "domain_identity": domain_identity,
        "patch_roles": patch_roles,
        "patch_alias_mapping": alias_mapping,
        "case_setup": case_setup,
        "pre_solver_validation": validation,
        "commands": {
            "checkMesh": checkmesh,
            "simpleFoam_dry_run": dry_run,
            "simpleFoam_500": solver_run,
            "postProcess_yPlus": yplus_post,
        },
        "solver_setup_attempts": attempts,
        "coefficients": coeffs,
        "corrected_coefficients": converted,
        "force_split": force_split,
        "yPlus": yplus,
        "residuals": residuals,
        "force_stability": stability,
        "before_after_comparison": comparison,
        "failure": failure,
        "verdict": verdict,
        "elapsed_s": time.monotonic() - start,
    }
    base.write_json(output_dir / "domain_convention_fix_manifest.json", manifest)
    write_run_reports(output_dir, manifest)
    write_rerun(output_dir, source_case)
    return manifest


def classify_domain_identity(geometry: Mapping[str, Any]) -> dict[str, Any]:
    domain = geometry["domain_extent"]
    y_min = float(domain["y"]["min"])
    y_max = float(domain["y"]["max"])
    y_span = y_max - y_min
    half = base.AUTHORITY_HALF_SPAN_M
    full = base.AUTHORITY_FULL_SPAN_M
    patches = geometry["patches"]
    root_candidates = [
        name
        for name, data in patches.items()
        if extent_axis_close(data["extent"], "y", 0.0)
    ]
    outboard_candidates = [
        name
        for name, data in patches.items()
        if extent_axis_close(data["extent"], "y", half)
    ]
    if abs(y_min) < 1e-6 and abs(y_max - half) < 1e-4:
        identity = "half-wing"
    elif abs(y_min + half) < 1e-4 and abs(y_max - half) < 1e-4:
        identity = "full-wing"
    else:
        identity = "ambiguous"
    previous_sref = FULL_REF_AREA_M2
    corrected_sref = HALF_REF_AREA_M2 if identity == "half-wing" else FULL_REF_AREA_M2
    return {
        "mesh_identity": identity,
        "mesh_y_min_m": y_min,
        "mesh_y_max_m": y_max,
        "mesh_y_span_m": y_span,
        "authority_half_span_m": half,
        "authority_full_span_m": full,
        "root_plane_patch_original": root_candidates[0] if root_candidates else None,
        "outboard_span_patch_original": outboard_candidates[0] if outboard_candidates else None,
        "previous_forceCoeffs_sref_m2": previous_sref,
        "corrected_forceCoeffs_sref_m2": corrected_sref,
        "reference_area_convention": (
            "half-wing raw forces normalized by half-wing Sref; coefficients are also "
            "full-wing-equivalent under mirror symmetry"
            if identity == "half-wing"
            else "full-wing forces normalized by full-wing Sref"
        ),
        "coefficient_correction": (
            "previous half-domain forces used full-wing Sref, so same-force coefficients were "
            "about half of the corrected half-Sref convention"
            if identity == "half-wing"
            else "no doubling/reference correction needed"
        ),
    }


def classify_patch_roles(
    geometry: Mapping[str, Any],
    domain_identity: Mapping[str, Any],
) -> dict[str, Any]:
    mesh_identity = domain_identity["mesh_identity"]
    root_patch = domain_identity.get("root_plane_patch_original")
    tip_patch = domain_identity.get("outboard_span_patch_original")
    roles: dict[str, dict[str, Any]] = {}
    for name, data in geometry["patches"].items():
        if name == "airfoil_upper":
            role = "main_lifting_wall_upper"
            corrected = name
        elif name == "airfoil_lower":
            role = "main_lifting_wall_lower"
            corrected = name
        elif name == "te_wall":
            role = "trailing_edge_wall"
            corrected = name
        elif name in {"farfield", "outlet"} or "inlet" in name.lower() or "outer" in name.lower():
            role = "farfield_or_inlet_outlet"
            corrected = name
        elif mesh_identity == "half-wing" and name == root_patch:
            role = "root_symmetry"
            corrected = "root_symmetry"
        elif mesh_identity == "half-wing" and name == tip_patch:
            role = "physical_tip_wall"
            corrected = "physical_tip"
        elif mesh_identity == "full-wing" and name in {"tip_left", "tip_right"}:
            role = "physical_tip_wall"
            corrected = name
        elif name == "closure_wall":
            role = "diagnostic_wall"
            corrected = name
        else:
            role = "unknown_error"
            corrected = name
        roles[name] = {
            "original_patch": name,
            "corrected_patch": corrected,
            "role": role,
            "original_type": data.get("type"),
            "nFaces": data.get("nFaces"),
            "extent": data.get("extent"),
        }
    return {
        "mesh_identity": mesh_identity,
        "roles": roles,
        "root_symmetry_original_patch": root_patch if mesh_identity == "half-wing" else None,
        "physical_tip_original_patches": [tip_patch] if mesh_identity == "half-wing" and tip_patch else [
            name for name, role in roles.items() if role["role"] == "physical_tip_wall"
        ],
    }


def build_alias_mapping(patch_roles: Mapping[str, Any]) -> dict[str, Any]:
    aliases = {}
    for original, data in patch_roles["roles"].items():
        corrected = data["corrected_patch"]
        aliases[original] = {
            "corrected_patch": corrected,
            "role": data["role"],
            "rename_required": original != corrected,
            "boundary_class": boundary_class_for_role(data["role"]),
            "force_inclusion": force_inclusion_for_role(data["role"]),
        }
    return {
        "policy": "boundary metadata/patch labels only; no points/faces/owner/neighbour topology edits",
        "aliases": aliases,
    }


def generate_corrected_case(
    *,
    case_dir: Path,
    source_case: Path,
    domain_identity: Mapping[str, Any],
    patch_roles: Mapping[str, Any],
    alias_mapping: Mapping[str, Any],
    iterations: int,
) -> dict[str, Any]:
    if domain_identity["mesh_identity"] == "ambiguous":
        raise RuntimeError("domain identity is ambiguous; refusing to generate solver case")
    if case_dir.exists():
        shutil.rmtree(case_dir)
    (case_dir / "constant").mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_case / "constant" / "polyMesh", case_dir / "constant" / "polyMesh")
    rewrite_boundary(case_dir / "constant" / "polyMesh" / "boundary", alias_mapping)
    for path in (case_dir / "0", case_dir / "system"):
        path.mkdir(parents=True, exist_ok=True)

    corrected_names = {
        original: data["corrected_patch"]
        for original, data in patch_roles["roles"].items()
    }
    role_to_patches: dict[str, list[str]] = {}
    for original, data in patch_roles["roles"].items():
        role_to_patches.setdefault(data["role"], []).append(corrected_names[original])
    main_walls = role_to_patches.get("main_lifting_wall_upper", []) + role_to_patches.get("main_lifting_wall_lower", [])
    physical_tips = role_to_patches.get("physical_tip_wall", [])
    trailing_edges = role_to_patches.get("trailing_edge_wall", [])
    diagnostic_walls = role_to_patches.get("diagnostic_wall", [])
    solid_walls = main_walls + physical_tips + trailing_edges + diagnostic_walls
    root_symmetry = role_to_patches.get("root_symmetry", [])
    flow_boundaries = role_to_patches.get("farfield_or_inlet_outlet", [])
    force_groups: dict[str, tuple[str, ...]] = {
        "primary": tuple(main_walls),
        "total": tuple(main_walls + physical_tips + trailing_edges + diagnostic_walls),
    }
    for patch in physical_tips + trailing_edges + diagnostic_walls:
        force_groups[patch] = (patch,)
    force_groups = {key: value for key, value in force_groups.items() if value}
    flow_bc_policy = base.build_flow_bc_policy(flow_boundaries)
    sref = domain_identity["corrected_forceCoeffs_sref_m2"]

    (case_dir / "system" / "controlDict").write_text(
        control_dict_text(force_groups=force_groups, max_iterations=iterations, start_from="startTime", sref=sref),
        encoding="utf-8",
    )
    (case_dir / "system" / "fvSchemes").write_text(fv_schemes_bounded_upwind_text(), encoding="utf-8")
    (case_dir / "system" / "fvSolution").write_text(fv_solution_bounded_upwind_text(), encoding="utf-8")
    (case_dir / "system" / "meshQualityDict").write_text(base.mesh_quality_dict_text(), encoding="utf-8")
    (case_dir / "constant" / "transportProperties").write_text(base.transport_properties_text(), encoding="utf-8")
    (case_dir / "constant" / "turbulenceProperties").write_text(base.turbulence_properties_text(), encoding="utf-8")
    for field_name, text in {
        "U": u_field_text(solid_walls, root_symmetry, flow_bc_policy),
        "p": p_field_text(solid_walls, root_symmetry, flow_bc_policy),
        "nut": nut_field_text(solid_walls, root_symmetry, flow_bc_policy),
        "nuTilda": nu_tilda_field_text(solid_walls, root_symmetry, flow_bc_policy),
    }.items():
        (case_dir / "0" / field_name).write_text(text, encoding="utf-8")

    return {
        "case_dir": str(case_dir),
        "source_case": str(source_case),
        "mesh_topology_policy": "copied accepted polyMesh; only boundary names/classes corrected",
        "domain_identity": domain_identity["mesh_identity"],
        "solver": "simpleFoam",
        "turbulence_model": "SpalartAllmaras",
        "solver_setup_profile": "bounded_upwind_final_attempt_after_force_runaway",
        "solver_setup_note": (
            "The corrected symmetry-plane case first ran away with the previous relaxation "
            "profile, then with conservative relaxation. This final bounded attempt keeps "
            "the same mesh, BCs, turbulence model, and operating point, but uses upwind "
            "divergence schemes plus stronger SIMPLE damping for the high-nonorthogonal mesh."
        ),
        "velocity_mps": base.VELOCITY_MPS,
        "aoa_deg": base.AOA_DEG,
        "inlet_U": list(base.inlet_velocity(base.AOA_DEG)),
        "dragDir": list(base.drag_dir(base.AOA_DEG)),
        "liftDir": list(base.lift_dir(base.AOA_DEG)),
        "rho_kg_m3": base.AIR_DENSITY,
        "nu_m2_s": base.KINEMATIC_VISCOSITY,
        "ref_area_m2": sref,
        "full_ref_area_m2": FULL_REF_AREA_M2,
        "half_ref_area_m2": HALF_REF_AREA_M2,
        "ref_length_m": base.REF_LENGTH_M,
        "ref_origin_m": list(base.REF_ORIGIN_M),
        "solid_walls": solid_walls,
        "root_symmetry": root_symmetry,
        "flow_boundaries": flow_boundaries,
        "force_groups": {key: list(value) for key, value in force_groups.items()},
        "flow_bc_policy": flow_bc_policy,
        "normalization_policy": domain_identity["reference_area_convention"],
    }


def rewrite_boundary(path: Path, alias_mapping: Mapping[str, Any]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for original, mapping in alias_mapping["aliases"].items():
        corrected = mapping["corrected_patch"]
        boundary_class = mapping["boundary_class"]
        pattern = re.compile(
            rf"(^\s*){re.escape(original)}(\s*\n\s*\{{.*?^\s*type\s+)([A-Za-z0-9_]+)(\s*;)",
            re.MULTILINE | re.DOTALL,
        )
        text, count = pattern.subn(rf"\g<1>{corrected}\g<2>{boundary_class}\g<4>", text, count=1)
        if count != 1:
            raise RuntimeError(f"could not rewrite boundary metadata for {original}")
    path.write_text(text, encoding="utf-8")


def control_dict_text(
    *,
    force_groups: Mapping[str, Sequence[str]],
    max_iterations: int,
    start_from: str,
    sref: float,
) -> str:
    force_objects = "\n".join(
        force_coeff_function_text(name=f"forceCoeffs_{name}", patches=patches, sref=sref)
        + "\n"
        + base.forces_function_text(name=f"forces_{name}", patches=patches)
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


def fv_schemes_bounded_upwind_text() -> str:
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
    default         cellLimited Gauss linear 1;
}
divSchemes
{
    default                         none;
    div(phi,U)                      bounded Gauss upwind;
    div(phi,nuTilda)                bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U)))))   Gauss linear;
}
laplacianSchemes
{
    default         Gauss linear limited 0.5;
}
interpolationSchemes
{
    default         linear;
}
snGradSchemes
{
    default         limited 0.5;
}
wallDist
{
    method          meshWave;
}
"""


def fv_solution_bounded_upwind_text() -> str:
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
        relTol          0.05;
        smoother        GaussSeidel;
    }
    U
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0.05;
    }
    nuTilda
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0.05;
    }
}
SIMPLE
{
    nNonOrthogonalCorrectors 4;
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
        p               0.05;
    }
    equations
    {
        U               0.1;
        nuTilda         0.1;
    }
}
"""


def force_coeff_function_text(*, name: str, patches: Sequence[str], sref: float) -> str:
    patch_list = " ".join(patches)
    lift = base.lift_dir(base.AOA_DEG)
    drag = base.drag_dir(base.AOA_DEG)
    return f"""    {name}
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        patches         ({patch_list});
        rho             rhoInf;
        rhoInf          {base.AIR_DENSITY:.9g};
        liftDir         ({lift[0]:.9g} {lift[1]:.9g} {lift[2]:.9g});
        dragDir         ({drag[0]:.9g} {drag[1]:.9g} {drag[2]:.9g});
        CofR            ({base.REF_ORIGIN_M[0]:.9f} {base.REF_ORIGIN_M[1]:.9f} {base.REF_ORIGIN_M[2]:.9f});
        pitchAxis       (0 1 0);
        magUInf         {base.VELOCITY_MPS:.9g};
        lRef            {base.REF_LENGTH_M:.9f};
        Aref            {sref:.9f};
        writeControl    timeStep;
        writeInterval   1;
        log             true;
    }}
"""


def u_field_text(
    solid_walls: Sequence[str],
    root_symmetry: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    u = base.inlet_velocity(base.AOA_DEG)
    return (
        base.field_header("volVectorField", "U", "[0 1 -1 0 0 0 0]", f"uniform {base.vec(u)}")
        + "\n".join(base.flow_u_entry(name, policy["U"], u) for name, policy in flow_bc_policy.items())
        + "\n"
        + "\n".join(symmetry_entry(name) for name in root_symmetry)
        + "\n"
        + "\n".join(base.no_slip_entry(name) for name in solid_walls)
        + "\n}\n"
    )


def p_field_text(
    solid_walls: Sequence[str],
    root_symmetry: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    return (
        base.field_header("volScalarField", "p", "[0 2 -2 0 0 0 0]", "uniform 0")
        + "\n".join(base.flow_p_entry(name, policy["p"]) for name, policy in flow_bc_policy.items())
        + "\n"
        + "\n".join(symmetry_entry(name) for name in root_symmetry)
        + "\n"
        + "\n".join(base.zero_gradient_entry(name) for name in solid_walls)
        + "\n}\n"
    )


def nut_field_text(
    solid_walls: Sequence[str],
    root_symmetry: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    return (
        base.field_header("volScalarField", "nut", "[0 2 -1 0 0 0 0]", "uniform 0")
        + "\n".join(base.calculated_scalar_entry(name) for name in flow_bc_policy)
        + "\n"
        + "\n".join(symmetry_entry(name) for name in root_symmetry)
        + "\n"
        + "\n".join(base.nut_wall_entry(name) for name in solid_walls)
        + "\n}\n"
    )


def nu_tilda_field_text(
    solid_walls: Sequence[str],
    root_symmetry: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    return (
        base.field_header("volScalarField", "nuTilda", "[0 2 -1 0 0 0 0]", "uniform 4.0e-5")
        + "\n".join(base.flow_nu_tilda_entry(name, policy["nuTilda"]) for name, policy in flow_bc_policy.items())
        + "\n"
        + "\n".join(symmetry_entry(name) for name in root_symmetry)
        + "\n"
        + "\n".join(base.fixed_value_scalar_entry(name, "0") for name in solid_walls)
        + "\n}\n"
    )


def symmetry_entry(name: str) -> str:
    return f"""    {name}
    {{
        type            symmetryPlane;
    }}"""


def validate_corrected_case(
    case_dir: Path,
    case_setup: Mapping[str, Any],
    domain_identity: Mapping[str, Any],
    checkmesh: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    boundary = base.parse_boundary(case_dir / "constant" / "polyMesh" / "boundary")
    patches = boundary["patches"]
    field_entries = {
        field: base.parse_field_patch_entries(case_dir / "0" / field)
        for field in base.FIELD_NAMES
    }
    missing_by_field = {
        field: sorted(set(patches) - set(entries))
        for field, entries in field_entries.items()
    }
    root_names = set(case_setup["root_symmetry"])
    force_patches = {
        patch
        for group in case_setup["force_groups"].values()
        for patch in group
    }
    checks = {
        "domain_classified": domain_identity["mesh_identity"] in {"half-wing", "full-wing"},
        "all_fields_cover_all_patches": all(not missing for missing in missing_by_field.values()),
        "root_symmetry_boundary_class": all(patches.get(name, {}).get("type") == "symmetryPlane" for name in root_names),
        "root_symmetry_field_entries": all(
            field_entries[field].get(name, {}).get("type") == "symmetryPlane"
            for field in base.FIELD_NAMES
            for name in root_names
        ),
        "root_symmetry_excluded_from_forces": not (root_names & force_patches),
        "solid_walls_are_wall_boundary_class": all(
            patches.get(name, {}).get("type") == "wall"
            for name in case_setup["solid_walls"]
        ),
        "physical_tip_is_wall": all(
            patches.get(name, {}).get("type") == "wall"
            for name in case_setup["force_groups"]
            if name == "physical_tip"
        ),
        "force_patches_exist": force_patches <= set(patches),
        "half_sref_used_for_halfwing": (
            abs(float(case_setup["ref_area_m2"]) - HALF_REF_AREA_M2) < 1e-9
            if domain_identity["mesh_identity"] == "half-wing"
            else True
        ),
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
        "root_symmetry": list(root_names),
        "force_patches": sorted(force_patches),
        "checkmesh": checkmesh,
    }


def build_coefficient_summary(coeffs: Mapping[str, Any]) -> dict[str, Any]:
    summary = coeffs.get("summary", {})
    corrected = {
        "CD_primary_raw_half_sref": summary.get("CD_primary"),
        "CL_primary_raw_half_sref": summary.get("CL_primary"),
        "CD_total_raw_half_sref": summary.get("CD_total"),
        "CL_total_raw_half_sref": summary.get("CL_total"),
        "CD_physical_tip": summary.get("CD_physical_tip"),
        "CD_te_wall": summary.get("CD_te_wall"),
        "CD_diagnostic_sum_excluding_root": summary.get("CD_diagnostic_sum"),
    }
    corrected.update(
        {
            "CD_primary_fullwing_equivalent": corrected["CD_primary_raw_half_sref"],
            "CL_primary_fullwing_equivalent": corrected["CL_primary_raw_half_sref"],
            "CD_total_fullwing_equivalent": corrected["CD_total_raw_half_sref"],
            "CL_total_fullwing_equivalent": corrected["CL_total_raw_half_sref"],
            "normalization_note": (
                "Half-wing forces are normalized by half-wing Sref; under mirror symmetry these "
                "coefficients equal full-wing-equivalent coefficients without additional doubling."
            ),
        }
    )
    return corrected


def build_verdict(
    *,
    domain_identity: Mapping[str, Any],
    validation: Mapping[str, Any],
    checkmesh: Mapping[str, Any] | None,
    dry_run: Mapping[str, Any] | None,
    solver_run: Mapping[str, Any] | None,
    yplus_post: Mapping[str, Any] | None,
    coeffs: Mapping[str, Any],
    converted: Mapping[str, Any],
    yplus: Mapping[str, Any],
    stability: Mapping[str, Any],
    force_split: Mapping[str, Any],
    failure: Mapping[str, Any] | None,
) -> dict[str, Any]:
    simplefoam_completed = bool(solver_run and solver_run.get("returncode") == 0)
    y_summary = yplus.get("primary_main_wall_summary", {})
    diagnostic_sum = converted.get("CD_diagnostic_sum_excluding_root")
    total = converted.get("CD_total_fullwing_equivalent")
    diagnostic_fraction = diagnostic_sum / total if diagnostic_sum is not None and total else None
    yplus_ok = (
        isinstance(y_summary.get("mean"), (int, float))
        and isinstance(y_summary.get("p95"), (int, float))
        and y_summary["mean"] < 5.0
        and y_summary["p95"] < 10.0
    )
    diagnostics_resolved = (
        diagnostic_fraction is not None
        and diagnostic_fraction < 0.10
        and coeffs.get("summary", {}).get("CD_physical_tip") is not None
    )
    return {
        "status": (
            "route_smoke_pass"
            if simplefoam_completed and failure is None and stability.get("route_smoke_stable") is True
            else "blocked"
        ),
        "mesh_identity": domain_identity["mesh_identity"],
        "wrongly_wall_treated_patch": domain_identity.get("root_plane_patch_original"),
        "root_symmetry_correctly_applied": validation["checks"].get("root_symmetry_boundary_class")
        and validation["checks"].get("root_symmetry_excluded_from_forces"),
        "reference_area_convention": domain_identity["reference_area_convention"],
        "checkMesh_passed": checkmesh is not None and checkmesh.get("returncode") == 0,
        "dry_run_passed": dry_run is not None and dry_run.get("returncode") == 0,
        "simpleFoam_ran": simplefoam_completed,
        "yPlus_postprocess_passed": yplus_post is not None and yplus_post.get("returncode") == 0,
        "corrected_coefficients": converted,
        "yPlus_primary_mean_p95_max": {
            "mean": y_summary.get("mean"),
            "p95": y_summary.get("p95"),
            "max": y_summary.get("max"),
        },
        "yplus_wall_resolved_like": yplus_ok,
        "diagnostic_fraction_of_total_excluding_root": diagnostic_fraction,
        "diagnostic_patch_contamination_resolved": diagnostics_resolved,
        "force_window_stability": stability,
        "pressure_viscous_split_available": any(
            group.get("status") == "available"
            for group in force_split.get("groups", {}).values()
        ),
        "ready_for_aoa_cl_sweep": (
            simplefoam_completed
            and yplus_ok
            and diagnostics_resolved
            and stability.get("route_smoke_stable") is True
        ),
        "xfoil_comparable": False,
        "xfoil_note": "Only ready for comparable-CL sweep; do not compare to XFOIL until CL target is matched.",
        "failure": failure,
    }


def classify_corrected_solver_failure(log_path: Path, stability: Mapping[str, Any]) -> dict[str, Any]:
    if force_history_is_runaway(stability):
        return {
            "class": "numerical_divergence_force_runaway",
            "log": str(log_path),
            "evidence": {
                "force_window_stability": stability,
                "note": (
                    "Corrected half-wing BCs pass checkMesh and dry-run, but the primary "
                    "force window runs away/oscillates before a 500-iteration smoke can complete."
                ),
            },
            "tail": base.tail(log_path, 80),
        }
    fallback = base.classify_failure(log_path)
    if fallback.get("class") == "turbulence_variable_issue" and fallback.get("evidence") == [
        "trapFpe: Floating point exception trapping enabled (FOAM_SIGFPE)."
    ]:
        fallback["class"] = "numerical_divergence_or_interrupted_solver"
        fallback["evidence"] = [
            "solver stopped before 500 iterations; no FOAM FATAL BC/turbulence dictionary error was present",
        ]
    return fallback


def force_history_is_runaway(stability: Mapping[str, Any]) -> bool:
    if stability.get("status") != "available":
        return False
    for key in ("Cd", "Cl", "Cs"):
        data = stability.get(key)
        if not isinstance(data, Mapping):
            continue
        last = data.get("last")
        span = data.get("span")
        relative = data.get("relative_span")
        if isinstance(last, (int, float)) and abs(float(last)) > 5.0:
            return True
        if isinstance(span, (int, float)) and float(span) > 5.0:
            return True
        if isinstance(relative, (int, float)) and float(relative) > 1.0:
            return True
    return False


def build_before_after_comparison(
    converted: Mapping[str, Any],
    yplus: Mapping[str, Any],
    stability: Mapping[str, Any],
) -> dict[str, Any]:
    new_total = converted.get("CD_total_fullwing_equivalent")
    new_primary = converted.get("CD_primary_fullwing_equivalent")
    new_cl = converted.get("CL_primary_fullwing_equivalent")
    new_diag = converted.get("CD_diagnostic_sum_excluding_root")
    y_summary = yplus.get("primary_main_wall_summary", {})
    return {
        "previous": PREVIOUS,
        "corrected": {
            "CD_primary": new_primary,
            "CL_primary": new_cl,
            "CD_total": new_total,
            "diagnostic_sum_excluding_root": new_diag,
            "diagnostic_fraction_of_total": new_diag / new_total if new_diag is not None and new_total else None,
            "yplus_mean": y_summary.get("mean"),
            "yplus_p95": y_summary.get("p95"),
            "yplus_max": y_summary.get("max"),
            "force_stable": stability.get("route_smoke_stable"),
        },
        "delta": {
            "CD_total_change": new_total - PREVIOUS["CD_total"] if new_total is not None else None,
            "CD_primary_change": new_primary - PREVIOUS["CD_primary"] if new_primary is not None else None,
            "CL_primary_change": new_cl - PREVIOUS["CL_primary"] if new_cl is not None else None,
        },
    }


def write_domain_identity_audit(output_dir: Path, domain: Mapping[str, Any], geometry: Mapping[str, Any]) -> None:
    payload = {"domain_identity": domain, "patch_geometry": geometry}
    base.write_json(output_dir / "domain_identity_audit.json", payload)
    lines = ["# Domain Identity Audit", ""]
    lines.append(f"- mesh identity: `{domain['mesh_identity']}`")
    lines.append(f"- y range: `{domain['mesh_y_min_m']}..{domain['mesh_y_max_m']}` m")
    lines.append(f"- y span: `{domain['mesh_y_span_m']}` m")
    lines.append(f"- current authority half/full span: `{domain['authority_half_span_m']}` / `{domain['authority_full_span_m']}` m")
    lines.append(f"- patch on y=0: `{domain['root_plane_patch_original']}`")
    lines.append(f"- outboard span patch: `{domain['outboard_span_patch_original']}`")
    lines.append(f"- previous Sref in forceCoeffs: `{domain['previous_forceCoeffs_sref_m2']}` m^2")
    lines.append(f"- corrected Sref in forceCoeffs: `{domain['corrected_forceCoeffs_sref_m2']}` m^2")
    lines.append(f"- coefficient correction: {domain['coefficient_correction']}")
    lines.append("")
    lines.append("| patch | y min | y max | x min/max | z min/max |")
    lines.append("|---|---:|---:|---|---|")
    for name, data in geometry["patches"].items():
        extent = data["extent"]
        lines.append(
            f"| `{name}` | `{extent['y']['min']}` | `{extent['y']['max']}` | "
            f"`[{extent['x']['min']}, {extent['x']['max']}]` | "
            f"`[{extent['z']['min']}, {extent['z']['max']}]` |"
        )
    (output_dir / "domain_identity_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_patch_role_classification(output_dir: Path, patch_roles: Mapping[str, Any]) -> None:
    base.write_json(output_dir / "patch_role_classification.json", patch_roles)
    lines = ["# Patch Role Classification", ""]
    lines.append(f"- mesh identity: `{patch_roles['mesh_identity']}`")
    lines.append(f"- root symmetry original patch: `{patch_roles['root_symmetry_original_patch']}`")
    lines.append(f"- physical tip original patches: `{patch_roles['physical_tip_original_patches']}`")
    lines.append("")
    lines.append("| original patch | corrected patch | role | original type | nFaces |")
    lines.append("|---|---|---|---|---:|")
    for original, data in patch_roles["roles"].items():
        lines.append(
            f"| `{original}` | `{data['corrected_patch']}` | `{data['role']}` | "
            f"`{data['original_type']}` | {data['nFaces']} |"
        )
    (output_dir / "patch_role_classification.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_bc_policy(output_dir: Path, case_setup: Mapping[str, Any]) -> None:
    lines = ["# Corrected Boundary-Condition Policy", ""]
    lines.append("- mesh convention: `half-wing`")
    lines.append("- `root_symmetry` uses OpenFOAM `symmetryPlane` patch and field BCs.")
    lines.append("- `root_symmetry` is excluded from all `forceCoeffs` and `forces` functionObjects.")
    lines.append("- main upper/lower walls, physical tip, and trailing edge use noSlip wall BCs.")
    lines.append("- farfield/outlet keep the previous successful freestream/open convention.")
    lines.append("")
    lines.append("| role | patches | U/p/nut/nuTilda policy |")
    lines.append("|---|---|---|")
    lines.append(f"| root_symmetry | `{case_setup['root_symmetry']}` | `symmetryPlane` for all fields |")
    lines.append(f"| solid walls | `{case_setup['solid_walls']}` | `noSlip`, `zeroGradient`, wall function, `nuTilda fixedValue 0` |")
    lines.append(f"| flow boundaries | `{case_setup['flow_boundaries']}` | `{case_setup['flow_bc_policy']}` |")
    lines.append("")
    lines.append(f"- force groups: `{case_setup['force_groups']}`")
    (output_dir / "corrected_bc_policy.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_force_normalization_policy(output_dir: Path, case_setup: Mapping[str, Any]) -> None:
    text = f"""# Force Normalization Policy

- Mesh convention: `{case_setup['domain_identity']}`.
- Full-wing authority Sref: `{FULL_REF_AREA_M2}` m^2.
- Corrected half-wing Sref: `{HALF_REF_AREA_M2}` m^2.
- `forceCoeffs` uses the half-wing Sref because the solved domain is the half-wing.
- Raw half-domain coefficients are therefore also full-wing-equivalent under mirror symmetry:
  `C = F_half / (q * S_half) = (2 F_half) / (q * S_full)`.
- Root symmetry is a computational plane and contributes no aerodynamic force.
- Physical diagnostic force groups include only `physical_tip` and `te_wall` unless a closure wall appears.
"""
    (output_dir / "force_normalization_policy.md").write_text(text, encoding="utf-8")


def write_patch_alias_mapping(output_dir: Path, alias_mapping: Mapping[str, Any]) -> None:
    base.write_json(output_dir / "patch_alias_mapping.json", alias_mapping)


def write_patch_metadata_fix_report(
    output_dir: Path,
    alias_mapping: Mapping[str, Any],
    corrected_geometry: Mapping[str, Any],
) -> None:
    lines = ["# Patch Metadata Fix Report", ""]
    lines.append("- topology edit: none")
    lines.append("- edited metadata: patch names/classes in `constant/polyMesh/boundary` only")
    lines.append("- reason: original `tip_left` is the y=0 root plane in a half-wing domain")
    lines.append("")
    lines.append("| original patch | corrected patch | role | generated boundary class |")
    lines.append("|---|---|---|---|")
    for original, data in alias_mapping["aliases"].items():
        lines.append(
            f"| `{original}` | `{data['corrected_patch']}` | `{data['role']}` | `{data['boundary_class']}` |"
        )
    lines.append("")
    lines.append(f"- corrected domain geometry note: `{corrected_geometry['engineering_note']}`")
    (output_dir / "patch_metadata_fix_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_reports(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    verdict = manifest["verdict"]
    converted = manifest["corrected_coefficients"]
    yplus = manifest["yPlus"]
    residuals = manifest["residuals"]
    stability = manifest["force_stability"]
    commands = manifest["commands"]
    split = manifest["force_split"]
    comparison = manifest["before_after_comparison"]
    failure = manifest["failure"]

    route_lines = ["# Corrected Route-Smoke Report", ""]
    route_lines.append(f"- status: `{verdict['status']}`")
    route_lines.append(f"- mesh identity: `{verdict['mesh_identity']}`")
    route_lines.append(f"- simpleFoam ran: `{verdict['simpleFoam_ran']}`")
    route_lines.append(f"- dry-run passed: `{verdict['dry_run_passed']}`")
    route_lines.append(f"- yPlus postprocess passed: `{verdict['yPlus_postprocess_passed']}`")
    if failure:
        route_lines.append("- coefficient status: `not_valid_route_smoke_values; last unstable values are listed for diagnosis only`")
    for key in (
        "CD_primary_raw_half_sref",
        "CL_primary_raw_half_sref",
        "CD_primary_fullwing_equivalent",
        "CL_primary_fullwing_equivalent",
        "CD_total_raw_half_sref",
        "CD_total_fullwing_equivalent",
        "CD_diagnostic_sum_excluding_root",
        "CD_physical_tip",
        "CD_te_wall",
    ):
        route_lines.append(f"- {key}: `{converted.get(key)}`")
    for name, command in commands.items():
        if command:
            route_lines.append(f"- {name}: rc `{command.get('returncode')}`, elapsed_s `{command.get('elapsed_s')}`")
    if failure:
        route_lines.append(f"- failure class: `{failure.get('class')}`")
        route_lines.append(f"- failure log: `{failure.get('log')}`")
        evidence = failure.get("evidence")
        if isinstance(evidence, Mapping) and "force_window_stability" in evidence:
            route_lines.append(f"- failure evidence: `{evidence['force_window_stability']}`")
            route_lines.append(f"- failure note: {evidence.get('note')}")
        else:
            route_lines.append(f"- failure evidence: `{evidence}`")
    (output_dir / "corrected_route_smoke_report.md").write_text("\n".join(route_lines) + "\n", encoding="utf-8")

    force_lines = ["# Corrected Force Breakdown Report", ""]
    if failure:
        force_lines.append("The values below are last unstable values from a blocked solver attempt, not accepted route-smoke coefficients.")
        force_lines.append("")
    force_lines.append("| coefficient | value |")
    force_lines.append("|---|---:|")
    for key, value in converted.items():
        force_lines.append(f"| `{key}` | `{value}` |")
    force_lines.append("")
    force_lines.append("| forceCoeffs group | final Cd | final Cl |")
    force_lines.append("|---|---:|---:|")
    for group, data in manifest["coefficients"].get("functions", {}).items():
        last = data.get("last") or {}
        force_lines.append(f"| `{group}` | `{last.get('Cd')}` | `{last.get('Cl')}` |")
    (output_dir / "corrected_force_breakdown_report.md").write_text("\n".join(force_lines) + "\n", encoding="utf-8")

    y_lines = ["# Corrected yPlus Report", ""]
    y_lines.append(f"- primary main-wall summary: `{yplus.get('primary_main_wall_summary')}`")
    y_lines.append("")
    y_lines.append("| patch | mean | p90 | p95 | p99 | max | count |")
    y_lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for patch, data in yplus.get("patches", {}).items():
        y_lines.append(
            f"| `{patch}` | `{data.get('mean')}` | `{data.get('p90')}` | `{data.get('p95')}` | "
            f"`{data.get('p99')}` | `{data.get('max')}` | `{data.get('count')}` |"
        )
    (output_dir / "corrected_yplus_report.md").write_text("\n".join(y_lines) + "\n", encoding="utf-8")

    stability_lines = ["# Corrected Residual / Force Stability Report", ""]
    stability_lines.append(f"- residuals: `{residuals}`")
    stability_lines.append(f"- force final-window stability: `{stability}`")
    (output_dir / "corrected_residual_force_stability_report.md").write_text(
        "\n".join(stability_lines) + "\n",
        encoding="utf-8",
    )

    if verdict["pressure_viscous_split_available"]:
        split_lines = ["# Corrected Pressure / Viscous Split Report", ""]
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
        (output_dir / "corrected_pressure_viscous_split_report.md").write_text(
            "\n".join(split_lines) + "\n",
            encoding="utf-8",
        )

    comp_lines = ["# Before / After Convention Comparison", ""]
    comp_lines.append(f"- previous: `{comparison['previous']}`")
    comp_lines.append(f"- corrected: `{comparison['corrected']}`")
    comp_lines.append(f"- delta: `{comparison['delta']}`")
    comp_lines.append("")
    if failure:
        comp_lines.append("- corrected coefficient values are unstable last-attempt diagnostics, not accepted aerodynamic coefficients.")
    comp_lines.append("- CD_total changed because the root plane is no longer a noSlip wall and half-wing forces use half-wing Sref.")
    comp_lines.append("- Diagnostic root contamination is removed from forceCoeffs.")
    comp_lines.append("- CD_primary should be judged under the corrected half-Sref convention, not against the previous full-Sref half-domain number.")
    comp_lines.append("- yPlus remains wall-resolved-like if the corrected yPlus mean/p95 stay below 5/10.")
    comp_lines.append(f"- ready for AoA/CL sweep: `{verdict['ready_for_aoa_cl_sweep']}`")
    (output_dir / "before_after_convention_comparison.md").write_text("\n".join(comp_lines) + "\n", encoding="utf-8")

    verdict_lines = ["# Phase 4 Domain Convention Fix Verdict", ""]
    answers = [
        ("1. Is the current mesh half-wing or full-wing?", verdict["mesh_identity"]),
        ("2. Which patch was wrongly treated as physical wall?", verdict["wrongly_wall_treated_patch"]),
        ("3. Was root_symmetry correctly applied if needed?", verdict["root_symmetry_correctly_applied"]),
        ("4. What reference area convention is used?", verdict["reference_area_convention"]),
        ("5. What are corrected CD_primary and CL_primary?", {
            "status": "not valid; solver force history unstable before 500 iterations" if failure else "valid route-smoke",
            "last_unstable_CD_primary": converted.get("CD_primary_fullwing_equivalent"),
            "last_unstable_CL_primary": converted.get("CL_primary_fullwing_equivalent"),
        }),
        ("6. What are corrected CD_total and diagnostic CD sum?", {
            "status": "not valid; solver force history unstable before 500 iterations" if failure else "valid route-smoke",
            "last_unstable_CD_total": converted.get("CD_total_fullwing_equivalent"),
            "diagnostic_CD_sum_excluding_root": converted.get("CD_diagnostic_sum_excluding_root"),
            "diagnostic_fraction": verdict["diagnostic_fraction_of_total_excluding_root"],
        }),
        ("7. Did yPlus remain wall-resolved?", verdict["yplus_wall_resolved_like"]),
        ("8. Is diagnostic patch contamination resolved?", verdict["diagnostic_patch_contamination_resolved"]),
        ("9. Is the result ready for AoA/CL sweep?", verdict["ready_for_aoa_cl_sweep"]),
        ("10. Is it comparable to XFOIL yet, or only ready for comparable-CL sweep?", verdict["xfoil_note"]),
    ]
    for question, answer in answers:
        verdict_lines.append(f"{question}\n   - `{answer}`")
    (output_dir / "phase4_domain_convention_fix_verdict.md").write_text(
        "\n".join(verdict_lines) + "\n",
        encoding="utf-8",
    )


def write_rerun(output_dir: Path, source_case: Path) -> None:
    text = f"""# RERUN

From `/Volumes/Samsung SSD/hpa-mdo`:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/run_wo006_true_baseline_domain_convention_fix.py \\
  --source-case {shlex.quote(str(source_case))} \\
  --output-dir {shlex.quote(str(output_dir))} \\
  --clean
```

The runner copies the accepted true Baseline swept C-grid `polyMesh`, renames
the y=0 `tip_left` metadata to `root_symmetry`, sets it to `symmetryPlane`, uses
half-wing Sref for forceCoeffs, excludes root symmetry from all forces, and
reruns only the same operating-point route-smoke.
"""
    (output_dir / "RERUN.md").write_text(text, encoding="utf-8")


def extent_axis_close(extent: Mapping[str, Mapping[str, float]], axis: str, value: float, tol: float = 1e-6) -> bool:
    return abs(float(extent[axis]["min"]) - value) <= tol and abs(float(extent[axis]["max"]) - value) <= tol


def boundary_class_for_role(role: str) -> str:
    if role == "root_symmetry":
        return "symmetryPlane"
    if role in {"main_lifting_wall_upper", "main_lifting_wall_lower", "physical_tip_wall", "trailing_edge_wall", "diagnostic_wall"}:
        return "wall"
    return "patch"


def force_inclusion_for_role(role: str) -> str:
    if role in {"main_lifting_wall_upper", "main_lifting_wall_lower"}:
        return "primary_and_total"
    if role in {"physical_tip_wall", "trailing_edge_wall", "diagnostic_wall"}:
        return "diagnostic_and_total"
    if role == "root_symmetry":
        return "excluded"
    return "excluded"


if __name__ == "__main__":
    main()
