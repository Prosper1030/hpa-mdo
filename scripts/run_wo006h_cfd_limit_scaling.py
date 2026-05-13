#!/usr/bin/env python3
"""Run WO-006H Baseline A CFD local scaling and HPC package campaign.

WO-006H is an engineering campaign driver, not a coefficient promotion script.
It attempts current-Baseline-A mesh scaling locally, records resource/failure
evidence, and emits a directly runnable larger-compute package if local
geometry/mesh/solver gates still block credible CFD.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import multiprocessing as mp
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    build_wing_feature_refinement_boxes,
    write_boundary_layer_block_core_tet_mesh,
    write_faceted_volume_su2_case,
)
from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    build_boundary_layer_core_interface_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    build_farfield_box_surface,
    validate_surface_mesh,
)
from run_wo006r1_go_baseline_a_cfd_bridge import (  # noqa: E402
    _patch_runtime_reference_origin,
    build_current_go_wing_surface,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    MU_PA_S,
    RHO_KGPM3,
    VELOCITY_MPS,
    load_campaign_geometry,
)


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006h_cfd_limit_scaling"
SU2_COMMAND = "/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD"
DESIGN_GROSS_MASS_KG = 98.5
PIPELINE_FULL_SPAN_M = 34.332286
PIPELINE_HALF_SPAN_M = 17.166143
SREF_M2 = 33.420059598
CREF_M = 1.003721543
BREF_M = 34.332286
G0_MPS2 = 9.80665


@dataclass(frozen=True)
class NoBlMeshAttempt:
    attempt_id: str
    mesh_size: float
    farfield_mesh_size: float
    wing_refinement_radius: float
    feature_refinement_size: float
    timeout_seconds: float
    mesh_algorithm3d: int = 10


@dataclass(frozen=True)
class CoreVariantAttempt:
    attempt_id: str
    mesh_size: float
    farfield_mesh_size: float
    mesh_algorithm3d: int
    preserve_boundary_mesh: bool
    timeout_seconds: float


def required_cl(
    *,
    mass_kg: float = DESIGN_GROSS_MASS_KG,
    density_kgpm3: float = RHO_KGPM3,
    velocity_mps: float = VELOCITY_MPS,
    sref_m2: float = SREF_M2,
) -> float:
    q = 0.5 * density_kgpm3 * velocity_mps * velocity_mps
    return mass_kg * G0_MPS2 / (q * sref_m2)


def classify_verdict(
    *,
    no_bl_attempts: Sequence[Mapping[str, Any]],
    core_attempts: Sequence[Mapping[str, Any]],
) -> str:
    credible_mesh = any(
        attempt.get("status") == "meshed"
        and attempt.get("boundary_layer_present") is True
        and attempt.get("mesh_quality_status") == "pass"
        and attempt.get("can_merge_core_with_bl_block") is True
        and int(attempt.get("unmatched_core_interface_face_count") or 0) == 0
        and int(attempt.get("unmatched_bl_boundary_face_count") or 0) == 0
        for attempt in core_attempts
    )
    if credible_mesh:
        return "wo006h_bl_mesh_route_ready_needs_solver_grid_study"
    serious_no_bl = any(_is_serious_no_bl_scaling_attempt(attempt) for attempt in no_bl_attempts)
    if serious_no_bl:
        return "wo006h_serious_no_bl_scaling_only_not_cfd_result"
    return "wo006h_campaign_incomplete_needs_more_scaling"


def _is_serious_no_bl_scaling_attempt(attempt: Mapping[str, Any]) -> bool:
    return attempt.get("status") == "meshed" and int(attempt.get("volume_element_count") or 0) >= 1_000_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--clean", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--mesh-sizes",
        type=float,
        nargs="+",
        default=[0.10, 0.08, 0.06],
        help="No-BL wing mesh sizes to attempt. Existing R3 0.12/0.15 evidence is reused.",
    )
    parser.add_argument(
        "--no-bl-mesh-algorithm3d",
        type=int,
        default=10,
        help="Gmsh Mesh.Algorithm3D for no-BL controls; 10=HXT, 1=Delaunay.",
    )
    parser.add_argument("--mesh-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--core-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--skip-local-runs", action="store_true")
    parser.add_argument("--skip-no-bl-ladder", action="store_true")
    parser.add_argument("--skip-core-variants", action="store_true")
    args = parser.parse_args(argv)

    output_dir = args.output_dir
    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    machine = collect_machine_context()
    old_evidence = old_evidence_rows()
    authority = authority_payload()
    write_json(output_dir / "authority_and_environment.json", {
        "schema_version": "wo006h_authority_and_environment.v1",
        "authority": authority,
        "machine": machine,
        "toolchain": collect_toolchain_context(),
        "old_evidence": old_evidence,
        "official_sources": official_sources(),
    })
    write_csv(output_dir / "old_evidence_map.csv", old_evidence)

    no_bl_attempts: list[dict[str, Any]] = []
    core_attempts: list[dict[str, Any]] = []
    if not args.skip_local_runs:
        if not args.skip_no_bl_ladder:
            no_bl_attempts = run_no_bl_mesh_ladder(
                output_dir=output_dir / "local_no_bl_scaling",
                mesh_sizes=args.mesh_sizes,
                timeout_seconds=args.mesh_timeout_seconds,
                mesh_algorithm3d=args.no_bl_mesh_algorithm3d,
            )
        if not args.skip_core_variants:
            core_attempts = run_core_variant_attempts(
                output_dir=output_dir / "local_bl_core_variants",
                timeout_seconds=args.core_timeout_seconds,
            )

    verdict = classify_verdict(no_bl_attempts=no_bl_attempts, core_attempts=core_attempts)
    summary = {
        "schema_version": "wo006h_cfd_limit_scaling_summary.v1",
        "verdict": verdict,
        "completion_interpretation": completion_interpretation(verdict),
        "authority": authority,
        "required_cl_at_authority_condition": required_cl(),
        "local_machine": machine,
        "no_bl_attempts": no_bl_attempts,
        "core_variant_attempts": core_attempts,
        "engineering_read": engineering_read(verdict, no_bl_attempts, core_attempts),
        "blocked_claims": [
            "physically credible Baseline A SU2 drag",
            "low-confidence BL-resolved CL/CD/Cm",
            "drag/power calibration",
            "Baseline A reopen evidence",
            "RFQ/procurement truth",
            "final aircraft sign-off",
        ],
    }
    write_json(output_dir / "wo006h_cfd_limit_scaling_summary.json", summary)
    write_csv(output_dir / "local_no_bl_scaling_attempts.csv", no_bl_attempts)
    write_csv(output_dir / "local_bl_core_variant_attempts.csv", core_attempts)
    write_hpc_package(output_dir / "hpc_escalation_package")
    write_report(output_dir / "wo006h_cfd_limit_scaling_report.md", summary)
    write_reviewer_prompt(output_dir / "reviewer_prompt.md", summary)

    print(json.dumps({"verdict": verdict, "output_dir": str(output_dir)}, indent=2))
    return 0


def run_no_bl_mesh_ladder(
    *,
    output_dir: Path,
    mesh_sizes: Sequence[float],
    timeout_seconds: float,
    mesh_algorithm3d: int = 10,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    attempts = [
        NoBlMeshAttempt(
            attempt_id=f"no_bl_h_{slug(mesh_size)}",
            mesh_size=float(mesh_size),
            farfield_mesh_size=max(4.0, 40.0 * float(mesh_size)),
            wing_refinement_radius=6.0,
            feature_refinement_size=max(0.12, 1.5 * float(mesh_size)),
            timeout_seconds=timeout_seconds,
            mesh_algorithm3d=int(mesh_algorithm3d),
        )
        for mesh_size in mesh_sizes
    ]
    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        row = run_worker_with_timeout(
            target=no_bl_mesh_worker,
            payload=attempt.__dict__,
            case_dir=output_dir / attempt.attempt_id,
            timeout_seconds=attempt.timeout_seconds,
        )
        rows.append(row)
        write_json(output_dir / attempt.attempt_id / "attempt_summary.json", row)
        if row.get("status") in {"timeout", "failed", "terminated"}:
            break
    return rows


def no_bl_mesh_worker(queue: Any, *, payload: Mapping[str, Any], case_dir: str) -> None:
    start = time.time()
    case_path = Path(case_dir)
    case_path.mkdir(parents=True, exist_ok=True)
    mesh_algorithm3d = int(payload.get("mesh_algorithm3d", 10))
    if mesh_algorithm3d == 10:
        route = "current_go_mesh_native_no_bl_hxt_scaling"
    elif mesh_algorithm3d == 1:
        route = "current_go_mesh_native_no_bl_delaunay_scaling"
    else:
        route = f"current_go_mesh_native_no_bl_alg{mesh_algorithm3d}_scaling"
    try:
        geometry = load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
        wing = build_current_go_wing_surface(geometry)
        farfield = build_farfield_box_surface(
            wing,
            upstream_factor=2.0,
            downstream_factor=4.0,
            lateral_factor=2.0,
            vertical_factor=2.0,
        )
        feature_size = float(payload["feature_refinement_size"])
        report = write_faceted_volume_su2_case(
            wing,
            farfield,
            case_path,
            ref_area=geometry.reference.sref_full,
            ref_length=geometry.reference.cref,
            mesh_size=max(2.0, 25.0 * float(payload["mesh_size"])),
            wing_mesh_size=float(payload["mesh_size"]),
            farfield_mesh_size=float(payload["farfield_mesh_size"]),
            wing_refinement_radius=float(payload["wing_refinement_radius"]),
            refinement_boxes=build_wing_feature_refinement_boxes(wing, mesh_size=feature_size),
            velocity_mps=VELOCITY_MPS,
            alpha_deg=0.0,
            max_iterations=1000,
            solver="INC_NAVIER_STOKES",
            turbulence_model="NONE",
            wall_profile="adiabatic_no_slip",
            conv_num_method_flow="JST",
            cfl_number=0.05,
            linear_solver_iter=20,
            conv_cauchy_elems=100,
            conv_cauchy_eps="1e-4",
            output_files=("RESTART_ASCII", "SURFACE_CSV"),
            gmsh_threads=4,
            mesh_algorithm3d=mesh_algorithm3d,
            surface_triangulation_policy="shorter_diagonal",
        )
        _patch_runtime_reference_origin(Path(report["runtime_cfg_path"]), geometry.moment_origin_m)
        mesh_report = report.get("mesh_report") or {}
        marker_audit = report.get("marker_audit") or {}
        quality = mesh_report.get("quality_metrics") or {}
        row = {
            "attempt_id": payload["attempt_id"],
            "status": "meshed",
            "route": route,
            "mesh_size": payload["mesh_size"],
            "mesh_algorithm3d": mesh_algorithm3d,
            "volume_element_count": mesh_report.get("volume_element_count"),
            "node_count": mesh_report.get("node_count"),
            "mesh_quality_status": (mesh_report.get("mesh_quality_gate") or {}).get("status"),
            "mesh_quality_blockers": (mesh_report.get("mesh_quality_gate") or {}).get("blockers"),
            "marker_audit_status": marker_audit.get("status"),
            "min_gamma": quality.get("min_gamma"),
            "min_sicn": quality.get("min_sicn"),
            "min_sige": quality.get("min_sige"),
            "non_positive_volume_count": quality.get("non_positive_volume_count"),
            "mesh_path": report.get("mesh_path"),
            "runtime_cfg_path": report.get("runtime_cfg_path"),
            "elapsed_seconds": time.time() - start,
            "ru_maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "boundary_layer_present": False,
            "coefficient_interpretable": False,
            "engineering_read": (
                "No-BL mesh scaling evidence only. Marker/quality pass can support "
                "solver wiring, but no-BL tetra drag is not HPA viscous CFD truth."
            ),
        }
    except Exception as exc:  # pragma: no cover - real mesher failures are data.
        row = {
            "attempt_id": payload.get("attempt_id"),
            "status": "failed",
            "route": route,
            "mesh_size": payload.get("mesh_size"),
            "mesh_algorithm3d": mesh_algorithm3d,
            "failure_code": exc.__class__.__name__,
            "error": str(exc),
            "elapsed_seconds": time.time() - start,
            "ru_maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    queue.put(row)


def run_core_variant_attempts(*, output_dir: Path, timeout_seconds: float) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    attempts = [
        CoreVariantAttempt("core_preserve_alg1_h1p0", 1.0, 8.0, 1, True, timeout_seconds),
        CoreVariantAttempt("core_preserve_alg10_h1p0", 1.0, 8.0, 10, True, timeout_seconds),
        CoreVariantAttempt("core_remesh_alg10_h0p5", 0.5, 8.0, 10, False, timeout_seconds),
    ]
    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        row = run_worker_with_timeout(
            target=core_variant_worker,
            payload=attempt.__dict__,
            case_dir=output_dir / attempt.attempt_id,
            timeout_seconds=attempt.timeout_seconds,
        )
        rows.append(row)
        write_json(output_dir / attempt.attempt_id / "attempt_summary.json", row)
    return rows


def core_variant_worker(queue: Any, *, payload: Mapping[str, Any], case_dir: str) -> None:
    start = time.time()
    case_path = Path(case_dir)
    case_path.mkdir(parents=True, exist_ok=True)
    try:
        geometry = load_campaign_geometry(points_per_side=32, spanwise_subdivisions=2)
        block = build_wing_boundary_layer_block(
            geometry.spec.wing_spec,
            BoundaryLayerBlockSpec(
                first_layer_height_m=BL_FIRST_HEIGHT_M,
                growth_ratio=BL_GROWTH_RATIO,
                layer_count=BL_LAYERS,
            ),
        )
        core_interface = build_boundary_layer_core_interface_surface(block)
        validate_surface_mesh(
            core_interface,
            allowed_markers=frozenset({"bl_outer_interface", "wake_cut", "span_cap"}),
            required_markers=("bl_outer_interface", "wake_cut", "span_cap"),
        )
        farfield = build_farfield_box_surface(
            core_interface,
            upstream_factor=2.0,
            downstream_factor=4.0,
            lateral_factor=2.0,
            vertical_factor=2.0,
        )
        report = write_boundary_layer_block_core_tet_mesh(
            block,
            farfield,
            case_path / "core.msh",
            su2_path=case_path / "core.su2",
            mesh_size=float(payload["mesh_size"]),
            farfield_mesh_size=float(payload["farfield_mesh_size"]),
            preserve_boundary_mesh=bool(payload["preserve_boundary_mesh"]),
            gmsh_threads=4,
            mesh_algorithm3d=int(payload["mesh_algorithm3d"]),
        )
        quality = report.get("quality_metrics") or {}
        coupling = report.get("bl_block_coupling") or {}
        row = {
            "attempt_id": payload["attempt_id"],
            "status": report.get("status"),
            "route": "r6_owned_bl_core_variant",
            "mesh_size": payload["mesh_size"],
            "mesh_algorithm3d": payload["mesh_algorithm3d"],
            "preserve_boundary_mesh": payload["preserve_boundary_mesh"],
            "volume_element_count": report.get("volume_element_count"),
            "node_count": report.get("node_count"),
            "mesh_quality_status": (report.get("mesh_quality_gate") or {}).get("status"),
            "mesh_quality_blockers": (report.get("mesh_quality_gate") or {}).get("blockers"),
            "unmatched_core_interface_face_count": coupling.get(
                "unmatched_core_interface_face_count"
            ),
            "unmatched_bl_boundary_face_count": coupling.get(
                "unmatched_bl_boundary_face_count"
            ),
            "can_merge_core_with_bl_block": coupling.get("can_merge_core_with_bl_block"),
            "min_sicn": quality.get("min_sicn"),
            "min_sige": quality.get("min_sige"),
            "non_positive_volume_count": quality.get("non_positive_volume_count"),
            "mesh_path": report.get("mesh_path"),
            "su2_path": report.get("su2_path"),
            "elapsed_seconds": time.time() - start,
            "ru_maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "boundary_layer_present": True,
            "coefficient_interpretable": False,
            "engineering_read": (
                "Owned BL block/core topology variant. It is not a CFD result unless "
                "quality and zero-unmatched coupling gates pass."
            ),
        }
    except Exception as exc:  # pragma: no cover - real mesher failures are data.
        row = {
            "attempt_id": payload.get("attempt_id"),
            "status": "failed",
            "route": "r6_owned_bl_core_variant",
            "mesh_size": payload.get("mesh_size"),
            "mesh_algorithm3d": payload.get("mesh_algorithm3d"),
            "preserve_boundary_mesh": payload.get("preserve_boundary_mesh"),
            "failure_code": exc.__class__.__name__,
            "error": str(exc),
            "elapsed_seconds": time.time() - start,
            "ru_maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    queue.put(row)


def run_worker_with_timeout(
    *,
    target: Any,
    payload: Mapping[str, Any],
    case_dir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue: mp.Queue = context.Queue()
    process = context.Process(
        target=target,
        kwargs={"queue": queue, "payload": dict(payload), "case_dir": str(case_dir)},
    )
    start = time.time()
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(10.0)
        if process.is_alive():
            process.kill()
            process.join(5.0)
        return {
            "attempt_id": payload.get("attempt_id"),
            "status": "timeout",
            "failure_code": "local_timeout",
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": time.time() - start,
            "process_exitcode": process.exitcode,
            "case_dir": str(case_dir),
            "engineering_read": (
                "Local process exceeded the bounded runtime. Treat this as local "
                "scaling evidence, not as proof the physics is impossible."
            ),
        }
    if queue.empty():
        return {
            "attempt_id": payload.get("attempt_id"),
            "status": "terminated",
            "failure_code": "worker_no_payload",
            "elapsed_seconds": time.time() - start,
            "process_exitcode": process.exitcode,
            "case_dir": str(case_dir),
        }
    row = dict(queue.get())
    row["case_dir"] = str(case_dir)
    row["process_exitcode"] = process.exitcode
    return row


def authority_payload() -> dict[str, Any]:
    return {
        "design_gross_mass_kg": DESIGN_GROSS_MASS_KG,
        "full_span_m": PIPELINE_FULL_SPAN_M,
        "half_span_m": PIPELINE_HALF_SPAN_M,
        "sref_m2": SREF_M2,
        "cref_m": CREF_M,
        "bref_m": BREF_M,
        "velocity_mps": VELOCITY_MPS,
        "density_kgpm3": RHO_KGPM3,
        "dynamic_viscosity_pa_s": MU_PA_S,
        "required_cl": required_cl(),
        "blocked_legacy_mass_kg": "106.828608 kg is suspect screening only",
        "blocked_legacy_half_span_m": "16.5 m is local/splice screening only",
    }


def collect_machine_context() -> dict[str, Any]:
    def run(command: list[str]) -> str:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        return completed.stdout.strip()

    mem = run(["sysctl", "-n", "hw.memsize"])
    ncpu = run(["sysctl", "-n", "hw.ncpu"])
    logical = run(["sysctl", "-n", "hw.logicalcpu"])
    return {
        "hw_memsize_bytes": int(mem) if mem.isdigit() else mem,
        "hw_ncpu": int(ncpu) if ncpu.isdigit() else ncpu,
        "hw_logicalcpu": int(logical) if logical.isdigit() else logical,
        "uname": run(["uname", "-a"]),
        "cwd": str(REPO_ROOT),
    }


def collect_toolchain_context() -> dict[str, Any]:
    return {
        "SU2_CFD": shutil.which("SU2_CFD") or SU2_COMMAND,
        "SU2_DEF": shutil.which("SU2_DEF"),
        "gmsh": shutil.which("gmsh"),
        "vspscript": shutil.which("vspscript"),
        "python": sys.executable,
    }


def old_evidence_rows() -> list[dict[str, Any]]:
    return [
        {
            "evidence": "WO-006R3 current-GO no-BL high mesh",
            "path": str(WO006_ROOT / "wo006r3_surface_topology_repair/high_mesh_no_bl_wing_h_0p12_probe"),
            "volume_elements": 936017,
            "node_count": 176542,
            "boundary_layer": "none",
            "read": "marker/quality pass, solver timeout at iter 75; not drag evidence",
        },
        {
            "evidence": "Old mesh-native BL HXT best route",
            "path": "hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/mesh_native_hxt_thread_profile.v1.md",
            "volume_elements": 1125409,
            "node_count": 531054,
            "boundary_layer": "24 layers, first height 5e-5 m",
            "read": "best old BL route, not current coefficient truth",
        },
        {
            "evidence": "Old no-BL 1000-iter solver stability",
            "path": "hpa_meshing_package/docs/reports/mesh_native_blackcat_vsp_su2_iter1000/mesh_native_blackcat_vsp_su2_iter1000.v1.md",
            "volume_elements": 717901,
            "node_count": 258378,
            "boundary_layer": "none",
            "read": "positive drag stability reference only; CD too high/no BL",
        },
        {
            "evidence": "WO-006F best final sign-correct no-BL RANS",
            "path": str(WO006_ROOT / "wo006f_su2_engineering_result/attempt_06_medium_no_bl_inc_rans_sa_alpha5_zpos_no_wallfn"),
            "volume_elements": 434928,
            "node_count": None,
            "boundary_layer": "none",
            "read": "CL=1.289, CD=0.556 rejected as non-HPA and not converged",
        },
        {
            "evidence": "WO-006R6 owned BL/core repair",
            "path": str(WO006_ROOT / "wo006r6_core_interface_repair"),
            "volume_elements": "24576 BL cells plus 11644 core probe elements",
            "node_count": None,
            "boundary_layer": "owned BL block exists",
            "read": "fails final handoff: unmatched faces and non-positive core elements",
        },
    ]


def official_sources() -> list[dict[str, str]]:
    return [
        {
            "topic": "SU2 wall BC and marker semantics",
            "url": "https://su2code.github.io/docs_v7/Markers-and-BC/",
        },
        {
            "topic": "SU2 turbulence and wall functions",
            "url": "https://su2code.github.io/docs_v7/Theory/",
        },
        {
            "topic": "Gmsh discrete entities, HXT, physical groups, BL extrusion",
            "url": "https://gmsh.info/doc/texinfo/",
        },
        {
            "topic": "OpenVSP CFD mesh API/export knobs",
            "url": "https://openvsp.org/pyapi_docs/latest/openvsp.html",
        },
        {
            "topic": "NASA CFD best-practice/V&V guidance",
            "url": "https://ntrs.nasa.gov/api/citations/20040085757/downloads/20040085757.pdf",
        },
        {
            "topic": "NASA turbulent-flow grid convergence guidance",
            "url": "https://ntrs.nasa.gov/api/citations/20150005716/downloads/20150005716.pdf",
        },
    ]


def completion_interpretation(verdict: str) -> str:
    if verdict == "wo006h_serious_no_bl_scaling_only_not_cfd_result":
        return (
            "Not a CFD result. Local no-BL scaling succeeded, but BL/y+/convergence "
            "and grid-study gates still block aerodynamic use."
        )
    return "Not complete as CFD evidence; continue scaling or repair BL/core topology."


def engineering_read(
    verdict: str,
    no_bl_attempts: Sequence[Mapping[str, Any]],
    core_attempts: Sequence[Mapping[str, Any]],
) -> str:
    max_no_bl = max((int(item.get("volume_element_count") or 0) for item in no_bl_attempts), default=0)
    return (
        f"Largest local no-BL cell count observed: {max_no_bl}. This is route evidence "
        "only until a conformal BL-resolved mesh, y+, convergence, force stability, "
        "and mesh sensitivity are available."
    )


def write_hpc_package(package_dir: Path) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "case_matrix.csv").write_text(
        "\n".join(
            [
                "case_id,route,wing_h_m,gmsh_algorithm3d,expected_cells_order,solver,iterations,acceptance_gate",
                "mesh_h0055_hxt,no_bl_control,0.055,10,3.5e6-5e6,INC_NAVIER_STOKES,1000,resource_scaling_only_not_drag_truth",
                "mesh_h005_hxt,no_bl_failed_finer,0.05,10,topology_threshold_probe,INC_NAVIER_STOKES,1000,diagnose_hxt_plc_failure",
                "mesh_h004_hxt,no_bl_failed_finer,0.04,10,topology_threshold_probe,INC_NAVIER_STOKES,1000,diagnose_hxt_plc_failure",
                "mesh_h004_delaunay,no_bl_failed_finer,0.04,1,topology_threshold_probe,INC_NAVIER_STOKES,1000,diagnose_delaunay_boundary_overlap",
                "bl_core_preserve_alg1_32x2,owned_bl_core_preserved_interface,na,1,serious_current_go_bl_core_probe,INC_RANS_SA,2000,requires_quality_interface_yplus",
                "bl_core_preserve_alg10_32x2,owned_bl_core_preserved_interface,na,10,serious_current_go_bl_core_probe,INC_RANS_SA,2000,requires_quality_interface_yplus",
                "bl_core_remesh_alg10_32x2,owned_bl_core_rejected_control,na,10,interface_remesh_control,INC_RANS_SA,2000,reject_if_unmatched_faces_remain",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (package_dir / "run_hpc_campaign.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/Volumes/Samsung SSD/hpa-mdo}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_hpc_run}"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${SU2_BIN:-/Users/linyuan/.local/opt/su2/current/bin}:$PATH"
export PYTHONPATH="$REPO_ROOT/src:$REPO_ROOT/hpa_meshing_package/src:${PYTHONPATH:-}"

cd "$REPO_ROOT"
"$PYTHON" scripts/check_baseline_a_data_authority.py --check-only

run_case() {
  local case_name="$1"
  shift
  "$PYTHON" scripts/run_wo006h_cfd_limit_scaling.py \\
    --output-dir "$OUT_DIR/$case_name" \\
    "$@" \\
    --mesh-timeout-seconds "${MESH_TIMEOUT_SECONDS:-7200}" \\
    --core-timeout-seconds "${CORE_TIMEOUT_SECONDS:-7200}" \\
    --clean
}

run_case mesh_h0055_hxt --mesh-sizes 0.055 --skip-core-variants
run_case mesh_h005_hxt --mesh-sizes 0.05 --skip-core-variants
run_case mesh_h004_hxt --mesh-sizes 0.04 --skip-core-variants
run_case mesh_h004_delaunay --mesh-sizes 0.04 --no-bl-mesh-algorithm3d 1 --skip-core-variants
run_case bl_core_variants_32x2 --skip-no-bl-ladder

"$PYTHON" scripts/run_wo006h_reopened_cfd_campaign.py \\
  --input-dir "$OUT_DIR" \\
  --output-dir "$OUT_DIR/final_report" \\
  --hpc-package-dir "$PACKAGE_DIR"
""",
        encoding="utf-8",
    )
    os.chmod(package_dir / "run_hpc_campaign.sh", 0o755)
    (package_dir / "slurm_wo006h_mesh_ladder.sbatch").write_text(
        """#!/usr/bin/env bash
#SBATCH --job-name=wo006h-cfd
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH --output=wo006h-%j.log

set -euo pipefail
module purge || true
module load python || true
module load gmsh || true
module load su2 || true

export REPO_ROOT="${REPO_ROOT:-$PWD}"
export OUT_DIR="${OUT_DIR:-$REPO_ROOT/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_hpc_run}"
export MESH_TIMEOUT_SECONDS="${MESH_TIMEOUT_SECONDS:-7200}"
export CORE_TIMEOUT_SECONDS="${CORE_TIMEOUT_SECONDS:-7200}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/run_hpc_campaign.sh"
""",
        encoding="utf-8",
    )
    os.chmod(package_dir / "slurm_wo006h_mesh_ladder.sbatch", 0o755)
    (package_dir / "README.md").write_text(
        """# WO-006H Reopened CFD HPC Package

This package is for current Baseline A main-wing CFD route escalation after
the reopened WO-006H local campaign. It targets the missing serious cases,
not just already-successful smaller no-BL controls:

- finer no-BL topology probes at `h=0.05` and `h=0.04`;
- an alternate Gmsh 3D Delaunay probe at `h=0.04`;
- preserved-interface BL/core probes with Gmsh algorithms 1 and 10;
- an interface-remesh control that must remain rejected if unmatched faces
  remain.

It does not change external geometry or authority values.

Run from a machine with this repo, Gmsh, SU2, and Python dependencies:

```bash
export REPO_ROOT=/path/to/hpa-mdo
bash /path/to/this/package/run_hpc_campaign.sh
```

For Slurm:

```bash
cd "$REPO_ROOT"
sbatch /path/to/this/package/slurm_wo006h_mesh_ladder.sbatch
```

Acceptance is not "SU2 ran." A result is usable only after authority, marker,
BL/y+, mesh quality, force stability, convergence, and mesh-sensitivity gates
pass. No-BL mesh rungs are resource/sign/marker controls, not HPA drag truth.
""",
        encoding="utf-8",
    )


def write_report(path: Path, summary: Mapping[str, Any]) -> None:
    no_bl_rows = list(summary["no_bl_attempts"])
    core_rows = list(summary["core_variant_attempts"])
    lines = [
        "# WO-006H CFD Limit Scaling Campaign",
        "",
        f"Verdict: `{summary['verdict']}`",
        "",
        "## Authority",
        "",
        f"- design mass: `{DESIGN_GROSS_MASS_KG} kg`",
        f"- span: `{PIPELINE_FULL_SPAN_M} m` full / `{PIPELINE_HALF_SPAN_M} m` half",
        f"- Sref/Cref/Bref: `{SREF_M2} m^2`, `{CREF_M} m`, `{BREF_M} m`",
        f"- required CL at 6.5 m/s: `{required_cl():.3f}`",
        "",
        "## Local No-BL Scaling",
        "",
        *markdown_table(
            no_bl_rows,
            [
                "attempt_id",
                "status",
                "mesh_size",
                "volume_element_count",
                "node_count",
                "mesh_quality_status",
                "marker_audit_status",
                "failure_code",
                "elapsed_seconds",
            ],
        ),
        "",
        "## BL/Core Variants",
        "",
        *markdown_table(
            core_rows,
            [
                "attempt_id",
                "status",
                "mesh_algorithm3d",
                "preserve_boundary_mesh",
                "volume_element_count",
                "mesh_quality_status",
                "unmatched_core_interface_face_count",
                "unmatched_bl_boundary_face_count",
                "elapsed_seconds",
            ],
        ),
        "",
        "## Engineering Read",
        "",
        str(summary["engineering_read"]),
        "",
        "The HPC package is in `hpc_escalation_package/`. Lower-order AVL/XFOIL/VSPAERO remain sanity checks only.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_reviewer_prompt(path: Path, summary: Mapping[str, Any]) -> None:
    path.write_text(
        f"""Review WO-006H in /Volumes/Samsung SSD/hpa-mdo.

Read:
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_cfd_limit_scaling/wo006h_cfd_limit_scaling_summary.json
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_cfd_limit_scaling/wo006h_cfd_limit_scaling_report.md
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_cfd_limit_scaling/hpc_escalation_package/

Verdict to audit: {summary['verdict']}

Check whether the local scaling attempts are serious enough to support the
larger-compute escalation package, and reject any wording that promotes no-BL
tetra drag or failed BL/core variants into Baseline A aerodynamic calibration.

Authority must remain: 98.5 kg, full span 34.332286 m, half span 17.166143 m,
Sref 33.420059598 m^2, Cref 1.003721543 m.
""",
        encoding="utf-8",
    )


def markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, float):
                values.append(f"{value:.4g}")
            elif value is None:
                values.append("")
            else:
                values.append(str(value).replace("\n", " "))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    if not fieldnames:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (list, dict))
                    else value
                    for key, value in row.items()
                }
            )


def slug(value: float) -> str:
    return f"{value:.4g}".replace(".", "p").replace("-", "m")


if __name__ == "__main__":
    raise SystemExit(main())
