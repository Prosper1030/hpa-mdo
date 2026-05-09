#!/usr/bin/env python3
"""Screen selected wire termination hardware against effective load path demand."""
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

from scripts.phase36_wire_termination_efficiency_sensitivity import (  # noqa: E402
    build_current_wire_termination_efficiency_sensitivity,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase49_wire_termination_hardware_feasibility_screen"


@dataclass(frozen=True)
class WireTerminationHardwareFeasibilityRow:
    hardware_id: str
    status: str
    closes_wire_termination_margin: bool
    required_allowable_load_n: float
    required_mbl_at_eta_0p60_n: float | None
    minimum_breaking_load_n: float | None
    termination_efficiency: float | None
    derate_factor: float | None
    effective_termination_load_n: float | None
    effective_termination_margin_n: float | None
    minimum_breaking_load_margin_n: float | None
    end_anchor_or_pin_allowable_load_n: float | None
    end_anchor_or_pin_margin_n: float | None
    fixture_allowable_load_n: float | None
    fixture_margin_n: float | None
    bend_creep_abrasion_allowable_load_n: float | None
    bend_creep_abrasion_margin_n: float | None
    worst_margin_n: float | None
    traceability_status: str
    evidence_type: str
    source: str
    engineering_note: str


@dataclass(frozen=True)
class WireTerminationHardwareFeasibilityScreen:
    candidate_id: str
    overall_status: str
    required_allowable_load_n: float
    required_mbl_at_eta_0p60_n: float | None
    hardware_count: int
    positive_input_hardware_count: int
    negative_margin_hardware_count: int
    missing_input_hardware_count: int
    traceability_gap_hardware_count: int
    rows: tuple[WireTerminationHardwareFeasibilityRow, ...]


def build_wire_termination_hardware_feasibility_screen(
    termination_sensitivity: Any,
    *,
    termination_hardware: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> WireTerminationHardwareFeasibilityScreen:
    required_load = _attr_float(termination_sensitivity, "required_allowable_load_n")
    if required_load is None:
        raise ValueError("termination_sensitivity must include required_allowable_load_n.")
    required_mbl_eta_060 = _required_mbl_for_efficiency(termination_sensitivity, 0.60)
    if not termination_hardware:
        rows = (_missing_input_row(required_load, required_mbl_eta_060),)
    else:
        rows = tuple(
            _hardware_row(
                row,
                required_allowable_load_n=required_load,
                required_mbl_at_eta_0p60_n=required_mbl_eta_060,
            )
            for row in termination_hardware
        )
    positive_count = sum(1 for row in rows if row.status == "hardware_positive_input_check_only")
    negative_count = sum(1 for row in rows if row.status == "margin_negative")
    missing_count = sum(
        1
        for row in rows
        if row.status
        in {"hardware_selection_and_allowables_missing", "hardware_allowables_missing"}
    )
    traceability_gap_count = sum(
        1 for row in rows if row.status == "hardware_traceability_missing"
    )
    all_positive = rows and positive_count == len(rows)
    return WireTerminationHardwareFeasibilityScreen(
        candidate_id=str(getattr(termination_sensitivity, "candidate_id", "unknown")),
        overall_status=(
            "wire_termination_hardware_inputs_pass_not_fem_signoff"
            if all_positive
            else "wire_termination_hardware_feasibility_not_closed"
        ),
        required_allowable_load_n=required_load,
        required_mbl_at_eta_0p60_n=required_mbl_eta_060,
        hardware_count=len(rows),
        positive_input_hardware_count=positive_count,
        negative_margin_hardware_count=negative_count,
        missing_input_hardware_count=missing_count,
        traceability_gap_hardware_count=traceability_gap_count,
        rows=rows,
    )


def write_wire_termination_hardware_feasibility_screen_package(
    out_dir: Path,
    termination_sensitivity: Any,
    *,
    termination_hardware: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    screen = build_wire_termination_hardware_feasibility_screen(
        termination_sensitivity,
        termination_hardware=termination_hardware,
    )
    return [
        _write_template(out_dir / "wire_termination_hardware_inputs_template.csv"),
        _write_csv(out_dir / "wire_termination_hardware_feasibility_screen.csv", screen),
        _write_json(out_dir / "wire_termination_hardware_feasibility_screen.json", screen),
        _write_markdown(out_dir / "wire_termination_hardware_feasibility_screen.md", screen),
    ]


def build_current_wire_termination_hardware_feasibility_screen() -> (
    WireTerminationHardwareFeasibilityScreen
):
    return build_wire_termination_hardware_feasibility_screen(
        build_current_wire_termination_efficiency_sensitivity(),
        termination_hardware=(),
    )


def _hardware_row(
    hardware: dict[str, Any],
    *,
    required_allowable_load_n: float,
    required_mbl_at_eta_0p60_n: float | None,
) -> WireTerminationHardwareFeasibilityRow:
    hardware_id = str(hardware.get("hardware_id", "")).strip()
    mbl = _dict_float(hardware, "minimum_breaking_load_n")
    efficiency = _dict_float(hardware, "termination_efficiency")
    derate = _dict_float(hardware, "derate_factor")
    if efficiency is not None and (efficiency <= 0.0 or efficiency > 1.0):
        raise ValueError("termination_efficiency must be within (0, 1].")
    if derate is not None and (derate <= 0.0 or derate > 1.0):
        raise ValueError("derate_factor must be within (0, 1].")
    effective_load = _effective_termination_load(mbl, efficiency, derate)
    end_anchor = _dict_float(hardware, "end_anchor_or_pin_allowable_load_n")
    fixture = _dict_float(hardware, "fixture_allowable_load_n")
    bend = _dict_float(hardware, "bend_creep_abrasion_allowable_load_n")
    effective_margin = _margin(effective_load, required_allowable_load_n)
    mbl_margin = _margin(mbl, required_mbl_at_eta_0p60_n)
    end_anchor_margin = _margin(end_anchor, required_allowable_load_n)
    fixture_margin = _margin(fixture, required_allowable_load_n)
    bend_margin = _margin(bend, required_allowable_load_n)
    margins = [
        value
        for value in (
            effective_margin,
            mbl_margin,
            end_anchor_margin,
            fixture_margin,
            bend_margin,
        )
        if value is not None
    ]
    traceability_status = _traceability_status(
        hardware_id=hardware_id,
        evidence_type=str(hardware.get("evidence_type", "")).strip(),
        source=str(hardware.get("source", "")).strip(),
    )
    status = _status(
        margins=(
            effective_margin,
            mbl_margin,
            end_anchor_margin,
            fixture_margin,
            bend_margin,
        ),
        traceability_status=traceability_status,
    )
    return WireTerminationHardwareFeasibilityRow(
        hardware_id=hardware_id or "unnamed_wire_termination_hardware",
        status=status,
        closes_wire_termination_margin=False,
        required_allowable_load_n=required_allowable_load_n,
        required_mbl_at_eta_0p60_n=required_mbl_at_eta_0p60_n,
        minimum_breaking_load_n=mbl,
        termination_efficiency=efficiency,
        derate_factor=derate,
        effective_termination_load_n=effective_load,
        effective_termination_margin_n=effective_margin,
        minimum_breaking_load_margin_n=mbl_margin,
        end_anchor_or_pin_allowable_load_n=end_anchor,
        end_anchor_or_pin_margin_n=end_anchor_margin,
        fixture_allowable_load_n=fixture,
        fixture_margin_n=fixture_margin,
        bend_creep_abrasion_allowable_load_n=bend,
        bend_creep_abrasion_margin_n=bend_margin,
        worst_margin_n=min(margins) if margins else None,
        traceability_status=traceability_status,
        evidence_type=str(hardware.get("evidence_type", "")).strip(),
        source=str(hardware.get("source", "")).strip(),
        engineering_note=(
            "Positive rows are hardware input checks only, not wire termination signoff; "
            "end fitting installation, fatigue, wear, bend-radius details, anchor geometry, and inspection remain open."
        ),
    )


def _missing_input_row(
    required_allowable_load_n: float,
    required_mbl_at_eta_0p60_n: float | None,
) -> WireTerminationHardwareFeasibilityRow:
    return WireTerminationHardwareFeasibilityRow(
        hardware_id="wire_termination_hardware_input_required",
        status="hardware_selection_and_allowables_missing",
        closes_wire_termination_margin=False,
        required_allowable_load_n=required_allowable_load_n,
        required_mbl_at_eta_0p60_n=required_mbl_at_eta_0p60_n,
        minimum_breaking_load_n=None,
        termination_efficiency=None,
        derate_factor=None,
        effective_termination_load_n=None,
        effective_termination_margin_n=None,
        minimum_breaking_load_margin_n=None,
        end_anchor_or_pin_allowable_load_n=None,
        end_anchor_or_pin_margin_n=None,
        fixture_allowable_load_n=None,
        fixture_margin_n=None,
        bend_creep_abrasion_allowable_load_n=None,
        bend_creep_abrasion_margin_n=None,
        worst_margin_n=None,
        traceability_status="hardware_input_missing",
        evidence_type="",
        source="",
        engineering_note=(
            "Select actual selected termination hardware/process and provide MBL, "
            "efficiency, derate, pin/anchor, fixture, bend/creep/abrasion allowables."
        ),
    )


def _status(
    *,
    margins: tuple[float | None, ...],
    traceability_status: str,
) -> str:
    if any(margin is None for margin in margins):
        return "hardware_allowables_missing"
    if traceability_status != "traceable":
        return "hardware_traceability_missing"
    if any(margin < 0.0 for margin in margins):
        return "margin_negative"
    return "hardware_positive_input_check_only"


def _traceability_status(
    *,
    hardware_id: str,
    evidence_type: str,
    source: str,
) -> str:
    if not hardware_id:
        return "hardware_id_missing"
    if not evidence_type:
        return "evidence_type_missing"
    if not source:
        return "source_missing"
    return "traceable"


def _effective_termination_load(
    mbl: float | None,
    efficiency: float | None,
    derate: float | None,
) -> float | None:
    if mbl is None or efficiency is None or derate is None:
        return None
    return mbl * efficiency * derate


def _required_mbl_for_efficiency(sensitivity: Any, efficiency: float) -> float | None:
    for row in getattr(sensitivity, "rows", ()):
        if _attr_float(row, "termination_efficiency") == efficiency:
            return _attr_float(row, "required_minimum_breaking_load_n")
    return None


def _margin(provided: float | None, required: float | None) -> float | None:
    if provided is None or required is None:
        return None
    return provided - required


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


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{float(value):.4f}"


def _write_template(path: Path) -> Path:
    fields = [
        "hardware_id",
        "minimum_breaking_load_n",
        "termination_efficiency",
        "derate_factor",
        "end_anchor_or_pin_allowable_load_n",
        "fixture_allowable_load_n",
        "bend_creep_abrasion_allowable_load_n",
        "evidence_type",
        "source",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow({field: "" for field in fields})
    return path


def _write_csv(path: Path, screen: WireTerminationHardwareFeasibilityScreen) -> Path:
    fields = list(asdict(screen.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in screen.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, screen: WireTerminationHardwareFeasibilityScreen) -> Path:
    path.write_text(
        json.dumps(asdict(screen), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, screen: WireTerminationHardwareFeasibilityScreen) -> Path:
    lines = [
        "# Wire Termination Hardware Feasibility Screen",
        "",
        f"Candidate: `{screen.candidate_id}`",
        f"Overall status: `{screen.overall_status}`",
        "",
        "This is not wire termination signoff.",
        "",
        f"- required allowable load: `{screen.required_allowable_load_n:.4f} N`",
        f"- required MBL at eta 0.60: `{_fmt(screen.required_mbl_at_eta_0p60_n)} N`",
        f"- positive input hardware rows: `{screen.positive_input_hardware_count}`",
        f"- negative margin hardware rows: `{screen.negative_margin_hardware_count}`",
        f"- missing input hardware rows: `{screen.missing_input_hardware_count}`",
        "",
        "| hardware | status | effective load N | effective margin N | MBL margin N | anchor margin N | fixture margin N | bend margin N | traceability |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in screen.rows:
        lines.append(
            f"| `{row.hardware_id}` | `{row.status}` | {_fmt(row.effective_termination_load_n)} | "
            f"{_fmt(row.effective_termination_margin_n)} | "
            f"{_fmt(row.minimum_breaking_load_margin_n)} | "
            f"{_fmt(row.end_anchor_or_pin_margin_n)} | {_fmt(row.fixture_margin_n)} | "
            f"{_fmt(row.bend_creep_abrasion_margin_n)} | `{row.traceability_status}` |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- A positive hardware input row is only an input screen.",
            "- Termination signoff still needs selected process, installation detail, bend radius, pin/anchor geometry, wear/fatigue, and inspection evidence.",
            "- Cable-body tensile allowable is not a termination allowable.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    outputs = write_wire_termination_hardware_feasibility_screen_package(
        args.output_dir,
        build_current_wire_termination_efficiency_sensitivity(),
        termination_hardware=(),
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
