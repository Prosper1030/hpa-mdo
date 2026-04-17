from __future__ import annotations

import json
from pathlib import Path

import pytest

from hpa_mdo.utils.drawing_ready_package import export_drawing_ready_package


def _write(path: Path, text: str = "stub\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_export_drawing_ready_package_writes_manifest_and_readme(tmp_path: Path) -> None:
    output_dir = tmp_path / "output_case"
    _write(output_dir / "spar_jig_shape.step")
    _write(output_dir / "ansys" / "spar_data.csv", "y,t\n0,1\n")
    _write(output_dir / "optimization_summary.txt", "summary\n")
    _write(output_dir / "discrete_layup_final_design.json", '{"overall_status":"pass"}\n')
    _write(output_dir / "spar_flight_shape.step")

    package_dir = export_drawing_ready_package(output_dir)

    manifest_path = package_dir / "drawing_ready_manifest.json"
    readme_path = package_dir / "README.md"
    assert manifest_path.exists()
    assert readme_path.exists()
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

    readme = readme_path.read_text(encoding="utf-8")
    assert "Use `geometry/spar_jig_shape.step` as the primary spar drawing truth." in readme
    assert "Do not use `crossval_report.txt` as drawing truth" in readme


def test_export_drawing_ready_package_requires_core_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "output_case"
    _write(output_dir / "spar_jig_shape.step")
    _write(output_dir / "optimization_summary.txt", "summary\n")

    with pytest.raises(FileNotFoundError, match="Missing required drawing-ready artifacts"):
        export_drawing_ready_package(output_dir)
