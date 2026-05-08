#!/usr/bin/env python3
"""Separate tip-deflection gate wording from fracture or submission-relaxation claims."""
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

from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    load_current_candidate_reference,
)
from scripts.phase31_tip_deflection_revalidation_inputs import (  # noqa: E402
    build_current_tip_deflection_revalidation_check,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase39_tip_deflection_claim_boundary"
REQUIRED_SUBMISSION_RECHECKS = "loaded-shape; aeroelastic; clearance; load-path"


@dataclass(frozen=True)
class TipDeflectionClaimBoundaryRow:
    policy_key: str
    status: str
    current_raw_tip_limit_m: float
    current_effective_tip_limit_m: float
    deflection_limit_load_factor: float | None
    revalidation_status: str
    allowed_statement: str
    blocked_statement: str
    required_evidence: str


@dataclass(frozen=True)
class TipDeflectionClaimBoundary:
    candidate_id: str
    overall_status: str
    current_raw_tip_limit_m: float
    current_effective_tip_limit_m: float
    deflection_limit_load_factor: float | None
    revalidation_status: str
    rows: tuple[TipDeflectionClaimBoundaryRow, ...]


def build_tip_deflection_claim_boundary(
    reference: Any,
    *,
    revalidation_check: Any | None,
) -> TipDeflectionClaimBoundary:
    current_raw = _attr_float(revalidation_check, "current_raw_tip_limit_m")
    current_effective = _attr_float(revalidation_check, "current_effective_tip_limit_m")
    if current_raw is None:
        current_raw = _attr_float(reference, "tip_deflection_limit_m") or 0.0
    if current_effective is None:
        current_effective = _attr_float(reference, "tip_deflection_limit_m") or 0.0
    revalidation_status = _revalidation_status(revalidation_check)
    limit_n = _revalidation_limit_load_factor(revalidation_check)
    if limit_n is None:
        limit_n = _deflection_limit_load_factor(reference, current_effective)
    rows = (
        _current_gate_row(current_raw, current_effective, limit_n, revalidation_status),
        _exploration_row(current_raw, current_effective, limit_n, revalidation_status),
        _submission_row(current_raw, current_effective, limit_n, revalidation_status),
    )
    return TipDeflectionClaimBoundary(
        candidate_id=str(reference.candidate_id),
        overall_status=(
            "tip_deflection_claim_boundary_submission_gate_retained"
            if revalidation_status == "current_submission_gate_retained"
            else "tip_deflection_claim_boundary_revalidation_required"
        ),
        current_raw_tip_limit_m=float(current_raw),
        current_effective_tip_limit_m=float(current_effective),
        deflection_limit_load_factor=limit_n,
        revalidation_status=revalidation_status,
        rows=rows,
    )


def write_tip_deflection_claim_boundary_package(
    out_dir: Path,
    reference: Any,
    *,
    revalidation_check: Any | None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    boundary = build_tip_deflection_claim_boundary(
        reference,
        revalidation_check=revalidation_check,
    )
    return [
        _write_csv(out_dir / "tip_deflection_claim_boundary.csv", boundary),
        _write_json(out_dir / "tip_deflection_claim_boundary.json", boundary),
        _write_markdown(out_dir / "tip_deflection_claim_boundary.md", boundary),
    ]


def build_current_tip_deflection_claim_boundary() -> TipDeflectionClaimBoundary:
    return build_tip_deflection_claim_boundary(
        load_current_candidate_reference(),
        revalidation_check=build_current_tip_deflection_revalidation_check(),
    )


def _current_gate_row(
    current_raw: float,
    current_effective: float,
    limit_n: float | None,
    revalidation_status: str,
) -> TipDeflectionClaimBoundaryRow:
    return TipDeflectionClaimBoundaryRow(
        policy_key="current_submission_gate",
        status="design_validity_gate_not_fracture",
        current_raw_tip_limit_m=float(current_raw),
        current_effective_tip_limit_m=float(current_effective),
        deflection_limit_load_factor=limit_n,
        revalidation_status=revalidation_status,
        allowed_statement=(
            f"{current_raw:g} m raw tip limit remains a design-validity/submission gate."
        ),
        blocked_statement=(
            f"Do not treat the {current_raw:g} m raw gate as a fracture point or hardware strength margin."
        ),
        required_evidence="Keep current gate or provide qualified revalidation before submission relaxation.",
    )


def _exploration_row(
    current_raw: float,
    current_effective: float,
    limit_n: float | None,
    revalidation_status: str,
) -> TipDeflectionClaimBoundaryRow:
    return TipDeflectionClaimBoundaryRow(
        policy_key="exploration_relaxation",
        status="exploration_only_not_submission",
        current_raw_tip_limit_m=float(current_raw),
        current_effective_tip_limit_m=float(current_effective),
        deflection_limit_load_factor=limit_n,
        revalidation_status=revalidation_status,
        allowed_statement="Exploration-only relaxation may be used for trade studies.",
        blocked_statement="Do not use exploration relaxation for submission or pass/fail claims.",
        required_evidence="Label relaxed cases as exploration and keep submission reports on the current gate.",
    )


def _submission_row(
    current_raw: float,
    current_effective: float,
    limit_n: float | None,
    revalidation_status: str,
) -> TipDeflectionClaimBoundaryRow:
    return TipDeflectionClaimBoundaryRow(
        policy_key="submission_relaxation",
        status="submission_relaxation_requires_rechecks",
        current_raw_tip_limit_m=float(current_raw),
        current_effective_tip_limit_m=float(current_effective),
        deflection_limit_load_factor=limit_n,
        revalidation_status=revalidation_status,
        allowed_statement="Submission relaxation requires complete revalidation inputs.",
        blocked_statement="Do not relax the submission gate without loaded-shape, aeroelastic, clearance, and load-path rechecks.",
        required_evidence=REQUIRED_SUBMISSION_RECHECKS,
    )


def _revalidation_status(revalidation_check: Any | None) -> str:
    if revalidation_check is None:
        return "revalidation_check_unavailable"
    rows = tuple(getattr(revalidation_check, "rows", ()))
    if not rows:
        return "revalidation_input_missing"
    return str(getattr(rows[0], "status", "unknown"))


def _revalidation_limit_load_factor(revalidation_check: Any | None) -> float | None:
    if revalidation_check is None:
        return None
    rows = tuple(getattr(revalidation_check, "rows", ()))
    if not rows:
        return None
    return _attr_float(rows[0], "deflection_limit_load_factor")


def _deflection_limit_load_factor(reference: Any, effective_limit_m: float | None) -> float | None:
    tip = _attr_float(reference, "tip_deflection_m")
    n_ref = _attr_float(reference, "reference_load_factor")
    if effective_limit_m is None or tip is None or n_ref is None or tip <= 0.0:
        return None
    return float(n_ref) * float(effective_limit_m) / float(tip)


def _attr_float(obj: Any | None, name: str) -> float | None:
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value is None:
        return None
    return float(value)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.4f}"


def _write_csv(path: Path, boundary: TipDeflectionClaimBoundary) -> Path:
    fields = list(asdict(boundary.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in boundary.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, boundary: TipDeflectionClaimBoundary) -> Path:
    path.write_text(
        json.dumps(asdict(boundary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, boundary: TipDeflectionClaimBoundary) -> Path:
    lines = [
        "# Tip Deflection Claim Boundary",
        "",
        f"Candidate: `{boundary.candidate_id}`",
        f"Overall status: `{boundary.overall_status}`",
        "",
        "This separates the tip-deflection design-validity gate from fracture or submission-relaxation claims.",
        "",
        f"- current raw limit: `{_fmt(boundary.current_raw_tip_limit_m)} m`",
        f"- current effective limit: `{_fmt(boundary.current_effective_tip_limit_m)} m`",
        f"- deflection-limit load factor: `{_fmt(boundary.deflection_limit_load_factor)}`",
        f"- revalidation status: `{boundary.revalidation_status}`",
        "",
        "| policy | status | allowed statement | blocked statement | required evidence |",
        "|---|---|---|---|---|",
    ]
    for row in boundary.rows:
        lines.append(
            f"| {row.policy_key} | `{row.status}` | {row.allowed_statement} | "
            f"{row.blocked_statement} | {row.required_evidence} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- The 2.5 m raw gate is not a fracture point.",
            "- Exploration-only relaxations must stay out of submission pass/fail wording.",
            "- Submission relaxation needs loaded-shape, aeroelastic, clearance, and load-path rechecks.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    reference = load_current_candidate_reference()
    outputs = write_tip_deflection_claim_boundary_package(
        args.output_dir,
        reference,
        revalidation_check=build_current_tip_deflection_revalidation_check(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
