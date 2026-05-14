#!/usr/bin/env python3
"""Run Phase 1 toolchain sanity for the canonical hybrid half-wing CFD route."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_wo006r8_basic_airfoil_bl_benchmark import (  # noqa: E402
    build_basic_airfoil_case,
    run_basic_airfoil_benchmark,
)


DEFAULT_SECTION_TABLE_PATH = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "production_inspection"
    / "current_avl_compromise_conservative_closed"
    / "section_table.csv"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "cfd_release_v0"
    / "toolchain_sanity"
)
DEFAULT_MANIFEST_PATH = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "cfd_release_v0"
    / "manifest.yaml"
)
DEFAULT_SOLVER_COMMAND = "/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD"
REQUIRED_CASE_IDS = frozenset(
    {
        "naca4412_2d",
        "current_root_dae31",
        "current_tip_cst",
    }
)


@dataclass(frozen=True)
class Phase1CaseSpec:
    case_id: str
    section_role: str
    airfoil: str
    airfoil_id: str
    chord_m: float
    alpha_deg: float
    airfoil_dat_path: Path | None
    source_section_index: int | None


def build_phase1_case_specs(
    section_table_path: Path | str = DEFAULT_SECTION_TABLE_PATH,
    *,
    alpha_deg: float = 4.0,
) -> list[Phase1CaseSpec]:
    rows = _read_section_rows(Path(section_table_path))
    root = rows[0]
    tip = rows[-1]
    return [
        Phase1CaseSpec(
            case_id="naca4412_2d",
            section_role="naca4412_2d",
            airfoil="NACA4412",
            airfoil_id="NACA4412",
            chord_m=1.130189765,
            alpha_deg=float(alpha_deg),
            airfoil_dat_path=None,
            source_section_index=None,
        ),
        _spec_from_section("current_root_dae31", "current_root", root, alpha_deg),
        _spec_from_section("current_tip_cst", "current_tip", tip, alpha_deg),
    ]


def evaluate_phase1_toolchain_gate(
    reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    by_case_id = {str(report.get("phase1_case_id")): report for report in reports}
    missing = REQUIRED_CASE_IDS - set(by_case_id)
    if missing:
        blockers.append("phase1_required_case_missing")
    case_summaries: list[dict[str, Any]] = []
    for case_id in sorted(REQUIRED_CASE_IDS & set(by_case_id)):
        report = by_case_id[case_id]
        role = str(report.get("phase1_section_role") or case_id)
        solver = _mapping(report.get("solver"))
        gate = _mapping(solver.get("coefficient_sanity_gate"))
        coeffs = _mapping(gate.get("final_coefficients"))
        stable_window = _mapping(gate.get("stable_window"))
        cd = _float_or_none(coeffs.get("cd"))
        cl_span = _float_or_none(stable_window.get("cl_relative_span"))
        cd_span = _float_or_none(stable_window.get("cd_relative_span"))
        stable = (
            cl_span is not None
            and cd_span is not None
            and cl_span <= 0.01
            and cd_span <= 0.01
        )
        if solver.get("run_status") != "completed":
            blockers.append("case_solver_not_completed")
        if gate.get("status") != "pass":
            blockers.append("case_coefficient_gate_not_pass")
        if not stable:
            blockers.append("case_force_window_not_stable")
        if cd is None:
            blockers.append("case_cd_missing")
        elif role == "naca4412_2d" and not (0.01 <= cd <= 0.03):
            blockers.append("naca_cd_outside_0p01_0p03")
        elif role != "naca4412_2d" and cd >= 0.10:
            blockers.append("actual_section_cd_exceeds_0p1")
        elif role != "naca4412_2d" and cd >= 0.07:
            warnings.append("actual_section_cd_high_but_below_blocker")
        case_summaries.append(
            {
                "case_id": case_id,
                "role": role,
                "solver_status": solver.get("run_status"),
                "cd": cd,
                "cl_relative_span": cl_span,
                "cd_relative_span": cd_span,
                "stable": stable,
            }
        )
    status = "pass" if not blockers else "fail"
    return {
        "status": status,
        "release_status": "TOOLCHAIN_PASS" if status == "pass" else None,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "case_summaries": case_summaries,
    }


def run_phase1_toolchain_sanity(
    *,
    section_table_path: Path = DEFAULT_SECTION_TABLE_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_su2: bool,
    max_iterations: int,
    solver_command: str = DEFAULT_SOLVER_COMMAND,
    threads: int = 4,
    timeout_seconds: float = 1800.0,
    update_manifest: bool = False,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = build_phase1_case_specs(section_table_path)
    reports: list[dict[str, Any]] = []
    for spec in specs:
        case = build_basic_airfoil_case(
            airfoil=spec.airfoil,
            chord_m=spec.chord_m,
            alpha_deg=spec.alpha_deg,
            max_iterations=max_iterations,
            airfoil_dat_path=(
                None if spec.airfoil_dat_path is None else str(spec.airfoil_dat_path)
            ),
        )
        report = run_basic_airfoil_benchmark(
            case,
            output_dir / spec.case_id,
            run_su2=run_su2,
            solver_command=solver_command,
            threads=threads,
            timeout_seconds=timeout_seconds,
        )
        report["phase1_case_id"] = spec.case_id
        report["phase1_section_role"] = spec.section_role
        report["phase1_case_spec"] = _spec_payload(spec)
        reports.append(report)
    gate = evaluate_phase1_toolchain_gate(reports)
    summary = {
        "schema_version": "canonical_hybrid_phase1_toolchain_sanity.v0",
        "route": "canonical_hybrid_halfwing_v0",
        "phase_gate": "TOOLCHAIN_PASS",
        "section_table_path": str(section_table_path),
        "output_dir": str(output_dir),
        "run_su2": bool(run_su2),
        "case_specs": [_spec_payload(spec) for spec in specs],
        "case_report_paths": [
            str(Path(str(report["report_path"]))) for report in reports if report.get("report_path")
        ],
        "gate": gate,
    }
    summary_path = output_dir / "toolchain_sanity_report.json"
    md_path = output_dir / "toolchain_sanity_report.md"
    summary["report_path"] = str(summary_path)
    summary["markdown_report_path"] = str(md_path)
    if update_manifest and gate["status"] == "pass":
        _mark_manifest_toolchain_pass(manifest_path, summary)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown_summary(summary), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section-table", type=Path, default=DEFAULT_SECTION_TABLE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--solver-command", default=DEFAULT_SOLVER_COMMAND)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--max-iterations", type=int, default=2000)
    parser.add_argument("--run-su2", action="store_true")
    parser.add_argument("--update-manifest", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args(argv)

    summary = run_phase1_toolchain_sanity(
        section_table_path=args.section_table,
        output_dir=args.output_dir,
        run_su2=args.run_su2,
        max_iterations=args.max_iterations,
        solver_command=args.solver_command,
        threads=args.threads,
        timeout_seconds=args.timeout_seconds,
        update_manifest=args.update_manifest,
        manifest_path=args.manifest,
    )
    gate = summary["gate"]
    print(f"Phase 1 TOOLCHAIN_PASS gate: {gate['status']}")
    if gate["blockers"]:
        for blocker in gate["blockers"]:
            print(f"- {blocker}")
    return 0 if gate["status"] == "pass" else 1


def _read_section_rows(section_table_path: Path) -> list[dict[str, str]]:
    with section_table_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) < 2:
        raise ValueError(f"section table has too few rows: {section_table_path}")
    return rows


def _spec_from_section(
    case_id: str,
    section_role: str,
    row: Mapping[str, str],
    alpha_deg: float,
) -> Phase1CaseSpec:
    airfoil_id = str(row["airfoil_id"])
    return Phase1CaseSpec(
        case_id=case_id,
        section_role=section_role,
        airfoil=airfoil_id,
        airfoil_id=airfoil_id,
        chord_m=float(row["chord_m"]),
        alpha_deg=float(alpha_deg),
        airfoil_dat_path=Path(row["airfoil_dat_path"]),
        source_section_index=int(row["section_index"]),
    )


def _spec_payload(spec: Phase1CaseSpec) -> dict[str, Any]:
    payload = asdict(spec)
    payload["airfoil_dat_path"] = (
        None if spec.airfoil_dat_path is None else str(spec.airfoil_dat_path)
    )
    return payload


def _mark_manifest_toolchain_pass(manifest_path: Path, summary: Mapping[str, Any]) -> None:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    statuses = list(manifest.get("passed_gate_statuses") or [])
    if "TOOLCHAIN_PASS" not in statuses:
        statuses.append("TOOLCHAIN_PASS")
    manifest["passed_gate_statuses"] = statuses
    manifest["next_required_gate_status"] = "PRESSURE_SANITY_PASS"
    manifest["phase1_toolchain_sanity"] = {
        "status": "TOOLCHAIN_PASS",
        "report_path": summary.get("report_path"),
        "case_report_paths": summary.get("case_report_paths"),
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def _markdown_summary(summary: Mapping[str, Any]) -> str:
    gate = _mapping(summary.get("gate"))
    lines = [
        "# Canonical Hybrid Phase 1 Toolchain Sanity",
        "",
        f"- route: `{summary.get('route')}`",
        f"- phase gate: `{summary.get('phase_gate')}`",
        f"- status: `{gate.get('status')}`",
        f"- release status: `{gate.get('release_status')}`",
        f"- blockers: `{gate.get('blockers')}`",
        f"- warnings: `{gate.get('warnings')}`",
        "",
        "## Case Summary",
        "",
        "| case | role | CD | stable |",
        "|---|---|---:|---|",
    ]
    for row in gate.get("case_summaries") or []:
        lines.append(
            f"| `{row['case_id']}` | `{row['role']}` | `{row.get('cd')}` | `{row.get('stable')}` |"
        )
    lines.append("")
    return "\n".join(lines)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted


if __name__ == "__main__":
    raise SystemExit(main())
