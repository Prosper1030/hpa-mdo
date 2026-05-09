#!/usr/bin/env python3
"""Screen root-joint concept geometry and allowables against root moment demand."""
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

from scripts.phase35_root_joint_load_envelope import (  # noqa: E402
    build_current_root_joint_load_envelope,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase48_root_joint_detail_feasibility_screen"


@dataclass(frozen=True)
class RootJointDetailFeasibilityRow:
    concept_id: str
    status: str
    closes_root_joint_margin: bool
    effective_couple_arm_m: float | None
    required_couple_force_n: float | None
    fitting_or_clamp_allowable_force_n: float | None
    fitting_or_clamp_margin_n: float | None
    bonded_joint_allowable_force_n: float | None
    bonded_joint_margin_n: float | None
    insert_allowable_force_n: float | None
    insert_margin_n: float | None
    tube_wall_bearing_allowable_force_n: float | None
    tube_wall_bearing_margin_n: float | None
    worst_margin_n: float | None
    traceability_status: str
    evidence_type: str
    source: str
    engineering_note: str


@dataclass(frozen=True)
class RootJointDetailFeasibilityScreen:
    candidate_id: str
    overall_status: str
    design_root_bending_moment_n_m: float
    envelope_worst_couple_force_n: float | None
    envelope_worst_couple_case: str
    concept_count: int
    positive_input_concept_count: int
    negative_margin_concept_count: int
    missing_input_concept_count: int
    traceability_gap_concept_count: int
    rows: tuple[RootJointDetailFeasibilityRow, ...]


def build_root_joint_detail_feasibility_screen(
    root_joint_load_envelope: Any,
    *,
    root_joint_concepts: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> RootJointDetailFeasibilityScreen:
    design_moment = _attr_float(
        root_joint_load_envelope,
        "design_root_bending_moment_n_m",
    )
    if design_moment is None:
        raise ValueError("root_joint_load_envelope must include design_root_bending_moment_n_m.")
    worst_force, worst_case = _max_root_couple_row(
        tuple(getattr(root_joint_load_envelope, "rows", ()))
    )
    if not root_joint_concepts:
        rows = (_missing_input_row(worst_force),)
    else:
        rows = tuple(_concept_row(row, design_moment=design_moment) for row in root_joint_concepts)
    positive_count = sum(1 for row in rows if row.status == "concept_positive_input_check_only")
    negative_count = sum(1 for row in rows if row.status == "margin_negative")
    missing_count = sum(
        1
        for row in rows
        if row.status
        in {"concept_geometry_and_allowables_missing", "concept_allowables_missing"}
    )
    traceability_gap_count = sum(
        1 for row in rows if row.status == "concept_traceability_missing"
    )
    all_positive = rows and positive_count == len(rows)
    return RootJointDetailFeasibilityScreen(
        candidate_id=str(getattr(root_joint_load_envelope, "candidate_id", "unknown")),
        overall_status=(
            "root_joint_concept_inputs_pass_not_fem_signoff"
            if all_positive
            else "root_joint_detail_feasibility_not_closed"
        ),
        design_root_bending_moment_n_m=float(design_moment),
        envelope_worst_couple_force_n=worst_force,
        envelope_worst_couple_case=worst_case,
        concept_count=len(rows),
        positive_input_concept_count=positive_count,
        negative_margin_concept_count=negative_count,
        missing_input_concept_count=missing_count,
        traceability_gap_concept_count=traceability_gap_count,
        rows=rows,
    )


def write_root_joint_detail_feasibility_screen_package(
    out_dir: Path,
    root_joint_load_envelope: Any,
    *,
    root_joint_concepts: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    screen = build_root_joint_detail_feasibility_screen(
        root_joint_load_envelope,
        root_joint_concepts=root_joint_concepts,
    )
    return [
        _write_template(out_dir / "root_joint_detail_concept_inputs_template.csv"),
        _write_csv(out_dir / "root_joint_detail_feasibility_screen.csv", screen),
        _write_json(out_dir / "root_joint_detail_feasibility_screen.json", screen),
        _write_markdown(out_dir / "root_joint_detail_feasibility_screen.md", screen),
    ]


def build_current_root_joint_detail_feasibility_screen() -> RootJointDetailFeasibilityScreen:
    return build_root_joint_detail_feasibility_screen(
        build_current_root_joint_load_envelope(),
        root_joint_concepts=(),
    )


def _concept_row(
    concept: dict[str, Any],
    *,
    design_moment: float,
) -> RootJointDetailFeasibilityRow:
    concept_id = str(concept.get("concept_id", "")).strip()
    arm_m = _dict_float(concept, "effective_couple_arm_m")
    if arm_m is not None and arm_m <= 0.0:
        raise ValueError("effective_couple_arm_m must be positive.")
    required_force = None if arm_m is None else design_moment / arm_m
    fitting_allowable = _dict_float(concept, "fitting_or_clamp_allowable_force_n")
    bond_allowable = _dict_float(concept, "bonded_joint_allowable_force_n")
    insert_allowable = _dict_float(concept, "insert_allowable_force_n")
    tube_allowable = _dict_float(concept, "tube_wall_bearing_allowable_force_n")
    fitting_margin = _margin(fitting_allowable, required_force)
    bond_margin = _margin(bond_allowable, required_force)
    insert_margin = _margin(insert_allowable, required_force)
    tube_margin = _margin(tube_allowable, required_force)
    margins = [
        value
        for value in (fitting_margin, bond_margin, insert_margin, tube_margin)
        if value is not None
    ]
    traceability_status = _traceability_status(
        concept_id=concept_id,
        evidence_type=str(concept.get("evidence_type", "")).strip(),
        source=str(concept.get("source", "")).strip(),
    )
    status = _status(
        required_force=required_force,
        margins=(fitting_margin, bond_margin, insert_margin, tube_margin),
        traceability_status=traceability_status,
    )
    return RootJointDetailFeasibilityRow(
        concept_id=concept_id or "unnamed_root_joint_concept",
        status=status,
        closes_root_joint_margin=False,
        effective_couple_arm_m=arm_m,
        required_couple_force_n=required_force,
        fitting_or_clamp_allowable_force_n=fitting_allowable,
        fitting_or_clamp_margin_n=fitting_margin,
        bonded_joint_allowable_force_n=bond_allowable,
        bonded_joint_margin_n=bond_margin,
        insert_allowable_force_n=insert_allowable,
        insert_margin_n=insert_margin,
        tube_wall_bearing_allowable_force_n=tube_allowable,
        tube_wall_bearing_margin_n=tube_margin,
        worst_margin_n=min(margins) if margins else None,
        traceability_status=traceability_status,
        evidence_type=str(concept.get("evidence_type", "")).strip(),
        source=str(concept.get("source", "")).strip(),
        engineering_note=(
            "Positive rows are concept input checks only, not root-joint FEM signoff; "
            "fatigue, peel, bearing distribution, clamp preload, installation, and inspection remain open."
        ),
    )


def _missing_input_row(
    envelope_worst_couple_force_n: float | None,
) -> RootJointDetailFeasibilityRow:
    return RootJointDetailFeasibilityRow(
        concept_id="root_joint_concept_input_required",
        status="concept_geometry_and_allowables_missing",
        closes_root_joint_margin=False,
        effective_couple_arm_m=None,
        required_couple_force_n=envelope_worst_couple_force_n,
        fitting_or_clamp_allowable_force_n=None,
        fitting_or_clamp_margin_n=None,
        bonded_joint_allowable_force_n=None,
        bonded_joint_margin_n=None,
        insert_allowable_force_n=None,
        insert_margin_n=None,
        tube_wall_bearing_allowable_force_n=None,
        tube_wall_bearing_margin_n=None,
        worst_margin_n=None,
        traceability_status="concept_input_missing",
        evidence_type="",
        source="",
        engineering_note=(
            "Provide actual root fitting geometry, effective couple arm, and clamp/bond/"
            "insert/tube-wall allowables before root-joint margin can be screened."
        ),
    )


def _status(
    *,
    required_force: float | None,
    margins: tuple[float | None, ...],
    traceability_status: str,
) -> str:
    if required_force is None or any(margin is None for margin in margins):
        return "concept_allowables_missing"
    if traceability_status != "traceable":
        return "concept_traceability_missing"
    if any(margin < 0.0 for margin in margins):
        return "margin_negative"
    return "concept_positive_input_check_only"


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


def _max_root_couple_row(rows: tuple[Any, ...]) -> tuple[float | None, str]:
    values = [
        (
            _attr_float(row, "required_couple_force_n"),
            str(getattr(row, "load_case_key", "unknown")),
        )
        for row in rows
        if _attr_float(row, "required_couple_force_n") is not None
    ]
    return max(values, key=lambda value: value[0] or float("-inf")) if values else (None, "n/a")


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
        "effective_couple_arm_m",
        "fitting_or_clamp_allowable_force_n",
        "bonded_joint_allowable_force_n",
        "insert_allowable_force_n",
        "tube_wall_bearing_allowable_force_n",
        "evidence_type",
        "source",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow({field: "" for field in fields})
    return path


def _write_csv(path: Path, screen: RootJointDetailFeasibilityScreen) -> Path:
    fields = list(asdict(screen.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in screen.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, screen: RootJointDetailFeasibilityScreen) -> Path:
    path.write_text(
        json.dumps(asdict(screen), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, screen: RootJointDetailFeasibilityScreen) -> Path:
    lines = [
        "# Root Joint Detail Feasibility Screen",
        "",
        f"Candidate: `{screen.candidate_id}`",
        f"Overall status: `{screen.overall_status}`",
        "",
        "This is not root-joint FEM signoff.",
        "",
        f"- design root bending moment: `{screen.design_root_bending_moment_n_m:.4f} N*m`",
        f"- envelope worst couple force: `{_fmt(screen.envelope_worst_couple_force_n)} N`",
        f"- envelope worst couple case: `{screen.envelope_worst_couple_case}`",
        f"- positive input concepts: `{screen.positive_input_concept_count}`",
        f"- negative margin concepts: `{screen.negative_margin_concept_count}`",
        f"- missing input concepts: `{screen.missing_input_concept_count}`",
        "",
        "| concept | status | arm m | required couple N | clamp margin N | bond margin N | insert margin N | tube wall margin N | traceability |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in screen.rows:
        lines.append(
            f"| `{row.concept_id}` | `{row.status}` | {_fmt(row.effective_couple_arm_m)} | "
            f"{_fmt(row.required_couple_force_n)} | {_fmt(row.fitting_or_clamp_margin_n)} | "
            f"{_fmt(row.bonded_joint_margin_n)} | {_fmt(row.insert_margin_n)} | "
            f"{_fmt(row.tube_wall_bearing_margin_n)} | `{row.traceability_status}` |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- A positive concept input row is only a hand/input screen.",
            "- Root fitting, clamp preload, bond peel, insert bearing, tube-wall stress, fatigue, and installation still need FEM or reviewed hand margins.",
            "- A small net root force is not enough; the root bending moment dominates the local load path.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    outputs = write_root_joint_detail_feasibility_screen_package(
        args.output_dir,
        build_current_root_joint_load_envelope(),
        root_joint_concepts=(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
