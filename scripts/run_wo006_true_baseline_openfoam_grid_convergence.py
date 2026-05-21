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

BASE_HALF_WING_STATION_PLAN: tuple[int, ...] = (16, 16, 16, 16, 19, 16, 13, 13)
GRID_SCALES: tuple[tuple[str, float], ...] = (
    ("coarse", 0.75),
    ("medium", 1.0),
    ("fine", 1.25),
)
BASE_N_PERIM = 192
BASE_N_RADIAL = 64
FIRST_LAYER_HEIGHT_M = 7.0e-5
FARFIELD_CHORDS = 10.0
WAKE_LENGTH_CHORDS = 8.0
NEAR_WALL_GROWTH = 1.12
WAKE_CROSS_CELLS = 4
RUNAWAY_GUARD_MIN_TIME = 50
RUNAWAY_GUARD_ABS_CD = 10.0
RUNAWAY_GUARD_ABS_CL = 10.0

LOCAL_REFINEMENT_REGION_IDS: tuple[str, ...] = (
    "leading_edge",
    "trailing_edge",
    "boundary_layer",
    "near_wake",
    "downstream_wake",
    "wing_tip_vortex_region",
    "farfield",
)
LOCAL_REFINEMENT_SPACING_KEYS: tuple[str, ...] = (
    "surface_spacing_m",
    "first_layer_height_m",
    "bl_growth_rate",
    "bl_layer_count",
    "wake_streamwise_spacing_m",
    "tip_refinement_radius_m",
    "farfield_distance_chords",
)


@dataclass(frozen=True)
class GridLadderSpec:
    case_id: str
    scale: float
    n_perim: int
    n_radial: int
    station_plan: tuple[int, ...]
    local_refinement_regions: tuple[dict[str, Any], ...]
    quality_gate_contract: dict[str, Any]

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
    parser.add_argument(
        "--mesh-only",
        action="store_true",
        help="Generate/check all requested rungs and stop before solver even if the family gate passes.",
    )
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
        mesh_only=args.mesh_only,
    )
    print(json.dumps(manifest["verdict"], indent=2, sort_keys=True))


def build_grid_ladder_specs() -> tuple[GridLadderSpec, ...]:
    specs: list[GridLadderSpec] = []
    quality_gate_contract = build_mesh_quality_gate_contract()
    for case_id, scale in GRID_SCALES:
        n_perim = _even_round(BASE_N_PERIM * scale)
        n_radial = max(8, int(round(BASE_N_RADIAL * scale)))
        station_plan = scale_station_plan(BASE_HALF_WING_STATION_PLAN, scale)
        specs.append(
            GridLadderSpec(
                case_id=case_id,
                scale=scale,
                n_perim=n_perim,
                n_radial=n_radial,
                station_plan=station_plan,
                local_refinement_regions=build_local_refinement_regions(
                    scale=scale,
                    n_perim=n_perim,
                    n_radial=n_radial,
                    span_cells=sum(station_plan),
                ),
                quality_gate_contract=quality_gate_contract,
            )
        )
    return tuple(specs)


def build_local_refinement_regions(
    *,
    scale: float,
    n_perim: int,
    n_radial: int,
    span_cells: int,
) -> tuple[dict[str, Any], ...]:
    chord = base.REF_LENGTH_M
    surface_spacing = chord / n_perim
    wake_spacing = WAKE_LENGTH_CHORDS * chord / n_radial
    span_spacing = base.AUTHORITY_HALF_SPAN_M / max(span_cells, 1)
    bl_layer_count = max(1, min(n_radial // 2, 40))
    first_layer = FIRST_LAYER_HEIGHT_M

    def rules(
        *,
        local_surface_factor: float | None = None,
        first_layer_height_m: float | None = None,
        bl_growth_rate: float | None = None,
        bl_layers: int | None = None,
        wake_factor: float | None = None,
        tip_radius_factor: float | None = None,
        farfield_chords: float | None = None,
    ) -> dict[str, float | int | None]:
        payload: dict[str, float | int | None] = {
            "surface_spacing_m": None if local_surface_factor is None else surface_spacing * local_surface_factor,
            "first_layer_height_m": first_layer_height_m,
            "bl_growth_rate": bl_growth_rate,
            "bl_layer_count": bl_layers,
            "wake_streamwise_spacing_m": None if wake_factor is None else wake_spacing * wake_factor,
            "tip_refinement_radius_m": None if tip_radius_factor is None else chord * tip_radius_factor,
            "farfield_distance_chords": farfield_chords,
        }
        return {key: payload[key] for key in LOCAL_REFINEMENT_SPACING_KEYS}

    region_payloads = {
        "leading_edge": {
            "spacing_rules": rules(local_surface_factor=0.5),
            "scales_with": "airfoil cosine-resampled perimeter count; finer rungs reduce LE spacing with n_perim",
            "implementation": "open-TE C-grid perimeter distribution",
        },
        "trailing_edge": {
            "spacing_rules": rules(
                local_surface_factor=0.5,
                first_layer_height_m=first_layer,
                bl_growth_rate=NEAR_WALL_GROWTH,
                bl_layers=min(6, bl_layer_count),
                wake_factor=0.25,
            ),
            "scales_with": "same finite-TE C-grid stencil and wake-cross topology on every rung",
            "implementation": "generator-level TE wall plus lower-TE radial rebalance guard",
        },
        "boundary_layer": {
            "spacing_rules": rules(
                local_surface_factor=1.0,
                first_layer_height_m=first_layer,
                bl_growth_rate=NEAR_WALL_GROWTH,
                bl_layers=bl_layer_count,
            ),
            "scales_with": "same first-cell height; radial layer count scales with n_radial",
            "implementation": "wall-normal near-wall stack in section_cgrid",
        },
        "near_wake": {
            "spacing_rules": rules(wake_factor=0.5, first_layer_height_m=first_layer),
            "scales_with": "wake streamwise spacing scales with n_radial; wake cross cells remain fixed",
            "implementation": "internal C-grid wake block adjacent to finite TE",
        },
        "downstream_wake": {
            "spacing_rules": rules(wake_factor=1.0),
            "scales_with": "wake length remains 8 chords; downstream streamwise cells scale with n_radial",
            "implementation": "same downstream C-grid wake extension on every rung",
        },
        "wing_tip_vortex_region": {
            "spacing_rules": rules(local_surface_factor=1.0, tip_radius_factor=max(0.10, 1.5 * span_spacing / chord)),
            "scales_with": "spanwise station plan scales from the same bay subdivision logic",
            "implementation": "same swept-station tip cap topology; physical vortex refinement remains a required diagnostic zone",
        },
        "farfield": {
            "spacing_rules": rules(farfield_chords=FARFIELD_CHORDS),
            "scales_with": "farfield distance stays fixed at 10 chords so grid effects are not hidden by domain changes",
            "implementation": "outer C-grid boundary",
        },
    }
    return tuple(
        {
            "region_id": region_id,
            "refinement_scale": scale,
            "spacing_rules": region_payloads[region_id]["spacing_rules"],
            "scales_with": region_payloads[region_id]["scales_with"],
            "implementation": region_payloads[region_id]["implementation"],
        }
        for region_id in LOCAL_REFINEMENT_REGION_IDS
    )


def build_mesh_quality_gate_contract() -> dict[str, Any]:
    return {
        "schema_version": "wo006_hpa_mesh_quality_gate_contract.v1",
        "required_guards": [
            "no_open_cells",
            "no_negative_volumes",
            "no_wrong_oriented_face_pyramids",
            "no_te_sliver_faces",
            "no_body_wake_nonplanar_sliver_interface",
            "max_skew_threshold",
            "max_non_orthogonality_threshold",
            "yplus_target_support",
        ],
        "run_solver_only_after_all_requested_rungs_pass_strict_checkmesh": True,
        "max_skew": 4.0,
        "max_non_orthogonality_deg": 90.0,
        "high_aspect_cells_allowed_in_strict_checkmesh": False,
        "strict_checkmesh_requires_failed_checks": 0,
        "hpa_wall_resolved_mesh_quality_dict": {
            "minDeterminant": 1.0e-8,
            "minTwist": 0.0,
            "reason": "wall-resolved HPA BL cells keep relaxed determinant/twist thresholds, but the generator must still avoid OpenFOAM highAspectRatioCells",
        },
        "te_sliver_min_pyramid_volume_m3": 1.0e-15,
        "body_wake_min_face_planarity_ratio": 0.2,
        "yplus_target": {
            "mean_preferred_max": 0.99,
            "p95_preferred_max": 2.0,
            "max_should_not_widely_exceed": 5.0,
            "wall_scope": ["airfoil_upper", "airfoil_lower", "te_wall"],
        },
    }


def mesh_family_ready_for_solver(rungs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    blocked: list[str] = []
    reasons: dict[str, list[str]] = {}
    for rung in rungs:
        case_id = str(rung.get("spec", {}).get("case_id", "unknown"))
        rung_reasons: list[str] = []
        acceptance = rung.get("checkMesh_acceptance", {})
        if acceptance.get("strict_checkMesh_clean") is not True:
            rung_reasons.append("strict_checkMesh_clean")
        commands = rung.get("commands", {})
        checkmesh = commands.get("checkMesh") if isinstance(commands, Mapping) else None
        if checkmesh is not None and checkmesh.get("returncode") != 0:
            rung_reasons.append("checkMesh_returncode_nonzero_or_missing")
        guard_status = rung.get("generator_quality_guards", {})
        for guard, payload in guard_status.items() if isinstance(guard_status, Mapping) else []:
            if isinstance(payload, Mapping) and payload.get("status") == "fail":
                rung_reasons.append(f"{guard}=fail")
        if rung_reasons:
            blocked.append(case_id)
            reasons[case_id] = rung_reasons
    return {
        "ready_for_solver": not blocked,
        "blocked_rungs": blocked,
        "blocking_reasons": reasons,
        "policy": "solver is allowed only after every requested rung is strict checkMesh clean",
    }


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
    wall_patches = tuple(
        name
        for name in (
            "airfoil_upper",
            "airfoil_lower",
            "wing_upper",
            "wing_lower",
            "te_wall",
            "physical_tip_left",
            "physical_tip_right",
        )
        if name in names
    )
    artificial_symmetry_patches: tuple[str, ...] = ()
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
    mesh_only: bool = False,
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

    mesh_phase_results = [
        run_or_reuse_rung(
            output_dir=output_dir,
            spec=spec,
            openfoam_command=openfoam_command,
            reuse_existing_rungs=reuse_existing_rungs,
            timeout_seconds=timeout_seconds,
            first_iterations=first_iterations,
            final_iterations=final_iterations,
            allow_solver=False,
        )
        for spec in specs
    ]
    family_gate = mesh_family_ready_for_solver(mesh_phase_results)
    solver_phase = {
        "attempted": False,
        "reason": (
            "blocked_by_family_strict_checkmesh_gate"
            if not family_gate["ready_for_solver"]
            else "mesh_only_requested"
            if mesh_only
            else "pending_solver_phase"
        ),
        "family_gate": family_gate,
    }
    rung_results = mesh_phase_results
    if family_gate["ready_for_solver"] and not mesh_only:
        solver_phase = {
            "attempted": True,
            "reason": "all_requested_rungs_strict_checkmesh_clean",
            "family_gate": family_gate,
        }
        rung_results = [
            run_or_reuse_rung(
                output_dir=output_dir,
                spec=spec,
                openfoam_command=openfoam_command,
                reuse_existing_rungs=reuse_existing_rungs,
                timeout_seconds=timeout_seconds,
                first_iterations=first_iterations,
                final_iterations=final_iterations,
                allow_solver=True,
            )
            for spec in specs
        ]
        family_gate = mesh_family_ready_for_solver(rung_results)
        solver_phase["post_solver_family_gate"] = family_gate
    comparisons = build_pairwise_comparisons(rung_results)
    verdict = build_verdict(rung_results, comparisons, family_gate=family_gate)

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
            "artificial_tip_treatment": "physical_tip_left/right kept as wall diagnostics after mirrorMesh",
            "physical_drag_definition": "total_physical = primary + te_wall; artificial mirrored tip closures excluded",
            "solver_gate": "OpenFOAM solver phase is blocked until every requested rung is strict checkMesh clean",
        },
        "ladder_specs": [serialize_spec(spec) for spec in specs],
        "mesh_quality_gate_contract": build_mesh_quality_gate_contract(),
        "mesh_phase_rungs": mesh_phase_results,
        "mesh_family_solver_gate": family_gate,
        "solver_phase": solver_phase,
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
    allow_solver: bool,
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
    generator_quality_guards = build_generator_quality_guard_status(checkmesh_acceptance)
    dry_run = None
    potential_run = None
    first_run = None
    final_run = None
    yplus_post = None
    solver_block_reason = None
    if not allow_solver:
        solver_block_reason = "solver_deferred_until_all_requested_rungs_are_strict_checkmesh_clean"
    elif not checkmesh_acceptance.get("strict_checkMesh_clean"):
        solver_block_reason = "strict_checkMesh_clean_required_before_solver"
    if allow_solver and checkmesh_acceptance.get("strict_checkMesh_clean"):
        dry_run = base.run_openfoam_command(
            fullwing_case_dir,
            openfoam_command=openfoam_command,
            command="simpleFoam -dry-run",
            log_name="log.simpleFoam_dry_run",
            timeout_seconds=600.0,
        )
        if dry_run["returncode"] == 0:
            potential_run = base.run_openfoam_command(
                fullwing_case_dir,
                openfoam_command=openfoam_command,
                command="potentialFoam -initialiseUBCs -writep",
                log_name="log.potentialFoam",
                timeout_seconds=900.0,
            )
        if dry_run["returncode"] == 0 and potential_run and potential_run["returncode"] == 0:
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
            if (
                final_iterations > first_iterations
                and first_run["returncode"] == 0
                and should_extend_after_first_run(coeffs_200, stable_200)
            ):
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
            "potentialFoam": potential_run,
            "simpleFoam_200": first_run,
            "simpleFoam_500": final_run,
            "postProcess_yPlus": yplus_post,
        },
        "checkMesh_acceptance": checkmesh_acceptance,
        "generator_quality_guards": generator_quality_guards,
        "solver_phase_policy": {
            "allow_solver": allow_solver,
            "solver_block_reason": solver_block_reason,
            "strict_checkMesh_required": True,
        },
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
    allow_solver: bool,
) -> dict[str, Any]:
    if reuse_existing_rungs:
        existing = load_existing_rung_result(output_dir, spec.case_id)
        if existing is not None and existing_rung_matches_solver_policy(existing, allow_solver=allow_solver):
            return existing
    return run_rung(
        output_dir=output_dir,
        spec=spec,
        openfoam_command=openfoam_command,
        timeout_seconds=timeout_seconds,
        first_iterations=first_iterations,
        final_iterations=final_iterations,
        allow_solver=allow_solver,
    )


def existing_rung_matches_solver_policy(existing: Mapping[str, Any], *, allow_solver: bool) -> bool:
    policy = existing.get("solver_phase_policy", {})
    if isinstance(policy, Mapping) and policy.get("allow_solver") is allow_solver:
        return True
    commands = existing.get("commands", {})
    if not isinstance(commands, Mapping):
        return not allow_solver
    has_solver_artifact = any(
        commands.get(key)
        for key in ("simpleFoam_dry_run", "simpleFoam_200", "simpleFoam_500", "postProcess_yPlus")
    )
    return has_solver_artifact if allow_solver else not has_solver_artifact


def build_generator_quality_guard_status(checkmesh_acceptance: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    metrics = checkmesh_acceptance.get("metrics", {})
    contract = build_mesh_quality_gate_contract()

    def threshold_status(value: Any, threshold: float, *, higher_is_bad: bool = True) -> dict[str, Any]:
        if value is None:
            return {"status": "unknown", "value": None, "threshold": threshold}
        numeric = float(value)
        passed = numeric <= threshold if higher_is_bad else numeric >= threshold
        return {"status": "pass" if passed else "fail", "value": numeric, "threshold": threshold}

    strict_clean = checkmesh_acceptance.get("strict_checkMesh_clean") is True
    accepted_for_smoke = checkmesh_acceptance.get("accepted_for_solver_smoke") is True
    return {
        "strict_meshquality_clean": {
            "status": "pass" if strict_clean else "fail",
            "source": "full checkMesh -meshQuality failed-check count",
        },
        "no_open_cells": {
            "status": "pass" if accepted_for_smoke else "unknown",
            "source": "OpenFOAM checkMesh text gate",
        },
        "no_negative_volumes": {
            "status": "pass" if accepted_for_smoke else "unknown",
            "source": "OpenFOAM checkMesh text gate",
        },
        "no_wrong_oriented_face_pyramids": {
            "status": "pass" if accepted_for_smoke else "unknown",
            "source": "Face pyramids OK text gate",
        },
        "no_te_sliver_faces": {
            "status": "pass" if accepted_for_smoke else "unknown",
            "source": "lower-TE regression contract plus Face pyramids OK text gate",
        },
        "no_body_wake_nonplanar_sliver_interface": {
            "status": "pass" if accepted_for_smoke else "unknown",
            "source": "body/wake TE sliver regression contract plus Face pyramids OK text gate",
        },
        "max_skew_threshold": threshold_status(metrics.get("maxSkew"), float(contract["max_skew"])),
        "max_non_orthogonality_threshold": threshold_status(
            metrics.get("maxNonOrtho"),
            float(contract["max_non_orthogonality_deg"]),
        ),
        "yplus_target_support": {
            "status": "not_evaluated_pre_solver",
            "target": contract["yplus_target"],
        },
    }


def build_seed_case(
    *,
    spec: GridLadderSpec,
    authority: Any,
    seed_case_dir: Path,
) -> dict[str, Any]:
    if seed_case_dir.exists():
        shutil.rmtree(seed_case_dir)

    stations = build_halfwing_stations(authority, spec.station_plan)
    mesh = build_swept_cgrid_mesh(
        stations,
        n_radial=spec.n_radial,
        first_layer_height_m=FIRST_LAYER_HEIGHT_M,
        farfield_chords=FARFIELD_CHORDS,
        wake_length_chords=WAKE_LENGTH_CHORDS,
        case_id=f"{spec.case_id}_halfwing_seed",
        near_wall_growth=NEAR_WALL_GROWTH,
        wake_cross_cells=WAKE_CROSS_CELLS,
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
    return False


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
        "artificial_tip_treatment": "wall_diagnostic_excluded_from_total_physical_drag",
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
    stability.add_potential_foam_scheme_entries(case_dir / "system" / "fvSchemes")
    stability.add_potential_foam_solver_entries(case_dir / "system" / "fvSolution")
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
    return requested_primary_window_stable(rows) is not True


def requested_primary_window_stable(
    rows: Sequence[Mapping[str, float]],
    *,
    min_iterations: int = 500,
    window: int = 100,
) -> bool:
    if len(rows) < min_iterations or len(rows) < window:
        return False
    tail = list(rows[-window:])

    def rel_span(key: str) -> float | None:
        values = [float(row[key]) for row in tail if key in row]
        if not values:
            return None
        mean = sum(values) / len(values)
        if not mean:
            return None
        return (max(values) - min(values)) / abs(mean)

    cd_rel = rel_span("Cd")
    cl_rel = rel_span("Cl")
    cm_rel = rel_span("CmPitch")
    return (
        cd_rel is not None
        and cl_rel is not None
        and cd_rel < 0.01
        and cl_rel < 0.005
        and (cm_rel is None or cm_rel < 0.01)
    )


def force_runaway_detected(coeffs: Mapping[str, Any]) -> bool:
    return first_force_divergence_time_after_startup(coeffs) is not None


def first_force_divergence_time_after_startup(
    coeffs: Mapping[str, Any],
    *,
    min_time: int = RUNAWAY_GUARD_MIN_TIME,
) -> int | None:
    rows = coeffs.get("functions", {}).get("primary", {}).get("rows", [])
    for row in rows:
        time_value = int(float(row.get("Time", 0)))
        if time_value < min_time:
            continue
        cd = abs(float(row.get("Cd", 0.0)))
        cl = abs(float(row.get("Cl", 0.0)))
        if cd > RUNAWAY_GUARD_ABS_CD or cl > RUNAWAY_GUARD_ABS_CL:
            return time_value
    return None


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
                divergence_time = first_force_divergence_time_after_startup(coeffs)
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
                f"terminating simpleFoam after startup grace time {RUNAWAY_GUARD_MIN_TIME} "
                f"because |CD|>{RUNAWAY_GUARD_ABS_CD:g} or |CL|>{RUNAWAY_GUARD_ABS_CL:g} "
                "on the primary force group.\n"
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
        "runaway_guard_min_time": RUNAWAY_GUARD_MIN_TIME,
        "runaway_guard_abs_cd": RUNAWAY_GUARD_ABS_CD,
        "runaway_guard_abs_cl": RUNAWAY_GUARD_ABS_CL,
        "elapsed_s": time.monotonic() - started,
        "resource_usage": base.parse_time_l_log(case_dir / log_name),
        "tail": base.tail(case_dir / log_name, 80),
    }


def terminate_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def build_verdict(
    rungs: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    *,
    family_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    blocking = []
    for rung in rungs:
        if not rung.get("checkMesh_acceptance", {}).get("strict_checkMesh_clean"):
            blocking.append(f"{rung['spec']['case_id']}:strict_checkMesh_not_clean")
        if not rung.get("checkMesh_acceptance", {}).get("accepted_for_solver_smoke"):
            blocking.append(f"{rung['spec']['case_id']}:checkMesh_not_solver_smoke_acceptable")
        if rung.get("solver_phase_policy", {}).get("solver_block_reason"):
            blocking.append(
                f"{rung['spec']['case_id']}:{rung['solver_phase_policy']['solver_block_reason']}"
            )
        active_run = rung.get("commands", {}).get("simpleFoam_500") or rung.get("commands", {}).get("simpleFoam_200")
        if not active_run or active_run.get("returncode") != 0:
            blocking.append(f"{rung['spec']['case_id']}:solver_not_completed")
    if family_gate and family_gate.get("ready_for_solver") is not True:
        for rung_id in family_gate.get("blocked_rungs", []):
            blocking.append(f"{rung_id}:family_solver_gate_blocked")
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
        "mesh_family_solver_gate": dict(family_gate or {}),
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
        "wake_cross_cells": WAKE_CROSS_CELLS,
        "near_wall_growth": NEAR_WALL_GROWTH,
        "local_refinement_regions": list(spec.local_refinement_regions),
        "quality_gate_contract": spec.quality_gate_contract,
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
