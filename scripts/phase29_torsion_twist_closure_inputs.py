#!/usr/bin/env python3
"""Check user-supplied torsion/twist closure evidence against signoff requirements."""
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
from scripts.phase20_rear_spar_torsion_audit import (  # noqa: E402
    build_rear_spar_torsion_audit,
    load_current_equivalent_twist_max_deg,
    load_current_material_stiffness,
    load_current_rows,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase29_torsion_twist_closure_inputs"
ACCEPTED_CLOSURE_METHODS = ("tip_ring_fem", "aeroelastic_loop", "apdl_tip_ring_fem")


@dataclass(frozen=True)
class TorsionTwistClosureRow:
    case_id: str
    closure_method: str
    status: str
    measured_twist_deg: float | None
    twist_limit_deg: float | None
    twist_margin_deg: float | None
    torque_balance_error_pct: float | None
    max_allowed_torque_balance_error_pct: float | None
    torque_balance_margin_pct: float | None
    internal_equivalent_twist_deg: float | None
    max_spar_pair_line_angle_delta_deg: float | None
    source: str
    engineering_note: str


@dataclass(frozen=True)
class TorsionTwistClosureCheck:
    candidate_id: str
    overall_status: str
    accepted_closure_methods: tuple[str, ...]
    rows: tuple[TorsionTwistClosureRow, ...]


def build_torsion_twist_closure_check(
    torsion_audit: Any,
    *,
    closure_inputs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> TorsionTwistClosureCheck:
    rows = (
        (_missing_input_row(torsion_audit),)
        if not closure_inputs
        else tuple(_build_row(torsion_audit, raw) for raw in closure_inputs)
    )
    all_positive = rows and all(row.status == "margin_positive_input_check_only" for row in rows)
    return TorsionTwistClosureCheck(
        candidate_id=str(torsion_audit.candidate_id),
        overall_status=(
            "torsion_twist_input_margins_pass_not_aeroelastic_signoff"
            if all_positive
            else "torsion_twist_closure_not_closed"
        ),
        accepted_closure_methods=ACCEPTED_CLOSURE_METHODS,
        rows=rows,
    )


def write_torsion_twist_closure_input_package(
    out_dir: Path,
    torsion_audit: Any,
    *,
    closure_inputs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    check = build_torsion_twist_closure_check(torsion_audit, closure_inputs=closure_inputs)
    outputs = [
        _write_template(out_dir / "torsion_twist_closure_inputs_template.csv", torsion_audit),
        _write_csv(out_dir / "torsion_twist_closure_check.csv", check),
        _write_json(out_dir / "torsion_twist_closure_check.json", check),
        _write_markdown(out_dir / "torsion_twist_closure_check.md", check),
    ]
    return outputs


def read_torsion_twist_inputs_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_current_torsion_audit() -> Any:
    jig_rows, loaded_rows = load_current_rows()
    main_e, main_g, rear_e, rear_g = load_current_material_stiffness()
    return build_rear_spar_torsion_audit(
        CANDIDATE_ID,
        jig_rows=jig_rows,
        loaded_rows=loaded_rows,
        young_pa=main_e,
        shear_pa=main_g,
        rear_young_pa=rear_e,
        rear_shear_pa=rear_g,
        equivalent_twist_max_deg=load_current_equivalent_twist_max_deg(),
    )


def build_current_torsion_twist_closure_check() -> TorsionTwistClosureCheck:
    return build_torsion_twist_closure_check(build_current_torsion_audit(), closure_inputs=[])


def _build_row(torsion_audit: Any, raw: dict[str, Any]) -> TorsionTwistClosureRow:
    method = str(raw.get("closure_method", ""))
    measured_twist = _dict_float(raw, "measured_twist_deg")
    twist_limit = _dict_float(raw, "twist_limit_deg")
    torque_error = _dict_float(raw, "torque_balance_error_pct")
    max_torque_error = _dict_float(raw, "max_allowed_torque_balance_error_pct")
    twist_margin = _twist_margin(measured_twist, twist_limit)
    torque_margin = _margin(max_torque_error, torque_error)
    status = _status(
        method=method,
        measured_twist=measured_twist,
        twist_limit=twist_limit,
        torque_error=torque_error,
        max_torque_error=max_torque_error,
        margins=(twist_margin, torque_margin),
    )
    return TorsionTwistClosureRow(
        case_id=str(raw.get("case_id", "")),
        closure_method=method,
        status=status,
        measured_twist_deg=measured_twist,
        twist_limit_deg=twist_limit,
        twist_margin_deg=twist_margin,
        torque_balance_error_pct=torque_error,
        max_allowed_torque_balance_error_pct=max_torque_error,
        torque_balance_margin_pct=torque_margin,
        internal_equivalent_twist_deg=_attr_float(torsion_audit, "equivalent_twist_max_deg"),
        max_spar_pair_line_angle_delta_deg=_attr_float(
            torsion_audit,
            "max_spar_pair_line_angle_delta_deg",
        ),
        source=str(raw.get("source", "")),
        engineering_note=_engineering_note(status),
    )


def _missing_input_row(torsion_audit: Any) -> TorsionTwistClosureRow:
    return TorsionTwistClosureRow(
        case_id="torsion_twist_closure_input_required",
        closure_method="",
        status="closure_input_missing",
        measured_twist_deg=None,
        twist_limit_deg=None,
        twist_margin_deg=None,
        torque_balance_error_pct=None,
        max_allowed_torque_balance_error_pct=None,
        torque_balance_margin_pct=None,
        internal_equivalent_twist_deg=_attr_float(torsion_audit, "equivalent_twist_max_deg"),
        max_spar_pair_line_angle_delta_deg=_attr_float(
            torsion_audit,
            "max_spar_pair_line_angle_delta_deg",
        ),
        source="",
        engineering_note=(
            "Supply tip-ring FEM, APDL tip-ring FEM, or aeroelastic-loop twist and torque-balance evidence."
        ),
    )


def _status(
    *,
    method: str,
    measured_twist: float | None,
    twist_limit: float | None,
    torque_error: float | None,
    max_torque_error: float | None,
    margins: tuple[float | None, ...],
) -> str:
    if method not in ACCEPTED_CLOSURE_METHODS:
        return "invalid_twist_observable"
    if (
        measured_twist is None
        or twist_limit is None
        or torque_error is None
        or max_torque_error is None
    ):
        return "closure_input_incomplete"
    if any(value is not None and value < 0.0 for value in margins):
        return "margin_negative"
    return "margin_positive_input_check_only"


def _engineering_note(status: str) -> str:
    if status == "invalid_twist_observable":
        return (
            "Use tip-ring FEM, APDL tip-ring FEM, or aeroelastic-loop evidence; a single-node "
            "displacement or force-couple surrogate is not accepted."
        )
    return (
        "Input margin check only; not aeroelastic signoff unless the source is a qualified "
        "tip-ring FEM/APDL or aeroelastic-loop result."
    )


def _write_template(path: Path, torsion_audit: Any) -> Path:
    fields = [
        "case_id",
        "closure_method",
        "accepted_methods",
        "internal_equivalent_twist_deg",
        "max_spar_pair_line_angle_delta_deg",
        "measured_twist_deg",
        "twist_limit_deg",
        "torque_balance_error_pct",
        "max_allowed_torque_balance_error_pct",
        "source",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "candidate_tip_ring_or_aeroelastic_case",
                "closure_method": "tip_ring_fem",
                "accepted_methods": ";".join(ACCEPTED_CLOSURE_METHODS),
                "internal_equivalent_twist_deg": _fmt(
                    _attr_float(torsion_audit, "equivalent_twist_max_deg")
                ),
                "max_spar_pair_line_angle_delta_deg": _fmt(
                    _attr_float(torsion_audit, "max_spar_pair_line_angle_delta_deg")
                ),
                "measured_twist_deg": "",
                "twist_limit_deg": "",
                "torque_balance_error_pct": "",
                "max_allowed_torque_balance_error_pct": "",
                "source": "",
                "notes": "Use tip_ring_fem, apdl_tip_ring_fem, or aeroelastic_loop.",
            }
        )
    return path


def _write_csv(path: Path, check: TorsionTwistClosureCheck) -> Path:
    fields = list(asdict(check.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in check.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, check: TorsionTwistClosureCheck) -> Path:
    path.write_text(json.dumps(asdict(check), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, check: TorsionTwistClosureCheck) -> Path:
    lines = [
        "# Torsion Twist Closure Inputs",
        "",
        f"Candidate: `{check.candidate_id}`",
        f"Overall status: `{check.overall_status}`",
        "",
        "These are torsion/twist closure inputs, not aeroelastic signoff.",
        "",
        f"- accepted methods: `{'; '.join(check.accepted_closure_methods)}`",
        "",
        "| case | method | status | measured twist deg | twist margin deg | torque error % | torque margin % | source |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in check.rows:
        lines.append(
            f"| {row.case_id} | {row.closure_method or 'n/a'} | `{row.status}` | "
            f"{_fmt(row.measured_twist_deg)} | {_fmt(row.twist_margin_deg)} | "
            f"{_fmt(row.torque_balance_error_pct)} | {_fmt(row.torque_balance_margin_pct)} | "
            f"{row.source or 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Spar-pair line angle and internal equivalent twist remain diagnostics until tied to an accepted closure method.",
            "- Single-node displacement, force-couple surrogate, or warning-grade torque ownership evidence is not accepted as final twist closure.",
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


def _dict_float(row: dict[str, Any], name: str) -> float | None:
    value = row.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _twist_margin(measured: float | None, limit: float | None) -> float | None:
    if measured is None or limit is None:
        return None
    return float(limit) - abs(float(measured))


def _margin(allowable: float | None, demand: float | None) -> float | None:
    if allowable is None or demand is None:
        return None
    return float(allowable) - abs(float(demand))


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--closure-inputs-csv", type=Path)
    args = parser.parse_args(argv)

    torsion_audit = build_current_torsion_audit()
    closure_inputs = (
        []
        if args.closure_inputs_csv is None
        else read_torsion_twist_inputs_csv(args.closure_inputs_csv)
    )
    outputs = write_torsion_twist_closure_input_package(
        args.output_dir,
        torsion_audit,
        closure_inputs=closure_inputs,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
