#!/usr/bin/env python3
"""Build a full-aircraft wire/rigging BOM from Phase 9 representative designs."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB, load_config  # noqa: E402
from scripts.vendor_tube_catalog_phase9d import (  # noqa: E402
    VendorDesignPoint,
    load_representative_designs,
)


DEFAULT_PARETO_SUMMARY = (
    REPO_ROOT / "output" / "pareto_front_phase9c" / "pareto_front_phase9c_summary.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "full_wire_rigging_system_phase9e"
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "full_wire_rigging_system_phase9e_report.md"


@dataclass(frozen=True)
class AircraftWireRow:
    design_role: str
    design_label: str
    side: str
    identifier: str
    attach_label: str
    attach_y_m: float
    loaded_angle_deg: float
    L_flight_m: float
    delta_L_m: float
    L_cut_m: float
    stretch_percent: float
    tension_force_n: float
    allowable_tension_n: float | None
    tension_margin_n: float | None
    tension_utilization: float | None
    cable_material: str
    cable_diameter_mm: float
    cable_mass_cut_kg: float
    cable_mass_flight_kg: float


@dataclass(frozen=True)
class RiggingBomLine:
    design_role: str
    line_kind: str
    item_code: str
    quantity: int
    length_each_m: float | None
    total_length_m: float | None
    total_mass_kg: float | None
    note: str


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return float(text)


def _cable_area_m2(diameter_m: float) -> float:
    radius_m = 0.5 * float(diameter_m)
    return math.pi * radius_m * radius_m


def _load_wire_records_for_design(
    design: VendorDesignPoint,
) -> tuple[dict[str, object], list[dict[str, object]], Path]:
    summary_path = Path(design.summary_json_path).expanduser().resolve()
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    config_path = Path(str(summary_payload["config"])).expanduser().resolve()
    artifacts = summary_payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError(f"Summary has no artifacts section: {summary_path}")
    wire_json_path = artifacts.get("wire_rigging_json")
    if not wire_json_path:
        raise ValueError(f"Summary has no wire_rigging_json artifact: {summary_path}")
    wire_payload = json.loads(Path(str(wire_json_path)).read_text(encoding="utf-8"))
    records = wire_payload.get("wire_rigging")
    if not isinstance(records, list):
        raise ValueError(f"Wire payload has no wire_rigging list: {wire_json_path}")
    return summary_payload, records, config_path


def build_full_aircraft_wire_rows(
    *,
    design: VendorDesignPoint,
    positive_half_records: Iterable[dict[str, object]],
    cable_material: str,
    cable_diameter_m: float,
    cable_density_kgpm3: float,
) -> tuple[AircraftWireRow, ...]:
    area_m2 = _cable_area_m2(cable_diameter_m)
    mass_per_meter_kg = cable_density_kgpm3 * area_m2
    rows: list[AircraftWireRow] = []
    for record in positive_half_records:
        loaded_attach = record["attach_point_loaded_m"]
        anchor = record["anchor_point_m"]
        dy = abs(float(loaded_attach[1]) - float(anchor[1]))
        dz = abs(float(loaded_attach[2]) - float(anchor[2]))
        loaded_angle_deg = math.degrees(math.atan2(dz, max(dy, 1.0e-12)))
        L_cut_m = float(record["L_cut_m"])
        L_flight_m = float(record["L_flight_m"])
        delta_L_m = float(record["delta_L_m"])
        allowable = _safe_float(record.get("allowable_tension_n"))
        tension = float(record["tension_force_n"])
        tension_utilization = None if allowable in (None, 0.0) else float(tension / allowable)
        stretch_percent = 100.0 * delta_L_m / max(L_cut_m, 1.0e-12)
        for side_sign, side_name in ((+1.0, "starboard"), (-1.0, "port")):
            rows.append(
                AircraftWireRow(
                    design_role=design.role,
                    design_label=design.label,
                    side=side_name,
                    identifier=str(record["identifier"]),
                    attach_label=str(record.get("attach_label") or ""),
                    attach_y_m=side_sign * float(record["attach_y_m"]),
                    loaded_angle_deg=float(loaded_angle_deg),
                    L_flight_m=L_flight_m,
                    delta_L_m=delta_L_m,
                    L_cut_m=L_cut_m,
                    stretch_percent=float(stretch_percent),
                    tension_force_n=tension,
                    allowable_tension_n=allowable,
                    tension_margin_n=_safe_float(record.get("tension_margin_n")),
                    tension_utilization=tension_utilization,
                    cable_material=cable_material,
                    cable_diameter_mm=float(cable_diameter_m) * 1000.0,
                    cable_mass_cut_kg=float(mass_per_meter_kg * L_cut_m),
                    cable_mass_flight_kg=float(mass_per_meter_kg * L_flight_m),
                )
            )
    return tuple(rows)


def build_rigging_bom(
    *,
    design: VendorDesignPoint,
    positive_half_records: Iterable[dict[str, object]],
    cable_material: str,
    cable_diameter_m: float,
    cable_density_kgpm3: float,
) -> tuple[RiggingBomLine, ...]:
    area_m2 = _cable_area_m2(cable_diameter_m)
    mass_per_meter_kg = cable_density_kgpm3 * area_m2
    lines: list[RiggingBomLine] = []
    pair_count = 0
    for record in positive_half_records:
        pair_count += 1
        L_cut_m = float(record["L_cut_m"])
        total_length_m = 2.0 * L_cut_m
        lines.append(
            RiggingBomLine(
                design_role=design.role,
                line_kind="cable",
                item_code=f"{cable_material}_{float(cable_diameter_m) * 1000.0:.1f}mm_{record['identifier']}",
                quantity=2,
                length_each_m=L_cut_m,
                total_length_m=float(total_length_m),
                total_mass_kg=float(total_length_m * mass_per_meter_kg),
                note=f"Mirror pair for {record['identifier']} / {record.get('attach_label') or 'no-label'}",
            )
        )
    for item_code, note in (
        ("wing_fitting_placeholder", "Count only; mass/cost TBD in later hardware catalog."),
        ("fuselage_anchor_placeholder", "Count only; mass/cost TBD in later hardware catalog."),
        ("turnbuckle_placeholder", "Count only; mass/cost TBD in later hardware catalog."),
    ):
        lines.append(
            RiggingBomLine(
                design_role=design.role,
                line_kind="hardware_placeholder",
                item_code=item_code,
                quantity=2 * pair_count,
                length_each_m=None,
                total_length_m=None,
                total_mass_kg=None,
                note=note,
            )
        )
    return tuple(lines)


def summarize_design(
    *,
    design: VendorDesignPoint,
    wire_rows: Iterable[AircraftWireRow],
) -> dict[str, object]:
    rows = list(wire_rows)
    cable_cut_mass_kg = sum(row.cable_mass_cut_kg for row in rows)
    cable_cut_length_m = sum(row.L_cut_m for row in rows)
    cable_flight_length_m = sum(row.L_flight_m for row in rows)
    elastic_extension_m = sum(row.delta_L_m for row in rows)
    max_tension_row = max(rows, key=lambda item: item.tension_force_n)
    return {
        "role": design.role,
        "label": design.label,
        "layout": design.layout,
        "dihedral_multiplier": design.dihedral_multiplier,
        "wire_count_full_aircraft": len(rows),
        "cable_cut_length_total_m": float(cable_cut_length_m),
        "cable_flight_length_total_m": float(cable_flight_length_m),
        "elastic_extension_total_m": float(elastic_extension_m),
        "cable_cut_mass_total_kg": float(cable_cut_mass_kg),
        "max_tension_n": float(max_tension_row.tension_force_n),
        "max_utilization_pct": (
            None
            if max_tension_row.tension_utilization is None
            else float(100.0 * max_tension_row.tension_utilization)
        ),
        "min_margin_n": min(
            (
                float(row.tension_margin_n)
                for row in rows
                if row.tension_margin_n is not None
            ),
            default=None,
        ),
    }


def _write_wire_schedule_csv(path: Path, rows: Iterable[AircraftWireRow]) -> None:
    fieldnames = [
        "design_role",
        "design_label",
        "side",
        "identifier",
        "attach_label",
        "attach_y_m",
        "loaded_angle_deg",
        "L_flight_m",
        "delta_L_m",
        "L_cut_m",
        "stretch_percent",
        "tension_force_n",
        "allowable_tension_n",
        "tension_margin_n",
        "tension_utilization",
        "cable_material",
        "cable_diameter_mm",
        "cable_mass_cut_kg",
        "cable_mass_flight_kg",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _write_bom_csv(path: Path, rows: Iterable[RiggingBomLine]) -> None:
    fieldnames = [
        "design_role",
        "line_kind",
        "item_code",
        "quantity",
        "length_each_m",
        "total_length_m",
        "total_mass_kg",
        "note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def build_report(
    *,
    design_summaries: Iterable[dict[str, object]],
    bom_lines: Iterable[RiggingBomLine],
) -> str:
    summaries = list(design_summaries)
    bom = list(bom_lines)
    lines: list[str] = []
    lines.append("# Phase 9e Full Wire/Rigging System Report")
    lines.append("")
    lines.append("## Scope")
    lines.append(
        "- Phase 9e expands the existing positive-half-span `lift_wire_rigging.json` artifact into a mirrored full-aircraft cable schedule plus a rigging BOM."
    )
    lines.append(
        "- Cable rows now include full-aircraft quantity, total cut length, cable mass, loaded angle, elastic extension, and tension utilization."
    )
    lines.append(
        "- Hardware lines remain count-only placeholders in this phase; they are included so procurement and assembly planning can start before a detailed fitting catalog exists."
    )
    lines.append("")
    lines.append("## Design Summary")
    lines.append("")
    lines.append(
        "| Role | Layout | Mult | Wires (aircraft) | Cut Length (m) | Cable Mass (kg) | Max Tension (N) | Max Util (%) | Min Margin (N) |"
    )
    lines.append(
        "|------|--------|------|------------------|----------------|-----------------|-----------------|--------------|----------------|"
    )
    for item in summaries:
        max_util = item["max_utilization_pct"]
        min_margin = item["min_margin_n"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item["role"]),
                    str(item["layout"]),
                    f"{float(item['dihedral_multiplier']):.3f}",
                    str(int(item["wire_count_full_aircraft"])),
                    f"{float(item['cable_cut_length_total_m']):.3f}",
                    f"{float(item['cable_cut_mass_total_kg']):.4f}",
                    f"{float(item['max_tension_n']):.1f}",
                    "n/a" if max_util is None else f"{float(max_util):.2f}",
                    "n/a" if min_margin is None else f"{float(min_margin):.1f}",
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## BOM Highlights")
    lines.append("")
    lines.append(
        "| Role | Item | Qty | Length Each (m) | Total Length (m) | Total Mass (kg) | Note |"
    )
    lines.append(
        "|------|------|-----|-----------------|------------------|-----------------|------|"
    )
    for row in bom:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.design_role,
                    row.item_code,
                    str(row.quantity),
                    "n/a" if row.length_each_m is None else f"{row.length_each_m:.3f}",
                    "n/a" if row.total_length_m is None else f"{row.total_length_m:.3f}",
                    "n/a" if row.total_mass_kg is None else f"{row.total_mass_kg:.4f}",
                    row.note,
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if summaries:
        lightest = min(summaries, key=lambda item: float(item["cable_cut_mass_total_kg"]))
        heaviest = max(summaries, key=lambda item: float(item["cable_cut_mass_total_kg"]))
        highest_tension = max(summaries, key=lambda item: float(item["max_tension_n"]))
        lines.append(
            f"- The lightest cable system is `{lightest['role']}` at {float(lightest['cable_cut_mass_total_kg']):.4f} kg for the full aircraft."
        )
        lines.append(
            f"- The heaviest cable system is `{heaviest['role']}` at {float(heaviest['cable_cut_mass_total_kg']):.4f} kg, which is still much smaller than the tube discretization penalties found in 9d."
        )
        lines.append(
            f"- The highest single-wire tension is on `{highest_tension['role']}` at {float(highest_tension['max_tension_n']):.1f} N."
        )
    lines.append(
        "- Dual-wire layouts increase assembly complexity mainly through wire count and heterogeneous cut lengths, not through cable mass."
    )
    lines.append(
        "- Because the cable mass stays sub-kilogram across all representative designs, future ranking changes will be driven more by tube catalog discreteness and aerodynamic gates than by cable weight."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Phase 9e full wire/rigging system outputs."
    )
    parser.add_argument("--pareto-summary", default=str(DEFAULT_PARETO_SUMMARY))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    pareto_summary_path = Path(args.pareto_summary).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    report_path = Path(args.report_path).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    materials_db = MaterialDB()
    representative_designs = load_representative_designs(pareto_summary_path)

    wire_rows: list[AircraftWireRow] = []
    bom_lines: list[RiggingBomLine] = []
    design_summaries: list[dict[str, object]] = []

    for design in representative_designs:
        _, positive_half_records, config_path = _load_wire_records_for_design(design)
        cfg = load_config(config_path)
        cable_material = str(cfg.lift_wires.cable_material)
        cable_diameter_m = float(cfg.lift_wires.cable_diameter)
        density = float(materials_db.get(cable_material).density)
        design_wire_rows = build_full_aircraft_wire_rows(
            design=design,
            positive_half_records=positive_half_records,
            cable_material=cable_material,
            cable_diameter_m=cable_diameter_m,
            cable_density_kgpm3=density,
        )
        design_bom_lines = build_rigging_bom(
            design=design,
            positive_half_records=positive_half_records,
            cable_material=cable_material,
            cable_diameter_m=cable_diameter_m,
            cable_density_kgpm3=density,
        )
        wire_rows.extend(design_wire_rows)
        bom_lines.extend(design_bom_lines)
        design_summaries.append(summarize_design(design=design, wire_rows=design_wire_rows))

    wire_schedule_path = output_dir / "full_wire_rigging_phase9e_wire_schedule.csv"
    bom_path = output_dir / "full_wire_rigging_phase9e_bom.csv"
    summary_path = output_dir / "full_wire_rigging_phase9e_summary.json"

    _write_wire_schedule_csv(wire_schedule_path, wire_rows)
    _write_bom_csv(bom_path, bom_lines)
    summary_path.write_text(
        json.dumps(
            {
                "pareto_summary_path": str(pareto_summary_path),
                "design_summaries": design_summaries,
                "wire_rows": [asdict(row) for row in wire_rows],
                "bom_lines": [asdict(row) for row in bom_lines],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        build_report(
            design_summaries=design_summaries,
            bom_lines=bom_lines,
        ),
        encoding="utf-8",
    )

    print(f"Wrote wire schedule : {wire_schedule_path}")
    print(f"Wrote BOM           : {bom_path}")
    print(f"Wrote summary       : {summary_path}")
    print(f"Wrote report        : {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
