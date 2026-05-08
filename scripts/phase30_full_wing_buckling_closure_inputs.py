#!/usr/bin/env python3
"""Check full-wing global buckling evidence inputs against claim requirements."""
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


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase30_full_wing_buckling_closure_inputs"
ACCEPTED_MODEL_SCOPES = (
    "full_wing_global_eigen",
    "braced_subassembly_eigen",
    "apdl_full_wing_eigen",
)
REQUIRED_COMPONENTS = (
    "main_spar",
    "rear_spar",
    "finite_ribs",
    "wire_attach_load_path",
    "root_boundary",
)
REQUIRED_VERIFICATION_FIELDS = (
    "boundary_condition_status",
    "mesh_convergence_status",
    "solver_status",
)
PASS_STATUS = "pass"


@dataclass(frozen=True)
class FullWingBucklingClosureRow:
    case_id: str
    model_scope: str
    status: str
    claim_load_factor: float | None
    first_global_buckling_load_factor: float | None
    load_factor_margin: float | None
    includes_main_spar: bool
    includes_rear_spar: bool
    includes_finite_ribs: bool
    includes_wire_attach_load_path: bool
    includes_root_boundary: bool
    missing_components: str
    boundary_condition_status: str
    mesh_convergence_status: str
    solver_status: str
    source: str
    engineering_note: str


@dataclass(frozen=True)
class FullWingBucklingClosureCheck:
    candidate_id: str
    overall_status: str
    accepted_model_scopes: tuple[str, ...]
    required_components: tuple[str, ...]
    rows: tuple[FullWingBucklingClosureRow, ...]


def build_full_wing_buckling_closure_check(
    candidate_id: str,
    *,
    closure_inputs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> FullWingBucklingClosureCheck:
    rows = (
        (_missing_input_row(),)
        if not closure_inputs
        else tuple(_build_row(raw) for raw in closure_inputs)
    )
    all_positive = rows and all(row.status == "margin_positive_input_check_only" for row in rows)
    return FullWingBucklingClosureCheck(
        candidate_id=str(candidate_id),
        overall_status=(
            "buckling_input_margins_pass_not_full_aircraft_signoff"
            if all_positive
            else "full_wing_global_buckling_not_closed"
        ),
        accepted_model_scopes=ACCEPTED_MODEL_SCOPES,
        required_components=REQUIRED_COMPONENTS,
        rows=rows,
    )


def write_full_wing_buckling_closure_input_package(
    out_dir: Path,
    candidate_id: str,
    *,
    closure_inputs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    check = build_full_wing_buckling_closure_check(
        candidate_id,
        closure_inputs=closure_inputs,
    )
    return [
        _write_template(out_dir / "full_wing_buckling_closure_inputs_template.csv"),
        _write_csv(out_dir / "full_wing_buckling_closure_check.csv", check),
        _write_json(out_dir / "full_wing_buckling_closure_check.json", check),
        _write_markdown(out_dir / "full_wing_buckling_closure_check.md", check),
    ]


def read_full_wing_buckling_inputs_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_current_full_wing_buckling_closure_check() -> FullWingBucklingClosureCheck:
    return build_full_wing_buckling_closure_check(CANDIDATE_ID, closure_inputs=[])


def _build_row(raw: dict[str, Any]) -> FullWingBucklingClosureRow:
    claim_load_factor = _dict_float(raw, "claim_load_factor")
    first_global_buckling_load_factor = _dict_float(raw, "first_global_buckling_load_factor")
    load_factor_margin = _margin(first_global_buckling_load_factor, claim_load_factor)
    component_flags = {
        component: _dict_bool(raw, f"includes_{component}")
        for component in REQUIRED_COMPONENTS
    }
    missing_components = ";".join(
        component for component in REQUIRED_COMPONENTS if not component_flags[component]
    )
    verification_statuses = {
        field: str(raw.get(field, ""))
        for field in REQUIRED_VERIFICATION_FIELDS
    }
    status = _status(
        model_scope=str(raw.get("model_scope", "")),
        claim_load_factor=claim_load_factor,
        first_global_buckling_load_factor=first_global_buckling_load_factor,
        missing_components=missing_components,
        verification_statuses=verification_statuses,
        load_factor_margin=load_factor_margin,
    )
    return FullWingBucklingClosureRow(
        case_id=str(raw.get("case_id", "")),
        model_scope=str(raw.get("model_scope", "")),
        status=status,
        claim_load_factor=claim_load_factor,
        first_global_buckling_load_factor=first_global_buckling_load_factor,
        load_factor_margin=load_factor_margin,
        includes_main_spar=component_flags["main_spar"],
        includes_rear_spar=component_flags["rear_spar"],
        includes_finite_ribs=component_flags["finite_ribs"],
        includes_wire_attach_load_path=component_flags["wire_attach_load_path"],
        includes_root_boundary=component_flags["root_boundary"],
        missing_components=missing_components,
        boundary_condition_status=verification_statuses["boundary_condition_status"],
        mesh_convergence_status=verification_statuses["mesh_convergence_status"],
        solver_status=verification_statuses["solver_status"],
        source=str(raw.get("source", "")),
        engineering_note=_engineering_note(status),
    )


def _missing_input_row() -> FullWingBucklingClosureRow:
    return FullWingBucklingClosureRow(
        case_id="full_wing_global_buckling_input_required",
        model_scope="",
        status="closure_input_missing",
        claim_load_factor=None,
        first_global_buckling_load_factor=None,
        load_factor_margin=None,
        includes_main_spar=False,
        includes_rear_spar=False,
        includes_finite_ribs=False,
        includes_wire_attach_load_path=False,
        includes_root_boundary=False,
        missing_components=";".join(REQUIRED_COMPONENTS),
        boundary_condition_status="",
        mesh_convergence_status="",
        solver_status="",
        source="",
        engineering_note=(
            "Supply full-wing or credible braced-subassembly global buckling eigen/FEM evidence "
            "before any 1.5G/1.75G full-wing pass claim."
        ),
    )


def _status(
    *,
    model_scope: str,
    claim_load_factor: float | None,
    first_global_buckling_load_factor: float | None,
    missing_components: str,
    verification_statuses: dict[str, str],
    load_factor_margin: float | None,
) -> str:
    if model_scope not in ACCEPTED_MODEL_SCOPES:
        return "invalid_buckling_model_scope"
    if claim_load_factor is None or first_global_buckling_load_factor is None:
        return "closure_input_incomplete"
    if missing_components:
        return "required_structural_components_missing"
    if any(status != PASS_STATUS for status in verification_statuses.values()):
        return "verification_check_missing"
    if load_factor_margin is not None and load_factor_margin < 0.0:
        return "margin_negative"
    return "margin_positive_input_check_only"


def _engineering_note(status: str) -> str:
    if status == "invalid_buckling_model_scope":
        return (
            "Use full-wing global eigen, APDL full-wing eigen, or a credible braced-subassembly "
            "eigen model; a local shell coupon is not global buckling evidence."
        )
    if status == "required_structural_components_missing":
        return (
            "Buckling evidence must include the bracing structure that makes the claim physical: "
            "main spar, rear spar, finite ribs, wire-attach load path, and root boundary."
        )
    if status == "verification_check_missing":
        return (
            "Boundary conditions, mesh convergence, and solver status must all be marked pass "
            "before treating the input as qualified evidence."
        )
    return (
        "Input margin check only; not a full aircraft signoff without qualified model review, "
        "mesh/solver evidence, and engineering approval."
    )


def _write_template(path: Path) -> Path:
    fields = [
        "case_id",
        "model_scope",
        "accepted_model_scopes",
        "claim_load_factor",
        "first_global_buckling_load_factor",
        "includes_main_spar",
        "includes_rear_spar",
        "includes_finite_ribs",
        "includes_wire_attach_load_path",
        "includes_root_boundary",
        "boundary_condition_status",
        "mesh_convergence_status",
        "solver_status",
        "source",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "candidate_1p75g_global_buckling_case",
                "model_scope": "full_wing_global_eigen",
                "accepted_model_scopes": ";".join(ACCEPTED_MODEL_SCOPES),
                "claim_load_factor": "1.75",
                "first_global_buckling_load_factor": "",
                "includes_main_spar": "true",
                "includes_rear_spar": "true",
                "includes_finite_ribs": "true",
                "includes_wire_attach_load_path": "true",
                "includes_root_boundary": "true",
                "boundary_condition_status": "pass",
                "mesh_convergence_status": "pass",
                "solver_status": "pass",
                "source": "",
                "notes": "Use full_wing_global_eigen, apdl_full_wing_eigen, or braced_subassembly_eigen.",
            }
        )
    return path


def _write_csv(path: Path, check: FullWingBucklingClosureCheck) -> Path:
    fields = list(asdict(check.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in check.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, check: FullWingBucklingClosureCheck) -> Path:
    path.write_text(json.dumps(asdict(check), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, check: FullWingBucklingClosureCheck) -> Path:
    lines = [
        "# Full Wing Buckling Closure Inputs",
        "",
        f"Candidate: `{check.candidate_id}`",
        f"Overall status: `{check.overall_status}`",
        "",
        "These are full-wing global buckling closure inputs, not a full aircraft signoff.",
        "",
        f"- accepted model scopes: `{'; '.join(check.accepted_model_scopes)}`",
        f"- required components: `{'; '.join(check.required_components)}`",
        "",
        "| case | model scope | status | claim n | first buckling n | margin n | missing components | source |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in check.rows:
        lines.append(
            f"| {row.case_id} | {row.model_scope or 'n/a'} | `{row.status}` | "
            f"{_fmt(row.claim_load_factor)} | {_fmt(row.first_global_buckling_load_factor)} | "
            f"{_fmt(row.load_factor_margin)} | {row.missing_components or 'none'} | "
            f"{row.source or 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Local wall checks and main-spar coupon buckling are not full-wing global buckling evidence.",
            "- Positive input margins do not close drawing-release or flight-submission signoff by themselves.",
            "- Boundary conditions, mesh convergence, solver status, and included bracing components must be reviewed as engineering evidence.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _dict_float(row: dict[str, Any], name: str) -> float | None:
    value = row.get(name)
    if value is None or value == "":
        return None
    return float(value)


def _dict_bool(row: dict[str, Any], name: str) -> bool:
    value = row.get(name)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "pass", "included"}


def _margin(available: float | None, required: float | None) -> float | None:
    if available is None or required is None:
        return None
    return float(available) - float(required)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--closure-inputs-csv", type=Path)
    args = parser.parse_args(argv)

    closure_inputs = (
        []
        if args.closure_inputs_csv is None
        else read_full_wing_buckling_inputs_csv(args.closure_inputs_csv)
    )
    outputs = write_full_wing_buckling_closure_input_package(
        args.output_dir,
        CANDIDATE_ID,
        closure_inputs=closure_inputs,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
