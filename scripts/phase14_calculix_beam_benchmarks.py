#!/usr/bin/env python3
"""Mac-local CalculiX linear beam parity runner for Phase 14 benchmarks."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import numpy as np

from hpa_mdo.core import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.hifi.calculix_runner import find_ccx, run_static
from hpa_mdo.hifi.frd_parser import parse_displacement, parse_total_force_from_dat
from hpa_mdo.hifi.gmsh_runner import find_gmsh
from hpa_mdo.structure.calculix_beam_export import (
    BeamMaterial,
    DualPipeBenchmarkSpec,
    SinglePipeCantileverSpec,
    build_dual_pipe_benchmark_spec,
    build_single_pipe_cantilever_spec,
    cantilever_tip_deflection_point_load,
    cantilever_tip_deflection_uniform_load,
    write_calculix_beam_inp,
)
from hpa_mdo.structure.fem.elements import (
    _cs_norm,
    _rotation_matrix,
    _timoshenko_element_stiffness,
    _transform_12x12,
)
from hpa_mdo.structure.spar_model import tube_Ixx, tube_J, tube_area


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "output" / "phase14_dual_beam_calibration" / "benchmark_manifest.csv"
_BC_PENALTY = 1.0e18
_LINK_PENALTY = 1.0e17


@dataclass(frozen=True)
class SolverPaths:
    ccx_path: str | None
    gmsh_path: str | None


@dataclass(frozen=True)
class BenchmarkCase:
    benchmark_id: str
    variant_id: str
    display_name: str
    spec: SinglePipeCantileverSpec | DualPipeBenchmarkSpec
    closed_form_tip_deflection_m: float | None
    internal_metrics: dict[str, float]
    manifest_note: str
    status_hint: str
    note: str = ""


@dataclass(frozen=True)
class BenchmarkCaseResult:
    benchmark_id: str
    variant_id: str
    display_name: str
    status: str
    deck_path: Path
    frd_path: Path | None
    dat_path: Path | None
    closed_form_tip_deflection_m: float | None
    internal_tip_main_m: float | None
    fem_tip_main_m: float | None
    closed_form_error_pct: float | None
    internal_vs_fem_tip_main_pct: float | None
    internal_tip_rear_m: float | None
    fem_tip_rear_m: float | None
    internal_vs_fem_tip_rear_pct: float | None
    internal_reaction_total_fz_n: float | None
    fem_reaction_total_fz_n: float | None
    reaction_error_pct: float | None
    note: str


@dataclass(frozen=True)
class Round2BenchmarkRun:
    solver_paths: SolverPaths
    manifest_path: Path
    benchmark_output_dir: Path
    comparison_csv_path: Path
    summary_md_path: Path
    case_results: tuple[BenchmarkCaseResult, ...]


@dataclass(frozen=True)
class B2DiagnosisRow:
    case_id: str
    variant: str
    n_elem: int
    element_type: str
    section_sampling_mode: str
    internal_tip_uz_m: float
    calculix_tip_uz_m: float
    reference_tip_uz_m: float
    internal_vs_calculix_error_pct: float
    reference_vs_calculix_error_pct: float
    root_reaction_fz_n: float | None
    reaction_residual_n: float | None
    engineering_note: str


def discover_solver_paths(config_path: str | Path) -> SolverPaths:
    """Discover local solver paths through config + local_paths overlay."""

    cfg = load_config(config_path)
    return SolverPaths(
        ccx_path=find_ccx(cfg),
        gmsh_path=find_gmsh(cfg),
    )


def run_phase14_calculix_beam_benchmarks(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> Round2BenchmarkRun:
    """Generate B1-B5 beam decks, run CalculiX when available, and write reports."""

    config_path = Path(config_path).resolve()
    benchmark_dir = Path(output_dir).resolve()
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    phase14_dir = _phase14_artifact_dir(benchmark_dir)
    phase14_dir.mkdir(parents=True, exist_ok=True)

    manifest = Path(manifest_path).resolve()
    manifest_rows = _load_manifest_rows(manifest)
    cfg = load_config(config_path)
    solver_paths = SolverPaths(
        ccx_path=find_ccx(cfg),
        gmsh_path=find_gmsh(cfg),
    )
    cases = _build_benchmark_cases(cfg=cfg, manifest_rows=manifest_rows)

    case_results: list[BenchmarkCaseResult] = []
    for case in cases:
        deck_name = f"{case.benchmark_id}_{case.variant_id}".lower()
        deck = write_calculix_beam_inp(case.spec, benchmark_dir / f"{deck_name}.inp")
        if solver_paths.ccx_path is None:
            case_results.append(
                BenchmarkCaseResult(
                    benchmark_id=case.benchmark_id,
                    variant_id=case.variant_id,
                    display_name=case.display_name,
                    status="SKIP",
                    deck_path=deck.inp_path,
                    frd_path=None,
                    dat_path=None,
                    closed_form_tip_deflection_m=case.closed_form_tip_deflection_m,
                    internal_tip_main_m=case.internal_metrics.get("tip_main_m"),
                    fem_tip_main_m=None,
                    closed_form_error_pct=None,
                    internal_vs_fem_tip_main_pct=None,
                    internal_tip_rear_m=case.internal_metrics.get("tip_rear_m"),
                    fem_tip_rear_m=None,
                    internal_vs_fem_tip_rear_pct=None,
                    internal_reaction_total_fz_n=case.internal_metrics.get("reaction_total_fz_n"),
                    fem_reaction_total_fz_n=None,
                    reaction_error_pct=None,
                    note="CalculiX not available through load_config/find_ccx; deck generated only.",
                )
            )
            continue

        run_payload = run_static(deck.inp_path, cfg)
        if run_payload.get("error"):
            case_results.append(
                BenchmarkCaseResult(
                    benchmark_id=case.benchmark_id,
                    variant_id=case.variant_id,
                    display_name=case.display_name,
                    status="WARN",
                    deck_path=deck.inp_path,
                    frd_path=Path(run_payload["frd"]).resolve() if run_payload.get("frd") else None,
                    dat_path=Path(run_payload["dat"]).resolve() if run_payload.get("dat") else None,
                    closed_form_tip_deflection_m=case.closed_form_tip_deflection_m,
                    internal_tip_main_m=case.internal_metrics.get("tip_main_m"),
                    fem_tip_main_m=None,
                    closed_form_error_pct=None,
                    internal_vs_fem_tip_main_pct=None,
                    internal_tip_rear_m=case.internal_metrics.get("tip_rear_m"),
                    fem_tip_rear_m=None,
                    internal_vs_fem_tip_rear_pct=None,
                    internal_reaction_total_fz_n=case.internal_metrics.get("reaction_total_fz_n"),
                    fem_reaction_total_fz_n=None,
                    reaction_error_pct=None,
                    note=f"CalculiX run failed: {run_payload['error']}",
                )
            )
            continue

        frd_path = Path(run_payload["frd"]).resolve()
        dat_path = Path(run_payload["dat"]).resolve()
        case_results.append(
            _build_case_result(
                case=case,
                deck_path=deck.inp_path,
                node_sets=deck.node_sets,
                frd_path=frd_path,
                dat_path=dat_path,
            )
        )

    comparison_csv_path = phase14_dir / "internal_vs_fem_comparison.csv"
    summary_md_path = phase14_dir / "comparison_summary.md"
    _write_comparison_csv(comparison_csv_path, case_results)
    _write_summary_md(
        summary_md_path,
        solver_paths=solver_paths,
        manifest_path=manifest,
        case_results=case_results,
    )
    if solver_paths.ccx_path is not None:
        _write_b2_taper_diagnosis(
            phase14_dir=phase14_dir,
            benchmark_dir=benchmark_dir,
            cfg=cfg,
            cases=cases,
        )
    return Round2BenchmarkRun(
        solver_paths=solver_paths,
        manifest_path=manifest,
        benchmark_output_dir=benchmark_dir,
        comparison_csv_path=comparison_csv_path,
        summary_md_path=summary_md_path,
        case_results=tuple(case_results),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Config YAML used for local-path solver discovery.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for generated benchmark decks (normally output/.../round2_benchmarks).",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Phase 14 benchmark manifest CSV.",
    )
    return parser


def _load_manifest_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = {row["benchmark_id"]: row for row in csv.DictReader(handle)}
    missing = {"B1", "B2", "B3", "B4", "B5"} - set(rows)
    if missing:
        raise ValueError(f"Manifest is missing required Phase 14 benchmarks: {sorted(missing)}")
    return rows


def _material_from_cfg(cfg, material_key: str) -> BeamMaterial:
    materials_db = MaterialDB()
    material = materials_db.get(material_key)
    return BeamMaterial(
        name=material_key.upper(),
        young_pa=float(material.E),
        poisson_ratio=float(material.poisson_ratio),
        density_kgpm3=float(material.density),
    )


def _build_benchmark_cases(
    *,
    cfg,
    manifest_rows: dict[str, dict[str, str]],
) -> list[BenchmarkCase]:
    main_material = _material_from_cfg(cfg, cfg.main_spar.material)
    rear_material = _material_from_cfg(cfg, cfg.rear_spar.material)

    cases: list[BenchmarkCase] = []

    span_m = 10.0
    y_single = np.linspace(0.0, span_m, 21)
    tributary_single = _node_tributary_lengths(y_single)
    single_outer_radius_m = np.full(y_single.size - 1, 0.03)
    single_thickness_m = np.full(y_single.size - 1, 0.0015)
    point_load_n = 60.0
    uniform_load_npm = 8.0
    tip_nodal_fz_n = np.zeros(y_single.size)
    tip_nodal_fz_n[-1] = -point_load_n
    uniform_nodal_fz_n = -uniform_load_npm * tributary_single

    b1_tip_spec = build_single_pipe_cantilever_spec(
        name="b1_tip_load",
        y_nodes_m=y_single,
        outer_radius_m=single_outer_radius_m,
        thickness_m=single_thickness_m,
        material=main_material,
        nodal_fz_n=tip_nodal_fz_n,
    )
    b1_uniform_spec = build_single_pipe_cantilever_spec(
        name="b1_uniform_load",
        y_nodes_m=y_single,
        outer_radius_m=single_outer_radius_m,
        thickness_m=single_thickness_m,
        material=main_material,
        nodal_fz_n=uniform_nodal_fz_n,
    )

    second_moment_b1 = float(tube_Ixx(single_outer_radius_m[:1], single_thickness_m[:1])[0])
    b1_tip_closed_form_m = cantilever_tip_deflection_point_load(
        point_load_n=point_load_n,
        span_m=span_m,
        young_pa=main_material.young_pa,
        second_moment_m4=second_moment_b1,
    )
    b1_uniform_closed_form_m = cantilever_tip_deflection_uniform_load(
        uniform_load_npm=uniform_load_npm,
        span_m=span_m,
        young_pa=main_material.young_pa,
        second_moment_m4=second_moment_b1,
    )
    b1_tip_internal = _solve_single_beam_internal(b1_tip_spec)
    b1_uniform_internal = _solve_single_beam_internal(b1_uniform_spec)

    cases.append(
        BenchmarkCase(
            benchmark_id="B1",
            variant_id="tip_load",
            display_name="B1 simple cantilever tip load",
            spec=b1_tip_spec,
            closed_form_tip_deflection_m=b1_tip_closed_form_m,
            internal_metrics=b1_tip_internal,
            manifest_note=manifest_rows["B1"].get("notes", ""),
            status_hint=manifest_rows["B1"].get("readiness_status", ""),
        )
    )
    cases.append(
        BenchmarkCase(
            benchmark_id="B1",
            variant_id="uniform_load",
            display_name="B1 simple cantilever uniform load",
            spec=b1_uniform_spec,
            closed_form_tip_deflection_m=b1_uniform_closed_form_m,
            internal_metrics=b1_uniform_internal,
            manifest_note=manifest_rows["B1"].get("notes", ""),
            status_hint=manifest_rows["B1"].get("readiness_status", ""),
        )
    )

    b2_outer_radius_m = np.linspace(0.04, 0.025, y_single.size - 1)
    b2_thickness_m = np.linspace(0.0018, 0.0012, y_single.size - 1)
    b2_uniform_spec = build_single_pipe_cantilever_spec(
        name="b2_tapered_uniform_load",
        y_nodes_m=y_single,
        outer_radius_m=b2_outer_radius_m,
        thickness_m=b2_thickness_m,
        material=main_material,
        nodal_fz_n=uniform_nodal_fz_n,
    )
    cases.append(
        BenchmarkCase(
            benchmark_id="B2",
            variant_id="uniform_load",
            display_name="B2 tapered cantilever uniform load",
            spec=b2_uniform_spec,
            closed_form_tip_deflection_m=None,
            internal_metrics=_solve_single_beam_internal(b2_uniform_spec),
            manifest_note=manifest_rows["B2"].get("notes", ""),
            status_hint=manifest_rows["B2"].get("readiness_status", ""),
        )
    )

    y_dual = np.linspace(0.0, span_m, 13)
    tributary_dual = _node_tributary_lengths(y_dual)
    main_outer_radius_m = np.full(y_dual.size - 1, 0.035)
    main_thickness_m = np.full(y_dual.size - 1, 0.0018)
    rear_outer_radius_m = np.full(y_dual.size - 1, 0.028)
    rear_thickness_m = np.full(y_dual.size - 1, 0.0014)
    main_x_m = np.zeros(y_dual.size)
    rear_x_m = np.full(y_dual.size, 0.35)
    main_z_m = np.zeros(y_dual.size)
    rear_z_m = np.zeros(y_dual.size)
    joint_node_indices = (2, 4, 6, 8, 10)
    wire_node_indices = (8,)

    lift_nodal_fz_n = -12.0 * tributary_dual
    zero_nodal = np.zeros(y_dual.size)

    b3_spec = build_dual_pipe_benchmark_spec(
        name="b3_dual_no_wire",
        y_nodes_m=y_dual,
        main_x_m=main_x_m,
        rear_x_m=rear_x_m,
        main_z_m=main_z_m,
        rear_z_m=rear_z_m,
        main_outer_radius_m=main_outer_radius_m,
        main_thickness_m=main_thickness_m,
        rear_outer_radius_m=rear_outer_radius_m,
        rear_thickness_m=rear_thickness_m,
        material_main=main_material,
        material_rear=rear_material,
        main_nodal_fz_n=lift_nodal_fz_n,
        rear_nodal_fz_n=zero_nodal,
        joint_node_indices=joint_node_indices,
    )
    cases.append(
        BenchmarkCase(
            benchmark_id="B3",
            variant_id="lift_only",
            display_name="B3 dual beam without wire",
            spec=b3_spec,
            closed_form_tip_deflection_m=None,
            internal_metrics=_solve_dual_beam_internal(b3_spec),
            manifest_note=manifest_rows["B3"].get("notes", ""),
            status_hint=manifest_rows["B3"].get("readiness_status", ""),
        )
    )

    b4_spec = build_dual_pipe_benchmark_spec(
        name="b4_dual_vertical_wire",
        y_nodes_m=y_dual,
        main_x_m=main_x_m,
        rear_x_m=rear_x_m,
        main_z_m=main_z_m,
        rear_z_m=rear_z_m,
        main_outer_radius_m=main_outer_radius_m,
        main_thickness_m=main_thickness_m,
        rear_outer_radius_m=rear_outer_radius_m,
        rear_thickness_m=rear_thickness_m,
        material_main=main_material,
        material_rear=rear_material,
        main_nodal_fz_n=lift_nodal_fz_n,
        rear_nodal_fz_n=zero_nodal,
        joint_node_indices=joint_node_indices,
        wire_node_indices=wire_node_indices,
    )
    cases.append(
        BenchmarkCase(
            benchmark_id="B4",
            variant_id="vertical_wire",
            display_name="B4 dual beam with APDL-style vertical wire support",
            spec=b4_spec,
            closed_form_tip_deflection_m=None,
            internal_metrics=_solve_dual_beam_internal(b4_spec),
            manifest_note=manifest_rows["B4"].get("notes", ""),
            status_hint=manifest_rows["B4"].get("readiness_status", ""),
        )
    )

    torque_per_span_nmpm = np.full(y_dual.size, 4.0)
    torque_nodal_my_nm = torque_per_span_nmpm * tributary_dual
    couple_force_n = torque_nodal_my_nm / np.maximum(rear_x_m - main_x_m, 1.0e-12)

    b5_main_my_spec = build_dual_pipe_benchmark_spec(
        name="b5_main_beam_my_about_main_spar",
        y_nodes_m=y_dual,
        main_x_m=main_x_m,
        rear_x_m=rear_x_m,
        main_z_m=main_z_m,
        rear_z_m=rear_z_m,
        main_outer_radius_m=main_outer_radius_m,
        main_thickness_m=main_thickness_m,
        rear_outer_radius_m=rear_outer_radius_m,
        rear_thickness_m=rear_thickness_m,
        material_main=main_material,
        material_rear=rear_material,
        main_nodal_fz_n=lift_nodal_fz_n,
        rear_nodal_fz_n=zero_nodal,
        main_nodal_my_nm=torque_nodal_my_nm,
        joint_node_indices=joint_node_indices,
        wire_node_indices=wire_node_indices,
    )
    b5_couple_spec = build_dual_pipe_benchmark_spec(
        name="b5_front_rear_vertical_couple",
        y_nodes_m=y_dual,
        main_x_m=main_x_m,
        rear_x_m=rear_x_m,
        main_z_m=main_z_m,
        rear_z_m=rear_z_m,
        main_outer_radius_m=main_outer_radius_m,
        main_thickness_m=main_thickness_m,
        rear_outer_radius_m=rear_outer_radius_m,
        rear_thickness_m=rear_thickness_m,
        material_main=main_material,
        material_rear=rear_material,
        main_nodal_fz_n=lift_nodal_fz_n + couple_force_n,
        rear_nodal_fz_n=-couple_force_n,
        joint_node_indices=joint_node_indices,
        wire_node_indices=wire_node_indices,
    )
    b5_off_spec = build_dual_pipe_benchmark_spec(
        name="b5_cm_off_control",
        y_nodes_m=y_dual,
        main_x_m=main_x_m,
        rear_x_m=rear_x_m,
        main_z_m=main_z_m,
        rear_z_m=rear_z_m,
        main_outer_radius_m=main_outer_radius_m,
        main_thickness_m=main_thickness_m,
        rear_outer_radius_m=rear_outer_radius_m,
        rear_thickness_m=rear_thickness_m,
        material_main=main_material,
        material_rear=rear_material,
        main_nodal_fz_n=lift_nodal_fz_n,
        rear_nodal_fz_n=zero_nodal,
        joint_node_indices=joint_node_indices,
        wire_node_indices=wire_node_indices,
    )
    for variant_id, display_name, spec in (
        ("main_beam_my_about_main_spar", "B5 torque via main-beam MY", b5_main_my_spec),
        ("front_rear_vertical_couple", "B5 torque via front/rear vertical couple", b5_couple_spec),
        ("cm_off_control", "B5 Cm-off control", b5_off_spec),
    ):
        cases.append(
            BenchmarkCase(
                benchmark_id="B5",
                variant_id=variant_id,
                display_name=display_name,
                spec=spec,
                closed_form_tip_deflection_m=None,
                internal_metrics=_solve_dual_beam_internal(spec),
                manifest_note=manifest_rows["B5"].get("notes", ""),
                status_hint=manifest_rows["B5"].get("readiness_status", ""),
                note=(
                    "Report-only torque ownership variant. Do not treat as a single final validation truth."
                ),
            )
        )

    return cases


def _solve_single_beam_internal(spec: SinglePipeCantileverSpec) -> dict[str, float]:
    nodes = np.column_stack((np.zeros(spec.y_nodes_m.size), spec.y_nodes_m, np.zeros(spec.y_nodes_m.size)))
    area = tube_area(spec.outer_radius_m, spec.thickness_m)
    second_moment = tube_Ixx(spec.outer_radius_m, spec.thickness_m)
    polar = tube_J(spec.outer_radius_m, spec.thickness_m)
    loads = np.zeros((spec.y_nodes_m.size, 6), dtype=float)
    loads[:, 2] = spec.nodal_fz_n
    loads[:, 4] = spec.nodal_my_nm
    disp = _solve_beam_chain(
        nodes=nodes,
        area=area,
        iy=second_moment,
        iz=second_moment,
        polar=polar,
        young_pa=spec.material.young_pa,
        shear_pa=spec.material.young_pa / (2.0 * (1.0 + spec.material.poisson_ratio)),
        loads=loads,
        constrained_dofs=tuple([0, 1, 2, 3, 4, 5] + [idx * 6 + 2 for idx in spec.wire_node_indices]),
    )
    return {
        "tip_main_m": float(disp[-1, 2]),
        "reaction_total_fz_n": float(abs(np.sum(spec.nodal_fz_n))),
    }


def _solve_dual_beam_internal(spec: DualPipeBenchmarkSpec) -> dict[str, float]:
    nn = spec.y_nodes_m.size
    nodes_main = np.column_stack((spec.main_x_m, spec.y_nodes_m, spec.main_z_m))
    nodes_rear = np.column_stack((spec.rear_x_m, spec.y_nodes_m, spec.rear_z_m))
    area_main = tube_area(spec.main_outer_radius_m, spec.main_thickness_m)
    area_rear = tube_area(spec.rear_outer_radius_m, spec.rear_thickness_m)
    second_main = tube_Ixx(spec.main_outer_radius_m, spec.main_thickness_m)
    second_rear = tube_Ixx(spec.rear_outer_radius_m, spec.rear_thickness_m)
    polar_main = tube_J(spec.main_outer_radius_m, spec.main_thickness_m)
    polar_rear = tube_J(spec.rear_outer_radius_m, spec.rear_thickness_m)

    ndof = 2 * nn * 6
    stiffness = np.zeros((ndof, ndof), dtype=float)
    _assemble_chain_beam(
        stiffness,
        nodes=nodes_main,
        start_node=0,
        area=area_main,
        iy=second_main,
        iz=second_main,
        polar=polar_main,
        young_pa=spec.material_main.young_pa,
        shear_pa=spec.material_main.young_pa / (2.0 * (1.0 + spec.material_main.poisson_ratio)),
    )
    _assemble_chain_beam(
        stiffness,
        nodes=nodes_rear,
        start_node=nn,
        area=area_rear,
        iy=second_rear,
        iz=second_rear,
        polar=polar_rear,
        young_pa=spec.material_rear.young_pa,
        shear_pa=spec.material_rear.young_pa / (2.0 * (1.0 + spec.material_rear.poisson_ratio)),
    )

    rhs = np.zeros(ndof, dtype=float)
    for idx in range(nn):
        rhs[idx * 6 + 2] += spec.main_nodal_fz_n[idx]
        rhs[idx * 6 + 4] += spec.main_nodal_my_nm[idx]
        rhs[(nn + idx) * 6 + 2] += spec.rear_nodal_fz_n[idx]
        rhs[(nn + idx) * 6 + 4] += spec.rear_nodal_my_nm[idx]

    for node_index in spec.joint_node_indices:
        main_base = int(node_index) * 6
        rear_base = (nn + int(node_index)) * 6
        for dof in range(6):
            _apply_equal_dof_penalty(
                stiffness,
                main_base + dof,
                rear_base + dof,
                penalty=_LINK_PENALTY,
            )

    constrained_dofs = list(range(0, 6))
    constrained_dofs.extend(range(nn * 6, nn * 6 + 6))
    constrained_dofs.extend(int(idx) * 6 + 2 for idx in spec.wire_node_indices)
    for dof in constrained_dofs:
        stiffness[dof, dof] += _BC_PENALTY
        rhs[dof] = 0.0

    state = np.linalg.solve(stiffness, rhs)
    disp_main = state[: nn * 6].reshape((nn, 6))
    disp_rear = state[nn * 6 :].reshape((nn, 6))
    return {
        "tip_main_m": float(disp_main[-1, 2]),
        "tip_rear_m": float(disp_rear[-1, 2]),
        "reaction_total_fz_n": float(abs(np.sum(spec.main_nodal_fz_n) + np.sum(spec.rear_nodal_fz_n))),
    }


def _assemble_chain_beam(
    stiffness_matrix: np.ndarray,
    *,
    nodes: np.ndarray,
    start_node: int,
    area: np.ndarray,
    iy: np.ndarray,
    iz: np.ndarray,
    polar: np.ndarray,
    young_pa: float,
    shear_pa: float,
) -> None:
    for elem_index in range(nodes.shape[0] - 1):
        ni = nodes[elem_index]
        nj = nodes[elem_index + 1]
        dx = nj - ni
        length = _cs_norm(dx)
        local_stiffness = _timoshenko_element_stiffness(
            length,
            float(young_pa),
            float(shear_pa),
            float(area[elem_index]),
            float(iy[elem_index]),
            float(iz[elem_index]),
            float(polar[elem_index]),
        )
        rotation = _rotation_matrix(ni, nj)
        transform = _transform_12x12(rotation)
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            element_stiffness = transform.T @ local_stiffness @ transform
        g1 = (start_node + elem_index) * 6
        g2 = (start_node + elem_index + 1) * 6
        dofs = np.concatenate([np.arange(g1, g1 + 6), np.arange(g2, g2 + 6)])
        for local_i in range(12):
            global_i = int(dofs[local_i])
            for local_j in range(12):
                global_j = int(dofs[local_j])
                stiffness_matrix[global_i, global_j] += element_stiffness[local_i, local_j]


def _solve_beam_chain(
    *,
    nodes: np.ndarray,
    area: np.ndarray,
    iy: np.ndarray,
    iz: np.ndarray,
    polar: np.ndarray,
    young_pa: float,
    shear_pa: float,
    loads: np.ndarray,
    constrained_dofs: tuple[int, ...],
) -> np.ndarray:
    nn = nodes.shape[0]
    stiffness = np.zeros((nn * 6, nn * 6), dtype=float)
    _assemble_chain_beam(
        stiffness,
        nodes=nodes,
        start_node=0,
        area=area,
        iy=iy,
        iz=iz,
        polar=polar,
        young_pa=young_pa,
        shear_pa=shear_pa,
    )
    rhs = np.asarray(loads, dtype=float).reshape(nn * 6)
    for dof in constrained_dofs:
        stiffness[dof, dof] += _BC_PENALTY
        rhs[dof] = 0.0
    state = np.linalg.solve(stiffness, rhs)
    return state.reshape((nn, 6))


def _apply_equal_dof_penalty(
    stiffness: np.ndarray,
    dof_a: int,
    dof_b: int,
    *,
    penalty: float,
) -> None:
    stiffness[dof_a, dof_a] += penalty
    stiffness[dof_b, dof_b] += penalty
    stiffness[dof_a, dof_b] -= penalty
    stiffness[dof_b, dof_a] -= penalty


def _build_case_result(
    *,
    case: BenchmarkCase,
    deck_path: Path,
    node_sets: dict[str, tuple[int, ...]],
    frd_path: Path,
    dat_path: Path,
) -> BenchmarkCaseResult:
    disp = parse_displacement(frd_path)
    tip_main_id = node_sets["TIP_MAIN"][0]
    fem_tip_main_m = _nodal_uz(disp, tip_main_id)
    fem_tip_rear_m = None
    if "TIP_REAR" in node_sets:
        fem_tip_rear_m = _nodal_uz(disp, node_sets["TIP_REAR"][0])

    applied_support_fz_n = _support_applied_fz(case.spec, node_sets)
    total_force = parse_total_force_from_dat(dat_path, "HPA_SUPPORT_ALL")
    fem_reaction_total_fz_n = None
    if total_force is not None:
        fem_reaction_total_fz_n = abs(float(total_force[2]) - applied_support_fz_n)

    closed_form_error_pct = None
    if case.closed_form_tip_deflection_m is not None:
        closed_form_error_pct = _pct_error(
            abs(fem_tip_main_m),
            abs(case.closed_form_tip_deflection_m),
        )
    internal_vs_fem_tip_main_pct = _pct_error(
        abs(fem_tip_main_m),
        abs(case.internal_metrics["tip_main_m"]),
    )
    internal_vs_fem_tip_rear_pct = None
    if fem_tip_rear_m is not None and "tip_rear_m" in case.internal_metrics:
        internal_vs_fem_tip_rear_pct = _pct_error(
            abs(fem_tip_rear_m),
            abs(case.internal_metrics["tip_rear_m"]),
        )
    reaction_error_pct = None
    if fem_reaction_total_fz_n is not None and "reaction_total_fz_n" in case.internal_metrics:
        reaction_error_pct = _pct_error(
            abs(fem_reaction_total_fz_n),
            abs(case.internal_metrics["reaction_total_fz_n"]),
        )

    status, note = _evaluate_case_status(
        case=case,
        closed_form_error_pct=closed_form_error_pct,
        internal_vs_fem_tip_main_pct=internal_vs_fem_tip_main_pct,
        internal_vs_fem_tip_rear_pct=internal_vs_fem_tip_rear_pct,
        reaction_error_pct=reaction_error_pct,
    )
    return BenchmarkCaseResult(
        benchmark_id=case.benchmark_id,
        variant_id=case.variant_id,
        display_name=case.display_name,
        status=status,
        deck_path=deck_path,
        frd_path=frd_path,
        dat_path=dat_path,
        closed_form_tip_deflection_m=case.closed_form_tip_deflection_m,
        internal_tip_main_m=case.internal_metrics.get("tip_main_m"),
        fem_tip_main_m=fem_tip_main_m,
        closed_form_error_pct=closed_form_error_pct,
        internal_vs_fem_tip_main_pct=internal_vs_fem_tip_main_pct,
        internal_tip_rear_m=case.internal_metrics.get("tip_rear_m"),
        fem_tip_rear_m=fem_tip_rear_m,
        internal_vs_fem_tip_rear_pct=internal_vs_fem_tip_rear_pct,
        internal_reaction_total_fz_n=case.internal_metrics.get("reaction_total_fz_n"),
        fem_reaction_total_fz_n=fem_reaction_total_fz_n,
        reaction_error_pct=reaction_error_pct,
        note=note,
    )


def _evaluate_case_status(
    *,
    case: BenchmarkCase,
    closed_form_error_pct: float | None,
    internal_vs_fem_tip_main_pct: float | None,
    internal_vs_fem_tip_rear_pct: float | None,
    reaction_error_pct: float | None,
) -> tuple[str, str]:
    note_parts = [case.manifest_note, case.note]
    if case.benchmark_id == "B1":
        if case.closed_form_tip_deflection_m is None:
            return "WARN", "B1 closed-form reference missing."
        if (
            closed_form_error_pct is not None
            and closed_form_error_pct <= 1.0
            and internal_vs_fem_tip_main_pct is not None
            and internal_vs_fem_tip_main_pct <= 2.0
            and (reaction_error_pct is None or reaction_error_pct <= 1.0)
        ):
            return "PASS", _join_notes(note_parts) or "B1 linear parity passed."
        return "WARN", _join_notes(note_parts) or "B1 did not meet linear parity targets."
    if case.benchmark_id == "B2":
        if internal_vs_fem_tip_main_pct is not None and internal_vs_fem_tip_main_pct <= 2.0:
            return "PASS", _join_notes(note_parts) or "B2 tapered linear parity passed."
        note_parts.append(
            "Current gap points to tapered EI / section interpolation mismatch between the internal beam reference and the CalculiX B32R pipe deck."
        )
        return "WARN", _join_notes(note_parts) or "B2 tapered parity exceeded target."
    if case.benchmark_id in {"B3", "B4"}:
        if (
            internal_vs_fem_tip_main_pct is not None
            and internal_vs_fem_tip_main_pct <= 5.0
            and internal_vs_fem_tip_rear_pct is not None
            and internal_vs_fem_tip_rear_pct <= 5.0
            and (reaction_error_pct is None or reaction_error_pct <= 1.0)
        ):
            return "PASS", _join_notes(note_parts) or f"{case.benchmark_id} dual-beam parity passed."
        if (
            case.benchmark_id == "B4"
            and internal_vs_fem_tip_main_pct is not None
            and internal_vs_fem_tip_main_pct <= 5.0
            and internal_vs_fem_tip_rear_pct is not None
            and internal_vs_fem_tip_rear_pct <= 5.0
            and reaction_error_pct is not None
        ):
            note_parts.append(
                "Displacement parity is inside the 5% target, but support reaction recovery is still off; treat the APDL-style vertical-wire surrogate as kinematically useful but not yet reaction-truth."
            )
        return "WARN", _join_notes(note_parts) or f"{case.benchmark_id} dual-beam parity exceeded target."
    if (
        internal_vs_fem_tip_main_pct is not None
        and internal_vs_fem_tip_main_pct <= 5.0
        and (
            internal_vs_fem_tip_rear_pct is None
            or internal_vs_fem_tip_rear_pct <= 5.0
        )
    ):
        note_parts.append(
            "Displacements are in the expected linear range, but torque ownership and/or support reaction bookkeeping is not frozen enough to call this validation truth."
        )
    return "WARN", _join_notes(note_parts) or "B5 is report-only until torque ownership is frozen."


def _join_notes(notes: list[str]) -> str:
    cleaned = [note.strip() for note in notes if note and note.strip()]
    return " ".join(cleaned)


def _nodal_uz(displacements: np.ndarray, node_id: int) -> float:
    matches = displacements[displacements[:, 0].astype(int) == int(node_id)]
    if matches.size == 0:
        raise ValueError(f"Node {node_id} not found in FRD displacement output.")
    return float(matches[0, 3])


def _support_applied_fz(
    spec: SinglePipeCantileverSpec | DualPipeBenchmarkSpec,
    node_sets: dict[str, tuple[int, ...]],
) -> float:
    support_nodes = set(node_sets.get("HPA_SUPPORT_ALL", ()))
    if isinstance(spec, SinglePipeCantileverSpec):
        total = 0.0
        for node_id in support_nodes:
            total += float(spec.nodal_fz_n[_single_beam_station_index(node_id)])
        return total
    nn = spec.y_nodes_m.size
    main_total_nodes = 2 * nn - 1
    total = 0.0
    for node_id in support_nodes:
        if node_id <= main_total_nodes:
            total += float(spec.main_nodal_fz_n[_single_beam_station_index(node_id)])
        else:
            total += float(spec.rear_nodal_fz_n[_rear_beam_station_index(node_id, nn)])
    return total


def _pct_error(actual: float, reference: float) -> float:
    return 100.0 * abs(float(actual) - float(reference)) / max(abs(float(reference)), 1.0e-12)


def _node_tributary_lengths(y_nodes_m: np.ndarray) -> np.ndarray:
    dy = np.diff(y_nodes_m)
    tributary = np.zeros(y_nodes_m.size, dtype=float)
    tributary[0] = 0.5 * dy[0]
    tributary[-1] = 0.5 * dy[-1]
    for idx in range(1, y_nodes_m.size - 1):
        tributary[idx] = 0.5 * (dy[idx - 1] + dy[idx])
    return tributary


def _phase14_artifact_dir(benchmark_dir: Path) -> Path:
    name = benchmark_dir.name.lower()
    if re.match(r"^round\d+_(baseline|benchmarks)$", name):
        return benchmark_dir.parent
    return benchmark_dir


def _piecewise_uniform_load_reference_tip_deflection(
    *,
    y_nodes_m: np.ndarray,
    outer_radius_m: np.ndarray,
    thickness_m: np.ndarray,
    young_pa: float,
    uniform_load_npm: float,
) -> float:
    y_nodes = _as_array(y_nodes_m)
    second_moment_m4 = tube_Ixx(_as_array(outer_radius_m), _as_array(thickness_m))
    if y_nodes.size != second_moment_m4.size + 1:
        raise ValueError("y_nodes_m must have exactly one more station than element property arrays.")

    tip_deflection_m = 0.0
    for elem_index, second_moment in enumerate(second_moment_m4):
        y0 = float(y_nodes[elem_index])
        y1 = float(y_nodes[elem_index + 1])
        ys = np.linspace(y0, y1, 2049)
        moment_nm = 0.5 * float(uniform_load_npm) * (float(y_nodes[-1]) - ys) ** 2
        integrand = moment_nm * (float(y_nodes[-1]) - ys) / (
            float(young_pa) * max(float(second_moment), 1.0e-30)
        )
        tip_deflection_m += float(np.trapezoid(integrand, ys))
    return tip_deflection_m


def _write_b2_taper_diagnosis(
    *,
    phase14_dir: Path,
    benchmark_dir: Path,
    cfg,
    cases: list[BenchmarkCase],
) -> None:
    b2_case = next(case for case in cases if case.benchmark_id == "B2")
    if not isinstance(b2_case.spec, SinglePipeCantileverSpec):
        raise TypeError("B2 diagnosis expects a single-beam cantilever spec.")

    rows = _build_b2_diagnosis_rows(
        benchmark_dir=benchmark_dir,
        cfg=cfg,
        b2_spec=b2_case.spec,
    )
    csv_path = phase14_dir / "b2_taper_diagnosis.csv"
    fieldnames = [
        "case_id",
        "variant",
        "n_elem",
        "element_type",
        "section_sampling_mode",
        "internal_tip_uz_m",
        "calculix_tip_uz_m",
        "closed_form_or_reference_tip_uz_m",
        "internal_vs_calculix_error_pct",
        "reference_vs_calculix_error_pct",
        "root_reaction_fz_n",
        "reaction_residual_n",
        "engineering_note",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "case_id": row.case_id,
                    "variant": row.variant,
                    "n_elem": row.n_elem,
                    "element_type": row.element_type,
                    "section_sampling_mode": row.section_sampling_mode,
                    "internal_tip_uz_m": row.internal_tip_uz_m,
                    "calculix_tip_uz_m": row.calculix_tip_uz_m,
                    "closed_form_or_reference_tip_uz_m": row.reference_tip_uz_m,
                    "internal_vs_calculix_error_pct": row.internal_vs_calculix_error_pct,
                    "reference_vs_calculix_error_pct": row.reference_vs_calculix_error_pct,
                    "root_reaction_fz_n": row.root_reaction_fz_n,
                    "reaction_residual_n": row.reaction_residual_n,
                    "engineering_note": row.engineering_note,
                }
            )

    section_rows = [row for row in rows if row.case_id == "B2_section_sampling"]
    mesh_rows = [row for row in rows if row.case_id == "B2_mesh_sweep"]
    control_row = next(row for row in rows if row.case_id == "B2_constant_control")
    lines = [
        "# B2 Tapered Beam Diagnosis",
        "",
        "## Constant-Section Control",
        "",
        "| Variant | n_elem | Internal tip [m] | CalculiX tip [m] | Reference tip [m] | Internal vs CCX [%] | Ref vs CCX [%] |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        "| "
        f"{control_row.variant} | {control_row.n_elem} | "
        f"{control_row.internal_tip_uz_m:.6f} | {control_row.calculix_tip_uz_m:.6f} | "
        f"{control_row.reference_tip_uz_m:.6f} | {control_row.internal_vs_calculix_error_pct:.3f} | "
        f"{control_row.reference_vs_calculix_error_pct:.3f} |",
        "",
        "## Section Sampling Sweep (n_elem = 20)",
        "",
        "| Sampling mode | Internal tip [m] | CalculiX tip [m] | Reference tip [m] | Internal vs CCX [%] | Ref vs CCX [%] |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in section_rows:
        lines.append(
            "| "
            f"{row.section_sampling_mode} | {row.internal_tip_uz_m:.6f} | {row.calculix_tip_uz_m:.6f} | "
            f"{row.reference_tip_uz_m:.6f} | {row.internal_vs_calculix_error_pct:.3f} | "
            f"{row.reference_vs_calculix_error_pct:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Mesh Sweep (current section sampling)",
            "",
            "| n_elem | Internal tip [m] | CalculiX tip [m] | Reference tip [m] | Internal vs CCX [%] | Ref vs CCX [%] |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in mesh_rows:
        lines.append(
            "| "
            f"{row.n_elem} | {row.internal_tip_uz_m:.6f} | {row.calculix_tip_uz_m:.6f} | "
            f"{row.reference_tip_uz_m:.6f} | {row.internal_vs_calculix_error_pct:.3f} | "
            f"{row.reference_vs_calculix_error_pct:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Interpretation",
            "",
            f"- Constant-section control stays inside {control_row.reference_vs_calculix_error_pct:.3f}% vs the independent reference, so the nodal load mapping/root clamp route is not the dominant B2 problem.",
            f"- Across the n=20 section-sampling sweep, CalculiX stays in a narrow {min(row.reference_vs_calculix_error_pct for row in section_rows):.3f}% to {max(row.reference_vs_calculix_error_pct for row in section_rows):.3f}% error band relative to the independent Euler-Bernoulli reference.",
            f"- Across the current-sampling mesh sweep (8 -> 128 elements), the CalculiX gap does not converge away; the same reference-vs-CalculiX error band remains {min(row.reference_vs_calculix_error_pct for row in mesh_rows):.3f}% to {max(row.reference_vs_calculix_error_pct for row in mesh_rows):.3f}%.",
            "- This points to a stable B32R + PIPE tapered-beam formulation mismatch rather than a simple section-sampling or mesh-density bug in the local benchmark script.",
            "- Exploratory element-type swaps showed that CalculiX `*BEAM SECTION, SECTION=PIPE` is restricted to `B32R`, so a B31/B32 sensitivity study would require a different section representation instead of a one-line deck change.",
        ]
    )
    (phase14_dir / "b2_taper_diagnosis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_b2_diagnosis_rows(
    *,
    benchmark_dir: Path,
    cfg,
    b2_spec: SinglePipeCantileverSpec,
) -> list[B2DiagnosisRow]:
    uniform_load_npm = _uniform_load_from_spec(b2_spec)
    span_m = float(b2_spec.y_nodes_m[-1] - b2_spec.y_nodes_m[0])
    root_radius_m = float(b2_spec.outer_radius_m[0])
    tip_radius_m = float(b2_spec.outer_radius_m[-1])
    root_thickness_m = float(b2_spec.thickness_m[0])
    tip_thickness_m = float(b2_spec.thickness_m[-1])
    diagnosis_dir = benchmark_dir / "b2_diagnosis"
    diagnosis_dir.mkdir(parents=True, exist_ok=True)

    rows: list[B2DiagnosisRow] = []
    control_radius_m = 0.5 * (root_radius_m + tip_radius_m)
    control_thickness_m = 0.5 * (root_thickness_m + tip_thickness_m)
    rows.append(
        _run_b2_variant(
            cfg=cfg,
            diagnosis_dir=diagnosis_dir,
            case_id="B2_constant_control",
            variant="constant_control",
            n_elem=b2_spec.outer_radius_m.size,
            root_radius_m=control_radius_m,
            tip_radius_m=control_radius_m,
            root_thickness_m=control_thickness_m,
            tip_thickness_m=control_thickness_m,
            sampling_mode="constant_control",
            uniform_load_npm=uniform_load_npm,
            span_m=span_m,
            material=b2_spec.material,
        )
    )

    for sampling_mode in (
        "current",
        "inboard_end",
        "midpoint",
        "outboard_end",
        "average_geometry",
    ):
        rows.append(
            _run_b2_variant(
                cfg=cfg,
                diagnosis_dir=diagnosis_dir,
                case_id="B2_section_sampling",
                variant=sampling_mode,
                n_elem=b2_spec.outer_radius_m.size,
                root_radius_m=root_radius_m,
                tip_radius_m=tip_radius_m,
                root_thickness_m=root_thickness_m,
                tip_thickness_m=tip_thickness_m,
                sampling_mode=sampling_mode,
                uniform_load_npm=uniform_load_npm,
                span_m=span_m,
                material=b2_spec.material,
            )
        )

    for n_elem in (8, 16, 32, 64, 128):
        rows.append(
            _run_b2_variant(
                cfg=cfg,
                diagnosis_dir=diagnosis_dir,
                case_id="B2_mesh_sweep",
                variant="current",
                n_elem=n_elem,
                root_radius_m=root_radius_m,
                tip_radius_m=tip_radius_m,
                root_thickness_m=root_thickness_m,
                tip_thickness_m=tip_thickness_m,
                sampling_mode="current",
                uniform_load_npm=uniform_load_npm,
                span_m=span_m,
                material=b2_spec.material,
            )
        )
    return rows


def _run_b2_variant(
    *,
    cfg,
    diagnosis_dir: Path,
    case_id: str,
    variant: str,
    n_elem: int,
    root_radius_m: float,
    tip_radius_m: float,
    root_thickness_m: float,
    tip_thickness_m: float,
    sampling_mode: str,
    uniform_load_npm: float,
    span_m: float,
    material: BeamMaterial,
) -> B2DiagnosisRow:
    y_nodes_m = np.linspace(0.0, span_m, n_elem + 1)
    tributary_lengths_m = _node_tributary_lengths(y_nodes_m)
    nodal_fz_n = -float(uniform_load_npm) * tributary_lengths_m
    outer_radius_m, thickness_m = _b2_section_profile(
        root_radius_m=root_radius_m,
        tip_radius_m=tip_radius_m,
        root_thickness_m=root_thickness_m,
        tip_thickness_m=tip_thickness_m,
        n_elem=n_elem,
        sampling_mode=sampling_mode,
    )
    spec = build_single_pipe_cantilever_spec(
        name=f"{case_id.lower()}_{variant}_{n_elem}",
        y_nodes_m=y_nodes_m,
        outer_radius_m=outer_radius_m,
        thickness_m=thickness_m,
        material=material,
        nodal_fz_n=nodal_fz_n,
    )
    internal_tip_uz_m = abs(_solve_single_beam_internal(spec)["tip_main_m"])
    reference_tip_uz_m = _piecewise_uniform_load_reference_tip_deflection(
        y_nodes_m=y_nodes_m,
        outer_radius_m=outer_radius_m,
        thickness_m=thickness_m,
        young_pa=material.young_pa,
        uniform_load_npm=uniform_load_npm,
    )
    deck = write_calculix_beam_inp(spec, diagnosis_dir / f"{case_id.lower()}_{variant}_{n_elem}.inp")
    run_payload = run_static(deck.inp_path, cfg)
    if run_payload.get("error"):
        raise RuntimeError(f"B2 diagnosis run failed for {case_id}/{variant}/{n_elem}: {run_payload['error']}")
    frd_path = Path(run_payload["frd"]).resolve()
    dat_path = Path(run_payload["dat"]).resolve()
    disp = parse_displacement(frd_path)
    calculix_tip_uz_m = abs(_nodal_uz(disp, deck.node_sets["TIP_MAIN"][0]))
    total_force = parse_total_force_from_dat(dat_path, "HPA_SUPPORT_ALL")
    root_reaction_fz_n = None
    reaction_residual_n = None
    if total_force is not None:
        root_reaction_fz_n = abs(float(total_force[2]) - _support_applied_fz(spec, deck.node_sets))
        reaction_residual_n = float(root_reaction_fz_n + np.sum(spec.nodal_fz_n))
    engineering_note = (
        "Constant-section control keeps the same nodal load/displacement bookkeeping."
        if sampling_mode == "constant_control"
        else (
            "Linear nodal taper averaged over each element is identical to midpoint sampling."
            if sampling_mode == "average_geometry"
            else "B32R PIPE tapered-beam probe."
        )
    )
    return B2DiagnosisRow(
        case_id=case_id,
        variant=variant,
        n_elem=n_elem,
        element_type="B32R",
        section_sampling_mode=sampling_mode,
        internal_tip_uz_m=internal_tip_uz_m,
        calculix_tip_uz_m=calculix_tip_uz_m,
        reference_tip_uz_m=reference_tip_uz_m,
        internal_vs_calculix_error_pct=_pct_error(calculix_tip_uz_m, internal_tip_uz_m),
        reference_vs_calculix_error_pct=_pct_error(calculix_tip_uz_m, reference_tip_uz_m),
        root_reaction_fz_n=root_reaction_fz_n,
        reaction_residual_n=reaction_residual_n,
        engineering_note=engineering_note,
    )


def _b2_section_profile(
    *,
    root_radius_m: float,
    tip_radius_m: float,
    root_thickness_m: float,
    tip_thickness_m: float,
    n_elem: int,
    sampling_mode: str,
) -> tuple[np.ndarray, np.ndarray]:
    if sampling_mode == "constant_control":
        return (
            np.full(n_elem, root_radius_m, dtype=float),
            np.full(n_elem, root_thickness_m, dtype=float),
        )

    if sampling_mode == "current":
        return (
            np.linspace(root_radius_m, tip_radius_m, n_elem),
            np.linspace(root_thickness_m, tip_thickness_m, n_elem),
        )

    radius_nodes_m = np.linspace(root_radius_m, tip_radius_m, n_elem + 1)
    thickness_nodes_m = np.linspace(root_thickness_m, tip_thickness_m, n_elem + 1)
    if sampling_mode == "inboard_end":
        return radius_nodes_m[:-1], thickness_nodes_m[:-1]
    if sampling_mode in {"midpoint", "average_geometry"}:
        return (
            0.5 * (radius_nodes_m[:-1] + radius_nodes_m[1:]),
            0.5 * (thickness_nodes_m[:-1] + thickness_nodes_m[1:]),
        )
    if sampling_mode == "outboard_end":
        return radius_nodes_m[1:], thickness_nodes_m[1:]
    raise ValueError(f"Unsupported B2 section sampling mode: {sampling_mode}")


def _uniform_load_from_spec(spec: SinglePipeCantileverSpec) -> float:
    tributary_lengths_m = _node_tributary_lengths(spec.y_nodes_m)
    valid = tributary_lengths_m > 1.0e-12
    loads = -spec.nodal_fz_n[valid] / tributary_lengths_m[valid]
    return float(np.median(loads))


def _as_array(values: np.ndarray | list[float] | tuple[float, ...]) -> np.ndarray:
    return np.asarray(values, dtype=float)


def _write_comparison_csv(path: Path, case_results: list[BenchmarkCaseResult]) -> None:
    fieldnames = [
        "benchmark_id",
        "variant_id",
        "display_name",
        "status",
        "deck_path",
        "frd_path",
        "dat_path",
        "closed_form_tip_deflection_m",
        "internal_tip_main_m",
        "fem_tip_main_m",
        "closed_form_error_pct",
        "internal_vs_fem_tip_main_pct",
        "internal_tip_rear_m",
        "fem_tip_rear_m",
        "internal_vs_fem_tip_rear_pct",
        "internal_reaction_total_fz_n",
        "fem_reaction_total_fz_n",
        "reaction_error_pct",
        "note",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in case_results:
            writer.writerow(
                {
                    "benchmark_id": result.benchmark_id,
                    "variant_id": result.variant_id,
                    "display_name": result.display_name,
                    "status": result.status,
                    "deck_path": str(result.deck_path),
                    "frd_path": "" if result.frd_path is None else str(result.frd_path),
                    "dat_path": "" if result.dat_path is None else str(result.dat_path),
                    "closed_form_tip_deflection_m": result.closed_form_tip_deflection_m,
                    "internal_tip_main_m": result.internal_tip_main_m,
                    "fem_tip_main_m": result.fem_tip_main_m,
                    "closed_form_error_pct": result.closed_form_error_pct,
                    "internal_vs_fem_tip_main_pct": result.internal_vs_fem_tip_main_pct,
                    "internal_tip_rear_m": result.internal_tip_rear_m,
                    "fem_tip_rear_m": result.fem_tip_rear_m,
                    "internal_vs_fem_tip_rear_pct": result.internal_vs_fem_tip_rear_pct,
                    "internal_reaction_total_fz_n": result.internal_reaction_total_fz_n,
                    "fem_reaction_total_fz_n": result.fem_reaction_total_fz_n,
                    "reaction_error_pct": result.reaction_error_pct,
                    "note": result.note,
                }
            )


def _write_summary_md(
    path: Path,
    *,
    solver_paths: SolverPaths,
    manifest_path: Path,
    case_results: list[BenchmarkCaseResult],
) -> None:
    lines = [
        "# Phase 14 CalculiX Beam Benchmark Summary",
        "",
        "## Solver discovery",
        "",
        f"- Manifest: `{manifest_path}`",
        f"- ccx path: `{solver_paths.ccx_path}`" if solver_paths.ccx_path else "- ccx path: not found",
        f"- gmsh path: `{solver_paths.gmsh_path}`" if solver_paths.gmsh_path else "- gmsh path: not found",
        "",
    ]
    if solver_paths.ccx_path is None:
        lines.extend(
            [
                "## Availability",
                "",
                "- CalculiX not available through `load_config` + `find_ccx`; benchmark decks were generated but solver runs were skipped.",
                "",
            ]
        )

    lines.extend(
        [
            "## Benchmark results",
            "",
            "| Benchmark | Variant | Status | Main tip err vs internal [%] | Rear tip err vs internal [%] | Closed-form err [%] | Reaction err [%] |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in case_results:
        lines.append(
            "| "
            f"{result.benchmark_id} | {result.variant_id} | {result.status} | "
            f"{_fmt(result.internal_vs_fem_tip_main_pct)} | "
            f"{_fmt(result.internal_vs_fem_tip_rear_pct)} | "
            f"{_fmt(result.closed_form_error_pct)} | "
            f"{_fmt(result.reaction_error_pct)} |"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for result in case_results:
        lines.append(f"- `{result.benchmark_id}/{result.variant_id}`: {result.note}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _single_beam_station_index(node_id: int) -> int:
    if node_id < 1 or node_id % 2 == 0:
        raise ValueError(f"Beam station node id must be a positive odd endpoint id, got {node_id}.")
    return (node_id - 1) // 2


def _rear_beam_station_index(node_id: int, nn: int) -> int:
    rear_root_id = 2 * nn
    local_node_id = node_id - rear_root_id + 1
    if local_node_id < 1 or local_node_id % 2 == 0:
        raise ValueError(
            f"Rear beam station node id must map to an endpoint in the rear block, got {node_id}."
        )
    return (local_node_id - 1) // 2


def main() -> None:
    args = _build_parser().parse_args()
    run_phase14_calculix_beam_benchmarks(
        config_path=args.config,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
    )


if __name__ == "__main__":
    main()
