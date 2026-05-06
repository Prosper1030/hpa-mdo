from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import export_phase7_sidecar_vsp as exporter


def test_phase7_sidecar_export_preserves_loaded_sections_and_assignment(tmp_path: Path) -> None:
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
                "0.0 0.0 0.0 1.2 2.0",
                "AFILE",
                str(root_dat),
                "SECTION",
                "0.0 2.5 0.2 1.0 1.0",
                "AFILE",
                str(root_dat),
                "SECTION",
                "0.0 5.0 0.7 0.7 0.0",
                "AFILE",
                str(tip_dat),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = exporter.export_case(
        case_name="demo_case",
        definition={
            "policy_id": "A",
            "assignment": "root:rootfoil|mid1:rootfoil|mid2:tipfoil|tip:tipfoil",
            "source_avl": source_avl,
            "source_sidecar_report": tmp_path / "report.csv",
        },
        output_root=tmp_path / "exports",
        phase7_rows={
            "A": {
                "repaired_quality_summary": (
                    "root:root_quality;mid1:mid1_quality;mid2:mid2_quality;tip:tip_quality"
                )
            }
        },
        airfoil_paths={"rootfoil": root_dat, "tipfoil": tip_dat},
        build_vsp=False,
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
