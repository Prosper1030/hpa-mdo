#!/usr/bin/env python3
"""Separate internal local-buckling pass evidence from full-wing buckling claims."""
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
    build_phase15_rows,
    load_current_candidate_reference,
)
from scripts.phase30_full_wing_buckling_closure_inputs import (  # noqa: E402
    build_current_full_wing_buckling_closure_check,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase38_full_wing_buckling_claim_boundary"
DEFAULT_CLAIM_LOAD_FACTORS = (1.5, 1.75)


@dataclass(frozen=True)
class FullWingBucklingClaimBoundaryRow:
    claim_load_factor: float
    status: str
    fem_basis: str
    local_wall_buckling_utilization: float | None
    tube_stress_utilization: float | None
    wire_utilization: float | None
    first_failure_mode: str
    global_buckling_closure_status: str
    missing_global_components: str
    allowed_statement: str
    blocked_statement: str
    required_evidence: str


@dataclass(frozen=True)
class FullWingBucklingClaimBoundary:
    candidate_id: str
    overall_status: str
    required_claim_load_factors: tuple[float, ...]
    global_buckling_closure_status: str
    rows: tuple[FullWingBucklingClaimBoundaryRow, ...]


def build_full_wing_buckling_claim_boundary(
    candidate_id: str,
    *,
    phase15_rows: list[Any] | tuple[Any, ...],
    closure_check: Any | None,
    claim_load_factors: tuple[float, ...] = DEFAULT_CLAIM_LOAD_FACTORS,
) -> FullWingBucklingClaimBoundary:
    rows_by_load = {float(row.load_factor): row for row in phase15_rows}
    closure_status = _closure_status(closure_check)
    missing_components = _missing_components(closure_check)
    rows = tuple(
        _build_row(
            rows_by_load.get(float(load_factor)),
            claim_load_factor=float(load_factor),
            closure_status=closure_status,
            missing_components=missing_components,
        )
        for load_factor in claim_load_factors
    )
    return FullWingBucklingClaimBoundary(
        candidate_id=str(candidate_id),
        overall_status=(
            "full_wing_pass_claim_input_positive_review_required"
            if closure_status == "margin_positive_input_check_only"
            else "full_wing_pass_claim_blocked_global_buckling_missing"
        ),
        required_claim_load_factors=tuple(float(value) for value in claim_load_factors),
        global_buckling_closure_status=closure_status,
        rows=rows,
    )


def write_full_wing_buckling_claim_boundary_package(
    out_dir: Path,
    candidate_id: str,
    *,
    phase15_rows: list[Any] | tuple[Any, ...],
    closure_check: Any | None,
    claim_load_factors: tuple[float, ...] = DEFAULT_CLAIM_LOAD_FACTORS,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    boundary = build_full_wing_buckling_claim_boundary(
        candidate_id,
        phase15_rows=phase15_rows,
        closure_check=closure_check,
        claim_load_factors=claim_load_factors,
    )
    return [
        _write_csv(out_dir / "full_wing_buckling_claim_boundary.csv", boundary),
        _write_json(out_dir / "full_wing_buckling_claim_boundary.json", boundary),
        _write_markdown(out_dir / "full_wing_buckling_claim_boundary.md", boundary),
    ]


def build_current_full_wing_buckling_claim_boundary() -> FullWingBucklingClaimBoundary:
    reference = load_current_candidate_reference()
    return build_full_wing_buckling_claim_boundary(
        reference.candidate_id,
        phase15_rows=build_phase15_rows(reference),
        closure_check=build_current_full_wing_buckling_closure_check(),
    )


def _build_row(
    row: Any | None,
    *,
    claim_load_factor: float,
    closure_status: str,
    missing_components: str,
) -> FullWingBucklingClaimBoundaryRow:
    local_util = _attr_float(row, "local_wall_buckling_utilization")
    stress_util = _attr_float(row, "tube_stress_utilization")
    wire_util = _attr_float(row, "wire_utilization")
    internal_pass = all(
        value is not None and value < 1.0 for value in (local_util, stress_util, wire_util)
    )
    status = (
        "internal_local_pass_global_claim_blocked"
        if internal_pass and closure_status != "margin_positive_input_check_only"
        else "internal_or_global_buckling_claim_not_closed"
    )
    load_label = _load_label(claim_load_factor)
    return FullWingBucklingClaimBoundaryRow(
        claim_load_factor=float(claim_load_factor),
        status=status,
        fem_basis=str(getattr(row, "fem_basis", "")) if row is not None else "",
        local_wall_buckling_utilization=local_util,
        tube_stress_utilization=stress_util,
        wire_utilization=wire_util,
        first_failure_mode=str(getattr(row, "first_failure_mode", "")) if row is not None else "",
        global_buckling_closure_status=closure_status,
        missing_global_components=missing_components,
        allowed_statement=(
            f"{load_label} internal fixed-design modeled limits clear"
            if internal_pass
            else f"{load_label} internal fixed-design modeled limits are not clear"
        ),
        blocked_statement=(
            f"Do not claim {load_label} full-wing pass until full-wing or braced-subassembly "
            "global buckling evidence is present."
        ),
        required_evidence=(
            "Full-wing or credible braced-subassembly global buckling eigen/FEM with main spar, "
            "rear spar, finite ribs, wire-attach load path, root boundary, boundary-condition review, "
            "mesh convergence, and solver pass status."
        ),
    )


def _closure_status(closure_check: Any | None) -> str:
    if closure_check is None:
        return "closure_input_unavailable"
    rows = tuple(getattr(closure_check, "rows", ()))
    if not rows:
        return "closure_input_missing"
    return str(getattr(rows[0], "status", "unknown"))


def _missing_components(closure_check: Any | None) -> str:
    if closure_check is None:
        return "unknown"
    rows = tuple(getattr(closure_check, "rows", ()))
    if not rows:
        return "unknown"
    return str(getattr(rows[0], "missing_components", "") or "none")


def _attr_float(obj: Any | None, name: str) -> float | None:
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value is None:
        return None
    return float(value)


def _load_label(load_factor: float) -> str:
    return f"{float(load_factor):g}G"


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.4f}"


def _write_csv(path: Path, boundary: FullWingBucklingClaimBoundary) -> Path:
    fields = list(asdict(boundary.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in boundary.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, boundary: FullWingBucklingClaimBoundary) -> Path:
    path.write_text(
        json.dumps(asdict(boundary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, boundary: FullWingBucklingClaimBoundary) -> Path:
    lines = [
        "# Full Wing Buckling Claim Boundary",
        "",
        f"Candidate: `{boundary.candidate_id}`",
        f"Overall status: `{boundary.overall_status}`",
        "",
        "This separates internal fixed-design local checks from full-wing global buckling claims.",
        "",
        f"- global buckling closure status: `{boundary.global_buckling_closure_status}`",
        "",
        "| load | status | local wall util | stress util | wire util | allowed statement | blocked statement |",
        "|---:|---|---:|---:|---:|---|---|",
    ]
    for row in boundary.rows:
        lines.append(
            f"| {_load_label(row.claim_load_factor)} | `{row.status}` | "
            f"{_fmt(row.local_wall_buckling_utilization)} | "
            f"{_fmt(row.tube_stress_utilization)} | {_fmt(row.wire_utilization)} | "
            f"{row.allowed_statement} | {row.blocked_statement} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- Internal local-wall pass evidence is useful screening evidence, not a full-wing global buckling pass.",
            "- A 1.5G or 1.75G full-wing pass claim still needs global buckling eigen/FEM evidence with the bracing system included.",
            "- Keep the wording at internal fixed-design modeled limits clear until the Phase30 closure input is qualified.",
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
    outputs = write_full_wing_buckling_claim_boundary_package(
        args.output_dir,
        reference.candidate_id,
        phase15_rows=build_phase15_rows(reference),
        closure_check=build_current_full_wing_buckling_closure_check(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
