from __future__ import annotations

import json
from pathlib import Path

import pytest

from hpa_mdo.utils.drawing_ready_package import export_drawing_ready_package


def _write(path: Path, text: str = "stub\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sample_final_design_json() -> str:
    return """{
  "overall_status": "pass",
  "manufacturing_gates_passed": true,
  "critical_strength_ratio": {"value": 3.6, "spar": "main_spar", "segment_index": 2},
  "critical_failure_index": {"value": 0.12, "spar": "main_spar", "segment_index": 2},
  "spars": {
    "main_spar": {
      "segments": [
        {
          "segment_index": 1,
          "y_start_m": 0.0,
          "y_end_m": 1.5,
          "outer_radius_m": 0.03,
          "stack_notation": "[0/0/+45/-45]_s",
          "equivalent_properties": {"wall_thickness": 0.001}
        }
      ]
    },
    "rear_spar": {
      "segments": [
        {
          "segment_index": 1,
          "y_start_m": 0.0,
          "y_end_m": 1.5,
          "outer_radius_m": 0.01,
          "stack_notation": "[0/+45/-45]_s",
          "equivalent_properties": {"wall_thickness": 0.001}
        }
      ]
    }
  }
}
"""


def test_export_drawing_ready_package_writes_manifest_and_readme(tmp_path: Path) -> None:
    output_dir = tmp_path / "output_case"
    _write(output_dir / "spar_jig_shape.step")
    _write(
        output_dir / "ansys" / "spar_data.csv",
        (
            "Node,Y_Position_m,Main_X_m,Main_Z_m,Main_Outer_Radius_m,Main_Wall_Thickness_m,"
            "Rear_X_m,Rear_Z_m,Rear_Outer_Radius_m,Rear_Wall_Thickness_m,Lift_Per_Span_N_m,"
            "Torque_Per_Span_Nm_m,Main_FZ_N,Rear_FZ_N,Is_Joint,Is_Wire_Attach\n"
            "1,0.0,0.30,0.04,0.03,0.001,0.90,0.03,0.01,0.001,0,0,0,0,1,0\n"
            "2,1.5,0.28,0.07,0.02,0.001,0.80,0.06,0.01,0.001,0,0,0,0,0,1\n"
        ),
    )
    _write(output_dir / "optimization_summary.txt", "summary\n")
    _write(output_dir / "discrete_layup_final_design.json", _sample_final_design_json())
    _write(output_dir / "spar_flight_shape.step")

    package_dir = export_drawing_ready_package(output_dir)

    manifest_path = package_dir / "drawing_ready_manifest.json"
    readme_path = package_dir / "README.md"
    handoff_path = package_dir / "DRAWING_HANDOFF.md"
    checklist_path = package_dir / "DRAWING_CHECKLIST.md"
    station_table_path = package_dir / "data" / "drawing_station_table.csv"
    assert manifest_path.exists()
    assert readme_path.exists()
    assert handoff_path.exists()
    assert checklist_path.exists()
    assert station_table_path.exists()
    assert (package_dir / "geometry" / "spar_jig_shape.step").exists()
    assert (package_dir / "design" / "optimization_summary.txt").exists()
    assert (package_dir / "design" / "discrete_layup_final_design.json").exists()
    assert (package_dir / "data" / "spar_data.csv").exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifact"] == "drawing_ready_baseline_package"
    assert manifest["primary_drawing_truth"]["spar_geometry"] == "geometry/spar_jig_shape.step"
    assert manifest["primary_drawing_truth"]["final_design_basis"] == (
        "design/discrete_layup_final_design.json"
    )
    assert manifest["primary_drawing_truth"]["handoff_note"] == "DRAWING_HANDOFF.md"
    assert manifest["primary_drawing_truth"]["checklist"] == "DRAWING_CHECKLIST.md"
    assert manifest["primary_drawing_truth"]["drafting_station_table"] == (
        "data/drawing_station_table.csv"
    )
    derived = {item["package_relpath"] for item in manifest["derived_artifacts"]}
    assert "DRAWING_CHECKLIST.md" in derived
    assert "data/drawing_station_table.csv" in derived

    readme = readme_path.read_text(encoding="utf-8")
    assert "Use `geometry/spar_jig_shape.step` as the primary spar drawing truth." in readme
    assert "Do not use `crossval_report.txt` as drawing truth" in readme

    handoff = handoff_path.read_text(encoding="utf-8")
    assert "Primary spar drawing geometry: `geometry/spar_jig_shape.step`" in handoff
    assert "Do not use `crossval_report.txt` as drawing truth or validation truth." in handoff

    checklist = checklist_path.read_text(encoding="utf-8")
    assert "`data/drawing_station_table.csv`" in checklist
    assert "Joint stations: 0.000 m" in checklist
    assert "Wire attach stations: 1.500 m" in checklist
    assert "## Main Spar" in checklist

    station_table = station_table_path.read_text(encoding="utf-8")
    assert "Main_Outer_Diameter_mm" in station_table
    assert "60.000" in station_table


def test_export_drawing_ready_package_requires_core_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "output_case"
    _write(output_dir / "spar_jig_shape.step")
    _write(output_dir / "optimization_summary.txt", "summary\n")

    with pytest.raises(FileNotFoundError, match="Missing required drawing-ready artifacts"):
        export_drawing_ready_package(output_dir)
