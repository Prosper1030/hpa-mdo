from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_full_polar_builder_dry_run_creates_archive(tmp_path: Path) -> None:
    screening_dir = tmp_path / "screening"
    screening_dir.mkdir()
    coordinate_dir = screening_dir / "coordinates"
    coordinate_dir.mkdir()
    coordinate_path = coordinate_dir / "cst_tip_demo.dat"
    coordinate_path.write_text("cst_tip_demo\n1.0 0.0\n0.0 0.0\n1.0 0.0\n", encoding="utf-8")
    database_payload = {
        "records": [
            {
                "airfoil_id": "cst_tip_demo",
                "name": "cst_tip_demo",
                "source": f"offline_cst_zone_nsga_xfoil_database_builder_v1:{coordinate_path}",
                "source_quality": "cst_xfoil_mission_grade_candidate",
                "zone_hint": "tip",
                "thickness_ratio": 0.12,
                "max_camber": 0.03,
                "alpha_L0_deg": -2.0,
                "cl_alpha_per_rad": 6.0,
                "cm_design": -0.04,
                "safe_clmax": 1.2,
                "usable_clmax": 1.4,
                "polar_points": [],
                "notes": "unit test screening record",
                "coordinate_path": str(coordinate_path),
            }
        ]
    }
    (screening_dir / "airfoil_database.json").write_text(
        json.dumps(database_payload),
        encoding="utf-8",
    )
    (screening_dir / "per_zone_top_k.csv").write_text(
        "zone_name,airfoil_id,rank_in_zone,source_quality\n"
        "tip,cst_tip_demo,1,cst_xfoil_mission_grade_candidate\n",
        encoding="utf-8",
    )
    envelope_payload = {
        "zone_envelope": [
            {
                "zone_name": "tip",
                "re_min": 250000.0,
                "re_p50": 300000.0,
                "re_max": 350000.0,
                "cl_min": 0.2,
                "cl_p50": 0.5,
                "cl_p90": 0.8,
                "cl_max": 0.8,
                "max_fourier_target_cl": 0.8,
            }
        ]
    }
    envelope_path = screening_dir / "zone_envelope.json"
    envelope_path.write_text(json.dumps(envelope_payload), encoding="utf-8")
    output_dir = tmp_path / "full_polar"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_full_polar_airfoil_db.py",
            "--screening-output-dir",
            str(screening_dir),
            "--zone-envelope-json",
            str(envelope_path),
            "--output-dir",
            str(output_dir),
            "--dry-run",
            "--top-k-per-zone",
            "1",
            "--pareto-per-zone",
            "0",
            "--roughness-modes",
            "clean",
            "--alpha-step-deg",
            "1.0",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert (output_dir / "airfoil_records.json").is_file()
    assert (output_dir / "airfoil_records.csv").is_file()
    assert (output_dir / "polar_points.csv").is_file()
    assert (output_dir / "full_polar_build_report.json").is_file()
    assert (output_dir / "quality_report.csv").is_file()
    assert "full_polar_build_report" in result.stdout

    report = json.loads((output_dir / "full_polar_build_report.json").read_text(encoding="utf-8"))
    assert report["record_count"] == 7
    assert report["source_quality_counts"]["full_polar_candidate_not_mission_grade"] == 7
    assert report["records"]["cst_tip_demo"]["mission_grade_allowed"] is False
    assert report["records"]["fx76mp140"]["screening_quality"] == "seed_reference_pending_full_polar"
    assert "prestall" in (output_dir / "polar_points.csv").read_text(encoding="utf-8")
