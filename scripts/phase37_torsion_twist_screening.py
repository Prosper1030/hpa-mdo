#!/usr/bin/env python3
"""Collect torsion/twist screening signals without promoting them to signoff."""
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
from scripts.phase29_torsion_twist_closure_inputs import (  # noqa: E402
    build_current_torsion_audit,
    build_current_torsion_twist_closure_check,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase37_torsion_twist_screening"


@dataclass(frozen=True)
class TorsionTwistScreeningRow:
    signal_key: str
    title: str
    source: str
    status: str
    value: float | None
    unit: str
    engineering_read: str
    signoff_boundary: str
    next_evidence: str


@dataclass(frozen=True)
class TorsionTwistScreening:
    candidate_id: str
    overall_status: str
    internal_equivalent_twist_deg: float | None
    max_spar_pair_line_angle_delta_deg: float | None
    dense_finite_rib_angle_delta_deg: float | None
    rear_soft_angle_delta_deg: float | None
    closure_input_status: str
    accepted_closure_methods: tuple[str, ...]
    rows: tuple[TorsionTwistScreeningRow, ...]


def build_torsion_twist_screening(
    torsion_audit: Any,
    *,
    bracing_audit: Any | None,
    closure_check: Any | None,
) -> TorsionTwistScreening:
    dense_finite = _variant(bracing_audit, "dense_finite_rib_surrogate")
    rear_soft = _variant(bracing_audit, "rear_stiffness_5pct")
    accepted_methods = tuple(
        str(method)
        for method in getattr(
            closure_check,
            "accepted_closure_methods",
            ("tip_ring_fem", "aeroelastic_loop", "apdl_tip_ring_fem"),
        )
    )
    closure_status = _closure_input_status(closure_check)
    internal_twist = _attr_float(torsion_audit, "equivalent_twist_max_deg")
    spar_pair_angle = _attr_float(torsion_audit, "max_spar_pair_line_angle_delta_deg")
    dense_finite_angle_delta = _attr_float(dense_finite, "angle_delta_vs_baseline_deg")
    rear_soft_angle_delta = _attr_float(rear_soft, "angle_delta_vs_baseline_deg")

    rows = (
        TorsionTwistScreeningRow(
            signal_key="internal_equivalent_twist",
            title="Internal equivalent-beam twist",
            source="Phase20 rear_spar_torsion_audit",
            status="internal_beam_twist_diagnostic_not_signoff",
            value=internal_twist,
            unit="deg",
            engineering_read=(
                "The equivalent-beam twist number is small, but it is from the internal fixed-load "
                "model and does not prove aeroelastic load redistribution."
            ),
            signoff_boundary=(
                "Screening only; not aeroelastic signoff without an accepted tip-ring FEM/APDL or "
                "aeroelastic-loop observable."
            ),
            next_evidence="Tip-ring FEM/APDL twist or coupled aeroelastic twist loop with torque balance.",
        ),
        TorsionTwistScreeningRow(
            signal_key="spar_pair_line_angle",
            title="Jig-to-loaded spar-pair line angle",
            source="Phase20 rear_spar_torsion_audit",
            status="geometry_angle_not_aero_twist",
            value=spar_pair_angle,
            unit="deg",
            engineering_read=(
                "The main/rear spar-pair line angle moves substantially in the current geometry "
                "diagnostic, which flags torsional/bracing sensitivity."
            ),
            signoff_boundary=(
                "The spar-pair line angle is not aero twist and is not aeroelastic signoff."
            ),
            next_evidence="Map tip-section rotation from a qualified ring or aeroelastic result.",
        ),
        TorsionTwistScreeningRow(
            signal_key="dense_finite_rib_angle_delta",
            title="Dense finite-rib surrogate angle delta",
            source="Phase22 bracing_sensitivity",
            status="rib_link_angle_sensitivity_report_only",
            value=dense_finite_angle_delta,
            unit="deg",
            engineering_read=(
                "The dense finite-rib surrogate changes the spar-pair angle response, so rib/link "
                "assumptions affect torsion-like behavior."
            ),
            signoff_boundary=(
                "Report-only sensitivity; finite-rib surrogate response is not physical rib hardware "
                "or aeroelastic signoff."
            ),
            next_evidence="Finite-rib stiffness and attach margins tied to a braced FEM.",
        ),
        TorsionTwistScreeningRow(
            signal_key="rear_soft_angle_delta",
            title="Rear-soft spar-pair angle delta",
            source="Phase22 bracing_sensitivity",
            status="rear_spar_angle_sensitivity_report_only",
            value=rear_soft_angle_delta,
            unit="deg",
            engineering_read=(
                "Softening rear-spar stiffness strongly changes the angle response, so rear-spar "
                "participation remains inside the torsion/twist closure loop."
            ),
            signoff_boundary=(
                "Report-only sensitivity; not a rear-spar global bracing or torsional stiffness pass."
            ),
            next_evidence="Rear-spar-on/off braced-subassembly FEM with external correlation.",
        ),
        TorsionTwistScreeningRow(
            signal_key="closure_input",
            title="Accepted torsion/twist closure input",
            source="Phase29 torsion_twist_closure_inputs",
            status=closure_status,
            value=None,
            unit="",
            engineering_read=(
                "The accepted closure input row controls whether these screening signals can be "
                "converted into an input-margin check."
            ),
            signoff_boundary="Missing or input-only closure evidence remains not aeroelastic signoff.",
            next_evidence=(
                "Supply tip-ring FEM, APDL tip-ring FEM, or aeroelastic-loop twist and torque-balance "
                "evidence."
            ),
        ),
    )
    return TorsionTwistScreening(
        candidate_id=str(torsion_audit.candidate_id),
        overall_status="torsion_twist_screening_not_aeroelastic_signoff",
        internal_equivalent_twist_deg=internal_twist,
        max_spar_pair_line_angle_delta_deg=spar_pair_angle,
        dense_finite_rib_angle_delta_deg=dense_finite_angle_delta,
        rear_soft_angle_delta_deg=rear_soft_angle_delta,
        closure_input_status=closure_status,
        accepted_closure_methods=accepted_methods,
        rows=rows,
    )


def write_torsion_twist_screening_package(
    out_dir: Path,
    torsion_audit: Any,
    *,
    bracing_audit: Any | None,
    closure_check: Any | None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    screening = build_torsion_twist_screening(
        torsion_audit,
        bracing_audit=bracing_audit,
        closure_check=closure_check,
    )
    return [
        _write_csv(out_dir / "torsion_twist_screening.csv", screening),
        _write_json(out_dir / "torsion_twist_screening.json", screening),
        _write_markdown(out_dir / "torsion_twist_screening.md", screening),
    ]


def build_current_torsion_twist_screening() -> TorsionTwistScreening:
    model = build_current_candidate_model()
    return build_torsion_twist_screening(
        build_current_torsion_audit(),
        bracing_audit=build_bracing_sensitivity_audit(CANDIDATE_ID, model),
        closure_check=build_current_torsion_twist_closure_check(),
    )


def _variant(bracing_audit: Any | None, variant_id: str) -> Any | None:
    if bracing_audit is None:
        return None
    rows = {str(row.variant_id): row for row in getattr(bracing_audit, "rows", ())}
    return rows.get(variant_id)


def _closure_input_status(closure_check: Any | None) -> str:
    if closure_check is None:
        return "closure_input_unavailable"
    rows = tuple(getattr(closure_check, "rows", ()))
    if not rows:
        return "closure_input_missing"
    for row in rows:
        status = str(getattr(row, "status", "unknown"))
        if status != "margin_positive_input_check_only":
            return status
    overall_status = str(getattr(closure_check, "overall_status", "")).strip()
    return overall_status or str(getattr(rows[0], "status", "unknown"))


def _attr_float(obj: Any | None, name: str) -> float | None:
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value is None:
        return None
    return float(value)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.4f}"


def _write_csv(path: Path, screening: TorsionTwistScreening) -> Path:
    fields = list(asdict(screening.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in screening.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, screening: TorsionTwistScreening) -> Path:
    path.write_text(
        json.dumps(asdict(screening), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, screening: TorsionTwistScreening) -> Path:
    lines = [
        "# Torsion Twist Screening",
        "",
        f"Candidate: `{screening.candidate_id}`",
        f"Overall status: `{screening.overall_status}`",
        "",
        "This collects torsion/twist screening signals. It is not aeroelastic signoff.",
        "",
        "## Summary",
        "",
        f"- internal equivalent twist: `{_fmt(screening.internal_equivalent_twist_deg)} deg`",
        "- max spar-pair line-angle delta: "
        f"`{_fmt(screening.max_spar_pair_line_angle_delta_deg)} deg`",
        "- dense finite-rib angle delta: "
        f"`{_fmt(screening.dense_finite_rib_angle_delta_deg)} deg`",
        f"- rear-soft angle delta: `{_fmt(screening.rear_soft_angle_delta_deg)} deg`",
        f"- closure input status: `{screening.closure_input_status}`",
        f"- accepted methods: `{'; '.join(screening.accepted_closure_methods)}`",
        "",
        "## Screening Rows",
        "",
        "| signal | status | value | source | boundary | next evidence |",
        "|---|---|---:|---|---|---|",
    ]
    for row in screening.rows:
        value = _fmt(row.value)
        if value and row.unit:
            value = f"{value} {row.unit}"
        lines.append(
            f"| {row.title} | `{row.status}` | {value or 'n/a'} | "
            f"{row.source} | {row.signoff_boundary} | {row.next_evidence} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- The spar-pair line angle is not aero twist; it is a geometry/bracing sensitivity signal.",
            "- The internal equivalent twist is fixed-load model evidence, not coupled aeroelastic proof.",
            "- Dense finite-rib and rear-soft variants show sensitivity, not physical rib or rear-spar signoff.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    model = build_current_candidate_model()
    outputs = write_torsion_twist_screening_package(
        args.output_dir,
        build_current_torsion_audit(),
        bracing_audit=build_bracing_sensitivity_audit(CANDIDATE_ID, model),
        closure_check=build_current_torsion_twist_closure_check(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
