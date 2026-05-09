#!/usr/bin/env python3
"""Compare Phase41 braced links with Phase24 rib-spacing requirements."""
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

from scripts.phase22_bracing_sensitivity import build_current_candidate_model  # noqa: E402
from scripts.phase24_rib_spacing_requirements import (  # noqa: E402
    build_current_rib_spacing_requirements,
)
from scripts.phase41_braced_subassembly_fem_evidence import (  # noqa: E402
    load_current_braced_subassembly_fem_evidence,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase45_phase41_rib_spacing_link_review"
ENGINEERING_BOUNDARY = (
    "Phase45 checks whether the Phase41 braced-subassembly link grid is consistent "
    "with the nominal rib-bay length assumption. It is not physical rib stiffness "
    "or attachment signoff."
)


@dataclass(frozen=True)
class Phase41RibSpacingLinkReviewRow:
    case_id: str
    status: str
    claim_load_factor: float
    includes_finite_ribs: bool
    phase41_link_node_count: int
    model_link_node_count: int
    model_link_count_matches_phase41: bool
    model_bracing_station_count: int
    recommended_station_count: int
    station_count_delta: int
    target_bay_m: float
    max_model_link_subbay_m: float | None
    max_recommended_subbay_m: float | None
    link_spacing_margin_m: float | None
    phase30_closure_status: str
    engineering_read: str
    next_action: str


@dataclass(frozen=True)
class Phase41RibSpacingLinkReview:
    candidate_id: str
    overall_status: str
    row_count: int
    nominal_spacing_met_count: int
    physical_signoff_count: int
    engineering_boundary: str
    rows: tuple[Phase41RibSpacingLinkReviewRow, ...]


def build_phase41_rib_spacing_link_review(
    phase41_evidence: Any,
    *,
    spacing_requirements: Any,
    model: Any,
) -> Phase41RibSpacingLinkReview:
    link_indices = _phase41_link_indices(model)
    link_subbays = _link_subbays_m(model, link_indices)
    rows = tuple(
        _build_row(
            phase41_row,
            spacing_requirements=spacing_requirements,
            link_indices=link_indices,
            link_subbays=link_subbays,
        )
        for phase41_row in getattr(phase41_evidence, "rows", ())
    )
    nominal_count = sum(
        1
        for row in rows
        if row.status == "phase41_link_spacing_matches_nominal_not_physical_signoff"
    )
    return Phase41RibSpacingLinkReview(
        candidate_id=str(getattr(phase41_evidence, "candidate_id", "")),
        overall_status=(
            "phase41_rib_spacing_model_matches_nominal_not_physical_signoff"
            if rows and nominal_count == len(rows)
            else "phase41_rib_spacing_model_review_required"
        ),
        row_count=len(rows),
        nominal_spacing_met_count=nominal_count,
        physical_signoff_count=0,
        engineering_boundary=ENGINEERING_BOUNDARY,
        rows=rows,
    )


def write_phase41_rib_spacing_link_review_package(
    out_dir: Path,
    phase41_evidence: Any,
    *,
    spacing_requirements: Any,
    model: Any,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    review = build_phase41_rib_spacing_link_review(
        phase41_evidence,
        spacing_requirements=spacing_requirements,
        model=model,
    )
    return [
        _write_csv(out_dir / "phase41_rib_spacing_link_review.csv", review),
        _write_json(out_dir / "phase41_rib_spacing_link_review.json", review),
        _write_markdown(out_dir / "phase41_rib_spacing_link_review.md", review),
    ]


def build_current_phase41_rib_spacing_link_review() -> Phase41RibSpacingLinkReview:
    return build_phase41_rib_spacing_link_review(
        load_current_braced_subassembly_fem_evidence(),
        spacing_requirements=build_current_rib_spacing_requirements(),
        model=build_current_candidate_model(),
    )


def _build_row(
    phase41_row: Any,
    *,
    spacing_requirements: Any,
    link_indices: tuple[int, ...],
    link_subbays: tuple[float, ...],
) -> Phase41RibSpacingLinkReviewRow:
    target_bay = float(getattr(spacing_requirements, "target_bay_m", 0.0))
    max_link_subbay = max(link_subbays) if link_subbays else None
    phase41_link_count = int(getattr(phase41_row, "link_node_count", 0))
    model_link_count = len(link_indices)
    count_matches = phase41_link_count == model_link_count
    includes_finite_ribs = bool(getattr(phase41_row, "includes_finite_ribs", False))
    status = _status(
        includes_finite_ribs=includes_finite_ribs,
        link_count_matches=count_matches,
        max_link_subbay_m=max_link_subbay,
        target_bay_m=target_bay,
    )
    return Phase41RibSpacingLinkReviewRow(
        case_id=str(getattr(phase41_row, "case_id", "")),
        status=status,
        claim_load_factor=float(getattr(phase41_row, "claim_load_factor", 0.0)),
        includes_finite_ribs=includes_finite_ribs,
        phase41_link_node_count=phase41_link_count,
        model_link_node_count=model_link_count,
        model_link_count_matches_phase41=count_matches,
        model_bracing_station_count=model_link_count + 2 if link_subbays else 0,
        recommended_station_count=int(
            getattr(spacing_requirements, "recommended_station_count", 0)
        ),
        station_count_delta=(
            model_link_count
            + 2
            - int(getattr(spacing_requirements, "recommended_station_count", 0))
            if link_subbays
            else 0
        ),
        target_bay_m=target_bay,
        max_model_link_subbay_m=_round(max_link_subbay),
        max_recommended_subbay_m=_round(
            _optional_float(getattr(spacing_requirements, "max_recommended_subbay_m", None))
        ),
        link_spacing_margin_m=_round(
            None if max_link_subbay is None else target_bay - max_link_subbay
        ),
        phase30_closure_status=str(getattr(phase41_row, "phase30_closure_status", "")),
        engineering_read=_engineering_read(status),
        next_action=_next_action(status),
    )


def _phase41_link_indices(model: Any) -> tuple[int, ...]:
    node_count = len(getattr(model, "y_nodes_m", ()))
    raw_indices = (
        *tuple(getattr(model, "joint_node_indices", ())),
        *tuple(getattr(model, "dense_link_node_indices", ())),
        *tuple(getattr(model, "wire_node_indices", ())),
    )
    return tuple(sorted({int(idx) for idx in raw_indices if 0 < int(idx) < node_count - 1}))


def _link_subbays_m(model: Any, link_indices: tuple[int, ...]) -> tuple[float, ...]:
    y_nodes = np.asarray(getattr(model, "y_nodes_m", ()), dtype=float)
    if y_nodes.size < 2:
        return ()
    stations = [float(y_nodes[0])]
    stations.extend(float(y_nodes[idx]) for idx in link_indices)
    stations.append(float(y_nodes[-1]))
    stations = sorted(stations)
    return tuple(float(end - start) for start, end in zip(stations, stations[1:]))


def _status(
    *,
    includes_finite_ribs: bool,
    link_count_matches: bool,
    max_link_subbay_m: float | None,
    target_bay_m: float,
) -> str:
    if not includes_finite_ribs:
        return "phase41_finite_rib_links_missing"
    if not link_count_matches:
        return "phase41_link_count_mismatch_review_required"
    if max_link_subbay_m is None:
        return "phase41_link_spacing_missing"
    if max_link_subbay_m <= target_bay_m + 1.0e-9:
        return "phase41_link_spacing_matches_nominal_not_physical_signoff"
    return "phase41_link_spacing_exceeds_nominal"


def _engineering_read(status: str) -> str:
    if status == "phase41_link_spacing_matches_nominal_not_physical_signoff":
        return (
            "Phase41 link spacing is consistent with the nominal rib-bay length, "
            "but it does not prove physical rib stiffness, rib shear/cap strength, "
            "bond quality, or spar attachment margins."
        )
    if status == "phase41_link_count_mismatch_review_required":
        return "Phase41 recorded link count does not match the rebuilt current model link grid."
    if status == "phase41_link_spacing_exceeds_nominal":
        return "Phase41 link grid exceeds the nominal rib-bay spacing assumption."
    return "Phase41 link spacing evidence is missing or incomplete."


def _next_action(status: str) -> str:
    if status == "phase41_link_spacing_matches_nominal_not_physical_signoff":
        return (
            "Use Phase41 only as model-spacing evidence; close the physical rib "
            "assumption with finite rib stiffness and station-by-station attach margins."
        )
    return "Review Phase41 link construction before using it as rib-spacing evidence."


def _write_csv(path: Path, review: Phase41RibSpacingLinkReview) -> Path:
    fields = list(asdict(review.rows[0]).keys()) if review.rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in review.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, review: Phase41RibSpacingLinkReview) -> Path:
    path.write_text(
        json.dumps(asdict(review), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, review: Phase41RibSpacingLinkReview) -> Path:
    lines = [
        "# Phase41 Rib Spacing Link Review",
        "",
        f"Candidate: `{review.candidate_id}`",
        f"Overall status: `{review.overall_status}`",
        "",
        review.engineering_boundary,
        "",
        f"- rows: `{review.row_count}`",
        f"- nominal spacing met rows: `{review.nominal_spacing_met_count}`",
        f"- physical signoff rows: `{review.physical_signoff_count}`",
        "",
        "| case | status | links | stations | target m | max model subbay m | margin m | station delta |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in review.rows:
        lines.append(
            f"| {row.case_id} | `{row.status}` | {row.model_link_node_count} | "
            f"{row.model_bracing_station_count} | {_fmt(row.target_bay_m)} | "
            f"{_fmt(row.max_model_link_subbay_m)} | {_fmt(row.link_spacing_margin_m)} | "
            f"{row.station_count_delta} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- This verifies model link spacing only; it is not physical rib stiffness or attachment signoff.",
            "- A nominal 0.30 m model link grid still needs rib shear, cap, bond, insert, and spar-attach allowables.",
            "- Station-count agreement is useful traceability, but physical ribs must still be placed and sized.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    outputs = write_phase41_rib_spacing_link_review_package(
        args.output_dir,
        load_current_braced_subassembly_fem_evidence(),
        spacing_requirements=build_current_rib_spacing_requirements(),
        model=build_current_candidate_model(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
