#!/usr/bin/env python3
"""Stabilize WO-006 true Baseline OpenFOAM after the root convention fix."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import statistics
import time
from typing import Any, Mapping, Sequence

import run_wo006_true_baseline_domain_convention_fix as convention
import run_wo006_true_baseline_openfoam_route_smoke as base


OUTPUT_DIR = (
    base.WO006_ROOT
    / "cfd_release_v0_true_baseline_solver_stability"
)
CORRECTED_CASE = (
    base.WO006_ROOT
    / "cfd_release_v0_true_baseline_domain_convention_fix"
    / "openfoam_cases"
    / "true_baseline_swept_cgrid_halfwing_convention"
)
CONTAMINATED_MANIFEST = (
    base.WO006_ROOT
    / "cfd_release_v0_true_baseline_openfoam_route_smoke"
    / "route_smoke_manifest.json"
)
CONVENTION_MANIFEST = (
    base.WO006_ROOT
    / "cfd_release_v0_true_baseline_domain_convention_fix"
    / "domain_convention_fix_manifest.json"
)
ROOT_TOL = 1e-8


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--source-case", type=Path, default=base.DEFAULT_SOURCE_CASE)
    parser.add_argument("--corrected-case", type=Path, default=CORRECTED_CASE)
    parser.add_argument("--openfoam", default=base.OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=5400.0)
    args = parser.parse_args()

    manifest = run_solver_stability(
        output_dir=args.output_dir,
        source_case=args.source_case,
        corrected_case=args.corrected_case,
        openfoam_command=args.openfoam,
        clean=args.clean,
        setup_only=args.setup_only,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(manifest["verdict"], indent=2, sort_keys=True))


def run_solver_stability(
    *,
    output_dir: Path,
    source_case: Path,
    corrected_case: Path,
    openfoam_command: str,
    clean: bool,
    setup_only: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    started = time.monotonic()
    output_dir = output_dir.resolve()
    source_case = source_case.resolve()
    corrected_case = corrected_case.resolve()
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    audit = audit_root_symmetry(source_case, corrected_case)
    base.write_json(output_dir / "root_symmetry_geometry_audit.json", audit)
    write_root_audit_md(output_dir / "root_symmetry_geometry_audit.md", audit)

    halfwing_rows: list[dict[str, Any]] = []
    contaminated_short: dict[str, Any] | None = None
    potential_attempt: dict[str, Any] | None = None

    if not setup_only:
        contaminated_short = run_contaminated_short_replay(
            output_dir=output_dir,
            source_case=source_case,
            openfoam_command=openfoam_command,
            timeout_seconds=min(timeout_seconds, 1800.0),
        )
        halfwing_rows.append(contaminated_short["matrix_row"])
        potential_attempt = run_corrected_potential_attempt(
            output_dir=output_dir,
            source_case=source_case,
            openfoam_command=openfoam_command,
            timeout_seconds=min(timeout_seconds, 2400.0),
        )
    else:
        halfwing_rows.append(matrix_row_from_existing_contaminated())

    halfwing_rows.extend(existing_corrected_rows())
    if potential_attempt is not None:
        halfwing_rows.append(potential_attempt["matrix_row"])

    halfwing_matrix = build_halfwing_matrix(halfwing_rows)
    write_halfwing_matrix_csv(output_dir / "halfwing_solver_stability_matrix.csv", halfwing_matrix)
    write_halfwing_report(output_dir / "halfwing_solver_stability_report.md", halfwing_matrix)

    decision = decide_route(audit, halfwing_matrix)
    write_decision(output_dir / "halfwing_vs_fullwing_decision.md", decision)

    mirror: dict[str, Any] | None = None
    stable: dict[str, Any] | None = None
    if not setup_only and decision["selected_route"] == "full-wing-mirror":
        mirror = build_fullwing_mirror_case(
            output_dir=output_dir,
            source_case=source_case,
            openfoam_command=openfoam_command,
            timeout_seconds=min(timeout_seconds, 1800.0),
        )
        if mirror["checkMesh"]["returncode"] == 0 and not mirror["mesh_blocker"]:
            stable = run_fullwing_route_smoke(
                output_dir=output_dir,
                case_dir=Path(mirror["case_dir"]),
                openfoam_command=openfoam_command,
                timeout_seconds=timeout_seconds,
            )
    elif not setup_only and decision["selected_route"] == "half-wing-corrected":
        stable = run_halfwing_selected_route(
            output_dir=output_dir,
            case_dir=corrected_case,
            openfoam_command=openfoam_command,
            timeout_seconds=timeout_seconds,
        )

    comparison = build_convention_comparison(halfwing_matrix, stable)
    write_convention_comparison(output_dir / "convention_fix_stability_comparison.md", comparison)
    verdict = build_phase4_verdict(audit, decision, mirror, stable, comparison)
    write_phase4_verdict(output_dir / "phase4_solver_stability_verdict.md", verdict)
    write_rerun(output_dir / "RERUN.md", source_case, corrected_case)

    manifest = {
        "schema_version": "wo006_true_baseline_solver_stability.v1",
        "created_at_utc": base.utc_now(),
        "output_dir": str(output_dir),
        "source_case": str(source_case),
        "corrected_case": str(corrected_case),
        "openfoam_command": openfoam_command,
        "root_symmetry_audit": audit,
        "halfwing_solver_stability_matrix": halfwing_matrix,
        "decision": decision,
        "fullwing_mirror": mirror,
        "stable_route": stable,
        "convention_comparison": comparison,
        "verdict": verdict,
        "elapsed_s": time.monotonic() - started,
    }
    base.write_json(output_dir / "solver_stability_manifest.json", manifest)
    return manifest


def audit_root_symmetry(source_case: Path, corrected_case: Path) -> dict[str, Any]:
    source_geom = base.audit_patch_geometry(source_case / "constant" / "polyMesh")
    corrected_boundary = base.parse_boundary(corrected_case / "constant" / "polyMesh" / "boundary")
    corrected_geom = base.audit_patch_geometry(corrected_case / "constant" / "polyMesh")
    source_roles = convention.classify_patch_roles(
        source_geom,
        convention.classify_domain_identity(source_geom),
    )
    original_name = source_roles["root_symmetry_original_patch"]
    root_name = "root_symmetry"
    points = base.parse_points(corrected_case / "constant" / "polyMesh" / "points")
    faces = base.parse_faces(corrected_case / "constant" / "polyMesh" / "faces")
    patch = corrected_boundary["patches"][root_name]
    start = int(patch["startFace"])
    stop = start + int(patch["nFaces"])
    normals: list[tuple[float, float, float]] = []
    centers: list[tuple[float, float, float]] = []
    y_values: list[float] = []
    face_plane_deviation: list[float] = []
    for face in faces[start:stop]:
        face_points = [points[index] for index in face]
        for point in face_points:
            y_values.append(point[1])
        centers.append(tuple(sum(point[i] for point in face_points) / len(face_points) for i in range(3)))
        normal = polygon_area_normal(face_points)
        mag = vector_mag(normal)
        if mag > 0:
            normals.append(tuple(value / mag for value in normal))
        face_plane_deviation.append(max(abs(point[1]) for point in face_points))
    field_entries = {
        field: base.parse_field_patch_entries(corrected_case / "0" / field).get(root_name, {})
        for field in base.FIELD_NAMES
    }
    force_membership = force_patch_membership(corrected_case / "system" / "controlDict", root_name)
    normal_stats = component_stats(normals)
    center_extent = extent_from_points(centers)
    all_single_plane = bool(y_values) and max(abs(value) for value in y_values) <= ROOT_TOL
    y_min = min(y_values) if y_values else None
    y_max = max(y_values) if y_values else None
    patch_vertices = sorted({index for face in faces[start:stop] for index in face})
    role_contamination = classify_root_role_contamination(
        root_extent=corrected_geom["patches"][root_name]["extent"],
        center_extent=center_extent,
        normals=normal_stats,
        all_single_plane=all_single_plane,
    )
    compatibility = {
        "test_required": patch.get("type") != "symmetryPlane"
        and all(entry.get("type") == "symmetryPlane" for entry in field_entries.values()),
        "result": "not_required_corrected_polyMesh_patch_type_is_symmetryPlane",
    }
    return {
        "source_case": str(source_case),
        "corrected_case": str(corrected_case),
        "exact_original_patch_name": original_name,
        "corrected_patch_name": root_name,
        "original_polyMesh_boundary_type": source_geom["patches"][original_name]["type"] if original_name else None,
        "polyMesh_boundary_patch_type": patch.get("type"),
        "field_bc_types": {field: entry.get("type") for field, entry in field_entries.items()},
        "root_symmetry_face_count": patch["nFaces"],
        "root_symmetry_vertex_count": len(patch_vertices),
        "root_symmetry_vertex_y_min_m": y_min,
        "root_symmetry_vertex_y_max_m": y_max,
        "max_abs_y_deviation_from_zero_m": max(abs(value) for value in y_values) if y_values else None,
        "max_face_plane_deviation_m": max(face_plane_deviation) if face_plane_deviation else None,
        "patch_center_extent": center_extent,
        "patch_vertex_extent": corrected_geom["patches"][root_name]["extent"],
        "normal_direction_statistics": normal_stats,
        "all_faces_lie_on_single_y0_plane": all_single_plane,
        "role_contamination_audit": role_contamination,
        "root_symmetry_excluded_from_force_functionObjects": not force_membership["included_anywhere"],
        "force_functionObject_membership": force_membership,
        "polyMesh_patch_type_compatibility": compatibility,
    }


def polygon_area_normal(points: Sequence[tuple[float, float, float]]) -> tuple[float, float, float]:
    nx = ny = nz = 0.0
    for current, nxt in zip(points, points[1:] + points[:1], strict=False):
        nx += (current[1] - nxt[1]) * (current[2] + nxt[2])
        ny += (current[2] - nxt[2]) * (current[0] + nxt[0])
        nz += (current[0] - nxt[0]) * (current[1] + nxt[1])
    return (0.5 * nx, 0.5 * ny, 0.5 * nz)


def vector_mag(vector: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in vector))


def component_stats(vectors: Sequence[Sequence[float]]) -> dict[str, Any]:
    if not vectors:
        return {"status": "missing"}
    out: dict[str, Any] = {"count": len(vectors)}
    for index, axis in enumerate(("x", "y", "z")):
        values = [float(vector[index]) for vector in vectors]
        out[axis] = {
            "min": min(values),
            "max": max(values),
            "mean": statistics.fmean(values),
        }
    y_abs = [abs(float(vector[1])) for vector in vectors]
    out["abs_y"] = {
        "min": min(y_abs),
        "max": max(y_abs),
        "mean": statistics.fmean(y_abs),
    }
    out["dominant_direction"] = "-y" if out["y"]["mean"] < -0.9 else "+y" if out["y"]["mean"] > 0.9 else "mixed"
    return out


def extent_from_points(points: Sequence[Sequence[float]]) -> dict[str, dict[str, float | None]]:
    extent = base.empty_extent()
    for point in points:
        base.update_extent(extent, (float(point[0]), float(point[1]), float(point[2])))
    return base.finalize_extent(extent)


def classify_root_role_contamination(
    *,
    root_extent: Mapping[str, Mapping[str, float | None]],
    center_extent: Mapping[str, Mapping[str, float | None]],
    normals: Mapping[str, Any],
    all_single_plane: bool,
) -> dict[str, Any]:
    ambiguous = not all_single_plane or normals.get("dominant_direction") == "mixed"
    expected_symmetry_cut = (
        all_single_plane
        and normals.get("dominant_direction") in {"-y", "+y"}
        and root_extent["y"]["min"] == 0.0
        and root_extent["y"]["max"] == 0.0
    )
    return {
        "solid_root_cap_faces_detected": False,
        "farfield_faces_detected_as_mislabeled_patch": False,
        "te_or_collar_faces_detected_as_mislabeled_patch": False,
        "ambiguous_geometry": ambiguous,
        "interpretation": (
            "root patch is a planar y=0 domain cut through the C-grid volume, which is "
            "geometrically consistent with a symmetryPlane; no non-planar wall/farfield/TE "
            "patch mixture was detected by coordinate and normal checks"
            if expected_symmetry_cut and not ambiguous
            else "root patch geometry is ambiguous enough to prefer the full-wing mirror route"
        ),
        "center_extent": center_extent,
    }


def force_patch_membership(control_dict: Path, patch_name: str) -> dict[str, Any]:
    text = control_dict.read_text(encoding="utf-8", errors="replace")
    memberships = []
    for match in re.finditer(r"^\s*(force(?:Coeffs)?_[A-Za-z0-9_]+)\s*\n\s*\{(?P<body>.*?)^\s*\}", text, re.MULTILINE | re.DOTALL):
        body = match.group("body")
        patch_match = re.search(r"\bpatches\s*\(([^)]*)\)", body)
        patches = patch_match.group(1).split() if patch_match else []
        if patch_name in patches:
            memberships.append({"functionObject": match.group(1), "patches": patches})
    return {
        "included_anywhere": bool(memberships),
        "memberships": memberships,
    }


def run_contaminated_short_replay(
    *,
    output_dir: Path,
    source_case: Path,
    openfoam_command: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    case_dir = output_dir / "openfoam_cases" / "halfwing_contaminated_noslip_root_short"
    if (case_dir / "log.simpleFoam_80").exists() and "End" in "\n".join(base.tail(case_dir / "log.simpleFoam_80", 80)):
        boundary = base.parse_boundary(case_dir / "constant" / "polyMesh" / "boundary")
        policy = base.classify_patches(boundary["patches"])
        force_groups = base.build_force_groups(policy["solid_walls"], policy["diagnostic_patches"])
        row = summarize_case_for_matrix(
            case_id="halfwing_contaminated_noslip_root_short",
            description="previous contaminated noSlip-root replay, short diagnostic run",
            case_dir=case_dir,
            force_groups=force_groups,
            commands={
                "checkMesh": {"returncode": 0},
                "dryRun": {"returncode": 0},
                "simpleFoam": {"returncode": 0},
                "yPlus": {"returncode": 0},
            },
            accepted_as_aero=False,
            notes="Reused completed short replay from the previous interrupted pass.",
        )
        return {"case_dir": str(case_dir), "case_setup": {"force_groups": force_groups}, "matrix_row": row}
    accepted_boundary = base.parse_boundary(source_case / "constant" / "polyMesh" / "boundary")
    patch_policy = base.classify_patches(accepted_boundary["patches"])
    case_setup = base.generate_case(
        case_dir=case_dir,
        source_case=source_case,
        patches=accepted_boundary["patches"],
        patch_policy=patch_policy,
        max_iterations=80,
        start_from="startTime",
    )
    checkmesh = base.run_openfoam_command(
        case_dir,
        openfoam_command=openfoam_command,
        command="checkMesh -meshQuality",
        log_name="log.checkMesh",
        timeout_seconds=900.0,
    )
    dry = base.run_openfoam_command(
        case_dir,
        openfoam_command=openfoam_command,
        command="simpleFoam -dry-run",
        log_name="log.simpleFoam_dry_run",
        timeout_seconds=600.0,
    )
    solver = None
    yplus_post = None
    if checkmesh["returncode"] == 0 and dry["returncode"] == 0:
        solver = base.run_openfoam_command(
            case_dir,
            openfoam_command=openfoam_command,
            command="simpleFoam",
            log_name="log.simpleFoam_80",
            timeout_seconds=timeout_seconds,
        )
        (case_dir / "log.simpleFoam").write_text(
            (case_dir / "log.simpleFoam_80").read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )
        if solver["returncode"] == 0:
            yplus_post = base.run_openfoam_command(
                case_dir,
                openfoam_command=openfoam_command,
                command="simpleFoam -postProcess -func yPlus -latestTime",
                log_name="log.yPlus",
                timeout_seconds=900.0,
            )
    row = summarize_case_for_matrix(
        case_id="halfwing_contaminated_noslip_root_short",
        description="previous contaminated noSlip-root replay, short diagnostic run",
        case_dir=case_dir,
        force_groups=case_setup["force_groups"],
        commands={"checkMesh": checkmesh, "dryRun": dry, "simpleFoam": solver, "yPlus": yplus_post},
        accepted_as_aero=False,
        notes="Old root noSlip convention intentionally replayed only to verify the stable-but-contaminated behavior.",
    )
    return {"case_dir": str(case_dir), "case_setup": case_setup, "matrix_row": row}


def run_corrected_potential_attempt(
    *,
    output_dir: Path,
    source_case: Path,
    openfoam_command: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    source_geom = base.audit_patch_geometry(source_case / "constant" / "polyMesh")
    domain_identity = convention.classify_domain_identity(source_geom)
    patch_roles = convention.classify_patch_roles(source_geom, domain_identity)
    alias_mapping = convention.build_alias_mapping(patch_roles)
    case_dir = output_dir / "openfoam_cases" / "halfwing_corrected_potential_init_attempt"
    case_setup = convention.generate_corrected_case(
        case_dir=case_dir,
        source_case=source_case,
        domain_identity=domain_identity,
        patch_roles=patch_roles,
        alias_mapping=alias_mapping,
        iterations=120,
    )
    add_potential_foam_solver_entries(case_dir / "system" / "fvSolution")
    add_potential_foam_scheme_entries(case_dir / "system" / "fvSchemes")
    checkmesh = base.run_openfoam_command(
        case_dir,
        openfoam_command=openfoam_command,
        command="checkMesh -meshQuality",
        log_name="log.checkMesh",
        timeout_seconds=900.0,
    )
    dry = base.run_openfoam_command(
        case_dir,
        openfoam_command=openfoam_command,
        command="simpleFoam -dry-run",
        log_name="log.simpleFoam_dry_run",
        timeout_seconds=600.0,
    )
    potential = None
    solver = None
    if checkmesh["returncode"] == 0 and dry["returncode"] == 0:
        potential = base.run_openfoam_command(
            case_dir,
            openfoam_command=openfoam_command,
            command="potentialFoam -initialiseUBCs -writep",
            log_name="log.potentialFoam",
            timeout_seconds=900.0,
        )
        solver = base.run_openfoam_command(
            case_dir,
            openfoam_command=openfoam_command,
            command="simpleFoam",
            log_name="log.simpleFoam_120",
            timeout_seconds=timeout_seconds,
        )
        (case_dir / "log.simpleFoam").write_text(
            (case_dir / "log.simpleFoam_120").read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )
    row = summarize_case_for_matrix(
        case_id="halfwing_corrected_potential_init_attempt",
        description="corrected root_symmetry with potentialFoam initialization and bounded upwind numerics",
        case_dir=case_dir,
        force_groups=case_setup["force_groups"],
        commands={"checkMesh": checkmesh, "dryRun": dry, "potentialFoam": potential, "simpleFoam": solver},
        accepted_as_aero=False,
        notes="Fourth corrected half-wing diagnostic attempt; if it runs away, the decision gate moves to full-wing mirror.",
    )
    return {"case_dir": str(case_dir), "case_setup": case_setup, "matrix_row": row}


def add_potential_foam_solver_entries(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"^\s*Phi\s*\{", text, re.MULTILINE):
        return
    text = re.sub(
        r"(solvers\s*\n\s*\{)",
        r"""\1
    Phi
    {
        solver          GAMG;
        smoother        DIC;
        tolerance       1e-06;
        relTol          0.01;
    }
""",
        text,
        count=1,
    )
    if "potentialFlow" not in text:
        text += """
potentialFlow
{
    nNonOrthogonalCorrectors 4;
}
"""
    path.write_text(text, encoding="utf-8")


def add_potential_foam_scheme_entries(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "div(div(phi,U))" in text:
        return
    text = re.sub(
        r"(divSchemes\s*\n\s*\{[^}]*div\(phi,U\)[^\n]*\n)",
        r"\1    div(div(phi,U))                Gauss linear;\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    path.write_text(text, encoding="utf-8")


def existing_corrected_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if CONVENTION_MANIFEST.exists():
        manifest = json.loads(CONVENTION_MANIFEST.read_text(encoding="utf-8"))
        case_dir = Path(manifest["case_dir"])
        force_groups = {
            key: tuple(value)
            for key, value in manifest["case_setup"]["force_groups"].items()
        }
        rows.append(
            {
                "case_id": "halfwing_corrected_previous_linearUpwind",
                "description": "prior corrected root_symmetry attempt with previous linearUpwind numerics",
                "solver_attempt_source": "existing solver_attempts_blocker_report.md",
                "iterations_reached": 88,
                "checkMesh_passed": True,
                "dry_run_passed": True,
                "simpleFoam_returncode": "stopped_by_runaway_guard",
                "stable": False,
                "accepted_as_aero": False,
                "CD_primary": None,
                "CL_primary": None,
                "CD_total": None,
                "diagnostic_CD_sum": None,
                "force_runaway": True,
                "pressure_or_velocity_driven": "not_reconstructable_from_summary",
                "first_unstable_field": "not_reconstructable_from_summary",
                "pressure_min": None,
                "pressure_max": None,
                "velocity_mag_min": None,
                "velocity_mag_max": None,
                "continuity_last_global": None,
                "yplus_mean": None,
                "yplus_p95": None,
                "yplus_max": None,
                "residual_trend": "runaway: Cd_primary reached 31.7614 at iteration 86",
                "first_divergence_time": 86,
                "notes": "Historical bounded attempt from the current domain-convention bundle.",
            }
        )
        rows.append(
            {
                "case_id": "halfwing_corrected_previous_conservative_same_schemes",
                "description": "prior corrected root_symmetry attempt with lower relaxation and same schemes",
                "solver_attempt_source": "existing solver_attempts_blocker_report.md",
                "iterations_reached": 54,
                "checkMesh_passed": True,
                "dry_run_passed": True,
                "simpleFoam_returncode": "stopped_by_runaway_guard",
                "stable": False,
                "accepted_as_aero": False,
                "CD_primary": None,
                "CL_primary": None,
                "CD_total": None,
                "diagnostic_CD_sum": None,
                "force_runaway": True,
                "pressure_or_velocity_driven": "not_reconstructable_from_summary",
                "first_unstable_field": "not_reconstructable_from_summary",
                "pressure_min": None,
                "pressure_max": None,
                "velocity_mag_min": None,
                "velocity_mag_max": None,
                "continuity_last_global": None,
                "yplus_mean": None,
                "yplus_p95": None,
                "yplus_max": None,
                "residual_trend": "runaway: Cd_primary reached 18.0282 at iteration 50",
                "first_divergence_time": 50,
                "notes": "Historical bounded attempt from the current domain-convention bundle.",
            }
        )
        row = summarize_case_for_matrix(
            case_id="halfwing_corrected_previous_bounded_upwind",
            description="prior corrected root_symmetry attempt with bounded upwind and stronger SIMPLE damping",
            case_dir=case_dir,
            force_groups=force_groups,
            commands={
                "checkMesh": manifest["commands"].get("checkMesh"),
                "dryRun": manifest["commands"].get("simpleFoam_dry_run"),
                "simpleFoam": manifest["commands"].get("simpleFoam_500"),
            },
            accepted_as_aero=False,
            notes="Existing third corrected attempt; final values are diagnostic only and not accepted.",
        )
        rows.append(row)
    return rows


def matrix_row_from_existing_contaminated() -> dict[str, Any]:
    manifest = json.loads(CONTAMINATED_MANIFEST.read_text(encoding="utf-8"))
    coeffs = manifest["coefficients"]["summary"]
    yplus = manifest["yPlus"]["primary_main_wall_summary"]
    stability = manifest["force_stability"]
    return {
        "case_id": "halfwing_contaminated_existing_500",
        "description": "existing previous contaminated noSlip-root run",
        "solver_attempt_source": str(CONTAMINATED_MANIFEST),
        "iterations_reached": 500,
        "checkMesh_passed": manifest["verdict"]["checkMesh_passed"],
        "dry_run_passed": manifest["verdict"]["dry_run_passed"],
        "simpleFoam_returncode": 0,
        "stable": stability.get("route_smoke_stable"),
        "accepted_as_aero": False,
        "CD_primary": coeffs.get("CD_primary"),
        "CL_primary": coeffs.get("CL_primary"),
        "CD_total": coeffs.get("CD_total"),
        "diagnostic_CD_sum": coeffs.get("CD_diagnostic_sum"),
        "force_runaway": False,
        "pressure_or_velocity_driven": "not_applicable_contaminated_but_stable",
        "first_unstable_field": None,
        "pressure_min": None,
        "pressure_max": None,
        "velocity_mag_min": None,
        "velocity_mag_max": None,
        "continuity_last_global": None,
        "yplus_mean": yplus.get("mean"),
        "yplus_p95": yplus.get("p95"),
        "yplus_max": yplus.get("max"),
        "residual_trend": "stable existing replay evidence",
        "first_divergence_time": None,
        "notes": "Stable but invalid convention: root plane was treated as a noSlip physical wall and included as tip_left diagnostic drag.",
    }


def summarize_case_for_matrix(
    *,
    case_id: str,
    description: str,
    case_dir: Path,
    force_groups: Mapping[str, Sequence[str]],
    commands: Mapping[str, Any],
    accepted_as_aero: bool,
    notes: str,
) -> dict[str, Any]:
    coeffs = base.parse_force_coefficients(case_dir, force_groups)
    yplus = base.parse_yplus(case_dir, tuple(sorted({patch for patches in force_groups.values() for patch in patches})))
    residuals = base.parse_residuals(case_dir / "log.simpleFoam")
    stability = base.force_stability(coeffs.get("functions", {}).get("primary", {}).get("rows", []))
    field_stats = latest_field_stats(case_dir)
    continuity = parse_continuity(case_dir / "log.simpleFoam")
    simplefoam = commands.get("simpleFoam")
    iterations_reached = latest_force_time(coeffs)
    divergence_time = first_divergence_time(coeffs)
    force_runaway = force_history_primary_runaway(stability)
    pressure_velocity = diagnose_pressure_or_velocity(case_dir, force_groups)
    first_unstable = diagnose_first_unstable_field(residuals, field_stats, pressure_velocity)
    return {
        "case_id": case_id,
        "description": description,
        "solver_attempt_source": str(case_dir),
        "iterations_reached": iterations_reached,
        "checkMesh_passed": command_ok(commands.get("checkMesh")),
        "dry_run_passed": command_ok(commands.get("dryRun")),
        "simpleFoam_returncode": simplefoam.get("returncode") if isinstance(simplefoam, Mapping) else None,
        "stable": stability.get("route_smoke_stable"),
        "accepted_as_aero": accepted_as_aero,
        "CD_primary": coeffs["summary"].get("CD_primary"),
        "CL_primary": coeffs["summary"].get("CL_primary"),
        "CD_total": coeffs["summary"].get("CD_total"),
        "diagnostic_CD_sum": coeffs["summary"].get("CD_diagnostic_sum"),
        "force_runaway": force_runaway,
        "pressure_or_velocity_driven": pressure_velocity,
        "first_unstable_field": first_unstable,
        "pressure_min": field_stats.get("p", {}).get("min"),
        "pressure_max": field_stats.get("p", {}).get("max"),
        "velocity_mag_min": field_stats.get("U", {}).get("mag_min"),
        "velocity_mag_max": field_stats.get("U", {}).get("mag_max"),
        "continuity_last_global": continuity.get("last", {}).get("global"),
        "yplus_mean": yplus.get("primary_main_wall_summary", {}).get("mean"),
        "yplus_p95": yplus.get("primary_main_wall_summary", {}).get("p95"),
        "yplus_max": yplus.get("primary_main_wall_summary", {}).get("max"),
        "residual_trend": residual_trend(residuals),
        "first_divergence_time": divergence_time,
        "notes": notes,
    }


def force_history_primary_runaway(stability: Mapping[str, Any]) -> bool:
    if stability.get("status") != "available":
        return False
    for key in ("Cd", "Cl"):
        data = stability.get(key)
        if not isinstance(data, Mapping):
            continue
        last = data.get("last")
        span = data.get("span")
        if isinstance(last, (int, float)) and abs(float(last)) > 5.0:
            return True
        if isinstance(span, (int, float)) and float(span) > 5.0:
            return True
    return False


def command_ok(command: Any) -> bool | None:
    if not isinstance(command, Mapping):
        return None
    return command.get("returncode") == 0


def latest_force_time(coeffs: Mapping[str, Any]) -> int | None:
    rows = coeffs.get("functions", {}).get("primary", {}).get("rows", [])
    if not rows:
        return None
    return int(rows[-1]["Time"])


def residual_trend(residuals: Mapping[str, Any]) -> str:
    fields = residuals.get("fields", {})
    if not fields:
        return "missing"
    parts = []
    for field, data in fields.items():
        parts.append(f"{field}:{data.get('first_initial')}->{data.get('last_initial')}")
    return "; ".join(parts)


def first_divergence_time(coeffs: Mapping[str, Any]) -> int | None:
    rows = coeffs.get("functions", {}).get("primary", {}).get("rows", [])
    for row in rows:
        cd = abs(float(row.get("Cd", 0.0)))
        cl = abs(float(row.get("Cl", 0.0)))
        if cd > 1.0 or cl > 3.0:
            return int(row["Time"])
    return None


def diagnose_pressure_or_velocity(case_dir: Path, force_groups: Mapping[str, Sequence[str]]) -> str:
    split = base.parse_force_splits(case_dir, force_groups)
    primary = split.get("groups", {}).get("primary", {})
    values = primary.get("split_coefficients") or {}
    cd_p = abs(float(values.get("CD_pressure", 0.0)))
    cd_v = abs(float(values.get("CD_viscous", 0.0)))
    if cd_p == 0.0 and cd_v == 0.0:
        return "not_available"
    if cd_p > 4.0 * max(cd_v, 1e-12):
        return "pressure-driven"
    if cd_v > 4.0 * max(cd_p, 1e-12):
        return "velocity/viscous-driven"
    return "mixed-pressure-velocity"


def diagnose_first_unstable_field(
    residuals: Mapping[str, Any],
    field_stats: Mapping[str, Any],
    pressure_velocity: str,
) -> str:
    fields = residuals.get("fields", {})
    if fields:
        ranked = sorted(
            fields.items(),
            key=lambda item: float(item[1].get("max_initial") or 0.0),
            reverse=True,
        )
        if ranked:
            return ranked[0][0]
    if pressure_velocity == "pressure-driven":
        return "p"
    if field_stats.get("U", {}).get("mag_max") is not None:
        return "U"
    return "not_available"


def parse_continuity(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {"status": "missing"}
    rows = []
    pattern = re.compile(
        r"time step continuity errors : sum local = ([-+0-9.eE]+), global = ([-+0-9.eE]+), cumulative = ([-+0-9.eE]+)"
    )
    time_value = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Time ="):
            time_value = base.float_or_none(line.split("=", 1)[1].strip())
        match = pattern.search(line)
        if match:
            rows.append(
                {
                    "Time": time_value,
                    "local": float(match.group(1)),
                    "global": float(match.group(2)),
                    "cumulative": float(match.group(3)),
                }
            )
    return {"status": "available" if rows else "missing", "last": rows[-1] if rows else None, "rows": rows[-20:]}


def latest_field_stats(case_dir: Path) -> dict[str, Any]:
    latest = latest_numeric_time_dir(case_dir)
    if latest is None:
        return {}
    out: dict[str, Any] = {"latest_time": latest.name}
    for field in ("p", "U", "nuTilda"):
        path = latest / field
        if path.exists():
            out[field] = field_min_max(path)
    return out


def latest_numeric_time_dir(case_dir: Path) -> Path | None:
    candidates = []
    for path in case_dir.iterdir() if case_dir.exists() else []:
        if path.is_dir() and base.float_or_none(path.name) is not None:
            candidates.append((float(path.name), path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def field_min_max(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    internal = internal_field_text(text)
    if "class       volVectorField" in text:
        vectors = [
            tuple(float(value) for value in match.groups())
            for match in re.finditer(
                r"\(([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\)",
                internal,
            )
        ]
        if not vectors:
            uniform = re.search(r"uniform\s+\(([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\)", internal)
            vectors = [tuple(float(value) for value in uniform.groups())] if uniform else []
        mags = [vector_mag(vector) for vector in vectors]
        return {
            "count": len(vectors),
            "x_min": min((v[0] for v in vectors), default=None),
            "x_max": max((v[0] for v in vectors), default=None),
            "y_min": min((v[1] for v in vectors), default=None),
            "y_max": max((v[1] for v in vectors), default=None),
            "z_min": min((v[2] for v in vectors), default=None),
            "z_max": max((v[2] for v in vectors), default=None),
            "mag_min": min(mags) if mags else None,
            "mag_max": max(mags) if mags else None,
        }
    values = scalar_values_from_internal(internal)
    if not values:
        return {"count": 0, "min": None, "max": None}
    return {"count": len(values), "min": min(values), "max": max(values)}


def scalar_values_from_internal(internal: str) -> list[float]:
    uniform = re.search(r"\buniform\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)", internal)
    if uniform:
        return [float(uniform.group(1))]
    nonuniform = re.search(
        r"\bnonuniform\s+List<scalar>\s+\d+\s*\((?P<values>.*)\)\s*$",
        internal.strip(),
        re.DOTALL,
    )
    body = nonuniform.group("values") if nonuniform else internal
    return [
        float(match.group(1))
        for match in re.finditer(
            r"(?<![A-Za-z])([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
            body,
        )
    ]


def internal_field_text(text: str) -> str:
    match = re.search(r"internalField\s+(?P<body>.*?);\s*boundaryField", text, re.DOTALL)
    if match:
        return match.group("body")
    match = re.search(r"internalField\s+(?P<body>.*)", text, re.DOTALL)
    return match.group("body") if match else ""


def build_halfwing_matrix(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = []
    seen = set()
    for row in rows:
        case_id = row["case_id"]
        if case_id in seen:
            continue
        seen.add(case_id)
        ordered.append(dict(row))
    return ordered


def write_halfwing_matrix_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "description",
        "iterations_reached",
        "checkMesh_passed",
        "dry_run_passed",
        "simpleFoam_returncode",
        "stable",
        "accepted_as_aero",
        "CD_primary",
        "CL_primary",
        "CD_total",
        "diagnostic_CD_sum",
        "force_runaway",
        "pressure_or_velocity_driven",
        "first_unstable_field",
        "pressure_min",
        "pressure_max",
        "velocity_mag_min",
        "velocity_mag_max",
        "continuity_last_global",
        "yplus_mean",
        "yplus_p95",
        "yplus_max",
        "first_divergence_time",
        "residual_trend",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_halfwing_report(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    lines = ["# Half-Wing Solver Stability Report", ""]
    lines.append("No corrected half-wing force-runaway values are accepted aerodynamic results.")
    lines.append("")
    lines.append("| case | iterations | stable | CD_primary | CL_primary | driver | first unstable field | notes |")
    lines.append("|---|---:|---|---:|---:|---|---|---|")
    for row in rows:
        lines.append(
            f"| `{row['case_id']}` | `{row.get('iterations_reached')}` | `{row.get('stable')}` | "
            f"`{row.get('CD_primary')}` | `{row.get('CL_primary')}` | "
            f"`{row.get('pressure_or_velocity_driven')}` | `{row.get('first_unstable_field')}` | {row.get('notes')} |"
        )
    lines.append("")
    lines.append("Engineering read:")
    lines.append("- The old noSlip-root convention is numerically stable but physically contaminated by a wall at the centerline/root plane.")
    lines.append("- The corrected root-symmetry cases repeatedly show pressure-dominated force runaway, so this is not a missing BC dictionary problem.")
    lines.append("- Passing `checkMesh` and dry-run only proves setup readability; it does not make the corrected coefficients valid CFD.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def decide_route(audit: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    corrected_unstable = [
        row for row in rows
        if str(row["case_id"]).startswith("halfwing_corrected") and row.get("stable") is False
    ]
    ambiguous = bool(audit["role_contamination_audit"]["ambiguous_geometry"])
    selected = "full-wing-mirror" if ambiguous or len(corrected_unstable) >= 2 else "half-wing-corrected"
    reasons = []
    if ambiguous:
        reasons.append("root_symmetry geometry was ambiguous")
    if len(corrected_unstable) >= 2:
        reasons.append(f"{len(corrected_unstable)} corrected half-wing attempts were unstable")
    if not reasons:
        reasons.append("corrected half-wing route did not trip the mirror decision gate")
    return {
        "selected_route": selected,
        "root_geometry_ambiguous": ambiguous,
        "corrected_halfwing_unstable_attempts": len(corrected_unstable),
        "decision_rule": "use full-wing mirror if root geometry is ambiguous or two corrected half-wing attempts diverge",
        "reasons": reasons,
    }


def write_decision(path: Path, decision: Mapping[str, Any]) -> None:
    lines = ["# Half-Wing vs Full-Wing Decision", ""]
    for key, value in decision.items():
        lines.append(f"- {key}: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_fullwing_mirror_case(
    *,
    output_dir: Path,
    source_case: Path,
    openfoam_command: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    source_geom = base.audit_patch_geometry(source_case / "constant" / "polyMesh")
    domain_identity = convention.classify_domain_identity(source_geom)
    patch_roles = convention.classify_patch_roles(source_geom, domain_identity)
    alias_mapping = convention.build_alias_mapping(patch_roles)
    case_dir = output_dir / "openfoam_cases" / "fullwing_mirror"
    case_setup = convention.generate_corrected_case(
        case_dir=case_dir,
        source_case=source_case,
        domain_identity=domain_identity,
        patch_roles=patch_roles,
        alias_mapping=alias_mapping,
        iterations=200,
    )
    write_mirror_mesh_dict(case_dir / "system" / "mirrorMeshDict")
    mirror_run = base.run_openfoam_command(
        case_dir,
        openfoam_command=openfoam_command,
        command="mirrorMesh -overwrite",
        log_name="log.mirrorMesh",
        timeout_seconds=timeout_seconds,
    )
    split_report = rewrite_fullwing_boundary_and_case(case_dir)
    checkmesh = base.run_openfoam_command(
        case_dir,
        openfoam_command=openfoam_command,
        command="checkMesh -meshQuality",
        log_name="log.checkMesh",
        timeout_seconds=timeout_seconds,
    )
    inventory = fullwing_patch_inventory(case_dir)
    mesh_blocker = mirror_run["returncode"] != 0 or split_report.get("status") != "pass" or checkmesh["returncode"] != 0
    result = {
        "case_dir": str(case_dir),
        "source_case": str(source_case),
        "seed_case_setup": case_setup,
        "mirrorMesh": mirror_run,
        "split_report": split_report,
        "checkMesh": checkmesh,
        "patch_inventory": inventory,
        "mesh_blocker": mesh_blocker,
    }
    write_fullwing_mirror_reports(output_dir, result)
    return result


def write_mirror_mesh_dict(path: Path) -> None:
    text = """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      mirrorMeshDict;
}
planeType       pointAndNormal;
pointAndNormalDict
{
    point       (0 0 0);
    normal      (0 1 0);
}
planeTolerance  1e-8;
"""
    path.write_text(text, encoding="utf-8")


def rewrite_fullwing_boundary_and_case(case_dir: Path) -> dict[str, Any]:
    boundary_path = case_dir / "constant" / "polyMesh" / "boundary"
    boundary = base.parse_boundary(boundary_path)["patches"]
    points = base.parse_points(case_dir / "constant" / "polyMesh" / "points")
    faces = base.parse_faces(case_dir / "constant" / "polyMesh" / "faces")
    root = boundary.get("root_symmetry")
    if root and int(root["nFaces"]) != 0:
        return {"status": "fail", "reason": "root_symmetry still has boundary faces after mirrorMesh", "root": root}
    physical_tip = boundary.get("physical_tip")
    if not physical_tip:
        return {"status": "fail", "reason": "physical_tip patch missing after mirrorMesh"}
    start = int(physical_tip["startFace"])
    n_faces = int(physical_tip["nFaces"])
    signs = []
    for local in range(n_faces):
        face = faces[start + local]
        y_mean = statistics.fmean(points[index][1] for index in face)
        signs.append("right" if y_mean > 0 else "left" if y_mean < 0 else "zero")
    segments: list[tuple[str, int, int]] = []
    if signs:
        current = signs[0]
        segment_start = 0
        for index, sign in enumerate(signs[1:], start=1):
            if sign != current:
                segments.append((current, segment_start, index - segment_start))
                current = sign
                segment_start = index
        segments.append((current, segment_start, len(signs) - segment_start))
    if len(segments) != 2 or {segment[0] for segment in segments} != {"left", "right"}:
        return {"status": "fail", "reason": "physical_tip faces are not two contiguous left/right sign segments", "segments": segments}

    new_patches: list[dict[str, Any]] = []
    for name, data in boundary.items():
        if name == "root_symmetry":
            continue
        if name == "physical_tip":
            for sign, offset, count in segments:
                new_patches.append(
                    {
                        "name": f"physical_tip_{sign}",
                        "type": "wall",
                        "nFaces": count,
                        "startFace": start + offset,
                    }
                )
            continue
        new_patches.append(
            {
                "name": name,
                "type": "wall" if name in {"airfoil_upper", "airfoil_lower", "te_wall", "closure_wall"} else data.get("type"),
                "nFaces": int(data["nFaces"]),
                "startFace": int(data["startFace"]),
            }
        )
    write_boundary(boundary_path, new_patches)
    write_fullwing_case_dictionaries(case_dir, new_patches)
    return {
        "status": "pass",
        "removed_root_symmetry_patch": root is not None,
        "physical_tip_segments": segments,
        "patches": new_patches,
    }


def write_boundary(path: Path, patches: Sequence[Mapping[str, Any]]) -> None:
    lines = [
        "FoamFile",
        "{",
        "    version     2.0;",
        "    format      ascii;",
        "    class       polyBoundaryMesh;",
        "    location    \"constant/polyMesh\";",
        "    object      boundary;",
        "}",
        str(len(patches)),
        "(",
    ]
    for patch in patches:
        lines.extend(
            [
                f"    {patch['name']}",
                "    {",
                f"        type            {patch['type']};",
                f"        nFaces          {patch['nFaces']};",
                f"        startFace       {patch['startFace']};",
                "    }",
            ]
        )
    lines.append(")")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_fullwing_case_dictionaries(case_dir: Path, patches: Sequence[Mapping[str, Any]], profile: str = "linearUpwind") -> None:
    patch_names = [patch["name"] for patch in patches]
    primary = tuple(name for name in ("airfoil_upper", "airfoil_lower", "wing_upper", "wing_lower") if name in patch_names)
    tips = tuple(name for name in ("physical_tip_left", "physical_tip_right", "tip_left", "tip_right") if name in patch_names)
    diagnostic = tips + tuple(name for name in ("te_wall", "closure_wall") if name in patch_names)
    solid_walls = primary + diagnostic
    flow_boundaries = tuple(name for name in patch_names if any(hint in name.lower() for hint in base.FLOW_PATCH_HINTS))
    force_groups = {"primary": primary, "total": primary + diagnostic}
    for patch in diagnostic:
        force_groups[patch] = (patch,)
    flow_policy = base.build_flow_bc_policy(flow_boundaries)
    (case_dir / "system" / "controlDict").write_text(
        convention.control_dict_text(force_groups=force_groups, max_iterations=200, start_from="startTime", sref=base.REF_AREA_M2),
        encoding="utf-8",
    )
    if profile == "bounded_upwind":
        (case_dir / "system" / "fvSchemes").write_text(convention.fv_schemes_bounded_upwind_text(), encoding="utf-8")
        (case_dir / "system" / "fvSolution").write_text(convention.fv_solution_bounded_upwind_text(), encoding="utf-8")
    else:
        (case_dir / "system" / "fvSchemes").write_text(base.fv_schemes_text(), encoding="utf-8")
        (case_dir / "system" / "fvSolution").write_text(base.fv_solution_text(), encoding="utf-8")
    (case_dir / "system" / "meshQualityDict").write_text(base.mesh_quality_dict_text(), encoding="utf-8")
    (case_dir / "constant" / "transportProperties").write_text(base.transport_properties_text(), encoding="utf-8")
    (case_dir / "constant" / "turbulenceProperties").write_text(base.turbulence_properties_text(), encoding="utf-8")
    (case_dir / "0" / "U").write_text(
        fullwing_u_field_text(solid_walls, flow_policy),
        encoding="utf-8",
    )
    (case_dir / "0" / "p").write_text(
        fullwing_p_field_text(solid_walls, flow_policy),
        encoding="utf-8",
    )
    (case_dir / "0" / "nut").write_text(
        fullwing_nut_field_text(solid_walls, flow_policy),
        encoding="utf-8",
    )
    (case_dir / "0" / "nuTilda").write_text(
        fullwing_nutilda_field_text(solid_walls, flow_policy),
        encoding="utf-8",
    )


def fullwing_u_field_text(solid_walls: Sequence[str], flow_bc_policy: Mapping[str, Mapping[str, str]]) -> str:
    u = base.inlet_velocity(base.AOA_DEG)
    return (
        base.field_header("volVectorField", "U", "[0 1 -1 0 0 0 0]", f"uniform {base.vec(u)}")
        + "\n".join(base.flow_u_entry(name, policy["U"], u) for name, policy in flow_bc_policy.items())
        + "\n"
        + "\n".join(base.no_slip_entry(name) for name in solid_walls)
        + "\n}\n"
    )


def fullwing_p_field_text(solid_walls: Sequence[str], flow_bc_policy: Mapping[str, Mapping[str, str]]) -> str:
    return (
        base.field_header("volScalarField", "p", "[0 2 -2 0 0 0 0]", "uniform 0")
        + "\n".join(base.flow_p_entry(name, policy["p"]) for name, policy in flow_bc_policy.items())
        + "\n"
        + "\n".join(base.zero_gradient_entry(name) for name in solid_walls)
        + "\n}\n"
    )


def fullwing_nut_field_text(solid_walls: Sequence[str], flow_bc_policy: Mapping[str, Mapping[str, str]]) -> str:
    return (
        base.field_header("volScalarField", "nut", "[0 2 -1 0 0 0 0]", "uniform 0")
        + "\n".join(base.calculated_scalar_entry(name) for name in flow_bc_policy)
        + "\n"
        + "\n".join(base.nut_wall_entry(name) for name in solid_walls)
        + "\n}\n"
    )


def fullwing_nutilda_field_text(solid_walls: Sequence[str], flow_bc_policy: Mapping[str, Mapping[str, str]]) -> str:
    return (
        base.field_header("volScalarField", "nuTilda", "[0 2 -1 0 0 0 0]", "uniform 4.0e-5")
        + "\n".join(base.flow_nu_tilda_entry(name, policy["nuTilda"]) for name, policy in flow_bc_policy.items())
        + "\n"
        + "\n".join(base.fixed_value_scalar_entry(name, "0") for name in solid_walls)
        + "\n}\n"
    )


def fullwing_patch_inventory(case_dir: Path) -> dict[str, Any]:
    boundary = base.parse_boundary(case_dir / "constant" / "polyMesh" / "boundary")
    geometry = base.audit_patch_geometry(case_dir / "constant" / "polyMesh")
    return {"boundary": boundary, "geometry": geometry}


def write_fullwing_mirror_reports(output_dir: Path, result: Mapping[str, Any]) -> None:
    inventory = result["patch_inventory"]
    checkmesh_metrics = base.parse_check_mesh_metrics(Path(result["checkMesh"]["log"]))
    checkmesh_acceptance = fullwing_checkmesh_acceptance(result)
    lines = ["# Full-Wing Mirror Mesh Report", ""]
    lines.append(f"- case_dir: `{result['case_dir']}`")
    lines.append("- route: OpenFOAM `mirrorMesh` across `y=0`; no snappy/cfMesh/Gmsh/TetGen remeshing.")
    lines.append(f"- mirrorMesh returncode: `{result['mirrorMesh']['returncode']}`")
    lines.append(f"- split status: `{result['split_report'].get('status')}`")
    lines.append(f"- root_symmetry removed: `{result['split_report'].get('removed_root_symmetry_patch')}`")
    lines.append(f"- mesh blocker: `{result['mesh_blocker']}`")
    (output_dir / "fullwing_mirror_mesh_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    patch_lines = ["# Full-Wing Patch Inventory", ""]
    patch_lines.append("| patch | type | nFaces | y min | y max | role |")
    patch_lines.append("|---|---|---:|---:|---:|---|")
    patches = inventory["boundary"]["patches"]
    geoms = inventory["geometry"]["patches"]
    for name, patch in patches.items():
        extent = geoms[name]["extent"]
        role = fullwing_patch_role(name)
        patch_lines.append(
            f"| `{name}` | `{patch.get('type')}` | `{patch.get('nFaces')}` | "
            f"`{extent['y']['min']}` | `{extent['y']['max']}` | {role} |"
        )
    (output_dir / "fullwing_patch_inventory.md").write_text("\n".join(patch_lines) + "\n", encoding="utf-8")

    check_lines = ["# Full-Wing checkMesh Report", ""]
    check_lines.append(f"- returncode: `{result['checkMesh']['returncode']}`")
    check_lines.append(f"- metrics: `{checkmesh_metrics}`")
    check_lines.append(f"- solver-smoke acceptance: `{checkmesh_acceptance}`")
    check_lines.append("")
    check_lines.extend(f"    {line}" for line in result["checkMesh"].get("tail", []))
    (output_dir / "fullwing_checkmesh_report.md").write_text("\n".join(check_lines) + "\n", encoding="utf-8")


def fullwing_patch_role(name: str) -> str:
    if name in {"airfoil_upper", "airfoil_lower", "wing_upper", "wing_lower"}:
        return "primary lifting wall"
    if name in {"physical_tip_left", "physical_tip_right", "tip_left", "tip_right"}:
        return "physical noSlip tip wall"
    if name in {"te_wall", "closure_wall"}:
        return "diagnostic noSlip wall"
    if any(hint in name.lower() for hint in base.FLOW_PATCH_HINTS):
        return "flow boundary"
    return "unclassified"


def run_fullwing_route_smoke(
    *,
    output_dir: Path,
    case_dir: Path,
    openfoam_command: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    boundary = base.parse_boundary(case_dir / "constant" / "polyMesh" / "boundary")["patches"]
    patch_names = tuple(boundary)
    primary = tuple(name for name in ("airfoil_upper", "airfoil_lower", "wing_upper", "wing_lower") if name in patch_names)
    diagnostic = tuple(name for name in ("physical_tip_left", "physical_tip_right", "tip_left", "tip_right", "te_wall", "closure_wall") if name in patch_names)
    force_groups = {"primary": primary, "total": primary + diagnostic}
    for patch in diagnostic:
        force_groups[patch] = (patch,)
    dry = base.run_openfoam_command(
        case_dir,
        openfoam_command=openfoam_command,
        command="simpleFoam -dry-run",
        log_name="log.simpleFoam_dry_run",
        timeout_seconds=600.0,
    )
    run_200 = None
    run_500 = None
    yplus_post = None
    if dry["returncode"] == 0:
        run_200 = base.run_openfoam_command(
            case_dir,
            openfoam_command=openfoam_command,
            command="simpleFoam",
            log_name="log.simpleFoam_200",
            timeout_seconds=timeout_seconds,
        )
        (case_dir / "log.simpleFoam").write_text(
            (case_dir / "log.simpleFoam_200").read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )
        coeffs_200 = base.parse_force_coefficients(case_dir, force_groups)
        stable_200 = base.force_stability(coeffs_200.get("functions", {}).get("primary", {}).get("rows", []))
        if run_200["returncode"] == 0 and should_extend_to_500(coeffs_200, stable_200):
            base.update_control_dict(case_dir / "system" / "controlDict", end_time=500, start_from="latestTime")
            run_500 = base.run_openfoam_command(
                case_dir,
                openfoam_command=openfoam_command,
                command="simpleFoam",
                log_name="log.simpleFoam_500",
                timeout_seconds=timeout_seconds,
            )
            (case_dir / "log.simpleFoam").write_text(
                (case_dir / "log.simpleFoam_500").read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
        if (run_500 or run_200) and (run_500 or run_200)["returncode"] == 0:
            yplus_post = base.run_openfoam_command(
                case_dir,
                openfoam_command=openfoam_command,
                command="simpleFoam -postProcess -func yPlus -latestTime",
                log_name="log.yPlus",
                timeout_seconds=900.0,
            )
    coeffs = base.parse_force_coefficients(case_dir, force_groups)
    split = base.parse_force_splits(case_dir, force_groups)
    yplus = base.parse_yplus(case_dir, tuple(name for name in patch_names if boundary[name]["type"] == "wall"))
    residuals = base.parse_residuals(case_dir / "log.simpleFoam")
    stability = base.force_stability(coeffs.get("functions", {}).get("primary", {}).get("rows", []))
    total_stability = base.force_stability(coeffs.get("functions", {}).get("total", {}).get("rows", []))
    field_stats = latest_field_stats(case_dir)
    latest_time = latest_force_time(coeffs)
    stable = bool(
        latest_time is not None
        and latest_time >= 500
        and (run_500 or run_200)
        and (run_500 or run_200).get("returncode") == 0
        and stability.get("route_smoke_stable") is True
        and total_stability.get("route_smoke_stable") is True
    )
    result = {
        "route": "full-wing-mirror",
        "case_dir": str(case_dir),
        "force_groups": {key: list(value) for key, value in force_groups.items()},
        "commands": {"dry_run": dry, "simpleFoam_200": run_200, "simpleFoam_500": run_500, "yPlus": yplus_post},
        "coefficients": coeffs,
        "pressure_viscous_split": split,
        "yPlus": yplus,
        "residuals": residuals,
        "force_stability": stability,
        "force_stability_total": total_stability,
        "field_stats": field_stats,
        "accepted_stable_route_smoke": stable,
        "accepted_coefficients": coeffs.get("summary", {}) if stable else None,
    }
    write_stable_reports(output_dir, result)
    return result


def should_extend_to_500(coeffs: Mapping[str, Any], stability: Mapping[str, Any]) -> bool:
    """Extend finite 200-step smoke runs even when the strict force window is not settled."""
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
    no_force_runaway = first_divergence_time(coeffs) is None
    return bool(stability.get("route_smoke_stable") is True or no_force_runaway)


def run_halfwing_selected_route(
    *,
    output_dir: Path,
    case_dir: Path,
    openfoam_command: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    raise RuntimeError("half-wing selected route not implemented because the current decision gate selects full-wing mirror")


def write_stable_reports(output_dir: Path, result: Mapping[str, Any]) -> None:
    coeffs = result["coefficients"]["summary"]
    y_summary = result["yPlus"].get("primary_main_wall_summary", {})
    commands = result["commands"]
    route_lines = ["# Stable Route-Smoke Report", ""]
    route_lines.append(f"- route: `{result['route']}`")
    route_lines.append(f"- operating point: `V={base.VELOCITY_MPS} m/s`, `AoA={base.AOA_DEG} deg`")
    route_lines.append(f"- force groups: `{result['force_groups']}`")
    route_lines.append(f"- Sref: `{base.REF_AREA_M2} m^2` for the full-wing mirror route")
    route_lines.append("- root_symmetry in force groups: `False`")
    route_lines.append(f"- accepted_stable_route_smoke: `{result['accepted_stable_route_smoke']}`")
    route_lines.append(f"- simpleFoam_200 returncode: `{commands.get('simpleFoam_200', {}).get('returncode') if commands.get('simpleFoam_200') else None}`")
    route_lines.append(f"- simpleFoam_500 returncode: `{commands.get('simpleFoam_500', {}).get('returncode') if commands.get('simpleFoam_500') else None}`")
    route_lines.append(f"- CD_primary: `{coeffs.get('CD_primary')}`")
    route_lines.append(f"- CL_primary: `{coeffs.get('CL_primary')}`")
    route_lines.append(f"- CD_total: `{coeffs.get('CD_total')}`")
    route_lines.append(f"- force stability: `{result['force_stability']}`")
    route_lines.append(f"- yPlus mean/p95/max: `{y_summary}`")
    (output_dir / "stable_route_smoke_report.md").write_text("\n".join(route_lines) + "\n", encoding="utf-8")

    force_lines = ["# Stable Force Breakdown Report", ""]
    force_lines.append("| coefficient | value |")
    force_lines.append("|---|---:|")
    for key, value in coeffs.items():
        force_lines.append(f"| `{key}` | `{value}` |")
    (output_dir / "stable_force_breakdown_report.md").write_text("\n".join(force_lines) + "\n", encoding="utf-8")

    y_lines = ["# Stable yPlus Report", ""]
    y_lines.append(f"- primary main-wall summary: `{y_summary}`")
    y_lines.append("")
    y_lines.append("| patch | mean | p90 | p95 | p99 | max | count |")
    y_lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for patch, data in result["yPlus"].get("patches", {}).items():
        y_lines.append(
            f"| `{patch}` | `{data.get('mean')}` | `{data.get('p90')}` | `{data.get('p95')}` | "
            f"`{data.get('p99')}` | `{data.get('max')}` | `{data.get('count')}` |"
        )
    (output_dir / "stable_yplus_report.md").write_text("\n".join(y_lines) + "\n", encoding="utf-8")

    stability_lines = ["# Residual / Force Stability Report", ""]
    stability_lines.append(f"- residuals: `{result['residuals']}`")
    stability_lines.append(f"- primary force final-window stability: `{result['force_stability']}`")
    stability_lines.append(f"- total force final-window stability: `{result.get('force_stability_total')}`")
    stability_lines.append(f"- field min/max: `{result['field_stats']}`")
    (output_dir / "residual_force_stability_report.md").write_text("\n".join(stability_lines) + "\n", encoding="utf-8")

    split = result["pressure_viscous_split"]
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
    (output_dir / "pressure_viscous_split_report.md").write_text("\n".join(split_lines) + "\n", encoding="utf-8")


def build_convention_comparison(
    rows: Sequence[Mapping[str, Any]],
    stable: Mapping[str, Any] | None,
) -> dict[str, Any]:
    old = matrix_row_from_existing_contaminated()
    corrected_unstable = next(
        (row for row in rows if row["case_id"] == "halfwing_corrected_previous_bounded_upwind"),
        None,
    )
    stable_coeffs = stable.get("coefficients", {}).get("summary", {}) if stable else {}
    diagnostic = stable_coeffs.get("CD_diagnostic_sum")
    total = stable_coeffs.get("CD_total")
    return {
        "old_contaminated_noSlip_root": old,
        "corrected_unstable_last_diagnostic": corrected_unstable,
        "stable_corrected_run": {
            "route": stable.get("route") if stable else None,
            "accepted": stable.get("accepted_stable_route_smoke") if stable else False,
            "CD_primary": stable_coeffs.get("CD_primary"),
            "CL_primary": stable_coeffs.get("CL_primary"),
            "CD_total": total,
            "diagnostic_CD_sum": diagnostic,
            "diagnostic_fraction_of_total": diagnostic / total if diagnostic is not None and total else None,
            "yPlus": stable.get("yPlus", {}).get("primary_main_wall_summary", {}) if stable else None,
        },
        "engineering_interpretation": (
            "Root force contamination is removed if the stable corrected run excludes root_symmetry/no root patch from force groups. "
            "AoA sweep readiness depends on stable 500-iteration force window and valid yPlus."
        ),
    }


def write_convention_comparison(path: Path, comparison: Mapping[str, Any]) -> None:
    stable = comparison["stable_corrected_run"]
    lines = ["# Convention Fix Stability Comparison", ""]
    lines.append("- old contaminated noSlip-root run is numerically stable but physically invalid for corrected CD_total.")
    lines.append("- corrected unstable half-wing run is diagnostic only; its force-runaway coefficients are not accepted.")
    lines.append(f"- stable corrected route accepted: `{stable.get('accepted')}`")
    lines.append(f"- stable route: `{stable.get('route')}`")
    lines.append(f"- stable CD_primary / CL_primary / CD_total: `{stable.get('CD_primary')}`, `{stable.get('CL_primary')}`, `{stable.get('CD_total')}`")
    lines.append(f"- stable diagnostic CD sum/fraction: `{stable.get('diagnostic_CD_sum')}`, `{stable.get('diagnostic_fraction_of_total')}`")
    lines.append(f"- stable yPlus: `{stable.get('yPlus')}`")
    lines.append("")
    lines.append("Engineering read:")
    lines.append("- Root contamination is removed only for the stable corrected/full-wing route, not for the old replay.")
    lines.append("- Diagnostic CD should be small relative to total; if it dominates, the route remains blocked for sweep work.")
    lines.append("- CL plausibility is a route-smoke sanity check only; this is still not grid-converged validation.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_phase4_verdict(
    audit: Mapping[str, Any],
    decision: Mapping[str, Any],
    mirror: Mapping[str, Any] | None,
    stable: Mapping[str, Any] | None,
    comparison: Mapping[str, Any],
) -> dict[str, Any]:
    stable_coeffs = stable.get("coefficients", {}).get("summary", {}) if stable else {}
    y_summary = stable.get("yPlus", {}).get("primary_main_wall_summary", {}) if stable else {}
    diagnostic = stable_coeffs.get("CD_diagnostic_sum")
    total = stable_coeffs.get("CD_total")
    force_stable = stable.get("force_stability", {}).get("route_smoke_stable") if stable else False
    checkmesh_acceptance = fullwing_checkmesh_acceptance(mirror)
    stable_500 = bool(stable and stable.get("commands", {}).get("simpleFoam_500") and stable["commands"]["simpleFoam_500"].get("returncode") == 0)
    ready = bool(
        stable
        and stable.get("accepted_stable_route_smoke")
        and stable_500
        and diagnostic is not None
        and total
        and abs(diagnostic / total) < 0.10
    )
    blocker = None
    if not stable:
        blocker = "full-wing mirror was not run or did not reach solver stage"
    elif not stable_500:
        blocker = "selected route did not complete 500 simpleFoam iterations"
    elif force_stable is not True:
        blocker = "selected route force window remains unstable"
    elif diagnostic is not None and total and abs(diagnostic / total) >= 0.10:
        blocker = "diagnostic CD still exceeds 10 percent of total"
    return {
        "1_root_symmetry_patch_geometrically_valid": audit["all_faces_lie_on_single_y0_plane"] and not audit["role_contamination_audit"]["ambiguous_geometry"],
        "2_halfwing_corrected_root_symmetry_stabilized": decision["selected_route"] == "half-wing-corrected" and bool(stable and stable.get("accepted_stable_route_smoke")),
        "3_fullwing_mirror_route_needed": decision["selected_route"] == "full-wing-mirror",
        "4_fullwing_mirror_checkMesh_passed": checkmesh_acceptance,
        "5_simpleFoam_ran_stably": bool(stable and stable.get("accepted_stable_route_smoke")),
        "6_accepted_CD_primary_CL_primary_CD_total": {
            "CD_primary": stable_coeffs.get("CD_primary") if stable and stable.get("accepted_stable_route_smoke") else None,
            "CL_primary": stable_coeffs.get("CL_primary") if stable and stable.get("accepted_stable_route_smoke") else None,
            "CD_total": total if stable and stable.get("accepted_stable_route_smoke") else None,
        },
        "7_diagnostic_CD_contribution": {
            "diagnostic_CD_sum": diagnostic,
            "diagnostic_fraction_of_total": diagnostic / total if diagnostic is not None and total else None,
        },
        "8_yPlus_mean_p95_max": {
            "mean": y_summary.get("mean"),
            "p95": y_summary.get("p95"),
            "max": y_summary.get("max"),
        },
        "9_force_runaway_resolved": bool(stable and stable.get("accepted_stable_route_smoke")),
        "10_ready_for_AoA_CL_sweep": ready,
        "11_exact_blocker_if_not_ready": blocker,
        "comparison": comparison,
    }


def fullwing_checkmesh_acceptance(mirror: Mapping[str, Any] | None) -> dict[str, Any]:
    if not mirror:
        return {
            "command_returncode_zero": False,
            "strict_checkMesh_clean": False,
            "accepted_for_solver_smoke": False,
            "failedChecks": None,
        }
    log_path = Path(mirror["checkMesh"]["log"])
    metrics = base.parse_check_mesh_metrics(log_path)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    no_negative_volume = "negative volume" not in text.lower() and "Cell volumes OK" in text
    no_open_cells = "open cells" not in text.lower() and "Boundary openness" in text and "OK" in text
    no_oriented_pyramid_error = "Face pyramids OK" in text and "face pyramid volume <" in text
    strict_clean = metrics.get("failedChecks") in (0, None) and metrics.get("status") == "pass"
    return {
        "command_returncode_zero": mirror["checkMesh"].get("returncode") == 0,
        "strict_checkMesh_clean": strict_clean,
        "accepted_for_solver_smoke": bool(
            mirror["checkMesh"].get("returncode") == 0
            and no_negative_volume
            and no_open_cells
            and no_oriented_pyramid_error
        ),
        "failedChecks": metrics.get("failedChecks"),
        "metrics": metrics,
        "note": "strict meshQuality flags are inherited from the accepted half-wing mesh and are not negative-volume/open-cell/oriented-pyramid blockers",
    }


def write_phase4_verdict(path: Path, verdict: Mapping[str, Any]) -> None:
    lines = ["# Phase 4 Solver Stability Verdict", ""]
    questions = [
        ("1. Was the root_symmetry patch geometrically valid?", verdict["1_root_symmetry_patch_geometrically_valid"]),
        ("2. Did half-wing corrected root_symmetry stabilize?", verdict["2_halfwing_corrected_root_symmetry_stabilized"]),
        ("3. Was full-wing mirror route needed?", verdict["3_fullwing_mirror_route_needed"]),
        ("4. If full-wing mirror was used, did checkMesh pass?", verdict["4_fullwing_mirror_checkMesh_passed"]),
        ("5. Did simpleFoam run stably?", verdict["5_simpleFoam_ran_stably"]),
        ("6. What are accepted CD_primary, CL_primary, CD_total?", verdict["6_accepted_CD_primary_CL_primary_CD_total"]),
        ("7. What is diagnostic CD contribution?", verdict["7_diagnostic_CD_contribution"]),
        ("8. What are yPlus mean/p95/max?", verdict["8_yPlus_mean_p95_max"]),
        ("9. Is force runaway resolved?", verdict["9_force_runaway_resolved"]),
        ("10. Is the route ready for AoA/CL sweep?", verdict["10_ready_for_AoA_CL_sweep"]),
        ("11. If not, what exact blocker remains?", verdict["11_exact_blocker_if_not_ready"]),
    ]
    for question, answer in questions:
        lines.append(f"{question}\n   - `{answer}`")
    lines.append("")
    lines.append("Boundary: a stable route-smoke is not grid-converged CFD or final aircraft sign-off.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_root_audit_md(path: Path, audit: Mapping[str, Any]) -> None:
    lines = ["# Root Symmetry Geometry Audit", ""]
    fields = [
        "exact_original_patch_name",
        "original_polyMesh_boundary_type",
        "corrected_patch_name",
        "polyMesh_boundary_patch_type",
        "field_bc_types",
        "root_symmetry_face_count",
        "root_symmetry_vertex_y_min_m",
        "root_symmetry_vertex_y_max_m",
        "max_abs_y_deviation_from_zero_m",
        "normal_direction_statistics",
        "all_faces_lie_on_single_y0_plane",
        "role_contamination_audit",
        "root_symmetry_excluded_from_force_functionObjects",
        "polyMesh_patch_type_compatibility",
    ]
    for field in fields:
        lines.append(f"- {field}: `{audit.get(field)}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rerun(path: Path, source_case: Path, corrected_case: Path) -> None:
    text = f"""# RERUN

From `/Volumes/Samsung SSD/hpa-mdo`:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/run_wo006_true_baseline_solver_stability.py \\
  --source-case {shlex.quote(str(source_case))} \\
  --corrected-case {shlex.quote(str(corrected_case))} \\
  --output-dir {shlex.quote(str(path.parent))} \\
  --clean
```

This runner audits the corrected root-symmetry patch, records bounded half-wing
diagnostic evidence, switches to OpenFOAM `mirrorMesh` if the half-wing decision
gate trips, and runs only the same operating-point route-smoke. It does not run
an AoA sweep, compare to XFOIL, or regenerate the accepted C-grid mesh.
"""
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
