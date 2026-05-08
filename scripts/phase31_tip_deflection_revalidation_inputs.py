#!/usr/bin/env python3
"""Check proposed tip-deflection limit relaxations against revalidation requirements."""
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

from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    load_current_candidate_reference,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase31_tip_deflection_revalidation_inputs"
TIP_DEFLECTION_TOLERANCE_FACTOR = 1.02
EXPLORATION_RAW_LIMIT_CEILING_M = 3.0
ACCEPTED_USAGE_CONTEXTS = ("exploration", "submission")
RECHECK_FIELDS = (
    "loaded_shape_rechecked",
    "aeroelastic_rechecked",
    "clearance_rechecked",
    "load_path_rechecked",
)


@dataclass(frozen=True)
class TipDeflectionRevalidationRow:
    case_id: str
    usage_context: str
    status: str
    current_raw_tip_limit_m: float
    current_effective_tip_limit_m: float
    proposed_raw_tip_limit_m: float | None
    proposed_effective_tip_limit_m: float | None
    deflection_limit_load_factor: float | None
    loaded_shape_rechecked: bool
    aeroelastic_rechecked: bool
    clearance_rechecked: bool
    load_path_rechecked: bool
    missing_rechecks: str
    source: str
    engineering_note: str


@dataclass(frozen=True)
class TipDeflectionRevalidationCheck:
    candidate_id: str
    overall_status: str
    accepted_usage_contexts: tuple[str, ...]
    current_raw_tip_limit_m: float
    current_effective_tip_limit_m: float
    rows: tuple[TipDeflectionRevalidationRow, ...]


def build_tip_deflection_revalidation_check(
    reference: Any,
    *,
    revalidation_inputs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> TipDeflectionRevalidationCheck:
    current_raw = _current_raw_limit_m(reference)
    current_effective = float(reference.tip_deflection_limit_m)
    rows = (
        (_current_gate_row(reference, current_raw=current_raw),)
        if not revalidation_inputs
        else tuple(_build_row(reference, raw, current_raw=current_raw) for raw in revalidation_inputs)
    )
    all_current = rows and all(row.status == "current_submission_gate_retained" for row in rows)
    all_revalidated = rows and all(
        row.status in {
            "current_submission_gate_retained",
            "submission_revalidation_input_check_only",
        }
        for row in rows
    )
    return TipDeflectionRevalidationCheck(
        candidate_id=str(reference.candidate_id),
        overall_status=(
            "tip_deflection_current_submission_gate_retained"
            if all_current
            else (
                "tip_deflection_revalidation_inputs_pass_not_submission_signoff"
                if all_revalidated
                else "tip_deflection_submission_gate_not_revalidated"
            )
        ),
        accepted_usage_contexts=ACCEPTED_USAGE_CONTEXTS,
        current_raw_tip_limit_m=current_raw,
        current_effective_tip_limit_m=current_effective,
        rows=rows,
    )


def write_tip_deflection_revalidation_input_package(
    out_dir: Path,
    reference: Any,
    *,
    revalidation_inputs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    check = build_tip_deflection_revalidation_check(
        reference,
        revalidation_inputs=revalidation_inputs,
    )
    return [
        _write_template(out_dir / "tip_deflection_revalidation_inputs_template.csv", check),
        _write_csv(out_dir / "tip_deflection_revalidation_check.csv", check),
        _write_json(out_dir / "tip_deflection_revalidation_check.json", check),
        _write_markdown(out_dir / "tip_deflection_revalidation_check.md", check),
    ]


def read_tip_deflection_revalidation_inputs_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_current_tip_deflection_revalidation_check() -> TipDeflectionRevalidationCheck:
    return build_tip_deflection_revalidation_check(
        load_current_candidate_reference(),
        revalidation_inputs=[],
    )


def _build_row(
    reference: Any,
    raw: dict[str, Any],
    *,
    current_raw: float,
) -> TipDeflectionRevalidationRow:
    usage_context = str(raw.get("usage_context", ""))
    proposed_raw = _dict_float(raw, "proposed_raw_tip_limit_m")
    proposed_effective = _effective_limit_m(proposed_raw)
    load_factor = _deflection_limit_load_factor(reference, proposed_effective)
    rechecks = {
        field: _dict_bool(raw, field)
        for field in RECHECK_FIELDS
    }
    missing_rechecks = ";".join(field for field in RECHECK_FIELDS if not rechecks[field])
    status = _status(
        usage_context=usage_context,
        proposed_raw=proposed_raw,
        current_raw=current_raw,
        missing_rechecks=missing_rechecks,
    )
    return TipDeflectionRevalidationRow(
        case_id=str(raw.get("case_id", "")),
        usage_context=usage_context,
        status=status,
        current_raw_tip_limit_m=current_raw,
        current_effective_tip_limit_m=float(reference.tip_deflection_limit_m),
        proposed_raw_tip_limit_m=proposed_raw,
        proposed_effective_tip_limit_m=proposed_effective,
        deflection_limit_load_factor=load_factor,
        loaded_shape_rechecked=rechecks["loaded_shape_rechecked"],
        aeroelastic_rechecked=rechecks["aeroelastic_rechecked"],
        clearance_rechecked=rechecks["clearance_rechecked"],
        load_path_rechecked=rechecks["load_path_rechecked"],
        missing_rechecks=missing_rechecks,
        source=str(raw.get("source", "")),
        engineering_note=_engineering_note(status),
    )


def _current_gate_row(reference: Any, *, current_raw: float) -> TipDeflectionRevalidationRow:
    return TipDeflectionRevalidationRow(
        case_id="current_2p5m_submission_gate",
        usage_context="submission",
        status="current_submission_gate_retained",
        current_raw_tip_limit_m=current_raw,
        current_effective_tip_limit_m=float(reference.tip_deflection_limit_m),
        proposed_raw_tip_limit_m=current_raw,
        proposed_effective_tip_limit_m=float(reference.tip_deflection_limit_m),
        deflection_limit_load_factor=_deflection_limit_load_factor(
            reference,
            float(reference.tip_deflection_limit_m),
        ),
        loaded_shape_rechecked=False,
        aeroelastic_rechecked=False,
        clearance_rechecked=False,
        load_path_rechecked=False,
        missing_rechecks="",
        source="current configuration",
        engineering_note="Current 2.5 m raw submission/design-validity gate is retained.",
    )


def _status(
    *,
    usage_context: str,
    proposed_raw: float | None,
    current_raw: float,
    missing_rechecks: str,
) -> str:
    if usage_context not in ACCEPTED_USAGE_CONTEXTS:
        return "invalid_usage_context"
    if proposed_raw is None:
        return "revalidation_input_incomplete"
    if proposed_raw <= current_raw + 1.0e-12:
        return "current_submission_gate_retained"
    if usage_context == "exploration":
        if proposed_raw > EXPLORATION_RAW_LIMIT_CEILING_M:
            return "relaxation_not_recommended"
        return "exploration_only_not_submission"
    if missing_rechecks:
        return "submission_revalidation_missing"
    return "submission_revalidation_input_check_only"


def _engineering_note(status: str) -> str:
    if status == "exploration_only_not_submission":
        return (
            "Relaxation is limited to exploration; do not use it for submission without "
            "loaded-shape, aeroelastic, clearance, and load-path rechecks."
        )
    if status == "submission_revalidation_missing":
        return (
            "A relaxed submission gate must include loaded-shape, aeroelastic, clearance, "
            "and load-path revalidation evidence."
        )
    if status == "relaxation_not_recommended":
        return "Relaxation beyond 3.0 m raw is not recommended without a new validation basis."
    if status == "invalid_usage_context":
        return "Use usage_context exploration or submission."
    return "Input check only; this is not a fracture point or standalone submission signoff."


def _write_template(path: Path, check: TipDeflectionRevalidationCheck) -> Path:
    fields = [
        "case_id",
        "usage_context",
        "accepted_usage_contexts",
        "current_raw_tip_limit_m",
        "current_effective_tip_limit_m",
        "proposed_raw_tip_limit_m",
        "loaded_shape_rechecked",
        "aeroelastic_rechecked",
        "clearance_rechecked",
        "load_path_rechecked",
        "source",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for usage_context, proposed in (("exploration", 2.75), ("submission", 2.50)):
            writer.writerow(
                {
                    "case_id": f"{usage_context}_tip_limit_case",
                    "usage_context": usage_context,
                    "accepted_usage_contexts": ";".join(ACCEPTED_USAGE_CONTEXTS),
                    "current_raw_tip_limit_m": _fmt(check.current_raw_tip_limit_m),
                    "current_effective_tip_limit_m": _fmt(check.current_effective_tip_limit_m),
                    "proposed_raw_tip_limit_m": _fmt(proposed),
                    "loaded_shape_rechecked": "false",
                    "aeroelastic_rechecked": "false",
                    "clearance_rechecked": "false",
                    "load_path_rechecked": "false",
                    "source": "",
                    "notes": "Submission relaxation requires all rechecks marked true.",
                }
            )
    return path


def _write_csv(path: Path, check: TipDeflectionRevalidationCheck) -> Path:
    fields = list(asdict(check.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in check.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, check: TipDeflectionRevalidationCheck) -> Path:
    path.write_text(json.dumps(asdict(check), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, check: TipDeflectionRevalidationCheck) -> Path:
    lines = [
        "# Tip Deflection Revalidation Inputs",
        "",
        f"Candidate: `{check.candidate_id}`",
        f"Overall status: `{check.overall_status}`",
        "",
        "These are tip-deflection revalidation inputs. The 2.5 m raw gate is not a fracture point.",
        "",
        "| case | context | status | raw limit m | effective limit m | n limit | missing rechecks | source |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in check.rows:
        lines.append(
            f"| {row.case_id} | {row.usage_context} | `{row.status}` | "
            f"{_fmt(row.proposed_raw_tip_limit_m)} | {_fmt(row.proposed_effective_tip_limit_m)} | "
            f"{_fmt(row.deflection_limit_load_factor)} | {row.missing_rechecks or 'none'} | "
            f"{row.source or 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Retaining the current 2.5 m raw limit keeps it as a design-validity/submission gate.",
            "- Exploration-only relaxations are not submission evidence.",
            "- Submission relaxation requires loaded-shape, aeroelastic, clearance, and load-path rechecks.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _current_raw_limit_m(reference: Any) -> float:
    return float(reference.tip_deflection_limit_m) / TIP_DEFLECTION_TOLERANCE_FACTOR


def _effective_limit_m(raw_limit_m: float | None) -> float | None:
    if raw_limit_m is None:
        return None
    return float(raw_limit_m) * TIP_DEFLECTION_TOLERANCE_FACTOR


def _deflection_limit_load_factor(reference: Any, effective_limit_m: float | None) -> float | None:
    if effective_limit_m is None or float(reference.tip_deflection_m) <= 0.0:
        return None
    return (
        float(reference.reference_load_factor)
        * float(effective_limit_m)
        / float(reference.tip_deflection_m)
    )


def _dict_float(row: dict[str, Any], name: str) -> float | None:
    value = row.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _dict_bool(row: dict[str, Any], name: str) -> bool:
    value = row.get(name)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "pass", "checked"}


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--revalidation-inputs-csv", type=Path)
    args = parser.parse_args(argv)

    reference = load_current_candidate_reference()
    revalidation_inputs = (
        []
        if args.revalidation_inputs_csv is None
        else read_tip_deflection_revalidation_inputs_csv(args.revalidation_inputs_csv)
    )
    outputs = write_tip_deflection_revalidation_input_package(
        args.output_dir,
        reference,
        revalidation_inputs=revalidation_inputs,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
