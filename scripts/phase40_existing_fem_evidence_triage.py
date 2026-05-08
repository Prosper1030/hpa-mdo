#!/usr/bin/env python3
"""Triage existing FEM artifacts against the structural closure goal."""
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


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase40_existing_fem_evidence_triage"
DEFAULT_CANDIDATE_STATIC_SUMMARY = (
    REPO_ROOT
    / "output"
    / "go_mode_fem_validation_repair"
    / "candidate_linearized_wire_surrogate"
    / "fem_load_factor_summary.csv"
)
DEFAULT_HIFI_STRUCTURAL_CHECKS = (
    REPO_ROOT
    / "output"
    / "blackcat_004"
    / "hifi_support_reaction_rerun_20260418"
    / "structural_check.json",
    REPO_ROOT
    / "output"
    / "blackcat_004"
    / "hifi_support_reaction_rerun_20260418_discrete_1p0"
    / "structural_check.json",
)


@dataclass(frozen=True)
class ExistingFemEvidenceRow:
    case_id: str
    artifact_kind: str
    model_scope: str
    status: str
    closes_full_wing_buckling_claim: bool
    closes_rear_spar_rib_bracing: bool
    closes_local_detail_hardware: bool
    claim_load_factor_coverage: str
    key_metric: str
    source: str
    engineering_note: str
    next_action: str


@dataclass(frozen=True)
class ExistingFemEvidenceTriage:
    candidate_id: str
    overall_status: str
    row_count: int
    closing_evidence_count: int
    rows: tuple[ExistingFemEvidenceRow, ...]


def build_existing_fem_evidence_triage(
    candidate_id: str,
    *,
    candidate_static_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    hifi_structural_checks: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> ExistingFemEvidenceTriage:
    rows: list[ExistingFemEvidenceRow] = []
    if candidate_static_rows:
        rows.append(_candidate_static_row(candidate_static_rows))
    rows.extend(_hifi_structural_check_row(raw) for raw in hifi_structural_checks)
    closing_count = sum(
        1
        for row in rows
        if row.closes_full_wing_buckling_claim
        or row.closes_rear_spar_rib_bracing
        or row.closes_local_detail_hardware
    )
    return ExistingFemEvidenceTriage(
        candidate_id=str(candidate_id),
        overall_status=(
            "existing_fem_evidence_contains_closure_candidate"
            if closing_count
            else "existing_fem_evidence_does_not_close_goal"
        ),
        row_count=len(rows),
        closing_evidence_count=closing_count,
        rows=tuple(rows),
    )


def write_existing_fem_evidence_triage_package(
    out_dir: Path,
    candidate_id: str,
    *,
    candidate_static_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    hifi_structural_checks: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    triage = build_existing_fem_evidence_triage(
        candidate_id,
        candidate_static_rows=candidate_static_rows,
        hifi_structural_checks=hifi_structural_checks,
    )
    return [
        _write_csv(out_dir / "existing_fem_evidence_triage.csv", triage),
        _write_json(out_dir / "existing_fem_evidence_triage.json", triage),
        _write_markdown(out_dir / "existing_fem_evidence_triage.md", triage),
    ]


def read_candidate_static_summary_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_hifi_structural_check_json(path: Path, *, case_id: str | None = None) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw["_case_id"] = case_id or path.parent.name
    raw["_source"] = str(path)
    return raw


def build_current_existing_fem_evidence_triage() -> ExistingFemEvidenceTriage:
    return build_existing_fem_evidence_triage(
        CANDIDATE_ID,
        candidate_static_rows=read_candidate_static_summary_csv(DEFAULT_CANDIDATE_STATIC_SUMMARY),
        hifi_structural_checks=tuple(
            read_hifi_structural_check_json(path)
            for path in DEFAULT_HIFI_STRUCTURAL_CHECKS
            if path.exists()
        ),
    )


def _candidate_static_row(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> ExistingFemEvidenceRow:
    load_factors = sorted(
        {
            round(float(row["load_factor"]), 2)
            for row in rows
            if str(row.get("calculix_status", "")).strip() == "ran"
            and str(row.get("load_factor", "")).strip()
        }
    )
    max_tip_error = _max_float(rows, "tip_error_pct")
    max_root_error = _max_float(rows, "root_reaction_error_pct")
    max_wire_error = _max_float(rows, "wire_reaction_error_pct")
    source = _first_nonempty(rows, "calculix_deck")
    return ExistingFemEvidenceRow(
        case_id="candidate_equivalent_static_reference",
        artifact_kind="candidate_static_load_factor_fem",
        model_scope="equivalent_dual_beam_static_reference",
        status="equivalent_static_reference_not_global_buckling",
        closes_full_wing_buckling_claim=False,
        closes_rear_spar_rib_bracing=False,
        closes_local_detail_hardware=False,
        claim_load_factor_coverage=";".join(f"{value:.2f}" for value in load_factors),
        key_metric=(
            f"max tip error={_fmt(max_tip_error)}%; "
            f"max root reaction error={_fmt(max_root_error)}%; "
            f"max wire reaction error={_fmt(max_wire_error)}%"
        ),
        source=source,
        engineering_note=(
            "Candidate CalculiX evidence is useful equivalent-physics static reference context, "
            "but it has no global BUCKLE step, no finite-rib stiffness proof, and no local hardware margins."
        ),
        next_action=(
            "Use as a static reference only; run a braced/full-wing eigen model before any "
            "1.5G/1.75G full-wing pass claim."
        ),
    )


def _hifi_structural_check_row(raw: dict[str, Any]) -> ExistingFemEvidenceRow:
    case_id = str(raw.get("_case_id", "hifi_structural_check"))
    buckle = raw.get("buckle", {}) if isinstance(raw.get("buckle", {}), dict) else {}
    mesh = _first_mapping(raw, ("mesh_diagnostics", "mesh"))
    overall = str(raw.get("overall_comparability", "unknown"))
    buckle_comp = str(buckle.get("comparability", "unknown"))
    analysis_reality = str(mesh.get("analysis_reality", raw.get("analysis_reality", "unknown")))
    closes = overall == "COMPARABLE" and buckle_comp == "COMPARABLE"
    status = (
        "hifi_buckle_candidate_for_manual_review"
        if closes
        else "limited_hifi_buckle_not_phase30_closure"
    )
    return ExistingFemEvidenceRow(
        case_id=case_id,
        artifact_kind="hifi_structural_check",
        model_scope=analysis_reality,
        status=status,
        closes_full_wing_buckling_claim=False,
        closes_rear_spar_rib_bracing=False,
        closes_local_detail_hardware=False,
        claim_load_factor_coverage="",
        key_metric=(
            f"overall comparability={overall}; "
            f"buckle comparability={buckle_comp}; "
            f"message={buckle.get('message', 'n/a')}"
        ),
        source=str(raw.get("_source", buckle.get("artifact_path", ""))),
        engineering_note=(
            "Existing hi-fi BUCKLE output is inspection evidence only unless it has a qualified "
            "claim-load-factor margin, component coverage, convergence, and mode review. A LIMITED "
            "run with no reference buckling index cannot close Phase30."
        ),
        next_action=(
            "Convert the model into Phase30 closure input only after documenting model scope, included "
            "components, first global buckling load factor, mesh convergence, solver status, and mode review."
        ),
    )


def _first_mapping(raw: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        value = raw.get(key, {})
        if isinstance(value, dict):
            return value
    return {}


def _max_float(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...], key: str) -> float | None:
    values = [_dict_float(row, key) for row in rows]
    finite = [value for value in values if value is not None]
    return max(finite) if finite else None


def _first_nonempty(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...], key: str) -> str:
    for row in rows:
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def _dict_float(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None or value == "":
        return None
    return float(value)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def _write_csv(path: Path, triage: ExistingFemEvidenceTriage) -> Path:
    fields = list(asdict(triage.rows[0]).keys()) if triage.rows else list(ExistingFemEvidenceRow.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in triage.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, triage: ExistingFemEvidenceTriage) -> Path:
    path.write_text(json.dumps(asdict(triage), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, triage: ExistingFemEvidenceTriage) -> Path:
    lines = [
        "# Existing FEM Evidence Triage",
        "",
        f"Candidate: `{triage.candidate_id}`",
        f"Overall status: `{triage.overall_status}`",
        "",
        "This triage does not close the structural goal by itself. It classifies existing FEM artifacts so they are not mistaken for full-wing global buckling, braced rib/rear-spar, or hardware signoff.",
        "",
        f"- rows: `{triage.row_count}`",
        f"- closing evidence rows: `{triage.closing_evidence_count}`",
        "",
        "| case | status | scope | closes full-wing global buckling | closes details | coverage | key metric |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for row in triage.rows:
        lines.append(
            f"| {row.case_id} | `{row.status}` | `{row.model_scope}` | "
            f"`{row.closes_full_wing_buckling_claim}` | `{row.closes_local_detail_hardware}` | "
            f"{row.claim_load_factor_coverage or 'n/a'} | {row.key_metric} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- Equivalent static FEM agreement is reference context, not global buckling evidence.",
            "- LIMITED hi-fi BUCKLE runs with no reference buckling index or reviewed load-factor margin do not close Phase30.",
            "- Full-wing global buckling closure still needs a qualified full-wing or braced-subassembly eigen model with main spar, rear spar, finite ribs, wire-attach load path, root boundary, mesh convergence, solver status, and mode review.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--candidate-static-summary", type=Path, default=DEFAULT_CANDIDATE_STATIC_SUMMARY)
    parser.add_argument(
        "--hifi-structural-check",
        type=Path,
        action="append",
        default=None,
        help="Path to a structural_check.json artifact. May be repeated.",
    )
    args = parser.parse_args(argv)

    hifi_paths = tuple(args.hifi_structural_check or DEFAULT_HIFI_STRUCTURAL_CHECKS)
    outputs = write_existing_fem_evidence_triage_package(
        args.output_dir,
        CANDIDATE_ID,
        candidate_static_rows=read_candidate_static_summary_csv(args.candidate_static_summary),
        hifi_structural_checks=tuple(
            read_hifi_structural_check_json(path)
            for path in hifi_paths
            if path.exists()
        ),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
