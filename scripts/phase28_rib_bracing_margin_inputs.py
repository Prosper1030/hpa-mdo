#!/usr/bin/env python3
"""Check user-supplied rib/bracing allowables against current bracing requirements."""
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

from scripts.phase15_candidate_load_factor_buckling_check import CANDIDATE_ID  # noqa: E402
from scripts.phase22_bracing_sensitivity import (  # noqa: E402
    build_bracing_sensitivity_audit,
    build_current_candidate_model,
)
from scripts.phase24_rib_spacing_requirements import (  # noqa: E402
    build_current_rib_spacing_requirements,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase28_rib_bracing_margin_inputs"
FINITE_RIB_VARIANT_ID = "dense_finite_rib_surrogate"


@dataclass(frozen=True)
class RibBracingMarginRow:
    bay_index: int
    start_y_m: float
    end_y_m: float
    required_intermediate_stations: int
    covered_intermediate_station_count: int | None
    covered_station_ids: str
    station_coverage_status: str
    recommended_subbay_m: float
    bay_vertical_load_scale_n: float
    required_link_force_n: float
    rib_family: str
    status: str
    allowable_link_force_n: float | None
    link_margin_n: float | None
    allowable_shear_force_n: float | None
    shear_margin_n: float | None
    allowable_bond_force_n: float | None
    bond_margin_n: float | None
    worst_margin_n: float | None
    allowable_basis: str
    evidence_type: str
    attachment_basis: str
    traceability_status: str
    source: str
    engineering_note: str


@dataclass(frozen=True)
class RibBracingMarginCheck:
    candidate_id: str
    overall_status: str
    finite_rib_variant_id: str
    required_link_force_n: float
    traceability_gap_count: int
    station_coverage_gap_count: int
    rows: tuple[RibBracingMarginRow, ...]


def build_rib_bracing_margin_check(
    spacing_requirements: Any,
    bracing_audit: Any,
    *,
    rib_allowables: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> RibBracingMarginCheck:
    required_link_force = _finite_rib_link_force(bracing_audit)
    allowables_by_bay = {
        int(float(row.get("bay_index", -1))): row
        for row in rib_allowables
        if row.get("bay_index", "") != ""
    }
    rows = tuple(
        _build_row(
            spacing_row,
            required_link_force_n=required_link_force,
            allowable=allowables_by_bay.get(int(spacing_row.bay_index)),
        )
        for spacing_row in getattr(spacing_requirements, "rows", ())
    )
    traceability_gap_count = sum(1 for row in rows if row.status == "rib_traceability_missing")
    station_coverage_gap_count = sum(
        1 for row in rows if row.status == "rib_station_coverage_missing"
    )
    all_positive = rows and all(row.status == "margin_positive_input_check_only" for row in rows)
    return RibBracingMarginCheck(
        candidate_id=str(spacing_requirements.candidate_id),
        overall_status=(
            "rib_bracing_input_margins_pass_not_fem_signoff"
            if all_positive
            else "rib_bracing_margins_not_closed"
        ),
        finite_rib_variant_id=FINITE_RIB_VARIANT_ID,
        required_link_force_n=required_link_force,
        traceability_gap_count=traceability_gap_count,
        station_coverage_gap_count=station_coverage_gap_count,
        rows=rows,
    )


def write_rib_bracing_margin_input_package(
    out_dir: Path,
    spacing_requirements: Any,
    bracing_audit: Any,
    *,
    rib_allowables: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    check = build_rib_bracing_margin_check(
        spacing_requirements,
        bracing_audit,
        rib_allowables=rib_allowables,
    )
    outputs = [
        _write_template(out_dir / "rib_bracing_margin_inputs_template.csv", check),
        _write_csv(out_dir / "rib_bracing_margin_check.csv", check),
        _write_json(out_dir / "rib_bracing_margin_check.json", check),
        _write_markdown(out_dir / "rib_bracing_margin_check.md", check),
    ]
    return outputs


def read_rib_allowables_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_current_rib_bracing_margin_check() -> RibBracingMarginCheck:
    model = build_current_candidate_model()
    bracing_audit = build_bracing_sensitivity_audit(CANDIDATE_ID, model)
    spacing_requirements = build_current_rib_spacing_requirements()
    return build_rib_bracing_margin_check(
        spacing_requirements,
        bracing_audit,
        rib_allowables=[],
    )


def _build_row(
    spacing_row: Any,
    *,
    required_link_force_n: float,
    allowable: dict[str, Any] | None,
) -> RibBracingMarginRow:
    allowable_link = _dict_float(allowable, "allowable_link_force_n")
    allowable_shear = _dict_float(allowable, "allowable_shear_force_n")
    allowable_bond = _dict_float(allowable, "allowable_bond_force_n")
    link_margin = _margin(allowable_link, required_link_force_n)
    shear_margin = _margin(allowable_shear, required_link_force_n)
    bond_margin = _margin(allowable_bond, required_link_force_n)
    margins = [value for value in (link_margin, shear_margin, bond_margin) if value is not None]
    rib_family = str((allowable or {}).get("rib_family", "")).strip()
    source = str((allowable or {}).get("source", "")).strip()
    allowable_basis = str((allowable or {}).get("allowable_basis", "")).strip()
    evidence_type = str((allowable or {}).get("evidence_type", "")).strip()
    attachment_basis = str((allowable or {}).get("attachment_basis", "")).strip()
    covered_station_count = _dict_int(allowable, "covered_intermediate_station_count")
    covered_station_ids = str((allowable or {}).get("covered_station_ids", "")).strip()
    station_coverage_status = _station_coverage_status(
        required_intermediate_stations=int(spacing_row.required_intermediate_stations),
        covered_intermediate_station_count=covered_station_count,
        covered_station_ids=covered_station_ids,
    )
    traceability_status = _traceability_status(
        rib_family=rib_family,
        source=source,
        allowable_basis=allowable_basis,
        evidence_type=evidence_type,
        attachment_basis=attachment_basis,
    )
    status = _status(
        provided=(allowable_link, allowable_shear, allowable_bond),
        margins=margins,
        traceability_status=traceability_status,
        station_coverage_status=station_coverage_status,
    )
    return RibBracingMarginRow(
        bay_index=int(spacing_row.bay_index),
        start_y_m=float(spacing_row.start_y_m),
        end_y_m=float(spacing_row.end_y_m),
        required_intermediate_stations=int(spacing_row.required_intermediate_stations),
        covered_intermediate_station_count=covered_station_count,
        covered_station_ids=covered_station_ids,
        station_coverage_status=station_coverage_status,
        recommended_subbay_m=float(spacing_row.recommended_subbay_m),
        bay_vertical_load_scale_n=float(spacing_row.bay_vertical_load_scale_n),
        required_link_force_n=float(required_link_force_n),
        rib_family=rib_family,
        status=status,
        allowable_link_force_n=allowable_link,
        link_margin_n=link_margin,
        allowable_shear_force_n=allowable_shear,
        shear_margin_n=shear_margin,
        allowable_bond_force_n=allowable_bond,
        bond_margin_n=bond_margin,
        worst_margin_n=None if not margins else min(margins),
        allowable_basis=allowable_basis,
        evidence_type=evidence_type,
        attachment_basis=attachment_basis,
        traceability_status=traceability_status,
        source=source,
        engineering_note=(
            "Input margin check only; not finite-rib FEM signoff and not a substitute for rib stiffness, "
            "station-by-station spar-attach, cap, web, bond, traceability, or manufacturing evidence."
        ),
    )


def _finite_rib_link_force(bracing_audit: Any) -> float:
    for row in getattr(bracing_audit, "rows", ()):
        if str(row.variant_id) == FINITE_RIB_VARIANT_ID:
            return float(row.link_force_max_n)
    raise ValueError(f"{FINITE_RIB_VARIANT_ID} row is required.")


def _status(
    *,
    provided: tuple[float | None, ...],
    margins: list[float],
    traceability_status: str,
    station_coverage_status: str,
) -> str:
    if any(value is None for value in provided):
        return "rib_allowable_missing"
    if any(value < 0.0 for value in margins):
        return "margin_negative"
    if traceability_status != "traceable_input":
        return "rib_traceability_missing"
    if station_coverage_status != "station_coverage_satisfied":
        return "rib_station_coverage_missing"
    return "margin_positive_input_check_only"


def _station_coverage_status(
    *,
    required_intermediate_stations: int,
    covered_intermediate_station_count: int | None,
    covered_station_ids: str,
) -> str:
    if required_intermediate_stations <= 0:
        return "station_coverage_satisfied"
    if covered_intermediate_station_count is None:
        return "station_coverage_count_missing"
    if covered_intermediate_station_count < required_intermediate_stations:
        return "station_coverage_count_insufficient"
    station_ids = [value for value in covered_station_ids.split(";") if value.strip()]
    if not station_ids:
        return "station_ids_missing"
    if len(station_ids) < required_intermediate_stations:
        return "station_ids_insufficient"
    return "station_coverage_satisfied"


def _traceability_status(
    *,
    rib_family: str,
    source: str,
    allowable_basis: str,
    evidence_type: str,
    attachment_basis: str,
) -> str:
    if not rib_family:
        return "rib_family_missing"
    if not source:
        return "source_missing"
    if not allowable_basis:
        return "allowable_basis_missing"
    if not evidence_type:
        return "evidence_type_missing"
    if not attachment_basis:
        return "attachment_basis_missing"
    return "traceable_input"


def _write_template(path: Path, check: RibBracingMarginCheck) -> Path:
    fields = [
        "bay_index",
        "start_y_m",
        "end_y_m",
        "required_intermediate_stations",
        "covered_intermediate_station_count",
        "covered_station_ids",
        "recommended_subbay_m",
        "bay_vertical_load_scale_n",
        "required_link_force_n",
        "rib_family",
        "allowable_link_force_n",
        "allowable_shear_force_n",
        "allowable_bond_force_n",
        "allowable_basis",
        "evidence_type",
        "attachment_basis",
        "source",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in check.rows:
            writer.writerow(
                {
                    "bay_index": row.bay_index,
                    "start_y_m": _fmt(row.start_y_m),
                    "end_y_m": _fmt(row.end_y_m),
                    "required_intermediate_stations": row.required_intermediate_stations,
                    "covered_intermediate_station_count": "",
                    "covered_station_ids": "",
                    "recommended_subbay_m": _fmt(row.recommended_subbay_m),
                    "bay_vertical_load_scale_n": _fmt(row.bay_vertical_load_scale_n),
                    "required_link_force_n": _fmt(row.required_link_force_n),
                    "rib_family": "",
                    "allowable_link_force_n": "",
                    "allowable_shear_force_n": "",
                    "allowable_bond_force_n": "",
                    "allowable_basis": "",
                    "evidence_type": "",
                    "attachment_basis": "",
                    "source": "",
                    "notes": "",
                }
            )
    return path


def _write_csv(path: Path, check: RibBracingMarginCheck) -> Path:
    fields = list(asdict(check.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in check.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, check: RibBracingMarginCheck) -> Path:
    path.write_text(json.dumps(asdict(check), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, check: RibBracingMarginCheck) -> Path:
    lines = [
        "# Rib Bracing Margin Inputs",
        "",
        f"Candidate: `{check.candidate_id}`",
        f"Overall status: `{check.overall_status}`",
        "",
        "These are rib bracing input margins, not finite-rib FEM signoff.",
        "",
        f"- finite-rib surrogate requirement row: `{check.finite_rib_variant_id}`",
        f"- required link force: `{check.required_link_force_n:.3f} N`",
        f"- traceability-gap bays: `{check.traceability_gap_count}`",
        f"- station-coverage-gap bays: `{check.station_coverage_gap_count}`",
        "",
        "| bay | y start m | y end m | required stations | covered stations | station ids | status | traceability | station coverage | required link N | link margin N | shear margin N | bond margin N | allowable basis | evidence type | attachment basis | source |",
        "|---:|---:|---:|---:|---:|---|---|---|---|---:|---:|---:|---:|---|---|---|---|",
    ]
    for row in check.rows:
        lines.append(
            f"| {row.bay_index} | {row.start_y_m:.3f} | {row.end_y_m:.3f} | "
            f"{row.required_intermediate_stations} | "
            f"{_fmt_int(row.covered_intermediate_station_count)} | "
            f"{row.covered_station_ids or 'n/a'} | "
            f"`{row.status}` | `{row.traceability_status}` | "
            f"`{row.station_coverage_status}` | {row.required_link_force_n:.3f} | "
            f"{_fmt(row.link_margin_n)} | {_fmt(row.shear_margin_n)} | {_fmt(row.bond_margin_n)} | "
            f"{row.allowable_basis or 'n/a'} | {row.evidence_type or 'n/a'} | "
            f"{row.attachment_basis or 'n/a'} | "
            f"{row.source or 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Positive margins here only mean supplied rib/link/bond numbers exceed the Phase 22 surrogate link-force requirement.",
            "- A traceable rib input requires rib family, source, allowable basis, evidence type, and attachment basis for each bay.",
            "- Each bay-level input must also identify how many required intermediate stations it covers.",
            "- This is not finite-rib FEM signoff and does not close bracing stiffness, station-level spar attachment, cap/web sizing, or full-wing buckling by itself.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _dict_float(row: dict[str, Any] | None, name: str) -> float | None:
    if row is None:
        return None
    value = row.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _dict_int(row: dict[str, Any] | None, name: str) -> int | None:
    if row is None:
        return None
    value = row.get(name)
    if value is None or value == "":
        return None
    return int(float(value))


def _margin(provided: float | None, required: float) -> float | None:
    if provided is None:
        return None
    return float(provided) - float(required)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.3f}"


def _fmt_int(value: int | None) -> str:
    return "" if value is None else str(int(value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--rib-allowables-csv", type=Path)
    args = parser.parse_args(argv)

    model = build_current_candidate_model()
    bracing_audit = build_bracing_sensitivity_audit(CANDIDATE_ID, model)
    spacing_requirements = build_current_rib_spacing_requirements()
    rib_allowables = (
        []
        if args.rib_allowables_csv is None
        else read_rib_allowables_csv(args.rib_allowables_csv)
    )
    outputs = write_rib_bracing_margin_input_package(
        args.output_dir,
        spacing_requirements,
        bracing_audit,
        rib_allowables=rib_allowables,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
