#!/usr/bin/env python3
"""Back-calculate wire termination MBL requirements across efficiency assumptions."""
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
    DEFAULT_TERMINATION_EFFICIENCY,
    build_current_detail_sizing_requirements,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase36_wire_termination_efficiency_sensitivity"
DEFAULT_TERMINATION_EFFICIENCIES = (0.40, 0.50, 0.60, 0.70, 0.80, 1.00)


@dataclass(frozen=True)
class WireTerminationEfficiencyRow:
    termination_efficiency: float
    status: str
    service_load_n: float
    required_allowable_load_n: float
    required_minimum_breaking_load_n: float
    body_allowable_n: float | None
    body_allowable_margin_n: float | None
    engineering_note: str


@dataclass(frozen=True)
class WireTerminationEfficiencySensitivity:
    candidate_id: str
    overall_status: str
    default_termination_efficiency: float
    service_load_n: float
    required_allowable_load_n: float
    body_allowable_n: float | None
    body_allowable_margin_n: float | None
    rows: tuple[WireTerminationEfficiencyRow, ...]


def build_wire_termination_efficiency_sensitivity(
    detail_requirements: Any,
    *,
    termination_efficiencies: tuple[float, ...] = DEFAULT_TERMINATION_EFFICIENCIES,
) -> WireTerminationEfficiencySensitivity:
    if any(efficiency <= 0.0 or efficiency > 1.0 for efficiency in termination_efficiencies):
        raise ValueError("termination_efficiencies values must be within (0, 1].")
    requirement = _wire_termination_requirement(detail_requirements)
    service_load = _attr_float(requirement, "service_load_n")
    required_load = _attr_float(requirement, "required_allowable_load_n")
    body_allowable = _attr_float(requirement, "body_allowable_n")
    body_margin = _attr_float(requirement, "body_allowable_margin_n")
    rows = tuple(
        WireTerminationEfficiencyRow(
            termination_efficiency=float(efficiency),
            status="termination_mbl_requirement_only",
            service_load_n=service_load,
            required_allowable_load_n=required_load,
            required_minimum_breaking_load_n=required_load / float(efficiency),
            body_allowable_n=body_allowable,
            body_allowable_margin_n=body_margin,
            engineering_note=(
                "Efficiency sensitivity only; not termination signoff and not a substitute "
                "for selected end fitting, swage/knot/splice, bend radius, creep, abrasion, pin, or anchor allowables."
            ),
        )
        for efficiency in termination_efficiencies
    )
    return WireTerminationEfficiencySensitivity(
        candidate_id=str(detail_requirements.candidate_id),
        overall_status="termination_efficiency_sensitivity_defined_not_signoff",
        default_termination_efficiency=DEFAULT_TERMINATION_EFFICIENCY,
        service_load_n=service_load,
        required_allowable_load_n=required_load,
        body_allowable_n=body_allowable,
        body_allowable_margin_n=body_margin,
        rows=rows,
    )


def write_wire_termination_efficiency_sensitivity_package(
    out_dir: Path,
    detail_requirements: Any,
    *,
    termination_efficiencies: tuple[float, ...] = DEFAULT_TERMINATION_EFFICIENCIES,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sensitivity = build_wire_termination_efficiency_sensitivity(
        detail_requirements,
        termination_efficiencies=termination_efficiencies,
    )
    outputs = [
        _write_csv(out_dir / "wire_termination_efficiency_sensitivity.csv", sensitivity),
        _write_json(out_dir / "wire_termination_efficiency_sensitivity.json", sensitivity),
        _write_markdown(out_dir / "wire_termination_efficiency_sensitivity.md", sensitivity),
    ]
    return outputs


def build_current_wire_termination_efficiency_sensitivity() -> (
    WireTerminationEfficiencySensitivity
):
    return build_wire_termination_efficiency_sensitivity(
        build_current_detail_sizing_requirements()
    )


def _wire_termination_requirement(detail_requirements: Any) -> Any:
    for row in getattr(detail_requirements, "rows", ()):
        if str(row.key) == "wire_termination":
            return row
    raise ValueError("wire_termination detail requirement row is required.")


def _attr_float(obj: Any, name: str) -> float:
    value = getattr(obj, name, None)
    if value is None or value == "":
        raise ValueError(f"{name} is required for wire termination sensitivity.")
    return float(value)


def _write_csv(path: Path, sensitivity: WireTerminationEfficiencySensitivity) -> Path:
    fields = list(asdict(sensitivity.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in sensitivity.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, sensitivity: WireTerminationEfficiencySensitivity) -> Path:
    path.write_text(
        json.dumps(asdict(sensitivity), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, sensitivity: WireTerminationEfficiencySensitivity) -> Path:
    lines = [
        "# Wire Termination Efficiency Sensitivity",
        "",
        f"Candidate: `{sensitivity.candidate_id}`",
        f"Overall status: `{sensitivity.overall_status}`",
        "",
        "This is a termination MBL requirement sensitivity, not termination signoff.",
        "",
        f"- service wire load: `{sensitivity.service_load_n:.3f} N`",
        f"- required allowable load: `{sensitivity.required_allowable_load_n:.3f} N`",
        f"- cable-body allowable: `{_fmt(sensitivity.body_allowable_n)} N`",
        f"- cable-body margin against required load: `{_fmt(sensitivity.body_allowable_margin_n)} N`",
        "",
        "| efficiency | status | required MBL N | body allowable N | body margin N |",
        "|---:|---|---:|---:|---:|",
    ]
    for row in sensitivity.rows:
        lines.append(
            f"| {row.termination_efficiency:.2f} | `{row.status}` | "
            f"{row.required_minimum_breaking_load_n:.3f} | {_fmt(row.body_allowable_n)} | "
            f"{_fmt(row.body_allowable_margin_n)} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Do not use cable-body tensile allowable as termination allowable.",
            "- Select real termination hardware/process and verify efficiency, bend, creep, abrasion, pin, and anchor margins.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    outputs = write_wire_termination_efficiency_sensitivity_package(
        args.output_dir,
        build_current_detail_sizing_requirements(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
