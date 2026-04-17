"""Build a drawing-ready baseline package from a solved output directory."""

from __future__ import annotations

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
        },
        "artifacts": records,
    }
    (package_dir / "drawing_ready_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_package_readme(package_dir, records)
    _write_drawing_handoff(package_dir)
    return package_dir
