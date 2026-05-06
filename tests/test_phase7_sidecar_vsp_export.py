from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import export_phase7_sidecar_vsp as exporter


def _write_demo_source(
    tmp_path: Path,
    *,
    chords: tuple[float, float, float] = (1.2, 1.0, 0.7),
) -> tuple[Path, Path, Path]:
    source_avl = tmp_path / "source.avl"
    root_dat = tmp_path / "root.dat"
    tip_dat = tmp_path / "tip.dat"
    root_dat.write_text("root\n1 0\n0 0\n1 0\n", encoding="utf-8")
    tip_dat.write_text("tip\n1 0\n0 0\n1 0\n", encoding="utf-8")
    source_avl.write_text(
        "\n".join(
            [
                "demo",
                "#Mach",
                "0.0",
                "#IYsym  iZsym  Zsym",
                "1 0 0",
                "#Sref  Cref  Bref",
                "10.0 1.0 10.0",
                "#Xref  Yref  Zref",
                "0.25 0.0 0.0",
                "#CDp",
                "0.0",
                "SURFACE",
                "Wing",
                "16 1 24 1",
                "SECTION",
                f"0.0 0.0 0.0 {chords[0]} 2.0",
                "AFILE",
                str(root_dat),
                "SECTION",
                f"0.0 2.5 0.2 {chords[1]} 1.0",
                "AFILE",
                str(root_dat),
                "SECTION",
                f"0.0 5.0 0.7 {chords[2]} 0.0",
                "AFILE",
                str(tip_dat),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return source_avl, root_dat, tip_dat


def _demo_definition(source_avl: Path, tmp_path: Path) -> dict[str, object]:
    return {
        "policy_id": "A",
        "assignment": "root:rootfoil|mid1:rootfoil|mid2:tipfoil|tip:tipfoil",
        "source_avl": source_avl,
        "source_sidecar_report": tmp_path / "report.csv",
    }


def _demo_phase7_rows() -> dict[str, dict[str, str]]:
    return {
        "A": {
            "repaired_quality_summary": (
                "root:root_quality;mid1:mid1_quality;mid2:mid2_quality;tip:tip_quality"
            )
        }
    }


def test_phase7_sidecar_export_preserves_loaded_sections_and_assignment(tmp_path: Path) -> None:
    source_avl, root_dat, tip_dat = _write_demo_source(tmp_path)

    report = exporter.export_case(
        case_name="demo_case",
        definition=_demo_definition(source_avl, tmp_path),
        output_root=tmp_path / "exports",
        phase7_rows=_demo_phase7_rows(),
        airfoil_paths={"rootfoil": root_dat, "tipfoil": tip_dat},
        build_vsp=False,
        export_mode="avl_parity",
    )

    case_dir = Path(report["case_dir"])
    assert (case_dir / "demo_case.avl").is_file()
    assert (case_dir / "demo_case.vspscript").is_file()
    assert report["vsp_status"] == "vsp_skipped"
    with (case_dir / "section_table.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert float(rows[-1]["z_m"]) == 0.7
    assert rows[0]["airfoil_id"] == "rootfoil"
    assert rows[-1]["airfoil_id"] == "tipfoil"
    manifest = json.loads((case_dir / "geometry_manifest.json").read_text(encoding="utf-8"))
    assert manifest["loaded_tip_z_m"] == 0.7
    assert manifest["parity_checks"][-1]["name"] == "loaded_z_nonzero"
    assert {check["status"] for check in manifest["parity_checks"]} <= {"pass", "warn"}


def test_production_inspection_export_has_monotone_chord_and_cruise_metadata(tmp_path: Path) -> None:
    source_avl, root_dat, tip_dat = _write_demo_source(tmp_path, chords=(1.2, 0.75, 0.95))

    report = exporter.export_case(
        case_name="demo_case",
        definition=_demo_definition(source_avl, tmp_path),
        output_root=tmp_path / "exports",
        phase7_rows=_demo_phase7_rows(),
        airfoil_paths={"rootfoil": root_dat, "tipfoil": tip_dat},
        build_vsp=False,
        export_mode="production_inspection",
        incidence_offset_deg=4.25,
    )

    case_dir = Path(report["case_dir"])
    assert case_dir.parent.name == "production_inspection"
    with (case_dir / "section_table.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    chords = [float(row["chord_m"]) for row in rows]
    twists = [float(row["twist_deg"]) for row in rows]
    assert all(right <= left for left, right in zip(chords[:-1], chords[1:]))
    assert twists == [6.25, 5.25, 4.25]

    manifest = json.loads((case_dir / "geometry_manifest.json").read_text(encoding="utf-8"))
    assert manifest["export_mode"] == "production_inspection"
    assert manifest["chord_mode"] == "monotone_normalized"
    assert manifest["incidence_mode"] == "cruise_alpha_zero"
    assert manifest["vsp_alpha0_is_cruise"] is True
    assert manifest["chord_monotonicity_enforced"] is True
    assert manifest["source_geometry"] == "sidecar_avl_loaded_shape"
    assert manifest["export_mode_warning"].startswith("This file is cruise-normalized")
    assert abs(manifest["Sref"] - manifest["computed_wing_area_m2"]) <= 0.05
    assert manifest["loaded_tip_z_m"] == 0.7
    report_text = (case_dir / "export_report.md").read_text(encoding="utf-8")
    assert (
        "This file is cruise-normalized and monotone-chord. Use this for "
        "VSP/SolidWorks/fairing/manual geometry inspection."
    ) in report_text


def test_avl_parity_export_preserves_original_section_table_and_metadata(tmp_path: Path) -> None:
    source_avl, root_dat, tip_dat = _write_demo_source(tmp_path)

    report = exporter.export_case(
        case_name="demo_case",
        definition=_demo_definition(source_avl, tmp_path),
        output_root=tmp_path / "exports",
        phase7_rows=_demo_phase7_rows(),
        airfoil_paths={"rootfoil": root_dat, "tipfoil": tip_dat},
        build_vsp=False,
        export_mode="avl_parity",
    )

    case_dir = Path(report["case_dir"])
    assert case_dir.parent.name == "avl_parity"
    with (case_dir / "section_table.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [float(row["chord_m"]) for row in rows] == [1.2, 1.0, 0.7]
    assert [float(row["twist_deg"]) for row in rows] == [2.0, 1.0, 0.0]

    manifest = json.loads((case_dir / "geometry_manifest.json").read_text(encoding="utf-8"))
    assert manifest["export_mode"] == "avl_parity"
    assert manifest["chord_mode"] == "original_inverse_chord"
    assert manifest["incidence_mode"] == "avl_body_axis"
    assert manifest["vsp_alpha0_is_cruise"] is False
    assert manifest["chord_monotonicity_enforced"] is False
    assert manifest["export_mode_warning"].startswith("This file is for AVL/VSP parity only")
    assert manifest["loaded_tip_z_m"] == 0.7
    report_text = (case_dir / "export_report.md").read_text(encoding="utf-8")
    assert (
        "This file is for AVL/VSP parity only. Alpha=0 is not necessarily cruise. "
        "Do not use directly for production layout."
    ) in report_text
