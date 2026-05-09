#!/usr/bin/env python3
"""Triage existing torque/twist evidence without promoting it to signoff."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.phase15_candidate_load_factor_buckling_check import CANDIDATE_ID  # noqa: E402


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase47_existing_torsion_twist_evidence_triage"
DEFAULT_PHASE13_MODES = (
    REPO_ROOT / "output" / "phase13_moment_ownership_ab_test" / "moment_ownership_modes.csv"
)
DEFAULT_B5_SOLUTION = (
    REPO_ROOT / "output" / "phase14_dual_beam_calibration" / "b5_solution_hunt.csv"
)
DEFAULT_SINGLE_BEAM_PROBE = (
    REPO_ROOT / "output" / "phase14_dual_beam_calibration" / "b5_single_beam_torsion_probe.csv"
)
DEFAULT_B5_PARITY = (
    REPO_ROOT / "output" / "phase14_dual_beam_calibration" / "b5_torque_parity_diagnosis.csv"
)


@dataclass(frozen=True)
class ExistingTorsionTwistEvidenceRow:
    evidence_key: str
    title: str
    status: str
    closes_torsion_twist_claim: bool
    supports_torque_observable: bool
    supports_aeroelastic_twist: bool
    key_metric: str
    existing_evidence_boundary: str
    remaining_blocker: str
    next_action: str


@dataclass(frozen=True)
class ExistingTorsionTwistEvidenceTriage:
    candidate_id: str
    overall_status: str
    row_count: int
    closing_evidence_count: int
    torque_observable_evidence_count: int
    aeroelastic_closure_evidence_count: int
    rows: tuple[ExistingTorsionTwistEvidenceRow, ...]


def build_existing_torsion_twist_evidence_triage(
    candidate_id: str,
    *,
    phase13_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    b5_solution_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    single_beam_torsion_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    b5_parity_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> ExistingTorsionTwistEvidenceTriage:
    rows = (
        _phase13_row(tuple(phase13_rows)),
        _b5_solution_row(tuple(b5_solution_rows)),
        _single_beam_probe_row(tuple(single_beam_torsion_rows)),
        _b5_parity_row(tuple(b5_parity_rows)),
    )
    closing_count = sum(1 for row in rows if row.closes_torsion_twist_claim)
    torque_count = sum(1 for row in rows if row.supports_torque_observable)
    aero_count = sum(1 for row in rows if row.supports_aeroelastic_twist)
    return ExistingTorsionTwistEvidenceTriage(
        candidate_id=str(candidate_id),
        overall_status=(
            "existing_torsion_twist_evidence_contains_closure_candidate"
            if closing_count
            else "existing_torsion_twist_evidence_does_not_close_goal"
        ),
        row_count=len(rows),
        closing_evidence_count=closing_count,
        torque_observable_evidence_count=torque_count,
        aeroelastic_closure_evidence_count=aero_count,
        rows=rows,
    )


def write_existing_torsion_twist_evidence_triage_package(
    out_dir: Path,
    candidate_id: str,
    *,
    phase13_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    b5_solution_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    single_beam_torsion_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    b5_parity_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    triage = build_existing_torsion_twist_evidence_triage(
        candidate_id,
        phase13_rows=phase13_rows,
        b5_solution_rows=b5_solution_rows,
        single_beam_torsion_rows=single_beam_torsion_rows,
        b5_parity_rows=b5_parity_rows,
    )
    return [
        _write_csv(out_dir / "existing_torsion_twist_evidence_triage.csv", triage),
        _write_json(out_dir / "existing_torsion_twist_evidence_triage.json", triage),
        _write_markdown(out_dir / "existing_torsion_twist_evidence_triage.md", triage),
    ]


def build_current_existing_torsion_twist_evidence_triage() -> (
    ExistingTorsionTwistEvidenceTriage
):
    return build_existing_torsion_twist_evidence_triage(
        CANDIDATE_ID,
        phase13_rows=_read_csv(DEFAULT_PHASE13_MODES),
        b5_solution_rows=_read_csv(DEFAULT_B5_SOLUTION),
        single_beam_torsion_rows=_read_csv(DEFAULT_SINGLE_BEAM_PROBE),
        b5_parity_rows=_read_csv(DEFAULT_B5_PARITY),
    )


def _phase13_row(rows: tuple[dict[str, Any], ...]) -> ExistingTorsionTwistEvidenceRow:
    interpretable = [
        row for row in rows if str(row.get("physically_interpretable", "")).lower() == "true"
    ]
    best = min(
        interpretable or rows,
        key=lambda row: _dict_float(row, "total_moment_residual_nm") or float("inf"),
        default={},
    )
    hard_failures = sorted(
        {
            failure
            for row in rows
            for failure in str(row.get("hard_failures", "")).split(";")
            if failure
        }
    )
    return ExistingTorsionTwistEvidenceRow(
        evidence_key="phase13_torque_ownership_ab_test",
        title="Phase13 torque ownership A/B test",
        status="torque_ownership_diagnostic_not_aeroelastic_signoff",
        closes_torsion_twist_claim=False,
        supports_torque_observable=False,
        supports_aeroelastic_twist=False,
        key_metric=(
            "best interpretable mode="
            f"{best.get('mode_id', 'n/a')}; "
            "XY residual="
            f"{_fmt(_dict_float(best, 'xy_moment_residual_nm'))} N*m; "
            "total residual="
            f"{_fmt(_dict_float(best, 'total_moment_residual_nm'))} N*m; "
            "hard failures="
            f"{';'.join(hard_failures) if hard_failures else 'none'}."
        ),
        existing_evidence_boundary=(
            "Torque ownership diagnostics identify bookkeeping and force-couple behavior, "
            "but they do not provide accepted tip-ring FEM/APDL twist or aeroelastic-loop closure."
        ),
        remaining_blocker=(
            "Moment ownership remains diagnostic/report-only until validated against a "
            "qualified torque/twist closure observable."
        ),
        next_action="Use the Phase13 diagnosis to choose a reviewed torque convention for a closure FEM.",
    )


def _b5_solution_row(rows: tuple[dict[str, Any], ...]) -> ExistingTorsionTwistEvidenceRow:
    direct = _row_by_key(rows, "torque_mode", "main_beam_my_about_main_spar")
    force_couple = _row_by_key(rows, "torque_mode", "front_rear_vertical_couple")
    return ExistingTorsionTwistEvidenceRow(
        evidence_key="phase14_b5_solution_hunt",
        title="Phase14 B5 solution hunt",
        status="direct_my_torque_observable_surrogate_policy_open",
        closes_torsion_twist_claim=False,
        supports_torque_observable=True,
        supports_aeroelastic_twist=False,
        key_metric=(
            "direct MY root torque error="
            f"{_fmt(_dict_float(direct, 'root_torque_error_pct'))}%; "
            "direct MY main root torque="
            f"{_fmt(_dict_float(direct, 'main_section_torque_root_n_m'))} N*m; "
            "front/rear couple main max torque="
            f"{_fmt(_dict_float(force_couple, 'main_section_torque_max_abs_n_m'))} N*m."
        ),
        existing_evidence_boundary=(
            "CalculiX section forces can observe direct MY torque, but the front/rear "
            "vertical-couple route is a bending/shear surrogate in the current topology."
        ),
        remaining_blocker=(
            "Direct MY is observable, but front/rear couple is not truth-equivalent and "
            "neither row is candidate aeroelastic twist closure."
        ),
        next_action=(
            "Promote only a reviewed direct-MY or tip-ring load case into Phase29 closure inputs; "
            "keep force-couple evidence as a separate surrogate."
        ),
    )


def _single_beam_probe_row(
    rows: tuple[dict[str, Any], ...]
) -> ExistingTorsionTwistEvidenceRow:
    torque = _row_by_key(rows, "case_id", "single_tip_my_100nm")
    control = _row_by_key(rows, "case_id", "single_control_0nm")
    return ExistingTorsionTwistEvidenceRow(
        evidence_key="phase14_single_beam_torsion_probe",
        title="Phase14 single-beam torsion probe",
        status="section_force_torque_observable_not_candidate_closure",
        closes_torsion_twist_claim=False,
        supports_torque_observable=True,
        supports_aeroelastic_twist=False,
        key_metric=(
            "applied MY="
            f"{_fmt(_dict_float(torque, 'applied_tip_my_nm'))} N*m; "
            "max |torque|="
            f"{_fmt(_dict_float(torque, 'max_abs_section_force_torque_nm'))} N*m; "
            "zero-control max |torque|="
            f"{_fmt(_dict_float(control, 'max_abs_section_force_torque_nm'))} N*m."
        ),
        existing_evidence_boundary=(
            "This proves section-force torque observability in a benchmark family, not "
            "the current candidate's aeroelastic twist or braced wing torsional stiffness."
        ),
        remaining_blocker="Candidate-level tip-ring FEM/APDL or aeroelastic-loop twist evidence is still missing.",
        next_action="Reuse the section-force observable in a candidate-level torque/twist closure case.",
    )


def _b5_parity_row(rows: tuple[dict[str, Any], ...]) -> ExistingTorsionTwistEvidenceRow:
    twist_errors = [
        _dict_float(row, "twist_error_pct")
        for row in rows
        if _dict_float(row, "twist_error_pct") is not None
    ]
    return ExistingTorsionTwistEvidenceRow(
        evidence_key="phase14_b5_twist_proxy_parity",
        title="Phase14 B5 twist-proxy parity",
        status="centerline_twist_proxy_mismatch_not_closure",
        closes_torsion_twist_claim=False,
        supports_torque_observable=False,
        supports_aeroelastic_twist=False,
        key_metric=(
            "max twist proxy error="
            f"{_fmt(max(twist_errors) if twist_errors else None)}%; "
            "rows="
            f"{len(rows)}."
        ),
        existing_evidence_boundary=(
            "The centerline twist proxy has large mismatch and was explicitly not the "
            "right beam-axis torque observable."
        ),
        remaining_blocker="Replace centerline UZ/twist proxy with reviewed section-force or tip-ring rotation evidence.",
        next_action="Do not promote centerline twist proxy rows to Phase29 closure input.",
    )


def _row_by_key(rows: tuple[dict[str, Any], ...], key: str, value: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get(key, "")) == value:
            return row
    return {}


def _dict_float(row: dict[str, Any], name: str) -> float | None:
    value = row.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _read_csv(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def _write_csv(path: Path, triage: ExistingTorsionTwistEvidenceTriage) -> Path:
    fields = list(asdict(triage.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in triage.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, triage: ExistingTorsionTwistEvidenceTriage) -> Path:
    path.write_text(
        json.dumps(asdict(triage), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, triage: ExistingTorsionTwistEvidenceTriage) -> Path:
    lines = [
        "# Existing Torsion/Twist Evidence Triage",
        "",
        f"Candidate: `{triage.candidate_id}`",
        f"Overall status: `{triage.overall_status}`",
        "",
        "Existing torque evidence is useful, but it is not aeroelastic signoff.",
        "",
        f"- rows: `{triage.row_count}`",
        f"- closing evidence rows: `{triage.closing_evidence_count}`",
        f"- torque-observable evidence rows: `{triage.torque_observable_evidence_count}`",
        f"- aeroelastic closure evidence rows: `{triage.aeroelastic_closure_evidence_count}`",
        "",
        "| evidence | status | closes claim | torque observable | aeroelastic closure | key metric | boundary |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for row in triage.rows:
        lines.append(
            f"| {row.title} | `{row.status}` | {row.closes_torsion_twist_claim} | "
            f"{row.supports_torque_observable} | {row.supports_aeroelastic_twist} | "
            f"{row.key_metric} | {row.existing_evidence_boundary} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- Direct-MY section-force evidence can support a future torque closure route.",
            "- Force-couple and centerline twist-proxy rows remain surrogate/diagnostic evidence.",
            "- Accepted Phase29 closure still requires tip-ring FEM/APDL or aeroelastic-loop twist and torque-balance evidence.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    outputs = write_existing_torsion_twist_evidence_triage_package(
        args.output_dir,
        CANDIDATE_ID,
        phase13_rows=_read_csv(DEFAULT_PHASE13_MODES),
        b5_solution_rows=_read_csv(DEFAULT_B5_SOLUTION),
        single_beam_torsion_rows=_read_csv(DEFAULT_SINGLE_BEAM_PROBE),
        b5_parity_rows=_read_csv(DEFAULT_B5_PARITY),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
