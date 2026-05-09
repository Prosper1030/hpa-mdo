#!/usr/bin/env python3
"""Screen wire-attach local detail concepts against force and moment demand."""
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

from scripts.phase34_wire_attach_load_decomposition import (  # noqa: E402
    build_current_wire_attach_load_decomposition,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase50_wire_attach_detail_feasibility_screen"


@dataclass(frozen=True)
class WireAttachDetailFeasibilityRow:
    concept_id: str
    status: str
    closes_wire_attach_margin: bool
    required_resultant_load_n: float
    required_spanwise_load_n: float | None
    required_transverse_load_n: float | None
    required_local_moment_n_m: float | None
    attach_ring_or_lug_allowable_load_n: float | None
    attach_ring_or_lug_margin_n: float | None
    bonded_load_path_allowable_load_n: float | None
    bonded_load_path_margin_n: float | None
    insert_pullout_bearing_allowable_load_n: float | None
    insert_pullout_bearing_margin_n: float | None
    local_tube_wall_crushing_allowable_load_n: float | None
    local_tube_wall_crushing_margin_n: float | None
    local_moment_allowable_n_m: float | None
    local_moment_margin_n_m: float | None
    worst_margin_n_equivalent: float | None
    traceability_status: str
    evidence_type: str
    source: str
    engineering_note: str


@dataclass(frozen=True)
class WireAttachDetailFeasibilityScreen:
    candidate_id: str
    overall_status: str
    local_moment_status: str
    required_resultant_load_n: float
    required_spanwise_load_n: float | None
    required_transverse_load_n: float | None
    required_local_moment_n_m: float | None
    concept_count: int
    positive_input_concept_count: int
    negative_margin_concept_count: int
    missing_input_concept_count: int
    traceability_gap_concept_count: int
    rows: tuple[WireAttachDetailFeasibilityRow, ...]


def build_wire_attach_detail_feasibility_screen(
    wire_attach_load_decomposition: Any,
    *,
    attach_detail_concepts: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> WireAttachDetailFeasibilityScreen:
    required_resultant = _attr_float(
        wire_attach_load_decomposition,
        "max_resultant_design_load_n",
    )
    if required_resultant is None:
        raise ValueError("wire_attach_load_decomposition must include max_resultant_design_load_n.")
    rows = tuple(getattr(wire_attach_load_decomposition, "rows", ()))
    required_spanwise = _component_design_load_max(rows, "spanwise_y")
    required_transverse = _component_design_load_max(rows, "transverse_xz")
    required_local_moment = _attr_float(
        wire_attach_load_decomposition,
        "max_resultant_design_local_moment_n_m",
    )
    local_moment_status = (
        "attach_eccentricity_defined"
        if required_local_moment is not None
        else "attach_eccentricity_missing"
    )
    if not attach_detail_concepts:
        screen_rows = (
            _missing_input_row(
                required_resultant_load_n=required_resultant,
                required_spanwise_load_n=required_spanwise,
                required_transverse_load_n=required_transverse,
                required_local_moment_n_m=required_local_moment,
            ),
        )
    else:
        screen_rows = tuple(
            _concept_row(
                row,
                required_resultant_load_n=required_resultant,
                required_spanwise_load_n=required_spanwise,
                required_transverse_load_n=required_transverse,
                required_local_moment_n_m=required_local_moment,
                local_moment_status=local_moment_status,
            )
            for row in attach_detail_concepts
        )
    positive_count = sum(1 for row in screen_rows if row.status == "detail_positive_input_check_only")
    negative_count = sum(1 for row in screen_rows if row.status == "margin_negative")
    missing_count = sum(
        1
        for row in screen_rows
        if row.status in {"detail_geometry_and_allowables_missing", "detail_allowables_missing"}
    )
    traceability_gap_count = sum(
        1 for row in screen_rows if row.status == "detail_traceability_missing"
    )
    all_positive = screen_rows and positive_count == len(screen_rows)
    return WireAttachDetailFeasibilityScreen(
        candidate_id=str(getattr(wire_attach_load_decomposition, "candidate_id", "unknown")),
        overall_status=(
            "wire_attach_detail_inputs_pass_not_fem_signoff"
            if all_positive
            else "wire_attach_detail_feasibility_not_closed"
        ),
        local_moment_status=local_moment_status,
        required_resultant_load_n=required_resultant,
        required_spanwise_load_n=required_spanwise,
        required_transverse_load_n=required_transverse,
        required_local_moment_n_m=required_local_moment,
        concept_count=len(screen_rows),
        positive_input_concept_count=positive_count,
        negative_margin_concept_count=negative_count,
        missing_input_concept_count=missing_count,
        traceability_gap_concept_count=traceability_gap_count,
        rows=screen_rows,
    )


def write_wire_attach_detail_feasibility_screen_package(
    out_dir: Path,
    wire_attach_load_decomposition: Any,
    *,
    attach_detail_concepts: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    screen = build_wire_attach_detail_feasibility_screen(
        wire_attach_load_decomposition,
        attach_detail_concepts=attach_detail_concepts,
    )
    return [
        _write_template(out_dir / "wire_attach_detail_inputs_template.csv"),
        _write_csv(out_dir / "wire_attach_detail_feasibility_screen.csv", screen),
        _write_json(out_dir / "wire_attach_detail_feasibility_screen.json", screen),
        _write_markdown(out_dir / "wire_attach_detail_feasibility_screen.md", screen),
    ]


def build_current_wire_attach_detail_feasibility_screen() -> WireAttachDetailFeasibilityScreen:
    return build_wire_attach_detail_feasibility_screen(
        build_current_wire_attach_load_decomposition(),
        attach_detail_concepts=(),
    )


def _concept_row(
    concept: dict[str, Any],
    *,
    required_resultant_load_n: float,
    required_spanwise_load_n: float | None,
    required_transverse_load_n: float | None,
    required_local_moment_n_m: float | None,
    local_moment_status: str,
) -> WireAttachDetailFeasibilityRow:
    concept_id = str(concept.get("concept_id", "")).strip()
    ring_allowable = _dict_float(concept, "attach_ring_or_lug_allowable_load_n")
    bond_allowable = _dict_float(concept, "bonded_load_path_allowable_load_n")
    insert_allowable = _dict_float(concept, "insert_pullout_bearing_allowable_load_n")
    tube_allowable = _dict_float(concept, "local_tube_wall_crushing_allowable_load_n")
    moment_allowable = _dict_float(concept, "local_moment_allowable_n_m")
    ring_margin = _margin(ring_allowable, required_resultant_load_n)
    bond_margin = _margin(bond_allowable, required_resultant_load_n)
    insert_margin = _margin(insert_allowable, required_spanwise_load_n)
    tube_margin = _margin(tube_allowable, required_transverse_load_n)
    moment_margin = _margin(moment_allowable, required_local_moment_n_m)
    margins = [
        value
        for value in (ring_margin, bond_margin, insert_margin, tube_margin, moment_margin)
        if value is not None
    ]
    traceability_status = _traceability_status(
        concept_id=concept_id,
        evidence_type=str(concept.get("evidence_type", "")).strip(),
        source=str(concept.get("source", "")).strip(),
    )
    status = _status(
        margins=(ring_margin, bond_margin, insert_margin, tube_margin, moment_margin),
        traceability_status=traceability_status,
        local_moment_status=local_moment_status,
    )
    return WireAttachDetailFeasibilityRow(
        concept_id=concept_id or "unnamed_wire_attach_detail_concept",
        status=status,
        closes_wire_attach_margin=False,
        required_resultant_load_n=required_resultant_load_n,
        required_spanwise_load_n=required_spanwise_load_n,
        required_transverse_load_n=required_transverse_load_n,
        required_local_moment_n_m=required_local_moment_n_m,
        attach_ring_or_lug_allowable_load_n=ring_allowable,
        attach_ring_or_lug_margin_n=ring_margin,
        bonded_load_path_allowable_load_n=bond_allowable,
        bonded_load_path_margin_n=bond_margin,
        insert_pullout_bearing_allowable_load_n=insert_allowable,
        insert_pullout_bearing_margin_n=insert_margin,
        local_tube_wall_crushing_allowable_load_n=tube_allowable,
        local_tube_wall_crushing_margin_n=tube_margin,
        local_moment_allowable_n_m=moment_allowable,
        local_moment_margin_n_m=moment_margin,
        worst_margin_n_equivalent=min(margins) if margins else None,
        traceability_status=traceability_status,
        evidence_type=str(concept.get("evidence_type", "")).strip(),
        source=str(concept.get("source", "")).strip(),
        engineering_note=(
            "Positive rows are detail input checks only, not wire-attach local FEM signoff; "
            "stress concentration, bond peel, bearing distribution, fatigue, installation, and inspection remain open."
        ),
    )


def _missing_input_row(
    *,
    required_resultant_load_n: float,
    required_spanwise_load_n: float | None,
    required_transverse_load_n: float | None,
    required_local_moment_n_m: float | None,
) -> WireAttachDetailFeasibilityRow:
    return WireAttachDetailFeasibilityRow(
        concept_id="wire_attach_detail_concept_input_required",
        status="detail_geometry_and_allowables_missing",
        closes_wire_attach_margin=False,
        required_resultant_load_n=required_resultant_load_n,
        required_spanwise_load_n=required_spanwise_load_n,
        required_transverse_load_n=required_transverse_load_n,
        required_local_moment_n_m=required_local_moment_n_m,
        attach_ring_or_lug_allowable_load_n=None,
        attach_ring_or_lug_margin_n=None,
        bonded_load_path_allowable_load_n=None,
        bonded_load_path_margin_n=None,
        insert_pullout_bearing_allowable_load_n=None,
        insert_pullout_bearing_margin_n=None,
        local_tube_wall_crushing_allowable_load_n=None,
        local_tube_wall_crushing_margin_n=None,
        local_moment_allowable_n_m=None,
        local_moment_margin_n_m=None,
        worst_margin_n_equivalent=None,
        traceability_status="concept_input_missing",
        evidence_type="",
        source="",
        engineering_note=(
            "Provide attach eccentricity, lug/ring, bond, insert, local tube-wall, "
            "and local moment allowables before the wire-attach detail can be screened."
        ),
    )


def _status(
    *,
    margins: tuple[float | None, ...],
    traceability_status: str,
    local_moment_status: str,
) -> str:
    if local_moment_status != "attach_eccentricity_defined":
        return "attach_eccentricity_missing"
    if any(margin is None for margin in margins):
        return "detail_allowables_missing"
    if traceability_status != "traceable":
        return "detail_traceability_missing"
    if any(margin < 0.0 for margin in margins):
        return "margin_negative"
    return "detail_positive_input_check_only"


def _traceability_status(
    *,
    concept_id: str,
    evidence_type: str,
    source: str,
) -> str:
    if not concept_id:
        return "concept_id_missing"
    if not evidence_type:
        return "evidence_type_missing"
    if not source:
        return "source_missing"
    return "traceable"


def _component_design_load_max(rows: tuple[Any, ...], component_key: str) -> float | None:
    values = [
        _attr_float(row, "design_load_n")
        for row in rows
        if str(getattr(row, "component_key", "")) == component_key
    ]
    finite_values = [value for value in values if value is not None]
    return max(finite_values) if finite_values else None


def _margin(provided: float | None, required: float | None) -> float | None:
    if provided is None or required is None:
        return None
    return provided - required


def _attr_float(obj: Any, name: str) -> float | None:
    value = getattr(obj, name, None)
    if value is None or value == "":
        return None
    return float(value)


def _dict_float(row: dict[str, Any], name: str) -> float | None:
    value = row.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.4f}"


def _write_template(path: Path) -> Path:
    fields = [
        "concept_id",
        "attach_ring_or_lug_allowable_load_n",
        "bonded_load_path_allowable_load_n",
        "insert_pullout_bearing_allowable_load_n",
        "local_tube_wall_crushing_allowable_load_n",
        "local_moment_allowable_n_m",
        "evidence_type",
        "source",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow({field: "" for field in fields})
    return path


def _write_csv(path: Path, screen: WireAttachDetailFeasibilityScreen) -> Path:
    fields = list(asdict(screen.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in screen.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, screen: WireAttachDetailFeasibilityScreen) -> Path:
    path.write_text(
        json.dumps(asdict(screen), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, screen: WireAttachDetailFeasibilityScreen) -> Path:
    lines = [
        "# Wire Attach Detail Feasibility Screen",
        "",
        f"Candidate: `{screen.candidate_id}`",
        f"Overall status: `{screen.overall_status}`",
        "",
        "This is not wire-attach local FEM signoff.",
        "",
        f"- local moment status: `{screen.local_moment_status}`",
        f"- required resultant load: `{screen.required_resultant_load_n:.4f} N`",
        f"- required spanwise load: `{_fmt(screen.required_spanwise_load_n)} N`",
        f"- required transverse load: `{_fmt(screen.required_transverse_load_n)} N`",
        f"- required local moment: `{_fmt(screen.required_local_moment_n_m)} N*m`",
        f"- missing input concepts: `{screen.missing_input_concept_count}`",
        "",
        "| concept | status | ring margin N | bond margin N | insert margin N | tube wall margin N | moment margin N*m | traceability |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in screen.rows:
        lines.append(
            f"| `{row.concept_id}` | `{row.status}` | "
            f"{_fmt(row.attach_ring_or_lug_margin_n)} | "
            f"{_fmt(row.bonded_load_path_margin_n)} | "
            f"{_fmt(row.insert_pullout_bearing_margin_n)} | "
            f"{_fmt(row.local_tube_wall_crushing_margin_n)} | "
            f"{_fmt(row.local_moment_margin_n_m)} | `{row.traceability_status}` |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- A positive detail input row is only an input screen.",
            "- Wire-attach signoff still needs lug/ring stress, bond peel/shear, insert pullout/bearing, local tube-wall, fatigue, and installation evidence.",
            "- Missing attach eccentricity means the local moment path is not defined.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    outputs = write_wire_attach_detail_feasibility_screen_package(
        args.output_dir,
        build_current_wire_attach_load_decomposition(),
        attach_detail_concepts=(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
