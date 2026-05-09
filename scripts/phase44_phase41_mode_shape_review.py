#!/usr/bin/env python3
"""Screen Phase41 first buckling mode shapes without promoting signoff."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.hifi.frd_parser import (  # noqa: E402
    FRDFieldBlock,
    parse_buckle_eigenvalues,
    parse_field_blocks,
    parse_nodal_coordinates,
)
from scripts.phase41_braced_subassembly_fem_evidence import (  # noqa: E402
    BracedSubassemblyFemEvidence,
    load_current_braced_subassembly_fem_evidence,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase44_phase41_mode_shape_review"
ENGINEERING_BOUNDARY = (
    "Phase44 is automated first-mode screening for Phase41 route evidence. It is "
    "not a full-wing pass claim and does not replace manual mode-shape review, "
    "boundary-condition review, mesh/link sensitivity, or detail FEM margins."
)


@dataclass(frozen=True)
class Phase41ModeShapeReviewRow:
    case_id: str
    status: str
    frd_path: str
    dat_path: str
    first_eigen_multiplier: float | None
    mode_block_count: int
    selected_mode_block_index: int | None
    selected_mode_step_number: int | None
    selected_mode_result_set: int | None
    selected_mode_analysis_value: float | None
    node_count: int
    semispan_m: float | None
    max_mode_node_id: int | None
    max_mode_y_m: float | None
    max_mode_magnitude_m: float | None
    root_band_max_magnitude_m: float | None
    tip_band_max_magnitude_m: float | None
    root_to_max_ratio: float | None
    tip_to_max_ratio: float | None
    spar_mean_participation_ratio: float | None
    engineering_read: str
    next_action: str


@dataclass(frozen=True)
class Phase41ModeShapeReview:
    candidate_id: str
    overall_status: str
    row_count: int
    review_required_count: int
    missing_count: int
    engineering_boundary: str
    rows: tuple[Phase41ModeShapeReviewRow, ...]


def build_phase41_mode_shape_review(
    phase41_evidence: BracedSubassemblyFemEvidence,
) -> Phase41ModeShapeReview:
    rows = tuple(_build_row(row) for row in phase41_evidence.rows)
    missing_count = sum(1 for row in rows if row.status != "mode_shape_engineering_review_required")
    review_required_count = sum(
        1 for row in rows if row.status == "mode_shape_engineering_review_required"
    )
    return Phase41ModeShapeReview(
        candidate_id=str(phase41_evidence.candidate_id),
        overall_status=(
            "phase41_mode_shape_review_incomplete"
            if missing_count
            else "phase41_mode_shape_engineering_review_required"
        ),
        row_count=len(rows),
        review_required_count=review_required_count,
        missing_count=missing_count,
        engineering_boundary=ENGINEERING_BOUNDARY,
        rows=rows,
    )


def write_phase41_mode_shape_review_package(
    out_dir: Path,
    phase41_evidence: BracedSubassemblyFemEvidence,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    review = build_phase41_mode_shape_review(phase41_evidence)
    return [
        _write_csv(out_dir / "phase41_mode_shape_review.csv", review),
        _write_json(out_dir / "phase41_mode_shape_review.json", review),
        _write_markdown(out_dir / "phase41_mode_shape_review.md", review),
    ]


def build_current_phase41_mode_shape_review() -> Phase41ModeShapeReview:
    return build_phase41_mode_shape_review(load_current_braced_subassembly_fem_evidence())


def _build_row(phase41_row: Any) -> Phase41ModeShapeReviewRow:
    frd_text = str(getattr(phase41_row, "frd_path", "")).strip()
    dat_text = str(getattr(phase41_row, "dat_path", "")).strip()
    frd_path = Path(frd_text) if frd_text else Path()
    dat_path = Path(dat_text) if dat_text else Path()
    first_lambda = _first_lambda(phase41_row, dat_path)
    if not frd_text:
        return _empty_row(
            phase41_row,
            status="frd_missing",
            first_lambda=first_lambda,
            engineering_read="Phase41 has no FRD path, so the first mode shape cannot be screened.",
            next_action="Run Phase41 with CalculiX and retain the FRD before reviewing the buckling mode.",
        )
    if not frd_path.exists():
        return _empty_row(
            phase41_row,
            status="frd_missing",
            first_lambda=first_lambda,
            engineering_read=f"Phase41 FRD path does not exist: {frd_path}.",
            next_action="Regenerate Phase41 outputs or fix the recorded FRD path before mode review.",
        )
    coords = parse_nodal_coordinates(frd_path)
    blocks = parse_field_blocks(frd_path, "DISP")
    selected_index, selected_block = _select_first_eigenmode_block(blocks, first_lambda)
    if selected_block is None:
        return _empty_row(
            phase41_row,
            status="eigenmode_block_missing",
            first_lambda=first_lambda,
            mode_block_count=len(blocks),
            engineering_read="FRD exists, but no eigenmode DISP block was found after the static/reference block.",
            next_action="Check the CalculiX BUCKLE output request and rerun Phase41 if eigenmode blocks were not written.",
        )
    metrics = _mode_metrics(coords, selected_block.rows)
    if metrics is None:
        return _empty_row(
            phase41_row,
            status="coordinate_displacement_mismatch",
            first_lambda=first_lambda,
            mode_block_count=len(blocks),
            selected_index=selected_index,
            selected_block=selected_block,
            engineering_read="The selected DISP block does not share node ids with the FRD coordinate block.",
            next_action="Inspect the FRD coordinate and displacement blocks before using the mode-shape screen.",
        )
    return Phase41ModeShapeReviewRow(
        case_id=str(getattr(phase41_row, "case_id", "")),
        status="mode_shape_engineering_review_required",
        frd_path=str(frd_path),
        dat_path=str(dat_path) if dat_text else "",
        first_eigen_multiplier=first_lambda,
        mode_block_count=len(blocks),
        selected_mode_block_index=selected_index,
        selected_mode_step_number=selected_block.step_number,
        selected_mode_result_set=selected_block.result_set,
        selected_mode_analysis_value=selected_block.analysis_value,
        node_count=metrics["node_count"],
        semispan_m=metrics["semispan_m"],
        max_mode_node_id=metrics["max_mode_node_id"],
        max_mode_y_m=metrics["max_mode_y_m"],
        max_mode_magnitude_m=metrics["max_mode_magnitude_m"],
        root_band_max_magnitude_m=metrics["root_band_max_magnitude_m"],
        tip_band_max_magnitude_m=metrics["tip_band_max_magnitude_m"],
        root_to_max_ratio=metrics["root_to_max_ratio"],
        tip_to_max_ratio=metrics["tip_to_max_ratio"],
        spar_mean_participation_ratio=metrics["spar_mean_participation_ratio"],
        engineering_read=(
            "Automated mode screening only: the first positive-eigenvalue DISP "
            "block was parsed, but an engineer still needs to inspect the "
            "deformed mode, boundary conditions, mesh/link sensitivity, and "
            "detail load paths before any global buckling pass claim."
        ),
        next_action=(
            "Open the FRD/deformed mode, confirm the first mode is a relevant "
            "global/braced structural mode, then repeat with mesh and link "
            "sensitivity before promoting Phase30 closure evidence."
        ),
    )


def _empty_row(
    phase41_row: Any,
    *,
    status: str,
    first_lambda: float | None,
    mode_block_count: int = 0,
    selected_index: int | None = None,
    selected_block: FRDFieldBlock | None = None,
    engineering_read: str,
    next_action: str,
) -> Phase41ModeShapeReviewRow:
    return Phase41ModeShapeReviewRow(
        case_id=str(getattr(phase41_row, "case_id", "")),
        status=status,
        frd_path=str(getattr(phase41_row, "frd_path", "")),
        dat_path=str(getattr(phase41_row, "dat_path", "")),
        first_eigen_multiplier=first_lambda,
        mode_block_count=mode_block_count,
        selected_mode_block_index=selected_index,
        selected_mode_step_number=(
            selected_block.step_number if selected_block is not None else None
        ),
        selected_mode_result_set=(
            selected_block.result_set if selected_block is not None else None
        ),
        selected_mode_analysis_value=(
            selected_block.analysis_value if selected_block is not None else None
        ),
        node_count=0,
        semispan_m=None,
        max_mode_node_id=None,
        max_mode_y_m=None,
        max_mode_magnitude_m=None,
        root_band_max_magnitude_m=None,
        tip_band_max_magnitude_m=None,
        root_to_max_ratio=None,
        tip_to_max_ratio=None,
        spar_mean_participation_ratio=None,
        engineering_read=engineering_read,
        next_action=next_action,
    )


def _select_first_eigenmode_block(
    blocks: tuple[FRDFieldBlock, ...],
    first_lambda: float | None,
) -> tuple[int | None, FRDFieldBlock | None]:
    positive_blocks = [
        (idx, block)
        for idx, block in enumerate(blocks)
        if block.analysis_value is not None and float(block.analysis_value) > 0.0
    ]
    if positive_blocks and first_lambda is not None:
        return min(
            positive_blocks,
            key=lambda item: abs(float(item[1].analysis_value) - float(first_lambda)),
        )
    if positive_blocks:
        return positive_blocks[0]
    if len(blocks) > 1:
        return 1, blocks[1]
    return None, None


def _mode_metrics(
    coords: np.ndarray,
    disp: np.ndarray,
) -> dict[str, Any] | None:
    coord_by_id = {int(row[0]): row[1:4] for row in coords}
    disp_by_id = {int(row[0]): row[1:4] for row in disp}
    node_ids = sorted(set(coord_by_id).intersection(disp_by_id))
    if not node_ids:
        return None
    xyz = np.asarray([coord_by_id[node_id] for node_id in node_ids], dtype=float)
    uvw = np.asarray([disp_by_id[node_id] for node_id in node_ids], dtype=float)
    magnitudes = np.linalg.norm(uvw, axis=1)
    max_index = int(np.argmax(magnitudes))
    max_mag = float(magnitudes[max_index])
    ys = xyz[:, 1]
    xs = xyz[:, 0]
    y_min = float(np.min(ys))
    y_max = float(np.max(ys))
    semispan = y_max - y_min
    root_band = max(0.02 * semispan, 1.0e-9)
    root_max = float(np.max(magnitudes[ys <= y_min + root_band]))
    tip_max = float(np.max(magnitudes[ys >= y_max - root_band]))
    return {
        "node_count": len(node_ids),
        "semispan_m": _round(semispan),
        "max_mode_node_id": int(node_ids[max_index]),
        "max_mode_y_m": _round(float(ys[max_index])),
        "max_mode_magnitude_m": _round(max_mag),
        "root_band_max_magnitude_m": _round(root_max),
        "tip_band_max_magnitude_m": _round(tip_max),
        "root_to_max_ratio": _ratio(root_max, max_mag),
        "tip_to_max_ratio": _ratio(tip_max, max_mag),
        "spar_mean_participation_ratio": _spar_mean_participation_ratio(xs, magnitudes),
    }


def _spar_mean_participation_ratio(xs: np.ndarray, magnitudes: np.ndarray) -> float | None:
    if len(xs) < 2:
        return None
    median_x = float(np.median(xs))
    lower = magnitudes[xs <= median_x]
    upper = magnitudes[xs > median_x]
    if lower.size == 0 or upper.size == 0:
        return None
    lower_mean = float(np.mean(lower))
    upper_mean = float(np.mean(upper))
    return _ratio(min(lower_mean, upper_mean), max(lower_mean, upper_mean))


def _first_lambda(phase41_row: Any, dat_path: Path) -> float | None:
    value = getattr(phase41_row, "first_eigen_multiplier", None)
    if value not in (None, ""):
        return float(value)
    if dat_path.exists():
        eigenvalues = parse_buckle_eigenvalues(dat_path)
        if eigenvalues:
            return float(eigenvalues[0])
    return None


def _ratio(numerator: float, denominator: float) -> float | None:
    if abs(float(denominator)) <= 1.0e-15:
        return None
    return _round(float(numerator) / float(denominator))


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _write_csv(path: Path, review: Phase41ModeShapeReview) -> Path:
    fields = list(asdict(review.rows[0]).keys()) if review.rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in review.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, review: Phase41ModeShapeReview) -> Path:
    path.write_text(
        json.dumps(asdict(review), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, review: Phase41ModeShapeReview) -> Path:
    lines = [
        "# Phase41 Mode Shape Review",
        "",
        f"Candidate: `{review.candidate_id}`",
        f"Overall status: `{review.overall_status}`",
        "",
        review.engineering_boundary,
        "",
        f"- rows: `{review.row_count}`",
        f"- review required rows: `{review.review_required_count}`",
        f"- missing/incomplete rows: `{review.missing_count}`",
        "",
        "| case | status | lambda 1 | mode block | max node | max y m | tip/max | root/max | spar balance |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in review.rows:
        lines.append(
            f"| {row.case_id} | `{row.status}` | {_fmt(row.first_eigen_multiplier)} | "
            f"{_fmt(row.selected_mode_block_index)} | {_fmt(row.max_mode_node_id)} | "
            f"{_fmt(row.max_mode_y_m)} | {_fmt(row.tip_to_max_ratio)} | "
            f"{_fmt(row.root_to_max_ratio)} | {_fmt(row.spar_mean_participation_ratio)} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- This is a parseable first-mode screen, not a full-wing pass claim.",
            "- A human review still needs to confirm mode identity, boundary conditions, mesh sensitivity, and rib/link modeling.",
            "- Local wire-attach, root-joint, termination, and rib attachment margins remain outside this report.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _fmt(value: float | int | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    outputs = write_phase41_mode_shape_review_package(
        args.output_dir,
        load_current_braced_subassembly_fem_evidence(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
