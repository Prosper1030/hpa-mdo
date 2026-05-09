#!/usr/bin/env python3
"""Review Phase41 buckling reference loads before treating eigenvalues as ranking evidence."""
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

from hpa_mdo.hifi.frd_parser import (  # noqa: E402
    parse_buckle_eigenvalues,
    parse_total_force_from_dat,
)
from scripts.phase41_braced_subassembly_fem_evidence import (  # noqa: E402
    BracedSubassemblyFemEvidence,
    load_current_braced_subassembly_fem_evidence,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase42_phase41_reference_load_review"
LAMBDA_REVIEW_THRESHOLD = 50.0
BALANCE_ERROR_WARN_PCT = 5.0


@dataclass(frozen=True)
class Phase41ReferenceLoadReviewRow:
    case_id: str
    status: str
    deck_path: str
    dat_path: str
    applied_fz_n: float | None
    applied_abs_fz_n: float | None
    applied_my_nm: float | None
    applied_axial_fy_n: float | None
    support_reaction_fz_n: float | None
    fz_balance_error_pct: float | None
    fz_balance_status: str
    sign_convention_read: str
    first_eigen_multiplier: float | None
    lambda_plausibility_status: str
    axial_reference_load_status: str
    phase41_status: str
    phase30_closure_status: str
    engineering_read: str
    next_action: str


@dataclass(frozen=True)
class Phase41ReferenceLoadReview:
    candidate_id: str
    overall_status: str
    row_count: int
    not_rankable_count: int
    compression_path_review_count: int
    balanced_count: int
    rows: tuple[Phase41ReferenceLoadReviewRow, ...]


def build_phase41_reference_load_review(
    phase41_evidence: BracedSubassemblyFemEvidence,
) -> Phase41ReferenceLoadReview:
    rows = tuple(_build_row(row) for row in phase41_evidence.rows)
    not_rankable_count = sum(
        1 for row in rows if row.status == "reference_load_formulation_not_rankable"
    )
    compression_path_review_count = sum(
        1
        for row in rows
        if row.status == "reference_load_compression_path_review_required"
    )
    return Phase41ReferenceLoadReview(
        candidate_id=str(phase41_evidence.candidate_id),
        overall_status=(
            "phase41_reference_load_formulation_not_rankable"
            if not_rankable_count
            else "phase41_reference_load_compression_path_review_required"
            if compression_path_review_count
            else "phase41_reference_load_review_required"
        ),
        row_count=len(rows),
        not_rankable_count=not_rankable_count,
        compression_path_review_count=compression_path_review_count,
        balanced_count=sum(1 for row in rows if row.fz_balance_status == "balanced"),
        rows=rows,
    )


def write_phase41_reference_load_review_package(
    out_dir: Path,
    phase41_evidence: BracedSubassemblyFemEvidence,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    review = build_phase41_reference_load_review(phase41_evidence)
    return [
        _write_csv(out_dir / "phase41_reference_load_review.csv", review),
        _write_json(out_dir / "phase41_reference_load_review.json", review),
        _write_markdown(out_dir / "phase41_reference_load_review.md", review),
    ]


def build_current_phase41_reference_load_review() -> Phase41ReferenceLoadReview:
    return build_phase41_reference_load_review(
        load_current_braced_subassembly_fem_evidence()
    )


def _build_row(phase41_row: Any) -> Phase41ReferenceLoadReviewRow:
    deck_path = Path(str(phase41_row.deck_path))
    dat_path = Path(str(phase41_row.dat_path)) if str(phase41_row.dat_path) else Path()
    loads = _read_cloads(deck_path)
    applied_fz = _sum_dof(loads, 3)
    applied_abs_fz = _sum_abs_dof(loads, 3)
    applied_my = _sum_dof(loads, 5)
    applied_fy = _sum_dof(loads, 2)
    support_reaction = (
        parse_total_force_from_dat(dat_path, "HPA_SUPPORT_ALL")
        if dat_path.exists()
        else None
    )
    support_fz = support_reaction[2] if support_reaction is not None else None
    fz_balance_error = _balance_error_pct(applied_fz, support_fz)
    first_lambda = _first_lambda(phase41_row, dat_path)
    lambda_status = _lambda_status(first_lambda)
    axial_status = _axial_reference_status(applied_fy)
    balance_status = _balance_status(fz_balance_error)
    sign_read = _sign_convention_read(applied_fz, support_fz)
    status = _row_status(
        balance_status=balance_status,
        lambda_status=lambda_status,
        axial_status=axial_status,
    )
    return Phase41ReferenceLoadReviewRow(
        case_id=str(phase41_row.case_id),
        status=status,
        deck_path=str(deck_path),
        dat_path=str(dat_path) if dat_path else "",
        applied_fz_n=applied_fz,
        applied_abs_fz_n=applied_abs_fz,
        applied_my_nm=applied_my,
        applied_axial_fy_n=applied_fy,
        support_reaction_fz_n=support_fz,
        fz_balance_error_pct=fz_balance_error,
        fz_balance_status=balance_status,
        sign_convention_read=sign_read,
        first_eigen_multiplier=first_lambda,
        lambda_plausibility_status=lambda_status,
        axial_reference_load_status=axial_status,
        phase41_status=str(phase41_row.status),
        phase30_closure_status=str(phase41_row.phase30_closure_status),
        engineering_read=_engineering_read(
            status=status,
            balance_status=balance_status,
            lambda_status=lambda_status,
            axial_status=axial_status,
        ),
        next_action=_next_action(status),
    )


def _read_cloads(path: Path) -> tuple[tuple[int, int, float], ...]:
    if not path.exists():
        return ()
    loads: list[tuple[int, int, float]] = []
    in_cload = False
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw.strip()
        upper = stripped.upper()
        if upper.startswith("*CLOAD"):
            in_cload = True
            continue
        if in_cload and stripped.startswith("*"):
            break
        if not in_cload or not stripped or stripped.startswith("**"):
            continue
        parts = [part.strip() for part in stripped.split(",")]
        if len(parts) < 3:
            continue
        loads.append((int(parts[0]), int(parts[1]), float(parts[2])))
    return tuple(loads)


def _sum_dof(loads: tuple[tuple[int, int, float], ...], dof: int) -> float | None:
    values = [value for _, load_dof, value in loads if load_dof == dof]
    return sum(values) if values else None


def _sum_abs_dof(loads: tuple[tuple[int, int, float], ...], dof: int) -> float | None:
    values = [abs(value) for _, load_dof, value in loads if load_dof == dof]
    return sum(values) if values else None


def _balance_error_pct(applied_fz: float | None, support_fz: float | None) -> float | None:
    if applied_fz is None or support_fz is None or abs(applied_fz) <= 1.0e-12:
        return None
    error_pct = (
        abs(float(applied_fz) + float(support_fz)) / abs(float(applied_fz)) * 100.0
    )
    return round(error_pct, 6)


def _first_lambda(phase41_row: Any, dat_path: Path) -> float | None:
    if getattr(phase41_row, "first_eigen_multiplier", None) is not None:
        return float(phase41_row.first_eigen_multiplier)
    if dat_path.exists():
        eigenvalues = parse_buckle_eigenvalues(dat_path)
        if eigenvalues:
            return float(eigenvalues[0])
    return None


def _balance_status(fz_balance_error_pct: float | None) -> str:
    if fz_balance_error_pct is None:
        return "not_available"
    if fz_balance_error_pct <= BALANCE_ERROR_WARN_PCT:
        return "balanced"
    return "load_balance_review_required"


def _sign_convention_read(
    applied_fz: float | None,
    support_fz: float | None,
) -> str:
    if applied_fz is None or support_fz is None:
        return "not_available"
    if applied_fz * support_fz < 0.0:
        return "support_reaction_opposes_applied_fz"
    return "support_reaction_same_sign_as_applied_fz"


def _lambda_status(first_lambda: float | None) -> str:
    if first_lambda is None:
        return "not_available"
    if first_lambda > LAMBDA_REVIEW_THRESHOLD:
        return "implausibly_high_for_claim_margin"
    return "screening_range"


def _axial_reference_status(applied_fy: float | None) -> str:
    if applied_fy is None or abs(applied_fy) <= 1.0e-12:
        return "no_axial_compression_reference"
    return "axial_reference_load_present"


def _row_status(
    *,
    balance_status: str,
    lambda_status: str,
    axial_status: str,
) -> str:
    if balance_status == "load_balance_review_required":
        return "load_balance_or_sign_review_required"
    if (
        lambda_status == "implausibly_high_for_claim_margin"
        and axial_status == "no_axial_compression_reference"
    ):
        return "reference_load_formulation_not_rankable"
    if lambda_status == "not_available":
        return "solver_eigenvalue_missing"
    if axial_status == "no_axial_compression_reference":
        return "reference_load_compression_path_review_required"
    return "mode_review_still_required"


def _engineering_read(
    *,
    status: str,
    balance_status: str,
    lambda_status: str,
    axial_status: str,
) -> str:
    if status == "reference_load_formulation_not_rankable":
        return (
            "The vertical reaction balance is acceptable, so a simple FZ sign flip is not the primary issue. "
            "The Phase41 deck is a transverse lift/moment reference with no axial compression reference, "
            "and the very large eigen multiplier is not usable buckling margin."
        )
    if status == "load_balance_or_sign_review_required":
        return "The applied vertical load and support reaction do not balance closely enough for buckling ranking."
    if status == "reference_load_compression_path_review_required":
        return (
            "The eigen multiplier is in a screening range, but the deck has no direct axial "
            "compression reference. Bending moment may create compression, so this needs a "
            "reviewed compressive reference path before mode-shape review can be treated as "
            "rankable buckling evidence."
        )
    return (
        "Reference load still needs mode review before ranking. "
        f"balance={balance_status}; lambda={lambda_status}; axial={axial_status}."
    )


def _next_action(status: str) -> str:
    if status == "reference_load_formulation_not_rankable":
        return (
            "Replace Phase41's transverse lift/moment reference with a qualified global/prestress buckling "
            "load case or move to a shell/beam model with reviewed compressive stress state."
        )
    if status == "load_balance_or_sign_review_required":
        return "Fix load/sign convention and rerun Phase41 before mode review."
    if status == "reference_load_compression_path_review_required":
        return (
            "Qualify the compressive prestress/reference-load path from the bending/axial "
            "load state, then rerun Phase41/Phase42 before using the eigenvalue for ranking."
        )
    return "Perform mode-shape review, mesh/link sensitivity, and Phase30 promotion only if the first mode is physical."


def _write_csv(path: Path, review: Phase41ReferenceLoadReview) -> Path:
    fields = list(asdict(review.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in review.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, review: Phase41ReferenceLoadReview) -> Path:
    path.write_text(
        json.dumps(asdict(review), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, review: Phase41ReferenceLoadReview) -> Path:
    lines = [
        "# Phase41 Reference Load Review",
        "",
        f"Candidate: `{review.candidate_id}`",
        f"Overall status: `{review.overall_status}`",
        "",
        "This checks whether the Phase41 braced-subassembly eigenvalue can be used as ranking evidence. A balanced support reaction is not enough: the reference load must create a physical global buckling stress state.",
        "",
        f"- rows: `{review.row_count}`",
        f"- not-rankable rows: `{review.not_rankable_count}`",
        f"- compression-path review rows: `{review.compression_path_review_count}`",
        f"- balanced rows: `{review.balanced_count}`",
        "",
        "| case | status | Fz N | RFz N | balance % | axial ref | lambda status | lambda |",
        "|---|---|---:|---:|---:|---|---|---:|",
    ]
    for row in review.rows:
        lines.append(
            f"| {row.case_id} | `{row.status}` | {_fmt(row.applied_fz_n)} | "
            f"{_fmt(row.support_reaction_fz_n)} | {_fmt(row.fz_balance_error_pct)} | "
            f"{row.axial_reference_load_status} | {row.lambda_plausibility_status} | "
            f"{_fmt(row.first_eigen_multiplier)} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Read",
            "",
        ]
    )
    for row in review.rows:
        lines.append(f"- **{row.case_id}**: {row.engineering_read}")
        lines.append(f"  Next: {row.next_action}")
    lines.extend(
        [
            "",
            "Conclusion: the current Phase41 eigenvalue is route/debug evidence, not usable buckling margin.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    outputs = write_phase41_reference_load_review_package(
        args.output_dir,
        load_current_braced_subassembly_fem_evidence(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
