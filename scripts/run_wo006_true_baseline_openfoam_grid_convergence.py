#!/usr/bin/env python3
"""Run a structured-hexa OpenFOAM grid-convergence study for true Baseline A."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import time
from typing import Any, Mapping, Sequence

from cfd_rescue.baseline_geometry import interpolate_station, load_baseline_authority
from cfd_rescue.polyfoam import write_openfoam_case
from cfd_rescue.swept_cgrid import build_swept_cgrid_mesh
from cfd_rescue.swept_hexa import mesh_quality_summary
import run_wo006_true_baseline_domain_convention_fix as convention
import run_wo006_true_baseline_openfoam_route_smoke as base
import run_wo006_true_baseline_solver_stability as stability


WO006_ROOT = (
    Path(__file__).resolve().parents[1]
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_true_baseline_grid_convergence"
OPENFOAM_WRAPPER = base.OPENFOAM_WRAPPER
MEDIUM_SOURCE_CASE = convention.base.DEFAULT_SOURCE_CASE

BASE_HALF_WING_STATION_PLAN: tuple[int, ...] = (10, 10, 10, 10, 12, 10, 8, 8)
GRID_SCALES: tuple[tuple[str, float], ...] = (
    ("coarse", 0.75),
    ("medium", 1.0),
    ("fine", 1.25),
)
BASE_N_PERIM = 192
BASE_N_RADIAL = 64
FIRST_LAYER_HEIGHT_M = 5.0e-5
FARFIELD_CHORDS = 10.0
WAKE_LENGTH_CHORDS = 8.0


@dataclass(frozen=True)
class GridLadderSpec:
    case_id: str
    scale: float
    n_perim: int
    n_radial: int
    station_plan: tuple[int, ...]

    @property
    def span_cells(self) -> int:
        return sum(self.station_plan)

    @property
    def station_count(self) -> int:
        return self.span_cells + 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--openfoam", default=OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--levels", nargs="+", default=["coarse", "medium", "fine"])
    parser.add_argument("--no-reuse-existing-rungs", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=5400.0)
    parser.add_argument("--first-iterations", type=int, default=200)
    parser.add_argument("--final-iterations", type=int, default=500)
    args = parser.parse_args()

    manifest = run_grid_convergence(
        output_dir=args.output_dir,
        openfoam_command=args.openfoam,
        clean=args.clean,
        requested_levels=tuple(args.levels),
        reuse_existing_rungs=not args.no_reuse_existing_rungs,
        timeout_seconds=args.timeout_seconds,
        first_iterations=args.first_iterations,
        final_iterations=args.final_iterations,
    )
    print(json.dumps(manifest["verdict"], indent=2, sort_keys=True))


def build_grid_ladder_specs() -> tuple[GridLadderSpec, ...]:
    specs: list[GridLadderSpec] = []
    for case_id, scale in GRID_SCALES:
        specs.append(
            GridLadderSpec(
                case_id=case_id,
                scale=scale,
                n_perim=_even_round(BASE_N_PERIM * scale),
                n_radial=max(8, int(round(BASE_N_RADIAL * scale))),
                station_plan=scale_station_plan(BASE_HALF_WING_STATION_PLAN, scale),
            )
        )
    return tuple(specs)


def scale_station_plan(plan: Sequence[int], scale: float) -> tuple[int, ...]:
    return tuple(max(1, int(round(value * scale))) for value in plan)


def build_force_groups(patch_names: Sequence[str]) -> dict[str, tuple[str, ...]]:
    names = tuple(patch_names)
    primary = tuple(name for name in ("airfoil_upper", "airfoil_lower", "wing_upper", "wing_lower") if name in names)
    artificial_tips = tuple(name for name in ("physical_tip_left", "physical_tip_right", "physical_tip", "tip_left", "tip_right") if name in names)
    trailing_edges = tuple(name for name in ("te_wall",) if name in names)
    diagnostic_walls = tuple(name for name in ("closure_wall",) if name in names)
    groups: dict[str, tuple[str, ...]] = {
        "primary": primary,
        "total": primary + artificial_tips + trailing_edges + diagnostic_walls,
        "total_physical": primary + trailing_edges,
    }
    for patch in artificial_tips + trailing_edges + diagnostic_walls:
        groups[patch] = (patch,)
    return {name: patches for name, patches in groups.items() if patches}


def build_boundary_contract(patch_names: Sequence[str]) -> dict[str, tuple[str, ...]]:
    names = tuple(patch_names)
    wall_patches = tuple(name for name in ("airfoil_upper", "airfoil_lower", "wing_upper", "wing_lower", "te_wall") if name in names)
    artificial_symmetry_patches = tuple(name for name in ("physical_tip_left", "physical_tip_right") if name in names)
    flow_patches = tuple(
        name
        for name in names
        if any(hint in name.lower() for hint in base.FLOW_PATCH_HINTS)
    )
    return {
        "wall_patches": wall_patches,
        "artificial_symmetry_patches": artificial_symmetry_patches,
        "flow_patches": flow_patches,
    }


def run_grid_convergence(
    *,
    output_dir: Path,
    openfoam_command: str,
    clean: bool,
    requested_levels: Sequence[str],
    reuse_existing_rungs: bool,
    timeout_seconds: float,
    first_iterations: int,
    final_iterations: int,
) -> dict[str, Any]:
    start = time.monotonic()
    output_dir = output_dir.resolve()
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    spec_by_name = {spec.case_id: spec for spec in build_grid_ladder_specs()}
    specs = [spec_by_name[name] for name in requested_levels if name in spec_by_name]
    if not specs:
        raise RuntimeError(f"no valid ladder levels requested: {requested_levels}")

    rung_results = [
        run_or_reuse_rung(
            output_dir=output_dir,
            spec=spec,
            openfoam_command=openfoam_command,
            reuse_existing_rungs=reuse_existing_rungs,
            timeout_seconds=timeout_seconds,
            first_iterations=first_iterations,
            final_iterations=final_iterations,
        )
        for spec in specs
    ]
    comparisons = build_pairwise_comparisons(rung_results)
    verdict = build_verdict(rung_results, comparisons)

    manifest = {
        "schema_version": "wo006_true_baseline_openfoam_grid_convergence.v1",
        "created_at_utc": base.utc_now(),
        "output_dir": str(output_dir),
        "openfoam_command": openfoam_command,
        "same_geometry_contract": {
            "geometry_authority": str(convention.base.DEFAULT_SOURCE_CASE),
            "first_layer_height_m": FIRST_LAYER_HEIGHT_M,
            "farfield_chords": FARFIELD_CHORDS,
            "wake_length_chords": WAKE_LENGTH_CHORDS,
            "aoa_deg": base.AOA_DEG,
            "velocity_mps": base.VELOCITY_MPS,
            "force_group_contract": "preserve primary/total/individual diagnostics and add total_physical",
            "artificial_tip_treatment": "physical_tip_left/right set to symmetryPlane after mirrorMesh",
            "physical_drag_definition": "total_physical = primary + te_wall; artificial mirrored tip closures excluded",
        },
        "ladder_specs": [serialize_spec(spec) for spec in specs],
        "rungs": rung_results,
        "pairwise_comparisons": comparisons,
        "verdict": verdict,
        "elapsed_s": time.monotonic() - start,
    }
    write_json(output_dir / "grid_convergence_manifest.json", manifest)
    write_report(output_dir / "grid_convergence_report.md", manifest)
    write_rerun(output_dir / "RERUN.md", specs)
    return manifest


def run_rung(
    *,
    output_dir: Path,
    spec: GridLadderSpec,
    openfoam_command: str,
    timeout_seconds: float,
    first_iterations: int,
    final_iterations: int,
) -> dict[str, Any]:
    rung_dir = output_dir / "openfoam_cases" / spec.case_id
    seed_case_dir = rung_dir / "halfwing_seed"
    corrected_case_dir = rung_dir / "halfwing_corrected"
    fullwing_case_dir = rung_dir / "fullwing_artificial_tip_symmetry"
    authority = load_baseline_authority(
        n_perim=spec.n_perim,
        airfoil_loop_mode="open_te_cgrid",
    )
    quality = build_seed_case(
        spec=spec,
        authority=authority,
        seed_case_dir=seed_case_dir,
    )

    source_geom = base.audit_patch_geometry(seed_case_dir / "constant" / "polyMesh")
    domain_identity = convention.classify_domain_identity(source_geom)
    patch_roles = convention.classify_patch_roles(source_geom, domain_identity)
    alias_mapping = convention.build_alias_mapping(patch_roles)
    corrected_setup = convention.generate_corrected_case(
        case_dir=corrected_case_dir,
        source_case=seed_case_dir,
        domain_identity=domain_identity,
        patch_roles=patch_roles,
        alias_mapping=alias_mapping,
        iterations=first_iterations,
    )

    if fullwing_case_dir.exists():
        shutil.rmtree(fullwing_case_dir)
    shutil.copytree(corrected_case_dir, fullwing_case_dir)
    stability.write_mirror_mesh_dict(fullwing_case_dir / "system" / "mirrorMeshDict")
    mirror_run = base.run_openfoam_command(
        fullwing_case_dir,
        openfoam_command=openfoam_command,
        command="mirrorMesh -overwrite",
        log_name="log.mirrorMesh",
        timeout_seconds=min(timeout_seconds, 1800.0),
    )
    split_report = stability.rewrite_fullwing_boundary_and_case(fullwing_case_dir)
    contract = apply_artificial_tip_boundary_contract(fullwing_case_dir, first_iterations)
    force_groups = build_force_groups(tuple(contract["patch_names"]))

    checkmesh = base.run_openfoam_command(
        fullwing_case_dir,
        openfoam_command=openfoam_command,
        command="checkMesh -meshQuality",
        log_name="log.checkMesh",
        timeout_seconds=min(timeout_seconds, 1800.0),
    )
    checkmesh_acceptance = stability.fullwing_checkmesh_acceptance({"checkMesh": checkmesh})
    dry_run = None
    first_run = None
    final_run = None
    yplus_post = None
    if checkmesh_acceptance["accepted_for_solver_smoke"]:
        dry_run = base.run_openfoam_command(
            fullwing_case_dir,
            openfoam_command=openfoam_command,
            command="simpleFoam -dry-run",
            log_name="log.simpleFoam_dry_run",
            timeout_seconds=600.0,
        )
        if dry_run["returncode"] == 0:
            first_run = run_simplefoam_with_guard(
                fullwing_case_dir,
                openfoam_command=openfoam_command,
                force_groups=force_groups,
                command="simpleFoam",
                log_name="log.simpleFoam_200",
                timeout_seconds=timeout_seconds,
            )
            (fullwing_case_dir / "log.simpleFoam").write_text(
                (fullwing_case_dir / "log.simpleFoam_200").read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
            coeffs_200 = base.parse_force_coefficients(fullwing_case_dir, force_groups)
            stable_200 = base.force_stability(coeffs_200.get("functions", {}).get("primary", {}).get("rows", []))
            if first_run["returncode"] == 0 and should_extend_after_first_run(coeffs_200, stable_200):
                base.update_control_dict(
                    fullwing_case_dir / "system" / "controlDict",
                    end_time=final_iterations,
                    start_from="latestTime",
                )
                final_run = run_simplefoam_with_guard(
                    fullwing_case_dir,
                    openfoam_command=openfoam_command,
                    force_groups=force_groups,
                    command="simpleFoam",
                    log_name="log.simpleFoam_500",
                    timeout_seconds=timeout_seconds,
                )
                (fullwing_case_dir / "log.simpleFoam").write_text(
                    (fullwing_case_dir / "log.simpleFoam_500").read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                )
            active_run = final_run or first_run
            if active_run and active_run["returncode"] == 0:
                yplus_post = base.run_openfoam_command(
                    fullwing_case_dir,
                    openfoam_command=openfoam_command,
                    command="simpleFoam -postProcess -func yPlus -latestTime",
                    log_name="log.yPlus",
                    timeout_seconds=900.0,
                )

    coefficients = base.parse_force_coefficients(fullwing_case_dir, force_groups)
    summary = augment_coefficient_summary(coefficients)
    force_split = base.parse_force_splits(fullwing_case_dir, force_groups)
    yplus = base.parse_yplus(fullwing_case_dir, contract["wall_patches"])
    residuals = base.parse_residuals(fullwing_case_dir / "log.simpleFoam")
    active_run = final_run or first_run
    total_physical_rows = coefficients.get("functions", {}).get("total_physical", {}).get("rows", [])
    stability_primary = gate_force_window_stability(
        base.force_stability(coefficients.get("functions", {}).get("primary", {}).get("rows", [])),
        active_run,
    )
    stability_physical = gate_force_window_stability(
        base.force_stability(total_physical_rows),
        active_run,
    )
    result = {
        "spec": serialize_spec(spec),
        "seed_mesh_quality": quality,
        "seed_case_dir": str(seed_case_dir),
        "corrected_halfwing_case_dir": str(corrected_case_dir),
        "corrected_halfwing_setup": corrected_setup,
        "case_dir": str(fullwing_case_dir),
        "mirrorMesh": mirror_run,
        "mirror_split_report": split_report,
        "boundary_contract": contract,
        "force_groups": {name: list(patches) for name, patches in force_groups.items()},
        "commands": {
            "checkMesh": checkmesh,
            "simpleFoam_dry_run": dry_run,
            "simpleFoam_200": first_run,
            "simpleFoam_500": final_run,
            "postProcess_yPlus": yplus_post,
        },
        "checkMesh_acceptance": checkmesh_acceptance,
        "coefficients": coefficients,
        "summary": summary,
        "pressure_viscous_split": force_split,
        "yPlus": yplus,
        "residuals": residuals,
        "force_window_stability": {
            "primary": stability_primary,
            "total_physical": stability_physical,
        },
    }
    write_json(rung_result_path(output_dir, spec.case_id), result)
    return result


def run_or_reuse_rung(
    *,
    output_dir: Path,
    spec: GridLadderSpec,
    openfoam_command: str,
    reuse_existing_rungs: bool,
    timeout_seconds: float,
    first_iterations: int,
    final_iterations: int,
) -> dict[str, Any]:
    if reuse_existing_rungs:
        existing = load_existing_rung_result(output_dir, spec.case_id)
        if existing is not None:
            return existing
    return run_rung(
        output_dir=output_dir,
        spec=spec,
        openfoam_command=openfoam_command,
        timeout_seconds=timeout_seconds,
        first_iterations=first_iterations,
        final_iterations=final_iterations,
    )


def build_seed_case(
    *,
    spec: GridLadderSpec,
    authority: Any,
    seed_case_dir: Path,
) -> dict[str, Any]:
    if seed_case_dir.exists():
        shutil.rmtree(seed_case_dir)
    if is_medium_reference_case(spec) and MEDIUM_SOURCE_CASE.exists():
        shutil.copytree(MEDIUM_SOURCE_CASE, seed_case_dir)
        metadata_path = seed_case_dir / "swept_ogrid_mesh_metadata.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            return dict(metadata.get("quality", {}))
        return {"status": "copied_existing_medium_source_case"}

    stations = build_halfwing_stations(authority, spec.station_plan)
    mesh = build_swept_cgrid_mesh(
        stations,
        n_radial=spec.n_radial,
        first_layer_height_m=FIRST_LAYER_HEIGHT_M,
        farfield_chords=FARFIELD_CHORDS,
        wake_length_chords=WAKE_LENGTH_CHORDS,
        case_id=f"{spec.case_id}_halfwing_seed",
    )
    quality = mesh_quality_summary(mesh)
    write_openfoam_case(
        seed_case_dir,
        mesh=mesh,
        ref_area=authority.reference.sref_full,
        ref_length=authority.reference.cref,
        ref_origin=base.REF_ORIGIN_M,
        aoa_deg=base.AOA_DEG,
        max_iterations=1,
        quality=quality,
    )
    return quality


def build_halfwing_stations(authority: Any, station_plan: Sequence[int]) -> list[Any]:
    stations: list[Any] = []
    for idx, n_sub in enumerate(station_plan):
        left = authority.half_stations[idx]
        right = authority.half_stations[idx + 1]
        block = [left] + [
            interpolate_station(left, right, step / n_sub)
            for step in range(1, n_sub)
        ]
        if idx == len(station_plan) - 1:
            block.append(right)
        stations.extend(block)
    return stations


def is_medium_reference_case(spec: GridLadderSpec) -> bool:
    return (
        spec.n_perim == BASE_N_PERIM
        and spec.n_radial == BASE_N_RADIAL
        and tuple(spec.station_plan) == BASE_HALF_WING_STATION_PLAN
    )


def apply_artificial_tip_boundary_contract(case_dir: Path, first_iterations: int) -> dict[str, Any]:
    boundary = base.parse_boundary(case_dir / "constant" / "polyMesh" / "boundary")["patches"]
    patch_names = tuple(boundary)
    contract = build_boundary_contract(patch_names)
    patch_types = {
        name: "wall" for name in contract["wall_patches"]
    } | {
        name: "symmetryPlane" for name in contract["artificial_symmetry_patches"]
    } | {
        name: boundary[name].get("type", "patch") for name in contract["flow_patches"]
    }
    rewrite_boundary_types(case_dir / "constant" / "polyMesh" / "boundary", patch_types)
    write_fullwing_case_dictionaries(
        case_dir,
        force_groups=build_force_groups(patch_names),
        wall_patches=contract["wall_patches"],
        artificial_symmetry_patches=contract["artificial_symmetry_patches"],
        flow_patches=contract["flow_patches"],
        max_iterations=first_iterations,
    )
    return {
        "patch_names": list(patch_names),
        "wall_patches": list(contract["wall_patches"]),
        "artificial_symmetry_patches": list(contract["artificial_symmetry_patches"]),
        "flow_patches": list(contract["flow_patches"]),
        "artificial_tip_treatment": "symmetryPlane",
    }


def write_fullwing_case_dictionaries(
    case_dir: Path,
    *,
    force_groups: Mapping[str, Sequence[str]],
    wall_patches: Sequence[str],
    artificial_symmetry_patches: Sequence[str],
    flow_patches: Sequence[str],
    max_iterations: int,
) -> None:
    flow_policy = base.build_flow_bc_policy(flow_patches)
    (case_dir / "system" / "controlDict").write_text(
        control_dict_text(force_groups=force_groups, max_iterations=max_iterations, start_from="startTime"),
        encoding="utf-8",
    )
    (case_dir / "system" / "fvSchemes").write_text(base.fv_schemes_text(), encoding="utf-8")
    (case_dir / "system" / "fvSolution").write_text(base.fv_solution_text(), encoding="utf-8")
    (case_dir / "system" / "meshQualityDict").write_text(base.mesh_quality_dict_text(), encoding="utf-8")
    (case_dir / "constant" / "transportProperties").write_text(base.transport_properties_text(), encoding="utf-8")
    (case_dir / "constant" / "turbulenceProperties").write_text(base.turbulence_properties_text(), encoding="utf-8")
    (case_dir / "0" / "U").write_text(
        u_field_text(wall_patches, artificial_symmetry_patches, flow_policy),
        encoding="utf-8",
    )
    (case_dir / "0" / "p").write_text(
        p_field_text(wall_patches, artificial_symmetry_patches, flow_policy),
        encoding="utf-8",
    )
    (case_dir / "0" / "nut").write_text(
        nut_field_text(wall_patches, artificial_symmetry_patches, flow_policy),
        encoding="utf-8",
    )
    (case_dir / "0" / "nuTilda").write_text(
        nu_tilda_field_text(wall_patches, artificial_symmetry_patches, flow_policy),
        encoding="utf-8",
    )


def rewrite_boundary_types(path: Path, patch_types: Mapping[str, str]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for patch, patch_type in patch_types.items():
        pattern = base.re.compile(
            rf"(^\s*{base.re.escape(patch)}\s*\n\s*\{{.*?^\s*type\s+)([A-Za-z0-9_]+)(\s*;)",
            base.re.MULTILINE | base.re.DOTALL,
        )
        text, count = pattern.subn(rf"\g<1>{patch_type}\g<3>", text, count=1)
        if count != 1:
            raise RuntimeError(f"could not update boundary patch type for {patch}")
    path.write_text(text, encoding="utf-8")


def control_dict_text(
    *,
    force_groups: Mapping[str, Sequence[str]],
    max_iterations: int,
    start_from: str,
) -> str:
    force_objects = "\n".join(
        base.force_coeff_function_text(name=f"forceCoeffs_{name}", patches=patches)
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


def u_field_text(
    wall_patches: Sequence[str],
    artificial_symmetry_patches: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    u = base.inlet_velocity(base.AOA_DEG)
    return (
        base.field_header("volVectorField", "U", "[0 1 -1 0 0 0 0]", f"uniform {base.vec(u)}")
        + "\n".join(base.flow_u_entry(name, policy["U"], u) for name, policy in flow_bc_policy.items())
        + "\n"
        + "\n".join(convention.symmetry_entry(name) for name in artificial_symmetry_patches)
        + "\n"
        + "\n".join(base.no_slip_entry(name) for name in wall_patches)
        + "\n}\n"
    )


def p_field_text(
    wall_patches: Sequence[str],
    artificial_symmetry_patches: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    return (
        base.field_header("volScalarField", "p", "[0 2 -2 0 0 0 0]", "uniform 0")
        + "\n".join(base.flow_p_entry(name, policy["p"]) for name, policy in flow_bc_policy.items())
        + "\n"
        + "\n".join(convention.symmetry_entry(name) for name in artificial_symmetry_patches)
        + "\n"
        + "\n".join(base.zero_gradient_entry(name) for name in wall_patches)
        + "\n}\n"
    )


def nut_field_text(
    wall_patches: Sequence[str],
    artificial_symmetry_patches: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    return (
        base.field_header("volScalarField", "nut", "[0 2 -1 0 0 0 0]", "uniform 0")
        + "\n".join(base.calculated_scalar_entry(name) for name in flow_bc_policy)
        + "\n"
        + "\n".join(convention.symmetry_entry(name) for name in artificial_symmetry_patches)
        + "\n"
        + "\n".join(base.nut_wall_entry(name) for name in wall_patches)
        + "\n}\n"
    )


def nu_tilda_field_text(
    wall_patches: Sequence[str],
    artificial_symmetry_patches: Sequence[str],
    flow_bc_policy: Mapping[str, Mapping[str, str]],
) -> str:
    return (
        base.field_header("volScalarField", "nuTilda", "[0 2 -1 0 0 0 0]", "uniform 4.0e-5")
        + "\n".join(base.flow_nu_tilda_entry(name, policy["nuTilda"]) for name, policy in flow_bc_policy.items())
        + "\n"
        + "\n".join(convention.symmetry_entry(name) for name in artificial_symmetry_patches)
        + "\n"
        + "\n".join(base.fixed_value_scalar_entry(name, "0") for name in wall_patches)
        + "\n}\n"
    )


def augment_coefficient_summary(coefficients: Mapping[str, Any]) -> dict[str, float | None]:
    summary = dict(coefficients.get("summary", {}))
    total_physical = coefficients.get("functions", {}).get("total_physical", {}).get("last")
    if total_physical:
        summary["CD_total_physical"] = base.float_or_none(total_physical.get("Cd"))
        summary["CL_total_physical"] = base.float_or_none(total_physical.get("Cl"))
    else:
        summary["CD_total_physical"] = None
        summary["CL_total_physical"] = None
    return summary


def build_pairwise_comparisons(rungs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for left, right in zip(rungs[:-1], rungs[1:]):
        left_summary = left.get("summary", {})
        right_summary = right.get("summary", {})
        left_split = left.get("pressure_viscous_split", {}).get("groups", {})
        right_split = right.get("pressure_viscous_split", {}).get("groups", {})
        pairs.append(
            {
                "pair": f"{left['spec']['case_id']}->{right['spec']['case_id']}",
                "from_case": left["spec"]["case_id"],
                "to_case": right["spec"]["case_id"],
                "percent_change": {
                    "CD_primary": percent_change(left_summary.get("CD_primary"), right_summary.get("CD_primary")),
                    "CL_primary": percent_change(left_summary.get("CL_primary"), right_summary.get("CL_primary")),
                    "CD_total_physical": percent_change(
                        left_summary.get("CD_total_physical"),
                        right_summary.get("CD_total_physical"),
                    ),
                    "CD_primary_pressure": percent_change(
                        split_value(left_split, "primary", "CD_pressure"),
                        split_value(right_split, "primary", "CD_pressure"),
                    ),
                    "CD_primary_viscous": percent_change(
                        split_value(left_split, "primary", "CD_viscous"),
                        split_value(right_split, "primary", "CD_viscous"),
                    ),
                    "CD_total_physical_pressure": percent_change(
                        split_value(left_split, "total_physical", "CD_pressure"),
                        split_value(right_split, "total_physical", "CD_pressure"),
                    ),
                    "CD_total_physical_viscous": percent_change(
                        split_value(left_split, "total_physical", "CD_viscous"),
                        split_value(right_split, "total_physical", "CD_viscous"),
                    ),
                },
            }
        )
    return pairs


def should_extend_after_first_run(coeffs: Mapping[str, Any], stability_window: Mapping[str, Any]) -> bool:
    rows = coeffs.get("functions", {}).get("primary", {}).get("rows", [])
    if not rows:
        return False
    last = rows[-1]
    finite = all(
        value is not None and math.isfinite(float(value))
        for value in (last.get("Cd"), last.get("Cl"))
    )
    if not finite:
        return False
    if force_runaway_detected(coeffs):
        return False
    return stability_window.get("route_smoke_stable") is not True


def force_runaway_detected(coeffs: Mapping[str, Any]) -> bool:
    return stability.first_divergence_time(coeffs) is not None


def gate_force_window_stability(
    stability_window: Mapping[str, Any],
    run_info: Mapping[str, Any] | None,
) -> dict[str, Any]:
    gated = dict(stability_window)
    if not run_info or run_info.get("returncode") != 0:
        gated["route_smoke_stable"] = False
        if run_info and run_info.get("stopped_by_runaway_guard"):
            gated["status"] = "runaway_guard_triggered"
            gated["runaway_time"] = run_info.get("runaway_time")
        elif run_info:
            gated["status"] = "solver_not_completed"
    return gated


def run_simplefoam_with_guard(
    case_dir: Path,
    *,
    openfoam_command: str,
    force_groups: Mapping[str, Sequence[str]],
    command: str,
    log_name: str,
    timeout_seconds: float,
    poll_seconds: float = 5.0,
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
    stopped_by_runaway = False
    divergence_time = None

    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            ["/usr/bin/time", "-l", openfoam_command, "-c", wrapped],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        returncode: int | str | None = None
        while True:
            try:
                returncode = proc.wait(timeout=poll_seconds)
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - started
                coeffs = base.parse_force_coefficients(run_dir, force_groups)
                divergence_time = stability.first_divergence_time(coeffs)
                if divergence_time is not None:
                    stopped_by_runaway = True
                    terminate_process_group(proc.pid)
                    proc.wait(timeout=30.0)
                    returncode = "stopped_by_runaway_guard"
                    break
                if elapsed >= timeout_seconds:
                    timed_out = True
                    terminate_process_group(proc.pid)
                    proc.wait(timeout=30.0)
                    returncode = 124
                    break
        if timed_out:
            log.write(f"\nTIMEOUT after {timeout_seconds:.1f} seconds\n")
        if stopped_by_runaway:
            log.write(
                "\nRUNAWAY_GUARD "
                f"triggered at pseudo-time {divergence_time}; "
                "terminating simpleFoam because |CD|>1 or |CL|>3 on the primary force group.\n"
            )

    base.normalize_logs(run_dir)
    shutil.copytree(run_dir, case_dir, dirs_exist_ok=True)
    return {
        "command": command,
        "log": str(case_dir / log_name),
        "returncode": returncode,
        "timed_out": timed_out,
        "stopped_by_runaway_guard": stopped_by_runaway,
        "runaway_time": divergence_time,
        "elapsed_s": time.monotonic() - started,
        "resource_usage": base.parse_time_l_log(case_dir / log_name),
        "tail": base.tail(case_dir / log_name, 80),
    }


def terminate_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def build_verdict(rungs: Sequence[Mapping[str, Any]], comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    blocking = []
    for rung in rungs:
        if not rung.get("checkMesh_acceptance", {}).get("accepted_for_solver_smoke"):
            blocking.append(f"{rung['spec']['case_id']}:checkMesh_not_solver_smoke_acceptable")
        active_run = rung.get("commands", {}).get("simpleFoam_500") or rung.get("commands", {}).get("simpleFoam_200")
        if not active_run or active_run.get("returncode") != 0:
            blocking.append(f"{rung['spec']['case_id']}:solver_not_completed")
    cd_changes = [
        abs(float(change))
        for comparison in comparisons
        for key, change in comparison.get("percent_change", {}).items()
        if key in {"CD_primary", "CD_total_physical"} and change is not None
    ]
    max_cd_change = max(cd_changes, default=None)
    demonstrated = not blocking and max_cd_change is not None and max_cd_change <= 5.0
    return {
        "study_status": "grid_independent_demonstrated" if demonstrated else "grid_independence_not_demonstrated",
        "blocking_items": blocking,
        "max_abs_cd_percent_change": max_cd_change,
        "cd_change_threshold_policy": {
            "demonstrated_if_max_change_percent_lte": 5.0,
            "clearly_not_independent_if_any_change_percent_gt": 10.0,
        },
        "do_not_update_design_power": not demonstrated,
        "engineering_conclusion": (
            "Current CFD is not grid-independent; do not update design power from this OpenFOAM line yet."
            if not demonstrated
            else "Grid convergence is provisionally demonstrated for this artificial-tip treatment."
        ),
    }


def write_report(path: Path, manifest: Mapping[str, Any]) -> None:
    lines = ["# True Baseline OpenFOAM Grid Convergence", ""]
    lines.append("## Setup")
    lines.append("")
    contract = manifest["same_geometry_contract"]
    lines.append(f"- geometry authority: `{contract['geometry_authority']}`")
    lines.append(f"- AoA: `{contract['aoa_deg']} deg`")
    lines.append(f"- velocity: `{contract['velocity_mps']} m/s`")
    lines.append(f"- artificial tip treatment: `{contract['artificial_tip_treatment']}`")
    lines.append(f"- physical drag definition: `{contract['physical_drag_definition']}`")
    lines.append("")
    lines.append("## Rungs")
    lines.append("")
    lines.append("| rung | scale | half-wing span cells | n_perim | n_radial | full-wing cells | CD_primary | CL_primary | CD_total_physical | y+ mean/p95/max | primary stable | total_physical stable |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|")
    for rung in manifest["rungs"]:
        summary = rung["summary"]
        check_metrics = rung["checkMesh_acceptance"].get("metrics", {})
        y_summary = rung["yPlus"].get("primary_main_wall_summary", {})
        primary_stable = rung["force_window_stability"]["primary"].get("route_smoke_stable")
        physical_stable = rung["force_window_stability"]["total_physical"].get("route_smoke_stable")
        lines.append(
            f"| `{rung['spec']['case_id']}` | `{rung['spec']['scale']}` | `{rung['spec']['span_cells']}` | "
            f"`{rung['spec']['n_perim']}` | `{rung['spec']['n_radial']}` | "
            f"`{check_metrics.get('cells')}` | `{summary.get('CD_primary')}` | `{summary.get('CL_primary')}` | "
            f"`{summary.get('CD_total_physical')}` | "
            f"`{y_summary.get('mean')}/{y_summary.get('p95')}/{y_summary.get('max')}` | "
            f"`{primary_stable}` | `{physical_stable}` |"
        )
    lines.append("")
    lines.append("## Pressure / Viscous Split")
    lines.append("")
    lines.append("| rung | CDp primary | CDv primary | CDp total_physical | CDv total_physical |")
    lines.append("|---|---:|---:|---:|---:|")
    for rung in manifest["rungs"]:
        groups = rung["pressure_viscous_split"]["groups"]
        lines.append(
            f"| `{rung['spec']['case_id']}` | "
            f"`{split_value(groups, 'primary', 'CD_pressure')}` | "
            f"`{split_value(groups, 'primary', 'CD_viscous')}` | "
            f"`{split_value(groups, 'total_physical', 'CD_pressure')}` | "
            f"`{split_value(groups, 'total_physical', 'CD_viscous')}` |"
        )
    lines.append("")
    lines.append("## Pairwise Delta")
    lines.append("")
    lines.append("| pair | dCD_primary % | dCL_primary % | dCD_total_physical % | dCDp primary % | dCDv primary % | dCDp total_physical % | dCDv total_physical % |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for comparison in manifest["pairwise_comparisons"]:
        delta = comparison["percent_change"]
        lines.append(
            f"| `{comparison['pair']}` | `{delta.get('CD_primary')}` | `{delta.get('CL_primary')}` | "
            f"`{delta.get('CD_total_physical')}` | `{delta.get('CD_primary_pressure')}` | "
            f"`{delta.get('CD_primary_viscous')}` | `{delta.get('CD_total_physical_pressure')}` | "
            f"`{delta.get('CD_total_physical_viscous')}` |"
        )
    lines.append("")
    lines.append("## Residuals")
    lines.append("")
    for rung in manifest["rungs"]:
        lines.append(f"### {rung['spec']['case_id']}")
        lines.append("")
        lines.append(f"- residual summary: `{rung['residuals']}`")
        lines.append(f"- primary force-window stability: `{rung['force_window_stability']['primary']}`")
        lines.append(f"- total_physical force-window stability: `{rung['force_window_stability']['total_physical']}`")
        lines.append("")
    lines.append("## Verdict")
    lines.append("")
    verdict = manifest["verdict"]
    lines.append(f"- study_status: `{verdict['study_status']}`")
    lines.append(f"- max_abs_cd_percent_change: `{verdict['max_abs_cd_percent_change']}`")
    lines.append(f"- blocking_items: `{verdict['blocking_items']}`")
    lines.append(f"- do_not_update_design_power: `{verdict['do_not_update_design_power']}`")
    lines.append(f"- engineering_conclusion: {verdict['engineering_conclusion']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rerun(path: Path, specs: Sequence[GridLadderSpec]) -> None:
    levels = " ".join(spec.case_id for spec in specs)
    path.write_text(
        f"""# Rerun

```
./.venv/bin/python scripts/run_wo006_true_baseline_openfoam_grid_convergence.py \\
  --clean \\
  --levels {levels}
```
""",
        encoding="utf-8",
    )


def serialize_spec(spec: GridLadderSpec) -> dict[str, Any]:
    return {
        "case_id": spec.case_id,
        "scale": spec.scale,
        "n_perim": spec.n_perim,
        "n_radial": spec.n_radial,
        "station_plan": list(spec.station_plan),
        "span_cells": spec.span_cells,
        "station_count": spec.station_count,
    }


def split_value(groups: Mapping[str, Any], group: str, key: str) -> float | None:
    payload = groups.get(group, {})
    split = payload.get("split_coefficients") if isinstance(payload, Mapping) else None
    value = None if split is None else split.get(key)
    return None if value is None else float(value)


def percent_change(old: float | None, new: float | None) -> float | None:
    if old is None or new is None:
        return None
    if abs(float(old)) < 1.0e-12:
        return None
    return 100.0 * (float(new) - float(old)) / abs(float(old))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rung_result_path(output_dir: Path, case_id: str) -> Path:
    return output_dir / "openfoam_cases" / case_id / "rung_result.json"


def load_existing_rung_result(output_dir: Path, case_id: str) -> dict[str, Any] | None:
    path = rung_result_path(output_dir, case_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _even_round(value: float) -> int:
    rounded = int(round(value))
    return rounded if rounded % 2 == 0 else rounded + 1


if __name__ == "__main__":
    main()
