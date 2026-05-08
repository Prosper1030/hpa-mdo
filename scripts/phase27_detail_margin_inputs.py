#!/usr/bin/env python3
"""Check user-supplied detail hardware allowables against Phase 23 requirements."""
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


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase27_detail_margin_inputs"


@dataclass(frozen=True)
class DetailMarginRow:
    key: str
    title: str
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
    worst_margin: float | None
    source: str
    engineering_note: str


@dataclass(frozen=True)
class DetailMarginCheck:
    candidate_id: str
    overall_status: str
    rows: tuple[DetailMarginRow, ...]


def build_detail_margin_check(
    detail_requirements: Any,
    *,
    hardware_allowables: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> DetailMarginCheck:
    allowables_by_key = {str(row.get("key", "")): row for row in hardware_allowables}
    rows = tuple(
        _build_margin_row(requirement, allowables_by_key.get(str(requirement.key)))
        for requirement in getattr(detail_requirements, "rows", ())
    )
    all_positive = rows and all(row.status == "margin_positive_input_check_only" for row in rows)
    return DetailMarginCheck(
        candidate_id=str(detail_requirements.candidate_id),
        overall_status=(
            "hardware_input_margins_pass_not_fem_signoff"
            if all_positive
            else "hardware_input_margins_not_closed"
        ),
        rows=rows,
    )


def write_detail_margin_input_package(
    out_dir: Path,
    detail_requirements: Any,
    *,
    hardware_allowables: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    check = build_detail_margin_check(
        detail_requirements,
        hardware_allowables=hardware_allowables,
    )
    outputs = [
        _write_template(out_dir / "detail_margin_inputs_template.csv", detail_requirements),
        _write_csv(out_dir / "detail_margin_check.csv", check),
        _write_json(out_dir / "detail_margin_check.json", check),
        _write_markdown(out_dir / "detail_margin_check.md", check),
    ]
    return outputs


def read_hardware_allowables_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _build_margin_row(requirement: Any, allowable: dict[str, Any] | None) -> DetailMarginRow:
    required_load = _attr_float(requirement, "required_allowable_load_n")
    required_moment = _attr_float(requirement, "required_allowable_moment_n_m")
    required_mbl = _attr_float(requirement, "required_minimum_breaking_load_n")
    provided_load = _dict_float(allowable, "allowable_load_n")
    provided_moment = _dict_float(allowable, "allowable_moment_n_m")
    provided_mbl = _dict_float(allowable, "minimum_breaking_load_n")
    load_margin = _margin(provided_load, required_load)
    moment_margin = _margin(provided_moment, required_moment)
    mbl_margin = _margin(provided_mbl, required_mbl)
    margins = [value for value in (load_margin, moment_margin, mbl_margin) if value is not None]
    status = _status(
        required_values=(required_load, required_moment, required_mbl),
        provided_values=(provided_load, provided_moment, provided_mbl),
        margins=margins,
    )
    return DetailMarginRow(
        key=str(requirement.key),
        title=str(requirement.title),
        component_id=str((allowable or {}).get("component_id", "")),
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
        worst_margin=None if not margins else min(margins),
        source=str((allowable or {}).get("source", "")),
        engineering_note=(
            "Input margin check only; not FEM signoff and not a substitute for local load introduction, "
            "fatigue, manufacturing, bond, or inspection evidence."
        ),
    )


def _status(
    *,
    required_values: tuple[float | None, ...],
    provided_values: tuple[float | None, ...],
    margins: list[float],
) -> str:
    required_indices = [idx for idx, value in enumerate(required_values) if value is not None]
    if any(provided_values[idx] is None for idx in required_indices):
        return "hardware_allowable_missing"
    if any(value < 0.0 for value in margins):
        return "margin_negative"
    return "margin_positive_input_check_only"


def _write_template(path: Path, detail_requirements: Any) -> Path:
    fields = [
        "key",
        "title",
        "component_id",
        "required_allowable_load_n",
        "required_allowable_moment_n_m",
        "required_minimum_breaking_load_n",
        "allowable_load_n",
        "allowable_moment_n_m",
        "minimum_breaking_load_n",
        "source",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in getattr(detail_requirements, "rows", ()):
            writer.writerow(
                {
                    "key": row.key,
                    "title": row.title,
                    "component_id": "",
                    "required_allowable_load_n": _fmt(_attr_float(row, "required_allowable_load_n")),
                    "required_allowable_moment_n_m": _fmt(
                        _attr_float(row, "required_allowable_moment_n_m")
                    ),
                    "required_minimum_breaking_load_n": _fmt(
                        _attr_float(row, "required_minimum_breaking_load_n")
                    ),
                    "allowable_load_n": "",
                    "allowable_moment_n_m": "",
                    "minimum_breaking_load_n": "",
                    "source": "",
                    "notes": "",
                }
            )
    return path


def _write_csv(path: Path, check: DetailMarginCheck) -> Path:
    fields = list(asdict(check.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in check.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, check: DetailMarginCheck) -> Path:
    path.write_text(json.dumps(asdict(check), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, check: DetailMarginCheck) -> Path:
    lines = [
        "# Detail Margin Inputs",
        "",
        f"Candidate: `{check.candidate_id}`",
        f"Overall status: `{check.overall_status}`",
        "",
        "These are hardware input margins, not FEM signoff.",
        "",
        "| item | component | status | load margin N | moment margin N*m | MBL margin N | source |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for row in check.rows:
        lines.append(
            f"| {row.title} | {row.component_id or 'n/a'} | `{row.status}` | "
            f"{_fmt(row.load_margin_n)} | {_fmt(row.moment_margin_n_m)} | "
            f"{_fmt(row.mbl_margin_n)} | {row.source or 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Positive margins here only mean the supplied hardware numbers exceed Phase 23 requirements.",
            "- This is not FEM signoff and does not close bond, insert, bearing, fatigue, local wall, or installation details by itself.",
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
    if required is None:
        return None
    if provided is None:
        return None
    return float(provided) - float(required)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--hardware-allowables-csv", type=Path)
    args = parser.parse_args(argv)

    requirements = build_current_detail_sizing_requirements()
    hardware_allowables = (
        []
        if args.hardware_allowables_csv is None
        else read_hardware_allowables_csv(args.hardware_allowables_csv)
    )
    outputs = write_detail_margin_input_package(
        args.output_dir,
        requirements,
        hardware_allowables=hardware_allowables,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
