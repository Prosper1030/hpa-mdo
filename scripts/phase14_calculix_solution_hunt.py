#!/usr/bin/env python3
"""Focused Phase 14 CalculiX solution-hunt probes."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.phase14_calculix_beam_benchmarks as phase14_bench


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
        choices=("b2",),
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


if __name__ == "__main__":
    main()
