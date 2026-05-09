#!/usr/bin/env python3
"""Rank local detail blockers by work priority without claiming failure order."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    CANDIDATE_ID,
)
from scripts.phase23_detail_sizing_requirements import (  # noqa: E402
    build_current_detail_sizing_requirements,
)
from scripts.phase33_local_detail_subcomponent_margins import (  # noqa: E402
    build_current_local_detail_subcomponent_margin_check,
)
from scripts.phase34_wire_attach_load_decomposition import (  # noqa: E402
    build_current_wire_attach_load_decomposition,
)
from scripts.phase35_root_joint_load_envelope import (  # noqa: E402
    build_current_root_joint_load_envelope,
)
from scripts.phase36_wire_termination_efficiency_sensitivity import (  # noqa: E402
    build_current_wire_termination_efficiency_sensitivity,
)
from scripts.phase43_existing_detail_allowable_evidence_triage import (  # noqa: E402
    build_current_existing_detail_allowable_evidence_triage,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase46_local_detail_criticality_ordering"
LOCAL_DETAIL_KEYS = (
    "wire_attach_local_load_path",
    "root_joint",
    "wire_termination",
)


@dataclass(frozen=True)
class LocalDetailCriticalityRow:
    blocker_key: str
    title: str
    work_priority_rank: int
    status: str
    design_severity_n_equivalent: float
    governing_screen: str
    demand_summary: str
    local_allowable_gap_summary: str
    existing_allowable_status: str
    closes_engineering_margin: bool
    ordering_boundary: str
    engineering_read: str
    next_action: str


@dataclass(frozen=True)
class LocalDetailCriticalityOrdering:
    candidate_id: str
    overall_status: str
    row_count: int
    unclosed_detail_count: int
    highest_priority_key: str
    rows: tuple[LocalDetailCriticalityRow, ...]


def build_local_detail_criticality_ordering(
    candidate_id: str,
    *,
    detail_requirements: Any,
    local_detail_subcomponent_check: Any,
    wire_attach_load_decomposition: Any,
    root_joint_load_envelope: Any,
    wire_termination_efficiency_sensitivity: Any,
    existing_detail_allowable_evidence_triage: Any | None = None,
) -> LocalDetailCriticalityOrdering:
    details = _rows_by_key(detail_requirements, "key")
    raw_rows = (
        _wire_attach_row(
            details.get("wire_attach_local_load_path"),
            local_detail_subcomponent_check,
            wire_attach_load_decomposition,
            existing_detail_allowable_evidence_triage,
        ),
        _root_joint_row(
            details.get("root_joint"),
            local_detail_subcomponent_check,
            root_joint_load_envelope,
            existing_detail_allowable_evidence_triage,
        ),
        _wire_termination_row(
            details.get("wire_termination"),
            local_detail_subcomponent_check,
            wire_termination_efficiency_sensitivity,
            existing_detail_allowable_evidence_triage,
        ),
    )
    rows = tuple(
        replace(row, work_priority_rank=index)
        for index, row in enumerate(
            sorted(
                raw_rows,
                key=lambda row: (-row.design_severity_n_equivalent, row.blocker_key),
            ),
            start=1,
        )
    )
    unclosed_count = sum(1 for row in rows if not row.closes_engineering_margin)
    return LocalDetailCriticalityOrdering(
        candidate_id=str(candidate_id),
        overall_status=(
            "local_detail_margins_close_input_check_only"
            if unclosed_count == 0
            else "local_detail_work_priority_ranked_allowables_missing"
        ),
        row_count=len(rows),
        unclosed_detail_count=unclosed_count,
        highest_priority_key=rows[0].blocker_key if rows else "",
        rows=rows,
    )


def write_local_detail_criticality_ordering_package(
    out_dir: Path,
    candidate_id: str,
    *,
    detail_requirements: Any,
    local_detail_subcomponent_check: Any,
    wire_attach_load_decomposition: Any,
    root_joint_load_envelope: Any,
    wire_termination_efficiency_sensitivity: Any,
    existing_detail_allowable_evidence_triage: Any | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ordering = build_local_detail_criticality_ordering(
        candidate_id,
        detail_requirements=detail_requirements,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        existing_detail_allowable_evidence_triage=(
            existing_detail_allowable_evidence_triage
        ),
    )
    return [
        _write_csv(out_dir / "local_detail_criticality_ordering.csv", ordering),
        _write_json(out_dir / "local_detail_criticality_ordering.json", ordering),
        _write_markdown(out_dir / "local_detail_criticality_ordering.md", ordering),
    ]


def build_current_local_detail_criticality_ordering() -> LocalDetailCriticalityOrdering:
    return build_local_detail_criticality_ordering(
        CANDIDATE_ID,
        detail_requirements=build_current_detail_sizing_requirements(),
        local_detail_subcomponent_check=(
            build_current_local_detail_subcomponent_margin_check()
        ),
        wire_attach_load_decomposition=build_current_wire_attach_load_decomposition(),
        root_joint_load_envelope=build_current_root_joint_load_envelope(),
        wire_termination_efficiency_sensitivity=(
            build_current_wire_termination_efficiency_sensitivity()
        ),
        existing_detail_allowable_evidence_triage=(
            build_current_existing_detail_allowable_evidence_triage()
        ),
    )


def _wire_attach_row(
    detail: Any | None,
    local_detail_subcomponent_check: Any,
    decomposition: Any,
    existing_triage: Any | None,
) -> LocalDetailCriticalityRow:
    severity = _attr_float(decomposition, "max_resultant_design_load_n")
    if severity is None:
        severity = _attr_float(detail, "required_allowable_load_n") or 0.0
    spanwise = _component_design_load_max(decomposition, "spanwise_y")
    transverse = _component_design_load_max(decomposition, "transverse_xz")
    local_moment = _attr_float(decomposition, "max_resultant_design_local_moment_n_m")
    demand = (
        "attach max resultant design="
        f"{_fmt(severity)} N; "
        "spanwise design="
        f"{_fmt(spanwise)} N; "
        "transverse design="
        f"{_fmt(transverse)} N; "
        "max local moment="
        f"{_fmt(local_moment)} N*m."
    )
    return _row(
        blocker_key="wire_attach_local_load_path",
        title="Wire attach local load path",
        governing_screen="wire_attach_resultant_design_load",
        design_severity_n_equivalent=severity,
        demand_summary=demand,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        existing_triage=existing_triage,
        engineering_read=(
            "Wire attach remains a local-detail blocker because the resultant, spanwise, "
            "and transverse components must enter the lug/ring, bond, insert, and local "
            "tube wall; force decomposition is not stress or fatigue signoff."
        ),
        next_action=(
            "Size or FEM the attach ring/lug, bond, insert pullout/bearing, and local "
            "tube-wall crushing path using the decomposed force and eccentricity."
        ),
    )


def _root_joint_row(
    detail: Any | None,
    local_detail_subcomponent_check: Any,
    envelope: Any,
    existing_triage: Any | None,
) -> LocalDetailCriticalityRow:
    max_couple_force, max_couple_case = _max_root_couple_row(envelope)
    severity = max_couple_force
    if severity is None:
        severity = _attr_float(detail, "required_allowable_moment_n_m") or 0.0
    demand = (
        "root design force="
        f"{_fmt(_attr_float(envelope, 'design_root_force_n'))} N; "
        "root design moment="
        f"{_fmt(_attr_float(envelope, 'design_root_bending_moment_n_m'))} N*m; "
        "max couple force="
        f"{_fmt(max_couple_force)} N; "
        "max couple case="
        f"{max_couple_case}; "
        "force-only misleading="
        f"{getattr(envelope, 'force_only_check_is_misleading', 'unknown')}."
    )
    return _row(
        blocker_key="root_joint",
        title="Root fitting / clamp / bonded insert",
        governing_screen="root_moment_couple_force",
        design_severity_n_equivalent=severity,
        demand_summary=demand,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        existing_triage=existing_triage,
        engineering_read=(
            "Root joint is the first local-detail work priority when the root bending "
            "moment is reacted through a short clamp or bond couple; the force-only check "
            "is misleading for fitting, insert, bond, and tube-wall design."
        ),
        next_action=(
            "Replace assumed couple arms with actual root fitting geometry, then close "
            "clamp, bond, insert, bearing, tube-wall, and fatigue/inspection margins."
        ),
    )


def _wire_termination_row(
    detail: Any | None,
    local_detail_subcomponent_check: Any,
    sensitivity: Any,
    existing_triage: Any | None,
) -> LocalDetailCriticalityRow:
    eta_060 = _termination_efficiency_row(sensitivity, 0.60)
    eta_080 = _termination_efficiency_row(sensitivity, 0.80)
    severity = _attr_float(eta_060, "required_minimum_breaking_load_n")
    if severity is None:
        severity = _attr_float(detail, "required_minimum_breaking_load_n") or 0.0
    demand = (
        "required load="
        f"{_fmt(_attr_float(detail, 'required_allowable_load_n'))} N; "
        "required MBL="
        f"{_fmt(_attr_float(detail, 'required_minimum_breaking_load_n'))} N; "
        "body margin="
        f"{_fmt(_attr_float(sensitivity, 'body_allowable_margin_n'))} N; "
        "eta 0.60 MBL="
        f"{_fmt(_attr_float(eta_060, 'required_minimum_breaking_load_n'))} N; "
        "eta 0.80 MBL="
        f"{_fmt(_attr_float(eta_080, 'required_minimum_breaking_load_n'))} N."
    )
    return _row(
        blocker_key="wire_termination",
        title="Wire termination / end fitting",
        governing_screen="termination_required_mbl_eta_0p60",
        design_severity_n_equivalent=severity,
        demand_summary=demand,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        existing_triage=existing_triage,
        engineering_read=(
            "Wire body strength is not termination allowable; the end fitting, swage, "
            "splice, knot, pin, bend radius, creep, and abrasion path must be derated "
            "and sourced before the 6 kN wire can be treated as installed capacity."
        ),
        next_action=(
            "Select the actual termination hardware or process and verify effective "
            "termination load after efficiency, derate, bend, anchor, creep, and abrasion."
        ),
    )


def _row(
    *,
    blocker_key: str,
    title: str,
    governing_screen: str,
    design_severity_n_equivalent: float,
    demand_summary: str,
    local_detail_subcomponent_check: Any,
    existing_triage: Any | None,
    engineering_read: str,
    next_action: str,
) -> LocalDetailCriticalityRow:
    local_summary = _local_gap_summary(blocker_key, local_detail_subcomponent_check)
    existing_summary, existing_closes_margin = _existing_summary(blocker_key, existing_triage)
    local_closes_margin = _local_inputs_positive(blocker_key, local_detail_subcomponent_check)
    closes_margin = bool(existing_closes_margin and local_closes_margin)
    return LocalDetailCriticalityRow(
        blocker_key=blocker_key,
        title=title,
        work_priority_rank=0,
        status=(
            "work_priority_ranked_input_margin_candidate_not_fem_signoff"
            if closes_margin
            else "work_priority_ranked_negative_or_missing_margin"
        ),
        design_severity_n_equivalent=float(design_severity_n_equivalent),
        governing_screen=governing_screen,
        demand_summary=demand_summary,
        local_allowable_gap_summary=local_summary,
        existing_allowable_status=existing_summary,
        closes_engineering_margin=closes_margin,
        ordering_boundary="work_priority_only_not_failure_load_factor_rank",
        engineering_read=engineering_read,
        next_action=next_action,
    )


def _local_gap_summary(parent_key: str, check: Any) -> str:
    rows = _local_rows(parent_key, check)
    missing = sum(
        1 for row in rows if getattr(row, "status", "") == "subcomponent_allowable_missing"
    )
    moment_missing = sum(
        1
        for row in rows
        if getattr(row, "status", "") == "subcomponent_moment_allowable_missing"
    )
    negative = sum(1 for row in rows if getattr(row, "status", "") == "margin_negative")
    traceability_gap = sum(
        1 for row in rows if getattr(row, "status", "") == "subcomponent_traceability_missing"
    )
    positive = sum(
        1 for row in rows if getattr(row, "status", "") == "margin_positive_input_check_only"
    )
    worst_values = [
        _attr_float(row, name)
        for row in rows
        for name in (
            "load_margin_n",
            "moment_margin_n_m",
            "mbl_margin_n",
            "effective_termination_load_margin_n",
        )
    ]
    finite = [value for value in worst_values if value is not None]
    return (
        "local subcomponents="
        f"{len(rows)}; "
        "missing allowables="
        f"{missing}; "
        "moment allowable gaps="
        f"{moment_missing}; "
        "negative margins="
        f"{negative}; "
        "traceability gaps="
        f"{traceability_gap}; "
        "positive input rows="
        f"{positive}; "
        "worst local margin="
        f"{_fmt(min(finite) if finite else None)}."
    )


def _existing_summary(parent_key: str, triage: Any | None) -> tuple[str, bool]:
    if triage is None:
        return "existing detail allowable triage is not available.", False
    rows = _rows_by_key(triage, "blocker_key")
    row = rows.get(parent_key)
    if row is None:
        return (
            "existing triage status="
            f"{getattr(triage, 'overall_status', 'unknown')}; row status=missing.",
            False,
        )
    return (
        "existing triage status="
        f"{getattr(triage, 'overall_status', 'unknown')}; "
        "row status="
        f"{getattr(row, 'status', 'unknown')}; "
        "closes margin="
        f"{bool(getattr(row, 'closes_engineering_margin', False))}; "
        "missing allowable rows="
        f"{int(getattr(row, 'missing_allowable_rows', 0))}; "
        "negative margin rows="
        f"{int(getattr(row, 'negative_margin_rows', 0))}; "
        "traceability gap rows="
        f"{int(getattr(row, 'traceability_gap_rows', 0))}.",
        bool(getattr(row, "closes_engineering_margin", False)),
    )


def _local_inputs_positive(parent_key: str, check: Any) -> bool:
    rows = _local_rows(parent_key, check)
    return bool(rows) and all(
        getattr(row, "status", "") == "margin_positive_input_check_only"
        for row in rows
    )


def _local_rows(parent_key: str, check: Any) -> tuple[Any, ...]:
    return tuple(
        row for row in getattr(check, "rows", ()) if getattr(row, "parent_key", "") == parent_key
    )


def _rows_by_key(container: Any, field_name: str) -> dict[str, Any]:
    return {
        str(getattr(row, field_name, "")): row
        for row in getattr(container, "rows", ())
    }


def _component_design_load_max(decomposition: Any, component_key: str) -> float | None:
    values = [
        _attr_float(row, "design_load_n")
        for row in getattr(decomposition, "rows", ())
        if str(getattr(row, "component_key", "")) == component_key
    ]
    finite = [value for value in values if value is not None]
    return max(finite) if finite else None


def _max_root_couple_row(envelope: Any) -> tuple[float | None, str]:
    values = [
        (
            _attr_float(row, "required_couple_force_n"),
            str(getattr(row, "load_case_key", "unknown")),
        )
        for row in getattr(envelope, "rows", ())
        if _attr_float(row, "required_couple_force_n") is not None
    ]
    return max(values, key=lambda value: value[0] or float("-inf")) if values else (None, "n/a")


def _termination_efficiency_row(sensitivity: Any, efficiency: float) -> Any | None:
    for row in getattr(sensitivity, "rows", ()):
        row_efficiency = _attr_float(row, "termination_efficiency")
        if row_efficiency is not None and abs(row_efficiency - float(efficiency)) < 1e-9:
            return row
    return None


def _attr_float(obj: Any | None, name: str) -> float | None:
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value in (None, ""):
        return None
    return float(value)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def _write_csv(path: Path, ordering: LocalDetailCriticalityOrdering) -> Path:
    fields = list(asdict(ordering.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in ordering.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, ordering: LocalDetailCriticalityOrdering) -> Path:
    path.write_text(
        json.dumps(asdict(ordering), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, ordering: LocalDetailCriticalityOrdering) -> Path:
    lines = [
        "# Local Detail Criticality Ordering",
        "",
        f"Candidate: `{ordering.candidate_id}`",
        f"Overall status: `{ordering.overall_status}`",
        "",
        "This is not local-detail signoff. It ranks work priority only, not true failure load factor.",
        "",
        f"- rows: `{ordering.row_count}`",
        f"- unclosed details: `{ordering.unclosed_detail_count}`",
        f"- highest priority: `{ordering.highest_priority_key}`",
        "",
        "| priority | blocker | status | governing screen | severity N-equivalent | demand | gap summary | boundary | next action |",
        "|---:|---|---|---|---:|---|---|---|---|",
    ]
    for row in ordering.rows:
        lines.append(
            f"| {row.work_priority_rank} | {row.title} | `{row.status}` | "
            f"`{row.governing_screen}` | {row.design_severity_n_equivalent:.4f} | "
            f"{row.demand_summary} | {row.local_allowable_gap_summary} "
            f"{row.existing_allowable_status} | `{row.ordering_boundary}` | "
            f"{row.next_action} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- A higher work-priority rank is not a lower failure load factor.",
            "- Root moment-couple screening must be replaced by actual fitting geometry and margins.",
            "- Cable-body strength must not be reused as termination allowable.",
            "- Attach decomposition must still become local stress, bond, insert, bearing, tube-wall, and fatigue evidence.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    outputs = write_local_detail_criticality_ordering_package(
        args.output_dir,
        CANDIDATE_ID,
        detail_requirements=build_current_detail_sizing_requirements(),
        local_detail_subcomponent_check=(
            build_current_local_detail_subcomponent_margin_check()
        ),
        wire_attach_load_decomposition=build_current_wire_attach_load_decomposition(),
        root_joint_load_envelope=build_current_root_joint_load_envelope(),
        wire_termination_efficiency_sensitivity=(
            build_current_wire_termination_efficiency_sensitivity()
        ),
        existing_detail_allowable_evidence_triage=(
            build_current_existing_detail_allowable_evidence_triage()
        ),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
