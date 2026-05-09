#!/usr/bin/env python3
"""Triage existing catalogs against local detail and rib allowable blockers."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.phase15_candidate_load_factor_buckling_check import CANDIDATE_ID  # noqa: E402
from scripts.phase28_rib_bracing_margin_inputs import (  # noqa: E402
    build_current_rib_bracing_margin_check,
)
from scripts.phase33_local_detail_subcomponent_margins import (  # noqa: E402
    build_current_local_detail_subcomponent_margin_check,
)
from scripts.phase36_wire_termination_efficiency_sensitivity import (  # noqa: E402
    build_current_wire_termination_efficiency_sensitivity,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase43_existing_detail_allowable_evidence_triage"
DEFAULT_MATERIAL_CATALOG = REPO_ROOT / "data" / "materials.yaml"
DEFAULT_RIB_CATALOG = REPO_ROOT / "data" / "rib_properties.yaml"
DEFAULT_TUBE_CATALOGS = (
    REPO_ROOT / "data" / "carbon_tubes.csv",
    REPO_ROOT / "data" / "real_vendor_tubes.csv",
)
WIRE_BODY_MATERIAL_MARKERS = ("dyneema", "piano_wire")


@dataclass(frozen=True)
class ExistingDetailAllowableEvidenceRow:
    blocker_key: str
    title: str
    status: str
    closes_engineering_margin: bool
    catalog_summary: str
    demand_summary: str
    missing_allowable_rows: int
    moment_allowable_gap_rows: int
    negative_margin_rows: int
    traceability_gap_rows: int
    station_coverage_gap_rows: int
    worst_margin: float | None
    existing_evidence_boundary: str
    missing_for_margin: str
    next_action: str


@dataclass(frozen=True)
class ExistingDetailAllowableEvidenceTriage:
    candidate_id: str
    overall_status: str
    row_count: int
    closing_evidence_count: int
    rows: tuple[ExistingDetailAllowableEvidenceRow, ...]


def build_existing_detail_allowable_evidence_triage(
    candidate_id: str,
    *,
    material_catalog: dict[str, Any],
    tube_catalog_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    rib_catalog: dict[str, Any],
    local_detail_subcomponent_check: Any,
    rib_bracing_margin_check: Any,
    wire_termination_efficiency_sensitivity: Any,
) -> ExistingDetailAllowableEvidenceTriage:
    material_summary = _material_catalog_summary(material_catalog)
    tube_summary = _tube_catalog_summary(tube_catalog_rows)
    rib_summary = _rib_catalog_summary(rib_catalog)
    rows = (
        _local_detail_row(
            "wire_attach_local_load_path",
            "Wire attach local load path",
            local_detail_subcomponent_check,
            catalog_summary=f"{material_summary}; {tube_summary}",
            missing_for_margin=(
                "attach ring/lug/bond/insert/tube-wall local allowables, eccentricity "
                "and local moment, plus local FEM or hand-margin basis"
            ),
            next_action="Select attach hardware and verify lug/ring, bond, insert, and local tube-wall margins.",
        ),
        _local_detail_row(
            "root_joint",
            "Root fitting / clamp / bonded insert",
            local_detail_subcomponent_check,
            catalog_summary=f"{material_summary}; {tube_summary}",
            missing_for_margin=(
                "root fitting, clamp, bonded insert, bearing, tube-wall load-introduction, "
                "and couple-force margins"
            ),
            next_action="Select root joint hardware and close moment-couple, clamp, insert, bond, and tube-wall margins.",
        ),
        _wire_termination_row(
            local_detail_subcomponent_check,
            wire_termination_efficiency_sensitivity,
            material_summary=material_summary,
        ),
        _rib_row(
            "rib_load_transfer",
            "Rib load transfer",
            rib_bracing_margin_check,
            rib_summary=rib_summary,
            missing_for_margin=(
                "finite rib stiffness, rib shear/cap/bond/spar-attach allowables, "
                "and station-by-station load-transfer traceability"
            ),
            next_action="Replace rib proxy evidence with finite-rib stiffness and rib attach allowables.",
        ),
        _rib_row(
            "rib_spacing_assumption",
            "Rib spacing assumption",
            rib_bracing_margin_check,
            rib_summary=rib_summary,
            missing_for_margin=(
                "physical rib station coverage, max unsupported subbay proof, rib stiffness, "
                "and attachment margins at the claimed 0.30 m bracing length"
            ),
            next_action="Verify physical rib/bracing station coverage and stiffness before crediting the 0.30 m bay.",
        ),
    )
    closing_count = sum(1 for row in rows if row.closes_engineering_margin)
    return ExistingDetailAllowableEvidenceTriage(
        candidate_id=str(candidate_id),
        overall_status=(
            "existing_detail_allowables_contain_closure_candidate"
            if closing_count
            else "existing_detail_allowables_do_not_close_goal"
        ),
        row_count=len(rows),
        closing_evidence_count=closing_count,
        rows=rows,
    )


def write_existing_detail_allowable_evidence_triage_package(
    out_dir: Path,
    candidate_id: str,
    *,
    material_catalog: dict[str, Any],
    tube_catalog_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    rib_catalog: dict[str, Any],
    local_detail_subcomponent_check: Any,
    rib_bracing_margin_check: Any,
    wire_termination_efficiency_sensitivity: Any,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    triage = build_existing_detail_allowable_evidence_triage(
        candidate_id,
        material_catalog=material_catalog,
        tube_catalog_rows=tube_catalog_rows,
        rib_catalog=rib_catalog,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        rib_bracing_margin_check=rib_bracing_margin_check,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
    )
    return [
        _write_csv(out_dir / "existing_detail_allowable_evidence_triage.csv", triage),
        _write_json(out_dir / "existing_detail_allowable_evidence_triage.json", triage),
        _write_markdown(out_dir / "existing_detail_allowable_evidence_triage.md", triage),
    ]


def build_current_existing_detail_allowable_evidence_triage() -> (
    ExistingDetailAllowableEvidenceTriage
):
    return build_existing_detail_allowable_evidence_triage(
        CANDIDATE_ID,
        material_catalog=_read_yaml(DEFAULT_MATERIAL_CATALOG),
        tube_catalog_rows=tuple(
            row
            for path in DEFAULT_TUBE_CATALOGS
            for row in _read_csv(path)
        ),
        rib_catalog=_read_yaml(DEFAULT_RIB_CATALOG),
        local_detail_subcomponent_check=build_current_local_detail_subcomponent_margin_check(),
        rib_bracing_margin_check=build_current_rib_bracing_margin_check(),
        wire_termination_efficiency_sensitivity=build_current_wire_termination_efficiency_sensitivity(),
    )


def _local_detail_row(
    blocker_key: str,
    title: str,
    check: Any,
    *,
    catalog_summary: str,
    missing_for_margin: str,
    next_action: str,
) -> ExistingDetailAllowableEvidenceRow:
    rows = _local_rows(check, blocker_key)
    counts = _local_counts(rows)
    return ExistingDetailAllowableEvidenceRow(
        blocker_key=blocker_key,
        title=title,
        status=_local_status(counts),
        closes_engineering_margin=False,
        catalog_summary=catalog_summary,
        demand_summary=_local_demand_summary(rows),
        missing_allowable_rows=counts["missing"],
        moment_allowable_gap_rows=counts["moment_missing"],
        negative_margin_rows=counts["negative"],
        traceability_gap_rows=counts["traceability_gap"],
        station_coverage_gap_rows=0,
        worst_margin=_worst_margin(rows),
        existing_evidence_boundary=(
            "Material and tube catalogs provide screening properties or tube geometry; "
            "they do not define selected local hardware allowables."
        ),
        missing_for_margin=missing_for_margin,
        next_action=next_action,
    )


def _wire_termination_row(
    check: Any,
    sensitivity: Any,
    *,
    material_summary: str,
) -> ExistingDetailAllowableEvidenceRow:
    rows = _local_rows(check, "wire_termination")
    counts = _local_counts(rows)
    return ExistingDetailAllowableEvidenceRow(
        blocker_key="wire_termination",
        title="Wire termination / end fitting",
        status="material_body_strength_not_termination_allowable",
        closes_engineering_margin=False,
        catalog_summary=material_summary,
        demand_summary=_wire_termination_demand_summary(rows, sensitivity),
        missing_allowable_rows=counts["missing"],
        moment_allowable_gap_rows=counts["moment_missing"],
        negative_margin_rows=counts["negative"],
        traceability_gap_rows=counts["traceability_gap"],
        station_coverage_gap_rows=0,
        worst_margin=_worst_margin(rows),
        existing_evidence_boundary=(
            "Wire/cable material tensile strength is cable-body evidence only; it is not "
            "a swage, splice, knot, end anchor, pin, bend-radius, creep, or abrasion allowable."
        ),
        missing_for_margin=(
            "selected termination hardware/process, MBL, efficiency or derate, pin/anchor, "
            "bend-radius, creep, abrasion, and traceable source"
        ),
        next_action="Select termination hardware/process and verify effective termination load margin.",
    )


def _rib_row(
    blocker_key: str,
    title: str,
    check: Any,
    *,
    rib_summary: str,
    missing_for_margin: str,
    next_action: str,
) -> ExistingDetailAllowableEvidenceRow:
    rows = tuple(getattr(check, "rows", ()))
    missing = sum(
        1
        for row in rows
        if getattr(row, "status", "")
        in {"rib_allowable_missing", "rib_stiffness_or_allowable_missing"}
    )
    negative = sum(1 for row in rows if getattr(row, "status", "") == "margin_negative")
    traceability_gap = sum(1 for row in rows if getattr(row, "status", "") == "rib_traceability_missing")
    station_gap = sum(
        1 for row in rows if getattr(row, "status", "") == "rib_station_coverage_missing"
    )
    return ExistingDetailAllowableEvidenceRow(
        blocker_key=blocker_key,
        title=title,
        status="rib_catalog_proxy_not_margin",
        closes_engineering_margin=False,
        catalog_summary=rib_summary,
        demand_summary=(
            "required link force="
            f"{_fmt(_attr_float(check, 'required_link_force_n'))} N"
        ),
        missing_allowable_rows=missing,
        moment_allowable_gap_rows=0,
        negative_margin_rows=negative,
        traceability_gap_rows=traceability_gap,
        station_coverage_gap_rows=station_gap,
        worst_margin=_worst_margin(rows),
        existing_evidence_boundary=(
            "Rib family and spacing catalogs are proxy/layout evidence; they do not prove "
            "finite rib stiffness, shear/cap/bond strength, or spar-attachment margins."
        ),
        missing_for_margin=missing_for_margin,
        next_action=next_action,
    )


def _local_rows(check: Any, parent_key: str) -> tuple[Any, ...]:
    return tuple(
        row for row in getattr(check, "rows", ()) if getattr(row, "parent_key", "") == parent_key
    )


def _local_counts(rows: tuple[Any, ...]) -> dict[str, int]:
    return {
        "missing": sum(
            1
            for row in rows
            if getattr(row, "status", "")
            in {"subcomponent_allowable_missing", "subcomponent_moment_allowable_missing"}
        ),
        "moment_missing": sum(
            1
            for row in rows
            if getattr(row, "status", "") == "subcomponent_moment_allowable_missing"
        ),
        "negative": sum(1 for row in rows if getattr(row, "status", "") == "margin_negative"),
        "traceability_gap": sum(
            1 for row in rows if getattr(row, "status", "") == "subcomponent_traceability_missing"
        ),
    }


def _local_status(counts: dict[str, int]) -> str:
    if counts["negative"]:
        return "local_subcomponent_margin_negative"
    if counts["missing"] or counts["moment_missing"]:
        return "local_subcomponent_allowables_missing"
    if counts["traceability_gap"]:
        return "local_subcomponent_traceability_missing"
    return "local_subcomponent_inputs_positive_not_fem_signoff"


def _local_demand_summary(rows: tuple[Any, ...]) -> str:
    loads = [_attr_float(row, "required_allowable_load_n") for row in rows]
    moments = [_attr_float(row, "required_allowable_moment_n_m") for row in rows]
    mbls = [_attr_float(row, "required_minimum_breaking_load_n") for row in rows]
    return (
        "required load="
        f"{_fmt(max(value for value in loads if value is not None) if any(value is not None for value in loads) else None)} N; "
        "required moment="
        f"{_fmt(max(value for value in moments if value is not None) if any(value is not None for value in moments) else None)} N*m; "
        "required MBL="
        f"{_fmt(max(value for value in mbls if value is not None) if any(value is not None for value in mbls) else None)} N"
    )


def _wire_termination_demand_summary(rows: tuple[Any, ...], sensitivity: Any) -> str:
    eta_rows = {
        float(getattr(row, "termination_efficiency")): row
        for row in getattr(sensitivity, "rows", ())
        if getattr(row, "termination_efficiency", None) is not None
    }
    eta_060 = eta_rows.get(0.6)
    eta_040 = eta_rows.get(0.4)
    return (
        f"{_local_demand_summary(rows)}; "
        "eta 0.60 MBL="
        f"{_fmt(_attr_float(eta_060, 'required_minimum_breaking_load_n') if eta_060 else None)} N; "
        "eta 0.40 MBL="
        f"{_fmt(_attr_float(eta_040, 'required_minimum_breaking_load_n') if eta_040 else None)} N"
    )


def _material_catalog_summary(catalog: dict[str, Any]) -> str:
    wire_keys = sorted(
        key
        for key in catalog
        if any(marker in key.lower() for marker in WIRE_BODY_MATERIAL_MARKERS)
    )
    return (
        "wire body material keys="
        f"{';'.join(wire_keys) if wire_keys else 'none'}; "
        "material entries="
        f"{len(catalog)}"
    )


def _tube_catalog_summary(rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str:
    vendors = sorted({str(row.get("vendor", "")).strip() for row in rows if row.get("vendor")})
    return (
        "tube catalog rows="
        f"{len(rows)}; "
        "tube vendors="
        f"{';'.join(vendors) if vendors else 'none'}"
    )


def _rib_catalog_summary(catalog: dict[str, Any]) -> str:
    families = catalog.get("families", {}) if isinstance(catalog, dict) else {}
    family_keys = sorted(str(key) for key in families)
    default_family = catalog.get("metadata", {}).get("default_family", "") if isinstance(catalog, dict) else ""
    default_spacing = catalog.get("metadata", {}).get("default_spacing_m", "") if isinstance(catalog, dict) else ""
    return (
        "rib families="
        f"{';'.join(family_keys) if family_keys else 'none'}; "
        "default family="
        f"{default_family or 'unknown'}; "
        "default spacing="
        f"{default_spacing or 'unknown'} m"
    )


def _worst_margin(rows: tuple[Any, ...]) -> float | None:
    values = [
        _attr_float(row, name)
        for row in rows
        for name in (
            "worst_margin",
            "worst_margin_n",
            "load_margin_n",
            "moment_margin_n_m",
            "mbl_margin_n",
            "effective_termination_load_margin_n",
            "link_margin_n",
            "shear_margin_n",
            "bond_margin_n",
        )
    ]
    finite = [value for value in values if value is not None]
    return min(finite) if finite else None


def _attr_float(obj: Any | None, name: str) -> float | None:
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value in (None, ""):
        return None
    return float(value)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _read_csv(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


def _write_csv(path: Path, triage: ExistingDetailAllowableEvidenceTriage) -> Path:
    fields = list(asdict(triage.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in triage.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, triage: ExistingDetailAllowableEvidenceTriage) -> Path:
    path.write_text(
        json.dumps(asdict(triage), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, triage: ExistingDetailAllowableEvidenceTriage) -> Path:
    lines = [
        "# Existing Detail Allowable Evidence Triage",
        "",
        f"Candidate: `{triage.candidate_id}`",
        f"Overall status: `{triage.overall_status}`",
        "",
        "Existing material, tube, and rib catalogs cannot close local hardware margins by themselves.",
        "",
        f"- rows: `{triage.row_count}`",
        f"- closing evidence rows: `{triage.closing_evidence_count}`",
        "",
        "| blocker | status | closes margin | catalog boundary | demand | missing for margin |",
        "|---|---|---:|---|---|---|",
    ]
    for row in triage.rows:
        lines.append(
            f"| {row.title} | `{row.status}` | `{row.closes_engineering_margin}` | "
            f"{row.existing_evidence_boundary} | {row.demand_summary} | {row.missing_for_margin} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- Tube/material strength values are not lug, bond, insert, clamp, termination, or rib-attachment allowables.",
            "- Rib family catalogs are stiffness/layout proxies until finite-rib stiffness and attachment margins are supplied.",
            "- Positive detail inputs, if added later, still need traceability and are not local FEM signoff by themselves.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    triage = build_current_existing_detail_allowable_evidence_triage()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        _write_csv(args.output_dir / "existing_detail_allowable_evidence_triage.csv", triage),
        _write_json(args.output_dir / "existing_detail_allowable_evidence_triage.json", triage),
        _write_markdown(args.output_dir / "existing_detail_allowable_evidence_triage.md", triage),
    ]
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
