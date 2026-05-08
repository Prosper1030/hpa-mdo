#!/usr/bin/env python3
"""Diagnose rear-spar and rib-bracing effects without promoting them to signoff."""
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


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase32_rear_spar_rib_bracing_diagnostic"
MODEL_BIAS_GUARDRAIL = "internal_model_bias_guardrail_required"


@dataclass(frozen=True)
class RearSparRibBracingDiagnosticRow:
    key: str
    title: str
    source_variant_id: str
    status: str
    tip_delta_pct: float
    max_vertical_delta_pct: float
    angle_delta_deg: float
    link_force_max_n: float
    model_bias_guardrail: str
    engineering_read: str
    next_evidence: str


@dataclass(frozen=True)
class RearSparRibBracingDiagnostic:
    candidate_id: str
    overall_status: str
    rows: tuple[RearSparRibBracingDiagnosticRow, ...]


def build_rear_spar_rib_bracing_diagnostic(
    bracing_audit: Any,
) -> RearSparRibBracingDiagnostic:
    rows_by_variant = {str(row.variant_id): row for row in getattr(bracing_audit, "rows", ())}
    rear_soft = rows_by_variant.get("rear_stiffness_5pct")
    dense_finite = rows_by_variant.get("dense_finite_rib_surrogate")
    rows = (
        _rear_spar_row(rear_soft),
        _rib_load_transfer_row(dense_finite),
    )
    return RearSparRibBracingDiagnostic(
        candidate_id=str(bracing_audit.candidate_id),
        overall_status="bracing_effective_but_not_signed_off",
        rows=rows,
    )


def write_rear_spar_rib_bracing_diagnostic_package(
    out_dir: Path,
    bracing_audit: Any,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    diagnostic = build_rear_spar_rib_bracing_diagnostic(bracing_audit)
    return [
        _write_csv(out_dir / "rear_spar_rib_bracing_diagnostic.csv", diagnostic),
        _write_json(out_dir / "rear_spar_rib_bracing_diagnostic.json", diagnostic),
        _write_markdown(out_dir / "rear_spar_rib_bracing_diagnostic.md", diagnostic),
    ]


def build_current_rear_spar_rib_bracing_diagnostic() -> RearSparRibBracingDiagnostic:
    model = build_current_candidate_model()
    audit = build_bracing_sensitivity_audit(CANDIDATE_ID, model)
    return build_rear_spar_rib_bracing_diagnostic(audit)


def _rear_spar_row(row: Any | None) -> RearSparRibBracingDiagnosticRow:
    tip_delta = _attr_float(row, "tip_main_delta_vs_baseline_pct")
    max_vertical_delta = _attr_float(row, "max_vertical_delta_vs_baseline_pct")
    angle_delta = _attr_float(row, "angle_delta_vs_baseline_deg")
    link_force = _attr_float(row, "link_force_max_n")
    return RearSparRibBracingDiagnosticRow(
        key="rear_spar_stiffness",
        title="Rear spar stiffness participation",
        source_variant_id="rear_stiffness_5pct" if row is not None else "",
        status=(
            "strong_model_sensitivity_not_signoff"
            if tip_delta is not None and abs(tip_delta) >= 25.0
            else "model_sensitivity_weak_or_missing"
        ),
        tip_delta_pct=tip_delta or 0.0,
        max_vertical_delta_pct=max_vertical_delta or 0.0,
        angle_delta_deg=angle_delta or 0.0,
        link_force_max_n=link_force or 0.0,
        model_bias_guardrail=MODEL_BIAS_GUARDRAIL,
        engineering_read=(
            "rear spar cannot be ignored: softening rear stiffness materially changes tip motion and "
            "spar-pair angle in the current beam model. This is participation evidence, not FEM signoff."
        ),
        next_evidence=(
            "Run a dual-spar finite-rib FEM or ANSYS/CalculiX braced-subassembly check to quantify "
            "load sharing with model-bias correction."
        ),
    )


def _rib_load_transfer_row(row: Any | None) -> RearSparRibBracingDiagnosticRow:
    tip_delta = _attr_float(row, "tip_main_delta_vs_baseline_pct")
    max_vertical_delta = _attr_float(row, "max_vertical_delta_vs_baseline_pct")
    angle_delta = _attr_float(row, "angle_delta_vs_baseline_deg")
    link_force = _attr_float(row, "link_force_max_n")
    return RearSparRibBracingDiagnosticRow(
        key="rib_load_transfer",
        title="Rib load transfer and bracing",
        source_variant_id="dense_finite_rib_surrogate" if row is not None else "",
        status=(
            "surrogate_load_transfer_not_signoff"
            if link_force is not None and link_force > 0.0
            else "surrogate_load_transfer_missing"
        ),
        tip_delta_pct=tip_delta or 0.0,
        max_vertical_delta_pct=max_vertical_delta or 0.0,
        angle_delta_deg=angle_delta or 0.0,
        link_force_max_n=link_force or 0.0,
        model_bias_guardrail=MODEL_BIAS_GUARDRAIL,
        engineering_read=(
            "Dense finite-rib surrogate transfers load and changes deflection/twist response, but it is "
            "still a surrogate link model rather than physical rib shear, cap, bond, and attach proof."
        ),
        next_evidence=(
            "Replace surrogate links with finite rib stiffness and rib/spar-attach allowables, then "
            "cross-check against a braced structural FEM."
        ),
    )


def _write_csv(path: Path, diagnostic: RearSparRibBracingDiagnostic) -> Path:
    fields = list(asdict(diagnostic.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in diagnostic.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, diagnostic: RearSparRibBracingDiagnostic) -> Path:
    path.write_text(
        json.dumps(asdict(diagnostic), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, diagnostic: RearSparRibBracingDiagnostic) -> Path:
    lines = [
        "# Rear Spar And Rib Bracing Diagnostic",
        "",
        f"Candidate: `{diagnostic.candidate_id}`",
        f"Overall status: `{diagnostic.overall_status}`",
        "",
        "This converts Phase22 sensitivity into engineering readout. It is not a full-wing FEM signoff.",
        "",
        "| item | status | variant | d tip % | d max vertical % | d angle deg | link force N | guardrail |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in diagnostic.rows:
        lines.append(
            f"| {row.title} | `{row.status}` | `{row.source_variant_id or 'n/a'}` | "
            f"{_fmt(row.tip_delta_pct)} | {_fmt(row.max_vertical_delta_pct)} | "
            f"{_fmt(row.angle_delta_deg)} | {_fmt(row.link_force_max_n)} | "
            f"{row.model_bias_guardrail} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- Rear spar and rib-link assumptions move the response enough that they must stay in the closure loop.",
            "- Dense finite rib is still a finite-rib surrogate, not physical rib hardware validation.",
            "- Prior dual-spar/ANSYS spot checks indicate internal model bias can underpredict deflection, so this diagnostic needs external FEM correlation before signoff.",
            "- Use this as a target for the next braced FEM, not as a release claim.",
            "",
            "## Reads",
            "",
        ]
    )
    for row in diagnostic.rows:
        lines.extend(
            [
                f"- **{row.title}**: {row.engineering_read}",
                f"  Next evidence: {row.next_evidence}",
            ]
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _attr_float(obj: Any | None, name: str) -> float | None:
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value is None:
        return None
    return float(value)


def _fmt(value: float) -> str:
    return f"{float(value):.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    model = build_current_candidate_model()
    audit = build_bracing_sensitivity_audit(CANDIDATE_ID, model)
    outputs = write_rear_spar_rib_bracing_diagnostic_package(args.output_dir, audit)
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
