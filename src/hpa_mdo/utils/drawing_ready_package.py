"""Build a drawing-ready baseline package from a solved output directory."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
import shutil


@dataclass(frozen=True)
class DrawingArtifactSpec:
    """One artifact that belongs in the drawing-ready package."""

    source_relpath: str
    package_relpath: str
    role: str
    required: bool
    drawing_use: str
    note: str


@dataclass(frozen=True)
class DerivedDrawingArtifact:
    """One package-native artifact derived from copied design data."""

    package_relpath: str
    role: str
    drawing_use: str


_ARTIFACT_SPECS: tuple[DrawingArtifactSpec, ...] = (
    DrawingArtifactSpec(
        source_relpath="spar_jig_shape.step",
        package_relpath="geometry/spar_jig_shape.step",
        role="primary_spar_jig_geometry",
        required=True,
        drawing_use="Use this as the primary spar geometry for drawing and manufacturing interpretation.",
        note="This is the main structural jig-shape STEP, not a loaded-shape reference.",
    ),
    DrawingArtifactSpec(
        source_relpath="wing_jig.vsp3",
        package_relpath="geometry/wing_jig.vsp3",
        role="primary_jig_oml_geometry",
        required=False,
        drawing_use="Use this as the jig-side OML reference when outer-mold geometry is needed.",
        note="Optional because VSP export may be unavailable on some machines.",
    ),
    DrawingArtifactSpec(
        source_relpath="spar_flight_shape.step",
        package_relpath="references/spar_flight_shape.step",
        role="loaded_shape_reference_geometry",
        required=False,
        drawing_use="Reference only. Use this to understand the predicted loaded shape, not the manufacturing jig.",
        note="Loaded-shape geometry is not the primary drawing truth for manufacturing.",
    ),
    DrawingArtifactSpec(
        source_relpath="wing_cruise.vsp3",
        package_relpath="references/wing_cruise.vsp3",
        role="cruise_oml_reference_geometry",
        required=False,
        drawing_use="Reference only. Use this to inspect the cruise OML target/result relation.",
        note="Cruise OML is a flight-state reference, not the primary jig drawing source.",
    ),
    DrawingArtifactSpec(
        source_relpath="ansys/spar_data.csv",
        package_relpath="data/spar_data.csv",
        role="spanwise_tabular_geometry_contract",
        required=True,
        drawing_use="Use this when you need spanwise station data, tube dimensions, and export-contract tabular values.",
        note="This is the easiest table to consume when turning geometry into drafting dimensions.",
    ),
    DrawingArtifactSpec(
        source_relpath="optimization_summary.txt",
        package_relpath="design/optimization_summary.txt",
        role="human_readable_design_summary",
        required=True,
        drawing_use="Read this first for the top-level structural, layup, and final-design summary.",
        note="This summary now surfaces the discrete final-design verdict.",
    ),
    DrawingArtifactSpec(
        source_relpath="discrete_layup_final_design.json",
        package_relpath="design/discrete_layup_final_design.json",
        role="machine_readable_final_design_verdict",
        required=True,
        drawing_use="Use this as the machine-readable final design verdict and discrete layup basis.",
        note="This is the formal final-design artifact; do not replace it with internal cross-validation reports.",
    ),
    DrawingArtifactSpec(
        source_relpath="mass_budget_report.md",
        package_relpath="design/mass_budget_report.md",
        role="aircraft_mass_budget_reference",
        required=False,
        drawing_use="Reference only. Use this when the drawing package also needs aircraft-level mass/CG context.",
        note="Optional support artifact; not required for spar drawing geometry itself.",
    ),
)

_DERIVED_ARTIFACTS: tuple[DerivedDrawingArtifact, ...] = (
    DerivedDrawingArtifact(
        package_relpath="DRAWING_HANDOFF.md",
        role="drawing_handoff_note",
        drawing_use="Open this first when handing the package to someone who needs the shortest drawing entrypoint.",
    ),
    DerivedDrawingArtifact(
        package_relpath="DRAWING_CHECKLIST.md",
        role="drawing_checklist",
        drawing_use="Use this as the drawing checklist and segment-level layup/dimension summary.",
    ),
    DerivedDrawingArtifact(
        package_relpath="data/drawing_station_table.csv",
        role="drawing_station_table",
        drawing_use="Use this as the drafting-friendly station table with diameters and special stations.",
    ),
)


def _resolve_artifact_records(output_dir: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for spec in _ARTIFACT_SPECS:
        source_path = output_dir / spec.source_relpath
        exists = source_path.exists()
        records.append(
            {
                "role": spec.role,
                "required": spec.required,
                "status": "present" if exists else "missing",
                "source_path": str(source_path.resolve()),
                "package_relpath": spec.package_relpath,
                "drawing_use": spec.drawing_use,
                "note": spec.note,
            }
        )
    return records


def _write_package_readme(package_dir: Path, records: list[dict[str, object]]) -> None:
    primary_lines = []
    reference_lines = []
    for record in records:
        line = (
            f"- `{record['package_relpath']}`: {record['drawing_use']} "
            f"({record['status']})"
        )
        if str(record["role"]).startswith("primary_") or "final_design" in str(record["role"]):
            primary_lines.append(line)
        else:
            reference_lines.append(line)

    lines = [
        "# Drawing-Ready Baseline Package",
        "",
        "This package is the repo's drawing-ready baseline export.",
        "",
        "## Use These First",
        *primary_lines,
        "",
        "## Reference / Support Artifacts",
        *reference_lines,
        "",
        "## Important Boundaries",
        "- Use `geometry/spar_jig_shape.step` as the primary spar drawing truth.",
        "- Use `design/discrete_layup_final_design.json` and `design/optimization_summary.txt` as the final-design basis.",
        "- Use `references/*` only as loaded-shape or cruise-state references.",
        "- Do not use `crossval_report.txt` as drawing truth or validation truth.",
        "",
        "## Machine-Readable Manifest",
        "- `drawing_ready_manifest.json` records the exact source paths and intended role of each artifact.",
        "",
    ]
    (package_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_drawing_handoff(package_dir: Path) -> None:
    lines = [
        "# Drawing Handoff",
        "",
        "Use these files first:",
        "- Primary spar drawing geometry: `geometry/spar_jig_shape.step`",
        "- Final design basis: `design/discrete_layup_final_design.json`",
        "- Human-readable summary: `design/optimization_summary.txt`",
        "- Tabular geometry contract: `data/spar_data.csv`",
        "",
        "Reference only:",
        "- `references/*` are loaded-shape / cruise-state references, not jig drawing truth.",
        "",
        "Do not use `crossval_report.txt` as drawing truth or validation truth.",
        "",
    ]
    (package_dir / "DRAWING_HANDOFF.md").write_text("\n".join(lines), encoding="utf-8")


def _as_float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def _as_int(row: dict[str, str], key: str) -> int:
    return int(float(row[key]))


def _load_station_rows(output_root: Path) -> list[dict[str, str]]:
    csv_path = output_root / "ansys" / "spar_data.csv"
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_final_design(output_root: Path) -> dict[str, object]:
    json_path = output_root / "discrete_layup_final_design.json"
    return json.loads(json_path.read_text(encoding="utf-8"))


def _write_station_table(package_dir: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "Node",
        "Y_Position_m",
        "Main_X_m",
        "Main_Z_m",
        "Main_Outer_Diameter_mm",
        "Main_Wall_Thickness_mm",
        "Rear_X_m",
        "Rear_Z_m",
        "Rear_Outer_Diameter_mm",
        "Rear_Wall_Thickness_mm",
        "Is_Joint",
        "Is_Wire_Attach",
    ]
    out_path = package_dir / "data" / "drawing_station_table.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Node": _as_int(row, "Node"),
                    "Y_Position_m": f"{_as_float(row, 'Y_Position_m'):.6f}",
                    "Main_X_m": f"{_as_float(row, 'Main_X_m'):.6f}",
                    "Main_Z_m": f"{_as_float(row, 'Main_Z_m'):.6f}",
                    "Main_Outer_Diameter_mm": f"{_as_float(row, 'Main_Outer_Radius_m') * 2000.0:.3f}",
                    "Main_Wall_Thickness_mm": f"{_as_float(row, 'Main_Wall_Thickness_m') * 1000.0:.3f}",
                    "Rear_X_m": f"{_as_float(row, 'Rear_X_m'):.6f}",
                    "Rear_Z_m": f"{_as_float(row, 'Rear_Z_m'):.6f}",
                    "Rear_Outer_Diameter_mm": f"{_as_float(row, 'Rear_Outer_Radius_m') * 2000.0:.3f}",
                    "Rear_Wall_Thickness_mm": f"{_as_float(row, 'Rear_Wall_Thickness_m') * 1000.0:.3f}",
                    "Is_Joint": _as_int(row, "Is_Joint"),
                    "Is_Wire_Attach": _as_int(row, "Is_Wire_Attach"),
                }
            )


def _format_segment_schedule(name: str, spar: dict[str, object]) -> list[str]:
    segments = spar.get("segments", [])
    lines = [f"## {name}", "", "| Seg | Span (m) | OD (mm) | Wall (mm) | Layup |", "|---|---|---:|---:|---|"]
    for segment in segments:
        y_start = float(segment["y_start_m"])
        y_end = float(segment["y_end_m"])
        outer_radius_m = float(segment["outer_radius_m"])
        wall_thickness_m = float(segment["equivalent_properties"]["wall_thickness"])
        layup = str(segment["stack_notation"])
        lines.append(
            "| "
            f"{int(segment['segment_index'])} | "
            f"{y_start:.2f} - {y_end:.2f} | "
            f"{outer_radius_m * 2000.0:.1f} | "
            f"{wall_thickness_m * 1000.0:.3f} | "
            f"{layup} |"
        )
    lines.append("")
    return lines


def _write_drawing_checklist(
    package_dir: Path,
    station_rows: list[dict[str, str]],
    final_design: dict[str, object],
) -> None:
    joint_rows = [row for row in station_rows if _as_int(row, "Is_Joint") == 1]
    wire_rows = [row for row in station_rows if _as_int(row, "Is_Wire_Attach") == 1]
    root_row = station_rows[0]
    tip_row = station_rows[-1]
    spars = final_design.get("spars", {})

    lines = [
        "# Drawing Checklist",
        "",
        "Use this checklist when turning the package into drafting work.",
        "",
        "## Open These First",
        "- `geometry/spar_jig_shape.step`",
        "- `design/discrete_layup_final_design.json`",
        "- `design/optimization_summary.txt`",
        "- `data/drawing_station_table.csv`",
        "",
        "## Quick Geometry Snapshot",
        (
            "- Main spar OD: "
            f"{_as_float(root_row, 'Main_Outer_Radius_m') * 2000.0:.1f} mm at root, "
            f"{_as_float(tip_row, 'Main_Outer_Radius_m') * 2000.0:.1f} mm at tip"
        ),
        (
            "- Rear spar OD: "
            f"{_as_float(root_row, 'Rear_Outer_Radius_m') * 2000.0:.1f} mm at root, "
            f"{_as_float(tip_row, 'Rear_Outer_Radius_m') * 2000.0:.1f} mm at tip"
        ),
        (
            "- Main spar wall: "
            f"{_as_float(root_row, 'Main_Wall_Thickness_m') * 1000.0:.3f} mm at root, "
            f"{_as_float(tip_row, 'Main_Wall_Thickness_m') * 1000.0:.3f} mm at tip"
        ),
        "",
        "## Special Stations",
    ]
    if joint_rows:
        joint_positions = ", ".join(f"{_as_float(row, 'Y_Position_m'):.3f} m" for row in joint_rows)
        lines.append(f"- Joint stations: {joint_positions}")
    else:
        lines.append("- Joint stations: none flagged in `spar_data.csv`")
    if wire_rows:
        wire_positions = ", ".join(f"{_as_float(row, 'Y_Position_m'):.3f} m" for row in wire_rows)
        lines.append(f"- Wire attach stations: {wire_positions}")
    else:
        lines.append("- Wire attach stations: none flagged in `spar_data.csv`")

    lines.extend(
        [
            "",
            "## Final Design Gates",
            f"- Overall status: {final_design.get('overall_status', 'unknown')}",
            (
                "- Manufacturing gates passed: "
                f"{final_design.get('manufacturing_gates_passed', 'unknown')}"
            ),
        ]
    )

    critical_sr = final_design.get("critical_strength_ratio", {})
    critical_fi = final_design.get("critical_failure_index", {})
    if critical_sr:
        lines.append(
            "- Critical strength ratio: "
            f"{float(critical_sr.get('value', 0.0)):.3f} "
            f"({critical_sr.get('spar', 'unknown')} seg {critical_sr.get('segment_index', '?')})"
        )
    if critical_fi:
        lines.append(
            "- Critical failure index: "
            f"{float(critical_fi.get('value', 0.0)):.3f} "
            f"({critical_fi.get('spar', 'unknown')} seg {critical_fi.get('segment_index', '?')})"
        )

    lines.extend(["", "## Segment Schedules", ""])
    main_spar = spars.get("main_spar")
    if isinstance(main_spar, dict):
        lines.extend(_format_segment_schedule("Main Spar", main_spar))
    rear_spar = spars.get("rear_spar")
    if isinstance(rear_spar, dict):
        lines.extend(_format_segment_schedule("Rear Spar", rear_spar))

    lines.extend(
        [
            "## Boundaries",
            "",
            "- Use `geometry/spar_jig_shape.step` as the spar drawing truth.",
            "- Use `references/*` only to understand loaded-shape / cruise-state context.",
            "- Do not use `crossval_report.txt` as drawing truth or validation truth.",
            "",
        ]
    )
    (package_dir / "DRAWING_CHECKLIST.md").write_text("\n".join(lines), encoding="utf-8")


def export_drawing_ready_package(
    output_dir: str | Path,
    *,
    package_dir_name: str = "drawing_ready_package",
) -> Path:
    """Copy the drawing-ready artifact set into a dedicated package directory."""
    output_root = Path(output_dir).expanduser().resolve()
    if not output_root.exists():
        raise FileNotFoundError(f"Output directory does not exist: {output_root}")

    records = _resolve_artifact_records(output_root)
    missing_required = [r for r in records if r["required"] and r["status"] != "present"]
    if missing_required:
        missing_list = ", ".join(str(r["source_path"]) for r in missing_required)
        raise FileNotFoundError(f"Missing required drawing-ready artifacts: {missing_list}")
    station_rows = _load_station_rows(output_root)
    final_design = _load_final_design(output_root)

    package_dir = output_root / package_dir_name
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    for record in records:
        if record["status"] != "present":
            continue
        source_path = Path(str(record["source_path"]))
        dest_path = package_dir / str(record["package_relpath"])
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)

    manifest = {
        "artifact": "drawing_ready_baseline_package",
        "output_root": str(output_root),
        "package_dir": str(package_dir),
        "primary_drawing_truth": {
            "spar_geometry": "geometry/spar_jig_shape.step",
            "final_design_basis": "design/discrete_layup_final_design.json",
            "human_summary": "design/optimization_summary.txt",
            "tabular_geometry": "data/spar_data.csv",
            "handoff_note": "DRAWING_HANDOFF.md",
            "checklist": "DRAWING_CHECKLIST.md",
            "drafting_station_table": "data/drawing_station_table.csv",
        },
        "artifacts": records,
        "derived_artifacts": [
            {
                "package_relpath": artifact.package_relpath,
                "role": artifact.role,
                "drawing_use": artifact.drawing_use,
            }
            for artifact in _DERIVED_ARTIFACTS
        ],
    }
    (package_dir / "drawing_ready_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_package_readme(package_dir, records)
    _write_drawing_handoff(package_dir)
    _write_station_table(package_dir, station_rows)
    _write_drawing_checklist(package_dir, station_rows, final_design)
    return package_dir
