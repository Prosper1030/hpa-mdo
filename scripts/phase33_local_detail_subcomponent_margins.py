#!/usr/bin/env python3
"""Check local detail subcomponent allowables against Phase 23 requirements."""
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

from scripts.phase23_detail_sizing_requirements import (  # noqa: E402
    build_current_detail_sizing_requirements,
)
from scripts.phase34_wire_attach_load_decomposition import (  # noqa: E402
    build_current_wire_attach_load_decomposition,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase33_local_detail_subcomponent_margins"

SUBCOMPONENT_REQUIREMENTS: tuple[tuple[str, str, str], ...] = (
    (
        "wire_attach_local_load_path",
        "attach_ring_or_lug",
        "Attach ring or lug",
    ),
    (
        "wire_attach_local_load_path",
        "bonded_load_path",
        "Attach bond load path",
    ),
    (
        "wire_attach_local_load_path",
        "insert_pullout_bearing",
        "Attach insert pullout and bearing",
    ),
    (
        "wire_attach_local_load_path",
        "local_tube_wall_crushing",
        "Attach local tube-wall crushing",
    ),
    (
        "root_joint",
        "root_fitting_or_clamp",
        "Root fitting or clamp",
    ),
    (
        "root_joint",
        "bonded_joint",
        "Root bonded joint",
    ),
    (
        "root_joint",
        "root_insert",
        "Root insert",
    ),
    (
        "root_joint",
        "root_tube_wall_bearing",
        "Root tube-wall bearing",
    ),
    (
        "wire_termination",
        "termination_process_efficiency",
        "Termination process efficiency",
    ),
    (
        "wire_termination",
        "end_anchor_or_pin",
        "End anchor or pin",
    ),
    (
        "wire_termination",
        "bend_radius_creep_abrasion",
        "Bend radius, creep, and abrasion",
    ),
)


@dataclass(frozen=True)
class LocalDetailSubcomponentMarginRow:
    parent_key: str
    parent_title: str
    subcomponent_key: str
    subcomponent_title: str
    component_id: str
    status: str
    required_allowable_load_n: float | None
    provided_allowable_load_n: float | None
    load_margin_n: float | None
    required_allowable_moment_n_m: float | None
    provided_allowable_moment_n_m: float | None
    moment_margin_n_m: float | None
    required_minimum_breaking_load_n: float | None
    provided_minimum_breaking_load_n: float | None
    mbl_margin_n: float | None
    effective_termination_load_n: float | None
    effective_termination_load_margin_n: float | None
    worst_margin: float | None
    allowable_basis: str
    evidence_type: str
    derate_factor: float | None
    termination_efficiency: float | None
    traceability_status: str
    source: str
    engineering_note: str


@dataclass(frozen=True)
class LocalDetailSubcomponentMarginCheck:
    candidate_id: str
    overall_status: str
    total_subcomponent_count: int
    missing_subcomponent_count: int
    negative_margin_count: int
    traceability_gap_count: int
    rows: tuple[LocalDetailSubcomponentMarginRow, ...]


def build_local_detail_subcomponent_margin_check(
    detail_requirements: Any,
    *,
    subcomponent_allowables: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    wire_attach_load_decomposition: Any | None = None,
) -> LocalDetailSubcomponentMarginCheck:
    requirements_by_key = {
        str(row.key): row
        for row in getattr(detail_requirements, "rows", ())
    }
    allowables_by_key = {
        (str(row.get("parent_key", "")), str(row.get("subcomponent_key", ""))): row
        for row in subcomponent_allowables
    }
    rows = tuple(
        _build_row(
            requirements_by_key[parent_key],
            parent_key=parent_key,
            subcomponent_key=subcomponent_key,
            subcomponent_title=subcomponent_title,
            allowable=allowables_by_key.get((parent_key, subcomponent_key)),
            wire_attach_load_decomposition=wire_attach_load_decomposition,
        )
        for parent_key, subcomponent_key, subcomponent_title in SUBCOMPONENT_REQUIREMENTS
    )
    missing_count = sum(
        1
        for row in rows
        if row.status
        in {"subcomponent_allowable_missing", "subcomponent_moment_allowable_missing"}
    )
    negative_count = sum(1 for row in rows if row.status == "margin_negative")
    traceability_gap_count = sum(
        1 for row in rows if row.status == "subcomponent_traceability_missing"
    )
    all_positive = rows and all(row.status == "margin_positive_input_check_only" for row in rows)
    return LocalDetailSubcomponentMarginCheck(
        candidate_id=str(detail_requirements.candidate_id),
        overall_status=(
            "local_detail_subcomponent_inputs_pass_not_fem_signoff"
            if all_positive
            else "local_detail_subcomponent_margins_not_closed"
        ),
        total_subcomponent_count=len(rows),
        missing_subcomponent_count=missing_count,
        negative_margin_count=negative_count,
        traceability_gap_count=traceability_gap_count,
        rows=rows,
    )


def write_local_detail_subcomponent_margin_package(
    out_dir: Path,
    detail_requirements: Any,
    *,
    subcomponent_allowables: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    wire_attach_load_decomposition: Any | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    check = build_local_detail_subcomponent_margin_check(
        detail_requirements,
        subcomponent_allowables=subcomponent_allowables,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
    )
    outputs = [
        _write_template(
            out_dir / "local_detail_subcomponent_margin_inputs_template.csv",
            check,
        ),
        _write_csv(out_dir / "local_detail_subcomponent_margin_check.csv", check),
        _write_json(out_dir / "local_detail_subcomponent_margin_check.json", check),
        _write_markdown(out_dir / "local_detail_subcomponent_margin_check.md", check),
    ]
    return outputs


def read_subcomponent_allowables_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_current_local_detail_subcomponent_margin_check() -> LocalDetailSubcomponentMarginCheck:
    return build_local_detail_subcomponent_margin_check(
        build_current_detail_sizing_requirements(),
        subcomponent_allowables=[],
        wire_attach_load_decomposition=build_current_wire_attach_load_decomposition(),
    )


def _build_row(
    requirement: Any,
    *,
    parent_key: str,
    subcomponent_key: str,
    subcomponent_title: str,
    allowable: dict[str, Any] | None,
    wire_attach_load_decomposition: Any | None,
) -> LocalDetailSubcomponentMarginRow:
    required_load = _attr_float(requirement, "required_allowable_load_n")
    required_moment = _required_moment(
        requirement,
        parent_key=parent_key,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
    )
    required_mbl = _attr_float(requirement, "required_minimum_breaking_load_n")
    provided_load = _dict_float(allowable, "allowable_load_n")
    provided_moment = _dict_float(allowable, "allowable_moment_n_m")
    provided_mbl = _dict_float(allowable, "minimum_breaking_load_n")
    load_margin = _margin(provided_load, required_load)
    moment_margin = _margin(provided_moment, required_moment)
    mbl_margin = _margin(provided_mbl, required_mbl)
    component_id = str((allowable or {}).get("component_id", "")).strip()
    source = str((allowable or {}).get("source", "")).strip()
    allowable_basis = str((allowable or {}).get("allowable_basis", "")).strip()
    evidence_type = str((allowable or {}).get("evidence_type", "")).strip()
    derate_factor = _dict_float(allowable, "derate_factor")
    termination_efficiency = _dict_float(allowable, "termination_efficiency")
    effective_termination_load = _effective_termination_load(
        parent_key=parent_key,
        subcomponent_key=subcomponent_key,
        minimum_breaking_load_n=provided_mbl,
        derate_factor=derate_factor,
        termination_efficiency=termination_efficiency,
    )
    effective_termination_load_margin = _margin(effective_termination_load, required_load)
    traceability_status = _traceability_status(
        parent_key=parent_key,
        subcomponent_key=subcomponent_key,
        component_id=component_id,
        source=source,
        allowable_basis=allowable_basis,
        evidence_type=evidence_type,
        derate_factor=derate_factor,
        termination_efficiency=termination_efficiency,
    )
    status_margins = [
        value
        for value in (
            load_margin,
            moment_margin,
            mbl_margin,
            effective_termination_load_margin,
        )
        if value is not None
    ]
    force_like_margins = [
        value
        for value in (
            load_margin,
            mbl_margin,
            effective_termination_load_margin,
        )
        if value is not None
    ]
    status = _status(
        parent_key=parent_key,
        required_values=(required_load, required_moment, required_mbl),
        provided_values=(provided_load, provided_moment, provided_mbl),
        margins=status_margins,
        traceability_status=traceability_status,
    )
    return LocalDetailSubcomponentMarginRow(
        parent_key=parent_key,
        parent_title=str(requirement.title),
        subcomponent_key=subcomponent_key,
        subcomponent_title=subcomponent_title,
        component_id=component_id,
        status=status,
        required_allowable_load_n=required_load,
        provided_allowable_load_n=provided_load,
        load_margin_n=load_margin,
        required_allowable_moment_n_m=required_moment,
        provided_allowable_moment_n_m=provided_moment,
        moment_margin_n_m=moment_margin,
        required_minimum_breaking_load_n=required_mbl,
        provided_minimum_breaking_load_n=provided_mbl,
        mbl_margin_n=mbl_margin,
        effective_termination_load_n=effective_termination_load,
        effective_termination_load_margin_n=effective_termination_load_margin,
        worst_margin=None if not force_like_margins else min(force_like_margins),
        allowable_basis=allowable_basis,
        evidence_type=evidence_type,
        derate_factor=derate_factor,
        termination_efficiency=termination_efficiency,
        traceability_status=traceability_status,
        source=source,
        engineering_note=(
            "Input margin check only; not local FEM signoff and not a substitute for bearing, "
            "bond, insert, clamp, fatigue, inspection, traceability, or manufacturing evidence."
        ),
    )


def _status(
    *,
    parent_key: str,
    required_values: tuple[float | None, ...],
    provided_values: tuple[float | None, ...],
    margins: list[float],
    traceability_status: str,
) -> str:
    required_indices = [idx for idx, value in enumerate(required_values) if value is not None]
    if (
        parent_key == "wire_attach_local_load_path"
        and required_values[1] is not None
        and provided_values[0] is not None
        and provided_values[1] is None
    ):
        return "subcomponent_moment_allowable_missing"
    if any(provided_values[idx] is None for idx in required_indices):
        return "subcomponent_allowable_missing"
    if any(value < 0.0 for value in margins):
        return "margin_negative"
    if traceability_status != "traceable_input":
        return "subcomponent_traceability_missing"
    return "margin_positive_input_check_only"


def _traceability_status(
    *,
    parent_key: str,
    subcomponent_key: str,
    component_id: str,
    source: str,
    allowable_basis: str,
    evidence_type: str,
    derate_factor: float | None,
    termination_efficiency: float | None,
) -> str:
    if not component_id:
        return "component_id_missing"
    if not source:
        return "source_missing"
    if not allowable_basis:
        return "allowable_basis_missing"
    if not evidence_type:
        return "evidence_type_missing"
    if (
        parent_key == "wire_termination"
        and subcomponent_key == "termination_process_efficiency"
    ):
        if derate_factor is None and termination_efficiency is None:
            return "termination_efficiency_or_derate_missing"
        if derate_factor is not None and not _is_valid_factor(derate_factor):
            return "derate_factor_out_of_range"
        if termination_efficiency is not None and not _is_valid_factor(
            termination_efficiency
        ):
            return "termination_efficiency_out_of_range"
    return "traceable_input"


def _required_moment(
    requirement: Any,
    *,
    parent_key: str,
    wire_attach_load_decomposition: Any | None,
) -> float | None:
    if parent_key == "wire_attach_local_load_path":
        attach_moment = _attr_float(
            wire_attach_load_decomposition,
            "max_resultant_design_local_moment_n_m",
        )
        if attach_moment is not None:
            return attach_moment
    return _attr_float(requirement, "required_allowable_moment_n_m")


def _is_valid_factor(value: float) -> bool:
    return 0.0 < float(value) <= 1.0


def _valid_factors(*values: float | None) -> tuple[float, ...]:
    return tuple(
        float(value)
        for value in values
        if value is not None and _is_valid_factor(value)
    )


def _effective_termination_load(
    *,
    parent_key: str,
    subcomponent_key: str,
    minimum_breaking_load_n: float | None,
    derate_factor: float | None,
    termination_efficiency: float | None,
) -> float | None:
    if (
        parent_key != "wire_termination"
        or subcomponent_key != "termination_process_efficiency"
    ):
        return None
    factors = _valid_factors(derate_factor, termination_efficiency)
    if minimum_breaking_load_n is None or not factors:
        return None
    effective_load = float(minimum_breaking_load_n)
    for factor in factors:
        effective_load *= factor
    return effective_load


def _write_template(path: Path, check: LocalDetailSubcomponentMarginCheck) -> Path:
    fields = [
        "parent_key",
        "subcomponent_key",
        "subcomponent_title",
        "component_id",
        "required_allowable_load_n",
        "required_allowable_moment_n_m",
        "required_minimum_breaking_load_n",
        "allowable_load_n",
        "allowable_moment_n_m",
        "minimum_breaking_load_n",
        "allowable_basis",
        "evidence_type",
        "derate_factor",
        "termination_efficiency",
        "source",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in check.rows:
            writer.writerow(
                {
                    "parent_key": row.parent_key,
                    "subcomponent_key": row.subcomponent_key,
                    "subcomponent_title": row.subcomponent_title,
                    "component_id": "",
                    "required_allowable_load_n": _fmt(row.required_allowable_load_n),
                    "required_allowable_moment_n_m": _fmt(
                        row.required_allowable_moment_n_m
                    ),
                    "required_minimum_breaking_load_n": _fmt(
                        row.required_minimum_breaking_load_n
                    ),
                    "allowable_load_n": "",
                    "allowable_moment_n_m": "",
                    "minimum_breaking_load_n": "",
                    "allowable_basis": "",
                    "evidence_type": "",
                    "derate_factor": "",
                    "termination_efficiency": "",
                    "source": "",
                    "notes": "",
                }
            )
    return path


def _write_csv(path: Path, check: LocalDetailSubcomponentMarginCheck) -> Path:
    fields = list(asdict(check.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in check.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, check: LocalDetailSubcomponentMarginCheck) -> Path:
    path.write_text(
        json.dumps(asdict(check), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, check: LocalDetailSubcomponentMarginCheck) -> Path:
    lines = [
        "# Local Detail Subcomponent Margins",
        "",
        f"Candidate: `{check.candidate_id}`",
        f"Overall status: `{check.overall_status}`",
        "",
        "These are local detail subcomponent margins, not local FEM signoff.",
        "",
        f"- total subcomponents: `{check.total_subcomponent_count}`",
        f"- missing subcomponents: `{check.missing_subcomponent_count}`",
        f"- negative-margin subcomponents: `{check.negative_margin_count}`",
        f"- traceability-gap subcomponents: `{check.traceability_gap_count}`",
        "",
        "| parent | subcomponent | component | status | traceability | load margin N | moment margin N*m | MBL margin N | effective termination load N | effective termination margin N | allowable basis | evidence type | derate | termination efficiency | source |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---:|---:|---|",
    ]
    for row in check.rows:
        lines.append(
            f"| {row.parent_title} | {row.subcomponent_title} | "
            f"{row.component_id or 'n/a'} | `{row.status}` | "
            f"`{row.traceability_status}` | "
            f"{_fmt(row.load_margin_n)} | {_fmt(row.moment_margin_n_m)} | "
            f"{_fmt(row.mbl_margin_n)} | "
            f"{_fmt(row.effective_termination_load_n)} | "
            f"{_fmt(row.effective_termination_load_margin_n)} | "
            f"{row.allowable_basis or 'n/a'} | "
            f"{row.evidence_type or 'n/a'} | {_fmt(row.derate_factor)} | "
            f"{_fmt(row.termination_efficiency)} | "
            f"{row.source or 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Positive inputs only mean every required subcomponent allowable exceeds the Phase 23 scalar requirement.",
            "- A traceable input requires a component id, source, allowable basis, and evidence type for each subcomponent.",
            "- Termination process efficiency also requires an explicit efficiency or derate factor; when both are supplied, independent factors are multiplied before comparing derated MBL against required load.",
            "- This does not close local stress concentration, load introduction, bond peel, fatigue, inspection, traceability, or installation quality.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _attr_float(obj: Any, name: str) -> float | None:
    value = getattr(obj, name, None)
    if value is None or value == "":
        return None
    return float(value)


def _dict_float(row: dict[str, Any] | None, name: str) -> float | None:
    if row is None:
        return None
    value = row.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _margin(provided: float | None, required: float | None) -> float | None:
    if required is None or provided is None:
        return None
    return float(provided) - float(required)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--subcomponent-allowables-csv", type=Path)
    args = parser.parse_args(argv)

    detail_requirements = build_current_detail_sizing_requirements()
    subcomponent_allowables = (
        []
        if args.subcomponent_allowables_csv is None
        else read_subcomponent_allowables_csv(args.subcomponent_allowables_csv)
    )
    outputs = write_local_detail_subcomponent_margin_package(
        args.output_dir,
        detail_requirements,
        subcomponent_allowables=subcomponent_allowables,
        wire_attach_load_decomposition=build_current_wire_attach_load_decomposition(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
