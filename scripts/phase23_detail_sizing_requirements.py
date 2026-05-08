#!/usr/bin/env python3
"""Turn local load-path service loads into hardware/detail sizing requirements."""
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
from scripts.phase19_local_load_path_ledger import (  # noqa: E402
    build_local_load_path_ledger,
    load_current_spar_rows,
    load_current_wire_rigging,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase23_detail_sizing_requirements"
DEFAULT_DETAIL_SAFETY_FACTOR = 2.0
DEFAULT_TERMINATION_EFFICIENCY = 0.60


@dataclass(frozen=True)
class DetailSizingRequirement:
    key: str
    title: str
    status: str
    service_load_n: float | None
    service_moment_n_m: float | None
    required_allowable_load_n: float | None
    required_allowable_moment_n_m: float | None
    body_allowable_n: float | None
    body_allowable_margin_n: float | None
    body_allowable_meets_required_load: bool | None
    required_minimum_breaking_load_n: float | None
    evidence: str
    requirement_note: str
    remaining_blocker: str


@dataclass(frozen=True)
class DetailSizingRequirements:
    candidate_id: str
    overall_status: str
    detail_safety_factor: float
    termination_efficiency: float
    rows: tuple[DetailSizingRequirement, ...]


def build_detail_sizing_requirements(
    local_ledger: Any,
    *,
    detail_safety_factor: float = DEFAULT_DETAIL_SAFETY_FACTOR,
    termination_efficiency: float = DEFAULT_TERMINATION_EFFICIENCY,
) -> DetailSizingRequirements:
    if detail_safety_factor <= 0.0:
        raise ValueError("detail_safety_factor must be positive.")
    if termination_efficiency <= 0.0 or termination_efficiency > 1.0:
        raise ValueError("termination_efficiency must be within (0, 1].")

    by_key = {str(entry.key): entry for entry in local_ledger.entries}
    rows = (
        _wire_attach_requirement(
            by_key["wire_attach_local_load_path"],
            detail_safety_factor=detail_safety_factor,
        ),
        _root_joint_requirement(
            by_key["root_joint"],
            detail_safety_factor=detail_safety_factor,
        ),
        _wire_termination_requirement(
            by_key["wire_termination"],
            detail_safety_factor=detail_safety_factor,
            termination_efficiency=termination_efficiency,
        ),
    )
    return DetailSizingRequirements(
        candidate_id=str(local_ledger.candidate_id),
        overall_status="requirements_only_not_margin_signoff",
        detail_safety_factor=float(detail_safety_factor),
        termination_efficiency=float(termination_efficiency),
        rows=rows,
    )


def write_detail_sizing_requirements_package(
    out_dir: Path,
    local_ledger: Any,
    *,
    detail_safety_factor: float = DEFAULT_DETAIL_SAFETY_FACTOR,
    termination_efficiency: float = DEFAULT_TERMINATION_EFFICIENCY,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    requirements = build_detail_sizing_requirements(
        local_ledger,
        detail_safety_factor=detail_safety_factor,
        termination_efficiency=termination_efficiency,
    )
    outputs = [
        _write_csv(out_dir / "detail_sizing_requirements.csv", requirements),
        _write_json(out_dir / "detail_sizing_requirements.json", requirements),
        _write_markdown(out_dir / "detail_sizing_requirements.md", requirements),
    ]
    return outputs


def build_current_detail_sizing_requirements() -> DetailSizingRequirements:
    reference = load_current_candidate_reference()
    ledger = build_local_load_path_ledger(
        reference,
        wire_rigging=load_current_wire_rigging(),
        spar_rows=load_current_spar_rows(),
    )
    return build_detail_sizing_requirements(ledger)


def _wire_attach_requirement(
    entry: Any,
    *,
    detail_safety_factor: float,
) -> DetailSizingRequirement:
    load = _float_or_none(entry.primary_load_n)
    design_load = _scale(load, detail_safety_factor)
    return DetailSizingRequirement(
        key=str(entry.key),
        title=str(entry.title),
        status="requirement_defined_hardware_margin_missing",
        service_load_n=load,
        service_moment_n_m=None,
        required_allowable_load_n=design_load,
        required_allowable_moment_n_m=None,
        body_allowable_n=None,
        body_allowable_margin_n=None,
        body_allowable_meets_required_load=None,
        required_minimum_breaking_load_n=None,
        evidence=str(entry.evidence),
        requirement_note=(
            f"Wire attach ring/lug/insert/bond local load path should carry at least {_fmt(design_load)} N "
            "resultant design load before component-specific reductions."
        ),
        remaining_blocker="Select/detail the attach hardware and verify bearing, bond shear, insert pullout, and tube-wall crushing margins.",
    )


def _root_joint_requirement(
    entry: Any,
    *,
    detail_safety_factor: float,
) -> DetailSizingRequirement:
    load = _float_or_none(entry.primary_load_n)
    moment = _float_or_none(entry.primary_moment_n_m)
    return DetailSizingRequirement(
        key=str(entry.key),
        title=str(entry.title),
        status="requirement_defined_hardware_margin_missing",
        service_load_n=load,
        service_moment_n_m=moment,
        required_allowable_load_n=_scale(load, detail_safety_factor),
        required_allowable_moment_n_m=_scale(moment, detail_safety_factor),
        body_allowable_n=None,
        body_allowable_margin_n=None,
        body_allowable_meets_required_load=None,
        required_minimum_breaking_load_n=None,
        evidence=str(entry.evidence),
        requirement_note=(
            f"Root fitting/clamp/bonded insert should carry at least {_fmt(_scale(moment, detail_safety_factor))} N*m "
            "design bending moment plus the listed resultant root force."
        ),
        remaining_blocker="Create root fitting/clamp/bonded-insert local margins or FEM with bearing and bond allowables.",
    )


def _wire_termination_requirement(
    entry: Any,
    *,
    detail_safety_factor: float,
    termination_efficiency: float,
) -> DetailSizingRequirement:
    load = _float_or_none(entry.primary_load_n)
    body_allowable = _body_allowable_from_utilization(
        load,
        _float_or_none(entry.utilization),
    )
    design_load = _scale(load, detail_safety_factor)
    body_margin = _margin(body_allowable, design_load)
    required_mbl = None if design_load is None else design_load / termination_efficiency
    return DetailSizingRequirement(
        key=str(entry.key),
        title=str(entry.title),
        status="requirement_defined_hardware_margin_missing",
        service_load_n=load,
        service_moment_n_m=None,
        required_allowable_load_n=design_load,
        required_allowable_moment_n_m=None,
        body_allowable_n=body_allowable,
        body_allowable_margin_n=body_margin,
        body_allowable_meets_required_load=(
            None if body_margin is None else bool(body_margin >= 0.0)
        ),
        required_minimum_breaking_load_n=required_mbl,
        evidence=str(entry.evidence),
        requirement_note=(
            f"wire termination required MBL is {_fmt(required_mbl)} N for "
            f"{termination_efficiency:.2f} termination efficiency and {detail_safety_factor:.2f} detail SF."
        ),
        remaining_blocker="Pick real termination hardware/process and verify efficiency, bend radius, creep, abrasion, pin, anchor, and clamp allowables.",
    )


def _body_allowable_from_utilization(load: float | None, utilization: float | None) -> float | None:
    if load is None or utilization is None or utilization <= 0.0:
        return None
    return float(load) / float(utilization)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _scale(value: float | None, factor: float) -> float | None:
    return None if value is None else float(value) * float(factor)


def _margin(allowable: float | None, required: float | None) -> float | None:
    if allowable is None or required is None:
        return None
    return float(allowable) - float(required)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def _write_csv(path: Path, requirements: DetailSizingRequirements) -> Path:
    fields = list(asdict(requirements.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in requirements.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, requirements: DetailSizingRequirements) -> Path:
    path.write_text(json.dumps(asdict(requirements), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, requirements: DetailSizingRequirements) -> Path:
    lines = [
        "# Detail Sizing Requirements",
        "",
        f"Candidate: `{requirements.candidate_id}`",
        f"Overall status: `{requirements.overall_status}`",
        "",
        "These are requirements only, not a hardware margin signoff.",
        "",
        "## Assumptions",
        "",
        f"- detail safety factor: `{requirements.detail_safety_factor:.2f}`",
        f"- termination efficiency for MBL back-calc: `{requirements.termination_efficiency:.2f}`",
        "",
        "## Requirements",
        "",
        "| item | status | service load N | service moment N*m | required load N | body margin N | required moment N*m | required MBL N | blocker |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in requirements.rows:
        lines.append(
            f"| {row.title} | `{row.status}` | {_fmt(row.service_load_n)} | "
            f"{_fmt(row.service_moment_n_m)} | {_fmt(row.required_allowable_load_n)} | "
            f"{_fmt(row.body_allowable_margin_n)} | "
            f"{_fmt(row.required_allowable_moment_n_m)} | {_fmt(row.required_minimum_breaking_load_n)} | "
            f"{row.remaining_blocker} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
        ]
    )
    for row in requirements.rows:
        lines.append(f"- **{row.title}**: {row.requirement_note}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--detail-safety-factor", type=float, default=DEFAULT_DETAIL_SAFETY_FACTOR)
    parser.add_argument("--termination-efficiency", type=float, default=DEFAULT_TERMINATION_EFFICIENCY)
    args = parser.parse_args(argv)

    requirements = build_current_detail_sizing_requirements()
    if (
        args.detail_safety_factor != DEFAULT_DETAIL_SAFETY_FACTOR
        or args.termination_efficiency != DEFAULT_TERMINATION_EFFICIENCY
    ):
        reference = load_current_candidate_reference()
        ledger = build_local_load_path_ledger(
            reference,
            wire_rigging=load_current_wire_rigging(),
            spar_rows=load_current_spar_rows(),
        )
        requirements = build_detail_sizing_requirements(
            ledger,
            detail_safety_factor=args.detail_safety_factor,
            termination_efficiency=args.termination_efficiency,
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        _write_csv(args.output_dir / "detail_sizing_requirements.csv", requirements),
        _write_json(args.output_dir / "detail_sizing_requirements.json", requirements),
        _write_markdown(args.output_dir / "detail_sizing_requirements.md", requirements),
    ]
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
