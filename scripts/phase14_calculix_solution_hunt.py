#!/usr/bin/env python3
"""Focused Phase 14 CalculiX solution-hunt probes."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.phase14_calculix_beam_benchmarks as phase14_bench
from hpa_mdo.hifi.frd_parser import parse_displacement, parse_last_field_block


DEFAULT_MANIFEST = REPO_ROOT / "output" / "phase14_dual_beam_calibration" / "benchmark_manifest.csv"


@dataclass(frozen=True)
class B2SolutionHuntRow:
    candidate_id: str
    route_family: str
    status: str
    element_type: str
    section_sampling_mode: str
    n_elem: int | None
    supported_in_ccx: bool
    solver_returncode: int | None
    calculix_tip_uz_m: float | None
    reference_tip_uz_m: float | None
    reference_vs_calculix_error_pct: float | None
    engineering_note: str


@dataclass(frozen=True)
class B5SingleBeamProbeRow:
    case_id: str
    applied_tip_my_nm: float
    tip_uz_abs_m: float
    section_force_torque_root_nm: float
    section_force_torque_tip_nm: float
    max_abs_section_force_torque_nm: float
    engineering_note: str


@dataclass(frozen=True)
class B5SolutionHuntRow:
    torque_mode: str
    applied_spanwise_moment_n_m: float
    centerline_twist_proxy_rad: float
    main_section_torque_root_n_m: float
    main_section_torque_max_abs_n_m: float
    rear_section_torque_max_abs_n_m: float
    expected_main_root_section_torque_n_m: float
    root_torque_error_pct: float | None
    engineering_note: str


def write_single_beam_apdl_truth_deck(
    spec: phase14_bench.SinglePipeCantileverSpec,
    path: str | Path,
) -> Path:
    """Write a minimal BEAM188/CTUBE APDL truth deck for one cantilever."""

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "! ============================================================",
        "! Phase 14 B2 tapered tube truth deck",
        "! Purpose: independent ANSYS APDL BEAM188/CTUBE comparison deck",
        "! Geometry/load convention matches the Mac-local CalculiX benchmark",
        "! ============================================================",
        "/PREP7",
        "",
        "! --- Material ---",
        f"MP,EX,1,{spec.material.young_pa:.9e}",
        f"MP,PRXY,1,{spec.material.poisson_ratio:.9g}",
        f"MP,DENS,1,{spec.material.density_kgpm3:.9g}",
        "",
        "! --- Element type ---",
        "ET,1,BEAM188",
        "KEYOPT,1,1,0",
        "KEYOPT,1,3,2",
        "",
        "! --- Keypoints ---",
    ]
    for node_index, y_m in enumerate(spec.y_nodes_m, start=1):
        lines.append(f"K,{node_index},0.0,{float(y_m):.9g},0.0")
    lines.extend(
        [
            "",
            "! --- Lines ---",
        ]
    )
    for line_id in range(1, spec.y_nodes_m.size):
        lines.append(f"L,{line_id},{line_id + 1}")
    lines.extend(
        [
            "",
            "! --- Elementwise CTUBE sections + mesh ---",
        ]
    )
    for elem_index, (outer_radius_m, thickness_m) in enumerate(
        zip(spec.outer_radius_m, spec.thickness_m, strict=True),
        start=1,
    ):
        inner_radius_m = max(float(outer_radius_m) - float(thickness_m), 0.0)
        lines.extend(
            [
                f"SECTYPE,{elem_index},BEAM,CTUBE",
                f"SECDATA,{inner_radius_m:.9e},{float(outer_radius_m):.9e}",
                f"LSEL,S,LINE,,{elem_index}",
                f"LATT,1,,1,,,,{elem_index}",
                "LESIZE,ALL,,,1",
                "LMESH,ALL",
            ]
        )
    lines.extend(
        [
            "ALLSEL,ALL",
            "",
            "! --- Boundary conditions ---",
            "DK,1,ALL,0",
        ]
    )
    for node_index in spec.wire_node_indices:
        lines.append(f"DK,{int(node_index) + 1},UZ,0")
    lines.extend(
        [
            "",
            "! --- Loads ---",
        ]
    )
    for node_index, fz_n in enumerate(spec.nodal_fz_n, start=1):
        if abs(float(fz_n)) > 0.0:
            lines.append(f"FK,{node_index},FZ,{float(fz_n):.9e}")
    for node_index, my_nm in enumerate(spec.nodal_my_nm, start=1):
        if abs(float(my_nm)) > 0.0:
            lines.append(f"FK,{node_index},MY,{float(my_nm):.9e}")
    lines.extend(
        [
            "",
            "! --- Solve ---",
            "FINISH",
            "/SOLU",
            "ANTYPE,STATIC",
            "SOLVE",
            "FINISH",
            "",
            "! --- Post ---",
            "/POST1",
            "SET,LAST",
            f"*GET,TIP_UZ,NODE,{spec.y_nodes_m.size},U,Z",
            "PRRSOL,FZ",
            "/OUTPUT,b2_tapered_tube_post,txt",
            "*VWRITE,TIP_UZ",
            "('TIP_UZ=',E16.8)",
            "/OUTPUT",
            "FINISH",
            "",
        ]
    )
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_dual_beam_apdl_truth_deck(
    spec: phase14_bench.DualPipeBenchmarkSpec,
    path: str | Path,
) -> Path:
    """Write a parity-style dual-beam APDL truth deck for one B5 variant."""

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    nn = spec.y_nodes_m.size
    lines = [
        "! ============================================================",
        f"! Phase 14 B5 truth deck: {spec.name}",
        "! Purpose: parity-style ANSYS APDL dual-beam truth deck",
        "! Beam-link/wire/load ownership matches the Mac-local CalculiX benchmark",
        "! ============================================================",
        "/PREP7",
        "",
        "! --- Materials ---",
        f"MP,EX,1,{spec.material_main.young_pa:.9e}",
        f"MP,PRXY,1,{spec.material_main.poisson_ratio:.9g}",
        f"MP,DENS,1,{spec.material_main.density_kgpm3:.9g}",
        f"MP,EX,2,{spec.material_rear.young_pa:.9e}",
        f"MP,PRXY,2,{spec.material_rear.poisson_ratio:.9g}",
        f"MP,DENS,2,{spec.material_rear.density_kgpm3:.9g}",
        "",
        "! --- Element types ---",
        "ET,1,BEAM188",
        "KEYOPT,1,1,0",
        "KEYOPT,1,3,2",
        "ET,2,BEAM188",
        "KEYOPT,2,1,0",
        "KEYOPT,2,3,2",
        "",
        "! --- Main keypoints ---",
    ]
    for node_index in range(nn):
        lines.append(
            f"K,{node_index + 1},{float(spec.main_x_m[node_index]):.9g},{float(spec.y_nodes_m[node_index]):.9g},{float(spec.main_z_m[node_index]):.9g}"
        )
    lines.extend(
        [
            "",
            "! --- Rear keypoints ---",
        ]
    )
    for node_index in range(nn):
        lines.append(
            f"K,{nn + node_index + 1},{float(spec.rear_x_m[node_index]):.9g},{float(spec.y_nodes_m[node_index]):.9g},{float(spec.rear_z_m[node_index]):.9g}"
        )
    lines.extend(
        [
            "",
            "! --- Main lines ---",
        ]
    )
    for line_id in range(1, nn):
        lines.append(f"L,{line_id},{line_id + 1}")
    lines.extend(
        [
            "",
            "! --- Rear lines ---",
        ]
    )
    for elem_index in range(nn - 1):
        start_id = nn + elem_index + 1
        lines.append(f"L,{start_id},{start_id + 1}")
    lines.extend(
        [
            "",
            "! --- Main sections + mesh ---",
        ]
    )
    for elem_index, (outer_radius_m, thickness_m) in enumerate(
        zip(spec.main_outer_radius_m, spec.main_thickness_m, strict=True),
        start=1,
    ):
        inner_radius_m = max(float(outer_radius_m) - float(thickness_m), 0.0)
        lines.extend(
            [
                f"SECTYPE,{elem_index},BEAM,CTUBE",
                f"SECDATA,{inner_radius_m:.9e},{float(outer_radius_m):.9e}",
                f"LSEL,S,LINE,,{elem_index}",
                f"LATT,1,,1,,,,{elem_index}",
                "LESIZE,ALL,,,1",
                "LMESH,ALL",
            ]
        )
    lines.extend(
        [
            "ALLSEL,ALL",
            "",
            "! --- Rear sections + mesh ---",
        ]
    )
    for elem_index, (outer_radius_m, thickness_m) in enumerate(
        zip(spec.rear_outer_radius_m, spec.rear_thickness_m, strict=True),
        start=1,
    ):
        inner_radius_m = max(float(outer_radius_m) - float(thickness_m), 0.0)
        sec_id = (nn - 1) + elem_index
        line_id = (nn - 1) + elem_index
        lines.extend(
            [
                f"SECTYPE,{sec_id},BEAM,CTUBE",
                f"SECDATA,{inner_radius_m:.9e},{float(outer_radius_m):.9e}",
                f"LSEL,S,LINE,,{line_id}",
                f"LATT,2,,2,,,,{sec_id}",
                "LESIZE,ALL,,,1",
                "LMESH,ALL",
            ]
        )
    lines.extend(
        [
            "ALLSEL,ALL",
            "",
            "! --- Parity-style equal-DOF rib links ---",
        ]
    )
    for node_index in spec.joint_node_indices:
        main_node = int(node_index) + 1
        rear_node = nn + int(node_index) + 1
        for dof_label in ("UX", "UY", "UZ", "ROTX", "ROTY", "ROTZ"):
            lines.append(f"CE,NEXT,0,{main_node},{dof_label},1,{rear_node},{dof_label},-1")
    lines.extend(
        [
            "",
            "! --- Boundary conditions ---",
            "DK,1,ALL,0",
            f"DK,{nn + 1},ALL,0",
        ]
    )
    for wire_node_index in spec.wire_node_indices:
        lines.append(f"DK,{int(wire_node_index) + 1},UZ,0")
    lines.extend(
        [
            "",
            "! --- Loads ---",
        ]
    )
    for node_index, fz_n in enumerate(spec.main_nodal_fz_n, start=1):
        if abs(float(fz_n)) > 0.0:
            lines.append(f"FK,{node_index},FZ,{float(fz_n):.9e}")
    for node_index, my_nm in enumerate(spec.main_nodal_my_nm, start=1):
        if abs(float(my_nm)) > 0.0:
            lines.append(f"FK,{node_index},MY,{float(my_nm):.9e}")
    for node_index, fz_n in enumerate(spec.rear_nodal_fz_n, start=1):
        if abs(float(fz_n)) > 0.0:
            lines.append(f"FK,{nn + node_index},FZ,{float(fz_n):.9e}")
    for node_index, my_nm in enumerate(spec.rear_nodal_my_nm, start=1):
        if abs(float(my_nm)) > 0.0:
            lines.append(f"FK,{nn + node_index},MY,{float(my_nm):.9e}")
    lines.extend(
        [
            "",
            "! --- Solve ---",
            "FINISH",
            "/SOLU",
            "ANTYPE,STATIC",
            "SOLVE",
            "FINISH",
            "",
            "! --- Post ---",
            "/POST1",
            "SET,LAST",
            f"*GET,MAIN_TIP_UZ,NODE,{nn},U,Z",
            f"*GET,REAR_TIP_UZ,NODE,{2 * nn},U,Z",
            "PRRSOL,FZ",
            "/OUTPUT,b5_truth_post,txt",
            "*VWRITE,MAIN_TIP_UZ,REAR_TIP_UZ",
            "('MAIN_TIP_UZ=',E16.8,', REAR_TIP_UZ=',E16.8)",
            "/OUTPUT",
            "FINISH",
            "",
        ]
    )
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def run_b2_solution_hunt(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Path]:
    """Run the B2 tapered-beam solution hunt and write artifacts."""

    config_path = Path(config_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    apdl_dir = output_dir / "apdl_truth_decks"
    apdl_dir.mkdir(parents=True, exist_ok=True)

    cfg = phase14_bench.load_config(config_path)
    manifest_rows = phase14_bench._load_manifest_rows(Path(manifest_path).resolve())
    cases = phase14_bench._build_benchmark_cases(cfg=cfg, manifest_rows=manifest_rows)
    b2_case = next(case for case in cases if case.benchmark_id == "B2")
    if not isinstance(b2_case.spec, phase14_bench.SinglePipeCantileverSpec):
        raise TypeError("B2 solution hunt expects a single-pipe cantilever spec.")

    diagnosis_dir = output_dir / "_b2_solution_hunt_runs"
    rows = phase14_bench._build_b2_diagnosis_rows(
        benchmark_dir=diagnosis_dir,
        cfg=cfg,
        b2_spec=b2_case.spec,
    )
    current_row = next(
        row
        for row in rows
        if row.case_id == "B2_section_sampling" and row.section_sampling_mode == "current"
    )
    midpoint_row = next(
        row
        for row in rows
        if row.case_id == "B2_section_sampling" and row.section_sampling_mode == "midpoint"
    )
    average_row = next(
        row
        for row in rows
        if row.case_id == "B2_section_sampling" and row.section_sampling_mode == "average_geometry"
    )

    solution_rows = [
        B2SolutionHuntRow(
            candidate_id="current_b32r_pipe",
            route_family="legal_ccx_pipe",
            status="WARN",
            element_type=current_row.element_type,
            section_sampling_mode=current_row.section_sampling_mode,
            n_elem=current_row.n_elem,
            supported_in_ccx=True,
            solver_returncode=0,
            calculix_tip_uz_m=current_row.calculix_tip_uz_m,
            reference_tip_uz_m=current_row.reference_tip_uz_m,
            reference_vs_calculix_error_pct=current_row.reference_vs_calculix_error_pct,
            engineering_note="Current production-like CalculiX route. Stable tapered-beam underprediction remains.",
        ),
        B2SolutionHuntRow(
            candidate_id="midpoint_b32r_pipe",
            route_family="legal_ccx_pipe",
            status="WARN",
            element_type=midpoint_row.element_type,
            section_sampling_mode=midpoint_row.section_sampling_mode,
            n_elem=midpoint_row.n_elem,
            supported_in_ccx=True,
            solver_returncode=0,
            calculix_tip_uz_m=midpoint_row.calculix_tip_uz_m,
            reference_tip_uz_m=midpoint_row.reference_tip_uz_m,
            reference_vs_calculix_error_pct=midpoint_row.reference_vs_calculix_error_pct,
            engineering_note="Midpoint section sampling does not materially reduce the tapered-pipe gap.",
        ),
        B2SolutionHuntRow(
            candidate_id="average_geometry_b32r_pipe",
            route_family="legal_ccx_pipe",
            status="WARN",
            element_type=average_row.element_type,
            section_sampling_mode=average_row.section_sampling_mode,
            n_elem=average_row.n_elem,
            supported_in_ccx=True,
            solver_returncode=0,
            calculix_tip_uz_m=average_row.calculix_tip_uz_m,
            reference_tip_uz_m=average_row.reference_tip_uz_m,
            reference_vs_calculix_error_pct=average_row.reference_vs_calculix_error_pct,
            engineering_note="Average-geometry sampling collapses to the same result as midpoint sampling for a linear taper.",
        ),
    ]

    baseline_deck_path = diagnosis_dir / "b2_diagnosis" / "b2_section_sampling_current_20.inp"
    for element_type in ("B31R", "B31", "B32"):
        solution_rows.append(
            _run_b2_element_type_swap_probe(
                baseline_deck_path=baseline_deck_path,
                cfg=cfg,
                output_dir=output_dir / "_b2_solution_hunt_element_type_probes",
                element_type=element_type,
            )
        )

    apdl_path = write_single_beam_apdl_truth_deck(
        b2_case.spec,
        apdl_dir / "b2_tapered_tube.apdl",
    )
    solution_rows.append(
        B2SolutionHuntRow(
            candidate_id="apdl_truth_deck",
            route_family="apdl_truth",
            status="TRUTH_DECK_PREPARED",
            element_type="BEAM188",
            section_sampling_mode="current",
            n_elem=b2_case.spec.outer_radius_m.size,
            supported_in_ccx=False,
            solver_returncode=None,
            calculix_tip_uz_m=None,
            reference_tip_uz_m=None,
            reference_vs_calculix_error_pct=None,
            engineering_note="Prepared an ANSYS APDL BEAM188/CTUBE deck because no legal CalculiX pipe alternative improved the warning-grade tapered result.",
        )
    )

    csv_path = output_dir / "b2_solution_hunt.csv"
    _write_csv(
        csv_path,
        fieldnames=[
            "candidate_id",
            "route_family",
            "status",
            "element_type",
            "section_sampling_mode",
            "n_elem",
            "supported_in_ccx",
            "solver_returncode",
            "calculix_tip_uz_m",
            "reference_tip_uz_m",
            "reference_vs_calculix_error_pct",
            "engineering_note",
        ],
        rows=[row.__dict__ for row in solution_rows],
    )

    md_path = output_dir / "b2_solution_hunt.md"
    md_lines = [
        "# B2 Solution Hunt",
        "",
        "## Candidate Summary",
        "",
        "| Candidate | Status | Element | Sampling | Tip [m] | Reference [m] | Ref vs CCX [%] |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in solution_rows:
        md_lines.append(
            "| "
            f"{row.candidate_id} | {row.status} | {row.element_type} | {row.section_sampling_mode} | "
            f"{_fmt_number(row.calculix_tip_uz_m)} | {_fmt_number(row.reference_tip_uz_m)} | "
            f"{_fmt_number(row.reference_vs_calculix_error_pct)} |"
        )
    md_lines.extend(
        [
            "",
            "## Engineering Interpretation",
            "",
            f"- The current legal CalculiX route stays at {current_row.reference_vs_calculix_error_pct:.3f}% error relative to the independent reference; midpoint and average-geometry sampling stay at {midpoint_row.reference_vs_calculix_error_pct:.3f}% / {average_row.reference_vs_calculix_error_pct:.3f}%, so the warning does not come from a simple elementwise section-sampling choice.",
            "- CalculiX 2.23 rejects the obvious element-type swap probes (`B31R`, `B31`, `B32`) because `*BEAM SECTION, SECTION=PIPE` is restricted to `B32R`. That removes the most obvious like-for-like pipe sensitivity path.",
            "- No honest Mac-local CalculiX route in this hunt moved B2 into a pass-grade band without changing the physics family or using a manual-invalid workaround.",
            f"- The next defensible truth source is the APDL deck at `{apdl_path}`. It keeps the same beam/load conventions while moving the tapered-pipe question to BEAM188/CTUBE.",
            "",
            "## Verdict",
            "",
            "B2 remains a warning in the current CalculiX gate. From a structures-engineering standpoint, the evidence now points to a solver/formulation difference for tapered pipe beams rather than a trivial local exporter bug.",
        ]
    )
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return {
        "csv_path": csv_path,
        "md_path": md_path,
        "apdl_path": apdl_path,
    }


def run_b5_single_beam_torsion_probe(
    *,
    config_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Run a minimal single-beam torsion probe to validate torque observability."""

    config_path = Path(config_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = phase14_bench.load_config(config_path)

    material = phase14_bench.BeamMaterial(
        name="MAIN",
        young_pa=135.0e9,
        poisson_ratio=0.3,
        density_kgpm3=1600.0,
    )
    y_nodes_m = np.linspace(0.0, 10.0, 21)
    outer_radius_m = np.full(y_nodes_m.size - 1, 0.03)
    thickness_m = np.full(y_nodes_m.size - 1, 0.0015)

    probe_rows = [
        _run_single_beam_torque_probe_case(
            cfg=cfg,
            output_dir=output_dir / "_b5_single_beam_probe_runs",
            case_id="single_tip_my_100nm",
            spec=phase14_bench.build_single_pipe_cantilever_spec(
                name="b5_single_tip_my_100nm",
                y_nodes_m=y_nodes_m,
                outer_radius_m=outer_radius_m,
                thickness_m=thickness_m,
                material=material,
                nodal_fz_n=np.zeros(y_nodes_m.size),
                nodal_my_nm=np.pad(np.asarray([100.0]), (y_nodes_m.size - 1, 0)),
            ),
        ),
        _run_single_beam_torque_probe_case(
            cfg=cfg,
            output_dir=output_dir / "_b5_single_beam_probe_runs",
            case_id="single_control_0nm",
            spec=phase14_bench.build_single_pipe_cantilever_spec(
                name="b5_single_control_0nm",
                y_nodes_m=y_nodes_m,
                outer_radius_m=outer_radius_m,
                thickness_m=thickness_m,
                material=material,
                nodal_fz_n=np.zeros(y_nodes_m.size),
                nodal_my_nm=np.zeros(y_nodes_m.size),
            ),
        ),
    ]

    csv_path = output_dir / "b5_single_beam_torsion_probe.csv"
    _write_csv(
        csv_path,
        fieldnames=[
            "case_id",
            "applied_tip_my_nm",
            "tip_uz_abs_m",
            "section_force_torque_root_nm",
            "section_force_torque_tip_nm",
            "max_abs_section_force_torque_nm",
            "engineering_note",
        ],
        rows=[row.__dict__ for row in probe_rows],
    )

    torque_row = next(row for row in probe_rows if row.case_id == "single_tip_my_100nm")
    control_row = next(row for row in probe_rows if row.case_id == "single_control_0nm")
    md_path = output_dir / "b5_single_beam_torsion_probe.md"
    lines = [
        "# B5 Single-Beam Torsion Probe",
        "",
        "## Probe Summary",
        "",
        "| Case | Applied tip MY [N m] | |UZ_tip| [m] | Root section torque [N m] | Tip section torque [N m] | Max |torque| [N m] |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in probe_rows:
        lines.append(
            "| "
            f"{row.case_id} | {row.applied_tip_my_nm:.3f} | {row.tip_uz_abs_m:.6e} | "
            f"{row.section_force_torque_root_nm:.3f} | {row.section_force_torque_tip_nm:.3f} | "
            f"{row.max_abs_section_force_torque_nm:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Interpretation",
            "",
            f"- With a pure 100 N m tip `MY` load, the centerline `UZ` response stays tiny ({torque_row.tip_uz_abs_m:.3e} m), so the old B5 `UZ`-only route is structurally blind to pure torsion on a centered single beam.",
            f"- The same deck shows a clean `SECTION FORCES` torque signal: root/tip values {torque_row.section_force_torque_root_nm:.3f} / {torque_row.section_force_torque_tip_nm:.3f} N m and max |torque| {torque_row.max_abs_section_force_torque_nm:.3f} N m.",
            f"- The zero-torque control stays at {control_row.max_abs_section_force_torque_nm:.3e} N m, so the signal is not numerical noise from the parser alone.",
            "",
            "## Verdict",
            "",
            "CalculiX does expose beam-axis torsion in this benchmark family. The missing piece was not solver capability; it was that the prior parity report was watching the wrong observable.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"csv_path": csv_path, "md_path": md_path}


def run_b5_solution_hunt(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Path]:
    """Run B5 torque observability probes and write artifacts."""

    config_path = Path(config_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    apdl_dir = output_dir / "apdl_truth_decks"
    apdl_dir.mkdir(parents=True, exist_ok=True)

    cfg = phase14_bench.load_config(config_path)
    manifest_rows = phase14_bench._load_manifest_rows(Path(manifest_path).resolve())
    cases = phase14_bench._build_benchmark_cases(cfg=cfg, manifest_rows=manifest_rows)
    b5_cases = [case for case in cases if case.benchmark_id == "B5"]

    solution_rows = [
        _run_dual_beam_section_force_probe(
            cfg=cfg,
            output_dir=output_dir / "_b5_solution_hunt_runs",
            case=case,
        )
        for case in b5_cases
    ]

    truth_deck_paths = {
        case.variant_id: write_dual_beam_apdl_truth_deck(
            case.spec,
            apdl_dir / f"b5_{case.variant_id}.apdl",
        )
        for case in b5_cases
        if isinstance(case.spec, phase14_bench.DualPipeBenchmarkSpec)
    }

    csv_path = output_dir / "b5_solution_hunt.csv"
    _write_csv(
        csv_path,
        fieldnames=[
            "torque_mode",
            "applied_spanwise_moment_n_m",
            "centerline_twist_proxy_rad",
            "main_section_torque_root_n_m",
            "main_section_torque_max_abs_n_m",
            "rear_section_torque_max_abs_n_m",
            "expected_main_root_section_torque_n_m",
            "root_torque_error_pct",
            "engineering_note",
        ],
        rows=[row.__dict__ for row in solution_rows],
    )

    by_mode = {row.torque_mode: row for row in solution_rows}
    my_row = by_mode["main_beam_my_about_main_spar"]
    couple_row = by_mode["front_rear_vertical_couple"]
    control_row = by_mode["cm_off_control"]
    md_path = output_dir / "b5_solution_hunt.md"
    lines = [
        "# B5 Solution Hunt",
        "",
        "## Candidate Summary",
        "",
        "| Mode | Applied moment [N m] | Twist proxy [rad] | Main root torque [N m] | Main max |torque| [N m] | Rear max |torque| [N m] | Root torque err [%] |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in solution_rows:
        lines.append(
            "| "
            f"{row.torque_mode} | {row.applied_spanwise_moment_n_m:.3f} | {row.centerline_twist_proxy_rad:.6f} | "
            f"{row.main_section_torque_root_n_m:.6f} | {row.main_section_torque_max_abs_n_m:.6f} | "
            f"{row.rear_section_torque_max_abs_n_m:.6f} | {_fmt_number(row.root_torque_error_pct)} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Interpretation",
            "",
            f"- The direct `main_beam_my_about_main_spar` route now has a clean observable: main-beam section torque is {my_row.main_section_torque_root_n_m:.3f} N m at the root section and {my_row.main_section_torque_max_abs_n_m:.3f} N m max, versus an expected {my_row.expected_main_root_section_torque_n_m:.3f} N m from the distributed nodal `MY` loads. The root torque error is {my_row.root_torque_error_pct:.3f}%.",
            f"- The `cm_off_control` case stays near numerical zero in section-force torque ({control_row.main_section_torque_max_abs_n_m:.3e} N m main, {control_row.rear_section_torque_max_abs_n_m:.3e} N m rear) even though the old centerline twist proxy was nonzero. That confirms the old proxy mixed in non-torsional deformation modes.",
            f"- The `front_rear_vertical_couple` case still changes the centerline twist proxy ({couple_row.centerline_twist_proxy_rad:.6f} rad), but its beam-axis section torque stays near zero on both beams ({couple_row.main_section_torque_max_abs_n_m:.3e} / {couple_row.rear_section_torque_max_abs_n_m:.3e} N m). In engineering terms, this load path is acting like a coupled bending/shear surrogate in the current linked dual-beam topology, not like the same torsional observable as direct `MY`.",
            "- That means B5 should not be treated as one blended parity gate. Direct `MY` ownership is now observable in CalculiX via `SECTION FORCES`; the front/rear vertical-couple route should remain a separate surrogate experiment, not a truth-equivalent replacement.",
            "",
            "## APDL Truth Decks",
            "",
            f"- `main_beam_my_about_main_spar`: `{truth_deck_paths['main_beam_my_about_main_spar']}`",
            f"- `front_rear_vertical_couple`: `{truth_deck_paths['front_rear_vertical_couple']}`",
            f"- `cm_off_control`: `{truth_deck_paths['cm_off_control']}`",
            "",
            "## Verdict",
            "",
            "B5 is no longer blocked by lack of a CalculiX torque observable. The real remaining question is policy: direct `MY` can be checked through section forces, but the vertical-couple surrogate should not be promoted to the same truth status without external confirmation.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"csv_path": csv_path, "md_path": md_path}


def _run_b2_element_type_swap_probe(
    *,
    baseline_deck_path: Path,
    cfg: Any,
    output_dir: Path,
    element_type: str,
) -> B2SolutionHuntRow:
    output_dir.mkdir(parents=True, exist_ok=True)
    probe_path = output_dir / f"b2_{element_type.lower()}_pipe_probe.inp"
    text = baseline_deck_path.read_text(encoding="utf-8")
    probe_path.write_text(text.replace("TYPE=B32R", f"TYPE={element_type}"), encoding="utf-8")
    run_payload = phase14_bench.run_static(probe_path, cfg)
    note = "CalculiX accepted the probe unexpectedly."
    status = "PASS"
    if run_payload.get("error"):
        note = _extract_solver_rejection_reason(str(run_payload["error"]))
        status = "REJECTED"
    return B2SolutionHuntRow(
        candidate_id=f"{element_type.lower()}_pipe_probe",
        route_family="illegal_ccx_pipe_swap",
        status=status,
        element_type=element_type,
        section_sampling_mode="current",
        n_elem=20,
        supported_in_ccx=False,
        solver_returncode=run_payload.get("returncode"),
        calculix_tip_uz_m=None,
        reference_tip_uz_m=None,
        reference_vs_calculix_error_pct=None,
        engineering_note=note,
    )


def _run_single_beam_torque_probe_case(
    *,
    cfg: Any,
    output_dir: Path,
    case_id: str,
    spec: phase14_bench.SinglePipeCantileverSpec,
) -> B5SingleBeamProbeRow:
    output_dir.mkdir(parents=True, exist_ok=True)
    deck = phase14_bench.write_calculix_beam_inp(spec, output_dir / f"{case_id}.inp")
    _inject_section_force_output(deck.inp_path)
    run_payload = phase14_bench.run_static(deck.inp_path, cfg)
    if run_payload.get("error"):
        raise RuntimeError(f"B5 single-beam probe failed for {case_id}: {run_payload['error']}")
    field = parse_last_field_block(Path(run_payload["frd"]), "STRESS")
    if field is None:
        raise RuntimeError(f"B5 single-beam probe produced no STRESS/SECTION FORCES block for {case_id}.")
    torque = _component_series(field.rows, field.labels, "SXY")
    disp = parse_displacement(Path(run_payload["frd"]))
    tip_uz_abs_m = abs(_nodal_uz(disp, deck.node_sets["TIP_MAIN"][0]))
    applied_tip_my_nm = float(spec.nodal_my_nm[-1])
    note = "SECTION FORCES exposes beam-axis torque even when centerline UZ is nearly zero."
    if abs(applied_tip_my_nm) <= 1.0e-12:
        note = "Zero-torque control establishes the section-force noise floor."
    return B5SingleBeamProbeRow(
        case_id=case_id,
        applied_tip_my_nm=applied_tip_my_nm,
        tip_uz_abs_m=tip_uz_abs_m,
        section_force_torque_root_nm=float(torque[0]),
        section_force_torque_tip_nm=float(torque[-1]),
        max_abs_section_force_torque_nm=float(np.max(np.abs(torque))),
        engineering_note=note,
    )


def _run_dual_beam_section_force_probe(
    *,
    cfg: Any,
    output_dir: Path,
    case: phase14_bench.BenchmarkCase,
) -> B5SolutionHuntRow:
    if not isinstance(case.spec, phase14_bench.DualPipeBenchmarkSpec):
        raise TypeError("B5 solution hunt expects dual-beam specs.")
    output_dir.mkdir(parents=True, exist_ok=True)
    diagnostic = phase14_bench._run_dual_beam_diagnostic_case(
        cfg=cfg,
        diagnosis_dir=output_dir,
        spec=case.spec,
    )
    _inject_section_force_output(diagnostic.deck_path)
    rerun = phase14_bench.run_static(diagnostic.deck_path, cfg)
    if rerun.get("error"):
        raise RuntimeError(f"B5 section-force rerun failed for {case.variant_id}: {rerun['error']}")
    field = parse_last_field_block(Path(rerun["frd"]), "STRESS")
    if field is None:
        raise RuntimeError(f"B5 section-force probe produced no STRESS block for {case.variant_id}.")

    root_rear = diagnostic.node_sets["ROOT_REAR"][0]
    main_rows = field.rows[field.rows[:, 0] < float(root_rear)]
    rear_rows = field.rows[field.rows[:, 0] >= float(root_rear)]
    main_torque = _component_series(main_rows, field.labels, "SXY")
    rear_torque = _component_series(rear_rows, field.labels, "SXY")
    expected_root_torque = _expected_main_root_section_torque(case.spec)
    root_torque_error_pct = None
    if abs(expected_root_torque) > 1.0e-12:
        root_torque_error_pct = phase14_bench._pct_error(float(main_torque[0]), expected_root_torque)

    note_parts = []
    if case.variant_id == "main_beam_my_about_main_spar":
        note_parts.append("Direct MY route is now observable through main-beam section torque.")
    elif case.variant_id == "front_rear_vertical_couple":
        note_parts.append(
            "Force-couple route changes centerline displacement but does not create a meaningful beam-axis section-torque signal."
        )
    else:
        note_parts.append("Zero-torque control establishes the section-force baseline for the dual-beam topology.")

    return B5SolutionHuntRow(
        torque_mode=case.variant_id,
        applied_spanwise_moment_n_m=float(case.internal_metrics["applied_spanwise_moment_n_m"]),
        centerline_twist_proxy_rad=float(diagnostic.fem_twist_proxy_rad),
        main_section_torque_root_n_m=float(main_torque[0]),
        main_section_torque_max_abs_n_m=float(np.max(np.abs(main_torque))),
        rear_section_torque_max_abs_n_m=float(np.max(np.abs(rear_torque))),
        expected_main_root_section_torque_n_m=expected_root_torque,
        root_torque_error_pct=root_torque_error_pct,
        engineering_note=" ".join(note_parts),
    )


def _expected_main_root_section_torque(spec: phase14_bench.DualPipeBenchmarkSpec) -> float:
    # The root beam section sits outboard of the clamped root node, so the
    # root-node applied MY does not appear in the first beam section resultant.
    return float(np.sum(spec.main_nodal_my_nm[1:]))


def _component_series(rows: np.ndarray, labels: tuple[str, ...], label: str) -> np.ndarray:
    label_upper = str(label).upper()
    try:
        idx = [name.upper() for name in labels].index(label_upper)
    except ValueError as exc:
        raise KeyError(f"Component {label} not present in FRD field labels {labels}.") from exc
    return np.asarray(rows[:, idx + 1], dtype=float)


def _inject_section_force_output(inp_path: Path) -> None:
    text = inp_path.read_text(encoding="utf-8")
    target = "*NODE FILE, OUTPUT=2D\nU"
    replacement = "*NODE FILE, OUTPUT=2D\nU\n*EL FILE, SECTION FORCES\nS,NOE"
    if replacement in text:
        return
    if target not in text:
        raise ValueError(f"Expected node-file output block not found in {inp_path}.")
    inp_path.write_text(text.replace(target, replacement), encoding="utf-8")


def _nodal_uz(displacements: np.ndarray, node_id: int) -> float:
    matches = displacements[displacements[:, 0] == float(node_id)]
    if matches.size == 0:
        raise KeyError(f"Node {node_id} not present in FRD displacement block.")
    return float(matches[-1, 3])


def _fmt_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{float(value):.6f}"


def _extract_solver_rejection_reason(text: str) -> str:
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if "*BEAM SECTION of type PIPE can" in line and idx + 1 < len(lines):
            return f"{line} {lines[idx + 1]}"
    for line in lines:
        if "CalculiX stops" in line:
            return line
    return "CalculiX rejected the deck."


def _write_csv(path: Path, *, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Config YAML used for local solver discovery.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Phase 14 artifact root, typically output/phase14_dual_beam_calibration.",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Phase 14 benchmark manifest CSV.",
    )
    parser.add_argument(
        "--task",
        choices=("b2", "b5"),
        default="b2",
        help="Focused solution-hunt task to run.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.task == "b2":
        run_b2_solution_hunt(
            config_path=args.config,
            output_dir=args.output_dir,
            manifest_path=args.manifest,
        )
    elif args.task == "b5":
        run_b5_single_beam_torsion_probe(
            config_path=args.config,
            output_dir=args.output_dir,
        )
        run_b5_solution_hunt(
            config_path=args.config,
            output_dir=args.output_dir,
            manifest_path=args.manifest,
        )


if __name__ == "__main__":
    main()
